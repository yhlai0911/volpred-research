#!/usr/bin/env python3
"""
K1470 — 100-Multistart Re-estimation of the Main Table 1 Spec (K1145/K1147/K1150)

Motivation
----------
paper/eav-universal-magnitude Table 1 (tab:main_results) reports pooled
theta_EAV for TW (K1145, N=31), US (K1147, N=30), JP (K1150, N=30) estimated
with the BCD (block coordinate descent) pooled MLE under a SINGLE default
initialisation (init_vix=1e-7, init_eav=5e-5). The Section 6.6.4 multistart
audit (K1213/K1216/K1216b/K1216c) showed that the *joint* pooled-MLE variant
of this spec (S<=10 pools, K1168/K1172 ladder) has a panel-wide two-basin
likelihood surface: 10/10 audited markets FRAGILE (default init lands in an
inferior basin; LR 146-2837 vs chi2(1)=3.84).

The main Table 1 numbers were therefore flagged in body.tex (line ~598-607):
"(K1145/K1147/K1150) are produced under default single-init L-BFGS-B and
must be re-run under the same multistart protocol". K1470 executes that
re-run on the ORIGINAL main spec (BCD, full N=30/31 panels) — not the S=10
joint-MLE reduction audited in K1216c.

Protocol (Section 6.6.4 / sec:multistart_method, adapted to the BCD spec)
-------------------------------------------------------------------------
1. 100 random initialisations per market, seeds 43..142 (identical seed
   discipline to K1213/K1216/K1216b/K1216c):
     init_eav  ~ log-uniform on [1e-6, 5e-4]   (verbatim protocol step 1)
     init_vix  ~ log-uniform on [1e-9, 1e-3]   (the BCD shared bound box;
                 the canonical BCD has no theta0 in the shared block —
                 theta0_i are stock fixed effects refit in the inner loop,
                 so the random-init dimension is the shared (vix, eav) pair)
   Estimation procedure per start = EXACTLY the original spec call:
   fit_pooled_panel(stocks, max_outer=8, time_budget=600) — same inner
   3-start per-stock L-BFGS-B, same bounds, same lag conventions
   (vix[t-1], eav[t-1] inside _negll_numba; nothing touched).
2. Penalty-trap guard: reject non-finite LL or LL < 1000.
3. K-means (K=2) basin identification on (theta_EAV, LL) pairs
   (kmeans_basins vendored verbatim from experiments/k1216/k1216.py).
4. Best-LL across valid starts = multistart estimate.
5. Sensitivity polish: Nelder-Mead warm-start on the shared 2-vector at the
   best fit's per-stock params, then a short BCD continuation (max_outer=3)
   so the polished LL is computed like-with-like (final inner pass included,
   exactly as fit_pooled_panel does for every fit).
6. Refined = argmax LL over {canonical, best multistart, NM continuation}.
7. LR = 2*(LL_refined - LL_canonical) vs chi2(1) = 3.84.
   FRAGILE  if LR > 3.84 (canonical sits in an inferior basin)
   STABLE   if LR <= 3.84 (canonical is the global basin)
8. Hessian SE on theta_EAV at the refined point (module's own
   hessian_se_theta_eav — numerical 2nd derivative, stock params fixed).
9. Cross-market magnitude ordering check: canonical US > JP > TW —
   does it survive refinement?
10. Seed discipline: base=42; start seeds 43..142; K-means seed 42.

Data / spec provenance (NOT re-implemented — imported from the originals)
-------------------------------------------------------------------------
- experiments/k1145/k1145.py  TW  N=31, 2010-2025, TWSE announcement file
- experiments/k1147/k1147.py  US  N=30, 2014-2025, yfinance earnings dates
- experiments/k1150/k1150.py  JP  N=30, 2014-2025, yfinance earnings dates
All price/VIX/earnings data come from the cached parquet/json files inside
each original experiment's data/ directory (no network needed).

Canonical reference values (verbatim from the stored results.json):
- k1145_results.json main_fit_eav_window_1: theta_eav=6.362165248598386e-05,
  pooled_loglik=329349.9818402385
- k1147_results.json main_fit_eav_window_1: theta_eav=0.00019089860360002893,
  pooled_loglik=256713.69603405558
- k1150_results.json main_fit_eav_window_1: theta_eav=0.00014127865441754286,
  pooled_loglik=234432.52034662137

Honesty rules
-------------
- The canonical fit is REPRODUCED here with the exact original call and
  cross-checked against the stored results.json (rel tol 1e-3). If the
  reproduction diverges, the run aborts the market with INCONCLUSIVE —
  we never silently substitute a different baseline.
- No paper .tex is modified by this script. No knowledge.json writes.
- All randomness seeded. Lag conventions untouched (inherited verbatim).

Outputs
-------
experiments/k1470_eav_multistart_main_spec/
  k1470_results.json            final 3-market results
  k1470_results_partial.json    per-market checkpoint (long-job safety)
  k1470_multistart_<MKT>.csv    per-start table (seed, inits, estimates, LL)
  k1470_basin_hist_<MKT>.png    theta_EAV multistart histogram + lines
"""

