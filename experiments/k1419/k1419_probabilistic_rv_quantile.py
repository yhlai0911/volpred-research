#!/usr/bin/env python3
"""
K1419: Probabilistic volatility-quantile pilot with local offline data.

Scope note:
- Full brief asked for HAR-RV + GJR-GARCH conditional quantiles on long 5-min RV.
- Local canonical intraday RV coverage is too sparse for a 2012-2026 honest run
  (SPY daily RV only 99 days; 0050 only 72 non-null days; no QQQ daily RV file).
- This pilot therefore uses a common range-based daily variance proxy
  (Parkinson variance) across SPY / QQQ / 0050.TW for 2023-2026, and asks a
  narrower question: does direct quantile HAR improve pinball loss versus
  Gaussian / empirical residual quantiles built on the same HAR point forecast?
"""

from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import norm

try:
    from volpred.stats.model_evaluation import dm_test
    from volpred.utils import clean_tw50_data
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from volpred.stats.model_evaluation import dm_test
    from volpred.utils import clean_tw50_data


ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = EXPERIMENT_DIR / "k1419_probabilistic_rv_quantile_results.json"
LOCAL_PRICE_CACHE_DB = ROOT / "data" / "cache" / "price_cache.db"
SPY_DAILY_RV = ROOT / "data" / "intraday" / "SPY_daily_rv.csv"
TW_DAILY_RV = ROOT / "data" / "intraday" / "0050_TW_daily_rv.csv"

START = "2023-01-03"
OOS_START = "2025-01-02"
TAUS = [0.05, 0.25, 0.50, 0.75, 0.95]
REFIT_EVERY = 21
MIN_TRAIN = 180
EPS = 1e-12


@dataclass
class ForecastOutput:
    dates: list[str]
    actual: np.ndarray
    gaussian: dict[float, np.ndarray]
    empirical: dict[float, np.ndarray]
    qhar: dict[float, np.ndarray]


def load_cached_ohlcv(ticker: str) -> pd.DataFrame:
    query = (
        "SELECT date, open, high, low, close, adj_close "
        "FROM price_data WHERE ticker = ? AND date >= ? ORDER BY date"
    )
    with sqlite3.connect(LOCAL_PRICE_CACHE_DB) as conn:
        df = pd.read_sql_query(query, conn, params=(ticker, START))
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def load_daily_rv(path: Path) -> pd.Series:
    if not path.exists():
        return pd.Series(dtype=float)
    df = pd.read_csv(path)
    if df.empty:
        return pd.Series(dtype=float)
    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col])
    return pd.Series(df["rv_5min"].values, index=df[date_col]).sort_index()


def build_proxy_series(asset: str, ticker: str) -> pd.DataFrame:
    df = load_cached_ohlcv(ticker)
    if asset == "0050.TW":
        for col in ["open", "high", "low", "close"]:
            df[col], _ = clean_tw50_data(df[col])
    close = df["adj_close"].fillna(df["close"]).astype(float)
    ret = np.log(close / close.shift(1))
    r2 = ret.pow(2)

    hl = np.log(df["high"].astype(float) / df["low"].astype(float))
    park = hl.pow(2) / (4.0 * np.log(2.0))
    park = park.replace([np.inf, -np.inf], np.nan)

    out = pd.DataFrame(index=df.index)
    out["return"] = ret
    out["r2"] = r2
    out["parkinson_var"] = park
    out["log_proxy"] = np.log(np.maximum(park, EPS))

    if asset == "SPY":
        out["daily_rv_5min"] = load_daily_rv(SPY_DAILY_RV).reindex(out.index)
    elif asset == "0050.TW":
        out["daily_rv_5min"] = load_daily_rv(TW_DAILY_RV).reindex(out.index)
    else:
        out["daily_rv_5min"] = np.nan
    return out.dropna(subset=["return", "r2", "parkinson_var", "log_proxy"])


