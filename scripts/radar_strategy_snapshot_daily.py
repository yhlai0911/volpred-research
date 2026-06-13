"""
radar_strategy_snapshot_daily.py
─────────────────────────────────────────────────────────────────────────────
VolPred Radar P1 — 每日策略配置 snapshot job。

讀 canonical 策略配置（Supabase `strategy_signals` 表，is_active=true 的
strategy_key → weights jsonb，{asset: weight_pct}）+ metrics（`strategy_metrics_cache`
表 strategy → metrics jsonb），對「今天」(Asia/Taipei) 寫入一筆 per-strategy
snapshot 到 `radar_strategy_snapshots`。

冪等：靠 unique(snapshot_date, strategy_id) — 同日同策略已存在則 skip（不覆寫，
保留當日第一次 snapshot 的權威值）。重跑安全。

資料來源即線上 StrategyPanel / getStrategyOverview 顯示的同一張表，**真實數據，不造假**。

環境變數（讀 .env.local，禁硬編碼）：
  SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY

用法：
  uv run python scripts/radar_strategy_snapshot_daily.py            # 實跑（落地今日）
  uv run python scripts/radar_strategy_snapshot_daily.py --dry-run  # 只印不寫
  uv run python scripts/radar_strategy_snapshot_daily.py --date 2026-06-14  # 指定 snapshot_date
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
TAIPEI = ZoneInfo("Asia/Taipei")
SNAPSHOT_TABLE = "radar_strategy_snapshots"
SIGNALS_TABLE = "strategy_signals"
METRICS_TABLE = "strategy_metrics_cache"


def _load_env() -> tuple[str, str]:
    """Load SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY from .env.local (then env)."""
    for env_file in (REPO_ROOT / ".env.local", REPO_ROOT / ".env"):
        if not env_file.exists():
            continue
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY") and key not in os.environ:
                os.environ[key] = val
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set (.env.local or env)."
        )
    return url, key


def _session(key: str) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
    )
    return s


def fetch_active_strategies(session: requests.Session, base_url: str) -> list[dict]:
    """Active strategies = canonical Radar 配置 source (strategy_signals.is_active)."""
    resp = session.get(
        f"{base_url}/rest/v1/{SIGNALS_TABLE}",
        params={
            "select": "strategy_key,strategy_name,weights,is_active",
            "is_active": "eq.true",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_metrics(session: requests.Session, base_url: str) -> dict[str, dict]:
    """Return {strategy_key: metrics_blob}; metrics is nullable in snapshot."""
    resp = session.get(
        f"{base_url}/rest/v1/{METRICS_TABLE}",
        params={"select": "strategy,metrics"},
        timeout=30,
    )
    resp.raise_for_status()
    out: dict[str, dict] = {}
    for row in resp.json():
        key = row.get("strategy")
        if key:
            out[key] = row.get("metrics")
    return out


def fetch_existing_for_date(
    session: requests.Session, base_url: str, snapshot_date: str
) -> set[str]:
    """strategy_ids already snapshotted for this date (idempotency)."""
    resp = session.get(
        f"{base_url}/rest/v1/{SNAPSHOT_TABLE}",
        params={"select": "strategy_id", "snapshot_date": f"eq.{snapshot_date}"},
        timeout=30,
    )
    resp.raise_for_status()
    return {row["strategy_id"] for row in resp.json()}


def insert_snapshots(
    session: requests.Session, base_url: str, rows: list[dict]
) -> int:
    """Insert new snapshot rows. on_conflict=ignore_duplicates makes reruns safe."""
    if not rows:
        return 0
    resp = session.post(
        f"{base_url}/rest/v1/{SNAPSHOT_TABLE}",
        params={"on_conflict": "snapshot_date,strategy_id"},
        headers={"Prefer": "resolution=ignore-duplicates,return=representation"},
        data=json.dumps(rows),
        timeout=60,
    )
    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"insert failed: {resp.status_code} {resp.text[:400]}"
        )
    try:
        return len(resp.json())
    except Exception:  # noqa: BLE001
        return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="VolPred Radar daily strategy snapshot")
    parser.add_argument("--dry-run", action="store_true", help="Print, do not write")
    parser.add_argument(
        "--date",
        default=None,
        help="snapshot_date as YYYY-MM-DD (default: today in Asia/Taipei)",
    )
    args = parser.parse_args()

    snapshot_date = args.date or _dt.datetime.now(TAIPEI).date().isoformat()
    base_url, key = _load_env()
    session = _session(key)

    strategies = fetch_active_strategies(session, base_url)
    metrics_by_key = fetch_metrics(session, base_url)
    existing = (
        set()
        if args.dry_run
        else fetch_existing_for_date(session, base_url, snapshot_date)
    )

    print(f"snapshot_date={snapshot_date}  active_strategies={len(strategies)}  "
          f"already_snapshotted={len(existing)}")

    rows: list[dict] = []
    skipped = 0
    for s in strategies:
        sid = s.get("strategy_key")
        weights = s.get("weights")
        if not sid or not isinstance(weights, dict) or not weights:
            print(f"  [skip] '{sid}' missing/invalid weights")
            skipped += 1
            continue
        if sid in existing:
            print(f"  [skip] '{sid}' already snapshotted for {snapshot_date}")
            skipped += 1
            continue
        rows.append(
            {
                "snapshot_date": snapshot_date,
                "strategy_id": sid,
                "weights": weights,
                "metrics": metrics_by_key.get(sid),
            }
        )

    if args.dry_run:
        print("=== DRY RUN — no writes ===")
        for r in rows:
            print(f"  + {r['strategy_id']}: {json.dumps(r['weights'], ensure_ascii=False)}")
        print(f"would insert {len(rows)} rows, skip {skipped}")
        return 0

    inserted = insert_snapshots(session, base_url, rows)
    print(f"inserted {inserted} rows, skipped {skipped} "
          f"(total active {len(strategies)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
