"""Research: buyback-blackout coverage as a SPY volatility calendar factor.

This is a free-data diagnostic, not a CRSP/Compustat full-S&P study.

Question:
    Do days when a large share of major S&P 500 constituents are plausibly in
    issuer-repurchase blackout windows have systematically higher SPY realized
    volatility?

Design:
    Universe: current S&P 500 top-50 proxy from the same static list used in
              K1510. Weights are current yfinance fast_info market caps.
    Calendar: yfinance earnings dates. A firm is treated as blackout from
              35 calendar days before its earnings announcement through
              2 calendar days after the announcement.
    Target  : SPY close-to-close squared return from yfinance adjusted close.
    Tests   : HAC OLS on same-day, next-day, and next-5-day log variance;
              block bootstrap top-vs-bottom coverage; expanding OOS QLIKE
              baseline vs baseline+blackout_coverage_lag1.

Hard limitations:
    - No actual issuer repurchase execution data.
    - No historical S&P 500 membership or historical market caps.
    - yfinance earnings dates are a free-data calendar proxy.
"""
from __future__ import annotations

import json
import math
import time
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise

warnings.filterwarnings("ignore")

SEED = 42
EXPERIMENT_ID = "research_buyback_blackout_vol"
OUT_DIR = Path(__file__).resolve().parent
DATA_DIR = OUT_DIR / "data"
START = "2020-01-01"
END = "2026-07-05"  # yfinance end is exclusive; current run date 2026-07-04.
EARNINGS_LIMIT = 50
BLACKOUT_PRE_DAYS = 35
BLACKOUT_POST_DAYS = 2
EPS = 1e-10

# Same current large-cap scope as K1510. This keeps the experiment bounded and
# makes the survivorship/current-snapshot limitation explicit.
TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK-B", "TSLA",
    "AVGO", "LLY", "JPM", "V", "WMT", "XOM", "UNH", "MA", "PG", "JNJ",
    "ORCL", "HD", "COST", "ABBV", "BAC", "NFLX", "KO", "CRM", "AMD",
    "CVX", "MRK", "ADBE", "TMO", "ACN", "LIN", "PEP", "MCD", "CSCO",
    "WFC", "ABT", "DHR", "QCOM", "TXN", "DIS", "INTU", "VZ", "AMGN",
    "IBM", "PM", "CMCSA", "NOW", "PFE",
]


