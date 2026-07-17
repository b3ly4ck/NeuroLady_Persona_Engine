# F-016 — Wan Intimate Video Generation — test specification

Mirror of `developer files/features/F-016-wan-intimate-video-generation.md`. Every TC id embeds the
`FR-`/`NFR-`/`US-` id it verifies. Because F-016 drives a heavy GPU model, tests split into:
**automated** (job-contract, gate refusal, idempotency, atomicity, isolation, config, encode,
`MEDIA_ASSET` write — driven with the ComfyUI call and encode **stubbed/mocked**, no GPU), and
**benchmark/manual** (the actual clip time, VRAM, and visual quality on the RTX 8000 — like the
image A/B, these are marked `benchmark` and run against real weights, not in the unit suite).

## Functional

### FR-016-01 — Fixed job payload + structured result
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-016-01-01 | unit | happy | A valid job payload is accepted and parsed (all fields) | automated |
| TC-FR-016-01-02 | unit | negative | A malformed/incomplete payload is rejected before any GPU work | automated |
| TC-FR-016-01-03 | unit | mapping | Result carries output path + timing + status | automated |

### FR-016-02 — Wan image+text→video at low configurable resolution/duration
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-016-02-01 | unit | mapping | Job resolution/duration/fps flow into the ComfyUI graph inputs | automated |
| TC-FR-016-02-02 | unit | boundary | Frame count = round(duration×fps) honored (≈65 @ 4 s/16 fps) | automated |
| TC-FR-016-02-03 | benchmark | happy | A real clip at the target low res animates the keyframe | benchmark |

### FR-016-03 — Lightning 4-step + GGUF on Turing (no FP8)
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-016-03-01 | unit | mapping | The graph loads GGUF weights + the Lightning LoRA at the configured step count | automated |
| TC-FR-016-03-02 | unit | boundary | Step count defaults to 4 and is config-driven | automated |
| TC-FR-016-03-03 | benchmark | happy | Real generation runs on the Turing GPU with no FP8 path | benchmark |

### FR-016-04 — Model-swappable behind the fixed API
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-016-04-01 | unit | happy | Switching tier (5B↔A14B) / quant changes config only, not the job schema | automated |
| TC-FR-016-04-02 | unit | mapping | The chosen tier/quant resolves to concrete weight paths | automated |

### FR-016-05 — Frames → Telegram MP4, atomic store
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-016-05-01 | unit | happy | Frames encode to H.264/yuv420p/faststart MP4 at the job fps | automated |
| TC-FR-016-05-02 | unit | happy | Output lands atomically at media/&lt;slug&gt;/videos/&lt;MED-id&gt;.mp4 | automated |
| TC-FR-016-05-03 | integration | error | A failed encode leaves no partial .mp4 (temp+rename) | automated |

### FR-016-06 — MEDIA_ASSET row
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-016-06-01 | integration | happy | A stored clip writes a kind=video, intimate=true row with dims/duration/fps | automated |
| TC-FR-016-06-02 | integration | mapping | The row references the source keyframe + generation metadata | automated |

### FR-016-07 — Hard safety gate (CRITICAL)
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-016-07-01 | unit | error | A job with no F-014 clearance generates NOTHING (no frames, no files) | automated |
| TC-FR-016-07-02 | unit | error | An invalid/forged clearance is refused (fail closed) | automated |
| TC-FR-016-07-03 | unit | security | The hard never-generate boundary cannot be bypassed by any field/prompt | automated |

### FR-016-08 — Idempotent by MED-id (resume)
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-016-08-01 | integration | idempotency | Existing MED-id output → no-op, no regeneration | automated |
| TC-FR-016-08-02 | integration | idempotency | Re-running an interrupted batch skips completed jobs | automated |

### FR-016-09 — Degrade cleanly on failure
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-016-09-01 | integration | error | A generation error marks the job failed, leaves no partial output | automated |
| TC-FR-016-09-02 | integration | error | VRAM is released in finally; the next job still runs | automated |
| TC-FR-016-09-03 | integration | error | One failed job does not stop the batch | automated |

