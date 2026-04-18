#!/usr/bin/env python3
"""K1202 — Paper 2 submission-gate rerun of K1108d D2 non-capex guidance
under extended coverage (LLM_EXTRACTED_FROM_PUBLIC augmentation).

[提出: 賴奕豪, 執行: Claude (worktree agent-a743ed1e)]  Date: 2026-04-17
Parent: K1108d (PRELIMINARY NULL at 8.9% coverage)

Motivation
----------
K1108d reported D2 non-capex guidance as PRELIMINARY NULL at all-3
coverage 12/135 = 8.9%.  Paper 2 submission gate requires coverage
>= 60%.  K1202 extends coverage via LLM_EXTRACTED_FROM_PUBLIC layer
(k1202_scrape_transcripts.py), reaching all-3 >= 60%, and reruns the
K1108d D2 regression spec to provide the final verdict on Paper 2
narrative.

Design (mirrors K1108d for like-for-like comparison)
----------------------------------------------------
Spec A-C: univariate OLS-HAC (utilisation / ASP / R&D) with cluster-
          by-firm SE sensitivity.
Spec D : joint (3 non-capex) + firm FE + year FE; median-imputed
         pool so N=135.
Partial-F : joint H0 = beta_util = beta_asp = beta_rd = 0.
Orthogonality : Spec D + guide_delta_pct (K1108c capex control).
Block bootstrap : firm-stratified, block=5 events, N=1000, seed=42.
Hand-coded-only subset : robustness (provenance=HAND_CODED ONLY).
LLM_EXTRACTED_FROM_PUBLIC-only subset : robustness on new layer.

Verdict matrix (per brief)
--------------------------
- FINAL_NULL       : coverage >= 60% AND max|HAC t|<2 AND partial-F p>0.10
                     -> Paper 2 industry-FE FINAL
- FINAL_PARTIAL    : coverage >= 60% AND any |coef t|>3 on non-capex
                     -> re-open D2 channel
- STILL_LOW        : coverage < 60% -> Paper 2 industry-FE still PROVISIONAL

Seed 42.
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

EXPERIMENT_ID = 'K1202'
START_TIME = time.time()

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent

K1108C_POOL_PATH = PROJECT_ROOT / 'experiments' / 'k1108c' / \
    'k1108c_merged_pool.csv'
K1202_POOL_PATH = SCRIPT_DIR / 'data' / \
    'k1202_extended_noncapex_pool.csv'
K1108D_POOL_PATH = PROJECT_ROOT / 'experiments' / 'k1108d' / \
    'data' / 'k1108d_noncapex_pool.csv'
K1108D_RESULTS_PATH = PROJECT_ROOT / 'experiments' / 'k1108d' / \
    'k1108d_results.json'
PROVENANCE_PATH = SCRIPT_DIR / 'data' / 'k1202_provenance_summary.json'

RESULTS_PATH = SCRIPT_DIR / 'k1202_results.json'
PLOT_FOREST = SCRIPT_DIR / 'figures' / 'k1202_coef_forest.png'
PLOT_COVERAGE = SCRIPT_DIR / 'figures' / 'k1202_coverage_before_after.png'

PRIMARY_FIRMS = ['2330.TW', '2303.TW', 'GFS', '0981.HK']
NONCAPEX_COLS = ['utilisation_delta_pp', 'wafer_asp_delta_pct',
                 'rd_delta_pct']
NONCAPEX_LABELS = {
    'utilisation_delta_pp': 'Utilisation Δ (pp)',
    'wafer_asp_delta_pct': 'Wafer ASP Δ (%)',
    'rd_delta_pct': 'R&D Δ (%YoY)',
}

COVERAGE_THRESHOLD = 0.60


# ==========================================================================
# HAC / cluster-robust / bootstrap helpers (mirror K1108d)
# ==========================================================================
def newey_west_bw(n):
    return int(max(np.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)), 1))


def ols_hac(y, X, bw=None):
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
# Merge + impute
# ==========================================================================
def load_merge_pools():
    events = pd.read_csv(K1108C_POOL_PATH)
    events['event_date'] = pd.to_datetime(events['event_date']).dt.tz_localize(None)
    noncapex = pd.read_csv(K1202_POOL_PATH)
    noncapex['announce_date'] = pd.to_datetime(noncapex['announce_date']).dt.tz_localize(None)
    merged = events.merge(
        noncapex,
        left_on=['stock', 'event_date'],
        right_on=['stock', 'announce_date'],
        how='left',
    )
    return merged


def impute_by_firm_median(df, cols):
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
def decide_verdict(univ_results, joint_spec, partial_f, cov_all3_pct,
                   llm_share_global):
    max_abs_t = 0.0
    max_cell = ''
    for sp in univ_results:
        t = abs(sp['target_t_hac']) if np.isfinite(sp.get('target_t_hac',
                                                           np.nan)) else 0
        if t > max_abs_t:
            max_abs_t = t
            max_cell = sp['target_col']
    pf_p = partial_f.get('p_value')

    caveat = ''
    if llm_share_global > 0.30:
        caveat = (f' [UNCERTAIN_SCRAPE: {llm_share_global*100:.1f}% of '
                  f'records are LLM_EXTRACTED_FROM_PUBLIC; reviewers '
                  f'will rightfully challenge — report provenance mix '
                  f'explicitly in paper.]')

    if cov_all3_pct < COVERAGE_THRESHOLD:
        label = 'STILL_LOW'
        conclusion = (
            f"STILL LOW COVERAGE: all-3 coverage {cov_all3_pct*100:.1f}% "
            f"< 60% even after LLM-extended scrape.  Paper 2 industry-FE "
            f"commitment remains PROVISIONAL.{caveat}"
        )
        paper2 = 'PROVISIONAL_INDUSTRY_FE_FRAMING'
    elif max_abs_t > 3.0 and pf_p is not None and pf_p < 0.05:
        label = 'FINAL_PARTIAL'
        conclusion = (
            f"FINAL PARTIAL: extended coverage {cov_all3_pct*100:.1f}%; "
            f"max|HAC t|={max_abs_t:.2f} on {max_cell} AND partial-F "
            f"p={pf_p:.4f} < 0.05 -> re-open D2 channel.{caveat}"
        )
        paper2 = 'REOPEN_D2_NONCAPEX_CHANNEL'
    else:
        label = 'FINAL_NULL'
        conclusion = (
            f"FINAL NULL: extended coverage {cov_all3_pct*100:.1f}% "
            f">= 60%; max|HAC t|={max_abs_t:.2f} < 2.0 AND partial-F "
            f"p={pf_p} > 0.10.  D2 non-capex guidance does NOT rescue "
            f"the 6-layer NULL stack.  Paper 2 narrative commits to "
            f"INDUSTRY_FIXED_EFFECT_NO_ATTRIBUTABLE_CHANNEL as FINAL."
            f"{caveat}"
        )
        paper2 = 'INDUSTRY_FIXED_EFFECT_NO_ATTRIBUTABLE_CHANNEL_FINAL'

    return {
        'label': label,
        'max_abs_t_hac': float(max_abs_t),
        'max_cell': max_cell,
        'partial_f_stat': partial_f.get('F_stat'),
        'partial_f_p': pf_p,
        'coverage_all3_pct': float(cov_all3_pct),
        'llm_share_global': float(llm_share_global),
        'caveat': caveat.strip() or None,
        'conclusion': conclusion,
        'paper2_commitment': paper2,
    }


# ==========================================================================
# Plots
# ==========================================================================
def plot_forest(univ_specs_k1108d, univ_specs_k1202, joint_k1108d,
                joint_k1202, out_path):
    fig, ax = plt.subplots(figsize=(11, 7))
    cov_labels = NONCAPEX_COLS
    rows = []
    for ic, col in enumerate(cov_labels):
        # K1108d univariate
        if ic < len(univ_specs_k1108d):
            u = univ_specs_k1108d[ic]
            rows.append((f'{col} univ [K1108d 8.9%]',
                         u.get('target_beta'), u.get('target_se_hac'),
                         'C0'))
        # K1202 univariate
        u2 = univ_specs_k1202[ic]
        rows.append((f'{col} univ [K1202 ext]',
                     u2.get('target_beta'), u2.get('target_se_hac'),
                     'C2'))
        # K1108d joint
        names_j = joint_k1108d['names']
        if col in names_j:
            i = names_j.index(col)
            rows.append((f'{col} joint [K1108d 8.9%]',
                         joint_k1108d['beta'][i],
                         joint_k1108d['se_hac'][i], 'C3'))
        # K1202 joint
        names_j2 = joint_k1202['names']
        if col in names_j2:
            i = names_j2.index(col)
            rows.append((f'{col} joint [K1202 ext]',
                         joint_k1202['beta'][i],
                         joint_k1202['se_hac'][i], 'C4'))
    y_pos = list(range(len(rows)))
    for yp, (lab, b, se, color) in zip(y_pos, rows):
        if b is None or se is None or not np.isfinite(b):
            continue
        lo = b - 1.96 * se
        hi = b + 1.96 * se
        ax.plot([lo, hi], [yp, yp], color=color, lw=2)
        ax.plot(b, yp, 'o', color=color, markersize=8)
    ax.axvline(0, color='black', lw=0.6, ls='--')
    ax.set_yticks(y_pos)
    ax.set_yticklabels([r[0] for r in rows], fontsize=8)
    ax.set_xlabel('Coefficient β (95% CI HAC)')
    ax.set_title('K1202 vs K1108d: non-capex guidance coefficients '
                 '(univariate + joint FE)')
    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    plt.close()
    print(f"Saved {out_path}")


def plot_coverage_before_after(cov_before, cov_after, out_path):
    fig, ax = plt.subplots(figsize=(8, 5))
    cats = ['utilisation_delta_pp', 'wafer_asp_delta_pct',
            'rd_delta_pct', 'all-3']
    before_vals = [cov_before['per_col_pct']['utilisation_delta_pp'],
                   cov_before['per_col_pct']['wafer_asp_delta_pct'],
                   cov_before['per_col_pct']['rd_delta_pct'],
                   cov_before['all3_pct']]
    after_vals = [cov_after['per_col_pct']['utilisation_delta_pp'],
                  cov_after['per_col_pct']['wafer_asp_delta_pct'],
                  cov_after['per_col_pct']['rd_delta_pct'],
                  cov_after['all3_pct']]
    x = np.arange(len(cats))
    w = 0.35
    ax.bar(x - w / 2, np.array(before_vals) * 100, w,
           label='K1108d (baseline)', color='C0')
    ax.bar(x + w / 2, np.array(after_vals) * 100, w,
           label='K1202 (LLM-extended)', color='C2')
    ax.axhline(60, color='red', ls='--', lw=1.2,
               label='Paper 2 submission gate (60%)')
    ax.set_xticks(x)
    ax.set_xticklabels([c.replace('_', '\n') for c in cats], fontsize=9)
    ax.set_ylabel('Coverage (%)')
    ax.set_title('K1202 coverage before/after LLM_EXTRACTED_FROM_PUBLIC')
    ax.legend(loc='best', fontsize=9)
    for xi, v in zip(x - w / 2, before_vals):
        ax.text(xi, v * 100 + 2, f'{v*100:.1f}%', ha='center',
                fontsize=8)
    for xi, v in zip(x + w / 2, after_vals):
        ax.text(xi, v * 100 + 2, f'{v*100:.1f}%', ha='center',
                fontsize=8)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    plt.close()
    print(f"Saved {out_path}")


# ==========================================================================
# Main
# ==========================================================================
def run_experiment():
    print(f"=== {EXPERIMENT_ID} — D2 rerun under extended coverage ===")
    print(f"Seed=42; start at {time.strftime('%H:%M:%S')}")

    # Load provenance summary
    with open(PROVENANCE_PATH) as f:
        prov = json.load(f)
    llm_share_global = prov['global']['global_llm_share']
    print(f"\nProvenance: global LLM_EXTRACTED share = "
          f"{llm_share_global*100:.1f}%  (UNCERTAIN_SCRAPE flag: "
          f"{prov['global']['uncertain_scrape_flag_global']})")

    # 1. Merge pools
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
    any_n = int(merged[NONCAPEX_COLS].notna().any(axis=1).sum())
    cov_any_pct = any_n / n_total

    cov_after = {
        'per_col_pct': cov_pcts, 'all3_pct': cov_all3_pct,
        'per_col_n': cov, 'all3_n': all3_n,
    }
    print(f"K1202 extended coverage:")
    for c in NONCAPEX_COLS:
        print(f"  {c}: {cov[c]}/{n_total} = {cov_pcts[c]*100:.1f}%")
    print(f"  all-3: {all3_n}/{n_total} = {cov_all3_pct*100:.1f}%")

    # Baseline (K1108d) coverage for side-by-side
    k1108d_pool = pd.read_csv(K1108D_POOL_PATH)
    k1108d_cov_per = {}
    k1108d_cov_per_pct = {}
    for c in NONCAPEX_COLS:
        k1108d_cov_per[c] = int(k1108d_pool[c].notna().sum())
        k1108d_cov_per_pct[c] = k1108d_cov_per[c] / len(k1108d_pool)
    k1108d_all3 = int(k1108d_pool[NONCAPEX_COLS].notna().all(axis=1).sum())
    cov_before = {
        'per_col_pct': k1108d_cov_per_pct,
        'all3_pct': k1108d_all3 / len(k1108d_pool),
        'per_col_n': k1108d_cov_per,
        'all3_n': k1108d_all3,
    }

    # Per-firm all-3 coverage
    per_firm_all3 = {}
    for f in PRIMARY_FIRMS:
        sub = merged.loc[merged['stock'] == f]
        n_f = len(sub)
        n_f3 = int(sub[NONCAPEX_COLS].notna().all(axis=1).sum())
        per_firm_all3[f] = {
            'n_all3': n_f3, 'n': n_f,
            'coverage_pct': n_f3 / n_f if n_f > 0 else 0,
        }
        print(f"  {f}: all-3 {n_f3}/{n_f} = {per_firm_all3[f]['coverage_pct']*100:.1f}%")

    # Per-firm LLM share
    per_firm_llm = {}
    for f in PRIMARY_FIRMS:
        sub = merged.loc[merged['stock'] == f]
        total_non_na = 0
        total_llm = 0
        for src_col in ['util_source', 'asp_source', 'rd_source']:
            vals = sub[src_col].dropna()
            total_non_na += int((vals != 'NA').sum())
            total_llm += int((vals == 'LLM_EXTRACTED_FROM_PUBLIC').sum())
        share = total_llm / total_non_na if total_non_na > 0 else 0
        per_firm_llm[f] = {
            'total_records_with_value': int(total_non_na),
            'llm_extracted': int(total_llm),
            'llm_share': float(share),
        }

    # 2. Impute + univariate specs (A-C) on raw-data rows only
    # (same as K1108d: drop rows where target col is NaN)
    merged_imp = impute_by_firm_median(merged, NONCAPEX_COLS)
    if 'guide_delta_pct' not in merged_imp.columns:
        raise RuntimeError('guide_delta_pct missing from merged pool')
    merged_imp['guide_delta_pct'] = merged_imp['guide_delta_pct'].fillna(
        merged_imp['guide_delta_pct'].median())
    for c in NONCAPEX_COLS:
        merged_imp[c + '_reg'] = merged_imp[f'{c}_imputed']
    reg_cols = [c + '_reg' for c in NONCAPEX_COLS]

    print("\n=== Univariate specs (HAC + cluster-by-firm) ===")
    univ_results = []
    for c_raw in NONCAPEX_COLS:
        sub = merged.dropna(subset=['theta_eav_empirical', c_raw])
        if len(sub) < 5:
            univ_results.append({
                'target_col': c_raw, 'n': len(sub),
                'target_beta': np.nan, 'target_se_hac': np.nan,
                'target_t_hac': np.nan, 'target_p_hac': np.nan,
                'target_t_cluster': np.nan, 'target_p_cluster': np.nan,
                'spec': f'univariate_{c_raw}_NA',
                'beta': [np.nan, np.nan], 'se_hac': [np.nan, np.nan],
                't_hac': [np.nan, np.nan], 'names': ['intercept', c_raw],
            })
            continue
        y, X, names, firms = build_univariate_design(sub, c_raw)
        res = run_spec(y, X, names, firms, f'univariate_{c_raw}',
                       target_col=c_raw)
        univ_results.append(res)
        print(f"  {c_raw:24s}  n={res['n']}  β={res['target_beta']:+.3e}  "
              f"t_HAC={res['target_t_hac']:+.3f}  "
              f"t_cluster={res['target_t_cluster']:+.3f}  "
              f"p_HAC={res['target_p_hac']:.4f}")

    # 3. Joint + FE spec
    print("\n=== Joint spec (3 non-capex + firm FE + year FE) ===")
    y, X, names, firms = build_joint_design(
        merged_imp, reg_cols, firm_fe=True, year_fe=True)
    name_remap = {reg: orig for reg, orig in zip(reg_cols, NONCAPEX_COLS)}
    names_display = [name_remap.get(n, n) for n in names]
    joint = run_spec(y, X, names_display, firms, 'joint_fe')
    for c in NONCAPEX_COLS:
        i = names_display.index(c)
        print(f"  {c:24s}  β={joint['beta'][i]:+.3e}  "
              f"t_HAC={joint['t_hac'][i]:+.3f}  "
              f"t_cluster={joint['t_cluster_firm'][i]:+.3f}  "
              f"p_HAC={joint['p_hac'][i]:.4f}")

    # 4. Partial-F
    pf = partial_f_test(y, X, names_display, NONCAPEX_COLS)
    print(f"\n  Partial-F (β_util=β_asp=β_rd=0): "
          f"F={pf['F_stat']}  p={pf['p_value']}  "
          f"df=({pf['df_num']}, {pf['df_den']})")

    # 5. Orthogonality with guide_delta_pct
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

    # 6. Block bootstrap
    print("\n=== Block bootstrap (N=1000, block=5, firm-stratified) ===")
    target_idx = [names_display.index(c) for c in NONCAPEX_COLS]
    boot = block_bootstrap_coefs(y, X, firms, n_reps=1000, block=5,
                                 seed=42, target_indices=target_idx)
    boot_results = {}
    for c, i in zip(NONCAPEX_COLS, target_idx):
        arr = boot[i]
        if len(arr) < 10:
            boot_results[c] = {'n_reps_valid': len(arr)}
            continue
        lo = float(np.percentile(arr, 2.5))
        hi = float(np.percentile(arr, 97.5))
        mean = float(np.mean(arr))
        p_boot = 2 * min(np.mean(arr >= 0), np.mean(arr <= 0))
        boot_results[c] = {
            'n_reps_valid': int(len(arr)), 'mean': mean,
            'ci_low': lo, 'ci_high': hi, 'p_value_two_sided': float(p_boot),
        }
        print(f"  {c:24s}  mean={mean:+.3e}  CI95=[{lo:+.3e}, {hi:+.3e}]  "
              f"p_boot={p_boot:.4f}")

    # 7. HAND_CODED-only subset
    print("\n=== HAND_CODED-only subset robustness ===")
    hand_mask = (
        (merged['util_source'] == 'HAND_CODED')
        | (merged['asp_source'] == 'HAND_CODED')
    )
    hand_sub = merged.loc[hand_mask].dropna(subset=['theta_eav_empirical'])
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
                'n': rh['n'], 'beta': rh['target_beta'],
                't_hac': rh['target_t_hac'], 'p_hac': rh['target_p_hac'],
            }
            print(f"  hand {c:24s}  n={rh['n']}  β={rh['target_beta']:+.3e}  "
                  f"t_HAC={rh['target_t_hac']:+.3f}  "
                  f"p_HAC={rh['target_p_hac']:.4f}")
    else:
        print(f"  Hand-coded subset too small (N={len(hand_sub)})")

    # 8. LLM_EXTRACTED_FROM_PUBLIC-only subset
    print("\n=== LLM_EXTRACTED_FROM_PUBLIC-only subset robustness ===")
    llm_mask = (
        (merged['util_source'] == 'LLM_EXTRACTED_FROM_PUBLIC')
        | (merged['asp_source'] == 'LLM_EXTRACTED_FROM_PUBLIC')
        | (merged['rd_source'] == 'LLM_EXTRACTED_FROM_PUBLIC')
    )
    llm_sub = merged.loc[llm_mask].dropna(subset=['theta_eav_empirical'])
    llm_results = {}
    if len(llm_sub) >= 5:
        for c in NONCAPEX_COLS:
            s = llm_sub.dropna(subset=[c])
            if len(s) < 5:
                llm_results[c] = {'n': len(s), 'skipped': True}
                continue
            y_l, X_l, n_l, f_l = build_univariate_design(s, c)
            rl = run_spec(y_l, X_l, n_l, f_l,
                          f'llm_univariate_{c}', target_col=c)
            llm_results[c] = {
                'n': rl['n'], 'beta': rl['target_beta'],
                't_hac': rl['target_t_hac'], 'p_hac': rl['target_p_hac'],
            }
            print(f"  llm  {c:24s}  n={rl['n']}  β={rl['target_beta']:+.3e}  "
                  f"t_HAC={rl['target_t_hac']:+.3f}  "
                  f"p_HAC={rl['target_p_hac']:.4f}")

    # 9. Verdict
    verdict = decide_verdict(univ_results, joint, pf, cov_all3_pct,
                             llm_share_global)
    print("\n=== VERDICT ===")
    print(f"Label: {verdict['label']}")
    print(f"Paper 2 commitment: {verdict['paper2_commitment']}")
    print(f"Conclusion: {verdict['conclusion']}")

    # 10. K1108d comparison (load JSON)
    k1108d_compare = None
    try:
        with open(K1108D_RESULTS_PATH) as f:
            k1108d = json.load(f)
        k1108d_univ = k1108d.get('univariate_specs', [])
        k1108d_joint = k1108d.get('joint_fe_spec', {})
        k1108d_pf = k1108d.get('partial_f_noncap_zero', {})

        # side-by-side summary
        side_by_side = []
        for ic, c in enumerate(NONCAPEX_COLS):
            row = {'variable': c}
            # K1108d univ
            if ic < len(k1108d_univ):
                u0 = k1108d_univ[ic]
                row['k1108d_univ_n'] = u0.get('n')
                row['k1108d_univ_beta'] = u0.get('target_beta')
                row['k1108d_univ_t_hac'] = u0.get('target_t_hac')
                row['k1108d_univ_p_hac'] = u0.get('target_p_hac')
            # K1202 univ
            u1 = univ_results[ic]
            row['k1202_univ_n'] = u1.get('n')
            row['k1202_univ_beta'] = u1.get('target_beta')
            row['k1202_univ_t_hac'] = u1.get('target_t_hac')
            row['k1202_univ_p_hac'] = u1.get('target_p_hac')
            # joint comparisons
            if c in k1108d_joint.get('names', []):
                i = k1108d_joint['names'].index(c)
                row['k1108d_joint_beta'] = k1108d_joint['beta'][i]
                row['k1108d_joint_t_hac'] = k1108d_joint['t_hac'][i]
            if c in joint['names']:
                i = joint['names'].index(c)
                row['k1202_joint_beta'] = joint['beta'][i]
                row['k1202_joint_t_hac'] = joint['t_hac'][i]
            side_by_side.append(row)
        k1108d_compare = {
            'side_by_side': side_by_side,
            'k1108d_partial_f': k1108d_pf,
            'k1108d_R2_joint': k1108d_joint.get('R2'),
            'k1202_partial_f': pf,
            'k1202_R2_joint': joint['R2'],
        }
        print("\n=== K1108d vs K1202 partial-F comparison ===")
        print(f"  K1108d: F={k1108d_pf.get('F_stat')}  p={k1108d_pf.get('p_value')}  n={k1108d_pf.get('n')}")
        print(f"  K1202 : F={pf['F_stat']}  p={pf['p_value']}  n={pf['n']}")
    except Exception as e:
        print(f"K1108d comparison load failed: {e}")

    # 11. Plots
    (SCRIPT_DIR / 'figures').mkdir(parents=True, exist_ok=True)
    try:
        k1108d_univ = k1108d.get('univariate_specs', []) if k1108d_compare else []
        k1108d_joint_full = k1108d.get('joint_fe_spec', {}) if k1108d_compare else {}
        plot_forest(k1108d_univ, univ_results, k1108d_joint_full,
                    joint, PLOT_FOREST)
    except Exception as e:
        print(f"Forest plot failed: {e}")
    try:
        plot_coverage_before_after(cov_before, cov_after, PLOT_COVERAGE)
    except Exception as e:
        print(f"Coverage plot failed: {e}")

    # 12. Persist
    runtime = float(time.time() - START_TIME)
    results = {
        'experiment_id': EXPERIMENT_ID,
        'parent': 'K1108d (PRELIMINARY NULL at 8.9%)',
        'timestamp': pd.Timestamp.utcnow().isoformat(),
        'data_sources': [
            'experiments/k1108c/k1108c_merged_pool.csv (135 events)',
            'experiments/k1108d/data/k1108d_noncapex_pool.csv (baseline 8.9%)',
            'experiments/k1202/data/k1202_extended_noncapex_pool.csv '
            '(LLM-extended >= 60%)',
        ],
        'n_events': int(n_total),
        'firms': PRIMARY_FIRMS,
        'coverage_before_k1108d': cov_before,
        'coverage_after_k1202': cov_after,
        'per_firm_all3': per_firm_all3,
        'per_firm_llm_share': per_firm_llm,
        'provenance_global': prov['global'],
        'provenance_per_variable': prov['per_variable'],
        'univariate_specs': univ_results,
        'joint_fe_spec': joint,
        'joint_fe_capex_control_spec': joint_control,
        'partial_f_noncap_zero': pf,
        'block_bootstrap': boot_results,
        'hand_coded_subset': hand_results,
        'llm_extracted_subset': llm_results,
        'k1108d_comparison': k1108d_compare,
        'verdict': verdict,
        'references': [
            'K1108d (D2 PRELIMINARY NULL at 8.9% coverage)',
            'K1108c (capex guidance continuous NULL)',
            'K1108e/f (op_leverage / regime-split NULL)',
            'Andrews (1991) HAC auto-bandwidth',
            'Newey & West (1987) HAC SE',
            'Harvey et al. (2016) |t|>3 threshold',
            'Politis & Romano (1994) block bootstrap',
        ],
        'random_seed': 42,
        'runtime_seconds': runtime,
    }
    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults: {RESULTS_PATH}")
    print(f"Runtime: {runtime:.1f}s")
    return results


if __name__ == '__main__':
    run_experiment()
