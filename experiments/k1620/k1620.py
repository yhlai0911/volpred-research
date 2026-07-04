#!/usr/bin/env python
"""
k1620 — 加密貨幣 low-volatility anomaly 的 regime 依賴性
========================================================

研究問題
--------
Low-volatility anomaly（低波動資產風險調整後報酬 >= 高波動資產，違反 CAPM）在
傳統股市被大量記載（Baker-Bradley-Wurgler 2011；Blitz & van Vliet 2007）。
本實驗檢定：**在加密貨幣，low-vol 溢酬是否只在特定市場 regime 出現（regime-dependent）？**

方法
----
1. 一籃子大市值 crypto（yfinance），日資料 2019-01-01 起。
2. 每月月底 rebalance：用「過去 30 日 daily log-return std」排序當月存活幣，分 tercile。
   - low-vol group = 波動最低三分之一等權；high-vol group = 波動最高三分之一等權。
   - premium_t = low-vol group 月報酬 − high-vol group 月報酬。
3. 兩種 regime（皆 lag，用月初已知資訊）：
   - Regime A（primary, trend）：BTC 收盤 vs 其 200 日 SMA（>SMA=bull, <=SMA=bear）。
   - Regime B（vol）：BTC 過去 30 日 vol vs 其「expanding median」（>median=high-vol regime）。
4. 主檢定：premium 在不同 regime 是否顯著不同 —— 各 regime 平均 premium + Newey-West(HAC)
   t 檢定，及迴歸 premium ~ const + regime_dummy（HAC SE）。block bootstrap 佐證。

防錯規則遵守（見 .claude/rules/experiments.md）
--------------------------------------------
* LOOKAHEAD（最高優先）：排序 vol 與 regime 訊號都只用「持有月之前」已實現的資訊。
  程式碼以 `.shift(1)` 等效邏輯明確落實（ranking 在 t-1 月底、報酬在 t 月）。見 build_portfolios()。
* SEED 固定：np.random.seed(SEED)；block bootstrap 用獨立固定種子。
* 跨資產不當 iid：先把同月的跨幣報酬「聚合成 group 月報酬」（等權），再對月度時間序列做
  HAC 檢定 —— 不把 coin-month 當獨立樣本（K1355 教訓）。
* 不看圖下結論：所有結論來自正式 t-test / 迴歸 / bootstrap。
* Null 如實報告；不宣稱因果。

Survivorship caveat：只用「當前 yfinance 抓得到、且在持有月月底仍有報價」的幣，
排除中途消失幣的終端損失（例如 MATIC 於 2025-03 停更），會**高估**存活宇宙報酬。
結論只在「這組存活大市值幣樣本內」成立，不可外推為 crypto low-vol 普世溢酬。
"""

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# 固定 seed（研究誠實原則：所有隨機程序固定 seed）
# ---------------------------------------------------------------------------
SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
START = "2019-01-01"
END = "2026-07-04"

TICKERS = [
    "BTC-USD", "ETH-USD", "BNB-USD", "XRP-USD", "ADA-USD", "SOL-USD",
    "DOGE-USD", "LTC-USD", "LINK-USD", "DOT-USD", "AVAX-USD", "MATIC-USD",
]

VOL_WINDOW = 30          # 過去 30 日 realized vol 用於排序
MIN_VOL_OBS = 25         # 30 日窗內至少 25 個有效 daily return 才算 vol 可靠
MIN_ELIGIBLE = 6         # 一個月至少 6 幣可用，tercile 才各 >= 2
SMA_WINDOW = 200         # BTC 200 日 SMA 定義 trend regime
N_BOOT = 2000            # block bootstrap 重抽次數


# ---------------------------------------------------------------------------
# 1. 資料
# ---------------------------------------------------------------------------
def download_prices() -> pd.DataFrame:
    import yfinance as yf

    px = yf.download(
        TICKERS, start=START, end=END, auto_adjust=True, progress=False
    )["Close"]
    px = px.reindex(columns=TICKERS)
    px.index = pd.to_datetime(px.index)
    px = px.sort_index()
    return px


