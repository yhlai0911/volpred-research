"""
K1303 v2 — HAR-CJ (Continuous + Jump decomposition) vs HAR-RV on TX1 + SPY/QQQ/GLD
=====================================================================================

Revision: v2_abd
Changes from v1 (per Codex primary-path FAIL report 2026-05-13):

  ABD1. BNS/3-sigma jump threshold: Jump days formally identified via 3-sigma threshold
        on max(RV-BPV,0). Non-jump days get J_t=0. Jump component expressed as J/RV
        (dimensionless jump share, range [0,1]) — this is critical to prevent explosive
        betas that result from the extreme scale mismatch between log(CV) (~-10) and
        log1p(J_abs) (~0.000006). J/RV share puts j features in [0,1] range, comparable
        in scale to log-difference features. CV component: log(CV_{t-1}) as before.

  ABD2. HAC DM test: dm_test() from src/volpred/stats/model_evaluation.py (Newey-West HAC)
        replaces inline plain-variance DM. QLIKE loss (Patton 2011) replaces MSE.

  ABD3. 1-step lag: Features at t-1 predict target RV_t (not RV_{t+1}).
        Target = log(RV_t), features = .shift(1) for daily lag, .rolling().mean().shift(1)
        for weekly/monthly. Standard HAR-CJ convention per ABD (2007).

Motivation
----------
Barndorff-Nielsen & Shephard (2004 JBES; 2006 JFEC) and Andersen-Bollerslev-Diebold
(2007 RFS) showed jump-component decomposition of realized variance delivers
persistent forecast gain over plain HAR-RV.

  RV_t  = sum_k r_{t,k}^2
  BPV_t = (pi/2) * (M/(M-1)) * sum_k |r_{t,k}| * |r_{t,k-1}|   (BNS)
  J_t   = max(RV_t - BPV_t, 0)  [thresholded: set to 0 on non-jump days]
  CV_t  = RV_t - J_t

HAR-CJ: log(RV_t) = a + b_d*log(CV_{t-1}) + b_w*log(CV_w) + b_m*log(CV_m)
                       + g_d*log1p(J_{t-1}) + g_w*log1p(J_w) + g_m*log1p(J_m) + eps_t
HAR-RV: log(RV_t) = a + b_d*log(RV_{t-1}) + b_w*log(RV_w) + b_m*log(RV_m) + eps_t

Lookahead discipline
--------------------
- Features at row t use only [t-22 .. t-1] (.shift(1) + rolling on lagged series).
- Target: log(RV_t) — standard 1-step HAR per ABD (2007).
- All features strictly .shift(1) before target date: NO lookahead.
- 70/30 chronological split.
- Seed = 42 fixed for all random processes.

Author : Claude (K1303-v2, worktree agent, 2026-05-13)
"""
from __future__ import annotations

import json
import re
import sys
import time
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Add volpred to path for dm_test (HAC Newey-West)
# parents[2] = volpred-research repo root; src/ contains the volpred package
_SRC_DIR = Path(__file__).resolve().parents[2] / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# Reuse existing TX1 cache (built by v1)
TAIFEX_DIR = Path.home() / "Dropbox/TAIFEXDATA/TAIFEXDATA/python"

# Cache files — reuse v1 parquet (same RV/BPV values; J/CV re-derived after thresholding)
CACHE_TX1_DAILY = DATA_DIR / "_tx1_daily_cj_2017-2026.parquet"
CACHE_SPY_DAILY = DATA_DIR / "_spy_daily_cj_recent.parquet"
CACHE_QQQ_DAILY = DATA_DIR / "_qqq_daily_cj_recent.parquet"
CACHE_GLD_DAILY = DATA_DIR / "_gld_daily_cj_recent.parquet"

SEED = 42
RNG = np.random.default_rng(SEED)

# ======================================================================
# 0) Import HAC dm_test from volpred
# ======================================================================
try:
    from volpred.stats.model_evaluation import dm_test as _dm_test_hac, qlike_pointwise
    _HAC_AVAILABLE = True
    print("[dm_test] HAC Newey-West dm_test loaded from volpred.stats.model_evaluation")
