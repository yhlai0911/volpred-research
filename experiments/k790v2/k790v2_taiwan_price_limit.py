"""
K790v2: Taiwan Price Limit Latent Volatility (debug/clean version)
=================================================================
Hypothesis: Taiwan's ±10% daily price limits create latent volatility.
When |r_{t-1}| approaches the limit (>5% or >3%), the NEXT day's variance
is systematically higher (trapped orders released).

Models:
  1. GJR-GARCH(1,1) baseline
  2. GJR-GARCH-X with dummy I(|r_{t-1}|>5%)  [hard limit proxy]
  3. GJR-GARCH-X with dummy I(|r_{t-1}|>3%)  [soft limit proxy]

Data: 0050.TW via yfinance (2006-01-01 onward)
      clean_tw50_data() applied to fix 2014 split artifact
OOS:  2015-01-01 onward (expanding window, refit every 63 days)

Evaluation:
  - QLIKE on r² (Patton 2011 proxy-robust)
  - DM test (Harvey et al. 1997)
  - Diagnostics: limit-hit frequency, convergence rate

Reference:
  Huang & Liu (2014), "Price limits and stock market volatility in Taiwan"
  Patton (2011), "Volatility forecast comparison using imperfect volatility proxies"
  Harvey, Leybourne & Newbold (1997), "Testing the equality of prediction MSEs"
"""

import sys
import os
import json
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import minimize
from scipy.stats import norm
import warnings
warnings.filterwarnings('ignore')

# Make sure volpred is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from volpred.utils import clean_tw50_data

# ─── Configuration ────────────────────────────────────────────────────────────
START_DATE   = "2006-01-01"
OOS_START    = "2015-01-01"
REFIT_EVERY  = 63          # trading days between refits
MIN_TRAIN    = 500         # minimum observations to start fitting
THRESHOLD_5  = 0.05        # hard limit proxy
THRESHOLD_3  = 0.03        # soft limit proxy

# ─── Data Download & Clean ────────────────────────────────────────────────────
print("=" * 60)
print("K790v2: Taiwan Price Limit Latent Volatility")
print("=" * 60)

print(f"\nDownloading 0050.TW from {START_DATE}...")
raw = yf.download("0050.TW", start=START_DATE, progress=False, auto_adjust=True)
prices_raw = raw["Close"].squeeze()
print(f"Raw rows: {len(prices_raw)}")

clean_prices, clean_returns = clean_tw50_data(prices_raw)
r = clean_returns.dropna()
print(f"After clean: {len(r)} obs, {r.index[0].date()} to {r.index[-1].date()}")

# ─── Descriptive Statistics ───────────────────────────────────────────────────
print("\n--- Descriptive Statistics ---")
print(f"  Mean:     {r.mean()*100:.4f}%")
print(f"  Std:      {r.std()*100:.4f}%")
print(f"  Skewness: {r.skew():.4f}")
print(f"  Kurtosis: {r.kurt():.4f}")
print(f"  Min:      {r.min()*100:.2f}%")
print(f"  Max:      {r.max()*100:.2f}%")

# ─── Limit Proximity Diagnostics ─────────────────────────────────────────────
print("\n--- Price Limit Proximity Diagnostics ---")
abs_r = r.abs()
limit5_days = (abs_r > THRESHOLD_5).sum()
limit3_days = (abs_r > THRESHOLD_3).sum()
total_days  = len(r)
print(f"  |r| > 5%: {limit5_days} days ({limit5_days/total_days*100:.1f}%)")
print(f"  |r| > 3%: {limit3_days} days ({limit3_days/total_days*100:.1f}%)")

