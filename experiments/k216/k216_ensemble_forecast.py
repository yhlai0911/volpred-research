"""
K216: Optimal Ensemble of Volatility Forecasters
=================================================

Hypothesis:
  Forecast combination (Granger-Ramanathan 1984, Timmermann 2006) often beats
  individual forecasters even when those individuals are roughly equivalent.
  Can an optimal combination of GJR-GARCH, EWMA, rolling variance, VIX-implied,
  and Parkinson range beat any single model?

Method:
  1. Six individual forecasters (rolling estimation, daily):
     a) GJR-GARCH(1,1,1) h_t, window=2000
     b) EWMA(lambda=0.94), window=500
     c) EWMA(lambda=0.97), window=500
     d) Simple 22-day rolling variance
     e) VIX^2/252 (implied vol squared, annualized to daily)
     f) Parkinson range estimator (22-day rolling)
  2. Four combination methods:
     a) Equal weight (1/N)
     b) Inverse QLIKE weight (rolling 252-day, better models get more weight)
     c) OLS combination (Granger-Ramanathan: RV = sum(beta_i * forecast_i) + eps, rolling 252d)
     d) Trimmed mean (drop highest and lowest forecast, average remaining)
  3. Evaluation:
     - OOS QLIKE for each individual and each combination
     - DM test: combination vs best individual (GJR-GARCH baseline)
     - Cross-asset comparison (SPY, QQQ, GLD, TLT)
  4. Statistical requirements: DM test, Harvey threshold (t>3.0), cross-asset

Data: SPY, QQQ, GLD, TLT daily from yfinance. OOS: 2023-01-01 to 2024-12-31.

Literature:
  - Granger & Ramanathan (1984): improved combination of forecasts
  - Timmermann (2006): Handbook of Economic Forecasting, ch. on forecast combinations
  - Patton (2011): QLIKE is proxy-robust loss function
  - Hansen et al. (2011): Model Confidence Set

[提出: 用戶, 執行: Claude]
"""

import json
import sys
import time
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
OOS_END = "2024-12-31"
GARCH_WINDOW = 2000
OTHER_WINDOW = 500
COMBO_WINDOW = 252  # Rolling window for combination weight estimation
PARKINSON_WINDOW = 22
RV_WINDOW = 22

ASSETS = {
    "SPY": "SPY",
    "QQQ": "QQQ",
    "GLD": "GLD",
    "TLT": "TLT",
}

print("=" * 80)
print("K216: OPTIMAL ENSEMBLE OF VOLATILITY FORECASTERS")
print("Can combining GJR-GARCH, EWMA, RV, VIX, Parkinson beat any single model?")
print("=" * 80)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def qlike_loss(realized, forecast):
    """QLIKE loss: sum(log(h) + r^2/h). Lower is better."""
    mask = (forecast > 0) & np.isfinite(realized) & np.isfinite(forecast) & (realized >= 0)
    r2 = realized[mask]
    h = forecast[mask]
    return np.mean(np.log(h) + r2 / h)


def dm_test(loss1, loss2, h=1):
    """
    Diebold-Mariano test. H0: equal predictive accuracy.
    Returns (t-stat, p-value). Negative t-stat means loss1 < loss2 (model 1 better).
    """
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan
    d_mean = np.mean(d)
    # Newey-West variance with h-1 lags
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k], ddof=1)[0, 1]
        gamma_sum += 2 * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return np.nan, np.nan
    t_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * stats.t.cdf(-abs(t_stat), df=n - 1)
    return t_stat, p_value


def qlike_loss_series(realized, forecast):
    """Element-wise QLIKE loss for DM test."""
    mask = (forecast > 0) & np.isfinite(realized) & np.isfinite(forecast) & (realized >= 0)
    out = np.full_like(realized, np.nan, dtype=float)
    out[mask] = np.log(forecast[mask]) + realized[mask] / forecast[mask]
    return out


# ============================================================
# INDIVIDUAL FORECASTERS
# ============================================================

