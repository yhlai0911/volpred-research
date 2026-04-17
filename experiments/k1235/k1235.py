"""
K1235: Paper 9 garch-x-vix FEZ + STOXX50E K949 spec bundle experiment

Purpose: Generate canonical t-statistics for the K1232-flagged no-source values:
    - FEZ t=3.45 (Paper 9 Table 6 line 526 + Abstract + Conclusion)
    - STOXX50E t=3.64 (Paper 9 Table 6 line 525)

Root cause (per K1232): K949 spec (MF-GJR log-exp, OOS 2016-2025, W=2000,
refit=21) was not applied to these 2 tickers. K1235 reruns K949 spec verbatim
on FEZ and ^STOXX50E to produce canonical numbers that can be compared against
paper-claimed values.

**IMPORTANT methodological caveat**: Paper 9 Table 6 was produced under the
A4f spec (tau = theta0 + theta1 * VIX^2, free omega, OOS 2019-2026, refit=63).
K949 spec differs: log-exp link, constrained omega (E[g]=1), OOS 2016-2025,
refit=21. We reuse K949 spec verbatim per task brief. Any MATCH/MISMATCH
verdict should therefore be interpreted as: "does K949 spec reproduce the
paper's claim, or does the paper need an erratum/spec clarification?"

K949 spec (verbatim copy):
  - Model: MF-GJR with tau_t = exp(theta0 + theta1 * log(VIX_t))
  - Short-run g_t: GJR(1,1,1), constrained (E[g_t] = 1 via intercept)
  - Parameters estimated jointly via MLE (L-BFGS-B)
  - Benchmarks: GARCH(1,1), GJR(1,1,1) via arch package
  - Window W = 2000 trading days
  - Refit every 21 days
  - OOS: 2016-01-01 to 2025-12-31
  - Loss: QLIKE on r^2
  - DM test: HAC-robust variance + Harvey (1997) small-sample correction
  - Seed: 42

Tickers:
  - FEZ (SPDR EURO STOXX 50 ETF) — directly flagged by K1232
  - ^STOXX50E (EURO STOXX 50 cash index) — directly flagged by K1232
    (probed: ^ESTX50 / ^SX5E delisted on yfinance; ^STOXX50E works)

Output:
  - k1235_results.json — per-ticker DM t (raw + Harvey) + QLIKE + p-value
  - k1235_qlike_timeseries.png — per-ticker QLIKE cumulative timeseries
  - k1235_dm_rolling.png — per-ticker DM rolling t-statistic
  - README.md — MATCH / MISMATCH / BORDERLINE verdict vs paper

Data source: yfinance (daily OHLC adjusted close, 2006-2025)

Lookahead protection:
  - Signal uses log(VIX_t) consistent with K949 (VIX_t IS lagged in the sense
    that sigma_{t+1}^2 is forecast using info up to end of t, and VIX_t is
    observed at end of t)
  - r_{t-1} used to update g_t -> forecast for r_t^2
  - No same-day signal * same-day return

Reproducibility:
  - np.random.seed(42) fixed
  - Numba JIT paths identical to K949
  - arch_model defaults identical to K949
"""

import numpy as np
import pandas as pd
import json
import warnings
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.optimize import minimize
from scipy.stats import spearmanr, norm
from arch import arch_model
from datetime import datetime
from numba import njit
from pathlib import Path

warnings.filterwarnings('ignore')
np.random.seed(42)

# ============================================================
# 1. Configuration (VERBATIM K949 SPEC)
# ============================================================
import yfinance as yf

# K1235 tickers (only the 2 flagged by K1232)
ASSETS = ['FEZ', '^STOXX50E']
ASSET_LABELS = {'FEZ': 'FEZ', '^STOXX50E': 'STOXX50E'}

START = '2006-01-01'       # Must be >= WINDOW+1 before OOS_START for rolling estimation
END = '2025-12-31'
OOS_START = '2016-01-01'   # K949 verbatim
WINDOW = 2000              # K949 verbatim
REFIT_EVERY = 21           # K949 verbatim

# Paper-claimed values (from main.tex line 525, 526)
PAPER_CLAIMS = {
    'FEZ': 3.45,
    '^STOXX50E': 3.64,
}

