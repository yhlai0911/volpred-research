#!/usr/bin/env python3
"""K1716: daily-OHLC diagnostic of the 2022 expansion of SPX expiries.

This is deliberately a proxy diagnostic, not a causal 0DTE study.  The
identifying contrast is the change on Tuesday/Thursday relative to the
already-established Monday/Wednesday/Friday expiry weekdays.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy.stats import norm


SEED = 42
START = "2018-01-01"
END_EXCLUSIVE = "2026-07-16"
TUESDAY_LISTING = pd.Timestamp("2022-04-18")
THURSDAY_LISTING = pd.Timestamp("2022-05-11")
POST_START = pd.Timestamp("2022-05-19")  # first listed Thursday expiry
EPS = 1e-12

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "SPY_ohlcv.csv"
RESULTS_PATH = ROOT / "K1716_results.json"
FIGURE_PATH = ROOT / "k1716_intraday_share.png"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: dict) -> None:
    """Write a validated JSON artifact atomically in its destination directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    try:
        json.loads(temporary.read_text(encoding="utf-8"))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def refresh_snapshot(path: Path = DATA_PATH) -> pd.DataFrame:
    raw = yf.download(
        "SPY",
        start=START,
        end=END_EXCLUSIVE,
        auto_adjust=False,
        actions=False,
        progress=False,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned no SPY observations")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    keep = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    missing = sorted(set(keep).difference(raw.columns))
    if missing:
        raise RuntimeError(f"missing yfinance columns: {missing}")
    out = raw.loc[:, keep].copy().reset_index()
    out["Date"] = pd.to_datetime(out["Date"]).dt.strftime("%Y-%m-%d")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        out.to_csv(handle, index=False, float_format="%.10g")
    try:
        check = pd.read_csv(temporary, float_precision="round_trip")
        if len(check) != len(out):
            raise RuntimeError(f"snapshot validation row mismatch: {len(check)} != {len(out)}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return out


def load_snapshot(path: Path = DATA_PATH, refresh: bool = False) -> pd.DataFrame:
    if refresh or not path.exists():
        refresh_snapshot(path)
    frame = pd.read_csv(path, parse_dates=["Date"], float_precision="round_trip")
    required = {"Date", "Open", "High", "Low", "Close", "Adj Close", "Volume"}
    if not required.issubset(frame.columns):
        raise ValueError(f"snapshot lacks columns: {sorted(required - set(frame.columns))}")
    return frame


def prepare_daily(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    df = raw.sort_values("Date").drop_duplicates("Date", keep="last").copy()
    numeric = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    for col in numeric:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    valid = (
        df[numeric].notna().all(axis=1)
        & (df[["Open", "High", "Low", "Close"]] > 0).all(axis=1)
        & (df["High"] >= df[["Open", "Close", "Low"]].max(axis=1))
        & (df["Low"] <= df[["Open", "Close", "High"]].min(axis=1))
    )
    invalid_rows = int((~valid).sum())
    df = df.loc[valid].copy()

    previous_close = df["Close"].shift(1)
    log_hl = np.log(df["High"] / df["Low"])
    df["parkinson_var"] = log_hl.pow(2) / (4.0 * math.log(2.0))
    df["overnight_var"] = np.log(df["Open"] / previous_close).pow(2)
    df["c2c_var"] = np.log(df["Close"] / previous_close).pow(2)
    df["proxy_total_var"] = df["parkinson_var"] + df["overnight_var"]
    df["intraday_share"] = df["parkinson_var"] / df["proxy_total_var"].clip(lower=EPS)
    df["log_parkinson_var"] = np.log(df["parkinson_var"].clip(lower=EPS))
    df["log_overnight_var"] = np.log(df["overnight_var"].clip(lower=EPS))
    df["log_c2c_var"] = np.log(df["c2c_var"].clip(lower=EPS))
    clipped_share = df["intraday_share"].clip(1e-6, 1.0 - 1e-6)
    df["logit_intraday_share"] = np.log(clipped_share / (1.0 - clipped_share))

    df["dow"] = df["Date"].dt.dayofweek
    df["tue_thu"] = df["dow"].isin([1, 3]).astype(float)
    df["post"] = (df["Date"] >= POST_START).astype(float)
    df["post_x_tue_thu"] = df["post"] * df["tue_thu"]
    # Explicit point-in-time controls: every row uses information through t-1.
    df["lag5_log_total"] = np.log(df["proxy_total_var"].clip(lower=EPS)).rolling(5).mean().shift(1)
    df["lag1_abs_return"] = np.log(df["Close"] / previous_close).abs().shift(1)
    angle = 2.0 * np.pi * (df["Date"].dt.month - 1) / 12.0
    df["month_sin"] = np.sin(angle)
    df["month_cos"] = np.cos(angle)

    diagnostics = {
        "downloaded_rows": int(len(raw)),
        "deduplicated_valid_rows": int(len(df)),
        "invalid_ohlc_rows_removed": invalid_rows,
        "duplicate_dates_removed": int(len(raw) - len(raw.drop_duplicates("Date", keep="last"))),
    }
    return df, diagnostics


def design_matrix(df: pd.DataFrame) -> pd.DataFrame:
    dow = pd.get_dummies(df["dow"].astype(int), prefix="dow", drop_first=True, dtype=float)
    x = pd.concat(
        [
            df[["post", "post_x_tue_thu", "lag5_log_total", "lag1_abs_return", "month_sin", "month_cos"]],
            dow,
        ],
        axis=1,
    )
    return sm.add_constant(x.astype(float), has_constant="add")


def fit_did(df: pd.DataFrame, outcome: str) -> tuple[dict[str, float | int], np.ndarray, pd.DataFrame]:
    cols = [
        outcome,
        "post",
        "post_x_tue_thu",
        "lag5_log_total",
        "lag1_abs_return",
        "month_sin",
        "month_cos",
        "dow",
    ]
    sample = df.loc[:, cols].replace([np.inf, -np.inf], np.nan).dropna().copy()
    x = design_matrix(sample)
    y = sample[outcome].astype(float)
    hac_lag = max(1, int(math.ceil(len(sample) ** (1.0 / 3.0))))
    fitted = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": hac_lag})
    term = "post_x_tue_thu"
    coefficient = float(fitted.params[term])
    standard_error = float(fitted.bse[term])
    t_stat = coefficient / standard_error
    p_value = float(2.0 * norm.sf(abs(t_stat)))
    result: dict[str, float | int] = {
        "n": int(len(sample)),
        "coefficient": coefficient,
        "standard_error_hac": standard_error,
        "t_stat_hac": float(t_stat),
        "p_value_hac": p_value,
        "hac_lag": hac_lag,
        "r_squared": float(fitted.rsquared),
        "post_main_effect": float(fitted.params["post"]),
    }
    return result, fitted.resid.to_numpy(), sample


def moving_block_bootstrap_ci(
    sample: pd.DataFrame,
    outcome: str,
    reps: int = 1000,
    block_length: int = 10,
) -> tuple[float, float, int]:
    """Pairs moving-block bootstrap for the DiD interaction coefficient."""
    rng = np.random.default_rng(SEED)
    n = len(sample)
    starts = np.arange(0, n - block_length + 1)
    n_blocks = int(math.ceil(n / block_length))
    coefs: list[float] = []
    for _ in range(reps):
        chosen = rng.choice(starts, size=n_blocks, replace=True)
        index = np.concatenate([np.arange(s, s + block_length) for s in chosen])[:n]
        draw = sample.iloc[index].reset_index(drop=True)
        try:
            fitted = sm.OLS(draw[outcome].astype(float), design_matrix(draw)).fit()
            value = float(fitted.params["post_x_tue_thu"])
            if np.isfinite(value):
                coefs.append(value)
        except (ValueError, np.linalg.LinAlgError):  # silent-ok: invalid draws are counted and the 95% floor fails loudly below
            continue
    if len(coefs) < int(0.95 * reps):
        raise RuntimeError(f"only {len(coefs)}/{reps} valid bootstrap draws")
    low, high = np.quantile(coefs, [0.025, 0.975])
    return float(low), float(high), len(coefs)


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    ordered = sorted(p_values.items(), key=lambda item: item[1])
    m = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, (name, value) in enumerate(ordered):
        candidate = min(1.0, (m - rank) * value)
        running = max(running, candidate)
        adjusted[name] = running
    return adjusted


def placebo_fit(df: pd.DataFrame, outcome: str, break_date: pd.Timestamp) -> dict[str, float | int]:
    if break_date < TUESDAY_LISTING:
        placebo = df.loc[df["Date"] < TUESDAY_LISTING].copy()
        scope = "pre-treatment-only"
    else:
        placebo = df.loc[df["Date"] >= POST_START].copy()
        scope = "post-treatment-only"
    placebo["post"] = (placebo["Date"] >= break_date).astype(float)
    placebo["post_x_tue_thu"] = placebo["post"] * placebo["tue_thu"]
    result, _, _ = fit_did(placebo, outcome)
    result["sample_scope"] = scope
    return result


def pretrend_fit(df: pd.DataFrame, outcome: str) -> dict[str, float | int]:
    """Test differential linear trends using only never-yet-treated dates."""
    pre = df.loc[df["Date"] < TUESDAY_LISTING].copy()
    pre["trend_years"] = (pre["Date"] - pre["Date"].min()).dt.days / 365.25
    pre["trend_x_tue_thu"] = pre["trend_years"] * pre["tue_thu"]
    cols = [
        outcome,
        "trend_years",
        "trend_x_tue_thu",
        "lag5_log_total",
        "lag1_abs_return",
        "month_sin",
        "month_cos",
        "dow",
    ]
    sample = pre.loc[:, cols].replace([np.inf, -np.inf], np.nan).dropna().copy()
    dow = pd.get_dummies(sample["dow"].astype(int), prefix="dow", drop_first=True, dtype=float)
    x = pd.concat(
        [
            sample[["trend_years", "trend_x_tue_thu", "lag5_log_total", "lag1_abs_return", "month_sin", "month_cos"]],
            dow,
        ],
        axis=1,
    )
    x = sm.add_constant(x.astype(float), has_constant="add")
    hac_lag = max(1, int(math.ceil(len(sample) ** (1.0 / 3.0))))
    fitted = sm.OLS(sample[outcome].astype(float), x).fit(cov_type="HAC", cov_kwds={"maxlags": hac_lag})
    term = "trend_x_tue_thu"
    t_stat = float(fitted.tvalues[term])
    return {
        "n": int(len(sample)),
        "coefficient_per_year": float(fitted.params[term]),
        "t_stat_hac": t_stat,
        "p_value_hac": float(2.0 * norm.sf(abs(t_stat))),
        "hac_lag": hac_lag,
    }


def descriptive_table(df: pd.DataFrame) -> dict[str, dict[str, float | int]]:
    usable = df.loc[(df["Date"] < TUESDAY_LISTING) | (df["Date"] >= POST_START)].copy()
    output: dict[str, dict[str, float | int]] = {}
    for post_name, post_value in [("pre", 0.0), ("post", 1.0)]:
        for group_name, group_value in [("tue_thu", 1.0), ("mon_wed_fri", 0.0)]:
            cell = usable.loc[(usable["post"] == post_value) & (usable["tue_thu"] == group_value)]
            output[f"{post_name}_{group_name}"] = {
                "n": int(len(cell)),
                "mean_parkinson_var": float(cell["parkinson_var"].mean()),
                "mean_overnight_var": float(cell["overnight_var"].mean()),
                "mean_c2c_var": float(cell["c2c_var"].mean()),
                "mean_intraday_share": float(cell["intraday_share"].mean()),
            }
    return output


def make_figure(df: pd.DataFrame) -> None:
    plot = df.set_index("Date").copy()
    monthly = (
        plot.groupby([pd.Grouper(freq="ME"), "tue_thu"])["intraday_share"]
        .mean()
        .unstack("tue_thu")
        .rename(columns={0.0: "Mon/Wed/Fri", 1.0: "Tue/Thu"})
    )
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(10, 5.2))
    monthly.rolling(3, min_periods=1).mean().plot(ax=ax, linewidth=1.8)
    ax.axvspan(TUESDAY_LISTING, POST_START, color="#f5a623", alpha=0.18, label="listing transition")
    ax.axvline(POST_START, color="#9b1c31", linestyle="--", linewidth=1.3)
    ax.set(title="SPY daily-OHLC proxy: intraday variance share", xlabel="", ylabel="Parkinson / (Parkinson + overnight)")
    ax.legend(frameon=False, ncol=3)
    fig.tight_layout()
    fig.savefig(FIGURE_PATH, dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="refresh the frozen yfinance snapshot")
    args = parser.parse_args()

    raw = load_snapshot(refresh=args.refresh)
    daily, data_checks = prepare_daily(raw)
    analysis = daily.loc[(daily["Date"] < TUESDAY_LISTING) | (daily["Date"] >= POST_START)].copy()
    outcomes = ["log_parkinson_var", "log_overnight_var", "log_c2c_var", "logit_intraday_share"]
    regressions: dict[str, dict[str, float | int | list[float]]] = {}
    raw_p: dict[str, float] = {}
    for outcome in outcomes:
        result, _, sample = fit_did(analysis, outcome)
        low, high, valid_reps = moving_block_bootstrap_ci(sample, outcome)
        result["bootstrap_95_ci"] = [low, high]
        result["bootstrap_valid_reps"] = valid_reps
        regressions[outcome] = result
        raw_p[outcome] = float(result["p_value_hac"])
    adjusted = holm_adjust(raw_p)
    for outcome, value in adjusted.items():
        regressions[outcome]["holm_p_value"] = value
        regressions[outcome]["harvey_abs_t_ge_3"] = bool(abs(float(regressions[outcome]["t_stat_hac"])) >= 3.0)

    primary_consistent = (
        regressions["log_parkinson_var"]["harvey_abs_t_ge_3"]
        and regressions["logit_intraday_share"]["harvey_abs_t_ge_3"]
        and float(regressions["log_parkinson_var"]["holm_p_value"]) < 0.05
        and float(regressions["logit_intraday_share"]["holm_p_value"]) < 0.05
        and np.sign(float(regressions["log_parkinson_var"]["coefficient"]))
        == np.sign(float(regressions["logit_intraday_share"]["coefficient"]))
    )
    placebos = {
        date.strftime("%Y-%m-%d"): {
            outcome: placebo_fit(daily, outcome, date)
            for outcome in ["log_parkinson_var", "logit_intraday_share"]
        }
        for date in [pd.Timestamp("2021-05-19"), pd.Timestamp("2023-05-19")]
    }
    pretrends = {
        outcome: pretrend_fit(daily, outcome)
        for outcome in ["log_parkinson_var", "logit_intraday_share"]
    }
    make_figure(daily)

    result_payload = {
        "experiment_id": "K1716",
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "seed": SEED,
        "data": {
            "source": "Yahoo Finance via yfinance; SPY unadjusted daily OHLCV",
            "requested_start": START,
            "requested_end_exclusive": END_EXCLUSIVE,
            "effective_start": daily["Date"].min().strftime("%Y-%m-%d"),
            "effective_end": daily["Date"].max().strftime("%Y-%m-%d"),
            "snapshot_path": str(DATA_PATH.relative_to(ROOT)),
            "snapshot_sha256": sha256(DATA_PATH),
            "reader": "pandas.read_csv(float_precision='round_trip')",
            **data_checks,
        },
        "provenance": {
            "script_sha256": sha256(Path(__file__)),
            "figure_sha256": sha256(FIGURE_PATH),
            "numpy_version": np.__version__,
            "pandas_version": pd.__version__,
            "statsmodels_version": sm.__version__,
            "yfinance_version": yf.__version__,
        },
        "design": {
            "treatment_weekdays": ["Tuesday", "Thursday"],
            "control_weekdays": ["Monday", "Wednesday", "Friday"],
            "tuesday_listing_date": TUESDAY_LISTING.strftime("%Y-%m-%d"),
            "thursday_listing_date": THURSDAY_LISTING.strftime("%Y-%m-%d"),
            "post_start_first_full_thursday_expiry": POST_START.strftime("%Y-%m-%d"),
            "transition_dates_excluded": ["2022-04-18", "2022-05-18"],
            "interaction": "post x Tue/Thu, conditional on weekday FE, lagged proxy variance, lagged absolute return, and month seasonality",
            "lookahead_policy": "lag5_log_total and lag1_abs_return use explicit shift(1); outcome is contemporaneous diagnostic, not a forecast",
            "inference": "Newey-West HAC with ceil(n^(1/3)) lag; 1,000-rep 10-day moving-block bootstrap; Holm family across four outcomes; Harvey |t|>=3",
        },
        "descriptive": descriptive_table(daily),
        "regressions": regressions,
        "placebo_breaks": placebos,
        "pre_treatment_differential_trends": pretrends,
        "prior_replication": {
            "experiment": "K1477",
            "relationship": "independent stricter re-verification of the same SPY daily-OHLC question",
            "incremental_design": "official listing transition exclusion, log outcomes, weekday fixed effects, lagged controls, canonical HAC bandwidth, Holm, block bootstrap, restricted-era placebos, and pretrend tests",
            "qualitative_consistency": "both K1477 and K1716 find no Tue/Thu-specific post-expansion interaction",
        },
        "verdict": "CONDITIONAL_PROXY_BREAK" if primary_consistent else "NULL_PROXY_DIAGNOSTIC",
        "primary_success_criteria_met": bool(primary_consistent),
        "limitations": [
            "SPY daily OHLC is not SPX intraday realized variance or options order flow.",
            "The fixed 2022-Q2 breakpoint coincides with monetary-policy and volatility-regime changes.",
            "The Tue/Thu interaction improves on a raw pre/post comparison but does not identify 0DTE volume or dealer gamma causally.",
            "Daily range estimators lose the intraday timing needed to test market-maker hedging mechanisms.",
        ],
        "artifacts": {"figure": FIGURE_PATH.name},
    }
    atomic_write_json(RESULTS_PATH, result_payload)
    print(json.dumps({"verdict": result_payload["verdict"], "results": str(RESULTS_PATH), "snapshot_sha256": result_payload["data"]["snapshot_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
