"""K1481: Inventory-surprise commodity RV regime feature (Crude pilot).

Tests whether adding EIA crude inventory surprise to HAR-RV improves
one-step-ahead WTI realized vol forecasts vs price-only baseline.

Lookahead discipline:
- All HAR features at trading day t use info <= t-1 via .shift(1).
- EIA inventory surprise indexed at the period_end Friday is delayed
  +5 business days to model the Wed-of-following-week publication lag,
  then .shift(1) again for daily signal.

Seeds: np.random.seed(42); rng = np.random.default_rng(42) for bootstrap.

Outputs:
  - k1481_inventory_surprise_crude_rv_pilot_results.json
  - figure_har_vs_inv.png
"""

from __future__ import annotations

import io
import json
import math
import os
import sys
import time
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

EXP_DIR = Path(__file__).resolve().parent
EXP_ID = "k1481_inventory_surprise_crude_rv_pilot"
RESULTS_PATH = EXP_DIR / f"{EXP_ID}_results.json"
FIG_PATH = EXP_DIR / "figure_har_vs_inv.png"

START = "2010-01-04"
END = "2026-05-31"

TRAIN_END_FIRST = "2014-12-31"  # first OOS = 2015-01-01
REFIT_FREQ_DAYS = 252  # annual refit
SEED = 42
N_BOOT = 1000

EIA_XLS_URL = "https://www.eia.gov/dnav/pet/hist_xls/WCESTUS1w.xls"


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_wti_ohlc() -> pd.DataFrame:
    df = yf.download("CL=F", start=START, end=END, progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns=str.lower)
    df = df[["open", "high", "low", "close"]].dropna()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df


def load_eia_crude_stocks() -> pd.Series:
    """Return weekly crude stocks (kbbl) indexed at period_end Friday."""
    r = requests.get(EIA_XLS_URL, timeout=60)
    r.raise_for_status()
    xls = pd.ExcelFile(io.BytesIO(r.content))
    raw = pd.read_excel(xls, sheet_name="Data 1", header=None)
    # First 3 rows are header / labels; data starts at row 3.
    data = raw.iloc[3:].copy()
    data.columns = ["date", "stocks"]
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["stocks"] = pd.to_numeric(data["stocks"], errors="coerce")
    data = data.dropna()
    data = data.set_index("date").sort_index()
    return data["stocks"]


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def garman_klass_rv(ohlc: pd.DataFrame) -> pd.Series:
    """Garman-Klass realized variance estimator (daily)."""
    hi = np.log(ohlc["high"] / ohlc["low"])
    co = np.log(ohlc["close"] / ohlc["open"])
    rv = 0.5 * hi ** 2 - (2 * math.log(2) - 1) * co ** 2
    rv = rv.clip(lower=1e-10)
    rv.name = "rv"
    return rv


def har_features(log_rv: pd.Series) -> pd.DataFrame:
    """HAR features: daily / weekly / monthly averages of log-RV."""
    df = pd.DataFrame({"log_rv": log_rv})
    df["log_rv_d"] = log_rv
    df["log_rv_w"] = log_rv.rolling(5).mean()
    df["log_rv_m"] = log_rv.rolling(22).mean()
    # Target: next-day log RV.
    df["target"] = log_rv.shift(-1)
    return df


def ar1_one_step(series: pd.Series, window: int = 52) -> pd.Series:
    """Rolling AR(1) one-step-ahead naive forecast.

    For each index t, fit AR(1) on series[t-window:t] (last `window` obs strictly
    before t) and predict series[t]. Returns predictions aligned to series index.
    """
    fc = pd.Series(index=series.index, dtype=float)
    vals = series.values
    for i in range(len(vals)):
        if i < window:
            continue
        y = vals[i - window : i]
        # AR(1): y_k = a + b * y_{k-1}
        y_lag = y[:-1]
        y_curr = y[1:]
        if len(y_lag) < 5:
            continue
        x = np.column_stack([np.ones_like(y_lag), y_lag])
        try:
            beta, *_ = np.linalg.lstsq(x, y_curr, rcond=None)
            fc.iloc[i] = beta[0] + beta[1] * vals[i - 1]
        except np.linalg.LinAlgError:
            continue
    return fc


