"""
K212: Conditional VIX Sufficiency — When Does VIX Fail Even for Equities?
=========================================================================
Background: K207 showed VIX is sufficient for equities ON AVERAGE.
K211 showed QQQ HL passes Harvey (t=-5.68) even for equities.
Question: Is VIX sufficiency CONDITIONAL on market regime?

Methodology:
  1. Split sample into VIX regimes:
     - Low (<15), Medium (15-25), High (25-35), Crisis (>35)
  2. For each regime, test if non-VIX features add partial correlation
     beyond VIX: own 22d vol, range ratio, lagged VIX change
  3. Interaction model: RV = α + β1*VIX + β2*OwnVol + β3*VIX*OwnVol
  4. If regime-conditional, build regime-switching VT:
     VIX-based in normal, OwnVol-based in crisis

Data: SPY, QQQ daily from yfinance. VIX from yfinance. OOS: 2023-2024.
Statistical: Harvey threshold (|t|>3.0), partial correlations per regime.

[提出: 用戶, 執行: Claude]
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
from datetime import datetime

np.random.seed(42)

# ============================================================
# 1. Download data
# ============================================================
print("=" * 70)
print("K212: Conditional VIX Sufficiency — When Does VIX Fail?")
print("=" * 70)

print("\n[1/8] Downloading data...")

tickers = {
    "SPY": "SPY",
    "QQQ": "QQQ",
    "VIX": "^VIX",
}

raw_data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start="2006-01-01", end="2025-01-01", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    col = "Adj Close" if "Adj Close" in df.columns else "Close"
    raw_data[name] = df[[col, "High", "Low"]].copy()
    raw_data[name].columns = [f"{name}", f"{name}_High", f"{name}_Low"]
    print(f"  {name}: {len(raw_data[name])} obs")

# Combine
df = pd.concat(raw_data.values(), axis=1)
df = df.dropna()
print(f"  Combined: {len(df)} obs, {df.index[0].date()} ~ {df.index[-1].date()}")

# ============================================================
# 2. Compute features
# ============================================================
print("\n[2/8] Computing features...")

for asset in ["SPY", "QQQ"]:
    # Returns
    df[f"{asset}_ret"] = np.log(df[asset] / df[asset].shift(1))

    # 22-day realized vol (annualized)
    df[f"{asset}_RV22"] = df[f"{asset}_ret"].rolling(22).std() * np.sqrt(252)

    # Forward 22-day realized vol (target)
    df[f"{asset}_FwdRV22"] = df[f"{asset}_ret"].shift(-1).rolling(22).apply(
        lambda x: x.std() * np.sqrt(252) if len(x) == 22 else np.nan
    )
    # Simpler forward RV: use shift approach
    rv_series = df[f"{asset}_ret"].rolling(22).std() * np.sqrt(252)
    df[f"{asset}_FwdRV22"] = rv_series.shift(-22)

    # Range ratio: (High-Low)/Close — intraday vol proxy
    df[f"{asset}_RangeRatio"] = (df[f"{asset}_High"] - df[f"{asset}_Low"]) / df[asset]
    # 5-day smoothed range ratio
    df[f"{asset}_RangeRatio5"] = df[f"{asset}_RangeRatio"].rolling(5).mean()

# VIX annualized vol (already annualized, divide by 100 to get fraction)
df["VIX_frac"] = df["VIX"] / 100.0

# Lagged VIX change (5-day)
df["VIX_chg5"] = df["VIX"].pct_change(5)

# VIX regime
def classify_vix_regime(vix):
    if vix < 15:
        return "Low (<15)"
    elif vix < 25:
        return "Medium (15-25)"
    elif vix < 35:
        return "High (25-35)"
    else:
        return "Crisis (>35)"

df["VIX_regime"] = df["VIX"].apply(classify_vix_regime)

# Drop NaN
df = df.dropna()
print(f"  After feature computation: {len(df)} obs")

# Regime distribution
regime_counts = df["VIX_regime"].value_counts()
print("\n  VIX Regime Distribution:")
for regime in ["Low (<15)", "Medium (15-25)", "High (25-35)", "Crisis (>35)"]:
    if regime in regime_counts.index:
        pct = regime_counts[regime] / len(df) * 100
        print(f"    {regime}: {regime_counts[regime]} days ({pct:.1f}%)")
    else:
        print(f"    {regime}: 0 days (0.0%)")

# ============================================================
# 3. Define OOS period
# ============================================================
print("\n[3/8] Splitting IS/OOS...")

oos_start = "2023-01-01"
oos_end = "2024-12-31"

df_is = df[df.index < oos_start]
df_oos = df[(df.index >= oos_start) & (df.index <= oos_end)]

print(f"  IS: {len(df_is)} obs ({df_is.index[0].date()} ~ {df_is.index[-1].date()})")
print(f"  OOS: {len(df_oos)} obs ({df_oos.index[0].date()} ~ {df_oos.index[-1].date()})")

# ============================================================
# 4. Partial correlations per regime
# ============================================================
print("\n[4/8] Partial correlations per regime (controlling for VIX)...")

def partial_corr(x, y, z):
    """Partial correlation between x and y controlling for z.
    Returns (r_partial, t_stat, p_value, n)."""
    # Remove NaN
    mask = ~(np.isnan(x) | np.isnan(y) | np.isnan(z))
    x, y, z = x[mask], y[mask], z[mask]
    n = len(x)
    if n < 10:
        return np.nan, np.nan, np.nan, n

    # Residualize x on z
    slope_xz = np.polyfit(z, x, 1)
    resid_x = x - np.polyval(slope_xz, z)

    # Residualize y on z
    slope_yz = np.polyfit(z, y, 1)
    resid_y = y - np.polyval(slope_yz, z)

    # Correlation of residuals
    r, p = stats.pearsonr(resid_x, resid_y)

    # t-stat with df = n - 3 (controlling for 1 variable)
    df_stat = n - 3
    if abs(r) >= 1.0:
        t_stat = np.inf * np.sign(r)
    else:
        t_stat = r * np.sqrt(df_stat / (1 - r**2))

    return r, t_stat, p, n

regimes = ["Low (<15)", "Medium (15-25)", "High (25-35)", "Crisis (>35)"]
features = {
    "Own 22d RV": lambda df, asset: df[f"{asset}_RV22"].values,
    "Range Ratio (5d)": lambda df, asset: df[f"{asset}_RangeRatio5"].values,
    "VIX Change (5d)": lambda df, asset: df["VIX_chg5"].values,
}

results = {}

for sample_name, sample_df in [("Full Sample", df), ("IS", df_is), ("OOS", df_oos)]:
    results[sample_name] = {}
    print(f"\n  === {sample_name} ===")

    for asset in ["SPY", "QQQ"]:
        results[sample_name][asset] = {}
        print(f"\n  {asset}:")
        print(f"  {'Feature':<22} {'Regime':<18} {'r_partial':>10} {'t-stat':>8} {'p-value':>10} {'N':>6} {'Harvey':>8}")
        print(f"  {'-'*22} {'-'*18} {'-'*10} {'-'*8} {'-'*10} {'-'*6} {'-'*8}")

        for feat_name, feat_func in features.items():
            results[sample_name][asset][feat_name] = {}

            for regime in regimes:
                regime_mask = sample_df["VIX_regime"] == regime
                regime_df = sample_df[regime_mask]

                if len(regime_df) < 20:
                    results[sample_name][asset][feat_name][regime] = {
                        "r_partial": None, "t_stat": None, "p_value": None,
                        "n": len(regime_df), "passes_harvey": False
                    }
                    print(f"  {feat_name:<22} {regime:<18} {'N/A':>10} {'N/A':>8} {'N/A':>10} {len(regime_df):>6} {'N/A':>8}")
                    continue

                target = regime_df[f"{asset}_FwdRV22"].values
                feature = feat_func(regime_df, asset)
                control = regime_df["VIX_frac"].values

                r, t, p, n = partial_corr(feature, target, control)
                passes = abs(t) > 3.0 if not np.isnan(t) else False

                results[sample_name][asset][feat_name][regime] = {
                    "r_partial": round(r, 4) if not np.isnan(r) else None,
                    "t_stat": round(t, 3) if not np.isnan(t) else None,
                    "p_value": round(p, 4) if not np.isnan(p) else None,
                    "n": int(n),
                    "passes_harvey": bool(passes)
                }

                harvey_str = "PASS" if passes else "fail"
                print(f"  {feat_name:<22} {regime:<18} {r:>10.4f} {t:>8.3f} {p:>10.4f} {n:>6} {harvey_str:>8}")

# ============================================================
# 5. Interaction model
# ============================================================
print("\n[5/8] Interaction model: FwdRV = α + β1*VIX + β2*OwnVol + β3*VIX×OwnVol...")

from numpy.linalg import lstsq

interaction_results = {}

for sample_name, sample_df in [("Full Sample", df), ("IS", df_is), ("OOS", df_oos)]:
    interaction_results[sample_name] = {}

    for asset in ["SPY", "QQQ"]:
        y = sample_df[f"{asset}_FwdRV22"].values
        vix = sample_df["VIX_frac"].values
        own_vol = sample_df[f"{asset}_RV22"].values

        # Model 1: VIX only
        X1 = np.column_stack([np.ones(len(y)), vix])
        beta1, res1, _, _ = lstsq(X1, y, rcond=None)
        ss_res1 = np.sum((y - X1 @ beta1)**2)
        ss_tot = np.sum((y - y.mean())**2)
        r2_vix_only = 1 - ss_res1 / ss_tot

        # Model 2: VIX + OwnVol
        X2 = np.column_stack([np.ones(len(y)), vix, own_vol])
        beta2, res2, _, _ = lstsq(X2, y, rcond=None)
        ss_res2 = np.sum((y - X2 @ beta2)**2)
        r2_vix_ownvol = 1 - ss_res2 / ss_tot

        # Model 3: VIX + OwnVol + Interaction
        interaction = vix * own_vol
        X3 = np.column_stack([np.ones(len(y)), vix, own_vol, interaction])
        beta3, res3, _, _ = lstsq(X3, y, rcond=None)
        ss_res3 = np.sum((y - X3 @ beta3)**2)
        r2_interaction = 1 - ss_res3 / ss_tot

        # t-stats for interaction model
        n = len(y)
        k = X3.shape[1]
        mse = ss_res3 / (n - k)
        try:
            cov_beta = mse * np.linalg.inv(X3.T @ X3)
            se_beta = np.sqrt(np.diag(cov_beta))
            t_stats = beta3 / se_beta
        except np.linalg.LinAlgError:
            t_stats = [np.nan] * k

        # F-test: Model 2 vs Model 3 (does interaction term help?)
        df1 = 1  # one additional parameter
        df2 = n - k
        if ss_res2 > 0:
            f_stat = ((ss_res2 - ss_res3) / df1) / (ss_res3 / df2)
            f_pval = 1 - stats.f.cdf(f_stat, df1, df2)
        else:
            f_stat, f_pval = np.nan, np.nan

        interaction_results[sample_name][asset] = {
            "r2_vix_only": round(r2_vix_only, 4),
            "r2_vix_ownvol": round(r2_vix_ownvol, 4),
            "r2_interaction": round(r2_interaction, 4),
            "delta_r2_ownvol": round(r2_vix_ownvol - r2_vix_only, 4),
            "delta_r2_interaction": round(r2_interaction - r2_vix_ownvol, 4),
            "beta_interaction": round(float(beta3[3]), 4),
            "t_interaction": round(float(t_stats[3]), 3),
            "f_stat_interaction": round(float(f_stat), 3),
            "f_pval_interaction": round(float(f_pval), 4),
            "n": n,
        }

        print(f"\n  {sample_name} / {asset}:")
        print(f"    R² VIX-only:      {r2_vix_only:.4f}")
        print(f"    R² VIX+OwnVol:    {r2_vix_ownvol:.4f}  (ΔR²={r2_vix_ownvol - r2_vix_only:+.4f})")
        print(f"    R² w/ Interaction: {r2_interaction:.4f}  (ΔR²={r2_interaction - r2_vix_ownvol:+.4f})")
        print(f"    β(VIX×OwnVol): {beta3[3]:.4f}  t={t_stats[3]:.3f}")
        print(f"    F-test (interaction): F={f_stat:.3f}  p={f_pval:.4f}")

# ============================================================
# 6. Regime-conditional forecast encompassing test
# ============================================================
print("\n[6/8] Regime-conditional forecast encompassing (DM-like per regime)...")

encompassing_results = {}

for sample_name, sample_df in [("IS", df_is), ("OOS", df_oos)]:
    encompassing_results[sample_name] = {}

    for asset in ["SPY", "QQQ"]:
        encompassing_results[sample_name][asset] = {}

        for regime in regimes:
            regime_mask = sample_df["VIX_regime"] == regime
            regime_df = sample_df[regime_mask]

            if len(regime_df) < 30:
                encompassing_results[sample_name][asset][regime] = {
                    "n": len(regime_df),
                    "qlike_vix": None,
                    "qlike_ownvol": None,
                    "dm_t": None,
                    "dm_p": None,
                    "winner": "insufficient data"
                }
                continue

            target = regime_df[f"{asset}_FwdRV22"].values
            vix_pred = regime_df["VIX_frac"].values
            own_pred = regime_df[f"{asset}_RV22"].values

            # Ensure positive values for QLIKE
            eps = 1e-8
            target_pos = np.maximum(target, eps)
            vix_pos = np.maximum(vix_pred, eps)
            own_pos = np.maximum(own_pred, eps)

            # QLIKE loss: log(σ²_pred) + RV²_actual / σ²_pred
            # Using vol (not variance): log(pred²) + actual² / pred²
            qlike_vix = np.mean(np.log(vix_pos**2) + (target_pos**2) / (vix_pos**2))
            qlike_own = np.mean(np.log(own_pos**2) + (target_pos**2) / (own_pos**2))

            # DM test: loss difference
            d = (np.log(vix_pos**2) + (target_pos**2) / (vix_pos**2)) - \
                (np.log(own_pos**2) + (target_pos**2) / (own_pos**2))

            # Newey-West adjusted t-stat (lag=22 for monthly horizon)
            n_dm = len(d)
            d_bar = d.mean()
            lag = min(22, n_dm // 3)

            # Newey-West variance
            gamma_0 = np.var(d, ddof=1)
            nw_var = gamma_0
            for j in range(1, lag + 1):
                gamma_j = np.cov(d[j:], d[:-j])[0, 1] if len(d[j:]) > 1 else 0
                nw_var += 2 * (1 - j / (lag + 1)) * gamma_j

            se_dm = np.sqrt(nw_var / n_dm)
            dm_t = d_bar / se_dm if se_dm > 0 else 0
            dm_p = 2 * (1 - stats.norm.cdf(abs(dm_t)))

            winner = "VIX" if dm_t < 0 else "OwnVol"
            if dm_p > 0.10:
                winner += " (n.s.)"

            encompassing_results[sample_name][asset][regime] = {
                "n": len(regime_df),
                "qlike_vix": round(qlike_vix, 4),
                "qlike_ownvol": round(qlike_own, 4),
                "dm_t": round(dm_t, 3),
                "dm_p": round(dm_p, 4),
                "winner": winner
            }

    print(f"\n  === {sample_name} ===")
    for asset in ["SPY", "QQQ"]:
        print(f"\n  {asset}:")
        print(f"  {'Regime':<18} {'N':>5} {'QLIKE(VIX)':>12} {'QLIKE(Own)':>12} {'DM t':>8} {'p':>8} {'Winner':>16}")
        print(f"  {'-'*18} {'-'*5} {'-'*12} {'-'*12} {'-'*8} {'-'*8} {'-'*16}")
        for regime in regimes:
            r = encompassing_results[sample_name][asset][regime]
            if r["qlike_vix"] is not None:
                print(f"  {regime:<18} {r['n']:>5} {r['qlike_vix']:>12.4f} {r['qlike_ownvol']:>12.4f} {r['dm_t']:>8.3f} {r['dm_p']:>8.4f} {r['winner']:>16}")
            else:
                print(f"  {regime:<18} {r['n']:>5} {'N/A':>12} {'N/A':>12} {'N/A':>8} {'N/A':>8} {'insufficient':>16}")

# ============================================================
# 7. Regime-switching VT backtest
# ============================================================
print("\n[7/8] Regime-switching VT backtest (OOS 2023-2024)...")

vt_results = {}

for asset in ["SPY", "QQQ"]:
    asset_oos = df_oos.copy()

    target_vol = 0.12  # 12% target
    rf_daily = 0.05 / 252  # ~5% risk-free

    # Strategy 1: Pure VIX VT (benchmark)
    vix_weight = target_vol / asset_oos["VIX_frac"]
    vix_weight = vix_weight.clip(0, 1.5)  # cap at 150%
    # Use lagged weight (VIX_t → return_{t+1})
    vix_weight_lag = vix_weight.shift(1)
    ret_vix_vt = vix_weight_lag * asset_oos[f"{asset}_ret"]

    # Strategy 2: Pure OwnVol VT
    own_weight = target_vol / asset_oos[f"{asset}_RV22"]
    own_weight = own_weight.clip(0, 1.5)
    own_weight_lag = own_weight.shift(1)
    ret_own_vt = own_weight_lag * asset_oos[f"{asset}_ret"]

    # Strategy 3: Regime-switching VT
    # VIX-based when VIX < 25 (Low + Medium)
    # OwnVol-based when VIX >= 25 (High + Crisis)
    regime_weight = pd.Series(index=asset_oos.index, dtype=float)
    low_med_mask = asset_oos["VIX"].values < 25
    regime_weight[low_med_mask] = vix_weight[low_med_mask]
    regime_weight[~low_med_mask] = own_weight[~low_med_mask]
    regime_weight = regime_weight.clip(0, 1.5)
    regime_weight_lag = regime_weight.shift(1)
    ret_regime_vt = regime_weight_lag * asset_oos[f"{asset}_ret"]

    # Strategy 4: Blended VT (adaptive blend based on VIX level)
    # α = min(1, VIX/25): 0% OwnVol at VIX=0, 100% OwnVol at VIX≥25
    alpha = (asset_oos["VIX"] / 25).clip(0, 1)
    blended_weight = (1 - alpha) * vix_weight + alpha * own_weight
    blended_weight = blended_weight.clip(0, 1.5)
    blended_weight_lag = blended_weight.shift(1)
    ret_blended_vt = blended_weight_lag * asset_oos[f"{asset}_ret"]

    # Buy and hold
    ret_bh = asset_oos[f"{asset}_ret"]

    strategies = {
        "Buy & Hold": ret_bh,
        "VIX VT": ret_vix_vt,
        "OwnVol VT": ret_own_vt,
        "Regime Switch VT": ret_regime_vt,
        "Blended VT": ret_blended_vt,
    }

    vt_results[asset] = {}
    print(f"\n  {asset}:")
    print(f"  {'Strategy':<20} {'Ann Ret':>8} {'Ann Vol':>8} {'Sharpe':>8} {'MDD':>8} {'Calmar':>8}")
    print(f"  {'-'*20} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")

    for strat_name, rets in strategies.items():
        rets_clean = rets.dropna()
        if len(rets_clean) < 50:
            continue

        ann_ret = rets_clean.mean() * 252
        ann_vol = rets_clean.std() * np.sqrt(252)
        sharpe = (ann_ret - 0.05) / ann_vol if ann_vol > 0 else 0

        cum_ret = (1 + rets_clean).cumprod()
        rolling_max = cum_ret.cummax()
        drawdown = (cum_ret - rolling_max) / rolling_max
        mdd = drawdown.min()
        calmar = ann_ret / abs(mdd) if mdd < 0 else 0

        vt_results[asset][strat_name] = {
            "ann_ret": round(ann_ret, 4),
            "ann_vol": round(ann_vol, 4),
            "sharpe": round(sharpe, 3),
            "mdd": round(mdd, 4),
            "calmar": round(calmar, 3),
        }

        print(f"  {strat_name:<20} {ann_ret:>8.2%} {ann_vol:>8.2%} {sharpe:>8.3f} {mdd:>8.2%} {calmar:>8.3f}")

    # DM test: Regime Switch vs VIX VT
    ret_a = ret_vix_vt.dropna()
    ret_b = ret_regime_vt.dropna()
    common_idx = ret_a.index.intersection(ret_b.index)
    if len(common_idx) > 50:
        ra = ret_a.loc[common_idx].values
        rb = ret_b.loc[common_idx].values
        # Compare squared returns as loss
        # Actually compare Sharpe: use bootstrap
        n_boot = 10000
        diff_sharpe = []
        combined = np.column_stack([ra, rb])
        for _ in range(n_boot):
            idx = np.random.choice(len(combined), len(combined), replace=True)
            boot = combined[idx]
            s_a = (boot[:, 0].mean() * 252 - 0.05) / (boot[:, 0].std() * np.sqrt(252))
            s_b = (boot[:, 1].mean() * 252 - 0.05) / (boot[:, 1].std() * np.sqrt(252))
            diff_sharpe.append(s_b - s_a)

        diff_sharpe = np.array(diff_sharpe)
        pct_better = np.mean(diff_sharpe > 0)
        mean_diff = np.mean(diff_sharpe)
        ci_lo, ci_hi = np.percentile(diff_sharpe, [2.5, 97.5])

        print(f"\n  Bootstrap Sharpe diff (RegimeSwitch - VIX VT):")
        print(f"    Mean diff: {mean_diff:+.4f}")
        print(f"    95% CI: [{ci_lo:+.4f}, {ci_hi:+.4f}]")
        print(f"    Prob(RegimeSwitch > VIX VT): {pct_better:.1%}")

        vt_results[asset]["sharpe_diff_bootstrap"] = {
            "mean_diff": round(mean_diff, 4),
            "ci_95_lo": round(ci_lo, 4),
            "ci_95_hi": round(ci_hi, 4),
            "prob_regime_better": round(pct_better, 4),
        }

# ============================================================
# 8. Multi-period robustness: test across 3 OOS periods
# ============================================================
print("\n[8/8] Multi-period robustness check...")

oos_periods = [
    ("2015-2016", "2015-01-01", "2016-12-31"),
    ("2019-2020", "2019-01-01", "2020-12-31"),  # includes COVID
    ("2023-2024", "2023-01-01", "2024-12-31"),
]

robustness_results = {}

for period_name, p_start, p_end in oos_periods:
    period_df = df[(df.index >= p_start) & (df.index <= p_end)]
    robustness_results[period_name] = {}

    print(f"\n  Period: {period_name} (N={len(period_df)})")

    for asset in ["SPY", "QQQ"]:
        # Test: partial corr of OwnVol|VIX per regime
        regime_partial = {}
        for regime in regimes:
            rmask = period_df["VIX_regime"] == regime
            rdf = period_df[rmask]
            if len(rdf) < 20:
                regime_partial[regime] = {"r": None, "t": None, "n": len(rdf)}
                continue

            r, t, p, n = partial_corr(
                rdf[f"{asset}_RV22"].values,
                rdf[f"{asset}_FwdRV22"].values,
                rdf["VIX_frac"].values
            )
            regime_partial[regime] = {
                "r": round(r, 4) if not np.isnan(r) else None,
                "t": round(t, 3) if not np.isnan(t) else None,
                "n": int(n),
                "passes_harvey": bool(abs(t) > 3.0) if not np.isnan(t) else False
            }

        robustness_results[period_name][asset] = regime_partial

        # Print
        print(f"    {asset}: ", end="")
        for regime in regimes:
            rr = regime_partial[regime]
            if rr["r"] is not None:
                flag = "*" if rr.get("passes_harvey") else ""
                print(f"{regime}: r={rr['r']:.3f}(t={rr['t']:.1f}){flag}  ", end="")
            else:
                print(f"{regime}: N/A  ", end="")
        print()

# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY: K212 Conditional VIX Sufficiency")
print("=" * 70)

# Count Harvey passes across all regimes/features/periods
total_tests = 0
harvey_passes = 0
regime_pass_counts = {r: 0 for r in regimes}
regime_total_counts = {r: 0 for r in regimes}

for sample_name in ["IS", "OOS"]:
    for asset in ["SPY", "QQQ"]:
        for feat_name in features.keys():
            for regime in regimes:
                r = results[sample_name][asset][feat_name][regime]
                if r["t_stat"] is not None:
                    total_tests += 1
                    regime_total_counts[regime] += 1
                    if r["passes_harvey"]:
                        harvey_passes += 1
                        regime_pass_counts[regime] += 1

print(f"\n1. Partial Correlation Tests (non-VIX features | VIX):")
print(f"   Total tests: {total_tests}")
print(f"   Harvey passes (|t|>3.0): {harvey_passes} ({harvey_passes/total_tests*100:.1f}%)")
print(f"\n   By regime:")
for regime in regimes:
    if regime_total_counts[regime] > 0:
        pct = regime_pass_counts[regime] / regime_total_counts[regime] * 100
        print(f"     {regime}: {regime_pass_counts[regime]}/{regime_total_counts[regime]} pass ({pct:.0f}%)")

print(f"\n2. Interaction Model (VIX × OwnVol):")
for sample_name in ["Full Sample", "IS", "OOS"]:
    for asset in ["SPY", "QQQ"]:
        ir = interaction_results[sample_name][asset]
        sig = "***" if abs(ir["t_interaction"]) > 3.0 else ("**" if abs(ir["t_interaction"]) > 2.0 else ("*" if abs(ir["t_interaction"]) > 1.65 else ""))
        print(f"   {sample_name}/{asset}: ΔR²(OwnVol)={ir['delta_r2_ownvol']:+.4f}, β(interaction) t={ir['t_interaction']:.2f}{sig}")

print(f"\n3. Regime-Switching VT (OOS 2023-2024):")
for asset in ["SPY", "QQQ"]:
    vix_s = vt_results[asset].get("VIX VT", {}).get("sharpe", "N/A")
    reg_s = vt_results[asset].get("Regime Switch VT", {}).get("sharpe", "N/A")
    boot = vt_results[asset].get("sharpe_diff_bootstrap", {})
    prob = boot.get("prob_regime_better", "N/A")
    print(f"   {asset}: VIX VT Sharpe={vix_s}, RegimeSwitch Sharpe={reg_s}, P(Switch>VIX)={prob}")

# Determine overall conclusion
print(f"\n4. CONCLUSION:")

# Check if any regime consistently shows VIX failure
any_regime_failure = False
for regime in ["High (25-35)", "Crisis (>35)"]:
    # Check OOS partial correlations
    for asset in ["SPY", "QQQ"]:
        for feat in features.keys():
            r = results["OOS"][asset][feat][regime]
            if r.get("passes_harvey"):
                any_regime_failure = True

if any_regime_failure:
    print("   VIX sufficiency IS conditional — it breaks down in high-VIX regimes.")
    print("   Non-VIX features (own vol, range ratio) add information in crisis periods.")
else:
    print("   VIX sufficiency appears UNCONDITIONAL across regimes.")
    print("   Non-VIX features do NOT reliably add information in any regime.")

# Check interaction significance
for sample_name in ["OOS"]:
    for asset in ["SPY", "QQQ"]:
        ir = interaction_results[sample_name][asset]
        if abs(ir["t_interaction"]) > 3.0:
            print(f"   BUT: Interaction term significant in OOS for {asset} (t={ir['t_interaction']:.2f})")
            print(f"   → Non-linear interaction between VIX and OwnVol matters.")

# ============================================================
# Save results
# ============================================================
output = {
    "experiment": "K212",
    "title": "Conditional VIX Sufficiency — When Does VIX Fail Even for Equities?",
    "timestamp": datetime.now().isoformat(),
    "data": {
        "assets": ["SPY", "QQQ"],
        "period": "2006-2024",
        "oos": "2023-2024",
    },
    "partial_correlations": results,
    "interaction_model": interaction_results,
    "encompassing_tests": encompassing_results,
    "vt_backtest": vt_results,
    "robustness_multi_period": robustness_results,
    "methodology": {
        "regimes": {"Low": "<15", "Medium": "15-25", "High": "25-35", "Crisis": ">35"},
        "features_tested": list(features.keys()),
        "harvey_threshold": 3.0,
        "vt_target_vol": 0.12,
    },
}

output_path = "experiments/k212_conditional_vix_results.json"
with open(output_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to {output_path}")
print("=" * 70)