def _json_default(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    return str(obj)


def _download_close(tickers: list[str] | str, start: str, end: str) -> pd.DataFrame:
    raw = yf.download(
        tickers,
        start=start,
        end=end,
        auto_adjust=False,
        progress=False,
        threads=True,
    )
    if raw.empty:
        raise RuntimeError(f"yfinance returned empty data for {tickers}")

    if isinstance(raw.columns, pd.MultiIndex):
        field = "Adj Close" if "Adj Close" in raw.columns.get_level_values(0) else "Close"
        close = raw[field].copy()
    else:
        field = "Adj Close" if "Adj Close" in raw.columns else "Close"
        close = raw[[field]].copy()
        close.columns = [tickers if isinstance(tickers, str) else tickers[0]]

    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    close = close.sort_index().dropna(how="all")
    return close


def fetch_market_caps(tickers: list[str]) -> pd.DataFrame:
    rows = []
    t0 = time.time()
    for i, ticker in enumerate(tickers, 1):
        market_cap = np.nan
        error = None
        try:
            info = yf.Ticker(ticker).fast_info
            market_cap = getattr(info, "market_cap", np.nan)
        except Exception as exc:  # fail-loud via returned error table
            error = f"{type(exc).__name__}: {exc}"
        rows.append({
            "ticker": ticker,
            "market_cap": float(market_cap) if pd.notna(market_cap) else np.nan,
            "error": error,
        })
        if i % 10 == 0:
            print(f"[caps] {i}/{len(tickers)} in {time.time() - t0:.1f}s")

    caps = pd.DataFrame(rows)
    valid = caps["market_cap"].notna() & (caps["market_cap"] > 0)
    if int(valid.sum()) < 40:
        missing = caps.loc[~valid, ["ticker", "error"]].to_dict("records")
        raise RuntimeError(f"Too few valid market caps: {int(valid.sum())}; missing={missing}")

    caps["weight_top50"] = 0.0
    caps.loc[valid, "weight_top50"] = (
        caps.loc[valid, "market_cap"] / caps.loc[valid, "market_cap"].sum()
    )
    return caps


def fetch_earnings_dates(tickers: list[str]) -> pd.DataFrame:
    rows = []
    failures = []
    t0 = time.time()
    for i, ticker in enumerate(tickers, 1):
        try:
            ed = yf.Ticker(ticker).get_earnings_dates(limit=EARNINGS_LIMIT)
        except Exception as exc:
            failures.append({"ticker": ticker, "error": f"{type(exc).__name__}: {exc}"})
            ed = None
        if ed is not None and not ed.empty:
            tmp = ed.reset_index()
            tmp["ticker"] = ticker
            rows.append(tmp)
        if i % 10 == 0:
            print(f"[earnings] {i}/{len(tickers)} in {time.time() - t0:.1f}s")

    if not rows:
        raise RuntimeError("No earnings dates returned by yfinance")

    earnings = pd.concat(rows, ignore_index=True)
    earnings.columns = [str(c).strip() for c in earnings.columns]
    if "Earnings Date" not in earnings.columns:
        first_col = earnings.columns[0]
        earnings = earnings.rename(columns={first_col: "Earnings Date"})

    earnings = earnings.rename(columns={
        "Earnings Date": "earnings_datetime",
        "EPS Estimate": "eps_estimate",
        "Reported EPS": "reported_eps",
        "Surprise(%)": "surprise_pct",
    })
    dt = pd.to_datetime(earnings["earnings_datetime"], utc=True, errors="coerce")
    earnings["earnings_date"] = (
        dt.dt.tz_convert("America/New_York")
        .dt.normalize()
        .dt.tz_localize(None)
    )
    earnings = earnings.dropna(subset=["earnings_date"]).copy()
    earnings["earnings_date"] = pd.to_datetime(earnings["earnings_date"]).dt.normalize()
    earnings["is_future_or_unreported"] = earnings.get("reported_eps", pd.Series(index=earnings.index)).isna()
    earnings["fetch_failure_count"] = len(failures)
    return earnings.sort_values(["ticker", "earnings_date"], ignore_index=True)


def build_blackout_coverage(
    trading_days: pd.DatetimeIndex,
    earnings: pd.DataFrame,
    caps: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    weights = caps.set_index("ticker")["weight_top50"].to_dict()
    valid_tickers = [ticker for ticker in TICKERS if weights.get(ticker, 0.0) > 0]
    flags = pd.DataFrame(False, index=trading_days, columns=valid_tickers)

    sample_start = trading_days.min() - pd.Timedelta(days=BLACKOUT_POST_DAYS)
    sample_end = trading_days.max() + pd.Timedelta(days=BLACKOUT_PRE_DAYS)
    in_range = earnings[
        (earnings["earnings_date"] >= sample_start)
        & (earnings["earnings_date"] <= sample_end)
        & (earnings["ticker"].isin(valid_tickers))
    ].copy()

    for row in in_range.itertuples(index=False):
        ticker = getattr(row, "ticker")
        event_date = pd.Timestamp(getattr(row, "earnings_date")).normalize()
        start = event_date - pd.Timedelta(days=BLACKOUT_PRE_DAYS)
        end = event_date + pd.Timedelta(days=BLACKOUT_POST_DAYS)
        mask = (flags.index >= start) & (flags.index <= end)
        flags.loc[mask, ticker] = True

    weight_series = pd.Series(weights).reindex(valid_tickers).fillna(0.0)
    coverage = pd.DataFrame(index=trading_days)
    coverage["blackout_coverage"] = flags.mul(weight_series, axis=1).sum(axis=1)
    coverage["blackout_firm_count"] = flags.sum(axis=1).astype(int)
    coverage["any_blackout"] = coverage["blackout_firm_count"] > 0
    return coverage, in_range


def _third_friday(year: int, month: int) -> pd.Timestamp:
    days = pd.date_range(f"{year:04d}-{month:02d}-01", periods=31, freq="D")
    fridays = days[(days.month == month) & (days.dayofweek == 4)]
    return pd.Timestamp(fridays[2]).normalize()


def build_model_frame(coverage: pd.DataFrame, spy_close: pd.Series, vix_close: pd.Series) -> pd.DataFrame:
    spy_close = spy_close.dropna().sort_index()
    vix_close = vix_close.dropna().sort_index()
    log_ret = np.log(spy_close).diff()
    r2 = log_ret.pow(2)

    df = pd.DataFrame(index=spy_close.index)
    df["spy_close"] = spy_close
    df["spy_log_ret"] = log_ret
    df["spy_r2"] = r2
    df["log_r2"] = np.log(r2 + EPS)
    df["ann_abs_ret_vol"] = log_ret.abs() * math.sqrt(252)
    df["rv5_var_lag1"] = r2.rolling(5).mean().shift(1)
    df["rv21_var_lag1"] = r2.rolling(21).mean().shift(1)
    df["log_rv5_lag1"] = np.log(df["rv5_var_lag1"] + EPS)
    df["log_rv21_lag1"] = np.log(df["rv21_var_lag1"] + EPS)
    df["vix_close"] = vix_close.reindex(df.index).ffill()
    df["log_vix_lag1"] = np.log(df["vix_close"].shift(1) + EPS)
    df["fwd5_var"] = sum(r2.shift(-i) for i in range(1, 6)) / 5.0
    df["log_fwd5_var"] = np.log(df["fwd5_var"] + EPS)

    df = df.join(coverage[["blackout_coverage", "blackout_firm_count"]], how="left")
    df[["blackout_coverage", "blackout_firm_count"]] = (
        df[["blackout_coverage", "blackout_firm_count"]].fillna(0.0)
    )
    df["blackout_coverage_lag1"] = df["blackout_coverage"].shift(1)

    opex = []
    for idx in df.index:
        third = _third_friday(idx.year, idx.month)
        opex.append(abs((idx.normalize() - third).days) <= 2)
    df["opex_window"] = np.array(opex, dtype=float)
    df["dow"] = df.index.dayofweek
    df["month"] = df.index.month
    return df


def _make_design(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = df[columns + ["dow", "month"]].copy()
    out = pd.get_dummies(out, columns=["dow", "month"], drop_first=True, dtype=float)
    out = sm.add_constant(out, has_constant="add")
    return out.astype(float)


def hac_ols(df: pd.DataFrame, y_col: str, x_cols: list[str], hac_lags: int) -> dict:
    use = df[[y_col] + x_cols + ["dow", "month"]].replace([np.inf, -np.inf], np.nan).dropna()
    x = _make_design(use, x_cols)
    y = use[y_col].astype(float)
    model = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": hac_lags})
    focal = x_cols[0]
    coef = float(model.params[focal])
    se = float(model.bse[focal])
    t_stat = float(model.tvalues[focal])
    p_value = float(model.pvalues[focal])
    return {
        "target": y_col,
        "focal": focal,
        "n": int(model.nobs),
        "coef_log_variance_per_1_weight": coef,
        "coef_log_variance_per_10pp": coef * 0.10,
        "se": se,
        "t_stat": t_stat,
        "p_value": p_value,
        "harvey_pass_abs_t_gt_3": bool(abs(t_stat) > 3.0),
        "r2_adj": float(model.rsquared_adj),
        "hac_lags": hac_lags,
    }


def block_bootstrap_top_bottom(df: pd.DataFrame, n_boot: int = 1000, block_len: int = 10) -> dict:
    use = df[["ann_abs_ret_vol", "blackout_coverage"]].dropna().copy()
    q25 = float(use["blackout_coverage"].quantile(0.25))
    q75 = float(use["blackout_coverage"].quantile(0.75))
    use["bucket"] = np.where(
        use["blackout_coverage"] >= q75,
        "high",
        np.where(use["blackout_coverage"] <= q25, "low", "mid"),
    )
    high = use.loc[use["bucket"] == "high", "ann_abs_ret_vol"]
    low = use.loc[use["bucket"] == "low", "ann_abs_ret_vol"]
    observed = float(high.mean() - low.mean())

    rng = np.random.default_rng(SEED)
    labels = use["bucket"].to_numpy()
    values = use["ann_abs_ret_vol"].to_numpy()
    n = len(use)
    diffs = []
    for _ in range(n_boot):
        starts = rng.integers(0, n, size=int(np.ceil(n / block_len)))
        idx = np.concatenate([(np.arange(s, s + block_len) % n) for s in starts])[:n]
        boot_labels = labels[idx]
        boot_values = values[idx]
        high_values = boot_values[boot_labels == "high"]
        low_values = boot_values[boot_labels == "low"]
        if len(high_values) == 0 or len(low_values) == 0:
            continue
        diffs.append(float(high_values.mean() - low_values.mean()))

    ci = np.quantile(diffs, [0.025, 0.975]) if diffs else [np.nan, np.nan]
    return {
        "n": int(n),
        "q25_coverage": q25,
        "q75_coverage": q75,
        "high_n": int((use["bucket"] == "high").sum()),
        "low_n": int((use["bucket"] == "low").sum()),
        "high_mean_ann_abs_vol": float(high.mean()),
        "low_mean_ann_abs_vol": float(low.mean()),
        "diff_high_minus_low_ann_abs_vol": observed,
        "bootstrap_reps": int(len(diffs)),
        "block_len": block_len,
        "ci95": [float(ci[0]), float(ci[1])],
        "ci_excludes_zero": bool(ci[0] > 0 or ci[1] < 0),
    }


def expanding_oos_qlike(df: pd.DataFrame, min_train: int = 504) -> dict:
    base_cols = ["log_rv5_lag1", "log_rv21_lag1", "log_vix_lag1", "opex_window"]
    aug_cols = ["blackout_coverage_lag1"] + base_cols
    use = df[["spy_r2", "log_r2"] + aug_cols + ["dow", "month"]].replace([np.inf, -np.inf], np.nan).dropna()
    design_base = _make_design(use, base_cols)
    design_aug = _make_design(use, aug_cols)
    y = use["log_r2"].astype(float).to_numpy()
    actual = use["spy_r2"].astype(float).to_numpy()

    pred_base = []
    pred_aug = []
    actual_oos = []
    dates = []
    for i in range(min_train, len(use)):
        xb_train = design_base.iloc[:i].to_numpy()
        xa_train = design_aug.iloc[:i].to_numpy()
        y_train = y[:i]
        beta_b = np.linalg.lstsq(xb_train, y_train, rcond=None)[0]
        beta_a = np.linalg.lstsq(xa_train, y_train, rcond=None)[0]
        pb = float(np.exp(design_base.iloc[i].to_numpy() @ beta_b))
        pa = float(np.exp(design_aug.iloc[i].to_numpy() @ beta_a))
        pred_base.append(float(np.clip(pb, EPS, 0.25)))
        pred_aug.append(float(np.clip(pa, EPS, 0.25)))
        actual_oos.append(float(max(actual[i], EPS)))
        dates.append(use.index[i])

    actual_arr = np.asarray(actual_oos)
    base_arr = np.asarray(pred_base)
    aug_arr = np.asarray(pred_aug)
    loss_base = qlike_pointwise(actual_arr, base_arr)
    loss_aug = qlike_pointwise(actual_arr, aug_arr)
    dm_t, dm_p = dm_test(loss_aug, loss_base, h=1)
    q_base = qlike(actual_arr, base_arr)
    q_aug = qlike(actual_arr, aug_arr)
    return {
        "n_oos": int(len(actual_arr)),
        "oos_start": pd.Timestamp(dates[0]).date().isoformat() if dates else None,
        "oos_end": pd.Timestamp(dates[-1]).date().isoformat() if dates else None,
        "min_train": min_train,
        "baseline_qlike": float(q_base),
        "augmented_qlike": float(q_aug),
        "improvement_pct": float((q_base - q_aug) / abs(q_base) * 100.0) if q_base else np.nan,
        "dm_t_aug_minus_base": float(dm_t),
        "dm_p": float(dm_p),
        "harvey_pass_aug_better": bool(dm_t < -3.0),
    }


def make_figure(df: pd.DataFrame, out_path: Path) -> None:
    plot = df.dropna(subset=["blackout_coverage", "spy_r2"]).copy()
    plot["rv21_ann"] = (plot["spy_r2"].rolling(21).mean() * 252).pow(0.5)

    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=False)
    axes[0].plot(plot.index, plot["blackout_coverage"] * 100, color="#1f77b4", lw=1.1)
    axes[0].set_title("Top-50 proxy buyback-blackout coverage")
    axes[0].set_ylabel("Market-cap weight (%)")
    axes[0].grid(alpha=0.25)

    axes[1].plot(plot.index, plot["rv21_ann"] * 100, color="#444444", lw=1.0, label="SPY 21d RV")
    axes[1].plot(
        plot.index,
        plot["blackout_coverage"].rolling(21).mean() * 100,
        color="#d62728",
        lw=1.0,
        label="Coverage 21d avg",
    )
    axes[1].set_title("SPY realized volatility vs blackout coverage")
    axes[1].set_ylabel("Percent")
    axes[1].grid(alpha=0.25)
    axes[1].legend(loc="upper right")

    fig.tight_layout()
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def verdict_from_results(regressions: dict, oos: dict, boot: dict) -> str:
    predictive = regressions["predictive_1d"]
    fwd5 = regressions["forward_5d"]
    if (
        predictive["t_stat"] > 3.0
        and fwd5["t_stat"] > 3.0
        and oos["harvey_pass_aug_better"]
    ):
        return "PASS"
    if (
        predictive["t_stat"] > 0
        and fwd5["t_stat"] > 0
        and oos["improvement_pct"] > 0
        and (boot["ci95"][0] > 0)
    ):
        return "DIRECTIONAL_ONLY"
    return "NULL_OR_PROXY_LIMITED"


def main() -> None:
    np.random.seed(SEED)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[{EXPERIMENT_ID}] fetching SPY/^VIX")
    close = _download_close(["SPY", "^VIX"], START, END)
    spy = close["SPY"].dropna()
    vix = close["^VIX"].dropna()

    print(f"[{EXPERIMENT_ID}] fetching market caps")
    caps = fetch_market_caps(TICKERS)
    caps.to_csv(DATA_DIR / "market_caps_top50_snapshot.csv", index=False)

    print(f"[{EXPERIMENT_ID}] fetching earnings dates")
    earnings = fetch_earnings_dates(TICKERS)
    earnings.to_csv(DATA_DIR / "earnings_dates_yfinance.csv", index=False)

    coverage, earnings_in_range = build_blackout_coverage(spy.index, earnings, caps)
    coverage.to_csv(DATA_DIR / "blackout_coverage_daily.csv", index_label="date")

    frame = build_model_frame(coverage, spy, vix)
    frame.to_csv(DATA_DIR / "model_frame.csv", index_label="date")

    controls = ["log_rv5_lag1", "log_rv21_lag1", "log_vix_lag1", "opex_window"]
    regressions = {
        "same_day": hac_ols(
            frame,
            "log_r2",
            ["blackout_coverage"] + controls,
            hac_lags=5,
        ),
        "predictive_1d": hac_ols(
            frame,
            "log_r2",
            ["blackout_coverage_lag1"] + controls,
            hac_lags=5,
        ),
        "forward_5d": hac_ols(
            frame,
            "log_fwd5_var",
            ["blackout_coverage"] + controls,
            hac_lags=10,
        ),
    }
    boot = block_bootstrap_top_bottom(frame)
    oos = expanding_oos_qlike(frame)

    fig_path = OUT_DIR / "blackout_coverage_vs_spy_rv.png"
    make_figure(frame, fig_path)

    valid_caps = caps[caps["weight_top50"] > 0].copy()
    earnings_tickers = set(earnings_in_range["ticker"].unique())
    earnings_weight = float(
        valid_caps.loc[valid_caps["ticker"].isin(earnings_tickers), "weight_top50"].sum()
    )
    coverage_summary = {
        "start": frame.index.min().date().isoformat(),
        "end": frame.index.max().date().isoformat(),
        "trading_days": int(len(frame)),
        "mean_coverage": float(coverage["blackout_coverage"].mean()),
        "median_coverage": float(coverage["blackout_coverage"].median()),
        "p75_coverage": float(coverage["blackout_coverage"].quantile(0.75)),
        "p90_coverage": float(coverage["blackout_coverage"].quantile(0.90)),
        "max_coverage": float(coverage["blackout_coverage"].max()),
        "mean_firm_count": float(coverage["blackout_firm_count"].mean()),
        "max_firm_count": int(coverage["blackout_firm_count"].max()),
    }

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Buyback-blackout coverage as a SPY volatility calendar factor",
        "run_date": pd.Timestamp.utcnow().isoformat(),
        "seed": SEED,
        "verdict": verdict_from_results(regressions, oos, boot),
        "data": {
            "price_source": "yfinance adjusted close via yf.download(auto_adjust=False), Adj Close field",
            "earnings_source": f"yfinance Ticker.get_earnings_dates(limit={EARNINGS_LIMIT})",
            "universe": "current top-50 large-cap S&P proxy reused from K1510; not historical S&P 500 constituents",
            "period": {"start": START, "end_exclusive": END},
            "blackout_window_calendar_days": {
                "pre_earnings": BLACKOUT_PRE_DAYS,
                "post_earnings": BLACKOUT_POST_DAYS,
            },
            "tickers": TICKERS,
            "n_tickers": len(TICKERS),
            "valid_market_cap_tickers": int((caps["weight_top50"] > 0).sum()),
            "earnings_rows_total": int(len(earnings)),
            "earnings_rows_in_model_range": int(len(earnings_in_range)),
            "earnings_tickers_in_model_range": int(len(earnings_tickers)),
            "top50_weight_with_earnings_in_range": earnings_weight,
            "yfinance_version": getattr(yf, "__version__", "unknown"),
        },
        "coverage_summary": coverage_summary,
        "tests": {
            "hac_regressions": regressions,
            "top_bottom_block_bootstrap": boot,
            "expanding_oos_qlike": oos,
        },
        "interpretation": {
            "primary_gate": (
                "Treat as publishable only if predictive_1d and forward_5d coefficients "
                "are positive with Harvey |t|>3 and OOS QLIKE improves with DM t<-3."
            ),
            "limitations": [
                "Current top-50 survivorship universe, not full historical S&P 500.",
                "Current market-cap weights, not daily historical index weights.",
                "Blackout window is inferred from earnings dates; no actual issuer repurchase suspension or 10b5-1 plan data.",
                "SPY close-to-close r^2 is a daily proxy, not intraday realized variance.",
                "Earnings calendar from yfinance may include revised or future expected dates.",
            ],
        },
        "artifacts": {
            "figure": str(fig_path.relative_to(OUT_DIR)),
            "market_caps": "data/market_caps_top50_snapshot.csv",
            "earnings_dates": "data/earnings_dates_yfinance.csv",
            "coverage": "data/blackout_coverage_daily.csv",
            "model_frame": "data/model_frame.csv",
        },
    }

    out = OUT_DIR / f"{EXPERIMENT_ID}_results.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=True, default=_json_default) + "\n")
    print(json.dumps({
        "verdict": results["verdict"],
        "n_days": coverage_summary["trading_days"],
        "mean_coverage": coverage_summary["mean_coverage"],
        "predictive_1d_t": regressions["predictive_1d"]["t_stat"],
        "forward_5d_t": regressions["forward_5d"]["t_stat"],
        "oos_improvement_pct": oos["improvement_pct"],
        "results": str(out),
    }, indent=2))


if __name__ == "__main__":
    main()