OUTPUT_DIR = Path(__file__).resolve().parent

# ============================================================
# 2. Data Download
# ============================================================
print("K1235: downloading data...")
price_data = {}
# Download VIX + both equity tickers
for ticker in ASSETS + ['^VIX']:
    df = yf.download(ticker, start=START, end=END, progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    price_data[ticker] = df['Close']
    print(f"  {ticker}: {len(df)} rows, range={df.index[0].date()}..{df.index[-1].date()}")

# Build aligned DataFrame
prices = pd.DataFrame(price_data)
prices = prices.ffill()

returns = {}
for asset in ASSETS:
    r = np.log(prices[asset] / prices[asset].shift(1)).dropna() * 100
    returns[asset] = r

vix = prices['^VIX']
log_vix = np.log(vix)

# ============================================================
# 3. MF-GJR Model (VERBATIM K949)
# ============================================================

@njit
def mf_gjr_negloglik_numba(params, returns_arr, log_vix_arr):
    """MF-GJR(VIX) negative log-likelihood (numba JIT). VERBATIM K949."""
    omega_g = params[0]
    alpha = params[1]
    gamma = params[2]
    beta = params[3]
    theta0 = params[4]
    theta1 = params[5]

    T = len(returns_arr)
    if T < 2:
        return 1e10

    if alpha < 0 or beta < 0 or gamma < 0:
        return 1e10
    if alpha + beta + gamma/2 >= 1.0:
        return 1e10
    if omega_g < 0.001 or omega_g > 5.0:
        return 1e10

    intercept = omega_g * (1.0 - alpha - beta - gamma/2.0)
    nll = 0.0
    g_prev = 1.0
    log2pi = 1.8378770664093453  # np.log(2*pi)

    for t in range(1, T):
        r_prev = returns_arr[t-1]
        tau_prev = np.exp(theta0 + theta1 * log_vix_arr[t-1])
        tau_t = np.exp(theta0 + theta1 * log_vix_arr[t])

        if tau_prev < 1e-8:
            tau_prev = 1e-8

        r2_scaled = (r_prev * r_prev) / tau_prev
        ind = 1.0 if r_prev < 0 else 0.0

        g_t = intercept + alpha * r2_scaled + gamma * r2_scaled * ind + beta * g_prev
        if g_t < 1e-8:
            g_t = 1e-8

        sigma2 = tau_t * g_t
        if sigma2 < 1e-8:
            sigma2 = 1e-8

        r_t = returns_arr[t]
        nll += 0.5 * (log2pi + np.log(sigma2) + r_t * r_t / sigma2)
        g_prev = g_t

    return nll


@njit
def mf_gjr_compute_g_series(params, returns_arr, log_vix_arr):
    """Compute full g series for a fitted model. VERBATIM K949."""
    omega_g = params[0]
    alpha = params[1]
    gamma = params[2]
    beta = params[3]
    theta0 = params[4]
    theta1 = params[5]

    T = len(returns_arr)
    g = np.ones(T)
    intercept = omega_g * (1.0 - alpha - beta - gamma/2.0)

    for t in range(1, T):
        r_prev = returns_arr[t-1]
        tau_prev = np.exp(theta0 + theta1 * log_vix_arr[t-1])
        if tau_prev < 1e-8:
            tau_prev = 1e-8
        r2_scaled = (r_prev * r_prev) / tau_prev
        ind = 1.0 if r_prev < 0 else 0.0
        g[t] = intercept + alpha * r2_scaled + gamma * r2_scaled * ind + beta * g[t-1]
        if g[t] < 1e-8:
            g[t] = 1e-8

    return g


def fit_mf_gjr(returns_arr, log_vix_arr):
    """Fit MF-GJR model with multiple starting points. VERBATIM K949."""
    _ = mf_gjr_negloglik_numba(np.array([1.0, 0.05, 0.05, 0.9, -0.5, 0.5]),
                                returns_arr[:10], log_vix_arr[:10])

    best_result = None
    best_nll = 1e10

    starts = [
        [1.0, 0.05, 0.05, 0.90, -0.5, 0.5],
        [1.0, 0.08, 0.10, 0.85, 0.0, 0.3],
        [1.0, 0.03, 0.07, 0.88, -1.0, 0.8],
        [1.0, 0.10, 0.05, 0.80, 0.5, 0.2],
    ]

    bounds = [(0.001, 5.0), (0.001, 0.3), (0.001, 0.5), (0.5, 0.999),
              (-5.0, 5.0), (-2.0, 3.0)]

    for x0 in starts:
        try:
            result = minimize(
                lambda p: mf_gjr_negloglik_numba(p, returns_arr, log_vix_arr),
                x0, method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 5000, 'ftol': 1e-10})
            if result.fun < best_nll:
                best_nll = result.fun
                best_result = result
        except Exception:
            continue

    return best_result


