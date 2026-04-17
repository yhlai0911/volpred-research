"""
K420b: Taiwan Vol Prediction with Clean Data
Corrects K420's data contamination (2014-01-02 split artifact).

Step 1: Clean data (remove split artifact + extreme outliers)
Step 2: Verify diagnostics (ARCH effects should be present after cleaning)
Step 3: Compare models with proper diagnostics

Data: 0050.TW (cleaned), SPY, ^VIX from yfinance
Output: experiments/k420b_prs_taiwan_clean_results.json
"""
import yfinance as yf
import numpy as np
import pandas as pd
from scipy import stats
from arch import arch_model
from statsmodels.stats.diagnostic import het_arch, acorr_ljungbox
from statsmodels.tsa.stattools import adfuller
import json, warnings
from datetime import datetime, timezone

warnings.filterwarnings('ignore')

print("=" * 75)
print("K420b: Taiwan Vol Prediction (Clean Data)")
print("=" * 75)

# Data
tw50 = yf.download('0050.TW', start='2010-01-01', progress=False)
spy = yf.download('SPY', start='2010-01-01', progress=False)
vix = yf.download('^VIX', start='2010-01-01', progress=False)['Close'].dropna().squeeze()

tw50_close = tw50['Close'].dropna().squeeze()
spy_close = spy['Close'].dropna().squeeze()

common = tw50_close.index.intersection(spy_close.index).intersection(vix.index)
tw50_close = tw50_close.loc[common]
spy_close = spy_close.loc[common]
vix_v = vix.loc[common]

tw50_ret = tw50_close.pct_change().dropna()
spy_ret = spy_close.pct_change().dropna().reindex(tw50_ret.index).fillna(0)
vix_v = vix_v.reindex(tw50_ret.index).fillna(20)

# === STEP 1: Data Cleaning ===
print("--- Step 1: Data Cleaning ---")
print(f"Before cleaning: n={len(tw50_ret)}, skew={tw50_ret.skew():.2f}, kurt={tw50_ret.kurtosis():.2f}")

# Remove known split artifact and extreme outliers (>15%)
outlier_mask = tw50_ret.abs() < 0.15
tw50_ret_clean = tw50_ret[outlier_mask]
spy_ret_clean = spy_ret.reindex(tw50_ret_clean.index).fillna(0)
vix_clean = vix_v.reindex(tw50_ret_clean.index).fillna(20)

n_removed = len(tw50_ret) - len(tw50_ret_clean)
print(f"Removed {n_removed} outliers (>15%)")
print(f"After cleaning: n={len(tw50_ret_clean)}, skew={tw50_ret_clean.skew():.2f}, kurt={tw50_ret_clean.kurtosis():.2f}")

n = len(tw50_ret_clean)

# === STEP 2: Diagnostics ===
print(f"\n--- Step 2: Diagnostics ---")
adf = adfuller(tw50_ret_clean.values, maxlag=20)
print(f"ADF: stat={adf[0]:.3f}, p={adf[1]:.6f} ({'stationary' if adf[1]<0.05 else 'NON-stationary'})")

arch_lm = het_arch(tw50_ret_clean.values, nlags=5)
print(f"ARCH LM: stat={arch_lm[0]:.1f}, p={arch_lm[1]:.6f} ({'has ARCH ✓' if arch_lm[1]<0.05 else 'NO ARCH ✗'})")

lb = acorr_ljungbox(tw50_ret_clean.values, lags=10, return_df=True)
print(f"Ljung-Box(10): p={lb['lb_pvalue'].iloc[-1]:.4f}")

lb_sq = acorr_ljungbox(tw50_ret_clean.values**2, lags=10, return_df=True)
print(f"Ljung-Box(10) r²: p={lb_sq['lb_pvalue'].iloc[-1]:.6f} ({'vol clustering ✓' if lb_sq['lb_pvalue'].iloc[-1]<0.05 else 'no clustering'})")

# Spot-SPY relationship
corr_spy = float(tw50_ret_clean.corr(spy_ret_clean))
print(f"\n0050.TW-SPY correlation: {corr_spy:.3f}")

# === STEP 3: GARCH Estimation + Convergence Check ===
print(f"\n--- Step 3: GARCH Estimation ---")
all_r = tw50_ret_clean.values * 100
oos_start = '2020-01-01'
oos_mask = tw50_ret_clean.index >= oos_start
oos_start_loc = int(np.where(tw50_ret_clean.index >= oos_start)[0][0])
n_oos = int(oos_mask.sum())
print(f"OOS: {n_oos} days")

# Full-sample GARCH for diagnostics
m_full = arch_model(pd.Series(all_r), vol='GARCH', p=1, o=1, q=1, mean='Zero', dist='normal')
r_full = m_full.fit(disp='off', show_warning=False)
print(f"Converged: {r_full.convergence_flag == 0}")
omega = float(r_full.params.get('omega', 0))
alpha = float(r_full.params.get('alpha[1]', 0))
gamma = float(r_full.params.get('gamma[1]', 0))
beta = float(r_full.params.get('beta[1]', 0))
persistence = alpha + gamma/2 + beta
print(f"Params: ω={omega:.6f}, α={alpha:.4f}, γ={gamma:.4f}, β={beta:.4f}, persistence={persistence:.4f}")

