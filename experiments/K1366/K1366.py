#!/usr/bin/env python3
"""K1366: Historical second-moment shock response templates.

This is a narrow VIRF-inspired pilot, not a fully identified structural
MGARCH/BEKK implementation.  It uses an EWMA conditional covariance filter to
construct pre-shock baselines and historical post-shock response paths for
SPY/TLT/UUP/GLD/HYG.  Placebo calendar-date bootstraps provide empirical bands
for peak and persistence diagnostics.

Any predictive carryover diagnostic uses `signal.shift(1)`.  The main
event-response paths are descriptive historical templates after a realized
shock and are not trading signals.
"""

from __future__ import annotations

import argparse
import json
import math
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore", category=FutureWarning)

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
DATA_DIR.mkdir(parents=True, exist_ok=True)
FIG_DIR.mkdir(parents=True, exist_ok=True)

EXPERIMENT_ID = "K1366"
SEED = 42
START = "2016-01-01"
TICKERS = {
    "SPY": "US equity",
    "TLT": "long Treasury",
    "UUP": "US dollar",
    "GLD": "gold",
    "HYG": "high-yield credit",
}
EVENTS = {
    "2018Q4_equity_credit": {
        "date": "2018-10-10",
        "description": "Q4 2018 equity/credit selloff shock",
    },
    "2020_covid_liquidity": {
        "date": "2020-03-16",
        "description": "COVID liquidity crash shock",
    },
    "2022_rate_shock": {
        "date": "2022-06-13",
        "description": "2022 inflation/rate repricing shock before the June FOMC",
    },
    "2025_tariff_shock": {
        "date": "2025-04-03",
        "description": "2025 tariff-policy repricing shock",
    },
}
EWMA_LAMBDA = 0.94
INIT_WINDOW = 252
HORIZON = 60
PLACEBO_REPS = 1000
EXCLUDE_AROUND_EVENTS = 63
EPS = 1e-12

LITERATURE = [
    {
        "citation": "Hafner and Herwartz (2006), Volatility impulse response functions for multivariate GARCH models",
        "url": "https://econpapers.repec.org/RePEc:eee:econom:v132y2006i2p381-402",
        "role": "canonical VIRF definition for multivariate GARCH second-moment shock responses",
    },
    {
        "citation": "Fengler and Polivka (2025), Structural Volatility Impulse Response Analysis, Journal of Financial Econometrics",
        "url": "https://academic.oup.com/jfec/article/23/2/nbae036/7994364",
        "role": "motivates structural embedding, historical scenarios, and confidence intervals for VIRFs",
    },
    {
        "citation": "Bauwens, Laurent, and Rombouts (2006), Multivariate GARCH models: a survey",
        "url": "https://ideas.repec.org/a/jae/japmet/v21y2006i1p79-109.html",
        "role": "background on feasible MGARCH parameterizations and why a pilot should avoid overclaiming full identification",
    },
    {
        "citation": "DCC-GARCH VIRF extension (2020), Volatility impulse response analysis for DCC-GARCH models",
        "url": "https://ideas.repec.org/a/wly/jforec/v39y2020i5p788-796.html",
        "role": "connects VIRF-style responses with DCC-GARCH and network/connectedness diagnostics",
    },
]


@dataclass(frozen=True)
class EventResolution:
    name: str
    requested_date: str
    trading_date: pd.Timestamp
    description: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def cache_name(ticker: str) -> str:
    return ticker.replace("^", "").replace("=", "_").replace("-", "_") + ".csv"


def read_cached_close(path: Path) -> pd.Series:
    df = pd.read_csv(path, parse_dates=["Date"])
    if "Close" not in df.columns:
        raise ValueError(f"cache lacks Close column: {path}")
    out = df.set_index("Date")["Close"].sort_index()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out[~out.index.duplicated(keep="last")]


def load_close(ticker: str, refresh: bool) -> pd.Series:
    cache = DATA_DIR / cache_name(ticker)
    if cache.exists() and not refresh:
        return read_cached_close(cache)

    import yfinance as yf

    hist = yf.Ticker(ticker).history(start=START, auto_adjust=True)
    if hist is None or hist.empty:
        raise RuntimeError(f"empty yfinance history for {ticker}")
    close = hist["Close"].copy()
    close.index = pd.to_datetime(close.index).tz_localize(None)
    close = close[~close.index.duplicated(keep="last")].sort_index()
    close.to_frame("Close").reset_index().rename(columns={"index": "Date"}).to_csv(
        cache, index=False
    )
    return close


