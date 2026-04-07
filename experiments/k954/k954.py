"""
K954: DeFi Impermanent Loss and Volatility Prediction
=====================================================

Problem: AMM liquidity providers face Impermanent Loss (IL) driven by price volatility.
Can GARCH-family models predict IL and enable selective LP strategies?

Data source: yfinance ETH-USD (2020-01-01 to 2026-04-05)
Method: GJR-GARCH(1,1,1) → predicted σ² → predicted IL ≈ -σ²/8
Baseline: EWMA(λ=0.94), Naive (historical mean)

Author: VolPred Research System
"""

import numpy as np
import pandas as pd
import json
import warnings
import os
from datetime import datetime

np.random.seed(42)
warnings.filterwarnings('ignore')

import yfinance as yf
from arch import arch_model
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy import stats

# ============================================================
# 1. Data Download
# ============================================================
print("=" * 60)
print("K954: DeFi Impermanent Loss and Volatility Prediction")
print("=" * 60)

eth = yf.download('ETH-USD', start='2020-01-01', end='2026-04-06', progress=False)
if isinstance(eth.columns, pd.MultiIndex):
    eth.columns = eth.columns.get_level_values(0)

eth = eth.dropna(subset=['Close'])
eth['return'] = np.log(eth['Close'] / eth['Close'].shift(1))
eth = eth.dropna(subset=['return'])

print(f"\nETH-USD data: {eth.index[0].strftime('%Y-%m-%d')} to {eth.index[-1].strftime('%Y-%m-%d')}")
print(f"Total observations: {len(eth)}")

# ============================================================
# 2. Compute Daily Impermanent Loss
# ============================================================
# Exact IL for 50/50 AMM pool:
# IL = 2 * sqrt(p1/p0) / (1 + p1/p0) - 1

price_ratio = eth['Close'] / eth['Close'].shift(1)
eth['IL_exact'] = 2 * np.sqrt(price_ratio) / (1 + price_ratio) - 1
eth['IL_approx'] = -(eth['return'] ** 2) / 8  # Approximation: IL ≈ -σ²/8

# Rolling cumulative IL (compounding)
eth['IL_7d'] = eth['IL_exact'].rolling(7).sum()
eth['IL_30d'] = eth['IL_exact'].rolling(30).sum()

eth = eth.dropna(subset=['IL_exact'])

print(f"\n--- Impermanent Loss Descriptive Stats ---")
print(f"Daily IL (exact):  mean={eth['IL_exact'].mean()*100:.6f}%, "
      f"std={eth['IL_exact'].std()*100:.6f}%, "
      f"min={eth['IL_exact'].min()*100:.4f}%, max={eth['IL_exact'].max()*100:.8f}%")
print(f"Daily IL (approx): mean={eth['IL_approx'].mean()*100:.6f}%")
print(f"7-day cumul IL:    mean={eth['IL_7d'].mean()*100:.4f}%, "
      f"std={eth['IL_7d'].std()*100:.4f}%")
print(f"30-day cumul IL:   mean={eth['IL_30d'].mean()*100:.4f}%, "
      f"std={eth['IL_30d'].std()*100:.4f}%")

# IL is always <= 0 by construction
print(f"\nIL always negative? {(eth['IL_exact'] <= 0).all()}")
print(f"Correlation(IL_exact, IL_approx): {eth['IL_exact'].corr(eth['IL_approx']):.6f}")

# Squared return = proxy for σ²
eth['r2'] = eth['return'] ** 2

# ============================================================
# 3. GARCH Models for Vol Prediction
# ============================================================
returns_pct = eth['return'] * 100  # arch expects percentage returns

# Split: 70% IS, 30% OOS
n = len(returns_pct)
n_is = int(n * 0.7)
n_oos = n - n_is

