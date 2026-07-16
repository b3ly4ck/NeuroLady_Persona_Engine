"""A/B image-generation benchmark — which candidate to use for persona photos.

Compares the two downloaded image-edit candidates on the metrics that decide deployment:
  • **A — Phr00t "Rapid AIO" NSFW v23** (a single merged ComfyUI checkpoint, distilled, ~4-8 steps).
  • **B — official Qwen-Image-Edit-2511 (diffusers) + Lightning distill LoRA** (4 or 8 steps).

For each candidate it measures, on the same GPU:
  • **cold-load time**  — checkpoint/pipeline → GPU (matters for day/night load-unload cadence, §6.1)
  • **per-image time**  — average seconds/image at the recommended low step count
  • **peak VRAM**       — GB reserved (does it fit alongside a KV cache? headroom?)
  • **output images**   — saved for side-by-side **realism** judgement (human-scored, not automated)

The realism verdict is the user's (visual); this harness produces the images + the hard numbers so
that judgement is grounded. Run it as the **night GPU step** — the chat LLM must be unloaded first
(only one heavy model owns the 48 GB GPU at a time, architecture.md §6.1).

    # unload the chat model first (frees the GPU), then:
    image/.venv/bin/python image/benchmark.py --candidates A,B --reference <face.jpg> --n 3

Outputs land in image/bench_out/{A,B}/ and a summary in image/bench_out/results.md.
"""
from __future__ import annotations

import argparse
import gc
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # repo root — works from any git worktree
V23_CHECKPOINT = ROOT / "image/models/v23/Qwen-Rapid-AIO-NSFW-v23.safetensors"
BASE_DIR = ROOT / "image/models/native/base"
LIGHTNING_LORA = ROOT / "image/models/native/lightning-distill/Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors"
COMFY_DIR = ROOT / "image/comfyui"
OUT_DIR = ROOT / "image/bench_out"

# Fixed, realistic "phone photo" edit prompts — the actual product use case (a real girl's camera
# roll): casual, imperfect, believable. Same prompts for both candidates → fair comparison.
PROMPTS = [
    "a casual mirror selfie of this woman at the gym, gym clothes, phone visible, natural lighting, candid",
    "a photo of this woman at a cozy cafe, holding a coffee, warm afternoon light, casual outfit, candid phone photo",
    "a selfie of this woman relaxing at home in the evening, soft lamp light, comfy clothes, natural and imperfect",
]


@dataclass
class Result:
    candidate: str
    load_s: float = 0.0
    gen_times: list[float] = field(default_factory=list)
    peak_vram_gb: float = 0.0
    steps: int = 0
    out_paths: list[str] = field(default_factory=list)
    error: str | None = None
    notes: str = ""

    @property
    def avg_gen_s(self) -> float:
        return sum(self.gen_times) / len(self.gen_times) if self.gen_times else 0.0


def _peak_vram_gb() -> float:
    import torch
    return torch.cuda.max_memory_reserved() / 1e9 if torch.cuda.is_available() else 0.0


def _reset_vram() -> None:
    import torch
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()


# ── candidate B — diffusers (base + Lightning LoRA) ─────────────────────────────────────────────


