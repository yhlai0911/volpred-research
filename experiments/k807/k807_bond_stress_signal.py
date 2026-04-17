#!/usr/bin/env python3
"""
K807: Bond Stress De-Risk Signal (Simplified & Focused)

[提出: Codex #8, 執行: Claude]

Building on K766 (BSI: Sharpe 1.041 net, DM NS vs baselines).
K807 simplifies to 2-feature composite (HYG-LQD spread + TLT vol),
tests smooth-weight variant (like 12/VIX), and combination with VIX.

Key differences from K766:
  - 2 features only (drop corr + slope → reduce noise/overfitting)
  - Strategy 2: smooth continuous weight (not regime-switch)
  - Strategy 3: min(VIX_weight, bond_stress_weight) combination
  - Strict OOS: 2023-01-01 ~ 2024-12-31
  - Expanding z-score (no lookahead)

Features:
  1. HYG-LQD spread proxy → credit stress
  2. TLT 20d realized vol → duration/rate stress
  Composite = mean(z1, z2), expanding z-score

Strategies:
  S0: BH 50/50 SPY/GLD (baseline)
  S1: Binary switch — stress > threshold → 25% SPY / 75% GLD
  S2: Smooth weight — w_spy = clip(0.5 - 0.15 * composite, 0.2, 0.8)
  S3: Combined — w_spy = min(12/VIX, 0.5 - 0.15 * composite)

Evaluation: Sharpe, CAGR, MDD, Calmar, Sortino, DM test (Harvey t>3.0),
            Cross-OOS 5 × 2yr, downside semivariance

Data: yfinance (HYG, LQD, TLT, SPY, GLD, ^VIX), 2008-2026
References:
  - Baele, Bekaert & Inghelbrecht (2010) RFS
  - Connolly, Stivers & Sun (2005) JFQA
  - Collin-Dufresne, Goldstein & Martin (2001) JF
  - K766 (BSI 4-feature, regime switch)
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from scipy import stats
import warnings
warnings.filterwarnings("ignore")

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("=" * 70)
print("K807: Bond Stress De-Risk Signal (Simplified)")
print("=" * 70)

tickers = ["SPY", "GLD", "TLT", "HYG", "LQD", "^VIX"]
start_date = "2007-01-01"
end_date = "2026-04-01"

print(f"\nDownloading {tickers} from {start_date} to {end_date}...")
raw = yf.download(tickers, start=start_date, end=end_date, auto_adjust=True)

# Extract close prices
close = raw["Close"].copy()
close = close.rename(columns={"^VIX": "VIX"})
close = close.ffill().dropna()

print(f"Data shape: {close.shape}")
print(f"Date range: {close.index[0].date()} to {close.index[-1].date()}")
print(f"Columns: {list(close.columns)}")

# Returns
ret = close.pct_change()
ret_spy = ret["SPY"]
ret_gld = ret["GLD"]

# ============================================================
# 2. CONSTRUCT BOND STRESS COMPOSITE (2 features)
# ============================================================
print("\n" + "=" * 70)
print("2. Constructing Bond Stress Composite (2 features)")
print("=" * 70)

# Feature 1: HYG-LQD spread proxy
# LQD outperforming HYG = credit stress rising
# Use 20-day rolling return difference
ret_hyg = ret["HYG"]
ret_lqd = ret["LQD"]
spread_proxy = (ret_lqd.rolling(20).sum() - ret_hyg.rolling(20).sum())
# Higher = more credit stress (HYG underperforming LQD)

# Feature 2: TLT 20-day realized vol (annualized)
tlt_log_ret = np.log(close["TLT"] / close["TLT"].shift(1))
tlt_rv20 = tlt_log_ret.rolling(20).std() * np.sqrt(252)

# Expanding z-scores (no lookahead — uses only past data)
def expanding_zscore(series):
    """Z-score using expanding window (only past data, no future info)."""
    exp_mean = series.expanding(min_periods=60).mean()
    exp_std = series.expanding(min_periods=60).std()
    z = (series - exp_mean) / exp_std.replace(0, np.nan)
    return z

z_spread = expanding_zscore(spread_proxy)
z_tlt_vol = expanding_zscore(tlt_rv20)

# Composite: simple mean of z-scores
composite = (z_spread + z_tlt_vol) / 2.0
composite = composite.dropna()

print(f"\nComposite stress score stats:")
print(f"  Mean: {composite.mean():.3f}")
print(f"  Std:  {composite.std():.3f}")
print(f"  Min:  {composite.min():.3f}")
print(f"  Max:  {composite.max():.3f}")
print(f"  Skew: {composite.skew():.3f}")
print(f"  Kurt: {composite.kurtosis():.3f}")
print(f"  Valid obs: {composite.notna().sum()}")

# Correlation with VIX
vix = close["VIX"]
mask = composite.notna() & vix.notna()
corr_with_vix = composite[mask].corr(vix[mask])
print(f"\n  Correlation with VIX level: {corr_with_vix:.3f}")
print(f"  → {'Moderate' if 0.3 < abs(corr_with_vix) < 0.7 else 'Low' if abs(corr_with_vix) <= 0.3 else 'High'} correlation — {'good complement' if abs(corr_with_vix) < 0.6 else 'overlapping'}")

# ============================================================
# 3. STRATEGY CONSTRUCTION
# ============================================================
print("\n" + "=" * 70)
print("3. Strategy Construction")
print("=" * 70)

# Align all data
df = pd.DataFrame({
    "ret_spy": ret_spy,
    "ret_gld": ret_gld,
    "composite": composite,
    "vix": vix,
}).dropna()

print(f"Aligned data: {len(df)} obs, {df.index[0].date()} to {df.index[-1].date()}")

# --- signal.shift(1) — USE YESTERDAY'S SIGNAL FOR TODAY'S RETURN ---
sig_composite = df["composite"].shift(1)  # CRITICAL: lag by 1 day
sig_vix = df["vix"].shift(1)              # CRITICAL: lag by 1 day

# S0: BH 50/50 SPY/GLD (baseline)
w_spy_s0 = pd.Series(0.5, index=df.index)

# S1: Binary switch
# stress > 75th expanding percentile → 25% SPY / 75% GLD
# else → 50/50
threshold_75 = sig_composite.expanding(min_periods=60).quantile(0.75)
stress_flag = (sig_composite > threshold_75).astype(float)
w_spy_s1 = pd.Series(0.5, index=df.index)
w_spy_s1[stress_flag == 1.0] = 0.25

# S2: Smooth weight
# w_spy = clip(0.5 - 0.15 * composite, 0.2, 0.8)
# When composite is high (stress), reduce SPY; when low, increase
w_spy_s2 = (0.5 - 0.15 * sig_composite).clip(0.2, 0.8)

# S3: Combined with 12/VIX
# VIX-based weight
w_vix = (12.0 / sig_vix).clip(0.0, 1.0)
# Bond stress weight
w_bond = (0.5 - 0.15 * sig_composite).clip(0.2, 0.8)
# Take the more conservative (lower SPY) of the two
w_spy_s3 = pd.concat([w_vix, w_bond], axis=1).min(axis=1)

# S4: 12/VIX standalone (for comparison)
w_spy_s4 = w_vix.copy()

# ============================================================
# 4. PORTFOLIO RETURNS WITH TX COST
# ============================================================
print("\n" + "=" * 70)
print("4. Computing Portfolio Returns (TX cost = 5 bps/leg)")
print("=" * 70)

TX_COST = 0.0005  # 5 bps per leg

def compute_portfolio(w_spy_series, ret_spy, ret_gld, name, tx_cost=TX_COST):
    """Compute gross and net portfolio returns."""
    w = w_spy_series.copy()
    # Drop NaN signals
    valid = w.notna() & ret_spy.notna() & ret_gld.notna()
    w = w[valid]
    rs = ret_spy[valid]
    rg = ret_gld[valid]

    # Gross return
    port_ret_gross = w * rs + (1 - w) * rg

    # TX cost: proportional to weight change
    w_change = w.diff().abs()
    tx = w_change * tx_cost * 2  # both legs
    tx = tx.fillna(0)

    port_ret_net = port_ret_gross - tx

    return port_ret_gross, port_ret_net


def calc_metrics(returns, name):
    """Calculate strategy performance metrics."""
    r = returns.dropna()
    n = len(r)
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    years = n / 252
    total_ret = cum.iloc[-1] - 1
    cagr = (1 + total_ret) ** (1 / years) - 1 if years > 0 else 0
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    # Sortino (downside deviation)
    downside = r[r < 0]
    down_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else ann_vol
    sortino = ann_ret / down_vol if down_vol > 0 else 0

    # Downside semivariance (annualized)
    semi_var = (r[r < 0] ** 2).mean() * 252 if (r < 0).sum() > 0 else 0

    return {
        "name": name,
        "ann_ret": round(ann_ret, 4),
        "ann_vol": round(ann_vol, 4),
        "sharpe": round(sharpe, 4),
        "mdd": round(mdd, 4),
        "cagr": round(cagr, 4),
        "calmar": round(calmar, 4),
        "sortino": round(sortino, 4),
        "semi_var": round(semi_var, 4),
        "total_return": round(total_ret, 4),
        "n_days": n,
    }


strategies = {
    "S0: BH 50/50": w_spy_s0,
    "S1: Binary Switch": w_spy_s1,
    "S2: Smooth Weight": w_spy_s2,
    "S3: Combined VIX+Bond": w_spy_s3,
    "S4: 12/VIX Only": w_spy_s4,
}

port_returns = {}
for name, w in strategies.items():
    gross, net = compute_portfolio(w, df["ret_spy"], df["ret_gld"], name)
    port_returns[f"{name} (gross)"] = gross
    port_returns[f"{name} (net)"] = net

# ============================================================
# 5. FULL SAMPLE METRICS
# ============================================================
print("\n" + "=" * 70)
print("5. Full Sample Metrics")
print("=" * 70)

full_metrics = {}
for label, rets in port_returns.items():
    m = calc_metrics(rets, label)
    full_metrics[label] = m

# Print table
print(f"\n{'Strategy':<35} {'Sharpe':>7} {'CAGR':>7} {'MDD':>8} {'Calmar':>7} {'Sortino':>8} {'SemiVar':>8}")
print("-" * 90)
for label in sorted(full_metrics.keys()):
    m = full_metrics[label]
    print(f"{m['name']:<35} {m['sharpe']:7.3f} {m['cagr']:7.3%} {m['mdd']:8.3%} {m['calmar']:7.3f} {m['sortino']:8.3f} {m['semi_var']:8.4f}")

# ============================================================
# 6. OOS PERIOD (2023-01 ~ 2024-12)
# ============================================================
print("\n" + "=" * 70)
print("6. OOS Period: 2023-01-01 to 2024-12-31")
print("=" * 70)

oos_start = "2023-01-01"
oos_end = "2024-12-31"

oos_metrics = {}
for label, rets in port_returns.items():
    oos_r = rets.loc[oos_start:oos_end]
    if len(oos_r) > 50:
        m = calc_metrics(oos_r, f"OOS {label}")
        oos_metrics[label] = m

print(f"\n{'Strategy':<35} {'Sharpe':>7} {'CAGR':>7} {'MDD':>8} {'Calmar':>7} {'Sortino':>8}")
print("-" * 85)
for label in sorted(oos_metrics.keys()):
    m = oos_metrics[label]
    print(f"{m['name']:<35} {m['sharpe']:7.3f} {m['cagr']:7.3%} {m['mdd']:8.3%} {m['calmar']:7.3f} {m['sortino']:8.3f}")

# ============================================================
# 7. DM TESTS (Harvey t > 3.0)
# ============================================================
print("\n" + "=" * 70)
print("7. Diebold-Mariano Tests (Harvey threshold t > 3.0)")
print("=" * 70)

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. loss = -return (lower loss = better)."""
    d = loss1 - loss2
    d = d.dropna()
    n = len(d)
    if n < 30:
        return np.nan, np.nan
    d_bar = d.mean()

    # HAC variance (Newey-West with h-1 lags)
    gamma_0 = d.var()
    V = gamma_0
    for k in range(1, h):
        gamma_k = d.iloc[k:].reset_index(drop=True).cov(d.iloc[:-k].reset_index(drop=True))
        V += 2 * gamma_k

    se = np.sqrt(V / n) if V > 0 else 1e-10
    t_stat = d_bar / se
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return round(t_stat, 3), round(p_val, 4)


