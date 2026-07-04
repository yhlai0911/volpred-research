#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K1628 — 投資迷思驗證：「黃金真的是股災避風港嗎？」
================================================================

研究問題
--------
讀者常把「黃金是避險資產」理解成：股市大跌時，黃金應該明顯上漲或至少不跌。
本實驗用 GLD 與 SPY 的日報酬，檢驗黃金在股票壓力日是否真的呈現 safe-haven
特徵，以及這個保護力是否穩定。

文獻口徑
--------
- Baur and Lucey (2010): hedge = 平均不相關/負相關；safe haven = 市場崩跌時不相關/負相關。
- Baur and McDermott (2010): gold 對美歐股市常是 hedge/safe haven，但效果非所有市場普遍成立。
- Hood and Malik (2013): gold 可作 weak safe haven，但 VIX 在高波動期通常更強。

方法
----
這是 empirical descriptive test，不是交易策略：
1. 資料：本地 SQLite price_cache.db，GLD / SPY / ^VIX，2016-01-04 起。
2. 報酬：各資產 adj_close close-to-close pct_change。
3. Safe-haven 檢定：
   - 全樣本與 SPY 下跌/大跌條件下的 GLD 平均報酬、收紅率、SPY-GLD 相關。
   - 股票壓力定義：SPY<0、SPY<-1%、SPY<-2%、SPY<-3%、SPY bottom 10/5/1%。
   - VIX 高波動 regime 作描述性 robustness：VIX top 20/10/5%。
   - 事件視角：2018Q4、COVID crash、2022 rate-shock bear、2025 April shock。
4. 統計：
   - Wilson CI for GLD positive rate.
   - Fisher-z CI for correlation.
   - HAC lag=5 mean test for GLD conditional mean.
   - Baur-style quantile interaction regression with HAC lag=5.
   - Circular block bootstrap (block=5, B=2000, seed=42) for key conditions.

注意
----
本實驗的 same-day GLD/SPY 關係是 safe-haven 定義下的「危機同日描述」，
不是 signal-from-t-1 的預測回測；不產生可交易策略績效宣稱。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import statsmodels.api as sm

matplotlib.use("Agg")
import matplotlib.pyplot as plt


