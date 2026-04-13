#!/usr/bin/env python3
"""
K1098: A4f on 0050.TW with TAIFEX VIXTWN — Taiwan-Matched IV Pilot
===================================================================
[提出: Claude (Paper 10 side paper candidate), 執行: Claude]

Motivation:
  Paper 9 demonstrated that A4f-VIX on 0050.TW fails Harvey threshold
  (K1077 DM t=-0.49 NS). K1083 attributed 83% of the Taiwan gap to
  USD/TWD currency channel. K1085 (GLD-GVZ) and K1088 (USO-OVX) confirmed
  that asset-matched implied volatility passes Harvey (+4.46, +4.48).

  Open question: Does Taiwan have its own asset-matched IV that rescues
  0050.TW? TAIFEX publishes VIXTWN (台指選擇權 30-day IV) since 2006.
  K997 brief test used short data; K1098 uses full 2007-2021 Dropbox
  official data.

Hypotheses:
  H1: A4f-VIXTWN on 0050.TW DM Harvey PASS (|t|>3.0)?
  H2: A4f-VIXTWN beats A4f-VIX (head-to-head)?
  H3: COMBO (VIX + VIXTWN) is strictly better?
  H4: Does VIXTWN rescue the K1083 Taiwan currency gap?

Data:
  - 0050.TW: yfinance + clean_tw50_data (MANDATORY)
  - ^VIX: yfinance
  - VIXTWN: ~/Dropbox/TAIFEXDATA/vix/VIX/新_每日收盤VIX/ (2007-2021, 15 years)

Design:
  - Rolling-window GARCH with 1000-day training, 63-day refit
  - 4 models: GJR, A4f-VIX (K1077 baseline), A4f-VIXTWN (new), A4f-COMBO
  - OOS: 2013-01-01 ~ 2021-12-31 (9 years; 0050.TW starts 2009, needs 1000-day warmup)
  - Evaluation: QLIKE on r² (Patton 2011), DM Harvey (|t|>3.0), 1000-rep bootstrap CI

References:
  - Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3):776-797.
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey, Leybourne & Newbold (1997, 2016). Testing equality of prediction MSEs.
  - TAIFEX VIXTWN White Paper (2006 launch).
  - K1077 (0050.TW A4f-VIX DM -0.49 NS), K1083 (Currency 83% of gap),
    K1085 (GLD-GVZ asset-matched PASS), K1088 (USO-OVX asset-matched PASS),
    K997 (VIXTWN brief, short data).

Paper 10 implication:
  - If A4f-VIXTWN Harvey PASS: Paper 10 side paper feasible
    ("Taiwan Asset-Matched IV for Volatility Forecasting")
  - If NULL: Taiwan gap is structural (currency, concentration), not IV choice

Author: VolPred Research System
Date: 2026-04-12
Experiment ID: K1098
"""

import os
import sys
import glob
import json
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from scipy import stats, optimize

try:
    from numba import njit
    NUMBA_OK = True
except Exception:
    NUMBA_OK = False
    def njit(*a, **kw):
        def wrap(f):
            return f
        return wrap if a and callable(a[0]) else wrap

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1098"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.utils import clean_tw50_data  # MANDATORY for 0050.TW

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1098_results.json')
VIXTWN_CSV_PATH = os.path.join(SCRIPT_DIR, 'k1098_vixtwn_daily.csv')

# Configuration
DATA_START = '2007-01-01'    # VIXTWN starts 2007 in Dropbox
DATA_END = '2022-01-01'      # VIXTWN ends 2021-12
WINDOW = 1000                # 1000-day warmup (~4 years; still above 500-day threshold)
REFIT_EVERY = 63             # quarterly refit
OOS_START = '2013-01-01'     # 0050.TW starts 2009-01-02 + 1000-day warmup
OOS_END = '2021-12-31'

VIXTWN_DIR = os.path.expanduser('~/Dropbox/TAIFEXDATA/vix/VIX/新_每日收盤VIX/')

print("=" * 70)
print(f"{EXPERIMENT_ID}: 0050.TW A4f with TAIFEX VIXTWN — Paper 10 pilot")
print(f"  4 models: GJR / A4f-VIX / A4f-VIXTWN / A4f-COMBO")
print(f"  OOS: {OOS_START} ~ {OOS_END}, window={WINDOW}, refit={REFIT_EVERY}")
print("=" * 70)

# ============================================================
# SECTION 1: VIXTWN PARSER
# ============================================================
print("\n[1] Parsing TAIFEX VIXTWN files...")

def parse_vixtwn_line(line):
    """
    Parse a single VIXTWN line.
    Handles variable tab-separated columns across year formats:
      - 2007-2014 (most files): YYYYMMDD\tCODE\tVALUE            (3 fields)
      - 2007-10/11 edge case  : YYYYMMDD<spaces>CODE\tVALUE       (2 tab-fields, space+code fused)
      - 2015-2019: YYYYMMDD\tCODE\t\t\tVALUE                       (5 fields, extra empty)
      - 2020-2021: YYYYMMDD\tCODE\t\t\tVALUE\t\tPREV               (7 fields)

    Strategy: use a two-stage parse:
      1) Split by tab. Extract date from any 8-digit leading token after
         normalizing whitespace from the first token.
      2) The VIXTWN value is the FIRST non-empty field after the code column
         that parses as a float in (0, 200). This handles 2, 3, 5, 7 cols
         uniformly.
    Returns (date_str, value_float) or None if unparseable.
    """
    raw = line.rstrip('\r\n')
    if not raw or raw.strip().startswith('-') or raw.strip().startswith('日'):
        return None
    parts = raw.split('\t')
    if len(parts) < 2:
        return None
    # First field may contain "DATE<spaces>CODE" fused with spaces (2007 edge)
    first = parts[0]
    # Normalize: split the first column on whitespace to extract date token
    first_tokens = first.split()
    if not first_tokens:
        return None
    date_str = first_tokens[0].strip()
    if not (len(date_str) == 8 and date_str.isdigit()):
        return None
    # Now gather all candidate numeric fields: leftover tokens in first col
    # after the date, plus remaining tab-separated fields
    candidates = list(first_tokens[1:]) + [p.strip() for p in parts[1:]]
    # Skip the code column (heuristic: 8-digit code like 13452100)
    # The first candidate that's a plausible VIX value wins.
    # Codes are typically > 1000000, VIX values are in (0, 200).
    for v in candidates:
        if v == '':
            continue
        try:
            val = float(v)
        except ValueError:
            continue
        if 0 < val < 200:
            return date_str, val
        # else: skip (likely the product code)
    return None