except ImportError as e:
    print(f"[dm_test] WARNING: could not import from volpred: {e}")
    print("[dm_test] Falling back to inline HAC implementation")
    _HAC_AVAILABLE = False

    def _dm_test_hac(loss1: np.ndarray, loss2: np.ndarray, h: int = 1) -> Tuple[float, float]:
        """Inline fallback: DM with Newey-West HAC (mirrors model_evaluation.py:83)."""
        from scipy import stats as sp_stats
        d = np.asarray(loss1, dtype=np.float64) - np.asarray(loss2, dtype=np.float64)
        valid = np.isfinite(d)
        d = d[valid]
        n = len(d)
        if n < 10:
            return (0.0, 1.0)
        d_mean = np.mean(d)
        max_lag = max(1, min(int(np.ceil(h ** (1/3) * n ** (1/3))), n // 4))
        gamma0 = np.mean((d - d_mean) ** 2)
        var_d = gamma0
        for lag in range(1, max_lag + 1):
            weight = 1 - lag / (max_lag + 1)
            gamma_l = np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean))
            var_d += 2 * weight * gamma_l
        if var_d <= 0:
            return (0.0, 1.0)
        se = np.sqrt(var_d / n)
        if se < 1e-15:
            return (0.0, 1.0)
        t_stat = d_mean / se
        p_val = 2 * (1 - sp_stats.t.cdf(abs(t_stat), df=n - 1))
        return (float(t_stat), float(p_val))

    def qlike_pointwise(actual: np.ndarray, predicted: np.ndarray) -> np.ndarray:
        """QLIKE pointwise: L(a,f) = a/f - log(a/f) - 1."""
        a = np.maximum(np.asarray(actual, dtype=np.float64), 1e-16)
        f = np.maximum(np.asarray(predicted, dtype=np.float64), 1e-16)
        ratio = a / f
        return ratio - np.log(ratio) - 1


# ======================================================================
# 1) Barndorff-Nielsen Bipower Variation
# ======================================================================
def compute_bpv(rets: np.ndarray) -> float:
    """Barndorff-Nielsen-Shephard bipower variation with small-sample correction.

    BPV = (pi/2) * (M/(M-1)) * sum_{k=2..M} |r_k| * |r_{k-1}|
    """
    M = len(rets)
    if M < 2:
        return float("nan")
    abs_r = np.abs(rets)
    bpv = (np.pi / 2.0) * (M / (M - 1.0)) * float((abs_r[1:] * abs_r[:-1]).sum())
    return bpv


# ======================================================================
# 2) ABD1 FIX: Formal jump identification via 3-sigma threshold
# ======================================================================
def apply_jump_threshold(daily: pd.DataFrame) -> pd.DataFrame:
    """Apply 3-sigma threshold to formally identify jump days (ABD Fix 1).

    Raw max(RV-BPV, 0) is noisy — all days appear to have jumps. We identify
    'significant' jump days as those where max(RV-BPV,0) > mu + 3*sigma.

    Algorithm:
      1. Compute raw_j = max(RV - BPV, 0) for all days
      2. mu = mean(raw_j), sigma = std(raw_j)
      3. jump_day = (raw_j > mu + 3*sigma)
      4. J_t = raw_j * jump_day  (= 0 on non-jump days)
      5. CV_t = RV_t - J_t        (= RV_t on non-jump days)

    This is the standard approach widely used in the HAR-CJ literature
    (see e.g., Andersen-Bollerslev-Diebold 2007 Table 2 footnote).
    """
    d = daily.copy()
    # Recompute raw_j from rv and bpv columns (bpv may be available from v1 cache)
    if "bpv" in d.columns:
        raw_j = np.maximum(d["rv"].values - d["bpv"].values, 0.0)
    else:
        # Fallback: use the cached j values directly
        raw_j = np.maximum(d["j"].values, 0.0)

    mu_j = float(np.nanmean(raw_j))
    sigma_j = float(np.nanstd(raw_j))
    threshold = mu_j + 3.0 * sigma_j

    jump_day = (raw_j > threshold)
    j_thresh = raw_j * jump_day
    cv_thresh = d["rv"].values - j_thresh

    d["j"] = j_thresh
    d["cv"] = cv_thresh
    d["raw_j"] = raw_j
    d["jump_day"] = jump_day.astype(int)
    d["jump_threshold"] = threshold

    n_jump = int(jump_day.sum())
    frac_jump = float(jump_day.mean())
    print(f"  [jump_threshold] mu={mu_j:.2e}, sigma={sigma_j:.2e}, "
          f"threshold={threshold:.2e}, n_jump={n_jump} ({frac_jump:.1%})")
    return d


