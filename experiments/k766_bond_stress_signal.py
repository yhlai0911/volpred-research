#!/usr/bin/env python3
"""
K766: Bond Market Stress as Equity De-Risking Signal

[提出: Codex GPT-5.4 8th suggestion #2, 執行: Claude]

Concept: Credit and duration stress often show up BEFORE equity drawdowns.
Build a composite Bond Stress Index (BSI) from bond market features that is
NOT VIX-dependent, as an alternative de-risking signal.

Features (all from yfinance):
  1. HYG-LQD spread proxy (high yield vs investment grade) — credit stress
  2. TLT 20-day realized vol — duration stress
  3. TLT-SHY slope (long vs short duration returns) — term structure proxy
  4. Stock-bond correlation rolling 60d (SPY vs TLT) — regime indicator

Composite BSI = z-score average of all 4 features (higher = more stressed)

Strategy:
  BSI > 75th percentile → 30% SPY + 35% GLD + 35% SHY (defensive)
  BSI < 25th percentile → full 12/VIX weight in SPY, rest GLD (risk-on)
  Otherwise → 50/50 SPY/GLD (neutral)
  signal.shift(1) enforced — no lookahead
  Monthly rebalancing with stress override (daily check for regime break)

Comparison: vs 12/VIX, 50/50, BH SPY
Cross-OOS: 5 non-overlapping periods

Related: K22/K24 (HYG fails cross-OOS), K561 (TLT worse than GLD),
K651 (credit spread flips sign), K713 (TLT 25% helps static),
K763 (regime carry filter)

References:
- Baele, Bekaert & Inghelbrecht (2010) "The Determinants of Stock and Bond
  Return Comovements", RFS
- Connolly, Stivers & Sun (2005) "Stock Market Uncertainty and the
  Stock-Bond Return Relation", JFQA
- Collin-Dufresne, Goldstein & Martin (2001) "The Determinants of Credit
  Spread Changes", JF
- Krishnamurthy & Vissing-Jorgensen (2012) "The Aggregate Demand for
  Treasury Debt", JPE

Data: yfinance SPY/GLD/TLT/SHY/HYG/LQD/^VIX, 2008-2026
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from scipy import stats

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("=" * 70)
print("K766: Bond Market Stress as Equity De-Risking Signal")
print("=" * 70)

tickers = ["SPY", "GLD", "TLT", "SHY", "HYG", "LQD", "^VIX"]
start = "2007-01-01"
end = "2026-03-31"

print(f"\nDownloading {tickers} from {start} to {end}...")
raw = yf.download(tickers, start=start, end=end, auto_adjust=True)

# Extract close prices
close = raw["Close"].copy()
col_map = {"^VIX": "VIX"}
close = close.rename(columns=col_map)
close = close.ffill().dropna()

print(f"Data shape: {close.shape}")
print(f"Date range: {close.index[0].date()} to {close.index[-1].date()}")
print(f"Columns: {list(close.columns)}")

# Simple returns
ret = close.pct_change()
ret_spy = ret["SPY"]
ret_gld = ret["GLD"]
ret_tlt = ret["TLT"]
ret_shy = ret["SHY"]

# ============================================================
# 2. CONSTRUCT BOND STRESS INDEX (BSI)
# ============================================================
print("\n" + "=" * 70)
print("2. Constructing Bond Stress Index (BSI)")
print("=" * 70)

# Feature 1: HYG-LQD spread proxy (ratio-based since no actual spreads)
# Higher ratio = credit stress (HYG underperforming LQD)
# Use cumulative return difference over 20d as spread proxy
hyg_lqd_ratio = (close["LQD"] / close["HYG"]).pct_change(20)
# Higher = LQD outperforming HYG = credit stress rising

# Feature 2: TLT 20-day realized volatility
tlt_log_ret = np.log(close["TLT"] / close["TLT"].shift(1))
tlt_rv20 = tlt_log_ret.rolling(20).std() * np.sqrt(252)

# Feature 3: TLT-SHY slope (long vs short duration performance)
# Lower = curve flattening/inverting = stress
tlt_shy_slope = (close["TLT"] / close["SHY"]).pct_change(20)
# Negative = long duration underperforming = rising rates / stress

# Feature 4: Stock-bond correlation rolling 60d
spy_tlt_corr = ret_spy.rolling(60).corr(ret_tlt)
# Higher (positive) correlation = flight-to-quality broken = stress

print("\nFeature descriptive statistics:")
features_raw = pd.DataFrame({
    "HYG_LQD_spread": hyg_lqd_ratio,
    "TLT_RV20": tlt_rv20,
    "TLT_SHY_slope": tlt_shy_slope,
    "SPY_TLT_corr": spy_tlt_corr
})
print(features_raw.describe().round(4))

# Z-score each feature using EXPANDING window (no lookahead)
# Each feature scored so that HIGHER = MORE STRESS
def expanding_zscore(series):
    """Expanding z-score: uses only past data up to each point."""
    mean = series.expanding(min_periods=60).mean()
    std = series.expanding(min_periods=60).std()
    return (series - mean) / std.replace(0, np.nan)

# HYG-LQD spread: higher = more credit stress → keep as is
z_hyg_lqd = expanding_zscore(hyg_lqd_ratio)

# TLT RV: higher vol = more duration stress → keep as is
z_tlt_rv = expanding_zscore(tlt_rv20)

# TLT-SHY slope: NEGATIVE = stress (long underperforms) → negate
z_tlt_shy = -expanding_zscore(tlt_shy_slope)

# SPY-TLT corr: POSITIVE = broken diversification = stress → keep as is
z_spy_tlt = expanding_zscore(spy_tlt_corr)

# Composite BSI = average of z-scores
bsi = (z_hyg_lqd + z_tlt_rv + z_tlt_shy + z_spy_tlt) / 4.0
bsi = bsi.dropna()

print(f"\nBSI computed: {len(bsi)} observations")
print(f"BSI stats: mean={bsi.mean():.3f}, std={bsi.std():.3f}, "
      f"min={bsi.min():.3f}, max={bsi.max():.3f}")

# Percentile thresholds using expanding window (no lookahead)
bsi_pct75 = bsi.expanding(min_periods=252).quantile(0.75)
bsi_pct25 = bsi.expanding(min_periods=252).quantile(0.25)

# ============================================================
# 3. BSI DIAGNOSTICS — Does BSI lead equity drawdowns?
# ============================================================
print("\n" + "=" * 70)
print("3. BSI Diagnostics — Lead-lag with equity drawdowns")
print("=" * 70)

# Align data
common_idx = bsi.dropna().index.intersection(ret_spy.dropna().index)
common_idx = common_idx[common_idx >= "2008-01-01"]  # ensure enough history

bsi_aligned = bsi.loc[common_idx]
spy_ret_aligned = ret_spy.loc[common_idx]

# Forward SPY drawdown (next 22 days max drawdown)
spy_cumret_fwd = (1 + spy_ret_aligned).rolling(22).apply(
    lambda x: (np.cumprod(x) / np.maximum.accumulate(np.cumprod(x)) - 1).min(),
    raw=True
)
# Actually, compute forward 22d return for simplicity
spy_fwd22 = spy_ret_aligned.shift(-22).rolling(22).sum()  # approximate

# Simpler: correlation of BSI with next-month return
for lag in [1, 5, 10, 22]:
    fwd_ret = spy_ret_aligned.shift(-lag)
    corr_val = bsi_aligned.corr(fwd_ret)
    n = (~bsi_aligned.isna() & ~fwd_ret.isna()).sum()
    t_stat = corr_val * np.sqrt((n - 2) / (1 - corr_val**2))
    print(f"  BSI vs SPY return t+{lag:2d}d: corr={corr_val:.4f}, t={t_stat:.2f}, n={n}")

# BSI quintile analysis
bsi_q = pd.qcut(bsi_aligned, 5, labels=[1, 2, 3, 4, 5])
for q in range(1, 6):
    mask = bsi_q == q
    avg_ret = spy_ret_aligned[mask].shift(-1).mean() * 252  # annualized next-day
    vol_ret = spy_ret_aligned[mask].shift(-1).std() * np.sqrt(252)
    count = mask.sum()
    print(f"  BSI Q{q}: avg ann ret={avg_ret:.3f}, ann vol={vol_ret:.3f}, "
          f"Sharpe={avg_ret/vol_ret:.3f}, n={count}")

# ============================================================
# 4. STRATEGY CONSTRUCTION
# ============================================================
print("\n" + "=" * 70)
print("4. Strategy Construction")
print("=" * 70)

# Align all data
df = pd.DataFrame({
    "ret_spy": ret_spy,
    "ret_gld": ret_gld,
    "ret_tlt": ret_tlt,
    "ret_shy": ret_shy,
    "VIX": close["VIX"],
    "BSI": bsi,
    "BSI_p75": bsi_pct75,
    "BSI_p25": bsi_pct25,
}).dropna()

# Filter to 2008+ (need history for z-scores)
df = df[df.index >= "2008-06-01"]
print(f"Strategy period: {df.index[0].date()} to {df.index[-1].date()}, n={len(df)}")

# 12/VIX weight (capped at 1.0)
vix_weight = np.clip(12.0 / df["VIX"], 0, 1.0)

# *** CRITICAL: signal.shift(1) — all signals use previous day's data ***
bsi_signal = df["BSI"].shift(1)
bsi_p75_signal = df["BSI_p75"].shift(1)
bsi_p25_signal = df["BSI_p25"].shift(1)
vix_weight_signal = vix_weight.shift(1)

# Monthly rebalancing flag (first trading day of month) with daily stress override
is_month_start = df.index.to_series().dt.month != df.index.to_series().dt.month.shift(1)

# Strategy: BSI-based de-risking
# Regime determination
regime = pd.Series("neutral", index=df.index)
regime[bsi_signal > bsi_p75_signal] = "stress"
regime[bsi_signal < bsi_p25_signal] = "risk_on"

# Monthly rebalancing with daily stress override
# Only change from non-stress to non-stress on month starts
# But allow immediate switch TO stress (override) at any time
prev_regime = regime.shift(1).fillna("neutral")
regime_final = prev_regime.copy()  # keep previous until month start

for i in range(len(df)):
    if i == 0:
        regime_final.iloc[i] = regime.iloc[i]
        continue

    current_regime = regime.iloc[i]
    prev = regime_final.iloc[i - 1]

    # Always allow immediate switch TO stress
    if current_regime == "stress":
        regime_final.iloc[i] = "stress"
    # On month start, allow any regime change
    elif is_month_start.iloc[i]:
        regime_final.iloc[i] = current_regime
    # Otherwise keep previous
    else:
        regime_final.iloc[i] = prev

print(f"\nRegime distribution:")
print(regime_final.value_counts())
print(f"Regime distribution (%):")
print((regime_final.value_counts() / len(regime_final) * 100).round(1))

# Weights by regime
w_spy_bsi = pd.Series(0.5, index=df.index)  # neutral default
w_gld_bsi = pd.Series(0.5, index=df.index)

# Stress: 30% SPY, 35% GLD, 35% SHY
stress_mask = regime_final == "stress"
w_spy_bsi[stress_mask] = 0.30
w_gld_bsi[stress_mask] = 0.35
w_shy_bsi = pd.Series(0.0, index=df.index)
w_shy_bsi[stress_mask] = 0.35

# Risk-on: 12/VIX weight in SPY, rest in GLD
riskon_mask = regime_final == "risk_on"
w_spy_bsi[riskon_mask] = vix_weight_signal[riskon_mask]
w_gld_bsi[riskon_mask] = 1.0 - vix_weight_signal[riskon_mask]

# Neutral: 50/50 SPY/GLD
neutral_mask = regime_final == "neutral"
w_spy_bsi[neutral_mask] = 0.50
w_gld_bsi[neutral_mask] = 0.50

# BSI strategy returns (3 assets)
ret_bsi = (w_spy_bsi * df["ret_spy"] +
           w_gld_bsi * df["ret_gld"] +
           w_shy_bsi * df["ret_shy"])

# Transaction costs: 5 bps per leg on weight changes
tx_cost = 0.0005
w_change_spy = w_spy_bsi.diff().abs().fillna(0)
w_change_gld = w_gld_bsi.diff().abs().fillna(0)
w_change_shy = w_shy_bsi.diff().abs().fillna(0)
total_turnover = w_change_spy + w_change_gld + w_change_shy
tx_daily = total_turnover * tx_cost

ret_bsi_net = ret_bsi - tx_daily

# ============================================================
# 5. BENCHMARK STRATEGIES (same period, same lag)
# ============================================================
print("\n" + "=" * 70)
print("5. Benchmark Strategies")
print("=" * 70)

# 12/VIX strategy
w_spy_12vix = np.clip(12.0 / df["VIX"].shift(1), 0, 1.0)
w_gld_12vix = 1.0 - w_spy_12vix
ret_12vix = w_spy_12vix * df["ret_spy"] + w_gld_12vix * df["ret_gld"]
# TX for 12/VIX
tx_12vix = (w_spy_12vix.diff().abs().fillna(0) + w_gld_12vix.diff().abs().fillna(0)) * tx_cost
ret_12vix_net = ret_12vix - tx_12vix

# 50/50 (rebalanced monthly)
ret_5050 = 0.5 * df["ret_spy"] + 0.5 * df["ret_gld"]

# Buy and Hold SPY
ret_bh_spy = df["ret_spy"]

# ============================================================
# 6. PERFORMANCE METRICS
# ============================================================
print("\n" + "=" * 70)
print("6. Full-Sample Performance Comparison")
print("=" * 70)

def calc_metrics(returns, name=""):
    """Calculate comprehensive performance metrics."""
    r = returns.dropna()
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # CAGR
    years = len(r) / 252
    total_ret = cum.iloc[-1]
    cagr = total_ret ** (1 / years) - 1 if years > 0 else 0

    # Calmar
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = r[r < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0

    return {
        "name": name,
        "ann_ret": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "mdd": mdd,
        "cagr": cagr,
        "calmar": calmar,
        "sortino": sortino,
        "total_return": total_ret,
        "n_days": len(r),
    }


strategies = {
    "BSI De-Risk (gross)": ret_bsi,
    "BSI De-Risk (net TX)": ret_bsi_net,
    "12/VIX (gross)": ret_12vix,
    "12/VIX (net TX)": ret_12vix_net,
    "50/50 SPY/GLD": ret_5050,
    "BH SPY": ret_bh_spy,
}

results = {}
for name, ret in strategies.items():
    m = calc_metrics(ret, name)
    results[name] = m
    print(f"\n  {name}:")
    print(f"    Sharpe={m['sharpe']:.3f}, CAGR={m['cagr']*100:.1f}%, "
          f"Vol={m['ann_vol']*100:.1f}%, MDD={m['mdd']*100:.1f}%")
    print(f"    Calmar={m['calmar']:.3f}, Sortino={m['sortino']:.3f}, "
          f"Total={m['total_return']:.2f}x")

# ============================================================
# 7. STATISTICAL TESTS
# ============================================================
print("\n" + "=" * 70)
print("7. Statistical Tests (Diebold-Mariano)")
print("=" * 70)

def dm_test(r1, r2, benchmark_ret=None):
    """Diebold-Mariano test comparing two strategy returns.
    H0: r1 and r2 have equal expected returns.
    Positive t = r1 is better.
    """
    d = r1 - r2
    d = d.dropna()
    n = len(d)
    mean_d = d.mean()
    se_d = d.std() / np.sqrt(n)
    t_stat = mean_d / se_d if se_d > 0 else 0
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return t_stat, p_val, n

# BSI net vs benchmarks
comparisons = [
    ("BSI net vs 12/VIX net", ret_bsi_net, ret_12vix_net),
    ("BSI net vs 50/50", ret_bsi_net, ret_5050),
    ("BSI net vs BH SPY", ret_bsi_net, ret_bh_spy),
    ("BSI gross vs 12/VIX gross", ret_bsi, ret_12vix),
]

dm_results = {}
for label, r1, r2 in comparisons:
    t, p, n = dm_test(r1, r2)
    sig = "***" if abs(t) > 3.0 else "**" if abs(t) > 2.0 else "*" if abs(t) > 1.65 else "NS"
    print(f"  {label}: t={t:.3f}, p={p:.4f} {sig} (n={n})")
    dm_results[label] = {"t": round(t, 3), "p": round(p, 4), "sig": sig}

# ============================================================
# 8. CROSS-OOS VALIDATION (5 non-overlapping periods)
# ============================================================
print("\n" + "=" * 70)
print("8. Cross-OOS Validation (5 non-overlapping periods)")
print("=" * 70)

oos_periods = [
    ("2008-06-01", "2010-05-31", "GFC"),
    ("2011-06-01", "2013-05-31", "Euro Crisis"),
    ("2015-06-01", "2017-05-31", "Low Vol"),
    ("2018-06-01", "2020-05-31", "COVID"),
    ("2022-06-01", "2024-05-31", "Rate Hikes"),
]

oos_results = []
for start_d, end_d, label in oos_periods:
    mask = (df.index >= start_d) & (df.index <= end_d)
    if mask.sum() < 100:
        print(f"  {label}: insufficient data ({mask.sum()} days), skipping")
        continue

    bsi_r = ret_bsi_net[mask]
    vix_r = ret_12vix_net[mask]
    r5050 = ret_5050[mask]

    m_bsi = calc_metrics(bsi_r, f"BSI {label}")
    m_vix = calc_metrics(vix_r, f"12/VIX {label}")
    m_5050 = calc_metrics(r5050, f"50/50 {label}")

    # BSI beats 50/50?
    beats_5050 = m_bsi["sharpe"] > m_5050["sharpe"]
    # BSI beats 12/VIX?
    beats_12vix = m_bsi["sharpe"] > m_vix["sharpe"]

    result = {
        "period": label,
        "start": start_d,
        "end": end_d,
        "bsi_sharpe": round(m_bsi["sharpe"], 3),
        "bsi_mdd": round(m_bsi["mdd"], 3),
        "vix_sharpe": round(m_vix["sharpe"], 3),
        "vix_mdd": round(m_vix["mdd"], 3),
        "r5050_sharpe": round(m_5050["sharpe"], 3),
        "r5050_mdd": round(m_5050["mdd"], 3),
        "beats_5050": beats_5050,
        "beats_12vix": beats_12vix,
        "n_days": mask.sum(),
    }
    oos_results.append(result)

    win_5050 = "✓" if beats_5050 else "✗"
    win_12vix = "✓" if beats_12vix else "✗"
    print(f"\n  {label} ({start_d} to {end_d}), n={mask.sum()}:")
    print(f"    BSI:   Sharpe={m_bsi['sharpe']:.3f}, MDD={m_bsi['mdd']*100:.1f}%")
    print(f"    12/VIX: Sharpe={m_vix['sharpe']:.3f}, MDD={m_vix['mdd']*100:.1f}%")
    print(f"    50/50: Sharpe={m_5050['sharpe']:.3f}, MDD={m_5050['mdd']*100:.1f}%")
    print(f"    Beats 50/50: {win_5050}, Beats 12/VIX: {win_12vix}")

n_beats_5050 = sum(1 for r in oos_results if r["beats_5050"])
n_beats_12vix = sum(1 for r in oos_results if r["beats_12vix"])
n_periods = len(oos_results)

print(f"\n  Cross-OOS Summary:")
print(f"    BSI beats 50/50: {n_beats_5050}/{n_periods}")
print(f"    BSI beats 12/VIX: {n_beats_12vix}/{n_periods}")

# ============================================================
# 9. BSI COMPONENT ANALYSIS — Which features matter?
# ============================================================
print("\n" + "=" * 70)
print("9. BSI Component Analysis — Individual feature predictive power")
print("=" * 70)

# Test each component individually
components = {
    "HYG-LQD spread": z_hyg_lqd,
    "TLT RV20": z_tlt_rv,
    "TLT-SHY slope (neg)": z_tlt_shy,
    "SPY-TLT corr": z_spy_tlt,
}

fwd_ret = ret_spy.shift(-1)  # next-day return for predictive analysis

for name, z in components.items():
    aligned = pd.DataFrame({"z": z, "fwd": fwd_ret}).dropna()
    aligned = aligned[aligned.index >= "2008-06-01"]

    corr = aligned["z"].corr(aligned["fwd"])
    n = len(aligned)
    t = corr * np.sqrt((n - 2) / (1 - corr**2)) if abs(corr) < 1 else 0

    # Quintile spread
    q = pd.qcut(aligned["z"], 5, labels=[1, 2, 3, 4, 5], duplicates="drop")
    q5_ret = aligned["fwd"][q == 5].mean() * 252
    q1_ret = aligned["fwd"][q == 1].mean() * 252
    spread = q5_ret - q1_ret

    print(f"  {name}: corr={corr:.4f}, t={t:.2f}, "
          f"Q5-Q1 spread={spread:.3f} ann")

# ============================================================
# 10. SENSITIVITY ANALYSIS — BSI threshold variation
# ============================================================
print("\n" + "=" * 70)
print("10. Sensitivity Analysis — BSI threshold variation")
print("=" * 70)

sensitivities = []
for stress_pct in [0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]:
    for riskon_pct in [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]:
        if riskon_pct >= stress_pct:
            continue

        pct_hi = bsi.expanding(min_periods=252).quantile(stress_pct)
        pct_lo = bsi.expanding(min_periods=252).quantile(riskon_pct)

        sig_bsi = bsi.shift(1)
        sig_hi = pct_hi.shift(1)
        sig_lo = pct_lo.shift(1)

        w_s = pd.Series(0.5, index=df.index)
        w_g = pd.Series(0.5, index=df.index)
        w_sh = pd.Series(0.0, index=df.index)

        vw = vix_weight.shift(1)

        stress_m = sig_bsi > sig_hi
        w_s[stress_m] = 0.30
        w_g[stress_m] = 0.35
        w_sh[stress_m] = 0.35

        riskon_m = sig_bsi < sig_lo
        w_s[riskon_m] = vw[riskon_m]
        w_g[riskon_m] = 1.0 - vw[riskon_m]

        r = (w_s * df["ret_spy"] + w_g * df["ret_gld"] + w_sh * df["ret_shy"])
        tc = (w_s.diff().abs().fillna(0) + w_g.diff().abs().fillna(0) +
              w_sh.diff().abs().fillna(0)) * tx_cost
        r_net = r - tc

        m = calc_metrics(r_net, f"stress={stress_pct}, riskon={riskon_pct}")
        sensitivities.append({
            "stress_pct": stress_pct,
            "riskon_pct": riskon_pct,
            "sharpe": round(m["sharpe"], 3),
            "mdd": round(m["mdd"], 3),
            "cagr": round(m["cagr"], 4),
        })

sens_df = pd.DataFrame(sensitivities)
print(f"\n  Sensitivity grid: {len(sens_df)} parameter combinations")
print(f"  Sharpe range: {sens_df['sharpe'].min():.3f} to {sens_df['sharpe'].max():.3f}")
print(f"  Best: stress={sens_df.loc[sens_df['sharpe'].idxmax(), 'stress_pct']}, "
      f"riskon={sens_df.loc[sens_df['sharpe'].idxmax(), 'riskon_pct']}")
print(f"  Base (75/25): Sharpe={results['BSI De-Risk (net TX)']['sharpe']:.3f}")
print(f"\n  Top 5 configurations:")
top5 = sens_df.nlargest(5, "sharpe")
for _, row in top5.iterrows():
    print(f"    stress={row['stress_pct']:.2f}, riskon={row['riskon_pct']:.2f}: "
          f"Sharpe={row['sharpe']:.3f}, MDD={row['mdd']*100:.1f}%")

# Check sensitivity: does ±20% change threshold affect Sharpe by >30%?
base_sharpe = results["BSI De-Risk (net TX)"]["sharpe"]
nearby = sens_df[
    (sens_df["stress_pct"].between(0.70, 0.80)) &
    (sens_df["riskon_pct"].between(0.20, 0.30))
]
if len(nearby) > 0:
    worst_nearby = nearby["sharpe"].min()
    pct_drop = (base_sharpe - worst_nearby) / abs(base_sharpe) * 100
    print(f"\n  Sensitivity check (±20% around base):")
    print(f"    Base Sharpe: {base_sharpe:.3f}")
    print(f"    Worst nearby: {worst_nearby:.3f}")
    print(f"    Drop: {pct_drop:.1f}% (threshold: 30%)")
    sensitivity_pass = pct_drop < 30
    print(f"    Sensitivity test: {'PASS' if sensitivity_pass else 'FAIL'}")
else:
    sensitivity_pass = False

# ============================================================
# 11. REGIME ANALYSIS — BSI in specific market events
# ============================================================
print("\n" + "=" * 70)
print("11. Regime Analysis — BSI behavior in key events")
print("=" * 70)

events = [
    ("2008-09-01", "2009-03-31", "GFC Peak"),
    ("2011-07-01", "2011-10-31", "US Downgrade"),
    ("2020-02-15", "2020-04-30", "COVID Crash"),
    ("2022-01-01", "2022-12-31", "Rate Hikes 2022"),
    ("2023-03-01", "2023-04-30", "SVB Crisis"),
    ("2024-07-01", "2024-08-31", "Aug 2024 Selloff"),
]

for start_e, end_e, label in events:
    mask_e = (bsi.index >= start_e) & (bsi.index <= end_e)
    if mask_e.sum() == 0:
        continue

    bsi_event = bsi[mask_e]
    spy_event = ret_spy.reindex(bsi_event.index)

    # BSI percentile at event start vs end
    bsi_start = bsi_event.iloc[0]
    bsi_end = bsi_event.iloc[-1]
    bsi_max = bsi_event.max()

    # How many days was BSI in stress regime?
    stress_days = (regime_final.reindex(bsi_event.index) == "stress").sum()
    total_days = len(bsi_event)

    # SPY drawdown during event
    spy_cum = (1 + spy_event).cumprod()
    spy_dd = (spy_cum / spy_cum.cummax() - 1).min()

    print(f"\n  {label} ({start_e} to {end_e}):")
    print(f"    BSI: start={bsi_start:.2f}, max={bsi_max:.2f}, end={bsi_end:.2f}")
    print(f"    Stress days: {stress_days}/{total_days} ({stress_days/total_days*100:.0f}%)")
    print(f"    SPY drawdown: {spy_dd*100:.1f}%")

# ============================================================
# 12. RESULTS SUMMARY & CONCLUSION
# ============================================================
print("\n" + "=" * 70)
print("12. Results Summary & Conclusion")
print("=" * 70)

bsi_net_metrics = results["BSI De-Risk (net TX)"]
vix_net_metrics = results["12/VIX (net TX)"]
r5050_metrics = results["50/50 SPY/GLD"]

# Codex severity assessment
codex_severity = "NULL"
if bsi_net_metrics["sharpe"] > r5050_metrics["sharpe"]:
    if n_beats_5050 >= 3:
        codex_severity = "LOW"
    if n_beats_5050 >= 4:
        codex_severity = "MEDIUM"
    if abs(dm_results.get("BSI net vs 50/50", {}).get("t", 0)) > 3.0:
        codex_severity = "HIGH"

conclusion_lines = []
conclusion_lines.append(f"BSI net Sharpe: {bsi_net_metrics['sharpe']:.3f}")
conclusion_lines.append(f"12/VIX net Sharpe: {vix_net_metrics['sharpe']:.3f}")
conclusion_lines.append(f"50/50 Sharpe: {r5050_metrics['sharpe']:.3f}")
conclusion_lines.append(f"BSI net MDD: {bsi_net_metrics['mdd']*100:.1f}%")
conclusion_lines.append(f"Cross-OOS vs 50/50: {n_beats_5050}/{n_periods}")
conclusion_lines.append(f"Cross-OOS vs 12/VIX: {n_beats_12vix}/{n_periods}")
conclusion_lines.append(f"DM t (BSI vs 50/50): {dm_results.get('BSI net vs 50/50', {}).get('t', 'N/A')}")
conclusion_lines.append(f"DM t (BSI vs 12/VIX): {dm_results.get('BSI net vs 12/VIX net', {}).get('t', 'N/A')}")
conclusion_lines.append(f"Sensitivity: {'PASS' if sensitivity_pass else 'FAIL'}")
conclusion_lines.append(f"Codex severity: {codex_severity}")

for line in conclusion_lines:
    print(f"  {line}")

# ============================================================
# 13. SAVE RESULTS
# ============================================================
print("\n" + "=" * 70)
print("13. Saving results...")
print("=" * 70)

output = {
    "experiment_id": "K766",
    "title": "Bond Market Stress as Equity De-Risking Signal",
    "proposer": "Codex GPT-5.4 (8th suggestion #2)",
    "executor": "Claude",
    "data_source": "yfinance daily (SPY, GLD, TLT, SHY, HYG, LQD, ^VIX)",
    "data_period": f"{df.index[0].date()} to {df.index[-1].date()}",
    "n_observations": len(df),
    "methodology": {
        "BSI_features": [
            "HYG-LQD 20d spread proxy (credit stress)",
            "TLT 20d realized vol (duration stress)",
            "TLT-SHY 20d slope (term structure proxy)",
            "SPY-TLT 60d rolling correlation (regime indicator)",
        ],
        "BSI_construction": "expanding z-score average of 4 features",
        "strategy_rules": {
            "stress": "BSI > 75th pct → 30% SPY + 35% GLD + 35% SHY",
            "risk_on": "BSI < 25th pct → 12/VIX weight SPY + rest GLD",
            "neutral": "25th < BSI < 75th → 50/50 SPY/GLD",
        },
        "rebalancing": "Monthly with daily stress override",
        "lag": "signal.shift(1) — all signals use previous day data",
        "tx_cost": "5 bps per leg on weight changes",
    },
    "full_sample_metrics": {
        name: {k: round(v, 4) if isinstance(v, (float, np.floating)) else v
               for k, v in m.items()}
        for name, m in results.items()
    },
    "dm_tests": dm_results,
    "cross_oos": {
        "periods": oos_results,
        "beats_5050": f"{n_beats_5050}/{n_periods}",
        "beats_12vix": f"{n_beats_12vix}/{n_periods}",
    },
    "sensitivity": {
        "n_configs": len(sens_df),
        "sharpe_range": [round(sens_df["sharpe"].min(), 3),
                         round(sens_df["sharpe"].max(), 3)],
        "best_config": {
            "stress_pct": float(sens_df.loc[sens_df["sharpe"].idxmax(), "stress_pct"]),
            "riskon_pct": float(sens_df.loc[sens_df["sharpe"].idxmax(), "riskon_pct"]),
            "sharpe": float(sens_df.loc[sens_df["sharpe"].idxmax(), "sharpe"]),
        },
        "sensitivity_pass": sensitivity_pass,
    },
    "regime_distribution": regime_final.value_counts().to_dict(),
    "codex_severity": codex_severity,
    "conclusion": " | ".join(conclusion_lines),
    "references": [
        "Baele, Bekaert & Inghelbrecht (2010) RFS",
        "Connolly, Stivers & Sun (2005) JFQA",
        "Collin-Dufresne, Goldstein & Martin (2001) JF",
        "Krishnamurthy & Vissing-Jorgensen (2012) JPE",
    ],
    "related_experiments": ["K22", "K24", "K33", "K561", "K651", "K713", "K763"],
    "created_at": datetime.now().isoformat(),
}

results_path = "experiments/k766_bond_stress_signal_results.json"
with open(results_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"Results saved to {results_path}")
print("\n" + "=" * 70)
print("K766 COMPLETE")
print("=" * 70)