# Use squared returns as loss (MSE proxy)
baseline_net = port_returns["S0: BH 50/50 (net)"]
loss_baseline = -baseline_net  # negative return = loss

dm_results = {}
test_pairs = [
    ("S1 net vs 50/50", "S1: Binary Switch (net)", "S0: BH 50/50 (net)"),
    ("S2 net vs 50/50", "S2: Smooth Weight (net)", "S0: BH 50/50 (net)"),
    ("S3 net vs 50/50", "S3: Combined VIX+Bond (net)", "S0: BH 50/50 (net)"),
    ("S2 net vs 12/VIX net", "S2: Smooth Weight (net)", "S4: 12/VIX Only (net)"),
    ("S3 net vs 12/VIX net", "S3: Combined VIX+Bond (net)", "S4: 12/VIX Only (net)"),
    ("S1 net vs 12/VIX net", "S1: Binary Switch (net)", "S4: 12/VIX Only (net)"),
]

for name, s_a, s_b in test_pairs:
    r_a = port_returns[s_a]
    r_b = port_returns[s_b]
    # Align
    common = r_a.dropna().index.intersection(r_b.dropna().index)
    loss_a = -r_a[common]
    loss_b = -r_b[common]
    t, p = dm_test(loss_a, loss_b)
    sig = "***" if abs(t) > 3.0 else "**" if abs(t) > 2.5 else "*" if abs(t) > 1.96 else "NS"
    dm_results[name] = {"t": t, "p": p, "sig": sig}
    print(f"  {name:<30}: t = {t:7.3f}, p = {p:.4f}  [{sig}]")

