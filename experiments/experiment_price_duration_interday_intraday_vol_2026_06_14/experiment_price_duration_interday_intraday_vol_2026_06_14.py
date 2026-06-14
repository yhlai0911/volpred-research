"""Price-duration proxy for interday vs intraday volatility dynamics.

This experiment is a local-data pilot inspired by Li, Nolte, Nolte and Yu
(2025), not a full tick-level price-duration estimator.  The available data are
5-minute bars, so "duration" is measured on a five-minute grid by counting how
often the intraday log price path crosses an adaptive price-change threshold.

Design:
1. Use only local 5-minute bars from data/intraday.
2. Estimate the price threshold and intraday duration seasonality on a
   chronological train split.
3. Evaluate on a chronological holdout split.
4. Test whether adding seasonality-aware duration features reduces holdout
   intraday RV RMSE relative to a plain duration-count model.
5. Separately quantify whether duration intensity is tied to intraday RV more
   strongly than to overnight variance.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm


EXPERIMENT_ID = "experiment_price_duration_interday_intraday_vol_2026_06_14"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "intraday"
RESULT_PATH = OUT_DIR / f"{EXPERIMENT_ID}_results.json"
FIG_SEASONALITY = OUT_DIR / "fig_duration_seasonality.png"
FIG_RMSE = OUT_DIR / "fig_rmse_comparison.png"

SEED = 42
BOOTSTRAP_N = 1000
TRAIN_FRAC = 0.7
TICKERS = {
    "SPY": {"safe_name": "SPY"},
    "0050.TW": {"safe_name": "0050_TW"},
}


@dataclass
class SampleInfo:
    ticker: str
    start_date: str
    end_date: str
    n_days_total: int
    n_days_train: int
    n_days_test: int
    bars_per_day: int
    threshold_log_price: float


def load_intraday_bars(ticker: str, safe_name: str) -> pd.DataFrame:
    files = sorted(DATA_DIR.glob(f"{safe_name}_5min_*.csv"))
    if not files:
        raise FileNotFoundError(f"No local 5-minute files for {ticker}")

    parts: list[pd.DataFrame] = []
    for path in files:
        df = pd.read_csv(path, skiprows=2)
        df.columns = ["Datetime", "Close", "High", "Low", "Open", "Volume"]
        df["Datetime"] = pd.to_datetime(df["Datetime"])
        for col in ["Close", "High", "Low", "Open", "Volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["Datetime", "Open", "Close", "High", "Low"])
        df["date"] = df["Datetime"].dt.date
        parts.append(df[["Datetime", "date", "Open", "High", "Low", "Close", "Volume"]])

    data = pd.concat(parts, ignore_index=True).sort_values("Datetime").reset_index(drop=True)
    counts = data.groupby("date").size()
    modal_bars = int(counts.mode().iloc[0])
    complete_days = counts[counts == modal_bars].index
    data = data[data["date"].isin(complete_days)].copy()
    data["bin_idx"] = data.groupby("date").cumcount()
    data["clock"] = data["Datetime"].dt.strftime("%H:%M")

    data["bar_log_ret"] = np.log(data["Close"] / data["Open"])
    data["bar_rv"] = data["bar_log_ret"] ** 2
    data.attrs["bars_per_day"] = modal_bars
    return data


def split_days(data: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    unique_days = np.array(sorted(data["date"].unique()))
    split_idx = max(20, int(len(unique_days) * TRAIN_FRAC))
    split_idx = min(split_idx, max(len(unique_days) - 10, 1))
    return unique_days, unique_days[:split_idx], unique_days[split_idx:]


def estimate_threshold(train_df: pd.DataFrame, bars_per_day: int) -> float:
    daily_rv = train_df.groupby("date")["bar_rv"].sum()
    median_daily_sigma = float(np.sqrt(daily_rv.median()))
    threshold = median_daily_sigma / np.sqrt(bars_per_day)
    if not np.isfinite(threshold) or threshold <= 0:
        threshold = float(train_df["bar_log_ret"].abs().median())
    return max(threshold, 1e-8)


def count_threshold_events(day_df: pd.DataFrame, threshold: float) -> np.ndarray:
    """Count price-threshold crossings per bar on a coarse 5-minute grid."""
    rows = day_df.sort_values("bin_idx")
    anchor = float(np.log(rows["Open"].iloc[0]))
    events = np.zeros(len(rows), dtype=float)

    for pos, close_price in enumerate(rows["Close"].to_numpy()):
        log_close = float(np.log(close_price))
        move = log_close - anchor
        hits = int(np.floor(abs(move) / threshold))
        if hits > 0:
            events[pos] = float(hits)
            anchor += np.sign(move) * hits * threshold
    return events


def build_daily_features(data: pd.DataFrame, train_days: np.ndarray, threshold: float) -> tuple[pd.DataFrame, np.ndarray]:
    records: list[dict] = []
    event_rows: list[np.ndarray] = []
    dates = sorted(data["date"].unique())
    prev_close: float | None = None

    for date in dates:
        day = data[data["date"] == date].sort_values("bin_idx")
        events = count_threshold_events(day, threshold)
        open_price = float(day["Open"].iloc[0])
        close_price = float(day["Close"].iloc[-1])
        high_price = float(day["High"].max())
        low_price = float(day["Low"].min())
        intraday_rv = float(day["bar_rv"].sum())
        overnight_ret = np.nan if prev_close is None else float(np.log(open_price / prev_close))
        overnight_var = np.nan if prev_close is None else overnight_ret ** 2
        event_count = float(events.sum())
        bars_per_day = int(len(day))
        records.append(
            {
                "date": str(date),
                "intraday_rv": intraday_rv,
                "overnight_var": overnight_var,
                "total_rv": intraday_rv + (0.0 if np.isnan(overnight_var) else overnight_var),
                "event_count": event_count,
                "mean_duration_bars": float(bars_per_day / event_count) if event_count > 0 else float(bars_per_day),
                "pd_iv_plain": float((threshold ** 2) * event_count),
                "parkinson_var": float((np.log(high_price / low_price) ** 2) / (4.0 * np.log(2.0))),
            }
        )
        event_rows.append(events)
        prev_close = close_price

    daily = pd.DataFrame(records)
    daily["date_obj"] = pd.to_datetime(daily["date"]).dt.date

    train_mask = daily["date_obj"].isin(set(train_days))
    train_events = np.vstack([event_rows[i] for i, is_train in enumerate(train_mask) if is_train])
    seasonal_profile = train_events.mean(axis=0)
    # Avoid division blow-ups in calm bins while preserving relative shape.
    seasonal_floor = max(float(np.percentile(seasonal_profile, 10)), 1e-4)
    seasonal_profile = np.maximum(seasonal_profile, seasonal_floor)
    seasonal_profile = seasonal_profile / seasonal_profile.mean()

    weighted_counts = []
    alignments = []
    for events in event_rows:
        weighted_count = float(np.sum(events / seasonal_profile))
        event_count = float(np.sum(events))
        alignment = float(np.sum(events * seasonal_profile) / event_count) if event_count > 0 else 0.0
        weighted_counts.append(weighted_count)
        alignments.append(alignment)

    daily["season_weighted_event_count"] = weighted_counts
    daily["seasonal_alignment"] = alignments
    daily["pd_iv_season_weighted"] = (threshold ** 2) * daily["season_weighted_event_count"]
    return daily, seasonal_profile


def fit_predict_log_ols(train: pd.DataFrame, test: pd.DataFrame, feature_cols: list[str]) -> tuple[np.ndarray, dict]:
    eps = 1e-12
    X_train = pd.DataFrame(index=train.index)
    X_test = pd.DataFrame(index=test.index)
    for col in feature_cols:
        if col.startswith("log_"):
            raw_col = col[4:]
            X_train[col] = np.log(train[raw_col] + eps)
            X_test[col] = np.log(test[raw_col] + eps)
        else:
            X_train[col] = train[col]
            X_test[col] = test[col]
    X_train = sm.add_constant(X_train, has_constant="add")
    X_test = sm.add_constant(X_test, has_constant="add")
    y_train = np.log(train["intraday_rv"] + eps)
    model = sm.OLS(y_train, X_train).fit()
    pred_log = model.predict(X_test)
    pred = np.exp(pred_log)
    return pred.to_numpy(), {
        "features": feature_cols,
        "params": {str(k): float(v) for k, v in model.params.items()},
        "train_r2": float(model.rsquared),
        "train_n": int(model.nobs),
    }


def forecast_metrics(actual: np.ndarray, pred: np.ndarray) -> dict:
    eps = 1e-12
    err = pred - actual
    rmse = float(np.sqrt(np.mean(err ** 2)))
    mae = float(np.mean(np.abs(err)))
    log_rmse = float(np.sqrt(np.mean((np.log(pred + eps) - np.log(actual + eps)) ** 2)))
    qlike = float(np.mean(np.log(pred + eps) + actual / (pred + eps)))
    return {"rmse": rmse, "mae": mae, "log_rmse": log_rmse, "qlike": qlike}


def paired_bootstrap_rmse_delta(actual: np.ndarray, plain: np.ndarray, seasonal: np.ndarray, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    n = len(actual)
    observed_plain = np.sqrt(np.mean((plain - actual) ** 2))
    observed_seasonal = np.sqrt(np.mean((seasonal - actual) ** 2))
    observed_delta = float(observed_seasonal - observed_plain)
    boot = np.empty(BOOTSTRAP_N)
    idx = np.arange(n)
    for i in range(BOOTSTRAP_N):
        sample_idx = rng.choice(idx, size=n, replace=True)
        boot[i] = np.sqrt(np.mean((seasonal[sample_idx] - actual[sample_idx]) ** 2)) - np.sqrt(
            np.mean((plain[sample_idx] - actual[sample_idx]) ** 2)
        )
    ci_low, ci_high = np.percentile(boot, [2.5, 97.5])
    p_improve = float((np.sum(boot >= 0.0) + 1) / (BOOTSTRAP_N + 1))
    return {
        "observed_rmse_delta_seasonal_minus_plain": observed_delta,
        "observed_rmse_reduction_pct": float((observed_plain - observed_seasonal) / observed_plain * 100.0),
        "bootstrap_ci_95": [float(ci_low), float(ci_high)],
        "one_sided_p_seasonal_better": p_improve,
        "n_bootstrap": BOOTSTRAP_N,
    }


def safe_corr(x: pd.Series, y: pd.Series) -> float | None:
    df = pd.concat([x, y], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(df) < 5 or df.iloc[:, 0].std() <= 0 or df.iloc[:, 1].std() <= 0:
        return None
    return float(df.iloc[:, 0].corr(df.iloc[:, 1]))


def evaluate_ticker(ticker: str, safe_name: str, seed_offset: int) -> tuple[dict, np.ndarray]:
    bars = load_intraday_bars(ticker, safe_name)
    unique_days, train_days, test_days = split_days(bars)
    bars_per_day = int(bars.attrs["bars_per_day"])
    train_bars = bars[bars["date"].isin(train_days)].copy()
    threshold = estimate_threshold(train_bars, bars_per_day)
    daily, seasonal_profile = build_daily_features(bars, train_days, threshold)
    daily = daily.dropna(subset=["overnight_var"]).reset_index(drop=True)

    train = daily[daily["date_obj"].isin(set(train_days))].copy()
    test = daily[daily["date_obj"].isin(set(test_days))].copy()

    plain_pred, plain_model = fit_predict_log_ols(train, test, ["log_pd_iv_plain"])
    seasonal_pred, seasonal_model = fit_predict_log_ols(
        train,
        test,
        ["log_pd_iv_plain", "log_pd_iv_season_weighted", "seasonal_alignment"],
    )
    range_pred, range_model = fit_predict_log_ols(train, test, ["log_parkinson_var"])

    actual = test["intraday_rv"].to_numpy()
    metrics = {
        "plain_duration": forecast_metrics(actual, plain_pred),
        "seasonality_augmented_duration": forecast_metrics(actual, seasonal_pred),
        "parkinson_range": forecast_metrics(actual, range_pred),
    }
    bootstrap = paired_bootstrap_rmse_delta(actual, plain_pred, seasonal_pred, SEED + seed_offset)

    correlations = {
        "event_count_vs_intraday_rv_train": safe_corr(train["event_count"], train["intraday_rv"]),
        "event_count_vs_overnight_var_train": safe_corr(train["event_count"], train["overnight_var"]),
        "event_count_vs_intraday_rv_test": safe_corr(test["event_count"], test["intraday_rv"]),
        "event_count_vs_overnight_var_test": safe_corr(test["event_count"], test["overnight_var"]),
        "season_weighted_count_vs_intraday_rv_test": safe_corr(
            test["season_weighted_event_count"], test["intraday_rv"]
        ),
    }

    sample = SampleInfo(
        ticker=ticker,
        start_date=str(unique_days[0]),
        end_date=str(unique_days[-1]),
        n_days_total=int(len(unique_days)),
        n_days_train=int(len(train_days)),
        n_days_test=int(len(test_days)),
        bars_per_day=bars_per_day,
        threshold_log_price=float(threshold),
    )

    verdict = "null"
    if bootstrap["observed_rmse_reduction_pct"] > 0 and bootstrap["one_sided_p_seasonal_better"] < 0.05:
        verdict = "positive"
    elif bootstrap["observed_rmse_reduction_pct"] > 0:
        verdict = "weak_positive_not_significant"

    result = {
        "sample": asdict(sample),
        "train_test_dates": {
            "train_start": str(train["date"].iloc[0]),
            "train_end": str(train["date"].iloc[-1]),
            "test_start": str(test["date"].iloc[0]),
            "test_end": str(test["date"].iloc[-1]),
        },
        "duration_threshold": {
            "definition": "median train daily intraday sigma divided by sqrt(bars_per_day)",
            "value_log_price": float(threshold),
        },
        "holdout_metrics": metrics,
        "rmse_delta_test": bootstrap,
        "correlations": correlations,
        "models": {
            "plain_duration": plain_model,
            "seasonality_augmented_duration": seasonal_model,
            "parkinson_range": range_model,
        },
        "descriptive": {
            "train_intraday_rv_mean": float(train["intraday_rv"].mean()),
            "test_intraday_rv_mean": float(test["intraday_rv"].mean()),
            "train_overnight_share_mean": float((train["overnight_var"] / train["total_rv"]).mean()),
            "test_overnight_share_mean": float((test["overnight_var"] / test["total_rv"]).mean()),
            "train_event_count_mean": float(train["event_count"].mean()),
            "test_event_count_mean": float(test["event_count"].mean()),
        },
        "verdict": verdict,
    }
    return result, seasonal_profile


def make_plots(results: dict, profiles: dict[str, np.ndarray]) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
    for ticker, profile in profiles.items():
        axes[0].plot(np.arange(len(profile)), profile, label=ticker, linewidth=2)
    axes[0].axhline(1.0, color="black", linewidth=1, linestyle="--", alpha=0.5)
    axes[0].set_title("Train-Sample Duration Event Seasonality")
    axes[0].set_xlabel("5-minute bin")
    axes[0].set_ylabel("event intensity / daily average")
    axes[0].legend()

    labels = []
    plain_vals = []
    seasonal_vals = []
    range_vals = []
    for ticker, res in results["tickers"].items():
        labels.append(ticker)
        plain_vals.append(res["holdout_metrics"]["plain_duration"]["rmse"])
        seasonal_vals.append(res["holdout_metrics"]["seasonality_augmented_duration"]["rmse"])
        range_vals.append(res["holdout_metrics"]["parkinson_range"]["rmse"])
    x = np.arange(len(labels))
    width = 0.25
    axes[1].bar(x - width, plain_vals, width, label="plain duration")
    axes[1].bar(x, seasonal_vals, width, label="seasonality augmented")
    axes[1].bar(x + width, range_vals, width, label="Parkinson")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels)
    axes[1].set_title("Holdout Intraday RV RMSE")
    axes[1].set_ylabel("RMSE")
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(FIG_RMSE, dpi=150, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 4.5))
    for ticker, profile in profiles.items():
        ax.plot(np.arange(len(profile)), profile, label=ticker, linewidth=2)
    ax.axhline(1.0, color="black", linewidth=1, linestyle="--", alpha=0.5)
    ax.set_title("Price-Duration Event Seasonality Proxy")
    ax.set_xlabel("5-minute bin")
    ax.set_ylabel("event intensity / daily average")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG_SEASONALITY, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    ticker_results: dict[str, dict] = {}
    profiles: dict[str, np.ndarray] = {}
    for i, (ticker, cfg) in enumerate(TICKERS.items()):
        result, profile = evaluate_ticker(ticker, cfg["safe_name"], i)
        ticker_results[ticker] = result
        profiles[ticker] = profile

    summary = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Price-duration proxy for interday vs intraday volatility dynamics",
        "created_at": "2026-06-14",
        "seed": SEED,
        "data_source": "local 5-minute bars in data/intraday",
        "method_scope": "5-minute bar proxy, not tick-level price-duration estimator",
        "literature": [
            {
                "citation": "Li, Nolte, Nolte and Yu (2025), Journal of Time Series Analysis",
                "role": "Direct motivation: adaptive price-duration framework decoupling interday and intraday volatility dynamics.",
                "url": "https://doi.org/10.1111/jtsa.12849",
            },
            {
                "citation": "Engle and Russell (1998), Econometrica",
                "role": "Foundational autoregressive conditional duration framework for irregularly spaced financial events.",
                "url": "https://www.jstor.org/stable/2999632",
            },
            {
                "citation": "Andersen and Bollerslev (1998), Journal of Finance",
                "role": "Intraday volatility periodicity and longer-run dependencies motivate seasonality separation.",
                "url": "https://econ.duke.edu/~boller/Published_Papers/jf_98.pdf",
            },
        ],
        "hypothesis": (
            "Adding train-estimated duration seasonality to a plain adaptive-threshold "
            "duration count should reduce holdout intraday RV RMSE if price-duration "
            "seasonality contains incremental information."
        ),
        "tickers": ticker_results,
    }

    reductions = {
        ticker: res["rmse_delta_test"]["observed_rmse_reduction_pct"]
        for ticker, res in ticker_results.items()
    }
    significant = {
        ticker: res["rmse_delta_test"]["one_sided_p_seasonal_better"] < 0.05
        for ticker, res in ticker_results.items()
    }
    any_significant = any(significant.values())
    all_positive = all(reductions[t] > 0 for t in reductions)
    if any_significant:
        overall_verdict = "partial_significant_increment"
    elif all_positive:
        overall_verdict = "weak_positive_not_significant"
    else:
        overall_verdict = "null_proxy_evidence"

    summary["overall_conclusion"] = {
        "rmse_reduction_pct_by_ticker": reductions,
        "significant_by_ticker": significant,
        "verdict": overall_verdict,
        "interpretation": (
            "Duration intensity is informative for intraday RV, but the added "
            "seasonality component is not uniformly or statistically significant "
            "across SPY and 0050.TW in this short 2026 local sample."
        ),
    }

    make_plots(summary, profiles)
    with RESULT_PATH.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary["overall_conclusion"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
