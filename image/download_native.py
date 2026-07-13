"""Download the LightX2V-native image artifacts into image/models/native/.

These are candidate (B) of the quality A/B (see image/README.md): the *original* base model
plus the LightX2V Lightning distill LoRA, so LightX2V can serve Qwen-Image-Edit-2511 directly
(no ComfyUI merge). Candidate (A) — the Phr00t AIO — is fetched by download_model.py.

    Qwen/Qwen-Image-Edit-2511                    # original base pipeline (transformer+VAE+text enc)
    lightx2v/Qwen-Image-Edit-2511-Lightning      # 4-step distill LoRA (bf16 / fp32 / fp8)

NSFW LoRAs (snofs, qwen4play, …) are community models (Civitai) — not auto-pulled here; they are
dropped into native/loras/ by hand at bench time so (B) reaches NSFW parity with (A).

Run inside this runner's isolated env (queued behind the AIO download):
    image/.venv/bin/python image/download_native.py
"""
import os
from pathlib import Path

os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")

from huggingface_hub import snapshot_download  # noqa: E402

NATIVE_DIR = Path(__file__).parent / "models" / "native"
REPOS = [
    ("Qwen/Qwen-Image-Edit-2511", "base"),
    ("lightx2v/Qwen-Image-Edit-2511-Lightning", "lightning-distill"),
]


def main() -> None:
    for repo_id, subdir in REPOS:
        dest = NATIVE_DIR / subdir
        dest.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {repo_id} -> {dest}")
        snapshot_download(repo_id=repo_id, local_dir=str(dest))
        print(f"Done: {repo_id}")
    print("Native (B) artifacts ready. NSFW LoRAs (snofs/qwen4play) added manually at bench time.")


if __name__ == "__main__":
    main()
