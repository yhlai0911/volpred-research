"""
K397: India Market Volatility — Does the World's Fastest-Growing Economy Behave Differently?
============================================================================================
[提出: 用戶, 執行: Claude]

跳躍式探索：首次對印度市場進行專門波動率研究。

Pre-experiment check: 2 mentions of India but no dedicated experiment.
K237 tested 5 international markets (not India). K357 global spillover (9 countries, not India).

Data (yfinance):
- INDA (iShares MSCI India ETF) — primary proxy for India equity
- ^NSEI (Nifty 50) — secondary, may have data gaps
- SPY, GLD, ^VIX — benchmarks
- EEM, 0050.TW — EM comparisons

Methodology:
1. India vol characteristics: annualized vol, leverage effect (gamma), vol clustering
2. India-US relationship: VIX correlation, VIX→India vol prediction, Granger causality
3. India-specific factors: rate hike sensitivity (2022), India VIX (NVIX ^INDIAVIX)
4. 50/50 INDA/GLD portfolio: does the VT framework apply?
5. Time zone dynamics: India opens between Europe close and US open

Output: experiments/k397_india_vol.py + results JSON
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
from datetime import datetime
import json
import traceback

# ==================================================================
# CONFIG
# ==================================================================
WINDOW = 2000
TARGET_VOL_ANNUAL = 0.12  # 12% target (same as standard VT)
TARGET_VOL_DAILY = TARGET_VOL_ANNUAL / np.sqrt(252)
MAX_LEVERAGE = 1.5
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252

DATA_START = "2012-01-01"  # INDA ETF inception: 2012-02-02
DATA_END = "2026-03-25"

CRISES = [
    ("Taper Tantrum 2013",   "2013-05-22", "2013-08-30"),
    ("China Deval 2015",     "2015-08-11", "2015-09-29"),
    ("Demonetization 2016",  "2016-11-08", "2017-01-31"),
    ("COVID 2020",           "2020-02-20", "2020-03-23"),
    ("Rate Hike 2022",       "2022-01-03", "2022-10-12"),
    ("2024 Election Shock",  "2024-06-04", "2024-06-14"),
]

print("=" * 80)
print("K397: INDIA MARKET VOLATILITY — FASTEST-GROWING ECONOMY DIFFERENTLY?")
print("=" * 80)
print(f"  Data range: {DATA_START} to {DATA_END}")
print(f"  Window: {WINDOW}")
print(f"  Target vol: {TARGET_VOL_ANNUAL:.0%} annualized")
print(f"  Crises analyzed: {len(CRISES)}")

# ==================================================================
# 1. Download Data
# ==================================================================
print("\n[1/7] Downloading data...")

tickers = {
    "INDA": "INDA",       # iShares MSCI India ETF
    "SPY": "SPY",         # S&P 500
    "GLD": "GLD",         # Gold
    "EEM": "EEM",         # Emerging Markets
    "TW50": "0050.TW",    # Taiwan 50
}

prices = {}
returns = {}

for name, ticker in tickers.items():
    try:
        raw = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        close = raw["Close"].dropna()
        prices[name] = close
        ret = np.log(close / close.shift(1)).dropna()
        returns[name] = ret
        print(f"  {name} ({ticker}): {close.index[0].strftime('%Y-%m-%d')} to {close.index[-1].strftime('%Y-%m-%d')}, {len(ret)} days")
    except Exception as e:
        print(f"  {name} ({ticker}): FAILED - {e}")

# VIX (not a return series)
vix_raw = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix = vix_raw["Close"].dropna()
print(f"  VIX: {vix.index[0].strftime('%Y-%m-%d')} to {vix.index[-1].strftime('%Y-%m-%d')}, {len(vix)} days")

# Try India VIX
try:
    india_vix_raw = yf.download("^INDIAVIX", start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
    if isinstance(india_vix_raw.columns, pd.MultiIndex):
        india_vix_raw.columns = india_vix_raw.columns.get_level_values(0)
    india_vix = india_vix_raw["Close"].dropna()
    has_india_vix = len(india_vix) > 100
    if has_india_vix:
        print(f"  India VIX: {india_vix.index[0].strftime('%Y-%m-%d')} to {india_vix.index[-1].strftime('%Y-%m-%d')}, {len(india_vix)} days")
    else:
        print(f"  India VIX: insufficient data ({len(india_vix)} days)")
        has_india_vix = False
except Exception as e:
    print(f"  India VIX: FAILED - {e}")
    has_india_vix = False
    india_vix = pd.Series(dtype=float)

# Try Nifty 50 direct
try:
    nifty_raw = yf.download("^NSEI", start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
    if isinstance(nifty_raw.columns, pd.MultiIndex):
        nifty_raw.columns = nifty_raw.columns.get_level_values(0)
    nifty_close = nifty_raw["Close"].dropna()
    nifty_ret = np.log(nifty_close / nifty_close.shift(1)).dropna()
    has_nifty = len(nifty_ret) > 100
    if has_nifty:
        print(f"  Nifty 50 (^NSEI): {nifty_close.index[0].strftime('%Y-%m-%d')} to {nifty_close.index[-1].strftime('%Y-%m-%d')}, {len(nifty_ret)} days")
except Exception as e:
    print(f"  Nifty 50 (^NSEI): FAILED - {e}")
    has_nifty = False

# ==================================================================
# 2. India Vol Characteristics
# ==================================================================
print("\n[2/7] India volatility characteristics...")

results = {"experiment": "K397", "title": "India Market Volatility", "date": datetime.now().strftime("%Y-%m-%d")}

# Basic statistics
vol_stats = {}
for name in ["INDA", "SPY", "EEM", "TW50"]:
    if name not in returns:
        continue
    r = returns[name]
    ann_vol = r.std() * np.sqrt(252)
    ann_ret = r.mean() * 252
    skew = r.skew()
    kurt = r.kurtosis()

    # Rolling 22d realized vol
    rv22 = r.rolling(22).std() * np.sqrt(252)
    vol_of_vol = rv22.std()

    # Autocorrelation of squared returns (vol clustering)
    r2 = r ** 2
    acf1 = r2.autocorr(lag=1)
    acf5 = r2.autocorr(lag=5)
    acf22 = r2.autocorr(lag=22)

    vol_stats[name] = {
        "ann_return": float(ann_ret),
        "ann_vol": float(ann_vol),
        "sharpe": float(ann_ret / ann_vol) if ann_vol > 0 else 0,
        "skewness": float(skew),
        "excess_kurtosis": float(kurt),
        "vol_of_vol": float(vol_of_vol),
        "acf1_r2": float(acf1),
        "acf5_r2": float(acf5),
        "acf22_r2": float(acf22),
        "n_obs": len(r),
    }

print("\n  === Volatility Comparison ===")
print(f"  {'Asset':<8} {'Ann Vol':>8} {'Ann Ret':>8} {'Sharpe':>8} {'Skew':>7} {'Kurt':>7} {'ACF1(r²)':>9} {'VolOfVol':>9}")
print("  " + "-" * 74)
for name in ["INDA", "SPY", "EEM", "TW50"]:
    if name not in vol_stats:
        continue
    s = vol_stats[name]
    print(f"  {name:<8} {s['ann_vol']:>7.1%} {s['ann_return']:>7.1%} {s['sharpe']:>8.2f} {s['skewness']:>7.3f} {s['excess_kurtosis']:>7.2f} {s['acf1_r2']:>9.3f} {s['vol_of_vol']:>9.3f}")

results["vol_characteristics"] = vol_stats

# ==================================================================
# 3. GJR-GARCH Estimation — Leverage Effect (gamma)
# ==================================================================
print("\n[3/7] GJR-GARCH estimation (leverage effect)...")

garch_results = {}
for name in ["INDA", "SPY", "EEM", "TW50"]:
    if name not in returns:
        continue
    r = returns[name]
    try:
        am = arch_model(r * 100, vol="GARCH", p=1, o=1, q=1, dist="normal", mean="Constant")
        res = am.fit(disp="off", show_warning=False)

        omega = res.params.get("omega", 0)
        alpha = res.params.get("alpha[1]", 0)
        gamma = res.params.get("gamma[1]", 0)
        beta = res.params.get("beta[1]", 0)
        persistence = alpha + gamma/2 + beta

        garch_results[name] = {
            "omega": float(omega),
            "alpha": float(alpha),
            "gamma": float(gamma),
            "beta": float(beta),
            "persistence": float(persistence),
            "gamma_significant": bool(res.pvalues.get("gamma[1]", 1) < 0.05),
            "gamma_pvalue": float(res.pvalues.get("gamma[1]", 1)),
            "log_likelihood": float(res.loglikelihood),
        }

        sig = "***" if res.pvalues.get("gamma[1]", 1) < 0.001 else "**" if res.pvalues.get("gamma[1]", 1) < 0.01 else "*" if res.pvalues.get("gamma[1]", 1) < 0.05 else ""
        print(f"  {name:<8} gamma={gamma:.4f}{sig}  alpha={alpha:.4f}  beta={beta:.4f}  persist={persistence:.4f}")
    except Exception as e:
        print(f"  {name:<8} FAILED: {e}")

results["gjr_garch"] = garch_results

# ==================================================================
# 4. India-US Relationship: VIX Correlation & Granger Causality
# ==================================================================
print("\n[4/7] India-US volatility relationship...")

# Align INDA returns with VIX
if "INDA" in returns:
    common_idx = returns["INDA"].index.intersection(vix.index)
    inda_aligned = returns["INDA"].loc[common_idx]
    vix_aligned = vix.loc[common_idx]
    spy_aligned = returns["SPY"].reindex(common_idx).dropna()

    # Restrict to common dates across all three
    common_all = inda_aligned.index.intersection(spy_aligned.index)
    inda_aligned = inda_aligned.loc[common_all]
    vix_aligned = vix_aligned.loc[common_all]
    spy_aligned = spy_aligned.loc[common_all]

    # 4a. Correlation: INDA daily returns vs VIX change
    dvix = vix_aligned.pct_change().dropna()
    inda_for_corr = inda_aligned.reindex(dvix.index).dropna()
    common_corr = inda_for_corr.index.intersection(dvix.index)

    corr_inda_dvix = np.corrcoef(inda_for_corr.loc[common_corr].values, dvix.loc[common_corr].values)[0, 1]

    # SPY vs VIX for comparison
    spy_for_corr = spy_aligned.reindex(common_corr).dropna()
    common_spy_corr = spy_for_corr.index.intersection(dvix.loc[common_corr].index)
    corr_spy_dvix = np.corrcoef(spy_for_corr.loc[common_spy_corr].values, dvix.loc[common_spy_corr].values)[0, 1]

    print(f"\n  Correlation with ΔVIX:")
    print(f"    INDA vs ΔVIX: {corr_inda_dvix:.3f}")
    print(f"    SPY  vs ΔVIX: {corr_spy_dvix:.3f}")
    print(f"    Ratio (INDA/SPY): {corr_inda_dvix/corr_spy_dvix:.2f}")

    # 4b. VIX predicts INDA realized vol?
    # Rolling 22d realized vol for INDA
    inda_rv22 = (returns["INDA"].rolling(22).std() * np.sqrt(252)).dropna()
    vix_for_pred = (vix / 100).reindex(inda_rv22.index).dropna()

    common_pred = inda_rv22.index.intersection(vix_for_pred.index)
    inda_rv = inda_rv22.loc[common_pred].values
    vix_pred = vix_for_pred.loc[common_pred].values

    # Lagged prediction: VIX(t) → INDA_RV(t+22)
    # Use VIX 22 days ago to predict current INDA RV
    vix_lagged = vix_for_pred.shift(22).reindex(common_pred).dropna()
    common_lag = vix_lagged.index.intersection(inda_rv22.loc[common_pred].index)

    if len(common_lag) > 50:
        slope, intercept, r_value, p_value, std_err = stats.linregress(
            vix_lagged.loc[common_lag].values,
            inda_rv22.loc[common_lag].values
        )
        r2_vix_inda = r_value ** 2
        t_stat = slope / std_err

        print(f"\n  VIX(t) → INDA RV(t+22):")
        print(f"    R² = {r2_vix_inda:.4f}")
        print(f"    slope = {slope:.4f}, t = {t_stat:.2f}, p = {p_value:.4f}")
        print(f"    Harvey threshold: {'PASS' if abs(t_stat) > 3.0 else 'FAIL'} (t={abs(t_stat):.2f} vs 3.0)")

        results["vix_prediction"] = {
            "r2": float(r2_vix_inda),
            "slope": float(slope),
            "t_stat": float(t_stat),
            "p_value": float(p_value),
            "harvey_pass": bool(abs(t_stat) > 3.0),
            "n_obs": len(common_lag),
        }

    # 4c. Granger Causality: SPY vol → INDA vol (and reverse)
    print(f"\n  Granger Causality (5-lag VAR):")

    spy_rv22 = (returns["SPY"].rolling(22).std() * np.sqrt(252)).dropna()
    common_gc = inda_rv22.index.intersection(spy_rv22.index)

    if len(common_gc) > 100:
        inda_rv_gc = inda_rv22.loc[common_gc].values
        spy_rv_gc = spy_rv22.loc[common_gc].values

        # Simple Granger test: regress INDA_RV on its own lags + SPY_RV lags
        max_lag = 5
        n_gc = len(inda_rv_gc)

        # Build lag matrices
        Y_inda = inda_rv_gc[max_lag:]
        Y_spy = spy_rv_gc[max_lag:]

        X_inda_lags = np.column_stack([inda_rv_gc[max_lag-i-1:n_gc-i-1] for i in range(max_lag)])
        X_spy_lags = np.column_stack([spy_rv_gc[max_lag-i-1:n_gc-i-1] for i in range(max_lag)])

        # Restricted model: INDA_RV ~ own lags only
        X_restricted = np.column_stack([np.ones(len(Y_inda)), X_inda_lags])
        beta_r = np.linalg.lstsq(X_restricted, Y_inda, rcond=None)[0]
        resid_r = Y_inda - X_restricted @ beta_r
        ssr_r = np.sum(resid_r ** 2)

        # Unrestricted model: INDA_RV ~ own lags + SPY_RV lags
        X_unrestricted = np.column_stack([np.ones(len(Y_inda)), X_inda_lags, X_spy_lags])
        beta_u = np.linalg.lstsq(X_unrestricted, Y_inda, rcond=None)[0]
        resid_u = Y_inda - X_unrestricted @ beta_u
        ssr_u = np.sum(resid_u ** 2)

        # F-test
        n_obs_gc = len(Y_inda)
        k_r = X_restricted.shape[1]
        k_u = X_unrestricted.shape[1]
        f_stat_spy_to_inda = ((ssr_r - ssr_u) / (k_u - k_r)) / (ssr_u / (n_obs_gc - k_u))
        p_spy_to_inda = 1 - stats.f.cdf(f_stat_spy_to_inda, k_u - k_r, n_obs_gc - k_u)

        print(f"    SPY vol → INDA vol: F={f_stat_spy_to_inda:.2f}, p={p_spy_to_inda:.4f} {'***' if p_spy_to_inda < 0.001 else '**' if p_spy_to_inda < 0.01 else '*' if p_spy_to_inda < 0.05 else ''}")

        # Reverse: INDA vol → SPY vol
        X_restricted_rev = np.column_stack([np.ones(len(Y_spy)), X_spy_lags])
        beta_r_rev = np.linalg.lstsq(X_restricted_rev, Y_spy, rcond=None)[0]
        resid_r_rev = Y_spy - X_restricted_rev @ beta_r_rev
        ssr_r_rev = np.sum(resid_r_rev ** 2)

        X_unrestricted_rev = np.column_stack([np.ones(len(Y_spy)), X_spy_lags, X_inda_lags])
        beta_u_rev = np.linalg.lstsq(X_unrestricted_rev, Y_spy, rcond=None)[0]
        resid_u_rev = Y_spy - X_unrestricted_rev @ beta_u_rev
        ssr_u_rev = np.sum(resid_u_rev ** 2)

        f_stat_inda_to_spy = ((ssr_r_rev - ssr_u_rev) / (k_u - k_r)) / (ssr_u_rev / (n_obs_gc - k_u))
        p_inda_to_spy = 1 - stats.f.cdf(f_stat_inda_to_spy, k_u - k_r, n_obs_gc - k_u)

        print(f"    INDA vol → SPY vol: F={f_stat_inda_to_spy:.2f}, p={p_inda_to_spy:.4f} {'***' if p_inda_to_spy < 0.001 else '**' if p_inda_to_spy < 0.01 else '*' if p_inda_to_spy < 0.05 else ''}")

        results["granger_causality"] = {
            "spy_to_inda": {"f_stat": float(f_stat_spy_to_inda), "p_value": float(p_spy_to_inda), "significant": bool(p_spy_to_inda < 0.05)},
            "inda_to_spy": {"f_stat": float(f_stat_inda_to_spy), "p_value": float(p_inda_to_spy), "significant": bool(p_inda_to_spy < 0.05)},
            "direction": "bidirectional" if (p_spy_to_inda < 0.05 and p_inda_to_spy < 0.05) else
                         "SPY→INDA" if p_spy_to_inda < 0.05 else
                         "INDA→SPY" if p_inda_to_spy < 0.05 else "none",
            "n_obs": n_obs_gc,
            "lags": max_lag,
        }

    # 4d. Correlation structure
    corr_results = {}
    for name in ["SPY", "EEM", "TW50"]:
        if name not in returns:
            continue
        common_c = returns["INDA"].index.intersection(returns[name].index)
        if len(common_c) > 50:
            rho = np.corrcoef(returns["INDA"].loc[common_c].values, returns[name].loc[common_c].values)[0, 1]
            corr_results[f"INDA_{name}"] = float(rho)
            print(f"    corr(INDA, {name}) = {rho:.3f}")

    results["correlations_with_inda"] = corr_results

# ==================================================================
# 5. Crisis Behavior Comparison
# ==================================================================
print("\n[5/7] Crisis behavior comparison...")

crisis_results = {}
print(f"\n  {'Crisis':<24} {'INDA MDD':>10} {'SPY MDD':>10} {'EEM MDD':>10} {'INDA Vol':>10}")
print("  " + "-" * 68)

for crisis_name, start, end in CRISES:
    crisis_data = {}
    for name in ["INDA", "SPY", "EEM"]:
        if name not in prices:
            continue
        try:
            p = prices[name].loc[start:end]
            if len(p) < 2:
                continue
            cumret = p / p.iloc[0] - 1
            mdd = (p / p.cummax() - 1).min()
            period_vol = returns[name].loc[start:end].std() * np.sqrt(252)
            crisis_data[name] = {
                "mdd": float(mdd),
                "total_return": float(cumret.iloc[-1]),
                "period_vol": float(period_vol) if not np.isnan(period_vol) else None,
            }
        except Exception:
            pass

    inda_mdd = crisis_data.get("INDA", {}).get("mdd", None)
    spy_mdd = crisis_data.get("SPY", {}).get("mdd", None)
    eem_mdd = crisis_data.get("EEM", {}).get("mdd", None)
    inda_vol = crisis_data.get("INDA", {}).get("period_vol", None)

    print(f"  {crisis_name:<24} {inda_mdd:>9.1%} {spy_mdd if spy_mdd else 'N/A':>10} {eem_mdd if eem_mdd else 'N/A':>10} {inda_vol if inda_vol else 'N/A':>10}")
    if spy_mdd is not None and isinstance(spy_mdd, float):
        print(f"  {'':>24} {'':>10} {spy_mdd:>9.1%} {eem_mdd:>9.1%} {inda_vol:>9.1%}" if eem_mdd is not None and inda_vol is not None else "")

    crisis_results[crisis_name] = crisis_data

# Re-print nicely
print(f"\n  === Crisis MDD Summary (re-formatted) ===")
print(f"  {'Crisis':<24} {'INDA':>8} {'SPY':>8} {'EEM':>8} {'INDA Vol':>9}")
print("  " + "-" * 60)
for crisis_name, start, end in CRISES:
    cd = crisis_results.get(crisis_name, {})
    i_mdd = cd.get("INDA", {}).get("mdd")
    s_mdd = cd.get("SPY", {}).get("mdd")
    e_mdd = cd.get("EEM", {}).get("mdd")
    i_vol = cd.get("INDA", {}).get("period_vol")

    i_str = f"{i_mdd:.1%}" if i_mdd is not None else "N/A"
    s_str = f"{s_mdd:.1%}" if s_mdd is not None else "N/A"
    e_str = f"{e_mdd:.1%}" if e_mdd is not None else "N/A"
    v_str = f"{i_vol:.1%}" if i_vol is not None else "N/A"

    print(f"  {crisis_name:<24} {i_str:>8} {s_str:>8} {e_str:>8} {v_str:>9}")

results["crisis_behavior"] = crisis_results

# ==================================================================
# 6. Rate Hike Sensitivity (2022 Comparison)
# ==================================================================
print("\n[6/7] Rate hike sensitivity analysis...")

# Compare 2022 drawdowns across markets
rate_hike_start = "2022-01-03"
rate_hike_end = "2022-12-30"

rate_sensitivity = {}
for name in ["INDA", "SPY", "EEM", "TW50"]:
    if name not in prices:
        continue
    try:
        p = prices[name].loc[rate_hike_start:rate_hike_end]
        if len(p) < 50:
            continue
        r = returns[name].loc[rate_hike_start:rate_hike_end]
        total_ret = float(p.iloc[-1] / p.iloc[0] - 1)
        mdd = float((p / p.cummax() - 1).min())
        ann_vol = float(r.std() * np.sqrt(252))

        rate_sensitivity[name] = {
            "total_return_2022": total_ret,
            "mdd_2022": mdd,
            "vol_2022": ann_vol,
        }
        print(f"  {name:<8} 2022: Return={total_ret:>7.1%}  MDD={mdd:>7.1%}  Vol={ann_vol:>7.1%}")
    except Exception as e:
        print(f"  {name:<8} 2022: FAILED - {e}")

results["rate_hike_sensitivity"] = rate_sensitivity

# ==================================================================
# 7. India VIX Analysis (if available)
# ==================================================================
if has_india_vix:
    print("\n[BONUS] India VIX analysis...")

    common_ivix = india_vix.index.intersection(vix.index)
    if len(common_ivix) > 50:
        ivix_aligned = india_vix.loc[common_ivix]
        us_vix_aligned = vix.loc[common_ivix]

        corr_ivix_vix = np.corrcoef(ivix_aligned.values, us_vix_aligned.values)[0, 1]
        mean_ivix = ivix_aligned.mean()
        mean_usvix = us_vix_aligned.mean()
        spread = ivix_aligned - us_vix_aligned
        mean_spread = spread.mean()

        print(f"  India VIX mean: {mean_ivix:.1f}")
        print(f"  US VIX mean: {mean_usvix:.1f}")
        print(f"  Mean spread (IVIX - VIX): {mean_spread:.1f}")
        print(f"  Correlation (IVIX, VIX): {corr_ivix_vix:.3f}")

        results["india_vix"] = {
            "mean_india_vix": float(mean_ivix),
            "mean_us_vix": float(mean_usvix),
            "mean_spread": float(mean_spread),
            "correlation": float(corr_ivix_vix),
            "n_obs": len(common_ivix),
        }
else:
    print("\n[BONUS] India VIX: skipped (no data)")

# ==================================================================
# 8. VT Strategy for India: 12/VIX Applied to INDA
# ==================================================================
print("\n[7/7] VT Strategy for India...")

if "INDA" in returns:
    # Align INDA returns with VIX
    common_vt = returns["INDA"].index.intersection(vix.index)
    inda_r = returns["INDA"].loc[common_vt]
    vix_vt = vix.loc[common_vt]

    # Strategy 1: Pure INDA buy-and-hold
    bnh_ret = inda_r.copy()
    bnh_cum = (1 + bnh_ret).cumprod()

    # Strategy 2: 12/VIX on INDA (lagged)
    vt_weight = np.clip(12.0 / vix_vt, 0, MAX_LEVERAGE)
    vt_weight_lagged = vt_weight.shift(1).dropna()
    inda_r_vt = inda_r.reindex(vt_weight_lagged.index).dropna()
    common_vt2 = vt_weight_lagged.index.intersection(inda_r_vt.index)
    vt_weight_lagged = vt_weight_lagged.loc[common_vt2]
    inda_r_vt = inda_r_vt.loc[common_vt2]

    vt_ret = vt_weight_lagged * inda_r_vt
    vt_cum = (1 + vt_ret).cumprod()

    # Strategy 3: 50/50 INDA/GLD with 12/VIX (lagged)
    if "GLD" in returns:
        gld_r_vt = returns["GLD"].reindex(common_vt2).dropna()
        common_50 = vt_weight_lagged.index.intersection(gld_r_vt.index)

        portfolio_r = 0.5 * returns["INDA"].reindex(common_50).dropna() + 0.5 * returns["GLD"].reindex(common_50).dropna()
        vt_w_50 = vt_weight_lagged.reindex(common_50).dropna()

        # Need all three aligned
        common_final = portfolio_r.index.intersection(vt_w_50.index)
        portfolio_r = portfolio_r.loc[common_final]
        vt_w_50 = vt_w_50.loc[common_final]

        vt_5050_ret = vt_w_50 * portfolio_r
        vt_5050_cum = (1 + vt_5050_ret).cumprod()

        # Also 50/50 B&H
        bnh_5050 = portfolio_r.copy()
        bnh_5050_cum = (1 + bnh_5050).cumprod()

    # Calculate metrics
    def calc_metrics(ret_series, name):
        """Calculate strategy metrics."""
        r = ret_series.dropna()
        if len(r) < 50:
            return None
        n_years = len(r) / 252
        ann_ret = r.mean() * 252
        ann_vol = r.std() * np.sqrt(252)
        sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0

        cum = (1 + r).cumprod()
        drawdown = cum / cum.cummax() - 1
        mdd = drawdown.min()

        # Sharpe t-stat
        sharpe_se = 1.0 / np.sqrt(n_years) if n_years > 0 else 999
        sharpe_t = sharpe / sharpe_se if sharpe_se > 0 else 0

        calmar = ann_ret / abs(mdd) if mdd != 0 else 0

        # Sortino
        downside = r[r < 0]
        downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else ann_vol
        sortino = (ann_ret - RF_ANNUAL) / downside_vol if downside_vol > 0 else 0

        return {
            "ann_return": float(ann_ret),
            "ann_vol": float(ann_vol),
            "sharpe": float(sharpe),
            "sharpe_t": float(sharpe_t),
            "mdd": float(mdd),
            "calmar": float(calmar),
            "sortino": float(sortino),
            "n_years": float(n_years),
            "n_obs": len(r),
        }

    strategies = {}

    # Pure INDA B&H
    m = calc_metrics(bnh_ret, "INDA B&H")
    if m:
        strategies["INDA_BnH"] = m
        print(f"\n  INDA Buy & Hold:")
        print(f"    Sharpe={m['sharpe']:.3f} (t={m['sharpe_t']:.2f})  MDD={m['mdd']:.1%}  Vol={m['ann_vol']:.1%}")

    # 12/VIX on INDA
    m = calc_metrics(vt_ret, "INDA 12/VIX")
    if m:
        strategies["INDA_12VIX"] = m
        print(f"\n  INDA 12/VIX VT:")
        print(f"    Sharpe={m['sharpe']:.3f} (t={m['sharpe_t']:.2f})  MDD={m['mdd']:.1%}  Vol={m['ann_vol']:.1%}")

    # 50/50 INDA/GLD B&H
    if "GLD" in returns:
        m = calc_metrics(bnh_5050, "50/50 B&H")
        if m:
            strategies["INDA_GLD_5050_BnH"] = m
            print(f"\n  50/50 INDA/GLD Buy & Hold:")
            print(f"    Sharpe={m['sharpe']:.3f} (t={m['sharpe_t']:.2f})  MDD={m['mdd']:.1%}  Vol={m['ann_vol']:.1%}")

        # 50/50 INDA/GLD 12/VIX
        m = calc_metrics(vt_5050_ret, "50/50 VT")
        if m:
            strategies["INDA_GLD_5050_12VIX"] = m
            print(f"\n  50/50 INDA/GLD 12/VIX VT:")
            print(f"    Sharpe={m['sharpe']:.3f} (t={m['sharpe_t']:.2f})  MDD={m['mdd']:.1%}  Vol={m['ann_vol']:.1%}")

    # MDD improvement test (bootstrap)
    if "INDA_BnH" in strategies and "INDA_12VIX" in strategies:
        mdd_bnh = strategies["INDA_BnH"]["mdd"]
        mdd_vt = strategies["INDA_12VIX"]["mdd"]
        mdd_improvement = mdd_vt - mdd_bnh  # Less negative = improvement

        print(f"\n  MDD Improvement (VT vs B&H): {mdd_improvement:+.1%}")

        # Bootstrap test
        n_boot = 10000
        inda_r_arr = inda_r_vt.values
        vt_w_arr = vt_weight_lagged.loc[inda_r_vt.index].values
        n_days = len(inda_r_arr)

        boot_mdd_diff = np.zeros(n_boot)
        for b in range(n_boot):
            idx = np.random.choice(n_days, n_days, replace=True)
            r_boot = inda_r_arr[idx]
            w_boot = vt_w_arr[idx]

            # B&H MDD
            cum_bnh = np.cumprod(1 + r_boot)
            peak_bnh = np.maximum.accumulate(cum_bnh)
            dd_bnh = (cum_bnh / peak_bnh - 1).min()

            # VT MDD
            cum_vt = np.cumprod(1 + w_boot * r_boot)
            peak_vt = np.maximum.accumulate(cum_vt)
            dd_vt = (cum_vt / peak_vt - 1).min()

            boot_mdd_diff[b] = dd_vt - dd_bnh

        p_mdd = np.mean(boot_mdd_diff <= 0)
        print(f"  Bootstrap: VT MDD < B&H MDD in {p_mdd:.1%} of {n_boot} simulations (p={1-p_mdd:.4f})")

        strategies["mdd_bootstrap"] = {
            "mdd_improvement": float(mdd_improvement),
            "bootstrap_pct_vt_wins": float(p_mdd),
            "p_value": float(1 - p_mdd),
            "n_boot": n_boot,
        }

    results["vt_strategies"] = strategies

# ==================================================================
# 9. Time Zone Dynamics: India opens between Europe & US
# ==================================================================
print("\n\n[EXTRA] Time zone transmission dynamics...")

if "INDA" in returns and "SPY" in returns and "TW50" in returns:
    # INDA is USD-denominated ETF traded on NYSE, so it reflects same-day US trading
    # But the underlying Nifty moves during India hours (IST = UTC+5:30)
    # Compare SPY(t-1) → INDA(t) vs SPY(t-1) → TW50(t) for TZ transmission

    spy_lag1 = returns["SPY"].shift(1)

    for name in ["INDA", "TW50", "EEM"]:
        if name not in returns:
            continue
        common_tz = returns[name].index.intersection(spy_lag1.dropna().index)
        if len(common_tz) < 100:
            continue

        r_asset = returns[name].loc[common_tz].values
        r_spy_lag = spy_lag1.loc[common_tz].values

        # Remove NaN
        mask = ~(np.isnan(r_asset) | np.isnan(r_spy_lag))
        r_asset = r_asset[mask]
        r_spy_lag = r_spy_lag[mask]

        if len(r_asset) > 50:
            slope, intercept, r_value, p_value, std_err = stats.linregress(r_spy_lag, r_asset)
            print(f"  SPY(t-1) → {name}(t): beta={slope:.3f}, R²={r_value**2:.4f}, t={slope/std_err:.2f}, p={p_value:.4f}")

            if "timezone_transmission" not in results:
                results["timezone_transmission"] = {}
            results["timezone_transmission"][name] = {
                "beta": float(slope),
                "r2": float(r_value**2),
                "t_stat": float(slope/std_err),
                "p_value": float(p_value),
            }

# ==================================================================
# 10. India VIX vs US VIX as predictor
# ==================================================================
if has_india_vix and "INDA" in returns:
    print("\n[EXTRA] India VIX vs US VIX as INDA volatility predictor...")

    # Compare predictive power: India VIX vs US VIX for INDA realized vol
    inda_rv22_pred = (returns["INDA"].rolling(22).std() * np.sqrt(252)).dropna()

    # India VIX predictor
    ivix_pred = (india_vix / 100).shift(22)
    common_ivix_pred = inda_rv22_pred.index.intersection(ivix_pred.dropna().index)

    if len(common_ivix_pred) > 50:
        y_iv = inda_rv22_pred.loc[common_ivix_pred].values
        x_ivix = ivix_pred.loc[common_ivix_pred].values

        slope_iv, intercept_iv, r_iv, p_iv, se_iv = stats.linregress(x_ivix, y_iv)
        r2_ivix = r_iv ** 2

        # US VIX predictor (same dates)
        usvix_pred = (vix / 100).shift(22)
        common_both = common_ivix_pred.intersection(usvix_pred.dropna().index)

        if len(common_both) > 50:
            x_usvix = usvix_pred.loc[common_both].values
            y_both = inda_rv22_pred.loc[common_both].values
            x_ivix_both = ivix_pred.loc[common_both].values

            slope_us, intercept_us, r_us, p_us, se_us = stats.linregress(x_usvix, y_both)
            r2_usvix = r_us ** 2

            slope_iv2, intercept_iv2, r_iv2, p_iv2, se_iv2 = stats.linregress(x_ivix_both, y_both)
            r2_ivix2 = r_iv2 ** 2

            print(f"  India VIX(t) → INDA RV(t+22): R²={r2_ivix2:.4f}")
            print(f"  US VIX(t) → INDA RV(t+22):    R²={r2_usvix:.4f}")
            print(f"  India VIX advantage: {r2_ivix2 - r2_usvix:+.4f}")

            results["vix_comparison_as_predictor"] = {
                "india_vix_r2": float(r2_ivix2),
                "us_vix_r2": float(r2_usvix),
                "india_vix_advantage": float(r2_ivix2 - r2_usvix),
                "n_obs": len(common_both),
            }

# ==================================================================
# 11. Full Period Rolling Correlation
# ==================================================================
print("\n[EXTRA] Rolling 252d correlation: INDA-SPY...")

if "INDA" in returns and "SPY" in returns:
    common_roll = returns["INDA"].index.intersection(returns["SPY"].index)
    inda_roll = returns["INDA"].loc[common_roll]
    spy_roll = returns["SPY"].loc[common_roll]

    rolling_corr = inda_roll.rolling(252).corr(spy_roll).dropna()

    print(f"  Mean rolling corr: {rolling_corr.mean():.3f}")
    print(f"  Min rolling corr:  {rolling_corr.min():.3f}")
    print(f"  Max rolling corr:  {rolling_corr.max():.3f}")
    print(f"  Std rolling corr:  {rolling_corr.std():.3f}")

    # Regime breakdown
    low_corr = rolling_corr[rolling_corr < 0.3]
    high_corr = rolling_corr[rolling_corr > 0.6]

    print(f"  Days with corr < 0.3: {len(low_corr)} ({len(low_corr)/len(rolling_corr):.1%})")
    print(f"  Days with corr > 0.6: {len(high_corr)} ({len(high_corr)/len(rolling_corr):.1%})")

    results["rolling_correlation"] = {
        "mean": float(rolling_corr.mean()),
        "min": float(rolling_corr.min()),
        "max": float(rolling_corr.max()),
        "std": float(rolling_corr.std()),
        "pct_below_03": float(len(low_corr)/len(rolling_corr)),
        "pct_above_06": float(len(high_corr)/len(rolling_corr)),
    }

# ==================================================================
# 12. India Amplification Factor (K237-style)
# ==================================================================
print("\n[EXTRA] India amplification factor...")

if "INDA" in returns and "SPY" in returns:
    common_amp = returns["INDA"].index.intersection(returns["SPY"].index)
    inda_amp = returns["INDA"].loc[common_amp]
    spy_amp = returns["SPY"].loc[common_amp]

    # Amplification = ratio of vol during SPY stress to calm
    spy_rv22_amp = spy_amp.rolling(22).std() * np.sqrt(252)
    inda_rv22_amp = inda_amp.rolling(22).std() * np.sqrt(252)

    high_vix_dates = spy_rv22_amp[spy_rv22_amp > spy_rv22_amp.quantile(0.75)].index
    low_vix_dates = spy_rv22_amp[spy_rv22_amp < spy_rv22_amp.quantile(0.25)].index

    inda_vol_high = inda_rv22_amp.loc[inda_rv22_amp.index.intersection(high_vix_dates)].mean()
    inda_vol_low = inda_rv22_amp.loc[inda_rv22_amp.index.intersection(low_vix_dates)].mean()

    amplification = inda_vol_high / inda_vol_low if inda_vol_low > 0 else np.nan

    # Compare to SPY's own amplification
    spy_vol_high = spy_rv22_amp.loc[spy_rv22_amp.index.intersection(high_vix_dates)].mean()
    spy_vol_low = spy_rv22_amp.loc[spy_rv22_amp.index.intersection(low_vix_dates)].mean()
    spy_amplification = spy_vol_high / spy_vol_low if spy_vol_low > 0 else np.nan

    print(f"  INDA amplification (Q75/Q25 vol): {amplification:.2f}x")
    print(f"  SPY amplification (Q75/Q25 vol):  {spy_amplification:.2f}x")
    print(f"  Relative amplification (INDA/SPY): {amplification/spy_amplification:.2f}x" if spy_amplification and not np.isnan(spy_amplification) else "")

    results["amplification"] = {
        "inda": float(amplification),
        "spy": float(spy_amplification),
        "relative": float(amplification / spy_amplification) if spy_amplification and not np.isnan(spy_amplification) else None,
        "inda_vol_high": float(inda_vol_high),
        "inda_vol_low": float(inda_vol_low),
    }

# ==================================================================
# SUMMARY
# ==================================================================
print("\n" + "=" * 80)
print("K397 SUMMARY")
print("=" * 80)

print("\n1. VOLATILITY PROFILE:")
if "INDA" in vol_stats:
    vs = vol_stats["INDA"]
    print(f"   INDA annualized vol: {vs['ann_vol']:.1%}")
    print(f"   INDA vs SPY vol ratio: {vs['ann_vol']/vol_stats.get('SPY', {}).get('ann_vol', 0.15):.2f}x")
    print(f"   INDA skewness: {vs['skewness']:.3f} (negative = leverage effect)")
    print(f"   INDA excess kurtosis: {vs['excess_kurtosis']:.2f} (fat tails)")

print("\n2. LEVERAGE EFFECT (GJR gamma):")
for name in ["INDA", "SPY", "EEM"]:
    if name in garch_results:
        g = garch_results[name]
        sig_str = "***" if g['gamma_pvalue'] < 0.001 else "**" if g['gamma_pvalue'] < 0.01 else "*" if g['gamma_pvalue'] < 0.05 else "n.s."
        print(f"   {name}: gamma={g['gamma']:.4f} ({sig_str})")

print("\n3. VIX-INDIA RELATIONSHIP:")
if "vix_prediction" in results:
    vp = results["vix_prediction"]
    print(f"   VIX(t) → INDA RV(t+22): R²={vp['r2']:.4f}, t={vp['t_stat']:.2f}")
    print(f"   Harvey test: {'PASS' if vp['harvey_pass'] else 'FAIL'}")

if "granger_causality" in results:
    gc = results["granger_causality"]
    print(f"   Granger direction: {gc['direction']}")

print("\n4. VT STRATEGY EFFECTIVENESS:")
if "vt_strategies" in results:
    strats = results["vt_strategies"]
    for key, s in strats.items():
        if isinstance(s, dict) and "sharpe" in s:
            harvey = "PASS" if abs(s.get('sharpe_t', 0)) > 3.0 else "FAIL"
            print(f"   {key}: Sharpe={s['sharpe']:.3f} (t={s.get('sharpe_t', 0):.2f}, Harvey {harvey}), MDD={s['mdd']:.1%}")

    if "mdd_bootstrap" in strats:
        mb = strats["mdd_bootstrap"]
        print(f"   MDD improvement: {mb['mdd_improvement']:+.1%} (bootstrap p={mb['p_value']:.4f})")

print("\n5. CROSS-MARKET DYNAMICS:")
if "correlations_with_inda" in results:
    for k, v in results["correlations_with_inda"].items():
        print(f"   {k}: {v:.3f}")

if "rolling_correlation" in results:
    rc = results["rolling_correlation"]
    print(f"   Rolling 252d INDA-SPY corr: mean={rc['mean']:.3f}, range=[{rc['min']:.3f}, {rc['max']:.3f}]")

if "amplification" in results:
    amp = results["amplification"]
    print(f"   India amplification: {amp['inda']:.2f}x (SPY: {amp['spy']:.2f}x)")

print("\n6. KEY FINDINGS:")
findings = []

# Check if India behaves differently
if "INDA" in vol_stats:
    vs_inda = vol_stats["INDA"]
    vs_spy = vol_stats.get("SPY", {})
    vol_ratio = vs_inda.get("ann_vol", 0) / vs_spy.get("ann_vol", 0.15)

    if vol_ratio > 1.3:
        findings.append(f"INDA is significantly more volatile than SPY ({vol_ratio:.2f}x)")
    elif vol_ratio < 0.8:
        findings.append(f"INDA is significantly less volatile than SPY ({vol_ratio:.2f}x)")
    else:
        findings.append(f"INDA vol comparable to SPY ({vol_ratio:.2f}x)")

if "INDA" in garch_results:
    g = garch_results["INDA"]
    if g["gamma_significant"]:
        findings.append(f"India has significant leverage effect (gamma={g['gamma']:.4f})")
    else:
        findings.append(f"India leverage effect NOT significant (gamma={g['gamma']:.4f})")

if "granger_causality" in results:
    findings.append(f"Volatility transmission: {results['granger_causality']['direction']}")

if "vt_strategies" in results:
    strats = results["vt_strategies"]
    if "INDA_12VIX" in strats and "INDA_BnH" in strats:
        sharpe_diff = strats["INDA_12VIX"]["sharpe"] - strats["INDA_BnH"]["sharpe"]
        mdd_diff = strats["INDA_12VIX"]["mdd"] - strats["INDA_BnH"]["mdd"]
        findings.append(f"12/VIX VT for India: Sharpe {'improvement' if sharpe_diff > 0 else 'decline'} of {sharpe_diff:+.3f}")
        findings.append(f"12/VIX VT for India: MDD improvement of {mdd_diff:+.1%}")

    if "INDA_GLD_5050_12VIX" in strats:
        s = strats["INDA_GLD_5050_12VIX"]
        findings.append(f"50/50 INDA/GLD + 12/VIX: Sharpe={s['sharpe']:.3f}, MDD={s['mdd']:.1%}")

for i, f in enumerate(findings, 1):
    print(f"   {i}. {f}")

results["findings"] = findings

# ==================================================================
# Save Results
# ==================================================================
output_file = "/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-af0237cf/experiments/k397_india_vol_results.json"
with open(output_file, "w") as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to: {output_file}")
print("\n[K397 COMPLETE]")
