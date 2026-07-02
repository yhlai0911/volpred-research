from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats


EXPERIMENT_ID = "research_glp_1_adoption_shock_sector_consumption_healthca"
ROOT = Path(__file__).resolve().parents[2]
EXP_DIR = ROOT / "experiments" / EXPERIMENT_ID
DATA_DIR = EXP_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
FIGURES_DIR = EXP_DIR / "figures"
RESULTS_PATH = EXP_DIR / f"{EXPERIMENT_ID}_results.json"

RANDOM_SEED = 42
N_BOOT = 10_000
N_PLACEBO = 2_000
BASELINE_START_OFFSET = -60
BASELINE_END_OFFSET = -11
PRE_START_OFFSET = -10
PRE_END_OFFSET = -1
POST_HORIZONS = [5, 22]
MIN_GROUP_TICKERS = {
    "glp_makers": 1,
    "healthcare_broad": 2,
    "diabetes_medtech": 2,
    "food_beverage": 3,
    "restaurants": 3,
}
EPS = 1e-12


EVENTS = [
    {
        "date": "2021-06-04",
        "label": "FDA Wegovy chronic weight-management approval",
        "shock_type": "approval",
        "source": "FDA approval / Wegovy label event",
    },
    {
        "date": "2022-04-28",
        "label": "Lilly SURMOUNT-1 top-line tirzepatide obesity result",
        "shock_type": "clinical_topline",
        "source": "Eli Lilly SURMOUNT-1 top-line release",
    },
    {
        "date": "2023-08-08",
        "label": "Novo SELECT semaglutide CV outcomes headline",
        "shock_type": "clinical_topline",
        "source": "Novo Nordisk SELECT headline release",
    },
    {
        "date": "2023-11-08",
        "label": "FDA Zepbound chronic weight-management approval",
        "shock_type": "approval",
        "source": "FDA Zepbound approval release",
    },
    {
        "date": "2024-03-08",
        "label": "FDA Wegovy CV risk-reduction label expansion",
        "shock_type": "label_expansion",
        "source": "FDA semaglutide CV risk-reduction indication",
    },
    {
        "date": "2024-08-20",
        "label": "Lilly SURMOUNT-1 three-year diabetes-risk reduction",
        "shock_type": "clinical_topline",
        "source": "Eli Lilly SURMOUNT-1 three-year release",
    },
]

TARGET_GROUPS = {
    "glp_makers": ["LLY", "NVO"],
    "healthcare_broad": ["XLV", "IYH", "IHE", "PPH"],
    "diabetes_medtech": ["DXCM", "PODD", "TNDM", "ABT", "MDT"],
    "food_beverage": ["XLP", "PBJ", "PEP", "KO", "MDLZ", "HSY", "GIS", "KHC", "CPB", "CAG", "KDP", "MNST"],
    "restaurants": ["MCD", "SBUX", "YUM", "DPZ", "CMG", "DRI", "CAKE", "WING"],
}
CONTROL_TICKERS = ["SPY", "QQQ", "IWM"]


@dataclass(frozen=True)
class WindowMetric:
    event_date: pd.Timestamp
    trading_date: pd.Timestamp
    ticker: str
    group: str
    horizon: int
    baseline_rv: float
    pre_rv: float
    post_rv: float
    same_day_r2: float
    log_rv_ratio: float


def ensure_dirs() -> None:
    for path in [DATA_DIR, RAW_DIR, FIGURES_DIR]:
        path.mkdir(parents=True, exist_ok=True)


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
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if pd.isna(value):
        return None
    return value


def extract_adjusted_close(download: pd.DataFrame, symbol: str) -> pd.Series:
    if download.empty:
        raise ValueError(f"No yfinance data for {symbol}")

    data = download.copy()
    if isinstance(data.columns, pd.MultiIndex):
        if "Adj Close" in data.columns.get_level_values(0):
            close = data["Adj Close"]
        elif "Adj Close" in data.columns.get_level_values(-1):
            close = data.xs("Adj Close", level=-1, axis=1)
        elif "Close" in data.columns.get_level_values(0):
            close = data["Close"]
        else:
            raise ValueError(f"Cannot find close column for {symbol}")
        if isinstance(close, pd.DataFrame):
            if symbol in close.columns:
                close = close[symbol]
            else:
                close = close.iloc[:, 0]
    elif "Adj Close" in data.columns:
        close = data["Adj Close"]
    elif "Close" in data.columns:
        close = data["Close"]
    else:
        raise ValueError(f"Cannot find close column for {symbol}")

    series = pd.Series(close, name=symbol)
    series.index = pd.to_datetime(series.index).tz_localize(None)
    return series.dropna().astype(float)


