#!/usr/bin/env python3
"""K1556: U.S. macro release days and global ETF co-jumps.

The script deliberately separates same-day event responses from predictive
signals. Same-day release-day diagnostics are not trading signals. All
persistence signals use explicit lagged information:

    macro_release_signal = macro_release_day.shift(1)
    macro_abs_surprise_signal = macro_abs_surprise_proxy.shift(1)
"""

from __future__ import annotations

import json
import math
import re
import warnings
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy import stats

SEED = 42
np.random.seed(SEED)

EXPERIMENT_ID = "K1556"
ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

PRICE_START = "2014-01-01"
PRICE_END = "2026-06-28"
ANALYSIS_START = "2025-01-01"
COUNTRY_ETFS = ["EFA", "EEM", "EWJ", "EWG", "EWT", "EWY", "EWZ", "INDA"]
TICKERS = ["SPY", "^VIX", *COUNTRY_ETFS]
RELEASE_START_YEAR = 2025
RELEASE_END_YEAR = 2026

RELEASE_SPECS = {
    10: {"event_type": "cpi", "name": "Consumer Price Index"},
    50: {"event_type": "employment", "name": "Employment Situation"},
    53: {"event_type": "gdp", "name": "Gross Domestic Product"},
}

EVENT_TEST_COLUMNS = [
    "global_cojump_count",
    "avg_country_abs_ret_z",
    "vix_jump_z",
    "avg_country_fwd5_rv_z",
]


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, tuple):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        value = float(obj)
        return None if not math.isfinite(value) else value
    if isinstance(obj, pd.Timestamp):
        return obj.date().isoformat()
    return obj


def _rolling_z(s: pd.Series, window: int, min_periods: int) -> pd.Series:
    mu = s.rolling(window, min_periods=min_periods).mean().shift(1)
    sigma = s.rolling(window, min_periods=min_periods).std(ddof=1).shift(1)
    return (s - mu) / sigma.replace(0, np.nan)


def _obs_surprise(x: pd.Series, window: int, min_periods: int) -> pd.Series:
    mu = x.rolling(window, min_periods=min_periods).mean().shift(1)
    sigma = x.rolling(window, min_periods=min_periods).std(ddof=1).shift(1)
    return (x - mu) / sigma.replace(0, np.nan)


