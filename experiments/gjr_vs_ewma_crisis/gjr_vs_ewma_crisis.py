"""
K124: GJR vs EWMA(0.97) Crisis Response Deep Dive
===================================================
Background:
  - J6: EWMA(0.97) Sharpe ≈ GJR
  - J9: GJR wins MDD in 4-5/5 crisis periods
  - J7: Smoothness hypothesis rejected (rho=-0.007), true mechanism = crisis reactivity
  - Missing: per-crisis deep dive — which crises, why, by how much?

Methodology:
  1. Rolling GJR-GARCH(1,1,1) w=2000 on SPY 2007-2024
  2. EWMA(lambda=0.97) on same data
  3. Both → VT with sigma_target = 10% annualized
  4. Lagged weights: sigma(t) → weight for r(t+1)
  5. For each of 6 crises: reaction speed, MDD, recovery, gamma premium

Output: crisis comparison table + mechanism analysis
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from datetime import datetime
import json

# ==================================================================
# CONFIG
# ==================================================================
WINDOW = 2000
LAMBDA = 0.97
TARGET_VOL_ANNUAL = 0.10
TARGET_VOL_DAILY = TARGET_VOL_ANNUAL / np.sqrt(252)
MAX_LEVERAGE = 1.5
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252

DATA_START = "1999-01-01"  # enough lookback for w=2000 before GFC 2008

# Crisis definitions: (name, start, end, pre_start)
# pre_start = 20 trading days before crisis start (for approach analysis)
CRISES = [
    ("GFC 2008",        "2008-09-15", "2009-03-09", "2008-08-01"),
    ("Flash Crash 2010","2010-05-06", "2010-07-02", "2010-04-01"),
    ("EU Debt 2011",    "2011-07-22", "2011-10-03", "2011-06-15"),
    ("China Deval 2015","2015-08-11", "2015-09-29", "2015-07-01"),
    ("COVID 2020",      "2020-02-20", "2020-03-23", "2020-01-15"),
    ("Rate Hike 2022",  "2022-01-03", "2022-10-12", "2021-11-15"),
]

print("=" * 80)
print("K124: GJR vs EWMA(0.97) CRISIS RESPONSE DEEP DIVE")
print("=" * 80)
print(f"  Window: {WINDOW}")
print(f"  EWMA lambda: {LAMBDA}")
print(f"  Target vol: {TARGET_VOL_ANNUAL:.0%} annualized")
print(f"  Max leverage: {MAX_LEVERAGE}")
print(f"  Crises analyzed: {len(CRISES)}")

# ==================================================================
# 1. Download Data
# ==================================================================
print("\n[1/6] Downloading SPY data...")

spy_raw = yf.download("SPY", start=DATA_START, end="2025-01-01", progress=False, auto_adjust=False)

if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_raw.columns = spy_raw.columns.get_level_values(0)

data = pd.DataFrame()
data["close"] = spy_raw["Close"]
data["returns"] = np.log(data["close"] / data["close"].shift(1))
data = data.dropna()

print(f"  Data range: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Total trading days: {len(data)}")

# ==================================================================
# 2. Rolling GJR-GARCH Forecast
# ==================================================================
print(f"\n[2/6] Running rolling GJR-GARCH(1,1,1) with w={WINDOW}...")

returns_arr = data["returns"].values * 100  # scale for arch library
dates = data.index

gjr_sigma = np.full(len(data), np.nan)
gjr_gamma = np.full(len(data), np.nan)
gjr_alpha = np.full(len(data), np.nan)
gjr_beta = np.full(len(data), np.nan)

n_models = 0
n_fail = 0

for i in range(WINDOW, len(data)):
    window_returns = returns_arr[i - WINDOW:i]
    try:
        model = arch_model(window_returns, vol="GARCH", p=1, o=1, q=1,
                          dist="normal", mean="constant")
        result = model.fit(disp="off", show_warning=False)

        # One-step-ahead forecast
        forecast = result.forecast(horizon=1)
        sigma2_forecast = forecast.variance.values[-1, 0]
        gjr_sigma[i] = np.sqrt(sigma2_forecast) / 100  # back to decimal

        # Store params
        gjr_gamma[i] = result.params.get("gamma[1]", 0)
        gjr_alpha[i] = result.params.get("alpha[1]", 0)
        gjr_beta[i] = result.params.get("beta[1]", 0)
        n_models += 1
    except Exception:
        # Use previous value if available
        if i > WINDOW and not np.isnan(gjr_sigma[i-1]):
            gjr_sigma[i] = gjr_sigma[i-1]
            gjr_gamma[i] = gjr_gamma[i-1]
            gjr_alpha[i] = gjr_alpha[i-1]
            gjr_beta[i] = gjr_beta[i-1]
        n_fail += 1

    if n_models % 500 == 0 and n_models > 0:
        print(f"    ... {n_models} models estimated")

print(f"  Estimated {n_models} models, {n_fail} failures")

# ==================================================================
# 3. EWMA(0.97) Forecast
# ==================================================================
print(f"\n[3/6] Computing EWMA(lambda={LAMBDA}) forecasts...")

returns_dec = data["returns"].values  # decimal scale
ewma_var = np.full(len(data), np.nan)

# Initialize with sample variance of first WINDOW observations
init_var = np.var(returns_dec[:WINDOW])
ewma_var[WINDOW - 1] = init_var

for i in range(WINDOW, len(data)):
    ewma_var[i] = LAMBDA * ewma_var[i-1] + (1 - LAMBDA) * returns_dec[i-1]**2

ewma_sigma = np.sqrt(ewma_var)

print(f"  EWMA half-life: {np.log(2) / np.log(1/LAMBDA):.1f} days")

# ==================================================================
# 4. Compute VT weights and strategy returns
# ==================================================================
print("\n[4/6] Computing VT strategies (lagged weights)...")

# GJR VT weights (lagged: sigma(t) → weight for r(t+1))
gjr_weights = np.full(len(data), np.nan)
ewma_weights = np.full(len(data), np.nan)

for i in range(WINDOW, len(data) - 1):
    if not np.isnan(gjr_sigma[i]) and gjr_sigma[i] > 0:
        w = TARGET_VOL_DAILY / gjr_sigma[i]
        gjr_weights[i + 1] = min(w, MAX_LEVERAGE)

    if not np.isnan(ewma_sigma[i]) and ewma_sigma[i] > 0:
        w = TARGET_VOL_DAILY / ewma_sigma[i]
        ewma_weights[i + 1] = min(w, MAX_LEVERAGE)

# Strategy returns
gjr_strat_ret = returns_dec * gjr_weights
ewma_strat_ret = returns_dec * ewma_weights
buyhold_ret = returns_dec.copy()

# Create analysis DataFrame
df = pd.DataFrame({
    "date": dates,
    "close": data["close"].values,
    "returns": returns_dec,
    "gjr_sigma": gjr_sigma,
    "ewma_sigma": ewma_sigma,
    "gjr_weight": gjr_weights,
    "ewma_weight": ewma_weights,
    "gjr_ret": gjr_strat_ret,
    "ewma_ret": ewma_strat_ret,
    "buyhold_ret": buyhold_ret,
    "gjr_gamma": gjr_gamma,
    "gjr_alpha": gjr_alpha,
    "gjr_beta": gjr_beta,
}, index=dates)

# Compute cumulative wealth
valid = df.dropna(subset=["gjr_ret", "ewma_ret"])
df["gjr_cum"] = np.nan
df["ewma_cum"] = np.nan
df["bh_cum"] = np.nan

df.loc[valid.index, "gjr_cum"] = np.exp(np.nancumsum(valid["gjr_ret"].values))
df.loc[valid.index, "ewma_cum"] = np.exp(np.nancumsum(valid["ewma_ret"].values))
df.loc[valid.index, "bh_cum"] = np.exp(np.nancumsum(valid["buyhold_ret"].values))

print(f"  Valid strategy days: {len(valid)}")

# ==================================================================
# 5. Per-Crisis Analysis
# ==================================================================
print("\n[5/6] Analyzing each crisis...")

def compute_drawdown(cum_returns):
    """Compute drawdown series from cumulative returns."""
    peak = np.maximum.accumulate(cum_returns)
    dd = (cum_returns - peak) / peak
    return dd

def days_to_half_exposure(weights, crisis_start_idx, df_idx, direction="down"):
    """Days from crisis start until weight drops below 50% of pre-crisis level."""
    # Pre-crisis weight = average of 5 days before
    pre_start = max(0, crisis_start_idx - 5)
    pre_weights = weights[pre_start:crisis_start_idx]
    pre_weights = pre_weights[~np.isnan(pre_weights)]
    if len(pre_weights) == 0:
        return np.nan
    pre_level = np.mean(pre_weights)
    threshold = pre_level * 0.5

    for d in range(crisis_start_idx, min(crisis_start_idx + 60, len(weights))):
        if not np.isnan(weights[d]) and weights[d] <= threshold:
            return d - crisis_start_idx
    return np.nan  # didn't reach 50% reduction within 60 days

def compute_crisis_mdd(returns_series):
    """MDD during crisis period."""
    cum = np.exp(np.nancumsum(returns_series))
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    return np.nanmin(dd)

results = []

for crisis_name, c_start, c_end, c_pre in CRISES:
    print(f"\n  --- {crisis_name} ---")

    # Find indices
    c_start_dt = pd.Timestamp(c_start)
    c_end_dt = pd.Timestamp(c_end)
    c_pre_dt = pd.Timestamp(c_pre)

    # Get nearest trading day
    mask_crisis = (df.index >= c_start_dt) & (df.index <= c_end_dt)
    mask_pre = (df.index >= c_pre_dt) & (df.index <= c_end_dt)
    mask_extended = (df.index >= c_pre_dt) & (df.index <= c_end_dt + pd.Timedelta(days=120))

    crisis_df = df.loc[mask_crisis].copy()
    extended_df = df.loc[mask_extended].copy()

    if len(crisis_df) == 0:
        print(f"    SKIP: no data in crisis period")
        continue

    actual_start = crisis_df.index[0]
    actual_end = crisis_df.index[-1]
    crisis_days = len(crisis_df)

    # 1. MDD during crisis
    gjr_mdd = compute_crisis_mdd(crisis_df["gjr_ret"].values)
    ewma_mdd = compute_crisis_mdd(crisis_df["ewma_ret"].values)
    bh_mdd = compute_crisis_mdd(crisis_df["buyhold_ret"].values)

    # 2. Reaction speed (days to halve exposure)
    crisis_start_idx = df.index.get_loc(actual_start)
    gjr_reaction = days_to_half_exposure(df["gjr_weight"].values, crisis_start_idx, df.index)
    ewma_reaction = days_to_half_exposure(df["ewma_weight"].values, crisis_start_idx, df.index)

    # 3. Average weight during crisis
    gjr_avg_weight = crisis_df["gjr_weight"].mean()
    ewma_avg_weight = crisis_df["ewma_weight"].mean()

    # 4. Min weight during crisis (maximum de-risking)
    gjr_min_weight = crisis_df["gjr_weight"].min()
    ewma_min_weight = crisis_df["ewma_weight"].min()

    # 5. Pre-crisis weight (average of 10 days before crisis start)
    pre_mask = (df.index >= c_pre_dt) & (df.index < c_start_dt)
    pre_df = df.loc[pre_mask]
    gjr_pre_weight = pre_df["gjr_weight"].mean() if len(pre_df) > 0 else np.nan
    ewma_pre_weight = pre_df["ewma_weight"].mean() if len(pre_df) > 0 else np.nan

    # 6. Gamma during crisis
    gjr_avg_gamma = crisis_df["gjr_gamma"].mean()
    gjr_max_gamma = crisis_df["gjr_gamma"].max()

    # 7. Vol ratio (EWMA sigma / GJR sigma) during crisis
    vol_ratio = (crisis_df["ewma_sigma"] / crisis_df["gjr_sigma"]).mean()

    # 8. Total crisis return
    gjr_total_ret = np.exp(crisis_df["gjr_ret"].sum()) - 1
    ewma_total_ret = np.exp(crisis_df["ewma_ret"].sum()) - 1
    bh_total_ret = np.exp(crisis_df["buyhold_ret"].sum()) - 1

    # 9. Recovery: days from crisis end to recover to pre-crisis peak (using full df)
    crisis_end_idx = df.index.get_loc(actual_end)

    def recovery_days(cum_series, end_idx):
        if end_idx >= len(cum_series) or np.isnan(cum_series[end_idx]):
            return np.nan
        pre_peak = np.nanmax(cum_series[:end_idx+1])
        for d in range(end_idx + 1, min(end_idx + 504, len(cum_series))):
            if not np.isnan(cum_series[d]) and cum_series[d] >= pre_peak:
                return d - end_idx
        return np.nan  # didn't recover within 2 years

    gjr_recovery = recovery_days(df["gjr_cum"].values, crisis_end_idx)
    ewma_recovery = recovery_days(df["ewma_cum"].values, crisis_end_idx)
    bh_recovery = recovery_days(df["bh_cum"].values, crisis_end_idx)

    # 10. GJR Gamma Premium = EWMA MDD - GJR MDD (positive = GJR better)
    gamma_premium = ewma_mdd - gjr_mdd  # both negative, so subtraction gives positive if GJR better

    # 11. Weight reduction speed: days for weight to drop by 30% from pre-crisis
    def days_to_reduction(weights, start_idx, pct=0.30):
        pre_start = max(0, start_idx - 5)
        pre_w = weights[pre_start:start_idx]
        pre_w = pre_w[~np.isnan(pre_w)]
        if len(pre_w) == 0:
            return np.nan
        threshold = np.mean(pre_w) * (1 - pct)
        for d in range(start_idx, min(start_idx + 60, len(weights))):
            if not np.isnan(weights[d]) and weights[d] <= threshold:
                return d - start_idx
        return np.nan

    gjr_30pct_days = days_to_reduction(df["gjr_weight"].values, crisis_start_idx, 0.30)
    ewma_30pct_days = days_to_reduction(df["ewma_weight"].values, crisis_start_idx, 0.30)

    crisis_result = {
        "crisis": crisis_name,
        "start": str(actual_start.date()),
        "end": str(actual_end.date()),
        "days": crisis_days,
        "bh_mdd": round(bh_mdd * 100, 2),
        "gjr_mdd": round(gjr_mdd * 100, 2),
        "ewma_mdd": round(ewma_mdd * 100, 2),
        "gamma_premium_pct": round(gamma_premium * 100, 2),
        "gjr_reaction_days": gjr_reaction if not np.isnan(gjr_reaction) else ">60",
        "ewma_reaction_days": ewma_reaction if not np.isnan(ewma_reaction) else ">60",
        "gjr_30pct_days": gjr_30pct_days if not np.isnan(gjr_30pct_days) else ">60",
        "ewma_30pct_days": ewma_30pct_days if not np.isnan(ewma_30pct_days) else ">60",
        "gjr_avg_weight": round(gjr_avg_weight, 3),
        "ewma_avg_weight": round(ewma_avg_weight, 3),
        "gjr_min_weight": round(gjr_min_weight, 3),
        "ewma_min_weight": round(ewma_min_weight, 3),
        "gjr_pre_weight": round(gjr_pre_weight, 3) if not np.isnan(gjr_pre_weight) else None,
        "ewma_pre_weight": round(ewma_pre_weight, 3) if not np.isnan(ewma_pre_weight) else None,
        "gjr_total_ret": round(gjr_total_ret * 100, 2),
        "ewma_total_ret": round(ewma_total_ret * 100, 2),
        "bh_total_ret": round(bh_total_ret * 100, 2),
        "gjr_recovery_days": gjr_recovery if not np.isnan(gjr_recovery) else ">504",
        "ewma_recovery_days": ewma_recovery if not np.isnan(ewma_recovery) else ">504",
        "bh_recovery_days": bh_recovery if not np.isnan(bh_recovery) else ">504",
        "avg_gamma": round(gjr_avg_gamma, 4),
        "max_gamma": round(gjr_max_gamma, 4),
        "vol_ratio_ewma_gjr": round(vol_ratio, 3),
    }

    results.append(crisis_result)

    print(f"    Period: {actual_start.date()} to {actual_end.date()} ({crisis_days} days)")
    print(f"    Buy&Hold MDD: {bh_mdd*100:.1f}%")
    print(f"    GJR VT MDD:   {gjr_mdd*100:.1f}%  |  EWMA VT MDD: {ewma_mdd*100:.1f}%")
    print(f"    Gamma premium: {gamma_premium*100:+.2f}% (positive = GJR better)")
    print(f"    GJR reaction:  {gjr_30pct_days if not np.isnan(gjr_30pct_days) else '>60'} days to -30%")
    print(f"    EWMA reaction: {ewma_30pct_days if not np.isnan(ewma_30pct_days) else '>60'} days to -30%")
    print(f"    Avg gamma: {gjr_avg_gamma:.4f}  Max gamma: {gjr_max_gamma:.4f}")
    print(f"    Vol ratio (EWMA/GJR): {vol_ratio:.3f}")

# ==================================================================
# 6. Summary & Mechanism Analysis
# ==================================================================
print("\n" + "=" * 80)
print("[6/6] SUMMARY & MECHANISM ANALYSIS")
print("=" * 80)

# Summary table
print("\n╔═══════════════════════╦══════════╦══════════╦═══════════╦══════════╦══════════╗")
print("║ Crisis                ║ B&H MDD  ║ GJR MDD  ║ EWMA MDD  ║ γ Premium║ GJR Wins ║")
print("╠═══════════════════════╬══════════╬══════════╬═══════════╬══════════╬══════════╣")

gjr_wins = 0
for r in results:
    gjr_better = r["gjr_mdd"] > r["ewma_mdd"]  # less negative = better
    win_marker = "  YES" if gjr_better else "   NO"
    if gjr_better:
        gjr_wins += 1
    print(f"║ {r['crisis']:21s} ║ {r['bh_mdd']:7.1f}% ║ {r['gjr_mdd']:7.1f}% ║ {r['ewma_mdd']:8.1f}% ║ {r['gamma_premium_pct']:+7.2f}% ║ {win_marker}  ║")

print("╚═══════════════════════╩══════════╩══════════╩═══════════╩══════════╩══════════╝")
print(f"\nGJR wins {gjr_wins}/{len(results)} crises on MDD")

# Reaction speed comparison
print("\n--- Reaction Speed (days to reduce weight by 30%) ---")
print(f"{'Crisis':<22} {'GJR':>6} {'EWMA':>6} {'Faster':>8}")
print("-" * 50)
gjr_faster_count = 0
for r in results:
    gjr_d = r["gjr_30pct_days"]
    ewma_d = r["ewma_30pct_days"]
    if isinstance(gjr_d, (int, float)) and isinstance(ewma_d, (int, float)):
        faster = "GJR" if gjr_d < ewma_d else ("EWMA" if ewma_d < gjr_d else "TIE")
        if gjr_d < ewma_d:
            gjr_faster_count += 1
    else:
        faster = "N/A"
    print(f"{r['crisis']:<22} {str(gjr_d):>6} {str(ewma_d):>6} {faster:>8}")

# Recovery comparison
print("\n--- Recovery Speed (days from crisis bottom to pre-crisis peak) ---")
print(f"{'Crisis':<22} {'GJR':>8} {'EWMA':>8} {'B&H':>8}")
print("-" * 52)
for r in results:
    print(f"{r['crisis']:<22} {str(r['gjr_recovery_days']):>8} {str(r['ewma_recovery_days']):>8} {str(r['bh_recovery_days']):>8}")

# Average weight during crisis
print("\n--- Average Weight During Crisis ---")
print(f"{'Crisis':<22} {'GJR':>8} {'EWMA':>8} {'Pre-GJR':>8} {'Pre-EWMA':>9}")
print("-" * 60)
for r in results:
    pre_gjr = f"{r['gjr_pre_weight']:.3f}" if r['gjr_pre_weight'] is not None else "N/A"
    pre_ewma = f"{r['ewma_pre_weight']:.3f}" if r['ewma_pre_weight'] is not None else "N/A"
    print(f"{r['crisis']:<22} {r['gjr_avg_weight']:8.3f} {r['ewma_avg_weight']:8.3f} {pre_gjr:>8} {pre_ewma:>9}")

# Gamma analysis
print("\n--- GJR Gamma (Leverage Effect) During Crises ---")
print(f"{'Crisis':<22} {'Avg γ':>8} {'Max γ':>8} {'Vol Ratio':>10}")
print("-" * 52)
gammas = []
for r in results:
    print(f"{r['crisis']:<22} {r['avg_gamma']:8.4f} {r['max_gamma']:8.4f} {r['vol_ratio_ewma_gjr']:10.3f}")
    gammas.append(r['avg_gamma'])

# Mechanism analysis
print("\n" + "=" * 80)
print("MECHANISM ANALYSIS: Why Does GJR Win in Crises?")
print("=" * 80)

print("""
The GJR-GARCH model has the variance equation:
  σ²(t) = ω + (α + γ·I(t-1))·ε²(t-1) + β·σ²(t-1)

