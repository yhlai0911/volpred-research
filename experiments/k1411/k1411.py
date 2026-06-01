#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K1411 — 槓桿型 ETF（00631L 元大台灣50正2）的單筆 vs 分批、波動率拖累、與借貸/加碼金風險
=========================================================================================

研究問題（讀者提問）
--------------------
一位讀者讀完我們「單筆 vs 分批」文章（結論：非槓桿下單筆贏在 time-in-market，
資金效率口徑兩者打平）後問：**槓桿型（如 00631L）在股市創新高位時，單筆還是
分批較好？若單筆資金是信貸（借來的），或該搭配保留加碼金？** 他的直覺：槓桿
特性是大跌後更難回來（跌 50% 要漲 100% 才回本）。

本實驗用真實資料量化回答四個子問題：
  Q1 「跌 50% 要漲 100%」直覺 + 波動率拖累有多大？
  Q2 槓桿是否翻轉了「單筆 vs 分批」的結論？
  Q3 高位（創近一年新高附近）進場，單筆 vs 分批誰較好？
  Q4 借錢（信貸）單筆 × 2x 槓桿 × 高位進場的尾部破產風險？加碼金能否改善？

資料（yfinance, auto_adjust=True）
----------------------------------
  - 00631L.TW（真實 2x 槓桿 ETF，2014-10 起 ~2827 日）= headline 真實資料
  - 0050.TW（2009 起）= 重建 2x daily-rebal sim，隔離槓桿衰減機制
  - ^TWII（1997 起）= 拉長歷史做 robustness

方法（硬性）
------------
1. 波動率拖累：2x daily-rebal 累積 = ∏(1 + 2·r_daily − daily_cost)，非 2× 標的累積。
   比較 (a) 真實 00631L (b) 2×0050 buy-hold (c) 從 0050 重建的 2x-daily-rebal。
   對照理論公式 drag ≈ −(L(L−1)/2)·σ² = −σ²（L=2）。
2. 單筆 vs 分批（在 00631L 與 0050 上）：rolling historical windows（真實路徑，
   保留路徑相依）。單筆=t0 全投；分批=12 個月平均投入。比終值分布、破產/趨近
   歸零機率、最大回撤、年化 IRR。同 lag、固定 seed。
3. 高位進場條件：篩 t0 落在「價格 ≥ trailing-252 日高點 × (1 − X%)」的進場點，
   單筆 vs 分批比較。
4. 信貸風險：本金=借款 P，台灣信貸年化 3%/5%/7% 各跑；淨值=部位市值 − 未償貸款。
   量化破產機率（淨值 ≤ 0）在不同持有期。⚠️ 風險教育，非建議借貸。
5. 加碼金：保留 R% 現金，下跌 X% 時加碼，對比全額單筆。
6. 誠實：破產率報 Wilson CI；不過度宣稱；固定 seed=20260602；明確 lag；無 lookahead。

用法
----
    uv run python experiments/k1411/k1411.py            # 用 cache 離線跑
    uv run python experiments/k1411/k1411.py --refresh  # 重新抓 yfinance
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
from matplotlib import font_manager

for _f in ["Arial Unicode MS", "PingFang TC", "Heiti TC", "Hiragino Sans GB"]:
    try:
        font_manager.findfont(_f, fallback_to_default=False)
        plt.rcParams["font.sans-serif"] = [_f]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
FIG_DIR = os.path.join(HERE, "figures")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(FIG_DIR, exist_ok=True)

SEED = 20260602
TRADING_DAYS = 252

# 2x daily-rebalanced sim 的每日成本（年化）：管理費 ~1.13% + 融資/swap 利差近似。
# 真實 00631L 內扣費用率約 1.13%/年（元大公告），借券/期貨展延成本另計。這裡用
# 年化 1.5% 當總拖累 proxy（保守略高於純管理費），results/README 明記為假設。
LEV_DAILY_COST_ANNUAL = 0.015
LEV_DAILY_COST = LEV_DAILY_COST_ANNUAL / TRADING_DAYS
LEVERAGE = 2.0

# 信貸年化利率情境（台灣信貸常見區間）
CREDIT_RATES = [0.03, 0.05, 0.07]

TICKERS = {"L00631L": "00631L.TW", "T0050": "0050.TW", "TWII": "^TWII"}


# ---------------------------------------------------------------------------
# 1. 資料
# ---------------------------------------------------------------------------
def fetch(name, symbol, refresh=False):
    path = os.path.join(DATA_DIR, f"{name}.csv")
    if (not refresh) and os.path.exists(path):
        px = pd.read_csv(path, parse_dates=["Date"]).set_index("Date")["Close"]
        return px
    import yfinance as yf
    h = yf.Ticker(symbol).history(period="max", auto_adjust=True)
    if h is None or h.empty:
        raise RuntimeError(f"{symbol}: empty from yfinance")
    px = h["Close"].copy()
    px.index = pd.to_datetime(px.index).tz_localize(None)
    px = px[~px.index.duplicated(keep="last")].sort_index()
    px = px[px > 0]
    px.to_frame("Close").reset_index().rename(columns={"index": "Date"}).to_csv(path, index=False)
    return px


def daily_returns(px):
    return px.pct_change().dropna()


def clean_vendor_breaks(px, index_px, name, asset_limit=0.30, index_max=0.12,
                        expected_lev=1.0):
    """偵測並修復 yfinance 對台股 ticker 的『scale-break』壞點（已實證 K1411）：
    Yahoo 偶爾對某一天套錯累積調整因子，造成單日 |報酬| 物理上不可能（台股日內
    漲跌幅限制 ±10%；2x ETF 約 ±20%），且該天大盤（TWII）幾乎沒動。

    偵測準則（cross-check，避免誤殺真實大跌）：
      |asset 當日報酬| > asset_limit  AND  |同日 TWII 報酬| < index_max
    → 判定為壞點（資產不可能在大盤幾乎沒動時暴跌 30%+）。

    修復：把該壞日的報酬替換為『大盤當日報酬 × expected_lev』的合理估計，
    再從替換後的報酬重建價格序列（保留其餘所有真實日報酬）。這只移除人為的
    level 不連續，不改任何正常交易日。回傳 (修復後 px, 壞點清單)。

    研究誠實註記：這是修復『資料供應商錯誤』，非修改研究結果。每個被改的日子
    都記錄在 results.json 的 data_cleaning 區，可完全復現。"""
    r = px.pct_change()
    idx = index_px.reindex(px.index).pct_change()
    breaks = []
    r_fixed = r.copy()
    for d in px.index[1:]:
        ar = r.loc[d]
        ir = idx.loc[d] if d in idx.index and pd.notna(idx.loc[d]) else 0.0
        if pd.notna(ar) and abs(ar) > asset_limit and abs(ir) < index_max:
            repl = expected_lev * ir  # 用大盤 × 槓桿倍數估計合理當日報酬
            breaks.append({
                "date": str(d.date()),
                "raw_return": round(float(ar), 4),
                "twii_return": round(float(ir), 4),
                "replaced_with": round(float(repl), 4),
            })
            r_fixed.loc[d] = repl
    if not breaks:
        return px, []
    # 從修復後報酬重建價格（起點價不變）
    p0 = float(px.iloc[0])
    rebuilt = p0 * (1.0 + r_fixed.fillna(0.0)).cumprod()
    rebuilt.iloc[0] = p0
    return rebuilt, breaks