def load_prices(refresh: bool) -> tuple[pd.DataFrame, dict]:
    closes: dict[str, pd.Series] = {}
    failures: dict[str, str] = {}
    for ticker in TICKERS:
        try:
            closes[ticker] = load_close(ticker, refresh=refresh)
        except Exception as exc:
            failures[ticker] = str(exc)

    missing = [ticker for ticker in TICKERS if ticker not in closes]
    if missing:
        raise RuntimeError(f"required yfinance histories failed: {missing}")

    calendar = closes["SPY"].dropna().index
    prices = pd.DataFrame({k: s.reindex(calendar).ffill() for k, s in closes.items()})
    prices = prices.dropna()
    prices.index.name = "Date"
    prices.to_csv(DATA_DIR / "close_prices_yfinance.csv")

    coverage = {}
    for ticker, label in TICKERS.items():
        s = prices[ticker].dropna()
        coverage[ticker] = {
            "role": label,
            "first": str(s.index.min().date()),
            "last": str(s.index.max().date()),
            "n_daily_prices": int(len(s)),
            "load_error": failures.get(ticker),
        }
    return prices, coverage


def compute_returns(prices: pd.DataFrame) -> pd.DataFrame:
    returns = np.log(prices).diff().dropna()
    returns.to_csv(DATA_DIR / "daily_log_returns.csv")
    return returns


def ewma_covariances(returns: pd.DataFrame) -> dict[pd.Timestamp, np.ndarray]:
    """Forecast covariance for each date using only prior returns."""
    if len(returns) <= INIT_WINDOW + HORIZON + 5:
        raise ValueError("not enough returns for EWMA covariance experiment")
    arr = returns.to_numpy(dtype=float)
    dates = list(returns.index)
    h_prev = np.cov(arr[:INIT_WINDOW], rowvar=False)
    covs: dict[pd.Timestamp, np.ndarray] = {}
    for i, date in enumerate(dates):
        if i >= INIT_WINDOW:
            covs[date] = h_prev.copy()
        r = arr[i]
        h_prev = EWMA_LAMBDA * h_prev + (1.0 - EWMA_LAMBDA) * np.outer(r, r)
        h_prev = (h_prev + h_prev.T) / 2.0
    return covs


def cov_to_corr(cov: np.ndarray) -> np.ndarray:
    diag = np.sqrt(np.clip(np.diag(cov), EPS, None))
    corr = cov / np.outer(diag, diag)
    return np.clip(corr, -1.0, 1.0)


def resolve_events(index: pd.DatetimeIndex) -> list[EventResolution]:
    out: list[EventResolution] = []
    for name, cfg in EVENTS.items():
        requested = pd.Timestamp(cfg["date"])
        pos = index.searchsorted(requested)
        if pos >= len(index) - HORIZON - 2:
            raise ValueError(f"event too close to sample end: {name}")
        trading_date = index[pos]
        out.append(
            EventResolution(
                name=name,
                requested_date=cfg["date"],
                trading_date=trading_date,
                description=cfg["description"],
            )
        )
    return out


def response_path(
    covs: dict[pd.Timestamp, np.ndarray],
    returns: pd.DataFrame,
    event_date: pd.Timestamp,
) -> pd.DataFrame:
    dates = list(returns.index)
    start_pos = dates.index(event_date)
    base = covs[event_date]
    base_total_var = float(np.trace(base))
    base_corr = cov_to_corr(base)
    rows = []
    for h in range(HORIZON + 1):
        response_pos = start_pos + h + 1
        if response_pos >= len(dates):
            break
        response_date = dates[response_pos]
        cov = covs[response_date]
        total_var_lift = float(np.trace(cov) / base_total_var - 1.0)
        corr = cov_to_corr(cov)
        corr_delta = corr - base_corr
        offdiag = corr_delta[np.triu_indices_from(corr_delta, k=1)]
        row = {
            "horizon": h,
            "response_date": str(response_date.date()),
            "total_variance_lift": total_var_lift,
            "avg_abs_corr_delta": float(np.mean(np.abs(offdiag))),
            "mean_corr_delta": float(np.mean(offdiag)),
        }
        for i, ticker in enumerate(TICKERS):
            row[f"{ticker}_vol_lift"] = float(
                math.sqrt(max(cov[i, i], EPS) / max(base[i, i], EPS)) - 1.0
            )
        rows.append(row)
    return pd.DataFrame(rows)