oos_mask = r.index >= OOS_START
oos_r    = r[oos_mask]
oos_abs  = oos_r.abs()
oos_lim5 = (oos_abs > THRESHOLD_5).sum()
oos_lim3 = (oos_abs > THRESHOLD_3).sum()
print(f"\n  OOS period ({OOS_START} onward, {len(oos_r)} days):")
print(f"    |r| > 5%: {oos_lim5} days ({oos_lim5/len(oos_r)*100:.1f}%)")
print(f"    |r| > 3%: {oos_lim3} days ({oos_lim3/len(oos_r)*100:.1f}%)")

if limit5_days < 30:
    print("\n  WARNING: Very few >5% days. Hard limit proxy may lack power.")

# ─── GJR-GARCH Negative Log-Likelihood ───────────────────────────────────────

def gjr_garch_nll(params, returns, exog=None):
    """GJR-GARCH(1,1) or GJR-GARCH-X(1,1) negative log-likelihood.

    Model:
      r_t = mu + eps_t
      eps_t = sigma_t * z_t,  z_t ~ N(0,1)
      sigma²_t = omega + alpha*eps²_{t-1} + gamma*eps²_{t-1}*I(eps_{t-1}<0)
                       + beta*sigma²_{t-1}
                       + delta*X_{t-1}   [if exog provided]

    Params: [mu, omega, alpha, gamma, beta]  (+ delta if exog provided)
    Constraints: omega>0, alpha>=0, gamma>=0, beta>=0,
                 alpha + gamma/2 + beta < 1 (covariance stationarity)
    """
    n_base = 5
    if exog is not None:
        mu, omega, alpha, gamma, beta, delta = params
    else:
        mu, omega, alpha, gamma, beta = params
        delta = 0.0

    # Hard positivity/bounds check
    if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0:
        return 1e10
    if alpha + gamma/2 + beta >= 1.0:
        return 1e10

    T = len(returns)
    sigma2 = np.empty(T)
    eps    = returns - mu

    # Initialize variance at unconditional variance
    uncond = omega / max(1 - alpha - gamma/2 - beta, 1e-6)
    sigma2[0] = uncond

    for t in range(1, T):
        ind = 1.0 if eps[t-1] < 0 else 0.0
        x_lag = float(exog[t-1]) if exog is not None else 0.0
        sigma2[t] = (omega
                     + alpha * eps[t-1]**2
                     + gamma * eps[t-1]**2 * ind
                     + beta  * sigma2[t-1]
                     + delta * x_lag)
        if sigma2[t] <= 0:
            sigma2[t] = 1e-8

    # Log-likelihood
    nll = 0.5 * np.sum(np.log(sigma2) + eps**2 / sigma2)
    if not np.isfinite(nll):
        return 1e10
    return nll


def fit_gjr_garch(returns, exog=None, n_restarts=3):
    """Fit GJR-GARCH(-X) with multiple restarts. Returns (params, converged)."""
    r_arr = np.asarray(returns, dtype=float)
    e_arr = np.asarray(exog,    dtype=float) if exog is not None else None

    var_r = np.var(r_arr)

    best_val    = np.inf
    best_params = None
    best_conv   = False

    # Starting points
    starts = [
        [0.0, var_r * 0.05, 0.05, 0.05, 0.88],
        [0.0, var_r * 0.10, 0.08, 0.06, 0.85],
        [r_arr.mean(), var_r * 0.02, 0.03, 0.07, 0.90],
    ]
    if exog is not None:
        starts = [s + [0.001 * var_r] for s in starts]

    bounds_base = [
        (None, None),          # mu: unconstrained
        (1e-8, None),          # omega > 0
        (0.0,  0.5),           # alpha in [0, 0.5]
        (0.0,  0.5),           # gamma in [0, 0.5]
        (0.0,  0.9999),        # beta  in [0, 1)
    ]
    if exog is not None:
        bounds_base.append((0.0, None))   # delta >= 0 (variance only increases)

    for x0 in starts[:n_restarts]:
        try:
            res = minimize(
                gjr_garch_nll,
                x0,
                args=(r_arr, e_arr),
                method='L-BFGS-B',
                bounds=bounds_base,
                options={'maxiter': 500, 'ftol': 1e-9}
            )
            if res.fun < best_val:
                best_val    = res.fun
                best_params = res.x
                best_conv   = res.success
        except Exception:
            pass

    return best_params, best_conv


