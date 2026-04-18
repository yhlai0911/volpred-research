"""
K1130 - Extended IS 2012-2019 for K1128 OFI-jump regime test
==============================================================

Follow-up to K1128 / K1131: testing error_log 2026-04-13 fix #1
(extend IS to include prior VIX spikes 2012-2019) for regime-switching fix.

Problem (from K1128 and K1131):
  K1128 used IS 2017-2019 (VIX 9-37). OOS 2020-2021 contained COVID VIX up to 82.
  IS VIX tertile cutoffs (33%=12.07, 67%=14.99) applied to OOS: low=0, mid=854,
  high=20,060. Regime design collapsed — almost everything is "high" tertile.
  K1131 (spline) NULL: OOS DM t=-3.94 (spline worse); proved problem is structural.

Fix tested here (error_log 2026-04-13 fix #1):
  Extend IS to 2012-2019 (8 years) so IS contains 2015 China devaluation
  (VIX ~40+) and 2018 Feb volpocalypse (VIX ~50). Extended IS's VIX tertile
  cutoffs should be wider — hopefully overlapping OOS VIX range so regime
  split is not degenerate.

  Note: TAIFEX tick data starts 2012 (CLAUDE.md). Cannot use 2008 GFC.

Hypotheses (mirrors task brief):
  H1: Extended IS LRT chi^2 (regime vs no-regime) > K1128 chi^2 AND p < 0.05
  H2: Extended IS regime OOS DM-HLN t<=-2 (vs no-regime baseline),
      Harvey joint with p<0.05
  H3: Extended IS regime OOS DM t<=-2 vs K1128 original-IS regime
      (i.e., extended significantly better than original)
  H4: OOS bar coverage per extended-IS tertile >= 10% for each of 3 tertiles

Scenarios:
  A: All PASS — fix validated, error_log #1 confirmed
  B: H1/H2 PASS, H3 marginal — partial/incremental
  C: H4 PASS (coverage fixed), H2 FAIL — regime split OK but signal unstable
  D: H4 FAIL — extended IS still cannot cover COVID OOS

Data:
  - TAIFEX TX futures 2012-2021 tick data (local)
  - VIX daily from yfinance
  - Extended IS: 2012-01-01 .. 2019-12-31 (8 years)
  - OOS: 2020-01-01 .. 2021-12-31 (aligned with K1128)

Worktree rules (experiment-preamble.md Section 8):
  - Only writes under experiments/k1130/
  - No knowledge.json / feed.json writes
  - No supabase_sync
  - Commit at end

Author: Claude (main-thread agent-k1130)
Date: 2026-04-17
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats as sp_stats

from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, brier_score_loss, log_loss
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

np.random.seed(42)
RNG = np.random.default_rng(42)

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR
TAIFEX_DIR = Path("/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python")

DAY_START = 84500
DAY_END = 134459   # exclusive of 13:45 (K1124 Codex fix)

STUDY_START = pd.Timestamp("2012-01-01")
STUDY_END = pd.Timestamp("2021-12-31")

IS_END = pd.Timestamp("2019-12-31")
OOS_START = pd.Timestamp("2020-01-01")

# For K1131 reference to prior K1128 IS
K1128_IS_START = pd.Timestamp("2017-01-01")
K1128_IS_END = pd.Timestamp("2019-12-31")

MU1 = np.sqrt(2.0 / np.pi)
K_WIN = 16
JUMP_ALPHA = 0.01


# =====================================================================
# 1. TAIFEX bar loading pipeline (reused verbatim from K1124 w/ rolling
#    T-1 active contract selection)
# =====================================================================
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
    return int(df.groupby("contract_month")["volume"].sum().idxmax())


def _pick_active_contract_rolling(prev_df, curr_df):
    if prev_df is None:
        return _pick_active_contract(curr_df)
    prev_totals = prev_df.groupby("contract_month")["volume"].sum()
    curr_contracts = set(curr_df["contract_month"].unique())
    for contract, _ in prev_totals.sort_values(ascending=False).items():
        if int(contract) in curr_contracts:
            return int(contract)
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

    df = pd.DataFrame({"bar": bar, "price": p, "volume": v, "signed_vol": signed_vol})

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
            "date": date, "bar": int(b_id),
            "price_open": float(prices_b[0]), "price_close": float(prices_b[-1]),
            "log_ret": float(np.log(prices_b[-1] / prices_b[0])),
            "volume": total_vol, "signed_vol": signed_sum, "ofi": ofi,
            "rv": rv, "n_ticks": int(len(g)),
            "is_settlement": bool(_is_third_wednesday(date)),
        })
    return pd.DataFrame(bars)


def load_all_bars(start: pd.Timestamp, end: pd.Timestamp, cache: bool = True) -> pd.DataFrame:
    cache_path = SCRIPT_DIR / f"_cache_bars_{start.date()}_{end.date()}.parquet"
    if cache and cache_path.exists():
        print(f"[CACHE] Loading {cache_path.name}")
        df = pd.read_parquet(cache_path)
        df["date"] = pd.to_datetime(df["date"])
        return df

    print(f"[TAIFEX] Scanning {TAIFEX_DIR} for {start.date()}..{end.date()}")
    all_files = sorted(TAIFEX_DIR.glob("Daily_*TX.csv"))
    frames = []
    t0 = time.time()
    n_done = 0
    prev_df = None
    for f in all_files:
        date = _parse_date_from_filename(f.name)
        if date is None or date < (start - pd.Timedelta(days=4)) or date > end:
            continue
        df = _read_taifex_file(f)
        if df is None:
            prev_df = None
            continue
        active = _pick_active_contract_rolling(prev_df, df)
        prev_df = df
        if date < start:
            continue
        df_active = df[df["contract_month"] == active].copy()
        day_mask = (df_active["time_int"] >= DAY_START) & (df_active["time_int"] <= DAY_END)
        day_df = df_active.loc[day_mask]
        if len(day_df) < 50:
            continue
        bars = compute_bars_for_day(day_df, date)
        if len(bars) < 30:
            continue
        bars["active_contract"] = active
        frames.append(bars)
        n_done += 1
        if n_done % 200 == 0:
            print(f"  processed {n_done} days, elapsed {time.time()-t0:.1f}s")

    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values(["date", "bar"]).reset_index(drop=True)
    print(f"[TAIFEX] Loaded {n_done} days, {len(out)} bars, {time.time()-t0:.1f}s")
    if cache:
        out.to_parquet(cache_path, index=False)
        print(f"[CACHE] Saved to {cache_path.name}")
    return out


# =====================================================================
# 2. Lee-Mykland jump detection (reuse K1128 BV-fixed formula)
# =====================================================================
def compute_jumps_per_day(day_df: pd.DataFrame, K: int = K_WIN):
    r = day_df["log_ret"].values
    n = len(r)
    sigma_hat = np.full(n, np.nan)
    abs_r = np.abs(r)
    pairs = abs_r[:-1] * abs_r[1:]
    for t in range(K, n):
        start = t - K
        stop = t - 1
        if start >= 0 and stop <= len(pairs):
            window_pairs = pairs[start:stop]
            if len(window_pairs) == K - 1:
                bv = window_pairs.sum() / ((K - 1) * MU1 ** 2)
                sigma_hat[t] = np.sqrt(max(bv, 1e-16))
    L = abs_r / sigma_hat
    return sigma_hat, L


# =====================================================================
# 3. Logistic fit + DM-HLN (reuse K1128 code)
# =====================================================================
def fit_logistic(X_is, y_is, X_oos, y_oos, name):
    sc = StandardScaler()
    Xi = sc.fit_transform(X_is)
    Xo = sc.transform(X_oos)
    model = LogisticRegression(C=1.0, max_iter=1000, solver="lbfgs", random_state=42)
    model.fit(Xi, y_is)
    p_is = np.clip(model.predict_proba(Xi)[:, 1], 1e-7, 1 - 1e-7)
    p_oos = np.clip(model.predict_proba(Xo)[:, 1], 1e-7, 1 - 1e-7)
    auc_is = roc_auc_score(y_is, p_is) if len(np.unique(y_is)) > 1 else np.nan
    auc_oos = roc_auc_score(y_oos, p_oos) if len(np.unique(y_oos)) > 1 else np.nan
    ll_is = float(-log_loss(y_is, p_is))
    ll_oos = float(-log_loss(y_oos, p_oos))
    return {
        "name": name,
        "n_features": int(X_is.shape[1]),
        "coefs": model.coef_[0].tolist(),
        "intercept": float(model.intercept_[0]),
        "scaler_mean": sc.mean_.tolist(),
        "scaler_scale": sc.scale_.tolist(),
        "auc_is": float(auc_is) if not np.isnan(auc_is) else None,
        "auc_oos": float(auc_oos) if not np.isnan(auc_oos) else None,
        "brier_is": float(brier_score_loss(y_is, p_is)),
        "brier_oos": float(brier_score_loss(y_oos, p_oos)),
        "ll_is": ll_is,
        "ll_oos": ll_oos,
        "n_is": int(len(y_is)),
        "n_oos": int(len(y_oos)),
        "n_is_positive": int(y_is.sum()),
        "n_oos_positive": int(y_oos.sum()),
        "p_is": p_is,
        "p_oos": p_oos,
    }


def dm_hln_ll(p1, p2, y, name=""):
    """DM-HLN on log-loss differences. t>0 => p2 has higher LL than p1."""
    eps = 1e-7
    p1c = np.clip(p1, eps, 1 - eps)
    p2c = np.clip(p2, eps, 1 - eps)
    ll1 = y * np.log(p1c) + (1 - y) * np.log(1 - p1c)
    ll2 = y * np.log(p2c) + (1 - y) * np.log(1 - p2c)
    d = ll2 - ll1
    n = len(d)
    mean_d = d.mean()
    if abs(mean_d) < 1e-20:
        return {"t": 0.0, "t_plain": 0.0, "mean_d": 0.0, "se": 0.0, "n": int(n)}
    q = max(1, int(np.ceil(n ** (1/3))))
    d_dm = d - mean_d
    gamma_0 = (d_dm ** 2).mean()
    var_nw = gamma_0
    for k in range(1, q + 1):
        if k < n:
            gamma_k = (d_dm[k:] * d_dm[:-k]).mean()
            w_k = 1.0 - k / (q + 1)
            var_nw += 2 * w_k * gamma_k
    se = np.sqrt(max(var_nw, 1e-16) / n)
    t_plain = mean_d / se
    hln_mult = np.sqrt((n + 1 - 2 * 1 + 1 * (1 - 1) / n) / n)
    t_hln = t_plain * hln_mult
    return {"t": float(t_hln), "t_plain": float(t_plain),
            "mean_d": float(mean_d), "se": float(se), "n": int(n)}


# =====================================================================
# MAIN
# =====================================================================
def main():
    print("=" * 70)
    print("K1130 - Extended IS 2012-2019 OFI-jump regime retest")
    print("=" * 70)
    t0 = datetime.now()

    # --------- Step 1: load bars (build extended cache 2012-2021) ---------
    print("\n[Step 1] Loading bars 2012-2021 (build extended cache if needed)...")
    df = load_all_bars(STUDY_START, STUDY_END, cache=True)
    df = df.sort_values(["date", "bar"]).reset_index(drop=True)
    print(f"  Loaded {len(df):,} bars across {df['date'].nunique()} days")
    print(f"  Period: {df['date'].min()} to {df['date'].max()}")

    # --------- Step 2: Lee-Mykland jump detection ---------
    print("\n[Step 2] Computing Lee-Mykland jump statistic...")
    all_sigma = np.full(len(df), np.nan)
    all_L = np.full(len(df), np.nan)
    for date, idx in df.groupby("date").groups.items():
        idx_arr = np.array(idx)
        day_df = df.loc[idx_arr]
        sigma_hat, L = compute_jumps_per_day(day_df, K=K_WIN)
        all_sigma[idx_arr] = sigma_hat
        all_L[idx_arr] = L
    df["sigma_hat"] = all_sigma
    df["L_stat"] = all_L

    n_valid_global = np.isfinite(all_L).sum()
    C_n = np.sqrt(2 * np.log(n_valid_global)) - 0.5 * (np.log(np.log(n_valid_global)) + np.log(4 * np.pi)) / np.sqrt(2 * np.log(n_valid_global))
    S_n = 1.0 / np.sqrt(2 * np.log(n_valid_global))
    beta_n = -np.log(-np.log(1 - JUMP_ALPHA))
    thresh_multi = C_n + S_n * beta_n

    df["jump"] = ((df["L_stat"] > thresh_multi) & np.isfinite(df["L_stat"])).astype(int)
    df.loc[~np.isfinite(df["L_stat"]), "jump"] = -1
    n_jump = (df["jump"] == 1).sum()
    print(f"  Valid L obs: {n_valid_global:,}")
    print(f"  Gumbel threshold (alpha={JUMP_ALPHA}): {thresh_multi:.3f}")
    print(f"  Jumps: {n_jump} ({n_jump/n_valid_global*100:.2f}%)")

    # --------- Step 3: features + jump_{t+1} target ---------
    print("\n[Step 3] Building features and jump_{t+1} target...")
    df["jump_next"] = -1
    df["ofi_abs"] = df["ofi"].abs()
    for date, gdf in df.groupby("date"):
        idx = gdf.index.values
        jumps = gdf["jump"].values
        jump_next = np.full(len(gdf), -1)
        jump_next[:-1] = jumps[1:]
        df.loc[idx, "jump_next"] = jump_next

    valid_mask = (df["jump_next"].isin([0, 1])) & df["ofi"].notna() & df["log_ret"].notna()
    valid_mask &= np.isfinite(df["L_stat"])
    df_valid = df[valid_mask].copy().reset_index(drop=True)
    print(f"  Valid bars: {len(df_valid):,}")
    print(f"  Jump rate: {df_valid['jump_next'].mean()*100:.3f}%")

    # --------- Step 4: load VIX with T-1 lag ---------
    print("\n[Step 4] Loading daily VIX (T-1 lag)...")
    import yfinance as yf
    vix = yf.download("^VIX", start="2011-12-01", end="2022-01-31",
                      progress=False, auto_adjust=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    vix_df = vix[["Close"]].reset_index()
    vix_df.columns = ["date", "vix"]
    vix_df["date"] = pd.to_datetime(vix_df["date"]).dt.normalize()
    vix_df = vix_df.dropna().drop_duplicates("date").sort_values("date").reset_index(drop=True)
    vix_df["vix_lag1"] = vix_df["vix"].shift(1)
    vix_df["vix_lag1"] = vix_df["vix_lag1"].ffill()

    df_valid["date_norm"] = pd.to_datetime(df_valid["date"]).dt.normalize()
    df_valid = df_valid.merge(
        vix_df[["date", "vix_lag1"]].rename(columns={"date": "date_norm"}),
        on="date_norm", how="left",
    )
    df_valid["vix_lag1"] = df_valid["vix_lag1"].ffill().bfill()  # bfill safety for first rows
    n_missing_vix = df_valid["vix_lag1"].isna().sum()
    print(f"  VIX days: {len(vix_df)}, missing in merged: {n_missing_vix}")
    # If first few days after TAIFEX open have no matched VIX (due to holiday),
    # use next-available VIX. Keep assertion soft:
    if n_missing_vix > 0:
        print("  [WARN] some VIX missing; dropping those rows.")
        df_valid = df_valid.dropna(subset=["vix_lag1"]).reset_index(drop=True)

    # --------- Step 5: tertile cutoffs on EXTENDED IS (2012-2019) ---------
    print("\n[Step 5] VIX tertile cutoffs (extended IS 2012-2019)...")
    df_valid["year"] = df_valid["date"].dt.year
    is_mask_ext = df_valid["year"].isin(list(range(2012, 2020)))  # 2012..2019
    is_mask_k1128 = df_valid["year"].isin([2017, 2018, 2019])
    oos_mask = df_valid["year"].isin([2020, 2021])

    vix_is_ext = df_valid.loc[is_mask_ext, "vix_lag1"].values
    vix_is_k1128 = df_valid.loc[is_mask_k1128, "vix_lag1"].values
    cutoff_33_ext = float(np.quantile(vix_is_ext, 1/3))
    cutoff_67_ext = float(np.quantile(vix_is_ext, 2/3))
    cutoff_33_k1128 = float(np.quantile(vix_is_k1128, 1/3))
    cutoff_67_k1128 = float(np.quantile(vix_is_k1128, 2/3))
    print(f"  Extended IS VIX: min={vix_is_ext.min():.2f}, mean={vix_is_ext.mean():.2f}, std={vix_is_ext.std():.2f}, max={vix_is_ext.max():.2f}")
    print(f"  K1128 IS VIX:    min={vix_is_k1128.min():.2f}, mean={vix_is_k1128.mean():.2f}, std={vix_is_k1128.std():.2f}, max={vix_is_k1128.max():.2f}")
    print(f"  Extended cutoffs: 33%={cutoff_33_ext:.3f}, 67%={cutoff_67_ext:.3f}")
    print(f"  K1128 cutoffs:    33%={cutoff_33_k1128:.3f}, 67%={cutoff_67_k1128:.3f}")

    def assign_tertile(vix_val, c33, c67):
        if vix_val <= c33:
            return 0
        elif vix_val <= c67:
            return 1
        else:
            return 2

    df_valid["vix_tertile_ext"] = df_valid["vix_lag1"].apply(
        lambda v: assign_tertile(v, cutoff_33_ext, cutoff_67_ext)
    )
    df_valid["vix_tertile_k1128"] = df_valid["vix_lag1"].apply(
        lambda v: assign_tertile(v, cutoff_33_k1128, cutoff_67_k1128)
    )

    # --------- Step 6: OOS regime coverage comparison (H4) ---------
    print("\n[Step 6] OOS regime coverage comparison (H4)...")
    coverage_ext = df_valid.loc[oos_mask, "vix_tertile_ext"].value_counts().sort_index()
    coverage_k1128 = df_valid.loc[oos_mask, "vix_tertile_k1128"].value_counts().sort_index()
    n_oos = int(oos_mask.sum())
    cov_ext_pct = {int(k): float(v / n_oos * 100) for k, v in coverage_ext.items()}
    cov_k1128_pct = {int(k): float(v / n_oos * 100) for k, v in coverage_k1128.items()}
    print(f"  OOS total bars: {n_oos:,}")
    print(f"  K1128 IS tertile OOS %: low={cov_k1128_pct.get(0,0):.2f}%, mid={cov_k1128_pct.get(1,0):.2f}%, high={cov_k1128_pct.get(2,0):.2f}%")
    print(f"  Extended IS OOS %:     low={cov_ext_pct.get(0,0):.2f}%, mid={cov_ext_pct.get(1,0):.2f}%, high={cov_ext_pct.get(2,0):.2f}%")

    # H4 metric: all 3 tertiles must have >= 10% coverage
    min_coverage_pct_ext = min(cov_ext_pct.get(0, 0), cov_ext_pct.get(1, 0), cov_ext_pct.get(2, 0))
    h4_pass = bool(min_coverage_pct_ext >= 10.0)
    print(f"  H4 PASS (min coverage >= 10%): {h4_pass} (min={min_coverage_pct_ext:.2f}%)")

    # --------- Step 7: build features + refit per tertile (extended IS) ---------
    print("\n[Step 7] Building features and fitting per-tertile models (extended IS)...")
    df_valid["jump_curr"] = df_valid["jump"].clip(lower=0)
    df_valid["ofi_t"] = df_valid["ofi"]
    df_valid["ofi_abs_t"] = df_valid["ofi"].abs()

    FEAT_M1 = ["jump_curr"]
    FEAT_M3 = ["jump_curr", "ofi_abs_t", "ofi_t"]
    FEAT_BASE = ["jump_curr", "ofi_abs_t", "ofi_t"]  # no-regime baseline for H2

    tertile_names = {0: "low", 1: "mid", 2: "high"}

    # ---- Per-tertile M1 and M3 fit on EXTENDED IS ----
    tertile_results_ext = {}
    for t_idx in [0, 1, 2]:
        tname = tertile_names[t_idx]
        print(f"\n  [Extended IS] Tertile {t_idx} ({tname}):")
        is_t_mask = is_mask_ext & (df_valid["vix_tertile_ext"] == t_idx)
        oos_t_mask = oos_mask & (df_valid["vix_tertile_ext"] == t_idx)
        n_is_t = int(is_t_mask.sum())
        n_oos_t = int(oos_t_mask.sum())
        n_jumps_is_t = int(df_valid.loc[is_t_mask, "jump_next"].sum())
        n_jumps_oos_t = int(df_valid.loc[oos_t_mask, "jump_next"].sum())
        print(f"    IS N={n_is_t:,} (jumps={n_jumps_is_t}), OOS N={n_oos_t:,} (jumps={n_jumps_oos_t})")

        if n_jumps_is_t < 5 or n_jumps_oos_t < 5:
            print(f"    SKIP: insufficient jumps")
            tertile_results_ext[tname] = {
                "tertile_idx": t_idx, "status": "skipped_insufficient_jumps",
                "n_is": n_is_t, "n_oos": n_oos_t,
                "n_is_jumps": n_jumps_is_t, "n_oos_jumps": n_jumps_oos_t,
            }
            continue

        X_is_M1 = df_valid.loc[is_t_mask, FEAT_M1].values
        y_is_t = df_valid.loc[is_t_mask, "jump_next"].values.astype(int)
        X_oos_M1 = df_valid.loc[oos_t_mask, FEAT_M1].values
        y_oos_t = df_valid.loc[oos_t_mask, "jump_next"].values.astype(int)
        X_is_M3 = df_valid.loc[is_t_mask, FEAT_M3].values
        X_oos_M3 = df_valid.loc[oos_t_mask, FEAT_M3].values

        try:
            M1_t = fit_logistic(X_is_M1, y_is_t, X_oos_M1, y_oos_t, f"M1_ext_{tname}")
            M3_t = fit_logistic(X_is_M3, y_is_t, X_oos_M3, y_oos_t, f"M3_ext_{tname}")
            dm_M3_vs_M1 = dm_hln_ll(M1_t["p_oos"], M3_t["p_oos"], y_oos_t)
        except Exception as e:
            print(f"    ERROR: {e}")
            tertile_results_ext[tname] = {
                "tertile_idx": t_idx, "status": f"error: {e}",
                "n_is": n_is_t, "n_oos": n_oos_t,
            }
            continue

        print(f"    M1 AUC IS={M1_t['auc_is']:.4f} OOS={M1_t['auc_oos']:.4f}")
        print(f"    M3 AUC IS={M3_t['auc_is']:.4f} OOS={M3_t['auc_oos']:.4f}")
        print(f"    M3 coefs (std): jump={M3_t['coefs'][0]:+.3f} |OFI|={M3_t['coefs'][1]:+.3f} OFI={M3_t['coefs'][2]:+.3f}")
        print(f"    DM M3 vs M1: t={dm_M3_vs_M1['t']:+.3f}")

        tertile_results_ext[tname] = {
            "tertile_idx": t_idx, "status": "ok",
            "n_is": n_is_t, "n_oos": n_oos_t,
            "n_is_jumps": n_jumps_is_t, "n_oos_jumps": n_jumps_oos_t,
            "vix_range": {
                "is_min": float(df_valid.loc[is_t_mask, "vix_lag1"].min()),
                "is_max": float(df_valid.loc[is_t_mask, "vix_lag1"].max()),
                "oos_min": float(df_valid.loc[oos_t_mask, "vix_lag1"].min()) if n_oos_t > 0 else None,
                "oos_max": float(df_valid.loc[oos_t_mask, "vix_lag1"].max()) if n_oos_t > 0 else None,
            },
            "M1": {k: v for k, v in M1_t.items() if k not in ("p_is", "p_oos")},
            "M3": {k: v for k, v in M3_t.items() if k not in ("p_is", "p_oos")},
            "dm_M3_vs_M1": dm_M3_vs_M1,
            # keep in memory for assembled-OOS stitching below
            "_p_oos_M1": M1_t["p_oos"],
            "_p_oos_M3": M3_t["p_oos"],
            "_y_oos": y_oos_t,
            "_oos_indices": np.where(oos_t_mask.values)[0],
        }

    # --------- Step 8: H2 — no-regime base vs extended-IS regime (OOS DM) ---------
    print("\n[Step 8] H2 - OOS DM: extended-IS regime model vs no-regime base")
    # No-regime baseline: single logistic fit on ALL extended IS, predict on OOS
    X_is_base = df_valid.loc[is_mask_ext, FEAT_BASE].values
    y_is_base = df_valid.loc[is_mask_ext, "jump_next"].values.astype(int)
    X_oos_all = df_valid.loc[oos_mask, FEAT_BASE].values
    y_oos_all = df_valid.loc[oos_mask, "jump_next"].values.astype(int)
    M_base_ext = fit_logistic(X_is_base, y_is_base, X_oos_all, y_oos_all, "Base_extIS")
    print(f"  Base (no-regime) IS AUC={M_base_ext['auc_is']:.4f}, OOS AUC={M_base_ext['auc_oos']:.4f}")

    # Stitched regime OOS probabilities (assemble per-tertile M3 predictions to full OOS alignment)
    p_oos_regime_ext = np.full(int(oos_mask.sum()), np.nan)
    oos_indices_relative = np.arange(int(oos_mask.sum()))
    oos_rows_df = df_valid[oos_mask].reset_index(drop=True)
    for t_idx in [0, 1, 2]:
        tname = tertile_names[t_idx]
        r = tertile_results_ext.get(tname, {})
        if r.get("status") != "ok":
            continue
        # within this tertile, relative indices
        rel_idx = np.where(oos_rows_df["vix_tertile_ext"].values == t_idx)[0]
        if len(rel_idx) != len(r["_p_oos_M3"]):
            print(f"  [WARN] {tname}: length mismatch {len(rel_idx)} vs {len(r['_p_oos_M3'])}")
            # fallback: skip
            continue
        p_oos_regime_ext[rel_idx] = r["_p_oos_M3"]

    # For tertiles where no model was fit (or skipped), fall back to base probability
    nan_mask = np.isnan(p_oos_regime_ext)
    if nan_mask.any():
        print(f"  [INFO] {int(nan_mask.sum())} OOS bars have no regime model; filling with base prediction")
        p_oos_regime_ext[nan_mask] = M_base_ext["p_oos"][nan_mask]

    # DM: extended-IS regime vs base (H2)
    dm_h2 = dm_hln_ll(M_base_ext["p_oos"], p_oos_regime_ext, y_oos_all)
    # DM t>0 means regime has higher LL than base; but dm_hln_ll returns t on LL diff (p2-p1),
    # so t>0 => regime better. We want t<=-2 per task brief for "regime beats base" if the
    # direction convention is that lower LOSS => better. Let's check: p1=base, p2=regime.
    # d = ll_regime - ll_base, so positive d => regime wins. Thus t>0 favors regime.
    # Task brief says "DM t <= -2". Let's be careful: if we follow the convention in k1128/k1131
    # where DM t>0 => p2 wins, then H2 PASS is t>=2. However task brief literally says t<=-2.
    # K1131 README used "spline vs tertile: t=-3.94 (reverse)" — so they used the sign where
    # t<0 meant p2 (spline) was WORSE. That matches our dm_hln_ll convention with p1=old, p2=new:
    # so for H2 "new regime model beats base", we want t>=+2.
    # Report BOTH so there's no ambiguity:
    print(f"  DM regime_ext vs base: t={dm_h2['t']:+.3f} (positive => regime wins)")
    print(f"    (convention: t>0 means regime_ext LL > base LL, i.e., regime predicts better)")
    h2_pass = bool(dm_h2["t"] >= 2.0 and abs(dm_h2["t"]) < 1e6)

    # --------- Step 9: H1 — LRT: extended-IS regime joint improvement over base ---------
    print("\n[Step 9] H1 - LRT: extended-IS regime vs no-regime base on IS...")
    # Base: fit on IS, get IS NLL
    nll_base_is = -M_base_ext["ll_is"] * M_base_ext["n_is"]
    # Regime-IS NLL: sum of per-tertile M3 IS NLLs (fit each tertile on IS tertile subset)
    # Each per-tertile M3 was fit on tertile IS; we need IS log-likelihood contributions.
    # Re-derive: for each tertile M3_t, ll_is is mean log-loss * (-1) per obs. Convert to total NLL.
    nll_regime_is = 0.0
    total_is_obs_counted = 0
    for t_idx in [0, 1, 2]:
        tname = tertile_names[t_idx]
        r = tertile_results_ext.get(tname, {})
        if r.get("status") != "ok":
            # If tertile was skipped, we'd use base predictions for that tertile on its IS obs
            # Subset of IS in this tertile that was skipped:
            is_t_mask = is_mask_ext & (df_valid["vix_tertile_ext"] == t_idx)
            y_is_t_sk = df_valid.loc[is_t_mask, "jump_next"].values.astype(int)
            if len(y_is_t_sk) == 0:
                continue
            # Base prediction on these IS obs
            X_is_t_sk = df_valid.loc[is_t_mask, FEAT_BASE].values
            # Transform using base's scaler: we saved scaler_mean/scale
            X_scaled = (X_is_t_sk - np.array(M_base_ext["scaler_mean"])) / np.array(M_base_ext["scaler_scale"])
            z = X_scaled @ np.array(M_base_ext["coefs"]) + M_base_ext["intercept"]
            p_is_fallback = 1.0 / (1.0 + np.exp(-z))
            p_is_fallback = np.clip(p_is_fallback, 1e-7, 1 - 1e-7)
            ll_contrib = (y_is_t_sk * np.log(p_is_fallback) + (1 - y_is_t_sk) * np.log(1 - p_is_fallback)).sum()
            nll_regime_is += -ll_contrib
            total_is_obs_counted += len(y_is_t_sk)
            continue
        # Use M3 IS log-likelihood directly
        ll_mean_per_obs = r["M3"]["ll_is"]  # mean LL per obs (already negative of log_loss but sign: ll_is = -log_loss_scalar; see fit_logistic)
        n_is_t = r["M3"]["n_is"]
        ll_total = ll_mean_per_obs * n_is_t
        nll_regime_is += -ll_total
        total_is_obs_counted += n_is_t

    # LRT statistic
    # df: regime model has 3 tertiles × 4 params (intercept + 3 coefs) = 12; base has 4 params.
    # df diff = 12 - 4 = 8 (but if some tertiles fallback to base, df is lower; we treat those as same as base)
    fitted_tertiles = sum(1 for t in [0, 1, 2] if tertile_results_ext.get(tertile_names[t], {}).get("status") == "ok")
    # For each fitted tertile, we add (4) parameters vs base's (4). Extra = 4 * (fitted - 1) because
    # base already has 1 "intercept + 3 coefs" worth. Alternative: df = (fitted - 1) * 4 + 0 for fallback tertiles.
    # Cleanest: count free params:
    df_regime = fitted_tertiles * 4 + (3 - fitted_tertiles) * 0  # fallback uses base params
    df_base = 4
    df_lrt = max(df_regime - df_base, 1)
    lrt_stat = 2 * (nll_base_is - nll_regime_is)
    lrt_p = float(1.0 - sp_stats.chi2.cdf(max(lrt_stat, 0), df=df_lrt))
    print(f"  NLL base (IS): {nll_base_is:.3f}")
    print(f"  NLL regime (IS, extended): {nll_regime_is:.3f}")
    print(f"  LRT chi²={lrt_stat:.3f}, df={df_lrt}, p={lrt_p:.4f}")

    # K1128 reference LRT: refit K1128 baseline (IS 2017-2019) + per-tertile M3 for comparison
    print("\n  Computing K1128 reference LRT (IS 2017-2019) for comparison...")
    X_is_base_k1128 = df_valid.loc[is_mask_k1128, FEAT_BASE].values
    y_is_base_k1128 = df_valid.loc[is_mask_k1128, "jump_next"].values.astype(int)
    X_oos_all_k1128 = df_valid.loc[oos_mask, FEAT_BASE].values
    M_base_k1128 = fit_logistic(X_is_base_k1128, y_is_base_k1128, X_oos_all_k1128, y_oos_all, "Base_k1128IS")
    nll_base_k1128_is = -M_base_k1128["ll_is"] * M_base_k1128["n_is"]
    print(f"    K1128 base IS AUC={M_base_k1128['auc_is']:.4f}, OOS AUC={M_base_k1128['auc_oos']:.4f}")

    # K1128 per-tertile M3 on K1128 IS
    k1128_tertile_results = {}
    nll_regime_k1128_is = 0.0
    for t_idx in [0, 1, 2]:
        tname = tertile_names[t_idx]
        is_t_mask = is_mask_k1128 & (df_valid["vix_tertile_k1128"] == t_idx)
        oos_t_mask_k1128 = oos_mask & (df_valid["vix_tertile_k1128"] == t_idx)
        n_is_t = int(is_t_mask.sum())
        n_oos_t = int(oos_t_mask_k1128.sum())
        n_jumps_is_t = int(df_valid.loc[is_t_mask, "jump_next"].sum())
        n_jumps_oos_t = int(df_valid.loc[oos_t_mask_k1128, "jump_next"].sum())
        if n_jumps_is_t < 5 or n_jumps_oos_t < 5:
            # fallback to base for this tertile's IS contribution
            y_is_t_sk = df_valid.loc[is_t_mask, "jump_next"].values.astype(int)
            if len(y_is_t_sk) > 0:
                X_is_t_sk = df_valid.loc[is_t_mask, FEAT_BASE].values
                X_scaled = (X_is_t_sk - np.array(M_base_k1128["scaler_mean"])) / np.array(M_base_k1128["scaler_scale"])
                z = X_scaled @ np.array(M_base_k1128["coefs"]) + M_base_k1128["intercept"]
                p_is_fb = 1.0 / (1.0 + np.exp(-z))
                p_is_fb = np.clip(p_is_fb, 1e-7, 1 - 1e-7)
                ll_contrib = (y_is_t_sk * np.log(p_is_fb) + (1 - y_is_t_sk) * np.log(1 - p_is_fb)).sum()
                nll_regime_k1128_is += -ll_contrib
            k1128_tertile_results[tname] = {
                "tertile_idx": t_idx, "status": "skipped_insufficient_jumps",
                "n_is": n_is_t, "n_oos": n_oos_t,
                "n_is_jumps": n_jumps_is_t, "n_oos_jumps": n_jumps_oos_t,
            }
            continue
        X_is_t = df_valid.loc[is_t_mask, FEAT_M3].values
        y_is_t = df_valid.loc[is_t_mask, "jump_next"].values.astype(int)
        X_oos_t = df_valid.loc[oos_t_mask_k1128, FEAT_M3].values
        y_oos_t = df_valid.loc[oos_t_mask_k1128, "jump_next"].values.astype(int)
        try:
            M3_t = fit_logistic(X_is_t, y_is_t, X_oos_t, y_oos_t, f"M3_k1128_{tname}")
        except Exception as e:
            k1128_tertile_results[tname] = {"status": f"error: {e}"}
            continue
        nll_regime_k1128_is += -(M3_t["ll_is"] * M3_t["n_is"])
        k1128_tertile_results[tname] = {
            "tertile_idx": t_idx, "status": "ok",
            "n_is": n_is_t, "n_oos": n_oos_t,
            "n_is_jumps": n_jumps_is_t, "n_oos_jumps": n_jumps_oos_t,
            "M3": {k: v for k, v in M3_t.items() if k not in ("p_is", "p_oos")},
            "_p_oos_M3": M3_t["p_oos"],
            "_oos_tertile_mask_rel": np.where(oos_rows_df["vix_tertile_k1128"].values == t_idx)[0],
        }

    fitted_k1128 = sum(1 for t in [0, 1, 2] if k1128_tertile_results.get(tertile_names[t], {}).get("status") == "ok")
    df_regime_k1128 = fitted_k1128 * 4
    df_lrt_k1128 = max(df_regime_k1128 - 4, 1)
    lrt_k1128 = 2 * (nll_base_k1128_is - nll_regime_k1128_is)
    lrt_p_k1128 = float(1.0 - sp_stats.chi2.cdf(max(lrt_k1128, 0), df=df_lrt_k1128))
    print(f"    K1128 LRT chi²={lrt_k1128:.3f}, df={df_lrt_k1128}, p={lrt_p_k1128:.4f}")

    h1_pass = bool(lrt_stat > lrt_k1128 and lrt_p < 0.05)
    print(f"  H1 PASS (ext LRT > K1128 LRT AND p<0.05): {h1_pass}")

    # --------- Step 10: H3 — Extended IS regime vs K1128 original regime (OOS DM) ---------
    print("\n[Step 10] H3 - Extended IS regime vs K1128 original regime (OOS DM)...")
    # Stitched K1128 OOS regime predictions
    p_oos_regime_k1128 = np.full(int(oos_mask.sum()), np.nan)
    for t_idx in [0, 1, 2]:
        tname = tertile_names[t_idx]
        r = k1128_tertile_results.get(tname, {})
        if r.get("status") != "ok":
            continue
        rel_idx = r["_oos_tertile_mask_rel"]
        if len(rel_idx) != len(r["_p_oos_M3"]):
            continue
        p_oos_regime_k1128[rel_idx] = r["_p_oos_M3"]
    # fallback to K1128 base
    nan_mask_k1128 = np.isnan(p_oos_regime_k1128)
    if nan_mask_k1128.any():
        p_oos_regime_k1128[nan_mask_k1128] = M_base_k1128["p_oos"][nan_mask_k1128]

    dm_h3 = dm_hln_ll(p_oos_regime_k1128, p_oos_regime_ext, y_oos_all)
    print(f"  DM extended_regime vs K1128_regime: t={dm_h3['t']:+.3f} (positive => extended wins)")
    h3_pass = bool(dm_h3["t"] >= 2.0)

    # --------- Step 11: scenario verdict ---------
    print("\n[Step 11] Scenario verdict...")
    if h1_pass and h2_pass and h3_pass and h4_pass:
        scenario = "A"
        implication = "VALIDATED - error_log fix #1 confirmed. Extended IS recovers regime-switching signal."
    elif h1_pass and h2_pass and not h3_pass and h4_pass:
        scenario = "B"
        implication = "PARTIAL - extended IS identifies regime but marginal improvement over K1128 original."
    elif h4_pass and not h2_pass:
        scenario = "C"
        implication = "INVALIDATED (signal) - regime coverage fixed but OFI-jump regime-switching signal not robust."
    elif not h4_pass:
        scenario = "D"
        implication = "INVALIDATED (structural) - extended IS still cannot cover COVID OOS. OFI-jump regime narrative must be abandoned."
    else:
        scenario = "MIXED"
        implication = f"Mixed: H1={h1_pass} H2={h2_pass} H3={h3_pass} H4={h4_pass}. Review each hypothesis individually."

    print(f"  Scenario: {scenario}")
    print(f"  Implication: {implication}")

    # --------- Step 12: plots ---------
    print("\n[Step 12] Plotting...")

    # Plot 1: IS VIX distribution comparison (K1128 vs extended) with tertile cutoffs
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    ax = axes[0]
    ax.hist(vix_is_k1128, bins=40, alpha=0.6, color="steelblue", label=f"K1128 IS 2017-2019 (N={len(vix_is_k1128):,})", density=True)
    ax.hist(vix_is_ext, bins=40, alpha=0.4, color="coral", label=f"K1130 Extended IS 2012-2019 (N={len(vix_is_ext):,})", density=True)
    ax.axvline(cutoff_33_k1128, color="steelblue", linestyle="--", alpha=0.8, label=f"K1128 33%={cutoff_33_k1128:.2f}")
    ax.axvline(cutoff_67_k1128, color="steelblue", linestyle=":", alpha=0.8, label=f"K1128 67%={cutoff_67_k1128:.2f}")
    ax.axvline(cutoff_33_ext, color="coral", linestyle="--", alpha=0.8, label=f"Ext 33%={cutoff_33_ext:.2f}")
    ax.axvline(cutoff_67_ext, color="coral", linestyle=":", alpha=0.8, label=f"Ext 67%={cutoff_67_ext:.2f}")
    ax.set_xlabel("VIX")
    ax.set_ylabel("Density")
    ax.set_title("(a) IS VIX distribution: K1128 vs K1130 extended")
    ax.legend(fontsize=8, loc="upper right")

    ax = axes[1]
    vix_oos = df_valid.loc[oos_mask, "vix_lag1"].values
    ax.hist(vix_oos, bins=40, alpha=0.6, color="seagreen", label=f"OOS 2020-2021 (N={len(vix_oos):,})", density=True)
    ax.axvline(cutoff_33_k1128, color="steelblue", linestyle="--", alpha=0.8)
    ax.axvline(cutoff_67_k1128, color="steelblue", linestyle=":", alpha=0.8)
    ax.axvline(cutoff_33_ext, color="coral", linestyle="--", alpha=0.8)
    ax.axvline(cutoff_67_ext, color="coral", linestyle=":", alpha=0.8)
    ax.text(0.98, 0.95, f"K1128 cutoffs (blue): {cutoff_33_k1128:.2f}/{cutoff_67_k1128:.2f}\nExtended (coral): {cutoff_33_ext:.2f}/{cutoff_67_ext:.2f}",
            transform=ax.transAxes, ha="right", va="top", fontsize=9,
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.8))
    ax.set_xlabel("VIX")
    ax.set_ylabel("Density")
    ax.set_title("(b) OOS VIX distribution w/ both tertile cutoffs")
    ax.legend(fontsize=9)

    plt.suptitle("K1130: IS VIX regime — K1128 (2017-2019) vs Extended (2012-2019)", fontsize=12, y=1.00)
    plt.tight_layout()
    fig_path1 = SCRIPT_DIR / "is_extended_vs_original.png"
    plt.savefig(fig_path1, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {fig_path1}")

    # Plot 2: OOS regime coverage comparison bar chart
    fig, ax = plt.subplots(figsize=(10, 6))
    tnames_plot = ["Low", "Mid", "High"]
    x = np.arange(3)
    w = 0.38
    k1128_pcts = [cov_k1128_pct.get(i, 0) for i in range(3)]
    ext_pcts = [cov_ext_pct.get(i, 0) for i in range(3)]
    ax.bar(x - w/2, k1128_pcts, w, color="steelblue", label="K1128 IS cutoffs (2017-2019)", alpha=0.8)
    ax.bar(x + w/2, ext_pcts, w, color="coral", label="K1130 Extended IS (2012-2019)", alpha=0.8)
    ax.axhline(10, color="red", linestyle="--", alpha=0.5, label="H4 threshold (10%)")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{n}\nVIX tertile" for n in tnames_plot])
    ax.set_ylabel("OOS bar coverage (%)")
    ax.set_title(f"OOS 2020-2021 regime coverage: K1128 vs K1130 extended\n(H4 PASS: {h4_pass})")
    for i, (k1v, extv) in enumerate(zip(k1128_pcts, ext_pcts)):
        ax.text(i - w/2, k1v + 0.8, f"{k1v:.1f}%", ha="center", fontsize=9)
        ax.text(i + w/2, extv + 0.8, f"{extv:.1f}%", ha="center", fontsize=9)
    ax.legend()
    plt.tight_layout()
    fig_path2 = SCRIPT_DIR / "oos_regime_coverage.png"
    plt.savefig(fig_path2, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {fig_path2}")

    # --------- Step 13: save results JSON ---------
    runtime = (datetime.now() - t0).total_seconds()
    print(f"\n[Step 13] Saving results (runtime={runtime:.1f}s)...")

    # strip in-memory arrays from saved structures
    def strip_arrays(d):
        if isinstance(d, dict):
            return {k: strip_arrays(v) for k, v in d.items() if not k.startswith("_")}
        return d

    results = {
        "experiment_id": "K1130",
        "title": "Extended IS 2012-2019 for K1128 OFI-jump regime test (error_log fix #1)",
        "timestamp": datetime.now().isoformat(),
        "data_source": "TAIFEX TX futures 5-min bars 2012-2021 (rebuilt cache this experiment)",
        "period_IS_extended": "2012-01-01..2019-12-31 (8 years)",
        "period_IS_k1128_reference": "2017-01-01..2019-12-31 (3 years)",
        "period_OOS": "2020-01-01..2021-12-31",
        "vix_source": "yfinance ^VIX daily close, T-1 lag (Taiwan prev-US-close rule)",
        "n_bars_total": int(len(df)),
        "n_valid": int(len(df_valid)),
        "n_is_extended": int(is_mask_ext.sum()),
        "n_is_k1128": int(is_mask_k1128.sum()),
        "n_oos": int(oos_mask.sum()),
        "jump_detection": {
            "method": "Lee-Mykland (2008) L_t=|r|/sigma with rolling BV K=16 strictly past",
            "K_window": K_WIN,
            "alpha": JUMP_ALPHA,
            "threshold_Gumbel": float(thresh_multi),
            "n_jumps": int(n_jump),
            "jump_rate_pct": float(n_jump / n_valid_global * 100),
        },
        "vix_tertile_cutoffs": {
            "extended_IS_2012_2019": {
                "cutoff_33": cutoff_33_ext,
                "cutoff_67": cutoff_67_ext,
                "min": float(vix_is_ext.min()),
                "mean": float(vix_is_ext.mean()),
                "std": float(vix_is_ext.std()),
                "max": float(vix_is_ext.max()),
            },
            "k1128_IS_2017_2019": {
                "cutoff_33": cutoff_33_k1128,
                "cutoff_67": cutoff_67_k1128,
                "min": float(vix_is_k1128.min()),
                "mean": float(vix_is_k1128.mean()),
                "std": float(vix_is_k1128.std()),
                "max": float(vix_is_k1128.max()),
            },
        },
        "oos_regime_coverage": {
            "k1128_cutoffs_pct": cov_k1128_pct,
            "extended_cutoffs_pct": cov_ext_pct,
            "n_oos": n_oos,
            "min_coverage_pct_extended": float(min_coverage_pct_ext),
            "H4_threshold_pct": 10.0,
            "H4_pass": h4_pass,
        },
        "per_tertile_extended": strip_arrays(tertile_results_ext),
        "per_tertile_k1128": strip_arrays(k1128_tertile_results),
        "base_extended_IS": {k: v for k, v in M_base_ext.items() if k not in ("p_is", "p_oos")},
        "base_k1128_IS": {k: v for k, v in M_base_k1128.items() if k not in ("p_is", "p_oos")},
        "H1_LRT": {
            "nll_base_extIS": float(nll_base_is),
            "nll_regime_extIS": float(nll_regime_is),
            "lrt_chi2_ext": float(lrt_stat),
            "df_ext": int(df_lrt),
            "p_ext": lrt_p,
            "nll_base_k1128IS": float(nll_base_k1128_is),
            "nll_regime_k1128IS": float(nll_regime_k1128_is),
            "lrt_chi2_k1128": float(lrt_k1128),
            "df_k1128": int(df_lrt_k1128),
            "p_k1128": lrt_p_k1128,
            "pass": h1_pass,
            "note": "PASS if extended LRT > K1128 LRT AND p_ext < 0.05",
        },
        "H2_OOS_DM_ext_regime_vs_base": {
            "t": dm_h2["t"],
            "t_plain": dm_h2.get("t_plain"),
            "mean_d": dm_h2["mean_d"],
            "n": dm_h2["n"],
            "pass": h2_pass,
            "note": "convention: positive t => regime beats base in OOS LL. PASS if t>=+2.0.",
        },
        "H3_OOS_DM_ext_vs_k1128": {
            "t": dm_h3["t"],
            "t_plain": dm_h3.get("t_plain"),
            "mean_d": dm_h3["mean_d"],
            "n": dm_h3["n"],
            "pass": h3_pass,
            "note": "convention: positive t => extended beats K1128 in OOS LL. PASS if t>=+2.0.",
        },
        "H4_oos_coverage_min_10pct": h4_pass,
        "scenario": scenario,
        "implication_error_log_fix_1": implication,
        "seed": 42,
        "runtime_sec": runtime,
        "references": [
            "Lee & Mykland (2008) RFS 21(6), 2535-2563",
            "Cont, Kukanov, Stoikov (2014) JFE 12(1), 47-88",
            "Harvey, Leybourne, Newbold (1997) IJF 13(2), 281-291",
            "K1128 (this project): original VIX tertile regime split",
            "K1131 (this project): natural cubic spline rescue (NULL)",
            "error_log.md 2026-04-13 entry: IS-regime degeneracy on COVID OOS",
        ],
    }

    out_path = SCRIPT_DIR / "k1130_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  Saved: {out_path}")

    # --------- Step 14: final summary ---------
    print("\n" + "=" * 70)
    print("K1130 SUMMARY")
    print("=" * 70)
    print(f"\nIS extended 2012-2019: N={int(is_mask_ext.sum()):,}, VIX range={vix_is_ext.min():.2f}-{vix_is_ext.max():.2f}")
    print(f"IS K1128 2017-2019:    N={int(is_mask_k1128.sum()):,}, VIX range={vix_is_k1128.min():.2f}-{vix_is_k1128.max():.2f}")
    print(f"OOS 2020-2021:         N={int(oos_mask.sum()):,}, VIX range={vix_oos.min():.2f}-{vix_oos.max():.2f}")
    print(f"\nExtended cutoffs: 33%={cutoff_33_ext:.3f}, 67%={cutoff_67_ext:.3f}")
    print(f"K1128 cutoffs:    33%={cutoff_33_k1128:.3f}, 67%={cutoff_67_k1128:.3f}")
    print(f"\nOOS regime coverage:")
    print(f"  K1128: low={cov_k1128_pct.get(0,0):.2f}% mid={cov_k1128_pct.get(1,0):.2f}% high={cov_k1128_pct.get(2,0):.2f}%")
    print(f"  Ext:   low={cov_ext_pct.get(0,0):.2f}% mid={cov_ext_pct.get(1,0):.2f}% high={cov_ext_pct.get(2,0):.2f}%")
    print(f"\nHypotheses:")
    print(f"  H1 (LRT ext > K1128 AND p<0.05): {h1_pass}")
    print(f"       ext  chi²={lrt_stat:.3f}, df={df_lrt}, p={lrt_p:.4f}")
    print(f"       K1128 chi²={lrt_k1128:.3f}, df={df_lrt_k1128}, p={lrt_p_k1128:.4f}")
    print(f"  H2 (OOS DM ext_regime > base, t>=+2): {h2_pass}")
    print(f"       t={dm_h2['t']:+.3f}")
    print(f"  H3 (OOS DM ext > K1128, t>=+2): {h3_pass}")
    print(f"       t={dm_h3['t']:+.3f}")
    print(f"  H4 (min OOS coverage >= 10%): {h4_pass}")
    print(f"       min={min_coverage_pct_ext:.2f}%")
    print(f"\nScenario: {scenario}")
    print(f"Implication: {implication}")

    return results


if __name__ == "__main__":
    main()