import csv
import importlib.util
import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy import optimize

warnings.filterwarnings('ignore')

GLOBAL_SEED = 42
np.random.seed(GLOBAL_SEED)

EXPERIMENT_ID = 'K1470'
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT = SCRIPT_DIR.parent.parent

N_STARTS = int(os.environ.get('K1470_N_STARTS', '100'))
START_SEEDS = list(range(43, 43 + N_STARTS))          # 43..142 by default
MARKETS_ENV = os.environ.get('K1470_MARKETS', 'TW,US,JP')
PER_FIT_MAX_OUTER = 8          # identical to original main fit
PER_FIT_TIME_BUDGET = 600      # identical to original main fit
CHI2_1_95 = 3.841458820694124  # chi2(1) 5% critical value

RESULTS_PATH = SCRIPT_DIR / 'k1470_results.json'
PARTIAL_PATH = SCRIPT_DIR / 'k1470_results_partial.json'

# Canonical stored values (verbatim from each results.json, see docstring)
CANONICAL_STORED = {
    'TW': {'exp': 'K1145', 'theta_eav': 6.362165248598386e-05,
           'pooled_loglik': 329349.9818402385, 'n_stocks': 31},
    'US': {'exp': 'K1147', 'theta_eav': 0.00019089860360002893,
           'pooled_loglik': 256713.69603405558, 'n_stocks': 30},
    'JP': {'exp': 'K1150', 'theta_eav': 0.00014127865441754286,
           'pooled_loglik': 234432.52034662137, 'n_stocks': 30},
}

MODULE_FILES = {
    'TW': PROJECT / 'experiments' / 'k1145' / 'k1145.py',
    'US': PROJECT / 'experiments' / 'k1147' / 'k1147.py',
    'JP': PROJECT / 'experiments' / 'k1150' / 'k1150.py',
}


def log(msg):
    print(msg, flush=True)