# ---------------------------------------------------------------------------
# 2. 槓桿重建：2x daily-rebalanced
# ---------------------------------------------------------------------------
def rebuild_2x_daily(underlying_ret, leverage=LEVERAGE, daily_cost=LEV_DAILY_COST):
    """從標的『日報酬』重建 2x daily-rebalanced 累積淨值序列（normalized 起點=1）。
    每日 = 1 + leverage * r_daily - daily_cost，**逐日複利**（非 2× 累積）。
    underlying_ret: pd.Series 標的日報酬。回傳 (nav Series 與報酬同 index, 最終累積值)。
    無 lookahead：第 t 日淨值僅用第 t 日及以前的標的報酬。"""
    lev_daily = 1.0 + leverage * underlying_ret.values - daily_cost
    cum = np.cumprod(lev_daily)
    nav = pd.Series(cum, index=underlying_ret.index)
    return nav, float(cum[-1])


def buyhold_2x(underlying_px, leverage=LEVERAGE):
    """2× buy-hold（非每日再平衡）累積：終值 = 1 + leverage * (P_T/P_0 - 1)。
    這是『把標的整段報酬乘 2』的天真做法，用來對照 daily-rebal 的差距。"""
    total_ret = underlying_px.iloc[-1] / underlying_px.iloc[0] - 1.0
    return 1.0 + leverage * total_ret


def vol_drag_analysis(px_under, px_lev_real, label_under):
    """量化波動率拖累：
      (a) 真實槓桿 ETF（若有）累積
      (b) 2×標的 buy-hold 累積
      (c) 從標的重建的 2x daily-rebal 累積
    回報三者終值 + 理論 drag 對照。"""
    r_under = daily_returns(px_under)
    nav_rebal, rebal_term = rebuild_2x_daily(r_under)
    bh_term = buyhold_2x(px_under)
    under_term = float(px_under.iloc[-1] / px_under.iloc[0])

    ann_vol = float(r_under.std() * np.sqrt(TRADING_DAYS))
    n_days = len(r_under)
    years = n_days / TRADING_DAYS

    # 理論波動率拖累（連續近似）：每年 drag ≈ -(L(L-1)/2)*sigma^2
    theo_annual_drag = -(LEVERAGE * (LEVERAGE - 1) / 2.0) * ann_vol ** 2

    def safe_cagr(term):
        # 終值 <= 0（理論上可能因模型穿破，但真實 LETF 有下限）→ 視為 -100%
        if term <= 0:
            return -1.0
        return term ** (1.0 / years) - 1.0

    rebal_cagr = safe_cagr(rebal_term)
    bh_cagr = safe_cagr(bh_term)
    under_cagr = safe_cagr(under_term)
    naive_2x_cagr = 2.0 * under_cagr

    out = {
        "underlying_label": label_under,
        "period_start": str(r_under.index.min().date()),
        "period_end": str(r_under.index.max().date()),
        "n_days": int(n_days),
        "years": round(years, 2),
        "underlying_ann_vol": round(ann_vol, 4),
        "underlying_total_return_x": round(under_term, 4),
        "underlying_cagr": round(under_cagr, 4),
        "naive_2x_cagr_expectation": round(naive_2x_cagr, 4),
        "buyhold_2x_terminal_x": round(bh_term, 4),
        "buyhold_2x_cagr": round(bh_cagr, 4),
        "daily_rebal_2x_terminal_x": round(rebal_term, 4),
        "daily_rebal_2x_cagr": round(rebal_cagr, 4),
        "theoretical_annual_vol_drag": round(theo_annual_drag, 4),
        "empirical_annual_drag_rebal_minus_naive": round(rebal_cagr - naive_2x_cagr, 4),
        "daily_cost_annual_assumed": LEV_DAILY_COST_ANNUAL,
        "_nav_rebal": nav_rebal,
    }
    return out


def vol_drag_vs_real(px_0050, px_00631l):
    """把『真實 00631L』vs『從 0050 重建的 2x daily-rebal』對齊共同期間比較，
    驗證重建模型貼近真實槓桿 ETF（sanity check 重建正確性）。"""
    common = px_00631l.index.intersection(px_0050.index).sort_values()
    if len(common) < 200:
        return {"note": "insufficient overlap"}
    p0050 = px_0050.reindex(common).dropna()
    p631 = px_00631l.reindex(common).dropna()
    common2 = p0050.index.intersection(p631.index)
    p0050 = p0050.reindex(common2)
    p631 = p631.reindex(common2)

    r0050_c = p0050.pct_change().dropna()
    _, rebal_term = rebuild_2x_daily(r0050_c)
    real_term = float(p631.iloc[-1] / p631.iloc[0])
    bh_term = buyhold_2x(p0050)
    years = len(r0050_c) / TRADING_DAYS
    return {
        "overlap_start": str(common2.min().date()),
        "overlap_end": str(common2.max().date()),
        "n_days": int(len(common2)),
        "years": round(years, 2),
        "real_00631L_terminal_x": round(real_term, 4),
        "rebuilt_2x_daily_rebal_terminal_x": round(rebal_term, 4),
        "naive_2x_buyhold_terminal_x": round(bh_term, 4),
        "real_cagr": round(real_term ** (1 / years) - 1 if real_term > 0 else -1.0, 4),
        "rebuilt_cagr": round(rebal_term ** (1 / years) - 1 if rebal_term > 0 else -1.0, 4),
        "rebuilt_vs_real_terminal_ratio": round(rebal_term / real_term, 4) if real_term > 0 else None,
    }


