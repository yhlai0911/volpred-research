"""
Admissible constrained multivariate HAR / vMEM-lite guardrail.

Question
--------
Does enforcing positivity/admissibility constraints stabilize a multivariate
HAR-style variance system relative to unconstrained OLS?

The experiment uses six ETF daily squared-return variance proxies and a
multivariate HAR design matrix:
    RV_t ~ all assets' RV_{t-1}, RV_{t-1:t-5}, RV_{t-1:t-22}

Three estimators are compared per target asset:
    1. unconstrained OLS
    2. OLS coefficients projected to nonnegative values
    3. NNLS coefficients projected into a simple admissible region:
       intercept >= 0, all lag coefficients >= 0, sum lag coefficients <= 0.995

Run:
    python experiments/research_admissible_constrained_multivariate_har_vmem_gua/research_admissible_constrained_multivariate_har_vmem_gua.py
"""

from __future__ import annotations

import json
import os
import sys
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import lsq_linear
from scipy.stats import binomtest

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise, spearman_corr

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(line_buffering=True)

EXPERIMENT_ID = "research_admissible_constrained_multivariate_har_vmem_gua"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(SCRIPT_DIR, f"{EXPERIMENT_ID}_results.json")
CHART_PATH = os.path.join(SCRIPT_DIR, f"{EXPERIMENT_ID}_summary.png")

SEED = 42
ASSETS = ["SPY", "QQQ", "IWM", "TLT", "GLD", "HYG"]
START = "2007-01-01"
END = "2026-06-28"
OOS_START = "2020-01-01"
REFIT_EVERY = 63
MIN_TRAIN = 1500
FLOOR = 1e-10
ADMISSIBLE_MAX_LAG_SUM = 0.995
TARGET_VOL_ANNUAL = 0.12
MAX_LEVERAGE = 2.0


@dataclass
class FitResult:
    beta: np.ndarray
    raw_ols_beta: np.ndarray | None
    lag_sum: float
    admissible_scaled: bool
    status: str


def download_prices() -> pd.DataFrame:
    print(f"Downloading {ASSETS} {START}->{END}")
    df = yf.download(ASSETS, start=START, end=END, progress=False, auto_adjust=True)
    if df.empty:
        raise RuntimeError("yfinance returned empty dataframe")
    if isinstance(df.columns, pd.MultiIndex):
        close = df["Close"].copy()
    else:
        close = df[["Close"]].copy()
        close.columns = ASSETS[:1]
    close = close.dropna(how="all")
    close = close[ASSETS].dropna()
    if close.empty:
        raise RuntimeError("No complete close-price panel after dropna")
    return close


def build_panel(close: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, List[str]]:
    returns_pct = close.pct_change().dropna() * 100.0
    rv = returns_pct.pow(2)

    features = []
    names = []
    for asset in ASSETS:
        daily = rv[asset].shift(1)
        weekly = rv[asset].rolling(5).mean().shift(1)
        monthly = rv[asset].rolling(22).mean().shift(1)
        features.extend([daily, weekly, monthly])
        names.extend([f"{asset}_rv_d_lag1", f"{asset}_rv_w_lag1", f"{asset}_rv_m_lag1"])
    x = pd.concat(features, axis=1)
    x.columns = names

    data = pd.concat({"target": rv, "features": x}, axis=1).dropna()
    y = data["target"][ASSETS].copy()
    x = data["features"].copy()
    returns_pct = returns_pct.loc[y.index]
    return x, y, returns_pct


def add_intercept(x: np.ndarray) -> np.ndarray:
    return np.column_stack([np.ones(len(x)), x])


def fit_ols(x: np.ndarray, y: np.ndarray) -> FitResult:
    beta, *_ = np.linalg.lstsq(add_intercept(x), y, rcond=None)
    return FitResult(
        beta=beta,
        raw_ols_beta=beta.copy(),
        lag_sum=float(np.sum(beta[1:])),
        admissible_scaled=False,
        status="ok",
    )


