"""F-008 Image Generation Runner — the isolated night-batch engine (architecture.md §3.9, §6.2c).

Callers interact ONLY through the fixed job contract (`contract.GenerationJob`) and the queue
(`queue_ops`): enqueue → the night batch generates → assets appear in media/ + MEDIA_ASSET rows.
No model code leaks out of `backends`; the heavy GPU stack lives in the separate ComfyUI process
(image/.venv), keeping this package importable from the bot env (NFR-008-07).
"""
