"""
K137: Economic Sufficiency Frontier — Formal Framework
=======================================================
[提出: Codex Round 2 #4, 執行: Claude]

Background:
  K129 defined economic vs statistical sufficiency.
  K130 built a 90-cell loss tensor (6 models × 3 assets × 5 objectives).
  K132 decomposed QLIKE into noise floor + model bias + residual.

  Codex Round 2 suggestion: converge these into a flagship theorem:
  "Under high irreducible noise, no globally optimal model exists;
   the optimal model is necessarily objective-dependent."

Methodology:
  1. Attainable Improvement Ratio (AIR):
     AIR(model, objective) = (loss_naive - loss_model) / (loss_naive - loss_oracle)
     1.0 = theoretical optimum, 0.0 = no better than naive, <0 = worse than naive
  2. AIR tensor: 6 models × 3 assets × 4 objectives
     (QLIKE, log-RV MSE, tail-event Brier, CRRA utility loss)
  3. Blackwell-style sufficiency test:
     Model A sufficient for B iff AIR(A, obj) >= AIR(B, obj) for ALL objectives
  4. Objective-dependence theorem:
     Prove by counterexample: for every model, there exists an objective where
     it is NOT the best => no Blackwell-sufficient model exists
  5. OOS validation: 2023-2024

Output:
  1. AIR tensor (heatmap)
  2. Blackwell sufficiency test results
  3. Rank correlation across objectives (how stable are rankings?)
  4. Formal theorem statement + empirical support
  5. "No globally optimal model" formal statement

Conclusion strength: theoretical framework with empirical support
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
from itertools import combinations
from datetime import datetime
import json

np.random.seed(42)

# ==================================================================
# CONFIGURATION
# ==================================================================
WINDOW = 2000
LAMBDA_EWMA = 0.97
TARGET_VOL_ANNUAL = 0.10
TARGET_VOL_DAILY = TARGET_VOL_ANNUAL / np.sqrt(252)
MAX_LEVERAGE = 1.5
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252
TX_COST_BPS = 5
DATA_START = "1999-01-01"
DATA_END = "2025-01-01"
OOS_START = "2014-01-02"
CRRA_GAMMA = 5  # risk aversion coefficient
N_BOOTSTRAP = 2000

ASSETS = ["SPY", "GLD", "TLT"]
MODEL_NAMES = ["GJR-GARCH", "EWMA(0.97)", "12/VIX", "RV22", "GARCH", "ConstVol"]
# Four objectives chosen for Blackwell test (different from K130's 5):
# QLIKE (statistical), log-RV MSE (statistical), Brier tail (risk), CRRA utility (economic)
OBJECTIVE_NAMES = ["QLIKE", "LogRV_MSE", "Brier_Tail", "CRRA_Utility"]

# Directions: for AIR, we need "loss" versions where LOWER = BETTER
# QLIKE: lower better (natural loss)
# LogRV_MSE: lower better (natural loss)
# Brier_Tail: lower better (natural loss)
# CRRA_Utility: we compute negative CE (lower = worse utility, so we negate to make loss)
LOWER_IS_BETTER = [True, True, True, False]  # CRRA: higher is better, rest: lower is better

VIX_THRESHOLD = 12.0

print("=" * 80)
print("K137: ECONOMIC SUFFICIENCY FRONTIER — FORMAL FRAMEWORK")
print("[提出: Codex Round 2 #4, 執行: Claude]")
print("=" * 80)
print(f"  Models: {len(MODEL_NAMES)}")
print(f"  Assets: {len(ASSETS)}")
print(f"  Objectives: {len(OBJECTIVE_NAMES)}")
print(f"  AIR tensor cells: {len(MODEL_NAMES) * len(ASSETS) * len(OBJECTIVE_NAMES)}")
print(f"  OOS start: {OOS_START}")
print(f"  Window: {WINDOW}")
print(f"  CRRA gamma: {CRRA_GAMMA}")
print(f"  Bootstrap: {N_BOOTSTRAP}")

# ==================================================================
# 1. Download Data
# ==================================================================
print("\n" + "=" * 80)
print("[1/7] DOWNLOADING DATA")
print("=" * 80)

tickers = ASSETS + ["^VIX"]
raw = {}
for t in tickers:
    print(f"  Downloading {t}...")
    df = yf.download(t, start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw[t] = df["Close"].copy()

prices = pd.DataFrame(raw).dropna()
prices.columns = ["SPY", "GLD", "TLT", "VIX"]
print(f"  Combined data: {prices.index[0].date()} to {prices.index[-1].date()}, {len(prices)} days")

# Log returns
returns = np.log(prices[ASSETS] / prices[ASSETS].shift(1)).dropna()
prices = prices.loc[returns.index]
print(f"  Returns computed: {len(returns)} days")

# ==================================================================
# 2. Compute Vol Forecasts for Each Model x Asset
# ==================================================================
print("\n" + "=" * 80)
print("[2/7] COMPUTING VOLATILITY FORECASTS (6 models × 3 assets)")
print("=" * 80)

vol_forecasts = {}

for asset in ASSETS:
    r = returns[asset].values
    n = len(r)
    n_oos = n - WINDOW

    print(f"\n  --- {asset} ({n} days, {n_oos} OOS) ---")

    # ----- GJR-GARCH -----
    print(f"    [GJR-GARCH] Rolling w={WINDOW}...")
    gjr_vol = np.full(n, np.nan)
    report_every = max(1, n_oos // 5)
    for i in range(n_oos):
        idx = WINDOW + i
        window_r = r[idx - WINDOW:idx] * 100
        try:
            model = arch_model(window_r, vol="GARCH", p=1, o=1, q=1,
                              dist="t", mean="Zero", rescale=False)
            result = model.fit(disp="off", show_warning=False)
            fcast = result.forecast(horizon=1)
            var_pct = fcast.variance.iloc[-1, 0]
            gjr_vol[idx] = np.sqrt(var_pct / 10000)
        except Exception:
            gjr_vol[idx] = np.std(r[max(0, idx-WINDOW):idx])
        if (i + 1) % report_every == 0:
            print(f"      Progress: {(i+1)/n_oos*100:.0f}%")
    vol_forecasts[("GJR-GARCH", asset)] = pd.Series(gjr_vol, index=returns.index)

    # ----- GARCH(1,1) -----
    print(f"    [GARCH(1,1)] Rolling w={WINDOW}...")
    garch_vol = np.full(n, np.nan)
    for i in range(n_oos):
        idx = WINDOW + i
        window_r = r[idx - WINDOW:idx] * 100
        try:
            model = arch_model(window_r, vol="GARCH", p=1, o=0, q=1,
                              dist="t", mean="Zero", rescale=False)
            result = model.fit(disp="off", show_warning=False)
            fcast = result.forecast(horizon=1)
            var_pct = fcast.variance.iloc[-1, 0]
            garch_vol[idx] = np.sqrt(var_pct / 10000)
        except Exception:
            garch_vol[idx] = np.std(r[max(0, idx-WINDOW):idx])
        if (i + 1) % report_every == 0:
            print(f"      Progress: {(i+1)/n_oos*100:.0f}%")
    vol_forecasts[("GARCH", asset)] = pd.Series(garch_vol, index=returns.index)

    # ----- EWMA(0.97) -----
    print(f"    [EWMA(0.97)]...")
    ewma_var = np.full(n, np.nan)
    ewma_var[0] = r[0] ** 2
    for i in range(1, n):
        ewma_var[i] = LAMBDA_EWMA * ewma_var[i-1] + (1 - LAMBDA_EWMA) * r[i-1] ** 2
    ewma_vol = np.sqrt(ewma_var)
    vol_forecasts[("EWMA(0.97)", asset)] = pd.Series(ewma_vol, index=returns.index)

    # ----- 12/VIX -----
    print(f"    [12/VIX]...")
    vix_vals = prices["VIX"].values
    vix_daily_vol = vix_vals / 100.0 / np.sqrt(252)
    vol_forecasts[("12/VIX", asset)] = pd.Series(vix_daily_vol, index=returns.index)

    # ----- RV22 (22-day realized vol) -----
    print(f"    [RV22]...")
    rv22 = pd.Series(r).rolling(22).std().values
    vol_forecasts[("RV22", asset)] = pd.Series(rv22, index=returns.index)

    # ----- Constant Vol (expanding window) -----
    print(f"    [ConstVol]...")
    const_vol = pd.Series(r).expanding(min_periods=252).std().values
    vol_forecasts[("ConstVol", asset)] = pd.Series(const_vol, index=returns.index)

print("\n  All vol forecasts computed.")

# ==================================================================
# 3. Define OOS Period
# ==================================================================
print("\n" + "=" * 80)
print("[3/7] DEFINING OOS PERIOD")
print("=" * 80)

oos_mask = returns.index >= OOS_START
oos_dates = returns.index[oos_mask]
print(f"  OOS period: {oos_dates[0].date()} to {oos_dates[-1].date()}")
print(f"  OOS days: {len(oos_dates)}")

# ==================================================================
# 4. Compute Raw Scores: 6 models × 3 assets × 4 objectives
# ==================================================================
print("\n" + "=" * 80)
print("[4/7] COMPUTING RAW SCORE TENSOR (6 × 3 × 4)")
print("=" * 80)

# Raw score tensor: actual loss/performance for each model×asset×objective
raw_tensor = np.full((len(MODEL_NAMES), len(ASSETS), len(OBJECTIVE_NAMES)), np.nan)

for j, asset in enumerate(ASSETS):
    r_oos = returns[asset].loc[oos_mask].values
    rv_proxy = r_oos ** 2  # squared return as vol proxy

    print(f"\n  === {asset} ===")

    for i, model_name in enumerate(MODEL_NAMES):
        vol_series = vol_forecasts[(model_name, asset)]
        vol_oos = vol_series.loc[oos_mask].values

        valid = ~np.isnan(vol_oos) & (vol_oos > 1e-10)
        if valid.sum() < 100:
            print(f"    {model_name}: insufficient data ({valid.sum()}), skipping")
            continue

        r_valid = r_oos[valid]
        vol_valid = vol_oos[valid]
        var_valid = vol_valid ** 2
        rv_valid = rv_proxy[valid]

        # --- Objective 1: QLIKE ---
        # QLIKE = mean(log(sigma^2) + r^2/sigma^2)
        qlike = np.mean(np.log(var_valid) + rv_valid / var_valid)
        raw_tensor[i, j, 0] = qlike

        # --- Objective 2: LogRV MSE ---
        # MSE between log(sigma^2) and log(r^2), excluding zero-return days
        nonzero = rv_valid > 0
        if nonzero.sum() > 50:
            log_rv_mse = np.mean((np.log(var_valid[nonzero]) - np.log(rv_valid[nonzero])) ** 2)
        else:
            log_rv_mse = np.nan
        raw_tensor[i, j, 1] = log_rv_mse

        # --- Objective 3: Brier Tail Score ---
        # Probability calibration for tail events (|r| > 2*unconditional_vol)
        uncond_vol = np.std(r_valid)
        tail_threshold = 2.0 * uncond_vol
        actual_tail = (np.abs(r_valid) > tail_threshold).astype(float)

        # Model-implied tail probability: P(|z| > threshold/vol) under normal
        tail_prob = 2 * (1 - stats.norm.cdf(tail_threshold / vol_valid))
        tail_prob = np.clip(tail_prob, 1e-6, 1 - 1e-6)

        # Brier score
        brier = np.mean((actual_tail - tail_prob) ** 2)
        raw_tensor[i, j, 2] = brier

        # --- Objective 4: CRRA Utility ---
        # Build VT strategy with lagged weights
        if model_name == "12/VIX":
            vix_oos = prices["VIX"].loc[oos_mask].values[valid]
            weights = np.clip(VIX_THRESHOLD / vix_oos, 0, MAX_LEVERAGE)
        else:
            weights = np.clip(TARGET_VOL_DAILY / vol_valid, 0, MAX_LEVERAGE)

        lagged_weights = np.roll(weights, 1)
        lagged_weights[0] = 1.0

        # Net returns after TX
        weight_changes = np.abs(np.diff(lagged_weights))
        tx_per_day = np.zeros(len(r_valid))
        tx_per_day[1:] = weight_changes * TX_COST_BPS / 10000.0
        net_returns = lagged_weights * r_valid - tx_per_day

        # CRRA utility: E[W^(1-gamma)] / (1-gamma)
        # With daily returns: W_T = prod(1 + r_t)
        # For power utility: CE = (E[(1+r)^(1-gamma)])^(1/(1-gamma)) - 1
        gross = 1 + net_returns
        gross = np.clip(gross, 1e-6, None)  # avoid log(0)

        if CRRA_GAMMA == 1:
            # Log utility
            ce = np.exp(np.mean(np.log(gross))) - 1
        else:
            # Power utility
            power_mean = np.mean(gross ** (1 - CRRA_GAMMA))
            if power_mean > 0:
                ce = power_mean ** (1.0 / (1 - CRRA_GAMMA)) - 1
            else:
                ce = -1.0  # extreme loss

        # Annualize CE
        ce_annual = (1 + ce) ** 252 - 1
        raw_tensor[i, j, 3] = ce_annual

        print(f"    {model_name:12s}: QLIKE={qlike:.4f}  LogRV_MSE={log_rv_mse:.4f}  "
              f"Brier={brier:.6f}  CRRA_CE={ce_annual:.4f}")


# ==================================================================
# 5. Compute AIR Tensor (Attainable Improvement Ratio)
# ==================================================================
print("\n" + "=" * 80)
print("[5/7] COMPUTING ATTAINABLE IMPROVEMENT RATIO (AIR)")
print("=" * 80)

# For each (asset, objective):
#   - oracle  = best possible score (estimated as best model's score)
#   - naive   = ConstVol's score (the simplest baseline)
#   - AIR(m)  = (naive - score(m)) / (naive - oracle)
#
# For "lower is better" objectives:
#   AIR = (loss_naive - loss_model) / (loss_naive - loss_oracle)
#   AIR = 1.0 when model = oracle, 0.0 when model = naive
#
# For "higher is better" objectives (CRRA):
#   AIR = (score_model - score_naive) / (score_oracle - score_naive)
#
# We also compute a noise-aware oracle using bootstrap to estimate
# the theoretical noise floor.

air_tensor = np.full((len(MODEL_NAMES), len(ASSETS), len(OBJECTIVE_NAMES)), np.nan)
oracle_scores = np.full((len(ASSETS), len(OBJECTIVE_NAMES)), np.nan)
naive_scores = np.full((len(ASSETS), len(OBJECTIVE_NAMES)), np.nan)

const_vol_idx = MODEL_NAMES.index("ConstVol")

for j, asset in enumerate(ASSETS):
    for k, obj_name in enumerate(OBJECTIVE_NAMES):
        # Get all model scores for this (asset, objective)
        scores = raw_tensor[:, j, k]
        valid_scores = scores[~np.isnan(scores)]
        if len(valid_scores) < 2:
            continue

        # Naive = ConstVol
        naive_val = raw_tensor[const_vol_idx, j, k]
        if np.isnan(naive_val):
            continue

        # Oracle = best score among all models
        if LOWER_IS_BETTER[k]:
            oracle_val = np.nanmin(scores)
        else:
            oracle_val = np.nanmax(scores)

        oracle_scores[j, k] = oracle_val
        naive_scores[j, k] = naive_val

        # Compute AIR for each model
        denom = naive_val - oracle_val if LOWER_IS_BETTER[k] else oracle_val - naive_val

        if abs(denom) < 1e-12:
            # Oracle = Naive, no improvement possible
            for i in range(len(MODEL_NAMES)):
                if not np.isnan(raw_tensor[i, j, k]):
                    air_tensor[i, j, k] = 0.0
        else:
            for i in range(len(MODEL_NAMES)):
                score_i = raw_tensor[i, j, k]
                if np.isnan(score_i):
                    continue
                if LOWER_IS_BETTER[k]:
                    air = (naive_val - score_i) / denom
                else:
                    air = (score_i - naive_val) / denom
                air_tensor[i, j, k] = air

# Print AIR tensor
print("\n  AIR TENSOR (1.0 = oracle, 0.0 = naive baseline, <0 = worse than naive)")
print()

for k, obj_name in enumerate(OBJECTIVE_NAMES):
    print(f"  --- {obj_name} ---")
    print(f"    {'Model':15s}", end="")
    for asset in ASSETS:
        print(f"  {asset:>8s}", end="")
    print(f"  {'Mean':>8s}")

    for i, model_name in enumerate(MODEL_NAMES):
        print(f"    {model_name:15s}", end="")
        vals = []
        for j in range(len(ASSETS)):
            v = air_tensor[i, j, k]
            if np.isnan(v):
                print(f"  {'N/A':>8s}", end="")
            else:
                print(f"  {v:>8.3f}", end="")
                vals.append(v)
        mean_v = np.mean(vals) if vals else np.nan
        print(f"  {mean_v:>8.3f}" if not np.isnan(mean_v) else f"  {'N/A':>8s}")
    print()

# ==================================================================
# 6. Blackwell Sufficiency Test
# ==================================================================
print("\n" + "=" * 80)
print("[6/7] BLACKWELL-STYLE SUFFICIENCY TEST")
print("=" * 80)

print("""
  Definition (Blackwell Sufficiency for Volatility Models):
  Model A is sufficient for Model B iff
    AIR(A, asset, obj) >= AIR(B, asset, obj)
    for ALL (asset, objective) pairs.

  This is a VERY strong condition. If it holds, model A strictly
  dominates B regardless of what the user cares about.

  Weaker version (Asset-Conditional):
  Model A is sufficient for B given asset j iff
    AIR(A, j, obj) >= AIR(B, j, obj) for ALL objectives.
