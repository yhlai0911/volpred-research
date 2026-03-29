"""
K678: Strategy Correlation Matrix & Diversification Map
========================================================
Motivation: K643 found avg strategy correlation = 0.72 (too high).
This experiment identifies:
  1. Full pairwise correlation matrix across all strategies
  2. Most/least correlated pairs
  3. Most "independent" strategy
  4. Best 2-strategy combo (max combined Sharpe)
  5. Correlation by VIX regime (VIX > 25 vs <= 25)

Data source: paper_trading.json (daily portfolio_return, 2023-01 to 2026-03)
VIX source: yfinance (^VIX) + local CSV fallback
References: K643 (strategy correlation avg 0.72)
"""

import json
import sys
import warnings
from datetime import datetime
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── Paths ──
BASE = Path(__file__).resolve().parent.parent
PT_PATH = BASE / "storage" / "paper_trading.json"
VIX_CSV = BASE / "storage" / "sentiment" / "vix_historical.csv"
OUT_PATH = BASE / "experiments" / "k678_results.json"

# ── Strategy display names ──
DISPLAY = {
    "slow_vt": "GARCH VT (SPY)",
    "risk_parity": "Risk Parity (SPY+GLD)",
    "simple_12vix": "12/VIX (SPY)",
    "recommended_5050": "50/50 SPY/GLD",
    "taiwan_8.63vix": "台灣 VT (0050)",
    "taiwan_spy_momentum": "台股動量 (0050)",
    "tz_tw_jp_5050": "TW+JP 50/50 TZ",
    "global_vt_tz": "Global VT+TZ",
    "vix_leading_guard": "VIX+領先 (0050)",
    "vix_cond_leverage": "VIX 條件槓桿",
    "taiwan_hybrid_leverage": "台股混合槓桿",
    "piecewise_conservative": "保守型 VT",
    "fear_dca": "恐慌加碼 DCA",
    "adaptive_tier": "Adaptive Tier",
}

SKIP = {"_market_daily"}

# ── 1. Load paper trading returns ──
print("=" * 60)
print("K678: Strategy Correlation Matrix & Diversification Map")
print("=" * 60)

with open(PT_PATH) as f:
    pt_data = json.load(f)

# Build a DataFrame: rows = dates, columns = strategies
series_dict = {}
for key, val in pt_data.items():
    if key in SKIP:
        continue
    entries = val.get("entries", [])
    if not entries:
        continue
    dates, rets = [], []
    for e in entries:
        r = e.get("portfolio_return")
        if r is not None:
            dates.append(e["data_date"])
            rets.append(float(r))
    if len(dates) > 100:  # minimum threshold
        s = pd.Series(rets, index=pd.to_datetime(dates), name=key)
        series_dict[key] = s

# Align to common date range (intersection)
df_all = pd.DataFrame(series_dict)
df_all.sort_index(inplace=True)

# For pair-wise analysis, use all available data between each pair
# For the matrix, use common dates among all
print(f"\nStrategies loaded: {len(df_all.columns)}")
print(f"Date range: {df_all.index.min().date()} to {df_all.index.max().date()}")
print(f"Total rows (union): {len(df_all)}")

# ── 2. Load VIX data ──
print("\n--- Loading VIX data ---")
vix_df = None
try:
    import yfinance as yf
    vix_raw = yf.download("^VIX", start="2022-01-01", end="2026-12-31", progress=False)
    if len(vix_raw) > 100:
        if isinstance(vix_raw.columns, pd.MultiIndex):
            vix_df = vix_raw["Close"]["^VIX"].rename("VIX")
        else:
            vix_df = vix_raw["Close"].rename("VIX")
        print(f"  yfinance VIX: {len(vix_df)} rows, {vix_df.index.min().date()} to {vix_df.index.max().date()}")
except Exception as e:
    print(f"  yfinance failed: {e}")

if vix_df is None or len(vix_df) < 100:
    # Fallback to CSV
    csv_df = pd.read_csv(VIX_CSV, skiprows=2, parse_dates=["Date"], index_col="Date")
    vix_df = csv_df.iloc[:, 0].rename("VIX")
    print(f"  CSV fallback VIX: {len(vix_df)} rows")

# ── 3. Full Correlation Matrix ──
print("\n" + "=" * 60)
print("SECTION 1: FULL CORRELATION MATRIX")
print("=" * 60)

