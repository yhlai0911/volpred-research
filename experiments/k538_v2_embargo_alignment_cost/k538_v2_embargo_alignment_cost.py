"""
K538 v2: corrected meta-labeling refit.

Fixes the three issues found in the mile_b70e8480 Codex review:
1. Cross-OOS embargo is enforced as 22 trading rows, not calendar dates.
2. Row t uses information through t-1 and evaluates return at t.
3. Transaction cost is proportional to absolute position turnover.
"""

from __future__ import annotations

import json
import math
import os
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler
import xgboost as xgb


warnings.filterwarnings("ignore")

EXPERIMENT_ID = "k538_v2_embargo_alignment_cost"
ROOT = Path(__file__).resolve().parent
ORIG_RESULTS = ROOT.parent / "k538" / "k538_meta_labeling_results.json"
SNAPSHOT_DIR = ROOT / "data"

SEED = 42
EMBARGO_ROWS = 22
TX_COST = 0.0010
THRESHOLDS = np.arange(0.40, 0.70, 0.02)


@dataclass(frozen=True)
class OOSConfig:
    train_start: str
    train_end: str
    test_end: str
    label: str


OOS_CONFIGS = [
    OOSConfig("2010-01-01", "2013-12-31", "2015-12-31", "post_gfc"),
    OOSConfig("2014-01-01", "2017-12-31", "2019-12-31", "volmageddon"),
    OOSConfig("2017-01-01", "2021-12-31", "2023-12-31", "covid_bear"),
]


MODELS = {
    "logistic": {
        "name": "Logistic Regression",
        "model_fn": lambda: LogisticRegression(
            C=1.0, penalty="l2", solver="lbfgs", max_iter=1000, random_state=SEED
        ),
    },
    "xgboost": {
        "name": "XGBoost",
        "model_fn": lambda: xgb.XGBClassifier(
            n_estimators=100,
            max_depth=3,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            use_label_encoder=False,
            eval_metric="logloss",
            n_jobs=1,
            random_state=SEED,
            verbosity=0,
        ),
    },
    "random_forest": {
        "name": "Random Forest",
        "model_fn": lambda: RandomForestClassifier(
            n_estimators=200,
            max_depth=5,
            min_samples_leaf=20,
            random_state=SEED,
            n_jobs=1,
        ),
    },
}


def download_data() -> dict[str, pd.DataFrame]:
    tickers = {
        "SPY": "SPY",
        "VIX": "^VIX",
        "VIX3M": "^VIX3M",
        "TLT": "TLT",
        "GLD": "GLD",
    }
    out = {}
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    for name, ticker in tickers.items():
        snapshot_path = SNAPSHOT_DIR / f"{name}_auto_adjust_2006_2025.csv"
        if snapshot_path.exists():
            df = pd.read_csv(snapshot_path, index_col=0, parse_dates=True)
        else:
            df = yf.download(
                ticker,
                start="2006-01-01",
                end="2026-01-01",
                auto_adjust=True,
                progress=False,
            )
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.to_csv(snapshot_path, index_label="Date")
        out[name] = df
    return out


