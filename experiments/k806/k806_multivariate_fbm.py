"""K806: Multivariate Fractional Brownian Motion (mfBm) Volatility Prediction.

Cross-asset rough volatility experiment: estimates time-varying Hurst exponents
for multiple assets and tests whether cross-asset H(t) information improves
single-asset volatility forecasting.

Literature basis:
  - arXiv:2504.15985 (April 2025): Multivariate fBm for realized volatility
  - Gatheral, Jaisson & Rosenbaum (2018): "Volatility is rough", QF
  - K529: SPY H≈0.1 confirmed, HAR-Rough beats GJR (DM=-7.04) but not EWMA
  - Fukasawa (2021): Rough volatility — fact or artifact?

Key question:
  Can cross-asset Hurst exponents (from QQQ, GLD, BTC, 0050.TW) improve
  SPY volatility forecasting beyond own-H information?

Models tested:
  1. GJR-GARCH(1,1): Standard benchmark (no H)
  2. EWMA(λ=0.94): Simple exponential smoothing benchmark
  3. GJR + own H(t): GJR with own asset's rolling H as exogenous
  4. GJR + cross-asset H: GJR with all assets' H vector
  5. HAR: Standard HAR(1,5,22)
  6. HAR + own H(t): HAR with own asset's H
  7. HAR + cross-asset H: HAR with all assets' H vector

Assets: SPY, QQQ, GLD, 0050.TW, BTC-USD
Data: 2005-01-01 to 2024-12-31 (yfinance)
OOS:  2023-01-01 to 2024-12-31
Eval: QLIKE on r², Spearman rank correlation, DM test (Harvey t>3.0)

Usage:
    uv run python experiments/k806_multivariate_fbm.py
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

# Ensure project root is on path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))


# ============================================================
#  Configuration
# ============================================================

ASSETS = ["SPY", "QQQ", "GLD", "0050.TW", "BTC-USD"]
DATA_START = "2005-01-01"
DATA_END = "2024-12-31"
OOS_START = "2023-01-01"

# Hurst estimation
H_WINDOW = 60          # Rolling window for variogram H estimation
H_LAGS = [1, 2, 5, 10, 22]  # Lags for variogram

# GARCH
GARCH_REFIT_EVERY = 21  # Monthly refit

# HAR
HAR_LAGS = [1, 5, 22]

TARGET_ASSET = "SPY"  # Primary prediction target


# ============================================================
#  Utility functions
# ============================================================

def print_section(title: str, char: str = "=", width: int = 72):
    print(f"\n{char * width}")
    print(f"  {title}")
    print(f"{char * width}")


def qlike_loss(realized: np.ndarray, forecast: np.ndarray) -> float:
    """QLIKE loss: mean(realized/forecast - log(realized/forecast) - 1).
    Patton (2011) proxy-robust loss function.
    """
    mask = (realized > 0) & (forecast > 0) & np.isfinite(realized) & np.isfinite(forecast)
    r, f = realized[mask], forecast[mask]
    if len(r) == 0:
        return np.inf
    ratio = r / f
    return float(np.mean(ratio - np.log(ratio) - 1))


def qlike_loss_array(realized: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    """Element-wise QLIKE loss for DM test."""
    ratio = realized / forecast
    return ratio - np.log(ratio) - 1


def dm_test(loss1: np.ndarray, loss2: np.ndarray, h: int = 1) -> tuple:
    """Diebold-Mariano test (two-sided).
    loss1 - loss2 < 0 means model 1 is better.
    Returns (DM statistic, p-value).
    """
    d = loss1 - loss2
    T = len(d)
    d_bar = np.mean(d)
    gamma_0 = np.var(d, ddof=0)
    gamma_sum = 0.0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k], ddof=0)[0, 1]
        gamma_sum += 2 * gamma_k
    var_d = (gamma_0 + gamma_sum) / T
    if var_d <= 0:
        var_d = gamma_0 / T
    dm_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_value)


def spearman_corr(realized: np.ndarray, forecast: np.ndarray) -> float:
    """Spearman rank correlation between realized and forecast."""
    mask = np.isfinite(realized) & np.isfinite(forecast)
    if mask.sum() < 10:
        return np.nan
    corr, _ = stats.spearmanr(realized[mask], forecast[mask])
    return float(corr)


# ============================================================
#  Hurst Exponent Estimation (Variogram-based)
# ============================================================

def estimate_hurst_variogram(log_vol: np.ndarray, lags: list[int] | None = None) -> float:
    """Variogram estimator (Gatheral et al. 2018).
    m(2, delta) = E[|log σ_{t+δ} − log σ_t|²]
    slope of log m(2,δ) vs log(δ) = 2H.
    Returns H.
    """
    if lags is None:
        lags = [1, 2, 5, 10, 22]
    T = len(log_vol)
    if T < max(lags) + 5:
        return np.nan

    valid_lags = []
    m2_vals = []
    for delta in lags:
        if delta >= T:
            continue
        diffs = log_vol[delta:] - log_vol[:-delta]
        m2 = np.mean(diffs ** 2)
        if m2 > 0:
            valid_lags.append(delta)
            m2_vals.append(m2)

    if len(valid_lags) < 3:
        return np.nan

    log_lags = np.log(np.array(valid_lags, dtype=float))
    log_m2 = np.log(np.array(m2_vals))

    slope, _, _, _, _ = stats.linregress(log_lags, log_m2)
    H = slope / 2.0
    return float(H)


def rolling_hurst(log_vol: pd.Series, window: int = 60,
                  lags: list[int] | None = None) -> pd.Series:
    """Rolling variogram-based Hurst exponent estimation.
    Returns a Series of H(t) aligned with the input index.
    """
    if lags is None:
        lags = H_LAGS
    T = len(log_vol)
    H_series = pd.Series(np.nan, index=log_vol.index)

    arr = log_vol.values
    for i in range(window, T):
        chunk = arr[i - window:i]
        H_series.iloc[i] = estimate_hurst_variogram(chunk, lags=lags)

    return H_series


# ============================================================
#  Parkinson Realized Volatility Proxy
# ============================================================

def parkinson_rv(high: pd.Series, low: pd.Series) -> pd.Series:
    """Parkinson (1980) high-low range estimator for daily variance.
    RV_park = (ln(H/L))^2 / (4*ln(2))
    """
    log_hl = np.log(high / low)
    return log_hl ** 2 / (4 * np.log(2))


# ============================================================
#  Model: GJR-GARCH(1,1) with optional exogenous regressors
# ============================================================

def fit_gjr_garch(returns: np.ndarray, exog: np.ndarray | None = None):
    """Fit GJR-GARCH(1,1) via maximum likelihood.
    σ²_t = ω + α r²_{t-1} + γ r²_{t-1} I(r_{t-1}<0) + β σ²_{t-1} [+ δ'X_{t-1}]

    Returns dict with parameters and conditional variances.
    """
    from scipy.optimize import minimize

    T = len(returns)
    r = returns.copy()

    has_exog = exog is not None and len(exog) > 0
    n_exog = exog.shape[1] if has_exog else 0

    # Initial values
    var_r = np.var(r)
    x0 = [var_r * 0.05, 0.05, 0.05, 0.90]  # omega, alpha, gamma, beta
    if has_exog:
        x0.extend([0.0] * n_exog)

    bounds = [(1e-8, var_r * 10), (1e-6, 0.5), (0.0, 0.5), (0.1, 0.999)]
    if has_exog:
        bounds.extend([(-0.5, 0.5)] * n_exog)

    def neg_loglik(params):
        omega, alpha, gamma_p, beta = params[:4]
        delta = params[4:] if has_exog else []

        sigma2 = np.full(T, var_r)
        for t in range(1, T):
            indicator = 1.0 if r[t-1] < 0 else 0.0
            sigma2[t] = omega + alpha * r[t-1]**2 + gamma_p * r[t-1]**2 * indicator + beta * sigma2[t-1]
            if has_exog:
                for k in range(n_exog):
                    sigma2[t] += delta[k] * exog[t-1, k]
            sigma2[t] = max(sigma2[t], 1e-10)

        # Gaussian log-likelihood
        ll = -0.5 * np.sum(np.log(2 * np.pi * sigma2) + r**2 / sigma2)
        return -ll

    try:
        result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                          options={'maxiter': 500, 'ftol': 1e-10})
        if not result.success:
            # Try Nelder-Mead fallback (no bounds)
            result = minimize(neg_loglik, x0, method='Nelder-Mead',
                              options={'maxiter': 1000})

        params = result.x
        omega, alpha, gamma_p, beta = params[:4]
        delta = params[4:] if has_exog else []

        # Recompute conditional variance with fitted params
        sigma2 = np.full(T, var_r)
        for t in range(1, T):
            indicator = 1.0 if r[t-1] < 0 else 0.0
            sigma2[t] = omega + alpha * r[t-1]**2 + gamma_p * r[t-1]**2 * indicator + beta * sigma2[t-1]
            if has_exog:
                for k in range(n_exog):
                    sigma2[t] += delta[k] * exog[t-1, k]
            sigma2[t] = max(sigma2[t], 1e-10)

        persistence = alpha + gamma_p / 2 + beta
        converged = result.success or result.fun < 1e15

        return {
            'params': {'omega': omega, 'alpha': alpha, 'gamma': gamma_p,
                       'beta': beta, 'delta': list(delta)},
            'sigma2': sigma2,
            'persistence': persistence,
            'converged': converged,
            'loglik': -result.fun,
        }
    except Exception as e:
        # Fallback: return EWMA-like
        sigma2 = np.full(T, var_r)
        for t in range(1, T):
            sigma2[t] = 0.94 * sigma2[t-1] + 0.06 * r[t-1]**2
        return {
            'params': {'omega': 0, 'alpha': 0.06, 'gamma': 0, 'beta': 0.94, 'delta': []},
            'sigma2': sigma2,
            'persistence': 1.0,
            'converged': False,
            'loglik': np.nan,
        }


def gjr_forecast_oos(returns: np.ndarray, oos_start_idx: int,
                     exog: np.ndarray | None = None,
                     refit_every: int = 21) -> np.ndarray:
    """Rolling OOS forecast with GJR-GARCH, refitting periodically.
    Returns 1-step-ahead σ² forecasts for OOS period.
    CRITICAL: signal.shift(1) equivalent — forecast at t uses data up to t-1.
    """
    T = len(returns)
    n_oos = T - oos_start_idx
    forecasts = np.full(n_oos, np.nan)

    last_fit = None
    last_fit_idx = -999

    for i in range(n_oos):
        t = oos_start_idx + i  # Current time point — we forecast σ²_t
        # Use data up to t-1 for fitting (no lookahead)
        train_end = t  # exclusive: returns[:t] = data up to t-1

        if train_end < 252:
            continue

        # Refit periodically
        if last_fit is None or (i - last_fit_idx) >= refit_every:
            train_r = returns[:train_end]
            train_exog = exog[:train_end] if exog is not None else None
            last_fit = fit_gjr_garch(train_r, train_exog)
            last_fit_idx = i

        # 1-step-ahead forecast: σ²_t = ω + α r²_{t-1} + γ r²_{t-1} I + β σ²_{t-1}
        p = last_fit['params']
        r_prev = returns[t - 1]
        sigma2_prev = last_fit['sigma2'][-1] if i == 0 or i == last_fit_idx else forecasts[i - 1]
        if np.isnan(sigma2_prev) or sigma2_prev <= 0:
            sigma2_prev = np.var(returns[:train_end])

        indicator = 1.0 if r_prev < 0 else 0.0
        fc = p['omega'] + p['alpha'] * r_prev**2 + p['gamma'] * r_prev**2 * indicator + p['beta'] * sigma2_prev
        if exog is not None and len(p['delta']) > 0:
            for k, d in enumerate(p['delta']):
                fc += d * exog[t - 1, k]  # Uses t-1 exog (no lookahead)
        forecasts[i] = max(fc, 1e-10)

    return forecasts


# ============================================================
#  Model: EWMA
# ============================================================

def ewma_forecast_oos(returns: np.ndarray, oos_start_idx: int,
                      lam: float = 0.94) -> np.ndarray:
    """EWMA 1-step-ahead OOS forecasts.
    σ²_t = λ σ²_{t-1} + (1-λ) r²_{t-1}
    """
    T = len(returns)
    n_oos = T - oos_start_idx

    # Build full EWMA chain from start
    sigma2 = np.full(T, np.var(returns[:oos_start_idx]))
    for t in range(1, T):
        sigma2[t] = lam * sigma2[t-1] + (1 - lam) * returns[t-1]**2
        sigma2[t] = max(sigma2[t], 1e-10)

    # Forecasts: σ²_t uses r_{t-1} (no lookahead via EWMA recursion)
    return sigma2[oos_start_idx:]


# ============================================================
#  Model: HAR with optional exogenous regressors
# ============================================================

def har_forecast_oos(rv_series: pd.Series, oos_start_idx: int,
                     exog_df: pd.DataFrame | None = None,
                     refit_every: int = 63) -> np.ndarray:
    """HAR(1,5,22) with optional exogenous variables.
    RV_{t+1} = c + β₁ RV_t + β₅ RV_{t-4:t} + β₂₂ RV_{t-21:t} [+ δ'X_t]
    CRITICAL: All predictors use info up to time t to forecast t+1.
    """
    from numpy.linalg import lstsq

    rv = rv_series.values
    T = len(rv)
    n_oos = T - oos_start_idx
    forecasts = np.full(n_oos, np.nan)

    # Precompute HAR features for full sample
    rv_1 = rv.copy()  # RV(t)
    rv_5 = pd.Series(rv).rolling(5).mean().values   # avg RV(t-4:t)
    rv_22 = pd.Series(rv).rolling(22).mean().values  # avg RV(t-21:t)

    last_coeffs = None
    last_fit_idx = -999

    for i in range(n_oos):
        t = oos_start_idx + i  # predict RV at t using data up to t-1

        if t < 23:
            continue

        # Refit periodically
        if last_coeffs is None or (i - last_fit_idx) >= refit_every:
            # Training: predict RV[s] using features at s-1, for s in [23, t)
            train_end = t
            targets = rv[23:train_end]
            # Features at s-1 for predicting s
            feat_indices = np.arange(22, train_end - 1)
            X_train = np.column_stack([
                np.ones(len(feat_indices)),
                rv_1[feat_indices],
                rv_5[feat_indices],
                rv_22[feat_indices],
            ])
            if exog_df is not None:
                exog_vals = exog_df.values
                X_train = np.column_stack([X_train, exog_vals[feat_indices]])

            # Remove any NaN rows
            mask = np.all(np.isfinite(X_train), axis=1) & np.isfinite(targets)
            if mask.sum() < 30:
                continue
            X_clean = X_train[mask]
            y_clean = targets[mask]

            last_coeffs, _, _, _ = lstsq(X_clean, y_clean, rcond=None)
            last_fit_idx = i

        if last_coeffs is None:
            continue

        # Forecast: use features at t-1
        x_pred = np.array([1.0, rv_1[t-1], rv_5[t-1], rv_22[t-1]])
        if exog_df is not None:
            x_exog = exog_df.values[t-1]
            x_pred = np.concatenate([x_pred, x_exog])

        if not np.all(np.isfinite(x_pred)):
            continue

        fc = x_pred @ last_coeffs
        forecasts[i] = max(fc, 1e-10)

    return forecasts


# ============================================================
#  Data Loading
# ============================================================

def load_all_assets() -> dict[str, pd.DataFrame]:
    """Load OHLCV data for all assets via DataManager."""
    from volpred.data.manager import DataManager
    dm = DataManager()

    data = {}
    for asset in ASSETS:
        print(f"  Loading {asset}...", end=" ")
        try:
            df = dm.get_price_data(asset, DATA_START, DATA_END)
            if df is not None and len(df) > 100:
                data[asset] = df
                print(f"OK ({len(df)} obs, {df.index[0].date()} to {df.index[-1].date()})")
            else:
                print(f"SKIP (only {len(df) if df is not None else 0} obs)")
        except Exception as e:
            print(f"ERROR: {e}")
    return data


def prepare_asset_data(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare single asset: returns, RV proxy, log-vol."""
    # Handle both uppercase and lowercase column names
    cols = {c.lower(): c for c in df.columns}
    close_col = cols.get('close', 'Close')
    high_col = cols.get('high', 'High')
    low_col = cols.get('low', 'Low')

    out = pd.DataFrame(index=df.index)
    out['close'] = df[close_col]
    out['high'] = df[high_col]
    out['low'] = df[low_col]
    out['returns'] = np.log(df[close_col] / df[close_col].shift(1))
    out['r_squared'] = out['returns'] ** 2

    # Parkinson RV proxy
    out['rv_park'] = parkinson_rv(df[high_col], df[low_col])

    # Log-volatility for Hurst estimation (using |r| as proxy)
    abs_r = out['returns'].abs()
    abs_r = abs_r.replace(0, np.nan).ffill()
    out['log_vol'] = np.log(abs_r.clip(lower=1e-10))

    out = out.dropna(subset=['returns'])
    return out


# ============================================================
#  Main Experiment
# ============================================================

def run_experiment():
    start_time = time.time()
    print_section("K806: Multivariate Fractional Brownian Motion (mfBm)")
    print(f"  Timestamp: {datetime.utcnow().isoformat()}")
    print(f"  Assets: {ASSETS}")
    print(f"  Data: {DATA_START} to {DATA_END}")
    print(f"  OOS: {OOS_START} to {DATA_END}")
    print(f"  Target: {TARGET_ASSET}")

    # ----------------------------------------------------------
    # Step 0: Load data
    # ----------------------------------------------------------
    print_section("Step 0: Data Loading")
    raw_data = load_all_assets()
    if TARGET_ASSET not in raw_data:
        raise ValueError(f"Target asset {TARGET_ASSET} not available!")

    # Prepare per-asset data
    asset_data = {}
    for asset, df in raw_data.items():
        asset_data[asset] = prepare_asset_data(df)
        print(f"  {asset}: {len(asset_data[asset])} trading days")

    # ----------------------------------------------------------
    # Step 1: Descriptive statistics
    # ----------------------------------------------------------
    print_section("Step 1: Descriptive Statistics")
    desc_stats = {}
    for asset in asset_data:
        r = asset_data[asset]['returns'].dropna()
        desc_stats[asset] = {
            'n_obs': int(len(r)),
            'mean': float(r.mean()),
            'std': float(r.std()),
            'skew': float(r.skew()),
            'kurtosis': float(r.kurtosis()),
            'min': float(r.min()),
            'max': float(r.max()),
        }
        print(f"  {asset}: n={len(r)}, mean={r.mean():.6f}, std={r.std():.4f}, "
              f"skew={r.skew():.2f}, kurt={r.kurtosis():.2f}")

    # ----------------------------------------------------------
    # Step 2: Estimate rolling Hurst exponents for all assets
    # ----------------------------------------------------------
    print_section("Step 2: Rolling Hurst Exponent Estimation")
    hurst_data = {}
    hurst_stats = {}

    for asset in asset_data:
        print(f"  Estimating H(t) for {asset}...", end=" ")
        log_vol = asset_data[asset]['log_vol']
        H_rolling = rolling_hurst(log_vol, window=H_WINDOW, lags=H_LAGS)

        # Also compute full-sample H
        full_H = estimate_hurst_variogram(log_vol.dropna().values, lags=H_LAGS)

        H_valid = H_rolling.dropna()
        hurst_data[asset] = H_rolling

        hurst_stats[asset] = {
            'full_sample_H': round(full_H, 4) if not np.isnan(full_H) else None,
            'rolling_mean_H': round(float(H_valid.mean()), 4) if len(H_valid) > 0 else None,
            'rolling_std_H': round(float(H_valid.std()), 4) if len(H_valid) > 0 else None,
            'rolling_min_H': round(float(H_valid.min()), 4) if len(H_valid) > 0 else None,
            'rolling_max_H': round(float(H_valid.max()), 4) if len(H_valid) > 0 else None,
            'frac_rough': round(float((H_valid < 0.5).mean()), 4) if len(H_valid) > 0 else None,
            'n_valid': int(len(H_valid)),
        }
        print(f"H_full={full_H:.4f}, H_mean={H_valid.mean():.4f}, "
              f"frac_rough={float((H_valid < 0.5).mean()):.2%}")

    # ----------------------------------------------------------
    # Step 3: Cross-asset H correlations
    # ----------------------------------------------------------
    print_section("Step 3: Cross-Asset Hurst Correlations")

    # Align all H series to common dates
    target_dates = asset_data[TARGET_ASSET].index
    H_aligned = pd.DataFrame(index=target_dates)
    for asset in hurst_data:
        H_aligned[f"H_{asset}"] = hurst_data[asset].reindex(target_dates)

    H_corr = H_aligned.dropna().corr()
    cross_h_correlations = {}
    print("  Correlation matrix of H(t) across assets:")
    for i, a1 in enumerate(H_corr.columns):
        for j, a2 in enumerate(H_corr.columns):
            if j > i:
                corr_val = H_corr.iloc[i, j]
                key = f"{a1} vs {a2}"
                cross_h_correlations[key] = round(float(corr_val), 4)
                print(f"    {key}: {corr_val:.4f}")

    # ----------------------------------------------------------
    # Step 4: Build aligned dataset for target asset
    # ----------------------------------------------------------
    print_section("Step 4: Building Aligned OOS Dataset")

    target_df = asset_data[TARGET_ASSET].copy()

    # Add own H
    target_df['H_own'] = hurst_data[TARGET_ASSET]

    # Add cross-asset H (forward-fill for missing dates in other assets)
    for asset in ASSETS:
        if asset != TARGET_ASSET and asset in hurst_data:
            # Reindex to target dates, forward-fill
            h_reindexed = hurst_data[asset].reindex(target_df.index).ffill()
            target_df[f'H_{asset}'] = h_reindexed

    # Identify OOS start index
    oos_mask = target_df.index >= OOS_START
    oos_start_idx = np.where(oos_mask)[0][0]
    n_oos = oos_mask.sum()

    print(f"  Target: {TARGET_ASSET}")
    print(f"  Total obs: {len(target_df)}")
    print(f"  OOS start idx: {oos_start_idx} ({target_df.index[oos_start_idx].date()})")
    print(f"  OOS obs: {n_oos}")
    print(f"  OOS end: {target_df.index[-1].date()}")

    # Realized r² as evaluation target (Patton 2011: r² is unbiased for σ²)
    realized = target_df['r_squared'].values[oos_start_idx:]

    # ----------------------------------------------------------
    # Step 5: Run all models
    # ----------------------------------------------------------
    print_section("Step 5: OOS Forecasting")

    returns = target_df['returns'].values
    rv_park = target_df['rv_park']

    results = {}

    # --- Model 1: GJR-GARCH (baseline) ---
    print("  [1/7] GJR-GARCH (baseline)...")
    fc_gjr = gjr_forecast_oos(returns, oos_start_idx, refit_every=GARCH_REFIT_EVERY)
    results['GJR-GARCH'] = fc_gjr

    # --- Model 2: EWMA ---
    print("  [2/7] EWMA (λ=0.94)...")
    fc_ewma = ewma_forecast_oos(returns, oos_start_idx)
    results['EWMA'] = fc_ewma

    # --- Model 3: GJR + own H(t) ---
    print("  [3/7] GJR + own H(t)...")
    # Prepare exogenous: own H (shift(1) already in gjr_forecast via exog[t-1])
    H_own = target_df['H_own'].ffill().fillna(0.1).values
    exog_own = H_own.reshape(-1, 1)
    fc_gjr_own_h = gjr_forecast_oos(returns, oos_start_idx, exog=exog_own,
                                     refit_every=GARCH_REFIT_EVERY)
    results['GJR+ownH'] = fc_gjr_own_h

    # --- Model 4: GJR + cross-asset H ---
    print("  [4/7] GJR + cross-asset H...")
    # Build cross-asset H matrix
    h_cols = ['H_own']
    for asset in ASSETS:
        if asset != TARGET_ASSET and f'H_{asset}' in target_df.columns:
            h_cols.append(f'H_{asset}')
    exog_cross = target_df[h_cols].ffill().fillna(0.1).values
    fc_gjr_cross_h = gjr_forecast_oos(returns, oos_start_idx, exog=exog_cross,
                                       refit_every=GARCH_REFIT_EVERY)
    results['GJR+crossH'] = fc_gjr_cross_h

    # --- Model 5: HAR (standard) ---
    print("  [5/7] HAR(1,5,22)...")
    fc_har = har_forecast_oos(rv_park, oos_start_idx)
    results['HAR'] = fc_har

    # --- Model 6: HAR + own H(t) ---
    print("  [6/7] HAR + own H(t)...")
    exog_own_df = pd.DataFrame({'H_own': target_df['H_own'].ffill().fillna(0.1)},
                                index=target_df.index)
    fc_har_own_h = har_forecast_oos(rv_park, oos_start_idx, exog_df=exog_own_df)
    results['HAR+ownH'] = fc_har_own_h

    # --- Model 7: HAR + cross-asset H ---
    print("  [7/7] HAR + cross-asset H...")
    exog_cross_df = target_df[h_cols].ffill().fillna(0.1)
    fc_har_cross_h = har_forecast_oos(rv_park, oos_start_idx, exog_df=exog_cross_df)
    results['HAR+crossH'] = fc_har_cross_h

    # ----------------------------------------------------------
    # Step 6: Evaluation
    # ----------------------------------------------------------
    print_section("Step 6: OOS Evaluation (QLIKE on r², Spearman, DM test)")

    eval_results = {}
    loss_arrays = {}

    for name, fc in results.items():
        # Filter valid
        mask = np.isfinite(realized) & np.isfinite(fc) & (realized > 0) & (fc > 0)
        r_valid = realized[mask]
        f_valid = fc[mask]

        if len(r_valid) < 50:
            print(f"  {name}: SKIP (only {len(r_valid)} valid obs)")
            continue

        ql = qlike_loss(r_valid, f_valid)
        sp = spearman_corr(r_valid, f_valid)

        eval_results[name] = {
            'qlike': round(ql, 6),
            'spearman': round(sp, 4),
            'n_valid': int(len(r_valid)),
        }
        # Store loss arrays for DM test (full length, with NaN padding)
        la = np.full(len(realized), np.nan)
        la[mask] = qlike_loss_array(r_valid, f_valid)
        loss_arrays[name] = la

        print(f"  {name:20s}: QLIKE={ql:.6f}, Spearman={sp:.4f} (n={len(r_valid)})")

    # Ranking
    ranking = sorted(eval_results.items(), key=lambda x: x[1]['qlike'])
    print("\n  QLIKE Ranking (lower is better):")
    for rank, (name, metrics) in enumerate(ranking, 1):
        print(f"    {rank}. {name:20s}: {metrics['qlike']:.6f}")

    # ----------------------------------------------------------
    # Step 7: DM Tests
    # ----------------------------------------------------------
    print_section("Step 7: Diebold-Mariano Tests (Harvey t>3.0)")

    dm_results = {}
    model_names = list(eval_results.keys())
    baseline = 'GJR-GARCH'

    # Compare each model vs GJR baseline
    for name in model_names:
        if name == baseline:
            continue
        la1 = loss_arrays[name]
        la2 = loss_arrays[baseline]
        mask = np.isfinite(la1) & np.isfinite(la2)
        if mask.sum() < 50:
            continue
        dm_stat, dm_p = dm_test(la1[mask], la2[mask])
        key = f"{name} vs {baseline}"
        dm_results[key] = {
            'dm_stat': round(dm_stat, 4),
            'p_value': round(dm_p, 6),
            'significant_harvey': abs(dm_stat) > 3.0,
            'winner': name if dm_stat < 0 else baseline,
        }
        sig_mark = "***" if abs(dm_stat) > 3.0 else ("*" if dm_p < 0.05 else "")
        print(f"  {key:35s}: DM={dm_stat:+.4f}, p={dm_p:.6f} {sig_mark}")

    # Key comparisons: cross-H vs own-H
    cross_own_pairs = [
        ('GJR+crossH', 'GJR+ownH'),
        ('HAR+crossH', 'HAR+ownH'),
        ('HAR+ownH', 'HAR'),
        ('HAR+crossH', 'HAR'),
        ('GJR+ownH', 'EWMA'),
        ('HAR+crossH', 'EWMA'),
    ]
    print("\n  Key cross-asset comparisons:")
    for m1, m2 in cross_own_pairs:
        if m1 in loss_arrays and m2 in loss_arrays:
            la1 = loss_arrays[m1]
            la2 = loss_arrays[m2]
            mask = np.isfinite(la1) & np.isfinite(la2)
            if mask.sum() < 50:
                continue
            dm_stat, dm_p = dm_test(la1[mask], la2[mask])
            key = f"{m1} vs {m2}"
            dm_results[key] = {
                'dm_stat': round(dm_stat, 4),
                'p_value': round(dm_p, 6),
                'significant_harvey': abs(dm_stat) > 3.0,
                'winner': m1 if dm_stat < 0 else m2,
            }
            sig_mark = "***" if abs(dm_stat) > 3.0 else ("*" if dm_p < 0.05 else "")
            direction = "better" if dm_stat < 0 else "worse"
            print(f"    {key:35s}: DM={dm_stat:+.4f}, p={dm_p:.6f} {sig_mark} "
                  f"({m1} {direction})")

    # ----------------------------------------------------------
    # Step 8: Per-asset Hurst analysis (all 5 assets)
    # ----------------------------------------------------------
    print_section("Step 8: Cross-Asset Hurst Summary")

    per_asset_hurst_oos = {}
    for asset in hurst_data:
        H_s = hurst_data[asset]
        # Get OOS period H values
        if asset in asset_data:
            oos_dates = asset_data[asset].index[asset_data[asset].index >= OOS_START]
            H_oos = H_s.reindex(oos_dates).dropna()
            if len(H_oos) > 0:
                per_asset_hurst_oos[asset] = {
                    'oos_mean_H': round(float(H_oos.mean()), 4),
                    'oos_std_H': round(float(H_oos.std()), 4),
                    'oos_min_H': round(float(H_oos.min()), 4),
                    'oos_max_H': round(float(H_oos.max()), 4),
                    'oos_frac_rough': round(float((H_oos < 0.5).mean()), 4),
                }
                print(f"  {asset:12s}: OOS H_mean={H_oos.mean():.4f}, "
                      f"std={H_oos.std():.4f}, rough={float((H_oos < 0.5).mean()):.0%}")

    # ----------------------------------------------------------
    # Step 9: Convergence & robustness checks
    # ----------------------------------------------------------
    print_section("Step 9: Convergence & Robustness Checks")

    # Check GJR convergence with a sample fit
    sample_fit = fit_gjr_garch(returns[:oos_start_idx])
    print(f"  GJR sample fit: converged={sample_fit['converged']}, "
          f"persistence={sample_fit['persistence']:.4f}")
    if sample_fit['persistence'] >= 1.0:
        print("  WARNING: GJR persistence >= 1 (non-stationary)")

    # Check forecast reasonableness
    for name, fc in results.items():
        valid = fc[np.isfinite(fc) & (fc > 0)]
        if len(valid) > 0:
            print(f"  {name:20s}: mean_fc={valid.mean():.6f}, "
                  f"min={valid.min():.8f}, max={valid.max():.6f}, "
                  f"n_valid={len(valid)}/{len(fc)}")

    # ----------------------------------------------------------
    # Compile results
    # ----------------------------------------------------------
    runtime = time.time() - start_time
    print_section(f"Done! Runtime: {runtime:.1f}s")

    # Conclusions
    conclusions = []
    if ranking:
        best = ranking[0][0]
        conclusions.append(f"Best QLIKE model: {best} ({ranking[0][1]['qlike']:.6f})")

    # Check if cross-asset H adds value
    gjr_own_ql = eval_results.get('GJR+ownH', {}).get('qlike', np.inf)
    gjr_cross_ql = eval_results.get('GJR+crossH', {}).get('qlike', np.inf)
    gjr_base_ql = eval_results.get('GJR-GARCH', {}).get('qlike', np.inf)

    if gjr_own_ql < gjr_base_ql:
        conclusions.append(f"Own H(t) improves GJR: QLIKE {gjr_base_ql:.6f} → {gjr_own_ql:.6f}")
    else:
        conclusions.append(f"Own H(t) does NOT improve GJR: QLIKE {gjr_base_ql:.6f} → {gjr_own_ql:.6f}")

    if gjr_cross_ql < gjr_own_ql:
        conclusions.append(f"Cross-asset H adds value over own H in GJR: {gjr_own_ql:.6f} → {gjr_cross_ql:.6f}")
    else:
        conclusions.append(f"Cross-asset H does NOT add value over own H in GJR: {gjr_own_ql:.6f} → {gjr_cross_ql:.6f}")

    har_ql = eval_results.get('HAR', {}).get('qlike', np.inf)
    har_own_ql = eval_results.get('HAR+ownH', {}).get('qlike', np.inf)
    har_cross_ql = eval_results.get('HAR+crossH', {}).get('qlike', np.inf)

    if har_cross_ql < har_ql:
        conclusions.append(f"Cross-asset H improves HAR: {har_ql:.6f} → {har_cross_ql:.6f}")
    else:
        conclusions.append(f"Cross-asset H does NOT improve HAR: {har_ql:.6f} → {har_cross_ql:.6f}")

    # Harvey threshold check
    any_harvey = any(v.get('significant_harvey', False) for v in dm_results.values())
    conclusions.append(f"Harvey (2016) |t|>3.0 threshold met: {any_harvey}")

    for c in conclusions:
        print(f"  >> {c}")

    # ----------------------------------------------------------
    # Save results
    # ----------------------------------------------------------
    output = {
        'experiment_id': 'K806',
        'title': 'Multivariate Fractional Brownian Motion (mfBm) Volatility Prediction',
        'description': ('Cross-asset rough volatility: estimates time-varying Hurst exponents '
                        'for SPY, QQQ, GLD, 0050.TW, BTC-USD and tests whether cross-asset H(t) '
                        'improves SPY volatility forecasting.'),
        'target_asset': TARGET_ASSET,
        'assets': ASSETS,
        'data_source': 'yfinance',
        'data_period': f'{DATA_START} to {DATA_END}',
        'oos_period': f'{OOS_START} to {DATA_END}',
        'oos_n': int(n_oos),
        'timestamp': datetime.utcnow().isoformat(),
        'references': [
            'arXiv:2504.15985 (April 2025): Multivariate fBm for realized volatility',
            'Gatheral, Jaisson & Rosenbaum (2018): Volatility is rough, QF',
            'K529: SPY H≈0.1, HAR-Rough beats GJR (DM=-7.04)',
            'Fukasawa (2021): Rough volatility — fact or artifact?',
            'Patton (2011): Volatility forecast comparison using imperfect proxies, JoE',
            'Harvey (2016): Testing for cross-sectional anomalies, RFS',
        ],
        'methodology': {
            'hurst_estimation': 'Rolling variogram (window=60, lags=[1,2,5,10,22])',
            'garch_refit': f'Every {GARCH_REFIT_EVERY} days (expanding window)',
            'har_refit': 'Every 63 days (quarterly, expanding window)',
            'evaluation': 'QLIKE on r² (Patton 2011 proxy-robust), Spearman rank corr',
            'statistical_test': 'DM test with Harvey (2016) |t|>3.0 threshold',
            'lag_discipline': 'All forecasts use t-1 information only (no lookahead)',
        },
        'descriptive_statistics': desc_stats,
        'hurst_estimation': {
            'full_sample': hurst_stats,
            'oos': per_asset_hurst_oos,
            'cross_correlations': cross_h_correlations,
        },
        'oos_results': eval_results,
        'oos_ranking_qlike': [{'rank': i+1, 'model': name, 'qlike': m['qlike']}
                               for i, (name, m) in enumerate(ranking)],
        'dm_tests': dm_results,
        'convergence': {
            'gjr_sample_converged': sample_fit['converged'],
            'gjr_persistence': round(sample_fit['persistence'], 4),
        },
        'conclusions': conclusions,
        'limitations': [
            'Uses daily Parkinson RV as σ² proxy — intraday data would give cleaner estimates',
            'Variogram H with window=60 is noisy — trade-off between responsiveness and stability',
            'BTC-USD and 0050.TW have different trading calendars — forward-fill alignment may introduce lag',
            'GJR with exogenous H: H enters linearly in variance equation — nonlinear effects not captured',
            'HAR with H: potential multicollinearity between RV lags and H (both measure vol persistence)',
            'Single target asset (SPY) — cross-asset H value may differ for other targets',
            'No intraday RV (5-min) available — cannot use Hansen & Lunde (2005) gold standard',
        ],
        'runtime_seconds': round(runtime, 1),
    }

    out_path = project_root / 'experiments' / 'k806_multivariate_fbm_results.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  Results saved to: {out_path}")

    return output


if __name__ == '__main__':
    run_experiment()
