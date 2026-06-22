#!/usr/bin/env python3
"""Headless Gemini caller — FALLBACK path for one-shot Q&A / fact-check.

Why this exists (2026-05-20 — fallback role):
- Primary headless Gemini = Antigravity CLI `agy -p`. This script is the
  FALLBACK: a dependency-free, API-key-authenticated path used when agy is
  unavailable or when a pure pipe-able one-shot API call is wanted.
- agy uses Google OAuth; this uses an API key (GOOGLE_CLOUD_API_KEY) — two
  independent auth paths, so a single auth outage can't kill the whole line.
- Independent of gemini-cli (which stops serving 2026-06-18); this calls the
  Gemini API directly and keeps working after that date.

⚠️ COST: every successful call hits the PAID Gemini API. This script notifies
the admin by email on each use (see _notify_usage) — keep usage rare; prefer
agy for normal work.

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
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "gemini-3.1-pro-preview"
API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_USAGE_LOG = REPO / "storage" / "logs" / "gemini_ask_usage.jsonl"


def _warn_usage_notification(message: str, exc: Exception) -> None:
    print(f"⚠️  [gemini_ask.py] {message}: {type(exc).__name__}: {exc}", file=sys.stderr)


def _caller() -> str:
    """Best-effort identification of the parent process (who invoked us)."""
    try:
        ppid = os.getppid()
        comm = subprocess.run(
            ["ps", "-p", str(ppid), "-o", "comm="],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        return f"{comm or '?'} (ppid={ppid})"
    except Exception:
        return "unknown"


def _notify_usage(model: str, prompt: str, response_chars: int) -> None:
    """Record + loudly notify the admin that gemini_ask.py was used (= paid
    Gemini API call). Runs after every SUCCESSFUL call. Best-effort: a failure
    here never blocks the answer the caller already received.

    User directive 2026-05-20: gemini_ask.py is a fallback — any use means
    money spent, so it must emphatically notify.
    """
    ts = datetime.now(timezone.utc).isoformat()
    caller = _caller()
    # 1. Append to the usage ledger (always — the reliable record).
    try:
        _USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _USAGE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": ts, "model": model, "caller": caller,
                "prompt_chars": len(prompt), "response_chars": response_chars,
            }, ensure_ascii=False) + "\n")
    except Exception as exc:
        _warn_usage_notification("usage ledger write failed", exc)
    # 2. Loud stderr banner (visible to interactive / cron-log readers).
    print(
        f"\n⚠️  [gemini_ask.py] PAID Gemini API call — model={model}, "
        f"caller={caller}, prompt={len(prompt)}字 → 已通知 admin\n",
        file=sys.stderr,
    )
    # 3. Email the admin (--force bypasses 24h dedup so EVERY use notifies).
    body = (
        "## 觸發條件\n"
        f"scripts/gemini_ask.py 於 {ts} 被呼叫並成功打 Gemini API。\n"
        f"- caller: {caller}\n- model: {model}\n"
        f"- prompt {len(prompt)} 字 / 回應 {response_chars} 字\n"
        "## 影響\n"
        "此呼叫直接打 PAID Gemini API → 產生實際 API 費用。gemini_ask.py 是 "
        "agy 的 fallback，正常情況不應頻繁觸發；短時間多次出現代表 agy 或主"
        "路徑可能異常。\n"
        "## 建議行動\n"
        "查 storage/logs/gemini_ask_usage.jsonl 看呼叫頻率與 caller。若非預期："
        "查為何沒走 agy；若為單次 fallback：忽略即可。"
    )
    try:
        subprocess.run(
            ["uv", "run", "volpred", "ops", "send-alert", "--force",
             "--level", "warn",
             "--title", "⚠️ gemini_ask.py 已呼叫 — 產生 Gemini API 費用",
             "--body", body],
            cwd=str(REPO), capture_output=True, timeout=60,
        )
    except Exception as exc:
        _warn_usage_notification("admin alert send failed", exc)


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
    answer = ask(prompt, model=model)
    print(answer)
    # Notify admin AFTER the answer is on stdout — paid API call just happened.
    _notify_usage(model, prompt, len(answer))
    return 0


if __name__ == "__main__":
    sys.exit(main())
