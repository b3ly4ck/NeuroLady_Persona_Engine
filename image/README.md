# image/ — Image generation runner

Self-hosted image gen/edit that produces each persona's photo archive (architecture.md §4.3,
§3.9). Like `chat/`, this module is an **isolated model runner**: its own virtual environment, its
own model weights, and (once built) a fixed **job API** the media pipeline calls (enqueue →
generate → write archive). Nothing outside this folder imports its Python dependencies — that is
how we avoid dependency conflicts with the chat/video runners (architecture.md §6.2c).

## Model
- **`Phr00t/Qwen-Image-Edit-Rapid-AIO` — v23 NSFW** (`v23/Qwen-Rapid-AIO-NSFW-v23.safetensors`,
  ~28.4 GB). An **All-In-One** checkpoint on top of **Qwen-Image-Edit-2511**: accelerator + VAE +
  CLIP merged into one file, **FP8**-quantized, running at **4-8 steps / CFG 1**. Community
  skin/realism + NSFW LoRAs baked in. Tuned for **character consistency** across edits, so it holds
  each persona's appearance when conditioned on her reference images (`media/<slug>/reference/`).
- v5+ ships **separate NSFW and SFW** builds; we default to NSFW (the product serves both SFW and
  intimate shots, §4.3). SFW build: `--variant SFW`.
- Accelerated by **LightX2V** (an inference framework, not a model — 4-step distilled checkpoints +
  INT8/FP8/NVFP4 quant), so the night batch fits the sleep window on our GPU (§4.3, §6.2b).

## Layout
```
image/
  .venv/            # isolated env (gitignored) — created with: uv venv image/.venv --python 3.11
  models/           # safetensors weights (gitignored) — populated by download_model.py
  comfyui/          # headless ComfyUI runtime (gitignored — cloned, not vendored)
  prompts/          # generation-prompt templates + ComfyUI workflow JSON (versioned, per-runner)
  download_model.py # fetches the selected AIO checkpoint into models/
  # serve.py        # (next) thin job-API wrapper in front of headless ComfyUI + LightX2V
```

## Setup (isolated env)
```bash
uv venv image/.venv --python 3.11
VIRTUAL_ENV=image/.venv uv pip install "huggingface_hub" hf_transfer
image/.venv/bin/python image/download_model.py                 # default v23 NSFW
# image/.venv/bin/python image/download_model.py --variant SFW # SFW build
```

## GPU scheduling
The image runner is a **night-batch** service: the day/night scheduler (§6.1) keeps the **chat**
runner resident/warm by day and only brings up image/video runners at night, once the chat LLM is
unloaded and the GPU is free. Both the chat and image checkpoints are ~28 GB, so **only one owns
the 48 GB GPU at a time** — do not load this runner while the chat runner holds the GPU.

## Serving (decided — build/test at night)
The AIO checkpoint is a **merged single-file** (accelerator+VAE+CLIP) safetensors in **ComfyUI
format**. LightX2V's native config-loader wants a base model + separate LoRA/quant configs and does
**not** ingest the merged AIO file directly, so the runner serves the AIO on a **headless ComfyUI**
runtime (ComfyUI is its native loader) with **LightX2V acceleration nodes**, all behind our own thin
**media job-API** (the fixed §6.2c contract: enqueue → generate → write archive). Decision recorded
in architecture.md §4.3 / §6.2c.

Build steps (run inside this isolated runner; **GPU load-tested only at night** when the chat runner
has released the 48 GB GPU):
```bash
# 1. headless ComfyUI + its deps into the isolated env
git clone https://github.com/comfyanonymous/ComfyUI image/comfyui
uv pip install --python image/.venv/bin/python -r image/comfyui/requirements.txt
# torch built for this GPU (Turing sm_75 / CUDA 12.1):
uv pip install --python image/.venv/bin/python torch torchvision \
  --index-url https://download.pytorch.org/whl/cu121
# 2. LightX2V acceleration nodes (custom_nodes)
# 3. point ComfyUI at image/models/ (extra_model_paths.yaml) — do NOT copy the 28 GB file
# 4. image/serve.py — thin job-API wrapper over ComfyUI's /prompt API, warm-gated
```
