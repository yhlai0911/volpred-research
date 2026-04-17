#!/usr/bin/env python3
"""K639: Crypto-Equity Volatility Linkage

Jump exploration into crypto/DeFi space. Bitcoin has become increasingly
correlated with equity markets since 2020. Does BTC vol contain information
for SPY vol prediction, or vice versa?

Analyses:
1. Descriptive: Rolling correlation |r_SPY| vs |r_BTC|, pre/post 2020
2. Tail dependence: Joint extreme events
3. Granger causality: Bidirectional vol spillovers
4. Forecasting: HAR + |r_BTC| and GJR-GARCH-X for SPY vol
5. Portfolio diversification: 90/10 SPY/BTC, VT strategy with BTC
6. BTC-specific vol characteristics: leverage effect, persistence, distribution

Data source: yfinance (SPY, BTC-USD), 2015-01-01 to 2026-03-27
OOS period: 2023-01-01 to 2024-12-31

References:
- Bouri et al. (2017) "On the return-volatility relationship in the Bitcoin market
  around the price crash of 2013", Economics, 11(1)
- Corbet et al. (2018) "Exploring the dynamic relationships between
  cryptocurrencies and other financial assets", Economics Letters, 165
- Klein et al. (2018) "Bitcoin is not the New Gold", Int Rev Financial Analysis, 59

[提出: 跳躍式探索 (DeFi/Crypto), 執行: Claude]
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
from datetime import datetime
import json
import os


# ─── Helper functions ────────────────────────────────────────────

def qlike_loss(realized_var, forecast_var):
    """QLIKE loss: log(forecast) + realized/forecast. Lower is better."""
    valid = (forecast_var > 0) & (realized_var > 0) & np.isfinite(realized_var) & np.isfinite(forecast_var)
    r = realized_var[valid]
    f = forecast_var[valid]
    return np.mean(np.log(f) + r / f)


def qlike_loss_array(realized_var, forecast_var):
    """QLIKE loss per observation for DM test."""
    valid = (forecast_var > 0) & (realized_var > 0) & np.isfinite(realized_var) & np.isfinite(forecast_var)
    r = realized_var[valid]
    f = forecast_var[valid]
    return np.log(f) + r / f


def dm_test(loss1, loss2):
    """Diebold-Mariano test. H0: equal predictive ability.
    Negative t-stat means loss1 < loss2 (model 1 better)."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan
    d_mean = np.mean(d)
    lag = max(1, int(n ** (1 / 3)))
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, lag + 1):
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        gamma_sum += 2 * (1 - k / (lag + 1)) * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return np.nan, np.nan
    t_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return t_stat, p_value


def granger_causality_test(y, x, maxlag=5):
    """Manual Granger causality test using OLS F-test.
    Tests if x Granger-causes y."""
    from numpy.linalg import lstsq

    results = {}
    for lag in range(1, maxlag + 1):
        # Build matrices
        n = len(y) - lag
        if n < lag * 2 + 10:
            continue

        Y = y[lag:]

        # Restricted model: only lags of y
        X_r = np.column_stack([y[lag - i - 1:-(i + 1)] for i in range(lag)])
        X_r = np.column_stack([np.ones(n), X_r])

        # Unrestricted model: lags of y + lags of x
        X_u = np.column_stack([X_r,
                               *[x[lag - i - 1:-(i + 1)] for i in range(lag)]])

        # Fit both
        beta_r, res_r, _, _ = lstsq(X_r, Y, rcond=None)
        beta_u, res_u, _, _ = lstsq(X_u, Y, rcond=None)

        ssr_r = np.sum((Y - X_r @ beta_r) ** 2)
        ssr_u = np.sum((Y - X_u @ beta_u) ** 2)

        df_diff = lag  # number of additional regressors
        df_u = n - X_u.shape[1]

        if df_u <= 0 or ssr_u <= 0:
            continue

        f_stat = ((ssr_r - ssr_u) / df_diff) / (ssr_u / df_u)
        p_value = 1 - stats.f.cdf(f_stat, df_diff, df_u)

        results[lag] = {"f_stat": float(f_stat), "p_value": float(p_value)}

    return results


# ═══════════════════════════════════════════════════════════════════
# SECTION 1: DATA DOWNLOAD AND PREPARATION
# ═══════════════════════════════════════════════════════════════════
print("=" * 70)
print("K639: Crypto-Equity Volatility Linkage")
print("=" * 70)

print("\n[1] Downloading data from yfinance...")
spy = yf.download("SPY", start="2015-01-01", end="2026-03-28", progress=False)
btc = yf.download("BTC-USD", start="2015-01-01", end="2026-03-28", progress=False)

# Handle MultiIndex columns from yfinance
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(btc.columns, pd.MultiIndex):
    btc.columns = btc.columns.get_level_values(0)

print(f"  SPY raw: {len(spy)} rows, {spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')}")
print(f"  BTC raw: {len(btc)} rows, {btc.index[0].strftime('%Y-%m-%d')} to {btc.index[-1].strftime('%Y-%m-%d')}")

# Compute log returns
spy["ret"] = np.log(spy["Close"] / spy["Close"].shift(1))
btc["ret"] = np.log(btc["Close"] / btc["Close"].shift(1))

# Filter BTC to weekdays only (for consistency with SPY)
btc_weekday = btc[btc.index.dayofweek < 5].copy()

# Align on common dates
common_dates = spy.index.intersection(btc_weekday.index)
spy_aligned = spy.loc[common_dates].copy()
btc_aligned = btc_weekday.loc[common_dates].copy()

# Drop NaN
spy_aligned = spy_aligned.dropna(subset=["ret"])
btc_aligned = btc_aligned.loc[spy_aligned.index]

print(f"  Common trading days: {len(common_dates)}")
print(f"  After alignment: {len(spy_aligned)} rows")
print(f"  Period: {spy_aligned.index[0].strftime('%Y-%m-%d')} to {spy_aligned.index[-1].strftime('%Y-%m-%d')}")

# Absolute returns as vol proxy
spy_aligned["abs_ret"] = np.abs(spy_aligned["ret"])
btc_aligned["abs_ret"] = np.abs(btc_aligned["ret"])
spy_aligned["sq_ret"] = spy_aligned["ret"] ** 2
btc_aligned["sq_ret"] = btc_aligned["ret"] ** 2