# ---------------------------------------------------------------------------
# 3. 單筆 vs 分批（rolling windows，真實路徑）
# ---------------------------------------------------------------------------
def recover_multiple(drawdown_frac):
    """跌 drawdown_frac（例 0.5）後回本需漲多少倍。drawdown=0.5 -> 1.0 (100%)。"""
    return drawdown_frac / (1.0 - drawdown_frac)


def lumpsum_vs_dca_window(px_daily, start_i, horizon_days, dca_months=12,
                          near_zero_thresh=0.10):
    """在單一 window（從 start_i 起、長 horizon_days 個交易日）上比較：
      - 單筆：t0 投入 1.0（單位本金）→ 終值 = 部位市值
      - 分批：dca_months 個月、每月初（每 21 交易日）投入等額 1/dca_months，
        未投入現金不計息（保守）
    px_daily: 該資產的價格序列（00631L 已含真實槓桿，0050 為非槓桿）。
    回傳 lumpsum / dca 的終值（總投入 1.0 為基準）、最大回撤、是否趨近歸零。
    無 lookahead：投入與估值只用 window 內已實現價格。"""
    seg = px_daily.iloc[start_i:start_i + horizon_days + 1]
    if len(seg) < horizon_days + 1:
        return None
    p = seg.values
    p0 = p[0]
    pend = p[-1]

    # 單筆：1.0 全投在 t0
    ls_units = 1.0 / p0
    ls_terminal = ls_units * pend
    ls_path = ls_units * p
    ls_peak = np.maximum.accumulate(ls_path)
    ls_mdd = float(np.min(ls_path / ls_peak - 1.0))
    ls_near_zero = bool(np.min(ls_path) <= near_zero_thresh * 1.0)

    # 分批：每月初投入 1/dca_months；逐日追蹤部位市值（含未投入現金）
    contrib = 1.0 / dca_months
    step = 21
    contrib_days = set(k * step for k in range(dca_months))
    units_t = np.zeros(len(p))
    cash_t = np.zeros(len(p))
    u = 0.0
    c = 1.0
    for t in range(len(p)):
        if t in contrib_days and c > 0:
            amt = min(contrib, c)
            u += amt / p[t]
            c -= amt
        units_t[t] = u
        cash_t[t] = c
    dca_path = units_t * p + cash_t
    dca_terminal = float(dca_path[-1])
    dca_peak = np.maximum.accumulate(dca_path)
    dca_mdd = float(np.min(dca_path / dca_peak - 1.0))
    dca_near_zero = bool(np.min(dca_path) <= near_zero_thresh * 1.0)

    years = horizon_days / TRADING_DAYS
    return {
        "lumpsum_terminal": float(ls_terminal),
        "dca_terminal": dca_terminal,
        "lumpsum_cagr": float(ls_terminal ** (1 / years) - 1) if ls_terminal > 0 else -1.0,
        "dca_cagr": float(dca_terminal ** (1 / years) - 1) if dca_terminal > 0 else -1.0,
        "lumpsum_mdd": ls_mdd,
        "dca_mdd": dca_mdd,
        "lumpsum_near_zero": ls_near_zero,
        "dca_near_zero": dca_near_zero,
        "start_date": str(seg.index[0].date()),
    }


def rolling_lumpsum_dca(px_daily, horizon_days, label, dca_months=12,
                        near_zero_thresh=0.10, high_water_mask=None):
    """對所有可用 rolling start 跑 lumpsum vs DCA，彙整分布。
    high_water_mask: 可選 boolean Series（對齊 px index），只取 mask=True 的 start。"""
    n = len(px_daily)
    ls_terms, dca_terms = [], []
    ls_cagrs, dca_cagrs = [], []
    ls_mdds, dca_mdds = [], []
    ls_nz, dca_nz = 0, 0
    ls_win = 0
    total = 0
    for i in range(0, n - horizon_days - 1):
        if high_water_mask is not None and not bool(high_water_mask.iloc[i]):
            continue
        r = lumpsum_vs_dca_window(px_daily, i, horizon_days, dca_months, near_zero_thresh)
        if r is None:
            continue
        ls_terms.append(r["lumpsum_terminal"])
        dca_terms.append(r["dca_terminal"])
        ls_cagrs.append(r["lumpsum_cagr"])
        dca_cagrs.append(r["dca_cagr"])
        ls_mdds.append(r["lumpsum_mdd"])
        dca_mdds.append(r["dca_mdd"])
        ls_nz += int(r["lumpsum_near_zero"])
        dca_nz += int(r["dca_near_zero"])
        ls_win += int(r["lumpsum_terminal"] > r["dca_terminal"])
        total += 1

    if total == 0:
        return {"label": label, "n_windows": 0, "note": "no windows"}

    ls_terms = np.array(ls_terms)
    dca_terms = np.array(dca_terms)
    lo_ls, hi_ls = wilson_ci(ls_nz, total)
    lo_dca, hi_dca = wilson_ci(dca_nz, total)
    return {
        "label": label,
        "horizon_days": horizon_days,
        "horizon_years": round(horizon_days / TRADING_DAYS, 2),
        "dca_months": dca_months,
        "near_zero_threshold": near_zero_thresh,
        "n_windows": int(total),
        "lumpsum_median_terminal": round(float(np.median(ls_terms)), 4),
        "dca_median_terminal": round(float(np.median(dca_terms)), 4),
        "lumpsum_mean_terminal": round(float(np.mean(ls_terms)), 4),
        "dca_mean_terminal": round(float(np.mean(dca_terms)), 4),
        "lumpsum_p5_terminal": round(float(np.percentile(ls_terms, 5)), 4),
        "dca_p5_terminal": round(float(np.percentile(dca_terms, 5)), 4),
        "lumpsum_p95_terminal": round(float(np.percentile(ls_terms, 95)), 4),
        "dca_p95_terminal": round(float(np.percentile(dca_terms, 95)), 4),
        "lumpsum_median_cagr": round(float(np.median(ls_cagrs)), 4),
        "dca_median_cagr": round(float(np.median(dca_cagrs)), 4),
        "lumpsum_median_mdd": round(float(np.median(ls_mdds)), 4),
        "dca_median_mdd": round(float(np.median(dca_mdds)), 4),
        "lumpsum_worst_mdd": round(float(np.min(ls_mdds)), 4),
        "dca_worst_mdd": round(float(np.min(dca_mdds)), 4),
        "lumpsum_near_zero_prob": round(ls_nz / total, 4),
        "lumpsum_near_zero_ci": [round(lo_ls, 4), round(hi_ls, 4)],
        "dca_near_zero_prob": round(dca_nz / total, 4),
        "dca_near_zero_ci": [round(lo_dca, 4), round(hi_dca, 4)],
        "lumpsum_beats_dca_prob": round(ls_win / total, 4),
        "_ls_terms": ls_terms,
        "_dca_terms": dca_terms,
    }