def standardized_shock(
    covs: dict[pd.Timestamp, np.ndarray],
    returns: pd.DataFrame,
    event_date: pd.Timestamp,
) -> dict:
    r = returns.loc[event_date].to_numpy(dtype=float)
    cov = covs[event_date]
    diag = np.sqrt(np.clip(np.diag(cov), EPS, None))
    inv_cov = np.linalg.pinv(cov)
    mahal = float(r.T @ inv_cov @ r)
    return {
        "trading_date": str(event_date.date()),
        "log_returns": {ticker: float(returns.loc[event_date, ticker]) for ticker in TICKERS},
        "standardized_returns": {
            ticker: float(r[i] / diag[i]) for i, ticker in enumerate(TICKERS)
        },
        "mahalanobis_squared": mahal,
        "mahalanobis_chi2_p_upper": float(stats.chi2.sf(mahal, df=len(TICKERS))),
    }


def valid_placebo_dates(
    returns: pd.DataFrame, events: list[EventResolution]
) -> list[pd.Timestamp]:
    idx = returns.index
    start = INIT_WINDOW + 5
    end = len(idx) - HORIZON - 2
    excluded = pd.Series(False, index=idx)
    for event in events:
        loc = idx.get_loc(event.trading_date)
        lo = max(0, loc - EXCLUDE_AROUND_EVENTS)
        hi = min(len(idx), loc + EXCLUDE_AROUND_EVENTS + HORIZON + 2)
        excluded.iloc[lo:hi] = True
    candidates = [
        idx[i]
        for i in range(start, end)
        if not bool(excluded.iloc[i]) and idx[i] in returns.index
    ]
    if len(candidates) < 250:
        raise ValueError("too few placebo dates after exclusions")
    return candidates