# Use pairwise complete observations for max data utilization
corr_matrix = df_all.corr(method="pearson", min_periods=100)
print(f"\nCorrelation matrix shape: {corr_matrix.shape}")

# Print matrix with display names
strat_keys = list(corr_matrix.columns)
n = len(strat_keys)

# Short labels for printing
SHORT = {k: v[:18] for k, v in DISPLAY.items()}
for k in strat_keys:
    if k not in SHORT:
        SHORT[k] = k[:18]

print("\nPairwise correlations (all pairs):")
print("-" * 50)

# ── 4. Extract all pairs ──
pairs = []
for i, j in combinations(range(n), 2):
    k1, k2 = strat_keys[i], strat_keys[j]
    r = corr_matrix.loc[k1, k2]
    if not np.isnan(r):
        # Count common observations
        common = df_all[[k1, k2]].dropna().shape[0]
        pairs.append({
            "strat1": k1,
            "strat2": k2,
            "name1": DISPLAY.get(k1, k1),
            "name2": DISPLAY.get(k2, k2),
            "correlation": round(float(r), 4),
            "common_obs": int(common),
        })

pairs.sort(key=lambda x: x["correlation"], reverse=True)

print(f"\nTotal pairs: {len(pairs)}")
print(f"Average correlation: {np.mean([p['correlation'] for p in pairs]):.4f}")
print(f"Median correlation: {np.median([p['correlation'] for p in pairs]):.4f}")
print(f"Std of correlations: {np.std([p['correlation'] for p in pairs]):.4f}")

avg_corr = float(np.mean([p["correlation"] for p in pairs]))
med_corr = float(np.median([p["correlation"] for p in pairs]))

# Most correlated
print("\n--- TOP 5 MOST CORRELATED PAIRS ---")
for p in pairs[:5]:
    print(f"  r={p['correlation']:+.4f}  {p['name1']} x {p['name2']}  (n={p['common_obs']})")

# Least correlated
print("\n--- TOP 5 LEAST CORRELATED PAIRS (best diversification) ---")
for p in pairs[-5:]:
    print(f"  r={p['correlation']:+.4f}  {p['name1']} x {p['name2']}  (n={p['common_obs']})")

# ── 5. Most "independent" strategy ──
print("\n" + "=" * 60)
print("SECTION 2: STRATEGY INDEPENDENCE RANKING")
print("=" * 60)

avg_corr_per_strat = {}
for k in strat_keys:
    others = [corr_matrix.loc[k, k2] for k2 in strat_keys if k2 != k and not np.isnan(corr_matrix.loc[k, k2])]
    if others:
        avg_corr_per_strat[k] = float(np.mean(others))

independence_ranking = sorted(avg_corr_per_strat.items(), key=lambda x: x[1])
print("\nAverage correlation with all other strategies (lower = more independent):")
for rank, (k, avg_r) in enumerate(independence_ranking, 1):
    print(f"  {rank}. {DISPLAY.get(k, k):30s}  avg_r = {avg_r:.4f}")

most_independent = independence_ranking[0]
print(f"\n>>> Most independent: {DISPLAY.get(most_independent[0], most_independent[0])} (avg_r = {most_independent[1]:.4f})")

# ── 6. Best 2-strategy combo (max combined Sharpe) ──
print("\n" + "=" * 60)
print("SECTION 3: BEST 2-STRATEGY COMBO (Equal-Weight Sharpe)")
print("=" * 60)

combo_results = []
for i, j in combinations(range(n), 2):
    k1, k2 = strat_keys[i], strat_keys[j]
    common = df_all[[k1, k2]].dropna()
    if len(common) < 200:
        continue

    # Equal-weight combined return
    combined = (common[k1] + common[k2]) / 2.0

    # Annualized Sharpe (252 trading days)
    mu = combined.mean() * 252
    sigma = combined.std() * np.sqrt(252)
    sharpe = mu / sigma if sigma > 0 else 0.0

    # Individual Sharpes for comparison
    mu1 = common[k1].mean() * 252
    sig1 = common[k1].std() * np.sqrt(252)
    sh1 = mu1 / sig1 if sig1 > 0 else 0.0

    mu2 = common[k2].mean() * 252
    sig2 = common[k2].std() * np.sqrt(252)
    sh2 = mu2 / sig2 if sig2 > 0 else 0.0

    r = corr_matrix.loc[k1, k2]

    combo_results.append({
        "strat1": k1,
        "strat2": k2,
        "name1": DISPLAY.get(k1, k1),
        "name2": DISPLAY.get(k2, k2),
        "combined_sharpe": round(float(sharpe), 4),
        "sharpe1": round(float(sh1), 4),
        "sharpe2": round(float(sh2), 4),
        "correlation": round(float(r), 4),
        "combined_ann_return": round(float(mu), 4),
        "combined_ann_vol": round(float(sigma), 4),
        "obs": int(len(common)),
    })