def bench_B_diffusers(reference: Path, n: int, steps: int = 8) -> Result:
    """Load Qwen-Image-Edit-2511 via diffusers, apply the Lightning distill LoRA, generate."""
    res = Result(candidate="B_diffusers_lightning", steps=steps)
    try:
        import torch
        from diffusers import DiffusionPipeline  # auto-selects QwenImageEditPlusPipeline
        from PIL import Image

        _reset_vram()
        t0 = time.monotonic()
        pipe = DiffusionPipeline.from_pretrained(str(BASE_DIR), torch_dtype=torch.bfloat16)
        # Lightning distill: 8 (or 4) steps instead of ~30 — the whole point of candidate B's speed.
        if LIGHTNING_LORA.exists():
            pipe.load_lora_weights(str(LIGHTNING_LORA))
        # base transformer (39G) + text encoder (16G) > 48GB — expect the offload path on this GPU.
        try:
            pipe.to("cuda")
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            pipe.enable_model_cpu_offload()
            res.notes = "does not fit 48GB fully; ran with model_cpu_offload"
        res.load_s = time.monotonic() - t0

        ref = Image.open(reference).convert("RGB")
        out_dir = OUT_DIR / "B"
        out_dir.mkdir(parents=True, exist_ok=True)
        for i, prompt in enumerate(PROMPTS[:n]):
            t = time.monotonic()
            image = pipe(image=ref, prompt=prompt, num_inference_steps=steps,
                         true_cfg_scale=1.0).images[0]
            res.gen_times.append(time.monotonic() - t)
            p = out_dir / f"B_{i:02d}.png"
            image.save(p)
            res.out_paths.append(str(p))

        res.peak_vram_gb = _peak_vram_gb()
        del pipe
        _reset_vram()
    except Exception as exc:  # keep the other candidate runnable even if this one fails
        res.error = f"{type(exc).__name__}: {exc}"
    return res


# ── candidate A — ComfyUI AIO checkpoint (headless server API) ─────────────────────────────────


def bench_A_comfy(reference: Path, n: int, steps: int = 6) -> Result:
    """Drive the Rapid-AIO checkpoint through a headless ComfyUI server.

    Starts ComfyUI, POSTs a Qwen-Image-Edit workflow that loads the AIO checkpoint and samples at a
    low step count, and polls /history for the result. The workflow graph lives in
    image/bench_workflow_aio.json (kept as a versioned asset, not inlined) — it is the one part that
    must be validated against the actual AIO on the first GPU run (node names/wiring for this build).
    """
    res = Result(candidate="A_rapid_aio_v23", steps=steps)
    import shutil
    import subprocess
    import threading
    import urllib.request

    workflow_path = ROOT / "image/bench_workflow_aio.json"
    proc = None
    # ComfyUI runs in its own process — in-process torch stats see nothing, so sample nvidia-smi.
    vram_samples: list[float] = []
    stop_sampling = threading.Event()

    def _sample_vram() -> None:
        while not stop_sampling.is_set():
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                capture_output=True, text=True)
            try:
                vram_samples.append(int(out.stdout.splitlines()[0].strip()) / 1024)
            except (ValueError, IndexError):
                pass
            stop_sampling.wait(2)

    try:
        if not workflow_path.exists():
            raise FileNotFoundError(
                "image/bench_workflow_aio.json missing — export a Qwen-Image-Edit workflow for the "
                "AIO checkpoint from ComfyUI (API format) and save it here.")

        # LoadImage resolves names against ComfyUI's input dir — stage the reference there.
        comfy_input = COMFY_DIR / "input"
        comfy_input.mkdir(exist_ok=True)
        ref_name = f"bench_ref{reference.suffix or '.png'}"
        shutil.copy2(reference, comfy_input / ref_name)

        threading.Thread(target=_sample_vram, daemon=True).start()
        t0 = time.monotonic()
        proc = subprocess.Popen(
            [str(ROOT / "image/.venv/bin/python"), str(COMFY_DIR / "main.py"),
             "--port", "8188", "--output-directory", str(OUT_DIR / "A")],
            cwd=str(COMFY_DIR), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # wait for the server + model load (readiness gate)
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=3)
                break
            except Exception:
                time.sleep(3)
        res.load_s = time.monotonic() - t0

        workflow = json.loads(workflow_path.read_text())
        (OUT_DIR / "A").mkdir(parents=True, exist_ok=True)
        for i, prompt in enumerate(PROMPTS[:n]):
            wf = _inject(workflow, prompt=prompt, reference=ref_name, steps=steps, seed=i)
            t = time.monotonic()
            # first gen also pulls the 28GB checkpoint into VRAM — give it a long leash
            _comfy_run_and_wait(wf, timeout=1200 if i == 0 else 600)
            res.gen_times.append(time.monotonic() - t)
        res.out_paths = sorted(str(p) for p in (OUT_DIR / "A").glob("*.png"))
        res.notes = "gen[0] includes lazy checkpoint load into VRAM"
        res.peak_vram_gb = max(vram_samples, default=0.0)
    except Exception as exc:
        res.error = f"{type(exc).__name__}: {exc}"
    finally:
        stop_sampling.set()
        if proc is not None:
            proc.terminate()
    return res