def fit_projected_nonnegative(x: np.ndarray, y: np.ndarray) -> FitResult:
    raw = fit_ols(x, y).beta
    beta = np.maximum(raw, 0.0)
    return FitResult(
        beta=beta,
        raw_ols_beta=raw,
        lag_sum=float(np.sum(beta[1:])),
        admissible_scaled=False,
        status="ok",
    )


def fit_admissible_nnls(x: np.ndarray, y: np.ndarray) -> FitResult:
    x_i = add_intercept(x)
    res = lsq_linear(
        x_i,
        y,
        bounds=(0.0, np.inf),
        method="trf",
        lsmr_tol="auto",
        max_iter=500,
    )
    beta = np.maximum(res.x, 0.0)
    lag_sum = float(np.sum(beta[1:]))
    scaled = False
    if lag_sum > ADMISSIBLE_MAX_LAG_SUM:
        beta[1:] *= ADMISSIBLE_MAX_LAG_SUM / lag_sum
        lag_sum = float(np.sum(beta[1:]))
        scaled = True
    return FitResult(
        beta=beta,
        raw_ols_beta=None,
        lag_sum=lag_sum,
        admissible_scaled=scaled,
        status="ok" if res.success else "lsq_linear_not_success",
    )


def predict(beta: np.ndarray, x_row: np.ndarray) -> float:
    return float(add_intercept(x_row.reshape(1, -1))[0] @ beta)


def max_drawdown(returns: np.ndarray) -> float:
    if len(returns) == 0:
        return np.nan
    equity = np.cumprod(1.0 + np.asarray(returns, dtype=float))
    peak = np.maximum.accumulate(equity)
    dd = equity / peak - 1.0
    return float(np.min(dd))


def annualized_return(returns: np.ndarray) -> float:
    if len(returns) == 0:
        return np.nan
    equity = float(np.prod(1.0 + returns))
    years = len(returns) / 252.0
    if years <= 0 or equity <= 0:
        return np.nan
    return equity ** (1.0 / years) - 1.0


def volatility_overlay_metrics(forecast_var_pct2: np.ndarray, returns_pct: np.ndarray) -> Dict:
    pred = np.maximum(np.asarray(forecast_var_pct2, dtype=float), FLOOR)
    ret = np.asarray(returns_pct, dtype=float) / 100.0
    target_daily_pct = TARGET_VOL_ANNUAL * 100.0 / np.sqrt(252.0)
    weights = np.clip(target_daily_pct / np.sqrt(pred), 0.0, MAX_LEVERAGE)
    strat_ret = weights * ret
    turnover = np.abs(np.diff(weights, prepend=weights[0]))
    return {
        "mean_weight": float(np.mean(weights)),
        "mean_daily_turnover": float(np.mean(turnover)),
        "annualized_return": float(annualized_return(strat_ret)),
        "annualized_vol": float(np.std(strat_ret, ddof=1) * np.sqrt(252.0)),
        "max_drawdown": float(max_drawdown(strat_ret)),
    }


def holm_adjust(p_values: Dict[str, float]) -> Dict[str, float]:
    items = sorted(p_values.items(), key=lambda kv: kv[1])
    m = len(items)
    adjusted = {}
    running = 0.0
    for rank, (key, p) in enumerate(items):
        adj = min(1.0, (m - rank) * p)
        running = max(running, adj)
        adjusted[key] = running
    return adjusted


