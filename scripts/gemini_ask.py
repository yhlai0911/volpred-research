#!/usr/bin/env python3
"""Headless Gemini caller — replaces `gemini -p` for second-opinion / fact-check.

Why this exists:
- gemini-cli 0.42 (oauth-personal) stops serving 2026-06-18 (transition to Antigravity CLI).
- Antigravity `agy chat` opens a GUI IDE chat — NO stdout pipe, unusable for headless.
- This wrapper hits the Gemini API directly via GOOGLE_CLOUD_API_KEY → true stdout pipe.
- API key path has Gemini 3 access (gemini-3.1-pro-preview verified 2026-05-20).

Usage:
    uv run python scripts/gemini_ask.py "your prompt"
    echo "long prompt" | uv run python scripts/gemini_ask.py -
    uv run python scripts/gemini_ask.py --model gemini-2.5-flash "quick question"

Default model: gemini-3.1-pro-preview (best available under API key, 2026-05-20).
Exit 0 + answer to stdout on success; exit 1 + error to stderr on failure.
"""
from __future__ import annotations
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "gemini-3.1-pro-preview"
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def load_api_key() -> str:
    # env first, then .env / .env.local
    key = os.environ.get("GOOGLE_CLOUD_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    for fname in (".env", ".env.local"):
        p = REPO / fname
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if line.startswith(("GOOGLE_CLOUD_API_KEY=", "GEMINI_API_KEY=")):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ERROR: no GOOGLE_CLOUD_API_KEY / GEMINI_API_KEY found in env or .env")


def ask(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 120) -> str:
    key = load_api_key()
    url = f"{API_BASE}/{model}:generateContent?key={key}"
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:400]
        raise SystemExit(f"ERROR: Gemini API HTTP {e.code} — {detail}")
    except Exception as e:
        raise SystemExit(f"ERROR: Gemini API call failed — {e}")
    cands = data.get("candidates", [])
    if not cands:
        raise SystemExit(f"ERROR: no candidates in response — {str(data)[:300]}")
    parts = cands[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts)
    if not text:
        raise SystemExit(f"ERROR: empty response — finish_reason={cands[0].get('finishReason')}")
    return text


def main() -> int:
    args = sys.argv[1:]
    model = DEFAULT_MODEL
    if "--model" in args:
        i = args.index("--model")
        model = args[i + 1]
        args = args[:i] + args[i + 2:]
    if not args:
        print(__doc__, file=sys.stderr)
        return 1
    if args[0] == "-":
        prompt = sys.stdin.read()
    else:
        prompt = " ".join(args)
    if not prompt.strip():
        print("ERROR: empty prompt", file=sys.stderr)
        return 1
    print(ask(prompt, model=model))
    return 0


if __name__ == "__main__":
    sys.exit(main())
