"""
K402: COVID Structural Break — What Changed PERMANENTLY in Vol Dynamics?
========================================================================
[提出: Claude, 執行: Claude]

Pre-experiment check: K392 found 10 post-2020 changes. K393 gamma trajectory.
But never formally tested which COVID changes are PERMANENT vs temporary.

Data: SPY, VIX daily from yfinance.
Split: pre-COVID (2005-2019) vs post-COVID (2021-2024). Exclude 2020 as transition.

Methodology: 8 structural break hypotheses tested with proper statistics.
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime
import json
import warnings
warnings.filterwarnings('ignore')

print("=" * 80)
print("K402: COVID Structural Break — What Changed PERMANENTLY in Vol Dynamics?")
print("=" * 80)

# ─── Data Download ───────────────────────────────────────────────────────────
print("\n[1] Downloading data from yfinance...")

spy = yf.download("SPY", start="2005-01-01", end="2025-01-01", auto_adjust=False)
vix = yf.download("^VIX", start="2005-01-01", end="2025-01-01", auto_adjust=False)
gld = yf.download("GLD", start="2005-01-01", end="2025-01-01", auto_adjust=False)

# Flatten multi-level columns if present
for df in [spy, vix, gld]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

print(f"  SPY: {spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')} ({len(spy)} days)")
print(f"  VIX: {vix.index[0].strftime('%Y-%m-%d')} to {vix.index[-1].strftime('%Y-%m-%d')} ({len(vix)} days)")
print(f"  GLD: {gld.index[0].strftime('%Y-%m-%d')} to {gld.index[-1].strftime('%Y-%m-%d')} ({len(gld)} days)")

# ─── Define Periods ─────────────────────────────────────────────────────────
pre_start, pre_end = "2005-01-01", "2019-12-31"
post_start, post_end = "2021-01-01", "2024-12-31"

spy_pre = spy.loc[pre_start:pre_end].copy()
spy_post = spy.loc[post_start:post_end].copy()
vix_pre = vix.loc[pre_start:pre_end].copy()
vix_post = vix.loc[post_start:post_end].copy()
gld_pre = gld.loc[pre_start:pre_end].copy()
gld_post = gld.loc[post_start:post_end].copy()

print(f"\n  Pre-COVID:  {pre_start} to {pre_end} (SPY: {len(spy_pre)} days)")
print(f"  Post-COVID: {post_start} to {post_end} (SPY: {len(spy_post)} days)")
print(f"  Excluded:   2020 (COVID transition year)")

# Compute returns
spy_pre['ret'] = np.log(spy_pre['Close'] / spy_pre['Close'].shift(1))
spy_post['ret'] = np.log(spy_post['Close'] / spy_post['Close'].shift(1))
spy_pre['abs_ret'] = spy_pre['ret'].abs()
spy_post['abs_ret'] = spy_post['ret'].abs()

# Full SPY for rolling analyses
spy_full = spy.copy()
spy_full['ret'] = np.log(spy_full['Close'] / spy_full['Close'].shift(1))

results = {}

# ═══════════════════════════════════════════════════════════════════════════
# Hypothesis A: Mean VIX Level Changed?
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("Hypothesis A: Mean VIX Level Changed?")
print("=" * 80)

vix_pre_close = vix_pre['Close'].dropna().values.flatten()
vix_post_close = vix_post['Close'].dropna().values.flatten()

t_stat_a, p_val_a = stats.ttest_ind(vix_pre_close, vix_post_close, equal_var=False)
# Also Welch t-test (same as above with equal_var=False)
mean_pre = np.mean(vix_pre_close)
mean_post = np.mean(vix_post_close)
std_pre = np.std(vix_pre_close, ddof=1)
std_post = np.std(vix_post_close, ddof=1)
effect_size_a = (mean_post - mean_pre) / np.sqrt((std_pre**2 + std_post**2) / 2)  # Cohen's d

print(f"  Pre-COVID  mean VIX: {mean_pre:.2f} (std: {std_pre:.2f}, n={len(vix_pre_close)})")
print(f"  Post-COVID mean VIX: {mean_post:.2f} (std: {std_post:.2f}, n={len(vix_post_close)})")
print(f"  Welch t-test: t={t_stat_a:.3f}, p={p_val_a:.6f}")
print(f"  Cohen's d: {effect_size_a:.3f}")
print(f"  Direction: VIX {'higher' if mean_post > mean_pre else 'lower'} post-COVID")

# Check year-by-year trend to assess permanence
print("\n  Year-by-year VIX mean:")
for yr in range(2005, 2025):
    yr_data = vix.loc[str(yr)]['Close'].dropna().values.flatten()
    if len(yr_data) > 0:
        marker = " <<<" if yr == 2020 else ""
        print(f"    {yr}: {np.mean(yr_data):.2f} (std: {np.std(yr_data, ddof=1):.2f}, n={len(yr_data)}){marker}")

# Is post-COVID VIX declining back toward pre-COVID levels?
vix_2021 = np.mean(vix.loc['2021']['Close'].dropna().values.flatten())
vix_2022 = np.mean(vix.loc['2022']['Close'].dropna().values.flatten())
vix_2023 = np.mean(vix.loc['2023']['Close'].dropna().values.flatten())
vix_2024 = np.mean(vix.loc['2024']['Close'].dropna().values.flatten())
trend_declining = vix_2024 < vix_2021

results['A_mean_vix'] = {
    'hypothesis': 'Mean VIX level changed',
    'pre_mean': round(float(mean_pre), 2),
    'post_mean': round(float(mean_post), 2),
    't_stat': round(float(t_stat_a), 3),
    'p_value': round(float(p_val_a), 6),
    'cohens_d': round(float(effect_size_a), 3),
    'significant': p_val_a < 0.05,
    'permanent': not trend_declining,
    'assessment': 'TEMPORARY — VIX declining back toward pre-COVID levels' if trend_declining else 'PERMANENT — VIX elevated post-COVID'
}

# ═══════════════════════════════════════════════════════════════════════════
# Hypothesis B: Vol Clustering (ACF) Changed?
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("Hypothesis B: Vol Clustering (ACF of |returns|) Changed?")
print("=" * 80)

def compute_acf(series, nlags=20):
    """Compute autocorrelation function."""
    series = series.dropna().values.flatten()
    n = len(series)
    mean = np.mean(series)
    var = np.var(series)
    acf_vals = []
    for lag in range(1, nlags + 1):
        cov = np.mean((series[lag:] - mean) * (series[:-lag] - mean))
        acf_vals.append(cov / var)
    return np.array(acf_vals)

lags_to_check = [1, 5, 10, 20]
nlags = 20
acf_pre = compute_acf(spy_pre['abs_ret'].dropna(), nlags)
acf_post = compute_acf(spy_post['abs_ret'].dropna(), nlags)

print(f"  ACF of |returns| at selected lags:")
print(f"  {'Lag':>5} {'Pre-COVID':>12} {'Post-COVID':>12} {'Change':>10}")
for lag in lags_to_check:
    change = acf_post[lag-1] - acf_pre[lag-1]
    print(f"  {lag:>5} {acf_pre[lag-1]:>12.4f} {acf_post[lag-1]:>12.4f} {change:>+10.4f}")

# Bootstrap comparison at lag-1
def bootstrap_acf_lag1(series, n_boot=5000):
    """Bootstrap ACF(1) of absolute returns."""
    series = series.dropna().values.flatten()
    n = len(series)
    acf1_boots = []
    for _ in range(n_boot):
        # Block bootstrap (block size = 20) to preserve serial dependence
        block_size = 20
        n_blocks = n // block_size + 1
        indices = np.concatenate([
            np.arange(start, min(start + block_size, n))
            for start in np.random.randint(0, n - block_size, size=n_blocks)
        ])[:n]
        boot_sample = series[indices]
        abs_boot = np.abs(boot_sample)
        mean_b = np.mean(abs_boot)
        var_b = np.var(abs_boot)
        if var_b > 0:
            cov1 = np.mean((abs_boot[1:] - mean_b) * (abs_boot[:-1] - mean_b))
            acf1_boots.append(cov1 / var_b)
    return np.array(acf1_boots)

print("\n  Bootstrap comparison of ACF(1) of |returns| (5000 reps, block bootstrap)...")
boot_pre = bootstrap_acf_lag1(spy_pre['ret'], n_boot=5000)
boot_post = bootstrap_acf_lag1(spy_post['ret'], n_boot=5000)

diff_boot = boot_post - boot_pre[:len(boot_post)]
p_val_b = np.mean(diff_boot < 0) if np.mean(acf_post[0]) > np.mean(acf_pre[0]) else np.mean(diff_boot > 0)
# Two-sided
p_val_b_2sided = 2 * min(np.mean(diff_boot > 0), np.mean(diff_boot < 0))

print(f"  Pre-COVID  ACF(1) mean: {np.mean(boot_pre):.4f} [{np.percentile(boot_pre, 2.5):.4f}, {np.percentile(boot_pre, 97.5):.4f}]")
print(f"  Post-COVID ACF(1) mean: {np.mean(boot_post):.4f} [{np.percentile(boot_post, 2.5):.4f}, {np.percentile(boot_post, 97.5):.4f}]")
print(f"  Bootstrap p-value (two-sided): {p_val_b_2sided:.4f}")

results['B_vol_clustering'] = {
    'hypothesis': 'Vol clustering (ACF) changed',
    'pre_acf1': round(float(acf_pre[0]), 4),
    'post_acf1': round(float(acf_post[0]), 4),
    'bootstrap_p_2sided': round(float(p_val_b_2sided), 4),
    'significant': p_val_b_2sided < 0.05,
    'direction': 'stronger' if acf_post[0] > acf_pre[0] else 'weaker',
    'assessment': ''
}

# ═══════════════════════════════════════════════════════════════════════════
# Hypothesis C: Leverage Effect (Gamma) Changed?
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("Hypothesis C: Leverage Effect (Gamma) Changed?")
print("=" * 80)

def estimate_gamma(returns):
    """Estimate leverage effect gamma = corr(r_t, sigma^2_{t+1}).
    Using simple proxy: gamma = corr(r_t, r_{t+1}^2)"""
    returns = returns.dropna().values.flatten()
    r_t = returns[:-1]
    r_t1_sq = returns[1:] ** 2
    # Remove any inf/nan
    mask = np.isfinite(r_t) & np.isfinite(r_t1_sq)
    r_t = r_t[mask]
    r_t1_sq = r_t1_sq[mask]
    gamma = np.corrcoef(r_t, r_t1_sq)[0, 1]
    return gamma

gamma_pre = estimate_gamma(spy_pre['ret'])
gamma_post = estimate_gamma(spy_post['ret'])

print(f"  Pre-COVID  gamma (corr(r_t, r²_t+1)): {gamma_pre:.4f}")
print(f"  Post-COVID gamma (corr(r_t, r²_t+1)): {gamma_post:.4f}")

# Bootstrap comparison
def bootstrap_gamma(returns, n_boot=5000):
    returns = returns.dropna().values.flatten()
    n = len(returns)
    gammas = []
    for _ in range(n_boot):
        # Block bootstrap
        block_size = 50
        n_blocks = n // block_size + 1
        indices = np.concatenate([
            np.arange(start, min(start + block_size, n))
            for start in np.random.randint(0, n - block_size, size=n_blocks)
        ])[:n]
        boot_ret = returns[indices]
        r_t = boot_ret[:-1]
        r_t1_sq = boot_ret[1:] ** 2
        mask = np.isfinite(r_t) & np.isfinite(r_t1_sq)
        if np.sum(mask) > 10:
            gammas.append(np.corrcoef(r_t[mask], r_t1_sq[mask])[0, 1])
    return np.array(gammas)

print("  Bootstrap comparison (5000 reps, block bootstrap)...")
boot_gamma_pre = bootstrap_gamma(spy_pre['ret'], 5000)
boot_gamma_post = bootstrap_gamma(spy_post['ret'], 5000)

diff_gamma = boot_gamma_post - boot_gamma_pre[:len(boot_gamma_post)]
p_val_c = 2 * min(np.mean(diff_gamma > 0), np.mean(diff_gamma < 0))

print(f"  Pre-COVID  gamma: {np.mean(boot_gamma_pre):.4f} [{np.percentile(boot_gamma_pre, 2.5):.4f}, {np.percentile(boot_gamma_pre, 97.5):.4f}]")
print(f"  Post-COVID gamma: {np.mean(boot_gamma_post):.4f} [{np.percentile(boot_gamma_post, 2.5):.4f}, {np.percentile(boot_gamma_post, 97.5):.4f}]")
print(f"  Bootstrap p-value (two-sided): {p_val_c:.4f}")

# Year-by-year gamma
print("\n  Year-by-year gamma:")
for yr in range(2005, 2025):
    yr_ret = spy_full.loc[str(yr)]['ret'].dropna()
    if len(yr_ret) > 20:
        g = estimate_gamma(yr_ret)
        marker = " <<<" if yr == 2020 else ""
        print(f"    {yr}: {g:.4f}{marker}")

results['C_leverage_effect'] = {
    'hypothesis': 'Leverage effect (gamma) changed',
    'pre_gamma': round(float(gamma_pre), 4),
    'post_gamma': round(float(gamma_post), 4),
    'bootstrap_p_2sided': round(float(p_val_c), 4),
    'significant': p_val_c < 0.05,
    'direction': 'stronger (more negative)' if gamma_post < gamma_pre else 'weaker (less negative)',
    'assessment': ''
}

# ═══════════════════════════════════════════════════════════════════════════
# Hypothesis D: Overnight Return Fraction Changed?
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("Hypothesis D: Overnight Return Fraction Changed?")
print("=" * 80)

def compute_overnight_fraction(df):
    """Compute what fraction of daily variance comes from overnight gap."""
    close_to_close = np.log(df['Close'] / df['Close'].shift(1))
    open_to_close = np.log(df['Close'] / df['Open'])
    overnight = np.log(df['Open'] / df['Close'].shift(1))

    close_to_close = close_to_close.dropna().values.flatten()
    open_to_close = open_to_close.dropna().values.flatten()
    overnight = overnight.dropna().values.flatten()

    var_cc = np.var(close_to_close)
    var_oc = np.var(open_to_close)
    var_on = np.var(overnight)

    return var_on / var_cc, var_on, var_oc, var_cc

on_frac_pre, var_on_pre, var_oc_pre, var_cc_pre = compute_overnight_fraction(spy_pre)
on_frac_post, var_on_post, var_oc_post, var_cc_post = compute_overnight_fraction(spy_post)

print(f"  Pre-COVID:  Overnight var fraction = {on_frac_pre:.4f} ({on_frac_pre*100:.1f}%)")
print(f"              Overnight var = {var_on_pre*10000:.4f} bps²  Intraday var = {var_oc_pre*10000:.4f} bps²")
print(f"  Post-COVID: Overnight var fraction = {on_frac_post:.4f} ({on_frac_post*100:.1f}%)")
print(f"              Overnight var = {var_on_post*10000:.4f} bps²  Intraday var = {var_oc_post*10000:.4f} bps²")

# Bootstrap the fraction difference
def bootstrap_overnight_fraction(df, n_boot=5000):
    close_to_close = np.log(df['Close'] / df['Close'].shift(1)).dropna().values.flatten()
    overnight = np.log(df['Open'] / df['Close'].shift(1)).dropna().values.flatten()
    n = min(len(close_to_close), len(overnight))
    close_to_close = close_to_close[:n]
    overnight = overnight[:n]
    fracs = []
    for _ in range(n_boot):
        idx = np.random.randint(0, n, size=n)
        var_cc = np.var(close_to_close[idx])
        var_on = np.var(overnight[idx])
        if var_cc > 0:
            fracs.append(var_on / var_cc)
    return np.array(fracs)

print("  Bootstrap comparison (5000 reps)...")
boot_on_pre = bootstrap_overnight_fraction(spy_pre, 5000)
boot_on_post = bootstrap_overnight_fraction(spy_post, 5000)
diff_on = boot_on_post - boot_on_pre[:len(boot_on_post)]
p_val_d = 2 * min(np.mean(diff_on > 0), np.mean(diff_on < 0))

print(f"  Pre-COVID  fraction: {np.mean(boot_on_pre):.4f} [{np.percentile(boot_on_pre, 2.5):.4f}, {np.percentile(boot_on_pre, 97.5):.4f}]")
print(f"  Post-COVID fraction: {np.mean(boot_on_post):.4f} [{np.percentile(boot_on_post, 2.5):.4f}, {np.percentile(boot_on_post, 97.5):.4f}]")
print(f"  Bootstrap p-value (two-sided): {p_val_d:.4f}")

# Year-by-year
print("\n  Year-by-year overnight variance fraction:")
for yr in range(2005, 2025):
    yr_data = spy.loc[str(yr)]
    if len(yr_data) > 20:
        frac, _, _, _ = compute_overnight_fraction(yr_data)
        marker = " <<<" if yr == 2020 else ""
        print(f"    {yr}: {frac:.4f} ({frac*100:.1f}%){marker}")

results['D_overnight_fraction'] = {
    'hypothesis': 'Overnight return fraction changed',
    'pre_fraction': round(float(on_frac_pre), 4),
    'post_fraction': round(float(on_frac_post), 4),
    'bootstrap_p_2sided': round(float(p_val_d), 4),
    'significant': p_val_d < 0.05,
    'direction': 'larger overnight fraction' if on_frac_post > on_frac_pre else 'smaller overnight fraction',
    'assessment': ''
}

# ═══════════════════════════════════════════════════════════════════════════
# Hypothesis E: SPY-GLD Correlation Changed?
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("Hypothesis E: SPY-GLD Correlation Changed?")
print("=" * 80)

# Align dates
spy_gld_pre = spy_pre[['ret']].join(
    pd.DataFrame({'gld_ret': np.log(gld_pre['Close'] / gld_pre['Close'].shift(1))}, index=gld_pre.index),
    how='inner'
).dropna()

spy_gld_post = spy_post[['ret']].join(
    pd.DataFrame({'gld_ret': np.log(gld_post['Close'] / gld_post['Close'].shift(1))}, index=gld_post.index),
    how='inner'
).dropna()

corr_pre = spy_gld_pre['ret'].values.flatten()
corr_gld_pre = spy_gld_pre['gld_ret'].values.flatten()
rho_pre = np.corrcoef(corr_pre, corr_gld_pre)[0, 1]

corr_post = spy_gld_post['ret'].values.flatten()
corr_gld_post = spy_gld_post['gld_ret'].values.flatten()
rho_post = np.corrcoef(corr_post, corr_gld_post)[0, 1]

# Fisher z-test for correlation comparison
def fisher_z_test(r1, n1, r2, n2):
    z1 = np.arctanh(r1)
    z2 = np.arctanh(r2)
    se = np.sqrt(1/(n1-3) + 1/(n2-3))
    z_stat = (z1 - z2) / se
    p_val = 2 * (1 - stats.norm.cdf(abs(z_stat)))
    return z_stat, p_val

z_stat_e, p_val_e = fisher_z_test(rho_pre, len(corr_pre), rho_post, len(corr_post))

print(f"  Pre-COVID  SPY-GLD correlation: {rho_pre:.4f} (n={len(corr_pre)})")
print(f"  Post-COVID SPY-GLD correlation: {rho_post:.4f} (n={len(corr_post)})")
print(f"  Fisher z-test: z={z_stat_e:.3f}, p={p_val_e:.6f}")

# Year-by-year
print("\n  Year-by-year SPY-GLD correlation:")
for yr in range(2005, 2025):
    spy_yr = spy.loc[str(yr)]
    gld_yr = gld.loc[str(yr)]
    spy_ret_yr = np.log(spy_yr['Close'] / spy_yr['Close'].shift(1))
    gld_ret_yr = np.log(gld_yr['Close'] / gld_yr['Close'].shift(1))
    combined = pd.DataFrame({'spy': spy_ret_yr, 'gld': gld_ret_yr}).dropna()
    if len(combined) > 20:
        r = np.corrcoef(combined['spy'].values.flatten(), combined['gld'].values.flatten())[0, 1]
        marker = " <<<" if yr == 2020 else ""
        print(f"    {yr}: {r:.4f}{marker}")

results['E_spy_gld_corr'] = {
    'hypothesis': 'SPY-GLD correlation changed',
    'pre_correlation': round(float(rho_pre), 4),
    'post_correlation': round(float(rho_post), 4),
    'fisher_z': round(float(z_stat_e), 3),
    'p_value': round(float(p_val_e), 6),
    'significant': p_val_e < 0.05,
    'direction': 'more positive' if rho_post > rho_pre else 'more negative',
    'assessment': ''
}

# ═══════════════════════════════════════════════════════════════════════════
# Hypothesis F: VIX Mean-Reversion Speed Changed?
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("Hypothesis F: VIX Mean-Reversion Speed Changed?")
print("=" * 80)

def estimate_mr_speed(vix_close):
    """Estimate mean-reversion speed via AR(1): VIX_t = c + phi * VIX_{t-1} + e.
    Mean-reversion speed = 1 - phi (higher = faster reversion)."""
    vix_vals = vix_close.dropna().values.flatten()
    y = vix_vals[1:]
    x = vix_vals[:-1]
    # OLS
    n = len(y)
    x_mean = np.mean(x)
    y_mean = np.mean(y)
    phi = np.sum((x - x_mean) * (y - y_mean)) / np.sum((x - x_mean)**2)
    c = y_mean - phi * x_mean
    mr_speed = 1 - phi
    # Half-life in days
    if phi > 0 and phi < 1:
        half_life = -np.log(2) / np.log(phi)
    else:
        half_life = np.inf
    return phi, c, mr_speed, half_life

phi_pre, c_pre, mr_pre, hl_pre = estimate_mr_speed(vix_pre['Close'])
phi_post, c_post, mr_post, hl_post = estimate_mr_speed(vix_post['Close'])

print(f"  Pre-COVID:  phi={phi_pre:.4f}, MR speed={mr_pre:.4f}, half-life={hl_pre:.1f} days")
print(f"  Post-COVID: phi={phi_post:.4f}, MR speed={mr_post:.4f}, half-life={hl_post:.1f} days")

# Bootstrap
def bootstrap_mr(vix_close, n_boot=5000):
    vix_vals = vix_close.dropna().values.flatten()
    n = len(vix_vals)
    phis = []
    for _ in range(n_boot):
        # Block bootstrap to preserve serial dependence
        block_size = 50
        n_blocks = n // block_size + 1
        indices = np.concatenate([
            np.arange(start, min(start + block_size, n))
            for start in np.random.randint(0, n - block_size, size=n_blocks)
        ])[:n]
        boot_vix = vix_vals[indices]
        y = boot_vix[1:]
        x = boot_vix[:-1]
        x_mean = np.mean(x)
        y_mean = np.mean(y)
        denom = np.sum((x - x_mean)**2)
        if denom > 0:
            phi = np.sum((x - x_mean) * (y - y_mean)) / denom
            phis.append(phi)
    return np.array(phis)

print("  Bootstrap comparison (5000 reps, block bootstrap)...")
boot_phi_pre = bootstrap_mr(vix_pre['Close'], 5000)
boot_phi_post = bootstrap_mr(vix_post['Close'], 5000)

diff_phi = boot_phi_post - boot_phi_pre[:len(boot_phi_post)]
p_val_f = 2 * min(np.mean(diff_phi > 0), np.mean(diff_phi < 0))

print(f"  Pre-COVID  phi: {np.mean(boot_phi_pre):.4f} [{np.percentile(boot_phi_pre, 2.5):.4f}, {np.percentile(boot_phi_pre, 97.5):.4f}]")
print(f"  Post-COVID phi: {np.mean(boot_phi_post):.4f} [{np.percentile(boot_phi_post, 2.5):.4f}, {np.percentile(boot_phi_post, 97.5):.4f}]")
print(f"  Bootstrap p-value (two-sided): {p_val_f:.4f}")

# Year-by-year
print("\n  Year-by-year VIX AR(1) phi:")
for yr in range(2005, 2025):
    yr_vix = vix.loc[str(yr)]['Close'].dropna()
    if len(yr_vix) > 20:
        phi_yr, _, _, hl_yr = estimate_mr_speed(yr_vix)
        marker = " <<<" if yr == 2020 else ""
        print(f"    {yr}: phi={phi_yr:.4f}, half-life={hl_yr:.1f} days{marker}")

results['F_mr_speed'] = {
    'hypothesis': 'VIX mean-reversion speed changed',
    'pre_phi': round(float(phi_pre), 4),
    'post_phi': round(float(phi_post), 4),
    'pre_halflife_days': round(float(hl_pre), 1),
    'post_halflife_days': round(float(hl_post), 1),
    'bootstrap_p_2sided': round(float(p_val_f), 4),
    'significant': p_val_f < 0.05,
    'direction': 'faster reversion' if phi_post < phi_pre else 'slower reversion',
    'assessment': ''
}

# ═══════════════════════════════════════════════════════════════════════════
# Hypothesis G: Day-of-Week Patterns Changed?
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("Hypothesis G: Day-of-Week Volatility Patterns Changed?")
print("=" * 80)

spy_pre['dow'] = spy_pre.index.dayofweek
spy_post['dow'] = spy_post.index.dayofweek

dow_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
print(f"  {'Day':>5} {'Pre |ret| (bps)':>16} {'Post |ret| (bps)':>17} {'Change':>10}")

dow_pre_vols = []
dow_post_vols = []
for d in range(5):
    pre_d = spy_pre[spy_pre['dow'] == d]['abs_ret'].dropna().values.flatten() * 10000
    post_d = spy_post[spy_post['dow'] == d]['abs_ret'].dropna().values.flatten() * 10000
    dow_pre_vols.append(np.mean(pre_d))
    dow_post_vols.append(np.mean(post_d))
    change = np.mean(post_d) - np.mean(pre_d)
    print(f"  {dow_names[d]:>5} {np.mean(pre_d):>16.2f} {np.mean(post_d):>17.2f} {change:>+10.2f}")

# Monday effect: is Monday vol still highest?
pre_monday_rank = sorted(range(5), key=lambda i: dow_pre_vols[i], reverse=True).index(0) + 1
post_monday_rank = sorted(range(5), key=lambda i: dow_post_vols[i], reverse=True).index(0) + 1
print(f"\n  Monday vol rank: Pre-COVID #{pre_monday_rank}, Post-COVID #{post_monday_rank}")

# Kruskal-Wallis test for day-of-week effect
groups_pre = [spy_pre[spy_pre['dow'] == d]['abs_ret'].dropna().values.flatten() for d in range(5)]
groups_post = [spy_post[spy_post['dow'] == d]['abs_ret'].dropna().values.flatten() for d in range(5)]

kw_pre = stats.kruskal(*groups_pre)
kw_post = stats.kruskal(*groups_post)

print(f"\n  Kruskal-Wallis test for day-of-week effect:")
print(f"    Pre-COVID:  H={kw_pre.statistic:.3f}, p={kw_pre.pvalue:.4f}")
print(f"    Post-COVID: H={kw_post.statistic:.3f}, p={kw_post.pvalue:.4f}")

results['G_dow_patterns'] = {
    'hypothesis': 'Day-of-week volatility patterns changed',
    'pre_monday_rank': int(pre_monday_rank),
    'post_monday_rank': int(post_monday_rank),
    'pre_kw_stat': round(float(kw_pre.statistic), 3),
    'pre_kw_pvalue': round(float(kw_pre.pvalue), 4),
    'post_kw_stat': round(float(kw_post.statistic), 3),
    'post_kw_pvalue': round(float(kw_post.pvalue), 4),
    'pre_dow_significant': kw_pre.pvalue < 0.05,
    'post_dow_significant': kw_post.pvalue < 0.05,
    'assessment': ''
}

# ═══════════════════════════════════════════════════════════════════════════
# Hypothesis H: VIX Floor Changed?
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("Hypothesis H: VIX Floor Changed?")
print("=" * 80)

# Count days VIX < various thresholds
thresholds = [10, 11, 12, 13, 14, 15]
print(f"  {'Threshold':>10} {'Pre-COVID (%)':>15} {'Post-COVID (%)':>16}")
for thresh in thresholds:
    pct_pre = np.mean(vix_pre_close < thresh) * 100
    pct_post = np.mean(vix_post_close < thresh) * 100
    print(f"  VIX < {thresh:>3} {pct_pre:>14.1f}% {pct_post:>15.1f}%")

# Minimum VIX
min_vix_pre = np.min(vix_pre_close)
min_vix_post = np.min(vix_post_close)
pct1_pre = np.percentile(vix_pre_close, 1)
pct1_post = np.percentile(vix_post_close, 1)
pct5_pre = np.percentile(vix_pre_close, 5)
pct5_post = np.percentile(vix_post_close, 5)

print(f"\n  Minimum VIX:     Pre={min_vix_pre:.2f}, Post={min_vix_post:.2f}")
print(f"  1st percentile:  Pre={pct1_pre:.2f}, Post={pct1_post:.2f}")
print(f"  5th percentile:  Pre={pct5_pre:.2f}, Post={pct5_post:.2f}")

# Mann-Whitney U test on lower tail (bottom 20% of VIX distribution)
q20_pre = np.percentile(vix_pre_close, 20)
q20_post = np.percentile(vix_post_close, 20)
lower_pre = vix_pre_close[vix_pre_close <= q20_pre]
lower_post = vix_post_close[vix_post_close <= q20_post]

u_stat, p_val_h = stats.mannwhitneyu(lower_pre, lower_post, alternative='two-sided')
print(f"\n  Mann-Whitney U test on bottom 20% of VIX:")
print(f"    Pre 20th pct:  {q20_pre:.2f} (n={len(lower_pre)})")
print(f"    Post 20th pct: {q20_post:.2f} (n={len(lower_post)})")
print(f"    U={u_stat:.0f}, p={p_val_h:.6f}")

# Year-by-year minimum VIX
print("\n  Year-by-year VIX minimum:")
for yr in range(2005, 2025):
    yr_vix = vix.loc[str(yr)]['Close'].dropna().values.flatten()
    if len(yr_vix) > 0:
        marker = " <<<" if yr == 2020 else ""
        print(f"    {yr}: min={np.min(yr_vix):.2f}, 5th pct={np.percentile(yr_vix, 5):.2f}{marker}")

results['H_vix_floor'] = {
    'hypothesis': 'VIX floor changed (minimum level elevated)',
    'pre_min_vix': round(float(min_vix_pre), 2),
    'post_min_vix': round(float(min_vix_post), 2),
    'pre_5th_pct': round(float(pct5_pre), 2),
    'post_5th_pct': round(float(pct5_post), 2),
    'pre_pct_below_12': round(float(np.mean(vix_pre_close < 12) * 100), 1),
    'post_pct_below_12': round(float(np.mean(vix_post_close < 12) * 100), 1),
    'mann_whitney_p': round(float(p_val_h), 6),
    'significant': p_val_h < 0.05,
    'assessment': ''
}

# ═══════════════════════════════════════════════════════════════════════════
# Assess Permanence for Each Hypothesis
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("PERMANENCE ASSESSMENT")
print("=" * 80)

# For B: Vol clustering — check if 2024 ACF is closer to pre-COVID or post-COVID
acf_2021 = compute_acf(spy_full.loc['2021']['ret'].apply(abs).dropna(), 1)[0]
acf_2022 = compute_acf(spy_full.loc['2022']['ret'].apply(abs).dropna(), 1)[0]
acf_2023 = compute_acf(spy_full.loc['2023']['ret'].apply(abs).dropna(), 1)[0]
acf_2024 = compute_acf(spy_full.loc['2024']['ret'].apply(abs).dropna(), 1)[0]
acf_trend = [acf_2021, acf_2022, acf_2023, acf_2024]
acf_reverting = abs(acf_2024 - acf_pre[0]) < abs(acf_2021 - acf_pre[0])

if results['B_vol_clustering']['significant']:
    if acf_reverting:
        results['B_vol_clustering']['assessment'] = 'TEMPORARY — ACF reverting toward pre-COVID levels'
        results['B_vol_clustering']['permanent'] = False
    else:
        results['B_vol_clustering']['assessment'] = 'PERMANENT — ACF change persists through 2024'
        results['B_vol_clustering']['permanent'] = True
else:
    results['B_vol_clustering']['assessment'] = 'NO CHANGE — Not statistically significant'
    results['B_vol_clustering']['permanent'] = False

# For C: Leverage effect
gamma_2024 = estimate_gamma(spy_full.loc['2024']['ret'].dropna())
gamma_reverting = abs(gamma_2024 - gamma_pre) < abs(gamma_post - gamma_pre) * 0.5

if results['C_leverage_effect']['significant']:
    if gamma_reverting:
        results['C_leverage_effect']['assessment'] = 'TEMPORARY — Gamma reverting toward pre-COVID levels'
        results['C_leverage_effect']['permanent'] = False
    else:
        results['C_leverage_effect']['assessment'] = 'PERMANENT — Leverage effect change persists'
        results['C_leverage_effect']['permanent'] = True
else:
    results['C_leverage_effect']['assessment'] = 'NO CHANGE — Not statistically significant'
    results['C_leverage_effect']['permanent'] = False

# For D: Overnight fraction
on_frac_2024, _, _, _ = compute_overnight_fraction(spy.loc['2024'])
on_reverting = abs(on_frac_2024 - on_frac_pre) < abs(on_frac_post - on_frac_pre) * 0.5

if results['D_overnight_fraction']['significant']:
    if on_reverting:
        results['D_overnight_fraction']['assessment'] = 'TEMPORARY — Overnight fraction reverting'
        results['D_overnight_fraction']['permanent'] = False
    else:
        results['D_overnight_fraction']['assessment'] = 'PERMANENT — Overnight fraction shift persists'
        results['D_overnight_fraction']['permanent'] = True
else:
    results['D_overnight_fraction']['assessment'] = 'NO CHANGE — Not statistically significant'
    results['D_overnight_fraction']['permanent'] = False

# For E: SPY-GLD correlation
spy_ret_2024 = np.log(spy.loc['2024']['Close'] / spy.loc['2024']['Close'].shift(1))
gld_ret_2024 = np.log(gld.loc['2024']['Close'] / gld.loc['2024']['Close'].shift(1))
combined_2024 = pd.DataFrame({'spy': spy_ret_2024, 'gld': gld_ret_2024}).dropna()
rho_2024 = np.corrcoef(combined_2024['spy'].values.flatten(), combined_2024['gld'].values.flatten())[0, 1]
corr_reverting = abs(rho_2024 - rho_pre) < abs(rho_post - rho_pre) * 0.5

if results['E_spy_gld_corr']['significant']:
    if corr_reverting:
        results['E_spy_gld_corr']['assessment'] = 'TEMPORARY — Correlation reverting toward pre-COVID'
        results['E_spy_gld_corr']['permanent'] = False
    else:
        results['E_spy_gld_corr']['assessment'] = 'PERMANENT — Correlation regime shift persists'
        results['E_spy_gld_corr']['permanent'] = True
else:
    results['E_spy_gld_corr']['assessment'] = 'NO CHANGE — Not statistically significant'
    results['E_spy_gld_corr']['permanent'] = False

# For F: Mean-reversion speed
phi_2024, _, _, hl_2024 = estimate_mr_speed(vix.loc['2024']['Close'].dropna())
phi_reverting = abs(phi_2024 - phi_pre) < abs(phi_post - phi_pre) * 0.5

if results['F_mr_speed']['significant']:
    if phi_reverting:
        results['F_mr_speed']['assessment'] = 'TEMPORARY — MR speed reverting'
        results['F_mr_speed']['permanent'] = False
    else:
        results['F_mr_speed']['assessment'] = 'PERMANENT — MR speed change persists'
        results['F_mr_speed']['permanent'] = True
else:
    results['F_mr_speed']['assessment'] = 'NO CHANGE — Not statistically significant'
    results['F_mr_speed']['permanent'] = False

# For G: Day-of-week
if results['G_dow_patterns']['pre_dow_significant'] and not results['G_dow_patterns']['post_dow_significant']:
    results['G_dow_patterns']['assessment'] = 'PERMANENT — Day-of-week effect disappeared post-COVID'
    results['G_dow_patterns']['permanent'] = True
elif not results['G_dow_patterns']['pre_dow_significant'] and not results['G_dow_patterns']['post_dow_significant']:
    results['G_dow_patterns']['assessment'] = 'NO CHANGE — Day-of-week effect was never significant'
    results['G_dow_patterns']['permanent'] = False
else:
    results['G_dow_patterns']['assessment'] = 'UNCERTAIN — Further analysis needed'
    results['G_dow_patterns']['permanent'] = False

# For H: VIX floor
vix_2024_min = np.min(vix.loc['2024']['Close'].dropna().values.flatten())
floor_reverting = vix_2024_min < 11  # VIX went back below 11?

if results['H_vix_floor']['significant']:
    if floor_reverting:
        results['H_vix_floor']['assessment'] = 'TEMPORARY — VIX floor reverting (sub-11 seen again)'
        results['H_vix_floor']['permanent'] = False
    else:
        results['H_vix_floor']['assessment'] = 'PERMANENT — Elevated VIX floor persists'
        results['H_vix_floor']['permanent'] = True
else:
    results['H_vix_floor']['assessment'] = 'NO CHANGE — VIX floor not significantly different'
    results['H_vix_floor']['permanent'] = False

# ═══════════════════════════════════════════════════════════════════════════
# COVID Impact Scorecard
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("COVID IMPACT SCORECARD")
print("=" * 80)

scorecard = []
for key, val in results.items():
    label = key.split('_', 1)[0]
    sig = "YES" if val.get('significant', False) else "NO"
    perm = "PERMANENT" if val.get('permanent', False) else ("TEMPORARY" if val.get('significant', False) else "N/A")
    assessment = val.get('assessment', '')
    scorecard.append({
        'id': label,
        'hypothesis': val['hypothesis'],
        'significant_change': sig,
        'permanence': perm,
        'assessment': assessment
    })
    print(f"\n  [{label}] {val['hypothesis']}")
    print(f"      Significant change: {sig}")
    print(f"      Permanence: {perm}")
    print(f"      Assessment: {assessment}")

# Summary counts
n_sig = sum(1 for s in scorecard if s['significant_change'] == 'YES')
n_perm = sum(1 for s in scorecard if s['permanence'] == 'PERMANENT')
n_temp = sum(1 for s in scorecard if s['permanence'] == 'TEMPORARY')

print(f"\n  ─── SUMMARY ───")
print(f"  Total hypotheses tested: 8")
print(f"  Significant changes found: {n_sig}/8")
print(f"  Permanent changes: {n_perm}")
print(f"  Temporary changes: {n_temp}")
print(f"  No change: {8 - n_sig}")

# ═══════════════════════════════════════════════════════════════════════════
# Save Results
# ═══════════════════════════════════════════════════════════════════════════
output = {
    'experiment': 'K402',
    'title': 'COVID Structural Break — What Changed PERMANENTLY in Vol Dynamics?',
    'data_source': 'yfinance (SPY, ^VIX, GLD)',
    'pre_period': f'{pre_start} to {pre_end}',
    'post_period': f'{post_start} to {post_end}',
    'excluded': '2020 (COVID transition)',
    'methodology': '8 structural break hypotheses: Welch t-test, bootstrap (5000 reps, block), Fisher z-test, Mann-Whitney U, Kruskal-Wallis',
    'summary': {
        'total_hypotheses': 8,
        'significant_changes': n_sig,
        'permanent_changes': n_perm,
        'temporary_changes': n_temp,
        'no_change': 8 - n_sig
    },
    'scorecard': scorecard,
    'detailed_results': results
}

results_path = 'experiments/k402_covid_structural_results.json'
with open(results_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to {results_path}")

# ═══════════════════════════════════════════════════════════════════════════
# Implications for Vol Prediction
# ═══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("IMPLICATIONS FOR VOL PREDICTION MODELS")
print("=" * 80)

implications = []
if results['A_mean_vix'].get('permanent', False):
    implications.append("- VIX mean level permanently elevated → recalibrate long-run mean in models")
if results['B_vol_clustering'].get('permanent', False):
    implications.append("- Vol clustering changed → re-estimate GARCH persistence parameters")
if results['C_leverage_effect'].get('permanent', False):
    implications.append("- Leverage effect changed → GJR-GARCH gamma parameter needs updating")
if results['D_overnight_fraction'].get('permanent', False):
    implications.append("- Overnight fraction shifted → adjust for overnight vs intraday vol separately")
if results['E_spy_gld_corr'].get('permanent', False):
    implications.append("- SPY-GLD correlation regime changed → portfolio diversification assumptions need updating")
if results['F_mr_speed'].get('permanent', False):
    implications.append("- VIX mean-reversion speed changed → VT strategy calibration affected")
if results['G_dow_patterns'].get('permanent', False):
    implications.append("- Day-of-week effect disappeared → calendar-based strategies no longer viable")
if results['H_vix_floor'].get('permanent', False):
    implications.append("- VIX floor elevated → 'low vol' threshold should be raised from 12 to ~15")

if implications:
    for imp in implications:
        print(f"  {imp}")
else:
    print("  No permanent changes detected — pre-COVID models may still be valid")

temp_implications = []
for key, val in results.items():
    if val.get('significant', False) and not val.get('permanent', False):
        temp_implications.append(f"  - {val['hypothesis']}: {val['assessment']}")

if temp_implications:
    print(f"\n  Temporary changes (may have already reverted):")
    for ti in temp_implications:
        print(ti)

print("\n" + "=" * 80)
print("K402 COMPLETE")
print("=" * 80)