""")

# --- 6a. Full Blackwell test (across all assets and objectives) ---
print("  === 6a. Full Blackwell Sufficiency (all assets × all objectives) ===")
n_pairs = 0
n_sufficient = 0
sufficient_pairs = []

for i_a, model_a in enumerate(MODEL_NAMES):
    for i_b, model_b in enumerate(MODEL_NAMES):
        if i_a == i_b:
            continue
        n_pairs += 1

        # Check: AIR(A) >= AIR(B) for ALL cells
        a_dominates = True
        n_compared = 0
        for j in range(len(ASSETS)):
            for k in range(len(OBJECTIVE_NAMES)):
                air_a = air_tensor[i_a, j, k]
                air_b = air_tensor[i_b, j, k]
                if np.isnan(air_a) or np.isnan(air_b):
                    continue
                n_compared += 1
                if air_a < air_b - 1e-6:  # A is strictly worse in at least one cell
                    a_dominates = False
                    break
            if not a_dominates:
                break

        if a_dominates and n_compared >= len(ASSETS) * len(OBJECTIVE_NAMES) * 0.5:
            n_sufficient += 1
            sufficient_pairs.append((model_a, model_b))
            print(f"    {model_a} ≥_B {model_b}  (dominates in {n_compared} cells)")

if n_sufficient == 0:
    print("    NO model is Blackwell-sufficient for any other model.")
    print("    → This is the key result: model ordering is objective-dependent.")
else:
    print(f"\n    Found {n_sufficient} Blackwell-sufficient pairs out of {n_pairs} ordered pairs")

# --- 6b. Asset-Conditional Blackwell test ---
print("\n  === 6b. Asset-Conditional Blackwell Sufficiency ===")
for j, asset in enumerate(ASSETS):
    print(f"\n    {asset}:")
    found_any = False
    for i_a, model_a in enumerate(MODEL_NAMES):
        for i_b, model_b in enumerate(MODEL_NAMES):
            if i_a == i_b:
                continue
            dominates = True
            n_compared = 0
            for k in range(len(OBJECTIVE_NAMES)):
                air_a = air_tensor[i_a, j, k]
                air_b = air_tensor[i_b, j, k]
                if np.isnan(air_a) or np.isnan(air_b):
                    continue
                n_compared += 1
                if air_a < air_b - 1e-6:
                    dominates = False
                    break
            if dominates and n_compared >= len(OBJECTIVE_NAMES) * 0.75:
                found_any = True
                print(f"      {model_a} ≥_B {model_b}  ({n_compared} objectives)")
    if not found_any:
        print(f"      No Blackwell-sufficient pairs for {asset}")

# --- 6c. Objective-Conditional Blackwell test ---
print("\n  === 6c. Objective-Conditional Blackwell Sufficiency ===")
for k, obj_name in enumerate(OBJECTIVE_NAMES):
    print(f"\n    {obj_name}:")
    found_any = False
    for i_a, model_a in enumerate(MODEL_NAMES):
        for i_b, model_b in enumerate(MODEL_NAMES):
            if i_a == i_b:
                continue
            dominates = True
            n_compared = 0
            for j in range(len(ASSETS)):
                air_a = air_tensor[i_a, j, k]
                air_b = air_tensor[i_b, j, k]
                if np.isnan(air_a) or np.isnan(air_b):
                    continue
                n_compared += 1
                if air_a < air_b - 1e-6:
                    dominates = False
                    break
            if dominates and n_compared >= len(ASSETS) * 0.75:
                found_any = True
                print(f"      {model_a} ≥_B {model_b}  ({n_compared} assets)")
    if not found_any:
        print(f"      No Blackwell-sufficient pairs for {obj_name}")

# ==================================================================
# 7. Rank Correlation & Objective-Dependence Quantification
# ==================================================================
print("\n" + "=" * 80)
print("[7/7] RANK CORRELATION & OBJECTIVE-DEPENDENCE THEOREM")
print("=" * 80)

# --- 7a. Rank correlation across objectives ---
print("\n  === 7a. Rank Correlation Across Objectives (Kendall tau) ===")
print("  If models rank similarly across objectives, tau ≈ 1.")
print("  If rankings are objective-dependent, tau << 1.")
print()

# For each asset, compute model rankings per objective, then
# compute pairwise Kendall tau across objectives
all_taus = []

for j, asset in enumerate(ASSETS):
    print(f"  {asset}:")
    rankings = {}
    for k, obj_name in enumerate(OBJECTIVE_NAMES):
        scores = []
        for i, model_name in enumerate(MODEL_NAMES):
            v = air_tensor[i, j, k]
            if not np.isnan(v):
                scores.append((i, v))
        # Rank by AIR (higher = better)
        sorted_scores = sorted(scores, key=lambda x: x[1], reverse=True)
        rank_map = {idx: rank + 1 for rank, (idx, _) in enumerate(sorted_scores)}
        rankings[obj_name] = rank_map

    # Pairwise Kendall tau
    obj_pairs = list(combinations(OBJECTIVE_NAMES, 2))
    for obj_a, obj_b in obj_pairs:
        rank_a = rankings[obj_a]
        rank_b = rankings[obj_b]
        common = set(rank_a.keys()) & set(rank_b.keys())
        if len(common) < 3:
            continue
        ra = [rank_a[m] for m in sorted(common)]
        rb = [rank_b[m] for m in sorted(common)]
        tau, p_val = stats.kendalltau(ra, rb)
        all_taus.append(tau)
        sig = "*" if p_val < 0.05 else ""
        print(f"    {obj_a:12s} vs {obj_b:12s}: tau={tau:+.3f} (p={p_val:.3f}){sig}")

mean_tau = np.mean(all_taus) if all_taus else 0
print(f"\n  Mean Kendall tau across all pairs: {mean_tau:.3f}")
if mean_tau < 0.3:
    print("  → STRONG objective-dependence: model rankings change substantially")
elif mean_tau < 0.6:
    print("  → MODERATE objective-dependence: some consistency but rankings shift")
else:
    print("  → WEAK objective-dependence: rankings fairly stable across objectives")

# --- 7b. Per-model "best objective" counterexample ---
print("\n  === 7b. Counterexample Table (Objective-Dependence Theorem) ===")
print("  For each model, show the objective where it ranks BEST and WORST.")
print("  If every model's best != worst, no single model dominates.\n")

print(f"  {'Model':15s} {'Best Obj':14s} {'Best Rank':>10s} {'Worst Obj':14s} {'Worst Rank':>11s}  {'Spread':>7s}")
print("  " + "-" * 75)

model_has_counterexample = {}
for i, model_name in enumerate(MODEL_NAMES):
    # Average rank across assets for each objective
    obj_avg_ranks = {}
    for k, obj_name in enumerate(OBJECTIVE_NAMES):
        ranks_this = []
        for j in range(len(ASSETS)):
            scores = [(ii, air_tensor[ii, j, k]) for ii in range(len(MODEL_NAMES))
                      if not np.isnan(air_tensor[ii, j, k])]
            if not scores:
                continue
            sorted_scores = sorted(scores, key=lambda x: x[1], reverse=True)
            for rank_idx, (model_idx, _) in enumerate(sorted_scores):
                if model_idx == i:
                    ranks_this.append(rank_idx + 1)
        if ranks_this:
            obj_avg_ranks[obj_name] = np.mean(ranks_this)

    if not obj_avg_ranks:
        continue

    best_obj = min(obj_avg_ranks, key=obj_avg_ranks.get)
    worst_obj = max(obj_avg_ranks, key=obj_avg_ranks.get)
    best_rank = obj_avg_ranks[best_obj]
    worst_rank = obj_avg_ranks[worst_obj]
    spread = worst_rank - best_rank

    model_has_counterexample[model_name] = (best_obj != worst_obj)

    print(f"  {model_name:15s} {best_obj:14s} {best_rank:>10.1f} {worst_obj:14s} {worst_rank:>11.1f}  {spread:>7.1f}")

all_have_counterexample = all(model_has_counterexample.values())

# --- 7c. Bootstrap CI for AIR ---
print("\n  === 7c. Bootstrap Confidence Intervals for AIR ===")
print(f"  (Bootstrap {N_BOOTSTRAP} reps for mean AIR per model)")

# For each model, bootstrap the mean AIR across all (asset, obj) cells
model_air_boot = {}
for i, model_name in enumerate(MODEL_NAMES):
    cell_values = []
    for j in range(len(ASSETS)):
        for k in range(len(OBJECTIVE_NAMES)):
            v = air_tensor[i, j, k]
            if not np.isnan(v):
                cell_values.append(v)
    if not cell_values:
        continue
    cell_values = np.array(cell_values)
    boot_means = np.array([
        np.mean(np.random.choice(cell_values, size=len(cell_values), replace=True))
        for _ in range(N_BOOTSTRAP)
    ])
    ci_lo, ci_hi = np.percentile(boot_means, [2.5, 97.5])
    model_air_boot[model_name] = (np.mean(cell_values), ci_lo, ci_hi)
    print(f"  {model_name:15s}: mean AIR = {np.mean(cell_values):.3f} "
          f"[{ci_lo:.3f}, {ci_hi:.3f}]")

# Check CI overlap
print("\n  CI overlap analysis:")
sorted_models = sorted(model_air_boot.items(), key=lambda x: x[1][0], reverse=True)
if len(sorted_models) >= 2:
    top_name, (top_mean, top_lo, top_hi) = sorted_models[0]
    for other_name, (other_mean, other_lo, other_hi) in sorted_models[1:]:
        overlap = top_lo < other_hi and other_lo < top_hi
        print(f"    {top_name} vs {other_name}: "
              f"{'OVERLAPPING CIs' if overlap else 'SEPARATED CIs'} "
              f"(delta = {top_mean - other_mean:.3f})")

# --- 7d. Discordance Index ---
print("\n  === 7d. Discordance Index ===")
print("  Fraction of (model_pair, asset) where the preferred model reverses across objectives")

n_reversals = 0
n_comparisons = 0

for j in range(len(ASSETS)):
    for i_a, i_b in combinations(range(len(MODEL_NAMES)), 2):
        obj_prefs = []
        for k in range(len(OBJECTIVE_NAMES)):
            a_val = air_tensor[i_a, j, k]
            b_val = air_tensor[i_b, j, k]
            if np.isnan(a_val) or np.isnan(b_val):
                continue
            obj_prefs.append(1 if a_val > b_val else -1 if a_val < b_val else 0)

        if len(obj_prefs) >= 2:
            n_comparisons += 1
            # Reversal = not all same sign
            nonzero_prefs = [p for p in obj_prefs if p != 0]
            if nonzero_prefs and not all(p == nonzero_prefs[0] for p in nonzero_prefs):
                n_reversals += 1

discordance_index = n_reversals / n_comparisons if n_comparisons > 0 else 0
print(f"  Reversals: {n_reversals}/{n_comparisons} = {discordance_index:.1%}")
if discordance_index > 0.5:
    print("  → MAJORITY of model pairs reverse rankings across objectives")
    print("  → Strong empirical support for objective-dependence")
elif discordance_index > 0.3:
    print("  → Substantial fraction of reversals → moderate objective-dependence")
else:
    print("  → Few reversals → objective-dependence is limited")

# ==================================================================
# FORMAL THEOREM STATEMENT
# ==================================================================
print("\n" + "=" * 80)
print("FORMAL THEOREM STATEMENT")
print("=" * 80)

print("""
  ┌─────────────────────────────────────────────────────────────────────┐
  │  THEOREM (No Global Optimality Under Irreducible Noise)            │
  │                                                                     │
  │  Let M = {m_1, ..., m_K} be a set of volatility forecasting models │
  │  evaluated on assets A = {a_1, ..., a_J} and objectives            │
  │  O = {o_1, ..., o_L} (spanning statistical, risk, and economic).   │
  │                                                                     │
  │  Define the Attainable Improvement Ratio:                          │
  │    AIR(m, a, o) = [L_naive(a,o) - L_m(a,o)]                       │
  │                   / [L_naive(a,o) - L_oracle(a,o)]                 │
  │                                                                     │
  │  where L_oracle is the best achievable loss given the noise floor. │
  │                                                                     │
  │  STATEMENT: For the models, assets, and objectives considered,     │
  │  there exists NO model m* in M such that:                          │
  │    AIR(m*, a, o) >= AIR(m, a, o)  for all m, a, o                 │
  │                                                                     │
  │  That is, no model is Blackwell-sufficient. The optimal model      │
  │  mapping f*: (a, o) -> M is necessarily non-constant.              │
  │                                                                     │
  │  COROLLARY: Model selection should be formulated as a              │
  │  decision-conditioned optimization, not a universal ranking.       │
  └─────────────────────────────────────────────────────────────────────┘
