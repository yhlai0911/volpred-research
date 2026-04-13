"""
K1124 — TAIFEX TX Order Flow Imbalance for short-horizon vol prediction

Motivation:
  Today 3 dead-end directions (firm-selection / copula / alt-data) — need a
  true fresh direction. OFI is a microstructure signal orthogonal to
  K1100g day/night session mechanics. Cont, Kukanov, Stoikov (2014) showed
  OFI has short-horizon RETURN prediction power. This experiment tests the
  UNSTUDIED question: does OFI magnitude predict RV (vol) at 5-min horizon
  on TAIFEX TX?

Design:
  - Data: TAIFEX TX futures 2017-2021, day session 08:45-13:45 only
    (night session has structural discontinuity — K1100g_d1 lesson)
  - Active contract per day (K849 rule: max total volume)
  - 5-min bars (60 bars per day)
  - Target: RV_{t+1} = sum of squared tick log-returns in bar t+1
  - Tick rule (Lee & Ready 1991 pure-tick variant):
      price up -> buy-initiated (+1)
      price down -> sell-initiated (-1)
      zero tick -> carry forward previous non-zero direction
      First tick: default +1
  - OFI per bar: (sum of signed volume) / (total volume)

Models (all use bar-level logret^2 as input):
  M1: GARCH(1,1) on 5-min logret (standard baseline)
  M2: HAR-RV(1, 12, 60) — daily(1 bar) + ~1h(12 bars) + ~5h(60 bars)
      (Corsi 2009 adapted to 5-min RV bars)
  M3: HAR-RV + |OFI_t| as exog (H1 core test)
  M4: HAR-RV + OFI_t signed (H2 asymmetry)
  M5: HAR-RV + OFI persistence (lag-5 cumulative |OFI|)

Evaluation:
  - IS: 2017-2019 (3 years ~ 180 days/year minus holidays ~ 540 days)
  - OOS: 2020-2021 (2 years ~ 480 days)
  - Triple threshold (K1100g_d2 lesson):
      (1) DM-HLN |t| > 2 vs M2 (primary baseline)
      (2) QLIKE improvement > 5%
      (3) Sub-period stable (split OOS in half, both show improvement)

  Cross-session is handled by NOT predicting the first bar of each day
  (no previous bar in same session).

Author: Claude (worktree agent-k1124)
Date: 2026-04-13
Seed: 42
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")

RNG = np.random.default_rng(42)
np.random.seed(42)

SCRIPT_DIR = Path(__file__).resolve().parent
TAIFEX_DIR = Path("/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python")

DAY_START = 84500      # 08:45 in HHMMSS
DAY_END = 134459       # 13:44:59 (Codex audit: avoid bar=60 by excluding 13:45 exact)
# 08:45..13:44:59 = 60 bars of 5-min each (bars 0..59)

STUDY_START = pd.Timestamp("2017-01-01")
STUDY_END = pd.Timestamp("2021-12-31")

IS_END = pd.Timestamp("2019-12-31")
OOS_START = pd.Timestamp("2020-01-01")
OOS_MID = pd.Timestamp("2020-12-31")  # split OOS into 2 halves


# ============================================================
# Loader
# ============================================================
def _parse_date_from_filename(fname: str):
    base = fname.replace("Daily_", "")
    try:
        ymd = base.split("TX")[0]
        parts = ymd.split("_")
        if len(parts) != 3:
            return None
        return pd.Timestamp(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return None


def _read_taifex_file(path: Path):
    if not path.exists() or path.stat().st_size < 100:
        return None
    for enc in ("big5", "cp950", "utf-8"):
        try:
            df = pd.read_csv(path, encoding=enc, dtype=str, low_memory=False)
            break
        except Exception:
            df = None
    if df is None or len(df) < 10:
        return None
    contract = df.iloc[:, 2].astype(str)
    monthly_mask = contract.str.match(r"^\d{6}$")
    df = df.loc[monthly_mask].copy()
    df["contract_month"] = pd.to_numeric(df.iloc[:, 2], errors="coerce").astype("Int64")
    df["time_int"] = pd.to_numeric(df.iloc[:, 3], errors="coerce").astype("Int64")
    df["price"] = pd.to_numeric(df.iloc[:, 4], errors="coerce")
    df["volume"] = pd.to_numeric(df.iloc[:, 5], errors="coerce")
    df = df.dropna(subset=["contract_month", "time_int", "price", "volume"])
    if len(df) < 10:
        return None
    return df[["contract_month", "time_int", "price", "volume"]]


def _pick_active_contract(df):
    """Fallback (intraday): choose max total-volume contract from current day.
    Used only for very first day when no prior info is available."""
    return int(df.groupby("contract_month")["volume"].sum().idxmax())


def _pick_active_contract_rolling(prev_df, curr_df):
    """Codex audit fix: use T-1 volume to choose which contract to use on day T.
    This avoids selection lookahead (otherwise we pick afternoon's winner for
    morning bars). If prev_df not available, fall back to current day.

    Also handles roll days: if the T-1 winner is no longer traded on day T
    (because it expired — e.g. after 3rd Wed settlement), we fall back to the
    next-most-liquid contract from the INTERSECTION of T-1 and T."""
    if prev_df is None:
        return _pick_active_contract(curr_df)
    prev_totals = prev_df.groupby("contract_month")["volume"].sum()
    curr_contracts = set(curr_df["contract_month"].unique())
    # Find T-1 winner that still exists on T
    for contract, _ in prev_totals.sort_values(ascending=False).items():
        if int(contract) in curr_contracts:
            return int(contract)
    # Should not happen — fall back
    return _pick_active_contract(curr_df)


def _is_third_wednesday(date):
    if date.dayofweek != 2:
        return False
    return 15 <= date.day <= 21


def tick_rule_direction(prices: np.ndarray) -> np.ndarray:
    n = len(prices)
    dirs = np.zeros(n, dtype=np.int8)
    prev_dir = 1
    prev_price = prices[0]
    dirs[0] = prev_dir
    for i in range(1, n):
        if prices[i] > prev_price:
            prev_dir = 1
        elif prices[i] < prev_price:
            prev_dir = -1
        dirs[i] = prev_dir
        prev_price = prices[i]
    return dirs


def compute_bars_for_day(day_df: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
    """Compute 5-min bar series for one day, including OFI."""
    day_df = day_df.sort_values("time_int").reset_index(drop=True)
    t = day_df["time_int"].values
    p = day_df["price"].values.astype(float)
    v = day_df["volume"].values.astype(float)

    h = t // 10000
    m = (t % 10000) // 100
    minutes_of_day = h * 60 + m
    base_min = 8 * 60 + 45
    bar = (minutes_of_day - base_min) // 5

    dirs = tick_rule_direction(p)
    signed_vol = dirs.astype(float) * v

    df = pd.DataFrame({
        "bar": bar,
        "price": p,
        "volume": v,
        "signed_vol": signed_vol,
    })

    bars = []
    for b_id, g in df.groupby("bar"):
        if len(g) < 2:
            continue
        prices_b = g["price"].values
        log_ret_ticks = np.diff(np.log(prices_b))
        rv = float(np.sum(log_ret_ticks ** 2))
        total_vol = float(g["volume"].sum())
        signed_sum = float(g["signed_vol"].sum())
        ofi = signed_sum / total_vol if total_vol > 0 else 0.0
        bars.append({
            "date": date,
            "bar": int(b_id),
            "price_open": float(prices_b[0]),
            "price_close": float(prices_b[-1]),
            "log_ret": float(np.log(prices_b[-1] / prices_b[0])),
            "volume": total_vol,
            "signed_vol": signed_sum,
            "ofi": ofi,
            "rv": rv,
            "n_ticks": int(len(g)),
            "is_settlement": bool(_is_third_wednesday(date)),
        })
    return pd.DataFrame(bars)


def load_all_bars(start: pd.Timestamp, end: pd.Timestamp, cache: bool = True) -> pd.DataFrame:
    """Load 5-min bar series for all trading days in [start, end]."""
    cache_path = SCRIPT_DIR / f"_cache_bars_{start.date()}_{end.date()}.parquet"
    if cache and cache_path.exists():
        print(f"[CACHE] Loading {cache_path.name}")
        df = pd.read_parquet(cache_path)
        df["date"] = pd.to_datetime(df["date"])
        return df

    print(f"[TAIFEX] Scanning {TAIFEX_DIR} for {start.date()}..{end.date()}")
    all_files = sorted(TAIFEX_DIR.glob("Daily_*TX.csv"))
    # Widen start to load prev-day reference for rolling contract selection
    frames = []
    t0 = time.time()
    n_done = 0
    prev_df = None  # T-1 full day ticks, used to pick today's active contract
    for f in all_files:
        date = _parse_date_from_filename(f.name)
        if date is None or date < (start - pd.Timedelta(days=4)) or date > end:
            continue
        df = _read_taifex_file(f)
        if df is None:
            prev_df = None
            continue
        # Codex fix: use T-1 volume to pick today's contract (no lookahead)
        active = _pick_active_contract_rolling(prev_df, df)
        prev_df = df  # save for next iteration BEFORE filtering
        if date < start:
            continue  # warmup only
        df_active = df[df["contract_month"] == active].copy()
        day_mask = (df_active["time_int"] >= DAY_START) & (df_active["time_int"] <= DAY_END)
        day_df = df_active.loc[day_mask]
        if len(day_df) < 50:
            continue
        bars = compute_bars_for_day(day_df, date)
        if len(bars) < 30:
            continue
        # Track which contract was used for diagnostics
        bars["active_contract"] = active
        frames.append(bars)
        n_done += 1
        if n_done % 100 == 0:
            print(f"  processed {n_done} days, elapsed {time.time()-t0:.1f}s")

    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values(["date", "bar"]).reset_index(drop=True)
    print(f"[TAIFEX] Loaded {n_done} days, {len(out)} bars, {time.time()-t0:.1f}s")
    if cache:
        out.to_parquet(cache_path, index=False)
        print(f"[CACHE] Saved to {cache_path.name}")
    return out


# ============================================================
# Models
# ============================================================
def har_rv_features(rv_series: np.ndarray, lags=(1, 12, 60)):
    """Return X matrix of HAR features: RV_{t-1}, mean RV_{t-1..t-lag2}, mean RV_{t-1..t-lag3}.
    For bars where t < max(lags), row is NaN."""
    n = len(rv_series)
    X = np.full((n, len(lags)), np.nan)
    max_lag = max(lags)
    for t in range(max_lag, n):
        X[t, 0] = rv_series[t - lags[0]]
        X[t, 1] = np.mean(rv_series[t - lags[1]:t])
        X[t, 2] = np.mean(rv_series[t - lags[2]:t])
    return X


def make_model_data(df_bars: pd.DataFrame):
    """Build model-ready DataFrame with HAR features + OFI features + target RV_{t+1}.
    Critical: HAR features use only WITHIN-DAY history for that bar. Since we
    have 60 bars/day, a lag-60 feature needs to span across day boundary.
    We use a GLOBAL time-ordered series and mask out rows where the required
    history spans across days (first 60 bars of each day drop lag60 feature;
    strictly we drop rows where any of the 60 prior bars are NOT in the same day).

    Solution: for each row t, compute (a) whether prior max_lag bars are all in
    the same day as t; if yes, use HAR features; else skip.
    """
    df = df_bars.copy().reset_index(drop=True)
    n = len(df)
    rv = df["rv"].values
    lret = df["log_ret"].values
    ofi = df["ofi"].values
    dates = df["date"].values

    # Target: rv of next bar (within same day)
    df["rv_next"] = np.nan
    df["lret_next"] = np.nan
    for t in range(n - 1):
        if df.loc[t, "date"] == df.loc[t + 1, "date"]:
            df.loc[t, "rv_next"] = rv[t + 1]
            df.loc[t, "lret_next"] = lret[t + 1]

    # Within-day index (0..59 typically)
    df["bar_idx"] = df.groupby(df["date"].astype(str)).cumcount()

    # HAR features: use within-day windows where possible
    # lag1: prev bar in same day (bar_idx >= 1)
    # lag12: avg of 12 prev bars (bar_idx >= 12)
    # lag60: avg of 60 prev bars (bar_idx >= 60) — but typical day has 60 bars
    #        so lag60 only available for LAST bar of day (bar_idx=59 uses bar 0..58)
    # To keep enough sample, use lags (1, 6, 12) — daily (1 bar), half-hour (6), 1-hour (12)
    # These are within-day horizons analogous to HAR daily/weekly/monthly scaled down.

    # Recompute HAR with (1, 6, 12) and require bar_idx >= 12
    lag1 = np.full(n, np.nan)
    lag6 = np.full(n, np.nan)
    lag12 = np.full(n, np.nan)
    day_grp = df["date"].astype(str).values
    for t in range(n):
        if df.loc[t, "bar_idx"] >= 12:
            # verify previous 12 bars are same day
            if day_grp[t - 12] == day_grp[t]:
                lag1[t] = rv[t - 1]
                lag6[t] = float(np.mean(rv[t - 6:t]))
                lag12[t] = float(np.mean(rv[t - 12:t]))

    df["har_lag1"] = lag1
    df["har_lag6"] = lag6
    df["har_lag12"] = lag12

    # OFI features (current bar t, predict t+1) — strict: no lookahead
    df["abs_ofi"] = np.abs(ofi)
    df["ofi_signed"] = ofi
    # OFI persistence: lag-5 cumulative |OFI|
    ofi_pers = np.full(n, np.nan)
    for t in range(n):
        if df.loc[t, "bar_idx"] >= 5:
            if day_grp[t - 5] == day_grp[t]:
                ofi_pers[t] = float(np.sum(np.abs(ofi[t - 4:t + 1])))  # t-4..t inclusive
    df["ofi_pers"] = ofi_pers
    # Robustness (Codex Bug 3): use strictly-past OFI (lag-1) to rule out
    # current-bar info-set asymmetry as a cause of beta(|OFI|)<0.
    abs_ofi_lag1 = np.full(n, np.nan)
    ofi_signed_lag1 = np.full(n, np.nan)
    for t in range(n):
        if df.loc[t, "bar_idx"] >= 1 and day_grp[t - 1] == day_grp[t]:
            abs_ofi_lag1[t] = np.abs(ofi[t - 1])
            ofi_signed_lag1[t] = ofi[t - 1]
    df["abs_ofi_lag1"] = abs_ofi_lag1
    df["ofi_signed_lag1"] = ofi_signed_lag1

    # Keep only rows with all features + target
    valid = df.dropna(subset=["rv_next", "har_lag1", "har_lag6", "har_lag12",
                                "ofi_pers", "abs_ofi_lag1", "ofi_signed_lag1"]).copy()
    return valid


# ============================================================
# Estimation: OLS with Newey-West later for DM
# ============================================================
def fit_ols(X: np.ndarray, y: np.ndarray):
    """OLS with intercept, returns beta vector (including intercept)."""
    X1 = np.hstack([np.ones((len(X), 1)), X])
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    return beta


def predict_ols(X: np.ndarray, beta: np.ndarray):
    X1 = np.hstack([np.ones((len(X), 1)), X])
    return X1 @ beta


def garch_11_rolling_5min(logrets: np.ndarray):
    """Simple rolling GARCH(1,1) one-step-ahead variance forecast.
    We estimate once on IS sample, then recurse h_{t+1} = omega + alpha*r_t^2 + beta*h_t.
    For speed we use MoM-ish starting values then refine via scipy.
    Returns next-step forecasts aligned with logrets (forecast at t is for t+1).
    """
    r = logrets
    r2 = r ** 2
    mean_r2 = np.mean(r2)
    # Use standard starting values
    omega0 = 0.05 * mean_r2
    alpha0 = 0.1
    beta0 = 0.85

    def nll(params):
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 0.999:
            return 1e10
        n = len(r)
        h = np.zeros(n)
        h[0] = mean_r2
        ll = 0.0
        for t in range(1, n):
            h[t] = omega + alpha * r2[t - 1] + beta * h[t - 1]
            if h[t] <= 0:
                return 1e10
            ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + r2[t] / h[t])
        return -ll

    from scipy.optimize import minimize
    res = minimize(nll, [omega0, alpha0, beta0], method="Nelder-Mead",
                   options={"xatol": 1e-6, "maxiter": 500})
    omega, alpha, beta = res.x

    # Now do one-step forecasts over ENTIRE series
    n = len(r)
    h = np.zeros(n)
    h[0] = mean_r2
    forecasts = np.zeros(n)  # forecasts[t] = h_{t+1} prediction made at t
    for t in range(n):
        if t == 0:
            h[t] = mean_r2
        else:
            h[t] = omega + alpha * r2[t - 1] + beta * h[t - 1]
        forecasts[t] = omega + alpha * r2[t] + beta * h[t]  # h_{t+1}
    return forecasts, (omega, alpha, beta)


# ============================================================
# DM-HLN test
# ============================================================
def dm_hln(e1: np.ndarray, e2: np.ndarray, h: int = 1):
    """Diebold-Mariano with Harvey-Leybourne-Newbold small-sample adjustment.
    d_t = loss1 - loss2. Negative -> model 1 better.
    Returns (dm_stat, dm_pvalue). Positive DM => model 2 better than model 1.
    Here we pass e1=loss_baseline, e2=loss_candidate so positive DM => baseline
    bigger loss => candidate wins.
    """
    d = e1 - e2
    n = len(d)
    if n < 10:
        return 0.0, 1.0
    mean_d = np.mean(d)
    # Newey-West variance with lag = h-1 for h-step-ahead forecasts; h=1 -> 0 lag
    gamma0 = np.var(d, ddof=1)
    var_d = gamma0 / n
    if var_d <= 0:
        return 0.0, 1.0
    dm = mean_d / np.sqrt(var_d)
    # HLN correction
    k = ((n + 1 - 2 * h + h * (h - 1) / n) / n) ** 0.5
    dm_hln_stat = dm * k
    df = n - 1
    pval = 2 * (1 - sp_stats.t.cdf(abs(dm_hln_stat), df=df))
    return float(dm_hln_stat), float(pval)


def qlike_loss(y_true: np.ndarray, y_pred: np.ndarray):
    """Patton 2011 QLIKE: robust to vol proxy noise.
    Both y_true and y_pred must be positive (variance-like)."""
    y_pred = np.clip(y_pred, 1e-12, None)
    y_true = np.clip(y_true, 1e-12, None)
    return y_true / y_pred - np.log(y_true / y_pred) - 1


# ============================================================
# Main
# ============================================================
def main():
    print("=" * 60)
    print("K1124 — TAIFEX OFI for short-horizon vol prediction")
    print("=" * 60)

    # Step 1: load bars
    bars = load_all_bars(STUDY_START, STUDY_END, cache=True)
    print(f"Total bars: {len(bars)}")
    print(f"Unique days: {bars['date'].nunique()}")
    print(f"Period: {bars['date'].min()} .. {bars['date'].max()}")

    # Step 2: build model data
    print("\n[Step 2] Building HAR + OFI features")
    md = make_model_data(bars)
    print(f"After feature construction: {len(md)} rows")
    print(f"Mean RV: {md['rv'].mean():.2e}, std: {md['rv'].std():.2e}")
    print(f"Mean |OFI|: {md['abs_ofi'].mean():.4f}")
    print(f"Mean OFI: {md['ofi_signed'].mean():.4f}")

    # Step 3: train/test split
    is_mask = md["date"] <= IS_END
    oos_mask = md["date"] >= OOS_START
    md_is = md.loc[is_mask].copy()
    md_oos = md.loc[oos_mask].copy()
    print(f"\n[Step 3] Split: IS={len(md_is)} ({md_is['date'].min().date()}..{md_is['date'].max().date()})")
    print(f"              OOS={len(md_oos)} ({md_oos['date'].min().date()}..{md_oos['date'].max().date()})")

    y_is = md_is["rv_next"].values
    y_oos = md_oos["rv_next"].values

    # Model definitions
    results = {}

    # M1: GARCH(1,1) on 5-min logret. Fit on IS, recurse through OOS using
    # the recursion but with IS-estimated params (static parameters).
    print("\n[M1] GARCH(1,1)")
    all_lret = md["lret_next"].shift(1).fillna(0).values  # logret at time t (the return that realized in bar t)
    # Actually we want logret_t which corresponds to rv_t -- use md["log_ret"]
    lret_series = md["log_ret"].values  # contemporaneous bar return
    is_lret = md_is["log_ret"].values
    # Forecast h_{t+1}; align: forecast[t] is for t+1; we want prediction of rv_{t+1}
    # So GARCH forecasts from entire sequence of lrets and we take forecasts aligned
    # to the position of each row in md (sorted).
    full_lret = md["log_ret"].values
    garch_forecasts, garch_params = garch_11_rolling_5min(is_lret)
    # Use IS params for full-series recursion:
    omega, alpha, beta = garch_params
    print(f"  omega={omega:.2e}, alpha={alpha:.4f}, beta={beta:.4f}, persistence={alpha+beta:.4f}")

    # Full-series GARCH forecasts (using IS params)
    r2_full = full_lret ** 2
    n_full = len(full_lret)
    h_full = np.zeros(n_full)
    h_full[0] = np.mean(is_lret ** 2)
    garch_f = np.zeros(n_full)
    for t in range(n_full):
        if t == 0:
            pass
        else:
            h_full[t] = omega + alpha * r2_full[t - 1] + beta * h_full[t - 1]
        garch_f[t] = omega + alpha * r2_full[t] + beta * h_full[t]  # h_{t+1}

    # Cannot easily align GARCH forecasts across feature-constructed data because
    # md has dropped rows. Use IS/OOS prediction from GARCH based on position:
    garch_pred = garch_f  # aligned to md rows (we didn't drop anything here, lret vector from md)

    garch_is_pred = garch_pred[is_mask.values[:len(garch_pred)] if False else np.arange(len(md_is))]
    # Cleaner: just predict on md rows directly using md["log_ret"] series with IS params
    r2 = md["log_ret"].values ** 2
    h = np.zeros(len(md))
    h[0] = np.mean(is_lret ** 2)
    pred = np.zeros(len(md))
    for t in range(len(md)):
        if t > 0:
            h[t] = omega + alpha * r2[t - 1] + beta * h[t - 1]
        pred[t] = omega + alpha * r2[t] + beta * h[t]
    garch_is_pred = pred[:len(md_is)]
    garch_oos_pred = pred[-len(md_oos):]

    q_is = qlike_loss(y_is, garch_is_pred)
    q_oos = qlike_loss(y_oos, garch_oos_pred)
    results["M1_GARCH11"] = {
        "params": {"omega": float(omega), "alpha": float(alpha), "beta": float(beta)},
        "IS_QLIKE": float(np.mean(q_is)),
        "OOS_QLIKE": float(np.mean(q_oos)),
    }
    print(f"  IS QLIKE={np.mean(q_is):.4f}, OOS QLIKE={np.mean(q_oos):.4f}")

    # M2-M5: OLS on HAR ± OFI features
    def fit_and_evaluate(feature_cols, name):
        X_is = md_is[feature_cols].values
        y_is_local = md_is["rv_next"].values
        X_oos = md_oos[feature_cols].values
        y_oos_local = md_oos["rv_next"].values
        beta_hat = fit_ols(X_is, y_is_local)
        pred_is = predict_ols(X_is, beta_hat)
        pred_oos = predict_ols(X_oos, beta_hat)
        # clip negative predictions (variance must be positive)
        pred_is = np.clip(pred_is, 1e-12, None)
        pred_oos = np.clip(pred_oos, 1e-12, None)
        q_is_local = qlike_loss(y_is_local, pred_is)
        q_oos_local = qlike_loss(y_oos_local, pred_oos)
        return {
            "features": feature_cols,
            "beta": beta_hat.tolist(),
            "IS_QLIKE": float(np.mean(q_is_local)),
            "OOS_QLIKE": float(np.mean(q_oos_local)),
            "pred_is": pred_is,
            "pred_oos": pred_oos,
            "q_is": q_is_local,
            "q_oos": q_oos_local,
        }

    print("\n[M2] HAR-RV(1, 6, 12)")
    m2 = fit_and_evaluate(["har_lag1", "har_lag6", "har_lag12"], "M2_HAR")
    results["M2_HAR"] = {"IS_QLIKE": m2["IS_QLIKE"], "OOS_QLIKE": m2["OOS_QLIKE"],
                         "beta": m2["beta"]}
    print(f"  IS QLIKE={m2['IS_QLIKE']:.4f}, OOS QLIKE={m2['OOS_QLIKE']:.4f}")

    print("\n[M3] HAR + |OFI|")
    m3 = fit_and_evaluate(["har_lag1", "har_lag6", "har_lag12", "abs_ofi"], "M3_HAR_absOFI")
    results["M3_HAR_absOFI"] = {"IS_QLIKE": m3["IS_QLIKE"], "OOS_QLIKE": m3["OOS_QLIKE"],
                                "beta": m3["beta"]}
    print(f"  IS QLIKE={m3['IS_QLIKE']:.4f}, OOS QLIKE={m3['OOS_QLIKE']:.4f}")
    print(f"  beta(|OFI|) = {m3['beta'][-1]:.2e}")

    print("\n[M4] HAR + OFI signed")
    m4 = fit_and_evaluate(["har_lag1", "har_lag6", "har_lag12", "ofi_signed"], "M4_HAR_signedOFI")
    results["M4_HAR_signedOFI"] = {"IS_QLIKE": m4["IS_QLIKE"], "OOS_QLIKE": m4["OOS_QLIKE"],
                                    "beta": m4["beta"]}
    print(f"  IS QLIKE={m4['IS_QLIKE']:.4f}, OOS QLIKE={m4['OOS_QLIKE']:.4f}")
    print(f"  beta(OFI) = {m4['beta'][-1]:.2e}")

    print("\n[M5] HAR + OFI persistence (cumulative |OFI| over last 5 bars)")
    m5 = fit_and_evaluate(["har_lag1", "har_lag6", "har_lag12", "ofi_pers"], "M5_HAR_OFIpers")
    results["M5_HAR_OFIpers"] = {"IS_QLIKE": m5["IS_QLIKE"], "OOS_QLIKE": m5["OOS_QLIKE"],
                                  "beta": m5["beta"]}
    print(f"  IS QLIKE={m5['IS_QLIKE']:.4f}, OOS QLIKE={m5['OOS_QLIKE']:.4f}")
    print(f"  beta(OFI_pers) = {m5['beta'][-1]:.2e}")

    print("\n[M6] HAR + |OFI_{t-1}| (strict lag-1 robustness; rules out current-bar info leak)")
    m6 = fit_and_evaluate(["har_lag1", "har_lag6", "har_lag12", "abs_ofi_lag1"], "M6_HAR_absOFIlag1")
    results["M6_HAR_absOFIlag1"] = {"IS_QLIKE": m6["IS_QLIKE"], "OOS_QLIKE": m6["OOS_QLIKE"],
                                     "beta": m6["beta"]}
    print(f"  IS QLIKE={m6['IS_QLIKE']:.4f}, OOS QLIKE={m6['OOS_QLIKE']:.4f}")
    print(f"  beta(|OFI_{{t-1}}|) = {m6['beta'][-1]:.2e}")

    print("\n[M7] HAR + OFI_{t-1} signed (strict lag-1 robustness)")
    m7 = fit_and_evaluate(["har_lag1", "har_lag6", "har_lag12", "ofi_signed_lag1"], "M7_HAR_signedOFIlag1")
    results["M7_HAR_signedOFIlag1"] = {"IS_QLIKE": m7["IS_QLIKE"], "OOS_QLIKE": m7["OOS_QLIKE"],
                                        "beta": m7["beta"]}
    print(f"  IS QLIKE={m7['IS_QLIKE']:.4f}, OOS QLIKE={m7['OOS_QLIKE']:.4f}")
    print(f"  beta(OFI_{{t-1}}) = {m7['beta'][-1]:.2e}")

    # Step 4: DM tests vs M2 baseline
    print("\n[Step 4] DM-HLN tests (vs M2 HAR baseline, OOS)")
    dm_results = {}
    for name, m in [("M3", m3), ("M4", m4), ("M5", m5), ("M6", m6), ("M7", m7)]:
        dm_stat, dm_pval = dm_hln(m2["q_oos"], m["q_oos"], h=1)
        dm_results[name] = {"dm_stat": dm_stat, "dm_pvalue": dm_pval}
        qlike_impr = 100 * (m2["OOS_QLIKE"] - m["OOS_QLIKE"]) / m2["OOS_QLIKE"]
        print(f"  {name} vs M2: DM={dm_stat:.3f} (p={dm_pval:.4f}), QLIKE impr={qlike_impr:+.2f}%")

    # DM vs M1 GARCH for reference
    print("\n  Reference: vs M1 GARCH")
    q_m1_oos = qlike_loss(y_oos, garch_oos_pred)
    for name, m in [("M2", m2), ("M3", m3), ("M4", m4), ("M5", m5), ("M6", m6), ("M7", m7)]:
        dm_stat, dm_pval = dm_hln(q_m1_oos, m["q_oos"], h=1)
        qlike_impr = 100 * (np.mean(q_m1_oos) - m["OOS_QLIKE"]) / np.mean(q_m1_oos)
        print(f"  {name} vs M1: DM={dm_stat:.3f} (p={dm_pval:.4f}), QLIKE impr={qlike_impr:+.2f}%")

    # Step 5: Sub-period stability (split OOS in half)
    print("\n[Step 5] OOS sub-period stability")
    oos_dates = md_oos["date"].values
    mid_date = pd.Timestamp("2021-01-01")
    oos1_mask = md_oos["date"] < mid_date
    oos2_mask = md_oos["date"] >= mid_date
    subperiod = {}
    for name, m in [("M2", m2), ("M3", m3), ("M4", m4), ("M5", m5), ("M6", m6), ("M7", m7)]:
        q_h1 = m["q_oos"][oos1_mask.values]
        q_h2 = m["q_oos"][oos2_mask.values]
        subperiod[name] = {"OOS_H1_QLIKE": float(np.mean(q_h1)),
                            "OOS_H2_QLIKE": float(np.mean(q_h2))}
    print(f"  H1 (2020): " + " | ".join(f"{k}={v['OOS_H1_QLIKE']:.4f}" for k, v in subperiod.items()))
    print(f"  H2 (2021): " + " | ".join(f"{k}={v['OOS_H2_QLIKE']:.4f}" for k, v in subperiod.items()))

    # Step 6: Settlement day effect (H3)
    print("\n[Step 6] Settlement day OFI effect (H3)")
    sett_mask = md_oos["is_settlement"].values
    n_sett = int(np.sum(sett_mask))
    n_non = int(np.sum(~sett_mask))
    if n_sett >= 20 and n_non >= 100:
        abs_ofi_sett = md_oos.loc[sett_mask, "abs_ofi"].mean()
        abs_ofi_non = md_oos.loc[~sett_mask, "abs_ofi"].mean()
        rv_sett = md_oos.loc[sett_mask, "rv_next"].mean()
        rv_non = md_oos.loc[~sett_mask, "rv_next"].mean()
        print(f"  settlement bars={n_sett}, non-settlement bars={n_non}")
        print(f"  |OFI| mean: settlement={abs_ofi_sett:.4f}, non={abs_ofi_non:.4f}")
        print(f"  RV mean: settlement={rv_sett:.2e}, non={rv_non:.2e} (ratio={rv_sett/rv_non:.2f}x)")
        # t-test on |OFI| difference
        t_stat, p_val = sp_stats.ttest_ind(
            md_oos.loc[sett_mask, "abs_ofi"].values,
            md_oos.loc[~sett_mask, "abs_ofi"].values,
            equal_var=False,
        )
        print(f"  Welch t-test on |OFI|: t={t_stat:.3f}, p={p_val:.4f}")
        settlement = {
            "n_settlement_bars": n_sett,
            "n_non_bars": n_non,
            "abs_ofi_settlement": float(abs_ofi_sett),
            "abs_ofi_non": float(abs_ofi_non),
            "rv_settlement": float(rv_sett),
            "rv_non": float(rv_non),
            "rv_ratio": float(rv_sett / rv_non),
            "t_stat_absofi": float(t_stat),
            "t_pvalue_absofi": float(p_val),
        }
    else:
        settlement = {"note": "insufficient settlement-bar sample"}

    # Step 7: Simple diagnostics
    print("\n[Step 7] OFI distribution + auto-correlation")
    ofi_vals = md["ofi_signed"].values
    abs_ofi_vals = md["abs_ofi"].values
    ofi_dist = {
        "ofi_mean": float(np.mean(ofi_vals)),
        "ofi_std": float(np.std(ofi_vals)),
        "ofi_skew": float(sp_stats.skew(ofi_vals)),
        "ofi_kurt": float(sp_stats.kurtosis(ofi_vals)),
        "absofi_mean": float(np.mean(abs_ofi_vals)),
        "absofi_std": float(np.std(abs_ofi_vals)),
    }
    # ACF of |OFI|
    absofi_arr = md_is["abs_ofi"].values
    acf_1 = np.corrcoef(absofi_arr[:-1], absofi_arr[1:])[0, 1]
    acf_5 = np.corrcoef(absofi_arr[:-5], absofi_arr[5:])[0, 1]
    ofi_dist["absofi_acf_lag1"] = float(acf_1)
    ofi_dist["absofi_acf_lag5"] = float(acf_5)
    print(f"  OFI: mean={ofi_dist['ofi_mean']:.4f}, std={ofi_dist['ofi_std']:.4f}")
    print(f"  |OFI| ACF(1)={acf_1:.3f}, ACF(5)={acf_5:.3f}")

    # ============================================================
    # Final results JSON
    # ============================================================
    final = {
        "experiment_id": "K1124",
        "title": "TAIFEX OFI for short-horizon vol prediction",
        "data_source": "TAIFEX TX futures tick data (local 33G)",
        "period": {"start": str(STUDY_START.date()), "end": str(STUDY_END.date())},
        "n_days": int(bars["date"].nunique()),
        "n_bars": int(len(md)),
        "IS_period": f"{md_is['date'].min().date()}..{md_is['date'].max().date()}",
        "OOS_period": f"{md_oos['date'].min().date()}..{md_oos['date'].max().date()}",
        "n_IS": int(len(md_is)),
        "n_OOS": int(len(md_oos)),
        "models": results,
        "dm_tests_vs_M2": dm_results,
        "subperiod_OOS": subperiod,
        "settlement_effect": settlement,
        "ofi_distribution": ofi_dist,
        "triple_threshold_evaluation": {},
    }

    # Triple threshold check (H1 core)
    print("\n[VERDICT] Triple threshold vs M2 HAR baseline")
    for name, m, dm in [("M3", m3, dm_results["M3"]),
                         ("M4", m4, dm_results["M4"]),
                         ("M5", m5, dm_results["M5"]),
                         ("M6", m6, dm_results["M6"]),
                         ("M7", m7, dm_results["M7"])]:
        qlike_impr = 100 * (m2["OOS_QLIKE"] - m["OOS_QLIKE"]) / m2["OOS_QLIKE"]
        h1_better = subperiod[name]["OOS_H1_QLIKE"] < subperiod["M2"]["OOS_H1_QLIKE"]
        h2_better = subperiod[name]["OOS_H2_QLIKE"] < subperiod["M2"]["OOS_H2_QLIKE"]
        dm_pass = abs(dm["dm_stat"]) > 2
        qlike_pass = qlike_impr > 5
        stable_pass = h1_better and h2_better
        overall = dm_pass and qlike_pass and stable_pass
        print(f"  {name}: DM|t|>2={dm_pass} ({dm['dm_stat']:+.2f}), "
              f"QLIKE>5%={qlike_pass} ({qlike_impr:+.2f}%), "
              f"stable={stable_pass} -> {'PASS' if overall else 'FAIL'}")
        final["triple_threshold_evaluation"][name] = {
            "dm_stat": dm["dm_stat"],
            "qlike_improvement_pct": qlike_impr,
            "sub_h1_improve": bool(h1_better),
            "sub_h2_improve": bool(h2_better),
            "verdict": "PASS" if overall else "FAIL",
        }

    out_path = SCRIPT_DIR / "k1124_results.json"
    with open(out_path, "w") as f:
        json.dump(final, f, indent=2, default=str)
    print(f"\n[DONE] Wrote {out_path}")

    # Plots
    make_plots(md, md_is, md_oos, m2, m3, m4, m5, m6, m7, SCRIPT_DIR)

    return final


def make_plots(md, md_is, md_oos, m2, m3, m4, m5, m6, m7, out_dir):
    # Plot 1: OFI distribution + ACF
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    axes[0].hist(md["ofi_signed"].values, bins=50, color="steelblue", alpha=0.7)
    axes[0].set_title("OFI distribution (all bars)")
    axes[0].set_xlabel("OFI")
    axes[0].axvline(0, color="red", ls="--")

    # ACF
    from scipy.signal import correlate
    ao = md_is["abs_ofi"].values - md_is["abs_ofi"].values.mean()
    acf = correlate(ao, ao, mode="full")[len(ao) - 1:][:30]
    acf /= acf[0]
    axes[1].stem(range(30), acf, basefmt=" ")
    axes[1].set_title("|OFI| ACF (lag 0..29)")
    axes[1].axhline(0, color="black", lw=0.5)
    axes[1].set_xlabel("lag")
    plt.tight_layout()
    plt.savefig(out_dir / "k1124_ofi_distribution.png", dpi=100)
    plt.close()

    # Plot 2: OOS QLIKE bar chart
    fig, ax = plt.subplots(figsize=(10, 5))
    labels = ["M2 HAR", "M3 HAR+|OFI|", "M4 HAR+OFI", "M5 HAR+pers",
              "M6 HAR+|OFI|_{t-1}", "M7 HAR+OFI_{t-1}"]
    vals = [m2["OOS_QLIKE"], m3["OOS_QLIKE"], m4["OOS_QLIKE"], m5["OOS_QLIKE"],
            m6["OOS_QLIKE"], m7["OOS_QLIKE"]]
    colors = ["gray", "steelblue", "green", "orange", "purple", "crimson"]
    bars_p = ax.bar(labels, vals, color=colors, alpha=0.8)
    ax.set_ylabel("OOS QLIKE (lower better)")
    ax.set_title("K1124: Out-of-Sample QLIKE comparison (2020-2021)")
    for b, v in zip(bars_p, vals):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.4f}",
                ha="center", va="bottom", fontsize=9)
    plt.tight_layout()
    plt.savefig(out_dir / "k1124_oos_qlike.png", dpi=100)
    plt.close()

    # Plot 3: settlement vs non |OFI|
    try:
        fig, ax = plt.subplots(figsize=(7, 5))
        sett = md_oos.loc[md_oos["is_settlement"], "abs_ofi"]
        non = md_oos.loc[~md_oos["is_settlement"], "abs_ofi"]
        ax.boxplot([non.values, sett.values], labels=["non-settle", "settle day"])
        ax.set_ylabel("|OFI|")
        ax.set_title("|OFI| distribution: settlement vs non-settlement (OOS)")
        plt.tight_layout()
        plt.savefig(out_dir / "k1124_settlement_ofi.png", dpi=100)
        plt.close()
    except Exception as e:
        print(f"Plot 3 skipped: {e}")


if __name__ == "__main__":
    main()
