"""Rough Volatility Pilot Experiment for SPY.

Tests the Rough Fractional Stochastic Volatility (RFSV) framework:
1. Estimates Hurst exponent H from log realized variance
2. Tests roughness claim: H < 0.5?
3. Implements fractional differencing forecaster
4. OOS comparison vs GJR-GARCH via QLIKE + DM test

References:
  - Gatheral, Jaisson & Rosenbaum (2018): "Volatility is rough"
  - Bennedsen, Lunde & Pakkanen (2022): "Decoupling the short- and long-term
    behavior of stochastic volatility"

Usage:
    uv run python scripts/rough_vol_pilot.py
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

# Ensure project root is on path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from volpred.data.manager import DataManager


# ============================================================
#  Utility functions
# ============================================================

def print_section(title: str, char: str = "-", width: int = 72):
    print(f"\n{char * width}")
    print(f"  {title}")
    print(f"{char * width}")


def qlike_loss(realized: np.ndarray, forecast: np.ndarray) -> float:
    """QLIKE loss: mean(realized/forecast - log(realized/forecast) - 1).
    Lower is better.
    """
    ratio = realized / forecast
    return float(np.mean(ratio - np.log(ratio) - 1))


def dm_test(loss1: np.ndarray, loss2: np.ndarray, h: int = 1) -> tuple:
    """Diebold-Mariano test (two-sided).
    H0: equal predictive accuracy.
    Returns (DM statistic, p-value).
    loss1 - loss2 < 0 means model 1 is better.
    """
    d = loss1 - loss2
    T = len(d)
    d_bar = np.mean(d)

    # HAC variance (Newey-West with h-1 lags)
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
#  Hurst exponent estimation
# ============================================================

def estimate_hurst_rs(series: np.ndarray) -> tuple:
    """R/S analysis for Hurst exponent.
    Returns (H, std_err).
    """
    from hurst import compute_Hc
    H, c, data = compute_Hc(series, kind="change", simplified=False)

    # Bootstrap for confidence interval
    n_boot = 1000
    rng = np.random.RandomState(42)
    H_boots = []
    T = len(series)
    for _ in range(n_boot):
        idx = rng.choice(T, size=T, replace=True)
        try:
            h_b, _, _ = compute_Hc(series[idx], kind="change", simplified=True)
            H_boots.append(h_b)
        except Exception:
            continue

    H_boots = np.array(H_boots)
    se = np.std(H_boots)
    return float(H), float(se), H_boots


def estimate_hurst_dfa(series: np.ndarray, min_window: int = 10, max_window: int = None) -> tuple:
    """Detrended Fluctuation Analysis (DFA) for Hurst exponent.
    Returns (H, std_err).
    """
    T = len(series)
    if max_window is None:
        max_window = T // 4

    # Cumulative sum of demeaned series
    y = np.cumsum(series - np.mean(series))

    # Window sizes (log-spaced)
    window_sizes = np.unique(np.logspace(
        np.log10(min_window), np.log10(max_window), num=30
    ).astype(int))
    window_sizes = window_sizes[window_sizes >= min_window]
    window_sizes = window_sizes[window_sizes <= max_window]

    fluctuations = []
    valid_windows = []

    for n in window_sizes:
        n_segments = T // n
        if n_segments < 2:
            continue

        F2 = []
        for i in range(n_segments):
            segment = y[i * n:(i + 1) * n]
            # Linear detrend
            x_ax = np.arange(n)
            coeffs = np.polyfit(x_ax, segment, 1)
            trend = np.polyval(coeffs, x_ax)
            F2.append(np.mean((segment - trend) ** 2))

        if F2:
            fluctuations.append(np.sqrt(np.mean(F2)))
            valid_windows.append(n)

    if len(valid_windows) < 3:
        return np.nan, np.nan, np.array([])

    log_n = np.log(valid_windows)
    log_f = np.log(fluctuations)

    # OLS fit
    slope, intercept, r_value, p_value, std_err = stats.linregress(log_n, log_f)
    H = slope  # DFA exponent = H for fBm

    # Bootstrap
    n_boot = 1000
    rng = np.random.RandomState(42)
    H_boots = []
    n_points = len(log_n)
    for _ in range(n_boot):
        idx = rng.choice(n_points, size=n_points, replace=True)
        try:
            s, _, _, _, _ = stats.linregress(log_n[idx], log_f[idx])
            H_boots.append(s)
        except Exception:
            continue

    H_boots = np.array(H_boots)
    se = np.std(H_boots) if len(H_boots) > 0 else std_err

    return float(H), float(se), H_boots


def estimate_hurst_variogram(log_vol: np.ndarray, max_lag: int = 50) -> tuple:
    """Variogram-based estimator (Gatheral et al. 2018).
    m(q, delta) = E[|log sigma_{t+delta} - log sigma_t|^q]
    For q=2: slope of log m(2, delta) vs log(delta) gives 2H.
    """
    lags = np.arange(1, max_lag + 1)
    m2 = []
    valid_lags = []

    for delta in lags:
        diffs = log_vol[delta:] - log_vol[:-delta]
        if len(diffs) > 10:
            m2.append(np.mean(diffs ** 2))
            valid_lags.append(delta)

    valid_lags = np.array(valid_lags, dtype=float)
    m2 = np.array(m2)

    log_lags = np.log(valid_lags)
    log_m2 = np.log(m2)

    slope, intercept, r_value, p_value, std_err = stats.linregress(log_lags, log_m2)
    H = slope / 2.0

    # Bootstrap on the regression
    n_boot = 1000
    rng = np.random.RandomState(42)
    H_boots = []
    n_points = len(log_lags)
    for _ in range(n_boot):
        idx = rng.choice(n_points, size=n_points, replace=True)
        try:
            s, _, _, _, _ = stats.linregress(log_lags[idx], log_m2[idx])
            H_boots.append(s / 2.0)
        except Exception:
            continue

    H_boots = np.array(H_boots)
    se = np.std(H_boots) if len(H_boots) > 0 else std_err / 2.0

    return float(H), float(se), float(r_value ** 2), H_boots


# ============================================================
#  Fractional differencing
# ============================================================

def fractional_diff_weights(d: float, n_weights: int) -> np.ndarray:
    """Compute weights for fractional differencing of order d.
    w_k = (-1)^k * C(d, k) = prod_{i=0}^{k-1} (d-i)/(i+1) * (-1)^k
    Using the recursive formula: w_k = -w_{k-1} * (d - k + 1) / k
    """
    w = np.zeros(n_weights)
    w[0] = 1.0
    for k in range(1, n_weights):
        w[k] = -w[k - 1] * (d - k + 1) / k
    return w


def fractional_diff(series: np.ndarray, d: float, window: int = None) -> np.ndarray:
    """Apply fractional differencing of order d.
    If window is None, use full history (exact).
    result[t] = sum_{k=0}^{min(t, window-1)} w[k] * series[t-k]
    """
    T = len(series)
    if window is None:
        window = T
    else:
        window = min(window, T)

    w = fractional_diff_weights(d, window)

    result = np.full(T, np.nan)
    for t in range(window - 1, T):
        lookback = min(t + 1, window)
        # Gather series[t], series[t-1], ..., series[t-lookback+1]
        vals = series[t - lookback + 1:t + 1][::-1]
        result[t] = np.dot(w[:lookback], vals)

    return result


# ============================================================
#  RFSV Forecaster
# ============================================================

class RFSVForecaster:
    """Simple Rough Fractional Stochastic Volatility forecaster.

    Based on Gatheral et al. (2018):
    - Log-vol follows fractional Brownian motion with Hurst H < 0.5
    - Forecast: use fractional differencing to extract the fBm component
      then predict next-day log-vol via AR(p) on the differenced series
    """

    def __init__(self, H: float, ar_order: int = 5, frac_window: int = 500):
        self.H = H
        self.d = H + 0.5  # fractional differencing order for fBm with Hurst H
        # For rough vol: H < 0.5, so d = H + 0.5 < 1.0
        # This makes the fractionally differenced series stationary
        self.ar_order = ar_order
        self.frac_window = frac_window

    def fit_and_forecast(self, log_vol_history: np.ndarray) -> float:
        """Given log-vol history up to t, forecast log-vol at t+1.
        Returns forecast of log(variance) at t+1.
        """
        T = len(log_vol_history)
        if T < self.frac_window:
            # Fallback: simple AR(1) on log-vol
            return self._ar1_forecast(log_vol_history)

        # Step 1: Fractionally difference the log-vol series
        fd_series = fractional_diff(log_vol_history, self.d, window=self.frac_window)

        # Find valid (non-NaN) portion
        valid_mask = ~np.isnan(fd_series)
        if valid_mask.sum() < self.ar_order + 10:
            return self._ar1_forecast(log_vol_history)

        fd_valid = fd_series[valid_mask]

        # Step 2: Fit AR(p) on the fractionally differenced series
        p = min(self.ar_order, len(fd_valid) - 1)
        X = np.column_stack([fd_valid[p - 1 - i:len(fd_valid) - 1 - i] for i in range(p)])
        y = fd_valid[p:]

        # OLS with intercept
        X_aug = np.column_stack([np.ones(len(X)), X])
        try:
            beta = np.linalg.lstsq(X_aug, y, rcond=None)[0]
        except Exception:
            return self._ar1_forecast(log_vol_history)

        # Step 3: Forecast next fd value
        last_vals = fd_valid[-p:][::-1]
        x_new = np.concatenate([[1.0], last_vals])
        fd_forecast = np.dot(beta, x_new)

        # Step 4: Invert fractional differencing to get log-vol forecast
        # Approximate: log_vol_{t+1} ≈ fd_forecast + sum of weighted past log_vols
        # The inversion uses: x_t = fd_t + sum_{k=1}^{N} (-w_k) * x_{t-k}
        w = fractional_diff_weights(self.d, self.frac_window)
        n_use = min(len(log_vol_history), self.frac_window - 1)
        past_vals = log_vol_history[-n_use:][::-1]
        correction = -np.dot(w[1:n_use + 1], past_vals)
        log_vol_forecast = fd_forecast + correction

        return float(log_vol_forecast)

    def _ar1_forecast(self, log_vol: np.ndarray) -> float:
        """Simple AR(1) fallback."""
        y = log_vol[1:]
        x = log_vol[:-1]
        if len(y) < 2:
            return float(log_vol[-1])
        slope, intercept, _, _, _ = stats.linregress(x, y)
        return float(intercept + slope * log_vol[-1])


# ============================================================
#  GJR-GARCH rolling forecaster
# ============================================================

def gjr_garch_rolling_forecast(returns: np.ndarray, window: int) -> float:
    """Fit GJR-GARCH(1,1) on returns[-window:] and forecast 1-step variance."""
    from arch import arch_model

    ret_pct = returns[-window:] * 100
    model = arch_model(
        ret_pct, vol="GARCH", p=1, o=1, q=1,
        dist="normal", mean="Zero", rescale=False
    )
    result = model.fit(disp="off", show_warning=False)
    fc_var = result.forecast(horizon=1).variance.iloc[-1, 0] / 10000
    return float(fc_var)


# ============================================================
#  Main experiment
# ============================================================

def main():
    print("=" * 72)
    print("  ROUGH VOLATILITY PILOT EXPERIMENT — SPY")
    print("  Gatheral, Jaisson & Rosenbaum (2018): 'Volatility is rough'")
    print("=" * 72)

    # ---- 1. Load data ----
    print_section("1. Data Loading")
    dm = DataManager()
    # Need data from 2015 onwards for window=2000 + OOS 2023-2025
    data = dm.get_model_data("SPY", "2014-01-01", "2026-12-31")
    print(f"  Total observations: {len(data)}")
    print(f"  Date range: {data.index[0].date()} to {data.index[-1].date()}")

    returns = data["returns"].values
    dates = data.index

    # Realized variance proxy: Parkinson (already computed)
    rv_parkinson = data["rv_parkinson"].values

    # Also compute squared returns as alternative proxy
    sq_returns = returns ** 2

    # Log realized variance (use Parkinson, more efficient)
    # Floor at 1e-10 to avoid log(0)
    rv_clean = np.maximum(rv_parkinson, 1e-10)
    log_rv = np.log(rv_clean)

    # Also try squared returns (noisier but standard in literature)
    sq_clean = np.maximum(sq_returns, 1e-10)
    log_sq = np.log(sq_clean)

    print(f"  Mean ann. vol (Parkinson): {np.sqrt(np.mean(rv_parkinson) * 252):.2%}")
    print(f"  Mean ann. vol (sq returns): {np.sqrt(np.mean(sq_returns) * 252):.2%}")

    # ---- 2. Hurst exponent estimation ----
    print_section("2. Hurst Exponent Estimation")

    # Use full sample log(RV) for Hurst estimation
    print("\n  [A] Using log(Parkinson RV) as log-vol proxy:")

    # R/S analysis
    H_rs, se_rs, boots_rs = estimate_hurst_rs(log_rv)
    ci_rs_lo = np.percentile(boots_rs, 2.5) if len(boots_rs) > 0 else H_rs - 1.96 * se_rs
    ci_rs_hi = np.percentile(boots_rs, 97.5) if len(boots_rs) > 0 else H_rs + 1.96 * se_rs
    print(f"      R/S analysis:    H = {H_rs:.4f}  (SE={se_rs:.4f}, 95% CI=[{ci_rs_lo:.4f}, {ci_rs_hi:.4f}])")

    # DFA
    H_dfa, se_dfa, boots_dfa = estimate_hurst_dfa(log_rv)
    ci_dfa_lo = np.percentile(boots_dfa, 2.5) if len(boots_dfa) > 0 else H_dfa - 1.96 * se_dfa
    ci_dfa_hi = np.percentile(boots_dfa, 97.5) if len(boots_dfa) > 0 else H_dfa + 1.96 * se_dfa
    print(f"      DFA:             H = {H_dfa:.4f}  (SE={se_dfa:.4f}, 95% CI=[{ci_dfa_lo:.4f}, {ci_dfa_hi:.4f}])")

    # Variogram (Gatheral et al. 2018 method)
    H_var, se_var, r2_var, boots_var = estimate_hurst_variogram(log_rv, max_lag=100)
    ci_var_lo = np.percentile(boots_var, 2.5) if len(boots_var) > 0 else H_var - 1.96 * se_var
    ci_var_hi = np.percentile(boots_var, 97.5) if len(boots_var) > 0 else H_var + 1.96 * se_var
    print(f"      Variogram:       H = {H_var:.4f}  (SE={se_var:.4f}, 95% CI=[{ci_var_lo:.4f}, {ci_var_hi:.4f}], R²={r2_var:.4f})")

    print(f"\n  [B] Using log(squared returns) as log-vol proxy:")
    H_rs2, se_rs2, _ = estimate_hurst_rs(log_sq)
    H_dfa2, se_dfa2, _ = estimate_hurst_dfa(log_sq)
    H_var2, se_var2, r2_var2, _ = estimate_hurst_variogram(log_sq, max_lag=100)
    print(f"      R/S analysis:    H = {H_rs2:.4f}  (SE={se_rs2:.4f})")
    print(f"      DFA:             H = {H_dfa2:.4f}  (SE={se_dfa2:.4f})")
    print(f"      Variogram:       H = {H_var2:.4f}  (SE={se_var2:.4f}, R²={r2_var2:.4f})")

    # ---- 3. Roughness test ----
    print_section("3. Roughness Test: H < 0.5?")

    # Use variogram estimate (most standard in rough vol literature)
    H_primary = H_var
    se_primary = se_var
    boots_primary = boots_var

    # One-sided t-test: H0: H >= 0.5 vs H1: H < 0.5
    t_stat_rough = (H_primary - 0.5) / se_primary
    p_rough = stats.norm.cdf(t_stat_rough)  # one-sided

    print(f"  Primary estimator: Variogram (Gatheral et al. 2018)")
    print(f"  H = {H_primary:.4f} ± {se_primary:.4f}")
    print(f"  H0: H >= 0.5  vs  H1: H < 0.5")
    print(f"  t-statistic: {t_stat_rough:.4f}")
    print(f"  p-value (one-sided): {p_rough:.6f}")

    if p_rough < 0.01:
        print(f"  *** RESULT: REJECT H0 at 1% level. Volatility IS rough (H < 0.5). ***")
    elif p_rough < 0.05:
        print(f"  ** RESULT: REJECT H0 at 5% level. Evidence for roughness. **")
    elif p_rough < 0.10:
        print(f"  * RESULT: REJECT H0 at 10% level. Marginal evidence for roughness. *")
    else:
        print(f"  RESULT: FAIL TO REJECT H0. No significant evidence of roughness.")

    # Bootstrap test
    if len(boots_primary) > 0:
        p_boot = np.mean(boots_primary < 0.5)
        print(f"  Bootstrap P(H < 0.5) = {p_boot:.4f} ({int(p_boot*1000)}/1000 samples)")

    # Summary table
    print(f"\n  {'Method':<20s} {'H':>8s} {'SE':>8s} {'95% CI':>22s} {'H<0.5?':>8s}")
    print(f"  {'-'*66}")
    methods = [
        ("R/S (Parkinson)", H_rs, se_rs, ci_rs_lo, ci_rs_hi),
        ("DFA (Parkinson)", H_dfa, se_dfa, ci_dfa_lo, ci_dfa_hi),
        ("Variogram (Park.)", H_var, se_var, ci_var_lo, ci_var_hi),
        ("R/S (sq. ret.)", H_rs2, se_rs2, H_rs2 - 1.96*se_rs2, H_rs2 + 1.96*se_rs2),
        ("DFA (sq. ret.)", H_dfa2, se_dfa2, H_dfa2 - 1.96*se_dfa2, H_dfa2 + 1.96*se_dfa2),
        ("Variogram (sq.ret)", H_var2, se_var2, H_var2 - 1.96*se_var2, H_var2 + 1.96*se_var2),
    ]
    for name, h, se, lo, hi in methods:
        rough = "YES" if hi < 0.5 else ("maybe" if h < 0.5 else "NO")
        print(f"  {name:<20s} {h:>8.4f} {se:>8.4f} [{lo:>8.4f}, {hi:>8.4f}] {rough:>8s}")

    # ---- 4. Scaling behavior: m(q, delta) ----
    print_section("4. Scaling Analysis: m(q, delta) for q = 0.5, 1, 2, 3")

    for q in [0.5, 1.0, 2.0, 3.0]:
        lags = np.arange(1, 101)
        mq = []
        valid_lags = []
        for delta in lags:
            diffs = log_rv[delta:] - log_rv[:-delta]
            if len(diffs) > 10:
                mq.append(np.mean(np.abs(diffs) ** q))
                valid_lags.append(delta)

        log_lags = np.log(valid_lags)
        log_mq = np.log(mq)
        slope, _, r2, _, _ = stats.linregress(log_lags, log_mq)
        zeta_q = slope
        H_q = zeta_q / q
        print(f"  q={q:.1f}: zeta(q)={zeta_q:.4f}, H(q)={H_q:.4f}, R²={r2:.4f}")

    # ---- 5. OOS Forecasting comparison ----
    print_section("5. Out-of-Sample Forecasting: RFSV vs GJR-GARCH")

    # OOS period: 2023-01-01 to 2024-12-31
    oos_start = pd.Timestamp("2023-01-01")
    oos_end = pd.Timestamp("2024-12-31")
    window = 2000

    oos_mask = (dates >= oos_start) & (dates <= oos_end)
    oos_indices = np.where(oos_mask)[0]

    # Filter: need at least `window` observations before OOS start
    valid_oos = oos_indices[oos_indices >= window]
    print(f"  OOS period: {oos_start.date()} to {oos_end.date()}")
    print(f"  OOS observations: {len(valid_oos)}")
    print(f"  Rolling window: {window}")

    if len(valid_oos) < 252:
        print(f"  WARNING: Only {len(valid_oos)} OOS obs. Need >= 252.")
        # Try to extend
        oos_end_ext = dates[-1]
        oos_mask_ext = (dates >= oos_start) & (dates <= oos_end_ext)
        oos_indices_ext = np.where(oos_mask_ext)[0]
        valid_oos_ext = oos_indices_ext[oos_indices_ext >= window]
        if len(valid_oos_ext) >= 252:
            print(f"  Extending OOS to {oos_end_ext.date()}: {len(valid_oos_ext)} obs.")
            valid_oos = valid_oos_ext
            oos_end = oos_end_ext

    assert len(valid_oos) >= 252, f"Insufficient OOS data: {len(valid_oos)} < 252"

    # Use the variogram H estimate for RFSV
    H_use = H_primary
    print(f"  Using H = {H_use:.4f} for RFSV forecaster")

    rfsv = RFSVForecaster(H=H_use, ar_order=5, frac_window=500)

    # Storage for results
    realized_oos = np.zeros(len(valid_oos))
    fc_rfsv = np.zeros(len(valid_oos))
    fc_gjr = np.zeros(len(valid_oos))

    n_total = len(valid_oos)
    print(f"\n  Running rolling forecasts ({n_total} steps)...")

    for i, t in enumerate(valid_oos):
        if (i + 1) % 100 == 0 or i == 0 or i == n_total - 1:
            print(f"    Step {i+1}/{n_total}  (date: {dates[t].date()})")

        # Realized variance at t (the target to forecast)
        realized_oos[i] = rv_parkinson[t]

        # RFSV forecast: use log_rv[t-window:t] to forecast log_rv[t]
        history = log_rv[t - window:t]
        log_fc = rfsv.fit_and_forecast(history)
        fc_rfsv[i] = np.exp(log_fc)

        # GJR-GARCH forecast: use returns[t-window:t] to forecast var at t
        try:
            fc_gjr[i] = gjr_garch_rolling_forecast(returns[:t], window)
        except Exception as e:
            # Fallback: use unconditional variance
            fc_gjr[i] = np.var(returns[t - window:t])

    # Sanity: clip extreme forecasts
    fc_rfsv = np.clip(fc_rfsv, 1e-10, 1.0)
    fc_gjr = np.clip(fc_gjr, 1e-10, 1.0)
    realized_oos = np.maximum(realized_oos, 1e-10)

    # ---- 6. Compute losses ----
    print_section("6. Forecast Evaluation")

    # QLIKE loss (element-wise for DM test)
    qlike_rfsv_vec = realized_oos / fc_rfsv - np.log(realized_oos / fc_rfsv) - 1
    qlike_gjr_vec = realized_oos / fc_gjr - np.log(realized_oos / fc_gjr) - 1

    qlike_rfsv = float(np.mean(qlike_rfsv_vec))
    qlike_gjr = float(np.mean(qlike_gjr_vec))

    # MSE of log variance
    mse_rfsv = float(np.mean((np.log(fc_rfsv) - np.log(realized_oos)) ** 2))
    mse_gjr = float(np.mean((np.log(fc_gjr) - np.log(realized_oos)) ** 2))

    # MAE
    mae_rfsv = float(np.mean(np.abs(np.sqrt(fc_rfsv) - np.sqrt(realized_oos))))
    mae_gjr = float(np.mean(np.abs(np.sqrt(fc_gjr) - np.sqrt(realized_oos))))

    # Correlation
    corr_rfsv = float(np.corrcoef(fc_rfsv, realized_oos)[0, 1])
    corr_gjr = float(np.corrcoef(fc_gjr, realized_oos)[0, 1])

    print(f"\n  {'Metric':<25s} {'RFSV':>15s} {'GJR-GARCH':>15s} {'Winner':>10s}")
    print(f"  {'-'*65}")

    winner_qlike = "RFSV" if qlike_rfsv < qlike_gjr else "GJR"
    print(f"  {'QLIKE':<25s} {qlike_rfsv:>15.6f} {qlike_gjr:>15.6f} {winner_qlike:>10s}")

    winner_mse = "RFSV" if mse_rfsv < mse_gjr else "GJR"
    print(f"  {'MSE(log var)':<25s} {mse_rfsv:>15.6f} {mse_gjr:>15.6f} {winner_mse:>10s}")

    winner_mae = "RFSV" if mae_rfsv < mae_gjr else "GJR"
    print(f"  {'MAE(vol)':<25s} {mae_rfsv:>15.6f} {mae_gjr:>15.6f} {winner_mae:>10s}")

    winner_corr = "RFSV" if corr_rfsv > corr_gjr else "GJR"
    print(f"  {'Corr(fc, realized)':<25s} {corr_rfsv:>15.4f} {corr_gjr:>15.4f} {winner_corr:>10s}")

    # ---- 7. Diebold-Mariano test ----
    print_section("7. Diebold-Mariano Test (QLIKE)")

    dm_stat, dm_pval = dm_test(qlike_rfsv_vec, qlike_gjr_vec, h=1)
    print(f"  H0: RFSV and GJR-GARCH have equal predictive accuracy")
    print(f"  DM statistic: {dm_stat:.4f}")
    print(f"  p-value (two-sided): {dm_pval:.6f}")

    if dm_stat < 0:
        print(f"  Direction: RFSV has LOWER loss (better)")
    else:
        print(f"  Direction: GJR-GARCH has LOWER loss (better)")

    if dm_pval < 0.01:
        print(f"  *** Significant at 1% level ***")
    elif dm_pval < 0.05:
        print(f"  ** Significant at 5% level **")
    elif dm_pval < 0.10:
        print(f"  * Significant at 10% level *")
    else:
        print(f"  Not significant at conventional levels")

    # Also DM test on MSE(log)
    mse_rfsv_vec = (np.log(fc_rfsv) - np.log(realized_oos)) ** 2
    mse_gjr_vec = (np.log(fc_gjr) - np.log(realized_oos)) ** 2
    dm_stat_mse, dm_pval_mse = dm_test(mse_rfsv_vec, mse_gjr_vec, h=1)
    print(f"\n  DM test on MSE(log var):")
    print(f"  DM statistic: {dm_stat_mse:.4f}, p-value: {dm_pval_mse:.6f}")

    # ---- 8. Subsample analysis ----
    print_section("8. Subsample Analysis")

    # Split OOS into halves
    mid = len(valid_oos) // 2
    for label, sl in [("First half", slice(0, mid)), ("Second half", slice(mid, None))]:
        q_rfsv = float(np.mean(qlike_rfsv_vec[sl]))
        q_gjr = float(np.mean(qlike_gjr_vec[sl]))
        winner = "RFSV" if q_rfsv < q_gjr else "GJR"
        d1 = dates[valid_oos[sl.start]].date()
        d2 = dates[valid_oos[min(sl.stop - 1 if sl.stop else len(valid_oos) - 1, len(valid_oos) - 1)]].date()
        print(f"  {label} ({d1} to {d2}): QLIKE RFSV={q_rfsv:.6f}, GJR={q_gjr:.6f} → {winner}")

    # High-vol vs low-vol periods
    med_rv = np.median(realized_oos)
    hi_vol = realized_oos > med_rv
    lo_vol = ~hi_vol
    for label, mask in [("High-vol days", hi_vol), ("Low-vol days", lo_vol)]:
        q_rfsv = float(np.mean(qlike_rfsv_vec[mask]))
        q_gjr = float(np.mean(qlike_gjr_vec[mask]))
        winner = "RFSV" if q_rfsv < q_gjr else "GJR"
        print(f"  {label}: QLIKE RFSV={q_rfsv:.6f}, GJR={q_gjr:.6f} → {winner}")

    # ---- 9. Forecast statistics ----
    print_section("9. Forecast Statistics")

    print(f"  {'Statistic':<25s} {'RFSV':>15s} {'GJR-GARCH':>15s} {'Realized':>15s}")
    print(f"  {'-'*70}")
    print(f"  {'Mean(var)':<25s} {np.mean(fc_rfsv):>15.6e} {np.mean(fc_gjr):>15.6e} {np.mean(realized_oos):>15.6e}")
    print(f"  {'Median(var)':<25s} {np.median(fc_rfsv):>15.6e} {np.median(fc_gjr):>15.6e} {np.median(realized_oos):>15.6e}")
    print(f"  {'Std(var)':<25s} {np.std(fc_rfsv):>15.6e} {np.std(fc_gjr):>15.6e} {np.std(realized_oos):>15.6e}")
    print(f"  {'Mean(ann.vol)':<25s} {np.sqrt(np.mean(fc_rfsv)*252):>15.2%} {np.sqrt(np.mean(fc_gjr)*252):>15.2%} {np.sqrt(np.mean(realized_oos)*252):>15.2%}")

    # Bias
    bias_rfsv = np.mean(fc_rfsv - realized_oos)
    bias_gjr = np.mean(fc_gjr - realized_oos)
    print(f"  {'Bias':<25s} {bias_rfsv:>15.6e} {bias_gjr:>15.6e}")

    # ---- 10. Summary ----
    print_section("SUMMARY", "=")

    print(f"  Hurst Exponent Estimates (log Parkinson RV):")
    print(f"    R/S:        H = {H_rs:.4f} ± {se_rs:.4f}")
    print(f"    DFA:        H = {H_dfa:.4f} ± {se_dfa:.4f}")
    print(f"    Variogram:  H = {H_var:.4f} ± {se_var:.4f}  (primary)")
    print(f"")
    print(f"  Roughness test (H < 0.5):")
    print(f"    t = {t_stat_rough:.4f}, p = {p_rough:.6f}")
    rough_verdict = "YES" if p_rough < 0.05 else "NO (not significant)"
    print(f"    Is SPY volatility rough? {rough_verdict}")
    print(f"")
    print(f"  OOS Forecasting ({len(valid_oos)} days, window={window}):")
    print(f"    QLIKE:  RFSV={qlike_rfsv:.6f}, GJR={qlike_gjr:.6f} → {winner_qlike}")
    print(f"    DM test: stat={dm_stat:.4f}, p={dm_pval:.6f}")
    print(f"")

    # Does RFSV beat the GJR-GARCH QLIKE ceiling?
    if qlike_rfsv < qlike_gjr and dm_pval < 0.05:
        print(f"  *** RFSV SIGNIFICANTLY BEATS GJR-GARCH QLIKE CEILING ***")
    elif qlike_rfsv < qlike_gjr:
        print(f"  RFSV has lower QLIKE but difference is NOT statistically significant")
    else:
        print(f"  GJR-GARCH REMAINS SUPERIOR (RFSV does not beat the ceiling)")

    pct_diff = (qlike_rfsv - qlike_gjr) / qlike_gjr * 100
    print(f"  QLIKE difference: {pct_diff:+.2f}% ({'RFSV worse' if pct_diff > 0 else 'RFSV better'})")
    print(f"{'=' * 72}")

    # Save results
    results = {
        "experiment": "rough_vol_pilot",
        "asset": "SPY",
        "hurst_estimates": {
            "rs_parkinson": {"H": H_rs, "SE": se_rs},
            "dfa_parkinson": {"H": H_dfa, "SE": se_dfa},
            "variogram_parkinson": {"H": H_var, "SE": se_var, "R2": r2_var},
            "rs_sq_returns": {"H": H_rs2, "SE": se_rs2},
            "dfa_sq_returns": {"H": H_dfa2, "SE": se_dfa2},
            "variogram_sq_returns": {"H": H_var2, "SE": se_var2, "R2": r2_var2},
        },
        "roughness_test": {
            "H": H_primary,
            "SE": se_primary,
            "t_stat": t_stat_rough,
            "p_value": p_rough,
            "is_rough": p_rough < 0.05,
        },
        "oos": {
            "period": f"{oos_start.date()} to {oos_end.date()}",
            "n_obs": len(valid_oos),
            "window": window,
            "qlike_rfsv": qlike_rfsv,
            "qlike_gjr": qlike_gjr,
            "mse_log_rfsv": mse_rfsv,
            "mse_log_gjr": mse_gjr,
            "dm_stat_qlike": dm_stat,
            "dm_pval_qlike": dm_pval,
            "dm_stat_mse": dm_stat_mse,
            "dm_pval_mse": dm_pval_mse,
            "winner": winner_qlike,
        },
    }

    import json
    out_path = project_root / "experiments" / "rough_vol_pilot_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to: {out_path}")


if __name__ == "__main__":
    main()
