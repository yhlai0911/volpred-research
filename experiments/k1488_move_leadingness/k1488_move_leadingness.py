#!/usr/bin/env python3
"""K1488: MOVE leadingness for equity volatility and stock-bond allocation.

Research question:
  Does Treasury-market implied volatility (MOVE) add information beyond VIX
  and recent realized volatility for (a) next-day SPY variance forecasts and
  (b) simple stock-bond allocation rules?

Hard anti-lookahead rule:
  All forecast/allocation signals are shifted by one trading period before use.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


SEED = 42
START = "2003-01-01"
END = "2026-06-13"
TICKERS = ["SPY", "TLT", "IEF", "^VIX", "^MOVE"]
OUT = Path(__file__).resolve().parent
EPS = 1e-10


@dataclass
class ForecastResult:
    dates: pd.DatetimeIndex
    actual: np.ndarray
    forecasts: dict[str, np.ndarray]


def _download_prices() -> pd.DataFrame:
    """Fetch adjusted closes and pin the exact snapshot used by the experiment."""
    cache = OUT / "close_prices.csv"
    if cache.exists():
        px = pd.read_csv(cache, parse_dates=["Date"], index_col="Date")
        return px.sort_index()

    raw = yf.download(
        TICKERS,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned an empty dataframe")
    close = raw["Close"].copy()
    close = close.rename(columns={"^VIX": "VIX", "^MOVE": "MOVE"})
    close = close.dropna(how="all")
    if len(close.dropna(subset=["SPY", "TLT", "IEF", "VIX", "MOVE"])) < 3000:
        raise RuntimeError("insufficient common observations from yfinance")
    close.to_csv(cache, index_label="Date")
    return close


def _features(prices: pd.DataFrame) -> pd.DataFrame:
    px = prices.dropna(subset=["SPY", "VIX", "MOVE"]).copy()
    ret = np.log(px["SPY"]).diff()
    r2 = ret.pow(2)
    move_log = np.log(px["MOVE"])
    move_z = (move_log - move_log.rolling(252).mean()) / move_log.rolling(252).std()

    df = pd.DataFrame(index=px.index)
    df["target_r2"] = r2
    df["target_log_r2"] = np.log(r2 + EPS)
    df["log_rv1_lag"] = np.log(r2.shift(1) + EPS)
    df["log_rv5_lag"] = np.log(r2.rolling(5).mean().shift(1) + EPS)
    df["log_rv22_lag"] = np.log(r2.rolling(22).mean().shift(1) + EPS)
    # VIX is an annualized 30-day implied volatility. Convert to daily variance,
    # then lag by one trading day so the forecast for t only uses t-1 information.
    df["log_vix_var_lag"] = np.log(((px["VIX"] / 100.0) ** 2 / 252.0).shift(1) + EPS)
    df["move_z_lag"] = move_z.shift(1)
    df["move_chg5_lag"] = move_log.diff(5).shift(1)
    return df.dropna()


def _ols_forecast(train: pd.DataFrame, row: pd.Series, features: list[str]) -> float:
    x = train[features].to_numpy(dtype=float)
    y = train["target_log_r2"].to_numpy(dtype=float)
    x = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    x_next = np.array([1.0, *[float(row[f]) for f in features]])
    return float(np.exp(x_next @ beta))


def rolling_forecasts(df: pd.DataFrame) -> ForecastResult:
    models = {
        "HAR_RV": ["log_rv1_lag", "log_rv5_lag", "log_rv22_lag"],
        "HAR_VIX": ["log_rv1_lag", "log_rv5_lag", "log_rv22_lag", "log_vix_var_lag"],
        "HAR_VIX_MOVE": [
            "log_rv1_lag",
            "log_rv5_lag",
            "log_rv22_lag",
            "log_vix_var_lag",
            "move_z_lag",
            "move_chg5_lag",
        ],
    }
    window = 1260
    oos_start = pd.Timestamp("2010-01-04")
    rows: list[pd.Timestamp] = []
    forecasts = {name: [] for name in models}
    actual: list[float] = []

    for pos in range(window, len(df)):
        date = df.index[pos]
        if date < oos_start:
            continue
        train = df.iloc[pos - window : pos]
        row = df.iloc[pos]
        rows.append(date)
        actual.append(float(max(row["target_r2"], EPS)))
        for name, cols in models.items():
            forecasts[name].append(max(_ols_forecast(train, row, cols), EPS))

    return ForecastResult(
        dates=pd.DatetimeIndex(rows),
        actual=np.asarray(actual, dtype=float),
        forecasts={k: np.asarray(v, dtype=float) for k, v in forecasts.items()},
    )


def _hac_predictive_regression(df: pd.DataFrame) -> dict:
    """Full-sample diagnostic regression; primary evidence is OOS QLIKE."""
    import statsmodels.api as sm

    y = df["target_log_r2"]
    x = sm.add_constant(
        df[
            [
                "log_rv1_lag",
                "log_rv5_lag",
                "log_rv22_lag",
                "log_vix_var_lag",
                "move_z_lag",
                "move_chg5_lag",
            ]
        ]
    )
    fit = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    return {
        "n": int(fit.nobs),
        "r2": float(fit.rsquared),
        "params": {k: float(v) for k, v in fit.params.items()},
        "tvalues_hac": {k: float(v) for k, v in fit.tvalues.items()},
        "pvalues_hac": {k: float(v) for k, v in fit.pvalues.items()},
    }


def _perf(monthly_ret: pd.Series) -> dict:
    r = monthly_ret.dropna()
    nav = (1 + r).cumprod()
    years = len(r) / 12.0
    ann_ret = float(nav.iloc[-1] ** (1 / years) - 1) if years > 0 else np.nan
    ann_vol = float(r.std(ddof=1) * np.sqrt(12))
    sharpe = float(ann_ret / ann_vol) if ann_vol > 0 else np.nan
    dd = nav / nav.cummax() - 1
    return {
        "n_months": int(len(r)),
        "cumulative_return": float(nav.iloc[-1] - 1),
        "annual_return": ann_ret,
        "annual_vol": ann_vol,
        "sharpe": sharpe,
        "max_drawdown": float(dd.min()),
    }


def _block_bootstrap_sharpe_diff(
    r1: pd.Series,
    r2: pd.Series,
    *,
    block_size: int = 6,
    reps: int = 1000,
) -> dict:
    aligned = pd.concat([r1, r2], axis=1).dropna()
    a = aligned.iloc[:, 0].to_numpy()
    b = aligned.iloc[:, 1].to_numpy()
    n = len(aligned)
    rng = np.random.default_rng(SEED)

    def sharpe(x: np.ndarray) -> float:
        vol = np.std(x, ddof=1) * np.sqrt(12)
        if vol <= 0:
            return np.nan
        nav = np.prod(1 + x)
        ann = nav ** (12 / len(x)) - 1
        return float(ann / vol)

    obs = sharpe(a) - sharpe(b)
    sims = []
    starts = np.arange(0, max(n - block_size + 1, 1))
    for _ in range(reps):
        idx: list[int] = []
        while len(idx) < n:
            s = int(rng.choice(starts))
            idx.extend(range(s, min(s + block_size, n)))
        idx_arr = np.asarray(idx[:n])
        sims.append(sharpe(a[idx_arr]) - sharpe(b[idx_arr]))
    sims_arr = np.asarray(sims, dtype=float)
    return {
        "observed_sharpe_diff": float(obs),
        "bootstrap_mean": float(np.nanmean(sims_arr)),
        "ci_95": [float(x) for x in np.nanpercentile(sims_arr, [2.5, 97.5])],
        "p_two_sided": float(np.mean(np.abs(sims_arr) >= abs(obs))),
        "reps": reps,
        "block_size_months": block_size,
    }


def allocation_test(prices: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    daily = prices.dropna(subset=["SPY", "TLT", "IEF", "MOVE"]).copy()
    daily_ret = daily[["SPY", "TLT", "IEF"]].pct_change()
    monthly_ret = (1 + daily_ret).resample("ME").prod() - 1

    move_log = np.log(daily["MOVE"])
    move_z_daily = (move_log - move_log.rolling(252).mean()) / move_log.rolling(252).std()
    # Month-end signal is shifted by one month before being applied.
    move_z_signal = move_z_daily.resample("ME").last().shift(1).reindex(monthly_ret.index)
    data = monthly_ret.join(move_z_signal.rename("move_z_lag")).dropna()
    data = data.loc[data.index >= "2010-01-31"]

    stress = data["move_z_lag"] > 1.0
    strategies = pd.DataFrame(index=data.index)
    strategies["static_60_40_tlt"] = 0.60 * data["SPY"] + 0.40 * data["TLT"]
    strategies["static_60_40_ief"] = 0.60 * data["SPY"] + 0.40 * data["IEF"]
    strategies["move_duration_switch"] = np.where(
        stress,
        0.60 * data["SPY"] + 0.40 * data["IEF"],
        0.60 * data["SPY"] + 0.40 * data["TLT"],
    )
    strategies["move_defensive_switch"] = np.where(
        stress,
        0.40 * data["SPY"] + 0.60 * data["IEF"],
        0.60 * data["SPY"] + 0.40 * data["TLT"],
    )
    strategies["spy_bh"] = data["SPY"]

    metrics = {col: _perf(strategies[col]) for col in strategies.columns}
    static_names = ["static_60_40_tlt", "static_60_40_ief"]
    best_static = max(static_names, key=lambda name: metrics[name]["sharpe"])
    boot = {
        f"{name}_vs_{best_static}": _block_bootstrap_sharpe_diff(
            strategies[name], strategies[best_static]
        )
        for name in ["move_duration_switch", "move_defensive_switch"]
    }

    diagnostics = {
        "n_months": int(len(data)),
        "move_stress_month_share": float(stress.mean()),
        "move_z_threshold": 1.0,
        "best_static_oos": best_static,
    }
    result = {
        "sample": {
            "start": data.index[0].date().isoformat(),
            "end": data.index[-1].date().isoformat(),
        },
        "signal": "MOVE log z-score using trailing 252 trading days; month-end signal shifted 1 month",
        "metrics": metrics,
        "diagnostics": diagnostics,
        "bootstrap_tests": boot,
    }
    nav = (1 + strategies).cumprod()
    nav["move_z_lag"] = data["move_z_lag"]
    return result, nav


def make_figures(
    forecast: ForecastResult,
    allocation_nav: pd.DataFrame,
) -> None:
    losses = {
        name: qlike_pointwise(forecast.actual, pred)
        for name, pred in forecast.forecasts.items()
    }
    diff = pd.DataFrame(index=forecast.dates)
    diff["HAR_VIX_minus_HAR_VIX_MOVE"] = losses["HAR_VIX"] - losses["HAR_VIX_MOVE"]
    diff["cum_loss_diff"] = diff["HAR_VIX_minus_HAR_VIX_MOVE"].cumsum()

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=160)
    ax.plot(diff.index, diff["cum_loss_diff"], color="#22577a", lw=1.5)
    ax.axhline(0, color="#555555", lw=1, ls="--")
    ax.set_title("Cumulative QLIKE loss difference: HAR-VIX minus HAR-VIX-MOVE")
    ax.set_ylabel("Positive means MOVE-augmented model lower loss")
    fig.tight_layout()
    fig.savefig(OUT / "fig_a_forecast_loss_diff.png", bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5.8), dpi=160)
    plot_cols = [
        "static_60_40_tlt",
        "static_60_40_ief",
        "move_duration_switch",
        "move_defensive_switch",
    ]
    for col in plot_cols:
        ax.plot(allocation_nav.index, allocation_nav[col], label=col, lw=1.7)
    stress = allocation_nav["move_z_lag"] > 1.0
    for date in allocation_nav.index[stress]:
        ax.axvspan(date, date + pd.offsets.MonthEnd(1), color="#e63946", alpha=0.05)
    ax.set_title("MOVE-gated allocation vs static 60/40 variants")
    ax.set_ylabel("Growth of $1")
    ax.legend(frameon=True, ncols=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "fig_b_allocation_nav.png", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    prices = _download_prices()
    df = _features(prices)
    forecast = rolling_forecasts(df)

    qlike_scores = {
        name: qlike(forecast.actual, pred)
        for name, pred in forecast.forecasts.items()
    }
    losses = {
        name: qlike_pointwise(forecast.actual, pred)
        for name, pred in forecast.forecasts.items()
    }
    dm = {
        "HAR_VIX_MOVE_vs_HAR_VIX": {
            "t": dm_test(losses["HAR_VIX_MOVE"], losses["HAR_VIX"], h=1)[0],
            "p": dm_test(losses["HAR_VIX_MOVE"], losses["HAR_VIX"], h=1)[1],
        },
        "HAR_VIX_vs_HAR_RV": {
            "t": dm_test(losses["HAR_VIX"], losses["HAR_RV"], h=1)[0],
            "p": dm_test(losses["HAR_VIX"], losses["HAR_RV"], h=1)[1],
        },
    }
    hac = _hac_predictive_regression(df.loc[df.index >= "2010-01-04"])
    allocation, allocation_nav = allocation_test(prices)
    make_figures(forecast, allocation_nav)

    verdict_forecast = (
        "PASS"
        if dm["HAR_VIX_MOVE_vs_HAR_VIX"]["t"] < -3.0
        and qlike_scores["HAR_VIX_MOVE"] < qlike_scores["HAR_VIX"]
        else "NULL"
    )
    best_static = allocation["diagnostics"]["best_static_oos"]
    alloc_tests = allocation["bootstrap_tests"]
    dynamic_beats = [
        name
        for name, test in alloc_tests.items()
        if test["observed_sharpe_diff"] > 0 and test["ci_95"][0] > 0
    ]
    verdict_allocation = "PASS" if dynamic_beats else "NULL"
    overall = "PASS" if verdict_forecast == "PASS" or verdict_allocation == "PASS" else "NULL"

    result = {
        "experiment_id": "k1488_move_leadingness",
        "title": "MOVE leadingness for SPY volatility and stock-bond allocation",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data_source": {
            "source": "Yahoo Finance via yfinance, auto_adjust=True",
            "tickers": TICKERS,
            "start": START,
            "end_exclusive": END,
            "snapshot_file": "close_prices.csv",
        },
        "related_prior_work": {
            "K1442": "MOVE/VIX ratio around CPI; event-study NULL for vol-crush pattern",
            "K1460": "Lagged stock-bond correlation regime 60/40 switching underperformed static 60/40 IEF",
        },
        "forecast_test": {
            "target": "SPY close-to-close squared log return at t",
            "information_set": "all model features explicitly shifted by 1 trading day",
            "oos_start": forecast.dates[0].date().isoformat(),
            "oos_end": forecast.dates[-1].date().isoformat(),
            "n_oos_days": int(len(forecast.dates)),
            "rolling_window_days": 1260,
            "qlike": qlike_scores,
            "dm_tests": dm,
            "hac_full_sample_diagnostic": hac,
            "verdict": verdict_forecast,
        },
        "allocation_test": allocation,
        "verdicts": {
            "forecast": verdict_forecast,
            "allocation": verdict_allocation,
            "overall": overall,
            "best_static_allocation_benchmark": best_static,
        },
        "charts": [
            "fig_a_forecast_loss_diff.png",
            "fig_b_allocation_nav.png",
        ],
        "methodology_flags": {
            "lookahead_guard": "features use shift(1); month-end MOVE signal shifted 1 month before allocation",
            "bootstrap_seed": SEED,
            "dm_harvey_threshold": "|t| > 3.0",
            "null_results_reported": True,
        },
    }

    (OUT / "k1488_move_leadingness_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["verdicts"], ensure_ascii=False, indent=2))
    print(json.dumps(result["forecast_test"]["qlike"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