# ---------------------------------------------------------------------------
# 2. Portfolio 建構（含 lookahead 防護）
# ---------------------------------------------------------------------------
def build_portfolios(px: pd.DataFrame):
    """
    回傳每月的 group 報酬與診斷。

    Lookahead 防護核心
    ------------------
    對持有月 t：
      * 排序資訊窗口 = 截至「t-1 月底最後交易日」為止的過去 30 日 vol（完全在持有期之前）。
      * 買入價 = t-1 月底收盤；賣出價 = t 月底收盤。
      * 因此 signal 來自 t-1（`vol_{t-1}`），報酬實現於 t。等價於對月頻序列做 signal.shift(1)。
    """
    # 日 log return（每幣獨立）
    logret = np.log(px / px.shift(1))

    # 月底最後交易日索引（用實際存在的交易日，crypto 每日都交易）
    month_end_idx = px.groupby([px.index.year, px.index.month]).apply(
        lambda g: g.index[-1]
    )
    month_ends = pd.DatetimeIndex(sorted(month_end_idx.values))

    # Codex review fix (k1620): drop the trailing INCOMPLETE month. When END
    # falls mid-month (e.g. 2026-07-04), the last "month_end" is that month's
    # last available trading day (2026-07-02), whose next day stays in the same
    # month → it is NOT a true calendar month-end. Treating a 2-day stub as a
    # full monthly holding return violates the month-t convention. Detect via
    # "next day stays in same month" and drop it.
    if len(month_ends) >= 1:
        _last = pd.Timestamp(month_ends[-1])
        if (_last + pd.Timedelta(days=1)).month == _last.month:
            month_ends = month_ends[:-1]

    records = []
    coin_counts = []

    # i 從 1 開始：需要前一個月底（t-1）作 signal，本月底（t）作賣出
    for i in range(1, len(month_ends)):
        t_minus_1 = month_ends[i - 1]   # signal 日 & 買入日（月初部位在此決定）
        t = month_ends[i]               # 賣出日（持有月 t 的月底）

        eligible = []
        for coin in TICKERS:
            p_buy = px.loc[t_minus_1, coin]
            p_sell = px.loc[t, coin]
            if not (np.isfinite(p_buy) and np.isfinite(p_sell)):
                # 缺任一端點（幣尚未上市 / 已停更）→ 該月排除該幣
                continue
            # 過去 30 日 vol：截至 t_minus_1（含）的最後 VOL_WINDOW 個 daily return
            win = logret.loc[:t_minus_1, coin].iloc[-VOL_WINDOW:]
            win = win.dropna()
            if len(win) < MIN_VOL_OBS:
                continue
            vol = win.std(ddof=1)
            # 持有月報酬（t-1 月底 -> t 月底），只用價格，部位已在 t-1 決定
            hold_ret = p_sell / p_buy - 1.0
            eligible.append((coin, vol, hold_ret))

        n = len(eligible)
        coin_counts.append({"month_end": str(pd.Timestamp(t).date()), "n_eligible": n})
        if n < MIN_ELIGIBLE:
            continue

        eligible.sort(key=lambda x: x[1])  # 按 vol 由低到高
        k = n // 3
        low_group = eligible[:k]            # 低波動 tercile
        high_group = eligible[-k:]          # 高波動 tercile
        all_group = eligible

        low_ret = float(np.mean([r for _, _, r in low_group]))
        high_ret = float(np.mean([r for _, _, r in high_group]))
        ew_ret = float(np.mean([r for _, _, r in all_group]))
        premium = low_ret - high_ret        # low-vol anomaly：正 = 低波動贏

        records.append({
            "month_end": pd.Timestamp(t),
            "n_eligible": n,
            "k": k,
            "low_ret": low_ret,
            "high_ret": high_ret,
            "ew_ret": ew_ret,
            "premium": premium,
        })

    port = pd.DataFrame(records).set_index("month_end")
    counts = pd.DataFrame(coin_counts)
    return port, counts, month_ends, logret


