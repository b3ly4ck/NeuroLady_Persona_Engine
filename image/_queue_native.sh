#!/usr/bin/env bash
# Queue runner for the LightX2V-native A/B candidate (B).
# Waits until the AIO weights download (download_model.py) finishes so the network isn't
# thrashed, THEN: (1) pulls the native base + Lightning distill LoRA, (2) clones LightX2V.
# Building LightX2V kernels + the actual bench happen later, at the night GPU window.
set -u
cd "/home/human/NeuroLady_Final"

echo "[queue] $(date '+%F %T')  waiting for AIO download to finish…"
while pgrep -f "download_model.py" >/dev/null 2>&1; do
  sleep 60
done
echo "[queue] $(date '+%F %T')  AIO download finished — starting native pulls."

echo "[queue] (1/2) native weights (base 2511 + Lightning distill LoRA)…"
image/.venv/bin/python image/download_native.py

echo "[queue] (2/2) clone LightX2V framework…"
if [ ! -d image/lightx2v/.git ]; then
  git clone --depth 1 https://github.com/ModelTC/LightX2V image/lightx2v
else
  echo "[queue] image/lightx2v already present — skipping clone."
fi

echo "[queue] $(date '+%F %T')  DONE. LightX2V kernels + A/B bench are the night step (see image/README.md)."