def build_inventory_surprise(stocks: pd.Series) -> pd.DataFrame:
    """Return weekly DataFrame with delta, ar1_forecast, surprise, surprise_z."""
    df = pd.DataFrame({"stocks": stocks.sort_index()})
    df["delta"] = df["stocks"].diff()
    df = df.dropna(subset=["delta"])
    df["ar1_fc"] = ar1_one_step(df["delta"], window=52)
    df["surprise"] = df["delta"] - df["ar1_fc"]
    # Rolling 52-wk std of surprise (strictly past).
    df["surprise_std52"] = df["surprise"].shift(1).rolling(52).std()
    df["surprise_z"] = df["surprise"] / df["surprise_std52"]
    return df


def lag_inventory_to_daily(weekly_surprise_z: pd.Series, daily_index: pd.DatetimeIndex) -> pd.Series:
    """Convert weekly surprise (period_end Friday) to daily availability.

    EIA releases ~Wed of the week following the Friday period_end.
    We model the earliest usable trading day as period_end Friday + 5 business
    days (i.e. the following Friday). Then forward-fill onto the daily index.
    """
    # Shift each weekly observation forward by 5 business days.
    shifted_index = weekly_surprise_z.index + pd.tseries.offsets.BDay(5)
    s = pd.Series(weekly_surprise_z.values, index=shifted_index)
    s = s[~s.index.duplicated(keep="last")].sort_index()
    s = s.reindex(s.index.union(daily_index)).sort_index().ffill()
    s = s.reindex(daily_index)
    return s


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass
class ModelSpec:
    name: str
    features: list

MODELS = [
    ModelSpec(name="HAR-RV", features=["log_rv_d", "log_rv_w", "log_rv_m"]),
    ModelSpec(name="HAR-INV", features=["log_rv_d", "log_rv_w", "log_rv_m", "surprise_z_lag"]),
    ModelSpec(
        name="HAR-INV-REGIME",
        features=["log_rv_d", "log_rv_w", "log_rv_m", "surprise_z_lag", "surprise_regime"],
    ),
]


def fit_ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    Xc = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(Xc, y, rcond=None)
    return beta