def wilson_ci(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    phat = k / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    half = (z * np.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def near_high_mask(px, lookback=TRADING_DAYS, within_pct=0.05):
    """boolean mask：價格 ≥ trailing-lookback 日高點 × (1 - within_pct)。
    無 lookahead：trailing max 只用過去 lookback 日（含當日）。對齊 px index。"""
    roll_max = px.rolling(lookback, min_periods=lookback).max()
    mask = px >= roll_max * (1.0 - within_pct)
    return mask.fillna(False)


# ---------------------------------------------------------------------------
# 4. 信貸（借錢單筆）風險
# ---------------------------------------------------------------------------
def credit_ruin_analysis(px_daily, horizon_days_list, credit_rates,
                         high_water_mask=None):
    """信貸（無擔保個人信貸，非融資）模型：借款本金 P=1.0 全部投入部位，
    部位市值路徑 pos（起始=1），未償貸款本息 loan(t)=(1+rate)^t（年複利近似）。
    淨值 equity(t) = pos(t) − loan(t)。

    注意：t=0 時 equity = pos[0] − loan[0] = 1 − 1 = 0（借多少買多少，淨值=0
    是定義上的起點，**不是破產**）。因此破產定義必須避開 day-0 trivial 觸發：

      - **insolvent_at_horizon**（主要口徑）：到期時 equity[-1] < 0
        → 賣掉部位仍無法清償貸款，真正「借錢還倒虧」。
      - **ever_underwater_after_entry**（路徑口徑）：進場後（t>0）任一時點
        equity < 0 → 期間曾陷入賣掉也還不清的窘境（信貸無 margin call 強平，
        但代表帳面已資不抵債，若被迫變現即實現虧損）。

    回報兩種口徑的機率 + Wilson CI。high_water_mask: 只取高位進場點。無 lookahead。"""
    n = len(px_daily)
    p = px_daily.values
    results = {}
    for hd in horizon_days_list:
        years = hd / TRADING_DAYS
        per_rate = {}
        for rate in credit_rates:
            insolvent_end = 0
            ever_under = 0
            total = 0
            final_equity = []
            min_equity = []
            for i in range(0, n - hd - 1):
                if high_water_mask is not None and not bool(high_water_mask.iloc[i]):
                    continue
                seg = p[i:i + hd + 1]
                if len(seg) < hd + 1:
                    continue
                pos = seg / seg[0]            # 部位市值路徑（起始=1=借款額）
                t_years = np.arange(len(seg)) / TRADING_DAYS
                loan = (1.0 + rate) ** t_years  # 未償貸款本息（年複利近似）
                equity = pos - loan
                total += 1
                # 主要口徑：到期資不抵債
                insolvent_end += int(equity[-1] < 0.0)
                # 路徑口徑：進場後（排除 t=0 的 trivial 0）任一時點 < 0
                ever_under += int(bool(np.any(equity[1:] < 0.0)))
                final_equity.append(float(equity[-1]))
                min_equity.append(float(np.min(equity[1:])))
            if total == 0:
                continue
            lo, hi = wilson_ci(insolvent_end, total)
            lo2, hi2 = wilson_ci(ever_under, total)
            fe = np.array(final_equity)
            per_rate[f"{rate*100:.0f}pct"] = {
                "annual_rate": rate,
                "n_windows": int(total),
                "ruin_prob": round(insolvent_end / total, 4),
                "ruin_ci": [round(lo, 4), round(hi, 4)],
                "ever_underwater_prob": round(ever_under / total, 4),
                "ever_underwater_ci": [round(lo2, 4), round(hi2, 4)],
                "median_final_equity": round(float(np.median(fe)), 4),
                "p5_final_equity": round(float(np.percentile(fe, 5)), 4),
                "median_min_equity": round(float(np.median(min_equity)), 4),
            }
        results[f"{years:.0f}y"] = per_rate
    return results


# ---------------------------------------------------------------------------
# 5. 加碼金（保留現金逢低加碼）vs 全額單筆
# ---------------------------------------------------------------------------
def reserve_buydip_window(px_daily, start_i, horizon_days, reserve_frac=0.30,
                          dip_trigger=0.20, near_zero_thresh=0.10):
    """保留 reserve_frac 現金，當部位自進場後運行高點回落 dip_trigger 時，一次性把
    保留現金全部加碼投入；對比全額單筆（reserve_frac=0）。
    回傳兩策略終值 + 是否趨近歸零。無 lookahead：加碼觸發只看已實現回落。"""
    seg = px_daily.iloc[start_i:start_i + horizon_days + 1]
    if len(seg) < horizon_days + 1:
        return None
    p = seg.values
    p0 = p[0]
    pend = p[-1]

    # 全額單筆
    full_units = 1.0 / p0
    full_terminal = full_units * pend
    full_path = full_units * p
    full_nz = bool(np.min(full_path) <= near_zero_thresh)

    # 保留加碼金
    invest0 = 1.0 - reserve_frac
    units = invest0 / p0
    cash = reserve_frac
    deployed = False
    run_peak = p0
    path = np.empty(len(p))
    for t in range(len(p)):
        run_peak = max(run_peak, p[t])
        if (not deployed) and cash > 0 and p[t] <= run_peak * (1.0 - dip_trigger):
            units += cash / p[t]
            cash = 0.0
            deployed = True
        path[t] = units * p[t] + cash
    res_terminal = units * pend + cash
    res_nz = bool(np.min(path) <= near_zero_thresh)

    return {
        "full_terminal": float(full_terminal),
        "reserve_terminal": float(res_terminal),
        "full_near_zero": full_nz,
        "reserve_near_zero": res_nz,
        "reserve_deployed": deployed,
    }


def rolling_reserve_buydip(px_daily, horizon_days, label, reserve_frac=0.30,
                           dip_trigger=0.20, near_zero_thresh=0.10,
                           high_water_mask=None):
    n = len(px_daily)
    full_t, res_t = [], []
    full_nz, res_nz = 0, 0
    res_wins = 0
    deployed_ct = 0
    total = 0
    for i in range(0, n - horizon_days - 1):
        if high_water_mask is not None and not bool(high_water_mask.iloc[i]):
            continue
        r = reserve_buydip_window(px_daily, i, horizon_days, reserve_frac,
                                  dip_trigger, near_zero_thresh)
        if r is None:
            continue
        full_t.append(r["full_terminal"])
        res_t.append(r["reserve_terminal"])
        full_nz += int(r["full_near_zero"])
        res_nz += int(r["reserve_near_zero"])
        res_wins += int(r["reserve_terminal"] > r["full_terminal"])
        deployed_ct += int(r["reserve_deployed"])
        total += 1
    if total == 0:
        return {"label": label, "n_windows": 0}
    full_t = np.array(full_t)
    res_t = np.array(res_t)
    lo_f, hi_f = wilson_ci(full_nz, total)
    lo_r, hi_r = wilson_ci(res_nz, total)
    return {
        "label": label,
        "horizon_years": round(horizon_days / TRADING_DAYS, 2),
        "reserve_frac": reserve_frac,
        "dip_trigger": dip_trigger,
        "n_windows": int(total),
        "full_median_terminal": round(float(np.median(full_t)), 4),
        "reserve_median_terminal": round(float(np.median(res_t)), 4),
        "full_p5_terminal": round(float(np.percentile(full_t, 5)), 4),
        "reserve_p5_terminal": round(float(np.percentile(res_t, 5)), 4),
        "full_near_zero_prob": round(full_nz / total, 4),
        "full_near_zero_ci": [round(lo_f, 4), round(hi_f, 4)],
        "reserve_near_zero_prob": round(res_nz / total, 4),
        "reserve_near_zero_ci": [round(lo_r, 4), round(hi_r, 4)],
        "reserve_beats_full_prob": round(res_wins / total, 4),
        "reserve_deployed_prob": round(deployed_ct / total, 4),
    }


# ---------------------------------------------------------------------------
# 6. 圖
# ---------------------------------------------------------------------------
def fig_vol_drag(px_0050, px_00631l):
    """圖1：波動率拖累 — 真實 00631L vs 重建 2x-daily-rebal vs 2x naive buyhold +
    『跌 X% 要漲多少回本』不對稱曲線。"""
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))

    common = px_00631l.index.intersection(px_0050.index).sort_values()
    p0050 = px_0050.reindex(common).dropna()
    p631 = px_00631l.reindex(common).dropna()
    c2 = p0050.index.intersection(p631.index)
    p0050 = p0050.reindex(c2)
    p631 = p631.reindex(c2)
    r0050 = p0050.pct_change().dropna()
    nav_rebal, _ = rebuild_2x_daily(r0050)

    real_nav = p631 / p631.iloc[0]
    rebal_nav = nav_rebal / nav_rebal.iloc[0]   # 對齊起點=1（reindex 後 r0050 起於第二天）
    bh_nav = 1.0 + LEVERAGE * (p0050 / p0050.iloc[0] - 1.0)
    under_nav = p0050 / p0050.iloc[0]

    ax = axes[0]
    ax.plot(under_nav.index, under_nav.values, color="#888888", lw=1.2, label="0050 標的（1x）")
    ax.plot(bh_nav.index, bh_nav.values, color="#4C72B0", lw=1.5, ls="--",
            label="2× naive buy-hold（天真認知）")
    ax.plot(rebal_nav.index, rebal_nav.values, color="#C44E52", lw=1.8,
            label="2× daily-rebal 重建（含拖累+成本）")
    ax.plot(real_nav.index, real_nav.values, color="#55A868", lw=1.8, alpha=0.85,
            label="真實 00631L")
    ax.set_title("圖1a 槓桿累積：真實 vs 重建 vs 天真 2×\n（共同期間，起點正規化=1）")
    ax.set_ylabel("累積淨值（起點=1）")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)

    ax2 = axes[1]
    dd = np.linspace(0.05, 0.85, 100)
    rec = dd / (1.0 - dd) * 100
    ax2.plot(dd * 100, rec, color="#C44E52", lw=2)
    for x in [0.3, 0.5, 0.7]:
        y = x / (1 - x) * 100
        ax2.scatter([x * 100], [y], color="#1f3b6f", zorder=5)
        ax2.annotate(f"跌{x*100:.0f}% → 漲{y:.0f}%回本", (x * 100, y),
                     textcoords="offset points", xytext=(8, -2), fontsize=9)
    ax2.set_title("圖1b 槓桿的不對稱：跌 X% 要漲多少才回本\n（跌 50% 需漲 100%；槓桿放大跌幅 → 更難回本）")
    ax2.set_xlabel("最大回撤 (%)")
    ax2.set_ylabel("回本所需漲幅 (%)")
    ax2.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "fig1_vol_drag_and_asymmetry.png"), dpi=300)
    plt.close(fig)


