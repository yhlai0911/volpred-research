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
    """從 FRED 下載最新總經指標。

    2026-05-29 fix: 公開 `fredgraph.csv` scraping endpoint 已被 FRED bot-detection
    擋掉（回傳 HTML/403），約 4/16 起所有日頻系列 (DGS10/DGS2/EFFR/BAMLH...)
    silent stale 6 週。改用官方 API (api.stlouisfed.org) + FRED_API_KEY
    (.env.local，2026-05-10 已備)。官方 API 不被 bot-block，回傳乾淨 JSON。
    """
    import os
    import pandas as pd

    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        # Load from .env.local if not in env (cron may not source profile)
        env_local = PROJECT / ".env.local"
        if env_local.exists():
            for line in env_local.read_text().splitlines():
                line = line.strip()
                if line.startswith("FRED_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break
    if not api_key:
        print("  ❌ FRED_API_KEY 缺失 (.env.local) — 無法抓 FRED；macro 數據將 stale")
        print("  FRED: 0 updated, 0 failed (no api key)")
        return

    api_url = "https://api.stlouisfed.org/fred/series/observations"
    macro_dir = PROJECT / "storage" / "macro"
    updated = 0
    failed = 0
    stale_warn = []

    import time

    def _fetch_with_retry(params, *, attempts=3):
        """FRED API 偶發 5xx (504 Gateway Timeout) — transient server-side.
        Retry with backoff before giving up (2026-05-29: FRED API outage during
        backfill). 4xx (bad key / bad series) fails fast, no retry."""
        last_exc = None
        for i in range(attempts):
            try:
                resp = requests.get(api_url, params=params, timeout=45)
                if resp.status_code >= 500:
                    last_exc = RuntimeError(f"HTTP {resp.status_code} (server-side)")
                    time.sleep(5 * (i + 1))
                    continue
                resp.raise_for_status()
                return resp
            except requests.exceptions.RequestException as e:
                last_exc = e
                time.sleep(5 * (i + 1))
        raise last_exc or RuntimeError("fetch failed")

    for ticker in sorted(FRED_TICKERS):
        outpath = macro_dir / f"fred_{ticker}.csv"
        try:
            params = {
                "series_id": ticker,
                "api_key": api_key,
                "file_type": "json",
                "observation_start": "2006-01-01",
            }
            resp = _fetch_with_retry(params)
            payload = resp.json()
            obs = payload.get("observations", [])
            if not obs:
                raise ValueError("empty observations")
            df = pd.DataFrame(obs)[["date", "value"]].copy()
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
            df.columns = [ticker]
            df[ticker] = pd.to_numeric(df[ticker], errors="coerce")
            valid = df.dropna()
            if valid.empty:
                raise ValueError("all values NaN after coerce")
            df.to_csv(outpath)
            last_valid = valid.index[-1].strftime("%Y-%m-%d")
            print(f"  ✅ {ticker:20s} → {last_valid}")
            updated += 1
            # Flag daily-frequency series that are >7 days stale (data integrity)
            if (datetime.now() - valid.index[-1].to_pydatetime()).days > 14 and ticker in {
                "DGS10", "DGS2", "EFFR", "BAMLH0A0HYM2", "T10YIE", "WALCL",
            }:
                stale_warn.append(f"{ticker}={last_valid}")
        except Exception as e:
            print(f"  ❌ {ticker:20s}: {str(e)[:60]}")
            failed += 1

    print(f"  FRED: {updated} updated, {failed} failed")
    if stale_warn:
        print(f"  ⚠️  FRED daily series >14d stale (check FRED publish): {stale_warn}")


if __name__ == "__main__":
    sys.exit(main() or 0)