def compute_sigma2_forecast(params, returns, exog=None):
    """Given fitted params, compute one-step-ahead sigma² for each t.

    sigma²_{t+1} is computed using info up to t (proper OOS forecast).
    Returns sigma2_forecast aligned with returns index (shifted by 1).
    """
    r_arr = np.asarray(returns, dtype=float)
    e_arr = np.asarray(exog, dtype=float) if exog is not None else None
    T     = len(r_arr)

    if exog is not None:
        mu, omega, alpha, gamma, beta, delta = params
    else:
        mu, omega, alpha, gamma, beta = params
        delta = 0.0

    eps    = r_arr - mu
    sigma2 = np.empty(T + 1)
    uncond = omega / max(1 - alpha - gamma/2 - beta, 1e-6)
    sigma2[0] = uncond

    for t in range(T):
        ind    = 1.0 if eps[t] < 0 else 0.0
        x_lag  = float(e_arr[t]) if e_arr is not None else 0.0
        sigma2[t+1] = (omega
                       + alpha * eps[t]**2
                       + gamma * eps[t]**2 * ind
                       + beta  * sigma2[t]
                       + delta * x_lag)
        if sigma2[t+1] <= 0:
            sigma2[t+1] = uncond

    # sigma2[t+1] is the forecast for day t+1 using data up to t
    # Return as index-aligned with returns (shifted: forecast[t] is for day t)
    return sigma2[1:]  # length T, sigma2[i] is forecast for r[i]


# ─── Expanding Window OOS Forecast ────────────────────────────────────────────
print("\n--- Running Expanding Window OOS Forecast ---")
print(f"  OOS start: {OOS_START}, refit every {REFIT_EVERY} days")

r_arr    = r.values
dates    = r.index
abs_r_arr= np.abs(r_arr)
# Limit dummy signals (using lag-1, so at time t we observe |r_{t-1}|)
dummy5   = (abs_r_arr > THRESHOLD_5).astype(float)  # I(|r_t| > 5%)
dummy3   = (abs_r_arr > THRESHOLD_3).astype(float)  # I(|r_t| > 3%)

oos_start_idx = np.searchsorted(dates, pd.Timestamp(OOS_START))
print(f"  Total observations: {len(r_arr)}")
print(f"  Training obs (pre-OOS): {oos_start_idx}")
print(f"  OOS observations: {len(r_arr) - oos_start_idx}")

# Storage for OOS forecasts
fcst_base = np.full(len(r_arr), np.nan)
fcst_x5   = np.full(len(r_arr), np.nan)
fcst_x3   = np.full(len(r_arr), np.nan)
conv_base_list = []
conv_x5_list   = []
conv_x3_list   = []

# The last refit point (trigger refit when we've seen REFIT_EVERY new OOS obs)
last_refit = oos_start_idx
params_base_stored = None
params_x5_stored   = None
params_x3_stored   = None

# Track convergence per refit
total_refits   = 0
conv_base_cnt  = 0
conv_x5_cnt    = 0
conv_x3_cnt    = 0