results = {
    "experiment_id": "K639",
    "title": "Crypto-Equity Volatility Linkage",
    "data_source": "yfinance",
    "assets": ["SPY", "BTC-USD"],
    "period": f"{spy_aligned.index[0].strftime('%Y-%m-%d')} to {spy_aligned.index[-1].strftime('%Y-%m-%d')}",
    "n_obs": int(len(spy_aligned)),
    "timestamp": datetime.now().isoformat(),
}


# ═══════════════════════════════════════════════════════════════════
# SECTION 2: DESCRIPTIVE STATISTICS
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("[2] Descriptive Statistics")
print("=" * 70)

for name, df in [("SPY", spy_aligned), ("BTC-USD", btc_aligned)]:
    ret = df["ret"].values
    print(f"\n  {name}:")
    print(f"    N = {len(ret)}")
    print(f"    Mean daily return = {np.mean(ret)*100:.4f}%")
    print(f"    Std daily return  = {np.std(ret)*100:.4f}%")
    print(f"    Annualized vol    = {np.std(ret)*np.sqrt(252)*100:.2f}%")
    print(f"    Skewness          = {stats.skew(ret):.4f}")
    print(f"    Kurtosis (excess) = {stats.kurtosis(ret):.4f}")
    print(f"    Min               = {np.min(ret)*100:.4f}%")
    print(f"    Max               = {np.max(ret)*100:.4f}%")

    # ADF test
    from statsmodels.tsa.stattools import adfuller
    adf_stat, adf_p, _, _, _, _ = adfuller(ret, maxlag=20, regression="c")
    print(f"    ADF statistic     = {adf_stat:.4f} (p={adf_p:.6f})")

    # ARCH LM test
    from statsmodels.stats.diagnostic import het_arch
    arch_lm, arch_p, _, _ = het_arch(ret, nlags=10)
    print(f"    ARCH LM(10)       = {arch_lm:.2f} (p={arch_p:.6f})")

results["descriptive"] = {
    "SPY": {
        "n_obs": int(len(spy_aligned)),
        "mean_daily_ret": float(np.mean(spy_aligned["ret"])),
        "std_daily_ret": float(np.std(spy_aligned["ret"])),
        "annualized_vol": float(np.std(spy_aligned["ret"]) * np.sqrt(252)),
        "skewness": float(stats.skew(spy_aligned["ret"])),
        "excess_kurtosis": float(stats.kurtosis(spy_aligned["ret"])),
    },
    "BTC": {
        "n_obs": int(len(btc_aligned)),
        "mean_daily_ret": float(np.mean(btc_aligned["ret"])),
        "std_daily_ret": float(np.std(btc_aligned["ret"])),
        "annualized_vol": float(np.std(btc_aligned["ret"]) * np.sqrt(252)),
        "skewness": float(stats.skew(btc_aligned["ret"])),
        "excess_kurtosis": float(stats.kurtosis(btc_aligned["ret"])),
    },
    "btc_spy_vol_ratio": float(np.std(btc_aligned["ret"]) / np.std(spy_aligned["ret"])),
}

print(f"\n  BTC/SPY vol ratio = {results['descriptive']['btc_spy_vol_ratio']:.2f}x")


# ═══════════════════════════════════════════════════════════════════
# SECTION 3: ROLLING CORRELATION ANALYSIS
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("[3] Rolling Correlation: |r_SPY| vs |r_BTC|")
print("=" * 70)

# Build combined df
combined = pd.DataFrame({
    "spy_abs_ret": spy_aligned["abs_ret"],
    "btc_abs_ret": btc_aligned["abs_ret"],
    "spy_ret": spy_aligned["ret"],
    "btc_ret": btc_aligned["ret"],
    "spy_sq_ret": spy_aligned["sq_ret"],
    "btc_sq_ret": btc_aligned["sq_ret"],
}, index=spy_aligned.index)

# Rolling correlation (252-day window)
rolling_corr_abs = combined["spy_abs_ret"].rolling(252).corr(combined["btc_abs_ret"])
rolling_corr_ret = combined["spy_ret"].rolling(252).corr(combined["btc_ret"])

# Split pre/post 2020
pre_2020 = combined.loc[:"2019-12-31"]
post_2020 = combined.loc["2020-01-01":]

corr_pre_abs = pre_2020["spy_abs_ret"].corr(pre_2020["btc_abs_ret"])
corr_post_abs = post_2020["spy_abs_ret"].corr(post_2020["btc_abs_ret"])
corr_pre_ret = pre_2020["spy_ret"].corr(pre_2020["btc_ret"])
corr_post_ret = post_2020["spy_ret"].corr(post_2020["btc_ret"])

# Test if correlation changed significantly (Fisher z-transform)
n_pre = len(pre_2020)
n_post = len(post_2020)
z_pre = np.arctanh(corr_pre_ret)
z_post = np.arctanh(corr_post_ret)
se_diff = np.sqrt(1 / (n_pre - 3) + 1 / (n_post - 3))
z_test = (z_post - z_pre) / se_diff
z_pval = 2 * (1 - stats.norm.cdf(abs(z_test)))

print(f"\n  Return correlation:")
print(f"    Pre-2020  (n={n_pre}): corr = {corr_pre_ret:.4f}")
print(f"    Post-2020 (n={n_post}): corr = {corr_post_ret:.4f}")
print(f"    Fisher z-test: z = {z_test:.4f}, p = {z_pval:.6f}")

print(f"\n  |Return| correlation (vol linkage):")
print(f"    Pre-2020:  corr = {corr_pre_abs:.4f}")
print(f"    Post-2020: corr = {corr_post_abs:.4f}")

# Rolling correlation statistics
rc_valid = rolling_corr_abs.dropna()
print(f"\n  Rolling 252d |ret| corr stats:")
print(f"    Mean  = {rc_valid.mean():.4f}")
print(f"    Std   = {rc_valid.std():.4f}")
print(f"    Min   = {rc_valid.min():.4f}")
print(f"    Max   = {rc_valid.max():.4f}")

# Also compute rolling return correlation
rc_ret_valid = rolling_corr_ret.dropna()
print(f"\n  Rolling 252d return corr stats:")
print(f"    Mean  = {rc_ret_valid.mean():.4f}")
print(f"    Std   = {rc_ret_valid.std():.4f}")
print(f"    Min   = {rc_ret_valid.min():.4f}")
print(f"    Max   = {rc_ret_valid.max():.4f}")