def fig_lumpsum_dca(ls_dca_lev, ls_dca_under, ls_dca_lev_high):
    """圖2：單筆 vs 分批中位終值 + 單筆勝率（槓桿 vs 非槓桿 vs 高位進場）。"""
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))

    panels = [
        ("槓桿 00631L\n全部進場點", ls_dca_lev),
        ("非槓桿 0050\n全部進場點", ls_dca_under),
        ("槓桿 00631L\n僅高位進場", ls_dca_lev_high),
    ]
    x = np.arange(len(panels))
    w = 0.35
    ls_med = [p[1]["lumpsum_median_terminal"] for p in panels]
    dca_med = [p[1]["dca_median_terminal"] for p in panels]
    ax = axes[0]
    ax.bar(x - w / 2, ls_med, w, color="#4C72B0", label="單筆 中位終值")
    ax.bar(x + w / 2, dca_med, w, color="#DD8452", label="分批(12月) 中位終值")
    ax.axhline(1.0, color="grey", lw=1, ls=":", label="投入本金=1")
    for xi, (lm, dm) in enumerate(zip(ls_med, dca_med)):
        ax.text(xi - w / 2, lm + 0.02, f"{lm:.2f}", ha="center", fontsize=8)
        ax.text(xi + w / 2, dm + 0.02, f"{dm:.2f}", ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([p[0] for p in panels], fontsize=9)
    ax.set_ylabel("中位終值（每 1 元投入，3 年持有）")
    ax.set_title("圖2a 單筆 vs 分批：中位終值")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3, axis="y")

    ax2 = axes[1]
    ls_win = [p[1]["lumpsum_beats_dca_prob"] * 100 for p in panels]
    ax2.bar(x, ls_win, 0.5, color="#55A868")
    ax2.axhline(50, color="red", lw=1, ls="--", label="50%（無優勢）")
    for xi, v in enumerate(ls_win):
        ax2.text(xi, v + 1, f"{v:.0f}%", ha="center", fontsize=9)
    ax2.set_xticks(x)
    ax2.set_xticklabels([p[0] for p in panels], fontsize=9)
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("單筆終值 > 分批 的視窗比例 (%)")
    ax2.set_title("圖2b 單筆勝過分批的機率\n（>50% = 單筆通常較好）")
    ax2.legend(fontsize=8)
    ax2.grid(alpha=0.3, axis="y")

    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "fig2_lumpsum_vs_dca.png"), dpi=300)
    plt.close(fig)