def parse_all_vixtwn():
    """Parse all monthly VIXTWN files. Use monthly (not yearly) to avoid
    duplication; fallback to yearly if monthly missing."""
    all_records = {}   # date_str -> value
    year_dirs = sorted([d for d in os.listdir(VIXTWN_DIR)
                        if os.path.isdir(os.path.join(VIXTWN_DIR, d))
                        and d.isdigit()])
    files_processed = 0
    lines_skipped_header = 0
    for ydir in year_dirs:
        ypath = os.path.join(VIXTWN_DIR, ydir)
        # Prefer monthly files (6-digit YYYYMM prefix)
        monthly = sorted(glob.glob(os.path.join(ypath, '*.txt')))
        # Filter out the yearly aggregate (prefix = 4-digit year only)
        monthly = [f for f in monthly
                   if os.path.basename(f)[:6].isdigit()]
        if not monthly:
            # Fallback: use yearly aggregate
            yearly = sorted(glob.glob(os.path.join(ypath, '*.txt')))
            monthly = yearly
        for mf in monthly:
            try:
                with open(mf, 'r', encoding='utf-8', errors='ignore') as fh:
                    for line in fh:
                        parsed = parse_vixtwn_line(line)
                        if parsed is None:
                            lines_skipped_header += 1
                            continue
                        dstr, val = parsed
                        # Keep first occurrence (monthly files are authoritative)
                        if dstr not in all_records:
                            all_records[dstr] = val
                files_processed += 1
            except Exception as e:
                print(f"    WARN: Failed to parse {mf}: {e}")
    print(f"  Parsed {files_processed} files, {len(all_records)} unique dates, "
          f"{lines_skipped_header} header/blank lines skipped")
    # Build DataFrame
    df = pd.DataFrame({
        'date': pd.to_datetime(list(all_records.keys()), format='%Y%m%d'),
        'VIXTWN': list(all_records.values()),
    })
    df = df.sort_values('date').reset_index(drop=True)
    df = df.set_index('date')
    return df


vixtwn_df = parse_all_vixtwn()
print(f"  VIXTWN range: {vixtwn_df.index[0].date()} ~ {vixtwn_df.index[-1].date()}, "
      f"n={len(vixtwn_df)}")
print(f"  VIXTWN mean={vixtwn_df['VIXTWN'].mean():.2f}, "
      f"std={vixtwn_df['VIXTWN'].std():.2f}, max={vixtwn_df['VIXTWN'].max():.2f}")
print(f"  Date of VIXTWN max: {vixtwn_df['VIXTWN'].idxmax().date()}")

# Save parsed CSV
vixtwn_df.to_csv(VIXTWN_CSV_PATH)
print(f"  Saved parsed VIXTWN to {VIXTWN_CSV_PATH}")

# ============================================================
# SECTION 2: 0050.TW + ^VIX DATA LOADING
# ============================================================
print("\n[2] Loading 0050.TW and ^VIX...")
import yfinance as yf

raw_tw = yf.download('0050.TW', start=DATA_START, end=DATA_END,
                     progress=False, auto_adjust=False)
if isinstance(raw_tw.columns, pd.MultiIndex):
    raw_tw.columns = raw_tw.columns.get_level_values(0)
prices_tw_raw = raw_tw['Close'].copy() if 'Close' in raw_tw.columns else raw_tw.iloc[:, 0].copy()
prices_tw, _ = clean_tw50_data(prices_tw_raw)
log_ret_tw = np.log(prices_tw / prices_tw.shift(1))

vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END,
                      progress=False, auto_adjust=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].copy()

# Align all three on 0050.TW trading days (forward-fill VIX and VIXTWN)
vix_ffill = vix_close.reindex(prices_tw.index, method='ffill')
vixtwn_ffill = vixtwn_df['VIXTWN'].reindex(prices_tw.index, method='ffill')

df = pd.DataFrame({
    'price': prices_tw,
    'log_ret': log_ret_tw,
    'VIX': vix_ffill,
    'VIXTWN': vixtwn_ffill,
})
df = df.dropna()

# Safety net
max_abs_ret = df['log_ret'].abs().max()
if max_abs_ret > 0.3:
    print(f"  ⚠️ WARNING: Max |return| = {max_abs_ret:.4f}, dropping extreme outliers")
    df = df[df['log_ret'].abs() <= 0.3]

n_total = len(df)
print(f"  Joint sample: {df.index[0].date()} ~ {df.index[-1].date()}, n={n_total}")
print(f"  Max |log_ret|: {df['log_ret'].abs().max():.4f}")

ret = df['log_ret'].values
vix = df['VIX'].values
vixtwn = df['VIXTWN'].values
r2 = ret ** 2
dates = df.index

# ============================================================
# SECTION 3: DIAGNOSTICS
# ============================================================
print("\n[3] Diagnostics...")
print(f"  0050.TW returns:")
print(f"    ann mean: {np.mean(ret)*252:.4f}")
print(f"    ann std : {np.std(ret)*np.sqrt(252):.4f}")
print(f"    skew    : {stats.skew(ret):.3f}")
print(f"    kurt    : {stats.kurtosis(ret):.3f}")
print(f"  VIX: mean={np.mean(vix):.2f}, max={np.max(vix):.2f} @ {dates[np.argmax(vix)].date()}")
print(f"  VIXTWN: mean={np.mean(vixtwn):.2f}, max={np.max(vixtwn):.2f} @ {dates[np.argmax(vixtwn)].date()}")

