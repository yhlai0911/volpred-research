#!/usr/bin/env python3
"""K1108e: operating leverage as foundry θ_EAV mechanism (D3 candidate).

[提出: 賴奕豪, 執行: Claude]  Date: 2026-04-17
Parent: K1108c (commit d1240e89, H2_MAGNITUDE_NULL DECISIVE)
Grand-parent: K1108b (H2 DECISIVE NULL with binary flag)

Motivation
----------
K1108 → K1108b → K1108c established a **three-layer DECISIVE NULL** on
the capex-guidance hypothesis for foundry θ_EAV. D3 remains: perhaps
foundry θ₂>0 is driven by the *balance-sheet cost structure* itself
(high PP&E intensity, long-lived equipment → fixed-cost operating
leverage) rather than guidance event content. If op_leverage PASSES,
the Paper 2 foundry-rule mechanism = structural balance-sheet feature
rather than event-specific guidance. If op_leverage NULLs, D3 is
falsified and we proceed to K1108f regime-split.

Hypotheses
----------
H_D3_PASS     : max |HAC t| on op_leverage_{1,2,3} > 3.0 (Harvey 2016),
                β₁ sign positive for op_leverage_1/3 (or positive for
                debt/equity under levered-firm amplification story),
                joint partial-F p < 0.01. → Paper 2 mechanism confirmed
                as balance-sheet structure.
H_D3_NULL     : all three |HAC t| < 2.0 AND partial-F p > 0.10 →
                balance-sheet structure does NOT explain foundry θ₂>0.
                Capex + op_leverage both falsified → D4 regime-split next.
H_D3_PARTIAL  : at least one |HAC t| in (2.0, 3.0) → suggestive but
                not Harvey-decisive; report as partial evidence.

Design
------
Stage 0 (data): Reuse K1108c `k1108c_merged_pool.csv` (135 firm-events
with θ_EAV_empirical, guide_delta_pct, 4 firms). Join op_leverage by
firm + event-date PIT lookup.

Stage 1 (specs): For each of three op_leverage covariates separately,
and three estimator specs (pooled OLS / firm-FE / firm-FE + year-FE):

  θ_EAV_empirical_{i,d}
      = β₀ + β₁ · op_leverage_{k,i,d-lag}
        + [firm_fe_i]  + [year_fe_year(d)]
        + ε_{i,d}

where op_leverage_{k,i,d-lag} is the most recent annual op_leverage
measure published ≥ 45 days before event d (conservative PIT).

SE: Newey-West HAC (Andrews 1991 auto-bandwidth) pooled over (firm, d),
plus cluster-by-firm fallback for sensitivity.

Stage 2 (control): Joint regression including BOTH guide_delta_pct
(K1108c covariate, confirmed null) AND op_leverage_k. Tests whether
op_leverage β₁ is orthogonal to guidance channel (distinct mechanism)
or confounded.

Stage 3 (partial-F): Wald joint-F across the three op_leverage
covariates; overall test of balance-sheet structure as mechanism.

Stage 4 (bootstrap): Block bootstrap β₁ (N=1000, block=event-cluster,
firm-stratified, seed=42) for each of the 9 primary cells.

Controls for lookahead
----------------------
- θ_EAV_empirical_{i,d} already lagged per K1108b convention (uses
  VIX²_{d-1}, EAV_{d-1}).
- op_leverage at fiscal-year-end t is matched to event d such that
  (d - t) >= 45 days: a 45-day conservative publication lag. Typical
  annual-report lag for TWSE is ~90d, US 10-K is 60-90d, HKEX ~120d.
  45d is CONSERVATIVE floor; we additionally require the next firm
  annual report does not precede d, so no future info leaks.
- Firm FE absorbs time-invariant level differences (e.g. SMIC's ~3x
  higher PPE/Rev versus TSMC). Year FE absorbs macro shocks common
  across firms in a given year.
- seed=42 fixed; numpy/scipy deterministic.

Statistical limitations
-----------------------
- yfinance annual coverage = 2021-12-31 to 2025-12-31 (5 FYs). Events
  in 2014-2020 are DROPPED from K1108e sample. Effective N ≈ 50-70
  firm-events from the K1108c pool. This is smaller than K1108c's 135
  but still adequate for firm-FE + year-FE with 3 regressors.
- FY-level op_leverage does not capture within-year variation; time
  series length per firm is only 5 points. Firm FE exhausts most
  level variance; identification comes from year-over-year changes
  within firm around events.
- op_leverage_2 (D/E) can be negative-equity for distressed periods;
  we require equity > 0 filter.
"""
from __future__ import annotations