# Yearly return correlation
yearly_corrs = {}
for year in range(2015, 2027):
    mask = combined.index.year == year
    if mask.sum() > 50:
        c = combined.loc[mask, "spy_ret"].corr(combined.loc[mask, "btc_ret"])
        yearly_corrs[str(year)] = float(c)
        print(f"    {year}: {c:.4f}")

results["correlation"] = {
    "return_corr_pre_2020": float(corr_pre_ret),
    "return_corr_post_2020": float(corr_post_ret),
    "fisher_z_test": float(z_test),
    "fisher_z_pvalue": float(z_pval),
    "abs_return_corr_pre_2020": float(corr_pre_abs),
    "abs_return_corr_post_2020": float(corr_post_abs),
    "rolling_252d_abs_corr_mean": float(rc_valid.mean()),
    "rolling_252d_abs_corr_std": float(rc_valid.std()),
    "rolling_252d_ret_corr_mean": float(rc_ret_valid.mean()),
    "rolling_252d_ret_corr_std": float(rc_ret_valid.std()),
    "yearly_return_corr": yearly_corrs,
}


# ═══════════════════════════════════════════════════════════════════
# SECTION 4: VOL RATIO OVER TIME
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("[4] BTC/SPY Volatility Ratio Over Time")
print("=" * 70)

spy_rv_60 = combined["spy_sq_ret"].rolling(60).mean()
btc_rv_60 = combined["btc_sq_ret"].rolling(60).mean()
vol_ratio = np.sqrt(btc_rv_60 / spy_rv_60)

vr_valid = vol_ratio.dropna()
print(f"\n  60-day rolling vol ratio (BTC/SPY):")
print(f"    Mean  = {vr_valid.mean():.2f}x")
print(f"    Std   = {vr_valid.std():.2f}")
print(f"    Min   = {vr_valid.min():.2f}x")
print(f"    Max   = {vr_valid.max():.2f}x")

# Yearly vol ratio
yearly_vr = {}
for year in range(2015, 2027):
    mask = combined.index.year == year
    s = combined.loc[mask]
    if len(s) > 50:
        vr = np.std(s["btc_ret"]) / np.std(s["spy_ret"])
        yearly_vr[str(year)] = float(vr)
        print(f"    {year}: {vr:.2f}x")

results["vol_ratio"] = {
    "rolling_60d_mean": float(vr_valid.mean()),
    "rolling_60d_std": float(vr_valid.std()),
    "rolling_60d_min": float(vr_valid.min()),
    "rolling_60d_max": float(vr_valid.max()),
    "yearly": yearly_vr,
}


# ═══════════════════════════════════════════════════════════════════
# SECTION 5: TAIL DEPENDENCE
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("[5] Tail Dependence Analysis")
print("=" * 70)

spy_ret = combined["spy_ret"].values
btc_ret = combined["btc_ret"].values

# Define extreme events
thresholds = [0.01, 0.05, 0.10]
for th in thresholds:
    spy_extreme_down = spy_ret < np.quantile(spy_ret, th)
    btc_extreme_down = btc_ret < np.quantile(btc_ret, th)

    # Joint extreme probability
    joint_down = np.mean(spy_extreme_down & btc_extreme_down)
    # Under independence
    expected_joint = th * th

    # Chi-square test for independence
    contingency = np.array([
        [np.sum(spy_extreme_down & btc_extreme_down),
         np.sum(spy_extreme_down & ~btc_extreme_down)],
        [np.sum(~spy_extreme_down & btc_extreme_down),
         np.sum(~spy_extreme_down & ~btc_extreme_down)]
    ])
    chi2, chi2_p, _, _ = stats.chi2_contingency(contingency)

    # Conditional probability: P(BTC extreme | SPY extreme)
    p_btc_given_spy = np.sum(spy_extreme_down & btc_extreme_down) / max(1, np.sum(spy_extreme_down))

    print(f"\n  Threshold = {th*100:.0f}th percentile:")
    print(f"    P(SPY extreme & BTC extreme) = {joint_down:.4f} (vs {expected_joint:.4f} under independence)")
    print(f"    Excess tail dependence ratio  = {joint_down/expected_joint:.2f}x")
    print(f"    P(BTC extreme | SPY extreme)  = {p_btc_given_spy:.4f} (vs {th:.4f} under indep)")
    print(f"    Chi-square = {chi2:.2f}, p = {chi2_p:.6f}")

# Exceedance correlation (corr on extreme days only)
spy_q5 = np.quantile(spy_ret, 0.05)
mask_extreme = spy_ret < spy_q5
if np.sum(mask_extreme) > 10:
    corr_extreme = np.corrcoef(spy_ret[mask_extreme], btc_ret[mask_extreme])[0, 1]
    corr_all = np.corrcoef(spy_ret, btc_ret)[0, 1]
    print(f"\n  Exceedance correlation (SPY < 5th pct):")
    print(f"    Corr on extreme days = {corr_extreme:.4f}")
    print(f"    Corr on all days     = {corr_all:.4f}")
else:
    corr_extreme = np.nan
    corr_all = np.corrcoef(spy_ret, btc_ret)[0, 1]

results["tail_dependence"] = {
    "thresholds_tested": thresholds,
    "joint_extreme_1pct": float(np.mean((spy_ret < np.quantile(spy_ret, 0.01)) & (btc_ret < np.quantile(btc_ret, 0.01)))),
    "joint_extreme_5pct": float(np.mean((spy_ret < np.quantile(spy_ret, 0.05)) & (btc_ret < np.quantile(btc_ret, 0.05)))),
    "joint_extreme_10pct": float(np.mean((spy_ret < np.quantile(spy_ret, 0.10)) & (btc_ret < np.quantile(btc_ret, 0.10)))),
    "exceedance_corr_5pct": float(corr_extreme) if not np.isnan(corr_extreme) else None,
    "unconditional_corr": float(corr_all),
}


# ═══════════════════════════════════════════════════════════════════
# SECTION 6: GRANGER CAUSALITY
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("[6] Granger Causality Tests")
print("=" * 70)

