"""chat/serve.py — start the local Chat-LLM inference server behind the fixed API.

This is the "efficient reference" serving layer for the chat runner (architecture.md §4.1, §6.1,
§6.2c). It launches a llama.cpp-backed, **OpenAI-compatible** HTTP server for the downloaded GGUF
weights and — critically — does not declare itself ready until the model is **loaded and warmed**
(a warm-up inference), so the day/night scheduler can treat "model warm" (not merely "process
started") as the readiness gate and users never eat the cold-start latency (architecture.md §4.1).

Contract exposed to callers (the Orchestrator, F-002):
    POST http://127.0.0.1:8080/v1/chat/completions   (OpenAI Chat Completions)
    GET  http://127.0.0.1:8080/v1/models

Nothing outside chat/ imports this runner's deps — isolation per architecture.md §6.2c. Run it
inside this runner's own env:

    chat/.venv/bin/python chat/serve.py

Tunables (env vars, all optional — defaults sized for the 48 GB Quadro RTX 8000 / Turing sm_75):
    CHAT_MODEL_PATH   path to the .gguf                    (default: the Q6_K in chat/models/)
    CHAT_HOST         bind host                            (default: 127.0.0.1)
    CHAT_PORT         bind port                            (default: 8080)
    CHAT_N_CTX        context window (tokens)              (default: 16384)
    CHAT_N_GPU_LAYERS layers offloaded to GPU, -1 = all    (default: -1, full offload)
    CHAT_N_BATCH      prompt batch size                    (default: 512)
    CHAT_N_PARALLEL   concurrent request slots             (default: 2)
    CHAT_FLASH_ATTN   flash-attention 1/0 (Turing-capable) (default: 1)
    CHAT_CHAT_FORMAT  llama.cpp chat template name         (default: auto from GGUF metadata)
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

log = logging.getLogger("chat.serve")

CHAT_DIR = Path(__file__).parent
DEFAULT_MODEL = (
    CHAT_DIR / "models" / "Qwen3.5-35B-A3B-Uncensored-HauhauCS-Aggressive-Q6_K.gguf"
)
READY_FILE = CHAT_DIR / ".runner_ready"  # touched once the model is warm; removed on shutdown


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _resolve_model_path() -> Path:
    p = Path(_env("CHAT_MODEL_PATH", str(DEFAULT_MODEL)))
    if not p.exists():
        raise SystemExit(
            f"Model weights not found at {p}. Run chat/download_model.py first, or set "
            f"CHAT_MODEL_PATH to an existing .gguf."
        )
    return p


def _build_server_cmd(model: Path, host: str, port: int) -> list[str]:
    """Assemble the llama_cpp.server launch command from the tuned defaults / env overrides."""
    cmd = [
        sys.executable, "-m", "llama_cpp.server",
        "--model", str(model),
        "--host", host,
        "--port", str(port),
        "--n_ctx", _env("CHAT_N_CTX", "16384"),
        "--n_gpu_layers", _env("CHAT_N_GPU_LAYERS", "-1"),  # -1 = offload every layer to the GPU
        "--n_batch", _env("CHAT_N_BATCH", "512"),
        "--n_threads", _env("CHAT_N_THREADS", str(os.cpu_count() or 8)),
    ]
    # Continuous batching across a few slots so concurrent turns don't serialize.
    n_parallel = _env("CHAT_N_PARALLEL", "2")
    cmd += ["--n_threads_batch", _env("CHAT_N_THREADS_BATCH", str(os.cpu_count() or 8))]
    # llama-cpp-python exposes flash-attention + parallel slots via these settings.
    if _env("CHAT_FLASH_ATTN", "1") == "1":
        cmd += ["--flash_attn", "true"]
    chat_format = os.environ.get("CHAT_CHAT_FORMAT")
    if chat_format:
        cmd += ["--chat_format", chat_format]
    # This Qwen3.5 GGUF is a *reasoning* model: its chat template opens a <think> block at every
    # generation prompt, so by default the model emits a long chain-of-thought ("Thinking
    # Process: …") that eats the token budget and seconds of latency before the actual reply.
    # For a real-time texting companion we want direct, in-character replies, so we disable
    # thinking at model-load time (the template then injects an empty <think></think> and the model
    # answers straight away). Set CHAT_ENABLE_THINKING=1 to turn reasoning back on if ever needed.
    if _env("CHAT_ENABLE_THINKING", "0") != "1":
        cmd += ["--chat_template_kwargs", '{"enable_thinking": false}']
    # cache_prompt keeps the persona/system prefix hot across a user's turns.
    cmd += ["--cache", "true"]
    # n_parallel is passed through the server's model settings when supported.
    os.environ.setdefault("N_PARALLEL", n_parallel)
    return cmd


def _wait_until_loaded(base_url: str, proc: subprocess.Popen, timeout_s: float = 900.0) -> None:
    """Poll /v1/models until the server reports the model is loaded (or the process dies)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"llama_cpp.server exited early with code {proc.returncode}")
        try:
            r = httpx.get(f"{base_url}/v1/models", timeout=5.0)
            if r.status_code == 200 and r.json().get("data"):
                return
        except httpx.HTTPError:
            pass
        time.sleep(2.0)
    raise SystemExit("Timed out waiting for the model to load.")


def _warm_up(base_url: str) -> float:
    """Fire one tiny inference so CUDA kernels are compiled/primed before we accept traffic.

    Returns the warm-up latency in seconds. This is the readiness gate of architecture.md §4.1:
    only after this succeeds is the runner considered "warm" and safe to serve.
    """
    t0 = time.monotonic()
    r = httpx.post(
        f"{base_url}/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 8,
            "temperature": 0.0,
        },
        timeout=300.0,
    )
    r.raise_for_status()
    return time.monotonic() - t0


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("CHAT_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    model = _resolve_model_path()
    host = _env("CHAT_HOST", "127.0.0.1")
    port = int(_env("CHAT_PORT", "8080"))
    base_url = f"http://{host}:{port}"

    cmd = _build_server_cmd(model, host, port)
    log.info("Starting Chat-LLM server: %s", " ".join(cmd))
    log.info("Model: %s (%.1f GB)", model.name, model.stat().st_size / 1e9)

    if READY_FILE.exists():
        READY_FILE.unlink()

    proc = subprocess.Popen(cmd)

    def _shutdown(*_a: object) -> None:
        log.info("Shutting down Chat-LLM server ...")
        if READY_FILE.exists():
            READY_FILE.unlink()
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        log.info("Loading weights onto the GPU (this takes a moment) ...")
        _wait_until_loaded(base_url, proc)
        log.info("Weights loaded — running warm-up inference ...")
        warm_s = _warm_up(base_url)
        READY_FILE.touch()
        log.info("READY: model warm (warm-up inference %.2fs). Serving %s/v1/chat/completions",
                 warm_s, base_url)
    except SystemExit:
        proc.terminate()
        raise

    # Supervise: block on the server process; if it dies, exit non-zero so a supervisor restarts us.
    ret = proc.wait()
    if READY_FILE.exists():
        READY_FILE.unlink()
    sys.exit(ret)


if __name__ == "__main__":
    main()