### FR-016-10 — GPU day/night handoff
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-016-10-01 | unit | happy | Video waits when the chat LLM holds the GPU / it is not the night window | automated |
| TC-FR-016-10-02 | unit | happy | Wan loads once and stays resident across the batch | automated |
| TC-FR-016-10-03 | integration | boundary | Wan unloads / frees VRAM before the awake window | automated |

### FR-016-11 — Isolated runner, no import coupling
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-016-11-01 | unit | security | services/bot never imports the video/ runner | automated |
| TC-FR-016-11-02 | unit | mapping | Interaction is only via the job API + media/ archive | automated |

### FR-016-12 — Repeatable benchmark
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-016-12-01 | benchmark | happy | The bench reports clip time + peak VRAM + sample per tier×quant | benchmark |
| TC-FR-016-12-02 | benchmark | boundary | The bench flags configs that miss the 4 s/≈90 s target | benchmark |

### FR-016-13 — Auditable generation
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-016-13-01 | unit | happy | Tier/quant/steps/seed/res/frames/timing recorded with the asset | automated |
| TC-FR-016-13-02 | unit | mapping | The recorded config can reproduce the same clip (seed honored) | automated |

## Non-functional

### NFR-016-01 — Speed target (CRITICAL, benchmark)
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-NFR-016-01-01 | benchmark | performance | ~4 s clip generates in ≈90 s (≤150 s hard cap) on the RTX 8000 | benchmark |
| TC-NFR-016-01-02 | benchmark | boundary | Time scales as expected with frames/resolution | benchmark |

### NFR-016-02 — Fits the GPU without FP8 / CPU-offload
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-NFR-016-02-01 | benchmark | performance | Peak VRAM fits 48 GB with headroom, no sequential CPU-offload | benchmark |

### NFR-016-03 — Never on the hot path
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-NFR-016-03-01 | unit | mapping | No reply path invokes the video runner | automated |

### NFR-016-04 — Isolation provable
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-NFR-016-04-01 | unit | security | Import-graph assertion: services/bot ⇏ video/ | automated |

### NFR-016-05 — Durability/atomicity
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-NFR-016-05-01 | integration | persistence | Crash mid-gen → complete clip+row or nothing for that MED-id | automated |

### NFR-016-06 — Safety absolute (fail closed)
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-NFR-016-06-01 | unit | security | Malformed/adversarial payload → refuse (fail closed), never generate | automated |
| TC-NFR-016-06-02 | unit | security | Ambiguous clearance → treated as not cleared | automated |

### NFR-016-07 — Batch throughput
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-NFR-016-07-01 | benchmark | load | A roster's worth of clips fits the configured night window | benchmark |

### NFR-016-08 — Config without code change
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-NFR-016-08-01 | unit | happy | Resolution/duration/fps/tier/quant/steps/window come from config | automated |

### NFR-016-09 — Reproducibility
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-NFR-016-09-01 | unit | consistency | Same seed+config → same job graph inputs (deterministic setup) | automated |

## User-story acceptance (manual / benchmark)
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-US-016-01-01 | e2e | manual | The clip is smooth and unmistakably her (human-judged) | benchmark |
| TC-US-016-02-01 | e2e | manual | Intimate video refused outside the F-014 boundary end-to-end | benchmark |
| TC-US-016-03-01 | benchmark | manual | 4 s/≈90 s target met on the RTX 8000 | benchmark |
| TC-US-016-06-01 | benchmark | manual | The bench drives the tier/quant production decision | benchmark |

## Coverage summary
- **Functional FR-016-01..13:** ~30 TCs (unit/integration automated + benchmark for the real-GPU
  ones), 3 for the critical safety gate (FR-016-07).
- **Non-functional NFR-016-01..09:** ~11 TCs (automated where logic-testable; benchmark for
  speed/VRAM/throughput).
- **User stories:** 4 manual/benchmark acceptance TCs.
- **Grand total: ~45 enumerated tests.** The automated subset (job contract, gate, idempotency,
  atomicity, isolation, config, encode, MEDIA_ASSET) is CI-runnable with the GPU stubbed; the
  `benchmark`-marked cases are the measured 4 s/≈90 s decision on real weights.