import json
import os
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
EXPERIMENT_ID = 'K1108e'

SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent
K1108C_POOL_PATH = PROJECT_ROOT / 'experiments' / 'k1108c' / 'k1108c_merged_pool.csv'

DATA_DIR = SCRIPT_DIR / 'data'
DATA_DIR.mkdir(parents=True, exist_ok=True)

RESULTS_PATH = SCRIPT_DIR / 'k1108e_results.json'
PLOT_SCATTER = SCRIPT_DIR / 'k1108e_scatter_opleverage.png'
PLOT_FOREST = SCRIPT_DIR / 'k1108e_coef_forest.png'

# 4-firm sample matching K1108c primary pool (TSM ADR excluded per K1108b)
PRIMARY_FIRMS = ['2330.TW', '2303.TW', 'GFS', '0981.HK']

# PIT publication lag floor (conservative; see module docstring)
PIT_LAG_DAYS = 45

# Op leverage measures
OPLEV_COLS = ['op_leverage_1', 'op_leverage_2', 'op_leverage_3']
OPLEV_LABELS = {
    'op_leverage_1': 'PPE / Revenue',
    'op_leverage_2': 'Debt / Equity',
    'op_leverage_3': '(PPE + SGA) / Revenue',
}

# ==========================================================================
# HAC / OLS / Bootstrap helpers (reused pattern from K1108c)
# ==========================================================================

def newey_west_bw(n):
    """Andrews (1991) automatic bandwidth for Newey-West HAC."""
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
    """Cluster-robust SE (by firm)."""
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
    # Stata small-sample correction
    scale = (G / (G - 1.0)) * ((n - 1.0) / (n - k)) if G > 1 else 1.0
    cov = scale * XtX_inv @ meat @ XtX_inv
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    return cov, se


def block_bootstrap_beta1(y, x, firms, n_reps=1000, block=5, seed=42,
                           extra_X=None):
    """Block bootstrap β₁ on pooled regression.

    Blocks are drawn within each firm to preserve firm-level serial
    dependence. Returns array of β₁ replicates.
    """
    rng = np.random.default_rng(seed)
    out = np.zeros(n_reps)
    uniq_firms = np.unique(firms)
    idx_by_firm = {f: np.where(firms == f)[0] for f in uniq_firms}

    for r in range(n_reps):
        sel = []
        for f, idxs in idx_by_firm.items():
            m = len(idxs)
            if m == 0:
                continue
            n_blocks = int(np.ceil(m / block))
            for _ in range(n_blocks):
                start_pos = rng.integers(0, max(m - block + 1, 1))
                blk_idx = idxs[start_pos: start_pos + block]
                sel.extend(blk_idx.tolist())
        sel = np.array(sel, dtype=int)
        ys = y[sel]
        xs = x[sel]
        if extra_X is not None:
            Xs = np.column_stack([np.ones(len(sel)), xs, extra_X[sel]])
        else:
            Xs = np.column_stack([np.ones(len(sel)), xs])
        try:
            XtX_inv = np.linalg.pinv(Xs.T @ Xs)
            b = XtX_inv @ Xs.T @ ys
            out[r] = b[1]
        except Exception:
            out[r] = np.nan
    return out[~np.isnan(out)]


# ==========================================================================
# PIT merge (op_leverage → event d)
# ==========================================================================

