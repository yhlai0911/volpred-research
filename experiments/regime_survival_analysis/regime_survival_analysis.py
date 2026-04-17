"""
K119: Market Regime Duration Analysis with Survival Models
==========================================================
Extends P34 (vol regime Weibull shape<1) to multiple regime types.

Questions:
1. Do different market regimes (bull/bear/high-vol/low-vol) have different
   survival characteristics?
2. Which regimes exhibit mean-reversion (shape>1, predictable ending)?
3. Can regime duration predict transitions for investable strategies?

Methodology:
- SPY + VIX daily data 2007-2024
- 4 regime definitions: Bull, Bear, High Vol, Low Vol
- Weibull survival model for each regime
- Kaplan-Meier survival curves
- Log-rank tests for cross-regime comparison
- Bootstrap CIs for Weibull parameters
- Regime-ending strategy test if shape>1

[提出: Claude, 執行: Claude]
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import weibull_min, expon, kstest
from scipy.optimize import minimize
from itertools import combinations
from collections import defaultdict

# =============================================================================
# 1. DATA DOWNLOAD
# =============================================================================
print("=" * 70)
print("K119: Market Regime Duration Analysis with Survival Models")
print("=" * 70)

print("\n[1/7] Downloading data...")

spy_raw = yf.download("SPY", start="2006-01-01", end="2025-01-01",
                       progress=False, auto_adjust=False)
vix_raw = yf.download("^VIX", start="2006-01-01", end="2025-01-01",
                       progress=False, auto_adjust=False)

# Handle MultiIndex columns
if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_raw.columns = spy_raw.columns.get_level_values(0)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)

spy = spy_raw[['Close']].rename(columns={'Close': 'spy_close'})
vix = vix_raw[['Close']].rename(columns={'Close': 'vix'})

df = spy.join(vix, how='inner').dropna()
df['ret'] = df['spy_close'].pct_change()
df['ret_22d'] = df['spy_close'].pct_change(22) * 100  # 22-day return in %
df = df.dropna()

# Trim to 2007-2024
df = df.loc['2007-01-01':'2024-12-31']
print(f"   Data: {df.index[0].date()} to {df.index[-1].date()}, {len(df)} trading days")

# =============================================================================
# 2. REGIME DEFINITIONS
# =============================================================================
print("\n[2/7] Defining regimes...")

regimes = {
    'Bull':    (df['ret_22d'] > 0) & (df['vix'] < 20),
    'Bear':    (df['ret_22d'] < -5),
    'High_Vol': (df['vix'] > 25),
    'Low_Vol':  (df['vix'] < 15),
}

# Also add two additional regimes for richer analysis
regimes['Sideways'] = (df['ret_22d'].abs() < 2) & (df['vix'] >= 15) & (df['vix'] <= 25)
regimes['Crisis']   = (df['ret_22d'] < -10) & (df['vix'] > 30)

for name, mask in regimes.items():
    pct = mask.sum() / len(df) * 100
    print(f"   {name:10s}: {mask.sum():5d} days ({pct:.1f}%)")


def extract_episodes(mask_series):
    """Extract contiguous episodes from a boolean series.
    Returns list of (start_date, end_date, duration_days)."""
    episodes = []
    in_regime = False
    start = None

    for i, (date, val) in enumerate(mask_series.items()):
        if val and not in_regime:
            in_regime = True
            start = date
        elif not val and in_regime:
            in_regime = False
            end = mask_series.index[i - 1]
            duration = (mask_series.index[i-1] - start).days + 1
            # Count trading days
            trading_days = mask_series.loc[start:end].sum()
            episodes.append({
                'start': start,
                'end': end,
                'calendar_days': duration,
                'trading_days': int(trading_days),
            })

    # Handle still-in-regime at end (right-censored)
    if in_regime:
        end = mask_series.index[-1]
        duration = (end - start).days + 1
        trading_days = mask_series.loc[start:end].sum()
        episodes.append({
            'start': start,
            'end': end,
            'calendar_days': duration,
            'trading_days': int(trading_days),
            'censored': True,
        })

    return episodes


# Extract episodes for each regime
regime_episodes = {}
for name, mask in regimes.items():
    eps = extract_episodes(mask)
    # Mark non-censored
    for e in eps:
        if 'censored' not in e:
            e['censored'] = False
    regime_episodes[name] = eps

print("\n   Episode counts:")
for name, eps in regime_episodes.items():
    n_total = len(eps)
    n_censored = sum(1 for e in eps if e['censored'])
    if n_total > 0:
        durations = [e['trading_days'] for e in eps]
        print(f"   {name:10s}: {n_total:3d} episodes ({n_censored} censored), "
              f"mean={np.mean(durations):.1f}d, median={np.median(durations):.1f}d, "
              f"max={np.max(durations)}d")
    else:
        print(f"   {name:10s}: 0 episodes")


# =============================================================================
# 3. WEIBULL SURVIVAL MODEL FITTING
# =============================================================================
print("\n[3/7] Fitting Weibull survival models...")


def fit_weibull_mle(durations, censored=None):
    """Fit Weibull distribution via MLE, handling right-censored data.

    Weibull PDF: f(t) = (k/λ)(t/λ)^(k-1) exp(-(t/λ)^k)
    Weibull survival: S(t) = exp(-(t/λ)^k)

    For censored observation: contributes S(t) to likelihood
    For uncensored: contributes f(t) to likelihood
    """
    durations = np.array(durations, dtype=float)
    if censored is None:
        censored = np.zeros(len(durations), dtype=bool)
    else:
        censored = np.array(censored, dtype=bool)

    # Remove zeros
    valid = durations > 0
    durations = durations[valid]
    censored = censored[valid[:len(censored)] if len(censored) >= len(valid) else valid]

    def neg_log_likelihood(params):
        k, lam = params  # shape, scale
        if k <= 0 or lam <= 0:
            return 1e10

        ll = 0
        for t, c in zip(durations, censored):
            if not c:
                # Uncensored: log f(t)
                ll += np.log(k) - np.log(lam) + (k - 1) * np.log(t / lam) - (t / lam) ** k
            else:
                # Censored: log S(t)
                ll += -(t / lam) ** k

        return -ll

    # Try multiple starting points
    best_result = None
    best_nll = np.inf

    for k0 in [0.5, 1.0, 1.5, 2.0]:
        for lam0 in [np.median(durations), np.mean(durations), np.max(durations) / 2]:
            try:
                result = minimize(neg_log_likelihood, [k0, lam0],
                                  method='Nelder-Mead',
                                  options={'maxiter': 5000, 'xatol': 1e-8, 'fatol': 1e-8})
                if result.fun < best_nll and result.x[0] > 0 and result.x[1] > 0:
                    best_nll = result.fun
                    best_result = result
            except Exception:
                continue

    if best_result is None:
        return None, None

    return best_result.x[0], best_result.x[1]  # shape, scale


def bootstrap_weibull(durations, censored=None, n_boot=1000, seed=42):
    """Bootstrap CIs for Weibull parameters."""
    rng = np.random.RandomState(seed)
    n = len(durations)
    shapes = []
    scales = []

    for _ in range(n_boot):
        idx = rng.choice(n, size=n, replace=True)
        d_boot = [durations[i] for i in idx]
        c_boot = [censored[i] for i in idx] if censored else None

        k, lam = fit_weibull_mle(d_boot, c_boot)
        if k is not None and 0.01 < k < 10 and 0.1 < lam < 10000:
            shapes.append(k)
            scales.append(lam)

    if len(shapes) < 100:
        return None, None

    shape_ci = (np.percentile(shapes, 2.5), np.percentile(shapes, 97.5))
    scale_ci = (np.percentile(scales, 2.5), np.percentile(scales, 97.5))

    return shape_ci, scale_ci


weibull_results = {}

for name, eps in regime_episodes.items():
    if len(eps) < 20:
        print(f"   {name:10s}: SKIP (only {len(eps)} episodes, need >= 20)")
        continue

    durations = [e['trading_days'] for e in eps]
    censored = [e['censored'] for e in eps]

    shape, scale = fit_weibull_mle(durations, censored)

    if shape is None:
        print(f"   {name:10s}: FAILED to fit Weibull")
        continue

    # Interpretation
    if shape < 0.9:
        interp = "PERSISTENCE (decreasing hazard)"
    elif shape > 1.1:
        interp = "MEAN-REVERSION (increasing hazard)"
    else:
        interp = "MEMORYLESS (~exponential)"

    # Weibull mean = λ * Γ(1 + 1/k)
    from scipy.special import gamma
    weibull_mean = scale * gamma(1 + 1 / shape)
    weibull_median = scale * (np.log(2)) ** (1 / shape)

    print(f"   {name:10s}: shape={shape:.3f}, scale={scale:.1f}, "
          f"mean={weibull_mean:.1f}d, median={weibull_median:.1f}d → {interp}")

    weibull_results[name] = {
        'shape': shape,
        'scale': scale,
        'mean': weibull_mean,
        'median': weibull_median,
        'n_episodes': len(eps),
        'interpretation': interp,
    }

# Bootstrap CIs
print("\n   Bootstrap 95% CIs (1000 reps)...")
for name, eps in regime_episodes.items():
    if name not in weibull_results:
        continue

    durations = [e['trading_days'] for e in eps]
    censored = [e['censored'] for e in eps]

    shape_ci, scale_ci = bootstrap_weibull(durations, censored)

    if shape_ci is not None:
        weibull_results[name]['shape_ci'] = shape_ci
        weibull_results[name]['scale_ci'] = scale_ci

        # Does CI exclude 1?
        excludes_1 = shape_ci[1] < 1.0 or shape_ci[0] > 1.0
        sig = "***" if excludes_1 else "(n.s.)"

        print(f"   {name:10s}: shape CI=[{shape_ci[0]:.3f}, {shape_ci[1]:.3f}] {sig}, "
              f"scale CI=[{scale_ci[0]:.1f}, {scale_ci[1]:.1f}]")
    else:
        print(f"   {name:10s}: Bootstrap failed (too few valid resamples)")


# =============================================================================
# 4. KAPLAN-MEIER SURVIVAL CURVES
# =============================================================================
print("\n[4/7] Computing Kaplan-Meier survival curves...")


def kaplan_meier(durations, censored=None):
    """Compute Kaplan-Meier survival function."""
    n = len(durations)
    if censored is None:
        censored = [False] * n

    # Create event table
    events = sorted(zip(durations, censored), key=lambda x: x[0])

    times = sorted(set(d for d, _ in events))

    km_times = [0]
    km_survival = [1.0]

    n_at_risk = n

    for t in times:
        # Events at this time
        d_i = sum(1 for dur, c in events if dur == t and not c)  # deaths
        c_i = sum(1 for dur, c in events if dur == t and c)      # censored

        if n_at_risk > 0 and d_i > 0:
            survival_prob = 1 - d_i / n_at_risk
            km_times.append(t)
            km_survival.append(km_survival[-1] * survival_prob)

        n_at_risk -= (d_i + c_i)

    return np.array(km_times), np.array(km_survival)


km_curves = {}
for name, eps in regime_episodes.items():
    if name not in weibull_results:
        continue

    durations = [e['trading_days'] for e in eps]
    censored = [e['censored'] for e in eps]

    t, s = kaplan_meier(durations, censored)
    km_curves[name] = (t, s)

    # Key percentiles
    median_idx = np.searchsorted(-s, -0.5)
    q25_idx = np.searchsorted(-s, -0.25)

    median_t = t[min(median_idx, len(t) - 1)]
    q25_t = t[min(q25_idx, len(t) - 1)]

    print(f"   {name:10s}: KM median={median_t}d, 25th pctile={q25_t}d, "
          f"S(5d)={s[np.searchsorted(t, 5) if 5 <= t[-1] else -1]:.3f}, "
          f"S(20d)={s[np.searchsorted(t, 20) if 20 <= t[-1] else -1]:.3f}")


# =============================================================================
# 5. LOG-RANK TESTS
# =============================================================================
print("\n[5/7] Log-rank tests (pairwise regime comparison)...")


def log_rank_test(durations1, censored1, durations2, censored2):
    """Two-sample log-rank test.
    Returns chi-squared statistic and p-value.
    """
    from scipy.stats import chi2

    # Combine all event times
    all_events = []
    for d, c in zip(durations1, censored1):
        all_events.append((d, 0 if not c else 1, 1))  # (time, censored, group)
    for d, c in zip(durations2, censored2):
        all_events.append((d, 0 if not c else 1, 2))

    all_events.sort(key=lambda x: x[0])

    unique_times = sorted(set(e[0] for e in all_events if e[1] == 0))  # death times only

    # At each death time, compute expected vs observed deaths in group 1
    n1 = len(durations1)
    n2 = len(durations2)

    O1 = 0  # Observed deaths in group 1
    E1 = 0  # Expected deaths in group 1
    V = 0   # Variance

    # Track at-risk counts
    at_risk_1 = n1
    at_risk_2 = n2

    # Process events in time order
    prev_time = -1

    for t in unique_times:
        # Count events at this time
        d1 = sum(1 for e in all_events if e[0] == t and e[1] == 0 and e[2] == 1)
        d2 = sum(1 for e in all_events if e[0] == t and e[1] == 0 and e[2] == 2)
        c1 = sum(1 for e in all_events if e[0] == t and e[1] == 1 and e[2] == 1)
        c2 = sum(1 for e in all_events if e[0] == t and e[1] == 1 and e[2] == 2)

        d_total = d1 + d2
        n_total = at_risk_1 + at_risk_2

        if n_total > 0:
            O1 += d1
            e1 = at_risk_1 * d_total / n_total
            E1 += e1

            if n_total > 1:
                V += (at_risk_1 * at_risk_2 * d_total * (n_total - d_total)) / \
                     (n_total ** 2 * (n_total - 1))

        # Remove from at-risk
        at_risk_1 -= (d1 + c1)
        at_risk_2 -= (d2 + c2)

    if V <= 0:
        return 0, 1.0

    chi2_stat = (O1 - E1) ** 2 / V
    p_value = 1 - chi2.cdf(chi2_stat, df=1)

    return chi2_stat, p_value


# Pairwise tests
regime_names = [name for name in regimes.keys() if name in weibull_results]

print(f"\n   {'':12s}", end="")
for name in regime_names:
    print(f"{name:>12s}", end="")
print()

logrank_results = {}
for i, name1 in enumerate(regime_names):
    print(f"   {name1:12s}", end="")
    eps1 = regime_episodes[name1]
    d1 = [e['trading_days'] for e in eps1]
    c1 = [e['censored'] for e in eps1]

    for j, name2 in enumerate(regime_names):
        if j <= i:
            print(f"{'---':>12s}", end="")
            continue

        eps2 = regime_episodes[name2]
        d2 = [e['trading_days'] for e in eps2]
        c2 = [e['censored'] for e in eps2]

        chi2_stat, p_val = log_rank_test(d1, c1, d2, c2)
        sig = "***" if p_val < 0.001 else "**" if p_val < 0.01 else "*" if p_val < 0.05 else ""
        print(f"{p_val:>9.4f}{sig:>3s}", end="")

        logrank_results[(name1, name2)] = {'chi2': chi2_stat, 'p': p_val}

    print()


# =============================================================================
# 6. GOODNESS-OF-FIT: WEIBULL vs EXPONENTIAL
# =============================================================================
print("\n[6/7] Goodness-of-fit: Weibull vs Exponential (LRT)...")

for name in regime_names:
    eps = regime_episodes[name]
    durations = np.array([e['trading_days'] for e in eps if not e['censored']], dtype=float)

    if len(durations) < 20:
        continue

    # Fit Weibull (already done)
    shape = weibull_results[name]['shape']
    scale = weibull_results[name]['scale']

    # Weibull log-likelihood (uncensored only for fair comparison)
    ll_weibull = 0
    for t in durations:
        if t > 0:
            ll_weibull += np.log(shape) - np.log(scale) + \
                          (shape - 1) * np.log(t / scale) - (t / scale) ** shape

    # Exponential log-likelihood (Weibull with shape=1)
    exp_rate = 1 / np.mean(durations)
    ll_exp = 0
    for t in durations:
        if t > 0:
            ll_exp += np.log(exp_rate) - exp_rate * t

    # Likelihood ratio test (1 df: shape parameter)
    from scipy.stats import chi2
    lr_stat = 2 * (ll_weibull - ll_exp)
    lr_pval = 1 - chi2.cdf(max(lr_stat, 0), df=1)

    sig = "***" if lr_pval < 0.001 else "**" if lr_pval < 0.01 else "*" if lr_pval < 0.05 else "n.s."

    print(f"   {name:10s}: LR={lr_stat:.2f}, p={lr_pval:.4f} {sig} "
          f"(Weibull {'significantly better' if lr_pval < 0.05 else 'NOT better'} than Exponential)")


# =============================================================================
# 7. INVESTABILITY TEST: REGIME-ENDING STRATEGY
# =============================================================================
print("\n[7/7] Investability test: regime-ending strategies...")
print("   Testing if knowing regime duration improves allocation...")

# For regimes with shape > 1 (mean-reverting), test:
# - After regime lasts > median duration, increase hedge
# For regimes with shape < 1 (persistent), test:
# - Regime likely to continue → stay in position

# Build daily regime signals based on rolling duration
def compute_regime_duration_series(mask_series):
    """For each day, compute how long the current regime has lasted."""
    durations = pd.Series(0, index=mask_series.index)
    current_duration = 0

    for i, (date, val) in enumerate(mask_series.items()):
        if val:
            current_duration += 1
        else:
            current_duration = 0
        durations.iloc[i] = current_duration

    return durations


# Strategy: use regime duration to predict next-day returns
print("\n   --- Conditional Return Analysis ---")
print(f"   {'Regime':<12s} {'Duration>Med':<15s} {'Mean Ret (%)':<15s} "
      f"{'Duration<=Med':<15s} {'Mean Ret (%)':<15s} {'t-stat':<10s}")

from scipy.stats import ttest_ind

strategy_signals = {}

for name, mask in regimes.items():
    if name not in weibull_results:
        continue

    duration_series = compute_regime_duration_series(mask)
    median_dur = weibull_results[name]['median']

    # Next-day return
    next_ret = df['ret'].shift(-1) * 100  # in %

    # In-regime days split by duration
    in_regime = mask
    long_regime = in_regime & (duration_series > median_dur)
    short_regime = in_regime & (duration_series <= median_dur) & (duration_series > 0)

    ret_long = next_ret[long_regime].dropna()
    ret_short = next_ret[short_regime].dropna()

    if len(ret_long) > 30 and len(ret_short) > 30:
        t_stat, p_val = ttest_ind(ret_long, ret_short)

        print(f"   {name:<12s} {len(ret_long):>5d} days    {ret_long.mean():>8.4f}%       "
              f"{len(ret_short):>5d} days    {ret_short.mean():>8.4f}%       "
              f"t={t_stat:>6.2f} {'*' if abs(t_stat) > 2 else ''}")

        strategy_signals[name] = {
            'n_long': len(ret_long),
            'n_short': len(ret_short),
            'ret_long': ret_long.mean(),
            'ret_short': ret_short.mean(),
            't_stat': t_stat,
            'p_val': p_val,
        }


# Hazard rate analysis: does hazard actually increase/decrease with duration?
print("\n   --- Empirical Hazard Rate by Duration Tercile ---")

for name, mask in regimes.items():
    if name not in weibull_results:
        continue

    eps = [e for e in regime_episodes[name] if not e['censored']]
    if len(eps) < 30:
        continue

    durations = sorted([e['trading_days'] for e in eps])
    n = len(durations)

    # Tercile boundaries
    t1 = durations[n // 3]
    t2 = durations[2 * n // 3]

    tercile_1 = [d for d in durations if d <= t1]
    tercile_2 = [d for d in durations if t1 < d <= t2]
    tercile_3 = [d for d in durations if d > t2]

    # "Hazard" approximation: fraction of episodes ending at each tercile range
    print(f"   {name:10s}: short(<={t1}d)={len(tercile_1):3d} eps, "
          f"mid({t1+1}-{t2}d)={len(tercile_2):3d} eps, "
          f"long(>{t2}d)={len(tercile_3):3d} eps | "
          f"shape={weibull_results[name]['shape']:.3f}")


# Full backtest: regime-duration-aware VT overlay
print("\n   --- Regime Duration VT Overlay Backtest ---")

# Strategy: when in High_Vol regime for > median duration, reduce equity
# (since shape < 1 means it persists → stay defensive longer)
# When in Low_Vol regime for > median duration, reduce equity
# (if shape > 1 means it's about to end → preemptive hedge)

# Baseline: 12/VIX
df['w_base'] = 12 / df['vix']
df['w_base'] = df['w_base'].clip(0, 1)

# Overlay: adjust based on regime duration
high_vol_duration = compute_regime_duration_series(regimes['High_Vol'])
low_vol_duration = compute_regime_duration_series(regimes['Low_Vol'])

# Test different overlay rules
overlay_results = {}

for overlay_name, adjustment_func in [
    ("Base 12/VIX", lambda w, hvd, lvd: w),
    ("HV persist +hedge", lambda w, hvd, lvd: w * 0.5 if hvd > 10 else w),
    ("LV ending -hedge", lambda w, hvd, lvd: w * 0.8 if lvd > 30 else w),
    ("Combined", lambda w, hvd, lvd: (w * 0.5 if hvd > 10 else w * 0.8 if lvd > 30 else w)),
]:
    weights = []
    for i in range(len(df)):
        w = df['w_base'].iloc[i]
        hvd = high_vol_duration.iloc[i]
        lvd = low_vol_duration.iloc[i]
        w_adj = adjustment_func(w, hvd, lvd)
        weights.append(np.clip(w_adj, 0, 1))

    df[f'w_{overlay_name}'] = weights

    # Use lagged weights (VIX_t → r_{t+1})
    df[f'strat_ret_{overlay_name}'] = df[f'w_{overlay_name}'].shift(1) * df['ret']

    strat_ret = df[f'strat_ret_{overlay_name}'].dropna()

    sharpe = strat_ret.mean() / strat_ret.std() * np.sqrt(252)
    cum_ret = (1 + strat_ret).cumprod()
    mdd = (cum_ret / cum_ret.cummax() - 1).min()
    annual_ret = (cum_ret.iloc[-1]) ** (252 / len(strat_ret)) - 1

    overlay_results[overlay_name] = {
        'sharpe': sharpe,
        'mdd': mdd,
        'annual_ret': annual_ret,
    }

    print(f"   {overlay_name:<25s}: Sharpe={sharpe:.3f}, MDD={mdd:.1%}, Ann.Ret={annual_ret:.1%}")

# Improvement test
base_ret = df['strat_ret_Base 12/VIX'].dropna()
for overlay_name in ['HV persist +hedge', 'LV ending -hedge', 'Combined']:
    overlay_ret = df[f'strat_ret_{overlay_name}'].dropna()

    # Align
    common_idx = base_ret.index.intersection(overlay_ret.index)
    diff = overlay_ret.loc[common_idx] - base_ret.loc[common_idx]
    t_stat = diff.mean() / diff.std() * np.sqrt(len(diff))

    sig = "***" if abs(t_stat) > 3 else "**" if abs(t_stat) > 2 else "*" if abs(t_stat) > 1.65 else "n.s."
    print(f"   {overlay_name} vs Base: t={t_stat:.2f} {sig}")


# =============================================================================
# SUMMARY
# =============================================================================
print("\n" + "=" * 70)
print("SUMMARY: K119 Regime Survival Analysis")
print("=" * 70)

print("\n┌─────────────┬────────┬──────────┬──────────┬────────────────────────────────────┐")
print("│ Regime      │ N_eps  │ Shape    │ Shape CI │ Interpretation                     │")
print("├─────────────┼────────┼──────────┼──────────┼────────────────────────────────────┤")

for name in regime_names:
    r = weibull_results[name]
    ci = r.get('shape_ci')
    ci_str = f"[{ci[0]:.2f},{ci[1]:.2f}]" if ci else "N/A"

    # Significance
    if ci:
        if ci[1] < 1.0:
            sig = " *** shape<1"
        elif ci[0] > 1.0:
            sig = " *** shape>1"
        else:
            sig = " (n.s.)"
    else:
        sig = ""

    print(f"│ {name:<11s} │ {r['n_episodes']:>6d} │ {r['shape']:>8.3f} │ {ci_str:>8s} │ {r['interpretation']:<34s}│")

print("└─────────────┴────────┴──────────┴──────────┴────────────────────────────────────┘")

print("\nKey Findings:")
print("─" * 60)

# Analyze which regimes have significant shape parameters
for name in regime_names:
    r = weibull_results[name]
    ci = r.get('shape_ci')
    if ci:
        if ci[1] < 1.0:
            print(f"  ✓ {name}: shape={r['shape']:.3f} CI={ci}, DECREASING hazard")
            print(f"    → Longer the regime lasts, LESS likely to end")
            print(f"    → NOT predictable, persistence dominant")
        elif ci[0] > 1.0:
            print(f"  ★ {name}: shape={r['shape']:.3f} CI={ci}, INCREASING hazard")
            print(f"    → Longer the regime lasts, MORE likely to end")
            print(f"    → Potentially predictable regime transitions!")
        else:
            print(f"  ○ {name}: shape={r['shape']:.3f} CI={ci}, MEMORYLESS")
            print(f"    → Duration does not predict ending")

print("\nLog-rank Tests (significant pairs):")
for (n1, n2), res in logrank_results.items():
    if res['p'] < 0.05:
        print(f"  {n1} vs {n2}: chi2={res['chi2']:.2f}, p={res['p']:.4f} ***")

print("\nInvestability:")
any_investable = False
for name, sig in strategy_signals.items():
    if abs(sig['t_stat']) > 2:
        any_investable = True
        print(f"  {name}: duration split yields t={sig['t_stat']:.2f} return difference")

if not any_investable:
    print("  No regime duration signal yields significant return difference (t>2)")
    print("  → Regime duration is descriptively interesting but NOT investable")

print("\nOverlay Strategy:")
base_s = overlay_results['Base 12/VIX']['sharpe']
for name, res in overlay_results.items():
    if name == 'Base 12/VIX':
        continue
    delta = res['sharpe'] - base_s
    print(f"  {name}: ΔSharpe = {delta:+.3f} ({'improvement' if delta > 0 else 'WORSE'})")

print("\n" + "=" * 70)
print("CONCLUSION:")

# Count significant results
n_persistent = sum(1 for name in regime_names
                   if weibull_results[name].get('shape_ci') and
                   weibull_results[name]['shape_ci'][1] < 1.0)
n_meanrev = sum(1 for name in regime_names
                if weibull_results[name].get('shape_ci') and
                weibull_results[name]['shape_ci'][0] > 1.0)
n_memoryless = len(regime_names) - n_persistent - n_meanrev

print(f"  {n_persistent} regimes show PERSISTENCE (shape<1)")
print(f"  {n_meanrev} regimes show MEAN-REVERSION (shape>1)")
print(f"  {n_memoryless} regimes are MEMORYLESS (~exponential)")

if n_meanrev == 0:
    print("\n  ★ NO regime shows predictable ending (shape>1)")
    print("    Confirms P34: market regimes generally PERSIST")
    print("    → Regime duration is NOT a useful trading signal")
    print("    → VT should not try to time regime transitions")
else:
    print(f"\n  ★ {n_meanrev} regime(s) show mean-reversion!")
    print("    These may offer predictable transition timing")
    print("    But check if overlay strategy actually improves Sharpe")

print("=" * 70)