def _inject(workflow: dict, *, prompt: str, reference: str, steps: int, seed: int) -> dict:
    """Fill the workflow's prompt/reference/steps/seed placeholders (validated on first GPU run)."""
    import copy
    wf = copy.deepcopy(workflow)
    for node in wf.values():
        inp = node.get("inputs", {})
        for k in list(inp):
            if inp[k] == "__PROMPT__":
                inp[k] = prompt
            elif inp[k] == "__REFERENCE__":
                inp[k] = reference
            elif inp[k] == "__STEPS__":
                inp[k] = steps
            elif inp[k] == "__SEED__":
                inp[k] = seed
    return wf


def _comfy_run_and_wait(workflow: dict, timeout: float = 300) -> None:
    import urllib.request
    data = json.dumps({"prompt": workflow}).encode()
    req = urllib.request.Request("http://127.0.0.1:8188/prompt", data=data,
                                 headers={"Content-Type": "application/json"})
    pid = json.loads(urllib.request.urlopen(req, timeout=30).read())["prompt_id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hist = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:8188/history/{pid}", timeout=10).read())
        if pid in hist:
            status = hist[pid].get("status", {})
            if status.get("status_str") == "error":
                msgs = [m for m in status.get("messages", []) if m and m[0] == "execution_error"]
                raise RuntimeError(f"ComfyUI execution error: {msgs or status}")
            return
        time.sleep(1)
    raise TimeoutError("ComfyUI generation timed out")


# ── report ──────────────────────────────────────────────────────────────────────────────────────


def write_results(results: list[Result]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Image-generation A/B benchmark", "",
        "| Candidate | steps | load (s) | avg gen (s/img) | peak VRAM (GB) | images | notes | error |",
        "|-----------|------:|---------:|----------------:|---------------:|-------:|-------|-------|",
    ]
    for r in results:
        lines.append(
            f"| {r.candidate} | {r.steps} | {r.load_s:.1f} | {r.avg_gen_s:.2f} | "
            f"{r.peak_vram_gb:.1f} | {len(r.out_paths)} | {r.notes or '—'} | {r.error or '—'} |")
    lines += ["", "Realism is judged visually from the saved images in `bench_out/{A,B}/`.",
              "Decision factors: realism, s/image, load/unload time (day↔night cadence), VRAM headroom."]
    (OUT_DIR / "results.md").write_text("\n".join(lines))
    print("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default="A,B", help="comma list of A,B")
    ap.add_argument("--reference", required=True, help="path to a reference face/body photo")
    ap.add_argument("--n", type=int, default=3, help="images per candidate (<= len(PROMPTS))")
    ap.add_argument("--steps", type=int, default=8)
    args = ap.parse_args()
    ref = Path(args.reference)
    if not ref.exists():
        raise SystemExit(f"reference image not found: {ref}")

    results: list[Result] = []
    want = {c.strip().upper() for c in args.candidates.split(",")}
    if "B" in want:
        print("→ candidate B (diffusers + Lightning LoRA) …")
        results.append(bench_B_diffusers(ref, args.n, args.steps))
    if "A" in want:
        print("→ candidate A (Rapid AIO via ComfyUI) …")
        results.append(bench_A_comfy(ref, args.n, min(args.steps, 6)))
    write_results(results)


if __name__ == "__main__":
    main()