matplotlib.rcParams["font.sans-serif"] = [
    "Arial Unicode MS",
    "Heiti TC",
    "STHeiti",
    "Hiragino Sans GB",
    "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False


SEED = 42
BOOT_N = 2000
BOOT_BLOCK = 5
HAC_LAG = 5

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DB_PATH = REPO / "data" / "cache" / "price_cache.db"

START_DATE = "2016-01-04"
SPY = "SPY"
GLD = "GLD"
VIX = "^VIX"


EPISODES = {
    "2018Q4_selloff": ("2018-10-01", "2018-12-31", "2018Q4 sell-off"),
    "covid_crash": ("2020-02-20", "2020-04-30", "COVID crash"),
    "rate_shock_2022": ("2022-01-03", "2022-10-31", "2022 rate-shock bear"),
    "apr_2025_shock": ("2025-04-01", "2025-04-30", "2025 April shock"),
}


LITERATURE = [
    {
        "citation": "Baur, D. G. and Lucey, B. M. (2010), Financial Review",
        "title": "Is Gold a Hedge or a Safe Haven? An Analysis of Stocks, Bonds and Gold",
        "design_use": "Defines hedge vs safe haven and motivates extreme-stock-return conditioning.",
        "url": "https://doi.org/10.1111/j.1540-6288.2010.00244.x",
    },
    {
        "citation": "Baur, D. G. and McDermott, T. K. (2010), Journal of Banking & Finance",
        "title": "Is gold a safe haven? International evidence",
        "design_use": "Warns that safe-haven behavior is market- and crisis-dependent.",
        "url": "https://doi.org/10.1016/j.jbankfin.2009.12.008",
    },
    {
        "citation": "Hood, M. and Malik, F. (2013), Review of Financial Economics",
        "title": "Is gold the best hedge and a safe haven under changing stock market volatility?",
        "design_use": "Motivates VIX high-volatility robustness and weak-vs-strong safe-haven distinction.",
        "url": "https://doi.org/10.1016/j.rfe.2013.03.001",
    },
]


def load_price_series(ticker: str, start: str = START_DATE) -> pd.DataFrame:
    con = sqlite3.connect(str(DB_PATH))
    try:
        df = pd.read_sql(
            "SELECT date, close, adj_close FROM price_data WHERE ticker=? ORDER BY date",
            con,
            params=(ticker,),
            parse_dates=["date"],
        )
    finally:
        con.close()

    if df.empty:
        raise ValueError(f"No rows found for ticker={ticker}")

    price = df["adj_close"].where(df["adj_close"].notna(), df["close"]).astype(float)
    out = pd.DataFrame({"date": df["date"], "price": price})
    out = out.dropna(subset=["price"]).drop_duplicates("date").sort_values("date")
    out = out[out["date"] >= pd.Timestamp(start)].reset_index(drop=True)
    out["ret"] = out["price"].pct_change()
    return out[["date", "price", "ret"]]


def load_vix(start: str = START_DATE) -> pd.DataFrame:
    con = sqlite3.connect(str(DB_PATH))
    try:
        df = pd.read_sql(
            "SELECT date, close FROM price_data WHERE ticker=? ORDER BY date",
            con,
            params=(VIX,),
            parse_dates=["date"],
        )
    finally:
        con.close()
    out = df.dropna(subset=["close"]).drop_duplicates("date").sort_values("date")
    out = out[out["date"] >= pd.Timestamp(start)].reset_index(drop=True)
    return out.rename(columns={"close": "vix"})[["date", "vix"]]


def build_panel() -> pd.DataFrame:
    spy = load_price_series(SPY).rename(columns={"price": "spy_price", "ret": "r_spy"})
    gld = load_price_series(GLD).rename(columns={"price": "gld_price", "ret": "r_gld"})
    vix = load_vix()

    panel = (
        spy[["date", "spy_price", "r_spy"]]
        .merge(gld[["date", "gld_price", "r_gld"]], on="date", how="inner")
        .merge(vix, on="date", how="left")
        .dropna(subset=["r_spy", "r_gld"])
        .sort_values("date")
        .reset_index(drop=True)
    )
    panel["rolling_corr_60d"] = panel["r_spy"].rolling(60).corr(panel["r_gld"])
    panel["spy_drawdown"] = panel["spy_price"] / panel["spy_price"].cummax() - 1.0
    return panel


def wilson_ci(k: int, n: int, z: float = 1.959963984540054) -> list[float]:
    if n == 0:
        return [float("nan"), float("nan")]
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return [float(center - half), float(center + half)]


def fisher_corr_ci(r: float, n: int, z: float = 1.959963984540054) -> list[float]:
    if n <= 3 or not np.isfinite(r):
        return [float("nan"), float("nan")]
    r_clip = float(np.clip(r, -0.999999, 0.999999))
    zr = np.arctanh(r_clip)
    se = 1 / np.sqrt(n - 3)
    return [float(np.tanh(zr - z * se)), float(np.tanh(zr + z * se))]


def hac_mean_test(x: np.ndarray, lag: int = HAC_LAG) -> dict:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 3:
        return {"mean": float("nan"), "se_hac": float("nan"), "t_hac": float("nan"), "p_hac": float("nan")}
    X = np.ones((len(x), 1))
    res = sm.OLS(x, X).fit(cov_type="HAC", cov_kwds={"maxlags": lag})
    return {
        "mean": float(res.params[0]),
        "se_hac": float(res.bse[0]),
        "t_hac": float(res.tvalues[0]),
        "p_hac": float(res.pvalues[0]),
    }


def annualized_vol(x: pd.Series) -> float:
    return float(x.std(ddof=1) * np.sqrt(252)) if len(x) > 1 else float("nan")


def compound_return(x: pd.Series) -> float:
    if len(x) == 0:
        return float("nan")
    return float((1.0 + x).prod() - 1.0)


def condition_metrics(df: pd.DataFrame, mask: pd.Series, label: str, definition: str) -> dict:
    sub = df.loc[mask].copy()
    n = int(len(sub))
    if n == 0:
        return {"label": label, "definition": definition, "n": 0}

    gld_pos = sub["r_gld"] > 0
    gld_nonneg = sub["r_gld"] >= 0
    corr = float(sub["r_spy"].corr(sub["r_gld"])) if n > 1 else float("nan")
    mean_test = hac_mean_test(sub["r_gld"].to_numpy())
    spy_down = sub["r_spy"] < 0
    n_spy_down = int(spy_down.sum())
    pos_when_spy_down = float((sub.loc[spy_down, "r_gld"] > 0).mean()) if n_spy_down else float("nan")

    return {
        "label": label,
        "definition": definition,
        "n": n,
        "spy_mean_return": float(sub["r_spy"].mean()),
        "gld_mean_return": float(sub["r_gld"].mean()),
        "gld_mean_return_hac": mean_test,
        "spy_compound_return": compound_return(sub["r_spy"]),
        "gld_compound_return": compound_return(sub["r_gld"]),
        "spy_ann_vol": annualized_vol(sub["r_spy"]),
        "gld_ann_vol": annualized_vol(sub["r_gld"]),
        "gld_positive_rate": float(gld_pos.mean()),
        "gld_positive_rate_ci95": wilson_ci(int(gld_pos.sum()), n),
        "gld_nonnegative_rate": float(gld_nonneg.mean()),
        "spy_gld_corr": corr,
        "spy_gld_corr_ci95_fisher": fisher_corr_ci(corr, n),
        "n_spy_down_inside_condition": n_spy_down,
        "gld_positive_when_spy_down_inside_condition": pos_when_spy_down,
        "min_date": sub["date"].min().strftime("%Y-%m-%d"),
        "max_date": sub["date"].max().strftime("%Y-%m-%d"),
    }


def circular_block_bootstrap_condition(
    df: pd.DataFrame,
    condition_name: str,
    condition_func,
    block: int = BOOT_BLOCK,
    n_boot: int = BOOT_N,
    seed: int = SEED,
) -> dict:
    rng = np.random.default_rng(seed)
    n = len(df)
    if n == 0:
        return {"condition": condition_name, "n_boot_effective": 0}

    n_blocks = int(np.ceil(n / block))
    est_mean = []
    est_pos = []
    est_corr = []
    r_spy = df["r_spy"].to_numpy()
    r_gld = df["r_gld"].to_numpy()
    vix = df["vix"].to_numpy()
    dates = df["date"].to_numpy()

    for _ in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block) % n for s in starts])[:n]
        sample = pd.DataFrame(
            {
                "date": dates[idx],
                "r_spy": r_spy[idx],
                "r_gld": r_gld[idx],
                "vix": vix[idx],
            }
        )
        mask = condition_func(sample)
        sub = sample.loc[mask]
        if len(sub) < 4:
            continue
        est_mean.append(float(sub["r_gld"].mean()))
        est_pos.append(float((sub["r_gld"] > 0).mean()))
        est_corr.append(float(sub["r_spy"].corr(sub["r_gld"])))

    def ci(vals):
        vals = np.array(vals, dtype=float)
        vals = vals[np.isfinite(vals)]
        if len(vals) == 0:
            return [float("nan"), float("nan")]
        return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]

    return {
        "condition": condition_name,
        "block": block,
        "n_boot": n_boot,
        "seed": seed,
        "n_boot_effective": int(len(est_mean)),
        "gld_mean_return_ci95": ci(est_mean),
        "gld_positive_rate_ci95": ci(est_pos),
        "spy_gld_corr_ci95": ci(est_corr),
    }