def placebo_bootstrap(
    covs: dict[pd.Timestamp, np.ndarray],
    returns: pd.DataFrame,
    candidates: list[pd.Timestamp],
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    sampled = rng.choice(np.array(candidates, dtype="datetime64[ns]"), size=PLACEBO_REPS, replace=True)
    paths = []
    summaries = []
    for rep, raw_date in enumerate(sampled):
        event_date = pd.Timestamp(raw_date)
        path = response_path(covs, returns, event_date)
        path["rep"] = rep
        paths.append(path[["rep", "horizon", "total_variance_lift", "avg_abs_corr_delta"]])
        summaries.append(
            {
                "rep": rep,
                "pseudo_event_date": str(event_date.date()),
                "peak_total_variance_lift": float(path["total_variance_lift"].max()),
                "avg20_total_variance_lift": float(
                    path.loc[path["horizon"] <= 20, "total_variance_lift"].mean()
                ),
                "peak_avg_abs_corr_delta": float(path["avg_abs_corr_delta"].max()),
            }
        )
    path_df = pd.concat(paths, ignore_index=True)
    summary_df = pd.DataFrame(summaries)
    path_df.to_csv(DATA_DIR / "placebo_response_paths.csv", index=False)
    summary_df.to_csv(DATA_DIR / "placebo_summary.csv", index=False)
    return path_df, summary_df


def empirical_p_ge(observed: float, null_values: pd.Series) -> float:
    values = null_values.dropna().to_numpy(dtype=float)
    return float((np.sum(values >= observed) + 1.0) / (len(values) + 1.0))


def first_decay_day(path: pd.DataFrame, threshold: float) -> int | None:
    after_peak = path.loc[path["total_variance_lift"].idxmax() :]
    hit = after_peak[after_peak["total_variance_lift"] <= threshold]
    if hit.empty:
        return None
    return int(hit.iloc[0]["horizon"])


def summarize_event(
    event: EventResolution,
    path: pd.DataFrame,
    shock: dict,
    placebo_summary: pd.DataFrame,
    placebo_bands: pd.DataFrame,
) -> dict:
    peak_row = path.loc[path["total_variance_lift"].idxmax()]
    peak = float(peak_row["total_variance_lift"])
    avg20 = float(path.loc[path["horizon"] <= 20, "total_variance_lift"].mean())
    peak_corr = float(path["avg_abs_corr_delta"].max())
    half_threshold = max(0.0, peak / 2.0)
    p_peak = empirical_p_ge(peak, placebo_summary["peak_total_variance_lift"])
    p_avg20 = empirical_p_ge(avg20, placebo_summary["avg20_total_variance_lift"])
    p_corr = empirical_p_ge(peak_corr, placebo_summary["peak_avg_abs_corr_delta"])

    peak_asset_lifts = {
        ticker: float(path[f"{ticker}_vol_lift"].max()) for ticker in TICKERS
    }
    h0_band = placebo_bands.loc[placebo_bands["horizon"] == 0].iloc[0]
    return {
        "event": event.name,
        "description": event.description,
        "requested_date": event.requested_date,
        "trading_date": str(event.trading_date.date()),
        "shock": shock,
        "peak_total_variance_lift": peak,
        "peak_total_variance_horizon": int(peak_row["horizon"]),
        "avg_0_20_total_variance_lift": avg20,
        "peak_avg_abs_corr_delta": peak_corr,
        "p_peak_vs_placebo": p_peak,
        "p_avg20_vs_placebo": p_avg20,
        "p_peak_corr_vs_placebo": p_corr,
        "half_life_trading_days": first_decay_day(path, half_threshold),
        "zero_decay_trading_days": first_decay_day(path, 0.0),
        "peak_asset_vol_lifts": peak_asset_lifts,
        "h0_placebo_5_95_band": {
            "p05": float(h0_band["total_variance_lift_p05"]),
            "p95": float(h0_band["total_variance_lift_p95"]),
        },
    }


def build_placebo_bands(placebo_paths: pd.DataFrame) -> pd.DataFrame:
    bands = (
        placebo_paths.groupby("horizon")
        .agg(
            total_variance_lift_p05=("total_variance_lift", lambda x: float(np.quantile(x, 0.05))),
            total_variance_lift_p50=("total_variance_lift", lambda x: float(np.quantile(x, 0.50))),
            total_variance_lift_p95=("total_variance_lift", lambda x: float(np.quantile(x, 0.95))),
            avg_abs_corr_delta_p95=("avg_abs_corr_delta", lambda x: float(np.quantile(x, 0.95))),
        )
        .reset_index()
    )
    bands.to_csv(DATA_DIR / "placebo_bands_by_horizon.csv", index=False)
    return bands


def build_lagged_carryover_diagnostic(
    returns: pd.DataFrame,
    event_dates: list[pd.Timestamp],
    covs: dict[pd.Timestamp, np.ndarray],
) -> dict:
    """Small lookahead guard diagnostic: event shock at t predicts t+1 EWMA lift."""
    signal = pd.Series(0.0, index=returns.index, name="event_shock_signal")
    signal.loc[event_dates] = 1.0
    lagged_signal = signal.shift(1)
    total_var = pd.Series({date: float(np.trace(cov)) for date, cov in covs.items()})
    total_var = total_var.reindex(returns.index)
    one_day_lift = total_var.pct_change()
    panel = pd.DataFrame(
        {
            "event_shock_signal": signal,
            "event_shock_signal_lag1": lagged_signal,
            "one_day_total_var_lift": one_day_lift,
        }
    ).dropna()
    event_next = panel.loc[panel["event_shock_signal_lag1"] == 1.0, "one_day_total_var_lift"]
    non_event = panel.loc[panel["event_shock_signal_lag1"] == 0.0, "one_day_total_var_lift"]
    t_stat, p_value = stats.ttest_ind(event_next, non_event, equal_var=False)
    panel.to_csv(DATA_DIR / "lagged_event_carryover_panel.csv")
    return {
        "purpose": "guardrail diagnostic only; central event templates are descriptive",
        "lookahead_policy": "event_shock_signal_lag1 = event_shock_signal.shift(1)",
        "n_event_next_days": int(len(event_next)),
        "n_non_event_days": int(len(non_event)),
        "event_next_day_mean_lift": float(event_next.mean()),
        "non_event_day_mean_lift": float(non_event.mean()),
        "welch_t": float(t_stat),
        "welch_p": float(p_value),
    }


def plot_total_variance_paths(
    event_paths: dict[str, pd.DataFrame], bands: pd.DataFrame
) -> str:
    fig, ax = plt.subplots(figsize=(10, 5.8))
    x = bands["horizon"].to_numpy()
    p05 = bands["total_variance_lift_p05"].to_numpy()
    p95 = bands["total_variance_lift_p95"].to_numpy()
    p50 = bands["total_variance_lift_p50"].to_numpy()
    ax.fill_between(x, p05, p95, color="#d9dee7", alpha=0.7, label="Placebo 5-95% band")
    ax.plot(x, p50, color="#7a8494", linewidth=1.5, label="Placebo median")
    colors = ["#005f73", "#ae2012", "#ca6702", "#6a4c93"]
    for color, (name, path) in zip(colors, event_paths.items(), strict=False):
        ax.plot(
            path["horizon"],
            path["total_variance_lift"],
            linewidth=2.2,
            label=name,
            color=color,
        )
    ax.axhline(0, color="#2f3437", linewidth=0.8)
    ax.set_title("K1366 total covariance trace response after historical shocks")
    ax.set_xlabel("Trading days after event shock")
    ax.set_ylabel("EWMA total variance lift vs pre-shock baseline")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(alpha=0.25)
    out = FIG_DIR / "k1366_total_variance_response.png"
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return str(out.relative_to(HERE))


def plot_asset_peak_heatmap(summaries: list[dict]) -> str:
    heat = pd.DataFrame(
        [s["peak_asset_vol_lifts"] for s in summaries],
        index=[s["event"] for s in summaries],
    )
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    im = ax.imshow(heat.to_numpy(), cmap="RdYlBu_r", aspect="auto")
    ax.set_xticks(np.arange(len(heat.columns)), labels=heat.columns)
    ax.set_yticks(np.arange(len(heat.index)), labels=heat.index)
    for i in range(len(heat.index)):
        for j in range(len(heat.columns)):
            ax.text(j, i, f"{heat.iloc[i, j]:+.0%}", ha="center", va="center", fontsize=8)
    ax.set_title("Peak asset vol lift by historical shock")
    cbar = fig.colorbar(im, ax=ax, shrink=0.85)
    cbar.set_label("Peak vol lift")
    out = FIG_DIR / "k1366_asset_peak_vol_lifts.png"
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return str(out.relative_to(HERE))


def plot_corr_response(event_paths: dict[str, pd.DataFrame], bands: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(10, 5.8))
    x = bands["horizon"].to_numpy()
    ax.plot(
        x,
        bands["avg_abs_corr_delta_p95"].to_numpy(),
        color="#7a8494",
        linestyle="--",
        linewidth=1.5,
        label="Placebo 95% avg |corr delta|",
    )
    colors = ["#005f73", "#ae2012", "#ca6702", "#6a4c93"]
    for color, (name, path) in zip(colors, event_paths.items(), strict=False):
        ax.plot(
            path["horizon"],
            path["avg_abs_corr_delta"],
            linewidth=2.0,
            label=name,
            color=color,
        )
    ax.set_title("Average absolute correlation-matrix change after shocks")
    ax.set_xlabel("Trading days after event shock")
    ax.set_ylabel("Average absolute off-diagonal correlation change")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(alpha=0.25)
    out = FIG_DIR / "k1366_correlation_response.png"
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)
    return str(out.relative_to(HERE))