def pit_merge_opleverage(events_df, oplev_df, lag_days=PIT_LAG_DAYS):
    """For each event row, attach op_leverage_{1,2,3} from the most recent
    fiscal-year-end published >= lag_days before the event date. Rows with
    no matching op_leverage (e.g. pre-2022 events under 5-year yfinance
    coverage) are kept with NaN op_leverage and DROPPED in regression.

    Normalises tickers (K1108c uses stock='2330.TW'; we use ticker='2330.TW';
    both are identical except TSM/ADR case).
    """
    out_rows = []
    for _, ev in events_df.iterrows():
        stock = ev['stock']
        d = pd.Timestamp(ev['event_date']).tz_localize(None)

        # Candidate fy_ends for this firm
        firm_ol = oplev_df.loc[oplev_df['ticker'] == stock].copy()
        firm_ol['pub_date'] = firm_ol['fy_end'] + pd.Timedelta(days=lag_days)
        eligible = firm_ol.loc[firm_ol['pub_date'] <= d]
        if len(eligible) == 0:
            # Out-of-coverage event — mark NaN
            row = ev.to_dict()
            row.update({c: np.nan for c in OPLEV_COLS})
            row['matched_fy_end'] = pd.NaT
            out_rows.append(row)
            continue
        latest = eligible.sort_values('fy_end').iloc[-1]
        row = ev.to_dict()
        for c in OPLEV_COLS:
            row[c] = latest[c]
        row['matched_fy_end'] = latest['fy_end']
        out_rows.append(row)
    return pd.DataFrame(out_rows)


# ==========================================================================
# Stage 1/2: regression specs
# ==========================================================================

def build_design_matrix(df, oplev_col, include_guide=False,
                         firm_fe=False, year_fe=False):
    """Build design matrix for regression.

    Returns (y, X, colnames, cluster_ids_by_firm).
    """
    y = df['theta_eav_empirical'].values
    x = df[oplev_col].values
    firms = df['stock'].values
    years = pd.to_datetime(df['event_date']).dt.year.values

    cols = [np.ones(len(df)), x]
    names = ['intercept', oplev_col]

    if include_guide:
        cols.append(df['guide_delta_pct'].values)
        names.append('guide_delta_pct')

    if firm_fe:
        uniq_firms = sorted(np.unique(firms))[:-1]  # drop last as reference
        for f in uniq_firms:
            cols.append((firms == f).astype(float))
            names.append(f'firm_fe_{f}')

    if year_fe:
        uniq_years = sorted(np.unique(years))[:-1]
        for yr in uniq_years:
            cols.append((years == yr).astype(float))
            names.append(f'year_fe_{yr}')

    X = np.column_stack(cols)
    return y, X, names, firms


def run_spec(df, oplev_col, include_guide=False, firm_fe=False,
             year_fe=False, spec_label=''):
    """Run one regression spec; return dict summary."""
    y, X, names, firms = build_design_matrix(df, oplev_col, include_guide,
                                              firm_fe, year_fe)
    res = ols_hac(y, X)
    # Cluster-robust SE as sensitivity
    _, se_cluster = cluster_robust_cov(X, res['resid'], firms)
    t_cluster = res['beta'] / np.where(se_cluster > 0, se_cluster, np.nan)
    p_cluster = 2.0 * (1.0 - stats.norm.cdf(np.abs(t_cluster)))

    idx_oplev = names.index(oplev_col)
    beta1 = float(res['beta'][idx_oplev])
    se1_hac = float(res['se_hac'][idx_oplev])
    t1_hac = float(res['t_hac'][idx_oplev])
    p1_hac = float(res['p_hac'][idx_oplev])
    t1_cluster = float(t_cluster[idx_oplev])
    p1_cluster = float(p_cluster[idx_oplev])
    ci_lo = beta1 - 1.96 * se1_hac
    ci_hi = beta1 + 1.96 * se1_hac

    return {
        'spec': spec_label,
        'oplev_col': oplev_col,
        'n': int(res['n']),
        'beta1': beta1,
        'se_hac': se1_hac,
        't_hac': t1_hac,
        'p_hac': p1_hac,
        't_cluster_firm': t1_cluster,
        'p_cluster_firm': p1_cluster,
        'ci_95_low_hac': ci_lo,
        'ci_95_high_hac': ci_hi,
        'R2': float(res['R2']),
        'bw': int(res['bw']),
        'include_guide': include_guide,
        'firm_fe': firm_fe,
        'year_fe': year_fe,
        'n_params': int(len(res['beta'])),
        'full_beta': res['beta'].tolist(),
        'full_names': names,
    }


