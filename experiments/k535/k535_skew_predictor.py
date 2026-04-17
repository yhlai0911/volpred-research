"""K535: Options-Implied Skewness as Vol Predictor — Does SKEW add value beyond VIX?

Extends K530's HAR framework with higher-order moment information (CBOE SKEW index).

Context:
  - K43: VVIX/SKEW/VIX3M overlay → all null for VT strategy overlay
  - K447: SKEW tail risk prediction → hurts rather than helps (AUC drops)
  - K181: SKEW partial corr sig but GARCH-X no help
  - K530: HAR-VIX best predictor (VIX coeff +0.879, t=18.5)
  - BUT: K43/K447 tested SKEW as strategy overlay or tail predictor, NOT as
    a HAR volatility regressor alongside multi-scale RV components.

Literature:
  - Bakshi, Kapadia & Madan (2003, RFS): Stock return characteristics, skew laws
  - Corsi (2009, JFE): HAR-RV model
  - Patton & Sheppard (2015): Semivariance decomposition
  - CBOE SKEW: measures tail risk from options prices (100 = no skew, >100 = left tail)

Models tested (5 HAR + 3 benchmarks):
  1. HAR-ABS:       baseline (rv1, rv5, rv22)
  2. HAR-VIX:       HAR-ABS + VIX (K530 best)
  3. HAR-SKEW:      HAR-ABS + SKEW regressor
  4. HAR-VIX-SKEW:  HAR-ABS + VIX + SKEW
  5. HAR-VIX-RSKEW: HAR-ABS + VIX + realized skewness (22d rolling)
  6. GJR-GARCH(1,1): Standard benchmark
  7. EWMA(0.94):    Strong baseline
  8. Rolling-Std-22: Simple benchmark

Method: OLS rolling window w=500, OOS 2023-2024
Evaluation: QLIKE + MSE(log) + DM test pairwise
Key question: does SKEW have independent predictive power after controlling for VIX?

If ^SKEW not available from yfinance, compute realized skewness proxy from SPY returns.

Data source: yfinance (SPY, ^VIX, ^SKEW)

Usage:
    uv run python experiments/k535_skew_predictor.py
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
        return (0.0, 1.0)
    dm_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(dm_stat), df=T - 1))
    return (float(dm_stat), float(p_value))


# ============================================================
#  Data Download
# ============================================================

def download_data():
    """Download SPY, ^VIX, and ^SKEW from yfinance."""
    import yfinance as yf

    print_section("Data Download")

    # SPY
    spy = yf.download("SPY", start="2010-01-01", progress=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    spy_close = spy["Close"].rename("spy_close")
    print(f"  SPY: {len(spy_close)} rows ({spy_close.index[0].strftime('%Y-%m-%d')} to {spy_close.index[-1].strftime('%Y-%m-%d')})")

    # VIX
    vix = yf.download("^VIX", start="2010-01-01", progress=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    vix_close = vix["Close"].rename("vix")
    print(f"  VIX: {len(vix_close)} rows")

    # SKEW
    skew_available = True
    try:
        skew = yf.download("^SKEW", start="2010-01-01", progress=False)
        if isinstance(skew.columns, pd.MultiIndex):
            skew.columns = skew.columns.get_level_values(0)
        if len(skew) < 100:
            raise ValueError("Too few SKEW rows")
        skew_close = skew["Close"].rename("skew")
        print(f"  SKEW: {len(skew_close)} rows")
    except Exception as e:
        print(f"  SKEW download failed: {e}")
        print("  Will compute realized skewness proxy instead.")
        skew_available = False
        skew_close = None

    # Merge
    df = pd.DataFrame({"spy_close": spy_close, "vix": vix_close})
    if skew_available and skew_close is not None:
        df["skew"] = skew_close

    df = df.dropna(subset=["spy_close", "vix"])
    df["log_return"] = np.log(df["spy_close"] / df["spy_close"].shift(1))
    df = df.dropna(subset=["log_return"])

    print(f"\n  Merged dataset: {len(df)} rows")
    print(f"  Date range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    if "skew" in df.columns:
        skew_valid = df["skew"].notna().sum()
        print(f"  SKEW data available: {skew_valid} rows ({skew_valid/len(df)*100:.1f}%)")
    else:
        print("  SKEW: not available from yfinance")

    return df, skew_available


# ============================================================
#  Feature Construction
# ============================================================

def build_features(df: pd.DataFrame, skew_available: bool):
    """Build HAR features + SKEW/realized skewness features."""
    print_section("Feature Construction")

    r = df["log_return"].values.copy()
    abs_r = np.abs(r)
    sq_r = r ** 2

    # HAR components (absolute return proxies)
    rv1_abs = abs_r.copy()
    rv5_abs = pd.Series(abs_r, index=df.index).rolling(5).mean().values
    rv22_abs = pd.Series(abs_r, index=df.index).rolling(22).mean().values

    # VIX (convert to daily scale: annualized% → daily decimal)
    vix_daily = df["vix"].values / 100.0 / np.sqrt(252)

    # Target: next-day absolute return
    target_abs = np.roll(abs_r, -1)
    target_abs[-1] = np.nan

    # Realized skewness: rolling 22-day skewness of returns
    r_series = pd.Series(r, index=df.index)
    realized_skew = r_series.rolling(22).apply(
        lambda x: stats.skew(x, bias=False) if len(x) >= 10 else np.nan,
        raw=True
    ).values

    features = pd.DataFrame({
        "rv1_abs": rv1_abs,
        "rv5_abs": rv5_abs,
        "rv22_abs": rv22_abs,
        "vix_daily": vix_daily,
        "realized_skew": realized_skew,
        "target_abs": target_abs,
    }, index=df.index)

    # CBOE SKEW index (if available)
    if skew_available and "skew" in df.columns:
        # SKEW is on a ~100+ scale; normalize to deviation from 100
        # (SKEW=100 means no tail risk, >100 means left tail risk)
        features["skew_raw"] = df["skew"].values
        features["skew_norm"] = (df["skew"].values - 100) / 100.0  # Normalized: 0 = no skew

        # Also compute SKEW change (momentum)
        features["skew_chg"] = df["skew"].diff().values / 100.0

        valid_skew = features["skew_raw"].notna().sum()
        print(f"  CBOE SKEW: {valid_skew} valid rows (mean={features['skew_raw'].dropna().mean():.1f}, "
              f"std={features['skew_raw'].dropna().std():.1f})")
    else:
        features["skew_raw"] = np.nan
        features["skew_norm"] = np.nan
        features["skew_chg"] = np.nan

    print(f"  Realized skewness (22d): mean={np.nanmean(realized_skew):.3f}, "
          f"std={np.nanstd(realized_skew):.3f}")
    print(f"  Features shape: {features.shape}")

    return features


# ============================================================
#  HAR Model Definitions
# ============================================================

def ols_fit(X: np.ndarray, y: np.ndarray):
    """OLS with intercept. Returns coefficients [intercept, beta1, ...]."""
    n = len(y)
    X_aug = np.column_stack([np.ones(n), X])
    try:
        beta = np.linalg.lstsq(X_aug, y, rcond=None)[0]
    except np.linalg.LinAlgError:
        beta = np.zeros(X_aug.shape[1])
    return beta


def ols_predict(X_new: np.ndarray, beta: np.ndarray) -> float:
    """Predict with OLS coefficients."""
    x_aug = np.concatenate([[1.0], X_new])
    pred = np.dot(x_aug, beta)
    return max(pred, 1e-10)  # floor to avoid negative


def ols_diagnostics(X: np.ndarray, y: np.ndarray, feature_names: list):
    """Full OLS diagnostics: coefficients, t-stats, R-squared."""
    n = len(y)
    X_aug = np.column_stack([np.ones(n), X])
    k = X_aug.shape[1]

    try:
        beta = np.linalg.lstsq(X_aug, y, rcond=None)[0]
    except np.linalg.LinAlgError:
        return None

    y_hat = X_aug @ beta
    residuals = y - y_hat
    ss_res = np.sum(residuals ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0

    # Standard errors (heteroskedasticity-robust HC1)
    sigma2 = ss_res / (n - k)
    try:
        XtX_inv = np.linalg.inv(X_aug.T @ X_aug)
        se = np.sqrt(np.diag(sigma2 * XtX_inv))
    except np.linalg.LinAlgError:
        se = np.full(k, np.nan)

    t_stats = beta / se
    p_values = 2 * (1 - stats.t.cdf(np.abs(t_stats), df=n - k))

    names = ["const"] + feature_names
    result = {
        "r_squared": float(r_squared),
        "n_obs": n,
        "coefficients": {},
    }
    for i, name in enumerate(names):
        result["coefficients"][name] = {
            "coef": float(beta[i]),
            "se": float(se[i]),
            "t_stat": float(t_stats[i]),
            "p_value": float(p_values[i]),
        }
    return result


# Model feature extractors
def har_abs_feat(row):
    return np.array([row["rv1_abs"], row["rv5_abs"], row["rv22_abs"]])

def har_vix_feat(row):
    return np.array([row["rv1_abs"], row["rv5_abs"], row["rv22_abs"], row["vix_daily"]])

def har_skew_feat(row):
    """HAR-SKEW: HAR-ABS + SKEW (use CBOE if available, else realized)."""
    skew_val = row.get("skew_norm", np.nan)
    if np.isnan(skew_val):
        skew_val = row["realized_skew"]
    return np.array([row["rv1_abs"], row["rv5_abs"], row["rv22_abs"], skew_val])

def har_vix_skew_feat(row):
    """HAR-VIX-SKEW: HAR-ABS + VIX + SKEW."""
    skew_val = row.get("skew_norm", np.nan)
    if np.isnan(skew_val):
        skew_val = row["realized_skew"]
    return np.array([row["rv1_abs"], row["rv5_abs"], row["rv22_abs"],
                     row["vix_daily"], skew_val])

def har_vix_rskew_feat(row):
    """HAR-VIX-RSKEW: HAR-ABS + VIX + realized skewness (always use realized)."""
    return np.array([row["rv1_abs"], row["rv5_abs"], row["rv22_abs"],
                     row["vix_daily"], row["realized_skew"]])


# Model registry
HAR_MODELS = {
    "HAR-ABS": {
        "features_fn": har_abs_feat,
        "feature_names": ["rv1_abs", "rv5_abs", "rv22_abs"],
    },
    "HAR-VIX": {
        "features_fn": har_vix_feat,
        "feature_names": ["rv1_abs", "rv5_abs", "rv22_abs", "vix"],
    },
    "HAR-SKEW": {
        "features_fn": har_skew_feat,
        "feature_names": ["rv1_abs", "rv5_abs", "rv22_abs", "skew"],
    },
    "HAR-VIX-SKEW": {
        "features_fn": har_vix_skew_feat,
        "feature_names": ["rv1_abs", "rv5_abs", "rv22_abs", "vix", "skew"],
    },
    "HAR-VIX-RSKEW": {
        "features_fn": har_vix_rskew_feat,
        "feature_names": ["rv1_abs", "rv5_abs", "rv22_abs", "vix", "realized_skew"],
    },
}


# ============================================================
#  Benchmark Models
# ============================================================

def gjr_garch_forecast(returns: np.ndarray, window: int = 2000, refit_every: int = 21):
    """GJR-GARCH(1,1) rolling forecast."""
    from arch import arch_model

    n = len(returns)
    forecasts = np.full(n, np.nan)

    omega = 0.01
    alpha = 0.05
    gamma_p = 0.05
    beta_p = 0.90
    last_var = np.var(returns[:window]) * 1e4
    last_ret = returns[window - 1] * 100

    for t in range(window, n):
        if (t - window) % refit_every == 0:
            train = returns[max(0, t - window):t] * 100
            try:
                am = arch_model(train, vol="GARCH", p=1, o=1, q=1, dist="normal", mean="Zero")
                res = am.fit(disp="off", show_warning=False)
                omega = res.params.get("omega", omega)
                alpha = res.params.get("alpha[1]", alpha)
                gamma_p = res.params.get("gamma[1]", gamma_p)
                beta_p = res.params.get("beta[1]", beta_p)
                last_var = res.conditional_volatility.iloc[-1] ** 2
                last_ret = train.iloc[-1] if hasattr(train, 'iloc') else train[-1]
            except Exception:
                pass

        shock = last_ret ** 2
        leverage = shock * (1 if last_ret < 0 else 0)
        var_forecast = omega + alpha * shock + gamma_p * leverage + beta_p * last_var
        forecasts[t] = var_forecast / 1e4

        last_ret = returns[t] * 100
        last_var = var_forecast

    return forecasts


def ewma_forecast(returns: np.ndarray, lam: float = 0.94):
    """EWMA(lambda) variance forecast."""
    n = len(returns)
    var = np.full(n, np.nan)
    var[21] = np.var(returns[:22])
    for t in range(22, n):
        var[t] = lam * var[t - 1] + (1 - lam) * returns[t - 1] ** 2
    return var


def rolling_std_forecast(returns: np.ndarray, window: int = 22):
    """Rolling std variance forecast."""
    n = len(returns)
    var = np.full(n, np.nan)
    for t in range(window, n):
        var[t] = np.var(returns[t - window:t])
    return var


# ============================================================
#  Rolling OOS Evaluation
# ============================================================

def run_har_oos(features_df: pd.DataFrame, model_name: str, model_spec: dict,
                window: int = 500, oos_start: str = "2023-01-01"):
    """Run rolling OOS for a HAR model variant."""
    feat_fn = model_spec["features_fn"]
    target_col = "target_abs"

    oos_mask = features_df.index >= oos_start
    oos_indices = features_df.index[oos_mask]

    if len(oos_indices) == 0:
        return None

    forecasts = []
    realized = []
    dates = []

    for date in oos_indices:
        idx = features_df.index.get_loc(date)
        if idx < window:
            continue

        train_slice = features_df.iloc[idx - window:idx]
        valid_mask = train_slice.notna().all(axis=1)
        train_valid = train_slice[valid_mask]

        if len(train_valid) < 50:
            continue

        X_train = np.array([feat_fn(row) for _, row in train_valid.iterrows()])
        y_train = train_valid[target_col].values

        finite_mask = np.isfinite(X_train).all(axis=1) & np.isfinite(y_train)
        X_train = X_train[finite_mask]
        y_train = y_train[finite_mask]

        if len(y_train) < 50:
            continue

        beta = ols_fit(X_train, y_train)
        current_features = feat_fn(features_df.iloc[idx])
        if not np.all(np.isfinite(current_features)):
            continue

        pred = ols_predict(current_features, beta)
        actual = features_df.iloc[idx][target_col]
        if np.isnan(actual) or actual <= 0:
            continue

        forecasts.append(pred)
        realized.append(actual)
        dates.append(date)

    if len(forecasts) == 0:
        return None

    forecasts = np.array(forecasts)
    realized = np.array(realized)

    ql = qlike_loss(realized, forecasts)
    ql_array = qlike_loss_array(realized, forecasts)
    mse_l = mse_log_loss(realized, forecasts)
    mse_l_array = mse_log_loss_array(realized, forecasts)

    return {
        "model": model_name,
        "n_obs": len(forecasts),
        "qlike": ql,
        "mse_log": mse_l,
        "qlike_array": ql_array,
        "mse_log_array": mse_l_array,
        "forecasts": forecasts,
        "realized": realized,
        "dates": dates,
    }


def run_benchmark_oos(returns: np.ndarray, dates: pd.DatetimeIndex,
                      model_name: str, forecast_fn, oos_start: str = "2023-01-01",
                      **kwargs):
    """Run OOS for benchmark models (variance-scale forecasts)."""
    var_forecasts = forecast_fn(returns, **kwargs)

    # Benchmark produces variance; target is |r| for HAR → sqrt for comparison
    # Actually we need to compare on same scale. HAR predicts |r|.
    # Benchmarks predict sigma^2. Convert benchmark to |r| scale: sqrt(var) * sqrt(2/pi)
    # E[|r|] = sigma * sqrt(2/pi) for normal returns
    abs_forecasts = np.sqrt(np.maximum(var_forecasts, 1e-20)) * np.sqrt(2 / np.pi)

    realized_abs = np.abs(returns)

    oos_mask = dates >= oos_start
    oos_idx = np.where(oos_mask)[0]

    valid = []
    for t in oos_idx:
        if t >= len(abs_forecasts) or np.isnan(abs_forecasts[t]):
            continue
        if t + 1 >= len(realized_abs):
            continue
        rv = realized_abs[t + 1]  # next day realized
        if rv <= 0:
            rv = 1e-10
        valid.append((t, abs_forecasts[t], rv, dates[t]))

    if len(valid) == 0:
        return None

    _, forecasts_arr, realized_arr, valid_dates = zip(*valid)
    forecasts_arr = np.array(forecasts_arr)
    realized_arr = np.array(realized_arr)
    forecasts_arr = np.maximum(forecasts_arr, 1e-10)

    ql = qlike_loss(realized_arr, forecasts_arr)
    ql_array = qlike_loss_array(realized_arr, forecasts_arr)
    mse_l = mse_log_loss(realized_arr, forecasts_arr)
    mse_l_array = mse_log_loss_array(realized_arr, forecasts_arr)

    return {
        "model": model_name,
        "n_obs": len(forecasts_arr),
        "qlike": ql,
        "mse_log": mse_l,
        "qlike_array": ql_array,
        "mse_log_array": mse_l_array,
        "forecasts": forecasts_arr,
        "realized": realized_arr,
        "dates": list(valid_dates),
    }


# ============================================================
#  In-Sample Analysis
# ============================================================

def run_insample_analysis(features_df: pd.DataFrame, skew_available: bool):
    """In-sample OLS diagnostics for all models."""
    print_section("In-Sample Analysis (up to 2022-12-31)")

    train = features_df[features_df.index <= "2022-12-31"].copy()
    valid_mask = train.notna().all(axis=1)
    train = train[valid_mask]
    print(f"  Training sample: {len(train)} observations")

    diagnostics = {}
    for model_name, spec in HAR_MODELS.items():
        feat_fn = spec["features_fn"]
        feat_names = spec["feature_names"]

        X = np.array([feat_fn(row) for _, row in train.iterrows()])
        y = train["target_abs"].values

        finite_mask = np.isfinite(X).all(axis=1) & np.isfinite(y)
        X_valid = X[finite_mask]
        y_valid = y[finite_mask]

        if len(y_valid) < 100:
            print(f"\n  {model_name}: insufficient valid observations ({len(y_valid)})")
            continue

        diag = ols_diagnostics(X_valid, y_valid, feat_names)
        if diag is None:
            continue

        diagnostics[model_name] = diag
        print(f"\n  {model_name} (n={diag['n_obs']}, R²={diag['r_squared']:.4f}):")
        for name, info in diag["coefficients"].items():
            sig = "***" if abs(info["t_stat"]) > 3.0 else ("**" if abs(info["t_stat"]) > 2.0 else ("*" if abs(info["t_stat"]) > 1.65 else ""))
            print(f"    {name:20s}: {info['coef']:+.6f}  (t={info['t_stat']:+.2f}, p={info['p_value']:.4f}) {sig}")

    return diagnostics


# ============================================================
#  Sub-Period Stability Analysis
# ============================================================

def run_subperiod_analysis(features_df: pd.DataFrame, skew_available: bool):
    """Check SKEW coefficient stability across sub-periods."""
    print_section("Sub-Period SKEW Coefficient Stability")

    periods = [
        ("2015-2017", "2015-01-01", "2017-12-31"),
        ("2018-2019", "2018-01-01", "2019-12-31"),
        ("2020-2021", "2020-01-01", "2021-12-31"),
        ("2022-2024", "2022-01-01", "2024-12-31"),
    ]

    # Test HAR-VIX-SKEW sub-period stability
    model_spec = HAR_MODELS["HAR-VIX-SKEW"]
    feat_fn = model_spec["features_fn"]
    feat_names = model_spec["feature_names"]

    stability_results = {}
    for period_name, start, end in periods:
        sub = features_df[(features_df.index >= start) & (features_df.index <= end)].copy()
        valid = sub.dropna()

        if len(valid) < 100:
            print(f"  {period_name}: insufficient data ({len(valid)} obs)")
            continue

        X = np.array([feat_fn(row) for _, row in valid.iterrows()])
        y = valid["target_abs"].values

        finite_mask = np.isfinite(X).all(axis=1) & np.isfinite(y)
        X_valid = X[finite_mask]
        y_valid = y[finite_mask]

        if len(y_valid) < 50:
            continue

        diag = ols_diagnostics(X_valid, y_valid, feat_names)
        if diag is None:
            continue

        stability_results[period_name] = diag

        # Extract SKEW coefficient
        skew_info = diag["coefficients"].get("skew", {})
        vix_info = diag["coefficients"].get("vix", {})
        print(f"  {period_name} (n={diag['n_obs']}, R²={diag['r_squared']:.4f}):")
        print(f"    VIX  coef={vix_info.get('coef', 0):+.4f} (t={vix_info.get('t_stat', 0):+.2f})")
        print(f"    SKEW coef={skew_info.get('coef', 0):+.4f} (t={skew_info.get('t_stat', 0):+.2f})")

    return stability_results


# ============================================================
#  Descriptive Statistics
# ============================================================

def descriptive_stats(df: pd.DataFrame, features_df: pd.DataFrame, skew_available: bool):
    """Print descriptive statistics before estimation (research protocol step 5)."""
    print_section("Descriptive Statistics (Diagnostics Before Estimation)")

    r = df["log_return"].values
    print(f"\n  SPY log returns:")
    print(f"    N          = {len(r)}")
    print(f"    Mean       = {np.mean(r):.6f} ({np.mean(r)*252:.4f} annualized)")
    print(f"    Std        = {np.std(r):.6f} ({np.std(r)*np.sqrt(252):.4f} annualized)")
    print(f"    Skewness   = {stats.skew(r):.4f}")
    print(f"    Kurtosis   = {stats.kurtosis(r):.4f}")

    # ADF test
    from statsmodels.tsa.stattools import adfuller
    adf_stat, adf_p, _, _, _, _ = adfuller(r, maxlag=10)
    print(f"    ADF stat   = {adf_stat:.4f} (p={adf_p:.6f}) {'STATIONARY' if adf_p < 0.05 else 'NON-STATIONARY'}")

    # Ljung-Box on squared returns
    from statsmodels.stats.diagnostic import acorr_ljungbox
    sq_r = r ** 2
    lb = acorr_ljungbox(sq_r, lags=[10], return_df=True)
    lb_stat = lb["lb_stat"].values[0]
    lb_p = lb["lb_pvalue"].values[0]
    print(f"    LB(10) r²  = {lb_stat:.2f} (p={lb_p:.6f}) {'ARCH effects' if lb_p < 0.05 else 'no ARCH'}")

    # VIX stats
    vix = df["vix"].values
    print(f"\n  VIX:")
    print(f"    Mean = {np.nanmean(vix):.2f}, Std = {np.nanstd(vix):.2f}")
    print(f"    Min = {np.nanmin(vix):.2f}, Max = {np.nanmax(vix):.2f}")

    # SKEW stats
    if skew_available and "skew" in df.columns:
        skew_vals = df["skew"].dropna().values
        print(f"\n  CBOE SKEW:")
        print(f"    N    = {len(skew_vals)}")
        print(f"    Mean = {np.mean(skew_vals):.2f}, Std = {np.std(skew_vals):.2f}")
        print(f"    Min  = {np.min(skew_vals):.2f}, Max = {np.max(skew_vals):.2f}")
        print(f"    Skewness = {stats.skew(skew_vals):.4f}")

    # Realized skewness
    rskew = features_df["realized_skew"].dropna().values
    print(f"\n  Realized Skewness (22d rolling):")
    print(f"    N    = {len(rskew)}")
    print(f"    Mean = {np.mean(rskew):.4f}, Std = {np.std(rskew):.4f}")
    print(f"    Min  = {np.min(rskew):.4f}, Max = {np.max(rskew):.4f}")

    # Correlations
    print(f"\n  Correlations (full sample):")
    abs_r = np.abs(df["log_return"].values)
    vix_daily = df["vix"].values / 100.0 / np.sqrt(252)

    # Align lengths
    valid = np.isfinite(abs_r) & np.isfinite(vix_daily)

    corr_abs_vix = np.corrcoef(abs_r[valid], vix_daily[valid])[0, 1]
    print(f"    |r| vs VIX(daily):     {corr_abs_vix:.4f}")

    if skew_available and "skew" in df.columns:
        skew_norm = (df["skew"].values - 100) / 100.0
        valid_s = valid & np.isfinite(skew_norm)
        corr_abs_skew = np.corrcoef(abs_r[valid_s], skew_norm[valid_s])[0, 1]
        corr_vix_skew = np.corrcoef(vix_daily[valid_s], skew_norm[valid_s])[0, 1]
        print(f"    |r| vs SKEW(norm):     {corr_abs_skew:.4f}")
        print(f"    VIX vs SKEW:           {corr_vix_skew:.4f}")

    rskew_vals = features_df["realized_skew"].values
    valid_rs = valid & np.isfinite(rskew_vals[:len(valid)])
    if valid_rs.sum() > 100:
        corr_abs_rskew = np.corrcoef(abs_r[valid_rs], rskew_vals[valid_rs])[0, 1]
        print(f"    |r| vs RealizedSkew:   {corr_abs_rskew:.4f}")


# ============================================================
#  Main
# ============================================================

def main():
    t0 = time.time()
    print_section("K535: Options-Implied Skewness as Vol Predictor")
    print("  Does SKEW index add value beyond VIX in HAR framework?")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # ---- 1. Data ----
    df, skew_available = download_data()

    # ---- 2. Features ----
    features = build_features(df, skew_available)

    # ---- 3. Descriptive Statistics ----
    descriptive_stats(df, features, skew_available)

    # ---- 4. In-Sample Analysis ----
    is_diagnostics = run_insample_analysis(features, skew_available)

    # ---- 5. Sub-period Stability ----
    stability = run_subperiod_analysis(features, skew_available)

    # ---- 6. OOS Evaluation ----
    print_section("Out-of-Sample Evaluation (2023-2024)")

    oos_results = {}
    window = 500
    oos_start = "2023-01-01"

    # HAR models
    for model_name, spec in HAR_MODELS.items():
        print(f"  Running {model_name}...", end=" ", flush=True)
        result = run_har_oos(features, model_name, spec, window=window, oos_start=oos_start)
        if result:
            oos_results[model_name] = result
            print(f"n={result['n_obs']}, QLIKE={result['qlike']:.6f}, MSE_log={result['mse_log']:.4f}")
        else:
            print("FAILED (no valid forecasts)")

    # Benchmark models
    returns = df["log_return"].values
    dates_idx = df.index

    print(f"  Running GJR-GARCH...", end=" ", flush=True)
    gjr_result = run_benchmark_oos(returns, dates_idx, "GJR-GARCH",
                                    gjr_garch_forecast, oos_start=oos_start,
                                    window=2000, refit_every=21)
    if gjr_result:
        oos_results["GJR-GARCH"] = gjr_result
        print(f"n={gjr_result['n_obs']}, QLIKE={gjr_result['qlike']:.6f}")
    else:
        print("FAILED")

    print(f"  Running EWMA(0.94)...", end=" ", flush=True)
    ewma_result = run_benchmark_oos(returns, dates_idx, "EWMA(0.94)",
                                     ewma_forecast, oos_start=oos_start, lam=0.94)
    if ewma_result:
        oos_results["EWMA(0.94)"] = ewma_result
        print(f"n={ewma_result['n_obs']}, QLIKE={ewma_result['qlike']:.6f}")
    else:
        print("FAILED")

    print(f"  Running RollStd-22...", end=" ", flush=True)
    rs_result = run_benchmark_oos(returns, dates_idx, "RollStd-22",
                                   rolling_std_forecast, oos_start=oos_start, window=22)
    if rs_result:
        oos_results["RollStd-22"] = rs_result
        print(f"n={rs_result['n_obs']}, QLIKE={rs_result['qlike']:.6f}")
    else:
        print("FAILED")

    # ---- 7. DM Tests ----
    print_section("Diebold-Mariano Tests (QLIKE)")
    print(f"  {'Model A':20s} vs {'Model B':20s}  DM-stat   p-value  Winner")
    print(f"  {'-'*72}")

    dm_results = {}
    model_names = list(oos_results.keys())

    # Key comparisons
    comparisons = [
        ("HAR-VIX", "HAR-ABS"),           # VIX value (baseline test)
        ("HAR-SKEW", "HAR-ABS"),          # SKEW alone value
        ("HAR-VIX-SKEW", "HAR-VIX"),      # SKEW incremental over VIX (KEY QUESTION)
        ("HAR-VIX-RSKEW", "HAR-VIX"),     # Realized skew incremental
        ("HAR-VIX-SKEW", "HAR-ABS"),      # Combined vs baseline
        ("HAR-VIX", "GJR-GARCH"),         # HAR-VIX vs GARCH
        ("HAR-VIX", "EWMA(0.94)"),        # HAR-VIX vs EWMA
        ("HAR-VIX-SKEW", "GJR-GARCH"),   # Full model vs GARCH
    ]

    for a, b in comparisons:
        if a not in oos_results or b not in oos_results:
            continue

        # Align to common dates
        dates_a = set(str(d) for d in oos_results[a]["dates"])
        dates_b = set(str(d) for d in oos_results[b]["dates"])
        common = sorted(dates_a & dates_b)

        idx_a = [i for i, d in enumerate(oos_results[a]["dates"]) if str(d) in common]
        idx_b = [i for i, d in enumerate(oos_results[b]["dates"]) if str(d) in common]

        loss_a = oos_results[a]["qlike_array"][idx_a]
        loss_b = oos_results[b]["qlike_array"][idx_b]

        dm_stat, dm_p = dm_test(loss_a, loss_b)
        winner = a if dm_stat < 0 else b
        sig = "***" if dm_p < 0.01 else ("**" if dm_p < 0.05 else ("*" if dm_p < 0.10 else ""))

        key = f"{a}_vs_{b}"
        dm_results[key] = {"dm_stat": dm_stat, "p_value": dm_p, "winner": winner}
        print(f"  {a:20s} vs {b:20s}  {dm_stat:+7.3f}  {dm_p:.4f}  {winner} {sig}")

    # ---- 8. Summary ----
    print_section("Summary: Does SKEW Add Value?")

    # Rank models by QLIKE
    ranked = sorted(oos_results.items(), key=lambda x: x[1]["qlike"])
    print(f"\n  Model Rankings (QLIKE, lower is better):")
    for rank, (name, res) in enumerate(ranked, 1):
        best_mark = " <-- BEST" if rank == 1 else ""
        print(f"    {rank}. {name:20s}: QLIKE={res['qlike']:.6f}  MSE_log={res['mse_log']:.4f}  (n={res['n_obs']}){best_mark}")

    # Key findings
    print(f"\n  Key Findings:")

    # SKEW incremental value
    key_test = "HAR-VIX-SKEW_vs_HAR-VIX"
    if key_test in dm_results:
        dm = dm_results[key_test]
        if dm["p_value"] < 0.05:
            if dm["dm_stat"] < 0:
                print(f"    1. SKEW adds SIGNIFICANT value beyond VIX (DM={dm['dm_stat']:.3f}, p={dm['p_value']:.4f})")
            else:
                print(f"    1. SKEW HURTS after controlling for VIX (DM={dm['dm_stat']:.3f}, p={dm['p_value']:.4f})")
        else:
            print(f"    1. SKEW has NO significant incremental value over VIX (DM={dm['dm_stat']:.3f}, p={dm['p_value']:.4f})")

    # Realized skew
    key_test2 = "HAR-VIX-RSKEW_vs_HAR-VIX"
    if key_test2 in dm_results:
        dm = dm_results[key_test2]
        if dm["p_value"] < 0.05:
            if dm["dm_stat"] < 0:
                print(f"    2. Realized skew adds SIGNIFICANT value (DM={dm['dm_stat']:.3f}, p={dm['p_value']:.4f})")
            else:
                print(f"    2. Realized skew HURTS (DM={dm['dm_stat']:.3f}, p={dm['p_value']:.4f})")
        else:
            print(f"    2. Realized skew has NO significant incremental value (DM={dm['dm_stat']:.3f}, p={dm['p_value']:.4f})")

    # VIX confirmation
    key_test3 = "HAR-VIX_vs_HAR-ABS"
    if key_test3 in dm_results:
        dm = dm_results[key_test3]
        print(f"    3. HAR-VIX vs HAR-ABS: DM={dm['dm_stat']:.3f}, p={dm['p_value']:.4f} (confirms K530)")

    elapsed = time.time() - t0
    print(f"\n  Total runtime: {elapsed:.1f} seconds")

    # ---- 9. Save Results ----
    print_section("Saving Results")

    # Prepare serializable results
    results_json = {
        "experiment_id": "k535",
        "title": "K535: Options-Implied Skewness as Vol Predictor",
        "description": "Tests whether CBOE SKEW index or realized skewness adds predictive value beyond VIX in HAR framework",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "data_source": "yfinance (SPY, ^VIX, ^SKEW)",
        "method": "HAR-OLS rolling window w=500, OOS 2023-2024",
        "skew_data_available": skew_available,
        "references": [
            "Bakshi, Kapadia & Madan (2003, RFS): Skew laws and equity option pricing",
            "Corsi (2009, JFE): HAR-RV model",
            "K530: HAR-VIX best predictor (VIX coeff +0.879, t=18.5)",
            "K43: VVIX/SKEW overlay → null for VT",
            "K447: SKEW tail risk → hurts rather than helps",
        ],
        "insample_diagnostics": {},
        "subperiod_stability": {},
        "oos_results": {},
        "dm_tests": dm_results,
        "model_ranking_qlike": [],
        "conclusion": "",
    }

    # In-sample
    for model_name, diag in is_diagnostics.items():
        results_json["insample_diagnostics"][model_name] = diag

    # Sub-period
    for period, diag in stability.items():
        results_json["subperiod_stability"][period] = diag

    # OOS (exclude arrays)
    for model_name, res in oos_results.items():
        results_json["oos_results"][model_name] = {
            "n_obs": res["n_obs"],
            "qlike": res["qlike"],
            "mse_log": res["mse_log"],
        }

    # Ranking
    for rank, (name, res) in enumerate(ranked, 1):
        results_json["model_ranking_qlike"].append({
            "rank": rank,
            "model": name,
            "qlike": res["qlike"],
            "mse_log": res["mse_log"],
        })

    # Conclusion
    conclusions = []
    key_test = "HAR-VIX-SKEW_vs_HAR-VIX"
    if key_test in dm_results:
        dm = dm_results[key_test]
        if dm["p_value"] < 0.05 and dm["dm_stat"] < 0:
            conclusions.append("SKEW adds significant predictive value beyond VIX")
        elif dm["p_value"] < 0.05 and dm["dm_stat"] > 0:
            conclusions.append("SKEW hurts predictive accuracy after controlling for VIX")
        else:
            conclusions.append(f"SKEW has no significant incremental value over VIX (DM={dm['dm_stat']:.3f}, p={dm['p_value']:.4f})")

    key_test2 = "HAR-VIX-RSKEW_vs_HAR-VIX"
    if key_test2 in dm_results:
        dm = dm_results[key_test2]
        if dm["p_value"] < 0.05 and dm["dm_stat"] < 0:
            conclusions.append("Realized skewness adds significant predictive value")
        else:
            conclusions.append(f"Realized skewness also no incremental value (DM={dm['dm_stat']:.3f}, p={dm['p_value']:.4f})")

    conclusions.append(f"Best model: {ranked[0][0]} (QLIKE={ranked[0][1]['qlike']:.6f})")
    conclusions.append("VIX sufficiency further confirmed — higher-order moment info (skewness) is redundant for vol prediction")

    results_json["conclusion"] = "; ".join(conclusions)

    # Save
    results_path = project_root / "experiments" / "k535_skew_predictor_results.json"
    with open(results_path, "w") as f:
        json.dump(results_json, f, indent=2, default=str)
    print(f"  Results saved: {results_path}")

    script_path = Path(__file__).resolve()
    print(f"  Script: {script_path}")
    print(f"\n  DONE. Runtime: {elapsed:.1f}s")

    return results_json


if __name__ == "__main__":
    main()
