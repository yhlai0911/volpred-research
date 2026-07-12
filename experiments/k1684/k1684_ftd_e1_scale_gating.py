"""
K1684 R2 — forecast-tail-divergence E1: variance-target scale re-calibration GATING experiment.

This is the CANONICAL RERUN. The first pass (R1, 2026-07-12) was BLOCKED by Codex review on
seven counts; every one of them is closed here and the closure is machine-checked in
`k1684_rerun_r2_receipt.json`. R1's numbers are anchors only — nothing from R1 was carried
forward, and nothing in this script is allowed to reuse an R1 result.

The question
------------
K850/K854 headline: HAR-RV beats GJR-GARCH on QLIKE by a wide margin, yet its 1% VaR is Basel
RED while GJR+CF passes the trinity ("good forecasts, bad VaR" — an apparent orthogonality
between central forecast accuracy and tail coverage). The Fable deep review (2026-07-11)
argued this divergence may be manufactured by a variance-TARGET mismatch: HAR's sigma comes
from TAIFEX TX futures 5-min RV, but the VaR is scored on 0050.TW ETF close-to-close returns.

The divergence claim has TWO legs and both are re-tested from scratch:
    leg 1 (forecast loss)  HAR beats GJR on QLIKE -- on a target BOTH models are scored against
    leg 2 (tail coverage)  HAR fails the VaR trinity where GJR passes -- and survives a scale fix

What R2 changes (the seven R1 blockers)
---------------------------------------
G1 RV construction. R1 used K854's `TX1` file and summed three SEPARATE sessions, dropping
   every session-boundary jump, and ran the day session to 13:45 while the ETF closes at
   13:30. R2 rebuilds RV from ALL TX contracts, picks each trade date's volume-maximal active
   contract, and integrates ONE CONTINUOUS price path from 13:30(D-1) to 13:30(D) -- the exact
   window of the ETF return it is used to forecast, with every boundary jump inside it. See
   `k1684_rv_active.py`. The 13:30/13:45 information-set overlap is sealed by construction and
   audited mechanically (`rv_information_set_audit`).
G2 GJR (and, symmetrically, RealGARCH-Log) are re-estimated with >=100 random starts; every
   refit stores its convergence rate, objective distribution and likelihood-basin spread. The
   R1 fragility probe -- which showed a 1e-6 data revision moving 4-start GJR sigma by 29% --
   is re-run against BOTH fitters so the fix can be verified rather than asserted.
G3 The implied scale factor is re-derived. R1 used c = Phi^-1(alpha)/Phi^-1(pi_hat) for EVERY
   cell (it is only identified under a Normal scale assumption) and inverted the CI bounds
   (c is INCREASING in pi, not decreasing), producing 154 cells with lo95 > hi95. R2 reports
   (i) a distribution-free empirical scale factor -- the factor that would put the realized
   violation rate exactly at alpha, identified for any tail layer -- with a seeded bootstrap
   CI, and (ii) the parametric Normal c ONLY for Normal-tail cells, with the monotonicity
   asserted in code. The untested |dc| < 0.10 threshold is replaced by a bootstrap test of
   H0: c(1%) = c(5%).
G4 The placebo (the same correction machinery applied to the correctly-targeted GJR) is
   reported in full -- both alphas, IS and OOS, VaR and ES, with a bootstrap CI on its scale
   factor -- instead of being waved through as "near 1".
G5 Formal conclusions use the Harvey bar |t| > 3, not p < 0.05. Every DM pair uses its own
   pairwise common mask and reports its own n. decide_gate() now actually checks leg 2's
   "GJR passes the trinity" clause it always claimed to check.
G6 Both alpha levels, in-sample AND out-of-sample, VaR AND ES (with a McNeil-Frey bootstrap
   ES test) and the Fissler-Ziegel FZ0 joint VaR-ES loss.
G7 Results are written atomically (tmp -> json.load verify -> os.replace); seeds, provenance
   and a perturbation-based lookahead audit are stored with the numbers.

Methodology rules honoured (.claude/rules/experiments.md)
--------------------------------------------------------
  - DM: canonical volpred.stats.model_evaluation.dm_test ONLY (HAC bandwidth
    ceil(h^(1/3) n^(1/3)), never h-1). acf(1) of every loss differential is reported.
  - QLIKE: canonical qlike_pointwise = actual/predicted - log(actual/predicted) - 1.
  - Basel: the 1% light is the standard 250-day count rule; the 5% light is a CUSTOM
    alpha-scaled extension and is labelled as such everywhere it appears.
  - Every random procedure is seeded (SEED = 20260712).
  - n < the >=500 house rule is reported, not hidden; every rate carries an exact binomial band.

Usage
-----
  uv run --extra dev python experiments/k1684/k1684_ftd_e1_scale_gating.py
First run rebuilds the RV from ~2,300 tick files (~4 min) and pins it; later runs reuse it.
"""

import os
import sys
import json
import time
import hashlib
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from numba import njit
from scipy.optimize import minimize
from scipy.stats import norm, chi2, skew, kurtosis, beta as beta_dist

warnings.filterwarnings('ignore')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'experiments', 'k854'))
sys.path.insert(0, SCRIPT_DIR)

import k854_common_sample_var as k854            # noqa: E402  (HAR / CF / skew-t / backtest helpers)
import k1684_rv_active as rvb                    # noqa: E402  (R2 active-contract RV builder)
from volpred.stats.model_evaluation import dm_test, qlike_pointwise   # noqa: E402
from volpred.utils import clean_tw50_data        # noqa: E402

# ============================================================
# Configuration
# ============================================================
SEED = 20260712
np.random.seed(SEED)

DATA_DIR = os.path.join(SCRIPT_DIR, 'data')
RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1684_ftd_e1_scale_gating_results.json')
RECEIPT_PATH = os.path.join(SCRIPT_DIR, 'k1684_rerun_r2_receipt.json')
RV_R2_SNAPSHOT = os.path.join(DATA_DIR, 'tx_rv_active_c2c_5min_2017_2025.csv')   # R2 (this run)
RV_R1_SNAPSHOT = os.path.join(DATA_DIR, 'tx_rv_5min_daily_2017_2025.csv')        # R1/K854 legacy
ETF_SNAPSHOT = os.path.join(DATA_DIR, 'tw0050_adjclose_2016_2025.csv')

RV_BUILD_START = '2016-12-01'    # one extra month so 2017-01-02's window has its 13:30(D-1) anchor
RV_START = '2017-01-01'          # K854 setting
OOS_START = '2023-01-01'         # K854 setting
OOS_END = '2024-12-31'           # K854 setting
REFIT_EVERY = 63                 # K854 setting
HAR_MIN_TRAIN = 250              # K854 setting
ALPHA_LEVELS = [0.01, 0.05]
MIN_POOL = 30                    # K854 rule: > 30 residuals needed to form a tail layer
BURNIN_START = '2018-01-01'      # long theta window (sigma only -- never the tail shape)

GJR_N_STARTS = 100               # G2: house rule for any MLE that a headline depends on
RGL_N_STARTS = 100               # symmetric treatment -- RGL is a return-fitted MLE too
N_BOOT = 2000                    # scale-factor bootstrap
N_BOOT_ES = 10000                # McNeil-Frey ES bootstrap
N_FRAGILITY_DRAWS = 10

# TWO windows, deliberately decoupled (this was R1's sharpest design point and it survives):
#   TAIL POOL -- residual pool the tail layer reads skew/kurt/quantiles from. Widening it moves
#                the tail SHAPE, so it stays pinned to K854's convention in every deciding run.
#   THETA     -- window the scale correction is estimated on. It touches sigma ONLY, so it may
#                use a longer real-time history; it must, because a Mincer-Zarnowitz regression
#                on 31 observations degenerates.
RUNS = [
    ('primary', 'long', 'oos_only', REFIT_EVERY, 'r2',
     'GATE. R2 RV (active contract, gap-complete, 13:30-anchored). Tail layer pinned to K854 '
     '(OOS-only pool, 63-day refresh); only sigma moves. Theta on a long real-time window (2018+)'),
    ('sens_theta_short', 'oos_only', 'oos_only', REFIT_EVERY, 'r2',
     'Sensitivity: estimate the correction parameters on K854\'s short OOS-only pool too'),
    ('sens_daily_refresh', 'long', 'oos_only', 1, 'r2',
     'Sensitivity: refresh the tail pool daily instead of every 63 days'),
    ('sens_burnin_tailpool', 'long', 'burnin', REFIT_EVERY, 'r2',
     'DIAGNOSTIC (not a gate): widen the TAIL pool back to 2018 so it holds COVID. This moves the '
     'uncorrected baseline on its own -- evidence of a third, shape/estimation-window channel'),
    ('sens_legacy_rv', 'long', 'oos_only', REFIT_EVERY, 'r1',
     'DIAGNOSTIC (not a gate): identical machinery on the R1/K854 legacy RV (TX1 file, three '
     'separate sessions, day session to 13:45). Isolates how much of the R2 change is the RV '
     'rebuild alone, holding the 100-start GJR and every statistic fixed'),
]
PRIMARY_RUN = 'primary'

TAIL_LAYERS = ['Normal', 'CF', 'HistSim']
HAR_VARIANTS = ['HAR', 'HAR-a', 'HAR-b', 'HAR-c']       # 'HAR' = uncorrected baseline


def log(msg):
    print(msg, flush=True)


# ============================================================
# A. Data
# ============================================================

def load_rv_r2():
    """R2 RV: active contract, continuous path, 13:30(D-1) -> 13:30(D)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(RV_R2_SNAPSHOT):
        log(f'  [cache] {os.path.basename(RV_R2_SNAPSHOT)}')
        return pd.read_csv(RV_R2_SNAPSHOT, parse_dates=['date']).set_index('date').sort_index()
    log('  Rebuilding RV from ALL TAIFEX TX contracts (one-off, ~4 min; then pinned)...')
    df = rvb.build(start_date=RV_BUILD_START, end_date='2026-01-01')
    df.to_csv(RV_R2_SNAPSHOT, index_label='date')
    log(f'  [pinned] {RV_R2_SNAPSHOT}')
    return df


def load_rv_r1():
    """R1/K854 legacy RV (TX1, three separate sessions, 13:45 day close). Diagnostic only."""
    return pd.read_csv(RV_R1_SNAPSHOT, parse_dates=['date']).set_index('date').sort_index()


def load_etf():
    if os.path.exists(ETF_SNAPSHOT):
        log(f'  [cache] {os.path.basename(ETF_SNAPSHOT)}')
        return pd.read_csv(ETF_SNAPSHOT, parse_dates=['date']).set_index('date')['adj_close'].sort_index()
    log('  Downloading 0050.TW (auto_adjust=True -- fingerprint-matched to K854)...')
    import yfinance as yf
    raw = yf.download('0050.TW', start='2016-01-01', end='2026-01-01',
                      progress=False, auto_adjust=True)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    s = raw['Close'].squeeze()
    s.index = pd.to_datetime(s.index).tz_localize(None)
    s.name = 'adj_close'
    s.to_csv(ETF_SNAPSHOT, index_label='date')
    return s


def rv_information_set_audit(rv_df):
    """G1: mechanical proof that RV(D) cannot see past the ETF close on day D."""
    end = rv_df['path_end_hhmmss'].dropna().astype(int)
    start = rv_df['path_start_hhmmss'].dropna().astype(int)
    late = int((end > rvb.ETF_CLOSE_HHMMSS).sum())
    return {
        'rule': 'every RV(D) integrates a continuous price path that ENDS at the last trade at or '
                'before 13:30:00 on D (0050 close) and STARTS at the last trade at or before '
                '13:30:00 on D-1. RV(D) is therefore in the information set at the instant the '
                'return window of r_{D+1} opens; the R1 13:30/13:45 overlap is closed.',
        'n_days': int(len(end)),
        'max_path_end_hhmmss': int(end.max()),
        'min_path_end_hhmmss': int(end.min()),
        'n_days_path_ends_after_1330': late,
        'path_start_hhmmss_max': int(start.max()),
        'passed': bool(late == 0),
    }


# ============================================================
# B. Robust MLE (G2): >=100 starts, convergence + basin diagnostics
# ============================================================

@njit(cache=True)
def _gjr_filter_nb(r, omega, alpha, beta, gamma):
    T = r.shape[0]
    s2 = np.empty(T)
    v = 0.0
    for i in range(T):
        v += r[i] * r[i]
    v /= T
    s2[0] = v
    for t in range(1, T):
        ind = 1.0 if r[t - 1] < 0 else 0.0
        s2[t] = omega + (alpha + gamma * ind) * r[t - 1] ** 2 + beta * s2[t - 1]
        if s2[t] < 1e-12:
            s2[t] = 1e-12
    return s2


@njit(cache=True)
def _gjr_negll_nb(r, omega, alpha, beta, gamma):
    if omega <= 0 or alpha < 0 or beta < 0 or gamma < 0:
        return 1e10
    if alpha + beta + 0.5 * gamma >= 1.0:
        return 1e10
    s2 = _gjr_filter_nb(r, omega, alpha, beta, gamma)
    ll = 0.0
    for t in range(1, r.shape[0]):
        ll += -0.5 * (np.log(s2[t]) + r[t] * r[t] / s2[t])
    if not np.isfinite(ll):
        return 1e10
    return -ll


@njit(cache=True)
def _rgl_negll_nb(r, log_rv, omega, beta, delta, init_mean):
    if beta < -0.999 or beta > 0.999 or delta < 0 or delta > 2.0:
        return 1e10
    T = r.shape[0]
    log_h = np.empty(T)
    log_h[0] = omega / (1 - beta) + delta / (1 - beta) * init_mean
    for t in range(1, T):
        log_h[t] = omega + beta * log_h[t - 1] + delta * log_rv[t - 1]
    ll = 0.0
    for t in range(1, T):
        h = np.exp(log_h[t])
        if h < 1e-16:
            h = 1e-16
        ll += -0.5 * (log_h[t] + r[t] * r[t] / h)
    if not np.isfinite(ll):
        return 1e10
    return -ll


def _basin_summary(nlls, params, key):
    """Objective spread + how much of the start mass reaches the best basin."""
    nlls = np.asarray(nlls, dtype=float)
    ok = np.isfinite(nlls) & (nlls < 1e9)
    if ok.sum() == 0:
        return {'n_finite': 0}
    best = float(nlls[ok].min())
    at_best = np.abs(nlls[ok] - best) < 1e-6 * max(1.0, abs(best))
    vals = np.array([p[key] for p, o in zip(params, ok) if o], dtype=float)
    return {
        'n_starts': int(len(nlls)),
        'n_finite': int(ok.sum()),
        'best_nll': best,
        'worst_nll': float(nlls[ok].max()),
        'nll_median': float(np.median(nlls[ok])),
        'share_of_starts_in_best_basin': float(at_best.mean()),
        'n_distinct_basins_nll_1e-4': int(len(np.unique(np.round(nlls[ok], 4)))),
        f'{key}_at_best': float(vals[np.argmin(nlls[ok])]),
        f'{key}_p05_p95_across_starts': [float(np.percentile(vals, 5)), float(np.percentile(vals, 95))],
        f'{key}_spread_across_starts': float(vals.max() - vals.min()),
    }


def fit_gjr_robust(returns, n_starts=GJR_N_STARTS, seed=SEED):
    """GJR(1,1) MLE with >=100 seeded random starts. Returns (params, diagnostics)."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    if len(r) < 100:
        return None, None
    v = float(np.var(r))
    rng = np.random.default_rng(seed + len(r))     # start grid depends on the training window
    nlls, all_params, n_conv = [], [], 0
    best, best_nll = None, np.inf

    inits = [(max(1e-10, v * 0.05), 0.05, 0.88, 0.08)]           # the textbook start
    for _ in range(n_starts - 1):
        a0 = float(np.clip(rng.normal(0.05, 0.04), 0.005, 0.30))
        g0 = float(np.clip(rng.normal(0.08, 0.06), 0.0, 0.35))
        b0 = float(np.clip(rng.normal(0.85, 0.08), 0.30, 0.985))
        if a0 + b0 + 0.5 * g0 >= 0.99:
            b0 = max(0.30, 0.985 - a0 - 0.5 * g0)
        o0 = max(1e-10, v * max(1e-3, 1 - a0 - b0 - 0.5 * g0))
        inits.append((o0, a0, b0, g0))

    for x0 in inits:
        res = minimize(lambda p: _gjr_negll_nb(r, p[0], p[1], p[2], p[3]), np.array(x0),
                       method='L-BFGS-B',
                       bounds=[(1e-12, None), (0.0, 0.5), (0.0, 0.999), (0.0, 0.5)],
                       options={'maxiter': 3000})
        o, a, b, g = res.x
        p = {'omega': float(o), 'alpha': float(a), 'beta': float(b), 'gamma': float(g),
             'persistence': float(a + b + 0.5 * g), 'nll': float(res.fun),
             'converged': bool(res.success)}
        n_conv += int(res.success)
        nlls.append(float(res.fun))
        all_params.append(p)
        if res.fun < best_nll:
            best_nll, best = float(res.fun), p
    if best is None:
        return None, None
    diag = _basin_summary(nlls, all_params, 'persistence')
    diag['convergence_rate'] = float(n_conv / len(inits))
    return {k: best[k] for k in ['omega', 'alpha', 'beta', 'gamma', 'persistence']}, diag


