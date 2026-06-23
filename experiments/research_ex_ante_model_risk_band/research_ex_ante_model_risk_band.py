#!/usr/bin/env python3
"""Ex-ante model-risk band for low-risk portfolio construction.

This experiment tests whether "low-risk/min-vol" implementation choices
produce materially different realized outcomes even when the signal family is
the same.  It deliberately studies construction model risk, not the existence
of low-volatility alpha.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import minimize
from scipy import stats
from sklearn.covariance import LedoitWolf

from volpred.stats.model_evaluation import dm_test, strategy_dm_test


EXP_ID = "research_ex_ante_model_risk_band"
SEED = 20260624
BOOTSTRAP_REPS = 1000
BOOTSTRAP_BLOCK = 21
TRADING_DAYS = 252
OOS_START = pd.Timestamp("2012-01-01")

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
FIG_DIR = ROOT / "figures"
RESULTS_PATH = ROOT / f"{EXP_ID}_results.json"

UNIVERSE = [
    "XLB",  # materials
    "XLE",  # energy
    "XLF",  # financials
    "XLI",  # industrials
    "XLK",  # technology
    "XLP",  # consumer staples
    "XLU",  # utilities
    "XLV",  # health care
    "XLY",  # consumer discretionary
    "IYR",  # real estate proxy; longer history than XLRE
]

BENCHMARKS = ["SPY", "RSP", "USMV", "SPLV"]
COST_BPS_GRID = [0, 10, 25]
LOOKBACKS = [126, 252, 504]
COV_ESTIMATORS = ["sample", "ledoit_wolf", "diagonal", "ewma_63"]
WEIGHT_CAPS = [0.20, 0.35, 0.50]
SHORT_MODES = {
    "long_only": {"lower": 0.0, "gross_limit": 1.0},
    "limited_short": {"lower": -0.05, "gross_limit": 1.20},
}


@dataclass(frozen=True)
class Spec:
    estimator: str
    lookback: int
    cap: float
    short_mode: str

    @property
    def name(self) -> str:
        cap_label = str(int(round(self.cap * 100))).zfill(2)
        return (
            f"{self.estimator}_lb{self.lookback}_cap{cap_label}_"
            f"{self.short_mode}"
        )


def _download_prices() -> pd.DataFrame:
    tickers = sorted(set(UNIVERSE + BENCHMARKS))
    cache_path = DATA_DIR / "prices.csv"
    if cache_path.exists():
        cached = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        if all(ticker in cached.columns for ticker in tickers):
            print(f"Using cached prices from {cache_path}")
            return cached[tickers].sort_index()

    print(f"Downloading {len(tickers)} tickers via yfinance ...")
    raw = yf.download(
        tickers,
        start="2003-01-01",
        auto_adjust=True,
        progress=False,
        group_by="column",
        threads=True,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned no data")

    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" not in raw.columns.get_level_values(0):
            raise RuntimeError(f"No Close field in yfinance columns: {raw.columns}")
        prices = raw["Close"].copy()
    else:
        prices = raw[["Close"]].rename(columns={"Close": tickers[0]})

    prices = prices.sort_index()
    prices = prices.loc[:, [c for c in tickers if c in prices.columns]]
    prices = prices.dropna(how="all")
    missing = [t for t in tickers if t not in prices.columns]
    if missing:
        raise RuntimeError(f"Missing yfinance columns: {missing}")
    return prices


def _prepare_returns(prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    universe_prices = prices[UNIVERSE].dropna(how="any")
    universe_returns = universe_prices.pct_change(fill_method=None).dropna(how="any")
    benchmark_returns = prices[BENCHMARKS].pct_change(fill_method=None)
    return universe_returns, benchmark_returns


def _month_end_dates(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
    month_ends = index.to_series().groupby(pd.Grouper(freq="ME")).tail(1).index

    # Drop the current partial month when the download includes month-to-date
    # observations.  This keeps the final holding month complete.
    now_month = pd.Timestamp.now(tz=None).to_period("M")
    if len(month_ends) and month_ends[-1].to_period("M") == now_month:
        month_ends = month_ends[:-1]
    return list(month_ends)


def _ewma_cov(window: pd.DataFrame, half_life: float = 63.0) -> np.ndarray:
    x = window.to_numpy(dtype=float)
    n = x.shape[0]
    ages = np.arange(n - 1, -1, -1, dtype=float)
    weights = np.exp(np.log(0.5) * ages / half_life)
    weights = weights / weights.sum()
    center = np.average(x, axis=0, weights=weights)
    xc = x - center
    denom = max(1e-12, 1.0 - float(np.sum(weights**2)))
    cov = (xc * weights[:, None]).T @ xc / denom
    return cov


def _estimate_cov(window: pd.DataFrame, estimator: str) -> np.ndarray:
    if estimator == "sample":
        cov = window.cov().to_numpy(dtype=float)
    elif estimator == "ledoit_wolf":
        cov = LedoitWolf().fit(window.to_numpy(dtype=float)).covariance_
    elif estimator == "diagonal":
        var = window.var(ddof=1).to_numpy(dtype=float)
        cov = np.diag(var)
    elif estimator == "ewma_63":
        cov = _ewma_cov(window, half_life=63.0)
    else:
        raise ValueError(f"Unknown covariance estimator: {estimator}")

    cov = np.asarray(cov, dtype=float)
    cov = 0.5 * (cov + cov.T)
    ridge = max(1e-10, 1e-6 * float(np.nanmean(np.diag(cov))))
    return cov + np.eye(cov.shape[0]) * ridge


def _solve_min_var(cov: np.ndarray, lower: float, cap: float, gross_limit: float) -> tuple[np.ndarray, bool]:
    n = cov.shape[0]
    x0 = np.full(n, 1.0 / n)
    bounds = [(lower, cap)] * n
    constraints = [
        {
            "type": "eq",
            "fun": lambda w: float(np.sum(w) - 1.0),
            "jac": lambda w: np.ones_like(w),
        }
    ]
    if lower < 0:
        constraints.append(
            {
                "type": "ineq",
                "fun": lambda w: float(gross_limit - np.sum(np.abs(w))),
                "jac": lambda w: -np.sign(w),
            }
        )

    def objective(w: np.ndarray) -> float:
        return float(w @ cov @ w)

    def gradient(w: np.ndarray) -> np.ndarray:
        return 2.0 * cov @ w

    result = minimize(
        objective,
        x0,
        method="SLSQP",
        jac=gradient,
        bounds=bounds,
        constraints=constraints,
        options={"ftol": 1e-12, "maxiter": 150, "disp": False},
    )

    if result.success and np.all(np.isfinite(result.x)):
        w = np.asarray(result.x, dtype=float)
        w[np.abs(w) < 1e-12] = 0.0
        return w / w.sum(), True

    # Feasible fallback.  It is deliberately conservative and counted.
    fallback = np.full(n, 1.0 / n)
    return fallback, False


def _holding_periods(returns: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.DataFrame]]:
    month_ends = _month_end_dates(returns.index)
    periods: list[tuple[pd.Timestamp, pd.Timestamp, pd.DataFrame]] = []
    for rebalance_date, next_end in zip(month_ends[:-1], month_ends[1:]):
        if next_end < OOS_START:
            continue
        holding = returns.loc[(returns.index > rebalance_date) & (returns.index <= next_end)]
        if holding.empty:
            continue
        periods.append((rebalance_date, next_end, holding))
    return periods


def _backtest(
    returns: pd.DataFrame,
    periods: list[tuple[pd.Timestamp, pd.Timestamp, pd.DataFrame]],
    weight_func: Callable[[pd.Timestamp], tuple[np.ndarray, bool]],
) -> tuple[pd.Series, pd.Series, pd.DataFrame, int]:
    daily_returns: list[pd.Series] = []
    turnover_by_date: dict[pd.Timestamp, float] = {}
    weights_by_date: dict[pd.Timestamp, np.ndarray] = {}
    failures = 0
    prev_weights: np.ndarray | None = None
    prev_holding: pd.DataFrame | None = None
    prev_port_ret = 0.0

    for rebalance_date, _next_end, holding in periods:
        weights, ok = weight_func(rebalance_date)
        if not ok:
            failures += 1

        if prev_weights is None or prev_holding is None:
            turnover = 0.0
        else:
            asset_cum = (1.0 + prev_holding).prod().to_numpy(dtype=float) - 1.0
            denom = max(1e-12, 1.0 + prev_port_ret)
            drifted = prev_weights * (1.0 + asset_cum) / denom
            turnover = float(np.sum(np.abs(weights - drifted)))

        gross = holding @ weights
        daily_returns.append(gross)
        turnover_by_date[holding.index[0]] = turnover
        weights_by_date[rebalance_date] = weights
        prev_weights = weights
        prev_holding = holding
        prev_port_ret = float((1.0 + gross).prod() - 1.0)

    ret = pd.concat(daily_returns).sort_index()
    turnover = pd.Series(turnover_by_date, name="turnover").sort_index()
    weights_df = pd.DataFrame.from_dict(weights_by_date, orient="index", columns=returns.columns)
    weights_df.index.name = "rebalance_date"
    return ret, turnover, weights_df.sort_index(), failures


def _metrics(
    returns: pd.Series,
    turnover: pd.Series | None = None,
    benchmark: pd.Series | None = None,
) -> dict[str, float | int | None]:
    r = returns.dropna().astype(float)
    n = int(r.shape[0])
    years = n / TRADING_DAYS
    total = float((1.0 + r).prod() - 1.0)
    cagr = float((1.0 + total) ** (1.0 / years) - 1.0) if years > 0 else np.nan
    vol = float(r.std(ddof=1) * math.sqrt(TRADING_DAYS))
    sharpe = float(r.mean() / r.std(ddof=1) * math.sqrt(TRADING_DAYS)) if r.std(ddof=1) > 0 else np.nan
    nav = (1.0 + r).cumprod()
    drawdown = nav / nav.cummax() - 1.0
    downside = r[r < 0].std(ddof=1) * math.sqrt(TRADING_DAYS)
    sortino = float(r.mean() * TRADING_DAYS / downside) if downside and downside > 0 else np.nan
    out: dict[str, float | int | None] = {
        "n_days": n,
        "start": r.index.min().strftime("%Y-%m-%d"),
        "end": r.index.max().strftime("%Y-%m-%d"),
        "total_return": total,
        "cagr": cagr,
        "ann_return_arithmetic": float(r.mean() * TRADING_DAYS),
        "ann_vol": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": float(drawdown.min()),
        "calmar": float(cagr / abs(drawdown.min())) if drawdown.min() < 0 else np.nan,
    }
    if turnover is not None and len(turnover):
        t = turnover.reindex(r.index).fillna(0.0)
        out["avg_monthly_turnover"] = float(turnover.mean())
        out["ann_turnover"] = float(turnover.sum() / years)
    else:
        out["avg_monthly_turnover"] = None
        out["ann_turnover"] = None

    if benchmark is not None:
        aligned = pd.concat([r, benchmark], axis=1, join="inner").dropna()
        if aligned.shape[0] > 10:
            diff = aligned.iloc[:, 0] - aligned.iloc[:, 1]
            out["tracking_error"] = float(diff.std(ddof=1) * math.sqrt(TRADING_DAYS))
            cov = np.cov(aligned.iloc[:, 0], aligned.iloc[:, 1], ddof=1)
            out["beta_to_benchmark"] = float(cov[0, 1] / cov[1, 1]) if cov[1, 1] > 0 else np.nan
        else:
            out["tracking_error"] = np.nan
            out["beta_to_benchmark"] = np.nan
    else:
        out["tracking_error"] = np.nan
        out["beta_to_benchmark"] = np.nan
    return out


def _apply_costs(gross: pd.Series, turnover: pd.Series, cost_bps: int) -> pd.Series:
    net = gross.copy()
    cost = turnover * (cost_bps / 10_000.0)
    common = net.index.intersection(cost.index)
    net.loc[common] = net.loc[common] - cost.loc[common]
    return net


def _stationary_bootstrap_indices(n: int, block_length: float, rng: np.random.Generator) -> np.ndarray:
    p = 1.0 / block_length
    idx = np.empty(n, dtype=int)
    idx[0] = int(rng.integers(0, n))
    for i in range(1, n):
        if rng.random() < p:
            idx[i] = int(rng.integers(0, n))
        else:
            idx[i] = (idx[i - 1] + 1) % n
    return idx


def _bootstrap_band(returns_matrix: pd.DataFrame) -> dict[str, dict[str, float]]:
    rng = np.random.default_rng(SEED)
    x = returns_matrix.dropna(how="any").to_numpy(dtype=float)
    n, _m = x.shape
    records = {
        "ann_vol_range": [],
        "ann_vol_p90_p10": [],
        "sharpe_range": [],
        "sharpe_p90_p10": [],
        "max_drawdown_range": [],
        "max_drawdown_p90_p10": [],
    }
    for _ in range(BOOTSTRAP_REPS):
        idx = _stationary_bootstrap_indices(n, BOOTSTRAP_BLOCK, rng)
        sample = x[idx, :]
        std = sample.std(axis=0, ddof=1)
        ann_vol = std * math.sqrt(TRADING_DAYS)
        sharpe = np.divide(
            sample.mean(axis=0) * math.sqrt(TRADING_DAYS),
            std,
            out=np.full(sample.shape[1], np.nan),
            where=std > 0,
        )
        nav = np.cumprod(1.0 + sample, axis=0)
        dd = nav / np.maximum.accumulate(nav, axis=0) - 1.0
        mdd = dd.min(axis=0)
        for key, values in [
            ("ann_vol", ann_vol),
            ("sharpe", sharpe),
            ("max_drawdown", mdd),
        ]:
            records[f"{key}_range"].append(float(np.nanmax(values) - np.nanmin(values)))
            records[f"{key}_p90_p10"].append(
                float(np.nanpercentile(values, 90) - np.nanpercentile(values, 10))
            )

    summary: dict[str, dict[str, float]] = {}
    for key, values in records.items():
        arr = np.asarray(values, dtype=float)
        summary[key] = {
            "mean": float(arr.mean()),
            "p05": float(np.percentile(arr, 5)),
            "p50": float(np.percentile(arr, 50)),
            "p95": float(np.percentile(arr, 95)),
        }
    return summary


def _formal_tests(spec_returns: pd.DataFrame, baselines: dict[str, pd.Series]) -> pd.DataFrame:
    rows = []
    for spec_name in spec_returns.columns:
        sr = spec_returns[spec_name].dropna()
        for baseline_name, br in baselines.items():
            aligned = pd.concat([sr, br], axis=1, join="inner").dropna()
            if aligned.shape[0] < 252:
                continue
            r_spec = aligned.iloc[:, 0].to_numpy(dtype=float)
            r_base = aligned.iloc[:, 1].to_numpy(dtype=float)
            var_t, var_p = dm_test(r_spec**2, r_base**2, h=1)
            ret_t, ret_p = strategy_dm_test(r_spec, r_base, h=1, loss_fn="negative_return")
            rows.append(
                {
                    "spec": spec_name,
                    "baseline": baseline_name,
                    "n_days": int(aligned.shape[0]),
                    "variance_dm_t": float(var_t),
                    "variance_dm_p": float(var_p),
                    "variance_harvey_pass_lower_var": bool(var_t < -3.0),
                    "return_dm_t": float(ret_t),
                    "return_dm_p": float(ret_p),
                    "return_harvey_pass_higher_return": bool(ret_t < -3.0),
                }
            )
    return pd.DataFrame(rows)


def _plot_metric_bands(metrics_10bps: pd.DataFrame, benchmarks: pd.DataFrame) -> None:
    plot_df = metrics_10bps.copy()
    cols = ["ann_vol", "sharpe", "max_drawdown", "tracking_error", "ann_turnover"]
    fig, axes = plt.subplots(1, len(cols), figsize=(18, 4.2))
    for ax, col in zip(axes, cols):
        values = plot_df[col].dropna()
        ax.boxplot(values, vert=True, widths=0.45, showfliers=True)
        ax.scatter(np.ones(len(values)) + np.random.default_rng(SEED).normal(0, 0.03, len(values)), values, s=12, alpha=0.35)
        if col in benchmarks.columns:
            for name, row in benchmarks.dropna(subset=[col]).iterrows():
                ax.axhline(row[col], linestyle="--", linewidth=1.2, label=name)
        ax.set_title(col)
        ax.set_xticks([])
        ax.grid(alpha=0.25)
    handles, labels = axes[0].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="lower center", ncol=min(4, len(handles)))
    fig.suptitle("Low-risk construction model-risk bands (10 bps one-way cost)")
    fig.tight_layout(rect=[0, 0.08, 1, 0.95])
    fig.savefig(FIG_DIR / "model_risk_bands_10bps.png", dpi=180)
    plt.close(fig)


def _plot_nav(spec_returns_10bps: pd.DataFrame, metrics_10bps: pd.DataFrame, baseline_returns: dict[str, pd.Series]) -> None:
    selected = []
    selected.append(metrics_10bps["ann_vol"].idxmin())
    selected.append(metrics_10bps["sharpe"].idxmax())
    selected.append(metrics_10bps["sharpe"].idxmin())
    selected.append((metrics_10bps["sharpe"] - metrics_10bps["sharpe"].median()).abs().idxmin())
    selected = list(dict.fromkeys(selected))

    fig, ax = plt.subplots(figsize=(11, 6))
    for spec in selected:
        nav = (1.0 + spec_returns_10bps[spec].dropna()).cumprod()
        ax.plot(nav.index, nav, linewidth=1.3, label=spec)

    for name, ret in baseline_returns.items():
        nav = (1.0 + ret.dropna()).cumprod()
        ax.plot(nav.index, nav, linewidth=2.0, linestyle="--", label=name)

    ax.set_yscale("log")
    ax.set_title("Representative cumulative NAVs (log scale)")
    ax.set_ylabel("Growth of $1")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "representative_navs_10bps.png", dpi=180)
    plt.close(fig)


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    FIG_DIR.mkdir(exist_ok=True)
    np.random.seed(SEED)

    prices = _download_prices()
    prices.to_csv(DATA_DIR / "prices.csv")
    universe_returns, benchmark_returns = _prepare_returns(prices)
    universe_returns.to_csv(DATA_DIR / "universe_daily_returns.csv")
    benchmark_returns.to_csv(DATA_DIR / "benchmark_daily_returns.csv")

    periods = _holding_periods(universe_returns)
    if len(periods) < 60:
        raise RuntimeError(f"Too few monthly OOS periods: {len(periods)}")

    specs = [
        Spec(estimator=estimator, lookback=lookback, cap=cap, short_mode=short_mode)
        for estimator in COV_ESTIMATORS
        for lookback in LOOKBACKS
        for cap in WEIGHT_CAPS
        for short_mode in SHORT_MODES
    ]

    gross_returns: dict[str, pd.Series] = {}
    turnover: dict[str, pd.Series] = {}
    weights_records = []
    optimizer_failures: dict[str, int] = {}

    for i, spec in enumerate(specs, start=1):
        print(f"[{i:02d}/{len(specs)}] Backtesting {spec.name}")

        def weight_func(date: pd.Timestamp, _spec: Spec = spec) -> tuple[np.ndarray, bool]:
            window = universe_returns.loc[:date].tail(_spec.lookback)
            if window.shape[0] < _spec.lookback:
                return np.full(len(UNIVERSE), 1.0 / len(UNIVERSE)), False
            cov = _estimate_cov(window, _spec.estimator)
            params = SHORT_MODES[_spec.short_mode]
            return _solve_min_var(
                cov,
                lower=float(params["lower"]),
                cap=_spec.cap,
                gross_limit=float(params["gross_limit"]),
            )

        ret, to, weights, failures = _backtest(universe_returns, periods, weight_func)
        gross_returns[spec.name] = ret
        turnover[spec.name] = to
        optimizer_failures[spec.name] = failures
        weights = weights.copy()
        weights["spec"] = spec.name
        weights_records.append(weights.reset_index())

    def ew_weight_func(_date: pd.Timestamp) -> tuple[np.ndarray, bool]:
        return np.full(len(UNIVERSE), 1.0 / len(UNIVERSE)), True

    sector_ew_gross, sector_ew_turnover, _sector_weights, _ = _backtest(
        universe_returns,
        periods,
        ew_weight_func,
    )

    gross_df = pd.DataFrame(gross_returns).dropna(how="all")
    gross_df.to_csv(DATA_DIR / "spec_gross_daily_returns.csv")
    all_weights = pd.concat(weights_records, ignore_index=True)
    all_weights.to_csv(DATA_DIR / "monthly_weights.csv", index=False)

    spec_metrics_rows = []
    net_returns_by_cost: dict[int, pd.DataFrame] = {}
    benchmark_for_tracking = benchmark_returns["SPY"].reindex(gross_df.index)

    for cost_bps in COST_BPS_GRID:
        cost_returns = {}
        for spec in specs:
            net = _apply_costs(gross_returns[spec.name], turnover[spec.name], cost_bps)
            cost_returns[spec.name] = net
            m = _metrics(net, turnover[spec.name], benchmark_for_tracking)
            m.update(asdict(spec))
            m["spec"] = spec.name
            m["cost_bps"] = cost_bps
            m["optimizer_failures"] = optimizer_failures[spec.name]
            spec_metrics_rows.append(m)
        net_df = pd.DataFrame(cost_returns).dropna(how="all")
        net_returns_by_cost[cost_bps] = net_df
        net_df.to_csv(DATA_DIR / f"spec_net_daily_returns_{cost_bps}bps.csv")

    spec_metrics = pd.DataFrame(spec_metrics_rows)
    spec_metrics.to_csv(DATA_DIR / "spec_metrics.csv", index=False)

    baseline_returns: dict[str, pd.Series] = {}
    baseline_metrics_rows = []
    for cost_bps in COST_BPS_GRID:
        sector_net = _apply_costs(sector_ew_gross, sector_ew_turnover, cost_bps)
        baseline_returns[f"sector_equal_weight_{cost_bps}bps"] = sector_net
        m = _metrics(sector_net, sector_ew_turnover, benchmark_for_tracking)
        m.update({"benchmark": "sector_equal_weight", "cost_bps": cost_bps})
        baseline_metrics_rows.append(m)

    for benchmark in BENCHMARKS:
        br = benchmark_returns[benchmark].reindex(gross_df.index).dropna()
        if br.shape[0] < 252:
            continue
        baseline_returns[benchmark] = br
        m = _metrics(br, None, benchmark_for_tracking)
        m.update({"benchmark": benchmark, "cost_bps": 0})
        baseline_metrics_rows.append(m)

    baseline_metrics = pd.DataFrame(baseline_metrics_rows)
    baseline_metrics.to_csv(DATA_DIR / "baseline_metrics.csv", index=False)

    metrics_10 = spec_metrics.loc[spec_metrics["cost_bps"] == 10].set_index("spec")
    baseline_plot = baseline_metrics.loc[
        (
            (baseline_metrics["benchmark"] == "sector_equal_weight")
            & (baseline_metrics["cost_bps"] == 10)
        )
        | (baseline_metrics["benchmark"].isin(BENCHMARKS))
    ].drop_duplicates(subset=["benchmark"], keep="first").set_index("benchmark")
    spec_returns_10 = net_returns_by_cost[10]
    formal = _formal_tests(
        spec_returns_10,
        {
            "sector_equal_weight_10bps": baseline_returns["sector_equal_weight_10bps"],
            "SPY": baseline_returns["SPY"],
        },
    )
    formal.to_csv(DATA_DIR / "formal_tests_10bps.csv", index=False)

    bootstrap = _bootstrap_band(spec_returns_10)
    _plot_metric_bands(metrics_10, baseline_plot)
    _plot_nav(
        spec_returns_10,
        metrics_10,
        {
            "sector_equal_weight_10bps": baseline_returns["sector_equal_weight_10bps"],
            "SPY": baseline_returns["SPY"].reindex(spec_returns_10.index),
            "USMV": baseline_returns.get("USMV", pd.Series(dtype=float)).reindex(spec_returns_10.index),
        },
    )

    band_10 = {
        metric: {
            "min": float(metrics_10[metric].min()),
            "p10": float(metrics_10[metric].quantile(0.10)),
            "median": float(metrics_10[metric].median()),
            "p90": float(metrics_10[metric].quantile(0.90)),
            "max": float(metrics_10[metric].max()),
            "range": float(metrics_10[metric].max() - metrics_10[metric].min()),
            "p90_p10": float(metrics_10[metric].quantile(0.90) - metrics_10[metric].quantile(0.10)),
        }
        for metric in ["ann_vol", "sharpe", "max_drawdown", "tracking_error", "ann_turnover"]
    }

    best_by_metric = {
        "min_ann_vol": metrics_10["ann_vol"].idxmin(),
        "max_sharpe": metrics_10["sharpe"].idxmax(),
        "min_max_drawdown": metrics_10["max_drawdown"].idxmax(),
        "max_max_drawdown": metrics_10["max_drawdown"].idxmin(),
        "min_turnover": metrics_10["ann_turnover"].idxmin(),
        "max_turnover": metrics_10["ann_turnover"].idxmax(),
    }

    formal_summary = {}
    for baseline in formal["baseline"].unique():
        sub = formal.loc[formal["baseline"] == baseline]
        formal_summary[baseline] = {
            "n_tests": int(sub.shape[0]),
            "variance_harvey_pass_lower_var": int(sub["variance_harvey_pass_lower_var"].sum()),
            "return_harvey_pass_higher_return": int(sub["return_harvey_pass_higher_return"].sum()),
            "median_variance_dm_t": float(sub["variance_dm_t"].median()),
            "median_return_dm_t": float(sub["return_dm_t"].median()),
        }

    sector_vol = float(
        baseline_metrics.loc[
            (baseline_metrics["benchmark"] == "sector_equal_weight")
            & (baseline_metrics["cost_bps"] == 10),
            "ann_vol",
        ].iloc[0]
    )
    spy_vol = float(baseline_metrics.loc[baseline_metrics["benchmark"] == "SPY", "ann_vol"].iloc[0])
    median_vol = float(metrics_10["ann_vol"].median())
    vol_range = float(metrics_10["ann_vol"].max() - metrics_10["ann_vol"].min())
    sharpe_range = float(metrics_10["sharpe"].max() - metrics_10["sharpe"].min())
    mdd_range = float(metrics_10["max_drawdown"].max() - metrics_10["max_drawdown"].min())

    if vol_range > 0.03 and sharpe_range > 0.35 and mdd_range > 0.10:
        verdict = "MODEL_RISK_BAND_MATERIAL"
    else:
        verdict = "MODEL_RISK_BAND_MODEST"

    results = {
        "experiment_id": EXP_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "data": {
            "source": "yfinance adjusted close via auto_adjust=True",
            "universe": UNIVERSE,
            "benchmarks": BENCHMARKS,
            "universe_start": universe_returns.index.min().strftime("%Y-%m-%d"),
            "universe_end": universe_returns.index.max().strftime("%Y-%m-%d"),
            "oos_start": gross_df.index.min().strftime("%Y-%m-%d"),
            "oos_end": gross_df.index.max().strftime("%Y-%m-%d"),
            "oos_days": int(gross_df.dropna(how="all").shape[0]),
            "oos_months": int(len(periods)),
        },
        "design": {
            "lookbacks": LOOKBACKS,
            "cov_estimators": COV_ESTIMATORS,
            "weight_caps": WEIGHT_CAPS,
            "short_modes": SHORT_MODES,
            "cost_bps_grid": COST_BPS_GRID,
            "bootstrap_reps": BOOTSTRAP_REPS,
            "bootstrap_block_days": BOOTSTRAP_BLOCK,
            "lookahead_guard": (
                "Weights are estimated at month-end t from returns through t "
                "and applied only to trading days t+1 through the next month-end."
            ),
        },
        "summary_10bps": {
            "n_specs": int(metrics_10.shape[0]),
            "model_risk_band": band_10,
            "best_by_metric": best_by_metric,
            "median_ann_vol_minus_sector_ew": float(median_vol - sector_vol),
            "median_ann_vol_minus_spy": float(median_vol - spy_vol),
            "formal_tests": formal_summary,
        },
        "bootstrap_model_risk_band_10bps": bootstrap,
        "baselines": baseline_metrics.to_dict(orient="records"),
        "top_specs_10bps": (
            metrics_10.sort_values("sharpe", ascending=False)
            .head(10)
            .reset_index()
            .to_dict(orient="records")
        ),
        "bottom_specs_10bps": (
            metrics_10.sort_values("sharpe", ascending=True)
            .head(10)
            .reset_index()
            .to_dict(orient="records")
        ),
        "optimizer_failures_total": int(sum(optimizer_failures.values())),
        "files": {
            "prices": "data/prices.csv",
            "universe_returns": "data/universe_daily_returns.csv",
            "benchmark_returns": "data/benchmark_daily_returns.csv",
            "spec_metrics": "data/spec_metrics.csv",
            "formal_tests": "data/formal_tests_10bps.csv",
            "weights": "data/monthly_weights.csv",
            "figure_bands": "figures/model_risk_bands_10bps.png",
            "figure_nav": "figures/representative_navs_10bps.png",
        },
    }

    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({
        "verdict": verdict,
        "oos_days": results["data"]["oos_days"],
        "n_specs": int(metrics_10.shape[0]),
        "vol_range_10bps": vol_range,
        "sharpe_range_10bps": sharpe_range,
        "mdd_range_10bps": mdd_range,
        "optimizer_failures_total": results["optimizer_failures_total"],
    }, indent=2))


if __name__ == "__main__":
    main()