# ---------------------------------------------------------------------------
# 3. Regime 定義（皆 lag：用月初已知資訊）
# ---------------------------------------------------------------------------
def add_regimes(port: pd.DataFrame, px: pd.DataFrame, logret: pd.DataFrame):
    """
    Regime A（trend, primary）：t-1 月底 BTC 收盤是否 > 其 200 日 SMA。bull=1, bear=0。
    Regime B（vol）：t-1 月底 BTC 過去 30 日 vol 是否 > 「截至 t-1 的 expanding median」。high=1。

    兩者都只用 t-1（含）以前資訊，對持有月 t 而言完全 lagged（無 lookahead）。
    expanding median 避免用 full-sample median 造成的 in-sample 門檻 lookahead。
    """
    btc = px["BTC-USD"]
    btc_sma = btc.rolling(SMA_WINDOW, min_periods=SMA_WINDOW).mean()
    btc_ret = logret["BTC-USD"]
    btc_vol30 = btc_ret.rolling(VOL_WINDOW, min_periods=MIN_VOL_OBS).std(ddof=1)

    # 對每個持有月 t，取 signal 日 = 前一個月底 t-1
    idx_months = port.index
    # 建 month_end -> 前一個月底 的映射（port.index 已是持有月月底 t；t-1 = 上一筆）
    # 直接用 px 的月底序列比較穩妥：找出 <= (t 前一個月底) 的最後資料點
    # 這裡以「t 的前一個交易月月底」為 signal 日。
    signal_dates = []
    all_me = px.groupby([px.index.year, px.index.month]).apply(lambda g: g.index[-1])
    all_me = pd.DatetimeIndex(sorted(all_me.values))
    for t in idx_months:
        pos = all_me.get_loc(t)
        signal_dates.append(all_me[pos - 1])
    signal_dates = pd.DatetimeIndex(signal_dates)

    trend_bull = []
    vol_high = []
    btc_vol_series = []
    # expanding median 需依時間順序累積 BTC 月度 vol
    hist_vols = []
    for sd in signal_dates:
        # Regime A: BTC vs 200d SMA（signal 日已知）
        close_sd = btc.loc[sd]
        sma_sd = btc_sma.loc[sd] if sd in btc_sma.index else np.nan
        trend_bull.append(1 if (np.isfinite(sma_sd) and close_sd > sma_sd) else 0)

        # Regime B: BTC 30d vol vs expanding median（只用截至 sd 的歷史，含 sd）
        v = btc_vol30.loc[sd] if sd in btc_vol30.index else np.nan
        btc_vol_series.append(float(v) if np.isfinite(v) else np.nan)
        if np.isfinite(v):
            hist_vols.append(v)
        med = np.median(hist_vols) if hist_vols else np.nan
        vol_high.append(1 if (np.isfinite(v) and np.isfinite(med) and v > med) else 0)

    port = port.copy()
    port["signal_date"] = signal_dates
    port["btc_close_sig"] = btc.loc[signal_dates].values
    port["trend_bull"] = trend_bull            # 1=bull, 0=bear
    port["btc_vol30_sig"] = btc_vol_series
    port["vol_high"] = vol_high                # 1=high-vol regime, 0=low-vol regime
    return port


# ---------------------------------------------------------------------------
# 4. 統計檢定
# ---------------------------------------------------------------------------
def nw_ttest_mean(x: np.ndarray, maxlags: int | None = None):
    """對一維序列的均值做 Newey-West(HAC) t 檢定（H0: mean=0）。"""
    import statsmodels.api as sm

    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 3:
        return {"mean": float(np.mean(x)) if n else np.nan, "t": np.nan, "p": np.nan, "n": n}
    if maxlags is None:
        maxlags = int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
        maxlags = max(1, maxlags)
    X = np.ones((n, 1))
    res = sm.OLS(x, X).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    return {
        "mean": float(res.params[0]),
        "t": float(res.tvalues[0]),
        "p": float(res.pvalues[0]),
        "n": int(n),
        "maxlags": int(maxlags),
    }