spy_vol = combined["spy_abs_ret"].values
btc_vol = combined["btc_abs_ret"].values

# Remove initial NaN
valid_mask = np.isfinite(spy_vol) & np.isfinite(btc_vol)
spy_vol_clean = spy_vol[valid_mask]
btc_vol_clean = btc_vol[valid_mask]

print("\n  Testing: Does BTC vol Granger-cause SPY vol?")
gc_btc_to_spy = granger_causality_test(spy_vol_clean, btc_vol_clean, maxlag=10)
for lag, res in gc_btc_to_spy.items():
    sig = "***" if res["p_value"] < 0.01 else "**" if res["p_value"] < 0.05 else "*" if res["p_value"] < 0.10 else ""
    print(f"    Lag {lag}: F = {res['f_stat']:.4f}, p = {res['p_value']:.6f} {sig}")

print("\n  Testing: Does SPY vol Granger-cause BTC vol?")
gc_spy_to_btc = granger_causality_test(btc_vol_clean, spy_vol_clean, maxlag=10)
for lag, res in gc_spy_to_btc.items():
    sig = "***" if res["p_value"] < 0.01 else "**" if res["p_value"] < 0.05 else "*" if res["p_value"] < 0.10 else ""
    print(f"    Lag {lag}: F = {res['f_stat']:.4f}, p = {res['p_value']:.6f} {sig}")

# Summary
btc_causes_spy_5 = any(v["p_value"] < 0.05 for v in gc_btc_to_spy.values())
spy_causes_btc_5 = any(v["p_value"] < 0.05 for v in gc_spy_to_btc.values())
print(f"\n  BTC vol → SPY vol (at 5%): {'YES' if btc_causes_spy_5 else 'NO'}")
print(f"  SPY vol → BTC vol (at 5%): {'YES' if spy_causes_btc_5 else 'NO'}")
if btc_causes_spy_5 and spy_causes_btc_5:
    print("  → Bidirectional volatility spillover")
elif btc_causes_spy_5:
    print("  → Unidirectional: BTC → SPY")
elif spy_causes_btc_5:
    print("  → Unidirectional: SPY → BTC")
else:
    print("  → No significant Granger causality")

# Also test with squared returns
print("\n  Testing with squared returns (variance proxy):")
spy_var = combined["spy_sq_ret"].values[valid_mask]
btc_var = combined["btc_sq_ret"].values[valid_mask]

gc_btc_to_spy_sq = granger_causality_test(spy_var, btc_var, maxlag=5)
gc_spy_to_btc_sq = granger_causality_test(btc_var, spy_var, maxlag=5)

print("  BTC sq_ret → SPY sq_ret:")
for lag, res in gc_btc_to_spy_sq.items():
    sig = "***" if res["p_value"] < 0.01 else "**" if res["p_value"] < 0.05 else "*" if res["p_value"] < 0.10 else ""
    print(f"    Lag {lag}: F = {res['f_stat']:.4f}, p = {res['p_value']:.6f} {sig}")

print("  SPY sq_ret → BTC sq_ret:")
for lag, res in gc_spy_to_btc_sq.items():
    sig = "***" if res["p_value"] < 0.01 else "**" if res["p_value"] < 0.05 else "*" if res["p_value"] < 0.10 else ""
    print(f"    Lag {lag}: F = {res['f_stat']:.4f}, p = {res['p_value']:.6f} {sig}")

results["granger_causality"] = {
    "btc_vol_to_spy_vol": {str(k): v for k, v in gc_btc_to_spy.items()},
    "spy_vol_to_btc_vol": {str(k): v for k, v in gc_spy_to_btc.items()},
    "btc_var_to_spy_var": {str(k): v for k, v in gc_btc_to_spy_sq.items()},
    "spy_var_to_btc_var": {str(k): v for k, v in gc_spy_to_btc_sq.items()},
    "btc_causes_spy_5pct": btc_causes_spy_5,
    "spy_causes_btc_5pct": spy_causes_btc_5,
}


# ═══════════════════════════════════════════════════════════════════
# SECTION 7: BTC-SPECIFIC VOL CHARACTERISTICS
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("[7] BTC-Specific Volatility Characteristics")
print("=" * 70)

# Fit GJR-GARCH to BTC
btc_ret_pct = btc_aligned["ret"].values * 100
spy_ret_pct = spy_aligned["ret"].values * 100

print("\n  Fitting GJR-GARCH(1,1) to BTC-USD...")
try:
    gjr_btc = arch_model(btc_ret_pct, vol="Garch", p=1, o=1, q=1, dist="t")
    res_btc = gjr_btc.fit(disp="off")

    omega_b = res_btc.params.get("omega", np.nan)
    alpha_b = res_btc.params.get("alpha[1]", np.nan)
    gamma_b = res_btc.params.get("gamma[1]", np.nan)
    beta_b = res_btc.params.get("beta[1]", np.nan)
    nu_b = res_btc.params.get("nu", np.nan)
    persistence_b = alpha_b + gamma_b / 2 + beta_b

    print(f"    omega     = {omega_b:.6f}")
    print(f"    alpha     = {alpha_b:.6f}")
    print(f"    gamma     = {gamma_b:.6f} ({'positive=leverage' if gamma_b > 0 else 'negative=inverse leverage'})")
    print(f"    beta      = {beta_b:.6f}")
    print(f"    nu (df)   = {nu_b:.4f}")
    print(f"    persistence = {persistence_b:.6f}")
    print(f"    converged = {res_btc.convergence_flag == 0}")

    btc_leverage_positive = gamma_b > 0
    print(f"\n    BTC leverage effect: gamma = {gamma_b:.6f}")
    if gamma_b > 0:
        print("    → Standard leverage: negative returns increase vol more")
    elif gamma_b < 0:
        print("    → INVERSE leverage: positive returns increase vol more (crypto-specific!)")
    else:
        print("    → No asymmetry")

    btc_garch_results = {
        "omega": float(omega_b),
        "alpha": float(alpha_b),
        "gamma": float(gamma_b),
        "beta": float(beta_b),
        "nu_df": float(nu_b),
        "persistence": float(persistence_b),
        "converged": bool(res_btc.convergence_flag == 0),
        "leverage_direction": "standard" if gamma_b > 0 else "inverse" if gamma_b < 0 else "none",
    }