def forecast_gjr_garch(returns, oos_mask, window=2000):
    """GJR-GARCH(1,1,1) rolling window forecast."""
    n = len(returns)
    forecasts = np.full(n, np.nan)
    ret_vals = returns.values * 100  # scale for arch

    oos_indices = np.where(oos_mask)[0]
    total = len(oos_indices)

    for count, t in enumerate(oos_indices):
        if t < window:
            continue
        try:
            train = ret_vals[t - window:t]
            am = arch_model(train, vol='Garch', p=1, o=1, q=1, dist='normal', mean='Zero')
            res = am.fit(disp='off', show_warning=False)
            fc = res.forecast(horizon=1)
            h = fc.variance.values[-1, 0] / 10000  # back to decimal
            if h > 0 and np.isfinite(h):
                forecasts[t] = h
        except Exception:
            pass

        if (count + 1) % 100 == 0:
            print(f"    GJR-GARCH: {count + 1}/{total}", end='\r')

    print(f"    GJR-GARCH: {total}/{total} done")
    return forecasts


def forecast_ewma(returns, lam, oos_mask, window=500):
    """EWMA variance forecast."""
    n = len(returns)
    forecasts = np.full(n, np.nan)
    r2 = (returns.values) ** 2

    oos_indices = np.where(oos_mask)[0]
    for t in oos_indices:
        if t < window:
            continue
        # Initialize with sample variance
        train_r2 = r2[t - window:t]
        var_t = train_r2[0]
        for i in range(1, len(train_r2)):
            var_t = lam * var_t + (1 - lam) * train_r2[i]
        forecasts[t] = var_t

    return forecasts


def forecast_rolling_var(returns, oos_mask, window=22):
    """Simple rolling variance (22-day)."""
    n = len(returns)
    forecasts = np.full(n, np.nan)
    r2 = (returns.values) ** 2

    oos_indices = np.where(oos_mask)[0]
    for t in oos_indices:
        if t < window:
            continue
        forecasts[t] = np.mean(r2[t - window:t])

    return forecasts


def forecast_vix_implied(vix_series, oos_mask):
    """VIX^2 / 252 as daily implied variance forecast."""
    n = len(vix_series)
    forecasts = np.full(n, np.nan)

    oos_indices = np.where(oos_mask)[0]
    for t in oos_indices:
        if t < 1:
            continue
        # Use previous day's VIX to avoid look-ahead
        v = vix_series.iloc[t - 1]
        if np.isfinite(v) and v > 0:
            forecasts[t] = (v / 100) ** 2 / 252

    return forecasts


def forecast_parkinson(high, low, oos_mask, window=22):
    """Parkinson range-based variance estimator (rolling)."""
    n = len(high)
    forecasts = np.full(n, np.nan)

    # Parkinson: sigma^2 = (1/(4*n*ln2)) * sum(ln(H/L))^2
    log_hl = np.log(high.values / low.values)

    oos_indices = np.where(oos_mask)[0]
    for t in oos_indices:
        if t < window:
            continue
        lhl = log_hl[t - window:t]
        valid = lhl[np.isfinite(lhl) & (lhl > 0)]
        if len(valid) >= window // 2:
            forecasts[t] = np.sum(valid ** 2) / (4 * len(valid) * np.log(2))

    return forecasts


# ============================================================
# COMBINATION METHODS
# ============================================================

def combine_equal_weight(forecasts_dict, oos_mask):
    """1/N equal weight combination."""
    keys = list(forecasts_dict.keys())
    n = len(forecasts_dict[keys[0]])
    combined = np.full(n, np.nan)

    oos_indices = np.where(oos_mask)[0]
    for t in oos_indices:
        vals = [forecasts_dict[k][t] for k in keys if np.isfinite(forecasts_dict[k][t]) and forecasts_dict[k][t] > 0]
        if len(vals) >= 2:
            combined[t] = np.mean(vals)

    return combined


