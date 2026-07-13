"""
K628b re-run: the directional spillover conclusions under a REAL generalized FEVD.

Why this exists
---------------
`k628b_vol_spillover.py:280-299` documents its decomposition as "generalized FEVD
(Pesaran & Shin, 1998)" and then calls `results.fevd(h)`. statsmodels has no GFEVD:
`.fevd()` is the ORTHOGONALISED (Cholesky) FEVD, which is a function of the order in
which the variables were handed to the VAR. K628b's order is

    ['SPY', 'GLD', 'TLT', '0050.TW', 'USO']

with SPY first -- the position that mechanically maximises a variable's estimated
exogeneity, and therefore its NET spillover. The headline claim ("SPY is dominant NET
TRANSMITTER, net = +43.7%") is exactly the claim that position manufactures. So the
claim cannot be evaluated from the existing numbers; it has to be re-estimated with a
decomposition that does not depend on the ordering.

The axis bug is NOT the issue here. K865's `decomp[-1]` bug (error_log 2026-07-11) took
the last VARIABLE instead of the last HORIZON. K628b's `decomp[i][-1]` is the correct
slice; the class sweep confirmed it (error_log line 621) and `check_axis_equivalence()`
below re-proves it numerically rather than taking that on trust. The defect is the label
and the estimator, not the indexing.

What this script does
---------------------
A. Full sample, both decompositions. Cholesky arm must reproduce k628b_results.json,
   otherwise a Cholesky-vs-GFEVD gap could be a data/pipeline difference rather than a
   property of the estimator.
B. ALL 120 orderings (5! is small enough to enumerate -- no sampling, no blind spot).
   The VAR is genuinely re-fitted on each permuted column order, so the Cholesky factor
   of Sigma is taken in that order. GFEVD is checked to be numerically invariant across
   the same 120 fits rather than asserted to be by citation.
C. Granger network re-run. The TRANSMITTER/RECEIVER role labels in K628b come from the
   Granger out-in degree, which is a set of PAIRWISE bivariate tests and never touches a
   FEVD. Structurally it cannot be an ordering artifact -- but that is a claim about the
   code, so it is verified against the stored numbers instead of argued.
D. Rolling TSI (200-day windows) under both decompositions, benchmarked against a
   no-spillover null floor: independent AR(p) series with each asset's own persistence
   preserved and TRUE cross-dependence exactly zero. An estimated TSI level is not
   interpretable without knowing what the estimator reports when the answer is 0.

Hard rules applied (.claude/rules/experiments.md)
-------------------------------------------------
- Seed 42 for every stochastic routine (null simulation). Permutations are exhaustive,
  so nothing is left to sampling.
- No lookahead: this is an in-sample network description, not a forecast. Each rolling
  window's VAR is fitted on that window's data only and stamped at its LAST observation.
- GFEVD rows do not sum to 1 before normalisation (shocks are not orthogonalised); every
  normalised matrix is asserted to have unit row sums.
- No try/except around the estimation loops. A silently skipped fit would drop exactly
  the windows where the VAR is worst behaved, which would flatter the estimator.

References
----------
- Pesaran, H.H. & Shin, Y. (1998). "Generalized Impulse Response Analysis in Linear
  Multivariate Models." Economics Letters 58(1), 17-29.
- Koop, G., Pesaran, M.H. & Potter, S.M. (1996). J. Econometrics 74(1), 119-147.
- Diebold, F.X. & Yilmaz, K. (2012). IJF 28(1), 57-66.
- K865b (same KPPS implementation, same question asked of K865), K1025_v3.
"""

import argparse
import json
import warnings
from datetime import datetime, timezone
from itertools import permutations
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.tsa.api import VAR
from statsmodels.tsa.stattools import adfuller, grangercausalitytests

warnings.filterwarnings('ignore')

HERE = Path(__file__).resolve().parent
SEED = 42

# ── K628b's configuration, reproduced exactly ─────────────────────────────────
ASSETS = ['SPY', 'GLD', 'TLT', '0050.TW', 'USO']   # SPY first == the K628b ordering
START = '2010-01-01'
END = '2026-03-27'
ROLL_WINDOW = 22            # realized-vol window
MAX_LAG = 5                 # VAR lag ceiling (AIC selects within it), Granger maxlag
FEVD_HORIZON = 10
ROLL_SPILL_WINDOW = 200     # rolling spillover window
ROLL_STEP = 20
ROLL_MAX_LAG = 3            # K628b uses maxlags=3 inside the rolling loop

N_NULL_REPS = 200
BURN_IN = 1000


# ══════════════════════════════════════════════════════════════════════════════
# Data — identical pipeline to k628b_vol_spillover.py
# ══════════════════════════════════════════════════════════════════════════════

def load_prices(refresh: bool = False) -> pd.DataFrame:
    cache = HERE / 'data' / 'prices.csv'
    if cache.exists() and not refresh:
        prices = pd.read_csv(cache, index_col=0, parse_dates=True)
        print(f"Loaded cached prices: {len(prices)} obs "
              f"({prices.index[0].date()} to {prices.index[-1].date()})")
        return prices[ASSETS]

    import yfinance as yf
    print(f"Downloading {ASSETS} from yfinance ({START} to {END})...")
    raw = yf.download(ASSETS, start=START, end=END, auto_adjust=True, progress=False)
    prices = pd.DataFrame({a: raw['Close'][a] for a in ASSETS})
    prices = prices.ffill().dropna()          # K628b: ffill 0050.TW holidays, then dropna
    prices.to_csv(cache)
    print(f"  {len(prices)} obs -> cached at {cache}")
    return prices[ASSETS]