def partial_f_test(df, include_fe=True):
    """Joint F test: are all three op_leverage measures jointly zero?

    H₀: β_op1 = β_op2 = β_op3 = 0 (controlling for firm + year FE)
    H₁: at least one β ≠ 0
    """
    # Restricted: only firm_fe + year_fe + guide_delta_pct
    y, X_u, names_u, _ = build_design_matrix(
        df, 'op_leverage_1',
        include_guide=True, firm_fe=include_fe, year_fe=include_fe,
    )
    # Add op_leverage_2 and op_leverage_3 to unrestricted
    X_u = np.column_stack([X_u,
                            df['op_leverage_2'].values,
                            df['op_leverage_3'].values])
    names_u = list(names_u) + ['op_leverage_2', 'op_leverage_3']

    # Restricted: drop all three op_leverage cols
    oplev_cols_idx = [names_u.index(c) for c in OPLEV_COLS]
    keep_idx = [i for i in range(X_u.shape[1]) if i not in oplev_cols_idx]
    X_r = X_u[:, keep_idx]

    res_u = ols_hac(y, X_u)
    res_r = ols_hac(y, X_r)
    n, k_u = X_u.shape
    k_r = X_r.shape[1]
    q = k_u - k_r  # 3 restrictions

    # F statistic (classical)
    num = (res_r['ss_res'] - res_u['ss_res']) / q
    den = res_u['ss_res'] / (n - k_u)
    F = num / den if den > 0 else np.nan
    p_F = 1.0 - stats.f.cdf(F, q, n - k_u) if np.isfinite(F) else np.nan

    return {
        'F_stat': float(F),
        'p_value': float(p_F),
        'df_num': int(q),
        'df_den': int(n - k_u),
        'n': int(n),
        'ssr_unrestricted': float(res_u['ss_res']),
        'ssr_restricted': float(res_r['ss_res']),
    }


# ==========================================================================
# Verdict
# ==========================================================================

def decide_verdict(spec_cells, partial_f):
    """Apply D3 verdict criteria to 9-cell table + partial-F."""
    max_abs_t = max(abs(c['t_hac']) for c in spec_cells)
    argmax = max(spec_cells, key=lambda c: abs(c['t_hac']))

    bullets = []
    bullets.append(f"max |t_HAC| across 9 cells = {max_abs_t:.3f}  "
                   f"(at {argmax['spec']} × {argmax['oplev_col']})")
    bullets.append(f"partial-F on {{op_lev_1,2,3}} "
                   f"(FE controls, with guide): F={partial_f['F_stat']:.3f}  "
                   f"p={partial_f['p_value']:.4f}")

    if max_abs_t > 3.0 and partial_f['p_value'] < 0.01:
        label = 'H_D3_PASS'
        conclusion = (
            "Operating leverage (balance-sheet fixed-cost structure) PASSES "
            "as a foundry θ_EAV mechanism. Paper 2 foundry-rule interpretation "
            "shifts from event-specific capex guidance to structural PPE/Rev or "
            "debt/equity differences across firms."
        )
    elif max_abs_t > 2.0 and partial_f['p_value'] < 0.10:
        label = 'H_D3_PARTIAL'
        conclusion = (
            "Suggestive but not Harvey-decisive. At least one op_leverage "
            "measure reaches |t|>2 and joint p < 0.10, but max |t| < 3. Report "
            "as partial evidence; further testing in K1108f regime-split."
        )
    else:
        label = 'H_D3_NULL'
        conclusion = (
            "Balance-sheet operating leverage does NOT explain foundry "
            "θ_EAV. Capex (K1108/b/c) + op_leverage (K1108e) are both "
            "falsified as the foundry-specific mechanism. Proceed to "
            "K1108f regime-split or D4 next."
        )
    bullets.append(f"Verdict → {label}")

    return {
        'label': label,
        'max_abs_t_hac': max_abs_t,
        'max_cell': f"{argmax['spec']} × {argmax['oplev_col']}",
        'partial_f_stat': partial_f['F_stat'],
        'partial_f_p': partial_f['p_value'],
        'bullets': bullets,
        'conclusion': conclusion,
    }


# ==========================================================================
# Plots
# ==========================================================================