def regime_diff_regression(premium: np.ndarray, dummy: np.ndarray):
    """premium ~ const + dummy，HAC SE。dummy 係數檢定兩 regime premium 差異。"""
    import statsmodels.api as sm

    premium = np.asarray(premium, dtype=float)
    dummy = np.asarray(dummy, dtype=float)
    mask = np.isfinite(premium) & np.isfinite(dummy)
    premium, dummy = premium[mask], dummy[mask]
    n = len(premium)
    maxlags = max(1, int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0))))
    X = sm.add_constant(dummy)
    res = sm.OLS(premium, X).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    return {
        "const": float(res.params[0]),          # regime=0 的平均 premium
        "dummy_coef": float(res.params[1]),      # regime=1 相對 regime=0 的差異
        "dummy_t": float(res.tvalues[1]),
        "dummy_p": float(res.pvalues[1]),
        "n": int(n),
        "maxlags": int(maxlags),
    }


def block_bootstrap_diff(premium: np.ndarray, dummy: np.ndarray,
                         block: int = 3, n_boot: int = N_BOOT, seed: int = SEED):
    """
    對「regime=1 平均 premium − regime=0 平均 premium」做 circular block bootstrap，
    保留時間序列自相關結構。回傳 bootstrap p-value（雙尾）。
    """
    rng = np.random.default_rng(seed)
    premium = np.asarray(premium, dtype=float)
    dummy = np.asarray(dummy, dtype=float)
    mask = np.isfinite(premium) & np.isfinite(dummy)
    premium, dummy = premium[mask], dummy[mask]
    n = len(premium)

    def diff_of(p, d):
        g1 = p[d == 1]
        g0 = p[d == 0]
        if len(g1) == 0 or len(g0) == 0:
            return np.nan
        return np.mean(g1) - np.mean(g0)

    obs = diff_of(premium, dummy)

    n_blocks = int(np.ceil(n / block))
    diffs = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        idx = np.concatenate([(np.arange(s, s + block) % n) for s in starts])[:n]
        diffs[b] = diff_of(premium[idx], dummy[idx])
    diffs = diffs[np.isfinite(diffs)]
    # 以「中心化後的 |diff| >= |obs|」估雙尾 p
    centered = diffs - np.nanmean(diffs)
    p = float(np.mean(np.abs(centered) >= abs(obs))) if len(diffs) else np.nan
    return {"obs_diff": float(obs), "boot_p": p, "n_boot_valid": int(len(diffs))}


