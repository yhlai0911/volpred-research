#!/usr/bin/env python3
"""Quantum-reservoir reproducibility gate via a classical echo-state proxy.

The queued paper proposes quantum reservoir computing (QRC) for realized
volatility forecasting. This experiment does not simulate qubits. It asks a
more modest reproducibility question: if the quantum reservoir is replaced by a
transparent fixed classical reservoir, does the reservoir idea itself beat
strong lagged-volatility baselines on a daily public-data proxy?
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


EXPERIMENT_ID = "research_quantum_reservoir_computing_for_realized_volatil"
OUT_DIR = ROOT / "experiments" / EXPERIMENT_ID
DATA_DIR = OUT_DIR / "data"
PRICE_CACHE = DATA_DIR / "adjusted_close_yfinance.csv"
OUT_PATH = OUT_DIR / f"{EXPERIMENT_ID}_results.json"
FIG_PATH = OUT_DIR / f"{EXPERIMENT_ID}_qlike_improvement.png"

SEED = 42
DATA_START = "2010-01-01"
DATA_END_EXCLUSIVE = "2026-07-02"
OOS_START = pd.Timestamp("2019-01-02")
EPS = 1.0e-10

TICKERS = ["SPY", "QQQ", "IWM", "GLD", "TLT", "HYG", "EEM", "USO"]
FEATURES = [
    "log_rv_lag1",
    "log_rv_lag5",
    "log_rv_lag22",
    "abs_ret_lag1",
    "neg_ret_lag1",
    "ret_lag1",
]
HAR_FEATURES = ["log_rv_lag1", "log_rv_lag5", "log_rv_lag22"]

RESERVOIR_DIM = 96
RANDOM_FEATURE_DIM = 96
SPECTRAL_RADIUS = 0.85
SPARSITY = 0.12
INPUT_SCALE = 0.45
LEAK_RATE = 0.35
RIDGE_ALPHA = 5.0
RANDOM_FEATURE_ALPHA = 5.0
RESERVOIR_ALPHA = 20.0
RESERVOIR_SEEDS = [7, 11, 23, 42, 73, 101, 131, 173]
BOOTSTRAP_REPS = 1000


@dataclass(frozen=True)
class AssetResult:
    ticker: str
    train_start: str
    train_end: str
    oos_start: str
    oos_end: str
    train_rows: int
    oos_rows: int
    calibration_factors: dict[str, float]
    qlike: dict[str, float]
    dm_vs_naive_har22: dict[str, dict[str, float]]
    dm_vs_linear_har: dict[str, dict[str, float]]
    dm_vs_linear_harx: dict[str, dict[str, float]]
    reservoir_seed_qlike: dict[str, float]
    reservoir_wins_vs_naive_har22: dict[str, bool]


def download_adjusted_close(refresh: bool = False) -> pd.DataFrame:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if PRICE_CACHE.exists() and not refresh:
        return pd.read_csv(PRICE_CACHE, parse_dates=["Date"]).set_index("Date").sort_index()

    import yfinance as yf

    raw = yf.download(
        TICKERS,
        start=DATA_START,
        end=DATA_END_EXCLUSIVE,
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned an empty dataframe")

    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(0):
            close = raw["Close"].copy()
        elif "Close" in raw.columns.get_level_values(1):
            close = raw.xs("Close", axis=1, level=1).copy()
        else:
            raise RuntimeError(f"Cannot locate Close columns: {raw.columns}")
    else:
        close = raw[["Close"]].copy()
        close.columns = [TICKERS[0]]

    close = close.loc[:, [ticker for ticker in TICKERS if ticker in close.columns]]
    close = close.dropna(how="all").sort_index()
    close.to_csv(PRICE_CACHE, index_label="Date")
    return close


def make_feature_frame(close: pd.Series) -> pd.DataFrame:
    px = close.dropna().astype(float).sort_index()
    ret = np.log(px / px.shift(1))
    rv = ret.pow(2).clip(lower=EPS)

    # The signal is explicitly lagged: row t uses information through t-1 only.
    signal = rv.copy()
    out = pd.DataFrame(index=px.index)
    out["close"] = px
    out["ret"] = ret
    out["rv"] = rv
    out["log_rv"] = np.log(rv + EPS)
    out["log_rv_lag1"] = np.log(signal.shift(1) + EPS)
    out["log_rv_lag5"] = np.log(signal.rolling(5).mean().shift(1) + EPS)
    out["log_rv_lag22"] = np.log(signal.rolling(22).mean().shift(1) + EPS)
    out["abs_ret_lag1"] = ret.abs().shift(1)
    out["neg_ret_lag1"] = (-ret.clip(upper=0.0)).shift(1)
    out["ret_lag1"] = ret.shift(1)
    out["target_log_rv"] = out["log_rv"]
    out["naive_har22"] = signal.rolling(22).mean().shift(1).clip(lower=EPS)
    out["date"] = out.index
    out = out.reset_index(drop=True)
    valid = out[FEATURES + ["target_log_rv", "rv", "naive_har22"]].notna().all(axis=1)
    return out.loc[valid].reset_index(drop=True)


def standardize_by_train(panel: pd.DataFrame, train_mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = panel[FEATURES].astype(float).to_numpy()
    mean = x[train_mask].mean(axis=0)
    sd = x[train_mask].std(axis=0)
    sd = np.where(sd < 1.0e-12, 1.0, sd)
    return (x - mean) / sd, mean, sd


def fit_log_ridge(x_train: np.ndarray, y_train: np.ndarray, x_all: np.ndarray, alpha: float) -> np.ndarray:
    model = Ridge(alpha=alpha)
    model.fit(x_train, y_train)
    pred_log = model.predict(x_all)
    return np.exp(np.clip(pred_log, np.log(EPS), np.log(0.25)))


def qlike_scalar_calibrate(
    actual: np.ndarray,
    predicted: np.ndarray,
    train_mask: np.ndarray,
) -> tuple[np.ndarray, float]:
    """Train-only scalar calibration for QLIKE on variance forecasts.

    For loss a/(c f) - log(a/(c f)) - 1, the train optimum is
    c = mean(a/f). The factor is estimated only on the training window.
    """
    pred = np.maximum(np.asarray(predicted, dtype=float), EPS)
    actual = np.maximum(np.asarray(actual, dtype=float), EPS)
    valid = train_mask & np.isfinite(actual) & np.isfinite(pred) & (pred > 0)
    if valid.sum() < 50:
        return pred, 1.0
    factor = float(np.mean(actual[valid] / pred[valid]))
    if not math.isfinite(factor):
        factor = 1.0
    factor = float(np.clip(factor, 0.02, 50.0))
    return np.maximum(pred * factor, EPS), factor


def random_feature_forecast(
    x_std: np.ndarray,
    y: np.ndarray,
    train_mask: np.ndarray,
    seed: int,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    w = rng.normal(0.0, 1.0 / math.sqrt(x_std.shape[1]), size=(x_std.shape[1], RANDOM_FEATURE_DIM))
    b = rng.normal(0.0, 0.35, size=RANDOM_FEATURE_DIM)
    z = np.tanh(x_std @ w + b)
    design = np.column_stack([x_std, z])
    return fit_log_ridge(design[train_mask], y[train_mask], design, RANDOM_FEATURE_ALPHA)


def make_sparse_reservoir(seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    w_res = rng.normal(0.0, 1.0, size=(RESERVOIR_DIM, RESERVOIR_DIM))
    mask = rng.random(size=w_res.shape) < SPARSITY
    w_res = w_res * mask
    eigvals = np.linalg.eigvals(w_res)
    radius = float(np.max(np.abs(eigvals)))
    if radius > 1.0e-12:
        w_res = w_res * (SPECTRAL_RADIUS / radius)
    w_in = rng.normal(0.0, INPUT_SCALE, size=(RESERVOIR_DIM, len(FEATURES)))
    bias = rng.normal(0.0, 0.05, size=RESERVOIR_DIM)
    return w_res, w_in, bias


def reservoir_states(x_std: np.ndarray, seed: int) -> np.ndarray:
    w_res, w_in, bias = make_sparse_reservoir(seed)
    states = np.zeros((len(x_std), RESERVOIR_DIM), dtype=float)
    state = np.zeros(RESERVOIR_DIM, dtype=float)
    for idx, row in enumerate(x_std):
        proposal = np.tanh(w_res @ state + w_in @ row + bias)
        state = (1.0 - LEAK_RATE) * state + LEAK_RATE * proposal
        states[idx] = state
    return states


def reservoir_forecast(
    x_std: np.ndarray,
    y: np.ndarray,
    train_mask: np.ndarray,
    seed: int,
) -> np.ndarray:
    states = reservoir_states(x_std, seed)
    design = np.column_stack([x_std, states])
    return fit_log_ridge(design[train_mask], y[train_mask], design, RESERVOIR_ALPHA)


def asset_backtest(ticker: str, close: pd.Series) -> AssetResult:
    panel = make_feature_frame(close)
    train_mask = (panel["date"] < OOS_START).to_numpy()
    oos_mask = (panel["date"] >= OOS_START).to_numpy()
    if train_mask.sum() < 750 or oos_mask.sum() < 252:
        raise RuntimeError(f"{ticker}: insufficient train/OOS rows")

    y = panel["target_log_rv"].astype(float).to_numpy()
    actual = panel["rv"].astype(float).to_numpy()
    x_std, _, _ = standardize_by_train(panel, train_mask)

    har_idx = [FEATURES.index(name) for name in HAR_FEATURES]
    linear_har = fit_log_ridge(
        x_std[train_mask][:, har_idx],
        y[train_mask],
        x_std[:, har_idx],
        RIDGE_ALPHA,
    )
    linear_harx = fit_log_ridge(x_std[train_mask], y[train_mask], x_std, RIDGE_ALPHA)
    random_features = random_feature_forecast(x_std, y, train_mask, seed=SEED)

    reservoir_preds: dict[int, np.ndarray] = {}
    for seed in RESERVOIR_SEEDS:
        reservoir_preds[seed] = reservoir_forecast(x_std, y, train_mask, seed=seed)

    reservoir_stack = np.vstack([reservoir_preds[seed] for seed in RESERVOIR_SEEDS])
    reservoir_median = np.median(reservoir_stack, axis=0)

    predictions = {
        "naive_har22": panel["naive_har22"].astype(float).to_numpy(),
        "linear_har": linear_har,
        "linear_harx": linear_harx,
        "random_features": random_features,
        "reservoir_seed42": reservoir_preds[SEED],
        "reservoir_seed_median": reservoir_median,
    }
    calibration_factors: dict[str, float] = {}
    for name, pred in list(predictions.items()):
        calibrated, factor = qlike_scalar_calibrate(actual, pred, train_mask)
        predictions[name] = calibrated
        calibration_factors[name] = factor

    qlike_by_model = {
        name: qlike(actual[oos_mask], pred[oos_mask]) for name, pred in predictions.items()
    }
    baseline_loss_naive = qlike_pointwise(actual[oos_mask], predictions["naive_har22"][oos_mask])
    baseline_loss_har = qlike_pointwise(actual[oos_mask], predictions["linear_har"][oos_mask])
    baseline_loss_harx = qlike_pointwise(actual[oos_mask], predictions["linear_harx"][oos_mask])
    dm_vs_naive: dict[str, dict[str, float]] = {}
    dm_vs_har: dict[str, dict[str, float]] = {}
    dm_vs_harx: dict[str, dict[str, float]] = {}
    for name in ["naive_har22", "linear_har", "random_features", "reservoir_seed42", "reservoir_seed_median"]:
        if name != "naive_har22":
            loss = qlike_pointwise(actual[oos_mask], predictions[name][oos_mask])
            t_stat, p_val = dm_test(loss, baseline_loss_naive, h=1)
            dm_vs_naive[name] = {
                "t": t_stat,
                "p": p_val,
                "mean_loss_diff": float(np.mean(loss - baseline_loss_naive)),
            }
        if name != "linear_har":
            loss = qlike_pointwise(actual[oos_mask], predictions[name][oos_mask])
            t_stat, p_val = dm_test(loss, baseline_loss_har, h=1)
            dm_vs_har[name] = {
                "t": t_stat,
                "p": p_val,
                "mean_loss_diff": float(np.mean(loss - baseline_loss_har)),
            }
        if name != "linear_harx":
            loss = qlike_pointwise(actual[oos_mask], predictions[name][oos_mask])
            t_stat, p_val = dm_test(loss, baseline_loss_harx, h=1)
            dm_vs_harx[name] = {
                "t": t_stat,
                "p": p_val,
                "mean_loss_diff": float(np.mean(loss - baseline_loss_harx)),
            }

    seed_qlike = {
        str(seed): qlike(
            actual[oos_mask],
            qlike_scalar_calibrate(actual, reservoir_preds[seed], train_mask)[0][oos_mask],
        )
        for seed in RESERVOIR_SEEDS
    }
    seed_wins = {
        str(seed): bool(seed_qlike[str(seed)] < qlike_by_model["naive_har22"])
        for seed in RESERVOIR_SEEDS
    }

    dates = panel.loc[oos_mask, "date"]
    return AssetResult(
        ticker=ticker,
        train_start=pd.Timestamp(panel.loc[train_mask, "date"].min()).strftime("%Y-%m-%d"),
        train_end=pd.Timestamp(panel.loc[train_mask, "date"].max()).strftime("%Y-%m-%d"),
        oos_start=pd.Timestamp(dates.min()).strftime("%Y-%m-%d"),
        oos_end=pd.Timestamp(dates.max()).strftime("%Y-%m-%d"),
        train_rows=int(train_mask.sum()),
        oos_rows=int(oos_mask.sum()),
        calibration_factors=calibration_factors,
        qlike=qlike_by_model,
        dm_vs_naive_har22=dm_vs_naive,
        dm_vs_linear_har=dm_vs_har,
        dm_vs_linear_harx=dm_vs_harx,
        reservoir_seed_qlike=seed_qlike,
        reservoir_wins_vs_naive_har22=seed_wins,
    )


def bootstrap_asset_mean(diffs: np.ndarray, seed: int = SEED) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    boot = np.empty(BOOTSTRAP_REPS, dtype=float)
    for idx in range(BOOTSTRAP_REPS):
        sample = rng.choice(diffs, size=len(diffs), replace=True)
        boot[idx] = float(np.mean(sample))
    return {
        "B": BOOTSTRAP_REPS,
        "seed": seed,
        "n_assets": int(len(diffs)),
        "mean": float(np.mean(diffs)),
        "ci95": [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))],
        "prob_mean_below_zero": float(np.mean(boot < 0.0)),
    }


def summarize(asset_results: list[AssetResult]) -> dict[str, Any]:
    models = list(asset_results[0].qlike.keys())
    panel_means = {
        model: float(np.mean([asset.qlike[model] for asset in asset_results]))
        for model in models
    }
    primary_baseline = min(
        ["naive_har22", "linear_har", "linear_harx"],
        key=lambda model: panel_means[model],
    )

    def build_diff_block(baseline: str) -> dict[str, dict[str, Any]]:
        block: dict[str, dict[str, Any]] = {}
        for model in models:
            if model == baseline:
                continue
            diffs = np.asarray([asset.qlike[model] - asset.qlike[baseline] for asset in asset_results], dtype=float)
            block[model] = {
                "mean": float(np.mean(diffs)),
                "asset_wins": int(np.sum(diffs < 0.0)),
                "n_assets": int(len(diffs)),
                "bootstrap": bootstrap_asset_mean(diffs),
            }
        return block

    diff_vs_primary = build_diff_block(primary_baseline)
    diff_vs_linear_harx = build_diff_block("linear_harx")

    reservoir_seed_summary = {
        str(seed): {
            "mean_qlike": float(np.mean([asset.reservoir_seed_qlike[str(seed)] for asset in asset_results])),
            "wins_vs_naive_har22": int(
                np.sum([asset.reservoir_wins_vs_naive_har22[str(seed)] for asset in asset_results])
            ),
        }
        for seed in RESERVOIR_SEEDS
    }
    seed_means = np.asarray([v["mean_qlike"] for v in reservoir_seed_summary.values()], dtype=float)

    primary_diff = diff_vs_primary["reservoir_seed_median"]
    if primary_diff["mean"] < 0 and primary_diff["asset_wins"] >= 5 and primary_diff["bootstrap"]["ci95"][1] < 0:
        verdict = "PASS_RESERVOIR_PROXY"
    elif primary_diff["mean"] < 0:
        verdict = "MIXED_WEAK_RESERVOIR_PROXY"
    else:
        verdict = "NULL_VS_PRIMARY_BASELINE"

    return {
        "primary_baseline": primary_baseline,
        "panel_qlike_means": panel_means,
        "diff_vs_primary_baseline": diff_vs_primary,
        "diff_vs_linear_harx": diff_vs_linear_harx,
        "reservoir_seed_summary": reservoir_seed_summary,
        "reservoir_seed_mean_qlike_range": [float(np.min(seed_means)), float(np.max(seed_means))],
        "verdict": verdict,
    }


def make_figure(asset_results: list[AssetResult], summary: dict[str, Any]) -> None:
    models = ["naive_har22", "linear_har", "random_features", "reservoir_seed42", "reservoir_seed_median"]
    fig, axes = plt.subplots(1, 2, figsize=(15, 5.8))

    baseline = summary["primary_baseline"]
    panel_means = summary["panel_qlike_means"]
    rel = {
        model: 100.0 * (panel_means[baseline] - panel_means[model]) / abs(panel_means[baseline])
        for model in models
    }
    labels = {
        "naive_har22": "Naive HAR22",
        "linear_har": "Linear HAR",
        "random_features": "Random features",
        "reservoir_seed42": "ESN seed 42",
        "reservoir_seed_median": "ESN median",
    }
    colors = ["#8a8f98" if rel[m] <= 0 else "#2f7d57" for m in models]
    axes[0].bar([labels[m] for m in models], [rel[m] for m in models], color=colors)
    axes[0].axhline(0, color="black", linewidth=0.9)
    axes[0].set_ylabel("Panel QLIKE improvement vs primary baseline (%)")
    axes[0].set_title("Reservoir proxy vs lagged-volatility baseline")
    axes[0].tick_params(axis="x", rotation=25)

    tickers = [asset.ticker for asset in asset_results]
    diffs = [
        100.0
        * (asset.qlike[baseline] - asset.qlike["reservoir_seed_median"])
        / abs(asset.qlike[baseline])
        for asset in asset_results
    ]
    axes[1].bar(tickers, diffs, color=["#2f7d57" if d > 0 else "#a33f3f" for d in diffs])
    axes[1].axhline(0, color="black", linewidth=0.9)
    axes[1].set_ylabel("Reservoir median improvement vs primary baseline (%)")
    axes[1].set_title("Asset-level seed-median reservoir result")
    axes[1].tick_params(axis="x", rotation=20)

    fig.suptitle("Quantum-reservoir idea gate using a classical echo-state proxy", fontsize=13)
    fig.tight_layout()
    FIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG_PATH, dpi=160)
    plt.close(fig)


def run(refresh: bool = False) -> dict[str, Any]:
    np.random.seed(SEED)
    prices = download_adjusted_close(refresh=refresh)
    asset_results: list[AssetResult] = []
    skipped: dict[str, str] = {}
    for ticker in TICKERS:
        if ticker not in prices.columns:
            skipped[ticker] = "missing_price_column"
            continue
        try:
            asset_results.append(asset_backtest(ticker, prices[ticker]))
        except Exception as exc:  # fail visible in result JSON, not silent
            skipped[ticker] = repr(exc)

    if not asset_results:
        raise RuntimeError("No assets completed")

    summary = summarize(asset_results)
    make_figure(asset_results, summary)

    result = {
        "experiment_id": EXPERIMENT_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "completed",
        "verdict": summary["verdict"],
        "seed": SEED,
        "hypothesis": (
            "A classical echo-state reservoir proxy for QRC should improve one-day-ahead "
            "daily variance forecasts beyond linear HARX if the reservoir mechanism itself "
            "is reproducibly useful without quantum hardware."
        ),
        "literature_checked": [
            "Li, Mukhopadhyay, Bayat, and Habibnia (2025/2026), Quantum Reservoir Computing for Realized Volatility Forecasting, arXiv:2505.13933.",
            "Corsi (2009), A simple approximate long-memory model of realized volatility, Journal of Financial Econometrics.",
            "Jaeger and Haas (2004), Harnessing nonlinearity: predicting chaotic systems and saving energy in wireless communication, Science.",
            "Zhang, Zhang, Cucuringu, and Qian (2022/2024), Volatility forecasting with machine learning and intraday commonality, arXiv:2202.08962.",
        ],
        "data": {
            "source": "yfinance adjusted daily close, auto_adjust=True",
            "download_start": DATA_START,
            "download_end_exclusive": DATA_END_EXCLUSIVE,
            "tickers": TICKERS,
            "data_cache": str(PRICE_CACHE.relative_to(ROOT)),
            "coverage": {
                ticker: {
                    "first": pd.Timestamp(prices[ticker].dropna().index.min()).strftime("%Y-%m-%d"),
                    "last": pd.Timestamp(prices[ticker].dropna().index.max()).strftime("%Y-%m-%d"),
                    "n_prices": int(prices[ticker].dropna().shape[0]),
                }
                for ticker in prices.columns
            },
            "skipped": skipped,
        },
        "method": {
            "target": "same-day close-to-close squared log return r_t^2; all predictors lagged through t-1",
            "proxy_notice": "This is a daily public-data proxy, not the high-frequency realized-volatility target used in the QRC paper.",
            "lookahead_guard": "features use signal.shift(1) and rolling(...).mean().shift(1); train rows date < 2019-01-02; OOS rows date >= 2019-01-02.",
            "models": {
                "naive_har22": "22-day lagged rolling mean variance",
                "linear_har": "Ridge on lagged daily/weekly/monthly log variance",
                "linear_harx": "Ridge on HAR lags plus lagged return/asymmetry features",
                "random_features": "fixed tanh random features plus Ridge readout",
                "reservoir_seed42": "fixed sparse echo-state reservoir plus Ridge readout, seed 42",
                "reservoir_seed_median": "pointwise median forecast across eight fixed reservoir seeds",
            },
            "reservoir": {
                "dim": RESERVOIR_DIM,
                "spectral_radius": SPECTRAL_RADIUS,
                "sparsity": SPARSITY,
                "input_scale": INPUT_SCALE,
                "leak_rate": LEAK_RATE,
                "seeds": RESERVOIR_SEEDS,
            },
            "evaluation": "Patton QLIKE on r^2 after train-only scalar QLIKE calibration for every model; primary gate baseline is the strongest calibrated traditional benchmark among naive_har22, linear_har, and linear_harx; pairwise DM-HAC via volpred.stats.model_evaluation.dm_test; target-level bootstrap B=1000 seed=42.",
        },
        "summary": summary,
        "assets": [asset.__dict__ for asset in asset_results],
        "main_findings": [],
        "limitations": [
            "No quantum Hamiltonian, qubit simulation, measurement noise, or hardware constraint is modeled.",
            "Daily close-to-close squared returns are noisy proxies, not 5-minute realized variance.",
            "Reservoir hyperparameters are fixed ex ante and not tuned; this is a gate, not an optimized ESN study.",
            "Assets are liquid ETFs only; S&P 500 index RV and macro/microstructure feature sets from the QRC paper are not replicated.",
        ],
        "figure": str(FIG_PATH.relative_to(ROOT)),
    }

    primary = summary["diff_vs_primary_baseline"]["reservoir_seed_median"]
    primary_baseline = summary["primary_baseline"]
    if summary["verdict"] == "NULL_VS_PRIMARY_BASELINE":
        result["main_findings"].append(
            f"The classical reservoir proxy does not beat the primary traditional baseline ({primary_baseline}) on panel QLIKE."
        )
    else:
        result["main_findings"].append(
            "The classical reservoir proxy shows a negative mean QLIKE difference vs linear HARX, but the evidence must be interpreted as an ESN proxy, not quantum advantage."
        )
    result["main_findings"].append(
        f"Reservoir seed-median mean QLIKE diff vs {primary_baseline} = {primary['mean']:.6g}, "
        f"asset wins = {primary['asset_wins']}/{primary['n_assets']}, "
        f"bootstrap CI = [{primary['bootstrap']['ci95'][0]:.6g}, {primary['bootstrap']['ci95'][1]:.6g}]."
    )
    result["main_findings"].append(
        "All predictors are lagged; no evaluation-period target labels are used in model fitting."
    )

    OUT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="redownload yfinance prices")
    args = parser.parse_args()
    result = run(refresh=args.refresh)
    print(
        json.dumps(
            {
                "experiment_id": result["experiment_id"],
                "verdict": result["verdict"],
                "assets_completed": len(result["assets"]),
                "panel_qlike_means": result["summary"]["panel_qlike_means"],
                "results": str(OUT_PATH.relative_to(ROOT)),
                "figure": str(FIG_PATH.relative_to(ROOT)),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
