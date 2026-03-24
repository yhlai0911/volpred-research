"""
K270: Rate Hike Regime Detection — Can We Identify When GLD Hedge Will Fail?
=============================================================================
Background: K269 showed GLD hedge fails during rate-hike crises (2022 corr=0.44).
If we could detect this regime in advance, we could switch from GLD to TIP/SHY/cash.

Data: SPY, GLD, TLT, TIP, SHY, ^VIX daily from yfinance, 2005-2024.

Methodology:
  1. Rate-hike regime indicators (each binary 0/1):
     - TLT drawdown from rolling peak > 10% (bonds falling = rates rising)
     - TLT-SHY spread narrowing (yield curve flattening signal)
     - TIP/TLT ratio rising (real rates rising faster than nominal)
     - VIX elevated but not spiking (grind, not crash)
  2. Composite rate-hike score (0-4)
  3. Adaptive strategies when score >= threshold:
     a. Replace GLD with TIP in 50/50
     b. Replace GLD with SHY in 50/50
     c. Move to 60% cash + 40% SPY (pure defensive)
  4. Compare vs static 50/50 SPY/GLD + 12/VIX VT
  5. 2022 acid test + full-period analysis
  6. 5-period cross-OOS validation

Statistical constraints:
  - Harvey t > 3.0 for strategy claims
  - DM test vs static 50/50
  - Net of TX cost 0.1% per switch
  - Lagged signals only (signal_t → weight_{t+1})

[提出: User (K269 follow-up), 執行: Claude]
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
print("K270: Rate Hike Regime Detection")
print("=" * 70)

print("\n[1/7] Downloading data from yfinance...")

tickers = {
    "SPY": "SPY",
    "GLD": "GLD",
    "TLT": "TLT",
    "TIP": "TIP",
    "SHY": "SHY",
    "VIX": "^VIX",
}

prices = {}
for name, ticker in tickers.items():
    raw = yf.download(ticker, start="2004-01-01", end="2025-01-01", progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    col = "Adj Close" if "Adj Close" in raw.columns else "Close"
    prices[name] = raw[col].copy()
    prices[name].name = name
    print(f"  {name}: {len(raw)} rows, {raw.index[0].strftime('%Y-%m-%d')} to {raw.index[-1].strftime('%Y-%m-%d')}")

# Combine into single DataFrame, forward-fill for holidays
df = pd.DataFrame(prices)
df = df.ffill().dropna()
print(f"\n  Combined: {len(df)} rows, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# Calculate returns
rets = df.pct_change().dropna()

# ============================================================
# 2. Build rate-hike regime indicators
# ============================================================
print("\n[2/7] Building rate-hike regime indicators...")

# --- Indicator 1: TLT drawdown from rolling 252d peak ---
tlt_peak = df["TLT"].rolling(252, min_periods=1).max()
tlt_dd = (df["TLT"] - tlt_peak) / tlt_peak
ind_tlt_dd = (tlt_dd < -0.10).astype(int)
ind_tlt_dd.name = "TLT_DD_10pct"

# --- Indicator 2: TLT-SHY spread narrowing ---
# Use rolling 63d return spread; when TLT underperforms SHY significantly,
# rates are rising (TLT more sensitive to rate changes)
tlt_ret63 = df["TLT"].pct_change(63)
shy_ret63 = df["SHY"].pct_change(63)
tlt_shy_spread = tlt_ret63 - shy_ret63
# Signal: TLT underperforming SHY by more than 5% over 3 months
ind_spread = (tlt_shy_spread < -0.05).astype(int)
ind_spread.name = "TLT_SHY_spread"

# --- Indicator 3: TIP/TLT ratio rising ---
# When TIP outperforms TLT, real rates are rising faster than nominal
# (or inflation expectations are rising = rate hikes likely)
tip_tlt_ratio = df["TIP"] / df["TLT"]
tip_tlt_ratio_ma = tip_tlt_ratio.rolling(63).mean()
tip_tlt_ratio_rising = (tip_tlt_ratio > tip_tlt_ratio_ma * 1.02).astype(int)
ind_tip_tlt = tip_tlt_ratio_rising
ind_tip_tlt.name = "TIP_TLT_rising"

# --- Indicator 4: VIX elevated but not spiking (grind) ---
# VIX between 20 and 35 = elevated concern but no panic crash
# (crashes tend to be VIX > 35-40 spikes)
vix = df["VIX"]
ind_vix_grind = ((vix > 20) & (vix < 35)).astype(int)
ind_vix_grind.name = "VIX_grind"

# --- Composite score ---
indicators = pd.DataFrame({
    "TLT_DD": ind_tlt_dd,
    "TLT_SHY": ind_spread,
    "TIP_TLT": ind_tip_tlt,
    "VIX_grind": ind_vix_grind,
}, index=df.index).dropna()

composite = indicators.sum(axis=1)
composite.name = "rate_hike_score"

# Align everything
common_idx = rets.index.intersection(composite.index)
rets = rets.loc[common_idx]
composite = composite.loc[common_idx]
indicators = indicators.loc[common_idx]

print(f"  Analysis period: {common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')}")
print(f"  Total trading days: {len(common_idx)}")

# Score distribution
print("\n  Composite Score Distribution:")
for score in range(5):
    count = (composite == score).sum()
    pct = count / len(composite) * 100
    print(f"    Score {score}: {count:5d} days ({pct:5.1f}%)")

# ============================================================
# 3. Analyze GLD hedge effectiveness by regime
# ============================================================
print("\n[3/7] Analyzing GLD hedge effectiveness by regime score...")

print("\n  SPY-GLD correlation by rate-hike score:")
print(f"  {'Score':<8} {'Days':<8} {'Corr(SPY,GLD)':<16} {'GLD ret (ann)':<16} {'SPY ret (ann)':<16}")
print("  " + "-" * 64)
for score in range(5):
    mask = composite == score
    if mask.sum() < 30:
        continue
    corr = rets.loc[mask, "SPY"].corr(rets.loc[mask, "GLD"])
    gld_ann = rets.loc[mask, "GLD"].mean() * 252
    spy_ann = rets.loc[mask, "SPY"].mean() * 252
    print(f"  {score:<8} {mask.sum():<8} {corr:>+.4f}          {gld_ann:>+.4f}          {spy_ann:>+.4f}")

# High score (>=3) vs low score (<3)
high_mask = composite >= 3
low_mask = composite < 3
corr_high = rets.loc[high_mask, "SPY"].corr(rets.loc[high_mask, "GLD"])
corr_low = rets.loc[low_mask, "SPY"].corr(rets.loc[low_mask, "GLD"])
print(f"\n  Score >= 3 (rate hike): corr = {corr_high:+.4f} ({high_mask.sum()} days)")
print(f"  Score <  3 (normal):    corr = {corr_low:+.4f} ({low_mask.sum()} days)")

# 2022 specific analysis
mask_2022 = (rets.index >= "2022-01-01") & (rets.index < "2023-01-01")
if mask_2022.sum() > 0:
    avg_score_2022 = composite.loc[mask_2022].mean()
    pct_high_2022 = (composite.loc[mask_2022] >= 3).mean() * 100
    corr_2022 = rets.loc[mask_2022, "SPY"].corr(rets.loc[mask_2022, "GLD"])
    print(f"\n  2022 Analysis (the acid test):")
    print(f"    Average score: {avg_score_2022:.2f}")
    print(f"    Days with score >= 3: {pct_high_2022:.1f}%")
    print(f"    SPY-GLD corr: {corr_2022:+.4f}")

# ============================================================
# 4. Define strategies
# ============================================================
print("\n[4/7] Defining and backtesting strategies...")

# 12/VIX weight function
def calc_vt_weight(vix_series):
    """12/VIX weight, capped [0,1], lagged by 1 day."""
    w = (12.0 / vix_series).clip(0, 1)
    return w.shift(1)  # Lag: signal_t → weight_{t+1}

vix_aligned = df["VIX"].loc[common_idx]
vt_weight = calc_vt_weight(vix_aligned)

# Lag the composite score by 1 day (signal_t → allocation_{t+1})
composite_lag = composite.shift(1)

# Transaction cost tracking
TX_COST = 0.001  # 10 bps per switch

def backtest_strategy(name, spy_w, gld_w, tip_w, shy_w, cash_w, vt_w, rets_df):
    """
    Backtest a portfolio with given asset weights and VT scaling.
    All weights are Series aligned to rets_df.index.
    Returns: daily return series, turnover count.
    """
    # Portfolio return = VT_weight * (weighted sum of asset returns) + (1-VT_weight) * cash
    asset_ret = (spy_w * rets_df["SPY"] + gld_w * rets_df["GLD"] +
                 tip_w * rets_df["TIP"] + shy_w * rets_df["SHY"])
    # Cash return approximated as SHY return for simplicity
    cash_ret = rets_df["SHY"]

    port_ret = vt_w * asset_ret + (1 - vt_w) * cash_ret

    # Count allocation switches for TX cost
    total_w = spy_w + gld_w + tip_w + shy_w + cash_w
    switches = (total_w.diff().abs() > 0.01).sum()

    return port_ret.dropna(), switches

# Strategy allocation weights (all as Series)
strategies = {}

# --- Strategy 0: Static 50/50 SPY/GLD + 12/VIX (benchmark) ---
spy_w_static = pd.Series(0.5, index=common_idx)
gld_w_static = pd.Series(0.5, index=common_idx)
tip_w_static = pd.Series(0.0, index=common_idx)
shy_w_static = pd.Series(0.0, index=common_idx)
cash_w_static = pd.Series(0.0, index=common_idx)

strategies["Static 50/50+VT"] = {
    "spy_w": spy_w_static, "gld_w": gld_w_static,
    "tip_w": tip_w_static, "shy_w": shy_w_static,
    "cash_w": cash_w_static, "vt_w": vt_weight,
}

# --- Strategy 1: Adaptive — replace GLD with TIP when score >= 3 ---
rate_hike_flag = (composite_lag >= 3).astype(float)
spy_w_tip = pd.Series(0.5, index=common_idx)
gld_w_tip = 0.5 * (1 - rate_hike_flag)
tip_w_tip = 0.5 * rate_hike_flag
shy_w_tip = pd.Series(0.0, index=common_idx)
cash_w_tip = pd.Series(0.0, index=common_idx)

strategies["Adaptive TIP+VT (>=3)"] = {
    "spy_w": spy_w_tip, "gld_w": gld_w_tip,
    "tip_w": tip_w_tip, "shy_w": shy_w_tip,
    "cash_w": cash_w_tip, "vt_w": vt_weight,
}

# --- Strategy 2: Adaptive — replace GLD with SHY when score >= 3 ---
spy_w_shy = pd.Series(0.5, index=common_idx)
gld_w_shy = 0.5 * (1 - rate_hike_flag)
tip_w_shy = pd.Series(0.0, index=common_idx)
shy_w_shy = 0.5 * rate_hike_flag
cash_w_shy = pd.Series(0.0, index=common_idx)

strategies["Adaptive SHY+VT (>=3)"] = {
    "spy_w": spy_w_shy, "gld_w": gld_w_shy,
    "tip_w": tip_w_shy, "shy_w": shy_w_shy,
    "cash_w": cash_w_shy, "vt_w": vt_weight,
}

# --- Strategy 3: Defensive — 40% SPY + 60% cash when score >= 3 ---
spy_w_def = 0.5 * (1 - rate_hike_flag) + 0.4 * rate_hike_flag
gld_w_def = 0.5 * (1 - rate_hike_flag)
tip_w_def = pd.Series(0.0, index=common_idx)
shy_w_def = pd.Series(0.0, index=common_idx)
cash_w_def = 0.6 * rate_hike_flag

strategies["Defensive 40/60+VT (>=3)"] = {
    "spy_w": spy_w_def, "gld_w": gld_w_def,
    "tip_w": tip_w_def, "shy_w": shy_w_def,
    "cash_w": cash_w_def, "vt_w": vt_weight,
}

# --- Strategy 4: Adaptive TIP with score >= 2 (more sensitive) ---
rate_hike_flag_2 = (composite_lag >= 2).astype(float)
spy_w_tip2 = pd.Series(0.5, index=common_idx)
gld_w_tip2 = 0.5 * (1 - rate_hike_flag_2)
tip_w_tip2 = 0.5 * rate_hike_flag_2
shy_w_tip2 = pd.Series(0.0, index=common_idx)
cash_w_tip2 = pd.Series(0.0, index=common_idx)

strategies["Adaptive TIP+VT (>=2)"] = {
    "spy_w": spy_w_tip2, "gld_w": gld_w_tip2,
    "tip_w": tip_w_tip2, "shy_w": shy_w_tip2,
    "cash_w": cash_w_tip2, "vt_w": vt_weight,
}

# --- Strategy 5: Buy & Hold SPY (reference) ---
strategies["Buy&Hold SPY"] = {
    "spy_w": pd.Series(1.0, index=common_idx),
    "gld_w": pd.Series(0.0, index=common_idx),
    "tip_w": pd.Series(0.0, index=common_idx),
    "shy_w": pd.Series(0.0, index=common_idx),
    "cash_w": pd.Series(0.0, index=common_idx),
    "vt_w": pd.Series(1.0, index=common_idx),
}

# --- Strategy 6: Gradual scaling — reduce GLD proportional to score ---
# score 0-1: full GLD, score 2: 75% GLD + 25% TIP, score 3: 50/50, score 4: 25% GLD + 75% TIP
score_lag = composite_lag.clip(0, 4)
gld_frac = (1 - score_lag / 4.0).clip(0, 1)
tip_frac = (score_lag / 4.0).clip(0, 1)
strategies["Gradual TIP+VT"] = {
    "spy_w": pd.Series(0.5, index=common_idx),
    "gld_w": 0.5 * gld_frac,
    "tip_w": 0.5 * tip_frac,
    "shy_w": pd.Series(0.0, index=common_idx),
    "cash_w": pd.Series(0.0, index=common_idx),
    "vt_w": vt_weight,
}

# ============================================================
# 5. Run backtests — full period and sub-periods
# ============================================================
print("\n[5/7] Running backtests...")

def calc_metrics(ret_series, name=""):
    """Calculate standard performance metrics."""
    ret = ret_series.dropna()
    if len(ret) < 30:
        return None

    ann_ret = ret.mean() * 252
    ann_vol = ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    cum = (1 + ret).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Sortino
    downside = ret[ret < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Sharpe t-stat
    n_years = len(ret) / 252
    sharpe_t = sharpe * np.sqrt(n_years)

    return {
        "name": name,
        "ann_ret": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "sharpe_t": sharpe_t,
        "mdd": mdd,
        "sortino": sortino,
        "calmar": calmar,
        "n_days": len(ret),
    }

# Full period backtest
print("\n  === Full Period Results ===")
print(f"  {'Strategy':<30} {'Ann Ret':>8} {'Ann Vol':>8} {'Sharpe':>8} {'MDD':>8} {'Sortino':>8} {'Calmar':>8} {'Sharpe-t':>9}")
print("  " + "-" * 111)

full_results = {}
full_returns = {}

for strat_name, weights in strategies.items():
    port_ret = (weights["vt_w"] * (
        weights["spy_w"] * rets["SPY"] +
        weights["gld_w"] * rets["GLD"] +
        weights["tip_w"] * rets["TIP"] +
        weights["shy_w"] * rets["SHY"]
    ) + (1 - weights["vt_w"]) * rets["SHY"]).dropna()

    # Apply TX cost for switches
    if "Static" not in strat_name and "Buy" not in strat_name:
        # Detect switches in allocation
        if "Adaptive" in strat_name or "Defensive" in strat_name:
            flag = rate_hike_flag if ">=3" in strat_name else rate_hike_flag_2
            switch_days = flag.diff().abs() > 0.01
        elif "Gradual" in strat_name:
            switch_days = gld_frac.diff().abs() > 0.01
        else:
            switch_days = pd.Series(False, index=common_idx)

        tx_cost_series = switch_days.astype(float) * TX_COST
        port_ret = port_ret - tx_cost_series.reindex(port_ret.index).fillna(0)

    full_returns[strat_name] = port_ret
    m = calc_metrics(port_ret, strat_name)
    if m:
        full_results[strat_name] = m
        print(f"  {strat_name:<30} {m['ann_ret']:>+.4f}  {m['ann_vol']:>.4f}  {m['sharpe']:>+.4f}  {m['mdd']:>+.4f}  {m['sortino']:>+.4f}  {m['calmar']:>+.4f}  {m['sharpe_t']:>+.4f}")

# Count switches
for strat_name in strategies:
    if "Adaptive" in strat_name or "Defensive" in strat_name:
        flag = rate_hike_flag if ">=3" in strat_name else rate_hike_flag_2
        n_switches = (flag.diff().abs() > 0.01).sum()
        n_years = len(common_idx) / 252
        print(f"  {strat_name}: {n_switches} switches ({n_switches/n_years:.1f}/yr)")

# ============================================================
# 6. 2022 Acid Test
# ============================================================
print("\n\n  === 2022 Acid Test (Rate Hike Crisis) ===")
print(f"  {'Strategy':<30} {'2022 Ret':>10} {'2022 MDD':>10} {'2022 Vol':>10} {'2022 Sharpe':>12}")
print("  " + "-" * 72)

for strat_name, port_ret in full_returns.items():
    mask_2022_s = (port_ret.index >= "2022-01-01") & (port_ret.index < "2023-01-01")
    r2022 = port_ret.loc[mask_2022_s]
    if len(r2022) < 10:
        continue
    ann_ret = r2022.mean() * 252
    ann_vol = r2022.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + r2022).cumprod()
    peak = cum.cummax()
    mdd = ((cum - peak) / peak).min()
    print(f"  {strat_name:<30} {ann_ret:>+.4f}    {mdd:>+.4f}    {ann_vol:>.4f}    {sharpe:>+.4f}")

# Also test specific sub-periods
sub_periods = {
    "2008 GFC": ("2008-01-01", "2009-01-01"),
    "2013 Taper Tantrum": ("2013-05-01", "2013-12-31"),
    "2018 Rate Hikes": ("2018-01-01", "2019-01-01"),
    "2020 COVID": ("2020-01-01", "2021-01-01"),
    "2022 Rate Hikes": ("2022-01-01", "2023-01-01"),
    "2023-24 High Rates": ("2023-01-01", "2025-01-01"),
}

print("\n\n  === Strategy Performance by Crisis Period ===")
print(f"  {'Period':<22} {'Static 50/50':>14} {'Adpt TIP(3)':>14} {'Adpt SHY(3)':>14} {'Def 40/60':>14} {'Gradual TIP':>14}")
print("  " + "-" * 92)

for period_name, (start, end) in sub_periods.items():
    vals = []
    skip = False
    for sn in ["Static 50/50+VT", "Adaptive TIP+VT (>=3)", "Adaptive SHY+VT (>=3)",
                "Defensive 40/60+VT (>=3)", "Gradual TIP+VT"]:
        sr = full_returns[sn]
        mask_sr = (sr.index >= start) & (sr.index < end)
        r = sr.loc[mask_sr]
        if len(r) < 10:
            skip = True
            break
        cum_ret = (1 + r).prod() - 1
        vals.append(f"{cum_ret:>+.4f}")
    if skip:
        continue

    print(f"  {period_name:<22} {'  '.join(vals)}")

# ============================================================
# 7. Cross-OOS Validation (5 periods)
# ============================================================
print("\n\n[6/7] Cross-OOS Validation (5 periods)...")

oos_periods = [
    ("2007-2010", "2007-01-01", "2011-01-01"),
    ("2011-2014", "2011-01-01", "2015-01-01"),
    ("2015-2018", "2015-01-01", "2019-01-01"),
    ("2019-2022", "2019-01-01", "2023-01-01"),
    ("2023-2024", "2023-01-01", "2025-01-01"),
]

# Compare best adaptive vs static benchmark
best_adaptive = "Adaptive TIP+VT (>=3)"  # Will check which is best
benchmark = "Static 50/50+VT"

print(f"\n  Comparing '{best_adaptive}' vs '{benchmark}' across OOS periods")
print(f"\n  {'Period':<14} {'Bench Sharpe':>13} {'Adapt Sharpe':>13} {'Delta':>8} {'DM t-stat':>10} {'DM p-val':>9} {'Winner':>10}")
print("  " + "-" * 77)

oos_wins = 0
oos_results = []

for period_name, start, end in oos_periods:
    bench_sr = full_returns[benchmark]
    adapt_sr = full_returns[best_adaptive]

    r_bench = bench_sr.loc[(bench_sr.index >= start) & (bench_sr.index < end)].dropna()
    r_adapt = adapt_sr.loc[(adapt_sr.index >= start) & (adapt_sr.index < end)].dropna()

    # Align
    common = r_bench.index.intersection(r_adapt.index)
    r_bench = r_bench.loc[common]
    r_adapt = r_adapt.loc[common]

    if len(common) < 60:
        continue

    m_bench = calc_metrics(r_bench, benchmark)
    m_adapt = calc_metrics(r_adapt, best_adaptive)

    # Diebold-Mariano test (using squared returns as loss proxy)
    # Loss = -return (we want higher returns)
    d = r_adapt - r_bench  # Positive = adaptive better
    dm_t = d.mean() / (d.std() / np.sqrt(len(d))) if d.std() > 0 else 0
    dm_p = 1 - stats.t.cdf(dm_t, df=len(d)-1)  # One-sided: adaptive > benchmark

    delta_sharpe = m_adapt["sharpe"] - m_bench["sharpe"]
    winner = best_adaptive.split("+")[0] if delta_sharpe > 0 else benchmark.split("+")[0]
    if delta_sharpe > 0:
        oos_wins += 1

    oos_results.append({
        "period": period_name,
        "bench_sharpe": m_bench["sharpe"],
        "adapt_sharpe": m_adapt["sharpe"],
        "delta": delta_sharpe,
        "dm_t": dm_t,
        "dm_p": dm_p,
        "winner": winner,
    })

    print(f"  {period_name:<14} {m_bench['sharpe']:>+.4f}       {m_adapt['sharpe']:>+.4f}       {delta_sharpe:>+.4f}  {dm_t:>+.4f}     {dm_p:>.4f}    {winner}")

print(f"\n  Adaptive wins: {oos_wins}/{len(oos_results)} periods")

# ============================================================
# 8. Statistical tests — full period
# ============================================================
print("\n\n[7/7] Statistical Tests (Full Period)...")

print("\n  DM Test: Each adaptive strategy vs Static 50/50+VT")
print(f"  {'Strategy':<30} {'DM t-stat':>10} {'DM p-val':>10} {'Significant':>12}")
print("  " + "-" * 62)

r_bench_full = full_returns[benchmark].dropna()

for strat_name in ["Adaptive TIP+VT (>=3)", "Adaptive SHY+VT (>=3)",
                     "Defensive 40/60+VT (>=3)", "Adaptive TIP+VT (>=2)", "Gradual TIP+VT"]:
    r_strat = full_returns[strat_name].dropna()
    common = r_bench_full.index.intersection(r_strat.index)
    rb = r_bench_full.loc[common]
    rs = r_strat.loc[common]

    d = rs - rb
    dm_t = d.mean() / (d.std() / np.sqrt(len(d))) if d.std() > 0 else 0
    dm_p = 1 - stats.t.cdf(dm_t, df=len(d)-1)
    sig = "YES (p<0.05)" if dm_p < 0.05 else "no"
    harvey = " [Harvey t>3]" if abs(dm_t) > 3.0 else ""
    print(f"  {strat_name:<30} {dm_t:>+.4f}     {dm_p:>.4f}     {sig}{harvey}")

# Correlation analysis: does the detector actually predict GLD-SPY correlation?
print("\n\n  === Regime Detection Accuracy ===")
# Rolling 63d correlation
rolling_corr = rets["SPY"].rolling(63).corr(rets["GLD"])
rolling_corr.name = "SPY_GLD_corr"

# Does high composite score predict high correlation (GLD failure)?
for threshold in [2, 3, 4]:
    high = composite_lag >= threshold
    high = high.reindex(rolling_corr.index).fillna(False)
    corr_when_high = rolling_corr.loc[high].mean()
    corr_when_low = rolling_corr.loc[~high].mean()
    n_high = high.sum()

    # t-test for difference
    if high.sum() > 30 and (~high).sum() > 30:
        t_val, p_val = stats.ttest_ind(
            rolling_corr.loc[high].dropna(),
            rolling_corr.loc[~high].dropna()
        )
    else:
        t_val, p_val = 0, 1

    print(f"  Score >= {threshold}: avg corr = {corr_when_high:+.4f} (n={n_high}), "
          f"Score < {threshold}: avg corr = {corr_when_low:+.4f}, "
          f"diff t={t_val:+.3f}, p={p_val:.4f}")

# ============================================================
# 9. Individual indicator analysis
# ============================================================
print("\n\n  === Individual Indicator Effectiveness ===")
print(f"  {'Indicator':<16} {'Avg corr ON':>14} {'Avg corr OFF':>14} {'Diff':>8} {'t-stat':>8} {'p-val':>8}")
print("  " + "-" * 68)

for ind_name in ["TLT_DD", "TLT_SHY", "TIP_TLT", "VIX_grind"]:
    ind = indicators[ind_name].shift(1).reindex(rolling_corr.index).fillna(0)
    on_mask = ind == 1
    off_mask = ind == 0

    corr_on = rolling_corr.loc[on_mask].dropna()
    corr_off = rolling_corr.loc[off_mask].dropna()

    if len(corr_on) > 30 and len(corr_off) > 30:
        t_val, p_val = stats.ttest_ind(corr_on, corr_off)
        print(f"  {ind_name:<16} {corr_on.mean():>+.4f}        {corr_off.mean():>+.4f}        "
              f"{corr_on.mean()-corr_off.mean():>+.4f}  {t_val:>+.3f}  {p_val:>.4f}")
    else:
        print(f"  {ind_name:<16} insufficient data")

# ============================================================
# 10. Summary and conclusion
# ============================================================
print("\n\n" + "=" * 70)
print("SUMMARY: K270 Rate Hike Regime Detection")
print("=" * 70)

# Find best adaptive strategy
best_strat = None
best_sharpe_improvement = -999
for sn in ["Adaptive TIP+VT (>=3)", "Adaptive SHY+VT (>=3)",
            "Defensive 40/60+VT (>=3)", "Adaptive TIP+VT (>=2)", "Gradual TIP+VT"]:
    if sn in full_results and benchmark in full_results:
        delta = full_results[sn]["sharpe"] - full_results[benchmark]["sharpe"]
        if delta > best_sharpe_improvement:
            best_sharpe_improvement = delta
            best_strat = sn

print(f"\n  Best adaptive strategy: {best_strat}")
print(f"  Sharpe improvement vs static 50/50: {best_sharpe_improvement:+.4f}")
print(f"  Benchmark (Static 50/50+VT) Sharpe: {full_results[benchmark]['sharpe']:+.4f}")
if best_strat:
    print(f"  Best adaptive Sharpe:                {full_results[best_strat]['sharpe']:+.4f}")
    print(f"  Best adaptive MDD:                   {full_results[best_strat]['mdd']:+.4f}")
    print(f"  Benchmark MDD:                       {full_results[benchmark]['mdd']:+.4f}")

# 2022 specific
if best_strat:
    r_bench_full_s = full_returns[benchmark]
    r_adapt_full_s = full_returns[best_strat]
    mask_bench_2022 = (r_bench_full_s.index >= "2022-01-01") & (r_bench_full_s.index < "2023-01-01")
    mask_adapt_2022 = (r_adapt_full_s.index >= "2022-01-01") & (r_adapt_full_s.index < "2023-01-01")
if best_strat and mask_bench_2022.sum() > 0:
    r_bench_2022 = r_bench_full_s.loc[mask_bench_2022]
    r_adapt_2022 = r_adapt_full_s.loc[mask_adapt_2022]
    bench_2022_ret = (1 + r_bench_2022).prod() - 1
    adapt_2022_ret = (1 + r_adapt_2022).prod() - 1
    print(f"\n  2022 cumulative return:")
    print(f"    Static 50/50+VT: {bench_2022_ret:+.4f}")
    print(f"    {best_strat}: {adapt_2022_ret:+.4f}")

print(f"\n  Cross-OOS wins: {oos_wins}/{len(oos_results)}")

# Final assessment
harvey_pass = False
if best_strat and best_strat in full_results:
    harvey_pass = abs(full_results[best_strat]["sharpe_t"]) > 3.0

print(f"\n  Harvey (2016) t > 3.0 threshold: {'PASS' if harvey_pass else 'FAIL'}")

# Assess statistical significance
sig_count = 0
for r in oos_results:
    if r["dm_p"] < 0.05 and r["delta"] > 0:
        sig_count += 1
print(f"  Significant OOS periods (DM p<0.05): {sig_count}/{len(oos_results)}")

# Limitations
print(f"""
  LIMITATIONS:
  - Rate-hike indicators are backward-looking (TLT drawdown, spread)
  - Composite score thresholds not optimized (avoids data-snooping)
  - TIP data starts 2005 (shorter history)
  - 2022 is the only severe rate-hike episode in sample
  - TX costs assumed 10 bps per switch (conservative for ETFs)
  - VT weight uses same 12/VIX for all strategies
  - Forward-fill used for holiday alignment