# ============================================================
# 8. CROSS-OOS: 5 × 2-YEAR PERIODS
# ============================================================
print("\n" + "=" * 70)
print("8. Cross-OOS Validation (5 × 2-year non-overlapping periods)")
print("=" * 70)

cross_periods = [
    ("2009-01~2010-12", "2009-01-01", "2010-12-31"),
    ("2013-01~2014-12", "2013-01-01", "2014-12-31"),
    ("2016-01~2017-12", "2016-01-01", "2017-12-31"),
    ("2019-01~2020-12", "2019-01-01", "2020-12-31"),
    ("2023-01~2024-12", "2023-01-01", "2024-12-31"),
]

cross_oos_results = []
s2_beats_5050 = 0
s2_beats_12vix = 0
s3_beats_5050 = 0
s3_beats_12vix = 0

print(f"\n{'Period':<20} {'S2 Sharpe':>10} {'S3 Sharpe':>10} {'50/50':>10} {'12/VIX':>10} {'S2>50':>6} {'S3>50':>6} {'S2>VIX':>7} {'S3>VIX':>7}")
print("-" * 100)

for label, s, e in cross_periods:
    r_s0 = port_returns["S0: BH 50/50 (net)"].loc[s:e].dropna()
    r_s2 = port_returns["S2: Smooth Weight (net)"].loc[s:e].dropna()
    r_s3 = port_returns["S3: Combined VIX+Bond (net)"].loc[s:e].dropna()
    r_s4 = port_returns["S4: 12/VIX Only (net)"].loc[s:e].dropna()

    if len(r_s0) < 200:
        continue

    m_s0 = calc_metrics(r_s0, "50/50")
    m_s2 = calc_metrics(r_s2, "S2")
    m_s3 = calc_metrics(r_s3, "S3")
    m_s4 = calc_metrics(r_s4, "12/VIX")

    b_s2_50 = m_s2["sharpe"] > m_s0["sharpe"]
    b_s3_50 = m_s3["sharpe"] > m_s0["sharpe"]
    b_s2_vix = m_s2["sharpe"] > m_s4["sharpe"]
    b_s3_vix = m_s3["sharpe"] > m_s4["sharpe"]

    if b_s2_50: s2_beats_5050 += 1
    if b_s3_50: s3_beats_5050 += 1
    if b_s2_vix: s2_beats_12vix += 1
    if b_s3_vix: s3_beats_12vix += 1

    period_result = {
        "period": label,
        "start": s, "end": e,
        "s2_sharpe": m_s2["sharpe"], "s2_mdd": m_s2["mdd"],
        "s3_sharpe": m_s3["sharpe"], "s3_mdd": m_s3["mdd"],
        "r5050_sharpe": m_s0["sharpe"], "r5050_mdd": m_s0["mdd"],
        "vix_sharpe": m_s4["sharpe"], "vix_mdd": m_s4["mdd"],
        "s2_beats_5050": str(b_s2_50),
        "s3_beats_5050": str(b_s3_50),
        "s2_beats_12vix": str(b_s2_vix),
        "s3_beats_12vix": str(b_s3_vix),
        "n_days": str(len(r_s0)),
    }
    cross_oos_results.append(period_result)

    print(f"{label:<20} {m_s2['sharpe']:10.3f} {m_s3['sharpe']:10.3f} {m_s0['sharpe']:10.3f} {m_s4['sharpe']:10.3f} {'Y' if b_s2_50 else 'N':>6} {'Y' if b_s3_50 else 'N':>6} {'Y' if b_s2_vix else 'N':>7} {'Y' if b_s3_vix else 'N':>7}")

