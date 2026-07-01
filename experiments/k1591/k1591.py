#!/usr/bin/env python3
"""
K1591: Ex-ante macro regime design for GLD leverage-direction claims.

This experiment rebuilds the gold regime test requested by the
leverage-direction Stage 2 plan. Regimes are defined only from external
lagged instruments:

  - VIX stress threshold
  - DXY 63-trading-day trend
  - Treasury basis/curve movement: 10Y minus 13-week Treasury yield

The main test is a reduced-form GJR-style news-impact regression for daily
GLD volatility response. A rolling GJR-GARCH gamma diagnostic is reported as a
secondary check.

All regime inputs are shifted by one trading day before use.
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from arch import arch_model
from scipy.stats import norm

warnings.filterwarnings("ignore")

EXPERIMENT_ID = "k1591"
SEED = 1591
N_BOOTSTRAP = 1000
BLOCK_LEN = 10
VIX_STRESS_THRESHOLD = 20.0
DXY_TREND_DAYS = 63
TREASURY_BASIS_DAYS = 63
TRAIN_END = pd.Timestamp("2018-12-31")
HOLDOUT_START = pd.Timestamp("2019-01-01")
ROLLING_GJR_WINDOW = 504
ROLLING_GJR_STEP = 63
MIN_GROUP_OBS = 60
MIN_SIGN_OBS = 12

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
PAPER_DATA = PROJECT_ROOT / "paper/leverage-direction/data/spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv"
RESULTS_PATH = SCRIPT_DIR / "k1591_results.json"
DAILY_PANEL_PATH = SCRIPT_DIR / "tables/k1591_daily_panel.csv"
SUMMARY_TABLE_PATH = SCRIPT_DIR / "tables/k1591_regime_summary.csv"
ROLLING_TABLE_PATH = SCRIPT_DIR / "tables/k1591_rolling_gjr_gamma.csv"
FIG_PATH = SCRIPT_DIR / "figures/k1591_holdout_regime_asymmetry.png"
MACRO_CACHE_PATH = SCRIPT_DIR / "data/external_macro_yfinance_2010_2026.csv"

np.random.seed(SEED)


@dataclass
class RegressionResult:
    n_obs: int
    n_pos: int
    n_neg: int
    beta_pos: float | None
    beta_neg: float | None
    gamma_diff: float | None
    gamma_diff_se: float | None
    gamma_diff_t: float | None
    gamma_diff_p: float | None
    r2_adj: float | None
    status: str


def as_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def json_ready(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): json_ready(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [json_ready(v) for v in obj]
    if isinstance(obj, tuple):
        return [json_ready(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return as_float_or_none(obj)
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if pd.isna(obj):
        return None
    return obj


def close_series(raw: pd.DataFrame, ticker: str) -> pd.Series:
    if isinstance(raw.columns, pd.MultiIndex):
        if ("Close", ticker) in raw.columns:
            series = raw[("Close", ticker)]
        else:
            series = raw.xs("Close", axis=1, level=0).iloc[:, 0]
    else:
        series = raw["Close"]
    series = series.rename(ticker)
    series.index = pd.to_datetime(series.index).tz_localize(None)
    return series.astype(float)


def download_or_load_macro(start: str, end: str) -> tuple[pd.DataFrame, str]:
    if MACRO_CACHE_PATH.exists():
        macro = pd.read_csv(MACRO_CACHE_PATH, parse_dates=["date"]).set_index("date")
        return macro, f"cache:{MACRO_CACHE_PATH.relative_to(PROJECT_ROOT)}"

    tickers = {
        "dxy": "DX-Y.NYB",
        "tnx": "^TNX",
        "irx": "^IRX",
    }
    series = {}
    for name, ticker in tickers.items():
        raw = yf.download(
            ticker,
            start=start,
            end=end,
            auto_adjust=True,
            progress=False,
            threads=False,
        )
        if raw.empty:
            raise RuntimeError(f"yfinance returned no data for {ticker}")
        series[name] = close_series(raw, ticker)

    macro = pd.concat(series.values(), axis=1)
    macro.columns = list(series.keys())
    macro = macro.sort_index()
    macro.to_csv(MACRO_CACHE_PATH, index_label="date")
    return macro, "yfinance:DX-Y.NYB,^TNX,^IRX"


def load_base_panel() -> tuple[pd.DataFrame, dict[str, Any]]:
    if not PAPER_DATA.exists():
        raise FileNotFoundError(PAPER_DATA)

    raw = pd.read_csv(PAPER_DATA, parse_dates=["date"]).set_index("date").sort_index()
    start = raw.index.min().strftime("%Y-%m-%d")
    end = (raw.index.max() + pd.Timedelta(days=3)).strftime("%Y-%m-%d")
    macro, macro_source = download_or_load_macro(start, end)

    df = pd.DataFrame(
        {
            "gld": raw["gld_adj_close"],
            "vix": raw["vix_adj_close"],
        },
        index=raw.index,
    )
    df = df.join(macro, how="left")
    df[["dxy", "tnx", "irx"]] = df[["dxy", "tnx", "irx"]].ffill()
    df = df.dropna(subset=["gld", "vix", "dxy", "tnx", "irx"])

    df["gld_ret_pct"] = 100.0 * np.log(df["gld"] / df["gld"].shift(1))
    df["gld_r2"] = df["gld_ret_pct"] ** 2
    df["lag_ret_pct"] = df["gld_ret_pct"].shift(1)
    df["lag_r2"] = df["lag_ret_pct"] ** 2
    df["pos_lag_r2"] = np.where(df["lag_ret_pct"] >= 0.0, df["lag_r2"], 0.0)
    df["neg_lag_r2"] = np.where(df["lag_ret_pct"] < 0.0, df["lag_r2"], 0.0)
    df["rv5_lag"] = df["gld_r2"].rolling(5).mean().shift(1)
    df["rv22_lag"] = df["gld_r2"].rolling(22).mean().shift(1)

    # External regime instruments. Each is shifted one day before classification.
    df["vix_lag"] = df["vix"].shift(1)
    df["dxy_trend_63d_lag"] = (100.0 * np.log(df["dxy"] / df["dxy"].shift(DXY_TREND_DAYS))).shift(1)
    df["treasury_basis"] = df["tnx"] - df["irx"]
    df["treasury_basis_change_63d_lag"] = (
        df["treasury_basis"] - df["treasury_basis"].shift(TREASURY_BASIS_DAYS)
    ).shift(1)
    df["vix_stress_lag"] = df["vix_lag"] >= VIX_STRESS_THRESHOLD
    df["dxy_uptrend_lag"] = df["dxy_trend_63d_lag"] > 0.0
    df["basis_steepening_lag"] = df["treasury_basis_change_63d_lag"] > 0.0

    conditions = [
        df["vix_stress_lag"] & (~df["dxy_uptrend_lag"]) & (~df["basis_steepening_lag"]),
        df["vix_stress_lag"] & df["dxy_uptrend_lag"] & df["basis_steepening_lag"],
    ]
    choices = ["safe_haven_stress", "liquidation_stress"]
    df["regime"] = np.select(conditions, choices, default="neutral")
    df["period"] = np.where(df.index <= TRAIN_END, "train_2010_2018", "holdout_2019_2026")

    df = df.dropna(
        subset=[
            "gld_ret_pct",
            "gld_r2",
            "lag_ret_pct",
            "lag_r2",
            "pos_lag_r2",
            "neg_lag_r2",
            "rv5_lag",
            "rv22_lag",
            "vix_lag",
            "dxy_trend_63d_lag",
            "treasury_basis_change_63d_lag",
        ]
    )

    metadata = {
        "paper_data": str(PAPER_DATA.relative_to(PROJECT_ROOT)),
        "macro_source": macro_source,
        "sample_start": df.index.min().strftime("%Y-%m-%d"),
        "sample_end": df.index.max().strftime("%Y-%m-%d"),
        "n_obs": int(len(df)),
        "regime_rule": {
            "vix_stress": f"lagged VIX >= {VIX_STRESS_THRESHOLD}",
            "dxy_trend": f"lagged {DXY_TREND_DAYS}-trading-day log DXY return > 0",
            "treasury_basis": "10Y minus 13-week yield, lagged 63-trading-day change > 0",
            "safe_haven_stress": "VIX stress, DXY not up, Treasury basis not steepening",
            "liquidation_stress": "VIX stress, DXY up, Treasury basis steepening",
            "neutral": "all other days",
            "lookahead_guard": "all regime variables are shifted by one trading day",
        },
    }
    return df, metadata


def fit_news_impact_regression(group: pd.DataFrame) -> RegressionResult:
    group = group.dropna(subset=["gld_r2", "pos_lag_r2", "neg_lag_r2", "rv5_lag", "rv22_lag"])
    n_obs = int(len(group))
    n_pos = int((group["lag_ret_pct"] >= 0.0).sum())
    n_neg = int((group["lag_ret_pct"] < 0.0).sum())
    if n_obs < MIN_GROUP_OBS or n_pos < MIN_SIGN_OBS or n_neg < MIN_SIGN_OBS:
        return RegressionResult(
            n_obs=n_obs,
            n_pos=n_pos,
            n_neg=n_neg,
            beta_pos=None,
            beta_neg=None,
            gamma_diff=None,
            gamma_diff_se=None,
            gamma_diff_t=None,
            gamma_diff_p=None,
            r2_adj=None,
            status="insufficient_observations",
        )

    y = group["gld_r2"].astype(float)
    x = group[["pos_lag_r2", "neg_lag_r2", "rv5_lag", "rv22_lag"]].astype(float)
    x = sm.add_constant(x)
    try:
        model = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
        beta_pos = float(model.params["pos_lag_r2"])
        beta_neg = float(model.params["neg_lag_r2"])
        cov = model.cov_params()
        diff = beta_neg - beta_pos
        var_diff = (
            cov.loc["neg_lag_r2", "neg_lag_r2"]
            + cov.loc["pos_lag_r2", "pos_lag_r2"]
            - 2.0 * cov.loc["neg_lag_r2", "pos_lag_r2"]
        )
        se = float(math.sqrt(max(var_diff, 1e-12)))
        t_stat = float(diff / se)
        p_val = float(2.0 * (1.0 - norm.cdf(abs(t_stat))))
        return RegressionResult(
            n_obs=n_obs,
            n_pos=n_pos,
            n_neg=n_neg,
            beta_pos=beta_pos,
            beta_neg=beta_neg,
            gamma_diff=float(diff),
            gamma_diff_se=se,
            gamma_diff_t=t_stat,
            gamma_diff_p=p_val,
            r2_adj=float(model.rsquared_adj),
            status="ok",
        )
    except Exception as exc:
        return RegressionResult(
            n_obs=n_obs,
            n_pos=n_pos,
            n_neg=n_neg,
            beta_pos=None,
            beta_neg=None,
            gamma_diff=None,
            gamma_diff_se=None,
            gamma_diff_t=None,
            gamma_diff_p=None,
            r2_adj=None,
            status=f"fit_failed:{type(exc).__name__}",
        )


def summarize_regressions(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    periods = ["train_2010_2018", "holdout_2019_2026", "full_2010_2026"]
    regimes = ["safe_haven_stress", "liquidation_stress", "neutral", "all"]
    out: dict[str, dict[str, Any]] = {}
    for period in periods:
        if period == "full_2010_2026":
            period_df = df
        else:
            period_df = df[df["period"] == period]
        out[period] = {}
        for regime in regimes:
            if regime == "all":
                group = period_df
            else:
                group = period_df[period_df["regime"] == regime]
            out[period][regime] = fit_news_impact_regression(group).__dict__
    return out


def contiguous_block_sample(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    n = len(df)
    if n <= BLOCK_LEN:
        return df.sample(n=n, replace=True, random_state=int(rng.integers(0, 2**31 - 1)))
    starts = rng.integers(0, n - BLOCK_LEN + 1, size=math.ceil(n / BLOCK_LEN))
    blocks = [df.iloc[start : start + BLOCK_LEN] for start in starts]
    sample = pd.concat(blocks, axis=0).iloc[:n].copy()
    sample.index = pd.RangeIndex(len(sample))
    return sample


def bootstrap_holdout_difference(df: pd.DataFrame) -> dict[str, Any]:
    holdout = df[df["period"] == "holdout_2019_2026"].copy()
    if len(holdout) < MIN_GROUP_OBS:
        return {"status": "insufficient_holdout"}

    rng = np.random.default_rng(SEED)
    records = []
    for _ in range(N_BOOTSTRAP):
        sample = contiguous_block_sample(holdout, rng)
        safe = fit_news_impact_regression(sample[sample["regime"] == "safe_haven_stress"])
        liq = fit_news_impact_regression(sample[sample["regime"] == "liquidation_stress"])
        if safe.status == "ok" and liq.status == "ok":
            records.append(
                {
                    "safe_haven_gamma_diff": safe.gamma_diff,
                    "liquidation_gamma_diff": liq.gamma_diff,
                    "safe_minus_liquidation": safe.gamma_diff - liq.gamma_diff,
                }
            )

    boot = pd.DataFrame(records)
    if boot.empty:
        return {"status": "no_valid_bootstrap_draws", "valid_draws": 0}

    summary = {"status": "ok", "valid_draws": int(len(boot)), "requested_draws": N_BOOTSTRAP}
    for col in boot.columns:
        values = boot[col].dropna().astype(float)
        summary[col] = {
            "mean": float(values.mean()),
            "median": float(values.median()),
            "ci_2p5": float(values.quantile(0.025)),
            "ci_97p5": float(values.quantile(0.975)),
            "pct_negative": float((values < 0.0).mean() * 100.0),
            "pct_positive": float((values > 0.0).mean() * 100.0),
        }
    return summary


def rolling_gjr_gamma(df: pd.DataFrame) -> pd.DataFrame:
    returns = df["gld_ret_pct"].dropna()
    rows = []
    for end_idx in range(ROLLING_GJR_WINDOW, len(returns), ROLLING_GJR_STEP):
        window = returns.iloc[end_idx - ROLLING_GJR_WINDOW : end_idx]
        end_date = returns.index[end_idx - 1]
        try:
            model = arch_model(
                window,
                mean="Zero",
                vol="Garch",
                p=1,
                o=1,
                q=1,
                dist="t",
                rescale=False,
            )
            res = model.fit(disp="off", options={"maxiter": 500})
            gamma = float(res.params.get("gamma[1]", np.nan))
            t_stat = float(res.tvalues.get("gamma[1]", np.nan))
            alpha = float(res.params.get("alpha[1]", np.nan))
            beta = float(res.params.get("beta[1]", np.nan))
            status = "ok"
        except Exception as exc:
            gamma = np.nan
            t_stat = np.nan
            alpha = np.nan
            beta = np.nan
            status = f"fit_failed:{type(exc).__name__}"

        if end_date in df.index:
            regime = str(df.loc[end_date, "regime"])
            period = str(df.loc[end_date, "period"])
        else:
            regime = "missing"
            period = "missing"

        rows.append(
            {
                "end_date": end_date,
                "period": period,
                "regime": regime,
                "gamma": gamma,
                "gamma_t": t_stat,
                "alpha": alpha,
                "beta": beta,
                "status": status,
                "n_obs": int(len(window)),
            }
        )
    return pd.DataFrame(rows)


def newey_west_mean_t(values: pd.Series, lags: int = 4) -> tuple[float | None, float | None]:
    x = values.dropna().astype(float).to_numpy()
    n = len(x)
    if n < 5:
        return None, None
    mean_x = x.mean()
    residual = x - mean_x
    gamma0 = float(np.mean(residual**2))
    variance = gamma0
    for lag in range(1, min(lags, n - 1) + 1):
        weight = 1.0 - lag / (lags + 1.0)
        gamma_lag = float(np.mean(residual[lag:] * residual[:-lag]))
        variance += 2.0 * weight * gamma_lag
    variance = max(variance / n, 1e-12)
    t_stat = mean_x / math.sqrt(variance)
    p_val = 2.0 * (1.0 - norm.cdf(abs(t_stat)))
    return float(t_stat), float(p_val)


def summarize_rolling_gjr(rolling: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for period in ["train_2010_2018", "holdout_2019_2026", "full_2010_2026"]:
        period_df = rolling if period == "full_2010_2026" else rolling[rolling["period"] == period]
        out[period] = {}
        for regime in ["safe_haven_stress", "liquidation_stress", "neutral", "all"]:
            group = period_df if regime == "all" else period_df[period_df["regime"] == regime]
            group = group[group["status"] == "ok"]
            gamma = group["gamma"].dropna().astype(float)
            t_stat, p_val = newey_west_mean_t(gamma)
            out[period][regime] = {
                "n_windows": int(len(gamma)),
                "mean_gamma": as_float_or_none(gamma.mean()) if len(gamma) else None,
                "median_gamma": as_float_or_none(gamma.median()) if len(gamma) else None,
                "pct_negative": as_float_or_none((gamma < 0.0).mean() * 100.0) if len(gamma) else None,
                "hac_t_mean_zero": t_stat,
                "hac_p_mean_zero": p_val,
            }
    return out


def make_summary_table(regression_summary: dict[str, dict[str, Any]], rolling_summary: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for period, regimes in regression_summary.items():
        for regime, stats in regimes.items():
            roll = rolling_summary.get(period, {}).get(regime, {})
            rows.append(
                {
                    "period": period,
                    "regime": regime,
                    "n_obs": stats.get("n_obs"),
                    "n_pos": stats.get("n_pos"),
                    "n_neg": stats.get("n_neg"),
                    "beta_pos": stats.get("beta_pos"),
                    "beta_neg": stats.get("beta_neg"),
                    "gamma_diff_neg_minus_pos": stats.get("gamma_diff"),
                    "gamma_diff_hac_t": stats.get("gamma_diff_t"),
                    "gamma_diff_p": stats.get("gamma_diff_p"),
                    "news_impact_status": stats.get("status"),
                    "rolling_gjr_n_windows": roll.get("n_windows"),
                    "rolling_gjr_mean_gamma": roll.get("mean_gamma"),
                    "rolling_gjr_pct_negative": roll.get("pct_negative"),
                    "rolling_gjr_hac_t": roll.get("hac_t_mean_zero"),
                }
            )
    return pd.DataFrame(rows)


def make_figure(summary: pd.DataFrame, bootstrap: dict[str, Any]) -> None:
    holdout = summary[
        (summary["period"] == "holdout_2019_2026")
        & (summary["regime"].isin(["safe_haven_stress", "liquidation_stress", "neutral"]))
    ].copy()
    labels = {
        "safe_haven_stress": "Safe-haven\nstress",
        "liquidation_stress": "Liquidation\nstress",
        "neutral": "Neutral",
    }
    colors = {
        "safe_haven_stress": "#3b7d8f",
        "liquidation_stress": "#b55d4c",
        "neutral": "#6d7378",
    }
    x = np.arange(len(holdout))
    y = holdout["gamma_diff_neg_minus_pos"].astype(float).to_numpy()
    se = (
        holdout["gamma_diff_neg_minus_pos"].astype(float)
        / holdout["gamma_diff_hac_t"].replace(0, np.nan).astype(float)
    ).abs()
    yerr = (1.96 * se).replace([np.inf, -np.inf], np.nan).fillna(0.0).to_numpy()

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    axes[0].bar(
        x,
        y,
        yerr=yerr,
        capsize=4,
        color=[colors[r] for r in holdout["regime"]],
        edgecolor="#222222",
        linewidth=0.7,
    )
    axes[0].axhline(0.0, color="#222222", linewidth=0.9)
    axes[0].set_xticks(x)
    axes[0].set_xticklabels([labels[r] for r in holdout["regime"]])
    axes[0].set_ylabel("Negative-shock minus positive-shock response")
    axes[0].set_title("Holdout reduced-form asymmetry")
    axes[0].grid(axis="y", alpha=0.25)

    diff_summary = bootstrap.get("safe_minus_liquidation", {})
    if bootstrap.get("status") == "ok" and diff_summary:
        ci_low = diff_summary["ci_2p5"]
        ci_high = diff_summary["ci_97p5"]
        median = diff_summary["median"]
        axes[1].errorbar([0], [median], yerr=[[median - ci_low], [ci_high - median]], fmt="o", color="#222222")
        axes[1].axhline(0.0, color="#222222", linewidth=0.9)
        axes[1].set_xlim(-0.8, 0.8)
        axes[1].set_xticks([0])
        axes[1].set_xticklabels(["Safe minus\nliquidation"])
        axes[1].set_ylabel("Bootstrap difference")
        axes[1].set_title(f"Block bootstrap ({bootstrap['valid_draws']} valid draws)")
        axes[1].grid(axis="y", alpha=0.25)
    else:
        axes[1].text(0.5, 0.5, "Bootstrap unavailable", ha="center", va="center", transform=axes[1].transAxes)
        axes[1].set_axis_off()

    fig.suptitle("K1591: Ex-ante macro regimes for GLD leverage-direction")
    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=160, bbox_inches="tight")
    plt.close(fig)


def infer_conclusion(regression_summary: dict[str, dict[str, Any]], bootstrap: dict[str, Any]) -> dict[str, Any]:
    holdout = regression_summary["holdout_2019_2026"]
    safe = holdout["safe_haven_stress"]
    liq = holdout["liquidation_stress"]
    status = "hold"
    rationale = []

    if safe["status"] != "ok" or liq["status"] != "ok":
        status = "insufficient_regime_power"
        rationale.append("At least one stress regime lacks enough holdout observations for the primary regression.")
    else:
        safe_gamma = safe["gamma_diff"]
        liq_gamma = liq["gamma_diff"]
        safe_t = safe["gamma_diff_t"]
        liq_t = liq["gamma_diff_t"]
        rationale.append(
            "Holdout safe-haven gamma_diff (negative minus positive) "
            f"={safe_gamma:.4f}, HAC t={safe_t:.2f}."
        )
        rationale.append(
            "Holdout liquidation gamma_diff "
            f"={liq_gamma:.4f}, HAC t={liq_t:.2f}."
        )
        if safe_gamma < 0.0 and liq_gamma > 0.0:
            status = "directionally_supportive"
        elif safe_gamma < 0.0:
            status = "partial_safe_haven_only"
        elif liq_gamma > 0.0:
            status = "partial_liquidation_only"
        else:
            status = "not_supportive"

    if bootstrap.get("status") == "ok":
        diff = bootstrap["safe_minus_liquidation"]
        rationale.append(
            "Bootstrap safe-minus-liquidation median "
            f"={diff['median']:.4f}, 95% CI [{diff['ci_2p5']:.4f}, {diff['ci_97p5']:.4f}]."
        )
        if diff["ci_2p5"] <= 0.0 <= diff["ci_97p5"]:
            rationale.append("The regime contrast is not cleanly separated at the 95% bootstrap interval.")
        else:
            rationale.append("The regime contrast excludes zero at the 95% bootstrap interval.")
    else:
        rationale.append(f"Bootstrap status: {bootstrap.get('status')}")

    return {
        "status": status,
        "paper_claim_allowed": (
            "Only a regime-dependent, externally defined gold claim is allowed; "
            "do not restore an unconditional inverted-leverage claim from this experiment."
        ),
        "rationale": rationale,
    }


def main() -> None:
    print(f"{EXPERIMENT_ID}: loading panel")
    df, metadata = load_base_panel()
    DAILY_PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_TABLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ROLLING_TABLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    print(f"{EXPERIMENT_ID}: fitting news-impact regressions")
    regression_summary = summarize_regressions(df)

    print(f"{EXPERIMENT_ID}: block bootstrap")
    bootstrap = bootstrap_holdout_difference(df)

    print(f"{EXPERIMENT_ID}: rolling GJR diagnostic")
    rolling = rolling_gjr_gamma(df)
    rolling_summary = summarize_rolling_gjr(rolling)

    summary_table = make_summary_table(regression_summary, rolling_summary)
    daily_cols = [
        "gld",
        "vix",
        "dxy",
        "tnx",
        "irx",
        "treasury_basis",
        "gld_ret_pct",
        "lag_ret_pct",
        "gld_r2",
        "pos_lag_r2",
        "neg_lag_r2",
        "rv5_lag",
        "rv22_lag",
        "vix_lag",
        "dxy_trend_63d_lag",
        "treasury_basis_change_63d_lag",
        "regime",
        "period",
    ]
    df[daily_cols].to_csv(DAILY_PANEL_PATH, index_label="date")
    summary_table.to_csv(SUMMARY_TABLE_PATH, index=False)
    rolling.to_csv(ROLLING_TABLE_PATH, index=False)
    make_figure(summary_table, bootstrap)

    regime_counts = (
        df.groupby(["period", "regime"]).size().unstack(fill_value=0).astype(int).to_dict(orient="index")
    )
    conclusion = infer_conclusion(regression_summary, bootstrap)

    results = {
        "experiment_id": EXPERIMENT_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "purpose": "Stage 2 ex-ante gold regime design for leverage-direction manuscript",
        "data": metadata,
        "parameters": {
            "train_end": TRAIN_END.strftime("%Y-%m-%d"),
            "holdout_start": HOLDOUT_START.strftime("%Y-%m-%d"),
            "vix_stress_threshold": VIX_STRESS_THRESHOLD,
            "dxy_trend_days": DXY_TREND_DAYS,
            "treasury_basis_days": TREASURY_BASIS_DAYS,
            "bootstrap_reps": N_BOOTSTRAP,
            "bootstrap_block_len": BLOCK_LEN,
            "rolling_gjr_window": ROLLING_GJR_WINDOW,
            "rolling_gjr_step": ROLLING_GJR_STEP,
        },
        "regime_counts": regime_counts,
        "primary_news_impact_regressions": regression_summary,
        "bootstrap_holdout_difference": bootstrap,
        "rolling_gjr_gamma_diagnostic": rolling_summary,
        "conclusion": conclusion,
        "outputs": {
            "daily_panel": str(DAILY_PANEL_PATH.relative_to(PROJECT_ROOT)),
            "summary_table": str(SUMMARY_TABLE_PATH.relative_to(PROJECT_ROOT)),
            "rolling_gjr_table": str(ROLLING_TABLE_PATH.relative_to(PROJECT_ROOT)),
            "figure": str(FIG_PATH.relative_to(PROJECT_ROOT)),
            "macro_cache": str(MACRO_CACHE_PATH.relative_to(PROJECT_ROOT)),
        },
        "limitations": [
            "GLD ETF is a proxy for spot/futures gold; Stage 2 contribution gate still asks for futures/institutional validation.",
            "Treasury basis is proxied by 10Y minus 13-week yield; this is an external curve/basis proxy, not repo specialness.",
            "The primary news-impact regression is reduced-form and should not be described as a full structural GJR likelihood estimate.",
            "Regime labels are pre-specified and lagged, but their economic interpretation remains a hypothesis requiring robustness.",
        ],
    }
    RESULTS_PATH.write_text(json.dumps(json_ready(results), indent=2) + "\n", encoding="utf-8")
    print(f"{EXPERIMENT_ID}: wrote {RESULTS_PATH.relative_to(PROJECT_ROOT)}")
    print(json.dumps(json_ready(conclusion), indent=2))


if __name__ == "__main__":
    main()