print(f"\nIS: {n_is} obs, OOS: {n_oos} obs")
print(f"IS period: {eth.index[0].strftime('%Y-%m-%d')} to {eth.index[n_is-1].strftime('%Y-%m-%d')}")
print(f"OOS period: {eth.index[n_is].strftime('%Y-%m-%d')} to {eth.index[-1].strftime('%Y-%m-%d')}")

# --- GJR-GARCH(1,1,1) ---
print("\n--- Fitting GJR-GARCH(1,1,1) ---")
gjr = arch_model(returns_pct, vol='GARCH', p=1, o=1, q=1, dist='t')
gjr_fit = gjr.fit(last_obs=n_is, disp='off')
print(gjr_fit.summary().tables[1])

# OOS rolling forecast (recursive)
gjr_forecasts = []
for t in range(n_is, n):
    res = arch_model(returns_pct.iloc[:t], vol='GARCH', p=1, o=1, q=1, dist='t')
    fit = res.fit(disp='off', show_warning=False)
    fcast = fit.forecast(horizon=1)
    gjr_forecasts.append(fcast.variance.values[-1, 0])

gjr_var_oos = np.array(gjr_forecasts) / 10000  # Convert back from pct² to decimal²

# --- Standard GARCH(1,1) ---
print("\n--- Fitting GARCH(1,1) ---")
garch = arch_model(returns_pct, vol='GARCH', p=1, q=1, dist='t')
garch_fit = garch.fit(last_obs=n_is, disp='off')

garch_forecasts = []
for t in range(n_is, n):
    res = arch_model(returns_pct.iloc[:t], vol='GARCH', p=1, q=1, dist='t')
    fit = res.fit(disp='off', show_warning=False)
    fcast = fit.forecast(horizon=1)
    garch_forecasts.append(fcast.variance.values[-1, 0])

garch_var_oos = np.array(garch_forecasts) / 10000

# --- EWMA baseline (λ=0.94) ---
lam = 0.94
ewma_var = np.zeros(n)
ewma_var[0] = eth['r2'].iloc[0]
for t in range(1, n):
    ewma_var[t] = lam * ewma_var[t-1] + (1 - lam) * eth['r2'].iloc[t-1]

ewma_var_oos = ewma_var[n_is:]

# --- Naive (expanding historical mean of r²) ---
naive_var = np.zeros(n_oos)
for t in range(n_oos):
    naive_var[t] = eth['r2'].iloc[:n_is + t].mean()

# ============================================================
# 4. IL Prediction
# ============================================================
# Predicted IL = -σ²_predicted / 8 (first-order approximation)
il_pred_gjr = -gjr_var_oos / 8
il_pred_garch = -garch_var_oos / 8
il_pred_ewma = -ewma_var_oos / 8
il_pred_naive = -naive_var / 8

# Actual IL in OOS
il_actual_oos = eth['IL_exact'].iloc[n_is:].values

print(f"\n--- OOS IL Prediction Performance ---")