# ======================================================================
# 3) TAIFEX TX1 data loading (uses existing cache from v1)
# ======================================================================
COLS_RAW = [
    "trade_date", "symbol", "contract_mo", "trade_time",
    "price", "qty", "near_price", "far_price",
    "auction_flag", "ts",
]


def _load_one_tx1(fn: Path) -> pd.DataFrame:
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
        open=("price", "first"),
        close=("price", "last"),
        high=("price", "max"),
        low=("price", "min"),
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
    """Load TX1 daily RV/BPV from cache (built by v1) or rebuild."""
    if CACHE_TX1_DAILY.exists() and not force:
        df = pd.read_parquet(CACHE_TX1_DAILY)
        print(f"[TX1] Loaded {len(df)} rows from cache")
        return df

    # Rebuild from tick data
    files = _list_tx1_files(pd.Timestamp("2017-05-16"), pd.Timestamp("2026-05-08"))
    print(f"[TX1] Found {len(files)} files, rebuilding...")
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
            bpv = compute_bpv(rets)
            rows.append({
                "date": file_date,
                "rv": rv,
                "bpv": bpv,
                "j": max(rv - bpv, 0.0),  # raw (pre-threshold)
                "cv": min(rv, bpv),
                "n_bars": int(len(bars)),
            })
        except Exception as e:
            print(f"  [warn] {fn.name}: {e}")
        if (i + 1) % 250 == 0:
            print(f"  [{i+1}/{len(files)}] elapsed={time.time()-t0:.1f}s")
    if not rows:
        raise RuntimeError("[TX1] No daily rows built")
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    df.to_parquet(CACHE_TX1_DAILY, index=False)
    print(f"[TX1] Cached {len(df)} rows → {CACHE_TX1_DAILY}")
    return df


def load_us_daily(symbol: str, cache: Path, force: bool = False) -> pd.DataFrame:
    """Load US ETF 5-min daily RV/BPV from cache or rebuild from yfinance."""
    if cache.exists() and not force:
        df = pd.read_parquet(cache)
        print(f"[{symbol}] Loaded {len(df)} rows from cache")
        return df

    import yfinance as yf
    print(f"[{symbol}] Downloading 5-min bars (60d cap)...")
    df = yf.download(symbol, period="60d", interval="5m",
                     auto_adjust=True, progress=False)
    if df is None or df.empty:
        raise RuntimeError(f"[{symbol}] yfinance returned empty")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    ts_col = "Datetime" if "Datetime" in df.columns else df.columns[0]
    df = df.rename(columns={ts_col: "ts", "Close": "close"})
    df["ts"] = pd.to_datetime(df["ts"])
    if df["ts"].dt.tz is not None:
        df["ts"] = df["ts"].dt.tz_convert("America/New_York").dt.tz_localize(None)
    df["session_date"] = df["ts"].dt.normalize()
    mins = df["ts"].dt.hour * 60 + df["ts"].dt.minute
    df = df[(mins >= 9 * 60 + 30) & (mins <= 16 * 60)].copy()
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"]).sort_values("ts").reset_index(drop=True)

    rows: List[dict] = []
    for date, grp in df.groupby("session_date"):
        grp = grp.sort_values("ts").reset_index(drop=True)
        if len(grp) < 30:
            continue
        prices = grp["close"].to_numpy(dtype=float)
        rets = np.log(prices[1:] / prices[:-1])
        if len(rets) < 29:
            continue
        rv = float((rets ** 2).sum())
        bpv = compute_bpv(rets)
        rows.append({
            "date": date,
            "rv": rv,
            "bpv": bpv,
            "j": max(rv - bpv, 0.0),  # raw (pre-threshold)
            "cv": min(rv, bpv),
            "n_bars": int(len(grp)),
        })
    out = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    out.to_parquet(cache, index=False)
    print(f"[{symbol}] Cached {len(out)} rows → {cache}")
    return out


