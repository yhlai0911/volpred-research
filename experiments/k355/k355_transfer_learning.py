"""
K355: Transfer Learning for Volatility — Can SPY Vol Knowledge Help Predict Other Assets?
==========================================================================================

Hypothesis:
  SPY has the MOST data and BEST vol predictability (confirmed across 15+ experiments).
  Can we "transfer" SPY's GARCH parameters as informative priors for other assets?
  This is especially useful for assets with short history or poor predictability.

Related findings:
  - K207: VIX sufficient for equity, NOT for others
  - K342: Oil GARCH QLIKE 2.5x worse than SPY
  - K345: FX GARCH OOS R²=0.04 (poor)
  - K352: Bayesian shrinkage helps SPY but hurts GLD

Method:
  1. "Source model": fit GJR-GARCH on SPY (w=2000) to get reference params
  2. "Transfer" approaches for each target asset:
     a. Direct transfer: use SPY's GARCH params on target asset (no refit) — baseline
     b. Fine-tuned transfer: initialize with SPY params, refit on target with small window (w=500)
     c. Blended: weighted average of SPY-initialized and target-only variance forecasts
  3. Benchmarks:
     - Target-only GARCH (w=2000, full window)
     - Target-only GARCH (w=500, small window — simulates limited data)
  4. Evaluation: QLIKE on OOS period (2023-01 ~ 2025-12)
  5. Statistical test: Diebold-Mariano for significance

Key question: Does SPY knowledge transfer to improve short-sample vol prediction?

Data: yfinance real data — SPY, GLD, TLT, BTC-USD, CL=F

[提出: 用戶 (K355 transfer learning exploration), 執行: Claude]
"""

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ============================================================
# CONFIG
# ============================================================
DATA_START = "2005-01-01"
DATA_END = "2026-12-31"
OOS_START = "2023-01-01"
OOS_END = "2025-12-31"
WINDOW_FULL = 2000
WINDOW_SMALL = 500
SOURCE_ASSET = "SPY"
TARGET_ASSETS = {
    "GLD": "GLD",
    "TLT": "TLT",
    "BTC": "BTC-USD",
    "Oil": "CL=F",
}
BLEND_WEIGHTS = [0.2, 0.4, 0.6, 0.8]  # weight on transfer model

print("=" * 80)
print("K355: TRANSFER LEARNING FOR VOLATILITY")
print("Can SPY GARCH knowledge help predict other assets?")
print("=" * 80)


# ============================================================
# HELPER FUNCTIONS
# ============================================================
def qlike_loss(realized, predicted):
    """QLIKE loss: mean(log(pred) + realized/pred). Lower is better."""
    mask = (predicted > 0) & (realized > 0) & np.isfinite(realized) & np.isfinite(predicted)
    r = realized[mask]
    p = predicted[mask]
    if len(r) == 0:
        return np.nan
    return np.mean(np.log(p) + r / p)


def qlike_losses_array(realized, predicted):
    """Per-observation QLIKE losses for DM test."""
    mask = (predicted > 0) & (realized > 0) & np.isfinite(realized) & np.isfinite(predicted)
    r = realized[mask]
    p = predicted[mask]
    return np.log(p) + r / p


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. H0: equal predictive ability.
    Returns (t-stat, p-value). Negative t → model 1 is better."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    if len(d) < 10:
        return np.nan, np.nan
    n = len(d)
    d_mean = np.mean(d)
    # HAC variance (Newey-West with h-1 lags)
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k
    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        return np.nan, np.nan
    t_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * stats.t.sf(abs(t_stat), df=n - 1)
    return t_stat, p_value


