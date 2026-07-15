#!/usr/bin/env bash
set -e
cd "/home/human/NeuroLady_Final"
echo "[1/2] torch cu121 (Turing sm_75)…"
uv pip install --python image/.venv/bin/python torch torchvision torchaudio \
  --index-url https://download.pytorch.org/whl/cu121
echo "[2/2] ComfyUI requirements…"
uv pip install --python image/.venv/bin/python -r image/comfyui/requirements.txt
echo "DONE comfyui deps"
