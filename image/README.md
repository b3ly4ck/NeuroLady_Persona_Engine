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
  prompts/          # generation-prompt templates (versioned, per-runner — never shared)
  download_model.py # fetches the selected AIO checkpoint into models/
  # serve.py        # (TBD) starts the local job-API server behind the fixed contract
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

## Serving (TBD)
The AIO checkpoint is a merged (accelerator+VAE+CLIP) safetensors, the format ComfyUI loads
natively; the runner will expose the fixed media **job API** (§6.2c) in front of the pipeline.
Serving backend + LightX2V wiring are being finalized — see `serve.py` once added.
