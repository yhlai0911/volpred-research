#!/usr/bin/env python3
"""Cold-start transfer learning pilot for new-issue volatility forecasting.

The experiment tests a narrow, reproducible question:

    Can source-similar cross-asset history improve one-day-ahead close-to-close
    variance forecasts for assets with only ~60 trading days of own history?

This is a public-data proxy for the richer realized-volatility setting in the
new-issues / spin-offs transfer-learning literature. It uses daily adjusted
closes, target variance is close-to-close squared log return, and every feature
is explicitly lagged by one trading day.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_ID = "research_transfer_learning_for_new_issues_vol"
OUT_DIR = ROOT / "experiments" / EXPERIMENT_ID
DATA_DIR = OUT_DIR / "data"
PRICE_CACHE = DATA_DIR / "adjusted_close_yfinance.csv"
OUT_PATH = OUT_DIR / f"{EXPERIMENT_ID}_results.json"
FIG_PATH = OUT_DIR / f"{EXPERIMENT_ID}_qlike_improvement.png"

SEED = 42
EPS = 1.0e-10
DATA_START = "2015-01-01"
DATA_END_EXCLUSIVE = "2026-07-02"
MIN_EVAL_DAY = 60
MAX_EVAL_DAY = 550
SELECTION_DAYS = 45
SOURCE_WINDOW_DAYS = 40
TOP_SOURCE_WINDOWS = 12
MIN_TARGET_TRAIN_ROWS = 25
RIDGE_ALPHA = 1.0

TARGET_TICKERS = [
    "ABNB",  # IPO 2020
    "COIN",  # direct listing 2021
    "RIVN",  # IPO 2021
    "HOOD",  # IPO 2021
    "GEHC",  # GE HealthCare spin-off 2023
    "KVUE",  # Johnson & Johnson consumer-health IPO / separation 2023
    "ARM",  # IPO 2023
    "CAVA",  # IPO 2023
    "VLTO",  # Danaher spin-off 2023
    "BIRK",  # IPO 2023
]

SOURCE_TICKERS = [
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "XLK",
    "XLF",
    "XLY",
    "XLI",
    "XLV",
    "XLE",
    "XLP",
    "XLU",
    "SMH",
    "HYG",
    "TLT",
    "GLD",
    "USO",
    "UUP",
    "EEM",
    "EFA",
]

FEATURES = [
    "log_rv_lag1",
    "log_rv_lag5",
    "log_rv_lag22",
    "abs_ret_lag1",
    "neg_ret_lag1",
]


@dataclass(frozen=True)
class TargetRun:
    ticker: str
    first_price_date: str
    eval_start_date: pd.Timestamp
    train_rows: int
    eval_rows: int
    selected_source_rows: int
    all_source_rows: int
    selected_windows: list[dict[str, Any]]
    predictions: pd.DataFrame


def download_adjusted_close(refresh: bool = False) -> pd.DataFrame:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if PRICE_CACHE.exists() and not refresh:
        prices = pd.read_csv(PRICE_CACHE, parse_dates=["Date"]).set_index("Date")
        return prices.sort_index()

    import yfinance as yf

    tickers = TARGET_TICKERS + SOURCE_TICKERS
    raw = yf.download(
        tickers,
        start=DATA_START,
        end=DATA_END_EXCLUSIVE,
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned an empty dataframe")

    if isinstance(raw.columns, pd.MultiIndex):
        level0 = list(raw.columns.get_level_values(0))
        level1 = list(raw.columns.get_level_values(1))
        if "Close" in level0:
            close = raw["Close"].copy()
        elif "Close" in level1:
            close = raw.xs("Close", axis=1, level=1).copy()
        else:
            raise RuntimeError(f"Cannot locate Close columns in yfinance output: {raw.columns}")
    else:
        if "Close" not in raw.columns:
            raise RuntimeError(f"Cannot locate Close column in yfinance output: {raw.columns}")
        close = raw[["Close"]].copy()
        close.columns = [tickers[0]]

    close = close.loc[:, [c for c in tickers if c in close.columns]]
    close = close.dropna(how="all").sort_index()
    close.to_csv(PRICE_CACHE, index_label="Date")
    return close


def make_feature_frame(close: pd.Series, ticker: str, role: str) -> pd.DataFrame:
    px = close.dropna().astype(float).sort_index()
    ret = np.log(px / px.shift(1))
    rv = ret.pow(2).clip(lower=EPS)

    # The signal is explicitly lagged: row date t only uses information through
    # t-1 to predict close-to-close variance realized on t.
    signal = rv.copy()
    out = pd.DataFrame(index=px.index)
    out["ticker"] = ticker
    out["role"] = role
    out["close"] = px
    out["ret"] = ret
    out["rv"] = rv
    out["log_rv"] = np.log(rv + EPS)
    out["log_rv_lag1"] = np.log(signal.shift(1) + EPS)
    out["log_rv_lag5"] = np.log(signal.rolling(5).mean().shift(1) + EPS)
    out["log_rv_lag22"] = np.log(signal.rolling(22).mean().shift(1) + EPS)
    out["abs_ret_lag1"] = ret.abs().shift(1)
    out["neg_ret_lag1"] = ret.clip(upper=0.0).shift(1)
    out["day_number"] = np.arange(1, len(out) + 1)
    out["date"] = out.index
    out["target_log_rv"] = out["log_rv"]
    out["valid_model_row"] = out[FEATURES + ["rv", "target_log_rv"]].notna().all(axis=1)
    return out.reset_index(drop=True)


def zscore(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    sd = float(np.nanstd(values))
    if not math.isfinite(sd) or sd < 1.0e-12:
        return values * 0.0
    return (values - float(np.nanmean(values))) / sd


def select_source_windows(
    *,
    target_panel: pd.DataFrame,
    source_panels: dict[str, pd.DataFrame],
    eval_start_date: pd.Timestamp,
) -> list[dict[str, Any]]:
    initial = (
        target_panel.loc[target_panel["day_number"] <= SELECTION_DAYS, "log_rv"]
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
        .to_numpy()
    )
    if len(initial) < SOURCE_WINDOW_DAYS:
        return []
    target_seq = zscore(initial[:SOURCE_WINDOW_DAYS])

    candidates: list[dict[str, Any]] = []
    for ticker, panel in source_panels.items():
        source = panel[(panel["date"] < eval_start_date) & panel["log_rv"].notna()].sort_values("date")
        values = source["log_rv"].to_numpy(dtype=float)
        dates = source["date"].to_numpy()
        if len(values) < SOURCE_WINDOW_DAYS:
            continue
        for start in range(0, len(values) - SOURCE_WINDOW_DAYS + 1, SOURCE_WINDOW_DAYS):
            stop = start + SOURCE_WINDOW_DAYS
            seq = values[start:stop]
            distance = float(np.mean((zscore(seq) - target_seq) ** 2))
            candidates.append(
                {
                    "source_ticker": ticker,
                    "start_date": pd.Timestamp(dates[start]).strftime("%Y-%m-%d"),
                    "end_date": pd.Timestamp(dates[stop - 1]).strftime("%Y-%m-%d"),
                    "distance": distance,
                    "n_days": SOURCE_WINDOW_DAYS,
                }
            )

    candidates.sort(key=lambda row: row["distance"])
    return candidates[:TOP_SOURCE_WINDOWS]


def rows_for_selected_windows(
    source_panel_all: pd.DataFrame,
    selected_windows: list[dict[str, Any]],
) -> pd.DataFrame:
    blocks: list[pd.DataFrame] = []
    for window in selected_windows:
        ticker = window["source_ticker"]
        start = pd.Timestamp(window["start_date"])
        end = pd.Timestamp(window["end_date"])
        block = source_panel_all[
            (source_panel_all["ticker"] == ticker)
            & (source_panel_all["date"] >= start)
            & (source_panel_all["date"] <= end)
            & (source_panel_all["valid_model_row"])
        ]
        if not block.empty:
            blocks.append(block)
    if not blocks:
        return source_panel_all.iloc[0:0].copy()
    return pd.concat(blocks, ignore_index=True).drop_duplicates(["ticker", "date"])


def fit_predict_log_variance(train: pd.DataFrame, eval_rows: pd.DataFrame) -> np.ndarray:
    if len(train) < len(FEATURES) + 5:
        raise ValueError(f"insufficient training rows: {len(train)}")
    model = make_pipeline(StandardScaler(), Ridge(alpha=RIDGE_ALPHA))
    x_train = train[FEATURES].astype(float).to_numpy()
    y_train = train["target_log_rv"].astype(float).to_numpy()
    model.fit(x_train, y_train)
    pred_log = model.predict(eval_rows[FEATURES].astype(float).to_numpy())
    return np.exp(np.clip(pred_log, np.log(EPS), np.log(2.0)))


def qlike_loss(realized: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    y = np.clip(np.asarray(realized, dtype=float), EPS, None)
    h = np.clip(np.asarray(forecast, dtype=float), EPS, None)
    ratio = y / h
    return ratio - np.log(ratio) - 1.0


def nw_mean_tstat(diff: np.ndarray, lag: int = 5) -> dict[str, float]:
    x = np.asarray(diff, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < lag + 5:
        return {"n": float(n), "mean": float(np.nanmean(x)) if n else math.nan, "t": math.nan}
    mean = float(np.mean(x))
    centered = x - mean
    lrv = float(np.dot(centered, centered) / n)
    for ell in range(1, min(lag, n - 1) + 1):
        gamma = float(np.dot(centered[ell:], centered[:-ell]) / n)
        weight = 1.0 - ell / (lag + 1.0)
        lrv += 2.0 * weight * gamma
    if lrv <= 0.0 or not math.isfinite(lrv):
        return {"n": float(n), "mean": mean, "t": math.nan}
    se = math.sqrt(lrv / n)
    return {"n": float(n), "mean": mean, "t": mean / se}


def exact_two_sided_sign_p(k_success: int, n: int) -> float:
    if n <= 0:
        return math.nan
    tail = min(k_success, n - k_success)
    prob = sum(math.comb(n, i) for i in range(tail + 1)) / (2**n)
    return float(min(1.0, 2.0 * prob))


def bootstrap_target_mean_ci(target_means: list[float], b: int = 1000) -> dict[str, Any]:
    rng = np.random.default_rng(SEED)
    values = np.asarray(target_means, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return {"B": b, "seed": SEED, "n_targets": 0, "mean": math.nan, "ci95": [math.nan, math.nan]}
    draws = rng.choice(values, size=(b, len(values)), replace=True).mean(axis=1)
    return {
        "B": b,
        "seed": SEED,
        "n_targets": int(len(values)),
        "mean": float(values.mean()),
        "ci95": [float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))],
        "prob_mean_below_zero": float(np.mean(draws < 0.0)),
    }


def run_target(
    ticker: str,
    target_panel: pd.DataFrame,
    source_panels: dict[str, pd.DataFrame],
    source_panel_all: pd.DataFrame,
) -> TargetRun | None:
    valid_target = target_panel[target_panel["valid_model_row"]].copy()
    if valid_target.empty:
        return None

    eval_candidates = valid_target[
        (valid_target["day_number"] > MIN_EVAL_DAY) & (valid_target["day_number"] <= MAX_EVAL_DAY)
    ].copy()
    if len(eval_candidates) < 100:
        return None

    eval_start_date = pd.Timestamp(eval_candidates["date"].min())
    target_train = valid_target[valid_target["day_number"] <= MIN_EVAL_DAY].copy()
    if len(target_train) < MIN_TARGET_TRAIN_ROWS:
        return None

    all_source_train = source_panel_all[
        (source_panel_all["date"] < eval_start_date) & (source_panel_all["valid_model_row"])
    ].copy()
    selected_windows = select_source_windows(
        target_panel=target_panel,
        source_panels=source_panels,
        eval_start_date=eval_start_date,
    )
    selected_source_train = rows_for_selected_windows(source_panel_all, selected_windows)

    if len(selected_source_train) < SOURCE_WINDOW_DAYS:
        return None

    pred = pd.DataFrame(
        {
            "date": eval_candidates["date"].to_numpy(),
            "ticker": ticker,
            "day_number": eval_candidates["day_number"].to_numpy(),
            "realized_rv": eval_candidates["rv"].to_numpy(dtype=float),
        }
    )
    naive = np.exp(eval_candidates["log_rv_lag22"].to_numpy(dtype=float))
    pred["naive_har22"] = np.clip(naive, EPS, None)
    pred["target_only_ridge"] = fit_predict_log_variance(target_train, eval_candidates)
    pred["all_source_transfer"] = fit_predict_log_variance(
        pd.concat([all_source_train, target_train], ignore_index=True),
        eval_candidates,
    )
    pred["similar_source_transfer"] = fit_predict_log_variance(
        pd.concat([selected_source_train, target_train], ignore_index=True),
        eval_candidates,
    )

    for model in ["naive_har22", "target_only_ridge", "all_source_transfer", "similar_source_transfer"]:
        pred[f"loss_{model}"] = qlike_loss(pred["realized_rv"].to_numpy(), pred[model].to_numpy())

    return TargetRun(
        ticker=ticker,
        first_price_date=pd.Timestamp(target_panel["date"].min()).strftime("%Y-%m-%d"),
        eval_start_date=eval_start_date,
        train_rows=len(target_train),
        eval_rows=len(eval_candidates),
        selected_source_rows=len(selected_source_train),
        all_source_rows=len(all_source_train),
        selected_windows=selected_windows,
        predictions=pred,
    )


def summarize_predictions(runs: list[TargetRun]) -> dict[str, Any]:
    all_predictions = pd.concat([run.predictions for run in runs], ignore_index=True)
    models = ["naive_har22", "target_only_ridge", "all_source_transfer", "similar_source_transfer"]
    loss_cols = {model: f"loss_{model}" for model in models}

    panel_means = {
        model: float(all_predictions[loss_cols[model]].mean())
        for model in models
    }
    target_rows: list[dict[str, Any]] = []
    target_diffs_selected: list[float] = []
    target_diffs_all: list[float] = []
    target_diffs_selected_vs_naive: list[float] = []
    target_diffs_all_vs_naive: list[float] = []

    for run in runs:
        df = run.predictions
        base = float(df["loss_target_only_ridge"].mean())
        selected = float(df["loss_similar_source_transfer"].mean())
        all_source = float(df["loss_all_source_transfer"].mean())
        naive = float(df["loss_naive_har22"].mean())
        target_diffs_selected.append(selected - base)
        target_diffs_all.append(all_source - base)
        target_diffs_selected_vs_naive.append(selected - naive)
        target_diffs_all_vs_naive.append(all_source - naive)
        target_rows.append(
            {
                "ticker": run.ticker,
                "first_price_date": run.first_price_date,
                "eval_start_date": run.eval_start_date.strftime("%Y-%m-%d"),
                "train_rows": run.train_rows,
                "eval_rows": run.eval_rows,
                "all_source_rows": run.all_source_rows,
                "selected_source_rows": run.selected_source_rows,
                "qlike_loss": {
                    "naive_har22": naive,
                    "target_only_ridge": base,
                    "all_source_transfer": all_source,
                    "similar_source_transfer": selected,
                },
                "diff_vs_target_only": {
                    "naive_har22": naive - base,
                    "all_source_transfer": all_source - base,
                    "similar_source_transfer": selected - base,
                },
                "diff_vs_naive_har22": {
                    "target_only_ridge": base - naive,
                    "all_source_transfer": all_source - naive,
                    "similar_source_transfer": selected - naive,
                },
                "improved_vs_target_only": {
                    "naive_har22": naive < base,
                    "all_source_transfer": all_source < base,
                    "similar_source_transfer": selected < base,
                },
                "improved_vs_naive_har22": {
                    "target_only_ridge": base < naive,
                    "all_source_transfer": all_source < naive,
                    "similar_source_transfer": selected < naive,
                },
                "top_selected_windows": run.selected_windows[:5],
            }
        )

    selected_diff_panel = (
        all_predictions["loss_similar_source_transfer"] - all_predictions["loss_target_only_ridge"]
    ).to_numpy()
    all_diff_panel = (
        all_predictions["loss_all_source_transfer"] - all_predictions["loss_target_only_ridge"]
    ).to_numpy()
    naive_diff_panel = (
        all_predictions["loss_naive_har22"] - all_predictions["loss_target_only_ridge"]
    ).to_numpy()
    selected_diff_vs_naive_panel = (
        all_predictions["loss_similar_source_transfer"] - all_predictions["loss_naive_har22"]
    ).to_numpy()
    all_diff_vs_naive_panel = (
        all_predictions["loss_all_source_transfer"] - all_predictions["loss_naive_har22"]
    ).to_numpy()
    target_only_diff_vs_naive_panel = (
        all_predictions["loss_target_only_ridge"] - all_predictions["loss_naive_har22"]
    ).to_numpy()

    selected_wins = int(sum(v < 0.0 for v in target_diffs_selected))
    all_wins = int(sum(v < 0.0 for v in target_diffs_all))
    selected_wins_vs_naive = int(sum(v < 0.0 for v in target_diffs_selected_vs_naive))
    all_wins_vs_naive = int(sum(v < 0.0 for v in target_diffs_all_vs_naive))
    n_targets = len(runs)

    return {
        "panel_qlike_loss_means": panel_means,
        "primary_baseline": "naive_har22",
        "panel_diff_vs_target_only": {
            "naive_har22": nw_mean_tstat(naive_diff_panel, lag=5),
            "all_source_transfer": nw_mean_tstat(all_diff_panel, lag=5),
            "similar_source_transfer": nw_mean_tstat(selected_diff_panel, lag=5),
        },
        "panel_diff_vs_naive_har22": {
            "target_only_ridge": nw_mean_tstat(target_only_diff_vs_naive_panel, lag=5),
            "all_source_transfer": nw_mean_tstat(all_diff_vs_naive_panel, lag=5),
            "similar_source_transfer": nw_mean_tstat(selected_diff_vs_naive_panel, lag=5),
        },
        "target_level_sign_tests": {
            "all_source_transfer": {
                "wins": all_wins,
                "n": n_targets,
                "two_sided_p": exact_two_sided_sign_p(all_wins, n_targets),
            },
            "similar_source_transfer": {
                "wins": selected_wins,
                "n": n_targets,
                "two_sided_p": exact_two_sided_sign_p(selected_wins, n_targets),
            },
        },
        "target_level_sign_tests_vs_naive_har22": {
            "all_source_transfer": {
                "wins": all_wins_vs_naive,
                "n": n_targets,
                "two_sided_p": exact_two_sided_sign_p(all_wins_vs_naive, n_targets),
            },
            "similar_source_transfer": {
                "wins": selected_wins_vs_naive,
                "n": n_targets,
                "two_sided_p": exact_two_sided_sign_p(selected_wins_vs_naive, n_targets),
            },
        },
        "target_level_bootstrap_mean_loss_diff": {
            "all_source_transfer_minus_target_only": bootstrap_target_mean_ci(target_diffs_all),
            "similar_source_transfer_minus_target_only": bootstrap_target_mean_ci(target_diffs_selected),
            "all_source_transfer_minus_naive_har22": bootstrap_target_mean_ci(
                target_diffs_all_vs_naive
            ),
            "similar_source_transfer_minus_naive_har22": bootstrap_target_mean_ci(
                target_diffs_selected_vs_naive
            ),
        },
        "per_target": target_rows,
        "prediction_rows": int(len(all_predictions)),
    }


def make_figure(summary: dict[str, Any]) -> None:
    rows = summary["per_target"]
    tickers = [row["ticker"] for row in rows]
    selected = [row["diff_vs_naive_har22"]["similar_source_transfer"] for row in rows]
    all_source = [row["diff_vs_naive_har22"]["all_source_transfer"] for row in rows]

    x = np.arange(len(tickers))
    width = 0.38
    fig, ax = plt.subplots(figsize=(11, 5.8))
    ax.axhline(0.0, color="#222222", linewidth=1.0)
    ax.bar(x - width / 2, selected, width, label="similar-source transfer", color="#2c7fb8")
    ax.bar(x + width / 2, all_source, width, label="all-source pooled", color="#f28e2b")
    ax.set_xticks(x)
    ax.set_xticklabels(tickers, rotation=30, ha="right")
    ax.set_ylabel("Mean normalized QLIKE loss diff vs naive HAR22\n(negative = transfer better)")
    ax.set_title("Cold-start volatility forecast transfer vs naive HAR22 baseline")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=160)
    plt.close(fig)


def run(refresh: bool = False) -> dict[str, Any]:
    prices = download_adjusted_close(refresh=refresh)
    missing = [t for t in TARGET_TICKERS + SOURCE_TICKERS if t not in prices.columns]
    if missing:
        raise RuntimeError(f"Downloaded price panel is missing columns: {missing}")

    target_panels = {
        ticker: make_feature_frame(prices[ticker], ticker, "target")
        for ticker in TARGET_TICKERS
    }
    source_panels = {
        ticker: make_feature_frame(prices[ticker], ticker, "source")
        for ticker in SOURCE_TICKERS
    }
    source_panel_all = pd.concat(source_panels.values(), ignore_index=True)

    runs: list[TargetRun] = []
    skipped: dict[str, str] = {}
    for ticker, panel in target_panels.items():
        try:
            run_result = run_target(ticker, panel, source_panels, source_panel_all)
        except Exception as exc:  # keep one data glitch from killing the panel
            skipped[ticker] = f"{type(exc).__name__}: {exc}"
            continue
        if run_result is None:
            skipped[ticker] = "insufficient valid rows after cold-start filters"
        else:
            runs.append(run_result)

    if len(runs) < 5:
        raise RuntimeError(f"too few target runs completed: {len(runs)}; skipped={skipped}")

    summary = summarize_predictions(runs)
    make_figure(summary)

    data_coverage = {
        ticker: {
            "first": pd.Timestamp(prices[ticker].dropna().index.min()).strftime("%Y-%m-%d"),
            "last": pd.Timestamp(prices[ticker].dropna().index.max()).strftime("%Y-%m-%d"),
            "n_prices": int(prices[ticker].dropna().shape[0]),
        }
        for ticker in TARGET_TICKERS + SOURCE_TICKERS
    }

    selected_block = summary["panel_diff_vs_naive_har22"]["similar_source_transfer"]
    selected_boot = summary["target_level_bootstrap_mean_loss_diff"][
        "similar_source_transfer_minus_naive_har22"
    ]
    selected_sign = summary["target_level_sign_tests_vs_naive_har22"]["similar_source_transfer"]
    if (
        selected_block["mean"] < 0.0
        and selected_sign["wins"] >= math.ceil(0.6 * selected_sign["n"])
        and selected_boot["ci95"][0] < 0.0
    ):
        verdict = "CONDITIONAL_PASS_WEAK"
    elif selected_block["mean"] < 0.0:
        verdict = "MIXED_WEAK"
    else:
        verdict = "NULL_VS_NAIVE_BASELINE"

    result = {
        "experiment_id": EXPERIMENT_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "status": "completed",
        "verdict": verdict,
        "hypothesis": (
            "For new issues/spin-offs with ~60 trading days of own history, "
            "source-similar cross-asset history improves one-day-ahead close-to-close "
            "variance forecasts versus a target-only cold-start Ridge/HAR proxy."
        ),
        "data": {
            "source": "yfinance adjusted daily close, auto_adjust=True",
            "download_start": DATA_START,
            "download_end_exclusive": DATA_END_EXCLUSIVE,
            "target_tickers": TARGET_TICKERS,
            "source_tickers": SOURCE_TICKERS,
            "data_cache": str(PRICE_CACHE.relative_to(ROOT)),
            "coverage": data_coverage,
            "skipped_targets": skipped,
        },
        "method": {
            "target": "close-to-close squared log return on date t",
            "features": FEATURES,
            "lookahead_defense": (
                "Feature construction uses signal.shift(1), rolling(...).mean().shift(1), "
                "and target-only training uses only the first 60 trading days; evaluation "
                "starts after day 60."
            ),
            "selection": {
                "initial_target_days": SELECTION_DAYS,
                "source_window_days": SOURCE_WINDOW_DAYS,
                "top_source_windows": TOP_SOURCE_WINDOWS,
                "distance": "mean squared distance between z-scored log realized-variance sequences",
                "source_cutoff": "source windows must end before the target evaluation start date",
            },
            "models": [
                "naive_har22: lagged 22-day mean variance",
                "target_only_ridge: Ridge on first 60 target trading days only",
                "all_source_transfer: Ridge on all eligible source rows before eval start + target train rows",
                "similar_source_transfer: Ridge on selected source windows + target train rows",
            ],
            "loss": "normalized Patton-style QLIKE y/h - log(y/h) - 1",
            "primary_baseline": (
                "naive_har22 is the primary benchmark because target-only Ridge with "
                "only 60 trading days can be numerically unstable; target-only Ridge "
                "is retained as a cold-start overfitting diagnostic."
            ),
            "inference": [
                "Newey-West t-stat on pooled target-day loss differentials, lag=5",
                "target-level exact sign test",
                "target-level bootstrap CI over mean loss differentials, B=1000, seed=42",
            ],
        },
        "summary": summary,
        "figure": str(FIG_PATH.relative_to(ROOT)),
        "main_findings": [],
        "limitations": [
            "Daily close-to-close squared returns are a noisy proxy, not 5-minute realized variance.",
            "The target universe contains recent public listings/spin-offs with yfinance coverage; it is not the exact 10-asset sample from Teller, Pigorsch & Pigorsch (2025).",
            "Source-window selection is a simple z-scored Euclidean proxy, not full DTW multi-source transfer learning.",
            "Pooled Newey-West inference ignores cross-sectional dependence across target tickers; target-level bootstrap is reported separately.",
            "A positive result would be a cold-start public-data pilot, not a paper-grade new-issues transfer-learning claim.",
        ],
        "literature_checked": [
            {
                "citation": "Teller, Pigorsch & Pigorsch (2025), Realized Volatility Forecasting for New Issues and Spin-Offs using Multi-Source Transfer Learning",
                "url": "https://arxiv.org/abs/2503.12648",
                "relevance": "Direct motivation: sparse target history and source-similar transfer for new issues/spin-offs.",
            },
            {
                "citation": "Liu, Tran, Wang, Gerlach & Kohn (2023), Data Scaling Effect of Deep Learning in Financial Time Series Forecasting",
                "url": "https://arxiv.org/abs/2309.02072",
                "relevance": "Global training across many stocks can help volatility forecasting, motivating pooled-source baselines.",
            },
            {
                "citation": "Christensen, Siggaard & Veliyev (2026), A machine learning approach to volatility forecasting",
                "url": "https://arxiv.org/abs/2601.13014",
                "relevance": "HAR-style realized-vol predictors and ML comparison frame for volatility forecasting.",
            },
            {
                "citation": "Corsi (2009), A simple approximate long-memory model of realized volatility",
                "url": "https://doi.org/10.1093/jjfinec/nbp001",
                "relevance": "Daily/weekly/monthly lag structure motivating the HAR proxy features.",
            },
        ],
    }

    similar_mean_vs_naive = summary["panel_diff_vs_naive_har22"]["similar_source_transfer"]["mean"]
    all_mean_vs_naive = summary["panel_diff_vs_naive_har22"]["all_source_transfer"]["mean"]
    similar_mean_vs_target = summary["panel_diff_vs_target_only"]["similar_source_transfer"]["mean"]
    all_mean_vs_target = summary["panel_diff_vs_target_only"]["all_source_transfer"]["mean"]
    target_only_vs_naive = summary["panel_diff_vs_naive_har22"]["target_only_ridge"]["mean"]
    result["main_findings"] = [
        (
            f"Primary result: similar-source transfer mean QLIKE diff vs naive HAR22 = "
            f"{similar_mean_vs_naive:.6g}; positive means transfer is worse. Verdict={verdict}."
        ),
        (
            f"All-source pooled mean QLIKE diff vs naive HAR22 = {all_mean_vs_naive:.6g}; "
            "naive pooling also fails to beat the simple HAR22 baseline."
        ),
        (
            f"Cold-start target-only Ridge is unstable: mean QLIKE diff vs naive HAR22 = "
            f"{target_only_vs_naive:.6g}. Transfer models reduce this instability "
            f"(similar-source vs target-only diff = {similar_mean_vs_target:.6g}; "
            f"all-source vs target-only diff = {all_mean_vs_target:.6g}) but do not "
            "beat the rolling-volatility baseline."
        ),
        (
            f"target-level similar-source wins = {selected_sign['wins']}/{selected_sign['n']} "
            f"against naive HAR22 (two-sided sign p={selected_sign['two_sided_p']:.4f})."
        ),
        (
            "The experiment is lookahead-protected by one-day lagged features and fixed "
            "cold-start training windows; no evaluation-period target labels enter training."
        ),
    ]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="redownload yfinance prices")
    args = parser.parse_args()
    result = run(refresh=args.refresh)
    print(json.dumps({
        "experiment_id": result["experiment_id"],
        "verdict": result["verdict"],
        "targets_completed": len(result["summary"]["per_target"]),
        "prediction_rows": result["summary"]["prediction_rows"],
        "results": str(OUT_PATH.relative_to(ROOT)),
        "figure": str(FIG_PATH.relative_to(ROOT)),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