for t in range(oos_start_idx, len(r_arr)):
    # Decide whether to refit
    do_refit = (t == oos_start_idx) or ((t - last_refit) >= REFIT_EVERY)

    if do_refit:
        train_r   = r_arr[:t]
        train_d5  = dummy5[:t]   # exog for X5: I(|r_{s}|>5%) for s=0..t-1
        train_d3  = dummy3[:t]   # exog for X3

        # NOTE: exog in variance equation is X_{t-1} → we pass dummy5 directly
        # and index in gjr_garch_nll uses t-1 position naturally.

        p_base, c_base = fit_gjr_garch(train_r, exog=None)
        p_x5,   c_x5   = fit_gjr_garch(train_r, exog=train_d5)
        p_x3,   c_x3   = fit_gjr_garch(train_r, exog=train_d3)

        params_base_stored = p_base
        params_x5_stored   = p_x5
        params_x3_stored   = p_x3

        last_refit = t
        total_refits += 1
        if c_base: conv_base_cnt += 1
        if c_x5:   conv_x5_cnt   += 1
        if c_x3:   conv_x3_cnt   += 1

        if total_refits <= 3 or total_refits % 10 == 0:
            print(f"    Refit #{total_refits} at t={t} ({dates[t].date()}), "
                  f"train={t} obs, conv=({c_base},{c_x5},{c_x3})")

    # Generate forecast for day t using params fitted on data[:t]
    # (expanding window: use all data up to but not including t)
    # We compute sigma²_t = f(params, eps_{t-1}, sigma²_{t-1})
    # using a full forward pass through training data to get sigma²_{t-1},
    # then one more step.

    # For efficiency: recompute only when params change
    # During non-refit days, we do a single-step update using stored state

    # --- baseline forecast ---
    if params_base_stored is not None:
        try:
            fv = compute_sigma2_forecast(params_base_stored, r_arr[:t], exog=None)
            # fv[-1] is the forecast for position t (the NEXT day after training)
            # But we only want σ²_t (the forecast for day t using data up to t-1)
            # compute_sigma2_forecast returns sigma2[1..T], where sigma2[i] is for r[i]
            # So for position t, we need the forecast from data[:t], last element
            fcst_base[t] = fv[-1]
        except Exception:
            pass

    # --- X5 forecast ---
    if params_x5_stored is not None:
        try:
            fv = compute_sigma2_forecast(params_x5_stored, r_arr[:t], exog=dummy5[:t])
            fcst_x5[t] = fv[-1]
        except Exception:
            pass

    # --- X3 forecast ---
    if params_x3_stored is not None:
        try:
            fv = compute_sigma2_forecast(params_x3_stored, r_arr[:t], exog=dummy3[:t])
            fcst_x3[t] = fv[-1]
        except Exception:
            pass

print(f"\n  Total refits: {total_refits}")
print(f"  Convergence rate — Base: {conv_base_cnt}/{total_refits} "
      f"({100*conv_base_cnt/max(total_refits,1):.0f}%), "
      f"X5: {conv_x5_cnt}/{total_refits} ({100*conv_x5_cnt/max(total_refits,1):.0f}%), "
      f"X3: {conv_x3_cnt}/{total_refits} ({100*conv_x3_cnt/max(total_refits,1):.0f}%)")

# ─── OOS Evaluation ───────────────────────────────────────────────────────────
print("\n--- OOS Evaluation (QLIKE on r²) ---")

# Extract OOS window
oos_idx   = slice(oos_start_idx, len(r_arr))
r_oos     = r_arr[oos_idx]
r2_oos    = r_oos**2                        # proxy for σ² (Patton 2011)
f_base    = fcst_base[oos_idx]
f_x5      = fcst_x5[oos_idx]
f_x3      = fcst_x3[oos_idx]

# Remove NaN positions
valid_mask = (np.isfinite(f_base) & np.isfinite(f_x5) & np.isfinite(f_x3)
              & np.isfinite(r2_oos) & (f_base > 0) & (f_x5 > 0) & (f_x3 > 0))
print(f"  Valid OOS forecast pairs: {valid_mask.sum()} / {len(r_oos)}")

r2_v  = r2_oos[valid_mask]
fb_v  = f_base[valid_mask]
fx5_v = f_x5[valid_mask]
fx3_v = f_x3[valid_mask]

def qlike(sigma2_hat, r2_actual):
    """QLIKE loss: log(sigma²) + r²/sigma² (Patton 2011)."""
    return np.mean(np.log(sigma2_hat) + r2_actual / sigma2_hat)