def combine_inverse_qlike(forecasts_dict, realized, oos_mask, lookback=252):
    """Inverse QLIKE weight: models with lower recent QLIKE get higher weight."""
    keys = list(forecasts_dict.keys())
    n = len(realized)
    combined = np.full(n, np.nan)

    oos_indices = np.where(oos_mask)[0]
    for t in oos_indices:
        if t < lookback:
            continue

        # Compute rolling QLIKE for each model over lookback window
        weights = {}
        ql_values = {}
        for k in keys:
            h_window = forecasts_dict[k][t - lookback:t]
            r_window = realized[t - lookback:t]
            valid_mask = (h_window > 0) & np.isfinite(h_window) & np.isfinite(r_window) & (r_window >= 0)
            if np.sum(valid_mask) >= lookback // 2:
                ql = np.mean(np.log(h_window[valid_mask]) + r_window[valid_mask] / h_window[valid_mask])
                if np.isfinite(ql):
                    ql_values[k] = ql

        # Use exp(-ql) as weight: lower QLIKE = higher weight (works for negative QLIKE too)
        if len(ql_values) >= 2:
            # Shift to make all positive for numerical stability
            min_ql = min(ql_values.values())
            for k in ql_values:
                weights[k] = np.exp(-(ql_values[k] - min_ql))  # relative inverse

        if len(weights) >= 2:
            total_w = sum(weights.values())
            forecast_val = sum(weights[k] / total_w * forecasts_dict[k][t]
                             for k in weights
                             if np.isfinite(forecasts_dict[k][t]) and forecasts_dict[k][t] > 0)
            if forecast_val > 0:
                combined[t] = forecast_val

    return combined


def combine_ols(forecasts_dict, realized, oos_mask, lookback=252):
    """
    OLS combination (Granger-Ramanathan):
    RV_t = sum(beta_i * forecast_i_t) + epsilon_t
    Rolling 252-day estimation, constrained beta >= 0.
    """
    keys = list(forecasts_dict.keys())
    n = len(realized)
    combined = np.full(n, np.nan)

    oos_indices = np.where(oos_mask)[0]
    for t in oos_indices:
        if t < lookback:
            continue

        # Build X matrix and y vector from lookback window
        y = realized[t - lookback:t]
        X = np.column_stack([forecasts_dict[k][t - lookback:t] for k in keys])

        # Filter valid rows
        valid = np.all(np.isfinite(X), axis=1) & np.isfinite(y) & (y >= 0) & np.all(X > 0, axis=1)
        if np.sum(valid) < len(keys) + 5:
            continue

        y_v = y[valid]
        X_v = X[valid]

        try:
            # OLS: beta = (X'X)^-1 X'y
            beta = np.linalg.lstsq(X_v, y_v, rcond=None)[0]

            # Clip negative weights to 0 and renormalize
            beta = np.maximum(beta, 0)
            if np.sum(beta) > 0:
                beta = beta / np.sum(beta)  # normalize to sum=1

                # Apply to current forecasts
                current = np.array([forecasts_dict[k][t] for k in keys])
                if np.all(np.isfinite(current)) and np.all(current > 0):
                    combined[t] = np.dot(beta, current)
        except Exception:
            pass

    return combined


def combine_trimmed_mean(forecasts_dict, oos_mask):
    """Trimmed mean: drop highest and lowest, average the rest."""
    keys = list(forecasts_dict.keys())
    n = len(forecasts_dict[keys[0]])
    combined = np.full(n, np.nan)

    oos_indices = np.where(oos_mask)[0]
    for t in oos_indices:
        vals = [forecasts_dict[k][t] for k in keys if np.isfinite(forecasts_dict[k][t]) and forecasts_dict[k][t] > 0]
        if len(vals) >= 4:  # Need at least 4 to trim top and bottom
            vals_sorted = sorted(vals)
            trimmed = vals_sorted[1:-1]  # drop min and max
            combined[t] = np.mean(trimmed)
        elif len(vals) >= 2:
            combined[t] = np.mean(vals)

    return combined


# ============================================================
# MAIN EXPERIMENT
# ============================================================

results = {}
all_details = {}

