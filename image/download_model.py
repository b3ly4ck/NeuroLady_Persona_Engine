"""Download the image gen/edit model weights into image/models/.

Selected model (see architecture.md §4.3 / §6.2b):
    Phr00t/Qwen-Image-Edit-Rapid-AIO  ::  v23 NSFW checkpoint

`Qwen-Image-Edit-Rapid-AIO` v23 (NSFW variant) is an All-In-One, distilled + FP8-quantized
build on top of Qwen-Image-Edit-2511: the accelerator, VAE and CLIP are merged into one
~28.4 GB safetensors checkpoint, running at 4-8 steps / CFG 1. Conditioned on each persona's
reference images for identity-consistent output. Accelerated by LightX2V (§4.3).

Run inside this runner's isolated env:
    image/.venv/bin/python image/download_model.py            # default v23 NSFW
    image/.venv/bin/python image/download_model.py --variant SFW   # SFW build
"""
import argparse
import os
from pathlib import Path

os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")

from huggingface_hub import hf_hub_download  # noqa: E402

REPO_ID = "Phr00t/Qwen-Image-Edit-Rapid-AIO"
# The checkpoint lives in a per-version subfolder on the repo, e.g. v23/Qwen-Rapid-AIO-NSFW-v23.safetensors
FILENAME_TMPL = "{version}/Qwen-Rapid-AIO-{variant}-{version}.safetensors"
MODELS_DIR = Path(__file__).parent / "models"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="v23", help="AIO release tag, e.g. v23")
    parser.add_argument(
        "--variant",
        default="NSFW",
        choices=["NSFW", "SFW"],
        help="which build to fetch (v5+ ships separate NSFW / SFW checkpoints)",
    )
    args = parser.parse_args()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    filename = FILENAME_TMPL.format(version=args.version, variant=args.variant)
    print(f"Downloading {REPO_ID} :: {filename} -> {MODELS_DIR}")
    path = hf_hub_download(
        repo_id=REPO_ID,
        filename=filename,
        local_dir=str(MODELS_DIR),
    )
    print(f"Done: {path}")


if __name__ == "__main__":
    main()
