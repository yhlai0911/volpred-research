"""K794: Multivariate Fractional Brownian Motion for Realized Volatility Forecasting.

Literature basis:
  - arXiv:2504.15985 (April 2025): Cross-asset mfBm with heterogeneous Hurst exponents
    can reduce forecasting errors vs univariate fBm
  - Gatheral, Jaisson & Rosenbaum (2018): "Volatility is rough" — fBm H≈0.1
  - K529: SPY has H≈0.1 (rough), confirmed Gatheral et al.
  - K530: HAR Multi-Scale is champion (DM=-15.45 vs GJR-GARCH)

Research question:
  Does using CROSS-ASSET roughness information improve vol forecasting?
  Different assets have different Hurst exponents H, and their fractional
  increments may be correlated. Can we exploit this?

Models tested:
  1. Univariate fBm (baseline): H-weighted multi-scale mean-reversion for SPY only
  2. Bivariate fBm: SPY + GLD (different H), cross-asset fractional increments
  3. Trivariate fBm: SPY + GLD + EEM (3 assets, 3 H values)
  4. HAR-ABS (baseline): K530's champion model
  5. GJR-GARCH(1,1): standard comparison

Implementation (simplified but correct):
  For each asset i, use log(r²_t) as proxy for log-volatility.
  Estimate H via variogram: E[|X(t+τ) - X(t)|²] = C × τ^(2H)
  HAR-like approximation: fBm forecast ≈ weighted average of past log-vol at
  multiple scales, with weights determined by H.
  For multivariate: add cross-asset log-vol terms with weights from cross-H.

Data: SPY, GLD, EEM from yfinance, start=2006-01-01
OOS:  2023-01-01 to 2024-12-31, expanding window
Eval: QLIKE on r² (Patton 2011), DM test (Harvey t>3.0)

Usage:
    uv run python experiments/k794_multivariate_fbm.py
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

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))


# ============================================================
#  Utility Functions
# ============================================================

def print_section(title: str, char: str = "=", width: int = 72):
    print(f"\n{char * width}")
    print(f"  {title}")
    print(f"{char * width}")


def qlike_loss(realized: np.ndarray, forecast: np.ndarray) -> float:
    """QLIKE loss: mean(realized/forecast - log(realized/forecast) - 1).
    Patton (2011) robust to proxy noise when target is r².
    """
    ratio = realized / forecast
    return float(np.mean(ratio - np.log(ratio) - 1))


def qlike_loss_array(realized: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    """Element-wise QLIKE loss."""
    ratio = realized / forecast
    return ratio - np.log(ratio) - 1


def dm_test(loss1: np.ndarray, loss2: np.ndarray, h: int = 1) -> tuple:
    """Diebold-Mariano test. loss1 - loss2 < 0 means model 1 is better."""
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
#  Hurst Estimation via Variogram (Gatheral et al. 2018)
# ============================================================

def estimate_hurst_variogram(log_vol: np.ndarray, max_lag: int = 50) -> tuple:
    """Variogram estimator: m(2,δ) = E[|log σ_{t+δ} − log σ_t|²]
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