def load_module(market):
    path = MODULE_FILES[market]
    name = f'k1470_src_{market.lower()}'
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# kmeans_basins — vendored VERBATIM from experiments/k1216/k1216.py:345
# (k1216c imported it the same way; vendored here so K1470 does not execute
#  k1216.py module-level code).
# ---------------------------------------------------------------------------
def kmeans_basins(theta_eavs, logliks, seed=42):
    """K=2 K-means on standardized (theta_EAV, LL); basin 0 = low-theta."""
    X = np.column_stack([theta_eavs, logliks])
    mu = X.mean(axis=0); sd = X.std(axis=0)
    sd[sd == 0] = 1.0
    Z = (X - mu) / sd
    rng = np.random.default_rng(seed)
    if len(Z) < 2:
        return np.zeros(len(Z), dtype=int), {
            'basin_A_frac': 1.0, 'basin_B_frac': 0.0,
            'basin_A_theta_mean': float(theta_eavs.mean()) if len(theta_eavs) else None,
            'basin_B_theta_mean': None,
            'basin_A_ll_mean': float(logliks.mean()) if len(logliks) else None,
            'basin_B_ll_mean': None,
            'basin_A_ll_max': float(logliks.max()) if len(logliks) else None,
            'basin_B_ll_max': None,
        }
    idx = rng.choice(len(Z), size=2, replace=False)
    c = Z[idx].copy()
    for _ in range(200):
        d = np.linalg.norm(Z[:, None, :] - c[None, :, :], axis=2)
        lbl = np.argmin(d, axis=1)
        new_c = np.array([Z[lbl == k].mean(axis=0) if (lbl == k).any()
                          else c[k] for k in range(2)])
        if np.allclose(new_c, c, atol=1e-8):
            break
        c = new_c
    means = np.array([theta_eavs[lbl == k].mean() if (lbl == k).any()
                      else np.inf for k in range(2)])
    if means[0] > means[1]:
        lbl = 1 - lbl
    stats = {
        'basin_A_frac': float(np.mean(lbl == 0)),
        'basin_B_frac': float(np.mean(lbl == 1)),
        'basin_A_theta_mean': float(theta_eavs[lbl == 0].mean())
            if (lbl == 0).any() else None,
        'basin_B_theta_mean': float(theta_eavs[lbl == 1].mean())
            if (lbl == 1).any() else None,
        'basin_A_ll_mean': float(logliks[lbl == 0].mean())
            if (lbl == 0).any() else None,
        'basin_B_ll_mean': float(logliks[lbl == 1].mean())
            if (lbl == 1).any() else None,
        'basin_A_ll_max': float(logliks[lbl == 0].max())
            if (lbl == 0).any() else None,
        'basin_B_ll_max': float(logliks[lbl == 1].max())
            if (lbl == 1).any() else None,
    }
    return lbl, stats


def is_valid_fit(fit):
    """Penalty-trap guard (protocol step 2, adapted: LL here is ~2.3e5-3.3e5)."""
    if fit is None:
        return False
    ll = fit.get('pooled_loglik')
    return ll is not None and np.isfinite(ll) and ll > 1000.0


def fit_summary_row(seed, iv, ie, fit, valid):
    return {
        'start_seed': seed,
        'init_vix': iv,
        'init_eav': ie,
        'theta_vix': fit['theta_vix'] if fit else None,
        'theta_eav': fit['theta_eav'] if fit else None,
        'pooled_loglik': fit['pooled_loglik'] if fit else None,
        'n_outer_iters': fit['n_outer_iters'] if fit else None,
        'converged_flag': fit['converged'] if fit else None,
        'valid': valid,
    }


def nm_polish(mod, stocks, best_fit):
    """Protocol step 5 adapted to BCD: NM warm-start on the shared 2-vector
    at the best fit's per-stock params, then a short BCD continuation so the
    LL is computed like-with-like (with inner refits + final pass)."""
    tv0 = best_fit['theta_vix']
    te0 = best_fit['theta_eav']
    stock_params = [np.array(p) for p in best_fit['per_stock_params']]
    try:
        res = optimize.minimize(
            mod.shared_objective, [tv0, te0],
            args=(stocks, stock_params),
            method='Nelder-Mead',
            options={'maxiter': 400, 'xatol': 1e-12, 'fatol': 1e-8},
        )
        tv_nm, te_nm = float(res.x[0]), float(res.x[1])
    except Exception as exc:
        log(f'    [NM] failed: {exc}')
        return None
    # clip into the BCD shared bounds before continuation
    tv_nm = min(max(tv_nm, 1e-9), 1e-3)
    te_nm = min(max(te_nm, -1e-2), 1e-2)
    cont = mod.fit_pooled_panel(stocks, max_outer=3, init_vix=tv_nm,
                                init_eav=te_nm, verbose=False,
                                time_budget=PER_FIT_TIME_BUDGET)
    cont['nm_shared'] = [tv_nm, te_nm]
    return cont