for asset_name, ticker in ASSETS.items():
    print(f"\n{'='*60}")
    print(f"  Asset: {asset_name} ({ticker})")
    print(f"{'='*60}")

    t0 = time.time()

    # --- Download data ---
    print(f"  Downloading {ticker} + VIX...")
    df = yf.download(ticker, start=DATA_START, end=DATA_END, auto_adjust=True, progress=False)
    vix_df = yf.download("^VIX", start=DATA_START, end=DATA_END, auto_adjust=True, progress=False)

    if df.empty:
        print(f"  ERROR: No data for {ticker}")
        continue

    # Handle MultiIndex columns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if isinstance(vix_df.columns, pd.MultiIndex):
        vix_df.columns = vix_df.columns.get_level_values(0)

    # Compute returns
    df['Return'] = df['Close'].pct_change()
    df = df.dropna(subset=['Return'])

    # Realized variance proxy: r^2
    df['RV'] = df['Return'] ** 2

    # Merge VIX
    df['VIX'] = vix_df['Close'].reindex(df.index).ffill()

    # OOS mask (numpy array for consistent use)
    oos_mask = np.array((df.index >= OOS_START) & (df.index <= OOS_END))
    oos_count = oos_mask.sum()
    print(f"  Total obs: {len(df)}, OOS obs: {oos_count}")

    if oos_count < 100:
        print(f"  ERROR: Not enough OOS data for {asset_name}")
        continue

    # --- Individual forecasters ---
    print(f"\n  Computing individual forecasters...")
    forecasts = {}

    # 1. GJR-GARCH
    print(f"  [1/6] GJR-GARCH(1,1,1) w={GARCH_WINDOW}...")
    forecasts['GJR-GARCH'] = forecast_gjr_garch(df['Return'], oos_mask, window=GARCH_WINDOW)

    # 2. EWMA(0.94)
    print(f"  [2/6] EWMA(0.94) w={OTHER_WINDOW}...")
    forecasts['EWMA_094'] = forecast_ewma(df['Return'], 0.94, oos_mask, window=OTHER_WINDOW)

    # 3. EWMA(0.97)
    print(f"  [3/6] EWMA(0.97) w={OTHER_WINDOW}...")
    forecasts['EWMA_097'] = forecast_ewma(df['Return'], 0.97, oos_mask, window=OTHER_WINDOW)

    # 4. Rolling 22d variance
    print(f"  [4/6] Rolling 22d variance...")
    forecasts['RollingVar22'] = forecast_rolling_var(df['Return'], oos_mask, window=RV_WINDOW)

    # 5. VIX implied
    print(f"  [5/6] VIX^2/252 implied...")
    forecasts['VIX_Implied'] = forecast_vix_implied(df['VIX'], oos_mask)

    # 6. Parkinson range
    print(f"  [6/6] Parkinson range (22d)...")
    forecasts['Parkinson'] = forecast_parkinson(df['High'], df['Low'], oos_mask, window=PARKINSON_WINDOW)

    # --- Check individual forecast coverage ---
    realized = df['RV'].values
    print(f"\n  Individual forecast coverage (OOS):")
    for k, v in forecasts.items():
        valid = np.sum(np.isfinite(v) & oos_mask)
        print(f"    {k:15s}: {valid}/{oos_count} valid")

    # --- Combination methods ---
    print(f"\n  Computing combination forecasts...")
    combos = {}

    # 1. Equal weight
    print(f"  [1/4] Equal weight...")
    combos['EqualWeight'] = combine_equal_weight(forecasts, oos_mask)

    # 2. Inverse QLIKE weight
    print(f"  [2/4] Inverse QLIKE weight (rolling {COMBO_WINDOW}d)...")
    combos['InvQLIKE'] = combine_inverse_qlike(forecasts, realized, oos_mask, lookback=COMBO_WINDOW)

    # 3. OLS (Granger-Ramanathan)
    print(f"  [3/4] OLS combination (rolling {COMBO_WINDOW}d)...")
    combos['OLS_GR'] = combine_ols(forecasts, realized, oos_mask, lookback=COMBO_WINDOW)

    # 4. Trimmed mean
    print(f"  [4/4] Trimmed mean...")
    combos['TrimmedMean'] = combine_trimmed_mean(forecasts, oos_mask)

    # --- Evaluate all models ---
    print(f"\n  Evaluating QLIKE and DM tests...")

    # Collect results for this asset
    asset_results = {}

    # Common valid mask: only evaluate where all forecasts are valid
    all_models = {**forecasts, **combos}

    # Use common mask where at least GJR-GARCH and the model being compared are valid
    gjr_forecast = forecasts['GJR-GARCH']

    for model_name, model_forecast in all_models.items():
        # Valid where both this model and OOS
        valid = (oos_mask &
                 np.isfinite(model_forecast) & (model_forecast > 0) &
                 np.isfinite(realized) & (realized >= 0))

        if np.sum(valid) < 50:
            print(f"    {model_name}: insufficient valid forecasts ({np.sum(valid)})")
            continue

        # QLIKE
        ql = qlike_loss(realized[valid], model_forecast[valid])

        # DM test vs GJR-GARCH
        # Common valid for both
        both_valid = (valid &
                      np.isfinite(gjr_forecast) & (gjr_forecast > 0))
        if np.sum(both_valid) >= 50:
            loss_gjr = qlike_loss_series(realized, gjr_forecast)
            loss_model = qlike_loss_series(realized, model_forecast)
            # Use only common valid for DM
            l1 = loss_gjr[both_valid]
            l2 = loss_model[both_valid]
            dm_t, dm_p = dm_test(l1, l2, h=1)
        else:
            dm_t, dm_p = np.nan, np.nan

        asset_results[model_name] = {
            'QLIKE': ql,
            'n_valid': int(np.sum(valid)),
            'DM_t_vs_GJR': dm_t,
            'DM_p_vs_GJR': dm_p,
        }

    results[asset_name] = asset_results

    elapsed = time.time() - t0
    print(f"\n  {asset_name} completed in {elapsed:.1f}s")

    # --- Print asset summary ---
    print(f"\n  {'Model':<20s} {'QLIKE':>10s} {'DM_t':>8s} {'DM_p':>8s} {'n':>6s}  Notes")
    print(f"  {'-'*65}")
    for model_name, r in sorted(asset_results.items(), key=lambda x: x[1]['QLIKE']):
        notes = ""
        if model_name == 'GJR-GARCH':
            notes = "(baseline)"
        elif r['DM_p_vs_GJR'] < 0.05 and r['DM_t_vs_GJR'] < 0:
            notes = "*** BEATS GJR p<0.05"
        elif r['DM_p_vs_GJR'] < 0.10 and r['DM_t_vs_GJR'] < 0:
            notes = "* marginal p<0.10"
        elif r['DM_p_vs_GJR'] < 0.05 and r['DM_t_vs_GJR'] > 0:
            notes = "WORSE than GJR p<0.05"

        print(f"  {model_name:<20s} {r['QLIKE']:>10.6f} {r['DM_t_vs_GJR']:>8.3f} {r['DM_p_vs_GJR']:>8.4f} {r['n_valid']:>6d}  {notes}")

    # Store details for cross-asset analysis
    all_details[asset_name] = {
        'forecasts': {k: v.tolist() for k, v in forecasts.items()},
        'combos': {k: v.tolist() for k, v in combos.items()},
        'realized': realized.tolist(),
        'oos_mask': oos_mask.tolist(),
    }


