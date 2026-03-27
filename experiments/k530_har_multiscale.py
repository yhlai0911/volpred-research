"""K530: HAR Multi-Scale Volatility Forecast for SPY + 0050.TW.

Extends K529's HAR-Rough finding (DM=-7.04 vs GJR, tied with EWMA) with
a proper multi-variant HAR implementation using daily proxies.

Literature basis:
  - Corsi (2009, JFE): Original HAR-RV model — multi-scale RV (1d, 5d, 22d)
  - Patton & Sheppard (2015): Semivariance decomposition (good/bad vol)
  - K529: HAR-Rough beat GJR-GARCH (DM=-7.04) but tied with EWMA

Daily proxies (no intraday data yet):
  - RV_1 = |r_t| (absolute return)
  - RV_5 = mean(|r_{t-i}|, i=0..4)
  - RV_22 = mean(|r_{t-i}|, i=0..21)

Models tested (6 HAR + 3 benchmarks):
  1. HAR-ABS:       c + β1·RV1 + β5·RV5 + β22·RV22 (abs return proxy)
  2. HAR-SQ:        Same with squared returns
  3. HAR-RS:        Semivariance (positive + negative) + RV22
  4. HAR-VIX:       HAR-ABS + lagged VIX regressor
  5. HAR-LEVERAGE:  HAR-ABS + leverage term (negative return × RV)
  6. HAR-JUMP:      HAR-ABS + jump indicator (|r_t| > 3σ)
  7. GJR-GARCH(1,1): Standard benchmark
  8. EWMA(λ=0.94):  Strong baseline per K529
  9. Rolling-Std-22: Simple 22-day rolling std

Method: OLS rolling window w=500, OOS 2023-2024
Evaluation: QLIKE + MSE(log) + DM test pairwise
Cross-asset: SPY + 0050.TW

Usage:
    uv run python experiments/k530_har_multiscale.py
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
#  HAR Feature Construction
# ============================================================

def build_har_features(df: pd.DataFrame, use_vix: bool = False):
    """Build HAR features from daily data.

    Returns DataFrame with columns:
      - rv1_abs, rv5_abs, rv22_abs   (absolute return proxies)
      - rv1_sq, rv5_sq, rv22_sq      (squared return proxies)
      - rs_pos, rs_neg               (semivariance components)
      - leverage                     (negative return × RV interaction)
      - jump                         (|r| > 3σ indicator)
      - vix                          (if available)
      - target_abs, target_sq        (next-day realized vol)
    """
    r = df["log_return"].values.copy()
    n = len(r)

    # Absolute return proxies
    abs_r = np.abs(r)
    sq_r = r ** 2

    # Rolling averages
    rv1_abs = abs_r.copy()
    rv5_abs = pd.Series(abs_r).rolling(5).mean().values
    rv22_abs = pd.Series(abs_r).rolling(22).mean().values

    rv1_sq = sq_r.copy()
    rv5_sq = pd.Series(sq_r).rolling(5).mean().values
    rv22_sq = pd.Series(sq_r).rolling(22).mean().values

    # Semivariance: positive and negative components
    rs_pos = np.where(r > 0, sq_r, 0.0)
    rs_neg = np.where(r < 0, sq_r, 0.0)
    # Rolling 5-day average for semivariance
    rs_pos_5 = pd.Series(rs_pos).rolling(5).mean().values
    rs_neg_5 = pd.Series(rs_neg).rolling(5).mean().values

    # Leverage term: I(r<0) * abs(r) * rv5_abs
    leverage = np.where(r < 0, abs_r * rv5_abs, 0.0)

    # Jump indicator: |r| > 3 * rolling std
    rolling_std = pd.Series(r).rolling(252).std().values
    jump = np.where(abs_r > 3 * rolling_std, 1.0, 0.0)

    # Target: next-day realized volatility
    target_abs = np.roll(abs_r, -1)
    target_sq = np.roll(sq_r, -1)
    target_abs[-1] = np.nan
    target_sq[-1] = np.nan

    features = pd.DataFrame({
        "rv1_abs": rv1_abs,
        "rv5_abs": rv5_abs,
        "rv22_abs": rv22_abs,
        "rv1_sq": rv1_sq,
        "rv5_sq": rv5_sq,
        "rv22_sq": rv22_sq,
        "rs_pos_5": rs_pos_5,
        "rs_neg_5": rs_neg_5,
        "rv22_sq_for_rs": rv22_sq,  # used in HAR-RS model
        "leverage": leverage,
        "jump": jump,
        "target_abs": target_abs,
        "target_sq": target_sq,
    }, index=df.index)

    if use_vix and "vix" in df.columns:
        features["vix"] = df["vix"].values / 100.0 / np.sqrt(252)  # annualized → daily scale

    return features


# ============================================================
#  HAR Models (OLS)
# ============================================================

def ols_fit(X: np.ndarray, y: np.ndarray):
    """OLS with intercept. Returns coefficients [intercept, β1, β2, ...]."""
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
    return max(pred, 1e-10)  # floor to avoid negative variance


def har_abs_features(feat: pd.Series):
    """HAR-ABS: rv1_abs, rv5_abs, rv22_abs."""
    return np.array([feat["rv1_abs"], feat["rv5_abs"], feat["rv22_abs"]])


def har_sq_features(feat: pd.Series):
    """HAR-SQ: rv1_sq, rv5_sq, rv22_sq."""
    return np.array([feat["rv1_sq"], feat["rv5_sq"], feat["rv22_sq"]])


def har_rs_features(feat: pd.Series):
    """HAR-RS: rs_pos_5, rs_neg_5, rv22_sq."""
    return np.array([feat["rs_pos_5"], feat["rs_neg_5"], feat["rv22_sq_for_rs"]])


def har_vix_features(feat: pd.Series):
    """HAR-VIX: rv1_abs, rv5_abs, rv22_abs, vix."""
    base = [feat["rv1_abs"], feat["rv5_abs"], feat["rv22_abs"]]
    if "vix" in feat.index:
        base.append(feat["vix"])
    return np.array(base)


def har_leverage_features(feat: pd.Series):
    """HAR-LEVERAGE: rv1_abs, rv5_abs, rv22_abs, leverage."""
    return np.array([feat["rv1_abs"], feat["rv5_abs"], feat["rv22_abs"], feat["leverage"]])


def har_jump_features(feat: pd.Series):
    """HAR-JUMP: rv1_abs, rv5_abs, rv22_abs, jump."""
    return np.array([feat["rv1_abs"], feat["rv5_abs"], feat["rv22_abs"], feat["jump"]])


# Model registry
HAR_MODELS = {
    "HAR-ABS": {"features_fn": har_abs_features, "target": "target_abs"},
    "HAR-SQ":  {"features_fn": har_sq_features,  "target": "target_sq"},
    "HAR-RS":  {"features_fn": har_rs_features,  "target": "target_sq"},
    "HAR-VIX": {"features_fn": har_vix_features, "target": "target_abs"},
    "HAR-LEVERAGE": {"features_fn": har_leverage_features, "target": "target_abs"},
    "HAR-JUMP": {"features_fn": har_jump_features, "target": "target_abs"},
}


# ============================================================
#  Benchmark Models
# ============================================================

def gjr_garch_forecast(returns: np.ndarray, window: int = 2000, refit_every: int = 21):
    """GJR-GARCH(1,1) rolling forecast."""
    from arch import arch_model

    n = len(returns)
    forecasts = np.full(n, np.nan)

    # Initialize params
    omega = 0.01
    alpha = 0.05
    gamma_p = 0.05
    beta_p = 0.90
    last_var = np.var(returns[:window]) * 1e4  # percent scale
    last_ret = returns[window - 1] * 100

    for t in range(window, n):
        if (t - window) % refit_every == 0:
            train = returns[max(0, t - window):t] * 100  # percent scale
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
                pass  # use previous params

        # One-step forecast
        shock = last_ret ** 2
        leverage = shock * (1 if last_ret < 0 else 0)
        var_forecast = omega + alpha * shock + gamma_p * leverage + beta_p * last_var
        forecasts[t] = var_forecast / 1e4  # back to decimal scale

        # Update for next step
        last_ret = returns[t] * 100
        last_var = var_forecast

    return forecasts


def ewma_forecast(returns: np.ndarray, lam: float = 0.94):
    """EWMA(λ) variance forecast."""
    n = len(returns)
    var = np.full(n, np.nan)
    # Initialize with first 22-day variance
    var[21] = np.var(returns[:22])
    for t in range(22, n):
        var[t] = lam * var[t - 1] + (1 - lam) * returns[t - 1] ** 2
    return var


def rolling_std_forecast(returns: np.ndarray, window: int = 22):
    """Rolling standard deviation forecast (variance)."""
    n = len(returns)
    var = np.full(n, np.nan)
    for t in range(window, n):
        var[t] = np.var(returns[t - window:t])
    return var


# ============================================================
#  Main Rolling OOS Evaluation
# ============================================================

def run_har_oos(features_df: pd.DataFrame, model_name: str, model_spec: dict,
                window: int = 500, oos_start: str = "2023-01-01"):
    """Run rolling OOS for a HAR model variant."""
    feat_fn = model_spec["features_fn"]
    target_col = model_spec["target"]

    # Find OOS start index
    oos_mask = features_df.index >= oos_start
    oos_indices = features_df.index[oos_mask]

    if len(oos_indices) == 0:
        return None

    forecasts = []
    realized = []
    dates = []

    for i, date in enumerate(oos_indices):
        idx = features_df.index.get_loc(date)
        if idx < window:
            continue

        # Training window
        train_slice = features_df.iloc[idx - window:idx]

        # Remove NaN rows
        valid_mask = train_slice.notna().all(axis=1)
        train_valid = train_slice[valid_mask]

        if len(train_valid) < 50:  # minimum obs
            continue

        # Build X, y for training
        X_train = np.array([feat_fn(row) for _, row in train_valid.iterrows()])
        y_train = train_valid[target_col].values

        # Remove any remaining NaN
        finite_mask = np.isfinite(X_train).all(axis=1) & np.isfinite(y_train)
        X_train = X_train[finite_mask]
        y_train = y_train[finite_mask]

        if len(y_train) < 50:
            continue

        # Fit OLS
        beta = ols_fit(X_train, y_train)

        # Predict (using current-day features to forecast next-day)
        current_features = feat_fn(features_df.iloc[idx])
        if not np.all(np.isfinite(current_features)):
            continue

        pred = ols_predict(current_features, beta)

        # Actual realized value (next day)
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

    # Compute losses
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
    """Run OOS for benchmark models."""
    var_forecasts = forecast_fn(returns, **kwargs)

    # Realized variance (next-day r²)
    realized_var = returns ** 2

    # Align and filter OOS
    oos_mask = dates >= oos_start
    oos_idx = np.where(oos_mask)[0]

    # Filter valid (non-NaN) forecasts
    valid = []
    for t in oos_idx:
        if t >= len(var_forecasts) or np.isnan(var_forecasts[t]):
            continue
        if t + 1 >= len(realized_var):
            continue
        rv = realized_var[t + 1]  # next day realized
        if rv <= 0:
            rv = 1e-10
        valid.append((t, var_forecasts[t], rv, dates[t]))

    if len(valid) == 0:
        return None

    _, forecasts, realized, valid_dates = zip(*valid)
    forecasts = np.array(forecasts)
    realized = np.array(realized)

    # Floor
    forecasts = np.maximum(forecasts, 1e-10)

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
        "dates": list(valid_dates),
    }


# ============================================================
#  In-Sample Diagnostics (OLS R², coefficient analysis)
# ============================================================

def insample_diagnostics(features_df: pd.DataFrame, model_name: str, model_spec: dict,
                         sample_end: str = "2022-12-31"):
    """In-sample OLS diagnostics for a HAR model."""
    feat_fn = model_spec["features_fn"]
    target_col = model_spec["target"]

    train = features_df[features_df.index <= sample_end].copy()
    valid_mask = train.notna().all(axis=1)
    train = train[valid_mask]

    if len(train) < 100:
        return None

    X = np.array([feat_fn(row) for _, row in train.iterrows()])
    y = train[target_col].values

    finite_mask = np.isfinite(X).all(axis=1) & np.isfinite(y)
    X = X[finite_mask]
    y = y[finite_mask]

    if len(y) < 100:
        return None

    # OLS with intercept
    n = len(y)
    X_aug = np.column_stack([np.ones(n), X])
    beta = np.linalg.lstsq(X_aug, y, rcond=None)[0]

    # R²
    y_pred = X_aug @ beta
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_squared = 1 - ss_res / ss_tot

    # Residual standard error
    k = X_aug.shape[1]
    s2 = ss_res / (n - k)
    se = np.sqrt(s2)

    # Standard errors of coefficients
    try:
        cov_beta = s2 * np.linalg.inv(X_aug.T @ X_aug)
        se_beta = np.sqrt(np.diag(cov_beta))
        t_stats = beta / se_beta
        p_values = 2 * (1 - stats.t.cdf(np.abs(t_stats), df=n - k))
    except np.linalg.LinAlgError:
        se_beta = np.full(k, np.nan)
        t_stats = np.full(k, np.nan)
        p_values = np.full(k, np.nan)

    # Feature names
    if model_name == "HAR-ABS":
        names = ["const", "rv1_abs", "rv5_abs", "rv22_abs"]
    elif model_name == "HAR-SQ":
        names = ["const", "rv1_sq", "rv5_sq", "rv22_sq"]
    elif model_name == "HAR-RS":
        names = ["const", "rs_pos_5", "rs_neg_5", "rv22_sq"]
    elif model_name == "HAR-VIX":
        names = ["const", "rv1_abs", "rv5_abs", "rv22_abs", "vix"]
    elif model_name == "HAR-LEVERAGE":
        names = ["const", "rv1_abs", "rv5_abs", "rv22_abs", "leverage"]
    elif model_name == "HAR-JUMP":
        names = ["const", "rv1_abs", "rv5_abs", "rv22_abs", "jump"]
    else:
        names = [f"x{i}" for i in range(k)]

    coefficients = {}
    for i, name in enumerate(names):
        coefficients[name] = {
            "coef": float(beta[i]),
            "se": float(se_beta[i]),
            "t": float(t_stats[i]),
            "p": float(p_values[i]),
        }

    return {
        "model": model_name,
        "n_obs": n,
        "r_squared": float(r_squared),
        "adj_r_squared": float(1 - (1 - r_squared) * (n - 1) / (n - k)),
        "residual_se": float(se),
        "coefficients": coefficients,
    }


# ============================================================
#  Main Experiment Runner
# ============================================================

def run_asset(asset: str, oos_start: str = "2023-01-01", oos_end: str = "2024-12-31",
              har_window: int = 500, garch_window: int = 2000):
    """Run full HAR multi-scale experiment for one asset."""
    print_section(f"Asset: {asset}")

    # Load data via yfinance
    import yfinance as yf
    raw = yf.download(asset, start="2005-01-01", end="2025-01-01", progress=False)
    if raw is None or len(raw) < 1000:
        print(f"  Insufficient data for {asset}")
        return None

    # Flatten MultiIndex columns if present
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    df = pd.DataFrame(index=raw.index)
    df["close"] = raw["Close"]
    df["high"] = raw["High"]
    df["low"] = raw["Low"]
    df["log_return"] = np.log(df["close"] / df["close"].shift(1))
    df = df.dropna(subset=["log_return"])

    print(f"  Data: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Total obs: {len(df)}")

    # Check for VIX column
    has_vix = "vix" in df.columns
    if not has_vix and asset == "SPY":
        # Try to load VIX separately
        try:
            vix_data = yf.download("^VIX", start=df.index[0], end=df.index[-1] + pd.Timedelta(days=5), progress=False)
            if len(vix_data) > 0:
                if isinstance(vix_data.columns, pd.MultiIndex):
                    vix_data.columns = vix_data.columns.get_level_values(0)
                df["vix"] = vix_data["Close"].reindex(df.index, method="ffill")
                has_vix = True
                print(f"  VIX loaded: {vix_data.index[0].strftime('%Y-%m-%d')} to {vix_data.index[-1].strftime('%Y-%m-%d')}")
        except Exception as e:
            print(f"  VIX load failed: {e}")

    # Build HAR features
    use_vix = has_vix and asset == "SPY"
    features_df = build_har_features(df, use_vix=use_vix)

    # Filter to OOS end
    if oos_end:
        features_df = features_df[features_df.index <= oos_end]
        df = df[df.index <= oos_end]

    # ── Descriptive Statistics ──
    print_section("Descriptive Statistics", "-")
    r = df["log_return"].values
    print(f"  Mean daily return:  {np.mean(r):.6f}")
    print(f"  Std daily return:   {np.std(r):.6f}")
    print(f"  Skewness:           {stats.skew(r):.4f}")
    print(f"  Kurtosis (excess):  {stats.kurtosis(r):.4f}")
    print(f"  Min / Max:          {np.min(r):.4f} / {np.max(r):.4f}")

    abs_r = np.abs(r)
    print(f"  Mean |r|:           {np.mean(abs_r):.6f}")
    print(f"  Mean r²:            {np.mean(r**2):.8f}")

    # Autocorrelation of |r| (proxy for vol clustering)
    from statsmodels.stats.diagnostic import acorr_ljungbox
    lb_result = acorr_ljungbox(abs_r[1:], lags=[10], return_df=True)
    lb_stat = lb_result["lb_stat"].iloc[0]
    lb_pval = lb_result["lb_pvalue"].iloc[0]
    print(f"  Ljung-Box |r| lag10: stat={lb_stat:.2f}, p={lb_pval:.6f}")

    desc_stats = {
        "mean_return": float(np.mean(r)),
        "std_return": float(np.std(r)),
        "skewness": float(stats.skew(r)),
        "kurtosis": float(stats.kurtosis(r)),
        "mean_abs_r": float(np.mean(abs_r)),
        "mean_r_sq": float(np.mean(r**2)),
        "ljung_box_abs_r_lag10": {"stat": float(lb_stat), "p": float(lb_pval)},
    }

    # ── In-Sample Diagnostics ──
    print_section("In-Sample Diagnostics (pre-2023)", "-")
    insample_results = {}

    models_to_run = dict(HAR_MODELS)
    if not use_vix:
        models_to_run.pop("HAR-VIX", None)

    for model_name, model_spec in models_to_run.items():
        diag = insample_diagnostics(features_df, model_name, model_spec, sample_end="2022-12-31")
        if diag:
            insample_results[model_name] = diag
            print(f"\n  {model_name}:")
            print(f"    R² = {diag['r_squared']:.4f}, Adj-R² = {diag['adj_r_squared']:.4f}")
            print(f"    N = {diag['n_obs']}")
            for cname, cvals in diag["coefficients"].items():
                sig = "***" if cvals["p"] < 0.01 else "**" if cvals["p"] < 0.05 else "*" if cvals["p"] < 0.10 else ""
                print(f"    {cname:12s}: β={cvals['coef']:+.6f}  t={cvals['t']:+.3f}  p={cvals['p']:.4f} {sig}")

    # ── OOS HAR Models ──
    print_section("Out-of-Sample Evaluation (OOS)", "-")
    oos_results = {}

    for model_name, model_spec in models_to_run.items():
        t0 = time.time()
        result = run_har_oos(features_df, model_name, model_spec,
                             window=har_window, oos_start=oos_start)
        elapsed = time.time() - t0
        if result:
            oos_results[model_name] = result
            print(f"  {model_name:15s}: QLIKE={result['qlike']:.6f}  MSE(log)={result['mse_log']:.4f}"
                  f"  N={result['n_obs']}  ({elapsed:.1f}s)")
        else:
            print(f"  {model_name:15s}: FAILED")

    # ── OOS Benchmark Models ──
    print_section("Benchmark Models (OOS)", "-")
    returns = df["log_return"].values
    dates_idx = df.index

    # GJR-GARCH
    t0 = time.time()
    gjr_result = run_benchmark_oos(returns, dates_idx, "GJR-GARCH",
                                   gjr_garch_forecast, oos_start=oos_start,
                                   window=garch_window, refit_every=21)
    elapsed = time.time() - t0
    if gjr_result:
        oos_results["GJR-GARCH"] = gjr_result
        print(f"  GJR-GARCH:       QLIKE={gjr_result['qlike']:.6f}  MSE(log)={gjr_result['mse_log']:.4f}"
              f"  N={gjr_result['n_obs']}  ({elapsed:.1f}s)")

    # EWMA
    t0 = time.time()
    ewma_result = run_benchmark_oos(returns, dates_idx, "EWMA(0.94)",
                                    ewma_forecast, oos_start=oos_start,
                                    lam=0.94)
    elapsed = time.time() - t0
    if ewma_result:
        oos_results["EWMA(0.94)"] = ewma_result
        print(f"  EWMA(0.94):      QLIKE={ewma_result['qlike']:.6f}  MSE(log)={ewma_result['mse_log']:.4f}"
              f"  N={ewma_result['n_obs']}  ({elapsed:.1f}s)")

    # Rolling Std
    t0 = time.time()
    rstd_result = run_benchmark_oos(returns, dates_idx, "RollStd-22",
                                    rolling_std_forecast, oos_start=oos_start,
                                    window=22)
    elapsed = time.time() - t0
    if rstd_result:
        oos_results["RollStd-22"] = rstd_result
        print(f"  RollStd-22:      QLIKE={rstd_result['qlike']:.6f}  MSE(log)={rstd_result['mse_log']:.4f}"
              f"  N={rstd_result['n_obs']}  ({elapsed:.1f}s)")

    # ── DM Tests (pairwise against GJR-GARCH) ──
    print_section("DM Tests vs GJR-GARCH (QLIKE)", "-")
    dm_results = {}

    if "GJR-GARCH" in oos_results:
        ref_result = oos_results["GJR-GARCH"]

        for model_name, result in oos_results.items():
            if model_name == "GJR-GARCH":
                continue

            # Align by common dates
            ref_dates = set(str(d) for d in ref_result["dates"])
            model_dates = set(str(d) for d in result["dates"])
            common_dates = sorted(ref_dates & model_dates)

            if len(common_dates) < 50:
                print(f"  {model_name} vs GJR-GARCH: insufficient overlap ({len(common_dates)})")
                continue

            # Get aligned losses
            ref_date_map = {str(d): i for i, d in enumerate(ref_result["dates"])}
            model_date_map = {str(d): i for i, d in enumerate(result["dates"])}

            ref_losses = np.array([ref_result["qlike_array"][ref_date_map[d]] for d in common_dates])
            model_losses = np.array([result["qlike_array"][model_date_map[d]] for d in common_dates])

            dm_stat, dm_pval = dm_test(model_losses, ref_losses)
            dm_results[model_name] = {
                "dm_stat": dm_stat,
                "p_value": dm_pval,
                "n_common": len(common_dates),
                "significant_5pct": dm_pval < 0.05,
                "significant_harvey": abs(dm_stat) > 3.0,
                "direction": "model better" if dm_stat < 0 else "GJR better",
            }

            sig_str = "***" if abs(dm_stat) > 3.0 else "**" if dm_pval < 0.05 else "*" if dm_pval < 0.10 else ""
            dir_str = "←" if dm_stat < 0 else "→"
            print(f"  {model_name:15s} vs GJR: DM={dm_stat:+.3f}  p={dm_pval:.4f}  "
                  f"N={len(common_dates)}  {dir_str} {sig_str}")

    # ── DM Tests (pairwise against EWMA) ──
    print_section("DM Tests vs EWMA(0.94) (QLIKE)", "-")
    dm_vs_ewma = {}

    if "EWMA(0.94)" in oos_results:
        ref_result = oos_results["EWMA(0.94)"]

        for model_name, result in oos_results.items():
            if model_name == "EWMA(0.94)":
                continue

            ref_dates = set(str(d) for d in ref_result["dates"])
            model_dates = set(str(d) for d in result["dates"])
            common_dates = sorted(ref_dates & model_dates)

            if len(common_dates) < 50:
                continue

            ref_date_map = {str(d): i for i, d in enumerate(ref_result["dates"])}
            model_date_map = {str(d): i for i, d in enumerate(result["dates"])}

            ref_losses = np.array([ref_result["qlike_array"][ref_date_map[d]] for d in common_dates])
            model_losses = np.array([result["qlike_array"][model_date_map[d]] for d in common_dates])

            dm_stat, dm_pval = dm_test(model_losses, ref_losses)
            dm_vs_ewma[model_name] = {
                "dm_stat": dm_stat,
                "p_value": dm_pval,
                "n_common": len(common_dates),
                "significant_5pct": dm_pval < 0.05,
                "significant_harvey": abs(dm_stat) > 3.0,
                "direction": "model better" if dm_stat < 0 else "EWMA better",
            }

            sig_str = "***" if abs(dm_stat) > 3.0 else "**" if dm_pval < 0.05 else "*" if dm_pval < 0.10 else ""
            dir_str = "←" if dm_stat < 0 else "→"
            print(f"  {model_name:15s} vs EWMA: DM={dm_stat:+.3f}  p={dm_pval:.4f}  "
                  f"N={len(common_dates)}  {dir_str} {sig_str}")

    # ── Best HAR pairwise DM ──
    print_section("Pairwise DM: Best HAR vs All Others (QLIKE)", "-")
    har_models_in_oos = [k for k in oos_results if k.startswith("HAR")]
    dm_pairwise_har = {}

    if len(har_models_in_oos) >= 2:
        # Find best HAR by QLIKE
        best_har = min(har_models_in_oos, key=lambda k: oos_results[k]["qlike"])
        print(f"  Best HAR model: {best_har} (QLIKE={oos_results[best_har]['qlike']:.6f})")

        ref_result = oos_results[best_har]
        for model_name in har_models_in_oos:
            if model_name == best_har:
                continue

            result = oos_results[model_name]
            ref_dates = set(str(d) for d in ref_result["dates"])
            model_dates = set(str(d) for d in result["dates"])
            common_dates = sorted(ref_dates & model_dates)

            if len(common_dates) < 50:
                continue

            ref_date_map = {str(d): i for i, d in enumerate(ref_result["dates"])}
            model_date_map = {str(d): i for i, d in enumerate(result["dates"])}

            ref_losses = np.array([ref_result["qlike_array"][ref_date_map[d]] for d in common_dates])
            model_losses = np.array([result["qlike_array"][model_date_map[d]] for d in common_dates])

            dm_stat, dm_pval = dm_test(ref_losses, model_losses)
            dm_pairwise_har[f"{best_har} vs {model_name}"] = {
                "dm_stat": dm_stat,
                "p_value": dm_pval,
                "n_common": len(common_dates),
            }

            sig_str = "***" if abs(dm_stat) > 3.0 else "**" if dm_pval < 0.05 else "*" if dm_pval < 0.10 else ""
            dir_str = "←" if dm_stat < 0 else "→"
            print(f"  {best_har} vs {model_name}: DM={dm_stat:+.3f}  p={dm_pval:.4f}  {dir_str} {sig_str}")

    # ── Summary ──
    print_section(f"Summary for {asset}", "=")
    print(f"  {'Model':15s}  {'QLIKE':>10s}  {'MSE(log)':>10s}  {'N':>5s}  {'Rank':>5s}")
    print(f"  {'-'*50}")

    sorted_models = sorted(oos_results.keys(), key=lambda k: oos_results[k]["qlike"])
    for rank, model_name in enumerate(sorted_models, 1):
        r = oos_results[model_name]
        best_marker = " ★" if rank == 1 else ""
        print(f"  {model_name:15s}  {r['qlike']:10.6f}  {r['mse_log']:10.4f}  {r['n_obs']:5d}  {rank:5d}{best_marker}")

    # Compile results
    oos_summary = {}
    for model_name, result in oos_results.items():
        oos_summary[model_name] = {
            "qlike": result["qlike"],
            "mse_log": result["mse_log"],
            "n_obs": result["n_obs"],
            "rank_qlike": sorted_models.index(model_name) + 1,
        }

    return {
        "asset": asset,
        "data_period": f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
        "n_total": len(df),
        "has_vix": has_vix,
        "oos_period": f"{oos_start} to {oos_end}",
        "har_window": har_window,
        "garch_window": garch_window,
        "descriptive_stats": desc_stats,
        "insample_diagnostics": insample_results,
        "oos_results": oos_summary,
        "dm_vs_gjr": dm_results,
        "dm_vs_ewma": dm_vs_ewma,
        "dm_pairwise_har": dm_pairwise_har,
        "ranking": sorted_models,
    }


# ============================================================
#  Main
# ============================================================

def main():
    print_section("K530: HAR Multi-Scale Volatility Forecast", "=")
    print("  Literature: Corsi (2009, JFE), Patton & Sheppard (2015)")
    print("  Extends K529 (HAR-Rough beat GJR, tied EWMA)")
    print()

    t_start = time.time()
    all_results = {}

    # Run SPY
    spy_results = run_asset("SPY", oos_start="2023-01-01", oos_end="2024-12-31")
    if spy_results:
        all_results["SPY"] = spy_results

    # Run 0050.TW
    tw_results = run_asset("0050.TW", oos_start="2023-01-01", oos_end="2024-12-31")
    if tw_results:
        all_results["0050.TW"] = tw_results

    elapsed = time.time() - t_start

    # ── Cross-asset Comparison ──
    if len(all_results) >= 2:
        print_section("Cross-Asset Comparison", "=")
        for asset, results in all_results.items():
            print(f"\n  {asset}:")
            print(f"    {'Model':15s}  {'QLIKE':>10s}  {'Rank':>5s}")
            for rank, model in enumerate(results["ranking"], 1):
                ql = results["oos_results"][model]["qlike"]
                print(f"    {model:15s}  {ql:10.6f}  {rank:5d}")

    # ── Save results ──
    output = {
        "experiment_id": "K530",
        "title": "HAR Multi-Scale Volatility Forecast (SPY + 0050.TW)",
        "timestamp": datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "data_source": "yfinance (daily)",
        "references": [
            "Corsi (2009, JFE): Original HAR-RV model",
            "Patton & Sheppard (2015): Semivariance decomposition",
            "K529: HAR-Rough beat GJR-GARCH (DM=-7.04)",
        ],
        "method": {
            "har_variants": ["HAR-ABS", "HAR-SQ", "HAR-RS", "HAR-VIX", "HAR-LEVERAGE", "HAR-JUMP"],
            "benchmarks": ["GJR-GARCH(1,1)", "EWMA(0.94)", "RollStd-22"],
            "har_window": 500,
            "garch_window": 2000,
            "oos_period": "2023-01-01 to 2024-12-31",
            "evaluation": "QLIKE + MSE(log) + DM test",
            "daily_proxies": {
                "RV1": "|r_t| or r_t²",
                "RV5": "mean(|r_{t-i}|, i=0..4) or mean(r²_{t-i})",
                "RV22": "mean(|r_{t-i}|, i=0..21) or mean(r²_{t-i})",
            },
        },
        "results": {},
    }

    for asset, results in all_results.items():
        # Clean up non-serializable items from insample_diagnostics
        clean_insample = {}
        for model_name, diag in results["insample_diagnostics"].items():
            clean_insample[model_name] = {
                "r_squared": diag["r_squared"],
                "adj_r_squared": diag["adj_r_squared"],
                "n_obs": diag["n_obs"],
                "residual_se": diag["residual_se"],
                "coefficients": diag["coefficients"],
            }

        output["results"][asset] = {
            "data_period": results["data_period"],
            "n_total": results["n_total"],
            "has_vix": results["has_vix"],
            "oos_period": results["oos_period"],
            "descriptive_stats": results["descriptive_stats"],
            "insample_diagnostics": clean_insample,
            "oos_results": results["oos_results"],
            "dm_vs_gjr": results["dm_vs_gjr"],
            "dm_vs_ewma": results["dm_vs_ewma"],
            "dm_pairwise_har": results["dm_pairwise_har"],
            "ranking": results["ranking"],
        }

    # Key findings
    findings = []
    for asset, results in all_results.items():
        best = results["ranking"][0]
        best_ql = results["oos_results"][best]["qlike"]
        findings.append(f"{asset}: Best model = {best} (QLIKE={best_ql:.6f})")

        # Check if any HAR beats GJR significantly (Harvey t>3)
        har_beat_gjr = [m for m, d in results["dm_vs_gjr"].items()
                        if m.startswith("HAR") and d["dm_stat"] < -3.0]
        if har_beat_gjr:
            findings.append(f"  HAR models beating GJR (Harvey): {har_beat_gjr}")
        else:
            findings.append(f"  No HAR model beats GJR at Harvey t>3 threshold")

        # Check if any HAR beats EWMA
        har_beat_ewma = [m for m, d in results["dm_vs_ewma"].items()
                         if m.startswith("HAR") and d["dm_stat"] < -3.0]
        if har_beat_ewma:
            findings.append(f"  HAR models beating EWMA (Harvey): {har_beat_ewma}")
        else:
            findings.append(f"  No HAR model beats EWMA at Harvey t>3 threshold")

    output["key_findings"] = findings

    # Save
    outfile = project_root / "experiments" / "k530_har_multiscale_results.json"
    with open(outfile, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n  Results saved to: {outfile}")
    print(f"  Total elapsed: {elapsed:.1f}s")

    # Final summary
    print_section("Key Findings", "=")
    for finding in findings:
        print(f"  {finding}")


if __name__ == "__main__":
    main()