def download_prices() -> pd.DataFrame:
    path = DATA_DIR / "prices.csv"
    if path.exists():
        return pd.read_csv(path, parse_dates=["date"])

    raw = yf.download(TICKERS, start=PRICE_START, end=PRICE_END, auto_adjust=True, progress=False, threads=False)
    if raw.empty:
        raise RuntimeError("yfinance returned empty data")

    rows: list[pd.DataFrame] = []
    for ticker in TICKERS:
        if isinstance(raw.columns, pd.MultiIndex):
            sub = raw.xs(ticker, axis=1, level=-1)
        else:
            sub = raw.copy()
        keep = sub[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"]).copy()
        keep.columns = ["open", "high", "low", "close", "volume"]
        keep["ticker"] = ticker
        keep["date"] = keep.index
        rows.append(keep.reset_index(drop=True))

    prices = pd.concat(rows, ignore_index=True)
    prices = prices[["ticker", "date", "open", "high", "low", "close", "volume"]]
    prices.to_csv(path, index=False)
    return prices


def close_panel(prices: pd.DataFrame) -> pd.DataFrame:
    close = prices.pivot(index="date", columns="ticker", values="close").sort_index()
    return close.ffill()


def _parse_fred_calendar_table(table: pd.DataFrame, release_id: int, year: int) -> list[dict[str, Any]]:
    rows = []
    values = table.iloc[:, 0].dropna().astype(str).tolist()
    spec = RELEASE_SPECS[release_id]
    for pos, value in enumerate(values):
        if not re.search(r"\b20\d{2}\b", value):
            continue
        date_text = value.replace("Updated", "").strip()
        parsed = pd.to_datetime(date_text, errors="coerce")
        if pd.isna(parsed):
            warnings.warn(f"Could not parse FRED release date: {value!r}")
            continue
        if parsed.year != year:
            continue
        time_text = values[pos + 1] if pos + 1 < len(values) else ""
        rows.append(
            {
                "release_date": parsed.normalize(),
                "release_id": release_id,
                "event_type": spec["event_type"],
                "release_name": spec["name"],
                "calendar_time_text": time_text,
                "source_url": (
                    "https://fred.stlouisfed.org/releases/calendar"
                    f"?rid={release_id}&ve={year}-12-31&view=year&vs={year}-01-01"
                ),
            }
        )
    return rows


def load_release_calendar() -> pd.DataFrame:
    path = DATA_DIR / "fred_release_calendar.csv"
    if path.exists():
        return pd.read_csv(path, parse_dates=["release_date"])

    rows: list[dict[str, Any]] = []
    for year in range(RELEASE_START_YEAR, RELEASE_END_YEAR + 1):
        for release_id in RELEASE_SPECS:
            url = (
                "https://fred.stlouisfed.org/releases/calendar"
                f"?rid={release_id}&ve={year}-12-31&view=year&vs={year}-01-01"
            )
            try:
                tables = pd.read_html(url)
            except Exception as exc:  # pragma: no cover - network guard
                warnings.warn(f"FRED release calendar read failed for {release_id} {year}: {exc}")
                continue
            if not tables:
                warnings.warn(f"FRED release calendar returned no tables for {release_id} {year}")
                continue
            rows.extend(_parse_fred_calendar_table(tables[0], release_id, year))

    if not rows:
        raise RuntimeError("No FRED release calendar rows were fetched")

    calendar = pd.DataFrame(rows).drop_duplicates(["release_date", "release_id"]).sort_values("release_date")
    calendar.to_csv(path, index=False)
    return calendar


def read_fred_series(code: str) -> pd.Series:
    path = REPO_ROOT / "storage" / "macro" / f"fred_{code}.csv"
    df = pd.read_csv(path)
    date_col = "date" if "date" in df.columns else "observation_date"
    value_col = code if code in df.columns else [c for c in df.columns if c != date_col][0]
    s = df[[date_col, value_col]].copy()
    s[date_col] = pd.to_datetime(s[date_col])
    s[value_col] = pd.to_numeric(s[value_col], errors="coerce")
    return s.set_index(date_col)[value_col].dropna().sort_index()


def _monthly_reference_date(release_date: pd.Timestamp) -> pd.Timestamp:
    first_this_month = pd.Timestamp(year=release_date.year, month=release_date.month, day=1)
    return first_this_month - pd.DateOffset(months=1)


def _gdp_reference_date(release_date: pd.Timestamp) -> pd.Timestamp:
    month = release_date.month
    year = release_date.year
    if month <= 3:
        return pd.Timestamp(year=year - 1, month=10, day=1)
    if month <= 6:
        return pd.Timestamp(year=year, month=1, day=1)
    if month <= 9:
        return pd.Timestamp(year=year, month=4, day=1)
    return pd.Timestamp(year=year, month=7, day=1)


def build_macro_surprise_table(calendar: pd.DataFrame) -> pd.DataFrame:
    payems = read_fred_series("PAYEMS")
    unrate = read_fred_series("UNRATE")
    cpi = read_fred_series("CPIAUCSL")
    gdpc1 = read_fred_series("GDPC1")

    payems_sur = _obs_surprise(payems.diff(), 36, 12)
    unrate_sur = _obs_surprise(-unrate.diff(), 36, 12)
    employment_sur = pd.concat([payems_sur, unrate_sur], axis=1).mean(axis=1)
    cpi_sur = _obs_surprise(np.log(cpi).diff() * 100.0, 36, 12)
    gdp_sur = _obs_surprise(np.log(gdpc1).diff() * 400.0, 20, 8)

    rows: list[dict[str, Any]] = []
    for row in calendar.to_dict("records"):
        release_date = pd.Timestamp(row["release_date"])
        event_type = str(row["event_type"])
        if event_type in {"cpi", "employment"}:
            obs_date = _monthly_reference_date(release_date)
            series = cpi_sur if event_type == "cpi" else employment_sur
        elif event_type == "gdp":
            obs_date = _gdp_reference_date(release_date)
            series = gdp_sur
        else:
            continue

        surprise = float(series.loc[obs_date]) if obs_date in series.index and pd.notna(series.loc[obs_date]) else np.nan
        rows.append(
            {
                **row,
                "observation_date_proxy": obs_date,
                "macro_surprise_proxy": surprise,
                "macro_abs_surprise_proxy": abs(surprise) if math.isfinite(surprise) else np.nan,
                "surprise_proxy_method": "actual-minus-trailing-nowcast; not paid consensus or real-time vintage",
            }
        )

    out = pd.DataFrame(rows).sort_values(["release_date", "release_id"])
    out.to_csv(DATA_DIR / "macro_release_surprises.csv", index=False)
    return out


def map_releases_to_trading_days(calendar: pd.DataFrame, trading_index: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame]:
    mapped_rows: list[dict[str, Any]] = []
    for row in calendar.to_dict("records"):
        release_date = pd.Timestamp(row["release_date"])
        pos = trading_index.searchsorted(release_date)
        mapped = pd.NaT if pos >= len(trading_index) else trading_index[pos]
        mapped_rows.append({**row, "mapped_trading_date": mapped})

    mapped = pd.DataFrame(mapped_rows)
    mapped.to_csv(DATA_DIR / "release_events_mapped.csv", index=False)

    daily = pd.DataFrame(index=trading_index)
    daily["macro_release_day"] = 0.0
    daily["release_count"] = 0.0
    daily["macro_surprise_proxy"] = np.nan
    daily["macro_abs_surprise_proxy"] = np.nan
    for event_type in ["cpi", "employment", "gdp"]:
        daily[f"is_{event_type}"] = 0.0

    grouped = mapped.dropna(subset=["mapped_trading_date"]).groupby("mapped_trading_date")
    for date, g in grouped:
        date = pd.Timestamp(date)
        daily.loc[date, "macro_release_day"] = 1.0
        daily.loc[date, "release_count"] = float(len(g))
        for event_type in g["event_type"].unique():
            daily.loc[date, f"is_{event_type}"] = 1.0
        daily.loc[date, "macro_surprise_proxy"] = float(pd.to_numeric(g["macro_surprise_proxy"], errors="coerce").mean())
        daily.loc[date, "macro_abs_surprise_proxy"] = float(pd.to_numeric(g["macro_abs_surprise_proxy"], errors="coerce").mean())

    daily["macro_abs_surprise_proxy"] = daily["macro_abs_surprise_proxy"].fillna(0.0)
    daily["macro_surprise_proxy"] = daily["macro_surprise_proxy"].fillna(0.0)

    near = pd.Series(False, index=trading_index)
    for date in mapped["mapped_trading_date"].dropna():
        loc = trading_index.get_loc(pd.Timestamp(date))
        for off in range(-1, 2):
            j = loc + off
            if 0 <= j < len(trading_index):
                near.iloc[j] = True
    daily["near_macro_release"] = near.astype(float)
    daily["control_eligible"] = ((daily["macro_release_day"] == 0) & (daily["near_macro_release"] == 0)).astype(float)
    return daily, mapped


def forward_rv(rets: pd.DataFrame, horizon: int) -> pd.Series:
    rv = pd.Series(0.0, index=rets.index)
    for col in rets.columns:
        s = pd.Series(0.0, index=rets.index)
        for lag in range(horizon):
            s = s + rets[col].shift(-lag).pow(2)
        rv = rv + np.sqrt(s * 252.0 / horizon)
    return rv / len(rets.columns)


def trailing_rv(rets: pd.DataFrame, horizon: int) -> pd.Series:
    rv = pd.Series(0.0, index=rets.index)
    for col in rets.columns:
        s = pd.Series(0.0, index=rets.index)
        for lag in range(1, horizon + 1):
            s = s + rets[col].shift(lag).pow(2)
        rv = rv + np.sqrt(s * 252.0 / horizon)
    return rv / len(rets.columns)


def build_daily_features(close: pd.DataFrame, release_daily: pd.DataFrame) -> pd.DataFrame:
    rets = np.log(close).diff()
    country_rets = rets[COUNTRY_ETFS]

    daily = release_daily.copy()
    spy_std = rets["SPY"].rolling(252, min_periods=63).std(ddof=1).shift(1)
    daily["spy_ret_z"] = rets["SPY"] / spy_std.replace(0, np.nan)
    daily["spy_abs_ret_z"] = daily["spy_ret_z"].abs()

    vix_chg = np.log(close["^VIX"]).diff()
    vix_std = vix_chg.rolling(252, min_periods=63).std(ddof=1).shift(1)
    daily["vix_jump_z"] = vix_chg.clip(lower=0) / vix_std.replace(0, np.nan)

    abs_z_cols = []
    ret_z_cols = []
    for ticker in COUNTRY_ETFS:
        vol = country_rets[ticker].rolling(252, min_periods=63).std(ddof=1).shift(1)
        ret_z = country_rets[ticker] / vol.replace(0, np.nan)
        daily[f"{ticker}_ret_z"] = ret_z
        daily[f"{ticker}_abs_ret_z"] = ret_z.abs()
        daily[f"{ticker}_jump"] = (ret_z.abs() > 2.0).astype(float)
        abs_z_cols.append(f"{ticker}_abs_ret_z")
        ret_z_cols.append(f"{ticker}_ret_z")

    daily["avg_country_abs_ret_z"] = daily[abs_z_cols].mean(axis=1)
    daily["avg_country_ret_z"] = daily[ret_z_cols].mean(axis=1)
    daily["global_cojump_count"] = daily[[f"{t}_jump" for t in COUNTRY_ETFS]].sum(axis=1)

    fwd5 = forward_rv(country_rets, 5)
    tr5 = trailing_rv(country_rets, 5)
    daily["avg_country_fwd5_rv"] = fwd5
    daily["avg_country_fwd5_rv_z"] = _rolling_z(fwd5 - tr5, 252, 63)

    # Required no-lookahead guard for post-release/persistence tests.
    daily["macro_release_signal"] = daily["macro_release_day"].shift(1).fillna(0.0)
    daily["macro_abs_surprise_signal"] = daily["macro_abs_surprise_proxy"].shift(1).fillna(0.0)
    daily["macro_market_abs_proxy"] = (daily["macro_release_day"] * daily["spy_abs_ret_z"]).fillna(0.0)
    daily["macro_market_abs_signal"] = daily["macro_market_abs_proxy"].shift(1).fillna(0.0)

    valid_cols = EVENT_TEST_COLUMNS + ["spy_ret_z", "spy_abs_ret_z"]
    # FRED's public release-calendar page used here returns the current-year
    # and next-year schedules, not a full historical archive. Keep older prices
    # only for rolling baselines, and restrict controls to the official calendar
    # coverage window so event days and control days share the same regime.
    daily = daily.dropna(subset=valid_cols)
    daily = daily.loc[daily.index >= pd.Timestamp(ANALYSIS_START)].copy()
    daily.to_csv(DATA_DIR / "daily_features.csv", index_label="date")
    return daily


def bootstrap_mean_diff(event_values: np.ndarray, control_values: np.ndarray, reps: int = 1000) -> tuple[float, float]:
    rng = np.random.default_rng(SEED)
    diffs = []
    for _ in range(reps):
        e = rng.choice(event_values, size=len(event_values), replace=True)
        c = rng.choice(control_values, size=len(control_values), replace=True)
        diffs.append(float(np.nanmean(e) - np.nanmean(c)))
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return float(lo), float(hi)


def compare_groups(daily: pd.DataFrame, group_col: str, target_col: str) -> dict[str, Any]:
    event = daily.loc[daily[group_col] > 0, target_col].dropna().to_numpy()
    control = daily.loc[(daily[group_col] == 0) & (daily["control_eligible"] > 0), target_col].dropna().to_numpy()
    if len(event) < 5 or len(control) < 20:
        return {
            "target": target_col,
            "group": group_col,
            "n_event": int(len(event)),
            "n_control": int(len(control)),
            "status": "insufficient_sample",
        }
    t_stat, p_value = stats.ttest_ind(event, control, equal_var=False, nan_policy="omit")
    try:
        mw_stat, mw_p = stats.mannwhitneyu(event, control, alternative="two-sided")
    except ValueError:
        mw_stat, mw_p = np.nan, np.nan
    ci_low, ci_high = bootstrap_mean_diff(event, control)
    return {
        "target": target_col,
        "group": group_col,
        "n_event": int(len(event)),
        "n_control": int(len(control)),
        "event_mean": float(np.nanmean(event)),
        "control_mean": float(np.nanmean(control)),
        "diff": float(np.nanmean(event) - np.nanmean(control)),
        "welch_t": float(t_stat),
        "welch_p": float(p_value),
        "mann_whitney_u": float(mw_stat) if math.isfinite(float(mw_stat)) else None,
        "mann_whitney_p": float(mw_p) if math.isfinite(float(mw_p)) else None,
        "bootstrap_ci_95": [ci_low, ci_high],
        "harvey_pass_abs_t_ge_3": bool(abs(float(t_stat)) >= 3.0),
        "bootstrap_ci_excludes_zero": bool(ci_low > 0 or ci_high < 0),
    }


def run_event_tests(daily: pd.DataFrame) -> list[dict[str, Any]]:
    tests = [compare_groups(daily, "macro_release_day", col) for col in EVENT_TEST_COLUMNS]

    surprise_threshold = daily.loc[daily["macro_release_day"] > 0, "macro_abs_surprise_proxy"].replace(0, np.nan).quantile(0.75)
    daily = daily.copy()
    daily["top_actual_surprise_day"] = (
        (daily["macro_release_day"] > 0)
        & (daily["macro_abs_surprise_proxy"] >= surprise_threshold)
        & (daily["macro_abs_surprise_proxy"] > 0)
    ).astype(float)
    for col in EVENT_TEST_COLUMNS:
        tests.append(compare_groups(daily, "top_actual_surprise_day", col))
    return tests


def run_beta_tests(daily: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    base = daily.loc[(daily["macro_release_day"] > 0) | (daily["control_eligible"] > 0)].copy()
    base["spy_x_macro"] = base["spy_ret_z"] * base["macro_release_day"]
    for ticker in COUNTRY_ETFS:
        y_col = f"{ticker}_ret_z"
        df = base[[y_col, "spy_ret_z", "macro_release_day", "spy_x_macro"]].dropna()
        if len(df) < 252:
            rows.append({"ticker": ticker, "status": "insufficient_sample", "n": int(len(df))})
            continue
        x = sm.add_constant(df[["spy_ret_z", "macro_release_day", "spy_x_macro"]])
        model = sm.OLS(df[y_col], x).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
        event_beta = float(model.params["spy_ret_z"] + model.params["spy_x_macro"])
        normal_beta = float(model.params["spy_ret_z"])
        rows.append(
            {
                "ticker": ticker,
                "n": int(len(df)),
                "normal_beta": normal_beta,
                "macro_day_beta": event_beta,
                "beta_interaction": float(model.params["spy_x_macro"]),
                "interaction_t": float(model.tvalues["spy_x_macro"]),
                "interaction_p": float(model.pvalues["spy_x_macro"]),
                "macro_day_alpha": float(model.params["macro_release_day"]),
                "macro_day_alpha_t": float(model.tvalues["macro_release_day"]),
                "harvey_pass_interaction_t_ge_3": bool(model.tvalues["spy_x_macro"] >= 3.0),
            }
        )
    return rows


def run_persistence_tests(daily: pd.DataFrame) -> list[dict[str, Any]]:
    tests = [
        compare_groups(daily, "macro_release_signal", "avg_country_fwd5_rv_z"),
        compare_groups(daily, "macro_abs_surprise_signal", "avg_country_fwd5_rv_z"),
        compare_groups(daily, "macro_market_abs_signal", "avg_country_fwd5_rv_z"),
    ]
    return tests


def make_plot(daily: pd.DataFrame, event_tests: list[dict[str, Any]], beta_tests: list[dict[str, Any]]) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))

    event_summary = pd.DataFrame([x for x in event_tests if x.get("group") == "macro_release_day" and "diff" in x])
    axes[0, 0].bar(event_summary["target"], event_summary["diff"], color="#276FBF")
    axes[0, 0].axhline(0, color="black", linewidth=0.8)
    axes[0, 0].set_title("Release-day event minus control mean")
    axes[0, 0].tick_params(axis="x", rotation=35)

    cojump = daily[["macro_release_day", "global_cojump_count"]].dropna()
    axes[0, 1].hist(
        [
            cojump.loc[cojump["macro_release_day"] == 0, "global_cojump_count"],
            cojump.loc[cojump["macro_release_day"] > 0, "global_cojump_count"],
        ],
        bins=np.arange(-0.5, len(COUNTRY_ETFS) + 1.5, 1),
        label=["control", "release"],
        color=["#9AA0A6", "#D95D39"],
        alpha=0.8,
    )
    axes[0, 1].set_title("Global cojump count distribution")
    axes[0, 1].legend()

    beta = pd.DataFrame(beta_tests)
    axes[1, 0].bar(beta["ticker"], beta["beta_interaction"], color="#2A9D8F")
    axes[1, 0].axhline(0, color="black", linewidth=0.8)
    axes[1, 0].set_title("Macro-day beta amplification vs ordinary days")

    daily[["avg_country_fwd5_rv_z", "macro_release_signal"]].dropna().assign(
        group=lambda x: np.where(x["macro_release_signal"] > 0, "post-release", "control")
    ).boxplot(column="avg_country_fwd5_rv_z", by="group", ax=axes[1, 1])
    axes[1, 1].set_title("Next-5d RV z after lagged release signal")
    axes[1, 1].set_xlabel("")
    fig.suptitle("K1556 U.S. macro releases and global ETF co-jumps", fontsize=14)
    fig.tight_layout()
    fig.savefig(ROOT / "k1556_event_effects.png", dpi=160)
    plt.close(fig)


