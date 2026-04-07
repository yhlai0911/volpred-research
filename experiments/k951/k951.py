"""
K951: Copula-GARCH Hedge on High-Corr ETF Pairs
================================================
Question: Where is the correlation threshold for copula hedge effectiveness?
- K923: SPY-GLD (r=0.058) → NULL (HE<3%)
- K931: 0050-TSMC (r>0.9) → HE=0.855

Pairs tested (different correlation levels):
1. SPY-QQQ  (r ≈ 0.93, high)
2. GLD-SLV  (r ≈ 0.85, mid-high)
3. SPY-EWG  (r ≈ 0.75, mid)

Methods: OLS, Rolling OLS(252), DCC-GARCH proxy, Copula-GARCH (Student-t)
Evaluation: HE, VaR 5% reduction, ES 5% reduction, Tail HE, DM test

Data source: yfinance
IS: 2008-01-01 to 2018-12-31, OOS: 2019-01-01 to 2025-12-31
Refit copula every 63 trading days

References:
- Patton (2006): Modelling asymmetric exchange rate dependence, IER
- Ederington (1979): The hedging performance of the new futures markets, JF
- Joe (1997): Multivariate models and dependence concepts
- Harvey (2016): ...and the cross-section of expected returns, RFS

Author: VolPred Research System
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime
from scipy import stats
from scipy.optimize import minimize
from arch import arch_model

np.random.seed(42)
warnings.filterwarnings('ignore')

# ============================================================
# 1. Data Download
# ============================================================
print("=" * 60)
print("K951: Copula-GARCH Hedge on High-Corr ETF Pairs")
print("=" * 60)

PAIRS = [
    ("SPY", "QQQ", "High (≈0.93)"),
    ("GLD", "SLV", "Mid-High (≈0.85)"),
    ("SPY", "EWG", "Mid (≈0.75)"),
]

START = "2006-01-01"  # extra buffer for warm-up
END = "2025-12-31"
IS_END = "2018-12-31"
OOS_START = "2019-01-01"
REFIT_FREQ = 63  # trading days

# Download all tickers
tickers = list(set([t for p in PAIRS for t in p[:2]]))
print(f"\nDownloading: {tickers}")
raw = yf.download(tickers, start=START, end=END, auto_adjust=True)['Close']
raw = raw.dropna()
print(f"Data: {raw.index[0].date()} to {raw.index[-1].date()}, {len(raw)} days")

# Compute log returns (percentage)
returns = np.log(raw / raw.shift(1)).dropna() * 100  # in percent for GARCH

# ============================================================
# 2. Helper Functions
# ============================================================

def fit_gjr_garch(ret_series, p=1, o=1, q=1):
    """Fit GJR-GARCH(1,1,1) model, return model result."""
    am = arch_model(ret_series, vol='GARCH', p=p, o=o, q=q, dist='t', mean='Zero')
    try:
        res = am.fit(disp='off', show_warning=False)
        return res
    except Exception:
        # Fallback to simpler model
        am2 = arch_model(ret_series, vol='GARCH', p=1, q=1, dist='normal', mean='Zero')
        return am2.fit(disp='off', show_warning=False)


def pit_transform(resid, vol, dist_params, dist_type='t'):
    """Probability Integral Transform: standardized residuals → uniform."""
    std_resid = resid / vol
    if dist_type == 't':
        nu = dist_params.get('nu', 5.0)
        # arch package standardizes to unit variance, so scale = sqrt((nu-2)/nu)
        scale = np.sqrt((nu - 2) / nu) if nu > 2 else 1.0
        u = stats.t.cdf(std_resid * scale, df=nu)
    else:
        u = stats.norm.cdf(std_resid)
    # Clip to avoid boundary issues
    u = np.clip(u, 1e-6, 1 - 1e-6)
    return u


def fit_student_t_copula(u1, u2):
    """
    Fit bivariate Student-t copula by MLE.
    Returns (rho, nu).
    """
    # Transform to t-quantiles for a grid of nu values
    best_ll = -np.inf
    best_rho = 0.5
    best_nu = 5

    for nu_try in [3, 4, 5, 6, 8, 10, 15, 20, 30]:
        # Transform uniform to t-quantiles
        x1 = stats.t.ppf(u1, df=nu_try)
        x2 = stats.t.ppf(u2, df=nu_try)

        # MLE for correlation given nu
        def neg_ll(rho_param):
            rho_val = np.atleast_1d(rho_param).ravel()[0]
            rho = float(np.clip(rho_val, -0.999, 0.999))
            n = len(x1)
            R = np.array([[1.0, rho], [rho, 1.0]])
            det_R = 1 - rho**2
            if det_R <= 0:
                return 1e10

            # Bivariate Student-t copula log-density
            # c(u1,u2) = f_2(t^{-1}(u1), t^{-1}(u2); R, nu) / (f_1(t^{-1}(u1);nu) * f_1(t^{-1}(u2);nu))
            # Log-likelihood of copula density
            quad = (x1**2 + x2**2 - 2*rho*x1*x2) / det_R
            ll = n * (
                np.log(np.math.factorial(1))  # Gamma((nu+2)/2) / Gamma(nu/2) terms
                + stats.loggamma.logpdf(1, (nu_try+2)/2) if False else 0
            )
            # Use proper formula
            from scipy.special import gammaln
            ll = (
                n * gammaln((nu_try + 2) / 2)
                - n * gammaln(nu_try / 2)
                - n * 0.5 * np.log(det_R)
                + np.sum(-(nu_try + 2) / 2 * np.log(1 + quad / nu_try))
                - np.sum(-(nu_try + 1) / 2 * np.log(1 + x1**2 / nu_try))
                - np.sum(-(nu_try + 1) / 2 * np.log(1 + x2**2 / nu_try))
            )
            return -ll

        x0_val = float(np.corrcoef(x1, x2)[0, 1])
        res = minimize(neg_ll, x0=x0_val,
                      method='Nelder-Mead', options={'maxiter': 500})
        if -res.fun > best_ll:
            best_ll = -res.fun
            best_rho = np.clip(res.x[0], -0.999, 0.999)
            best_nu = nu_try

    return best_rho, best_nu


def copula_hedge_ratio(rho_cop, sigma_s, sigma_f, nu):
    """
    Copula-implied hedge ratio.
    For Student-t copula: h = rho * sigma_s / sigma_f * tail_correction
    Tail correction captures excess tail dependence beyond Gaussian.
    """
    # Tail dependence coefficient for Student-t copula
    # lambda = 2 * t_{nu+1}(-sqrt((nu+1)(1-rho)/(1+rho)))
    if nu > 1:
        arg = -np.sqrt((nu + 1) * (1 - rho_cop) / (1 + rho_cop + 1e-10))
        tail_dep = 2 * stats.t.cdf(arg, df=nu + 1)
    else:
        tail_dep = 0

    # Correction factor: accounts for heavier tails increasing hedge need
    # In practice: for nu < 10, correction > 1 (need slightly more hedge)
    if nu > 2:
        correction = 1 + 0.5 * tail_dep  # mild correction
    else:
        correction = 1.0

    h = rho_cop * (sigma_s / (sigma_f + 1e-10)) * correction
    return h


def compute_hedged_returns(spot_ret, fut_ret, hedge_ratios):
    """Compute hedged portfolio returns: r_h = r_s - h * r_f."""
    return spot_ret - hedge_ratios * fut_ret


def hedging_effectiveness(unhedged, hedged):
    """Ederington HE = 1 - Var(hedged) / Var(unhedged)."""
    var_uh = np.var(unhedged)
    var_h = np.var(hedged)
    if var_uh == 0:
        return 0
    return 1 - var_h / var_uh


def var_reduction(unhedged, hedged, alpha=0.05):
    """VaR reduction at alpha level."""
    var_uh = np.percentile(unhedged, alpha * 100)
    var_h = np.percentile(hedged, alpha * 100)
    if var_uh == 0:
        return 0
    return (var_uh - var_h) / abs(var_uh)  # positive = improvement


def es_reduction(unhedged, hedged, alpha=0.05):
    """ES reduction at alpha level."""
    var_uh = np.percentile(unhedged, alpha * 100)
    var_h = np.percentile(hedged, alpha * 100)
    es_uh = np.mean(unhedged[unhedged <= var_uh])
    es_h = np.mean(hedged[hedged <= var_h])
    if es_uh == 0:
        return 0
    return (es_uh - es_h) / abs(es_uh)


def tail_he(unhedged, hedged, threshold_sigma=2):
    """HE computed only when spot return < -threshold_sigma * std."""
    sigma = np.std(unhedged)
    mask = unhedged < -threshold_sigma * sigma
    if mask.sum() < 10:
        return np.nan
    return hedging_effectiveness(unhedged[mask], hedged[mask])


def dm_test_hedge(loss1, loss2):
    """
    Diebold-Mariano test on squared hedged returns.
    loss = hedged_return^2 (variance proxy)
    Returns t-stat.
    """
    d = loss1 - loss2
    n = len(d)
    if n < 30:
        return np.nan
    d_bar = np.mean(d)
    # HAC variance (Newey-West with lag = int(n^(1/3)))
    max_lag = int(n**(1/3))
    gamma_0 = np.var(d)
    gamma_sum = 0
    for k in range(1, max_lag + 1):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * (1 - k / (max_lag + 1)) * gamma_k
    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        return np.nan
    return d_bar / np.sqrt(var_d)


# ============================================================
# 3. Main Hedging Analysis
# ============================================================

all_results = {}

for spot_ticker, fut_ticker, corr_label in PAIRS:
    print(f"\n{'='*60}")
    print(f"Pair: {spot_ticker} - {fut_ticker} (Correlation: {corr_label})")
    print(f"{'='*60}")

    # Get returns for this pair
    spot_ret = returns[spot_ticker].copy()
    fut_ret = returns[fut_ticker].copy()

    # Align
    common_idx = spot_ret.index.intersection(fut_ret.index)
    spot_ret = spot_ret.loc[common_idx]
    fut_ret = fut_ret.loc[common_idx]

    # Full sample correlation
    full_corr = np.corrcoef(spot_ret.values, fut_ret.values)[0, 1]
    print(f"Full sample correlation: {full_corr:.4f}")

    # Split IS/OOS
    is_mask = common_idx <= IS_END
    oos_mask = common_idx >= OOS_START

    spot_is = spot_ret[is_mask].values
    fut_is = fut_ret[is_mask].values
    spot_oos = spot_ret[oos_mask].values
    fut_oos = fut_ret[oos_mask].values
    oos_dates = common_idx[oos_mask]

    print(f"IS: {is_mask.sum()} days, OOS: {oos_mask.sum()} days")
    print(f"IS corr: {np.corrcoef(spot_is, fut_is)[0,1]:.4f}")
    print(f"OOS corr: {np.corrcoef(spot_oos, fut_oos)[0,1]:.4f}")

    pair_results = {
        'pair': f"{spot_ticker}-{fut_ticker}",
        'corr_label': corr_label,
        'full_corr': float(full_corr),
        'is_corr': float(np.corrcoef(spot_is, fut_is)[0,1]),
        'oos_corr': float(np.corrcoef(spot_oos, fut_oos)[0,1]),
        'n_is': int(is_mask.sum()),
        'n_oos': int(oos_mask.sum()),
        'methods': {}
    }

    # ---- Method 1: OLS (expanding) ----
    print("\n  [1] OLS (expanding)...")
    h_ols_oos = np.zeros(len(spot_oos))
    all_spot = np.concatenate([spot_is, spot_oos])
    all_fut = np.concatenate([fut_is, fut_oos])
    n_is_len = len(spot_is)

    for t in range(len(spot_oos)):
        # Use all data up to this point
        s_hist = all_spot[:n_is_len + t]
        f_hist = all_fut[:n_is_len + t]
        cov = np.cov(s_hist, f_hist)[0, 1]
        var_f = np.var(f_hist)
        h_ols_oos[t] = cov / var_f if var_f > 0 else 0

    hedged_ols = spot_oos - h_ols_oos * fut_oos
    he_ols = hedging_effectiveness(spot_oos, hedged_ols)
    print(f"    HE = {he_ols:.4f}")

    pair_results['methods']['OLS'] = {
        'HE': float(he_ols),
        'VaR5_reduction': float(var_reduction(spot_oos, hedged_ols)),
        'ES5_reduction': float(es_reduction(spot_oos, hedged_ols)),
        'Tail_HE': float(tail_he(spot_oos, hedged_ols)),
        'mean_h': float(np.mean(h_ols_oos)),
    }

    # ---- Method 2: Rolling OLS (252) ----
    print("  [2] Rolling OLS (252)...")
    window = 252
    h_roll_oos = np.zeros(len(spot_oos))

    for t in range(len(spot_oos)):
        # Use last 252 days ending at t-1
        end_idx = n_is_len + t
        start_idx = max(0, end_idx - window)
        s_win = all_spot[start_idx:end_idx]
        f_win = all_fut[start_idx:end_idx]
        cov = np.cov(s_win, f_win)[0, 1]
        var_f = np.var(f_win)
        h_roll_oos[t] = cov / var_f if var_f > 0 else 0

    hedged_roll = spot_oos - h_roll_oos * fut_oos
    he_roll = hedging_effectiveness(spot_oos, hedged_roll)
    print(f"    HE = {he_roll:.4f}")

    pair_results['methods']['Rolling_OLS'] = {
        'HE': float(he_roll),
        'VaR5_reduction': float(var_reduction(spot_oos, hedged_roll)),
        'ES5_reduction': float(es_reduction(spot_oos, hedged_roll)),
        'Tail_HE': float(tail_he(spot_oos, hedged_roll)),
        'mean_h': float(np.mean(h_roll_oos)),
    }

    # ---- Method 3: DCC-GARCH (rolling correlation proxy) ----
    print("  [3] DCC-GARCH (rolling corr proxy)...")
    # Fit marginal GARCH on IS, then forecast OOS
    spot_all_series = pd.Series(all_spot)
    fut_all_series = pd.Series(all_fut)

    h_dcc_oos = np.zeros(len(spot_oos))

    # Fit GARCH on IS for initial params
    garch_spot_is = fit_gjr_garch(pd.Series(spot_is))
    garch_fut_is = fit_gjr_garch(pd.Series(fut_is))

    # For OOS: refit every REFIT_FREQ days
    last_refit = 0
    sigma_s_forecast = np.zeros(len(spot_oos))
    sigma_f_forecast = np.zeros(len(spot_oos))

    for t in range(len(spot_oos)):
        if t == 0 or (t - last_refit) >= REFIT_FREQ:
            # Refit GARCH on expanding window
            end_idx = n_is_len + t
            try:
                g_s = fit_gjr_garch(spot_all_series.iloc[:end_idx])
                g_f = fit_gjr_garch(fut_all_series.iloc[:end_idx])
                garch_spot_is = g_s
                garch_fut_is = g_f
            except Exception:
                pass
            last_refit = t

        # One-step forecast
        try:
            fc_s = garch_spot_is.forecast(horizon=1, reindex=False)
            sigma_s_forecast[t] = np.sqrt(fc_s.variance.values[-1, 0])
        except Exception:
            sigma_s_forecast[t] = np.std(spot_is)

        try:
            fc_f = garch_fut_is.forecast(horizon=1, reindex=False)
            sigma_f_forecast[t] = np.sqrt(fc_f.variance.values[-1, 0])
        except Exception:
            sigma_f_forecast[t] = np.std(fut_is)

        # Rolling correlation (252)
        end_idx = n_is_len + t
        start_idx = max(0, end_idx - window)
        rho_t = np.corrcoef(all_spot[start_idx:end_idx], all_fut[start_idx:end_idx])[0, 1]

        h_dcc_oos[t] = rho_t * sigma_s_forecast[t] / (sigma_f_forecast[t] + 1e-10)

    hedged_dcc = spot_oos - h_dcc_oos * fut_oos
    he_dcc = hedging_effectiveness(spot_oos, hedged_dcc)
    print(f"    HE = {he_dcc:.4f}")

    pair_results['methods']['DCC_GARCH'] = {
        'HE': float(he_dcc),
        'VaR5_reduction': float(var_reduction(spot_oos, hedged_dcc)),
        'ES5_reduction': float(es_reduction(spot_oos, hedged_dcc)),
        'Tail_HE': float(tail_he(spot_oos, hedged_dcc)),
        'mean_h': float(np.mean(h_dcc_oos)),
    }

    # ---- Method 4: Copula-GARCH ----
    print("  [4] Copula-GARCH (Student-t copula)...")

    h_cop_oos = np.zeros(len(spot_oos))
    copula_rho_history = []
    copula_nu_history = []

    last_refit = -REFIT_FREQ  # force refit at t=0
    current_rho_cop = full_corr
    current_nu_cop = 5
    # Initialize current GARCH models with IS fit
    current_gs = garch_spot_is
    current_gf = garch_fut_is

    for t in range(len(spot_oos)):
        if (t - last_refit) >= REFIT_FREQ or t == 0:
            end_idx = n_is_len + t
            train_spot = pd.Series(all_spot[:end_idx].copy(), name='ret')
            train_fut = pd.Series(all_fut[:end_idx].copy(), name='ret')

            try:
                # Fit marginal GARCH
                g_s = fit_gjr_garch(train_spot)
                g_f = fit_gjr_garch(train_fut)

                # Get standardized residuals and conditional volatilities
                resid_s = np.asarray(g_s.resid, dtype=float).flatten()
                vol_s = np.asarray(g_s.conditional_volatility, dtype=float).flatten()
                resid_f = np.asarray(g_f.resid, dtype=float).flatten()
                vol_f = np.asarray(g_f.conditional_volatility, dtype=float).flatten()

                # Ensure same length (trim to min)
                min_len = min(len(resid_s), len(vol_s), len(resid_f), len(vol_f))
                resid_s = resid_s[-min_len:]
                vol_s = vol_s[-min_len:]
                resid_f = resid_f[-min_len:]
                vol_f = vol_f[-min_len:]

                # Check distribution type
                if 'nu' in g_s.params.index:
                    nu_s = float(g_s.params['nu'])
                    dist_s = {'nu': nu_s}
                    dtype_s = 't'
                else:
                    dist_s = {}
                    dtype_s = 'normal'

                if 'nu' in g_f.params.index:
                    nu_f = float(g_f.params['nu'])
                    dist_f = {'nu': nu_f}
                    dtype_f = 't'
                else:
                    dist_f = {}
                    dtype_f = 'normal'

                # PIT
                u_s = pit_transform(resid_s, vol_s, dist_s, dtype_s)
                u_f = pit_transform(resid_f, vol_f, dist_f, dtype_f)

                # Fit copula (use last 500 obs for speed)
                n_cop = min(500, len(u_s))
                rho_cop, nu_cop = fit_student_t_copula(u_s[-n_cop:], u_f[-n_cop:])

                current_rho_cop = rho_cop
                current_nu_cop = nu_cop

                # Store current GARCH models
                current_gs = g_s
                current_gf = g_f

                copula_rho_history.append(float(rho_cop))
                copula_nu_history.append(float(nu_cop))
                print(f"    Refit at t={t}: rho={rho_cop:.4f}, nu={nu_cop}")

            except Exception as e:
                import traceback
                print(f"    Refit failed at t={t}: {e}")
                traceback.print_exc()

            last_refit = t

        # Forecast sigma
        try:
            fc_s = current_gs.forecast(horizon=1, reindex=False)
            sig_s = np.sqrt(fc_s.variance.values[-1, 0])
        except Exception:
            sig_s = np.std(spot_is)

        try:
            fc_f = current_gf.forecast(horizon=1, reindex=False)
            sig_f = np.sqrt(fc_f.variance.values[-1, 0])
        except Exception:
            sig_f = np.std(fut_is)

        h_cop_oos[t] = copula_hedge_ratio(current_rho_cop, sig_s, sig_f, current_nu_cop)

    hedged_cop = spot_oos - h_cop_oos * fut_oos
    he_cop = hedging_effectiveness(spot_oos, hedged_cop)
    print(f"    HE = {he_cop:.4f}")

    pair_results['methods']['Copula_GARCH'] = {
        'HE': float(he_cop),
        'VaR5_reduction': float(var_reduction(spot_oos, hedged_cop)),
        'ES5_reduction': float(es_reduction(spot_oos, hedged_cop)),
        'Tail_HE': float(tail_he(spot_oos, hedged_cop)),
        'mean_h': float(np.mean(h_cop_oos)),
        'copula_rho_mean': float(np.mean(copula_rho_history)) if copula_rho_history else None,
        'copula_nu_mean': float(np.mean(copula_nu_history)) if copula_nu_history else None,
        'copula_rho_history': copula_rho_history,
        'copula_nu_history': copula_nu_history,
    }

    # ---- DM Tests ----
    print("\n  DM Tests (squared hedged returns):")
    methods_names = ['OLS', 'Rolling_OLS', 'DCC_GARCH', 'Copula_GARCH']
    hedged_arrays = {
        'OLS': hedged_ols,
        'Rolling_OLS': hedged_roll,
        'DCC_GARCH': hedged_dcc,
        'Copula_GARCH': hedged_cop,
    }

    dm_results = {}
    for i, m1 in enumerate(methods_names):
        for j, m2 in enumerate(methods_names):
            if i < j:
                loss1 = hedged_arrays[m1]**2
                loss2 = hedged_arrays[m2]**2
                t_stat = dm_test_hedge(loss1, loss2)
                key = f"{m1}_vs_{m2}"
                dm_results[key] = float(t_stat) if not np.isnan(t_stat) else None
                sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else "")
                print(f"    {m1} vs {m2}: t = {t_stat:.3f} {sig}")
                # Positive t means m1 has larger loss (m2 is better)

    pair_results['dm_tests'] = dm_results

    # ---- Summary Table ----
    print(f"\n  Summary for {spot_ticker}-{fut_ticker}:")
    print(f"  {'Method':<16} {'HE':>8} {'VaR5%':>8} {'ES5%':>8} {'TailHE':>8} {'Mean h':>8}")
    print(f"  {'-'*56}")
    for m in methods_names:
        mr = pair_results['methods'][m]
        tail = f"{mr['Tail_HE']:.4f}" if not np.isnan(mr.get('Tail_HE', np.nan)) else "N/A"
        print(f"  {m:<16} {mr['HE']:>8.4f} {mr['VaR5_reduction']:>8.4f} {mr['ES5_reduction']:>8.4f} {tail:>8} {mr['mean_h']:>8.4f}")

    all_results[f"{spot_ticker}-{fut_ticker}"] = pair_results

# ============================================================
# 4. Cross-Pair Summary
# ============================================================
print("\n" + "=" * 60)
print("CROSS-PAIR SUMMARY")
print("=" * 60)

print(f"\n{'Pair':<12} {'Corr':>6} | {'OLS':>8} {'Roll':>8} {'DCC':>8} {'Copula':>8} | {'Cop-OLS':>8}")
print("-" * 75)
for pair_key, pr in all_results.items():
    he_ols = pr['methods']['OLS']['HE']
    he_roll = pr['methods']['Rolling_OLS']['HE']
    he_dcc = pr['methods']['DCC_GARCH']['HE']
    he_cop = pr['methods']['Copula_GARCH']['HE']
    diff = he_cop - he_ols
    print(f"{pair_key:<12} {pr['oos_corr']:>6.3f} | {he_ols:>8.4f} {he_roll:>8.4f} {he_dcc:>8.4f} {he_cop:>8.4f} | {diff:>+8.4f}")

# ============================================================
# 5. Conclusions
# ============================================================
print("\n" + "=" * 60)
print("CONCLUSIONS")
print("=" * 60)

# Check if copula adds value at any correlation level
for pair_key, pr in all_results.items():
    he_best_simple = max(pr['methods']['OLS']['HE'], pr['methods']['Rolling_OLS']['HE'])
    he_cop = pr['methods']['Copula_GARCH']['HE']
    dm_cop_vs_ols = pr['dm_tests'].get('OLS_vs_Copula_GARCH')
    dm_cop_vs_roll = pr['dm_tests'].get('Rolling_OLS_vs_Copula_GARCH')

    improvement = he_cop - he_best_simple
    print(f"\n{pair_key} (corr={pr['oos_corr']:.3f}):")
    print(f"  Best simple HE: {he_best_simple:.4f}")
    print(f"  Copula HE: {he_cop:.4f}")
    print(f"  Improvement: {improvement:+.4f}")
    if dm_cop_vs_ols is not None:
        print(f"  DM(OLS vs Copula): t={dm_cop_vs_ols:.3f} {'(sig)' if abs(dm_cop_vs_ols) > 3.0 else '(not sig)'}")

# ============================================================
# 6. Save Results
# ============================================================
final_results = {
    'experiment_id': 'K951',
    'title': 'Copula-GARCH Hedge on High-Corr ETF Pairs',
    'data_source': 'yfinance',
    'is_period': '2006-01-01 to 2018-12-31',
    'oos_period': '2019-01-01 to 2025-12-31',
    'refit_freq': REFIT_FREQ,
    'timestamp': datetime.now().isoformat(),
    'seed': 42,
    'pairs': all_results,
    'methodology': {
        'marginal_model': 'GJR-GARCH(1,1,1) with Student-t innovations',
        'copula': 'Bivariate Student-t copula (MLE)',
        'pit': 'Probability Integral Transform with scale correction',
        'dcc_proxy': 'Rolling 252-day correlation as DCC approximation',
        'refit': f'Every {REFIT_FREQ} trading days (expanding window)',
        'hedge_ratio': 'h = rho * sigma_S / sigma_F * tail_correction',
    },
    'references': [
        'Patton (2006): Modelling asymmetric exchange rate dependence, IER',
        'Ederington (1979): The hedging performance of the new futures markets, JF',
        'Joe (1997): Multivariate models and dependence concepts',
        'Harvey (2016): ...and the cross-section of expected returns, RFS',
    ],
}

results_path = 'experiments/k951/k951_results.json'
with open(results_path, 'w') as f:
    json.dump(final_results, f, indent=2, default=str)
print(f"\nResults saved to {results_path}")

# ============================================================
# 7. Visualization
# ============================================================
fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# Plot 1: HE comparison across pairs
ax = axes[0, 0]
pairs_labels = list(all_results.keys())
methods = ['OLS', 'Rolling_OLS', 'DCC_GARCH', 'Copula_GARCH']
method_labels = ['OLS', 'Rolling OLS', 'DCC-GARCH', 'Copula-GARCH']
x = np.arange(len(pairs_labels))
width = 0.2

for i, (m, ml) in enumerate(zip(methods, method_labels)):
    vals = [all_results[p]['methods'][m]['HE'] for p in pairs_labels]
    ax.bar(x + i * width, vals, width, label=ml, alpha=0.85)

ax.set_ylabel('Hedging Effectiveness (HE)')
ax.set_title('HE by Pair and Method (OOS)')
ax.set_xticks(x + 1.5 * width)
corr_labels = [f"{p}\n(r={all_results[p]['oos_corr']:.2f})" for p in pairs_labels]
ax.set_xticklabels(corr_labels)
ax.legend(fontsize=8)
ax.grid(axis='y', alpha=0.3)

# Plot 2: VaR 5% reduction
ax = axes[0, 1]
for i, (m, ml) in enumerate(zip(methods, method_labels)):
    vals = [all_results[p]['methods'][m]['VaR5_reduction'] for p in pairs_labels]
    ax.bar(x + i * width, vals, width, label=ml, alpha=0.85)

ax.set_ylabel('VaR 5% Reduction')
ax.set_title('VaR 5% Reduction by Pair and Method (OOS)')
ax.set_xticks(x + 1.5 * width)
ax.set_xticklabels(corr_labels)
ax.legend(fontsize=8)
ax.grid(axis='y', alpha=0.3)

# Plot 3: Copula improvement vs correlation
ax = axes[1, 0]
corrs = [all_results[p]['oos_corr'] for p in pairs_labels]
cop_improvement = [all_results[p]['methods']['Copula_GARCH']['HE'] - all_results[p]['methods']['OLS']['HE']
                   for p in pairs_labels]
ax.scatter(corrs, cop_improvement, s=100, c='red', zorder=5)
for i, p in enumerate(pairs_labels):
    ax.annotate(p, (corrs[i], cop_improvement[i]), textcoords="offset points",
               xytext=(5, 5), fontsize=9)
ax.axhline(y=0, color='gray', linestyle='--', alpha=0.5)
ax.set_xlabel('OOS Correlation')
ax.set_ylabel('Copula HE - OLS HE')
ax.set_title('Copula Improvement over OLS vs Correlation')
ax.grid(alpha=0.3)

# Plot 4: Tail HE comparison
ax = axes[1, 1]
for i, (m, ml) in enumerate(zip(methods, method_labels)):
    vals = []
    for p in pairs_labels:
        v = all_results[p]['methods'][m].get('Tail_HE', np.nan)
        vals.append(v if not np.isnan(v) else 0)
    ax.bar(x + i * width, vals, width, label=ml, alpha=0.85)

ax.set_ylabel('Tail HE (spot < -2σ)')
ax.set_title('Tail Hedging Effectiveness (OOS)')
ax.set_xticks(x + 1.5 * width)
ax.set_xticklabels(corr_labels)
ax.legend(fontsize=8)
ax.grid(axis='y', alpha=0.3)

plt.tight_layout()
chart_path = 'experiments/k951/k951_hedge_comparison.png'
plt.savefig(chart_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"Chart saved to {chart_path}")

print("\n✓ K951 complete.")
