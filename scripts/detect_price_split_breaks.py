#!/usr/bin/env python3
"""偵測 price_cache 內未回溯調整的分割斷點（split break）與填充假 bar。

起因：0050.TW 在 2014-01-02 有 4.01x 未調整斷點（2013-12-31 close 58.70 →
2014-01-02 close 14.6375），adj_close 同步跳動代表這不是真實報酬，而是
yfinance 對 2025 年 1:4 分割的回溯調整只套用到 2014-01-02 起的區段。任何
跨該日的長樣本 rolling / realized-vol / 報酬序列都被污染（實測 RV
persistence 相關係數被壓到 0.017）。

判準
----
split_break：|log(close_t / close_{t-1})| 超過門檻，且
  (a) adj_close 的比值與 close 比值幾乎相同 —— 代表調整層沒有修正它
      （真實暴跌時 adj_close 會跟著跌，但配息/分割調整過的資料
       adj_close 比值會與 close 比值分離），且
  (b) 比值接近常見分割比（2, 3, 4, 5, 10 及其倒數）容差 3%。
兩條都中才報 split_break —— 只中 (a) 的列為 large_move 供人工看，
避免把 COVID 熔斷那種真跌誤判成資料錯誤。

stale_fill：連續 N 天 close 完全相同且 volume == 0 的填充假 bar
（會製造假零報酬，壓低 realized vol）。

CSV 模式（--csv-scan）
---------------------
DB 修好之後仍有一批污染是碰不到的：**已凍結的 pinned snapshot CSV**。0050
事件的實際受害者幾乎全在那裡（16 個檔，含 taiwan-vt 與 garch-x-vix 兩篇論文
的主資料檔）。CSV 沒有 adj_close 可做 coherence 檢查，改用另一條判準：

    真分割是價格水準的永久位移；真實行情會回復。

比較斷點前後各 20 筆的中位數，要求水準位移比值也落在同一分割比 ±10% 內。
這條判準能把 2018-02-06 Volmageddon（VIX 單日 ×2 但水準會回落）與 0050 的
真斷點分開。另外排除波動率指數欄、非價格水準欄（計數 / 衍生統計 / 報酬）、
低於 1.0 的價格（tick size 離散跳動），並要求日期嚴格遞增（long-format
panel 的換標的邊界不是時序相鄰）。

**這是 triage 工具，不是自動修復器**：回報的是候選。0050 型態（×0.2494 於
2014-01-02）已人工確認；K1677 的 MARA / PLUG 是真實股票分割；kalshi 事件
機率市場與新聞計數 panel 則是已知的殘餘誤報，需人工判讀。

用法
----
    uv run python scripts/detect_price_split_breaks.py            # 掃 DB
    uv run python scripts/detect_price_split_breaks.py --csv-scan # 掃 snapshot CSV
    uv run python scripts/detect_price_split_breaks.py --json
    uv run python scripts/detect_price_split_breaks.py --ticker 0050.TW

exit code 1 = 有 split_break（可當 CI gate）。
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path

def _find_repo_root() -> Path:
    """Walk up to the directory holding .git, rather than assuming a depth.

    2026-07-21: this used to be `Path(__file__).resolve().parent.parent`, which
    is only correct while the file sits directly in scripts/. A dead-code sweep
    moved it to scripts/_legacy/ (commit a15fba0d7) and the constant silently
    started pointing at scripts/ — every glob then matched nothing and
    `--csv-scan` reported "0 files, 0 breaks", i.e. a clean bill of health for
    a repo that in fact had 19 contaminated snapshots. Depth-based roots break
    silently on any move; a marker search does not.
    """
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / ".git").exists():
            return candidate
    # No marker found (e.g. an exported copy) — fall back to the old assumption
    # rather than crashing, but the scan guard below still catches a bad root.
    return here.parent.parent


REPO_ROOT = _find_repo_root()
DB_PATH = REPO_ROOT / "data" / "cache" / "price_cache.db"

# 常見分割比例（含反向分割的倒數）
SPLIT_RATIOS = [2, 3, 4, 5, 6, 8, 10, 20]
RATIO_TOL = 0.03          # 比值落在分割比 ±3% 內視為分割
MOVE_THRESHOLD = 0.35     # |log return| 門檻，約 ±35%
ADJ_COHERENCE_TOL = 0.02  # close 比值與 adj_close 比值差距 <2% 視為「調整層沒修正」
STALE_MIN_RUN = 3         # 連續幾天相同 close + 零成交量才算 stale fill


def _is_split_ratio(ratio: float) -> float | None:
    """回傳最接近的分割比（如 4.0 或 0.25），不像分割則 None。"""
    for r in SPLIT_RATIOS:
        for cand in (float(r), 1.0 / r):
            if abs(ratio / cand - 1.0) <= RATIO_TOL:
                return cand
    return None


def scan_ticker(conn: sqlite3.Connection, ticker: str) -> dict:
    rows = conn.execute(
        "select date, close, adj_close, volume from price_data "
        "where ticker = ? order by date",
        (ticker,),
    ).fetchall()

    splits, large_moves, stale_runs = [], [], []

    for prev, cur in zip(rows, rows[1:]):
        prev_date, prev_close, prev_adj, _ = prev
        cur_date, cur_close, cur_adj, _ = cur
        if not prev_close or not cur_close or prev_close <= 0 or cur_close <= 0:
            continue

        ratio = cur_close / prev_close
        if abs(math.log(ratio)) < MOVE_THRESHOLD:
            continue

        # adj_close 是否跟著跳（跳 = 調整層沒修正這個斷點）
        adj_ratio = None
        if prev_adj and cur_adj and prev_adj > 0:
            adj_ratio = cur_adj / prev_adj
        adj_incoherent = (
            adj_ratio is not None and abs(adj_ratio / ratio - 1.0) <= ADJ_COHERENCE_TOL
        )

        split_ratio = _is_split_ratio(ratio)
        record = {
            "date": cur_date,
            "prev_date": prev_date,
            "prev_close": round(prev_close, 4),
            "close": round(cur_close, 4),
            "ratio": round(ratio, 4),
            "adj_ratio": round(adj_ratio, 4) if adj_ratio else None,
            "log_return": round(math.log(ratio), 4),
        }
        if split_ratio and adj_incoherent:
            record["matched_split"] = split_ratio
            splits.append(record)
        else:
            record["why_not_split"] = (
                "adj_close 有分離（可能是真實行情）"
                if not adj_incoherent
                else "比值不像常見分割比"
            )
            large_moves.append(record)

    # stale fill：連續相同 close 且 volume == 0
    run_start, run_len = None, 0
    for date, close, _adj, volume in rows:
        if volume == 0 and run_start is not None and close == run_start[1]:
            run_len += 1
            continue
        if run_len >= STALE_MIN_RUN:
            stale_runs.append(
                {"start": run_start[0], "days": run_len, "close": round(run_start[1], 4)}
            )
        run_start, run_len = (date, close), 0
    if run_len >= STALE_MIN_RUN:
        stale_runs.append(
            {"start": run_start[0], "days": run_len, "close": round(run_start[1], 4)}
        )

    return {
        "ticker": ticker,
        "n_rows": len(rows),
        "date_range": [rows[0][0], rows[-1][0]] if rows else None,
        "split_breaks": splits,
        "large_moves": large_moves,
        "stale_fills": stale_runs,
    }


PRICE_COL_HINTS = ("close", "price", "adj", "open", "high", "low")
# 波動率指數不會分割，且天生有 ±100% 單日跳動（2018-02-06 Volmageddon、
# 2020-03 COVID）—— 一律排除，否則整份掃描被它們的真實行情淹沒。
VOL_INDEX_HINTS = ("vix", "vvix", "ovx", "vxn", "move", "skew")
# 欄名雖含 close/price，但語意不是「價格水準」—— 計數、衍生統計、報酬。
# 這些天生就會 ×2 / ÷2（close_vote_count 從 1 變 2），不是分割。
NON_LEVEL_HINTS = ("count", "_n", "num", "std", "range", "_rv", "rv_",
                   "vol", "return", "_ret", "ret_", "chg", "change", "pct",
                   "min", "max", "mean", "median", "sum", "hours", "flag")
CSV_TREES = ("experiments", "paper")
PERSIST_WINDOW = 20   # 斷點前後各取幾筆算中位數
PERSIST_TOL = 0.10    # 水準位移比值需落在分割比 ±10% 內
# 低於此價格的欄位跳過：tick size 造成的離散跳動（0.005 → 0.01 就是 ×2）
# 會被誤判成分割。
MIN_PRICE_LEVEL = 1.0


def scan_csv(path: Path) -> dict:
    """掃單一 pinned snapshot CSV。

    DB 有偵測器守著，但**已凍結的 snapshot CSV 沒有** —— 而 0050 事件的污染
    幾乎全部落在那裡（DB 修好碰不到它們）。判準與 scan_ticker 相同，只是逐欄
    套用在欄名像價格的欄位上（close / price / adj / open / high / low）。
    """
    import csv as _csv

    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        rows = list(_csv.DictReader(fh))
    if len(rows) < 2:
        return {"path": str(path), "n_rows": len(rows), "breaks": []}

    fields = rows[0].keys()
    date_col = next((f for f in fields if f and "date" in f.lower()), None)
    if date_col is None:
        # 沒有日期欄就無法確認相鄰兩列真的是時序相鄰 —— 不猜，直接跳過。
        return {"path": str(path), "n_rows": len(rows), "breaks": [],
                "skipped": "no-date-column"}
    price_cols = [
        f for f in fields
        if f and any(h in f.lower() for h in PRICE_COL_HINTS)
        and "volume" not in f.lower()
        and not any(v in f.lower() for v in VOL_INDEX_HINTS)
        and not any(n in f.lower() for n in NON_LEVEL_HINTS)
    ]

    # 純波動率指數檔（檔名是 vix/ovx…，且欄名只有通用的 Open/High/Low/Close，
    # 沒有其他標的前綴）整檔跳過 —— 那些欄位其實全是指數本身。
    # 注意不能只看檔名：`0050_tw_vix_2007-2022.csv` 檔名含 vix 卻是 0050 的
    # 主資料檔，早期版本因此漏報了兩篇論文的資料來源。
    generic_only = all(
        c.lower().replace(" ", "").replace("_", "")
        in {"open", "high", "low", "close", "adjclose", "price"}
        for c in price_cols
    ) if price_cols else False
    if generic_only and any(v in path.name.lower() for v in VOL_INDEX_HINTS):
        return {"path": str(path), "n_rows": len(rows), "breaks": [],
                "skipped": "vol-index-only"}

    breaks = []
    for col in price_cols:
        # 先取出整欄的數值序列，持續性檢查需要斷點前後的水準
        series = []
        for row in rows:
            raw = (row.get(col) or "").strip()
            try:
                val = float(raw)
            except ValueError:
                continue  # silent-ok: 空格 / NA / 停牌標記是正常資料形狀，逐列示警會淹沒輸出
            series.append((row.get(date_col, "?") if date_col else "?", val))

        # 逐格跳過可以安靜，整欄跳過不行：欄名被當成價格欄、但沒有一格解析得出數字時，
        # 下面的迴圈直接不跑，這一欄會被當成「乾淨無斷點」報出去 —— 靜默的假陰性。
        if rows and not series:
            print(f"⚠️  {path.name}: 欄位 {col!r} 共 {len(rows)} 列但無任何可解析數值，"
                  f"該欄未做斷點檢查", file=sys.stderr)

        for i in range(1, len(series)):
            (prev_date, prev_val), (cur_date, val) = series[i - 1], series[i]
            if prev_val <= 0 or val <= 0:
                continue
            if prev_val < MIN_PRICE_LEVEL or val < MIN_PRICE_LEVEL:
                continue
            # long-format panel（多資產堆疊同一檔）相鄰兩列可能是同一天的不同
            # 標的，或在換 ticker 處日期倒退。那種「斷點」只是換了一檔股票。
            # 嚴格要求日期遞增，才算得上時間序列上的相鄰兩點。
            if not (prev_date and cur_date and cur_date > prev_date):
                continue
            ratio = val / prev_val
            if abs(math.log(ratio)) < MOVE_THRESHOLD:
                continue
            matched = _is_split_ratio(ratio)
            if not matched:
                continue

            # 持續性檢查：真分割是永久的水準位移，真實行情會回復。
            # 比較斷點前後各 PERSIST_WINDOW 筆的中位數比值。
            before = sorted(v for _, v in series[max(0, i - PERSIST_WINDOW):i])
            after = sorted(v for _, v in series[i:i + PERSIST_WINDOW])
            if len(before) < 3 or len(after) < 3:
                continue
            med_before = before[len(before) // 2]
            med_after = after[len(after) // 2]
            if med_before <= 0:
                continue
            level_shift = med_after / med_before
            if abs(level_shift / matched - 1.0) > PERSIST_TOL:
                continue  # 水準沒有永久位移 → 是行情，不是分割

            breaks.append({
                "column": col,
                "prev_date": prev_date,
                "date": cur_date,
                "prev_value": round(prev_val, 4),
                "value": round(val, 4),
                "ratio": round(ratio, 4),
                "matched_split": matched,
                "level_shift": round(level_shift, 4),
            })

    return {"path": str(path), "n_rows": len(rows), "breaks": breaks}


def collect_snapshot_csvs(repo: Path) -> list[Path]:
    """Collect snapshot CSVs without assuming experiment-directory depth."""
    return sorted({
        path
        for tree in CSV_TREES
        for path in (repo / tree).glob("**/data/*.csv")
    })


def run_csv_scan(repo: Path, as_json: bool) -> int:
    paths = collect_snapshot_csvs(repo)

    # Scanning nothing is a broken scan, not a clean repo. Without this, a bad
    # --repo (or a moved script, see _find_repo_root) prints "0 / 0" and exits
    # 0 — indistinguishable from "audited everything, found nothing". That is
    # exactly how this detector spent time reporting all-clear on a repo with
    # 19 contaminated snapshots. Fail loudly instead.
    if not paths:
        patterns = [f"{tree}/**/data/*.csv" for tree in CSV_TREES]
        msg = (f"no CSV matched {patterns} under {repo} — "
               f"the scan found nothing to audit, which is a configuration "
               f"error, not a clean result. Check --repo.")
        if as_json:
            print(json.dumps({"error": msg, "scanned": 0, "dirty": []},
                             ensure_ascii=False, indent=2))
        else:
            print(f"❌ {msg}", file=sys.stderr)
        return 2

    results = [scan_csv(p) for p in paths]
    dirty = [r for r in results if r["breaks"]]

    if as_json:
        print(json.dumps({"scanned": len(results), "dirty": dirty},
                         ensure_ascii=False, indent=2))
        return 1 if dirty else 0

    print(f"掃描 pinned snapshot CSV：{len(results)} 個檔")
    for r in dirty:
        rel = Path(r["path"]).relative_to(repo)
        print(f"\n🚫 {rel}  (n={r['n_rows']})")
        seen = set()
        for b in r["breaks"]:
            key = (b["prev_date"], b["date"], b["matched_split"])
            if key in seen:
                continue
            seen.add(key)
            cols = [x["column"] for x in r["breaks"]
                    if (x["prev_date"], x["date"], x["matched_split"]) == key]
            print(f"     {b['prev_date']} → {b['date']}: {b['prev_value']} → "
                  f"{b['value']} (×{b['ratio']}, 最接近 {b['matched_split']})")
            print(f"     受影響欄位: {', '.join(cols)}")
    print(f"\n有斷點的檔案：{len(dirty)} / {len(results)}")
    return 1 if dirty else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--ticker", help="只掃單一 ticker")
    ap.add_argument("--csv-scan", action="store_true",
                    help="改掃 pinned snapshot CSV（experiments/ 與 paper/ 底下）")
    ap.add_argument("--repo", default=str(REPO_ROOT))
    ap.add_argument("--json", action="store_true", help="輸出完整 JSON")
    args = ap.parse_args()

    if args.csv_scan:
        return run_csv_scan(Path(args.repo), args.json)

    conn = sqlite3.connect(args.db)
    if args.ticker:
        tickers = [args.ticker]
    else:
        tickers = [r[0] for r in conn.execute(
            "select distinct ticker from price_data order by ticker")]

    results = [scan_ticker(conn, t) for t in tickers]
    n_breaks = sum(len(r["split_breaks"]) for r in results)

    if args.json:
        print(json.dumps({"results": results, "n_split_breaks": n_breaks},
                         ensure_ascii=False, indent=2))
        return 1 if n_breaks else 0

    for r in results:
        flags = []
        if r["split_breaks"]:
            flags.append(f"{len(r['split_breaks'])} split-break")
        if r["stale_fills"]:
            flags.append(f"{len(r['stale_fills'])} stale-fill")
        if r["large_moves"]:
            flags.append(f"{len(r['large_moves'])} large-move")
        status = "🚫 " if r["split_breaks"] else ("⚠️  " if flags else "✅ ")
        print(f"{status}{r['ticker']:<10} n={r['n_rows']:<5} "
              f"{', '.join(flags) if flags else 'clean'}")
        for b in r["split_breaks"]:
            print(f"     🚫 SPLIT BREAK {b['prev_date']} → {b['date']}: "
                  f"{b['prev_close']} → {b['close']} (×{b['ratio']}, "
                  f"最接近 {b['matched_split']}), adj 同步跳 ×{b['adj_ratio']}")
        for s in r["stale_fills"]:
            print(f"     ⚠️  STALE FILL {s['start']} 起連續 {s['days']} 天 "
                  f"close={s['close']} 且 volume=0")
        for m in r["large_moves"]:
            print(f"     · large move {m['prev_date']} → {m['date']}: "
                  f"×{m['ratio']} — {m['why_not_split']}")

    print(f"\n合計 split_break: {n_breaks}")
    return 1 if n_breaks else 0


if __name__ == "__main__":
    sys.exit(main())
