#!/usr/bin/env python3
"""Intraday vs overnight pseudo-VRP decomposition.

The task asks for a yfinance-only variant of the intraday/overnight VRP
question. Because free daily OHLC data do not contain option-implied variance,
this script uses a rolling one-step-ahead GARCH(1,1) variance forecast as an
ex-ante physical-measure proxy and labels the result as pseudo-VRP.
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from arch import arch_model


SEED = 42
TICKERS = ["SPY", "QQQ", "IWM", "EFA"]
START = "2003-01-01"
END = "2026-06-15"
ANALYSIS_START = pd.Timestamp("2007-01-03")
OOS_START = pd.Timestamp("2018-01-02")

GARCH_WINDOW = 1000
GARCH_REFIT_EVERY = 21
SHARE_WINDOW = 252
BOOTSTRAP_REPS = 1000
BOOTSTRAP_BLOCK = 21
HAC_LAGS = 5
EPS = 1e-12

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
RESULTS_PATH = HERE / "research_intraday_vs_overnight_vrp_results.json"
FIG_SHARE = HERE / "fig_session_variance_shares.png"
FIG_PREDICT = HERE / "fig_predictive_tstats.png"


@dataclass(frozen=True)
class RegressionResult:
    nobs: int
    coef_overnight: float
    t_overnight: float
    p_overnight: float
    coef_intraday: float
    t_intraday: float
    p_intraday: float
    r2: float


def download_ohlc() -> dict[str, pd.DataFrame]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw = yf.download(TICKERS, start=START, end=END, auto_adjust=True, progress=False, threads=False)
    if raw.empty:
        raise RuntimeError("yfinance returned no data")
    if not isinstance(raw.columns, pd.MultiIndex):
        raise RuntimeError("Expected MultiIndex OHLC columns for multiple tickers")

    out: dict[str, pd.DataFrame] = {}
    for field in ["Open", "High", "Low", "Close"]:
        frame = raw[field].copy()[TICKERS].dropna(how="any")
        frame.index = pd.to_datetime(frame.index)
        out[field.lower()] = frame
        frame.to_csv(DATA_DIR / f"{field.lower()}.csv")
    return out


def one_step_garch_variance(close_to_close: pd.Series) -> pd.Series:
    """Rolling/refit one-step GARCH variance forecast in decimal-return units.

    The forecast for day t is computed from returns through t-1. Parameters are
    refit every GARCH_REFIT_EVERY observations on a trailing GARCH_WINDOW sample.
    """

    r_pct = close_to_close.dropna() * 100.0
    values = r_pct.to_numpy(dtype=float)
    index = r_pct.index
    forecasts_pct2 = np.full(len(r_pct), np.nan, dtype=float)

    for fit_start in range(GARCH_WINDOW, len(r_pct), GARCH_REFIT_EVERY):
        sample = values[fit_start - GARCH_WINDOW : fit_start]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = arch_model(sample, mean="Zero", vol="GARCH", p=1, q=1, dist="normal", rescale=False)
            fit = model.fit(disp="off", show_warning=False)

        params = fit.params
        omega = float(params["omega"])
        alpha = float(params["alpha[1]"])
        beta = float(params["beta[1]"])
        h_prev = float(np.asarray(fit.conditional_volatility)[-1] ** 2)
        block_end = min(fit_start + GARCH_REFIT_EVERY, len(r_pct))

        for i in range(fit_start, block_end):
            h_t = omega + alpha * values[i - 1] ** 2 + beta * h_prev
            forecasts_pct2[i] = max(h_t, EPS)
            h_prev = h_t

    return pd.Series(forecasts_pct2 / 10000.0, index=index, name="garch_total_var")


def build_components(ohlc: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    open_px = ohlc["open"]
    close_px = ohlc["close"]
    overnight = np.log(open_px / close_px.shift(1))
    intraday = np.log(close_px / open_px)
    close_to_close = np.log(close_px / close_px.shift(1))

    components: dict[str, pd.DataFrame] = {}
    for ticker in TICKERS:
        df = pd.DataFrame(
            {
                "overnight_ret": overnight[ticker],
                "intraday_ret": intraday[ticker],
                "close_to_close_ret": close_to_close[ticker],
            }
        ).dropna()
        df = df[df.index >= ANALYSIS_START].copy()
        df["overnight_var"] = df["overnight_ret"] ** 2
        df["intraday_var"] = df["intraday_ret"] ** 2
        df["session_var"] = df["overnight_var"] + df["intraday_var"]
        df["close_to_close_var"] = df["close_to_close_ret"] ** 2
        df["covariance_residual_var"] = df["close_to_close_var"] - df["session_var"]

        garch_total = one_step_garch_variance(df["close_to_close_ret"]).reindex(df.index)
        share_raw = (
            df["overnight_var"].rolling(SHARE_WINDOW).sum()
            / df["session_var"].rolling(SHARE_WINDOW).sum().replace(0.0, np.nan)
        )
        # Use only information known before day t to allocate the total GARCH forecast.
        overnight_share_lag1 = share_raw.shift(1).clip(lower=0.0, upper=1.0)
        df["garch_total_var"] = garch_total
        df["expected_overnight_var"] = df["garch_total_var"] * overnight_share_lag1
        df["expected_intraday_var"] = df["garch_total_var"] * (1.0 - overnight_share_lag1)
        df["overnight_pseudo_vrp"] = df["expected_overnight_var"] - df["overnight_var"]
        df["intraday_pseudo_vrp"] = df["expected_intraday_var"] - df["intraday_var"]

        # Predictive information set: yesterday's realized premium and controls.
        df["overnight_pseudo_vrp_lag1"] = df["overnight_pseudo_vrp"].shift(1)
        df["intraday_pseudo_vrp_lag1"] = df["intraday_pseudo_vrp"].shift(1)
        df["log_session_var"] = np.log(df["session_var"] + EPS)
        df["log_session_var_lag1"] = df["log_session_var"].shift(1)
        df["log_garch_total_var_lag1"] = np.log(df["garch_total_var"].shift(1) + EPS)
        components[ticker] = df
    return components


def moving_block_indices(n: int, rng: np.random.Generator) -> np.ndarray:
    chosen: list[int] = []
    while len(chosen) < n:
        start = int(rng.integers(0, max(1, n - BOOTSTRAP_BLOCK + 1)))
        chosen.extend(range(start, min(start + BOOTSTRAP_BLOCK, n)))
    return np.asarray(chosen[:n], dtype=int)


def bootstrap_share_and_premium(df: pd.DataFrame) -> dict:
    sample = df[df.index >= OOS_START][
        ["overnight_var", "intraday_var", "session_var", "overnight_pseudo_vrp", "intraday_pseudo_vrp"]
    ].dropna()
    arr = sample.to_numpy(dtype=float)
    rng = np.random.default_rng(SEED)
    rows = []
    for _ in range(BOOTSTRAP_REPS):
        b = arr[moving_block_indices(len(arr), rng)]
        overnight_sum = b[:, 0].sum()
        intraday_sum = b[:, 1].sum()
        session_sum = b[:, 2].sum()
        overnight_premium_mean = b[:, 3].mean()
        intraday_premium_mean = b[:, 4].mean()
        rows.append(
            {
                "overnight_share": overnight_sum / session_sum if session_sum > 0 else np.nan,
                "intraday_share": intraday_sum / session_sum if session_sum > 0 else np.nan,
                "premium_diff_overnight_minus_intraday": overnight_premium_mean - intraday_premium_mean,
            }
        )
    boot = pd.DataFrame(rows)
    out = {}
    for col in boot.columns:
        values = boot[col].dropna().to_numpy()
        out[col] = {
            "mean": round(float(values.mean()), 6),
            "ci_2p5": round(float(np.quantile(values, 0.025)), 6),
            "ci_97p5": round(float(np.quantile(values, 0.975)), 6),
            "p_gt_0": round(float((values > 0).mean()), 4),
            "p_gt_half": round(float((values > 0.5).mean()), 4) if "share" in col else None,
        }
    return out


def standardize(s: pd.Series) -> pd.Series:
    sd = s.std(ddof=1)
    if not np.isfinite(sd) or sd <= 0:
        return s * np.nan
    return (s - s.mean()) / sd


def predictive_regression(df: pd.DataFrame) -> RegressionResult:
    oos = df[df.index >= OOS_START].copy()
    reg = pd.DataFrame(
        {
            "target": oos["log_session_var"],
            "overnight": standardize(oos["overnight_pseudo_vrp_lag1"]),
            "intraday": standardize(oos["intraday_pseudo_vrp_lag1"]),
            "log_session_lag1": oos["log_session_var_lag1"],
            "log_garch_lag1": oos["log_garch_total_var_lag1"],
        }
    ).replace([np.inf, -np.inf], np.nan).dropna()
    x = sm.add_constant(reg[["overnight", "intraday", "log_session_lag1", "log_garch_lag1"]])
    fit = sm.OLS(reg["target"], x).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    return RegressionResult(
        nobs=int(fit.nobs),
        coef_overnight=round(float(fit.params["overnight"]), 6),
        t_overnight=round(float(fit.tvalues["overnight"]), 4),
        p_overnight=round(float(fit.pvalues["overnight"]), 6),
        coef_intraday=round(float(fit.params["intraday"]), 6),
        t_intraday=round(float(fit.tvalues["intraday"]), 4),
        p_intraday=round(float(fit.pvalues["intraday"]), 6),
        r2=round(float(fit.rsquared), 6),
    )


def summarize_asset(ticker: str, df: pd.DataFrame) -> dict:
    oos = df[df.index >= OOS_START].dropna(
        subset=["overnight_var", "intraday_var", "session_var", "garch_total_var", "overnight_pseudo_vrp"]
    )
    overnight_sum = float(oos["overnight_var"].sum())
    intraday_sum = float(oos["intraday_var"].sum())
    session_sum = float(oos["session_var"].sum())
    total_sum = float(oos["close_to_close_var"].sum())
    covariance_sum = float(oos["covariance_residual_var"].sum())
    expected_sum = float(oos["garch_total_var"].sum())
    overnight_premium = float(oos["overnight_pseudo_vrp"].mean())
    intraday_premium = float(oos["intraday_pseudo_vrp"].mean())
    reg = predictive_regression(df)
    boot = bootstrap_share_and_premium(df)

    return {
        "ticker": ticker,
        "n_oos": int(len(oos)),
        "oos_start": str(oos.index[0].date()),
        "oos_end": str(oos.index[-1].date()),
        "realized_session_variance": {
            "overnight_share": round(overnight_sum / session_sum, 6),
            "intraday_share": round(intraday_sum / session_sum, 6),
            "covariance_residual_share_of_close_to_close_var": round(covariance_sum / total_sum, 6),
            "mean_daily_overnight_var_pct2": round(float(oos["overnight_var"].mean() * 10000.0), 6),
            "mean_daily_intraday_var_pct2": round(float(oos["intraday_var"].mean() * 10000.0), 6),
            "mean_daily_close_to_close_var_pct2": round(float(oos["close_to_close_var"].mean() * 10000.0), 6),
        },
        "garch_proxy": {
            "mean_expected_total_var_pct2": round(float(oos["garch_total_var"].mean() * 10000.0), 6),
            "mean_realized_session_var_pct2": round(float(oos["session_var"].mean() * 10000.0), 6),
            "expected_minus_realized_total_var_pct2": round((expected_sum - session_sum) / len(oos) * 10000.0, 6),
            "mean_overnight_pseudo_vrp_pct2": round(overnight_premium * 10000.0, 6),
            "mean_intraday_pseudo_vrp_pct2": round(intraday_premium * 10000.0, 6),
            "mean_premium_diff_overnight_minus_intraday_pct2": round(
                (overnight_premium - intraday_premium) * 10000.0, 6
            ),
        },
        "bootstrap_oos": boot,
        "predictive_regression_oos": reg.__dict__,
    }


def build_figures(summaries: dict[str, dict]) -> None:
    labels = list(summaries)
    overnight = [summaries[t]["realized_session_variance"]["overnight_share"] for t in labels]
    intraday = [summaries[t]["realized_session_variance"]["intraday_share"] for t in labels]

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(9, 5.5))
    x = np.arange(len(labels))
    ax.bar(x, overnight, label="Overnight", color="#4c78a8")
    ax.bar(x, intraday, bottom=overnight, label="Intraday", color="#f58518")
    ax.axhline(0.5, color="#444444", linewidth=1, linestyle="--")
    ax.set_xticks(x, labels)
    ax.set_ylim(0, 1.0)
    ax.set_ylabel("Share of OOS session variance")
    ax.set_title("Overnight vs Intraday Realized Variance Shares")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIG_SHARE, dpi=180)
    plt.close(fig)

    t_overnight = [summaries[t]["predictive_regression_oos"]["t_overnight"] for t in labels]
    t_intraday = [summaries[t]["predictive_regression_oos"]["t_intraday"] for t in labels]
    fig2, ax2 = plt.subplots(figsize=(9, 5.5))
    width = 0.36
    ax2.bar(x - width / 2, t_overnight, width=width, label="Lagged overnight pseudo-VRP", color="#4c78a8")
    ax2.bar(x + width / 2, t_intraday, width=width, label="Lagged intraday pseudo-VRP", color="#f58518")
    ax2.axhline(3.0, color="#444444", linewidth=1, linestyle="--")
    ax2.axhline(-3.0, color="#444444", linewidth=1, linestyle="--")
    ax2.set_xticks(x, labels)
    ax2.set_ylabel("HAC t-stat")
    ax2.set_title("Next-Day Session Variance Predictive Regressions")
    ax2.legend(frameon=False)
    fig2.tight_layout()
    fig2.savefig(FIG_PREDICT, dpi=180)
    plt.close(fig2)


def main() -> None:
    np.random.seed(SEED)
    ohlc = download_ohlc()
    components = build_components(ohlc)
    summaries = {ticker: summarize_asset(ticker, df) for ticker, df in components.items()}
    build_figures(summaries)

    overnight_majority_assets = [
        ticker
        for ticker, s in summaries.items()
        if s["bootstrap_oos"]["overnight_share"]["ci_2p5"] > 0.5
    ]
    predictive_assets = [
        ticker
        for ticker, s in summaries.items()
        if s["predictive_regression_oos"]["t_overnight"] > 3.0
    ]

    verdict = "NULL"
    if len(overnight_majority_assets) >= 3 and len(predictive_assets) >= 3:
        verdict = "PSEUDO_VRP_SUPPORT"
    elif len(overnight_majority_assets) >= 3 or len(predictive_assets) >= 3:
        verdict = "PARTIAL"

    results = {
        "experiment_id": "research_intraday_vs_overnight_vrp",
        "title": "Intraday vs overnight pseudo-VRP decomposition across SPY/QQQ/IWM/EFA",
        "date_run_utc": pd.Timestamp.now("UTC").strftime("%Y-%m-%d"),
        "seed": SEED,
        "data": {
            "source": "yfinance adjusted OHLC; auto_adjust=True",
            "tickers": TICKERS,
            "download_start": START,
            "download_end": END,
            "analysis_start": str(ANALYSIS_START.date()),
            "oos_start": str(OOS_START.date()),
            "cached_ohlc_dir": "experiments/research_intraday_vs_overnight_vrp/data/",
        },
        "method": {
            "returns": {
                "overnight": "log(Open_t / Close_{t-1})",
                "intraday": "log(Close_t / Open_t)",
                "close_to_close": "log(Close_t / Close_{t-1})",
            },
            "pseudo_vrp_definition": (
                "GARCH one-step expected component variance minus realized component variance; "
                "not an option-implied model-free VRP."
            ),
            "garch_proxy": {
                "model": "Zero-mean GARCH(1,1) on close-to-close log returns in percent units",
                "window": GARCH_WINDOW,
                "refit_every": GARCH_REFIT_EVERY,
                "forecast_timing": "forecast for day t uses returns through t-1",
            },
            "component_allocation": (
                "total GARCH variance is allocated by trailing 252d overnight share shifted by one day"
            ),
            "predictive_regression": {
                "target": "current-day log(session variance)",
                "features": [
                    "overnight_pseudo_vrp.shift(1)",
                    "intraday_pseudo_vrp.shift(1)",
                    "log_session_var.shift(1)",
                    "log_garch_total_var.shift(1)",
                ],
                "standard_errors": f"Newey-West HAC maxlags={HAC_LAGS}",
                "success_rule": (
                    "overall support requires overnight variance-share CI lower > 0.5 and "
                    "lagged overnight pseudo-VRP HAC t > 3 in at least 3 of 4 assets"
                ),
            },
            "bootstrap": {"reps": BOOTSTRAP_REPS, "block_length": BOOTSTRAP_BLOCK, "seed": SEED},
            "lookahead_protection": [
                "GARCH forecast for day t uses close-to-close returns through t-1",
                "component allocation share is shifted by one day",
                "predictive features use explicit .shift(1)",
            ],
        },
        "asset_results": summaries,
        "figures": [FIG_SHARE.name, FIG_PREDICT.name],
        "literature": [
            {
                "citation": "Papagelis and Dotsis (2025), The Variance Risk Premium Over Trading and Nontrading Periods",
                "url": "https://onlinelibrary.wiley.com/doi/full/10.1002/fut.22589",
            },
            {
                "citation": "Carr and Wu (2009), Variance Risk Premia",
                "url": "https://doi.org/10.1093/rfs/hhn038",
            },
            {
                "citation": "Bollerslev, Tauchen, and Zhou (2009), Expected Stock Returns and Variance Risk Premia",
                "url": "https://www.federalreserve.gov/pubs/feds/2007/200711/",
            },
            {
                "citation": "Corsi (2009), A Simple Approximate Long-Memory Model of Realized Volatility",
                "url": "https://doi.org/10.1093/jjfinec/nbp001",
            },
        ],
        "research_honesty_notes": [
            "Daily yfinance OHLC cannot identify true option-implied VRP; this is a pseudo-VRP proxy only.",
            "No same-day realized pseudo-VRP is used as a predictor; predictive regressions use lagged features.",
            "Because GARCH is a physical-measure forecast, mean pseudo-premia should not be interpreted as investable option carry.",
        ],
        "verdict": {
            "overall": verdict,
            "overnight_majority_assets": overnight_majority_assets,
            "predictive_assets": predictive_assets,
            "plain_english": (
                "Overnight pseudo-VRP dominates and predicts next-day variance in most assets."
                if verdict == "PSEUDO_VRP_SUPPORT"
                else "Evidence is mixed: one leg of the overnight dominance/predictability gate passes, but not both."
                if verdict == "PARTIAL"
                else "The yfinance-only pseudo-VRP proxy does not support a broad cross-asset overnight-dominance plus next-day-RV prediction claim."
            ),
        },
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(results["verdict"], indent=2, ensure_ascii=False))
    print(json.dumps({k: v["realized_session_variance"] for k, v in summaries.items()}, indent=2))


if __name__ == "__main__":
    main()