def build_har_features(df: pd.DataFrame) -> pd.DataFrame:
    x = pd.DataFrame(index=df.index)
    x["target"] = df["log_proxy"]
    x["lag1"] = df["log_proxy"].shift(1)
    x["avg5"] = df["log_proxy"].rolling(5).mean().shift(1)
    x["avg22"] = df["log_proxy"].rolling(22).mean().shift(1)
    x["ret_abs_lag1"] = df["return"].abs().shift(1)
    x["r2_lag1"] = df["r2"].shift(1)
    return x.dropna()


def fit_ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.linalg.lstsq(np.column_stack([np.ones(len(X)), X]), y, rcond=None)[0]


def predict_ols(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    return np.column_stack([np.ones(len(X)), X]) @ beta


def fit_quantile_regression(X: np.ndarray, y: np.ndarray, tau: float) -> np.ndarray:
    beta0 = fit_ols(X, y)

    def objective(beta: np.ndarray) -> float:
        pred = predict_ols(beta, X)
        e = y - pred
        loss = np.where(e >= 0, tau * e, (tau - 1.0) * e)
        return float(np.mean(loss))

    res = minimize(objective, beta0, method="Powell", options={"maxiter": 3000, "xtol": 1e-6, "ftol": 1e-6})
    return np.asarray(res.x if res.success else beta0, dtype=float)


def pinball_loss(y: np.ndarray, q: np.ndarray, tau: float) -> np.ndarray:
    e = y - q
    return np.where(e >= 0, tau * e, (tau - 1.0) * e)


def harvey_significant(dm_t: float) -> bool:
    return bool(abs(dm_t) > 3.0)


def run_asset(asset: str, ticker: str) -> tuple[ForecastOutput, dict]:
    proxy = build_proxy_series(asset, ticker)
    feats = build_har_features(proxy)
    feats = feats[feats.index >= pd.Timestamp("2024-01-01")]
    oos_mask = feats.index >= pd.Timestamp(OOS_START)
    oos_idx = np.where(oos_mask)[0]
    if len(oos_idx) == 0 or oos_idx[0] < MIN_TRAIN:
        raise RuntimeError(f"{asset}: insufficient train history for OOS")

    X_all = feats[["lag1", "avg5", "avg22", "ret_abs_lag1", "r2_lag1"]].to_numpy()
    y_all = feats["target"].to_numpy()

    forecasts = ForecastOutput(
        dates=[d.strftime("%Y-%m-%d") for d in feats.index[oos_mask]],
        actual=y_all[oos_mask],
        gaussian={tau: np.zeros(len(oos_idx)) for tau in TAUS},
        empirical={tau: np.zeros(len(oos_idx)) for tau in TAUS},
        qhar={tau: np.zeros(len(oos_idx)) for tau in TAUS},
    )

    ols_beta = None
    q_betas: dict[float, np.ndarray] = {}
    resid_std = None
    resid_emp_q: dict[float, float] = {}

    for j, t in enumerate(oos_idx):
        if j % REFIT_EVERY == 0 or ols_beta is None:
            X_train = X_all[:t]
            y_train = y_all[:t]
            ols_beta = fit_ols(X_train, y_train)
            ols_pred_train = predict_ols(ols_beta, X_train)
            resid = y_train - ols_pred_train
            resid_std = float(np.std(resid, ddof=1))
            resid_emp_q = {tau: float(np.quantile(resid, tau)) for tau in TAUS}
            q_betas = {tau: fit_quantile_regression(X_train, y_train, tau) for tau in TAUS}

        x_test = X_all[t:t + 1]
        mean_hat = float(predict_ols(ols_beta, x_test)[0])
        for tau in TAUS:
            forecasts.gaussian[tau][j] = mean_hat + norm.ppf(tau) * resid_std
            forecasts.empirical[tau][j] = mean_hat + resid_emp_q[tau]
            forecasts.qhar[tau][j] = float(predict_ols(q_betas[tau], x_test)[0])

    tau_summary = {}
    for tau in TAUS:
        actual = forecasts.actual
        losses_g = pinball_loss(actual, forecasts.gaussian[tau], tau)
        losses_e = pinball_loss(actual, forecasts.empirical[tau], tau)
        losses_q = pinball_loss(actual, forecasts.qhar[tau], tau)
        dm_e_t, dm_e_p = dm_test(losses_e, losses_g)
        dm_q_t, dm_q_p = dm_test(losses_q, losses_g)
        tau_summary[str(tau)] = {
            "gaussian": {
                "pinball_mean": round(float(losses_g.mean()), 8),
                "coverage": round(float(np.mean(actual <= forecasts.gaussian[tau])), 4),
            },
            "empirical": {
                "pinball_mean": round(float(losses_e.mean()), 8),
                "coverage": round(float(np.mean(actual <= forecasts.empirical[tau])), 4),
                "dm_t_vs_gaussian": round(float(dm_e_t), 4),
                "dm_p_vs_gaussian": round(float(dm_e_p), 6),
                "harvey_gate": harvey_significant(dm_e_t),
            },
            "qhar": {
                "pinball_mean": round(float(losses_q.mean()), 8),
                "coverage": round(float(np.mean(actual <= forecasts.qhar[tau])), 4),
                "dm_t_vs_gaussian": round(float(dm_q_t), 4),
                "dm_p_vs_gaussian": round(float(dm_q_p), 6),
                "harvey_gate": harvey_significant(dm_q_t),
            },
        }

    daily_rv_non_null = int(proxy["daily_rv_5min"].notna().sum())
    diag = {
        "rows_total": int(len(proxy)),
        "rows_model": int(len(feats)),
        "oos_rows": int(len(forecasts.actual)),
        "daily_rv_non_null": daily_rv_non_null,
        "target_used": "log_5min_rv" if daily_rv_non_null >= 200 else "log_parkinson_proxy",
    }
    return forecasts, {"diagnostics": diag, "quantile_results": tau_summary}


def main() -> None:
    assets = {
        "SPY": "SPY",
        "QQQ": "QQQ",
        "0050.TW": "0050.TW",
    }
    results = {}
    any_harvey = []
    for asset, ticker in assets.items():
        _, res = run_asset(asset, ticker)
        results[asset] = res
        any_harvey.append(any(v["qhar"]["harvey_gate"] or v["empirical"]["harvey_gate"] for v in res["quantile_results"].values()))

    output = {
        "experiment_id": "K1419",
        "title": "Probabilistic volatility-quantile pilot with local offline proxies",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "status": "pilot_offline_first_pass",
            "reason": "Long-horizon 5-min RV coverage is unavailable locally for SPY/QQQ/0050, so this run uses Parkinson range proxy as the common target when daily RV files are too short.",
            "oos_start": OOS_START,
            "taus": TAUS,
            "refit_every_days": REFIT_EVERY,
        },
        "methodology": {
            "point_model": "HAR-style OLS on log variance proxy",
            "quantile_models": [
                "Gaussian residual quantile around HAR point forecast",
                "Empirical residual quantile around HAR point forecast",
                "Direct quantile HAR regression",
            ],
            "evaluation": [
                "Pinball loss per tau",
                "Coverage vs nominal tau",
                "DM test on pointwise pinball loss vs Gaussian baseline",
                "Harvey gate |t| > 3.0",
            ],
        },
        "asset_results": results,
        "summary": {
            "assets_with_any_harvey_pass": int(sum(any_harvey)),
            "harvey_pass_assets": [asset for asset, passed in zip(assets.keys(), any_harvey) if passed],
        },
        "limitations": [
            "This is not the full brief-specified HAR-RV / GJR-GARCH / Fissler-Ziegel experiment.",
            "SPY and 0050 local daily 5-min RV files only cover 2026; QQQ has no local daily RV file.",
            "Therefore the common comparison target is a range-based proxy, not canonical long-horizon intraday RV.",
            "VaR/ES mapping is deferred to a compute-queue follow-up once long-horizon intraday RV coverage is materialized.",
        ],
    }
    RESULTS_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