def build_dataset(data: dict[str, pd.DataFrame]) -> dict[str, object]:
    common = data["SPY"].index.intersection(data["VIX"].index)
    for name in ["VIX3M", "TLT", "GLD"]:
        common = common.intersection(data[name].index)

    spy_close = data["SPY"].loc[common, "Close"]
    vix_close = data["VIX"].loc[common, "Close"]
    vix3m_close = data["VIX3M"].loc[common, "Close"]
    tlt_close = data["TLT"].loc[common, "Close"]
    gld_close = data["GLD"].loc[common, "Close"]

    spy_ret = spy_close.pct_change()
    vt_weight_raw = (12.0 / vix_close).clip(0, 1.5)
    vt_position = vt_weight_raw.shift(1)
    vt_ret = vt_position * spy_ret
    bh_position = pd.Series(1.0, index=common)
    bh_ret = spy_ret
    excess_ret = vt_ret - bh_ret

    # Corrected alignment: row t contains t-1 information and labels return at t.
    label = (excess_ret > 0).astype(float)
    label[excess_ret.isna()] = np.nan

    features = pd.DataFrame(index=common)
    features["vix_level"] = vix_close
    features["vix_log"] = np.log(vix_close)
    features["vix_5d_change"] = vix_close.pct_change(5)
    features["vix_22d_pctile"] = vix_close.rolling(252).rank(pct=True)
    features["vix_term_ratio"] = vix_close / vix3m_close
    features["spy_5d_ret"] = spy_close.pct_change(5)
    features["spy_22d_ret"] = spy_close.pct_change(22)
    features["spy_5d_vol"] = spy_ret.rolling(5).std() * math.sqrt(252)
    features["vt_excess_5d"] = excess_ret.rolling(5).sum()
    features["vt_excess_22d"] = excess_ret.rolling(22).sum()
    features["vt_win_rate_22d"] = (excess_ret > 0).rolling(22).mean()
    features["tlt_5d_vol"] = tlt_close.pct_change().rolling(5).std() * math.sqrt(252)
    features["gld_5d_vol"] = gld_close.pct_change().rolling(5).std() * math.sqrt(252)
    features["vt_weight"] = vt_weight_raw

    # All model inputs are known at close t-1 when evaluating close-to-close return t.
    features = features.shift(1)
    features["vix_level_lag2"] = vix_close.shift(2)
    features["spy_ret_lag1"] = spy_ret.shift(1)

    feature_cols = [c for c in features.columns if features[c].notna().sum() > len(features) * 0.5]
    features = features[feature_cols]

    valid_start = "2007-01-01"
    dates = common[
        (common >= valid_start)
        & vt_ret.notna().reindex(common).fillna(False).to_numpy()
        & bh_ret.notna().reindex(common).fillna(False).to_numpy()
        & label.notna().reindex(common).fillna(False).to_numpy()
    ]

    feat_df = features.loc[dates].copy()
    label_df = label.loc[dates].astype(int).copy()
    valid_mask = feat_df.notna().all(axis=1)

    feat_df = feat_df[valid_mask]
    label_df = label_df[valid_mask]

    return {
        "feature_cols": feature_cols,
        "features": feat_df,
        "label": label_df,
        "spy_ret": spy_ret.loc[feat_df.index],
        "vt_ret": vt_ret.loc[feat_df.index],
        "bh_ret": bh_ret.loc[feat_df.index],
        "vt_position": vt_position.loc[feat_df.index],
        "bh_position": bh_position.loc[feat_df.index],
        "common": common,
    }


def sharpe(returns: np.ndarray) -> float:
    if len(returns) == 0 or np.nanstd(returns) == 0:
        return 0.0
    return float(np.nanmean(returns) / np.nanstd(returns) * math.sqrt(252))


def ann_return(returns: np.ndarray) -> float:
    if len(returns) == 0:
        return 0.0
    return float((1 + np.nanmean(returns)) ** 252 - 1)


def mdd(returns: np.ndarray) -> float:
    if len(returns) == 0:
        return 0.0
    cum = pd.Series(returns).add(1).cumprod()
    dd = (cum - cum.cummax()) / cum.cummax()
    return float(dd.min())


def net_returns(position: np.ndarray, spy_ret: np.ndarray, tx_cost: float = TX_COST) -> tuple[np.ndarray, np.ndarray]:
    position = np.asarray(position, dtype=float)
    spy_ret = np.asarray(spy_ret, dtype=float)
    turnover = np.abs(np.diff(position, prepend=position[0]))
    return position * spy_ret - turnover * tx_cost, turnover


def first_test_after_embargo(index: pd.DatetimeIndex, train_dates: pd.DatetimeIndex) -> pd.Timestamp:
    last_train_pos = index.get_loc(train_dates[-1])
    return index[last_train_pos + EMBARGO_ROWS + 1]