# ============================================================
# CROSS-ASSET SUMMARY
# ============================================================
print("\n\n" + "=" * 80)
print("CROSS-ASSET SUMMARY")
print("=" * 80)

# Table: rows = models, columns = assets
all_models_set = set()
for asset_name in results:
    all_models_set.update(results[asset_name].keys())
all_models_sorted = sorted(all_models_set)

# Header
print(f"\n{'Model':<20s}", end="")
for asset in ASSETS:
    if asset in results:
        print(f"  {asset:>12s}", end="")
print(f"  {'Avg QLIKE':>12s}  {'Best?':>6s}")
print("-" * (20 + 14 * len(results) + 20))

model_avg_qlike = {}
for model_name in all_models_sorted:
    qlikes = []
    print(f"{model_name:<20s}", end="")
    for asset in ASSETS:
        if asset in results and model_name in results[asset]:
            ql = results[asset][model_name]['QLIKE']
            print(f"  {ql:>12.6f}", end="")
            qlikes.append(ql)
        else:
            print(f"  {'N/A':>12s}", end="")

    if qlikes:
        avg_ql = np.mean(qlikes)
        model_avg_qlike[model_name] = avg_ql
        print(f"  {avg_ql:>12.6f}", end="")
    else:
        print(f"  {'N/A':>12s}", end="")

    print()