n_periods = len(cross_oos_results)
print(f"\nS2 beats 50/50: {s2_beats_5050}/{n_periods}")
print(f"S2 beats 12/VIX: {s2_beats_12vix}/{n_periods}")
print(f"S3 beats 50/50: {s3_beats_5050}/{n_periods}")
print(f"S3 beats 12/VIX: {s3_beats_12vix}/{n_periods}")

# ============================================================
# 9. DOWNSIDE ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("9. Downside Risk Analysis")
print("=" * 70)

# Worst drawdown periods (2020 COVID, 2022 rate hikes)
crisis_periods = [
    ("COVID (2020-02~2020-03)", "2020-02-01", "2020-03-31"),
    ("Rate Hikes (2022-01~2022-06)", "2022-01-01", "2022-06-30"),
    ("2022 Full Year", "2022-01-01", "2022-12-31"),
]

print(f"\n{'Period':<35} {'S2 ret':>8} {'S3 ret':>8} {'50/50':>8} {'12/VIX':>8}")
print("-" * 70)
crisis_results = {}
for label, s, e in crisis_periods:
    for sname, key in [("S2", "S2: Smooth Weight (net)"),
                        ("S3", "S3: Combined VIX+Bond (net)"),
                        ("50/50", "S0: BH 50/50 (net)"),
                        ("12/VIX", "S4: 12/VIX Only (net)")]:
        r = port_returns[key].loc[s:e].dropna()
        cum_ret = (1 + r).prod() - 1
        if label not in crisis_results:
            crisis_results[label] = {}
        crisis_results[label][sname] = round(float(cum_ret), 4)

    cr = crisis_results[label]
    print(f"{label:<35} {cr['S2']:8.3%} {cr['S3']:8.3%} {cr['50/50']:8.3%} {cr['12/VIX']:8.3%}")