# ============================================================
# 4. OOS Loop (VERBATIM K949)
# ============================================================

def qlike_loss(sigma2_pred, r2_actual):
    mask = (sigma2_pred > 1e-10) & np.isfinite(r2_actual) & np.isfinite(sigma2_pred)
    s2 = sigma2_pred[mask]
    r2 = r2_actual[mask]
    return np.mean(r2/s2 + np.log(s2))


def run_oos_for_asset(asset, ret_series, vix_series, log_vix_series):
    label = ASSET_LABELS.get(asset, asset)
    print(f"\n{'='*60}")
    print(f"Processing {label} (ticker={asset})...")
    print(f"{'='*60}")

    common_idx = ret_series.index.intersection(log_vix_series.index)
    ret = ret_series.loc[common_idx].copy()
    lv = log_vix_series.loc[common_idx].copy()

    # drop any non-finite
    mask_finite = np.isfinite(ret.values) & np.isfinite(lv.values)
    ret = ret[mask_finite]
    lv = lv[mask_finite]

    oos_mask = ret.index >= OOS_START
    oos_dates = ret.index[oos_mask]

    if len(oos_dates) == 0:
        print(f"  No OOS data for {asset}")
        return None

    n_oos = len(oos_dates)
    print(f"  OOS period: {oos_dates[0].date()} to {oos_dates[-1].date()} ({n_oos} days)")
    print(f"  Total rows incl. IS: {len(ret)}")

    forecasts = {m: np.full(n_oos, np.nan) for m in ['GARCH', 'GJR', 'MF-GJR']}
    r2_actual = np.full(n_oos, np.nan)

    all_dates = ret.index
    oos_start_pos = np.where(all_dates >= OOS_START)[0][0]

    last_garch_params = None
    last_gjr_params = None
    last_mf_params = None
    last_garch_var = None
    last_gjr_var = None
    last_mf_g = 1.0

    ret_vals = ret.values
    lv_vals = lv.values

    for i in range(n_oos):
        t = oos_start_pos + i

        if t < WINDOW:
            continue

        r2_actual[i] = ret_vals[t] ** 2
        need_refit = (i == 0) or (i % REFIT_EVERY == 0)

        train_ret = ret_vals[t-WINDOW:t]
        train_lv = lv_vals[t-WINDOW:t]

        # GARCH(1,1)
        if need_refit:
            try:
                am = arch_model(pd.Series(train_ret), vol='Garch', p=1, q=1,
                              mean='Zero', dist='normal', rescale=False)
                res = am.fit(disp='off', show_warning=False)
                last_garch_params = (res.params['omega'], res.params['alpha[1]'], res.params['beta[1]'])
                last_garch_var = res.conditional_volatility.iloc[-1]**2
            except Exception:
                pass

        if last_garch_params is not None and last_garch_var is not None:
            omega, alpha, beta = last_garch_params
            r_prev = train_ret[-1]
            h = omega + alpha * r_prev**2 + beta * last_garch_var
            forecasts['GARCH'][i] = h
            last_garch_var = h

        # GJR(1,1,1)
        if need_refit:
            try:
                am = arch_model(pd.Series(train_ret), vol='Garch', p=1, o=1, q=1,
                              mean='Zero', dist='normal', rescale=False)
                res = am.fit(disp='off', show_warning=False)
                last_gjr_params = (res.params['omega'], res.params['alpha[1]'],
                                  res.params['gamma[1]'], res.params['beta[1]'])
                last_gjr_var = res.conditional_volatility.iloc[-1]**2
            except Exception:
                pass

        if last_gjr_params is not None and last_gjr_var is not None:
            omega, alpha, gamma, beta = last_gjr_params
            r_prev = train_ret[-1]
            ind = 1.0 if r_prev < 0 else 0.0
            h = omega + alpha * r_prev**2 + gamma * r_prev**2 * ind + beta * last_gjr_var
            forecasts['GJR'][i] = h
            last_gjr_var = h

        # MF-GJR(VIX)
        if need_refit:
            try:
                result = fit_mf_gjr(train_ret, train_lv)
                if result is not None and result.fun < 1e9:
                    last_mf_params = result.x
                    g_arr = mf_gjr_compute_g_series(last_mf_params, train_ret, train_lv)
                    last_mf_g = g_arr[-1]
            except Exception:
                pass

        if last_mf_params is not None:
            try:
                omega_g, al, gm, bt, th0, th1 = last_mf_params
                r_prev = train_ret[-1]
                tau_prev = np.exp(th0 + th1 * train_lv[-1])
                tau_next = np.exp(th0 + th1 * train_lv[-1])
                if tau_prev < 1e-8:
                    tau_prev = 1e-8
                r2_scaled = (r_prev**2) / tau_prev
                ind = 1.0 if r_prev < 0 else 0.0
                intercept = omega_g * (1 - al - bt - gm/2)
                g_next = intercept + al * r2_scaled + gm * r2_scaled * ind + bt * last_mf_g
                if g_next < 1e-8:
                    g_next = 1e-8
                sigma2_next = tau_next * g_next
                forecasts['MF-GJR'][i] = sigma2_next
                last_mf_g = g_next
            except Exception:
                pass

        if (i+1) % 500 == 0:
            print(f"  {label}: {i+1}/{n_oos} done")

    # Evaluation
    valid = np.isfinite(r2_actual)
    for m in forecasts:
        valid &= np.isfinite(forecasts[m])

    n_valid = int(np.sum(valid))
    print(f"  Valid observations: {n_valid}")

    if n_valid < 100:
        print(f"  Too few valid observations for {asset}")
        return None

    r2_v = r2_actual[valid]

    results = {}
    for m in ['GARCH', 'GJR', 'MF-GJR']:
        f_v = forecasts[m][valid]
        ql = qlike_loss(f_v, r2_v)
        rho, pval = spearmanr(f_v, r2_v)
        results[m] = {'QLIKE': float(ql), 'Spearman_rho': float(rho), 'Spearman_pval': float(pval)}
        print(f"  {m:10s}: QLIKE={ql:.4f}, Spearman rho={rho:.4f}")

    # DM test: MF-GJR vs GJR (MF-GJR is the tested model; positive t = MF-GJR better)
    d_mf = r2_v / forecasts['MF-GJR'][valid] + np.log(forecasts['MF-GJR'][valid])
    d_gjr = r2_v / forecasts['GJR'][valid] + np.log(forecasts['GJR'][valid])
    d = d_gjr - d_mf  # positive = MF-GJR better

    T = len(d)
    d_bar = float(np.mean(d))
    lag = int(T**(1/3))
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0.0
    for k in range(1, lag+1):
        w = 1 - k/(lag+1)
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        gamma_sum += 2 * w * gamma_k
    var_d = gamma_0 + gamma_sum
    se_d = np.sqrt(max(var_d, 1e-10) / T)
    dm_t = d_bar / se_d if se_d > 0 else 0

    # Harvey small-sample correction (h=1)
    # Harvey-Leybourne-Newbold (1997): t* = t * sqrt((T + 1 - 2h + h(h-1)/T) / T)
    # With h=1: t* = t * sqrt((T - 1 + 0) / T) approximately (simplified form)
    # K949 uses: t * sqrt((T + 1 - 2 + 1/T) / T) = t * sqrt((T - 1 + 1/T) / T)
    dm_t_harvey = dm_t * np.sqrt((T + 1 - 2 + 1/T) / T)
    # Two-sided p-value (large-T normal approx)
    dm_p = 2.0 * (1.0 - norm.cdf(abs(dm_t)))
    dm_p_harvey = 2.0 * (1.0 - norm.cdf(abs(dm_t_harvey)))

    results['DM_MFvsGJR'] = {
        't_stat': float(dm_t),
        't_harvey': float(dm_t_harvey),
        'p_value_raw': float(dm_p),
        'p_value_harvey': float(dm_p_harvey),
        'significant_harvey3': bool(abs(dm_t_harvey) > 3.0),
        'mean_loss_diff': float(d_bar),
        'hac_lag': int(lag),
        'n_effective': int(T)
    }

    print(f"  DM(MF-GJR vs GJR): t={dm_t:.3f}, t_harvey={dm_t_harvey:.3f}, "
          f"p_harvey={dm_p_harvey:.4f}, |t_harvey|>3.0: {abs(dm_t_harvey)>3.0}")

    # QLIKE improvement
    ql_garch = results['GARCH']['QLIKE']
    ql_gjr = results['GJR']['QLIKE']
    ql_mf = results['MF-GJR']['QLIKE']

    results['QLIKE_improvement'] = {
        'MF_vs_GARCH_pct': float((ql_garch - ql_mf) / abs(ql_garch) * 100),
        'MF_vs_GJR_pct': float((ql_gjr - ql_mf) / abs(ql_gjr) * 100),
    }

    if last_mf_params is not None:
        results['theta1_VIX_elasticity'] = float(last_mf_params[5])
        results['theta0'] = float(last_mf_params[4])
        results['mf_params'] = {
            'omega_g': float(last_mf_params[0]),
            'alpha': float(last_mf_params[1]),
            'gamma': float(last_mf_params[2]),
            'beta': float(last_mf_params[3]),
            'theta0': float(last_mf_params[4]),
            'theta1': float(last_mf_params[5])
        }

    results['n_oos'] = n_valid
    results['oos_period'] = f"{oos_dates[0].date()} to {oos_dates[-1].date()}"

    # Comparison vs paper claim
    claimed_t = PAPER_CLAIMS.get(asset)
    if claimed_t is not None:
        diff = dm_t_harvey - claimed_t
        pct_diff = (diff / claimed_t) * 100 if claimed_t != 0 else 0
        # Tolerance bands
        abs_diff = abs(diff)
        if abs_diff < 0.2:
            verdict = 'MATCH'
        elif abs_diff < 0.5:
            verdict = 'BORDERLINE'
        else:
            verdict = 'MISMATCH'
        results['paper_comparison'] = {
            'paper_claimed_t': float(claimed_t),
            'k1235_t_harvey': float(dm_t_harvey),
            'diff': float(diff),
            'pct_diff': float(pct_diff),
            'verdict': verdict,
            'tolerance_match_lt': 0.2,
            'tolerance_borderline_lt': 0.5,
            'note': 'Paper 9 Table 6 uses A4f spec (VIX^2, free omega, OOS 2019-2026, refit=63); '
                    'K1235 uses K949 spec (log-exp tau, constrained omega, OOS 2016-2025, refit=21). '
                    'Verdict reflects whether K949 spec alone is sufficient to reproduce the claim.'
        }
        print(f"  Paper claim t={claimed_t}, K1235 t_harvey={dm_t_harvey:.3f}, "
              f"diff={diff:+.3f} ({pct_diff:+.1f}%), verdict={verdict}")

    return results, forecasts, r2_actual, valid, oos_dates


