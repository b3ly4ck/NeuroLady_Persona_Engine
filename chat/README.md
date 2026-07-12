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
  serve.py          # (TODO) starts the local inference server behind the fixed API
```

## Setup (isolated env)
```bash
uv venv chat/.venv --python 3.11
VIRTUAL_ENV=chat/.venv uv pip install "huggingface_hub" hf_transfer
chat/.venv/bin/python chat/download_model.py            # default Q6_K
# chat/.venv/bin/python chat/download_model.py --quant Q5_K_M   # alt
```

## Serving (next step)
GGUF weights are served with a llama.cpp-based backend (e.g. `llama-cpp-python` CUDA build or the
`llama-server` binary), exposing an OpenAI-compatible HTTP endpoint. The day/night scheduler
(architecture.md §6.1) keeps this runner **warm and resident** during awake hours and unloads it at
night so the GPU can run the image/video runners. Serving deps are pinned in this runner's own env
only.