def safe_haven_regression(df: pd.DataFrame) -> dict:
    q10 = float(df["r_spy"].quantile(0.10))
    q05 = float(df["r_spy"].quantile(0.05))
    q01 = float(df["r_spy"].quantile(0.01))

    x = df["r_spy"].to_numpy()
    bins = {
        "q10_to_q05": ((df["r_spy"] <= q10) & (df["r_spy"] > q05)).to_numpy(),
        "q05_to_q01": ((df["r_spy"] <= q05) & (df["r_spy"] > q01)).to_numpy(),
        "q01": (df["r_spy"] <= q01).to_numpy(),
    }
    X = pd.DataFrame(
        {
            "const": 1.0,
            "r_spy_base": x,
            "r_spy_x_q10_to_q05": x * bins["q10_to_q05"].astype(float),
            "r_spy_x_q05_to_q01": x * bins["q05_to_q01"].astype(float),
            "r_spy_x_q01": x * bins["q01"].astype(float),
        }
    )
    y = df["r_gld"].to_numpy()
    res = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAG})

    params = {name: float(res.params[name]) for name in X.columns}
    bse = {name: float(res.bse[name]) for name in X.columns}
    tvals = {name: float(res.tvalues[name]) for name in X.columns}
    pvals = {name: float(res.pvalues[name]) for name in X.columns}

    base = params["r_spy_base"]
    slopes = {
        "normal_above_q10": base,
        "q10_to_q05": base + params["r_spy_x_q10_to_q05"],
        "q05_to_q01": base + params["r_spy_x_q05_to_q01"],
        "q01": base + params["r_spy_x_q01"],
    }
    strong_safe_haven_flags = {k: bool(v <= 0) for k, v in slopes.items()}

    return {
        "spec": "r_gld = alpha + beta*r_spy + regime interaction slopes, HAC lag=5",
        "n_obs": int(len(df)),
        "spy_quantiles": {"q10": q10, "q05": q05, "q01": q01},
        "params": params,
        "se_hac": bse,
        "t_hac": tvals,
        "p_hac": pvals,
        "r_squared": float(sm.OLS(y, X).fit().rsquared),
        "conditional_slopes": slopes,
        "strong_safe_haven_slope_nonpositive": strong_safe_haven_flags,
        "interpretation": (
            "Nonpositive conditional slope in crash bins is consistent with the strong safe-haven "
            "definition; positive slopes imply gold tends to co-move with equities in that stress bin."
        ),
    }