qlike_base = qlike(fb_v,  r2_v)
qlike_x5   = qlike(fx5_v, r2_v)
qlike_x3   = qlike(fx3_v, r2_v)

print(f"  QLIKE — Base: {qlike_base:.6f}")
print(f"  QLIKE — X5:   {qlike_x5:.6f}")
print(f"  QLIKE — X3:   {qlike_x3:.6f}")

# Also compute MSE on r²
mse_base = np.mean((fb_v  - r2_v)**2)
mse_x5   = np.mean((fx5_v - r2_v)**2)
mse_x3   = np.mean((fx3_v - r2_v)**2)
print(f"\n  MSE(r²) — Base: {mse_base:.2e}")
print(f"  MSE(r²) — X5:   {mse_x5:.2e}")
print(f"  MSE(r²) — X3:   {mse_x3:.2e}")

# ─── Diebold-Mariano Test ─────────────────────────────────────────────────────
print("\n--- Diebold-Mariano Test (Harvey et al. 1997) ---")

def dm_test(loss1, loss2, h=1):
    """DM test: H0: equal predictive accuracy.
    loss_diff = loss1 - loss2 (positive = model2 better)
    Returns (DM_stat, p-value). Harvey correction applied.
    """
    d  = loss1 - loss2
    T  = len(d)
    d_mean = np.mean(d)
    # Newey-West variance with lag h-1
    gamma0 = np.var(d, ddof=0)
    nw_var  = gamma0
    for k in range(1, h):
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        nw_var  += 2 * (1 - k/(h+1)) * gamma_k
    nw_var = max(nw_var, 1e-20)
    dm_stat = d_mean / np.sqrt(nw_var / T)
    # Harvey et al. small-sample correction
    harvey_dm = dm_stat * np.sqrt((T + 1 - 2*h + h*(h-1)/T) / T)
    p_val = 2 * (1 - norm.cdf(abs(harvey_dm)))
    return harvey_dm, p_val

# QLIKE losses per observation
ql_loss_base = np.log(fb_v)  + r2_v / fb_v
ql_loss_x5   = np.log(fx5_v) + r2_v / fx5_v
ql_loss_x3   = np.log(fx3_v) + r2_v / fx3_v

dm_stat_x5, p_x5 = dm_test(ql_loss_base, ql_loss_x5)
dm_stat_x3, p_x3 = dm_test(ql_loss_base, ql_loss_x3)
dm_stat_x5x3, p_x5x3 = dm_test(ql_loss_x5, ql_loss_x3)

print(f"  DM(Base vs X5):  stat={dm_stat_x5:.3f}, p={p_x5:.4f}  "
      f"{'X5 BETTER' if dm_stat_x5 > 0 else 'Base better'}")
print(f"  DM(Base vs X3):  stat={dm_stat_x3:.3f}, p={p_x3:.4f}  "
      f"{'X3 BETTER' if dm_stat_x3 > 0 else 'Base better'}")
print(f"  DM(X5 vs X3):    stat={dm_stat_x5x3:.3f}, p={p_x5x3:.4f}")
print(f"\n  Harvey (1997) significance threshold: |t| > 3.0")
print(f"  X5 significant (|t|>3.0): {abs(dm_stat_x5) > 3.0}")
print(f"  X3 significant (|t|>3.0): {abs(dm_stat_x3) > 3.0}")

# ─── Conditional Analysis ─────────────────────────────────────────────────────
print("\n--- Conditional QLIKE (around limit-hit days) ---")

# Day AFTER a limit-proximity event
d5_oos = dummy5[oos_idx][valid_mask]
d3_oos = dummy3[oos_idx][valid_mask]

