"""Intraday seasonal component vs plain HAR-RV pilot.

Task: research_intraday_garch_vs_har_rv_rv

Question
--------
Does a simple past-only intraday multiplicative-shape proxy add next-day SPY
realized-variance forecasting value beyond daily HAR-RV?

This is a pilot because the free/local 5-minute SPY cache has far fewer than
252 OOS days. It must not be cited as paper-grade evidence.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


EXPERIMENT_ID = "research_intraday_garch_vs_har_rv_rv"
ROOT = Path(__file__).resolve().parents[2]
EXP_DIR = ROOT / "experiments" / EXPERIMENT_ID
DATA_DIR = ROOT / "data" / "intraday"
FIG_DIR = EXP_DIR / "figures"
RESULTS_PATH = EXP_DIR / f"{EXPERIMENT_ID}_results.json"
TICKER = "SPY"
SEED = 1534
MIN_INITIAL_TRAIN = 45
HARVEY_THRESHOLD = 3.0


def _safe_float(value: float | np.floating | None) -> float | None:
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _date_from_path(path: Path) -> str:
    match = re.search(r"SPY_5min_(\d{4}-\d{2}-\d{2})\.csv$", path.name)
    if not match:
        raise ValueError(f"unrecognized SPY 5-minute filename: {path}")
    return match.group(1)


def load_local_spy_5m() -> pd.DataFrame:
    """Load local yfinance 5-minute SPY daily files.

    Files are created by scripts/collect_5min_data.py and have yfinance's
    multi-row CSV header. We intentionally use local snapshots only so the
    experiment is reproducible and does not drift with live API availability.
    """
    frames: list[pd.DataFrame] = []
    for path in sorted(DATA_DIR.glob("SPY_5min_*.csv")):
        date = _date_from_path(path)
        try:
            raw = pd.read_csv(path, skiprows=[1, 2])
        except Exception as exc:  # fail-open with diagnostics; one bad day should not kill the pilot
            print(f"[{EXPERIMENT_ID}] WARN read failed path={path} error={type(exc).__name__}: {exc}")
            continue
        required = {"Price", "Close", "Open", "High", "Low", "Volume"}
        if not required.issubset(raw.columns):
            print(f"[{EXPERIMENT_ID}] WARN schema invalid path={path} columns={list(raw.columns)}")
            continue
        raw = raw.rename(columns={"Price": "datetime"})
        raw["datetime"] = pd.to_datetime(raw["datetime"], utc=True, errors="coerce")
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            raw[col] = pd.to_numeric(raw[col], errors="coerce")
        raw["date"] = pd.to_datetime(date).date()
        raw = raw.dropna(subset=["datetime", "Open", "High", "Low", "Close"])
        if len(raw) < 40:
            print(f"[{EXPERIMENT_ID}] WARN too few bars path={path} n={len(raw)}")
            continue
        frames.append(raw[["datetime", "date", "Open", "High", "Low", "Close", "Volume"]])

    if not frames:
        raise RuntimeError(f"no usable SPY 5-minute files found in {DATA_DIR}")

    data = pd.concat(frames, ignore_index=True).sort_values(["datetime"])
    data = data.drop_duplicates(subset=["datetime"], keep="last")
    return data


def build_daily_measures(bars: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily_rows: list[dict] = []
    slot_rows: list[dict] = []

    for date, group in bars.groupby("date", sort=True):
        g = group.sort_values("datetime").reset_index(drop=True)
        log_close = np.log(g["Close"].to_numpy(dtype=float))
        ret = np.diff(log_close)
        if len(ret) < 30:
            continue

        sq = ret ** 2
        rv = float(np.sum(sq))
        if not math.isfinite(rv) or rv <= 0:
            continue

        share = sq / rv
        n = len(sq)
        first6 = float(np.sum(share[: min(6, n)]))
        last6 = float(np.sum(share[max(0, n - 6):]))
        first_half = float(np.sum(share[: n // 2]))
        concentration = float(np.sum(share ** 2))
        max_slot_share = float(np.max(share))

        daily_rows.append({
            "date": pd.Timestamp(date),
            "rv": rv,
            "log_rv": math.log(rv),
            "n_bars": int(len(g)),
            "n_returns": int(n),
            "first6_share": first6,
            "last6_share": last6,
            "open_close_share": first6 + last6,
            "first_half_share": first_half,
            "seasonal_concentration": concentration,
            "max_slot_share": max_slot_share,
        })

        for idx, value in enumerate(sq):
            slot_rows.append({"date": pd.Timestamp(date), "slot": idx + 1, "sq_return": float(value), "rv_share": float(share[idx])})

    daily = pd.DataFrame(daily_rows).sort_values("date").set_index("date")
    slots = pd.DataFrame(slot_rows)
    if len(daily) < 70:
        raise RuntimeError(f"insufficient usable daily RV rows: {len(daily)}")
    return daily, slots


def make_features(daily: pd.DataFrame) -> pd.DataFrame:
    df = daily.copy()
    # Information set: features observed at day t, target is RV at day t+1.
    df["har_lag1"] = df["log_rv"]
    df["har_week"] = df["log_rv"].rolling(5, min_periods=5).mean()
    df["har_month"] = df["log_rv"].rolling(22, min_periods=22).mean()
    df["target_log_rv_next"] = df["log_rv"].shift(-1)
    df["target_rv_next"] = df["rv"].shift(-1)
    df["target_date_next"] = df.index.to_series().shift(-1)
    return df.dropna()


def _fit_predict(train: pd.DataFrame, test_row: pd.Series, features: list[str]) -> float:
    x_train = train[features].to_numpy(dtype=float)
    y_train = train["target_log_rv_next"].to_numpy(dtype=float)
    x_train = np.column_stack([np.ones(len(x_train)), x_train])
    beta, *_ = np.linalg.lstsq(x_train, y_train, rcond=None)
    x_test = np.array([1.0] + [float(test_row[f]) for f in features])
    pred_log = float(x_test @ beta)
    return float(np.exp(np.clip(pred_log, -30, 5)))


def expanding_oos(features_df: pd.DataFrame) -> pd.DataFrame:
    baseline_features = ["har_lag1", "har_week", "har_month"]
    augmented_features = baseline_features + [
        "open_close_share",
        "first_half_share",
        "seasonal_concentration",
        "max_slot_share",
    ]
    initial_train = min(MIN_INITIAL_TRAIN, max(30, len(features_df) // 2))
    rows: list[dict] = []
    for i in range(initial_train, len(features_df)):
        train = features_df.iloc[:i]
        test = features_df.iloc[i]
        rows.append({
            "feature_date": features_df.index[i].strftime("%Y-%m-%d"),
            "target_date": pd.Timestamp(test["target_date_next"]).strftime("%Y-%m-%d"),
            "actual_rv": float(test["target_rv_next"]),
            "har_pred": _fit_predict(train, test, baseline_features),
            "seasonal_pred": _fit_predict(train, test, augmented_features),
        })
    return pd.DataFrame(rows)


def evaluate_forecasts(oos: pd.DataFrame) -> dict:
    actual = oos["actual_rv"].to_numpy(dtype=float)
    har_pred = oos["har_pred"].to_numpy(dtype=float)
    seasonal_pred = oos["seasonal_pred"].to_numpy(dtype=float)
    har_losses = qlike_pointwise(actual, har_pred)
    seasonal_losses = qlike_pointwise(actual, seasonal_pred)
    dm_t, dm_p = dm_test(seasonal_losses, har_losses, h=1)
    har_qlike = qlike(actual, har_pred)
    seasonal_qlike = qlike(actual, seasonal_pred)
    improvement = (har_qlike - seasonal_qlike) / har_qlike if har_qlike and math.isfinite(har_qlike) else np.nan
    return {
        "har_qlike": _safe_float(har_qlike),
        "seasonal_qlike": _safe_float(seasonal_qlike),
        "seasonal_vs_har_qlike_improvement_pct": _safe_float(improvement * 100),
        "dm_t_seasonal_minus_har": _safe_float(dm_t),
        "dm_p": _safe_float(dm_p),
        "harvey_abs_t_gt_3": bool(abs(dm_t) > HARVEY_THRESHOLD),
    }


def make_figures(daily: pd.DataFrame, slots: pd.DataFrame, oos: pd.DataFrame) -> list[str]:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []

    fig, ax = plt.subplots(figsize=(10, 4))
    annualized_rv = np.sqrt(daily["rv"] * 252) * 100
    ax.plot(daily.index, annualized_rv, color="#2f5d62", linewidth=1.5)
    ax.set_title("SPY 5-minute realized volatility snapshot")
    ax.set_ylabel("Annualized RV (%)")
    ax.grid(alpha=0.25)
    fig.autofmt_xdate()
    path = FIG_DIR / "fig_daily_rv_snapshot.png"
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(ROOT)))

    profile = slots.groupby("slot")["rv_share"].mean()
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(profile.index, profile.values * 100, color="#7c3f58", linewidth=1.6)
    ax.set_title("Average intraday RV share by 5-minute slot")
    ax.set_xlabel("5-minute return slot")
    ax.set_ylabel("Share of daily RV (%)")
    ax.grid(alpha=0.25)
    path = FIG_DIR / "fig_intraday_seasonal_profile.png"
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(ROOT)))

    fig, ax = plt.subplots(figsize=(8, 4))
    idx = np.arange(len(oos))
    ax.plot(idx, np.sqrt(oos["actual_rv"] * 252) * 100, label="actual", color="#222222", linewidth=1.2)
    ax.plot(idx, np.sqrt(oos["har_pred"] * 252) * 100, label="HAR", color="#2d6cdf", linewidth=1.2)
    ax.plot(idx, np.sqrt(oos["seasonal_pred"] * 252) * 100, label="HAR + intraday shape", color="#c26d2d", linewidth=1.2)
    ax.set_title("OOS next-day RV forecasts (pilot window)")
    ax.set_ylabel("Annualized RV (%)")
    ax.set_xlabel("OOS forecast index")
    ax.legend(frameon=False)
    ax.grid(alpha=0.25)
    path = FIG_DIR / "fig_oos_forecasts.png"
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(ROOT)))

    return paths


def run() -> dict:
    np.random.seed(SEED)
    bars = load_local_spy_5m()
    daily, slots = build_daily_measures(bars)
    features_df = make_features(daily)
    oos = expanding_oos(features_df)
    metrics = evaluate_forecasts(oos)
    figures = make_figures(daily, slots, oos)

    verdict = "PILOT_ONLY_INSUFFICIENT_OOS"
    if len(oos) >= 252 and metrics["harvey_abs_t_gt_3"]:
        verdict = "CONDITIONAL_PASS"
    elif len(oos) >= 252:
        verdict = "NULL_NO_HARVEY_PASS"

    oos_path = EXP_DIR / f"{EXPERIMENT_ID}_oos_forecasts.csv"
    daily_path = EXP_DIR / f"{EXPERIMENT_ID}_daily_measures.csv"
    oos.to_csv(oos_path, index=False)
    daily.to_csv(daily_path)

    result = {
        "experiment_id": EXPERIMENT_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "claim_strength": "pilot only; not paper-grade due to <252 OOS forecasts",
        "data": {
            "source": "local yfinance 5-minute snapshots from data/intraday/SPY_5min_YYYY-MM-DD.csv",
            "ticker": TICKER,
            "start_date": daily.index.min().strftime("%Y-%m-%d"),
            "end_date": daily.index.max().strftime("%Y-%m-%d"),
            "n_intraday_bars": int(len(bars)),
            "n_daily_rv": int(len(daily)),
            "median_bars_per_day": _safe_float(daily["n_bars"].median()),
            "n_feature_rows": int(len(features_df)),
            "n_oos_forecasts": int(len(oos)),
        },
        "information_set": {
            "features": "day-t HAR and intraday shape measures observed after close",
            "target": "day-t+1 5-minute realized variance",
            "lookahead_guard": "target_rv_next = rv.shift(-1); all predictors are day-t or rolling windows ending at day t",
        },
        "diagnostics": {
            "annualized_rv_mean_pct": _safe_float(np.sqrt(daily["rv"].mean() * 252) * 100),
            "annualized_rv_median_pct": _safe_float(np.sqrt(daily["rv"].median() * 252) * 100),
            "open_close_share_mean_pct": _safe_float(daily["open_close_share"].mean() * 100),
            "seasonal_concentration_mean": _safe_float(daily["seasonal_concentration"].mean()),
            "top_intraday_slot_by_mean_share": int(slots.groupby("slot")["rv_share"].mean().idxmax()),
        },
        "model_comparison": metrics,
        "statistical_standard": {
            "loss": "Patton QLIKE on next-day realized variance",
            "dm": "volpred.stats.model_evaluation.dm_test, h=1",
            "harvey_threshold_abs_t": HARVEY_THRESHOLD,
            "oos_minimum_for_paper_grade": 252,
        },
        "literature": [
            {
                "citation": "Corsi (2009), Journal of Financial Econometrics",
                "role": "HAR-RV baseline: heterogeneous daily/weekly/monthly realized-volatility components",
                "url": "https://academic.oup.com/jfec/article-abstract/7/2/174/856522",
            },
            {
                "citation": "Andersen and Bollerslev (1997), Journal of Empirical Finance",
                "role": "intraday periodicity and volatility persistence motivation",
                "url": "https://ideas.repec.org/a/eee/empfin/v4y1997i2-3p115-158.html",
            },
            {
                "citation": "Engle and Sokalska (2012), Journal of Financial Econometrics",
                "role": "multiplicative daily x diurnal x stochastic intraday volatility decomposition",
                "url": "https://academic.oup.com/jfec/article-abstract/10/1/54/755620",
            },
        ],
        "limitations": [
            "Local yfinance 5-minute cache covers only a short 2026 window; OOS forecasts are far below 252.",
            "This is a linear OLS proxy for a multiplicative component model, not a full intraday GARCH MLE.",
            "SPY ETF 5-minute bars only; no cross-asset or true trade/quote microstructure cleaning.",
            "Forecast target is intraday realized variance, not total close-to-close variance including overnight.",
        ],
        "artifacts": {
            "daily_measures_csv": str(daily_path.relative_to(ROOT)),
            "oos_forecasts_csv": str(oos_path.relative_to(ROOT)),
            "figures": figures,
            "codex_review": f"experiments/{EXPERIMENT_ID}/codex_review.md",
            "results_json": str(RESULTS_PATH.relative_to(ROOT)),
        },
    }

    RESULTS_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    summary = run()
    print(json.dumps({
        "experiment_id": summary["experiment_id"],
        "verdict": summary["verdict"],
        "n_daily_rv": summary["data"]["n_daily_rv"],
        "n_oos_forecasts": summary["data"]["n_oos_forecasts"],
        "model_comparison": summary["model_comparison"],
    }, ensure_ascii=False, indent=2))