def fetch_data(ticker, start, end):
    """Fetch daily data from yfinance."""
    print(f"  Fetching {ticker}...")
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Close"]].dropna()
    df["return"] = np.log(df["Close"] / df["Close"].shift(1)) * 100  # pct log return
    df["realized_var"] = df["return"] ** 2  # squared return proxy
    df = df.dropna()
    print(f"    Got {len(df)} observations: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    return df


def fit_gjr_garch(returns, p=1, o=1, q=1, dist="normal"):
    """Fit GJR-GARCH and return model result."""
    am = arch_model(returns, vol="Garch", p=p, o=o, q=q, dist=dist, mean="Constant")
    try:
        res = am.fit(disp="off", show_warning=False)
        return res
    except Exception:
        return None


def extract_garch_params(res):
    """Extract GARCH params from fitted result."""
    params = res.params
    return {
        "mu": params.get("mu", 0.0),
        "omega": params["omega"],
        "alpha": params["alpha[1]"],
        "gamma": params.get("gamma[1]", 0.0),
        "beta": params["beta[1]"],
    }


def rolling_garch_forecast(returns, window, oos_start_idx):
    """Rolling GJR-GARCH forecast. Returns array of variance forecasts."""
    n = len(returns)
    forecasts = np.full(n, np.nan)

    for t in range(oos_start_idx, n):
        start_idx = max(0, t - window)
        train = returns.iloc[start_idx:t]
        if len(train) < 100:
            continue

        res = fit_gjr_garch(train)
        if res is None:
            continue

        # One-step-ahead forecast
        fcast = res.forecast(horizon=1)
        forecasts[t] = fcast.variance.iloc[-1, 0]

    return forecasts


def direct_transfer_forecast(target_returns, source_params, oos_start_idx):
    """Apply SPY's GARCH params directly to target asset's returns.
    No refitting — pure parameter transfer.
    Uses the GJR-GARCH recursion: σ²_t = ω + α·r²_{t-1} + γ·r²_{t-1}·I(r<0) + β·σ²_{t-1}
    """
    n = len(target_returns)
    forecasts = np.full(n, np.nan)
    r = target_returns.values

    omega = source_params["omega"]
    alpha = source_params["alpha"]
    gamma = source_params["gamma"]
    beta = source_params["beta"]

    # Initialize variance with unconditional variance of target
    unc_var = np.var(r[:oos_start_idx]) if oos_start_idx > 0 else np.var(r[:500])

    # Run GARCH recursion from start to build up variance path
    sigma2 = np.full(n, unc_var)
    for t in range(1, n):
        indicator = 1.0 if r[t - 1] < 0 else 0.0
        sigma2[t] = omega + alpha * r[t - 1] ** 2 + gamma * r[t - 1] ** 2 * indicator + beta * sigma2[t - 1]
        sigma2[t] = max(sigma2[t], 1e-8)  # floor

    # Forecast for t is σ²_t (computed using info up to t-1)
    for t in range(oos_start_idx, n):
        indicator = 1.0 if r[t - 1] < 0 else 0.0
        forecasts[t] = omega + alpha * r[t - 1] ** 2 + gamma * r[t - 1] ** 2 * indicator + beta * sigma2[t - 1]
        forecasts[t] = max(forecasts[t], 1e-8)
        sigma2[t] = forecasts[t]  # update for next step

    return forecasts


def finetune_transfer_forecast(target_returns, source_params, window, oos_start_idx):
    """Initialize GARCH estimation with SPY params, refit on target with small window.
    The arch library doesn't support warm-starting from params, so we:
    1. Use source params to set starting values for optimization
    2. Fit on small window of target data
    """
    n = len(target_returns)
    forecasts = np.full(n, np.nan)

    for t in range(oos_start_idx, n):
        start_idx = max(0, t - window)
        train = target_returns.iloc[start_idx:t]
        if len(train) < 100:
            continue

        am = arch_model(train, vol="Garch", p=1, o=1, q=1, dist="normal", mean="Constant")

        # Use source params as starting values
        starting_values = np.array([
            source_params["mu"],
            source_params["omega"],
            source_params["alpha"],
            source_params["gamma"],
            source_params["beta"],
        ])

        try:
            res = am.fit(
                disp="off",
                show_warning=False,
                starting_values=starting_values,
            )
            fcast = res.forecast(horizon=1)
            forecasts[t] = fcast.variance.iloc[-1, 0]
        except Exception:
            # Fallback: fit without starting values
            try:
                res = am.fit(disp="off", show_warning=False)
                fcast = res.forecast(horizon=1)
                forecasts[t] = fcast.variance.iloc[-1, 0]
            except Exception:
                continue

    return forecasts


def blended_forecast(forecast_transfer, forecast_target, weight_transfer):
    """Blend transfer and target-only forecasts."""
    blended = np.full_like(forecast_transfer, np.nan)
    valid = np.isfinite(forecast_transfer) & np.isfinite(forecast_target) & (forecast_transfer > 0) & (forecast_target > 0)
    blended[valid] = weight_transfer * forecast_transfer[valid] + (1 - weight_transfer) * forecast_target[valid]
    return blended


# ============================================================
# DATA COLLECTION
# ============================================================
print("\n[1] Fetching data from yfinance...")
all_data = {}
all_tickers = {SOURCE_ASSET: SOURCE_ASSET}
all_tickers.update(TARGET_ASSETS)

for name, ticker in all_tickers.items():
    all_data[name] = fetch_data(ticker, DATA_START, DATA_END)

# ============================================================
# SOURCE MODEL: Fit GJR-GARCH on SPY (full sample pre-OOS)
# ============================================================
print("\n[2] Fitting source model: GJR-GARCH on SPY...")
spy_data = all_data[SOURCE_ASSET]
spy_oos_idx = spy_data.index.get_indexer([pd.Timestamp(OOS_START)], method="bfill")[0]

# Fit on pre-OOS data
spy_pre_oos = spy_data["return"].iloc[:spy_oos_idx]
spy_res = fit_gjr_garch(spy_pre_oos)
if spy_res is None:
    print("ERROR: Cannot fit SPY source model!")
    sys.exit(1)

spy_params = extract_garch_params(spy_res)
print(f"\n  SPY GJR-GARCH params (source model, w={len(spy_pre_oos)}):")
for k, v in spy_params.items():
    print(f"    {k:>8s} = {v:.6f}")

# Persistence check
persistence = spy_params["alpha"] + spy_params["gamma"] / 2 + spy_params["beta"]
print(f"    persistence = {persistence:.4f}")

# ============================================================
# RUN EXPERIMENTS ON EACH TARGET ASSET
# ============================================================
print("\n[3] Running transfer learning experiments...")
results = {}

for asset_name, ticker in TARGET_ASSETS.items():
    print(f"\n{'='*60}")
    print(f"  TARGET: {asset_name} ({ticker})")
    print(f"{'='*60}")

    target_data = all_data[asset_name]
    target_returns = target_data["return"]
    target_realized = target_data["realized_var"].values

    # Find OOS start index for this asset
    oos_candidates = target_data.index[target_data.index >= pd.Timestamp(OOS_START)]
    if len(oos_candidates) == 0:
        print(f"  SKIP: No OOS data for {asset_name}")
        continue
    oos_start_idx = target_data.index.get_loc(oos_candidates[0])

    n_oos = len(target_data) - oos_start_idx
    print(f"  OOS period: {target_data.index[oos_start_idx].strftime('%Y-%m-%d')} to {target_data.index[-1].strftime('%Y-%m-%d')} ({n_oos} obs)")

    # Also fit target's own pre-OOS model for comparison
    target_pre_oos = target_returns.iloc[:oos_start_idx]
    target_res = fit_gjr_garch(target_pre_oos)
    if target_res is not None:
        target_params = extract_garch_params(target_res)
        print(f"\n  {asset_name} own params:")
        for k, v in target_params.items():
            print(f"    {k:>8s} = {v:.6f}")
        t_persistence = target_params["alpha"] + target_params["gamma"] / 2 + target_params["beta"]
        print(f"    persistence = {t_persistence:.4f}")
    else:
        target_params = None

    # --- Approach 1: Target-only GARCH (w=2000, full benchmark) ---
    print(f"\n  [A] Target-only GJR-GARCH (w={WINDOW_FULL})...")
    fc_target_full = rolling_garch_forecast(target_returns, WINDOW_FULL, oos_start_idx)

    # --- Approach 2: Target-only GARCH (w=500, small window) ---
    print(f"  [B] Target-only GJR-GARCH (w={WINDOW_SMALL})...")
    fc_target_small = rolling_garch_forecast(target_returns, WINDOW_SMALL, oos_start_idx)

    # --- Approach 3: Direct transfer (SPY params, no refit) ---
    print(f"  [C] Direct transfer (SPY params, no refit)...")
    fc_direct = direct_transfer_forecast(target_returns, spy_params, oos_start_idx)

    # --- Approach 4: Fine-tuned transfer (SPY init, refit w=500) ---
    print(f"  [D] Fine-tuned transfer (SPY init, refit w={WINDOW_SMALL})...")
    fc_finetune = finetune_transfer_forecast(target_returns, spy_params, WINDOW_SMALL, oos_start_idx)

    # --- Approach 5: Blended forecasts ---
    print(f"  [E] Blended forecasts (multiple weights)...")

    # Compute QLIKE for all approaches
    oos_realized = target_realized[oos_start_idx:]

    approaches = {
        f"Target-only (w={WINDOW_FULL})": fc_target_full[oos_start_idx:],
        f"Target-only (w={WINDOW_SMALL})": fc_target_small[oos_start_idx:],
        "Direct transfer (SPY)": fc_direct[oos_start_idx:],
        f"Fine-tuned (SPY→w={WINDOW_SMALL})": fc_finetune[oos_start_idx:],
    }

    # Add blended approaches
    for w in BLEND_WEIGHTS:
        blended = blended_forecast(fc_finetune[oos_start_idx:], fc_target_full[oos_start_idx:], w)
        approaches[f"Blend({w:.0%} transfer)"] = blended

    print(f"\n  QLIKE Results for {asset_name}:")
    print(f"  {'Approach':<35s} {'QLIKE':>10s} {'Valid N':>8s}")
    print(f"  {'-'*55}")

    approach_qlikes = {}
    approach_losses = {}  # per-obs losses for DM test
    for name, fc in approaches.items():
        ql = qlike_loss(oos_realized, fc)
        valid_n = np.sum(np.isfinite(fc) & (fc > 0) & (oos_realized > 0) & np.isfinite(oos_realized))
        approach_qlikes[name] = ql
        approach_losses[name] = qlike_losses_array(oos_realized, fc)
        print(f"  {name:<35s} {ql:10.4f} {valid_n:8d}")

    # Find best approach
    valid_qlikes = {k: v for k, v in approach_qlikes.items() if np.isfinite(v)}
    if valid_qlikes:
        best_name = min(valid_qlikes, key=valid_qlikes.get)
        best_ql = valid_qlikes[best_name]
        print(f"\n  ★ Best: {best_name} (QLIKE={best_ql:.4f})")

    # DM tests: compare each transfer approach vs target-only (w=2000)
    baseline_key = f"Target-only (w={WINDOW_FULL})"
    if baseline_key in approach_losses:
        baseline_loss = approach_losses[baseline_key]
        print(f"\n  DM test vs {baseline_key}:")
        print(f"  {'Approach':<35s} {'DM t-stat':>10s} {'p-value':>10s} {'Signif':>8s}")
        print(f"  {'-'*65}")

        dm_results = {}
        for name, losses in approach_losses.items():
            if name == baseline_key:
                continue
            # Ensure same length
            min_len = min(len(baseline_loss), len(losses))
            if min_len < 10:
                continue
            t_stat, p_val = dm_test(losses[:min_len], baseline_loss[:min_len])
            signif = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
            direction = "BETTER" if t_stat < 0 else "WORSE"
            dm_results[name] = {"t_stat": t_stat, "p_value": p_val, "direction": direction}
            print(f"  {name:<35s} {t_stat:10.3f} {p_val:10.4f} {signif:>8s} ({direction})")

    # Store results
    results[asset_name] = {
        "n_oos": int(n_oos),
        "oos_period": f"{target_data.index[oos_start_idx].strftime('%Y-%m-%d')} to {target_data.index[-1].strftime('%Y-%m-%d')}",
        "qlikes": {k: float(v) if np.isfinite(v) else None for k, v in approach_qlikes.items()},
        "dm_tests": dm_results if baseline_key in approach_losses else {},
        "best_approach": best_name if valid_qlikes else None,
        "spy_params": {k: float(v) for k, v in spy_params.items()},
        "target_params": {k: float(v) for k, v in target_params.items()} if target_params else None,
    }


# ============================================================
# PARAMETER DISTANCE ANALYSIS
# ============================================================
print("\n\n" + "=" * 80)
print("PARAMETER DISTANCE ANALYSIS")
print("How different are SPY's GARCH params from each target?")
print("=" * 80)

print(f"\n{'Asset':<10s} {'omega_diff':>12s} {'alpha_diff':>12s} {'gamma_diff':>12s} {'beta_diff':>12s} {'persist_diff':>12s} {'Transfer':>10s}")
print("-" * 80)

for asset_name in TARGET_ASSETS:
    if asset_name not in results or results[asset_name]["target_params"] is None:
        continue
    tp = results[asset_name]["target_params"]
    sp = results[asset_name]["spy_params"]

    diffs = {
        "omega": tp["omega"] - sp["omega"],
        "alpha": tp["alpha"] - sp["alpha"],
        "gamma": tp["gamma"] - sp["gamma"],
        "beta": tp["beta"] - sp["beta"],
    }
    sp_persist = sp["alpha"] + sp["gamma"] / 2 + sp["beta"]
    tp_persist = tp["alpha"] + tp["gamma"] / 2 + tp["beta"]

    # Was transfer beneficial?
    qlikes = results[asset_name]["qlikes"]
    target_full_ql = qlikes.get(f"Target-only (w={WINDOW_FULL})", np.nan)
    best_transfer_ql = np.inf
    best_transfer_name = None
    for k, v in qlikes.items():
        if "transfer" in k.lower() or "fine" in k.lower() or "blend" in k.lower() or "direct" in k.lower():
            if v is not None and v < best_transfer_ql:
                best_transfer_ql = v
                best_transfer_name = k

    transfer_helped = "YES" if best_transfer_ql < target_full_ql else "NO"

    print(f"{asset_name:<10s} {diffs['omega']:12.4f} {diffs['alpha']:12.4f} {diffs['gamma']:12.4f} {diffs['beta']:12.4f} {tp_persist - sp_persist:12.4f} {transfer_helped:>10s}")


# ============================================================
# CROSS-ASSET SUMMARY
# ============================================================
print("\n\n" + "=" * 80)
print("CROSS-ASSET SUMMARY")
print("=" * 80)

print(f"\n{'Asset':<10s} {'Target w=2000':>15s} {'Target w=500':>15s} {'Direct SPY':>15s} {'Finetune':>15s} {'Best Blend':>15s} {'Winner':>20s}")
print("-" * 105)

transfer_wins = 0
transfer_total = 0

for asset_name in TARGET_ASSETS:
    if asset_name not in results:
        continue
    qlikes = results[asset_name]["qlikes"]
    target_full = qlikes.get(f"Target-only (w={WINDOW_FULL})", np.nan)
    target_small = qlikes.get(f"Target-only (w={WINDOW_SMALL})", np.nan)
    direct = qlikes.get("Direct transfer (SPY)", np.nan)
    finetune = qlikes.get(f"Fine-tuned (SPY→w={WINDOW_SMALL})", np.nan)

    # Best blend
    best_blend_ql = np.inf
    best_blend_name = ""
    for k, v in qlikes.items():
        if "Blend" in k and v is not None and v < best_blend_ql:
            best_blend_ql = v
            best_blend_name = k
    if np.isinf(best_blend_ql):
        best_blend_ql = np.nan

    winner = results[asset_name]["best_approach"] or "N/A"
    # Truncate winner name
    if len(winner) > 20:
        winner = winner[:17] + "..."

    def fmt(x):
        return f"{x:15.4f}" if np.isfinite(x) else f"{'N/A':>15s}"

    print(f"{asset_name:<10s} {fmt(target_full)} {fmt(target_small)} {fmt(direct)} {fmt(finetune)} {fmt(best_blend_ql)} {winner:>20s}")

    # Count transfer wins
    transfer_total += 1
    if results[asset_name]["best_approach"] is not None:
        best = results[asset_name]["best_approach"]
        if "transfer" in best.lower() or "fine" in best.lower() or "blend" in best.lower() or "direct" in best.lower():
            transfer_wins += 1


# ============================================================
# KEY INSIGHT: Does transfer help for w=500 specifically?
# ============================================================
print("\n\n" + "=" * 80)
print("KEY COMPARISON: Fine-tuned Transfer vs Target-only (w=500)")
print("(Simulates: 'I only have 500 days of target data. Does SPY help?')")
print("=" * 80)

print(f"\n{'Asset':<10s} {'Target w=500':>15s} {'Finetune w=500':>15s} {'Δ QLIKE':>12s} {'DM t':>10s} {'DM p':>10s} {'Verdict':>12s}")
print("-" * 85)

finetune_vs_small_wins = 0
finetune_vs_small_total = 0

for asset_name in TARGET_ASSETS:
    if asset_name not in results:
        continue
    qlikes = results[asset_name]["qlikes"]
    target_small = qlikes.get(f"Target-only (w={WINDOW_SMALL})", np.nan)
    finetune = qlikes.get(f"Fine-tuned (SPY→w={WINDOW_SMALL})", np.nan)

    if np.isnan(target_small) or np.isnan(finetune):
        continue

    delta = finetune - target_small
    finetune_vs_small_total += 1

    # DM test
    dm_info = results[asset_name].get("dm_tests", {}).get(f"Fine-tuned (SPY→w={WINDOW_SMALL})", {})
    t_stat = dm_info.get("t_stat", np.nan)
    p_val = dm_info.get("p_value", np.nan)

    verdict = "TRANSFER BETTER" if delta < 0 else "TARGET BETTER"
    if delta < 0:
        finetune_vs_small_wins += 1

    print(f"{asset_name:<10s} {target_small:15.4f} {finetune:15.4f} {delta:12.4f} {t_stat:10.3f} {p_val:10.4f} {verdict:>12s}")


# ============================================================
# FINAL VERDICT
# ============================================================
print("\n\n" + "=" * 80)
print("FINAL VERDICT")
print("=" * 80)

print(f"\n  Transfer approach wins vs target-only (w=2000): {transfer_wins}/{transfer_total}")
print(f"  Fine-tuned vs target-only (w=500):              {finetune_vs_small_wins}/{finetune_vs_small_total}")

if transfer_wins == 0:
    verdict = "NEGATIVE"
    explanation = "SPY GARCH params do NOT transfer to other assets. Each asset's own dynamics dominate."
elif transfer_wins == transfer_total:
    verdict = "POSITIVE"
    explanation = "SPY GARCH params consistently improve predictions for other assets!"
else:
    verdict = "MIXED"
    explanation = f"Transfer helps some assets ({transfer_wins}/{transfer_total}) but not universally."

print(f"\n  Overall verdict: {verdict}")
print(f"  {explanation}")

print(f"\n  Interpretation:")
print(f"  - Direct transfer (no refit) tests if SPY's EXACT parameters work on other assets")
print(f"  - Fine-tuned tests if SPY params are good STARTING POINTS for optimization")
print(f"  - Blending tests if mixing transfer + target forecasts helps")
print(f"  - If ALL fail, it means vol dynamics are fundamentally asset-specific")
print(f"  - If fine-tune/blend help for w=500 only, it means SPY provides useful priors")
print(f"    when target data is limited (short history)")


# ============================================================
# SAVE RESULTS
# ============================================================
output_path = PROJECT_ROOT / "experiments" / "k355_transfer_learning_results.json"
output = {
    "experiment": "K355",
    "title": "Transfer Learning for Volatility",
    "source_asset": SOURCE_ASSET,
    "target_assets": list(TARGET_ASSETS.keys()),
    "oos_period": f"{OOS_START} to {OOS_END}",
    "window_full": WINDOW_FULL,
    "window_small": WINDOW_SMALL,
    "spy_params": {k: float(v) for k, v in spy_params.items()},
    "results": {},
    "verdict": verdict,
    "explanation": explanation,
    "transfer_wins_vs_full": f"{transfer_wins}/{transfer_total}",
    "finetune_wins_vs_small": f"{finetune_vs_small_wins}/{finetune_vs_small_total}",
}

for asset_name, res_dict in results.items():
    # Convert numpy types for JSON serialization
    clean = {}
    for k, v in res_dict.items():
        if isinstance(v, dict):
            clean[k] = {}
            for k2, v2 in v.items():
                if isinstance(v2, dict):
                    clean[k][k2] = {k3: float(v3) if isinstance(v3, (np.floating, float)) and np.isfinite(v3) else str(v3) for k3, v3 in v2.items()}
                elif isinstance(v2, (np.floating, float)):
                    clean[k][k2] = float(v2) if np.isfinite(v2) else None
                else:
                    clean[k][k2] = v2
        elif isinstance(v, (np.floating, float)):
            clean[k] = float(v) if np.isfinite(v) else None
        else:
            clean[k] = v
    output["results"][asset_name] = clean

with open(output_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to: {output_path}")
print("\n" + "=" * 80)
print("K355 COMPLETE")
print("=" * 80)