# Residual check
std_resid = r_full.std_resid
lb_resid = acorr_ljungbox(std_resid**2, lags=10, return_df=True)['lb_pvalue'].iloc[-1]
print(f"Residual ARCH-free: p={lb_resid:.4f} ({'✓' if lb_resid > 0.05 else '✗ still ARCH'})")

# === STEP 4: OOS Model Comparison (1-step ahead) ===
print(f"\n{'='*70}")
print("Step 4: OOS Comparison (proper 1-step ahead)")
print(f"{'='*70}")

rv_proxy = tw50_ret_clean**2
rv_oos = rv_proxy[oos_mask]

# Model 1: GJR-GARCH
forecasts = {}
fc_gjr = []
for t in range(oos_start_loc, len(all_r)):
    try:
        m = arch_model(pd.Series(all_r[max(0,t-2000):t]), vol='GARCH', p=1, o=1, q=1, mean='Zero', dist='normal')
        r = m.fit(disp='off', show_warning=False)
        fc = r.forecast(horizon=1)
        fc_gjr.append(float(fc.variance.iloc[-1, 0]) / 10000)
    except:
        fc_gjr.append(fc_gjr[-1] if fc_gjr else float(tw50_ret_clean.var()))
forecasts['GJR-GARCH'] = pd.Series(fc_gjr, index=tw50_ret_clean.index[oos_mask])

# Model 2: EWMA(0.94)
lam = 0.94
ewma_var = float(tw50_ret_clean.iloc[:oos_start_loc].var())
fc_ewma = []
for t in range(oos_start_loc, len(all_r)):
    fc_ewma.append(ewma_var)
    ewma_var = lam * ewma_var + (1-lam) * (all_r[t]/100)**2
forecasts['EWMA(0.94)'] = pd.Series(fc_ewma, index=tw50_ret_clean.index[oos_mask])

# Model 3: GARCH-X with SPY
spy_abs = spy_ret_clean.abs().values * 100
fc_garchx = []
for t in range(oos_start_loc, len(all_r)):
    try:
        window = slice(max(0,t-2000), t)
        r_w = pd.Series(all_r[window])
        x_w = pd.DataFrame({'spy': spy_abs[window]})
        m = arch_model(r_w, vol='GARCH', p=1, o=1, q=1, mean='Zero', dist='normal', x=x_w)
        r = m.fit(disp='off', show_warning=False)
        fc = r.forecast(horizon=1, x=pd.DataFrame({'spy': [spy_abs[t-1]]}))
        fc_garchx.append(float(fc.variance.iloc[-1, 0]) / 10000)
    except:
        fc_garchx.append(fc_gjr[t-oos_start_loc] if t-oos_start_loc < len(fc_gjr) else float(tw50_ret_clean.var()))
forecasts['GARCH-X(SPY)'] = pd.Series(fc_garchx, index=tw50_ret_clean.index[oos_mask])

# Model 4: VIX-based
vix_oos = vix_clean[oos_mask]
forecasts['VIX-based'] = (vix_oos / 100 / np.sqrt(252))**2

def qlike(actual, forecast):
    valid = (actual > 0) & (forecast > 0)
    a, f = actual[valid], forecast[valid]
    return float(np.mean(np.log(f) + a/f))

print(f"\n{'Model':<18} {'QLIKE':>10} {'vs GJR':>10} {'DM t':>8} {'Harvey':>8}")
print("-" * 58)

qlike_gjr = qlike(rv_oos, forecasts['GJR-GARCH'])
for mname, fc in forecasts.items():
    ql = qlike(rv_oos, fc)
    pct_diff = (ql - qlike_gjr) / abs(qlike_gjr) * 100

    if mname == 'GJR-GARCH':
        print(f"{mname:<18} {ql:>10.4f} {'baseline':>10} {'—':>8} {'—':>8}")
        continue

    loss_gjr = np.log(forecasts['GJR-GARCH']) + rv_oos/forecasts['GJR-GARCH']
    loss_alt = np.log(fc) + rv_oos/fc
    d = (loss_gjr - loss_alt).dropna()
    dm_t = float(d.mean() / (d.std() / np.sqrt(len(d)))) if d.std() > 0 else 0
    harvey = "★ PASS" if abs(dm_t) > 3 else "FAIL"
    print(f"{mname:<18} {ql:>10.4f} {pct_diff:>+9.2f}% {dm_t:>8.2f} {harvey:>8}")

# Save
output = {
    'experiment': 'K420b',
    'title': 'Taiwan Vol Prediction (Clean Data)',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_cleaning': {'removed': n_removed, 'n_after': n},
    'diagnostics': {
        'skew': round(float(tw50_ret_clean.skew()), 2),
        'kurt': round(float(tw50_ret_clean.kurtosis()), 2),
        'adf_p': round(float(adf[1]), 6),
        'arch_lm_p': round(float(arch_lm[1]), 6),
        'has_arch': float(arch_lm[1]) < 0.05,
    },
    'garch_convergence': {
        'converged': r_full.convergence_flag == 0,
        'persistence': round(persistence, 4),
        'resid_arch_free': float(lb_resid) > 0.05,
    },
    'qlike': {m: round(qlike(rv_oos, fc), 4) for m, fc in forecasts.items()},
}

with open('experiments/k420b_prs_taiwan_clean_results.json', 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)

print(f"\nResults saved to experiments/k420b_prs_taiwan_clean_results.json")
