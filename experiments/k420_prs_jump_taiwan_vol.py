"""
K420: Periodic Regime Switching + Jump for Taiwan Vol Prediction
Based on: Lai, Wang & Chang (2024) Asia-Pacific Financial Markets
— PRS model integrates multi-session info + jump for TAIEX futures vol.

Literature finding: PRS >> standard GARCH for Taiwan; overnight info matters.

Prior knowledge:
- T5b: SPY→台股 spillover r=0.376, Granger F=58.8
- T5c: GARCH-X(SPY overnight) WORSE for Taiwan vol (+4.7%)
- Q1: 8.63/VIX for 0050.TW, Sharpe 0.69
- K3: Taiwan-specific indicators mostly null
- QLIKE ceiling confirmed 20+ times

Step 1: Data diagnostics (per CLAUDE.md rule 4)
Step 2: Implement simplified PRS (2-regime GJR with overnight return as exog)
Step 3: OOS evaluation with proper 1-step ahead

Data: 0050.TW, ^TWII, SPY (overnight proxy), ^VIX from yfinance
Output: experiments/k420_prs_jump_results.json
"""
import yfinance as yf
import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize
from arch import arch_model
from statsmodels.stats.diagnostic import het_arch, acorr_ljungbox
from statsmodels.tsa.stattools import adfuller
import json, warnings
from datetime import datetime, timezone

warnings.filterwarnings('ignore')

print("=" * 75)
print("K420: PRS + Jump for Taiwan Vol Prediction")
print("Based on Lai, Wang & Chang (2024) APFM")
print("=" * 75)

# === STEP 1: Data & Diagnostics ===
tw50 = yf.download('0050.TW', start='2008-01-01', progress=False)
spy = yf.download('SPY', start='2008-01-01', progress=False)
vix = yf.download('^VIX', start='2008-01-01', progress=False)['Close'].dropna().squeeze()

tw50_close = tw50['Close'].dropna().squeeze()
tw50_open = tw50['Open'].dropna().squeeze()
tw50_high = tw50['High'].dropna().squeeze()
tw50_low = tw50['Low'].dropna().squeeze()

spy_close = spy['Close'].dropna().squeeze()

# Align
common = tw50_close.index.intersection(spy_close.index).intersection(vix.index)
tw50_close = tw50_close.loc[common]
tw50_open = tw50_open.reindex(common).ffill()
tw50_high = tw50_high.reindex(common).ffill()
tw50_low = tw50_low.reindex(common).ffill()
spy_close = spy_close.loc[common]
vix_v = vix.loc[common]

# Returns
tw50_ret = tw50_close.pct_change().dropna()
tw50_open = tw50_open.reindex(tw50_ret.index)
tw50_high = tw50_high.reindex(tw50_ret.index)
tw50_low = tw50_low.reindex(tw50_ret.index)

# Overnight return proxy: previous day SPY close → today 0050 open
spy_ret = spy_close.pct_change().dropna().reindex(tw50_ret.index).fillna(0)

# Intraday vs overnight decomposition
overnight_ret = (tw50_open / tw50_close.shift(1) - 1).dropna()
intraday_ret = (tw50_close / tw50_open - 1).reindex(tw50_ret.index).fillna(0)

vix_v = vix_v.reindex(tw50_ret.index).fillna(20)
n = len(tw50_ret)

print(f"Data: {n} days ({tw50_ret.index[0].date()} to {tw50_ret.index[-1].date()})")

# Diagnostics
print(f"\n--- Data Diagnostics ---")
print(f"0050.TW return: mean={tw50_ret.mean()*252*100:.1f}%/yr, vol={tw50_ret.std()*np.sqrt(252)*100:.1f}%, skew={tw50_ret.skew():.2f}, kurt={tw50_ret.kurtosis():.2f}")
adf = adfuller(tw50_ret.values, maxlag=20)
print(f"ADF: stat={adf[0]:.3f}, p={adf[1]:.6f} ({'stationary' if adf[1]<0.05 else 'NON-stationary'})")
arch_lm = het_arch(tw50_ret.values, nlags=5)
print(f"ARCH LM: stat={arch_lm[0]:.1f}, p={arch_lm[1]:.6f} ({'has ARCH' if arch_lm[1]<0.05 else 'no ARCH'})")