""")

# ============================================================
# 11. Save results
# ============================================================
results_data = {
    "experiment": "K270",
    "title": "Rate Hike Regime Detection",
    "timestamp": datetime.now().isoformat(),
    "data_source": "yfinance",
    "assets": ["SPY", "GLD", "TLT", "TIP", "SHY", "VIX"],
    "period": f"{common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')}",
    "n_days": len(common_idx),
    "score_distribution": {str(i): int((composite == i).sum()) for i in range(5)},
    "full_period_results": {
        name: {k: float(v) if isinstance(v, (np.floating, float)) else v
               for k, v in res.items()}
        for name, res in full_results.items()
    },
    "cross_oos_results": oos_results,
    "cross_oos_wins": oos_wins,
    "cross_oos_total": len(oos_results),
    "best_adaptive": best_strat,
    "best_sharpe_improvement": float(best_sharpe_improvement) if best_sharpe_improvement != -999 else None,
    "harvey_pass": harvey_pass,
    "methodology": {
        "indicators": [
            "TLT drawdown from 252d peak > 10%",
            "TLT-SHY 63d return spread < -5%",
            "TIP/TLT ratio > 63d MA * 1.02",
            "VIX between 20 and 35 (grind zone)"
        ],
        "composite_threshold": 3,
        "tx_cost_per_switch": 0.001,
        "vt_formula": "12/VIX, lagged 1 day",
        "signal_lag": "1 day (no look-ahead)",
    }
}

output_path = "experiments/k270_rate_hike_results.json"
with open(output_path, "w") as f:
    json.dump(results_data, f, indent=2, default=str)
print(f"\n  Results saved to {output_path}")

print("\n" + "=" * 70)
print("K270 COMPLETE")
print("=" * 70)
