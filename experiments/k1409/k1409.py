#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K1409 — 高股息 ETF「月月配 1 萬」規劃的 block-bootstrap 模擬

組合（固定張數，1 張 = 1000 股）：
    0056.TW  : 10   張
    00878.TW : 23.8 張
    00919.TW : 12.8 張

目標：每月領約 NT$1 萬（一年 12 萬），檢驗達標機率、淨值分布、下檔風險，
      並評估圖中隱含的 ~9.7% 現金殖利率是否過度樂觀。

研究誠實重點
------------
1. 價格用未還原收盤 (auto_adjust=False) 算 NAV 波動；配息現金流
   (Ticker.dividends) 另計，兩者明確分開、不重複計（不一邊用還原價、
   一邊又把配息加回）。
2. 三檔歷史長度不同（0056 ~2007、00878 ~2020、00919 ~2022 起）。價格報酬
   block bootstrap 母體取「三檔共同重疊期」（受 00919 限制 → 約 2022-04 起，
   ~50 個月），母體短且幾乎只經歷 2022 一次空頭 + 後續多頭 → 偏多頭，
   結論帶樂觀偏誤，於 README + results 明記。
3. 「月月配」是**日曆結構**（季配錯開），不是隨機事件：三檔實際除息月份合計
   覆蓋 12 個月中的 ~11 個（重疊期內僅 4 月無人配息）。因此配息模擬採
   **保留真實除息月曆 + 對每股金額做 bootstrap** 的設計：哪個月由哪檔配息
   是固定的（取自實際資料），只隨機抽「每股配多少」與價格報酬。若直接對
   「整月配息」做 block bootstrap 會打亂日曆對齊、虛構出大量 0 配息月
   （artifact），故不採用。
4. 0056 在重疊期間由年配轉季配；模擬以「每檔在重疊期實際發生的每次配息」
   為母體（不外插、不捏造金額），並依該檔在重疊期的年均配息次數安排日曆。
5. 所有隨機程序固定 seed = 20260530；bootstrap 次數 = 5000；horizon = 36 月。

用法
----
    uv run python experiments/k1409/k1409.py            # 有 cache 則離線跑
    uv run python experiments/k1409/k1409.py --refresh  # 重新從 yfinance 抓
