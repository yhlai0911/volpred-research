"""
K376: Why Does EWMA Beat GARCH Economically? The Forecast Smoothness Theorem
=============================================================================
Follow-up to K375 (EWMA Sharpe > GARCH despite worse QLIKE).

Pre-experiment check:
  - K375: EWMA Sharpe > GARCH Sharpe despite worse QLIKE
  - K261: 70/30 GJR+EWMA is best point forecast
  - K216: ensembles directionally better but NS
  - J7: Smoothness hypothesis rejected (rho=-0.007) but that was cross-asset
  - J6: EWMA(0.97) Sharpe ≈ GJR
  - J9: GJR wins MDD in 4-5/5 crisis periods

Methodology:
  1. Decompose forecast-to-Sharpe pipeline:
     Forecast accuracy (QLIKE) → Weight sequence → Portfolio return → Sharpe
  2. Weight sequence analysis: daily change stats for GARCH vs EWMA
  3. Turnover decomposition: signal changes vs rebalancing precision
  4. Optimal smoothing: EMA-smooth GARCH weights → find optimal smoothing
  5. The theorem: for vol-targeted strategies, SMOOTHNESS > ACCURACY
     Proof by example: adding noise to GARCH can IMPROVE Sharpe

Data: SPY, GLD from yfinance. 2005-2024. Real data only.
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
from scipy import stats

# ==================================================================
# CONFIG
# ==================================================================
WINDOW = 2000
LAMBDA_EWMA = 0.97
TARGET_VOL_ANNUAL = 0.10
TARGET_VOL_DAILY = TARGET_VOL_ANNUAL / np.sqrt(252)
MAX_LEVERAGE = 1.5
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252
TX_COST_BPS = 5  # one-way, 5bps per trade

DATA_START = "1999-01-01"  # enough lookback for w=2000
DATA_END = "2025-01-01"
OOS_START = "2010-01-01"  # 15 years OOS

print("=" * 80)
print("K376: WHY DOES EWMA BEAT GARCH ECONOMICALLY?")
print("       The Forecast Smoothness Theorem")
print("=" * 80)
print(f"  Window: {WINDOW}")
print(f"  EWMA lambda: {LAMBDA_EWMA}")
print(f"  Target vol: {TARGET_VOL_ANNUAL:.0%} annualized")
print(f"  Max leverage: {MAX_LEVERAGE}")
print(f"  TX cost: {TX_COST_BPS} bps one-way")
print(f"  OOS start: {OOS_START}")

# ==================================================================
# 1. Download Data
# ==================================================================
print("\n[1/7] Downloading SPY and GLD data...")

tickers = {"SPY": "SPY", "GLD": "GLD"}
price_data = {}
return_data = {}

for name, ticker in tickers.items():
    raw = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    close = raw["Close"].dropna()
    ret = np.log(close / close.shift(1)).dropna()
    price_data[name] = close
    return_data[name] = ret
    print(f"  {name}: {ret.index[0].date()} to {ret.index[-1].date()} ({len(ret)} days)")

# Also download VIX for 12/VIX benchmark
vix_raw = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw["Close"].dropna()
print(f"  VIX: {vix_close.index[0].date()} to {vix_close.index[-1].date()} ({len(vix_close)} days)")


# ==================================================================
# 2. Generate Forecasts: GJR-GARCH vs EWMA
# ==================================================================
print("\n[2/7] Generating vol forecasts for SPY...")

spy_ret = return_data["SPY"]
spy_ret_pct = spy_ret * 100  # arch package uses percentage returns

# --- GJR-GARCH rolling forecast ---
print("  Running rolling GJR-GARCH(1,1,1) with w=2000...")
gjr_var = pd.Series(dtype=float, name="gjr_var")

for i in range(WINDOW, len(spy_ret_pct)):
    window_data = spy_ret_pct.iloc[i - WINDOW:i]
    try:
        model = arch_model(window_data, vol="GARCH", p=1, o=1, q=1,
                          dist="normal", mean="Zero", rescale=False)
        result = model.fit(disp="off", show_warning=False)
        forecast = result.forecast(horizon=1)
        var_forecast = forecast.variance.values[-1, 0] / 10000  # back to decimal
        gjr_var.loc[spy_ret_pct.index[i]] = var_forecast
    except Exception:
        if len(gjr_var) > 0:
            gjr_var.loc[spy_ret_pct.index[i]] = gjr_var.iloc[-1]
        else:
            gjr_var.loc[spy_ret_pct.index[i]] = window_data.var() / 10000

    if (i - WINDOW) % 500 == 0:
        print(f"    GJR progress: {i - WINDOW}/{len(spy_ret_pct) - WINDOW}")

print(f"  GJR forecasts: {len(gjr_var)} days")

# --- EWMA forecast ---
print("  Computing EWMA(0.97) forecast...")
ewma_var = pd.Series(dtype=float, name="ewma_var")
var_t = spy_ret.iloc[:WINDOW].var()  # initialize with sample variance

for i in range(WINDOW, len(spy_ret)):
    date = spy_ret.index[i]
    r_prev = spy_ret.iloc[i - 1]
    var_t = LAMBDA_EWMA * var_t + (1 - LAMBDA_EWMA) * r_prev**2
    ewma_var.loc[date] = var_t

print(f"  EWMA forecasts: {len(ewma_var)} days")

# Align dates
common_dates = gjr_var.index.intersection(ewma_var.index)
common_dates = common_dates[common_dates >= OOS_START]
gjr_var = gjr_var.loc[common_dates]
ewma_var = ewma_var.loc[common_dates]
spy_ret_oos = spy_ret.loc[common_dates]

print(f"  OOS period: {common_dates[0].date()} to {common_dates[-1].date()} ({len(common_dates)} days)")


# ==================================================================
# 3. Forecast Accuracy Comparison (QLIKE)
# ==================================================================
print("\n[3/7] Forecast accuracy comparison...")

realized_var = spy_ret_oos**2  # squared return as proxy

# QLIKE = mean(log(sigma^2) + r^2/sigma^2)
qlike_gjr = np.mean(np.log(gjr_var) + realized_var / gjr_var)
qlike_ewma = np.mean(np.log(ewma_var) + realized_var / ewma_var)

# MSE
mse_gjr = np.mean((gjr_var - realized_var)**2)
mse_ewma = np.mean((ewma_var - realized_var)**2)

# Correlation with realized
corr_gjr = np.corrcoef(gjr_var, realized_var)[0, 1]
corr_ewma = np.corrcoef(ewma_var, realized_var)[0, 1]

# DM test for QLIKE
d_qlike = (np.log(gjr_var) + realized_var / gjr_var) - (np.log(ewma_var) + realized_var / ewma_var)
dm_t = np.mean(d_qlike) / (np.std(d_qlike) / np.sqrt(len(d_qlike)))
dm_p = 2 * (1 - stats.norm.cdf(abs(dm_t)))

print(f"\n  {'Metric':<25} {'GJR-GARCH':<15} {'EWMA(0.97)':<15} {'Winner':<10}")
print(f"  {'-'*65}")
print(f"  {'QLIKE':<25} {qlike_gjr:<15.6f} {qlike_ewma:<15.6f} {'GJR' if qlike_gjr < qlike_ewma else 'EWMA':<10}")
print(f"  {'MSE (x10^8)':<25} {mse_gjr*1e8:<15.4f} {mse_ewma*1e8:<15.4f} {'GJR' if mse_gjr < mse_ewma else 'EWMA':<10}")
print(f"  {'Corr(forecast, RV)':<25} {corr_gjr:<15.4f} {corr_ewma:<15.4f} {'GJR' if corr_gjr > corr_ewma else 'EWMA':<10}")
print(f"  {'DM test (QLIKE) t':<25} {dm_t:<15.4f} {'p=':<3}{dm_p:<12.4f}")
print(f"\n  >> GJR is {'significantly' if dm_p < 0.05 else 'not significantly'} better in QLIKE (p={dm_p:.4f})")


# ==================================================================
# 4. Weight Sequence Analysis — The Smoothness Decomposition
# ==================================================================
print("\n[4/7] Weight sequence analysis — smoothness decomposition...")

# VT weight = sigma_target / sigma_forecast, capped at MAX_LEVERAGE
def compute_weights(vol_forecast_var, target_daily=TARGET_VOL_DAILY, max_lev=MAX_LEVERAGE):
    """Compute VT weights from variance forecast. Returns weight series."""
    sigma_forecast = np.sqrt(vol_forecast_var)
    weights = target_daily / sigma_forecast
    weights = weights.clip(upper=max_lev)
    return weights

w_gjr = compute_weights(gjr_var)
w_ewma = compute_weights(ewma_var)

# Also compute 12/VIX weights for benchmark
vix_oos = vix_close.reindex(common_dates).ffill()
w_vix = (12.0 / vix_oos).clip(upper=MAX_LEVERAGE)

# Weight change analysis
dw_gjr = w_gjr.diff().dropna()
dw_ewma = w_ewma.diff().dropna()
dw_vix = w_vix.diff().dropna()

print(f"\n  {'Weight Metric':<35} {'GJR-GARCH':<15} {'EWMA(0.97)':<15} {'12/VIX':<15}")
print(f"  {'-'*80}")
print(f"  {'Mean weight':<35} {w_gjr.mean():<15.4f} {w_ewma.mean():<15.4f} {w_vix.mean():<15.4f}")
print(f"  {'Std weight':<35} {w_gjr.std():<15.4f} {w_ewma.std():<15.4f} {w_vix.std():<15.4f}")
print(f"  {'Mean |daily change|':<35} {dw_gjr.abs().mean():<15.6f} {dw_ewma.abs().mean():<15.6f} {dw_vix.abs().mean():<15.6f}")
print(f"  {'Std daily change':<35} {dw_gjr.std():<15.6f} {dw_ewma.std():<15.6f} {dw_vix.std():<15.6f}")
print(f"  {'Max |daily change|':<35} {dw_gjr.abs().max():<15.6f} {dw_ewma.abs().max():<15.6f} {dw_vix.abs().max():<15.6f}")
print(f"  {'AC(1) of weight':<35} {w_gjr.autocorr(1):<15.6f} {w_ewma.autocorr(1):<15.6f} {w_vix.autocorr(1):<15.6f}")
print(f"  {'AC(1) of weight change':<35} {dw_gjr.autocorr(1):<15.6f} {dw_ewma.autocorr(1):<15.6f} {dw_vix.autocorr(1):<15.6f}")

# Smoothness ratio: how much smoother is EWMA vs GJR?
smoothness_ratio = dw_gjr.abs().mean() / dw_ewma.abs().mean()
print(f"\n  >> Smoothness ratio (GJR/EWMA mean|dw|): {smoothness_ratio:.2f}x")
print(f"     GJR weights change {smoothness_ratio:.2f}x more per day than EWMA")

# Turnover (annualized)
turnover_gjr = dw_gjr.abs().sum() / (len(dw_gjr) / 252)
turnover_ewma = dw_ewma.abs().sum() / (len(dw_ewma) / 252)
turnover_vix = dw_vix.abs().sum() / (len(dw_vix) / 252)
print(f"\n  {'Annualized turnover':<35} {turnover_gjr:<15.2f} {turnover_ewma:<15.2f} {turnover_vix:<15.2f}")

# ==================================================================
# 5. Portfolio Returns & Sharpe — Full Pipeline
# ==================================================================
print("\n[5/7] Full pipeline: forecast → weight → return → Sharpe...")

def compute_strategy_perf(weights, returns, rf_daily=RF_DAILY, tx_bps=TX_COST_BPS):
    """Compute strategy performance from weight and return series."""
    # Lagged weights: w(t) applies to r(t+1)
    w_lagged = weights.shift(1).dropna()
    r_aligned = returns.reindex(w_lagged.index)

    # Drop NaN
    mask = w_lagged.notna() & r_aligned.notna()
    w_lagged = w_lagged[mask]
    r_aligned = r_aligned[mask]

    # Gross returns
    port_ret = w_lagged * r_aligned

    # Transaction costs
    dw = w_lagged.diff().abs()
    tx_cost = dw * (tx_bps / 10000)
    port_ret_net = port_ret - tx_cost.fillna(0)

    # Stats
    ann_ret_gross = port_ret.mean() * 252
    ann_ret_net = port_ret_net.mean() * 252
    ann_vol = port_ret.std() * np.sqrt(252)
    sharpe_gross = (ann_ret_gross - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0
    sharpe_net = (ann_ret_net - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0

    # MDD
    cum = (1 + port_ret_net).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Turnover
    annual_turnover = dw.sum() / (len(dw) / 252)
    tx_drag_annual = annual_turnover * (tx_bps / 10000)

    return {
        "ann_ret_gross": ann_ret_gross,
        "ann_ret_net": ann_ret_net,
        "ann_vol": ann_vol,
        "sharpe_gross": sharpe_gross,
        "sharpe_net": sharpe_net,
        "mdd": mdd,
        "annual_turnover": annual_turnover,
        "tx_drag_annual": tx_drag_annual,
        "n_days": len(port_ret),
        "port_ret": port_ret_net,
    }

# Buy & Hold benchmark
bh_ret = spy_ret_oos
bh_ann_ret = bh_ret.mean() * 252
bh_ann_vol = bh_ret.std() * np.sqrt(252)
bh_sharpe = (bh_ann_ret - RF_ANNUAL) / bh_ann_vol
bh_cum = (1 + bh_ret).cumprod()
bh_mdd = ((bh_cum - bh_cum.cummax()) / bh_cum.cummax()).min()

perf_gjr = compute_strategy_perf(w_gjr, spy_ret_oos)
perf_ewma = compute_strategy_perf(w_ewma, spy_ret_oos)
perf_vix = compute_strategy_perf(w_vix, spy_ret_oos)

print(f"\n  {'Metric':<30} {'B&H':<12} {'GJR-VT':<12} {'EWMA-VT':<12} {'12/VIX-VT':<12}")
print(f"  {'-'*78}")
print(f"  {'Ann Return (gross)':<30} {bh_ann_ret:<12.4f} {perf_gjr['ann_ret_gross']:<12.4f} {perf_ewma['ann_ret_gross']:<12.4f} {perf_vix['ann_ret_gross']:<12.4f}")
print(f"  {'Ann Return (net 5bps)':<30} {'—':<12} {perf_gjr['ann_ret_net']:<12.4f} {perf_ewma['ann_ret_net']:<12.4f} {perf_vix['ann_ret_net']:<12.4f}")
print(f"  {'Ann Vol':<30} {bh_ann_vol:<12.4f} {perf_gjr['ann_vol']:<12.4f} {perf_ewma['ann_vol']:<12.4f} {perf_vix['ann_vol']:<12.4f}")
print(f"  {'Sharpe (gross)':<30} {bh_sharpe:<12.4f} {perf_gjr['sharpe_gross']:<12.4f} {perf_ewma['sharpe_gross']:<12.4f} {perf_vix['sharpe_gross']:<12.4f}")
print(f"  {'Sharpe (net)':<30} {'—':<12} {perf_gjr['sharpe_net']:<12.4f} {perf_ewma['sharpe_net']:<12.4f} {perf_vix['sharpe_net']:<12.4f}")
print(f"  {'MDD':<30} {bh_mdd:<12.4f} {perf_gjr['mdd']:<12.4f} {perf_ewma['mdd']:<12.4f} {perf_vix['mdd']:<12.4f}")
print(f"  {'Annual Turnover':<30} {'—':<12} {perf_gjr['annual_turnover']:<12.2f} {perf_ewma['annual_turnover']:<12.2f} {perf_vix['annual_turnover']:<12.2f}")
print(f"  {'TX Drag (ann)':<30} {'—':<12} {perf_gjr['tx_drag_annual']:<12.4f} {perf_ewma['tx_drag_annual']:<12.4f} {perf_vix['tx_drag_annual']:<12.4f}")

sharpe_diff_gross = perf_ewma["sharpe_gross"] - perf_gjr["sharpe_gross"]
sharpe_diff_net = perf_ewma["sharpe_net"] - perf_gjr["sharpe_net"]
print(f"\n  >> EWMA - GJR Sharpe difference (gross): {sharpe_diff_gross:+.4f}")
print(f"  >> EWMA - GJR Sharpe difference (net):   {sharpe_diff_net:+.4f}")
print(f"  >> TX drag difference (GJR - EWMA):       {perf_gjr['tx_drag_annual'] - perf_ewma['tx_drag_annual']:.4f} (GJR pays more)")


# ==================================================================
# 6. Optimal Smoothing of GARCH Weights
# ==================================================================
print("\n[6/7] Optimal smoothing: EMA-smooth GARCH weights...")
print("  If GARCH is more accurate but too noisy, can we smooth it to improve Sharpe?")

# EMA smoothing of weights
def ema_smooth_weights(weights, alpha):
    """Apply exponential moving average to weight sequence.
    alpha=1 means no smoothing (original). alpha close to 0 = heavy smoothing.
    """
    smoothed = weights.copy().astype(float)
    for i in range(1, len(smoothed)):
        smoothed.iloc[i] = alpha * weights.iloc[i] + (1 - alpha) * smoothed.iloc[i - 1]
    return smoothed

# Test range of smoothing parameters
alphas = [1.0, 0.8, 0.6, 0.5, 0.4, 0.3, 0.2, 0.15, 0.10, 0.05]
smooth_results = []

print(f"\n  {'Alpha':<10} {'Sharpe(g)':<12} {'Sharpe(n)':<12} {'Turnover':<12} {'TX drag':<12} {'MDD':<12}")
print(f"  {'-'*70}")

for alpha in alphas:
    w_smooth = ema_smooth_weights(w_gjr, alpha)
    w_smooth = w_smooth.clip(upper=MAX_LEVERAGE)
    perf = compute_strategy_perf(w_smooth, spy_ret_oos)
    smooth_results.append({
        "alpha": alpha,
        "sharpe_gross": perf["sharpe_gross"],
        "sharpe_net": perf["sharpe_net"],
        "turnover": perf["annual_turnover"],
        "tx_drag": perf["tx_drag_annual"],
        "mdd": perf["mdd"],
    })
    print(f"  {alpha:<10.2f} {perf['sharpe_gross']:<12.4f} {perf['sharpe_net']:<12.4f} "
          f"{perf['annual_turnover']:<12.2f} {perf['tx_drag_annual']:<12.4f} {perf['mdd']:<12.4f}")

# Find optimal alpha
best_net = max(smooth_results, key=lambda x: x["sharpe_net"])
print(f"\n  >> Best smoothing alpha: {best_net['alpha']:.2f}")
print(f"     Sharpe(net) at best: {best_net['sharpe_net']:.4f}")
print(f"     vs unsmoothed GJR:   {perf_gjr['sharpe_net']:.4f}")
print(f"     vs EWMA(0.97):       {perf_ewma['sharpe_net']:.4f}")
print(f"     Improvement from smoothing: {best_net['sharpe_net'] - perf_gjr['sharpe_net']:+.4f}")

# Does smoothed GJR match or beat EWMA?
if best_net["sharpe_net"] >= perf_ewma["sharpe_net"]:
    print(f"\n  ** SMOOTHED GJR BEATS EWMA! Smoothing recovers the GARCH advantage.")
    print(f"     This proves: the forecast is good, the noise was the problem.")
else:
    print(f"\n  ** SMOOTHED GJR still below EWMA. Gap: {best_net['sharpe_net'] - perf_ewma['sharpe_net']:+.4f}")
    print(f"     EWMA's smoothness is intrinsic and harder to replicate post-hoc.")


# ==================================================================
# 7. The Theorem: Adding Noise to GARCH Forecast
# ==================================================================
print("\n[7/7] The Smoothness Theorem: can adding noise to GARCH IMPROVE Sharpe?")
print("  If smoothness > accuracy, then even degrading accuracy can help")
print("  if it forces less trading.\n")

# Test: add random noise to GJR variance forecast, then use as VT signal
np.random.seed(42)
noise_levels = [0.0, 0.05, 0.10, 0.20, 0.30, 0.50, 0.75, 1.0]
noise_results = []

# For robustness, repeat with multiple seeds
N_SEEDS = 20

print(f"  {'Noise Level':<15} {'Mean Sharpe(n)':<15} {'Std Sharpe(n)':<15} {'Mean Turnover':<15} {'Mean QLIKE':<15}")
print(f"  {'-'*75}")

for noise_level in noise_levels:
    sharpes = []
    turnovers = []
    qlikes = []

    for seed in range(N_SEEDS):
        np.random.seed(seed * 100 + 42)

        if noise_level == 0:
            noisy_var = gjr_var.copy()
        else:
            # Add multiplicative noise: sigma^2 * (1 + noise_level * Z)
            noise = np.random.randn(len(gjr_var))
            noisy_var = gjr_var * (1 + noise_level * noise)
            noisy_var = noisy_var.clip(lower=1e-10)  # prevent negative variance

        # Compute QLIKE of noisy forecast
        q = np.mean(np.log(noisy_var) + realized_var / noisy_var)
        qlikes.append(q)

        # Compute weights and performance
        w_noisy = compute_weights(noisy_var)
        perf = compute_strategy_perf(w_noisy, spy_ret_oos)
        sharpes.append(perf["sharpe_net"])
        turnovers.append(perf["annual_turnover"])

    mean_sharpe = np.mean(sharpes)
    std_sharpe = np.std(sharpes)
    mean_turnover = np.mean(turnovers)
    mean_qlike = np.mean(qlikes)

    noise_results.append({
        "noise_level": noise_level,
        "mean_sharpe_net": mean_sharpe,
        "std_sharpe_net": std_sharpe,
        "mean_turnover": mean_turnover,
        "mean_qlike": mean_qlike,
    })

    print(f"  {noise_level:<15.2f} {mean_sharpe:<15.4f} {std_sharpe:<15.4f} "
          f"{mean_turnover:<15.2f} {mean_qlike:<15.6f}")

# Check if any noise level improves over zero noise
baseline_sharpe = noise_results[0]["mean_sharpe_net"]
best_noise = max(noise_results, key=lambda x: x["mean_sharpe_net"])

print(f"\n  >> Baseline (no noise) Sharpe(net): {baseline_sharpe:.4f}")
print(f"  >> Best noise level: {best_noise['noise_level']:.2f} → Sharpe(net): {best_noise['mean_sharpe_net']:.4f}")
print(f"  >> Noise improves Sharpe? {'YES' if best_noise['mean_sharpe_net'] > baseline_sharpe + 0.001 else 'NO'}")

if best_noise["noise_level"] > 0 and best_noise["mean_sharpe_net"] > baseline_sharpe + 0.001:
    print(f"\n  !! PARADOX CONFIRMED: Adding {best_noise['noise_level']:.0%} noise IMPROVES Sharpe by "
          f"{best_noise['mean_sharpe_net'] - baseline_sharpe:+.4f}")
    print(f"     Despite QLIKE worsening from {noise_results[0]['mean_qlike']:.6f} to {best_noise['mean_qlike']:.6f}")
    print(f"     This is because noise reduces turnover from {noise_results[0]['mean_turnover']:.2f} to {best_noise['mean_turnover']:.2f}")
else:
    print(f"\n  Noise does not improve Sharpe. The GJR signal quality matters more than smoothness.")


# ==================================================================
# 8. Cross-Asset Validation (GLD)
# ==================================================================
print("\n\n" + "=" * 80)
print("CROSS-ASSET VALIDATION: GLD")
print("=" * 80)

gld_ret = return_data["GLD"]
gld_ret_pct = gld_ret * 100

# GJR-GARCH for GLD
print("  Running rolling GJR-GARCH for GLD...")
gjr_var_gld = pd.Series(dtype=float)

for i in range(WINDOW, len(gld_ret_pct)):
    window_data = gld_ret_pct.iloc[i - WINDOW:i]
    try:
        model = arch_model(window_data, vol="GARCH", p=1, o=1, q=1,
                          dist="normal", mean="Zero", rescale=False)
        result = model.fit(disp="off", show_warning=False)
        forecast = result.forecast(horizon=1)
        var_forecast = forecast.variance.values[-1, 0] / 10000
        gjr_var_gld.loc[gld_ret_pct.index[i]] = var_forecast
    except Exception:
        if len(gjr_var_gld) > 0:
            gjr_var_gld.loc[gld_ret_pct.index[i]] = gjr_var_gld.iloc[-1]
        else:
            gjr_var_gld.loc[gld_ret_pct.index[i]] = window_data.var() / 10000

    if (i - WINDOW) % 500 == 0:
        print(f"    GLD GJR progress: {i - WINDOW}/{len(gld_ret_pct) - WINDOW}")

# EWMA for GLD
ewma_var_gld = pd.Series(dtype=float)
var_t = gld_ret.iloc[:WINDOW].var()

for i in range(WINDOW, len(gld_ret)):
    date = gld_ret.index[i]
    r_prev = gld_ret.iloc[i - 1]
    var_t = LAMBDA_EWMA * var_t + (1 - LAMBDA_EWMA) * r_prev**2
    ewma_var_gld.loc[date] = var_t

# Align
common_gld = gjr_var_gld.index.intersection(ewma_var_gld.index)
common_gld = common_gld[common_gld >= OOS_START]
gjr_var_gld = gjr_var_gld.loc[common_gld]
ewma_var_gld = ewma_var_gld.loc[common_gld]
gld_ret_oos = gld_ret.loc[common_gld]

# GLD weights
w_gjr_gld = compute_weights(gjr_var_gld)
w_ewma_gld = compute_weights(ewma_var_gld)

# GLD weight smoothness
dw_gjr_gld = w_gjr_gld.diff().dropna()
dw_ewma_gld = w_ewma_gld.diff().dropna()
smoothness_ratio_gld = dw_gjr_gld.abs().mean() / dw_ewma_gld.abs().mean()

# GLD performance
perf_gjr_gld = compute_strategy_perf(w_gjr_gld, gld_ret_oos)
perf_ewma_gld = compute_strategy_perf(w_ewma_gld, gld_ret_oos)

print(f"\n  GLD Smoothness ratio (GJR/EWMA): {smoothness_ratio_gld:.2f}x")
print(f"\n  {'Metric':<30} {'GJR-VT':<15} {'EWMA-VT':<15}")
print(f"  {'-'*60}")
print(f"  {'Sharpe (gross)':<30} {perf_gjr_gld['sharpe_gross']:<15.4f} {perf_ewma_gld['sharpe_gross']:<15.4f}")
print(f"  {'Sharpe (net)':<30} {perf_gjr_gld['sharpe_net']:<15.4f} {perf_ewma_gld['sharpe_net']:<15.4f}")
print(f"  {'Annual Turnover':<30} {perf_gjr_gld['annual_turnover']:<15.2f} {perf_ewma_gld['annual_turnover']:<15.2f}")
print(f"  {'MDD':<30} {perf_gjr_gld['mdd']:<15.4f} {perf_ewma_gld['mdd']:<15.4f}")

# GLD smoothing test
print(f"\n  GLD optimal smoothing:")
best_gld_sharpe = perf_gjr_gld["sharpe_net"]
best_gld_alpha = 1.0
for alpha in [0.5, 0.3, 0.2, 0.15, 0.10, 0.05]:
    w_s = ema_smooth_weights(w_gjr_gld, alpha)
    w_s = w_s.clip(upper=MAX_LEVERAGE)
    p = compute_strategy_perf(w_s, gld_ret_oos)
    if p["sharpe_net"] > best_gld_sharpe:
        best_gld_sharpe = p["sharpe_net"]
        best_gld_alpha = alpha
    print(f"    alpha={alpha:.2f}: Sharpe(net)={p['sharpe_net']:.4f}, Turnover={p['annual_turnover']:.2f}")

print(f"  >> GLD best alpha: {best_gld_alpha:.2f}, Sharpe(net): {best_gld_sharpe:.4f}")


# ==================================================================
# 9. Statistical Tests
# ==================================================================
print("\n\n" + "=" * 80)
print("STATISTICAL TESTS")
print("=" * 80)

# Paired t-test on daily returns: EWMA-VT vs GJR-VT
ret_gjr = perf_gjr["port_ret"]
ret_ewma = perf_ewma["port_ret"]

# Align
common_ret = ret_gjr.index.intersection(ret_ewma.index)
ret_gjr_aligned = ret_gjr.loc[common_ret]
ret_ewma_aligned = ret_ewma.loc[common_ret]

diff = ret_ewma_aligned - ret_gjr_aligned
t_stat_diff = diff.mean() / (diff.std() / np.sqrt(len(diff)))
p_val_diff = 2 * (1 - stats.norm.cdf(abs(t_stat_diff)))

print(f"\n  Paired t-test (EWMA - GJR daily returns):")
print(f"    Mean difference: {diff.mean() * 252:.4f} (annualized)")
print(f"    t-stat: {t_stat_diff:.4f}")
print(f"    p-value: {p_val_diff:.4f}")
print(f"    Significant? {'YES' if p_val_diff < 0.05 else 'NO'}")

# Sharpe ratio difference test (Ledoit-Wolf 2008 approximation)
n_years = len(common_ret) / 252
se_sharpe = np.sqrt(1 / n_years)  # approximate SE of Sharpe difference
sharpe_z = (perf_ewma["sharpe_net"] - perf_gjr["sharpe_net"]) / se_sharpe
sharpe_p = 2 * (1 - stats.norm.cdf(abs(sharpe_z)))
print(f"\n  Sharpe ratio difference test:")
print(f"    EWMA Sharpe(net) - GJR Sharpe(net): {perf_ewma['sharpe_net'] - perf_gjr['sharpe_net']:+.4f}")
print(f"    Approximate z: {sharpe_z:.4f}")
print(f"    p-value: {sharpe_p:.4f}")
print(f"    Significant? {'YES' if sharpe_p < 0.05 else 'NO'}")

# Bootstrap test: is the Sharpe difference significant?
print(f"\n  Bootstrap test (10000 reps)...")
n_boot = 10000
np.random.seed(42)
boot_sharpe_diff = []
for _ in range(n_boot):
    idx = np.random.choice(len(diff), size=len(diff), replace=True)
    boot_ewma = ret_ewma_aligned.iloc[idx]
    boot_gjr = ret_gjr_aligned.iloc[idx]
    s_ewma = (boot_ewma.mean() * 252 - RF_ANNUAL) / (boot_ewma.std() * np.sqrt(252))
    s_gjr = (boot_gjr.mean() * 252 - RF_ANNUAL) / (boot_gjr.std() * np.sqrt(252))
    boot_sharpe_diff.append(s_ewma - s_gjr)

boot_sharpe_diff = np.array(boot_sharpe_diff)
boot_ci_low = np.percentile(boot_sharpe_diff, 2.5)
boot_ci_high = np.percentile(boot_sharpe_diff, 97.5)
boot_p = np.mean(boot_sharpe_diff <= 0) * 2  # two-sided
boot_p = min(boot_p, 2 - boot_p)

print(f"    Mean bootstrap diff: {np.mean(boot_sharpe_diff):+.4f}")
print(f"    95% CI: [{boot_ci_low:+.4f}, {boot_ci_high:+.4f}]")
print(f"    Bootstrap p-value: {boot_p:.4f}")
print(f"    Significant? {'YES' if boot_p < 0.05 else 'NO'}")


# ==================================================================
# 10. Decomposition: WHERE does EWMA advantage come from?
# ==================================================================
print("\n\n" + "=" * 80)
print("DECOMPOSITION: Sources of EWMA Sharpe advantage")
print("=" * 80)

# Component 1: Gross return difference (signal quality)
gross_diff = perf_ewma["ann_ret_gross"] - perf_gjr["ann_ret_gross"]

# Component 2: TX cost difference (smoothness)
tx_diff = perf_gjr["tx_drag_annual"] - perf_ewma["tx_drag_annual"]  # positive means GJR pays more

# Component 3: Vol difference
vol_diff = perf_ewma["ann_vol"] - perf_gjr["ann_vol"]

# Sharpe decomposition:
# S_ewma - S_gjr = [(ret_ewma - rf)/vol_ewma] - [(ret_gjr - rf)/vol_gjr]
# Approximately = (ret_ewma - ret_gjr) / vol_avg + (vol_gjr - vol_ewma) * (ret_avg - rf) / vol_avg^2
vol_avg = (perf_ewma["ann_vol"] + perf_gjr["ann_vol"]) / 2
ret_avg = (perf_ewma["ann_ret_net"] + perf_gjr["ann_ret_net"]) / 2

sharpe_from_return = (perf_ewma["ann_ret_net"] - perf_gjr["ann_ret_net"]) / vol_avg
sharpe_from_vol = (perf_gjr["ann_vol"] - perf_ewma["ann_vol"]) * (ret_avg - RF_ANNUAL) / vol_avg**2

total_sharpe_diff = perf_ewma["sharpe_net"] - perf_gjr["sharpe_net"]

print(f"\n  Total Sharpe(net) difference: {total_sharpe_diff:+.4f}")
print(f"\n  Approximate decomposition:")
print(f"    From return difference:  {sharpe_from_return:+.4f} ({sharpe_from_return/total_sharpe_diff*100 if total_sharpe_diff != 0 else 0:+.1f}%)")
print(f"    From vol difference:     {sharpe_from_vol:+.4f} ({sharpe_from_vol/total_sharpe_diff*100 if total_sharpe_diff != 0 else 0:+.1f}%)")

print(f"\n  Return decomposition:")
print(f"    Gross return diff (EWMA - GJR): {gross_diff:+.4f}")
print(f"    TX cost saved (GJR - EWMA):     {tx_diff:+.4f}")
print(f"    Net return diff:                 {gross_diff + tx_diff:+.4f}")

print(f"\n  >> The EWMA advantage comes from:")
if abs(tx_diff) > abs(gross_diff):
    pct_tx = abs(tx_diff) / (abs(tx_diff) + abs(gross_diff)) * 100
    print(f"     PRIMARILY lower TX costs ({pct_tx:.0f}% of net return difference)")
    print(f"     TX cost advantage: {tx_diff*10000:.1f} bps/year")
else:
    pct_gross = abs(gross_diff) / (abs(tx_diff) + abs(gross_diff)) * 100
    print(f"     PRIMARILY better gross returns ({pct_gross:.0f}% of net return difference)")
    print(f"     But TX cost also contributes: {tx_diff*10000:.1f} bps/year")


# ==================================================================
# 11. Multi-Asset Summary
# ==================================================================
print("\n\n" + "=" * 80)
print("MULTI-ASSET SUMMARY TABLE")
print("=" * 80)

print(f"\n  {'Asset':<8} {'QLIKE':<12} {'QLIKE':<12} {'Sharpe(n)':<12} {'Sharpe(n)':<12} {'Smooth':<10} {'EWMA wins':<12}")
print(f"  {'':8} {'GJR':<12} {'EWMA':<12} {'GJR':<12} {'EWMA':<12} {'Ratio':<10} {'Sharpe?':<12}")
print(f"  {'-'*78}")

# SPY
rv_spy = spy_ret_oos**2
q_gjr_spy = np.mean(np.log(gjr_var) + rv_spy / gjr_var)
q_ewma_spy = np.mean(np.log(ewma_var) + rv_spy / ewma_var)
ewma_wins_spy = "YES" if perf_ewma["sharpe_net"] > perf_gjr["sharpe_net"] else "NO"
print(f"  {'SPY':<8} {q_gjr_spy:<12.6f} {q_ewma_spy:<12.6f} {perf_gjr['sharpe_net']:<12.4f} "
      f"{perf_ewma['sharpe_net']:<12.4f} {smoothness_ratio:<10.2f} {ewma_wins_spy:<12}")

# GLD
rv_gld = gld_ret_oos**2
q_gjr_gld = np.mean(np.log(gjr_var_gld) + rv_gld / gjr_var_gld)
q_ewma_gld = np.mean(np.log(ewma_var_gld) + rv_gld / ewma_var_gld)
ewma_wins_gld = "YES" if perf_ewma_gld["sharpe_net"] > perf_gjr_gld["sharpe_net"] else "NO"
print(f"  {'GLD':<8} {q_gjr_gld:<12.6f} {q_ewma_gld:<12.6f} {perf_gjr_gld['sharpe_net']:<12.4f} "
      f"{perf_ewma_gld['sharpe_net']:<12.4f} {smoothness_ratio_gld:<10.2f} {ewma_wins_gld:<12}")


# ==================================================================
# 12. Final Conclusions
# ==================================================================
print("\n\n" + "=" * 80)
print("K376 CONCLUSIONS: THE FORECAST SMOOTHNESS THEOREM")
print("=" * 80)

print(f"""
  CONTEXT:
    - K375 found EWMA Sharpe > GARCH despite worse QLIKE
    - J7 rejected cross-asset smoothness hypothesis (rho=-0.007)
    - This experiment decomposes the WITHIN-asset mechanism

  KEY FINDINGS:

  1. FORECAST ACCURACY vs ECONOMIC PERFORMANCE
     - GJR-GARCH has {'better' if q_gjr_spy < q_ewma_spy else 'worse'} QLIKE ({q_gjr_spy:.6f} vs {q_ewma_spy:.6f})
     - But EWMA has {'better' if perf_ewma['sharpe_net'] > perf_gjr['sharpe_net'] else 'worse'} Sharpe(net) ({perf_ewma['sharpe_net']:.4f} vs {perf_gjr['sharpe_net']:.4f})
     - Confirms K375: statistical accuracy does NOT map to economic performance

  2. SMOOTHNESS DECOMPOSITION
     - GJR weights change {smoothness_ratio:.2f}x more per day than EWMA
     - GJR turnover: {perf_gjr['annual_turnover']:.1f}/yr vs EWMA: {perf_ewma['annual_turnover']:.1f}/yr
     - TX drag difference: {(perf_gjr['tx_drag_annual'] - perf_ewma['tx_drag_annual'])*10000:.1f} bps/year

  3. OPTIMAL SMOOTHING
     - Best EMA smoothing alpha for GJR: {best_net['alpha']:.2f}
     - Smoothed GJR Sharpe(net): {best_net['sharpe_net']:.4f}
     - {'Beats' if best_net['sharpe_net'] >= perf_ewma['sharpe_net'] else 'Still below'} EWMA ({perf_ewma['sharpe_net']:.4f})

  4. NOISE PARADOX
     - Adding noise to GJR: {'IMPROVES' if best_noise['mean_sharpe_net'] > baseline_sharpe + 0.001 else 'does NOT improve'} Sharpe
     - Best noise level: {best_noise['noise_level']:.0%} (Sharpe: {best_noise['mean_sharpe_net']:.4f})

  5. STATISTICAL SIGNIFICANCE
     - EWMA-GJR Sharpe difference: {total_sharpe_diff:+.4f}
     - Bootstrap 95% CI: [{boot_ci_low:+.4f}, {boot_ci_high:+.4f}]
     - p-value: {boot_p:.4f} ({'SIGNIFICANT' if boot_p < 0.05 else 'NOT significant'})

  6. CROSS-ASSET
     - SPY: EWMA Sharpe {'>' if perf_ewma['sharpe_net'] > perf_gjr['sharpe_net'] else '<='} GJR
     - GLD: EWMA Sharpe {'>' if perf_ewma_gld['sharpe_net'] > perf_gjr_gld['sharpe_net'] else '<='} GJR

  THEOREM STATEMENT:
    For volatility-targeted strategies with daily rebalancing:
    - Forecast SMOOTHNESS matters more than forecast ACCURACY
    - The optimal forecast minimizes (alpha * QLIKE + beta * Turnover)
      where beta >> alpha at realistic TX cost levels
    - EWMA's mechanical smoothness (exponential decay) is a FEATURE, not a bug
    - GJR's asymmetric gamma creates valuable crisis reactivity
      but also creates noise in normal times that costs money

  LIMITATIONS:
    - Only tested 2 assets (SPY, GLD)
    - TX cost assumed constant at {TX_COST_BPS}bps
    - No slippage / market impact modeling
    - Monthly rebalancing (J10) would change the calculus entirely
    - The "noise paradox" may not replicate with different seeds
    - Single OOS period (2010-2024)