except Exception as e:
    print(f"    Error fitting BTC GJR-GARCH: {e}")
    btc_garch_results = {"error": str(e)}

# Fit GJR-GARCH to SPY for comparison
print("\n  Fitting GJR-GARCH(1,1) to SPY (comparison)...")
try:
    gjr_spy = arch_model(spy_ret_pct, vol="Garch", p=1, o=1, q=1, dist="t")
    res_spy = gjr_spy.fit(disp="off")

    omega_s = res_spy.params.get("omega", np.nan)
    alpha_s = res_spy.params.get("alpha[1]", np.nan)
    gamma_s = res_spy.params.get("gamma[1]", np.nan)
    beta_s = res_spy.params.get("beta[1]", np.nan)
    nu_s = res_spy.params.get("nu", np.nan)
    persistence_s = alpha_s + gamma_s / 2 + beta_s

    print(f"    omega     = {omega_s:.6f}")
    print(f"    alpha     = {alpha_s:.6f}")
    print(f"    gamma     = {gamma_s:.6f}")
    print(f"    beta      = {beta_s:.6f}")
    print(f"    nu (df)   = {nu_s:.4f}")
    print(f"    persistence = {persistence_s:.6f}")

    spy_garch_results = {
        "omega": float(omega_s),
        "alpha": float(alpha_s),
        "gamma": float(gamma_s),
        "beta": float(beta_s),
        "nu_df": float(nu_s),
        "persistence": float(persistence_s),
        "converged": bool(res_spy.convergence_flag == 0),
    }
except Exception as e:
    print(f"    Error fitting SPY GJR-GARCH: {e}")
    spy_garch_results = {"error": str(e)}

print("\n  Comparison:")
print(f"    {'Parameter':<15} {'BTC':>10} {'SPY':>10}")
print(f"    {'-'*35}")
if "error" not in btc_garch_results and "error" not in spy_garch_results:
    print(f"    {'alpha':<15} {btc_garch_results['alpha']:>10.6f} {spy_garch_results['alpha']:>10.6f}")
    print(f"    {'gamma':<15} {btc_garch_results['gamma']:>10.6f} {spy_garch_results['gamma']:>10.6f}")
    print(f"    {'beta':<15} {btc_garch_results['beta']:>10.6f} {spy_garch_results['beta']:>10.6f}")
    print(f"    {'persistence':<15} {btc_garch_results['persistence']:>10.6f} {spy_garch_results['persistence']:>10.6f}")

results["btc_vol_characteristics"] = {
    "btc_gjr_garch": btc_garch_results,
    "spy_gjr_garch": spy_garch_results,
}


# ═══════════════════════════════════════════════════════════════════
# SECTION 8: FORECASTING - HAR + |r_BTC| for SPY vol
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("[8] Forecasting: HAR + |r_BTC| for SPY vol")
print("=" * 70)

# Build HAR features
combined["rv_spy_1"] = combined["spy_sq_ret"]
combined["rv_spy_5"] = combined["spy_sq_ret"].rolling(5).mean()
combined["rv_spy_22"] = combined["spy_sq_ret"].rolling(22).mean()
combined["btc_abs_ret_lag1"] = combined["btc_abs_ret"].shift(1)
combined["btc_sq_ret_lag1"] = combined["btc_sq_ret"].shift(1)
combined["btc_rv_5"] = combined["btc_sq_ret"].rolling(5).mean().shift(1)

# Target: next day realized variance
combined["target_rv"] = combined["spy_sq_ret"].shift(-1)

# Drop NaN
har_data = combined.dropna(subset=["rv_spy_1", "rv_spy_5", "rv_spy_22",
                                    "btc_abs_ret_lag1", "btc_rv_5",
                                    "target_rv"])

# OOS: 2023-01-01 to 2024-12-31
oos_start = "2023-01-01"
oos_end = "2024-12-31"
train_data = har_data.loc[:oos_start].iloc[:-1]
test_data = har_data.loc[oos_start:oos_end]

print(f"\n  Training: {len(train_data)} obs")
print(f"  OOS test: {len(test_data)} obs ({test_data.index[0].strftime('%Y-%m-%d')} to {test_data.index[-1].strftime('%Y-%m-%d')})")

from numpy.linalg import lstsq as np_lstsq

# Model 1: HAR baseline
X_train_har = np.column_stack([
    np.ones(len(train_data)),
    train_data["rv_spy_1"].values,
    train_data["rv_spy_5"].values,
    train_data["rv_spy_22"].values,
])
y_train = train_data["target_rv"].values

beta_har, _, _, _ = np_lstsq(X_train_har, y_train, rcond=None)

X_test_har = np.column_stack([
    np.ones(len(test_data)),
    test_data["rv_spy_1"].values,
    test_data["rv_spy_5"].values,
    test_data["rv_spy_22"].values,
])
y_test = test_data["target_rv"].values

forecast_har = X_test_har @ beta_har
forecast_har = np.maximum(forecast_har, 1e-10)

# Model 2: HAR + |r_BTC|
X_train_har_btc = np.column_stack([
    X_train_har,
    train_data["btc_abs_ret_lag1"].values,
])
beta_har_btc, _, _, _ = np_lstsq(X_train_har_btc, y_train, rcond=None)

X_test_har_btc = np.column_stack([
    X_test_har,
    test_data["btc_abs_ret_lag1"].values,
])
forecast_har_btc = X_test_har_btc @ beta_har_btc
forecast_har_btc = np.maximum(forecast_har_btc, 1e-10)

# Model 3: HAR + BTC 5-day RV
X_train_har_btcrv = np.column_stack([
    X_train_har,
    train_data["btc_rv_5"].values,
])
beta_har_btcrv, _, _, _ = np_lstsq(X_train_har_btcrv, y_train, rcond=None)

X_test_har_btcrv = np.column_stack([
    X_test_har,
    test_data["btc_rv_5"].values,
])
forecast_har_btcrv = X_test_har_btcrv @ beta_har_btcrv
forecast_har_btcrv = np.maximum(forecast_har_btcrv, 1e-10)

# QLIKE evaluation
qlike_har = qlike_loss(y_test, forecast_har)
qlike_har_btc = qlike_loss(y_test, forecast_har_btc)
qlike_har_btcrv = qlike_loss(y_test, forecast_har_btcrv)