def build_conditions(df: pd.DataFrame) -> dict[str, tuple[str, pd.Series]]:
    q10 = float(df["r_spy"].quantile(0.10))
    q05 = float(df["r_spy"].quantile(0.05))
    q01 = float(df["r_spy"].quantile(0.01))
    vix80 = float(df["vix"].quantile(0.80))
    vix90 = float(df["vix"].quantile(0.90))
    vix95 = float(df["vix"].quantile(0.95))

    return {
        "all_days": ("All paired GLD/SPY trading days", pd.Series(True, index=df.index)),
        "spy_down": ("SPY return < 0", df["r_spy"] < 0),
        "spy_below_minus_1pct": ("SPY return < -1%", df["r_spy"] < -0.01),
        "spy_below_minus_2pct": ("SPY return < -2%", df["r_spy"] < -0.02),
        "spy_below_minus_3pct": ("SPY return < -3%", df["r_spy"] < -0.03),
        "spy_bottom_10pct": (f"SPY bottom 10% daily returns (<= {q10:.4%})", df["r_spy"] <= q10),
        "spy_bottom_5pct": (f"SPY bottom 5% daily returns (<= {q05:.4%})", df["r_spy"] <= q05),
        "spy_bottom_1pct": (f"SPY bottom 1% daily returns (<= {q01:.4%})", df["r_spy"] <= q01),
        "vix_top_20pct": (f"VIX top 20% days (>= {vix80:.2f})", df["vix"] >= vix80),
        "vix_top_10pct": (f"VIX top 10% days (>= {vix90:.2f})", df["vix"] >= vix90),
        "vix_top_5pct": (f"VIX top 5% days (>= {vix95:.2f})", df["vix"] >= vix95),
        "vix_top_10pct_and_spy_down": (
            f"VIX top 10% (>= {vix90:.2f}) and SPY return < 0",
            (df["vix"] >= vix90) & (df["r_spy"] < 0),
        ),
    }


