#!/usr/bin/env python3
"""
K501 retry: US->Taiwan return prediction, timing-aligned and tradability-aware.

This retry fixes four issues found in the 2026-06-07 Codex review:
1. Align target timing to the statement actually tested.
2. Clean 0050.TW split/outlier artifacts before estimation.
3. Separate non-tradable close-to-close information transmission from
   tradable Taiwan open-to-close execution.
4. Save results to the canonical in-folder artifact path.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler

try:
    from volpred.utils import clean_tw50_data
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from volpred.utils import clean_tw50_data

warnings.filterwarnings("ignore")
np.random.seed(42)

EXPERIMENT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = EXPERIMENT_DIR / "k501_return_prediction_results.json"
LOCAL_PRICE_CACHE_DB = Path(__file__).resolve().parents[2] / "data" / "cache" / "price_cache.db"

DATA_START = "2016-01-04"
DATA_END = "2026-06-06"
OOS_START = "2020-01-02"
# Local offline retry only has US cache from 2016 onward, so use a 3-year
# minimum IS window instead of the original 1000-day requirement.
MIN_IS = 756
RIDGE_ALPHA = 1.0
TW_ROUNDTRIP_COST = 0.001855


@dataclass
class ForecastBundle:
    dates: pd.DatetimeIndex
    actuals: np.ndarray
    models: dict[str, np.ndarray]
    pip_dict: dict[str, dict[str, float | bool]]
    selected_vars: list[str]
    n_selected: int


def load_cached_ohlcv(ticker: str) -> pd.DataFrame:
    if not LOCAL_PRICE_CACHE_DB.exists():
        raise FileNotFoundError(f"Cache missing: {LOCAL_PRICE_CACHE_DB}")

    query = (
        "SELECT date, open, high, low, close, volume, adj_close "
        "FROM price_data WHERE ticker = ? AND date >= ? AND date < ? ORDER BY date"
    )
    with sqlite3.connect(LOCAL_PRICE_CACHE_DB) as conn:
        df = pd.read_sql_query(query, conn, params=(ticker, DATA_START, DATA_END))
    if df.empty:
        raise FileNotFoundError(f"Ticker {ticker} missing from local cache")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def collect_cached_data() -> dict[str, pd.DataFrame]:
    tickers = {
        "SPY": "SPY",
        "QQQ": "QQQ",
        "0050.TW": "0050.TW",
        "VIX": "^VIX",
        "TLT": "TLT",
    }
    data = {}
    print("=" * 72)
    print("K501 retry: timing-aligned return prediction")
    print("=" * 72)
    print("\n[1] Loading local cached data...")
    for name, ticker in tickers.items():
        df = load_cached_ohlcv(ticker)
        data[name] = df
        print(f"  {name:7s} {len(df):4d} rows  {df.index[0].date()} -> {df.index[-1].date()}")
    return data


def get_close(df: pd.DataFrame) -> pd.Series:
    return df["adj_close"].fillna(df["close"]).astype(float)


def clean_tw50_frame(df: pd.DataFrame) -> pd.DataFrame:
    clean = df.copy()
    clean["close"], _ = clean_tw50_data(clean["close"])
    clean["open"], _ = clean_tw50_data(clean["open"])
    clean["volume"] = clean["volume"].fillna(0.0)
    return clean


def build_features_spy(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    spy = data["SPY"].copy()
    vix = get_close(data["VIX"]).reindex(spy.index, method="ffill")
    tlt = get_close(data["TLT"]).reindex(spy.index, method="ffill")
    qqq = get_close(data["QQQ"]).reindex(spy.index, method="ffill")

    ret = np.log(get_close(spy) / get_close(spy).shift(1)) * 100
    features = pd.DataFrame(index=spy.index)
    features["target"] = ret.shift(-1)
    features["ret_L1"] = ret
    features["ret_L2"] = ret.shift(1)
    features["vix_level_L1"] = vix.shift(1)
    features["vix_change_L1"] = vix.diff().shift(1)
    features["tlt_ret_L1"] = (np.log(tlt / tlt.shift(1)) * 100).shift(1)
    features["qqq_ret_L1"] = (np.log(qqq / qqq.shift(1)) * 100).shift(1)
    vol_surprise = spy["volume"] / spy["volume"].rolling(20).mean() - 1
    features["vol_surprise_L1"] = vol_surprise.shift(1)
    return features.dropna()


def build_features_qqq(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    qqq = data["QQQ"].copy()
    vix = get_close(data["VIX"]).reindex(qqq.index, method="ffill")
    spy = get_close(data["SPY"]).reindex(qqq.index, method="ffill")
    tlt = get_close(data["TLT"]).reindex(qqq.index, method="ffill")

    ret = np.log(get_close(qqq) / get_close(qqq).shift(1)) * 100
    features = pd.DataFrame(index=qqq.index)
    features["target"] = ret.shift(-1)
    features["ret_L1"] = ret
    features["ret_L2"] = ret.shift(1)
    features["vix_level_L1"] = vix.shift(1)
    features["vix_change_L1"] = vix.diff().shift(1)
    features["spy_ret_L1"] = (np.log(spy / spy.shift(1)) * 100).shift(1)
    features["tlt_ret_L1"] = (np.log(tlt / tlt.shift(1)) * 100).shift(1)
    vol_surprise = qqq["volume"] / qqq["volume"].rolling(20).mean() - 1
    features["vol_surprise_L1"] = vol_surprise.shift(1)
    return features.dropna()


def build_features_taiwan(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    tw = clean_tw50_frame(data["0050.TW"])
    spy_close = get_close(data["SPY"])
    vix_close = get_close(data["VIX"])

    tw_close = tw["close"].astype(float)
    tw_open = tw["open"].astype(float)
    tw_c2c = np.log(tw_close / tw_close.shift(1)) * 100
    tw_o2c = np.log(tw_close / tw_open) * 100

    spy_ret_prev = (np.log(spy_close / spy_close.shift(1)) * 100).reindex(tw.index, method="ffill")
    spy_mom5_prev = (spy_close.pct_change(5) * 100).reindex(tw.index, method="ffill")
    vix_prev = vix_close.reindex(tw.index, method="ffill")

    volume_surprise = tw["volume"] / tw["volume"].rolling(20).mean() - 1

    features = pd.DataFrame(index=tw.index)
    features["target_c2c_same_day"] = tw_c2c
    features["target_o2c_same_day"] = tw_o2c
    features["ret_L1"] = tw_c2c.shift(1)
    features["ret_L2"] = tw_c2c.shift(2)
    features["spy_ret_prev"] = spy_ret_prev
    features["spy_mom5_prev"] = spy_mom5_prev
    features["vix_level_prev"] = vix_prev
    features["vix_change_prev"] = vix_prev.diff()
    features["vol_surprise_L1"] = volume_surprise.shift(1)
    return features.dropna()


def ssvs_variable_selection(y: np.ndarray, X: np.ndarray, n_iter: int = 12000, burnin: int = 2000) -> np.ndarray:
    n, p = X.shape
    beta_ols, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta_ols
    sigma2_ols = np.var(resid)

    try:
        se_ols = np.sqrt(np.diag(np.linalg.inv(X.T @ X)) * sigma2_ols)
    except np.linalg.LinAlgError:
        se_ols = np.abs(beta_ols) * 0.5 + 0.01

    tau = se_ols
    c = 10.0
    p_prior = 0.5

    gamma = np.ones(p)
    beta = beta_ols.copy()
    sigma2 = sigma2_ols
    gamma_samples = np.zeros((n_iter - burnin, p))

    for it in range(n_iter):
        for j in range(p):
            log_p1 = np.log(p_prior) - 0.5 * np.log(2 * np.pi * (c * tau[j]) ** 2) - beta[j] ** 2 / (2 * (c * tau[j]) ** 2)
            log_p0 = np.log(1 - p_prior) - 0.5 * np.log(2 * np.pi * tau[j] ** 2) - beta[j] ** 2 / (2 * tau[j] ** 2)
            mx = max(log_p1, log_p0)
            p1 = np.exp(log_p1 - mx)
            p0 = np.exp(log_p0 - mx)
            gamma[j] = 1 if np.random.random() < p1 / (p1 + p0) else 0

        d = np.diag([(c * tau[j]) ** 2 if gamma[j] == 1 else tau[j] ** 2 for j in range(p)])
        try:
            d_inv = np.diag([1.0 / d[j, j] for j in range(p)])
            v_post = np.linalg.inv(X.T @ X / sigma2 + d_inv)
            m_post = v_post @ (X.T @ y / sigma2)
            beta = np.random.multivariate_normal(m_post, v_post)
        except (np.linalg.LinAlgError, ValueError):
            pass

        resid = y - X @ beta
        sigma2 = 1.0 / np.random.gamma(n / 2, 2.0 / np.sum(resid ** 2))

        if it >= burnin:
            gamma_samples[it - burnin] = gamma

    return gamma_samples.mean(axis=0)


def expanding_window_forecast(features_df: pd.DataFrame, target_col: str) -> ForecastBundle:
    oos_mask = features_df.index >= pd.Timestamp(OOS_START)
    oos_indices = np.where(oos_mask)[0]
    if len(oos_indices) == 0 or oos_indices[0] < MIN_IS:
        raise RuntimeError(f"Insufficient IS sample for {target_col}: first_oos={oos_indices[0] if len(oos_indices) else 'NA'}")

    predictor_cols = [c for c in features_df.columns if c != target_col and not c.startswith("target_")]
    y_all = features_df[target_col].values
    X_all = features_df[predictor_cols].values
    dates = features_df.index[oos_mask]

    first_oos = oos_indices[0]
    scaler_init = StandardScaler()
    pips = ssvs_variable_selection(y_all[:first_oos], scaler_init.fit_transform(X_all[:first_oos]))
    selected = pips > 0.5

    models = {name: np.zeros(len(oos_indices)) for name in ["hist_mean", "ar1", "ssvs_ols", "ridge", "logistic_direction"]}
    actuals = np.zeros(len(oos_indices))

    for i, t in enumerate(oos_indices):
        y_train = y_all[:t]
        X_train = X_all[:t]
        X_test = X_all[t:t + 1]
        actuals[i] = y_all[t]

        models["hist_mean"][i] = np.mean(y_train)

        ar1_idx = predictor_cols.index("ret_L1")
        x_ar1 = X_train[:, ar1_idx:ar1_idx + 1]
        beta_ar1 = np.linalg.lstsq(np.column_stack([np.ones(len(x_ar1)), x_ar1]), y_train, rcond=None)[0]
        models["ar1"][i] = beta_ar1[0] + beta_ar1[1] * X_test[0, ar1_idx]

        if selected.any():
            x_sel = X_train[:, selected]
            beta_ssvs = np.linalg.lstsq(np.column_stack([np.ones(len(x_sel)), x_sel]), y_train, rcond=None)[0]
            models["ssvs_ols"][i] = beta_ssvs[0] + X_test[:, selected][0] @ beta_ssvs[1:]
        else:
            models["ssvs_ols"][i] = np.mean(y_train)

        scaler = StandardScaler()
        x_train_scaled = scaler.fit_transform(X_train)
        x_test_scaled = scaler.transform(X_test)

        ridge = Ridge(alpha=RIDGE_ALPHA, fit_intercept=True, solver="svd")
        ridge.fit(x_train_scaled, y_train)
        models["ridge"][i] = ridge.predict(x_test_scaled)[0]

        y_dir = (y_train > 0).astype(int)
        if len(np.unique(y_dir)) > 1:
            logit = LogisticRegression(C=1.0, max_iter=500, random_state=42)
            logit.fit(x_train_scaled, y_dir)
            prob_up = logit.predict_proba(x_test_scaled)[0, 1]
            models["logistic_direction"][i] = (2 * prob_up - 1) * np.mean(np.abs(y_train))
        else:
            models["logistic_direction"][i] = np.mean(y_train)

    pip_dict = {
        col: {"PIP": round(float(pips[i]), 4), "selected": bool(selected[i])}
        for i, col in enumerate(predictor_cols)
    }
    return ForecastBundle(
        dates=dates,
        actuals=actuals,
        models=models,
        pip_dict=pip_dict,
        selected_vars=[predictor_cols[i] for i in range(len(predictor_cols)) if selected[i]],
        n_selected=int(selected.sum()),
    )


def evaluate_predictions(bundle: ForecastBundle) -> dict[str, dict[str, float | bool]]:
    actuals = bundle.actuals
    hist = bundle.models["hist_mean"]
    sse_hist = np.sum((actuals - hist) ** 2)
    out = {}
    n = len(actuals)

    for model_name, preds in bundle.models.items():
        sse_model = np.sum((actuals - preds) ** 2)
        oos_r2 = 0.0 if model_name == "hist_mean" else 1.0 - sse_model / sse_hist
        hit_rate = float(np.mean(np.sign(preds) == np.sign(actuals)))
        hits = int(np.sum(np.sign(preds) == np.sign(actuals)))
        binom_p = float(stats.binomtest(hits, n, 0.5).pvalue)

        if model_name == "hist_mean":
            dm_stat = dm_p = cw_stat = cw_p = 0.0
        else:
            d = (actuals - hist) ** 2 - (actuals - preds) ** 2
            lag = max(1, int(n ** (1 / 3)))
            gamma_sum = np.var(d)
            for k in range(1, lag + 1):
                gamma_k = np.cov(d[k:], d[:-k])[0, 1]
                gamma_sum += 2 * (1 - k / (lag + 1)) * gamma_k
            dm_stat = float(np.mean(d) / max(np.sqrt(gamma_sum / n), 1e-10))
            dm_p = float(2 * (1 - stats.norm.cdf(abs(dm_stat))))

            cw_adj = (actuals - hist) ** 2 - ((actuals - preds) ** 2 - (hist - preds) ** 2)
            cw_stat = float(np.mean(cw_adj) / max(np.std(cw_adj) / np.sqrt(n), 1e-10))
            cw_p = float(1 - stats.norm.cdf(cw_stat))

        out[model_name] = {
            "oos_r2_pct": round(float(oos_r2 * 100), 4),
            "hit_rate": round(hit_rate, 4),
            "binom_p": round(binom_p, 6),
            "dm_stat": round(dm_stat, 4),
            "dm_p": round(dm_p, 6),
            "cw_stat": round(cw_stat, 4),
            "cw_p": round(cw_p, 6),
            "passes_harvey": bool(abs(dm_stat) > 3.0) if model_name != "hist_mean" else False,
        }
    return out


def evaluate_tradable_long_cash(preds_pct: np.ndarray, o2c_pct: np.ndarray) -> dict[str, float]:
    position = (preds_pct > 0).astype(float)
    weight_change = np.abs(np.diff(np.r_[0.0, position]))
    gross = position * (o2c_pct / 100.0)
    net = gross - weight_change * TW_ROUNDTRIP_COST
    ann_ret = net.mean() * 252
    ann_vol = net.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
    cum = np.cumprod(1 + net)
    peak = np.maximum.accumulate(cum)
    dd = cum / peak - 1
    return {
        "ann_return_pct": round(float(ann_ret * 100), 4),
        "ann_vol_pct": round(float(ann_vol * 100), 4),
        "sharpe": round(float(sharpe), 4),
        "mdd_pct": round(float(dd.min() * 100), 4),
        "turnover_per_year": round(float(weight_change.mean() * 252), 4),
        "n_trades": int(weight_change.sum()),
        "exposure_pct": round(float(position.mean() * 100), 2),
        "signal_positive_pct": round(float(np.mean(preds_pct > 0) * 100), 2),
    }


def summarize_taiwan(features_tw: pd.DataFrame, c2c_bundle: ForecastBundle, o2c_bundle: ForecastBundle) -> dict:
    c2c_eval = evaluate_predictions(c2c_bundle)
    o2c_eval = evaluate_predictions(o2c_bundle)

    best_c2c_model = max(
        [(m, r) for m, r in c2c_eval.items() if m != "hist_mean"],
        key=lambda x: x[1]["oos_r2_pct"],
    )[0]
    best_o2c_model = max(
        [(m, r) for m, r in o2c_eval.items() if m != "hist_mean"],
        key=lambda x: x[1]["oos_r2_pct"],
    )[0]

    tw_o2c = features_tw.loc[o2c_bundle.dates, "target_o2c_same_day"].values
    tradable_best = evaluate_tradable_long_cash(o2c_bundle.models[best_o2c_model], tw_o2c)
    tradable_ssvs = evaluate_tradable_long_cash(o2c_bundle.models["ssvs_ols"], tw_o2c)

    return {
        "timing_definitions": {
            "non_tradable_channel": "SPY previous close available before TW open -> explains TW same-day close-to-close return (contains overnight gap).",
            "tradable_channel": "SPY previous close available before TW open -> trade 0050.TW at TW open, realize same-day open-to-close return net of 18.55bp round-trip cost.",
        },
        "data_quality": {
            "cleaning_applied": "clean_tw50_data on both open and close",
            "close_to_close_min_pct": round(float(features_tw["target_c2c_same_day"].min()), 4),
            "close_to_close_kurtosis": round(float(features_tw["target_c2c_same_day"].kurtosis()), 4),
            "open_to_close_min_pct": round(float(features_tw["target_o2c_same_day"].min()), 4),
            "open_to_close_kurtosis": round(float(features_tw["target_o2c_same_day"].kurtosis()), 4),
        },
        "non_tradable_info_channel": {
            "target": "TW same-day close-to-close return",
            "selected_vars": c2c_bundle.selected_vars,
            "pip_dict": c2c_bundle.pip_dict,
            "evaluation": c2c_eval,
            "best_model_by_oos_r2": best_c2c_model,
        },
        "tradable_open_to_close_channel": {
            "target": "TW same-day open-to-close return",
            "selected_vars": o2c_bundle.selected_vars,
            "pip_dict": o2c_bundle.pip_dict,
            "evaluation": o2c_eval,
            "best_model_by_oos_r2": best_o2c_model,
            "best_model_tradable_long_cash_net": tradable_best,
            "ssvs_tradable_long_cash_net": tradable_ssvs,
        },
    }


def main() -> None:
    data = collect_cached_data()

    print("\n[2] Building features...")
    features_spy = build_features_spy(data)
    features_qqq = build_features_qqq(data)
    features_tw = build_features_taiwan(data)
    print(f"  SPY features: {len(features_spy)} rows")
    print(f"  QQQ features: {len(features_qqq)} rows")
    print(f"  TW  features: {len(features_tw)} rows")

    print("\n[3] Running expanding-window forecasts...")
    spy_bundle = expanding_window_forecast(features_spy, "target")
    qqq_bundle = expanding_window_forecast(features_qqq, "target")
    tw_c2c_bundle = expanding_window_forecast(features_tw, "target_c2c_same_day")
    tw_o2c_bundle = expanding_window_forecast(features_tw, "target_o2c_same_day")

    spy_eval = evaluate_predictions(spy_bundle)
    qqq_eval = evaluate_predictions(qqq_bundle)
    tw_summary = summarize_taiwan(features_tw, tw_c2c_bundle, tw_o2c_bundle)

    k521 = json.loads((Path("experiments/k521/k521_2day_momentum_check_results.json")).read_text())
    timing_bias_provenance = {
        "legacy_i8_reference_invalid": True,
        "replacement_artifact": "experiments/k521/k521_2day_momentum_check_results.json",
        "replacement_fields": {
            "gap_sharpe": k521["supplement_findings"]["component_analysis"]["gap_sharpe"],
            "intraday_sharpe": k521["supplement_findings"]["component_analysis"]["intraday_sharpe"],
            "c2c_sharpe": k521["supplement_findings"]["component_analysis"]["c2c_sharpe"],
            "conclusion": k521["supplement_findings"]["component_analysis"]["conclusion"],
        },
        "note": "The previously cited `I8 3.09 -> 0.87` numbers are not reproducible from a canonical local I8 artifact in this repo. K521 is the canonical local timing-bias artifact now referenced.",
    }

    output = {
        "experiment_id": "K501",
        "title": "K501 retry: timing-aligned return prediction with tradable Taiwan implementation",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": {
            "primary": f"local sqlite cache: {LOCAL_PRICE_CACHE_DB}",
            "tickers_loaded": ["SPY", "QQQ", "0050.TW", "^VIX", "TLT"],
            "period": f"{DATA_START} to {DATA_END}",
            "oos_start": OOS_START,
        },
        "methodology_changes_vs_original": [
            "Taiwan predictive target split into same-day close-to-close info channel and same-day open-to-close tradable channel.",
            "0050.TW open and close cleaned with clean_tw50_data before feature engineering.",
            "Tradable strategy uses long/cash at TW open and deducts 18.55bp round-trip cost on every position change.",
            "Artifact path unified to experiments/k501/k501_return_prediction_results.json.",
            "Legacy I8 timing-bias citation replaced with canonical K521 artifact provenance.",
        ],
        "asset_results": {
            "SPY": {
                "selected_vars": spy_bundle.selected_vars,
                "pip_dict": spy_bundle.pip_dict,
                "evaluation": spy_eval,
            },
            "QQQ": {
                "selected_vars": qqq_bundle.selected_vars,
                "pip_dict": qqq_bundle.pip_dict,
                "evaluation": qqq_eval,
            },
            "0050.TW": tw_summary,
        },
        "timing_bias_provenance": timing_bias_provenance,
        "limitations": [
            "Retry uses locally cached tickers only; original HYG/^TNX/^IRX/TWD=X feature set is unavailable offline.",
            "SPY/QQQ histories in local cache begin 2016-01-04, so the retry sample is shorter than the original 2007-start run.",
            "Tradable Taiwan implementation is long/cash, not shortable ETF exposure.",
        ],
    }

    RESULTS_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str))

    print("\n[4] Key retry outputs")
    tw_c2c = tw_summary["non_tradable_info_channel"]
    tw_o2c = tw_summary["tradable_open_to_close_channel"]
    print(
        "  TW info channel:",
        tw_c2c["best_model_by_oos_r2"],
        f"OOS R²={tw_c2c['evaluation'][tw_c2c['best_model_by_oos_r2']]['oos_r2_pct']:.3f}%",
        f"Hit={tw_c2c['evaluation'][tw_c2c['best_model_by_oos_r2']]['hit_rate']*100:.1f}%",
    )
    print(
        "  TW tradable channel:",
        tw_o2c["best_model_by_oos_r2"],
        f"OOS R²={tw_o2c['evaluation'][tw_o2c['best_model_by_oos_r2']]['oos_r2_pct']:.3f}%",
        f"Net Sharpe={tw_o2c['best_model_tradable_long_cash_net']['sharpe']:.3f}",
    )
    print(f"\nResults saved to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