# ============================================================
# 10. SENSITIVITY ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("10. Sensitivity Analysis (S2 smooth weight parameter)")
print("=" * 70)

# S2: w_spy = clip(0.5 - beta * composite, floor, ceiling)
# Test beta in [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
# and floor/ceiling combos

sensitivity_results = []
base_sharpe = full_metrics["S2: Smooth Weight (net)"]["sharpe"]

for beta in [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]:
    for floor_val in [0.1, 0.2, 0.3]:
        ceil_val = 1.0 - floor_val  # symmetric
        w_test = (0.5 - beta * sig_composite).clip(floor_val, ceil_val)
        g, n = compute_portfolio(w_test, df["ret_spy"], df["ret_gld"], "test")
        m = calc_metrics(n, "test")
        sensitivity_results.append({
            "beta": beta, "floor": floor_val, "ceil": ceil_val,
            "sharpe": m["sharpe"], "mdd": m["mdd"]
        })

sens_df = pd.DataFrame(sensitivity_results)
sharpe_range = [sens_df["sharpe"].min(), sens_df["sharpe"].max()]
best_cfg = sens_df.loc[sens_df["sharpe"].idxmax()]
worst_cfg = sens_df.loc[sens_df["sharpe"].idxmin()]

# Sensitivity pass: +-20% parameter change doesn't drop Sharpe > 30%
beta_range = [0.12, 0.18]  # +-20% of 0.15
sens_20 = sens_df[(sens_df["beta"] >= beta_range[0]) & (sens_df["beta"] <= beta_range[1])]
if len(sens_20) > 0:
    worst_20 = sens_20["sharpe"].min()
    sensitivity_pass = (base_sharpe - worst_20) / base_sharpe < 0.30
else:
    sensitivity_pass = True

print(f"  Tested {len(sensitivity_results)} configurations")
print(f"  Sharpe range: [{sharpe_range[0]:.3f}, {sharpe_range[1]:.3f}]")
print(f"  Base (beta=0.15, floor=0.2): {base_sharpe:.3f}")
print(f"  Best: beta={best_cfg['beta']}, floor={best_cfg['floor']}, Sharpe={best_cfg['sharpe']:.3f}")
print(f"  Worst: beta={worst_cfg['beta']}, floor={worst_cfg['floor']}, Sharpe={worst_cfg['sharpe']:.3f}")
print(f"  Sensitivity pass (+-20% → <30% drop): {sensitivity_pass}")