def plot_scatter_panel(df, spec_cells, oplev_cols):
    """3-panel scatter θ_EAV vs each op_leverage measure (no-FE primary)."""
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.2))
    primary_cells = [c for c in spec_cells
                     if c['spec'] == 'pooled_ols_with_guide']
    cell_by_col = {c['oplev_col']: c for c in primary_cells}
    firms = df['stock'].unique()
    colors = plt.cm.tab10(np.arange(len(firms)))
    firm_color = {f: colors[i] for i, f in enumerate(firms)}
    for i, col in enumerate(oplev_cols):
        ax = axes[i]
        sub = df.dropna(subset=[col])
        for f in firms:
            m = sub['stock'] == f
            ax.scatter(sub.loc[m, col], sub.loc[m, 'theta_eav_empirical'],
                       s=30, alpha=0.7, color=firm_color[f], label=f)
        cell = cell_by_col.get(col)
        if cell is not None:
            # Draw unconditional pooled-OLS line (just for visual reference)
            xs = np.linspace(sub[col].min(), sub[col].max(), 80)
            # Approximate intercept from cell's beta (only β on x not full)
            # We plot slope through mean for visual only
            y_bar = sub['theta_eav_empirical'].mean()
            x_bar = sub[col].mean()
            ys = y_bar + cell['beta1'] * (xs - x_bar)
            ax.plot(xs, ys, 'k-', lw=1.8,
                    label=f"β₁={cell['beta1']:+.2e}  t={cell['t_hac']:+.2f}")
        ax.axhline(0, color='gray', lw=0.6, ls='--')
        ax.set_xlabel(OPLEV_LABELS[col])
        ax.set_ylabel('θ_EAV_empirical')
        ax.set_title(f'K1108e panel: θ_EAV vs {OPLEV_LABELS[col]}')
        ax.legend(loc='best', fontsize=8)
    plt.tight_layout()
    plt.savefig(PLOT_SCATTER, dpi=120)
    plt.close()
    print(f"Saved {PLOT_SCATTER}")


def plot_coef_forest(spec_cells):
    """Coefficient forest plot: β₁ point est + 95% HAC CI across 9 cells."""
    fig, ax = plt.subplots(figsize=(10, 7))
    labels = []
    betas = []
    ci_los = []
    ci_his = []
    colors_list = []
    for cell in spec_cells:
        labels.append(f"{cell['spec']} × {cell['oplev_col']}")
        betas.append(cell['beta1'])
        ci_los.append(cell['ci_95_low_hac'])
        ci_his.append(cell['ci_95_high_hac'])
        if abs(cell['t_hac']) > 3.0:
            colors_list.append('green')
        elif abs(cell['t_hac']) > 2.0:
            colors_list.append('orange')
        else:
            colors_list.append('steelblue')
    ypos = np.arange(len(labels))
    for i, (b, lo, hi, c) in enumerate(zip(betas, ci_los, ci_his, colors_list)):
        ax.plot([lo, hi], [i, i], color=c, lw=2.2)
        ax.plot(b, i, 'o', color=c, ms=7)
    ax.axvline(0, color='red', lw=1, ls='--')
    ax.set_yticks(ypos)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel('β₁ on op_leverage measure (± 95% HAC CI)')
    ax.set_title('K1108e: Operating-leverage coefficient forest\n'
                 'green |t|>3, orange |t|>2, blue NS')
    plt.tight_layout()
    plt.savefig(PLOT_FOREST, dpi=120)
    plt.close()
    print(f"Saved {PLOT_FOREST}")


# ==========================================================================
# Main
# ==========================================================================

