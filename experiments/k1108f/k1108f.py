#!/usr/bin/env python3
"""
K1108f: Regime-split K1108c 5-foundry pool by semiconductor cycle.
====================================================================
[提出: 賴奕豪, 執行: Claude]  Date: 2026-04-17
Parent: K1108c (commit ?; 4-firm pool N=135 continuous guide_delta_pct NULL)

Motivation (D4 hypothesis)
--------------------------
K1108c's pooled continuous-magnitude regression yielded NULL
(β₁ = -1.29e-05, HAC t = -1.34, p = 0.18). But the semiconductor
industry is strongly cyclical:
  - UP-cycle: 2020 post-COVID restocking + 2024-2026 AI/HBM boom
    → capex RAISE plausibly signals GROWTH (positive β on θ_EAV)
  - DOWN-cycle: 2022-2023 memory/logic inventory correction
    → capex CUT signals DISTRESS (negative β on θ_EAV)
  - Pooling across regimes could mechanically CANCEL these two
    opposite effects → false NULL

If K1108f finds significant β_up vs β_down with opposite signs
(Wald F rejecting equality), then K1108c pooled NULL is a MASKING
confounding artifact — and the paper-2 foundry narrative needs a
REGIME-DEPENDENT capex mechanism, not "capex irrelevant".

If K1108f still yields NULL for both regimes (and/or Wald F does not
reject equality), the 4-layer null stack
(K1108 / K1108b / K1108c / K1108f) is confirmed: capex guidance is
NOT the foundry mechanism. Paper 2 must pivot to K1108d/e candidates.

Design
------
Reuse K1108c's merged pool (N=135 events, 4 firms) verbatim:
    theta_eav_empirical per (firm, event_date) as the dependent.
Do NOT refit A4f-EAV (indicated rule: "reuse pool data, DO NOT
rewrite θ_EAV"). This ensures no double-counting or seed drift
relative to K1108c.

Regime dating (fixed a priori; no data-snooping)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  UP:    2020-04-01 to 2021-12-31   (post-COVID recovery)
         2024-01-01 to 2026-04-15   (AI/HBM boom)
  DOWN:  2022-01-01 to 2023-11-30   (inventory correction)
  TRANS: 2020-01-01 to 2020-03-31   (COVID shock)
         2023-12-01 to 2023-12-31   (recovery edge)
  Pre-2020 (2014-2019) events are coded per TSMC-revenue-YoY sign
  for the continuous-proxy spec 2; for Spec 1 they default to
  "NEUTRAL" and are excluded from the regime-split primary test
  to keep the regime definitions sharp.

Spec 1 (regime-dummy interaction):
    θ_EAV = β₀ + β_up · guide_delta_pct · 1[UP]
              + β_down · guide_delta_pct · 1[DOWN]
              + ε
  HAC Newey-West SE, auto-bandwidth.
  Wald F-test H₀: β_up = β_down.

Spec 2 (continuous proxy — TSMC revenue YoY, strictly t-1 shift):
    θ_EAV = β₀ + β₁ · guide_delta_pct
              + β₂ · guide_delta_pct · tsmc_rev_yoy_lag
              + ε
  tsmc_rev_yoy_lag is TSMC quarterly revenue YoY growth of the
  PREVIOUS quarter (strict PIT: quarterly data announced ~2 months
  after fiscal quarter end → use quarter t-1 YoY when event falls
  in quarter t).

Bootstrap block (event-cluster) N=1000, seed=42.

Lookahead guard
  - Regime dates fixed at top of file, not learned from data
  - TSMC rev YoY uses strict t-1 quarter (PIT shift)
  - np.random.seed(42) everywhere

Power warning
  If any regime n < 20, that regime is flagged UNDERPOWERED in
  README and JSON output, and the Wald F is reported alongside the
  power caveat.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
import matplotlib.pyplot as plt

import warnings
warnings.filterwarnings('ignore')

np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = 'K1108f'

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent
K1108C_DIR = PROJECT_ROOT / 'experiments' / 'k1108c'

# If running inside a worktree where k1108c/ is not present, fall back to
# the canonical main-tree path.
if not (K1108C_DIR / 'k1108c_merged_pool.csv').exists():
    _MAIN_TREE_K1108C = Path('/Users/yhlai0911/Desktop/volpred-research') / 'experiments' / 'k1108c'
    if (_MAIN_TREE_K1108C / 'k1108c_merged_pool.csv').exists():
        K1108C_DIR = _MAIN_TREE_K1108C

RESULTS_PATH = SCRIPT_DIR / 'k1108f_results.json'
PLOT_SCATTER = SCRIPT_DIR / 'k1108f_scatter_by_regime.png'
PLOT_FOREST = SCRIPT_DIR / 'k1108f_coef_forest.png'


# --------------------------------------------------------------------------
# Regime definitions (fixed a priori)
# --------------------------------------------------------------------------

UP_PERIODS = [
    ('2020-04-01', '2021-12-31'),   # post-COVID recovery
    ('2024-01-01', '2026-04-15'),   # AI / HBM boom
]
DOWN_PERIODS = [
    ('2022-01-01', '2023-11-30'),   # memory/logic inventory correction
]
TRANS_PERIODS = [
    ('2020-01-01', '2020-03-31'),
    ('2023-12-01', '2023-12-31'),
]


def classify_regime(dt: pd.Timestamp) -> str:
    dt = pd.Timestamp(dt)
    for lo, hi in UP_PERIODS:
        if pd.Timestamp(lo) <= dt <= pd.Timestamp(hi):
            return 'UP'
    for lo, hi in DOWN_PERIODS:
        if pd.Timestamp(lo) <= dt <= pd.Timestamp(hi):
            return 'DOWN'
    for lo, hi in TRANS_PERIODS:
        if pd.Timestamp(lo) <= dt <= pd.Timestamp(hi):
            return 'TRANSITION'
    return 'NEUTRAL'   # pre-2020 events


# --------------------------------------------------------------------------
# TSMC quarterly revenue YoY (hand-coded for strict PIT, fallback)
# Values source: TSMC IR / press releases, in NT$ billions (consolidated)
# YoY = (Q - Q_{-4}) / Q_{-4}
# Each quarter's YoY is lagged by 1 quarter (PIT) when assigning to events.
# --------------------------------------------------------------------------
# Quarterly TSMC revenue (NT$ bn, rounded to 1 decimal from press releases)
# Years 2013-2025 Q1-Q4 (2026 partial)
TSMC_QUARTERLY_REV = [
    # (year, quarter, revenue_ntd_bn)
    (2013, 1, 132.5), (2013, 2, 155.9), (2013, 3, 162.6), (2013, 4, 146.0),
    (2014, 1, 148.2), (2014, 2, 183.0), (2014, 3, 209.1), (2014, 4, 222.0),
    (2015, 1, 222.0), (2015, 2, 205.3), (2015, 3, 212.5), (2015, 4, 203.9),
    (2016, 1, 203.9), (2016, 2, 221.8), (2016, 3, 260.4), (2016, 4, 261.6),
    (2017, 1, 233.9), (2017, 2, 213.5), (2017, 3, 252.1), (2017, 4, 277.5),
    (2018, 1, 248.1), (2018, 2, 233.3), (2018, 3, 260.3), (2018, 4, 289.8),
    (2019, 1, 218.7), (2019, 2, 240.9), (2019, 3, 293.0), (2019, 4, 317.2),
    (2020, 1, 310.6), (2020, 2, 310.7), (2020, 3, 356.4), (2020, 4, 361.5),
    (2021, 1, 362.4), (2021, 2, 372.1), (2021, 3, 414.6), (2021, 4, 438.2),
    (2022, 1, 491.0), (2022, 2, 534.1), (2022, 3, 613.1), (2022, 4, 625.5),
    (2023, 1, 508.6), (2023, 2, 480.8), (2023, 3, 546.7), (2023, 4, 625.5),
    (2024, 1, 592.6), (2024, 2, 673.5), (2024, 3, 759.7), (2024, 4, 869.3),
    (2025, 1, 839.3), (2025, 2, 933.8), (2025, 3, 989.9), (2025, 4, 1015.6),
    (2026, 1, 1050.0),   # placeholder — 2026 Q1 guidance midpoint
]


def build_tsmc_yoy_pit() -> pd.DataFrame:
    """Return DataFrame with quarter_start, rev_yoy, reporting_date (PIT).

    PIT convention: Q revenue announced ~1 month after Q end (TSMC IR).
    So rev_yoy_t available from reporting_date onward.
    For strict t-1 PIT usage, event at time d uses most recent
    (reporting_date <= d) YoY.
    """
    df = pd.DataFrame(TSMC_QUARTERLY_REV, columns=['year', 'quarter', 'rev_ntd_bn'])
    df['quarter_start'] = df.apply(
        lambda r: pd.Timestamp(f'{int(r.year)}-{(int(r.quarter) - 1) * 3 + 1:02d}-01'),
        axis=1,
    )
    df['quarter_end'] = df['quarter_start'] + pd.offsets.QuarterEnd(0)
    # TSMC typically releases monthly rev ~10th of next month; quarterly
    # consolidated revenue aggregated by mid-month after quarter end.
    df['reporting_date'] = df['quarter_end'] + pd.Timedelta(days=15)

    df['rev_yoy'] = df['rev_ntd_bn'].pct_change(periods=4)
    df = df.dropna(subset=['rev_yoy']).reset_index(drop=True)
    return df[['year', 'quarter', 'quarter_start', 'quarter_end',
               'reporting_date', 'rev_ntd_bn', 'rev_yoy']]


def attach_tsmc_yoy_lag(events_df: pd.DataFrame,
                        yoy_df: pd.DataFrame) -> pd.DataFrame:
    """For each event_date, attach the most recent TSMC rev_yoy that was
    REPORTED BEFORE event_date (strict PIT). This is the "t-1 quarter
    YoY" in the sense: YoY from the previous completed & announced
    quarter.
    """
    events_df = events_df.copy()
    events_df['event_date'] = pd.to_datetime(events_df['event_date'])
    yoy_df = yoy_df.sort_values('reporting_date').reset_index(drop=True)

    tsmc_yoy_values = []
    for ed in events_df['event_date']:
        mask = yoy_df['reporting_date'] < ed  # strict: < not <=
        if mask.any():
            last_row = yoy_df.loc[mask].iloc[-1]
            tsmc_yoy_values.append(float(last_row['rev_yoy']))
        else:
            tsmc_yoy_values.append(np.nan)
    events_df['tsmc_rev_yoy_lag'] = tsmc_yoy_values
    return events_df


# --------------------------------------------------------------------------
# Econometric helpers — reused / adapted from K1108c
# --------------------------------------------------------------------------

def newey_west_bw(n):
    return int(np.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))


def ols_hac(y, X, bw=None):
    """OLS + Newey-West HAC-robust SE."""
    n, k = X.shape
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    resid = y - X @ beta

    if bw is None:
        bw = max(newey_west_bw(n), 1)

    S0 = (X * resid[:, None]).T @ (X * resid[:, None]) / n
    S = S0.copy()
    for lag in range(1, bw + 1):
        w = 1.0 - lag / (bw + 1.0)
        Gamma = np.zeros((k, k))
        for t in range(lag, n):
            xt = X[t, :].reshape(-1, 1)
            xtl = X[t - lag, :].reshape(-1, 1)
            Gamma += (resid[t] * resid[t - lag]) * (xt @ xtl.T)
        Gamma /= n
        S += w * (Gamma + Gamma.T)

    cov_hac = n * XtX_inv @ S @ XtX_inv
    se_hac = np.sqrt(np.clip(np.diag(cov_hac), 0, None))
    t_hac = beta / np.where(se_hac > 0, se_hac, np.nan)
    p_hac = 2.0 * (1.0 - stats.norm.cdf(np.abs(t_hac)))

    ss_res = float((resid ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan

    return {
        'beta': beta,
        'cov_hac': cov_hac,
        'se_hac': se_hac,
        't_hac': t_hac,
        'p_hac': p_hac,
        'R2': float(r2),
        'n': int(n),
        'bw': int(bw),
        'ss_res': ss_res,
        'resid': resid,
    }


def wald_test_linear(beta, cov, R, r):
    """Wald test H0: R·beta = r.

    R: (q, k) matrix, r: (q,), beta: (k,), cov: (k, k).
    Returns {F, df, p}.
    """
    R = np.asarray(R, dtype=float)
    r = np.asarray(r, dtype=float)
    diff = R @ beta - r
    middle = R @ cov @ R.T
    # Use pseudo-inverse for numerical stability
    middle_inv = np.linalg.pinv(middle)
    stat = float(diff.T @ middle_inv @ diff)
    q = R.shape[0]
    # As F-statistic (stat / q) with (q, n-k) — but with HAC we typically
    # compare to chi-squared. Report both.
    chi2_p = float(1.0 - stats.chi2.cdf(stat, df=q))
    return {
        'statistic_chi2': stat,
        'df': q,
        'p_chi2': chi2_p,
    }


def block_bootstrap_regime(pool_df, spec, n_reps=1000, block=10, seed=42):
    """Block bootstrap within firm; return array of (β_up, β_down) replicates
    for spec='regime_dummy', or (β1, β2) for spec='continuous_yoy'.
    """
    rng = np.random.default_rng(seed)
    replicates = []
    firms = pool_df['stock'].unique()
    firm_frames = {f: pool_df.loc[pool_df['stock'] == f].reset_index(drop=True)
                   for f in firms}

    for r in range(n_reps):
        sampled_rows = []
        for f, df in firm_frames.items():
            n = len(df)
            if n == 0:
                continue
            n_blocks = int(np.ceil(n / block))
            for _ in range(n_blocks):
                start = rng.integers(0, max(n - block + 1, 1))
                sampled_rows.append(df.iloc[start:start + block])
        boot = pd.concat(sampled_rows, ignore_index=True)

        try:
            if spec == 'regime_dummy':
                y = boot['theta_eav_empirical'].values
                up_x = boot['guide_delta_pct'].values * (boot['regime'] == 'UP').values
                dn_x = boot['guide_delta_pct'].values * (boot['regime'] == 'DOWN').values
                X = np.column_stack([np.ones(len(y)), up_x, dn_x])
                XtX_inv = np.linalg.pinv(X.T @ X)
                b = XtX_inv @ X.T @ y
                replicates.append((b[1], b[2]))
            elif spec == 'continuous_yoy':
                y = boot['theta_eav_empirical'].values
                x1 = boot['guide_delta_pct'].values
                x2 = boot['guide_delta_pct'].values * boot['tsmc_rev_yoy_lag'].values
                X = np.column_stack([np.ones(len(y)), x1, x2])
                XtX_inv = np.linalg.pinv(X.T @ X)
                b = XtX_inv @ X.T @ y
                replicates.append((b[1], b[2]))
        except Exception:
            continue
    return np.array(replicates)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def run_experiment():
    print(f"=== {EXPERIMENT_ID}: Regime-split K1108c pooled capex regression ===")
    print(f"Seed=42, starting at {time.strftime('%H:%M:%S')}")

    # 1. Load K1108c merged pool (DO NOT rewrite θ_EAV per task spec)
    merged_path = K1108C_DIR / 'k1108c_merged_pool.csv'
    if not merged_path.exists():
        raise SystemExit(f"Missing {merged_path} — K1108c must be present")

    pool = pd.read_csv(merged_path)
    pool['event_date'] = pd.to_datetime(pool['event_date']).dt.tz_localize(None)
    print(f"Loaded K1108c pool: N={len(pool)}, "
          f"firms={pool['stock'].nunique()}, "
          f"date range [{pool['event_date'].min().date()} .. "
          f"{pool['event_date'].max().date()}]")

    # 2. Regime classification
    pool['regime'] = pool['event_date'].apply(classify_regime)
    regime_counts = pool['regime'].value_counts()
    print("\n>>> Regime classification (fixed a priori):")
    for r, n in regime_counts.items():
        print(f"    {r}: {n}")

    # Power warning check
    n_up = int((pool['regime'] == 'UP').sum())
    n_down = int((pool['regime'] == 'DOWN').sum())
    underpower_flag = False
    power_warnings = []
    if n_up < 20:
        underpower_flag = True
        power_warnings.append(f"UP regime n={n_up} < 20 → UNDERPOWERED")
    if n_down < 20:
        underpower_flag = True
        power_warnings.append(f"DOWN regime n={n_down} < 20 → UNDERPOWERED")
    for w in power_warnings:
        print(f"    ⚠️ {w}")

    # 3. TSMC revenue YoY PIT merge (for Spec 2)
    yoy_df = build_tsmc_yoy_pit()
    pool = attach_tsmc_yoy_lag(pool, yoy_df)
    n_missing_yoy = int(pool['tsmc_rev_yoy_lag'].isna().sum())
    print(f"\n>>> TSMC rev YoY PIT merge: "
          f"{len(pool) - n_missing_yoy}/{len(pool)} events have valid t-1 YoY "
          f"(missing: {n_missing_yoy} pre-2014Q1 events)")

    # 4. Spec 1 — regime dummy interaction
    print("\n>>> SPEC 1: θ_EAV = β₀ + β_up·Δpct·1[UP] + β_down·Δpct·1[DOWN]")
    primary_pool = pool.loc[pool['regime'].isin(['UP', 'DOWN'])].reset_index(drop=True)
    print(f"    Primary analysis pool (UP ∪ DOWN): N={len(primary_pool)}")

    y1 = primary_pool['theta_eav_empirical'].values
    up_mask = (primary_pool['regime'] == 'UP').values.astype(float)
    dn_mask = (primary_pool['regime'] == 'DOWN').values.astype(float)
    dx = primary_pool['guide_delta_pct'].values
    X1 = np.column_stack([np.ones(len(y1)), dx * up_mask, dx * dn_mask])
    spec1 = ols_hac(y1, X1)

    b_up = float(spec1['beta'][1])
    b_dn = float(spec1['beta'][2])
    se_up = float(spec1['se_hac'][1])
    se_dn = float(spec1['se_hac'][2])
    t_up = float(spec1['t_hac'][1])
    t_dn = float(spec1['t_hac'][2])
    p_up = float(spec1['p_hac'][1])
    p_dn = float(spec1['p_hac'][2])

    print(f"    β_up   = {b_up:+.4e}  SE={se_up:.4e}  t={t_up:+.3f}  p={p_up:.4f}")
    print(f"    β_down = {b_dn:+.4e}  SE={se_dn:.4e}  t={t_dn:+.3f}  p={p_dn:.4f}")

    # Wald F: β_up = β_down
    wald1 = wald_test_linear(spec1['beta'], spec1['cov_hac'],
                             R=np.array([[0.0, 1.0, -1.0]]), r=[0.0])
    print(f"    Wald χ² (β_up = β_down) = {wald1['statistic_chi2']:.3f} "
          f"(df={wald1['df']}, p={wald1['p_chi2']:.4f})")

    # 5. Spec 2 — continuous proxy (TSMC rev YoY interaction)
    print("\n>>> SPEC 2: θ_EAV = β₀ + β₁·Δpct + β₂·Δpct·TSMC_YoY_lag")
    pool_yoy = pool.dropna(subset=['tsmc_rev_yoy_lag']).reset_index(drop=True)
    print(f"    Spec 2 pool: N={len(pool_yoy)} (after dropping pre-data events)")

    y2 = pool_yoy['theta_eav_empirical'].values
    dx2 = pool_yoy['guide_delta_pct'].values
    yoy2 = pool_yoy['tsmc_rev_yoy_lag'].values
    X2 = np.column_stack([np.ones(len(y2)), dx2, dx2 * yoy2])
    spec2 = ols_hac(y2, X2)

    b1 = float(spec2['beta'][1])
    b2 = float(spec2['beta'][2])
    se_b1 = float(spec2['se_hac'][1])
    se_b2 = float(spec2['se_hac'][2])
    t_b1 = float(spec2['t_hac'][1])
    t_b2 = float(spec2['t_hac'][2])
    p_b1 = float(spec2['p_hac'][1])
    p_b2 = float(spec2['p_hac'][2])

    print(f"    β₁ (Δpct main)         = {b1:+.4e}  t={t_b1:+.3f}  p={p_b1:.4f}")
    print(f"    β₂ (Δpct × YoY interact)= {b2:+.4e}  t={t_b2:+.3f}  p={p_b2:.4f}")

    # 6. Block bootstrap — Spec 1
    print("\n>>> Block bootstrap Spec 1 (N=1000, block=10)")
    boot1 = block_bootstrap_regime(primary_pool, spec='regime_dummy',
                                   n_reps=1000, block=10, seed=42)
    boot1_up = boot1[:, 0]
    boot1_dn = boot1[:, 1]
    print(f"    β_up   bootstrap mean={np.mean(boot1_up):+.3e}  "
          f"95% CI=[{np.percentile(boot1_up, 2.5):+.3e}, "
          f"{np.percentile(boot1_up, 97.5):+.3e}]")
    print(f"    β_down bootstrap mean={np.mean(boot1_dn):+.3e}  "
          f"95% CI=[{np.percentile(boot1_dn, 2.5):+.3e}, "
          f"{np.percentile(boot1_dn, 97.5):+.3e}]")
    boot1_diff = boot1_up - boot1_dn
    boot1_diff_ci = (float(np.percentile(boot1_diff, 2.5)),
                     float(np.percentile(boot1_diff, 97.5)))
    boot1_diff_p = float(2 * min(np.mean(boot1_diff >= 0),
                                 np.mean(boot1_diff <= 0)))
    print(f"    Bootstrap (β_up − β_down) 95% CI = "
          f"[{boot1_diff_ci[0]:+.3e}, {boot1_diff_ci[1]:+.3e}]  "
          f"p={boot1_diff_p:.4f}")

    # 7. Block bootstrap — Spec 2 (interaction β₂)
    print("\n>>> Block bootstrap Spec 2 β₂ (N=1000, block=10)")
    boot2 = block_bootstrap_regime(pool_yoy, spec='continuous_yoy',
                                   n_reps=1000, block=10, seed=42)
    boot2_b1 = boot2[:, 0]
    boot2_b2 = boot2[:, 1]
    print(f"    β₁ bootstrap mean={np.mean(boot2_b1):+.3e}  "
          f"95% CI=[{np.percentile(boot2_b1, 2.5):+.3e}, "
          f"{np.percentile(boot2_b1, 97.5):+.3e}]")
    print(f"    β₂ bootstrap mean={np.mean(boot2_b2):+.3e}  "
          f"95% CI=[{np.percentile(boot2_b2, 2.5):+.3e}, "
          f"{np.percentile(boot2_b2, 97.5):+.3e}]")

    # 8. Verdict decision
    verdict = decide_verdict(
        b_up, t_up, b_dn, t_dn, wald1,
        t_b2, n_up, n_down, underpower_flag,
    )
    print(f"\n>>> VERDICT: {verdict['label']}")
    for bullet in verdict['bullets']:
        print(f"    - {bullet}")

    # 9. Plots
    plot_scatter_by_regime(pool, b_up, b_dn, spec1['beta'][0])
    plot_coefficient_forest(b_up, se_up, b_dn, se_dn,
                            b1, se_b1, b2, se_b2,
                            n_up, n_down, len(pool_yoy))

    # 10. Persist
    runtime = float(time.time() - START_TIME)
    results = {
        'experiment_id': EXPERIMENT_ID,
        'parent': 'K1108c (continuous pooled NULL)',
        'hypothesis': 'D4: capex guidance sensitivity is regime-dependent',
        'timestamp': pd.Timestamp.utcnow().isoformat(),
        'data_source': [
            'experiments/k1108c/k1108c_merged_pool.csv (N=135 events, 4 firms, θ_EAV reused verbatim)',
            'TSMC quarterly revenue (NT$ bn) hand-coded 2013Q1-2026Q1 from TSMC IR press releases',
        ],
        'regime_definition': {
            'UP_PERIODS': UP_PERIODS,
            'DOWN_PERIODS': DOWN_PERIODS,
            'TRANS_PERIODS': TRANS_PERIODS,
            'note': 'Fixed a priori at top of k1108f.py; not data-adaptive.',
        },
        'regime_counts': {k: int(v) for k, v in regime_counts.items()},
        'power': {
            'n_up': n_up,
            'n_down': n_down,
            'underpowered': underpower_flag,
            'warnings': power_warnings,
        },
        'spec1_regime_dummy': {
            'description': 'θ_EAV = β₀ + β_up·Δpct·1[UP] + β_down·Δpct·1[DOWN]',
            'n': int(spec1['n']),
            'beta0': float(spec1['beta'][0]),
            'beta_up': b_up,
            'se_hac_up': se_up,
            't_hac_up': t_up,
            'p_hac_up': p_up,
            'beta_down': b_dn,
            'se_hac_down': se_dn,
            't_hac_down': t_dn,
            'p_hac_down': p_dn,
            'R2': float(spec1['R2']),
            'newey_west_bw': int(spec1['bw']),
            'wald_up_eq_down_chi2': wald1['statistic_chi2'],
            'wald_p_chi2': wald1['p_chi2'],
        },
        'spec2_continuous_yoy': {
            'description': 'θ_EAV = β₀ + β₁·Δpct + β₂·Δpct·TSMC_YoY_lag (PIT t-1)',
            'n': int(spec2['n']),
            'beta0': float(spec2['beta'][0]),
            'beta1_main': b1,
            'se_hac_b1': se_b1,
            't_hac_b1': t_b1,
            'p_hac_b1': p_b1,
            'beta2_interaction': b2,
            'se_hac_b2': se_b2,
            't_hac_b2': t_b2,
            'p_hac_b2': p_b2,
            'R2': float(spec2['R2']),
            'newey_west_bw': int(spec2['bw']),
        },
        'block_bootstrap_spec1': {
            'n_reps': 1000,
            'block_size': 10,
            'beta_up_mean': float(np.mean(boot1_up)),
            'beta_up_ci_95': [float(np.percentile(boot1_up, 2.5)),
                              float(np.percentile(boot1_up, 97.5))],
            'beta_down_mean': float(np.mean(boot1_dn)),
            'beta_down_ci_95': [float(np.percentile(boot1_dn, 2.5)),
                                float(np.percentile(boot1_dn, 97.5))],
            'diff_up_minus_down_ci_95': list(boot1_diff_ci),
            'diff_up_minus_down_p_two_sided': boot1_diff_p,
        },
        'block_bootstrap_spec2': {
            'n_reps': 1000,
            'block_size': 10,
            'beta1_mean': float(np.mean(boot2_b1)),
            'beta1_ci_95': [float(np.percentile(boot2_b1, 2.5)),
                            float(np.percentile(boot2_b1, 97.5))],
            'beta2_mean': float(np.mean(boot2_b2)),
            'beta2_ci_95': [float(np.percentile(boot2_b2, 2.5)),
                            float(np.percentile(boot2_b2, 97.5))],
        },
        'verdict': verdict,
        'comparison_stack': {
            'K1108': 'TSMC single-firm N=48 INCONCLUSIVE (t=0.94)',
            'K1108b': 'Pool binary N=136 DECISIVE NULL (pool Wald t=-0.0003)',
            'K1108c': 'Pool continuous N=135 DECISIVE NULL (β₁=-1.29e-05, t=-1.34)',
            'K1108f': f"Pool regime-split ({verdict['label']})",
        },
        'references': [
            'K1108c (parent: continuous magnitude NULL)',
            'Newey & West (1987) HAC SE',
            'Andrews (1991) automatic bandwidth',
            'Harvey et al. (2016) t > 3.0 multi-testing threshold',
            'Politis & Romano (1994) stationary bootstrap',
            'Wald (1943) large-sample χ² test',
        ],
        'random_seed': 42,
        'runtime_seconds': runtime,
    }
    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults written: {RESULTS_PATH}")
    print(f"Total runtime: {runtime:.1f}s")
    return results


def decide_verdict(b_up, t_up, b_dn, t_dn, wald,
                   t_b2, n_up, n_down, underpowered):
    """
    PASS criterion (primary):
      EITHER {max(|t_up|, |t_dn|) > 3.0 (Harvey) AND wald p_chi2 < 0.05}
      OR the Spec 2 interaction |t_b2| > 3.0

    PARTIAL: 2 < |t| < 3 for either coefficient AND Wald p < 0.10
    NULL: |t_up| < 2 AND |t_dn| < 2 AND Wald p > 0.10 AND |t_b2| < 2

    Underpowered flag is appended but does not re-label NULL to
    INCONCLUSIVE — the task spec requires explicit power warning.
    """
    bullets = []
    bullets.append(f"β_up   = {b_up:+.3e}  t_HAC = {t_up:+.3f}  (n_up={n_up})")
    bullets.append(f"β_down = {b_dn:+.3e}  t_HAC = {t_dn:+.3f}  (n_dn={n_down})")
    bullets.append(f"Wald χ² (β_up = β_down) = {wald['statistic_chi2']:.3f}  "
                   f"p = {wald['p_chi2']:.4f}")
    bullets.append(f"Spec 2 |t_b2| (interaction) = {abs(t_b2):.3f}")

    harvey_pass_any = (max(abs(t_up), abs(t_dn)) > 3.0 and wald['p_chi2'] < 0.05)
    harvey_pass_interaction = abs(t_b2) > 3.0

    partial = ((max(abs(t_up), abs(t_dn)) > 2.0 and wald['p_chi2'] < 0.10)
               or (2.0 < abs(t_b2) <= 3.0))

    null_final = (abs(t_up) < 2.0 and abs(t_dn) < 2.0
                  and wald['p_chi2'] > 0.10
                  and abs(t_b2) < 2.0)

    if harvey_pass_any or harvey_pass_interaction:
        label = 'H1_REGIME_DEPENDENT_PASS'
        conclusion = (
            "K1108c pooled NULL was MASKING regime-dependent capex "
            "sensitivity. Foundry mechanism is capex × regime, not "
            "capex alone. Paper 2 narrative: retain capex but gate by "
            "semiconductor cycle."
        )
    elif partial:
        label = 'H3_REGIME_PARTIAL'
        conclusion = (
            "Partial regime-dependent signal (|t| in [2,3]). Not "
            "Harvey-robust but suggests pooled NULL hides some "
            "heterogeneity. Next step: fit more firms or longer sample."
        )
    elif null_final:
        label = 'H2_REGIME_NULL_CONFIRMED'
        conclusion = (
            "4-layer null stack (K1108 / K1108b / K1108c / K1108f) "
            "CONFIRMS capex guidance is NOT the foundry θ₂>0 mechanism, "
            "whether as binary flag, continuous magnitude, OR regime-"
            "interacted. Paper 2 must pivot to K1108d/e (non-capex "
            "quantitative guidance, operating leverage)."
        )
    else:
        label = 'INCONCLUSIVE'
        conclusion = (
            "Borderline case — one but not both NULL criteria met. "
            "Report both coefficient sets and defer narrative decision."
        )

    if underpowered:
        bullets.append("⚠️ UNDERPOWERED regime(s) — interpret with caution")

    return {
        'label': label,
        'bullets': bullets,
        'conclusion_vs_K1108c_pool': conclusion,
    }


def plot_scatter_by_regime(pool, b_up, b_dn, beta0):
    fig, ax = plt.subplots(figsize=(10, 6))
    color_map = {'UP': 'tab:green', 'DOWN': 'tab:red',
                 'TRANSITION': 'tab:orange', 'NEUTRAL': 'tab:gray'}
    marker_map = {'UP': 'o', 'DOWN': 's', 'TRANSITION': '^', 'NEUTRAL': 'x'}

    for regime, color in color_map.items():
        sub = pool.loc[pool['regime'] == regime]
        if len(sub) == 0:
            continue
        ax.scatter(sub['guide_delta_pct'], sub['theta_eav_empirical'],
                   s=30, alpha=0.7, color=color,
                   marker=marker_map[regime],
                   label=f'{regime} (n={len(sub)})')

    x_range = np.linspace(pool['guide_delta_pct'].min(),
                          pool['guide_delta_pct'].max(), 100)
    ax.plot(x_range, beta0 + b_up * x_range, color='tab:green', lw=2,
            ls='--', label=f'UP fit slope={b_up:+.2e}')
    ax.plot(x_range, beta0 + b_dn * x_range, color='tab:red', lw=2,
            ls='--', label=f'DOWN fit slope={b_dn:+.2e}')
    ax.axhline(0, color='black', lw=0.5, ls=':')
    ax.axvline(0, color='black', lw=0.5, ls=':')
    ax.set_xlabel('guide_delta_pct (%)')
    ax.set_ylabel('θ_EAV_empirical')
    ax.set_title('K1108f: Regime-split scatter of θ_EAV vs capex guide Δpct')
    ax.legend(loc='best', fontsize=9)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(PLOT_SCATTER, dpi=120)
    plt.close()
    print(f"Saved {PLOT_SCATTER}")


def plot_coefficient_forest(b_up, se_up, b_dn, se_dn,
                            b1_cont, se_b1_cont, b2_int, se_b2_int,
                            n_up, n_down, n_spec2):
    fig, ax = plt.subplots(figsize=(10, 5))
    labels = [f'β_up (n={n_up})',
              f'β_down (n={n_down})',
              f'β₁ Spec2 main (n={n_spec2})',
              f'β₂ Spec2 YoY interact (n={n_spec2})']
    betas = [b_up, b_dn, b1_cont, b2_int]
    ses = [se_up, se_dn, se_b1_cont, se_b2_int]
    colors = ['tab:green', 'tab:red', 'tab:blue', 'tab:purple']

    y_pos = np.arange(len(labels))[::-1]
    for y, b, se, c in zip(y_pos, betas, ses, colors):
        lo = b - 1.96 * se
        hi = b + 1.96 * se
        ax.errorbar([b], [y], xerr=[[b - lo], [hi - b]],
                    fmt='o', color=c, capsize=5, lw=2, markersize=8)
    ax.axvline(0, color='black', lw=0.8, ls='--')
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels)
    ax.set_xlabel('Coefficient (with HAC 95% CI)')
    ax.set_title('K1108f: Regime-split coefficient forest plot')
    ax.grid(alpha=0.3, axis='x')
    plt.tight_layout()
    plt.savefig(PLOT_FOREST, dpi=120)
    plt.close()
    print(f"Saved {PLOT_FOREST}")


if __name__ == '__main__':
    run_experiment()
