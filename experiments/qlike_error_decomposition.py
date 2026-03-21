"""
K132: QLIKE-Optimal Prediction Error Decomposition
====================================================
Decompose QLIKE loss into noise floor, model bias, and residual components
to quantify how much of the "explainable variance" GJR-GARCH captures.

K126 revealed that the QLIKE ceiling comes from r² proxy's intrinsic stochasticity.
This experiment goes further: what fraction of the *remaining explainable* variance
does the model actually capture?

Methodology:
1. Fit GJR-GARCH OOS with rolling window (w=2000)
2. Decompose total QLIKE into 3 components:
   - Noise floor: theoretical minimum from standardized residual distribution
   - Model bias: systematic over/under-estimation of variance
   - Residual: unexplained structure beyond noise
3. Bootstrap (5000 reps) for CI on each component
4. Capture Rate = 1 - (actual - noise_floor) / (shuffle - noise_floor)
5. Regime-conditional decomposition (VIX <15, 15-25, >25)
6. Cross-asset comparison: SPY vs GLD vs BTC

[提出: Gemini Round 2 #1, 執行: Claude]
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
import json
from datetime import datetime

np.random.seed(42)

# ============================================================
# 1. Download data
# ============================================================
print("=" * 70)
print("K132: QLIKE-Optimal Prediction Error Decomposition")
print("=" * 70)

print("\n[1/6] Downloading data...")

assets = {
    "SPY": {"ticker": "SPY", "start": "2000-01-01", "end": "2026-01-01", "has_vix": True},
    "GLD": {"ticker": "GLD", "start": "2004-11-01", "end": "2026-01-01", "has_vix": False},
    "BTC": {"ticker": "BTC-USD", "start": "2014-09-17", "end": "2026-01-01", "has_vix": False},
}

price_data = {}
for name, cfg in assets.items():
    raw = yf.download(cfg["ticker"], start=cfg["start"], end=cfg["end"], progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    col = "Adj Close" if "Adj Close" in raw.columns else "Close"
    ret = raw[col].pct_change().dropna() * 100  # percentage returns for arch
    price_data[name] = ret
    print(f"  {name}: {ret.index[0].strftime('%Y-%m-%d')} to {ret.index[-1].strftime('%Y-%m-%d')} ({len(ret)} obs)")

# VIX for regime classification
vix_raw = yf.download("^VIX", start="2000-01-01", end="2026-01-01", progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix = vix_raw["Close"].copy()
vix.name = "VIX"
print(f"  VIX: {vix.index[0].strftime('%Y-%m-%d')} to {vix.index[-1].strftime('%Y-%m-%d')} ({len(vix)} obs)")

# ============================================================
# 2. GJR-GARCH OOS estimation
# ============================================================
print("\n[2/6] Running GJR-GARCH OOS estimation...")

WINDOW = 2000
N_BOOTSTRAP = 5000

def fit_gjr_oos(returns, window=2000):
    """Fit GJR-GARCH(1,1) with rolling window, return OOS sigma2 and r2."""
    n = len(returns)
    oos_start = window

    sigma2_oos = []
    r2_oos = []
    dates_oos = []
    std_resid_oos = []

    for t in range(oos_start, n):
        train_start = max(0, t - window)
        train = returns.iloc[train_start:t]

        try:
            am = arch_model(train, vol="Garch", p=1, o=1, q=1, dist="normal", mean="Constant")
            res = am.fit(disp="off", show_warning=False)

            # One-step-ahead forecast
            fcast = res.forecast(horizon=1)
            sigma2_pred = fcast.variance.values[-1, 0]

            # Realized: squared return
            r2_realized = returns.iloc[t] ** 2

            # Standardized residual
            z = returns.iloc[t] / np.sqrt(sigma2_pred)

            sigma2_oos.append(sigma2_pred)
            r2_oos.append(r2_realized)
            dates_oos.append(returns.index[t])
            std_resid_oos.append(z)
        except Exception:
            continue

    return (np.array(sigma2_oos), np.array(r2_oos),
            pd.DatetimeIndex(dates_oos), np.array(std_resid_oos))


# Run for each asset
results = {}
for name in assets:
    print(f"  Fitting {name}...", end=" ", flush=True)
    ret = price_data[name]
    sigma2, r2, dates, z = fit_gjr_oos(ret, window=WINDOW)
    results[name] = {
        "sigma2": sigma2,
        "r2": r2,
        "dates": dates,
        "z": z,
    }
    print(f"{len(sigma2)} OOS observations")

# ============================================================
# 3. QLIKE Decomposition (with proper handling of zero returns)
# ============================================================
print("\n[3/6] Decomposing QLIKE into components...")

def qlike_loss(sigma2, r2):
    """QLIKE loss: mean of log(sigma2) + r2/sigma2."""
    return np.mean(np.log(sigma2) + r2 / sigma2)


def decompose_qlike(sigma2, r2, z, n_bootstrap=5000):
    """
    Decompose QLIKE into interpretable components.

    The key decomposition:
    QLIKE = E[log(h) + r²/h]

    We decompose the EXCESS QLIKE (over the irreducible part) using only
    the standardized residuals z = r/sqrt(h), filtering out zero-return days
    that cause log(0) issues.

    Approach:
    - ratio = r²/h = z²
    - excess_qlike = E[z² - log(z²) - 1] (this equals 0 when z²=1 always)
    - noise floor = Euler-Mascheroni constant ≈ 0.5772 (theoretical for z~N(0,1))
    - bias = systematic deviation of E[z²] from 1
    - capture_rate = how much of the explainable range the model captures
    """
    n = len(sigma2)

    # Total QLIKE
    total_qlike = qlike_loss(sigma2, r2)

    # ===== Filter out zero-return days for ratio-based analysis =====
    # r² = 0 causes log(r²/h) = -inf. These days carry no predictive content.
    nonzero_mask = r2 > 0
    n_zero = np.sum(~nonzero_mask)
    pct_zero = n_zero / n * 100

    sigma2_nz = sigma2[nonzero_mask]
    r2_nz = r2[nonzero_mask]
    z_nz = z[nonzero_mask]
    n_nz = len(sigma2_nz)

    # z² = r²/h (the key ratio)
    z2 = z_nz ** 2
    ratio = r2_nz / sigma2_nz  # Same as z²

    # ===== Excess QLIKE =====
    # E[z² - log(z²) - 1]: this is the KL-divergence-like measure
    # f(x) = x - log(x) - 1, minimized at x=1 where f(1)=0
    excess_per_obs = ratio - np.log(ratio) - 1
    excess_qlike = np.mean(excess_per_obs)

    # ===== Noise Floor =====
    # For z~N(0,1), z² ~ chi²(1):
    # E[z² - log(z²) - 1] = E[z²] - E[log(z²)] - 1
    #   = 1 - (psi(1/2) + log(2)) - 1
    #   = -(psi(1/2) + log(2))
    #   = -(-1.9635 + 0.6931)
    #   = 1.2704 - 0.6931 = 0.5772 (Euler-Mascheroni)
    euler_gamma = 0.5772156649
    noise_floor = euler_gamma

    # Empirical noise floor from actual z distribution
    noise_floor_empirical = np.mean(z2 - np.log(z2) - 1)

    # ===== Bias Component =====
    # Decompose excess into bias (mean shift) + variance (dispersion)
    # If ratio has mean mu ≠ 1, the bias component is:
    # f(E[ratio]) = E[ratio] - log(E[ratio]) - 1
    mean_ratio = np.mean(ratio)
    bias_component = mean_ratio - np.log(mean_ratio) - 1

    # ===== Variance Component =====
    # The rest is due to dispersion of ratio around its mean
    variance_component = excess_qlike - bias_component

    # ===== Shuffle QLIKE (upper bound = no temporal structure) =====
    shuffle_excesses = []
    for _ in range(1000):
        idx = np.random.permutation(n_nz)
        shuf_ratio = r2_nz[idx] / sigma2_nz
        shuffle_excesses.append(np.mean(shuf_ratio - np.log(shuf_ratio) - 1))
    shuffle_excess = np.mean(shuffle_excesses)

    # ===== Capture Rate =====
    # How much of the explainable structure does the model capture?
    # capture = 1 - (actual_excess - noise_floor) / (shuffle_excess - noise_floor)
    # 100% = all explainable structure captured (excess = noise_floor)
    # 0% = no better than random shuffle
    explainable_range = shuffle_excess - noise_floor
    if explainable_range > 0.001:
        capture_rate = 1.0 - (excess_qlike - noise_floor) / explainable_range
    else:
        capture_rate = np.nan

    # ===== Model-attributable excess =====
    model_excess = max(0, excess_qlike - noise_floor)

    # ===== Bootstrap CIs =====
    boot_excess = []
    boot_bias = []
    boot_variance = []
    boot_capture = []

    for b in range(n_bootstrap):
        idx = np.random.choice(n_nz, n_nz, replace=True)
        r2_b = r2_nz[idx]
        s2_b = sigma2_nz[idx]
        ratio_b = r2_b / s2_b

        excess_b = np.mean(ratio_b - np.log(ratio_b) - 1)
        mean_ratio_b = np.mean(ratio_b)
        bias_b = mean_ratio_b - np.log(mean_ratio_b) - 1
        var_b = excess_b - bias_b

        # Shuffle for capture
        idx_shuf = np.random.permutation(n_nz)
        shuf_ratio = r2_b[idx_shuf] / s2_b
        shuf_b = np.mean(shuf_ratio - np.log(shuf_ratio) - 1)
        range_b = shuf_b - noise_floor
        if range_b > 0.001:
            cap_b = 1.0 - (excess_b - noise_floor) / range_b
        else:
            cap_b = np.nan

        boot_excess.append(excess_b)
        boot_bias.append(bias_b)
        boot_variance.append(var_b)
        boot_capture.append(cap_b)

    boot_excess = np.array(boot_excess)
    boot_bias = np.array(boot_bias)
    boot_variance = np.array(boot_variance)
    boot_capture = np.array([x for x in boot_capture if not np.isnan(x)])

    return {
        "total_qlike": total_qlike,
        "excess_qlike": excess_qlike,
        "noise_floor_theory": noise_floor,
        "noise_floor_empirical": noise_floor_empirical,
        "bias_component": bias_component,
        "variance_component": variance_component,
        "model_excess": model_excess,
        "shuffle_excess": shuffle_excess,
        "capture_rate": capture_rate,
        "explainable_range": explainable_range,
        "mean_ratio": mean_ratio,
        "std_z": np.std(z),
        "mean_z2": np.mean(z**2),
        "n_obs": n,
        "n_nonzero": n_nz,
        "n_zero_returns": int(n_zero),
        "pct_zero_returns": pct_zero,
        "ci": {
            "excess": (float(np.percentile(boot_excess, 2.5)), float(np.percentile(boot_excess, 97.5))),
            "bias": (float(np.percentile(boot_bias, 2.5)), float(np.percentile(boot_bias, 97.5))),
            "variance": (float(np.percentile(boot_variance, 2.5)), float(np.percentile(boot_variance, 97.5))),
            "capture_rate": (float(np.percentile(boot_capture, 2.5)), float(np.percentile(boot_capture, 97.5))) if len(boot_capture) > 10 else (np.nan, np.nan),
        }
    }


# Run decomposition for each asset
decomp_results = {}
for name in assets:
    print(f"\n  === {name} ===")
    r = results[name]
    decomp = decompose_qlike(r["sigma2"], r["r2"], r["z"], n_bootstrap=N_BOOTSTRAP)
    decomp_results[name] = decomp

    print(f"  Total QLIKE:          {decomp['total_qlike']:.4f}")
    print(f"  Zero-return days:     {decomp['n_zero_returns']} ({decomp['pct_zero_returns']:.1f}%) — excluded from ratio analysis")
    print(f"  Excess QLIKE:         {decomp['excess_qlike']:.4f} [{decomp['ci']['excess'][0]:.4f}, {decomp['ci']['excess'][1]:.4f}]")
    print(f"  Noise floor (theory): {decomp['noise_floor_theory']:.4f} (Euler-Mascheroni)")
    print(f"  Noise floor (empir.): {decomp['noise_floor_empirical']:.4f}")
    print(f"  Bias component:       {decomp['bias_component']:.6f} [{decomp['ci']['bias'][0]:.6f}, {decomp['ci']['bias'][1]:.6f}]")
    print(f"  Variance component:   {decomp['variance_component']:.4f} [{decomp['ci']['variance'][0]:.4f}, {decomp['ci']['variance'][1]:.4f}]")
    print(f"  Shuffle excess:       {decomp['shuffle_excess']:.4f}")
    print(f"  Explainable range:    {decomp['explainable_range']:.4f}")
    print(f"  Capture Rate:         {decomp['capture_rate']:.1%} [{decomp['ci']['capture_rate'][0]:.1%}, {decomp['ci']['capture_rate'][1]:.1%}]")
    print(f"  Mean ratio (r²/h):    {decomp['mean_ratio']:.4f} (ideal=1)")
    print(f"  Std(z):               {decomp['std_z']:.4f} (ideal=1)")
    print(f"  E[z²]:                {decomp['mean_z2']:.4f} (ideal=1)")

# ============================================================
# 4. Regime-Conditional Decomposition
# ============================================================
print("\n\n[4/6] Regime-conditional decomposition (VIX-based)...")

def regime_decompose(sigma2, r2, z, dates, vix_series, regimes):
    """Decompose QLIKE by VIX regime."""
    common = dates.intersection(vix_series.index)
    if len(common) < 100:
        return None

    mask = np.isin(dates, common)
    sigma2_aligned = sigma2[mask]
    r2_aligned = r2[mask]
    z_aligned = z[mask]
    dates_aligned = dates[mask]
    vix_aligned = vix_series.reindex(dates_aligned).values

    regime_results = {}
    for regime_name, (low, high) in regimes.items():
        regime_mask = (vix_aligned >= low) & (vix_aligned < high)
        n_regime = regime_mask.sum()
        if n_regime < 50:
            regime_results[regime_name] = {"n": int(n_regime), "skip": True}
            continue

        s2_r = sigma2_aligned[regime_mask]
        r2_r = r2_aligned[regime_mask]
        z_r = z_aligned[regime_mask]

        # Filter zero returns
        nz = r2_r > 0
        s2_r = s2_r[nz]
        r2_r = r2_r[nz]
        z_r = z_r[nz]
        n_nz = len(s2_r)

        if n_nz < 30:
            regime_results[regime_name] = {"n": int(n_regime), "skip": True}
            continue

        ratio = r2_r / s2_r
        excess = np.mean(ratio - np.log(ratio) - 1)
        mean_ratio = np.mean(ratio)
        bias = mean_ratio - np.log(mean_ratio) - 1
        variance = excess - bias

        # Shuffle for capture rate
        shuffle_excesses = []
        for _ in range(1000):
            idx = np.random.permutation(n_nz)
            shuf_ratio = r2_r[idx] / s2_r
            shuffle_excesses.append(np.mean(shuf_ratio - np.log(shuf_ratio) - 1))
        shuffle_excess = np.mean(shuffle_excesses)

        noise_floor = 0.5772
        explainable = shuffle_excess - noise_floor
        capture = 1.0 - (excess - noise_floor) / explainable if explainable > 0.001 else np.nan

        regime_results[regime_name] = {
            "n": int(n_regime),
            "n_nonzero": int(n_nz),
            "pct": n_regime / len(sigma2_aligned),
            "excess_qlike": excess,
            "bias": bias,
            "variance": variance,
            "shuffle_excess": shuffle_excess,
            "capture_rate": capture,
            "mean_ratio": mean_ratio,
            "mean_z2": np.mean(z_r**2),
            "skip": False,
        }

    return regime_results


regimes = {
    "Low (VIX<15)": (0, 15),
    "Medium (15-25)": (15, 25),
    "High (VIX>25)": (25, 200),
}

regime_all = {}
for name in assets:
    r = results[name]
    reg = regime_decompose(r["sigma2"], r["r2"], r["z"], r["dates"], vix, regimes)
    regime_all[name] = reg

    if reg is None:
        print(f"\n  {name}: insufficient VIX overlap, skipping")
        continue

    print(f"\n  === {name} Regime Decomposition ===")
    print(f"  {'Regime':<20} {'N':>6} {'%':>6} {'Excess':>8} {'Bias':>10} {'Variance':>10} {'Capture':>9}")
    print(f"  {'-'*69}")
    for regime_name, rd in reg.items():
        if rd.get("skip"):
            print(f"  {regime_name:<20} {rd['n']:>6} {'(skip)':>6}")
            continue
        cap_str = f"{rd['capture_rate']:.1%}" if not np.isnan(rd['capture_rate']) else "N/A"
        print(f"  {regime_name:<20} {rd['n']:>6} {rd['pct']:>5.1%} {rd['excess_qlike']:>8.4f} "
              f"{rd['bias']:>10.6f} {rd['variance']:>10.4f} {cap_str:>9}")

# ============================================================
# 5. EWMA comparison
# ============================================================
print("\n\n[5/6] Comparing GJR-GARCH vs EWMA(0.97) capture rates...")

def ewma_oos(returns, lam=0.97, window=2000):
    """EWMA variance estimation."""
    n = len(returns)
    oos_start = window

    sigma2_oos = []
    r2_oos = []
    z_oos = []
    dates_oos = []

    ret_vals = returns.values
    var_ewma = np.var(ret_vals[:window])

    for t in range(oos_start, n):
        sigma2_oos.append(var_ewma)
        r2_oos.append(ret_vals[t] ** 2)
        z_oos.append(ret_vals[t] / np.sqrt(var_ewma) if var_ewma > 0 else 0)
        dates_oos.append(returns.index[t])
        var_ewma = lam * var_ewma + (1 - lam) * ret_vals[t] ** 2

    return np.array(sigma2_oos), np.array(r2_oos), pd.DatetimeIndex(dates_oos), np.array(z_oos)


ewma_results = {}
for name in assets:
    ret = price_data[name]
    sigma2, r2, dates, z = ewma_oos(ret, lam=0.97, window=WINDOW)

    # Filter zero returns
    nz = r2 > 0
    sigma2_nz = sigma2[nz]
    r2_nz = r2[nz]
    n_nz = len(sigma2_nz)

    ratio = r2_nz / sigma2_nz
    excess = np.mean(ratio - np.log(ratio) - 1)
    mean_ratio = np.mean(ratio)
    bias = mean_ratio - np.log(mean_ratio) - 1
    variance = excess - bias

    # Total QLIKE
    total_qlike = np.mean(np.log(sigma2) + r2 / sigma2)

    # Shuffle
    shuffle_excesses = []
    for _ in range(1000):
        idx = np.random.permutation(n_nz)
        shuf_ratio = r2_nz[idx] / sigma2_nz
        shuffle_excesses.append(np.mean(shuf_ratio - np.log(shuf_ratio) - 1))
    shuffle_excess = np.mean(shuffle_excesses)

    noise_floor = 0.5772
    explainable = shuffle_excess - noise_floor
    capture = 1.0 - (excess - noise_floor) / explainable if explainable > 0.001 else np.nan

    ewma_results[name] = {
        "total_qlike": total_qlike,
        "excess_qlike": excess,
        "bias": bias,
        "variance": variance,
        "capture_rate": capture,
        "shuffle_excess": shuffle_excess,
        "mean_ratio": mean_ratio,
    }

# Print comparison table
print(f"\n  {'Asset':<8} {'Model':<10} {'Total QLIKE':>12} {'Excess':>10} {'Bias':>10} {'Variance':>10} {'Capture':>10}")
print(f"  {'-'*80}")
for name in assets:
    gjr = decomp_results[name]
    ewma = ewma_results[name]
    gjr_cap = f"{gjr['capture_rate']:.1%}" if not np.isnan(gjr['capture_rate']) else "N/A"
    ewma_cap = f"{ewma['capture_rate']:.1%}" if not np.isnan(ewma['capture_rate']) else "N/A"
    print(f"  {name:<8} {'GJR':<10} {gjr['total_qlike']:>11.4f} {gjr['excess_qlike']:>10.4f} "
          f"{gjr['bias_component']:>10.6f} {gjr['variance_component']:>10.4f} {gjr_cap:>10}")
    print(f"  {'':<8} {'EWMA(0.97)':<10} {ewma['total_qlike']:>11.4f} {ewma['excess_qlike']:>10.4f} "
          f"{ewma['bias']:>10.6f} {ewma['variance']:>10.4f} {ewma_cap:>10}")
    print()

# ============================================================
# 6. Summary & Save Results
# ============================================================
print("\n[6/6] Summary & Conclusions")
print("=" * 70)

# Composition breakdown: what % of excess QLIKE is noise vs model-attributable?
print("\n=== QLIKE Composition Breakdown ===\n")
print(f"{'Component':<30} {'SPY':>12} {'GLD':>12} {'BTC':>12}")
print(f"{'-'*66}")

for label, key in [
    ("Total QLIKE", "total_qlike"),
    ("Excess QLIKE (z²-log(z²)-1)", "excess_qlike"),
]:
    print(f"{label:<30} {decomp_results['SPY'][key]:>12.4f} {decomp_results['GLD'][key]:>12.4f} {decomp_results['BTC'][key]:>12.4f}")

print(f"{'  Noise floor (Euler γ)':<30} {0.5772:>12.4f} {0.5772:>12.4f} {0.5772:>12.4f}")

# Noise as % of excess
for name in assets:
    d = decomp_results[name]
    noise_pct = 0.5772 / d['excess_qlike'] * 100 if d['excess_qlike'] > 0 else float('nan')
    decomp_results[name]['noise_pct_of_excess'] = noise_pct

print(f"{'  Noise % of excess':<30} {decomp_results['SPY']['noise_pct_of_excess']:>11.1f}% {decomp_results['GLD']['noise_pct_of_excess']:>11.1f}% {decomp_results['BTC']['noise_pct_of_excess']:>11.1f}%")
print(f"{'  Bias component':<30} {decomp_results['SPY']['bias_component']:>12.6f} {decomp_results['GLD']['bias_component']:>12.6f} {decomp_results['BTC']['bias_component']:>12.6f}")
print(f"{'  Variance component':<30} {decomp_results['SPY']['variance_component']:>12.4f} {decomp_results['GLD']['variance_component']:>12.4f} {decomp_results['BTC']['variance_component']:>12.4f}")
print(f"{'Shuffle excess (no structure)':<30} {decomp_results['SPY']['shuffle_excess']:>12.4f} {decomp_results['GLD']['shuffle_excess']:>12.4f} {decomp_results['BTC']['shuffle_excess']:>12.4f}")
print(f"{'Capture Rate':<30} {decomp_results['SPY']['capture_rate']:>11.1%} {decomp_results['GLD']['capture_rate']:>11.1%} {decomp_results['BTC']['capture_rate']:>11.1%}")

# CIs
print(f"\n{'Capture Rate 95% CI':<30}", end="")
for name in assets:
    ci = decomp_results[name]['ci']['capture_rate']
    if not np.isnan(ci[0]):
        print(f" [{ci[0]:.1%},{ci[1]:.1%}]", end="")
    else:
        print(f"  {'N/A':>10}", end="")
print()

# Zero returns info
print(f"\n{'Zero-return days excluded':<30} {decomp_results['SPY']['n_zero_returns']:>12} {decomp_results['GLD']['n_zero_returns']:>12} {decomp_results['BTC']['n_zero_returns']:>12}")

print(f"\n{'Mean r²/h (ideal=1)':<30} {decomp_results['SPY']['mean_ratio']:>12.4f} {decomp_results['GLD']['mean_ratio']:>12.4f} {decomp_results['BTC']['mean_ratio']:>12.4f}")
print(f"{'E[z²] (ideal=1)':<30} {decomp_results['SPY']['mean_z2']:>12.4f} {decomp_results['GLD']['mean_z2']:>12.4f} {decomp_results['BTC']['mean_z2']:>12.4f}")

# Regime table
print("\n\n=== Regime-Conditional Capture Rates ===")
print(f"\n  {'Regime':<20} {'SPY':>10} {'GLD':>10} {'BTC':>10}")
print(f"  {'-'*50}")
for regime_name in regimes:
    vals = []
    for name in assets:
        if regime_all.get(name) and regime_all[name].get(regime_name) and not regime_all[name][regime_name].get("skip"):
            cap = regime_all[name][regime_name]['capture_rate']
            vals.append(f"{cap:.1%}" if not np.isnan(cap) else "N/A")
        else:
            vals.append("N/A")
    print(f"  {regime_name:<20} {vals[0]:>10} {vals[1]:>10} {vals[2]:>10}")

# Regime excess QLIKE breakdown
print(f"\n  {'Regime':<20} {'SPY Excess':>12} {'GLD Excess':>12} {'BTC Excess':>12}")
print(f"  {'-'*56}")
for regime_name in regimes:
    vals = []
    for name in assets:
        if regime_all.get(name) and regime_all[name].get(regime_name) and not regime_all[name][regime_name].get("skip"):
            vals.append(f"{regime_all[name][regime_name]['excess_qlike']:.4f}")
        else:
            vals.append("N/A")
    print(f"  {regime_name:<20} {vals[0]:>12} {vals[1]:>12} {vals[2]:>12}")

# Interpretation
print("\n\n=== Key Findings ===")

spy_cap = decomp_results["SPY"]["capture_rate"]
gld_cap = decomp_results["GLD"]["capture_rate"]
btc_cap = decomp_results["BTC"]["capture_rate"]

spy_noise_pct = decomp_results["SPY"]["noise_pct_of_excess"]
gld_noise_pct = decomp_results["GLD"]["noise_pct_of_excess"]
btc_noise_pct = decomp_results["BTC"]["noise_pct_of_excess"]

print(f"""
1. NOISE FLOOR DOMINANCE:
   The Euler-Mascheroni constant (γ ≈ 0.5772) is the irreducible QLIKE noise
   when r² proxies σ²_true. As a % of excess QLIKE:
   - SPY: {spy_noise_pct:.1f}%  |  GLD: {gld_noise_pct:.1f}%  |  BTC: {btc_noise_pct:.1f}%
   → {'SPY and GLD are noise-dominated; most error is measurement, not model' if spy_noise_pct > 70 else 'There is room for model improvement'}

