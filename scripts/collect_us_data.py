"""美股數據收集（美股收盤後 05:30 台北時間執行）

收集：
- SPY/GLD/TLT 日線（yfinance，DataManager 快取）
- ^VIX 日線
- SPY 5-min data（用於 HAR-RV / Realized GARCH）

Cron: 30 5 * * 2-6（週二至六 = 美股週一至五收盤後）
"""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
VENV_PYTHON = PROJECT / ".venv" / "bin" / "python"


def main():
    now = datetime.now()
    print(f"=== 美股數據收集: {now.strftime('%Y-%m-%d %H:%M')} ===")

    sys.path.insert(0, str(PROJECT / "src"))

    # 1. 日線數據（force_refresh=True 強制從 yfinance 拉最新）
    print("\n--- 日線數據 ---")
    try:
        from volpred.data.manager import DataManager
        dm = DataManager()
        for ticker in ["SPY", "GLD", "TLT", "^VIX"]:
            try:
                data = dm.get_model_data(ticker, "2020-01-01", "2026-12-31", force_refresh=True)
                print(f"  {ticker:6s}: {data.index[-1].date()} close={float(data.iloc[-1]['close']):.2f} ({len(data)} rows)")
            except Exception as e:
                print(f"  {ticker:6s}: error ({e})")
    except Exception as e:
        print(f"  DataManager error: {e}")

    # 2. SPY 5-min data（Realized Volatility 用）
    print("\n--- SPY 5-min ---")
    try:
        subprocess.run(
            [str(VENV_PYTHON), str(PROJECT / "scripts" / "collect_5min_data.py")],
            cwd=str(PROJECT),
            timeout=120,
        )
    except Exception as e:
        print(f"  5-min error: {e}")

    print("\n✓ 美股數據收集完成")


if __name__ == "__main__":
    main()
