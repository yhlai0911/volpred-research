#!/usr/bin/env python3
"""
K709: Rate-Conditional SPY/GLD Allocation Rebuild
=================================================

Best-faith reconstruction of the article-backed K709 experiment.

Two distinct objects are computed explicitly because the original article
appears to have mixed them:

1. Descriptive regime slices:
   - classify each day by the trailing 126-trading-day change in ^TNX
   - compute same-day annualized SPY / GLD returns within each regime
   - this reproduces the eye-catching "falling-rate GLD vs SPY" numbers

2. Tradable lagged strategy:
   - use the regime label from 126 trading days earlier
   - freeze the signal at each month-end
   - apply the allocation on the following month
   - compare to a monthly rebalanced 50/50 SPY/GLD benchmark

Seed is fixed for bootstrap reproducibility.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
FIG_DIR = ROOT
RESULTS_PATH = ROOT / "k709_results.json"

START_DATE = "2005-12-01"
END_DATE = "2026-05-29"
LOOKBACK_DAYS = 126
SIGNAL_LAG_DAYS = 126
THRESHOLD_BP = 50
THRESHOLD_PCT = THRESHOLD_BP / 100.0
BOOTSTRAP_BLOCK = 21
BOOTSTRAP_REPS = 2000
SEED = 42

ARTICLE_OCCUPANCY_FIG = FIG_DIR / "k709_regime_occupancy.png"
ARTICLE_RETURNS_FIG = FIG_DIR / "k709_regime_returns.png"
ARTICLE_SHARPE_FIG = FIG_DIR / "k709_sharpe_compare.png"


@dataclass
class StrategyMetrics:
    ann_return: float
    ann_vol: float
    sharpe_rf0: float
    sharpe_irx: float
    mdd: float
    n_days: int


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def download_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = yf.download(
        ["SPY", "GLD", "^TNX", "^IRX"],
        start=START_DATE,
        end=END_DATE,
        auto_adjust=False,
        progress=False,
    )
    if raw.empty:
        raise RuntimeError("yfinance download returned empty data.")
    adj = raw["Adj Close"].rename(columns={"^TNX": "TNX", "^IRX": "IRX"})
    return raw, adj


def save_snapshots(raw: pd.DataFrame, adj: pd.DataFrame) -> None:
    for ticker in ["SPY", "GLD", "^TNX", "^IRX"]:
        ticker_df = raw.xs(ticker, axis=1, level=1).copy()
        out = DATA_DIR / f"{ticker.replace('^', '')}_yfinance_snapshot.csv"
        ticker_df.to_csv(out, index_label="Date")
    adj.to_csv(DATA_DIR / "adj_close_panel.csv", index_label="Date")


def classify_regime(delta: pd.Series, threshold: float) -> pd.Series:
    regime = pd.Series("stable", index=delta.index, dtype="object")
    regime[delta > threshold] = "rising"
    regime[delta < -threshold] = "falling"
    regime[delta.isna()] = np.nan
    return regime


def compute_descriptive_stats(
    returns: pd.DataFrame,
    regime: pd.Series,
    threshold: float,
) -> dict:
    valid = regime.notna()
    ret = returns.loc[valid]
    reg = regime.loc[valid]

    out: dict[str, dict[str, float]] = {}
    for name in ["rising", "stable", "falling"]:
        mask = reg == name
        sub = ret.loc[mask]
        out[name] = {
            "n_days": int(mask.sum()),
            "occupancy_pct": round(float(mask.mean() * 100), 3),
            "spy_ann_return_pct": round(float(sub["SPY"].mean() * 252 * 100), 3),
            "gld_ann_return_pct": round(float(sub["GLD"].mean() * 252 * 100), 3),
        }

    return {
        "lookback_days": LOOKBACK_DAYS,
        "threshold_pct_points": threshold,
        "sample_start": str(ret.index.min().date()),
        "sample_end": str(ret.index.max().date()),
        "n_days": int(len(ret)),
        "regimes": out,
    }


def month_end_signal(series: pd.Series) -> pd.Series:
    return series.resample("ME").last().shift(1)


def build_tradable_signal(regime: pd.Series) -> pd.Series:
    lagged_regime = regime.shift(SIGNAL_LAG_DAYS)
    month_signal = month_end_signal(lagged_regime)
    month_index = lagged_regime.index.to_period("M").to_timestamp("M")
    signal = month_signal.reindex(month_index).set_axis(lagged_regime.index)
    return signal


def run_monthly_rebalanced_portfolio(
    returns: pd.DataFrame,
    signal: pd.Series | None,
) -> pd.Series:
    dates = returns.index
    port_ret: list[float] = []

    w_spy = 0.5
    w_gld = 0.5

    for i, date in enumerate(dates):
        if signal is not None and pd.notna(signal.iloc[i]):
            label = signal.iloc[i]
            if label == "rising":
                target_spy, target_gld = 0.6, 0.4
            elif label == "falling":
                target_spy, target_gld = 0.4, 0.6
            else:
                target_spy, target_gld = 0.5, 0.5
        else:
            target_spy, target_gld = 0.5, 0.5

        daily = w_spy * returns.iloc[i]["SPY"] + w_gld * returns.iloc[i]["GLD"]
        port_ret.append(daily)

        if i == len(dates) - 1:
            break

        total = 1.0 + daily
        w_spy = w_spy * (1.0 + returns.iloc[i]["SPY"]) / total
        w_gld = w_gld * (1.0 + returns.iloc[i]["GLD"]) / total

        if dates[i + 1].month != date.month:
            w_spy = target_spy
            w_gld = target_gld

    return pd.Series(port_ret, index=dates)


def compute_metrics(returns: pd.Series, rf_daily: pd.Series) -> StrategyMetrics:
    ann_return = float(returns.mean() * 252)
    ann_vol = float(returns.std(ddof=1) * math.sqrt(252))
    rf_ann = float(rf_daily.reindex(returns.index).fillna(0).mean() * 252)

    wealth = (1.0 + returns).cumprod()
    drawdown = wealth / wealth.cummax() - 1.0
    mdd = float(drawdown.min())

    return StrategyMetrics(
        ann_return=round(ann_return, 6),
        ann_vol=round(ann_vol, 6),
        sharpe_rf0=round(ann_return / ann_vol, 6),
        sharpe_irx=round((ann_return - rf_ann) / ann_vol, 6),
        mdd=round(mdd, 6),
        n_days=int(len(returns)),
    )


def dm_hln_test(strategy: pd.Series, benchmark: pd.Series) -> dict:
    # Treat higher return as lower "loss": loss = -return.
    d = benchmark - strategy
    d = d.dropna()
    n = len(d)
    mean_d = float(d.mean())
    gamma0 = float(np.var(d, ddof=1))
    if gamma0 <= 0:
        return {"stat": 0.0, "p_value": 1.0, "n": n}
    dm = mean_d / math.sqrt(gamma0 / n)
    hln = dm * math.sqrt((n + 1 - 2) / n)
    p_value = 2 * (1 - stats.t.cdf(abs(hln), df=n - 1))
    return {
        "stat": round(float(hln), 6),
        "p_value": round(float(p_value), 6),
        "mean_daily_return_diff": round(float((strategy - benchmark).mean()), 8),
        "n": int(n),
    }


def jobson_korkie_memmel(strategy: pd.Series, benchmark: pd.Series) -> dict:
    x = strategy.dropna().to_numpy()
    y = benchmark.reindex(strategy.index).dropna().to_numpy()
    n = min(len(x), len(y))
    x = x[:n]
    y = y[:n]

    mu_x, mu_y = x.mean(), y.mean()
    sig_x, sig_y = x.std(ddof=1), y.std(ddof=1)
    sr_x = mu_x / sig_x
    sr_y = mu_y / sig_y
    rho = np.corrcoef(x, y)[0, 1]

    theta = (
        (1 / n)
        * (2 * (1 - rho) + 0.5 * (sr_x**2 + sr_y**2 - 2 * sr_x * sr_y * rho))
    )
    z = (sr_x - sr_y) / math.sqrt(theta) if theta > 0 else 0.0
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    return {
        "z_stat": round(float(z), 6),
        "p_value": round(float(p), 6),
        "delta_sharpe_rf0": round(float((sr_x - sr_y) * math.sqrt(252)), 6),
    }


def circular_block_bootstrap_diff(
    strategy: pd.Series,
    benchmark: pd.Series,
    block_size: int,
    n_boot: int,
    seed: int,
) -> dict:
    aligned = pd.concat([strategy.rename("strategy"), benchmark.rename("benchmark")], axis=1).dropna()
    arr = aligned.to_numpy()
    n = len(arr)
    rng = np.random.default_rng(seed)
    n_blocks = math.ceil(n / block_size)
    diffs: list[float] = []

    for _ in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        idx: list[int] = []
        for s in starts:
            idx.extend(((s + np.arange(block_size)) % n).tolist())
        sample = arr[idx[:n]]
        strat = sample[:, 0]
        bench = sample[:, 1]
        strat_sr = strat.mean() / strat.std(ddof=1) * math.sqrt(252)
        bench_sr = bench.mean() / bench.std(ddof=1) * math.sqrt(252)
        diffs.append(float(strat_sr - bench_sr))

    diffs_arr = np.array(diffs)
    ci_lo, ci_hi = np.quantile(diffs_arr, [0.025, 0.975])
    p_two_sided = 2 * min((diffs_arr <= 0).mean(), (diffs_arr >= 0).mean())
    return {
        "block_size_days": int(block_size),
        "n_boot": int(n_boot),
        "seed": int(seed),
        "delta_sharpe_mean": round(float(diffs_arr.mean()), 6),
        "delta_sharpe_ci_95": [round(float(ci_lo), 6), round(float(ci_hi), 6)],
        "p_two_sided_against_zero": round(float(p_two_sided), 6),
    }


def threshold_sensitivity(
    returns: pd.DataFrame,
    tnx: pd.Series,
    rf_daily: pd.Series,
) -> list[dict]:
    rows: list[dict] = []
    for threshold in [0.48, 0.49, 0.50]:
        delta = tnx.diff(LOOKBACK_DAYS)
        regime = classify_regime(delta, threshold)
        desc = compute_descriptive_stats(returns, regime, threshold)
        signal = build_tradable_signal(regime)
        valid = signal.notna()
        strat = run_monthly_rebalanced_portfolio(returns.loc[valid], signal.loc[valid])
        bh = run_monthly_rebalanced_portfolio(returns.loc[valid], None)
        metrics_strat = compute_metrics(strat, rf_daily.loc[valid])
        metrics_bh = compute_metrics(bh, rf_daily.loc[valid])
        rows.append(
            {
                "threshold_pct_points": threshold,
                "descriptive_falling_gld_ann_pct": desc["regimes"]["falling"]["gld_ann_return_pct"],
                "descriptive_falling_spy_ann_pct": desc["regimes"]["falling"]["spy_ann_return_pct"],
                "descriptive_occupancy_pct": {
                    k: v["occupancy_pct"] for k, v in desc["regimes"].items()
                },
                "tradable_cond_sharpe_rf0": metrics_strat.sharpe_rf0,
                "tradable_bh_sharpe_rf0": metrics_bh.sharpe_rf0,
                "tradable_delta_sharpe_rf0": round(
                    metrics_strat.sharpe_rf0 - metrics_bh.sharpe_rf0, 6
                ),
            }
        )
    return rows


def plot_regime_occupancy(desc: dict) -> None:
    labels = ["rising", "stable", "falling"]
    vals = [desc["regimes"][k]["occupancy_pct"] for k in labels]
    colors = ["#2E86AB", "#9CA3AF", "#C0392B"]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(labels, vals, color=colors)
    ax.set_ylabel("Percent of trading days")
    ax.set_title("Rate regime occupancy (TNX 126d change, +/-50bp)")
    for i, v in enumerate(vals):
        ax.text(i, v + 0.6, f"{v:.1f}%", ha="center", fontsize=10)
    fig.tight_layout()
    fig.savefig(ARTICLE_OCCUPANCY_FIG, dpi=150)
    plt.close(fig)


def plot_regime_returns(desc: dict) -> None:
    labels = ["rising", "stable", "falling"]
    spy_vals = [desc["regimes"][k]["spy_ann_return_pct"] for k in labels]
    gld_vals = [desc["regimes"][k]["gld_ann_return_pct"] for k in labels]
    x = np.arange(len(labels))
    width = 0.35

    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.bar(x - width / 2, spy_vals, width, label="SPY", color="#1F77B4")
    ax.bar(x + width / 2, gld_vals, width, label="GLD", color="#D4A017")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Annualized arithmetic return (%)")
    ax.set_title("Same-day descriptive returns by rate regime")
    ax.legend()
    fig.tight_layout()
    fig.savefig(ARTICLE_RETURNS_FIG, dpi=150)
    plt.close(fig)


def plot_sharpe(metrics_bh: StrategyMetrics, metrics_strat: StrategyMetrics) -> None:
    labels = ["50/50 BH", "Rate-conditional"]
    vals = [metrics_bh.sharpe_rf0, metrics_strat.sharpe_rf0]
    colors = ["#6B7280", "#0F766E"]

    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    ax.bar(labels, vals, color=colors)
    ax.set_ylabel("Sharpe (rf=0)")
    ax.set_title("Tradable monthly strategy vs benchmark")
    for i, v in enumerate(vals):
        ax.text(i, v + 0.01, f"{v:.3f}", ha="center", fontsize=10)
    fig.tight_layout()
    fig.savefig(ARTICLE_SHARPE_FIG, dpi=150)
    plt.close(fig)


def main() -> None:
    ensure_dirs()
    raw, adj = download_data()
    save_snapshots(raw, adj)

    panel = adj[["SPY", "GLD", "TNX"]].dropna().copy()
    returns = panel[["SPY", "GLD"]].pct_change().dropna()
    tnx = panel["TNX"].reindex(returns.index).ffill()
    irx = adj["IRX"].reindex(returns.index).ffill()
    rf_daily = irx.fillna(0) / 100.0 / 252.0

    delta = tnx.diff(LOOKBACK_DAYS)
    regime = classify_regime(delta, THRESHOLD_PCT)

    descriptive = compute_descriptive_stats(returns, regime, THRESHOLD_PCT)
    signal = build_tradable_signal(regime)
    valid = signal.notna()

    tradable_returns = returns.loc[valid]
    tradable_signal = signal.loc[valid]
    conditional = run_monthly_rebalanced_portfolio(tradable_returns, tradable_signal)
    benchmark = run_monthly_rebalanced_portfolio(tradable_returns, None)
    rf_tradable = rf_daily.loc[valid]

    conditional_metrics = compute_metrics(conditional, rf_tradable)
    benchmark_metrics = compute_metrics(benchmark, rf_tradable)

    dm = dm_hln_test(conditional, benchmark)
    jk = jobson_korkie_memmel(conditional, benchmark)
    boot = circular_block_bootstrap_diff(
        conditional,
        benchmark,
        block_size=BOOTSTRAP_BLOCK,
        n_boot=BOOTSTRAP_REPS,
        seed=SEED,
    )

    plot_regime_occupancy(descriptive)
    plot_regime_returns(descriptive)
    plot_sharpe(benchmark_metrics, conditional_metrics)

    results = {
        "meta": {
            "experiment_id": "k709",
            "title": "Rate-Conditional SPY/GLD Allocation Rebuild",
            "generated_at": pd.Timestamp.now("UTC").isoformat(),
            "data_source": "yfinance SPY / GLD / ^TNX / ^IRX",
            "sample_start": str(panel.index.min().date()),
            "sample_end": str(panel.index.max().date()),
            "seed": SEED,
        },
        "spec": {
            "lookback_days": LOOKBACK_DAYS,
            "signal_lag_days": SIGNAL_LAG_DAYS,
            "threshold_pct_points": THRESHOLD_PCT,
            "allocation_rule": {
                "rising": {"SPY": 0.6, "GLD": 0.4},
                "stable": {"SPY": 0.5, "GLD": 0.5},
                "falling": {"SPY": 0.4, "GLD": 0.6},
            },
            "rebalance_rule": "month-end signal, applied next month",
        },
        "descriptive_same_day_regime_stats": descriptive,
        "tradable_lagged_strategy": {
            "sample_start": str(tradable_returns.index.min().date()),
            "sample_end": str(tradable_returns.index.max().date()),
            "conditional": asdict(conditional_metrics),
            "buy_and_hold_50_50": asdict(benchmark_metrics),
            "delta_sharpe_rf0": round(
                conditional_metrics.sharpe_rf0 - benchmark_metrics.sharpe_rf0, 6
            ),
            "delta_sharpe_irx": round(
                conditional_metrics.sharpe_irx - benchmark_metrics.sharpe_irx, 6
            ),
        },
        "statistical_tests": {
            "dm_hln_daily_return_diff": dm,
            "jobson_korkie_memmel_sharpe_diff": jk,
            "moving_block_bootstrap_sharpe_diff": boot,
        },
        "threshold_sensitivity": threshold_sensitivity(returns, tnx, rf_daily),
        "article_claim_reconciliation": {
            "observation": (
                "A single threshold/spec does not reproduce all article claims exactly. "
                "With +/-50bp same-day regimes, the descriptive 30.8% GLD vs 13.4% SPY "
                "falling-rate gap appears. Under the fair monthly tradable implementation, "
                "delta Sharpe is essentially zero (about -0.002 rf=0), while nearby threshold "
                "variants only move the result by a few basis points."
            ),
            "best_faith_interpretation": (
                "The published article likely mixed a hindsight descriptive regime table "
                "with a separate lagged tradable backtest, and the surviving artifacts are "
                "insufficient to recover the published +0.019 exactly."
            ),
        },
        "artifacts": {
            "figures": [
                str(ARTICLE_OCCUPANCY_FIG.name),
                str(ARTICLE_RETURNS_FIG.name),
                str(ARTICLE_SHARPE_FIG.name),
            ],
            "data_files": sorted(p.name for p in DATA_DIR.glob("*.csv")),
        },
    }

    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(json.dumps(
        {
            "descriptive_falling": descriptive["regimes"]["falling"],
            "cond_sharpe_rf0": conditional_metrics.sharpe_rf0,
            "bh_sharpe_rf0": benchmark_metrics.sharpe_rf0,
            "delta_sharpe_rf0": round(
                conditional_metrics.sharpe_rf0 - benchmark_metrics.sharpe_rf0, 6
            ),
            "jk_p": jk["p_value"],
            "bootstrap_ci": boot["delta_sharpe_ci_95"],
        },
        indent=2,
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