# ============================================================
# 5. Run both assets
# ============================================================

print("\nWarming up numba JIT...")
_ = mf_gjr_negloglik_numba(
    np.array([1.0, 0.05, 0.05, 0.9, -0.5, 0.5]),
    np.random.randn(100), np.random.randn(100))
_ = mf_gjr_compute_g_series(
    np.array([1.0, 0.05, 0.05, 0.9, -0.5, 0.5]),
    np.random.randn(100), np.random.randn(100))
print("JIT compilation done.")

all_results = {}
all_forecasts = {}

for asset in ASSETS:
    out = run_oos_for_asset(asset, returns[asset], vix, log_vix)
    if out is not None:
        results, forecasts, r2_actual, valid, oos_dates = out
        all_results[asset] = results
        all_forecasts[asset] = {
            'forecasts': forecasts,
            'r2_actual': r2_actual,
            'valid': valid,
            'oos_dates': oos_dates
        }

# ============================================================
# 6. Summary
# ============================================================

print("\n" + "="*80)
print("K1235 SUMMARY")
print("="*80)

summary_table = []
for asset in ASSETS:
    if asset not in all_results:
        continue
    r = all_results[asset]
    cmp_ = r.get('paper_comparison', {})
    row = {
        'Ticker': asset,
        'Label': ASSET_LABELS.get(asset, asset),
        'N_OOS': r['n_oos'],
        'QLIKE_GARCH': r['GARCH']['QLIKE'],
        'QLIKE_GJR': r['GJR']['QLIKE'],
        'QLIKE_MF': r['MF-GJR']['QLIKE'],
        'Improve_vs_GJR_pct': r['QLIKE_improvement']['MF_vs_GJR_pct'],
        'DM_t_raw': r['DM_MFvsGJR']['t_stat'],
        'DM_t_harvey': r['DM_MFvsGJR']['t_harvey'],
        'p_harvey': r['DM_MFvsGJR']['p_value_harvey'],
        'paper_claim': cmp_.get('paper_claimed_t'),
        'verdict': cmp_.get('verdict'),
    }
    summary_table.append(row)