def determine_verdict(event_tests: list[dict[str, Any]], beta_tests: list[dict[str, Any]], persistence_tests: list[dict[str, Any]]) -> tuple[str, str]:
    event_by_target = {x.get("target"): x for x in event_tests if x.get("group") == "macro_release_day"}
    cojump_pass = bool(event_by_target.get("global_cojump_count", {}).get("harvey_pass_abs_t_ge_3"))
    absret_pass = bool(event_by_target.get("avg_country_abs_ret_z", {}).get("harvey_pass_abs_t_ge_3"))
    vix_pass = bool(event_by_target.get("vix_jump_z", {}).get("harvey_pass_abs_t_ge_3"))
    persistence_pass = any(bool(x.get("harvey_pass_abs_t_ge_3")) and float(x.get("diff", 0.0)) > 0 for x in persistence_tests)
    beta_passes = sum(1 for x in beta_tests if bool(x.get("harvey_pass_interaction_t_ge_3")))
    positive_beta_count = sum(1 for x in beta_tests if float(x.get("beta_interaction", 0.0)) > 0)

    if (cojump_pass or absret_pass) and vix_pass and beta_passes >= 2 and persistence_pass:
        return "PASS", "Event-day cojump, VIX jump, beta amplification, and lagged RV persistence all clear strict gates."
    if (cojump_pass or absret_pass or vix_pass) and positive_beta_count >= 5:
        return "CONDITIONAL_EVENT_DAY_PASS_NO_PERSISTENCE", (
            "Daily ETF data show event-day synchronization, but beta/persistence gates are incomplete."
        )
    if cojump_pass or absret_pass or vix_pass:
        return "WEAK_EVENT_DAY_ONLY", "At least one release-day event statistic clears the strict gate, but the broader mechanism is incomplete."
    return "NULL_PROXY", "Daily ETF and free macro-calendar proxies do not clear strict global cojump gates."