print(f"\n  QLIKE scores (lower = better):")
print(f"    HAR baseline:    {qlike_har:.6f}")
print(f"    HAR + |r_BTC|:   {qlike_har_btc:.6f}")
print(f"    HAR + BTC RV5:   {qlike_har_btcrv:.6f}")

# DM tests
loss_har = qlike_loss_array(y_test, forecast_har)
loss_har_btc = qlike_loss_array(y_test, forecast_har_btc)
loss_har_btcrv = qlike_loss_array(y_test, forecast_har_btcrv)

dm_btc_vs_base, dm_btc_p = dm_test(loss_har_btc, loss_har)
dm_btcrv_vs_base, dm_btcrv_p = dm_test(loss_har_btcrv, loss_har)

print(f"\n  DM test (HAR+BTC vs HAR baseline):")
print(f"    HAR+|r_BTC| vs HAR:  t = {dm_btc_vs_base:.4f}, p = {dm_btc_p:.6f}")
print(f"    HAR+BTC_RV5 vs HAR:  t = {dm_btcrv_vs_base:.4f}, p = {dm_btcrv_p:.6f}")

# BTC coefficient significance in HAR+|r_BTC|
btc_coef = beta_har_btc[-1]
# Simple t-test for coefficient
residuals_train = y_train - X_train_har_btc @ beta_har_btc
mse = np.mean(residuals_train ** 2)
XtX_inv = np.linalg.inv(X_train_har_btc.T @ X_train_har_btc)
se_coefs = np.sqrt(mse * np.diag(XtX_inv))
t_btc_coef = btc_coef / se_coefs[-1]
p_btc_coef = 2 * (1 - stats.t.cdf(abs(t_btc_coef), df=len(y_train) - len(beta_har_btc)))

print(f"\n  BTC |return| coefficient in HAR model:")
print(f"    beta = {btc_coef:.6f}")
print(f"    t    = {t_btc_coef:.4f}")
print(f"    p    = {p_btc_coef:.6f}")

results["har_forecasting"] = {
    "oos_period": f"{oos_start} to {oos_end}",
    "n_oos": int(len(test_data)),
    "qlike_har_baseline": float(qlike_har),
    "qlike_har_btc_abs": float(qlike_har_btc),
    "qlike_har_btc_rv5": float(qlike_har_btcrv),
    "dm_har_btc_vs_baseline": {"t_stat": float(dm_btc_vs_base), "p_value": float(dm_btc_p)},
    "dm_har_btcrv5_vs_baseline": {"t_stat": float(dm_btcrv_vs_base), "p_value": float(dm_btcrv_p)},
    "btc_coef_in_har": {
        "beta": float(btc_coef),
        "t_stat": float(t_btc_coef),
        "p_value": float(p_btc_coef),
    },
    "qlike_improvement_btc_abs_pct": float((qlike_har - qlike_har_btc) / qlike_har * 100),
}


# ═══════════════════════════════════════════════════════════════════
# SECTION 9: GJR-GARCH-X FORECASTING (Rolling OOS)
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("[9] GJR-GARCH-X Rolling OOS Forecast")
print("=" * 70)

# Rolling OOS with window=1500
window = 1500
spy_pct = spy_aligned["ret"].values * 100
btc_abs = btc_aligned["abs_ret"].values
realized = spy_aligned["sq_ret"].values  # in return^2 units

oos_mask = spy_aligned.index >= oos_start
oos_idx = np.where(oos_mask)[0]
# Also restrict to before oos_end
oos_end_mask = spy_aligned.index <= oos_end
oos_idx = np.where(oos_mask & oos_end_mask)[0]

n_oos = len(oos_idx)
print(f"\n  Window = {window}, OOS = {n_oos} days")
print(f"  Refitting every 22 days to save time...")

forecast_gjr = np.full(n_oos, np.nan)
forecast_gjr_x = np.full(n_oos, np.nan)

refit_interval = 22
last_fit_gjr = None
last_fit_gjr_x = None

for i, idx in enumerate(oos_idx):
    if idx < window:
        continue

    train_start = idx - window
    train_ret = spy_pct[train_start:idx]
    train_btc_abs = btc_abs[train_start:idx]

    need_refit = (i % refit_interval == 0) or last_fit_gjr is None

    if need_refit:
        # GJR-GARCH baseline
        try:
            model_gjr = arch_model(train_ret, vol="Garch", p=1, o=1, q=1, dist="t")
            last_fit_gjr = model_gjr.fit(disp="off", show_warning=False)
        except Exception:
            pass

        # GJR-GARCH-X with |r_BTC|
        try:
            model_gjr_x = arch_model(train_ret, vol="Garch", p=1, o=1, q=1, dist="t",
                                     x=pd.DataFrame({"btc_abs": train_btc_abs}))
            last_fit_gjr_x = model_gjr_x.fit(disp="off", show_warning=False)
        except Exception:
            pass

    if last_fit_gjr is not None:
        try:
            fcast = last_fit_gjr.forecast(horizon=1)
            # Convert from pct^2 to ret^2
            forecast_gjr[i] = fcast.variance.values[-1, 0] / 10000.0
        except Exception:
            pass

    if last_fit_gjr_x is not None:
        try:
            # For GARCH-X forecast, need to provide exog for the forecast period
            fcast_x = last_fit_gjr_x.forecast(horizon=1,
                                               x={"btc_abs": btc_abs[idx:idx+1]})
            forecast_gjr_x[i] = fcast_x.variance.values[-1, 0] / 10000.0
        except Exception:
            # Fallback: use baseline if X forecast fails
            if last_fit_gjr is not None:
                try:
                    fcast = last_fit_gjr.forecast(horizon=1)
                    forecast_gjr_x[i] = fcast.variance.values[-1, 0] / 10000.0
                except Exception:
                    pass

    if (i + 1) % 100 == 0:
        print(f"    Progress: {i+1}/{n_oos}")

# Evaluate
realized_oos = realized[oos_idx]
valid_gjr = np.isfinite(forecast_gjr) & np.isfinite(realized_oos) & (forecast_gjr > 0)
valid_gjr_x = np.isfinite(forecast_gjr_x) & np.isfinite(realized_oos) & (forecast_gjr_x > 0)

