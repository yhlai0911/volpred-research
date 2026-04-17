"""K529: Rough Volatility with Time-Varying Hurst Exponent for SPY.

Jump-direction experiment: tests whether the "rough volatility" paradigm
(fBm with H≈0.1) can improve volatility forecasting over standard GARCH,
and whether a TIME-VARYING Hurst exponent adds further value.

Literature basis:
  - Gatheral, Jaisson & Rosenbaum (2018): "Volatility is rough" — fBm H≈0.1
  - Frontiers (2025): Time-varying Hurst via Daubechies-4 wavelet → 12.3% RMSE
    reduction, 9.8% MAPE improvement vs constant H
  - arXiv:2504.15985: Multivariate fBm framework for realized volatility
  - Fukasawa (2021): Rough volatility — fact or artifact?

Key concept:
  Traditional GARCH assumes vol dynamics ≈ BM (H=0.5).
  Rough vol literature finds H≈0.1 → anti-persistent, "rougher" volatility path.
  Time-varying H captures regime-dependent roughness changes.

Models tested:
  1. RoughVol-Const: Constant H, fBm-based mean-reversion forecast
  2. RoughVol-TV:    Time-varying H (rolling 252-day), adaptive mean-reversion
  3. HAR-Rough:      HAR(1,5,22) with H-dependent component weighting
  4. GJR-GARCH(1,1): Standard benchmark
  5. EWMA(λ=0.94):  Simple exponential smoothing benchmark

Data: SPY daily, 2005-01-04 to 2026-03-26 (yfinance)
OOS:  2023-01-01 to 2024-12-31 (≥252 obs)
Eval: QLIKE + MSE(log) + DM test (Harvey t>3.0 threshold)

Usage:
    uv run python experiments/k529_rough_volatility.py
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
import pywt
from scipy import stats

warnings.filterwarnings("ignore")

# Ensure project root is on path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from volpred.data.manager import DataManager


# ============================================================
#  Utility functions
# ============================================================

def print_section(title: str, char: str = "=", width: int = 72):
    print(f"\n{char * width}")
    print(f"  {title}")
    print(f"{char * width}")


def qlike_loss(realized: np.ndarray, forecast: np.ndarray) -> float:
    """QLIKE loss: mean(realized/forecast - log(realized/forecast) - 1)."""
    ratio = realized / forecast
    return float(np.mean(ratio - np.log(ratio) - 1))


def qlike_loss_array(realized: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    """Element-wise QLIKE loss."""
    ratio = realized / forecast
    return ratio - np.log(ratio) - 1


def mse_log_loss(realized: np.ndarray, forecast: np.ndarray) -> float:
    """MSE of log-variance."""
    return float(np.mean((np.log(realized) - np.log(forecast)) ** 2))


def mse_log_loss_array(realized: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    """Element-wise MSE of log-variance."""
    return (np.log(realized) - np.log(forecast)) ** 2


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


# ============================================================
#  Hurst Exponent Estimators
# ============================================================

def estimate_hurst_dfa(series: np.ndarray, min_window: int = 10,
                       max_window: int | None = None) -> float:
    """Detrended Fluctuation Analysis — returns H estimate.
    Vectorized where possible for speed.
    """
    T = len(series)
    if T < 50:
        return np.nan
    if max_window is None:
        max_window = T // 4

    y = np.cumsum(series - np.mean(series))
    window_sizes = np.unique(np.logspace(
        np.log10(min_window), np.log10(max_window), num=25
    ).astype(int))
    window_sizes = window_sizes[(window_sizes >= min_window) & (window_sizes <= max_window)]

    log_n_list = []
    log_f_list = []

    for n in window_sizes:
        n_seg = T // n
        if n_seg < 2:
            continue
        # Reshape into segments
        segments = y[:n_seg * n].reshape(n_seg, n)
        x_ax = np.arange(n, dtype=float)
        # Vectorized linear detrend: fit slope+intercept per segment
        x_mean = x_ax.mean()
        y_means = segments.mean(axis=1, keepdims=True)
        # slope = cov(x, y) / var(x) for each segment
        xc = x_ax - x_mean
        var_x = np.sum(xc ** 2)
        slopes = (segments - y_means) @ xc / var_x
        intercepts = y_means.ravel() - slopes * x_mean
        trends = intercepts[:, None] + slopes[:, None] * x_ax[None, :]
        F2 = np.mean((segments - trends) ** 2, axis=1)
        F_rms = np.sqrt(np.mean(F2))
        if F_rms > 0:
            log_n_list.append(np.log(n))
            log_f_list.append(np.log(F_rms))

    if len(log_n_list) < 3:
        return np.nan

    slope, _, _, _, _ = stats.linregress(log_n_list, log_f_list)
    return float(slope)


def estimate_hurst_variogram(log_vol: np.ndarray, max_lag: int = 50) -> tuple:
    """Variogram estimator (Gatheral et al. 2018).
    m(2, delta) = E[|log σ_{t+δ} − log σ_t|²]
    slope of log m(2,δ) vs log(δ) = 2H.
    Returns (H, R²).
    """
    T = len(log_vol)
    if T < max_lag + 10:
        max_lag = max(T // 3, 2)

    lags = np.arange(1, max_lag + 1)
    m2_vals = np.empty(len(lags))
    for i, delta in enumerate(lags):
        diffs = log_vol[delta:] - log_vol[:-delta]
        m2_vals[i] = np.mean(diffs ** 2)

    log_lags = np.log(lags.astype(float))
    log_m2 = np.log(m2_vals)

    slope, _, r_value, _, _ = stats.linregress(log_lags, log_m2)
    H = slope / 2.0
    return float(H), float(r_value ** 2)


def estimate_hurst_wavelet(log_vol: np.ndarray, wavelet: str = "db4",
                           max_level: int | None = None) -> float:
    """Wavelet-based Hurst estimator using Daubechies-4.

    Uses the wavelet variance at each scale j:
        Var(d_j) ∝ 2^{j(2H+1)}
    So slope of log2(Var(d_j)) vs j gives (2H+1).

    Reference: Frontiers (2025) time-varying Hurst paper.
    """
    T = len(log_vol)
    if T < 32:
        return np.nan

    if max_level is None:
        max_level = min(int(np.log2(T)) - 2, 10)
        max_level = max(max_level, 1)

    try:
        coeffs = pywt.wavedec(log_vol, wavelet, level=max_level)
    except Exception:
        return np.nan

    # coeffs[0] = approx, coeffs[1:] = detail (finest last → first)
    # Detail at level j has variance ∝ 2^{j*(2H+1)}
    # In pywt, coeffs[1] is the coarsest detail, coeffs[-1] is finest
    scales = []
    log_vars = []
    for j_idx in range(1, len(coeffs)):
        d = coeffs[j_idx]
        if len(d) < 4:
            continue
        var_d = np.var(d)
        if var_d > 0:
            # Scale j = max_level - j_idx + 1 (coarsest detail has largest j)
            j = max_level - j_idx + 1
            scales.append(j)
            log_vars.append(np.log2(var_d))

    if len(scales) < 3:
        return np.nan

    scales = np.array(scales, dtype=float)
    log_vars = np.array(log_vars)

    slope, _, _, _, _ = stats.linregress(scales, log_vars)
    # Var(d_j) ∝ 2^{j*(2H+1)} → log2(Var) = j*(2H+1) + const
    # slope = 2H + 1 → H = (slope - 1) / 2
    H = (slope - 1.0) / 2.0
    return float(H)


def estimate_hurst_rolling(log_vol: np.ndarray, window: int = 252,
                           method: str = "variogram") -> np.ndarray:
    """Rolling window Hurst estimation.
    Returns array of same length as log_vol (NaN for initial period).
    """
    T = len(log_vol)
    H_rolling = np.full(T, np.nan)

    for t in range(window - 1, T):
        segment = log_vol[t - window + 1:t + 1]
        if method == "variogram":
            H_val, _ = estimate_hurst_variogram(segment, max_lag=min(50, window // 5))
        elif method == "wavelet":
            H_val = estimate_hurst_wavelet(segment)
        elif method == "dfa":
            H_val = estimate_hurst_dfa(segment, max_window=window // 4)
        else:
            raise ValueError(f"Unknown method: {method}")

        # Clamp to reasonable range
        if not np.isnan(H_val):
            H_val = np.clip(H_val, 0.01, 0.99)
        H_rolling[t] = H_val

    return H_rolling


# ============================================================
#  Forecasting Models
# ============================================================

class RoughVolConstant:
    """Constant-H rough volatility forecaster.

    Uses the estimated (constant) Hurst exponent to build a
    mean-reversion forecast of variance:
        σ²_{t+1} = σ²_long + (σ²_t − σ²_long) · ρ(H)
    where ρ(H) = 1 − (1−2H)·Δ captures the anti-persistence.
    Lower H → faster mean-reversion → ρ closer to 0.
    """
    def __init__(self, H: float, long_window: int = 252):
        self.H = H
        self.long_window = long_window

    def forecast(self, rv_history: np.ndarray) -> float:
        """Forecast next-day variance given RV history."""
        # Long-run variance (trailing window mean)
        lw = min(self.long_window, len(rv_history))
        sigma2_long = np.mean(rv_history[-lw:])

        # Current variance (last observation)
        sigma2_t = rv_history[-1]

        # Anti-persistence factor from H
        # For H < 0.5: rho < 1 (mean-reverts faster than BM)
        # For H = 0.5: rho = 1 (standard random walk in var)
        # For H > 0.5: rho > 1 (trending, but clamped)
        H = np.clip(self.H, 0.01, 0.99)
        rho = 2 * H  # Simple mapping: H=0.1 → rho=0.2 (fast MR)

        forecast = sigma2_long + rho * (sigma2_t - sigma2_long)
        return float(max(forecast, 1e-10))


class RoughVolTimeVarying:
    """Time-varying H rough volatility forecaster.

    Same as RoughVolConstant but H changes each day based on
    rolling window estimation, capturing regime-dependent roughness.
    """
    def __init__(self, long_window: int = 252):
        self.long_window = long_window

    def forecast(self, rv_history: np.ndarray, H_t: float) -> float:
        """Forecast next-day variance using current H estimate."""
        if np.isnan(H_t):
            H_t = 0.1  # default to rough vol assumption

        lw = min(self.long_window, len(rv_history))
        sigma2_long = np.mean(rv_history[-lw:])
        sigma2_t = rv_history[-1]

        H = np.clip(H_t, 0.01, 0.99)
        rho = 2 * H

        forecast = sigma2_long + rho * (sigma2_t - sigma2_long)
        return float(max(forecast, 1e-10))


class HARRough:
    """HAR-Rough: HAR(1,5,22) model with H-dependent component weighting.

    Standard HAR: σ²_{t+1} = c + β₁·RV_d + β₅·RV_w + β₂₂·RV_m
    HAR-Rough: weights β_i are adjusted by H to emphasize short-term
    components when vol is rough (low H) and long-term when smooth (high H).

    The model is re-estimated on a rolling basis.
    """
    def __init__(self, use_H_weighting: bool = True):
        self.use_H_weighting = use_H_weighting

    def forecast(self, rv_history: np.ndarray, H_t: float = None,
                 fit_window: int = 500) -> float:
        """Fit HAR on trailing data and forecast."""
        T = len(rv_history)
        if T < 30:
            return float(np.mean(rv_history))

        # Build HAR regressors
        n_use = min(fit_window, T - 22)
        if n_use < 30:
            n_use = T - 22

        rv = rv_history[-(n_use + 22):]
        n = len(rv)

        # Dependent: RV_{t+1}
        y = rv[22:]

        # Daily: RV_t
        rv_d = rv[21:-1]

        # Weekly: mean(RV_{t}, ..., RV_{t-4})
        rv_w = np.array([np.mean(rv[i-4:i+1]) for i in range(21, n - 1)])

        # Monthly: mean(RV_{t}, ..., RV_{t-21})
        rv_m = np.array([np.mean(rv[i-21:i+1]) for i in range(21, n - 1)])

        # Trim to equal length
        min_len = min(len(y), len(rv_d), len(rv_w), len(rv_m))
        y = y[:min_len]
        rv_d = rv_d[:min_len]
        rv_w = rv_w[:min_len]
        rv_m = rv_m[:min_len]

        if len(y) < 10:
            return float(np.mean(rv_history[-22:]))

        # OLS regression
        X = np.column_stack([np.ones(len(y)), rv_d, rv_w, rv_m])
        try:
            beta = np.linalg.lstsq(X, y, rcond=None)[0]
        except Exception:
            return float(np.mean(rv_history[-22:]))

        # Forecast using latest data
        rv_d_now = rv_history[-1]
        rv_w_now = np.mean(rv_history[-5:])
        rv_m_now = np.mean(rv_history[-22:])

        if self.use_H_weighting and H_t is not None and not np.isnan(H_t):
            # H-dependent re-weighting:
            # Low H (rough) → emphasize daily (short-term MR signal)
            # High H (smooth) → emphasize monthly (trend)
            H = np.clip(H_t, 0.01, 0.99)
            # Weight adjustments
            w_d = 1.0 + (0.5 - H)  # H=0.1 → w_d=1.4, H=0.5 → w_d=1.0
            w_w = 1.0
            w_m = 1.0 - (0.5 - H)  # H=0.1 → w_m=0.6, H=0.5 → w_m=1.0
            forecast = (beta[0] +
                       beta[1] * rv_d_now * w_d +
                       beta[2] * rv_w_now * w_w +
                       beta[3] * rv_m_now * w_m)
        else:
            forecast = (beta[0] + beta[1] * rv_d_now +
                       beta[2] * rv_w_now + beta[3] * rv_m_now)

        return float(max(forecast, 1e-10))


def ewma_forecast(rv_history: np.ndarray, lam: float = 0.94) -> float:
    """EWMA forecast: σ²_{t+1} = λ·σ²_t + (1−λ)·r²_t.
    Here we use RV series, so: forecast = λ·EWMA_t + (1−λ)·RV_t.
    """
    T = len(rv_history)
    if T < 2:
        return float(rv_history[-1])

    ewma = rv_history[0]
    for t in range(1, T):
        ewma = lam * ewma + (1 - lam) * rv_history[t]

    return float(max(ewma, 1e-10))


def gjr_garch_forecast(returns: np.ndarray, window: int = 2000) -> float:
    """GJR-GARCH(1,1) 1-step forecast."""
    from arch import arch_model

    ret_pct = returns[-window:] * 100
    model = arch_model(ret_pct, vol="GARCH", p=1, o=1, q=1,
                       dist="normal", mean="Zero", rescale=False)
    try:
        result = model.fit(disp="off", show_warning=False)
        fc = result.forecast(horizon=1).variance.iloc[-1, 0] / 10000
        return float(max(fc, 1e-10))
    except Exception:
        # Fallback to simple GARCH
        model2 = arch_model(ret_pct, vol="GARCH", p=1, q=1,
                            dist="normal", mean="Zero", rescale=False)
        result2 = model2.fit(disp="off", show_warning=False)
        fc = result2.forecast(horizon=1).variance.iloc[-1, 0] / 10000
        return float(max(fc, 1e-10))


# ============================================================
#  Diagnostics
# ============================================================

def descriptive_stats(series: np.ndarray, name: str):
    """Print descriptive statistics."""
    print(f"  {name}:")
    print(f"    N={len(series)}, Mean={np.mean(series):.6f}, "
          f"Std={np.std(series):.6f}")
    print(f"    Skew={stats.skew(series):.3f}, "
          f"Kurt={stats.kurtosis(series):.3f} (excess)")
    print(f"    Min={np.min(series):.6f}, Max={np.max(series):.6f}")
    q = np.percentile(series, [5, 25, 50, 75, 95])
    print(f"    Percentiles [5,25,50,75,95]: "
          f"[{q[0]:.6f}, {q[1]:.6f}, {q[2]:.6f}, {q[3]:.6f}, {q[4]:.6f}]")


def adf_test(series: np.ndarray, name: str):
    """Augmented Dickey-Fuller stationarity test."""
    from statsmodels.tsa.stattools import adfuller
    result = adfuller(series, maxlag=20, autolag="AIC")
    print(f"  ADF ({name}): stat={result[0]:.4f}, p={result[1]:.4f}, "
          f"lags={result[2]}, {'Stationary' if result[1] < 0.05 else 'Non-stationary'}")


# ============================================================
#  Main experiment
# ============================================================

def main():
    t_start = time.time()
    print("=" * 72)
    print("  K529: ROUGH VOLATILITY WITH TIME-VARYING HURST — SPY")
    print("  Gatheral et al. (2018) + Frontiers (2025) Time-Varying H")
    print("=" * 72)

    # ── 1. Data Loading ──
    print_section("1. Data Loading & Diagnostics")

    dm = DataManager()
    data = dm.get_model_data("SPY", "2005-01-01", "2026-12-31")
    print(f"  Total observations: {len(data)}")
    print(f"  Date range: {data.index[0].date()} to {data.index[-1].date()}")

    returns = data["returns"].values
    rv_parkinson = data["rv_parkinson"].values
    dates = data.index

    # Clean up
    rv_clean = np.maximum(rv_parkinson, 1e-10)
    log_rv = np.log(rv_clean)

    # Descriptive statistics
    print()
    descriptive_stats(returns, "Returns")
    descriptive_stats(rv_clean, "RV (Parkinson)")
    descriptive_stats(log_rv, "Log RV")

    # Stationarity tests
    print()
    adf_test(returns, "Returns")
    adf_test(log_rv, "Log RV")

    # Annualized vol
    ann_vol = np.sqrt(np.mean(rv_clean) * 252)
    print(f"\n  Annualized vol (Parkinson): {ann_vol:.2%}")

    # ── 2. Full-Sample Hurst Estimation ──
    print_section("2. Full-Sample Hurst Exponent Estimation")

    # 2a. Variogram (Gatheral et al. 2018 — gold standard)
    H_vario, R2_vario = estimate_hurst_variogram(log_rv, max_lag=100)
    print(f"  Variogram (Gatheral):  H = {H_vario:.4f}  (R² = {R2_vario:.4f})")

    # 2b. DFA
    H_dfa = estimate_hurst_dfa(log_rv)
    print(f"  DFA:                   H = {H_dfa:.4f}")

    # 2c. Wavelet (Daubechies-4, as in Frontiers 2025)
    H_wavelet = estimate_hurst_wavelet(log_rv, wavelet="db4")
    print(f"  Wavelet (db4):         H = {H_wavelet:.4f}")

    # Roughness test (variogram as primary)
    H_primary = H_vario
    # Bootstrap SE for variogram
    n_boot = 2000
    rng = np.random.RandomState(42)
    H_boots = []
    for _ in range(n_boot):
        idx = rng.choice(len(log_rv), size=len(log_rv), replace=True)
        try:
            h_b, _ = estimate_hurst_variogram(log_rv[idx], max_lag=50)
            if not np.isnan(h_b):
                H_boots.append(h_b)
        except Exception:
            continue
    H_boots = np.array(H_boots)
    se_H = np.std(H_boots) if len(H_boots) > 0 else 0.01

    t_rough = (H_primary - 0.5) / se_H
    p_rough = stats.norm.cdf(t_rough)  # one-sided

    print(f"\n  Roughness Test (H0: H ≥ 0.5 vs H1: H < 0.5):")
    print(f"    H = {H_primary:.4f} ± {se_H:.4f}")
    print(f"    t-stat = {t_rough:.2f}, p-value = {p_rough:.6f}")
    print(f"    {'✓ ROUGH (H < 0.5 confirmed)' if p_rough < 0.01 else '✗ NOT rough'}")
    ci_lo = np.percentile(H_boots, 2.5) if len(H_boots) > 0 else H_primary - 1.96 * se_H
    ci_hi = np.percentile(H_boots, 97.5) if len(H_boots) > 0 else H_primary + 1.96 * se_H
    print(f"    95% CI: [{ci_lo:.4f}, {ci_hi:.4f}]")

    # ── 3. Rolling Hurst Estimation (Time-Varying H) ──
    print_section("3. Time-Varying Hurst Estimation (Rolling Window)")

    # Rolling H with variogram method (w=252)
    print("  Computing rolling H (variogram, w=252)...")
    H_rolling_vario = estimate_hurst_rolling(log_rv, window=252, method="variogram")

    # Rolling H with wavelet method (w=252)
    print("  Computing rolling H (wavelet, w=252)...")
    H_rolling_wavelet = estimate_hurst_rolling(log_rv, window=252, method="wavelet")

    # Summary of rolling H
    valid_vario = H_rolling_vario[~np.isnan(H_rolling_vario)]
    valid_wavelet = H_rolling_wavelet[~np.isnan(H_rolling_wavelet)]

    print(f"\n  Rolling H (variogram): N={len(valid_vario)}, "
          f"Mean={np.mean(valid_vario):.4f}, Std={np.std(valid_vario):.4f}, "
          f"Min={np.min(valid_vario):.4f}, Max={np.max(valid_vario):.4f}")
    print(f"  Rolling H (wavelet):   N={len(valid_wavelet)}, "
          f"Mean={np.mean(valid_wavelet):.4f}, Std={np.std(valid_wavelet):.4f}, "
          f"Min={np.min(valid_wavelet):.4f}, Max={np.max(valid_wavelet):.4f}")

    # Check: H < 0.5 what fraction of time?
    frac_rough_vario = np.mean(valid_vario < 0.5)
    frac_rough_wavelet = np.mean(valid_wavelet < 0.5)
    print(f"\n  Fraction of time H < 0.5 (rough):")
    print(f"    Variogram: {frac_rough_vario:.1%}")
    print(f"    Wavelet:   {frac_rough_wavelet:.1%}")

    # Correlation between variogram and wavelet H
    # Align to valid indices
    both_valid = ~np.isnan(H_rolling_vario) & ~np.isnan(H_rolling_wavelet)
    if both_valid.sum() > 10:
        corr_methods = np.corrcoef(H_rolling_vario[both_valid],
                                   H_rolling_wavelet[both_valid])[0, 1]
        print(f"  Correlation (variogram H vs wavelet H): {corr_methods:.4f}")
    else:
        corr_methods = np.nan

    # ── 4. OOS Forecasting ──
    print_section("4. Out-of-Sample Forecasting")

    oos_start = pd.Timestamp("2023-01-01")
    oos_end = pd.Timestamp("2024-12-31")
    oos_mask = (dates >= oos_start) & (dates <= oos_end)
    oos_indices = np.where(oos_mask)[0]

    n_oos = len(oos_indices)
    print(f"  OOS period: {dates[oos_indices[0]].date()} to "
          f"{dates[oos_indices[-1]].date()}")
    print(f"  OOS observations: {n_oos}")

    # Pre-allocate forecast arrays
    fc_rough_const = np.full(n_oos, np.nan)
    fc_rough_tv = np.full(n_oos, np.nan)
    fc_har_rough = np.full(n_oos, np.nan)
    fc_gjr = np.full(n_oos, np.nan)
    fc_ewma = np.full(n_oos, np.nan)
    realized_oos = np.full(n_oos, np.nan)

    # Models
    rough_const = RoughVolConstant(H=H_primary, long_window=252)
    rough_tv = RoughVolTimeVarying(long_window=252)
    har_rough = HARRough(use_H_weighting=True)

    garch_window = 2000
    garch_refit_every = 21  # Monthly refit to save time
    last_gjr_fc = None

    print("  Running OOS loop...")
    for i, t in enumerate(oos_indices):
        if i % 100 == 0:
            print(f"    {i}/{n_oos}...")

        # Realized variance at t+1 (target)
        if t + 1 < len(rv_clean):
            realized_oos[i] = rv_clean[t + 1]
        else:
            realized_oos[i] = rv_clean[t]

        # History available up to t
        rv_hist = rv_clean[:t + 1]
        ret_hist = returns[:t + 1]

        # Model 1: RoughVol-Constant
        fc_rough_const[i] = rough_const.forecast(rv_hist)

        # Model 2: RoughVol-TimeVarying (use rolling variogram H)
        H_t = H_rolling_vario[t]
        fc_rough_tv[i] = rough_tv.forecast(rv_hist, H_t)

        # Model 3: HAR-Rough (with H-weighted components)
        fc_har_rough[i] = har_rough.forecast(rv_hist, H_t, fit_window=500)

        # Model 4: GJR-GARCH (refit monthly)
        if i % garch_refit_every == 0 or last_gjr_fc is None:
            try:
                last_gjr_fc = gjr_garch_forecast(ret_hist, window=garch_window)
            except Exception:
                if last_gjr_fc is None:
                    last_gjr_fc = np.mean(rv_hist[-252:])
        fc_gjr[i] = last_gjr_fc

        # Model 5: EWMA
        fc_ewma[i] = ewma_forecast(rv_hist, lam=0.94)

    # ── 5. Evaluation ──
    print_section("5. Forecast Evaluation")

    # Remove any NaN
    valid = (~np.isnan(realized_oos) & ~np.isnan(fc_rough_const) &
             ~np.isnan(fc_rough_tv) & ~np.isnan(fc_har_rough) &
             ~np.isnan(fc_gjr) & ~np.isnan(fc_ewma))

    realized = realized_oos[valid]
    f_const = fc_rough_const[valid]
    f_tv = fc_rough_tv[valid]
    f_har = fc_har_rough[valid]
    f_gjr = fc_gjr[valid]
    f_ewma = fc_ewma[valid]

    n_valid = len(realized)
    print(f"  Valid OOS observations: {n_valid}")

    # QLIKE
    ql_const = qlike_loss(realized, f_const)
    ql_tv = qlike_loss(realized, f_tv)
    ql_har = qlike_loss(realized, f_har)
    ql_gjr = qlike_loss(realized, f_gjr)
    ql_ewma = qlike_loss(realized, f_ewma)

    # MSE(log)
    mse_const = mse_log_loss(realized, f_const)
    mse_tv = mse_log_loss(realized, f_tv)
    mse_har = mse_log_loss(realized, f_har)
    mse_gjr = mse_log_loss(realized, f_gjr)
    mse_ewma = mse_log_loss(realized, f_ewma)

    print(f"\n  {'Model':<25} {'QLIKE':>10} {'MSE(log)':>10}")
    print(f"  {'-' * 45}")
    print(f"  {'RoughVol-Const':<25} {ql_const:>10.6f} {mse_const:>10.6f}")
    print(f"  {'RoughVol-TV':<25} {ql_tv:>10.6f} {mse_tv:>10.6f}")
    print(f"  {'HAR-Rough':<25} {ql_har:>10.6f} {mse_har:>10.6f}")
    print(f"  {'GJR-GARCH(1,1)':<25} {ql_gjr:>10.6f} {mse_gjr:>10.6f}")
    print(f"  {'EWMA(0.94)':<25} {ql_ewma:>10.6f} {mse_ewma:>10.6f}")

    # Best model
    models = ["RoughVol-Const", "RoughVol-TV", "HAR-Rough",
              "GJR-GARCH", "EWMA"]
    qlikes = [ql_const, ql_tv, ql_har, ql_gjr, ql_ewma]
    mses = [mse_const, mse_tv, mse_har, mse_gjr, mse_ewma]
    best_ql = models[np.argmin(qlikes)]
    best_mse = models[np.argmin(mses)]
    print(f"\n  Best (QLIKE): {best_ql} ({min(qlikes):.6f})")
    print(f"  Best (MSE):   {best_mse} ({min(mses):.6f})")

    # ── 6. DM Tests ──
    print_section("6. Diebold-Mariano Tests")

    # Element-wise losses
    ql_arr_const = qlike_loss_array(realized, f_const)
    ql_arr_tv = qlike_loss_array(realized, f_tv)
    ql_arr_har = qlike_loss_array(realized, f_har)
    ql_arr_gjr = qlike_loss_array(realized, f_gjr)
    ql_arr_ewma = qlike_loss_array(realized, f_ewma)

    mse_arr_const = mse_log_loss_array(realized, f_const)
    mse_arr_tv = mse_log_loss_array(realized, f_tv)
    mse_arr_har = mse_log_loss_array(realized, f_har)
    mse_arr_gjr = mse_log_loss_array(realized, f_gjr)
    mse_arr_ewma = mse_log_loss_array(realized, f_ewma)

    # Key comparisons (negative DM = first model better)
    dm_pairs = [
        ("RoughVol-Const vs GJR", ql_arr_const, ql_arr_gjr,
         mse_arr_const, mse_arr_gjr),
        ("RoughVol-TV vs GJR", ql_arr_tv, ql_arr_gjr,
         mse_arr_tv, mse_arr_gjr),
        ("HAR-Rough vs GJR", ql_arr_har, ql_arr_gjr,
         mse_arr_har, mse_arr_gjr),
        ("RoughVol-TV vs Const", ql_arr_tv, ql_arr_const,
         mse_arr_tv, mse_arr_const),
        ("HAR-Rough vs EWMA", ql_arr_har, ql_arr_ewma,
         mse_arr_har, mse_arr_ewma),
        ("RoughVol-TV vs EWMA", ql_arr_tv, ql_arr_ewma,
         mse_arr_tv, mse_arr_ewma),
    ]

    dm_results = {}
    print(f"\n  {'Comparison':<30} {'DM(QLIKE)':>10} {'p':>8} "
          f"{'DM(MSE)':>10} {'p':>8}")
    print(f"  {'-' * 66}")

    for name, ql1, ql2, mse1, mse2 in dm_pairs:
        dm_ql, p_ql = dm_test(ql1, ql2)
        dm_mse, p_mse = dm_test(mse1, mse2)
        sig_ql = "***" if abs(dm_ql) > 3.0 else ("**" if abs(dm_ql) > 2.0 else
                 ("*" if abs(dm_ql) > 1.64 else ""))
        sig_mse = "***" if abs(dm_mse) > 3.0 else ("**" if abs(dm_mse) > 2.0 else
                  ("*" if abs(dm_mse) > 1.64 else ""))
        print(f"  {name:<30} {dm_ql:>8.3f}{sig_ql:<2} {p_ql:>8.4f} "
              f"{dm_mse:>8.3f}{sig_mse:<2} {p_mse:>8.4f}")
        dm_results[name] = {
            "dm_qlike": dm_ql, "p_qlike": p_ql,
            "dm_mse": dm_mse, "p_mse": p_mse
        }

    # ── 7. Time-Varying H Analysis ──
    print_section("7. Time-Varying Hurst Analysis")

    # Regime analysis: H in OOS period
    H_oos = H_rolling_vario[oos_indices][valid]
    H_oos_valid = H_oos[~np.isnan(H_oos)]
    print(f"  OOS H (variogram): Mean={np.mean(H_oos_valid):.4f}, "
          f"Std={np.std(H_oos_valid):.4f}")
    print(f"    Min={np.min(H_oos_valid):.4f}, Max={np.max(H_oos_valid):.4f}")
    print(f"    Fraction rough (H<0.5): {np.mean(H_oos_valid < 0.5):.1%}")

    # Compare forecast accuracy in rough vs smooth regimes
    rough_mask = H_oos < 0.5
    smooth_mask = H_oos >= 0.5
    n_rough_oos = rough_mask.sum()
    n_smooth_oos = smooth_mask.sum()

    print(f"\n  Regime breakdown: {n_rough_oos} rough days, "
          f"{n_smooth_oos} smooth days")

    if n_rough_oos > 20 and n_smooth_oos > 20:
        # QLIKE by regime
        ql_tv_rough = qlike_loss(realized[rough_mask], f_tv[rough_mask])
        ql_tv_smooth = qlike_loss(realized[smooth_mask], f_tv[smooth_mask])
        ql_gjr_rough = qlike_loss(realized[rough_mask], f_gjr[rough_mask])
        ql_gjr_smooth = qlike_loss(realized[smooth_mask], f_gjr[smooth_mask])

        print(f"\n  QLIKE by regime:")
        print(f"    {'Model':<20} {'Rough (H<0.5)':>14} {'Smooth (H≥0.5)':>14}")
        print(f"    {'-' * 48}")
        print(f"    {'RoughVol-TV':<20} {ql_tv_rough:>14.6f} {ql_tv_smooth:>14.6f}")
        print(f"    {'GJR-GARCH':<20} {ql_gjr_rough:>14.6f} {ql_gjr_smooth:>14.6f}")

        # TV advantage in each regime
        adv_rough = (ql_gjr_rough - ql_tv_rough) / ql_gjr_rough * 100
        adv_smooth = (ql_gjr_smooth - ql_tv_smooth) / ql_gjr_smooth * 100
        print(f"\n    TV vs GJR advantage: Rough={adv_rough:+.1f}%, "
              f"Smooth={adv_smooth:+.1f}%")
    else:
        ql_tv_rough = ql_tv_smooth = ql_gjr_rough = ql_gjr_smooth = np.nan
        adv_rough = adv_smooth = np.nan

    # ── 8. Wavelet H vs Variogram H comparison ──
    print_section("8. Wavelet vs Variogram Hurst Comparison")

    H_wavelet_oos = H_rolling_wavelet[oos_indices][valid]
    H_wavelet_valid = H_wavelet_oos[~np.isnan(H_wavelet_oos)]
    print(f"  OOS H (wavelet): Mean={np.mean(H_wavelet_valid):.4f}, "
          f"Std={np.std(H_wavelet_valid):.4f}")

    # Re-run TV model with wavelet H for comparison
    fc_tv_wavelet = np.full(n_oos, np.nan)
    for i, t in enumerate(oos_indices):
        rv_hist = rv_clean[:t + 1]
        H_t_w = H_rolling_wavelet[t]
        fc_tv_wavelet[i] = rough_tv.forecast(rv_hist, H_t_w)

    f_tv_w = fc_tv_wavelet[valid]
    ql_tv_w = qlike_loss(realized, f_tv_w)
    mse_tv_w = mse_log_loss(realized, f_tv_w)
    print(f"\n  RoughVol-TV (wavelet H): QLIKE={ql_tv_w:.6f}, MSE={mse_tv_w:.6f}")
    print(f"  RoughVol-TV (variogram H): QLIKE={ql_tv:.6f}, MSE={mse_tv:.6f}")
    print(f"  Wavelet vs Variogram advantage (QLIKE): "
          f"{(ql_tv - ql_tv_w)/ql_tv*100:+.2f}%")

    # DM test: TV-wavelet vs TV-variogram
    ql_arr_tv_w = qlike_loss_array(realized, f_tv_w)
    dm_w_v, p_w_v = dm_test(ql_arr_tv_w, ql_arr_tv)
    print(f"  DM(wavelet vs variogram): stat={dm_w_v:.3f}, p={p_w_v:.4f}")

    # ── 9. Summary ──
    print_section("9. Summary & Conclusions")

    elapsed = time.time() - t_start
    print(f"  Runtime: {elapsed:.1f}s")
    print(f"\n  Full-sample Hurst: {H_primary:.4f} (variogram), "
          f"{H_wavelet:.4f} (wavelet), {H_dfa:.4f} (DFA)")
    print(f"  Roughness confirmed: {'Yes' if p_rough < 0.01 else 'No'} "
          f"(p={p_rough:.6f})")

    print(f"\n  OOS QLIKE ranking:")
    ranked = sorted(zip(models + ["RoughVol-TV(wavelet)"],
                       qlikes + [ql_tv_w]),
                    key=lambda x: x[1])
    for rank, (m, q) in enumerate(ranked, 1):
        print(f"    {rank}. {m}: {q:.6f}")

    # Determine if any rough model passes Harvey threshold
    any_significant = False
    for name, info in dm_results.items():
        if abs(info["dm_qlike"]) > 3.0 or abs(info["dm_mse"]) > 3.0:
            any_significant = True
            break

    print(f"\n  Any DM test passes Harvey (2016) |t|>3.0: "
          f"{'Yes' if any_significant else 'No'}")

    # ── 10. Save results ──
    print_section("10. Saving Results")

    results = {
        "experiment_id": "K529",
        "title": "Rough Volatility with Time-Varying Hurst Exponent for SPY",
        "asset": "SPY",
        "data_source": "yfinance",
        "data_period": f"{data.index[0].date()} to {data.index[-1].date()}",
        "n_total": int(len(data)),
        "timestamp": datetime.now().isoformat(),
        "paradigm": "Rough Volatility (fBm with H<0.5)",
        "references": [
            "Gatheral, Jaisson & Rosenbaum (2018): Volatility is rough, QF",
            "Frontiers (2025): Time-varying Hurst via Daubechies-4 wavelet",
            "arXiv:2504.15985: Multivariate fBm for realized volatility",
            "Fukasawa (2021): Rough volatility fact vs artifact"
        ],
        "hurst_estimation": {
            "full_sample": {
                "variogram_H": round(H_primary, 4),
                "variogram_R2": round(R2_vario, 4),
                "variogram_SE": round(se_H, 4),
                "variogram_95CI": [round(ci_lo, 4), round(ci_hi, 4)],
                "dfa_H": round(H_dfa, 4),
                "wavelet_H": round(H_wavelet, 4),
                "roughness_t_stat": round(t_rough, 2),
                "roughness_p_value": round(p_rough, 6),
                "is_rough": bool(p_rough < 0.01)
            },
            "rolling": {
                "window": 252,
                "variogram": {
                    "mean_H": round(np.mean(valid_vario), 4),
                    "std_H": round(np.std(valid_vario), 4),
                    "min_H": round(np.min(valid_vario), 4),
                    "max_H": round(np.max(valid_vario), 4),
                    "frac_rough": round(frac_rough_vario, 4)
                },
                "wavelet": {
                    "mean_H": round(np.mean(valid_wavelet), 4),
                    "std_H": round(np.std(valid_wavelet), 4),
                    "min_H": round(np.min(valid_wavelet), 4),
                    "max_H": round(np.max(valid_wavelet), 4),
                    "frac_rough": round(frac_rough_wavelet, 4)
                },
                "correlation_vario_wavelet": round(corr_methods, 4) if not np.isnan(corr_methods) else None
            }
        },
        "oos": {
            "period": f"{dates[oos_indices[0]].date()} to {dates[oos_indices[-1]].date()}",
            "n_obs": int(n_valid),
            "garch_window": garch_window,
            "garch_refit_every": garch_refit_every,
            "results": {
                "RoughVol-Const": {
                    "qlike": round(ql_const, 6),
                    "mse_log": round(mse_const, 6),
                    "H_used": round(H_primary, 4)
                },
                "RoughVol-TV": {
                    "qlike": round(ql_tv, 6),
                    "mse_log": round(mse_tv, 6),
                    "H_method": "variogram_rolling_252"
                },
                "RoughVol-TV-Wavelet": {
                    "qlike": round(ql_tv_w, 6),
                    "mse_log": round(mse_tv_w, 6),
                    "H_method": "wavelet_rolling_252"
                },
                "HAR-Rough": {
                    "qlike": round(ql_har, 6),
                    "mse_log": round(mse_har, 6)
                },
                "GJR-GARCH": {
                    "qlike": round(ql_gjr, 6),
                    "mse_log": round(mse_gjr, 6)
                },
                "EWMA": {
                    "qlike": round(ql_ewma, 6),
                    "mse_log": round(mse_ewma, 6)
                }
            },
            "best_qlike": best_ql,
            "best_mse": best_mse
        },
        "dm_tests": dm_results,
        "regime_analysis": {
            "n_rough_days": int(n_rough_oos),
            "n_smooth_days": int(n_smooth_oos),
            "qlike_rough_regime": {
                "RoughVol-TV": round(float(ql_tv_rough), 6) if not np.isnan(ql_tv_rough) else None,
                "GJR-GARCH": round(float(ql_gjr_rough), 6) if not np.isnan(ql_gjr_rough) else None,
                "TV_advantage_pct": round(float(adv_rough), 2) if not np.isnan(adv_rough) else None
            },
            "qlike_smooth_regime": {
                "RoughVol-TV": round(float(ql_tv_smooth), 6) if not np.isnan(ql_tv_smooth) else None,
                "GJR-GARCH": round(float(ql_gjr_smooth), 6) if not np.isnan(ql_gjr_smooth) else None,
                "TV_advantage_pct": round(float(adv_smooth), 2) if not np.isnan(adv_smooth) else None
            }
        },
        "harvey_threshold_met": any_significant,
        "conclusions": [],
        "limitations": [
            "Uses daily Parkinson RV as proxy — intraday data would give cleaner H estimates",
            "Rolling H estimated with w=252 — shorter windows noisier, longer windows smoother",
            "Mean-reversion forecaster is simplified — full fBm simulation would be more principled",
            "GJR-GARCH refitted monthly (every 21 days) for computational efficiency",
            "Single asset (SPY) — results may differ for other assets/markets"
        ],
        "runtime_seconds": round(elapsed, 1)
    }

    # Build conclusions based on results
    conclusions = []
    if p_rough < 0.01:
        conclusions.append(
            f"SPY log-volatility is rough: H={H_primary:.4f} (variogram), "
            f"significantly below 0.5 (t={t_rough:.1f})"
        )
    conclusions.append(
        f"Full-sample H estimates: variogram={H_primary:.4f}, "
        f"wavelet={H_wavelet:.4f}, DFA={H_dfa:.4f}"
    )
    conclusions.append(
        f"Time-varying H varies from {np.min(valid_vario):.3f} to "
        f"{np.max(valid_vario):.3f} (mean={np.mean(valid_vario):.3f}), "
        f"rough {frac_rough_vario:.0%} of the time"
    )
    ranked_conc = sorted(zip(models + ["RoughVol-TV(wavelet)"],
                             qlikes + [ql_tv_w]),
                         key=lambda x: x[1])
    conclusions.append(
        f"OOS QLIKE ranking: 1st={ranked_conc[0][0]} ({ranked_conc[0][1]:.6f}), "
        f"2nd={ranked_conc[1][0]} ({ranked_conc[1][1]:.6f}), "
        f"last={ranked_conc[-1][0]} ({ranked_conc[-1][1]:.6f})"
    )
    if any_significant:
        conclusions.append("At least one DM test exceeds Harvey (2016) |t|>3.0 threshold")
    else:
        conclusions.append("No DM test exceeds Harvey (2016) |t|>3.0 threshold — "
                          "rough vol does not significantly beat benchmarks")

    results["conclusions"] = conclusions

    out_path = project_root / "experiments" / "k529_rough_volatility_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  Results saved to: {out_path}")

    # Final summary
    print(f"\n{'=' * 72}")
    print("  EXPERIMENT COMPLETE")
    for c in conclusions:
        print(f"  → {c}")
    print(f"{'=' * 72}\n")


if __name__ == "__main__":
    main()
