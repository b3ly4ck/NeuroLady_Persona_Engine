"""chat/smoke.py — the "reference" check for the chat runner.

Sends a couple of Chat Completions to the running serve.py endpoint and prints latency and
tokens/second. These numbers are the empirical baseline the F-002 reply-latency budget
(NFR-002-01, "< 5s on a warm model") is calibrated against.

Prereq: chat/serve.py is running and has logged "READY: model warm".

    chat/.venv/bin/python chat/smoke.py
    chat/.venv/bin/python chat/smoke.py --prompt "расскажи как прошёл твой день" --max-tokens 200
"""
from __future__ import annotations

import argparse
import os
import time

import httpx

# A minimal persona system prompt so the smoke output reads in-character (like the real F-002
# assembly will). Alina = Moscow psychologist & fitness enthusiast (architecture.md running example).
DEFAULT_SYSTEM = (
    "You are Alina, a 28-year-old woman from Moscow — a psychologist who loves fitness. "
    "You are texting a man you're getting to know. Reply like a real person over chat: warm, "
    "a little playful, casual and natural. Never say or imply you are an AI, a bot, or a model. "
    "Keep it short unless he asks for a story."
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("CHAT_BASE_URL", "http://127.0.0.1:8080"))
    ap.add_argument("--prompt", default="привет, как ты сегодня?")
    ap.add_argument("--system", default=DEFAULT_SYSTEM)
    ap.add_argument("--max-tokens", type=int, default=160)
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--runs", type=int, default=2)
    args = ap.parse_args()

    payload = {
        "messages": [
            {"role": "system", "content": args.system},
            {"role": "user", "content": args.prompt},
        ],
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "top_p": 0.9,
    }

    print(f"→ {args.base_url}  |  prompt: {args.prompt!r}\n")
    for i in range(1, args.runs + 1):
        t0 = time.monotonic()
        r = httpx.post(f"{args.base_url}/v1/chat/completions", json=payload, timeout=300.0)
        dt = time.monotonic() - t0
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"].strip()
        usage = data.get("usage", {})
        out_tok = usage.get("completion_tokens") or 0
        in_tok = usage.get("prompt_tokens") or 0
        tps = (out_tok / dt) if dt > 0 and out_tok else 0.0
        print(f"── run {i}/{args.runs} ─────────────────────────────────────────")
        print(text)
        print(
            f"\n[latency {dt:.2f}s | in {in_tok} tok | out {out_tok} tok | {tps:.1f} tok/s]\n"
        )


if __name__ == "__main__":
    main()