def run_rolling(x: pd.DataFrame, y: pd.DataFrame, returns_pct: pd.DataFrame) -> Dict:
    model_names = ["OLS", "ProjectedNonnegative", "AdmissibleNNLS"]
    forecasts = {
        model: pd.DataFrame(index=y.index[y.index >= OOS_START], columns=ASSETS, dtype=float)
        for model in model_names
    }
    fit_log = []
    oos_dates = list(forecasts["OLS"].index)
    refit_dates = oos_dates[::REFIT_EVERY]

    for refit_idx, refit_date in enumerate(refit_dates):
        next_refit = refit_dates[refit_idx + 1] if refit_idx + 1 < len(refit_dates) else None
        if next_refit is None:
            block_dates = [d for d in oos_dates if d >= refit_date]
        else:
            block_dates = [d for d in oos_dates if refit_date <= d < next_refit]
        train_mask = x.index < refit_date
        if int(train_mask.sum()) < MIN_TRAIN:
            continue

        x_train = x.loc[train_mask].to_numpy()
        x_block = x.loc[block_dates].to_numpy()
        assert x.loc[train_mask].index.max() < refit_date, "Training window leaks into forecast date"
        fit_entry = {
            "refit_date": refit_date.strftime("%Y-%m-%d"),
            "train_end": x.loc[train_mask].index.max().strftime("%Y-%m-%d"),
            "train_n": int(train_mask.sum()),
            "block_n": int(len(block_dates)),
            "assets": {},
        }

        for asset in ASSETS:
            y_train = y.loc[train_mask, asset].to_numpy()
            fits = {
                "OLS": fit_ols(x_train, y_train),
                "ProjectedNonnegative": fit_projected_nonnegative(x_train, y_train),
                "AdmissibleNNLS": fit_admissible_nnls(x_train, y_train),
            }
            for model, fit in fits.items():
                forecasts[model].loc[block_dates, asset] = add_intercept(x_block) @ fit.beta
            fit_entry["assets"][asset] = {
                model: {
                    "lag_sum": fit.lag_sum,
                    "admissible_scaled": fit.admissible_scaled,
                    "status": fit.status,
                    "negative_coefficients_raw_ols": (
                        int(np.sum(fit.raw_ols_beta < 0)) if fit.raw_ols_beta is not None else None
                    ),
                }
                for model, fit in fits.items()
            }
        fit_log.append(fit_entry)
        print(f"refit {refit_idx + 1}/{len(refit_dates)} {refit_date.date()} train={int(train_mask.sum())}")

    actual = y.loc[oos_dates]
    ret_oos = returns_pct.loc[oos_dates]
    return {
        "forecasts": forecasts,
        "actual": actual,
        "returns_pct": ret_oos,
        "fit_log": fit_log,
    }