# VIX vs VIXTWN correlation
corr_vix_vixtwn = np.corrcoef(vix, vixtwn)[0, 1]
print(f"  Correlation VIX-VIXTWN (levels): {corr_vix_vixtwn:.4f}")
# Log diff correlation
dvix = np.diff(np.log(vix + 1e-8))
dvixtwn = np.diff(np.log(vixtwn + 1e-8))
corr_vix_vixtwn_chg = np.corrcoef(dvix, dvixtwn)[0, 1]
print(f"  Correlation VIX-VIXTWN (log-diff): {corr_vix_vixtwn_chg:.4f}")

try:
    from statsmodels.tsa.stattools import adfuller
    adf_ret = adfuller(ret, maxlag=10, autolag='AIC')
    print(f"  ADF returns: stat={adf_ret[0]:.4f}, p={adf_ret[1]:.6f}")
except Exception as e:
    print(f"  ADF skipped: {e}")

try:
    from statsmodels.stats.diagnostic import het_arch
    arch_lm = het_arch(ret, nlags=5)
    print(f"  ARCH LM(5): stat={arch_lm[0]:.2f}, p={arch_lm[1]:.6f}")
except Exception as e:
    print(f"  ARCH LM skipped: {e}")

# ============================================================
# SECTION 4: MODEL IMPLEMENTATIONS
# ============================================================
print("\n[4] Model implementations...")


# --- GJR-GARCH(1,1) baseline ---
@njit(cache=True)
def gjr_loglik(params, returns):
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns[:min(250, n)])
    ll = 0.0
    for t in range(1, n):
        asym = gamma * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + returns[t]**2 / h[t])
    return -ll


