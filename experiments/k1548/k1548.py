#!/usr/bin/env python3
"""K1548: Taiwan-investor currency hedge-ratio comparison.

The experiment compares unhedged, full hedge, static minimum-variance,
EWMA covariance ("DCC-lite"), and HMM regime hedge-ratio overlays for USD
equity ETFs translated into TWD.  Every OOS hedge ratio is determined from
training data or information available before the return being hedged.
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from hmmlearn.hmm import GaussianHMM


SEED = 1548
START = "2015-01-01"
TRAIN_END = pd.Timestamp("2019-12-31")
OOS_START = pd.Timestamp("2020-01-02")
ASSETS = ["SPY", "EFA", "EEM", "QQQ"]
LOCAL_BENCHMARKS = ["0050.TW", "^TWII"]
FX_CANDIDATES = ["TWD=X", "USDTWD=X"]
ALL_TICKERS = ASSETS + LOCAL_BENCHMARKS + FX_CANDIDATES
POLICY_ORDER = ["unhedged", "full_hedge", "static_mv", "ewma_dcc_lite", "hmm_regime"]
OUT_DIR = Path(__file__).resolve().parent
DATA_DIR = OUT_DIR / "data"
FIG_DIR = OUT_DIR / "figures"
RESULT_PATH = OUT_DIR / "k1548_results.json"
RAW_DATA_PATH = DATA_DIR / "k1548_daily_returns.csv"


@dataclass
class MetricRow:
    asset: str
    policy: str
    observations: int
    total_return: float
    annual_return: float
    annual_vol: float
    downside_semivol: float
    sharpe: float
    max_drawdown: float
    var_5: float
    cvar_5: float
    avg_hedge_ratio: float
    hedge_ratio_std: float
    vol_reduction_vs_unhedged: float
    downside_reduction_vs_unhedged: float
    cvar_improvement_vs_unhedged: float


@dataclass
class TestRow:
    asset: str
    policy: str
    mean_daily_squared_return_reduction: float
    annualized_squared_return_reduction: float
    hac_tstat: float
    bootstrap_ci_low: float
    bootstrap_ci_high: float
    bootstrap_reps: int
    passes_harvey_gate: bool


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)


def _clean_columns(raw: pd.DataFrame) -> pd.DataFrame:
    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(0):
            prices = raw["Close"].copy()
        elif "Adj Close" in raw.columns.get_level_values(0):
            prices = raw["Adj Close"].copy()
        else:
            raise ValueError(f"Cannot locate close prices in columns: {raw.columns}")
    else:
        close_name = "Close" if "Close" in raw.columns else "Adj Close"
        prices = raw[[close_name]].copy()
        prices.columns = [ALL_TICKERS[0]]
    # Do not forward-fill across different market calendars: doing so creates
    # synthetic zero returns on non-trading days and biases realized volatility.
    prices = prices.sort_index()
    return prices


def fetch_prices() -> tuple[pd.DataFrame, str]:
    raw = yf.download(
        ALL_TICKERS,
        start=START,
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="column",
    )
    prices = _clean_columns(raw)
    available = [ticker for ticker in ALL_TICKERS if ticker in prices.columns]
    missing = sorted(set(ALL_TICKERS) - set(available))
    if missing:
        warnings.warn(f"Missing yfinance tickers: {missing}")
    fx_symbol = max(FX_CANDIDATES, key=lambda symbol: int(prices.get(symbol, pd.Series()).notna().sum()))
    if fx_symbol not in prices or prices[fx_symbol].dropna().empty:
        raise RuntimeError("No USD/TWD FX ticker returned usable data.")
    return prices[available], fx_symbol


def static_min_variance_ratio(asset_ret: pd.Series, fx_ret: pd.Series) -> float:
    sample = pd.concat([asset_ret, fx_ret], axis=1).dropna()
    sample.columns = ["asset", "fx"]
    var_fx = float(sample["fx"].var(ddof=1))
    if not np.isfinite(var_fx) or var_fx <= 0:
        return 1.0
    cov = float(sample["asset"].cov(sample["fx"]))
    return float(np.clip(1.0 + cov / var_fx, 0.0, 1.5))


def ewma_hedge_ratio(df: pd.DataFrame, lam: float = 0.94) -> pd.Series:
    train = df.loc[df.index <= TRAIN_END]
    oos = df.loc[df.index >= OOS_START]
    cov = float(train["asset"].cov(train["fx"]))
    var_fx = float(train["fx"].var(ddof=1))
    if not np.isfinite(cov):
        cov = 0.0
    if not np.isfinite(var_fx) or var_fx <= 0:
        var_fx = float(df["fx"].var(ddof=1))
    h_values: dict[pd.Timestamp, float] = {}

    # h_t is set before observing return_t; return_t updates only h_{t+1}.
    for date, row in oos.iterrows():
        h_values[date] = float(np.clip(1.0 + cov / var_fx, 0.0, 1.5))
        cov = lam * cov + (1.0 - lam) * float(row["asset"] * row["fx"])
        var_fx = lam * var_fx + (1.0 - lam) * float(row["fx"] ** 2)
        var_fx = max(var_fx, 1e-10)
    return pd.Series(h_values, name="ewma_dcc_lite")


def _standardize(train: pd.DataFrame, full: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    mean = train.mean(axis=0)
    std = train.std(axis=0, ddof=1).replace(0, np.nan).fillna(1.0)
    train_scaled = ((train - mean) / std).to_numpy()
    full_scaled = ((full - mean) / std).to_numpy()
    return train_scaled, full_scaled


def hmm_regime_hedge_ratio(df: pd.DataFrame, static_h: float) -> tuple[pd.Series, dict[str, object]]:
    features = df[["asset", "fx"]].dropna()
    train = features.loc[features.index <= TRAIN_END]
    oos = features.loc[features.index >= OOS_START]
    if len(train) < 756 or len(oos) < 252:
        return pd.Series(static_h, index=oos.index, name="hmm_regime"), {"fallback": "insufficient_data"}

    train_scaled, full_scaled = _standardize(train, features)
    model = GaussianHMM(
        n_components=2,
        covariance_type="full",
        n_iter=300,
        tol=1e-5,
        random_state=SEED,
        min_covar=1e-5,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model.fit(train_scaled)
    train_states = pd.Series(model.predict(train_scaled), index=train.index, name="state")
    prev_state = train_states.shift(1)
    state_ratios: dict[int, float] = {}
    state_counts: dict[int, int] = {}
    train_returns = df.loc[train.index, ["asset", "fx"]]
    for state in range(model.n_components):
        mask = prev_state == state
        state_counts[state] = int(mask.sum())
        if int(mask.sum()) < 60:
            state_ratios[state] = static_h
            continue
        state_ratios[state] = static_min_variance_ratio(train_returns.loc[mask, "asset"], train_returns.loc[mask, "fx"])

    h_values: dict[pd.Timestamp, float] = {}
    feature_index = list(features.index)
    position_by_date = {date: pos for pos, date in enumerate(feature_index)}
    # For each OOS return date, infer the previous day's state using only the
    # sequence available through that previous day, then apply the corresponding
    # train-estimated hedge ratio.
    for date in oos.index:
        pos = position_by_date[date]
        if pos == 0:
            h_values[date] = static_h
            continue
        states_through_prev = model.predict(full_scaled[:pos])
        prev_day_state = int(states_through_prev[-1])
        h_values[date] = state_ratios.get(prev_day_state, static_h)

    metadata = {
        "fallback": None,
        "state_ratios": {str(k): v for k, v in state_ratios.items()},
        "state_counts": {str(k): v for k, v in state_counts.items()},
        "model_converged": bool(getattr(model.monitor_, "converged", False)),
        "train_log_likelihood": float(model.score(train_scaled)),
    }
    return pd.Series(h_values, name="hmm_regime"), metadata


def hedged_return(asset_ret: pd.Series, fx_ret: pd.Series, hedge_ratio: pd.Series | float) -> pd.Series:
    if isinstance(hedge_ratio, pd.Series):
        h = hedge_ratio.reindex(asset_ret.index).ffill()
    else:
        h = pd.Series(float(hedge_ratio), index=asset_ret.index)
    h = h.clip(0.0, 1.5)
    return ((1.0 + asset_ret) * (1.0 + (1.0 - h) * fx_ret) - 1.0).dropna()


def max_drawdown(returns: pd.Series) -> float:
    wealth = (1.0 + returns).cumprod()
    drawdown = wealth / wealth.cummax() - 1.0
    return float(drawdown.min())


def metrics_for(asset: str, policy: str, returns: pd.Series, hedge_ratio: pd.Series | float, baseline: pd.Series) -> MetricRow:
    aligned = pd.concat([returns, baseline], axis=1, join="inner").dropna()
    aligned.columns = ["strategy", "baseline"]
    r = aligned["strategy"]
    b = aligned["baseline"]
    if isinstance(hedge_ratio, pd.Series):
        h = hedge_ratio.reindex(r.index).ffill().dropna()
        avg_h = float(h.mean())
        h_std = float(h.std(ddof=1))
    else:
        avg_h = float(hedge_ratio)
        h_std = 0.0
    annual_vol = float(r.std(ddof=1) * math.sqrt(252))
    annual_return = float(r.mean() * 252)
    downside = np.minimum(r.to_numpy(), 0.0)
    base_downside = np.minimum(b.to_numpy(), 0.0)
    downside_semivol = float(math.sqrt(np.mean(downside**2)) * math.sqrt(252))
    base_downside_semivol = float(math.sqrt(np.mean(base_downside**2)) * math.sqrt(252))
    var_5 = float(r.quantile(0.05))
    cvar_5 = float(r[r <= var_5].mean())
    base_var_5 = float(b.quantile(0.05))
    base_cvar_5 = float(b[b <= base_var_5].mean())
    base_vol = float(b.std(ddof=1) * math.sqrt(252))
    return MetricRow(
        asset=asset,
        policy=policy,
        observations=int(r.size),
        total_return=float((1.0 + r).prod() - 1.0),
        annual_return=annual_return,
        annual_vol=annual_vol,
        downside_semivol=downside_semivol,
        sharpe=float(annual_return / annual_vol) if annual_vol > 0 else float("nan"),
        max_drawdown=max_drawdown(r),
        var_5=var_5,
        cvar_5=cvar_5,
        avg_hedge_ratio=avg_h,
        hedge_ratio_std=h_std,
        vol_reduction_vs_unhedged=float(1.0 - annual_vol / base_vol) if base_vol > 0 else float("nan"),
        downside_reduction_vs_unhedged=float(1.0 - downside_semivol / base_downside_semivol)
        if base_downside_semivol > 0
        else float("nan"),
        cvar_improvement_vs_unhedged=float((base_cvar_5 - cvar_5) / abs(base_cvar_5)) if base_cvar_5 < 0 else float("nan"),
    )


def hac_tstat(series: pd.Series, lags: int = 5) -> float:
    x = series.dropna().to_numpy()
    n = len(x)
    if n < lags + 2:
        return float("nan")
    mean = float(np.mean(x))
    centered = x - mean
    gamma = float(np.mean(centered * centered))
    for lag in range(1, min(lags, n - 1) + 1):
        weight = 1.0 - lag / (lags + 1.0)
        gamma += 2.0 * weight * float(np.mean(centered[lag:] * centered[:-lag]))
    se = math.sqrt(max(gamma, 0.0) / n)
    return float(mean / se) if se > 0 else float("nan")


def circular_block_bootstrap_ci(series: pd.Series, reps: int = 3000, block: int = 10, seed_offset: int = 0) -> tuple[float, float]:
    x = series.dropna().to_numpy()
    n = len(x)
    if n == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(SEED + seed_offset)
    means = np.empty(reps)
    n_blocks = math.ceil(n / block)
    for rep in range(reps):
        starts = rng.integers(0, n, size=n_blocks)
        sample = []
        for start in starts:
            idx = (np.arange(start, start + block) % n).astype(int)
            sample.append(x[idx])
        means[rep] = np.concatenate(sample)[:n].mean()
    low, high = np.quantile(means, [0.025, 0.975])
    return float(low), float(high)


def test_loss_reduction(asset: str, policy: str, baseline: pd.Series, strategy: pd.Series, seed_offset: int) -> TestRow:
    aligned = pd.concat([baseline, strategy], axis=1, join="inner").dropna()
    aligned.columns = ["baseline", "strategy"]
    diff = aligned["baseline"] ** 2 - aligned["strategy"] ** 2
    ci_low, ci_high = circular_block_bootstrap_ci(diff, seed_offset=seed_offset)
    tstat = hac_tstat(diff)
    mean_diff = float(diff.mean())
    return TestRow(
        asset=asset,
        policy=policy,
        mean_daily_squared_return_reduction=mean_diff,
        annualized_squared_return_reduction=float(mean_diff * 252),
        hac_tstat=tstat,
        bootstrap_ci_low=ci_low,
        bootstrap_ci_high=ci_high,
        bootstrap_reps=3000,
        passes_harvey_gate=bool(tstat > 3.0 and ci_low > 0.0),
    )


def cumulative_series(returns_by_policy: dict[str, pd.Series]) -> pd.DataFrame:
    frame = pd.concat(returns_by_policy, axis=1).dropna()
    return (1.0 + frame).cumprod()


def plot_spy_cumulative(all_returns: dict[str, dict[str, pd.Series]]) -> None:
    cum = cumulative_series(all_returns["SPY"])
    fig, ax = plt.subplots(figsize=(9, 5))
    for policy in POLICY_ORDER:
        if policy in cum:
            ax.plot(cum.index, cum[policy], label=policy)
    ax.set_title("K1548 SPY TWD cumulative OOS returns by hedge policy")
    ax.set_ylabel("Growth of TWD 1")
    ax.legend(loc="best", fontsize=8)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1548_spy_cumulative_returns.png", dpi=160)
    plt.close(fig)


def plot_metric_bars(metrics: list[MetricRow]) -> None:
    frame = pd.DataFrame(asdict(row) for row in metrics)
    for column, filename, ylabel in [
        ("vol_reduction_vs_unhedged", "k1548_vol_reduction.png", "Vol reduction vs unhedged"),
        ("downside_reduction_vs_unhedged", "k1548_downside_reduction.png", "Downside semivol reduction"),
    ]:
        pivot = frame.pivot(index="asset", columns="policy", values=column)[POLICY_ORDER[1:]]
        fig, ax = plt.subplots(figsize=(9, 5))
        pivot.plot(kind="bar", ax=ax)
        ax.axhline(0, color="black", linewidth=0.8)
        ax.set_ylabel(ylabel)
        ax.set_title(f"K1548 {ylabel}")
        ax.legend(loc="best", fontsize=8)
        ax.grid(axis="y", alpha=0.25)
        fig.tight_layout()
        fig.savefig(FIG_DIR / filename, dpi=160)
        plt.close(fig)


def plot_hedge_ratios(metrics: list[MetricRow], h_paths: dict[str, dict[str, pd.Series | float]]) -> None:
    frame = pd.DataFrame(asdict(row) for row in metrics)
    pivot = frame.pivot(index="asset", columns="policy", values="avg_hedge_ratio")[POLICY_ORDER[1:]]
    fig, ax = plt.subplots(figsize=(9, 5))
    pivot.plot(kind="bar", ax=ax)
    ax.set_ylabel("Average hedge ratio")
    ax.set_title("K1548 average OOS hedge ratios")
    ax.axhline(1.0, color="black", linewidth=0.8, linestyle="--")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1548_average_hedge_ratios.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 5))
    for asset in ASSETS:
        series = h_paths[asset]["ewma_dcc_lite"]
        if isinstance(series, pd.Series):
            ax.plot(series.index, series, label=asset)
    ax.set_title("K1548 EWMA/DCC-lite dynamic hedge-ratio paths")
    ax.set_ylabel("Hedge ratio")
    ax.set_ylim(-0.05, 1.55)
    ax.legend(loc="best", fontsize=8)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1548_ewma_hedge_paths.png", dpi=160)
    plt.close(fig)


def summarize_verdict(metrics: list[MetricRow], tests: list[TestRow]) -> tuple[str, list[str]]:
    frame = pd.DataFrame(asdict(row) for row in metrics)
    tests_frame = pd.DataFrame(asdict(row) for row in tests)
    non_base = frame[frame["policy"] != "unhedged"].copy()
    mean_by_policy = non_base.groupby("policy")[["vol_reduction_vs_unhedged", "downside_reduction_vs_unhedged", "sharpe"]].mean()
    gate_by_policy = tests_frame.groupby("policy")["passes_harvey_gate"].sum().to_dict()
    best_vol_policy = str(mean_by_policy["vol_reduction_vs_unhedged"].idxmax())
    dynamic_policies = ["ewma_dcc_lite", "hmm_regime"]
    dynamic_gate_count = int(sum(gate_by_policy.get(policy, 0) for policy in dynamic_policies))
    static_gate_count = int(gate_by_policy.get("static_mv", 0) + gate_by_policy.get("full_hedge", 0))

    if best_vol_policy in dynamic_policies and dynamic_gate_count >= 2:
        verdict = "DYNAMIC_OVERLAY_PARTIAL_SUPPORT_BUT_ASSET_DEPENDENT"
    elif static_gate_count >= dynamic_gate_count:
        verdict = "STATIC_OR_FULL_HEDGE_DOMINATES_DYNAMIC_IN_FREE_DATA_OOS"
    else:
        verdict = "HEDGE_RATIO_RESULTS_MIXED_NO_ROBUST_DYNAMIC_EDGE"

    findings = [
        f"Average OOS vol reduction is highest for {best_vol_policy}: "
        f"{mean_by_policy.loc[best_vol_policy, 'vol_reduction_vs_unhedged']:.2%}.",
        "Harvey-style support counts by policy: "
        + ", ".join(f"{policy}={gate_by_policy.get(policy, 0)}/{len(ASSETS)}" for policy in POLICY_ORDER[1:]),
        "Dynamic policies are labelled EWMA/DCC-lite and train-only HMM regime overlays; the experiment does not claim a full DCC-GARCH implementation.",
    ]
    return verdict, findings


def run() -> dict[str, object]:
    _ensure_dirs()
    np.random.seed(SEED)
    prices, fx_symbol = fetch_prices()
    returns = prices.pct_change(fill_method=None)
    fx_ret = returns[fx_symbol].rename("fx")
    raw_return_frame = returns[[ticker for ticker in ASSETS + LOCAL_BENCHMARKS if ticker in returns.columns]].join(fx_ret)
    raw_return_frame.to_csv(RAW_DATA_PATH, index_label="date")

    all_metrics: list[MetricRow] = []
    all_tests: list[TestRow] = []
    all_returns: dict[str, dict[str, pd.Series]] = {}
    h_paths: dict[str, dict[str, pd.Series | float]] = {}
    hmm_metadata: dict[str, dict[str, object]] = {}
    sample_summary: dict[str, object] = {}

    for asset in ASSETS:
        df = pd.concat([returns[asset].rename("asset"), fx_ret], axis=1).dropna()
        df = df.loc[df.index >= pd.Timestamp(START)]
        train = df.loc[df.index <= TRAIN_END]
        oos = df.loc[df.index >= OOS_START]
        if len(train) < 756 or len(oos) < 252:
            raise RuntimeError(f"{asset} has insufficient train/OOS observations.")

        static_h = static_min_variance_ratio(train["asset"], train["fx"])
        ewma_h = ewma_hedge_ratio(df)
        hmm_h, hmm_meta = hmm_regime_hedge_ratio(df, static_h)
        hmm_metadata[asset] = hmm_meta
        policy_h: dict[str, pd.Series | float] = {
            "unhedged": 0.0,
            "full_hedge": 1.0,
            "static_mv": static_h,
            "ewma_dcc_lite": ewma_h,
            "hmm_regime": hmm_h,
        }
        h_paths[asset] = policy_h

        asset_returns: dict[str, pd.Series] = {}
        for policy in POLICY_ORDER:
            asset_returns[policy] = hedged_return(oos["asset"], oos["fx"], policy_h[policy])
        all_returns[asset] = asset_returns
        baseline = asset_returns["unhedged"]
        for policy in POLICY_ORDER:
            all_metrics.append(metrics_for(asset, policy, asset_returns[policy], policy_h[policy], baseline))
            if policy != "unhedged":
                seed_offset = (ASSETS.index(asset) + 1) * 100 + POLICY_ORDER.index(policy)
                all_tests.append(test_loss_reduction(asset, policy, baseline, asset_returns[policy], seed_offset))

        sample_summary[asset] = {
            "train_start": str(train.index.min().date()),
            "train_end": str(train.index.max().date()),
            "train_observations": int(len(train)),
            "oos_start": str(oos.index.min().date()),
            "oos_end": str(oos.index.max().date()),
            "oos_observations": int(len(oos)),
            "static_mv_hedge_ratio": static_h,
        }

    plot_spy_cumulative(all_returns)
    plot_metric_bars(all_metrics)
    plot_hedge_ratios(all_metrics, h_paths)
    verdict, findings = summarize_verdict(all_metrics, all_tests)

    local_benchmark_summary: dict[str, object] = {}
    for ticker in LOCAL_BENCHMARKS:
        if ticker not in returns.columns:
            continue
        series = returns[ticker].dropna()
        series = series.loc[series.index >= OOS_START]
        if series.empty:
            continue
        local_benchmark_summary[ticker] = {
            "oos_start": str(series.index.min().date()),
            "oos_end": str(series.index.max().date()),
            "observations": int(len(series)),
            "annual_vol": float(series.std(ddof=1) * math.sqrt(252)),
            "annual_return": float(series.mean() * 252),
            "max_drawdown": max_drawdown(series),
        }

    metrics_json = [asdict(row) for row in all_metrics]
    tests_json = [asdict(row) for row in all_tests]
    result: dict[str, object] = {
        "experiment_id": "K1548",
        "title": "Taiwan-investor USD/TWD equity currency hedge-ratio comparison",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data_source": {
            "provider": "yfinance",
            "tickers_requested": ALL_TICKERS,
            "usd_twd_ticker_used": fx_symbol,
            "start": START,
            "downloaded_price_start": str(prices.dropna(how="all").index.min().date()),
            "downloaded_price_end": str(prices.dropna(how="all").index.max().date()),
            "raw_return_csv": str(RAW_DATA_PATH.relative_to(OUT_DIR)),
        },
        "literature_basis": [
            {
                "citation": "Engle (2002), Dynamic Conditional Correlation",
                "url": "https://www.tandfonline.com/doi/abs/10.1198/073500102288618487",
                "role": "Motivates time-varying covariance hedge ratios; implemented here as EWMA/DCC-lite, not full DCC-GARCH.",
            },
            {
                "citation": "Kroner and Sultan (1993), time-varying distributions and dynamic hedging with FX futures",
                "url": "https://ideas.repec.org/a/cup/jfinqa/v28y1993i04p535-551_00.html",
                "role": "Canonical dynamic FX hedging benchmark.",
            },
            {
                "citation": "Campbell, Serfaty-de Medeiros, and Viceira style optimal currency hedging literature",
                "url": "https://www.tandfonline.com/doi/full/10.1080/0015198X.2019.1628556",
                "role": "Frames strategic currency-hedging policy for international equity portfolios.",
            },
        ],
        "design": {
            "train_end": str(TRAIN_END.date()),
            "oos_start": str(OOS_START.date()),
            "portfolio_return_formula": "(1+r_asset_usd)*(1+(1-h_t)*r_usdtwd)-1",
            "hedge_ratio_clip": [0.0, 1.5],
            "policies": {
                "unhedged": "h=0; full USD/TWD exposure",
                "full_hedge": "h=1; USD/TWD return removed; no carry or transaction cost model",
                "static_mv": "training-period minimum-variance h=1+cov(asset,fx)/var(fx)",
                "ewma_dcc_lite": "lambda=0.94 EWMA covariance/variance, h_t set before observing return_t",
                "hmm_regime": "2-state Gaussian HMM fit only on training returns; OOS h_t uses previous-day inferred state",
            },
            "lookahead_controls": [
                "EWMA h_t is computed before updating covariance with return_t.",
                "HMM model parameters and state-specific hedge ratios are train-only.",
                "OOS HMM hedge ratio for day t uses the state inferred through t-1, not day-t return.",
            ],
            "statistical_gate": "Positive daily squared-return reduction vs unhedged with HAC t>3 and block-bootstrap 95% CI above zero.",
        },
        "sample_summary": sample_summary,
        "local_twd_benchmarks": local_benchmark_summary,
        "metrics": metrics_json,
        "loss_reduction_tests": tests_json,
        "hmm_metadata": hmm_metadata,
        "figures": [
            "figures/k1548_spy_cumulative_returns.png",
            "figures/k1548_vol_reduction.png",
            "figures/k1548_downside_reduction.png",
            "figures/k1548_average_hedge_ratios.png",
            "figures/k1548_ewma_hedge_paths.png",
        ],
        "verdict": verdict,
        "main_findings": findings,
        "limitations": [
            "FX overlay ignores forward points, transaction costs, taxes, and actual hedge-instrument roll mechanics.",
            "EWMA/DCC-lite is a covariance proxy, not a full DCC-GARCH maximum-likelihood implementation.",
            "HMM parameters are train-only to avoid lookahead; regime classification may be too static for post-2020 shifts.",
            "USD ETFs are used as liquid proxies for Taiwan investors' global equity exposure; local fund wrappers may differ.",
            "No knowledge.json write is performed by this Codex experiment; promotion is left to the main K1259 writer gate.",
        ],
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> None:
    result = run()
    print(json.dumps({"experiment_id": result["experiment_id"], "verdict": result["verdict"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