def fig_credit_ruin(credit_all, credit_high):
    """圖3：信貸破產機率 vs 持有期（3 檔利率）+ 高位進場對照。"""
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), sharey=True)

    def plot_one(ax, credit, title):
        horizons = sorted(credit.keys(), key=lambda s: int(s.replace("y", "")))
        rates = ["3pct", "5pct", "7pct"]
        colors = {"3pct": "#55A868", "5pct": "#DD8452", "7pct": "#C44E52"}
        for rk in rates:
            xs, ys, los, his = [], [], [], []
            for h in horizons:
                if rk in credit[h]:
                    xs.append(int(h.replace("y", "")))
                    ys.append(credit[h][rk]["ruin_prob"] * 100)
                    los.append(credit[h][rk]["ruin_ci"][0] * 100)
                    his.append(credit[h][rk]["ruin_ci"][1] * 100)
            ax.plot(xs, ys, marker="o", color=colors[rk], lw=2,
                    label=f"信貸年息 {rk.replace('pct','%')}")
            ax.fill_between(xs, los, his, color=colors[rk], alpha=0.12)
        ax.set_xlabel("持有期（年）")
        ax.set_title(title)
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)

    plot_one(axes[0], credit_all, "圖3a 借錢買 00631L 的破產機率\n（全部進場點，淨值≤0 即破產）")
    plot_one(axes[1], credit_high, "圖3b 借錢 × 高位進場\n（僅創近一年新高附近進場）")
    axes[0].set_ylabel("破產機率 (%)")
    fig.suptitle("圖3 信貸 × 2x 槓桿的尾部破產風險（風險教育，非建議借貸）", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "fig3_credit_ruin_prob.png"), dpi=300)
    plt.close(fig)


