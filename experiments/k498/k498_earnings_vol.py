"""
K498: Earnings Season Volatility Patterns — GARCH-X Extension
=============================================================
Build on K412 (descriptive null at index level) by testing a formal
GJR-GARCH-X model with earnings dummy in variance equation + OOS QLIKE.

Research Questions:
1. SPY vol during earnings season (1/4/7/10月 3rd-4th week) vs non-earnings?
2. Can earnings dummy improve GJR-GARCH vol forecast (OOS QLIKE)?
3. VIX seasonal pattern around earnings?

Prior: K412/K923 found SPY earnings/non-earnings vol ratio=0.96x (p=0.615).
       Individual stocks show effect (AAPL 1.15x, MSFT 1.28x) but index
       diversification absorbs it. This experiment adds formal GARCH-X test.

Data: SPY + ^VIX daily 2005-2026 from yfinance
OOS: 2023-2025 (rolling 1-step)
Method: GJR-GARCH(1,1) baseline vs GJR-GARCH-X(1,1) with earnings dummy

References:
- Savor & Wilson (2016) "Earnings Announcements and Systematic Risk", JFE
- Barber et al. (2013) "Aggregate earnings surprises and stock returns"
- K412: Earnings Season Effect on Index Vol (null at index level)

[提出: User, 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
import warnings
import json
from datetime import datetime, timezone

warnings.filterwarnings('ignore')

# ============================================================
# 1. DATA
# ============================================================
print("=" * 70)
print("K498: Earnings Season Volatility Patterns — GARCH-X Extension")
print("=" * 70)

print("\nDownloading data...")
spy = yf.download('SPY', start='2005-01-01', end='2026-03-26', auto_adjust=False, progress=False)
vix = yf.download('^VIX', start='2005-01-01', end='2026-03-26', auto_adjust=False, progress=False)

# Flatten MultiIndex
for df in [spy, vix]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

spy['ret'] = spy['Close'].pct_change() * 100  # percent
spy['abs_ret'] = spy['ret'].abs()
spy['rv5'] = spy['ret'].rolling(5).var()  # 5-day realized variance
spy = spy.dropna(subset=['ret'])
vix = vix[['Close']].rename(columns={'Close': 'vix'})

# Merge VIX
df = spy[['ret', 'abs_ret', 'rv5', 'Close']].join(vix['vix'], how='inner')
df = df.dropna()

print(f"SPY: {len(df)} trading days, {df.index[0].date()} to {df.index[-1].date()}")
print(f"VIX: mean={df['vix'].mean():.1f}, std={df['vix'].std():.1f}")

# ============================================================
# 2. EARNINGS SEASON FLAG
# ============================================================
def is_earnings_season(date):
    """3rd-4th week of Jan/Apr/Jul/Oct (major tech earnings)"""
    if date.month not in [1, 4, 7, 10]:
        return False
    week_of_month = (date.day - 1) // 7 + 1
    return week_of_month in [3, 4]

def is_earnings_month(date):
    """Broader: entire month of Jan/Apr/Jul/Oct"""
    return date.month in [1, 4, 7, 10]

df['earnings_season'] = pd.Series(
    [1 if is_earnings_season(d) else 0 for d in df.index], index=df.index
)
df['earnings_month'] = pd.Series(
    [1 if is_earnings_month(d) else 0 for d in df.index], index=df.index
)

n_earn = df['earnings_season'].sum()
n_total = len(df)
print(f"\nEarnings season days: {n_earn} ({n_earn/n_total*100:.1f}%)")
print(f"Off-season days: {n_total - n_earn} ({(1-n_earn/n_total)*100:.1f}%)")

# ============================================================
# 3. DESCRIPTIVE ANALYSIS (confirming K412)
# ============================================================
print("\n" + "=" * 70)
print("PART 1: Descriptive Analysis (confirming K412)")
print("=" * 70)

earn = df[df['earnings_season'] == 1]
off = df[df['earnings_season'] == 0]

earn_vol = earn['abs_ret'].mean()
off_vol = off['abs_ret'].mean()
ratio = earn_vol / off_vol

# Welch t-test
t_welch, p_welch = stats.ttest_ind(earn['abs_ret'], off['abs_ret'], equal_var=False)

# Levene test for variance equality
lev_stat, lev_p = stats.levene(earn['ret'], off['ret'])

# F-test
var_earn = earn['ret'].var()
var_off = off['ret'].var()
f_ratio = var_earn / var_off

print(f"\nMean |return| — Earnings: {earn_vol:.3f}%, Off: {off_vol:.3f}%")
print(f"Ratio (earn/off): {ratio:.3f}")
print(f"Welch t-test: t={t_welch:.3f}, p={p_welch:.4f}")
print(f"Levene test (variance): stat={lev_stat:.3f}, p={lev_p:.4f}")
print(f"Variance ratio (F): {f_ratio:.4f}")

# Annualized
earn_ann_vol = earn['ret'].std() * np.sqrt(252)
off_ann_vol = off['ret'].std() * np.sqrt(252)
print(f"\nAnnualized vol — Earnings: {earn_ann_vol:.2f}%, Off: {off_ann_vol:.2f}%")

# ============================================================
# 4. VIX DURING EARNINGS SEASON
# ============================================================
print("\n" + "=" * 70)
print("PART 2: VIX During Earnings Season")
print("=" * 70)

vix_earn = df.loc[df['earnings_season'] == 1, 'vix']
vix_off = df.loc[df['earnings_season'] == 0, 'vix']

t_vix, p_vix = stats.ttest_ind(vix_earn, vix_off, equal_var=False)
print(f"\nVIX level — Earnings: {vix_earn.mean():.2f}, Off: {vix_off.mean():.2f}")
print(f"Welch t-test: t={t_vix:.3f}, p={p_vix:.4f}")

# VIX change during earnings
df['vix_chg'] = df['vix'].pct_change() * 100
vix_chg_earn = df.loc[df['earnings_season'] == 1, 'vix_chg'].dropna()
vix_chg_off = df.loc[df['earnings_season'] == 0, 'vix_chg'].dropna()
t_vchg, p_vchg = stats.ttest_ind(vix_chg_earn, vix_chg_off, equal_var=False)
print(f"VIX daily change — Earnings: {vix_chg_earn.mean():.3f}%, Off: {vix_chg_off.mean():.3f}%")
print(f"Welch t-test: t={t_vchg:.3f}, p={p_vchg:.4f}")

# Monthly VIX pattern
monthly_vix = df.groupby(df.index.month)['vix'].mean()
month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
print(f"\nMonthly VIX level:")
for m in range(1, 13):
    flag = ' *' if m in [1, 4, 7, 10] else ''
    print(f"  {month_names[m-1]}: {monthly_vix[m]:.2f}{flag}")
print("  (* = earnings month)")

# ============================================================
# 5. GJR-GARCH BASELINE vs GARCH-X WITH EARNINGS DUMMY
# ============================================================
print("\n" + "=" * 70)
print("PART 3: GJR-GARCH Baseline vs GARCH-X with Earnings Dummy")
print("=" * 70)

# Full sample estimation first
ret = df['ret']
earn_flag = df['earnings_season']

# Baseline GJR-GARCH(1,1) — full sample
print("\nFull-sample estimation:")
am_base = arch_model(ret, vol='GARCH', p=1, o=1, q=1, dist='t', mean='AR', lags=1)
res_base = am_base.fit(disp='off')
print(f"\n--- GJR-GARCH(1,1) Baseline ---")
print(f"  omega={res_base.params.get('omega', np.nan):.6f}")
print(f"  alpha={res_base.params.get('alpha[1]', np.nan):.4f}")
print(f"  gamma={res_base.params.get('gamma[1]', np.nan):.4f}")
print(f"  beta={res_base.params.get('beta[1]', np.nan):.4f}")
pers_base = (res_base.params.get('alpha[1]', 0) +
             res_base.params.get('gamma[1]', 0)/2 +
             res_base.params.get('beta[1]', 0))
print(f"  persistence={pers_base:.4f}")
print(f"  BIC={res_base.bic:.2f}")

# ---- Custom GJR-GARCH-X via MLE ----
# h_t = omega + alpha*eps_{t-1}^2 + gamma*I(eps<0)*eps_{t-1}^2 + beta*h_{t-1} + delta*x_t
# arch package doesn't support exogenous in variance eq, so we do it manually.

from scipy.optimize import minimize

from scipy.special import gammaln

def gjr_garch_x_loglik(params, returns, exog, include_x=True):
    """
    Negative log-likelihood for GJR-GARCH(1,1)-X with Student-t.
    params: [mu, phi, omega, alpha, gamma, beta, (delta if include_x), nu]
    Variance loop is in Python (unavoidable recursive structure), but
    the log-likelihood itself is vectorized.
    """
    n = len(returns)
    if include_x:
        mu, phi, omega, alpha, gamma, beta, delta, nu = params
    else:
        mu, phi, omega, alpha, gamma, beta, nu = params
        delta = 0.0

    # Constraints check
    if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0 or nu <= 2:
        return 1e10
    pers = alpha + gamma/2 + beta
    if pers >= 1.0:
        return 1e10

    # Compute residuals (vectorized)
    eps = np.empty(n)
    eps[0] = returns[0] - mu
    eps[1:] = returns[1:] - mu - phi * returns[:-1]

    eps2 = eps * eps
    indicator = (eps < 0).astype(float)

    # Variance recursion (must be sequential)
    h = np.empty(n)
    h[0] = omega / (1 - pers)

    for t in range(1, n):
        h[t] = (omega + alpha * eps2[t-1]
                + gamma * indicator[t-1] * eps2[t-1]
                + beta * h[t-1]
                + delta * exog[t])
        if h[t] <= 1e-8:
            h[t] = 1e-8

    # Student-t log-likelihood (vectorized, skip first obs)
    h_v = h[1:]
    eps2_v = eps2[1:]

    const = gammaln((nu + 1) / 2) - gammaln(nu / 2) - 0.5 * np.log(np.pi * (nu - 2))
    ll = const - 0.5 * np.log(h_v) - (nu + 1) / 2 * np.log(1 + eps2_v / (h_v * (nu - 2)))
    return -np.sum(ll)

ret_arr = ret.values.astype(float)
exog_season = earn_flag.values.astype(float)
exog_month = df['earnings_month'].values.astype(float)

# Get initial params from arch baseline
mu0 = res_base.params.get('Const', 0.05)
phi0 = res_base.params.get('y[1]', 0.0) if 'y[1]' in res_base.params else 0.0
omega0 = res_base.params.get('omega', 0.02)
alpha0 = res_base.params.get('alpha[1]', 0.05)
gamma0 = res_base.params.get('gamma[1]', 0.15)
beta0 = res_base.params.get('beta[1]', 0.85)
nu0 = res_base.params.get('nu', 7.0) if 'nu' in res_base.params else 7.0

# Fit baseline (no exog) for fair comparison
x0_base = [mu0, phi0, omega0, alpha0, gamma0, beta0, nu0]
bounds_base = [(-1, 1), (-0.5, 0.5), (1e-6, 1.0), (0, 0.5), (0, 0.5), (0, 0.999), (2.1, 50)]

res_custom_base = minimize(gjr_garch_x_loglik, x0_base,
                           args=(ret_arr, exog_season, False),
                           method='L-BFGS-B', bounds=bounds_base,
                           options={'maxiter': 500, 'ftol': 1e-10})

# Fit GARCH-X (season)
x0_x = [mu0, phi0, omega0, alpha0, gamma0, beta0, 0.0, nu0]
bounds_x = [(-1, 1), (-0.5, 0.5), (1e-6, 1.0), (0, 0.5), (0, 0.5), (0, 0.999), (-0.5, 0.5), (2.1, 50)]

res_custom_x = minimize(gjr_garch_x_loglik, x0_x,
                        args=(ret_arr, exog_season, True),
                        method='L-BFGS-B', bounds=bounds_x,
                        options={'maxiter': 500, 'ftol': 1e-10})

# Fit GARCH-X (month)
res_custom_xm = minimize(gjr_garch_x_loglik, x0_x,
                         args=(ret_arr, exog_month, True),
                         method='L-BFGS-B', bounds=bounds_x,
                         options={'maxiter': 500, 'ftol': 1e-10})

n_params_base = 7
n_params_x = 8
n_obs = len(ret_arr)

nll_base = res_custom_base.fun
nll_x = res_custom_x.fun
nll_xm = res_custom_xm.fun

bic_custom_base = 2 * nll_base + n_params_base * np.log(n_obs)
bic_custom_x = 2 * nll_x + n_params_x * np.log(n_obs)
bic_custom_xm = 2 * nll_xm + n_params_x * np.log(n_obs)

print(f"\n--- Custom GJR-GARCH(1,1) Baseline ---")
pnames_base = ['mu', 'phi', 'omega', 'alpha', 'gamma', 'beta', 'nu']
for i, pn in enumerate(pnames_base):
    print(f"  {pn}={res_custom_base.x[i]:.6f}")
print(f"  NLL={nll_base:.2f}, BIC={bic_custom_base:.2f}")

print(f"\n--- GJR-GARCH-X(1,1) + Earnings Season Dummy ---")
pnames_x = ['mu', 'phi', 'omega', 'alpha', 'gamma', 'beta', 'delta_earn', 'nu']
for i, pn in enumerate(pnames_x):
    print(f"  {pn}={res_custom_x.x[i]:.6f}")
x_coef = res_custom_x.x[6]
print(f"  NLL={nll_x:.2f}, BIC={bic_custom_x:.2f}")

print(f"\n--- GJR-GARCH-X(1,1) + Earnings Month Dummy ---")
for i, pn in enumerate(pnames_x):
    val = res_custom_xm.x[i]
    label = pn.replace('earn', 'month')
    print(f"  {label}={val:.6f}")
xm_coef = res_custom_xm.x[6]
print(f"  NLL={nll_xm:.2f}, BIC={bic_custom_xm:.2f}")

# Likelihood ratio test
lr_stat = 2 * (nll_base - nll_x)
lr_pval = 1 - stats.chi2.cdf(lr_stat, df=1) if lr_stat > 0 else 1.0

lr_stat_m = 2 * (nll_base - nll_xm)
lr_pval_m = 1 - stats.chi2.cdf(lr_stat_m, df=1) if lr_stat_m > 0 else 1.0

# Approximate SE via Hessian (numerical)
from scipy.optimize import approx_fprime
def hessian_diag(f, x, args, eps=1e-5):
    """Diagonal of Hessian (for approximate SE)"""
    n = len(x)
    se = np.zeros(n)
    f0 = f(x, *args)
    for i in range(n):
        xp = x.copy()
        xp[i] += eps
        xm = x.copy()
        xm[i] -= eps
        fp = f(xp, *args)
        fm = f(xm, *args)
        d2 = (fp - 2*f0 + fm) / eps**2
        se[i] = 1.0 / np.sqrt(max(d2, 1e-10))
    return se

se_x = hessian_diag(gjr_garch_x_loglik, res_custom_x.x, (ret_arr, exog_season, True))
x_tstat = x_coef / se_x[6] if se_x[6] > 0 else 0
x_pval = 2 * (1 - stats.norm.cdf(abs(x_tstat)))

se_xm = hessian_diag(gjr_garch_x_loglik, res_custom_xm.x, (ret_arr, exog_month, True))
xm_tstat = xm_coef / se_xm[6] if se_xm[6] > 0 else 0
xm_pval = 2 * (1 - stats.norm.cdf(abs(xm_tstat)))

print(f"\n--- Statistical Tests ---")
print(f"Earnings Season dummy: delta={x_coef:.6f}, SE={se_x[6]:.6f}, t={x_tstat:.4f}, p={x_pval:.4f}")
print(f"Earnings Month dummy:  delta={xm_coef:.6f}, SE={se_xm[6]:.6f}, t={xm_tstat:.4f}, p={xm_pval:.4f}")
print(f"\nLR test (season): LR={lr_stat:.4f}, p={lr_pval:.4f}")
print(f"LR test (month):  LR={lr_stat_m:.4f}, p={lr_pval_m:.4f}")
print(f"\nBIC: Base={bic_custom_base:.2f}, Season={bic_custom_x:.2f}, Month={bic_custom_xm:.2f}")
bic_prefers = 'GARCH-X(season)' if bic_custom_x < bic_custom_base and bic_custom_x < bic_custom_xm else \
              'GARCH-X(month)' if bic_custom_xm < bic_custom_base else 'Baseline'
print(f"BIC prefers: {bic_prefers}")

# ============================================================
# 6. OOS FORECASTING COMPARISON (2023-2025)
# ============================================================
print("\n" + "=" * 70)
print("PART 4: Out-of-Sample Forecasting (2023-2025)")
print("=" * 70)

oos_start = '2023-01-01'
oos_end = '2026-03-26'
window = 2000  # rolling window

oos_mask = df.index >= oos_start
oos_dates = df.index[oos_mask]
n_oos = len(oos_dates)
print(f"OOS period: {oos_dates[0].date()} to {oos_dates[-1].date()} ({n_oos} days)")

# Storage for forecasts
fc_base = np.full(n_oos, np.nan)
fc_x = np.full(n_oos, np.nan)
fc_x_month = np.full(n_oos, np.nan)
realized = np.full(n_oos, np.nan)

all_ret = df['ret'].values.astype(float)
all_earn = df['earnings_season'].values.astype(float)
all_earn_month = df['earnings_month'].values.astype(float)

oos_start_idx = int(np.where(df.index >= oos_start)[0][0])

print(f"Running {n_oos} rolling 1-step forecasts (window={window})...")

def gjr_garch_x_forecast(returns, exog, next_exog, include_x=True):
    """
    Estimate GJR-GARCH-X and return 1-step-ahead variance forecast.
    Returns (h_forecast, success).
    """
    n = len(returns)

    # Quick starting values from sample moments
    mu0 = np.mean(returns)
    var0 = np.var(returns)
    x0_base = [mu0, 0.0, 0.02, 0.05, 0.15, 0.80, 8.0]
    bounds_base = [(-1, 1), (-0.5, 0.5), (1e-6, 1.0), (0, 0.5), (0, 0.5), (0, 0.999), (2.1, 50)]

    if include_x:
        x0 = [mu0, 0.0, 0.02, 0.05, 0.15, 0.80, 0.0, 8.0]
        bounds = [(-1, 1), (-0.5, 0.5), (1e-6, 1.0), (0, 0.5), (0, 0.5), (0, 0.999), (-0.5, 0.5), (2.1, 50)]
    else:
        x0 = x0_base
        bounds = bounds_base

    try:
        res = minimize(gjr_garch_x_loglik, x0,
                       args=(returns, exog, include_x),
                       method='L-BFGS-B', bounds=bounds,
                       options={'maxiter': 200, 'ftol': 1e-8})

        if not res.success and res.fun > 1e9:
            return np.nan, False

        if include_x:
            mu, phi, omega, alpha, gamma, beta, delta, nu = res.x
        else:
            mu, phi, omega, alpha, gamma, beta, nu = res.x
            delta = 0.0

        # Compute variance path to get h_T
        eps = np.zeros(n)
        h = np.zeros(n)
        h[0] = omega / max(1 - alpha - gamma/2 - beta, 0.01)
        eps[0] = returns[0] - mu

        for t in range(1, n):
            eps[t] = returns[t] - mu - phi * returns[t-1]
            h[t] = (omega + alpha * eps[t-1]**2
                    + gamma * (eps[t-1] < 0) * eps[t-1]**2
                    + beta * h[t-1]
                    + delta * exog[t])
            if h[t] <= 0:
                h[t] = 1e-6

        # 1-step forecast
        h_forecast = (omega + alpha * eps[-1]**2
                      + gamma * (eps[-1] < 0) * eps[-1]**2
                      + beta * h[-1]
                      + delta * next_exog)
        return max(h_forecast, 1e-6), True
    except:
        return np.nan, False

failures_base = 0
failures_x = 0
failures_xm = 0

# Warm start: use full-sample estimates as initial guess, update as we go
prev_x_season = res_custom_x.x.copy()
prev_x_month = res_custom_xm.x.copy()

for i in range(n_oos):
    t = oos_start_idx + i
    if t < window:
        continue

    train_ret = all_ret[t-window:t]
    train_earn = all_earn[t-window:t]
    train_earn_month = all_earn_month[t-window:t]

    # Realized variance (squared return) for day t
    realized[i] = all_ret[t] ** 2

    # Baseline GJR-GARCH (use arch for speed — no exog needed)
    try:
        am = arch_model(pd.Series(train_ret), vol='GARCH', p=1, o=1, q=1, dist='t', mean='AR', lags=1)
        res = am.fit(disp='off', show_warning=False)
        fcast = res.forecast(horizon=1)
        fc_base[i] = fcast.variance.values[-1, 0]
    except:
        failures_base += 1

    # GARCH-X with earnings season dummy (custom MLE, warm start)
    try:
        bounds = [(-1, 1), (-0.5, 0.5), (1e-6, 1.0), (0, 0.5), (0, 0.5), (0, 0.999), (-0.5, 0.5), (2.1, 50)]
        res_opt = minimize(gjr_garch_x_loglik, prev_x_season,
                           args=(train_ret, train_earn, True),
                           method='L-BFGS-B', bounds=bounds,
                           options={'maxiter': 100, 'ftol': 1e-8})
        if res_opt.fun < 1e9:
            mu, phi, omega, alpha, gamma, beta, delta, nu = res_opt.x
            # Compute last eps and h
            n_t = len(train_ret)
            eps = np.zeros(n_t)
            h = np.zeros(n_t)
            h[0] = omega / max(1 - alpha - gamma/2 - beta, 0.01)
            eps[0] = train_ret[0] - mu
            for tt in range(1, n_t):
                eps[tt] = train_ret[tt] - mu - phi * train_ret[tt-1]
                h[tt] = (omega + alpha * eps[tt-1]**2
                         + gamma * (eps[tt-1] < 0) * eps[tt-1]**2
                         + beta * h[tt-1]
                         + delta * train_earn[tt])
                if h[tt] <= 0:
                    h[tt] = 1e-6
            h_forecast = (omega + alpha * eps[-1]**2
                          + gamma * (eps[-1] < 0) * eps[-1]**2
                          + beta * h[-1]
                          + delta * all_earn[t])
            fc_x[i] = max(h_forecast, 1e-6)
            prev_x_season = res_opt.x.copy()
        else:
            failures_x += 1
    except:
        failures_x += 1

    # GARCH-X with broader earnings month dummy (custom MLE, warm start)
    try:
        res_opt_m = minimize(gjr_garch_x_loglik, prev_x_month,
                             args=(train_ret, train_earn_month, True),
                             method='L-BFGS-B', bounds=bounds,
                             options={'maxiter': 100, 'ftol': 1e-8})
        if res_opt_m.fun < 1e9:
            mu, phi, omega, alpha, gamma, beta, delta, nu = res_opt_m.x
            n_t = len(train_ret)
            eps = np.zeros(n_t)
            h = np.zeros(n_t)
            h[0] = omega / max(1 - alpha - gamma/2 - beta, 0.01)
            eps[0] = train_ret[0] - mu
            for tt in range(1, n_t):
                eps[tt] = train_ret[tt] - mu - phi * train_ret[tt-1]
                h[tt] = (omega + alpha * eps[tt-1]**2
                         + gamma * (eps[tt-1] < 0) * eps[tt-1]**2
                         + beta * h[tt-1]
                         + delta * train_earn_month[tt])
                if h[tt] <= 0:
                    h[tt] = 1e-6
            h_forecast = (omega + alpha * eps[-1]**2
                          + gamma * (eps[-1] < 0) * eps[-1]**2
                          + beta * h[-1]
                          + delta * all_earn_month[t])
            fc_x_month[i] = max(h_forecast, 1e-6)
            prev_x_month = res_opt_m.x.copy()
        else:
            failures_xm += 1
    except:
        failures_xm += 1

    if (i + 1) % 100 == 0:
        print(f"  {i+1}/{n_oos} done...")

print(f"\nForecast failures: base={failures_base}, GARCH-X(season)={failures_x}, GARCH-X(month)={failures_xm}")

# ============================================================
# 7. EVALUATION
# ============================================================
print("\n" + "=" * 70)
print("PART 5: Forecast Evaluation")
print("=" * 70)

# Filter valid forecasts
valid = ~np.isnan(fc_base) & ~np.isnan(fc_x) & ~np.isnan(realized) & (realized > 0) & (fc_base > 0) & (fc_x > 0)
print(f"Valid forecast days: {valid.sum()}")

r = realized[valid]
fb = fc_base[valid]
fx = fc_x[valid]

valid_m = ~np.isnan(fc_base) & ~np.isnan(fc_x_month) & ~np.isnan(realized) & (realized > 0) & (fc_base > 0) & (fc_x_month > 0)
r_m = realized[valid_m]
fb_m = fc_base[valid_m]
fxm = fc_x_month[valid_m]

def qlike(actual, forecast):
    """QLIKE loss: log(forecast) + actual/forecast"""
    return np.mean(np.log(forecast) + actual / forecast)

def mse(actual, forecast):
    return np.mean((actual - forecast) ** 2)

def mae(actual, forecast):
    return np.mean(np.abs(actual - forecast))

# Main metrics
qlike_base = qlike(r, fb)
qlike_x = qlike(r, fx)
mse_base = mse(r, fb)
mse_x = mse(r, fx)
mae_base = mae(r, fb)
mae_x = mae(r, fx)

print(f"\n{'Model':<25} {'QLIKE':>10} {'MSE':>12} {'MAE':>10}")
print("-" * 60)
print(f"{'GJR-GARCH (base)':<25} {qlike_base:>10.6f} {mse_base:>12.6f} {mae_base:>10.6f}")
print(f"{'GJR-GARCH-X (season)':<25} {qlike_x:>10.6f} {mse_x:>12.6f} {mae_x:>10.6f}")

if valid_m.sum() > 0:
    qlike_xm = qlike(r_m, fxm)
    mse_xm = mse(r_m, fxm)
    mae_xm = mae(r_m, fxm)
    print(f"{'GJR-GARCH-X (month)':<25} {qlike_xm:>10.6f} {mse_xm:>12.6f} {mae_xm:>10.6f}")
else:
    qlike_xm = np.nan
    mse_xm = np.nan
    mae_xm = np.nan

# QLIKE improvement
qlike_improve = (qlike_base - qlike_x) / qlike_base * 100
print(f"\nQLIKE improvement (season): {qlike_improve:+.4f}%")
if not np.isnan(qlike_xm):
    qlike_improve_m = (qlike_base - qlike_xm) / qlike_base * 100
    print(f"QLIKE improvement (month):  {qlike_improve_m:+.4f}%")

# ============================================================
# 8. DIEBOLD-MARIANO TEST
# ============================================================
print("\n" + "=" * 70)
print("PART 6: Diebold-Mariano Test")
print("=" * 70)

def dm_test(actual, fc1, fc2, loss='qlike'):
    """DM test: H0: equal predictive accuracy, H1: fc1 != fc2"""
    if loss == 'qlike':
        d1 = np.log(fc1) + actual / fc1
        d2 = np.log(fc2) + actual / fc2
    elif loss == 'mse':
        d1 = (actual - fc1) ** 2
        d2 = (actual - fc2) ** 2
    else:
        d1 = np.abs(actual - fc1)
        d2 = np.abs(actual - fc2)

    d = d1 - d2  # positive = fc1 worse
    n = len(d)
    d_mean = d.mean()
    # HAC standard error (Newey-West with ~n^(1/3) lags)
    max_lag = int(np.ceil(n ** (1/3)))
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, max_lag + 1):
        w = 1 - k / (max_lag + 1)  # Bartlett kernel
        gamma_k = np.cov(d[k:], d[:-k], ddof=1)[0, 1]
        gamma_sum += 2 * w * gamma_k
    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        return 0, 1.0
    dm_stat = d_mean / np.sqrt(var_d)
    p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return dm_stat, p_val

# Base vs GARCH-X (season)
dm_q, p_q = dm_test(r, fb, fx, 'qlike')
dm_m, p_m = dm_test(r, fb, fx, 'mse')
print(f"\nBase vs GARCH-X (season):")
print(f"  DM (QLIKE): stat={dm_q:.4f}, p={p_q:.4f}")
print(f"  DM (MSE):   stat={dm_m:.4f}, p={p_m:.4f}")

# Base vs GARCH-X (month)
if valid_m.sum() > 100:
    dm_q_m, p_q_m = dm_test(r_m, fb_m, fxm, 'qlike')
    dm_m_m, p_m_m = dm_test(r_m, fb_m, fxm, 'mse')
    print(f"\nBase vs GARCH-X (month):")
    print(f"  DM (QLIKE): stat={dm_q_m:.4f}, p={p_q_m:.4f}")
    print(f"  DM (MSE):   stat={dm_m_m:.4f}, p={p_m_m:.4f}")
else:
    dm_q_m, p_q_m = np.nan, np.nan

# ============================================================
# 9. CONDITIONAL ANALYSIS — EARNINGS DAYS ONLY
# ============================================================
print("\n" + "=" * 70)
print("PART 7: Conditional Analysis — Forecasts on Earnings Days Only")
print("=" * 70)

oos_earnings_flag = all_earn[oos_start_idx:oos_start_idx+n_oos]
earn_mask = valid & (oos_earnings_flag == 1)
off_mask = valid & (oos_earnings_flag == 0)

if earn_mask.sum() > 10:
    qlike_base_earn = qlike(realized[earn_mask], fc_base[earn_mask])
    qlike_x_earn = qlike(realized[earn_mask], fc_x[earn_mask])
    qlike_base_off = qlike(realized[off_mask], fc_base[off_mask])
    qlike_x_off = qlike(realized[off_mask], fc_x[off_mask])

    print(f"\nEarnings days ({earn_mask.sum()}):")
    print(f"  QLIKE — Base: {qlike_base_earn:.6f}, GARCH-X: {qlike_x_earn:.6f}, diff: {qlike_base_earn-qlike_x_earn:+.6f}")
    print(f"\nOff-season days ({off_mask.sum()}):")
    print(f"  QLIKE — Base: {qlike_base_off:.6f}, GARCH-X: {qlike_x_off:.6f}, diff: {qlike_base_off-qlike_x_off:+.6f}")
else:
    qlike_base_earn = np.nan
    qlike_x_earn = np.nan
    qlike_base_off = np.nan
    qlike_x_off = np.nan
    print("  Insufficient earnings days in OOS for conditional analysis")

# ============================================================
# 10. EARNINGS SEASON VIX SEASONAL DECOMPOSITION
# ============================================================
print("\n" + "=" * 70)
print("PART 8: VIX Seasonal Decomposition Around Earnings")
print("=" * 70)

# Compute average VIX by day-within-earnings-period
# For each earnings month (1,4,7,10), compute avg VIX by day-of-month
earn_months_data = df[df.index.month.isin([1, 4, 7, 10])]
daily_vix = earn_months_data.groupby(earn_months_data.index.day)['vix'].agg(['mean', 'std', 'count'])
print(f"\nAvg VIX by day-of-month during earnings months:")
print(f"{'Day':<5} {'Mean VIX':>10} {'Std':>8} {'N':>5}")
print("-" * 30)
for day in sorted(daily_vix.index):
    if daily_vix.loc[day, 'count'] > 20:
        print(f"{day:<5} {daily_vix.loc[day, 'mean']:>10.2f} {daily_vix.loc[day, 'std']:>8.2f} {daily_vix.loc[day, 'count']:>5.0f}")

# Pre/during/post earnings VIX levels
df['earn_period'] = 'off'
for idx in df.index:
    m = idx.month
    d = idx.day
    wom = (d - 1) // 7 + 1
    if m in [1, 4, 7, 10]:
        if wom in [1, 2]:
            df.loc[idx, 'earn_period'] = 'pre'
        elif wom in [3, 4]:
            df.loc[idx, 'earn_period'] = 'during'
    elif m in [2, 5, 8, 11]:
        if wom in [1, 2]:
            df.loc[idx, 'earn_period'] = 'post'

period_vix = df.groupby('earn_period')['vix'].agg(['mean', 'std', 'count'])
print(f"\nVIX by earnings period:")
for p in ['pre', 'during', 'post', 'off']:
    if p in period_vix.index:
        print(f"  {p:<8}: mean={period_vix.loc[p, 'mean']:.2f}, std={period_vix.loc[p, 'std']:.2f}, n={period_vix.loc[p, 'count']:.0f}")

# ANOVA on VIX levels
vix_groups = [df[df['earn_period'] == p]['vix'].dropna() for p in ['pre', 'during', 'post', 'off']]
f_vix, p_vix_anova = stats.f_oneway(*vix_groups)
print(f"\nANOVA (VIX levels across periods): F={f_vix:.4f}, p={p_vix_anova:.4f}")

# ============================================================
# 11. YEARLY CONSISTENCY CHECK
# ============================================================
print("\n" + "=" * 70)
print("PART 9: Yearly Consistency of Earnings Vol Effect")
print("=" * 70)

years = sorted(df.index.year.unique())
yearly_diffs = []
print(f"\n{'Year':<6} {'Earn Vol%':>10} {'Off Vol%':>10} {'Ratio':>8} {'t':>8} {'p':>8}")
print("-" * 55)
for yr in years:
    sub = df[df.index.year == yr]
    e = sub[sub['earnings_season'] == 1]
    o = sub[sub['earnings_season'] == 0]
    if len(e) < 5 or len(o) < 20:
        continue
    ev = e['abs_ret'].mean()
    ov = o['abs_ret'].mean()
    r_yr = ev / ov
    t_yr, p_yr = stats.ttest_ind(e['abs_ret'], o['abs_ret'], equal_var=False)
    sig = '*' if p_yr < 0.05 else ''
    print(f"{yr:<6} {ev:>10.3f} {ov:>10.3f} {r_yr:>8.3f} {t_yr:>8.3f} {p_yr:>8.4f} {sig}")
    yearly_diffs.append(r_yr)

earn_higher = sum(1 for r in yearly_diffs if r > 1)
print(f"\nYears with earnings vol > off-season: {earn_higher}/{len(yearly_diffs)} ({earn_higher/len(yearly_diffs)*100:.0f}%)")

# ============================================================
# 12. SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("K498 SUMMARY")
print("=" * 70)

print(f"""
Data: SPY + ^VIX daily, 2005-2026, yfinance ({n_total} trading days)
OOS: {oos_dates[0].date()} to {oos_dates[-1].date()} ({n_oos} days)