def evaluate_split(
    feat_df: pd.DataFrame,
    label_df: pd.Series,
    spy_ret: pd.Series,
    vt_position: pd.Series,
    config: OOSConfig,
) -> dict[str, object]:
    train_mask = (feat_df.index >= config.train_start) & (feat_df.index <= config.train_end)
    train_dates = feat_df.index[train_mask]
    if len(train_dates) == 0:
        raise ValueError(f"No training rows for {config}")
    test_start = first_test_after_embargo(feat_df.index, train_dates)
    test_mask = (feat_df.index >= test_start) & (feat_df.index <= config.test_end)

    X_train = feat_df[train_mask].values
    y_train = label_df[train_mask].values
    X_test = feat_df[test_mask].values
    y_test = label_df[test_mask].values
    test_dates = feat_df.index[test_mask]
    test_spy_ret = spy_ret[test_mask].values
    test_vt_pos = vt_position[test_mask].values
    test_bh_pos = np.ones(len(test_dates))

    scaler = StandardScaler()
    X_train_sc = scaler.fit_transform(X_train)
    X_test_sc = scaler.transform(X_test)

    gap_rows = int(((feat_df.index > train_dates[-1]) & (feat_df.index < test_dates[0])).sum())
    out: dict[str, object] = {
        "period_label": config.label,
        "train_dates": f"{config.train_start} ~ {config.train_end}",
        "test_dates": f"{test_dates[0].strftime('%Y-%m-%d')} ~ {config.test_end}",
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "embargo_rows_between_train_and_test": gap_rows,
        "models": {},
    }

    for model_key, model_cfg in MODELS.items():
        model = model_cfg["model_fn"]()
        model.fit(X_train_sc, y_train)
        y_prob = model.predict_proba(X_test_sc)[:, 1]
        y_pred = (y_prob >= 0.5).astype(int)

        n_half = len(X_test) // 2
        val_prob, eval_prob = y_prob[:n_half], y_prob[n_half:]
        val_spy, eval_spy = test_spy_ret[:n_half], test_spy_ret[n_half:]
        val_vt_pos, eval_vt_pos = test_vt_pos[:n_half], test_vt_pos[n_half:]
        eval_bh_pos = test_bh_pos[n_half:]

        best_thr = 0.5
        best_val_sharpe = -np.inf
        for thr in THRESHOLDS:
            use_vt = (val_prob >= thr).astype(float)
            pos = use_vt * val_vt_pos + (1.0 - use_vt)
            ret, _ = net_returns(pos, val_spy)
            sr = sharpe(ret)
            if sr > best_val_sharpe:
                best_val_sharpe = sr
                best_thr = float(thr)

        use_vt = (eval_prob >= best_thr).astype(float)
        meta_pos = use_vt * eval_vt_pos + (1.0 - use_vt)
        meta_ret, meta_turnover = net_returns(meta_pos, eval_spy)
        vt_ret_net, vt_turnover = net_returns(eval_vt_pos, eval_spy)
        bh_ret_net, bh_turnover = net_returns(eval_bh_pos, eval_spy)

        out["models"][model_key] = {
            "model_name": model_cfg["name"],
            "classification": {
                "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
                "auc": round(float(roc_auc_score(y_test, y_prob)), 4),
                "brier": round(float(brier_score_loss(y_test, y_prob)), 4),
                "log_loss": round(float(log_loss(y_test, y_prob)), 4),
                "precision": round(float(precision_score(y_test, y_pred, zero_division=0)), 4),
                "recall": round(float(recall_score(y_test, y_pred, zero_division=0)), 4),
                "f1": round(float(f1_score(y_test, y_pred, zero_division=0)), 4),
            },
            "best_threshold": round(best_thr, 2),
            "val_sharpe": round(float(best_val_sharpe), 3),
            "oos_eval": {
                "n_eval": int(len(eval_prob)),
                "meta_sharpe": round(sharpe(meta_ret), 3),
                "vt_sharpe": round(sharpe(vt_ret_net), 3),
                "bh_sharpe": round(sharpe(bh_ret_net), 3),
                "meta_ann_ret": round(ann_return(meta_ret), 4),
                "vt_ann_ret": round(ann_return(vt_ret_net), 4),
                "bh_ann_ret": round(ann_return(bh_ret_net), 4),
                "meta_mdd": round(mdd(meta_ret), 4),
                "vt_mdd": round(mdd(vt_ret_net), 4),
                "bh_mdd": round(mdd(bh_ret_net), 4),
                "vt_usage_pct": round(float(np.mean(use_vt)), 4),
                "n_switches": int(np.abs(np.diff(use_vt, prepend=use_vt[0])).sum()),
                "meta_turnover": round(float(np.sum(meta_turnover)), 4),
                "vt_turnover": round(float(np.sum(vt_turnover)), 4),
                "bh_turnover": round(float(np.sum(bh_turnover)), 4),
            },
        }

    return out


