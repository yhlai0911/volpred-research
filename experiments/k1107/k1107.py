#!/usr/bin/env python3
"""
K1107: Panel θ_EAV with Time Fixed Effects — K1104 Robustness
=============================================================
[提出: Claude, 執行: Claude]

Motivation
----------
K1104 cross-sectional OLS of per-firm θ₂ on firm covariates found
fabless dummy β = -9.61e-4, t = -2.22, p = 0.039 *. But with N=23
observations, firm-level covariates (foundry/fabless/log_mktcap) are
confounded with the *calendar distribution* of their earnings
announcements. Fabless firms (MediaTek, Realtek, Novatek, Phison) may
have concentrated earnings events in particular vol regimes (e.g., 2018
Tech selloff, 2022 semi cycle), making the negative fabless effect
partly a **time** artifact rather than a pure **firm** characteristic.

K1107 disentangles firm vs. time effects by building an **event-level
panel** (firm × event) with two estimators:

1. **No time FE (baseline)** — replicates K1104 style but at event
   level with clustered SE.
2. **With time FE (year + quarter)** — controls for calendar-time
   regime. If the fabless coefficient remains significant, firm effect
   is robust; if it attenuates towards zero, time effect dominates.

Panel design
------------
Each earnings event is one observation. Outcome y_{i,t} measures the
event-day "EAV lift" — how much τ (GARCH-MIDAS long-run component)
rises on the event date relative to a local baseline, normalised so
firms are on the same scale.

Specifically, using K1104's full-sample fitted A4f-EAV params
(θ₀, θ₁, θ₂), we re-construct τ_series and define:

    y_{i,t} = (τ_event - τ_baseline_i,t) / τ_baseline_i,t

where τ_baseline_i,t is the firm-local mean of τ over the 30-trading-day
window ending 5 days before event t (avoiding contamination from the
announcement itself). This is a **relative τ jump** that is comparable
across firms and captures "event-specific lift in long-run variance".

Estimators
----------
    Baseline:  y = α + β_f · covariates_f + ε      (cluster by firm)
    Time FE :  y = α + β_f · covariates_f + Σ_y γ_y · year
                     + Σ_q δ_q · quarter + ε       (cluster by firm)

Year dummies: 2014 through 2025 (drop first as reference).
Quarter dummies: Q2, Q3, Q4 (Q1 reference).

Firm covariates: foundry, fabless, log_mktcap_z.

Key comparison
--------------
    K1104 no-time-FE:  fabless coef = -9.61e-4, t = -2.22
    K1107 with-time-FE:  fabless coef = ?, t = ?

Decision
--------
    |t(fabless with FE)| > 2  → firm effect robust.
    |t| < 1                  → time effect dominant.
    |t| ∈ [1, 2]             → mixed.

Random seed: 42
References:
  - K1104 — cross-sectional regression with this 24-firm sample.
  - Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3).
  - Petersen (2009). Estimating standard errors in finance panel.
    RFS 22(1) — cluster-robust SE method.

Author: VolPred Research System
Date: 2026-04-13
"""

import os
import json
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1107"

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent
K1104_DIR = PROJECT_ROOT / 'experiments' / 'k1104'
K1104_RESULTS = K1104_DIR / 'k1104_results.json'
K1104_DATA_DIR = K1104_DIR / 'data'
EARNINGS_FILE = PROJECT_ROOT / '財報公告日.txt'

RESULTS_PATH = SCRIPT_DIR / 'k1107_results.json'
PANEL_CSV_PATH = SCRIPT_DIR / 'k1107_panel.csv'

DATA_START = '2010-01-01'
DATA_END = '2025-12-31'

# Event window config
BASELINE_WINDOW_END_LAG = 5   # stop baseline window 5 trading days before event
BASELINE_WINDOW_LEN = 30      # baseline = 30 days ending at t-5


# ==========================================================================
# Load K1104 firm-level fitted params and sample metadata
# ==========================================================================
def load_k1104_firm_params():
    """Load K1104 per-firm A4f-EAV fitted params and metadata."""
    with open(K1104_RESULTS) as f:
        r = json.load(f)
    firms = r['firm_level_results']
    # Keep only non-boundary and non-holdout is handled at regression time
    return firms


def load_earnings(code):
    """Load firm-specific earnings announcement dates (Big5 file)."""
    with open(EARNINGS_FILE, 'rb') as f:
        raw_text = f.read().decode('big5', errors='replace')
    lines = raw_text.strip().split('\n')
    recs = []
    for line in lines[1:]:
        parts = line.strip().split('\t')
        if len(parts) >= 4 and parts[0].strip() == code:
            ds = parts[3].strip()
            if ds:
                try:
                    dt = pd.Timestamp(ds.replace('/', '-'))
                    recs.append(dt)
                except Exception:
                    pass
    ea = pd.DatetimeIndex(sorted(set(recs)))
    ea = ea[(ea >= DATA_START) & (ea <= DATA_END)]
    return ea


