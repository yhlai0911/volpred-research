"""
K1316 — VIX Sufficient Statistic Test on TAIFEX TX1 (Cross-Market Replication)
===============================================================================

Research Background
-------------------
K1315 confirmed US VIX is a sufficient statistic for SPY daily RV:
  Anti-QLIKE forecast combination assigns HAR-VIX weight=1.0, HAR-ABS weight=0.0.

Natural extension: Does this cross-market? Does US VIX dominate the HAR-RV
baseline for Taiwan futures (TX1) realized volatility prediction?

Hypotheses
----------
H1: HAR-VIX (US VIX lags as features) achieves significantly lower QLIKE on
    TX1 than HAR-RV (own RV lags); DM-HLN |t| > 3.
H0 (NULL): VIX has no incremental predictive value over own past RV for TX1 RV.

Models
------
HAR-RV  (baseline): features = [log(RV_{t-1}), log(RV_w), log(RV_m)]
HAR-VIX (test):    features = [log(VIX²_{t-1}), log(VIX²_w), log(VIX²_m)]

Target: log(RV_{t+1}), i.e. .shift(-1) on RV.
All feature series .shift(1) before rolling to enforce strict lookahead discipline.

Loss Functions
--------------
Primary: QLIKE  = log(σ²_hat) + RV / σ²_hat  (Patton 2011, proxy-robust)
         where σ²_hat = exp(fitted log-RV) from OLS
Secondary: MSE on log(RV) predictions

Statistical Tests
-----------------
DM-HLN: Harvey (1997) small-sample correction, h=1, QLIKE losses
Pass rule: |DM_HLN_t| > 3 AND HAR-VIX lower QLIKE → PASS; else NULL
Bootstrap: 500x iid CI on QLIKE diff (seed=42)

Lookahead Discipline (HARD)
---------------------------
- rv_lag1 = rv.shift(1) then rolling for RV_w, RV_m
- vix_lag1 = vix.shift(1) then rolling for VIX_w, VIX_m
- Target: log(RV).shift(-1) on RV column ONLY
- 70/30 chronological split, no peeking

Data Sources
------------
- TX1 daily RV: reuse K1309 cache (_tx1_daily_pd_2017-2026.parquet) or rebuild
  from TAIFEX tick CSV (day session 08:45–13:45, 5-min bars)
- VIX daily: yfinance.download("^VIX", ...) close price

Author: Worktree agent (K1316, 2026-05-13)
"""
from __future__ import annotations

import json
import re
import sys
import time
import warnings
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

SEED = 42
RNG = np.random.default_rng(SEED)

# Re-use K1309 TX1 daily cache (already built from TAIFEX ticks)
K1309_DATA_DIR = SCRIPT_DIR.parent / "k1309" / "data"
CACHE_TX1 = K1309_DATA_DIR / "_tx1_daily_pd_2017-2026.parquet"

# TAIFEX raw tick dir (fallback if cache absent)
TAIFEX_DIR = Path.home() / "Dropbox/TAIFEXDATA/TAIFEXDATA/python"

# VIX cache
CACHE_VIX = DATA_DIR / "_vix_daily_2017-2026.parquet"


# ======================================================================
# 1) Data loaders
# ======================================================================

COLS_RAW = [
    "trade_date", "symbol", "contract_mo", "trade_time",
    "price", "qty", "near_price", "far_price",
    "auction_flag", "ts",
]


def _load_one_tx1(fn: Path) -> pd.DataFrame:
    """Read a single TAIFEX TX1 tick CSV file (K1309 convention)."""
    last_err = None
    df = None
    for enc in ("big5", "cp950", "utf-8"):
        try:
            df = pd.read_csv(fn, encoding=enc, low_memory=False, na_values=["-"])
            break
        except UnicodeDecodeError as e:
            last_err = e
            continue
    if df is None:
        raise RuntimeError(f"Decode failed for {fn.name}: {last_err}")
    if df.shape[1] != len(COLS_RAW):
        raise RuntimeError(f"{fn.name}: expected {len(COLS_RAW)} cols, got {df.shape[1]}")
    df.columns = COLS_RAW
    df = df[df["auction_flag"] != "*"].copy()
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["qty"] = pd.to_numeric(df["qty"], errors="coerce")
    df = df.dropna(subset=["price", "qty"])
    df = df[df["price"] > 0]
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    df = df.dropna(subset=["ts"])
    return df[["ts", "price", "qty"]].reset_index(drop=True)


