"""
populate_strategy_badges.py
─────────────────────────────────────────────────────────────────────────────
將 StrategyPanel.tsx 中硬編碼的 stratMeta（assets / rebalance_freq /
strategy_type / strategy_type_color）寫入 Supabase strategy_signals 表的
新欄位（migration 020_strategy_badges.sql 建立的四個欄位）。

執行前提：
  1. 已在 Supabase 執行 020_strategy_badges.sql
  2. 環境變數 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 已設定

用法：
  uv run python scripts/populate_strategy_badges.py [--dry-run]

  --dry-run  只印出將寫入的內容，不實際呼叫 Supabase API
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ─────────────────────────────────────────────────────────────────────────────
# Badge metadata（來自 StrategyPanel.tsx stratMeta，並補全所有 STRATEGY_REGISTRY 策略）
# key 必須與 strategy_signals.strategy_key 完全一致
# ─────────────────────────────────────────────────────────────────────────────
BADGE_META: dict[str, dict] = {
    # ── 主動上線策略（is_active=True） ──────────────────────────────────────
    "slow_vt": {
        "assets":              ["SPY"],
        "rebalance_freq":      "日頻",
        "strategy_type":       "標準",
        "strategy_type_color": "bg-gray-700 text-gray-300",
    },
    "risk_parity": {
        "assets":              ["SPY", "GLD"],
        "rebalance_freq":      "日頻",
        "strategy_type":       "標準",
        "strategy_type_color": "bg-gray-700 text-gray-300",
    },
    "simple_12vix": {
        "assets":              ["SPY"],
        "rebalance_freq":      "日頻",
        "strategy_type":       "標準",
        "strategy_type_color": "bg-gray-700 text-gray-300",
    },
    "recommended_5050": {
        "assets":              ["SPY", "GLD"],
        "rebalance_freq":      "日頻",
        "strategy_type":       "推薦",
        "strategy_type_color": "bg-emerald-900/60 text-emerald-400",
    },
    # daily_update.py 使用 "taiwan_8.63vix"（含點號）
    "taiwan_8.63vix": {
        "assets":              ["0050.TW"],
        "rebalance_freq":      "日頻",
        "strategy_type":       "台股",
        "strategy_type_color": "bg-blue-900/60 text-blue-400",
    },
    "vix_leading_guard": {
        "assets":              ["0050.TW"],
        "rebalance_freq":      "日頻",
        "strategy_type":       "台股",
        "strategy_type_color": "bg-blue-900/60 text-blue-400",
    },
    "vix_cond_leverage": {
        "assets":              ["SPY", "GLD"],
        "rebalance_freq":      "月頻",
        "strategy_type":       "積極",
        "strategy_type_color": "bg-red-900/60 text-red-400",
    },
    "taiwan_hybrid_leverage": {
        "assets":              ["0050.TW"],
        "rebalance_freq":      "月頻",
        "strategy_type":       "台股積極",
        "strategy_type_color": "bg-red-900/60 text-red-400",
    },
    "piecewise_conservative": {
        "assets":              ["SPY", "GLD"],
        "rebalance_freq":      "日頻",
        "strategy_type":       "保守",
        "strategy_type_color": "bg-cyan-900/60 text-cyan-400",
    },
    "fear_dca": {
        "assets":              ["SPY"],
        "rebalance_freq":      "月投",
        "strategy_type":       "定期定額",
        "strategy_type_color": "bg-purple-900/60 text-purple-400",
    },
    "adaptive_tier": {
        "assets":              ["SPY", "GLD"],
        "rebalance_freq":      "日頻",
        "strategy_type":       "平衡",
        "strategy_type_color": "bg-yellow-900/60 text-yellow-400",
    },
    # ── 非主動上線策略（is_active=False，保留 paper trading 記錄） ──────────
    "taiwan_spy_momentum": {
        "assets":              ["0050.TW"],
        "rebalance_freq":      "日頻",
        "strategy_type":       "台股",
        "strategy_type_color": "bg-blue-900/60 text-blue-400",
    },
    "tz_tw_jp_5050": {
        "assets":              ["0050.TW", "1306.T"],
        "rebalance_freq":      "日頻",
        "strategy_type":       "跨市場",
        "strategy_type_color": "bg-indigo-900/60 text-indigo-400",
    },
    "global_vt_tz": {
        "assets":              ["SPY", "0050.TW"],
        "rebalance_freq":      "日頻",
        "strategy_type":       "跨市場",
        "strategy_type_color": "bg-indigo-900/60 text-indigo-400",
    },
}


def _supabase_client():
    """Build a minimal Supabase REST client using requests."""
    import requests  # noqa: PLC0415

    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in the environment."
        )

    session = requests.Session()
    session.headers.update(
        {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
    )
    return session, url


def fetch_existing_keys(session, base_url: str) -> dict[str, int]:
    """Return {strategy_key: id} for all rows in strategy_signals."""
    resp = session.get(
        f"{base_url}/rest/v1/strategy_signals",
        params={"select": "id,strategy_key"},
    )
    resp.raise_for_status()
    return {row["strategy_key"]: row["id"] for row in resp.json()}


def patch_badge(session, base_url: str, row_id: int, meta: dict, dry_run: bool) -> bool:
    payload = {
        "assets":              meta["assets"],
        "rebalance_freq":      meta["rebalance_freq"],
        "strategy_type":       meta["strategy_type"],
        "strategy_type_color": meta["strategy_type_color"],
    }
    if dry_run:
        print(f"  [dry-run] PATCH id={row_id}  {json.dumps(payload, ensure_ascii=False)}")
        return True

    resp = session.patch(
        f"{base_url}/rest/v1/strategy_signals",
        params={"id": f"eq.{row_id}"},
        json=payload,
    )
    if resp.status_code not in (200, 204):
        print(f"  ✗ PATCH id={row_id} failed: {resp.status_code} {resp.text[:200]}")
        return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Populate strategy badge columns in Supabase")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing to DB")
    args = parser.parse_args()

    dry_run: bool = args.dry_run

    if dry_run:
        print("=== DRY RUN — no DB writes ===\n")

    session, base_url = _supabase_client()

    existing = fetch_existing_keys(session, base_url)
    print(f"Found {len(existing)} strategy_signals rows in DB.\n")

    ok_count = 0
    skip_count = 0
    err_count = 0

    for key, meta in BADGE_META.items():
        if key not in existing:
            print(f"  [skip] '{key}' not found in DB (not yet added via add_strategy.py)")
            skip_count += 1
            continue

        row_id = existing[key]
        print(f"  → {key}  (id={row_id})  assets={meta['assets']}  freq={meta['rebalance_freq']}  type={meta['strategy_type']}")
        ok = patch_badge(session, base_url, row_id, meta, dry_run)
        if ok:
            ok_count += 1
        else:
            err_count += 1

    print(f"\n{'[dry-run] ' if dry_run else ''}Done — updated={ok_count}  skipped={skip_count}  errors={err_count}")
    if err_count:
        sys.exit(1)


if __name__ == "__main__":
    main()