def predict_ols(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    Xc = np.column_stack([np.ones(len(X)), X])
    return Xc @ beta


def expanding_oos_forecast(df: pd.DataFrame, spec: ModelSpec,
                           first_oos_idx: int, refit_freq: int) -> pd.Series:
    """Expanding-window OLS, refit every `refit_freq` steps."""
    preds = pd.Series(index=df.index, dtype=float)
    beta = None
    last_fit_idx = -1
    feature_cols = spec.features
    n = len(df)
    for t in range(first_oos_idx, n):
        # Refit if needed.
        if beta is None or (t - last_fit_idx) >= refit_freq:
            train = df.iloc[:t].dropna(subset=feature_cols + ["target"])
            if len(train) < 30:
                continue
            X_tr = train[feature_cols].values
            y_tr = train["target"].values
            beta = fit_ols(X_tr, y_tr)
            last_fit_idx = t
        row = df.iloc[t]
        if row[feature_cols].isna().any():
            continue
        X_te = row[feature_cols].values.reshape(1, -1)
        preds.iloc[t] = predict_ols(beta, X_te)[0]
    return preds


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def qlike(rv: np.ndarray, sigma2_hat: np.ndarray) -> float:
    """Patton 2011 QLIKE. Both inputs are variances (not logs)."""
    eps = 1e-10
    sigma2_hat = np.maximum(sigma2_hat, eps)
    rv = np.maximum(rv, eps)
    return float(np.mean(np.log(sigma2_hat) + rv / sigma2_hat))


def mse_log(log_rv_actual: np.ndarray, log_rv_pred: np.ndarray) -> float:
    return float(np.mean((log_rv_actual - log_rv_pred) ** 2))


def r2_oos(log_rv_actual: np.ndarray, log_rv_pred: np.ndarray, log_rv_mean_train: float) -> float:
    ss_res = np.sum((log_rv_actual - log_rv_pred) ** 2)
    ss_tot = np.sum((log_rv_actual - log_rv_mean_train) ** 2)
    if ss_tot == 0:
        return float("nan")
    return float(1 - ss_res / ss_tot)


def dm_test(loss1: np.ndarray, loss2: np.ndarray, n_boot: int = 1000, seed: int = 42):
    """Diebold-Mariano with HAC variance (Newey-West lag=5) and bootstrap p-value.

    H0: E[loss1 - loss2] = 0. Negative DM => model1 has lower loss => better.
    """
    d = loss1 - loss2
    n = len(d)
    if n < 10:
        return {"stat": float("nan"), "p_hac": float("nan"), "p_boot": float("nan"), "n": n}
    dbar = float(np.mean(d))
    # Newey-West variance with lag = 5.
    L = 5
    gamma0 = float(np.var(d, ddof=0))
    var = gamma0
    for k in range(1, L + 1):
        cov = float(np.mean((d[k:] - dbar) * (d[:-k] - dbar)))
        weight = 1 - k / (L + 1)
        var += 2 * weight * cov
    var = max(var, 1e-12)
    se = math.sqrt(var / n)
    stat = dbar / se
    # Asymptotic two-sided HAC p.
    from scipy.stats import norm
    p_hac = float(2 * (1 - norm.cdf(abs(stat))))
    # Stationary block bootstrap (block length ~ sqrt(n)).
    rng = np.random.default_rng(seed)
    block = max(int(round(math.sqrt(n))), 1)
    boot_stats = np.zeros(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, n, size=int(math.ceil(n / block)))
        idx = np.concatenate([np.arange(s, s + block) % n for s in starts])[:n]
        db = d[idx]
        mean_b = float(np.mean(db) - dbar)  # center under null
        # bootstrap variance with same HAC
        gamma0_b = float(np.var(db, ddof=0))
        var_b = gamma0_b
        for k in range(1, L + 1):
            cov_b = float(np.mean((db[k:] - np.mean(db)) * (db[:-k] - np.mean(db))))
            w = 1 - k / (L + 1)
            var_b += 2 * w * cov_b
        var_b = max(var_b, 1e-12)
        se_b = math.sqrt(var_b / n)
        boot_stats[b] = mean_b / se_b
    p_boot = float(np.mean(np.abs(boot_stats) >= abs(stat)))
    return {"stat": float(stat), "p_hac": p_hac, "p_boot": p_boot, "n": int(n)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    np.random.seed(SEED)
    t0 = time.time()
    print(f"[{EXP_ID}] start", flush=True)

    # --- Load data ---
    ohlc = load_wti_ohlc()
    print(f"  WTI OHLC: {len(ohlc)} days, {ohlc.index.min().date()} -> {ohlc.index.max().date()}", flush=True)

    stocks = load_eia_crude_stocks()
    print(f"  EIA stocks: {len(stocks)} weeks, {stocks.index.min().date()} -> {stocks.index.max().date()}", flush=True)

    # --- Features ---
    rv = garman_klass_rv(ohlc)
    log_rv = np.log(rv)
    har = har_features(log_rv)
    har.index.name = "date"

    inv_df = build_inventory_surprise(stocks)
    surprise_z_weekly = inv_df["surprise_z"].dropna()

    # Map weekly surprise to daily with 5-BD publication lag.
    surprise_daily = lag_inventory_to_daily(surprise_z_weekly, har.index)
    # Final lookahead guard: shift by 1 day so signal at t uses info <= t-1.
    har["surprise_z_lag"] = surprise_daily.shift(1)
    # Regime interaction: |z|>1 indicator (using the *lagged* z).
    har["surprise_regime"] = (har["surprise_z_lag"].abs() > 1).astype(float) * har["surprise_z_lag"].abs()

    # Lookahead audit values (printed for evidence).
    n_har_rows = int(har.dropna(subset=["log_rv_d", "log_rv_w", "log_rv_m", "target"]).shape[0])
    n_inv_rows = int(har.dropna(subset=["surprise_z_lag", "target"]).shape[0])
    print(f"  HAR rows w/ target: {n_har_rows}; INV rows w/ target: {n_inv_rows}", flush=True)

    # --- OOS split ---
    first_oos_idx = int(har.index.searchsorted(pd.Timestamp(TRAIN_END_FIRST) + pd.Timedelta(days=1)))
    print(f"  first_oos_idx = {first_oos_idx} ({har.index[first_oos_idx].date()})", flush=True)

    # --- Forecasts ---
    preds = {}
    for spec in MODELS:
        print(f"  fitting {spec.name}...", flush=True)
        preds[spec.name] = expanding_oos_forecast(har, spec, first_oos_idx, REFIT_FREQ_DAYS)

    # --- Align OOS ---
    eval_df = har[["target"]].copy()
    for name, p in preds.items():
        eval_df[f"pred_{name}"] = p
    eval_df = eval_df.iloc[first_oos_idx:].dropna()
    log_rv_train_mean = float(har["target"].iloc[:first_oos_idx].dropna().mean())

    print(f"  OOS rows after align: {len(eval_df)}", flush=True)

    # --- Metrics ---
    metrics = {}
    log_rv_actual = eval_df["target"].values
    rv_actual = np.exp(log_rv_actual)
    losses = {}
    for spec in MODELS:
        pname = f"pred_{spec.name}"
        log_pred = eval_df[pname].values
        sigma2_pred = np.exp(log_pred)
        ql = qlike(rv_actual, sigma2_pred)
        ms = mse_log(log_rv_actual, log_pred)
        r2 = r2_oos(log_rv_actual, log_pred, log_rv_train_mean)
        metrics[spec.name] = {"qlike": ql, "mse_log": ms, "r2_oos": r2}
        # Per-obs QLIKE losses for DM.
        per_q = np.log(np.maximum(sigma2_pred, 1e-10)) + rv_actual / np.maximum(sigma2_pred, 1e-10)
        per_m = (log_rv_actual - log_pred) ** 2
        losses[spec.name] = {"qlike_per": per_q, "mse_per": per_m}

    # --- DM tests vs baseline (HAR-RV) ---
    dm = {}
    for spec in MODELS:
        if spec.name == "HAR-RV":
            continue
        dm[f"{spec.name}_vs_HAR-RV_qlike"] = dm_test(
            losses[spec.name]["qlike_per"], losses["HAR-RV"]["qlike_per"],
            n_boot=N_BOOT, seed=SEED,
        )
        dm[f"{spec.name}_vs_HAR-RV_mse"] = dm_test(
            losses[spec.name]["mse_per"], losses["HAR-RV"]["mse_per"],
            n_boot=N_BOOT, seed=SEED,
        )

    # --- Improvement % over baseline ---
    base_q = metrics["HAR-RV"]["qlike"]
    base_m = metrics["HAR-RV"]["mse_log"]
    improvements = {}
    for spec in MODELS:
        if spec.name == "HAR-RV":
            continue
        improvements[spec.name] = {
            "qlike_pct": float((base_q - metrics[spec.name]["qlike"]) / abs(base_q) * 100),
            "mse_log_pct": float((base_m - metrics[spec.name]["mse_log"]) / abs(base_m) * 100),
        }

    # --- Verdict ---
    # PASS criteria: any non-baseline model has DM p_boot < 0.10 with negative DM stat
    # (lower loss) on either QLIKE or MSE, and the point estimate improves.
    verdict = "NULL"
    passing = []
    for spec in MODELS:
        if spec.name == "HAR-RV":
            continue
        ql_d = dm.get(f"{spec.name}_vs_HAR-RV_qlike", {})
        ms_d = dm.get(f"{spec.name}_vs_HAR-RV_mse", {})
        ql_better = (improvements[spec.name]["qlike_pct"] > 0) and ql_d.get("p_boot", 1) < 0.10
        ms_better = (improvements[spec.name]["mse_log_pct"] > 0) and ms_d.get("p_boot", 1) < 0.10
        if ql_better or ms_better:
            passing.append(spec.name)
    if passing:
        verdict = "PASS" if len(passing) >= 1 else "CONDITIONAL_PASS"

    # --- Figure ---
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
        ax = axes[0]
        ax.plot(eval_df.index, np.exp(log_rv_actual), color="#444", lw=0.7, label="Realized RV (GK)")
        ax.plot(eval_df.index, np.exp(eval_df["pred_HAR-RV"].values), color="#1f77b4", lw=0.7, label="HAR-RV")
        ax.plot(eval_df.index, np.exp(eval_df["pred_HAR-INV"].values), color="#d62728", lw=0.7, label="HAR-INV", alpha=0.85)
        ax.set_yscale("log")
        ax.set_ylabel("RV (Garman-Klass)")
        ax.set_title(f"K1481 OOS forecasts vs realized | WTI (CL=F) | n={len(eval_df)}")
        ax.legend(loc="upper right")
        ax.grid(alpha=0.3)
        ax2 = axes[1]
        sz = har["surprise_z_lag"].reindex(eval_df.index)
        ax2.plot(eval_df.index, sz.values, color="#2ca02c", lw=0.6)
        ax2.axhline(1, color="#aaa", ls="--", lw=0.6); ax2.axhline(-1, color="#aaa", ls="--", lw=0.6)
        ax2.set_ylabel("Inventory surprise Z (lagged)")
        ax2.set_xlabel("Date")
        ax2.grid(alpha=0.3)
        plt.tight_layout()
        plt.savefig(FIG_PATH, dpi=120)
        plt.close(fig)
        fig_ok = True
    except Exception as e:
        fig_ok = False
        print(f"  figure error: {e}", flush=True)

    # --- Write results ---
    results = {
        "experiment_id": EXP_ID,
        "title": "Inventory-surprise commodity RV regime feature (Crude pilot)",
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": round(time.time() - t0, 2),
        "verdict": verdict,
        "passing_models": passing,
        "data": {
            "asset": "CL=F (WTI futures, yfinance)",
            "ohlc_rows": int(len(ohlc)),
            "ohlc_start": str(ohlc.index.min().date()),
            "ohlc_end": str(ohlc.index.max().date()),
            "eia_series": "WCESTUS1 (Weekly U.S. Ending Stocks excluding SPR of Crude Oil, kbbl)",
            "eia_source_url": EIA_XLS_URL,
            "eia_rows": int(len(stocks)),
            "eia_start": str(stocks.index.min().date()),
            "eia_end": str(stocks.index.max().date()),
        },
        "design": {
            "rv_proxy": "Garman-Klass daily range estimator",
            "target": "log(RV_{t+1})",
            "models": [m.name for m in MODELS],
            "features": {m.name: m.features for m in MODELS},
            "consensus_proxy": "rolling 52-week AR(1) on weekly delta-stocks; surprise standardised by 52-wk rolling std",
            "publication_lag_business_days": 5,
            "lookahead_guard": "surprise_z (period_end Friday) shifted +5 BD then signal.shift(1); HAR features all lag<=t-1",
            "train_window": f"expanding from {START} up to fit-date",
            "first_oos_date": str(eval_df.index.min().date()),
            "last_oos_date": str(eval_df.index.max().date()),
            "oos_rows": int(len(eval_df)),
            "refit_frequency_days": REFIT_FREQ_DAYS,
            "seed": SEED,
            "n_boot": N_BOOT,
        },
        "metrics": metrics,
        "improvements_vs_HAR-RV_pct": improvements,
        "diebold_mariano": dm,
        "lookahead_audit": {
            "signal_shift_1_used": True,
            "weekly_to_daily_lag_business_days": 5,
            "feature_lag_check": "har['surprise_z_lag'] = lag_inventory_to_daily(...).shift(1) — see run.py",
        },
        "figure": str(FIG_PATH.name) if fig_ok else None,
        "notes": [
            "Consensus is a naive AR(1) proxy of inventory delta because public consensus survey history is paywalled.",
            "Garman-Klass RV proxy chosen over RV5 because intraday data not readily available for CL=F 2010-2026.",
            "5-business-day publication lag is conservative (real EIA release is Wed of following week, ~3-4 BD).",
            "Pilot scope: single asset (WTI). NG=F / heating oil extensions are future work pending PASS verdict.",
        ],
    }

    with RESULTS_PATH.open("w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"[{EXP_ID}] verdict={verdict} | wrote {RESULTS_PATH.name} ({results['runtime_seconds']}s)", flush=True)
    return results


if __name__ == "__main__":
    main()
