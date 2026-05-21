"""
K1301 — HAR-RS (Realized Semivariance) vs HAR-RV on TAIFEX TX1 + SPY
====================================================================

Motivation
----------
research_program.md open TODO: Barndorff-Nielsen-Kinnebrock-Shephard (BNKS, 2008)
proposed decomposing daily Realized Variance into upside / downside semivariances
by sign of intraday returns:

    RV_t        = sum_k r_{t,k}^2
    RS_plus_t   = sum_k r_{t,k}^2 * 1(r_{t,k} > 0)
    RS_minus_t  = sum_k r_{t,k}^2 * 1(r_{t,k} < 0)
    => RV_t = RS_plus_t + RS_minus_t  (by construction)

HAR-RS replaces the 3 HAR-RV terms (daily/weekly/monthly RV averages) by 6 terms
(daily/weekly/monthly RS_plus + RS_minus), testing whether downside semivariance
*dominates* RV in forecasting log(RV_{t+1}).

Related K
---------
- K863  : Phase Transition Detection NULL (physics indicators AUC 0.514 < VIX 0.555).
          Did not directly test BNKS decomposition.
- K868  : HAR Day/Night decomposition NULL (night info already captured by total RV).
          K1301 hypothesis: BNKS by-sign decomposition is a different cut from
          K868 by-session decomposition — may carry incremental info.
- K1100h: TAIFEX tick → 5-min bar pipeline (we reuse the loader pattern, but
          extend to 2017-2026 instead of 2017-2021).
- K1268 : SPY 5-min via yfinance, 60-day rolling cap lesson — short OOS OK for
          intraday-derived features as long as DM-HLN sample is honest.

Data
----
- TAIFEX TX1 5-min bars 2017-05-16 to 2026-05-08 (TAIFEX_DIR has files up to
  2026-05-08). Bars built from tick CSV via K1100h-derived loader; day session
  only (08:45 - 13:45, ~60 bars/day) is used for BNKS to avoid mixing the
  microstructure of the day vs night sessions. Robustness: also report SPY.
- SPY 5-min via yfinance, last 30 trading days (limited by yfinance 60d cap;
  intentionally short — see K1268 lesson).

Lookahead discipline
--------------------
- Target Y_t = log(RV_{t+1}).  Features at time t use only [t-22, ..., t-1]:
    daily      = RV_{t-1}                                 (lag-1)
    weekly_avg = mean(RV_{t-5}, ..., RV_{t-1})            (5 obs, lag-1 to lag-5)
    monthly_avg= mean(RV_{t-22}, ..., RV_{t-1})           (22 obs)
- Same lag convention for RS_plus / RS_minus.
- No future leakage: regression rows where any feature is NaN (warm-up) dropped.

Statistical tests
-----------------
- 70/30 chronological split.
- Estimate HAR-RV and HAR-RS OLS on the same training rows.
- Compute squared loss e_t^2 on the test set for both models.
- Diebold-Mariano (1995) test with Harvey-Leybourne-Newbold (1997) small-sample
  correction (HLN) at h=1; report DM_HLN_t and p-value.
- Pass criterion (per K1301 design):  |DM_HLN_t| > 3  AND  HAR-RS lower MSE
  => BNKS asymmetry adds significant information.
- Null:  HAR-RS DM_HLN_t close to zero / sign favoring HAR-RV
  => BNKS decomposition does not improve over HAR-RV  (K868-style result).

Seed = 42 wherever randomness enters (here only in bootstrap CI on test MSE).

Author : Claude (K1301, main thread autonomous)
Date   : 2026-05-11
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

TAIFEX_DIR = Path.home() / "Dropbox/TAIFEXDATA/TAIFEXDATA/python"

CACHE_TX1_5MIN = DATA_DIR / "_tx1_5min_2017-2026.parquet"
CACHE_TX1_DAILY_RS = DATA_DIR / "_tx1_daily_rs_2017-2026.parquet"
CACHE_SPY_5MIN = DATA_DIR / "_spy_5min_recent.parquet"
CACHE_SPY_DAILY_RS = DATA_DIR / "_spy_daily_rs_recent.parquet"

SEED = 42
RNG = np.random.default_rng(SEED)


# ======================================================================
# 1) TAIFEX TX1 tick → 5-min bars → daily RV / RS+ / RS-
#     (Lightweight clone of K1100h loader, scoped to day session,
#      extended through 2026-05.)
# ======================================================================
COLS_RAW = [
    "trade_date", "symbol", "contract_mo", "trade_time",
    "price", "qty", "near_price", "far_price",
    "auction_flag", "ts",
]


def _load_one_tx1(fn: Path) -> pd.DataFrame:
    """Load one TAIFEX TX1 daily CSV (big5 / cp950 / utf-8) → clean tick frame."""
    last_err: Optional[Exception] = None
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
    """Day session 08:45-13:45 only → 5-min bars (last-tick close per bin).

    K1100h-v2 endpoint fix: collapse bar_start >= 13:45 of file_date back to
    13:40 (so the close tick at 13:45:00 belongs to the (13:40, 13:45] bar
    instead of creating a 61st bar).
    """
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


def build_tx1_daily_rs(force: bool = False) -> pd.DataFrame:
    """Build daily RV / RS+ / RS- table for TAIFEX TX1 day session 2017-05-16 → 2026-05-08."""
    if CACHE_TX1_DAILY_RS.exists() and not force:
        return pd.read_parquet(CACHE_TX1_DAILY_RS)

    files = _list_tx1_files(pd.Timestamp("2017-05-16"), pd.Timestamp("2026-05-08"))
    print(f"[TX1] Found {len(files)} files (2017-05-16 → 2026-05-08)")

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
            r2 = rets ** 2
            rv = float(r2.sum())
            rs_plus = float((r2 * (rets > 0)).sum())
            rs_minus = float((r2 * (rets < 0)).sum())
            # log-return total for sanity
            tot_ret = float(np.log(prices[-1] / prices[0]))
            rows.append({
                "date": file_date,
                "rv": rv,
                "rs_plus": rs_plus,
                "rs_minus": rs_minus,
                "ret": tot_ret,
                "n_bars": int(len(bars)),
            })
        except Exception as e:
            print(f"  [warn] {fn.name}: {e}")
        if (i + 1) % 250 == 0:
            print(f"  [{i+1}/{len(files)}] elapsed={time.time()-t0:.1f}s")
    if not rows:
        raise RuntimeError("[TX1] No daily rows built")
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    df.to_parquet(CACHE_TX1_DAILY_RS, index=False)
    print(f"[TX1] Cached {len(df)} daily rows → {CACHE_TX1_DAILY_RS}")
    return df


# ======================================================================
# 2) SPY 5-min via yfinance → daily RV / RS+ / RS-
# ======================================================================
def build_spy_daily_rs(force: bool = False) -> pd.DataFrame:
    if CACHE_SPY_DAILY_RS.exists() and not force:
        return pd.read_parquet(CACHE_SPY_DAILY_RS)
    import yfinance as yf
    # yfinance allows up to 60d at 5m; we ask for 60d to maximize sample, then
    # honor "last 30 days" per K1301 design (last 30 unique trading dates).
    print("[SPY] Downloading 5-min bars (60d)...")
    df = yf.download("SPY", period="60d", interval="5m",
                     auto_adjust=True, progress=False)
    if df is None or df.empty:
        raise RuntimeError("[SPY] yfinance returned empty")
    # Flatten possible MultiIndex columns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    ts_col = "Datetime" if "Datetime" in df.columns else df.columns[0]
    df = df.rename(columns={ts_col: "ts", "Close": "close"})
    df["ts"] = pd.to_datetime(df["ts"])
    # Convert to ET-naive for session day labelling
    if df["ts"].dt.tz is not None:
        df["ts"] = df["ts"].dt.tz_convert("America/New_York").dt.tz_localize(None)
    df["session_date"] = df["ts"].dt.normalize()
    # Restrict to regular session 09:30 - 16:00 ET
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
        r2 = rets ** 2
        rv = float(r2.sum())
        rs_plus = float((r2 * (rets > 0)).sum())
        rs_minus = float((r2 * (rets < 0)).sum())
        rows.append({
            "date": date,
            "rv": rv,
            "rs_plus": rs_plus,
            "rs_minus": rs_minus,
            "ret": float(np.log(prices[-1] / prices[0])),
            "n_bars": int(len(grp)),
        })
    out = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    # Keep last 30 trading days per K1301 design.
    if len(out) > 30:
        out = out.tail(30).reset_index(drop=True)
    out.to_parquet(CACHE_SPY_DAILY_RS, index=False)
    print(f"[SPY] Cached {len(out)} daily rows → {CACHE_SPY_DAILY_RS}")
    return out


# ======================================================================
# 3) HAR feature builder + OLS + DM-HLN
# ======================================================================
def build_har_features(daily: pd.DataFrame) -> pd.DataFrame:
    """Add HAR features built ONLY from lagged values [t-22, ..., t-1].

    Returns dataframe with:
      Y               = log(RV_{t+1})  -- target placed at row t
      rv_d, rv_w, rv_m = HAR-RV daily/weekly/monthly aggregates from lag-1
      rsp_d, rsp_w, rsp_m, rsn_d, rsn_w, rsn_m  = HAR-RS variants
    Floor RV at 1e-12 before log.
    """
    d = daily.copy().sort_values("date").reset_index(drop=True)
    eps = 1e-12

    rv_lag1 = d["rv"].shift(1)
    rsp_lag1 = d["rs_plus"].shift(1)
    rsn_lag1 = d["rs_minus"].shift(1)

    # Weekly = avg of last 5 daily values [t-5, ..., t-1]
    d["rv_d"] = rv_lag1
    d["rv_w"] = rv_lag1.rolling(window=5, min_periods=5).mean()
    d["rv_m"] = rv_lag1.rolling(window=22, min_periods=22).mean()

    d["rsp_d"] = rsp_lag1
    d["rsp_w"] = rsp_lag1.rolling(window=5, min_periods=5).mean()
    d["rsp_m"] = rsp_lag1.rolling(window=22, min_periods=22).mean()

    d["rsn_d"] = rsn_lag1
    d["rsn_w"] = rsn_lag1.rolling(window=5, min_periods=5).mean()
    d["rsn_m"] = rsn_lag1.rolling(window=22, min_periods=22).mean()

    # Target: log(RV_{t+1})  -- shift up so row at date t carries Y for next day
    rv_shift = d["rv"].shift(-1)
    d["Y"] = np.log(rv_shift.clip(lower=eps))
    # Diagnostic: how many rows would have been clipped at 1e-12 floor?
    n_clip_target = int(((rv_shift > 0) & (rv_shift < eps)).sum())

    feat_cols = ["rv_d", "rv_w", "rv_m",
                 "rsp_d", "rsp_w", "rsp_m",
                 "rsn_d", "rsn_w", "rsn_m"]
    # Drop rows with any NaN in features or target
    d = d.dropna(subset=feat_cols + ["Y"]).reset_index(drop=True)
    # Log-transform features (HAR commonly uses log RV); floor first
    n_clip_feat = 0
    for c in feat_cols:
        n_clip_feat += int(((d[c] > 0) & (d[c] < eps)).sum())
        d[c] = np.log(d[c].clip(lower=eps))
    d.attrs["n_clip_target"] = n_clip_target
    d.attrs["n_clip_feat"] = n_clip_feat
    return d


def fit_ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Closed-form OLS with intercept column."""
    X1 = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    return beta