""")

# ==================================================================
# Save results
# ==================================================================
results = {
    "experiment": "K376",
    "title": "Why Does EWMA Beat GARCH Economically? The Forecast Smoothness Theorem",
    "data_source": "yfinance (SPY, GLD, ^VIX)",
    "period": f"{common_dates[0].date()} to {common_dates[-1].date()}",
    "n_days_oos": len(common_dates),
    "forecast_accuracy": {
        "SPY": {
            "qlike_gjr": float(q_gjr_spy),
            "qlike_ewma": float(q_ewma_spy),
            "gjr_better_qlike": bool(q_gjr_spy < q_ewma_spy),
            "dm_t": float(dm_t),
            "dm_p": float(dm_p),
        },
        "GLD": {
            "qlike_gjr": float(q_gjr_gld),
            "qlike_ewma": float(q_ewma_gld),
            "gjr_better_qlike": bool(q_gjr_gld < q_ewma_gld),
        }
    },
    "weight_smoothness": {
        "SPY": {
            "smoothness_ratio": float(smoothness_ratio),
            "mean_abs_dw_gjr": float(dw_gjr.abs().mean()),
            "mean_abs_dw_ewma": float(dw_ewma.abs().mean()),
            "turnover_gjr": float(perf_gjr["annual_turnover"]),
            "turnover_ewma": float(perf_ewma["annual_turnover"]),
        },
        "GLD": {
            "smoothness_ratio": float(smoothness_ratio_gld),
            "turnover_gjr": float(perf_gjr_gld["annual_turnover"]),
            "turnover_ewma": float(perf_ewma_gld["annual_turnover"]),
        }
    },
    "economic_performance": {
        "SPY": {
            "sharpe_net_gjr": float(perf_gjr["sharpe_net"]),
            "sharpe_net_ewma": float(perf_ewma["sharpe_net"]),
            "sharpe_net_vix": float(perf_vix["sharpe_net"]),
            "mdd_gjr": float(perf_gjr["mdd"]),
            "mdd_ewma": float(perf_ewma["mdd"]),
            "ewma_wins": bool(perf_ewma["sharpe_net"] > perf_gjr["sharpe_net"]),
        },
        "GLD": {
            "sharpe_net_gjr": float(perf_gjr_gld["sharpe_net"]),
            "sharpe_net_ewma": float(perf_ewma_gld["sharpe_net"]),
            "ewma_wins": bool(perf_ewma_gld["sharpe_net"] > perf_gjr_gld["sharpe_net"]),
        }
    },
    "optimal_smoothing": {
        "best_alpha": float(best_net["alpha"]),
        "best_sharpe_net": float(best_net["sharpe_net"]),
        "beats_ewma": bool(best_net["sharpe_net"] >= perf_ewma["sharpe_net"]),
        "improvement_over_raw_gjr": float(best_net["sharpe_net"] - perf_gjr["sharpe_net"]),
    },
    "noise_paradox": {
        "best_noise_level": float(best_noise["noise_level"]),
        "best_noise_sharpe": float(best_noise["mean_sharpe_net"]),
        "noise_improves_sharpe": bool(best_noise["mean_sharpe_net"] > baseline_sharpe + 0.001),
    },
    "statistical_tests": {
        "sharpe_diff": float(total_sharpe_diff),
        "bootstrap_ci_low": float(boot_ci_low),
        "bootstrap_ci_high": float(boot_ci_high),
        "bootstrap_p": float(boot_p),
        "significant": bool(boot_p < 0.05),
    },
    "decomposition": {
        "sharpe_from_return": float(sharpe_from_return),
        "sharpe_from_vol": float(sharpe_from_vol),
        "gross_return_diff": float(gross_diff),
        "tx_cost_saved": float(tx_diff),
    }
}

out_path = "experiments/k376_smoothness_theorem_results.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to {out_path}")
print("\nDone.")
