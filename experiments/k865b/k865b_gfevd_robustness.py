"""
K865b: Ordering robustness of the K865 "SPY is the volatility hub" conclusion.

Motivation
----------
K865's FEVD axis bug was fixed on 2026-07-11 (docs/error_log.md). The corrected
conclusion is "SPY is a NET TRANSMITTER in all five windows". But that conclusion
rests on statsmodels' *orthogonalised* (Cholesky) FEVD, which is **ordering
dependent** -- and SPY happens to sit first in the asset list. Variables ordered
first are mechanically more likely to be estimated as exogenous transmitters.
Diebold & Yilmaz (2012) use the *generalized* FEVD of Koop-Pesaran-Potter (1996)
and Pesaran-Shin (1998) precisely to avoid this.

Until the network is re-estimated with an order-invariant decomposition, the
SPY-hub claim cannot be made. This experiment does exactly that, plus two
diagnostics the original never ran.

What this script does
---------------------
A. GFEVD (KPPS) re-run of all five windows; NET spillover compared entry-by-entry
   against the Cholesky numbers currently in experiments/k865/k865_results.json.
B. Ordering-permutation sensitivity of the *Cholesky* estimator: >=50 random
   asset orderings (seed 42), VAR genuinely re-fitted on the permuted columns each
   time, mapped back to canonical labels. Turns "ordering might be driving this"
   from a worry into a measured distribution.
C. Rolling-window over-parameterisation diagnostic: K865's rolling design is
   VAR(5) x 7 vars on a 63-obs window = 36 parameters per equation (0.57
   params/obs). Four (window, lag) settings are compared, and level vs trend
   agreement is quantified with Spearman / Kendall statistics.
D. **No-spillover null floor.** Over-parameterised VARs manufacture connectedness
   out of estimation noise, so a TSI *level* is not interpretable on its own, and
   two windows with different sample sizes are not directly comparable. For every
   window and every rolling setting we simulate independent AR(p) series (own
   persistence preserved, zero true cross-dependence, seed 42, 200 reps) and
   estimate the TSI the same estimator would report when the true answer is 0.
   This gives a bias floor and an empirical p-value for the observed TSI.

Hard rules applied (.claude/rules/experiments.md)
-------------------------------------------------
- No lookahead: this is an in-sample network description, not a forecast. Windows
  are cut by date; each window's VAR is estimated on that window's data only.
- Seed: np.random.seed / np.random.default_rng(42) for every stochastic routine
  (permutations, AR null simulation). No unseeded randomness anywhere.
- GFEVD rows do NOT sum to 1 before normalisation (shocks are not orthogonalised);
  every normalised matrix is asserted to have unit row sums (tol 1e-8).
- Cholesky FEVD slice is decomp[:, -1, :] with a shape assert (2026-07-11 gate).

References
----------
- Diebold, F.X. & Yilmaz, K. (2012). "Better to Give than to Receive: Predictive
  Directional Measurement of Volatility Spillovers." IJF 28(1), 57-66.
- Pesaran, H.H. & Shin, Y. (1998). "Generalized Impulse Response Analysis in
  Linear Multivariate Models." Economics Letters 58(1), 17-29.
- Koop, G., Pesaran, M.H. & Potter, S.M. (1996). "Impulse Response Analysis in
  Nonlinear Multivariate Models." Journal of Econometrics 74(1), 119-147.
- K865 (Cholesky baseline being tested), K7 / K356 (prior SPY-hub evidence),
  K1025_v3 (same KPPS implementation, crypto-fear paper).
"""

import argparse
import json
import warnings
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.tsa.api import VAR

warnings.filterwarnings('ignore')

HERE = Path(__file__).resolve().parent
SEED = 42

# ── Configuration (mirrors K865 exactly so the Cholesky arm reproduces it) ──
ASSETS = ['SPY', 'QQQ', 'GLD', 'TLT', 'EEM', 'CL=F', 'BTC-USD']
LABELS = ['SPY', 'QQQ', 'GLD', 'TLT', 'EEM', 'OIL', 'BTC']
START_DATE = '2020-01-01'
END_DATE = '2026-04-05'
RV_WINDOW = 22
VAR_LAGS = 5
FEVD_HORIZON = 10

WINDOWS = {
    'covid_crisis': ('2020-01-02', '2020-06-30'),
    'post_covid_recovery': ('2020-07-01', '2021-12-31'),
    'rate_hike': ('2022-01-01', '2023-06-30'),
    'calm_2024_25': ('2024-01-01', '2026-02-28'),
    'tariff_crisis_extended': ('2025-10-01', '2026-04-04'),
}

# (window, lag) settings for the rolling diagnostic.
#   params per equation = n_vars * lag + 1
ROLLING_CONFIGS = [
    (63, 5),    # K865's setting: 36 params / 63 obs = 0.57
    (126, 2),   # 15 params / 126 obs = 0.12
    (252, 2),   # 15 params / 252 obs = 0.06
    (252, 5),   # 36 params / 252 obs = 0.14  -- isolates lag from window
]
ROLLING_STEP = 5
N_PERMUTATIONS = 50
N_NULL_REPS = 200


# ══════════════════════════════════════════════════════════════════════
# Data
# ══════════════════════════════════════════════════════════════════════