combo_results.sort(key=lambda x: x["combined_sharpe"], reverse=True)

print("\n--- TOP 10 BEST 2-STRATEGY COMBOS (by combined Sharpe) ---")
print(f"{'Rank':>4s}  {'Sharpe':>7s}  {'r':>7s}  {'AnnRet':>7s}  {'AnnVol':>7s}  {'Strategy Pair'}")
print("-" * 90)
for rank, c in enumerate(combo_results[:10], 1):
    print(f"  {rank:>2d}   {c['combined_sharpe']:>7.3f}  {c['correlation']:>7.3f}  "
          f"{c['combined_ann_return']:>7.3f}  {c['combined_ann_vol']:>7.3f}  "
          f"{c['name1'][:20]} + {c['name2'][:20]}")

# Check: is the best combo the least correlated pair?
best_combo = combo_results[0]
least_corr_pair = pairs[-1]
print(f"\n>>> Best combo: {best_combo['name1']} + {best_combo['name2']} (Sharpe={best_combo['combined_sharpe']:.3f}, r={best_combo['correlation']:.3f})")
print(f">>> Least corr: {least_corr_pair['name1']} + {least_corr_pair['name2']} (r={least_corr_pair['correlation']:.3f})")
is_same = (set([best_combo['strat1'], best_combo['strat2']]) ==
           set([least_corr_pair['strat1'], least_corr_pair['strat2']]))
print(f">>> Are they the same? {'YES' if is_same else 'NO — low correlation alone does not maximize Sharpe'}")

# ── 7. Correlation by VIX Regime ──
print("\n" + "=" * 60)
print("SECTION 4: CORRELATION BY VIX REGIME")
print("=" * 60)

# Merge VIX with strategy returns
df_with_vix = df_all.copy()
df_with_vix["VIX"] = vix_df.reindex(df_with_vix.index)
df_with_vix.dropna(subset=["VIX"], inplace=True)

vix_threshold = 25.0
mask_high = df_with_vix["VIX"] > vix_threshold
mask_low = df_with_vix["VIX"] <= vix_threshold

df_high = df_with_vix.loc[mask_high, strat_keys]
df_low = df_with_vix.loc[mask_low, strat_keys]

print(f"\nVIX <= {vix_threshold}: {mask_low.sum()} days")
print(f"VIX >  {vix_threshold}: {mask_high.sum()} days")

corr_low = df_low.corr(method="pearson", min_periods=30)
corr_high = df_high.corr(method="pearson", min_periods=30)

# Extract pair-wise correlations for both regimes
regime_pairs = []
for i, j in combinations(range(n), 2):
    k1, k2 = strat_keys[i], strat_keys[j]
    r_low = corr_low.loc[k1, k2] if not np.isnan(corr_low.loc[k1, k2]) else None
    r_high = corr_high.loc[k1, k2] if not np.isnan(corr_high.loc[k1, k2]) else None
    if r_low is not None and r_high is not None:
        regime_pairs.append({
            "strat1": k1,
            "strat2": k2,
            "name1": DISPLAY.get(k1, k1),
            "name2": DISPLAY.get(k2, k2),
            "r_calm": round(float(r_low), 4),
            "r_stress": round(float(r_high), 4),
            "delta_r": round(float(r_high - r_low), 4),
        })

avg_r_calm = np.mean([p["r_calm"] for p in regime_pairs])
avg_r_stress = np.mean([p["r_stress"] for p in regime_pairs])
avg_delta = np.mean([p["delta_r"] for p in regime_pairs])

print(f"\nAvg correlation VIX <= {vix_threshold}: {avg_r_calm:.4f}")
print(f"Avg correlation VIX >  {vix_threshold}: {avg_r_stress:.4f}")
print(f"Avg change (stress - calm):            {avg_delta:+.4f}")