# shift(1): effect on NEXT day's forecast accuracy
# We look at days t where dummy5[t-1] = 1 (limit event yesterday)
d5_lagged = np.zeros(len(d5_oos))
d5_lagged[1:] = d5_oos[:-1]
d3_lagged = np.zeros(len(d3_oos))
d3_lagged[1:] = d3_oos[:-1]

after5_mask = d5_lagged == 1
after3_mask = d3_lagged == 1
normal_mask = d3_lagged == 0

n_after5 = after5_mask.sum()
n_after3 = after3_mask.sum()
n_normal = normal_mask.sum()

print(f"  Days after >5% event:  {n_after5}")
print(f"  Days after >3% event:  {n_after3}")
print(f"  Normal days:           {n_normal}")

if n_after5 >= 10:
    ql_base_after5  = np.mean(ql_loss_base[after5_mask])
    ql_x5_after5    = np.mean(ql_loss_x5[after5_mask])
    ql_base_normal5 = np.mean(ql_loss_base[~after5_mask])
    ql_x5_normal5   = np.mean(ql_loss_x5[~after5_mask])
    print(f"\n  QLIKE after >5% event: Base={ql_base_after5:.4f}, X5={ql_x5_after5:.4f}")
    print(f"  QLIKE on normal days:  Base={ql_base_normal5:.4f}, X5={ql_x5_normal5:.4f}")
    improvement_after5 = (ql_base_after5 - ql_x5_after5) / ql_base_after5 * 100
    print(f"  X5 improvement on limit days: {improvement_after5:.2f}%")
else:
    print("  Insufficient limit events for conditional analysis.")

# ─── Compile Results ──────────────────────────────────────────────────────────
print("\n=== SUMMARY ===")
print(f"  Asset:     0050.TW")
print(f"  Period:    {dates[0].date()} to {dates[-1].date()}")
print(f"  OOS start: {OOS_START}")
print(f"  OOS obs:   {valid_mask.sum()}")
print(f"  Limit days >5%: {limit5_days} ({limit5_days/total_days*100:.1f}%)")
print(f"  Limit days >3%: {limit3_days} ({limit3_days/total_days*100:.1f}%)")
print()
print(f"  QLIKE:  Base={qlike_base:.6f}  X5={qlike_x5:.6f}  X3={qlike_x3:.6f}")
print(f"  Best model: {'X3' if qlike_x3 <= qlike_x5 and qlike_x3 < qlike_base else 'X5' if qlike_x5 < qlike_base else 'Base'}")
print()
print(f"  DM(Base vs X5): t={dm_stat_x5:.3f}, p={p_x5:.4f}")
print(f"  DM(Base vs X3): t={dm_stat_x3:.3f}, p={p_x3:.4f}")
print(f"  X5 statistically significant (|t|>3.0): {abs(dm_stat_x5) > 3.0}")
print(f"  X3 statistically significant (|t|>3.0): {abs(dm_stat_x3) > 3.0}")