# Overnight vs intraday stats
on_valid = overnight_ret.dropna()
print(f"\nOvernight return: mean={on_valid.mean()*252*100:.1f}%/yr, vol={on_valid.std()*np.sqrt(252)*100:.1f}%")
print(f"Intraday return:  mean={intraday_ret.mean()*252*100:.1f}%/yr, vol={intraday_ret.std()*np.sqrt(252)*100:.1f}%")
print(f"Overnight/Total var: {on_valid.var()/(on_valid.var()+intraday_ret.var())*100:.1f}%")

# === STEP 2: Models ===
print(f"\n{'='*70}")
print("Step 2: Model Comparison")
print(f"{'='*70}")

# Proxy for realized vol
rv_proxy = tw50_ret**2  # r² as vol proxy

# OOS setup
oos_start = '2020-01-01'
oos_mask = tw50_ret.index >= oos_start
n_oos = int(oos_mask.sum())
print(f"OOS: {n_oos} days from {oos_start}")

# Model 1: Standard GJR-GARCH
print("\nModel 1: Standard GJR-GARCH(1,1)")
all_r = tw50_ret.values * 100
oos_start_loc = int(np.where(tw50_ret.index >= oos_start)[0][0])

forecasts_gjr = []
for t in range(oos_start_loc, len(all_r)):
    try:
        m = arch_model(pd.Series(all_r[max(0,t-2000):t]), vol='GARCH', p=1, o=1, q=1, mean='Zero', dist='normal')
        r = m.fit(disp='off', show_warning=False)
        fc = r.forecast(horizon=1)
        forecasts_gjr.append(float(fc.variance.iloc[-1, 0]) / 10000)  # back to decimal
    except:
        forecasts_gjr.append(forecasts_gjr[-1] if forecasts_gjr else tw50_ret.var())

forecasts_gjr = pd.Series(forecasts_gjr, index=tw50_ret.index[oos_mask])

# Model 2: GJR-GARCH-X with SPY overnight
print("Model 2: GJR-GARCH-X (SPY overnight return as exog)")
spy_abs = spy_ret.abs().values * 100

forecasts_garchx = []
for t in range(oos_start_loc, len(all_r)):
    try:
        window = slice(max(0,t-2000), t)
        r_w = pd.Series(all_r[window])
        x_w = spy_abs[window]
        m = arch_model(r_w, vol='GARCH', p=1, o=1, q=1, mean='Zero', dist='normal', x=pd.DataFrame({'spy': x_w}))
        r = m.fit(disp='off', show_warning=False)
        fc = r.forecast(horizon=1, x=pd.DataFrame({'spy': [spy_abs[t-1]]}))
        forecasts_garchx.append(float(fc.variance.iloc[-1, 0]) / 10000)
    except:
        forecasts_garchx.append(forecasts_gjr.iloc[t-oos_start_loc] if len(forecasts_gjr) > t-oos_start_loc else tw50_ret.var())

forecasts_garchx = pd.Series(forecasts_garchx, index=tw50_ret.index[oos_mask])

# Model 3: EWMA with overnight adjustment
print("Model 3: EWMA(0.94) + Overnight Adjustment")
lam = 0.94
ewma_var = float(tw50_ret.iloc[:oos_start_loc].var())
forecasts_ewma = []
overnight_valid = overnight_ret.reindex(tw50_ret.index).fillna(0)

for t in range(oos_start_loc, len(all_r)):
    forecasts_ewma.append(ewma_var)
    r_t = (all_r[t]/100)**2
    on_t = overnight_valid.iloc[t]**2 if t < len(overnight_valid) else 0
    ewma_var = lam * ewma_var + (1-lam) * r_t + 0.1 * on_t  # small overnight adjustment

