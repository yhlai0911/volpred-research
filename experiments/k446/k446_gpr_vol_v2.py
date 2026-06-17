"""
K446 v2: GPR and SPY realized volatility with embargoed OOS tests.

This rerun fixes the 2026-06-18 Codex audit failures in the original K446
script:
  1. Forward-label OOS leakage via h-step train-tail embargo.
  2. 21-day DM tests using h=21 and Harvey-Leybourne-Newbold correction.
  3. HAC/Newey-West coefficient tests for incremental GPR regressions.
  4. AIC/BIC lag selection for Granger/VAR tests.
  5. Canonical variance QLIKE.
"""

from __future__ import annotations

import json
import math
import os
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from sklearn.linear_model import Ridge
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant
from statsmodels.tsa.api import VAR
from statsmodels.tsa.stattools import adfuller, grangercausalitytests


EXPERIMENT_DIR = Path(__file__).resolve().parent
DATA_DIR = EXPERIMENT_DIR / "data"
RESULTS_FILE = EXPERIMENT_DIR / "k446_gpr_vol_v2_results.json"
DATASET_FILE = DATA_DIR / "k446_v2_merged_dataset.csv"
GPR_CACHE = DATA_DIR / "gpr_daily_recent.xls"

SAMPLE_START = "2000-01-01"
SAMPLE_END = "2026-03-25"
OOS_START = pd.Timestamp("2023-01-01")
OOS_END = pd.Timestamp("2024-12-31")
RIDGE_ALPHA = 1.0
HAC_BUFFER = 5
RANDOM_SEED = 42


@dataclass(frozen=True)
class HorizonSpec:
    label: str
    target: str
    end_col: str
    h: int


HORIZONS = {
    "rv5_fwd": HorizonSpec("rv5_fwd", "rv5_fwd", "rv5_fwd_end", 5),
    "rv21_fwd": HorizonSpec("rv21_fwd", "rv21_fwd", "rv21_fwd_end", 21),
}


def _json_default(obj):
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return str(obj)