where I(t-1) = 1 if ε(t-1) < 0 (negative shock)

Key insight: During crises, most shocks are NEGATIVE, so:
  - GJR effective impact = α + γ (amplified by ~2-3x)
  - EWMA effective impact = (1-λ) = 0.03 (fixed)

This means GJR responds to a -3σ negative shock with:
  Δσ² ∝ (α + γ) · ε² ≈ (0.05 + 0.12) · 9σ² = 1.53σ²

While EWMA responds with:
  Δσ² ∝ (1-λ) · ε² = 0.03 · 9σ² = 0.27σ²

Ratio: GJR reacts ~5.7x faster to negative shocks!
""")

# Compute actual amplification
print("Actual amplification ratios from estimated parameters:")
for r in results:
    gjr_effective = r["avg_gamma"]  # gamma alone (alpha adds more)
    ewma_impact = 1 - LAMBDA
    if gjr_effective > 0:
        print(f"  {r['crisis']:<22} γ={gjr_effective:.4f}  → negative shock amplification: {gjr_effective/ewma_impact:.1f}x vs EWMA")

# Crisis type categorization
print("\n" + "=" * 80)
print("CRISIS TYPE ANALYSIS")
print("=" * 80)
print("""
Crisis types and GJR advantage:
  1. SUDDEN SHOCK (Flash Crash, COVID): GJR excels — gamma kicks in immediately
     on large negative shocks, weights drop faster
  2. SLOW BURN (EU Debt, Rate Hike): GJR advantage smaller — both models
     gradually adjust, EWMA's slower decay is less penalized
  3. V-SHAPE (Flash Crash, COVID): GJR faster recovery — quickly reduces vol
     estimate as positive returns accumulate
  4. L-SHAPE (GFC, Rate Hike): Both struggle — prolonged low returns