# Best model per asset
print(f"\n{'Best model per asset:'}")
for asset in ASSETS:
    if asset not in results:
        continue
    best = min(results[asset].items(), key=lambda x: x[1]['QLIKE'])
    print(f"  {asset}: {best[0]} (QLIKE={best[1]['QLIKE']:.6f})")

# Overall best
if model_avg_qlike:
    best_overall = min(model_avg_qlike.items(), key=lambda x: x[1])
    print(f"\n  Overall best (avg QLIKE): {best_overall[0]} ({best_overall[1]:.6f})")

# --- DM test summary: which combinations beat GJR? ---
print(f"\n\n{'='*80}")
print("DM TEST SUMMARY: Combination vs GJR-GARCH")
print("Negative t = combination better; p<0.05 = significant")
print(f"{'='*80}")

combo_names = ['EqualWeight', 'InvQLIKE', 'OLS_GR', 'TrimmedMean']
print(f"\n{'Combination':<20s}", end="")
for asset in ASSETS:
    if asset in results:
        print(f"  {'t-stat':>8s} {'p':>6s}", end="")
print()
print("-" * (20 + 16 * len(results)))

for combo in combo_names:
    print(f"{combo:<20s}", end="")
    wins = 0
    tested = 0
    for asset in ASSETS:
        if asset in results and combo in results[asset]:
            r = results[asset][combo]
            t = r['DM_t_vs_GJR']
            p = r['DM_p_vs_GJR']
            sig = "*" if p < 0.05 and t < 0 else ""
            print(f"  {t:>8.3f} {p:>5.3f}{sig}", end="")
            tested += 1
            if t < 0 and p < 0.05:
                wins += 1
        else:
            print(f"  {'N/A':>8s} {'':>6s}", end="")
    print(f"  [{wins}/{tested} sig. wins]")

# --- Does optimal combination vary by asset? ---
print(f"\n\n{'='*80}")
print("DOES THE OPTIMAL COMBINATION VARY BY ASSET?")
print(f"{'='*80}")

for asset in ASSETS:
    if asset not in results:
        continue
    # Rank all models
    ranked = sorted(results[asset].items(), key=lambda x: x[1]['QLIKE'])
    print(f"\n  {asset} ranking (top 5):")
    for rank, (name, r) in enumerate(ranked[:5], 1):
        is_combo = name in combo_names
        tag = "[COMBO]" if is_combo else "[INDIV]"
        print(f"    {rank}. {name:<20s} QLIKE={r['QLIKE']:.6f} {tag}")

# --- QLIKE improvement percentages ---
print(f"\n\n{'='*80}")
print("QLIKE IMPROVEMENT: Best Combination vs GJR-GARCH (baseline)")
print(f"{'='*80}")

for asset in ASSETS:
    if asset not in results or 'GJR-GARCH' not in results[asset]:
        continue
    gjr_ql = results[asset]['GJR-GARCH']['QLIKE']
    best_combo_name = None
    best_combo_ql = gjr_ql
    for combo in combo_names:
        if combo in results[asset]:
            ql = results[asset][combo]['QLIKE']
            if ql < best_combo_ql:
                best_combo_ql = ql
                best_combo_name = combo

    if best_combo_name:
        pct = (gjr_ql - best_combo_ql) / gjr_ql * 100
        print(f"  {asset}: {best_combo_name} QLIKE={best_combo_ql:.6f} vs GJR={gjr_ql:.6f} -> {pct:+.2f}% improvement")
    else:
        print(f"  {asset}: No combination beats GJR-GARCH")

# --- Harvey threshold check ---
print(f"\n\n{'='*80}")
print("HARVEY (2016) THRESHOLD CHECK: t > 3.0 for significance")
print(f"{'='*80}")