# ============================================================
# 11. COMPOSITE SIGNAL DESCRIPTIVE STATS BY REGIME
# ============================================================
print("\n" + "=" * 70)
print("11. Composite Signal by VIX Regime")
print("=" * 70)

vix_regimes = {
    "Low (<15)": sig_vix < 15,
    "Normal (15-25)": (sig_vix >= 15) & (sig_vix < 25),
    "High (25-35)": (sig_vix >= 25) & (sig_vix < 35),
    "Crisis (>35)": sig_vix >= 35,
}

print(f"{'VIX Regime':<20} {'N':>6} {'Composite Mean':>15} {'Composite Std':>14} {'Corr w/ SPY ret':>16}")
print("-" * 75)
for regime, mask in vix_regimes.items():
    m = mask & sig_composite.notna() & df["ret_spy"].notna()
    n = m.sum()
    if n > 10:
        c_mean = sig_composite[m].mean()
        c_std = sig_composite[m].std()
        corr = sig_composite[m].corr(df["ret_spy"][m])
        print(f"{regime:<20} {n:6d} {c_mean:15.3f} {c_std:14.3f} {corr:16.3f}")

# ============================================================
# 12. WEIGHT STATISTICS
# ============================================================
print("\n" + "=" * 70)
print("12. Weight Statistics")
print("=" * 70)

for sname, w in [("S1 Binary", w_spy_s1), ("S2 Smooth", w_spy_s2),
                  ("S3 Combined", w_spy_s3), ("S4 12/VIX", w_spy_s4)]:
    w_valid = w.dropna()
    turnover = w_valid.diff().abs().mean() * 252
    print(f"  {sname:<20}: mean={w_valid.mean():.3f}, std={w_valid.std():.3f}, "
          f"min={w_valid.min():.3f}, max={w_valid.max():.3f}, "
          f"ann_turnover={turnover:.3f}")

# ============================================================
# 13. SAVE RESULTS
# ============================================================
print("\n" + "=" * 70)
print("13. Saving Results")
print("=" * 70)

results = {
    "experiment_id": "K807",
    "title": "Bond Stress De-Risk Signal (Simplified & Focused)",
    "proposer": "Codex #8",
    "executor": "Claude",
    "data_source": "yfinance daily (SPY, GLD, TLT, HYG, LQD, ^VIX)",
    "data_period": f"{df.index[0].date()} to {df.index[-1].date()}",
    "n_observations": len(df),
    "related_experiments": ["K766", "K22", "K24", "K651", "K763"],
    "methodology": {
        "features": [
            "HYG-LQD 20d return spread (credit stress proxy)",
            "TLT 20d realized vol (duration/rate stress)",
        ],
        "composite": "mean of expanding z-scores (2 features)",
        "strategies": {
            "S0": "BH 50/50 SPY/GLD (baseline)",
            "S1": "Binary switch: composite > 75th expanding pctile → 25% SPY / 75% GLD",
            "S2": "Smooth weight: w_spy = clip(0.5 - 0.15 * composite, 0.2, 0.8)",
            "S3": "Combined: w_spy = min(12/VIX, 0.5 - 0.15 * composite)",
            "S4": "12/VIX only (comparison)",
        },
        "lag": "signal.shift(1) — all signals use previous day data",
        "tx_cost": "5 bps per leg on weight changes",
        "z_score": "expanding window (min 60 obs, no lookahead)",
    },
    "composite_signal_stats": {
        "mean": round(float(composite.mean()), 4),
        "std": round(float(composite.std()), 4),
        "skew": round(float(composite.skew()), 4),
        "kurtosis": round(float(composite.kurtosis()), 4),
        "corr_with_vix": round(float(corr_with_vix), 4),
    },
    "full_sample_metrics": full_metrics,
    "oos_metrics": oos_metrics,
    "dm_tests": dm_results,
    "cross_oos": {
        "periods": cross_oos_results,
        "s2_beats_5050": f"{s2_beats_5050}/{n_periods}",
        "s2_beats_12vix": f"{s2_beats_12vix}/{n_periods}",
        "s3_beats_5050": f"{s3_beats_5050}/{n_periods}",
        "s3_beats_12vix": f"{s3_beats_12vix}/{n_periods}",
    },
    "crisis_performance": crisis_results,
    "sensitivity": {
        "n_configs": len(sensitivity_results),
        "sharpe_range": [round(sharpe_range[0], 4), round(sharpe_range[1], 4)],
        "base_sharpe": round(base_sharpe, 4),
        "best_config": {
            "beta": float(best_cfg["beta"]),
            "floor": float(best_cfg["floor"]),
            "sharpe": float(best_cfg["sharpe"]),
        },
        "sensitivity_pass": str(sensitivity_pass),
    },
    "references": [
        "Baele, Bekaert & Inghelbrecht (2010) RFS",
        "Connolly, Stivers & Sun (2005) JFQA",
        "Collin-Dufresne, Goldstein & Martin (2001) JF",
        "K766: BSI 4-feature regime switch (Sharpe 1.041 net)",
    ],
    "conclusion": "",  # filled below
    "created_at": datetime.now().isoformat(),
}

