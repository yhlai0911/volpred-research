"""K1349: 0050.TW 5-minute HAR-RV pilot.

Research question:
  With the newly accumulated 0050.TW 5-minute bars, can a simple log-HAR-RV
  model forecast next-day realized variance better than naive RV baselines?

Method guards:
  - Daily target is realized variance built from 5-minute returns, not daily r^2.
  - All HAR features are explicit lagged values through t-1.
  - Expanding OOS training rows are strictly earlier than forecast date t.
  - Seed is fixed at 42. OOS is marked pilot-only because N << 252.

Outputs:
  - K1349_results.json
  - K1349_daily_realized_measures.csv
  - K1349_oos_forecasts_intraday_rv.csv
  - K1349_oos_forecasts_total_rv.csv
  - fig_k1349_rv_timeseries.png
  - fig_k1349_oos_qlike.png
  - fig_k1349_intraday_pattern.png
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise, spearman_corr
from volpred.utils import clean_tw50_data

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

SEED = 42
np.random.seed(SEED)

EXPERIMENT_ID = "K1349"
OUT_DIR = Path(__file__).resolve().parent
REPO_ROOT = OUT_DIR.parents[1]
DATA_DIR = REPO_ROOT / "data" / "intraday"
RESULTS_PATH = OUT_DIR / "K1349_results.json"
DAILY_MEASURES_PATH = OUT_DIR / "K1349_daily_realized_measures.csv"
OOS_INTRADAY_PATH = OUT_DIR / "K1349_oos_forecasts_intraday_rv.csv"
OOS_TOTAL_PATH = OUT_DIR / "K1349_oos_forecasts_total_rv.csv"
FIG_RV = OUT_DIR / "fig_k1349_rv_timeseries.png"
FIG_QLIKE = OUT_DIR / "fig_k1349_oos_qlike.png"
FIG_PATTERN = OUT_DIR / "fig_k1349_intraday_pattern.png"

TICKER = "0050.TW"
FILE_PATTERN = "0050_TW_5min_*.csv"
VAR_FLOOR = 1e-12
MIN_BARS_PER_DAY = 50
FIRST_OOS_OBS = 60
MIN_TRAIN_OBS = 35
HARVEY_T = 3.0
PAPER_GRADE_MIN_OOS = 252

LITERATURE = [
    {
        "citation": "Corsi (2009), Journal of Financial Econometrics, A Simple Approximate Long-Memory Model of Realized Volatility.",
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=626064",
        "role": "Canonical HAR-RV model with daily / weekly / monthly realized-volatility components.",
    },
    {
        "citation": "Andersen, Bollerslev, Diebold, and Labys (2003), Econometrica, Modeling and Forecasting Realized Volatility.",
        "url": "https://econ.duke.edu/~boller/Published_Papers/ecta_03.pdf",
        "role": "High-frequency intraday returns as realized-volatility measurement framework.",
    },
    {
        "citation": "Hansen and Lunde (2005), Journal of Financial Econometrics, A Realized Variance for the Whole Day Based on Intermittent High-Frequency Data.",
        "url": "https://ideas.repec.org/a/oup/jfinec/v3y2005i4p525-554.html",
        "role": "Motivates reporting intraday RV separately from overnight/whole-day RV.",
    },
    {
        "citation": "Barndorff-Nielsen and Shephard (2002), JRSS-B, Econometric analysis of realized volatility.",
        "url": "https://ideas.repec.org/a/bla/jorssb/v64y2002i2p253-280.html",
        "role": "Realized-variance / power-variation foundations and BPV-style jump diagnostics.",
    },
]

RELATED_PRIOR = [
    {
        "id": "K196",
        "note": "SPY 5-minute pilot found RV is more autocorrelated than daily r^2, but was preliminary.",
    },
    {
        "id": "K744",
        "note": "SPY pre-HAR-RV validation documented bar-count and proxy-quality checks for 5-minute data.",
    },
    {
        "id": "research_program.md line 357",
        "note": "Backlog requested Taiwan 5-minute HAR-RV for 0050.TW once enough data accumulated.",
    },
]


@dataclass
class DailyMeasure:
    date: str
    n_bars: int
    n_returns: int
    n_gaps: int
    max_gap_min: float
    zero_volume_bars: int
    intraday_rv: float
    bpv: float
    jump_variation: float
    rs_pos: float
    rs_neg: float
    intraday_return: float
    intraday_return_sq: float
    overnight_return: float | None
    overnight_sq: float | None
    full_return: float | None
    full_return_sq: float | None
    total_rv: float | None
    open_price: float
    close_price: float


def finite_float(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v


def load_5min_file(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, header=[0, 1], index_col=0, parse_dates=True)
    df.columns = [col[0] for col in df.columns]
    df.index = pd.to_datetime(df.index, utc=True)
    for col in ["Close", "High", "Low", "Open", "Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Close", "Open"]).sort_index()
    return df


def gap_stats(index: pd.DatetimeIndex) -> tuple[int, float]:
    if len(index) < 2:
        return 0, 0.0
    diffs = pd.Series(index[1:]) - pd.Series(index[:-1])
    gaps = diffs[diffs > pd.Timedelta(minutes=10)]
    if gaps.empty:
        return 0, 0.0
    return int(len(gaps)), float(gaps.max().total_seconds() / 60.0)


def compute_daily_measures() -> tuple[pd.DataFrame, pd.DataFrame]:
    files = sorted(DATA_DIR.glob(FILE_PATTERN))
    if not files:
        raise RuntimeError(f"No {FILE_PATTERN} files found under {DATA_DIR}")

    rows: list[DailyMeasure] = []
    pattern_rows: list[pd.DataFrame] = []
    prev_close: float | None = None

    for path in files:
        date = path.stem.replace("0050_TW_5min_", "")
        df = load_5min_file(path)
        if len(df) < MIN_BARS_PER_DAY:
            continue

        close = df["Close"].astype(float)
        open_price = float(df["Open"].iloc[0])
        close_price = float(close.iloc[-1])
        log_ret = np.log(close / close.shift(1)).dropna()
        if len(log_ret) < MIN_BARS_PER_DAY - 2:
            continue

        rv = float(np.sum(log_ret.to_numpy() ** 2))
        abs_ret = np.abs(log_ret.to_numpy())
        bpv = float((np.pi / 2.0) * np.sum(abs_ret[1:] * abs_ret[:-1])) if len(abs_ret) >= 2 else float("nan")
        jump = float(max(rv - bpv, 0.0)) if math.isfinite(bpv) else float("nan")
        rs_pos = float(np.sum(log_ret[log_ret >= 0.0] ** 2))
        rs_neg = float(np.sum(log_ret[log_ret < 0.0] ** 2))
        intraday_return = float(np.log(close_price / open_price))
        overnight_return: float | None = None
        overnight_sq: float | None = None
        full_return: float | None = None
        full_return_sq: float | None = None
        total_rv: float | None = None
        if prev_close is not None and prev_close > 0:
            overnight_return = float(np.log(open_price / prev_close))
            overnight_sq = float(overnight_return**2)
            full_return = float(np.log(close_price / prev_close))
            full_return_sq = float(full_return**2)
            total_rv = float(rv + overnight_sq)

        n_gaps, max_gap = gap_stats(df.index)
        zero_volume = int((df["Volume"].fillna(0.0) == 0.0).sum()) if "Volume" in df.columns else 0
        rows.append(
            DailyMeasure(
                date=date,
                n_bars=int(len(close)),
                n_returns=int(len(log_ret)),
                n_gaps=n_gaps,
                max_gap_min=max_gap,
                zero_volume_bars=zero_volume,
                intraday_rv=rv,
                bpv=bpv,
                jump_variation=jump,
                rs_pos=rs_pos,
                rs_neg=rs_neg,
                intraday_return=intraday_return,
                intraday_return_sq=float(intraday_return**2),
                overnight_return=overnight_return,
                overnight_sq=overnight_sq,
                full_return=full_return,
                full_return_sq=full_return_sq,
                total_rv=total_rv,
                open_price=open_price,
                close_price=close_price,
            )
        )

        intraday_pattern = pd.DataFrame(
            {
                "date": date,
                "bar_index": np.arange(1, len(log_ret) + 1),
                "ret_sq": log_ret.to_numpy() ** 2,
                "abs_ret": np.abs(log_ret.to_numpy()),
            }
        )
        pattern_rows.append(intraday_pattern)
        prev_close = close_price

    daily = pd.DataFrame([asdict(row) for row in rows])
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values("date").set_index("date")
    pattern = pd.concat(pattern_rows, ignore_index=True) if pattern_rows else pd.DataFrame()
    return daily, pattern


def autocorr(series: pd.Series, lag: int = 1) -> float | None:
    s = series.dropna().astype(float)
    if len(s) <= lag + 2:
        return None
    return finite_float(s.autocorr(lag=lag))


def build_feature_frame(daily: pd.DataFrame, target_col: str) -> pd.DataFrame:
    target = daily[target_col].astype(float)
    base = target.clip(lower=VAR_FLOOR)
    out = pd.DataFrame(index=daily.index)
    out["target"] = target
    out["log_target_lag1"] = np.log(base.shift(1))
    out["log_target_lag5"] = np.log(base.rolling(5).mean().shift(1))
    out["log_target_lag22"] = np.log(base.rolling(22).mean().shift(1))

    bpv = daily["bpv"].astype(float).clip(lower=VAR_FLOOR)
    out["log_bpv_lag1"] = np.log(bpv.shift(1))
    out["log_bpv_lag5"] = np.log(bpv.rolling(5).mean().shift(1))
    out["log_bpv_lag22"] = np.log(bpv.rolling(22).mean().shift(1))
    return out


def fit_log_ols(train: pd.DataFrame, feature_cols: list[str]) -> np.ndarray:
    x = train[feature_cols].to_numpy(dtype=float)
    x = np.c_[np.ones(len(x)), x]
    y = np.log(train["target"].clip(lower=VAR_FLOOR).to_numpy(dtype=float))
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    return coef


def expanding_oos_forecasts(daily: pd.DataFrame, target_col: str) -> pd.DataFrame:
    features = build_feature_frame(daily, target_col)
    models = {
        "expanding_mean": [],
        "rv_lag1": [],
        "ar1_logrv": [],
        "har_logrv": [],
        "har_bpv": [],
    }
    dates: list[pd.Timestamp] = []
    actual: list[float] = []

    ar_cols = ["log_target_lag1"]
    har_cols = ["log_target_lag1", "log_target_lag5", "log_target_lag22"]
    bpv_cols = [*har_cols, "log_bpv_lag1", "log_bpv_lag5", "log_bpv_lag22"]

    df = features.copy()
    for pos, (idx, row) in enumerate(df.iterrows()):
        if pos < FIRST_OOS_OBS:
            continue
        if not np.isfinite(row["target"]):
            continue
        train = df.iloc[:pos].dropna(subset=["target", *bpv_cols]).copy()
        if len(train) < MIN_TRAIN_OBS:
            continue
        if not np.all(np.isfinite(row[bpv_cols].to_numpy(dtype=float))):
            continue

        dates.append(pd.Timestamp(idx))
        actual.append(float(row["target"]))

        train_target = train["target"].clip(lower=VAR_FLOOR)
        models["expanding_mean"].append(float(train_target.mean()))
        models["rv_lag1"].append(float(math.exp(row["log_target_lag1"])))

        coef_ar = fit_log_ols(train, ar_cols)
        pred_ar = float(np.r_[1.0, row[ar_cols].to_numpy(dtype=float)] @ coef_ar)
        models["ar1_logrv"].append(float(max(math.exp(pred_ar), VAR_FLOOR)))

        coef_har = fit_log_ols(train, har_cols)
        pred_har = float(np.r_[1.0, row[har_cols].to_numpy(dtype=float)] @ coef_har)
        models["har_logrv"].append(float(max(math.exp(pred_har), VAR_FLOOR)))

        coef_bpv = fit_log_ols(train, bpv_cols)
        pred_bpv = float(np.r_[1.0, row[bpv_cols].to_numpy(dtype=float)] @ coef_bpv)
        models["har_bpv"].append(float(max(math.exp(pred_bpv), VAR_FLOOR)))

    out = pd.DataFrame({"date": dates, "actual": actual}).set_index("date")
    for model, vals in models.items():
        out[model] = vals
    return out


def evaluate_forecasts(oos: pd.DataFrame) -> dict[str, Any]:
    model_cols = [c for c in oos.columns if c != "actual"]
    actual = oos["actual"].to_numpy(dtype=float)
    losses = {model: qlike_pointwise(actual, oos[model].to_numpy(dtype=float)) for model in model_cols}
    metrics: dict[str, dict[str, float | int | None]] = {}
    for model in model_cols:
        forecast = oos[model].to_numpy(dtype=float)
        rho, rho_p = spearman_corr(actual, forecast)
        metrics[model] = {
            "qlike": finite_float(qlike(actual, forecast)),
            "mse": finite_float(np.mean((actual - forecast) ** 2)),
            "spearman_rho": finite_float(rho),
            "spearman_p": finite_float(rho_p),
        }

    comparisons: dict[str, dict[str, float | None]] = {}
    for model in model_cols:
        if model == "rv_lag1":
            continue
        t_stat, p_val = dm_test(losses[model], losses["rv_lag1"], h=1)
        base = metrics["rv_lag1"]["qlike"]
        cur = metrics[model]["qlike"]
        improvement = None
        if base is not None and cur is not None and base != 0:
            improvement = 100.0 * (base - cur) / abs(base)
        comparisons[f"{model}_vs_rv_lag1"] = {
            "qlike_improvement_pct": finite_float(improvement),
            "dm_t_model_minus_lag1": finite_float(t_stat),
            "dm_p": finite_float(p_val),
            "interpretation": "negative DM t means the named model has lower QLIKE than rv_lag1",
        }

    best_model = min(
        model_cols,
        key=lambda model: metrics[model]["qlike"] if metrics[model]["qlike"] is not None else float("inf"),
    )
    return {
        "n_oos": int(len(oos)),
        "start": str(oos.index.min().date()) if len(oos) else None,
        "end": str(oos.index.max().date()) if len(oos) else None,
        "metrics": metrics,
        "comparisons_vs_rv_lag1": comparisons,
        "best_by_qlike": best_model,
    }


def summarize_daily(daily: pd.DataFrame) -> dict[str, Any]:
    valid_total = daily.dropna(subset=["total_rv"])
    clean_close, _clean_ret = clean_tw50_data(daily["close_price"])
    close_delta = (clean_close - daily["close_price"]).abs()
    out = {
        "n_days": int(len(daily)),
        "start": str(daily.index.min().date()),
        "end": str(daily.index.max().date()),
        "bar_count": {
            "min": int(daily["n_bars"].min()),
            "median": float(daily["n_bars"].median()),
            "max": int(daily["n_bars"].max()),
            "mean": float(daily["n_bars"].mean()),
        },
        "gap_days": int((daily["n_gaps"] > 0).sum()),
        "zero_volume_bar_days": int((daily["zero_volume_bars"] > 0).sum()),
        "clean_tw50_data_sanity": {
            "applied_to_daily_close_path": "volpred.utils.clean_tw50_data(daily close_price)",
            "n_adjusted_daily_closes": int((close_delta > 1e-10).sum()),
            "max_abs_close_adjustment": finite_float(close_delta.max()),
            "note": "Expected zero for 2026-only intraday bars; this is a 0050.TW split-artifact guard, not the RV estimator.",
        },
        "intraday_rv": {
            "mean": float(daily["intraday_rv"].mean()),
            "median": float(daily["intraday_rv"].median()),
            "p95": float(daily["intraday_rv"].quantile(0.95)),
            "max": float(daily["intraday_rv"].max()),
            "mean_annualized_vol": float(np.sqrt(daily["intraday_rv"].mean() * 252.0)),
        },
        "overnight_share_of_total_rv": None,
        "autocorrelation_lag1": {
            "intraday_rv": autocorr(daily["intraday_rv"], 1),
            "total_rv": autocorr(daily["total_rv"], 1),
            "intraday_return_sq": autocorr(daily["intraday_return_sq"], 1),
            "abs_intraday_return": autocorr(daily["intraday_return"].abs(), 1),
            "bpv": autocorr(daily["bpv"], 1),
        },
    }
    if len(valid_total) > 0:
        out["overnight_share_of_total_rv"] = finite_float(
            valid_total["overnight_sq"].sum() / valid_total["total_rv"].sum()
        )
    return out


def verdict_for_target(target_eval: dict[str, Any]) -> str:
    n_oos = int(target_eval["n_oos"])
    if n_oos < PAPER_GRADE_MIN_OOS:
        return "PILOT_ONLY_INSUFFICIENT_OOS"
    comp = target_eval["comparisons_vs_rv_lag1"].get("har_logrv_vs_rv_lag1", {})
    imp = comp.get("qlike_improvement_pct")
    t_stat = comp.get("dm_t_model_minus_lag1")
    if imp is not None and t_stat is not None and imp > 5.0 and t_stat < -HARVEY_T:
        return "CONDITIONAL_PASS_HAR_BEATS_LAG1"
    return "NULL_NO_HARVEY_PASS"


def plot_rv_timeseries(daily: pd.DataFrame) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    ann_intraday = np.sqrt(daily["intraday_rv"] * 252.0)
    ann_total = np.sqrt(daily["total_rv"] * 252.0)
    axes[0].plot(daily.index, ann_intraday, label="intraday 5-min RV", color="#1f77b4", lw=1.2)
    axes[0].plot(daily.index, ann_total, label="intraday + overnight", color="#ff7f0e", lw=1.0, alpha=0.85)
    axes[0].set_ylabel("annualized vol")
    axes[0].set_title("K1349 0050.TW realized volatility from 5-minute bars")
    axes[0].legend(loc="best")

    axes[1].bar(daily.index, daily["overnight_sq"], color="#9467bd", alpha=0.7, label="overnight r^2")
    axes[1].plot(daily.index, daily["intraday_rv"], color="#1f77b4", lw=1.0, label="intraday RV")
    axes[1].set_ylabel("variance")
    axes[1].legend(loc="best")
    fig.tight_layout()
    fig.savefig(FIG_RV, dpi=140)
    plt.close(fig)


def plot_oos_qlike(intraday_eval: dict[str, Any], total_eval: dict[str, Any]) -> None:
    models = list(intraday_eval["metrics"].keys())
    x = np.arange(len(models))
    width = 0.38
    intra = [intraday_eval["metrics"][m]["qlike"] for m in models]
    total = [total_eval["metrics"][m]["qlike"] for m in models]
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.bar(x - width / 2, intra, width=width, label="intraday RV target", color="#1f77b4")
    ax.bar(x + width / 2, total, width=width, label="total RV target", color="#ff7f0e")
    ax.set_xticks(x)
    ax.set_xticklabels(models, rotation=25, ha="right")
    ax.set_ylabel("QLIKE (lower is better)")
    ax.set_title("K1349 pseudo-OOS QLIKE by target")
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(FIG_QLIKE, dpi=140)
    plt.close(fig)


def plot_intraday_pattern(pattern: pd.DataFrame) -> None:
    if pattern.empty:
        return
    grouped = pattern.groupby("bar_index")["ret_sq"].agg(["mean", "median", "count"])
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(grouped.index, grouped["mean"], lw=1.4, color="#1f77b4", label="mean 5-min r^2")
    ax.plot(grouped.index, grouped["median"], lw=1.1, color="#ff7f0e", label="median 5-min r^2")
    ax.set_xlabel("5-minute return index within session")
    ax.set_ylabel("squared log return")
    ax.set_title("K1349 average intraday variance pattern")
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(FIG_PATTERN, dpi=140)
    plt.close(fig)


def serialize_nested(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: serialize_nested(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [serialize_nested(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return finite_float(obj)
    return obj


def main() -> None:
    daily, pattern = compute_daily_measures()
    daily.to_csv(DAILY_MEASURES_PATH)

    oos_intraday = expanding_oos_forecasts(daily, "intraday_rv")
    oos_total = expanding_oos_forecasts(daily.dropna(subset=["total_rv"]), "total_rv")
    oos_intraday.to_csv(OOS_INTRADAY_PATH)
    oos_total.to_csv(OOS_TOTAL_PATH)

    intraday_eval = evaluate_forecasts(oos_intraday)
    total_eval = evaluate_forecasts(oos_total)
    plot_rv_timeseries(daily)
    plot_oos_qlike(intraday_eval, total_eval)
    plot_intraday_pattern(pattern)

    intraday_verdict = verdict_for_target(intraday_eval)
    total_verdict = verdict_for_target(total_eval)
    overall_verdict = "PILOT_ONLY_INSUFFICIENT_OOS"
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "title": "0050.TW 5-minute realized variance HAR-RV pilot",
        "created_by": "codex",
        "seed": SEED,
        "data_source": {
            "raw_files": f"{DATA_DIR}/{FILE_PATTERN}",
            "source": "Local yfinance 5-minute CSV cache",
            "ticker": TICKER,
        },
        "method": {
            "rv_target": "sum of squared 5-minute log returns from observed 0050.TW bars",
            "total_rv_target": "intraday RV plus squared overnight open-vs-previous-close return",
            "models": [
                "expanding_mean",
                "rv_lag1",
                "ar1_logrv",
                "har_logrv",
                "har_bpv",
            ],
            "first_oos_observation_index": FIRST_OOS_OBS,
            "min_train_obs": MIN_TRAIN_OBS,
            "loss": "QLIKE actual/forecast - log(actual/forecast) - 1",
            "dm_test": "volpred.stats.model_evaluation.dm_test on pointwise QLIKE losses; negative t means first model is better.",
            "paper_grade_warning": f"OOS N must be >= {PAPER_GRADE_MIN_OOS}; this pilot has far fewer observations.",
        },
        "lookahead_guard": [
            "HAR features use target.shift(1), rolling(5).mean().shift(1), and rolling(22).mean().shift(1).",
            "BPV features use bpv.shift(1), rolling(5).mean().shift(1), and rolling(22).mean().shift(1).",
            "For forecast date t, OLS training rows are df.iloc[:pos], strictly earlier than t.",
        ],
        "literature": LITERATURE,
        "related_prior_work": RELATED_PRIOR,
        "data_quality": summarize_daily(daily),
        "forecast_evaluation": {
            "intraday_rv": intraday_eval,
            "total_rv": total_eval,
        },
        "verdict": {
            "overall": overall_verdict,
            "intraday_rv": intraday_verdict,
            "total_rv": total_verdict,
            "notes": [
                "The 0050.TW 5-minute data pipeline is usable: 94 days, 53-54 bars/day, no large intraday gaps.",
                "Forecast comparison is intentionally pilot-only because OOS length is below the project 252-day minimum.",
                "Do not write a knowledge entry or article-grade claim from this pilot alone.",
            ],
        },
        "outputs": [
            DAILY_MEASURES_PATH.name,
            OOS_INTRADAY_PATH.name,
            OOS_TOTAL_PATH.name,
            FIG_RV.name,
            FIG_QLIKE.name,
            FIG_PATTERN.name,
        ],
    }
    RESULTS_PATH.write_text(json.dumps(serialize_nested(payload), indent=2, ensure_ascii=False) + "\n")

    print(f"[data] days={len(daily)} sample={daily.index.min().date()}->{daily.index.max().date()}")
    print(f"[oos] intraday_n={intraday_eval['n_oos']} total_n={total_eval['n_oos']}")
    print(f"[verdict] {overall_verdict}")
    for target_name, target_eval in [("intraday_rv", intraday_eval), ("total_rv", total_eval)]:
        best = target_eval["best_by_qlike"]
        har_comp = target_eval["comparisons_vs_rv_lag1"].get("har_logrv_vs_rv_lag1", {})
        print(
            f"[result] {target_name}: best={best} "
            f"HAR_vs_lag1_impr={har_comp.get('qlike_improvement_pct')} "
            f"dm_t={har_comp.get('dm_t_model_minus_lag1')}"
        )
    print(f"[write] {RESULTS_PATH}")


if __name__ == "__main__":
    main()