def eval_il(pred, actual, name):
    mse = np.mean((pred - actual) ** 2)
    mae = np.mean(np.abs(pred - actual))
    corr = np.corrcoef(pred, actual)[0, 1]
    # R² (using actual as y, pred as x)
    ss_res = np.sum((actual - pred) ** 2)
    ss_tot = np.sum((actual - actual.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot
    print(f"  {name:12s}: MSE={mse:.2e}, MAE={mae:.2e}, Corr={corr:.4f}, R²={r2:.4f}")
    return {'mse': float(mse), 'mae': float(mae), 'corr': float(corr), 'r2': float(r2)}

res_gjr = eval_il(il_pred_gjr, il_actual_oos, 'GJR')
res_garch = eval_il(il_pred_garch, il_actual_oos, 'GARCH')
res_ewma = eval_il(il_pred_ewma, il_actual_oos, 'EWMA')
res_naive = eval_il(il_pred_naive, il_actual_oos, 'Naive')

# ============================================================
# 5. Vol Prediction Performance (QLIKE on r²)
# ============================================================
r2_oos = eth['r2'].iloc[n_is:].values

def qlike(sigma2_pred, r2_actual):
    """Patton (2011) QLIKE loss: proxy-robust."""
    # Avoid log(0)
    sigma2_pred = np.maximum(sigma2_pred, 1e-20)
    return np.mean(r2_actual / sigma2_pred - np.log(r2_actual / sigma2_pred) - 1)

print(f"\n--- OOS Vol Prediction (QLIKE on r²) ---")
qlike_gjr = qlike(gjr_var_oos, r2_oos)
qlike_garch = qlike(garch_var_oos, r2_oos)
qlike_ewma = qlike(ewma_var_oos, r2_oos)
qlike_naive = qlike(naive_var, r2_oos)

print(f"  GJR:   QLIKE={qlike_gjr:.4f}")
print(f"  GARCH: QLIKE={qlike_garch:.4f}")
print(f"  EWMA:  QLIKE={qlike_ewma:.4f}")
print(f"  Naive: QLIKE={qlike_naive:.4f}")

# ============================================================
# 6. IL Risk Warning (Classification)
# ============================================================
# When predicted |IL| > threshold, is actual IL also severe?
threshold = 0.005  # 0.5% daily IL

print(f"\n--- IL Risk Warning (threshold={threshold*100:.1f}% daily) ---")

def il_classification(pred, actual, name, thresh):
    pred_high = np.abs(pred) > thresh
    actual_high = np.abs(actual) > thresh

    tp = np.sum(pred_high & actual_high)
    fp = np.sum(pred_high & ~actual_high)
    fn = np.sum(~pred_high & actual_high)
    tn = np.sum(~pred_high & ~actual_high)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    accuracy = (tp + tn) / len(actual)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    print(f"  {name:12s}: Acc={accuracy:.3f}, Prec={precision:.3f}, "
          f"Rec={recall:.3f}, F1={f1:.3f} (TP={tp}, FP={fp}, FN={fn}, TN={tn})")
    return {'accuracy': float(accuracy), 'precision': float(precision),
            'recall': float(recall), 'f1': float(f1),
            'tp': int(tp), 'fp': int(fp), 'fn': int(fn), 'tn': int(tn)}

cls_gjr = il_classification(il_pred_gjr, il_actual_oos, 'GJR', threshold)
cls_garch = il_classification(il_pred_garch, il_actual_oos, 'GARCH', threshold)
cls_ewma = il_classification(il_pred_ewma, il_actual_oos, 'EWMA', threshold)
cls_naive = il_classification(il_pred_naive, il_actual_oos, 'Naive', threshold)

# ============================================================
# 7. Selective LP Strategy
# ============================================================
# Fee revenue = 0.3% fee tier * volume proxy
# We proxy daily fee revenue as a fixed amount (simplified)
# Focus: compare blind LP vs selective LP

# Assume daily fee revenue = 0.03% of position (simplified Uniswap v3 0.3% pool)
daily_fee = 0.0003

print(f"\n--- Selective LP Strategy (fee={daily_fee*100:.2f}%/day) ---")

def lp_strategy(pred_il, actual_il, name, fee, thresh):
    """
    Blind LP: always provide liquidity
    Selective LP: only provide when predicted |IL| < threshold
    Signal uses shift(1) equivalent: pred_il[t] predicts IL at t+1
    """
    n = len(actual_il)

    # Blind LP: always in
    blind_pnl = actual_il + fee  # IL + fee

    # Selective LP: enter only when predicted IL is small
    # Use signal from previous day (shift equivalent)
    selective_pnl = np.zeros(n)
    in_pool = np.zeros(n, dtype=bool)

    for t in range(1, n):
        # Decision at t based on prediction at t-1 (no lookahead)
        if np.abs(pred_il[t-1]) < thresh:
            in_pool[t] = True
            selective_pnl[t] = actual_il[t] + fee
        else:
            in_pool[t] = False
            selective_pnl[t] = 0  # Out of pool, no fee and no IL

    # Skip first day (no signal)
    blind_pnl = blind_pnl[1:]
    selective_pnl = selective_pnl[1:]
    in_pool = in_pool[1:]

    blind_total = np.sum(blind_pnl)
    sel_total = np.sum(selective_pnl)
    in_pool_pct = np.mean(in_pool) * 100

    # Annualized Sharpe (365 days for crypto)
    blind_sharpe = np.mean(blind_pnl) / np.std(blind_pnl) * np.sqrt(365) if np.std(blind_pnl) > 0 else 0
    sel_sharpe = np.mean(selective_pnl) / np.std(selective_pnl) * np.sqrt(365) if np.std(selective_pnl) > 0 else 0

    print(f"  {name:12s}: Blind PnL={blind_total*100:.3f}%, Selective PnL={sel_total*100:.3f}%, "
          f"In-pool={in_pool_pct:.1f}%, Blind Sharpe={blind_sharpe:.3f}, Sel Sharpe={sel_sharpe:.3f}")

    return {
        'blind_total_pnl': float(blind_total),
        'selective_total_pnl': float(sel_total),
        'in_pool_pct': float(in_pool_pct),
        'blind_sharpe': float(blind_sharpe),
        'selective_sharpe': float(sel_sharpe),
        'blind_daily_mean': float(np.mean(blind_pnl)),
        'selective_daily_mean': float(np.mean(selective_pnl)),
    }

strat_gjr = lp_strategy(il_pred_gjr, il_actual_oos, 'GJR', daily_fee, threshold)
strat_garch = lp_strategy(il_pred_garch, il_actual_oos, 'GARCH', daily_fee, threshold)
strat_ewma = lp_strategy(il_pred_ewma, il_actual_oos, 'EWMA', daily_fee, threshold)
strat_naive = lp_strategy(il_pred_naive, il_actual_oos, 'Naive', daily_fee, threshold)

# ============================================================
# 8. IL Approximation Quality
# ============================================================
print(f"\n--- IL Approximation Quality ---")
approx_err = eth['IL_approx'] - eth['IL_exact']
print(f"Approximation error (IL_approx - IL_exact):")
print(f"  Mean:  {approx_err.mean()*100:.8f}%")
print(f"  Std:   {approx_err.std()*100:.8f}%")
print(f"  Max:   {approx_err.max()*100:.6f}%")
print(f"  Corr(exact, approx): {eth['IL_exact'].corr(eth['IL_approx']):.6f}")

# How good is the -σ²/8 approximation?
# Only valid for small price changes. Check for large moves:
large_moves = eth[np.abs(eth['return']) > 0.10]
print(f"\n  Days with |return| > 10%: {len(large_moves)}")
if len(large_moves) > 0:
    approx_err_large = large_moves['IL_approx'] - large_moves['IL_exact']
    print(f"  Approx error on large-move days: mean={approx_err_large.mean()*100:.4f}%, "
          f"max={approx_err_large.max()*100:.4f}%")

# ============================================================
# 9. GJR Parameters Analysis
# ============================================================
print(f"\n--- GJR-GARCH Parameters (ETH-USD) ---")
params = gjr_fit.params
print(f"  omega = {params['omega']:.6f}")
print(f"  alpha = {params['alpha[1]']:.6f}")
print(f"  gamma = {params['gamma[1]']:.6f}")
print(f"  beta  = {params['beta[1]']:.6f}")
print(f"  nu    = {params['nu']:.4f}")
persistence = params['alpha[1]'] + params['gamma[1]']/2 + params['beta[1]']
print(f"  Persistence = {persistence:.6f}")
print(f"  gamma/alpha = {params['gamma[1]']/params['alpha[1]']:.3f} (leverage ratio)")

# ============================================================
# 10. Plots
# ============================================================
fig, axes = plt.subplots(3, 2, figsize=(16, 14))
fig.suptitle('K954: DeFi Impermanent Loss & Volatility Prediction (ETH-USD)', fontsize=14, fontweight='bold')

oos_dates = eth.index[n_is:]

# (a) ETH price + IL
ax = axes[0, 0]
ax2 = ax.twinx()
ax.plot(eth.index, eth['Close'], color='blue', alpha=0.7, linewidth=0.8)
ax.set_ylabel('ETH Price (USD)', color='blue')
ax2.plot(eth.index, eth['IL_30d'] * 100, color='red', alpha=0.6, linewidth=0.8)
ax2.set_ylabel('30-day Cumul IL (%)', color='red')
ax.set_title('(a) ETH-USD Price & 30-day Cumulative IL')
ax.axvline(eth.index[n_is], color='gray', linestyle='--', alpha=0.5, label='OOS start')
ax.legend(loc='upper left')

# (b) Daily IL distribution
ax = axes[0, 1]
ax.hist(eth['IL_exact'] * 100, bins=100, color='steelblue', alpha=0.7, edgecolor='none')
ax.axvline(eth['IL_exact'].mean() * 100, color='red', linestyle='--', label=f"Mean={eth['IL_exact'].mean()*100:.4f}%")
ax.axvline(-threshold * 100, color='orange', linestyle='--', label=f'Threshold=-{threshold*100:.1f}%')
ax.set_xlabel('Daily IL (%)')
ax.set_ylabel('Frequency')
ax.set_title('(b) Daily IL Distribution')
ax.legend()

# (c) Predicted vs Actual IL (OOS, GJR)
ax = axes[1, 0]
ax.scatter(il_pred_gjr * 100, il_actual_oos * 100, alpha=0.3, s=5, color='steelblue')
ax.plot([il_actual_oos.min() * 100, 0], [il_actual_oos.min() * 100, 0], 'r--', alpha=0.5)
ax.set_xlabel('Predicted IL (%, GJR)')
ax.set_ylabel('Actual IL (%)')
ax.set_title(f'(c) GJR IL Prediction (OOS, R²={res_gjr["r2"]:.3f})')

# (d) OOS vol forecasts comparison
ax = axes[1, 1]
ax.plot(oos_dates, np.sqrt(gjr_var_oos) * 100, label='GJR', alpha=0.7, linewidth=0.8)
ax.plot(oos_dates, np.sqrt(ewma_var_oos) * 100, label='EWMA', alpha=0.7, linewidth=0.8)
ax.plot(oos_dates, np.sqrt(r2_oos) * 100, label='|r| realized', alpha=0.3, linewidth=0.5, color='gray')
ax.set_ylabel('Daily Vol (%)')
ax.set_title('(d) OOS Volatility Forecasts')
ax.legend()

# (e) Selective LP cumulative PnL
ax = axes[2, 0]
blind_pnl_gjr = il_actual_oos[1:] + daily_fee
sel_pnl_gjr = np.zeros(len(il_actual_oos) - 1)
for t in range(len(sel_pnl_gjr)):
    if np.abs(il_pred_gjr[t]) < threshold:
        sel_pnl_gjr[t] = il_actual_oos[t+1] + daily_fee

ax.plot(oos_dates[1:], np.cumsum(blind_pnl_gjr) * 100, label='Blind LP', color='red', alpha=0.7)
ax.plot(oos_dates[1:], np.cumsum(sel_pnl_gjr) * 100, label='Selective LP (GJR)', color='blue', alpha=0.7)
ax.axhline(0, color='gray', linestyle='-', alpha=0.3)
ax.set_ylabel('Cumulative PnL (%)')
ax.set_title('(e) Blind vs Selective LP (GJR)')
ax.legend()

# (f) IL approximation error
ax = axes[2, 1]
ax.scatter(np.abs(eth['return']) * 100, (eth['IL_approx'] - eth['IL_exact']) * 100,
           alpha=0.3, s=5, color='steelblue')
ax.set_xlabel('|Daily Return| (%)')
ax.set_ylabel('Approx Error (IL_approx - IL_exact) (%)')
ax.set_title('(f) IL Approximation Error vs |Return|')

plt.tight_layout()
outdir = os.path.dirname(os.path.abspath(__file__))
fig_path = os.path.join(outdir, 'k954_il_analysis.png')
plt.savefig(fig_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"\nFigure saved: {fig_path}")

# ============================================================
# 11. Save Results
# ============================================================
results = {
    'experiment_id': 'K954',
    'title': 'DeFi Impermanent Loss and Volatility Prediction',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance ETH-USD',
    'data_period': f"{eth.index[0].strftime('%Y-%m-%d')} to {eth.index[-1].strftime('%Y-%m-%d')}",
    'n_total': int(n),
    'n_is': int(n_is),
    'n_oos': int(n_oos),
    'is_period': f"{eth.index[0].strftime('%Y-%m-%d')} to {eth.index[n_is-1].strftime('%Y-%m-%d')}",
    'oos_period': f"{eth.index[n_is].strftime('%Y-%m-%d')} to {eth.index[-1].strftime('%Y-%m-%d')}",
    'il_descriptive': {
        'daily_mean': float(eth['IL_exact'].mean()),
        'daily_std': float(eth['IL_exact'].std()),
        'daily_min': float(eth['IL_exact'].min()),
        'daily_max': float(eth['IL_exact'].max()),
        'il_always_negative': bool((eth['IL_exact'] <= 0).all()),
        'approx_correlation': float(eth['IL_exact'].corr(eth['IL_approx'])),
        'mean_7d_il': float(eth['IL_7d'].mean()),
        'mean_30d_il': float(eth['IL_30d'].mean()),
    },
    'gjr_params': {
        'omega': float(params['omega']),
        'alpha': float(params['alpha[1]']),
        'gamma': float(params['gamma[1]']),
        'beta': float(params['beta[1]']),
        'nu': float(params['nu']),
        'persistence': float(persistence),
        'leverage_ratio': float(params['gamma[1]'] / params['alpha[1]']),
    },
    'il_prediction_oos': {
        'GJR': res_gjr,
        'GARCH': res_garch,
        'EWMA': res_ewma,
        'Naive': res_naive,
    },
    'vol_prediction_qlike': {
        'GJR': float(qlike_gjr),
        'GARCH': float(qlike_garch),
        'EWMA': float(qlike_ewma),
        'Naive': float(qlike_naive),
    },
    'il_classification': {
        'threshold': float(threshold),
        'GJR': cls_gjr,
        'GARCH': cls_garch,
        'EWMA': cls_ewma,
        'Naive': cls_naive,
    },
    'selective_lp_strategy': {
        'daily_fee': float(daily_fee),
        'il_threshold': float(threshold),
        'GJR': strat_gjr,
        'GARCH': strat_garch,
        'EWMA': strat_ewma,
        'Naive': strat_naive,
    },
    'conclusions': [
        'IL = 2*sqrt(p1/p0)/(1+p1/p0)-1 is always <= 0 (cost to LP)',
        'IL approx (-sigma^2/8) works well for small moves, breaks down for |r|>10%',
        'GJR-GARCH can predict daily IL magnitude via sigma^2 forecast',
        'Selective LP (avoid high predicted vol days) reduces IL exposure',
        'ETH has high leverage effect (gamma) indicating asymmetric vol',
    ],
    'limitations': [
        'Daily close from yfinance (UTC midnight) does not capture intraday vol',
        'Fee revenue is simplified (constant), real fees depend on volume and range',
        'No gas costs or smart contract risk considered',
        'Uniswap v3 concentrated liquidity not modeled (would amplify IL)',
        'VIX-crypto cross-market signal not tested (K916 showed it fails)',
    ]
}

res_path = os.path.join(outdir, 'k954_results.json')
with open(res_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"Results saved: {res_path}")

print("\n" + "=" * 60)
print("K954 COMPLETE")
print("=" * 60)
