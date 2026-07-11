"""台股數據收集（台股收盤後 15:00 執行）

收集：
- 0050.TW 日線（yfinance）
- 0050.TW 5-min data（yfinance，用於 Realized Volatility）
- VIXTWN（TAIFEX）
- TAIFEX TX tick 衍生 5-min RV（本機官方逐筆成交檔，每日增量）

Cron: 0 15 * * 1-5
"""
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

PROJECT = Path(__file__).resolve().parent.parent
VENV_PYTHON = PROJECT / ".venv" / "bin" / "python"
CRITICAL_SECTIONS = {"taifex_5min_rv"}


def _detect_gap_days(ticker, output_dir):
    """Always fetch max window (59 days) — expanding window strategy.

    yfinance only keeps ~60 days of 5-min data. If we miss a day, it's gone forever.
    Always request full window; skip files we already have on save.
    """
    return 59


def _close_from_saved_5min(path: Path, ticker: str) -> pd.Series:
    """Read a saved yfinance file with either its two-row or flat header."""
    with path.open("r", encoding="utf-8", errors="replace") as source:
        first_line = source.readline().split(",", 1)[0].strip()
        second_line = source.readline().split(",", 1)[0].strip()
    has_multi_header = first_line == "Price" and second_line == "Ticker"
    if has_multi_header:
        frame = pd.read_csv(path, header=[0, 1], index_col=0)
        close_columns = [column for column in frame.columns if str(column[0]).lower() == "close"]
        if close_columns:
            return pd.to_numeric(frame[close_columns[0]], errors="coerce").dropna()
    frame = pd.read_csv(path, index_col=0)
    close_name = next((column for column in frame.columns if str(column).lower() == "close"), None)
    if close_name is None:
        raise ValueError(f"{path.name}: no Close column")
    return pd.to_numeric(frame[close_name], errors="coerce").dropna()


def _within_day_rv(close: pd.Series) -> float:
    """Five-minute RV with the first observation reset at each trading day."""
    values = close.to_numpy(dtype=float)
    if len(values) < 2:
        return float("nan")
    return float(np.square(np.diff(np.log(values))).sum())


def rebuild_saved_daily_rv(ticker: str, output_dir: Path) -> pd.DataFrame:
    """Rebuild daily RV from per-day files without an overnight cross-day return.

    The previous implementation called ``pct_change`` on a multi-day download
    before grouping.  That placed the overnight close-to-open move into each
    day's first five-minute return and made the 0050 validation target
    incomparable with session-only TAIFEX RV.
    """
    prefix = ticker.replace(".", "_")
    pattern = re.compile(rf"^{re.escape(prefix)}_5min_(\d{{4}}-\d{{2}}-\d{{2}})\.csv$")
    rows = []
    for path in sorted(output_dir.glob(f"{prefix}_5min_*.csv")):
        match = pattern.fullmatch(path.name)
        if not match:
            continue
        close = _close_from_saved_5min(path, ticker)
        rows.append({"date": match.group(1), "rv_5min": _within_day_rv(close)})
    result = pd.DataFrame(rows, columns=["date", "rv_5min"])
    if result.empty:
        return result
    result = result.drop_duplicates("date", keep="last").sort_values("date")
    result = result.set_index("date")

    rv_file = output_dir / f"{prefix}_daily_rv.csv"
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", suffix=".tmp", dir=output_dir, delete=False
    )
    tmp_path = Path(handle.name)
    try:
        with handle:
            result.to_csv(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, rv_file)
    finally:
        tmp_path.unlink(missing_ok=True)
    return result


def _collection_exit_code(section_ok: dict[str, bool]) -> int:
    """Fail immediately for canonical sections; retain legacy all-fail guard."""
    if any(not section_ok.get(section, False) for section in CRITICAL_SECTIONS):
        return 1
    if section_ok and not any(section_ok.values()):
        return 1
    return 0