def download_adjusted_close(symbol: str) -> pd.Series | None:
    path = RAW_DIR / f"yfinance_adj_close_{symbol}.csv"
    if path.exists():
        cached = pd.read_csv(path, parse_dates=["Date"])
        if symbol in cached.columns:
            return pd.Series(cached[symbol].to_numpy(dtype=float), index=cached["Date"], name=symbol).dropna()

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=FutureWarning)
            data = yf.download(
                symbol,
                start="2020-01-01",
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


def build_returns() -> tuple[pd.DataFrame, dict]:
    symbols = sorted({ticker for group in TARGET_GROUPS.values() for ticker in group} | set(CONTROL_TICKERS))
    prices: dict[str, pd.Series] = {}
    meta: dict[str, dict] = {}
    for symbol in symbols:
        close = download_adjusted_close(symbol)
        if close is None or close.shape[0] < 252:
            meta[symbol] = {"usable": False, "reason": "missing_or_short_price_history"}
            continue
        prices[symbol] = close
        meta[symbol] = {
            "usable": True,
            "start": close.index.min(),
            "end": close.index.max(),
            "n_prices": int(close.shape[0]),
        }

    price_panel = pd.concat(prices.values(), axis=1).sort_index()
    returns = np.log(price_panel / price_panel.shift(1)).replace([np.inf, -np.inf], np.nan)
    returns.to_csv(DATA_DIR / "daily_log_returns.csv")
    return returns, meta


def first_trading_date_on_or_after(index: pd.DatetimeIndex, event_date: pd.Timestamp) -> pd.Timestamp | None:
    candidates = index[index >= event_date]
    if candidates.empty:
        return None
    return candidates[0]


def ticker_window_metric(
    returns: pd.Series,
    event_date: pd.Timestamp,
    ticker: str,
    group: str,
    horizon: int,
) -> WindowMetric | None:
    series = returns.dropna()
    trading_date = first_trading_date_on_or_after(series.index, event_date)
    if trading_date is None:
        return None

    loc = series.index.get_loc(trading_date)
    if isinstance(loc, slice) or isinstance(loc, np.ndarray):
        return None

    baseline_start = loc + BASELINE_START_OFFSET
    baseline_end = loc + BASELINE_END_OFFSET
    pre_start = loc + PRE_START_OFFSET
    pre_end = loc + PRE_END_OFFSET
    post_start = loc + 1
    post_end = loc + horizon
    if baseline_start < 0 or pre_start < 0 or post_end >= series.shape[0]:
        return None

    baseline = series.iloc[baseline_start : baseline_end + 1]
    pre = series.iloc[pre_start : pre_end + 1]
    post = series.iloc[post_start : post_end + 1]
    if baseline.shape[0] < 40 or pre.shape[0] < 5 or post.shape[0] < horizon:
        return None

    baseline_rv = float(np.mean(np.square(baseline)))
    pre_rv = float(np.mean(np.square(pre)))
    post_rv = float(np.mean(np.square(post)))
    same_day_r2 = float(series.iloc[loc] ** 2)
    if baseline_rv <= EPS or post_rv <= EPS:
        return None

    return WindowMetric(
        event_date=event_date,
        trading_date=trading_date,
        ticker=ticker,
        group=group,
        horizon=horizon,
        baseline_rv=baseline_rv,
        pre_rv=pre_rv,
        post_rv=post_rv,
        same_day_r2=same_day_r2,
        log_rv_ratio=float(np.log(post_rv / baseline_rv)),
    )


def compute_ticker_metrics_for_event(
    returns: pd.DataFrame,
    event_date: pd.Timestamp,
    horizon: int,
) -> list[WindowMetric]:
    rows: list[WindowMetric] = []
    for group, tickers in TARGET_GROUPS.items():
        for ticker in tickers:
            if ticker not in returns:
                continue
            metric = ticker_window_metric(returns[ticker], event_date, ticker, group, horizon)
            if metric is not None:
                rows.append(metric)
    return rows


def control_log_ratio(returns: pd.DataFrame, event_date: pd.Timestamp, horizon: int) -> float | None:
    values = []
    for ticker in CONTROL_TICKERS:
        if ticker not in returns:
            continue
        metric = ticker_window_metric(returns[ticker], event_date, ticker, "control", horizon)
        if metric is not None:
            values.append(metric.log_rv_ratio)
    if len(values) < 2:
        return None
    return float(np.mean(values))


def build_event_panels(returns: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    ticker_rows = []
    group_rows = []
    event_lookup = {pd.Timestamp(event["date"]): event for event in EVENTS}

    for event in EVENTS:
        event_date = pd.Timestamp(event["date"])
        for horizon in POST_HORIZONS:
            control_ratio = control_log_ratio(returns, event_date, horizon)
            if control_ratio is None:
                continue
            metrics = compute_ticker_metrics_for_event(returns, event_date, horizon)
            for metric in metrics:
                ticker_rows.append(
                    {
                        "event_date": metric.event_date,
                        "trading_date": metric.trading_date,
                        "event_label": event["label"],
                        "shock_type": event["shock_type"],
                        "source": event["source"],
                        "ticker": metric.ticker,
                        "group": metric.group,
                        "horizon": metric.horizon,
                        "baseline_rv": metric.baseline_rv,
                        "pre_rv": metric.pre_rv,
                        "post_rv": metric.post_rv,
                        "same_day_r2": metric.same_day_r2,
                        "log_rv_ratio": metric.log_rv_ratio,
                        "control_log_rv_ratio": control_ratio,
                        "adj_log_rv_ratio": metric.log_rv_ratio - control_ratio,
                    }
                )

            if not metrics:
                continue
            metric_df = pd.DataFrame([m.__dict__ for m in metrics])
            for group in TARGET_GROUPS:
                sub = metric_df[metric_df["group"] == group]
                min_tickers = MIN_GROUP_TICKERS[group]
                if sub.shape[0] < min_tickers:
                    continue
                group_rows.append(
                    {
                        "event_date": event_date,
                        "trading_date": sub["trading_date"].mode().iloc[0],
                        "event_label": event_lookup[event_date]["label"],
                        "shock_type": event_lookup[event_date]["shock_type"],
                        "group": group,
                        "horizon": horizon,
                        "n_tickers": int(sub.shape[0]),
                        "mean_log_rv_ratio": float(sub["log_rv_ratio"].mean()),
                        "median_log_rv_ratio": float(sub["log_rv_ratio"].median()),
                        "control_log_rv_ratio": control_ratio,
                        "adj_log_rv_ratio": float(sub["log_rv_ratio"].mean() - control_ratio),
                    }
                )

    ticker_panel = pd.DataFrame(ticker_rows)
    group_panel = pd.DataFrame(group_rows)
    ticker_panel.to_csv(DATA_DIR / "ticker_event_metrics.csv", index=False)
    group_panel.to_csv(DATA_DIR / "group_event_metrics.csv", index=False)
    return ticker_panel, group_panel


def holm_adjust(pvalues: list[float]) -> list[float]:
    n = len(pvalues)
    order = np.argsort(pvalues)
    adjusted = np.empty(n, dtype=float)
    running_max = 0.0
    for rank, idx in enumerate(order):
        raw = pvalues[idx]
        value = min(1.0, (n - rank) * raw)
        running_max = max(running_max, value)
        adjusted[idx] = running_max
    return adjusted.tolist()


def summarize_vector(values: np.ndarray, rng: np.random.Generator) -> dict:
    values = values[np.isfinite(values)]
    n = int(values.shape[0])
    if n == 0:
        return {
            "n_events": 0,
            "mean": None,
            "median": None,
            "t_stat": None,
            "p_t_upper": None,
            "sign_positive": None,
            "p_sign_upper": None,
            "boot_ci_low": None,
            "boot_ci_high": None,
            "boot_prob_mean_le_0": None,
        }

    mean = float(np.mean(values))
    median = float(np.median(values))
    if n > 1 and np.std(values, ddof=1) > EPS:
        t_stat = float(mean / (np.std(values, ddof=1) / math.sqrt(n)))
        p_t_upper = float(stats.t.sf(t_stat, df=n - 1))
    else:
        t_stat = None
        p_t_upper = None

    sign_positive = int(np.sum(values > 0))
    p_sign_upper = float(stats.binomtest(sign_positive, n=n, p=0.5, alternative="greater").pvalue)
    boot = rng.choice(values, size=(N_BOOT, n), replace=True).mean(axis=1)
    return {
        "n_events": n,
        "mean": mean,
        "median": median,
        "t_stat": t_stat,
        "p_t_upper": p_t_upper,
        "sign_positive": sign_positive,
        "p_sign_upper": p_sign_upper,
        "boot_ci_low": float(np.quantile(boot, 0.025)),
        "boot_ci_high": float(np.quantile(boot, 0.975)),
        "boot_prob_mean_le_0": float(np.mean(boot <= 0.0)),
    }


def build_anchor_group_panel(returns: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for horizon in POST_HORIZONS:
        for anchor in pd.DatetimeIndex(returns.index).unique().sort_values():
            control_ratio = control_log_ratio(returns, anchor, horizon)
            if control_ratio is None:
                continue
            metrics = compute_ticker_metrics_for_event(returns, anchor, horizon)
            if not metrics:
                continue
            metric_df = pd.DataFrame([metric.__dict__ for metric in metrics])
            for group in TARGET_GROUPS:
                sub = metric_df[metric_df["group"] == group]
                if sub.shape[0] < MIN_GROUP_TICKERS[group]:
                    continue
                rows.append(
                    {
                        "anchor_date": anchor,
                        "year": int(anchor.year),
                        "group": group,
                        "horizon": horizon,
                        "n_tickers": int(sub.shape[0]),
                        "control_log_rv_ratio": control_ratio,
                        "adj_log_rv_ratio": float(sub["log_rv_ratio"].mean() - control_ratio),
                    }
                )
    panel = pd.DataFrame(rows)
    panel.to_csv(DATA_DIR / "anchor_group_metrics.csv", index=False)
    return panel


def placebo_pvalue(
    anchor_panel: pd.DataFrame,
    group: str,
    horizon: int,
    observed_mean: float,
    rng: np.random.Generator,
) -> dict:
    true_event_dates = [pd.Timestamp(event["date"]) for event in EVENTS]
    sub = anchor_panel[(anchor_panel["group"] == group) & (anchor_panel["horizon"] == horizon)].copy()
    sub["anchor_date"] = pd.to_datetime(sub["anchor_date"])
    for event_date in true_event_dates:
        sub = sub[(sub["anchor_date"] - event_date).abs().dt.days > 30]

    values_by_year = {
        year: sub.loc[sub["year"] == year, "adj_log_rv_ratio"].to_numpy(dtype=float)
        for year in sorted({date.year for date in true_event_dates})
    }
    if any(values.shape[0] == 0 for values in values_by_year.values()):
        return {
            "n_placebo": 0,
            "p_placebo_upper": None,
            "placebo_mean": None,
            "placebo_ci_low": None,
            "placebo_ci_high": None,
        }

    placebo_means = []
    for _ in range(N_PLACEBO):
        sampled = []
        for event_date in true_event_dates:
            year_values = values_by_year[event_date.year]
            sampled.append(float(year_values[int(rng.integers(0, len(year_values)))]))
        if len(sampled) == len(true_event_dates):
            placebo_means.append(float(np.mean(sampled)))

    placebo = np.array(placebo_means, dtype=float)
    if placebo.shape[0] == 0:
        return {
            "n_placebo": 0,
            "p_placebo_upper": None,
            "placebo_mean": None,
            "placebo_ci_low": None,
            "placebo_ci_high": None,
        }
    return {
        "n_placebo": int(placebo.shape[0]),
        "p_placebo_upper": float((np.sum(placebo >= observed_mean) + 1.0) / (placebo.shape[0] + 1.0)),
        "placebo_mean": float(np.mean(placebo)),
        "placebo_ci_low": float(np.quantile(placebo, 0.025)),
        "placebo_ci_high": float(np.quantile(placebo, 0.975)),
    }


def summarize_group_panel(anchor_panel: pd.DataFrame, group_panel: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    rng = np.random.default_rng(RANDOM_SEED)
    rows = []
    for horizon in POST_HORIZONS:
        for group in TARGET_GROUPS:
            values = group_panel[
                (group_panel["horizon"] == horizon) & (group_panel["group"] == group)
            ]["adj_log_rv_ratio"].to_numpy(dtype=float)
            summary = summarize_vector(values, rng)
            placebo = placebo_pvalue(anchor_panel, group, horizon, summary["mean"], rng) if summary["mean"] is not None else {}
            rows.append({"group": group, "horizon": horizon, **summary, **placebo})

    summary_df = pd.DataFrame(rows)
    for p_col in ["p_t_upper", "p_sign_upper", "p_placebo_upper"]:
        adjusted_col = p_col.replace("p_", "p_holm_")
        valid = summary_df[p_col].notna()
        adjusted = [None] * summary_df.shape[0]
        adjusted_valid = holm_adjust(summary_df.loc[valid, p_col].astype(float).tolist())
        for idx, value in zip(summary_df.index[valid], adjusted_valid):
            adjusted[idx] = value
        summary_df[adjusted_col] = adjusted

    summary_df.to_csv(DATA_DIR / "group_summary.csv", index=False)

    result_dict = {}
    for _, row in summary_df.iterrows():
        key = f"{row['group']}_{int(row['horizon'])}d"
        result_dict[key] = {col: row[col] for col in summary_df.columns if col not in {"group", "horizon"}}
    return summary_df, result_dict


def make_figures(group_panel: pd.DataFrame, summary_df: pd.DataFrame) -> None:
    plot_df = summary_df.copy()
    plot_df["mean_exp"] = np.exp(plot_df["mean"]) - 1.0
    plot_df["ci_low_exp"] = np.exp(plot_df["boot_ci_low"]) - 1.0
    plot_df["ci_high_exp"] = np.exp(plot_df["boot_ci_high"]) - 1.0

    fig, ax = plt.subplots(figsize=(10, 5.8))
    groups = list(TARGET_GROUPS)
    x = np.arange(len(groups))
    width = 0.35
    colors = {5: "#1f77b4", 22: "#ff7f0e"}
    for i, horizon in enumerate(POST_HORIZONS):
        sub = plot_df[plot_df["horizon"] == horizon].set_index("group").loc[groups]
        centers = x + (i - 0.5) * width
        y = sub["mean_exp"].to_numpy(dtype=float)
        yerr = np.vstack(
            [
                y - sub["ci_low_exp"].to_numpy(dtype=float),
                sub["ci_high_exp"].to_numpy(dtype=float) - y,
            ]
        )
        ax.bar(centers, y, width=width, label=f"T+1..T+{horizon}", color=colors[horizon], alpha=0.82)
        ax.errorbar(centers, y, yerr=yerr, fmt="none", ecolor="#222222", elinewidth=1, capsize=3)
    ax.axhline(0, color="#333333", linewidth=1)
    ax.set_ylabel("Market-adjusted RV ratio minus 1")
    ax.set_title("GLP-1 event-window adjusted realized variance by group")
    ax.set_xticks(x)
    ax.set_xticklabels(groups, rotation=25, ha="right")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "group_adjusted_rv_ratio.png", dpi=180)
    plt.close(fig)

    heat = (
        group_panel[group_panel["horizon"] == 5]
        .pivot(index="event_label", columns="group", values="adj_log_rv_ratio")
        .reindex(columns=groups)
    )
    fig, ax = plt.subplots(figsize=(11, 5.8))
    im = ax.imshow(heat.to_numpy(dtype=float), aspect="auto", cmap="coolwarm", vmin=-2.0, vmax=2.0)
    ax.set_xticks(np.arange(len(heat.columns)))
    ax.set_xticklabels(heat.columns, rotation=25, ha="right")
    ax.set_yticks(np.arange(len(heat.index)))
    ax.set_yticklabels([label[:52] for label in heat.index])
    ax.set_title("T+1..T+5 adjusted log-RV ratio by GLP-1 event")
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Adjusted log-RV ratio")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "event_group_heatmap_5d.png", dpi=180)
    plt.close(fig)


def verdict(summary_df: pd.DataFrame) -> str:
    primary = summary_df[
        summary_df["group"].isin(["glp_makers", "food_beverage", "restaurants", "diabetes_medtech"])
    ].copy()
    positive_survivors = primary[
        (primary["mean"] > 0)
        & (primary["p_holm_t_upper"].fillna(1.0) < 0.05)
        & (primary["p_holm_placebo_upper"].fillna(1.0) < 0.05)
    ]
    weak = primary[
        (primary["mean"] > 0)
        & ((primary["p_t_upper"].fillna(1.0) < 0.10) | (primary["p_placebo_upper"].fillna(1.0) < 0.10))
    ]
    if not positive_survivors.empty:
        return "positive_glp1_event_vol_factor"
    if not weak.empty:
        return "weak_raw_only"
    return "null_or_inconclusive"


def main() -> None:
    ensure_dirs()
    returns, price_meta = build_returns()
    ticker_panel, group_panel = build_event_panels(returns)
    if ticker_panel.empty or group_panel.empty:
        raise RuntimeError("Event panels are empty; cannot summarize experiment.")

    anchor_panel = build_anchor_group_panel(returns)
    summary_df, summary = summarize_group_panel(anchor_panel, group_panel)
    make_figures(group_panel, summary_df)
    result_verdict = verdict(summary_df)

    results = {
        "experiment_id": EXPERIMENT_ID,
        "created_at": datetime.now().astimezone().isoformat(),
        "random_seed": RANDOM_SEED,
        "data_sources": {
            "prices": {
                "provider": "yfinance",
                "auto_adjust": False,
                "field_used": "Adj Close",
                "start": "2020-01-01",
                "tickers": TARGET_GROUPS,
                "controls": CONTROL_TICKERS,
                "price_meta": price_meta,
            },
            "event_sources": EVENTS,
        },
        "method": {
            "unit_of_inference": "event-level group mean, not pooled ticker-event rows",
            "baseline_window": "T-60..T-11 trading days",
            "pre_window_diagnostic": "T-10..T-1 trading days",
            "primary_post_windows": ["T+1..T+5", "T+1..T+22"],
            "same_day_treatment": "same-day squared return is recorded only as a diagnostic; primary tests start at T+1",
            "control_adjustment": "subtract equal-weight SPY/QQQ/IWM log-RV ratio for the same event window",
            "bootstrap": {
                "seed": RANDOM_SEED,
                "n_boot": N_BOOT,
                "resampling_unit": "event",
            },
            "placebo": {
                "seed": RANDOM_SEED,
                "n_placebo": N_PLACEBO,
                "anchor_rule": "random non-event trading days in the same calendar year, excluding +/-30 calendar days around true events",
            },
            "multiple_testing": "Holm adjustment across all group x horizon cells for t, sign, and placebo p-values",
        },
        "diagnostics": {
            "n_events": len(EVENTS),
            "n_ticker_event_rows": int(ticker_panel.shape[0]),
            "n_group_event_rows": int(group_panel.shape[0]),
            "n_anchor_group_rows": int(anchor_panel.shape[0]),
            "event_dates": [event["date"] for event in EVENTS],
            "groups": {group: len(tickers) for group, tickers in TARGET_GROUPS.items()},
        },
        "summary": summary,
        "verdict": result_verdict,
        "files": {
            "ticker_event_metrics": str(DATA_DIR / "ticker_event_metrics.csv"),
            "group_event_metrics": str(DATA_DIR / "group_event_metrics.csv"),
            "anchor_group_metrics": str(DATA_DIR / "anchor_group_metrics.csv"),
            "group_summary": str(DATA_DIR / "group_summary.csv"),
            "figures": [
                str(FIGURES_DIR / "group_adjusted_rv_ratio.png"),
                str(FIGURES_DIR / "event_group_heatmap_5d.png"),
            ],
        },
    }
    RESULTS_PATH.write_text(json.dumps(to_jsonable(results), indent=2), encoding="utf-8")
    print(json.dumps(to_jsonable({"verdict": result_verdict, "summary": summary}), indent=2))


if __name__ == "__main__":
    main()
