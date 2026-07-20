#!/usr/bin/env python3
"""F-016 video bench — Wan 2.2 image→video on headless ComfyUI (FR-016-12 / NFR-016-01).

Measures, per candidate config: **clip generation time**, **peak VRAM**, and writes a real MP4 +
the raw frames, so the production tier/quant/steps choice is a measured decision against the
**~4 s clip in ≈90 s** target — the same method as the image A/B.

Candidates:
  A  TI2V-5B GGUF          — dense, small (3.6 G), NO 4-step Lightning LoRA exists for it → more steps
  B  I2V-A14B GGUF + LoRA  — MoE high/low-noise, WITH the 4-step Lightning LoRA we already have

Usage:
  video/.venv/bin/python video/benchmark.py --candidates A --frames 65 --width 480 --height 480
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

COMFY = "http://127.0.0.1:8188"
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "bench_out"


def _post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(f"{COMFY}{path}", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req))


def _get(path: str) -> dict:
    return json.load(urllib.request.urlopen(f"{COMFY}{path}"))


def vram_used_mb() -> float:
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout.strip().splitlines()[0]
    return float(out)


def free_vram() -> None:
    """Release model VRAM between candidates — the image bench learned this the hard way
    (a leaked reservation starved the next model)."""
    try:
        _post("/free", {"unload_models": True, "free_memory": True})
    except Exception:  # noqa: BLE001
        pass


def graph_5b(ref: str, prompt: str, negative: str, w: int, h: int, frames: int,
             steps: int, cfg: float, seed: int, prefix: str) -> dict:
    """TI2V-5B: Wan22ImageToVideoLatent + plain KSampler (no Lightning LoRA exists for 5B)."""
    return {
        "1": {"class_type": "UnetLoaderGGUF",
              "inputs": {"unet_name": "Wan2.2-TI2V-5B-Q5_K_M.gguf"}},
        "2": {"class_type": "CLIPLoaderGGUF",
              "inputs": {"clip_name": "umt5-xxl-encoder-Q5_K_M.gguf", "type": "wan"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "wan2.2_vae.safetensors"}},
        "4": {"class_type": "LoadImage", "inputs": {"image": ref}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": negative}},
        "7": {"class_type": "Wan22ImageToVideoLatent",
              "inputs": {"vae": ["3", 0], "start_image": ["4", 0], "width": w, "height": h,
                         "length": frames, "batch_size": 1}},
        "8": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": "euler", "scheduler": "simple",
                         "positive": ["5", 0], "negative": ["6", 0],
                         "latent_image": ["7", 0], "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": prefix}},
    }


def graph_a14b(ref: str, prompt: str, negative: str, w: int, h: int, frames: int,
               steps: int, cfg: float, seed: int, prefix: str, unet: str, lora: str) -> dict:
    """I2V-A14B + the 4-step Lightning LoRA (single-expert path: whichever GGUF is given)."""
    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": unet}},
        "11": {"class_type": "LoraLoaderModelOnly",
               "inputs": {"model": ["1", 0], "lora_name": lora, "strength_model": 1.0}},
        "2": {"class_type": "CLIPLoaderGGUF",
              "inputs": {"clip_name": "umt5-xxl-encoder-Q5_K_M.gguf", "type": "wan"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
        "4": {"class_type": "LoadImage", "inputs": {"image": ref}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": negative}},
        "7": {"class_type": "WanImageToVideo",
              "inputs": {"positive": ["5", 0], "negative": ["6", 0], "vae": ["3", 0],
                         "start_image": ["4", 0], "width": w, "height": h,
                         "length": frames, "batch_size": 1}},
        "8": {"class_type": "KSampler",
              "inputs": {"model": ["11", 0], "seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": "euler", "scheduler": "simple",
                         "positive": ["7", 0], "negative": ["7", 1],
                         "latent_image": ["7", 2], "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": prefix}},
    }


def run(graph: dict, label: str, timeout_s: float = 1800.0) -> dict:
    """Submit the graph, poll until done, return timing + VRAM + produced frame files."""
    cid = str(uuid.uuid4())
    free_vram()
    base_vram = vram_used_mb()
    t0 = time.time()
    pid = _post("/prompt", {"prompt": graph, "client_id": cid})["prompt_id"]
    peak = base_vram
    err = None
    while True:
        time.sleep(2.0)
        peak = max(peak, vram_used_mb())
        hist = _get(f"/history/{pid}")
        if pid in hist:
            h = hist[pid]
            st = h.get("status", {})
            if st.get("status_str") == "error" or not st.get("completed", True):
                msgs = [m for m in st.get("messages", []) if m and m[0] == "execution_error"]
                err = msgs[-1][1] if msgs else st
            frames = [f for o in h.get("outputs", {}).values() for f in o.get("images", [])]
            return {"label": label, "seconds": round(time.time() - t0, 1),
                    "peak_vram_mb": round(peak), "base_vram_mb": round(base_vram),
                    "frames": frames, "error": err}
        if time.time() - t0 > timeout_s:
            return {"label": label, "seconds": round(time.time() - t0, 1),
                    "peak_vram_mb": round(peak), "frames": [], "error": "timeout"}


def encode_mp4(frames: list[dict], out_mp4: Path, fps: int) -> bool:
    """Frames (ComfyUI output pngs) → Telegram-friendly MP4 (FR-016-05)."""
    if not frames:
        return False
    src = Path("/home/human/NeuroLady_Final/image/comfyui/output")
    first = frames[0]["filename"]
    stem = first.rsplit("_", 2)[0]
    pattern = str(src / (stem + "_%05d_.png"))
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-start_number",
           first.rsplit("_", 2)[1], "-i", pattern,
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
           str(out_mp4)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0 and out_mp4.exists()


DEFAULT_PROMPT = ("a young woman with long blond hair sitting in soft indoor light, she slowly "
                  "moves her hands, gentle natural motion, subtle head movement, photorealistic, "
                  "shot on a phone camera")
DEFAULT_NEG = ("blurry, distorted hands, extra fingers, deformed face, warping, flicker, "
               "low quality, watermark, text, static image")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default="A", help="comma list: A (5B), B (A14B+LoRA)")
    ap.add_argument("--ref", default="wan_ref.png")
    ap.add_argument("--width", type=int, default=480)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--frames", type=int, default=65, help="~4s @16fps = 65 (4n+1)")
    ap.add_argument("--fps", type=int, default=16)
    ap.add_argument("--steps-5b", type=int, default=20)
    ap.add_argument("--steps-a14b", type=int, default=4)
    ap.add_argument("--cfg-5b", type=float, default=5.0)
    ap.add_argument("--cfg-a14b", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--a14b-unet", default="")
    ap.add_argument("--a14b-lora", default="Wan2.2-I2V-A14B-4steps-lora-rank64-Seko-V1/low_noise_model.safetensors")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--negative", default=DEFAULT_NEG)
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for cand in [c.strip().upper() for c in args.candidates.split(",") if c.strip()]:
        tag = f"{cand}{args.tag}_{args.width}x{args.height}_{args.frames}f"
        prefix = f"wanbench_{tag}"
        if cand == "A":
            g = graph_5b(args.ref, args.prompt, args.negative, args.width, args.height,
                         args.frames, args.steps_5b, args.cfg_5b, args.seed, prefix)
            label = f"A TI2V-5B Q5 steps={args.steps_5b} cfg={args.cfg_5b}"
        else:
            if not args.a14b_unet:
                print("!! candidate B needs --a14b-unet <file.gguf>")
                continue
            g = graph_a14b(args.ref, args.prompt, args.negative, args.width, args.height,
                           args.frames, args.steps_a14b, args.cfg_a14b, args.seed, prefix,
                           args.a14b_unet, args.a14b_lora)
            label = f"B A14B+Lightning steps={args.steps_a14b} cfg={args.cfg_a14b}"

        print(f"\n=== {label} | {args.width}x{args.height} {args.frames}f ===", flush=True)
        r = run(g, label)
        if r.get("error"):
            print(f"  ERROR: {str(r['error'])[:400]}")
        mp4 = OUT / f"{tag}.mp4"
        ok = encode_mp4(r["frames"], mp4, args.fps)
        clip_s = args.frames / args.fps
        r.update({"mp4": str(mp4) if ok else None, "clip_seconds": clip_s,
                  "ratio_gen_per_clip": round(r["seconds"] / clip_s, 1) if clip_s else None})
        print(f"  time={r['seconds']}s  peakVRAM={r['peak_vram_mb']}MB  frames={len(r['frames'])}"
              f"  mp4={'ok' if ok else 'FAILED'}  ({r['seconds']}s gen for {clip_s}s clip)")
        results.append(r)
        free_vram()

    (OUT / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print("\n== summary (target: ~4s clip in <=90s) ==")
    for r in results:
        print(f"  {r['label']:<44} {r['seconds']:>7}s  VRAM {r['peak_vram_mb']:>6}MB  "
              f"{'OK' if not r.get('error') else 'ERR'}")


if __name__ == "__main__":
    main()