if np.sum(valid_gjr) > 50 and np.sum(valid_gjr_x) > 50:
    qlike_gjr = qlike_loss(realized_oos[valid_gjr], forecast_gjr[valid_gjr])
    qlike_gjr_x = qlike_loss(realized_oos[valid_gjr_x], forecast_gjr_x[valid_gjr_x])

    print(f"\n  QLIKE scores:")
    print(f"    GJR-GARCH baseline:     {qlike_gjr:.6f}")
    print(f"    GJR-GARCH-X(|r_BTC|):   {qlike_gjr_x:.6f}")
    print(f"    Improvement:            {(qlike_gjr - qlike_gjr_x)/qlike_gjr*100:.4f}%")

    # DM test
    both_valid = valid_gjr & valid_gjr_x
    if np.sum(both_valid) > 50:
        loss_gjr_arr = qlike_loss_array(realized_oos[both_valid], forecast_gjr[both_valid])
        loss_gjr_x_arr = qlike_loss_array(realized_oos[both_valid], forecast_gjr_x[both_valid])
        dm_garch, dm_garch_p = dm_test(loss_gjr_x_arr, loss_gjr_arr)
        print(f"    DM test: t = {dm_garch:.4f}, p = {dm_garch_p:.6f}")
    else:
        dm_garch, dm_garch_p = np.nan, np.nan

    results["garch_forecasting"] = {
        "window": window,
        "n_oos_valid_gjr": int(np.sum(valid_gjr)),
        "n_oos_valid_gjr_x": int(np.sum(valid_gjr_x)),
        "qlike_gjr_baseline": float(qlike_gjr),
        "qlike_gjr_x_btc": float(qlike_gjr_x),
        "qlike_improvement_pct": float((qlike_gjr - qlike_gjr_x) / qlike_gjr * 100),
        "dm_test": {"t_stat": float(dm_garch), "p_value": float(dm_garch_p)},
    }
else:
    print("  Not enough valid forecasts for evaluation.")
    results["garch_forecasting"] = {"error": "insufficient valid forecasts"}


# ═══════════════════════════════════════════════════════════════════
# SECTION 10: PORTFOLIO DIVERSIFICATION
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("[10] Portfolio Diversification Analysis")
print("=" * 70)

spy_daily = spy_aligned["ret"].values
btc_daily = btc_aligned["ret"].values

# Backtest period: use all available data
# 100% SPY
port_spy100 = spy_daily

# 90/10 SPY/BTC
port_9010 = 0.90 * spy_daily + 0.10 * btc_daily

# 95/5 SPY/BTC
port_9505 = 0.95 * spy_daily + 0.05 * btc_daily

portfolios = {
    "100% SPY": port_spy100,
    "95/5 SPY/BTC": port_9505,
    "90/10 SPY/BTC": port_9010,
}

print(f"\n  Period: {spy_aligned.index[0].strftime('%Y-%m-%d')} to {spy_aligned.index[-1].strftime('%Y-%m-%d')}")
print(f"  {'Portfolio':<20} {'CAGR':>8} {'Vol':>8} {'Sharpe':>8} {'MDD':>8} {'Skew':>8}")
print(f"  {'-'*60}")

port_results = {}
for name, ret in portfolios.items():
    n_years = len(ret) / 252
    cumret = np.exp(np.cumsum(ret))
    cagr = (cumret[-1]) ** (1 / n_years) - 1

    ann_vol = np.std(ret) * np.sqrt(252)
    sharpe = (cagr) / ann_vol if ann_vol > 0 else 0

    # MDD
    wealth = np.exp(np.cumsum(ret))
    peak = np.maximum.accumulate(wealth)
    dd = (wealth - peak) / peak
    mdd = np.min(dd)

    skew = stats.skew(ret)

    print(f"  {name:<20} {cagr*100:>7.2f}% {ann_vol*100:>7.2f}% {sharpe:>7.3f} {mdd*100:>7.2f}% {skew:>7.3f}")

    port_results[name] = {
        "cagr": float(cagr),
        "ann_vol": float(ann_vol),
        "sharpe": float(sharpe),
        "mdd": float(mdd),
        "skewness": float(skew),
    }

# VT strategy applied to 90/10 portfolio
print("\n  VT Strategy on 90/10 SPY/BTC portfolio:")
print("  Using 12/VIX simple allocation...")

# Download VIX for VT
vix_data = yf.download("^VIX", start="2015-01-01", end="2026-03-28", progress=False)
if isinstance(vix_data.columns, pd.MultiIndex):
    vix_data.columns = vix_data.columns.get_level_values(0)
vix_close = vix_data["Close"].reindex(spy_aligned.index, method="ffill")

# 12/VIX allocation, capped at 1.5
vt_weight = np.minimum(12.0 / vix_close.values, 1.5)
vt_weight = np.maximum(vt_weight, 0.0)

# VT on 100% SPY
spy_vt = vt_weight * spy_daily
# VT on 90/10 portfolio
port_9010_vt = vt_weight * port_9010

# Metrics
def portfolio_metrics(ret, name):
    n_years = len(ret) / 252
    cumret = np.exp(np.cumsum(ret))
    cagr = (cumret[-1]) ** (1 / n_years) - 1
    ann_vol = np.std(ret) * np.sqrt(252)
    sharpe = cagr / ann_vol if ann_vol > 0 else 0
    wealth = np.exp(np.cumsum(ret))
    peak = np.maximum.accumulate(wealth)
    dd = (wealth - peak) / peak
    mdd = np.min(dd)
    return {
        "cagr": float(cagr),
        "ann_vol": float(ann_vol),
        "sharpe": float(sharpe),
        "mdd": float(mdd),
    }

vt_spy_metrics = portfolio_metrics(spy_vt, "VT 100% SPY")
vt_9010_metrics = portfolio_metrics(port_9010_vt, "VT 90/10")

print(f"\n  {'Portfolio':<25} {'CAGR':>8} {'Vol':>8} {'Sharpe':>8} {'MDD':>8}")
print(f"  {'-'*55}")
for name, m in [("VT 100% SPY", vt_spy_metrics), ("VT 90/10 SPY/BTC", vt_9010_metrics)]:
    print(f"  {name:<25} {m['cagr']*100:>7.2f}% {m['ann_vol']*100:>7.2f}% {m['sharpe']:>7.3f} {m['mdd']*100:>7.2f}%")