1. DESCRIPTIVE:
   - Earnings season vol ratio: {ratio:.3f} (earnings {'higher' if ratio > 1 else 'LOWER'})
   - Welch t-test: t={t_welch:.3f}, p={p_welch:.4f} {'SIGNIFICANT' if p_welch < 0.05 else 'NOT SIG'}
   - Levene test: stat={lev_stat:.3f}, p={lev_p:.4f}

2. VIX:
   - Earnings VIX: {vix_earn.mean():.2f}, Off-season: {vix_off.mean():.2f}
   - VIX t-test: t={t_vix:.3f}, p={p_vix:.4f}

3. GARCH-X MODEL (full sample):
   - Earnings season dummy: delta={x_coef:.6f}, t={x_tstat:.4f}, p={x_pval:.4f}
   - Earnings month dummy:  delta={xm_coef:.6f}, t={xm_tstat:.4f}, p={xm_pval:.4f}
   - LR test (season): {lr_stat:.4f}, p={lr_pval:.4f}
   - LR test (month):  {lr_stat_m:.4f}, p={lr_pval_m:.4f}
   - BIC prefers: {bic_prefers}

4. OOS QLIKE:
   - Baseline: {qlike_base:.6f}
   - GARCH-X (season): {qlike_x:.6f} ({qlike_improve:+.4f}%)
   - DM test (QLIKE): stat={dm_q:.4f}, p={p_q:.4f}

