# chat/ — Chat LLM runner

Self-hosted text LLM that powers real-time conversation (architecture.md §4.1). This module is an
**isolated model runner**: it has its own virtual environment and its own model weights, and (once
built) exposes a fixed network API that the Orchestrator calls. Nothing outside this folder imports
its Python dependencies — that is how we avoid dependency conflicts with the image/video runners
(see architecture.md §6.2c).

## Model
- **`HauhauCS/Qwen3.5-35B-A3B-Uncensored-HauhauCS-Aggressive`** — uncensored MoE, 35B total /
  ~3B active, 262K context, Apache-2.0. GGUF quants.
- **Default quant: `Q6_K` (~28.5 GB)** — near-lossless, fully fits the 48 GB GPU with headroom for
  KV cache. Alternatives: `Q5_K_M` (~24.8 GB, more context room), `Q8_0` (~36.9 GB, max quality).

## Layout
```
chat/
  .venv/            # isolated env (gitignored) — created with: uv venv chat/.venv --python 3.11
  models/           # GGUF weights (gitignored) — populated by download_model.py
  prompts/          # persona system-prompt + context-assembly templates (versioned)
  download_model.py # fetches the selected quant into models/
  serve.py          # starts the local inference server behind the fixed API (warm-gated)
  smoke.py          # sends a couple of chat completions; prints latency + tok/s (the "reference")
```

## Setup (isolated env)
```bash
uv venv chat/.venv --python 3.11
VIRTUAL_ENV=chat/.venv uv pip install "huggingface_hub" hf_transfer
chat/.venv/bin/python chat/download_model.py            # default Q6_K
# chat/.venv/bin/python chat/download_model.py --quant Q5_K_M   # alt
```

## Serving
GGUF weights are served with a **llama.cpp** backend (`llama-cpp-python`'s server), exposing an
**OpenAI-compatible** HTTP endpoint — the fixed contract the Orchestrator calls (architecture.md
§6.2c). `serve.py` does not report ready until the model is **loaded and warmed** (a warm-up
inference), so cold-start latency never leaks to users (architecture.md §4.1); the day/night
scheduler (§6.1) keeps the runner warm/resident by day and unloads it at night for the image/video
runners. Serving deps are pinned in this runner's own env only.

Install the serving backend into the isolated env (Turing sm_75 / CUDA 12.1 prebuilt wheel):
```bash
uv pip install --python chat/.venv/bin/python "llama-cpp-python[server]" httpx \
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
# If the prebuilt wheel doesn't offload to the GPU, build from source for this exact arch:
#   CMAKE_ARGS="-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=75" \
#   uv pip install --python chat/.venv/bin/python --no-binary llama-cpp-python "llama-cpp-python[server]"
```

Run it:
```bash
chat/.venv/bin/python chat/serve.py         # loads Q6_K, warms up, serves 127.0.0.1:8080
chat/.venv/bin/python chat/smoke.py         # (in another shell) prints latency + tok/s
```

Endpoint: `POST http://127.0.0.1:8080/v1/chat/completions` (and `GET /v1/models`). Tunables are env
vars documented at the top of `serve.py` (`CHAT_N_CTX`, `CHAT_N_GPU_LAYERS`, `CHAT_PORT`, …); the
defaults are sized for the 48 GB Quadro RTX 8000.