df_summary = pd.DataFrame(summary_table)
print("\n" + df_summary.to_string(index=False))

# Paper 9 R2 implication
print("\n" + "="*80)
print("PAPER 9 R2 IMPLICATION")
print("="*80)
verdicts = [r.get('paper_comparison', {}).get('verdict') for r in all_results.values()]
if all(v == 'MATCH' for v in verdicts if v is not None):
    r2_reco = 'use_k1235_canonical'
    r2_msg = 'All tickers MATCH. K1235 numbers can be cited directly as canonical source.'
elif all(v in ('MATCH', 'BORDERLINE') for v in verdicts if v is not None):
    r2_reco = 'use_k1235_canonical_with_footnote'
    r2_msg = 'All tickers MATCH/BORDERLINE. Cite K1235 as canonical with footnote on small divergence.'
elif any(v == 'MISMATCH' for v in verdicts if v is not None):
    r2_reco = 'errata_required'
    r2_msg = 'MISMATCH found. Paper cannot cite K1235 as matching claim. Options: (a) errata reporting K1235 numbers, (b) spec clarification that Table 6 used A4f spec (OOS 2019-2026) different from K949.'
else:
    r2_reco = 'review_manually'
    r2_msg = 'Mixed verdicts; manual review.'
print(f"Recommendation: {r2_reco}")
print(f"Rationale: {r2_msg}")