# ─── Save Results ─────────────────────────────────────────────────────────────
results = {
    "experiment_id": "K790v2",
    "title": "Taiwan Price Limit Latent Volatility (GJR-GARCH-X)",
    "asset": "0050.TW",
    "data_source": "yfinance",
    "start_date": str(dates[0].date()),
    "end_date": str(dates[-1].date()),
    "oos_start": OOS_START,
    "total_obs": int(len(r_arr)),
    "oos_obs": int(valid_mask.sum()),
    "diagnostics": {
        "limit_days_5pct": int(limit5_days),
        "limit_days_3pct": int(limit3_days),
        "limit_freq_5pct": float(limit5_days / total_days),
        "limit_freq_3pct": float(limit3_days / total_days),
        "oos_limit_days_5pct": int(oos_lim5),
        "oos_limit_days_3pct": int(oos_lim3),
        "total_refits": int(total_refits),
        "convergence_rate_base": float(conv_base_cnt / max(total_refits, 1)),
        "convergence_rate_x5":   float(conv_x5_cnt   / max(total_refits, 1)),
        "convergence_rate_x3":   float(conv_x3_cnt   / max(total_refits, 1)),
    },
    "qlike": {
        "base": float(qlike_base),
        "x5":   float(qlike_x5),
        "x3":   float(qlike_x3),
    },
    "mse_r2": {
        "base": float(mse_base),
        "x5":   float(mse_x5),
        "x3":   float(mse_x3),
    },
    "dm_test": {
        "base_vs_x5_stat":  float(dm_stat_x5),
        "base_vs_x5_pval":  float(p_x5),
        "base_vs_x3_stat":  float(dm_stat_x3),
        "base_vs_x3_pval":  float(p_x3),
        "x5_vs_x3_stat":    float(dm_stat_x5x3),
        "x5_vs_x3_pval":    float(p_x5x3),
        "x5_significant_harvey3": bool(abs(dm_stat_x5) > 3.0),
        "x3_significant_harvey3": bool(abs(dm_stat_x3) > 3.0),
    },
    "conclusion": "",
    "methodology": {
        "model": "GJR-GARCH(1,1)-X",
        "exog_x5": "I(|r_{t-1}|>5%) — hard limit proxy",
        "exog_x3": "I(|r_{t-1}|>3%) — soft limit proxy",
        "window": "expanding",
        "refit_every": REFIT_EVERY,
        "min_train": MIN_TRAIN,
        "evaluation": "QLIKE on r² (Patton 2011), DM test (Harvey et al. 1997)",
        "lag": "signal.shift(1) via exog index: exog[t-1] is used in variance at t",
    },
    "references": [
        "Patton A.J. (2011). Volatility forecast comparison using imperfect volatility proxies. JoE.",
        "Harvey, Leybourne & Newbold (1997). Testing equality of prediction MSEs. IJoF.",
        "Huang & Liu (2014). Price limits and stock market volatility in Taiwan. JFEC.",
    ]
}

# Build conclusion string
if abs(dm_stat_x5) > 3.0 or abs(dm_stat_x3) > 3.0:
    sig_model = "X5" if abs(dm_stat_x5) >= abs(dm_stat_x3) else "X3"
    results["conclusion"] = (
        f"SIGNIFICANT: {sig_model} dummy improves volatility forecasts for 0050.TW OOS. "
        f"Taiwan price limits create measurable latent volatility. "
        f"QLIKE: Base={qlike_base:.4f}, X5={qlike_x5:.4f}, X3={qlike_x3:.4f}. "
        f"DM(Base vs X5) t={dm_stat_x5:.2f} p={p_x5:.4f}, "
        f"DM(Base vs X3) t={dm_stat_x3:.2f} p={p_x3:.4f}."
    )
elif limit5_days < 30:
    results["conclusion"] = (
        f"NULL RESULT (insufficient limit events): Only {limit5_days} days with |r|>5% "
        f"in full sample. Price limit effect untestable. "
        f"QLIKE Base={qlike_base:.4f} vs X5={qlike_x5:.4f}."
    )
else:
    results["conclusion"] = (
        f"NULL RESULT: Price limit dummy does NOT significantly improve GJR-GARCH forecasts. "
        f"QLIKE: Base={qlike_base:.4f}, X5={qlike_x5:.4f}, X3={qlike_x3:.4f}. "
        f"DM(Base vs X5) t={dm_stat_x5:.2f} p={p_x5:.4f}, "
        f"DM(Base vs X3) t={dm_stat_x3:.2f} p={p_x3:.4f}. "
        f"Limit events ({limit5_days} days @ >5%) are too infrequent or "
        f"their vol impact is already captured by GARCH asymmetry terms."
    )

print(f"\nConclusion: {results['conclusion']}")

out_path = os.path.join(os.path.dirname(__file__), "k790v2_taiwan_price_limit_results.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"\nResults saved to: {out_path}")