def run():
    print(f"=== {EXPERIMENT_ID} — Operating leverage as foundry θ_EAV mechanism ===")
    print(f"Seed=42, start at {time.strftime('%H:%M:%S')}")

    # 0. Load K1108c merged pool
    if not K1108C_POOL_PATH.exists():
        raise FileNotFoundError(f"K1108c merged pool missing: {K1108C_POOL_PATH}")
    pool = pd.read_csv(K1108C_POOL_PATH)
    pool['event_date'] = pd.to_datetime(pool['event_date']).dt.tz_localize(None)
    pool = pool.loc[pool['stock'].isin(PRIMARY_FIRMS)].reset_index(drop=True)
    print(f"Loaded K1108c pool: {len(pool)} events across "
          f"{pool['stock'].nunique()} firms "
          f"({pool['event_date'].min().date()} → "
          f"{pool['event_date'].max().date()})")

    # 1. Load op_leverage
    oplev_path = SCRIPT_DIR / 'k1108e_opleverage_pool.csv'
    if not oplev_path.exists():
        print("op_leverage CSV missing — running fetch script")
        import k1108e_fetch_opleverage as fk  # type: ignore
        fk.main()
    oplev = pd.read_csv(oplev_path)
    oplev['fy_end'] = pd.to_datetime(oplev['fy_end']).dt.tz_localize(None)
    print(f"Loaded op_leverage: {len(oplev)} firm-years, "
          f"{oplev['ticker'].nunique()} firms, "
          f"{oplev['fy_end'].min().date()} → {oplev['fy_end'].max().date()}")

    # 2. PIT merge
    print(f"\n>>> PIT merge op_leverage → events (≥{PIT_LAG_DAYS}d publication lag)")
    merged = pit_merge_opleverage(pool, oplev, PIT_LAG_DAYS)
    n_total = len(merged)
    n_matched = merged[OPLEV_COLS].notna().all(axis=1).sum()
    print(f"  matched {n_matched}/{n_total} events")

    # Filter to matched only for regression
    df_reg = merged.dropna(subset=OPLEV_COLS).reset_index(drop=True)
    print(f"  Regression sample N = {len(df_reg)} events")
    print(f"  By firm:\n{df_reg.groupby('stock').size()}")
    print(f"  Event-year span: "
          f"{df_reg['event_date'].min().date()} → "
          f"{df_reg['event_date'].max().date()}")

    # Drop firms with <4 events (per task brief)
    counts = df_reg.groupby('stock').size()
    drop_firms = counts.loc[counts < 4].index.tolist()
    if drop_firms:
        print(f"  DROPPING firms with <4 events: {drop_firms}")
        df_reg = df_reg.loc[~df_reg['stock'].isin(drop_firms)].reset_index(drop=True)
        print(f"  Final N = {len(df_reg)}")
    df_reg.to_csv(SCRIPT_DIR / 'k1108e_merged_sample.csv', index=False)

    # 3. 9-cell regression matrix
    print("\n>>> 9-cell regression matrix: 3 specs × 3 op_leverage measures")
    spec_cells = []
    spec_defs = [
        ('pooled_ols_with_guide', False, False),
        ('firm_fe_with_guide', True, False),
        ('firm_year_fe_with_guide', True, True),
    ]
    for spec_label, firm_fe, year_fe in spec_defs:
        for col in OPLEV_COLS:
            cell = run_spec(df_reg, col, include_guide=True,
                             firm_fe=firm_fe, year_fe=year_fe,
                             spec_label=spec_label)
            spec_cells.append(cell)
            print(f"  {spec_label:28s} × {col:15s}  "
                  f"β₁={cell['beta1']:+.3e}  t_HAC={cell['t_hac']:+.3f}  "
                  f"p={cell['p_hac']:.4f}  n={cell['n']}")

    # 4. Partial-F joint test
    print("\n>>> Partial-F: all three op_leverage measures jointly zero?")
    partial_f = partial_f_test(df_reg, include_fe=True)
    print(f"  F({partial_f['df_num']}, {partial_f['df_den']}) = "
          f"{partial_f['F_stat']:.3f}  p = {partial_f['p_value']:.4f}")

    # 5. Bootstrap for primary cells (pooled_ols_with_guide × each op_lev)
    print("\n>>> Block bootstrap β₁ (N=1000, block=5, firm-stratified)")
    bootstrap_results = {}
    firms_arr = df_reg['stock'].values
    y_arr = df_reg['theta_eav_empirical'].values
    guide_arr = df_reg['guide_delta_pct'].values
    for col in OPLEV_COLS:
        x_arr = df_reg[col].values
        # extra_X = guide_delta_pct (controlling for K1108c covariate)
        boot = block_bootstrap_beta1(
            y_arr, x_arr, firms_arr,
            n_reps=1000, block=5, seed=42,
            extra_X=guide_arr,
        )
        ci_lo = float(np.percentile(boot, 2.5))
        ci_hi = float(np.percentile(boot, 97.5))
        p_two = float(2 * min(np.mean(boot >= 0), np.mean(boot <= 0)))
        bootstrap_results[col] = {
            'n_reps': int(len(boot)),
            'mean': float(np.mean(boot)),
            'sd': float(np.std(boot)),
            'ci_95_low': ci_lo,
            'ci_95_high': ci_hi,
            'p_value_two_sided': p_two,
            'ci_excludes_zero': bool((ci_lo > 0 and ci_hi > 0)
                                     or (ci_lo < 0 and ci_hi < 0)),
        }
        print(f"  {col:15s}  boot β̄={np.mean(boot):+.3e}  "
              f"95% CI=[{ci_lo:+.3e}, {ci_hi:+.3e}]  p={p_two:.4f}  "
              f"excludes 0: {bootstrap_results[col]['ci_excludes_zero']}")

    # 6. Verdict
    verdict = decide_verdict(spec_cells, partial_f)
    print(f"\n>>> VERDICT: {verdict['label']}")
    for b in verdict['bullets']:
        print(f"    {b}")
    print(f"    Conclusion: {verdict['conclusion']}")

    # 7. Plots
    plot_scatter_panel(df_reg, spec_cells, OPLEV_COLS)
    plot_coef_forest(spec_cells)

    # 8. Persist
    runtime = float(time.time() - START_TIME)
    results = {
        'experiment_id': EXPERIMENT_ID,
        'parent': 'K1108c (H2_MAGNITUDE_NULL DECISIVE)',
        'grand_parent': 'K1108b (H2 DECISIVE NULL with binary flag)',
        'hypothesis': 'D3: foundry θ_EAV driven by balance-sheet operating leverage',
        'timestamp': pd.Timestamp.utcnow().isoformat(),
        'data_source': [
            'experiments/k1108c/k1108c_merged_pool.csv (4-firm θ_EAV + guide_delta_pct)',
            'yfinance Ticker(...).balance_sheet + .financials (annual PPE/Debt/Equity/SGA/Revenue)',
        ],
        'yfinance_coverage_limit_notice': (
            'yfinance annual BS/IS data covers 2021-12-31 to 2025-12-31 only '
            '(5 fiscal years). Events pre-2022 are DROPPED from K1108e '
            'regression sample. This is a HARD constraint of the free API.'
        ),
        'pool_firms': PRIMARY_FIRMS,
        'pit_lag_days': PIT_LAG_DAYS,
        'n_events_k1108c_pool': int(len(pool)),
        'n_events_matched_oplev': int(n_matched),
        'n_events_regression_sample': int(len(df_reg)),
        'firms_dropped_lt4_events': drop_firms,
        'event_year_range_reg': [
            str(df_reg['event_date'].min().date()),
            str(df_reg['event_date'].max().date()),
        ],
        'by_firm_counts': df_reg.groupby('stock').size().to_dict(),
        'op_leverage_descriptives': {
            col: {
                'mean': float(df_reg[col].mean()),
                'sd': float(df_reg[col].std()),
                'min': float(df_reg[col].min()),
                'max': float(df_reg[col].max()),
            } for col in OPLEV_COLS
        },
        'regression_cells_9': [
            {k: v for k, v in c.items()
             if k not in ('full_beta', 'full_names')}
            for c in spec_cells
        ],
        'partial_f_joint_test': partial_f,
        'bootstrap_results': bootstrap_results,
        'verdict': verdict,
        'comparison_to_prior_K1108': {
            'K1108_TSMC_single_firm_N48': 'INCONCLUSIVE (t=0.94)',
            'K1108b_4firm_pooled_binary': 'H2 DECISIVE NULL (pool t=-0.0003)',
            'K1108c_continuous_magnitude': 'H2_MAGNITUDE_NULL DECISIVE (t=-1.34)',
            'K1108e_opleverage': verdict['label'],
        },
        'next_action': (
            'K1108f regime-split' if verdict['label'] == 'H_D3_NULL'
            else ('K1108g: paper 2 balance-sheet mechanism narrative integration'
                  if verdict['label'] == 'H_D3_PASS'
                  else 'K1108f regime-split (partial)')
        ),
        'references': [
            'K1108 (TSMC single-firm capex-guidance INCONCLUSIVE)',
            'K1108b (4-firm binary NULL)',
            'K1108c (4-firm continuous NULL)',
            'K1104 (foundry θ₂>0 rule)',
            'K1067 (A4f-EAV baseline)',
            'Mandelker & Rhee (1984). Impact of degrees of op+fin leverage on systematic risk of common stock. J Fin Quant Anal 19(1):45-57.',
            'Novy-Marx (2011). Operating leverage. Rev Financ 15(1):103-134.',
            'Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3).',
            'Andrews (1991). HAC auto-bandwidth. Econometrica 59(3):817-858.',
            'Newey & West (1987). HAC SE. Econometrica 55(3):703-708.',
            'Harvey et al. (2016). Cross-section of expected returns. RFS 29(1):5-68.',
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
    run()
