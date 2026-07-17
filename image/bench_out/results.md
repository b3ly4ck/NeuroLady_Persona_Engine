# Image-generation A/B benchmark

| Candidate | steps | load (s) | avg gen (s/img) | peak VRAM (GB) | images | notes | error |
|-----------|------:|---------:|----------------:|---------------:|-------:|-------|-------|
| A_rapid_aio_v23 | 4 | 24.0 | 117.16 | 40.3 | 3 | gen[0] includes lazy checkpoint load into VRAM | — |
| B_diffusers_lightning | 8 | 5.4 | 423.60 | 23.4 | 3 | bf16 does not fit (51GB free); ran with sequential_cpu_offload | — |

Realism is judged visually from the saved images in `bench_out/{A,B}/`.
Decision factors: realism, s/image, load/unload time (day↔night cadence), VRAM headroom.