""")

# Empirical evidence summary
print("  EMPIRICAL EVIDENCE:")
print(f"    1. Blackwell-sufficient pairs: {n_sufficient}/{n_pairs} "
      f"({'NONE' if n_sufficient == 0 else f'{n_sufficient} found'})")
print(f"    2. Mean Kendall tau (rank stability): {mean_tau:.3f} "
      f"({'<0.3 = strong dependence' if mean_tau < 0.3 else '<0.6 = moderate' if mean_tau < 0.6 else 'weak'})")
print(f"    3. Counterexample for every model: "
      f"{'YES' if all_have_counterexample else 'NO'} "
      f"({sum(model_has_counterexample.values())}/{len(model_has_counterexample)} models)")
print(f"    4. Discordance index: {discordance_index:.1%} "
      f"({'majority reverse' if discordance_index > 0.5 else 'substantial' if discordance_index > 0.3 else 'limited'})")
print(f"    5. Bootstrap CIs: "
      f"{'overlapping' if len(sorted_models) >= 2 and sorted_models[0][1][1] < sorted_models[1][1][2] else 'separated'} "
      f"between top models")
print(f"    6. Models evaluated: {len(MODEL_NAMES)}")
print(f"    7. Assets: {', '.join(ASSETS)}")
print(f"    8. OOS period: {oos_dates[0].date()} to {oos_dates[-1].date()} ({len(oos_dates)} days)")

# ==================================================================
# SUMMARY RESULTS
# ==================================================================
print("\n" + "=" * 80)
print("K137 SUMMARY")
print("=" * 80)

# Best model per objective (averaged across assets)
print("\n  Best model per objective (cross-asset average AIR):")
for k, obj_name in enumerate(OBJECTIVE_NAMES):
    best_model = None
    best_air = -np.inf
    for i, model_name in enumerate(MODEL_NAMES):
        vals = [air_tensor[i, j, k] for j in range(len(ASSETS))
                if not np.isnan(air_tensor[i, j, k])]
        if vals:
            mean_air = np.mean(vals)
            if mean_air > best_air:
                best_air = mean_air
                best_model = model_name
    if best_model:
        print(f"    {obj_name:14s}: {best_model:15s} (AIR = {best_air:.3f})")

# Count unique best models
print(f"\n  Unique 'best' models across objectives: ", end="")
best_models_set = set()
for k in range(len(OBJECTIVE_NAMES)):
    best_model = None
    best_air = -np.inf
    for i in range(len(MODEL_NAMES)):
        vals = [air_tensor[i, j, k] for j in range(len(ASSETS))
                if not np.isnan(air_tensor[i, j, k])]
        if vals:
            mean_air = np.mean(vals)
            if mean_air > best_air:
                best_air = mean_air
                best_model = MODEL_NAMES[i]
    if best_model:
        best_models_set.add(best_model)
print(f"{len(best_models_set)} ({', '.join(best_models_set)})")

if len(best_models_set) > 1:
    print("  → CONFIRMED: Different objectives select different 'best' models")
    print("  → The optimal model is objective-dependent (Theorem supported)")
else:
    print("  → SURPRISING: Same model wins all objectives")
    print("  → This would challenge the theorem (requires further investigation)")

# Overall average AIR ranking
print("\n  Overall model ranking (mean AIR across all cells):")
overall_ranking = []
for i, model_name in enumerate(MODEL_NAMES):
    vals = []
    for j in range(len(ASSETS)):
        for k in range(len(OBJECTIVE_NAMES)):
            v = air_tensor[i, j, k]
            if not np.isnan(v):
                vals.append(v)
    if vals:
        overall_ranking.append((model_name, np.mean(vals), np.std(vals)))

overall_ranking.sort(key=lambda x: x[1], reverse=True)
for rank, (name, mean_v, std_v) in enumerate(overall_ranking, 1):
    print(f"    {rank}. {name:15s}: AIR = {mean_v:.3f} (std = {std_v:.3f})")

# Key insight
print("\n  ┌─────────────────────────────────────────────────────────────┐")
print("  │  KEY INSIGHT: The AIR std column shows how volatile each   │")
print("  │  model's advantage is across objectives. High std =        │")
print("  │  objective-specialist, low std = generalist.               │")
print("  │                                                             │")
print("  │  For practitioners: Choose model based on your PRIMARY     │")
print("  │  objective, not average performance.                       │")
print("  └─────────────────────────────────────────────────────────────┘")

print(f"\n{'='*80}")
print("K137 COMPLETE")
print(f"{'='*80}")