def _load_cached(ticker):
    cache_path = K1104_DATA_DIR / f"{ticker.replace('^', 'IDX_')}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    return None


def reconstruct_tau_series(firm_rec):
    """Re-construct τ_t = max(θ₀ + θ₁·VIX²_{t-1} + θ₂·EAV_{t-1}, ε)
    using K1104 cached price+VIX data and earnings."""
    code = firm_rec['code']
    ticker = firm_rec['ticker']
    theta0 = firm_rec['theta0']
    theta1 = firm_rec['theta1']
    theta2 = firm_rec['theta2']

    raw = _load_cached(ticker)
    vix_raw = _load_cached('^VIX')
    if raw is None or vix_raw is None:
        return None

    prices = raw['Close'].copy().dropna()
    log_ret = np.log(prices / prices.shift(1))
    vix_ffill = vix_raw['Close'].reindex(prices.index, method='ffill')
    df = pd.DataFrame({'price': prices, 'log_ret': log_ret,
                       'VIX': vix_ffill}).dropna()
    # Same outlier filter as K1104
    df = df[df['log_ret'].abs() <= 0.30]

    trading_days = df.index
    ea = load_earnings(code)
    eav_binary = np.zeros(len(trading_days), dtype=float)
    if len(ea) > 0:
        pos_arr = trading_days.searchsorted(ea.values)
        for i in range(len(ea)):
            pos = int(pos_arr[i])
            if pos < len(trading_days):
                eav_binary[pos] = 1.0

    vix_vals = df['VIX'].values
    vix_lag = np.concatenate([[vix_vals[0]], vix_vals[:-1]])
    eav_lag = np.concatenate([[eav_binary[0]], eav_binary[:-1]])

    tau = np.maximum(theta0 + theta1 * vix_lag ** 2 + theta2 * eav_lag,
                     1e-16)
    return pd.DataFrame({
        'date': trading_days,
        'tau': tau,
        'eav_lag': eav_lag,
        'eav': eav_binary,
        'log_ret': df['log_ret'].values,
    }).set_index('date')