def evaluate(run: Dict) -> Dict:
    forecasts = run["forecasts"]
    actual = run["actual"]
    returns_pct = run["returns_pct"]
    models = list(forecasts.keys())
    per_asset = {}
    dm_tests = {}
    all_pvals = {}

    for asset in ASSETS:
        per_asset[asset] = {}
        a = actual[asset].to_numpy(dtype=float)
        for model in models:
            f_raw = forecasts[model][asset].to_numpy(dtype=float)
            valid = np.isfinite(a) & np.isfinite(f_raw)
            a_v = a[valid]
            f_v_raw = f_raw[valid]
            f_v = np.maximum(f_v_raw, FLOOR)
            losses = qlike_pointwise(a_v, f_v)
            abs_err = np.abs(a_v - f_v)
            rho, rho_p = spearman_corr(a_v, f_v)
            per_asset[asset][model] = {
                "n_oos": int(len(a_v)),
                "negative_forecast_count": int(np.sum(f_v_raw <= 0)),
                "negative_forecast_rate": float(np.mean(f_v_raw <= 0)),
                "QLIKE": float(qlike(a_v, f_v)),
                "MSE": float(np.mean((a_v - f_v) ** 2)),
                "Spearman_rho": float(rho),
                "Spearman_p": float(rho_p),
                "qlike_p95": float(np.nanquantile(losses, 0.95)),
                "qlike_p99": float(np.nanquantile(losses, 0.99)),
                "abs_error_p95": float(np.nanquantile(abs_err, 0.95)),
                "abs_error_p99": float(np.nanquantile(abs_err, 0.99)),
                "vol_target_overlay": volatility_overlay_metrics(f_v, returns_pct[asset].to_numpy(dtype=float)[valid]),
            }

        for model in ["ProjectedNonnegative", "AdmissibleNNLS"]:
            f_ols = np.maximum(forecasts["OLS"][asset].to_numpy(dtype=float), FLOOR)
            f_model = np.maximum(forecasts[model][asset].to_numpy(dtype=float), FLOOR)
            valid = np.isfinite(a) & np.isfinite(f_ols) & np.isfinite(f_model)
            loss_ols = qlike_pointwise(a[valid], f_ols[valid])
            loss_model = qlike_pointwise(a[valid], f_model[valid])
            t_stat, p_value = dm_test(loss_ols, loss_model, h=1)
            key = f"{asset}:{model}_vs_OLS"
            all_pvals[key] = float(p_value)
            dm_tests[key] = {
                "asset": asset,
                "model_a": "OLS",
                "model_b": model,
                "loss": "QLIKE",
                "dm_input": "loss_OLS - loss_constrained; positive t means constrained model lower loss",
                "DM_t": float(t_stat),
                "DM_p": float(p_value),
                "n": int(np.sum(valid)),
                "gate_abs_t_gt_3": bool(abs(t_stat) > 3.0),
            }

    adjusted = holm_adjust(all_pvals)
    for key, p_adj in adjusted.items():
        dm_tests[key]["holm_p"] = float(p_adj)
        dm_tests[key]["holm_pass_5pct"] = bool(p_adj < 0.05)

    aggregate = {}
    for model in models:
        qlikes = [per_asset[a][model]["QLIKE"] for a in ASSETS]
        neg_counts = [per_asset[a][model]["negative_forecast_count"] for a in ASSETS]
        aggregate[model] = {
            "mean_QLIKE": float(np.mean(qlikes)),
            "median_QLIKE": float(np.median(qlikes)),
            "total_negative_forecasts": int(np.sum(neg_counts)),
            "mean_negative_forecast_rate": float(np.mean([per_asset[a][model]["negative_forecast_rate"] for a in ASSETS])),
            "mean_overlay_turnover": float(np.mean([per_asset[a][model]["vol_target_overlay"]["mean_daily_turnover"] for a in ASSETS])),
            "mean_overlay_mdd": float(np.mean([per_asset[a][model]["vol_target_overlay"]["max_drawdown"] for a in ASSETS])),
        }

    model_wins = {}
    for model in ["ProjectedNonnegative", "AdmissibleNNLS"]:
        wins = []
        for asset in ASSETS:
            wins.append(per_asset[asset][model]["QLIKE"] < per_asset[asset]["OLS"]["QLIKE"])
        model_wins[model] = {
            "wins_vs_OLS": int(np.sum(wins)),
            "n_assets": len(wins),
            "sign_test_p": float(binomtest(int(np.sum(wins)), len(wins), p=0.5, alternative="greater").pvalue),
        }

    return {
        "per_asset": per_asset,
        "aggregate": aggregate,
        "dm_tests": dm_tests,
        "model_wins": model_wins,
    }


def make_chart(evaluation: Dict) -> None:
    models = ["OLS", "ProjectedNonnegative", "AdmissibleNNLS"]
    qlikes = [evaluation["aggregate"][m]["mean_QLIKE"] for m in models]
    negs = [evaluation["aggregate"][m]["total_negative_forecasts"] for m in models]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    colors = ["#6b7280", "#2563eb", "#059669"]
    axes[0].bar(models, qlikes, color=colors)
    axes[0].set_title("Mean OOS QLIKE across 6 ETFs")
    axes[0].set_ylabel("QLIKE (lower better)")
    axes[0].tick_params(axis="x", rotation=20)
    axes[1].bar(models, negs, color=colors)
    axes[1].set_title("Raw negative variance forecasts")
    axes[1].set_ylabel("Count")
    axes[1].tick_params(axis="x", rotation=20)
    fig.tight_layout()
    fig.savefig(CHART_PATH, dpi=160)
    plt.close(fig)


