# F-018 — Voice Video Circles — test specification

Mirror of `developer files/features/F-018-voice-video-circles.md`. Every TC id embeds the
`FR-`/`NFR-`/`US-` id it verifies. Automated tests stub the LLM script step, the ElevenLabs client,
and the avatar-render job API (no GPU, no external billing); `benchmark` rows are the real-GPU /
real-TTS acceptance runs (lip-sync and identity are human-judged, like the image A/B).

## Functional

### FR-018-01 — Nightly pipeline produces one shared circle per persona per day
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-018-01-01 | integration | happy | A full pipeline pass yields one video_note asset for (persona, today) | automated |
| TC-FR-018-01-02 | integration | boundary | Second pass same day → no second asset (shared, single) | automated |
| TC-FR-018-01-03 | integration | happy | All roster personas are attempted independently | automated |

### FR-018-02 — Script from her own F-006 material
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-018-02-01 | unit | happy | Script builder consumes reflection/plan text, first person, her language | automated |
| TC-FR-018-02-02 | unit | boundary | Spoken length target ~15-30s enforced (word budget) | automated |
| TC-FR-018-02-03 | consistency | mapping | Script content is consistent with the plan slots she'll cite in chat | automated |

### FR-018-03 — ElevenLabs voice with her profile; audio cached
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-018-03-01 | unit | mapping | TTS is called with voice_profile_ref + script | automated |
| TC-FR-018-03-02 | integration | idempotency | Render retry reuses cached audio (no second TTS call) | automated |

### FR-018-04 — Audio-driven talking head (true lip-sync), identity-conditioned
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-018-04-01 | unit | mapping | The render job carries the face reference + the TTS audio | automated |
| TC-FR-018-04-02 | benchmark | happy | Lips track the audio on a real render (human-judged) | benchmark |

### FR-018-05 — Model-agnostic behind the fixed job API (S2V / Hunyuan)
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-018-05-01 | unit | happy | Switching candidate A↔B changes config only, not the pipeline contract | automated |
| TC-FR-018-05-02 | unit | mapping | Each candidate resolves to its own weights/runtime config | automated |

### FR-018-06 — Bench decides the production model
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-018-06-01 | benchmark | happy | Bench reports lip-sync, identity, time, VRAM per candidate | benchmark |
| TC-FR-018-06-02 | benchmark | boundary | Bench flags a candidate that cannot fit the night slot on Turing | benchmark |

### FR-018-07 — Telegram video-note format, atomic store, shared catalog row
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-018-07-01 | unit | happy | Output is square, ≤60s, mp4/H.264 (video_note-valid) | automated |
| TC-FR-018-07-02 | integration | happy | Catalog row: kind=video_note, shared, date-tagged, provenance | automated |
| TC-FR-018-07-03 | integration | error | Failed encode leaves no partial file/row (temp+rename) | automated |

### FR-018-08 — Idempotent per (persona, date); resume reuses completed steps
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-018-08-01 | integration | idempotency | Re-run after crash: existing script+audio reused, only missing steps run | automated |
| TC-FR-018-08-02 | integration | idempotency | Completed circle → full re-run is a no-op | automated |

### FR-018-09 — Degrade cleanly at every step (CRITICAL)
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-018-09-01 | integration | error | Script-LLM failure → persona skipped, last good circle kept | automated |
| TC-FR-018-09-02 | integration | error | TTS outage → skip + log; rest of the batch proceeds | automated |
| TC-FR-018-09-03 | integration | error | Render/encode failure → no partial asset; last good circle kept | automated |

### FR-018-10 — Night GPU rotation compliance
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-018-10-01 | unit | happy | Render jobs run only in the assigned night slot | automated |
| TC-FR-018-10-02 | unit | mapping | S2V shares the Wan slot; Hunyuan registers its own | automated |
| TC-FR-018-10-03 | integration | boundary | VRAM released before the chat reload deadline | automated |

### FR-018-11 — Intro circle via the same pipeline (one-off)
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-018-11-01 | integration | happy | A one-off intro render produces intro_videonote_ref content | automated |
| TC-FR-018-11-02 | consistency | mapping | Intro and daily circles share identity/voice config | automated |

### FR-018-12 — Auditable
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-FR-018-12-01 | unit | happy | Script text, TTS params, model, seed, timings, F-006 sources recorded | automated |

## Non-functional

### NFR-018-01 — Cost scales with roster
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-NFR-018-01-01 | unit | boundary | One render + one TTS per persona/day regardless of user count | automated |

### NFR-018-02 — Night-window fit
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-NFR-018-02-01 | unit | boundary | Overcommitted config refused at planning | automated |
| TC-NFR-018-02-02 | benchmark | load | A real roster's circles fit the slot | benchmark |

### NFR-018-03 — No hot-path generation
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-NFR-018-03-01 | unit | mapping | User interactions serve from catalog only; no TTS/render inline | automated |

### NFR-018-04 — Identity/voice consistency across days
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-NFR-018-04-01 | benchmark | consistency | Same face + voice across consecutive daily circles (human-judged) | benchmark |

### NFR-018-05 — External-API resilience, secrets in env
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-NFR-018-05-01 | unit | error | TTS retries with backoff inside the window, then degrades | automated |
| TC-NFR-018-05-02 | unit | security | No API key in code; key comes from env/config | automated |

### NFR-018-06 — Isolation
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-NFR-018-06-01 | unit | security | services/bot imports no pipeline/runner internals | automated |

### NFR-018-07 — Config-driven
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-NFR-018-07-01 | unit | happy | Script length/TTS/model/resolution/slot all from config | automated |

### NFR-018-08 — Privacy: no user facts in shared circles (CRITICAL)
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-NFR-018-08-01 | unit | security | Script builder has no access path to USER_FACT / per-user data | automated |
| TC-NFR-018-08-02 | integration | security | A crafted user fact never appears in any circle script | automated |

## User-story acceptance (manual / benchmark)
| TC | level | case | title | status |
|----|-------|------|-------|--------|
| TC-US-018-01-01 | e2e | manual | The intro circle lands the "she's real" first impression | benchmark |
| TC-US-018-02-01 | e2e | manual | The daily circle's story matches her chat answers that day | benchmark |
| TC-US-018-03-01 | e2e | manual | Lip-sync + identity survive skeptic scrutiny | benchmark |
| TC-US-018-04-01 | benchmark | manual | One render served to multiple users (shared asset verified) | benchmark |

## Coverage summary
- **Functional FR-018-01..12:** 27 TCs (24 automated + 3 benchmark), 3 for the critical degrade
  chain (FR-018-09).
- **Non-functional NFR-018-01..08:** 11 TCs (9 automated + 2 benchmark), 2 for the critical
  privacy rule (NFR-018-08).
- **User stories:** 4 manual/benchmark acceptance TCs.
- **Grand total: 42 enumerated tests.**
