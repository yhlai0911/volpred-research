from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf


EXPERIMENT_ID = "research_mortgage_rate_lock_in_housing_turnover_freeze_ho"
ROOT = Path(__file__).resolve().parents[2]
EXP_DIR = ROOT / "experiments" / EXPERIMENT_ID
DATA_DIR = EXP_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
FIGURES_DIR = EXP_DIR / "figures"
RESULTS_PATH = EXP_DIR / f"{EXPERIMENT_ID}_results.json"

RANDOM_SEED = 20260702
N_BOOT = 3000
TRAIN_END = pd.Timestamp("2021-12-31")
EPS = 1e-12

FRED_SERIES = {
    "MORTGAGE30US": "30-year fixed mortgage rate",
    "ACTLISCOUUS": "Realtor.com active listing count",
    "NEWLISCOUUS": "Realtor.com new listing count",
    "MSACSR": "New houses months supply",
    "HOUST": "Housing starts",
    "PERMIT": "Building permits",
    "HSN1F": "New one-family houses sold",
}

TARGET_GROUPS = {
    "homebuilder": ["XHB", "ITB", "DHI", "LEN", "PHM", "TOL"],
    "regional_bank": ["KRE", "KBE"],
    "housing_platform": ["Z", "OPEN", "RKT", "UWMC"],
}


@dataclass
class BootstrapSummary:
    mean: float
    ci_low: float
    ci_high: float
    p_two_sided: float
    n_clusters: int


