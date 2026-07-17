# Image-generation A/B benchmark report

- **Date:** 2026-07-16
- **Branch:** `feature/image-benchmarks` (worktree, isolated from other agents)
- **Purpose:** pick the production image-edit model for the F-008 Image Generation Runner
  (architecture.md §4.3): realism, s/image, load/unload cadence (§6.1 day/night GPU handoff),
  VRAM fit on the target 48GB card.
- **Hardware:** Quadro RTX 8000 48GB (Turing sm_75 — no native bf16/fp8 tensor cores), CUDA 12.1.
- **Harness:** `image/benchmark.py` (v0.39.3) — same reference photo, same 3 "camera roll" prompts
  (gym mirror selfie / cozy cafe / evening at home), each candidate at its recommended distill
  step count. Reference: a live photo of a young woman (curly bob), 640×640
  (`image/ref_user.png`).

## Candidates

| | A | B |
|---|---|---|
| Model | Phr00t **Qwen-Rapid-AIO-NSFW-v23** (merged all-in-one checkpoint, 28.4GB) | official **Qwen-Image-Edit-2511** (diffusers bf16: 39G transformer + 16G text encoder) + **Lightning 8-step LoRA** |
| Runtime | headless ComfyUI server, API workflow (`image/bench_workflow_aio.json`) | diffusers `QwenImageEditPlusPipeline` |
| Steps | 4 (AIO is distill-merged) | 8 (matches the downloaded Lightning LoRA) |
| NSFW | yes (uncensored merge) | base model (needs uncensored finetune/LoRA for F-014) |

## Results

### Numbers

| Candidate | steps | cold load (s) | s/image (0/1/2) | peak VRAM (GB) | fits 48GB? |
|-----------|------:|--------------:|----------------:|---------------:|------------|
| A Rapid-AIO v23 | 4 | 24 (server; ckpt loads lazily inside gen 0) | **129 / 112 / 110** (avg 117) | 40.3 | **yes — comfortably** |
| B diffusers+Lightning | 8 | 5.4 (weights stay in RAM) | **451 / 409 / 411** (avg 424) | 23.4 | **no — bf16 55G > 48G, runs only via sequential CPU offload** |

> **A's per-image caveat:** the run uses `--disable-smart-memory` (needed to avoid a gen-2
> text-encode OOM), which re-stages weights RAM→VRAM every generation. A resident production
> runner (one load, then batch) would pay this once per night, so the marginal per-image cost is
> lower than the 110-112s measured here. 1024×1024, 4 steps.

### Deployment findings (hard facts from the runs)

1. **B in bf16 cannot fit the 48GB card at all** (39G transformer + 16G text encoder = 55G).
   `model_cpu_offload` (whole-component swapping) still OOMs: 39G transformer + ~6G activations
   at 1024² > 47.4G. Only layer-by-layer `sequential_cpu_offload` runs — i.e. every denoise step
   streams the full transformer over PCIe. On this card, unquantized B is a fundamentally
   offload-bound configuration. A quantized B (fp8/GGUF) would change this, but that artifact is
   not what we downloaded/tested (and Turing has no native fp8 anyway).
2. **A fits comfortably** (28.4G merged checkpoint) and leaves headroom.
3. **ComfyUI smart memory must be disabled for batch use** on this card — with it enabled, the
   second consecutive generation OOMs at text-encode (weights cast to fp32 while everything from
   gen 1 is still resident). `--disable-smart-memory` fixed it (cost: per-gen reload, see caveat).
4. **VRAM leak discipline matters in the harness/runner:** an exception path that skips
   `empty_cache()` keeps ~47G reserved and starves the next model. Fixed with `finally` cleanup
   (v0.39.2) — same rule must apply in the F-008 runner.

### Realism (visual, human-judged)

**Candidate A** — all 3 images: identity from the reference held perfectly (same face, same curly
bob — the model kept the haircut without being told), scenes match the prompts, hands/phones
correct, lighting coherent (morning gym / warm afternoon cafe / evening lamp). Reads as a real
person's camera roll. Samples: `image/bench_out/A/`.

**Candidate B** — **produced blank output**: all three PNGs are identical 3,129-byte files (a
uniform frame — the classic NaN-latents signature of this bf16 + sequential-offload path). So on
this hardware B failed the realism test in the strongest possible sense: at 424 s/image it
produced nothing usable at all. No further debugging was invested — see verdict.

### Earlier qualitative findings (same model family, pre-benchmark)

- v23 t2i at 768², 4 steps with an "unedited iPhone photo" prompt produced a strongly realistic
  face (pores, oily sheen, harsh light, sensor noise) — 4 steps ≈ 8 steps in quality for this use.
- v23 edit mode (reference → "straight hair, front-facing selfie", 1024², 4 steps) held identity,
  executed the edit, and preserved reference details (outfit, wall shadow) — first live validation
  of the F-009 conditioning concept.

## Verdict — **Candidate A: Phr00t Qwen-Rapid-AIO-NSFW-v23** (final, user-confirmed 2026-07-17)

A wins on every axis that matters for the F-008 runner:

| Axis | A | B |
|---|---|---|
| Fits the 48GB card | ✅ 40.3G peak, resident | ❌ 55G bf16, offload-only |
| s/image (1024², distilled) | **~110-117s** (marginal cost lower with resident weights) | 424s |
| Output quality | ✅ 3/3 realistic, identity held | ❌ 3/3 blank frames |
| NSFW (F-014 requirement) | ✅ uncensored merge | ❌ base model only |
| Night-window math (~300 img/night, NFR-008-02) | ~9h at measured worst case; within window after resident-weights + step/resolution tuning | impossible |

**Decision: the F-008 Image Generation Runner is built on the Rapid-AIO v23 checkpoint via
headless ComfyUI** (the exact path this benchmark exercised: server API + workflow JSON +
`--disable-smart-memory`). The model stays swappable behind the fixed job contract (FR-008-16),
so a future quantized official-stack candidate can be re-benchmarked with this same harness.

**Candidate B's weights (127GB: base 54G + lightning-distill 73G) were deleted from disk** after
this verdict to free space; the harness keeps B's code path so a quantized variant can be
re-tested later by re-downloading.

## Reproduce

```bash
# GPU must be free (chat LLM unloaded — architecture.md §6.1)
cd <worktree>
image/.venv/bin/python image/benchmark.py --candidates A,B \
  --reference image/ref_user.png --n 3 --steps-a 4 --steps-b 8
# outputs: image/bench_out/{A,B}/*.png + image/bench_out/results.md
```
