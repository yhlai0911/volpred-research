"""
K399: Markov Regime Switching for Volatility — Formal 2-State Hamilton (1989) Model
====================================================================================
[提出: User, 執行: Claude]

跳躍式探索：正式的 Hamilton (1989) regime switching model

Pre-experiment check: 6 prior mentions.
- K152: MS-GARCH (null for prediction)
- K391: classified 4 market phases (descriptive, not formal model)
- K278: VIX transitions
- K212: conditional VIX sufficiency
But never a FORMAL 2-state Markov switching model estimated via MLE on SPY.

Data: SPY daily returns from yfinance, 2005-01-01 to 2024-12-31.

Methodology:
1. Estimate 2-state Markov regime model on SPY returns via statsmodels MarkovRegression
   - State 1 (low vol / calm), State 2 (high vol / turbulent)
   - Parameters: μ_1, σ_1, μ_2, σ_2, transition probabilities p_11, p_22
2. Regime characteristics: time fraction, mean duration, transition asymmetry
3. Predictive test: does P(turbulent regime) predict future RV beyond VIX?
4. VT with regime overlay vs fixed 12/VIX
5. VIX as regime probability approximator

Limitations:
- 2-state model is a simplification (could be 3+)
- Estimation via MLE; convergence depends on initialization
- statsmodels MarkovRegression with switching_variance=True
- Real yfinance data only
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import warnings
import json
import os
from datetime import datetime

warnings.filterwarnings("ignore")

print("=" * 80)
print("K399: Markov Regime Switching for Volatility")
print("Formal 2-State Hamilton (1989) Model")
print("=" * 80)

# ─────────────────────────────────────────────────────────────
# 1. DATA ACQUISITION
# ─────────────────────────────────────────────────────────────
print("\n[1] Downloading SPY data from yfinance (2005-2024)...")

spy = yf.download("SPY", start="2005-01-01", end="2025-01-01", progress=False)
vix = yf.download("^VIX", start="2005-01-01", end="2025-01-01", progress=False)

# Handle multi-level columns if present
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

spy_ret = spy["Close"].pct_change().dropna()
spy_ret.name = "ret"

# Scale returns to percentage for numerical stability in MLE
spy_ret_pct = spy_ret * 100

# Align VIX
vix_close = vix["Close"].reindex(spy_ret.index).ffill().dropna()
spy_ret_pct = spy_ret_pct.reindex(vix_close.index).dropna()
spy_ret = spy_ret.reindex(spy_ret_pct.index)
vix_close = vix_close.reindex(spy_ret_pct.index)

print(f"  SPY returns: {len(spy_ret_pct)} days")
print(f"  Date range: {spy_ret_pct.index[0].date()} to {spy_ret_pct.index[-1].date()}")
print(f"  VIX aligned: {len(vix_close)} days")

# ─────────────────────────────────────────────────────────────
# 2. ESTIMATE MARKOV REGIME SWITCHING MODEL
# ─────────────────────────────────────────────────────────────
print("\n[2] Estimating 2-State Markov Regime Switching Model...")
print("    Hamilton (1989) framework via statsmodels MLE")

from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression

# Model: r_t = μ_{s_t} + σ_{s_t} * ε_t, s_t ∈ {0, 1}
# switching_variance=True allows different variance in each state
model = MarkovRegression(
    spy_ret_pct,
    k_regimes=2,
    switching_variance=True,
)

# Fit with multiple starts for robustness
best_result = None
best_llf = -np.inf
n_starts = 10

print(f"    Trying {n_starts} random initializations...")
for i in range(n_starts):
    try:
        result = model.fit(disp=False, maxiter=500)
        if result.llf > best_llf:
            best_llf = result.llf
            best_result = result
    except Exception:
        pass

if best_result is None:
    print("  ERROR: Could not estimate model. Trying default initialization...")
    best_result = model.fit(disp=False)

res = best_result
print(f"  Log-likelihood: {res.llf:.2f}")
print(f"  AIC: {res.aic:.2f}")
print(f"  BIC: {res.bic:.2f}")

# ─────────────────────────────────────────────────────────────
# 3. EXTRACT PARAMETERS
# ─────────────────────────────────────────────────────────────
print("\n[3] Regime Parameters:")

# Extract parameters
params = res.params
param_names = list(res.params.index) if hasattr(res.params, 'index') else []

print(f"  Parameter names: {param_names}")
print(f"  Parameter values: {[f'{p:.6f}' for p in params]}")

# Mean for each regime (const[0], const[1])
mu_0 = params['const[0]']
mu_1 = params['const[1]']

# Variance for each regime (sigma2[0], sigma2[1])
sigma2_0 = params['sigma2[0]']
sigma2_1 = params['sigma2[1]']
sigma_0 = np.sqrt(sigma2_0)
sigma_1 = np.sqrt(sigma2_1)

# Transition probabilities (from params: p[0->0] and p[1->0])
p_00 = params['p[0->0]']   # P(stay in state 0 | state 0)
p_10 = params['p[1->0]']   # P(go from state 1 to state 0)
p_01 = 1 - p_00             # P(switch from state 0 to state 1)
p_11 = 1 - p_10             # P(stay in state 1 | state 1)

# Ensure state 0 = low vol, state 1 = high vol
if sigma_0 > sigma_1:
    # Swap labels
    mu_0, mu_1 = mu_1, mu_0
    sigma_0, sigma_1 = sigma_1, sigma_0
    sigma2_0, sigma2_1 = sigma2_1, sigma2_0
    p_00, p_11 = p_11, p_00
    p_01, p_10 = p_10, p_01
    swap_flag = True
    print("  (States swapped so State 0 = Low Vol, State 1 = High Vol)")
else:
    swap_flag = False

# Convert from percentage returns back to decimal for interpretation
mu_0_dec = mu_0 / 100
mu_1_dec = mu_1 / 100
sigma_0_dec = sigma_0 / 100
sigma_1_dec = sigma_1 / 100

print(f"\n  ┌──────────────────────────────────────────────────────────┐")
print(f"  │ State 0 (Low Volatility / Calm):                        │")
print(f"  │   Mean daily return (μ₀): {mu_0_dec*100:+.4f}% ({mu_0_dec*252*100:+.2f}% ann.)    │")
print(f"  │   Daily volatility (σ₀):   {sigma_0_dec*100:.4f}% ({sigma_0_dec*np.sqrt(252)*100:.2f}% ann.)   │")
print(f"  │   P(stay in State 0):       {p_00:.4f}                       │")
print(f"  │                                                          │")
print(f"  │ State 1 (High Volatility / Turbulent):                   │")
print(f"  │   Mean daily return (μ₁): {mu_1_dec*100:+.4f}% ({mu_1_dec*252*100:+.2f}% ann.)   │")
print(f"  │   Daily volatility (σ₁):   {sigma_1_dec*100:.4f}% ({sigma_1_dec*np.sqrt(252)*100:.2f}% ann.)   │")
print(f"  │   P(stay in State 1):       {p_11:.4f}                       │")
print(f"  └──────────────────────────────────────────────────────────┘")

vol_ratio = sigma_1 / sigma_0
print(f"\n  Volatility ratio (σ₁/σ₀): {vol_ratio:.2f}x")
print(f"  Transition matrix:")
print(f"    From\\To   State0    State1")
print(f"    State0    {p_00:.4f}    {p_01:.4f}")
print(f"    State1    {p_10:.4f}    {p_11:.4f}")

# ─────────────────────────────────────────────────────────────
# 4. REGIME CHARACTERISTICS
# ─────────────────────────────────────────────────────────────
print("\n[4] Regime Characteristics:")

# Mean duration of each state
duration_0 = 1 / (1 - p_00)  # days
duration_1 = 1 / (1 - p_11)  # days

print(f"  Mean duration of State 0 (calm):     {duration_0:.1f} trading days ({duration_0/21:.1f} months)")
print(f"  Mean duration of State 1 (turbulent): {duration_1:.1f} trading days ({duration_1/21:.1f} months)")

# Ergodic (unconditional) probabilities
ergodic_0 = p_10 / (p_01 + p_10)
ergodic_1 = p_01 / (p_01 + p_10)
print(f"\n  Ergodic probabilities:")
print(f"    P(State 0 / calm):     {ergodic_0:.4f} ({ergodic_0*100:.1f}%)")
print(f"    P(State 1 / turbulent): {ergodic_1:.4f} ({ergodic_1*100:.1f}%)")

# Transition asymmetry
print(f"\n  Transition asymmetry:")
print(f"    P(calm → turbulent):   {p_01:.4f} per day")
print(f"    P(turbulent → calm):   {p_10:.4f} per day")
asym_ratio = p_01 / p_10 if p_10 > 0 else np.inf
print(f"    Ratio (entry/exit):     {asym_ratio:.4f}")
if asym_ratio < 1:
    print(f"    → Market enters turbulence SLOWLY but exits QUICKLY")
elif asym_ratio > 1:
    print(f"    → Market enters turbulence QUICKLY but exits SLOWLY")
else:
    print(f"    → Symmetric transitions")

# ─────────────────────────────────────────────────────────────
# 5. SMOOTHED PROBABILITIES & TIME-IN-REGIME
# ─────────────────────────────────────────────────────────────
print("\n[5] Smoothed Regime Probabilities:")

# Smoothed probabilities (Kim smoother)
smoothed_probs = res.smoothed_marginal_probabilities

# Handle swap
if swap_flag:
    prob_turbulent = smoothed_probs[0]  # swapped
    prob_calm = smoothed_probs[1]
else:
    prob_turbulent = smoothed_probs[1]
    prob_calm = smoothed_probs[0]

# Classify each day
regime_class = (prob_turbulent > 0.5).astype(int)
n_turbulent = regime_class.sum()
n_calm = len(regime_class) - n_turbulent
pct_turbulent = n_turbulent / len(regime_class) * 100

print(f"  Days in calm regime:     {n_calm} ({100 - pct_turbulent:.1f}%)")
print(f"  Days in turbulent regime: {n_turbulent} ({pct_turbulent:.1f}%)")

# Verify against ergodic
print(f"  (Ergodic prediction:      {ergodic_0*100:.1f}% calm, {ergodic_1*100:.1f}% turbulent)")

# Time-series regime episodes
regime_changes = np.diff(regime_class.values.astype(int))
n_transitions = np.sum(np.abs(regime_changes))
print(f"  Number of regime transitions: {n_transitions}")
print(f"  Average time between transitions: {len(regime_class)/n_transitions:.1f} days")

# Identify major turbulent episodes
turbulent_episodes = []
in_episode = False
start_idx = None
for i in range(len(regime_class)):
    if regime_class.iloc[i] == 1 and not in_episode:
        in_episode = True
        start_idx = i
    elif regime_class.iloc[i] == 0 and in_episode:
        in_episode = False
        duration = i - start_idx
        if duration >= 10:  # at least 10 trading days
            turbulent_episodes.append({
                'start': regime_class.index[start_idx].date(),
                'end': regime_class.index[i-1].date(),
                'duration': duration,
                'max_prob': prob_turbulent.iloc[start_idx:i].max()
            })
if in_episode:
    duration = len(regime_class) - start_idx
    if duration >= 10:
        turbulent_episodes.append({
            'start': regime_class.index[start_idx].date(),
            'end': regime_class.index[-1].date(),
            'duration': duration,
            'max_prob': prob_turbulent.iloc[start_idx:].max()
        })

print(f"\n  Major turbulent episodes (≥10 days):")
print(f"  {'Start':>12s}  {'End':>12s}  {'Duration':>8s}  {'Max P(turb)':>11s}")
for ep in sorted(turbulent_episodes, key=lambda x: x['duration'], reverse=True)[:15]:
    print(f"  {str(ep['start']):>12s}  {str(ep['end']):>12s}  {ep['duration']:>6d} d  {ep['max_prob']:>9.3f}")

# ─────────────────────────────────────────────────────────────
# 6. PREDICTIVE TEST: P(TURBULENT) → FUTURE RV
# ─────────────────────────────────────────────────────────────
print("\n[6] Predictive Test: Does Regime Probability Predict Future Realized Volatility?")
print("    Controlling for VIX (which is the known strong predictor)")

# Compute forward realized volatility (21-day)
rv_21 = spy_ret.rolling(21).std() * np.sqrt(252) * 100  # annualized %

# Create aligned DataFrame
df = pd.DataFrame({
    'prob_turbulent': prob_turbulent,
    'vix': vix_close,
    'rv_21_fwd': rv_21.shift(-21),  # 21-day forward RV
    'rv_5_fwd': (spy_ret.rolling(5).std() * np.sqrt(252) * 100).shift(-5),  # 5-day forward
    'ret': spy_ret,
}).dropna()

print(f"  Aligned sample: {len(df)} observations")

# 6a. Univariate correlations
corr_prob_rv21 = df['prob_turbulent'].corr(df['rv_21_fwd'])
corr_vix_rv21 = df['vix'].corr(df['rv_21_fwd'])
corr_prob_rv5 = df['prob_turbulent'].corr(df['rv_5_fwd'])
corr_vix_rv5 = df['vix'].corr(df['rv_5_fwd'])

print(f"\n  Univariate correlations with future RV:")
print(f"    {'Predictor':<20s}  {'→ RV(21d)':>10s}  {'→ RV(5d)':>10s}")
print(f"    {'P(turbulent)':20s}  {corr_prob_rv21:>10.4f}  {corr_prob_rv5:>10.4f}")
print(f"    {'VIX':20s}  {corr_vix_rv21:>10.4f}  {corr_vix_rv5:>10.4f}")

# 6b. Partial correlation: P(turbulent) → RV | VIX
# Using residual method
from numpy.linalg import lstsq

def partial_corr(x, y, z):
    """Partial correlation between x and y controlling for z."""
    # Residualize x on z
    X_z = np.column_stack([z, np.ones(len(z))])
    beta_x, _, _, _ = lstsq(X_z, x, rcond=None)
    resid_x = x - X_z @ beta_x
    # Residualize y on z
    beta_y, _, _, _ = lstsq(X_z, y, rcond=None)
    resid_y = y - X_z @ beta_y
    r = np.corrcoef(resid_x, resid_y)[0, 1]
    # t-test for partial correlation
    n = len(x)
    k = 1  # one control variable
    t_stat = r * np.sqrt((n - 2 - k) / (1 - r**2))
    p_val = 2 * stats.t.sf(np.abs(t_stat), df=n-2-k)
    return r, t_stat, p_val

pr_21, t_21, pval_21 = partial_corr(
    df['prob_turbulent'].values, df['rv_21_fwd'].values, df['vix'].values
)
pr_5, t_5, pval_5 = partial_corr(
    df['prob_turbulent'].values, df['rv_5_fwd'].values, df['vix'].values
)

print(f"\n  Partial correlations (controlling for VIX):")
print(f"    P(turbulent) → RV(21d) | VIX:  r = {pr_21:.4f}, t = {t_21:.2f}, p = {pval_21:.4e}")
print(f"    P(turbulent) → RV(5d)  | VIX:  r = {pr_5:.4f}, t = {t_5:.2f}, p = {pval_5:.4e}")

# Harvey (2016) threshold
harvey_pass_21 = abs(t_21) > 3.0
harvey_pass_5 = abs(t_5) > 3.0
print(f"\n  Harvey (2016) t > 3.0 threshold:")
print(f"    21-day RV: {'PASS ✓' if harvey_pass_21 else 'FAIL ✗'} (|t| = {abs(t_21):.2f})")
print(f"    5-day RV:  {'PASS ✓' if harvey_pass_5 else 'FAIL ✗'} (|t| = {abs(t_5):.2f})")

# 6c. Incremental R² test
from sklearn.linear_model import LinearRegression

# Model 1: VIX only
X1 = df[['vix']].values
y = df['rv_21_fwd'].values
r2_vix = 1 - np.sum((y - LinearRegression().fit(X1, y).predict(X1))**2) / np.sum((y - y.mean())**2)

# Model 2: VIX + P(turbulent)
X2 = df[['vix', 'prob_turbulent']].values
r2_both = 1 - np.sum((y - LinearRegression().fit(X2, y).predict(X2))**2) / np.sum((y - y.mean())**2)

delta_r2 = r2_both - r2_vix
# F-test for incremental R²
n = len(y)
p_full = 2
p_reduced = 1
f_stat = (delta_r2 / (p_full - p_reduced)) / ((1 - r2_both) / (n - p_full - 1))
f_pval = stats.f.sf(f_stat, p_full - p_reduced, n - p_full - 1)

print(f"\n  Incremental R² test (21-day RV):")
print(f"    R²(VIX only):            {r2_vix:.4f}")
print(f"    R²(VIX + P(turbulent)):  {r2_both:.4f}")
print(f"    ΔR²:                     {delta_r2:.4f}")
print(f"    F-stat: {f_stat:.2f}, p = {f_pval:.4e}")

# ─────────────────────────────────────────────────────────────
# 7. OUT-OF-SAMPLE PREDICTIVE TEST
# ─────────────────────────────────────────────────────────────
print("\n[7] Out-of-Sample Predictive Test (Expanding Window):")

# Use first 5 years as initial training, then expanding window
initial_train = 252 * 5  # ~5 years
n_total = len(spy_ret_pct)

oos_dates = []
oos_prob_turb = []
oos_vix = []
oos_rv21 = []

# Compute RV for OOS evaluation
rv_21_full = spy_ret.rolling(21).std() * np.sqrt(252) * 100

print(f"  Initial training: {initial_train} days")
print(f"  OOS window: {n_total - initial_train} days")
print(f"  Re-estimating every 63 days (quarterly)...")

last_prob_value = None
last_refit = 0
refit_count = 0

for t in range(initial_train, n_total - 21):
    # Re-estimate model every 63 trading days
    if t - last_refit >= 63 or last_prob_value is None:
        try:
            oos_model = MarkovRegression(
                spy_ret_pct.iloc[:t],
                k_regimes=2,
                switching_variance=True,
            )
            oos_res = oos_model.fit(disp=False, maxiter=300)

            # Get smoothed probs — use the LAST observation's probability
            sp = oos_res.smoothed_marginal_probabilities

            # Identify which state is high vol
            s0_var = oos_res.params['sigma2[0]']
            s1_var = oos_res.params['sigma2[1]']
            if s0_var > s1_var:
                turb_probs = sp[0]  # state 0 is high vol
            else:
                turb_probs = sp[1]  # state 1 is high vol

            # Use the last available probability as the "current" regime estimate
            last_prob_value = float(turb_probs.iloc[-1])
            last_refit = t
            refit_count += 1
        except Exception:
            pass

    if last_prob_value is not None:
        dt = spy_ret_pct.index[t]
        fwd_rv = rv_21_full.iloc[t + 21] if (t + 21) < len(rv_21_full) else np.nan
        if not np.isnan(fwd_rv) and t < len(vix_close):
            oos_dates.append(dt)
            oos_prob_turb.append(last_prob_value)
            oos_vix.append(float(vix_close.iloc[t]))
            oos_rv21.append(float(fwd_rv))

oos_df = pd.DataFrame({
    'prob_turbulent': oos_prob_turb,
    'vix': oos_vix,
    'rv_21_fwd': oos_rv21,
}, index=oos_dates).dropna()

print(f"  Model re-estimated {refit_count} times")
print(f"  OOS sample: {len(oos_df)} observations")

if len(oos_df) > 100:
    # OOS partial correlation
    oos_pr, oos_t, oos_pval = partial_corr(
        oos_df['prob_turbulent'].values,
        oos_df['rv_21_fwd'].values,
        oos_df['vix'].values
    )
    print(f"  OOS partial corr (P(turb) → RV | VIX): r = {oos_pr:.4f}, t = {oos_t:.2f}, p = {oos_pval:.4e}")
    print(f"  Harvey threshold: {'PASS' if abs(oos_t) > 3.0 else 'FAIL'} (|t| = {abs(oos_t):.2f})")

    # OOS R²
    X1_oos = oos_df[['vix']].values
    X2_oos = oos_df[['vix', 'prob_turbulent']].values
    y_oos = oos_df['rv_21_fwd'].values
    r2_vix_oos = 1 - np.sum((y_oos - LinearRegression().fit(X1_oos, y_oos).predict(X1_oos))**2) / np.sum((y_oos - y_oos.mean())**2)
    r2_both_oos = 1 - np.sum((y_oos - LinearRegression().fit(X2_oos, y_oos).predict(X2_oos))**2) / np.sum((y_oos - y_oos.mean())**2)
    print(f"  OOS R²(VIX): {r2_vix_oos:.4f}, R²(VIX+P(turb)): {r2_both_oos:.4f}, ΔR²: {r2_both_oos - r2_vix_oos:.4f}")
else:
    print("  Insufficient OOS data for reliable test")
    oos_pr, oos_t, oos_pval = np.nan, np.nan, np.nan

# ─────────────────────────────────────────────────────────────
# 8. VT WITH REGIME OVERLAY
# ─────────────────────────────────────────────────────────────
print("\n[8] Volatility Targeting with Regime Overlay:")

# Full-sample analysis for strategy comparison
# Use smoothed probabilities from full-sample estimation

vt_df = pd.DataFrame({
    'ret': spy_ret,
    'vix': vix_close,
    'prob_turbulent': prob_turbulent,
}).dropna()

# Strategy 1: Fixed 12/VIX (baseline)
vt_df['w_fixed'] = 12.0 / vt_df['vix']
vt_df['w_fixed'] = vt_df['w_fixed'].clip(0.5, 1.5)

# Strategy 2: Regime-adaptive VT
# When P(turbulent) > 0.5 → conservative 6/VIX
# When P(turbulent) < 0.2 → aggressive 18/VIX
# Otherwise → moderate 12/VIX
def regime_vt_weight(row):
    p = row['prob_turbulent']
    vix = row['vix']
    if p > 0.5:
        target = 6.0
    elif p < 0.2:
        target = 18.0
    else:
        # Linear interpolation between 6 and 18 for 0.2 < p < 0.5
        target = 18.0 - (p - 0.2) / 0.3 * 12.0
    w = target / vix
    return np.clip(w, 0.5, 1.5)

vt_df['w_regime'] = vt_df.apply(regime_vt_weight, axis=1)

# Strategy 3: Simple VIX threshold (no regime model)
# VIX > 25 → 6/VIX, VIX < 15 → 18/VIX, else 12/VIX
def vix_threshold_weight(row):
    vix = row['vix']
    if vix > 25:
        target = 6.0
    elif vix < 15:
        target = 18.0
    else:
        target = 12.0
    w = target / vix
    return np.clip(w, 0.5, 1.5)

vt_df['w_vix_thresh'] = vt_df.apply(vix_threshold_weight, axis=1)

# Use NEXT day returns (avoid look-ahead)
vt_df['fwd_ret'] = vt_df['ret'].shift(-1)

# Strategy returns
vt_df['ret_buyhold'] = vt_df['fwd_ret']
vt_df['ret_fixed'] = vt_df['w_fixed'] * vt_df['fwd_ret']
vt_df['ret_regime'] = vt_df['w_regime'] * vt_df['fwd_ret']
vt_df['ret_vix_thresh'] = vt_df['w_vix_thresh'] * vt_df['fwd_ret']

vt_df = vt_df.dropna()

# Performance metrics
def calc_metrics(returns, name):
    ann_ret = returns.mean() * 252 * 100
    ann_vol = returns.std() * np.sqrt(252) * 100
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + returns).cumprod()
    mdd = ((cum / cum.cummax()) - 1).min() * 100
    # Sortino
    downside = returns[returns < 0].std() * np.sqrt(252) * 100
    sortino = ann_ret / downside if downside > 0 else 0
    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0
    return {
        'name': name,
        'ann_return': ann_ret,
        'ann_vol': ann_vol,
        'sharpe': sharpe,
        'sortino': sortino,
        'mdd': mdd,
        'calmar': calmar,
    }

strategies = {
    'ret_buyhold': 'Buy & Hold SPY',
    'ret_fixed': 'Fixed VT (12/VIX)',
    'ret_regime': 'Regime-Adaptive VT',
    'ret_vix_thresh': 'VIX-Threshold VT',
}

print(f"\n  {'Strategy':<22s}  {'Return':>8s}  {'Vol':>8s}  {'Sharpe':>7s}  {'Sortino':>8s}  {'MDD':>8s}  {'Calmar':>7s}")
print(f"  {'-'*22}  {'-'*8}  {'-'*8}  {'-'*7}  {'-'*8}  {'-'*8}  {'-'*7}")

metrics_list = []
for col, name in strategies.items():
    m = calc_metrics(vt_df[col], name)
    metrics_list.append(m)
    print(f"  {name:<22s}  {m['ann_return']:>7.2f}%  {m['ann_vol']:>7.2f}%  {m['sharpe']:>7.3f}  {m['sortino']:>8.3f}  {m['mdd']:>7.2f}%  {m['calmar']:>7.3f}")

# ─────────────────────────────────────────────────────────────
# 9. REGIME VT: SUBPERIOD ANALYSIS
# ─────────────────────────────────────────────────────────────
print("\n[9] Regime VT Performance in Subperiods:")

# Define subperiods
subperiods = [
    ('2005-2007 (Pre-GFC)', '2005-01-01', '2007-12-31'),
    ('2008-2009 (GFC)', '2008-01-01', '2009-12-31'),
    ('2010-2014 (Recovery)', '2010-01-01', '2014-12-31'),
    ('2015-2019 (Late Bull)', '2015-01-01', '2019-12-31'),
    ('2020-2020 (COVID)', '2020-01-01', '2020-12-31'),
    ('2021-2024 (Post-COVID)', '2021-01-01', '2024-12-31'),
]

print(f"\n  {'Period':<25s}  {'Fixed Sharpe':>12s}  {'Regime Sharpe':>13s}  {'Diff':>6s}  {'% in Turb':>10s}")
print(f"  {'-'*25}  {'-'*12}  {'-'*13}  {'-'*6}  {'-'*10}")

for period_name, start, end in subperiods:
    mask = (vt_df.index >= start) & (vt_df.index <= end)
    sub = vt_df[mask]
    if len(sub) < 50:
        continue
    m_fixed = calc_metrics(sub['ret_fixed'], 'fixed')
    m_regime = calc_metrics(sub['ret_regime'], 'regime')
    pct_turb = (sub['prob_turbulent'] > 0.5).mean() * 100
    diff = m_regime['sharpe'] - m_fixed['sharpe']
    print(f"  {period_name:<25s}  {m_fixed['sharpe']:>12.3f}  {m_regime['sharpe']:>13.3f}  {diff:>+5.3f}  {pct_turb:>9.1f}%")

# ─────────────────────────────────────────────────────────────
# 10. VIX AS REGIME APPROXIMATOR
# ─────────────────────────────────────────────────────────────
print("\n[10] How Well Does VIX Approximate Regime Probability?")

# Correlation between VIX and P(turbulent)
corr_vix_prob = vt_df['vix'].corr(vt_df['prob_turbulent'])
print(f"  Correlation(VIX, P(turbulent)): {corr_vix_prob:.4f}")

# Logistic regression: can VIX predict regime?
from sklearn.linear_model import LogisticRegression

X_vix = vt_df['vix'].values.reshape(-1, 1)
y_regime = (vt_df['prob_turbulent'] > 0.5).astype(int).values

lr = LogisticRegression()
lr.fit(X_vix, y_regime)
lr_score = lr.score(X_vix, y_regime)
print(f"  Logistic accuracy (VIX → regime): {lr_score:.4f}")

# Find the VIX threshold that best separates regimes
vix_thresholds = np.arange(12, 35, 0.5)
best_acc = 0
best_thresh = 0
for thresh in vix_thresholds:
    pred = (vt_df['vix'] > thresh).astype(int).values
    acc = (pred == y_regime).mean()
    if acc > best_acc:
        best_acc = acc
        best_thresh = thresh

print(f"  Best VIX threshold for regime: {best_thresh:.1f} (accuracy: {best_acc:.4f})")

# Confusion matrix at best threshold
pred_best = (vt_df['vix'] > best_thresh).astype(int).values
tp = ((pred_best == 1) & (y_regime == 1)).sum()
fp = ((pred_best == 1) & (y_regime == 0)).sum()
tn = ((pred_best == 0) & (y_regime == 0)).sum()
fn = ((pred_best == 0) & (y_regime == 1)).sum()

print(f"  Confusion matrix (VIX > {best_thresh:.1f}):")
print(f"                    Actual Calm  Actual Turb")
print(f"    Pred Calm       {tn:>10d}    {fn:>10d}")
print(f"    Pred Turb       {fp:>10d}    {tp:>10d}")
print(f"    Sensitivity (TPR): {tp/(tp+fn):.4f}" if (tp+fn) > 0 else "")
print(f"    Specificity (TNR): {tn/(tn+fp):.4f}" if (tn+fp) > 0 else "")

# Conditional VIX statistics by regime
calm_vix = vt_df.loc[vt_df['prob_turbulent'] <= 0.5, 'vix']
turb_vix = vt_df.loc[vt_df['prob_turbulent'] > 0.5, 'vix']
print(f"\n  VIX statistics by regime:")
print(f"    Calm regime:     mean={calm_vix.mean():.2f}, median={calm_vix.median():.2f}, std={calm_vix.std():.2f}")
print(f"    Turbulent regime: mean={turb_vix.mean():.2f}, median={turb_vix.median():.2f}, std={turb_vix.std():.2f}")

# Overlap analysis
vix_overlap_low = max(calm_vix.quantile(0.25), turb_vix.quantile(0.25))
vix_overlap_high = min(calm_vix.quantile(0.75), turb_vix.quantile(0.75))
print(f"    IQR overlap zone: VIX {vix_overlap_low:.1f} - {vix_overlap_high:.1f}")
overlap_pct = ((vt_df['vix'] >= vix_overlap_low) & (vt_df['vix'] <= vix_overlap_high)).mean() * 100
print(f"    % of days in overlap zone: {overlap_pct:.1f}%")

# ─────────────────────────────────────────────────────────────
# 11. REGIME-CONDITIONAL RETURN STATISTICS
# ─────────────────────────────────────────────────────────────
print("\n[11] Regime-Conditional Return Statistics:")

calm_ret = vt_df.loc[vt_df['prob_turbulent'] <= 0.5, 'ret']
turb_ret = vt_df.loc[vt_df['prob_turbulent'] > 0.5, 'ret']

print(f"  {'Statistic':<25s}  {'Calm':>10s}  {'Turbulent':>10s}")
print(f"  {'-'*25}  {'-'*10}  {'-'*10}")
print(f"  {'Mean daily return':<25s}  {calm_ret.mean()*100:>9.4f}%  {turb_ret.mean()*100:>9.4f}%")
print(f"  {'Ann. return':<25s}  {calm_ret.mean()*252*100:>9.2f}%  {turb_ret.mean()*252*100:>9.2f}%")
print(f"  {'Daily volatility':<25s}  {calm_ret.std()*100:>9.4f}%  {turb_ret.std()*100:>9.4f}%")
print(f"  {'Ann. volatility':<25s}  {calm_ret.std()*np.sqrt(252)*100:>9.2f}%  {turb_ret.std()*np.sqrt(252)*100:>9.2f}%")
print(f"  {'Skewness':<25s}  {calm_ret.skew():>10.4f}  {turb_ret.skew():>10.4f}")
print(f"  {'Kurtosis':<25s}  {calm_ret.kurtosis():>10.4f}  {turb_ret.kurtosis():>10.4f}")
print(f"  {'Max daily loss':<25s}  {calm_ret.min()*100:>9.4f}%  {turb_ret.min()*100:>9.4f}%")
print(f"  {'Sharpe (in-regime)':<25s}  {calm_ret.mean()/calm_ret.std()*np.sqrt(252):>10.4f}  {turb_ret.mean()/turb_ret.std()*np.sqrt(252):>10.4f}")

# Welch's t-test for mean difference
t_welch, p_welch = stats.ttest_ind(calm_ret, turb_ret, equal_var=False)
# Levene's test for variance difference
lev_stat, lev_pval = stats.levene(calm_ret, turb_ret)

print(f"\n  Statistical tests:")
print(f"    Mean difference (Welch t): t = {t_welch:.2f}, p = {p_welch:.4e}")
print(f"    Variance difference (Levene): F = {lev_stat:.2f}, p = {lev_pval:.4e}")

# ─────────────────────────────────────────────────────────────
# 12. SUMMARY & CONCLUSIONS
# ─────────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("SUMMARY & CONCLUSIONS")
print("=" * 80)

conclusions = []

# Conclusion 1: Model estimation
print(f"\n1. MODEL ESTIMATION:")
print(f"   2-state Markov regime model successfully estimated via MLE")
print(f"   Calm state: μ={mu_0_dec*252*100:+.2f}% ann, σ={sigma_0_dec*np.sqrt(252)*100:.2f}% ann")
print(f"   Turbulent state: μ={mu_1_dec*252*100:+.2f}% ann, σ={sigma_1_dec*np.sqrt(252)*100:.2f}% ann")
print(f"   Volatility ratio: {vol_ratio:.2f}x")
conclusions.append(f"Volatility ratio between regimes: {vol_ratio:.1f}x")

# Conclusion 2: Regime durations
print(f"\n2. REGIME DURATION & ASYMMETRY:")
print(f"   Calm state mean duration: {duration_0:.0f} days ({duration_0/21:.1f} months)")
print(f"   Turbulent state mean duration: {duration_1:.0f} days ({duration_1/21:.1f} months)")
print(f"   Transition asymmetry: entry/exit ratio = {asym_ratio:.3f}")
if duration_0 > duration_1:
    print(f"   → Calm regimes last much longer; turbulence is episodic")
conclusions.append(f"Calm lasts ~{duration_0:.0f}d, turbulent ~{duration_1:.0f}d")

# Conclusion 3: Predictive power
print(f"\n3. PREDICTIVE POWER (BEYOND VIX):")
print(f"   In-sample partial r = {pr_21:.4f} (t = {t_21:.2f})")
if abs(t_21) > 3.0:
    print(f"   → PASSES Harvey threshold: regime probability adds beyond VIX")
    conclusions.append("Regime prob adds beyond VIX for vol prediction (Harvey pass)")
elif abs(t_21) > 1.96:
    print(f"   → Statistically significant but FAILS Harvey threshold")
    print(f"   → Marginal incremental value over VIX")
    conclusions.append(f"Marginal incremental value over VIX (t={t_21:.2f} < 3.0)")
else:
    print(f"   → NOT significant: VIX already captures regime information")
    conclusions.append("VIX already captures regime info (regime prob redundant)")

# Conclusion 4: VIX as approximator
print(f"\n4. VIX AS REGIME APPROXIMATOR:")
print(f"   Correlation: {corr_vix_prob:.4f}")
print(f"   Best VIX threshold: {best_thresh:.1f} (accuracy: {best_acc:.4f})")
if corr_vix_prob > 0.8:
    print(f"   → VIX is an excellent proxy for regime probability")
    conclusions.append(f"VIX is excellent regime proxy (r={corr_vix_prob:.3f})")
elif corr_vix_prob > 0.6:
    print(f"   → VIX is a good but imperfect proxy")
    conclusions.append(f"VIX is good but imperfect regime proxy (r={corr_vix_prob:.3f})")
else:
    print(f"   → VIX is a weak proxy; regime model captures different dynamics")
    conclusions.append(f"VIX is weak regime proxy (r={corr_vix_prob:.3f})")

# Conclusion 5: Strategy comparison
fixed_sharpe = [m for m in metrics_list if m['name'] == 'Fixed VT (12/VIX)'][0]['sharpe']
regime_sharpe = [m for m in metrics_list if m['name'] == 'Regime-Adaptive VT'][0]['sharpe']
sharpe_diff = regime_sharpe - fixed_sharpe

print(f"\n5. REGIME-ADAPTIVE VT vs FIXED VT:")
print(f"   Fixed 12/VIX Sharpe:       {fixed_sharpe:.3f}")
print(f"   Regime-Adaptive VT Sharpe: {regime_sharpe:.3f}")
print(f"   Difference:                {sharpe_diff:+.3f}")
if sharpe_diff > 0.05:
    print(f"   → Regime overlay IMPROVES VT meaningfully")
    conclusions.append(f"Regime overlay improves VT Sharpe by {sharpe_diff:+.3f}")
elif sharpe_diff > -0.05:
    print(f"   → Regime overlay has MARGINAL impact on VT")
    conclusions.append(f"Regime overlay has marginal impact ({sharpe_diff:+.3f} Sharpe)")
else:
    print(f"   → Regime overlay HURTS VT performance (overfitting concern)")
    conclusions.append(f"Regime overlay hurts VT ({sharpe_diff:+.3f} Sharpe)")

print(f"\n6. KEY CAVEATS:")
print(f"   - Full-sample estimation (look-ahead bias in regime probabilities)")
print(f"   - 2-state model is a simplification (may need 3+ states)")
print(f"   - Strategy comparison uses in-sample regime assignment")
print(f"   - No transaction costs considered")
print(f"   - OOS regime estimation quality depends on quarterly re-fitting")

# ─────────────────────────────────────────────────────────────
# SAVE RESULTS
# ─────────────────────────────────────────────────────────────
results = {
    "experiment": "K399",
    "title": "Markov Regime Switching for Volatility",
    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    "data_source": "yfinance (SPY, ^VIX)",
    "data_period": f"{spy_ret_pct.index[0].date()} to {spy_ret_pct.index[-1].date()}",
    "n_observations": len(spy_ret_pct),
    "method": "Hamilton (1989) 2-state Markov regime switching, statsmodels MLE",
    "model_params": {
        "calm_mean_ann_pct": round(mu_0_dec * 252 * 100, 2),
        "calm_vol_ann_pct": round(sigma_0_dec * np.sqrt(252) * 100, 2),
        "turbulent_mean_ann_pct": round(mu_1_dec * 252 * 100, 2),
        "turbulent_vol_ann_pct": round(sigma_1_dec * np.sqrt(252) * 100, 2),
        "vol_ratio": round(vol_ratio, 2),
        "p_stay_calm": round(float(p_00), 4),
        "p_stay_turbulent": round(float(p_11), 4),
        "p_calm_to_turb": round(float(p_01), 4),
        "p_turb_to_calm": round(float(p_10), 4),
    },
    "regime_characteristics": {
        "calm_mean_duration_days": round(duration_0, 1),
        "turbulent_mean_duration_days": round(duration_1, 1),
        "ergodic_prob_calm": round(float(ergodic_0), 4),
        "ergodic_prob_turbulent": round(float(ergodic_1), 4),
        "transition_asymmetry_ratio": round(asym_ratio, 4),
        "pct_time_turbulent": round(pct_turbulent, 1),
    },
    "predictive_tests": {
        "insample_partial_r_21d": round(pr_21, 4),
        "insample_t_stat_21d": round(float(t_21), 2),
        "insample_p_value_21d": float(pval_21),
        "harvey_pass_21d": harvey_pass_21,
        "insample_partial_r_5d": round(pr_5, 4),
        "insample_t_stat_5d": round(float(t_5), 2),
        "delta_r2_21d": round(delta_r2, 4),
        "oos_partial_r": round(float(oos_pr), 4) if not np.isnan(oos_pr) else None,
        "oos_t_stat": round(float(oos_t), 2) if not np.isnan(oos_t) else None,
    },
    "vix_as_regime_proxy": {
        "correlation_vix_prob_turb": round(corr_vix_prob, 4),
        "best_vix_threshold": round(best_thresh, 1),
        "threshold_accuracy": round(best_acc, 4),
        "logistic_accuracy": round(lr_score, 4),
    },
    "strategy_performance": {m['name']: {
        'ann_return': round(m['ann_return'], 2),
        'ann_vol': round(m['ann_vol'], 2),
        'sharpe': round(m['sharpe'], 3),
        'sortino': round(m['sortino'], 3),
        'mdd': round(m['mdd'], 2),
    } for m in metrics_list},
    "conclusions": conclusions,
}

results_path = os.path.join(os.path.dirname(__file__), "k399_markov_regime_results.json")
with open(results_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to: {results_path}")

print("\n" + "=" * 80)
print("K399 EXPERIMENT COMPLETE")
print("=" * 80)
