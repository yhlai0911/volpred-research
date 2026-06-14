"""K1328 — HAR ceiling validation with matched-feature ML baselines.

Question:
    Does a well-fitted HAR baseline create a practical forecasting ceiling
    against common ML models once the fitting scheme is tuned?

Honest scope:
    Uses local daily squared-return proxy from experiments/k1206/data/*.csv,
    not 5-min realized variance. The objective is schedule/baseline validation,
    not paper-grade high-frequency replication.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import ElasticNet, LinearRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


SEED = 42
EPS = 1e-12
ASSETS = ["SPY", "QQQ", "GLD", "TLT"]
DATA_DIR = Path("experiments/k1206/data")
OUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUT_DIR / "k1328_results.json"
CHART_PATH = OUT_DIR / "k1328_model_comparison.png"
OOS_START = pd.Timestamp("2021-01-04")
SELECTION_START = pd.Timestamp("2017-01-03")
SELECTION_END = pd.Timestamp("2020-12-31")
MIN_TRAIN = 252


@dataclass(frozen=True)
class Scheme:
    name: str
    window: int | None
    refit_every: int


SCHEMES = [
    Scheme("expanding_refit_1d", None, 1),
    Scheme("expanding_refit_21d", None, 21),
    Scheme("rolling_252_refit_1d", 252, 1),
    Scheme("rolling_252_refit_21d", 252, 21),
    Scheme("rolling_1000_refit_1d", 1000, 1),
    Scheme("rolling_1000_refit_21d", 1000, 21),
]
STAGE_A_SCHEMES = [scheme for scheme in SCHEMES if scheme.refit_every == 21]


def load_asset_frame(asset: str) -> pd.DataFrame:
    path = DATA_DIR / f"{asset}.csv"
    df = pd.read_csv(path, parse_dates=["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    close = df["Close"].astype(float)
    log_ret = np.log(close).diff()
    rv = log_ret.pow(2)
    out = pd.DataFrame({"date": df["Date"], "rv": rv})
    out["rv_lag1"] = out["rv"].shift(1)
    out["rv_mean5"] = out["rv"].shift(1).rolling(5).mean()
    out["rv_mean22"] = out["rv"].shift(1).rolling(22).mean()
    for col in ["rv_lag1", "rv_mean5", "rv_mean22", "rv"]:
        out[f"log_{col}"] = np.log(out[col].clip(lower=EPS))
    out = out.dropna().reset_index(drop=True)
    return out


def build_xy(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = df[["log_rv_lag1", "log_rv_mean5", "log_rv_mean22"]].to_numpy()
    y_log = df["log_rv"].to_numpy()
    y_rv = df["rv"].to_numpy()
    return x, y_log, y_rv


def build_model(model_name: str):
    if model_name == "HAR_OLS":
        return LinearRegression()
    if model_name == "ElasticNet":
        return Pipeline(
            [
                ("scaler", StandardScaler()),
                ("model", ElasticNet(alpha=0.001, l1_ratio=0.2, max_iter=20000, random_state=SEED)),
            ]
        )
    if model_name == "RandomForest":
        return RandomForestRegressor(
            n_estimators=120,
            max_depth=3,
            min_samples_leaf=20,
            random_state=SEED,
            n_jobs=1,
        )
    if model_name == "XGBoost":
        return XGBRegressor(
            objective="reg:squarederror",
            n_estimators=120,
            max_depth=3,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=SEED,
            n_jobs=1,
        )
    raise ValueError(f"Unknown model: {model_name}")


def walk_forward_predict(
    x: np.ndarray,
    y_log: np.ndarray,
    dates: pd.Series,
    scheme: Scheme,
    model_name: str,
    eval_start: pd.Timestamp,
    eval_end: pd.Timestamp | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mask = dates >= eval_start
    if eval_end is not None:
        mask &= dates <= eval_end
    eval_idx = np.flatnonzero(mask.to_numpy())
    if len(eval_idx) == 0:
        raise ValueError("No evaluation observations found.")
    eval_start_idx = int(eval_idx[0])
    eval_end_idx = int(eval_idx[-1])
    preds = np.full(len(x), np.nan)
    refit_counter = 0
    model = None

    for t in range(eval_start_idx, eval_end_idx + 1):
        if scheme.window is None:
            train_start = 0
        else:
            train_start = max(0, t - scheme.window)
        train_end = t
        if train_end - train_start < MIN_TRAIN:
            continue
        if model is None or refit_counter % scheme.refit_every == 0:
            model = build_model(model_name)
            model.fit(x[train_start:train_end], y_log[train_start:train_end])
        pred_log = float(model.predict(x[t : t + 1])[0])
        preds[t] = np.exp(pred_log)
        refit_counter += 1

    valid = np.isfinite(preds)
    return preds[valid], valid, np.flatnonzero(valid)


def summarize_scheme(stage_a: dict[str, dict[str, dict]]) -> dict[str, float]:
    means = {}
    for scheme_name in stage_a:
        qlikes = [stage_a[scheme_name][asset]["qlike"] for asset in ASSETS]
        means[scheme_name] = float(np.mean(qlikes))
    return means


def run_stage_a(asset_frames: dict[str, pd.DataFrame]) -> tuple[dict, Scheme]:
    stage_a: dict[str, dict[str, dict]] = {}
    for scheme in STAGE_A_SCHEMES:
        stage_a[scheme.name] = {}
        for asset, df in asset_frames.items():
            x, y_log, y_rv = build_xy(df)
            preds, _, valid_idx = walk_forward_predict(
                x,
                y_log,
                df["date"],
                scheme,
                "HAR_OLS",
                eval_start=SELECTION_START,
                eval_end=SELECTION_END,
            )
            actual = y_rv[valid_idx]
            stage_a[scheme.name][asset] = {
                "n_selection": int(len(actual)),
                "qlike": float(qlike(actual, preds)),
                "mean_pred_rv": float(np.mean(preds)),
            }
    scheme_scores = summarize_scheme(stage_a)
    best_name = min(scheme_scores, key=scheme_scores.get)
    best_scheme = next(s for s in SCHEMES if s.name == best_name)
    return (
        {
            "per_scheme_asset": stage_a,
            "cross_asset_mean_qlike": scheme_scores,
            "selection_window": {
                "start": str(SELECTION_START.date()),
                "end": str(SELECTION_END.date()),
            },
            "best_scheme": {
                "name": best_scheme.name,
                "window": best_scheme.window,
                "refit_every": best_scheme.refit_every,
            },
        },
        best_scheme,
    )


def run_stage_b(asset_frames: dict[str, pd.DataFrame], best_scheme: Scheme) -> dict:
    models = ["HAR_OLS", "ElasticNet", "RandomForest", "XGBoost"]
    per_asset: dict[str, dict] = {}
    pooled_losses: dict[str, list[np.ndarray]] = {m: [] for m in models}
    pooled_preds: dict[str, list[float]] = {m: [] for m in models}
    pooled_actual: list[float] = []
    model_schemes = {model_name: best_scheme for model_name in models}

    for asset, df in asset_frames.items():
        x, y_log, y_rv = build_xy(df)
        per_asset[asset] = {"models": {}, "pairwise_vs_har": {}}
        pred_store: dict[str, tuple[np.ndarray, np.ndarray]] = {}

        for model_name in models:
            preds, _, valid_idx = walk_forward_predict(
                x,
                y_log,
                df["date"],
                model_schemes[model_name],
                model_name,
                eval_start=OOS_START,
            )
            pred_store[model_name] = (preds, valid_idx)
        shared_valid_idx = sorted(
            set(pred_store["HAR_OLS"][1].tolist())
            .intersection(*[set(pred_store[m][1].tolist()) for m in models[1:]])
        )
        shared_valid_idx = np.array(shared_valid_idx, dtype=int)
        actual = y_rv[shared_valid_idx]
        pooled_actual.extend(actual.tolist())

        for model_name in models:
            preds, valid_idx = pred_store[model_name]
            idx_map = {idx: pos for pos, idx in enumerate(valid_idx)}
            aligned_preds = np.array([preds[idx_map[idx]] for idx in shared_valid_idx], dtype=float)
            losses = qlike_pointwise(actual, aligned_preds)
            pooled_losses[model_name].append(losses)
            pooled_preds[model_name].extend(aligned_preds.tolist())
            per_asset[asset]["models"][model_name] = {
                "qlike": float(qlike(actual, aligned_preds)),
                "mean_pred_rv": float(np.mean(aligned_preds)),
                "n_oos": int(len(actual)),
                "scheme": {
                    "window": model_schemes[model_name].window,
                    "refit_every": model_schemes[model_name].refit_every,
                },
            }

        har_loss = pooled_losses["HAR_OLS"][-1]
        for challenger in models[1:]:
            challenger_loss = pooled_losses[challenger][-1]
            t_stat, p_val = dm_test(har_loss, challenger_loss, h=1)
            har_qlike = per_asset[asset]["models"]["HAR_OLS"]["qlike"]
            challenger_qlike = per_asset[asset]["models"][challenger]["qlike"]
            favored = "HAR_OLS" if t_stat < 0 else challenger
            per_asset[asset]["pairwise_vs_har"][challenger] = {
                "dm_t_stat_har_minus_challenger": float(t_stat),
                "p_value": float(p_val),
                "harvey_pass": bool(abs(t_stat) > 3.0 and p_val < 0.05),
                "favored_model": favored,
                "lower_qlike_model": "HAR_OLS" if har_qlike < challenger_qlike else challenger,
            }

    pooled = {}
    pooled_actual_arr = np.array(pooled_actual, dtype=float)
    for model_name in models:
        preds = np.array(pooled_preds[model_name], dtype=float)
        pooled[model_name] = {
            "qlike": float(qlike(pooled_actual_arr, preds)),
            "n_oos": int(len(preds)),
        }
    for challenger in models[1:]:
        t_stat, p_val = dm_test(
            np.concatenate(pooled_losses["HAR_OLS"]),
            np.concatenate(pooled_losses[challenger]),
            h=1,
        )
        pooled[f"HAR_OLS_vs_{challenger}"] = {
            "dm_t_stat_har_minus_challenger": float(t_stat),
            "p_value": float(p_val),
            "harvey_pass": bool(abs(t_stat) > 3.0 and p_val < 0.05),
            "favored_model": "HAR_OLS" if t_stat < 0 else challenger,
        }
    return {"per_asset": per_asset, "pooled": pooled}


def make_chart(stage_b: dict) -> None:
    pooled = stage_b["pooled"]
    model_names = ["HAR_OLS", "ElasticNet", "RandomForest", "XGBoost"]
    values = [pooled[m]["qlike"] for m in model_names]
    colors = ["#1f77b4", "#2ca02c", "#ff7f0e", "#d62728"]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(model_names, values, color=colors)
    ax.set_title("K1328 pooled OOS QLIKE by model")
    ax.set_ylabel("QLIKE (lower is better)")
    ax.axhline(min(values), color="#333333", linestyle="--", linewidth=1)
    fig.tight_layout()
    fig.savefig(CHART_PATH, dpi=160)
    plt.close(fig)


def build_conclusion(stage_a: dict, stage_b: dict) -> dict:
    best_scheme = stage_a["best_scheme"]["name"]
    scheme_scores = stage_a["cross_asset_mean_qlike"]
    worst_scheme = max(scheme_scores, key=scheme_scores.get)
    pooled = stage_b["pooled"]
    challenger_names = ["ElasticNet", "RandomForest", "XGBoost"]
    har_qlike = pooled["HAR_OLS"]["qlike"]
    better_than_har = [
        name for name in challenger_names if pooled[name]["qlike"] < har_qlike
    ]
    harvey_losses = []
    for name in challenger_names:
        test = pooled[f"HAR_OLS_vs_{name}"]
        if test["favored_model"] != "HAR_OLS" and test["harvey_pass"]:
            harvey_losses.append(name)
    if harvey_losses:
        verdict = "FAIL"
        summary = (
            f"At least one challenger beats best HAR at Harvey strength in pooled OOS: {', '.join(harvey_losses)}."
        )
    elif better_than_har:
        verdict = "CONDITIONAL_PASS"
        summary = (
            f"Some challengers edge HAR on pooled QLIKE ({', '.join(better_than_har)}), "
            "but none clear the Harvey |t|>3 bar."
        )
    else:
        verdict = "PASS"
        summary = "Best HAR remains the pooled QLIKE leader; ceiling supported in this local proxy setup."
    tuning_gain = scheme_scores[worst_scheme] - scheme_scores[best_scheme]
    return {
        "verdict": verdict,
        "best_scheme": best_scheme,
        "worst_scheme": worst_scheme,
        "tuning_gain_qlike": float(tuning_gain),
        "summary": summary,
    }


def main() -> None:
    np.random.seed(SEED)
    asset_frames = {asset: load_asset_frame(asset) for asset in ASSETS}
    stage_a, best_scheme = run_stage_a(asset_frames)
    stage_b = run_stage_b(asset_frames, best_scheme)
    make_chart(stage_b)
    conclusion = build_conclusion(stage_a, stage_b)

    results = {
        "experiment_id": "K1328",
        "title": "HAR ceiling validation — rolling/refit tuned HAR vs matched-feature ML",
        "seed": SEED,
        "data_source": {
            "type": "local_snapshot",
            "base_dir": str(DATA_DIR),
            "assets": ASSETS,
            "selection_start": str(SELECTION_START.date()),
            "selection_end": str(SELECTION_END.date()),
            "oos_start": str(OOS_START.date()),
        },
        "literature": [
            {
                "citation": "Corsi (2009) A Simple Approximate Long-Memory Model of Realized Volatility",
                "role": "HAR baseline specification",
            },
            {
                "citation": "Audrino & Chassot (2024/2025 SSRN) Hard to Beat: The Overlooked Impact of Rolling Windows in the Era of Machine Learning",
                "role": "HAR ceiling / fitting-scheme motivation",
            },
            {
                "citation": "Kilic (2025 FEDS) Linear and nonlinear econometric models against machine learning models: realized volatility prediction",
                "role": "modern mixed evidence benchmark",
            },
        ],
        "method": {
            "target_proxy": "daily squared log return",
            "features": ["log_rv_lag1", "log_rv_mean5", "log_rv_mean22"],
            "target": "log(rv_t)",
            "lookahead_policy": "all features constructed from t-1 and earlier only",
            "stage_a_selection_rule": "HAR schemes with a common 21-day refit cadence are selected only on 2017-01-03 to 2020-12-31 holdout; 2021-01-04+ kept untouched for final evaluation",
            "stage_b_schedule_rule": "HAR and all ML challengers use the exact same selected window and the same 21-day refit cadence",
            "success_rule": "Harvey |t| > 3 and lower QLIKE required for strong challenger win",
        },
        "stage_a_har_scheme_audit": stage_a,
        "stage_b_model_comparison": stage_b,
        "conclusion": conclusion,
        "artifacts": {
            "chart_model_comparison": str(CHART_PATH.name),
        },
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(json.dumps(conclusion, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