def main() -> None:
    np.random.seed(SEED)
    close = download_prices()
    x, y, returns_pct = build_panel(close)
    print(f"Panel rows after lag construction: {len(x)} ({x.index.min().date()}->{x.index.max().date()})")
    assert all(name.endswith("_lag1") for name in x.columns), "Feature names must show lagged construction"

    run = run_rolling(x, y, returns_pct)
    evaluation = evaluate(run)
    make_chart(evaluation)

    result = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Admissible constrained multivariate HAR / vMEM-lite guardrail",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": {
            "source": "yfinance adjusted daily close",
            "assets": ASSETS,
            "download_start": START,
            "download_end": END,
            "close_panel_start": close.index.min().strftime("%Y-%m-%d"),
            "close_panel_end": close.index.max().strftime("%Y-%m-%d"),
            "n_close_rows": int(len(close)),
            "feature_panel_start": x.index.min().strftime("%Y-%m-%d"),
            "feature_panel_end": x.index.max().strftime("%Y-%m-%d"),
            "n_feature_rows": int(len(x)),
        },
        "methodology": {
            "target": "next-day squared percent return r_t^2 for each ETF",
            "features": "All features are RV daily/weekly/monthly aggregates shifted by 1 trading day.",
            "lookahead_safety": [
                "Feature construction uses shift(1) for daily, weekly, and monthly RV features.",
                "At each refit, training rows satisfy train_date < forecast_date; assertion enforces this.",
                "Forecasts are produced for the refit block before observing target-day returns.",
            ],
            "models": {
                "OLS": "Unconstrained equation-by-equation OLS; raw predictions may be negative.",
                "ProjectedNonnegative": "OLS coefficients clipped to nonnegative values; simple positivity projection.",
                "AdmissibleNNLS": "NNLS coefficients with lag coefficients scaled so sum(beta_lags)<=0.995.",
            },
            "oos_start": OOS_START,
            "refit_every_trading_days": REFIT_EVERY,
            "min_train_rows": MIN_TRAIN,
            "qlike_floor_for_evaluation_only": FLOOR,
            "admissible_max_lag_sum": ADMISSIBLE_MAX_LAG_SUM,
            "references": [
                "Corsi (2009) JFEc HAR-RV heterogeneous autoregressive realized volatility",
                "Engle and Gallo (2006) Journal of Econometrics multiple-indicator MEM",
                "Cipollini, Engle, and Gallo (2013) vMEM representation and inference",
                "Karanasos et al. (2026) JFEc admissible parameter space for vMEMs",
            ],
        },
        "evaluation": evaluation,
        "fit_log_summary": {
            "n_refits": int(len(run["fit_log"])),
            "first_refit": run["fit_log"][0] if run["fit_log"] else None,
            "last_refit": run["fit_log"][-1] if run["fit_log"] else None,
        },
        "artifacts": {
            "chart": os.path.basename(CHART_PATH),
        },
    }

    ols_neg = result["evaluation"]["aggregate"]["OLS"]["total_negative_forecasts"]
    adm_neg = result["evaluation"]["aggregate"]["AdmissibleNNLS"]["total_negative_forecasts"]
    ols_q = result["evaluation"]["aggregate"]["OLS"]["mean_QLIKE"]
    adm_q = result["evaluation"]["aggregate"]["AdmissibleNNLS"]["mean_QLIKE"]
    result["headline"] = {
        "verdict": "MIXED_GUARDRAIL",
        "summary": (
            f"AdmissibleNNLS eliminates negative forecasts ({ols_neg}->{adm_neg}) "
            f"but mean QLIKE changes {ols_q:.4f}->{adm_q:.4f}; treat as an engineering "
            "guardrail, not a robust accuracy upgrade unless per-asset DM supports it."
        ),
    }

    with open(RESULTS_PATH, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Saved {RESULTS_PATH}")
    print(json.dumps(result["headline"], indent=2))


if __name__ == "__main__":
    main()
