"""
K1062: Re-run K1059 with T+1 Event Window — Does 0050.TW ETF Show EAV Too?
==========================================================================

Research Questions (H1 vs H2):
- H1 (pure timing): K1059 looked at the wrong day. Using T+1 window, 0050.TW
  ETF will show EAV, since Taiwan earnings are typically announced AFTER market
  close → the vol shock propagates to the NEXT trading day.
- H2 (diversification wash-out): Individual-stock EAV exists but index-level
  ETF diversification washes it out, so even with T+1 ETF ratio ≈ 1.

Background:
- K1059 (T+0, 0050.TW): ratio = 1.007 (NULL), t = 0.018, p = 0.986
  BUT already showed offset +1 ratio = 1.313 — unexamined at the time.
- K1060 (T+1, individual stocks): mean ratio = 1.466, t = 2.075, p = 0.034
  9/10 stocks T+1 > T+0. Mechanism: Taiwan earnings → after close → T+1.

Data:
- 財報公告日.txt (Big5, parsed in K1059/K1060)
- 0050.TW (yfinance; apply volpred.utils.clean_tw50_data — 2014 split)
- ^VIX (yfinance)
- K1058 A4f/GJR implementation is re-used for Part D (custom MLE)

Parts:
  A. TSMC single-firm ETF-level EAV across 6 event windows (incl. T+1, T+2).
  B. Clustering × T+1: dense announce days → next-day 0050.TW vol.
  C. Multi-firm T+1 aggregation OLS: vol[T+1] = α + β·n_announce[T+0] + γ·VIX.
  D. A4f vs GJR QLIKE / DM conditional on T+0, T+1, non-event.

Error-log notes followed:
- 0050.TW must use clean_tw50_data (K928/K933).
- K1016: all numbers in article/README must match the JSON.
- K1060 lesson: Taiwan earnings post-close → T+1 is the correct window.
- K1059 lesson: report DOES show offset +1 ≈ 1.31 — this experiment quantifies it.
- Random seed = 42 everywhere.

Outputs:
  experiments/k1062/k1062_results.json
  experiments/k1062/k1062_window_comparison.png
  experiments/k1062/k1062_clustering_t1.png
  experiments/k1062/k1062_a4f_conditional.png
  experiments/k1062/README.md (generated separately)
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import optimize, stats

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_FILE = PROJECT_ROOT / "財報公告日.txt"
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from volpred.utils import clean_tw50_data  # noqa: E402

warnings.filterwarnings("ignore")
np.random.seed(42)
RNG = np.random.default_rng(42)
START_TIME = time.time()

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
START_DATE = "2003-06-30"
END_DATE = "2025-12-31"
OOS_START = "2010-01-01"
WINDOW = 2000
REFIT_EVERY = 63  # quarterly (matches K1058/K1059)
BOOTSTRAP_REPS = 5000
EVENT_HALF = 5     # ±5-day window for curve charts / non-event exclusion

# Windows we test in Part A. Each entry: (label, offsets) where offsets is a
# list of integer offsets relative to the mapped announce date (0 = day the
# announcement reaches the market = T+0 trading day).
WINDOWS: dict[str, list[int]] = {
    "T+0 only":           [0],
    "T+1 only":           [1],
    "T+2 only":           [2],
    "[-5, -1] pre-event": [-5, -4, -3, -2, -1],
    "[+1, +5] post-event": [1, 2, 3, 4, 5],
    "[T+1, T+3] window":  [1, 2, 3],
}

print("=" * 72)
print("K1062: T+1 event-window re-run of K1059 (0050.TW EAV)")
print("=" * 72)

# --------------------------------------------------------------------------
# Part 0: Load earnings announcement data
# --------------------------------------------------------------------------
print("\n[Part 0] Loading earnings announcement data (Big5)...")
with open(DATA_FILE, "rb") as f:
    raw_text = f.read().decode("big5", errors="replace")

records = []
for line in raw_text.strip().split("\n")[1:]:
    parts = line.strip().split("\t")
    if len(parts) >= 4:
        code = parts[0].strip()
        name = parts[1].strip()
        ym = parts[2].strip()
        date_str = parts[3].strip()
        if date_str:
            try:
                dt = pd.Timestamp(date_str.replace("/", "-"))
                records.append(
                    {"code": code, "name": name, "ym": ym, "announce_date": dt}
                )
            except Exception:
                pass

ea_df = pd.DataFrame(records)
print(f"  Total announcement records parsed: {len(ea_df):,}")
print(f"  Unique companies: {ea_df['code'].nunique():,}")
tsmc_df = ea_df[ea_df["code"] == "2330"].sort_values("announce_date")
print(f"  TSMC (2330) announcements: {len(tsmc_df)}")

# --------------------------------------------------------------------------
# Part 1: Load 0050.TW and VIX data
# --------------------------------------------------------------------------
print("\n[Part 1] Downloading 0050.TW and VIX (yfinance)...")
import yfinance as yf  # noqa: E402

tw50_raw = yf.download(
    "0050.TW", start=START_DATE, end=END_DATE, auto_adjust=True, progress=False
)
if isinstance(tw50_raw.columns, pd.MultiIndex):
    tw50_raw.columns = tw50_raw.columns.get_level_values(0)
tw50_raw.index = tw50_raw.index.tz_localize(None)

prices_clean, _ = clean_tw50_data(tw50_raw["Close"])
log_ret = np.log(prices_clean / prices_clean.shift(1))

vix_raw = yf.download("^VIX", start=START_DATE, end=END_DATE, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_raw.index = vix_raw.index.tz_localize(None)
vix_close = vix_raw["Close"].copy()

vix_ffill = vix_close.reindex(prices_clean.index, method="ffill")
df = pd.DataFrame({"log_ret": log_ret, "VIX": vix_ffill}).dropna()

# Safety filter (K1059 convention)
max_abs = df["log_ret"].abs().max()
if max_abs > 0.3:
    print(f"  WARNING: Max |return| = {max_abs:.4f}; clipping > 0.3.")
    df = df[df["log_ret"].abs() <= 0.3]

ret = df["log_ret"].values
vix = df["VIX"].values
r2 = ret ** 2
trading_dates = df.index
n_total = len(df)
print(
    f"  0050.TW: {trading_dates[0].date()} ~ {trading_dates[-1].date()}"
    f" | N = {n_total:,} trading days | mean r^2 = {r2.mean()*1e4:.2f} bp"
)

# --------------------------------------------------------------------------
# Part A: TSMC event-window comparison across 6 windows
# --------------------------------------------------------------------------
print("\n[Part A] TSMC single-firm EAV across 6 event windows ...")


def map_to_trading_day(ann_dates: pd.Series) -> pd.DatetimeIndex:
    """Map a calendar announce date to the next available trading day.

    Taiwan listed firms typically disclose earnings after the close, so this
    routine maps calendar date d → first trading day >= d. That trading day is
    labeled T+0 (the day the market first has to re-price given the news).
    """
    out = []
    for d in ann_dates:
        d_ts = pd.Timestamp(d)
        if d_ts < trading_dates[0] or d_ts > trading_dates[-1]:
            continue
        pos = trading_dates.searchsorted(d_ts)
        if pos < len(trading_dates):
            out.append(trading_dates[pos])
    return pd.DatetimeIndex(sorted(set(out)))


tsmc_t0 = map_to_trading_day(tsmc_df["announce_date"].values)
print(f"  TSMC events mapped to trading days: {len(tsmc_t0)}")

# Build positional index for each mapped event date.
t0_positions = np.array([trading_dates.get_loc(d) for d in tsmc_t0])


def bootstrap_ratio(event_r2: np.ndarray, non_event_r2: np.ndarray,
                    reps: int = BOOTSTRAP_REPS, seed: int = 42) -> dict:
    rng = np.random.default_rng(seed)
    if len(event_r2) < 5 or len(non_event_r2) < 100:
        return {"ci_low": None, "ci_high": None, "p_le_1": None}
    ratios = []
    for _ in range(reps):
        s1 = rng.choice(event_r2, size=len(event_r2), replace=True)
        s2 = rng.choice(non_event_r2, size=len(non_event_r2), replace=True)
        m2 = s2.mean()
        if m2 > 0:
            ratios.append(s1.mean() / m2)
    arr = np.array(ratios)
    return {
        "ci_low": float(np.percentile(arr, 2.5)),
        "ci_high": float(np.percentile(arr, 97.5)),
        "p_le_1": float((arr <= 1.0).mean()),  # one-sided null: ratio <= 1
    }


window_results: dict[str, dict] = {}

# Non-event mask shared across windows: exclude ±EVENT_HALF around every T+0.
exclusion = set()
for pos in t0_positions:
    for k in range(-EVENT_HALF, EVENT_HALF + 1):
        if 0 <= pos + k < n_total:
            exclusion.add(int(pos + k))
non_event_mask = np.ones(n_total, dtype=bool)
for idx in exclusion:
    non_event_mask[idx] = False
non_event_r2 = r2[non_event_mask]
nonevent_mean = float(non_event_r2.mean())
print(
    f"  Non-event sample (excluding ±{EVENT_HALF}d around each TSMC event): "
    f"n = {non_event_r2.size}, mean r^2 = {nonevent_mean*1e4:.2f} bp"
)

print("\n  window                    n_days  mean_r2(bp)  ratio  t_stat  p_val  boot_ci")
print("  " + "-" * 84)
for label, offsets in WINDOWS.items():
    idxs = []
    for pos in t0_positions:
        for off in offsets:
            j = pos + off
            if 0 <= j < n_total:
                idxs.append(int(j))
    idxs = sorted(set(idxs))
    event_r2 = r2[idxs]
    n_evt = len(event_r2)
    event_mean = float(event_r2.mean()) if n_evt else float("nan")
    ratio = event_mean / nonevent_mean if nonevent_mean else float("nan")
    if n_evt >= 5:
        t_stat, p_val = stats.ttest_ind(event_r2, non_event_r2, equal_var=False)
    else:
        t_stat, p_val = float("nan"), float("nan")
    boot = bootstrap_ratio(event_r2, non_event_r2)
    window_results[label] = {
        "offsets": offsets,
        "n_event_days": int(n_evt),
        "event_mean_r2_bp": event_mean * 1e4,
        "nonevent_mean_r2_bp": nonevent_mean * 1e4,
        "ratio": float(ratio),
        "t_stat": float(t_stat) if not np.isnan(t_stat) else None,
        "p_value_two_sided": float(p_val) if not np.isnan(p_val) else None,
        "bootstrap_ci_low": boot["ci_low"],
        "bootstrap_ci_high": boot["ci_high"],
        "bootstrap_p_le_1": boot["p_le_1"],
    }
    ci_str = (
        f"[{boot['ci_low']:.3f}, {boot['ci_high']:.3f}]"
        if boot["ci_low"] is not None
        else "n/a"
    )
    t_str = f"{t_stat:+.3f}" if not np.isnan(t_stat) else "  n/a"
    p_str = f"{p_val:.4f}" if not np.isnan(p_val) else "  n/a"
    print(
        f"  {label:<24}  {n_evt:5d}   {event_mean*1e4:7.3f}   "
        f"{ratio:5.3f}  {t_str}  {p_str}  {ci_str}"
    )

# Identify best window (highest ratio, positive) for narrative.
best_label = max(
    window_results.keys(), key=lambda k: window_results[k]["ratio"]
)
best = window_results[best_label]

# --------------------------------------------------------------------------
# Part B: Clustering × T+1
# --------------------------------------------------------------------------
print("\n[Part B] Clustering × T+1 (dense T+0 → next-day 0050.TW vol)...")

daily_count = (
    ea_df.groupby("announce_date").size().rename("n_announce")
)
daily_count.index = pd.to_datetime(daily_count.index)

# Align on trading calendar: if announcement fell on a non-trading day, shift
# forward to the next trading day (same rule as map_to_trading_day).
mapped_counts = pd.Series(0.0, index=trading_dates)
for d, n in daily_count.items():
    pos = trading_dates.searchsorted(pd.Timestamp(d))
    if pos < len(trading_dates):
        mapped_counts.iloc[pos] += n
mapped_counts = mapped_counts.astype(int)

nonzero = mapped_counts[mapped_counts > 0]
threshold_90 = int(nonzero.quantile(0.9))
print(
    f"  Days with at least one announce: {len(nonzero)} | "
    f"mean = {nonzero.mean():.1f}, max = {nonzero.max()}, "
    f"90th pct = {threshold_90}"
)

combined = pd.DataFrame(
    {"r2": r2, "VIX": vix, "n_announce": mapped_counts.values},
    index=trading_dates,
)
combined["r2_next"] = combined["r2"].shift(-1)  # T+1 vol

dense_mask = combined["n_announce"] >= threshold_90
any_mask = combined["n_announce"] > 0
none_mask = combined["n_announce"] == 0

vol_dense_t0 = combined.loc[dense_mask, "r2"].dropna().values
vol_dense_t1 = combined.loc[dense_mask, "r2_next"].dropna().values
vol_any_t0 = combined.loc[any_mask, "r2"].dropna().values
vol_any_t1 = combined.loc[any_mask, "r2_next"].dropna().values
vol_none = combined.loc[none_mask, "r2"].dropna().values

# K1059 replication (T+0)
t_t0, p_t0 = stats.ttest_ind(vol_dense_t0, vol_none, equal_var=False)

# H1 test (T+1): dense T+0 → next-day vol
t_t1, p_t1 = stats.ttest_ind(vol_dense_t1, vol_none, equal_var=False)

# Any-vs-none (T+1)
t_any_t1, p_any_t1 = stats.ttest_ind(vol_any_t1, vol_none, equal_var=False)

clustering = {
    "threshold_90": threshold_90,
    "n_dense_days": int(dense_mask.sum()),
    "n_any_announce_days": int(any_mask.sum()),
    "n_none_days": int(none_mask.sum()),
    "T0": {
        "dense_r2_bp": float(vol_dense_t0.mean() * 1e4),
        "none_r2_bp":  float(vol_none.mean() * 1e4),
        "ratio":       float(vol_dense_t0.mean() / vol_none.mean()),
        "t_stat":      float(t_t0),
        "p_value":     float(p_t0),
    },
    "T1": {
        "dense_r2_bp": float(vol_dense_t1.mean() * 1e4),
        "any_r2_bp":   float(vol_any_t1.mean() * 1e4),
        "none_r2_bp":  float(vol_none.mean() * 1e4),
        "ratio_dense": float(vol_dense_t1.mean() / vol_none.mean()),
        "ratio_any":   float(vol_any_t1.mean() / vol_none.mean()),
        "t_dense_vs_none": float(t_t1),
        "p_dense_vs_none": float(p_t1),
        "t_any_vs_none":   float(t_any_t1),
        "p_any_vs_none":   float(p_any_t1),
    },
}
print(
    f"  T+0 dense vs none: {clustering['T0']['dense_r2_bp']:.2f} vs "
    f"{clustering['T0']['none_r2_bp']:.2f} bp, ratio = "
    f"{clustering['T0']['ratio']:.3f}, t = {t_t0:+.3f}, p = {p_t0:.4f}"
)
print(
    f"  T+1 dense vs none: {clustering['T1']['dense_r2_bp']:.2f} vs "
    f"{clustering['T1']['none_r2_bp']:.2f} bp, ratio_dense = "
    f"{clustering['T1']['ratio_dense']:.3f}, t = {t_t1:+.3f}, p = {p_t1:.4f}"
)
print(
    f"  T+1 any vs none:   {clustering['T1']['any_r2_bp']:.2f} vs "
    f"{clustering['T1']['none_r2_bp']:.2f} bp, ratio_any = "
    f"{clustering['T1']['ratio_any']:.3f}, t = {t_any_t1:+.3f}, "
    f"p = {p_any_t1:.4f}"
)

# --------------------------------------------------------------------------
# Part C: Multi-firm T+1 OLS
# --------------------------------------------------------------------------
print("\n[Part C] OLS: vol[T+1] = α + β·n_announce[T+0] + γ·VIX[T+0] + ε ...")

reg_df = combined.dropna(subset=["r2_next"]).copy()
Y = reg_df["r2_next"].values * 1e4  # bp
X = np.column_stack(
    [np.ones(len(reg_df)), reg_df["n_announce"].values, reg_df["VIX"].values]
)
mask = ~np.isnan(Y) & ~np.isnan(X).any(axis=1)
Y_c, X_c = Y[mask], X[mask]
beta, *_ = np.linalg.lstsq(X_c, Y_c, rcond=None)
residuals = Y_c - X_c @ beta
dof = len(Y_c) - X_c.shape[1]
sigma2 = np.sum(residuals ** 2) / dof
se = np.sqrt(np.diag(sigma2 * np.linalg.inv(X_c.T @ X_c)))
t_vals = beta / se
R2 = 1 - np.sum(residuals ** 2) / np.sum((Y_c - Y_c.mean()) ** 2)

ols_t1 = {
    "n_obs": int(mask.sum()),
    "alpha":   {"coef": float(beta[0]), "t": float(t_vals[0])},
    "beta_n":  {"coef": float(beta[1]), "t": float(t_vals[1])},
    "gamma_vix": {"coef": float(beta[2]), "t": float(t_vals[2])},
    "R2": float(R2),
}
print(
    f"  N={ols_t1['n_obs']}, R²={R2:.4f} | "
    f"α={beta[0]:+.4f}(t={t_vals[0]:+.2f}) | "
    f"β_n={beta[1]:+.4f}(t={t_vals[1]:+.2f}) | "
    f"γ_VIX={beta[2]:+.4f}(t={t_vals[2]:+.2f})"
)

# Reference: K1059 Part B used T+0 with β = -0.46 (NS).
# We also replicate T+0 here so the comparison is explicit.
Y0 = reg_df["r2"].values * 1e4
mask0 = ~np.isnan(Y0) & ~np.isnan(X).any(axis=1)
Y0c, X0c = Y0[mask0], X[mask0]
beta0, *_ = np.linalg.lstsq(X0c, Y0c, rcond=None)
resid0 = Y0c - X0c @ beta0
sigma2_0 = np.sum(resid0 ** 2) / (len(Y0c) - 3)
se0 = np.sqrt(np.diag(sigma2_0 * np.linalg.inv(X0c.T @ X0c)))
t0_vals = beta0 / se0
R2_0 = 1 - np.sum(resid0 ** 2) / np.sum((Y0c - Y0c.mean()) ** 2)
ols_t0 = {
    "n_obs": int(mask0.sum()),
    "alpha":     {"coef": float(beta0[0]), "t": float(t0_vals[0])},
    "beta_n":    {"coef": float(beta0[1]), "t": float(t0_vals[1])},
    "gamma_vix": {"coef": float(beta0[2]), "t": float(t0_vals[2])},
    "R2": float(R2_0),
}
print(
    f"  [T+0 replicate] N={ols_t0['n_obs']}, R²={R2_0:.4f} | "
    f"β_n(T+0)={beta0[1]:+.4f}(t={t0_vals[1]:+.2f})  "
    f"[K1059 Part B reported β=-0.46 NS]"
)

# --------------------------------------------------------------------------
# Part D: A4f vs GJR conditional on T+0 / T+1 / non-event
# --------------------------------------------------------------------------
print("\n[Part D] A4f vs GJR OOS forecasts, conditional on event timing...")


def gjr_negll(params, returns):
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns[: min(250, n)])
    ll = 0.0
    for t in range(1, n):
        asym = gamma * returns[t - 1] ** 2 if returns[t - 1] < 0 else 0.0
        h[t] = omega + alpha * returns[t - 1] ** 2 + asym + beta * h[t - 1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + returns[t] ** 2 / h[t])
    return -ll


def fit_gjr(returns):
    var0 = np.var(returns)
    best_ll, best = np.inf, None
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, 0.03, 0.08, 0.88],
        [var0 * 0.10, 0.08, 0.10, 0.80],
    ]
    bounds = [(1e-8, var0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    for s in starts:
        try:
            res = optimize.minimize(
                gjr_negll, s, args=(returns,), method="L-BFGS-B", bounds=bounds
            )
            if res.fun < best_ll:
                best_ll, best = res.fun, res.x
        except Exception:
            continue
    return best


def gjr_step(params, h_prev, r_prev):
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev ** 2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev ** 2 + asym + beta * h_prev, 1e-10)


def fit_a4f(returns, vix_vals):
    n = len(returns)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]

    def neg_ll(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        tau = np.maximum(theta0 + theta1 * vix_lag ** 2, 1e-16)
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10
        eg = omega_g / (1.0 - persist)
        g = np.empty(n)
        g[0] = eg
        for t in range(1, n):
            u_prev = returns[t - 1] / np.sqrt(tau[t])
            asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev ** 2 + asym + beta * g[t - 1]
            if g[t] < 1e-10:
                g[t] = 1e-10
        ll = 0.0
        for t in range(n):
            s2 = tau[t] * g[t]
            if s2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(s2) + returns[t] ** 2 / s2)
        return -ll

    var0 = np.var(returns)
    vix2m = np.mean(vix_lag ** 2) + 1e-8
    best_ll, best = np.inf, None
    starts = [
        [var0 * 0.1,  var0 / vix2m,        0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2m * 0.5,  0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2,  var0 / vix2m * 1.5,  0.02, 0.08, 0.10, 0.80],
        [var0 * 0.01, var0 / vix2m * 2.0,  0.08, 0.04, 0.06, 0.85],
    ]
    bounds = [
        (-1e-2, 1e-2), (1e-8, 1e-3), (1e-6, 1.0),
        (1e-4, 0.3),   (1e-4, 0.3),  (0.5, 0.999),
    ]
    for s in starts:
        try:
            res = optimize.minimize(
                neg_ll, s, method="L-BFGS-B", bounds=bounds,
                options={"maxiter": 500},
            )
            if res.fun < best_ll:
                best_ll, best = res.fun, res.x
        except Exception:
            continue
    return best


oos_mask = df.index >= OOS_START
oos_indices = np.where(oos_mask)[0]
n_oos = len(oos_indices)
print(
    f"  OOS: {df.index[oos_mask][0].date()} ~ {df.index[oos_mask][-1].date()} "
    f"(N = {n_oos}); WINDOW = {WINDOW}, refit every {REFIT_EVERY} days."
)

gjr_fc = np.full(n_oos, np.nan)
a4f_fc = np.full(n_oos, np.nan)
gjr_params = a4f_params = None
gjr_h = a4f_g = None
refit_count = 0

for t_idx, abs_idx in enumerate(oos_indices):
    if t_idx % 500 == 0:
        print(f"    step {t_idx}/{n_oos} (elapsed {time.time()-START_TIME:.0f}s)")
    refit = (t_idx % REFIT_EVERY == 0) or (t_idx == 0)
    if refit:
        refit_count += 1
        train_start = max(0, abs_idx - WINDOW)
        tr_ret = ret[train_start:abs_idx]
        tr_vix = vix[train_start:abs_idx]
        gjr_params = fit_gjr(tr_ret)
        if gjr_params is not None:
            h = np.var(tr_ret)
            for i in range(1, len(tr_ret)):
                h = gjr_step(gjr_params, h, tr_ret[i - 1])
            gjr_h = h
        a4f_params = fit_a4f(tr_ret, tr_vix)
        if a4f_params is not None:
            theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = a4f_params
            n_tr = len(tr_ret)
            vix_lag_tr = np.empty(n_tr)
            vix_lag_tr[0] = tr_vix[0]
            vix_lag_tr[1:] = tr_vix[:-1]
            tau_tr = np.maximum(theta0 + theta1 * vix_lag_tr ** 2, 1e-16)
            persist = alpha_p + gamma_p / 2.0 + beta_p
            g = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
            for i in range(1, n_tr):
                u_prev = tr_ret[i - 1] / np.sqrt(tau_tr[i])
                asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
                g = omega_g + alpha_p * u_prev ** 2 + asym + beta_p * g
                g = max(g, 1e-10)
            a4f_g = g

    if gjr_params is not None:
        h_new = gjr_step(gjr_params, gjr_h, ret[abs_idx - 1])
        gjr_fc[t_idx] = h_new
        gjr_h = h_new

    if a4f_params is not None:
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = a4f_params
        v_lag = vix[abs_idx - 1]
        tau_t = max(theta0 + theta1 * v_lag ** 2, 1e-16)
        r_prev = ret[abs_idx - 1]
        u_prev = r_prev / np.sqrt(tau_t)
        asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev ** 2 + asym + beta_p * a4f_g
        g_new = max(g_new, 1e-10)
        a4f_fc[t_idx] = tau_t * g_new
        a4f_g = g_new

print(f"  Forecasting done: {refit_count} refits in {time.time()-START_TIME:.0f}s")

oos_r2 = r2[oos_mask]
oos_dates = df.index[oos_mask]
valid = (~np.isnan(gjr_fc)) & (~np.isnan(a4f_fc)) & (gjr_fc > 0) & (a4f_fc > 0)
print(f"  Valid forecast rows: {int(valid.sum())} / {n_oos}")

gjr_v = gjr_fc[valid]
a4f_v = a4f_fc[valid]
r2_v = oos_r2[valid]
dates_v = oos_dates[valid]


def qlike(actual: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    a = np.maximum(actual, 1e-12)
    f = np.maximum(forecast, 1e-12)
    ratio = a / f
    return ratio - np.log(ratio) - 1.0


gjr_ql = qlike(r2_v, gjr_v)
a4f_ql = qlike(r2_v, a4f_v)

# Conditional groups
t0_set = set(tsmc_t0)
# T+1 set: one trading day after each TSMC T+0 event.
t1_dates_all = []
for pos in t0_positions:
    if pos + 1 < n_total:
        t1_dates_all.append(trading_dates[pos + 1])
t1_set = set(t1_dates_all)

is_t0 = np.array([d in t0_set for d in dates_v])
is_t1 = np.array([d in t1_set for d in dates_v])
is_non_event = ~(is_t0 | is_t1)


def dm_block(a: np.ndarray, b: np.ndarray, label: str) -> dict:
    d = a - b   # a = GJR, b = A4f
    if len(d) < 5:
        return {"n": int(len(d)), "dm_t": None, "dm_p": None,
                "gjr_qlike": None, "a4f_qlike": None, "diff": None}
    dm_t = d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))
    dm_p = 2 * (1 - stats.norm.cdf(abs(dm_t)))
    return {
        "n": int(len(d)),
        "gjr_qlike": float(a.mean()),
        "a4f_qlike": float(b.mean()),
        "diff": float(d.mean()),
        "dm_t": float(dm_t),
        "dm_p": float(dm_p),
        "label": label,
    }


cond = {
    "overall":   dm_block(gjr_ql,             a4f_ql,             "overall"),
    "t0":        dm_block(gjr_ql[is_t0],      a4f_ql[is_t0],      "t0"),
    "t1":        dm_block(gjr_ql[is_t1],      a4f_ql[is_t1],      "t1"),
    "non_event": dm_block(gjr_ql[is_non_event], a4f_ql[is_non_event], "non_event"),
}

for k, b in cond.items():
    if b["dm_t"] is not None:
        print(
            f"  {k:<10}  N={b['n']:5d}  GJR={b['gjr_qlike']:.5f}  "
            f"A4f={b['a4f_qlike']:.5f}  diff={b['diff']:+.5f}  "
            f"DM t={b['dm_t']:+.3f} (p={b['dm_p']:.4f})"
        )
    else:
        print(f"  {k:<10}  N={b['n']} — insufficient sample.")

# --------------------------------------------------------------------------
# Hypothesis verdict
# --------------------------------------------------------------------------
print("\n[Verdict] H1 (timing) vs H2 (diversification wash-out)...")

t1_res = window_results["T+1 only"]
t0_res = window_results["T+0 only"]

# H1 support: T+1 ratio > 1 AND either (a) two-sided p < 0.10, or
# (b) bootstrap p(ratio≤1) < 0.10. We also require T+1 ratio > T+0 ratio.
h1_a = t1_res["ratio"] > 1.0
h1_b = t1_res["ratio"] > t0_res["ratio"]
h1_c = (t1_res["p_value_two_sided"] is not None
        and t1_res["p_value_two_sided"] < 0.10) \
       or (t1_res["bootstrap_p_le_1"] is not None
           and t1_res["bootstrap_p_le_1"] < 0.10)

if h1_a and h1_b and h1_c:
    verdict = "H1 SUPPORTED (pure timing): T+1 ETF EAV is present; K1059 saw the wrong day."
elif h1_a and h1_b:
    verdict = ("H1 PARTIAL: T+1 ratio > 1 and > T+0, but statistical evidence "
               "is weak — consistent with diversified ETF dilution on top of the timing shift.")
else:
    verdict = ("H2 SUPPORTED: even under T+1, ETF ratio is ≈ 1. "
               "Individual-stock EAV (K1060) is washed out by diversification.")

print(f"  Verdict: {verdict}")

# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------
print("\n[Charts] Rendering 3 figures ...")
plt.rcParams.update({"figure.dpi": 120, "savefig.dpi": 120})

# 1) Window comparison
fig, ax = plt.subplots(figsize=(11, 5.5))
labels = list(window_results.keys())
ratios = [window_results[l]["ratio"] for l in labels]
ns = [window_results[l]["n_event_days"] for l in labels]
colors = ["#6A994E" if r > 1 else "#A23B72" for r in ratios]
bars = ax.bar(range(len(labels)), ratios, color=colors, edgecolor="black", alpha=0.85)
ax.axhline(1.0, color="red", linestyle="--", lw=1.2, label="Null (ratio=1)")
ax.axhline(1.007, color="black", linestyle=":", lw=1.2,
           label="K1059 T+0 baseline (1.007)")
for i, (r, n, wl) in enumerate(zip(ratios, ns, labels)):
    t_stat = window_results[wl]["t_stat"]
    p_val = window_results[wl]["p_value_two_sided"]
    ax.text(i, r + 0.01, f"{r:.3f}", ha="center", fontsize=9, fontweight="bold")
    sub = f"n={n}"
    if t_stat is not None:
        sub += f"\nt={t_stat:+.2f}"
    if p_val is not None:
        sub += f"\np={p_val:.3f}"
    ax.text(i, max(ratios) * 0.06, sub, ha="center", va="bottom", fontsize=7)
ax.set_xticks(range(len(labels)))
ax.set_xticklabels(labels, rotation=15, ha="right")
ax.set_ylabel("event r^2 / non-event r^2")
ax.set_title("K1062 Part A: 0050.TW event-window ratios around TSMC earnings (2009-2025)")
ax.grid(axis="y", alpha=0.3)
ax.legend(loc="upper left", fontsize=9)
plt.tight_layout()
plt.savefig(SCRIPT_DIR / "k1062_window_comparison.png", bbox_inches="tight")
plt.close()
print("  saved k1062_window_comparison.png")

# 2) Clustering T+0 vs T+1 vs none
fig, ax = plt.subplots(figsize=(9.5, 5.5))
cats = ["None\n(no announce)", "Any\n(T+0)", "Dense\n(T+0)",
        "Any\n(T+1)", "Dense\n(T+1)"]
vals = [
    vol_none.mean() * 1e4,
    vol_any_t0.mean() * 1e4,
    vol_dense_t0.mean() * 1e4,
    vol_any_t1.mean() * 1e4,
    vol_dense_t1.mean() * 1e4,
]
bcol = ["lightgray", "#F18F01", "#E63946", "#2E86AB", "#1D3557"]
bars = ax.bar(cats, vals, color=bcol, edgecolor="black")
for b, v in zip(bars, vals):
    ax.text(b.get_x() + b.get_width() / 2, v + 0.05, f"{v:.2f}",
            ha="center", fontsize=9, fontweight="bold")
ax.set_ylabel("mean 0050.TW r^2 (bp)")
ax.set_title(
    "K1062 Part B: Clustering × T+1 — dense announce-day vol vs next-day vol"
)
ax.grid(axis="y", alpha=0.3)
none_bp = vol_none.mean() * 1e4
ax.axhline(none_bp, color="gray", linestyle=":", lw=1.0,
           label=f"No-announce baseline = {none_bp:.2f} bp")
ax.legend(fontsize=9)
plt.tight_layout()
plt.savefig(SCRIPT_DIR / "k1062_clustering_t1.png", bbox_inches="tight")
plt.close()
print("  saved k1062_clustering_t1.png")

# 3) A4f conditional performance
fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))

# (a) QLIKE bars
ax = axes[0]
groups = ["overall", "non_event", "t0", "t1"]
labs = ["Overall", "Non-event", "T+0", "T+1"]
w = 0.38
pos = np.arange(len(groups))
gjr_vals = [cond[g]["gjr_qlike"] for g in groups]
a4f_vals = [cond[g]["a4f_qlike"] for g in groups]
ax.bar(pos - w / 2, gjr_vals, w, label="GJR", color="#A23B72")
ax.bar(pos + w / 2, a4f_vals, w, label="A4f (VIX²)", color="#2E86AB")
ax.set_xticks(pos)
ax.set_xticklabels(labs)
ax.set_ylabel("QLIKE (lower = better)")
ax.set_title("(a) QLIKE conditional on event timing")
for i, g in enumerate(groups):
    ax.text(i - w / 2, gjr_vals[i] + 0.0002, f"{gjr_vals[i]:.4f}",
            ha="center", fontsize=8, rotation=0)
    ax.text(i + w / 2, a4f_vals[i] + 0.0002, f"{a4f_vals[i]:.4f}",
            ha="center", fontsize=8, rotation=0)
ax.grid(axis="y", alpha=0.3)
ax.legend()

# (b) DM t-stats
ax = axes[1]
dm_tvals = [cond[g]["dm_t"] if cond[g]["dm_t"] is not None else 0 for g in groups]
colors_dm = ["#2E86AB" if t > 0 else "#A23B72" for t in dm_tvals]
ax.bar(pos, dm_tvals, color=colors_dm, edgecolor="black")
for i, t in enumerate(dm_tvals):
    ax.text(i, t + 0.05 * np.sign(t if t != 0 else 1), f"{t:+.2f}",
            ha="center", fontsize=9)
ax.axhline(0, color="black", lw=0.8)
ax.axhline(3.0, color="red", linestyle="--", lw=1.0, label="|t|=3 (Harvey 2016)")
ax.axhline(-3.0, color="red", linestyle="--", lw=1.0)
ax.set_xticks(pos)
ax.set_xticklabels(labs)
ax.set_ylabel("DM t-stat (GJR − A4f; +ve = A4f better)")
ax.set_title("(b) Diebold–Mariano, GJR vs A4f")
ax.legend()
ax.grid(axis="y", alpha=0.3)

fig.suptitle(
    "K1062 Part D: A4f (GARCH-X, VIX²) vs GJR on TSMC-event days",
    fontsize=12,
)
plt.tight_layout(rect=[0, 0, 1, 0.96])
plt.savefig(SCRIPT_DIR / "k1062_a4f_conditional.png", bbox_inches="tight")
plt.close()
print("  saved k1062_a4f_conditional.png")

# --------------------------------------------------------------------------
# Results JSON
# --------------------------------------------------------------------------
elapsed = time.time() - START_TIME
now_iso = datetime.now(timezone.utc).isoformat()

results = {
    "experiment_id": "K1062",
    "title": "T+1 event-window re-run of K1059 — Does 0050.TW ETF show EAV too?",
    "proposer": "Claude (K1060 follow-up)",
    "executor": "Claude",
    "timestamp_utc": now_iso,
    "runtime_seconds": round(elapsed, 1),
    "random_seed": 42,
    "asset": "0050.TW",
    "data_sources": {
        "earnings": f"財報公告日.txt (Big5, parsed {len(ea_df):,} dated records, "
                    f"{ea_df['code'].nunique():,} companies)",
        "prices":   "yfinance 0050.TW daily (auto-adjust); clean_tw50_data applied",
        "vix":      "yfinance ^VIX daily",
    },
    "sample": {
        "start": str(trading_dates[0].date()),
        "end":   str(trading_dates[-1].date()),
        "n_trading_days": int(n_total),
        "n_tsmc_events_mapped": int(len(tsmc_t0)),
    },
    "config": {
        "OOS_START": OOS_START,
        "WINDOW": WINDOW,
        "REFIT_EVERY": REFIT_EVERY,
        "BOOTSTRAP_REPS": BOOTSTRAP_REPS,
        "EVENT_HALF_NONEVENT_EXCLUSION": EVENT_HALF,
    },
    "part_a_window_comparison": {
        "windows_tested": list(WINDOWS.keys()),
        "non_event_mean_r2_bp": nonevent_mean * 1e4,
        "results": window_results,
        "best_window_label": best_label,
        "best_window_ratio": best["ratio"],
    },
    "part_b_clustering_t1": clustering,
    "part_c_ols_t1": {
        "t1_regression": ols_t1,
        "t0_regression_replicate": ols_t0,
        "comment": ("K1059 Part B reported β_n(T+0) ≈ -0.46 NS. "
                    "H1 predicts β_n(T+0) > 0 when the dependent is r²[T+1]."),
    },
    "part_d_a4f_conditional": {
        "n_oos": int(n_oos),
        "n_valid_forecasts": int(valid.sum()),
        "refits": int(refit_count),
        "dm_blocks": cond,
    },
    "hypothesis_verdict": {
        "h1_pure_timing": (
            "T+1 ratio > 1 and > T+0, with statistical evidence "
            "(t or bootstrap p < 0.10)"),
        "h2_diversification_washout": (
            "Even under T+1, ratio ≈ 1 → index diversification dominates"),
        "h1_conditions": {
            "T1_ratio_gt_1":      bool(h1_a),
            "T1_ratio_gt_T0":     bool(h1_b),
            "T1_has_stat_evidence": bool(h1_c),
        },
        "verdict": verdict,
    },
    "references": [
        "Patell & Wolfson (1984) JAR — earnings day vol",
        "Beaver (1968) JAR — vol/volume at earnings",
        "Savor & Wilson (2016) JFQA — earnings as systematic risk",
        "K1058 — A4f on 0050.TW (DM NS, VaR Trinity A4f PASS)",
        "K1059 — TSMC → 0050.TW T+0 event study (ratio = 1.007, NULL)",
        "K1060 — Individual-stock T+1 EAV (mean ratio 1.466, t=2.075)",
        "Patton (2011) J Econometrics — QLIKE for vol model comparison",
    ],
    "error_log_checklist": {
        "clean_tw50_data_applied": True,
        "random_seed_fixed": 42,
        "no_shared_state_writes": True,
        "lag_respected": "OOS forecasts use only info up to t-1",
    },
}

out_path = SCRIPT_DIR / "k1062_results.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)

print(f"\nResults saved: {out_path}")
print("=" * 72)
print(f"K1062 done. Elapsed: {elapsed:.1f}s")
print(
    f"T+0 ratio = {t0_res['ratio']:.3f} (K1059 replicate); "
    f"T+1 ratio = {t1_res['ratio']:.3f}; "
    f"best window = {best_label} (ratio = {best['ratio']:.3f})."
)
print(f"Verdict: {verdict}")
print("=" * 72)
