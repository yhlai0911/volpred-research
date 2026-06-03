#!/usr/bin/env python3
"""Generate an image via the OpenAI Images API (gpt-image-2, fallback gpt-image-1).

WHY (2026-06-03): user authorized generating a VolPred FB-page logo (and future
assets) with gpt-image. Reusable so later asset needs (covers, post graphics) reuse it.

⚠️ PAID API. Logs every call to storage/logs/openai_image_usage.jsonl (mirrors the
gemini_ask paid-call discipline). Reads OPENAI_API_KEY from .env (never hardcoded).

Usage:
    uv run python scripts/gen_image.py --prompt "..." --out path.png [--size 1024x1024]
"""
from __future__ import annotations
import argparse, base64, json, os, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _key() -> str:
    for fname in (".env", ".env.local"):
        p = ROOT / fname
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("OPENAI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("OPENAI_API_KEY", "")


def _log(model: str, size: str, out: str, ok: bool):
    rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "api": "openai_images", "model": model, "size": size, "out": out, "ok": ok}
    d = ROOT / "storage" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "openai_image_usage.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def gen(prompt: str, out: Path, size: str) -> bool:
    key = _key()
    if not key:
        print("No OPENAI_API_KEY"); return False
    for model in ("gpt-image-2", "gpt-image-1"):
        body = json.dumps({"model": model, "prompt": prompt, "size": size, "n": 1}).encode()
        req = urllib.request.Request("https://api.openai.com/v1/images/generations",
                                     data=body, method="POST",
                                     headers={"Authorization": f"Bearer {key}",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.loads(r.read().decode())
            b64 = data["data"][0]["b64_json"]
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(base64.b64decode(b64))
            _log(model, size, str(out), True)
            print(f"OK model={model} -> {out} ({out.stat().st_size} bytes)")
            return True
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:300]
            print(f"model={model} HTTP {e.code}: {msg}")
            _log(model, size, str(out), False)
            if model == "gpt-image-1":
                return False
            # else try fallback
        except Exception as e:
            print(f"model={model} ERR: {e}")
            _log(model, size, str(out), False)
            return False
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", default="1024x1024")
    a = ap.parse_args()
    return 0 if gen(a.prompt, Path(a.out), a.size) else 1


if __name__ == "__main__":
    raise SystemExit(main())
