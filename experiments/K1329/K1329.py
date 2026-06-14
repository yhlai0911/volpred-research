#!/usr/bin/env python3
"""K1329: Oil volatility spillover into U.S. equity and energy-stock volatility.

The experiment asks whether lagged oil volatility shocks, built from CL=F and
USO close-to-close returns, add predictive content for next-day volatility in
SPY and energy equities after a HAR-style own-volatility baseline and VIX.

Lookahead discipline:
  - Every forecast feature used at date t is explicitly shifted by one day.
  - Granger tests use lagged predictors through statsmodels, not same-day values.
  - CL=F returns around the 2020 negative oil-price print are dropped when either
    the current or previous close is non-positive.
"""

from __future__ import annotations

import json
import math
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from statsmodels.tsa.stattools import grangercausalitytests


EXPERIMENT_ID = "K1329"
HERE = Path(__file__).resolve().parent
SEED = 42
START_DATE = "2007-01-01"
END_DATE = "2026-06-15"
EPS = 1e-12

RAW_TICKERS = ["CL=F", "USO", "^OVX", "^VIX", "SPY", "XLE", "XOP", "OIH", "XOM", "CVX"]
LABELS = {
    "CL=F": "CL",
    "USO": "USO",
    "^OVX": "OVX",
    "^VIX": "VIX",
    "SPY": "SPY",
    "XLE": "XLE",
    "XOP": "XOP",
    "OIH": "OIH",
    "XOM": "XOM",
    "CVX": "CVX",
}
TARGETS = ["SPY", "XLE", "XOP", "OIH", "XOM", "CVX"]
GRANGER_PREDICTORS = ["CL_volshock", "USO_volshock", "CL_vov", "USO_vov", "OVX_level_z"]

BASELINE_FEATURES = ["own_d_lag", "own_w_lag", "own_m_lag", "vix_level_z_lag"]
OIL_FEATURES = BASELINE_FEATURES + [
    "cl_volshock_lag",
    "uso_volshock_lag",
    "cl_vov_lag",
    "uso_vov_lag",
]
OIL_OVX_FEATURES = OIL_FEATURES + ["ovx_level_z_lag", "ovx_chg_z_lag"]
MODEL_FEATURES = {
    "baseline_har_vix": BASELINE_FEATURES,
    "plus_oil_volshock": OIL_FEATURES,
    "plus_oil_ovx": OIL_OVX_FEATURES,
}


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any) -> float | None:
    try:
        value_f = float(value)
    except Exception:
        return None
    if not math.isfinite(value_f):
        return None
    return value_f