def load_prices(refresh: bool = False) -> pd.DataFrame:
    """Download (or load cached) close prices. Cached so re-runs are exact."""
    cache = HERE / 'data' / 'prices.csv'
    if cache.exists() and not refresh:
        prices = pd.read_csv(cache, index_col=0, parse_dates=True)
        print(f"Loaded cached prices: {len(prices)} obs "
              f"({prices.index[0].date()} to {prices.index[-1].date()})")
        return prices

    import yfinance as yf
    print("Downloading prices from yfinance...")
    data = {}
    for asset, label in zip(ASSETS, LABELS):
        df = yf.download(asset, start=START_DATE, end=END_DATE, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data[label] = df['Close']
        print(f"  {label}: {len(df)} obs")

    prices = pd.DataFrame(data).ffill().dropna()
    prices.to_csv(cache)
    print(f"Combined: {len(prices)} obs -> cached at {cache}")
    return prices


def compute_rv(prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """22-day realized vol (annualised), then z-scored per asset (as in K865)."""
    log_ret = np.log(prices / prices.shift(1))
    rv_raw = (log_ret.rolling(RV_WINDOW).std() * np.sqrt(252)).dropna()
    rv_std = (rv_raw - rv_raw.mean()) / rv_raw.std()
    return rv_std, rv_raw


# ══════════════════════════════════════════════════════════════════════
# The two variance decompositions
# ══════════════════════════════════════════════════════════════════════

def cholesky_fevd(res, horizon: int = FEVD_HORIZON) -> np.ndarray:
    """Orthogonalised (Cholesky) FEVD -- the K865 estimator. ORDER DEPENDENT.

    statsmodels' ``decomp`` is (n, horizon, n): axis 0 = decomposed variable i,
    axis 1 = horizon step, axis 2 = shock source j. The DY table is the n x n
    matrix at the FINAL horizon, i.e. ``decomp[:, -1, :]``. The shape assert is
    the 2026-07-11 gate (see scripts/tests/test_fevd_shape.py).
    """
    decomp = res.fevd(horizon).decomp
    n = decomp.shape[0]
    assert decomp.shape == (n, horizon, n), (
        f"unexpected FEVD shape {decomp.shape}, expected ({n}, {horizon}, {n})"
    )
    return decomp[:, -1, :]


def generalized_fevd(res, horizon: int = FEVD_HORIZON) -> np.ndarray:
    """KPPS generalized FEVD (Koop-Pesaran-Potter 1996; Pesaran-Shin 1998).

        theta_ij(H) = sigma_jj^-1 * sum_h (e_i' A_h Sigma e_j)^2
                                  / sum_h (e_i' A_h Sigma A_h' e_i)

    Shocks are NOT orthogonalised, so the result is invariant to the ordering of
    the variables -- which is the whole point of running it. Rows do not sum to 1
    before normalisation; the caller row-normalises (standard DY 2012 treatment).

    Same implementation as experiments/k1025/k1025_v3.py (crypto-fear paper).
    """
    sigma = np.asarray(res.sigma_u)
    phi = res.ma_rep(maxn=horizon - 1)  # (horizon, n, n), phi[0] = I
    assert phi.shape[0] == horizon, f"ma_rep gave {phi.shape[0]} steps, expected {horizon}"

    sig_jj = np.diag(sigma)
    num = np.zeros_like(sigma)
    den = np.zeros(sigma.shape[0])
    for h in range(horizon):
        a_sigma = phi[h] @ sigma
        num += a_sigma ** 2                    # (i,j) = (e_i' A_h Sigma e_j)^2
        den += np.diag(a_sigma @ phi[h].T)     # (i)   = e_i' A_h Sigma A_h' e_i

    return (num / sig_jj[None, :]) / den[:, None]


def row_normalize(mat: np.ndarray) -> np.ndarray:
    """Normalise rows to sum to 1 and assert it. Required for GFEVD; harmless for
    Cholesky (whose rows already sum to ~1)."""
    out = mat / mat.sum(axis=1, keepdims=True)
    assert np.allclose(out.sum(axis=1), 1.0, atol=1e-8), (
        f"row sums are not 1: {out.sum(axis=1)}"
    )
    return out


def dy_metrics(theta_norm: np.ndarray, labels: list[str]) -> dict:
    """Diebold-Yilmaz connectedness measures from a row-normalised FEVD table.

    Row i = share of i's forecast-error variance from each shock j.
    FROM_i = what i RECEIVES (row ex-diagonal); TO_j = what j TRANSMITS (column
    ex-diagonal); NET = TO - FROM, in percentage points. TSI = off-diagonal / n.
    """
    n = theta_norm.shape[0]
    m = theta_norm * 100.0
    off_diag = m.sum() - np.trace(m)
    from_ = m.sum(axis=1) - np.diag(m)
    to_ = m.sum(axis=0) - np.diag(m)
    return {
        'total_spillover_index': float(off_diag / n),
        'from_others': {labels[i]: float(from_[i]) for i in range(n)},
        'to_others': {labels[i]: float(to_[i]) for i in range(n)},
        'net_spillover': {labels[i]: float(to_[i] - from_[i]) for i in range(n)},
        'matrix': [[float(m[i, j]) for j in range(n)] for i in range(n)],
    }


def fit_var(data: pd.DataFrame, lag: int):
    """Fit a VAR with a fixed lag order (no IC selection -- K865 uses ic=None)."""
    return VAR(data).fit(maxlags=lag, ic=None)


def tsi_only(theta_norm: np.ndarray) -> float:
    n = theta_norm.shape[0]
    m = theta_norm * 100.0
    return float((m.sum() - np.trace(m)) / n)


def stability(res) -> tuple[bool, float]:
    """Is the fitted VAR stable, and what is the largest companion eigenvalue?

    An FEVD off a NON-stationary VAR is not a variance share in the usual sense:
    the h-step forecast error variance is exploding, so the h=10 decomposition is
    describing a diverging object. Credit: flagged by the Codex review, which
    checked ``is_stable()`` on every rolling fit and found the 63-obs setting
    fails it most of the time. Reported per window and per rolling setting below.
    """
    roots = np.asarray(res.roots)                 # roots of the char. polynomial
    max_mod = float(1.0 / np.min(np.abs(roots)))  # largest companion eigenvalue
    return bool(res.is_stable(verbose=False)), max_mod


# ══════════════════════════════════════════════════════════════════════
# A. Five windows: Cholesky vs GFEVD
# ══════════════════════════════════════════════════════════════════════

def analyse_windows(rv: pd.DataFrame) -> dict:
    print("\n" + "=" * 72)
    print("A. Cholesky vs GFEVD across the five windows")
    print("=" * 72)

    out = {}
    for wname, (ws, we) in WINDOWS.items():
        wdata = rv.loc[(rv.index >= ws) & (rv.index <= we)]
        n_obs = len(wdata)
        lag = min(VAR_LAGS, n_obs // 15)          # identical rule to K865
        res = fit_var(wdata, lag)

        chol = dy_metrics(row_normalize(cholesky_fevd(res)), LABELS)
        gen = dy_metrics(row_normalize(generalized_fevd(res)), LABELS)
        is_stable, max_eig = stability(res)

        params_per_eq = len(LABELS) * lag + 1
        out[wname] = {
            'period': f"{ws} to {we}",
            'n_obs': n_obs,
            'var_lag': lag,
            'params_per_equation': params_per_eq,
            'params_per_obs': round(params_per_eq / n_obs, 3),
            'var_is_stable': is_stable,
            'var_max_eigenvalue': round(max_eig, 4),
            'cholesky': chol,
            'gfevd': gen,
            'net_comparison': {
                lab: {
                    'net_cholesky': round(chol['net_spillover'][lab], 2),
                    'net_gfevd': round(gen['net_spillover'][lab], 2),
                    'sign_flip': (chol['net_spillover'][lab] > 0) != (gen['net_spillover'][lab] > 0),
                }
                for lab in LABELS
            },
        }
        print(f"\n  {wname}  (n={n_obs}, lag={lag}, {params_per_eq} params/eq "
              f"= {params_per_eq / n_obs:.2f}/obs, VAR stable={is_stable} "
              f"max|eig|={max_eig:.3f})")
        print(f"    TSI   Cholesky {chol['total_spillover_index']:6.2f}%  |  "
              f"GFEVD {gen['total_spillover_index']:6.2f}%")
        print(f"    {'asset':<6} {'NET chol':>9} {'NET gfevd':>10}  flip")
        for lab in LABELS:
            c = chol['net_spillover'][lab]
            g = gen['net_spillover'][lab]
            flip = 'YES' if (c > 0) != (g > 0) else ''
            print(f"    {lab:<6} {c:9.1f} {g:10.1f}  {flip}")
    return out


def validate_against_k865(win: dict) -> dict:
    """The Cholesky arm here must reproduce experiments/k865/k865_results.json.

    Without this, a GFEVD-vs-Cholesky gap could just be a data or pipeline
    difference between the two scripts rather than a property of the estimator.
    """
    ref_path = HERE.parent / 'k865' / 'k865_results.json'
    if not ref_path.exists():
        return {'status': 'k865_results.json not found', 'checked': False}

    ref = json.loads(ref_path.read_text())
    diffs = []
    for wname, w in win.items():
        r = ref['window_analysis'][wname]['spillover']
        diffs.append(abs(w['cholesky']['total_spillover_index'] - r['total_spillover_index']))
        for lab in LABELS:
            diffs.append(abs(w['cholesky']['net_spillover'][lab] - r['net_spillover'][lab]))

    max_diff = float(max(diffs))
    print(f"\n  K865 reproduction check: max |diff| over TSI + NET = {max_diff:.4f} "
          f"({len(diffs)} quantities)")
    assert max_diff < 0.05, (
        f"Cholesky arm does NOT reproduce K865 (max diff {max_diff:.3f}); the "
        f"GFEVD comparison would not be apples-to-apples."
    )
    return {'checked': True, 'n_quantities': len(diffs),
            'max_abs_diff': round(max_diff, 4), 'tolerance': 0.05, 'status': 'PASS'}


# ══════════════════════════════════════════════════════════════════════
# B. Ordering-permutation sensitivity of the Cholesky estimator
# ══════════════════════════════════════════════════════════════════════

def permutation_sensitivity(rv: pd.DataFrame) -> dict:
    """Re-FIT the VAR on each permuted column order and recompute the Cholesky
    FEVD. (Relabelling alone would be a no-op; the VAR is genuinely re-estimated
    so the Cholesky factor of Sigma is taken in the permuted order.)

    Also verifies -- numerically, not by assertion of faith -- that the GFEVD is
    invariant to the same permutations.
    """
    print("\n" + "=" * 72)
    print(f"B. Cholesky ordering sensitivity ({N_PERMUTATIONS} random orders, seed {SEED})")
    print("=" * 72)

    rng = np.random.default_rng(SEED)
    n = len(LABELS)

    # Named orders first, then the random draws.
    identity = list(range(n))                      # SPY first  (= K865's order)
    reverse = list(range(n))[::-1]                 # SPY last
    perms = [('identity_SPY_first', identity), ('reversed_SPY_last', reverse)]
    seen = {tuple(identity), tuple(reverse)}
    while len(perms) - 2 < N_PERMUTATIONS:
        p = tuple(rng.permutation(n))
        if p in seen:
            continue
        seen.add(p)
        perms.append((f'random_{len(perms) - 1:02d}', list(p)))

    out = {}
    for wname, (ws, we) in WINDOWS.items():
        wdata = rv.loc[(rv.index >= ws) & (rv.index <= we)]
        lag = min(VAR_LAGS, len(wdata) // 15)

        # GFEVD reference (order-invariant by construction; verified below).
        gen_ref = dy_metrics(row_normalize(generalized_fevd(fit_var(wdata, lag))), LABELS)

        nets = {lab: [] for lab in LABELS}          # Cholesky NET per permutation
        tsis = []
        spy_position = []
        named = {}
        gfevd_dev = 0.0

        for pname, perm in perms:
            cols = [LABELS[k] for k in perm]
            res_p = fit_var(wdata[cols], lag)       # genuine re-estimation

            chol_p = row_normalize(cholesky_fevd(res_p))
            gen_p = row_normalize(generalized_fevd(res_p))

            # map back: entry for canonical (i, j) sits at (pos[i], pos[j])
            pos = {lab: k for k, lab in enumerate(cols)}
            idx = [pos[lab] for lab in LABELS]
            chol_c = chol_p[np.ix_(idx, idx)]
            gen_c = gen_p[np.ix_(idx, idx)]

            mc = dy_metrics(chol_c, LABELS)
            mg = dy_metrics(gen_c, LABELS)

            # GFEVD must be numerically identical to the canonical-order GFEVD
            dev = max(abs(mg['net_spillover'][lab] - gen_ref['net_spillover'][lab])
                      for lab in LABELS)
            gfevd_dev = max(gfevd_dev, dev)

            for lab in LABELS:
                nets[lab].append(mc['net_spillover'][lab])
            tsis.append(mc['total_spillover_index'])
            spy_position.append(cols.index('SPY'))
            if pname in ('identity_SPY_first', 'reversed_SPY_last'):
                named[pname] = {
                    'order': cols,
                    'spy_net': round(mc['net_spillover']['SPY'], 2),
                    'tsi': round(mc['total_spillover_index'], 2),
                }

        assert gfevd_dev < 1e-6, (
            f"GFEVD is NOT order-invariant in {wname}: max NET deviation {gfevd_dev:.3e}"
        )

        spy = np.array(nets['SPY'])
        rho, pval = stats.spearmanr(spy_position, spy)
        out[wname] = {
            'n_orderings': len(perms),
            'gfevd_max_net_deviation_across_orderings': float(gfevd_dev),
            'gfevd_spy_net': round(gen_ref['net_spillover']['SPY'], 2),
            'spy_net_cholesky_distribution': {
                'min': round(float(spy.min()), 2),
                'p05': round(float(np.percentile(spy, 5)), 2),
                'median': round(float(np.median(spy)), 2),
                'p95': round(float(np.percentile(spy, 95)), 2),
                'max': round(float(spy.max()), 2),
                'mean': round(float(spy.mean()), 2),
                'std': round(float(spy.std(ddof=1)), 2),
                'fraction_positive': round(float((spy > 0).mean()), 3),
                'fraction_top_transmitter': round(float(np.mean([
                    max(nets, key=lambda L: nets[L][k]) == 'SPY' for k in range(len(spy))
                ])), 3),
            },
            'spy_net_vs_spy_position': {
                'spearman_rho': round(float(rho), 3),
                'p_value': round(float(pval), 6),
                'note': 'negative rho = the earlier SPY is ordered, the larger its Cholesky NET',
            },
            'named_orderings': named,
            'tsi_distribution': {
                'min': round(float(np.min(tsis)), 2),
                'median': round(float(np.median(tsis)), 2),
                'max': round(float(np.max(tsis)), 2),
            },
            'all_assets_fraction_positive': {
                lab: round(float((np.array(nets[lab]) > 0).mean()), 3) for lab in LABELS
            },
            '_spy_net_samples': [round(float(v), 3) for v in spy],
        }

        d = out[wname]['spy_net_cholesky_distribution']
        print(f"\n  {wname}: SPY NET (Cholesky) over {len(perms)} orderings")
        print(f"    min {d['min']:.1f} | median {d['median']:.1f} | max {d['max']:.1f} "
              f"| positive in {d['fraction_positive'] * 100:.0f}% of orderings")
        print(f"    SPY first {named['identity_SPY_first']['spy_net']:.1f}  vs  "
              f"SPY last {named['reversed_SPY_last']['spy_net']:.1f}  |  "
              f"GFEVD {out[wname]['gfevd_spy_net']:.1f}")
        print(f"    Spearman(SPY position, SPY NET) = {rho:.3f} (p={pval:.4f})")
        print(f"    GFEVD order-invariance check: max NET deviation {gfevd_dev:.2e}")

    return out


# ══════════════════════════════════════════════════════════════════════
# D. No-spillover null floor (used by both C and A)
# ══════════════════════════════════════════════════════════════════════

def fit_ar_params(series: np.ndarray, lag: int) -> tuple[float, np.ndarray, float]:
    """OLS AR(p) for one series: returns (const, phi[1..p], residual sd)."""
    y = series[lag:]
    X = np.column_stack([np.ones(len(y))] + [series[lag - k: -k] for k in range(1, lag + 1)])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    sd = float(np.sqrt((resid ** 2).sum() / max(len(y) - X.shape[1], 1)))
    return float(beta[0]), beta[1:], sd


def simulate_independent_ar(ar_params: list, n_obs: int, rng: np.random.Generator,
                            burn: int = 200) -> np.ndarray:
    """Simulate each asset's own AR(p) INDEPENDENTLY: own persistence preserved,
    true cross-asset spillover exactly zero. Any TSI estimated on this data is
    pure finite-sample bias of the estimator."""
    n_vars = len(ar_params)
    total = n_obs + burn
    out = np.zeros((total, n_vars))
    for v, (c, phi, sd) in enumerate(ar_params):
        p = len(phi)
        eps = rng.normal(0.0, sd, size=total)
        y = np.zeros(total)
        for t in range(p, total):
            # y[t-p:t][::-1] = [y_{t-1}, y_{t-2}, ..., y_{t-p}], aligned with phi[0..p-1]
            y[t] = c + phi @ y[t - p: t][::-1] + eps[t]
        out[:, v] = y
    return out[burn:]


def null_tsi_floor(rv_source: pd.DataFrame, n_obs: int, lag: int, label: str,
                   reps: int = N_NULL_REPS) -> dict:
    """Distribution of the estimated TSI when the TRUE TSI is 0."""
    rng = np.random.default_rng(SEED)
    ar_params = [fit_ar_params(rv_source[lab].values, lag) for lab in LABELS]

    # No try/except: a silently skipped replication would bias the floor downward
    # (the fits that fail are the noisiest ones) without anyone seeing it. If a fit
    # ever fails, the experiment stops rather than quietly reporting a biased number.
    chol_tsi, gen_tsi = [], []
    for _ in range(reps):
        sim = simulate_independent_ar(ar_params, n_obs, rng)
        res = fit_var(pd.DataFrame(sim, columns=LABELS), lag)
        chol_tsi.append(tsi_only(row_normalize(cholesky_fevd(res))))
        gen_tsi.append(tsi_only(row_normalize(generalized_fevd(res))))
    assert len(gen_tsi) == reps, f"null floor lost replications: {len(gen_tsi)}/{reps}"

    def summarise(vals):
        a = np.array(vals)
        return {
            'mean': round(float(a.mean()), 2),
            'median': round(float(np.median(a)), 2),
            'p95': round(float(np.percentile(a, 95)), 2),
            'max': round(float(a.max()), 2),
        }

    print(f"    null floor [{label}] n={n_obs} lag={lag} reps={len(chol_tsi)}: "
          f"Cholesky median {np.median(chol_tsi):.1f}%  GFEVD median {np.median(gen_tsi):.1f}%")
    return {
        'n_obs': n_obs,
        'var_lag': lag,
        'reps': len(chol_tsi),
        'dgp': 'independent AR(p) per asset (own persistence kept, true TSI = 0)',
        'cholesky': summarise(chol_tsi),
        'gfevd': summarise(gen_tsi),
        '_gfevd_samples': [round(float(v), 3) for v in gen_tsi],
        '_cholesky_samples': [round(float(v), 3) for v in chol_tsi],
    }


# ══════════════════════════════════════════════════════════════════════
# C. Rolling over-parameterisation diagnostic
# ══════════════════════════════════════════════════════════════════════

def rolling_tsi(rv: pd.DataFrame, window: int, lag: int) -> dict[str, pd.Series]:
    """Rolling TSI under both decompositions (one VAR fit serves both).

    The end-points are anchored to the LAST observation and stepped backwards, so
    every (window, lag) setting lands on the SAME dates wherever they overlap.
    (Anchoring to each config's own start instead would give the 63- and 252-obs
    settings disjoint date grids, and no pair could be compared at all.)
    """
    dates, gen, chol, stable = [], [], [], []
    ends = sorted(range(len(rv), window, -ROLLING_STEP))
    # No try/except: a skipped window would silently drop exactly the periods where
    # the VAR is worst behaved -- i.e. it would flatter the setting under test.
    for end in ends:
        res = fit_var(rv.iloc[end - window: end], lag)
        gen.append(tsi_only(row_normalize(generalized_fevd(res))))
        chol.append(tsi_only(row_normalize(cholesky_fevd(res))))
        stable.append(stability(res)[0])
        dates.append(rv.index[end - 1])          # window ends at index end-1: no lookahead
    assert len(gen) == len(ends), f"rolling lost windows: {len(gen)}/{len(ends)}"
    return {
        'gfevd': pd.Series(gen, index=dates, name=f'gfevd_{window}_{lag}'),
        'cholesky': pd.Series(chol, index=dates, name=f'cholesky_{window}_{lag}'),
        'unstable_fraction': float(1.0 - np.mean(stable)) if stable else float('nan'),
    }


def rolling_diagnostic(rv: pd.DataFrame) -> tuple[dict, dict]:
    print("\n" + "=" * 72)
    print("C/D. Rolling over-parameterisation diagnostic + no-spillover null floor")
    print("=" * 72)

    n_vars = len(LABELS)
    series, meta = {}, {}
    for window, lag in ROLLING_CONFIGS:
        key = f'w{window}_l{lag}'
        both = rolling_tsi(rv, window, lag)
        s_gen, s_chol = both['gfevd'], both['cholesky']
        series[key] = both

        ppe = n_vars * lag + 1
        # Monotone trend of the GFEVD rolling TSI against time.
        t = np.arange(len(s_gen))
        rho_t, p_t = stats.spearmanr(t, s_gen.values)
        floor = null_tsi_floor(rv, window, lag, key)

        meta[key] = {
            'window': window,
            'var_lag': lag,
            'params_per_equation': ppe,
            'params_per_obs': round(ppe / window, 3),
            'n_windows': len(s_gen),
            'gfevd_tsi': {
                'mean': round(float(s_gen.mean()), 2),
                'std': round(float(s_gen.std()), 2),
                'min': round(float(s_gen.min()), 2),
                'max': round(float(s_gen.max()), 2),
            },
            'cholesky_tsi': {
                'mean': round(float(s_chol.mean()), 2),
                'std': round(float(s_chol.std()), 2),
            },
            'null_floor': floor,
            'gfevd_mean_minus_null_median': round(
                float(s_gen.mean()) - floor['gfevd']['median'], 2),
            'time_trend_spearman': {'rho': round(float(rho_t), 3), 'p_value': round(float(p_t), 6)},
            'unstable_var_fraction': round(both['unstable_fraction'], 3),
        }
        print(f"  {key}: {ppe} params/eq over {window} obs = {ppe / window:.2f}/obs | "
              f"GFEVD TSI mean {s_gen.mean():.1f}% (null median "
              f"{floor['gfevd']['median']:.1f}%) | trend rho {rho_t:+.2f} | "
              f"NON-STATIONARY VAR in {both['unstable_fraction'] * 100:.0f}% of windows")

    # Level and trend agreement between settings (GFEVD arm).
    keys = list(series.keys())
    pairwise = {}
    for a in range(len(keys)):
        for b in range(a + 1, len(keys)):
            ka, kb = keys[a], keys[b]
            sa, sb = series[ka]['gfevd'], series[kb]['gfevd']
            common = sa.index.intersection(sb.index)
            if len(common) < 20:
                continue
            rho, p = stats.spearmanr(sa.loc[common].values, sb.loc[common].values)
            pairwise[f'{ka}_vs_{kb}'] = {
                'n_common_dates': len(common),
                'spearman_rho': round(float(rho), 3),
                'p_value': round(float(p), 8),
                'level_gap_pp': round(float(sa.loc[common].mean() - sb.loc[common].mean()), 2),
            }

    # Do the settings agree on the REGIME RANKING (the only thing a level-free
    # reading could still claim)?
    regime_means = {}
    for key in keys:
        s = series[key]['gfevd']
        regime_means[key] = {}
        for wname, (ws, we) in WINDOWS.items():
            sel = s.loc[(s.index >= ws) & (s.index <= we)]
            regime_means[key][wname] = round(float(sel.mean()), 2) if len(sel) >= 3 else None

    common_regimes = [w for w in WINDOWS
                      if all(regime_means[k][w] is not None for k in keys)]
    regime_rank_agreement = {}
    for a in range(len(keys)):
        for b in range(a + 1, len(keys)):
            ka, kb = keys[a], keys[b]
            va = [regime_means[ka][w] for w in common_regimes]
            vb = [regime_means[kb][w] for w in common_regimes]
            tau, p = stats.kendalltau(va, vb)
            regime_rank_agreement[f'{ka}_vs_{kb}'] = {
                'kendall_tau': round(float(tau), 3), 'p_value': round(float(p), 6)}

    print("\n  Pairwise Spearman of rolling GFEVD TSI (level agreement):")
    for k, v in pairwise.items():
        print(f"    {k}: rho={v['spearman_rho']:+.2f} (n={v['n_common_dates']}), "
              f"level gap {v['level_gap_pp']:+.1f}pp")
    print(f"\n  Regime means (GFEVD rolling TSI, regimes with >=3 windows): {common_regimes}")
    for k in keys:
        print(f"    {k}: " + ", ".join(
            f"{w}={regime_means[k][w]}" for w in common_regimes))

    diag = {
        'configs': meta,
        'pairwise_spearman_gfevd': pairwise,
        'regime_means_gfevd': regime_means,
        'regime_rank_agreement_kendall': regime_rank_agreement,
        'regimes_compared': common_regimes,
    }
    return diag, series


# ══════════════════════════════════════════════════════════════════════
# Charts
# ══════════════════════════════════════════════════════════════════════

def chart_net_comparison(win: dict, path: Path):
    names = list(WINDOWS.keys())
    fig, axes = plt.subplots(1, len(names), figsize=(21, 4.6), sharey=True)
    x = np.arange(len(LABELS))
    for ax, wname in zip(axes, names):
        cmp = win[wname]['net_comparison']
        c = [cmp[l]['net_cholesky'] for l in LABELS]
        g = [cmp[l]['net_gfevd'] for l in LABELS]
        ax.bar(x - 0.2, c, 0.4, label='Cholesky (K865)', color='#c44e52')
        ax.bar(x + 0.2, g, 0.4, label='GFEVD (KPPS)', color='#4c72b0')
        ax.axhline(0, color='k', lw=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(LABELS, rotation=45)
        ax.set_title(f"{wname}\n(n={win[wname]['n_obs']})", fontsize=10)
        ax.grid(axis='y', alpha=0.3)
    axes[0].set_ylabel('NET spillover (pp)')
    axes[0].legend(fontsize=9)
    fig.suptitle('K865b (a) NET spillover: Cholesky vs order-invariant GFEVD', fontsize=13)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def chart_permutation(perm: dict, path: Path):
    names = list(WINDOWS.keys())
    fig, axes = plt.subplots(1, len(names), figsize=(21, 4.6))
    for ax, wname in zip(axes, names):
        d = perm[wname]
        samples = d['_spy_net_samples']
        ax.hist(samples, bins=15, color='#8c8c8c', alpha=0.75, edgecolor='white')
        ax.axvline(0, color='k', lw=1.0)
        ax.axvline(d['named_orderings']['identity_SPY_first']['spy_net'],
                   color='#c44e52', lw=2, label='SPY ordered 1st (K865)')
        ax.axvline(d['named_orderings']['reversed_SPY_last']['spy_net'],
                   color='#dd8452', lw=2, ls='--', label='SPY ordered last')
        ax.axvline(d['gfevd_spy_net'], color='#4c72b0', lw=2.5, label='GFEVD (order-free)')
        ax.set_title(f"{wname}\n{d['spy_net_cholesky_distribution']['fraction_positive'] * 100:.0f}%"
                     " of orderings positive", fontsize=10)
        ax.set_xlabel('SPY NET (pp)')
        ax.grid(alpha=0.3)
    axes[0].set_ylabel(f"# of orderings (n={perm[names[0]]['n_orderings']})")
    axes[0].legend(fontsize=8)
    fig.suptitle('K865b (b) SPY NET spillover under random Cholesky orderings (seed 42)',
                 fontsize=13)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def chart_rolling(series: dict, diag: dict, path: Path):
    fig, ax = plt.subplots(figsize=(14, 6))
    colors = ['#c44e52', '#4c72b0', '#55a868', '#8172b3']
    for (key, sd), col in zip(series.items(), colors):
        s = sd['gfevd']
        m = diag['configs'][key]
        ax.plot(s.index, s.values, lw=1.2, color=col,
                label=f"{key} ({m['params_per_obs']:.2f} params/obs), "
                      f"mean {m['gfevd_tsi']['mean']:.0f}%")
        ax.axhline(m['null_floor']['gfevd']['median'], color=col, ls=':', lw=1.2, alpha=0.8)
    ax.set_ylabel('Rolling total spillover index (GFEVD, %)')
    ax.set_title('K865b (c) Rolling TSI under four (window, lag) settings\n'
                 'dotted = no-spillover null floor (independent AR(p), true TSI = 0)',
                 fontsize=12)
    ax.legend(fontsize=9, loc='upper left')
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


# ══════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--refresh', action='store_true', help='re-download prices')
    args = ap.parse_args()

    t0 = datetime.now()
    np.random.seed(SEED)   # belt and braces; all routines use default_rng(SEED)

    print("K865b: Ordering robustness of the SPY-hub conclusion (GFEVD / KPPS)")
    print("=" * 72)

    prices = load_prices(refresh=args.refresh)
    rv, rv_raw = compute_rv(prices)
    rv = rv[LABELS].dropna()
    print(f"RV: {len(rv)} obs, {rv.index[0].date()} to {rv.index[-1].date()}")

    win = analyse_windows(rv)
    k865_check = validate_against_k865(win)
    perm = permutation_sensitivity(rv)

    # Null floor for the five full-window estimates (A), so that the TSI LEVELS
    # and the cross-regime TSI comparison can be read against the bias they carry.
    print("\n  Null floor for the five windows:")
    win_null = {}
    for wname, w in win.items():
        floor = null_tsi_floor(rv, w['n_obs'], w['var_lag'], wname)
        obs = w['gfevd']['total_spillover_index']
        samples = np.array(floor['_gfevd_samples'])
        win_null[wname] = {
            **{k: v for k, v in floor.items() if not k.startswith('_')},
            'observed_gfevd_tsi': round(obs, 2),
            'excess_over_null_median_pp': round(obs - floor['gfevd']['median'], 2),
            'empirical_p_value': round(float((samples >= obs).mean()), 4),
        }
    win_null['_note'] = ('empirical_p_value = share of no-spillover simulations whose '
                         'estimated TSI is at least the observed TSI')

    diag, series = rolling_diagnostic(rv)

    # Charts
    chart_net_comparison(win, HERE / 'assets' / 'k865b_net_comparison.png')
    chart_permutation(perm, HERE / 'assets' / 'k865b_spy_ordering_distribution.png')
    chart_rolling(series, diag, HERE / 'assets' / 'k865b_rolling_tsi_sensitivity.png')
    print("\nCharts written to assets/")

    # ── Verdict on the SPY-hub claim ──
    spy_gfevd_net = {w: round(win[w]['gfevd']['net_spillover']['SPY'], 2) for w in WINDOWS}
    spy_chol_net = {w: round(win[w]['cholesky']['net_spillover']['SPY'], 2) for w in WINDOWS}
    spy_positive_all = all(v > 0 for v in spy_gfevd_net.values())
    spy_top_gfevd = {
        w: max(win[w]['gfevd']['net_spillover'], key=win[w]['gfevd']['net_spillover'].get)
        for w in WINDOWS
    }
    verdict = {
        'spy_net_gfevd_by_window': spy_gfevd_net,
        'spy_net_cholesky_by_window': spy_chol_net,
        'spy_net_transmitter_in_all_windows_under_gfevd': bool(spy_positive_all),
        'largest_net_transmitter_under_gfevd': spy_top_gfevd,
        'spy_is_largest_transmitter_in_all_windows': all(v == 'SPY' for v in spy_top_gfevd.values()),
        'ordering_permutation_fraction_positive': {
            w: perm[w]['spy_net_cholesky_distribution']['fraction_positive'] for w in WINDOWS
        },
    }

    elapsed = (datetime.now() - t0).total_seconds()
    results = {
        'experiment_id': 'K865b',
        'title': 'Ordering robustness of the K865 SPY-hub conclusion (GFEVD / KPPS)',
        'parent_experiment': 'K865',
        'timestamp': datetime.now().isoformat(),
        'data_source': 'yfinance (daily close; cached at experiments/k865b/data/prices.csv)',
        'assets': LABELS,
        'period': f"{rv.index[0].date()} to {rv.index[-1].date()}",
        'total_observations': int(len(rv)),
        'parameters': {
            'rv_window': RV_WINDOW,
            'var_lags': VAR_LAGS,
            'fevd_horizon': FEVD_HORIZON,
            'rolling_configs': [{'window': w, 'lag': l} for w, l in ROLLING_CONFIGS],
            'rolling_step': ROLLING_STEP,
            'n_permutations': N_PERMUTATIONS,
            'n_null_reps': N_NULL_REPS,
            'seed': SEED,
        },
        'methodology': (
            'Diebold-Yilmaz (2012) connectedness on 22-day realized vol (z-scored), '
            'VAR(p) with fixed lag, FEVD horizon 10. Two decompositions: (i) Cholesky '
            'orthogonalised FEVD (order-dependent; the K865 estimator) and (ii) KPPS '
            'generalized FEVD (Pesaran-Shin 1998; order-invariant, row-normalised). '
            'Ordering sensitivity measured by re-estimating the VAR under 52 asset '
            'orderings. TSI levels benchmarked against a no-spillover null (independent '
            'AR(p) simulation, 200 reps, seed 42).'
        ),
        'k865_reproduction_check': k865_check,
        'window_analysis': win,
        'window_null_floor': win_null,
        'ordering_permutation': perm,
        'rolling_diagnostic': diag,
        'rolling_tsi_series_gfevd': {
            key: {d.strftime('%Y-%m-%d'): round(float(v), 2) for d, v in sd['gfevd'].items()}
            for key, sd in series.items()
        },
        'verdict': verdict,
        'runtime_seconds': round(elapsed, 1),
        'references': [
            'Diebold & Yilmaz (2012) IJF 28(1), 57-66',
            'Pesaran & Shin (1998) Economics Letters 58(1), 17-29',
            'Koop, Pesaran & Potter (1996) J. Econometrics 74(1), 119-147',
            'K865 (Cholesky baseline)', 'K7', 'K356', 'K1025_v3 (same KPPS code)',
        ],
    }

    out = HERE / 'k865b_results.json'
    with open(out, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print("\n" + "=" * 72)
    print("VERDICT")
    print("=" * 72)
    print(f"  SPY NET (GFEVD) by window: {spy_gfevd_net}")
    print(f"  SPY net transmitter in ALL windows under GFEVD: {spy_positive_all}")
    print(f"  SPY largest net transmitter under GFEVD in all windows: "
          f"{verdict['spy_is_largest_transmitter_in_all_windows']}")
    print(f"\n  Runtime {elapsed:.0f}s -> {out}")


if __name__ == '__main__':
    main()