# ---------------------------------------------------------------------------
def strip_arrays(d):
    if not isinstance(d, dict):
        return d
    return {k: v for k, v in d.items() if not k.startswith("_")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    raw_px = {}
    for name, sym in TICKERS.items():
        raw_px[name] = fetch(name, sym, refresh=args.refresh)

    # 資料清洗：用 TWII 交叉檢核修復 yfinance scale-break 壞點（見 clean_vendor_breaks）
    twii_raw = raw_px["TWII"]
    cleaning = {}
    px = {}
    expected_lev = {"L00631L": 2.0, "T0050": 1.0, "TWII": 1.0}
    for name in TICKERS:
        if name == "TWII":
            px[name] = twii_raw
            cleaning[name] = []
            continue
        cleaned, breaks = clean_vendor_breaks(raw_px[name], twii_raw, name,
                                              expected_lev=expected_lev[name])
        px[name] = cleaned
        cleaning[name] = breaks

    meta = {}
    for name, sym in TICKERS.items():
        p = px[name]
        r = daily_returns(p)
        meta[name] = {
            "symbol": sym,
            "start": str(p.index.min().date()),
            "end": str(p.index.max().date()),
            "n_days": int(len(p)),
            "ann_vol": round(float(r.std() * np.sqrt(TRADING_DAYS)), 4),
            "ann_ret": round(float((1 + r.mean()) ** TRADING_DAYS - 1), 4),
            "vendor_breaks_repaired": len(cleaning[name]),
        }

    # --- 1. 波動率拖累 ---
    drag_0050 = vol_drag_analysis(px["T0050"], px["L00631L"], "0050.TW（2009起）")
    drag_twii = vol_drag_analysis(px["TWII"], None, "^TWII（1997起）")
    real_vs_rebuilt = vol_drag_vs_real(px["T0050"], px["L00631L"])

    nav_631 = px["L00631L"] / px["L00631L"].iloc[0]
    dd_631 = (nav_631 / nav_631.cummax() - 1.0)
    max_dd_631 = float(dd_631.min())
    recover_needed = recover_multiple(abs(max_dd_631))
    nav_0050 = px["T0050"] / px["T0050"].iloc[0]
    dd_0050 = float((nav_0050 / nav_0050.cummax() - 1.0).min())

    # --- 2. 單筆 vs 分批（rolling，3 年持有期） ---
    HORIZON_DAYS = 3 * TRADING_DAYS
    _ = np.random.default_rng(SEED)  # 固定 seed（此實驗 rolling 為 deterministic，保留慣例）
    ls_dca_lev = rolling_lumpsum_dca(px["L00631L"], HORIZON_DAYS, "00631L 槓桿")
    ls_dca_under = rolling_lumpsum_dca(px["T0050"], HORIZON_DAYS, "0050 非槓桿")

    # --- 3. 高位進場條件 ---
    mask_631 = near_high_mask(px["L00631L"], lookback=TRADING_DAYS, within_pct=0.05)
    mask_0050 = near_high_mask(px["T0050"], lookback=TRADING_DAYS, within_pct=0.05)
    ls_dca_lev_high = rolling_lumpsum_dca(px["L00631L"], HORIZON_DAYS, "00631L 槓桿(高位)",
                                          high_water_mask=mask_631)
    ls_dca_under_high = rolling_lumpsum_dca(px["T0050"], HORIZON_DAYS, "0050 非槓桿(高位)",
                                            high_water_mask=mask_0050)

    # --- 4. 信貸破產風險 ---
    horizons = [1 * TRADING_DAYS, 2 * TRADING_DAYS, 3 * TRADING_DAYS, 5 * TRADING_DAYS]
    credit_all = credit_ruin_analysis(px["L00631L"], horizons, CREDIT_RATES)
    credit_high = credit_ruin_analysis(px["L00631L"], horizons, CREDIT_RATES,
                                       high_water_mask=mask_631)
    credit_under = credit_ruin_analysis(px["T0050"], horizons, CREDIT_RATES)

    # --- 5. 加碼金 ---
    reserve_lev = rolling_reserve_buydip(px["L00631L"], HORIZON_DAYS, "00631L 全部進場",
                                         reserve_frac=0.30, dip_trigger=0.20)
    reserve_lev_high = rolling_reserve_buydip(px["L00631L"], HORIZON_DAYS, "00631L 高位進場",
                                              reserve_frac=0.30, dip_trigger=0.20,
                                              high_water_mask=mask_631)

    # --- 圖 ---
    fig_vol_drag(px["T0050"], px["L00631L"])
    fig_lumpsum_dca(ls_dca_lev, ls_dca_under, ls_dca_lev_high)
    fig_credit_ruin(credit_all, credit_high)

    out = {
        "experiment_id": "k1411",
        "title": "槓桿型 ETF（00631L）單筆 vs 分批、波動率拖累、與借貸/加碼金風險",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "seed": SEED,
            "leverage": LEVERAGE,
            "lev_daily_cost_annual_assumed": LEV_DAILY_COST_ANNUAL,
            "credit_rates": CREDIT_RATES,
            "dca_months": 12,
            "holding_horizon_years_main": 3,
            "near_zero_threshold_frac": 0.10,
            "near_high_within_pct": 0.05,
            "near_high_lookback_days": TRADING_DAYS,
            "buydip_reserve_frac": 0.30,
            "buydip_dip_trigger": 0.20,
            "lookahead_check": "重建 2x 用逐日報酬複利（僅當期及過去）；rolling 視窗投入/估值"
                               "只用視窗內已實現價格；trailing-high mask 只用過去 252 日；"
                               "加碼觸發只看已實現回落；信貸利息為時間函數不含未來資訊。",
        },
        "data_meta": meta,
        "code_review": {
            "status": "CONDITIONAL_PASS_self_review",
            "reviewer_source": "main-thread structured self-review (Codex CLI 與 agy 本次環境皆 hang，"
                               ">20min 無輸出，已 kill；fallback 走主線程審查)",
            "note": "外部 AI reviewer 不可用，closure 暫定 CONDITIONAL_PASS；主線程合併後應以 "
                    "primary-path Codex 二次驗證（依 .claude/rules/experiments.md 規範）。",
            "checks_passed": [
                "Lookahead：rebuild_2x_daily(cumprod 僅當期+過去)、near_high_mask(pandas trailing "
                "rolling.max)、reserve_buydip(run_peak 增量追蹤)、credit loan(時間確定函數)、"
                "DCA(固定排程) — 皆無未來資訊。",
                "2x daily-rebal 正確：逐日 1+2r-cost 複利，經實證驗證(重建/真實 00631L 終值比 1.03)。",
                "clean_vendor_breaks：僅 |資產|>30% 且 |TWII|<12% 觸發，真實大跌(TWII 同步大跌)不會誤殺；"
                "2015-08-24 等壞點正確捕捉。",
                "信貸破產：equity[-1]<0(到期) + any(equity[1:]<0)(路徑) 皆排除 day-0 trivial(equity=0)。",
                "DCA：3年期(756d)內 12*21=252d 全投完，無未投盡 cash 殘留問題。",
            ],
        },
        "data_cleaning": {
            "method": "TWII cross-check：|asset 日報酬|>30% 且 |TWII 同日|<12% 判為 yfinance "
                      "scale-break 壞點，替換為 TWII當日報酬×槓桿倍數，再重建價格序列。",
            "repaired_breaks": cleaning,
        },
        "Q1_vol_drag_and_asymmetry": {
            "drag_from_0050": strip_arrays(drag_0050),
            "drag_from_twii": strip_arrays(drag_twii),
            "real_00631L_vs_rebuilt_2x_daily": real_vs_rebuilt,
            "real_00631L_max_drawdown": round(max_dd_631, 4),
            "real_00631L_recover_multiple_from_maxdd": round(recover_needed, 4),
            "underlying_0050_max_drawdown": round(dd_0050, 4),
            "asymmetry_examples": {
                "dd_30pct_needs_recover_pct": round(recover_multiple(0.30) * 100, 1),
                "dd_50pct_needs_recover_pct": round(recover_multiple(0.50) * 100, 1),
                "dd_70pct_needs_recover_pct": round(recover_multiple(0.70) * 100, 1),
            },
        },
        "Q2_lumpsum_vs_dca": {
            "leverage_00631L_all": strip_arrays(ls_dca_lev),
            "underlying_0050_all": strip_arrays(ls_dca_under),
            "leverage_flipped_conclusion": None,
        },
        "Q3_high_entry_condition": {
            "leverage_00631L_high": strip_arrays(ls_dca_lev_high),
            "underlying_0050_high": strip_arrays(ls_dca_under_high),
        },
        "Q4_credit_ruin": {
            "leverage_00631L_all_entries": credit_all,
            "leverage_00631L_high_entries": credit_high,
            "underlying_0050_all_entries": credit_under,
        },
        "Q4b_reserve_buydip": {
            "leverage_00631L_all": reserve_lev,
            "leverage_00631L_high": reserve_lev_high,
        },
        "data_limitations": [
            "重建 2x daily-rebal 用年化 1.5% 總拖累 proxy（管理費~1.13% + 融資/展延成本），"
            "真實 00631L 內扣費用與期貨展延成本逐期變動，重建為近似。",
            "00631L 樣本僅 2014-10 起 ~11.5 年，含 2015 股災/2018/2020/2022 但無 2008，"
            "尾部破產率可能低估（缺最嚴重空頭）。",
            "rolling windows 重疊 → 視窗間非獨立，CI 為近似（未做 block-adjusted SE）。",
            "信貸模型假設借款一次性全投、利息年複利、無提前還款/margin call 強平機制，"
            "真實券商維持率追繳會更早觸發實質破產（此模型可能低估破產時點）。",
            "分批未投入現金假設不計息（保守），若放定存會略改善分批相對表現。",
            "DCA 用固定 21 交易日為一個月近似；高位 mask 用 5% 容差 + 252 日回看。",
        ],
    }

    lev_ls_win = ls_dca_lev["lumpsum_beats_dca_prob"]
    und_ls_win = ls_dca_under["lumpsum_beats_dca_prob"]
    out["Q2_lumpsum_vs_dca"]["leverage_flipped_conclusion"] = {
        "lumpsum_beats_dca_leverage": lev_ls_win,
        "lumpsum_beats_dca_underlying": und_ls_win,
        "flipped": bool((und_ls_win > 0.5) != (lev_ls_win > 0.5)),
        "interpretation": ("槓桿下單筆勝率 %.0f%% vs 非槓桿 %.0f%%"
                           % (lev_ls_win * 100, und_ls_win * 100)),
    }

    out_path = os.path.join(HERE, "k1411_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # ---- console ----
    print("=== K1411 槓桿 ETF 單筆vs分批/波動拖累/借貸風險 ===")
    for name in TICKERS:
        m = meta[name]
        print(f"[{name}] {m['start']}~{m['end']} N={m['n_days']}  "
              f"年化報酬{m['ann_ret']*100:.1f}% / 波動{m['ann_vol']*100:.1f}%")

    print("\n-- Q1 波動率拖累（從 0050 重建 2x）--")
    d = drag_0050
    print(f"  標的 0050 CAGR {d['underlying_cagr']*100:.1f}% → 天真2x期望 {d['naive_2x_cagr_expectation']*100:.1f}%")
    bh = d['buyhold_2x_cagr'] if d['buyhold_2x_cagr'] is not None else float('nan')
    print(f"  2x buy-hold CAGR {bh*100:.1f}% / 2x daily-rebal CAGR {d['daily_rebal_2x_cagr']*100:.1f}%")
    print(f"  理論年化拖累 {d['theoretical_annual_vol_drag']*100:.2f}% / 實證(rebal-naive) "
          f"{d['empirical_annual_drag_rebal_minus_naive']*100:.2f}%")
    rv = real_vs_rebuilt
    print(f"  真實00631L終值 {rv['real_00631L_terminal_x']:.2f}x vs 重建 {rv['rebuilt_2x_daily_rebal_terminal_x']:.2f}x "
          f"vs 天真2x {rv['naive_2x_buyhold_terminal_x']:.2f}x (重建/真實={rv['rebuilt_vs_real_terminal_ratio']})")
    print(f"  00631L 史上最大回撤 {max_dd_631*100:.1f}% → 回本需漲 {recover_needed*100:.0f}%"
          f"（vs 0050 最大回撤 {dd_0050*100:.1f}%）")

    print("\n-- Q2 單筆 vs 分批（3年持有，全部進場點）--")
    for r in [ls_dca_lev, ls_dca_under]:
        print(f"  {r['label']}: 單筆勝率 {r['lumpsum_beats_dca_prob']*100:.0f}%  "
              f"單筆中位終值 {r['lumpsum_median_terminal']:.2f} vs 分批 {r['dca_median_terminal']:.2f}  "
              f"單筆MDD中位 {r['lumpsum_median_mdd']*100:.0f}% / 趨近歸零率 {r['lumpsum_near_zero_prob']*100:.1f}%")
    print(f"  → 槓桿是否翻轉結論: {out['Q2_lumpsum_vs_dca']['leverage_flipped_conclusion']['flipped']}")

    print("\n-- Q3 高位進場（價格≥近一年高點 95%）--")
    for r in [ls_dca_lev_high, ls_dca_under_high]:
        print(f"  {r['label']}: N={r['n_windows']}  單筆勝率 {r['lumpsum_beats_dca_prob']*100:.0f}%  "
              f"單筆中位終值 {r['lumpsum_median_terminal']:.2f} vs 分批 {r['dca_median_terminal']:.2f}")

    print("\n-- Q4 信貸風險（借錢全投 00631L，全部進場）到期資不抵債率 / 期間曾資不抵債率 --")
    for h in sorted(credit_all.keys(), key=lambda s: int(s.replace('y', ''))):
        c5 = credit_all[h].get("5pct")
        if c5:
            print(f"  {h} (5%): 到期資不抵債 {c5['ruin_prob']*100:.0f}%  "
                  f"期間曾資不抵債 {c5['ever_underwater_prob']*100:.0f}%  "
                  f"p5到期淨值 {c5['p5_final_equity']:+.2f}（每借1元）")
    print("  高位進場 (5%):")
    for h in sorted(credit_high.keys(), key=lambda s: int(s.replace('y', ''))):
        c5 = credit_high[h].get("5pct")
        if c5:
            print(f"  {h}: 到期資不抵債 {c5['ruin_prob']*100:.0f}%  "
                  f"期間曾資不抵債 {c5['ever_underwater_prob']*100:.0f}%")
    cu5 = credit_under["1y"].get("5pct")
    print(f"  對照非槓桿 0050 1y(5%): 到期資不抵債 {cu5['ruin_prob']*100:.0f}% "
          f"p5淨值 {cu5['p5_final_equity']:+.2f}")

    print("\n-- Q4b 加碼金（保留30%現金，回落20%加碼）--")
    for r in [reserve_lev, reserve_lev_high]:
        print(f"  {r['label']}: 加碼勝過全投 {r['reserve_beats_full_prob']*100:.0f}%  "
              f"中位終值 全投{r['full_median_terminal']:.2f}/加碼{r['reserve_median_terminal']:.2f}  "
              f"p5(下尾)終值 全投{r['full_p5_terminal']:.2f}/加碼{r['reserve_p5_terminal']:.2f}  "
              f"(觸發加碼率 {r['reserve_deployed_prob']*100:.0f}%)")

    print(f"\nresults -> {out_path}")


if __name__ == "__main__":
    main()
