"""
K381: DeFi Governance Token Volatility — UNI and AAVE vs BTC
============================================================
[提出: Claude, 執行: Claude]

跳躍式探索: First experiment on DeFi governance tokens.
Prior work: K277 BTC no leverage effect, K334 DeFi pilot (BTC/ETH only),
           K202 BTC VIX failure.

Question: Are DeFi governance tokens fundamentally different from BTC/ETH
          in their volatility structure? Can GARCH models work for them?

Data: yfinance (UNI-USD, AAVE-USD, BTC-USD, ETH-USD, SPY, ^VIX)
Period: All available (UNI ~Sep 2020, AAVE ~Oct 2020)
Status: PRELIMINARY (short history ~5 years)
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime
import json
import warnings
warnings.filterwarnings('ignore')

print("=" * 70)
print("K381: DeFi Governance Token Volatility — UNI & AAVE vs BTC")
print("=" * 70)
print(f"Run date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print()

# ─────────────────────────────────────────────────────────
# 1. DATA COLLECTION
# ─────────────────────────────────────────────────────────
print("=" * 70)
print("SECTION 1: Data Collection")
print("=" * 70)

tickers = {
    'UNI': 'UNI7083-USD',   # Correct Uniswap ticker (UNI-USD returns wrong token)
    'AAVE': 'AAVE-USD',
    'BTC': 'BTC-USD',
    'ETH': 'ETH-USD',
    'SPY': 'SPY',
}
# NOTE: UNI-USD on yfinance returns a corrupted/different token (prices ~0.0000).
# UNI7083-USD is the correct Uniswap governance token ($5-$40 range).

# Download all data
data = {}
for name, ticker in tickers.items():
    try:
        df = yf.download(ticker, start='2020-01-01', end='2026-03-25',
                         auto_adjust=True, progress=False)
        if len(df) > 100:
            data[name] = df
            print(f"  {name:5s}: {len(df):5d} obs, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
        else:
            print(f"  {name}: INSUFFICIENT DATA ({len(df)} obs)")
    except Exception as e:
        print(f"  {name}: DOWNLOAD FAILED: {e}")

# VIX separately
try:
    vix_df = yf.download('^VIX', start='2020-01-01', end='2026-03-25',
                          auto_adjust=True, progress=False)
    print(f"  VIX  : {len(vix_df):5d} obs")
except Exception as e:
    print(f"  VIX: DOWNLOAD FAILED: {e}")
    vix_df = None

# Compute returns
returns = {}
for name, df in data.items():
    close = df['Close'].squeeze()
    ret = np.log(close / close.shift(1)).dropna()
    returns[name] = ret

print(f"\nAll returns computed. Common period analysis follows.\n")

# Find common date range (intersection of UNI, AAVE, BTC, ETH, SPY)
# Note: crypto trades 7 days/week, SPY trades Mon-Fri only
# We align to SPY trading days for fair comparison
common_idx = returns['SPY'].index
for name in ['UNI', 'AAVE', 'BTC', 'ETH']:
    if name in returns:
        common_idx = common_idx.intersection(returns[name].index)

print(f"Common trading days (aligned to SPY): {len(common_idx)}")
print(f"Period: {common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')}")

# Aligned returns on common dates
aligned = {}
for name in ['UNI', 'AAVE', 'BTC', 'ETH', 'SPY']:
    if name in returns:
        aligned[name] = returns[name].reindex(common_idx).dropna()

# Also keep full crypto returns (including weekends) for vol calculation
crypto_full = {}
for name in ['UNI', 'AAVE', 'BTC', 'ETH']:
    if name in returns:
        crypto_full[name] = returns[name]

# ─────────────────────────────────────────────────────────
# 2. BASIC VOLATILITY CHARACTERISTICS
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SECTION 2: Basic Volatility Characteristics")
print("=" * 70)

print("\n--- 2a: Annualized Volatility (aligned to SPY trading days) ---")
print(f"{'Asset':6s} {'Ann Vol':>8s} {'Mean':>8s} {'Skew':>8s} {'Kurt':>8s} {'Min':>8s} {'Max':>8s} {'N':>6s}")
print("-" * 62)

stats_table = {}
for name in ['UNI', 'AAVE', 'BTC', 'ETH', 'SPY']:
    r = aligned[name]
    ann_vol = r.std() * np.sqrt(252) * 100
    ann_mean = r.mean() * 252 * 100
    skewness = stats.skew(r.dropna())
    kurtosis = stats.kurtosis(r.dropna())  # excess kurtosis
    stats_table[name] = {
        'ann_vol': float(ann_vol),
        'ann_mean': float(ann_mean),
        'skewness': float(skewness),
        'kurtosis': float(kurtosis),
        'min_ret': float(r.min() * 100),
        'max_ret': float(r.max() * 100),
        'n_obs': len(r)
    }
    print(f"{name:6s} {ann_vol:7.1f}% {ann_mean:7.1f}% {skewness:8.3f} {kurtosis:8.2f} {r.min()*100:7.1f}% {r.max()*100:7.1f}% {len(r):6d}")

print("\nInterpretation:")
uni_vol = stats_table['UNI']['ann_vol']
aave_vol = stats_table['AAVE']['ann_vol']
btc_vol = stats_table['BTC']['ann_vol']
spy_vol = stats_table['SPY']['ann_vol']
print(f"  UNI vol / BTC vol  = {uni_vol/btc_vol:.2f}x")
print(f"  AAVE vol / BTC vol = {aave_vol/btc_vol:.2f}x")
print(f"  UNI vol / SPY vol  = {uni_vol/spy_vol:.2f}x")
print(f"  BTC vol / SPY vol  = {btc_vol/spy_vol:.2f}x")

# Full crypto vol (including weekends)
print("\n--- 2b: Full Crypto Vol (all days including weekends) ---")
print(f"{'Asset':6s} {'Ann Vol (√365)':>14s} {'N_obs':>6s}")
print("-" * 30)
for name in ['UNI', 'AAVE', 'BTC', 'ETH']:
    r = crypto_full[name]
    ann_vol_365 = r.std() * np.sqrt(365) * 100
    print(f"{name:6s} {ann_vol_365:13.1f}% {len(r):6d}")

# ─────────────────────────────────────────────────────────
# 3. LEVERAGE EFFECT TEST
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SECTION 3: Leverage Effect (Asymmetric Volatility)")
print("=" * 70)
print("Test: Correlation between r_t and |r_{t+1}|")
print("Negative correlation = leverage effect (drops increase future vol)")
print()

print(f"{'Asset':6s} {'Corr(r,|r+1|)':>14s} {'t-stat':>8s} {'p-value':>8s} {'Effect':>12s}")
print("-" * 55)

leverage_results = {}
for name in ['UNI', 'AAVE', 'BTC', 'ETH', 'SPY']:
    r = aligned[name].values
    r_t = r[:-1]
    abs_r_t1 = np.abs(r[1:])
    corr, pval = stats.pearsonr(r_t, abs_r_t1)
    n = len(r_t)
    t_stat = corr * np.sqrt(n - 2) / np.sqrt(1 - corr**2)

    if pval < 0.01 and corr < 0:
        effect = "STRONG"
    elif pval < 0.05 and corr < 0:
        effect = "MODERATE"
    elif corr < 0:
        effect = "WEAK"
    else:
        effect = "ABSENT"

    leverage_results[name] = {
        'correlation': float(corr),
        't_stat': float(t_stat),
        'p_value': float(pval),
        'effect': effect
    }
    print(f"{name:6s} {corr:14.4f} {t_stat:8.3f} {pval:8.4f} {effect:>12s}")

# Also test with squared returns: corr(r_t, r_{t+1}^2)
print("\n--- Alternative: Corr(r_t, r_{t+1}^2) ---")
print(f"{'Asset':6s} {'Corr':>10s} {'t-stat':>8s} {'p-value':>8s}")
print("-" * 35)
for name in ['UNI', 'AAVE', 'BTC', 'ETH', 'SPY']:
    r = aligned[name].values
    r_t = r[:-1]
    r2_t1 = r[1:]**2
    corr, pval = stats.pearsonr(r_t, r2_t1)
    n = len(r_t)
    t_stat = corr * np.sqrt(n - 2) / np.sqrt(1 - corr**2)
    print(f"{name:6s} {corr:10.4f} {t_stat:8.3f} {pval:8.4f}")

# ─────────────────────────────────────────────────────────
# 4. VOLATILITY CLUSTERING (ACF of squared returns)
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SECTION 4: Volatility Clustering Strength")
print("=" * 70)
print("ACF of squared returns at lags 1, 5, 10, 21")
print()

def acf_manual(x, lag):
    """Compute autocorrelation at given lag."""
    x = np.array(x)
    n = len(x)
    mean = np.mean(x)
    var = np.var(x)
    if var == 0:
        return 0.0
    cov = np.mean((x[:n-lag] - mean) * (x[lag:] - mean))
    return cov / var

print(f"{'Asset':6s} {'ACF(1)':>8s} {'ACF(5)':>8s} {'ACF(10)':>8s} {'ACF(21)':>8s} {'Ljung-Box(10)':>14s} {'p-val':>8s}")
print("-" * 62)

clustering_results = {}
for name in ['UNI', 'AAVE', 'BTC', 'ETH', 'SPY']:
    r = aligned[name].values
    r2 = r**2

    acf1 = acf_manual(r2, 1)
    acf5 = acf_manual(r2, 5)
    acf10 = acf_manual(r2, 10)
    acf21 = acf_manual(r2, 21)

    # Ljung-Box test (manual)
    n = len(r2)
    K = 10
    lb_stat = n * (n + 2) * sum(acf_manual(r2, k)**2 / (n - k) for k in range(1, K+1))
    lb_pval = 1 - stats.chi2.cdf(lb_stat, K)

    clustering_results[name] = {
        'acf1': float(acf1),
        'acf5': float(acf5),
        'acf10': float(acf10),
        'acf21': float(acf21),
        'ljung_box_10': float(lb_stat),
        'lb_pval': float(lb_pval)
    }
    print(f"{name:6s} {acf1:8.4f} {acf5:8.4f} {acf10:8.4f} {acf21:8.4f} {lb_stat:14.1f} {lb_pval:8.4f}")

print("\nInterpretation:")
print("  Higher ACF = stronger vol clustering = GARCH more applicable")
print("  LB p<0.05 = significant clustering")

# ─────────────────────────────────────────────────────────
# 5. DeFi-BTC CORRELATION AND BETA
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SECTION 5: DeFi-BTC Relationship")
print("=" * 70)

# 5a: Unconditional correlation matrix
print("\n--- 5a: Correlation Matrix (returns) ---")
ret_df = pd.DataFrame(aligned)
corr_matrix = ret_df.corr()
print(corr_matrix.round(3).to_string())

# 5b: Beta to BTC
print("\n--- 5b: Beta to BTC (OLS: r_DeFi = alpha + beta * r_BTC + eps) ---")
print(f"{'Asset':6s} {'Beta':>8s} {'Alpha(ann%)':>12s} {'R²':>8s} {'Resid Vol(ann%)':>16s}")
print("-" * 55)

beta_results = {}
for name in ['UNI', 'AAVE', 'ETH', 'SPY']:
    y = aligned[name].values
    x = aligned['BTC'].values

    # Ensure same length
    min_len = min(len(y), len(x))
    y = y[:min_len]
    x = x[:min_len]

    # OLS
    x_const = np.column_stack([np.ones(len(x)), x])
    beta_hat = np.linalg.lstsq(x_const, y, rcond=None)[0]
    y_hat = x_const @ beta_hat
    residuals = y - y_hat

    ss_res = np.sum(residuals**2)
    ss_tot = np.sum((y - np.mean(y))**2)
    r_squared = 1 - ss_res / ss_tot

    alpha_ann = beta_hat[0] * 252 * 100
    resid_vol_ann = np.std(residuals) * np.sqrt(252) * 100

    beta_results[name] = {
        'beta_btc': float(beta_hat[1]),
        'alpha_ann_pct': float(alpha_ann),
        'r_squared': float(r_squared),
        'resid_vol_ann_pct': float(resid_vol_ann)
    }
    print(f"{name:6s} {beta_hat[1]:8.3f} {alpha_ann:12.1f} {r_squared:8.3f} {resid_vol_ann:16.1f}")

print("\nInterpretation:")
print("  Beta > 1: DeFi token amplifies BTC moves")
print("  Low R²: DeFi has significant idiosyncratic risk")
print("  High residual vol: DeFi-specific risk is large")

# 5c: Rolling correlation (60-day)
print("\n--- 5c: Rolling 60-day Correlation with BTC ---")
window = 60
for name in ['UNI', 'AAVE', 'ETH', 'SPY']:
    r1 = aligned[name]
    r2 = aligned['BTC']
    common = r1.index.intersection(r2.index)
    r1 = r1.reindex(common)
    r2 = r2.reindex(common)

    rolling_corr = r1.rolling(window).corr(r2).dropna()
    print(f"  {name}-BTC: mean={rolling_corr.mean():.3f}, min={rolling_corr.min():.3f}, "
          f"max={rolling_corr.max():.3f}, std={rolling_corr.std():.3f}")

# ─────────────────────────────────────────────────────────
# 6. DeFi-TradFi CONNECTION
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SECTION 6: DeFi-TradFi Connection")
print("=" * 70)

# 6a: DeFi-SPY correlation over time
print("\n--- 6a: Rolling 60-day Correlation with SPY ---")
for name in ['UNI', 'AAVE', 'BTC', 'ETH']:
    r1 = aligned[name]
    r2 = aligned['SPY']
    common = r1.index.intersection(r2.index)
    r1 = r1.reindex(common)
    r2 = r2.reindex(common)

    rolling_corr = r1.rolling(window).corr(r2).dropna()
    print(f"  {name}-SPY: mean={rolling_corr.mean():.3f}, min={rolling_corr.min():.3f}, "
          f"max={rolling_corr.max():.3f}, std={rolling_corr.std():.3f}")

# 6b: VIX impact on DeFi
if vix_df is not None:
    print("\n--- 6b: VIX Impact on DeFi Vol ---")
    print("Regression: |r_DeFi| = a + b * VIX_level + eps")
    print(f"{'Asset':6s} {'b (slope)':>10s} {'t-stat':>8s} {'p-value':>8s} {'R²':>8s}")
    print("-" * 42)

    vix_close = vix_df['Close'].squeeze()

    for name in ['UNI', 'AAVE', 'BTC', 'ETH', 'SPY']:
        r = aligned[name]
        common = r.index.intersection(vix_close.index)
        if len(common) < 100:
            print(f"  {name}: insufficient overlap")
            continue

        abs_r = np.abs(r.reindex(common).values)
        vix_vals = vix_close.reindex(common).values

        # Remove NaN
        mask = ~(np.isnan(abs_r) | np.isnan(vix_vals))
        abs_r = abs_r[mask]
        vix_vals = vix_vals[mask]

        x_const = np.column_stack([np.ones(len(vix_vals)), vix_vals])
        beta_hat = np.linalg.lstsq(x_const, abs_r, rcond=None)[0]
        y_hat = x_const @ beta_hat
        residuals = abs_r - y_hat

        ss_res = np.sum(residuals**2)
        ss_tot = np.sum((abs_r - np.mean(abs_r))**2)
        r_sq = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        n = len(abs_r)
        se = np.sqrt(ss_res / (n - 2) / np.sum((vix_vals - np.mean(vix_vals))**2))
        t_stat = beta_hat[1] / se
        p_val = 2 * (1 - stats.t.cdf(abs(t_stat), n - 2))

        print(f"{name:6s} {beta_hat[1]:10.6f} {t_stat:8.3f} {p_val:8.4f} {r_sq:8.4f}")

# ─────────────────────────────────────────────────────────
# 7. EXTREME EVENTS ANALYSIS
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SECTION 7: Extreme Events Analysis")
print("=" * 70)

print("\n--- 7a: Tail Distribution (% of days with |r| > threshold) ---")
thresholds = [0.03, 0.05, 0.10, 0.15, 0.20]
print(f"{'Asset':6s}", end="")
for t in thresholds:
    print(f" {'>'}{t*100:.0f}%{'':>4s}", end="")
print()
print("-" * 50)

for name in ['UNI', 'AAVE', 'BTC', 'ETH', 'SPY']:
    r = aligned[name].values
    print(f"{name:6s}", end="")
    for t in thresholds:
        pct = np.mean(np.abs(r) > t) * 100
        print(f" {pct:7.1f}%", end="")
    print()

# 7b: Worst drawdowns
print("\n--- 7b: Top 5 Worst Single-Day Returns ---")
for name in ['UNI', 'AAVE', 'BTC', 'ETH', 'SPY']:
    r = aligned[name]
    worst = r.nsmallest(5)
    print(f"\n  {name}:")
    for date, val in worst.items():
        print(f"    {date.strftime('%Y-%m-%d')}: {val*100:+.1f}%")

# 7c: Concurrent crashes
print("\n--- 7c: Concurrent Crash Analysis ---")
print("When BTC drops >5%, how much do DeFi tokens drop?")
btc_crashes = aligned['BTC'][aligned['BTC'] < -0.05]
print(f"\nBTC crash days (>5% drop): {len(btc_crashes)}")
if len(btc_crashes) > 0:
    print(f"{'Date':12s} {'BTC':>8s} {'UNI':>8s} {'AAVE':>8s} {'ETH':>8s} {'SPY':>8s}")
    print("-" * 50)
    for date in btc_crashes.index:
        print(f"{date.strftime('%Y-%m-%d'):12s}", end="")
        for name in ['BTC', 'UNI', 'AAVE', 'ETH', 'SPY']:
            if date in aligned[name].index:
                print(f" {aligned[name].loc[date]*100:+7.1f}%", end="")
            else:
                print(f" {'N/A':>7s}", end="")
        print()

    # Average response
    print(f"\n{'Average':12s}", end="")
    for name in ['BTC', 'UNI', 'AAVE', 'ETH', 'SPY']:
        vals = []
        for date in btc_crashes.index:
            if date in aligned[name].index:
                vals.append(aligned[name].loc[date])
        if vals:
            print(f" {np.mean(vals)*100:+7.1f}%", end="")
    print()

    # Beta during crashes
    print("\n  Crash beta (avg DeFi drop / avg BTC drop):")
    avg_btc = np.mean([aligned['BTC'].loc[d] for d in btc_crashes.index])
    for name in ['UNI', 'AAVE', 'ETH']:
        vals = [aligned[name].loc[d] for d in btc_crashes.index if d in aligned[name].index]
        if vals:
            crash_beta = np.mean(vals) / avg_btc
            print(f"    {name}: {crash_beta:.2f}x")

# ─────────────────────────────────────────────────────────
# 8. GARCH FEASIBILITY FOR DeFi TOKENS
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SECTION 8: GARCH Feasibility for DeFi Tokens")
print("=" * 70)

try:
    from arch import arch_model

    garch_results = {}
    print(f"\n{'Asset':6s} {'omega':>10s} {'alpha':>8s} {'beta':>8s} {'gamma':>8s} {'persist':>8s} {'HL(days)':>9s} {'AIC':>10s} {'Conv':>5s}")
    print("-" * 78)

    for name in ['UNI', 'AAVE', 'BTC', 'ETH', 'SPY']:
        r = aligned[name].dropna() * 100  # percentage returns for arch

        # Try GJR-GARCH(1,1)
        try:
            model = arch_model(r, vol='Garch', p=1, o=1, q=1,
                              mean='Constant', dist='t')
            result = model.fit(disp='off', show_warning=False)

            params = result.params
            omega = params.get('omega', np.nan)
            alpha = params.get('alpha[1]', np.nan)
            beta_g = params.get('beta[1]', np.nan)
            gamma = params.get('gamma[1]', np.nan)

            persistence = alpha + beta_g + 0.5 * gamma
            if persistence < 1 and persistence > 0:
                half_life = np.log(0.5) / np.log(persistence)
            else:
                half_life = np.nan

            garch_results[name] = {
                'omega': float(omega),
                'alpha': float(alpha),
                'beta': float(beta_g),
                'gamma': float(gamma),
                'persistence': float(persistence),
                'half_life': float(half_life) if not np.isnan(half_life) else None,
                'aic': float(result.aic),
                'converged': result.convergence_flag == 0
            }

            conv = "YES" if result.convergence_flag == 0 else "NO"
            print(f"{name:6s} {omega:10.4f} {alpha:8.4f} {beta_g:8.4f} {gamma:8.4f} "
                  f"{persistence:8.4f} {half_life:9.1f} {result.aic:10.1f} {conv:>5s}")
        except Exception as e:
            print(f"{name:6s} GJR-GARCH FAILED: {e}")
            garch_results[name] = {'error': str(e)}

    # Compare GARCH vs EGARCH for DeFi
    print("\n--- EGARCH comparison for DeFi tokens ---")
    print(f"{'Asset':6s} {'alpha':>8s} {'gamma':>8s} {'beta':>8s} {'AIC':>10s} {'GJR AIC':>10s} {'Better':>8s}")
    print("-" * 60)

    for name in ['UNI', 'AAVE', 'BTC', 'ETH']:
        r = aligned[name].dropna() * 100
        try:
            model_e = arch_model(r, vol='EGARCH', p=1, o=1, q=1,
                                mean='Constant', dist='t')
            result_e = model_e.fit(disp='off', show_warning=False)

            params_e = result_e.params
            alpha_e = params_e.get('alpha[1]', np.nan)
            gamma_e = params_e.get('gamma[1]', np.nan)
            beta_e = params_e.get('beta[1]', np.nan)

            gjr_aic = garch_results.get(name, {}).get('aic', np.nan)
            better = "EGARCH" if result_e.aic < gjr_aic else "GJR"

            print(f"{name:6s} {alpha_e:8.4f} {gamma_e:8.4f} {beta_e:8.4f} "
                  f"{result_e.aic:10.1f} {gjr_aic:10.1f} {better:>8s}")
        except Exception as e:
            print(f"{name:6s} EGARCH FAILED: {e}")

    # Standardized residuals diagnostics
    print("\n--- Standardized Residuals Diagnostics ---")
    print(f"{'Asset':6s} {'Mean':>8s} {'Std':>8s} {'Skew':>8s} {'Kurt':>8s} {'JB stat':>10s} {'JB p':>8s}")
    print("-" * 58)

    for name in ['UNI', 'AAVE', 'BTC', 'ETH', 'SPY']:
        r = aligned[name].dropna() * 100
        try:
            model = arch_model(r, vol='Garch', p=1, o=1, q=1,
                              mean='Constant', dist='t')
            result = model.fit(disp='off', show_warning=False)

            std_resid = result.std_resid.dropna()
            jb_stat, jb_p = stats.jarque_bera(std_resid)

            print(f"{name:6s} {std_resid.mean():8.4f} {std_resid.std():8.4f} "
                  f"{stats.skew(std_resid):8.4f} {stats.kurtosis(std_resid):8.4f} "
                  f"{jb_stat:10.1f} {jb_p:8.4f}")
        except Exception as e:
            print(f"{name:6s} FAILED: {e}")

except ImportError:
    print("arch package not available. Skipping GARCH analysis.")
    garch_results = {}

# ─────────────────────────────────────────────────────────
# 9. DeFi-SPECIFIC VOLATILITY REGIMES
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SECTION 9: DeFi-Specific Volatility Regimes")
print("=" * 70)

print("\n--- 9a: Rolling 30-day Realized Vol (annualized) ---")
rv_window = 30
for name in ['UNI', 'AAVE', 'BTC', 'ETH', 'SPY']:
    r = aligned[name]
    rv = r.rolling(rv_window).std() * np.sqrt(252) * 100
    rv = rv.dropna()

    # Regime classification
    low = rv[rv < rv.quantile(0.25)]
    high = rv[rv > rv.quantile(0.75)]

    print(f"\n  {name}:")
    print(f"    Overall: mean={rv.mean():.1f}%, median={rv.median():.1f}%")
    print(f"    Low regime (Q1):  mean={low.mean():.1f}%, count={len(low)}")
    print(f"    High regime (Q4): mean={high.mean():.1f}%, count={len(high)}")
    print(f"    High/Low ratio: {high.mean()/low.mean():.1f}x")

# 9b: DeFi idiosyncratic vol (after removing BTC component)
print("\n--- 9b: DeFi Idiosyncratic Vol (after removing BTC factor) ---")
for name in ['UNI', 'AAVE', 'ETH']:
    y = aligned[name].values
    x = aligned['BTC'].values
    min_len = min(len(y), len(x))
    y, x = y[:min_len], x[:min_len]

    # OLS residuals
    x_const = np.column_stack([np.ones(len(x)), x])
    beta_hat = np.linalg.lstsq(x_const, y, rcond=None)[0]
    resid = y - x_const @ beta_hat

    total_vol = np.std(y) * np.sqrt(252) * 100
    idio_vol = np.std(resid) * np.sqrt(252) * 100
    systematic_pct = (1 - (idio_vol/total_vol)**2) * 100

    print(f"  {name}: total vol={total_vol:.1f}%, idio vol={idio_vol:.1f}%, "
          f"BTC explains={systematic_pct:.1f}%")

# ─────────────────────────────────────────────────────────
# 10. YEAR-BY-YEAR ANALYSIS
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SECTION 10: Year-by-Year Volatility Evolution")
print("=" * 70)

years = sorted(set(aligned['UNI'].index.year))
print(f"\n{'Year':6s}", end="")
for name in ['UNI', 'AAVE', 'BTC', 'ETH', 'SPY']:
    print(f" {name:>8s}", end="")
print("  UNI/BTC  AAVE/BTC")
print("-" * 72)

for year in years:
    print(f"{year:6d}", end="")
    vols = {}
    for name in ['UNI', 'AAVE', 'BTC', 'ETH', 'SPY']:
        r_year = aligned[name][aligned[name].index.year == year]
        if len(r_year) > 20:
            vol = r_year.std() * np.sqrt(252) * 100
            vols[name] = vol
            print(f" {vol:7.1f}%", end="")
        else:
            print(f" {'N/A':>7s} ", end="")

    if 'UNI' in vols and 'BTC' in vols:
        print(f"  {vols['UNI']/vols['BTC']:7.2f}x", end="")
    if 'AAVE' in vols and 'BTC' in vols:
        print(f"  {vols['AAVE']/vols['BTC']:7.2f}x", end="")
    print()

# ─────────────────────────────────────────────────────────
# 11. SUMMARY AND CONCLUSIONS
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SECTION 11: Summary and Conclusions")
print("=" * 70)

conclusions = {
    'experiment': 'K381',
    'title': 'DeFi Governance Token Volatility — UNI and AAVE vs BTC',
    'status': 'PRELIMINARY',
    'data_source': 'yfinance',
    'period': f"{common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')}",
    'n_obs': len(common_idx),
    'assets': list(stats_table.keys()),
    'findings': {},
    'limitations': [
        'Short history (~5 years for DeFi tokens)',
        'Crypto trades 24/7 but analysis aligned to SPY trading days',
        'DeFi tokens have low liquidity compared to BTC/SPY',
        'No on-chain data (TVL, protocol events) included',
        'Survivorship bias: UNI and AAVE are successful protocols',
    ]
}

# Finding 1: Vol hierarchy
print("\n1. VOLATILITY HIERARCHY:")
vol_order = sorted(stats_table.items(), key=lambda x: x[1]['ann_vol'], reverse=True)
for name, s in vol_order:
    print(f"   {name}: {s['ann_vol']:.1f}%")
conclusions['findings']['vol_hierarchy'] = {name: s['ann_vol'] for name, s in vol_order}

# Finding 2: Leverage effect
print("\n2. LEVERAGE EFFECT:")
for name in ['UNI', 'AAVE', 'BTC', 'ETH', 'SPY']:
    le = leverage_results[name]
    print(f"   {name}: corr={le['correlation']:.4f}, effect={le['effect']}")
conclusions['findings']['leverage_effect'] = leverage_results

# Finding 3: BTC beta
print("\n3. BTC EXPOSURE:")
for name in ['UNI', 'AAVE', 'ETH']:
    b = beta_results[name]
    print(f"   {name}: beta={b['beta_btc']:.3f}, R²={b['r_squared']:.3f}, idio vol={b['resid_vol_ann_pct']:.1f}%")
conclusions['findings']['btc_beta'] = beta_results

# Finding 4: GARCH feasibility
print("\n4. GARCH FEASIBILITY:")
for name in ['UNI', 'AAVE', 'BTC', 'ETH', 'SPY']:
    g = garch_results.get(name, {})
    if 'persistence' in g:
        conv = "converged" if g.get('converged', False) else "NOT converged"
        hl = f"HL={g['half_life']:.1f}d" if g.get('half_life') else "HL=inf"
        print(f"   {name}: persist={g['persistence']:.4f}, {hl}, {conv}")
    elif 'error' in g:
        print(f"   {name}: FAILED ({g['error']})")
conclusions['findings']['garch'] = garch_results

# Finding 5: Clustering
print("\n5. VOL CLUSTERING STRENGTH:")
for name in ['UNI', 'AAVE', 'BTC', 'ETH', 'SPY']:
    c = clustering_results[name]
    sig = "SIGNIFICANT" if c['lb_pval'] < 0.05 else "NOT significant"
    print(f"   {name}: ACF(1)={c['acf1']:.4f}, ACF(5)={c['acf5']:.4f}, LB(10): {sig}")
conclusions['findings']['vol_clustering'] = clustering_results

# Overall verdict
print("\n" + "=" * 70)
print("OVERALL VERDICT:")
print("=" * 70)

verdict_lines = []

# Vol comparison
if stats_table['UNI']['ann_vol'] > stats_table['BTC']['ann_vol']:
    v = f"UNI ({stats_table['UNI']['ann_vol']:.0f}%) is MORE volatile than BTC ({stats_table['BTC']['ann_vol']:.0f}%)"
else:
    v = f"UNI ({stats_table['UNI']['ann_vol']:.0f}%) is LESS volatile than BTC ({stats_table['BTC']['ann_vol']:.0f}%)"
verdict_lines.append(v)
print(f"  - {v}")

if stats_table['AAVE']['ann_vol'] > stats_table['BTC']['ann_vol']:
    v = f"AAVE ({stats_table['AAVE']['ann_vol']:.0f}%) is MORE volatile than BTC ({stats_table['BTC']['ann_vol']:.0f}%)"
else:
    v = f"AAVE ({stats_table['AAVE']['ann_vol']:.0f}%) is LESS volatile than BTC ({stats_table['BTC']['ann_vol']:.0f}%)"
verdict_lines.append(v)
print(f"  - {v}")

# Leverage effect
uni_le = leverage_results['UNI']['effect']
aave_le = leverage_results['AAVE']['effect']
spy_le = leverage_results['SPY']['effect']
v = f"Leverage effect: UNI={uni_le}, AAVE={aave_le}, SPY={spy_le}"
verdict_lines.append(v)
print(f"  - {v}")

# GARCH
if garch_results.get('UNI', {}).get('converged', False):
    v = "GARCH converges for UNI — feasible but needs caution"
else:
    v = "GARCH convergence issues for UNI"
verdict_lines.append(v)
print(f"  - {v}")

# BTC dependence
uni_r2 = beta_results['UNI']['r_squared']
v = f"UNI R² to BTC = {uni_r2:.3f} — {'high' if uni_r2 > 0.3 else 'moderate' if uni_r2 > 0.15 else 'low'} BTC dependence"
verdict_lines.append(v)
print(f"  - {v}")

conclusions['verdict'] = verdict_lines

# Save results
results_path = 'experiments/k381_defi_tokens_results.json'
with open(results_path, 'w') as f:
    json.dump(conclusions, f, indent=2, default=str)
print(f"\nResults saved to {results_path}")

print("\n" + "=" * 70)
print("K381 COMPLETE")
print("=" * 70)
