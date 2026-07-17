# video/ — Wan 2.2 intimate video runner (F-016)

Isolated model runner for **image→video** intimate clips, the video-phase sibling of `image/`
(architecture.md §4.3/§4.3a/§6.2c/§6.3). Own env + weights + ComfyUI graph, behind a fixed job API;
**never** imported by `services/bot`.

## Why this stack (and why not LightX2V)
Our GPU is a **Quadro RTX 8000, 48 GB, Turing sm_75** — **no FP8** (needs Ada/Hopper sm_89+).
LightX2V's headline is FP8 distilled checkpoints, so it's dropped here (the image A/B proved it:
the LightX2V-native path OOM'd / produced blank frames). Instead we use the same pattern that won
for images: **community 4-step distill + GGUF quantization, served on headless ComfyUI**. GGUF has
no FP8 dependency → runs on Turing.

## Stack
- **Model:** Wan 2.2 image→video, GGUF-quantized.
  - `--tier 5b` → `QuantStack/Wan2.2-TI2V-5B-GGUF` (dense, fast — **primary**, our speed target)
  - `--tier a14b` → `QuantStack/Wan2.2-I2V-A14B-GGUF` (MoE high+low noise — bench candidate B)
- **Accelerator:** **Wan2.2-Lightning** 4-step distill LoRA (`lightx2v/Wan2.2-Lightning` — the LoRA,
  not the framework).
- **Runtime:** headless ComfyUI + **City96 ComfyUI-GGUF** custom nodes.
- **Support:** GGUF umt5-xxl text encoder + Wan VAE.

## Target (F-016 NFR-016-01)
A **~4 s clip (≈65 frames @ 16 fps)** at **Telegram-low resolution (≈480×480 / 512×384)**, generated
in **≈90 s** on the RTX 8000 (hard cap ≤ 150 s). Resolution is traded for speed on purpose — the
deliverable is an in-chat video message.

## Setup
```bash
# isolated env (uv, Python 3.11), like chat/ and image/
uv venv video/.venv --python 3.11
uv pip install --python video/.venv/bin/python huggingface_hub hf_transfer

# download the 5B tier (primary) — diffusion GGUF + Lightning LoRA + text encoder + VAE
video/.venv/bin/python video/download_model.py --tier 5b --quant Q5_K_M
```

## Status
- **Now:** feature/test spec (`developer files/{features,tests}/F-016-*.md`) + this scaffold +
  weight download. Serving (`video/serve.py`, thin wrapper over ComfyUI's `/prompt`) and the
  **bench** (`video/benchmark.py`, tier×quant × time/VRAM/quality vs the 4 s/≈90 s target) are the
  next steps — GPU load-test only when chat has released the GPU (night window, §6.1).
- Weights, `.venv`, and ComfyUI are git-ignored (see `.gitignore`).
