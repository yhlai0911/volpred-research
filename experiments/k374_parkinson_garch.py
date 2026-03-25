"""
K374: Parkinson-Targeted GJR-GARCH — Can We Break the Ceiling by Changing the Target?
=====================================================================================
Follow-up to K373 (Parkinson proxy R²=0.388, +31% vs r²) and K372 (48.7% noise floor).

QUESTION: If we FIT GARCH to predict Parkinson range instead of r², does QLIKE improve?

The insight: r² is a terrible proxy for daily variance (SNR ≈ 0.53 from K372).
Parkinson range = (H-L)²/(4·ln2) uses OHLC and has SNR=0.357 (K373).
If GARCH models target Parkinson directly, the loss function evaluation
uses a cleaner proxy → potentially lower QLIKE.

Methodology:
1. Standard:  GJR-GARCH(1,1) on returns → predict σ²_{t+1}. Evaluate QLIKE with r²_{t+1}.
2. Modified:  GJR-GARCH(1,1) on returns → predict σ²_{t+1}. Evaluate QLIKE with Parkinson_{t+1}.
3. Parkinson-fit: Fit model on Parkinson innovations → predict PK_{t+1}. Evaluate with PK_{t+1}.
4. Cross-target comparisons.
5. VIX-only OLS baselines for each target.
6. Combined: VIX + GARCH.
7. Rolling OOS (w=2000, 2015-2024). DM tests.

IMPORTANT: All predictors LAGGED (K362 lesson). No same-day information.

Data: SPY daily OHLC from yfinance, 2005-2024.

[提出: K373 follow-up, 執行: Claude]
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
# 1. Download SPY OHLC data
# ============================================================
print("=" * 70)
print("K374: Parkinson-Targeted GJR-GARCH")
print("     Can We Break the Ceiling by Changing the Target?")
print("=" * 70)

print("\n[1/7] Downloading SPY OHLC data...")

raw = yf.download("SPY", start="2003-01-01", end="2025-01-01", progress=False)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)

# Use Adj Close for returns, but H/L/O for Parkinson
col = "Adj Close" if "Adj Close" in raw.columns else "Close"
prices = raw[[col, "High", "Low", "Open"]].copy()
prices.columns = ["close", "high", "low", "open"]

# Returns in percentage (for arch library)
returns_pct = prices["close"].pct_change().dropna() * 100
# Returns in decimal (for r²)
returns_dec = prices["close"].pct_change().dropna()

# Parkinson estimator: PK = (ln(H/L))² / (4·ln2)
parkinson = (np.log(prices["high"] / prices["low"])) ** 2 / (4 * np.log(2))
parkinson = parkinson.reindex(returns_dec.index).dropna()

# Align all series
common_idx = returns_pct.index.intersection(parkinson.index)
returns_pct = returns_pct.loc[common_idx]
returns_dec = returns_dec.loc[common_idx]
parkinson = parkinson.loc[common_idx]
r_squared = returns_dec ** 2

# VIX for baseline
vix_raw = yf.download("^VIX", start="2003-01-01", end="2025-01-01", progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix = vix_raw["Close"].reindex(common_idx).ffill()

print(f"  SPY: {common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')} ({len(common_idx)} obs)")
print(f"  r² mean: {r_squared.mean():.6f}, Parkinson mean: {parkinson.mean():.6f}")
print(f"  Ratio PK/r²: {parkinson.mean() / r_squared.mean():.3f}")
print(f"  Corr(r², PK): {r_squared.corr(parkinson):.4f}")

# ============================================================
# 2. Helper functions
# ============================================================
def qlike(actual, predicted, eps=1e-10):
    """QLIKE loss: mean(log(predicted) + actual/predicted). Lower is better."""
    pred = np.maximum(predicted, eps)
    return np.mean(np.log(pred) + actual / pred)

def mse(actual, predicted):
    return np.mean((actual - predicted) ** 2)

def mincer_zarnowitz_r2(actual, predicted):
    """R² from regressing actual on predicted."""
    from numpy.polynomial import polynomial as P
    X = np.column_stack([np.ones(len(predicted)), predicted])
    beta = np.linalg.lstsq(X, actual, rcond=None)[0]
    fitted = X @ beta
    ss_res = np.sum((actual - fitted) ** 2)
    ss_tot = np.sum((actual - np.mean(actual)) ** 2)
    return 1 - ss_res / ss_tot

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. H0: equal predictive ability.
    Returns (t-stat, p-value). Negative t means loss1 < loss2 (model 1 better)."""
    d = loss1 - loss2
    n = len(d)
    d_mean = np.mean(d)
    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        var_d = gamma0 / n
    t_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * stats.t.cdf(-abs(t_stat), df=n - 1)
    return t_stat, p_value