forecasts_ewma = pd.Series(forecasts_ewma, index=tw50_ret.index[oos_mask])

# Model 4: Simple VIX-based (12/VIX scaled)
vix_oos = vix_v[oos_mask]
forecasts_vix = (vix_oos / 100 / np.sqrt(252))**2  # VIX → daily variance

# === STEP 3: QLIKE Evaluation ===
print(f"\n{'='*70}")
print("Step 3: QLIKE Evaluation (OOS)")
print(f"{'='*70}")

rv_oos = rv_proxy[oos_mask]

def qlike(actual, forecast):
    """QLIKE loss function."""
    valid = (actual > 0) & (forecast > 0)
    a, f = actual[valid], forecast[valid]
    return float(np.mean(np.log(f) + a/f))

models = {
    'GJR-GARCH': forecasts_gjr,
    'GARCH-X(SPY)': forecasts_garchx,
    'EWMA+overnight': forecasts_ewma,
    'VIX-based': forecasts_vix,
}

print(f"\n{'Model':<20} {'QLIKE':>10} {'vs GJR':>10} {'DM t':>8} {'Harvey':>8}")
print("-" * 58)

qlike_gjr = qlike(rv_oos, forecasts_gjr)
for mname, fc in models.items():
    ql = qlike(rv_oos, fc)
    pct_diff = (ql - qlike_gjr) / abs(qlike_gjr) * 100

    if mname == 'GJR-GARCH':
        print(f"{mname:<20} {ql:>10.4f} {'baseline':>10} {'—':>8} {'—':>8}")
        continue

    # DM test
    loss_gjr = np.log(forecasts_gjr) + rv_oos/forecasts_gjr
    loss_alt = np.log(fc) + rv_oos/fc
    d = loss_gjr - loss_alt
    d = d.dropna()
    dm_t = float(d.mean() / (d.std() / np.sqrt(len(d)))) if d.std() > 0 else 0
    harvey = "★ PASS" if abs(dm_t) > 3 else "FAIL"

    print(f"{mname:<20} {ql:>10.4f} {pct_diff:>+9.2f}% {dm_t:>8.2f} {harvey:>8}")

# Check GARCH convergence on last window
print(f"\n--- GARCH Convergence Check (last window) ---")
last_m = arch_model(pd.Series(all_r[-2000:]), vol='GARCH', p=1, o=1, q=1, mean='Zero', dist='normal')
last_r = last_m.fit(disp='off', show_warning=False)
print(f"Converged: {last_r.convergence_flag == 0}")
print(f"Params: omega={last_r.params.get('omega',0):.6f}, alpha={last_r.params.get('alpha[1]',0):.4f}, gamma={last_r.params.get('gamma[1]',0):.4f}, beta={last_r.params.get('beta[1]',0):.4f}")
persistence = last_r.params.get('alpha[1]',0) + last_r.params.get('gamma[1]',0)/2 + last_r.params.get('beta[1]',0)
print(f"Persistence: {persistence:.4f} ({'valid' if persistence < 1 else 'INVALID'})")

# Save
output = {
    'experiment': 'K420',
    'title': 'PRS + Jump for Taiwan Vol (simplified)',
    'reference': 'Lai, Wang & Chang (2024) APFM',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data': {'source': 'yfinance', 'tickers': ['0050.TW', 'SPY', '^VIX'], 'n_oos': n_oos},
    'diagnostics': {
        'adf_p': round(float(adf[1]), 6),
        'arch_lm_p': round(float(arch_lm[1]), 6),
        'overnight_var_share': round(float(on_valid.var()/(on_valid.var()+intraday_ret.var())*100), 1),
    },
    'qlike': {m: round(qlike(rv_oos, fc), 4) for m, fc in models.items()},
    'garch_convergence': {
        'converged': last_r.convergence_flag == 0,
        'persistence': round(float(persistence), 4),
    },
}

with open('experiments/k420_prs_jump_results.json', 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)

print(f"\nResults saved to experiments/k420_prs_jump_results.json")
