#!/usr/bin/env python3
"""修復 price_cache 內 0050.TW 2014-01-02 的未回溯調整分割斷點。

診斷
----
0050.TW（元大台灣50）在 2025 年執行 1 股拆 4 股。yfinance 的回溯調整只套用到
2014-01-02 起的區段，2013-12-31 及之前仍是分割前計價，於是在 2014-01-02 留下
一個 ×0.25 的假斷點：

    2013-12-31 close 58.70   (分割前計價)
    2014-01-02 close 14.6375 (分割後計價)

adj_close 同步跳（37.41 → 9.33），代表調整層完全沒有修正它 —— 這不是配息、
也不是真實行情，是資料源的區段不一致。0050 在 2014-01-02 當天並沒有分割。

修復
----
把 2014-01-02 之前的價格欄位除以 4（分割因子，精確值非 58.70/14.6375=4.0102；
後者混入了當日真實報酬），volume 乘 4，使全序列統一為分割後計價。

交叉驗證：修復後 2013-12-31 close = 58.70/4 = 14.675，恰等於 2014-01-02 的
open（14.675），日報酬 -0.256% —— 與斷點前後的正常波動一致。

用法
----
    uv run python scripts/fix_0050_split_break.py --dry-run   # 只看不改（預設）
    uv run python scripts/fix_0050_split_break.py --apply     # 實際寫入（先備份）
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB_PATH = REPO / "data" / "cache" / "price_cache.db"

TICKER = "0050.TW"
SPLIT_DATE = "2014-01-02"   # 斷點日：此日「之前」的資料需要調整
SPLIT_FACTOR = 4.0          # 1 股拆 4 股
PRICE_COLS = ["open", "high", "low", "close", "adj_close"]


def show_boundary(conn: sqlite3.Connection, label: str) -> None:
    rows = conn.execute(
        "select date, open, close, adj_close, volume from price_data "
        "where ticker = ? and date between '2013-12-30' and '2014-01-03' order by date",
        (TICKER,),
    ).fetchall()
    print(f"\n--- {label} ---")
    prev_close = None
    for date, o, c, adj, vol in rows:
        ret = f"{(c / prev_close - 1) * 100:+.3f}%" if prev_close else "   —   "
        print(f"  {date}  open={o:9.4f}  close={c:9.4f}  adj={adj:8.4f}  "
              f"vol={vol:>12,.0f}  ret={ret}")
        prev_close = c


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--apply", action="store_true", help="實際寫入（預設 dry-run）")
    ap.add_argument("--dry-run", action="store_true", help="只顯示不寫入")
    args = ap.parse_args()

    db = Path(args.db)
    conn = sqlite3.connect(db)

    n_affected = conn.execute(
        "select count(*) from price_data where ticker = ? and date < ?",
        (TICKER, SPLIT_DATE),
    ).fetchone()[0]
    print(f"ticker={TICKER}  斷點日={SPLIT_DATE}  分割因子={SPLIT_FACTOR}")
    print(f"待調整列數（date < {SPLIT_DATE}）：{n_affected}")

    if n_affected == 0:
        print("沒有需要調整的列 —— 可能已修復過。")
        return 0

    show_boundary(conn, "修復前")

    if not args.apply:
        print("\n[dry-run] 未寫入。加 --apply 才實際修改。")
        return 0

    backup = db.with_suffix(db.suffix + ".bak_0050split")
    shutil.copy2(db, backup)
    print(f"\n已備份 → {backup}")

    price_set = ", ".join(f"{col} = {col} / {SPLIT_FACTOR}" for col in PRICE_COLS)
    conn.execute(
        f"update price_data set {price_set}, volume = volume * {SPLIT_FACTOR} "
        "where ticker = ? and date < ?",
        (TICKER, SPLIT_DATE),
    )
    conn.commit()
    print(f"已更新 {n_affected} 列。")

    show_boundary(conn, "修復後")
    return 0


if __name__ == "__main__":
    sys.exit(main())
