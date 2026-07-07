#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K1656 — Net-of-cost smoothed volatility targeting + no-trade band
=================================================================

研究問題
--------
波動率目標 (VT) 策略日度再平衡造成高換手率 (~150-300%/yr)。扣掉交易成本後，
淨 Sharpe 是否被侵蝕？加入 (a) 21 日訊號平滑、(b) no-trade band (再平衡帶寬)
能否在**淨** Sharpe 上勝過標準日度 VT？在 SPY (美股) 與 0050.TW (台股) 兩市場
的答案是否一致？

差異化 (vs 內部 prior art)
--------------------------
- K48 (Rebalancing boundary) 測的是**月頻** 12/VIX 策略 (turnover 本就低)，結論
  net Sharpe 改善不顯著。本實驗打的是**日頻 VT** (turnover 200%+ 的真痛點)，band
  的邊際效益理論上應更大 — 這是 K48 沒覆蓋的空間。
- K499/K220 談 rebalance frequency (calendar)，本實驗把 no-trade band 與 calendar
  再平衡做 **turnover-matched** 對照，回答「band 是否為更好的降 turnover 手段」。
- 雙市場 (SPY + 0050.TW)，台股用**第一原理**成本 (證交稅只課賣出，追蹤 Δw 符號做
  非對稱成本)，避開 K604「TW 13x」被 K625 更正的高估陷阱。
- 毛 (gross) vs 淨 (net) Sharpe **並列表**，band 各檔一列 — explicit 量測。

方法論防錯 (CLAUDE.md / .claude/rules/experiments.md)
----------------------------------------------------
- Lookahead: 波動率訊號 shift(1) — vol_signal[t] 只用 returns[t-20..t-1]；平滑後仍
  只用 ≤ t-1 資訊。再平衡決策 (w_target[t], w_drift[t]) 皆為 t 日開盤前已知資訊，
  return r[t] 之後才發生，決策不使用 r[t]。
- yfinance 一律 auto_adjust=False，用 'Adj Close' 做總報酬 (K811 教訓)。
- 所有隨機程序固定 seed=1656 (bootstrap)。
- baseline 與所有變體共用同一 vol 估計與 w_target，只差再平衡規則 (公平比較)。
- Sharpe 遠高於 baseline 先懷疑 bug。

文獻
----
- Bai et al. (2025) "Target volatility strategies: optimal rebalancing boundary for
  transaction cost minimization", Financial Markets and Portfolio Management (FMPM),
  DOI 10.1007/s11408-025-00486-5.
- Leland, H. (2000) "Optimal Portfolio Management with Transaction Costs and Capital
  Gains Taxes". No-trade region；最優為 rebalance 到帶寬邊界 (非回 target)，turnover 減 ~50%。
- Fleming, Kirby, Ostdiek (2003) "The Economic Value of Volatility Timing Using Realized
  Volatility", JFE.
