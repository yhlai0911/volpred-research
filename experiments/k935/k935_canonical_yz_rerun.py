"""K935 follow-up: canonical rolling Yang-Zhang rerun.

This script does not overwrite the original K935 result. It addresses the
2026-06-23 24h-rule review caveat: the original K935 "YZ" target was a
single-day overnight-adjusted proxy, not the canonical multi-period
Yang-Zhang estimator.

Canonical rolling YZ variance over n days:
    sigma_yz^2 = sigma_o^2 + k * sigma_c^2 + (1-k) * sigma_rs^2

where sigma_o^2 is the rolling sample variance of overnight returns
log(Open_t / Close_{t-1}), sigma_c^2 is the rolling sample variance of
open-to-close returns, and sigma_rs^2 is the rolling mean Rogers-Satchell
variance. The task brief requests the 1/n variance convention over the
same 2000-day window used by K935.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy import stats
import yfinance as yf


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


SEED = 42
np.random.seed(SEED)

OUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUT_DIR / "k935_canonical_yz_rerun_results.json"

START = "2004-01-01"
END = "2026-01-01"
OOS_START = "2016-01-01"
WINDOW = 2000
REFIT = 21
FLOOR = 1e-10


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


def load_spy() -> pd.DataFrame:
    spy = yf.download(
        "SPY",
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    spy = _flatten_columns(spy)
    if spy.empty:
        raise RuntimeError("SPY download returned no rows")

    for col in ["High", "Low", "Open", "Close"]:
        if col not in spy.columns:
            raise RuntimeError(f"SPY data missing column: {col}")

    spy["log_H"] = np.log(spy["High"])
    spy["log_L"] = np.log(spy["Low"])
    spy["log_O"] = np.log(spy["Open"])
    spy["log_C"] = np.log(spy["Close"])
    spy["log_return"] = spy["log_C"] - spy["log_C"].shift(1)
    spy["r2"] = spy["log_return"] ** 2
    spy["overnight_return"] = spy["log_O"] - spy["log_C"].shift(1)
    spy["open_close_return"] = spy["log_C"] - spy["log_O"]

    spy["range_parkinson"] = (spy["log_H"] - spy["log_L"]) ** 2 / (4 * np.log(2))
    spy["range_rs"] = (
        (spy["log_H"] - spy["log_C"]) * (spy["log_H"] - spy["log_O"])
        + (spy["log_L"] - spy["log_C"]) * (spy["log_L"] - spy["log_O"])
    )

    # Original K935 YZ-style proxy, retained for sanity comparison.
    k_asymptotic = 0.34 / (1.34 + 2.0)
    spy["range_yz_style"] = (
        spy["overnight_return"] ** 2
        + k_asymptotic
        * ((spy["log_H"] - spy["log_O"]) ** 2 + (spy["log_L"] - spy["log_O"]) ** 2)
        + (1 - k_asymptotic) * spy["range_rs"]
    )

    # Canonical rolling Yang-Zhang over the same 2000-day memory used by K935.
    # The task brief specifies 1/n variance, hence ddof=0.
    k_yz = 0.34 / (1.34 + (WINDOW + 1) / (WINDOW - 1))
    sigma_o2 = spy["overnight_return"].rolling(WINDOW, min_periods=WINDOW).var(ddof=0)
    sigma_c2 = spy["open_close_return"].rolling(WINDOW, min_periods=WINDOW).var(ddof=0)
    sigma_rs2 = spy["range_rs"].rolling(WINDOW, min_periods=WINDOW).mean()
    spy["range_yz_canonical_2000"] = sigma_o2 + k_yz * sigma_c2 + (1 - k_yz) * sigma_rs2

    for col in ["range_parkinson", "range_rs", "range_yz_style", "range_yz_canonical_2000"]:
        spy[col] = np.maximum(spy[col], FLOOR)

    return spy.dropna(subset=["log_return", "r2", "range_parkinson", "range_yz_style"])


def _clean_positive(x: np.ndarray) -> np.ndarray:
    arr = np.asarray(x, dtype=np.float64)
    arr = arr[np.isfinite(arr) & (arr > 0)]
    return arr


def carr_fit(ranges: np.ndarray, max_iter: int = 500) -> dict:
    ranges = _clean_positive(ranges)
    if len(ranges) < 50:
        raise RuntimeError(f"Too few positive CARR observations: {len(ranges)}")

    t_obs = len(ranges)
    mean_r = float(np.mean(ranges))

    def neg_loglik(params: np.ndarray) -> float:
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0 or (alpha + beta) >= 0.9999:
            return 1e10
        lam = np.zeros(t_obs)
        lam[0] = omega / (1 - alpha - beta) if (alpha + beta) < 1 else mean_r
        for i in range(1, t_obs):
            lam[i] = omega + alpha * ranges[i - 1] + beta * lam[i - 1]
            if lam[i] <= FLOOR:
                lam[i] = FLOOR
        ll = -np.log(lam) - ranges / lam
        return -float(np.sum(ll[10:]))

    x0 = [mean_r * 0.05, 0.10, 0.85]
    bounds = [(1e-10, None), (1e-8, 0.5), (0.3, 0.9999)]
    result = minimize(
        neg_loglik,
        x0,
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": max_iter, "ftol": 1e-12},
    )

    if not result.success:
        for alpha0, beta0 in [(0.05, 0.90), (0.15, 0.80), (0.08, 0.88)]:
            alt = minimize(
                neg_loglik,
                [mean_r * 0.05, alpha0, beta0],
                method="L-BFGS-B",
                bounds=bounds,
                options={"maxiter": max_iter, "ftol": 1e-12},
            )
            if alt.success and alt.fun < result.fun:
                result = alt

    omega, alpha, beta = result.x
    return {
        "omega": float(omega),
        "alpha": float(alpha),
        "beta": float(beta),
        "persistence": float(alpha + beta),
        "converged": bool(result.success),
        "loglik": float(-result.fun),
        "n_fit": int(t_obs),
    }


def carr_forecast_one(params: dict, ranges_history: np.ndarray) -> float:
    ranges = _clean_positive(ranges_history)
    if len(ranges) < 10:
        return float("nan")

    omega, alpha, beta = params["omega"], params["alpha"], params["beta"]
    lam = omega / max(1 - alpha - beta, 0.01)
    for val in ranges:
        lam = omega + alpha * val + beta * lam
        if lam <= FLOOR:
            lam = FLOOR
    return float(lam)


def run_oos(spy: pd.DataFrame) -> dict:
    oos_idx = spy.index[spy.index >= pd.Timestamp(OOS_START)]
    first_oos_pos = int(np.searchsorted(spy.index, pd.Timestamp(OOS_START)))
    n_oos = len(oos_idx)

    models = {
        "CARR_Parkinson": "range_parkinson",
        "CARR_YZ_Style": "range_yz_style",
        "CARR_YZ_Canonical_2000": "range_yz_canonical_2000",
    }
    arrays = {name: spy[col].to_numpy(dtype=np.float64) for name, col in models.items()}
    forecasts = {name: np.full(n_oos, np.nan) for name in models}
    params_last = {}
    n_refits = 0

    for i in range(n_oos):
        t = first_oos_pos + i
        if i % REFIT == 0:
            train_start = max(0, t - WINDOW)
            train_end = t
            for name in models:
                params_last[name] = carr_fit(arrays[name][train_start:train_end])
            n_refits += 1

        for name in models:
            forecasts[name][i] = carr_forecast_one(params_last[name], arrays[name][train_start:t])

    actual_r2 = spy["r2"].to_numpy(dtype=np.float64)[first_oos_pos : first_oos_pos + n_oos]
    metrics = {}
    losses = {}
    for name, fcast in forecasts.items():
        valid = np.isfinite(fcast) & np.isfinite(actual_r2) & (fcast > 0) & (actual_r2 > 0)
        metrics[name] = {
            "qlike_r2": float(qlike(actual_r2[valid], fcast[valid])),
            "n_valid": int(valid.sum()),
        }
        rho, pval = stats.spearmanr(fcast[valid], actual_r2[valid])
        metrics[name]["spearman_rho"] = float(rho)
        metrics[name]["spearman_p"] = float(pval)
        losses[name] = qlike_pointwise(actual_r2[valid], fcast[valid])

    dm_vs_parkinson = {}
    for name in ["CARR_YZ_Style", "CARR_YZ_Canonical_2000"]:
        f1 = forecasts[name]
        f2 = forecasts["CARR_Parkinson"]
        valid = np.isfinite(f1) & np.isfinite(f2) & np.isfinite(actual_r2) & (f1 > 0) & (f2 > 0) & (actual_r2 > 0)
        loss1 = qlike_pointwise(actual_r2[valid], f1[valid])
        loss2 = qlike_pointwise(actual_r2[valid], f2[valid])
        t_stat, p_val = dm_test(loss1, loss2, h=1)
        pk_q = metrics["CARR_Parkinson"]["qlike_r2"]
        q = metrics[name]["qlike_r2"]
        dm_vs_parkinson[name] = {
            "t_stat": float(t_stat),
            "p_value": float(p_val),
            "harvey_threshold_abs_t_gt_3": bool(abs(t_stat) > 3.0),
            "winner": name if t_stat < -3.0 else ("CARR_Parkinson" if t_stat > 3.0 else "n.s."),
            "improvement_pct_vs_parkinson": float((pk_q - q) / pk_q * 100),
            "n_valid": int(valid.sum()),
        }

    # Directly test whether the canonical target materially changes the YZ-style result.
    f_can = forecasts["CARR_YZ_Canonical_2000"]
    f_style = forecasts["CARR_YZ_Style"]
    valid = np.isfinite(f_can) & np.isfinite(f_style) & np.isfinite(actual_r2) & (f_can > 0) & (f_style > 0) & (actual_r2 > 0)
    loss_can = qlike_pointwise(actual_r2[valid], f_can[valid])
    loss_style = qlike_pointwise(actual_r2[valid], f_style[valid])
    t_can_vs_style, p_can_vs_style = dm_test(loss_can, loss_style, h=1)

    ranking = sorted(
        ((name, vals["qlike_r2"]) for name, vals in metrics.items()),
        key=lambda item: item[1],
    )

    return {
        "oos_period": {
            "start": str(oos_idx[0].date()),
            "end": str(oos_idx[-1].date()),
            "n_oos": int(n_oos),
        },
        "window": WINDOW,
        "refit_every": REFIT,
        "n_refits": int(n_refits),
        "metrics": metrics,
        "ranking": [{"rank": i + 1, "model": name, "qlike_r2": q} for i, (name, q) in enumerate(ranking)],
        "dm_vs_parkinson": dm_vs_parkinson,
        "dm_canonical_vs_yz_style": {
            "t_stat": float(t_can_vs_style),
            "p_value": float(p_can_vs_style),
            "negative_t_means_canonical_better": True,
            "n_valid": int(valid.sum()),
        },
        "model_params_last_refit": {
            name: {k: (round(v, 10) if isinstance(v, float) else v) for k, v in params.items()}
            for name, params in params_last.items()
        },
    }


def main() -> dict:
    spy = load_spy()
    result = run_oos(spy)

    original_results_path = OUT_DIR / "k935_results.json"
    original_results = json.loads(original_results_path.read_text(encoding="utf-8"))
    original_key = original_results["layer4_dm_tests"].get("CARR_YZ vs CARR_Parkinson", {})

    result.update(
        {
            "experiment_id": "K935_canonical_yz_rerun",
            "parent_experiment": "K935",
            "parent_article_id": "mile_1bff1fe5",
            "generated_at": datetime.now(UTC).isoformat(),
            "seed": SEED,
            "data_source": "yfinance SPY OHLC, auto_adjust=True",
            "period": {"start": START, "end_exclusive": END, "n_obs_after_dropna": int(len(spy))},
            "formula": {
                "canonical_yz_2000": "sigma_o2 + k*sigma_c2 + (1-k)*sigma_rs2",
                "sigma_o2": "rolling 2000-day mean((log(Open_t/Close_{t-1}) - rolling_mean)^2), ddof=0 per task brief",
                "sigma_c2": "rolling 2000-day mean((log(Close_t/Open_t) - rolling_mean)^2), ddof=0",
                "sigma_rs2": "rolling 2000-day mean of Rogers-Satchell daily variance",
                "k": 0.34 / (1.34 + (WINDOW + 1) / (WINDOW - 1)),
            },
            "lookahead_policy": "Rolling YZ at day s uses OHLC through s; OOS forecast for day t uses target history only through t-1.",
            "original_k935_reference": {
                "qlike_r2_CARR_YZ": original_results["layer2_qlike_on_r2_patton"]["CARR_YZ"],
                "qlike_r2_CARR_Parkinson": original_results["layer2_qlike_on_r2_patton"]["CARR_Parkinson"],
                "dm_CARR_YZ_vs_CARR_Parkinson": original_key,
            },
        }
    )

    can = result["dm_vs_parkinson"]["CARR_YZ_Canonical_2000"]
    result["verdict"] = (
        "CANONICAL_YZ_CONFIRMS_HEADLINE"
        if can["t_stat"] < -3.0
        else "CANONICAL_YZ_DOES_NOT_CONFIRM_HEADLINE"
    )
    result["article_update_required"] = bool(result["verdict"] != "CANONICAL_YZ_CONFIRMS_HEADLINE")

    RESULTS_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[done] wrote {RESULTS_PATH}")
    print(
        "[summary]",
        result["verdict"],
        "canonical_vs_parkinson_t=" + f"{can['t_stat']:.4f}",
        "improvement_pct=" + f"{can['improvement_pct_vs_parkinson']:.2f}",
    )
    return result


if __name__ == "__main__":
    main()