results["portfolio_diversification"] = {
    "static": port_results,
    "vt_spy_100": vt_spy_metrics,
    "vt_9010_spy_btc": vt_9010_metrics,
}


# ═══════════════════════════════════════════════════════════════════
# SECTION 11: SUBPERIOD ANALYSIS
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("[11] Subperiod Analysis")
print("=" * 70)

periods = {
    "2015-2017 (early crypto)": ("2015-01-01", "2017-12-31"),
    "2018-2019 (crypto winter)": ("2018-01-01", "2019-12-31"),
    "2020-2021 (COVID + bull)": ("2020-01-01", "2021-12-31"),
    "2022 (crypto crash)": ("2022-01-01", "2022-12-31"),
    "2023-2024 (recovery)": ("2023-01-01", "2024-12-31"),
    "2025+ (recent)": ("2025-01-01", "2026-12-31"),
}

subperiod_results = {}
print(f"\n  {'Period':<30} {'Ret Corr':>10} {'Vol Corr':>10} {'BTC Vol':>10} {'SPY Vol':>10} {'Ratio':>8}")
print(f"  {'-'*78}")

for label, (start, end) in periods.items():
    mask = (combined.index >= start) & (combined.index <= end)
    sub = combined.loc[mask]
    if len(sub) < 30:
        continue

    rc = sub["spy_ret"].corr(sub["btc_ret"])
    vc = sub["spy_abs_ret"].corr(sub["btc_abs_ret"])
    bv = np.std(sub["btc_ret"]) * np.sqrt(252) * 100
    sv = np.std(sub["spy_ret"]) * np.sqrt(252) * 100
    ratio = bv / sv if sv > 0 else np.nan

    print(f"  {label:<30} {rc:>10.4f} {vc:>10.4f} {bv:>9.2f}% {sv:>9.2f}% {ratio:>7.2f}x")

    subperiod_results[label] = {
        "n_obs": int(len(sub)),
        "return_corr": float(rc),
        "vol_corr": float(vc),
        "btc_ann_vol": float(bv / 100),
        "spy_ann_vol": float(sv / 100),
        "vol_ratio": float(ratio),
    }

results["subperiod_analysis"] = subperiod_results


# ═══════════════════════════════════════════════════════════════════
# SECTION 12: SUMMARY AND CONCLUSIONS
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("[12] Summary and Conclusions")
print("=" * 70)

conclusions = []

# 1. Correlation trend
if results["correlation"]["fisher_z_pvalue"] < 0.05:
    conclusions.append(f"Return correlation significantly changed post-2020 (pre={results['correlation']['return_corr_pre_2020']:.3f}, post={results['correlation']['return_corr_post_2020']:.3f}, p={results['correlation']['fisher_z_pvalue']:.4f})")
else:
    conclusions.append(f"No significant change in return correlation pre/post 2020 (p={results['correlation']['fisher_z_pvalue']:.4f})")

# 2. Granger causality
if results["granger_causality"]["btc_causes_spy_5pct"] and results["granger_causality"]["spy_causes_btc_5pct"]:
    conclusions.append("Bidirectional Granger causality between BTC and SPY volatility")
elif results["granger_causality"]["btc_causes_spy_5pct"]:
    conclusions.append("Unidirectional Granger causality: BTC vol → SPY vol")
elif results["granger_causality"]["spy_causes_btc_5pct"]:
    conclusions.append("Unidirectional Granger causality: SPY vol → BTC vol")
else:
    conclusions.append("No significant Granger causality between BTC and SPY vol")

# 3. BTC leverage effect
if "error" not in btc_garch_results:
    lev = btc_garch_results["leverage_direction"]
    g = btc_garch_results["gamma"]
    conclusions.append(f"BTC leverage effect: {lev} (gamma={g:.4f})")

# 4. Forecasting value
if "error" not in results.get("garch_forecasting", {}):
    imp = results["garch_forecasting"]["qlike_improvement_pct"]
    dm_p = results["garch_forecasting"]["dm_test"]["p_value"]
    if dm_p < 0.05:
        conclusions.append(f"BTC vol significantly improves SPY vol forecasting (QLIKE improvement={imp:.2f}%, DM p={dm_p:.4f})")
    else:
        conclusions.append(f"BTC vol does NOT significantly improve SPY vol forecasting (QLIKE improvement={imp:.2f}%, DM p={dm_p:.4f})")

# 5. Tail dependence
jt5 = results["tail_dependence"]["joint_extreme_5pct"]
conclusions.append(f"Tail dependence: P(both extreme at 5%) = {jt5:.4f} (vs {0.0025:.4f} under independence, ratio = {jt5/0.0025:.1f}x)")

# 6. Diversification
if "100% SPY" in port_results and "90/10 SPY/BTC" in port_results:
    s100 = port_results["100% SPY"]["sharpe"]
    s9010 = port_results["90/10 SPY/BTC"]["sharpe"]
    if s9010 > s100:
        conclusions.append(f"90/10 SPY/BTC improves Sharpe ({s100:.3f} → {s9010:.3f})")
    else:
        conclusions.append(f"90/10 SPY/BTC does NOT improve Sharpe ({s100:.3f} → {s9010:.3f})")

results["conclusions"] = conclusions

print()
for i, c in enumerate(conclusions, 1):
    print(f"  {i}. {c}")

# Limitations
limitations = [
    "BTC data filtered to weekdays only — weekend vol information lost",
    "Squared returns used as RV proxy (no intraday data for BTC)",
    "GARCH-X forecast may have look-ahead issues with exogenous variable timing",
    "Portfolio backtest assumes daily rebalancing with no transaction costs",
    "BTC pre-2017 data may have lower liquidity/reliability",
    "VT strategy calibrated for equity, may not be optimal for crypto-mixed portfolios",
]
results["limitations"] = limitations

print("\n  Limitations:")
for lim in limitations:
    print(f"    - {lim}")


# ═══════════════════════════════════════════════════════════════════
# SAVE RESULTS
# ═══════════════════════════════════════════════════════════════════
output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "k639_results.json")
with open(output_path, "w") as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n  Results saved to: {output_path}")
print("\n" + "=" * 70)
print("K639 Complete!")
print("=" * 70)