if avg_delta > 0.05:
    regime_conclusion = f"Correlations INCREASE by {avg_delta:.3f} during stress — diversification weakens when most needed"
elif avg_delta < -0.05:
    regime_conclusion = f"Correlations DECREASE by {abs(avg_delta):.3f} during stress — strategies diversify better in crisis"
else:
    regime_conclusion = f"Correlation change is small ({avg_delta:+.3f}) — regime has limited impact on diversification"

print(f"\n>>> {regime_conclusion}")

# Pairs with BIGGEST correlation increase in stress
regime_pairs.sort(key=lambda x: x["delta_r"], reverse=True)
print("\n--- TOP 5 PAIRS: Biggest correlation INCREASE during stress ---")
for p in regime_pairs[:5]:
    print(f"  delta_r={p['delta_r']:+.4f}  (calm={p['r_calm']:.3f} → stress={p['r_stress']:.3f})  {p['name1'][:20]} x {p['name2'][:20]}")

# Pairs with BIGGEST correlation decrease in stress (beneficial)
print("\n--- TOP 5 PAIRS: Biggest correlation DECREASE during stress (desirable) ---")
for p in regime_pairs[-5:]:
    print(f"  delta_r={p['delta_r']:+.4f}  (calm={p['r_calm']:.3f} → stress={p['r_stress']:.3f})  {p['name1'][:20]} x {p['name2'][:20]}")

# ── 8. Individual strategy stats ──
print("\n" + "=" * 60)
print("SECTION 5: INDIVIDUAL STRATEGY STATISTICS")
print("=" * 60)

strat_stats = []
for k in strat_keys:
    s = df_all[k].dropna()
    mu = s.mean() * 252
    sig = s.std() * np.sqrt(252)
    sh = mu / sig if sig > 0 else 0.0
    # Max drawdown
    cum = (1 + s).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    strat_stats.append({
        "key": k,
        "name": DISPLAY.get(k, k),
        "obs": int(len(s)),
        "ann_return": round(float(mu), 4),
        "ann_vol": round(float(sig), 4),
        "sharpe": round(float(sh), 4),
        "max_dd": round(float(mdd), 4),
        "avg_corr_with_others": round(avg_corr_per_strat.get(k, float("nan")), 4),
    })

strat_stats.sort(key=lambda x: x["sharpe"], reverse=True)
print(f"\n{'Rank':>4s}  {'Sharpe':>7s}  {'AnnRet':>7s}  {'AnnVol':>7s}  {'MDD':>7s}  {'AvgR':>7s}  {'Strategy'}")
print("-" * 80)
for rank, s in enumerate(strat_stats, 1):
    print(f"  {rank:>2d}   {s['sharpe']:>7.3f}  {s['ann_return']:>7.3f}  {s['ann_vol']:>7.3f}  "
          f"{s['max_dd']:>7.3f}  {s['avg_corr_with_others']:>7.3f}  {s['name']}")

# ── 9. Best 3-strategy combo (bonus) ──
print("\n" + "=" * 60)
print("SECTION 6: BEST 3-STRATEGY COMBO (Equal-Weight)")
print("=" * 60)

triple_results = []
for combo_keys in combinations(strat_keys, 3):
    common = df_all[list(combo_keys)].dropna()
    if len(common) < 200:
        continue
    combined = common.mean(axis=1)
    mu = combined.mean() * 252
    sigma = combined.std() * np.sqrt(252)
    sharpe = mu / sigma if sigma > 0 else 0.0

    # Average pairwise correlation
    avg_pair_r = np.mean([
        corr_matrix.loc[combo_keys[i], combo_keys[j]]
        for i, j in combinations(range(3), 2)
        if not np.isnan(corr_matrix.loc[combo_keys[i], combo_keys[j]])
    ])

    triple_results.append({
        "strategies": list(combo_keys),
        "names": [DISPLAY.get(k, k) for k in combo_keys],
        "combined_sharpe": round(float(sharpe), 4),
        "avg_pair_corr": round(float(avg_pair_r), 4),
        "combined_ann_return": round(float(mu), 4),
        "combined_ann_vol": round(float(sigma), 4),
        "obs": int(len(common)),
    })

triple_results.sort(key=lambda x: x["combined_sharpe"], reverse=True)

