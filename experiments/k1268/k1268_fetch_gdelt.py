"""
K1268: Fetch GDELT 2.0 15-min export.CSV.zip files via public bulk endpoint.

Endpoint: http://data.gdeltproject.org/gdeltv2/{YYYYMMDDHHMMSS}.export.CSV.zip
- 96 files/day (every 15 min: :00, :15, :30, :45)
- No auth
- Rate-limit: 1 req/sec (conservative; their robots.txt allows aggressive but be polite)
"""
from __future__ import annotations

import io
import logging
import random
import sys
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import requests

# Seed all RNGs to comply with strict reproducibility (Codex review 2026-05-11)
random.seed(42)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("k1268_fetch")

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

BASE = "http://data.gdeltproject.org/gdeltv2"
RATE_LIMIT_SEC = 1.0
MAX_RETRIES = 3
TIMEOUT = 30

# Three event days (UTC 00:00 -> 23:45)
# GDELT 2.0 starts 2015-02-18; 2008 Lehman not available -> use SVB collapse instead.
EVENT_DAYS = [
    "2024-08-05",  # Nikkei flash crash / yen-carry unwind
    "2020-03-12",  # COVID-19 WHO pandemic declaration aftermath, SPY -9.5%
    "2023-03-13",  # SVB / Signature aftermath, regional bank stress
]


def slot_iter(date_str: str):
    """Yield YYYYMMDDHHMMSS strings for all 96 15-min slots of given date (UTC)."""
    base = datetime.strptime(date_str, "%Y-%m-%d")
    for i in range(96):
        ts = base + timedelta(minutes=15 * i)
        yield ts.strftime("%Y%m%d%H%M%S")


def fetch_one(slot: str, kind: str = "export") -> bytes | None:
    """Fetch one 15-min export.CSV.zip; return CSV bytes (decoded from zip) or None."""
    url = f"{BASE}/{slot}.{kind}.CSV.zip"
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(url, timeout=TIMEOUT)
            if r.status_code == 404:
                # Some early 2008/2020 slots may not exist in v2 (v2 starts 2015-02-18)
                log.warning("404 %s", url)
                return None
            if r.status_code >= 500:
                raise requests.HTTPError(f"5xx {r.status_code}")
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                names = zf.namelist()
                if not names:
                    return None
                return zf.read(names[0])
        except Exception as e:  # noqa: BLE001
            wait = (2**attempt) + random.random()
            log.warning("retry %d for %s: %s (sleep %.1fs)", attempt + 1, slot, e, wait)
            time.sleep(wait)
    log.error("FAILED %s after %d attempts", slot, MAX_RETRIES)
    return None


def fetch_day(date_str: str) -> dict:
    """Fetch all 96 slots for one date; save raw CSV per slot under data/<date>/."""
    out_dir = DATA_DIR / date_str
    out_dir.mkdir(exist_ok=True)
    ok, miss = 0, 0
    for slot in slot_iter(date_str):
        out_path = out_dir / f"{slot}.export.csv"
        if out_path.exists() and out_path.stat().st_size > 0:
            ok += 1
            continue
        data = fetch_one(slot, "export")
        if data is None:
            miss += 1
            out_path.write_bytes(b"")  # marker so we don't re-try
        else:
            out_path.write_bytes(data)
            ok += 1
        time.sleep(RATE_LIMIT_SEC)
    log.info("%s: ok=%d miss=%d", date_str, ok, miss)
    return {"date": date_str, "ok": ok, "miss": miss}


def main():
    summary = []
    for d in EVENT_DAYS:
        # GDELT 2.0 only goes back to 2015-02-18; 2008-09-15 will be all-miss.
        # We attempt anyway and fall back to skipping in aggregator.
        if d < "2015-02-18":
            log.warning("%s pre-dates GDELT 2.0 (2015-02-18); will be empty", d)
        summary.append(fetch_day(d))
    out = Path(__file__).parent / "fetch_summary.json"
    import json
    out.write_text(json.dumps(summary, indent=2))
    log.info("Done. Summary: %s", summary)


if __name__ == "__main__":
    sys.exit(main() or 0)
