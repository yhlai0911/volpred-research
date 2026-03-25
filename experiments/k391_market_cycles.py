#!/usr/bin/env python3
"""
K391: Volatility Across Market Cycles — Bull, Bear, Recovery, Distribution
==========================================================================
[提出: User, 執行: Claude]

Classifies SPY into 4 market phases using 200-day and 50-day MAs,
then measures vol dynamics, VIX, GJR leverage, and 50/50+VT performance
within each phase.

Data: SPY, GLD, VIX daily from yfinance, 2000-2024 (25 years).
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from collections import OrderedDict

warnings.filterwarnings("ignore")

# ── 1. Data Download ─────────────────────────────────────────────────────

print("=" * 70)
print("K391: Volatility Across Market Cycles")
print("=" * 70)
print()

START = "1999-01-01"  # extra year for MA warmup
END = "2025-01-01"

print("Downloading data from yfinance...")
spy = yf.download("SPY", start=START, end=END, progress=False)["Close"]
gld = yf.download("GLD", start=START, end=END, progress=False)["Close"]
vix = yf.download("^VIX", start=START, end=END, progress=False)["Close"]

# Flatten MultiIndex if needed
if isinstance(spy.columns, pd.MultiIndex) if hasattr(spy, 'columns') else False:
    spy = spy.iloc[:, 0]
if isinstance(gld.columns, pd.MultiIndex) if hasattr(gld, 'columns') else False:
    gld = gld.iloc[:, 0]
if isinstance(vix.columns, pd.MultiIndex) if hasattr(vix, 'columns') else False:
    vix = vix.iloc[:, 0]

# Ensure Series
spy = spy.squeeze()
gld = gld.squeeze()
vix = vix.squeeze()

print(f"SPY: {spy.index[0].date()} to {spy.index[-1].date()}, {len(spy)} obs")
print(f"GLD: {gld.index[0].date()} to {gld.index[-1].date()}, {len(gld)} obs")
print(f"VIX: {vix.index[0].date()} to {vix.index[-1].date()}, {len(vix)} obs")

# ── 2. Compute MAs and classify phases ──────────────────────────────────

spy_df = pd.DataFrame({"close": spy})
spy_df["ma50"] = spy_df["close"].rolling(50).mean()
spy_df["ma200"] = spy_df["close"].rolling(200).mean()
spy_df["ret"] = spy_df["close"].pct_change()

# Phase classification
# Bull: price > MA200 AND MA50 > MA200 (golden cross territory, trending up)
# Bear: price < MA200 AND MA50 < MA200 (death cross territory, trending down)
# Recovery: price crossing above — MA50 < MA200 but price > MA200, OR price < MA200 but MA50 rising
# Distribution: price crossing below — MA50 > MA200 but price < MA200, or flattening

def classify_phase(row):
    """
    4-phase classification:
    - Bull: price > MA200 AND MA50 > MA200
    - Bear: price < MA200 AND MA50 < MA200
    - Recovery: price < MA200 but MA50 > MA200 (or MA50 crossing up)
              Actually: MA50 < MA200 but price > some recovery signal
    - Distribution: MA50 > MA200 but price < MA200

    Simplified robust version:
    - Bull: close > MA200 AND MA50 > MA200
    - Bear: close < MA200 AND MA50 < MA200
    - Recovery: close < MA200 AND MA50 > MA200 (still below but structure improving)
    - Distribution: close > MA200 AND MA50 < MA200 (still above but structure deteriorating)
    """
    if pd.isna(row["ma50"]) or pd.isna(row["ma200"]):
        return np.nan

    above_200 = row["close"] > row["ma200"]
    golden = row["ma50"] > row["ma200"]

    if above_200 and golden:
        return "Bull"
    elif not above_200 and not golden:
        return "Bear"
    elif not above_200 and golden:
        return "Recovery"  # Structure still good but price dropped below 200MA
    else:  # above_200 and not golden
        return "Distribution"  # Price still above 200MA but MAs bearish


spy_df["phase"] = spy_df.apply(classify_phase, axis=1)

# Trim to 2000-2024
spy_df = spy_df.loc["2000-01-01":"2024-12-31"]

# Add VIX
spy_df["vix"] = vix.reindex(spy_df.index)

# Add GLD returns (available from ~2004)
gld_ret = gld.pct_change().reindex(spy_df.index)
spy_df["gld_ret"] = gld_ret

print(f"\nAnalysis period: {spy_df.index[0].date()} to {spy_df.index[-1].date()}")
print(f"Total trading days: {len(spy_df)}")
print(f"Days with phase classification: {spy_df['phase'].notna().sum()}")

# ── 3. Phase Statistics ─────────────────────────────────────────────────

print("\n" + "=" * 70)
print("PHASE STATISTICS (2000-2024)")
print("=" * 70)

phases = ["Bull", "Bear", "Recovery", "Distribution"]
results = {}

for phase in phases:
    mask = spy_df["phase"] == phase
    subset = spy_df[mask]
    n_days = len(subset)
    pct_time = n_days / spy_df["phase"].notna().sum() * 100

    # Returns
    mean_daily_ret = subset["ret"].mean()
    ann_ret = mean_daily_ret * 252
    daily_vol = subset["ret"].std()
    ann_vol = daily_vol * np.sqrt(252)

    # VIX
    mean_vix = subset["vix"].mean()
    median_vix = subset["vix"].median()
    max_vix = subset["vix"].max()

    # Vol clustering: ACF(1) of squared returns
    sq_ret = subset["ret"].dropna() ** 2
    if len(sq_ret) > 10:
        acf1 = sq_ret.autocorr(lag=1)
        acf5 = sq_ret.autocorr(lag=5)
    else:
        acf1 = acf5 = np.nan

    # GJR gamma estimation (simple proxy: asymmetric vol response)
    rets = subset["ret"].dropna()
    neg_rets = rets[rets < 0]
    pos_rets = rets[rets >= 0]
    neg_vol = neg_rets.std() if len(neg_rets) > 5 else np.nan
    pos_vol = pos_rets.std() if len(pos_rets) > 5 else np.nan
    leverage_ratio = neg_vol / pos_vol if pos_vol and pos_vol > 0 else np.nan

    results[phase] = {
        "n_days": n_days,
        "pct_time": round(pct_time, 1),
        "ann_return": round(ann_ret * 100, 2),
        "ann_vol": round(ann_vol * 100, 2),
        "sharpe": round(ann_ret / ann_vol, 3) if ann_vol > 0 else np.nan,
        "mean_vix": round(mean_vix, 2),
        "median_vix": round(median_vix, 2),
        "max_vix": round(max_vix, 2),
        "vol_cluster_acf1": round(acf1, 4) if not np.isnan(acf1) else np.nan,
        "vol_cluster_acf5": round(acf5, 4) if not np.isnan(acf5) else np.nan,
        "leverage_ratio": round(leverage_ratio, 3) if not np.isnan(leverage_ratio) else np.nan,
    }

    print(f"\n{'─' * 50}")
    print(f"Phase: {phase}")
    print(f"{'─' * 50}")
    print(f"  Days: {n_days} ({pct_time:.1f}% of total)")
    print(f"  Annualized Return: {ann_ret*100:+.2f}%")
    print(f"  Annualized Vol: {ann_vol*100:.2f}%")
    print(f"  Sharpe: {ann_ret/ann_vol:.3f}" if ann_vol > 0 else "  Sharpe: N/A")
    print(f"  Mean VIX: {mean_vix:.2f}")
    print(f"  Median VIX: {median_vix:.2f}")
    print(f"  Max VIX: {max_vix:.2f}")
    print(f"  Vol Clustering ACF(1): {acf1:.4f}" if not np.isnan(acf1) else "  Vol Clustering ACF(1): N/A")
    print(f"  Vol Clustering ACF(5): {acf5:.4f}" if not np.isnan(acf5) else "  Vol Clustering ACF(5): N/A")
    print(f"  Leverage Ratio (neg_vol/pos_vol): {leverage_ratio:.3f}" if not np.isnan(leverage_ratio) else "  Leverage Ratio: N/A")

# ── 4. GJR-GARCH by Phase ──────────────────────────────────────────────

print("\n" + "=" * 70)
print("GJR-GARCH ESTIMATION BY PHASE")
print("=" * 70)

try:
    from arch import arch_model

    for phase in phases:
        mask = spy_df["phase"] == phase
        rets = spy_df.loc[mask, "ret"].dropna() * 100  # in pct

        if len(rets) < 100:
            print(f"\n{phase}: Too few observations ({len(rets)}) for GARCH estimation")
            results[phase]["gjr_omega"] = np.nan
            results[phase]["gjr_alpha"] = np.nan
            results[phase]["gjr_gamma"] = np.nan
            results[phase]["gjr_beta"] = np.nan
            continue

        try:
            model = arch_model(rets, vol="GARCH", p=1, o=1, q=1, dist="t")
            res = model.fit(disp="off", show_warning=False)

            omega = res.params.get("omega", np.nan)
            alpha = res.params.get("alpha[1]", np.nan)
            gamma = res.params.get("gamma[1]", np.nan)
            beta = res.params.get("beta[1]", np.nan)

            results[phase]["gjr_omega"] = round(float(omega), 6)
            results[phase]["gjr_alpha"] = round(float(alpha), 4)
            results[phase]["gjr_gamma"] = round(float(gamma), 4)
            results[phase]["gjr_beta"] = round(float(beta), 4)

            print(f"\n{phase} (n={len(rets)}):")
            print(f"  omega={omega:.6f}, alpha={alpha:.4f}, gamma={gamma:.4f}, beta={beta:.4f}")
            print(f"  Persistence: {alpha + gamma/2 + beta:.4f}")
            print(f"  Leverage effect (gamma): {gamma:.4f}")
        except Exception as e:
            print(f"\n{phase}: GARCH estimation failed: {e}")
            results[phase]["gjr_omega"] = np.nan
            results[phase]["gjr_alpha"] = np.nan
            results[phase]["gjr_gamma"] = np.nan
            results[phase]["gjr_beta"] = np.nan

except ImportError:
    print("arch package not available, skipping GJR estimation")

# ── 5. 50/50+VT Performance by Phase ───────────────────────────────────

print("\n" + "=" * 70)
print("50/50 + VT STRATEGY PERFORMANCE BY PHASE")
print("=" * 70)

# Simple VT strategy: when VIX > 20, reduce equity allocation
# 50/50 baseline: 50% SPY + 50% GLD
# 50/50+VT: shift allocation based on VIX level
#   VIX < 15: 60% SPY, 40% GLD (risk-on)
#   VIX 15-20: 50% SPY, 50% GLD (neutral)
#   VIX 20-30: 40% SPY, 60% GLD (cautious)
#   VIX > 30: 30% SPY, 70% GLD (risk-off)

# Only analyze from 2004+ (GLD inception)
gld_start = gld.index[0]
analysis_mask = (spy_df.index >= gld_start) & spy_df["gld_ret"].notna() & spy_df["ret"].notna()

spy_df_gld = spy_df[analysis_mask].copy()

# 50/50 baseline
spy_df_gld["ret_5050"] = 0.5 * spy_df_gld["ret"] + 0.5 * spy_df_gld["gld_ret"]

# VT overlay
def vt_weights(vix_val):
    if pd.isna(vix_val):
        return 0.5, 0.5
    if vix_val < 15:
        return 0.60, 0.40
    elif vix_val < 20:
        return 0.50, 0.50
    elif vix_val < 30:
        return 0.40, 0.60
    else:
        return 0.30, 0.70

spy_w = spy_df_gld["vix"].apply(lambda v: vt_weights(v)[0])
gld_w = spy_df_gld["vix"].apply(lambda v: vt_weights(v)[1])
spy_df_gld["ret_vt"] = spy_w * spy_df_gld["ret"] + gld_w * spy_df_gld["gld_ret"]

print(f"\nAnalysis period (GLD available): {spy_df_gld.index[0].date()} to {spy_df_gld.index[-1].date()}")
print(f"Trading days: {len(spy_df_gld)}")

vt_results = {}

for phase in phases:
    mask = spy_df_gld["phase"] == phase
    subset = spy_df_gld[mask]
    n = len(subset)

    if n < 10:
        print(f"\n{phase}: Too few days ({n}) with GLD data")
        continue

    # 50/50
    ret_5050 = subset["ret_5050"]
    ann_ret_5050 = ret_5050.mean() * 252
    ann_vol_5050 = ret_5050.std() * np.sqrt(252)
    sharpe_5050 = ann_ret_5050 / ann_vol_5050 if ann_vol_5050 > 0 else np.nan

    # VT
    ret_vt = subset["ret_vt"]
    ann_ret_vt = ret_vt.mean() * 252
    ann_vol_vt = ret_vt.std() * np.sqrt(252)
    sharpe_vt = ann_ret_vt / ann_vol_vt if ann_vol_vt > 0 else np.nan

    # VT alpha (return difference)
    vt_alpha = (ann_ret_vt - ann_ret_5050) * 100
    sharpe_diff = sharpe_vt - sharpe_5050

    vt_results[phase] = {
        "n_days": n,
        "ann_ret_5050": round(ann_ret_5050 * 100, 2),
        "ann_vol_5050": round(ann_vol_5050 * 100, 2),
        "sharpe_5050": round(sharpe_5050, 3),
        "ann_ret_vt": round(ann_ret_vt * 100, 2),
        "ann_vol_vt": round(ann_vol_vt * 100, 2),
        "sharpe_vt": round(sharpe_vt, 3),
        "vt_alpha_bps": round(vt_alpha * 100, 1),  # in bps
        "sharpe_diff": round(sharpe_diff, 4),
    }

    print(f"\n{'─' * 60}")
    print(f"Phase: {phase} (n={n} days)")
    print(f"{'─' * 60}")
    print(f"  50/50 Baseline:  Return={ann_ret_5050*100:+.2f}%, Vol={ann_vol_5050*100:.2f}%, Sharpe={sharpe_5050:.3f}")
    print(f"  50/50+VT:        Return={ann_ret_vt*100:+.2f}%, Vol={ann_vol_vt*100:.2f}%, Sharpe={sharpe_vt:.3f}")
    print(f"  VT Alpha: {vt_alpha*100:+.1f} bps/year,  Sharpe diff: {sharpe_diff:+.4f}")

# ── 6. Phase Transitions ───────────────────────────────────────────────

print("\n" + "=" * 70)
print("PHASE TRANSITIONS")
print("=" * 70)

spy_df_phases = spy_df[spy_df["phase"].notna()].copy()
phase_changes = spy_df_phases["phase"] != spy_df_phases["phase"].shift(1)
transitions = spy_df_phases[phase_changes].copy()

# Remove first observation (trivially a "change")
transitions = transitions.iloc[1:]

total_transitions = len(transitions)
years = (spy_df_phases.index[-1] - spy_df_phases.index[0]).days / 365.25
transitions_per_year = total_transitions / years

print(f"\nTotal phase transitions: {total_transitions}")
print(f"Transitions per year: {transitions_per_year:.1f}")
print(f"Average phase duration: {len(spy_df_phases) / (total_transitions + 1):.0f} trading days")

# Transitions by decade
print("\nTransitions by decade:")
decade_transitions = {}
for decade_start in range(2000, 2030, 10):
    decade_end = decade_start + 10
    mask = (transitions.index.year >= decade_start) & (transitions.index.year < decade_end)
    n_trans = mask.sum()
    decade_years = min(decade_end, 2025) - decade_start
    per_year = n_trans / decade_years if decade_years > 0 else 0
    decade_label = f"{decade_start}s"
    decade_transitions[decade_label] = {
        "n_transitions": int(n_trans),
        "per_year": round(per_year, 1),
    }
    print(f"  {decade_label}: {n_trans} transitions ({per_year:.1f}/year)")

# Transition matrix
print("\nTransition Matrix (from → to):")
from_phases = spy_df_phases["phase"].shift(1)
to_phases = spy_df_phases["phase"]
mask = from_phases != to_phases
from_p = from_phases[mask].iloc[1:]
to_p = to_phases[mask].iloc[1:]

transition_matrix = pd.crosstab(from_p, to_p, margins=True)
print(transition_matrix.to_string())

# ── 7. Phase Duration Distribution ─────────────────────────────────────

print("\n" + "=" * 70)
print("PHASE DURATION DISTRIBUTION")
print("=" * 70)

# Identify contiguous phase blocks
spy_df_clean = spy_df[spy_df["phase"].notna()].copy()
spy_df_clean["phase_change"] = (spy_df_clean["phase"] != spy_df_clean["phase"].shift(1)).cumsum()

phase_blocks = spy_df_clean.groupby("phase_change").agg(
    phase=("phase", "first"),
    start=("close", lambda x: x.index[0]),
    end=("close", lambda x: x.index[-1]),
    n_days=("close", "count"),
)

for phase in phases:
    blocks = phase_blocks[phase_blocks["phase"] == phase]
    durations = blocks["n_days"]

    print(f"\n{phase}:")
    print(f"  Number of episodes: {len(blocks)}")
    print(f"  Mean duration: {durations.mean():.0f} days")
    print(f"  Median duration: {durations.median():.0f} days")
    print(f"  Min: {durations.min()} days, Max: {durations.max()} days")
    print(f"  Std: {durations.std():.0f} days")

    results[phase]["n_episodes"] = int(len(blocks))
    results[phase]["mean_duration_days"] = round(float(durations.mean()), 1)
    results[phase]["median_duration_days"] = round(float(durations.median()), 1)

# ── 8. Current Phase (latest data) ─────────────────────────────────────

print("\n" + "=" * 70)
print("CURRENT MARKET PHASE")
print("=" * 70)

last_row = spy_df_clean.iloc[-1]
last_date = spy_df_clean.index[-1]
current_phase = last_row["phase"]
current_price = last_row["close"]
current_ma50 = last_row["ma50"]
current_ma200 = last_row["ma200"]
current_vix = last_row["vix"]

# How long in current phase?
current_block = phase_blocks.iloc[-1]
current_duration = current_block["n_days"]

print(f"  Date: {last_date.date()}")
print(f"  Phase: {current_phase}")
print(f"  SPY Close: ${current_price:.2f}")
print(f"  MA50: ${current_ma50:.2f}")
print(f"  MA200: ${current_ma200:.2f}")
print(f"  VIX: {current_vix:.2f}")
print(f"  Days in current phase: {current_duration}")
print(f"  Price vs MA200: {(current_price/current_ma200 - 1)*100:+.1f}%")
print(f"  MA50 vs MA200: {(current_ma50/current_ma200 - 1)*100:+.1f}%")

# ── 9. Summary Table ───────────────────────────────────────────────────

print("\n" + "=" * 70)
print("SUMMARY TABLE")
print("=" * 70)

header = f"{'Phase':<15} {'Time%':>6} {'AnnRet':>8} {'AnnVol':>8} {'Sharpe':>7} {'MeanVIX':>8} {'ACF(1)':>7} {'LevRat':>7} {'GJRgam':>8}"
print(header)
print("─" * len(header))

for phase in phases:
    r = results[phase]
    gjr_gamma = r.get("gjr_gamma", np.nan)
    gjr_str = f"{gjr_gamma:.4f}" if not (gjr_gamma is None or (isinstance(gjr_gamma, float) and np.isnan(gjr_gamma))) else "N/A"
    acf1 = r.get("vol_cluster_acf1", np.nan)
    acf_str = f"{acf1:.4f}" if not (acf1 is None or (isinstance(acf1, float) and np.isnan(acf1))) else "N/A"
    lev = r.get("leverage_ratio", np.nan)
    lev_str = f"{lev:.3f}" if not (lev is None or (isinstance(lev, float) and np.isnan(lev))) else "N/A"

    print(f"{phase:<15} {r['pct_time']:>5.1f}% {r['ann_return']:>+7.2f}% {r['ann_vol']:>7.2f}% {r['sharpe']:>7.3f} {r['mean_vix']:>7.2f} {acf_str:>7} {lev_str:>7} {gjr_str:>8}")

print("\n" + "=" * 70)
print("VT STRATEGY IMPACT BY PHASE")
print("=" * 70)

if vt_results:
    header2 = f"{'Phase':<15} {'5050Ret':>8} {'VTRet':>8} {'Alpha':>10} {'5050SR':>7} {'VT_SR':>7} {'SRdiff':>8}"
    print(header2)
    print("─" * len(header2))

    for phase in phases:
        if phase in vt_results:
            vr = vt_results[phase]
            print(f"{phase:<15} {vr['ann_ret_5050']:>+7.2f}% {vr['ann_ret_vt']:>+7.2f}% {vr['vt_alpha_bps']:>+8.1f}bps {vr['sharpe_5050']:>7.3f} {vr['sharpe_vt']:>7.3f} {vr['sharpe_diff']:>+8.4f}")

# ── 10. Key Findings ───────────────────────────────────────────────────

print("\n" + "=" * 70)
print("KEY FINDINGS")
print("=" * 70)

# Find which phase VT helps most / hurts most
if vt_results:
    best_phase = max(vt_results, key=lambda p: vt_results[p]["sharpe_diff"])
    worst_phase = min(vt_results, key=lambda p: vt_results[p]["sharpe_diff"])

    print(f"\n1. VT MOST BENEFICIAL in: {best_phase} phase")
    print(f"   Sharpe improvement: {vt_results[best_phase]['sharpe_diff']:+.4f}")
    print(f"   Alpha: {vt_results[best_phase]['vt_alpha_bps']:+.1f} bps/year")

    print(f"\n2. VT MOST COSTLY in: {worst_phase} phase")
    print(f"   Sharpe impact: {vt_results[worst_phase]['sharpe_diff']:+.4f}")
    print(f"   Alpha: {vt_results[worst_phase]['vt_alpha_bps']:+.1f} bps/year")

# Leverage effect comparison
print(f"\n3. LEVERAGE EFFECT BY PHASE:")
for phase in phases:
    gjr = results[phase].get("gjr_gamma", np.nan)
    if gjr and not np.isnan(gjr):
        print(f"   {phase}: GJR gamma = {gjr:.4f}")

# Vol clustering comparison
print(f"\n4. VOL CLUSTERING BY PHASE:")
for phase in phases:
    acf = results[phase].get("vol_cluster_acf1", np.nan)
    if acf and not np.isnan(acf):
        print(f"   {phase}: ACF(1) of r^2 = {acf:.4f}")

# Phase frequency trend
print(f"\n5. PHASE TRANSITION FREQUENCY:")
for dec, dt in decade_transitions.items():
    print(f"   {dec}: {dt['per_year']:.1f} transitions/year")

print(f"\n6. CURRENT PHASE: {current_phase}")
print(f"   Duration: {current_duration} days")

# ── 11. Statistical Tests ──────────────────────────────────────────────

print("\n" + "=" * 70)
print("STATISTICAL TESTS")
print("=" * 70)

from scipy import stats

# Test 1: Are VIX levels significantly different across phases?
print("\nTest 1: Kruskal-Wallis test for VIX differences across phases")
vix_groups = [spy_df[spy_df["phase"] == p]["vix"].dropna() for p in phases]
vix_groups_clean = [g for g in vix_groups if len(g) > 0]
if len(vix_groups_clean) >= 2:
    kw_stat, kw_pval = stats.kruskal(*vix_groups_clean)
    print(f"  H-statistic: {kw_stat:.2f}, p-value: {kw_pval:.2e}")
    print(f"  {'Significant' if kw_pval < 0.01 else 'Not significant'} at 1% level")

# Test 2: Are returns significantly different across phases?
print("\nTest 2: Kruskal-Wallis test for return differences across phases")
ret_groups = [spy_df[spy_df["phase"] == p]["ret"].dropna() for p in phases]
ret_groups_clean = [g for g in ret_groups if len(g) > 0]
if len(ret_groups_clean) >= 2:
    kw_stat, kw_pval = stats.kruskal(*ret_groups_clean)
    print(f"  H-statistic: {kw_stat:.2f}, p-value: {kw_pval:.2e}")
    print(f"  {'Significant' if kw_pval < 0.01 else 'Not significant'} at 1% level")

# Test 3: Is vol clustering significantly different between Bull and Bear?
print("\nTest 3: Vol clustering comparison (Bull vs Bear)")
bull_sq = (spy_df[spy_df["phase"] == "Bull"]["ret"].dropna() ** 2)
bear_sq = (spy_df[spy_df["phase"] == "Bear"]["ret"].dropna() ** 2)

if len(bull_sq) > 50 and len(bear_sq) > 50:
    # Bootstrap ACF(1) difference
    n_boot = 5000
    bull_acf1_boot = []
    bear_acf1_boot = []

    for _ in range(n_boot):
        # Block bootstrap (blocks of 20)
        block_size = 20

        # Bull
        n_blocks = len(bull_sq) // block_size + 1
        indices = np.random.randint(0, len(bull_sq) - block_size, n_blocks)
        sample = np.concatenate([bull_sq.values[i:i+block_size] for i in indices])[:len(bull_sq)]
        s = pd.Series(sample)
        bull_acf1_boot.append(s.autocorr(lag=1))

        # Bear
        n_blocks = len(bear_sq) // block_size + 1
        indices = np.random.randint(0, len(bear_sq) - block_size, n_blocks)
        sample = np.concatenate([bear_sq.values[i:i+block_size] for i in indices])[:len(bear_sq)]
        s = pd.Series(sample)
        bear_acf1_boot.append(s.autocorr(lag=1))

    bull_acf1_arr = np.array(bull_acf1_boot)
    bear_acf1_arr = np.array(bear_acf1_boot)
    diff = bear_acf1_arr - bull_acf1_arr

    print(f"  Bull ACF(1) mean: {np.nanmean(bull_acf1_arr):.4f} (95% CI: [{np.nanpercentile(bull_acf1_arr, 2.5):.4f}, {np.nanpercentile(bull_acf1_arr, 97.5):.4f}])")
    print(f"  Bear ACF(1) mean: {np.nanmean(bear_acf1_arr):.4f} (95% CI: [{np.nanpercentile(bear_acf1_arr, 2.5):.4f}, {np.nanpercentile(bear_acf1_arr, 97.5):.4f}])")
    print(f"  Difference (Bear-Bull): {np.nanmean(diff):.4f} (95% CI: [{np.nanpercentile(diff, 2.5):.4f}, {np.nanpercentile(diff, 97.5):.4f}])")
    ci_lower = np.nanpercentile(diff, 2.5)
    ci_upper = np.nanpercentile(diff, 97.5)
    print(f"  {'Significant' if (ci_lower > 0 or ci_upper < 0) else 'Not significant'}: CI {'excludes' if (ci_lower > 0 or ci_upper < 0) else 'includes'} zero")

# Test 4: VT alpha significance by phase (t-test on daily return differences)
print("\nTest 4: VT alpha significance by phase (t-test on daily return diff)")
for phase in phases:
    mask = spy_df_gld["phase"] == phase
    subset = spy_df_gld[mask]
    if len(subset) < 30:
        continue

    diff_daily = subset["ret_vt"] - subset["ret_5050"]
    t_stat, p_val = stats.ttest_1samp(diff_daily.dropna(), 0)

    print(f"  {phase}: t={t_stat:.3f}, p={p_val:.4f}, mean_diff={diff_daily.mean()*10000:.2f} bps/day")
    print(f"    {'Significant' if p_val < 0.05 else 'Not significant'} at 5% level")

# ── 12. Save Results ───────────────────────────────────────────────────

output = {
    "experiment": "K391",
    "title": "Volatility Across Market Cycles",
    "data_source": "yfinance (SPY, GLD, ^VIX)",
    "period": "2000-01-01 to 2024-12-31",
    "methodology": "4-phase classification using 200-day and 50-day MAs",
    "phase_definitions": {
        "Bull": "Close > MA200 AND MA50 > MA200",
        "Bear": "Close < MA200 AND MA50 < MA200",
        "Recovery": "Close < MA200 AND MA50 > MA200 (structure improving but price below)",
        "Distribution": "Close > MA200 AND MA50 < MA200 (price above but structure deteriorating)",
    },
    "phase_statistics": results,
    "vt_strategy_by_phase": vt_results,
    "phase_transitions": {
        "total": total_transitions,
        "per_year": round(transitions_per_year, 1),
        "by_decade": decade_transitions,
    },
    "current_phase": {
        "date": str(last_date.date()),
        "phase": current_phase,
        "spy_price": round(float(current_price), 2),
        "ma50": round(float(current_ma50), 2),
        "ma200": round(float(current_ma200), 2),
        "vix": round(float(current_vix), 2),
        "days_in_phase": int(current_duration),
    },
    "limitations": [
        "MA-based classification is backward-looking and creates classification lag",
        "Phase transitions are only identified after the fact",
        "GLD data only from 2004, limiting VT analysis to 2004-2024",
        "VT strategy uses simple VIX thresholds, not optimized",
        "No transaction costs in VT analysis",
        "Classification does not account for sector rotation or breadth",
    ],
}

output_path = "/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a6a80c15/experiments/k391_market_cycles_results.json"
with open(output_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nResults saved to: {output_path}")
print("\n" + "=" * 70)
print("K391 COMPLETE")
print("=" * 70)
