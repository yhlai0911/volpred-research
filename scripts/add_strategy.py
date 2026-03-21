"""新增交易策略到系統（只寫 DB，不需改前端代碼、不需重新部署）。"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from supabase_sync import set_strategy_active, sync_strategy_signal


def main():
    parser = argparse.ArgumentParser(description="Manage trading strategies (DB only, no deploy needed)")
    parser.add_argument("--id", help="Strategy ID (snake_case)")
    parser.add_argument("--name", help="Display name")
    parser.add_argument("--howto", help="One-line operation instruction")
    parser.add_argument("--description", help="Full operation description")
    parser.add_argument("--color", default="#6B7280", help="Chart color (hex)")
    parser.add_argument("--assets", help="Initial asset weights as JSON")
    parser.add_argument("--order", type=int, default=7, help="Display order")
    parser.add_argument("--articles", default="[]", help="Related articles as JSON array")
    parser.add_argument("--deactivate", help="Deactivate strategy by name (hide from panel)")
    parser.add_argument("--activate", help="Re-activate strategy by name")
    args = parser.parse_args()

    if args.deactivate:
        print(f"Deactivating: {args.deactivate}")
        if not set_strategy_active(args.deactivate, False):
            raise SystemExit(1)
        print(f"✓ {args.deactivate} → is_active=false (hidden from panel)")
        return

    if args.activate:
        print(f"Activating: {args.activate}")
        if not set_strategy_active(args.activate, True):
            raise SystemExit(1)
        print(f"✓ {args.activate} → is_active=true (visible in panel)")
        return

    # Add new strategy
    if not args.id or not args.name or not args.howto or not args.description or not args.assets:
        parser.error("--id, --name, --howto, --description, --assets are required for adding a strategy")

    assets = json.loads(args.assets)
    articles = json.loads(args.articles)

    print(f"Adding strategy to DB: {args.id} → {args.name}")

    ok = sync_strategy_signal(
        args.name,
        assets,
        display_order=args.order,
        is_active=True,
        strategy_key=args.id,
        howto=args.howto,
        description=args.description,
        color=args.color,
        articles=articles,
    )
    if not ok:
        raise SystemExit(1)
    print(f"✓ Supabase strategy_signals updated")

    print(f"\n還需要手動做：")
    print(f"  1. daily_update.py — 加入 {args.id} 的計算邏輯")
    print(f"  2. 跑 3 年回測 → 更新 paper_trading.json + strategy_metrics.json")
    print(f"  3. 同步到 Supabase（paper_trades）")
    print(f"\n不需要重新部署前端 ✓")


if __name__ == "__main__":
    main()