def ensure_dirs() -> None:
    for path in [DATA_DIR, RAW_DIR, FIGURES_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def month_end_index(index: pd.Index | pd.Series) -> pd.DatetimeIndex:
    return pd.to_datetime(index).to_period("M").to_timestamp("M")


def to_jsonable(value):
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [to_jsonable(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if math.isnan(float(value)) or math.isinf(float(value)):
            return None
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if pd.isna(value):
        return None
    return value


def read_fred_series(code: str) -> pd.Series:
    path = RAW_DIR / f"fred_{code}.csv"
    if path.exists():
        df = pd.read_csv(path)
    else:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={code}"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        path.write_text(response.text, encoding="utf-8")
        df = pd.read_csv(path)
    if "observation_date" not in df.columns or code not in df.columns:
        raise ValueError(f"Unexpected FRED CSV shape for {code}: {df.columns.tolist()}")
    dates = pd.to_datetime(df["observation_date"])
    values = pd.to_numeric(df[code].replace(".", np.nan), errors="coerce")
    series = pd.Series(values.to_numpy(dtype=float), index=dates, name=code).dropna()
    return series


def monthly_fred_panel() -> tuple[pd.DataFrame, dict]:
    raw = {code: read_fred_series(code) for code in FRED_SERIES}
    monthly = pd.DataFrame(index=pd.date_range("1970-01-31", "2030-12-31", freq="ME"))
    for code, series in raw.items():
        by_month = series.groupby(month_end_index(series.index)).last()
        monthly[code] = by_month
    monthly = monthly.dropna(how="all")
    meta = {
        code: {
            "label": FRED_SERIES[code],
            "start": series.index.min(),
            "end": series.index.max(),
            "n_obs": int(series.shape[0]),
        }
        for code, series in raw.items()
    }
    return monthly, meta


def causal_z(series: pd.Series, min_periods: int = 24) -> pd.Series:
    mean = series.expanding(min_periods=min_periods).mean().shift(1)
    std = series.expanding(min_periods=min_periods).std(ddof=0).shift(1)
    return (series - mean) / std.replace(0.0, np.nan)


def yoy(series: pd.Series) -> pd.Series:
    return series / series.shift(12) - 1.0


def build_signals(fred_monthly: pd.DataFrame) -> pd.DataFrame:
    df = fred_monthly.copy()
    embedded_rate = df["MORTGAGE30US"].shift(6).ewm(
        span=36,
        min_periods=24,
        adjust=False,
    ).mean()
    lock_wedge = df["MORTGAGE30US"] - embedded_rate

    raw = pd.DataFrame(index=df.index)
    raw["mortgage_rate"] = df["MORTGAGE30US"]
    raw["embedded_rate_proxy"] = embedded_rate
    raw["lock_in_wedge"] = lock_wedge
    raw["lock_in_wedge_z"] = causal_z(lock_wedge)
    raw["new_listings_yoy"] = yoy(df["NEWLISCOUUS"])
    raw["active_listings_yoy"] = yoy(df["ACTLISCOUUS"])
    raw["months_supply"] = df["MSACSR"]
    raw["housing_starts_yoy"] = yoy(df["HOUST"])
    raw["permits_yoy"] = yoy(df["PERMIT"])
    raw["new_home_sales_yoy"] = yoy(df["HSN1F"])

    components = pd.DataFrame(index=df.index)
    components["new_listing_shortfall_z"] = -causal_z(raw["new_listings_yoy"])
    components["active_inventory_z"] = causal_z(raw["active_listings_yoy"])
    components["months_supply_z"] = causal_z(raw["months_supply"])
    components["starts_shortfall_z"] = -causal_z(raw["housing_starts_yoy"])
    components["permits_shortfall_z"] = -causal_z(raw["permits_yoy"])
    components["new_home_sales_shortfall_z"] = -causal_z(raw["new_home_sales_yoy"])
    raw = raw.join(components)
    raw["turnover_freeze_z"] = components[
        [
            "new_listing_shortfall_z",
            "months_supply_z",
            "starts_shortfall_z",
            "permits_shortfall_z",
            "new_home_sales_shortfall_z",
        ]
    ].mean(axis=1, skipna=False)

    # Lookahead control: target RV in month t only sees features observed at t-1.
    lagged_cols = [
        "mortgage_rate",
        "embedded_rate_proxy",
        "lock_in_wedge",
        "lock_in_wedge_z",
        "turnover_freeze_z",
        "new_listing_shortfall_z",
        "active_inventory_z",
        "months_supply_z",
        "starts_shortfall_z",
        "permits_shortfall_z",
        "new_home_sales_shortfall_z",
    ]
    lagged = raw[lagged_cols].shift(1).add_suffix("_lag")
    signals = raw.join(lagged)
    signals.index.name = "month"
    signals.to_csv(DATA_DIR / "monthly_signals.csv")
    return signals


def extract_adjusted_close(download: pd.DataFrame, symbol: str) -> pd.Series:
    if download.empty:
        raise ValueError(f"No yfinance data for {symbol}")

    data = download.copy()
    if isinstance(data.columns, pd.MultiIndex):
        if "Adj Close" in data.columns.get_level_values(0):
            close = data["Adj Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
        elif "Adj Close" in data.columns.get_level_values(-1):
            close = data.xs("Adj Close", level=-1, axis=1)
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
        elif "Close" in data.columns.get_level_values(0):
            close = data["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
        else:
            raise ValueError(f"Cannot find close column for {symbol}")
    elif "Adj Close" in data.columns:
        close = data["Adj Close"]
    elif "Close" in data.columns:
        close = data["Close"]
    else:
        raise ValueError(f"Cannot find close column for {symbol}")

    close = pd.Series(close, name=symbol)
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close.dropna()


def download_adjusted_close(symbol: str) -> pd.Series | None:
    path = RAW_DIR / f"yfinance_adj_close_{symbol}.csv"
    if path.exists():
        df = pd.read_csv(path, parse_dates=["Date"])
        if symbol in df.columns:
            series = pd.Series(df[symbol].to_numpy(dtype=float), index=df["Date"], name=symbol)
            return series.dropna()

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=FutureWarning)
            data = yf.download(
                symbol,
                start="2010-01-01",
                auto_adjust=False,
                progress=False,
                threads=False,
                timeout=30,
            )
        close = extract_adjusted_close(data, symbol)
    except Exception as exc:
        print(f"Skipping {symbol}: {exc}")
        return None

    out = close.rename(symbol).to_frame()
    out.index.name = "Date"
    out.reset_index().to_csv(path, index=False)
    return close


def build_monthly_rv_panel(signals: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rows = []
    price_meta = {}
    for group, symbols in TARGET_GROUPS.items():
        for symbol in symbols:
            close = download_adjusted_close(symbol)
            if close is None or close.shape[0] < 260:
                price_meta[symbol] = {"group": group, "usable": False, "reason": "too_short_or_missing"}
                continue
            returns = np.log(close).diff().dropna()
            monthly_rv = returns.pow(2).groupby(month_end_index(returns.index)).sum()
            monthly_rv = monthly_rv[monthly_rv > 0]
            if monthly_rv.shape[0] < 24:
                price_meta[symbol] = {"group": group, "usable": False, "reason": "monthly_rv_too_short"}
                continue
            baseline = monthly_rv.rolling(12, min_periods=9).mean().shift(1)
            asset = pd.DataFrame(
                {
                    "month": monthly_rv.index,
                    "symbol": symbol,
                    "group": group,
                    "rv": monthly_rv.to_numpy(dtype=float),
                    "baseline_rv": baseline.reindex(monthly_rv.index).to_numpy(dtype=float),
                }
            )
            rows.append(asset)
            price_meta[symbol] = {
                "group": group,
                "usable": True,
                "start": close.index.min(),
                "end": close.index.max(),
                "n_daily_prices": int(close.shape[0]),
                "n_monthly_rv": int(monthly_rv.shape[0]),
            }

    if not rows:
        raise RuntimeError("No target asset had usable price history")

    panel = pd.concat(rows, ignore_index=True)
    panel["month"] = pd.to_datetime(panel["month"])
    panel = panel.merge(
        signals.reset_index(),
        on="month",
        how="left",
        validate="many_to_one",
    )
    panel = panel.replace([np.inf, -np.inf], np.nan)
    panel["scaled_rv"] = panel["rv"] / panel["baseline_rv"] - 1.0
    panel["log_rv_rel"] = np.log(panel["rv"].clip(EPS)) - np.log(panel["baseline_rv"].clip(EPS))
    panel = panel.dropna(
        subset=[
            "rv",
            "baseline_rv",
            "scaled_rv",
            "log_rv_rel",
            "lock_in_wedge_z_lag",
            "turnover_freeze_z_lag",
        ]
    )
    panel.to_csv(DATA_DIR / "monthly_rv_panel.csv", index=False)
    return panel, price_meta


def clustered_ols(panel: pd.DataFrame) -> dict:
    data = panel.copy()
    group_dummies = pd.get_dummies(data["group"], prefix="group", drop_first=True, dtype=float)
    x = pd.concat(
        [
            data[["lock_in_wedge_z_lag", "turnover_freeze_z_lag"]].astype(float),
            group_dummies,
        ],
        axis=1,
    )
    x = sm.add_constant(x, has_constant="add")
    y = data["log_rv_rel"].astype(float)
    month_groups = data["month"].dt.strftime("%Y-%m")
    model = sm.OLS(y, x).fit(cov_type="cluster", cov_kwds={"groups": month_groups})
    params = dict(zip(x.columns, model.params))
    tvalues = dict(zip(x.columns, model.tvalues))
    pvalues = dict(zip(x.columns, model.pvalues))
    conf = model.conf_int()
    conf_int = {
        col: {"low": conf.loc[col, 0], "high": conf.loc[col, 1]}
        for col in x.columns
    }
    return {
        "n_rows": int(data.shape[0]),
        "n_months": int(data["month"].nunique()),
        "n_assets": int(data["symbol"].nunique()),
        "r_squared": float(model.rsquared),
        "params": params,
        "tvalues": tvalues,
        "pvalues": pvalues,
        "conf_int_95": conf_int,
        "covariance": "clustered_by_month",
    }


def qlike(actual: pd.Series, forecast: pd.Series) -> pd.Series:
    a = actual.astype(float).clip(lower=EPS)
    f = forecast.astype(float).clip(lower=EPS)
    return np.log(f) + a / f


def bootstrap_mean(values: np.ndarray, rng: np.random.Generator, n_boot: int = N_BOOT) -> BootstrapSummary:
    clean = np.asarray(values, dtype=float)
    clean = clean[np.isfinite(clean)]
    if clean.size == 0:
        return BootstrapSummary(np.nan, np.nan, np.nan, np.nan, 0)
    boot = np.empty(n_boot)
    for i in range(n_boot):
        sample = rng.choice(clean, size=clean.size, replace=True)
        boot[i] = sample.mean()
    mean = float(clean.mean())
    ci_low, ci_high = np.quantile(boot, [0.025, 0.975])
    p_two = 2.0 * min(float(np.mean(boot <= 0.0)), float(np.mean(boot >= 0.0)))
    return BootstrapSummary(mean, float(ci_low), float(ci_high), min(p_two, 1.0), int(clean.size))


def fit_oos_model(panel: pd.DataFrame, rng: np.random.Generator) -> tuple[dict, pd.DataFrame]:
    train = panel[panel["month"] <= TRAIN_END].copy()
    test = panel[panel["month"] > TRAIN_END].copy()
    if train.empty or test.empty:
        raise RuntimeError("Train/test split produced an empty side")

    all_groups = sorted(panel["group"].dropna().unique())

    def design(frame: pd.DataFrame) -> pd.DataFrame:
        dummies = pd.get_dummies(frame["group"], prefix="group", dtype=float)
        for group in all_groups:
            col = f"group_{group}"
            if col not in dummies.columns:
                dummies[col] = 0.0
        dummies = dummies[[f"group_{g}" for g in all_groups]]
        dummies = dummies.drop(columns=[f"group_{all_groups[0]}"])
        x = pd.concat(
            [
                frame[["lock_in_wedge_z_lag", "turnover_freeze_z_lag"]].astype(float),
                dummies.astype(float),
            ],
            axis=1,
        )
        return sm.add_constant(x, has_constant="add")

    x_train = design(train)
    x_test = design(test)
    model = sm.OLS(train["log_rv_rel"].astype(float), x_train).fit()
    pred_log_multiplier = model.predict(x_test)
    test["model_forecast_rv"] = (test["baseline_rv"] * np.exp(pred_log_multiplier)).clip(EPS)
    test["baseline_loss"] = qlike(test["rv"], test["baseline_rv"])
    test["model_loss"] = qlike(test["rv"], test["model_forecast_rv"])
    test["loss_diff_model_minus_baseline"] = test["model_loss"] - test["baseline_loss"]
    test.to_csv(DATA_DIR / "oos_predictions.csv", index=False)

    month_loss = test.groupby("month")["loss_diff_model_minus_baseline"].mean()
    overall = bootstrap_mean(month_loss.to_numpy(), rng)
    by_group = {}
    for group, frame in test.groupby("group"):
        group_month_loss = frame.groupby("month")["loss_diff_model_minus_baseline"].mean()
        by_group[group] = bootstrap_mean(group_month_loss.to_numpy(), rng).__dict__

    result = {
        "train_start": train["month"].min(),
        "train_end": train["month"].max(),
        "test_start": test["month"].min(),
        "test_end": test["month"].max(),
        "n_train_rows": int(train.shape[0]),
        "n_test_rows": int(test.shape[0]),
        "n_test_months": int(test["month"].nunique()),
        "n_test_assets": int(test["symbol"].nunique()),
        "model_params": dict(zip(x_train.columns, model.params)),
        "mean_loss_diff_model_minus_baseline": overall.__dict__,
        "by_group": by_group,
        "interpretation": "negative loss_diff means the lock-in model improves QLIKE versus trailing-12-month RV baseline",
    }
    return result, test


def regime_contrast(panel: pd.DataFrame, rng: np.random.Generator) -> dict:
    train_signal = panel.loc[panel["month"] <= TRAIN_END, "lock_in_wedge_z_lag"].dropna()
    threshold = float(train_signal.quantile(0.75))
    data = panel.copy()
    data["high_lock_regime"] = data["lock_in_wedge_z_lag"] >= threshold

    def summarize(frame: pd.DataFrame) -> dict:
        month_data = frame.groupby("month").agg(
            high_lock_regime=("high_lock_regime", "first"),
            mean_scaled_rv=("scaled_rv", "mean"),
            n_assets=("symbol", "nunique"),
        )
        high = month_data.loc[month_data["high_lock_regime"], "mean_scaled_rv"].to_numpy()
        low = month_data.loc[~month_data["high_lock_regime"], "mean_scaled_rv"].to_numpy()
        if high.size == 0 or low.size == 0:
            return {
                "high_lock_mean_scaled_rv": np.nan,
                "other_mean_scaled_rv": np.nan,
                "diff_high_minus_other": np.nan,
                "ci_low": np.nan,
                "ci_high": np.nan,
                "p_two_sided": np.nan,
                "n_high_months": int(high.size),
                "n_other_months": int(low.size),
            }
        observed = float(high.mean() - low.mean())
        boot = np.empty(N_BOOT)
        for i in range(N_BOOT):
            boot_high = rng.choice(high, size=high.size, replace=True).mean()
            boot_low = rng.choice(low, size=low.size, replace=True).mean()
            boot[i] = boot_high - boot_low
        ci_low, ci_high = np.quantile(boot, [0.025, 0.975])
        p_two = 2.0 * min(float(np.mean(boot <= 0.0)), float(np.mean(boot >= 0.0)))
        return {
            "high_lock_mean_scaled_rv": float(high.mean()),
            "other_mean_scaled_rv": float(low.mean()),
            "diff_high_minus_other": observed,
            "ci_low": float(ci_low),
            "ci_high": float(ci_high),
            "p_two_sided": min(p_two, 1.0),
            "n_high_months": int(high.size),
            "n_other_months": int(low.size),
        }

    by_group = {group: summarize(frame) for group, frame in data.groupby("group")}
    return {
        "lock_in_wedge_z_train_q75_threshold": threshold,
        "overall": summarize(data),
        "by_group": by_group,
    }


def signal_diagnostics(signals: pd.DataFrame, panel: pd.DataFrame) -> dict:
    usable = signals.dropna(subset=["lock_in_wedge_z_lag", "turnover_freeze_z_lag"])
    return {
        "signal_start": usable.index.min(),
        "signal_end": usable.index.max(),
        "n_signal_months": int(usable.shape[0]),
        "latest_signal_month": usable.index.max(),
        "latest_mortgage_rate_lag": usable["mortgage_rate_lag"].iloc[-1],
        "latest_embedded_rate_proxy_lag": usable["embedded_rate_proxy_lag"].iloc[-1],
        "latest_lock_in_wedge_lag": usable["lock_in_wedge_lag"].iloc[-1],
        "latest_lock_in_wedge_z_lag": usable["lock_in_wedge_z_lag"].iloc[-1],
        "latest_turnover_freeze_z_lag": usable["turnover_freeze_z_lag"].iloc[-1],
        "panel_start": panel["month"].min(),
        "panel_end": panel["month"].max(),
        "n_panel_rows": int(panel.shape[0]),
        "n_panel_months": int(panel["month"].nunique()),
        "n_assets": int(panel["symbol"].nunique()),
        "rows_by_group": panel.groupby("group").size().to_dict(),
        "assets_by_group": panel.groupby("group")["symbol"].nunique().to_dict(),
    }


def lookahead_alignment_checks(signals: pd.DataFrame) -> dict:
    pairs = {
        "mortgage_rate": "mortgage_rate_lag",
        "embedded_rate_proxy": "embedded_rate_proxy_lag",
        "lock_in_wedge": "lock_in_wedge_lag",
        "lock_in_wedge_z": "lock_in_wedge_z_lag",
        "turnover_freeze_z": "turnover_freeze_z_lag",
    }
    checks = {}
    for raw_col, lag_col in pairs.items():
        diff = (signals[lag_col] - signals[raw_col].shift(1)).dropna()
        max_abs_diff = float(diff.abs().max()) if not diff.empty else np.nan
        passed = bool(np.isfinite(max_abs_diff) and max_abs_diff < 1e-12)
        checks[f"{lag_col}_equals_{raw_col}_shift_1"] = {
            "max_abs_diff": max_abs_diff,
            "passed": passed,
        }
        if not passed:
            raise AssertionError(f"Lookahead alignment failed for {lag_col}")
    return checks


def plot_signals(signals: pd.DataFrame) -> None:
    usable = signals.dropna(subset=["lock_in_wedge_lag", "turnover_freeze_z_lag"])
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    axes[0].plot(usable.index, usable["mortgage_rate_lag"], label="Mortgage rate lag")
    axes[0].plot(usable.index, usable["embedded_rate_proxy_lag"], label="Embedded-rate proxy lag")
    axes[0].set_ylabel("Percent")
    axes[0].legend(loc="upper left")
    axes[0].set_title("Mortgage lock-in proxy and housing turnover-freeze signal")
    axes[1].plot(usable.index, usable["lock_in_wedge_lag"], color="#b45f06")
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_ylabel("Rate wedge")
    axes[2].plot(usable.index, usable["turnover_freeze_z_lag"], color="#38761d")
    axes[2].axhline(0, color="black", linewidth=0.8)
    axes[2].set_ylabel("Freeze z")
    axes[2].set_xlabel("Month")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "lock_in_wedge_and_turnover_freeze.png", dpi=160)
    plt.close(fig)


def plot_oos_by_group(oos_result: dict) -> None:
    by_group = oos_result["by_group"]
    groups = list(by_group)
    means = [by_group[g]["mean"] for g in groups]
    lows = [by_group[g]["ci_low"] for g in groups]
    highs = [by_group[g]["ci_high"] for g in groups]
    yerr = [
        [m - lo for m, lo in zip(means, lows)],
        [hi - m for m, hi in zip(means, highs)],
    ]
    fig, ax = plt.subplots(figsize=(8, 4.8))
    ax.bar(groups, means, color=["#4c78a8", "#f58518", "#54a24b"][: len(groups)])
    ax.errorbar(groups, means, yerr=yerr, fmt="none", color="black", capsize=4)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylabel("QLIKE loss diff vs baseline")
    ax.set_title("OOS QLIKE by group: negative improves on baseline")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "oos_qlike_loss_diff_by_group.png", dpi=160)
    plt.close(fig)


def plot_regime_by_group(regime: dict) -> None:
    rows = []
    for group, stats in regime["by_group"].items():
        rows.append(
            {
                "group": group,
                "high_lock": stats["high_lock_mean_scaled_rv"],
                "other": stats["other_mean_scaled_rv"],
            }
        )
    df = pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=(8, 4.8))
    x = np.arange(df.shape[0])
    width = 0.36
    ax.bar(x - width / 2, df["other"], width, label="Other months", color="#9ecae9")
    ax.bar(x + width / 2, df["high_lock"], width, label="High lock-in months", color="#fdae6b")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(df["group"])
    ax.set_ylabel("Mean RV / trailing baseline - 1")
    ax.set_title("Realized variance in high lock-in regimes")
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "high_lock_scaled_rv_by_group.png", dpi=160)
    plt.close(fig)


def make_verdict(ols: dict, oos: dict, regime: dict) -> dict:
    lock_p = ols["pvalues"].get("lock_in_wedge_z_lag", np.nan)
    freeze_p = ols["pvalues"].get("turnover_freeze_z_lag", np.nan)
    oos_ci = oos["mean_loss_diff_model_minus_baseline"]
    regime_overall = regime["overall"]

    oos_pass = (
        np.isfinite(oos_ci["ci_high"])
        and oos_ci["ci_high"] < 0
        and oos_ci["mean"] < 0
    )
    ols_pass = (
        (np.isfinite(lock_p) and lock_p < 0.05)
        or (np.isfinite(freeze_p) and freeze_p < 0.05)
    )
    regime_pass = (
        np.isfinite(regime_overall["ci_low"])
        and regime_overall["ci_low"] > 0
    )

    if oos_pass and ols_pass:
        verdict = "conditional_pass"
        conclusion = (
            "The public-data lock-in/turnover-freeze proxy improves OOS QLIKE and has "
            "formal in-sample support, but it remains a proxy rather than loan-level evidence."
        )
    elif oos_pass or (ols_pass and regime_pass):
        verdict = "mixed_or_weak"
        conclusion = (
            "The evidence is directionally interesting but not strong enough across formal tests "
            "to treat mortgage lock-in as a reliable standalone RV signal."
        )
    else:
        verdict = "null_or_inconclusive"
        conclusion = (
            "This public-data pilot does not provide robust evidence that the mortgage-rate "
            "lock-in wedge and housing turnover-freeze proxies reliably forecast target RV."
        )

    return {
        "verdict": verdict,
        "conclusion": conclusion,
        "criteria": {
            "ols_support_any_core_predictor_p_lt_0_05": bool(ols_pass),
            "oos_qlike_ci_entirely_below_zero": bool(oos_pass),
            "high_lock_regime_ci_entirely_above_zero": bool(regime_pass),
        },
    }


def main() -> None:
    ensure_dirs()
    rng = np.random.default_rng(RANDOM_SEED)

    fred_monthly, fred_meta = monthly_fred_panel()
    signals = build_signals(fred_monthly)
    panel, price_meta = build_monthly_rv_panel(signals)

    ols = clustered_ols(panel)
    oos, oos_rows = fit_oos_model(panel, rng)
    regime = regime_contrast(panel, rng)
    diagnostics = signal_diagnostics(signals, panel)
    alignment_checks = lookahead_alignment_checks(signals)
    verdict = make_verdict(ols, oos, regime)

    plot_signals(signals)
    plot_oos_by_group(oos)
    plot_regime_by_group(regime)

    results = {
        "experiment_id": EXPERIMENT_ID,
        "created_at": pd.Timestamp.now(tz="Asia/Taipei").isoformat(),
        "random_seed": RANDOM_SEED,
        "data_sources": {
            "fred": {
                "url_template": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=<CODE>",
                "series": fred_meta,
                "excluded_preflight_series": {
                    "EXHOSLUSM495N": "Public FRED CSV exposed only 13 months during preflight.",
                    "EXHOSLUSM495S": "Public FRED CSV exposed only 13 months during preflight.",
                },
            },
            "prices": {
                "provider": "yfinance",
                "auto_adjust": False,
                "field_used": "Adj Close",
                "targets": TARGET_GROUPS,
                "price_meta": price_meta,
            },
        },
        "method": {
            "embedded_rate_proxy": "36-month EWMA of MORTGAGE30US shifted by 6 months",
            "lock_in_wedge": "monthly MORTGAGE30US minus embedded_rate_proxy",
            "turnover_freeze_components": [
                "negative causal z-score of new listings YoY",
                "causal z-score of months supply",
                "negative causal z-score of housing starts YoY",
                "negative causal z-score of building permits YoY",
                "negative causal z-score of new-home sales YoY",
            ],
            "lookahead_control": "All raw monthly features are shifted by one month before merging with target RV: raw_features.shift(1).",
            "target": "Monthly realized variance from summed daily squared log returns.",
            "baseline": "Trailing 12-month mean monthly RV shifted by one month.",
            "train_test_split": f"Train <= {TRAIN_END.date()}, OOS > {TRAIN_END.date()}",
            "bootstrap": {
                "seed": RANDOM_SEED,
                "n_boot": N_BOOT,
                "cluster_unit": "month",
            },
        },
        "diagnostics": diagnostics,
        "lookahead_alignment_checks": alignment_checks,
        "clustered_ols": ols,
        "oos_qlike": oos,
        "regime_contrast": regime,
        "verdict": verdict,
        "figures": [
            "figures/lock_in_wedge_and_turnover_freeze.png",
            "figures/oos_qlike_loss_diff_by_group.png",
            "figures/high_lock_scaled_rv_by_group.png",
        ],
        "outputs": [
            "data/monthly_signals.csv",
            "data/monthly_rv_panel.csv",
            "data/oos_predictions.csv",
        ],
    }

    RESULTS_PATH.write_text(
        json.dumps(to_jsonable(results), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(to_jsonable(verdict), indent=2, ensure_ascii=False))
    print(f"Saved results to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