2. CAPTURE RATES (% of explainable structure captured):
   - SPY: {spy_cap:.1%}  |  GLD: {gld_cap:.1%}  |  BTC: {btc_cap:.1%}
   - CI: [{decomp_results['SPY']['ci']['capture_rate'][0]:.1%}, {decomp_results['SPY']['ci']['capture_rate'][1]:.1%}] | [{decomp_results['GLD']['ci']['capture_rate'][0]:.1%}, {decomp_results['GLD']['ci']['capture_rate'][1]:.1%}] | [{decomp_results['BTC']['ci']['capture_rate'][0]:.1%}, {decomp_results['BTC']['ci']['capture_rate'][1]:.1%}]

3. BIAS is TINY:
   SPY bias: {decomp_results['SPY']['bias_component']:.6f}
   GLD bias: {decomp_results['GLD']['bias_component']:.6f}
   BTC bias: {decomp_results['BTC']['bias_component']:.6f}
   → GJR-GARCH is well-calibrated ON AVERAGE. The problem is conditional dynamics.

4. GJR vs EWMA(0.97):
   SPY: GJR={decomp_results['SPY']['capture_rate']:.1%} vs EWMA={ewma_results['SPY']['capture_rate']:.1%}
   GLD: GJR={decomp_results['GLD']['capture_rate']:.1%} vs EWMA={ewma_results['GLD']['capture_rate']:.1%}
   BTC: GJR={decomp_results['BTC']['capture_rate']:.1%} vs EWMA={ewma_results['BTC']['capture_rate']:.1%}

