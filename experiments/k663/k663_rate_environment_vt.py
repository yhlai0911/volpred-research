"""
K663: Interest Rate Environment Impact on VT Strategy Performance
=================================================================
[提出: Claude, 執行: Claude]

Motivation:
  2022 showed rising rates can break traditional hedging (TLT crashed alongside
  stocks). Our VT strategies use GLD not TLT, but how does the rate environment
  affect strategy performance? This matters for strategy recommendations.

Key questions:
  1. Does GLD protect during rising rates? (Expected: mixed — gold hates rising real rates)
  2. Is 50/50 SPY/GLD robust across rate environments?
  3. How badly does TLT-based allocation fail during rising rates?
  4. Should VT strategy adjust for rate environment?
  5. Correlation dynamics: SPY-GLD and SPY-TLT correlation by regime

Rate regimes (based on 6-month change in 10Y yield):
  - Rising:  delta > +50bp
  - Falling: delta < -50bp
  - Stable:  within +/-50bp

Strategies:
  - 12/VIX on SPY (pure VT, no diversification)
  - 50/50 SPY/GLD + 12/VIX (current recommendation)
  - 80/20 SPY/GLD + 12/VIX (K646 optimized)
  - BH 60/40 SPY/GLD
  - BH 60/40 SPY/TLT (traditional)

Data: yfinance SPY, GLD, TLT, ^VIX, ^TNX daily (2006-01-01 to 2026-03-27)

Prior knowledge:
  - K646: Cross-OOS confirms 80/20 > 50/50 (4/5 periods, p=0.031) but minimax favors 50/50
  - N116: 12/VIX+SHY works in ALL rate environments
  - K270: Rate hike detector showed GLD hedge fails when corr=0.44 in 2022
  - Knowledge: TLT is a liability in rising rate environments (2022 stock-bond co-movement)

References:
  - Baur & Lucey (2010), "Is Gold a Hedge or a Safe Haven?", JBF
  - Baur & McDermott (2010), "Is gold a safe haven? International evidence", JBF
  - Erb & Harvey (2013), "The Golden Dilemma", FAJ
  - Campbell et al. (2017), "Inflation bets or deflation hedges?", JF
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from scipy import stats
import json

# ==================================================================
# CONFIG
# ==================================================================
DATA_START = "2006-01-01"
DATA_END = "2026-03-27"
RF_ANNUAL = 0.02
RF_DAILY = RF_ANNUAL / 252

VIX_TARGET = 12.0
TX_COST_BPS = 2  # 2bp per trade (one-way)

REGIME_THRESHOLD_BP = 50  # +/-50bp for 6-month yield change
YIELD_LOOKBACK = 126      # ~6 months trading days

print("=" * 70)
print("K663: Interest Rate Environment Impact on VT Strategy Performance")
print("=" * 70)

# ==================================================================
# 1. Download Data
# ==================================================================
print("\n[1/6] Downloading data from yfinance...")

tickers = {
    "SPY": "SPY",
    "GLD": "GLD",
    "TLT": "TLT",
    "VIX": "^VIX",
    "TNX": "^TNX",  # 10-Year Treasury yield
}

prices = {}
for name, ticker in tickers.items():
    raw = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    col = "Adj Close" if "Adj Close" in raw.columns else "Close"
    prices[name] = raw[col].copy()
    prices[name].name = name
    print(f"  {name}: {len(raw)} rows, {raw.index[0].strftime('%Y-%m-%d')} to {raw.index[-1].strftime('%Y-%m-%d')}")

df = pd.DataFrame(prices)
df = df.ffill().dropna()
print(f"\n  Combined: {len(df)} rows, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# Returns
rets = pd.DataFrame()
for asset in ["SPY", "GLD", "TLT"]:
    rets[asset] = df[asset].pct_change()
rets = rets.dropna()

# Align VIX and TNX with returns
vix = df["VIX"].reindex(rets.index).ffill()
tnx = df["TNX"].reindex(rets.index).ffill()

print(f"  Returns: {len(rets)} rows")
print(f"  TNX range: {tnx.min():.2f}% to {tnx.max():.2f}%")

# ==================================================================
# 2. Define Rate Regimes
# ==================================================================
print("\n[2/6] Defining rate regimes...")

# 6-month change in 10Y yield (in percentage points, TNX is already in %)
yield_change_6m = tnx - tnx.shift(YIELD_LOOKBACK)
yield_change_6m = yield_change_6m.dropna()

# Classify regimes
threshold = REGIME_THRESHOLD_BP / 100  # convert bp to percentage points
regime = pd.Series(index=yield_change_6m.index, dtype=str)
regime[yield_change_6m > threshold] = "rising"
regime[yield_change_6m < -threshold] = "falling"
regime[(yield_change_6m >= -threshold) & (yield_change_6m <= threshold)] = "stable"

# Count days in each regime
regime_counts = regime.value_counts()
total_days = len(regime)
print(f"\n  Regime classification (6mo yield change, threshold = +/-{REGIME_THRESHOLD_BP}bp):")
for r in ["rising", "stable", "falling"]:
    n = regime_counts.get(r, 0)
    pct = n / total_days * 100
    mask = regime == r
    avg_change = yield_change_6m[mask].mean() * 100  # in bp
    print(f"    {r:8s}: {n:5d} days ({pct:5.1f}%), avg 6m yield change = {avg_change:+.0f}bp")

# ==================================================================
# 3. Define and Compute Strategy Returns
# ==================================================================
print("\n[3/6] Computing strategy returns...")

# Align data — only use dates where we have regime classification
common_idx = rets.index.intersection(regime.index)
rets_aligned = rets.loc[common_idx]
vix_aligned = vix.reindex(common_idx).ffill()
regime_aligned = regime.reindex(common_idx)

print(f"  Analysis period: {common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')}")
print(f"  Analysis days: {len(common_idx)}")


def compute_12vix_weight(vix_series):
    """12/VIX equity allocation, capped at [0, 1]."""
    w = VIX_TARGET / vix_series
    return w.clip(0.0, 1.0)


def compute_strategy_returns(spy_ret, gld_ret, tlt_ret, vix_series,
                             spy_w, hedge_w, hedge_asset="GLD",
                             use_vt=True, name=""):
    """
    Compute daily strategy returns.
    spy_w + hedge_w = 1.0 for the risky portfolio.
    If use_vt: apply 12/VIX scaling to the risky portfolio.
    TX cost applied when VT weight changes.
    """
    hedge_ret = gld_ret if hedge_asset == "GLD" else tlt_ret

    # Risky portfolio return
    risky_ret = spy_w * spy_ret + hedge_w * hedge_ret

    if use_vt:
        vt_weight = compute_12vix_weight(vix_series)
        # Shift weight by 1 day (use yesterday's VIX for today's allocation)
        vt_weight_shifted = vt_weight.shift(1).fillna(vt_weight.iloc[0])

        # TX cost: proportional to weight change
        weight_change = vt_weight_shifted.diff().abs().fillna(0)
        tx_cost = weight_change * (TX_COST_BPS / 10000)

        # Strategy return = vt_weight * risky + (1 - vt_weight) * rf - tx_cost
        strat_ret = vt_weight_shifted * risky_ret + (1 - vt_weight_shifted) * RF_DAILY - tx_cost
    else:
        strat_ret = risky_ret

    return strat_ret


# Define strategies
strategies = {}

# 1. 12/VIX on SPY (pure VT, no hedge)
strategies["12/VIX SPY"] = compute_strategy_returns(
    rets_aligned["SPY"], rets_aligned["GLD"], rets_aligned["TLT"],
    vix_aligned, spy_w=1.0, hedge_w=0.0, use_vt=True, name="12/VIX SPY"
)

# 2. 50/50 SPY/GLD + 12/VIX
strategies["50/50 SPY/GLD + VT"] = compute_strategy_returns(
    rets_aligned["SPY"], rets_aligned["GLD"], rets_aligned["TLT"],
    vix_aligned, spy_w=0.5, hedge_w=0.5, hedge_asset="GLD", use_vt=True
)

# 3. 80/20 SPY/GLD + 12/VIX (K646 optimized)
strategies["80/20 SPY/GLD + VT"] = compute_strategy_returns(
    rets_aligned["SPY"], rets_aligned["GLD"], rets_aligned["TLT"],
    vix_aligned, spy_w=0.8, hedge_w=0.2, hedge_asset="GLD", use_vt=True
)

# 4. BH 60/40 SPY/GLD (no VT)
strategies["BH 60/40 SPY/GLD"] = compute_strategy_returns(
    rets_aligned["SPY"], rets_aligned["GLD"], rets_aligned["TLT"],
    vix_aligned, spy_w=0.6, hedge_w=0.4, hedge_asset="GLD", use_vt=False
)

# 5. BH 60/40 SPY/TLT (traditional)
strategies["BH 60/40 SPY/TLT"] = compute_strategy_returns(
    rets_aligned["SPY"], rets_aligned["GLD"], rets_aligned["TLT"],
    vix_aligned, spy_w=0.6, hedge_w=0.4, hedge_asset="TLT", use_vt=False
)


# ==================================================================
# 4. Performance by Regime
# ==================================================================
print("\n[4/6] Computing performance metrics by rate regime...\n")


def calc_metrics(daily_returns, label=""):
    """Calculate annualized Sharpe, CAGR, MDD, Sortino, Calmar."""
    r = daily_returns.dropna()
    if len(r) < 20:
        return {"sharpe": np.nan, "cagr": np.nan, "mdd": np.nan,
                "sortino": np.nan, "calmar": np.nan, "vol": np.nan,
                "n_days": len(r)}

    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else np.nan

    # CAGR
    cum = (1 + r).cumprod()
    years = len(r) / 252
    cagr = (cum.iloc[-1] ** (1 / years) - 1) if years > 0 else np.nan

    # MDD
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Sortino
    downside = r[r < 0].std() * np.sqrt(252)
    sortino = (ann_ret - RF_ANNUAL) / downside if downside > 0 else np.nan

    # Calmar
    calmar = cagr / abs(mdd) if mdd != 0 else np.nan

    return {
        "sharpe": round(float(sharpe), 3),
        "cagr": round(float(cagr) * 100, 2),   # in %
        "mdd": round(float(mdd) * 100, 2),      # in %
        "vol": round(float(ann_vol) * 100, 2),   # in %
        "sortino": round(float(sortino), 3),
        "calmar": round(float(calmar), 3),
        "n_days": int(len(r)),
    }


results_by_regime = {}

for regime_name in ["rising", "stable", "falling", "all"]:
    if regime_name == "all":
        mask = pd.Series(True, index=regime_aligned.index)
    else:
        mask = regime_aligned == regime_name

    regime_results = {}
    for strat_name, strat_rets in strategies.items():
        r = strat_rets[mask]
        metrics = calc_metrics(r, label=f"{strat_name} [{regime_name}]")
        regime_results[strat_name] = metrics

    results_by_regime[regime_name] = regime_results

# Print results table
for regime_name in ["rising", "stable", "falling", "all"]:
    n_days = list(results_by_regime[regime_name].values())[0]["n_days"]
    print(f"\n  === {regime_name.upper()} RATE REGIME ({n_days} days) ===")
    print(f"  {'Strategy':<27s} {'Sharpe':>7s} {'CAGR%':>7s} {'MDD%':>7s} {'Vol%':>7s} {'Sortino':>8s} {'Calmar':>7s}")
    print(f"  {'-'*27} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*8} {'-'*7}")
    for strat_name in strategies.keys():
        m = results_by_regime[regime_name][strat_name]
        print(f"  {strat_name:<27s} {m['sharpe']:7.3f} {m['cagr']:7.2f} {m['mdd']:7.2f} {m['vol']:7.2f} {m['sortino']:8.3f} {m['calmar']:7.3f}")

# ==================================================================
# 5. Correlation Dynamics by Regime
# ==================================================================
print("\n\n[5/6] Correlation dynamics by rate regime...\n")

corr_results = {}
for regime_name in ["rising", "stable", "falling", "all"]:
    if regime_name == "all":
        mask = pd.Series(True, index=regime_aligned.index)
    else:
        mask = regime_aligned == regime_name

    spy_r = rets_aligned["SPY"][mask]
    gld_r = rets_aligned["GLD"][mask]
    tlt_r = rets_aligned["TLT"][mask]

    spy_gld_corr = spy_r.corr(gld_r)
    spy_tlt_corr = spy_r.corr(tlt_r)
    gld_tlt_corr = gld_r.corr(tlt_r)

    corr_results[regime_name] = {
        "SPY-GLD": round(float(spy_gld_corr), 4),
        "SPY-TLT": round(float(spy_tlt_corr), 4),
        "GLD-TLT": round(float(gld_tlt_corr), 4),
    }
    print(f"  {regime_name:8s}: SPY-GLD = {spy_gld_corr:+.4f}, SPY-TLT = {spy_tlt_corr:+.4f}, GLD-TLT = {gld_tlt_corr:+.4f}")

# ==================================================================
# 5b. Detailed sub-period analysis (notable rate episodes)
# ==================================================================
print("\n\n  --- Notable Rate Episodes ---")

episodes = [
    ("2008-09 to 2009-03 (GFC, rates falling fast)", "2008-09-01", "2009-03-31"),
    ("2013-05 to 2013-09 (Taper Tantrum)", "2013-05-01", "2013-09-30"),
    ("2016-07 to 2018-10 (Hiking cycle)", "2016-07-01", "2018-10-31"),
    ("2020-01 to 2020-06 (COVID, rates collapse)", "2020-01-01", "2020-06-30"),
    ("2022-01 to 2022-12 (Aggressive tightening)", "2022-01-01", "2022-12-31"),
    ("2024-01 to 2024-12 (Higher for longer)", "2024-01-01", "2024-12-31"),
]

episode_results = {}
for ep_name, start, end in episodes:
    mask = (rets_aligned.index >= start) & (rets_aligned.index <= end)
    ep_rets = {}
    for strat_name, strat_r in strategies.items():
        r = strat_r[mask]
        ep_rets[strat_name] = calc_metrics(r)

    # Correlations in this episode
    spy_r = rets_aligned["SPY"][mask]
    gld_r = rets_aligned["GLD"][mask]
    tlt_r = rets_aligned["TLT"][mask]

    ep_corr = {
        "SPY-GLD": round(float(spy_r.corr(gld_r)), 4),
        "SPY-TLT": round(float(spy_r.corr(tlt_r)), 4),
    }

    episode_results[ep_name] = {"performance": ep_rets, "correlations": ep_corr}

    # Yield change in episode (use date-based slicing for tnx)
    tnx_ep = tnx.loc[(tnx.index >= start) & (tnx.index <= end)]
    if len(tnx_ep) > 1:
        yield_chg = tnx_ep.iloc[-1] - tnx_ep.iloc[0]
    else:
        yield_chg = np.nan

    print(f"\n  {ep_name}")
    print(f"    10Y yield change: {yield_chg:+.2f}%  |  SPY-GLD corr: {ep_corr['SPY-GLD']:+.4f}  |  SPY-TLT corr: {ep_corr['SPY-TLT']:+.4f}")
    print(f"    {'Strategy':<27s} {'Sharpe':>7s} {'Return%':>8s} {'MDD%':>7s}")
    print(f"    {'-'*27} {'-'*7} {'-'*8} {'-'*7}")
    for strat_name in strategies.keys():
        m = ep_rets[strat_name]
        print(f"    {strat_name:<27s} {m['sharpe']:7.3f} {m['cagr']:8.2f} {m['mdd']:7.2f}")

# ==================================================================
# 6. Key Findings & Summary
# ==================================================================
print("\n\n[6/6] Key findings...\n")

# Question 1: Does GLD protect during rising rates?
rising = results_by_regime["rising"]
falling = results_by_regime["falling"]

gld_rising_sharpe = rising["50/50 SPY/GLD + VT"]["sharpe"]
gld_falling_sharpe = falling["50/50 SPY/GLD + VT"]["sharpe"]
spy_rising_sharpe = rising["12/VIX SPY"]["sharpe"]
spy_falling_sharpe = falling["12/VIX SPY"]["sharpe"]

print(f"  Q1: Does GLD protect during rising rates?")
print(f"    50/50+VT Sharpe: rising={gld_rising_sharpe:.3f}, falling={gld_falling_sharpe:.3f}")
print(f"    12/VIX SPY Sharpe: rising={spy_rising_sharpe:.3f}, falling={spy_falling_sharpe:.3f}")
gld_advantage_rising = gld_rising_sharpe - spy_rising_sharpe
gld_advantage_falling = gld_falling_sharpe - spy_falling_sharpe
print(f"    GLD advantage (50/50 vs pure SPY): rising={gld_advantage_rising:+.3f}, falling={gld_advantage_falling:+.3f}")

# Question 2: Is 50/50 robust across regimes?
print(f"\n  Q2: 50/50 robustness across rate regimes:")
for reg in ["rising", "stable", "falling"]:
    s = results_by_regime[reg]["50/50 SPY/GLD + VT"]["sharpe"]
    m = results_by_regime[reg]["50/50 SPY/GLD + VT"]["mdd"]
    print(f"    {reg:8s}: Sharpe={s:.3f}, MDD={m:.2f}%")

sharpe_range = max(
    results_by_regime[r]["50/50 SPY/GLD + VT"]["sharpe"] for r in ["rising", "stable", "falling"]
) - min(
    results_by_regime[r]["50/50 SPY/GLD + VT"]["sharpe"] for r in ["rising", "stable", "falling"]
)
print(f"    Sharpe range across regimes: {sharpe_range:.3f}")

# Question 3: How badly does TLT fail during rising rates?
print(f"\n  Q3: TLT-based allocation in rising rates:")
tlt_rising = rising["BH 60/40 SPY/TLT"]
gld_bh_rising = rising["BH 60/40 SPY/GLD"]
print(f"    BH 60/40 SPY/TLT: Sharpe={tlt_rising['sharpe']:.3f}, MDD={tlt_rising['mdd']:.2f}%")
print(f"    BH 60/40 SPY/GLD: Sharpe={gld_bh_rising['sharpe']:.3f}, MDD={gld_bh_rising['mdd']:.2f}%")
tlt_vs_gld_rising = tlt_rising['sharpe'] - gld_bh_rising['sharpe']
print(f"    TLT disadvantage vs GLD in rising rates: {tlt_vs_gld_rising:+.3f} Sharpe")

# Question 4: Should VT adjust for rates?
print(f"\n  Q4: VT benefit across rate regimes:")
for reg in ["rising", "stable", "falling"]:
    vt_sharpe = results_by_regime[reg]["50/50 SPY/GLD + VT"]["sharpe"]
    bh_sharpe = results_by_regime[reg]["BH 60/40 SPY/GLD"]["sharpe"]
    benefit = vt_sharpe - bh_sharpe
    print(f"    {reg:8s}: VT benefit = {benefit:+.3f} Sharpe (VT={vt_sharpe:.3f} vs BH={bh_sharpe:.3f})")

# Question 5: 80/20 vs 50/50 by regime
print(f"\n  Q5: 80/20 vs 50/50 by regime:")
for reg in ["rising", "stable", "falling"]:
    s80 = results_by_regime[reg]["80/20 SPY/GLD + VT"]["sharpe"]
    s50 = results_by_regime[reg]["50/50 SPY/GLD + VT"]["sharpe"]
    diff = s80 - s50
    print(f"    {reg:8s}: 80/20={s80:.3f} vs 50/50={s50:.3f}, diff={diff:+.3f}")

# ==================================================================
# Prepare results JSON
# ==================================================================
print("\n\nSaving results...")

results = {
    "experiment_id": "K663",
    "title": "Interest Rate Environment Impact on VT Strategy Performance",
    "proposer": "Claude",
    "executor": "Claude",
    "timestamp": datetime.now().isoformat(),
    "data_source": "yfinance (SPY, GLD, TLT, ^VIX, ^TNX)",
    "data_period": f"{DATA_START} to {DATA_END}",
    "sample_days": int(len(common_idx)),
    "methodology": {
        "regime_definition": f"6-month change in 10Y yield, threshold = +/-{REGIME_THRESHOLD_BP}bp",
        "vt_rule": "12/VIX equity allocation",
        "tx_cost": f"{TX_COST_BPS}bp per trade",
        "risk_free_rate": f"{RF_ANNUAL*100:.1f}% annual",
    },
    "regime_distribution": {
        r: {
            "n_days": int(regime_counts.get(r, 0)),
            "pct": round(float(regime_counts.get(r, 0) / total_days * 100), 1),
            "avg_6m_yield_change_bp": round(float(yield_change_6m[regime == r].mean() * 100), 1)
        }
        for r in ["rising", "stable", "falling"]
    },
    "performance_by_regime": results_by_regime,
    "correlations_by_regime": corr_results,
    "notable_episodes": {
        ep_name: {
            "performance": {
                sn: episode_results[ep_name]["performance"][sn]
                for sn in strategies.keys()
            },
            "correlations": episode_results[ep_name]["correlations"]
        }
        for ep_name, _, _ in episodes
    },
    "key_findings": {
        "Q1_GLD_rising_rates": {
            "question": "Does GLD protect during rising rates?",
            "gld_advantage_rising": round(float(gld_advantage_rising), 3),
            "gld_advantage_falling": round(float(gld_advantage_falling), 3),
            "conclusion": "",  # filled below
        },
        "Q2_5050_robustness": {
            "question": "Is 50/50 SPY/GLD robust across rate environments?",
            "sharpe_range_across_regimes": round(float(sharpe_range), 3),
            "sharpe_by_regime": {
                r: results_by_regime[r]["50/50 SPY/GLD + VT"]["sharpe"]
                for r in ["rising", "stable", "falling"]
            },
            "conclusion": "",
        },
        "Q3_TLT_failure": {
            "question": "How badly does TLT-based allocation fail during rising rates?",
            "tlt_sharpe_rising": tlt_rising["sharpe"],
            "gld_sharpe_rising": gld_bh_rising["sharpe"],
            "tlt_disadvantage": round(float(tlt_vs_gld_rising), 3),
            "conclusion": "",
        },
        "Q4_VT_rate_adjustment": {
            "question": "Should VT strategy adjust for rate environment?",
            "vt_benefit_by_regime": {
                r: round(
                    float(results_by_regime[r]["50/50 SPY/GLD + VT"]["sharpe"]
                          - results_by_regime[r]["BH 60/40 SPY/GLD"]["sharpe"]),
                    3
                )
                for r in ["rising", "stable", "falling"]
            },
            "conclusion": "",
        },
        "Q5_8020_vs_5050_by_regime": {
            "question": "Does 80/20 vs 50/50 depend on rate regime?",
            "diff_by_regime": {
                r: round(
                    float(results_by_regime[r]["80/20 SPY/GLD + VT"]["sharpe"]
                          - results_by_regime[r]["50/50 SPY/GLD + VT"]["sharpe"]),
                    3
                )
                for r in ["rising", "stable", "falling"]
            },
            "conclusion": "",
        },
    },
    "references": [
        "Baur & Lucey (2010), Is Gold a Hedge or a Safe Haven?, JBF",
        "Baur & McDermott (2010), Is gold a safe haven? International evidence, JBF",
        "Erb & Harvey (2013), The Golden Dilemma, FAJ",
        "Campbell et al. (2017), Inflation bets or deflation hedges?, JF",
        "K646: Cross-OOS 80/20 vs 50/50",
        "K270: Rate Hike Regime Detection",
        "N116: 12/VIX in different rate environments",
    ],
}

# Fill in conclusions based on results
q1 = results["key_findings"]["Q1_GLD_rising_rates"]
if q1["gld_advantage_rising"] > 0:
    q1["conclusion"] = f"GLD still adds value during rising rates (+{q1['gld_advantage_rising']:.3f} Sharpe vs pure SPY VT). Gold hedge is rate-regime robust."
elif q1["gld_advantage_rising"] > -0.1:
    q1["conclusion"] = f"GLD marginally underperforms during rising rates ({q1['gld_advantage_rising']:+.3f} Sharpe) but not catastrophically. Mixed evidence."
else:
    q1["conclusion"] = f"GLD significantly underperforms during rising rates ({q1['gld_advantage_rising']:+.3f} Sharpe). Gold hedge fails in rising rate environments."

q2 = results["key_findings"]["Q2_5050_robustness"]
if q2["sharpe_range_across_regimes"] < 0.3:
    q2["conclusion"] = f"50/50 SPY/GLD is highly robust across rate regimes (Sharpe range = {q2['sharpe_range_across_regimes']:.3f}). Rate environment is NOT a critical factor."
elif q2["sharpe_range_across_regimes"] < 0.6:
    q2["conclusion"] = f"50/50 SPY/GLD shows moderate sensitivity to rate regime (Sharpe range = {q2['sharpe_range_across_regimes']:.3f}). Some adaptation may help."
else:
    q2["conclusion"] = f"50/50 SPY/GLD is NOT robust across rate regimes (Sharpe range = {q2['sharpe_range_across_regimes']:.3f}). Rate-conditional strategy recommended."

q3 = results["key_findings"]["Q3_TLT_failure"]
if q3["tlt_disadvantage"] < -0.3:
    q3["conclusion"] = f"TLT-based allocation severely underperforms GLD in rising rates ({q3['tlt_disadvantage']:+.3f} Sharpe). Traditional 60/40 is rate-regime fragile."
elif q3["tlt_disadvantage"] < -0.1:
    q3["conclusion"] = f"TLT-based allocation moderately underperforms GLD in rising rates ({q3['tlt_disadvantage']:+.3f} Sharpe). GLD is more rate-robust hedge."
else:
    q3["conclusion"] = f"TLT vs GLD difference is small in rising rates ({q3['tlt_disadvantage']:+.3f} Sharpe). Both hedges are similarly affected."

q4 = results["key_findings"]["Q4_VT_rate_adjustment"]
vt_benefits = list(q4["vt_benefit_by_regime"].values())
min_benefit = min(vt_benefits)
max_benefit = max(vt_benefits)
if min_benefit > 0:
    q4["conclusion"] = f"VT adds value in ALL rate regimes (benefit range: {min_benefit:+.3f} to {max_benefit:+.3f}). No rate-conditional adjustment needed."
else:
    q4["conclusion"] = f"VT benefit varies by regime ({min_benefit:+.3f} to {max_benefit:+.3f}). Rate-conditional VT scaling may improve results."

q5 = results["key_findings"]["Q5_8020_vs_5050_by_regime"]
diffs = list(q5["diff_by_regime"].values())
if all(d > 0 for d in diffs):
    q5["conclusion"] = "80/20 beats 50/50 in ALL rate regimes. K646 finding is rate-robust."
elif all(d < 0 for d in diffs):
    q5["conclusion"] = "50/50 beats 80/20 in ALL rate regimes. K646 finding may be period-specific."
else:
    pos = sum(1 for d in diffs if d > 0)
    q5["conclusion"] = f"Mixed: 80/20 wins in {pos}/3 regimes. Optimal GLD weight depends on rate environment."

# Save
output_path = "experiments/k663_results.json"
with open(output_path, "w") as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n  Results saved to {output_path}")
print(f"\n{'='*70}")
print("K663 COMPLETE")
print(f"{'='*70}")

# Print executive summary
print("\n  EXECUTIVE SUMMARY:")
for qkey, qval in results["key_findings"].items():
    print(f"\n  {qval['question']}")
    print(f"    -> {qval['conclusion']}")