def predict_ols(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    X1 = np.column_stack([np.ones(len(X)), X])
    return X1 @ beta


def dm_hln(loss_a: np.ndarray, loss_b: np.ndarray, h: int = 1) -> Tuple[float, float]:
    """Diebold-Mariano with Harvey-Leybourne-Newbold small-sample correction.

    d_t   = loss_a - loss_b
    DM    = mean(d) / sqrt(Var_lr(d)/T)
    HLN   = DM * sqrt((T + 1 - 2h + h(h-1)/T) / T)
    p     = 2 * (1 - t_cdf(|HLN|, df=T-1))
    """
    from scipy import stats as sp_stats
    d = np.asarray(loss_a, dtype=float) - np.asarray(loss_b, dtype=float)
    T = len(d)
    if T < 3:
        return float("nan"), float("nan")
    mu = d.mean()
    # Newey-West HAC variance with h-1 lags (here h=1 => just sample variance)
    if h <= 1:
        gamma0 = ((d - mu) ** 2).mean()
        v = gamma0
    else:
        gammas = [((d[:T - k] - mu) * (d[k:] - mu)).mean() for k in range(h)]
        v = gammas[0] + 2 * sum(gammas[1:])
    if v <= 0:
        return float("nan"), float("nan")
    dm = mu / np.sqrt(v / T)
    corr = np.sqrt((T + 1 - 2 * h + h * (h - 1) / T) / T)
    hln = dm * corr
    p = 2.0 * (1.0 - sp_stats.t.cdf(abs(hln), df=T - 1))
    return float(hln), float(p)


def bootstrap_mse_ci(losses: np.ndarray, n_boot: int = 1000,
                     seed: int = SEED) -> Tuple[float, float]:
    rng = np.random.default_rng(seed)
    T = len(losses)
    means = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, T, T)
        means[b] = losses[idx].mean()
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def evaluate_asset(name: str, daily: pd.DataFrame) -> Dict:
    print(f"\n[{name}] N daily rows raw = {len(daily)}")
    feat = build_har_features(daily)
    print(f"[{name}] N daily rows after HAR feature warm-up = {len(feat)}")
    if len(feat) < 60:
        print(f"[{name}] WARNING — sample too small for stable 70/30 split")

    rv_cols = ["rv_d", "rv_w", "rv_m"]
    rs_cols = ["rsp_d", "rsp_w", "rsp_m", "rsn_d", "rsn_w", "rsn_m"]

    y = feat["Y"].to_numpy(dtype=float)
    X_rv = feat[rv_cols].to_numpy(dtype=float)
    X_rs = feat[rs_cols].to_numpy(dtype=float)

    T = len(feat)
    n_train = int(np.floor(T * 0.7))
    idx_train = np.arange(n_train)
    idx_test = np.arange(n_train, T)

    # Fit on training, predict test
    beta_rv = fit_ols(X_rv[idx_train], y[idx_train])
    beta_rs = fit_ols(X_rs[idx_train], y[idx_train])

    yhat_rv_te = predict_ols(beta_rv, X_rv[idx_test])
    yhat_rs_te = predict_ols(beta_rs, X_rs[idx_test])

    e_rv = y[idx_test] - yhat_rv_te
    e_rs = y[idx_test] - yhat_rs_te
    mse_rv = float((e_rv ** 2).mean())
    mse_rs = float((e_rs ** 2).mean())
    mae_rv = float(np.abs(e_rv).mean())
    mae_rs = float(np.abs(e_rs).mean())

    dm_t, dm_p = dm_hln(e_rv ** 2, e_rs ** 2, h=1)

    ci_rv = bootstrap_mse_ci(e_rv ** 2)
    ci_rs = bootstrap_mse_ci(e_rs ** 2)

    # In-sample R2 (sanity)
    def _r2(y, yhat):
        ss_res = float(((y - yhat) ** 2).sum())
        ss_tot = float(((y - y.mean()) ** 2).sum())
        return 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    r2_rv_is = _r2(y[idx_train], predict_ols(beta_rv, X_rv[idx_train]))
    r2_rs_is = _r2(y[idx_train], predict_ols(beta_rs, X_rs[idx_train]))
    r2_rv_oos = _r2(y[idx_test], yhat_rv_te)
    r2_rs_oos = _r2(y[idx_test], yhat_rs_te)

    # Sample-size trust flag (Gemini reviewer recommendation 2026-05-11)
    n_test = T - n_train
    if n_test < 30:
        trust_flag = "UNTRUSTWORTHY_SMALL_SAMPLE"
    elif n_test < 100:
        trust_flag = "LIMITED_SAMPLE"
    else:
        trust_flag = "OK"

    return {
        "asset": name,
        "n_daily_rows": int(len(daily)),
        "n_har_rows": int(T),
        "n_train": int(n_train),
        "n_test": int(n_test),
        "n_clip_target_at_eps": int(feat.attrs.get("n_clip_target", 0)),
        "n_clip_feat_at_eps": int(feat.attrs.get("n_clip_feat", 0)),
        "sample_trust_flag": trust_flag,
        "date_range": [str(feat["date"].min()), str(feat["date"].max())],
        "har_rv": {
            "beta": {k: float(v) for k, v in zip(["intercept"] + rv_cols, beta_rv)},
            "mse_oos": mse_rv,
            "mae_oos": mae_rv,
            "r2_is": r2_rv_is,
            "r2_oos": r2_rv_oos,
            "mse_oos_ci95": ci_rv,
        },
        "har_rs": {
            "beta": {k: float(v) for k, v in zip(["intercept"] + rs_cols, beta_rs)},
            "mse_oos": mse_rs,
            "mae_oos": mae_rs,
            "r2_is": r2_rs_is,
            "r2_oos": r2_rs_oos,
            "mse_oos_ci95": ci_rs,
        },
        "dm_hln": {
            "loss": "squared_error",
            "h": 1,
            "t_stat": dm_t,
            "p_value": dm_p,
            "interpretation_sign": (
                "positive => HAR-RV loss > HAR-RS loss => HAR-RS preferred"
            ),
            "harvey_threshold": 3.0,
            "pass_3sigma": (not np.isnan(dm_t)) and abs(dm_t) > 3.0,
            "har_rs_lower_mse": mse_rs < mse_rv,
        },
    }