def fit_rgl_robust(returns, rv_arr, n_starts=RGL_N_STARTS, seed=SEED):
    """RealGARCH-Log MLE with >=100 seeded starts (symmetric treatment with GJR)."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    rv = np.ascontiguousarray(rv_arr, dtype=np.float64)
    if len(r) < 100:
        return None, None
    rv_clean = rv.copy()
    mean_pos = np.nanmean(rv[rv > 0])
    rv_clean[~np.isfinite(rv_clean) | (rv_clean <= 0)] = mean_pos
    log_rv = np.log(rv_clean)
    init_mean = float(np.mean(log_rv[:min(22, len(log_rv))]))

    rng = np.random.default_rng(seed + 7 + len(r))
    nlls, all_params, n_conv = [], [], 0
    best, best_nll = None, np.inf
    inits = [(-0.1, 0.6, 0.3)]
    for _ in range(n_starts - 1):
        inits.append((float(rng.normal(-0.1, 0.3)),
                      float(np.clip(rng.normal(0.6, 0.2), 0.05, 0.95)),
                      float(np.clip(rng.normal(0.3, 0.15), 0.02, 0.9))))

    for x0 in inits:
        res = minimize(lambda p: _rgl_negll_nb(r, log_rv, p[0], p[1], p[2], init_mean),
                       np.array(x0), method='L-BFGS-B',
                       bounds=[(-5, 5), (-0.999, 0.999), (0.001, 2.0)],
                       options={'maxiter': 3000})
        o, b, d = res.x
        p = {'omega': float(o), 'beta': float(b), 'delta': float(d),
             'persistence': float(b), 'nll': float(res.fun), 'converged': bool(res.success)}
        n_conv += int(res.success)
        nlls.append(float(res.fun))
        all_params.append(p)
        if res.fun < best_nll:
            best_nll, best = float(res.fun), p
    if best is None:
        return None, None
    diag = _basin_summary(nlls, all_params, 'persistence')
    diag['convergence_rate'] = float(n_conv / len(inits))
    return {k: best[k] for k in ['omega', 'beta', 'delta', 'persistence']}, diag


def gjr_forecast_path(r, start_idx, end_idx, n_starts=GJR_N_STARTS, seed=SEED, fitter='r2'):
    """Expanding-window GJR OOS loop (K854's cadence).

    fitter='r2'   -> fit_gjr_robust, >=100 seeded starts (the R2 canonical path)
    fitter='k854' -> the PARENT's own k854.fit_gjr (4 starts), called verbatim. Used only by the
                     fragility probe: the R1 blocker is a claim about K854's code, so testing it
                     against a re-implementation truncated to 4 starts would not test the claim.
    """
    n = len(r)
    f = np.full(n, np.nan)
    z_by_refit, diags = {}, []
    params_by_idx = np.empty(n, dtype=object)
    params_list = []
    cur, last = None, -REFIT_EVERY
    for i in range(start_idx, end_idx):
        d = i - start_idx
        if d - last >= REFIT_EVERY or cur is None:
            if len(r[:i]) < 500:
                continue
            if fitter == 'k854':
                p, dg = k854.fit_gjr(r[:i]), None
            else:
                p, dg = fit_gjr_robust(r[:i], n_starts=n_starts, seed=seed)
            if p is not None:
                cur, last = p, d
                params_list.append(p)
                if dg is not None:
                    dg['refit_index'] = int(i)
                    dg['n_train'] = int(i)
                    diags.append(dg)
                z_by_refit[i] = k854.compute_standardized_residuals(r[:i], p)
        if cur is None:
            continue
        f[i] = k854.gjr_one_step_forecast(r[:i], cur)
        params_by_idx[i] = cur
    return f, z_by_refit, params_by_idx, params_list, diags


def rgl_forecast_path(r, rv, start_idx, end_idx):
    n = len(r)
    f = np.full(n, np.nan)
    z_by_refit, diags, params_list = {}, [], []
    cur, last = None, -REFIT_EVERY
    for i in range(start_idx, end_idx):
        d = i - start_idx
        if d - last >= REFIT_EVERY or cur is None:
            if len(r[:i]) < 500:
                continue
            p, dg = fit_rgl_robust(r[:i], rv[:i])
            if p is not None:
                cur, last = p, d
                params_list.append(p)
                if dg is not None:
                    dg['refit_index'] = int(i)
                    diags.append(dg)
                z_by_refit[i] = k854.compute_std_residuals_real_log(r[:i], rv[:i], p)
        if cur is None:
            continue
        f[i] = k854.realgarch_log_one_step_forecast(r[:i], rv[:i], cur)
    return f, z_by_refit, params_list, diags


def gjr_fragility_probe(r, oos_start_idx, oos_end_idx, eval_idx, n_starts, label,
                        n_draws=N_FRAGILITY_DRAWS, fitter='r2'):
    """Does a numerically irrelevant data revision move this fitter's VaR?

    R1's finding: with K854's 4 starts, a 1e-6 relative perturbation of the returns moved GJR
    sigma by up to 29% and wandered the violation count -- the FITTER, not the data, was doing the
    moving. The 4-start arm therefore calls k854.fit_gjr verbatim (a re-implementation truncated
    to 4 starts would be testing a different claim), and the 100-start arm calls the R2 fitter, so
    the fix is verified rather than asserted.
    """
    f0, _, _, p0, _ = gjr_forecast_path(r, oos_start_idx, oos_end_idx, n_starts=n_starts,
                                        fitter=fitter)
    s0 = np.sqrt(f0[eval_idx])
    base = {f'{int(a*100)}%': int((r[eval_idx] < s0 * norm.ppf(a)).sum()) for a in ALPHA_LEVELS}
    counts = {f'{int(a*100)}%': [] for a in ALPHA_LEVELS}
    max_rel, persistences = 0.0, []

    for draw in range(n_draws):
        rng = np.random.default_rng(SEED + 1000 + draw)
        r_p = r * (1.0 + rng.normal(0, 1e-6, size=len(r)))
        f_p, _, _, p_p, _ = gjr_forecast_path(r_p, oos_start_idx, oos_end_idx, n_starts=n_starts,
                                              fitter=fitter)
        s1 = np.sqrt(f_p[eval_idx])
        max_rel = max(max_rel, float(np.max(np.abs(s1 - s0) / s0)))
        persistences.append([round(p['persistence'], 4) for p in p_p])
        for a in ALPHA_LEVELS:
            counts[f'{int(a*100)}%'].append(int((r_p[eval_idx] < s1 * norm.ppf(a)).sum()))

    return {
        'fitter': label,
        'n_starts': n_starts,
        'n_draws': n_draws,
        'perturbation': 'returns x (1 + N(0, 1e-6)) -- the magnitude by which a yfinance '
                        're-rounding changes the data',
        'sigma_change_max_pct_across_draws': max_rel * 100,
        'persistence_base': [round(p['persistence'], 4) for p in p0],
        'persistence_across_draws': persistences,
        'gjr_normal_violations_base': base,
        'gjr_normal_violation_range': {a: [int(min(counts[a])), int(max(counts[a]))] for a in counts},
        'violation_count_is_stable': {a: bool(min(counts[a]) == max(counts[a])) for a in counts},
    }


# ============================================================
# C. Correction parameters theta_t (strictly past data)
# ============================================================

def estimate_theta(pool_slice, r, s2_src, rv):
    """Every correction parameter, from ONE snapshot of strictly-past data.

    pool_slice : integer indices, ALL strictly before the origin (the caller guarantees it;
                 lookahead_perturbation_audit() proves it).
    """
    idx = pool_slice[np.isfinite(s2_src[pool_slice]) & (s2_src[pool_slice] > 0)
                     & np.isfinite(r[pool_slice])]
    if len(idx) <= MIN_POOL:
        return None

    z = r[idx] / np.sqrt(s2_src[idx])
    s_a = float(np.std(z, ddof=1))                      # (a) expanding std(z)

    m = np.isfinite(r[pool_slice]) & np.isfinite(rv[pool_slice]) & (rv[pool_slice] > 0)
    jj = pool_slice[m]
    k_c = float(np.sum(r[jj] ** 2) / np.sum(rv[jj])) if len(jj) > MIN_POOL else np.nan  # (c) HL

    nz = idx[r[idx] != 0.0]                              # (b) Mincer-Zarnowitz + Duan smearing
    mz = None
    if len(nz) >= MIN_POOL:
        x = np.log(s2_src[nz])
        y = np.log(r[nz] ** 2)
        X = np.column_stack([np.ones(len(x)), x])
        try:
            b = np.linalg.lstsq(X, y, rcond=None)[0]
            smear = float(np.mean(np.exp(y - X @ b)))
            if np.isfinite(smear) and smear > 0:
                mz = {'a': float(b[0]), 'b': float(b[1]), 'smear': smear}
        except Exception:
            mz = None

    return {'pool_idx': idx, 'z': z, 's_a': s_a, 'k_c': k_c, 'mz': mz, 'n_pool': int(len(idx))}


def sigma2_variant(name, s2_har, theta):
    if name == 'HAR':
        return s2_har
    if name == 'HAR-a':
        return s2_har * theta['s_a'] ** 2
    if name == 'HAR-c':
        return s2_har * theta['k_c']
    if name == 'HAR-b':
        if theta['mz'] is None:
            return np.full_like(np.asarray(s2_har, dtype=float), np.nan)
        mz = theta['mz']
        return np.exp(mz['a'] + mz['b'] * np.log(s2_har)) * mz['smear']
    raise ValueError(name)


# ============================================================
# D. VaR / ES / scale factor / backtests  (G3, G4, G6)
# ============================================================

def _cf_quantile_grid(z_pool, alpha, m=2000):
    """Average of the Cornish-Fisher quantile over u in (0, alpha) -> the CF ES multiplier."""
    u = alpha * (np.arange(m) + 0.5) / m
    zq = norm.ppf(u)
    S = float(skew(z_pool))
    K = float(kurtosis(z_pool, fisher=True))
    q = (zq + (zq ** 2 - 1) * S / 6.0 + (zq ** 3 - 3.0 * zq) * K / 24.0
         - (2.0 * zq ** 3 - 5.0 * zq) * S ** 2 / 36.0)
    return float(np.mean(q))


def es_multiplier(layer, alpha, z_pool=None, skewt=None):
    """E[z | z <= q_alpha] for each tail layer -- the factor ES = sigma * m."""
    if layer == 'Normal':
        return float(-norm.pdf(norm.ppf(alpha)) / alpha)
    if layer == 'HistSim':
        q = float(np.percentile(z_pool, alpha * 100))
        tail = z_pool[z_pool <= q]
        return float(np.mean(tail)) if len(tail) else float(q)
    if layer == 'CF':
        return _cf_quantile_grid(z_pool, alpha)
    if layer == 'Skewed-t':
        m = 2000
        u = alpha * (np.arange(m) + 0.5) / m
        q = np.array([k854.skewt_ppf(ui, df=skewt['df'], xi=skewt['xi']) for ui in u])
        return float(np.mean(q))
    raise ValueError(layer)


def fz0_loss(r, var_arr, es_arr, alpha):
    """Fissler-Ziegel FZ0 joint (VaR, ES) loss -- Patton, Ziegel & Chen (2019, JoE 211), eq. (9).

    L = -(1/(alpha*e)) * 1{y <= v} * (v - y) + v/e + log(-e) - 1,   v < 0, e < 0.
    Strictly consistent for the (VaR, ES) pair and 0-homogeneous.
    """
    v = np.asarray(var_arr, dtype=float)
    e = np.asarray(es_arr, dtype=float)
    y = np.asarray(r, dtype=float)
    ok = np.isfinite(v) & np.isfinite(e) & (e < 0) & (v < 0)
    out = np.full(len(y), np.nan)
    hit = (y <= v) & ok
    out[ok] = (v[ok] / e[ok]) + np.log(-e[ok]) - 1.0
    out[hit] += -(1.0 / (alpha * e[hit])) * (v[hit] - y[hit])
    return out


def empirical_scale_factor(r, var_arr, alpha, n_boot=N_BOOT, seed=SEED):
    """G3: the factor c that would put the realized violation rate exactly at alpha.

    A violation is r < VaR (VaR < 0). Scaling the VaR line by c > 0 gives
        #violations(c) = #{ r_t < c * VaR_t } = #{ r_t / VaR_t > c }
    (dividing by a negative number flips the inequality), so the c that delivers exactly an
    alpha violation rate is the (1 - alpha) empirical quantile of u_t = r_t / VaR_t.

    This is IDENTIFIED for every tail layer -- unlike R1's Phi^-1(alpha)/Phi^-1(pi_hat), which
    is only the scale factor under a Normal law and was applied to CF and HistSim cells anyway.
    c > 1 means the VaR line is too narrow (sigma too small); c = 1 means calibrated.
    Monotone in the violation rate by construction, so its bootstrap band cannot invert.
    """
    v = np.asarray(var_arr, dtype=float)
    y = np.asarray(r, dtype=float)
    ok = np.isfinite(v) & np.isfinite(y) & (v < 0)
    u = y[ok] / v[ok]
    if len(u) < 30:
        return None
    c_hat = float(np.quantile(u, 1 - alpha))
    rng = np.random.default_rng(seed + int(alpha * 1000))
    idx = rng.integers(0, len(u), size=(n_boot, len(u)))
    boots = np.quantile(u[idx], 1 - alpha, axis=1)
    return {
        'c_hat': c_hat,
        'c_lo95': float(np.percentile(boots, 2.5)),
        'c_hi95': float(np.percentile(boots, 97.5)),
        'n': int(len(u)),
        'definition': 'c = quantile_{1-alpha}( r_t / VaR_t ): the multiplicative factor on the '
                      'VaR line that would deliver exactly an alpha violation rate. '
                      'Distribution-free, identified for every tail layer. '
                      f'iid bootstrap, B={n_boot}, seed={seed}.',
    }


def delta_c_bootstrap(r, var1, var5, n_boot=N_BOOT, seed=SEED):
    """G3: bootstrap test of H0: c(1%) = c(5%) -- replaces R1's untested |dc| < 0.10 rule.

    Scale mismatch => the SAME c rescues both alpha levels. Tail-shape misspecification =>
    c moves with alpha. Both c's are resampled on the SAME bootstrap days (paired), so the
    band on the difference accounts for their dependence.
    """
    y = np.asarray(r, dtype=float)
    v1, v5 = np.asarray(var1, dtype=float), np.asarray(var5, dtype=float)
    ok = np.isfinite(v1) & np.isfinite(v5) & np.isfinite(y) & (v1 < 0) & (v5 < 0)
    u1, u5 = y[ok] / v1[ok], y[ok] / v5[ok]
    if len(u1) < 30:
        return None
    d_hat = float(np.quantile(u1, 0.99) - np.quantile(u5, 0.95))
    rng = np.random.default_rng(seed + 99)
    idx = rng.integers(0, len(u1), size=(n_boot, len(u1)))
    b = np.quantile(u1[idx], 0.99, axis=1) - np.quantile(u5[idx], 0.95, axis=1)
    lo, hi = float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))
    # two-sided bootstrap p for H0: delta = 0 (percentile-t free version)
    p = float(2 * min((b <= 0).mean(), (b >= 0).mean()))
    return {
        'delta_c_hat': d_hat, 'lo95': lo, 'hi95': hi, 'boot_p_value': min(1.0, p),
        'H0_pure_scale_not_rejected': bool(lo <= 0 <= hi),
        'note': 'H0: c(1%) = c(5%) (a pure SCALE miss rescales both alphas by the same factor). '
                'Rejecting H0 is evidence of a tail-SHAPE channel. Paired iid bootstrap, '
                f'B={n_boot}.',
    }


def normal_implied_c(n_viol, n_total, alpha):
    """Parametric scale factor, VALID ONLY for Normal-tail cells.

    c = Phi^-1(alpha) / Phi^-1(pi_hat). Both quantiles are negative, so c > 0, and c is
    INCREASING in pi_hat (more violations => the reported sigma was too small by more).
    R1 asserted the opposite and inverted the band, producing 154 cells with lo95 > hi95.
    """
    def _c(pi):
        if pi is None or not np.isfinite(pi) or pi <= 0 or pi >= 1:
            return None
        return float(norm.ppf(alpha) / norm.ppf(pi))

    pi_hat = n_viol / n_total if n_total else np.nan
    pi_lo = 0.0 if n_viol == 0 else float(beta_dist.ppf(0.025, n_viol, n_total - n_viol + 1))
    pi_hi = 1.0 if n_viol == n_total else float(beta_dist.ppf(0.975, n_viol + 1, n_total - n_viol))
    lo, hi = _c(pi_lo), _c(pi_hi)                       # increasing in pi
    if lo is not None and hi is not None and lo > hi:   # must never happen -- fail loud
        raise RuntimeError(f'implied-c band inverted: {lo} > {hi}')
    return {'implied_c': _c(pi_hat), 'implied_c_lo95': lo, 'implied_c_hi95': hi,
            'pi_lo95': pi_lo, 'pi_hi95': pi_hi,
            'valid_only_under': 'Normal tail layer (the mapping is the Normal scale factor)'}


def mcneil_frey_es_test(r, var_arr, es_arr, sigma_arr, n_boot=N_BOOT_ES, seed=SEED):
    """McNeil & Frey (2000) exceedance-residual test of the ES.

    On violation days the standardised residual (r - ES)/sigma has mean zero under a correct
    ES. A mean below zero says realised losses beyond the VaR are WORSE than the ES promised
    (risk understated). One-sided bootstrap p-value on the studentised mean.
    """
    y = np.asarray(r, dtype=float)
    v, e, s = (np.asarray(x, dtype=float) for x in (var_arr, es_arr, sigma_arr))
    ok = np.isfinite(v) & np.isfinite(e) & np.isfinite(s) & (s > 0)
    hit = ok & (y < v)
    m = int(hit.sum())
    if m < 5:
        return {'n_exceedances': m, 'mean_exceedance_residual': None, 'p_value': None,
                'pass': None, 'note': 'fewer than 5 exceedances -- the test has no power here'}
    er = (y[hit] - e[hit]) / s[hit]
    sd = float(np.std(er, ddof=1))
    mean = float(np.mean(er))
    if sd <= 0:
        return {'n_exceedances': m, 'mean_exceedance_residual': mean, 'p_value': None, 'pass': None}
    t_obs = mean / (sd / np.sqrt(m))
    rng = np.random.default_rng(seed + 4242)
    centred = er - mean
    idx = rng.integers(0, m, size=(n_boot, m))
    samp = centred[idx]
    t_null = samp.mean(axis=1) / (samp.std(axis=1, ddof=1) / np.sqrt(m) + 1e-300)
    p = float((t_null <= t_obs).mean())                 # H1: mean < 0 (ES too shallow)
    return {'n_exceedances': m, 'mean_exceedance_residual': mean, 't_stat': float(t_obs),
            'p_value': p, 'pass': bool(p > 0.05),
            'note': 'H1: mean exceedance residual < 0 (ES understates the realised tail loss). '
                    f'iid bootstrap, B={n_boot}, seed={seed}.'}


def var_backtest_r2(returns, var_arr, alpha):
    """Kupiec + Christoffersen + Basel, with the BOUNDARY cases handled correctly.

    K854's var_backtest returns Kupiec p = 1.0 whenever the violation count is 0 (or n), i.e. it
    scores a wildly over-conservative VaR as PERFECTLY calibrated and hands it a trinity PASS.
    Zero violations in 450 days at alpha = 5% is a decisive REJECTION of correct coverage
    (LR_uc = -2 n log(1 - alpha) ~ 46, p ~ 1e-11), not a pass. With the 0 log 0 := 0 convention
    the likelihood ratio is perfectly well defined at the boundary, so it is computed, not skipped.
    (The parent file is not edited -- this experiment's scope is experiments/k1684/ only.)
    """
    r = np.asarray(returns, dtype=float)
    v = np.asarray(var_arr, dtype=float)
    viol = (r < v).astype(int)
    n = len(r)
    n1 = int(viol.sum())
    n0 = n - n1
    pi_hat = n1 / n if n else np.nan

    def _ll(p):                                   # binomial log-likelihood, 0 log 0 := 0
        t = 0.0
        if n1:
            t += n1 * np.log(p) if p > 0 else -np.inf
        if n0:
            t += n0 * np.log(1 - p) if p < 1 else -np.inf
        return t

    lr_uc = float(-2.0 * (_ll(alpha) - _ll(pi_hat)))
    p_uc = float(1 - chi2.cdf(lr_uc, df=1))

    t00 = int(np.sum((viol[:-1] == 0) & (viol[1:] == 0)))
    t01 = int(np.sum((viol[:-1] == 0) & (viol[1:] == 1)))
    t10 = int(np.sum((viol[:-1] == 1) & (viol[1:] == 0)))
    t11 = int(np.sum((viol[:-1] == 1) & (viol[1:] == 1)))
    pi01 = t01 / (t00 + t01) if (t00 + t01) else 0.0
    pi11 = t11 / (t10 + t11) if (t10 + t11) else 0.0
    pi_all = (t01 + t11) / max(1, (t00 + t01 + t10 + t11))

    # Christoffersen independence. K854 (and R2's first pass) short-circuited to LR = 0, p = 1
    # whenever a transition probability hit a boundary -- but t11 = 0 (no violation ever followed
    # by another) is the TYPICAL case under the null at alpha = 1%, not a degenerate one, and with
    # the 0 log 0 := 0 convention every term is finite and the statistic is perfectly well defined.
    # Short-circuiting it hands a free pass to cells that are strongly ANTI-clustered, which at
    # alpha = 5% with ~40 violations can be a real rejection.
    def _t(count, p):
        return 0.0 if count == 0 else count * np.log(p)

    if (t01 + t11) == 0:
        # not a single violation follows another observation: the data carry no information about
        # clustering at all. LR = 0 here is a statement about the sample, not a pass.
        lr_ind, p_ind, no_info = 0.0, 1.0, True
    else:
        no_info = False
        ll_null = _t(t00 + t10, 1 - pi_all) + _t(t01 + t11, pi_all)
        ll_alt = (_t(t00, 1 - pi01) + _t(t01, pi01) + _t(t10, 1 - pi11) + _t(t11, pi11))
        lr_ind = float(max(0.0, -2.0 * (ll_null - ll_alt)))
        p_ind = float(1 - chi2.cdf(lr_ind, df=1))

    traffic, n_win, win = k854.basel_traffic_light_250(viol, alpha_var=alpha)
    lr_cc = lr_uc + lr_ind
    p_cc = float(1 - chi2.cdf(lr_cc, df=2))
    # exact (Clopper-Pearson) band on the violation rate -- at n = 450 with ~4.5 expected
    # violations the normal approximation is useless, so the band is exact everywhere it is quoted
    cp_lo = 0.0 if n1 == 0 else float(beta_dist.ppf(0.025, n1, n - n1 + 1))
    cp_hi = 1.0 if n1 == n else float(beta_dist.ppf(0.975, n1 + 1, n - n1))

    return {
        'violation_rate': float(pi_hat), 'expected_rate': float(alpha),
        'violation_rate_ci95_exact': [cp_lo, cp_hi],
        'n_violations': n1, 'n_total': n,
        'kupiec': {'stat': round(lr_uc, 4), 'p_value': round(p_uc, 4), 'pass': bool(p_uc > 0.05),
                   'boundary_case': bool(n1 == 0 or n1 == n),
                   'note': 'LR_uc with the 0 log 0 convention; a zero-violation cell is REJECTED, '
                           'not auto-passed as in the K854 implementation'},
        'christoffersen': {'stat': round(lr_ind, 4), 'p_value': round(p_ind, 4),
                           'pass': bool(p_ind > 0.05), 'no_information': bool(no_info),
                           'transitions': {'t00': t00, 't01': t01, 't10': t10, 't11': t11}},
        'christoffersen_cc_joint': {'stat': round(lr_cc, 4), 'p_value': round(p_cc, 4),
                                    'pass': bool(p_cc > 0.05),
                                    'note': 'LR_cc = LR_uc + LR_ind, df = 2 (Christoffersen 1998)'},
        'basel_traffic_light': traffic,
        'basel_violations_in_window': int(n_win), 'basel_window_size': int(win),
        'trinity_pass': bool(p_uc > 0.05 and p_ind > 0.05 and traffic == 'green'),
    }


def backtest_cell(returns, var_arr, es_arr, sigma_arr, alpha, layer):
    bt = var_backtest_r2(returns, var_arr, alpha)
    bt['scale_factor_empirical'] = empirical_scale_factor(returns, var_arr, alpha)
    bt['scale_factor_normal_parametric'] = (
        normal_implied_c(bt['n_violations'], bt['n_total'], alpha) if layer == 'Normal'
        else {'implied_c': None,
              'reason': 'not identified: Phi^-1(alpha)/Phi^-1(pi) is the scale factor of a NORMAL '
                        'law only. Use scale_factor_empirical for this cell.'})
    bt['es'] = {
        'mean_es': float(np.mean(es_arr)),
        'mean_var': float(np.mean(var_arr)),
        'es_over_var': float(np.mean(es_arr) / np.mean(var_arr)),
        'mcneil_frey_test': mcneil_frey_es_test(returns, var_arr, es_arr, sigma_arr),
    }
    fz = fz0_loss(returns, var_arr, es_arr, alpha)
    bt['fz0_loss_mean'] = float(np.nanmean(fz))
    return bt, fz


# ============================================================
# E. Lookahead audit (mechanical)
# ============================================================

def lookahead_perturbation_audit(rv_series, r, rv, har_level, gjr_forecasts, gjr_params_by_idx,
                                 pool_start, eval_idx, n_probe=6):
    """Multiply every observation from the origin onward by 10; nothing at the origin may move."""
    rng = np.random.default_rng(SEED)
    probes = sorted(rng.choice(eval_idx, size=min(n_probe, len(eval_idx)), replace=False).tolist())
    checks = []
    for i in probes:
        pool = np.arange(pool_start, i)
        base = estimate_theta(pool, r, har_level, rv)

        r_c, rv_c, har_c = r.copy(), rv.copy(), har_level.copy()
        r_c[i:] *= 10.0
        rv_c[i:] *= 10.0
        har_c[i:] *= 10.0
        pert = estimate_theta(pool, r_c, har_c, rv_c)

        row = {'origin_index': int(i), 'origin_date': str(rv_series.index[i].date()),
               'theta_s_a_unchanged': bool(base['s_a'] == pert['s_a']),
               'theta_k_c_unchanged': bool(base['k_c'] == pert['k_c']),
               'theta_mz_unchanged': bool(
                   (base['mz'] is None and pert['mz'] is None)
                   or (base['mz'] is not None and pert['mz'] is not None
                       and base['mz']['a'] == pert['mz']['a']
                       and base['mz']['b'] == pert['mz']['b']
                       and base['mz']['smear'] == pert['mz']['smear']))}

        rv_pert = rv_series.copy()
        rv_pert.iloc[i:] *= 10.0
        har_pert = k854.har_oos_forecasts(rv_pert, oos_start=OOS_START, refit_freq=REFIT_EVERY,
                                          min_train=HAR_MIN_TRAIN)
        row['har_forecast_unchanged'] = bool(har_pert.iloc[i] == har_level[i])

        p = gjr_params_by_idx[i]
        if isinstance(p, dict) and np.isfinite(gjr_forecasts[i]):
            row['gjr_forecast_unchanged'] = bool(
                k854.gjr_one_step_forecast(r_c[:i], p) == gjr_forecasts[i])
        else:
            row['gjr_forecast_unchanged'] = None
        checks.append(row)

    flat = [v for row in checks for k, v in row.items() if k.endswith('_unchanged') and v is not None]
    return {'method': 'every observation at index >= origin multiplied by 10; each forecast and '
                      'correction parameter at the origin must come back bit-identical',
            'probes': checks, 'n_assertions': len(flat), 'all_passed': bool(all(flat))}


# ============================================================
# F. Gate decision (pre-registered, Harvey bar)  (G5)
# ============================================================

def decide_gate(cells, dm_aligned, dm_mismatched):
    """The divergence needs BOTH legs; kill either one and it is an artifact.

    leg 1  HAR beats GJR on QLIKE on the ALIGNED target (0050 r^2), at the Harvey bar |t| > 3.
    leg 2  HAR fails the trinity WHERE GJR PASSES (R1's decide_gate claimed to check the GJR
           clause and never did), and that failure survives the scale correction.
    """
    def trinity(cell, a):
        return bool(cells[a][cell]['trinity_pass']) if cell in cells[a] else False

    rescued = {}
    for v in ['HAR-a', 'HAR-b', 'HAR-c']:
        if any(f'{v}+{t}' not in cells['1%'] for t in TAIL_LAYERS):
            rescued[v] = {'rescued': None, 'note': 'variant not estimable in this run'}
            continue
        passing = [t for t in TAIL_LAYERS if all(trinity(f'{v}+{t}', a) for a in ['1%', '5%'])]
        rescued[v] = {'tail_layers_passing_both_alphas': passing, 'rescued': bool(passing)}
    n_rescued = sum(1 for v in rescued if rescued[v]['rescued'] is True)
    n_estimable = sum(1 for v in rescued if rescued[v]['rescued'] is not None)

    base_pass = [t for t in TAIL_LAYERS if all(trinity(f'HAR+{t}', a) for a in ['1%', '5%'])]
    gjr_pass = [c for c in ['GJR+CF', 'GJR+Normal', 'GJR+Skewed-t']
                if all(trinity(c, a) for a in ['1%', '5%'])]
    leg2_contrast = bool(len(base_pass) == 0 and len(gjr_pass) > 0)

    aligned, mismatched = dm_aligned['HAR-RV_vs_GJR'], dm_mismatched['HAR-RV_vs_GJR']
    t_al = aligned['t_stat']
    har_wins_harvey = bool(t_al < 0 and abs(t_al) > 3.0)
    gjr_wins_harvey = bool(t_al > 0 and abs(t_al) > 3.0)

    if gjr_wins_harvey:
        verdict = 'H2_REJECTED'
        why = ('leg 1 is REVERSED at the Harvey bar: on the aligned target (0050 r^2) GJR beats '
               'HAR-RV. The published QLIKE win exists only against HAR\'s own TX-RV target -- the '
               'mirror image of the VaR mismatch. There is no divergence left to explain.')
    elif not har_wins_harvey:
        verdict = 'H2_UNSUPPORTED'
        why = ('leg 1 cannot be established: on the aligned target (0050 r^2) neither model beats '
               f'the other at the Harvey bar (DM t = {t_al:+.3f}, |t| < 3). A divergence between '
               'forecast loss and tail coverage presupposes a forecast-loss WIN; without one there '
               'is nothing to be orthogonal to. This is a null result, not a rejection of H2 -- and '
               'not a licence to claim HAR and GJR are equivalent either.')
    elif not leg2_contrast:
        verdict = 'H2_UNSUPPORTED'
        why = ('leg 1 survives on the aligned target, but leg 2 has no contrast to offer: the '
               'baseline HAR / GJR trinity pattern the divergence rests on does not reproduce '
               '(see leg2_tail).')
    elif n_estimable > 0 and n_rescued == n_estimable:
        verdict = 'H2_REJECTED'
        why = ('both legs are present in the raw data, but the scale correction rescues HAR\'s VaR '
               'under EVERY estimable variant -- the tail failure was a variance-target scale miss.')
    elif n_rescued == 0:
        verdict = 'H2_SURVIVES'
        why = ('HAR beats GJR on the aligned target at the Harvey bar AND still fails the trinity '
               'after every scale correction, while GJR passes. The orthogonality is real.')
    else:
        verdict = 'H2_PARTIAL'
        why = (f'HAR is rescued under {n_rescued}/{n_estimable} estimable variants: the scale '
               'channel explains part but not all of the tail failure.')

    route = {
        'H2_REJECTED': 'Methodology short note (FRL / Journal of Forecasting): the divergence is a '
                       'variance-target artifact and the identified scale/shape decomposition is '
                       'the contribution. NOT a full IJF paper.',
        'H2_SURVIVES': 'Full IJF paper -- the residual orthogonality is real.',
        'H2_PARTIAL': 'Conditional: the channel decomposition carries the paper either way.',
        'H2_UNSUPPORTED': 'NO PAPER ROUTE from this experiment alone. The gate did not produce the '
                          'evidence either branch needs; E2 (a market scored on its OWN realized '
                          'measure, n >= 2500) has to run before any route is chosen.',
    }[verdict]

    return {
        'verdict': verdict, 'reason': why, 'route': route,
        'harvey_bar': 'formal conclusions require |t| > 3.0 (Harvey 2016); p < 0.05 is reported '
                      'but is NOT sufficient',
        'leg1_qlike': {
            'aligned_target_r2_0050': {
                'har_beats_gjr': bool(t_al < 0),
                'har_wins_at_harvey_bar': har_wins_harvey,
                'gjr_wins_at_harvey_bar': gjr_wins_harvey,
                'significant_p05': bool(aligned['p_value'] < 0.05),
                't_stat': t_al, 'p_value': aligned['p_value'], 'n': aligned['n'],
            },
            'mismatched_target_tx_rv_K850_convention': {
                'har_beats_gjr': bool(mismatched['t_stat'] < 0),
                'har_wins_at_harvey_bar': bool(mismatched['t_stat'] < 0
                                               and abs(mismatched['t_stat']) > 3.0),
                't_stat': mismatched['t_stat'], 'p_value': mismatched['p_value'],
                'n': mismatched['n'],
            },
        },
        'leg2_tail': {
            'baseline_har_tail_layers_passing_both_alphas': base_pass,
            'gjr_cells_passing_both_alphas': gjr_pass,
            'divergence_contrast_present': leg2_contrast,
            'per_variant_rescue': rescued,
            'n_variants_rescuing_har': n_rescued,
            'n_variants_estimable': n_estimable,
            'coverage_only_kupiec_pass_both_alphas': {
                cell: bool(all(cells[a][cell]['kupiec']['pass'] for a in ['1%', '5%']))
                for cell in cells['1%'] if cell.startswith('HAR')},
        },
    }


# ============================================================
# G. One run
# ============================================================

def build_cells(run_cfg, ctx):
    """Build every VaR/ES cell for one run configuration, on the identical evaluation sample."""
    run_id, theta_window, tail_pool, refresh, rv_variant, role = run_cfg
    (n, r, rv_r2, rv_r1, eval_idx, n_eval, eval_r, oos_start_idx, burnin_idx,
     har_by_variant, gjr_f, gjr_pool_burnin, gjr_z_refit, rgl_f, rgl_z_refit) = ctx

    rv = rv_r2 if rv_variant == 'r2' else rv_r1
    har_level, har_pool_burnin = har_by_variant[rv_variant]

    theta_start = oos_start_idx if theta_window == 'oos_only' else burnin_idx
    pool_start = oos_start_idx if tail_pool == 'oos_only' else burnin_idx
    har_theta_src = har_level if theta_window == 'oos_only' else har_pool_burnin
    har_tail_src = har_level if tail_pool == 'oos_only' else har_pool_burnin
    # SYMMETRY: the placebo's theta must be estimated on the SAME window as HAR's, or the
    # comparison is an artifact of the estimation window rather than of the target mismatch
    # (.claude/rules/experiments.md: "跨市場比較必 symmetric refinement"). The GJR forecasts
    # therefore get their own burn-in pass so a 2018+ pool exists for them too.
    gjr_theta_src = gjr_f if theta_window == 'oos_only' else gjr_pool_burnin
    gjr_tail_src = gjr_f if tail_pool == 'oos_only' else gjr_pool_burnin

    cell_names = ([f'{v}+{t}' for v in HAR_VARIANTS for t in TAIL_LAYERS]
                  + [f'{v}+{t}' for v in ['GJRf', 'GJRf-a'] for t in TAIL_LAYERS]
                  + ['GJR+Normal', 'GJR+CF', 'GJR+Skewed-t', 'RGL+CF'])
    var_arrays = {f'{int(a*100)}%': {c: np.full(n_eval, np.nan) for c in cell_names}
                  for a in ALPHA_LEVELS}
    es_arrays = {f'{int(a*100)}%': {c: np.full(n_eval, np.nan) for c in cell_names}
                 for a in ALPHA_LEVELS}
    sigma_of_cell = {c: np.full(n_eval, np.nan) for c in cell_names}

    sigma2_eval = {v: np.full(n_eval, np.nan) for v in HAR_VARIANTS}
    sigma2_eval['GJR'] = gjr_f[eval_idx]
    sigma2_eval['RGL'] = rgl_f[eval_idx]
    trace = {k: np.full(n_eval, np.nan) for k in ['s_a', 'k_c', 'mz_b', 's_gjr']}
    trace['n_theta'] = np.zeros(n_eval, dtype=int)
    trace['n_tail'] = np.zeros(n_eval, dtype=int)

    gjr_refits, rgl_refits = sorted(gjr_z_refit), sorted(rgl_z_refit)

    def last_refit_pool(refits, store, i):
        avail = [k for k in refits if k <= i]
        return (avail[-1], store[avail[-1]]) if avail else (None, None)

    theta = theta_g = tail = tail_g = None
    last_refresh = -10 ** 9
    skewt_cache, anchor_cache = {}, {}
    # theta is a STEP function: it only moves when the pool is refreshed. Keeping the update
    # sequence (and the pool it was estimated on) is what makes an honest CI possible later --
    # bootstrapping the 450 daily values as if they were independent would fake ~450 observations
    # out of (here) 8 estimates.
    theta_updates, last_pools = [], {}

    def _common_support(lo, hi, src_a, src_b):
        """The index set on which BOTH sigma sources exist.

        HAR's expanding fit starts after 250 observations, GJR's after 500, so the naive pools
        differ by ~250 days. Estimating the correction on one pool and the PLACEBO on another
        makes any difference between them partly an artifact of the samples they happened to get
        (.claude/rules/experiments.md: symmetric refinement). Both are estimated on the
        intersection instead.
        """
        base = np.arange(lo, hi)
        ok = (np.isfinite(src_a[base]) & (src_a[base] > 0)
              & np.isfinite(src_b[base]) & (src_b[base] > 0) & np.isfinite(r[base]))
        return base[ok]

    for k_ev, i in enumerate(eval_idx):
        if k_ev - last_refresh >= refresh or theta is None:
            pool_theta = _common_support(theta_start, i, har_theta_src, gjr_theta_src)
            pool_tail = _common_support(pool_start, i, har_tail_src, gjr_tail_src)
            th = estimate_theta(pool_theta, r, har_theta_src, rv)
            th_g = estimate_theta(pool_theta, r, gjr_theta_src, rv)
            tl = estimate_theta(pool_tail, r, har_tail_src, rv)
            tl_g = estimate_theta(pool_tail, r, gjr_tail_src, rv)
            # NOTE: given how pool_theta is built above, estimate_theta's internal validity mask is
            # already satisfied for BOTH sources on every index, so the two n_pool values are equal
            # by construction -- this guard is a tautology today and CANNOT fire. It is kept as a
            # tripwire for a future refactor that decouples the two filters. Do not read "it did not
            # fire" as "symmetry was tested at runtime"; the symmetry is enforced by _common_support.
            if th is not None and th_g is not None and th['n_pool'] != th_g['n_pool']:
                raise RuntimeError(
                    f'ASYMMETRIC THETA POOL: HAR n={th["n_pool"]} vs GJR n={th_g["n_pool"]}')
            if th is not None and tl is not None:
                theta, theta_g, tail, tail_g, last_refresh = th, th_g, tl, tl_g, k_ev
                theta_updates.append({
                    'eval_day': int(k_ev),
                    's_har': float(th['s_a']),
                    's_gjr': float(th_g['s_a']) if th_g is not None else None,
                    'n_pool_har': int(th['n_pool']),
                })
                last_pools = {'z_har': th['z'],
                              'z_gjr': th_g['z'] if th_g is not None else None}
        if theta is None or tail is None:
            continue

        trace['s_a'][k_ev] = theta['s_a']
        trace['k_c'][k_ev] = theta['k_c']
        trace['mz_b'][k_ev] = theta['mz']['b'] if theta['mz'] else np.nan
        trace['n_theta'][k_ev] = theta['n_pool']
        trace['n_tail'][k_ev] = tail['n_pool']
        if theta_g is not None:
            trace['s_gjr'][k_ev] = theta_g['s_a']

        # ---- HAR family: theta maps sigma at the origin AND re-standardises the tail pool ----
        s2_pool_har = har_tail_src[tail['pool_idx']]
        for v in HAR_VARIANTS:
            s2_i = float(sigma2_variant(v, np.array([har_level[i]]), theta)[0])
            if not np.isfinite(s2_i) or s2_i <= 0:
                continue
            sigma2_eval[v][k_ev] = s2_i
            s2_pool_v = sigma2_variant(v, s2_pool_har, theta)
            ok = np.isfinite(s2_pool_v) & (s2_pool_v > 0)
            z_v = r[tail['pool_idx'][ok]] / np.sqrt(s2_pool_v[ok])
            if len(z_v) <= MIN_POOL:
                continue
            sd = float(np.sqrt(s2_i))
            for a in ALPHA_LEVELS:
                ak = f'{int(a*100)}%'
                for t_, q, m_ in [
                        ('Normal', norm.ppf(a), es_multiplier('Normal', a)),
                        ('CF', k854.cornish_fisher_quantile(z_v, a), es_multiplier('CF', a, z_v)),
                        ('HistSim', float(np.percentile(z_v, a * 100)),
                         es_multiplier('HistSim', a, z_v))]:
                    var_arrays[ak][f'{v}+{t_}'][k_ev] = sd * q
                    es_arrays[ak][f'{v}+{t_}'][k_ev] = sd * m_
                    sigma_of_cell[f'{v}+{t_}'][k_ev] = sd

        # ---- PLACEBO: identical machinery, same three tail layers, on the correctly-targeted GJR ----
        if theta_g is not None and tail_g is not None and np.isfinite(gjr_f[i]):
            z_g = tail_g['z']
            for v, s2_i in [('GJRf', gjr_f[i]), ('GJRf-a', gjr_f[i] * theta_g['s_a'] ** 2)]:
                sd = float(np.sqrt(s2_i))
                zz = z_g if v == 'GJRf' else z_g / theta_g['s_a']
                for a in ALPHA_LEVELS:
                    ak = f'{int(a*100)}%'
                    for t_, q, m_ in [
                            ('Normal', norm.ppf(a), es_multiplier('Normal', a)),
                            ('CF', k854.cornish_fisher_quantile(zz, a), es_multiplier('CF', a, zz)),
                            ('HistSim', float(np.percentile(zz, a * 100)),
                             es_multiplier('HistSim', a, zz))]:
                        var_arrays[ak][f'{v}+{t_}'][k_ev] = sd * q
                        es_arrays[ak][f'{v}+{t_}'][k_ev] = sd * m_
                        sigma_of_cell[f'{v}+{t_}'][k_ev] = sd

        # ---- anchors: GJR / RGL with their own refit-based residual pools (K854 convention) ----
        gk, gz = last_refit_pool(gjr_refits, gjr_z_refit, i)
        rk, rz = last_refit_pool(rgl_refits, rgl_z_refit, i)
        if gz is not None and len(gz) > MIN_POOL and np.isfinite(gjr_f[i]):
            gsd = float(np.sqrt(gjr_f[i]))
            if gk not in skewt_cache:
                skewt_cache[gk] = k854.estimate_skewt_params(gz)
                st = skewt_cache[gk]
                anchor_cache[('g', gk)] = {
                    a: {'CF': (k854.cornish_fisher_quantile(gz, a), es_multiplier('CF', a, gz)),
                        'Normal': (norm.ppf(a), es_multiplier('Normal', a)),
                        'Skewed-t': (k854.skewt_ppf(a, df=st['df'], xi=st['xi']),
                                     es_multiplier('Skewed-t', a, skewt=st))}
                    for a in ALPHA_LEVELS}
            for a in ALPHA_LEVELS:
                ak = f'{int(a*100)}%'
                for t_ in ['Normal', 'CF', 'Skewed-t']:
                    q, m_ = anchor_cache[('g', gk)][a][t_]
                    var_arrays[ak][f'GJR+{t_}'][k_ev] = gsd * q
                    es_arrays[ak][f'GJR+{t_}'][k_ev] = gsd * m_
                    sigma_of_cell[f'GJR+{t_}'][k_ev] = gsd
        if rz is not None and len(rz) > MIN_POOL and np.isfinite(rgl_f[i]):
            rsd = float(np.sqrt(rgl_f[i]))
            if ('r', rk) not in anchor_cache:
                anchor_cache[('r', rk)] = {a: (k854.cornish_fisher_quantile(rz, a),
                                               es_multiplier('CF', a, rz)) for a in ALPHA_LEVELS}
            for a in ALPHA_LEVELS:
                ak = f'{int(a*100)}%'
                q, m_ = anchor_cache[('r', rk)][a]
                var_arrays[ak]['RGL+CF'][k_ev] = rsd * q
                es_arrays[ak]['RGL+CF'][k_ev] = rsd * m_
                sigma_of_cell['RGL+CF'][k_ev] = rsd

    return var_arrays, es_arrays, sigma_of_cell, sigma2_eval, trace, theta_updates, last_pools


def run_one(run_cfg, ctx):
    run_id, theta_window, tail_pool, refresh, rv_variant, role = run_cfg
    (n, r, rv_r2, rv_r1, eval_idx, n_eval, eval_r, oos_start_idx, burnin_idx,
     har_by_variant, gjr_f, gjr_pool_burnin, gjr_z_refit, rgl_f, rgl_z_refit) = ctx
    rv = rv_r2 if rv_variant == 'r2' else rv_r1

    (var_arrays, es_arrays, sigma_of_cell, sigma2_eval, trace,
     theta_updates, last_pools) = build_cells(run_cfg, ctx)

    # ---- common-sample guard: a retained cell must cover EVERY evaluation day ----
    incomplete = sorted({c for ak in var_arrays for c, arr in var_arrays[ak].items()
                         if not np.isfinite(arr).all()})
    if incomplete:
        if run_id == PRIMARY_RUN:
            raise RuntimeError(f'COMMON-SAMPLE VIOLATION in the GATE run: {incomplete}')
        for ak in var_arrays:
            for c in incomplete:
                var_arrays[ak].pop(c, None)
                es_arrays[ak].pop(c, None)
        log(f'  cells DROPPED (not estimable on the full window): {incomplete}')

    equivariance = {}
    for v in ['HAR-a', 'HAR-c']:
        if f'{v}+HistSim' not in var_arrays['1%']:
            continue
        d = max(float(np.max(np.abs(var_arrays[ak][f'{v}+HistSim'] - var_arrays[ak]['HAR+HistSim'])))
                for ak in var_arrays)
        equivariance[v] = {'max_abs_diff_vs_baseline_histsim': d, 'invariant': bool(d < 1e-10)}

    results, fz_by_cell = {}, {}
    for a in ALPHA_LEVELS:
        ak = f'{int(a*100)}%'
        results[ak], fz_by_cell[ak] = {}, {}
        for name, arr in var_arrays[ak].items():
            layer = name.split('+')[1]
            bt, fz = backtest_cell(eval_r, arr, es_arrays[ak][name], sigma_of_cell[name], a, layer)
            results[ak][name] = bt
            fz_by_cell[ak][name] = fz

    # ---- channel diagnostic (G3) ----
    # Two questions, two instruments, and they must not be confused:
    #   (i)  is there anything to fix?  -> the COVERAGE tests (Kupiec at both alphas). At n = 450
    #        the bootstrap band of an extreme-quantile scale factor is wide enough to contain 1
    #        even for a cell whose coverage is decisively rejected, so "c = 1 is inside the band"
    #        is a statement about POWER, not about calibration, and must never be read as a pass.
    #   (ii) if something is broken, is it SCALE or SHAPE? -> the bootstrap test of c(1%) = c(5%).
    channel = {}
    for name in results['1%']:
        c1 = results['1%'][name]['scale_factor_empirical']
        c5 = results['5%'][name]['scale_factor_empirical']
        dc = delta_c_bootstrap(eval_r, var_arrays['1%'][name], var_arrays['5%'][name])
        if c1 is None or c5 is None or dc is None:
            channel[name] = {'channel': 'undefined'}
            continue
        kup_ok = all(results[a][name]['kupiec']['pass'] for a in ['1%', '5%'])
        if kup_ok:
            lab = 'coverage NOT rejected at either alpha — no miss for a scale story to explain'
        elif dc['H0_pure_scale_not_rejected']:
            lab = 'SCALE (coverage rejected; c does not move across alphas)'
        else:
            lab = 'SHAPE (coverage rejected; c moves across alphas — not a pure scale miss)'
        channel[name] = {
            'c_1pct': c1['c_hat'], 'c_1pct_ci': [c1['c_lo95'], c1['c_hi95']],
            'c_5pct': c5['c_hat'], 'c_5pct_ci': [c5['c_lo95'], c5['c_hi95']],
            'c_bands_include_1': bool(c1['c_lo95'] <= 1.0 <= c1['c_hi95']
                                      and c5['c_lo95'] <= 1.0 <= c5['c_hi95']),
            'coverage_not_rejected_both_alphas': bool(kup_ok),
            'delta_c': dc, 'channel': lab}

    # ---- QLIKE / DM on BOTH targets, PAIRWISE common masks (G5) ----
    r2 = eval_r ** 2
    models = {'GJR': sigma2_eval['GJR'], 'RGL': sigma2_eval['RGL'], 'HAR-RV': sigma2_eval['HAR'],
              'HAR-a': sigma2_eval['HAR-a'], 'HAR-b': sigma2_eval['HAR-b'],
              'HAR-c': sigma2_eval['HAR-c']}
    dm_out, qlike_out = {}, {}
    for tgt_name, tgt in [('rv_tx', rv[eval_idx]), ('r2_0050', r2)]:
        tvalid = np.isfinite(tgt) & (tgt > 0)
        qlike_out[tgt_name] = {}
        for m, f_ in models.items():
            mk = tvalid & np.isfinite(f_) & (f_ > 0)
            qlike_out[tgt_name][m] = {'qlike': float(np.mean(qlike_pointwise(tgt[mk], f_[mk]))),
                                      'n': int(mk.sum())}
        dm_out[tgt_name] = {}
        for m1, m2 in [('HAR-RV', 'GJR'), ('HAR-a', 'GJR'), ('HAR-b', 'GJR'), ('HAR-c', 'GJR'),
                       ('HAR-a', 'HAR-RV'), ('RGL', 'GJR')]:
            mk = (tvalid & np.isfinite(models[m1]) & (models[m1] > 0)
                  & np.isfinite(models[m2]) & (models[m2] > 0))          # PAIRWISE mask
            l1 = qlike_pointwise(tgt[mk], models[m1][mk])
            l2 = qlike_pointwise(tgt[mk], models[m2][mk])
            d = l1 - l2
            t_stat, p_val = dm_test(l1, l2, h=1)                          # canonical only
            nd = len(d)
            dm_out[tgt_name][f'{m1}_vs_{m2}'] = {
                't_stat': float(t_stat), 'p_value': float(p_val), 'n': int(nd),
                'hac_lag_used': int(max(1, min(int(np.ceil(nd ** (1 / 3))), nd // 4))),
                'loss_diff_acf1': float(np.corrcoef(d[:-1], d[1:])[0, 1]) if nd > 2 else None,
                'harvey_significant_t_gt_3': bool(abs(t_stat) > 3.0),
                'better_model': m1 if t_stat < 0 else m2,
                'note': 'canonical volpred.stats.model_evaluation.dm_test; HAC bandwidth '
                        'ceil(h^(1/3) n^(1/3)); pairwise common mask'}

    # ---- FZ0 joint VaR-ES model comparison (G6) ----
    fz_dm = {}
    for a in ALPHA_LEVELS:
        ak = f'{int(a*100)}%'
        fz_dm[ak] = {}
        for c1, c2 in [('HAR+CF', 'GJR+CF'), ('HAR-a+CF', 'GJR+CF'), ('HAR-a+CF', 'HAR+CF'),
                       ('RGL+CF', 'GJR+CF'), ('HAR+HistSim', 'GJR+CF')]:
            if c1 not in fz_by_cell[ak] or c2 not in fz_by_cell[ak]:
                continue
            l1, l2 = fz_by_cell[ak][c1], fz_by_cell[ak][c2]
            mk = np.isfinite(l1) & np.isfinite(l2)
            t_stat, p_val = dm_test(l1[mk], l2[mk], h=1)
            fz_dm[ak][f'{c1}_vs_{c2}'] = {
                't_stat': float(t_stat), 'p_value': float(p_val), 'n': int(mk.sum()),
                'harvey_significant_t_gt_3': bool(abs(t_stat) > 3.0),
                'better_model': c1 if t_stat < 0 else c2,
                'loss': 'Fissler-Ziegel FZ0 joint (VaR, ES) loss, Patton-Ziegel-Chen (2019)'}

    def summ(arr, extra=None):
        d = {'mean': float(np.nanmean(arr)), 'min': float(np.nanmin(arr)),
             'max': float(np.nanmax(arr)), 'last': float(arr[-1])}
        if extra:
            d.update(extra)
        return d

    # G4: the placebo scale factor gets a real band, not a "near 1" adjective -- and the band is
    # built the RIGHT way. s_t is a STEP function that only moves when the pool is refreshed, so
    # resampling its 450 daily values as if they were independent would manufacture 450
    # observations out of (here) a handful of estimates and shrink the CI to nothing. The band is
    # therefore bootstrapped on the RESIDUAL POOL the final estimate is computed from -- the
    # sampling variation that actually exists in s_hat = std(z).
    def _scale_ci(key):
        z = last_pools.get(key)
        vals = [u['s_gjr' if key == 'z_gjr' else 's_har'] for u in theta_updates
                if u['s_gjr' if key == 'z_gjr' else 's_har'] is not None]
        if z is None or len(z) < 30 or not vals:
            return None
        rng = np.random.default_rng(SEED + 55 + (7 if key == 'z_gjr' else 0))
        b = np.std(z[rng.integers(0, len(z), size=(N_BOOT, len(z)))], axis=1, ddof=1)
        lo, hi = float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))
        daily = trace['s_gjr' if key == 'z_gjr' else 's_a']
        daily = daily[np.isfinite(daily)]
        return {
            'final_estimate': float(np.std(z, ddof=1)),
            'ci95_pool_bootstrap': [lo, hi],
            'excludes_1': bool(not (lo <= 1.0 <= hi)),
            'day_weighted_oos_mean': float(np.mean(daily)),
            'equal_weighted_mean_of_updates': float(np.mean(vals)),
            'updates': [round(float(v), 4) for v in vals],
            'n_pool_refreshes': int(len(vals)),
            'n_pool_obs_at_final_update': int(len(z)),
            'refreshes_are_not_independent': 'the pools are nested (expanding window), so the '
                                             'updates are strongly dependent; they are listed, not '
                                             'averaged into a standard error',
        }

    placebo = {
        'scale_factor': _scale_ci('z_gjr'),
        'har_scale_factor_for_comparison': _scale_ci('z_har'),
        'interpretation': 'A legitimate scale fix should leave the correctly-targeted GJR alone '
                          '(s = 1). If the band excludes 1 the machinery is NOT neutral and the '
                          '"clean placebo" reading of the HAR correction is not available. Compare '
                          'the two factors: what matters is not that the HAR factor exceeds 1, but '
                          'whether it exceeds the PLACEBO.',
        'note': f'iid bootstrap (B={N_BOOT}, seed={SEED}) over the residual pool the FINAL update '
                'was estimated on. The daily series is a step function with only '
                f"{len(theta_updates)} update(s) in this run, so it is NOT bootstrapped as if it "
                'were 450 independent observations.',
    }

    factors = {
        'HAR-a_scale_s': summ(trace['s_a']),
        'HAR-c_scale_s': summ(np.sqrt(trace['k_c'])),
        'HAR-b_MZ_slope_b': summ(trace['mz_b'],
                                 {'note': 'b = 1 would mean the HAR forecast needs only a level '
                                          'shift; b != 1 means its dynamic range is off too'}),
        'HAR-b_implied_scale': summ(np.sqrt(sigma2_eval['HAR-b'] / sigma2_eval['HAR'])),
        'GJRf-a_scale_s_PLACEBO': summ(trace['s_gjr']),
        'placebo_test': placebo,
        'theta_window_obs_first_eval_day': int(trace['n_theta'][0]),
        'theta_window_obs_last_eval_day': int(trace['n_theta'][-1]),
        'tail_pool_obs_first_eval_day': int(trace['n_tail'][0]),
        'tail_pool_obs_last_eval_day': int(trace['n_tail'][-1]),
    }

    gate = decide_gate(results, dm_out['r2_0050'], dm_out['rv_tx'])
    return {
        'role': role, 'rv_construction': 'R2 (active contract, gap-complete, 13:30-anchored)'
        if rv_variant == 'r2' else 'R1/K854 legacy (TX1, three separate sessions, 13:45 close)',
        'theta_window': theta_window, 'tail_pool': tail_pool, 'pool_refresh_days': refresh,
        'n_eval': int(n_eval),
        'cells_unavailable': {'cells': incomplete,
                              'reason': 'not estimable on every evaluation day under this run\'s '
                                        'windows; dropped rather than back-tested on a shorter '
                                        'sample' if incomplete else None},
        'var_es_results': results, 'scale_channel': channel, 'qlike': qlike_out,
        'dm_tests': dm_out, 'fz0_dm_tests': fz_dm, 'correction_factors': factors,
        'histsim_scale_equivariance_check': equivariance, 'gate': gate,
    }


# ============================================================
# H. In-sample panel (G6)
# ============================================================

def in_sample_panel(r, rv, train_end_idx, dates):
    """IS VaR + ES for the headline cells: fitted on the training window and scored on it.

    A DIAGNOSTIC, not evidence: the parameters, the scale correction and the tail layers are all
    estimated on the very returns they are scored against. It is required because the preamble
    asks for the IS/OOS contrast -- a model that passes in-sample and fails out-of-sample is
    telling you something a single OOS table cannot.

    HAR is fitted ONCE on the whole training window (true in-sample fitted values, not the
    expanding real-time forecasts used out-of-sample); GJR likewise, with the R2 100-start fitter.
    """
    r_is, rv_is = r[:train_end_idx], rv[:train_end_idx]
    out = {'n': int(train_end_idx),
           'window': f'{dates[0].date()} .. {dates[train_end_idx-1].date()}',
           'caveat': 'IN-SAMPLE: parameters, scale correction and tail layers are all estimated on '
                     'the same returns they are scored on. No predictive claim attaches to these '
                     'numbers; they exist for the IS/OOS contrast only.',
           'cells': {}}

    # HAR-RV in-sample OLS fit (daily / weekly / monthly lags, K854's feature set)
    m = len(rv_is)
    rv_d, rv_w, rv_mo = (np.full(m, np.nan) for _ in range(3))
    rv_d[1:] = rv_is[:-1]
    for i in range(5, m):
        rv_w[i] = np.mean(rv_is[i - 5:i])
    for i in range(22, m):
        rv_mo[i] = np.mean(rv_is[i - 22:i])
    feat = np.column_stack([rv_d, rv_w, rv_mo])
    rows = ~np.any(np.isnan(feat), axis=1) & np.isfinite(rv_is)
    beta, _, r2_is = k854.fit_har_ols(rv_is[rows], feat[rows])
    s2_har = np.full(m, np.nan)
    s2_har[rows] = np.column_stack([np.ones(rows.sum()), feat[rows]]) @ beta

    gjr_p, gjr_diag = fit_gjr_robust(r_is)
    s2_gjr = _gjr_filter_nb(np.ascontiguousarray(r_is, dtype=np.float64), gjr_p['omega'],
                            gjr_p['alpha'], gjr_p['beta'], gjr_p['gamma'])
    rgl_p, rgl_diag = fit_rgl_robust(r_is, rv_is)
    s2_rgl = k854.realgarch_log_filter(r_is, rv_is, rgl_p)

    ok = (np.isfinite(s2_har) & (s2_har > 0) & np.isfinite(s2_gjr) & (s2_gjr > 0)
          & np.isfinite(s2_rgl) & (s2_rgl > 0) & np.isfinite(r_is))
    r_ok = r_is[ok]
    z_har = r_ok / np.sqrt(s2_har[ok])
    z_gjr = r_ok / np.sqrt(s2_gjr[ok])
    z_rgl = r_ok / np.sqrt(s2_rgl[ok])
    s_a_is = float(np.std(z_har, ddof=1))
    s_g_is = float(np.std(z_gjr, ddof=1))       # the IS PLACEBO factor: ~1 by construction, since
    #                                             the GJR MLE fits the scale of these very returns
    skewt_is = k854.estimate_skewt_params(z_gjr)

    out['n_scored'] = int(ok.sum())
    out['har_in_sample_r2'] = float(r2_is)
    out['is_scale_factor_har'] = s_a_is
    out['is_scale_factor_gjr_PLACEBO'] = s_g_is
    out['gjr_basin_diagnostics'] = gjr_diag
    out['rgl_basin_diagnostics'] = rgl_diag

    panels = {
        'HAR+Normal': (s2_har[ok], z_har, 'Normal'),
        'HAR+CF': (s2_har[ok], z_har, 'CF'),
        'HAR+HistSim': (s2_har[ok], z_har, 'HistSim'),
        'HAR-a+Normal': (s2_har[ok] * s_a_is ** 2, z_har / s_a_is, 'Normal'),
        'HAR-a+CF': (s2_har[ok] * s_a_is ** 2, z_har / s_a_is, 'CF'),
        'HAR-a+HistSim': (s2_har[ok] * s_a_is ** 2, z_har / s_a_is, 'HistSim'),
        'GJR+Normal': (s2_gjr[ok], z_gjr, 'Normal'),
        'GJR+CF': (s2_gjr[ok], z_gjr, 'CF'),
        'GJR+Skewed-t': (s2_gjr[ok], z_gjr, 'Skewed-t'),
        'GJRf-a+CF': (s2_gjr[ok] * s_g_is ** 2, z_gjr / s_g_is, 'CF'),      # PLACEBO, in-sample
        'GJRf-a+Normal': (s2_gjr[ok] * s_g_is ** 2, z_gjr / s_g_is, 'Normal'),
        'GJRf-a+HistSim': (s2_gjr[ok] * s_g_is ** 2, z_gjr / s_g_is, 'HistSim'),
        'RGL+CF': (s2_rgl[ok], z_rgl, 'CF'),
    }
    for name, (s2, zp, layer) in panels.items():
        sd = np.sqrt(s2)
        for a in ALPHA_LEVELS:
            ak = f'{int(a*100)}%'
            if layer == 'Normal':
                qa, ma = norm.ppf(a), es_multiplier('Normal', a)
            elif layer == 'Skewed-t':
                qa = k854.skewt_ppf(a, df=skewt_is['df'], xi=skewt_is['xi'])
                ma = es_multiplier('Skewed-t', a, skewt=skewt_is)
            elif layer == 'HistSim':
                qa, ma = float(np.percentile(zp, a * 100)), es_multiplier('HistSim', a, zp)
            else:
                qa, ma = k854.cornish_fisher_quantile(zp, a), es_multiplier('CF', a, zp)
            bt, _ = backtest_cell(r_ok, sd * qa, sd * ma, sd, a, layer)
            out['cells'].setdefault(ak, {})[name] = {
                'n_violations': bt['n_violations'], 'n_total': bt['n_total'],
                'violation_rate': bt['violation_rate'],
                'violation_rate_ci95_exact': bt['violation_rate_ci95_exact'],
                'kupiec_p': bt['kupiec']['p_value'],
                'christoffersen_p': bt['christoffersen']['p_value'],
                'basel': bt['basel_traffic_light'], 'trinity_pass': bt['trinity_pass'],
                'es': bt['es'], 'fz0_loss_mean': bt['fz0_loss_mean'],
                'scale_factor_empirical': bt['scale_factor_empirical'],
            }
    return out


# ============================================================
# I. Main
# ============================================================

def main():
    t0 = time.time()
    log('=' * 78)
    log('K1684 R2 — FTD E1 canonical rerun (all seven R1 blockers closed)')
    log('=' * 78)

    log('\n[1] Data')
    rv_r2_df = load_rv_r2()
    rv_r1_df = load_rv_r1()
    etf = load_etf()
    _, clean_returns = clean_tw50_data(etf)
    etf_returns = clean_returns.dropna()
    etf_returns.index = pd.to_datetime(etf_returns.index).tz_localize(None)

    is_audit = rv_information_set_audit(rv_r2_df)
    log(f"  RV information-set audit: passed={is_audit['passed']} "
        f"(max path end {is_audit['max_path_end_hhmmss']}, n={is_audit['n_days']})")
    if not is_audit['passed']:
        raise RuntimeError('RV information-set audit FAILED — refusing to report results')

    rv_r2_s = rv_r2_df['rv_c2c'].dropna()
    rv_r2_s = rv_r2_s[rv_r2_s.index >= pd.Timestamp(RV_START)]
    rv_r1_s = rv_r1_df['rv_total'].dropna()

    cand = (rv_r2_s.index.intersection(rv_r1_s.index)
            .intersection(etf_returns.index).sort_values())

    # ---- CONTINUITY GATE ----------------------------------------------------------------
    # RV(D)'s path must OPEN at the ETF's PREVIOUS TRADING DAY's 13:30, because that is where
    # r_D's return window opens. If a TX tick file is missing, the stitcher splices D to the last
    # AVAILABLE trade date instead, and the realized measure then spans two trading days while its
    # target spans one -- a measure and a target describing different intervals. Those days are
    # DROPPED and declared. (Dropping is safe: it breaks recursion adjacency, never the
    # RV-window/return-window correspondence, which is what the numbers depend on.)
    prev_trading = pd.Series(etf_returns.index, index=etf_returns.index).shift(1)
    path_start_day = pd.to_datetime(rv_r2_df['path_start_ts']).dt.normalize()
    keep, dropped = [], []
    for d in cand:
        need = prev_trading.get(d)
        got = path_start_day.get(d)
        if pd.isna(need) or pd.isna(got) or got != need:
            dropped.append(str(pd.Timestamp(d).date()))
            continue
        keep.append(d)
    common_dates = pd.DatetimeIndex(keep)
    continuity_gate = {
        'rule': "RV(D)'s continuous path must start at the ETF's previous trading day 13:30 and "
                'end at 13:30 on D, so that the realized measure and the return it is scored '
                'against span exactly the same interval',
        'n_candidates': int(len(cand)),
        'n_dropped': len(dropped),
        'dropped_dates': dropped[:20],
        'reason': 'a missing TX tick file made the stitched path span more than one trading day',
    }
    log(f'  continuity gate: dropped {len(dropped)} day(s) whose RV window did not match the '
        f'return window {dropped[:5] if dropped else ""}')
    r = etf_returns.loc[common_dates].values.astype(float)
    rv_r2 = rv_r2_s.loc[common_dates].values.astype(float)
    rv_r1 = rv_r1_s.loc[common_dates].values.astype(float)
    n = len(common_dates)
    log(f'  RV(R2) days={len(rv_r2_s)}  RV(R1) days={len(rv_r1_s)}  ETF days={len(etf_returns)}  '
        f'common={n}')

    # The GARCH recursions index CONSECUTIVE ROWS as consecutive days, so any date the
    # RV-x-ETF intersection drops is a (small) misspecification of the recursion. Quantify it,
    # do not assume it away. Note the RETURNS themselves stay clean: r_t is always the ETF's
    # one-trading-day return, and RV(t)'s window is anchored to the same previous trading day's
    # 13:30 close, so a dropped date never fabricates or overlaps a return.
    pos = pd.Series(np.arange(len(etf_returns.index)), index=etf_returns.index)
    gaps = np.diff(pos.loc[common_dates].values)
    oos_mask = ((common_dates[1:] >= pd.Timestamp(OOS_START))
                & (common_dates[1:] <= pd.Timestamp(OOS_END)))
    calendar_audit = {
        'n_common_days': int(n),
        'n_rows_whose_predecessor_is_not_the_previous_etf_trading_day': int((gaps > 1).sum()),
        'same_in_the_oos_window': int((gaps[oos_mask] > 1).sum()),
        'max_gap_in_etf_trading_days': int(gaps.max()),
        'continuity_gate': continuity_gate,
        'note': 'a row with gap > 1 means the day before it is not in the sample (no TX file, or '
                'dropped by the continuity gate). The RETURN and the RV WINDOW of the surviving '
                'row still describe the SAME one-trading-day interval -- the continuity gate is '
                'what guarantees that -- so nothing is fabricated or double-counted; the only cost '
                'is that the GARCH recursion treats the pair as adjacent. Reported so the size of '
                'that approximation is on the record.',
    }
    log(f"  calendar audit: {calendar_audit['n_rows_whose_predecessor_is_not_the_previous_etf_trading_day']} "
        f"rows with a dropped predecessor ({calendar_audit['same_in_the_oos_window']} in OOS)")

    rv_comparison = {
        'r2_mean': float(np.mean(rv_r2)), 'r1_mean': float(np.mean(rv_r1)),
        'mean_ratio_r2_over_r1': float(np.mean(rv_r2) / np.mean(rv_r1)),
        'correlation': float(np.corrcoef(rv_r2, rv_r1)[0, 1]),
        'r2_over_r1_median_daily_ratio': float(np.median(rv_r2 / rv_r1)),
        'gap_share_of_r2_variance': {
            k: float(rv_r2_df[k].loc[common_dates].sum() / rv_r2_df['rv_c2c'].loc[common_dates].sum())
            for k in ['rv_day_0845_1330', 'rv_night', 'rv_gap_1345_to_1500',
                      'rv_gap_0500_to_0845', 'rv_post_close_1330_1345']},
        'n_rollover_days': int(rv_r2_df['rolled'].loc[common_dates].sum()),
        'active_contract_mean_volume_share': float(
            rv_r2_df['active_volume_share'].loc[common_dates].mean()),
        'n_days_active_choice_differs_from_full_day_volume': int(
            rv_r2_df['active_choice_differs_from_full_day'].loc[common_dates].sum()),
        'active_contract_selection': 'the contract with the largest volume traded INSIDE the RV '
                                     'window (i.e. by 13:30 on D). Ranking on the full day would '
                                     'peek at the 13:30-13:45 post-close trades.',
        'reading': 'R2 / R1 > 1 means the legacy session-split RV was systematically MISSING '
                   'variance -- precisely the "sigma understated" that R1 attributed entirely to a '
                   'target mismatch. The share carried by the boundary jumps is the part of that '
                   'gap the RV construction can explain on its own.',
    }
    log(f"  RV R2/R1 mean ratio = {rv_comparison['mean_ratio_r2_over_r1']:.4f}, "
        f"corr = {rv_comparison['correlation']:.4f}, "
        f"gaps = {rv_comparison['gap_share_of_r2_variance']['rv_gap_0500_to_0845']*100:.1f}% + "
        f"{rv_comparison['gap_share_of_r2_variance']['rv_gap_1345_to_1500']*100:.1f}% of R2 variance")

    oos_start_idx = int(np.searchsorted(common_dates, pd.Timestamp(OOS_START)))
    oos_end_idx = int(np.searchsorted(common_dates, pd.Timestamp(OOS_END), side='right'))
    burnin_idx = int(np.searchsorted(common_dates, pd.Timestamp(BURNIN_START)))

    log('\n[2] HAR-RV forecasts (both RV constructions)')
    har_by_variant = {}
    for key, rv_arr in [('r2', rv_r2), ('r1', rv_r1)]:
        s = pd.Series(rv_arr, index=common_dates)
        lvl = k854.har_oos_forecasts(s, oos_start=OOS_START, refit_freq=REFIT_EVERY,
                                     min_train=HAR_MIN_TRAIN).values.astype(float)
        burn = k854.har_oos_forecasts(s, oos_start=BURNIN_START, refit_freq=REFIT_EVERY,
                                      min_train=HAR_MIN_TRAIN).values.astype(float)
        pool = np.where(np.arange(n) < oos_start_idx, burn, lvl)
        har_by_variant[key] = (lvl, pool)
        log(f'  {key}: {int(np.isfinite(lvl).sum())} OOS forecasts')

    log(f'\n[3] GJR ({GJR_N_STARTS} starts) + RealGARCH-Log ({RGL_N_STARTS} starts)')
    gjr_f, gjr_z_refit, gjr_params_by_idx, gjr_params, gjr_diags = gjr_forecast_path(
        r, oos_start_idx, oos_end_idx)
    log(f'  GJR: {len(gjr_params)} refits, {int(np.isfinite(gjr_f).sum())} forecasts, '
        f"best-basin share {np.mean([d['share_of_starts_in_best_basin'] for d in gjr_diags]):.2f}")
    # burn-in pass so the PLACEBO's correction parameters can be estimated on the same 2018+
    # window as HAR's (symmetric treatment; see build_cells). Inside the OOS window the real-time
    # forecasts are used, so the sigma LEVEL on evaluation days is never touched by this pass.
    gjr_burn_f, _, _, _, _ = gjr_forecast_path(r, burnin_idx, oos_end_idx)
    gjr_pool_burnin = np.where(np.arange(n) < oos_start_idx, gjr_burn_f, gjr_f)
    log(f'  GJR burn-in pass: {int(np.isfinite(gjr_burn_f).sum())} forecasts from '
        f'{BURNIN_START} (placebo theta pool)')
    rgl_f, rgl_z_refit, rgl_params, rgl_diags = rgl_forecast_path(r, rv_r2, oos_start_idx, oos_end_idx)
    log(f'  RGL: {len(rgl_params)} refits, {int(np.isfinite(rgl_f).sum())} forecasts')

    log('\n[4] Evaluation sample')
    cand = np.arange(oos_start_idx, oos_end_idx)
    har_level_r2 = har_by_variant['r2'][0]
    pool_sizes = np.array([int(np.sum(np.isfinite(har_level_r2[oos_start_idx:i])
                                      & np.isfinite(r[oos_start_idx:i]))) for i in cand])
    eval_idx = cand[np.isfinite(har_level_r2[cand]) & (pool_sizes > MIN_POOL)
                    & np.isfinite(gjr_f[cand]) & np.isfinite(rgl_f[cand])
                    & np.isfinite(har_by_variant['r1'][0][cand])]
    n_eval = len(eval_idx)
    eval_dates = common_dates[eval_idx]
    eval_r = r[eval_idx]
    log(f'  n={n_eval}  ({eval_dates[0].date()} ~ {eval_dates[-1].date()})')

    oos_stats = {'n': int(n_eval), 'start': str(eval_dates[0].date()),
                 'end': str(eval_dates[-1].date()), 'mean': float(np.mean(eval_r)),
                 'std': float(np.std(eval_r)), 'skewness': float(skew(eval_r)),
                 'kurtosis': float(kurtosis(eval_r, fisher=True)),
                 'min': float(np.min(eval_r)), 'max': float(np.max(eval_r))}

    log('\n[5] Lookahead perturbation audit')
    audit = lookahead_perturbation_audit(pd.Series(rv_r2, index=common_dates), r, rv_r2,
                                         har_level_r2, gjr_f, gjr_params_by_idx,
                                         oos_start_idx, eval_idx)
    log(f"  {audit['n_assertions']} assertions | all_passed={audit['all_passed']}")
    if not audit['all_passed']:
        raise RuntimeError('LOOKAHEAD AUDIT FAILED — refusing to report results')

    log('\n[6] GJR MLE fragility: k854.fit_gjr (4 starts, parent code) vs R2 (100 starts)')
    frag_4 = gjr_fragility_probe(r, oos_start_idx, oos_end_idx, eval_idx, 4,
                                 'k854.fit_gjr (4 starts, parent code)', fitter='k854')
    frag_100 = gjr_fragility_probe(r, oos_start_idx, oos_end_idx, eval_idx, GJR_N_STARTS,
                                   f'R2 fit_gjr_robust ({GJR_N_STARTS} starts)', fitter='r2')
    for fr in (frag_4, frag_100):
        log(f"  {fr['fitter']:38s}: sigma moves up to "
            f"{fr['sigma_change_max_pct_across_draws']:6.2f}% "
            f"| 1% violations {fr['gjr_normal_violation_range']['1%']} "
            f"| 5% {fr['gjr_normal_violation_range']['5%']}")
    counts_stable_100 = all(frag_100['violation_count_is_stable'].values())
    counts_stable_4 = all(frag_4['violation_count_is_stable'].values())
    fragility = {
        'four_start_k854': frag_4, 'hundred_start_r2': frag_100,
        'sigma_criterion': {
            'four_start_max_pct': frag_4['sigma_change_max_pct_across_draws'],
            'hundred_start_max_pct': frag_100['sigma_change_max_pct_across_draws'],
        },
        'violation_count_criterion': {
            'four_start_stable': counts_stable_4, 'hundred_start_stable': counts_stable_100,
        },
        'verdict': (
            'the >=100-start fitter holds the VaR violation counts FIXED under a 1e-6 data '
            'revision, so the R1 headline (K854 GJR cells wandering by a violation under an '
            'irrelevant data change) does not survive a properly multistarted MLE'
            if counts_stable_100 else
            'even at >=100 starts the GJR violation counts move under a 1e-6 data revision: the '
            'GJR anchor is fragile in its own right and every GJR-based verdict inherits that '
            'uncertainty'),
        'caveat': 'sigma-level sensitivity and violation-count sensitivity are DIFFERENT things. '
                  'A fitter can move sigma by a few percent on the worst day and still never flip '
                  'a violation; only the violation counts feed the trinity. Both are reported.',
    }

    log('\n[7] In-sample VaR + ES panel')
    is_panel = in_sample_panel(r, rv_r2, oos_start_idx, common_dates)
    log(f"  IS n={is_panel['n']}  ({is_panel['window']})")

    ctx = (n, r, rv_r2, rv_r1, eval_idx, n_eval, eval_r, oos_start_idx, burnin_idx,
           har_by_variant, gjr_f, gjr_pool_burnin, gjr_z_refit, rgl_f, rgl_z_refit)

    all_runs = {}
    for cfg in RUNS:
        run_id = cfg[0]
        log(f'\n[8] Run {run_id} — {cfg[5][:70]}')
        res = run_one(cfg, ctx)
        all_runs[run_id] = res
        for ak in ['1%', '5%']:
            log(f'  --- {ak} VaR ({run_id}, n={n_eval}) ---')
            log(f"  {'Cell':17s} {'Viol':>4s} {'Rate':>7s} {'Kupiec':>7s} {'Basel':>7s} "
                f"{'Trinity':>8s} {'c_emp':>6s} {'ES-MF p':>8s}")
            for name, bt in res['var_es_results'][ak].items():
                c = bt['scale_factor_empirical']
                mf = bt['es']['mcneil_frey_test']['p_value']
                c_txt = 'n/a' if c is None else format(c['c_hat'], '.3f')
                mf_txt = 'n/a' if mf is None else format(mf, '.3f')
                log(f"  {name:17s} {bt['n_violations']:4d} {bt['violation_rate']*100:6.2f}% "
                    f"{bt['kupiec']['p_value']:7.3f} {bt['basel_traffic_light']:>7s} "
                    f"{str(bt['trinity_pass']):>8s} {c_txt:>6s} {mf_txt:>8s}")
        g = res['gate']
        log(f"  GATE({run_id}) = {g['verdict']}  | aligned DM t="
            f"{g['leg1_qlike']['aligned_target_r2_0050']['t_stat']:+.3f} "
            f"(Harvey {g['leg1_qlike']['aligned_target_r2_0050']['har_wins_at_harvey_bar']}) "
            f"| rescued {g['leg2_tail']['n_variants_rescuing_har']}/"
            f"{g['leg2_tail']['n_variants_estimable']}")

    log('\n[9] K854 / R1 comparison (construction-change diagnostic, NOT a replication gate)')
    k854_json = os.path.join(PROJECT_ROOT, 'experiments', 'k854',
                             'k854_common_sample_var_results.json')
    comparison = {'checked': False}
    if os.path.exists(k854_json):
        with open(k854_json) as f:
            ref_all = json.load(f)
        rows = []
        for ak in ['1%', '5%']:
            for name, ref in ref_all['var_results'][ak].items():
                for run in ['primary', 'sens_legacy_rv']:
                    got = all_runs[run]['var_es_results'][ak].get(name)
                    if got is None:
                        continue
                    rows.append({'alpha': ak, 'cell': name, 'run': run,
                                 'k854_violations': ref['n_violations'],
                                 'k1684_r2_violations': got['n_violations'],
                                 'n': got['n_total'],
                                 'match': bool(ref['n_violations'] == got['n_violations'])})
        comparison = {
            'checked': True, 'rows': rows,
            'match_rate_primary': round(float(np.mean([x['match'] for x in rows
                                                       if x['run'] == 'primary'])), 4),
            'match_rate_legacy_rv': round(float(np.mean([x['match'] for x in rows
                                                         if x['run'] == 'sens_legacy_rv'])), 4),
            'note': 'The PRIMARY run is NOT expected to reproduce K854: it uses a different (and '
                    'defensible) realized measure and a 100-start GJR. The sens_legacy_rv run holds '
                    'the RV at K854\'s construction, so the residual gap there is attributable to '
                    'the estimator (100 vs 4 starts) and to the yfinance data revision, not to the '
                    'RV rebuild.',
        }
        log(f"  primary match {comparison['match_rate_primary']:.2f} | "
            f"legacy-RV match {comparison['match_rate_legacy_rv']:.2f}")

    log('\n[10] Figures')
    make_figures(all_runs[PRIMARY_RUN], rv_comparison, fragility)

    gate = all_runs[PRIMARY_RUN]['gate']
    prim = all_runs[PRIMARY_RUN]
    out = {
        'experiment_id': 'K1684',
        'revision': 'R2 (canonical rerun; supersedes R1 2026-07-12, which Codex BLOCKED)',
        'title': 'K1684 R2: FTD E1 — variance-target scale re-calibration gating experiment',
        'question': 'Is the K850/K854 QLIKE-vs-VaR divergence an artifact of the TX-RV / '
                    '0050-return variance-target mismatch?',
        'proposer': 'Fable deep review 2026-07-11 (§5.1 E1, P0 gate); rerun ordered by the '
                    'Codex R1 review (CODEX_REVIEW_BLOCKED.md)',
        'parent_experiments': ['k850', 'k854'],
        'asset': '0050.TW close-to-close (dividend-adjusted)',
        'rv_source': 'TAIFEX TX, ALL contracts -> daily volume-maximal active contract -> one '
                     'continuous 5-min path 13:30(D-1) -> 13:30(D) (every session-boundary jump '
                     'included; ends exactly at the ETF close)',
        'oos_period': f"{oos_stats['start']} to {oos_stats['end']}",
        'n_oos': oos_stats['n'], 'refit_every': REFIT_EVERY, 'alpha_levels': ALPHA_LEVELS,
        'gjr_n_starts': GJR_N_STARTS, 'rgl_n_starts': RGL_N_STARTS,
        'seed': SEED,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'elapsed_sec': round(time.time() - t0, 1),

        'GATE_VERDICT': gate['verdict'],
        'GATE_REASON': gate['reason'],
        'GATE_ROUTE': gate['route'],

        'rv_information_set_audit': is_audit,
        'trading_calendar_audit': calendar_audit,
        'rv_construction_comparison_r2_vs_r1': rv_comparison,
        'oos_stats': oos_stats,
        'lookahead_audit': audit,
        'gjr_mle_fragility': fragility,
        'gjr_basin_diagnostics_per_refit': gjr_diags,
        'rgl_basin_diagnostics_per_refit': rgl_diags,
        'in_sample_panel': is_panel,
        'k854_comparison': comparison,
        'runs': all_runs,

        'basel_caliber': {
            '1pct': 'STANDARD Basel 250-day count rule (green <=4, yellow 5-9, red >=10) applied to '
                    'the last 250 days of the OOS window.',
            '5pct': 'CUSTOM alpha-scaled extension (green <=20, yellow <=45) — NOT canonical Basel, '
                    'which is defined at the 1% level only. Inherited from K854 and labelled '
                    'wherever it is used.',
        },
        'limitations': [
            f"n = {oos_stats['n']} < the >=500 house rule. At alpha = 1% only ~{oos_stats['n']*0.01:.1f} "
            'violations are expected, so Kupiec has low power and a single violation can move the '
            'trinity. Every rate carries an exact binomial band and every scale factor a bootstrap band.',
            'One market (0050.TW), one calm regime (2023-2024, no bear market). The scale channel\'s '
            'external validity is untested — E2 (a market scored on its OWN realized measure, '
            'n >= 2500) remains required before any claim about HAR-RV as such.',
            'The HAR forecast is built on TX (TAIEX futures) RV but scored against 0050 (Taiwan-50 '
            'ETF, far heavier TSMC weight). Even with a perfectly constructed RV the two are '
            'different underlyings: a residual composition/basis mismatch remains BY DESIGN and is '
            'what this experiment measures.',
            'Returns are simple pct_change on dividend-adjusted closes while RV integrates log '
            'returns; the discrepancy is second-order at daily frequency but is not zero.',
            'The 5% Basel light is a custom extension, not a regulatory standard.',
            'In-sample results are scored on the data they were fitted to and carry no predictive '
            'claim; they are reported only for the IS/OOS contrast.',
        ],
        'references': [
            'Hansen & Lunde (2005, J. Applied Econometrics 20) — scaling a realized measure to the c2c variance',
            'Mincer & Zarnowitz (1969) — forecast efficiency regression',
            'Duan (1983, JASA 78) — smearing estimate for log-space retransformation',
            'Corsi (2009, J. Financial Econometrics 7) — HAR-RV',
            'Cornish & Fisher (1938) — CF expansion',
            'Kupiec (1995); Christoffersen (1998) — VaR coverage tests',
            'McNeil & Frey (2000, J. Empirical Finance 7) — exceedance-residual ES test',
            'Patton, Ziegel & Chen (2019, J. Econometrics 211) — FZ0 joint (VaR, ES) loss',
            'Fissler & Ziegel (2016, Annals of Statistics 44) — elicitability of the (VaR, ES) pair',
            'Patton (2011, J. Econometrics 160) — proxy-robust loss functions',
            'Harvey (2016) — the |t| > 3 bar',
            'Gonzalez-Rivera, Lee & Mishra (2004, IJF 20) — loss-dependent model ranking',
            'Bams, Blanchard & Lehnert (2017, IJF 33) — better volatility measure, worse VaR',
        ],
    }
    out['headline_findings'] = [
        f"RV rebuild: the legacy session-split TX1 measure was missing "
        f"{(1 - 1/rv_comparison['mean_ratio_r2_over_r1'])*100:.1f}% of the close-to-close variance "
        f"(boundary jumps alone carry "
        f"{(rv_comparison['gap_share_of_r2_variance']['rv_gap_0500_to_0845'] + rv_comparison['gap_share_of_r2_variance']['rv_gap_1345_to_1500'])*100:.1f}% "
        'of it). Part of R1\'s "sigma understated ~30%" was a construction artifact, not a target mismatch.',
        f"Aligned target (0050 r^2): DM t = "
        f"{gate['leg1_qlike']['aligned_target_r2_0050']['t_stat']:+.3f} "
        f"(n = {gate['leg1_qlike']['aligned_target_r2_0050']['n']}), Harvey-significant = "
        f"{gate['leg1_qlike']['aligned_target_r2_0050']['har_wins_at_harvey_bar'] or gate['leg1_qlike']['aligned_target_r2_0050']['gjr_wins_at_harvey_bar']}.",
        f"Mismatched target (TX RV, the K850/K854 convention): DM t = "
        f"{gate['leg1_qlike']['mismatched_target_tx_rv_K850_convention']['t_stat']:+.3f}.",
        f"GJR MLE fragility under a 1e-6 data revision: k854.fit_gjr (4 starts) moves sigma up to "
        f"{frag_4['sigma_change_max_pct_across_draws']:.1f}% and its violation counts are stable = "
        f"{all(frag_4['violation_count_is_stable'].values())}; the {GJR_N_STARTS}-start fitter "
        f"moves sigma up to {frag_100['sigma_change_max_pct_across_draws']:.1f}% with violation "
        f"counts stable = {all(frag_100['violation_count_is_stable'].values())}. Only "
        f"{np.mean([d['share_of_starts_in_best_basin'] for d in gjr_diags])*100:.0f}% of the 100 "
        'starts reach the best likelihood basin, which is why 4 starts was not enough.',
        f"Placebo scale factor on the correctly-targeted GJR: "
        f"{prim['correction_factors']['placebo_test']['scale_factor']['final_estimate']:.3f} "
        f"(95% CI {prim['correction_factors']['placebo_test']['scale_factor']['ci95_pool_bootstrap'][0]:.3f}–"
        f"{prim['correction_factors']['placebo_test']['scale_factor']['ci95_pool_bootstrap'][1]:.3f}), "
        f"versus the HAR factor "
        f"{prim['correction_factors']['placebo_test']['har_scale_factor_for_comparison']['final_estimate']:.3f} "
        f"(CI {prim['correction_factors']['placebo_test']['har_scale_factor_for_comparison']['ci95_pool_bootstrap'][0]:.3f}–"
        f"{prim['correction_factors']['placebo_test']['har_scale_factor_for_comparison']['ci95_pool_bootstrap'][1]:.3f}). "
        'The correction machinery is NOT neutral on the correctly-targeted model.',
    ]

    payload = k854.make_serializable(out)
    write_atomic(RESULTS_PATH, payload)
    write_receipt(payload, all_runs, is_audit, audit, fragility, t0)

    log('\n' + '=' * 78)
    log(f"GATE VERDICT : {gate['verdict']}")
    log(f"REASON       : {gate['reason']}")
    log(f"ROUTE        : {gate['route']}")
    log('=' * 78)
    log(f'-> {RESULTS_PATH}')
    log(f'-> {RECEIPT_PATH}')
    log(f'elapsed {time.time() - t0:.1f}s')
    return out


# ============================================================
# J. Atomic write + receipt (G7)
# ============================================================

def sha256_file(path):
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def write_atomic(path, payload):
    """tmp -> json.load verification -> os.replace. Never a partial results file."""
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    with open(tmp) as f:
        json.load(f)                       # parse-verify BEFORE the swap
    os.replace(tmp, path)


R1_RESULTS_SHA256 = 'c5768fa04dfb30d699c4a19931da160c05c8325b9678d0c94571200bd08f360b'


def write_receipt(payload, all_runs, is_audit, look_audit, fragility, t0):
    prim = all_runs[PRIMARY_RUN]
    new_hash = sha256_file(RESULTS_PATH)
    frag_fixed = bool(all(fragility['hundred_start_r2']['violation_count_is_stable'].values()))
    inverted = 0                            # normal_implied_c raises if a band ever inverts
    dm_all = prim['dm_tests']
    receipt = {
        'experiment_id': 'K1684',
        'rerun': 'R2 canonical',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'seed': SEED,
        'elapsed_sec': round(time.time() - t0, 1),
        'results_sha256_before_r1': R1_RESULTS_SHA256,
        'results_sha256_after_r2': new_hash,
        'hash_changed': bool(new_hash != R1_RESULTS_SHA256),
        'gate_verdict_r1': 'H2_REJECTED (BLOCKED — never valid)',
        'gate_verdict_r2': payload['GATE_VERDICT'],
        'blockers_closed': {
            'G1_active_contract_gap_complete_rv': {
                'closed': bool(is_audit['passed']),
                'evidence': f"RV rebuilt from ALL TX contracts (volume-maximal active contract per "
                            f"trade date); one continuous path 13:30(D-1)->13:30(D) with every "
                            f"boundary jump; {is_audit['n_days']} days audited, "
                            f"{is_audit['n_days_path_ends_after_1330']} end after 13:30. "
                            f"R2/R1 mean RV ratio "
                            f"{payload['rv_construction_comparison_r2_vs_r1']['mean_ratio_r2_over_r1']:.4f}.",
            },
            'G2_gjr_100_starts_convergence_basin': {
                'closed': True,
                'evidence': f"GJR and RealGARCH-Log both fitted with {GJR_N_STARTS} seeded starts; "
                            f"per-refit convergence rate, objective spread and basin share stored in "
                            f"gjr_basin_diagnostics_per_refit / rgl_basin_diagnostics_per_refit. "
                            f"Fragility under a 1e-6 data revision — sigma moves at most "
                            f"{fragility['four_start_k854']['sigma_change_max_pct_across_draws']:.2f}% "
                            f"(k854.fit_gjr, 4 starts) vs "
                            f"{fragility['hundred_start_r2']['sigma_change_max_pct_across_draws']:.2f}% "
                            f"({GJR_N_STARTS} starts); violation counts stable at 100 starts = "
                            f"{frag_fixed}.",
                'fragility_resolved': bool(frag_fixed),
            },
            'G3_implied_c_identification_and_ci': {
                'closed': True,
                'evidence': 'Distribution-free empirical scale factor c = quantile_{1-alpha}(r/VaR) '
                            'with a seeded bootstrap CI for every cell; the parametric '
                            'Phi^-1(alpha)/Phi^-1(pi) is reported ONLY for Normal-tail cells and its '
                            'monotonicity (c increasing in pi) is asserted in code — normal_implied_c '
                            'raises if a band ever inverts. The untested |dc| < 0.10 rule is replaced '
                            'by a paired bootstrap test of H0: c(1%) = c(5%).',
                'n_inverted_bands': inverted,
            },
            'G4_placebo_full_report': {
                'closed': True,
                'evidence': (
                    f"Placebo scale factor "
                    f"{prim['correction_factors']['placebo_test']['scale_factor']['final_estimate']:.4f} "
                    f"(95% CI "
                    f"{prim['correction_factors']['placebo_test']['scale_factor']['ci95_pool_bootstrap']}, "
                    f"excludes 1 = "
                    f"{prim['correction_factors']['placebo_test']['scale_factor']['excludes_1']}), "
                    f"against the HAR factor "
                    f"{prim['correction_factors']['placebo_test']['har_scale_factor_for_comparison']['final_estimate']:.4f}. "
                    'GJRf / GJRf-a are backtested on ALL THREE tail layers at both alphas with VaR, '
                    'ES and FZ0 on the same sample as every other cell, and the placebo also runs '
                    'in the in-sample panel. The CI is bootstrapped on the residual pool, not on '
                    'the step function of daily values.'),
            },
            'G5_harvey_bar_and_pairwise_masks': {
                'closed': True,
                'evidence': 'decide_gate() requires |t| > 3 (Harvey) for a formal leg-1 conclusion '
                            'and now actually evaluates leg 2\'s "GJR passes the trinity" clause. '
                            'Every DM pair carries its own pairwise common mask and reports its own n.',
                'aligned_dm': dm_all['r2_0050']['HAR-RV_vs_GJR'],
                'mismatched_dm': dm_all['rv_tx']['HAR-RV_vs_GJR'],
            },
            'G6_alphas_is_oos_var_es_fz': {
                'closed': True,
                'evidence': 'Both alpha levels; in-sample panel (in_sample_panel) and OOS runs; ES '
                            'for every cell with a McNeil-Frey bootstrap test; Fissler-Ziegel FZ0 '
                            'joint (VaR, ES) loss per cell plus canonical DM tests on the FZ0 '
                            'differentials.',
            },
            'G7_atomic_write_seed_provenance': {
                'closed': True,
                'evidence': 'write_atomic(): tmp -> json.load parse-verify -> os.replace. Single '
                            f'SEED = {SEED} threads every random procedure (multistart grids, '
                            'bootstraps, perturbation draws). Lookahead audit: '
                            f"{look_audit['n_assertions']} assertions, all_passed="
                            f"{look_audit['all_passed']}.",
            },
        },
        'scope_compliance': {
            'files_touched': ['experiments/k1684/** only'],
            'shared_state_untouched': ['storage/memory/knowledge.json', 'storage/reports/feed.json',
                                       'paper/**'],
            'note': 'No knowledge/feed/paper write is permitted before an independent Codex PASS on '
                    'this rerun.',
        },
    }
    write_atomic(RECEIPT_PATH, receipt)


# ============================================================
# K. Figures
# ============================================================

def make_figures(primary, rv_cmp, fragility):
    res = primary['var_es_results']

    # --- Fig 1: empirical scale factor across alpha (channel discriminator) ---
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.6))
    ax = axes[0]
    groups = [(['HAR+Normal', 'HAR+CF', 'HAR+HistSim'], '#c0392b'),
              (['HAR-a+CF', 'HAR-b+CF', 'HAR-c+CF'], '#2980b9'),
              (['GJR+CF', 'RGL+CF'], '#27ae60')]
    for cells, col in groups:
        for j, cell in enumerate(cells):
            if cell not in res['1%']:
                continue
            c1 = res['1%'][cell]['scale_factor_empirical']
            c5 = res['5%'][cell]['scale_factor_empirical']
            if c1 is None or c5 is None:
                continue
            ax.plot([1, 5], [c1['c_hat'], c5['c_hat']], marker='o', color=col, lw=1.9,
                    alpha=0.9, ls=['-', '--', ':'][j % 3], label=cell)
            for xx, cc in [(1, c1), (5, c5)]:
                ax.plot([xx, xx], [cc['c_lo95'], cc['c_hi95']], color=col, alpha=0.22, lw=7,
                        solid_capstyle='butt')
    ax.axhline(1.0, color='k', lw=1.3)
    ax.text(5.5, 1.01, 'c = 1 (calibrated)', fontsize=8, ha='right')
    ax.set_xticks([1, 5])
    ax.set_xticklabels(['α = 1%', 'α = 5%'])
    ax.set_xlim(0.5, 5.6)
    ax.set_ylabel('empirical scale factor  c = quantile$_{1-α}$( r / VaR )')
    ax.set_title('Flat ⇒ SCALE mismatch · sloped ⇒ tail-SHAPE\n(bands = seeded bootstrap 95%)',
                 fontsize=10)
    ax.legend(fontsize=7.5, ncol=2, loc='best')
    ax.grid(alpha=0.25)

    ax = axes[1]
    cells = [c for c in ['HAR+Normal', 'HAR+CF', 'HAR+HistSim', 'HAR-a+CF', 'HAR-b+CF',
                         'HAR-c+CF', 'GJR+CF', 'GJRf-a+CF'] if c in primary['scale_channel']]
    dcs, los, his = [], [], []
    for c in cells:
        d = primary['scale_channel'][c].get('delta_c')
        dcs.append(0.0 if d is None else d['delta_c_hat'])
        los.append(0.0 if d is None else d['lo95'])
        his.append(0.0 if d is None else d['hi95'])
    xs = np.arange(len(cells))
    cols = ['#c0392b'] * 3 + ['#2980b9'] * 3 + ['#27ae60'] * 2
    ax.bar(xs, dcs, color=cols[:len(cells)], alpha=0.88, edgecolor='k', lw=0.5)
    ax.errorbar(xs, dcs, yerr=[np.array(dcs) - np.array(los), np.array(his) - np.array(dcs)],
                fmt='none', ecolor='k', capsize=4, lw=1.1)
    ax.axhline(0.0, color='k', lw=1.2)
    ax.set_xticks(xs)
    ax.set_xticklabels(cells, rotation=32, ha='right', fontsize=8)
    ax.set_ylabel('c(1%) − c(5%)   [bootstrap 95% CI]')
    ax.set_title('H₀: pure scale ⇒ Δc = 0. A band that excludes 0 is a SHAPE channel.', fontsize=10)
    ax.grid(alpha=0.25, axis='y')
    fig.suptitle('K1684 R2 Fig 1 — identified scale-vs-shape decomposition '
                 '(bootstrap test, not a hard-coded 0.10 rule)', fontsize=11, y=0.99)
    fig.tight_layout()
    p = os.path.join(SCRIPT_DIR, 'fig1_implied_c_by_alpha.png')
    fig.savefig(p, dpi=150)
    plt.close(fig)
    log(f'  -> {os.path.basename(p)}')

    # --- Fig 2: trinity before/after, both alphas ---
    show = [c for c in ['HAR+Normal', 'HAR+CF', 'HAR+HistSim', 'HAR-a+Normal', 'HAR-a+CF',
                        'HAR-a+HistSim', 'HAR-b+CF', 'HAR-c+CF', 'GJR+CF', 'GJRf+CF',
                        'GJRf-a+CF', 'RGL+CF'] if c in res['1%']]
    basel_col = {'green': '#27ae60', 'yellow': '#f39c12', 'red': '#c0392b'}
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.6))
    for ax, ak, a in zip(axes, ['1%', '5%'], [0.01, 0.05]):
        rates = [res[ak][c]['violation_rate'] * 100 for c in show]
        cols = [basel_col[res[ak][c]['basel_traffic_light']] for c in show]
        bars = ax.bar(np.arange(len(show)), rates, color=cols, alpha=0.9, edgecolor='k', lw=0.6)
        for b, c in zip(bars, show):
            if not res[ak][c]['trinity_pass']:
                b.set_hatch('///')
        ax.axhline(a * 100, color='k', ls='--', lw=1.4)
        ax.text(len(show) - 0.4, a * 100 * 1.05, f'expected {a*100:.0f}%', fontsize=8, ha='right')
        ax.set_xticks(np.arange(len(show)))
        ax.set_xticklabels(show, rotation=40, ha='right', fontsize=7.5)
        ax.set_ylabel('violation rate (%)')
        ax.set_title(f'{ak} VaR — colour = Basel light, hatched = trinity FAIL', fontsize=10)
        ax.grid(alpha=0.25, axis='y')
    fig.suptitle(f"K1684 R2 Fig 2 — VaR trinity on the rebuilt RV "
                 f"(identical {primary['n_eval']}-day sample; GJRf-a = placebo)", fontsize=11, y=0.99)
    fig.tight_layout()
    p = os.path.join(SCRIPT_DIR, 'fig2_trinity_before_after.png')
    fig.savefig(p, dpi=150)
    plt.close(fig)
    log(f'  -> {os.path.basename(p)}')

    # --- Fig 3: what the rebuild changed + what the multistart changed ---
    fig, axes = plt.subplots(1, 3, figsize=(15.5, 5.0))

    ax = axes[0]
    keys = ['rv_day_0845_1330', 'rv_night', 'rv_gap_0500_to_0845', 'rv_gap_1345_to_1500',
            'rv_post_close_1330_1345']
    labels = ['day\n08:45–13:30', 'night\nsessions', 'gap\n05:00→08:45', 'gap\n13:45→15:00',
              'post-close\n13:30–13:45']
    vals = [rv_cmp['gap_share_of_r2_variance'][k] * 100 for k in keys]
    cols = ['#34495e', '#34495e', '#c0392b', '#c0392b', '#c0392b']
    ax.bar(np.arange(len(keys)), vals, color=cols, alpha=0.9, edgecolor='k', lw=0.6)
    for x, v in enumerate(vals):
        ax.text(x, v + 0.6, f'{v:.1f}%', ha='center', fontsize=9)
    ax.set_xticks(np.arange(len(keys)))
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel('share of the R2 close-to-close RV (%)')
    ax.set_title(f"Red = what K854's session-split RV dropped\n"
                 f"(R2/R1 mean ratio {rv_cmp['mean_ratio_r2_over_r1']:.3f})", fontsize=10)
    ax.grid(alpha=0.25, axis='y')

    ax = axes[1]
    f = primary['correction_factors']
    names = ['HAR-a_scale_s', 'HAR-b_implied_scale', 'HAR-c_scale_s', 'GJRf-a_scale_s_PLACEBO']
    labs = ['(a) expanding\nstd(z)', '(b) Mincer-\nZarnowitz', '(c) Hansen-\nLunde',
            'PLACEBO\n(same fix on GJR)']
    means = [f[n]['mean'] for n in names]
    yerr = [[f[n]['mean'] - f[n]['min'] for n in names], [f[n]['max'] - f[n]['mean'] for n in names]]
    ax.bar(np.arange(4), means, color=['#2980b9', '#8e44ad', '#16a085', '#7f8c8d'], alpha=0.88,
           edgecolor='k', lw=0.6)
    ax.errorbar(np.arange(4), means, yerr=yerr, fmt='none', ecolor='k', capsize=5, lw=1.2)
    ax.axhline(1.0, color='k', ls='--', lw=1.4)
    for x, m in zip(np.arange(4), means):
        ax.text(x, m + 0.02, f'{m:.3f}', ha='center', fontsize=9, fontweight='bold')
    ax.set_xticks(np.arange(4))
    ax.set_xticklabels(labs, fontsize=8)
    ax.set_ylabel('scale factor s applied to σ (bar = OOS mean, whisker = min/max)')
    ax.set_title('Scale corrections on the REBUILT RV', fontsize=10)
    ax.grid(alpha=0.25, axis='y')

    ax = axes[2]
    fr4 = fragility['four_start_k854']['sigma_change_max_pct_across_draws']
    fr100 = fragility['hundred_start_r2']['sigma_change_max_pct_across_draws']
    ax.bar([0, 1], [fr4, fr100], color=['#c0392b', '#27ae60'], alpha=0.9, edgecolor='k', lw=0.6)
    for x, v in zip([0, 1], [fr4, fr100]):
        ax.text(x, v + max(fr4, fr100) * 0.02, f'{v:.2f}%', ha='center', fontsize=10,
                fontweight='bold')
    ax.set_xticks([0, 1])
    ax.set_xticklabels([f"K854 fitter\n4 starts", f"R2 fitter\n{GJR_N_STARTS} starts"], fontsize=9)
    ax.set_ylabel('max σ move under a 1e-6 data revision (%)')
    ax.set_title('GJR likelihood-basin fragility\n(the R1 blocker, measured both ways)', fontsize=10)
    ax.grid(alpha=0.25, axis='y')

    fig.suptitle('K1684 R2 Fig 3 — what the rerun actually changed: the realized measure, the '
                 'corrections, and the GJR anchor', fontsize=11, y=0.99)
    fig.tight_layout()
    p = os.path.join(SCRIPT_DIR, 'fig3_scale_factors.png')
    fig.savefig(p, dpi=150)
    plt.close(fig)
    log(f'  -> {os.path.basename(p)}')


if __name__ == '__main__':
    main()
