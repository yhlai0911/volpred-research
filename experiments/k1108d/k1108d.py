#!/usr/bin/env python3
"""K1108d: non-capex quantitative guidance as foundry θ_EAV mechanism (D2).

[提出: 賴奕豪, 執行: Claude]  Date: 2026-04-17
Parent: K1108c (H2_MAGNITUDE_NULL), K1108e (H_D3_NULL), K1108f (D4 NULL)
Grand-parents: K1108, K1108b

Motivation (5-layer NULL precedent)
-----------------------------------
K1108 (TSMC alone, inconclusive) + K1108b (pool binary NULL) + K1108c
(pool continuous NULL) + K1108e (op_leverage NULL) + K1108f (regime-split
NULL) = 5-layer NULL stack on the foundry-specific mechanism behind
θ_EAV > 0 reported in K1104. Paper 2 narrative requires one more
plausible mechanism test: non-capex quantitative guidance tokens —
utilisation rate delta, wafer ASP guidance delta, R&D spend guidance
delta — that are orthogonal to capex announcements.

D2 hypothesis: if non-capex guidance magnitude explains θ_EAV (whereas
capex does not per K1108c), foundry narrative commits to "earnings-call
quantitative guidance" as the mechanism. If D2 NULLs on top of K1108/b/
c/e/f, the **6-layer NULL** confirms that Paper 2 must commit to the
*industry-fixed-effect, no attributable channel* framing (foundry θ₂>0
is a structural firm-type property not a guidance-event response).

Hypotheses
----------
H_D2_PASS     : any of 3 non-capex |HAC t| > 3.0 (Harvey 2016) AND
                joint partial-F p < 0.05. → Paper 2 commits to non-capex
                guidance as the channel.
H_D2_NULL     : all |HAC t| < 2.0 AND partial-F p > 0.10. → 6-layer
                NULL confirmed; Paper 2 commits to industry-FE framing.
H_D2_PARTIAL  : 2.0 < max|HAC t| < 3.0 OR partial-F p ∈ (0.05, 0.10)
                → suggestive, further testing needed.
H_D2_LOW_COV  : total all-3 coverage < 60% → preliminary only, verdict
                reported with LOW_COVERAGE_PRELIMINARY prefix; treat
                as NULL candidate pending data augmentation.

Data provenance
  - k1108c_merged_pool.csv (θ_EAV_empirical, guide_delta_pct, 135 events,
    4 firms TSMC/UMC/GFS/SMIC)
  - k1108d_noncapex_pool.csv (hand-coded + yfinance-proxy 3-dim non-capex)

Design
------
Stage 1: merge K1108c + K1108d pools on (stock, event_date).
Stage 2: 4 regression specs (pooled OLS HAC + cluster-by-firm sensitivity):
  Spec A: univariate utilisation_delta_pp
  Spec B: univariate wafer_asp_delta_pct
  Spec C: univariate rd_delta_pct
  Spec D: joint (all 3) + firm FE + year FE + guide_delta_pct control
Stage 3: partial-F on {β_util, β_asp, β_rd} = 0 in Spec D.
Stage 4: orthogonality check: does any β survive when capex guide_delta_pct
         is added as a control?
Stage 5: block bootstrap β (firm-stratified, block=5 events, N=1000).

Robustness
  - Median-impute missing non-capex values with firm-group median (then
    run NaN-dropped version as sensitivity).
  - HAND_CODED-only subset regression (high-confidence PIT sample).
  - Coverage < 60% → LOW_COVERAGE_PRELIMINARY label.

Lookahead guard
  - θ_EAV_empirical already lagged in K1108c convention
  - Non-capex values: hand-coded at earnings announcement date;
    proxy from yfinance quarterly_income_stmt treated as disclosed on
    the corresponding announce_date (contemporaneous PIT).

Seed: 42.
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
EXPERIMENT_ID = 'K1108d'

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent
K1108C_POOL_PATH = PROJECT_ROOT / 'experiments' / 'k1108c' / \
    'k1108c_merged_pool.csv'
NONCAPEX_POOL_PATH = SCRIPT_DIR / 'data' / 'k1108d_noncapex_pool.csv'

RESULTS_PATH = SCRIPT_DIR / 'k1108d_results.json'
PLOT_FOREST = SCRIPT_DIR / 'k1108d_coef_forest.png'
PLOT_SCATTER = SCRIPT_DIR / 'k1108d_scatter_best_predictor.png'

PRIMARY_FIRMS = ['2330.TW', '2303.TW', 'GFS', '0981.HK']
NONCAPEX_COLS = ['utilisation_delta_pp', 'wafer_asp_delta_pct',
                 'rd_delta_pct']
NONCAPEX_LABELS = {
    'utilisation_delta_pp': 'Utilisation Δ (pp)',
    'wafer_asp_delta_pct': 'Wafer ASP Δ (%)',
    'rd_delta_pct': 'R&D Δ (%YoY)',
}

COVERAGE_THRESHOLD = 0.60  # 60%


# ==========================================================================
# HAC / cluster-robust / bootstrap helpers (pattern from K1108c/e)
# ==========================================================================
def newey_west_bw(n):
    return int(max(np.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)), 1))


def ols_hac(y, X, bw=None):
    """OLS with Newey-West HAC-robust SE (Andrews 1991 BW)."""
    n, k = X.shape
    XtX_inv = np.linalg.pinv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    resid = y - X @ beta
    if bw is None:
        bw = newey_west_bw(n)

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
        'beta': beta, 'se_hac': se_hac, 't_hac': t_hac, 'p_hac': p_hac,
        'cov_hac': cov_hac, 'R2': float(r2), 'n': int(n), 'bw': int(bw),
        'ss_res': ss_res, 'resid': resid,
    }


def cluster_robust_cov(X, resid, cluster_ids):
    n, k = X.shape
    XtX_inv = np.linalg.pinv(X.T @ X)
    uniq = np.unique(cluster_ids)
    G = len(uniq)
    meat = np.zeros((k, k))
    for g in uniq:
        mask = cluster_ids == g
        Xg = X[mask]
        eg = resid[mask]
        score = Xg.T @ eg
        meat += np.outer(score, score)
    scale = (G / (G - 1.0)) * ((n - 1.0) / (n - k)) if G > 1 else 1.0
    cov = scale * XtX_inv @ meat @ XtX_inv
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    return cov, se


def block_bootstrap_coefs(y, X, firms, n_reps=1000, block=5, seed=42,
                          target_indices=None):
    """Block-bootstrap coefficient distribution. Blocks drawn within firm.

    target_indices: positions in beta to track (e.g. [1,2,3] for
        utilisation/asp/rd in joint spec); returns dict col_idx → array.
    """
    rng = np.random.default_rng(seed)
    k = X.shape[1]
    uniq_firms = np.unique(firms)
    idx_by_firm = {f: np.where(firms == f)[0] for f in uniq_firms}

    if target_indices is None:
        target_indices = list(range(k))

    out = {i: [] for i in target_indices}

    for _ in range(n_reps):
        sel = []
        for f, idxs in idx_by_firm.items():
            m = len(idxs)
            if m == 0:
                continue
            n_blocks = int(np.ceil(m / block))
            for __ in range(n_blocks):
                start = rng.integers(0, max(m - block + 1, 1))
                sel.extend(idxs[start:start + block].tolist())
        sel = np.array(sel, dtype=int)
        ys = y[sel]
        Xs = X[sel, :]
        try:
            XtX_inv = np.linalg.pinv(Xs.T @ Xs)
            b = XtX_inv @ Xs.T @ ys
            for i in target_indices:
                out[i].append(b[i])
        except Exception:
            for i in target_indices:
                out[i].append(np.nan)
    for i in target_indices:
        arr = np.array(out[i])
        out[i] = arr[~np.isnan(arr)]
    return out


# ==========================================================================
# Merge + imputation
# ==========================================================================
def load_merge_pools():
    """Merge K1108c events with K1108d non-capex covariates."""
    events = pd.read_csv(K1108C_POOL_PATH)
    events['event_date'] = pd.to_datetime(events['event_date'])\
        .dt.tz_localize(None)

    noncapex = pd.read_csv(NONCAPEX_POOL_PATH)
    noncapex['announce_date'] = pd.to_datetime(noncapex['announce_date'])\
        .dt.tz_localize(None)

    merged = events.merge(
        noncapex,
        left_on=['stock', 'event_date'],
        right_on=['stock', 'announce_date'],
        how='left',
    )
    return merged


def impute_by_firm_median(df, cols):
    """Median-impute missing values by firm group. Returns df copy with
    new columns {col}_imputed (float) and {col}_was_imputed (0/1)."""
    out = df.copy()
    for c in cols:
        firm_med = out.groupby('stock')[c].transform(lambda s: s.median())
        pool_med = out[c].median()
        imp = out[c].fillna(firm_med)
        imp = imp.fillna(pool_med)
        out[f'{c}_imputed'] = imp.astype(float)
        out[f'{c}_was_imputed'] = out[c].isna().astype(int)
    return out


# ==========================================================================
# Spec builders
# ==========================================================================
def build_univariate_design(df, col, firm_fe=False, year_fe=False,
                            extra_cols=None):
    """Univariate spec: y = β₀ + β₁·col [+ guide_delta_pct] [+ FE]"""
    y = df['theta_eav_empirical'].values
    x = df[col].values
    firms = df['stock'].values
    years = pd.to_datetime(df['event_date']).dt.year.values

    cols = [np.ones(len(df)), x]
    names = ['intercept', col]

    if extra_cols is not None:
        for ec in extra_cols:
            cols.append(df[ec].values)
            names.append(ec)

    if firm_fe:
        uniq = sorted(np.unique(firms))[:-1]
        for f in uniq:
            cols.append((firms == f).astype(float))
            names.append(f'firm_fe_{f}')

    if year_fe:
        uniq = sorted(np.unique(years))[:-1]
        for yr in uniq:
            cols.append((years == yr).astype(float))
            names.append(f'year_fe_{yr}')

    X = np.column_stack(cols)
    return y, X, names, firms


def build_joint_design(df, noncap_cols, firm_fe=False, year_fe=False,
                       extra_cols=None):
    y = df['theta_eav_empirical'].values
    firms = df['stock'].values
    years = pd.to_datetime(df['event_date']).dt.year.values

    cols = [np.ones(len(df))]
    names = ['intercept']

    for nc in noncap_cols:
        cols.append(df[nc].values)
        names.append(nc)

    if extra_cols is not None:
        for ec in extra_cols:
            cols.append(df[ec].values)
            names.append(ec)

    if firm_fe:
        uniq = sorted(np.unique(firms))[:-1]
        for f in uniq:
            cols.append((firms == f).astype(float))
            names.append(f'firm_fe_{f}')

    if year_fe:
        uniq = sorted(np.unique(years))[:-1]
        for yr in uniq:
            cols.append((years == yr).astype(float))
            names.append(f'year_fe_{yr}')

    X = np.column_stack(cols)
    return y, X, names, firms


def run_spec(y, X, names, firms, label, target_col=None):
    res = ols_hac(y, X)
    _, se_cluster = cluster_robust_cov(X, res['resid'], firms)
    t_cluster = res['beta'] / np.where(se_cluster > 0, se_cluster, np.nan)
    p_cluster = 2.0 * (1.0 - stats.norm.cdf(np.abs(t_cluster)))

    out = {
        'spec': label,
        'n': int(res['n']),
        'names': names,
        'beta': res['beta'].tolist(),
        'se_hac': res['se_hac'].tolist(),
        't_hac': res['t_hac'].tolist(),
        'p_hac': res['p_hac'].tolist(),
        'se_cluster_firm': se_cluster.tolist(),
        't_cluster_firm': t_cluster.tolist(),
        'p_cluster_firm': p_cluster.tolist(),
        'R2': float(res['R2']),
        'bw': int(res['bw']),
        'ss_res': float(res['ss_res']),
    }
    if target_col and target_col in names:
        i = names.index(target_col)
        out['target_col'] = target_col
        out['target_beta'] = float(res['beta'][i])
        out['target_se_hac'] = float(res['se_hac'][i])
        out['target_t_hac'] = float(res['t_hac'][i])
        out['target_p_hac'] = float(res['p_hac'][i])
        out['target_se_cluster'] = float(se_cluster[i])
        out['target_t_cluster'] = float(t_cluster[i])
        out['target_p_cluster'] = float(p_cluster[i])
        out['target_ci_95_low'] = float(res['beta'][i] - 1.96 * res['se_hac'][i])
        out['target_ci_95_high'] = float(res['beta'][i] + 1.96 * res['se_hac'][i])
    return out


def partial_f_test(y, X_unrest, names_unrest, noncap_cols):
    """Joint F: β on all 3 noncap_cols == 0."""
    keep_idx = [i for i, n in enumerate(names_unrest) if n not in noncap_cols]
    X_rest = X_unrest[:, keep_idx]

    res_u = ols_hac(y, X_unrest)
    res_r = ols_hac(y, X_rest)
    n, k_u = X_unrest.shape
    k_r = X_rest.shape[1]
    q = k_u - k_r

    num = (res_r['ss_res'] - res_u['ss_res']) / q
    den = res_u['ss_res'] / (n - k_u)
    F = num / den if den > 0 else np.nan
    p_F = 1.0 - stats.f.cdf(F, q, n - k_u) if np.isfinite(F) else np.nan

    return {
        'F_stat': float(F) if np.isfinite(F) else None,
        'p_value': float(p_F) if np.isfinite(p_F) else None,
        'df_num': int(q),
        'df_den': int(n - k_u),
        'n': int(n),
    }


# ==========================================================================
# Verdict
# ==========================================================================
def decide_verdict(univariate_specs, joint_spec, partial_f, coverage_pct,
                   coverage_all3_pct):
    """Apply D2 verdict criteria."""
    bullets = []
    bullets.append(f"Coverage (any-of-3): {coverage_pct*100:.1f}%  "
                   f"(all-3 non-NaN: {coverage_all3_pct*100:.1f}%)")

    max_abs_t = 0.0
    max_cell = ''
    univ_results = []
    for sp in univariate_specs:
        t = abs(sp['target_t_hac']) if np.isfinite(sp['target_t_hac']) else 0
        univ_results.append({
            'col': sp['target_col'],
            'beta': sp['target_beta'],
            't_hac': sp['target_t_hac'],
            'p_hac': sp['target_p_hac'],
            't_cluster': sp['target_t_cluster'],
        })
        bullets.append(
            f"  {sp['target_col']:24s}  β={sp['target_beta']:+.3e}  "
            f"t_HAC={sp['target_t_hac']:+.2f}  t_cluster={sp['target_t_cluster']:+.2f}  "
            f"p_HAC={sp['target_p_hac']:.3f}")
        if t > max_abs_t:
            max_abs_t = t
            max_cell = sp['target_col']

    pf_F = partial_f.get('F_stat')
    pf_p = partial_f.get('p_value')
    bullets.append(f"Partial-F ({{β_util,β_asp,β_rd}}=0): "
                   f"F={pf_F}  p={pf_p}")

    # Low coverage guard
    if coverage_all3_pct < COVERAGE_THRESHOLD:
        bullets.append(f"⚠️ LOW COVERAGE: all-3 coverage "
                       f"{coverage_all3_pct*100:.1f}% < "
                       f"{COVERAGE_THRESHOLD*100:.0f}% → PRELIMINARY ONLY")
        if max_abs_t > 3.0 and pf_p is not None and pf_p < 0.05:
            label = 'H_D2_PASS_LOW_COVERAGE'
            conclusion = (
                f"PRELIMINARY: Under low coverage, max |HAC t|={max_abs_t:.2f}>3 "
                f"on {max_cell} suggests D2 PASS but sample is too sparse "
                f"({coverage_all3_pct*100:.1f}%) to commit Paper 2 narrative. "
                f"Augment data before final verdict."
            )
        else:
            label = 'H_D2_LOW_COVERAGE_PRELIMINARY'
            conclusion = (
                f"LOW COVERAGE PRELIMINARY NULL: max |HAC t|={max_abs_t:.2f}, "
                f"partial-F p={pf_p}, all-3 coverage {coverage_all3_pct*100:.1f}% "
                f"< 60%. Under this sparse sample, non-capex guidance does NOT "
                f"rescue the 5-layer NULL stack. With K1108/b/c/e/f already "
                f"NULL, the foundry θ₂>0 rule is most likely a STRUCTURAL "
                f"industry-fixed-effect (no single-token mechanism). "
                f"Paper 2 narrative should provisionally commit to "
                f"industry-FE framing pending data augmentation."
            )
        return {
            'label': label,
            'max_abs_t_hac': float(max_abs_t),
            'max_cell': max_cell,
            'partial_f_stat': pf_F,
            'partial_f_p': pf_p,
            'coverage_all3_pct': float(coverage_all3_pct),
            'bullets': bullets,
            'conclusion': conclusion,
            'paper2_commitment': ('PROVISIONAL_INDUSTRY_FE_FRAMING'
                                   if 'LOW_COVERAGE' in label
                                   else 'LOW_COVERAGE_INCONCLUSIVE'),
        }

    # Non-low-coverage verdicts
    if max_abs_t > 3.0 and pf_p is not None and pf_p < 0.05:
        label = 'H_D2_PASS'
        conclusion = (
            f"Non-capex guidance PASSES: max |HAC t|={max_abs_t:.2f} on "
            f"{max_cell}; partial-F p={pf_p:.4f}. Paper 2 narrative commits "
            f"to non-capex quantitative guidance as foundry θ_EAV channel."
        )
        commit = 'NON_CAPEX_GUIDANCE_CHANNEL'
    elif max_abs_t > 2.0 and pf_p is not None and pf_p < 0.10:
        label = 'H_D2_PARTIAL'
        conclusion = (
            f"Suggestive but not Harvey-decisive. Max |HAC t|={max_abs_t:.2f} "
            f"in (2,3) OR partial-F p∈(0.05,0.10). Report as partial evidence."
        )
        commit = 'PARTIAL_NEEDS_FURTHER_TESTING'
    else:
        label = 'H_D2_NULL'
        conclusion = (
            f"6-LAYER NULL STACK CONFIRMED. Non-capex guidance NULL "
            f"(max|HAC t|={max_abs_t:.2f}, partial-F p={pf_p}) adds to "
            f"K1108 (capex NULL) + K1108b (pool binary NULL) + K1108c "
            f"(continuous magnitude NULL) + K1108e (op_leverage NULL) + "
            f"K1108f (regime-split NULL). Paper 2 narrative COMMITS to "
            f"*industry-fixed-effect, no attributable channel* framing: "
            f"foundry θ₂>0 is a structural firm-type property rather than "
            f"a guidance-event response."
        )
        commit = 'INDUSTRY_FIXED_EFFECT_NO_ATTRIBUTABLE_CHANNEL'

    return {
        'label': label,
        'max_abs_t_hac': float(max_abs_t),
        'max_cell': max_cell,
        'partial_f_stat': pf_F,
        'partial_f_p': pf_p,
        'coverage_all3_pct': float(coverage_all3_pct),
        'univariate_results': univ_results,
        'bullets': bullets,
        'conclusion': conclusion,
        'paper2_commitment': commit,
    }


# ==========================================================================
# Plots
# ==========================================================================
def plot_forest(univ_specs, joint_spec, out_path):
    """Forest plot of β (utilisation, asp, rd) from univariate + joint."""
    fig, ax = plt.subplots(figsize=(9.5, 5.5))
    y_pos = []
    labels = []
    betas = []
    los = []
    his = []

    # Univariate results (3 rows)
    for i, sp in enumerate(univ_specs):
        y_pos.append(i * 2 + 0)
        labels.append(f"{sp['target_col']} (univariate)")
        b = sp['target_beta']
        se = sp['target_se_hac']
        betas.append(b)
        los.append(b - 1.96 * se)
        his.append(b + 1.96 * se)

    # Joint spec (3 rows)
    names_j = joint_spec['names']
    for i, col in enumerate(NONCAPEX_COLS):
        y_pos.append(i * 2 + 1)
        labels.append(f"{col} (joint+FE+guide)")
        idx = names_j.index(col)
        b = joint_spec['beta'][idx]
        se = joint_spec['se_hac'][idx]
        betas.append(b)
        los.append(b - 1.96 * se)
        his.append(b + 1.96 * se)

    y_pos = np.array(y_pos)
    betas = np.array(betas)
    los = np.array(los)
    his = np.array(his)
    colors = ['C0' if 'univariate' in lb else 'C3' for lb in labels]
    for yp, b, lo, hi, c in zip(y_pos, betas, los, his, colors):
        ax.plot([lo, hi], [yp, yp], color=c, lw=2)
        ax.plot(b, yp, 'o', color=c, markersize=8)
    ax.axvline(0, color='black', lw=0.6, ls='--')
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel('Coefficient β (with 95% CI from HAC SE)')
    ax.set_title(f'K1108d: non-capex guidance coefficients '
                 f'(univariate blue, joint+FE red)')
    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    plt.close()
    print(f"Saved {out_path}")


def plot_scatter_best(merged, best_col, univ_spec, out_path):
    fig, ax = plt.subplots(figsize=(9, 6))
    firms = merged['stock'].unique()
    colors = plt.cm.tab10(np.arange(len(firms)))
    firm_color = {f: colors[i] for i, f in enumerate(firms)}
    for f in firms:
        m = merged['stock'] == f
        sub = merged.loc[m]
        ax.scatter(sub[best_col], sub['theta_eav_empirical'],
                   s=30, alpha=0.7, color=firm_color[f], label=f)
    sub_all = merged.dropna(subset=[best_col])
    if len(sub_all) > 2:
        xs = np.linspace(sub_all[best_col].min(),
                         sub_all[best_col].max(), 100)
        b0 = univ_spec['beta'][0]
        b1 = univ_spec['target_beta']
        ax.plot(xs, b0 + b1 * xs, 'k-', lw=1.8,
                label=f"β₁={b1:+.3e}  t_HAC={univ_spec['target_t_hac']:+.2f}  "
                      f"p={univ_spec['target_p_hac']:.3f}")
    ax.axhline(0, color='gray', lw=0.5, ls='--')
    ax.axvline(0, color='gray', lw=0.5, ls='--')
    ax.set_xlabel(NONCAPEX_LABELS[best_col])
    ax.set_ylabel('θ_EAV_empirical')
    ax.set_title(f'K1108d: θ_EAV vs {NONCAPEX_LABELS[best_col]} '
                 f'(best non-capex predictor)')
    ax.legend(loc='best', fontsize=9)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    plt.close()
    print(f"Saved {out_path}")


# ==========================================================================
# Main
# ==========================================================================
def run_experiment():
    print(f"=== {EXPERIMENT_ID} — non-capex guidance D2 test ===")
    print(f"Seed=42; start at {time.strftime('%H:%M:%S')}")

    # 1. Load + merge pools
    merged = load_merge_pools()
    n_total = len(merged)
    print(f"\nMerged pool: {n_total} events across "
          f"{merged['stock'].nunique()} firms")

    # Coverage
    cov = {}
    for c in NONCAPEX_COLS:
        cov[c] = int(merged[c].notna().sum())
    all3_n = int(merged[NONCAPEX_COLS].notna().all(axis=1).sum())
    cov_pcts = {c: cov[c] / n_total for c in NONCAPEX_COLS}
    cov_all3_pct = all3_n / n_total
    print(f"Coverage per col:")
    for c in NONCAPEX_COLS:
        print(f"  {c}: {cov[c]}/{n_total} = {cov_pcts[c]*100:.1f}%")
    print(f"  all-3 simultaneously non-NaN: {all3_n}/{n_total} "
          f"= {cov_all3_pct*100:.1f}%")

    # Per-firm coverage
    print(f"\nPer-firm coverage (all-3):")
    for f in PRIMARY_FIRMS:
        sub = merged.loc[merged['stock'] == f]
        n_f = len(sub)
        n_f_all3 = int(sub[NONCAPEX_COLS].notna().all(axis=1).sum())
        cov_f = n_f_all3 / n_f if n_f > 0 else 0
        tag = ' ⚠️ <50%' if cov_f < 0.5 else ''
        print(f"  {f}: {n_f_all3}/{n_f} = {cov_f*100:.1f}%{tag}")

    # 2. Median-impute
    merged_imp = impute_by_firm_median(merged, NONCAPEX_COLS)
    # guide_delta_pct was in K1108c pool; ensure numeric + impute
    if 'guide_delta_pct' not in merged_imp.columns:
        raise RuntimeError("guide_delta_pct missing from merged pool")
    merged_imp['guide_delta_pct'] = merged_imp['guide_delta_pct']\
        .fillna(merged_imp['guide_delta_pct'].median())

    # For imputed regression, use *_imputed columns
    for c in NONCAPEX_COLS:
        merged_imp[c + '_reg'] = merged_imp[f'{c}_imputed']
    reg_cols = [c + '_reg' for c in NONCAPEX_COLS]

    # 3. Univariate specs (Spec A/B/C)
    print("\n=== Univariate specs (HAC + cluster-by-firm) ===")
    univ_results = []
    for c_raw, c_reg in zip(NONCAPEX_COLS, reg_cols):
        # Drop rows where BOTH y and raw col are NaN (use raw, not imputed)
        sub = merged.dropna(subset=['theta_eav_empirical', c_raw])
        if len(sub) < 5:
            print(f"  {c_raw}: n={len(sub)} insufficient — skipping")
            univ_results.append({
                'target_col': c_raw,
                'target_beta': np.nan, 'target_se_hac': np.nan,
                'target_t_hac': np.nan, 'target_p_hac': np.nan,
                'target_t_cluster': np.nan, 'target_p_cluster': np.nan,
                'target_ci_95_low': np.nan, 'target_ci_95_high': np.nan,
                'n': len(sub), 'beta': [np.nan, np.nan], 'names': ['intercept', c_raw],
                'se_hac': [np.nan, np.nan], 't_hac': [np.nan, np.nan],
                'spec': f'univariate_{c_raw}_NA',
            })
            continue
        y, X, names, firms = build_univariate_design(sub, c_raw)
        res = run_spec(y, X, names, firms,
                       f'univariate_{c_raw}', target_col=c_raw)
        univ_results.append(res)
        print(f"  {c_raw:24s}  n={res['n']}  β={res['target_beta']:+.3e}  "
              f"t_HAC={res['target_t_hac']:+.3f}  "
              f"t_cluster={res['target_t_cluster']:+.3f}  "
              f"p_HAC={res['target_p_hac']:.4f}")

    # 4. Joint + FE + year_fe spec (Spec D)
    print("\n=== Joint spec (3 non-capex + firm FE + year FE) ===")
    # For joint use imputed columns so N isn't decimated
    y, X, names, firms = build_joint_design(
        merged_imp, reg_cols, firm_fe=True, year_fe=True)
    # Remap reg_cols back to logical names in spec output
    name_remap = {reg: orig for reg, orig in zip(reg_cols, NONCAPEX_COLS)}
    names_display = [name_remap.get(n, n) for n in names]
    joint = run_spec(y, X, names_display, firms, 'joint_fe')
    for c in NONCAPEX_COLS:
        i = names_display.index(c)
        print(f"  {c:24s}  β={joint['beta'][i]:+.3e}  "
              f"t_HAC={joint['t_hac'][i]:+.3f}  "
              f"t_cluster={joint['t_cluster_firm'][i]:+.3f}  "
              f"p_HAC={joint['p_hac'][i]:.4f}")

    # 5. Partial-F test (joint β_nc = 0)
    pf = partial_f_test(y, X, names_display, NONCAPEX_COLS)
    print(f"\n  Partial-F (β_util=β_asp=β_rd=0): "
          f"F={pf['F_stat']}  p={pf['p_value']}  "
          f"df=({pf['df_num']}, {pf['df_den']})")

    # 6. Control spec: joint + guide_delta_pct as control (K1108c capex)
    print("\n=== Orthogonality check: joint + guide_delta_pct control ===")
    y_o, X_o, names_o, firms_o = build_joint_design(
        merged_imp, reg_cols, firm_fe=True, year_fe=True,
        extra_cols=['guide_delta_pct'])
    names_o_display = [name_remap.get(n, n) for n in names_o]
    joint_control = run_spec(y_o, X_o, names_o_display, firms_o,
                             'joint_fe_with_capex_control')
    for c in NONCAPEX_COLS:
        i = names_o_display.index(c)
        print(f"  {c:24s}  β={joint_control['beta'][i]:+.3e}  "
              f"t_HAC={joint_control['t_hac'][i]:+.3f}  "
              f"p_HAC={joint_control['p_hac'][i]:.4f}")
    gi = names_o_display.index('guide_delta_pct')
    print(f"  guide_delta_pct (control)  "
          f"β={joint_control['beta'][gi]:+.3e}  "
          f"t_HAC={joint_control['t_hac'][gi]:+.3f}  "
          f"p_HAC={joint_control['p_hac'][gi]:.4f}")

    # 7. Block bootstrap on 3 non-capex coefs in joint spec
    print("\n=== Block bootstrap (N=1000, block=5, firm-stratified) ===")
    target_idx = [names_display.index(c) for c in NONCAPEX_COLS]
    boot = block_bootstrap_coefs(y, X, firms, n_reps=1000, block=5,
                                 seed=42, target_indices=target_idx)
    boot_results = {}
    for c, i in zip(NONCAPEX_COLS, target_idx):
        arr = boot[i]
        if len(arr) < 10:
            boot_results[c] = {'n_reps_valid': len(arr), 'ci_low': None,
                                'ci_high': None, 'mean': None}
            print(f"  {c}: insufficient bootstrap reps")
            continue
        lo = float(np.percentile(arr, 2.5))
        hi = float(np.percentile(arr, 97.5))
        mean = float(np.mean(arr))
        p_boot = 2 * min(np.mean(arr >= 0), np.mean(arr <= 0))
        boot_results[c] = {
            'n_reps_valid': int(len(arr)),
            'mean': mean,
            'ci_low': lo,
            'ci_high': hi,
            'p_value_two_sided': float(p_boot),
        }
        print(f"  {c:24s}  mean={mean:+.3e}  CI95=[{lo:+.3e}, {hi:+.3e}]  "
              f"p_boot={p_boot:.4f}")

    # 8. Hand-coded subset robustness
    print("\n=== Hand-coded-only subset robustness ===")
    hand_mask = (
        (merged['util_source'] == 'HAND_CODED')
        | (merged['asp_source'] == 'HAND_CODED')
    )
    hand_sub = merged.loc[hand_mask].dropna(
        subset=['theta_eav_empirical'])
    hand_results = {}
    if len(hand_sub) >= 5:
        for c in NONCAPEX_COLS:
            s = hand_sub.dropna(subset=[c])
            if len(s) < 5:
                hand_results[c] = {'n': len(s), 'skipped': True}
                continue
            y_h, X_h, n_h, f_h = build_univariate_design(s, c)
            rh = run_spec(y_h, X_h, n_h, f_h,
                          f'hand_univariate_{c}', target_col=c)
            hand_results[c] = {
                'n': rh['n'],
                'beta': rh['target_beta'],
                't_hac': rh['target_t_hac'],
                'p_hac': rh['target_p_hac'],
            }
            print(f"  hand-only {c:24s}  n={rh['n']}  "
                  f"β={rh['target_beta']:+.3e}  "
                  f"t_HAC={rh['target_t_hac']:+.3f}  "
                  f"p_HAC={rh['target_p_hac']:.4f}")
    else:
        print(f"  Hand-coded subset too small (N={len(hand_sub)})")

    # 9. Verdict
    cov_any_pct = merged[NONCAPEX_COLS].notna().any(axis=1).sum() / n_total
    verdict = decide_verdict(univ_results, joint, pf, cov_any_pct,
                             cov_all3_pct)
    print("\n=== VERDICT ===")
    print(f"Label: {verdict['label']}")
    for b in verdict['bullets']:
        print(f"  {b}")
    print(f"\nPaper 2 commitment: {verdict['paper2_commitment']}")
    print(f"Conclusion: {verdict['conclusion']}")

    # 10. Plots
    plot_forest(univ_results, joint, PLOT_FOREST)
    # Best predictor = largest |HAC t| in univariate
    valid_univ = [u for u in univ_results
                   if u.get('target_t_hac') is not None
                   and np.isfinite(u.get('target_t_hac', np.nan))]
    if len(valid_univ) > 0:
        best = max(valid_univ,
                   key=lambda u: abs(u.get('target_t_hac', 0)))
        plot_scatter_best(merged.dropna(subset=[best['target_col']]),
                          best['target_col'], best, PLOT_SCATTER)

    # 11. Persist
    runtime = float(time.time() - START_TIME)
    results = {
        'experiment_id': EXPERIMENT_ID,
        'parent_chain': ['K1108', 'K1108b', 'K1108c', 'K1108e', 'K1108f'],
        'timestamp': pd.Timestamp.utcnow().isoformat(),
        'data_sources': [
            'experiments/k1108c/k1108c_merged_pool.csv (135 events, '
            'θ_EAV_empirical + guide_delta_pct)',
            'experiments/k1108d/data/k1108d_noncapex_pool.csv (hand-coded + '
            'yfinance-proxy 3-dim non-capex: utilisation Δ pp, wafer ASP Δ %, '
            'R&D Δ %YoY)',
        ],
        'n_events': int(n_total),
        'firms': PRIMARY_FIRMS,
        'coverage': {
            'per_col_pct': {c: cov_pcts[c] for c in NONCAPEX_COLS},
            'per_col_n': {c: cov[c] for c in NONCAPEX_COLS},
            'all3_pct': float(cov_all3_pct),
            'all3_n': int(all3_n),
            'any_pct': float(cov_any_pct),
        },
        'univariate_specs': univ_results,
        'joint_fe_spec': joint,
        'joint_fe_capex_control_spec': joint_control,
        'partial_f_noncap_zero': pf,
        'block_bootstrap': boot_results,
        'hand_coded_subset': hand_results,
        'verdict': verdict,
        'five_layer_null_precedent': [
            {'experiment': 'K1108',
             'finding': 'TSMC single-firm capex inconclusive / weak NULL'},
            {'experiment': 'K1108b',
             'finding': 'Pool binary guide_updated DECISIVE NULL '
                        '(Wald t=-0.0003)'},
            {'experiment': 'K1108c',
             'finding': 'Continuous guide_delta_pct NULL (t_HAC below 2)'},
            {'experiment': 'K1108e',
             'finding': 'Operating leverage (PPE/Rev, D/E, (PPE+SGA)/Rev) NULL'},
            {'experiment': 'K1108f',
             'finding': 'Regime-split (volatility / cycle-phase) NULL'},
        ],
        'references': [
            'K1104 (foundry θ₂>0 rule baseline)',
            'K1108/b/c (capex guidance 3-layer NULL)',
            'K1108e (op_leverage D3 NULL)',
            'K1108f (regime-split D4 NULL)',
            'Andrews (1991) HAC auto-bandwidth',
            'Newey & West (1987) HAC SE',
            'Harvey et al. (2016) |t|>3 multi-testing threshold',
            'Politis & Romano (1994) block bootstrap',
        ],
        'random_seed': 42,
        'runtime_seconds': runtime,
    }

    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults written: {RESULTS_PATH}")
    print(f"Total runtime: {runtime:.1f}s")
    return results


if __name__ == '__main__':
    run_experiment()