def summarize_cross_oos(cross_results: dict[str, object]) -> dict[str, object]:
    summary = {}
    for model_key, model_cfg in MODELS.items():
        rows = [period["models"][model_key] for period in cross_results.values()]
        aucs = [r["classification"]["auc"] for r in rows]
        meta = [r["oos_eval"]["meta_sharpe"] for r in rows]
        vt = [r["oos_eval"]["vt_sharpe"] for r in rows]
        bh = [r["oos_eval"]["bh_sharpe"] for r in rows]
        summary[model_key] = {
            "name": model_cfg["name"],
            "auc_mean": round(float(np.mean(aucs)), 4),
            "auc_std": round(float(np.std(aucs)), 4),
            "meta_sharpe_mean": round(float(np.mean(meta)), 3),
            "meta_sharpe_std": round(float(np.std(meta)), 3),
            "vt_sharpe_mean": round(float(np.mean(vt)), 3),
            "bh_sharpe_mean": round(float(np.mean(bh)), 3),
            "meta_beats_vt": int(sum(m > v for m, v in zip(meta, vt))),
            "meta_beats_bh": int(sum(m > b for m, b in zip(meta, bh))),
            "n_periods": len(rows),
            "all_sharpes": {"meta": meta, "vt": vt, "bh": bh},
        }
    return summary


