#!/usr/bin/env python3
"""K1475: 11-signal momentum composite vs pure price momentum.

Honest-proxy design:
- The queued idea references a 2025 multidimensional-momentum theme, but the
  exact paper-grade equity panel is not pinned locally in this repo.
- Sandbox networking also blocks fresh Yahoo downloads.
- This experiment therefore uses a locally cached ETF panel from
  `experiments/k1090b/data/` as the canonical reproducible proxy.

Question:
- Can an equal-weight 11-signal composite improve tail outcomes versus a
  plain 12_1 price-momentum selector, holding the asset universe, rebalancing
  schedule, and timing convention fixed?

Timing discipline:
- Signals are computed at month-end `t` using data available no later than `t`.
- Positions are entered from the next trading day after `t`.
- No same-day signal is multiplied by same-day return.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("MPLCONFIGDIR", str(HERE / ".mplconfig"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm

SEED = 42
np.random.seed(SEED)

DATA_DIR = Path("experiments/k1090b/data")
RESULTS_PATH = HERE / "k1475_results.json"
FIG_EQUITY = HERE / "k1475_equity_drawdown.png"
FIG_METRICS = HERE / "k1475_metrics.png"

UNIVERSE = [
    "SPY",
    "QQQ",
    "IWM",
    "EEM",
    "EWJ",
    "FXI",
    "VGK",
    "GLD",
    "TLT",
    "USO",
    "SLV",
]
SAFE_ASSET = "IEF"
VIX_TICKER = "VIX"
TOP_N = 3
TX_COST_BPS = 10
START_DATE = "2018-01-02"
END_DATE = "2024-12-30"


@dataclass
class StrategyResult:
    name: str
    daily_returns: pd.Series
    monthly_returns: pd.Series
    weights: pd.DataFrame
    turnover: pd.Series
    selections: dict[str, list[str]]


def load_csv_price(ticker: str) -> pd.DataFrame:
    path = DATA_DIR / f"{ticker}.csv"
    df = pd.read_csv(path, parse_dates=["Date"])
    df = df.set_index("Date").sort_index()
    return df.loc[START_DATE:END_DATE].copy()


def build_panel() -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    closes = {}
    dollars = {}
    for ticker in UNIVERSE + [SAFE_ASSET]:
        df = load_csv_price(ticker)
        closes[ticker] = df["Close"].astype(float)
        dollars[ticker] = (df["Close"].astype(float) * df["Volume"].astype(float)).replace(0, np.nan)

    price = pd.DataFrame(closes).dropna()
    dollar_vol = pd.DataFrame(dollars).reindex(price.index)

    vix = load_csv_price(VIX_TICKER)["Close"].astype(float).reindex(price.index).ffill()
    return price, dollar_vol, vix


def percentile_rank_row(row: pd.Series) -> pd.Series:
    valid = row.dropna()
    if valid.empty:
        return pd.Series(np.nan, index=row.index)
    ranks = valid.rank(method="average", pct=True)
    out = pd.Series(np.nan, index=row.index, dtype=float)
    out.loc[valid.index] = ranks
    return out


def compute_signal_frames(price: pd.DataFrame, dollar_vol: pd.DataFrame) -> dict[str, pd.DataFrame]:
    ret = price.pct_change()

    ret_21 = price.pct_change(21)
    ret_63 = price.pct_change(63)
    ret_126 = price.pct_change(126)
    mom_12_1 = price.shift(21) / price.shift(252) - 1.0

    sharpe_21 = ret.rolling(21).mean() / ret.rolling(21).std()
    sharpe_63 = ret.rolling(63).mean() / ret.rolling(63).std()
    sharpe_126 = ret.rolling(126).mean() / ret.rolling(126).std()

    dist_52w_high = price / price.rolling(252).max() - 1.0
    up_day_frac_63 = ret.gt(0).rolling(63).mean()
    dv_trend_21_126 = np.log(dollar_vol.rolling(21).mean() / dollar_vol.rolling(126).mean())
    downside_vol_63 = -np.sqrt(ret.clip(upper=0).pow(2).rolling(63).mean() * 252.0)

    raw = {
        "ret_21": ret_21,
        "ret_63": ret_63,
        "ret_126": ret_126,
        "mom_12_1": mom_12_1,
        "sharpe_21": sharpe_21,
        "sharpe_63": sharpe_63,
        "sharpe_126": sharpe_126,
        "dist_52w_high": dist_52w_high,
        "up_day_frac_63": up_day_frac_63,
        "dv_trend_21_126": dv_trend_21_126,
        "downside_vol_63": downside_vol_63,
    }
    scored = {name: frame.apply(percentile_rank_row, axis=1) for name, frame in raw.items()}
    return scored


def month_end_dates(index: pd.Index) -> list[pd.Timestamp]:
    return list(index.to_series().groupby(index.to_period("M")).max())


def apply_selection(scores: pd.Series, positive_filter: pd.Series | None) -> tuple[list[str], pd.Series]:
    eligible = scores.dropna().sort_values(ascending=False)
    if positive_filter is not None:
        mask = positive_filter.reindex(eligible.index).fillna(False)
        eligible = eligible[mask]

    picks = list(eligible.head(TOP_N).index)
    weights = pd.Series(0.0, index=UNIVERSE + [SAFE_ASSET], dtype=float)
    if picks:
        w = 1.0 / TOP_N
        for ticker in picks:
            weights[ticker] = w
        weights[SAFE_ASSET] = max(0.0, 1.0 - weights.drop(SAFE_ASSET).sum())
    else:
        weights[SAFE_ASSET] = 1.0
    return picks, weights


def run_strategy(
    name: str,
    daily_ret: pd.DataFrame,
    rebal_dates: list[pd.Timestamp],
    composite_score: pd.DataFrame | None = None,
    baseline_score: pd.DataFrame | None = None,
    positive_filter: pd.DataFrame | None = None,
) -> StrategyResult:
    port = pd.Series(0.0, index=daily_ret.index, dtype=float)
    turnover = pd.Series(0.0, index=daily_ret.index, dtype=float)
    weights_df = pd.DataFrame(0.0, index=daily_ret.index, columns=UNIVERSE + [SAFE_ASSET], dtype=float)
    selections: dict[str, list[str]] = {}

    prev_weights = pd.Series(0.0, index=UNIVERSE + [SAFE_ASSET], dtype=float)

    for i, rebal_date in enumerate(rebal_dates[:-1]):
        next_rebal = rebal_dates[i + 1]
        start_loc = daily_ret.index.get_loc(rebal_date) + 1
        end_loc = daily_ret.index.get_loc(next_rebal)
        if start_loc > end_loc:
            continue
        hold_days = daily_ret.index[start_loc : end_loc + 1]

        if composite_score is not None:
            score_row = composite_score.loc[rebal_date]
        else:
            score_row = baseline_score.loc[rebal_date]
        pf = positive_filter.loc[rebal_date] if positive_filter is not None else None
        picks, new_weights = apply_selection(score_row, pf)
        selections[str(rebal_date.date())] = picks

        trade_cost = (new_weights - prev_weights).abs().sum() * (TX_COST_BPS / 10000.0)
        weights_df.loc[hold_days] = new_weights.values

        daily_slice = daily_ret.loc[hold_days, UNIVERSE + [SAFE_ASSET]]
        strategy_returns = daily_slice.mul(new_weights, axis=1).sum(axis=1)
        if len(strategy_returns) > 0:
            strategy_returns.iloc[0] -= trade_cost
            turnover.iloc[start_loc] = float((new_weights - prev_weights).abs().sum())
        port.loc[hold_days] = strategy_returns.values
        prev_weights = new_weights

    monthly = (1.0 + port).groupby(port.index.to_period("M")).prod() - 1.0
    monthly.index = monthly.index.to_timestamp("M")
    return StrategyResult(name, port, monthly, weights_df, turnover, selections)


def annualized_return(r: pd.Series) -> float:
    r = r.dropna()
    if r.empty:
        return float("nan")
    return float((1.0 + r).prod() ** (252.0 / len(r)) - 1.0)


def max_drawdown(r: pd.Series) -> float:
    wealth = (1.0 + r.fillna(0.0)).cumprod()
    dd = wealth / wealth.cummax() - 1.0
    return float(dd.min())


def harvey_t(r: pd.Series) -> float:
    r = r.dropna()
    if len(r) < 2 or r.std(ddof=1) == 0:
        return float("nan")
    return float(np.sqrt(len(r)) * r.mean() / r.std(ddof=1))


def newey_west_mean_t(monthly_r: pd.Series, lags: int = 3) -> float:
    y = monthly_r.dropna().values
    if len(y) < 12:
        return float("nan")
    X = np.ones((len(y), 1))
    res = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return float(res.tvalues[0])


def compute_metrics(result: StrategyResult) -> dict:
    r = result.daily_returns.dropna()
    m = result.monthly_returns.dropna()
    ann_ret = annualized_return(r)
    ann_vol = float(r.std(ddof=1) * np.sqrt(252.0))
    downside = r[r < 0].std(ddof=1) * np.sqrt(252.0)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else float("nan")
    sortino = ann_ret / downside if downside and not np.isnan(downside) else float("nan")
    mdd = max_drawdown(r)
    calmar = ann_ret / abs(mdd) if mdd < 0 else float("nan")
    turnover_ann = float(result.turnover.sum() / max(len(r) / 252.0, 1e-9))
    return {
        "n_days": int(len(r)),
        "n_months": int(len(m)),
        "start": str(r.index[0].date()),
        "end": str(r.index[-1].date()),
        "annual_return": round(ann_ret, 6),
        "annual_vol": round(ann_vol, 6),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "max_drawdown": round(mdd, 6),
        "calmar": round(calmar, 4),
        "harvey_t_daily": round(harvey_t(r), 4),
        "nw_t_monthly_mean": round(newey_west_mean_t(m), 4),
        "annual_turnover": round(turnover_ann, 4),
        "worst_day": round(float(r.min()), 6),
        "worst_month": round(float(m.min()), 6),
        "best_month": round(float(m.max()), 6),
        "avg_positions": round(float((result.weights[UNIVERSE] > 0).sum(axis=1).mean()), 4),
    }


def block_bootstrap_compare(
    base_monthly: pd.Series,
    challenger_monthly: pd.Series,
    block_size: int = 3,
    n_boot: int = 5000,
) -> dict:
    aligned = pd.concat(
        {"base": base_monthly, "challenger": challenger_monthly},
        axis=1,
    ).dropna()
    arr = aligned.values
    n = len(arr)
    rng = np.random.default_rng(SEED)

    sharpe_diff = []
    cagr_diff = []
    mdd_diff = []
    mean_diff = []

    def _mdd_from_ret(x: np.ndarray) -> float:
        wealth = np.cumprod(1.0 + x)
        dd = wealth / np.maximum.accumulate(wealth) - 1.0
        return float(dd.min())

    for _ in range(n_boot):
        idx = []
        while len(idx) < n:
            start = int(rng.integers(0, n))
            block = [(start + j) % n for j in range(block_size)]
            idx.extend(block)
        idx = idx[:n]
        sample = arr[idx]
        b = sample[:, 0]
        c = sample[:, 1]
        b_ann = (1.0 + b).prod() ** (12.0 / n) - 1.0
        c_ann = (1.0 + c).prod() ** (12.0 / n) - 1.0
        b_vol = np.std(b, ddof=1) * np.sqrt(12.0)
        c_vol = np.std(c, ddof=1) * np.sqrt(12.0)
        b_sharpe = b_ann / b_vol if b_vol > 0 else np.nan
        c_sharpe = c_ann / c_vol if c_vol > 0 else np.nan
        sharpe_diff.append(c_sharpe - b_sharpe)
        cagr_diff.append(c_ann - b_ann)
        mdd_diff.append(_mdd_from_ret(c) - _mdd_from_ret(b))
        mean_diff.append(c.mean() - b.mean())

    sharpe_arr = np.array(sharpe_diff)
    cagr_arr = np.array(cagr_diff)
    mdd_arr = np.array(mdd_diff)
    mean_arr = np.array(mean_diff)
    return {
        "n_months": int(n),
        "block_size_months": int(block_size),
        "n_boot": int(n_boot),
        "challenger_sharpe_gt_base_prob": round(float(np.nanmean(sharpe_arr > 0)), 4),
        "challenger_cagr_gt_base_prob": round(float(np.nanmean(cagr_arr > 0)), 4),
        "challenger_mdd_better_prob": round(float(np.nanmean(mdd_arr > 0)), 4),
        "mean_monthly_diff_avg": round(float(np.nanmean(mean_arr)), 6),
        "sharpe_diff_avg": round(float(np.nanmean(sharpe_arr)), 4),
        "mdd_diff_avg": round(float(np.nanmean(mdd_arr)), 6),
        "mdd_diff_p5_p50_p95": [
            round(float(np.nanpercentile(mdd_arr, q)), 6) for q in [5, 50, 95]
        ],
    }


def crash_windows(series: pd.Series) -> dict[str, dict]:
    windows = {
        "q4_2018": ("2018-09-20", "2018-12-24"),
        "covid_2020": ("2020-02-19", "2020-03-23"),
        "rate_shock_2022": ("2022-01-03", "2022-10-14"),
    }
    out = {}
    for name, (start, end) in windows.items():
        sub = series.loc[start:end]
        wealth = (1.0 + sub).prod() - 1.0 if not sub.empty else np.nan
        out[name] = {
            "n_days": int(len(sub)),
            "total_return": round(float(wealth), 6) if not np.isnan(wealth) else None,
            "worst_day": round(float(sub.min()), 6) if not sub.empty else None,
            "max_drawdown": round(max_drawdown(sub), 6) if not sub.empty else None,
        }
    return out


def subperiod_metrics(series: pd.Series) -> dict[str, dict]:
    periods = {
        "2019_2019": ("2019-01-01", "2019-12-31"),
        "2020_2021": ("2020-01-01", "2021-12-31"),
        "2022_2024": ("2022-01-01", "2024-12-30"),
    }
    out = {}
    for name, (start, end) in periods.items():
        sub = series.loc[start:end]
        if sub.empty:
            continue
        out[name] = {
            "annual_return": round(annualized_return(sub), 6),
            "annual_vol": round(float(sub.std(ddof=1) * np.sqrt(252.0)), 6),
            "sharpe": round(annualized_return(sub) / (sub.std(ddof=1) * np.sqrt(252.0)), 4),
            "max_drawdown": round(max_drawdown(sub), 6),
        }
    return out


def make_figures(base: StrategyResult, challenger: StrategyResult, metrics: dict) -> None:
    base_wealth = (1.0 + base.daily_returns.fillna(0.0)).cumprod()
    chal_wealth = (1.0 + challenger.daily_returns.fillna(0.0)).cumprod()
    base_dd = base_wealth / base_wealth.cummax() - 1.0
    chal_dd = chal_wealth / chal_wealth.cummax() - 1.0
    x = base_wealth.index.to_pydatetime()

    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    axes[0].plot(x, base_wealth.to_numpy(), label="Pure 12_1 momentum", lw=2)
    axes[0].plot(x, chal_wealth.to_numpy(), label="11-signal composite", lw=2)
    axes[0].set_title("Equity Curves")
    axes[0].legend()
    axes[0].grid(alpha=0.3)

    axes[1].plot(x, base_dd.to_numpy(), label="Pure 12_1 momentum", lw=2)
    axes[1].plot(x, chal_dd.to_numpy(), label="11-signal composite", lw=2)
    axes[1].set_title("Drawdowns")
    axes[1].grid(alpha=0.3)
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(FIG_EQUITY, dpi=180)
    plt.close(fig)

    metric_names = ["annual_return", "sharpe", "max_drawdown", "annual_turnover"]
    base_vals = [metrics["pure_price_momentum"][k] for k in metric_names]
    chal_vals = [metrics["signal_composite_11"][k] for k in metric_names]
    x = np.arange(len(metric_names))
    width = 0.35
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.bar(x - width / 2, base_vals, width, label="Pure 12_1")
    ax.bar(x + width / 2, chal_vals, width, label="Composite-11")
    ax.set_xticks(x)
    ax.set_xticklabels(metric_names)
    ax.set_title("Key Metrics")
    ax.grid(axis="y", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG_METRICS, dpi=180)
    plt.close(fig)


def main() -> None:
    price, dollar_vol, _vix = build_panel()
    returns = price.pct_change().dropna()
    signal_frames = compute_signal_frames(price[UNIVERSE], dollar_vol[UNIVERSE])
    signal_dates = month_end_dates(returns.index)

    composite_score = sum(signal_frames.values()) / len(signal_frames)
    baseline_score = signal_frames["mom_12_1"].copy()
    positive_filter = signal_frames["mom_12_1"].apply(lambda x: x > 0)

    warmup_ready = composite_score.dropna(how="all").index.min()
    rebal_dates = [d for d in signal_dates if d >= warmup_ready]
    analysis_returns = returns.loc[rebal_dates[0]:, UNIVERSE + [SAFE_ASSET]].copy()
    rebal_dates = [d for d in rebal_dates if d in analysis_returns.index]

    base = run_strategy(
        name="pure_price_momentum",
        daily_ret=analysis_returns,
        rebal_dates=rebal_dates,
        baseline_score=baseline_score.reindex(analysis_returns.index),
        positive_filter=positive_filter.reindex(analysis_returns.index),
    )
    challenger = run_strategy(
        name="signal_composite_11",
        daily_ret=analysis_returns,
        rebal_dates=rebal_dates,
        composite_score=composite_score.reindex(analysis_returns.index),
        positive_filter=positive_filter.reindex(analysis_returns.index),
    )

    metrics = {
        "pure_price_momentum": compute_metrics(base),
        "signal_composite_11": compute_metrics(challenger),
    }
    bootstrap = block_bootstrap_compare(base.monthly_returns, challenger.monthly_returns)

    signal_definitions = {
        "ret_21": "1-month total return",
        "ret_63": "3-month total return",
        "ret_126": "6-month total return",
        "mom_12_1": "12_1 price momentum (t-252 to t-21)",
        "sharpe_21": "1-month daily mean/std",
        "sharpe_63": "3-month daily mean/std",
        "sharpe_126": "6-month daily mean/std",
        "dist_52w_high": "distance to trailing 52-week high",
        "up_day_frac_63": "share of positive days over past 63 sessions",
        "dv_trend_21_126": "log short-vs-long dollar-volume trend",
        "downside_vol_63": "negative annualized downside volatility over past 63 sessions",
    }

    selection_examples = {
        "pure_price_first_5": {k: v for k, v in list(base.selections.items())[:5]},
        "composite_first_5": {k: v for k, v in list(challenger.selections.items())[:5]},
    }

    results = {
        "experiment_id": "K1475",
        "title": "11-signal momentum composite vs pure price momentum",
        "run_timestamp": pd.Timestamp.utcnow().isoformat(),
        "seed": SEED,
        "data": {
            "source": "local cached CSV snapshots in experiments/k1090b/data",
            "sample_start": str(analysis_returns.index[0].date()),
            "sample_end": str(analysis_returns.index[-1].date()),
            "n_days": int(len(analysis_returns)),
            "n_rebalances": int(len(rebal_dates) - 1),
            "universe": UNIVERSE,
            "safe_asset": SAFE_ASSET,
            "frequency": "daily returns, monthly rebalance",
        },
        "methodology": {
            "top_n": TOP_N,
            "tx_cost_bps": TX_COST_BPS,
            "eligibility_rule": "asset must have positive 12_1 momentum at rebalance date; else leftover weight goes to IEF",
            "timing_rule": "signals at month-end t, positions held from next trading day to next rebalance",
            "signal_definitions": signal_definitions,
            "score_construction": "each signal converted to cross-sectional percentile rank; composite = equal-weight average of 11 ranks",
            "benchmark": "pure price momentum uses only the mom_12_1 signal under the same top-3 and eligibility rules",
        },
        "metrics": metrics,
        "bootstrap": bootstrap,
        "crash_windows": {
            "pure_price_momentum": crash_windows(base.daily_returns),
            "signal_composite_11": crash_windows(challenger.daily_returns),
        },
        "subperiods": {
            "pure_price_momentum": subperiod_metrics(base.daily_returns),
            "signal_composite_11": subperiod_metrics(challenger.daily_returns),
        },
        "selection_examples": selection_examples,
        "verdict": {},
    }

    base_mdd = metrics["pure_price_momentum"]["max_drawdown"]
    chal_mdd = metrics["signal_composite_11"]["max_drawdown"]
    base_sharpe = metrics["pure_price_momentum"]["sharpe"]
    chal_sharpe = metrics["signal_composite_11"]["sharpe"]
    results["verdict"] = {
        "tail_improves": bool(chal_mdd > base_mdd),
        "sharpe_improves": bool(chal_sharpe > base_sharpe),
        "bootstrap_mdd_better_prob_gt_60pct": bool(bootstrap["challenger_mdd_better_prob"] > 0.6),
        "summary": (
            "composite improves tail without sacrificing Sharpe"
            if chal_mdd > base_mdd and chal_sharpe >= base_sharpe
            else "composite does not deliver a clean tail-improvement win"
        ),
    }

    make_figures(base, challenger, metrics)
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(json.dumps(results["metrics"], indent=2, ensure_ascii=False))
    print(json.dumps(results["verdict"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