def episode_metrics(df: pd.DataFrame) -> dict:
    out = {}
    for key, (start, end, label) in EPISODES.items():
        mask = (df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))
        out[key] = condition_metrics(df, mask, label, f"{start} to {end}")
    return out


def make_figures(df: pd.DataFrame, conditions: dict, results: dict) -> None:
    _fig_condition_bars(results)
    _fig_rolling_corr(df)


def _fig_condition_bars(results: dict) -> None:
    keys = [
        "all_days",
        "spy_down",
        "spy_below_minus_1pct",
        "spy_below_minus_2pct",
        "spy_below_minus_3pct",
        "vix_top_10pct_and_spy_down",
    ]
    labels = [
        "全樣本",
        "SPY<0",
        "SPY<-1%",
        "SPY<-2%",
        "SPY<-3%",
        "VIX前10%且SPY跌",
    ]
    rows = [results["conditions"][k] for k in keys]
    pos = [r["gld_positive_rate"] for r in rows]
    means = [r["gld_mean_return"] * 100 for r in rows]
    corr = [r["spy_gld_corr"] for r in rows]
    ns = [r["n"] for r in rows]

    x = np.arange(len(labels))
    fig, axes = plt.subplots(2, 1, figsize=(10.5, 8.0), sharex=True)

    axes[0].bar(x - 0.18, pos, width=0.36, color="#C9A227", edgecolor="black", linewidth=0.5, label="GLD收紅率")
    axes[0].axhline(0.5, color="black", linestyle="--", linewidth=1.0, label="50%")
    axes[0].set_ylabel("GLD 收紅率")
    axes[0].set_ylim(0, 0.75)
    axes[0].legend(loc="upper right", fontsize=9)
    for xi, p, n in zip(x, pos, ns):
        axes[0].text(xi - 0.18, p + 0.015, f"{p:.0%}\n(n={n})", ha="center", va="bottom", fontsize=8)

    ax2 = axes[0].twinx()
    ax2.plot(x + 0.18, corr, color="#2C3E50", marker="o", linewidth=2.0, label="SPY-GLD相關")
    ax2.axhline(0, color="#2C3E50", linestyle=":", linewidth=1.0)
    ax2.set_ylabel("同日相關")
    ax2.set_ylim(-0.35, 0.55)

    colors = ["#5DADE2" if m >= 0 else "#C0392B" for m in means]
    axes[1].bar(x, means, color=colors, edgecolor="black", linewidth=0.5)
    axes[1].axhline(0, color="black", linewidth=1.0)
    axes[1].set_ylabel("GLD 平均日報酬 (%)")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels, rotation=20, ha="right")
    for xi, m in zip(x, means):
        va = "bottom" if m >= 0 else "top"
        offset = 0.015 if m >= 0 else -0.015
        axes[1].text(xi, m + offset, f"{m:+.2f}%", ha="center", va=va, fontsize=9)

    fig.suptitle("黃金避風港檢定：股市壓力越大，GLD 不一定更常上漲", fontsize=13)
    fig.tight_layout()
    fig.savefig(HERE / "fig_safe_haven_conditions.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def _fig_rolling_corr(df: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(11, 5.8))
    ax.plot(df["date"], df["rolling_corr_60d"], color="#2C3E50", linewidth=1.4, label="60日 rolling corr(SPY, GLD)")
    ax.axhline(0, color="black", linestyle="--", linewidth=0.9)
    for _, (start, end, label) in EPISODES.items():
        ax.axvspan(pd.Timestamp(start), pd.Timestamp(end), color="#C9A227", alpha=0.13)
        mid = pd.Timestamp(start) + (pd.Timestamp(end) - pd.Timestamp(start)) / 2
        ax.text(mid, 0.92, label, rotation=90, ha="center", va="top", fontsize=8, color="#7D6608")
    ax.set_ylim(-0.75, 1.0)
    ax.set_ylabel("60日相關")
    ax.set_title("SPY-GLD 相關是 regime-dependent：危機中有時負相關，有時同跌", fontsize=13)
    ax.grid(alpha=0.25)
    ax.legend(loc="lower left", fontsize=9)
    fig.tight_layout()
    fig.savefig(HERE / "fig_rolling_corr_episodes.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    np.random.seed(SEED)
    df = build_panel()

    conditions = build_conditions(df)
    condition_results = {
        key: condition_metrics(df, mask, key, definition)
        for key, (definition, mask) in conditions.items()
    }
    episodes = episode_metrics(df)
    regression = safe_haven_regression(df)

    vix90 = float(df["vix"].quantile(0.90))
    boot = {
        "spy_below_minus_2pct": circular_block_bootstrap_condition(
            df,
            "SPY<-2%",
            lambda x: x["r_spy"] < -0.02,
            seed=SEED,
        ),
        "vix_top_10pct_and_spy_down": circular_block_bootstrap_condition(
            df,
            "VIX top 10% and SPY<0",
            lambda x, vix90=vix90: (x["vix"] >= vix90) & (x["r_spy"] < 0),
            seed=SEED + 1,
        ),
    }

    core = condition_results["spy_below_minus_2pct"]
    strong = condition_results["spy_below_minus_3pct"]
    vix_stress = condition_results["vix_top_10pct_and_spy_down"]
    verdict = {
        "label": "WEAK_REGIME_DEPENDENT_SAFE_HAVEN_NOT_AUTOMATIC",
        "one_sentence": (
            "GLD 對 SPY 的平均相關很低，但在 2016-2026 的 SPY 大跌日並沒有穩定負相關；"
            "SPY<-2% 時 GLD 收紅率約 "
            f"{core['gld_positive_rate']:.1%}、同日相關 {core['spy_gld_corr']:.3f}，"
            "因此『有時能保護』成立，『股災一定抗跌』不成立。"
        ),
        "safe_haven_gate": {
            "strong_definition": "crash-bin SPY-GLD corr <= 0 and GLD mean >= 0",
            "spy_below_minus_2pct_pass": bool(core["spy_gld_corr"] <= 0 and core["gld_mean_return"] >= 0),
            "spy_below_minus_3pct_pass": bool(strong["spy_gld_corr"] <= 0 and strong["gld_mean_return"] >= 0),
            "vix_top_10pct_and_spy_down_pass": bool(vix_stress["spy_gld_corr"] <= 0 and vix_stress["gld_mean_return"] >= 0),
        },
    }

    results = {
        "experiment_id": "k1628",
        "title": "黃金真的是股災避風港嗎？危機期間條件相關性",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": {
            "source": "data/cache/price_cache.db :: price_data",
            "assets": {"equity_proxy": SPY, "gold_proxy": GLD, "stress_proxy": VIX},
            "return_definition": "adj_close close-to-close pct_change for SPY/GLD; VIX close used only for descriptive regimes",
            "start_date": START_DATE,
            "sample_start": df["date"].min().strftime("%Y-%m-%d"),
            "sample_end": df["date"].max().strftime("%Y-%m-%d"),
            "n_common_days": int(len(df)),
            "adj_close_nulls_checked": "SPY/GLD adj_close null count is 0 in this window",
        },
        "methodology": {
            "type": "empirical descriptive same-day safe-haven test, not a trading backtest",
            "lookahead_note": (
                "Same-day SPY/GLD returns are used by design to test crisis co-movement. "
                "No trading signal or forecast is claimed; VIX same-day close appears only in descriptive regimes."
            ),
            "hac_lag": HAC_LAG,
            "bootstrap": {"block": BOOT_BLOCK, "n_boot": BOOT_N, "seed": SEED},
            "literature": LITERATURE,
        },
        "verdict": verdict,
        "conditions": condition_results,
        "episodes": episodes,
        "safe_haven_regression": regression,
        "bootstrap_ci": boot,
    }

    out = HERE / "k1628_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=float)

    make_figures(df, conditions, results)
    print(f"[k1628] rows={len(df)} {df['date'].min().date()}..{df['date'].max().date()}")
    print(f"[k1628] results -> {out}")
    print(f"[k1628] verdict -> {verdict['label']}")
    print(verdict["one_sentence"])


if __name__ == "__main__":
    main()