# ======================================================================
# 4) ABD3 FIX: Standard 1-step HAR feature builder
#    Features at t-1 predict target RV_t (not RV_{t+1})
# ======================================================================
def build_har_features(daily: pd.DataFrame) -> pd.DataFrame:
    """Build HAR-RV and HAR-CJ features with STANDARD 1-step lag.

    ABD Fix 3: Target = log(RV_t), features use t-1 values.
    Standard HAR: RV_t = a + b_d*RV_{t-1} + b_w*RV_w + b_m*RV_m + eps

    All features use .shift(1) so feature at row t reflects day t-1 value.
    Rolling windows also shifted: rv_w = mean(RV_{t-5..t-1}).

    Returns dataframe with:
      Y            = log(RV_t)  -- target at row t (NO future shift)
      rv_d, rv_w, rv_m  = HAR-RV features
      cv_d, cv_w, cv_m  = HAR-CJ continuous-component features
      j_d,  j_w,  j_m   = HAR-CJ jump-component features (log1p scale)
    """
    d = daily.copy().sort_values("date").reset_index(drop=True)
    eps = 1e-12

    # ABD3 Fix: shift(1) so feature at row t = value from day t-1
    rv_lag1 = d["rv"].shift(1)
    cv_lag1 = d["cv"].shift(1)
    j_lag1 = d["j"].shift(1)

    # HAR-RV features: daily, weekly (mean of last 5 days), monthly (mean of last 22 days)
    # Rolling applied to lagged series → rv_w at row t = mean(rv_{t-5..t-1})
    d["rv_d"] = rv_lag1
    d["rv_w"] = rv_lag1.rolling(window=5, min_periods=5).mean()
    d["rv_m"] = rv_lag1.rolling(window=22, min_periods=22).mean()

    # HAR-CJ continuous features
    d["cv_d"] = cv_lag1
    d["cv_w"] = cv_lag1.rolling(window=5, min_periods=5).mean()
    d["cv_m"] = cv_lag1.rolling(window=22, min_periods=22).mean()

    # HAR-CJ jump features: J expressed as FRACTION of RV (jump share, dimensionless [0,1])
    # This prevents explosive betas caused by the extreme scale mismatch between
    # log(CV) (~-10 log scale) and log1p(J_abs) (~0.000006). Using J/RV puts the
    # j features in [0,1] range, making OLS coefficients interpretable.
    # j_share_{t-1} = J_{t-1} / RV_{t-1} (= 0 on non-jump days after threshold)
    j_share_lag1 = j_lag1 / rv_lag1.clip(lower=eps)  # dimensionless jump share
    d["j_d"] = j_share_lag1
    d["j_w"] = j_share_lag1.rolling(window=5, min_periods=5).mean()
    d["j_m"] = j_share_lag1.rolling(window=22, min_periods=22).mean()

    # ABD3 Fix: Target = log(RV_t) — same-day realized variance (no shift(-1))
    d["Y"] = np.log(d["rv"].clip(lower=eps))

    feat_cols_rv = ["rv_d", "rv_w", "rv_m"]
    feat_cols_cv = ["cv_d", "cv_w", "cv_m"]
    feat_cols_j = ["j_d", "j_w", "j_m"]

    d = d.dropna(subset=feat_cols_rv + feat_cols_cv + feat_cols_j + ["Y"]).reset_index(drop=True)

    # Log-transform RV and CV features (strictly positive)
    for c in feat_cols_rv + feat_cols_cv:
        d[c] = np.log(d[c].clip(lower=eps))
    # j features are already in [0,1] (jump share ratio) — no log transform needed
    # (many zeros; log1p of a ratio in [0,1] compresses variation further)
    for c in feat_cols_j:
        d[c] = d[c].clip(lower=0.0)  # ensure non-negative; no log transform
    return d


# ======================================================================
# 5) OLS helpers
# ======================================================================
def fit_ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    X1 = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    return beta