# ============================================================
# 3. Rolling OOS GJR-GARCH estimation
# ============================================================
print("\n[2/7] Running GJR-GARCH rolling OOS (w=2000)...")

WINDOW = 2000
oos_start_idx = WINDOW  # First OOS observation

# We need enough data: returns_pct from index WINDOW onward is OOS
n_oos = len(returns_pct) - WINDOW
print(f"  Total obs: {len(returns_pct)}, Window: {WINDOW}, OOS: {n_oos}")
print(f"  OOS period: {returns_pct.index[WINDOW].strftime('%Y-%m-%d')} to {returns_pct.index[-1].strftime('%Y-%m-%d')}")

# Store OOS forecasts
garch_sigma2_oos = np.full(n_oos, np.nan)  # GARCH σ² forecast (from returns)
r2_oos = np.full(n_oos, np.nan)            # r² realized
pk_oos = np.full(n_oos, np.nan)            # Parkinson realized
vix_oos = np.full(n_oos, np.nan)           # VIX lagged

returns_arr = returns_pct.values
r2_arr = r_squared.values
pk_arr = parkinson.values
vix_arr = vix.values
dates_arr = returns_pct.index

n_fail = 0
for i in range(n_oos):
    t = WINDOW + i
    # Fit on [t-WINDOW : t], forecast t+1 (but we store at position i which corresponds to date t)
    # Actually: we fit on returns up to t-1, forecast for t.
    # The LAGGED forecast: use data up to t-1 to predict σ²_t
    train_ret = returns_arr[i:i + WINDOW]

    try:
        am = arch_model(train_ret, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Zero')
        res = am.fit(disp='off', show_warning=False)
        # One-step-ahead forecast
        fcast = res.forecast(horizon=1)
        garch_sigma2_oos[i] = fcast.variance.values[-1, 0] / 1e4  # Convert from pct² to decimal²
    except Exception:
        n_fail += 1
        if i > 0:
            garch_sigma2_oos[i] = garch_sigma2_oos[i - 1]
        else:
            garch_sigma2_oos[i] = np.var(train_ret) / 1e4

    # Realized values at time t (the day we're forecasting)
    r2_oos[i] = r2_arr[WINDOW + i]
    pk_oos[i] = pk_arr[WINDOW + i]
    # VIX at t-1 (LAGGED predictor)
    vix_oos[i] = vix_arr[WINDOW + i - 1]

    if (i + 1) % 500 == 0:
        print(f"    {i + 1}/{n_oos} done...")

print(f"  GARCH estimation complete. Failures: {n_fail}/{n_oos}")

# Convert VIX to daily variance: (VIX/100)² / 252
vix_sigma2 = (vix_oos / 100) ** 2 / 252

# ============================================================
# 4. Scale calibration: GARCH predicts r² scale, not PK scale
# ============================================================
print("\n[3/7] Scale calibration and baseline models...")

# GARCH σ² is calibrated to predict r² (since it's fitted on returns).
# For Parkinson evaluation, we need to rescale.
# Use expanding window OLS to map GARCH σ² → PK scale
# PK_t = a + b * GARCH_σ²_t (fitted on data up to t-1)

# Simple approach: use the ratio of means from training data
# More rigorous: rolling OLS calibration

garch_for_pk = np.full(n_oos, np.nan)  # GARCH σ² rescaled to PK
vix_for_pk = np.full(n_oos, np.nan)    # VIX σ² rescaled to PK
vix_for_r2 = vix_sigma2.copy()         # VIX already in r² scale (approx)

# Rolling calibration with expanding window (min 252 days)
MIN_CALIB = 252
for i in range(n_oos):
    if i < MIN_CALIB:
        # Use unconditional ratio for first MIN_CALIB days
        ratio = pk_arr[:WINDOW].mean() / r2_arr[:WINDOW].mean()
        garch_for_pk[i] = garch_sigma2_oos[i] * ratio
        vix_for_pk[i] = vix_sigma2[i] * ratio
    else:
        # Use expanding window of OOS data for calibration
        pk_hist = pk_oos[:i]
        garch_hist = garch_sigma2_oos[:i]
        vix_hist = vix_sigma2[:i]

        ratio_g = np.mean(pk_hist) / np.mean(garch_hist) if np.mean(garch_hist) > 0 else 1.0
        ratio_v = np.mean(pk_hist) / np.mean(vix_hist) if np.mean(vix_hist) > 0 else 1.0

        garch_for_pk[i] = garch_sigma2_oos[i] * ratio_g
        vix_for_pk[i] = vix_sigma2[i] * ratio_v

# Also create VIX-only OLS predictions for r² target (rolling)
vix_ols_for_r2 = np.full(n_oos, np.nan)
vix_ols_for_pk = np.full(n_oos, np.nan)

for i in range(MIN_CALIB, n_oos):
    # OLS: r²_t = a + b * VIX²_{t-1}/252
    X = np.column_stack([np.ones(i), vix_sigma2[:i]])

    # For r² target
    beta_r2 = np.linalg.lstsq(X, r2_oos[:i], rcond=None)[0]
    vix_ols_for_r2[i] = beta_r2[0] + beta_r2[1] * vix_sigma2[i]

    # For PK target
    beta_pk = np.linalg.lstsq(X, pk_oos[:i], rcond=None)[0]
    vix_ols_for_pk[i] = beta_pk[0] + beta_pk[1] * vix_sigma2[i]

# Ensure non-negative predictions
vix_ols_for_r2 = np.maximum(vix_ols_for_r2, 1e-10)
vix_ols_for_pk = np.maximum(vix_ols_for_pk, 1e-10)

# Combined: VIX + GARCH (rolling OLS)
combined_for_r2 = np.full(n_oos, np.nan)
combined_for_pk = np.full(n_oos, np.nan)

for i in range(MIN_CALIB, n_oos):
    X = np.column_stack([np.ones(i), garch_sigma2_oos[:i], vix_sigma2[:i]])

    beta_r2 = np.linalg.lstsq(X, r2_oos[:i], rcond=None)[0]
    combined_for_r2[i] = beta_r2[0] + beta_r2[1] * garch_sigma2_oos[i] + beta_r2[2] * vix_sigma2[i]

    beta_pk = np.linalg.lstsq(X, pk_oos[:i], rcond=None)[0]
    combined_for_pk[i] = beta_pk[0] + beta_pk[1] * garch_for_pk[i] + beta_pk[2] * vix_for_pk[i]

combined_for_r2 = np.maximum(combined_for_r2, 1e-10)
combined_for_pk = np.maximum(combined_for_pk, 1e-10)

print("  Scale calibration complete.")

# ============================================================
# 5. QLIKE evaluation with both targets
# ============================================================
print("\n[4/7] QLIKE evaluation...")

# Use only the well-calibrated portion (after MIN_CALIB)
eval_start = MIN_CALIB
eval_mask = np.ones(n_oos, dtype=bool)
eval_mask[:eval_start] = False
# Also remove any NaN
for arr in [garch_sigma2_oos, garch_for_pk, vix_ols_for_r2, vix_ols_for_pk, combined_for_r2, combined_for_pk]:
    eval_mask &= ~np.isnan(arr)

n_eval = eval_mask.sum()
print(f"  Evaluation period: {n_eval} obs (after {MIN_CALIB} calibration days)")
eval_dates = dates_arr[WINDOW:][eval_mask]
print(f"  Date range: {eval_dates[0].strftime('%Y-%m-%d')} to {eval_dates[-1].strftime('%Y-%m-%d')}")

# Extract evaluation arrays
r2_eval = r2_oos[eval_mask]
pk_eval = pk_oos[eval_mask]

garch_r2_eval = garch_sigma2_oos[eval_mask]   # GARCH → r² scale
garch_pk_eval = garch_for_pk[eval_mask]        # GARCH → PK scale
vix_r2_eval = vix_ols_for_r2[eval_mask]        # VIX OLS → r² scale
vix_pk_eval = vix_ols_for_pk[eval_mask]        # VIX OLS → PK scale
comb_r2_eval = combined_for_r2[eval_mask]      # Combined → r² scale
comb_pk_eval = combined_for_pk[eval_mask]      # Combined → PK scale

# ---- Panel A: r² as target ----
print("\n  --- Panel A: r² as evaluation target ---")
q_garch_r2 = qlike(r2_eval, garch_r2_eval)
q_vix_r2 = qlike(r2_eval, vix_r2_eval)
q_comb_r2 = qlike(r2_eval, comb_r2_eval)
mz_garch_r2 = mincer_zarnowitz_r2(r2_eval, garch_r2_eval)
mz_vix_r2 = mincer_zarnowitz_r2(r2_eval, vix_r2_eval)
mz_comb_r2 = mincer_zarnowitz_r2(r2_eval, comb_r2_eval)

print(f"    GARCH:    QLIKE={q_garch_r2:.4f}, MZ R²={mz_garch_r2:.4f}")
print(f"    VIX OLS:  QLIKE={q_vix_r2:.4f}, MZ R²={mz_vix_r2:.4f}")
print(f"    Combined: QLIKE={q_comb_r2:.4f}, MZ R²={mz_comb_r2:.4f}")

# ---- Panel B: Parkinson as target ----
print("\n  --- Panel B: Parkinson as evaluation target ---")
q_garch_pk = qlike(pk_eval, garch_pk_eval)
q_vix_pk = qlike(pk_eval, vix_pk_eval)
q_comb_pk = qlike(pk_eval, comb_pk_eval)
mz_garch_pk = mincer_zarnowitz_r2(pk_eval, garch_pk_eval)
mz_vix_pk = mincer_zarnowitz_r2(pk_eval, vix_pk_eval)
mz_comb_pk = mincer_zarnowitz_r2(pk_eval, comb_pk_eval)

print(f"    GARCH:    QLIKE={q_garch_pk:.4f}, MZ R²={mz_garch_pk:.4f}")
print(f"    VIX OLS:  QLIKE={q_vix_pk:.4f}, MZ R²={mz_vix_pk:.4f}")
print(f"    Combined: QLIKE={q_comb_pk:.4f}, MZ R²={mz_comb_pk:.4f}")

# ---- Panel C: Cross-target (GARCH fitted on r² but evaluated on PK, raw scale) ----
print("\n  --- Panel C: Cross-target evaluation ---")
# GARCH raw σ² evaluated against PK (no rescaling) — should be terrible
q_cross_raw = qlike(pk_eval, garch_r2_eval)
print(f"    GARCH(r² scale) → PK target (raw):    QLIKE={q_cross_raw:.4f}")
print(f"    GARCH(r² scale) → PK target (scaled):  QLIKE={q_garch_pk:.4f}")

# ============================================================
# 6. Noise floor comparison
# ============================================================
print("\n[5/7] Noise floor estimation (bootstrap)...")

N_BOOT = 5000

def bootstrap_noise_floor(actual, n_boot=5000):
    """Estimate noise floor: QLIKE of actual vs its own time-shuffled version."""
    n = len(actual)
    qlike_shuffled = np.zeros(n_boot)
    for b in range(n_boot):
        idx = np.random.permutation(n)
        shuffled = actual[idx]
        qlike_shuffled[b] = qlike(actual, shuffled)
    return np.mean(qlike_shuffled), np.std(qlike_shuffled)

# Noise floor for r²
nf_r2_mean, nf_r2_std = bootstrap_noise_floor(r2_eval, N_BOOT)
print(f"  r² noise floor:       {nf_r2_mean:.4f} ± {nf_r2_std:.4f}")

# Noise floor for Parkinson
nf_pk_mean, nf_pk_std = bootstrap_noise_floor(pk_eval, N_BOOT)
print(f"  Parkinson noise floor: {nf_pk_mean:.4f} ± {nf_pk_std:.4f}")

# Signal-to-noise ratio
snr_r2 = 1 - q_garch_r2 / nf_r2_mean if nf_r2_mean > 0 else 0
snr_pk = 1 - q_garch_pk / nf_pk_mean if nf_pk_mean > 0 else 0
print(f"\n  SNR (GARCH, r² target):       {snr_r2:.4f}")
print(f"  SNR (GARCH, Parkinson target): {snr_pk:.4f}")
print(f"  SNR improvement:               {(snr_pk / snr_r2 - 1) * 100:.1f}%")

# ============================================================
# 7. DM tests
# ============================================================
print("\n[6/7] Diebold-Mariano tests...")

# Element-wise QLIKE losses for DM test
def qlike_losses(actual, predicted, eps=1e-10):
    pred = np.maximum(predicted, eps)
    return np.log(pred) + actual / pred

# Panel A: r² target — GARCH vs VIX, GARCH vs Combined
loss_garch_r2 = qlike_losses(r2_eval, garch_r2_eval)
loss_vix_r2 = qlike_losses(r2_eval, vix_r2_eval)
loss_comb_r2 = qlike_losses(r2_eval, comb_r2_eval)

dm_gv_r2, p_gv_r2 = dm_test(loss_garch_r2, loss_vix_r2)
dm_gc_r2, p_gc_r2 = dm_test(loss_garch_r2, loss_comb_r2)
dm_vc_r2, p_vc_r2 = dm_test(loss_vix_r2, loss_comb_r2)

print("\n  --- r² target ---")
print(f"    GARCH vs VIX:      DM t={dm_gv_r2:+.3f}, p={p_gv_r2:.4f} {'*' if p_gv_r2 < 0.05 else ''}")
print(f"    GARCH vs Combined: DM t={dm_gc_r2:+.3f}, p={p_gc_r2:.4f} {'*' if p_gc_r2 < 0.05 else ''}")
print(f"    VIX vs Combined:   DM t={dm_vc_r2:+.3f}, p={p_vc_r2:.4f} {'*' if p_vc_r2 < 0.05 else ''}")

# Panel B: Parkinson target — GARCH vs VIX, GARCH vs Combined
loss_garch_pk = qlike_losses(pk_eval, garch_pk_eval)
loss_vix_pk = qlike_losses(pk_eval, vix_pk_eval)
loss_comb_pk = qlike_losses(pk_eval, comb_pk_eval)

dm_gv_pk, p_gv_pk = dm_test(loss_garch_pk, loss_vix_pk)
dm_gc_pk, p_gc_pk = dm_test(loss_garch_pk, loss_comb_pk)
dm_vc_pk, p_vc_pk = dm_test(loss_vix_pk, loss_comb_pk)

print("\n  --- Parkinson target ---")
print(f"    GARCH vs VIX:      DM t={dm_gv_pk:+.3f}, p={p_gv_pk:.4f} {'*' if p_gv_pk < 0.05 else ''}")
print(f"    GARCH vs Combined: DM t={dm_gc_pk:+.3f}, p={p_gc_pk:.4f} {'*' if p_gc_pk < 0.05 else ''}")
print(f"    VIX vs Combined:   DM t={dm_vc_pk:+.3f}, p={p_vc_pk:.4f} {'*' if p_vc_pk < 0.05 else ''}")

# KEY TEST: Same model, different targets
# Compare the improvement: does Parkinson target make GARCH look better?
print("\n  --- Cross-target comparison ---")
print(f"    GARCH QLIKE (r² target):       {q_garch_r2:.4f}")
print(f"    GARCH QLIKE (Parkinson target): {q_garch_pk:.4f}")
print(f"    (Not directly comparable — different units)")
print(f"    But relative to noise floor:")
print(f"      r² target:       {q_garch_r2:.4f} / {nf_r2_mean:.4f} = {q_garch_r2/nf_r2_mean:.4f}")
print(f"      Parkinson target: {q_garch_pk:.4f} / {nf_pk_mean:.4f} = {q_garch_pk/nf_pk_mean:.4f}")

# ============================================================
# 8. Regime-conditional analysis
# ============================================================
print("\n[7/7] Regime-conditional analysis...")

vix_eval = vix_oos[eval_mask]

regimes = {
    "Low (VIX<15)": vix_eval < 15,
    "Med (15≤VIX<25)": (vix_eval >= 15) & (vix_eval < 25),
    "High (VIX≥25)": vix_eval >= 25,
}

print("\n  Regime-conditional QLIKE and MZ R²:")
print(f"  {'Regime':<18} {'N':>5} | {'GARCH→r²':>10} {'GARCH→PK':>10} | {'MZ(r²)':>8} {'MZ(PK)':>8} | {'SNR(r²)':>8} {'SNR(PK)':>8}")
print("  " + "-" * 95)

regime_results = {}
for regime_name, mask in regimes.items():
    n_r = mask.sum()
    if n_r < 50:
        print(f"  {regime_name:<18} {n_r:>5} | Skip (too few)")
        continue

    # QLIKE in each regime
    q_r2_reg = qlike(r2_eval[mask], garch_r2_eval[mask])
    q_pk_reg = qlike(pk_eval[mask], garch_pk_eval[mask])

    # MZ R² in each regime
    mz_r2_reg = mincer_zarnowitz_r2(r2_eval[mask], garch_r2_eval[mask])
    mz_pk_reg = mincer_zarnowitz_r2(pk_eval[mask], garch_pk_eval[mask])

    # Noise floors per regime (smaller bootstrap)
    nf_r2_reg, _ = bootstrap_noise_floor(r2_eval[mask], 2000)
    nf_pk_reg, _ = bootstrap_noise_floor(pk_eval[mask], 2000)

    snr_r2_reg = 1 - q_r2_reg / nf_r2_reg if nf_r2_reg > 0 else 0
    snr_pk_reg = 1 - q_pk_reg / nf_pk_reg if nf_pk_reg > 0 else 0

    print(f"  {regime_name:<18} {n_r:>5} | {q_r2_reg:>10.4f} {q_pk_reg:>10.4f} | {mz_r2_reg:>8.4f} {mz_pk_reg:>8.4f} | {snr_r2_reg:>8.4f} {snr_pk_reg:>8.4f}")

    regime_results[regime_name] = {
        "n": int(n_r),
        "qlike_r2": float(q_r2_reg),
        "qlike_pk": float(q_pk_reg),
        "mz_r2": float(mz_r2_reg),
        "mz_pk": float(mz_pk_reg),
        "snr_r2": float(snr_r2_reg),
        "snr_pk": float(snr_pk_reg),
    }

# ============================================================
# 9. Parkinson-innovation GARCH (fit on PK-derived returns)
# ============================================================
print("\n\n[BONUS] Parkinson-innovation GARCH...")
print("  Idea: construct 'Parkinson returns' = sign(r) * sqrt(PK * 4 * ln2) and fit GARCH on them")

# Parkinson-implied absolute return
pk_abs_return = np.sqrt(parkinson.values * 4 * np.log(2))
pk_signed_return = np.sign(returns_dec.values) * pk_abs_return * 100  # pct

pk_sigma2_oos = np.full(n_oos, np.nan)
n_fail_pk = 0

for i in range(n_oos):
    train_pk_ret = pk_signed_return[i:i + WINDOW]

    try:
        am = arch_model(train_pk_ret, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Zero')
        res = am.fit(disp='off', show_warning=False)
        fcast = res.forecast(horizon=1)
        pk_sigma2_oos[i] = fcast.variance.values[-1, 0] / 1e4
    except Exception:
        n_fail_pk += 1
        if i > 0:
            pk_sigma2_oos[i] = pk_sigma2_oos[i - 1]
        else:
            pk_sigma2_oos[i] = np.var(train_pk_ret) / 1e4

print(f"  PK-GARCH estimation complete. Failures: {n_fail_pk}/{n_oos}")

# Evaluate PK-GARCH against both targets
pk_garch_eval = pk_sigma2_oos[eval_mask]
q_pkgarch_r2 = qlike(r2_eval, pk_garch_eval)
q_pkgarch_pk = qlike(pk_eval, pk_garch_eval)
mz_pkgarch_r2 = mincer_zarnowitz_r2(r2_eval, pk_garch_eval)
mz_pkgarch_pk = mincer_zarnowitz_r2(pk_eval, pk_garch_eval)

print(f"\n  PK-GARCH → r² target:  QLIKE={q_pkgarch_r2:.4f}, MZ R²={mz_pkgarch_r2:.4f}")
print(f"  PK-GARCH → PK target:  QLIKE={q_pkgarch_pk:.4f}, MZ R²={mz_pkgarch_pk:.4f}")
print(f"  Std GARCH → r² target: QLIKE={q_garch_r2:.4f}, MZ R²={mz_garch_r2:.4f}")
print(f"  Std GARCH → PK target: QLIKE={q_garch_pk:.4f}, MZ R²={mz_garch_pk:.4f}")

# DM: PK-GARCH vs Standard GARCH (both evaluated on PK target)
loss_pkgarch_pk = qlike_losses(pk_eval, pk_garch_eval)
dm_pkvs, p_pkvs = dm_test(loss_pkgarch_pk, loss_garch_pk)
print(f"\n  DM test: PK-GARCH vs Std GARCH (PK target): t={dm_pkvs:+.3f}, p={p_pkvs:.4f} {'*' if p_pkvs < 0.05 else ''}")

# DM: PK-GARCH vs Standard GARCH (both evaluated on r² target)
loss_pkgarch_r2 = qlike_losses(r2_eval, pk_garch_eval)
dm_pkvs_r2, p_pkvs_r2 = dm_test(loss_pkgarch_r2, loss_garch_r2)
print(f"  DM test: PK-GARCH vs Std GARCH (r² target):  t={dm_pkvs_r2:+.3f}, p={p_pkvs_r2:.4f} {'*' if p_pkvs_r2 < 0.05 else ''}")

# ============================================================
# 10. Summary statistics
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY TABLE")
print("=" * 70)

print(f"\n{'Model':<25} | {'r² target':>12} {'PK target':>12} | {'MZ R²(r²)':>10} {'MZ R²(PK)':>10} |")
print("-" * 75)
print(f"{'GJR-GARCH (standard)':<25} | {q_garch_r2:>12.4f} {q_garch_pk:>12.4f} | {mz_garch_r2:>10.4f} {mz_garch_pk:>10.4f} |")
print(f"{'GJR-GARCH (PK-fitted)':<25} | {q_pkgarch_r2:>12.4f} {q_pkgarch_pk:>12.4f} | {mz_pkgarch_r2:>10.4f} {mz_pkgarch_pk:>10.4f} |")
print(f"{'VIX OLS':<25} | {q_vix_r2:>12.4f} {q_vix_pk:>12.4f} | {mz_vix_r2:>10.4f} {mz_vix_pk:>10.4f} |")
print(f"{'GARCH + VIX Combined':<25} | {q_comb_r2:>12.4f} {q_comb_pk:>12.4f} | {mz_comb_r2:>10.4f} {mz_comb_pk:>10.4f} |")
print("-" * 75)
print(f"{'Noise floor':<25} | {nf_r2_mean:>12.4f} {nf_pk_mean:>12.4f} |")
print(f"{'SNR (standard GARCH)':<25} | {snr_r2:>12.4f} {snr_pk:>12.4f} |")

# ============================================================
# 11. Key question answer
# ============================================================
print("\n" + "=" * 70)
print("KEY FINDINGS")
print("=" * 70)

pk_improvement_mz = (mz_garch_pk / mz_garch_r2 - 1) * 100 if mz_garch_r2 > 0 else 0
pk_improvement_snr = (snr_pk / snr_r2 - 1) * 100 if snr_r2 > 0 else 0

print(f"\n1. MZ R² improvement (Parkinson vs r²): {pk_improvement_mz:+.1f}%")
print(f"   r² target MZ R²:       {mz_garch_r2:.4f}")
print(f"   Parkinson target MZ R²: {mz_garch_pk:.4f}")

print(f"\n2. SNR improvement: {pk_improvement_snr:+.1f}%")
print(f"   SNR (r² target):       {snr_r2:.4f}")
print(f"   SNR (Parkinson target): {snr_pk:.4f}")

print(f"\n3. PK-fitted GARCH vs Standard GARCH:")
print(f"   On PK target: DM t={dm_pkvs:+.3f} (p={p_pkvs:.4f})")
print(f"   On r² target: DM t={dm_pkvs_r2:+.3f} (p={p_pkvs_r2:.4f})")

# Does the 31% K373 R² improvement survive?
print(f"\n4. K373 R² improvement ({31}%) survival in GARCH OOS framework:")
if mz_garch_pk > mz_garch_r2:
    print(f"   YES — MZ R² improves by {pk_improvement_mz:.1f}% when using Parkinson target")
else:
    print(f"   NO — MZ R² does NOT improve ({pk_improvement_mz:.1f}%)")

print(f"\n5. Best model for each target:")
best_r2 = min([(q_garch_r2, "GARCH"), (q_vix_r2, "VIX"), (q_comb_r2, "Combined"), (q_pkgarch_r2, "PK-GARCH")], key=lambda x: x[0])
best_pk = min([(q_garch_pk, "GARCH"), (q_vix_pk, "VIX"), (q_comb_pk, "Combined"), (q_pkgarch_pk, "PK-GARCH")], key=lambda x: x[0])
print(f"   r² target best:       {best_r2[1]} (QLIKE={best_r2[0]:.4f})")
print(f"   Parkinson target best: {best_pk[1]} (QLIKE={best_pk[0]:.4f})")

# ============================================================
# 12. Correlation structure
# ============================================================
print(f"\n6. Proxy quality diagnostics:")
print(f"   Corr(r², PK) in OOS: {np.corrcoef(r2_eval, pk_eval)[0,1]:.4f}")
print(f"   r² CoV:  {np.std(r2_eval)/np.mean(r2_eval):.2f}")
print(f"   PK CoV:  {np.std(pk_eval)/np.mean(pk_eval):.2f}")
print(f"   r²/PK ratio: {np.mean(r2_eval)/np.mean(pk_eval):.3f}")

# ============================================================
# 13. Save results
# ============================================================
results = {
    "experiment": "K374",
    "title": "Parkinson-Targeted GJR-GARCH",
    "timestamp": datetime.now().isoformat(),
    "data": {
        "asset": "SPY",
        "source": "yfinance",
        "period": f"{common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')}",
        "total_obs": len(common_idx),
        "window": WINDOW,
        "oos_obs": int(n_eval),
        "oos_period": f"{eval_dates[0].strftime('%Y-%m-%d')} to {eval_dates[-1].strftime('%Y-%m-%d')}",
    },
    "results": {
        "panel_a_r2_target": {
            "garch_qlike": float(q_garch_r2),
            "vix_qlike": float(q_vix_r2),
            "combined_qlike": float(q_comb_r2),
            "pkgarch_qlike": float(q_pkgarch_r2),
            "garch_mz_r2": float(mz_garch_r2),
            "vix_mz_r2": float(mz_vix_r2),
            "combined_mz_r2": float(mz_comb_r2),
            "pkgarch_mz_r2": float(mz_pkgarch_r2),
            "noise_floor": float(nf_r2_mean),
            "snr_garch": float(snr_r2),
        },
        "panel_b_pk_target": {
            "garch_qlike": float(q_garch_pk),
            "vix_qlike": float(q_vix_pk),
            "combined_qlike": float(q_comb_pk),
            "pkgarch_qlike": float(q_pkgarch_pk),
            "garch_mz_r2": float(mz_garch_pk),
            "vix_mz_r2": float(mz_vix_pk),
            "combined_mz_r2": float(mz_comb_pk),
            "pkgarch_mz_r2": float(mz_pkgarch_pk),
            "noise_floor": float(nf_pk_mean),
            "snr_garch": float(snr_pk),
        },
        "dm_tests": {
            "r2_target": {
                "garch_vs_vix": {"t": float(dm_gv_r2), "p": float(p_gv_r2)},
                "garch_vs_combined": {"t": float(dm_gc_r2), "p": float(p_gc_r2)},
                "vix_vs_combined": {"t": float(dm_vc_r2), "p": float(p_vc_r2)},
            },
            "pk_target": {
                "garch_vs_vix": {"t": float(dm_gv_pk), "p": float(p_gv_pk)},
                "garch_vs_combined": {"t": float(dm_gc_pk), "p": float(p_gc_pk)},
                "vix_vs_combined": {"t": float(dm_vc_pk), "p": float(p_vc_pk)},
            },
            "pkgarch_vs_stdgarch": {
                "on_pk_target": {"t": float(dm_pkvs), "p": float(p_pkvs)},
                "on_r2_target": {"t": float(dm_pkvs_r2), "p": float(p_pkvs_r2)},
            },
        },
        "key_metrics": {
            "mz_r2_improvement_pct": float(pk_improvement_mz),
            "snr_improvement_pct": float(pk_improvement_snr),
            "corr_r2_pk": float(np.corrcoef(r2_eval, pk_eval)[0, 1]),
            "r2_cov": float(np.std(r2_eval) / np.mean(r2_eval)),
            "pk_cov": float(np.std(pk_eval) / np.mean(pk_eval)),
        },
        "regime_conditional": regime_results,
    },
    "conclusion": "",
    "limitations": [
        "SPY only — needs cross-asset validation",
        "Parkinson assumes no gaps/jumps (underestimates with overnight gaps)",
        "Scale calibration uses expanding OLS — slight look-ahead in mean ratio",
        "PK-GARCH uses sign(r)*sqrt(PK) as innovation — not a standard approach",
        "Single window size (w=2000) — sensitivity not tested",
    ],
}

# Generate conclusion
if mz_garch_pk > mz_garch_r2 * 1.1:
    conclusion = f"Parkinson target IMPROVES GARCH evaluation: MZ R² {mz_garch_r2:.4f} → {mz_garch_pk:.4f} (+{pk_improvement_mz:.1f}%). "
elif mz_garch_pk > mz_garch_r2:
    conclusion = f"Parkinson target shows MARGINAL improvement: MZ R² {mz_garch_r2:.4f} → {mz_garch_pk:.4f} (+{pk_improvement_mz:.1f}%). "
else:
    conclusion = f"Parkinson target does NOT improve GARCH evaluation: MZ R² {mz_garch_r2:.4f} → {mz_garch_pk:.4f} ({pk_improvement_mz:.1f}%). "

if abs(dm_pkvs) > 1.96:
    conclusion += f"PK-fitted GARCH is significantly {'better' if dm_pkvs < 0 else 'worse'} than standard GARCH (DM t={dm_pkvs:.2f}). "
else:
    conclusion += f"PK-fitted GARCH is NOT significantly different from standard GARCH (DM t={dm_pkvs:.2f}). "

conclusion += f"K373's +31% R² improvement {'partially survives' if pk_improvement_mz > 10 else 'does NOT survive'} in OOS GARCH framework. "
conclusion += f"SNR: r²={snr_r2:.3f}, PK={snr_pk:.3f} ({pk_improvement_snr:+.1f}%)."

results["conclusion"] = conclusion
print(f"\nCONCLUSION: {conclusion}")

# Save
out_path = "experiments/k374_parkinson_garch_results.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved to {out_path}")
