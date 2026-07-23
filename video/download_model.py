#!/usr/bin/env python3
"""Download Wan 2.2 image→video weights for the F-016 runner (architecture.md §4.3/§4.3a).

Turing-safe stack: **GGUF-quantized** Wan 2.2 (no FP8) + the **Wan2.2-Lightning 4-step distill
LoRA**, served later on headless ComfyUI + City96 ComfyUI-GGUF. Two tiers benched against the
4 s/≈90 s target (F-016 NFR-016-01):

  --tier 5b    QuantStack/Wan2.2-TI2V-5B-GGUF   (primary — dense, fast, our speed target)
  --tier a14b  QuantStack/Wan2.2-I2V-A14B-GGUF  (MoE high+low noise — bench candidate B)

Robust to filename drift: it lists the repo's files and picks the one matching --quant, rather than
hard-coding a GGUF filename. Each component is independent (one 404 doesn't abort the rest).

    video/.venv/bin/python video/download_model.py --tier 5b --quant Q5_K_M
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download, list_repo_files, snapshot_download

DEST = Path(__file__).parent / "models"

# Diffusion GGUF repos (QuantStack — the well-known Wan GGUF publisher).
DIFFUSION_REPOS = {
    "5b": "QuantStack/Wan2.2-TI2V-5B-GGUF",
    "a14b": "QuantStack/Wan2.2-I2V-A14B-GGUF",
}
# Support files (Turing-friendly): GGUF text encoder + the Wan VAE + the 4-step Lightning LoRA.
TEXT_ENCODER_REPO = "city96/umt5-xxl-encoder-gguf"      # GGUF umt5 → no fp8 needed on Turing
VAE_REPO = "Comfy-Org/Wan_2.2_ComfyUI_Repackaged"        # canonical ComfyUI repackaged assets
LIGHTNING_LORA_REPO = "lightx2v/Wan2.2-Lightning"        # the 4-step distill LoRA (framework dropped, LoRA kept)


def _pick(files: list[str], must_contain: list[str], suffix: str = ".gguf") -> list[str]:
    lc = [f for f in files if f.lower().endswith(suffix)]
    out = [f for f in lc if all(t.lower() in f.lower() for t in must_contain)]
    return out


def _download_diffusion(tier: str, quant: str, subdir: Path) -> None:
    repo = DIFFUSION_REPOS[tier]
    files = list_repo_files(repo)
    # A14B is MoE: needs BOTH high-noise and low-noise experts. 5B is a single file.
    wanted = _pick(files, [quant, "high"]) + _pick(files, [quant, "low"]) if tier == "a14b" \
        else _pick(files, [quant])
    if not wanted:
        print(f"  ! no {quant} GGUF found in {repo}. Available GGUFs:")
        for f in _pick(files, []):
            print(f"      {f}")
        raise SystemExit(f"pick a --quant that exists in {repo}")
    for f in wanted:
        print(f"  ↓ {repo} :: {f}")
        hf_hub_download(repo, f, local_dir=str(subdir / "diffusion"))


def _download_support(subdir: Path) -> None:
    # Text encoder (GGUF, pick Q5_K_M else the first gguf).
    try:
        te = list_repo_files(TEXT_ENCODER_REPO)
        pick = _pick(te, ["Q5_K_M"]) or _pick(te, ["Q8"]) or _pick(te, [])
        if pick:
            print(f"  ↓ {TEXT_ENCODER_REPO} :: {pick[0]}")
            hf_hub_download(TEXT_ENCODER_REPO, pick[0], local_dir=str(subdir / "text_encoder"))
    except Exception as exc:  # noqa: BLE001
        print(f"  ! text encoder skipped: {exc}")
    # VAE (safetensors) — grab any wan vae from the repackaged repo.
    try:
        print(f"  ↓ {VAE_REPO} :: **/vae/*wan*vae*.safetensors")
        snapshot_download(VAE_REPO, allow_patterns=["**/vae/*ae*.safetensors"],
                          local_dir=str(subdir / "vae"))
    except Exception as exc:  # noqa: BLE001
        print(f"  ! vae skipped: {exc}")
    # Lightning 4-step LoRA (small repo).
    try:
        print(f"  ↓ {LIGHTNING_LORA_REPO} (Lightning 4-step LoRA)")
        snapshot_download(LIGHTNING_LORA_REPO, allow_patterns=["*.safetensors", "*.json"],
                          local_dir=str(subdir / "lightning_lora"))
    except Exception as exc:  # noqa: BLE001
        print(f"  ! lightning lora skipped: {exc}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", choices=list(DIFFUSION_REPOS), default="5b")
    ap.add_argument("--quant", default="Q5_K_M", help="GGUF quant tag to match, e.g. Q4_K_M/Q5_K_M/Q6_K/Q8_0")
    ap.add_argument("--skip-support", action="store_true", help="only the diffusion GGUF(s)")
    args = ap.parse_args()

    subdir = DEST / args.tier
    subdir.mkdir(parents=True, exist_ok=True)
    print(f"== Wan 2.2 download: tier={args.tier} quant={args.quant} -> {subdir}")
    _download_diffusion(args.tier, args.quant, subdir)
    if not args.skip_support:
        _download_support(subdir)
    print("== done:", subdir)


if __name__ == "__main__":
    sys.exit(main())