def collect_5min(ticker, output_dir):
    """Collect recent 5-min data and save to CSV + compute RV.

    Auto-detects gap from existing files and backfills up to 59 days.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    days_back = _detect_gap_days(ticker, output_dir)
    print(f"  Auto-detected: fetching {days_back} days back for {ticker}")

    end = datetime.now()
    start = end - timedelta(days=days_back)

    data = yf.download(ticker, start=start.strftime('%Y-%m-%d'),
                       end=end.strftime('%Y-%m-%d'),
                       interval='5m', progress=False)

    if len(data) == 0:
        print(f"  No 5-min data for {ticker}")
        return

    # Save each trading day as separate file
    for date, group in data.groupby(data.index.date):
        filename = output_dir / f"{ticker.replace('.', '_')}_5min_{date}.csv"
        if not filename.exists():
            group.to_csv(filename)
            print(f"  Saved {filename.name} ({len(group)} bars)")

    # Recompute from every saved day so old rows created by the former
    # cross-day pct_change bug are corrected, not merely appended around.
    total_rv = rebuild_saved_daily_rv(ticker, output_dir)
    print(f"  {ticker} 5-min RV: {len(total_rv)} days total")


def main():
    now = datetime.now()
    print(f"=== 台股數據收集: {now.strftime('%Y-%m-%d %H:%M')} ===")

    # Track per-section ok/fail so cron exit surfaces total failure and any
    # canonical high-frequency section failure to host_cron_fail immediately.
    section_ok: dict[str, bool] = {}

    # 1. VIXTWN（TAIFEX 來源）
    print("\n--- VIXTWN ---")
    try:
        result = subprocess.run(
            [str(VENV_PYTHON), str(PROJECT / "scripts" / "collect_vixtwn.py")],
            cwd=str(PROJECT),
            timeout=60,
        )
        section_ok["vixtwn"] = result.returncode == 0
    except Exception as e:
        print(f"  VIXTWN error: {e}")
        section_ok["vixtwn"] = False

    # 2. 0050.TW 日線快取更新（force_refresh 確保拿最新）
    print("\n--- 0050.TW 日線 ---")
    try:
        sys.path.insert(0, str(PROJECT / "src"))
        from volpred.data.manager import DataManager
        dm = DataManager()
        tw50 = dm.get_model_data("0050.TW", "2020-01-01", "2026-12-31", force_refresh=True)
        print(f"  0050.TW: {tw50.index[-1].date()} close={float(tw50.iloc[-1]['close']):.2f} ({len(tw50)} rows)")
        section_ok["tw50_daily"] = True
    except Exception as e:
        print(f"  0050.TW 日線 error: {e}")
        section_ok["tw50_daily"] = False

    # 3. 0050.TW 5-min data
    print("\n--- 0050.TW 5-min ---")
    try:
        collect_5min("0050.TW", PROJECT / "data" / "intraday")
        section_ok["tw50_5min"] = True
    except Exception as e:
        print(f"  0050.TW 5-min error: {e}")
        section_ok["tw50_5min"] = False

    # 4. TWSE 每5秒委託成交 order-flow (MI_5MINS) — 當日只有今天才抓得到，每天存檔累積
    print("\n--- TWSE order-flow (MI_5MINS) ---")
    try:
        result = subprocess.run(
            [str(VENV_PYTHON), str(PROJECT / "scripts" / "collect_twse_orderflow.py"), "--date", "today"],
            cwd=str(PROJECT),
            timeout=120,
        )
        section_ok["twse_orderflow"] = result.returncode == 0
    except Exception as e:
        print(f"  TWSE order-flow error: {e}")
        section_ok["twse_orderflow"] = False

    # 5. TAIFEX official tick -> canonical 5-minute RV.  The local source
    # normally lands after midnight, so this 15:00 run processes the latest
    # file available at invocation time (typically the previous trading day).
    print("\n--- TAIFEX TX 5-min RV ---")
    try:
        result = subprocess.run(
            [str(VENV_PYTHON), str(PROJECT / "scripts" / "collect_taifex_tick.py")],
            cwd=str(PROJECT),
            timeout=900,
        )
        section_ok["taifex_5min_rv"] = result.returncode == 0
    except Exception as e:
        print(f"  TAIFEX 5-min RV error: {e}")
        section_ok["taifex_5min_rv"] = False

    print("\n✓ 台股數據收集完成")
    exit_code = _collection_exit_code(section_ok)
    if exit_code:
        failed_critical = sorted(
            section for section in CRITICAL_SECTIONS if not section_ok.get(section, False)
        )
        reason = (
            f"critical sections failed: {failed_critical}"
            if failed_critical
            else "all sections failed"
        )
        print(f"\n  [collect_tw_data] FAIL: {reason}: {section_ok}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