# ============================================================
# 7. Figures
# ============================================================

# Fig 1: QLIKE timeseries (cumulative means)
fig, axes = plt.subplots(len(all_results), 1, figsize=(12, 4*len(all_results)), squeeze=False)
for idx, asset in enumerate(ASSETS):
    if asset not in all_forecasts:
        continue
    label = ASSET_LABELS.get(asset, asset)
    ax = axes[idx, 0]
    fc = all_forecasts[asset]
    valid = fc['valid']
    r2 = fc['r2_actual'][valid]
    dates = fc['oos_dates'][valid]

    for m, color in [('GARCH', '#4a90d9'), ('GJR', '#f5a623'), ('MF-GJR', '#d0021b')]:
        f = fc['forecasts'][m][valid]
        loss = r2/f + np.log(f)
        cum_loss = np.cumsum(loss) / np.arange(1, len(loss)+1)
        ax.plot(dates, cum_loss, label=m, color=color, alpha=0.8, linewidth=1.3)
    ax.set_title(f'{label}: Cumulative-mean QLIKE (lower=better)')
    ax.set_ylabel('QLIKE')
    ax.legend()
    ax.grid(alpha=0.3)

plt.tight_layout()
fig_path = OUTPUT_DIR / 'k1235_qlike_timeseries.png'
plt.savefig(fig_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"Figure saved: {fig_path}")