"""
import os
import json
import argparse
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "PingFang TC", "Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
FIG_DIR = os.path.join(HERE, "figures")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(FIG_DIR, exist_ok=True)

SEED = 20260530
N_SIM = 5000
HORIZON_M = 36
BLOCK = 3                # 價格報酬 block bootstrap 區塊長度（月）
SHARES_PER_LOT = 1000

LOTS = {"0056.TW": 10.0, "00878.TW": 23.8, "00919.TW": 12.8}
SHARES = {k: v * SHARES_PER_LOT for k, v in LOTS.items()}
TICKERS = list(LOTS.keys())

MONTHLY_TARGET = 10_000.0
IMPLIED_YIELD = 0.097


# ---------------------------------------------------------------------------
# 1. 資料抓取（價格 + 配息分開，cache CSV）
# ---------------------------------------------------------------------------
def fetch_ticker(ticker, refresh=False):
    px_path = os.path.join(DATA_DIR, f"{ticker.replace('.','_')}_close.csv")
    dv_path = os.path.join(DATA_DIR, f"{ticker.replace('.','_')}_div.csv")
    if (not refresh) and os.path.exists(px_path) and os.path.exists(dv_path):
        px = pd.read_csv(px_path, parse_dates=["Date"]).set_index("Date")["Close"]
        dvdf = pd.read_csv(dv_path, parse_dates=["Date"])
        dv = dvdf.set_index("Date")["Dividend"] if len(dvdf) else pd.Series(dtype=float)
        return px, dv

    import yfinance as yf
    tk = yf.Ticker(ticker)
    h = tk.history(period="max", auto_adjust=False)   # 未還原收盤
    if h is None or h.empty:
        raise RuntimeError(f"{ticker}: price empty from yfinance")
    px = h["Close"].copy()
    px.index = pd.to_datetime(px.index).tz_localize(None)
    px = px[~px.index.duplicated(keep="last")].sort_index()
    px.to_frame("Close").reset_index().rename(columns={"index": "Date"}).to_csv(px_path, index=False)

    div = tk.dividends
    if div is None or len(div) == 0:
        dv = pd.Series(dtype=float)
        pd.DataFrame(columns=["Date", "Dividend"]).to_csv(dv_path, index=False)
    else:
        dv = div.copy()
        dv.index = pd.to_datetime(dv.index).tz_localize(None)
        dv = dv.sort_index()
        dv.to_frame("Dividend").reset_index().rename(columns={"index": "Date"}).to_csv(dv_path, index=False)
    return px, dv


# ---------------------------------------------------------------------------
# 2. 月度面板（共同重疊期）+ 每檔配息母體與日曆
# ---------------------------------------------------------------------------
def build_panel_and_dividends(prices, divs):
    monthly_ret = {}
    spans = {}
    for t in TICKERS:
        px = prices[t]
        spans[t] = (px.index.min(), px.index.max())
        m_close = px.resample("ME").last()
        monthly_ret[f"{t}_ret"] = m_close.pct_change()

    ret_panel = pd.DataFrame(monthly_ret)
    ret_cols = [f"{t}_ret" for t in TICKERS]
    common = ret_panel.dropna(subset=ret_cols)
    c_start, c_end = common.index.min(), common.index.max()

    # 每檔配息：取共同重疊期內實際發生的每次配息（每股金額），以及其除息月份
    div_pool = {}        # 每檔在重疊期的每股配息母體（每次配息一筆）
    div_months = {}      # 每檔實際除息日曆月份集合
    payments_per_year = {}
    for t in TICKERS:
        dv = divs[t]
        if len(dv):
            dv_ov = dv[(dv.index >= c_start) & (dv.index <= c_end + pd.offsets.MonthEnd(0))]
            dv_ov = dv_ov[dv_ov > 0]
        else:
            dv_ov = pd.Series(dtype=float)
        div_pool[t] = dv_ov.to_numpy() if len(dv_ov) else np.array([0.0])
        div_months[t] = sorted(set(dv_ov.index.month)) if len(dv_ov) else []
        # 重疊期年均配息次數（用於排日曆）
        n_years = max((c_end - c_start).days / 365.25, 1e-9)
        payments_per_year[t] = (len(dv_ov) / n_years) if len(dv_ov) else 0.0

    meta = {
        "spans": {t: (str(spans[t][0].date()), str(spans[t][1].date())) for t in TICKERS},
        "common_start": str(c_start.date()),
        "common_end": str(c_end.date()),
        "common_months": int(len(common)),
        "div_months_in_overlap": {t: div_months[t] for t in TICKERS},
        "n_payments_in_overlap": {t: int(len(div_pool[t])) if not (len(div_pool[t]) == 1 and div_pool[t][0] == 0) else 0 for t in TICKERS},
        "payments_per_year": {t: round(payments_per_year[t], 2) for t in TICKERS},
        "per_share_div_overlap": {t: [round(float(x), 4) for x in div_pool[t]] for t in TICKERS},
    }
    return common, div_pool, div_months, meta


def build_div_calendar(div_months):
    """為 36 個月 horizon 排定『每月每檔是否配息』(1/0)。
    用每檔在重疊期的實際除息月份 (1-12)，週期性鋪到 36 個月。
    起點月份 = 緊接最近資料月之後的下個月（calendar phase 用 1..12 對齊）。
    """
    # horizon month m 對應的日曆月 = ((start_month-1 + m) % 12) + 1
    # 取 start_month = 1（簡化，日曆相位不影響整體分布統計，只影響哪個月領）
    start_month = 1
    pay_flag = {t: np.zeros(HORIZON_M, dtype=bool) for t in TICKERS}
    cal_months = np.array([((start_month - 1 + m) % 12) + 1 for m in range(HORIZON_M)])
    for t in TICKERS:
        mset = set(div_months[t])
        pay_flag[t] = np.isin(cal_months, list(mset))
    return pay_flag, cal_months


# ---------------------------------------------------------------------------
# 3. 模擬：價格報酬 block bootstrap + 配息金額 bootstrap（保留真實月曆）
# ---------------------------------------------------------------------------
def simulate(panel, div_pool, div_months, prices, rng):
    ret_arr = {t: panel[f"{t}_ret"].to_numpy() for t in TICKERS}
    n = len(panel)
    max_start = n - BLOCK
    if max_start < 0:
        raise RuntimeError("共同重疊期月份數不足以做 block bootstrap")
    n_blocks = int(np.ceil(HORIZON_M / BLOCK))

    pay_flag, cal_months = build_div_calendar(div_months)

    last_px = {t: float(prices[t].iloc[-1]) for t in TICKERS}
    principal_t = {t: last_px[t] * SHARES[t] for t in TICKERS}
    principal = sum(principal_t.values())

    nav = np.zeros((N_SIM, HORIZON_M))
    monthly_div_cash = np.zeros((N_SIM, HORIZON_M))

    for s in range(N_SIM):
        # --- 價格報酬：所有檔共用同一組 block 起點 → 保留跨資產同期連動 ---
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        idx = np.concatenate([np.arange(st, st + BLOCK) for st in starts])[:HORIZON_M]
        nav_row = np.zeros(HORIZON_M)
        for t in TICKERS:
            growth = np.cumprod(1.0 + ret_arr[t][idx])
            nav_row += principal_t[t] * growth
            # --- 配息：真實除息月領，每股金額從母體 bootstrap ---
            pf = pay_flag[t]
            k = int(pf.sum())
            if k > 0 and len(div_pool[t]) > 0:
                amt = rng.choice(div_pool[t], size=k, replace=True)
                monthly_div_cash[s, pf] += amt * SHARES[t]
        nav[s] = nav_row

    # ---- 統計 ----
    def pct(a, q):
        return float(np.percentile(a, q))

    md_flat = monthly_div_cash.flatten()
    # 只看「實際有配息月份」的分布（排除日曆上本就無人配息的月，如 4 月）
    paid_mask_cal = np.zeros(HORIZON_M, dtype=bool)
    for t in TICKERS:
        paid_mask_cal |= pay_flag[t]
    md_paid_months = monthly_div_cash[:, paid_mask_cal].flatten()

    monthly_div_stats = {
        "all_months_median": pct(md_flat, 50),
        "all_months_p5": pct(md_flat, 5),
        "all_months_p95": pct(md_flat, 95),
        "all_months_mean": float(md_flat.mean()),
        "all_months_P_ge_10000": float((md_flat >= MONTHLY_TARGET).mean()),
        "all_months_P_zero": float((md_flat <= 1e-9).mean()),
        "paid_months_median": pct(md_paid_months, 50),
        "paid_months_p5": pct(md_paid_months, 5),
        "paid_months_p95": pct(md_paid_months, 95),
        "paid_months_P_ge_10000": float((md_paid_months >= MONTHLY_TARGET).mean()),
        "calendar_months_with_any_dividend": int(len(set(cal_months[paid_mask_cal]))),
    }

    avg_md_per_sim = monthly_div_cash.mean(axis=1)
    monthly_div_avg_stats = {
        "median": pct(avg_md_per_sim, 50),
        "p5": pct(avg_md_per_sim, 5),
        "p95": pct(avg_md_per_sim, 95),
        "P_avg_ge_10000": float((avg_md_per_sim >= MONTHLY_TARGET).mean()),
    }

    nav_stats = {}
    for m in (6, 12, 36):
        col = nav[:, m - 1]
        nav_stats[f"m{m}"] = {"median": pct(col, 50), "p5": pct(col, 5), "p95": pct(col, 95)}

    cum_div = monthly_div_cash.cumsum(axis=1)
    total_wealth_36 = nav[:, -1] + cum_div[:, -1]
    total_ret_36 = total_wealth_36 / principal - 1.0
    price_ret_36 = nav[:, -1] / principal - 1.0
    div_ret_36 = cum_div[:, -1] / principal
    total_ret_stats = {
        "median": pct(total_ret_36, 50), "p5": pct(total_ret_36, 5), "p95": pct(total_ret_36, 95),
        "price_only_median": pct(price_ret_36, 50),
        "div_only_median": pct(div_ret_36, 50),
        "P_total_negative": float((total_ret_36 < 0).mean()),
    }

    wealth_path = nav + cum_div
    run_max = np.maximum.accumulate(wealth_path, axis=1)
    mdd_per_sim = (wealth_path / run_max - 1.0).min(axis=1)
    run_max_nav = np.maximum.accumulate(nav, axis=1)
    mdd_nav_per_sim = (nav / run_max_nav - 1.0).min(axis=1)

    var5 = pct(total_ret_36, 5)
    cvar5 = float(total_ret_36[total_ret_36 <= var5].mean())
    downside = {
        "MDD_wealth_median": pct(mdd_per_sim, 50),
        "MDD_wealth_p5_worst": pct(mdd_per_sim, 5),
        "MDD_nav_median": pct(mdd_nav_per_sim, 50),
        "MDD_nav_p5_worst": pct(mdd_nav_per_sim, 5),
        "VaR5_total_ret_36m": var5,
        "CVaR5_total_ret_36m": cvar5,
        "nav_p5_36m": nav_stats["m36"]["p5"],
        "nav_p5_drawdown_vs_principal": nav_stats["m36"]["p5"] / principal - 1.0,
    }

    realized_yield_per_sim = (avg_md_per_sim * 12.0) / principal
    yield_stats = {
        "implied_yield_from_chart": IMPLIED_YIELD,
        "realized_yield_median": pct(realized_yield_per_sim, 50),
        "realized_yield_p5": pct(realized_yield_per_sim, 5),
        "realized_yield_p95": pct(realized_yield_per_sim, 95),
        "P_realized_ge_implied": float((realized_yield_per_sim >= IMPLIED_YIELD).mean()),
    }

    arrays = {
        "monthly_div_cash": monthly_div_cash,
        "nav": nav,
        "total_ret_36": total_ret_36,
        "mdd_per_sim": mdd_per_sim,
        "realized_yield_per_sim": realized_yield_per_sim,
        "paid_mask_cal": paid_mask_cal,
        "cal_months": cal_months,
    }
    results = {
        "principal_total": principal,
        "principal_by_ticker": principal_t,
        "last_close": last_px,
        "monthly_div_stats": monthly_div_stats,
        "monthly_div_avg_stats": monthly_div_avg_stats,
        "nav_stats": nav_stats,
        "total_ret_stats_36m": total_ret_stats,
        "downside_risk": downside,
        "yield_stats": yield_stats,
    }
    return results, arrays


# ---------------------------------------------------------------------------
# 4. 圖
# ---------------------------------------------------------------------------
def make_figures(results, arrays):
    md = arrays["monthly_div_cash"]
    nav = arrays["nav"]
    paid_mask = arrays["paid_mask_cal"]

    # (a) 月配息分布（只看有配息月，避開日曆 0 月稀釋）
    fig, ax = plt.subplots(figsize=(8, 5))
    md_paid = md[:, paid_mask].flatten()
    hi = np.percentile(md_paid, 99.5)
    ax.hist(md_paid[md_paid <= hi], bins=60, color="#4C72B0", alpha=0.85)
    s = results["monthly_div_stats"]
    ax.axvline(MONTHLY_TARGET, color="red", lw=2, ls="--",
               label=f"目標 1 萬（有配息月達標率 {s['paid_months_P_ge_10000']*100:.1f}%）")
    ax.axvline(s["paid_months_median"], color="green", lw=2, label=f"中位數 {s['paid_months_median']:,.0f}")
    ax.axvline(s["paid_months_p5"], color="orange", lw=1.5, ls=":", label=f"5% 分位 {s['paid_months_p5']:,.0f}")
    ax.axvline(s["paid_months_p95"], color="purple", lw=1.5, ls=":", label=f"95% 分位 {s['paid_months_p95']:,.0f}")
    ax.set_title("圖(a) 有配息月份的單月配息分布")
    ax.set_xlabel("單月組合配息（新台幣）")
    ax.set_ylabel("頻次")
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "a_monthly_dividend_dist.png"), dpi=130)
    plt.close(fig)

    # (b) 淨值 fan chart
    fig, ax = plt.subplots(figsize=(8, 5))
    months = np.arange(1, HORIZON_M + 1)
    p5 = np.percentile(nav, 5, axis=0)
    p25 = np.percentile(nav, 25, axis=0)
    p50 = np.percentile(nav, 50, axis=0)
    p75 = np.percentile(nav, 75, axis=0)
    p95 = np.percentile(nav, 95, axis=0)
    principal = results["principal_total"]
    ax.fill_between(months, p5, p95, color="#4C72B0", alpha=0.20, label="5–95% 區間")
    ax.fill_between(months, p25, p75, color="#4C72B0", alpha=0.40, label="25–75% 區間")
    ax.plot(months, p50, color="#1f3b6f", lw=2, label="中位數")
    ax.axhline(principal, color="black", lw=1.2, ls="--", label=f"初始本金 {principal:,.0f}")
    for m in (6, 12, 36):
        ax.axvline(m, color="grey", lw=0.7, ls=":")
    ax.set_title("圖(b) 投資組合淨值路徑 fan chart（固定張數，未還原價）")
    ax.set_xlabel("月")
    ax.set_ylabel("組合淨值（新台幣，不含已領配息）")
    ax.legend(fontsize=9, loc="best")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "b_nav_fanchart.png"), dpi=130)
    plt.close(fig)

    # (c) 達標機率 / 下檔風險
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    s = results["monthly_div_stats"]
    s_avg = results["monthly_div_avg_stats"]
    labels = ["有配息月\n單月≥1萬", "平均月配息\n≥1萬"]
    vals = [s["paid_months_P_ge_10000"] * 100, s_avg["P_avg_ge_10000"] * 100]
    bars = axes[0].bar(labels, vals, color=["#C44E52", "#55A868"])
    for b, v in zip(bars, vals):
        axes[0].text(b.get_x() + b.get_width() / 2, v + 1, f"{v:.1f}%", ha="center", fontsize=11)
    axes[0].set_ylim(0, 105)
    axes[0].set_ylabel("達標機率 (%)")
    axes[0].set_title("圖(c1) 月月領 1 萬達標機率")
    d = results["downside_risk"]
    rlabels = ["MDD\n中位數", "MDD\n5%最壞", "VaR5\n36m", "CVaR5\n36m", "淨值\n5%回撤"]
    rvals = [d["MDD_wealth_median"], d["MDD_wealth_p5_worst"],
             d["VaR5_total_ret_36m"], d["CVaR5_total_ret_36m"],
             d["nav_p5_drawdown_vs_principal"]]
    rvals = [v * 100 for v in rvals]
    rbars = axes[1].bar(rlabels, rvals, color="#C44E52")
    for b, v in zip(rbars, rvals):
        axes[1].text(b.get_x() + b.get_width() / 2, v - 1.5, f"{v:.1f}%", ha="center", va="top", fontsize=10)
    axes[1].axhline(0, color="black", lw=0.8)
    axes[1].set_ylabel("報酬 / 回撤 (%)")
    axes[1].set_title("圖(c2) 下檔風險（負值=虧損/回撤）")
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "c_target_and_downside.png"), dpi=130)
    plt.close(fig)

    # (d) 隱含 vs 可實現殖利率
    fig, ax = plt.subplots(figsize=(8, 5))
    ry = arrays["realized_yield_per_sim"] * 100
    ax.hist(ry, bins=50, color="#55A868", alpha=0.85)
    y = results["yield_stats"]
    ax.axvline(IMPLIED_YIELD * 100, color="red", lw=2, ls="--",
               label=f"圖中隱含 {IMPLIED_YIELD*100:.1f}%（模擬達此率機率 {y['P_realized_ge_implied']*100:.1f}%）")
    ax.axvline(y["realized_yield_median"] * 100, color="green", lw=2,
               label=f"模擬中位數 {y['realized_yield_median']*100:.2f}%")
    ax.axvline(y["realized_yield_p5"] * 100, color="orange", lw=1.5, ls=":",
               label=f"5% 分位 {y['realized_yield_p5']*100:.2f}%")
    ax.set_title("圖(d) 隱含 9.7% vs 模擬可實現現金殖利率")
    ax.set_xlabel("年化現金殖利率 (%)")
    ax.set_ylabel("頻次")
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "d_yield_implied_vs_realized.png"), dpi=130)
    plt.close(fig)


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    rng = np.random.default_rng(SEED)

    prices, divs = {}, {}
    for t in TICKERS:
        px, dv = fetch_ticker(t, refresh=args.refresh)
        prices[t] = px
        divs[t] = dv

    panel, div_pool, div_months, meta = build_panel_and_dividends(prices, divs)
    results, arrays = simulate(panel, div_pool, div_months, prices, rng)
    make_figures(results, arrays)

    s = results["monthly_div_stats"]
    s_avg = results["monthly_div_avg_stats"]
    y = results["yield_stats"]
    d = results["downside_risk"]
    verdict = {
        "paid_month_hit_prob": s["paid_months_P_ge_10000"],
        "avg_monthly_hit_prob": s_avg["P_avg_ge_10000"],
        "calendar_months_covered": s["calendar_months_with_any_dividend"],
        "bad_case_paid_month_div_p5": s["paid_months_p5"],
        "nav_p5_36m": results["nav_stats"]["m36"]["p5"],
        "nav_p5_drawdown_vs_principal": d["nav_p5_drawdown_vs_principal"],
        "implied_yield": IMPLIED_YIELD,
        "realized_yield_median": y["realized_yield_median"],
        "implied_optimistic": bool(y["realized_yield_median"] < IMPLIED_YIELD),
        "summary": (
            "季配錯開使 12 個日曆月中約 11 個有配息（4 月空窗）；但『有配息月就能領滿 1 萬』"
            "達標率不高，平均月配息達 1 萬的機率更低，因為實際可實現殖利率中位數"
            f"({y['realized_yield_median']*100:.1f}%) 低於圖中隱含 9.7%。隱含值偏樂觀。"
            "母體短且偏多頭，真實下檔風險與斷配風險很可能被低估。"
        ),
    }

    out = {
        "experiment_id": "k1409",
        "title": "高股息 ETF 月月配 1 萬規劃 block-bootstrap 模擬",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "tickers": TICKERS, "lots": LOTS, "shares": SHARES,
            "seed": SEED, "n_sim": N_SIM, "horizon_months": HORIZON_M,
            "price_block_size_months": BLOCK,
            "monthly_target_ntd": MONTHLY_TARGET,
            "implied_yield_from_chart": IMPLIED_YIELD,
            "price_basis": "auto_adjust=False raw close (price return only, no dividend re-added)",
            "dividend_basis": "Ticker.dividends; real ex-div calendar months preserved, per-share amount bootstrapped from overlap-period payment pool, counted as cash separately from price",
            "method": "price returns: joint block bootstrap (block=3m) over common-overlap monthly returns; dividends: real calendar schedule + amount bootstrap",
        },
        "data_meta": meta,
        "results": results,
        "verdict": verdict,
        "data_limitations": [
            "價格報酬 bootstrap 母體取三檔共同重疊期（受 00919 yfinance 價格 ~2022-10 起限制）。",
            f"共同重疊期僅 {meta['common_months']} 個月（{meta['common_start']} ~ {meta['common_end']}），樣本短。",
            "重疊期幾乎只經歷 2022 一次空頭 + 後續多頭 → 偏多頭，下檔風險與殖利率結論帶樂觀偏誤。",
            "配息金額母體為重疊期實際每次配息；若未來配息政策縮水或斷配，模型未涵蓋（樂觀偏誤）。",
            "0056 重疊期內由年配轉季配；模型用實際發生的配息次數與金額，不外插歷史年配型態。",
            "block bootstrap 假設未來月報酬/配息與重疊期同分布；長空頭或殖利率結構改變時實際更差。",
            "模型未計交易成本、二代健保補充保費、股利所得稅，實際可支配現金流會更低。",
        ],
    }

    out_path = os.path.join(HERE, "k1409_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("=== K1409 verdict ===")
    print(f"本金合計: {results['principal_total']:,.0f}  (0056 {results['principal_by_ticker']['0056.TW']:,.0f} / "
          f"00878 {results['principal_by_ticker']['00878.TW']:,.0f} / 00919 {results['principal_by_ticker']['00919.TW']:,.0f})")
    print(f"共同重疊期: {meta['common_start']} ~ {meta['common_end']} ({meta['common_months']} months)")
    print(f"除息日曆覆蓋月數: {s['calendar_months_with_any_dividend']}/12")
    print(f"有配息月 單月配息 median/p5/p95: {s['paid_months_median']:,.0f} / {s['paid_months_p5']:,.0f} / {s['paid_months_p95']:,.0f}")
    print(f"P(有配息月 >= 1萬) = {s['paid_months_P_ge_10000']*100:.1f}%")
    print(f"P(平均月配息 >= 1萬) = {s_avg['P_avg_ge_10000']*100:.1f}% ; 平均月配息 median = {s_avg['median']:,.0f}")
    print(f"NAV 36m median/p5/p95: {results['nav_stats']['m36']['median']:,.0f} / "
          f"{results['nav_stats']['m36']['p5']:,.0f} / {results['nav_stats']['m36']['p95']:,.0f}")
    print(f"NAV 5% 回撤 vs 本金: {d['nav_p5_drawdown_vs_principal']*100:.1f}%")
    print(f"MDD(wealth) median/p5: {d['MDD_wealth_median']*100:.1f}% / {d['MDD_wealth_p5_worst']*100:.1f}%")
    print(f"VaR5 / CVaR5 (36m total ret): {d['VaR5_total_ret_36m']*100:.1f}% / {d['CVaR5_total_ret_36m']*100:.1f}%")
    print(f"隱含殖利率 {IMPLIED_YIELD*100:.1f}% vs 可實現中位數 {y['realized_yield_median']*100:.2f}% "
          f"(p5 {y['realized_yield_p5']*100:.2f}%, p95 {y['realized_yield_p95']*100:.2f}%, P>=隱含 {y['P_realized_ge_implied']*100:.1f}%)")
    print(f"results -> {out_path}")


if __name__ == "__main__":
    main()
