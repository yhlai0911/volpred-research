"""K1327 -- Adaptive Multi-Factor HAR public-proxy stress test.

This is an honest daily-data proxy for Cinquetti et al.'s FoFI 2026
volatility-factor idea. The exact 287 high-frequency factor panel is not
available locally, so the script builds a large public factor bank from local
OHLC snapshots and local risk-proxy files.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import ElasticNet, LinearRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


SEED = 42
EPS = 1e-12
OOS_START = pd.Timestamp("2021-01-04")
ASSETS = ["SPY", "QQQ", "GLD", "TLT", "IWM", "EEM", "BTC_USD"]
ROLL_WINDOWS = [1, 5, 22, 66]
DATA_DIR = Path("experiments/k1206/data")
SENTIMENT_DIR = Path("storage/sentiment")
OUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUT_DIR / "k1327_results.json"
CHART_PATH = OUT_DIR / "k1327_qlike_comparison.png"


@dataclass(frozen=True)
class ModelSpec:
    name: str
    feature_set: str
    model_type: str
    alpha: float | None = None
    l1_ratio: float | None = None
    rolling: bool = False
    window: int | None = None
    refit_every: int = 63


def _safe_log(x: pd.Series) -> pd.Series:
    return np.log(x.astype(float).clip(lower=EPS))


def load_ohlc(asset: str) -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / f"{asset}.csv", parse_dates=["Date"])
    df = df.sort_values("Date")
    out = pd.DataFrame({"date": df["Date"]})
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    open_ = df["Open"].astype(float)
    log_close = np.log(close)
    log_high = np.log(high)
    log_low = np.log(low)
    log_open = np.log(open_)
    ret = log_close.diff()
    hl = log_high - log_low
    co = log_close - log_open
    parkinson = hl.pow(2) / (4.0 * np.log(2.0))
    gk = 0.5 * hl.pow(2) - (2.0 * np.log(2.0) - 1.0) * co.pow(2)
    rs = (log_high - log_close) * (log_high - log_open) + (log_low - log_close) * (log_low - log_open)
    out[f"{asset}_rv"] = ret.pow(2)
    out[f"{asset}_abs"] = ret.abs()
    out[f"{asset}_parkinson"] = parkinson
    out[f"{asset}_gk"] = gk.clip(lower=EPS)
    out[f"{asset}_rs"] = rs.clip(lower=EPS)
    return out


def load_yf_style_sentiment(path: Path, name: str) -> pd.DataFrame:
    df = pd.read_csv(path, skiprows=[1, 2])
    df = df.rename(columns={"Price": "date", "Close": name})
    return df[["date", name]].assign(date=lambda x: pd.to_datetime(x["date"]))


def load_credit_spread() -> pd.DataFrame:
    df = pd.read_csv(SENTIMENT_DIR / "credit_spread_proxy.csv", parse_dates=["Date"])
    df = df.rename(columns={"Date": "date", "HYG_LQD_Ratio": "credit_hyg_lqd_ratio"})
    return df[["date", "credit_hyg_lqd_ratio"]]


def build_master_frame() -> pd.DataFrame:
    master = load_ohlc("SPY")
    for asset in ASSETS[1:]:
        master = master.merge(load_ohlc(asset), on="date", how="left")
    for path, name in [
        (SENTIMENT_DIR / "vix_historical.csv", "vix"),
        (SENTIMENT_DIR / "vvix_historical.csv", "vvix"),
        (SENTIMENT_DIR / "skew_index.csv", "skew"),
    ]:
        master = master.merge(load_yf_style_sentiment(path, name), on="date", how="left")
    master = master.merge(load_credit_spread(), on="date", how="left")
    master = master.sort_values("date").ffill()
    return master


def add_shifted_factor_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    out_parts = [pd.DataFrame({"date": df["date"], "target_rv": df["SPY_rv"]})]
    factor_cols = []
    feature_families = []
    raw_factor_cols = [c for c in df.columns if c != "date" and c != "SPY_rv"]
    raw_factor_cols += ["SPY_rv"]
    for col in raw_factor_cols:
        family = col.split("_")[0]
        for w in ROLL_WINDOWS:
            feature = f"{col}_lagmean{w}"
            out_parts.append(pd.DataFrame({feature: _safe_log(df[col].shift(1).rolling(w).mean())}))
            factor_cols.append(feature)
            feature_families.append(family)
    out = pd.concat(out_parts, axis=1).copy()
    out["target_log_rv"] = _safe_log(out["target_rv"])
    out = out.replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)
    return out, factor_cols, feature_families


def select_hyperparams(
    train: pd.DataFrame,
    features: list[str],
    actual_col: str = "target_rv",
    y_col: str = "target_log_rv",
) -> dict[str, dict]:
    n = len(train)
    cut = int(n * 0.8)
    tr = train.iloc[:cut]
    val = train.iloc[cut:]
    x_tr = tr[features].to_numpy()
    y_tr = tr[y_col].to_numpy()
    x_val = val[features].to_numpy()
    actual_val = val[actual_col].to_numpy()
    grids = {
        "ridge": [{"alpha": a} for a in [0.1, 1.0, 10.0, 100.0, 1000.0]],
        "elasticnet": [
            {"alpha": a, "l1_ratio": l1}
            for a in [0.01, 0.05, 0.1, 0.2]
            for l1 in [0.1, 0.5, 0.9]
        ],
    }
    selected = {}
    for model_type, params_grid in grids.items():
        best = None
        for params in params_grid:
            if model_type == "ridge":
                model = Pipeline([("scale", StandardScaler()), ("model", Ridge(alpha=params["alpha"]))])
            else:
                model = Pipeline(
                    [
                        ("scale", StandardScaler()),
                        (
                            "model",
                            ElasticNet(
                                alpha=params["alpha"],
                                l1_ratio=params["l1_ratio"],
                                max_iter=50000,
                                random_state=SEED,
                            ),
                        ),
                    ]
                )
            model.fit(x_tr, y_tr)
            pred = np.exp(model.predict(x_val))
            score = qlike(actual_val, pred)
            if best is None or score < best["qlike"]:
                best = {"qlike": float(score), **params}
        selected[model_type] = best
    return selected


def build_model(spec: ModelSpec):
    if spec.model_type == "ols":
        return LinearRegression()
    if spec.model_type == "ridge":
        return Pipeline([("scale", StandardScaler()), ("model", Ridge(alpha=float(spec.alpha)))])
    if spec.model_type == "elasticnet":
        return Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "model",
                    ElasticNet(
                        alpha=float(spec.alpha),
                        l1_ratio=float(spec.l1_ratio),
                        max_iter=50000,
                        random_state=SEED,
                    ),
                ),
            ]
        )
    raise ValueError(f"Unknown model type: {spec.model_type}")


def walk_forward(df: pd.DataFrame, features: list[str], spec: ModelSpec) -> tuple[np.ndarray, np.ndarray, list[np.ndarray]]:
    oos_start_idx = int(np.flatnonzero(df["date"] >= OOS_START)[0])
    preds = np.full(len(df), np.nan)
    selected_masks: list[np.ndarray] = []
    model = None
    refit_count = 0
    for t in range(oos_start_idx, len(df)):
        if spec.rolling:
            train_start = max(0, t - int(spec.window))
        else:
            train_start = 0
        train = df.iloc[train_start:t]
        if len(train) < 252:
            continue
        if model is None or refit_count % spec.refit_every == 0:
            model = build_model(spec)
            model.fit(train[features].to_numpy(), train["target_log_rv"].to_numpy())
            if spec.model_type == "elasticnet":
                coef = model.named_steps["model"].coef_
                selected_masks.append(np.abs(coef) > 1e-10)
        pred_log = float(model.predict(df.iloc[t : t + 1][features].to_numpy())[0])
        preds[t] = np.exp(pred_log)
        refit_count += 1
    valid = np.isfinite(preds)
    return preds[valid], df.loc[valid, "target_rv"].to_numpy(), selected_masks


def evaluate_models(df: pd.DataFrame, har_features: list[str], mf_features: list[str], specs: list[ModelSpec]) -> dict:
    losses = {}
    output = {}
    for spec in specs:
        features = har_features if spec.feature_set == "har3" else mf_features
        preds, actual, selected_masks = walk_forward(df, features, spec)
        loss = qlike_pointwise(actual, preds)
        losses[spec.name] = loss
        output[spec.name] = {
            "qlike": float(qlike(actual, preds)),
            "mse": float(np.mean((actual - preds) ** 2)),
            "mean_pred_rv": float(np.mean(preds)),
            "n_oos": int(len(actual)),
            "feature_set": spec.feature_set,
            "model_type": spec.model_type,
            "rolling": spec.rolling,
            "window": spec.window,
            "refit_every": spec.refit_every,
            "alpha": spec.alpha,
            "l1_ratio": spec.l1_ratio,
            "selection_refits": int(len(selected_masks)),
        }
    pairwise = {}
    base_loss = losses["HAR3"]
    for name, loss in losses.items():
        if name == "HAR3":
            continue
        t_stat, p_val = dm_test(base_loss, loss, h=1)
        pairwise[name] = {
            "dm_t_stat_har3_minus_model": float(t_stat),
            "p_value": float(p_val),
            "harvey_pass": bool(abs(t_stat) > 3.0 and p_val < 0.05),
            "favored_model": "HAR3" if t_stat < 0 else name,
            "lower_qlike_model": "HAR3" if output["HAR3"]["qlike"] < output[name]["qlike"] else name,
        }
    return {"models": output, "pairwise_vs_har3": pairwise, "losses": losses}


def family_selection_summary(masks: list[np.ndarray], features: list[str]) -> dict:
    if not masks:
        return {}
    arr = np.vstack(masks)
    freq = arr.mean(axis=0)
    family_rows = {}
    for feature, f in zip(features, freq):
        family = feature.split("_")[0]
        family_rows.setdefault(family, []).append(float(f))
    return {
        family: {
            "mean_selection_frequency": float(np.mean(vals)),
            "max_selection_frequency": float(np.max(vals)),
            "n_features": int(len(vals)),
        }
        for family, vals in sorted(family_rows.items())
    }


def make_chart(results: dict) -> None:
    names = list(results["models"].keys())
    values = [results["models"][n]["qlike"] for n in names]
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.bar(names, values, color=["#4c78a8", "#72b7b2", "#54a24b", "#f58518", "#e45756"])
    ax.set_ylabel("OOS QLIKE (lower is better)")
    ax.set_title("K1327 Adaptive Multi-Factor HAR public-proxy test")
    ax.tick_params(axis="x", rotation=25)
    fig.tight_layout()
    fig.savefig(CHART_PATH, dpi=160)
    plt.close(fig)


def main() -> None:
    np.random.seed(SEED)
    master = build_master_frame()
    data, all_features, _ = add_shifted_factor_features(master)
    train = data[data["date"] < OOS_START].copy()
    har_features = ["SPY_rv_lagmean1", "SPY_rv_lagmean5", "SPY_rv_lagmean22"]
    mf_features = all_features
    hyper = select_hyperparams(train, mf_features)
    specs = [
        ModelSpec("HAR3", "har3", "ols", rolling=True, window=1000, refit_every=21),
        ModelSpec("MF_Ridge_static", "multifactor", "ridge", alpha=hyper["ridge"]["alpha"], rolling=False, refit_every=21),
        ModelSpec(
            "MF_ElasticNet_static",
            "multifactor",
            "elasticnet",
            alpha=hyper["elasticnet"]["alpha"],
            l1_ratio=hyper["elasticnet"]["l1_ratio"],
            rolling=False,
            refit_every=21,
        ),
        ModelSpec("MF_Ridge_rolling", "multifactor", "ridge", alpha=hyper["ridge"]["alpha"], rolling=True, window=1000, refit_every=63),
        ModelSpec(
            "MF_ElasticNet_rolling",
            "multifactor",
            "elasticnet",
            alpha=hyper["elasticnet"]["alpha"],
            l1_ratio=hyper["elasticnet"]["l1_ratio"],
            rolling=True,
            window=1000,
            refit_every=63,
        ),
    ]
    eval_out = evaluate_models(data, har_features, mf_features, specs)
    make_chart(eval_out)

    rolling_enet_preds, rolling_actual, rolling_masks = walk_forward(
        data,
        mf_features,
        specs[-1],
    )
    del rolling_enet_preds, rolling_actual
    selection = family_selection_summary(rolling_masks, mf_features)

    model_qlikes = {k: v["qlike"] for k, v in eval_out["models"].items()}
    best_model = min(model_qlikes, key=model_qlikes.get)
    strong_winners = [
        name
        for name, row in eval_out["pairwise_vs_har3"].items()
        if row["harvey_pass"] and row["lower_qlike_model"] == name
    ]
    if strong_winners:
        verdict = "PASS"
        summary = f"Adaptive multi-factor model(s) beat HAR3 at Harvey strength: {', '.join(strong_winners)}."
    elif best_model != "HAR3":
        verdict = "CONDITIONAL_PASS"
        summary = f"{best_model} has lower QLIKE than HAR3, but not at Harvey |t|>3 strength."
    else:
        verdict = "NULL"
        summary = "No adaptive multi-factor model beats HAR3 on QLIKE in this public daily proxy."

    results = {
        "experiment_id": "K1327",
        "title": "Adaptive Multi-Factor HAR public-proxy stress test",
        "seed": SEED,
        "data_source": {
            "local_files": [
                "experiments/k1206/data/*.csv",
                "storage/sentiment/vix_historical.csv",
                "storage/sentiment/vvix_historical.csv",
                "storage/sentiment/skew_index.csv",
                "storage/sentiment/credit_spread_proxy.csv",
            ],
            "sample_start": str(data["date"].min().date()),
            "sample_end": str(data["date"].max().date()),
            "oos_start": str(OOS_START.date()),
            "n_total": int(len(data)),
            "n_train_pre_oos": int(len(train)),
            "n_features_multifactor": int(len(mf_features)),
        },
        "literature": [
            "Cinquetti, Hong, Nolte & Nolte (2025/2026), Volatility Forecasting Factors",
            "Corsi (2009), HAR-RV",
            "Patton (2011), volatility forecast comparison with imperfect proxies",
        ],
        "method": {
            "target": "SPY daily squared log return",
            "model_space": "log(rv_t)",
            "evaluation": "QLIKE on positive variance forecasts exp(pred_log)",
            "lookahead_policy": "all factor features are shifted by one day before rolling aggregation",
            "hyperparam_selection": "pre-OOS train/validation split only",
        },
        "hyperparams": hyper,
        "evaluation": {
            "models": eval_out["models"],
            "pairwise_vs_har3": eval_out["pairwise_vs_har3"],
        },
        "rolling_elasticnet_family_selection": selection,
        "conclusion": {
            "verdict": verdict,
            "best_model": best_model,
            "summary": summary,
        },
        "artifacts": {
            "chart": CHART_PATH.name,
        },
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(json.dumps(results["conclusion"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