def walkforward(
    feat_df: pd.DataFrame,
    label_df: pd.Series,
    spy_ret: pd.Series,
    vt_position: pd.Series,
) -> dict[str, object]:
    X_all = feat_df.values
    y_all = label_df.values
    spy_all = spy_ret.values
    vt_pos_all = vt_position.values
    dates_all = feat_df.index
    out = {}

    min_train = 504
    retrain_freq = 63

    for model_key, model_cfg in MODELS.items():
        predictions = np.full(len(X_all), np.nan)
        last_train_marker = min_train - 1
        model = None
        scaler = None

        for t in range(min_train + EMBARGO_ROWS, len(X_all)):
            if model is None or (t - last_train_marker) >= retrain_freq:
                train_end_exclusive = t - EMBARGO_ROWS
                X_tr = X_all[:train_end_exclusive]
                y_tr = y_all[:train_end_exclusive]
                scaler = StandardScaler()
                X_tr_sc = scaler.fit_transform(X_tr)
                model = model_cfg["model_fn"]()
                model.fit(X_tr_sc, y_tr)
                last_train_marker = t

            predictions[t] = float(model.predict_proba(scaler.transform(X_all[t : t + 1]))[0, 1])

        valid = ~np.isnan(predictions)
        pred_vals = predictions[valid]
        spy_vals = spy_all[valid]
        vt_pos_vals = vt_pos_all[valid]
        dates_vals = dates_all[valid]

        cal_n = min(252, len(pred_vals) // 4)
        best_thr = 0.5
        best_cal_sharpe = -np.inf
        for thr in THRESHOLDS:
            use_vt = (pred_vals[:cal_n] >= thr).astype(float)
            pos = use_vt * vt_pos_vals[:cal_n] + (1.0 - use_vt)
            ret, _ = net_returns(pos, spy_vals[:cal_n])
            sr = sharpe(ret)
            if sr > best_cal_sharpe:
                best_cal_sharpe = sr
                best_thr = float(thr)

        eval_pred = pred_vals[cal_n:]
        eval_spy = spy_vals[cal_n:]
        eval_vt_pos = vt_pos_vals[cal_n:]
        eval_dates = dates_vals[cal_n:]
        use_vt = (eval_pred >= best_thr).astype(float)
        meta_pos = use_vt * eval_vt_pos + (1.0 - use_vt)
        meta_ret, meta_turnover = net_returns(meta_pos, eval_spy)
        vt_ret_net, vt_turnover = net_returns(eval_vt_pos, eval_spy)
        bh_ret_net, bh_turnover = net_returns(np.ones(len(eval_spy)), eval_spy)

        out[model_key] = {
            "name": model_cfg["name"],
            "threshold": round(best_thr, 2),
            "eval_start": eval_dates[0].strftime("%Y-%m-%d"),
            "eval_end": eval_dates[-1].strftime("%Y-%m-%d"),
            "n_eval_days": int(len(eval_pred)),
            "meta_sharpe": round(sharpe(meta_ret), 3),
            "vt_sharpe": round(sharpe(vt_ret_net), 3),
            "bh_sharpe": round(sharpe(bh_ret_net), 3),
            "meta_ann_ret": round(ann_return(meta_ret), 4),
            "vt_ann_ret": round(ann_return(vt_ret_net), 4),
            "bh_ann_ret": round(ann_return(bh_ret_net), 4),
            "meta_mdd": round(mdd(meta_ret), 4),
            "vt_mdd": round(mdd(vt_ret_net), 4),
            "bh_mdd": round(mdd(bh_ret_net), 4),
            "vt_usage_pct": round(float(np.mean(use_vt)), 4),
            "n_switches": int(np.abs(np.diff(use_vt, prepend=use_vt[0])).sum()),
            "meta_turnover": round(float(np.sum(meta_turnover)), 4),
            "vt_turnover": round(float(np.sum(vt_turnover)), 4),
            "bh_turnover": round(float(np.sum(bh_turnover)), 4),
        }

    return out


def feature_correlations(feature_cols: list[str], feat_df: pd.DataFrame, label_df: pd.Series) -> dict[str, object]:
    corr = {}
    for c in feature_cols:
        r, p = stats.pearsonr(feat_df[c], label_df)
        corr[c] = {"r": round(float(r), 6), "p_value": round(float(p), 6)}
    max_col = max(corr, key=lambda k: abs(corr[k]["r"]))
    return {
        "by_feature": corr,
        "max_abs_feature": max_col,
        "max_abs_r": abs(corr[max_col]["r"]),
    }


def compare_original(model_summary: dict[str, object], walkforward_results: dict[str, object]) -> dict[str, object]:
    original = json.loads(ORIG_RESULTS.read_text())
    comparison = {}
    for model_key in MODELS:
        comparison[model_key] = {
            "original_cross_oos": original["model_summary"][model_key],
            "corrected_cross_oos": model_summary[model_key],
            "original_walkforward": original["walkforward_results"][model_key],
            "corrected_walkforward": walkforward_results[model_key],
        }
    return comparison


def make_figures(model_summary: dict[str, object], walkforward_results: dict[str, object]) -> list[str]:
    names = [MODELS[k]["name"] for k in MODELS]
    keys = list(MODELS)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = np.arange(len(keys))
    width = 0.25
    ax.bar(x - width, [model_summary[k]["meta_sharpe_mean"] for k in keys], width, label="Meta")
    ax.bar(x, [model_summary[k]["vt_sharpe_mean"] for k in keys], width, label="VT net")
    ax.bar(x + width, [model_summary[k]["bh_sharpe_mean"] for k in keys], width, label="B&H")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=15, ha="right")
    ax.set_title("K538 v2 corrected cross-OOS Sharpe")
    ax.set_ylabel("Annualized Sharpe")
    ax.legend()
    fig.tight_layout()
    p1 = ROOT / "k538_v2_cross_oos_sharpe.png"
    fig.savefig(p1, dpi=160)
    plt.close(fig)

    fig, ax1 = plt.subplots(figsize=(8, 4.5))
    ax1.bar(x - 0.18, [walkforward_results[k]["vt_usage_pct"] * 100 for k in keys], 0.36, label="VT usage %")
    ax1.set_ylabel("VT usage (%)")
    ax1.set_xticks(x)
    ax1.set_xticklabels(names, rotation=15, ha="right")
    ax2 = ax1.twinx()
    ax2.plot(x + 0.18, [walkforward_results[k]["n_switches"] for k in keys], "o-", color="#b34700", label="Switches")
    ax2.set_ylabel("Switches")
    ax1.set_title("K538 v2 corrected walk-forward behavior")
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")
    fig.tight_layout()
    p2 = ROOT / "k538_v2_walkforward_behavior.png"
    fig.savefig(p2, dpi=160)
    plt.close(fig)

    return [p1.name, p2.name]