# Fig 2: Rolling DM t (window=252)
fig, axes = plt.subplots(len(all_results), 1, figsize=(12, 4*len(all_results)), squeeze=False)
for idx, asset in enumerate(ASSETS):
    if asset not in all_forecasts:
        continue
    label = ASSET_LABELS.get(asset, asset)
    ax = axes[idx, 0]
    fc = all_forecasts[asset]
    valid = fc['valid']
    r2 = fc['r2_actual'][valid]
    dates = fc['oos_dates'][valid]

    d_mf = r2 / fc['forecasts']['MF-GJR'][valid] + np.log(fc['forecasts']['MF-GJR'][valid])
    d_gjr = r2 / fc['forecasts']['GJR'][valid] + np.log(fc['forecasts']['GJR'][valid])
    d = d_gjr - d_mf
    # Rolling 252-day t-stat
    W_ROLL = 252
    rolling_t = np.full(len(d), np.nan)
    for i in range(W_ROLL, len(d)):
        sub = d[i-W_ROLL:i]
        rolling_t[i] = np.mean(sub) / (np.std(sub, ddof=1) / np.sqrt(W_ROLL)) if np.std(sub, ddof=1) > 0 else 0

    ax.plot(dates, rolling_t, color='#d0021b', alpha=0.9, linewidth=1.2)
    ax.axhline(y=0, color='black', linestyle='-', alpha=0.3)
    ax.axhline(y=2.0, color='gray', linestyle='--', alpha=0.4, label='|t|=2.0')
    ax.axhline(y=-2.0, color='gray', linestyle='--', alpha=0.4)
    # Paper-claimed and K1235 full-sample t
    if asset in PAPER_CLAIMS:
        ax.axhline(y=PAPER_CLAIMS[asset], color='blue', linestyle=':', alpha=0.7,
                   label=f'Paper claim t={PAPER_CLAIMS[asset]}')
    t_full = all_results[asset]['DM_MFvsGJR']['t_harvey']
    ax.axhline(y=t_full, color='green', linestyle=':', alpha=0.7,
               label=f'K1235 full t_harvey={t_full:.2f}')
    ax.set_title(f'{label}: 252-day rolling DM t (MF-GJR vs GJR, positive=MF-GJR better)')
    ax.set_ylabel('DM t')
    ax.legend(loc='best', fontsize=9)
    ax.grid(alpha=0.3)

plt.tight_layout()
fig_path2 = OUTPUT_DIR / 'k1235_dm_rolling.png'
plt.savefig(fig_path2, dpi=150, bbox_inches='tight')
plt.close()
print(f"Figure saved: {fig_path2}")

# ============================================================
# 8. Save results JSON
# ============================================================

output = {
    'experiment_id': 'K1235',
    'title': 'Paper 9 FEZ + STOXX50E K949 spec bundle — canonical t-statistics for K1232-flagged no-source values',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance',
    'tickers': ASSETS,
    'ticker_labels': ASSET_LABELS,
    'spec': 'K949 verbatim: MF-GJR log-exp tau, constrained omega (E[g]=1), GJR(1,1,1), MLE L-BFGS-B',
    'oos_period': f'{OOS_START} to {END}',
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'seed': 42,
    'models': ['GARCH(1,1)', 'GJR(1,1,1)', 'MF-GJR(VIX)'],
    'evaluation': 'QLIKE on r^2, Spearman rank, DM-HLN test (HAC-robust, Harvey 1997 correction)',
    'paper_claims': PAPER_CLAIMS,
    'paper9_table6_spec_caveat': (
        'Paper 9 Table 6 uses A4f spec (tau=VIX^2, free omega, OOS 2019-2026, refit=63). '
        'K1235 uses K949 spec (log-exp tau, constrained omega, OOS 2016-2025, refit=21) per task brief. '
        'MATCH/MISMATCH verdict therefore reflects whether K949 spec alone reproduces the paper value.'
    ),
    'results': all_results,
    'summary_table': summary_table,
    'paper9_r2_recommendation': {
        'code': r2_reco,
        'message': r2_msg,
    },
    'replication_hash_info': {
        'yfinance': 'daily OHLC auto_adjust=True',
        'numba': 'JIT compiled negloglik',
        'arch': 'GARCH + GJR via arch.arch_model, dist=normal, mean=Zero, rescale=False',
    },
}

out_path = OUTPUT_DIR / 'k1235_results.json'
with open(out_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"\nResults saved: {out_path}")
print("\nK1235 done.")
