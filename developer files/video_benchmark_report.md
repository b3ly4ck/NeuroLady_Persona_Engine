# F-016 Video Benchmark — Wan 2.2 image→video on the Quadro RTX 8000

Measured decision record for the production video config (F-016 FR-016-12 / NFR-016-01), same
method as the image A/B (`image_benchmark_report.md`). All runs: identical reference still
(`image/bench_ref/ref_face_v2.png` → `wan_ref.png`), identical prompt/negative/seed, headless
ComfyUI + City96 ComfyUI-GGUF, **no FP8** (Turing sm_75).

**Target (the product requirement):** a **~4 s clip (65 frames @ 16 fps)** at Telegram-low
resolution, generated in **≈90 s** (hard cap 150 s).

---

## Environment (as measured)

| | |
|---|---|
| GPU | Quadro RTX 8000, 48 GB, **Turing sm_75**, CUDA 12.1 |
| Runtime | ComfyUI **0.28.0** (native `nodes_wan.py`) + **City96 ComfyUI-GGUF**, torch 2.5.1+cu121 |
| Model A | `Wan2.2-TI2V-5B-Q5_K_M.gguf` (3.6 G) + `wan2.2_vae.safetensors` |
| Text encoder | `umt5-xxl-encoder-Q5_K_M.gguf` (3.9 G), `type=wan` |
| Model B | `Wan2.2-I2V-A14B` GGUF Q5_K_M (MoE high/low-noise) + our 4-step Lightning LoRA |
| Weights wiring | `video/extra_model_paths.yaml` — **absolute paths via config, no in-repo symlinks** (CLAUDE.md hard rule) |

**Setup gotchas found (binding for the F-016 runner):**
- `CLIPLoaderGGUF` needs **`sentencepiece` + `protobuf`** installed in the ComfyUI env, else the
  umt5 encoder fails at load (`ImportError`) — the graph is fine, the deps are not optional.
- ComfyUI needs `--disable-smart-memory` on this card (inherited from the image bench).
- **No Lightning 4-step LoRA exists for TI2V-5B** — the `lightx2v/Wan2.2-Lightning` LoRAs are all
  **A14B** (MoE high/low-noise). So 5B runs undistilled (more steps), A14B runs at 4 steps. That is
  precisely the trade the bench measures.

---

## Results — candidate A (TI2V-5B Q5)

| Run | Res | Frames (clip) | Steps | Time | Peak VRAM | vs 90 s target |
|---|---|---|---|---|---|---|
| smoke | 320×320 | 17 (1.06 s) | 8 | 81.7 s | 6.4 GB | (cold-load validation) |
| **target** | **480×480** | **65 (4.06 s)** | **8** | **57.3 s** | **6.4 GB** | ✅ **36 % under budget** |
| sweep | 480×480 | 65 (4.06 s) | 20 | _pending_ | | |
| sweep | 640×640 | 65 (4.06 s) | 8 | _pending_ | | |
| sweep | 640×640 | 65 (4.06 s) | 20 | _pending_ | | |

**Headline:** the product target is **met with room to spare** — a 4 s clip at 480×480 takes
**57.3 s**, and that number *includes* a cold model load inside the measurement. Pure sampling
measured at **1.86 s/step** (8 steps ≈ 15 s); the remainder is model load + text encode + VAE
decode of 65 frames. VRAM peaks at **6.4 GB of 48 GB** — the card is nowhere near the limit, which
is what unlocks the quality headroom being swept above.

**Motion verified, not just pixels:** frame-to-frame delta between first and last frame of the
smoke clip = **70.7 mean** (0 would be a static image), so the model is genuinely animating the
reference, not returning a still.

---

## Implications for the F-016 runner

1. **Speed is not the constraint — quality budget is.** Since 480×480/8-steps lands at 57 s of a
   90 s budget, the remaining headroom should be spent on steps and/or resolution (the sweep
   quantifies which buys more).
2. **Keep the model resident across a batch** (FR-016-10): a large slice of the measured 57 s is
   the cold load, which the night batch pays **once**, not per clip. Per-clip warm cost is
   materially lower — the batch-throughput math (NFR-016-07/F-017 NFR-017-01) should use the warm
   number, not this one.
3. **A14B is not needed for speed.** It remains worth benching for *quality* (4-step Lightning,
   better anatomy/motion per the model card), but 5B already satisfies the product requirement, so
   A14B has to win on output quality alone to justify its heavier load.

## Status
- Candidate A target run: **done, target met.**
- Candidate A quality sweep (steps × resolution): **running.**
- Candidate B (A14B + Lightning 4-step): weights downloading (HighNoise expert first).
- Production config decision: pending the sweep + a human quality judgement on the sample clips in
  `video/bench_out/` (same as the image A/B, where the user made the final call).