any_passes = False
for asset in ASSETS:
    if asset not in results:
        continue
    for combo in combo_names:
        if combo in results[asset]:
            r = results[asset][combo]
            t = abs(r['DM_t_vs_GJR'])
            if t > 3.0:
                direction = "BETTER" if r['DM_t_vs_GJR'] < 0 else "WORSE"
                print(f"  {asset} {combo}: |t|={t:.2f} > 3.0 ({direction} than GJR)")
                any_passes = True

if not any_passes:
    print("  NO combination passes Harvey threshold (|t| > 3.0) for any asset.")
    print("  This confirms the 'QLIKE ceiling' finding from prior experiments.")


# ============================================================
# FINAL VERDICT
# ============================================================
print(f"\n\n{'='*80}")
print("FINAL VERDICT")
print(f"{'='*80}")

# Count how many times combinations beat individuals
combo_beats_count = 0
combo_total = 0
for asset in ASSETS:
    if asset not in results:
        continue
    gjr_ql = results[asset].get('GJR-GARCH', {}).get('QLIKE', np.inf)
    for combo in combo_names:
        if combo in results[asset]:
            combo_total += 1
            if results[asset][combo]['QLIKE'] < gjr_ql:
                combo_beats_count += 1

print(f"""
  Combinations beating GJR-GARCH (by QLIKE): {combo_beats_count}/{combo_total}

  Key findings:
  1. Granger-Ramanathan (1984) prediction: combinations often improve.
     Result: {combo_beats_count}/{combo_total} cases show lower QLIKE for combos.

  2. Statistical significance (DM test p<0.05):
""", end="")

sig_count = 0
for asset in ASSETS:
    if asset not in results:
        continue
    for combo in combo_names:
        if combo in results[asset]:
            r = results[asset][combo]
            if r['DM_p_vs_GJR'] < 0.05 and r['DM_t_vs_GJR'] < 0:
                sig_count += 1
                print(f"     - {asset}/{combo}: t={r['DM_t_vs_GJR']:.3f}, p={r['DM_p_vs_GJR']:.4f}")

if sig_count == 0:
    print(f"     None. No combination is statistically significantly better than GJR-GARCH.")

print(f"""
  3. Harvey threshold (|t|>3.0): {"NONE pass" if not any_passes else "Some pass (see above)"}

  4. Cross-asset consistency: {"Best combination varies by asset" if len(set(
      min([(c, results[a][c]['QLIKE']) for c in combo_names if c in results[a]], key=lambda x: x[1])[0]
      for a in ASSETS if a in results
  )) > 1 else "Same combination best across all assets"}

  Conclusion: Forecast combination {"provides some" if combo_beats_count > combo_total // 2 else "does NOT provide"} QLIKE improvement over GJR-GARCH,
  but {"none are" if sig_count == 0 else f"{sig_count} are"} statistically significant (DM test).
  {"The QLIKE ceiling remains unbroken." if sig_count == 0 else "Some combinations break through."}
""")


# ============================================================
# SAVE RESULTS
# ============================================================
output = {
    'experiment': 'K216',
    'title': 'Optimal Ensemble of Volatility Forecasters',
    'oos_period': f'{OOS_START} to {OOS_END}',
    'garch_window': GARCH_WINDOW,
    'other_window': OTHER_WINDOW,
    'combo_window': COMBO_WINDOW,
    'individual_models': list(forecasts.keys()) if forecasts else [],
    'combination_methods': combo_names,
    'results': {},
}

for asset in results:
    output['results'][asset] = {}
    for model_name, r in results[asset].items():
        output['results'][asset][model_name] = {
            'QLIKE': float(r['QLIKE']) if np.isfinite(r['QLIKE']) else None,
            'n_valid': r['n_valid'],
            'DM_t_vs_GJR': float(r['DM_t_vs_GJR']) if np.isfinite(r['DM_t_vs_GJR']) else None,
            'DM_p_vs_GJR': float(r['DM_p_vs_GJR']) if np.isfinite(r['DM_p_vs_GJR']) else None,
        }

output_path = PROJECT_ROOT / "experiments" / "k216_ensemble_forecast_results.json"
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"\nResults saved to {output_path}")
print("Done.")