# ---------------------------------------------------------------------------
# 5. 圖
# ---------------------------------------------------------------------------
def make_plots(port: pd.DataFrame):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # (a) 累積報酬曲線 low-vol vs high-vol vs 等權全體
    fig, ax = plt.subplots(figsize=(10, 5.5))
    cum_low = (1 + port["low_ret"]).cumprod()
    cum_high = (1 + port["high_ret"]).cumprod()
    cum_ew = (1 + port["ew_ret"]).cumprod()
    ax.plot(port.index, cum_low, label="Low-vol tercile", color="#2a7", lw=2)
    ax.plot(port.index, cum_high, label="High-vol tercile", color="#c33", lw=2)
    ax.plot(port.index, cum_ew, label="Equal-weight all", color="#888", lw=1.4, ls="--")
    ax.set_yscale("log")
    ax.set_ylabel("Cumulative growth of $1 (log scale)")
    ax.set_title("k1620: Crypto low-vol vs high-vol tercile cumulative return\n"
                 "(monthly rebalance, rank by trailing 30d vol, signal lagged)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(HERE / "k1620_fig_cumret.png", dpi=130)
    plt.close(fig)

    # (b) 各 regime 平均 premium bar（兩種 regime 定義）
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, (col, labels, title) in zip(
        axes,
        [("trend_bull", {0: "Bear\n(BTC<200d SMA)", 1: "Bull\n(BTC>200d SMA)"},
          "Regime A: BTC trend"),
         ("vol_high", {0: "Low-vol regime\n(BTC vol<med)", 1: "High-vol regime\n(BTC vol>med)"},
          "Regime B: BTC vol")],
    ):
        means, ses, xt = [], [], []
        for val in [0, 1]:
            sub = port.loc[port[col] == val, "premium"].values
            st = nw_ttest_mean(sub)
            means.append(st["mean"] * 100)   # 轉百分點
            # HAC SE = mean / t
            se = abs(st["mean"] / st["t"]) * 100 if (st["t"] and np.isfinite(st["t"])) else 0
            ses.append(se)
            xt.append(labels[val])
        colors = ["#c33", "#2a7"]
        ax.bar([0, 1], means, yerr=ses, capsize=6, color=colors, alpha=0.85)
        ax.axhline(0, color="k", lw=0.8)
        ax.set_xticks([0, 1])
        ax.set_xticklabels(xt)
        ax.set_ylabel("Mean monthly low−high premium (%)")
        ax.set_title(title)
        ax.grid(True, axis="y", alpha=0.3)
    fig.suptitle("k1620: Low-vol premium by market regime (error bars = Newey-West HAC SE)")
    fig.tight_layout()
    fig.savefig(HERE / "k1620_fig_regime_premium.png", dpi=130)
    plt.close(fig)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    px = download_prices()

    # 資料診斷
    diag = {}
    for coin in TICKERS:
        s = px[coin].dropna()
        diag[coin] = {
            "n": int(len(s)),
            "first": str(s.index[0].date()) if len(s) else None,
            "last": str(s.index[-1].date()) if len(s) else None,
        }

    port, counts, month_ends, logret = build_portfolios(px)
    port = add_regimes(port, px, logret)

    prem = port["premium"].values

    # 全樣本 premium（低-高）HAC t 檢定
    overall = nw_ttest_mean(prem)

    # 各 regime premium
    results = {"regime_A_trend": {}, "regime_B_vol": {}}
    for col, key, lab0, lab1 in [
        ("trend_bull", "regime_A_trend", "bear", "bull"),
        ("vol_high", "regime_B_vol", "low_vol_regime", "high_vol_regime"),
    ]:
        r0 = nw_ttest_mean(port.loc[port[col] == 0, "premium"].values)
        r1 = nw_ttest_mean(port.loc[port[col] == 1, "premium"].values)
        reg = regime_diff_regression(port["premium"].values, port[col].values)
        boot = block_bootstrap_diff(port["premium"].values, port[col].values)
        results[key] = {
            lab0: r0,
            lab1: r1,
            "n_" + lab0: int((port[col] == 0).sum()),
            "n_" + lab1: int((port[col] == 1).sum()),
            "diff_regression_HAC": reg,   # dummy=1 相對 dummy=0
            "block_bootstrap": boot,
        }

    # 累積報酬 / annualized 摘要
    def ann_stats(r):
        r = pd.Series(r).dropna()
        if len(r) < 2:
            return {}
        mean_m = r.mean()
        std_m = r.std(ddof=1)
        sharpe_ann = (mean_m / std_m) * np.sqrt(12) if std_m > 0 else np.nan
        cum = float((1 + r).prod())
        return {
            "mean_monthly": float(mean_m),
            "std_monthly": float(std_m),
            "sharpe_annualized": float(sharpe_ann),
            "cumulative_multiple": cum,
            "n_months": int(len(r)),
        }

    port_stats = {
        "low_vol_tercile": ann_stats(port["low_ret"]),
        "high_vol_tercile": ann_stats(port["high_ret"]),
        "equal_weight_all": ann_stats(port["ew_ret"]),
        "premium_low_minus_high": ann_stats(port["premium"]),
    }

    make_plots(port)

    out = {
        "experiment_id": "k1620",
        "title": "加密貨幣 low-volatility anomaly 的 regime 依賴性",
        "data": {
            "source": "yfinance daily Close (auto_adjust=True)",
            "period": f"{START} .. {port.index[-1].date()}",
            "tickers": TICKERS,
            "n_tickers": len(TICKERS),
            "per_coin": diag,
            "n_months_tested": int(len(port)),
            "eligible_coin_counts_head": counts.head(8).to_dict("records"),
            "eligible_coin_counts_tail": counts.tail(4).to_dict("records"),
        },
        "config": {
            "vol_window_days": VOL_WINDOW,
            "min_vol_obs": MIN_VOL_OBS,
            "min_eligible_coins": MIN_ELIGIBLE,
            "sma_window": SMA_WINDOW,
            "seed": SEED,
            "n_boot": N_BOOT,
        },
        "overall_premium_low_minus_high": overall,
        "portfolio_stats": port_stats,
        "regime_tests": results,
        "lookahead_protection": (
            "Ranking vol computed on window ending at t-1 month-end; holding return over "
            "month t (buy t-1 month-end close, sell t month-end close); regime signals "
            "(BTC 200d SMA, BTC 30d vol vs expanding median) all evaluated at t-1 signal "
            "date. Equivalent to signal.shift(1) at monthly frequency."
        ),
        "survivorship_caveat": (
            "Universe = currently downloadable coins with quotes at both month endpoints; "
            "delisted coins' terminal losses excluded (e.g. MATIC ends 2025-03) → upward "
            "survivorship bias. Conclusions hold only within this surviving large-cap sample."
        ),
        "cross_asset_iid_note": (
            "Premium is a portfolio-level monthly series (cross-coin equal-weight aggregated "
            "within tercile BEFORE testing); tests run on the monthly time series with HAC, "
            "not on coin-month observations (K1355 rule)."
        ),
    }

    # 存月度序列供復現/繪圖核對
    port_out = port.reset_index().copy()
    port_out["month_end"] = port_out["month_end"].astype(str)
    port_out["signal_date"] = port_out["signal_date"].astype(str)
    out["monthly_series"] = port_out.to_dict("records")

    with open(HERE / "k1620_results.json", "w") as f:
        json.dump(out, f, indent=2, default=str)

    # 精簡 stdout 摘要
    print("=== k1620 summary ===")
    print(f"months tested: {len(port)}  | tickers: {len(TICKERS)}")
    print(f"overall premium(low-high) mean={overall['mean']:.4f} "
          f"t={overall['t']:.2f} p={overall['p']:.3f} n={overall['n']}")
    for key in ["regime_A_trend", "regime_B_vol"]:
        r = results[key]
        reg = r["diff_regression_HAC"]
        print(f"\n[{key}] diff(dummy) coef={reg['dummy_coef']:.4f} "
              f"t={reg['dummy_t']:.2f} p={reg['dummy_p']:.3f} "
              f"boot_p={r['block_bootstrap']['boot_p']:.3f}")
        for sub, v in r.items():
            if isinstance(v, dict) and "mean" in v:
                print(f"    {sub:>18}: mean={v['mean']:.4f} t={v['t']:.2f} "
                      f"p={v['p']:.3f} n={v['n']}")
    print("\nSharpe(ann): low={:.2f} high={:.2f} ew={:.2f}".format(
        port_stats["low_vol_tercile"].get("sharpe_annualized", float('nan')),
        port_stats["high_vol_tercile"].get("sharpe_annualized", float('nan')),
        port_stats["equal_weight_all"].get("sharpe_annualized", float('nan')),
    ))
    print("wrote k1620_results.json + 2 figures")


if __name__ == "__main__":
    main()