def _build_tx1_day_5min(file_date: pd.Timestamp, ticks: pd.DataFrame) -> pd.DataFrame:
    if ticks.empty:
        return pd.DataFrame()
    day_start = file_date.normalize() + pd.Timedelta(hours=8, minutes=45)
    day_end = file_date.normalize() + pd.Timedelta(hours=13, minutes=45)
    mask = (ticks["ts"] >= day_start) & (ticks["ts"] <= day_end)
    day = ticks[mask].copy()
    if day.empty:
        return pd.DataFrame()
    day["bar_start"] = day["ts"].dt.floor("5min")
    is_endpoint = day["bar_start"] >= day_end
    if is_endpoint.any():
        day.loc[is_endpoint, "bar_start"] = day_end - pd.Timedelta(minutes=5)
    g = day.groupby("bar_start", sort=True)
    bars = g.agg(
        close=("price", "last"),
        n_ticks=("price", "count"),
    ).reset_index()
    bars["session_date"] = file_date.normalize()
    return bars


def _list_tx1_files(start: pd.Timestamp, end: pd.Timestamp) -> List[Path]:
    pattern = re.compile(r"Daily_(\d{4})_(\d{2})_(\d{2})TX1\.csv")
    files = []
    for fn in sorted(TAIFEX_DIR.glob("Daily_*TX1.csv")):
        m = pattern.match(fn.name)
        if not m:
            continue
        d = pd.Timestamp(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if start <= d <= end:
            files.append(fn)
    return files


def load_tx1_daily(force: bool = False) -> pd.DataFrame:
    """Load TX1 daily RV. Reuse K1309 cache if available, else rebuild."""
    if CACHE_TX1.exists() and not force:
        df = pd.read_parquet(CACHE_TX1)
        print(f"[TX1] Loaded {len(df)} rows from K1309 cache: {CACHE_TX1}")
        return df[["date", "rv"]].copy()

    print(f"[TX1] K1309 cache not found at {CACHE_TX1}, rebuilding from ticks...")
    if not TAIFEX_DIR.exists():
        raise RuntimeError(f"TAIFEX dir not found: {TAIFEX_DIR}")

    files = _list_tx1_files(pd.Timestamp("2017-01-01"), pd.Timestamp("2026-05-01"))
    print(f"[TX1] Found {len(files)} tick files")
    rows: List[dict] = []
    t0 = time.time()
    for i, fn in enumerate(files):
        m = re.match(r"Daily_(\d{4})_(\d{2})_(\d{2})TX1\.csv", fn.name)
        file_date = pd.Timestamp(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        try:
            ticks = _load_one_tx1(fn)
            bars = _build_tx1_day_5min(file_date, ticks)
            if bars.empty or len(bars) < 20:
                continue
            bars = bars.sort_values("bar_start").reset_index(drop=True)
            prices = bars["close"].to_numpy(dtype=float)
            rets = np.log(prices[1:] / prices[:-1])
            if len(rets) < 19:
                continue
            rv = float((rets ** 2).sum())
            rows.append({"date": file_date, "rv": rv})
        except Exception as e:
            print(f"  [warn] {fn.name}: {e}")
        if (i + 1) % 250 == 0:
            print(f"  [{i+1}/{len(files)}] elapsed={time.time()-t0:.1f}s")

    if not rows:
        raise RuntimeError("[TX1] No daily rows built")
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    local_cache = DATA_DIR / "_tx1_daily_2017-2026.parquet"
    df.to_parquet(local_cache, index=False)
    print(f"[TX1] Rebuilt {len(df)} rows → cached at {local_cache}")
    return df


def load_vix_daily(force: bool = False) -> pd.DataFrame:
    """Download or load cached VIX daily close prices."""
    if CACHE_VIX.exists() and not force:
        df = pd.read_parquet(CACHE_VIX)
        print(f"[VIX] Loaded {len(df)} rows from cache: {CACHE_VIX}")
        return df

    import yfinance as yf
    print("[VIX] Downloading from yfinance...")
    raw = yf.download("^VIX", start="2017-01-01", end="2026-05-01",
                      auto_adjust=True, progress=False)
    if raw is None or raw.empty:
        raise RuntimeError("[VIX] yfinance returned empty dataframe")

    # Handle MultiIndex columns
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    raw = raw.reset_index()
    date_col = "Date" if "Date" in raw.columns else raw.columns[0]
    raw = raw.rename(columns={date_col: "date", "Close": "vix_close"})
    raw["date"] = pd.to_datetime(raw["date"])
    if raw["date"].dt.tz is not None:
        raw["date"] = raw["date"].dt.tz_localize(None)
    raw = raw[["date", "vix_close"]].dropna().sort_values("date").reset_index(drop=True)
    raw.to_parquet(CACHE_VIX, index=False)
    print(f"[VIX] Downloaded {len(raw)} rows → cached at {CACHE_VIX}")
    return raw


# ======================================================================
# 2) Feature engineering — HAR-RV and HAR-VIX
# ======================================================================

def build_har_features(tx1: pd.DataFrame, vix: pd.DataFrame) -> pd.DataFrame:
    """
    Build aligned daily dataset with HAR-RV and HAR-VIX features.

    Strict lookahead discipline:
    - rv_lag1 = rv.shift(1) ON THE TX1-ONLY SERIES before any rolling
    - vix_lag1 = vix.shift(1) ON THE VIX-ONLY SERIES before any rolling
    - HAR lags are built on each series independently, then merged
    - This preserves true own-calendar lags (not compressed by inner-join holes)
    - Target = rv.shift(-1) applied to TX1-only series, then merged

    HAR-RV features (all in log space, built on TX1 series):
        rv_d  = log(rv_lag1)                      -- daily lag on TX1 calendar
        rv_w  = log(rv_lag1.rolling(5).mean())    -- weekly avg on TX1 calendar
        rv_m  = log(rv_lag1.rolling(22).mean())   -- monthly avg on TX1 calendar

    HAR-VIX features (VIX² in log space, built on VIX series):
        vix_d = log(vix_lag1²)                    -- daily lag on VIX calendar
        vix_w = log(vix_lag1.rolling(5).mean()²)  -- NOTE: avg VIX first, then square
        vix_m = log(vix_lag1.rolling(22).mean()²)

    Note: We use log((avg_VIX)²) = 2*log(avg_VIX) rather than log(avg(VIX²))
    because avg_VIX is the natural HAR analogy (averaging the level, then squaring).
    This is analogous to HAR-RV which averages the RV (not the sqrt).

    Merge strategy: build all features and target on respective own calendars first,
    then inner-join to get dates with both TX1 and VIX available.

    Target: log(RV_{t+1}) via rv.shift(-1) on TX1 series only, before merge.
    """
    eps = 1e-12

    # --- Build TX1 features on TX1 own calendar (BEFORE merging) ---
    tx1 = tx1[["date", "rv"]].copy().sort_values("date").reset_index(drop=True)
    tx1["date"] = pd.to_datetime(tx1["date"])

    # HAR-RV features: shift(1) on TX1 calendar, then rolling on TX1 calendar
    rv_lag1 = tx1["rv"].shift(1)                                        # lag1 on TX1 calendar
    tx1["rv_d"] = rv_lag1
    tx1["rv_w"] = rv_lag1.rolling(window=5, min_periods=5).mean()       # 5-day avg on TX1 cal
    tx1["rv_m"] = rv_lag1.rolling(window=22, min_periods=22).mean()     # 22-day avg on TX1 cal

    # Target: RV_{t+1} on TX1 calendar (shift -1 on TX1 only)
    tx1["rv_next"] = tx1["rv"].shift(-1)

    # --- Build VIX features on VIX own calendar (BEFORE merging) ---
    vix = vix[["date", "vix_close"]].copy().sort_values("date").reset_index(drop=True)
    vix["date"] = pd.to_datetime(vix["date"])

    # HAR-VIX features: shift(1) on VIX calendar, then rolling on VIX calendar
    vix_lag1 = vix["vix_close"].shift(1)                                # lag1 on VIX calendar
    vix["vix_d"] = vix_lag1
    vix["vix_w"] = vix_lag1.rolling(window=5, min_periods=5).mean()    # 5-day avg on VIX cal
    vix["vix_m"] = vix_lag1.rolling(window=22, min_periods=22).mean()  # 22-day avg on VIX cal

    # --- Inner join on date ---
    # At this point, lags/rolling are already computed on respective own calendars.
    # Inner join selects dates where both TX1 and VIX are available.
    df = pd.merge(
        tx1[["date", "rv", "rv_d", "rv_w", "rv_m", "rv_next"]],
        vix[["date", "vix_close", "vix_d", "vix_w", "vix_m"]],
        on="date", how="inner"
    )
    df = df.sort_values("date").reset_index(drop=True)
    print(f"[Features] After inner join: {len(df)} rows, date range: {df['date'].min()} to {df['date'].max()}")

    # --- Drop NaN rows (warm-up + last row with no future target) ---
    feature_cols = ["rv_d", "rv_w", "rv_m", "vix_d", "vix_w", "vix_m", "rv_next"]
    df = df.dropna(subset=feature_cols).reset_index(drop=True)
    print(f"[Features] After dropna: {len(df)} rows")

    # --- Log transforms ---
    # HAR-RV: log(RV) -- RV must be positive
    df["log_rv_d"] = np.log(df["rv_d"].clip(lower=eps))
    df["log_rv_w"] = np.log(df["rv_w"].clip(lower=eps))
    df["log_rv_m"] = np.log(df["rv_m"].clip(lower=eps))

    # HAR-VIX: log(VIX²) = 2*log(VIX) -- VIX always > 0
    df["log_vix2_d"] = 2.0 * np.log(df["vix_d"].clip(lower=eps))
    df["log_vix2_w"] = 2.0 * np.log(df["vix_w"].clip(lower=eps))
    df["log_vix2_m"] = 2.0 * np.log(df["vix_m"].clip(lower=eps))

    # Target: log(RV_{t+1})
    df["Y"] = np.log(df["rv_next"].clip(lower=eps))

    return df


# ======================================================================
# 3) OLS estimation
# ======================================================================

def fit_ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """OLS with intercept. Returns beta = [intercept, b1, b2, b3]."""
    X1 = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    return beta


def predict_ols(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    X1 = np.column_stack([np.ones(len(X)), X])
    return X1 @ beta


# ======================================================================
# 4) Loss functions
# ======================================================================

def qlike_loss(rv_true: np.ndarray, log_rv_hat: np.ndarray) -> np.ndarray:
    """
    QLIKE loss (Patton 2011):
        L(σ², RV) = log(σ²) + RV / σ²

    where σ² = exp(log_rv_hat) is the predicted variance proxy.
    rv_true is the realized variance (actual RV, not log scale).
    """
    eps = 1e-12
    sigma2_hat = np.exp(log_rv_hat)
    sigma2_hat = np.maximum(sigma2_hat, eps)
    return np.log(sigma2_hat) + rv_true / sigma2_hat


def mse_loss(y_true: np.ndarray, y_hat: np.ndarray) -> np.ndarray:
    """MSE in log(RV) space."""
    return (y_true - y_hat) ** 2


# ======================================================================
# 5) DM-HLN test
# ======================================================================

def dm_hln(loss_a: np.ndarray, loss_b: np.ndarray, h: int = 1) -> Tuple[float, float]:
    """
    Diebold-Mariano with Harvey-Leybourne-Newbold (1997) small-sample correction.

    d_t = loss_a[t] - loss_b[t]
    Positive d_mean => a worse => b preferred.
    Returns (HLN t-stat, p-value).
    """
    from scipy import stats as sp_stats
    d = np.asarray(loss_a, dtype=float) - np.asarray(loss_b, dtype=float)
    T = len(d)
    if T < 3:
        return float("nan"), float("nan")
    mu = d.mean()
    if h <= 1:
        v = float(((d - mu) ** 2).mean())
    else:
        gammas = [float(((d[:T - k] - mu) * (d[k:] - mu)).mean()) for k in range(h)]
        v = gammas[0] + 2.0 * sum(gammas[1:])
    if v <= 0:
        return float("nan"), float("nan")
    dm = mu / np.sqrt(v / T)
    # HLN small-sample correction factor
    corr = np.sqrt((T + 1 - 2 * h + h * (h - 1) / T) / T)
    hln = dm * corr
    p = 2.0 * (1.0 - sp_stats.t.cdf(abs(hln), df=T - 1))
    return float(hln), float(p)


# ======================================================================
# 6) Bootstrap CI on QLIKE diff
# ======================================================================

def bootstrap_qlike_ci(
    loss_a: np.ndarray, loss_b: np.ndarray,
    n_boot: int = 500, seed: int = SEED
) -> Tuple[float, float, float]:
    """
    Bootstrap 95% CI on mean(loss_a) - mean(loss_b).
    Positive point estimate => a worse, b preferred.
    Returns (point_diff, lo95, hi95).
    """
    rng = np.random.default_rng(seed)
    a = np.asarray(loss_a, dtype=float)
    b = np.asarray(loss_b, dtype=float)
    T = len(a)
    point = float(a.mean() - b.mean())
    diffs = np.empty(n_boot)
    for k in range(n_boot):
        idx = rng.integers(0, T, T)
        diffs[k] = a[idx].mean() - b[idx].mean()
    return point, float(np.quantile(diffs, 0.025)), float(np.quantile(diffs, 0.975))


# ======================================================================
# 7) R² helper
# ======================================================================

def r_squared(y_true: np.ndarray, y_hat: np.ndarray) -> float:
    ss_res = float(((y_true - y_hat) ** 2).sum())
    ss_tot = float(((y_true - y_true.mean()) ** 2).sum())
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")


# ======================================================================
# 8) Main evaluation
# ======================================================================

def evaluate(df: pd.DataFrame) -> Dict:
    """
    Run HAR-RV vs HAR-VIX evaluation on the merged DataFrame.
    Returns full results dict.
    """
    har_rv_cols = ["log_rv_d", "log_rv_w", "log_rv_m"]
    har_vix_cols = ["log_vix2_d", "log_vix2_w", "log_vix2_m"]

    y = df["Y"].to_numpy(dtype=float)
    rv_true = df["rv_next"].to_numpy(dtype=float)  # actual RV for QLIKE
    X_rv = df[har_rv_cols].to_numpy(dtype=float)
    X_vix = df[har_vix_cols].to_numpy(dtype=float)

    T = len(df)
    n_train = int(np.floor(T * 0.70))
    n_test = T - n_train

    print(f"[Eval] T={T}, n_train={n_train}, n_test={n_test}")
    print(f"[Eval] IS: {df['date'].iloc[0]} to {df['date'].iloc[n_train-1]}")
    print(f"[Eval] OOS: {df['date'].iloc[n_train]} to {df['date'].iloc[-1]}")

    idx_tr = np.arange(n_train)
    idx_te = np.arange(n_train, T)

    # --- Fit OLS on IS ---
    beta_rv  = fit_ols(X_rv[idx_tr],  y[idx_tr])
    beta_vix = fit_ols(X_vix[idx_tr], y[idx_tr])

    # --- Predict OOS ---
    yhat_rv_te  = predict_ols(beta_rv,  X_rv[idx_te])
    yhat_vix_te = predict_ols(beta_vix, X_vix[idx_te])

    # --- Predict IS (for R²) ---
    yhat_rv_tr  = predict_ols(beta_rv,  X_rv[idx_tr])
    yhat_vix_tr = predict_ols(beta_vix, X_vix[idx_tr])

    # --- QLIKE losses (OOS) ---
    qlike_rv_te  = qlike_loss(rv_true[idx_te], yhat_rv_te)
    qlike_vix_te = qlike_loss(rv_true[idx_te], yhat_vix_te)

    # --- MSE losses (OOS, log-RV space) ---
    mse_rv_te  = mse_loss(y[idx_te], yhat_rv_te)
    mse_vix_te = mse_loss(y[idx_te], yhat_vix_te)

    mean_qlike_rv  = float(qlike_rv_te.mean())
    mean_qlike_vix = float(qlike_vix_te.mean())
    mean_mse_rv    = float(mse_rv_te.mean())
    mean_mse_vix   = float(mse_vix_te.mean())

    print(f"[Eval] QLIKE  HAR-RV={mean_qlike_rv:.6f}  HAR-VIX={mean_qlike_vix:.6f}")
    print(f"[Eval] MSE    HAR-RV={mean_mse_rv:.6f}   HAR-VIX={mean_mse_vix:.6f}")

    # --- DM-HLN on QLIKE ---
    dm_t_qlike, dm_p_qlike = dm_hln(qlike_rv_te, qlike_vix_te, h=1)
    # --- DM-HLN on MSE ---
    dm_t_mse, dm_p_mse = dm_hln(mse_rv_te, mse_vix_te, h=1)

    print(f"[Eval] DM-HLN QLIKE: t={dm_t_qlike:.4f}, p={dm_p_qlike:.4f}")
    print(f"[Eval] DM-HLN MSE:   t={dm_t_mse:.4f}, p={dm_p_mse:.4f}")

    # --- Bootstrap CI on QLIKE diff ---
    ql_diff_point, ql_diff_lo, ql_diff_hi = bootstrap_qlike_ci(
        qlike_rv_te, qlike_vix_te, n_boot=500, seed=SEED
    )
    print(f"[Eval] Bootstrap QLIKE diff: {ql_diff_point:.6f} [{ql_diff_lo:.6f}, {ql_diff_hi:.6f}]")

    # --- R² ---
    r2_rv_is   = r_squared(y[idx_tr], yhat_rv_tr)
    r2_rv_oos  = r_squared(y[idx_te], yhat_rv_te)
    r2_vix_is  = r_squared(y[idx_tr], yhat_vix_tr)
    r2_vix_oos = r_squared(y[idx_te], yhat_vix_te)

    # --- Verdict ---
    pass_3sigma_qlike  = (not np.isnan(dm_t_qlike)) and abs(dm_t_qlike) > 3.0
    vix_lower_qlike    = mean_qlike_vix < mean_qlike_rv
    ci_excludes_zero_ql = (ql_diff_lo > 0) or (ql_diff_hi < 0)

    if pass_3sigma_qlike and vix_lower_qlike and ci_excludes_zero_ql:
        verdict = "PASS"
    elif pass_3sigma_qlike and vix_lower_qlike:
        verdict = "PASS_CONDITIONAL"
    else:
        verdict = "NULL"

    print(f"\n[Eval] Verdict: {verdict}")
    print(f"         pass_3sigma_qlike={pass_3sigma_qlike}, vix_lower_qlike={vix_lower_qlike}")
    print(f"         ci_excludes_zero_ql={ci_excludes_zero_ql}")

    date_arr = df["date"].dt.strftime("%Y-%m-%d").to_numpy()

    return {
        "n_total": int(T),
        "n_train": int(n_train),
        "n_test": int(n_test),
        "date_range_is": [str(date_arr[0]), str(date_arr[n_train - 1])],
        "date_range_oos": [str(date_arr[n_train]), str(date_arr[-1])],
        "har_rv": {
            "features": har_rv_cols,
            "beta": {k: float(v) for k, v in zip(
                ["intercept", "log_rv_d", "log_rv_w", "log_rv_m"], beta_rv
            )},
            "qlike_oos": mean_qlike_rv,
            "mse_oos": mean_mse_rv,
            "r2_is": float(r2_rv_is),
            "r2_oos": float(r2_rv_oos),
        },
        "har_vix": {
            "features": har_vix_cols,
            "beta": {k: float(v) for k, v in zip(
                ["intercept", "log_vix2_d", "log_vix2_w", "log_vix2_m"], beta_vix
            )},
            "qlike_oos": mean_qlike_vix,
            "mse_oos": mean_mse_vix,
            "r2_is": float(r2_vix_is),
            "r2_oos": float(r2_vix_oos),
        },
        "dm_tests": {
            "qlike": {
                "loss": "QLIKE (Patton 2011)",
                "h": 1,
                "t_stat": float(dm_t_qlike),
                "p_value": float(dm_p_qlike),
                "interpretation_sign": "positive => HAR-RV worse (higher QLIKE) => HAR-VIX preferred",
                "harvey_threshold": 3.0,
                "pass_3sigma": bool(pass_3sigma_qlike),
            },
            "mse": {
                "loss": "MSE on log(RV)",
                "h": 1,
                "t_stat": float(dm_t_mse),
                "p_value": float(dm_p_mse),
                "interpretation_sign": "positive => HAR-RV worse (higher MSE) => HAR-VIX preferred",
                "harvey_threshold": 3.0,
            },
        },
        "bootstrap": {
            "n_boot": 500,
            "seed": SEED,
            "loss": "QLIKE",
            "qlike_diff_point_rv_minus_vix": float(ql_diff_point),
            "qlike_diff_ci95": [float(ql_diff_lo), float(ql_diff_hi)],
            "ci_excludes_zero": bool(ci_excludes_zero_ql),
            "interpretation": "positive diff => HAR-RV higher QLIKE => HAR-VIX preferred",
        },
        "verdict_components": {
            "pass_3sigma_dm_qlike": bool(pass_3sigma_qlike),
            "vix_lower_qlike": bool(vix_lower_qlike),
            "bootstrap_ci_excludes_zero": bool(ci_excludes_zero_ql),
        },
        "verdict": verdict,
    }


# ======================================================================
# 9) Plotting
# ======================================================================

def make_plots(df: pd.DataFrame, results: Dict, out_dir: Path) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        n_train = results["n_train"]
        y_all = df["Y"].to_numpy(dtype=float)
        rv_true = df["rv_next"].to_numpy(dtype=float)

        har_rv_cols  = ["log_rv_d", "log_rv_w", "log_rv_m"]
        har_vix_cols = ["log_vix2_d", "log_vix2_w", "log_vix2_m"]
        X_rv  = df[har_rv_cols].to_numpy(dtype=float)
        X_vix = df[har_vix_cols].to_numpy(dtype=float)

        beta_rv  = fit_ols(X_rv[:n_train],  y_all[:n_train])
        beta_vix = fit_ols(X_vix[:n_train], y_all[:n_train])
        yhat_rv  = predict_ols(beta_rv,  X_rv[n_train:])
        yhat_vix = predict_ols(beta_vix, X_vix[n_train:])

        ql_rv  = qlike_loss(rv_true[n_train:], yhat_rv)
        ql_vix = qlike_loss(rv_true[n_train:], yhat_vix)
        dates  = pd.to_datetime(df["date"].iloc[n_train:].to_numpy())

        fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))

        # Cumulative QLIKE
        axes[0].plot(dates, np.cumsum(ql_rv),  label="HAR-RV",  color="tab:blue")
        axes[0].plot(dates, np.cumsum(ql_vix), label="HAR-VIX", color="tab:red")
        axes[0].set_title("TX1 OOS: Cumulative QLIKE Loss")
        axes[0].set_ylabel("Cumulative QLIKE")
        axes[0].legend()
        axes[0].grid(alpha=0.3)
        for lbl in axes[0].get_xticklabels():
            lbl.set_rotation(30)

        # QLIKE scatter
        lim = max(float(ql_rv.max()), float(ql_vix.max())) * 1.05
        axes[1].scatter(ql_rv, ql_vix, s=6, alpha=0.35, color="tab:gray")
        axes[1].plot([0, lim], [0, lim], "k--", lw=1)
        axes[1].set_xlabel("HAR-RV QLIKE")
        axes[1].set_ylabel("HAR-VIX QLIKE")
        axes[1].set_title("Per-day QLIKE (below 45° = HAR-VIX wins)")
        axes[1].grid(alpha=0.3)

        dm_t = results["dm_tests"]["qlike"]["t_stat"]
        verdict = results["verdict"]
        fig.suptitle(
            f"K1316 HAR-VIX vs HAR-RV on TX1 (OOS n={results['n_test']})  "
            f"DM-HLN t={dm_t:.2f}  verdict={verdict}"
        )
        fig.tight_layout()
        out_path = out_dir / "k1316_qlike_plot.png"
        fig.savefig(out_path, dpi=130)
        plt.close(fig)
        print(f"[plot] wrote {out_path}")
    except Exception as e:
        print(f"[plot] skipped: {e}")


# ======================================================================
# 10) Main
# ======================================================================

def main():
    t_start = time.time()

    out: Dict = {
        "experiment_id": "K1316",
        "title": "VIX Sufficient Statistic Test on TAIFEX TX1 — Cross-Market Replication of K1315",
        "date_run": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seed": SEED,
        "research_background": (
            "K1315 confirmed: US VIX is a sufficient statistic for SPY daily RV — "
            "Anti-QLIKE combination assigns HAR-VIX weight=1.0, HAR-ABS weight=0.0. "
            "K1316 tests cross-market replication: does US VIX dominate HAR-RV for "
            "Taiwan futures (TX1) RV prediction?"
        ),
        "hypotheses": {
            "H1": "HAR-VIX QLIKE < HAR-RV QLIKE on TX1, with DM-HLN |t| > 3",
            "H0": "VIX has no incremental predictive value over own past RV for TX1 RV",
        },
        "methodology": {
            "target": "log(RV_{t+1}), via rv.shift(-1) on TX1 daily realized variance",
            "har_rv_features": [
                "log(rv_lag1) — daily lag",
                "log(rv_lag1.rolling(5).mean()) — weekly avg",
                "log(rv_lag1.rolling(22).mean()) — monthly avg",
            ],
            "har_vix_features": [
                "2*log(vix_lag1) = log(VIX²_{t-1}) — daily lag",
                "2*log(vix_lag1.rolling(5).mean()) — weekly avg of VIX then squared",
                "2*log(vix_lag1.rolling(22).mean()) — monthly avg of VIX then squared",
            ],
            "lookahead_guard": (
                "rv_lag1 = rv.shift(1) BEFORE rolling; "
                "vix_lag1 = vix.shift(1) BEFORE rolling; "
                "target = rv.shift(-1) on RV column only; "
                "70/30 chronological split, fit on IS only"
            ),
            "primary_loss": "QLIKE (Patton 2011) — proxy-robust, theoretically justified",
            "secondary_loss": "MSE on log(RV)",
            "dm_test": "DM-HLN Harvey (1997) h=1, on QLIKE losses",
            "pass_rule": "|DM_HLN_t| > 3 AND HAR-VIX lower QLIKE AND bootstrap 95% CI excludes 0",
            "bootstrap": "500x iid bootstrap (seed=42) on QLIKE diff",
            "split": "70/30 chronological",
        },
        "data_sources": {
            "TX1": (
                "TAIFEX TX1 tick CSV from K1309 cache (_tx1_daily_pd_2017-2026.parquet), "
                "day session 08:45–13:45, 5-min realized variance"
            ),
            "VIX": "yfinance ^VIX daily close, 2017-01-01 to 2026-05-01",
            "alignment": "Inner join on trading date (Taiwan vs US may differ on holidays)",
        },
    }

    # --- Load data ---
    print("\n[K1316] Loading TX1 daily RV...")
    tx1 = load_tx1_daily(force=False)

    print("\n[K1316] Loading VIX daily...")
    vix = load_vix_daily(force=False)

    # --- Build features ---
    print("\n[K1316] Building features...")
    df = build_har_features(tx1, vix)

    out["data_summary"] = {
        "tx1_raw_rows": int(len(tx1)),
        "vix_raw_rows": int(len(vix)),
        "merged_rows": int(len(df)),
        "date_range": [
            str(df["date"].min().date()),
            str(df["date"].max().date()),
        ],
        "rv_stats": {
            "mean": float(df["rv_next"].mean()),
            "std":  float(df["rv_next"].std()),
            "min":  float(df["rv_next"].min()),
            "max":  float(df["rv_next"].max()),
        },
        "vix_stats": {
            "mean": float(df["vix_d"].mean()),
            "std":  float(df["vix_d"].std()),
            "min":  float(df["vix_d"].min()),
            "max":  float(df["vix_d"].max()),
        },
    }

    # --- Evaluate ---
    print("\n[K1316] Running evaluation...")
    results = evaluate(df)
    out["model_metrics"] = results
    out["verdict"] = results["verdict"]
    out["dm_tests"] = results["dm_tests"]

    # --- Conclusions ---
    verdict = results["verdict"]
    dm_t_qlike  = results["dm_tests"]["qlike"]["t_stat"]
    qlike_rv    = results["har_rv"]["qlike_oos"]
    qlike_vix   = results["har_vix"]["qlike_oos"]
    qlike_pct   = 100.0 * (qlike_rv - qlike_vix) / abs(qlike_rv) if qlike_rv != 0 else 0.0

    if verdict == "PASS":
        conclusion_str = (
            f"PASS: US VIX IS a sufficient statistic for TX1 RV across markets. "
            f"HAR-VIX QLIKE={qlike_vix:.6f} < HAR-RV QLIKE={qlike_rv:.6f} "
            f"({qlike_pct:+.1f}%), DM-HLN t={dm_t_qlike:.3f} > 3.0. "
            f"Cross-market replication of K1315 result confirmed."
        )
    elif verdict == "PASS_CONDITIONAL":
        conclusion_str = (
            f"PASS_CONDITIONAL: HAR-VIX lower QLIKE and DM |t|>3, "
            f"but bootstrap CI does not fully exclude zero. "
            f"HAR-VIX QLIKE={qlike_vix:.6f} vs HAR-RV QLIKE={qlike_rv:.6f}. "
            f"DM-HLN t={dm_t_qlike:.3f}."
        )
    else:
        conclusion_str = (
            f"NULL: VIX is NOT a sufficient statistic for TX1 RV. "
            f"HAR-VIX QLIKE={qlike_vix:.6f} vs HAR-RV QLIKE={qlike_rv:.6f} "
            f"({qlike_pct:+.1f}%), DM-HLN t={dm_t_qlike:.3f}. "
            f"K1315 result (VIX sufficient for SPY) does not generalize cross-market to Taiwan futures. "
            f"Supports domestic RV persistence dominates foreign vol signal for TX1."
        )

    out["conclusions"] = {
        "primary": conclusion_str,
        "cross_market_replication": verdict in ("PASS", "PASS_CONDITIONAL"),
        "k1315_comparison": (
            "K1315: HAR-VIX weight=1.0 for SPY (VIX sufficient for own-market RV). "
            f"K1316: verdict={verdict} for TX1 (cross-market test). "
            "Together these experiments characterize the VIX sufficient statistic "
            "hypothesis within-market vs cross-market."
        ),
        "null_result_interpretation": (
            "NULL result is informative: domestic RV persistence (HAR-RV) "
            "is sufficient for TX1 volatility prediction; US fear gauge "
            "does not provide incremental information beyond own past RV."
            if verdict == "NULL" else ""
        ),
    }

    elapsed = time.time() - t_start
    out["runtime_seconds"] = float(f"{elapsed:.1f}")

    # --- Save results ---
    out_path = SCRIPT_DIR / "k1316_results.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[K1316] Results written to {out_path}")

    # --- Plot ---
    make_plots(df, results, SCRIPT_DIR)

    print(f"\n{'='*60}")
    print(f"K1316 VERDICT: {verdict}")
    print(f"  HAR-RV  QLIKE OOS: {qlike_rv:.6f}")
    print(f"  HAR-VIX QLIKE OOS: {qlike_vix:.6f}  ({qlike_pct:+.1f}%)")
    print(f"  DM-HLN t (QLIKE):  {dm_t_qlike:.4f}  p={results['dm_tests']['qlike']['p_value']:.4f}")
    print(f"  Bootstrap CI:      {results['bootstrap']['qlike_diff_ci95']}")
    print(f"  n_train={results['n_train']}, n_test={results['n_test']}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