print("\n--- TOP 5 BEST 3-STRATEGY COMBOS ---")
for rank, t in enumerate(triple_results[:5], 1):
    names_str = " + ".join([n[:15] for n in t["names"]])
    print(f"  {rank}. Sharpe={t['combined_sharpe']:.3f}  avg_r={t['avg_pair_corr']:.3f}  "
          f"AnnRet={t['combined_ann_return']:.3f}  AnnVol={t['combined_ann_vol']:.3f}")
    print(f"     {names_str}  (n={t['obs']})")

# ── 10. Summary ──
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)

# Build full correlation matrix as dict for JSON
corr_dict = {}
for k1 in strat_keys:
    corr_dict[k1] = {}
    for k2 in strat_keys:
        v = corr_matrix.loc[k1, k2]
        corr_dict[k1][k2] = round(float(v), 4) if not np.isnan(v) else None

summary = {
    "total_strategies": len(strat_keys),
    "total_pairs": len(pairs),
    "avg_correlation": round(avg_corr, 4),
    "median_correlation": round(med_corr, 4),
    "most_correlated_pair": pairs[0],
    "least_correlated_pair": pairs[-1],
    "most_independent_strategy": {
        "key": most_independent[0],
        "name": DISPLAY.get(most_independent[0], most_independent[0]),
        "avg_corr_with_others": round(most_independent[1], 4),
    },
    "best_2_combo": combo_results[0],
    "best_2_combo_is_least_corr": is_same,
    "best_3_combo": triple_results[0] if triple_results else None,
    "regime_analysis": {
        "vix_threshold": vix_threshold,
        "n_calm_days": int(mask_low.sum()),
        "n_stress_days": int(mask_high.sum()),
        "avg_r_calm": round(float(avg_r_calm), 4),
        "avg_r_stress": round(float(avg_r_stress), 4),
        "avg_delta_r": round(float(avg_delta), 4),
        "conclusion": regime_conclusion,
        "top_increase_pair": regime_pairs[0] if regime_pairs else None,
        "top_decrease_pair": regime_pairs[-1] if regime_pairs else None,
    },
}

print(f"\n  Strategies analyzed: {summary['total_strategies']}")
print(f"  Total pairs: {summary['total_pairs']}")
print(f"  Average correlation: {summary['avg_correlation']:.4f}")
print(f"  Most correlated: {pairs[0]['name1']} x {pairs[0]['name2']} (r={pairs[0]['correlation']:.4f})")
print(f"  Least correlated: {pairs[-1]['name1']} x {pairs[-1]['name2']} (r={pairs[-1]['correlation']:.4f})")
print(f"  Most independent: {DISPLAY.get(most_independent[0], most_independent[0])} (avg_r={most_independent[1]:.4f})")
print(f"  Best 2-combo Sharpe: {best_combo['combined_sharpe']:.3f} ({best_combo['name1']} + {best_combo['name2']})")
if triple_results:
    print(f"  Best 3-combo Sharpe: {triple_results[0]['combined_sharpe']:.3f} ({' + '.join(triple_results[0]['names'][:3])})")
print(f"  Regime effect: avg_delta_r = {avg_delta:+.4f}")
print(f"  {regime_conclusion}")

# ── Save results ──
results = {
    "experiment_id": "K678",
    "title": "Strategy Correlation Matrix & Diversification Map",
    "timestamp": datetime.now().isoformat(),
    "data_source": "paper_trading.json (daily portfolio_return)",
    "vix_source": "yfinance ^VIX (fallback: storage/sentiment/vix_historical.csv)",
    "period": f"{df_all.index.min().date()} to {df_all.index.max().date()}",
    "references": ["K643 (strategy correlation avg 0.72)"],
    "summary": summary,
    "strategy_stats": strat_stats,
    "correlation_matrix": corr_dict,
    "all_pairs_sorted": pairs,
    "top10_2_combos": combo_results[:10],
    "top5_3_combos": triple_results[:5],
    "regime_pairs": regime_pairs[:10] + regime_pairs[-10:],
    "independence_ranking": [
        {"key": k, "name": DISPLAY.get(k, k), "avg_corr": round(v, 4)}
        for k, v in independence_ranking
    ],
}

with open(OUT_PATH, "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\n>>> Results saved to {OUT_PATH}")
print("K678 complete.")