def plot_basin_hist(out_path, market, theta_eavs, labels,
                    canon_theta, refined_theta):
    fig, ax = plt.subplots(figsize=(8, 5))
    t_a = theta_eavs[labels == 0]
    t_b = theta_eavs[labels == 1]
    bins = 40
    ax.hist(t_a, bins=bins, alpha=0.65, label=f'basin A (n={len(t_a)})',
            color='#4878CF')
    if len(t_b):
        ax.hist(t_b, bins=bins, alpha=0.65, label=f'basin B (n={len(t_b)})',
                color='#EE854A')
    ax.axvline(canon_theta, color='red', ls='--', lw=1.5,
               label=f'canonical {canon_theta:.3e}')
    ax.axvline(refined_theta, color='green', ls='-', lw=1.5,
               label=f'refined {refined_theta:.3e}')
    ax.set_xlabel(r'$\hat{\theta}_{EAV}$ (multistart converged)')
    ax.set_ylabel('count')
    ax.set_title(f'K1470 {market}: main-spec BCD multistart '
                 f'({len(theta_eavs)} valid starts, seeds 43..142)')
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    log(f'    plot -> {out_path}')


def run_market(market):
    t0 = time.time()
    log(f"\n{'=' * 72}\n[K1470 {market}] loading original module + cached data\n{'=' * 72}")
    mod = load_module(market)
    stored = CANONICAL_STORED[market]

    stocks = []
    for tk in mod.TICKERS:
        st = mod.load_one_stock(tk, eav_window=1)
        if st is not None:
            stocks.append(st)
    log(f'[{market}] loaded {len(stocks)}/{len(mod.TICKERS)} stocks '
        f'(stored n_stocks={stored["n_stocks"]})')
    if len(stocks) != stored['n_stocks']:
        log(f'[{market}] PANEL MISMATCH vs stored results — INCONCLUSIVE')
        return {'market': market, 'source_experiment': stored['exp'],
                'verdict': 'INCONCLUSIVE_PANEL_MISMATCH',
                'n_stocks_loaded': len(stocks)}

    mean_sigma2 = float(np.mean([np.var(st['r']) for st in stocks]))
    pooled_obs = int(sum(st['n_obs'] for st in stocks))
    log(f'[{market}] pooled_obs={pooled_obs}  mean_sigma2={mean_sigma2:.3e}')

    # ---- 1) canonical reproduction (exact original call) ----
    log(f'[{market}] canonical reproduction: fit_pooled_panel(max_outer=8, '
        f'time_budget=600, default init 1e-7/5e-5) ...')
    tc = time.time()
    canon = mod.fit_pooled_panel(stocks, max_outer=PER_FIT_MAX_OUTER,
                                 verbose=False,
                                 time_budget=PER_FIT_TIME_BUDGET)
    canon_secs = time.time() - tc
    rel_theta = abs(canon['theta_eav'] - stored['theta_eav']) / abs(stored['theta_eav'])
    rel_ll = abs(canon['pooled_loglik'] - stored['pooled_loglik']) / abs(stored['pooled_loglik'])
    log(f'[{market}] canonical repro: theta_eav={canon["theta_eav"]:+.6e} '
        f'LL={canon["pooled_loglik"]:.2f} ({canon_secs:.1f}s) | '
        f'stored theta_eav={stored["theta_eav"]:+.6e} LL={stored["pooled_loglik"]:.2f} | '
        f'rel_dtheta={rel_theta:.2e} rel_dLL={rel_ll:.2e}')
    repro_ok = (rel_theta < 1e-3) and (rel_ll < 1e-4)
    if not repro_ok:
        log(f'[{market}] CANONICAL REPRODUCTION FAILED (tol 1e-3/1e-4) — '
            f'reporting both, verdict INCONCLUSIVE_REPRO_MISMATCH')
        return {
            'market': market, 'source_experiment': stored['exp'],
            'verdict': 'INCONCLUSIVE_REPRO_MISMATCH',
            'canonical_stored': stored,
            'canonical_reproduced': {k: canon[k] for k in
                                     ('theta_vix', 'theta_eav',
                                      'pooled_loglik', 'n_outer_iters',
                                      'converged')},
        }

    # ---- 2) 100 multistart (seeds 43..142) ----
    log(f'[{market}] multistart x{N_STARTS} (seeds {START_SEEDS[0]}..'
        f'{START_SEEDS[-1]}), per-start = exact original BCD call ...')
    rows = []
    fits = []
    tm = time.time()
    for i, seed in enumerate(START_SEEDS):
        rng = np.random.default_rng(seed)
        # protocol step 1: log-uniform theta_EAV on [1e-6, 5e-4];
        # shared vix init log-uniform on its BCD bound box [1e-9, 1e-3]
        ie = float(10.0 ** rng.uniform(-6.0, np.log10(5e-4)))
        iv = float(10.0 ** rng.uniform(-9.0, -3.0))
        try:
            fit = mod.fit_pooled_panel(stocks, max_outer=PER_FIT_MAX_OUTER,
                                       init_vix=iv, init_eav=ie,
                                       verbose=False,
                                       time_budget=PER_FIT_TIME_BUDGET)
        except Exception as exc:
            log(f'  [start {i + 1}/{N_STARTS}] seed={seed} EXC: {exc}')
            fit = None
        valid = is_valid_fit(fit)
        rows.append(fit_summary_row(seed, iv, ie, fit, valid))
        if valid:
            fits.append(fit)
        if (i + 1) % 10 == 0:
            el = time.time() - tm
            log(f'  [start {i + 1}/{N_STARTS}] valid={len(fits)}/{i + 1} '
                f'elapsed={el:.0f}s (~{el / (i + 1):.1f}s/start)')

    csv_path = SCRIPT_DIR / f'k1470_multistart_{market}.csv'
    with open(csv_path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    log(f'[{market}] multistart done in {time.time() - tm:.0f}s; '
        f'valid={len(fits)}/{N_STARTS}; csv -> {csv_path}')

    if len(fits) < 5:
        return {'market': market, 'source_experiment': stored['exp'],
                'verdict': 'INCONCLUSIVE_TOO_FEW_VALID',
                'n_valid': len(fits),
                'canonical_reproduced_loglik': canon['pooled_loglik']}

    theta_eavs = np.array([f['theta_eav'] for f in fits])
    logliks = np.array([f['pooled_loglik'] for f in fits])

    # ---- 3) basin identification ----
    labels, basin_stats = kmeans_basins(theta_eavs, logliks, seed=GLOBAL_SEED)
    log(f'[{market}] basins: A frac={basin_stats["basin_A_frac"]:.2f} '
        f'theta_mean={basin_stats["basin_A_theta_mean"]} '
        f'll_max={basin_stats["basin_A_ll_max"]} | '
        f'B frac={basin_stats["basin_B_frac"]:.2f} '
        f'theta_mean={basin_stats["basin_B_theta_mean"]} '
        f'll_max={basin_stats["basin_B_ll_max"]}')

    # ---- 4) best multistart ----
    best_idx = int(np.argmax(logliks))
    best_fit = fits[best_idx]
    best_seed = next((r['start_seed'] for r in rows
                      if r['valid'] and
                      r['pooled_loglik'] == best_fit['pooled_loglik']), None)
    log(f'[{market}] best multistart: theta_eav={best_fit["theta_eav"]:+.6e} '
        f'LL={best_fit["pooled_loglik"]:.2f} (seed={best_seed})')

    # ---- 5) NM polish + BCD continuation ----
    log(f'[{market}] Nelder-Mead polish + BCD continuation ...')
    polished = nm_polish(mod, stocks, best_fit)
    if polished is not None and is_valid_fit(polished):
        log(f'[{market}] NM continuation: theta_eav={polished["theta_eav"]:+.6e} '
            f'LL={polished["pooled_loglik"]:.2f}')
    else:
        log(f'[{market}] NM polish invalid/failed — skipped')
        polished = None

    # ---- 6) refined = argmax LL over {canonical, best multistart, NM} ----
    candidates = {'canonical': canon, 'best_multistart': best_fit}
    if polished is not None:
        candidates['nm_continuation'] = polished
    refined_name = max(candidates, key=lambda k: candidates[k]['pooled_loglik'])
    refined = candidates[refined_name]

    # ---- 7) LR test ----
    lr = 2.0 * (refined['pooled_loglik'] - canon['pooled_loglik'])
    verdict = 'FRAGILE' if lr > CHI2_1_95 else 'STABLE'
    theta_shift = refined['theta_eav'] - canon['theta_eav']
    theta_ratio = (refined['theta_eav'] / canon['theta_eav']
                   if canon['theta_eav'] != 0 else None)
    # Secondary identification diagnostic (does NOT change the protocol
    # verdict): LR within chi2(1) noise but theta_EAV moved materially
    # (>2x or <0.5x) = near-flat likelihood ridge in theta_EAV — the point
    # estimate is weakly identified even though canonical is "STABLE" by LR.
    flat_ridge = (lr <= CHI2_1_95 and theta_ratio is not None and
                  (theta_ratio > 2.0 or theta_ratio < 0.5))
    identification_flag = 'FLAT_RIDGE' if flat_ridge else 'OK'
    log(f'[{market}] refined={refined_name}: theta_eav={refined["theta_eav"]:+.6e} '
        f'LL={refined["pooled_loglik"]:.2f} | LR={lr:+.3f} vs chi2(1)=3.84 '
        f'-> {verdict} | theta ratio refined/canon={theta_ratio} | '
        f'identification={identification_flag}')

    # ---- 8) Hessian SE at refined ----
    ref_params = [np.array(p) for p in refined['per_stock_params']]
    hess_se = mod.hessian_se_theta_eav(stocks, ref_params,
                                       refined['theta_vix'],
                                       refined['theta_eav'])
    hess_t = (refined['theta_eav'] / hess_se) if hess_se else None
    log(f'[{market}] refined Hessian SE={hess_se} t={hess_t}')

    # ---- plot ----
    plot_basin_hist(SCRIPT_DIR / f'k1470_basin_hist_{market}.png', market,
                    theta_eavs, labels, canon['theta_eav'],
                    refined['theta_eav'])

    elapsed = time.time() - t0
    log(f'[{market}] done in {elapsed:.0f}s')
    return {
        'market': market,
        'source_experiment': stored['exp'],
        'n_stocks': len(stocks),
        'pooled_obs': pooled_obs,
        'mean_sigma2': mean_sigma2,
        'canonical_stored': stored,
        'canonical_reproduced': {
            'theta_vix': canon['theta_vix'],
            'theta_eav': canon['theta_eav'],
            'pooled_loglik': canon['pooled_loglik'],
            'n_outer_iters': canon['n_outer_iters'],
            'converged': canon['converged'],
            'repro_rel_dtheta': rel_theta,
            'repro_rel_dll': rel_ll,
        },
        'multistart': {
            'n_starts': N_STARTS,
            'start_seeds': [START_SEEDS[0], START_SEEDS[-1]],
            'n_valid': len(fits),
            'theta_eav_min': float(theta_eavs.min()),
            'theta_eav_max': float(theta_eavs.max()),
            'theta_eav_std': float(theta_eavs.std()),
            'loglik_min': float(logliks.min()),
            'loglik_max': float(logliks.max()),
            'loglik_spread': float(logliks.max() - logliks.min()),
            'basin_stats': basin_stats,
            'best': {
                'start_seed': best_seed,
                'theta_vix': best_fit['theta_vix'],
                'theta_eav': best_fit['theta_eav'],
                'pooled_loglik': best_fit['pooled_loglik'],
            },
        },
        'nm_continuation': (None if polished is None else {
            'nm_shared': polished.get('nm_shared'),
            'theta_vix': polished['theta_vix'],
            'theta_eav': polished['theta_eav'],
            'pooled_loglik': polished['pooled_loglik'],
        }),
        'refined': {
            'source': refined_name,
            'theta_vix': refined['theta_vix'],
            'theta_eav': refined['theta_eav'],
            'theta_rel': refined['theta_eav'] / mean_sigma2,
            'pooled_loglik': refined['pooled_loglik'],
            'hessian_se': hess_se,
            'hessian_t': hess_t,
        },
        'lr_test': {
            'lr_stat': lr,
            'chi2_1_crit': CHI2_1_95,
            'theta_shift': theta_shift,
            'theta_ratio_refined_over_canonical': theta_ratio,
        },
        'verdict': verdict,
        'identification_flag': identification_flag,
        'elapsed_seconds': elapsed,
    }


def main():
    t0 = time.time()
    markets = [m.strip() for m in MARKETS_ENV.split(',') if m.strip()]
    log(f'K1470 — main Table 1 spec (K1145/K1147/K1150) {N_STARTS}-multistart '
        f're-estimation\nmarkets={markets} seeds={START_SEEDS[0]}..'
        f'{START_SEEDS[-1]} base_seed={GLOBAL_SEED}')

    per_market = {}
    for mkt in markets:
        per_market[mkt] = run_market(mkt)
        # checkpoint after each market (long-job safety)
        with open(PARTIAL_PATH, 'w') as f:
            json.dump(per_market, f, indent=2, default=str)
        log(f'[checkpoint] -> {PARTIAL_PATH}')

    # ---- cross-market ordering check ----
    ordering = None
    complete = all(per_market.get(m, {}).get('verdict') in ('FRAGILE', 'STABLE')
                   for m in ('TW', 'US', 'JP')) and set(markets) >= {'TW', 'US', 'JP'}
    if complete:
        canon_theta = {m: per_market[m]['canonical_reproduced']['theta_eav']
                       for m in ('TW', 'US', 'JP')}
        ref_theta = {m: per_market[m]['refined']['theta_eav']
                     for m in ('TW', 'US', 'JP')}
        canon_order = sorted(canon_theta, key=canon_theta.get, reverse=True)
        ref_order = sorted(ref_theta, key=ref_theta.get, reverse=True)
        ordering = {
            'canonical_theta_eav': canon_theta,
            'refined_theta_eav': ref_theta,
            'canonical_order': canon_order,
            'refined_order': ref_order,
            'canonical_order_is_US_JP_TW': canon_order == ['US', 'JP', 'TW'],
            'refined_order_is_US_JP_TW': ref_order == ['US', 'JP', 'TW'],
            'ordering_preserved': canon_order == ref_order,
        }
        log(f'\n[ordering] canonical: {canon_order} '
            f'({ {m: f"{v:.3e}" for m, v in canon_theta.items()} })')
        log(f'[ordering] refined:   {ref_order} '
            f'({ {m: f"{v:.3e}" for m, v in ref_theta.items()} })')

    results = {
        'experiment_id': EXPERIMENT_ID,
        'title': '100-multistart re-estimation of main Table 1 spec '
                 '(K1145 TW / K1147 US / K1150 JP BCD pooled MLE)',
        'proposer': 'Claude (paper eav-universal-magnitude sec 6.6.4 '
                    'mandated re-run of single-init main results)',
        'executor': 'compute_queue worker',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'random_seed': GLOBAL_SEED,
        'start_seeds': [START_SEEDS[0], START_SEEDS[-1]],
        'protocol': 'sec:multistart_method (K1213/K1216/K1216b/K1216c), '
                    'adapted to BCD: random shared-init (log-uniform '
                    'theta_EAV [1e-6,5e-4]; log-uniform theta_VIX '
                    '[1e-9,1e-3]) x exact original fit_pooled_panel call '
                    '(max_outer=8, time_budget=600); penalty guard; '
                    'K-means K=2 basins; NM polish + BCD continuation; '
                    'LR vs chi2(1)=3.84',
        'spec_provenance': 'fit_pooled_panel / load_one_stock / '
                           'hessian_se_theta_eav imported verbatim from '
                           'experiments/k1145/k1145.py, k1147/k1147.py, '
                           'k1150/k1150.py (no re-implementation; lag '
                           'conventions untouched)',
        'per_market': per_market,
        'ordering_check': ordering,
        'elapsed_seconds_total': time.time() - t0,
    }
    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    log(f'\nResults -> {RESULTS_PATH}')
    log(f'Total elapsed: {time.time() - t0:.0f}s')

    if complete:
        verdicts = {m: per_market[m]['verdict'] for m in ('TW', 'US', 'JP')}
        log(f'VERDICTS: {verdicts}')
        log(f'ORDERING preserved: {ordering["ordering_preserved"]} '
            f'(refined order = {ordering["refined_order"]})')


if __name__ == '__main__':
    main()