5. CONCLUSION:
""")

if p_welch > 0.05 and x_pval > 0.05 and p_q > 0.05:
    conclusion = ("NULL RESULT — Earnings season has no systematic effect on SPY vol. "
                  "Consistent with K412. Index diversification absorbs individual stock "
                  "earnings effects. GARCH-X with earnings dummy does not improve forecasts.")
elif qlike_improve > 0 and p_q < 0.05:
    conclusion = ("POSITIVE — Earnings dummy significantly improves GARCH vol forecasts. "
                  "This contradicts K412 descriptive results and suggests GARCH-X captures "
                  "conditional earnings effects not visible in raw vol comparison.")
else:
    conclusion = (f"MIXED — Descriptive p={p_welch:.4f}, GARCH-X coef p={x_pval:.4f}, "
                  f"OOS DM p={p_q:.4f}. Effect may exist but is too weak to be practically useful.")

print(f"   {conclusion}")

# ============================================================
# SAVE RESULTS
# ============================================================
results = {
    'experiment': 'K498',
    'title': 'Earnings Season Volatility Patterns — GARCH-X Extension',
    'category': 'seasonality',
    'data_source': 'yfinance',
    'assets': ['SPY', '^VIX'],
    'sample_period': f"{df.index[0].date()} to {df.index[-1].date()}",
    'n_total_days': n_total,
    'n_earnings_days': int(n_earn),
    'oos_period': f"{oos_dates[0].date()} to {oos_dates[-1].date()}",
    'n_oos_days': n_oos,
    'rolling_window': window,
    'prior_knowledge': 'K412/K923: SPY earnings/non-earnings vol ratio=0.96x (p=0.615), null at index level',

    'descriptive': {
        'earnings_mean_abs_ret_pct': round(float(earn_vol), 4),
        'off_season_mean_abs_ret_pct': round(float(off_vol), 4),
        'vol_ratio': round(float(ratio), 4),
        'welch_t': round(float(t_welch), 4),
        'welch_p': round(float(p_welch), 4),
        'levene_stat': round(float(lev_stat), 4),
        'levene_p': round(float(lev_p), 4),
        'variance_ratio_F': round(float(f_ratio), 4),
        'annualized_vol_earnings': round(float(earn_ann_vol), 2),
        'annualized_vol_off_season': round(float(off_ann_vol), 2),
    },

    'vix_analysis': {
        'vix_earnings_mean': round(float(vix_earn.mean()), 2),
        'vix_off_season_mean': round(float(vix_off.mean()), 2),
        'vix_t_stat': round(float(t_vix), 4),
        'vix_p_val': round(float(p_vix), 4),
        'vix_change_earnings_mean': round(float(vix_chg_earn.mean()), 4),
        'vix_change_off_season_mean': round(float(vix_chg_off.mean()), 4),
        'vix_change_t': round(float(t_vchg), 4),
        'vix_change_p': round(float(p_vchg), 4),
        'vix_anova_F': round(float(f_vix), 4),
        'vix_anova_p': round(float(p_vix_anova), 4),
    },

    'garch_x_full_sample': {
        'baseline_bic': round(float(bic_custom_base), 2),
        'garch_x_season_bic': round(float(bic_custom_x), 2),
        'garch_x_month_bic': round(float(bic_custom_xm), 2),
        'bic_prefers': bic_prefers,
        'earnings_season_dummy_coef': round(float(x_coef), 6),
        'earnings_season_dummy_tstat': round(float(x_tstat), 4),
        'earnings_season_dummy_pval': round(float(x_pval), 4),
        'earnings_month_dummy_coef': round(float(xm_coef), 6),
        'earnings_month_dummy_tstat': round(float(xm_tstat), 4),
        'earnings_month_dummy_pval': round(float(xm_pval), 4),
        'lr_test_season': round(float(lr_stat), 4),
        'lr_pval_season': round(float(lr_pval), 4),
        'lr_test_month': round(float(lr_stat_m), 4),
        'lr_pval_month': round(float(lr_pval_m), 4),
        'persistence_base': round(float(pers_base), 4),
    },

    'oos_evaluation': {
        'n_valid_forecasts': int(valid.sum()),
        'qlike_base': round(float(qlike_base), 6),
        'qlike_garch_x_season': round(float(qlike_x), 6),
        'qlike_garch_x_month': round(float(qlike_xm), 6) if not np.isnan(qlike_xm) else None,
        'qlike_improvement_season_pct': round(float(qlike_improve), 4),
        'mse_base': round(float(mse_base), 6),
        'mse_garch_x_season': round(float(mse_x), 6),
        'mae_base': round(float(mae_base), 6),
        'mae_garch_x_season': round(float(mae_x), 6),
        'dm_test_qlike': {'stat': round(float(dm_q), 4), 'p': round(float(p_q), 4)},
        'dm_test_mse': {'stat': round(float(dm_m), 4), 'p': round(float(p_m), 4)},
        'dm_test_month_qlike': {'stat': round(float(dm_q_m), 4), 'p': round(float(p_q_m), 4)} if not np.isnan(dm_q_m) else None,
    },

    'conditional_analysis': {
        'earnings_days_qlike_base': round(float(qlike_base_earn), 6) if not np.isnan(qlike_base_earn) else None,
        'earnings_days_qlike_x': round(float(qlike_x_earn), 6) if not np.isnan(qlike_x_earn) else None,
        'off_season_qlike_base': round(float(qlike_base_off), 6) if not np.isnan(qlike_base_off) else None,
        'off_season_qlike_x': round(float(qlike_x_off), 6) if not np.isnan(qlike_x_off) else None,
    },

    'yearly_consistency': {
        'years_earnings_higher': earn_higher,
        'total_years': len(yearly_diffs),
        'pct_higher': round(earn_higher / len(yearly_diffs) * 100, 1) if yearly_diffs else None,
    },

    'conclusion': conclusion,
    'rating': '★',  # null expected based on K412
    'references': [
        'K412/K923: Earnings Season Effect on Index Volatility (null at index level)',
        'Savor & Wilson (2016) Earnings Announcements and Systematic Risk, JFE',
        'Barber et al. (2013) Aggregate earnings surprises and stock returns',
    ],
    'timestamp': datetime.now(timezone.utc).isoformat(),
}

with open('experiments/k498_earnings_vol_results.json', 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to experiments/k498_earnings_vol_results.json")
print(f"Script saved to experiments/k498_earnings_vol.py")