def _download_prices() -> pd.DataFrame:
    raw = yf.download(
        RAW_TICKERS,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned an empty panel")

    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" not in raw.columns.get_level_values(0):
            raise RuntimeError(f"downloaded panel has no Close field: {raw.columns}")
        close = raw["Close"].copy()
    else:
        close = raw.copy()

    close = close.rename(columns=LABELS)
    keep = [LABELS[t] for t in RAW_TICKERS if LABELS[t] in close.columns]
    close = close[keep].sort_index()
    close.index = pd.to_datetime(close.index).tz_localize(None)
    close = close.replace([np.inf, -np.inf], np.nan)
    close.to_csv(HERE / "K1329_close_prices.csv", index_label="date")
    return close


def _log_returns(close: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    ret = pd.DataFrame(index=close.index)
    diagnostics: dict[str, Any] = {}
    for col in close.columns:
        s = close[col].astype(float)
        s_valid = s.dropna()
        valid_pair = (s_valid > 0) & (s_valid.shift(1) > 0)
        ratio = pd.Series(np.nan, index=s.index, dtype=float)
        ratio_valid = pd.Series(np.nan, index=s_valid.index, dtype=float)
        ratio_valid.loc[valid_pair] = s_valid.loc[valid_pair] / s_valid.shift(1).loc[valid_pair]
        ratio.loc[ratio_valid.index] = ratio_valid
        r = np.log(ratio)
        ret[col] = r
        bad_dates = s.index[(s <= 0).fillna(False)].date.astype(str).tolist()
        diagnostics[col] = {
            "price_obs": int(s.notna().sum()),
            "return_obs": int(r.notna().sum()),
            "first_price_date": s.dropna().index.min().date().isoformat() if s.notna().any() else None,
            "last_price_date": s.dropna().index.max().date().isoformat() if s.notna().any() else None,
            "non_positive_price_dates": bad_dates,
            "non_positive_price_count": int(len(bad_dates)),
        }
    ret.to_csv(HERE / "K1329_log_returns.csv", index_label="date")
    return ret, diagnostics


def _rolling_z(series: pd.Series, window: int, min_periods: int | None = None) -> pd.Series:
    if min_periods is None:
        min_periods = max(10, window // 2)
    valid = series.dropna()
    mu = valid.rolling(window=window, min_periods=min_periods).mean()
    sd = valid.rolling(window=window, min_periods=min_periods).std(ddof=0)
    z = (valid - mu) / sd.replace(0, np.nan)
    return z.reindex(series.index)


def _build_raw_spillover_signals(close: pd.DataFrame, ret: pd.DataFrame) -> pd.DataFrame:
    signals = pd.DataFrame(index=close.index)
    for asset in ("CL", "USO"):
        valid_ret = ret[asset].dropna()
        rv5_valid = valid_ret.pow(2).rolling(5, min_periods=5).sum()
        log_rv5_valid = np.log(rv5_valid + EPS)
        log_rv5 = log_rv5_valid.reindex(close.index)
        signals[f"{asset}_volshock"] = _rolling_z(log_rv5, window=63, min_periods=42)
        vov20 = log_rv5_valid.dropna().rolling(20, min_periods=20).std(ddof=0).reindex(close.index)
        signals[f"{asset}_vov"] = _rolling_z(vov20, window=63, min_periods=42)

    if "OVX" in close.columns:
        signals["OVX_level_z"] = _rolling_z(np.log(close["OVX"]), window=252, min_periods=126)
        signals["OVX_chg_z"] = _rolling_z(close["OVX"].pct_change(), window=63, min_periods=42)
    else:
        signals["OVX_level_z"] = np.nan
        signals["OVX_chg_z"] = np.nan

    signals.to_csv(HERE / "K1329_raw_spillover_signals.csv", index_label="date")
    return signals


def _build_target_panel(
    target: str,
    close: pd.DataFrame,
    ret: pd.DataFrame,
    raw_signals: pd.DataFrame,
) -> pd.DataFrame:
    actual_var = ret[target].pow(2)
    log_actual_var = np.log(actual_var + EPS)

    valid_var = actual_var.dropna()
    own_d = np.log(valid_var + EPS).reindex(close.index)
    own_w = np.log(valid_var.rolling(5, min_periods=5).mean() + EPS).reindex(close.index)
    own_m = np.log(valid_var.rolling(22, min_periods=22).mean() + EPS).reindex(close.index)

    panel = pd.DataFrame(index=close.index)
    panel["actual_var"] = actual_var
    panel["log_actual_var"] = log_actual_var
    panel["own_d_lag"] = own_d.shift(1)
    panel["own_w_lag"] = own_w.shift(1)
    panel["own_m_lag"] = own_m.shift(1)
    panel["vix_level_z_lag"] = _rolling_z(np.log(close["VIX"]), window=252, min_periods=126).shift(1)

    # All oil features are signals from t-1 used to forecast target variance at t.
    panel["cl_volshock_lag"] = raw_signals["CL_volshock"].shift(1)
    panel["uso_volshock_lag"] = raw_signals["USO_volshock"].shift(1)
    panel["cl_vov_lag"] = raw_signals["CL_vov"].shift(1)
    panel["uso_vov_lag"] = raw_signals["USO_vov"].shift(1)
    panel["ovx_level_z_lag"] = raw_signals["OVX_level_z"].shift(1)
    panel["ovx_chg_z_lag"] = raw_signals["OVX_chg_z"].shift(1)
    return panel


def _fit_predict_log_variance(
    data: pd.DataFrame,
    features: list[str],
    split_idx: int,
) -> dict[str, Any]:
    train = data.iloc[:split_idx].copy()
    test = data.iloc[split_idx:].copy()

    x_train = train[features].astype(float)
    x_test = test[features].astype(float)
    mu = x_train.mean()
    sd = x_train.std(ddof=0).replace(0, 1.0)

    xtr = ((x_train - mu) / sd).to_numpy(dtype=float)
    xte = ((x_test - mu) / sd).to_numpy(dtype=float)
    ytr = train["log_actual_var"].to_numpy(dtype=float)

    xtr = np.column_stack([np.ones(len(xtr)), xtr])
    xte = np.column_stack([np.ones(len(xte)), xte])

    beta, *_ = np.linalg.lstsq(xtr, ytr, rcond=None)
    pred_log = xte @ beta
    pred_var = np.exp(np.clip(pred_log, np.log(EPS), np.log(0.25)))

    coefs = {"intercept": float(beta[0])}
    coefs.update({name: float(val) for name, val in zip(features, beta[1:], strict=True)})

    return {
        "index": test.index,
        "pred_var": pd.Series(pred_var, index=test.index),
        "pred_log_var": pd.Series(pred_log, index=test.index),
        "coefs_standardized": coefs,
    }


def _qlike(actual: pd.Series | np.ndarray, forecast: pd.Series | np.ndarray) -> np.ndarray:
    a = np.maximum(np.asarray(actual, dtype=float), EPS)
    f = np.maximum(np.asarray(forecast, dtype=float), EPS)
    ratio = a / f
    return ratio - np.log(ratio) - 1.0


def _dm_hln(loss_model: np.ndarray, loss_baseline: np.ndarray, horizon: int = 1) -> dict[str, float | int | None]:
    """Harvey-Leybourne-Newbold adjusted DM test with Newey-West variance."""
    d = np.asarray(loss_model, dtype=float) - np.asarray(loss_baseline, dtype=float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 30:
        return {"n": n, "mean_loss_diff": None, "t_stat": None, "p_value": None}

    d_mean = float(np.mean(d))
    centered = d - d_mean
    max_lag = max(horizon - 1, int(np.floor(n ** (1 / 3))))
    max_lag = min(max_lag, n // 4)
    gamma0 = float(np.mean(centered * centered))
    var_d = gamma0
    for lag in range(1, max_lag + 1):
        weight = 1.0 - lag / (max_lag + 1)
        cov = float(np.mean(centered[lag:] * centered[:-lag]))
        var_d += 2.0 * weight * cov
    if var_d <= 0:
        return {"n": n, "mean_loss_diff": d_mean, "t_stat": None, "p_value": None}

    se = math.sqrt(var_d / n)
    t_stat = d_mean / se
    hln = math.sqrt(max((n + 1 - 2 * horizon + horizon * (horizon - 1) / n) / n, EPS))
    t_hln = t_stat * hln
    p_value = 2.0 * (1.0 - stats.t.cdf(abs(t_hln), df=n - 1))
    return {
        "n": int(n),
        "mean_loss_diff": float(d_mean),
        "t_stat": float(t_hln),
        "p_value": float(p_value),
    }


def _run_oos_forecasts(
    target: str,
    close: pd.DataFrame,
    ret: pd.DataFrame,
    raw_signals: pd.DataFrame,
) -> dict[str, Any]:
    panel = _build_target_panel(target, close, ret, raw_signals)
    required = sorted(set(["actual_var", "log_actual_var", *OIL_OVX_FEATURES]))
    data = panel[required].replace([np.inf, -np.inf], np.nan).dropna()
    data = data[data["actual_var"] > 0].copy()
    if len(data) < 756:
        raise RuntimeError(f"{target}: insufficient forecast rows after feature construction: {len(data)}")

    split_idx = int(len(data) * 0.70)
    actual_oos = data["actual_var"].iloc[split_idx:]
    out: dict[str, Any] = {
        "target": target,
        "sample": {
            "n_total": int(len(data)),
            "n_train": int(split_idx),
            "n_oos": int(len(data) - split_idx),
            "first_date": data.index.min().date().isoformat(),
            "last_date": data.index.max().date().isoformat(),
            "oos_start": data.index[split_idx].date().isoformat(),
            "oos_end": data.index[-1].date().isoformat(),
        },
        "models": {},
        "comparisons_vs_baseline": {},
    }

    predictions: dict[str, pd.Series] = {}
    losses: dict[str, np.ndarray] = {}
    forecast_frame = pd.DataFrame(index=actual_oos.index)
    forecast_frame["actual_var"] = actual_oos

    for model_name, features in MODEL_FEATURES.items():
        fit = _fit_predict_log_variance(data, features, split_idx)
        pred = fit["pred_var"]
        predictions[model_name] = pred
        loss = _qlike(actual_oos.loc[pred.index], pred)
        losses[model_name] = loss
        forecast_frame[model_name] = pred
        out["models"][model_name] = {
            "features": features,
            "qlike_mean": float(np.mean(loss)),
            "qlike_median": float(np.median(loss)),
            "mae_variance": float(np.mean(np.abs(actual_oos.loc[pred.index] - pred))),
            "coefs_standardized": fit["coefs_standardized"],
        }

    baseline_loss = losses["baseline_har_vix"]
    baseline_qlike = out["models"]["baseline_har_vix"]["qlike_mean"]
    for model_name in ("plus_oil_volshock", "plus_oil_ovx"):
        model_qlike = out["models"][model_name]["qlike_mean"]
        dm = _dm_hln(losses[model_name], baseline_loss, horizon=1)
        out["comparisons_vs_baseline"][model_name] = {
            "qlike_improvement_pct": float((baseline_qlike - model_qlike) / baseline_qlike * 100.0),
            "dm_hln_model_minus_baseline": dm,
            "harvey_pass_abs_t_gt_3_and_improves": bool(
                dm["t_stat"] is not None
                and abs(float(dm["t_stat"])) > 3.0
                and model_qlike < baseline_qlike
            ),
        }

    forecast_frame.to_csv(HERE / f"K1329_{target}_oos_forecasts.csv", index_label="date")
    return out


def _granger_one_pair(
    target: str,
    predictor: str,
    target_log_var: pd.Series,
    predictor_signal: pd.Series,
    maxlag: int = 5,
) -> dict[str, Any]:
    df = pd.concat(
        [
            target_log_var.rename("target_log_var"),
            predictor_signal.rename("predictor"),
        ],
        axis=1,
    ).replace([np.inf, -np.inf], np.nan).dropna()
    std = df.std(ddof=0)
    if (
        len(df) < 252
        or df["target_log_var"].nunique() < 20
        or df["predictor"].nunique() < 20
        or std["target_log_var"] <= 0
        or std["predictor"] <= 0
    ):
        return {
            "target": target,
            "predictor": predictor,
            "n": int(len(df)),
            "status": "insufficient_variation",
            "best_lag": None,
            "best_raw_p": None,
            "lag_adjusted_p": None,
        }

    z = (df - df.mean()) / df.std(ddof=0).replace(0, np.nan)
    z = z.dropna()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tests = grangercausalitytests(z[["target_log_var", "predictor"]], maxlag=maxlag, verbose=False)
    except Exception as exc:
        return {
            "target": target,
            "predictor": predictor,
            "n": int(len(z)),
            "status": f"error: {type(exc).__name__}: {exc}",
            "best_lag": None,
            "best_raw_p": None,
            "lag_adjusted_p": None,
        }

    p_by_lag = {str(lag): float(tests[lag][0]["ssr_ftest"][1]) for lag in range(1, maxlag + 1)}
    best_lag_s, best_p = min(p_by_lag.items(), key=lambda kv: kv[1])
    lag_adjusted = min(float(best_p) * maxlag, 1.0)
    return {
        "target": target,
        "predictor": predictor,
        "n": int(len(z)),
        "status": "ok",
        "best_lag": int(best_lag_s),
        "p_by_lag": p_by_lag,
        "best_raw_p": float(best_p),
        "lag_adjusted_p": float(lag_adjusted),
    }


def _run_granger(close: pd.DataFrame, ret: pd.DataFrame, raw_signals: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for target in TARGETS:
        target_log_var = np.log(ret[target].pow(2) + EPS)
        for predictor in GRANGER_PREDICTORS:
            rows.append(_granger_one_pair(target, predictor, target_log_var, raw_signals[predictor]))

    family_n = sum(1 for r in rows if r.get("status") == "ok")
    for row in rows:
        lag_p = row.get("lag_adjusted_p")
        row["family_bonferroni_p"] = min(float(lag_p) * family_n, 1.0) if lag_p is not None else None
        row["family_pass_5pct"] = bool(row["family_bonferroni_p"] is not None and row["family_bonferroni_p"] < 0.05)

    pd.DataFrame(rows).to_csv(HERE / "K1329_granger_results.csv", index=False)
    return rows


def _same_next_day_correlations(ret: pd.DataFrame, raw_signals: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for target in TARGETS:
        target_log_var = np.log(ret[target].pow(2) + EPS)
        for predictor in GRANGER_PREDICTORS:
            x = raw_signals[predictor]
            rows.append(
                {
                    "target": target,
                    "predictor": predictor,
                    "same_day_corr": _safe_float(x.corr(target_log_var)),
                    "next_day_corr_predictor_t_to_target_t_plus_1": _safe_float(x.corr(target_log_var.shift(-1))),
                    "n_pair": int(pd.concat([x, target_log_var], axis=1).dropna().shape[0]),
                }
            )
    pd.DataFrame(rows).to_csv(HERE / "K1329_correlations.csv", index=False)
    return rows


def _plot_forecast_improvements(model_results: dict[str, Any]) -> None:
    rows = []
    for target, res in model_results.items():
        for model_name, cmp in res["comparisons_vs_baseline"].items():
            rows.append(
                {
                    "target": target,
                    "model": model_name,
                    "qlike_improvement_pct": cmp["qlike_improvement_pct"],
                }
            )
    df = pd.DataFrame(rows)
    pivot = df.pivot(index="target", columns="model", values="qlike_improvement_pct").loc[TARGETS]

    fig, ax = plt.subplots(figsize=(9.5, 5.2), dpi=160)
    pivot.plot(kind="bar", ax=ax, color=["#386641", "#bc6c25"])
    ax.axhline(0, color="#222222", linewidth=1)
    ax.axhline(1, color="#777777", linewidth=0.8, linestyle="--", alpha=0.7)
    ax.set_title("K1329 OOS QLIKE improvement vs HAR+VIX baseline")
    ax.set_ylabel("QLIKE improvement (%)")
    ax.set_xlabel("Target")
    ax.legend(frameon=True, title="")
    fig.tight_layout()
    fig.savefig(HERE / "K1329_oos_qlike_improvements.png", bbox_inches="tight")
    plt.close(fig)


def _plot_granger_heatmap(granger_rows: list[dict[str, Any]]) -> None:
    df = pd.DataFrame(granger_rows)
    ok = df[df["status"] == "ok"].copy()
    ok["score"] = -np.log10(ok["family_bonferroni_p"].astype(float).clip(lower=1e-16))
    pivot = ok.pivot(index="target", columns="predictor", values="score").reindex(index=TARGETS, columns=GRANGER_PREDICTORS)

    fig, ax = plt.subplots(figsize=(10.5, 5.4), dpi=160)
    im = ax.imshow(pivot.to_numpy(dtype=float), aspect="auto", cmap="YlGnBu", vmin=0, vmax=max(2.0, np.nanmax(pivot.to_numpy(dtype=float))))
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns, rotation=30, ha="right")
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    ax.set_title("K1329 Granger evidence: -log10(family Bonferroni p)")
    for i, target in enumerate(pivot.index):
        for j, predictor in enumerate(pivot.columns):
            value = pivot.loc[target, predictor]
            if pd.notna(value):
                ax.text(j, i, f"{value:.1f}", ha="center", va="center", fontsize=8, color="#111111")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(HERE / "K1329_granger_heatmap.png", bbox_inches="tight")
    plt.close(fig)


def _summarize(model_results: dict[str, Any], granger_rows: list[dict[str, Any]]) -> dict[str, Any]:
    forecast_passes = []
    for target, res in model_results.items():
        for model_name, cmp in res["comparisons_vs_baseline"].items():
            if cmp["harvey_pass_abs_t_gt_3_and_improves"]:
                forecast_passes.append(
                    {
                        "target": target,
                        "model": model_name,
                        "qlike_improvement_pct": cmp["qlike_improvement_pct"],
                        "dm_t": cmp["dm_hln_model_minus_baseline"]["t_stat"],
                        "dm_p": cmp["dm_hln_model_minus_baseline"]["p_value"],
                    }
                )

    granger_passes = [
        {
            "target": r["target"],
            "predictor": r["predictor"],
            "best_lag": r["best_lag"],
            "family_bonferroni_p": r["family_bonferroni_p"],
        }
        for r in granger_rows
        if r.get("family_pass_5pct")
    ]

    best_oos_by_target = {}
    for target, res in model_results.items():
        comps = res["comparisons_vs_baseline"]
        best = max(comps.items(), key=lambda kv: kv[1]["qlike_improvement_pct"])
        best_oos_by_target[target] = {
            "model": best[0],
            "qlike_improvement_pct": best[1]["qlike_improvement_pct"],
            "dm_t": best[1]["dm_hln_model_minus_baseline"]["t_stat"],
            "dm_p": best[1]["dm_hln_model_minus_baseline"]["p_value"],
            "harvey_pass": best[1]["harvey_pass_abs_t_gt_3_and_improves"],
        }

    if forecast_passes:
        verdict = "forecast_edge_pass"
    elif granger_passes:
        verdict = "statistical_spillover_without_oos_forecast_edge"
    else:
        verdict = "null_no_family_adjusted_spillover"

    return {
        "verdict": verdict,
        "forecast_passes_harvey_abs_t_gt_3": forecast_passes,
        "granger_family_passes_5pct": granger_passes,
        "best_oos_by_target": best_oos_by_target,
        "interpretation_guardrail": (
            "Forecast evidence uses daily close-to-close squared-return proxies, not intraday realized volatility. "
            "Granger/QLIKE results are predictive diagnostics, not structural causality."
        ),
    }


def main() -> None:
    np.random.seed(SEED)
    close = _download_prices()
    ret, price_diagnostics = _log_returns(close)
    raw_signals = _build_raw_spillover_signals(close, ret)

    model_results: dict[str, Any] = {}
    for target in TARGETS:
        model_results[target] = _run_oos_forecasts(target, close, ret, raw_signals)

    granger_rows = _run_granger(close, ret, raw_signals)
    correlations = _same_next_day_correlations(ret, raw_signals)

    _plot_forecast_improvements(model_results)
    _plot_granger_heatmap(granger_rows)

    summary = _summarize(model_results, granger_rows)
    result = {
        "experiment_id": EXPERIMENT_ID,
        "generated_at": _now_utc(),
        "seed": SEED,
        "data_source": {
            "source": "Yahoo Finance via yfinance",
            "requested_start": START_DATE,
            "requested_end_exclusive": END_DATE,
            "tickers": RAW_TICKERS,
            "latest_price_date": close.dropna(how="all").index.max().date().isoformat(),
            "notes": [
                "auto_adjust=True close prices",
                "CL=F log returns dropped when current or previous close is non-positive",
                "daily squared close-to-close returns are low-frequency volatility proxies",
            ],
        },
        "price_diagnostics": price_diagnostics,
        "method": {
            "target": "next-day close-to-close squared return variance proxy",
            "baseline": "HAR-style own daily/weekly/monthly log variance lags plus lagged VIX level z-score",
            "oil_extension": "lagged CL and USO 5-day log-RV shock z-scores plus lagged vol-of-vol z-scores",
            "ovx_robustness": "adds lagged OVX level and change z-scores",
            "lookahead_policy": "All forecast features use explicit .shift(1); Granger tests use lagged predictors only.",
            "formal_threshold": "Harvey-style DM gate requires |t| > 3 and lower OOS QLIKE than baseline.",
        },
        "literature_refs": [
            {
                "label": "Diebold and Yilmaz (2009), Measuring Financial Asset Return and Volatility Spillovers",
                "url": "https://www.nber.org/system/files/working_papers/w13811/w13811.pdf",
            },
            {
                "label": "Yu (2025), Industry Index Volatility Spillovers and Forecasting from Crude Oil Prices Based on the MS-HAR-TVP Model",
                "url": "https://www.mdpi.com/2227-7390/13/22/3723",
            },
            {
                "label": "Volatility spillovers between oil and financial markets during economic and financial crises",
                "url": "https://link.springer.com/article/10.1007/s12197-023-09634-x",
            },
        ],
        "model_results": model_results,
        "granger_results": granger_rows,
        "correlations": correlations,
        "summary": summary,
        "charts": [
            "K1329_oos_qlike_improvements.png",
            "K1329_granger_heatmap.png",
        ],
        "csv_outputs": [
            "K1329_close_prices.csv",
            "K1329_log_returns.csv",
            "K1329_raw_spillover_signals.csv",
            "K1329_granger_results.csv",
            "K1329_correlations.csv",
            *[f"K1329_{target}_oos_forecasts.csv" for target in TARGETS],
        ],
    }

    out_path = HERE / "K1329_results.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