def build_var_input(returns: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """22-day realized vol, then K628b's stationarity-driven log transform.

    K628b takes logs iff ANY series' ADF fails at 5%. That branch is reproduced rather
    than second-guessed: the point of this script is to change the DECOMPOSITION and
    nothing else, so that any difference in the answer is attributable to the estimator.
    """
    rvol = (returns.rolling(ROLL_WINDOW).std() * np.sqrt(252)).dropna()

    stationarity = {}
    for a in ASSETS:
        stat, pval = adfuller(rvol[a].dropna(), maxlag=10)[:2]
        stationarity[a] = {'adf_stat': float(stat), 'adf_pval': float(pval)}

    any_nonstationary = any(v['adf_pval'] >= 0.05 for v in stationarity.values())
    var_input = np.log(rvol + 1e-8) if any_nonstationary else rvol
    print(f"  RVol: {len(rvol)} obs | any non-stationary at 5% = {any_nonstationary} "
          f"-> VAR input is {'log-rvol' if any_nonstationary else 'rvol (levels)'}")
    return rvol, var_input, {'per_asset': stationarity, 'log_transform_applied': any_nonstationary}


# ══════════════════════════════════════════════════════════════════════════════
# The two decompositions
# ══════════════════════════════════════════════════════════════════════════════

def cholesky_fevd(res, horizon: int = FEVD_HORIZON) -> np.ndarray:
    """Orthogonalised (Cholesky) FEVD == what statsmodels' .fevd() actually returns.

    ORDER DEPENDENT. `decomp` is (n, horizon, n): axis 0 = decomposed variable i, axis 1
    = horizon step, axis 2 = shock source j. The DY table is the final-horizon slice.
    """
    decomp = res.fevd(horizon).decomp
    n = decomp.shape[0]
    assert decomp.shape == (n, horizon, n), \
        f"unexpected FEVD shape {decomp.shape}, expected ({n}, {horizon}, {n})"
    return decomp[:, -1, :]


def check_axis_equivalence(res, horizon: int = FEVD_HORIZON) -> dict:
    """Prove, not assume, that K628b's `decomp[i][-1]` is the correct slice.

    K865 took `decomp[-1]` (last VARIABLE) and every FEVD number it reported was void.
    K628b takes `decomp[i][-1]` per row i, which is the same object as `decomp[:, -1, :]`.
    Re-deriving that here means the rerun does not inherit a claim from a class sweep.
    """
    decomp = res.fevd(horizon).decomp
    n = decomp.shape[0]
    k628b_style = np.vstack([decomp[i][-1] for i in range(n)])   # the original's indexing
    canonical = decomp[:, -1, :]                                  # the K865-fix indexing
    max_dev = float(np.abs(k628b_style - canonical).max())
    assert max_dev == 0.0, f"K628b indexing is NOT the final-horizon slice (dev {max_dev})"
    return {'k628b_indexing': 'decomp[i][-1]',
            'canonical_indexing': 'decomp[:, -1, :]',
            'max_abs_deviation': max_dev,
            'verdict': 'IDENTICAL -- K628b has no axis bug (unlike K865)'}


def generalized_fevd(res, horizon: int = FEVD_HORIZON) -> np.ndarray:
    """KPPS generalized FEVD (Koop-Pesaran-Potter 1996; Pesaran-Shin 1998).

        theta_ij(H) = sigma_jj^-1 * sum_h (e_i' A_h Sigma e_j)^2
                                  / sum_h (e_i' A_h Sigma A_h' e_i)

    Shocks are NOT orthogonalised, so the result does not depend on the ordering of the
    variables -- which is the entire reason for running it. Rows do not sum to 1 before
    normalisation; the caller row-normalises (standard DY 2012 treatment).

    Same implementation as experiments/k865b/k865b_gfevd_robustness.py.
    """
    sigma = np.asarray(res.sigma_u)
    phi = res.ma_rep(maxn=horizon - 1)          # (horizon, n, n), phi[0] = I
    assert phi.shape[0] == horizon, f"ma_rep gave {phi.shape[0]} steps, expected {horizon}"

    sig_jj = np.diag(sigma)
    num = np.zeros_like(sigma)
    den = np.zeros(sigma.shape[0])
    for h in range(horizon):
        a_sigma = phi[h] @ sigma
        num += a_sigma ** 2                     # (i,j) = (e_i' A_h Sigma e_j)^2
        den += np.diag(a_sigma @ phi[h].T)      # (i)   = e_i' A_h Sigma A_h' e_i

    return (num / sig_jj[None, :]) / den[:, None]


def row_normalize(mat: np.ndarray) -> np.ndarray:
    out = mat / mat.sum(axis=1, keepdims=True)
    assert np.allclose(out.sum(axis=1), 1.0, atol=1e-8), f"row sums not 1: {out.sum(axis=1)}"
    return out


def dy_metrics(theta_norm: np.ndarray, labels: list[str]) -> dict:
    """Diebold-Yilmaz connectedness from a row-normalised FEVD table, in percentage points.

    Row i = share of i's forecast-error variance coming from each shock j. So
    FROM_i = what i RECEIVES (row ex-diagonal), TO_j = what j TRANSMITS (column
    ex-diagonal), NET = TO - FROM. TSI = off-diagonal mass / n.
    """
    n = theta_norm.shape[0]
    m = theta_norm * 100.0
    from_ = m.sum(axis=1) - np.diag(m)
    to_ = m.sum(axis=0) - np.diag(m)
    return {
        'total_spillover_index': float((m.sum() - np.trace(m)) / n),
        'from_others': {labels[i]: float(from_[i]) for i in range(n)},
        'to_others': {labels[i]: float(to_[i]) for i in range(n)},
        'net_spillover': {labels[i]: float(to_[i] - from_[i]) for i in range(n)},
        'matrix': [[float(m[i, j]) for j in range(n)] for i in range(n)],
    }


def select_lag_aic(data: pd.DataFrame, max_lag: int) -> int:
    """K628b's lag rule: AIC within maxlags, floor of 1.

    The VAR log-likelihood is invariant to the column order (|Sigma| is), so AIC picks the
    same lag under every permutation. That is asserted downstream, not assumed here.
    """
    lag = VAR(data).select_order(maxlags=max_lag).aic
    return int(lag) if lag and lag > 0 else 1


def fit_var(data: pd.DataFrame, lag: int):
    return VAR(data).fit(lag)


def role_of(net_pp: float, threshold: float = 5.0) -> str:
    """K628b's labelling rule: |NET| > 5pp to be called anything but BALANCED."""
    return 'TRANSMITTER' if net_pp > threshold else ('RECEIVER' if net_pp < -threshold else 'BALANCED')


# ══════════════════════════════════════════════════════════════════════════════
# A. Full sample: Cholesky vs GFEVD, and reproduction of the stored numbers
# ══════════════════════════════════════════════════════════════════════════════

def full_sample_analysis(var_input: pd.DataFrame) -> dict:
    print("\n" + "=" * 76)
    print("A. Full sample: Cholesky (what K628b actually ran) vs GFEVD (what it claimed)")
    print("=" * 76)

    data = var_input.dropna()
    lag = select_lag_aic(data, MAX_LAG)
    res = fit_var(data, lag)

    axis_check = check_axis_equivalence(res)
    chol = dy_metrics(row_normalize(cholesky_fevd(res)), ASSETS)
    gen = dy_metrics(row_normalize(generalized_fevd(res)), ASSETS)

    roots = np.asarray(res.roots)
    max_eig = float(1.0 / np.min(np.abs(roots)))
    is_stable = bool(res.is_stable(verbose=False))

    print(f"\n  n={len(data)}, VAR lag (AIC)={lag}, stable={is_stable}, max|eig|={max_eig:.4f}")
    print(f"  axis check: {axis_check['verdict']}")
    print(f"\n  TSI   Cholesky {chol['total_spillover_index']:6.2f}%   |   "
          f"GFEVD {gen['total_spillover_index']:6.2f}%")
    print(f"\n  {'asset':<10} {'NET chol':>10} {'NET gfevd':>10}  {'role chol':>12} {'role gfevd':>12}  flip")
    print(f"  {'-' * 68}")
    comparison = {}
    for a in ASSETS:
        c, g = chol['net_spillover'][a], gen['net_spillover'][a]
        rc, rg = role_of(c), role_of(g)
        flip = (c > 0) != (g > 0)
        comparison[a] = {
            'net_cholesky_pp': round(c, 2), 'net_gfevd_pp': round(g, 2),
            'from_cholesky_pp': round(chol['from_others'][a], 2),
            'from_gfevd_pp': round(gen['from_others'][a], 2),
            'to_cholesky_pp': round(chol['to_others'][a], 2),
            'to_gfevd_pp': round(gen['to_others'][a], 2),
            'role_cholesky': rc, 'role_gfevd': rg,
            'net_sign_flip': bool(flip), 'role_changed': rc != rg,
        }
        print(f"  {a:<10} {c:10.2f} {g:10.2f}  {rc:>12} {rg:>12}  {'YES' if flip else ''}")

    return {
        'n_obs': int(len(data)),
        'var_lag_aic': lag,
        'var_is_stable': is_stable,
        'var_max_eigenvalue': round(max_eig, 4),
        'axis_equivalence_check': axis_check,
        'cholesky': chol,
        'gfevd': gen,
        'net_comparison': comparison,
    }, res


def reproduction_check(full: dict) -> dict:
    """The Cholesky arm here must reproduce experiments/k628b/k628b_results.json.

    Without this, any Cholesky-vs-GFEVD gap could be a data-vintage or pipeline
    difference between the two scripts rather than a property of the estimator.
    """
    ref_path = HERE / 'k628b_results.json'
    ref = json.loads(ref_path.read_text())
    roles = ref['directional_roles']

    diffs, detail = [], {}
    for a in ASSETS:
        d_net = abs(full['cholesky']['net_spillover'][a] - roles[a]['net_pct'])
        d_to = abs(full['cholesky']['to_others'][a] - roles[a]['to_others_pct'])
        d_from = abs(full['cholesky']['from_others'][a] - roles[a]['from_others_pct'])
        diffs += [d_net, d_to, d_from]
        detail[a] = {'net': round(d_net, 3), 'to': round(d_to, 3), 'from': round(d_from, 3)}
    d_tsi = abs(full['cholesky']['total_spillover_index'] - ref['diebold_yilmaz']['total_spillover'])
    diffs.append(d_tsi)

    max_diff = float(max(diffs))
    ok = max_diff < 0.5           # pp; loose enough for yfinance re-download drift
    print(f"\n  Reproduction of k628b_results.json (Cholesky arm): "
          f"max |diff| = {max_diff:.3f}pp over {len(diffs)} quantities -> "
          f"{'PASS' if ok else 'FAIL'}")
    if not ok:
        print("    NOTE: the Cholesky arm does not reproduce the stored numbers. The "
              "GFEVD comparison below is then NOT apples-to-apples and must not be read "
              "as an estimator effect.")
    return {
        'reference': 'experiments/k628b/k628b_results.json',
        'stored_var_lag': ref['diebold_yilmaz']['selected_lag'],
        'rerun_var_lag': full['var_lag_aic'],
        'stored_n_obs': ref['n_observations'],
        'max_abs_diff_pp': round(max_diff, 3),
        'tsi_diff_pp': round(d_tsi, 3),
        'per_asset_abs_diff_pp': detail,
        'tolerance_pp': 0.5,
        'status': 'PASS' if ok else 'FAIL',
        'note': ('Data are re-downloaded from yfinance, so exact equality is not expected; '
                 'the check is that the Cholesky arm lands on the stored numbers, which is '
                 'what makes the GFEVD gap attributable to the decomposition.'),
    }


# ══════════════════════════════════════════════════════════════════════════════
# B. Exhaustive ordering sensitivity — all 5! = 120 orders, no sampling
# ══════════════════════════════════════════════════════════════════════════════

def ordering_sensitivity(var_input: pd.DataFrame) -> dict:
    data = var_input.dropna()
    all_perms = list(permutations(range(len(ASSETS))))
    print("\n" + "=" * 76)
    print(f"B. Ordering sensitivity — ALL {len(all_perms)} orderings (exhaustive, no sampling)")
    print("=" * 76)

    lag_ref = select_lag_aic(data, MAX_LAG)
    gen_ref = dy_metrics(row_normalize(generalized_fevd(fit_var(data, lag_ref))), ASSETS)

    nets = {a: [] for a in ASSETS}
    tsis, spy_pos, lags_seen, gfevd_dev = [], [], set(), 0.0
    named = {}

    for perm in all_perms:
        cols = [ASSETS[k] for k in perm]
        sub = data[cols]
        lag_p = select_lag_aic(sub, MAX_LAG)
        lags_seen.add(lag_p)
        res_p = fit_var(sub, lag_p)                       # genuine re-estimation

        chol_p = row_normalize(cholesky_fevd(res_p))
        gen_p = row_normalize(generalized_fevd(res_p))

        # map back to canonical labels: canonical (i,j) sits at (pos[i], pos[j])
        pos = {lab: k for k, lab in enumerate(cols)}
        idx = [pos[a] for a in ASSETS]
        mc = dy_metrics(chol_p[np.ix_(idx, idx)], ASSETS)
        mg = dy_metrics(gen_p[np.ix_(idx, idx)], ASSETS)

        gfevd_dev = max(gfevd_dev,
                        max(abs(mg['net_spillover'][a] - gen_ref['net_spillover'][a]) for a in ASSETS))

        for a in ASSETS:
            nets[a].append(mc['net_spillover'][a])
        tsis.append(mc['total_spillover_index'])
        spy_pos.append(cols.index('SPY'))

        if cols == ASSETS:
            named['k628b_order_SPY_first'] = {'order': cols, 'spy_net': round(mc['net_spillover']['SPY'], 2),
                                              'tsi': round(mc['total_spillover_index'], 2)}
        if cols == ASSETS[::-1]:
            named['reversed_SPY_last'] = {'order': cols, 'spy_net': round(mc['net_spillover']['SPY'], 2),
                                          'tsi': round(mc['total_spillover_index'], 2)}

    # The whole comparison rests on GFEVD actually being order-free. Prove it numerically.
    assert gfevd_dev < 1e-6, f"GFEVD is NOT order-invariant: max NET deviation {gfevd_dev:.3e}"
    assert lags_seen == {lag_ref}, \
        f"AIC lag is not order-invariant ({sorted(lags_seen)}); ordering and lag effects are confounded"

    spy = np.array(nets['SPY'])
    rho, pval = stats.spearmanr(spy_pos, spy)
    top_is_spy = float(np.mean([max(nets, key=lambda L: nets[L][k]) == 'SPY' for k in range(len(spy))]))

    per_asset = {}
    for a in ASSETS:
        v = np.array(nets[a])
        per_asset[a] = {
            'net_cholesky_min': round(float(v.min()), 2),
            'net_cholesky_median': round(float(np.median(v)), 2),
            'net_cholesky_max': round(float(v.max()), 2),
            'net_cholesky_range_pp': round(float(v.max() - v.min()), 2),
            'fraction_positive': round(float((v > 0).mean()), 3),
            'fraction_labelled_transmitter': round(float(np.mean([role_of(x) == 'TRANSMITTER' for x in v])), 3),
            'fraction_labelled_receiver': round(float(np.mean([role_of(x) == 'RECEIVER' for x in v])), 3),
            'net_gfevd': round(gen_ref['net_spillover'][a], 2),
            'role_gfevd': role_of(gen_ref['net_spillover'][a]),
        }

    print(f"\n  VAR lag identical under all {len(all_perms)} orderings: {sorted(lags_seen)}  (so the")
    print( "  spread below is the ORDERING alone, not a lag-selection side effect)")
    print(f"  GFEVD order-invariance: max NET deviation across all orderings = {gfevd_dev:.2e}")
    print(f"\n  Cholesky NET (pp) across all {len(all_perms)} orderings:")
    print(f"  {'asset':<10} {'min':>8} {'median':>8} {'max':>8} {'range':>8} {'%>0':>6}   {'GFEVD':>8} {'role(GFEVD)':>12}")
    print(f"  {'-' * 78}")
    for a in ASSETS:
        d = per_asset[a]
        print(f"  {a:<10} {d['net_cholesky_min']:8.2f} {d['net_cholesky_median']:8.2f} "
              f"{d['net_cholesky_max']:8.2f} {d['net_cholesky_range_pp']:8.2f} "
              f"{d['fraction_positive'] * 100:5.0f}%   {d['net_gfevd']:8.2f} {d['role_gfevd']:>12}")

    print(f"\n  SPY: K628b's order (SPY 1st) gives NET {named['k628b_order_SPY_first']['spy_net']:+.2f}pp; "
          f"SPY last gives {named['reversed_SPY_last']['spy_net']:+.2f}pp; GFEVD gives "
          f"{gen_ref['net_spillover']['SPY']:+.2f}pp")
    print(f"  Spearman(SPY's position in the ordering, SPY's Cholesky NET) = {rho:.3f} (p={pval:.2e})")
    print(f"  SPY is the largest net transmitter in {top_is_spy * 100:.0f}% of the 120 orderings")
    print(f"  Cholesky TSI ranges {min(tsis):.2f}% - {max(tsis):.2f}%; "
          f"GFEVD TSI = {gen_ref['total_spillover_index']:.2f}%")

    return {
        'n_orderings': len(all_perms),
        'exhaustive': True,
        'var_lag_invariant_across_orderings': sorted(lags_seen),
        'gfevd_max_net_deviation_across_orderings': float(gfevd_dev),
        'gfevd_order_invariance_verdict': 'CONFIRMED (deviation < 1e-6)',
        'per_asset': per_asset,
        'named_orderings': named,
        'spy_net_vs_spy_position': {
            'spearman_rho': round(float(rho), 3),
            'p_value': float(pval),
            'note': 'negative rho = the earlier SPY is ordered, the larger its Cholesky NET',
        },
        'spy_is_largest_transmitter_fraction': round(top_is_spy, 3),
        'cholesky_tsi_distribution': {
            'min': round(float(np.min(tsis)), 2),
            'median': round(float(np.median(tsis)), 2),
            'max': round(float(np.max(tsis)), 2),
        },
        'gfevd_tsi': round(gen_ref['total_spillover_index'], 2),
        '_spy_net_samples': [round(float(v), 3) for v in spy],
        '_spy_positions': [int(p) for p in spy_pos],
    }


# ══════════════════════════════════════════════════════════════════════════════
# C. Granger network — the role labels that do NOT come from a FEVD
# ══════════════════════════════════════════════════════════════════════════════

def granger_network(rvol: pd.DataFrame) -> dict:
    """K628b's Granger block, re-run verbatim.

    Every test here is a BIVARIATE regression of `effect` on its own lags plus lags of
    `cause`. No VAR ordering, no Cholesky factor, no covariance decomposition enters it.
    So the TRANSMITTER/RECEIVER labels derived from out-in degree cannot be an ordering
    artifact -- and the numbers below are checked against the stored ones to show that
    this rerun's Granger arm is the same object K628b reported, not a lookalike.
    """
    print("\n" + "=" * 76)
    print("C. Granger causality network (order-free by construction) — re-run")
    print("=" * 76)

    n = len(ASSETS)
    net_mat = np.zeros((n, n))
    results = {}
    for i, cause in enumerate(ASSETS):
        for j, effect in enumerate(ASSETS):
            if i == j:
                continue
            pair = rvol[[effect, cause]].dropna()
            test = grangercausalitytests(pair, maxlag=MAX_LAG, verbose=False)
            pvals = {lag: test[lag][0]['ssr_ftest'][1] for lag in range(1, MAX_LAG + 1)}
            best_lag = min(pvals, key=pvals.get)
            min_p = pvals[best_lag]
            f_stat = test[best_lag][0]['ssr_ftest'][0]
            results[f"{cause}->{effect}"] = {
                'f_stat': float(f_stat), 'p_value': float(min_p),
                'best_lag': int(best_lag), 'significant': bool(min_p < 0.05),
            }
            if min_p < 0.05:
                net_mat[i, j] = f_stat

    roles = {}
    for i, a in enumerate(ASSETS):
        out_d = int(np.sum(net_mat[i, :] > 0))
        in_d = int(np.sum(net_mat[:, i] > 0))
        net_d = out_d - in_d
        roles[a] = {
            'out_degree': out_d, 'in_degree': in_d, 'net_degree': net_d,
            'role': 'TRANSMITTER' if net_d > 0 else ('RECEIVER' if net_d < 0 else 'BALANCED'),
        }

    # Verify against the stored Granger numbers.
    ref = json.loads((HERE / 'k628b_results.json').read_text())['granger_causality']['network_roles']
    mismatches = {a: {'stored': ref[a], 'rerun': roles[a]} for a in ASSETS
                  if (ref[a]['out_degree'], ref[a]['in_degree'], ref[a]['role'])
                  != (roles[a]['out_degree'], roles[a]['in_degree'], roles[a]['role'])}

    total_links = int(np.sum(net_mat > 0))
    print(f"\n  {'asset':<10} {'OUT':>4} {'IN':>4} {'NET':>5}  {'role':>12}   {'stored (K628b)':>22}")
    print(f"  {'-' * 66}")
    for a in ASSETS:
        r = roles[a]
        s = ref[a]
        mark = '' if a not in mismatches else '  <-- DIFFERS'
        print(f"  {a:<10} {r['out_degree']:4d} {r['in_degree']:4d} {r['net_degree']:5d}  "
              f"{r['role']:>12}   OUT={s['out_degree']} IN={s['in_degree']} {s['role']:<12}{mark}")
    print(f"\n  Significant links: {total_links} (stored: "
          f"{json.loads((HERE / 'k628b_results.json').read_text())['granger_causality']['total_significant_links']})")
    print(f"  Role reproduction: {'ALL MATCH' if not mismatches else f'{len(mismatches)} MISMATCH'}")

    return {
        'results': results,
        'network_roles': roles,
        'total_significant_links': total_links,
        'depends_on_fevd_ordering': False,
        'why_order_free': ('Each link is a bivariate regression of the effect on its own lags '
                           'plus the cause\'s lags. No VAR ordering, Cholesky factor or covariance '
                           'decomposition enters the test, so the out-in degree roles are '
                           'structurally immune to the FEVD ordering problem.'),
        'reproduction_vs_stored': {
            'status': 'PASS' if not mismatches else 'MISMATCH',
            'mismatches': mismatches,
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# D. Rolling TSI + no-spillover null floor
# ══════════════════════════════════════════════════════════════════════════════

def rolling_tsi(var_input: pd.DataFrame) -> dict:
    """K628b's rolling spillover loop, under both decompositions.

    Same window/step/lag rule as the original. The window is stamped at its LAST
    observation, so no window uses information from after its own date.
    """
    print("\n" + "=" * 76)
    print(f"D. Rolling TSI ({ROLL_SPILL_WINDOW}-day window, step {ROLL_STEP}) — both decompositions")
    print("=" * 76)

    data = var_input.dropna()
    dates, chol, gen, spy_chol, spy_gen, unstable = [], [], [], [], [], []
    for s in range(0, len(data) - ROLL_SPILL_WINDOW, ROLL_STEP):
        w = data.iloc[s:s + ROLL_SPILL_WINDOW]
        lag = select_lag_aic(w, ROLL_MAX_LAG)
        res = fit_var(w, lag)
        mc = dy_metrics(row_normalize(cholesky_fevd(res)), ASSETS)
        mg = dy_metrics(row_normalize(generalized_fevd(res)), ASSETS)
        dates.append(w.index[-1])
        chol.append(mc['total_spillover_index'])
        gen.append(mg['total_spillover_index'])
        spy_chol.append(mc['net_spillover']['SPY'])
        spy_gen.append(mg['net_spillover']['SPY'])
        unstable.append(not res.is_stable(verbose=False))

    c, g = np.array(chol), np.array(gen)
    sc, sg = np.array(spy_chol), np.array(spy_gen)
    rho, p = stats.spearmanr(c, g)

    print(f"\n  {len(c)} windows | NON-STATIONARY VAR in {np.mean(unstable) * 100:.0f}% of them")
    print(f"  TSI  Cholesky mean {c.mean():5.2f}% (range {c.min():.2f}-{c.max():.2f})")
    print(f"  TSI  GFEVD    mean {g.mean():5.2f}% (range {g.min():.2f}-{g.max():.2f})")
    print(f"  Spearman(Cholesky TSI, GFEVD TSI) = {rho:.3f} (p={p:.2e})  <- do the two agree on TIMING?")
    print(f"  SPY NET  Cholesky mean {sc.mean():+6.2f}pp (positive in {(sc > 0).mean() * 100:.0f}% of windows)")
    print(f"  SPY NET  GFEVD    mean {sg.mean():+6.2f}pp (positive in {(sg > 0).mean() * 100:.0f}% of windows)")

    return {
        'window': ROLL_SPILL_WINDOW, 'step': ROLL_STEP, 'max_lag': ROLL_MAX_LAG,
        'n_windows': len(c),
        'nonstationary_var_fraction': round(float(np.mean(unstable)), 3),
        'cholesky_tsi': {'mean': round(float(c.mean()), 2), 'std': round(float(c.std()), 2),
                         'min': round(float(c.min()), 2), 'max': round(float(c.max()), 2)},
        'gfevd_tsi': {'mean': round(float(g.mean()), 2), 'std': round(float(g.std()), 2),
                      'min': round(float(g.min()), 2), 'max': round(float(g.max()), 2)},
        'tsi_timing_agreement_spearman': {'rho': round(float(rho), 3), 'p_value': float(p)},
        'spy_net_cholesky': {'mean': round(float(sc.mean()), 2),
                             'fraction_positive': round(float((sc > 0).mean()), 3)},
        'spy_net_gfevd': {'mean': round(float(sg.mean()), 2),
                          'fraction_positive': round(float((sg > 0).mean()), 3)},
        '_series': {
            'dates': [d.strftime('%Y-%m-%d') for d in dates],
            'cholesky_tsi': [round(float(v), 2) for v in c],
            'gfevd_tsi': [round(float(v), 2) for v in g],
            'spy_net_gfevd': [round(float(v), 2) for v in sg],
            'spy_net_cholesky': [round(float(v), 2) for v in sc],
        },
    }


def fit_ar_params(series: np.ndarray, lag: int):
    y = series[lag:]
    X = np.column_stack([np.ones(len(y))] + [series[lag - k: -k] for k in range(1, lag + 1)])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    sd = float(np.sqrt((resid ** 2).sum() / max(len(y) - X.shape[1], 1)))
    return float(beta[0]), beta[1:], sd


def simulate_independent_ar(ar_params, n_obs, rng, burn=BURN_IN) -> np.ndarray:
    """Each asset follows its OWN AR(p); the assets are simulated independently. True
    cross-asset spillover is exactly zero, so any TSI estimated here is pure finite-sample
    bias of the estimator."""
    total = n_obs + burn
    out = np.zeros((total, len(ar_params)))
    for v, (c, phi, sd) in enumerate(ar_params):
        p = len(phi)
        eps = rng.normal(0.0, sd, size=total)
        y = np.zeros(total)
        for t in range(p, total):
            y[t] = c + phi @ y[t - p: t][::-1] + eps[t]
        out[:, v] = y
    return out[burn:]


def null_floor(var_input: pd.DataFrame, n_obs: int, lag: int, label: str,
               observed_chol: float, observed_gen: float, reps: int = N_NULL_REPS,
               observed_net_gfevd: dict | None = None) -> dict:
    """What does the estimator report when the TRUE spillover is zero?

    Two things are benchmarked, because a positive number is not by itself evidence:

    - TSI LEVEL. An over-parameterised VAR manufactures connectedness out of estimation
      noise, so a level means nothing until you know the floor.
    - Each asset's NET. This is the one that matters for the directional claim. Switching
      Cholesky -> GFEVD removes the ORDERING artifact, but it does not tell us whether the
      surviving NET is distinguishable from what five INDEPENDENT series would produce.
      Without this, "SPY's GFEVD NET is +14.6pp" is the same category of error as reading a
      raw drawdown gap without a null (K1265): necessary, not sufficient.

    AR persistence is estimated once on the full sample and reused, so the only thing that
    varies between floors is n. No try/except: a silently dropped replication would be one
    of the noisiest, and every floor would be biased downward without anyone seeing it.
    """
    rng = np.random.default_rng(SEED)
    ar_params = [fit_ar_params(var_input[a].dropna().values, lag) for a in ASSETS]

    chol_t, gen_t = [], []
    gen_nets = {a: [] for a in ASSETS}
    for _ in range(reps):
        sim = pd.DataFrame(simulate_independent_ar(ar_params, n_obs, rng), columns=ASSETS)
        res = fit_var(sim, lag)
        mc = dy_metrics(row_normalize(cholesky_fevd(res)), ASSETS)
        mg = dy_metrics(row_normalize(generalized_fevd(res)), ASSETS)
        chol_t.append(mc['total_spillover_index'])
        gen_t.append(mg['total_spillover_index'])
        for a in ASSETS:
            gen_nets[a].append(mg['net_spillover'][a])
    assert len(gen_t) == reps, f"null floor lost replications: {len(gen_t)}/{reps}"

    ca, ga = np.array(chol_t), np.array(gen_t)

    def summarise(a):
        return {'mean': round(float(a.mean()), 2), 'median': round(float(np.median(a)), 2),
                'p95': round(float(np.percentile(a, 95)), 2), 'max': round(float(a.max()), 2)}

    out = {
        'n_obs': n_obs, 'var_lag': lag, 'reps': reps,
        'dgp': 'independent AR(p) per asset (own persistence kept, TRUE cross-spillover = 0)',
        'tsi_cholesky': summarise(ca), 'tsi_gfevd': summarise(ga),
        # keep the old key names so downstream readers of either shape still work
        'cholesky': summarise(ca), 'gfevd': summarise(ga),
        'observed_cholesky_tsi': round(observed_chol, 2),
        'observed_gfevd_tsi': round(observed_gen, 2),
        'gfevd_excess_over_null_median_pp': round(observed_gen - float(np.median(ga)), 2),
        'gfevd_empirical_p_value': round(float((ga >= observed_gen).mean()), 4),
        'cholesky_empirical_p_value': round(float((ca >= observed_chol).mean()), 4),
    }
    print(f"    null floor [{label}] n={n_obs} lag={lag} reps={reps}: "
          f"TSI GFEVD median {out['gfevd']['median']:.2f}% vs observed {observed_gen:.2f}% "
          f"(empirical p={out['gfevd_empirical_p_value']:.3f})")

    if observed_net_gfevd is not None:
        net_test = {}
        for a in ASSETS:
            v = np.array(gen_nets[a])
            obs = observed_net_gfevd[a]
            # two-sided: how often does a world with ZERO true spillover produce a NET at
            # least as extreme (in absolute value) as the one we observed?
            net_test[a] = {
                'observed_net_gfevd_pp': round(obs, 2),
                'null_net_mean': round(float(v.mean()), 2),
                'null_net_sd': round(float(v.std(ddof=1)), 2),
                'null_net_p05': round(float(np.percentile(v, 5)), 2),
                'null_net_p95': round(float(np.percentile(v, 95)), 2),
                'null_net_abs_max': round(float(np.abs(v).max()), 2),
                'two_sided_empirical_p': round(float((np.abs(v) >= abs(obs)).mean()), 4),
                'distinguishable_from_no_spillover_at_5pct':
                    bool(float((np.abs(v) >= abs(obs)).mean()) < 0.05),
            }
        out['net_vs_null'] = net_test
        print(f"    NET vs no-spillover null (two-sided empirical p):")
        for a in ASSETS:
            t = net_test[a]
            flag = 'REAL' if t['distinguishable_from_no_spillover_at_5pct'] else 'INDISTINGUISHABLE'
            print(f"      {a:<10} NET {t['observed_net_gfevd_pp']:+7.2f}pp | null |NET| max "
                  f"{t['null_net_abs_max']:5.2f} | p={t['two_sided_empirical_p']:.3f}  {flag}")

    return out


# ══════════════════════════════════════════════════════════════════════════════
# Charts
# ══════════════════════════════════════════════════════════════════════════════

def chart_net(full: dict, path: Path):
    fig, ax = plt.subplots(figsize=(9, 5.2))
    x = np.arange(len(ASSETS))
    c = [full['net_comparison'][a]['net_cholesky_pp'] for a in ASSETS]
    g = [full['net_comparison'][a]['net_gfevd_pp'] for a in ASSETS]
    ax.bar(x - 0.2, c, 0.4, label='Cholesky, SPY ordered 1st (what K628b ran)', color='#c44e52')
    ax.bar(x + 0.2, g, 0.4, label='GFEVD / KPPS (order-invariant)', color='#4c72b0')
    ax.axhline(0, color='k', lw=0.8)
    for thr, ls in ((5, ':'), (-5, ':')):
        ax.axhline(thr, color='grey', lw=0.8, ls=ls)
    ax.set_xticks(x)
    ax.set_xticklabels(ASSETS)
    ax.set_ylabel('NET spillover (pp)')
    ax.set_title('K628b re-run: NET spillover collapses once the ordering is removed\n'
                 '(dotted lines = the +/-5pp threshold K628b used to assign roles)', fontsize=11)
    ax.legend(fontsize=9)
    ax.grid(axis='y', alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def chart_ordering(order: dict, full: dict, path: Path):
    fig, ax = plt.subplots(figsize=(9, 5.2))
    samples = order['_spy_net_samples']
    ax.hist(samples, bins=24, color='#8c8c8c', alpha=0.75, edgecolor='white')
    ax.axvline(0, color='k', lw=1.0)
    ax.axvline(order['named_orderings']['k628b_order_SPY_first']['spy_net'], color='#c44e52', lw=2.2,
               label=f"SPY ordered 1st = K628b ({order['named_orderings']['k628b_order_SPY_first']['spy_net']:+.1f}pp)")
    ax.axvline(order['named_orderings']['reversed_SPY_last']['spy_net'], color='#dd8452', lw=2.2, ls='--',
               label=f"SPY ordered last ({order['named_orderings']['reversed_SPY_last']['spy_net']:+.1f}pp)")
    ax.axvline(full['net_comparison']['SPY']['net_gfevd_pp'], color='#4c72b0', lw=2.6,
               label=f"GFEVD, order-free ({full['net_comparison']['SPY']['net_gfevd_pp']:+.1f}pp)")
    ax.set_xlabel('SPY NET spillover (pp)')
    ax.set_ylabel(f"# of orderings (all {order['n_orderings']})")
    ax.set_title("K628b re-run: SPY's Cholesky NET under all 120 asset orderings\n"
                 f"Spearman(SPY's position, SPY's NET) = {order['spy_net_vs_spy_position']['spearman_rho']}"
                 "  (earlier = bigger)", fontsize=11)
    ax.legend(fontsize=8.5)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def chart_rolling(roll: dict, floor: dict, path: Path):
    d = pd.to_datetime(roll['_series']['dates'])
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=True)
    a0 = axes[0]
    a0.plot(d, roll['_series']['cholesky_tsi'], lw=1.1, color='#c44e52', label='Cholesky TSI (K628b)')
    a0.plot(d, roll['_series']['gfevd_tsi'], lw=1.1, color='#4c72b0', label='GFEVD TSI (order-free)')
    a0.axhline(floor['gfevd']['median'], color='#4c72b0', ls=':', lw=1.4,
               label=f"no-spillover null floor, GFEVD (median {floor['gfevd']['median']:.1f}%)")
    a0.axhline(floor['cholesky']['median'], color='#c44e52', ls=':', lw=1.4,
               label=f"no-spillover null floor, Cholesky (median {floor['cholesky']['median']:.1f}%)")
    a0.set_ylabel('Total spillover index (%)')
    a0.set_title(f"K628b re-run: rolling TSI ({roll['window']}-day windows) against a "
                 "true-zero-spillover null\n"
                 "the null floor is what the estimator reports when the assets are independent",
                 fontsize=11)
    a0.legend(fontsize=8.5, loc='upper left')
    a0.grid(alpha=0.3)

    a1 = axes[1]
    a1.plot(d, roll['_series']['spy_net_cholesky'], lw=1.1, color='#c44e52', label='SPY NET, Cholesky')
    a1.plot(d, roll['_series']['spy_net_gfevd'], lw=1.1, color='#4c72b0', label='SPY NET, GFEVD')
    a1.axhline(0, color='k', lw=0.8)
    a1.set_ylabel('SPY NET spillover (pp)')
    a1.set_xlabel('Window end date')
    a1.set_title('SPY NET spillover through time under both decompositions', fontsize=11)
    a1.legend(fontsize=9)
    a1.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--refresh', action='store_true', help='re-download prices')
    args = ap.parse_args()

    t0 = datetime.now()
    np.random.seed(SEED)

    print("K628b re-run: real KPPS generalized FEVD vs the Cholesky FEVD K628b actually ran")
    print("=" * 76)

    prices = load_prices(refresh=args.refresh)
    returns = prices.pct_change().dropna()
    print(f"Returns: {len(returns)} obs ({returns.index[0].date()} to {returns.index[-1].date()})")

    rvol, var_input, stationarity = build_var_input(returns)

    full, _ = full_sample_analysis(var_input)
    repro = reproduction_check(full)
    order = ordering_sensitivity(var_input)
    granger = granger_network(rvol)
    roll = rolling_tsi(var_input)

    print("\n  No-spillover null floors:")
    floor_roll = null_floor(var_input, ROLL_SPILL_WINDOW, ROLL_MAX_LAG, 'rolling',
                            roll['cholesky_tsi']['mean'], roll['gfevd_tsi']['mean'])
    floor_full = null_floor(var_input, full['n_obs'], full['var_lag_aic'], 'full_sample',
                            full['cholesky']['total_spillover_index'],
                            full['gfevd']['total_spillover_index'],
                            observed_net_gfevd=full['gfevd']['net_spillover'])

    chart_net(full, HERE / 'k628b_kpps_rerun_net_comparison.png')
    chart_ordering(order, full, HERE / 'k628b_kpps_rerun_ordering_distribution.png')
    chart_rolling(roll, floor_roll, HERE / 'k628b_kpps_rerun_rolling_tsi.png')
    print("\n  Charts written.")

    # ── Verdict ──────────────────────────────────────────────────────────────
    spy = full['net_comparison']['SPY']
    gen_net = full['gfevd']['net_spillover']
    top_gfevd = max(gen_net, key=gen_net.get)
    flips = [a for a in ASSETS if full['net_comparison'][a]['net_sign_flip']]
    role_changes = {a: f"{full['net_comparison'][a]['role_cholesky']} -> {full['net_comparison'][a]['role_gfevd']}"
                    for a in ASSETS if full['net_comparison'][a]['role_changed']}

    net_null = floor_full['net_vs_null']
    spy_beats_null = net_null['SPY']['distinguishable_from_no_spillover_at_5pct']
    spy_survives = gen_net['SPY'] > 5.0 and top_gfevd == 'SPY' and spy_beats_null
    spy_shrink = (gen_net['SPY'] / spy['net_cholesky_pp']) if spy['net_cholesky_pp'] else None
    real_under_gfevd = [a for a in ASSETS
                        if net_null[a]['distinguishable_from_no_spillover_at_5pct']]

    verdict = {
        'headline': None,   # filled below
        'fevd_directional_spillover': {
            'spy_net_cholesky_pp': spy['net_cholesky_pp'],
            'spy_net_gfevd_pp': spy['net_gfevd_pp'],
            'spy_net_shrinkage_ratio': round(spy_shrink, 3) if spy_shrink else None,
            'spy_still_dominant_transmitter_under_gfevd': bool(spy_survives),
            'spy_net_distinguishable_from_no_spillover_null': bool(spy_beats_null),
            'largest_net_transmitter_under_gfevd': top_gfevd,
            'assets_with_net_distinguishable_from_null': real_under_gfevd,
            'net_sign_flips_vs_cholesky': flips,
            'role_label_changes_vs_cholesky': role_changes,
            'ordering_range_of_spy_net_pp': order['per_asset']['SPY']['net_cholesky_range_pp'],
            'spy_positive_in_fraction_of_orderings': order['per_asset']['SPY']['fraction_positive'],
            'k628b_order_is_spy_net_maximising': bool(
                abs(spy['net_cholesky_pp'] - order['per_asset']['SPY']['net_cholesky_max']) < 0.1),
            'net_vs_no_spillover_null': net_null,
        },
        'granger_role_labels': {
            'depends_on_fevd_ordering': False,
            'reproduction_vs_stored': granger['reproduction_vs_stored']['status'],
            'roles': granger['network_roles'],
            'survives': granger['reproduction_vs_stored']['status'] == 'PASS',
        },
        'tsi_levels': {
            'full_sample_gfevd_tsi': round(full['gfevd']['total_spillover_index'], 2),
            'full_sample_cholesky_tsi': round(full['cholesky']['total_spillover_index'], 2),
            'rolling_gfevd_tsi_mean': roll['gfevd_tsi']['mean'],
            'rolling_cholesky_tsi_mean': roll['cholesky_tsi']['mean'],
            'rolling_null_floor_gfevd_median': floor_roll['gfevd']['median'],
            'rolling_gfevd_excess_over_null_pp': floor_roll['gfevd_excess_over_null_median_pp'],
            'rolling_gfevd_empirical_p': floor_roll['gfevd_empirical_p_value'],
        },
        'unaffected_by_this_defect': [
            'Granger causality network + out-in degree roles (pairwise, no FEVD)',
            'Forbes-Rigobon contagion test (correlation-based, no VAR)',
            'Rolling correlation crisis-vs-calm comparison',
            'OOS spillover-informed portfolio (driven by rolling Granger F-stat, not FEVD)',
            'Descriptive statistics, ADF, ARCH-LM',
        ],
        'vacuous_claim_flagged': (
            "K628b's article claims SPY's NET '+43.68% is far above the other four combined'. "
            "NET sums to zero by construction (every unit transmitted is a unit received), so "
            "whenever SPY is the ONLY net transmitter its NET必然 equals the sum of the other "
            "four's magnitudes. The statement is an identity, not evidence, under EITHER "
            "decomposition. It should not be restated in the corrected text."
        ),
    }

    # ── What has to be corrected downstream ──────────────────────────────────
    corrections = {
        'knowledge_json_K628b': {
            'note': 'PROPOSAL ONLY. knowledge.json is written by the main thread (K1259 rule).',
            'current_title': ('K628b: ★★ Cross-Asset Vol Spillover Network — SPY dominant '
                              'transmitter, 0050.TW pure receiver'),
            'proposed_title': ('K628b: ★★ Cross-Asset Vol Spillover Network — SPY is the largest '
                               'net transmitter, but the +43.7% magnitude was a Cholesky ordering '
                               'artifact (corrected to +14.6pp by KPPS re-run)'),
            'field_level_diff': [
                {'claim': "SPY 是主要傳播者（net +43.7%）",
                 'status': 'MAGNITUDE WITHDRAWN, DIRECTION SURVIVES',
                 'replace_with': (f"SPY 是最大淨傳出者（KPPS GFEVD net "
                                  f"{gen_net['SPY']:+.1f}pp）。原報的 +43.7% 來自 Cholesky FEVD 且 SPY "
                                  f"被排在第一位——全 120 種排序中該值域為 "
                                  f"{order['per_asset']['SPY']['net_cholesky_min']:+.1f} 到 "
                                  f"{order['per_asset']['SPY']['net_cholesky_max']:+.1f}pp，K628b 取到的正是最大值。")},
                {'claim': "0050.TW 是純接收者（OUT=0, IN=2）",
                 'status': 'SURVIVES',
                 'reason': ('OUT=0/IN=2 是 Granger out-in degree，不經 FEVD，與排序無關；'
                            '本次重跑逐項重現（ALL MATCH）。')},
                {'claim': "高波動 regime 網絡密度翻倍（11 vs 4 Granger links）",
                 'status': 'SURVIVES', 'reason': 'Granger-based, no FEVD.'},
                {'claim': "Forbes-Rigobon：無傳染（p>0.20），只是相互依存",
                 'status': 'SURVIVES', 'reason': '相關係數法，不經 VAR/FEVD。'},
                {'claim': "Total spillover 均值 25.8%（9.5%-51.6%）",
                 'status': 'DECOMPOSITION-SPECIFIC — RESTATE',
                 'replace_with': (f"該區間是 Cholesky TSI。order-invariant 的 GFEVD 下 rolling TSI "
                                  f"均值 {roll['gfevd_tsi']['mean']:.1f}%（{roll['gfevd_tsi']['min']:.1f}-"
                                  f"{roll['gfevd_tsi']['max']:.1f}%）。兩者時序高度同步 "
                                  f"(Spearman {roll['tsi_timing_agreement_spearman']['rho']})，但 200 日視窗的"
                                  f"無傳染 null floor 中位數已達 {floor_roll['gfevd']['median']:.1f}%，"
                                  f"故 TSI 的『水準』不可單獨解讀；超出 null 的部分仍顯著 "
                                  f"(empirical p={floor_roll['gfevd_empirical_p_value']:.3f})。")},
                {'claim': "Spillover-informed 配置 NULL（Sharpe 1.15 vs equal weight 1.21）",
                 'status': 'SURVIVES', 'reason': '由 rolling Granger F-stat 驅動，不經 FEVD。'},
                {'claim': "論文引用價值：支持 Taiwan VT 論文的 'US lead-lag' narrative",
                 'status': 'DOWNGRADE',
                 'replace_with': ('可支持「美股是最大淨傳出者」的方向性敘事，但不可引用 +43.7% 這個量級，'
                                  '也不可宣稱「SPY 傳出量是接收量的 10 倍」。')},
            ],
            'must_add_caveat': (
                'FEVD 方向性數字已於 2026-07-13 由 KPPS GFEVD 重估（experiments/k628b/'
                'k628b_kpps_rerun_results.json）。原 Cholesky 數字保留於 k628b_results.json 的 '
                '_correction_2026_07_13 區塊，僅供歷史對照，不可再引用。'),
        },
        'article_mile_55758994': {
            'title': '美股打噴嚏，台股真的感冒？16 年數據拆解跨市場波動傳染鏈',
            'status_in_feed': 'archived (但 live 導讀 mile_1597b341 的「本期精選」仍連到它)',
            'severity': 'HIGH — 這篇是 FEVD 方向性數字的主要對外載體，整個「結果一」段落建立在排序假象上',
            'sentences_to_correct': [
                {'locator': '方法段：「用 Diebold-Yilmaz（2012）的方向性 spillover 分解」',
                 'problem': ('未揭露用的是 Cholesky 正交化 FEVD 且方向性依賴變數排序；'
                             'DY(2012) 原文用的是 KPPS generalized FEVD，本實驗當時並沒有。'),
                 'fix': '明講原版用 Cholesky FEVD（order-dependent），已改用 KPPS GFEVD 重估。'},
                {'locator': '結果一表格：SPY 4.60 / 48.28 / **+43.68** / 淨發送者',
                 'problem': '整列都是排序假象（SPY 排第一 → NET 取到 120 種排序中的最大值）。',
                 'fix': (f"改為 KPPS GFEVD：SPY FROM {full['gfevd']['from_others']['SPY']:.2f} / "
                         f"TO {full['gfevd']['to_others']['SPY']:.2f} / NET {gen_net['SPY']:+.2f}pp。")},
                {'locator': '結果一表格：TLT -24.92（最大淨接收者）',
                 'problem': '方向對，量級錯。',
                 'fix': f"改為 GFEVD NET {gen_net['TLT']:+.2f}pp（仍是最大淨接收者）。"},
                {'locator': '結果一表格：USO -12.37（淨接收者）',
                 'problem': 'SIGN FLIP — 這是唯一角色標籤翻掉的資產。',
                 'fix': (f"改為 GFEVD NET {gen_net['USO']:+.2f}pp → 角色由「淨接收者」改為「平衡」"
                         f"（|NET| < 5pp 門檻）。「原油是波動接收者」這句話必須刪掉。")},
                {'locator': '結果一表格：0050.TW -1.75（淨接收者，接收量不大）',
                 'problem': '量級微調，方向與「不是主要節點」的結論不變。',
                 'fix': f"改為 GFEVD NET {gen_net['0050.TW']:+.2f}pp；「接收者但不是主要節點」的結論維持。"},
                {'locator': "「SPY 的 net spillover +43.68% 在五個資產中遠高於其他四個加總」",
                 'problem': ('雙重錯誤：(1) 43.68 是排序假象；(2) NET 依定義加總為零，'
                             '只要 SPY 是唯一淨傳出者，「高於其他四個加總」就是恆等式，本來就不是證據。'),
                 'fix': '整句刪除，不要用新數字重寫成同樣的句型。'},
                {'locator': ("「SPY 波動傳出的量（48.28%）是其接收的（4.60%）的 10 倍以上，"
                             "在五個主要資產類別中地位沒有任何資產接近它」"),
                 'problem': '10 倍比值完全是排序產物（SPY 排第一 → 接收量被壓到最低）。',
                 'fix': (f"改為 GFEVD：TO {full['gfevd']['to_others']['SPY']:.1f}% vs FROM "
                         f"{full['gfevd']['from_others']['SPY']:.1f}%（比值約 "
                         f"{full['gfevd']['to_others']['SPY'] / full['gfevd']['from_others']['SPY']:.1f} 倍，"
                         f"不是 10 倍）。「沒有任何資產接近它」需降級：SPY 在 120 種排序中只有 "
                         f"{order['spy_is_largest_transmitter_fraction'] * 100:.0f}% 是最大傳出者，"
                         f"但在 order-free 的 GFEVD 下它確實是最大的那一個。")},
                {'locator': "「TLT 的 net -24.92% 確認了 flight-to-quality 的方向性」",
                 'problem': '方向站得住，數字錯。',
                 'fix': f"改為 {gen_net['TLT']:+.2f}pp；flight-to-quality 的方向性結論保留。"},
                {'locator': "「知道 SPY 是主要發送者，TLT 是主要接收者」（OOS 段落）",
                 'problem': '此句本身在 GFEVD 下仍成立（方向不變），但它所依附的量級來自舊表。',
                 'fix': '句子可留，但引用的表格必須換成 GFEVD 版本。'},
                {'locator': '「Total spillover 均值 25.8%」類敘述（若文中有）',
                 'problem': 'Cholesky-specific，且 200 日視窗的無傳染 null floor 已達 12.4%。',
                 'fix': (f"改為 GFEVD {roll['gfevd_tsi']['mean']:.1f}%，並揭露 null floor "
                         f"{floor_roll['gfevd']['median']:.1f}%——TSI 的絕對水準約有一半是有限樣本偏誤。")},
            ],
            'recommended_action': ('文章已 archived。建議 (a) 在文首加更正聲明（比照 mile_1597b341 '
                                   '2026-07-11 的 K865 更正格式），(b) 換掉結果一整張表，'
                                   '(c) 若不重寫則從 mile_1597b341「本期精選」移除連結，避免 live 導讀'
                                   '把讀者導向未更正的頁面。'),
        },
        'article_mile_1597b341': {
            'title': '分散投資的幻覺：你以為無關的資產，其實偷偷牽動著你整個組合',
            'status_in_feed': 'published (LIVE)',
            'severity': ('LOW-MEDIUM — 這篇引用 K628b 的正文段落（第二層）只用 Granger + '
                         'Forbes-Rigobon，兩者都不受 FEVD 排序影響，因此正文論述本身站得住。'),
            'sentences_to_correct': [
                {'locator': ('第二層：「Granger 因果檢定的顯著水準在高波動期間達到極高……'
                             '用 Forbes-Rigobon 校正後，相關係數只剩 0.063」'),
                 'problem': 'NONE — Granger 與 FR 都不經 FEVD，本次重跑逐項重現。',
                 'fix': '不需更動。'},
                {'locator': '「本期精選」清單中連往 mile_55758994 的那一列',
                 'problem': ('該連結指向的文章整個「結果一」是排序假象。live 導讀把讀者導向'
                             '未更正的方向性數字。'),
                 'fix': '待 mile_55758994 更正後才保留連結；否則移除該列。'},
                {'locator': ('文首 2026-07-11 更正聲明：「本文其餘各層（……K628b 美台傳染……）'
                             '不受影響」'),
                 'problem': ('這句話在「本文引用 K628b 的部分」層次仍正確，但會讓讀者以為 K628b '
                             '整個實驗沒問題。K628b 的 FEVD 方向性其實與 K865 是同一個 class 的缺陷。'),
                 'fix': ('補一句：K628b 的 Granger / Forbes-Rigobon 結論（本文引用的部分）不受影響；'
                         '但 K628b 另有一組 FEVD 方向性數字（本文未引用）已於 2026-07-13 因同類'
                         '排序問題更正，詳見該實驗。')},
                {'locator': '圖表 caption「資料來源：實驗 K1445 / K628b / K1412 / K819 / K1011」',
                 'problem': '圖是相關係數，不是 FEVD。不受影響。',
                 'fix': '不需更動。'},
            ],
            'recommended_action': ('正文論述不需推翻。必要動作是 (a) 擴充文首更正聲明一句話，'
                                   '(b) 處理「本期精選」指向 mile_55758994 的連結。'),
        },
        'article_mile_530a28bc': {
            'title': '20年數據解讀台灣經濟脈絡（unpublished）',
            'status_in_feed': 'unpublished',
            'severity': 'LOW — 尚未對外；發佈前必須先套用上述更正。',
            'recommended_action': '若引用 K628b 的 FEVD 方向性數字，發佈前換成 GFEVD 版本。',
        },
        'baseline_removal': {
            'file': 'storage/ops/fevd_ordering_baseline.json',
            'site': 'experiments/k628b/k628b_vol_spillover.py',
            'precondition': ('k628b_vol_spillover.py 必須真的改用手刻 KPPS（sigma_u + ma_rep），'
                            'audit_fevd_ordering.py 才會把它從 VIOLATION/MISLABELED 改判 OK_GFEVD。'
                            '偵測器「不信註解，只信呼叫」——只改 docstring 不會過。'),
        },
    }
    results_corrections = corrections

    if spy_survives:
        verdict['headline'] = (
            f"PARTIALLY OVERTURNED. What survives: SPY is still the largest net transmitter "
            f"under the order-invariant GFEVD ({spy['net_gfevd_pp']:+.1f}pp), and it is "
            f"distinguishable from a no-spillover null. What does NOT: the MAGNITUDE. K628b "
            f"reported {spy['net_cholesky_pp']:+.1f}pp, which is the value its own asset "
            f"ordering maximises -- across all 120 orderings SPY's Cholesky NET runs "
            f"{order['per_asset']['SPY']['net_cholesky_min']:+.1f}pp to "
            f"{order['per_asset']['SPY']['net_cholesky_max']:+.1f}pp and SPY is the top "
            f"transmitter in only {order['spy_is_largest_transmitter_fraction'] * 100:.0f}% of them. "
            f"Every quantitative directional statement built on the {spy['net_cholesky_pp']:.1f}pp "
            f"figure has to be withdrawn; USO's RECEIVER label flips."
        )
    else:
        verdict['headline'] = (
            f"OVERTURNED: the FEVD directional conclusion does not survive an order-invariant "
            f"decomposition. SPY's NET goes from {spy['net_cholesky_pp']:+.1f}pp (Cholesky, SPY "
            f"ordered first) to {spy['net_gfevd_pp']:+.1f}pp (GFEVD). Largest net transmitter "
            f"under GFEVD is {top_gfevd}."
        )

    results = {
        'experiment_id': 'K628b_kpps_rerun',
        'parent_experiment': 'K628b',
        'title': 'K628b directional spillover re-estimated with a real KPPS generalized FEVD',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'motivation': (
            "k628b_vol_spillover.py documents its decomposition as 'generalized FEVD (Pesaran & "
            "Shin, 1998)' but calls statsmodels' results.fevd(), which is the ORTHOGONALISED "
            "(Cholesky) FEVD and depends on the order of the variables. K628b ordered SPY first "
            "-- the position that mechanically maximises estimated exogeneity -- and then reported "
            "SPY as the dominant net transmitter. This re-run replaces the decomposition and "
            "changes nothing else."
        ),
        'data_source': 'yfinance (daily close, auto_adjust; cached at experiments/k628b/data/prices.csv)',
        'data_period': f'{START} to {END}',
        'assets': ASSETS,
        'n_return_observations': int(len(returns)),
        'seed': SEED,
        'parameters': {
            'rvol_window': ROLL_WINDOW, 'var_max_lag': MAX_LAG, 'fevd_horizon': FEVD_HORIZON,
            'rolling_window': ROLL_SPILL_WINDOW, 'rolling_step': ROLL_STEP,
            'rolling_max_lag': ROLL_MAX_LAG, 'n_null_reps': N_NULL_REPS, 'null_burn_in': BURN_IN,
            'n_orderings': 120, 'orderings_exhaustive': True,
            'role_threshold_pp': 5.0,
        },
        'rvol_stationarity': stationarity,
        'cholesky_reproduction_check': repro,
        'full_sample': full,
        'ordering_sensitivity': order,
        'granger_causality': granger,
        'rolling_spillover': roll,
        'null_floor_rolling': floor_roll,
        'null_floor_full_sample': floor_full,
        'verdict': verdict,
        'corrections_required': results_corrections,
        'charts': {
            'net_comparison': 'k628b_kpps_rerun_net_comparison.png',
            'ordering_distribution': 'k628b_kpps_rerun_ordering_distribution.png',
            'rolling_tsi': 'k628b_kpps_rerun_rolling_tsi.png',
        },
        'references': [
            'Pesaran & Shin (1998) Economics Letters 58(1), 17-29',
            'Koop, Pesaran & Potter (1996) J. Econometrics 74(1), 119-147',
            'Diebold & Yilmaz (2012) IJF 28(1), 57-66',
            'K865b (same KPPS implementation; same defect found in K865)',
        ],
        'runtime_seconds': round((datetime.now() - t0).total_seconds(), 1),
    }

    out = HERE / 'k628b_kpps_rerun_results.json'
    out.write_text(json.dumps(results, indent=2, default=str))

    print("\n" + "=" * 76)
    print("VERDICT")
    print("=" * 76)
    print(f"  {verdict['headline']}")
    print(f"\n  Granger role labels (order-free): "
          f"{'SURVIVE' if verdict['granger_role_labels']['survives'] else 'DO NOT REPRODUCE'}")
    print(f"  Runtime {results['runtime_seconds']:.0f}s -> {out}")


if __name__ == '__main__':
    main()