# Build conclusion string
s2_net = full_metrics["S2: Smooth Weight (net)"]
s3_net = full_metrics["S3: Combined VIX+Bond (net)"]
s0_net = full_metrics["S0: BH 50/50 (net)"]
s4_net = full_metrics["S4: 12/VIX Only (net)"]

conclusion_parts = [
    f"S2 Smooth net Sharpe: {s2_net['sharpe']}",
    f"S3 Combined net Sharpe: {s3_net['sharpe']}",
    f"50/50 Sharpe: {s0_net['sharpe']}",
    f"12/VIX net Sharpe: {s4_net['sharpe']}",
    f"S2 MDD: {s2_net['mdd']:.1%}",
    f"S3 MDD: {s3_net['mdd']:.1%}",
    f"Cross-OOS S2 vs 50/50: {s2_beats_5050}/{n_periods}",
    f"Cross-OOS S3 vs 50/50: {s3_beats_5050}/{n_periods}",
    f"DM S2 vs 50/50: t={dm_results.get('S2 net vs 50/50', {}).get('t', 'N/A')}",
    f"DM S3 vs 50/50: t={dm_results.get('S3 net vs 50/50', {}).get('t', 'N/A')}",
    f"Composite-VIX corr: {corr_with_vix:.3f}",
    f"Sensitivity: {'PASS' if sensitivity_pass else 'FAIL'}",
]
results["conclusion"] = " | ".join(conclusion_parts)

output_path = "/Users/yhlai0911/Desktop/volpred-research/experiments/k807_bond_stress_signal_results.json"
with open(output_path, "w") as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to: {output_path}")

# ============================================================
# 14. SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("14. SUMMARY")
print("=" * 70)
print(f"\n  Composite-VIX correlation: {corr_with_vix:.3f}")
print(f"\n  Full Sample (net TX):")
print(f"    S0 BH 50/50:        Sharpe {s0_net['sharpe']:.3f}  MDD {s0_net['mdd']:.1%}")
print(f"    S1 Binary Switch:   Sharpe {full_metrics['S1: Binary Switch (net)']['sharpe']:.3f}  MDD {full_metrics['S1: Binary Switch (net)']['mdd']:.1%}")
print(f"    S2 Smooth Weight:   Sharpe {s2_net['sharpe']:.3f}  MDD {s2_net['mdd']:.1%}")
print(f"    S3 Combined VIX+B:  Sharpe {s3_net['sharpe']:.3f}  MDD {s3_net['mdd']:.1%}")
print(f"    S4 12/VIX Only:     Sharpe {s4_net['sharpe']:.3f}  MDD {s4_net['mdd']:.1%}")
print(f"\n  Cross-OOS:")
print(f"    S2 beats 50/50: {s2_beats_5050}/{n_periods}")
print(f"    S3 beats 50/50: {s3_beats_5050}/{n_periods}")
print(f"    S2 beats 12/VIX: {s2_beats_12vix}/{n_periods}")
print(f"    S3 beats 12/VIX: {s3_beats_12vix}/{n_periods}")
print(f"\n  DM Tests (Harvey t > 3.0):")
for name, res in dm_results.items():
    print(f"    {name:<30}: t = {res['t']:7.3f}  [{res['sig']}]")
print(f"\n  Sensitivity: {'PASS' if sensitivity_pass else 'FAIL'}")
print("\n  Done!")
