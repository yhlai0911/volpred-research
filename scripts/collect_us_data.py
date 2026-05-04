"""美股數據收集（美股收盤後 07:03 台北時間執行）

收集：
- SPY/GLD/TLT/QQQ/EEM 日線（yfinance，DataManager 快取）
- ^VIX/^VIX3M/^N225 日線
- SPY 5-min data（用於 HAR-RV / Realized GARCH）
- FRED 總經指標（每週一更新）

Cron: 3 7 * * 2-6（週二至六 = 美股週一至五收盤後）
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import requests
import io

PROJECT = Path(__file__).resolve().parent.parent
VENV_PYTHON = PROJECT / ".venv" / "bin" / "python"

# 所有策略和研究需要的日頻資產
DAILY_TICKERS = ["SPY", "GLD", "TLT", "QQQ", "EEM", "^VIX", "^VIX3M", "^N225"]

# FRED 指標（月/週頻，每週一更新即可）
FRED_TICKERS = [
    "FEDFUNDS", "DGS10", "DGS2", "UNRATE", "CPIAUCSL", "PAYEMS",
    "INDPRO", "UMCSENT", "WALCL", "EFFR", "STLFSI4", "T10YIE",
    "ICSA", "BAMLH0A0HYM2", "HOUST", "PERMIT", "RSAFS", "M2SL",
    "PCEPILFE", "DGORDER", "AWHMAN", "GDP", "GDPC1",
]


def main():
    now = datetime.now()
    print(f"=== 美股數據收集: {now.strftime('%Y-%m-%d %H:%M')} ===")

    sys.path.insert(0, str(PROJECT / "src"))
    sys.path.insert(0, str(PROJECT / "scripts"))

    # 2026-05-04 silent-fail fix: track per-section ok/fail so cron exit
    # code surfaces real failures to check_alerts host_cron_fail. Previously
    # all errors were caught and main() returned None → exit 0 even on
    # full network outage.
    section_ok: dict[str, bool] = {}

    # 0. Supabase heartbeat (prevent free-tier auto-pause)
    try:
        from supabase_sync import _request_json, SUPABASE_URL
        _request_json(f"{SUPABASE_URL}/rest/v1/articles?select=count&limit=1")
        print("  Supabase heartbeat OK")
        section_ok["supabase_heartbeat"] = True
    except Exception:
        print("  Supabase heartbeat failed (DB may be paused)")
        section_ok["supabase_heartbeat"] = False

    # 1. 日線數據（force_refresh=True 強制從 yfinance 拉最新）
    print("\n--- 日線數據 ---")
    daily_ok = 0
    daily_total = len(DAILY_TICKERS)
    try:
        from volpred.data.manager import DataManager
        dm = DataManager()
        for ticker in DAILY_TICKERS:
            try:
                data = dm.get_model_data(ticker, "2020-01-01", "2026-12-31", force_refresh=True)
                print(f"  {ticker:8s}: {data.index[-1].date()} close={float(data.iloc[-1]['close']):.2f} ({len(data)} rows)")
                daily_ok += 1
            except Exception as e:
                print(f"  {ticker:8s}: error ({e})")
        section_ok["daily_us"] = daily_ok > 0
        print(f"  daily_us: {daily_ok}/{daily_total} tickers ok")
    except Exception as e:
        print(f"  DataManager error: {e}")
        section_ok["daily_us"] = False

    # 2. SPY 5-min data（Realized Volatility 用）
    print("\n--- SPY 5-min ---")
    try:
        result = subprocess.run(
            [str(VENV_PYTHON), str(PROJECT / "scripts" / "collect_5min_data.py")],
            cwd=str(PROJECT),
            timeout=120,
        )
        section_ok["spy_5min"] = result.returncode == 0
    except Exception as e:
        print(f"  5-min error: {e}")
        section_ok["spy_5min"] = False

    # 3. FRED 總經指標（每週一更新，其他天跳過以節省 API）
    weekday = now.weekday()  # 0=Monday
    if weekday == 0:  # 只在週一更新
        print("\n--- FRED 總經指標（週一更新）---")
        try:
            _collect_fred()
            section_ok["fred"] = True
        except Exception as e:
            print(f"  FRED error: {e}")
            section_ok["fred"] = False
    else:
        print(f"\n--- FRED: 跳過（週{weekday+1}，只在週一更新）---")

    print("\n✓ 美股數據收集完成")
    # Total-failure exit: if no section succeeded → cron exit 1.
    # Partial failures are exit 0 (normal — a single ticker error or
    # weekend FRED skip should not page the operator).
    if section_ok and not any(section_ok.values()):
        print(f"\n  [collect_us_data] FAIL: all sections failed: {section_ok}",
              file=sys.stderr)
        return 1
    return 0


def _collect_fred():
    """從 FRED 下載最新總經指標（直接 CSV，不依賴 pandas_datareader）。"""
    import pandas as pd

    base_url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
    macro_dir = PROJECT / "storage" / "macro"
    updated = 0
    failed = 0

    for ticker in sorted(FRED_TICKERS):
        outpath = macro_dir / f"fred_{ticker}.csv"
        try:
            url = f"{base_url}?id={ticker}"
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            df = pd.read_csv(io.StringIO(resp.text), index_col=0, parse_dates=True)
            df.columns = [ticker]
            df[ticker] = pd.to_numeric(df[ticker], errors="coerce")
            df.to_csv(outpath)
            last_valid = df.dropna().index[-1].strftime("%Y-%m-%d")
            print(f"  ✅ {ticker:20s} → {last_valid}")
            updated += 1
        except Exception as e:
            print(f"  ❌ {ticker:20s}: {str(e)[:60]}")
            failed += 1

    print(f"  FRED: {updated} updated, {failed} failed")


if __name__ == "__main__":
    sys.exit(main() or 0)
