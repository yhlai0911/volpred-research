#!/usr/bin/env python3
"""K1675 — 台股颱風臨時停市事件研究（T+0: 2026-07-10 颱風巴威停市）.

研究問題
--------
颱風臨時停市（非預定休市）之後的首個交易日，台股是否出現系統性的
跳空放大 / 報酬放大 / 波動放大？（「停市會不會累積波動」的直覺 vs 數據）

停市日推導方法（雙來源 + 交叉驗證，2026-07-10 probe 修正版）
------------------------------------------------------------
原設計假設 exchange_calendars XTAI 對颱風停市「完全盲目」（sessions 對比
行情資料，缺資料 = 停市）。實際 probe 發現 exchange_calendars 4.13.2 已把
歷史颱風停市 backfill 進 adhoc_holidays（source 內有結構化 `typhoons` 清單），
因此推導改為雙來源 union：

  來源 A: exchange_calendars XTAI source 的 `typhoons` 清單 ∩ 2012-2025
          （每一天再驗證 ^TWII 與 0050.TW 皆無行情）
  來源 B: 殘差掃描 — calendar sessions 中 ^TWII 與 0050.TW 皆無行情的日子，
          再用第二獨立來源（TWSE 融資融券 storage/sentiment/tw_margin_0050.csv）
          交叉驗證：該日有融資券變動 = 市場實際有開 = yfinance 資料缺漏，剔除；
          該日無融資券資料且不緊鄰預定假期 = 真停市，納入。

  Probe 實測（寫死進 audit trail，見 results.json derivation_audit）:
    - 殘差掃描 5 天：2019-09-09 / 2021-04-06 有 TWSE 融資券資料 → yfinance 缺漏，剔除
      2022-02-04 / 2023-01-18 緊鄰春節連假（calendar 邊界 bug）→ 剔除
      2024-10-31（康芮）無融資券資料、非假期邊界 → 真停市，納入（library 漏列）
    - 今日 2026-07-10（巴威）由 config/market_closures_adhoc.json 偵測機制記錄，
      不在 2012-2025 統計樣本內。

統計設計
--------
事件 = 連續停市日合併（如 2024-07-24/25 凱米算 1 個事件）。
  (a) 復市首日 |開盤跳空| = |Open_R / Close_P - 1|（P = 停市前最後交易日）
  (b) 復市首日 |close-to-close 報酬| = |Close_R / Close_P - 1|
  (c) RV ratio = RV(復市起 5 個交易日) / RV(停市前 5 個交易日)，RV = sqrt(mean(r^2))
對照組 = 同月份（7-10 月）2012-2025 所有普通交易日（距任何停市日 >5 個交易日）。
次對照 = 對照組中的週一（跨 2+ 個日曆日的 gap，與停市跨日結構較可比）。
Bootstrap 95% CI，seed=42，10000 次重抽。樣本小（13 事件），如實標注，不過度宣稱。

Lookahead：本實驗為描述性事件研究，無交易訊號；所有統計皆以事件日切齊，
不使用未來資訊分組。隨機程序僅 bootstrap，固定 np.random.default_rng(42)。

資料來源：yfinance ^TWII（storage/macro/yf_TWII.csv，1997-2026）、
yfinance 0050.TW（storage/macro/yf_0050.TW.csv）、exchange_calendars XTAI 4.13.2、
TWSE 融資融券（storage/sentiment/tw_margin_0050.csv，交叉驗證用）。
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import exchange_calendars as xcals

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SEED = 42
N_BOOT = 10_000
SAMPLE_START, SAMPLE_END = "2012-01-01", "2025-12-31"

plt.rcParams["font.family"] = ["Heiti TC", "Arial Unicode MS", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

# 颱風名稱標注（公開紀錄：DGPA 停班停課公告 / TWSE 休市公告，人工核對）
TYPHOON_NAMES = {
    "2012-08-02": "蘇拉 Saola",
    "2013-08-21": "潭美 Trami",
    "2014-07-23": "麥德姆 Matmo",
    "2015-07-10": "昌鴻 Chan-hom",
    "2015-09-29": "杜鵑 Dujuan",
    "2016-07-08": "尼伯特 Nepartak",
    "2016-09-27": "梅姬 Megi",
    "2016-09-28": "梅姬 Megi",
    "2019-08-09": "利奇馬 Lekima",
    "2019-09-30": "米塔 Mitag",
    "2023-08-03": "卡努 Khanun",
    "2024-07-24": "凱米 Gaemi",
    "2024-07-25": "凱米 Gaemi",
    "2024-10-02": "山陀兒 Krathon",
    "2024-10-03": "山陀兒 Krathon",
    "2024-10-31": "康芮 Kong-rey",
}


def load_prices(path: Path) -> pd.DataFrame:
    """讀 yfinance CSV 並剔除 phantom 填充列。

    yfinance 在休市日有時塞「假列」：(a) 整列 OHLCV 完全複製前一日
    （^TWII 2014-07-23 / 2016-07-08 實測）；(b) OHLC 全平 + 量 0 + 收盤
    等於前日（0050.TW 在多個颱風日與 2025-06 分割暫停期實測）。
    真實交易日不可能整列與前日 byte-相同，剔除安全。
    """
    df = pd.read_csv(path, skiprows=[1, 2], index_col=0, parse_dates=True)
    df = df[df["Close"].notna()].sort_index()
    prev = df.shift(1)
    full_dup = (
        (df["Close"] == prev["Close"]) & (df["Open"] == prev["Open"])
        & (df["High"] == prev["High"]) & (df["Low"] == prev["Low"])
    )
    flat_filler = (
        (df["Close"] == prev["Close"]) & (df["Volume"] == 0) & (df["High"] == df["Low"])
    )
    phantom = full_dup | flat_filler
    dropped = df.index[phantom].strftime("%Y-%m-%d").tolist()
    if dropped:
        print(f"  [clean] {path.name}: 剔除 {len(dropped)} 個 phantom 填充列: {dropped}")
    return df[~phantom]


def derive_closures() -> tuple[list[str], dict]:
    """雙來源推導 2012-2025 颱風停市日，回傳 (dates, audit_trail)。"""
    twii = load_prices(ROOT / "storage/macro/yf_TWII.csv")
    t50 = load_prices(ROOT / "storage/macro/yf_0050.TW.csv")

    cal = xcals.get_calendar("XTAI")

    # 來源 A: library 結構化 typhoons 清單
    from exchange_calendars.exchange_calendar_xtai import typhoons

    src_a = sorted(
        d.strftime("%Y-%m-%d")
        for d in pd.DatetimeIndex(typhoons)
        if pd.Timestamp(SAMPLE_START) <= d <= pd.Timestamp(SAMPLE_END)
    )
    # 驗證：來源 A 每一天在兩個行情序列皆無資料
    bad_a = [d for d in src_a if pd.Timestamp(d) in twii.index or pd.Timestamp(d) in t50.index]
    if bad_a:
        raise RuntimeError(f"來源 A 有停市日卻有行情資料，需人工檢查: {bad_a}")

    # 來源 B: 殘差掃描 — 以 ^TWII（市場指數）缺資料的 session 為候選。
    # Codex review (2026-07-10) 補強：原版要求「兩序列皆缺」才成為候選，若某源在
    # 真停市日殘留未被清理攔截的 phantom 列會漏抓；改為指數缺資料即候選，
    # 再用 0050 真實行情 + TWSE 融資券 + 假期鄰接三重 reject，寬進嚴出。
    sess = pd.DatetimeIndex(
        [pd.Timestamp(s).tz_localize(None) if pd.Timestamp(s).tzinfo else pd.Timestamp(s)
         for s in cal.sessions_in_range(SAMPLE_START, SAMPLE_END)]
    )
    residual = list(sess.difference(twii.index))

    # 交叉驗證 1: TWSE 融資融券（獨立於 yfinance 的第二來源）
    margin = pd.read_csv(ROOT / "storage/sentiment/tw_margin_0050.csv", parse_dates=["date"])
    margin_days = set(margin["date"])

    # 交叉驗證 2: 是否緊鄰 calendar 已知假期（春節邊界 bug）
    all_holidays = set(
        pd.Timestamp(d).tz_localize(None) if pd.Timestamp(d).tzinfo else pd.Timestamp(d)
        for d in cal.adhoc_holidays
    )

    src_b, rejected = [], []
    for d in residual:
        if d in t50.index:
            rejected.append({"date": d.strftime("%Y-%m-%d"), "reason": "0050 有真實行情（市場有開，^TWII 資料缺漏）"})
            continue
        if d in margin_days:
            rejected.append({"date": d.strftime("%Y-%m-%d"), "reason": "TWSE 融資券有資料（市場有開，yfinance 缺漏）"})
            continue
        neighbors = [d - pd.Timedelta(days=1), d + pd.Timedelta(days=1)]
        if any(n in all_holidays for n in neighbors):
            rejected.append({"date": d.strftime("%Y-%m-%d"), "reason": "緊鄰預定連假（calendar 邊界誤標，非颱風）"})
            continue
        src_b.append(d.strftime("%Y-%m-%d"))

    closures = sorted(set(src_a) | set(src_b))

    # 正向總驗證：最終 16 個停市日全數不得有 TWSE 融資券資料（市場確實未開）
    margin_conflict = [d for d in closures if pd.Timestamp(d) in margin_days]
    if margin_conflict:
        raise RuntimeError(f"停市日在 TWSE 融資券出現交易資料，需人工檢查: {margin_conflict}")

    audit = {
        "source_a_library_typhoons": src_a,
        "source_b_residual_scan_accepted": src_b,
        "source_b_residual_scan_rejected": rejected,
        "final_margin_cross_check": f"{len(closures)}/{len(closures)} 停市日皆無 TWSE 融資券資料（市場確實未開）",
        "verification": "來源 A 全數確認 ^TWII 與 0050.TW 皆無行情；來源 B 指數缺資料即候選，以 0050 行情 + TWSE 融資券 + 假期鄰接三重 reject",
        "known_blind_spots": [
            "真停市日若緊鄰預定連假（如 2015-09-29 杜鵑型），來源 B 會誤剔，需靠來源 A 或 config/market_closures_adhoc.json 覆蓋",
            "來源 B 以 ^TWII 缺資料為 trigger；若 yfinance 在停市日塞入未被清理規則攔截的新型 phantom 列會漏抓（現行規則涵蓋全部已知 pattern）",
        ],
    }
    return closures, audit


def merge_events(closure_dates: list[str]) -> list[list[str]]:
    """連續停市日（中間無交易日）合併為單一事件。"""
    ds = [pd.Timestamp(d) for d in closure_dates]
    events, cur = [], [ds[0]]
    for prev, d in zip(ds, ds[1:]):
        if (d - prev).days <= 3:  # 連續（含跨週末不會發生：颱風連停都是相鄰平日）
            cur.append(d)
        else:
            events.append(cur)
            cur = [d]
    events.append(cur)
    return [[x.strftime("%Y-%m-%d") for x in ev] for ev in events]


def rv(returns: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(returns))))


def boot_ci(values: np.ndarray, rng: np.random.Generator, stat=np.mean) -> tuple[float, float]:
    n = len(values)
    stats = np.array([stat(values[rng.integers(0, n, n)]) for _ in range(N_BOOT)])
    return float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))


def main() -> None:
    rng = np.random.default_rng(SEED)
    twii = load_prices(ROOT / "storage/macro/yf_TWII.csv")
    px = twii.loc["2011-06-01":"2026-03-01"]  # 前後留 buffer 給 ±5 日視窗
    close, opn = px["Close"], px["Open"]
    ret = close.pct_change()
    gap = opn / close.shift(1) - 1.0

    # yfinance ^TWII 開盤價品質檢查：零跳空比例過高代表 open 被回填
    zero_gap_frac = float((gap.abs() < 1e-6).mean())

    closures, audit = derive_closures()
    events = merge_events(closures)
    closure_ts = set(pd.Timestamp(d) for d in closures)
    idx = close.index

    event_rows = []
    for ev in events:
        first, last = pd.Timestamp(ev[0]), pd.Timestamp(ev[-1])
        pre_days = idx[idx < first]
        post_days = idx[idx > last]
        if len(pre_days) < 6 or len(post_days) < 5:
            continue
        p_day, r_day = pre_days[-1], post_days[0]
        c_p = close.loc[p_day]
        g = abs(opn.loc[r_day] / c_p - 1.0)
        a = abs(close.loc[r_day] / c_p - 1.0)
        pre_win = ret.loc[pre_days[-5:]].dropna().to_numpy()
        post_win = ret.loc[post_days[:5]].dropna().to_numpy()
        # 復市首日報酬以 c_p 為基（跨停市），其後為正常日報酬
        post_win = post_win.copy()
        post_win[0] = close.loc[r_day] / c_p - 1.0
        rv_pre, rv_post = rv(pre_win), rv(post_win)
        event_rows.append({
            "closure_dates": ev,
            "typhoon": TYPHOON_NAMES.get(ev[0], "（未標名）"),
            "n_closure_days": len(ev),
            "last_pre_close_day": p_day.strftime("%Y-%m-%d"),
            "reopen_day": r_day.strftime("%Y-%m-%d"),
            "abs_open_gap_pct": round(g * 100, 4),
            "abs_close_ret_pct": round(a * 100, 4),
            "rv_pre_5d_pct": round(rv_pre * 100, 4),
            "rv_post_5d_pct": round(rv_post * 100, 4),
            "rv_ratio_post_over_pre": round(rv_post / rv_pre, 4),
        })

    ev_gap = np.array([r["abs_open_gap_pct"] for r in event_rows]) / 100
    ev_ret = np.array([r["abs_close_ret_pct"] for r in event_rows]) / 100
    ev_rvr = np.array([r["rv_ratio_post_over_pre"] for r in event_rows])

    # ── 對照組：同月份（停市事件出現的月份）普通交易日，排除停市 ±5 交易日 ──
    closure_months = sorted(set(pd.Timestamp(d).month for d in closures))
    sample_idx = idx[(idx >= pd.Timestamp(SAMPLE_START)) & (idx <= pd.Timestamp(SAMPLE_END))]
    excluded = set()
    for d in closure_ts:
        pos = idx.searchsorted(d)
        lo, hi = max(0, pos - 5), min(len(idx), pos + 6)
        excluded.update(idx[lo:hi])
    control_days = [
        d for d in sample_idx
        if d.month in closure_months and d not in excluded
        and not np.isnan(ret.loc[d]) and not np.isnan(gap.loc[d])
    ]
    ctrl_ret = np.abs(ret.loc[control_days].to_numpy())
    ctrl_gap = np.abs(gap.loc[control_days].to_numpy())
    monday_days = [d for d in control_days if d.weekday() == 0]
    ctrl_ret_mon = np.abs(ret.loc[monday_days].to_numpy())
    ctrl_gap_mon = np.abs(gap.loc[monday_days].to_numpy())

    # ── Bootstrap CI（seed=42）──
    def summarize(x: np.ndarray) -> dict:
        lo, hi = boot_ci(x, rng)
        lo_m, hi_m = boot_ci(x, rng, stat=np.median)
        return {
            "n": int(len(x)),
            "mean": float(np.mean(x)),
            "median": float(np.median(x)),
            "boot95_mean": [lo, hi],
            "boot95_median": [lo_m, hi_m],
        }

    def diff_ci(a: np.ndarray, b: np.ndarray) -> dict:
        """mean(a) - mean(b) 的 bootstrap 95% CI（兩組獨立重抽）。"""
        na, nb = len(a), len(b)
        d = np.array([
            np.mean(a[rng.integers(0, na, na)]) - np.mean(b[rng.integers(0, nb, nb)])
            for _ in range(N_BOOT)
        ])
        return {
            "point": float(np.mean(a) - np.mean(b)),
            "boot95": [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))],
            "significant_at_5pct": bool(np.percentile(d, 2.5) > 0 or np.percentile(d, 97.5) < 0),
        }

    results = {
        "experiment_id": "K1675",
        "title": "台股颱風臨時停市事件研究 — 復市首日跳空、報酬與前後 RV",
        "run_date": "2026-07-10",
        "trigger_event": {
            "date": "2026-07-10",
            "typhoon": "巴威 Bavi",
            "source": "config/market_closures_adhoc.json（detect_market_closure.py 自動偵測，NCDR/DGPA 停班停課 RSS：臺北市全日停止上班）",
            "note": "T+0 事件；不在 2012-2025 統計樣本內",
        },
        "sample_period": f"{SAMPLE_START} ~ {SAMPLE_END}",
        "data_sources": [
            "yfinance ^TWII (storage/macro/yf_TWII.csv)",
            "yfinance 0050.TW (storage/macro/yf_0050.TW.csv, 交叉驗證)",
            "exchange_calendars XTAI 4.13.2 (sessions + 結構化 typhoons 清單)",
            "TWSE 融資融券 (storage/sentiment/tw_margin_0050.csv, 殘差日交叉驗證)",
        ],
        "seed": SEED,
        "n_bootstrap": N_BOOT,
        "data_quality": {
            "twii_open_zero_gap_fraction": round(zero_gap_frac, 4),
            "note": "零跳空比例；過高代表 yfinance 以前日收盤回填開盤價，開盤跳空統計需保守解讀",
        },
        "closure_days": closures,
        "n_closure_days": len(closures),
        "n_events": len(event_rows),
        "derivation_audit": audit,
        "events": event_rows,
        "stats": {
            "closure_reopen_abs_gap": summarize(ev_gap),
            "closure_reopen_abs_ret": summarize(ev_ret),
            "closure_rv_ratio": summarize(ev_rvr),
            "control_abs_gap_same_months": summarize(ctrl_gap),
            "control_abs_ret_same_months": summarize(ctrl_ret),
            "control_monday_abs_gap": summarize(ctrl_gap_mon),
            "control_monday_abs_ret": summarize(ctrl_ret_mon),
            "diff_abs_ret_closure_minus_control": diff_ci(ev_ret, ctrl_ret),
            "diff_abs_ret_closure_minus_monday": diff_ci(ev_ret, ctrl_ret_mon),
            "diff_abs_gap_closure_minus_control": diff_ci(ev_gap, ctrl_gap),
            "diff_abs_gap_closure_minus_monday": diff_ci(ev_gap, ctrl_gap_mon),
        },
        "control_definition": {
            "primary": f"同月份（{closure_months} 月）2012-2025 普通交易日，排除任何停市日 ±5 個交易日，n={len(ctrl_ret)}",
            "secondary_monday": f"主對照中的週一（跨 2+ 日曆日 gap，與停市跨日結構較可比），n={len(ctrl_ret_mon)}",
        },
        "caveats": [
            f"停市事件僅 {len(event_rows)} 個（2012-2025），樣本小；bootstrap CI 寬，所有比較皆不足以宣稱統計顯著",
            "復市首日跳空橫跨 2+ 個日曆日（停市 + 可能的週末），與單日對照的隔夜 gap 結構不同；已用週一次對照緩解",
            "yfinance ^TWII 開盤價部分時期疑似回填（見 data_quality），跳空統計保守解讀；close-to-close 報酬不受影響",
            "颱風停市多在 7-10 月，對照已限同月份，但無法控制颱風本身對基本面的實質衝擊（災損）",
        ],
    }

    # ── RV path（±5 交易日事件時間）──
    tau_range = list(range(-5, 6))
    path_matrix = []
    for r in event_rows:
        p_day = pd.Timestamp(r["last_pre_close_day"])
        r_day = pd.Timestamp(r["reopen_day"])
        p_pos, r_pos = idx.get_loc(p_day), idx.get_loc(r_day)
        row = []
        for tau in tau_range:
            if tau <= 0:
                pos = p_pos + tau  # tau=0 → 停市前最後交易日
            else:
                pos = r_pos + (tau - 1)  # tau=1 → 復市首日
            x = ret.iloc[pos]
            if tau == 1:
                x = close.iloc[pos] / close.loc[p_day] - 1.0
            row.append(abs(x) * 100)
        path_matrix.append(row)
    path_arr = np.array(path_matrix)
    mean_path = path_arr.mean(axis=0)
    results["rv_path"] = {
        "tau": tau_range,
        "tau_definition": "tau<=0: 停市前第 |tau| 個交易日（0=最後交易日）；tau>=1: 復市後第 tau 個交易日",
        "mean_abs_ret_pct": [round(float(v), 4) for v in mean_path],
        "control_mean_abs_ret_pct": round(float(np.mean(ctrl_ret) * 100), 4),
    }

    # ── 圖 1: 復市首日 |報酬| vs 對照分佈 ──
    fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
    data = [ctrl_ret * 100, ctrl_ret_mon * 100, ev_ret * 100]
    labels = [f"普通交易日\n(同月份, n={len(ctrl_ret)})", f"普通週一\n(n={len(ctrl_ret_mon)})", f"颱風停市後首日\n(n={len(ev_ret)})"]
    bp = ax.boxplot(data, labels=labels, showfliers=False, patch_artist=True, widths=0.5)
    for patch, c in zip(bp["boxes"], ["#8faadc", "#a9c4a0", "#e8a87c"]):
        patch.set_facecolor(c)
    for i, arr in enumerate(data, start=1):
        jitter = rng.normal(0, 0.04, len(arr))
        ax.scatter(np.full(len(arr), i) + jitter, arr, s=8 if len(arr) > 50 else 30,
                   alpha=0.25 if len(arr) > 50 else 0.85, color="#444444", zorder=3)
    ax.set_ylabel("當日絕對報酬（%）")
    ax.set_title("台股颱風停市後首個交易日 vs 普通交易日：絕對報酬分佈（2012-2025）")
    ax.set_ylim(0, max(4.0, ev_ret.max() * 100 * 1.3))
    ax.grid(axis="y", alpha=0.3)
    fig.text(0.99, 0.01, "資料：yfinance ^TWII；K1675", ha="right", fontsize=7, color="#888888")
    fig.tight_layout()
    fig.savefig(OUT / "k1675_reopen_ret_dist.png")
    plt.close(fig)

    # ── 圖 2: 事件前後 ±5 日平均 |報酬| 路徑 ──
    fig, ax = plt.subplots(figsize=(8, 5), dpi=150)
    ax.plot(tau_range, mean_path, marker="o", color="#c0504d", label="停市事件平均（13 事件）")
    ax.fill_between(tau_range, path_arr.mean(0) - path_arr.std(0) / np.sqrt(len(path_arr)),
                    path_arr.mean(0) + path_arr.std(0) / np.sqrt(len(path_arr)),
                    alpha=0.15, color="#c0504d", label="±1 標準誤")
    ax.axhline(float(np.mean(ctrl_ret) * 100), ls="--", color="#555555",
               label=f"普通交易日平均 {np.mean(ctrl_ret)*100:.2f}%")
    ax.axvspan(0.25, 0.75, color="#bbbbbb", alpha=0.5)
    ax.text(0.5, ax.get_ylim()[1] * 0.92, "停市", ha="center", fontsize=9, color="#555555")
    ax.set_xticks(tau_range)
    ax.set_xlabel("事件時間（交易日；0 = 停市前最後交易日，1 = 復市首日）")
    ax.set_ylabel("平均絕對報酬（%）")
    ax.set_title("颱風停市前後 ±5 個交易日的平均每日絕對報酬（2012-2025，13 個事件）")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.text(0.99, 0.01, "資料：yfinance ^TWII；K1675", ha="right", fontsize=7, color="#888888")
    fig.tight_layout()
    fig.savefig(OUT / "k1675_rv_path.png")
    plt.close(fig)

    out_path = OUT / "k1675_results.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK — {len(closures)} closure days, {len(event_rows)} events")
    print(f"mean |reopen ret| = {np.mean(ev_ret)*100:.3f}% vs control {np.mean(ctrl_ret)*100:.3f}%")
    print(f"mean |reopen gap| = {np.mean(ev_gap)*100:.3f}% vs control {np.mean(ctrl_gap)*100:.3f}%")
    print(f"mean RV ratio = {np.mean(ev_rvr):.3f}")
    print(f"zero-gap fraction (open quality) = {zero_gap_frac:.3f}")
    print(f"results → {out_path}")


if __name__ == "__main__":
    main()
