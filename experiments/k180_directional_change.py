"""
K180: Directional Change (DC) Framework for Volatility Prediction
==================================================================

Hypothesis:
  Traditional GARCH models sample in calendar time (uniform intervals).
  Directional Change (DC) resamples in "intrinsic time" — only when price
  reverses by a threshold θ. This captures the market's inherent pace of
  information arrival.

  DC-derived features (event frequency, overshoot magnitude, inter-event
  duration) may contain volatility information beyond what standard GARCH
  or VIX captures.

  Can DC features break the GARCH QLIKE ceiling as GARCH-X regressors?

Method:
  1. Implement DC framework: for each threshold θ ∈ {0.5%, 1%, 2%, 3%, 5%},
     identify DC events (price reversal ≥ θ) and Overshoot events.
     All computed causally (only using data up to time t).
  2. Compute rolling DC features:
     (a) DC frequency: events per 22-day rolling window
     (b) Mean overshoot magnitude: average |OS|/θ in rolling window
     (c) Mean DC duration: average trading days between events
  3. GJR-GARCH-X: use DC features as external regressors.
     Compare to baseline GJR-GARCH on QLIKE.
  4. Statistical tests: DM test, partial correlation controlling for VIX.
  5. Additional test: does DC duration predict next-day realized vol?
     (Hawkes-style intensity — shorter inter-event times → higher vol)

Data:
  - SPY, QQQ, GLD, TLT, BTC-USD daily close-to-close returns
  - Source: DataManager (yfinance cache)
  - OOS: 2023-01-01 to 2024-12-31, rolling window=2000

Key safeguards:
  - No look-ahead: DC events computed causally from past data only
  - Partial r|VIX: test whether DC adds information beyond VIX
  - Harvey (2016): require t > 3.0 for any claimed significance
  - Cross-asset validation: 5 diverse assets

Literature:
  - Guillaume et al. (1997): Original DC framework for FX
  - Glattfelder et al. (2011): DC patterns in financial markets
  - Bakhach et al. (2016): DC-based trading strategies
  - Gemini R8#1: Suggested intrinsic time could break QLIKE ceiling

[提出: Gemini R8#1, 執行: Claude]
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
OOS_END = "2024-12-31"
WINDOW = 2000

# DC thresholds to test
DC_THRESHOLDS = [0.005, 0.01, 0.02, 0.03, 0.05]  # 0.5%, 1%, 2%, 3%, 5%

# Rolling window for DC feature aggregation (trading days)
DC_ROLL_WINDOW = 22  # ~1 month

ASSETS = {
    "SPY": "SPY",
    "QQQ": "QQQ",
    "GLD": "GLD",
    "TLT": "TLT",
    "BTC": "BTC-USD",
}

print("=" * 80)
print("K180: DIRECTIONAL CHANGE (DC) FRAMEWORK FOR VOLATILITY PREDICTION")
print("Can intrinsic-time features break the GJR-GARCH QLIKE ceiling?")
print("=" * 80)


# ============================================================
# HELPER FUNCTIONS
# ============================================================
def qlike_loss(realized, predicted):
    """QLIKE loss: mean(log(pred) + realized/pred). Lower is better."""
    mask = (predicted > 0) & (realized > 0) & np.isfinite(realized) & np.isfinite(predicted)
    r = realized[mask]
    p = predicted[mask]
    return np.mean(np.log(p) + r / p)


def qlike_loss_series(realized, predicted):
    """Element-wise QLIKE loss for DM test."""
    mask = (predicted > 0) & (realized > 0) & np.isfinite(realized) & np.isfinite(predicted)
    r = np.where(mask, realized, np.nan)
    p = np.where(mask, predicted, np.nan)
    return np.log(p) + r / p


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. H0: equal predictive ability.
    Returns (t-stat, p-value). Negative t → model 1 is better."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan
    d_mean = np.mean(d)
    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=1)
    hac_var = gamma0
    for k in range(1, max(h, 2)):
        if k < n:
            gamma_k = np.cov(d[k:], d[:-k])[0, 1]
            hac_var += 2 * (1 - k / max(h, 2)) * gamma_k
    se = np.sqrt(max(hac_var, 1e-20) / n)
    if se < 1e-15:
        return 0.0, 1.0
    t_stat = d_mean / se
    p_value = 2 * stats.t.sf(abs(t_stat), df=n - 1)
    return t_stat, p_value


def partial_correlation(x, y, z):
    """Partial correlation of x and y controlling for z.
    Returns (r_partial, p_value)."""
    mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    x, y, z = x[mask], y[mask], z[mask]
    n = len(x)
    if n < 10:
        return np.nan, np.nan

    # Residualize x and y on z
    z_mat = np.column_stack([np.ones(n), z])
    beta_x = np.linalg.lstsq(z_mat, x, rcond=None)[0]
    beta_y = np.linalg.lstsq(z_mat, y, rcond=None)[0]
    res_x = x - z_mat @ beta_x
    res_y = y - z_mat @ beta_y

    r, p = stats.pearsonr(res_x, res_y)
    return r, p


# ============================================================
# DIRECTIONAL CHANGE FRAMEWORK
# ============================================================
def compute_dc_events(prices, theta):
    """
    Compute Directional Change events causally from a price series.

    A DC event occurs when the price moves by at least theta (in log terms)
    from the most recent extreme point in the opposite direction.

    Parameters
    ----------
    prices : np.array
        Close prices
    theta : float
        DC threshold (e.g. 0.01 = 1%)

    Returns
    -------
    dc_events : list of dict
        Each event has: {index, type ('up'/'down'), price, extreme_price, extreme_index}
    os_events : list of dict
        Overshoot events following each DC
    """
    n = len(prices)
    if n < 2:
        return [], []

    log_p = np.log(prices)

    # State machine
    # mode: 'up' = looking for downturn DC, 'down' = looking for upturn DC
    # extreme: the extreme point of the current trend

    dc_events = []
    os_events = []

    # Initialize: determine initial direction from first two meaningful prices
    extreme_idx = 0
    extreme_price = log_p[0]

    # Find first move to determine initial mode
    mode = None
    for i in range(1, n):
        if log_p[i] - extreme_price >= theta:
            mode = 'up'
            extreme_idx = i
            extreme_price = log_p[i]
            break
        elif extreme_price - log_p[i] >= theta:
            mode = 'down'
            extreme_idx = i
            extreme_price = log_p[i]
            break
        # Track extreme for the undecided phase
        if log_p[i] > extreme_price:
            extreme_idx = i
            extreme_price = log_p[i]
        elif log_p[i] < extreme_price:
            extreme_idx = i
            extreme_price = log_p[i]

    if mode is None:
        return [], []

    start_i = extreme_idx + 1

    for i in range(start_i, n):
        if mode == 'up':
            # Track the high (extreme)
            if log_p[i] > extreme_price:
                extreme_price = log_p[i]
                extreme_idx = i
            # Check for downturn DC
            elif extreme_price - log_p[i] >= theta:
                dc_events.append({
                    'index': i,
                    'type': 'down',
                    'log_price': log_p[i],
                    'extreme_log_price': extreme_price,
                    'extreme_index': extreme_idx,
                    'magnitude': extreme_price - log_p[i],
                })
                # The overshoot of the PREVIOUS DC event is from the
                # previous DC event to this extreme
                if len(dc_events) >= 2:
                    prev_dc = dc_events[-2]
                    os_magnitude = abs(extreme_price - prev_dc['log_price']) - theta
                    os_events.append({
                        'dc_index': prev_dc['index'],
                        'os_end_index': extreme_idx,
                        'os_magnitude': max(os_magnitude, 0),
                    })

                # Switch mode
                mode = 'down'
                extreme_price = log_p[i]
                extreme_idx = i

        elif mode == 'down':
            # Track the low (extreme)
            if log_p[i] < extreme_price:
                extreme_price = log_p[i]
                extreme_idx = i
            # Check for upturn DC
            elif log_p[i] - extreme_price >= theta:
                dc_events.append({
                    'index': i,
                    'type': 'up',
                    'log_price': log_p[i],
                    'extreme_log_price': extreme_price,
                    'extreme_index': extreme_idx,
                    'magnitude': log_p[i] - extreme_price,
                })
                # Overshoot of previous DC
                if len(dc_events) >= 2:
                    prev_dc = dc_events[-2]
                    os_magnitude = abs(prev_dc['log_price'] - extreme_price) - theta
                    os_events.append({
                        'dc_index': prev_dc['index'],
                        'os_end_index': extreme_idx,
                        'os_magnitude': max(os_magnitude, 0),
                    })

                # Switch mode
                mode = 'up'
                extreme_price = log_p[i]
                extreme_idx = i

    return dc_events, os_events


def compute_dc_features_rolling(prices, theta, roll_window=DC_ROLL_WINDOW):
    """
    Compute causal (backward-looking) DC features for each day.

    For each day t, features are computed using ONLY data up to day t.

    Returns DataFrame with columns:
    - dc_freq: number of DC events in the last roll_window days, normalized
    - dc_mean_os: mean overshoot magnitude / theta in last roll_window days
    - dc_mean_dur: mean inter-DC-event duration in last roll_window days
    - dc_intensity: 1 / dc_mean_dur (Hawkes-style intensity)

    Parameters
    ----------
    prices : np.array
        Close prices
    theta : float
        DC threshold
    roll_window : int
        Lookback window for feature aggregation (trading days)

    Returns
    -------
    pd.DataFrame with DC features, indexed 0..n-1
    """
    n = len(prices)
    dc_freq = np.full(n, np.nan)
    dc_mean_os = np.full(n, np.nan)
    dc_mean_dur = np.full(n, np.nan)
    dc_intensity = np.full(n, np.nan)

    # Compute DC events for the full price series causally
    dc_events, os_events = compute_dc_events(prices, theta)

    if len(dc_events) == 0:
        return pd.DataFrame({
            'dc_freq': dc_freq,
            'dc_mean_os': dc_mean_os,
            'dc_mean_dur': dc_mean_dur,
            'dc_intensity': dc_intensity,
        })

    # Convert to arrays for vectorized lookback
    dc_indices = np.array([e['index'] for e in dc_events])
    dc_magnitudes = np.array([e['magnitude'] for e in dc_events])

    # For each day t, count DC events in [t - roll_window + 1, t]
    for t in range(roll_window, n):
        window_start = t - roll_window + 1
        # DC events within window (causal: event index <= t)
        mask = (dc_indices >= window_start) & (dc_indices <= t)
        events_in_window = dc_indices[mask]
        mags_in_window = dc_magnitudes[mask]

        count = len(events_in_window)
        dc_freq[t] = count / roll_window  # events per day

        if count > 0:
            # Mean overshoot = mean magnitude / theta (how much events exceed threshold)
            dc_mean_os[t] = np.mean(mags_in_window) / theta

        if count >= 2:
            # Mean duration between consecutive events
            durations = np.diff(events_in_window)
            dc_mean_dur[t] = np.mean(durations)
            dc_intensity[t] = 1.0 / dc_mean_dur[t] if dc_mean_dur[t] > 0 else np.nan
        elif count == 1:
            # Only one event — use distance from window start
            dc_mean_dur[t] = roll_window
            dc_intensity[t] = 1.0 / roll_window

    return pd.DataFrame({
        'dc_freq': dc_freq,
        'dc_mean_os': dc_mean_os,
        'dc_mean_dur': dc_mean_dur,
        'dc_intensity': dc_intensity,
    })


# ============================================================
# DATA LOADING
# ============================================================
print("\n[1/5] Loading data...")

all_data = {}
for name, ticker in ASSETS.items():
    print(f"  Downloading {name} ({ticker})...", end=" ")
    df = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    if 'adj close' in df.columns:
        df['close'] = df['adj close']
    df = df[['open', 'high', 'low', 'close', 'volume']].dropna()

    # Returns
    df['log_return'] = np.log(df['close'] / df['close'].shift(1))
    df['rv_proxy'] = df['log_return'] ** 2  # squared return as RV proxy
    df = df.dropna()

    print(f"{len(df)} obs ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")
    all_data[name] = df

# Load VIX for partial correlation
print("  Downloading VIX...")
vix_df = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_df.columns, pd.MultiIndex):
    vix_df.columns = vix_df.columns.get_level_values(0)
vix_df.columns = [c.lower() for c in vix_df.columns]
vix_series = vix_df['close'].dropna()
vix_series.name = 'vix'

# ============================================================
# STEP 1: DC EVENT STATISTICS
# ============================================================
print("\n[2/5] Computing DC events and descriptive statistics...")
print("-" * 80)

dc_stats = {}
for name, df in all_data.items():
    prices = df['close'].values
    stats_row = {'asset': name}
    for theta in DC_THRESHOLDS:
        dc_events, os_events = compute_dc_events(prices, theta)
        n_events = len(dc_events)
        n_days = len(prices)
        events_per_year = n_events / (n_days / 252)

        # Duration statistics
        if n_events >= 2:
            dc_indices = [e['index'] for e in dc_events]
            durations = np.diff(dc_indices)
            mean_dur = np.mean(durations)
            median_dur = np.median(durations)
        else:
            mean_dur = np.nan
            median_dur = np.nan

        # Overshoot statistics
        if len(os_events) > 0:
            os_mags = [e['os_magnitude'] for e in os_events]
            mean_os = np.mean(os_mags)
            mean_os_ratio = mean_os / theta
        else:
            mean_os = np.nan
            mean_os_ratio = np.nan

        theta_pct = f"{theta*100:.1f}%"
        stats_row[f'n_events_{theta_pct}'] = n_events
        stats_row[f'events_yr_{theta_pct}'] = round(events_per_year, 1)
        stats_row[f'mean_dur_{theta_pct}'] = round(mean_dur, 1) if not np.isnan(mean_dur) else np.nan
        stats_row[f'mean_os_ratio_{theta_pct}'] = round(mean_os_ratio, 2) if not np.isnan(mean_os_ratio) else np.nan

    dc_stats[name] = stats_row

print(f"\n{'Asset':<6} | {'θ':>5} | {'Events':>7} | {'Events/yr':>10} | {'Mean Dur':>9} | {'OS/θ':>6}")
print("-" * 60)
for name in ASSETS:
    for theta in DC_THRESHOLDS:
        theta_pct = f"{theta*100:.1f}%"
        s = dc_stats[name]
        print(f"{name:<6} | {theta_pct:>5} | {s[f'n_events_{theta_pct}']:>7} | "
              f"{s[f'events_yr_{theta_pct}']:>10.1f} | "
              f"{s.get(f'mean_dur_{theta_pct}', np.nan):>9} | "
              f"{s.get(f'mean_os_ratio_{theta_pct}', np.nan):>6}")
    print("-" * 60)

# ============================================================
# STEP 2: GARCH + DC REGRESSION OVERLAY
# ============================================================
# Strategy: Two-stage approach
#   Stage 1: Rolling GJR-GARCH produces baseline variance forecast h_t
#   Stage 2: Rolling OLS: RV_t = a + b*h_t + c*DC_feature_{t-1} + e_t
#            → Use fitted model to produce DC-adjusted forecast
# This avoids arch library's GARCH-X forecasting limitations while
# being methodologically sound (Engle & Rangel 2008 two-component approach)
print("\n[3/5] Running rolling GARCH + DC regression overlay comparison...")
print("=" * 80)

REGRESSION_WINDOW = 252  # 1 year of OOS data for rolling regression

results = {}

for name, df in all_data.items():
    print(f"\n{'='*60}")
    print(f"  Asset: {name}")
    print(f"{'='*60}")

    returns_100 = df['log_return'].values * 100  # arch library needs pct
    rv_proxy = df['rv_proxy'].values  # r^2
    dates = df.index
    n = len(returns_100)

    # Determine OOS range
    oos_mask = (dates >= OOS_START) & (dates <= OOS_END)
    oos_indices = np.where(oos_mask)[0]

    if len(oos_indices) == 0:
        print(f"  WARNING: No OOS data for {name}, skipping.")
        continue

    oos_start_idx = oos_indices[0]
    oos_end_idx = oos_indices[-1]
    n_oos = len(oos_indices)

    print(f"  OOS: {dates[oos_start_idx].strftime('%Y-%m-%d')} to "
          f"{dates[oos_end_idx].strftime('%Y-%m-%d')} ({n_oos} obs)")

    # Compute DC features for each threshold
    prices = df['close'].values
    dc_features_by_theta = {}
    for theta in DC_THRESHOLDS:
        dc_feat = compute_dc_features_rolling(prices, theta, DC_ROLL_WINDOW)
        dc_features_by_theta[theta] = dc_feat

    # Align VIX
    vix_aligned = vix_series.reindex(dates).ffill().values
    vix_for_corr = vix_aligned  # For partial correlation

    # ---- Baseline GJR-GARCH (rolling) ----
    print(f"  Running baseline GJR-GARCH (rolling w={WINDOW})...")
    gjr_forecasts = np.full(n, np.nan)

    for t in range(oos_start_idx, oos_end_idx + 1):
        start_t = max(0, t - WINDOW)
        y = returns_100[start_t:t]
        if len(y) < 500:
            continue
        try:
            model = arch_model(y, vol='GARCH', p=1, o=1, q=1, dist='normal')
            res = model.fit(disp='off', show_warning=False)
            fcast = res.forecast(horizon=1)
            gjr_forecasts[t] = fcast.variance.values[-1, 0] / 1e4  # back to decimal
        except Exception:
            pass

    gjr_valid_count = np.sum(np.isfinite(gjr_forecasts[oos_start_idx:oos_end_idx + 1]))
    print(f"  GJR baseline: {gjr_valid_count}/{n_oos} valid forecasts")

    # ---- DC-adjusted forecasts for each theta ----
    # Two-stage: rolling regression RV_t = a + b*h_t + c*DC_{t-1}
    # Use past REGRESSION_WINDOW days to fit, then forecast 1-step OOS
    garchx_results_by_theta = {}

    for theta in DC_THRESHOLDS:
        theta_pct = f"{theta*100:.1f}%"
        print(f"  Running GARCH + DC overlay (θ={theta_pct})...")

        dc_feat = dc_features_by_theta[theta]
        dc_freq_arr = dc_feat['dc_freq'].values
        dc_intensity_arr = dc_feat['dc_intensity'].values

        # DC-adjusted forecast via rolling regression
        dc_adj_forecasts = np.full(n, np.nan)
        success_count = 0

        for t in range(oos_start_idx, oos_end_idx + 1):
            # We need: gjr_forecasts and DC features for the regression window
            reg_start = max(0, t - REGRESSION_WINDOW)
            reg_end = t  # exclusive: train on [reg_start, t-1], predict t

            # Get training data
            rv_train = rv_proxy[reg_start:reg_end]
            gjr_train = gjr_forecasts[reg_start:reg_end]
            # DC feature lagged by 1: DC[t-1] → predict RV[t]
            dc_train = dc_freq_arr[reg_start:reg_end]

            # Valid mask
            valid_train = (np.isfinite(rv_train) & np.isfinite(gjr_train) &
                          np.isfinite(dc_train) & (rv_train > 0) & (gjr_train > 0))

            if np.sum(valid_train) < 50:
                continue

            # Build design matrix: [1, h_t, DC_{t}]
            # Note: we're regressing RV[s] on h[s] and DC[s-1]
            # So shift DC by 1 within the training window
            dc_train_lagged = np.full_like(dc_train, np.nan)
            dc_train_lagged[1:] = dc_train[:-1]
            valid_train = valid_train & np.isfinite(dc_train_lagged)

            if np.sum(valid_train) < 50:
                continue

            X_train = np.column_stack([
                np.ones(np.sum(valid_train)),
                gjr_train[valid_train],
                dc_train_lagged[valid_train],
            ])
            y_train = rv_train[valid_train]

            try:
                beta = np.linalg.lstsq(X_train, y_train, rcond=None)[0]

                # Predict: h_t from GJR + DC feature at t-1
                if not np.isfinite(gjr_forecasts[t]):
                    continue
                dc_val = dc_freq_arr[t - 1] if t > 0 and np.isfinite(dc_freq_arr[t - 1]) else np.nanmedian(dc_train)
                if not np.isfinite(dc_val):
                    continue

                pred = beta[0] + beta[1] * gjr_forecasts[t] + beta[2] * dc_val
                if np.isfinite(pred) and pred > 0:
                    dc_adj_forecasts[t] = pred
                    success_count += 1
                elif np.isfinite(pred):
                    # If negative, fall back to GJR
                    dc_adj_forecasts[t] = gjr_forecasts[t]
                    success_count += 1
            except Exception:
                pass

        print(f"    Success: {success_count}/{n_oos}")

        # Compute QLIKE
        oos_rv = rv_proxy[oos_start_idx:oos_end_idx + 1]
        oos_gjr = gjr_forecasts[oos_start_idx:oos_end_idx + 1]
        oos_dc_adj = dc_adj_forecasts[oos_start_idx:oos_end_idx + 1]

        valid = (np.isfinite(oos_rv) & np.isfinite(oos_gjr) & np.isfinite(oos_dc_adj) &
                 (oos_rv > 0) & (oos_gjr > 0) & (oos_dc_adj > 0))

        if np.sum(valid) < 50:
            print(f"    Insufficient valid forecasts ({np.sum(valid)}), skipping θ={theta_pct}")
            garchx_results_by_theta[theta] = {
                'qlike_gjr': np.nan, 'qlike_dc_adj': np.nan,
                'dm_t': np.nan, 'dm_p': np.nan, 'valid_obs': int(np.sum(valid))
            }
            continue

        qlike_gjr = qlike_loss(oos_rv[valid], oos_gjr[valid])
        qlike_dc_adj = qlike_loss(oos_rv[valid], oos_dc_adj[valid])

        # DM test
        loss_gjr = qlike_loss_series(oos_rv, oos_gjr)
        loss_dc_adj = qlike_loss_series(oos_rv, oos_dc_adj)
        dm_t, dm_p = dm_test(loss_gjr[valid], loss_dc_adj[valid])

        # QLIKE improvement
        qlike_pct_change = (qlike_dc_adj - qlike_gjr) / abs(qlike_gjr) * 100

        print(f"    QLIKE GJR: {qlike_gjr:.6f} | GARCH+DC: {qlike_dc_adj:.6f} | "
              f"Δ: {qlike_pct_change:+.3f}% | DM t={dm_t:.3f} p={dm_p:.4f}")

        garchx_results_by_theta[theta] = {
            'qlike_gjr': round(float(qlike_gjr), 6),
            'qlike_dc_adj': round(float(qlike_dc_adj), 6),
            'qlike_pct_change': round(float(qlike_pct_change), 3),
            'dm_t': round(float(dm_t), 3) if np.isfinite(dm_t) else None,
            'dm_p': round(float(dm_p), 4) if np.isfinite(dm_p) else None,
            'valid_obs': int(np.sum(valid)),
        }

    # ---- Partial correlation: DC features vs RV, controlling for VIX ----
    print(f"\n  Partial correlations (DC feature vs next-day RV | VIX):")
    partial_corr_results = {}

    for theta in DC_THRESHOLDS:
        theta_pct = f"{theta*100:.1f}%"
        dc_feat = dc_features_by_theta[theta]

        # Use OOS period for partial correlation
        # DC feature at t-1 → RV at t (causal)
        dc_freq_lagged = dc_feat['dc_freq'].values[oos_start_idx - 1:oos_end_idx]
        dc_intensity_lagged = dc_feat['dc_intensity'].values[oos_start_idx - 1:oos_end_idx]
        rv_target = rv_proxy[oos_start_idx:oos_end_idx + 1]
        vix_control = vix_for_corr[oos_start_idx - 1:oos_end_idx]

        # Partial corr: DC freq vs RV | VIX
        r_freq, p_freq = partial_correlation(dc_freq_lagged, rv_target, vix_control)
        r_int, p_int = partial_correlation(dc_intensity_lagged, rv_target, vix_control)

        partial_corr_results[theta] = {
            'r_freq_partial': round(float(r_freq), 4) if np.isfinite(r_freq) else None,
            'p_freq_partial': round(float(p_freq), 4) if np.isfinite(p_freq) else None,
            'r_intensity_partial': round(float(r_int), 4) if np.isfinite(r_int) else None,
            'p_intensity_partial': round(float(p_int), 4) if np.isfinite(p_int) else None,
        }

        print(f"    θ={theta_pct}: r_freq|VIX = {r_freq:.4f} (p={p_freq:.4f}), "
              f"r_intensity|VIX = {r_int:.4f} (p={p_int:.4f})"
              if np.isfinite(r_freq) else f"    θ={theta_pct}: insufficient data")

    # ---- Duration → next-day RV prediction (Hawkes-style) ----
    print(f"\n  Duration → next-day RV (Hawkes-style intensity test):")
    duration_results = {}

    for theta in DC_THRESHOLDS:
        theta_pct = f"{theta*100:.1f}%"
        dc_feat = dc_features_by_theta[theta]

        # Use intensity (1/duration) at t-1 to predict RV at t
        intensity = dc_feat['dc_intensity'].values
        # OOS period: intensity[t-1] → rv[t]
        x_hawkes = intensity[oos_start_idx - 1:oos_end_idx]
        y_hawkes = rv_proxy[oos_start_idx:oos_end_idx + 1]

        valid_hw = np.isfinite(x_hawkes) & np.isfinite(y_hawkes)
        if np.sum(valid_hw) < 30:
            duration_results[theta] = {'r': None, 'p': None, 'n': int(np.sum(valid_hw))}
            continue

        r_hw, p_hw = stats.pearsonr(x_hawkes[valid_hw], y_hawkes[valid_hw])
        # Also compute rank correlation (Spearman) for robustness
        rho_hw, p_rho = stats.spearmanr(x_hawkes[valid_hw], y_hawkes[valid_hw])

        duration_results[theta] = {
            'pearson_r': round(float(r_hw), 4),
            'pearson_p': round(float(p_hw), 4),
            'spearman_rho': round(float(rho_hw), 4),
            'spearman_p': round(float(p_rho), 4),
            'n': int(np.sum(valid_hw)),
        }

        print(f"    θ={theta_pct}: Pearson r={r_hw:.4f} (p={p_hw:.4f}), "
              f"Spearman ρ={rho_hw:.4f} (p={p_rho:.4f}), n={np.sum(valid_hw)}")

    # Store all results for this asset
    results[name] = {
        'garchx_by_theta': garchx_results_by_theta,
        'partial_correlations': partial_corr_results,
        'duration_hawkes': duration_results,
        'n_oos': n_oos,
    }


# ============================================================
# STEP 3: CROSS-ASSET SUMMARY
# ============================================================
print("\n" + "=" * 80)
print("[4/5] CROSS-ASSET SUMMARY")
print("=" * 80)

print(f"\n{'Asset':<6} | {'θ':>5} | {'QLIKE_GJR':>10} | {'QLIKE_DC':>10} | {'Δ%':>7} | {'DM t':>7} | {'DM p':>7} | {'Beat?':>5}")
print("-" * 80)

total_tests = 0
significant_improvements = 0
any_improvement = 0

for name in ASSETS:
    if name not in results:
        continue
    for theta in DC_THRESHOLDS:
        theta_pct = f"{theta*100:.1f}%"
        r = results[name]['garchx_by_theta'].get(theta, {})
        if r.get('qlike_gjr') is None or np.isnan(r.get('qlike_gjr', np.nan)):
            continue

        total_tests += 1
        q_dc = r.get('qlike_dc_adj', r.get('qlike_garchx'))
        if q_dc is None or np.isnan(q_dc):
            continue
        beat = q_dc < r['qlike_gjr']
        sig = r.get('dm_p') is not None and r['dm_p'] < 0.05 and beat

        if beat:
            any_improvement += 1
        if sig:
            significant_improvements += 1

        beat_str = "YES" if beat else "no"
        sig_str = " **" if sig else ""

        print(f"{name:<6} | {theta_pct:>5} | {r['qlike_gjr']:>10.6f} | "
              f"{r['qlike_dc_adj']:>10.6f} | {r.get('qlike_pct_change', 0):>+7.3f} | "
              f"{r.get('dm_t', 0):>7.3f} | {r.get('dm_p', 1):>7.4f} | {beat_str}{sig_str}")
    print("-" * 80)

print(f"\nSummary: {any_improvement}/{total_tests} point improvements, "
      f"{significant_improvements}/{total_tests} statistically significant (DM p<0.05)")

# Harvey threshold check
harvey_pass = 0
for name in results:
    for theta in DC_THRESHOLDS:
        r = results[name]['garchx_by_theta'].get(theta, {})
        if r.get('dm_t') is not None and abs(r['dm_t']) > 3.0:
            harvey_pass += 1
print(f"Harvey (2016) |t| > 3.0: {harvey_pass}/{total_tests} pass")

# ============================================================
# STEP 4: PARTIAL CORRELATION SUMMARY
# ============================================================
print(f"\n{'='*80}")
print("PARTIAL CORRELATION: DC features vs next-day RV, controlling for VIX")
print(f"{'='*80}")

print(f"\n{'Asset':<6} | {'θ':>5} | {'r_freq|VIX':>12} | {'p_freq':>8} | {'r_int|VIX':>12} | {'p_int':>8} | {'Adds info?':>10}")
print("-" * 80)

partial_sig_count = 0
partial_total = 0

for name in results:
    for theta in DC_THRESHOLDS:
        theta_pct = f"{theta*100:.1f}%"
        pc = results[name]['partial_correlations'].get(theta, {})
        r_f = pc.get('r_freq_partial')
        p_f = pc.get('p_freq_partial')
        r_i = pc.get('r_intensity_partial')
        p_i = pc.get('p_intensity_partial')

        if r_f is None:
            continue

        partial_total += 1
        adds_info = (p_f is not None and p_f < 0.05) or (p_i is not None and p_i < 0.05)
        if adds_info:
            partial_sig_count += 1

        info_str = "YES" if adds_info else "no"
        print(f"{name:<6} | {theta_pct:>5} | {r_f:>12.4f} | {p_f:>8.4f} | "
              f"{r_i if r_i is not None else 'N/A':>12} | "
              f"{p_i if p_i is not None else 'N/A':>8} | {info_str}")
    print("-" * 80)

print(f"\nPartial correlation significant: {partial_sig_count}/{partial_total}")

# ============================================================
# STEP 5: DURATION (HAWKES) SUMMARY
# ============================================================
print(f"\n{'='*80}")
print("HAWKES-STYLE: DC intensity (1/duration) → next-day RV")
print(f"{'='*80}")

print(f"\n{'Asset':<6} | {'θ':>5} | {'Pearson r':>10} | {'p':>8} | {'Spearman ρ':>11} | {'p':>8}")
print("-" * 70)

for name in results:
    for theta in DC_THRESHOLDS:
        theta_pct = f"{theta*100:.1f}%"
        hr = results[name]['duration_hawkes'].get(theta, {})
        pr = hr.get('pearson_r')
        pp = hr.get('pearson_p')
        sr = hr.get('spearman_rho')
        sp = hr.get('spearman_p')

        if pr is None:
            print(f"{name:<6} | {theta_pct:>5} | {'N/A':>10} | {'N/A':>8} | {'N/A':>11} | {'N/A':>8}")
        else:
            print(f"{name:<6} | {theta_pct:>5} | {pr:>10.4f} | {pp:>8.4f} | {sr:>11.4f} | {sp:>8.4f}")
    print("-" * 70)


# ============================================================
# CONCLUSIONS
# ============================================================
print("\n" + "=" * 80)
print("[5/5] CONCLUSIONS")
print("=" * 80)

conclusion_lines = []
if significant_improvements == 0:
    conclusion_lines.append(
        f"NULL RESULT: DC features do NOT significantly improve GJR-GARCH QLIKE "
        f"({any_improvement}/{total_tests} point improvements, 0 significant)."
    )
    conclusion_lines.append(
        "Intrinsic time sampling does not break the QLIKE ceiling. "
        "This is consistent with the VIX sufficient statistic finding — "
        "daily close-to-close returns contain most extractable vol information."
    )
else:
    conclusion_lines.append(
        f"PARTIAL RESULT: {significant_improvements}/{total_tests} significant improvements "
        f"found. Harvey threshold: {harvey_pass}/{total_tests}."
    )

if partial_sig_count > 0:
    conclusion_lines.append(
        f"DC features contain SOME information beyond VIX ({partial_sig_count}/{partial_total} "
        f"partial correlations significant), but not enough to improve GARCH forecasting."
    )
else:
    conclusion_lines.append(
        f"DC features do NOT add information beyond VIX (0/{partial_total} partial correlations significant)."
    )

for line in conclusion_lines:
    print(f"  {line}")

# ============================================================
# SAVE RESULTS
# ============================================================
output_file = PROJECT_ROOT / "experiments" / "k180_directional_change_results.json"

# Make results JSON-serializable
def make_serializable(obj):
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj) if np.isfinite(obj) else None
    elif isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    elif isinstance(obj, float) and not np.isfinite(obj):
        return None
    return obj

output = {
    'experiment': 'K180',
    'title': 'Directional Change (DC) Framework for Volatility Prediction',
    'hypothesis': 'DC intrinsic-time features break GJR-GARCH QLIKE ceiling',
    'proposed_by': 'Gemini R8#1',
    'config': {
        'oos_start': OOS_START,
        'oos_end': OOS_END,
        'window': WINDOW,
        'dc_thresholds': DC_THRESHOLDS,
        'dc_roll_window': DC_ROLL_WINDOW,
        'assets': list(ASSETS.keys()),
    },
    'results_by_asset': make_serializable(results),
    'summary': {
        'total_tests': total_tests,
        'point_improvements': any_improvement,
        'significant_improvements': significant_improvements,
        'harvey_pass': harvey_pass,
        'partial_corr_significant': partial_sig_count,
        'partial_corr_total': partial_total,
        'conclusions': conclusion_lines,
    },
    'dc_descriptive_stats': make_serializable(dc_stats),
}

with open(output_file, 'w') as f:
    json.dump(output, f, indent=2)

print(f"\nResults saved to: {output_file}")
print("\n" + "=" * 80)
print("K180 COMPLETE")
print("=" * 80)