# ======================================================================
# 4) Main
# ======================================================================
def main():
    out: Dict = {
        "experiment_id": "K1301",
        "title": "HAR-RS (Realized Semivariance) vs HAR-RV on TAIFEX TX1 + SPY",
        "date_run": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seed": SEED,
        "methodology": {
            "decomposition": "Barndorff-Nielsen, Kinnebrock, Shephard (2008) "
                              "RV = RS+ + RS- by sign of 5-min log returns",
            "target": "log(RV_{t+1})",
            "har_rv_features": ["log RV_{t-1}",
                                  "log mean RV_{[t-5,t-1]}",
                                  "log mean RV_{[t-22,t-1]}"],
            "har_rs_features": ["log RS+_{t-1}", "log mean RS+_{[t-5,t-1]}",
                                  "log mean RS+_{[t-22,t-1]}",
                                  "log RS-_{t-1}", "log mean RS-_{[t-5,t-1]}",
                                  "log mean RS-_{[t-22,t-1]}"],
            "split": "70/30 chronological",
            "test": "DM-HLN h=1 on squared errors (Harvey 1997 small-sample correction)",
            "pass_rule": "|DM_HLN_t| > 3 AND HAR-RS lower MSE",
            "lookahead_guard": "all features built from .shift(1) lag + rolling on lagged series; target shift(-1) only on RV column",
        },
        "data_sources": {
            "TX1": "TAIFEX tick CSV 2017-05-16..2026-05-08, day session 08:45-13:45, 5-min bars",
            "SPY": "yfinance 5m, last 30 trading days, regular session 09:30-16:00 ET",
        },
        "results": {},
    }

    # --- TAIFEX TX1 ---
    print("\n============ K1301: TAIFEX TX1 ============")
    try:
        tx1_daily = build_tx1_daily_rs(force=False)
        out["results"]["TX1"] = evaluate_asset("TX1", tx1_daily)
    except Exception as e:
        print(f"[TX1] FAILED: {e}")
        out["results"]["TX1"] = {"error": str(e)}

    # --- SPY ---
    print("\n============ K1301: SPY ============")
    try:
        spy_daily = build_spy_daily_rs(force=False)
        out["results"]["SPY"] = evaluate_asset("SPY", spy_daily)
    except Exception as e:
        print(f"[SPY] FAILED: {e}")
        out["results"]["SPY"] = {"error": str(e)}

    # --- Verdict ---
    verdict_lines: List[str] = []
    for asset in ("TX1", "SPY"):
        r = out["results"].get(asset, {})
        if "dm_hln" in r:
            dm = r["dm_hln"]
            mse_rv = r["har_rv"]["mse_oos"]
            mse_rs = r["har_rs"]["mse_oos"]
            verdict_lines.append(
                f"{asset}: DM_HLN_t={dm['t_stat']:.3f}  p={dm['p_value']:.4f}  "
                f"MSE_RV={mse_rv:.4f}  MSE_RS={mse_rs:.4f}  "
                f"pass_3sigma={dm['pass_3sigma']}  rs_lower_mse={dm['har_rs_lower_mse']}"
            )
        else:
            verdict_lines.append(f"{asset}: ERROR — {r.get('error', 'unknown')}")
    out["verdict_lines"] = verdict_lines
    print("\n============ VERDICT ============")
    for ln in verdict_lines:
        print(ln)

    # Overall classification per design rule — UNTRUSTWORTHY samples are
    # explicitly excluded from verdict per Gemini reviewer recommendation.
    def _pass(r):
        if "dm_hln" not in r:
            return False
        if r.get("sample_trust_flag") == "UNTRUSTWORTHY_SMALL_SAMPLE":
            return False
        return r["dm_hln"]["pass_3sigma"] and r["dm_hln"]["har_rs_lower_mse"]

    trustworthy_assets = [
        a for a in ("TX1", "SPY")
        if out["results"].get(a, {}).get("sample_trust_flag") != "UNTRUSTWORTHY_SMALL_SAMPLE"
        and "dm_hln" in out["results"].get(a, {})
    ]
    passes = [a for a in trustworthy_assets if _pass(out["results"][a])]
    out["trustworthy_assets"] = trustworthy_assets
    if not trustworthy_assets:
        out["overall_verdict"] = "INCONCLUSIVE_NO_TRUSTED_SAMPLE"
    elif len(passes) == len(trustworthy_assets):
        out["overall_verdict"] = "PASS_BOTH" if len(passes) > 1 else "PASS_SINGLE_TRUSTED_ASSET"
    elif passes:
        out["overall_verdict"] = "PASS_PARTIAL"
    else:
        out["overall_verdict"] = "NULL"

    out_path = SCRIPT_DIR / "k1301_results.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[done] wrote {out_path}")


if __name__ == "__main__":
    main()