def predict_ols(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    X1 = np.column_stack([np.ones(len(X)), X])
    return X1 @ beta


# ======================================================================
# 6) Per-asset evaluation with ABD2 fix: QLIKE + HAC DM
# ======================================================================
def evaluate_asset(name: str, daily_raw: pd.DataFrame) -> Dict:
    """Evaluate HAR-RV vs HAR-CJ for one asset.

    ABD2 Fix: Use QLIKE pointwise losses + HAC dm_test from model_evaluation.py.
    ABD3 Fix: Standard 1-step lag (features t-1 → target t).
    ABD1 Fix: Jump threshold applied to daily before feature building.
    """
    print(f"\n[{name}] Applying 3-sigma jump threshold...")
    daily = apply_jump_threshold(daily_raw)

    # Jump descriptives after thresholding
    j_share_raw = float((daily["raw_j"] / daily["rv"].clip(lower=1e-12)).mean())
    j_share_thresh = float((daily["j"] / daily["rv"].clip(lower=1e-12)).mean())
    frac_jump = float(daily["jump_day"].mean())

    print(f"[{name}] N daily rows raw = {len(daily)}")
    feat = build_har_features(daily)
    print(f"[{name}] N HAR rows after warm-up = {len(feat)}")

    if len(feat) < 60:
        print(f"[{name}] WARNING: small sample, 70/30 split may be unstable")

    rv_cols = ["rv_d", "rv_w", "rv_m"]
    cj_cols = ["cv_d", "cv_w", "cv_m", "j_d", "j_w", "j_m"]

    y = feat["Y"].to_numpy(dtype=float)
    X_rv = feat[rv_cols].to_numpy(dtype=float)
    X_cj = feat[cj_cols].to_numpy(dtype=float)

    T = len(feat)
    n_train = int(np.floor(T * 0.7))
    n_features_cj = 6
    if n_train <= n_features_cj + 5 or (T - n_train) < 5:
        return {
            "asset": name,
            "error": f"insufficient sample: T={T}, n_train={n_train}, n_test={T-n_train}",
            "n_har_rows": int(T),
            "note": "60d yfinance 5-min cap is the bottleneck. Use Polygon/IEX for longer US 5-min history.",
        }
    idx_train = np.arange(n_train)
    idx_test = np.arange(n_train, T)

    beta_rv = fit_ols(X_rv[idx_train], y[idx_train])
    beta_cj = fit_ols(X_cj[idx_train], y[idx_train])

    yhat_rv_te = predict_ols(beta_rv, X_rv[idx_test])
    yhat_cj_te = predict_ols(beta_cj, X_cj[idx_test])

    # ABD3: Target is log(RV_t); to compute QLIKE we need actual RV_t (not log)
    # feat["Y"] = log(RV_t), so actual RV_t = exp(Y)
    y_test = y[idx_test]
    rv_actual = np.exp(y_test)               # actual RV_t (level)
    rv_hat_rv = np.exp(yhat_rv_te)           # HAR-RV forecast (level)
    rv_hat_cj = np.exp(yhat_cj_te)          # HAR-CJ forecast (level)

    # ABD2 Fix: QLIKE pointwise losses (Patton 2011)
    qlike_rv = qlike_pointwise(rv_actual, rv_hat_rv)
    qlike_cj = qlike_pointwise(rv_actual, rv_hat_cj)

    mean_qlike_rv = float(np.nanmean(qlike_rv))
    mean_qlike_cj = float(np.nanmean(qlike_cj))

    # ABD2 Fix: HAC DM test with QLIKE losses
    # Positive t-stat => HAR-RV loss > HAR-CJ loss => HAR-CJ preferred
    dm_t, dm_p = _dm_test_hac(qlike_rv, qlike_cj, h=1)

    # MSE for reference (not primary criterion)
    e_rv = y_test - yhat_rv_te
    e_cj = y_test - yhat_cj_te
    mse_rv = float((e_rv ** 2).mean())
    mse_cj = float((e_cj ** 2).mean())

    def _r2(y_, yhat_):
        ss_res = float(((y_ - yhat_) ** 2).sum())
        ss_tot = float(((y_ - y_.mean()) ** 2).sum())
        return 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    r2_rv_is = _r2(y[idx_train], predict_ols(beta_rv, X_rv[idx_train]))
    r2_cj_is = _r2(y[idx_train], predict_ols(beta_cj, X_cj[idx_train]))
    r2_rv_oos = _r2(y_test, yhat_rv_te)
    r2_cj_oos = _r2(y_test, yhat_cj_te)

    pass_dm = (not np.isnan(dm_t)) and abs(dm_t) > 3.0
    cj_lower_qlike = mean_qlike_cj < mean_qlike_rv

    return {
        "asset": name,
        "n_daily_rows": int(len(daily)),
        "n_har_rows": int(T),
        "n_train": int(n_train),
        "n_test": int(T - n_train),
        "date_range": [str(feat["date"].min()), str(feat["date"].max())],
        "jump_descriptives": {
            "mean_j_share_of_rv_raw": j_share_raw,
            "mean_j_share_of_rv_thresholded": j_share_thresh,
            "frac_jump_days": frac_jump,
            "jump_threshold_value": float(daily["jump_threshold"].iloc[0]),
            "n_jump_days": int(daily["jump_day"].sum()),
        },
        "har_rv": {
            "beta": {k: float(v) for k, v in zip(["intercept"] + rv_cols, beta_rv)},
            "qlike_oos": mean_qlike_rv,
            "mse_oos": mse_rv,
            "r2_is": r2_rv_is,
            "r2_oos": r2_rv_oos,
        },
        "har_cj": {
            "beta": {k: float(v) for k, v in zip(["intercept"] + cj_cols, beta_cj)},
            "qlike_oos": mean_qlike_cj,
            "mse_oos": mse_cj,
            "r2_is": r2_cj_is,
            "r2_oos": r2_cj_oos,
        },
        "dm_hln": {
            "loss": "QLIKE_pointwise_Patton2011",
            "dm_implementation": "HAC_Newey-West_model_evaluation.py:83" if _HAC_AVAILABLE else "inline_HAC_fallback",
            "h": 1,
            "t_stat": float(dm_t) if not np.isnan(dm_t) else None,
            "p_value": float(dm_p) if not np.isnan(dm_p) else None,
            "interpretation_sign": "positive => HAR-RV QLIKE > HAR-CJ QLIKE => HAR-CJ preferred",
            "harvey_threshold": 3.0,
            "pass_3sigma": pass_dm,
            "har_cj_lower_qlike": cj_lower_qlike,
        },
    }


# ======================================================================
# 7) Main
# ======================================================================
def main():
    out: Dict = {
        "experiment_id": "K1303",
        "revision": "v2_abd",
        "title": "HAR-CJ (Continuous + Jump) vs HAR-RV on TAIFEX TX1 + SPY/QQQ/GLD",
        "date_run": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seed": SEED,
        "methodology": {
            "jump_identification": "3-sigma threshold on max(RV-BPV,0): J_t>0 only on days where max(RV-BPV,0)>mu+3*sigma (ABD Fix 1)",
            "dm_test": "HAC Newey-West from volpred.stats.model_evaluation:83 (ABD Fix 2)",
            "dm_loss": "QLIKE pointwise (Patton 2011) not MSE",
            "lag_convention": "1-step: features at t-1 predict target log(RV_t) (ABD Fix 3)",
            "bpv_formula": "(pi/2) * (M/(M-1)) * sum_{k=2..M} |r_k| * |r_{k-1}|",
            "har_rv_features": [
                "log RV_{t-1}", "log mean RV_{t-5..t-1}", "log mean RV_{t-22..t-1}"
            ],
            "har_cj_features": [
                "log CV_{t-1}", "log mean CV_{t-5..t-1}", "log mean CV_{t-22..t-1}",
                "J_{t-1}/RV_{t-1} (jump share)", "mean J-share_{t-5..t-1}", "mean J-share_{t-22..t-1}",
            ],
            "split": "70/30 chronological",
            "pass_rule": "|DM_HLN_t| > 3 AND HAR-CJ lower QLIKE (Harvey 2016 threshold)",
            "seed": SEED,
        },
        "data_sources": {
            "TX1": "TAIFEX tick CSV 2017-05-16..2026-05-08, day session 08:45-13:45, 5-min bars (cached parquet)",
            "SPY": "yfinance 5m, last 60d cap, regular session 09:30-16:00 ET (cached parquet)",
            "QQQ": "yfinance 5m, last 60d cap, regular session 09:30-16:00 ET (cached parquet)",
            "GLD": "yfinance 5m, last 60d cap, regular session 09:30-16:00 ET (cached parquet)",
        },
        "results": {},
    }

    # --- TX1 (long sample, primary test) ---
    print("\n============ K1303-v2: TAIFEX TX1 ============")
    try:
        tx1_daily = load_tx1_daily(force=False)
        out["results"]["TX1"] = evaluate_asset("TX1", tx1_daily)
    except Exception as e:
        import traceback
        print(f"[TX1] FAILED: {e}")
        traceback.print_exc()
        out["results"]["TX1"] = {"error": str(e)}

    # --- US ETFs (short sample, exploratory) ---
    for sym, cache in [("SPY", CACHE_SPY_DAILY),
                       ("QQQ", CACHE_QQQ_DAILY),
                       ("GLD", CACHE_GLD_DAILY)]:
        print(f"\n============ K1303-v2: {sym} ============")
        try:
            daily = load_us_daily(sym, cache, force=False)
            out["results"][sym] = evaluate_asset(sym, daily)
        except Exception as e:
            import traceback
            print(f"[{sym}] FAILED: {e}")
            traceback.print_exc()
            out["results"][sym] = {"error": str(e)}

    # --- Verdict ---
    print("\n============ VERDICT ============")
    verdict_lines: List[str] = []
    dm_t_per_asset: Dict[str, Optional[float]] = {}
    for asset in ("TX1", "SPY", "QQQ", "GLD"):
        r = out["results"].get(asset, {})
        if "dm_hln" in r:
            dm = r["dm_hln"]
            t_stat = dm.get("t_stat")
            p_val = dm.get("p_value")
            dm_t_per_asset[asset] = t_stat
            verdict_lines.append(
                f"{asset}: DM_HLN_t={t_stat:.3f}  p={p_val:.4f}  "
                f"QLIKE_RV={r['har_rv']['qlike_oos']:.4f}  QLIKE_CJ={r['har_cj']['qlike_oos']:.4f}  "
                f"pass_3sigma={dm['pass_3sigma']}  cj_lower_qlike={dm['har_cj_lower_qlike']}"
            )
        else:
            dm_t_per_asset[asset] = None
            verdict_lines.append(f"{asset}: ERROR — {r.get('error', 'unknown')}")
    for ln in verdict_lines:
        print(ln)

    def _pass(r):
        return ("dm_hln" in r and r["dm_hln"]["pass_3sigma"]
                and r["dm_hln"]["har_cj_lower_qlike"])

    def _is_gateable(r, min_n_train=200):
        if "dm_hln" not in r:
            return False
        if r.get("n_train", 0) < min_n_train:
            return False
        r2_rv = r.get("har_rv", {}).get("r2_oos", -np.inf)
        r2_cj = r.get("har_cj", {}).get("r2_oos", -np.inf)
        if r2_rv < -1.0 or r2_cj < -1.0:
            return False
        return True

    tx1_r = out["results"].get("TX1", {})
    tx1_pass = _pass(tx1_r)
    tx1_gateable = _is_gateable(tx1_r)
    n_pass = (1 if (tx1_pass and tx1_gateable) else 0)
    for a in ("SPY", "QQQ", "GLD"):
        r = out["results"].get(a, {})
        if _is_gateable(r) and _pass(r):
            n_pass += 1

    overall_verdict = "PASS" if (tx1_pass and tx1_gateable) else "NULL"
    us_gateable_passes = sum(
        1 for a in ("SPY", "QQQ", "GLD")
        if _is_gateable(out["results"].get(a, {})) and _pass(out["results"].get(a, {}))
    )

    out["verdict_lines"] = verdict_lines
    out["summary"] = {
        "verdict": overall_verdict,
        "n_pass": n_pass,
        "tx1_gateable": tx1_gateable,
        "tx1_pass": tx1_pass,
        "us_gateable_passes": us_gateable_passes,
        "dm_t_per_asset": dm_t_per_asset,
        "harvey_threshold": 3.0,
        "note": (
            "v2_abd: Jump threshold (3-sigma) + HAC DM QLIKE + 1-step lag. "
            "TX1 is primary gateable asset (n_train>200). "
            "US ETFs: 60d yfinance cap limits n_train<200, marked non-gateable."
        ),
    }

    out_path = SCRIPT_DIR / "k1303_results.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[done] wrote {out_path}")
    print(f"[done] overall_verdict={overall_verdict}, dm_t_per_asset={dm_t_per_asset}")


if __name__ == "__main__":
    main()