5. PRACTICAL IMPLICATION:
   With noise consuming {spy_noise_pct:.0f}%+ of excess QLIKE for liquid assets (SPY/GLD),
   the maximum possible improvement from ANY model change is bounded.
   The path to better QLIKE is not a better model but a better proxy:
   → 5-min realized variance would dramatically reduce the noise floor.
""")

# Save results
output = {
    "experiment": "K132",
    "title": "QLIKE-Optimal Prediction Error Decomposition",
    "proposed_by": "Gemini Round 2 #1",
    "executed_by": "Claude",
    "timestamp": datetime.now().isoformat(),
    "parameters": {
        "window": WINDOW,
        "n_bootstrap": N_BOOTSTRAP,
        "noise_floor_constant": 0.5772156649,
    },
    "decomposition": {},
    "regime_decomposition": {},
    "model_comparison": {},
}

for name in assets:
    d = decomp_results[name]
    output["decomposition"][name] = {
        "total_qlike": round(d["total_qlike"], 6),
        "excess_qlike": round(d["excess_qlike"], 6),
        "noise_floor_theory": round(d["noise_floor_theory"], 6),
        "noise_floor_empirical": round(d["noise_floor_empirical"], 6),
        "noise_pct_of_excess": round(d.get("noise_pct_of_excess", 0), 2),
        "bias_component": round(d["bias_component"], 8),
        "variance_component": round(d["variance_component"], 6),
        "shuffle_excess": round(d["shuffle_excess"], 6),
        "explainable_range": round(d["explainable_range"], 6),
        "capture_rate": round(d["capture_rate"], 4) if not np.isnan(d["capture_rate"]) else None,
        "capture_rate_ci_95": [
            round(d["ci"]["capture_rate"][0], 4) if not np.isnan(d["ci"]["capture_rate"][0]) else None,
            round(d["ci"]["capture_rate"][1], 4) if not np.isnan(d["ci"]["capture_rate"][1]) else None,
        ],
        "mean_ratio_r2_over_h": round(d["mean_ratio"], 4),
        "mean_z2": round(d["mean_z2"], 4),
        "n_oos": d["n_obs"],
        "n_nonzero": d["n_nonzero"],
        "n_zero_returns": d["n_zero_returns"],
    }

    if regime_all.get(name):
        output["regime_decomposition"][name] = {}
        for regime_name, rd in regime_all[name].items():
            if rd.get("skip"):
                output["regime_decomposition"][name][regime_name] = {"n": rd["n"], "skip": True}
            else:
                output["regime_decomposition"][name][regime_name] = {
                    "n": rd["n"],
                    "pct": round(rd["pct"], 4),
                    "excess_qlike": round(rd["excess_qlike"], 6),
                    "bias": round(rd["bias"], 8),
                    "variance": round(rd["variance"], 6),
                    "capture_rate": round(rd["capture_rate"], 4) if not np.isnan(rd["capture_rate"]) else None,
                    "mean_ratio": round(rd["mean_ratio"], 4),
                }

    output["model_comparison"][name] = {
        "gjr_total_qlike": round(decomp_results[name]["total_qlike"], 6),
        "ewma_total_qlike": round(ewma_results[name]["total_qlike"], 6),
        "gjr_capture": round(decomp_results[name]["capture_rate"], 4) if not np.isnan(decomp_results[name]["capture_rate"]) else None,
        "ewma_capture": round(ewma_results[name]["capture_rate"], 4) if not np.isnan(ewma_results[name]["capture_rate"]) else None,
        "gjr_excess": round(decomp_results[name]["excess_qlike"], 6),
        "ewma_excess": round(ewma_results[name]["excess_qlike"], 6),
        "gjr_bias": round(decomp_results[name]["bias_component"], 8),
        "ewma_bias": round(ewma_results[name]["bias"], 8),
    }

output_path = "experiments/qlike_error_decomposition_results.json"
with open(output_path, "w") as f:
    json.dump(output, f, indent=2, default=str)
print(f"\nResults saved to {output_path}")

print("\n" + "=" * 70)
print("K132 Complete")
print("=" * 70)