def verdict_from_summaries(summaries: list[dict]) -> tuple[str, str]:
    strong = [
        s
        for s in summaries
        if s["p_peak_vs_placebo"] <= 0.05
        and s["peak_total_variance_lift"] > 0
        and (s["half_life_trading_days"] is None or s["half_life_trading_days"] >= 5)
    ]
    corr = [s for s in summaries if s["p_peak_corr_vs_placebo"] <= 0.05]
    if len(strong) >= 2 and len(corr) >= 1:
        return (
            "CONDITIONAL_PASS_SCENARIO_LIBRARY",
            "At least two historical shocks have statistically unusual total-variance responses and at least one correlation-response diagnostic passes the placebo test. Use as a scenario-template library, not a structural causal VIRF.",
        )
    if len(strong) >= 2:
        return (
            "PARTIAL_VARIANCE_TEMPLATE_CORR_NULL",
            "At least two shocks clear the unusual total-variance response gate, but no event clears the correlation-response placebo gate. Use as a variance scenario-template library only; do not claim structural covariance-network VIRF evidence.",
        )
    if len(strong) >= 1:
        return (
            "PARTIAL_SINGLE_SHOCK_TEMPLATE",
            "Only one shock clears the unusual-response gate; the library is descriptive and underpowered for broad scenario claims.",
        )
    return (
        "NULL_PLACEBO_NOT_EXCEEDED",
        "Historical event responses do not exceed the placebo-date distribution enough to support a scenario-library claim.",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="redownload yfinance caches")
    args = parser.parse_args()

    rng = np.random.default_rng(SEED)
    prices, coverage = load_prices(refresh=args.refresh)
    returns = compute_returns(prices)
    covs = ewma_covariances(returns)
    events = resolve_events(returns.index)
    candidates = valid_placebo_dates(returns, events)
    placebo_paths, placebo_summary = placebo_bootstrap(covs, returns, candidates, rng)
    placebo_bands = build_placebo_bands(placebo_paths)

    event_paths: dict[str, pd.DataFrame] = {}
    event_summaries: list[dict] = []
    template_rows = []
    for event in events:
        path = response_path(covs, returns, event.trading_date)
        path["event"] = event.name
        path["trading_date"] = str(event.trading_date.date())
        event_paths[event.name] = path
        template_rows.append(path)
        shock = standardized_shock(covs, returns, event.trading_date)
        event_summaries.append(
            summarize_event(event, path, shock, placebo_summary, placebo_bands)
        )

    templates = pd.concat(template_rows, ignore_index=True)
    templates.to_csv(DATA_DIR / "K1366_response_templates.csv", index=False)
    carryover = build_lagged_carryover_diagnostic(
        returns, [event.trading_date for event in events], covs
    )

    figures = [
        plot_total_variance_paths(event_paths, placebo_bands),
        plot_asset_peak_heatmap(event_summaries),
        plot_corr_response(event_paths, placebo_bands),
    ]
    verdict, conclusion = verdict_from_summaries(event_summaries)

    results = {
        "experiment_id": EXPERIMENT_ID,
        "generated_at": utc_now(),
        "seed": SEED,
        "data": {
            "source": "yfinance adjusted close",
            "tickers": TICKERS,
            "start_requested": START,
            "sample_start": str(returns.index.min().date()),
            "sample_end": str(returns.index.max().date()),
            "n_daily_returns": int(len(returns)),
            "covariance_sample_start": str(min(covs).date()),
            "coverage": coverage,
        },
        "method": {
            "scope": "VIRF-inspired historical EWMA covariance response template; not a structural BEKK/DCC identification",
            "ewma_lambda": EWMA_LAMBDA,
            "init_window": INIT_WINDOW,
            "horizon_trading_days": HORIZON,
            "placebo_reps": PLACEBO_REPS,
            "placebo_exclusion_days_around_events": EXCLUDE_AROUND_EVENTS,
            "placebo_candidate_dates": int(len(candidates)),
        },
        "literature": LITERATURE,
        "events": event_summaries,
        "lagged_carryover_diagnostic": carryover,
        "success_criteria": {
            "strong_scenario_library": ">=2 events with p_peak_vs_placebo <= 0.05, positive peak response, and half-life >=5 trading days or not decayed within horizon; plus >=1 event with p_peak_corr_vs_placebo <= 0.05",
            "harvey_dm": "not applicable; this is not a forecast horse race",
        },
        "verdict": verdict,
        "conclusion": conclusion,
        "artifacts": {
            "templates_csv": "data/K1366_response_templates.csv",
            "placebo_summary_csv": "data/placebo_summary.csv",
            "placebo_bands_csv": "data/placebo_bands_by_horizon.csv",
            "lagged_carryover_panel_csv": "data/lagged_event_carryover_panel.csv",
            "figures": figures,
        },
        "limitations": [
            "EWMA covariance is a feasible public-data filter, not a fitted structural MGARCH/BEKK model.",
            "Event dates are manually specified historical scenarios; results are sensitive to date choice.",
            "Placebo-date bands are empirical diagnostics, not asymptotic VIRF confidence intervals.",
            "Close-to-close ETF returns omit intraday realized variance and option-implied volatility.",
            "The 2025 tariff shock is represented by the first large repricing trading day in the ETF data and should be rechecked if a more exact policy timestamp is required.",
        ],
    }
    (HERE / "K1366_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n"
    )
    print(json.dumps({"ok": True, "verdict": verdict, "figures": figures}, indent=2))


if __name__ == "__main__":
    main()