def load_gpr_data() -> pd.DataFrame:
    """Load Caldara-Iacoviello daily GPR data, pinning a local copy."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not GPR_CACHE.exists():
        url = "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls"
        urllib.request.urlretrieve(url, GPR_CACHE)

    raw = pd.read_excel(GPR_CACHE)
    gpr = raw[["date", "GPRD", "GPRD_ACT", "GPRD_THREAT"]].copy()
    gpr.columns = ["date", "gpr", "gpr_act", "gpr_threat"]
    gpr["date"] = pd.to_datetime(gpr["date"])
    return gpr.set_index("date").sort_index().dropna(subset=["gpr"])


def _download_series(ticker: str, start: str, end: str) -> pd.DataFrame:
    data = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    if data.empty:
        raise RuntimeError(f"yfinance returned no data for {ticker}")
    return data


def _target_end_dates(index: pd.Index, h: int) -> pd.Series:
    values = np.empty(len(index), dtype="datetime64[ns]")
    values[:] = np.datetime64("NaT")
    if len(index) > h:
        values[:-h] = index[h:].values
    return pd.Series(pd.to_datetime(values), index=index)


def load_market_data(start: str = SAMPLE_START, end: str = SAMPLE_END):
    spy = _download_series("SPY", start, end)
    vix = _download_series("^VIX", start, end)

    spy_ret = spy["Close"].pct_change().dropna()
    spy_ret.name = "spy_ret"

    rv21 = spy_ret.rolling(21).std() * np.sqrt(252) * 100
    rv21.name = "rv21"

    rv5_fwd = spy_ret.rolling(5).std().shift(-5) * np.sqrt(252) * 100
    rv5_fwd.name = "rv5_fwd"
    rv21_fwd = spy_ret.rolling(21).std().shift(-21) * np.sqrt(252) * 100
    rv21_fwd.name = "rv21_fwd"

    vix_close = vix["Close"].copy()
    vix_close.name = "vix"

    return spy_ret, rv21, rv5_fwd, rv21_fwd, vix_close


def prepare_dataset(
    gpr: pd.DataFrame,
    spy_ret: pd.Series,
    rv21: pd.Series,
    rv5_fwd: pd.Series,
    rv21_fwd: pd.Series,
    vix_close: pd.Series,
) -> pd.DataFrame:
    df = pd.DataFrame(index=spy_ret.index)
    df["spy_ret"] = spy_ret
    df["rv21"] = rv21
    df["rv5_fwd"] = rv5_fwd
    df["rv21_fwd"] = rv21_fwd
    df["rv5_fwd_end"] = _target_end_dates(df.index, 5)
    df["rv21_fwd_end"] = _target_end_dates(df.index, 21)
    df["vix"] = vix_close

    gpr_aligned = gpr.reindex(df.index, method="ffill")
    df["gpr"] = gpr_aligned["gpr"]
    df["gpr_act"] = gpr_aligned["gpr_act"]
    df["gpr_threat"] = gpr_aligned["gpr_threat"]

    df["gpr_ma7"] = df["gpr"].rolling(7).mean()
    df["gpr_ma21"] = df["gpr"].rolling(21).mean()
    df["gpr_std21"] = df["gpr"].rolling(21).std()
    df["gpr_zscore"] = (df["gpr"] - df["gpr_ma21"]) / df["gpr_std21"]
    df["gpr_change"] = df["gpr"].pct_change(5)
    df["gpr_log"] = np.log1p(df["gpr"])

    df["vix_ma5"] = df["vix"].rolling(5).mean()
    df["vix_change"] = df["vix"].pct_change(5)

    lag_cols = [
        "gpr",
        "gpr_ma7",
        "gpr_ma21",
        "gpr_zscore",
        "gpr_change",
        "gpr_log",
        "gpr_act",
        "gpr_threat",
        "vix",
        "vix_ma5",
        "vix_change",
        "rv21",
    ]
    for col in lag_cols:
        df[f"{col}_lag1"] = df[col].shift(1)

    return df.dropna()


def qlike_variance(actual_vol: np.ndarray, forecast_vol: np.ndarray) -> float:
    loss = qlike_variance_pointwise(actual_vol, forecast_vol)
    return float(np.nanmean(loss))


def qlike_variance_pointwise(actual_vol: np.ndarray, forecast_vol: np.ndarray) -> np.ndarray:
    actual_var = np.maximum(np.asarray(actual_vol, dtype=float) ** 2, 1e-12)
    forecast_var = np.maximum(np.asarray(forecast_vol, dtype=float) ** 2, 1e-12)
    ratio = actual_var / forecast_var
    return ratio - np.log(ratio) - 1


def mse(actual: np.ndarray, forecast: np.ndarray) -> float:
    return float(np.mean((np.asarray(actual) - np.asarray(forecast)) ** 2))


def r2_oos(actual: np.ndarray, forecast: np.ndarray) -> float:
    actual = np.asarray(actual)
    forecast = np.asarray(forecast)
    ss_res = float(np.sum((actual - forecast) ** 2))
    ss_tot = float(np.sum((actual - np.mean(actual)) ** 2))
    return float(1 - ss_res / ss_tot) if ss_tot > 0 else np.nan


def dm_hln(loss1: np.ndarray, loss2: np.ndarray, h: int) -> dict:
    """Two-sided DM test with Newey-West LRV and HLN small-sample adjustment.

    loss1 - loss2 > 0 means model 2 has lower average loss.
    """
    d = np.asarray(loss1, dtype=float) - np.asarray(loss2, dtype=float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n <= max(10, h + 1):
        return {"n": int(n), "error": "insufficient_observations"}

    d_bar = float(np.mean(d))
    centered = d - d_bar
    gamma0 = float(np.dot(centered, centered) / n)
    lrv = gamma0
    max_lag = min(h - 1, n - 1)
    autocovariances = []
    for lag in range(1, max_lag + 1):
        gamma = float(np.dot(centered[lag:], centered[:-lag]) / n)
        weight = 1.0 - lag / (max_lag + 1.0)
        lrv += 2.0 * weight * gamma
        autocovariances.append({"lag": lag, "weight": weight, "gamma": gamma})

    if lrv <= 0 or not np.isfinite(lrv):
        return {
            "n": int(n),
            "mean_loss_diff": d_bar,
            "error": "nonpositive_long_run_variance",
            "long_run_variance": float(lrv),
        }

    dm_stat = d_bar / math.sqrt(lrv / n)
    hln_factor = math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    hln_stat = dm_stat * hln_factor
    p_value = 2 * (1 - stats.t.cdf(abs(hln_stat), df=n - 1))
    return {
        "n": int(n),
        "h": int(h),
        "max_lag": int(max_lag),
        "mean_loss_diff": d_bar,
        "long_run_variance": float(lrv),
        "dm_statistic_raw": float(dm_stat),
        "hln_factor": float(hln_factor),
        "dm_statistic_hln": float(hln_stat),
        "p_value_hln": float(p_value),
        "model2_better": bool(d_bar > 0),
        "reject_5pct": bool(p_value < 0.05),
    }


def _fit_ridge(train: pd.DataFrame, test: pd.DataFrame, features: list[str], target: str):
    model = Ridge(alpha=RIDGE_ALPHA)
    model.fit(train[features].values, train[target].values)
    pred = np.maximum(model.predict(test[features].values), 0.1)
    return model, pred


def fixed_oos_forecasting(df: pd.DataFrame, spec: HorizonSpec) -> dict:
    feature_sets = {
        "baseline_rv": ["rv21_lag1"],
        "vix_only": ["vix_lag1", "vix_ma5_lag1"],
        "gpr_only": ["gpr_lag1", "gpr_ma7_lag1", "gpr_ma21_lag1", "gpr_zscore_lag1"],
        "gpr_decomposed": ["gpr_act_lag1", "gpr_threat_lag1", "gpr_ma21_lag1"],
        "vix_gpr": ["vix_lag1", "vix_ma5_lag1", "gpr_lag1", "gpr_ma7_lag1", "gpr_zscore_lag1"],
        "kitchen_sink": [
            "rv21_lag1",
            "vix_lag1",
            "vix_ma5_lag1",
            "vix_change_lag1",
            "gpr_lag1",
            "gpr_ma7_lag1",
            "gpr_ma21_lag1",
            "gpr_zscore_lag1",
            "gpr_change_lag1",
            "gpr_log_lag1",
            "gpr_act_lag1",
            "gpr_threat_lag1",
        ],
    }

    all_needed = sorted(set(sum(feature_sets.values(), []) + [spec.target, spec.end_col]))
    data = df[all_needed].dropna().copy()
    train_mask = (data.index < OOS_START) & (data[spec.end_col] < OOS_START)
    oos_mask = (data.index >= OOS_START) & (data.index <= OOS_END)
    train = data.loc[train_mask]
    oos = data.loc[oos_mask]
    if len(oos) < 50:
        raise RuntimeError(f"{spec.label} has too few OOS rows: {len(oos)}")

    results = {}
    forecasts = {}
    for name, features in feature_sets.items():
        model, pred = _fit_ridge(train, oos, features, spec.target)
        actual = oos[spec.target].values
        se = (actual - pred) ** 2
        ql = qlike_variance_pointwise(actual, pred)
        results[name] = {
            "features": features,
            "n_train_embargoed": int(len(train)),
            "n_train_original_style": int(((data.index < OOS_START)).sum()),
            "n_train_dropped_by_embargo": int(((data.index < OOS_START)).sum() - len(train)),
            "n_oos": int(len(oos)),
            "first_oos_origin": oos.index.min().date().isoformat(),
            "last_oos_origin": oos.index.max().date().isoformat(),
            "last_oos_target_end": pd.Timestamp(oos[spec.end_col].max()).date().isoformat(),
            "mse": float(mse(actual, pred)),
            "rmse": float(math.sqrt(mse(actual, pred))),
            "qlike_variance": float(np.nanmean(ql)),
            "r2_oos": float(r2_oos(actual, pred)),
            "coefficients": {features[i]: float(model.coef_[i]) for i in range(len(features))} | {"intercept": float(model.intercept_)},
        }
        forecasts[name] = {
            "actual": actual,
            "forecast": pred,
            "squared_error": se,
            "qlike_loss": ql,
        }

    if "baseline_rv" in forecasts:
        base = forecasts["baseline_rv"]
        for name, fc in forecasts.items():
            if name == "baseline_rv":
                continue
            results[name]["dm_mse_vs_baseline_hln"] = dm_hln(base["squared_error"], fc["squared_error"], spec.h)
            results[name]["dm_qlike_vs_baseline_hln"] = dm_hln(base["qlike_loss"], fc["qlike_loss"], spec.h)

    if "vix_only" in forecasts and "vix_gpr" in forecasts:
        vix = forecasts["vix_only"]
        vix_gpr = forecasts["vix_gpr"]
        results["vix_gpr"]["dm_mse_vs_vix_only_hln"] = dm_hln(vix["squared_error"], vix_gpr["squared_error"], spec.h)
        results["vix_gpr"]["dm_qlike_vs_vix_only_hln"] = dm_hln(vix["qlike_loss"], vix_gpr["qlike_loss"], spec.h)

    return results


def incremental_hac_analysis(df: pd.DataFrame, spec: HorizonSpec, hac_buffer: int = HAC_BUFFER) -> dict:
    cols = ["vix_lag1", "gpr_lag1", "gpr_zscore_lag1", spec.target]
    data = df[cols].dropna().copy()
    y = data[spec.target].values
    bandwidth = spec.h + hac_buffer

    def fit_model(feature_cols: list[str]):
        X = add_constant(data[feature_cols].values)
        plain = OLS(y, X).fit()
        hac = OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": bandwidth})
        return plain, hac

    m_vix_plain, m_vix_hac = fit_model(["vix_lag1"])
    m_gpr_plain, m_gpr_hac = fit_model(["vix_lag1", "gpr_lag1"])
    m_z_plain, m_z_hac = fit_model(["vix_lag1", "gpr_zscore_lag1"])

    resid_target = OLS(y, add_constant(data["vix_lag1"].values)).fit().resid
    resid_gpr = OLS(data["gpr_lag1"].values, add_constant(data["vix_lag1"].values)).fit().resid
    resid_z = OLS(data["gpr_zscore_lag1"].values, add_constant(data["vix_lag1"].values)).fit().resid
    partial_gpr = float(np.corrcoef(resid_target, resid_gpr)[0, 1])
    partial_z = float(np.corrcoef(resid_target, resid_z)[0, 1])

    def model_block(plain, hac, idx: int | None = None):
        out = {
            "r2": float(plain.rsquared),
            "adj_r2": float(plain.rsquared_adj),
            "aic": float(plain.aic),
            "bic": float(plain.bic),
            "hac_bandwidth": int(bandwidth),
        }
        if idx is not None:
            out.update(
                {
                    "coef": float(plain.params[idx]),
                    "ols_tstat": float(plain.tvalues[idx]),
                    "ols_pvalue": float(plain.pvalues[idx]),
                    "hac_tstat": float(hac.tvalues[idx]),
                    "hac_pvalue": float(hac.pvalues[idx]),
                    "hac_se": float(hac.bse[idx]),
                    "exceeds_abs3_hac": bool(abs(hac.tvalues[idx]) > 3.0),
                }
            )
        return out

    return {
        "n_obs": int(len(data)),
        "hac_bandwidth": int(bandwidth),
        "vix_only": model_block(m_vix_plain, m_vix_hac),
        "vix_plus_gpr": model_block(m_gpr_plain, m_gpr_hac, idx=2),
        "vix_plus_gpr_zscore": model_block(m_z_plain, m_z_hac, idx=2),
        "partial_correlations": {
            "gpr_controlling_vix": partial_gpr,
            "gpr_zscore_controlling_vix": partial_z,
            "raw_gpr_hac_tstat": float(m_gpr_hac.tvalues[2]),
            "raw_gpr_hac_pvalue": float(m_gpr_hac.pvalues[2]),
            "zscore_gpr_hac_tstat": float(m_z_hac.tvalues[2]),
            "zscore_gpr_hac_pvalue": float(m_z_hac.pvalues[2]),
            "raw_gpr_exceeds_abs3_hac": bool(abs(m_gpr_hac.tvalues[2]) > 3.0),
            "zscore_gpr_exceeds_abs3_hac": bool(abs(m_z_hac.tvalues[2]) > 3.0),
        },
    }


def granger_aic_bic(df: pd.DataFrame, max_lag: int = 10) -> dict:
    out = {}

    def test_pair(target_col: str, predictor_col: str, name: str):
        pair = df[[target_col, predictor_col]].dropna().copy()
        if len(pair) > 5000:
            pair = pair.tail(5000)

        result = {"n_obs": int(len(pair)), "max_lag": int(max_lag)}
        for col in [target_col, predictor_col]:
            adf_stat, adf_p, *_ = adfuller(pair[col].values, maxlag=20)
            result[f"adf_{col}"] = {"statistic": float(adf_stat), "pvalue": float(adf_p)}

        model = VAR(pair)
        selected = model.select_order(maxlags=max_lag)
        selected_orders = {
            "aic": selected.selected_orders.get("aic"),
            "bic": selected.selected_orders.get("bic"),
            "hqic": selected.selected_orders.get("hqic"),
            "fpe": selected.selected_orders.get("fpe"),
        }
        result["selected_orders"] = {k: (None if v is None else int(v)) for k, v in selected_orders.items()}

        tests = {}
        for criterion in ["aic", "bic"]:
            lag = result["selected_orders"].get(criterion)
            if lag is None or lag < 1:
                tests[criterion] = {"lag": lag, "error": "selected_lag_less_than_1"}
                continue
            fit = model.fit(lag)
            causality = fit.test_causality(caused=target_col, causing=[predictor_col], kind="f")
            tests[criterion] = {
                "lag": int(lag),
                "f_statistic": float(causality.test_statistic),
                "pvalue": float(causality.pvalue),
                "reject_5pct": bool(causality.pvalue < 0.05),
            }
        result["selected_lag_tests"] = tests

        raw_lag_tests = {}
        gc_data = pair[[target_col, predictor_col]].values
        raw = grangercausalitytests(gc_data, maxlag=max_lag, verbose=False)
        for lag in range(1, max_lag + 1):
            raw_lag_tests[str(lag)] = {
                "f_statistic": float(raw[lag][0]["ssr_ftest"][0]),
                "pvalue": float(raw[lag][0]["ssr_ftest"][1]),
            }
        result["raw_lag_tests_for_comparison"] = raw_lag_tests
        out[name] = result

    test_pair("vix", "gpr", "GPR->VIX")
    test_pair("rv21", "gpr", "GPR->RV21")
    test_pair("gpr", "vix", "VIX->GPR")
    return out


def clean_expanding_oos(df: pd.DataFrame, spec: HorizonSpec) -> dict:
    features_vix = ["vix_lag1", "vix_ma5_lag1"]
    features_vix_gpr = ["vix_lag1", "vix_ma5_lag1", "gpr_lag1", "gpr_ma7_lag1", "gpr_zscore_lag1"]
    cols = features_vix_gpr + [spec.target, spec.end_col]
    data = df[cols].dropna().copy()
    dates = data.index

    start_idx = max(500, int((dates >= pd.Timestamp("2005-01-01")).argmax()))
    rows = []
    errors_vix = []
    errors_gpr = []
    skipped = 0

    for i in range(start_idx, len(data)):
        test_date = dates[i]
        train = data.iloc[:i]
        train = train[train[spec.end_col] < test_date]
        if len(train) < 100:
            skipped += 1
            continue

        test = data.iloc[i : i + 1]
        actual = float(test[spec.target].iloc[0])
        _, pred_vix = _fit_ridge(train, test, features_vix, spec.target)
        _, pred_gpr = _fit_ridge(train, test, features_vix_gpr, spec.target)
        e_vix = (actual - float(pred_vix[0])) ** 2
        e_gpr = (actual - float(pred_gpr[0])) ** 2
        errors_vix.append(e_vix)
        errors_gpr.append(e_gpr)
        rows.append({"date": test_date, "year": test_date.year, "e_vix": e_vix, "e_gpr": e_gpr})

    by_year = {}
    rows_df = pd.DataFrame(rows)
    for year, sub in rows_df.groupby("year"):
        mse_v = float(sub["e_vix"].mean())
        mse_g = float(sub["e_gpr"].mean())
        by_year[str(int(year))] = {
            "mse_vix": mse_v,
            "mse_vix_gpr": mse_g,
            "mse_ratio": float(mse_g / mse_v) if mse_v > 0 else None,
            "gpr_improves": bool(mse_g < mse_v),
            "n_obs": int(len(sub)),
        }

    errors_vix_arr = np.asarray(errors_vix)
    errors_gpr_arr = np.asarray(errors_gpr)
    return {
        "method": "expanding_window_with_h_step_train_tail_embargo",
        "skipped_initial_rows": int(skipped),
        "yearly_results": by_year,
        "overall": {
            "mse_vix": float(np.mean(errors_vix_arr)),
            "mse_vix_gpr": float(np.mean(errors_gpr_arr)),
            "dm_mse_hln": dm_hln(errors_vix_arr, errors_gpr_arr, spec.h),
            "n_total_oos": int(len(errors_vix_arr)),
        },
    }


def descriptive_and_regime(df: pd.DataFrame) -> dict:
    desc = {}
    for col in ["gpr", "gpr_act", "gpr_threat", "rv21", "vix", "spy_ret"]:
        s = df[col].dropna()
        desc[col] = {
            "mean": float(s.mean()),
            "std": float(s.std()),
            "skew": float(s.skew()),
            "kurtosis": float(s.kurtosis()),
            "min": float(s.min()),
            "max": float(s.max()),
            "n": int(len(s)),
        }

    target = "rv5_fwd"
    q = df["gpr"].quantile([0.5, 0.75, 0.9])
    tmp = df.copy()
    tmp["gpr_regime"] = "low"
    tmp.loc[tmp["gpr"] > q.loc[0.5], "gpr_regime"] = "medium"
    tmp.loc[tmp["gpr"] > q.loc[0.75], "gpr_regime"] = "high"
    tmp.loc[tmp["gpr"] > q.loc[0.9], "gpr_regime"] = "extreme"
    regime = {}
    for label in ["low", "medium", "high", "extreme"]:
        sub = tmp[tmp["gpr_regime"] == label][["gpr", "vix", target]].dropna()
        regime[label] = {
            "n_obs": int(len(sub)),
            "avg_gpr": float(sub["gpr"].mean()),
            "avg_vix": float(sub["vix"].mean()),
            "avg_rv": float(sub[target].mean()),
            "gpr_rv_corr": float(sub["gpr"].corr(sub[target])),
        }

    events = {
        "9/11": ("2001-09-01", "2001-12-31"),
        "Iraq_War": ("2003-03-01", "2003-06-30"),
        "Crimea": ("2014-02-01", "2014-06-30"),
        "US_China_Trade": ("2018-03-01", "2019-12-31"),
        "COVID": ("2020-01-01", "2020-06-30"),
        "Ukraine_War": ("2022-02-01", "2022-12-31"),
        "Israel_Hamas": ("2023-10-01", "2024-03-31"),
    }
    event_analysis = {}
    for name, (start, end) in events.items():
        sub = df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
        event_analysis[name] = {
            "n_days": int(len(sub)),
            "avg_gpr": float(sub["gpr"].mean()),
            "avg_rv": float(sub[target].mean()),
            "gpr_rv_corr": float(sub["gpr"].corr(sub[target])),
        }

    return {
        "descriptive_stats": desc,
        "regime_stats": regime,
        "event_analysis": event_analysis,
        "thresholds": {"p50": float(q.loc[0.5]), "p75": float(q.loc[0.75]), "p90": float(q.loc[0.9])},
        "notes": [
            "Regime and event outputs are descriptive/ex-post only.",
            "Inference claims should use pre-registered cutpoints or OOS regimes.",
        ],
    }


def compare_article_claims(results: dict) -> dict:
    rv5_inc = results["incremental_hac"]["rv5_fwd"]
    rv21_inc = results["incremental_hac"]["rv21_fwd"]
    rv21_dm = results["fixed_oos"]["rv21_fwd"]["vix_gpr"]["dm_mse_vs_vix_only_hln"]
    granger = results["granger_aic_bic"]["GPR->VIX"]

    aic_test = granger["selected_lag_tests"].get("aic", {})
    bic_test = granger["selected_lag_tests"].get("bic", {})
    event_corrs = [v["gpr_rv_corr"] for v in results["descriptive_regime"]["event_analysis"].values()]
    extreme = results["descriptive_regime"]["regime_stats"]["extreme"]

    raw_5_pass = rv5_inc["partial_correlations"]["raw_gpr_exceeds_abs3_hac"]
    raw_21_pass = rv21_inc["partial_correlations"]["raw_gpr_exceeds_abs3_hac"]
    z_5_pass = rv5_inc["partial_correlations"]["zscore_gpr_exceeds_abs3_hac"]
    z_21_pass = rv21_inc["partial_correlations"]["zscore_gpr_exceeds_abs3_hac"]

    return {
        "claim_1_raw_gpr_partial_hac": {
            "rv5_hac_t": rv5_inc["partial_correlations"]["raw_gpr_hac_tstat"],
            "rv21_hac_t": rv21_inc["partial_correlations"]["raw_gpr_hac_tstat"],
            "rv5_abs3_pass": raw_5_pass,
            "rv21_abs3_pass": raw_21_pass,
            "verdict": "SUPPORTED_AFTER_HAC" if raw_5_pass and raw_21_pass else "REVERSED_OR_WEAKENED",
        },
        "claim_2_zscore_sensitivity_hac": {
            "rv5_z_hac_t": rv5_inc["partial_correlations"]["zscore_gpr_hac_tstat"],
            "rv21_z_hac_t": rv21_inc["partial_correlations"]["zscore_gpr_hac_tstat"],
            "rv5_z_abs3_pass": z_5_pass,
            "rv21_z_abs3_pass": z_21_pass,
            "verdict": "PARTIAL_ONLY" if z_5_pass != z_21_pass else "CONSISTENT",
        },
        "claim_3_oos_vix_gpr_vs_vix_only": {
            "rv21_dm_hln_t": rv21_dm.get("dm_statistic_hln"),
            "rv21_dm_hln_p": rv21_dm.get("p_value_hln"),
            "rv21_model2_better": rv21_dm.get("model2_better"),
            "rv21_reject_5pct": rv21_dm.get("reject_5pct"),
            "verdict": "NO_SIGNIFICANT_IMPROVEMENT" if not rv21_dm.get("reject_5pct", False) else "REVERSED_SIGNIFICANT",
        },
        "claim_4_granger_gpr_to_vix": {
            "aic_lag": aic_test.get("lag"),
            "aic_pvalue": aic_test.get("pvalue"),
            "bic_lag": bic_test.get("lag"),
            "bic_pvalue": bic_test.get("pvalue"),
            "raw_lag1_pvalue": granger["raw_lag_tests_for_comparison"]["1"]["pvalue"],
            "verdict": "SUPPORTED_BY_SELECTED_LAGS"
            if (aic_test.get("reject_5pct") or bic_test.get("reject_5pct"))
            else "NOT_SUPPORTED_BY_SELECTED_LAGS",
        },
        "claim_5_event_corr_range": {
            "min": float(np.nanmin(event_corrs)),
            "max": float(np.nanmax(event_corrs)),
            "verdict": "DESCRIPTIVE_VERIFIED",
        },
        "claim_6_extreme_regime": {
            "n_obs": extreme["n_obs"],
            "corr": extreme["gpr_rv_corr"],
            "verdict": "DESCRIPTIVE_VERIFIED",
        },
    }


def main() -> dict:
    np.random.seed(RANDOM_SEED)
    gpr = load_gpr_data()
    spy_ret, rv21, rv5_fwd, rv21_fwd, vix_close = load_market_data()
    df = prepare_dataset(gpr, spy_ret, rv21, rv5_fwd, rv21_fwd, vix_close)
    df.to_csv(DATASET_FILE, index_label="date")

    fixed = {}
    inc = {}
    expanding = {}
    for spec in HORIZONS.values():
        fixed[spec.label] = fixed_oos_forecasting(df, spec)
        inc[spec.label] = incremental_hac_analysis(df, spec)
        expanding[spec.label] = clean_expanding_oos(df, spec)

    results = {
        "experiment_id": "K446_v2",
        "parent_experiment": "K446",
        "title": "Geopolitical Risk Index and SPY Realized Volatility, v2 embargo/HAC rerun",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "random_seed": RANDOM_SEED,
        "data_sources": {
            "gpr": "Caldara & Iacoviello daily GPR, pinned to experiments/k446/data/gpr_daily_recent.xls",
            "spy": "yfinance SPY close",
            "vix": "yfinance ^VIX close",
            "sample_request": f"{SAMPLE_START} to {SAMPLE_END}",
            "sample_period_after_cleaning": f"{df.index.min().date()} to {df.index.max().date()}",
            "n_observations": int(len(df)),
            "oos_origin_period": f"{OOS_START.date()} to {OOS_END.date()}",
            "merged_dataset_csv": str(DATASET_FILE.relative_to(EXPERIMENT_DIR)),
        },
        "method_fixes": [
            "Fixed OOS train rows require target_end < 2023-01-01.",
            "Expanding OOS train rows require target_end < test_origin_date.",
            "DM tests use Newey-West long-run variance and Harvey-Leybourne-Newbold small-sample t correction.",
            "21-day forward RV DM tests use h=21.",
            "Incremental regressions report HAC/Newey-West coefficient t-statistics with maxlags=h+5.",
            "Granger uses VAR lag selection by AIC and BIC, with raw lag tests retained only for comparison.",
            "QLIKE is computed on variance forecasts, not volatility levels.",
        ],
        "descriptive_regime": descriptive_and_regime(df),
        "fixed_oos": fixed,
        "incremental_hac": inc,
        "granger_aic_bic": granger_aic_bic(df),
        "clean_expanding_oos": expanding,
    }
    results["article_claim_comparison"] = compare_article_claims(results)

    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2, default=_json_default)

    print(json.dumps(results["article_claim_comparison"], indent=2, default=_json_default))
    print(f"Saved {RESULTS_FILE}")
    return results


if __name__ == "__main__":
    main()
