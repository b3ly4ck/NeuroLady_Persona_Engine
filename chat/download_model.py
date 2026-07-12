"""Download the chat LLM weights into chat/models/.

Selected model (see architecture.md §4.1 / §6.2b):
    HauhauCS/Qwen3.5-35B-A3B-Uncensored-HauhauCS-Aggressive  (GGUF quants)

Default quant: Q6_K (~28.5 GB) — near-lossless quality, fully fits the 48 GB
GPU with room for KV cache. Override with --quant (e.g. Q5_K_M, Q8_0, IQ4_XS).

Run inside this runner's isolated env:
    chat/.venv/bin/python chat/download_model.py
"""
import argparse
import os
from pathlib import Path

os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")

from huggingface_hub import hf_hub_download  # noqa: E402

REPO_ID = "HauhauCS/Qwen3.5-35B-A3B-Uncensored-HauhauCS-Aggressive"
FILENAME_TMPL = "Qwen3.5-35B-A3B-Uncensored-HauhauCS-Aggressive-{quant}.gguf"
MODELS_DIR = Path(__file__).parent / "models"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quant", default="Q6_K", help="GGUF quant tag, e.g. Q6_K, Q5_K_M, Q8_0")
    args = parser.parse_args()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    filename = FILENAME_TMPL.format(quant=args.quant)
    print(f"Downloading {REPO_ID} :: {filename} -> {MODELS_DIR}")
    path = hf_hub_download(
        repo_id=REPO_ID,
        filename=filename,
        local_dir=str(MODELS_DIR),
    )
    print(f"Done: {path}")


if __name__ == "__main__":
    main()