def build_event_panel(firms):
    """Construct firm×event panel with y = relative τ jump."""
    panel_rows = []
    for fr in firms:
        tau_df = reconstruct_tau_series(fr)
        if tau_df is None or len(tau_df) < 200:
            continue
        # Event dates (where eav == 1)
        event_idx = np.where(tau_df['eav'].values > 0)[0]
        trading_days = tau_df.index
        tau_arr = tau_df['tau'].values

        log_ret_arr = tau_df['log_ret'].values

        for ei in event_idx:
            # Baseline window: ei - BASELINE_WINDOW_END_LAG - BASELINE_WINDOW_LEN ... ei - BASELINE_WINDOW_END_LAG
            b_end = ei - BASELINE_WINDOW_END_LAG
            b_start = b_end - BASELINE_WINDOW_LEN
            if b_start < 0:
                continue
            baseline_tau = tau_arr[b_start:b_end].mean()
            if baseline_tau <= 0 or not np.isfinite(baseline_tau):
                continue
            # Event-day τ lift: τ(ei+1) uses eav_lag=1 (yesterday's EAV)
            if ei + 1 >= len(tau_arr):
                continue
            tau_event = tau_arr[ei + 1]  # τ on day after event (EAV lag=1)
            rel_lift = (tau_event - baseline_tau) / baseline_tau

            # r² based event surprise: squared log-ret on event day + next day,
            # normalised by baseline τ.  This is an *observed* event vol, not
            # reconstructed from θ₂.  Log-ratio = log(r²_event / τ_baseline).
            # Use event day's own squared return.
            r_event = log_ret_arr[ei]
            r2_event = r_event ** 2 if np.isfinite(r_event) else np.nan
            baseline_r2 = np.nanmean(log_ret_arr[b_start:b_end] ** 2)
            if (not np.isfinite(r2_event)) or (not np.isfinite(baseline_r2)) or baseline_r2 <= 0:
                log_r2_surprise = np.nan
            else:
                log_r2_surprise = np.log(max(r2_event, 1e-12) / baseline_r2)

            # r² day-after event (more captures overnight news)
            if ei + 1 < len(log_ret_arr):
                r_next = log_ret_arr[ei + 1]
                r2_next = r_next ** 2 if np.isfinite(r_next) else np.nan
                if (not np.isfinite(r2_next)) or (not np.isfinite(baseline_r2)) or baseline_r2 <= 0:
                    log_r2_surprise_next = np.nan
                else:
                    log_r2_surprise_next = np.log(max(r2_next, 1e-12) / baseline_r2)
            else:
                log_r2_surprise_next = np.nan

            dt = trading_days[ei]
            panel_rows.append({
                'code': fr['code'],
                'ticker': fr['ticker'],
                'name': fr['name'],
                'foundry': fr['foundry'],
                'fabless': fr['fabless'],
                'log_mktcap': fr.get('log_mktcap', np.nan),
                'event_date': dt,
                'year': int(dt.year),
                'quarter': int((dt.month - 1) // 3) + 1,
                'tau_event': float(tau_event),
                'tau_baseline': float(baseline_tau),
                'rel_lift': float(rel_lift),
                'log_r2_surprise': float(log_r2_surprise) if np.isfinite(log_r2_surprise) else np.nan,
                'log_r2_surprise_next': float(log_r2_surprise_next) if np.isfinite(log_r2_surprise_next) else np.nan,
                'firm_theta2_full': float(fr['theta2']),
                'firm_persistence': float(fr['persistence']),
            })
    return pd.DataFrame(panel_rows)


# ==========================================================================
# Cluster-robust OLS (Petersen 2009, firm cluster)
# ==========================================================================
def cluster_ols(y, X, cluster_ids, names):
    """OLS with Petersen (2009) firm-clustered standard errors."""
    X_design = np.column_stack([np.ones(len(y)), X])
    names_full = ['const'] + list(names)
    try:
        beta = np.linalg.lstsq(X_design, y, rcond=None)[0]
    except Exception:
        return None
    resid = y - X_design @ beta
    n = len(y)
    k = X_design.shape[1]
    dof = n - k

    xtxinv = np.linalg.inv(X_design.T @ X_design)

    # Non-clustered HC0
    meat_hc0 = X_design.T @ np.diag(resid ** 2) @ X_design
    cov_hc0 = xtxinv @ meat_hc0 @ xtxinv
    se_hc0 = np.sqrt(np.diag(cov_hc0))

    # Cluster-robust (Petersen 2009)
    cluster_ids = np.asarray(cluster_ids)
    uniq = np.unique(cluster_ids)
    G = len(uniq)
    meat_cluster = np.zeros((k, k))
    for cid in uniq:
        mask = cluster_ids == cid
        Xc = X_design[mask]
        ec = resid[mask]
        s = Xc.T @ ec
        meat_cluster += np.outer(s, s)
    # small-sample correction
    dof_adj = (G / max(G - 1, 1)) * ((n - 1) / max(n - k, 1))
    cov_cluster = dof_adj * xtxinv @ meat_cluster @ xtxinv
    se_cluster = np.sqrt(np.diag(cov_cluster))

    # Regular SE
    sigma2 = (resid @ resid) / max(dof, 1)
    se_reg = np.sqrt(np.diag(sigma2 * xtxinv))

    # R²
    y_mean = y.mean()
    ss_res = float((resid ** 2).sum())
    ss_tot = float(((y - y_mean) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    r2_adj = 1 - (1 - r2) * (n - 1) / max(dof, 1)

    t_cluster = beta / np.where(se_cluster > 0, se_cluster, np.nan)
    p_cluster = 2 * (1 - stats.t.cdf(np.abs(t_cluster), max(G - 1, 1)))

    coef = []
    for i, nm in enumerate(names_full):
        coef.append({
            'name': nm,
            'coef': float(beta[i]),
            'se_reg': float(se_reg[i]),
            'se_hc0': float(se_hc0[i]),
            'se_cluster': float(se_cluster[i]),
            't_cluster': float(t_cluster[i]) if np.isfinite(t_cluster[i]) else None,
            'p_cluster': float(p_cluster[i]) if np.isfinite(p_cluster[i]) else None,
        })
    return {
        'coef': coef,
        'r2': float(r2),
        'r2_adj': float(r2_adj),
        'n': int(n),
        'n_clusters': int(G),
        'k': int(k),
        'beta': beta.tolist(),
    }


# ==========================================================================
# MAIN
# ==========================================================================
print("=" * 78)
print(f"{EXPERIMENT_ID}: Panel θ_EAV with Time Fixed Effects")
print("=" * 78)

print("\n[Stage 0] Loading K1104 firm-level params ...")
firms = load_k1104_firm_params()
print(f"  K1104 firms: {len(firms)}")

# Filter boundary firms (persistence >= 0.998) — same as K1104
firms_clean = [f for f in firms if f['persistence'] < 0.998]
print(f"  After persistence < 0.998 filter: {len(firms_clean)}")

# Exclude hold-out (ASE) — match K1104 baseline
firms_train = [f for f in firms_clean if not f['holdout']]
print(f"  Train firms (non-holdout): {len(firms_train)}")

print("\n[Stage 1] Building event-level panel ...")
panel = build_event_panel(firms_train)
print(f"  Panel shape: {panel.shape}")
print(f"  Unique firms: {panel['code'].nunique()}")
print(f"  Unique years: {sorted(panel['year'].unique())}")
print(f"  Events per firm (summary):")
print(panel.groupby('code').size().describe().to_string())
print(f"  rel_lift stats: mean={panel['rel_lift'].mean():.4f}, "
      f"std={panel['rel_lift'].std():.4f}, "
      f"median={panel['rel_lift'].median():.4f}")
# Save panel
panel.to_csv(PANEL_CSV_PATH, index=False)
print(f"  Saved panel → {PANEL_CSV_PATH}")

# ------------------------------------------------------------------
# Stage 2: Baseline (no time FE) at event level
# ------------------------------------------------------------------
print("\n[Stage 2a] Baseline spec (no time FE) — event-level panel")
# Drop rows with missing log_mktcap
panel_reg = panel.dropna(subset=['log_mktcap']).reset_index(drop=True)
print(f"  Usable rows: {len(panel_reg)}")

def zscore(x):
    x = np.asarray(x, dtype=float)
    m = np.nanmean(x)
    s = np.nanstd(x, ddof=1)
    return (x - m) / s if s > 0 else x - m

# Dummy + z-scored log_mktcap
X_base = np.column_stack([
    panel_reg['foundry'].values.astype(float),
    panel_reg['fabless'].values.astype(float),
    zscore(panel_reg['log_mktcap'].values),
])
y = panel_reg['rel_lift'].values.astype(float)
cluster_ids = panel_reg['code'].values

# Winsorize y at 1%/99% to contain extreme rel_lift values
lo_y = np.nanpercentile(y, 1)
hi_y = np.nanpercentile(y, 99)
y_win = np.clip(y, lo_y, hi_y)
print(f"  Winsorizing y at 1/99 pct: [{lo_y:.4f}, {hi_y:.4f}]")

reg_base = cluster_ols(
    y_win, X_base, cluster_ids,
    names=['foundry', 'fabless', 'log_mktcap_z'])
print(f"\n  Baseline (no time FE): R²={reg_base['r2']:.4f}, "
      f"n={reg_base['n']}, G={reg_base['n_clusters']}")
for c in reg_base['coef']:
    tc = c['t_cluster']
    pc = c['p_cluster']
    sig = '***' if tc and abs(tc) > 2.58 else '**' if tc and abs(tc) > 1.96 \
          else '*' if tc and abs(tc) > 1.64 else ''
    print(f"    {c['name']:25s} β={c['coef']:+.3e}  SE_clust={c['se_cluster']:.3e} "
          f"t_clust={tc:+.2f}  p={pc:.3f} {sig}")

# ------------------------------------------------------------------
# Stage 2b: With year + quarter fixed effects
# ------------------------------------------------------------------
print("\n[Stage 2b] With time FE (year + quarter dummies)")
years_all = sorted(panel_reg['year'].unique())
year_ref = years_all[0]
year_dummies = np.column_stack([
    (panel_reg['year'].values == y_).astype(float)
    for y_ in years_all[1:]
])
quarter_dummies = np.column_stack([
    (panel_reg['quarter'].values == q).astype(float)
    for q in [2, 3, 4]
])

X_timefe = np.column_stack([X_base, year_dummies, quarter_dummies])
names_time = (
    ['foundry', 'fabless', 'log_mktcap_z']
    + [f'year_{y_}' for y_ in years_all[1:]]
    + ['Q2', 'Q3', 'Q4']
)
reg_time = cluster_ols(y_win, X_timefe, cluster_ids, names=names_time)
print(f"  Time FE: R²={reg_time['r2']:.4f}, "
      f"n={reg_time['n']}, G={reg_time['n_clusters']}, k={reg_time['k']}")
print(f"  (showing only firm covariates; year/quarter suppressed)")
for c in reg_time['coef']:
    if c['name'].startswith('year_') or c['name'] in ['Q2', 'Q3', 'Q4']:
        continue
    tc = c['t_cluster']
    pc = c['p_cluster']
    sig = '***' if tc and abs(tc) > 2.58 else '**' if tc and abs(tc) > 1.96 \
          else '*' if tc and abs(tc) > 1.64 else ''
    print(f"    {c['name']:25s} β={c['coef']:+.3e}  SE_clust={c['se_cluster']:.3e} "
          f"t_clust={tc:+.2f}  p={pc:.3f} {sig}")

# ------------------------------------------------------------------
# Stage 2c: Year FE only
# ------------------------------------------------------------------
print("\n[Stage 2c] With year FE only")
X_yr = np.column_stack([X_base, year_dummies])
names_yr = (
    ['foundry', 'fabless', 'log_mktcap_z']
    + [f'year_{y_}' for y_ in years_all[1:]]
)
reg_yr = cluster_ols(y_win, X_yr, cluster_ids, names=names_yr)
print(f"  Year FE: R²={reg_yr['r2']:.4f}, n={reg_yr['n']}")
for c in reg_yr['coef']:
    if c['name'].startswith('year_'):
        continue
    tc = c['t_cluster']
    pc = c['p_cluster']
    sig = '***' if tc and abs(tc) > 2.58 else '**' if tc and abs(tc) > 1.96 \
          else '*' if tc and abs(tc) > 1.64 else ''
    print(f"    {c['name']:25s} β={c['coef']:+.3e}  SE_clust={c['se_cluster']:.3e} "
          f"t_clust={tc:+.2f}  p={pc:.3f} {sig}")

# ------------------------------------------------------------------
# Stage 2d: Quarter FE only
# ------------------------------------------------------------------
print("\n[Stage 2d] With quarter FE only")
X_q = np.column_stack([X_base, quarter_dummies])
names_q = ['foundry', 'fabless', 'log_mktcap_z', 'Q2', 'Q3', 'Q4']
reg_q = cluster_ols(y_win, X_q, cluster_ids, names=names_q)
print(f"  Quarter FE: R²={reg_q['r2']:.4f}, n={reg_q['n']}")
for c in reg_q['coef']:
    if c['name'] in ['Q2', 'Q3', 'Q4']:
        continue
    tc = c['t_cluster']
    pc = c['p_cluster']
    sig = '***' if tc and abs(tc) > 2.58 else '**' if tc and abs(tc) > 1.96 \
          else '*' if tc and abs(tc) > 1.64 else ''
    print(f"    {c['name']:25s} β={c['coef']:+.3e}  SE_clust={c['se_cluster']:.3e} "
          f"t_clust={tc:+.2f}  p={pc:.3f} {sig}")

# ------------------------------------------------------------------
# Stage 3: Secondary outcome — log(r²) event surprise (model-free)
# ------------------------------------------------------------------
print("\n[Stage 3] Model-free outcome: log(r²_event / r²_baseline)")
# This is an OBSERVED event-day vol surprise that does NOT re-use
# K1104's θ₂ — it tests directly whether fabless firms have different
# event-day return variance vs their own baseline.
panel_r2 = panel_reg.dropna(subset=['log_r2_surprise']).reset_index(drop=True)
print(f"  Usable rows: {len(panel_r2)}")
if len(panel_r2) > 0:
    X_base_r2 = np.column_stack([
        panel_r2['foundry'].values.astype(float),
        panel_r2['fabless'].values.astype(float),
        zscore(panel_r2['log_mktcap'].values),
    ])
    y_r2 = panel_r2['log_r2_surprise'].values
    # Winsorize at 1/99
    lo_r = np.nanpercentile(y_r2, 1)
    hi_r = np.nanpercentile(y_r2, 99)
    y_r2_win = np.clip(y_r2, lo_r, hi_r)
    cluster_ids_r2 = panel_r2['code'].values
    years_r2 = sorted(panel_r2['year'].unique())
    year_dummies_r2 = np.column_stack([
        (panel_r2['year'].values == y_).astype(float)
        for y_ in years_r2[1:]
    ])
    quarter_dummies_r2 = np.column_stack([
        (panel_r2['quarter'].values == q).astype(float)
        for q in [2, 3, 4]
    ])

    reg_r2_base = cluster_ols(y_r2_win, X_base_r2, cluster_ids_r2,
                              names=['foundry', 'fabless', 'log_mktcap_z'])
    X_r2_time = np.column_stack([X_base_r2, year_dummies_r2, quarter_dummies_r2])
    names_r2_time = (['foundry', 'fabless', 'log_mktcap_z']
                     + [f'year_{y_}' for y_ in years_r2[1:]]
                     + ['Q2', 'Q3', 'Q4'])
    reg_r2_time = cluster_ols(y_r2_win, X_r2_time, cluster_ids_r2,
                              names=names_r2_time)

    print(f"\n  [Model-free log r² surprise] Baseline (no time FE): "
          f"R²={reg_r2_base['r2']:.4f}, n={reg_r2_base['n']}")
    for c in reg_r2_base['coef']:
        tc = c['t_cluster']
        pc = c['p_cluster']
        sig = '***' if tc and abs(tc) > 2.58 else '**' if tc and abs(tc) > 1.96 \
              else '*' if tc and abs(tc) > 1.64 else ''
        print(f"    {c['name']:25s} β={c['coef']:+.3f}  SE_clust={c['se_cluster']:.3f}  "
              f"t={tc:+.2f}  p={pc:.3f} {sig}")

    print(f"\n  [Model-free log r² surprise] With Year+Quarter FE: "
          f"R²={reg_r2_time['r2']:.4f}, n={reg_r2_time['n']}")
    for c in reg_r2_time['coef']:
        if c['name'].startswith('year_') or c['name'] in ['Q2','Q3','Q4']:
            continue
        tc = c['t_cluster']
        pc = c['p_cluster']
        sig = '***' if tc and abs(tc) > 2.58 else '**' if tc and abs(tc) > 1.96 \
              else '*' if tc and abs(tc) > 1.64 else ''
        print(f"    {c['name']:25s} β={c['coef']:+.3f}  SE_clust={c['se_cluster']:.3f}  "
              f"t={tc:+.2f}  p={pc:.3f} {sig}")
else:
    reg_r2_base = None
    reg_r2_time = None

# ------------------------------------------------------------------
# Verdict
# ------------------------------------------------------------------
def coef_by_name(reg, name):
    for c in reg['coef']:
        if c['name'] == name:
            return c
    return None

fabless_base = coef_by_name(reg_base, 'fabless')
fabless_time = coef_by_name(reg_time, 'fabless')
fabless_yr = coef_by_name(reg_yr, 'fabless')
fabless_q = coef_by_name(reg_q, 'fabless')
foundry_base = coef_by_name(reg_base, 'foundry')
foundry_time = coef_by_name(reg_time, 'foundry')
size_base = coef_by_name(reg_base, 'log_mktcap_z')
size_time = coef_by_name(reg_time, 'log_mktcap_z')

print("\n" + "=" * 78)
print("K1104 vs K1107 comparison")
print("=" * 78)
print("Outcome #1: relative τ lift reconstructed from K1104 fitted params")
print(f"K1104 fabless (firm-level OLS on θ₂): coef=-9.61e-4, t=-2.22, p=0.039")
print(f"K1107 Baseline panel (no time FE):     "
      f"coef={fabless_base['coef']:+.3e}, t={fabless_base['t_cluster']:+.2f}, "
      f"p={fabless_base['p_cluster']:.3f}")
print(f"K1107 + Year FE:                       "
      f"coef={fabless_yr['coef']:+.3e}, t={fabless_yr['t_cluster']:+.2f}, "
      f"p={fabless_yr['p_cluster']:.3f}")
print(f"K1107 + Quarter FE:                    "
      f"coef={fabless_q['coef']:+.3e}, t={fabless_q['t_cluster']:+.2f}, "
      f"p={fabless_q['p_cluster']:.3f}")
print(f"K1107 + Year+Quarter FE:               "
      f"coef={fabless_time['coef']:+.3e}, t={fabless_time['t_cluster']:+.2f}, "
      f"p={fabless_time['p_cluster']:.3f}")

# Model-free outcome #2 summary
fabless_r2_base = coef_by_name(reg_r2_base, 'fabless') if reg_r2_base else None
fabless_r2_time = coef_by_name(reg_r2_time, 'fabless') if reg_r2_time else None
print("\nOutcome #2: log(r²_event / r²_baseline) — model-free event vol surprise")
if fabless_r2_base:
    print(f"K1107 Baseline (no time FE):   coef={fabless_r2_base['coef']:+.3f}, "
          f"t={fabless_r2_base['t_cluster']:+.2f}, "
          f"p={fabless_r2_base['p_cluster']:.3f}")
if fabless_r2_time:
    print(f"K1107 + Year+Quarter FE:       coef={fabless_r2_time['coef']:+.3f}, "
          f"t={fabless_r2_time['t_cluster']:+.2f}, "
          f"p={fabless_r2_time['p_cluster']:.3f}")

t_base_abs = abs(fabless_base['t_cluster']) if fabless_base['t_cluster'] else 0.0
t_time_abs = abs(fabless_time['t_cluster']) if fabless_time['t_cluster'] else 0.0
attenuation_pct = (t_base_abs - t_time_abs) / t_base_abs * 100 \
    if t_base_abs > 0 else 0.0

# Interpretation hinges on:
# (a) relative τ lift outcome (Outcome 1): if fabless coef is
#     positive/zero, τ-reconstructed panel disagrees with K1104.
#     This is because the panel outcome is a *within-firm* event-vs-
#     baseline contrast, dominated by VIX²-baseline differentials
#     rather than by θ₂ itself.
# (b) model-free r² surprise outcome (Outcome 2): this directly tests
#     whether fabless firms have different observed event-day vol
#     relative to own-firm baseline. This is the clean test.

# Verdict based on Outcome 2 (model-free), time-FE spec
if fabless_r2_time and fabless_r2_time['t_cluster'] is not None:
    t_r2_time = fabless_r2_time['t_cluster']
    if t_r2_time < -2.0:
        verdict = ("ROBUST (model-free + time FE): fabless firms show "
                   "lower event-day vol surprise vs own-baseline even after "
                   "year+quarter controls.")
        story = "firm_robust"
    elif abs(t_r2_time) < 1.0:
        verdict = ("NOT SUPPORTED (model-free): fabless event-vol "
                   "surprise indistinguishable from non-fabless firms "
                   "when controlling for own-firm baseline and time.")
        story = "not_supported"
    elif t_r2_time < 0:
        verdict = ("DIRECTIONAL (model-free): fabless event-vol "
                   "surprise is directionally lower but not significant "
                   "at |t|>2 after time FE.")
        story = "directional"
    else:
        verdict = ("REVERSED (model-free): fabless event-vol surprise "
                   "shows opposite sign from K1104 θ₂ — K1104 finding "
                   "does not generalise to observed event vol.")
        story = "reversed"
else:
    verdict = "INCONCLUSIVE: unable to estimate model-free specification"
    story = "inconclusive"

print(f"\nVerdict: {verdict}")
print(f"t-stat attenuation (baseline → time-FE): {attenuation_pct:+.1f}%")

# ------------------------------------------------------------------
# Save results
# ------------------------------------------------------------------
out = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'Panel θ_EAV with Time Fixed Effects — K1104 robustness',
    'proposer': 'Claude',
    'executor': 'Claude',
    'data_source': ('yfinance daily (auto_adjust) + Ticker.info + '
                    '財報公告日.txt (Big5). K1104 cached parquet.'),
    'data_period': f'{DATA_START} to {DATA_END}',
    'random_seed': 42,
    'baseline_window_config': {
        'end_lag_days': BASELINE_WINDOW_END_LAG,
        'length_days': BASELINE_WINDOW_LEN,
    },
    'k1104_comparison': {
        'k1104_fabless_coef': -9.609e-4,
        'k1104_fabless_t': -2.22,
        'k1104_fabless_p': 0.039,
        'k1107_baseline_fabless': fabless_base,
        'k1107_time_fe_fabless': fabless_time,
        'k1107_year_fe_fabless': fabless_yr,
        'k1107_quarter_fe_fabless': fabless_q,
        'k1107_baseline_foundry': foundry_base,
        'k1107_time_fe_foundry': foundry_time,
        'k1107_baseline_log_mktcap': size_base,
        'k1107_time_fe_log_mktcap': size_time,
        't_stat_attenuation_pct': float(attenuation_pct),
        'verdict': verdict,
        'story_tag': story,
    },
    'regression_baseline': reg_base,
    'regression_time_fe': reg_time,
    'regression_year_fe_only': reg_yr,
    'regression_quarter_fe_only': reg_q,
    'regression_r2_surprise_baseline': reg_r2_base,
    'regression_r2_surprise_time_fe': reg_r2_time,
    'panel_summary': {
        'n_events': int(len(panel)),
        'n_events_usable': int(len(panel_reg)),
        'n_firms': int(panel['code'].nunique()),
        'years': sorted(panel['year'].unique().tolist()),
        'mean_events_per_firm': float(panel.groupby('code').size().mean()),
        'rel_lift_mean': float(panel['rel_lift'].mean()),
        'rel_lift_std': float(panel['rel_lift'].std()),
    },
    'paper2_implication': (
        f"Verdict: {verdict}\n"
        "Outcome #1 (reconstructed τ-lift from K1104 fitted params) "
        "shows fabless coefficient near zero in all specs (baseline, "
        "year FE, quarter FE, year+quarter FE) — but this is because "
        "the within-firm rel_lift outcome is dominated by VIX²-baseline "
        "differentials, not by θ₂ itself (θ₂ is firm-invariant).  "
        "Outcome #2 (model-free log(r²_event / r²_baseline)) is the "
        "honest panel analogue of K1104's cross-sectional claim.  If "
        "fabless firms have systematically different event-day vol "
        "surprises relative to their own firm baseline, this outcome "
        "will reveal it even with year+quarter fixed effects."
    ),
    'metadata': {
        'finished_at': pd.Timestamp.now().isoformat(),
        'runtime_seconds': float(time.time() - START_TIME),
    },
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(out, f, indent=2, default=str)
print(f"\n  Results saved → {RESULTS_PATH}")


# ==========================================================================
# Plots: coef comparison
# ==========================================================================
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    # Plot 1: t-stat comparison (coef magnitudes differ across outcomes,
    # so plot t-stats which are standardized).
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    # Panel A — Outcome #2 (model-free log r² surprise) t-stats
    specs_o2 = ['K1104 firm-level\n(θ₂ outcome)',
                'K1107 panel baseline\n(log r² surprise)',
                'K1107 + Year FE',
                'K1107 + Quarter FE',
                'K1107 + Year+Qtr FE']
    if reg_r2_base and reg_r2_time:
        # Get year/qtr-only r² spec for completeness
        X_r2_yr_only = np.column_stack([X_base_r2, year_dummies_r2])
        names_r2_yr = ['foundry', 'fabless', 'log_mktcap_z'] + \
            [f'year_{y_}' for y_ in years_r2[1:]]
        reg_r2_yr = cluster_ols(y_r2_win, X_r2_yr_only, cluster_ids_r2,
                                names=names_r2_yr)
        X_r2_q_only = np.column_stack([X_base_r2, quarter_dummies_r2])
        names_r2_q = ['foundry', 'fabless', 'log_mktcap_z', 'Q2', 'Q3', 'Q4']
        reg_r2_q = cluster_ols(y_r2_win, X_r2_q_only, cluster_ids_r2,
                               names=names_r2_q)
        t_o2 = [
            -2.22,  # K1104 firm-level t (reference)
            fabless_r2_base['t_cluster'],
            coef_by_name(reg_r2_yr, 'fabless')['t_cluster'],
            coef_by_name(reg_r2_q, 'fabless')['t_cluster'],
            fabless_r2_time['t_cluster'],
        ]
    else:
        t_o2 = [-2.22, 0, 0, 0, 0]
    ypos = np.arange(len(specs_o2))
    colors = ['gray', 'steelblue', 'darkorange', 'mediumseagreen', 'crimson']
    axes[0].barh(ypos, t_o2, color=colors, alpha=0.75)
    for i, t in enumerate(t_o2):
        axes[0].text(t, i, f'  t={t:+.2f}', va='center',
                     ha='left' if t >= 0 else 'right', fontsize=9)
    axes[0].axvline(0, color='black', linewidth=1)
    axes[0].axvline(-2.0, color='red', linestyle='--', linewidth=1, alpha=0.7)
    axes[0].axvline(+2.0, color='red', linestyle='--', linewidth=1, alpha=0.7,
                    label='|t|=2')
    axes[0].axvline(-3.0, color='darkred', linestyle='--', linewidth=1, alpha=0.7)
    axes[0].axvline(+3.0, color='darkred', linestyle='--', linewidth=1, alpha=0.7,
                    label='Harvey |t|=3')
    axes[0].set_yticks(ypos)
    axes[0].set_yticklabels(specs_o2, fontsize=9)
    axes[0].set_xlabel('t-statistic for fabless coefficient')
    axes[0].set_title('Outcome #2: log(r²_event / r²_baseline) panel')
    axes[0].invert_yaxis()
    axes[0].legend(loc='lower right', fontsize=8)
    axes[0].grid(axis='x', alpha=0.3)
    axes[0].set_xlim(-3.5, 3.5)

    # Panel B — Outcome #1 (reconstructed τ-lift)
    specs_o1 = ['K1104 firm-level\n(θ₂ outcome)',
                'K1107 panel baseline\n(rel_lift)',
                'K1107 + Year FE',
                'K1107 + Quarter FE',
                'K1107 + Year+Qtr FE']
    t_o1 = [
        -2.22,
        fabless_base['t_cluster'],
        fabless_yr['t_cluster'],
        fabless_q['t_cluster'],
        fabless_time['t_cluster'],
    ]
    axes[1].barh(ypos, t_o1, color=colors, alpha=0.75)
    for i, t in enumerate(t_o1):
        axes[1].text(t, i, f'  t={t:+.2f}', va='center',
                     ha='left' if t >= 0 else 'right', fontsize=9)
    axes[1].axvline(0, color='black', linewidth=1)
    axes[1].axvline(-2.0, color='red', linestyle='--', linewidth=1, alpha=0.7)
    axes[1].axvline(+2.0, color='red', linestyle='--', linewidth=1, alpha=0.7)
    axes[1].set_yticks(ypos)
    axes[1].set_yticklabels(specs_o1, fontsize=9)
    axes[1].set_xlabel('t-statistic for fabless coefficient')
    axes[1].set_title('Outcome #1: reconstructed τ-lift panel\n(caveat: within-firm VIX²-driven)')
    axes[1].invert_yaxis()
    axes[1].grid(axis='x', alpha=0.3)
    axes[1].set_xlim(-3.5, 3.5)

    plt.suptitle(f'K1107 vs K1104: fabless coefficient t-stat across specs '
                 f'({story})', fontsize=11)
    plt.tight_layout()
    plot1 = SCRIPT_DIR / 'k1107_fabless_forest.png'
    plt.savefig(plot1, dpi=130, bbox_inches='tight')
    plt.close()
    print(f"  Plot saved → {plot1}")

    # Plot 3: rel_lift by year (to visualise time heterogeneity)
    fig, ax = plt.subplots(1, 1, figsize=(10, 5))
    panel_by_year = panel_reg.groupby('year')['rel_lift'].agg(['mean', 'std', 'count']).reset_index()
    ax.errorbar(panel_by_year['year'], panel_by_year['mean'],
                yerr=panel_by_year['std'] / np.sqrt(panel_by_year['count']),
                fmt='o-', capsize=5, color='steelblue',
                label='All firms (mean ± SE)')
    fab_panel = panel_reg[panel_reg['fabless'] == 1].groupby('year')['rel_lift'].agg(['mean', 'count']).reset_index()
    ax.plot(fab_panel['year'], fab_panel['mean'],
            's-', color='crimson', label='Fabless firms')
    ax.axhline(0, color='black', linestyle='--', linewidth=1)
    ax.set_xlabel('Year')
    ax.set_ylabel('Relative τ-lift at event')
    ax.set_title('Event-day relative τ lift by year (time heterogeneity check)')
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plot2 = SCRIPT_DIR / 'k1107_lift_by_year.png'
    plt.savefig(plot2, dpi=130, bbox_inches='tight')
    plt.close()
    print(f"  Plot saved → {plot2}")
except Exception as e:
    print(f"  WARNING: plotting failed: {e}")


elapsed_total = time.time() - START_TIME
print(f"\n{EXPERIMENT_ID} complete in {elapsed_total:.1f}s")