- Moreira & Muir (2017) "Volatility-Managed Portfolios", Journal of Finance.
"""

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 1656
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
DATA.mkdir(parents=True, exist_ok=True)

TRADING_DAYS = 252

# ----------------------------- 參數 -----------------------------
VOL_WINDOW = 20          # 日 — realized vol 估計窗 (responsive → 高 turnover，符合痛點)
SMOOTH_WINDOW = 21       # 日 — 訊號平滑
TARGET_VOL = 0.15        # 年化目標波動率
LEV_CAP = 2.0            # 槓桿上限
BANDS = [0.05, 0.10, 0.15, 0.20]   # no-trade band 掃描
START = "2011-06-01"
END = "2026-07-08"

# 成本假設 (以 per unit one-way turnover |Δw| 計)
# 美股 SPY: 5bp round-trip → 2.5bp one-way，買賣對稱
US_COST_BUY = 0.00025
US_COST_SELL = 0.00025
US_COST_ROBUST = 0.0005  # robustness: 10bp round-trip → 5bp one-way
# 台股 0050 (股票型 ETF): 手續費 0.1425% × 折扣 (單邊) + 證交稅 0.1% (僅賣出)
# 證交稅：股票型 ETF 現行 0.1% (千分之一，僅賣出；台股個股為 0.3%)。
# task brief 原寫 0.15% 有誤 — code-reviewer 質疑後查證 TWSE 現行 0.1%，改正 (成本=數據)。
TW_FEE = 0.001425
TW_DISCOUNT = 0.6        # 6 折 (常見電子下單) — base
TW_TAX_ETF = 0.001       # 證交稅 (股票型 ETF 0.1%，僅賣出課徵)
TW_COST_BUY = TW_FEE * TW_DISCOUNT
TW_COST_SELL = TW_FEE * TW_DISCOUNT + TW_TAX_ETF


# ----------------------------- 資料 -----------------------------
MAX_ABS_DAILY_RET = 0.30   # 資料品質 guard：SPY/TAIEX 歷史單日 <11%，>30% 必為 bad tick


def load_prices(ticker: str) -> pd.Series:
    """下載並快取 Adj Close (auto_adjust=False → 用 'Adj Close' 欄)。

    資料品質 guard：任何 |日報酬| > MAX_ABS_DAILY_RET 直接 raise。
    (K1656 診斷：yfinance 的 `0050.TW` Adj Close 在 2014-01-02 有 -75% 假象斷裂
     且 repair=True 修不好 → 棄用 0050.TW，改用 `^TWII` TAIEX 指數當台股 proxy。)"""
    cache = DATA / f"{ticker.replace('.', '_').replace('^','idx_')}_adjclose.csv"
    if cache.exists():
        s = pd.read_csv(cache, index_col=0, parse_dates=True).iloc[:, 0]
        s.name = ticker
        s = s.dropna()
    else:
        import yfinance as yf
        df = yf.download(ticker, start=START, end=END, auto_adjust=False, progress=False)
        if df.empty:
            raise RuntimeError(f"no data for {ticker}")
        col = df["Adj Close"]
        if isinstance(col, pd.DataFrame):  # MultiIndex columns
            col = col.iloc[:, 0]
        col = col.dropna()
        col.name = ticker
        col.to_csv(cache)
        s = col
    # guard
    r = s.pct_change().dropna()
    bad = r[r.abs() > MAX_ABS_DAILY_RET]
    if len(bad):
        raise RuntimeError(f"{ticker} bad-tick data quality fail: "
                           f"{[(str(d.date()), round(float(v),4)) for d, v in bad.items()]}")
    return s


# ------------------------- 目標權重 (無 lookahead) -------------------------
def target_weight_raw(rets: pd.Series) -> pd.Series:
    """w_target[t] = clip(target_vol / annualized_vol_hat[t], 0, cap)。
    vol_hat[t] 用 returns[t-VOL_WINDOW..t-1] (shift(1)) → 決策日 t 只用 ≤ t-1 資訊。"""
    vol_daily = rets.rolling(VOL_WINDOW).std().shift(1)   # <-- 明確 shift(1)
    vol_ann = vol_daily * np.sqrt(TRADING_DAYS)
    w = (TARGET_VOL / vol_ann).clip(lower=0.0, upper=LEV_CAP)
    return w


def target_weight_smoothed(w_raw: pd.Series) -> pd.Series:
    """21 日移動平均平滑。w_raw[t] 已只用 ≤ t-1 資訊，MA 之後仍 ≤ t-1。"""
    return w_raw.rolling(SMOOTH_WINDOW).mean()


# ------------------------- 成本函數 (非對稱) -------------------------
def cost_of_trade(dw: float, cost_buy: float, cost_sell: float) -> float:
    """dw = w_new - w_drift。>0 買入 (課 buy 成本)，<0 賣出 (課 sell 成本含稅)。"""
    if dw > 0:
        return dw * cost_buy
    else:
        return -dw * cost_sell


# ------------------------- 回測核心 -------------------------
def backtest(rets: pd.Series, w_target: pd.Series, rule: str,
             band: float = 0.0, cost_buy: float = 0.0, cost_sell: float = 0.0,
             rebal_to_edge: bool = False):
    """
    rule: 'daily' | 'band' | 'weekly' | 'monthly'
    回傳 dict: gross_ret, net_ret (pd.Series), turnover(年化), n_rebal, metrics。

    時序 (無 lookahead):
      w_held[t] = 決策於 t 日開盤 (用 w_target[t] = f(vol≤t-1) 與 w_drift[t] = f(r[t-1]))
      day t 賺 w_held[t]*r[t]；成本在 t 日開盤扣。net_ret[t] = w_held[t]*r[t] - cost[t]
    """
    df = pd.DataFrame({"r": rets, "wt": w_target}).dropna()
    idx = df.index
    r = df["r"].values
    wt = df["wt"].values
    n = len(df)

    # 月/週再平衡日 (calendar)
    if rule in ("weekly", "monthly"):
        if rule == "weekly":
            # 每週第一個交易日再平衡
            wk = idx.to_period("W")
            first_of_week = ~pd.Series(wk, index=idx).duplicated().values
            rebal_flag = first_of_week
        else:
            mo = idx.to_period("M")
            first_of_month = ~pd.Series(mo, index=idx).duplicated().values
            rebal_flag = first_of_month
    else:
        rebal_flag = np.ones(n, dtype=bool)

    w_held = np.zeros(n)
    gross = np.zeros(n)
    cost = np.zeros(n)
    turn = np.zeros(n)

    for t in range(n):
        if t == 0:
            w_drift = 0.0  # 從現金起始
        else:
            wp = w_held[t - 1]
            rp = r[t - 1]
            denom = 1.0 + wp * rp
            w_drift = wp * (1.0 + rp) / denom if denom != 0 else wp

        target = wt[t]

        # 決策
        if rule == "daily":
            new_w = target
        elif rule == "band":
            if abs(target - w_drift) > band:
                if rebal_to_edge:
                    # rebalance 到帶寬邊界 (Leland 最優)：只移到 target ± band 的近邊
                    if target > w_drift:
                        new_w = target - band
                    else:
                        new_w = target + band
                else:
                    new_w = target      # rebalance 回 target (task spec)
            else:
                new_w = w_drift          # no trade
        elif rule in ("weekly", "monthly"):
            new_w = target if rebal_flag[t] else w_drift
        else:
            raise ValueError(rule)

        dw = new_w - w_drift
        turn[t] = abs(dw)
        cost[t] = cost_of_trade(dw, cost_buy, cost_sell)
        w_held[t] = new_w
        gross[t] = new_w * r[t]

    gross_ret = pd.Series(gross, index=idx)
    net_ret = pd.Series(gross - cost, index=idx)
    years = n / TRADING_DAYS
    ann_turnover = turn.sum() / years           # 年化單邊換手率 (Σ|Δw| / 年)
    n_rebal = int((turn > 1e-9).sum())
    n_rebal_yr = n_rebal / years

    return {
        "gross_ret": gross_ret,
        "net_ret": net_ret,
        "ann_turnover": float(ann_turnover),
        "n_rebal_per_yr": float(n_rebal_yr),
        "metrics_gross": perf_metrics(gross_ret),
        "metrics_net": perf_metrics(net_ret),
    }


# ------------------------- 績效指標 -------------------------
def perf_metrics(ret: pd.Series) -> dict:
    r = ret.dropna().values
    mu = r.mean() * TRADING_DAYS
    sd = r.std(ddof=1) * np.sqrt(TRADING_DAYS)
    sharpe = mu / sd if sd > 0 else 0.0
    equity = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(equity)
    dd = equity / peak - 1.0
    mdd = dd.min()
    cagr = equity[-1] ** (TRADING_DAYS / len(r)) - 1.0 if len(r) > 0 else 0.0
    return {
        "ann_return": float(mu),
        "ann_vol": float(sd),
        "sharpe": float(sharpe),
        "cagr": float(cagr),
        "mdd": float(mdd),
    }


def sharpe_of(r: np.ndarray) -> float:
    sd = r.std(ddof=1)
    return (r.mean() / sd) * np.sqrt(TRADING_DAYS) if sd > 0 else 0.0


# ------------------------- 統計檢定: 淨 Sharpe 差 (block bootstrap) -------------------------
def bootstrap_sharpe_diff(net_a: pd.Series, net_b: pd.Series,
                          B: int = 5000, block: int = 10, seed: int = SEED):
    """H0: Sharpe(A) - Sharpe(B) = 0。stationary block bootstrap (Politis-Romano)
    on paired daily net returns。回傳 point diff, 95% CI, two-sided p。

    解讀順序：**p_value 為主要推論依據**（centered bootstrap 假設檢定）；ci95 為
    percentile 描述性區間，在偏態分佈邊界可能與 p 值不一致 (percentile-CI 已知
    anti-conservative)，不可單以 CI 排除 0 判定顯著。"""
    df = pd.DataFrame({"a": net_a, "b": net_b}).dropna()
    a = df["a"].values
    b = df["b"].values
    n = len(a)
    point = sharpe_of(a) - sharpe_of(b)
    rng = np.random.default_rng(seed)
    p = 1.0 / block
    diffs = np.empty(B)
    for i in range(B):
        idx = np.empty(n, dtype=int)
        pos = 0
        cur = rng.integers(0, n)
        while pos < n:
            idx[pos] = cur
            pos += 1
            if rng.random() < p:
                cur = rng.integers(0, n)
            else:
                cur = (cur + 1) % n
        diffs[i] = sharpe_of(a[idx]) - sharpe_of(b[idx])
    ci = np.percentile(diffs, [2.5, 97.5])
    # two-sided p: 以 bootstrap 分佈中心化到 0 後，|diff*| ≥ |point| 的比例
    centered = diffs - diffs.mean()
    pval = float(np.mean(np.abs(centered) >= abs(point)))
    return {
        "sharpe_diff": float(point),
        "ci95_low": float(ci[0]),
        "ci95_high": float(ci[1]),
        "p_value": pval,
        "B": B,
        "block": block,
    }


# ------------------------- 主流程 (單一市場) -------------------------
def run_market(ticker: str, cost_buy: float, cost_sell: float, cost_label: str,
               display: str = None):
    display = display or ticker
    px = load_prices(ticker)
    rets = px.pct_change().dropna()
    rets.name = "r"

    w_raw = target_weight_raw(rets)
    w_smooth = target_weight_smoothed(w_raw)

    # 共同有效樣本 (平滑需最長 warmup)
    valid = w_smooth.dropna().index
    rets_v = rets.loc[valid]
    w_raw_v = w_raw.loc[valid]
    w_smooth_v = w_smooth.loc[valid]

    out = {
        "ticker": ticker,
        "display": display,
        "cost_label": cost_label,
        "cost_buy": cost_buy,
        "cost_sell": cost_sell,
        "sample_start": str(valid[0].date()),
        "sample_end": str(valid[-1].date()),
        "n_obs": int(len(valid)),
        "target_vol": TARGET_VOL,
        "vol_window": VOL_WINDOW,
        "smooth_window": SMOOTH_WINDOW,
        "lev_cap": LEV_CAP,
        "variants": {},
        "tests": {},
    }

    # --- baseline: 標準日度 VT ---
    base = backtest(rets_v, w_raw_v, "daily", cost_buy=cost_buy, cost_sell=cost_sell)
    out["variants"]["baseline_daily"] = summarize(base)

    # --- band sweep (rebalance-to-target) ---
    for b in BANDS:
        bt = backtest(rets_v, w_raw_v, "band", band=b, cost_buy=cost_buy, cost_sell=cost_sell)
        out["variants"][f"band_{int(b*100)}"] = summarize(bt)

    # --- band sweep (rebalance-to-edge, Leland 最優) sensitivity ---
    for b in BANDS:
        bt = backtest(rets_v, w_raw_v, "band", band=b, cost_buy=cost_buy,
                      cost_sell=cost_sell, rebal_to_edge=True)
        out["variants"][f"band_edge_{int(b*100)}"] = summarize(bt)

    # --- 21 日訊號平滑 (daily rebalance on smoothed target) ---
    sm = backtest(rets_v, w_smooth_v, "daily", cost_buy=cost_buy, cost_sell=cost_sell)
    out["variants"]["smooth21"] = summarize(sm)

    # --- 平滑 + band (組合) ---
    for b in BANDS:
        cb = backtest(rets_v, w_smooth_v, "band", band=b, cost_buy=cost_buy, cost_sell=cost_sell)
        out["variants"][f"smooth21_band_{int(b*100)}"] = summarize(cb)

    # --- calendar 再平衡 (turnover-matched 對照) ---
    wk = backtest(rets_v, w_raw_v, "weekly", cost_buy=cost_buy, cost_sell=cost_sell)
    out["variants"]["calendar_weekly"] = summarize(wk)
    mo = backtest(rets_v, w_raw_v, "monthly", cost_buy=cost_buy, cost_sell=cost_sell)
    out["variants"]["calendar_monthly"] = summarize(mo)

    # ---- 統計檢定: 各 band / smooth vs baseline (淨 Sharpe 差, bootstrap) ----
    for name in [f"band_{int(b*100)}" for b in BANDS] + ["smooth21"] + \
                [f"smooth21_band_{int(b*100)}" for b in BANDS] + \
                ["calendar_weekly", "calendar_monthly"]:
        variant_ret = _get_net(out, name, ticker, cost_buy, cost_sell, rets_v, w_raw_v, w_smooth_v)
        test = bootstrap_sharpe_diff(variant_ret, base["net_ret"])
        out["tests"][f"{name}_vs_baseline_netSharpe"] = test

    # ---- turnover-matched sensitivity: band vs 最接近 turnover 的 calendar ----
    out["turnover_matched"] = build_turnover_matched(out)

    # 保留 base net_ret 供跨檢定 (放進 raw for 圖表)
    out["_raw_net"] = {
        "baseline_daily": base["net_ret"],
    }
    return out, base, rets_v, w_raw_v, w_smooth_v


def _get_net(out, name, ticker, cost_buy, cost_sell, rets_v, w_raw_v, w_smooth_v):
    """重跑該 variant 拿 net_ret (避免存整條 series 進 out)。"""
    if name.startswith("smooth21_band_"):
        b = int(name.split("_")[-1]) / 100
        r = backtest(rets_v, w_smooth_v, "band", band=b, cost_buy=cost_buy, cost_sell=cost_sell)
    elif name == "smooth21":
        r = backtest(rets_v, w_smooth_v, "daily", cost_buy=cost_buy, cost_sell=cost_sell)
    elif name.startswith("band_"):
        b = int(name.split("_")[-1]) / 100
        r = backtest(rets_v, w_raw_v, "band", band=b, cost_buy=cost_buy, cost_sell=cost_sell)
    elif name == "calendar_weekly":
        r = backtest(rets_v, w_raw_v, "weekly", cost_buy=cost_buy, cost_sell=cost_sell)
    elif name == "calendar_monthly":
        r = backtest(rets_v, w_raw_v, "monthly", cost_buy=cost_buy, cost_sell=cost_sell)
    else:
        raise ValueError(name)
    return r["net_ret"]


def summarize(bt: dict) -> dict:
    return {
        "ann_turnover_pct": round(bt["ann_turnover"] * 100, 1),
        "n_rebal_per_yr": round(bt["n_rebal_per_yr"], 1),
        "gross_sharpe": round(bt["metrics_gross"]["sharpe"], 4),
        "net_sharpe": round(bt["metrics_net"]["sharpe"], 4),
        "gross_cagr": round(bt["metrics_gross"]["cagr"], 4),
        "net_cagr": round(bt["metrics_net"]["cagr"], 4),
        "net_ann_return": round(bt["metrics_net"]["ann_return"], 4),
        "net_ann_vol": round(bt["metrics_net"]["ann_vol"], 4),
        "net_mdd": round(bt["metrics_net"]["mdd"], 4),
        "cost_drag_sharpe": round(bt["metrics_gross"]["sharpe"] - bt["metrics_net"]["sharpe"], 4),
    }


def build_turnover_matched(out: dict) -> dict:
    """對每個 band，找 turnover 最接近的 calendar 策略，比 net Sharpe。"""
    cal = {k: out["variants"][k] for k in ("calendar_weekly", "calendar_monthly")}
    res = {}
    for b in BANDS:
        key = f"band_{int(b*100)}"
        bt = out["variants"][key]
        bturn = bt["ann_turnover_pct"]
        # 最接近 turnover 的 calendar
        best = min(cal.items(), key=lambda kv: abs(kv[1]["ann_turnover_pct"] - bturn))
        res[key] = {
            "band_turnover_pct": bturn,
            "band_net_sharpe": bt["net_sharpe"],
            "matched_calendar": best[0],
            "calendar_turnover_pct": best[1]["ann_turnover_pct"],
            "calendar_net_sharpe": best[1]["net_sharpe"],
            "band_minus_calendar_net_sharpe": round(bt["net_sharpe"] - best[1]["net_sharpe"], 4),
        }
    return res


# ------------------------- 圖表 -------------------------
def make_figures(results: dict):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    markets = ["SPY", "TAIEX"]

    # Fig 1: gross vs net Sharpe by band width (baseline + bands), per market
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, mk in zip(axes, markets):
        v = results[mk]["variants"]
        labels = ["baseline"] + [f"band {int(b*100)}%" for b in BANDS]
        keys = ["baseline_daily"] + [f"band_{int(b*100)}" for b in BANDS]
        gross = [v[k]["gross_sharpe"] for k in keys]
        net = [v[k]["net_sharpe"] for k in keys]
        x = np.arange(len(labels))
        ax.bar(x - 0.2, gross, 0.4, label="Gross", color="#8ea9c1")
        ax.bar(x + 0.2, net, 0.4, label="Net", color="#c1543a")
        ax.set_xticks(x); ax.set_xticklabels(labels, rotation=20, ha="right")
        ax.set_title(f"{mk}: Gross vs Net Sharpe by no-trade band")
        ax.set_ylabel("Sharpe"); ax.legend(); ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(HERE / "fig1_gross_vs_net_sharpe.png", dpi=130)
    plt.close(fig)

    # Fig 2: turnover vs band width curve, per market
    fig, ax = plt.subplots(figsize=(8, 5))
    for mk, color in zip(markets, ["#1f77b4", "#d62728"]):
        v = results[mk]["variants"]
        bx = [0] + [int(b*100) for b in BANDS]
        turn = [v["baseline_daily"]["ann_turnover_pct"]] + \
               [v[f"band_{int(b*100)}"]["ann_turnover_pct"] for b in BANDS]
        ax.plot(bx, turn, "o-", color=color, label=mk)
    ax.set_xlabel("no-trade band width (%)"); ax.set_ylabel("annualized turnover (%)")
    ax.set_title("Turnover reduction vs no-trade band width")
    ax.legend(); ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(HERE / "fig2_turnover_curve.png", dpi=130)
    plt.close(fig)

    # Fig 3: net Sharpe vs turnover scatter — band vs calendar (turnover-matched view)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, mk in zip(axes, markets):
        v = results[mk]["variants"]
        # band points
        bt_turn = [v[f"band_{int(b*100)}"]["ann_turnover_pct"] for b in BANDS]
        bt_net = [v[f"band_{int(b*100)}"]["net_sharpe"] for b in BANDS]
        ax.scatter(bt_turn, bt_net, color="#c1543a", s=70, label="no-trade band", zorder=3)
        for b, xx, yy in zip(BANDS, bt_turn, bt_net):
            ax.annotate(f"{int(b*100)}%", (xx, yy), textcoords="offset points", xytext=(5, 4), fontsize=8)
        # calendar points
        for ck, cl in [("calendar_weekly", "weekly"), ("calendar_monthly", "monthly")]:
            ax.scatter([v[ck]["ann_turnover_pct"]], [v[ck]["net_sharpe"]], marker="s", s=70,
                       label=f"calendar {cl}", zorder=3)
        # baseline
        ax.scatter([v["baseline_daily"]["ann_turnover_pct"]], [v["baseline_daily"]["net_sharpe"]],
                   marker="*", s=160, color="black", label="baseline daily", zorder=3)
        ax.set_xlabel("annualized turnover (%)"); ax.set_ylabel("net Sharpe")
        ax.set_title(f"{mk}: net Sharpe vs turnover (turnover-matched)")
        ax.legend(fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(HERE / "fig3_turnover_matched_scatter.png", dpi=130)
    plt.close(fig)


# ------------------------- 執行 -------------------------
def main():
    results = {}

    # SPY (base cost)
    spy_out, spy_base, spy_rets, spy_wraw, spy_wsm = run_market(
        "SPY", US_COST_BUY, US_COST_SELL, "US 5bp round-trip (2.5bp one-way)")
    # 台股：TAIEX 指數 (^TWII) 當 proxy — 0050.TW yfinance 資料 2014-01-02 假象斷裂不可用。
    # 投資載具 = 0050 ETF，故套用 ETF 交易成本 (證交稅只課賣出，追蹤 Δw 符號)。
    tw_out, tw_base, tw_rets, tw_wraw, tw_wsm = run_market(
        "^TWII", TW_COST_BUY, TW_COST_SELL,
        f"TW ETF fee 0.1425%x{TW_DISCOUNT}+tax0.15% (buy {TW_COST_BUY*1e4:.1f}bp/sell {TW_COST_SELL*1e4:.1f}bp)",
        display="TAIEX")

    # cost sensitivity (US 10bp round-trip)
    spy_robust, _, _, _, _ = run_market(
        "SPY", US_COST_ROBUST, US_COST_ROBUST, "US 10bp round-trip (5bp one-way) ROBUST")

    # 移除不可序列化的 series
    for o in (spy_out, tw_out, spy_robust):
        o.pop("_raw_net", None)

    results["SPY"] = spy_out
    results["TAIEX"] = tw_out
    results["SPY_cost_robust"] = spy_robust

    # 圖表 (用 base-cost 兩市場)
    make_figures({"SPY": spy_out, "TAIEX": tw_out})

    # 頂層 summary / verdict 材料
    def best_net_band(o):
        cand = {k: v for k, v in o["variants"].items()
                if k.startswith("band_") and not k.startswith("band_edge_")}
        bk = max(cand.items(), key=lambda kv: kv[1]["net_sharpe"])
        return bk[0], bk[1]["net_sharpe"]

    summary = {}
    for mk in ("SPY", "TAIEX"):
        o = results[mk]
        base_net = o["variants"]["baseline_daily"]["net_sharpe"]
        base_turn = o["variants"]["baseline_daily"]["ann_turnover_pct"]
        bk, bnet = best_net_band(o)
        best_turn = o["variants"][bk]["ann_turnover_pct"]
        test = o["tests"][f"{bk}_vs_baseline_netSharpe"]
        summary[mk] = {
            "baseline_daily_net_sharpe": base_net,
            "baseline_daily_turnover_pct": base_turn,
            "best_net_band": bk,
            "best_net_band_net_sharpe": bnet,
            "best_net_band_turnover_pct": best_turn,
            "best_band_vs_baseline_net_sharpe_diff": test["sharpe_diff"],
            "best_band_vs_baseline_p": test["p_value"],
            "best_band_vs_baseline_ci95": [test["ci95_low"], test["ci95_high"]],
            "turnover_reduction_pct": round((1 - best_turn / base_turn) * 100, 1) if base_turn else None,
            "smooth21_net_sharpe": o["variants"]["smooth21"]["net_sharpe"],
            "smooth21_vs_baseline_p": o["tests"]["smooth21_vs_baseline_netSharpe"]["p_value"],
        }
    results["summary"] = summary
    results["params"] = {
        "seed": SEED, "target_vol": TARGET_VOL, "vol_window": VOL_WINDOW,
        "smooth_window": SMOOTH_WINDOW, "lev_cap": LEV_CAP, "bands": BANDS,
        "us_cost_oneway_bp": US_COST_BUY * 1e4, "tw_cost_buy_bp": TW_COST_BUY * 1e4,
        "tw_cost_sell_bp": TW_COST_SELL * 1e4, "tw_discount": TW_DISCOUNT,
    }
    results["references"] = [
        "Bai et al. (2025) FMPM, DOI 10.1007/s11408-025-00486-5 — VT optimal rebalancing boundary",
        "Leland (2000) — no-trade region, rebalance to boundary, turnover -50%",
        "Fleming, Kirby, Ostdiek (2003) JFE — economic value of volatility timing",
        "Moreira & Muir (2017) JF — Volatility-Managed Portfolios",
        "Internal K48 — monthly 12/VIX boundary: turnover down but net Sharpe insignificant",
    ]

    with open(HERE / "k1656_results.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print("WROTE", HERE / "k1656_results.json")

    # console 摘要
    for mk in ("SPY", "TAIEX"):
        s = summary[mk]
        print(f"\n=== {mk} ===")
        print(f"baseline daily: net Sharpe {s['baseline_daily_net_sharpe']}, turnover {s['baseline_daily_turnover_pct']}%")
        print(f"best net band: {s['best_net_band']} net Sharpe {s['best_net_band_net_sharpe']} "
              f"(turnover {s['best_net_band_turnover_pct']}%, -{s['turnover_reduction_pct']}%)")
        print(f"  band vs baseline net Sharpe diff = {s['best_band_vs_baseline_net_sharpe_diff']:.4f}, "
              f"p={s['best_band_vs_baseline_p']:.3f}, CI95={s['best_band_vs_baseline_ci95']}")
        print(f"smooth21: net Sharpe {s['smooth21_net_sharpe']}, p vs baseline {s['smooth21_vs_baseline_p']:.3f}")


if __name__ == "__main__":
    main()