def main() -> None:
    prices = download_prices()
    close = close_panel(prices)
    release_calendar = load_release_calendar()
    surprise_calendar = build_macro_surprise_table(release_calendar)
    release_daily, mapped = map_releases_to_trading_days(surprise_calendar, close.index)
    daily = build_daily_features(close, release_daily)

    event_tests = run_event_tests(daily)
    beta_tests = run_beta_tests(daily)
    persistence_tests = run_persistence_tests(daily)
    make_plot(daily, event_tests, beta_tests)
    verdict, conclusion = determine_verdict(event_tests, beta_tests, persistence_tests)

    results = {
        "experiment_id": EXPERIMENT_ID,
        "seed": SEED,
        "verdict": verdict,
        "conclusion": conclusion,
        "data": {
            "price_start": PRICE_START,
            "price_end": PRICE_END,
            "analysis_start": ANALYSIS_START,
            "tickers": TICKERS,
            "country_etfs": COUNTRY_ETFS,
            "price_rows": int(len(prices)),
            "daily_feature_rows": int(len(daily)),
            "release_calendar_rows": int(len(release_calendar)),
            "mapped_release_rows": int(mapped["mapped_trading_date"].notna().sum()),
            "macro_release_days": int(daily["macro_release_day"].sum()),
            "source_files": {
                "prices": str(DATA_DIR / "prices.csv"),
                "fred_release_calendar": str(DATA_DIR / "fred_release_calendar.csv"),
                "macro_release_surprises": str(DATA_DIR / "macro_release_surprises.csv"),
                "release_events_mapped": str(DATA_DIR / "release_events_mapped.csv"),
                "daily_features": str(DATA_DIR / "daily_features.csv"),
            },
        },
        "methodology": {
            "release_calendar": "FRED release-calendar pages for CPI rid=10, Employment rid=50, GDP rid=53.",
            "surprise_proxy": "FRED actual-minus-trailing-nowcast; not paid consensus and not real-time vintage.",
            "event_day_diagnostics": "Contemporaneous response only, not tradable signal.",
            "lookahead_policy": [
                "Rolling z-score baselines use .shift(1).",
                "macro_release_signal = macro_release_day.shift(1).fillna(0.0)",
                "macro_abs_surprise_signal = macro_abs_surprise_proxy.shift(1).fillna(0.0)",
                "macro_market_abs_signal = macro_market_abs_proxy.shift(1).fillna(0.0)",
            ],
        },
        "event_tests": event_tests,
        "beta_tests": beta_tests,
        "persistence_tests": persistence_tests,
        "gate_summary": {
            "event_day_harvey_passes": [
                x["target"]
                for x in event_tests
                if x.get("group") == "macro_release_day" and bool(x.get("harvey_pass_abs_t_ge_3"))
            ],
            "beta_interaction_passes": [
                x["ticker"] for x in beta_tests if bool(x.get("harvey_pass_interaction_t_ge_3"))
            ],
            "positive_beta_interactions": [
                x["ticker"] for x in beta_tests if float(x.get("beta_interaction", 0.0)) > 0
            ],
            "persistence_harvey_passes": [
                x["group"] for x in persistence_tests if bool(x.get("harvey_pass_abs_t_ge_3")) and float(x.get("diff", 0.0)) > 0
            ],
        },
        "limitations": [
            "Daily ETF close-to-close data cannot reproduce intraday announcement-window identification.",
            "Actual-minus-consensus surprises are unavailable; trailing-nowcast and market-shock proxies are weaker.",
            "FRED macro levels are current-vintage, so the actual-surprise proxy is not a real-time vintage dataset.",
            "Country ETFs are USD-listed and embed U.S. trading-hour/liquidity effects.",
        ],
    }

    out = ROOT / "k1556_results.json"
    out.write_text(json.dumps(_json_safe(results), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(_json_safe({"verdict": verdict, "conclusion": conclusion, "gate_summary": results["gate_summary"]}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
