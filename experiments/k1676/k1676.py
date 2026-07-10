#!/usr/bin/env python3
"""K1676: lagged USD / real-yield regimes and gold safe-haven effectiveness.

This is an empirical, descriptive conditional-hedge experiment.  It extends
K1628 instead of repeating it: K1628 asks whether GLD protects on equity-tail
days in general; K1676 asks whether information known by t-1 about the dollar
and the 10-year real yield changes that contemporaneous tail-day relationship.

Timing policy
-------------
* UUP and DFII10 regime variables are computed from trailing 252-market-day
  windows and explicitly shifted by one market day.
* 63-day rolling correlations are also shifted by one day.
* SPY tail labels and GLD returns are same-day by design because the estimand
  is crisis co-movement / hedge effectiveness, not a trading forecast.
* No strategy return, Sharpe ratio, or causal claim is produced.

All bootstrap procedures use seed=42.  Results JSON is written atomically.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.outliers_influence import variance_inflation_factor

matplotlib.use("Agg")
import matplotlib.pyplot as plt


EXPERIMENT_ID = "k1676"
TASK_ID = "research_safe_haven_regime"
SEED = 42
BOOT_REPS = 5_000
BOOT_BLOCK = 21
REGIME_WINDOW = 252
REGIME_MIN = 126
REGIME_Z = 0.5
CORR_WINDOW = 63
HAC_LAG = 21

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DB_PATH = REPO / "data" / "cache" / "price_cache.db"
UUP_PATH = REPO / "experiments" / "k1359" / "data" / "UUP.csv"
DFII10_PATH = REPO / "experiments" / "K1609" / "data" / "fred_dfii10.csv"
RESULTS_PATH = HERE / "k1676_results.json"
PANEL_PATH = HERE / "data" / "analysis_panel.csv"
FIG_CORR_PATH = HERE / "figures" / "fig1_lagged_correlations.png"
FIG_HEDGE_PATH = HERE / "figures" / "fig2_tail_hedge_by_regime.png"

LITERATURE = [
    {
        "citation": "Baur and Lucey (2010), Financial Review 45, 217-229",
        "title": "Is Gold a Hedge or a Safe Haven? An Analysis of Stocks, Bonds and Gold",
        "url": "https://doi.org/10.1111/j.1540-6288.2010.00244.x",
        "design_use": "Defines a hedge by average co-movement and a safe haven by co-movement in equity-market tails.",
    },
    {
        "citation": "Reboredo (2013), Journal of Banking & Finance 37, 2665-2676",
        "title": "Is gold a safe haven or a hedge for the US dollar? Implications for risk management",
        "url": "https://doi.org/10.1016/j.jbankfin.2013.03.020",
        "design_use": "Motivates separating gold-equity protection from gold-dollar average and tail dependence.",
    },
    {
        "citation": "Baur and McDermott (2016), Journal of Behavioral and Experimental Finance 10, 63-71",
        "title": "Why is gold a safe haven?",
        "url": "https://doi.org/10.1016/j.jbef.2016.03.002",
        "design_use": "Motivates regime dependence and the possibility that USD safe-haven demand masks gold protection.",
    },
    {
        "citation": "Batten, Loncarski, Szilagyi, and Zhou (2026), SSRN working paper",
        "title": "Gold and U.S. Treasuries as Competing Safe Assets",
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6627301",
        "design_use": "Motivates conditioning gold relationships on real-rate and dollar states; not treated as a settled result.",
    },
]


def _json_number(value: Any) -> Any:
    """Convert NumPy/pandas scalars and non-finite values for strict JSON."""
    if value is None:
        return None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        value = float(value)
        return value if np.isfinite(value) else None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def _clean_for_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _clean_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_for_json(v) for v in obj]
    return _json_number(obj)


def load_sqlite_price(ticker: str) -> pd.Series:
    with sqlite3.connect(str(DB_PATH)) as con:
        df = pd.read_sql(
            "SELECT date, close, adj_close FROM price_data WHERE ticker=? ORDER BY date",
            con,
            params=(ticker,),
            parse_dates=["date"],
        )
    if df.empty:
        raise ValueError(f"No local price rows for {ticker}")
    price = df["adj_close"].where(df["adj_close"].notna(), df["close"])
    out = pd.Series(pd.to_numeric(price, errors="coerce").to_numpy(), index=df["date"], name=ticker)
    return out[~out.index.duplicated(keep="last")].dropna().sort_index()


def load_uup() -> pd.Series:
    df = pd.read_csv(UUP_PATH)
    if not {"Date", "Close"}.issubset(df.columns):
        raise ValueError(f"Unexpected UUP schema: {list(df.columns)}")
    dates = pd.to_datetime(df["Date"], errors="coerce").dt.tz_localize(None).dt.normalize()
    values = pd.to_numeric(df["Close"], errors="coerce")
    out = pd.Series(values.to_numpy(), index=dates, name="UUP")
    return out[~out.index.duplicated(keep="last")].dropna().sort_index()


def load_dfii10() -> pd.Series:
    df = pd.read_csv(DFII10_PATH)
    date_col = "date" if "date" in df.columns else "observation_date"
    if date_col not in df.columns or "DFII10" not in df.columns:
        raise ValueError(f"Unexpected DFII10 schema: {list(df.columns)}")
    dates = pd.to_datetime(df[date_col], errors="coerce").dt.tz_localize(None).dt.normalize()
    values = pd.to_numeric(df["DFII10"], errors="coerce")
    out = pd.Series(values.to_numpy(), index=dates, name="dfii10")
    return out[~out.index.duplicated(keep="last")].dropna().sort_index()


def rolling_zscore(series: pd.Series) -> pd.Series:
    mean = series.rolling(REGIME_WINDOW, min_periods=REGIME_MIN).mean()
    std = series.rolling(REGIME_WINDOW, min_periods=REGIME_MIN).std(ddof=1)
    return (series - mean) / std.replace(0.0, np.nan)


def state_from_z(z: pd.Series) -> pd.Series:
    state = pd.Series(0, index=z.index, dtype="int8")
    state.loc[z >= REGIME_Z] = 1
    state.loc[z <= -REGIME_Z] = -1
    state.loc[z.isna()] = 0
    return state


def build_panel() -> tuple[pd.DataFrame, dict[str, Any]]:
    spy = load_sqlite_price("SPY")
    gld = load_sqlite_price("GLD")
    uup = load_uup()
    dfii10 = load_dfii10()

    # Compute every return on its own native trading-date series first.  The
    # previous observation date is carried into the merge so a multi-day UUP
    # return can never be paired with a one-day SPY/GLD return.
    native_frames = []
    for prefix, series in [("spy", spy), ("gld", gld), ("uup", uup)]:
        frame = pd.DataFrame(
            {
                f"{prefix}_price": series,
                f"r_{prefix}": np.log(series / series.shift(1)),
                f"{prefix}_return_start": series.index.to_series().shift(1),
            }
        )
        native_frames.append(frame)
    merged_native = pd.concat(native_frames, axis=1, join="inner").sort_index()
    same_return_interval = (
        (merged_native["spy_return_start"] == merged_native["gld_return_start"])
        & (merged_native["spy_return_start"] == merged_native["uup_return_start"])
    )
    mismatched_interval_rows = int((~same_return_interval).sum())
    panel = merged_native.loc[same_return_interval].copy()
    # Point-in-time conservative alignment: map each market date only to the
    # latest FRED observation dated on/before that date, then impose one extra
    # market-day lag. This avoids assuming that an observation dated t was
    # tradable before the ETF close on t. The file is current-vintage rather
    # than ALFRED vintage data, which remains an explicit limitation.
    market_dates = pd.DataFrame({"date": panel.index}).sort_values("date")
    fred_dates = dfii10.rename("dfii10_observed").reset_index()
    fred_dates.columns = ["observation_date", "dfii10_observed"]
    aligned = pd.merge_asof(
        market_dates,
        fred_dates.sort_values("observation_date"),
        left_on="date",
        right_on="observation_date",
        direction="backward",
        allow_exact_matches=True,
    ).set_index("date")
    panel["dfii10"] = aligned["dfii10_observed"]
    panel["dfii10_observation_date"] = aligned["observation_date"]
    panel["dfii10_available_lag1"] = panel["dfii10"].shift(1)
    panel["dfii10_regime_observation_date"] = panel["dfii10_observation_date"].shift(1)
    panel["d_dfii10"] = panel["dfii10"].diff()

    # Regimes known before the outcome date.
    panel["uup_z_lag1"] = rolling_zscore(np.log(panel["uup_price"])).shift(1)
    panel["real_yield_z_lag1"] = rolling_zscore(panel["dfii10_available_lag1"])
    panel["usd_state"] = state_from_z(panel["uup_z_lag1"])
    panel["real_yield_state"] = state_from_z(panel["real_yield_z_lag1"])

    # Trailing correlation state is likewise available only through t-1.
    panel["corr_gld_spy_63_lag1"] = panel["r_gld"].rolling(CORR_WINDOW).corr(panel["r_spy"]).shift(1)
    panel["corr_gld_uup_63_lag1"] = panel["r_gld"].rolling(CORR_WINDOW).corr(panel["r_uup"]).shift(1)
    panel["corr_gld_real_yield_63_lag1"] = (
        panel["r_gld"].rolling(CORR_WINDOW).corr(panel["d_dfii10"]).shift(1)
    )

    panel["tail_1pct"] = panel["r_spy"] <= np.log(0.99)
    panel["tail_2pct"] = panel["r_spy"] <= np.log(0.98)
    panel["joint_adverse"] = (panel["usd_state"] == 1) & (panel["real_yield_state"] == 1)
    panel["joint_benign"] = (panel["usd_state"] == -1) & (panel["real_yield_state"] == -1)

    required = ["r_spy", "r_gld", "r_uup", "d_dfii10", "uup_z_lag1", "real_yield_z_lag1"]
    analysis = panel.dropna(subset=required).copy()
    if len(analysis) < 1_000:
        raise ValueError(f"Too few common analysis rows: {len(analysis)}")

    fred_gap_days = (
        analysis.index.to_series(index=analysis.index) - analysis["dfii10_regime_observation_date"]
    ).dt.days
    diagnostics = {
        "raw_price_ranges": {
            "SPY": {"start": spy.index.min(), "end": spy.index.max(), "n": len(spy)},
            "GLD": {"start": gld.index.min(), "end": gld.index.max(), "n": len(gld)},
            "UUP": {"start": uup.index.min(), "end": uup.index.max(), "n": len(uup)},
            "DFII10": {"start": dfii10.index.min(), "end": dfii10.index.max(), "n": len(dfii10)},
        },
        "analysis_start": analysis.index.min(),
        "analysis_end": analysis.index.max(),
        "n_analysis_days": len(analysis),
        "return_alignment": {
            "policy": "Each asset return is computed natively; merged rows require identical return-start dates.",
            "n_common_end_dates_before_interval_gate": len(merged_native),
            "n_mismatched_interval_rows_dropped": mismatched_interval_rows,
            "n_after_interval_gate_before_rolling_burnin": len(panel),
        },
        "input_file_mtime_utc": {
            "price_cache_db": datetime.fromtimestamp(DB_PATH.stat().st_mtime, tz=timezone.utc),
            "uup_csv": datetime.fromtimestamp(UUP_PATH.stat().st_mtime, tz=timezone.utc),
            "dfii10_csv": datetime.fromtimestamp(DFII10_PATH.stat().st_mtime, tz=timezone.utc),
        },
        "dfii10_regime_observation_gap_days": {
            "min": int(fred_gap_days.min()),
            "median": float(fred_gap_days.median()),
            "max": int(fred_gap_days.max()),
        },
        "tail_counts": {"tail_1pct": int(analysis["tail_1pct"].sum()), "tail_2pct": int(analysis["tail_2pct"].sum())},
        "state_counts": {
            "usd_strong": int((analysis["usd_state"] == 1).sum()),
            "usd_neutral": int((analysis["usd_state"] == 0).sum()),
            "usd_weak": int((analysis["usd_state"] == -1).sum()),
            "real_yield_high": int((analysis["real_yield_state"] == 1).sum()),
            "real_yield_neutral": int((analysis["real_yield_state"] == 0).sum()),
            "real_yield_low": int((analysis["real_yield_state"] == -1).sum()),
        },
        "return_summary": {
            c: {
                "mean": float(analysis[c].mean()),
                "std": float(analysis[c].std(ddof=1)),
                "skew": float(analysis[c].skew()),
                "excess_kurtosis": float(analysis[c].kurt()),
            }
            for c in ["r_spy", "r_gld", "r_uup", "d_dfii10"]
        },
    }
    analysis.index.name = "date"
    return analysis, diagnostics


def condition_metrics(df: pd.DataFrame, mask: pd.Series) -> dict[str, Any]:
    sub = df.loc[mask, ["r_spy", "r_gld"]].dropna()
    n = len(sub)
    if n == 0:
        return {"n": 0}
    corr = sub["r_spy"].corr(sub["r_gld"]) if n > 2 else np.nan
    return {
        "n": n,
        "spy_mean_return": sub["r_spy"].mean(),
        "gld_mean_return": sub["r_gld"].mean(),
        "gld_positive_rate": (sub["r_gld"] > 0).mean(),
        "spy_gld_corr": corr,
        "gld_offset_ratio_mean": (sub["r_gld"] / (-sub["r_spy"]).clip(lower=1e-9)).mean(),
    }


def metric_grid(panel: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    specs = {
        "usd": ("usd_state", {"strong": 1, "neutral": 0, "weak": -1}),
        "real_yield": ("real_yield_state", {"high": 1, "neutral": 0, "low": -1}),
    }
    for tail_name in ["tail_1pct", "tail_2pct"]:
        out[tail_name] = {}
        for family, (state_col, states) in specs.items():
            out[tail_name][family] = {
                name: condition_metrics(panel, panel[tail_name] & (panel[state_col] == code))
                for name, code in states.items()
            }
        out[tail_name]["joint"] = {
            "adverse_strong_usd_high_real_yield": condition_metrics(panel, panel[tail_name] & panel["joint_adverse"]),
            "benign_weak_usd_low_real_yield": condition_metrics(panel, panel[tail_name] & panel["joint_benign"]),
        }
    return out


def hac_extreme_state_tests(panel: pd.DataFrame, state_col: str, tail_col: str) -> dict[str, Any]:
    sub = panel.loc[panel[tail_col] & panel[state_col].isin([-1, 1]), ["r_spy", "r_gld", state_col]].dropna()
    if len(sub) < 30 or (sub[state_col] == 1).sum() < 10 or (sub[state_col] == -1).sum() < 10:
        return {"n": len(sub), "error": "insufficient extreme-state tail observations"}

    high = (sub[state_col] == 1).astype(float)
    x_mean = sm.add_constant(pd.DataFrame({"high_state": high}, index=sub.index), has_constant="add")
    mean_fit = sm.OLS(sub["r_gld"], x_mean).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAG})

    x_beta = pd.DataFrame(
        {
            "r_spy": sub["r_spy"],
            "high_state": high,
            "r_spy_x_high": sub["r_spy"] * high,
        },
        index=sub.index,
    )
    x_beta = sm.add_constant(x_beta, has_constant="add")
    beta_fit = sm.OLS(sub["r_gld"], x_beta).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAG})
    return {
        "n": len(sub),
        "n_high": int(high.sum()),
        "n_low": int((1 - high).sum()),
        "mean_high_minus_low": {
            "coef": mean_fit.params["high_state"],
            "se_hac": mean_fit.bse["high_state"],
            "t_hac": mean_fit.tvalues["high_state"],
            "p_two_sided": mean_fit.pvalues["high_state"],
        },
        "tail_beta_high_minus_low": {
            "coef": beta_fit.params["r_spy_x_high"],
            "se_hac": beta_fit.bse["r_spy_x_high"],
            "t_hac": beta_fit.tvalues["r_spy_x_high"],
            "p_two_sided": beta_fit.pvalues["r_spy_x_high"],
            "beta_low": beta_fit.params["r_spy"],
            "beta_high": beta_fit.params["r_spy"] + beta_fit.params["r_spy_x_high"],
        },
    }


def interaction_design(
    panel: pd.DataFrame,
    tail_col: str,
    z_cols: list[str],
) -> tuple[pd.Series, pd.DataFrame]:
    """Build a hierarchical Baur-style tail-state interaction design.

    Every triple interaction is accompanied by all lower-order terms. The
    regime variables are continuous, pre-outcome z-scores; extreme buckets are
    retained only for descriptive charts and sparse-cell diagnostics.
    """
    needed = ["r_gld", "r_spy", tail_col, *z_cols]
    data = panel[needed].dropna().copy()
    tail = data[tail_col].astype(float)
    spy = data["r_spy"].astype(float)
    x = pd.DataFrame(
        {
            "r_spy": spy,
            "tail": tail,
            "r_spy_x_tail": spy * tail,
        },
        index=data.index,
    )
    for z_col in z_cols:
        prefix = "usd" if z_col == "uup_z_lag1" else "real_yield"
        z = data[z_col].astype(float)
        x[f"z_{prefix}"] = z
        x[f"tail_x_z_{prefix}"] = tail * z
        x[f"r_spy_x_z_{prefix}"] = spy * z
        x[f"r_spy_x_tail_x_z_{prefix}"] = spy * tail * z
    x = sm.add_constant(x, has_constant="add")
    return data["r_gld"].astype(float), x


def mean_interaction_design(
    panel: pd.DataFrame,
    tail_col: str,
    z_cols: list[str],
) -> tuple[pd.Series, pd.DataFrame]:
    """Design for average GLD protection, separate from the tail-beta model."""
    needed = ["r_gld", tail_col, *z_cols]
    data = panel[needed].dropna().copy()
    tail = data[tail_col].astype(float)
    x = pd.DataFrame({"tail": tail}, index=data.index)
    for z_col in z_cols:
        prefix = "usd" if z_col == "uup_z_lag1" else "real_yield"
        z = data[z_col].astype(float)
        x[f"z_{prefix}"] = z
        x[f"tail_x_z_{prefix}"] = tail * z
    x = sm.add_constant(x, has_constant="add")
    return data["r_gld"].astype(float), x


def fit_hac_design(y: pd.Series, x: pd.DataFrame) -> dict[str, Any]:
    fit = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAG})
    residual = pd.Series(fit.resid, index=y.index)
    return {
        "n": len(y),
        "hac_lag": HAC_LAG,
        "r_squared": fit.rsquared,
        "coefficients": {
            name: {
                "coef": fit.params[name],
                "se_hac": fit.bse[name],
                "t_hac": fit.tvalues[name],
                "p_two_sided": fit.pvalues[name],
            }
            for name in x.columns
        },
        "residual_acf": {f"lag_{lag}": residual.autocorr(lag=lag) for lag in [1, 5, 21]},
    }


def fit_interaction_model(panel: pd.DataFrame, tail_col: str, z_cols: list[str]) -> dict[str, Any]:
    y_mean, x_mean = mean_interaction_design(panel, tail_col, z_cols)
    y_beta, x_beta = interaction_design(panel, tail_col, z_cols)
    return {
        "tail_n": int(panel.loc[y_beta.index, tail_col].sum()),
        "mean_protection_model": fit_hac_design(y_mean, x_mean),
        "tail_beta_model": fit_hac_design(y_beta, x_beta),
    }


def run_interaction_models(panel: pd.DataFrame, tail_col: str) -> dict[str, Any]:
    separate_usd = fit_interaction_model(panel, tail_col, ["uup_z_lag1"])
    separate_real_yield = fit_interaction_model(panel, tail_col, ["real_yield_z_lag1"])
    joint = fit_interaction_model(panel, tail_col, ["uup_z_lag1", "real_yield_z_lag1"])

    z_frame = panel[["uup_z_lag1", "real_yield_z_lag1"]].dropna()
    z_with_const = sm.add_constant(z_frame, has_constant="add")
    vif = {
        z_with_const.columns[i]: variance_inflation_factor(z_with_const.to_numpy(), i)
        for i in range(1, z_with_const.shape[1])
    }
    return {
        "separate_usd": separate_usd,
        "separate_real_yield": separate_real_yield,
        "joint_primary": joint,
        "regime_correlation": z_frame.corr().iloc[0, 1],
        "regime_vif": vif,
    }


PRIMARY_SPECS = {
    "usd_tail_mean": ("mean_protection_model", "tail_x_z_usd", "negative"),
    "usd_tail_beta": ("tail_beta_model", "r_spy_x_tail_x_z_usd", "positive"),
    "real_yield_tail_mean": ("mean_protection_model", "tail_x_z_real_yield", "negative"),
    "real_yield_tail_beta": ("tail_beta_model", "r_spy_x_tail_x_z_real_yield", "positive"),
}


def block_bootstrap_joint_coefficients(
    panel: pd.DataFrame,
    tail_col: str,
) -> dict[str, Any]:
    """Circular-block bootstrap the four joint-model primary coefficients."""
    y_mean, x_mean = mean_interaction_design(panel, tail_col, ["uup_z_lag1", "real_yield_z_lag1"])
    y_beta, x_beta = interaction_design(panel, tail_col, ["uup_z_lag1", "real_yield_z_lag1"])
    if not y_mean.index.equals(y_beta.index):
        raise ValueError("Mean and beta interaction designs are not aligned")
    matrices = {
        "mean_protection_model": (y_mean.to_numpy(dtype=float), x_mean.to_numpy(dtype=float), x_mean.columns),
        "tail_beta_model": (y_beta.to_numpy(dtype=float), x_beta.to_numpy(dtype=float), x_beta.columns),
    }
    observed: dict[str, float] = {}
    for output_name, (model_name, coefficient, _) in PRIMARY_SPECS.items():
        y_values, x_values, columns = matrices[model_name]
        beta, *_ = np.linalg.lstsq(x_values, y_values, rcond=None)
        observed[output_name] = float(beta[columns.get_loc(coefficient)])
    n = len(y_beta)
    n_blocks = int(np.ceil(n / BOOT_BLOCK))
    rng = np.random.default_rng(SEED)
    draws = {name: [] for name in PRIMARY_SPECS}
    for _ in range(BOOT_REPS):
        starts = rng.integers(0, n, size=n_blocks)
        idx = np.concatenate([(np.arange(BOOT_BLOCK) + start) % n for start in starts])[:n]
        fitted: dict[str, tuple[np.ndarray, pd.Index]] = {}
        for model_name, (y_values, x_values, columns) in matrices.items():
            beta, *_ = np.linalg.lstsq(x_values[idx], y_values[idx], rcond=None)
            fitted[model_name] = (beta, columns)
        for output_name, (model_name, coefficient, _) in PRIMARY_SPECS.items():
            beta, columns = fitted[model_name]
            draws[output_name].append(float(beta[columns.get_loc(coefficient)]))
    return {
        "seed": SEED,
        "block": BOOT_BLOCK,
        "reps": BOOT_REPS,
        "coefficients": {
            name: {
                "observed": observed[name],
                "ci95_percentile": [np.quantile(draws[name], 0.025), np.quantile(draws[name], 0.975)],
            }
            for name in PRIMARY_SPECS
        },
    }


def leave_one_year_out_signs(panel: pd.DataFrame, tail_col: str) -> dict[str, Any]:
    """Check whether any single calendar year flips a primary coefficient."""
    y_all, _ = interaction_design(panel, tail_col, ["uup_z_lag1", "real_yield_z_lag1"])
    years = sorted(pd.Index(y_all.index.year).unique().tolist())
    estimates: dict[str, dict[str, Any]] = {name: {} for name in PRIMARY_SPECS}
    for year in years:
        reduced = panel.loc[panel.index.year != year]
        y_mean, x_mean = mean_interaction_design(reduced, tail_col, ["uup_z_lag1", "real_yield_z_lag1"])
        y_beta, x_beta = interaction_design(reduced, tail_col, ["uup_z_lag1", "real_yield_z_lag1"])
        model_fits: dict[str, tuple[np.ndarray, pd.Index]] = {}
        for model_name, y, x in [
            ("mean_protection_model", y_mean, x_mean),
            ("tail_beta_model", y_beta, x_beta),
        ]:
            beta, *_ = np.linalg.lstsq(x.to_numpy(dtype=float), y.to_numpy(dtype=float), rcond=None)
            model_fits[model_name] = (beta, x.columns)
        for output_name, (model_name, coefficient, _) in PRIMARY_SPECS.items():
            beta, columns = model_fits[model_name]
            estimates[output_name][str(year)] = beta[columns.get_loc(coefficient)]

    full_mean_y, full_mean_x = mean_interaction_design(panel, tail_col, ["uup_z_lag1", "real_yield_z_lag1"])
    full_beta_y, full_beta_x = interaction_design(panel, tail_col, ["uup_z_lag1", "real_yield_z_lag1"])
    full_models: dict[str, tuple[np.ndarray, pd.Index]] = {}
    for model_name, y, x in [
        ("mean_protection_model", full_mean_y, full_mean_x),
        ("tail_beta_model", full_beta_y, full_beta_x),
    ]:
        beta, *_ = np.linalg.lstsq(x.to_numpy(dtype=float), y.to_numpy(dtype=float), rcond=None)
        full_models[model_name] = (beta, x.columns)
    summary: dict[str, Any] = {}
    for name, by_year in estimates.items():
        model_name, coefficient, _ = PRIMARY_SPECS[name]
        beta, columns = full_models[model_name]
        full = float(beta[columns.get_loc(coefficient)])
        signs = [np.sign(float(value)) for value in by_year.values() if float(value) != 0]
        full_sign = np.sign(full)
        summary[name] = {
            "full_sample": full,
            "leave_one_year_out": by_year,
            "no_sign_flip": bool(all(sign == full_sign for sign in signs)),
            "same_sign_rate": float(np.mean([sign == full_sign for sign in signs])) if signs else None,
        }
    return {"years_omitted": years, "coefficients": summary}


def sparse_cell_gate(panel: pd.DataFrame, tail_col: str) -> dict[str, Any]:
    cells = {
        "usd_strong": panel[tail_col] & (panel["usd_state"] == 1),
        "usd_weak": panel[tail_col] & (panel["usd_state"] == -1),
        "real_yield_high": panel[tail_col] & (panel["real_yield_state"] == 1),
        "real_yield_low": panel[tail_col] & (panel["real_yield_state"] == -1),
    }
    details = {
        name: {
            "n": int(mask.sum()),
            "distinct_years": int(panel.index[mask].year.nunique()),
            "n_ge_50": bool(mask.sum() >= 50),
            "years_ge_5": bool(panel.index[mask].year.nunique() >= 5),
        }
        for name, mask in cells.items()
    }
    return {
        "rule": "Each primary extreme-state tail cell must have n>=50 and at least five distinct calendar years.",
        "cells": details,
        "pass": bool(all(item["n_ge_50"] and item["years_ge_5"] for item in details.values())),
    }


def adjust_joint_primary(
    interaction_models: dict[str, Any],
    coefficient_bootstrap: dict[str, Any],
    loyo: dict[str, Any],
) -> dict[str, Any]:
    joint = interaction_models["joint_primary"]
    pvals = [
        float(joint[model_name]["coefficients"][coefficient]["p_two_sided"])
        for model_name, coefficient, _ in PRIMARY_SPECS.values()
    ]
    reject, adjusted, _, _ = multipletests(pvals, alpha=0.05, method="holm")
    output: dict[str, Any] = {}
    for (name, (model_name, coefficient, expected)), holm_reject, holm_p in zip(
        PRIMARY_SPECS.items(), reject, adjusted, strict=True
    ):
        result = joint[model_name]["coefficients"][coefficient]
        coef = float(result["coef"])
        ci = coefficient_bootstrap["coefficients"][name]["ci95_percentile"]
        direction_ok = coef < 0 if expected == "negative" else coef > 0
        ci_excludes_zero = bool((ci[0] > 0) or (ci[1] < 0))
        no_sign_flip = bool(loyo["coefficients"][name]["no_sign_flip"])
        output[name] = {
            "coef": coef,
            "t_hac": result["t_hac"],
            "raw_p": result["p_two_sided"],
            "holm_p": float(holm_p),
            "holm_reject_5pct": bool(holm_reject),
            "harvey_abs_t_ge_3": bool(abs(float(result["t_hac"])) >= 3.0),
            "expected_direction": expected,
            "direction_ok": bool(direction_ok),
            "block_bootstrap_ci95": ci,
            "bootstrap_ci_excludes_zero": ci_excludes_zero,
            "loyo_no_sign_flip": no_sign_flip,
            "strict_pass": bool(
                holm_reject
                and abs(float(result["t_hac"])) >= 3.0
                and direction_ok
                and ci_excludes_zero
                and no_sign_flip
            ),
        }
    return {
        "model": (
            "Joint mean-protection model r_GLD ~ tail * {z_USD,z_real_yield} plus joint hierarchical "
            "tail-beta model r_GLD ~ r_SPY * tail * {z_USD,z_real_yield}; all lower-order terms included"
        ),
        "method": "Holm across four pre-specified partial interaction coefficients",
        "n_tests": len(output),
        "tests": output,
    }


def _corr(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 4 or np.std(x, ddof=1) == 0 or np.std(y, ddof=1) == 0:
        return np.nan
    return float(np.corrcoef(x, y)[0, 1])


def _bootstrap_stat(sample: pd.DataFrame, state_col: str, tail_col: str) -> tuple[float, float, float] | None:
    base = sample[tail_col].to_numpy(dtype=bool)
    state = sample[state_col].to_numpy()
    spy = sample["r_spy"].to_numpy(dtype=float)
    gld = sample["r_gld"].to_numpy(dtype=float)
    high = base & (state == 1) & np.isfinite(spy) & np.isfinite(gld)
    low = base & (state == -1) & np.isfinite(spy) & np.isfinite(gld)
    if high.sum() < 8 or low.sum() < 8:
        return None
    mean_diff = float(gld[high].mean() - gld[low].mean())
    positive_diff = float((gld[high] > 0).mean() - (gld[low] > 0).mean())
    corr_diff = _corr(spy[high], gld[high]) - _corr(spy[low], gld[low])
    return mean_diff, positive_diff, corr_diff


def circular_block_bootstrap(panel: pd.DataFrame, state_col: str, tail_col: str) -> dict[str, Any]:
    rng = np.random.default_rng(SEED)
    n = len(panel)
    n_blocks = int(np.ceil(n / BOOT_BLOCK))
    observed = _bootstrap_stat(panel, state_col, tail_col)
    draws: list[tuple[float, float, float]] = []
    for _ in range(BOOT_REPS):
        starts = rng.integers(0, n, size=n_blocks)
        idx = np.concatenate([(np.arange(BOOT_BLOCK) + s) % n for s in starts])[:n]
        stat = _bootstrap_stat(panel.iloc[idx], state_col, tail_col)
        if stat is not None and np.all(np.isfinite(stat)):
            draws.append(stat)
    arr = np.asarray(draws, dtype=float)
    names = ["mean_return_high_minus_low", "positive_rate_high_minus_low", "corr_high_minus_low"]
    if observed is None or len(arr) < BOOT_REPS * 0.8:
        return {"observed": observed, "n_effective": len(arr), "error": "insufficient bootstrap draws"}
    return {
        "seed": SEED,
        "block": BOOT_BLOCK,
        "reps_requested": BOOT_REPS,
        "n_effective": len(arr),
        "statistics": {
            name: {
                "observed": observed[i],
                "ci95_percentile": [np.quantile(arr[:, i], 0.025), np.quantile(arr[:, i], 0.975)],
            }
            for i, name in enumerate(names)
        },
    }


def rolling_correlation_diagnostics(panel: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in ["corr_gld_spy_63_lag1", "corr_gld_uup_63_lag1", "corr_gld_real_yield_63_lag1"]:
        tail = panel.loc[panel["tail_1pct"], col].dropna()
        normal = panel.loc[~panel["tail_1pct"], col].dropna()
        out[col] = {
            "all_mean": panel[col].mean(),
            "tail_day_mean": tail.mean(),
            "normal_day_mean": normal.mean(),
            "tail_minus_normal": tail.mean() - normal.mean(),
            "all_negative_rate": (panel[col].dropna() < 0).mean(),
            "tail_day_negative_rate": (tail < 0).mean(),
        }
    return out


def subperiod_metrics(panel: pd.DataFrame) -> dict[str, Any]:
    periods = {
        "2016_2019": ("2016-01-01", "2019-12-31"),
        "2020_2022": ("2020-01-01", "2022-12-31"),
        "2023_2026": ("2023-01-01", "2026-12-31"),
    }
    output: dict[str, Any] = {}
    for label, (start, end) in periods.items():
        sub = panel.loc[start:end]
        output[label] = {
            "n_days": len(sub),
            "tail_1pct_n": int(sub["tail_1pct"].sum()),
            "usd_strong_tail": condition_metrics(sub, sub["tail_1pct"] & (sub["usd_state"] == 1)),
            "usd_weak_tail": condition_metrics(sub, sub["tail_1pct"] & (sub["usd_state"] == -1)),
            "real_yield_high_tail": condition_metrics(sub, sub["tail_1pct"] & (sub["real_yield_state"] == 1)),
            "real_yield_low_tail": condition_metrics(sub, sub["tail_1pct"] & (sub["real_yield_state"] == -1)),
        }
    return output


def robustness_direction_gate(
    primary_adjustment: dict[str, Any],
    robustness_models: dict[str, Any],
    robustness_sparse_gate: dict[str, Any],
) -> dict[str, Any]:
    joint = robustness_models["joint_primary"]
    tests: dict[str, Any] = {}
    for name, (model_name, coefficient, _) in PRIMARY_SPECS.items():
        primary_coef = float(primary_adjustment["tests"][name]["coef"])
        robustness_coef = float(joint[model_name]["coefficients"][coefficient]["coef"])
        tests[name] = {
            "primary_tail_1pct_coef": primary_coef,
            "robustness_tail_2pct_coef": robustness_coef,
            "same_sign": bool(np.sign(primary_coef) == np.sign(robustness_coef)),
        }
    return {
        "rule": "A primary strict pass cannot become PASS if the -2% coefficient reverses sign; sparse -2% cells force INCONCLUSIVE.",
        "tests": tests,
        "all_same_sign": bool(all(item["same_sign"] for item in tests.values())),
        "sparse_cell_gate": robustness_sparse_gate,
    }


def build_verdict(
    primary_adjustment: dict[str, Any],
    subperiods: dict[str, Any],
    sparse_gate: dict[str, Any],
    robustness_gate: dict[str, Any],
) -> dict[str, Any]:
    passed = [name for name, test in primary_adjustment.get("tests", {}).items() if test["strict_pass"]]
    passed_robustness = (
        bool(all(robustness_gate["tests"][name]["same_sign"] for name in passed)) if passed else None
    )
    if passed and (not sparse_gate["pass"] or not robustness_gate["sparse_cell_gate"]["pass"]):
        label = "INCONCLUSIVE_SPARSE_REGIME_TAIL_CELLS"
        claim = (
            "At least one interaction clears the statistical screens, but an extreme-state tail cell "
            "at the primary or -2% robustness threshold fails the pre-specified n>=50 / five-year support gate; "
            "the result cannot be upgraded to PASS."
        )
    elif passed and not passed_robustness:
        label = "NULL_PRIMARY_EFFECT_REVERSES_AT_MINUS_2PCT_TAIL"
        claim = "A primary interaction clears its own screens but reverses sign at the fixed -2% tail threshold."
    elif passed:
        label = "CONDITIONAL_PASS_LAGGED_MACRO_STATE_MODIFIES_GOLD_TAIL_HEDGE"
        claim = (
            "At least one pre-specified USD/real-yield interaction survives Holm correction, "
            "the Harvey |t|>=3 screen, and the expected-direction gate. The finding remains "
            "conditional co-movement evidence, not a trading or causal result."
        )
    else:
        label = "NULL_NO_ROBUST_LAGGED_MACRO_STATE_MODIFIER"
        claim = (
            "Neither lagged USD nor lagged real-yield state robustly changes GLD tail-day mean "
            "protection or SPY-GLD tail beta under the pre-specified Holm + Harvey gate."
        )
    return {
        "label": label,
        "strict_primary_passes": passed,
        "claim": claim,
        "sparse_cell_gate_pass": sparse_gate["pass"],
        "robustness_tail_2pct_sparse_gate_pass": robustness_gate["sparse_cell_gate"]["pass"],
        "passed_coefficients_same_sign_at_tail_2pct": passed_robustness,
        "subperiod_note": "Subperiod cells are robustness diagnostics only; sparse cells cannot upgrade the primary verdict.",
        "n_subperiods": len(subperiods),
    }


def make_figures(panel: pd.DataFrame, metrics: dict[str, Any]) -> None:
    plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "Heiti TC", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    series = [
        ("corr_gld_spy_63_lag1", "GLD-SPY trailing 63d correlation (t-1)"),
        ("corr_gld_uup_63_lag1", "GLD-UUP trailing 63d correlation (t-1)"),
        ("corr_gld_real_yield_63_lag1", "GLD-real-yield-change trailing 63d correlation (t-1)"),
    ]
    for ax, (col, title) in zip(axes, series, strict=True):
        ax.plot(panel.index, panel[col], lw=0.9, color="#2b6cb0")
        ax.axhline(0, lw=0.8, color="black")
        tail_dates = panel.index[panel["tail_1pct"]]
        ax.scatter(tail_dates, panel.loc[tail_dates, col], s=7, color="#c53030", alpha=0.45, label="SPY <= -1%")
        ax.set_title(title)
        ax.grid(alpha=0.2)
    axes[0].legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(FIG_CORR_PATH, dpi=180, bbox_inches="tight")
    plt.close(fig)

    primary = metrics["tail_1pct"]
    labels = ["USD strong", "USD weak", "Real yield high", "Real yield low"]
    cells = [
        primary["usd"]["strong"],
        primary["usd"]["weak"],
        primary["real_yield"]["high"],
        primary["real_yield"]["low"],
    ]
    means = [100 * (cell.get("gld_mean_return") or 0.0) for cell in cells]
    positives = [100 * (cell.get("gld_positive_rate") or 0.0) for cell in cells]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    colors = ["#b83280", "#3182ce", "#dd6b20", "#38a169"]
    axes[0].bar(labels, means, color=colors)
    axes[0].axhline(0, color="black", lw=0.8)
    axes[0].set_ylabel("Mean GLD return on SPY <= -1% days (%)")
    axes[0].tick_params(axis="x", rotation=20)
    axes[1].bar(labels, positives, color=colors)
    axes[1].axhline(50, color="black", lw=0.8, ls="--")
    axes[1].set_ylabel("GLD positive rate on SPY <= -1% days (%)")
    axes[1].tick_params(axis="x", rotation=20)
    fig.suptitle("Gold tail-hedge outcomes by lagged macro regime")
    fig.tight_layout()
    fig.savefig(FIG_HEDGE_PATH, dpi=180, bbox_inches="tight")
    plt.close(fig)


def atomic_write_json(payload: dict[str, Any]) -> None:
    tmp_path = RESULTS_PATH.with_name(f".{RESULTS_PATH.name}.tmp")
    cleaned = _clean_for_json(payload)
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(cleaned, handle, ensure_ascii=False, indent=2, allow_nan=False)
    with tmp_path.open("r", encoding="utf-8") as handle:
        json.load(handle)
    os.replace(tmp_path, RESULTS_PATH)


def main() -> None:
    (HERE / "data").mkdir(exist_ok=True)
    (HERE / "figures").mkdir(exist_ok=True)
    panel, diagnostics = build_panel()
    metrics = metric_grid(panel)

    extreme_bucket_tests = {
        "usd": hac_extreme_state_tests(panel, "usd_state", "tail_1pct"),
        "real_yield": hac_extreme_state_tests(panel, "real_yield_state", "tail_1pct"),
    }
    interaction_models = run_interaction_models(panel, "tail_1pct")
    coefficient_bootstrap = block_bootstrap_joint_coefficients(panel, "tail_1pct")
    loyo = leave_one_year_out_signs(panel, "tail_1pct")
    sparse_gate = sparse_cell_gate(panel, "tail_1pct")
    primary_adjustment = adjust_joint_primary(interaction_models, coefficient_bootstrap, loyo)
    robustness_models = run_interaction_models(panel, "tail_2pct")
    robustness_sparse_gate = sparse_cell_gate(panel, "tail_2pct")
    robustness_gate = robustness_direction_gate(primary_adjustment, robustness_models, robustness_sparse_gate)
    bucket_bootstrap = {
        "usd_tail_1pct": circular_block_bootstrap(panel, "usd_state", "tail_1pct"),
        "real_yield_tail_1pct": circular_block_bootstrap(panel, "real_yield_state", "tail_1pct"),
    }
    subperiods = subperiod_metrics(panel)
    rolling_corr = rolling_correlation_diagnostics(panel)
    verdict = build_verdict(primary_adjustment, subperiods, sparse_gate, robustness_gate)

    panel.to_csv(PANEL_PATH)
    make_figures(panel, metrics)

    results = {
        "experiment_id": EXPERIMENT_ID,
        "task_id": TASK_ID,
        "generated_at_utc": datetime.now(timezone.utc),
        "title": "Lagged USD / real-yield regimes and gold safe-haven effectiveness",
        "research_type": "empirical descriptive conditional hedge study",
        "data": {
            "sources": {
                "SPY_GLD": "data/cache/price_cache.db::price_data (local cache of yfinance adjusted daily prices)",
                "UUP": "experiments/k1359/data/UUP.csv (archived yfinance adjusted close)",
                "DFII10": "experiments/K1609/data/fred_dfii10.csv (FRED 10-Year TIPS real yield)",
            },
            "proxy_disclosure": {
                "gold": "GLD ETF is a tradable gold proxy, not spot bullion or COMEX futures.",
                "dollar": "UUP is a USD-futures ETF proxy, not the broad trade-weighted dollar index.",
                "real_yield": "DFII10 is the FRED 10-year TIPS constant-maturity real yield; daily changes are percentage-point changes.",
            },
            "diagnostics": diagnostics,
        },
        "methodology": {
            "estimand": "Same-day GLD protection/co-movement on SPY tail days, conditional on macro states known by t-1.",
            "tail_definitions": {"primary": "SPY log return <= log(0.99)", "robustness": "SPY log return <= log(0.98)"},
            "regimes": (
                "Trailing 252-market-day z-score of log UUP level or DFII10 level, min 126; "
                "strong/high if z>=+0.5, weak/low if z<=-0.5; all shifted one day."
            ),
            "lookahead_policy": [
                "uup_z_lag1 and real_yield_z_lag1 use explicit shift(1)",
                "rolling correlations use explicit shift(1)",
                "DFII10 uses backward merge_asof by observation date and then one extra market-day availability lag; no backward fill is allowed",
                "same-day tail labels are descriptive safe-haven outcomes and are never used as trading signals",
            ],
            "primary_tests": (
                "Joint hierarchical OLS-HAC model with all lower-order terms for r_SPY * tail * continuous lagged USD/real-yield z-scores. "
                "The four partial tail-mean/tail-beta interaction coefficients are Holm-adjusted and must also pass expected direction, "
                "Harvey |t|>=3, 21-day circular-block CI, leave-one-year-out sign, and sparse-cell gates."
            ),
            "bootstrap": f"Circular moving-block bootstrap, block={BOOT_BLOCK}, reps={BOOT_REPS}, seed={SEED}.",
            "subperiods": ["2016-2019", "2020-2022", "2023-2026"],
            "literature": LITERATURE,
        },
        "metrics": metrics,
        "primary_interaction_models": interaction_models,
        "primary_multiple_testing": primary_adjustment,
        "primary_coefficient_block_bootstrap": coefficient_bootstrap,
        "primary_leave_one_year_out": loyo,
        "primary_sparse_cell_gate": sparse_gate,
        "robustness_tail_2pct_gate": robustness_gate,
        "extreme_bucket_descriptive_hac": extreme_bucket_tests,
        "extreme_bucket_block_bootstrap": bucket_bootstrap,
        "robustness_tail_2pct_interaction_models": robustness_models,
        "rolling_correlation_diagnostics": rolling_corr,
        "subperiods": subperiods,
        "verdict": verdict,
        "limitations": [
            "The common sample begins in 2016 after local-cache and rolling-window constraints and therefore excludes the 2008 crisis.",
            "GLD and UUP are ETF proxies with fees, tracking error, and U.S. trading-hour alignment; results are not bullion or global-FX evidence.",
            "DFII10 is current-vintage daily market-yield data, not ALFRED vintage data. merge_asof plus one market-day lag is conservative but cannot prove historical real-time availability or establish causality.",
            "Tail-day cells become sparse after regime splitting, especially at the -2% threshold and in subperiods.",
            "Regime thresholds were pre-specified but remain modeling choices; no threshold search is used to upgrade the verdict.",
            "Contemporaneous safe-haven effectiveness is not a forecast, strategy return, or recommendation.",
        ],
        "artifacts": {
            "analysis_panel": str(PANEL_PATH.relative_to(REPO)),
            "figures": [str(FIG_CORR_PATH.relative_to(REPO)), str(FIG_HEDGE_PATH.relative_to(REPO))],
        },
    }
    atomic_write_json(results)
    print(json.dumps(_clean_for_json({"verdict": verdict, "diagnostics": diagnostics}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