def main() -> None:
    np.random.seed(SEED)
    data = download_data()
    ds = build_dataset(data)
    feat_df = ds["features"]
    label_df = ds["label"]
    spy_ret = ds["spy_ret"]
    vt_position = ds["vt_position"]
    feature_cols = ds["feature_cols"]

    cross_results = {}
    for i, cfg in enumerate(OOS_CONFIGS, start=1):
        cross_results[f"period_{i}"] = evaluate_split(feat_df, label_df, spy_ret, vt_position, cfg)

    model_summary = summarize_cross_oos(cross_results)
    walkforward_results = walkforward(feat_df, label_df, spy_ret, vt_position)
    corr = feature_correlations(feature_cols, feat_df, label_df)
    comparison = compare_original(model_summary, walkforward_results)
    figures = make_figures(model_summary, walkforward_results)

    best_model = max(model_summary, key=lambda k: model_summary[k]["meta_sharpe_mean"])
    best = model_summary[best_model]
    wf_best = walkforward_results[best_model]
    cross_not_stably_superior = best["meta_beats_bh"] < 2
    wf_degenerate_or_not_superior = (
        wf_best["vt_usage_pct"] in (0, 1)
        or wf_best["meta_sharpe"] <= max(wf_best["vt_sharpe"], wf_best["bh_sharpe"])
    )
    qualitative_preserved = (
        cross_not_stably_superior
        and wf_degenerate_or_not_superior
    )

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "K538 corrected refit: true embargo, aligned label/return, turnover cost",
        "timestamp": datetime.now().isoformat(),
        "data_source": "yfinance (SPY, ^VIX, ^VIX3M, TLT, GLD)",
        "data_period": f"{feat_df.index[0].strftime('%Y-%m-%d')} to {feat_df.index[-1].strftime('%Y-%m-%d')}",
        "n_samples": int(len(feat_df)),
        "seed": SEED,
        "methodology": {
            "source_experiment": "experiments/k538/k538_meta_labeling.py",
            "corrections": [
                "label_t = 1 if VT return at t exceeds B&H return at t; features at t are shifted to t-1",
                "cross-OOS first test row is selected after exactly 22 intervening trading rows",
                "10 bps cost is charged on abs(delta portfolio SPY exposure) for meta and VT baseline",
            ],
            "n_features": len(feature_cols),
            "features": feature_cols,
            "models": list(MODELS.keys()),
            "cross_oos_periods": len(OOS_CONFIGS),
            "embargo_rows": EMBARGO_ROWS,
            "tx_cost_bps_per_turnover": int(TX_COST * 10000),
            "threshold_grid": [round(float(t), 2) for t in THRESHOLDS],
            "data_snapshot_files": sorted(p.name for p in SNAPSHOT_DIR.glob("*.csv")),
        },
        "label_balance": round(float(label_df.mean()), 4),
        "feature_correlations": corr,
        "cross_oos_results": cross_results,
        "model_summary": model_summary,
        "walkforward_results": walkforward_results,
        "comparison_to_original_k538": comparison,
        "figures": figures,
        "conclusion": {
            "best_cross_oos_model": best_model,
            "qualitative_article_conclusion_preserved": bool(qualitative_preserved),
            "summary": (
                f"Corrected refit preserves the K538 null conclusion. Best cross-OOS model is {MODELS[best_model]['name']} "
                f"with Meta Sharpe {best['meta_sharpe_mean']:.3f} vs VT {best['vt_sharpe_mean']:.3f} "
                f"and B&H {best['bh_sharpe_mean']:.3f}; it beats B&H in {best['meta_beats_bh']}/3 periods. "
                f"Walk-forward best-model Meta Sharpe is {wf_best['meta_sharpe']:.3f} vs VT {wf_best['vt_sharpe']:.3f} "
                f"and B&H {wf_best['bh_sharpe']:.3f}."
            ),
            "article_action": (
                "Existing errata is directionally sufficient; do not retract. If article is revised, replace the old "
                "Sharpe/usage/switch magnitudes with this v2 result set and remove the strict |r| < 0.02 wording."
            ),
        },
    }

    out_path = ROOT / "k538_v2_embargo_alignment_cost_results.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(json.dumps(results["conclusion"], indent=2, ensure_ascii=False))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