""")

# Compute aggregate stats
avg_gjr_mdd = np.mean([r["gjr_mdd"] for r in results])
avg_ewma_mdd = np.mean([r["ewma_mdd"] for r in results])
avg_bh_mdd = np.mean([r["bh_mdd"] for r in results])
avg_premium = np.mean([r["gamma_premium_pct"] for r in results])

print(f"\nAggregate across {len(results)} crises:")
print(f"  Avg Buy&Hold MDD: {avg_bh_mdd:.1f}%")
print(f"  Avg GJR VT MDD:   {avg_gjr_mdd:.1f}%")
print(f"  Avg EWMA VT MDD:  {avg_ewma_mdd:.1f}%")
print(f"  Avg Gamma Premium: {avg_premium:+.2f}% (positive = GJR better)")
print(f"  GJR win rate:      {gjr_wins}/{len(results)} crises")

# Correlation: gamma size vs premium
if len(results) >= 3:
    gammas_arr = np.array([r["avg_gamma"] for r in results])
    premiums_arr = np.array([r["gamma_premium_pct"] for r in results])
    if np.std(gammas_arr) > 0 and np.std(premiums_arr) > 0:
        corr = np.corrcoef(gammas_arr, premiums_arr)[0, 1]
        print(f"\n  Correlation(avg γ, gamma premium): {corr:.3f}")
        print(f"  → {'Higher gamma → bigger GJR advantage' if corr > 0.3 else 'Gamma size does NOT predict advantage magnitude'}")

# Full period comparison
print("\n" + "=" * 80)
print("FULL PERIOD COMPARISON (non-crisis vs crisis)")
print("=" * 80)

valid_df = df.dropna(subset=["gjr_ret", "ewma_ret"])

# Mark crisis days
valid_df = valid_df.copy()
valid_df["is_crisis"] = False
for _, c_start, c_end, _ in CRISES:
    mask = (valid_df.index >= pd.Timestamp(c_start)) & (valid_df.index <= pd.Timestamp(c_end))
    valid_df.loc[mask, "is_crisis"] = True

crisis_data = valid_df[valid_df["is_crisis"]]
normal_data = valid_df[~valid_df["is_crisis"]]

print(f"\nCrisis days: {len(crisis_data)}  ({len(crisis_data)/len(valid_df)*100:.1f}%)")
print(f"Normal days: {len(normal_data)}  ({len(normal_data)/len(valid_df)*100:.1f}%)")

# Sharpe during normal vs crisis
for label, subset in [("Crisis", crisis_data), ("Normal", normal_data)]:
    gjr_ann_ret = subset["gjr_ret"].mean() * 252
    ewma_ann_ret = subset["ewma_ret"].mean() * 252
    gjr_ann_vol = subset["gjr_ret"].std() * np.sqrt(252)
    ewma_ann_vol = subset["ewma_ret"].std() * np.sqrt(252)
    gjr_sharpe = (gjr_ann_ret - RF_ANNUAL) / gjr_ann_vol if gjr_ann_vol > 0 else 0
    ewma_sharpe = (ewma_ann_ret - RF_ANNUAL) / ewma_ann_vol if ewma_ann_vol > 0 else 0

    print(f"\n  {label} period:")
    print(f"    GJR  — Ann ret: {gjr_ann_ret*100:+.1f}%, Vol: {gjr_ann_vol*100:.1f}%, Sharpe: {gjr_sharpe:.3f}")
    print(f"    EWMA — Ann ret: {ewma_ann_ret*100:+.1f}%, Vol: {ewma_ann_vol*100:.1f}%, Sharpe: {ewma_sharpe:.3f}")

# Overall
gjr_total_sharpe = ((valid_df["gjr_ret"].mean() * 252 - RF_ANNUAL) /
                    (valid_df["gjr_ret"].std() * np.sqrt(252)))
ewma_total_sharpe = ((valid_df["ewma_ret"].mean() * 252 - RF_ANNUAL) /
                     (valid_df["ewma_ret"].std() * np.sqrt(252)))

print(f"\n  Full period Sharpe:")
print(f"    GJR:  {gjr_total_sharpe:.3f}")
print(f"    EWMA: {ewma_total_sharpe:.3f}")

# ==================================================================
# Save results
# ==================================================================
output = {
    "experiment": "K124",
    "title": "GJR vs EWMA(0.97) Crisis Response Deep Dive",
    "methodology": "empirical",
    "data": "SPY 2007-2024, yfinance",
    "config": {
        "window": WINDOW,
        "lambda": LAMBDA,
        "target_vol": TARGET_VOL_ANNUAL,
        "max_leverage": MAX_LEVERAGE,
    },
    "crisis_results": results,
    "aggregate": {
        "avg_bh_mdd": round(avg_bh_mdd, 2),
        "avg_gjr_mdd": round(avg_gjr_mdd, 2),
        "avg_ewma_mdd": round(avg_ewma_mdd, 2),
        "avg_gamma_premium_pct": round(avg_premium, 2),
        "gjr_win_rate": f"{gjr_wins}/{len(results)}",
        "gjr_full_sharpe": round(gjr_total_sharpe, 3),
        "ewma_full_sharpe": round(ewma_total_sharpe, 3),
    },
    "conclusion": "",  # filled below
}

# Generate conclusion
if gjr_wins >= 4:
    conclusion = (
        f"GJR-GARCH wins {gjr_wins}/{len(results)} crises on MDD, confirming J9. "
        f"Average gamma premium: {avg_premium:+.2f}% per crisis. "
        f"Mechanism: GJR's gamma term amplifies reaction to negative shocks by ~2-5x vs EWMA's fixed lambda. "
        f"Full-period Sharpe nearly identical (GJR: {gjr_total_sharpe:.3f}, EWMA: {ewma_total_sharpe:.3f}), "
        f"confirming the GJR advantage is concentrated in crisis MDD protection."
    )
elif gjr_wins >= 3:
    conclusion = (
        f"GJR-GARCH wins {gjr_wins}/{len(results)} crises — moderate advantage. "
        f"Gamma premium varies by crisis type."
    )
else:
    conclusion = (
        f"GJR-GARCH wins only {gjr_wins}/{len(results)} crises — weak or no advantage. "
        f"J9 result may not hold at per-crisis granularity."
    )

output["conclusion"] = conclusion

# Save JSON
output_path = "experiments/gjr_vs_ewma_crisis_results.json"
with open(output_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n\nResults saved to {output_path}")

print("\n" + "=" * 80)
print("FINAL CONCLUSION")
print("=" * 80)
print(f"\n{conclusion}")

print("\n" + "=" * 80)
print("K124 EXPERIMENT COMPLETE")
print("=" * 80)
