"""
K203: Momentum Crash Risk and Volatility
=========================================
Does past return (momentum) predict future volatility?

Daniel & Moskowitz (2016) showed momentum strategies crash in high-vol periods.
We test the reverse: does the momentum factor itself predict future vol?

Methodology:
1. Compute momentum signals (MOM_12_1, MOM_6_1, MOM_1) for 5 assets
2. Correlate |MOM| with next-month realized vol
3. Test extreme momentum as vol predictor (top/bottom decile)
4. Partial correlation controlling for VIX
5. Momentum-crash indicator: does extreme past return predict vol spikes?
6. VT with momentum overlay: reduce exposure when MOM extreme
7. Cross-asset validation

Statistical requirements: Harvey t>3.0, partial r|VIX, cross-asset consistency.

Data: SPY, QQQ, GLD, TLT, EEM daily from yfinance. OOS: 2023-2024.

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

# ============================================================
# 1. Download data
# ============================================================
print("=" * 70)
print("K203: Momentum Crash Risk and Volatility")
print("=" * 70)

ASSETS = ["SPY", "QQQ", "GLD", "TLT", "EEM"]
START = "2005-01-01"
END = "2026-01-01"
OOS_START = "2023-01-01"
OOS_END = "2025-01-01"

print("\n[1/7] Downloading data...")
prices = {}
returns = {}
for asset in ASSETS:
    df = yf.download(asset, start=START, end=END, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    col = "Adj Close" if "Adj Close" in df.columns else "Close"
    prices[asset] = df[col].copy()
    returns[asset] = df[col].pct_change().dropna()
    print(f"  {asset}: {len(returns[asset])} daily obs, "
          f"{prices[asset].index[0].strftime('%Y-%m-%d')} to "
          f"{prices[asset].index[-1].strftime('%Y-%m-%d')}")

# Download VIX for partial correlation control
vix_raw = yf.download("^VIX", start=START, end=END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix = vix_raw["Close"].copy()
vix.name = "VIX"
print(f"  VIX: {len(vix)} obs")

# ============================================================
# 2. Compute monthly returns and momentum signals
# ============================================================
print("\n[2/7] Computing momentum signals...")

def compute_monthly_data(price_series):
    """Compute monthly returns and momentum signals from daily prices."""
    # Resample to monthly (end of month)
    monthly_price = price_series.resample("ME").last().dropna()
    monthly_ret = monthly_price.pct_change().dropna()

    # Momentum signals
    # MOM_12_1: cumulative return months t-12 to t-1 (skip last month)
    mom_12_1 = (monthly_price / monthly_price.shift(12) - 1).shift(1)
    # MOM_6_1: cumulative return months t-6 to t-1
    mom_6_1 = (monthly_price / monthly_price.shift(6) - 1).shift(1)
    # MOM_1: last month return (short-term reversal)
    mom_1 = monthly_ret.shift(1)

    return monthly_ret, mom_12_1, mom_6_1, mom_1

def compute_monthly_realized_vol(daily_returns, year_month_index):
    """Compute realized vol for each month from daily returns."""
    monthly_groups = daily_returns.groupby(pd.Grouper(freq="ME"))
    rv = monthly_groups.std() * np.sqrt(252)  # Annualized
    # Align to year_month_index
    rv = rv.reindex(year_month_index)
    return rv

# Build monthly dataset for each asset
monthly_data = {}
for asset in ASSETS:
    m_ret, mom_12_1, mom_6_1, mom_1 = compute_monthly_data(prices[asset])
    rv = compute_monthly_realized_vol(returns[asset], m_ret.index)

    df = pd.DataFrame({
        "return": m_ret,
        "rv": rv,
        "mom_12_1": mom_12_1,
        "mom_6_1": mom_6_1,
        "mom_1": mom_1,
    }).dropna()

    # Add VIX (monthly average)
    vix_monthly = vix.resample("ME").mean()
    df["vix"] = vix_monthly.reindex(df.index)
    df = df.dropna()

    monthly_data[asset] = df
    print(f"  {asset}: {len(df)} monthly obs with all signals")

# ============================================================
# 3. Test 1: Correlation of |MOM| with next-month realized vol
# ============================================================
print("\n[3/7] Test 1: |MOM| correlation with next-month realized vol...")
print("-" * 70)

results = {}

for asset in ASSETS:
    df = monthly_data[asset].copy()
    # Next-month realized vol
    df["rv_next"] = df["rv"].shift(-1)
    df = df.dropna()

    # Split IS/OOS
    is_df = df[df.index < OOS_START]
    oos_df = df[(df.index >= OOS_START) & (df.index < OOS_END)]

    asset_results = {"n_is": len(is_df), "n_oos": len(oos_df)}

    print(f"\n  {asset} (IS={len(is_df)}, OOS={len(oos_df)} months):")

    for signal_name in ["mom_12_1", "mom_6_1", "mom_1"]:
        # Raw correlation
        r_is, p_is = stats.pearsonr(df[signal_name].abs().loc[is_df.index],
                                     df["rv_next"].loc[is_df.index])
        r_oos, p_oos = stats.pearsonr(df[signal_name].abs().loc[oos_df.index],
                                       df["rv_next"].loc[oos_df.index])

        # t-statistic
        n = len(is_df)
        t_is = r_is * np.sqrt(n - 2) / np.sqrt(1 - r_is**2) if abs(r_is) < 1 else 0
        n_oos = len(oos_df)
        t_oos = r_oos * np.sqrt(n_oos - 2) / np.sqrt(1 - r_oos**2) if abs(r_oos) < 1 else 0

        print(f"    |{signal_name}| → rv_next: IS r={r_is:.3f} (t={t_is:.2f}, p={p_is:.4f}) | "
              f"OOS r={r_oos:.3f} (t={t_oos:.2f}, p={p_oos:.4f})")

        asset_results[f"{signal_name}_r_is"] = round(r_is, 4)
        asset_results[f"{signal_name}_t_is"] = round(t_is, 2)
        asset_results[f"{signal_name}_p_is"] = round(p_is, 4)
        asset_results[f"{signal_name}_r_oos"] = round(r_oos, 4)
        asset_results[f"{signal_name}_t_oos"] = round(t_oos, 2)
        asset_results[f"{signal_name}_p_oos"] = round(p_oos, 4)

    results[asset] = asset_results

# ============================================================
# 4. Test 2: Extreme momentum and vol (quintile analysis)
# ============================================================
print("\n\n[4/7] Test 2: Extreme momentum quintile analysis...")
print("-" * 70)

quintile_results = {}

for asset in ASSETS:
    df = monthly_data[asset].copy()
    df["rv_next"] = df["rv"].shift(-1)
    df = df.dropna()

    # Full sample for quintile analysis (more power)
    print(f"\n  {asset} (N={len(df)}):")

    asset_q = {}
    for signal_name in ["mom_12_1", "mom_6_1", "mom_1"]:
        # Quintile labels (1=lowest momentum, 5=highest)
        df["quintile"] = pd.qcut(df[signal_name], 5, labels=[1, 2, 3, 4, 5])

        q_means = df.groupby("quintile")["rv_next"].mean()
        q_stds = df.groupby("quintile")["rv_next"].std()
        q_counts = df.groupby("quintile")["rv_next"].count()

        # Q1 (losers) vs Q5 (winners) vol comparison
        q1_vol = q_means.iloc[0]
        q5_vol = q_means.iloc[-1]

        # t-test Q1 vs Q5
        q1_data = df[df["quintile"] == 1]["rv_next"]
        q5_data = df[df["quintile"] == 5]["rv_next"]
        t_q1q5, p_q1q5 = stats.ttest_ind(q1_data, q5_data)

        # Extreme decile (top 10% and bottom 10%)
        df["decile"] = pd.qcut(df[signal_name], 10, labels=range(1, 11), duplicates="drop")
        d1_vol = df[df["decile"] == 1]["rv_next"].mean() if 1 in df["decile"].values else np.nan
        d10_vol = df[df["decile"] == 10]["rv_next"].mean() if 10 in df["decile"].values else np.nan
        mid_vol = df[(df["decile"] >= 4) & (df["decile"] <= 7)]["rv_next"].mean()

        print(f"    {signal_name}:")
        print(f"      Quintile vol: Q1(losers)={q1_vol:.3f}, Q3(mid)={q_means.iloc[2]:.3f}, "
              f"Q5(winners)={q5_vol:.3f}")
        print(f"      Q1 vs Q5: t={t_q1q5:.2f}, p={p_q1q5:.4f}")
        if not np.isnan(d1_vol):
            print(f"      Decile: D1={d1_vol:.3f}, Mid={mid_vol:.3f}, D10={d10_vol:.3f}")

        asset_q[signal_name] = {
            "q1_vol": round(q1_vol, 4),
            "q3_vol": round(q_means.iloc[2], 4),
            "q5_vol": round(q5_vol, 4),
            "t_q1q5": round(t_q1q5, 2),
            "p_q1q5": round(p_q1q5, 4),
            "d1_vol": round(d1_vol, 4) if not np.isnan(d1_vol) else None,
            "d10_vol": round(d10_vol, 4) if not np.isnan(d10_vol) else None,
            "mid_vol": round(mid_vol, 4),
        }

    quintile_results[asset] = asset_q

# ============================================================
# 5. Test 3: Partial correlation controlling for VIX
# ============================================================
print("\n\n[5/7] Test 3: Partial correlation |MOM| → rv_next | VIX...")
print("-" * 70)

def partial_corr(x, y, z):
    """Partial correlation of x and y controlling for z."""
    # Regress x on z
    slope_xz, intercept_xz, _, _, _ = stats.linregress(z, x)
    resid_x = x - (slope_xz * z + intercept_xz)

    # Regress y on z
    slope_yz, intercept_yz, _, _, _ = stats.linregress(z, y)
    resid_y = y - (slope_yz * z + intercept_yz)

    # Correlation of residuals
    r, p = stats.pearsonr(resid_x, resid_y)
    n = len(x)
    t_stat = r * np.sqrt(n - 3) / np.sqrt(1 - r**2) if abs(r) < 1 else 0
    return r, t_stat, p

partial_results = {}

for asset in ASSETS:
    df = monthly_data[asset].copy()
    df["rv_next"] = df["rv"].shift(-1)
    df = df.dropna()

    print(f"\n  {asset} (N={len(df)}):")
    asset_pr = {}

    for signal_name in ["mom_12_1", "mom_6_1", "mom_1"]:
        x = df[signal_name].abs().values
        y = df["rv_next"].values
        z = df["vix"].values

        r_raw, _ = stats.pearsonr(x, y)
        r_partial, t_partial, p_partial = partial_corr(x, y, z)

        # Also: VIX correlation with rv_next (benchmark)
        r_vix, _ = stats.pearsonr(z, y)

        print(f"    |{signal_name}| → rv_next:")
        print(f"      Raw r={r_raw:.3f} | Partial r|VIX = {r_partial:.3f} "
              f"(t={t_partial:.2f}, p={p_partial:.4f})")
        print(f"      (VIX → rv_next: r={r_vix:.3f})")

        asset_pr[signal_name] = {
            "r_raw": round(r_raw, 4),
            "r_partial_vix": round(r_partial, 4),
            "t_partial": round(t_partial, 2),
            "p_partial": round(p_partial, 4),
            "r_vix_rvnext": round(r_vix, 4),
        }

    partial_results[asset] = asset_pr

# ============================================================
# 6. Test 4: Momentum crash indicator — does extreme past
#    return predict vol spikes?
# ============================================================
print("\n\n[6/7] Test 4: Momentum crash indicator...")
print("-" * 70)

crash_results = {}

for asset in ASSETS:
    df = monthly_data[asset].copy()
    df["rv_next"] = df["rv"].shift(-1)
    df = df.dropna()

    print(f"\n  {asset} (N={len(df)}):")

    # Define vol spike as rv_next > 75th percentile
    vol_spike_threshold = df["rv_next"].quantile(0.75)
    df["vol_spike"] = (df["rv_next"] > vol_spike_threshold).astype(int)

    asset_crash = {}

    for signal_name in ["mom_12_1", "mom_6_1", "mom_1"]:
        # Extreme momentum: top 10% (big winners) or bottom 10% (big losers)
        p90 = df[signal_name].quantile(0.90)
        p10 = df[signal_name].quantile(0.10)

        extreme_up = df[df[signal_name] > p90]
        extreme_down = df[df[signal_name] < p10]
        middle = df[(df[signal_name] >= p10) & (df[signal_name] <= p90)]

        # Vol spike probability in each group
        spike_prob_up = extreme_up["vol_spike"].mean()
        spike_prob_down = extreme_down["vol_spike"].mean()
        spike_prob_mid = middle["vol_spike"].mean()
        spike_prob_base = df["vol_spike"].mean()

        # Chi-squared test: extreme vs middle
        # Combine extreme up and extreme down
        extreme_all = pd.concat([extreme_up, extreme_down])

        if len(extreme_all) > 5 and len(middle) > 5:
            contingency = pd.crosstab(
                pd.Series(["extreme"] * len(extreme_all) + ["middle"] * len(middle)),
                pd.Series(list(extreme_all["vol_spike"].values) + list(middle["vol_spike"].values))
            )
            chi2, p_chi2, _, _ = stats.chi2_contingency(contingency)
        else:
            chi2, p_chi2 = np.nan, np.nan

        # Mean next-month vol by group
        vol_up = extreme_up["rv_next"].mean()
        vol_down = extreme_down["rv_next"].mean()
        vol_mid = middle["rv_next"].mean()

        print(f"    {signal_name}:")
        print(f"      Vol spike prob: Winners(>p90)={spike_prob_up:.2%}, "
              f"Losers(<p10)={spike_prob_down:.2%}, Middle={spike_prob_mid:.2%} "
              f"(base={spike_prob_base:.2%})")
        print(f"      Mean rv_next: Winners={vol_up:.3f}, Losers={vol_down:.3f}, "
              f"Middle={vol_mid:.3f}")
        if not np.isnan(chi2):
            print(f"      Chi2(extreme vs mid): {chi2:.2f}, p={p_chi2:.4f}")

        asset_crash[signal_name] = {
            "spike_prob_winners": round(spike_prob_up, 4),
            "spike_prob_losers": round(spike_prob_down, 4),
            "spike_prob_middle": round(spike_prob_mid, 4),
            "spike_prob_base": round(spike_prob_base, 4),
            "mean_rv_winners": round(vol_up, 4),
            "mean_rv_losers": round(vol_down, 4),
            "mean_rv_middle": round(vol_mid, 4),
            "chi2": round(chi2, 2) if not np.isnan(chi2) else None,
            "p_chi2": round(p_chi2, 4) if not np.isnan(p_chi2) else None,
        }

    crash_results[asset] = asset_crash

# ============================================================
# 7. Test 5: VT with momentum overlay (OOS backtest)
# ============================================================
print("\n\n[7/7] Test 5: VT with momentum overlay (OOS 2023-2024)...")
print("-" * 70)

def compute_vt_backtest(daily_ret, monthly_mom, vix_series, oos_start, oos_end):
    """
    Backtest VT with and without momentum overlay.
    VT base: 12/VIX weight.
    Momentum overlay: reduce exposure when |MOM_12_1| is extreme.
    """
    # Monthly VIX
    vix_monthly = vix_series.resample("ME").last()

    # Align all monthly data
    common_idx = monthly_mom.dropna().index
    common_idx = common_idx.intersection(vix_monthly.dropna().index)

    # Filter to OOS
    oos_months = common_idx[(common_idx >= oos_start) & (common_idx < oos_end)]

    if len(oos_months) < 6:
        return None

    results = {"n_months": len(oos_months)}

    # For each month, compute monthly return with VT weight
    base_rets = []
    overlay_rets = []
    bh_rets = []

    for i, month_end in enumerate(oos_months):
        # VIX at month end → weight for NEXT month
        vix_val = vix_monthly.loc[month_end] if month_end in vix_monthly.index else None
        if vix_val is None or np.isnan(vix_val):
            continue

        # Base VT weight
        w_base = min(12.0 / vix_val, 1.0)

        # Momentum overlay: reduce if extreme
        mom_val = monthly_mom.loc[month_end] if month_end in monthly_mom.index else None
        if mom_val is None or np.isnan(mom_val):
            w_overlay = w_base
        else:
            # Full sample percentiles for thresholds
            all_mom = monthly_mom.loc[monthly_mom.index <= month_end].dropna()
            p90 = all_mom.quantile(0.90)
            p10 = all_mom.quantile(0.10)

            if mom_val > p90 or mom_val < p10:
                # Extreme momentum → reduce exposure by 50%
                w_overlay = w_base * 0.5
            else:
                w_overlay = w_base

        # Next month return
        next_month_start = month_end + pd.Timedelta(days=1)
        # Find next month end
        if i + 1 < len(oos_months):
            next_month_end = oos_months[i + 1]
        else:
            # Last month: use data up to OOS end
            next_month_end = pd.Timestamp(oos_end)

        # Daily returns in next month
        mask = (daily_ret.index > month_end) & (daily_ret.index <= next_month_end)
        month_daily = daily_ret[mask]

        if len(month_daily) < 5:
            continue

        # Compound monthly return
        bh_ret = (1 + month_daily).prod() - 1
        base_ret = w_base * bh_ret  # Simplified (no risk-free for excess)
        overlay_ret = w_overlay * bh_ret

        bh_rets.append(bh_ret)
        base_rets.append(base_ret)
        overlay_rets.append(overlay_ret)

    if len(bh_rets) < 6:
        return None

    bh_rets = np.array(bh_rets)
    base_rets = np.array(base_rets)
    overlay_rets = np.array(overlay_rets)

    # Sharpe ratios (monthly → annualized)
    sharpe_bh = np.mean(bh_rets) / np.std(bh_rets, ddof=1) * np.sqrt(12)
    sharpe_base = np.mean(base_rets) / np.std(base_rets, ddof=1) * np.sqrt(12)
    sharpe_overlay = np.mean(overlay_rets) / np.std(overlay_rets, ddof=1) * np.sqrt(12)

    # MDD
    def max_dd(rets):
        cum = np.cumprod(1 + rets)
        peak = np.maximum.accumulate(cum)
        dd = cum / peak - 1
        return dd.min()

    mdd_bh = max_dd(bh_rets)
    mdd_base = max_dd(base_rets)
    mdd_overlay = max_dd(overlay_rets)

    # DM test: overlay vs base
    d = overlay_rets - base_rets
    if np.std(d) > 0:
        dm_t = np.mean(d) / (np.std(d, ddof=1) / np.sqrt(len(d)))
        dm_p = 2 * (1 - stats.t.cdf(abs(dm_t), len(d) - 1))
    else:
        dm_t, dm_p = 0, 1.0

    results.update({
        "sharpe_bh": round(sharpe_bh, 3),
        "sharpe_vt_base": round(sharpe_base, 3),
        "sharpe_vt_overlay": round(sharpe_overlay, 3),
        "mdd_bh": round(mdd_bh, 4),
        "mdd_vt_base": round(mdd_base, 4),
        "mdd_vt_overlay": round(mdd_overlay, 4),
        "dm_t_overlay_vs_base": round(dm_t, 2),
        "dm_p": round(dm_p, 4),
        "n_months_used": len(bh_rets),
    })

    return results

vt_overlay_results = {}

for asset in ASSETS:
    df = monthly_data[asset]
    mom_12_1 = df["mom_12_1"]

    bt = compute_vt_backtest(
        returns[asset], mom_12_1, vix, OOS_START, OOS_END
    )

    if bt is not None:
        print(f"\n  {asset} ({bt['n_months_used']} months):")
        print(f"    B&H:         Sharpe={bt['sharpe_bh']:.3f}, MDD={bt['mdd_bh']:.1%}")
        print(f"    VT(12/VIX):  Sharpe={bt['sharpe_vt_base']:.3f}, MDD={bt['mdd_vt_base']:.1%}")
        print(f"    VT+MOM:      Sharpe={bt['sharpe_vt_overlay']:.3f}, MDD={bt['mdd_vt_overlay']:.1%}")
        print(f"    Overlay vs Base: DM t={bt['dm_t_overlay_vs_base']:.2f}, p={bt['dm_p']:.4f}")
        vt_overlay_results[asset] = bt
    else:
        print(f"\n  {asset}: Insufficient OOS data")
        vt_overlay_results[asset] = {"error": "insufficient data"}

# ============================================================
# 8. Cross-asset summary and Harvey threshold check
# ============================================================
print("\n\n" + "=" * 70)
print("CROSS-ASSET SUMMARY")
print("=" * 70)

# Summary: which momentum signals predict vol across assets?
print("\n--- |MOM| → next-month RV correlation (IS) ---")
print(f"{'Asset':<6} {'|MOM_12_1|':<16} {'|MOM_6_1|':<16} {'|MOM_1|':<16}")
for asset in ASSETS:
    r12 = results[asset]["mom_12_1_r_is"]
    r6 = results[asset]["mom_6_1_r_is"]
    r1 = results[asset]["mom_1_r_is"]
    print(f"{asset:<6} r={r12:+.3f}         r={r6:+.3f}         r={r1:+.3f}")

print("\n--- |MOM| → next-month RV correlation (OOS 2023-2024) ---")
print(f"{'Asset':<6} {'|MOM_12_1|':<16} {'|MOM_6_1|':<16} {'|MOM_1|':<16}")
for asset in ASSETS:
    r12 = results[asset]["mom_12_1_r_oos"]
    r6 = results[asset]["mom_6_1_r_oos"]
    r1 = results[asset]["mom_1_r_oos"]
    print(f"{asset:<6} r={r12:+.3f}         r={r6:+.3f}         r={r1:+.3f}")

print("\n--- Partial r|VIX (full sample) ---")
print(f"{'Asset':<6} {'|MOM_12_1|':<20} {'|MOM_6_1|':<20} {'|MOM_1|':<20}")
for asset in ASSETS:
    for signal_name in ["mom_12_1", "mom_6_1", "mom_1"]:
        pr = partial_results[asset][signal_name]
        if signal_name == "mom_12_1":
            line = f"{asset:<6} "
        else:
            line = "       "
        # Actually print all on one line per asset
    pr12 = partial_results[asset]["mom_12_1"]
    pr6 = partial_results[asset]["mom_6_1"]
    pr1 = partial_results[asset]["mom_1"]
    print(f"{asset:<6} r={pr12['r_partial_vix']:+.3f} (t={pr12['t_partial']:.1f})  "
          f"r={pr6['r_partial_vix']:+.3f} (t={pr6['t_partial']:.1f})  "
          f"r={pr1['r_partial_vix']:+.3f} (t={pr1['t_partial']:.1f})")

print("\n--- Momentum Crash Indicator (vol spike probability) ---")
print(f"{'Asset':<6} {'Signal':<10} {'Winners':<10} {'Losers':<10} {'Middle':<10} {'Chi2 p':<10}")
for asset in ASSETS:
    for sig in ["mom_12_1"]:  # Focus on main signal
        cr = crash_results[asset][sig]
        p_str = f"{cr['p_chi2']:.4f}" if cr['p_chi2'] is not None else "N/A"
        print(f"{asset:<6} {sig:<10} {cr['spike_prob_winners']:.1%}      "
              f"{cr['spike_prob_losers']:.1%}      {cr['spike_prob_middle']:.1%}      "
              f"{p_str}")

print("\n--- VT Momentum Overlay (OOS 2023-2024) ---")
print(f"{'Asset':<6} {'VT Base':<12} {'VT+MOM':<12} {'Delta':<10} {'DM t':<8}")
for asset in ASSETS:
    vt = vt_overlay_results[asset]
    if "error" not in vt:
        delta = vt["sharpe_vt_overlay"] - vt["sharpe_vt_base"]
        print(f"{asset:<6} Sh={vt['sharpe_vt_base']:.3f}    "
              f"Sh={vt['sharpe_vt_overlay']:.3f}    {delta:+.3f}     "
              f"t={vt['dm_t_overlay_vs_base']:.2f}")
    else:
        print(f"{asset:<6} {vt['error']}")

# ============================================================
# 9. Harvey threshold check
# ============================================================
print("\n\n--- Harvey (2017) Multiple Testing Check ---")
print("Threshold: |t| > 3.0 for new factor significance")

harvey_pass_count = 0
harvey_total = 0

for asset in ASSETS:
    for signal_name in ["mom_12_1", "mom_6_1", "mom_1"]:
        t_is = abs(results[asset][f"{signal_name}_t_is"])
        harvey_total += 1
        if t_is > 3.0:
            harvey_pass_count += 1
            print(f"  PASS: {asset} |{signal_name}| t={t_is:.2f}")

if harvey_pass_count == 0:
    print("  No signal passes Harvey threshold (|t|>3.0)")
print(f"\n  Score: {harvey_pass_count}/{harvey_total} pass Harvey threshold")

# ============================================================
# 10. Signed momentum test (not just absolute)
# ============================================================
print("\n\n--- Supplementary: Signed momentum → vol (asymmetry check) ---")

for asset in ASSETS:
    df = monthly_data[asset].copy()
    df["rv_next"] = df["rv"].shift(-1)
    df = df.dropna()

    # Separate positive and negative momentum
    pos = df[df["mom_12_1"] > 0]
    neg = df[df["mom_12_1"] < 0]

    # Correlation within each sign
    if len(pos) > 10 and len(neg) > 10:
        r_pos, p_pos = stats.pearsonr(pos["mom_12_1"].abs(), pos["rv_next"])
        r_neg, p_neg = stats.pearsonr(neg["mom_12_1"].abs(), neg["rv_next"])

        # Mean vol after positive vs negative momentum
        vol_after_pos = pos["rv_next"].mean()
        vol_after_neg = neg["rv_next"].mean()
        t_diff, p_diff = stats.ttest_ind(pos["rv_next"], neg["rv_next"])

        print(f"  {asset}: Vol after MOM>0: {vol_after_pos:.3f} (N={len(pos)}), "
              f"Vol after MOM<0: {vol_after_neg:.3f} (N={len(neg)}), "
              f"diff t={t_diff:.2f} p={p_diff:.4f}")

# ============================================================
# 11. Multiple regression: MOM + VIX → next-month vol
# ============================================================
print("\n\n--- Supplementary: OLS MOM + VIX → rv_next ---")

from numpy.linalg import lstsq as np_lstsq

for asset in ASSETS:
    df = monthly_data[asset].copy()
    df["rv_next"] = df["rv"].shift(-1)
    df = df.dropna()

    # Standardize
    for col in ["mom_12_1", "mom_6_1", "mom_1", "vix", "rv_next"]:
        df[f"{col}_z"] = (df[col] - df[col].mean()) / df[col].std()

    # Model: rv_next_z = b0 + b1*|mom_12_1_z| + b2*vix_z
    X = np.column_stack([
        np.ones(len(df)),
        df["mom_12_1_z"].abs().values,
        df["vix_z"].values,
    ])
    y = df["rv_next_z"].values

    beta, residuals, _, _ = np_lstsq(X, y, rcond=None)
    y_hat = X @ beta
    ss_res = np.sum((y - y_hat) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot

    # Standard errors
    n, k = X.shape
    mse = ss_res / (n - k)
    var_beta = mse * np.linalg.inv(X.T @ X).diagonal()
    se_beta = np.sqrt(var_beta)
    t_stats = beta / se_beta

    print(f"  {asset}: R²={r2:.3f}")
    print(f"    |MOM_12_1|: beta={beta[1]:.3f}, t={t_stats[1]:.2f}")
    print(f"    VIX:        beta={beta[2]:.3f}, t={t_stats[2]:.2f}")

# ============================================================
# 12. Final verdict
# ============================================================
print("\n\n" + "=" * 70)
print("K203 FINAL VERDICT")
print("=" * 70)

# Count significant results across assets
sig_count_is = 0
sig_count_oos = 0
sig_count_partial = 0
sig_count_crash = 0

for asset in ASSETS:
    for sig in ["mom_12_1", "mom_6_1", "mom_1"]:
        if abs(results[asset][f"{sig}_t_is"]) > 2.0:
            sig_count_is += 1
        if abs(results[asset][f"{sig}_t_oos"]) > 2.0:
            sig_count_oos += 1
        if abs(partial_results[asset][sig]["t_partial"]) > 2.0:
            sig_count_partial += 1

    cr = crash_results[asset]["mom_12_1"]
    if cr["p_chi2"] is not None and cr["p_chi2"] < 0.05:
        sig_count_crash += 1

total_tests = len(ASSETS) * 3

print(f"\n  Raw |MOM| → rv_next significant (IS):  {sig_count_is}/{total_tests}")
print(f"  Raw |MOM| → rv_next significant (OOS): {sig_count_oos}/{total_tests}")
print(f"  Partial |MOM| → rv_next | VIX:         {sig_count_partial}/{total_tests}")
print(f"  Momentum crash indicator (chi2 p<.05): {sig_count_crash}/{len(ASSETS)}")
print(f"  Harvey threshold passes:               {harvey_pass_count}/{total_tests}")

# VT overlay verdict
overlay_improvements = 0
for asset in ASSETS:
    vt = vt_overlay_results[asset]
    if "error" not in vt and vt["sharpe_vt_overlay"] > vt["sharpe_vt_base"]:
        overlay_improvements += 1

print(f"  VT overlay Sharpe improvements (OOS):  {overlay_improvements}/{len(ASSETS)}")

if harvey_pass_count == 0 and sig_count_partial < 3:
    print("\n  CONCLUSION: Momentum does NOT reliably predict future volatility")
    print("  beyond what VIX already captures. The VIX sufficient statistic")
    print("  finding (J3/J4/K1) extends to momentum-based signals.")
    verdict = "NULL"
elif harvey_pass_count > 0:
    print("\n  CONCLUSION: Some momentum signals show predictive power for vol,")
    print("  warranting further investigation.")
    verdict = "PROMISING"
else:
    print("\n  CONCLUSION: Weak evidence. Some signals significant at conventional")
    print("  levels but fail Harvey (2017) multiple testing correction.")
    verdict = "WEAK"

# ============================================================
# Save results
# ============================================================
output = {
    "experiment": "K203",
    "title": "Momentum Crash Risk and Volatility",
    "timestamp": datetime.now().isoformat(),
    "attribution": "[提出: 用戶, 執行: Claude]",
    "data": {
        "assets": ASSETS,
        "start": START,
        "end": END,
        "oos_start": OOS_START,
        "oos_end": OOS_END,
    },
    "test1_mom_vol_correlation": results,
    "test2_quintile_analysis": quintile_results,
    "test3_partial_corr_vix": partial_results,
    "test4_crash_indicator": crash_results,
    "test5_vt_overlay_oos": vt_overlay_results,
    "summary": {
        "sig_is": sig_count_is,
        "sig_oos": sig_count_oos,
        "sig_partial_vix": sig_count_partial,
        "sig_crash_chi2": sig_count_crash,
        "harvey_passes": harvey_pass_count,
        "vt_overlay_improvements": overlay_improvements,
        "total_tests": total_tests,
        "verdict": verdict,
    },
}

out_path = "experiments/k203/k203_momentum_crash_vol_results.json"
with open(out_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to {out_path}")
print("=" * 70)