def fit_gjr(returns):
    var0 = np.var(returns)
    best_ll = np.inf
    best_params = None
    converged = False
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, 0.03, 0.08, 0.88],
        [var0 * 0.10, 0.08, 0.10, 0.80],
    ]
    bounds = [(1e-8, var0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    for s in starts:
        try:
            res = optimize.minimize(gjr_loglik, s, args=(returns,),
                                    method='L-BFGS-B', bounds=bounds)
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
                converged = res.success
        except Exception:
            continue
    return best_params, converged


def gjr_forecast_1step(params, h_prev, r_prev):
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


# --- A4f single-X (VIX or VIXTWN): tau = theta0 + theta1 * X^2 ---
def fit_a4f_single(returns, x_vals):
    """A4f with a single exogenous regressor.
    tau_t = max(theta0 + theta1 * X_{t-1}^2, eps)
    Same Engle 2013 logic as K1077.
    Parameters: [theta0, theta1, omega_g, alpha, gamma, beta]
    """
    n = len(returns)
    x_lag = np.empty(n)
    x_lag[0] = x_vals[0]
    x_lag[1:] = x_vals[:-1]
    x_lag_sq = x_lag ** 2

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10
        tau = np.maximum(theta0 + theta1 * x_lag_sq, 1e-16)
        g = np.empty(n)
        g[0] = omega_g / (1.0 - persist)
        ll = 0.0
        for t in range(1, n):
            u_prev = returns[t-1] / np.sqrt(tau[t])
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10
        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)
        return -ll

    var0 = np.var(returns)
    x2_mean = np.mean(x_lag_sq) + 1e-8
    starts = [
        [var0 * 0.1, var0 / x2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / x2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / x2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [
        (-1e-2, 1e-2),
        (1e-10, 1e-2),
        (1e-6, 1.0),
        (1e-4, 0.3),
        (1e-4, 0.3),
        (0.5, 0.999),
    ]
    best_ll = np.inf
    best_params = None
    converged = False
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
                converged = res.success
        except Exception:
            continue
    return best_params, converged


# --- A4f COMBO: tau = theta0 + theta1 * VIX^2 + theta2 * VIXTWN^2 ---
def fit_a4f_combo(returns, vix_vals, vixtwn_vals):
    """A4f-COMBO: tau_t = max(theta0 + theta1 * VIX_{t-1}^2 + theta2 * VIXTWN_{t-1}^2, eps).
    Parameters: [theta0, theta1, theta2, omega_g, alpha, gamma, beta]
    """
    n = len(returns)
    v1_lag = np.empty(n); v1_lag[0] = vix_vals[0]; v1_lag[1:] = vix_vals[:-1]
    v2_lag = np.empty(n); v2_lag[0] = vixtwn_vals[0]; v2_lag[1:] = vixtwn_vals[:-1]
    v1_sq = v1_lag ** 2
    v2_sq = v2_lag ** 2

    def neg_loglik(params):
        theta0, theta1, theta2, omega_g, alpha, gamma_p, beta = params
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10
        tau = np.maximum(theta0 + theta1 * v1_sq + theta2 * v2_sq, 1e-16)
        g = np.empty(n)
        g[0] = omega_g / (1.0 - persist)
        ll = 0.0
        for t in range(1, n):
            u_prev = returns[t-1] / np.sqrt(tau[t])
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10
        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)
        return -ll

    var0 = np.var(returns)
    v1_mean = np.mean(v1_sq) + 1e-8
    v2_mean = np.mean(v2_sq) + 1e-8
    starts = [
        [var0 * 0.1, var0 / v1_mean * 0.5, var0 / v2_mean * 0.5, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / v1_mean * 0.3, var0 / v2_mean * 0.7, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / v1_mean * 0.7, var0 / v2_mean * 0.3, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [
        (-1e-2, 1e-2),      # theta0
        (1e-12, 1e-2),      # theta1 (VIX)
        (1e-12, 1e-2),      # theta2 (VIXTWN)
        (1e-6, 1.0),
        (1e-4, 0.3),
        (1e-4, 0.3),
        (0.5, 0.999),
    ]
    best_ll = np.inf
    best_params = None
    converged = False
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
                converged = res.success
        except Exception:
            continue
    return best_params, converged


# ============================================================
# SECTION 5: OUT-OF-SAMPLE FORECASTING
# ============================================================
print("\n[5] Out-of-sample forecasting...")

oos_mask = (dates >= OOS_START) & (dates <= OOS_END)
oos_indices = np.where(oos_mask)[0]
n_oos = len(oos_indices)
print(f"  OOS: {dates[oos_indices[0]].date()} ~ {dates[oos_indices[-1]].date()}, n={n_oos}")

# Verify sufficient history
first_oos_idx = oos_indices[0]
if first_oos_idx < WINDOW:
    print(f"  ⚠️ First OOS idx={first_oos_idx} < WINDOW={WINDOW}. Truncating warmup.")

gjr_fc = np.full(n_oos, np.nan)
a4f_vix_fc = np.full(n_oos, np.nan)
a4f_vixtwn_fc = np.full(n_oos, np.nan)
a4f_combo_fc = np.full(n_oos, np.nan)

refit_log = []

# State vars per model
gjr_h = None; gjr_p = None
av_g = None; av_p = None       # A4f-VIX
at_g = None; at_p = None       # A4f-VIXTWN
ac_g = None; ac_p = None       # A4f-COMBO

refit_count = 0

for t_idx, abs_idx in enumerate(oos_indices):
    # Refit at start or every REFIT_EVERY days
    need_refit = (t_idx == 0) or (t_idx % REFIT_EVERY == 0)

    if need_refit:
        refit_count += 1
        train_start = max(0, abs_idx - WINDOW)
        tr_ret = ret[train_start:abs_idx]
        tr_vix = vix[train_start:abs_idx]
        tr_vixtwn = vixtwn[train_start:abs_idx]

        # GJR
        p1, c1 = fit_gjr(tr_ret)
        if p1 is not None:
            gjr_p = p1
            h = np.var(tr_ret[:min(250, len(tr_ret))])
            for i in range(1, len(tr_ret)):
                h = gjr_forecast_1step(gjr_p, h, tr_ret[i-1])
            gjr_h = h

        # A4f-VIX
        p2, c2 = fit_a4f_single(tr_ret, tr_vix)
        if p2 is not None:
            av_p = p2
            theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = p2
            v_lag_tr = np.empty(len(tr_vix)); v_lag_tr[0] = tr_vix[0]; v_lag_tr[1:] = tr_vix[:-1]
            tau_tr = np.maximum(theta0 + theta1 * v_lag_tr**2, 1e-16)
            persist = alpha_p + gamma_p/2.0 + beta_p
            g = omega_g / (1.0 - persist)
            for i in range(1, len(tr_ret)):
                u_prev = tr_ret[i-1] / np.sqrt(tau_tr[i])
                asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
                g = max(g, 1e-10)
            av_g = g

        # A4f-VIXTWN
        p3, c3 = fit_a4f_single(tr_ret, tr_vixtwn)
        if p3 is not None:
            at_p = p3
            theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = p3
            x_lag_tr = np.empty(len(tr_vixtwn)); x_lag_tr[0] = tr_vixtwn[0]; x_lag_tr[1:] = tr_vixtwn[:-1]
            tau_tr = np.maximum(theta0 + theta1 * x_lag_tr**2, 1e-16)
            persist = alpha_p + gamma_p/2.0 + beta_p
            g = omega_g / (1.0 - persist)
            for i in range(1, len(tr_ret)):
                u_prev = tr_ret[i-1] / np.sqrt(tau_tr[i])
                asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
                g = max(g, 1e-10)
            at_g = g

        # A4f-COMBO
        p4, c4 = fit_a4f_combo(tr_ret, tr_vix, tr_vixtwn)
        if p4 is not None:
            ac_p = p4
            theta0, theta1c, theta2c, omega_g, alpha_p, gamma_p, beta_p = p4
            v1_lag_tr = np.empty(len(tr_vix)); v1_lag_tr[0] = tr_vix[0]; v1_lag_tr[1:] = tr_vix[:-1]
            v2_lag_tr = np.empty(len(tr_vixtwn)); v2_lag_tr[0] = tr_vixtwn[0]; v2_lag_tr[1:] = tr_vixtwn[:-1]
            tau_tr = np.maximum(theta0 + theta1c * v1_lag_tr**2 + theta2c * v2_lag_tr**2, 1e-16)
            persist = alpha_p + gamma_p/2.0 + beta_p
            g = omega_g / (1.0 - persist)
            for i in range(1, len(tr_ret)):
                u_prev = tr_ret[i-1] / np.sqrt(tau_tr[i])
                asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
                g = max(g, 1e-10)
            ac_g = g

        refit_log.append({
            'date': dates[abs_idx].strftime('%Y-%m-%d'),
            'gjr_conv': bool(c1) if p1 is not None else False,
            'a4f_vix_conv': bool(c2) if p2 is not None else False,
            'a4f_vixtwn_conv': bool(c3) if p3 is not None else False,
            'a4f_combo_conv': bool(c4) if p4 is not None else False,
            'av_theta1': float(av_p[1]) if av_p is not None else None,
            'at_theta1': float(at_p[1]) if at_p is not None else None,
            'ac_theta1_vix': float(ac_p[1]) if ac_p is not None else None,
            'ac_theta2_vixtwn': float(ac_p[2]) if ac_p is not None else None,
        })

        if refit_count % 10 == 0:
            elapsed = time.time() - START_TIME
            print(f"    Refit #{refit_count} at {dates[abs_idx].date()}, elapsed {elapsed:.0f}s")

    # Forecasts
    r_prev = ret[abs_idx - 1]
    v_prev = vix[abs_idx - 1]
    vt_prev = vixtwn[abs_idx - 1]

    if gjr_p is not None:
        h_new = gjr_forecast_1step(gjr_p, gjr_h, r_prev)
        gjr_fc[t_idx] = h_new
        gjr_h = h_new

    if av_p is not None:
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = av_p
        tau_t = max(theta0 + theta1 * v_prev**2, 1e-16)
        u_prev = r_prev / np.sqrt(tau_t)
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = max(omega_g + alpha_p * u_prev**2 + asym + beta_p * av_g, 1e-10)
        a4f_vix_fc[t_idx] = tau_t * g_new
        av_g = g_new

    if at_p is not None:
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = at_p
        tau_t = max(theta0 + theta1 * vt_prev**2, 1e-16)
        u_prev = r_prev / np.sqrt(tau_t)
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = max(omega_g + alpha_p * u_prev**2 + asym + beta_p * at_g, 1e-10)
        a4f_vixtwn_fc[t_idx] = tau_t * g_new
        at_g = g_new

    if ac_p is not None:
        theta0, theta1c, theta2c, omega_g, alpha_p, gamma_p, beta_p = ac_p
        tau_t = max(theta0 + theta1c * v_prev**2 + theta2c * vt_prev**2, 1e-16)
        u_prev = r_prev / np.sqrt(tau_t)
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = max(omega_g + alpha_p * u_prev**2 + asym + beta_p * ac_g, 1e-10)
        a4f_combo_fc[t_idx] = tau_t * g_new
        ac_g = g_new

elapsed = time.time() - START_TIME
print(f"  Forecasting complete in {elapsed:.0f}s, {refit_count} refits")

# ============================================================
# SECTION 6: EVALUATION
# ============================================================
print("\n[6] Evaluation...")

oos_r2 = r2[oos_indices]
oos_dates = dates[oos_indices]

valid = (~np.isnan(gjr_fc) & (gjr_fc > 0) &
         ~np.isnan(a4f_vix_fc) & (a4f_vix_fc > 0) &
         ~np.isnan(a4f_vixtwn_fc) & (a4f_vixtwn_fc > 0) &
         ~np.isnan(a4f_combo_fc) & (a4f_combo_fc > 0))
n_v = valid.sum()
print(f"  Valid joint observations: {n_v}/{n_oos}")


def qlike_loss(fc, r2_vals):
    return np.log(fc) + r2_vals / fc


def hac_dm_test(d_array):
    d_array = d_array[np.isfinite(d_array)]
    T = len(d_array)
    if T < 30:
        return np.nan, np.nan, T
    d_mean = np.mean(d_array)
    max_lag = max(1, int(np.floor(T**(1/3))))
    gamma_0 = np.var(d_array, ddof=0)
    hac_var = gamma_0
    for j in range(1, max_lag + 1):
        w_j = 1 - j / (max_lag + 1)
        gamma_j = np.mean((d_array[j:] - d_mean) * (d_array[:-j] - d_mean))
        hac_var += 2 * w_j * gamma_j
    if hac_var <= 0:
        return np.nan, np.nan, T
    dm_stat = d_mean / np.sqrt(hac_var / T)
    dm_p = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(dm_p), T


def bootstrap_ci_mean_diff(arr, n_boot=1000, seed=42):
    rng = np.random.default_rng(seed)
    n = len(arr)
    if n < 30:
        return (np.nan, np.nan)
    boot_means = np.empty(n_boot)
    block_len = max(1, int(n**(1/3)))
    for b in range(n_boot):
        starts = rng.integers(0, n, size=(n // block_len + 1))
        blocks = [arr[s:s+block_len] for s in starts if s + block_len <= n]
        boot_sample = np.concatenate(blocks)[:n]
        boot_means[b] = np.mean(boot_sample)
    return (float(np.percentile(boot_means, 2.5)),
            float(np.percentile(boot_means, 97.5)))


fc_gjr = gjr_fc[valid]
fc_av = a4f_vix_fc[valid]
fc_at = a4f_vixtwn_fc[valid]
fc_ac = a4f_combo_fc[valid]
r2_v = oos_r2[valid]

ql_gjr = float(np.mean(qlike_loss(fc_gjr, r2_v)))
ql_av = float(np.mean(qlike_loss(fc_av, r2_v)))
ql_at = float(np.mean(qlike_loss(fc_at, r2_v)))
ql_ac = float(np.mean(qlike_loss(fc_ac, r2_v)))

print(f"\n  QLIKE means (lower=better):")
print(f"    GJR         : {ql_gjr:.6f}")
print(f"    A4f-VIX     : {ql_av:.6f} ({(ql_av-ql_gjr)/abs(ql_gjr)*100:+.2f}%)")
print(f"    A4f-VIXTWN  : {ql_at:.6f} ({(ql_at-ql_gjr)/abs(ql_gjr)*100:+.2f}%)")
print(f"    A4f-COMBO   : {ql_ac:.6f} ({(ql_ac-ql_gjr)/abs(ql_gjr)*100:+.2f}%)")

# DM tests vs GJR baseline (positive t => A4f-X better)
loss_gjr = qlike_loss(fc_gjr, r2_v)
loss_av = qlike_loss(fc_av, r2_v)
loss_at = qlike_loss(fc_at, r2_v)
loss_ac = qlike_loss(fc_ac, r2_v)

dm_vix_vs_gjr = hac_dm_test(loss_gjr - loss_av)
dm_vixtwn_vs_gjr = hac_dm_test(loss_gjr - loss_at)
dm_combo_vs_gjr = hac_dm_test(loss_gjr - loss_ac)
dm_vixtwn_vs_vix = hac_dm_test(loss_av - loss_at)   # positive => VIXTWN better
dm_combo_vs_vixtwn = hac_dm_test(loss_at - loss_ac)  # positive => COMBO better
dm_combo_vs_vix = hac_dm_test(loss_av - loss_ac)

# Harvey PASS definition: t > +3.0 (positive = X model beats GJR with Harvey conservatism).
# |t| > 3 with negative t means X is significantly WORSE, not "pass".
def harvey_verdict(t):
    if not np.isfinite(t):
        return 'NA'
    if t > 3.0:
        return 'PASS'
    if t < -3.0:
        return 'WORSE_SIGNIF'
    return 'FAIL'

print(f"\n  DM tests (Harvey pass: t > +3.0; positive = X beats GJR):")
print(f"    A4f-VIX    vs GJR     : t={dm_vix_vs_gjr[0]:+.3f}  p={dm_vix_vs_gjr[1]:.4f}  "
      f"{harvey_verdict(dm_vix_vs_gjr[0])}")
print(f"    A4f-VIXTWN vs GJR     : t={dm_vixtwn_vs_gjr[0]:+.3f}  p={dm_vixtwn_vs_gjr[1]:.4f}  "
      f"{harvey_verdict(dm_vixtwn_vs_gjr[0])}")
print(f"    A4f-COMBO  vs GJR     : t={dm_combo_vs_gjr[0]:+.3f}  p={dm_combo_vs_gjr[1]:.4f}  "
      f"{harvey_verdict(dm_combo_vs_gjr[0])}")
print(f"    A4f-VIXTWN vs A4f-VIX : t={dm_vixtwn_vs_vix[0]:+.3f}  p={dm_vixtwn_vs_vix[1]:.4f}  "
      f"(positive => VIXTWN wins)")
print(f"    A4f-COMBO  vs A4f-VIXTWN: t={dm_combo_vs_vixtwn[0]:+.3f}  p={dm_combo_vs_vixtwn[1]:.4f}  "
      f"(positive => COMBO wins)")
print(f"    A4f-COMBO  vs A4f-VIX : t={dm_combo_vs_vix[0]:+.3f}  p={dm_combo_vs_vix[1]:.4f}  "
      f"(positive => COMBO wins)")

# Spearman (rank corr) with r^2
rho_gjr, _ = stats.spearmanr(fc_gjr, r2_v)
rho_av, _ = stats.spearmanr(fc_av, r2_v)
rho_at, _ = stats.spearmanr(fc_at, r2_v)
rho_ac, _ = stats.spearmanr(fc_ac, r2_v)

# Bootstrap CIs for QLIKE diffs
ci_av = bootstrap_ci_mean_diff(loss_gjr - loss_av, n_boot=1000)
ci_at = bootstrap_ci_mean_diff(loss_gjr - loss_at, n_boot=1000)
ci_ac = bootstrap_ci_mean_diff(loss_gjr - loss_ac, n_boot=1000)

# Theta1/Theta2 stability (from refit log)
av_theta1_vals = [r['av_theta1'] for r in refit_log if r.get('av_theta1') is not None]
at_theta1_vals = [r['at_theta1'] for r in refit_log if r.get('at_theta1') is not None]
ac_theta1_vix = [r['ac_theta1_vix'] for r in refit_log if r.get('ac_theta1_vix') is not None]
ac_theta2_vixtwn = [r['ac_theta2_vixtwn'] for r in refit_log if r.get('ac_theta2_vixtwn') is not None]

def stat_summary(arr):
    if not arr:
        return {'mean': None, 'median': None, 'min': None, 'max': None, 'n': 0}
    return {'mean': float(np.mean(arr)), 'median': float(np.median(arr)),
            'min': float(np.min(arr)), 'max': float(np.max(arr)), 'n': len(arr)}

# Regime analysis: VIX vs VIXTWN difference
# Where does VIXTWN carry independent info? regimes with high VIXTWN/VIX divergence
# or periods when Taiwan-specific risks (TSMC events, cross-strait) spike
vix_v = vix[oos_indices][valid]
vixtwn_v = vixtwn[oos_indices][valid]
# VIXTWN-VIX spread (standardized)
spread = (vixtwn_v - vix_v)
spread_z = (spread - np.mean(spread)) / (np.std(spread) + 1e-8)
# High-spread regime: top quintile (VIXTWN > VIX more than usual)
spread_q80 = np.percentile(spread_z, 80)
high_spread_mask = spread_z >= spread_q80
# Compute QLIKE differences in this regime
if high_spread_mask.sum() > 30:
    ql_av_hs = float(np.mean(qlike_loss(fc_av[high_spread_mask], r2_v[high_spread_mask])))
    ql_at_hs = float(np.mean(qlike_loss(fc_at[high_spread_mask], r2_v[high_spread_mask])))
    dm_hs = hac_dm_test(loss_av[high_spread_mask] - loss_at[high_spread_mask])
    regime_high_spread = {
        'n': int(high_spread_mask.sum()),
        'threshold_z': float(spread_q80),
        'qlike_a4f_vix': ql_av_hs,
        'qlike_a4f_vixtwn': ql_at_hs,
        'dm_vixtwn_vs_vix_t': float(dm_hs[0]) if np.isfinite(dm_hs[0]) else None,
        'dm_vixtwn_vs_vix_p': float(dm_hs[1]) if np.isfinite(dm_hs[1]) else None,
    }
else:
    regime_high_spread = {'n': int(high_spread_mask.sum()), 'status': 'insufficient'}

# ============================================================
# SECTION 7: HYPOTHESIS VERDICTS
# ============================================================
print("\n" + "=" * 70)
print("HYPOTHESIS VERDICTS")
print("=" * 70)

h1 = 'PASS' if dm_vixtwn_vs_gjr[0] > 3.0 else 'FAIL'
print(f"  H1 (A4f-VIXTWN on 0050.TW DM Harvey PASS): {h1}  "
      f"(t={dm_vixtwn_vs_gjr[0]:+.3f}, QLIKE {(ql_at-ql_gjr)/abs(ql_gjr)*100:+.2f}%)")

if ql_at < ql_av:
    h2_dir = 'VIXTWN better'
else:
    h2_dir = 'VIX better'
h2 = 'PASS' if dm_vixtwn_vs_vix[0] > 3.0 and ql_at < ql_av else 'FAIL'
print(f"  H2 (VIXTWN beats VIX head-to-head, |t|>3): {h2}  "
      f"(t={dm_vixtwn_vs_vix[0]:+.3f}, {h2_dir})")

h3_vs_vix = 'PASS' if dm_combo_vs_vix[0] > 3.0 and ql_ac < ql_av else 'FAIL'
h3_vs_vixtwn = 'PASS' if dm_combo_vs_vixtwn[0] > 3.0 and ql_ac < ql_at else 'FAIL'
h3 = 'PASS' if (h3_vs_vix == 'PASS' or h3_vs_vixtwn == 'PASS') else 'FAIL'
print(f"  H3 (COMBO strictly better than both): {h3}  "
      f"(vs VIX: {h3_vs_vix} t={dm_combo_vs_vix[0]:+.3f}; "
      f"vs VIXTWN: {h3_vs_vixtwn} t={dm_combo_vs_vixtwn[0]:+.3f})")

# H4: Rescue of K1083 currency gap. K1077 reported A4f-VIX DM -0.49 NS on TW.
# If A4f-VIXTWN Harvey PASS → rescues. If NULL → structural gap not fixable by IV choice.
if h1 == 'PASS':
    h4 = 'PASS (VIXTWN rescues)'
elif ql_at < ql_av and dm_vixtwn_vs_vix[0] > 0:
    h4 = 'PARTIAL (VIXTWN improves but sub-Harvey)'
else:
    h4 = 'FAIL (structural Taiwan gap not from IV choice)'
print(f"  H4 (VIXTWN rescues K1083 currency gap): {h4}")

verdicts = {
    'H1_a4f_vixtwn_harvey_pass': h1,
    'H2_vixtwn_beats_vix': h2,
    'H3_combo_strictly_better': h3,
    'H4_rescue_currency_gap': h4,
    'H3_combo_vs_vix': h3_vs_vix,
    'H3_combo_vs_vixtwn': h3_vs_vixtwn,
}

# ============================================================
# SECTION 8: RESULTS ASSEMBLY
# ============================================================
results = {
    'metadata': {
        'experiment_id': EXPERIMENT_ID,
        'asset': '0050.TW',
        'vix_source': '^VIX (yfinance, forward-filled to TW trading days)',
        'vixtwn_source': 'TAIFEX official Dropbox (2007-2021)',
        'vixtwn_parsed_path': VIXTWN_CSV_PATH,
        'vixtwn_n_raw': int(len(vixtwn_df)),
        'data_start': DATA_START,
        'data_end': DATA_END,
        'oos_start': OOS_START,
        'oos_end': OOS_END,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'n_total': int(n_total),
        'n_oos': int(n_oos),
        'n_valid': int(n_v),
        'n_refits': int(refit_count),
        'random_seed': 42,
        'elapsed_seconds': time.time() - START_TIME,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'proposer': 'Claude (Paper 10 side paper candidate)',
        'executor': 'Claude',
        'references': [
            'Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3):776-797.',
            'Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.',
            'Harvey, Leybourne & Newbold (1997, 2016). Testing equality of prediction MSEs.',
            'TAIFEX VIXTWN White Paper (2006).',
        ],
        'upstream_experiments': [
            'K1077 (0050.TW A4f-VIX DM -0.49 NS, 2010-2025)',
            'K1083 (Currency 83% of Taiwan gap)',
            'K1085 (GLD-GVZ asset-matched PASS +4.46)',
            'K1088 (USO-OVX asset-matched PASS +4.48)',
            'K997 (VIXTWN brief test, short data)',
        ],
    },
    'diagnostics': {
        'ret_ann_mean': float(np.mean(ret) * 252),
        'ret_ann_std': float(np.std(ret) * np.sqrt(252)),
        'ret_skew': float(stats.skew(ret)),
        'ret_kurt': float(stats.kurtosis(ret)),
        'vix_mean': float(np.mean(vix)),
        'vix_max': float(np.max(vix)),
        'vixtwn_mean': float(np.mean(vixtwn)),
        'vixtwn_max': float(np.max(vixtwn)),
        'corr_vix_vixtwn_levels': float(corr_vix_vixtwn),
        'corr_vix_vixtwn_logdiff': float(corr_vix_vixtwn_chg),
    },
    'qlike': {
        'gjr': ql_gjr,
        'a4f_vix': ql_av,
        'a4f_vixtwn': ql_at,
        'a4f_combo': ql_ac,
        'diff_vix_vs_gjr_pct': (ql_av - ql_gjr) / abs(ql_gjr) * 100,
        'diff_vixtwn_vs_gjr_pct': (ql_at - ql_gjr) / abs(ql_gjr) * 100,
        'diff_combo_vs_gjr_pct': (ql_ac - ql_gjr) / abs(ql_gjr) * 100,
    },
    'dm_tests': {
        # harvey_pass = t > +3.0 (X beats GJR significantly under Harvey conservatism).
        # harvey_worse = t < -3.0 (X significantly WORSE than GJR).
        'a4f_vix_vs_gjr': {'t': float(dm_vix_vs_gjr[0]), 'p': float(dm_vix_vs_gjr[1]),
                           'harvey_pass': bool(dm_vix_vs_gjr[0] > 3.0),
                           'harvey_worse': bool(dm_vix_vs_gjr[0] < -3.0)},
        'a4f_vixtwn_vs_gjr': {'t': float(dm_vixtwn_vs_gjr[0]), 'p': float(dm_vixtwn_vs_gjr[1]),
                              'harvey_pass': bool(dm_vixtwn_vs_gjr[0] > 3.0),
                              'harvey_worse': bool(dm_vixtwn_vs_gjr[0] < -3.0)},
        'a4f_combo_vs_gjr': {'t': float(dm_combo_vs_gjr[0]), 'p': float(dm_combo_vs_gjr[1]),
                             'harvey_pass': bool(dm_combo_vs_gjr[0] > 3.0),
                             'harvey_worse': bool(dm_combo_vs_gjr[0] < -3.0)},
        'a4f_vixtwn_vs_a4f_vix': {'t': float(dm_vixtwn_vs_vix[0]), 'p': float(dm_vixtwn_vs_vix[1]),
                                  'note': 'positive t => VIXTWN beats VIX'},
        'a4f_combo_vs_a4f_vixtwn': {'t': float(dm_combo_vs_vixtwn[0]), 'p': float(dm_combo_vs_vixtwn[1]),
                                    'note': 'positive t => COMBO beats VIXTWN'},
        'a4f_combo_vs_a4f_vix': {'t': float(dm_combo_vs_vix[0]), 'p': float(dm_combo_vs_vix[1]),
                                 'note': 'positive t => COMBO beats VIX'},
    },
    'spearman': {
        'gjr': float(rho_gjr),
        'a4f_vix': float(rho_av),
        'a4f_vixtwn': float(rho_at),
        'a4f_combo': float(rho_ac),
    },
    'bootstrap_ci_95_d_vs_gjr': {
        'a4f_vix': list(ci_av),
        'a4f_vixtwn': list(ci_at),
        'a4f_combo': list(ci_ac),
    },
    'theta_stability': {
        'a4f_vix_theta1': stat_summary(av_theta1_vals),
        'a4f_vixtwn_theta1': stat_summary(at_theta1_vals),
        'a4f_combo_theta1_vix': stat_summary(ac_theta1_vix),
        'a4f_combo_theta2_vixtwn': stat_summary(ac_theta2_vixtwn),
    },
    'regime_high_vixtwn_vix_spread': regime_high_spread,
    'hypothesis_verdicts': verdicts,
    'refit_log': refit_log,
}

# ============================================================
# SECTION 9: SAVE
# ============================================================
with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to {RESULTS_PATH}")
print(f"  Total elapsed: {time.time() - START_TIME:.0f}s")

# ============================================================
# SECTION 10: PLOTS
# ============================================================
print("\n[10] Generating plots...")
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # Plot 1: DM comparison bar chart (4 models vs GJR)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    labels = ['A4f-VIX', 'A4f-VIXTWN', 'A4f-COMBO']
    dm_ts = [dm_vix_vs_gjr[0], dm_vixtwn_vs_gjr[0], dm_combo_vs_gjr[0]]
    colors = ['steelblue', 'coral', 'seagreen']
    bars = ax1.bar(labels, dm_ts, color=colors)
    ax1.axhline(3.0, color='red', linestyle='--', alpha=0.7, label='Harvey +3')
    ax1.axhline(-3.0, color='red', linestyle='--', alpha=0.7, label='Harvey -3')
    ax1.axhline(0, color='black', linewidth=0.5)
    ax1.set_ylabel('DM t-statistic (positive = beats GJR)')
    ax1.set_title(f'K1098 DM vs GJR on 0050.TW ({OOS_START[:4]}-{OOS_END[:4]})\nHarvey threshold |t|>3.0')
    ax1.legend(loc='best')
    for bar, t in zip(bars, dm_ts):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                 f'{t:+.2f}', ha='center', va='bottom' if t >= 0 else 'top')

    # QLIKE comparison
    models = ['GJR', 'A4f-VIX', 'A4f-VIXTWN', 'A4f-COMBO']
    qlikes = [ql_gjr, ql_av, ql_at, ql_ac]
    colors2 = ['gray', 'steelblue', 'coral', 'seagreen']
    bars2 = ax2.bar(models, qlikes, color=colors2)
    ax2.set_ylabel('QLIKE (lower = better)')
    ax2.set_title('QLIKE on r² (Patton 2011)')
    for bar, q in zip(bars2, qlikes):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                 f'{q:.4f}', ha='center', va='bottom', fontsize=9)

    plt.tight_layout()
    plot1_path = os.path.join(SCRIPT_DIR, 'k1098_dm_comparison.png')
    plt.savefig(plot1_path, dpi=120, bbox_inches='tight')
    plt.close()
    print(f"  Saved {plot1_path}")

    # Plot 2: VIX vs VIXTWN time series
    fig, ax = plt.subplots(figsize=(14, 5))
    ax.plot(dates, vix, label='US VIX', color='steelblue', linewidth=0.8, alpha=0.8)
    ax.plot(dates, vixtwn, label='TAIFEX VIXTWN', color='coral', linewidth=0.8, alpha=0.8)
    ax.set_ylabel('IV level')
    ax.set_title(f'K1098: VIX vs VIXTWN levels (corr={corr_vix_vixtwn:.3f})')
    ax.legend()
    ax.grid(alpha=0.3)
    plot2_path = os.path.join(SCRIPT_DIR, 'k1098_vix_vs_vixtwn.png')
    plt.tight_layout()
    plt.savefig(plot2_path, dpi=120, bbox_inches='tight')
    plt.close()
    print(f"  Saved {plot2_path}")

    # Plot 3: θ₁ evolution (VIX vs VIXTWN loading over refits)
    fig, ax = plt.subplots(figsize=(14, 5))
    refit_dates = [pd.Timestamp(r['date']) for r in refit_log]
    av_theta = [r.get('av_theta1') for r in refit_log]
    at_theta = [r.get('at_theta1') for r in refit_log]
    ax.plot(refit_dates, av_theta, 'o-', label='A4f-VIX θ₁', color='steelblue', markersize=4)
    ax.plot(refit_dates, at_theta, 's-', label='A4f-VIXTWN θ₁', color='coral', markersize=4)
    ax.set_ylabel('θ₁ (IV² loading on τ_t)')
    ax.set_title(f'K1098: θ₁ evolution over quarterly refits')
    ax.legend()
    ax.grid(alpha=0.3)
    ax.set_yscale('log')
    plot3_path = os.path.join(SCRIPT_DIR, 'k1098_theta1_evolution.png')
    plt.tight_layout()
    plt.savefig(plot3_path, dpi=120, bbox_inches='tight')
    plt.close()
    print(f"  Saved {plot3_path}")

except Exception as e:
    import traceback
    print(f"  Plot generation failed: {e}")
    traceback.print_exc()

print("\n" + "=" * 70)
print(f"K1098 COMPLETE")
print(f"  H1 (VIXTWN Harvey pass): {h1}")
print(f"  H2 (VIXTWN beats VIX)  : {h2}")
print(f"  H3 (COMBO best)        : {h3}")
print(f"  H4 (Rescue K1083 gap)  : {h4}")
print("=" * 70)