def estimate_cross_hurst(log_vol_i: np.ndarray, log_vol_j: np.ndarray,
                         max_lag: int = 50) -> float:
    """Cross-variogram estimator for cross-Hurst exponent H_ij.
    m_ij(δ) = E[(log σ_i,t+δ − log σ_i,t)(log σ_j,t+δ − log σ_j,t)]
    slope of log |m_ij(δ)| vs log(δ) = 2 * H_ij (if positive cross-memory).
    Returns H_ij.
    """
    T = min(len(log_vol_i), len(log_vol_j))
    if T < max_lag + 10:
        max_lag = max(T // 3, 2)

    lags = np.arange(1, max_lag + 1)
    m_cross = np.empty(len(lags))
    for idx, delta in enumerate(lags):
        di = log_vol_i[delta:T] - log_vol_i[:T - delta]
        dj = log_vol_j[delta:T] - log_vol_j[:T - delta]
        m_cross[idx] = np.mean(di * dj)

    # Use absolute value for log regression (cross-cov can be negative)
    abs_m = np.abs(m_cross)
    valid = abs_m > 0
    if valid.sum() < 3:
        return 0.25  # fallback

    log_lags = np.log(lags[valid].astype(float))
    log_abs_m = np.log(abs_m[valid])

    slope, _, _, _, _ = stats.linregress(log_lags, log_abs_m)
    H_cross = slope / 2.0
    return float(np.clip(H_cross, 0.01, 0.99))


# ============================================================
#  fBm-Inspired Forecasting Models
# ============================================================

def fbm_weights(H: float, scales: list[int]) -> np.ndarray:
    """Generate HAR-like weights based on Hurst exponent.

    fBm with H < 0.5 (rough): more weight on recent observations (anti-persistent).
    fBm with H > 0.5 (smooth): more weight on longer scales (persistent).

    Weights: w_k ∝ scale_k^(2H - 1) for each averaging scale.
    This comes from the fBm autocovariance structure:
      Cov(X(t+τ), X(t)) ∝ τ^(2H) - ... → weight ∝ τ^(2H-1)
    """
    scales_arr = np.array(scales, dtype=float)
    raw_w = scales_arr ** (2 * H - 1)
    # Normalize to sum to 1
    return raw_w / raw_w.sum()


def compute_multiscale_logvol(log_vol: pd.Series, scales: list[int]) -> pd.DataFrame:
    """Compute rolling averages of log-volatility at multiple scales.
    scales = [1, 5, 22] mimics HAR's daily/weekly/monthly.
    """
    result = {}
    for s in scales:
        if s == 1:
            result[f"scale_{s}"] = log_vol
        else:
            result[f"scale_{s}"] = log_vol.rolling(s, min_periods=s).mean()
    return pd.DataFrame(result)


class UnivFBMForecaster:
    """Univariate fBm forecaster: H-weighted multi-scale mean-reversion."""

    def __init__(self, hurst_window: int = 504, scales: list[int] = None):
        self.hurst_window = hurst_window
        self.scales = scales or [1, 5, 22]
        self.H = None

    def fit_predict_oos(self, log_vol: pd.Series, oos_start: str,
                        refit_every: int = 22) -> pd.Series:
        """Rolling OOS forecast with periodic H re-estimation."""
        oos_mask = log_vol.index >= oos_start
        oos_idx = log_vol.index[oos_mask]

        multiscale = compute_multiscale_logvol(log_vol, self.scales)
        forecasts = pd.Series(index=oos_idx, dtype=float)

        last_refit = -999
        for i, date in enumerate(oos_idx):
            loc = log_vol.index.get_loc(date)
            if loc < max(self.scales) + self.hurst_window:
                continue

            # Re-estimate H periodically
            if i - last_refit >= refit_every:
                window_data = log_vol.iloc[loc - self.hurst_window:loc].values
                self.H, _ = estimate_hurst_variogram(window_data, max_lag=50)
                self.H = np.clip(self.H, 0.01, 0.99)
                last_refit = i

            # Forecast: H-weighted combination of multi-scale log-vol
            weights = fbm_weights(self.H, self.scales)
            ms_vals = multiscale.iloc[loc - 1]  # shift(1): use yesterday's info
            forecast_logvol = np.dot(weights, ms_vals.values)
            forecasts.iloc[i] = forecast_logvol

        return forecasts.dropna()


class MultiFBMForecaster:
    """Multivariate fBm forecaster: cross-asset fractional memory."""

    def __init__(self, hurst_window: int = 504, scales: list[int] = None):
        self.hurst_window = hurst_window
        self.scales = scales or [1, 5, 22]

    def fit_predict_oos(self, log_vols: dict[str, pd.Series],
                        target_asset: str, oos_start: str,
                        refit_every: int = 22) -> pd.Series:
        """Rolling OOS forecast using cross-asset fBm information.

        Key insight from arXiv:2504.15985:
        The multivariate fBm has cross-covariance:
          Cov(X_i(t+τ), X_j(t)) depends on H_i, H_j, and ρ_ij
        We approximate this with cross-asset weighted multi-scale averages.
        """
        assets = list(log_vols.keys())
        n_assets = len(assets)

        # Align all assets
        common_idx = log_vols[assets[0]].index
        for a in assets[1:]:
            common_idx = common_idx.intersection(log_vols[a].index)
        aligned = {a: log_vols[a].reindex(common_idx) for a in assets}

        oos_mask = common_idx >= oos_start
        oos_idx = common_idx[oos_mask]

        # Multiscale features for all assets
        multiscales = {a: compute_multiscale_logvol(aligned[a], self.scales)
                       for a in assets}

        forecasts = pd.Series(index=oos_idx, dtype=float)

        last_refit = -999
        H_dict = {}
        cross_H = {}
        cross_corr = {}
        own_weight = 0.6  # weight for own-asset signal

        for i, date in enumerate(oos_idx):
            loc = common_idx.get_loc(date)
            if loc < max(self.scales) + self.hurst_window:
                continue

            # Re-estimate H and cross-correlations periodically
            if i - last_refit >= refit_every:
                for a in assets:
                    window_data = aligned[a].iloc[loc - self.hurst_window:loc].values
                    h_val, _ = estimate_hurst_variogram(window_data, max_lag=50)
                    H_dict[a] = np.clip(h_val, 0.01, 0.99)

                # Cross-Hurst exponents and correlations
                for j, a2 in enumerate(assets):
                    if a2 == target_asset:
                        continue
                    w1 = aligned[target_asset].iloc[loc - self.hurst_window:loc].values
                    w2 = aligned[a2].iloc[loc - self.hurst_window:loc].values
                    cross_H[(target_asset, a2)] = estimate_cross_hurst(w1, w2, max_lag=50)
                    # Rolling correlation of fractional increments
                    d1 = np.diff(w1)
                    d2 = np.diff(w2)
                    cross_corr[(target_asset, a2)] = np.corrcoef(d1, d2)[0, 1]

                last_refit = i

            if target_asset not in H_dict:
                continue

            # Own-asset forecast (univariate fBm)
            own_weights = fbm_weights(H_dict[target_asset], self.scales)
            own_ms = multiscales[target_asset].iloc[loc - 1]  # shift(1)
            own_forecast = np.dot(own_weights, own_ms.values)

            # Cross-asset contributions
            cross_forecast = 0.0
            cross_total_weight = 0.0
            for a2 in assets:
                if a2 == target_asset:
                    continue
                if a2 not in H_dict:
                    continue

                # Weight for cross-asset contribution:
                # Higher cross-correlation → more useful
                # Cross-H determines scale weighting
                rho = cross_corr.get((target_asset, a2), 0.0)
                abs_rho = abs(rho)
                if abs_rho < 0.05:  # skip near-zero correlation
                    continue

                h_cross = cross_H.get((target_asset, a2), 0.25)
                cross_w = fbm_weights(h_cross, self.scales)
                other_ms = multiscales[a2].iloc[loc - 1]  # shift(1)
                other_val = np.dot(cross_w, other_ms.values)

                # Contribution = correlation-weighted other-asset signal
                cross_forecast += abs_rho * np.sign(rho) * other_val
                cross_total_weight += abs_rho

            # Combine own + cross
            if cross_total_weight > 0:
                cross_forecast /= cross_total_weight
                forecast_logvol = own_weight * own_forecast + (1 - own_weight) * cross_forecast
            else:
                forecast_logvol = own_forecast

            forecasts.iloc[i] = forecast_logvol

        return forecasts.dropna()


class HARAbsForecaster:
    """HAR-ABS model (K530 champion). Uses |r| as target, HAR(1,5,22) regressors."""

    def __init__(self, scales: list[int] = None):
        self.scales = scales or [1, 5, 22]

    def fit_predict_oos(self, abs_ret: pd.Series, oos_start: str,
                        refit_every: int = 22) -> pd.Series:
        """Rolling OOS with expanding window OLS."""
        multiscale = compute_multiscale_logvol(abs_ret, self.scales)

        oos_mask = abs_ret.index >= oos_start
        oos_idx = abs_ret.index[oos_mask]
        forecasts = pd.Series(index=oos_idx, dtype=float)

        last_refit = -999
        beta = None

        for i, date in enumerate(oos_idx):
            loc = abs_ret.index.get_loc(date)
            if loc < max(self.scales) + 100:
                continue

            # Re-estimate periodically
            if i - last_refit >= refit_every or beta is None:
                # Expanding window: use all data up to loc
                y = abs_ret.iloc[max(self.scales):loc].values
                X_data = multiscale.iloc[max(self.scales) - 1:loc - 1].values  # shift(1)

                # Filter valid rows
                valid = ~np.isnan(X_data).any(axis=1) & ~np.isnan(y)
                y_v = y[valid]
                X_v = X_data[valid]

                if len(y_v) < 50:
                    continue

                # OLS with intercept
                X_v = np.column_stack([np.ones(len(X_v)), X_v])
                try:
                    beta = np.linalg.lstsq(X_v, y_v, rcond=None)[0]
                except np.linalg.LinAlgError:
                    continue
                last_refit = i

            if beta is None:
                continue

            # Forecast using yesterday's multiscale (shift 1)
            x_today = multiscale.iloc[loc - 1].values
            if np.any(np.isnan(x_today)):
                continue
            x_today = np.concatenate([[1.0], x_today])
            forecasts.iloc[i] = np.dot(beta, x_today)

        return forecasts.dropna()


class GJRGarchForecaster:
    """GJR-GARCH(1,1) via arch package."""

    def fit_predict_oos(self, returns: pd.Series, oos_start: str,
                        refit_every: int = 22) -> pd.Series:
        """Rolling OOS GJR-GARCH forecast."""
        from arch import arch_model

        oos_mask = returns.index >= oos_start
        oos_idx = returns.index[oos_mask]
        forecasts = pd.Series(index=oos_idx, dtype=float)

        last_refit = -999
        model_fit = None

        for i, date in enumerate(oos_idx):
            loc = returns.index.get_loc(date)
            if loc < 500:
                continue

            if i - last_refit >= refit_every or model_fit is None:
                train = returns.iloc[:loc] * 100  # scale for arch
                try:
                    am = arch_model(train, vol="GARCH", p=1, o=1, q=1,
                                    dist="t", mean="Zero")
                    model_fit = am.fit(disp="off", show_warning=False)
                except Exception:
                    continue
                last_refit = i

            if model_fit is None:
                continue

            # 1-step forecast: conditional variance
            try:
                fc = model_fit.forecast(horizon=1, reindex=False)
                var_forecast = fc.variance.iloc[-1, 0] / 10000  # unscale
                forecasts.iloc[i] = var_forecast
            except Exception:
                continue

        return forecasts.dropna()


# ============================================================
#  Main Experiment
# ============================================================

def main():
    t0 = time.time()
    print_section("K794: Multivariate fBm for Vol Forecasting")
    print("Reference: arXiv:2504.15985 (April 2025)")
    print("Question: Does cross-asset roughness improve vol forecasting?")

    # ----------------------------------------------------------
    #  1. Data Download
    # ----------------------------------------------------------
    print_section("1. Data Download", "-")
    import yfinance as yf

    assets = {"SPY": "SPY", "GLD": "GLD", "EEM": "EEM"}
    start_date = "2006-01-01"
    end_date = "2025-12-31"

    prices = {}
    returns = {}
    for name, ticker in assets.items():
        df = yf.download(ticker, start=start_date, end=end_date,
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        prices[name] = df["Close"]
        returns[name] = np.log(df["Close"] / df["Close"].shift(1)).dropna()
        print(f"  {name}: {len(returns[name])} obs, "
              f"{returns[name].index[0].strftime('%Y-%m-%d')} to "
              f"{returns[name].index[-1].strftime('%Y-%m-%d')}")

    # Align all return series
    common_dates = returns["SPY"].index
    for a in ["GLD", "EEM"]:
        common_dates = common_dates.intersection(returns[a].index)
    for a in assets:
        returns[a] = returns[a].reindex(common_dates).dropna()
    print(f"  Common dates: {len(common_dates)}")

    # ----------------------------------------------------------
    #  2. Descriptive Statistics & Hurst Estimation
    # ----------------------------------------------------------
    print_section("2. Descriptive Statistics & Hurst Estimation", "-")

    # Log-volatility proxy: log(r²)
    log_vol = {}
    r_squared = {}
    abs_ret = {}
    for a in assets:
        r = returns[a]
        # Avoid log(0): use max(r², floor)
        r2 = r ** 2
        r2_floor = r2.clip(lower=1e-10)
        r_squared[a] = r2_floor
        log_vol[a] = np.log(r2_floor)
        abs_ret[a] = r.abs()
        print(f"\n  {a}:")
        print(f"    Mean return:  {r.mean() * 252:.4f} (annualized)")
        print(f"    Std return:   {r.std() * np.sqrt(252):.4f} (annualized)")
        print(f"    Skewness:     {r.skew():.4f}")
        print(f"    Kurtosis:     {r.kurtosis():.4f}")

    # Full-sample Hurst estimation
    print("\n  Full-sample Hurst exponents (variogram, max_lag=50):")
    H_full = {}
    for a in assets:
        lv = log_vol[a].dropna().values
        H, R2 = estimate_hurst_variogram(lv, max_lag=50)
        H_full[a] = H
        print(f"    {a}: H = {H:.4f}  (R² = {R2:.4f})")

    # Cross-Hurst
    print("\n  Cross-Hurst exponents:")
    pairs = [("SPY", "GLD"), ("SPY", "EEM"), ("GLD", "EEM")]
    cross_H_full = {}
    for a1, a2 in pairs:
        lv1 = log_vol[a1].dropna().values
        lv2 = log_vol[a2].dropna().values
        n = min(len(lv1), len(lv2))
        h_cross = estimate_cross_hurst(lv1[:n], lv2[:n], max_lag=50)
        cross_H_full[(a1, a2)] = h_cross
        # Also compute increment correlation
        d1 = np.diff(lv1[:n])
        d2 = np.diff(lv2[:n])
        rho = np.corrcoef(d1, d2)[0, 1]
        print(f"    {a1}-{a2}: H_cross = {h_cross:.4f}, increment_corr = {rho:.4f}")

    # ----------------------------------------------------------
    #  3. OOS Forecasting
    # ----------------------------------------------------------
    print_section("3. OOS Forecasting (2023-01-01 ~ 2024-12-31)", "-")
    oos_start = "2023-01-01"

    # Target: SPY r² (Patton 2011 QLIKE proxy-robust)
    spy_r2 = r_squared["SPY"]
    spy_r2_oos = spy_r2[spy_r2.index >= oos_start]
    print(f"  SPY OOS observations: {len(spy_r2_oos)}")

    # --- Model 1: Univariate fBm (SPY only) ---
    print("\n  [1/5] Univariate fBm (SPY)...")
    univ_fbm = UnivFBMForecaster(hurst_window=504, scales=[1, 5, 22])
    univ_fc_logvol = univ_fbm.fit_predict_oos(log_vol["SPY"], oos_start, refit_every=22)
    # Convert log-vol forecast to variance: exp(forecast)
    univ_fc_var = np.exp(univ_fc_logvol)
    print(f"    Forecasts: {len(univ_fc_var)}, final H = {univ_fbm.H:.4f}")

    # --- Model 2: Bivariate fBm (SPY + GLD) ---
    print("\n  [2/5] Bivariate fBm (SPY + GLD)...")
    biv_fbm = MultiFBMForecaster(hurst_window=504, scales=[1, 5, 22])
    biv_log_vols = {"SPY": log_vol["SPY"], "GLD": log_vol["GLD"]}
    biv_fc_logvol = biv_fbm.fit_predict_oos(biv_log_vols, "SPY", oos_start, refit_every=22)
    biv_fc_var = np.exp(biv_fc_logvol)
    print(f"    Forecasts: {len(biv_fc_var)}")

    # --- Model 3: Trivariate fBm (SPY + GLD + EEM) ---
    print("\n  [3/5] Trivariate fBm (SPY + GLD + EEM)...")
    triv_fbm = MultiFBMForecaster(hurst_window=504, scales=[1, 5, 22])
    triv_log_vols = {"SPY": log_vol["SPY"], "GLD": log_vol["GLD"], "EEM": log_vol["EEM"]}
    triv_fc_logvol = triv_fbm.fit_predict_oos(triv_log_vols, "SPY", oos_start, refit_every=22)
    triv_fc_var = np.exp(triv_fc_logvol)
    print(f"    Forecasts: {len(triv_fc_var)}")

    # --- Model 4: HAR-ABS (baseline champion) ---
    print("\n  [4/5] HAR-ABS (K530 champion)...")
    har_abs = HARAbsForecaster(scales=[1, 5, 22])
    har_fc_abs = har_abs.fit_predict_oos(abs_ret["SPY"], oos_start, refit_every=22)
    # Convert |r| forecast to variance: (E[|r|])² × π/2 ≈ (forecast)² × 1.5708
    har_fc_var = (har_fc_abs ** 2) * (np.pi / 2)
    print(f"    Forecasts: {len(har_fc_var)}")

    # --- Model 5: GJR-GARCH(1,1) ---
    print("\n  [5/5] GJR-GARCH(1,1)...")
    gjr = GJRGarchForecaster()
    gjr_fc_var = gjr.fit_predict_oos(returns["SPY"], oos_start, refit_every=22)
    print(f"    Forecasts: {len(gjr_fc_var)}")

    # ----------------------------------------------------------
    #  4. Evaluation
    # ----------------------------------------------------------
    print_section("4. Evaluation — QLIKE on r² (Patton 2011)", "-")

    # Align all forecasts to common dates
    models = {
        "Univ_fBm": univ_fc_var,
        "Biv_fBm_SPY_GLD": biv_fc_var,
        "Triv_fBm_SPY_GLD_EEM": triv_fc_var,
        "HAR_ABS": har_fc_var,
        "GJR_GARCH": gjr_fc_var,
    }

    # Find common OOS dates across all models
    common_oos = spy_r2_oos.index
    for name, fc in models.items():
        common_oos = common_oos.intersection(fc.index)
    print(f"  Common OOS dates: {len(common_oos)}")

    # Realized values (target)
    realized = spy_r2.reindex(common_oos).values

    # Compute forecasts on common dates
    forecasts_aligned = {}
    for name, fc in models.items():
        f = fc.reindex(common_oos).values
        # Floor forecasts to avoid division by zero
        f = np.maximum(f, 1e-12)
        forecasts_aligned[name] = f

    # QLIKE
    print(f"\n  {'Model':<30s} {'QLIKE':>10s} {'Rank':>6s}")
    print(f"  {'-'*46}")
    qlike_scores = {}
    for name, f in forecasts_aligned.items():
        ql = qlike_loss(realized, f)
        qlike_scores[name] = ql

    # Rank
    ranked = sorted(qlike_scores.items(), key=lambda x: x[1])
    for rank, (name, ql) in enumerate(ranked, 1):
        marker = " <-- BEST" if rank == 1 else ""
        print(f"  {name:<30s} {ql:>10.4f} {rank:>6d}{marker}")

    # ----------------------------------------------------------
    #  5. DM Tests
    # ----------------------------------------------------------
    print_section("5. DM Tests (pairwise)", "-")

    # Compute QLIKE loss arrays
    qlike_arrays = {}
    for name, f in forecasts_aligned.items():
        qlike_arrays[name] = qlike_loss_array(realized, f)

    # DM tests: each model vs GJR-GARCH and vs HAR-ABS
    dm_results = {}
    ref_models = ["GJR_GARCH", "HAR_ABS"]
    test_models = ["Univ_fBm", "Biv_fBm_SPY_GLD", "Triv_fBm_SPY_GLD_EEM"]

    print(f"  {'Comparison':<45s} {'DM stat':>10s} {'p-value':>10s} {'Winner':>12s}")
    print(f"  {'-'*77}")

    for test_m in test_models:
        for ref_m in ref_models:
            stat, pval = dm_test(qlike_arrays[test_m], qlike_arrays[ref_m])
            sig = "***" if abs(stat) > 3.0 else ("**" if abs(stat) > 2.0 else
                   ("*" if abs(stat) > 1.65 else ""))
            winner = test_m.split("_")[0] if stat < 0 else ref_m.split("_")[0]
            label = f"{test_m} vs {ref_m}"
            dm_results[label] = {"dm_stat": stat, "p_value": pval}
            print(f"  {label:<45s} {stat:>10.3f} {pval:>10.4f} {winner:>10s} {sig}")

    # Also: Bivariate vs Univariate
    stat, pval = dm_test(qlike_arrays["Biv_fBm_SPY_GLD"], qlike_arrays["Univ_fBm"])
    dm_results["Biv_vs_Univ"] = {"dm_stat": stat, "p_value": pval}
    print(f"\n  {'Biv_fBm vs Univ_fBm':<45s} {stat:>10.3f} {pval:>10.4f} "
          f"{'Biv' if stat < 0 else 'Univ':>10s}")

    stat, pval = dm_test(qlike_arrays["Triv_fBm_SPY_GLD_EEM"], qlike_arrays["Univ_fBm"])
    dm_results["Triv_vs_Univ"] = {"dm_stat": stat, "p_value": pval}
    print(f"  {'Triv_fBm vs Univ_fBm':<45s} {stat:>10.3f} {pval:>10.4f} "
          f"{'Triv' if stat < 0 else 'Univ':>10s}")

    stat, pval = dm_test(qlike_arrays["Triv_fBm_SPY_GLD_EEM"],
                         qlike_arrays["Biv_fBm_SPY_GLD"])
    dm_results["Triv_vs_Biv"] = {"dm_stat": stat, "p_value": pval}
    print(f"  {'Triv_fBm vs Biv_fBm':<45s} {stat:>10.3f} {pval:>10.4f} "
          f"{'Triv' if stat < 0 else 'Biv':>10s}")

    # ----------------------------------------------------------
    #  6. Spearman Rank Correlation (distribution-free)
    # ----------------------------------------------------------
    print_section("6. Spearman Rank Correlation", "-")
    spearman_results = {}
    for name, f in forecasts_aligned.items():
        rho, pval = stats.spearmanr(realized, f)
        spearman_results[name] = {"rho": float(rho), "p_value": float(pval)}
        sig = "***" if pval < 0.001 else ("**" if pval < 0.01 else
              ("*" if pval < 0.05 else ""))
        print(f"  {name:<30s}  rho = {rho:.4f}  (p = {pval:.4f}) {sig}")

    # ----------------------------------------------------------
    #  7. Sub-period Analysis
    # ----------------------------------------------------------
    print_section("7. Sub-period Analysis", "-")

    sub_periods = [
        ("2023-H1", "2023-01-01", "2023-06-30"),
        ("2023-H2", "2023-07-01", "2023-12-31"),
        ("2024-H1", "2024-01-01", "2024-06-30"),
        ("2024-H2", "2024-07-01", "2024-12-31"),
    ]

    sub_period_qlike = {}
    for period_name, p_start, p_end in sub_periods:
        mask = (common_oos >= p_start) & (common_oos <= p_end)
        if mask.sum() < 20:
            continue
        sub_realized = realized[mask]
        sub_period_qlike[period_name] = {}
        for name, f in forecasts_aligned.items():
            sub_f = f[mask]
            ql = qlike_loss(sub_realized, sub_f)
            sub_period_qlike[period_name][name] = ql

    # Print table
    model_names = list(models.keys())
    header = f"  {'Period':<12s}" + "".join(f"{m:<22s}" for m in model_names)
    print(header)
    print(f"  {'-' * (12 + 22 * len(model_names))}")
    for period_name in sub_period_qlike:
        row = f"  {period_name:<12s}"
        vals = sub_period_qlike[period_name]
        best_val = min(vals.values())
        for m in model_names:
            v = vals[m]
            marker = " *" if v == best_val else ""
            row += f"{v:<22.4f}"
        print(row)

    # ----------------------------------------------------------
    #  8. Sensitivity to Own-Weight Parameter
    # ----------------------------------------------------------
    print_section("8. Sensitivity: own_weight parameter (Bivariate)", "-")
    sensitivity_results = {}
    for ow in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
        biv_sens = MultiFBMForecaster(hurst_window=504, scales=[1, 5, 22])
        # We need to modify own_weight — reconstruct the forecast
        # For efficiency, use existing forecasts and reweight
        # own_forecast and cross_forecast are not stored separately,
        # so we approximate: at ow=1.0 it equals univariate
        # Approximate by blending univariate and bivariate
        if ow == 1.0:
            blended = univ_fc_var.reindex(common_oos).values
        else:
            # Solve for cross component: biv = 0.6*univ + 0.4*cross
            # cross = (biv - 0.6*univ) / 0.4
            u = univ_fc_var.reindex(common_oos).values
            b = biv_fc_var.reindex(common_oos).values
            cross_component = (b - 0.6 * u) / 0.4
            blended = ow * u + (1 - ow) * cross_component

        blended = np.maximum(blended, 1e-12)
        valid = ~np.isnan(blended)
        if valid.sum() > 50:
            ql = qlike_loss(realized[valid], blended[valid])
            sensitivity_results[ow] = ql
            print(f"    own_weight = {ow:.1f}: QLIKE = {ql:.4f}")

    # ----------------------------------------------------------
    #  9. Summary
    # ----------------------------------------------------------
    print_section("9. Summary & Conclusions", "-")

    best_model = ranked[0][0]
    best_qlike = ranked[0][1]

    # Key findings
    univ_qlike = qlike_scores.get("Univ_fBm", None)
    biv_qlike = qlike_scores.get("Biv_fBm_SPY_GLD", None)
    triv_qlike = qlike_scores.get("Triv_fBm_SPY_GLD_EEM", None)

    print(f"  Best model: {best_model} (QLIKE = {best_qlike:.4f})")
    print()

    if biv_qlike and univ_qlike:
        pct = (biv_qlike - univ_qlike) / univ_qlike * 100
        print(f"  Bivariate vs Univariate: {pct:+.2f}% QLIKE change")
        print(f"    → {'Cross-asset info HELPS' if pct < 0 else 'Cross-asset info does NOT help'}")

    if triv_qlike and univ_qlike:
        pct = (triv_qlike - univ_qlike) / univ_qlike * 100
        print(f"  Trivariate vs Univariate: {pct:+.2f}% QLIKE change")
        print(f"    → {'3-asset info adds value' if pct < 0 else '3-asset info does NOT add value'}")

    # vs baselines
    gjr_qlike = qlike_scores.get("GJR_GARCH", None)
    har_qlike = qlike_scores.get("HAR_ABS", None)
    print()
    if best_qlike and gjr_qlike:
        pct = (best_qlike - gjr_qlike) / gjr_qlike * 100
        print(f"  Best fBm vs GJR-GARCH: {pct:+.2f}% QLIKE")
    if best_qlike and har_qlike:
        pct = (best_qlike - har_qlike) / har_qlike * 100
        print(f"  Best fBm vs HAR-ABS: {pct:+.2f}% QLIKE")

    elapsed = time.time() - t0
    print(f"\n  Total runtime: {elapsed:.1f}s")

    # ----------------------------------------------------------
    #  10. Save Results
    # ----------------------------------------------------------
    results = {
        "experiment_id": "K794",
        "title": "Multivariate fBm for Realized Volatility Forecasting",
        "reference": "arXiv:2504.15985 (April 2025)",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "data_source": "yfinance",
        "assets": list(assets.keys()),
        "data_period": f"{start_date} to {end_date}",
        "oos_period": "2023-01-01 to 2024-12-31",
        "oos_observations": int(len(common_oos)),
        "hurst_full_sample": {a: round(H_full[a], 4) for a in assets},
        "cross_hurst_full_sample": {
            f"{a1}-{a2}": round(cross_H_full[(a1, a2)], 4)
            for a1, a2 in pairs
        },
        "qlike_results": {name: round(ql, 4) for name, ql in ranked},
        "qlike_ranking": [name for name, _ in ranked],
        "dm_tests": {k: {kk: round(vv, 4) for kk, vv in v.items()}
                     for k, v in dm_results.items()},
        "spearman_correlations": {k: {kk: round(vv, 4) for kk, vv in v.items()}
                                  for k, v in spearman_results.items()},
        "sub_period_qlike": {
            p: {m: round(v, 4) for m, v in vals.items()}
            for p, vals in sub_period_qlike.items()
        },
        "sensitivity_own_weight": {str(k): round(v, 4) for k, v in sensitivity_results.items()},
        "conclusions": {
            "best_model": best_model,
            "cross_asset_helps": bool(biv_qlike and biv_qlike < univ_qlike) if biv_qlike and univ_qlike else None,
            "trivariate_helps": bool(triv_qlike and triv_qlike < univ_qlike) if triv_qlike and univ_qlike else None,
            "beats_gjr": bool(best_qlike < gjr_qlike) if gjr_qlike else None,
            "beats_har": bool(best_qlike < har_qlike) if har_qlike else None,
        },
        "runtime_seconds": round(elapsed, 1),
        "methodology_notes": [
            "Hurst estimated via variogram (Gatheral et al. 2018)",
            "HAR-like approximation with H-dependent weights for fBm forecast",
            "Cross-asset via correlation-weighted fractional increments",
            "Own-weight = 0.6 for multivariate (tested sensitivity 0.3-1.0)",
            "QLIKE on r² is Patton (2011) proxy-robust",
            "signal.shift(1) enforced in all models (no lookahead)"
        ],
        "limitations": [
            "Daily r² is noisy proxy for true volatility",
            "HAR-like approximation, not true fBm conditional expectation",
            "Own-weight fixed at 0.6 (could optimize but risk overfitting)",
            "Cross-Hurst via cross-variogram is approximate",
            "No 5-min intraday data — daily proxies only"
        ]
    }

    out_path = Path(__file__).parent / "k794_multivariate_fbm_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n  Results saved to: {out_path}")


if __name__ == "__main__":
    main()
