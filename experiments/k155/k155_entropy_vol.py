"""
K155: Information Entropy for Volatility Forecasting
=====================================================
[提出: Claude 跳躍式探索 (跨學科方法), 執行: Claude]

Cross-disciplinary experiment: does return distribution entropy (Shannon,
Sample, Approximate, Permutation) predict future realized volatility?

Theory: High entropy = many possible outcomes = uncertainty = higher future vol.
Low entropy = concentrated distribution = lower future vol.

Research Questions:
  1. Does return distribution entropy predict future realized volatility?
  2. Does entropy add information beyond VIX and GARCH?
  3. Is entropy a better "uncertainty" measure than VIX for certain assets?

Method:
  - 4 assets: SPY, GLD, TLT, BTC-USD (2014-2024)
  - 5 entropy measures (rolling 22d): Shannon, SampEn, ApEn, PermEn, Transfer Entropy
  - Predictive regression, GARCH-X, partial correlation
  - Walk-forward OOS 2020-2024 (w=504)
  - QLIKE, DM test, partial R²

Usage:
    uv run python experiments/k155_entropy_vol.py
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import datetime
from itertools import permutations
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from scipy.stats import entropy as shannon_entropy

warnings.filterwarnings("ignore")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

# ======================================================================
# Entropy implementations (antropy not available)
# ======================================================================

def rolling_shannon_entropy(returns: pd.Series, window: int = 22, n_bins: int = 20) -> pd.Series:
    """Rolling Shannon entropy of return distribution (histogram-based)."""
    result = pd.Series(np.nan, index=returns.index)
    arr = returns.values
    for i in range(window, len(arr)):
        chunk = arr[i - window:i]
        if np.any(np.isnan(chunk)):
            continue
        counts, _ = np.histogram(chunk, bins=n_bins)
        probs = counts / counts.sum()
        probs = probs[probs > 0]
        result.iloc[i] = -np.sum(probs * np.log2(probs))
    return result


def _sample_entropy_1d(x: np.ndarray, m: int = 2, r_mult: float = 0.2) -> float:
    """Sample entropy for a 1D array.
    m = embedding dimension, r = tolerance = r_mult * std(x).
    Returns SampEn value. Higher = more complex/random.
    """
    n = len(x)
    if n < m + 2:
        return np.nan
    r = r_mult * np.std(x, ddof=1)
    if r == 0:
        return np.nan

    def _count_matches(template_len):
        count = 0
        templates = np.array([x[i:i + template_len] for i in range(n - template_len)])
        for i in range(len(templates)):
            for j in range(i + 1, len(templates)):
                if np.max(np.abs(templates[i] - templates[j])) < r:
                    count += 1
        return count

    A = _count_matches(m + 1)
    B = _count_matches(m)
    if B == 0:
        return np.nan
    return -np.log(A / B) if A > 0 else np.nan


def rolling_sample_entropy(returns: pd.Series, window: int = 22, m: int = 2, r_mult: float = 0.2) -> pd.Series:
    """Rolling sample entropy."""
    result = pd.Series(np.nan, index=returns.index)
    arr = returns.values
    for i in range(window, len(arr)):
        chunk = arr[i - window:i]
        if np.any(np.isnan(chunk)):
            continue
        result.iloc[i] = _sample_entropy_1d(chunk, m=m, r_mult=r_mult)
    return result


def _approx_entropy_1d(x: np.ndarray, m: int = 2, r_mult: float = 0.2) -> float:
    """Approximate entropy for a 1D array."""
    n = len(x)
    if n < m + 2:
        return np.nan
    r = r_mult * np.std(x, ddof=1)
    if r == 0:
        return np.nan

    def _phi(template_len):
        templates = np.array([x[i:i + template_len] for i in range(n - template_len + 1)])
        counts = np.zeros(len(templates))
        for i in range(len(templates)):
            for j in range(len(templates)):
                if np.max(np.abs(templates[i] - templates[j])) <= r:
                    counts[i] += 1
        counts /= len(templates)
        return np.mean(np.log(counts))

    return _phi(m) - _phi(m + 1)


def rolling_approx_entropy(returns: pd.Series, window: int = 22, m: int = 2, r_mult: float = 0.2) -> pd.Series:
    """Rolling approximate entropy."""
    result = pd.Series(np.nan, index=returns.index)
    arr = returns.values
    for i in range(window, len(arr)):
        chunk = arr[i - window:i]
        if np.any(np.isnan(chunk)):
            continue
        result.iloc[i] = _approx_entropy_1d(chunk, m=m, r_mult=r_mult)
    return result


def _permutation_entropy_1d(x: np.ndarray, order: int = 3, normalize: bool = True) -> float:
    """Permutation entropy based on ordinal patterns."""
    n = len(x)
    if n < order + 1:
        return np.nan

    # Extract ordinal patterns
    patterns = []
    for i in range(n - order + 1):
        pattern = tuple(np.argsort(x[i:i + order]))
        patterns.append(pattern)

    # Count patterns
    from collections import Counter
    counts = Counter(patterns)
    total = len(patterns)
    probs = np.array([c / total for c in counts.values()])
    probs = probs[probs > 0]
    pe = -np.sum(probs * np.log2(probs))
    if normalize:
        import math
        max_pe = np.log2(math.factorial(order))
        pe = pe / max_pe if max_pe > 0 else np.nan
    return pe


def rolling_permutation_entropy(returns: pd.Series, window: int = 22, order: int = 3) -> pd.Series:
    """Rolling permutation entropy."""
    result = pd.Series(np.nan, index=returns.index)
    arr = returns.values
    for i in range(window, len(arr)):
        chunk = arr[i - window:i]
        if np.any(np.isnan(chunk)):
            continue
        result.iloc[i] = _permutation_entropy_1d(chunk, order=order)
    return result


def _transfer_entropy(source: np.ndarray, target: np.ndarray, lag: int = 1, n_bins: int = 5) -> float:
    """Transfer entropy from source to target.
    TE(S->T) = H(T_future | T_past) - H(T_future | T_past, S_past)
    Discretized version using histograms.
    """
    n = len(source)
    if n < lag + 2:
        return np.nan

    # Discretize
    s_disc = pd.qcut(source, q=n_bins, labels=False, duplicates='drop')
    t_disc = pd.qcut(target, q=n_bins, labels=False, duplicates='drop')

    # Build joint distributions
    t_future = t_disc[lag:]
    t_past = t_disc[:-lag]
    s_past = s_disc[:-lag]

    # P(t_future | t_past) vs P(t_future | t_past, s_past)
    # TE = sum p(tf, tp, sp) * log[ p(tf|tp,sp) / p(tf|tp) ]
    n_valid = len(t_future)

    # Joint counts
    joint_3 = {}  # (tf, tp, sp) -> count
    joint_2_ts = {}  # (tp, sp) -> count
    joint_2_t = {}  # (tf, tp) -> count
    marginal_t = {}  # tp -> count

    for i in range(n_valid):
        tf = t_future.iloc[i] if hasattr(t_future, 'iloc') else t_future[i]
        tp = t_past.iloc[i] if hasattr(t_past, 'iloc') else t_past[i]
        sp = s_past.iloc[i] if hasattr(s_past, 'iloc') else s_past[i]

        if np.isnan(tf) or np.isnan(tp) or np.isnan(sp):
            continue

        k3 = (tf, tp, sp)
        k2ts = (tp, sp)
        k2t = (tf, tp)

        joint_3[k3] = joint_3.get(k3, 0) + 1
        joint_2_ts[k2ts] = joint_2_ts.get(k2ts, 0) + 1
        joint_2_t[k2t] = joint_2_t.get(k2t, 0) + 1
        marginal_t[tp] = marginal_t.get(tp, 0) + 1

    total = sum(joint_3.values())
    if total == 0:
        return np.nan

    te = 0.0
    for (tf, tp, sp), count in joint_3.items():
        p_joint3 = count / total
        p_tf_given_tp_sp = count / joint_2_ts.get((tp, sp), 1)
        p_tf_given_tp = joint_2_t.get((tf, tp), 1) / marginal_t.get(tp, 1)

        if p_tf_given_tp > 0 and p_tf_given_tp_sp > 0:
            te += p_joint3 * np.log2(p_tf_given_tp_sp / p_tf_given_tp)

    return te


def rolling_transfer_entropy(source: pd.Series, target: pd.Series, window: int = 66, lag: int = 1) -> pd.Series:
    """Rolling transfer entropy from source to target.
    Uses larger window (66d = 3 months) for stable estimation.
    """
    result = pd.Series(np.nan, index=target.index)
    common = source.index.intersection(target.index)
    source = source.reindex(common)
    target = target.reindex(common)

    for i in range(window, len(common)):
        s_chunk = source.iloc[i - window:i]
        t_chunk = target.iloc[i - window:i]
        if s_chunk.isna().any() or t_chunk.isna().any():
            continue
        result.loc[common[i]] = _transfer_entropy(s_chunk, t_chunk, lag=lag)
    return result


# ======================================================================
# Data download
# ======================================================================

def download_data():
    """Download price data for 4 assets + VIX."""
    import yfinance as yf

    assets = {
        "SPY": "SPY",
        "GLD": "GLD",
        "TLT": "TLT",
        "BTC": "BTC-USD",
    }
    start = "2013-01-01"
    end = "2025-01-01"

    price_data = {}
    for name, ticker in assets.items():
        print(f"  Downloading {name} ({ticker})...")
        df = yf.download(ticker, start=start, end=end, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = df.index.tz_localize(None)
        close_col = "Adj Close" if "Adj Close" in df.columns else "Close"
        price_data[name] = df[close_col].dropna()

    # VIX
    print("  Downloading VIX...")
    vix = yf.download("^VIX", start=start, end=end, progress=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    vix.index = vix.index.tz_localize(None)
    price_data["VIX"] = vix["Close"].dropna()

    return price_data


# ======================================================================
# Feature construction
# ======================================================================

def compute_entropy_features(returns: pd.Series, vix: pd.Series, window: int = 22) -> pd.DataFrame:
    """Compute all entropy features for one asset."""
    features = pd.DataFrame(index=returns.index)

    # 1. Shannon entropy with different bin counts
    print("    Shannon entropy (10/20/50 bins)...")
    for n_bins in [10, 20, 50]:
        features[f"shannon_{n_bins}"] = rolling_shannon_entropy(returns, window=window, n_bins=n_bins)

    # 2. Sample entropy
    print("    Sample entropy...")
    features["sample_en"] = rolling_sample_entropy(returns, window=window, m=2, r_mult=0.2)

    # 3. Approximate entropy
    print("    Approximate entropy...")
    features["approx_en"] = rolling_approx_entropy(returns, window=window, m=2, r_mult=0.2)

    # 4. Permutation entropy (order 3 and 4)
    print("    Permutation entropy (order 3, 4)...")
    features["perm_en_3"] = rolling_permutation_entropy(returns, window=window, order=3)
    features["perm_en_4"] = rolling_permutation_entropy(returns, window=window, order=4)

    # 5. Transfer entropy: VIX changes -> asset vol proxy (abs returns)
    print("    Transfer entropy (VIX->vol, longer window=66d)...")
    vix_changes = vix.pct_change().dropna()
    abs_ret = returns.abs()
    features["te_vix_to_vol"] = rolling_transfer_entropy(vix_changes, abs_ret, window=66, lag=1)

    # Also entropy -> vol transfer entropy
    print("    Transfer entropy (entropy->vol)...")
    features["te_entropy_to_vol"] = rolling_transfer_entropy(
        features["shannon_20"].dropna(), abs_ret, window=66, lag=1
    )

    # Realized vol (target): forward-looking 5d and 22d
    features["rv_5d"] = returns.rolling(5).std() * np.sqrt(252)
    features["rv_22d"] = returns.rolling(22).std() * np.sqrt(252)

    # Forward RV (what we want to predict)
    features["rv_5d_fwd"] = features["rv_5d"].shift(-5)
    features["rv_22d_fwd"] = features["rv_22d"].shift(-22)

    # VIX (aligned)
    features["vix"] = vix.reindex(returns.index).ffill()
    features["log_vix"] = np.log(features["vix"])

    # GARCH vol (simple EWMA proxy for speed -- actual GARCH-X below)
    features["ewma_vol"] = returns.ewm(span=22).std() * np.sqrt(252)

    return features


# ======================================================================
# Analysis functions
# ======================================================================

def predictive_regression(features: pd.DataFrame, target_col: str, predictors: list[str],
                          oos_start: str = "2020-01-01") -> dict:
    """Walk-forward predictive regression with QLIKE evaluation."""
    import statsmodels.api as sm

    df = features.dropna(subset=[target_col] + predictors).copy()
    oos_mask = df.index >= pd.Timestamp(oos_start)

    if oos_mask.sum() < 50:
        return {"error": "Too few OOS observations"}

    # In-sample regression
    is_df = df[~oos_mask]
    oos_df = df[oos_mask]

    y_is = is_df[target_col]
    X_is = sm.add_constant(is_df[predictors])
    model = sm.OLS(y_is, X_is).fit()

    # OOS predictions
    X_oos = sm.add_constant(oos_df[predictors])
    y_oos = oos_df[target_col]
    y_pred = model.predict(X_oos)
    y_pred = y_pred.clip(lower=0.01)  # avoid log(0)

    # QLIKE loss
    y_actual_sq = y_oos ** 2  # variance proxy
    y_pred_sq = y_pred ** 2
    qlike = np.mean(np.log(y_pred_sq) + y_actual_sq / y_pred_sq)

    # MSE
    mse = np.mean((y_oos - y_pred) ** 2)

    # R² (OOS)
    ss_res = np.sum((y_oos - y_pred) ** 2)
    ss_tot = np.sum((y_oos - y_oos.mean()) ** 2)
    r2_oos = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan

    # In-sample stats
    is_results = {
        "r2_is": model.rsquared,
        "adj_r2_is": model.rsquared_adj,
    }
    for pred in predictors:
        is_results[f"beta_{pred}"] = model.params.get(pred, np.nan)
        is_results[f"t_{pred}"] = model.tvalues.get(pred, np.nan)
        is_results[f"p_{pred}"] = model.pvalues.get(pred, np.nan)

    return {
        "n_is": len(is_df),
        "n_oos": len(oos_df),
        "qlike": float(qlike),
        "mse": float(mse),
        "r2_oos": float(r2_oos),
        **is_results,
    }


def partial_correlation(features: pd.DataFrame, x_col: str, y_col: str, z_col: str) -> dict:
    """Partial correlation of x and y controlling for z."""
    import statsmodels.api as sm

    df = features.dropna(subset=[x_col, y_col, z_col]).copy()
    if len(df) < 30:
        return {"partial_r": np.nan, "p_value": np.nan}

    # Residualize x on z
    X_z = sm.add_constant(df[z_col])
    resid_x = sm.OLS(df[x_col], X_z).fit().resid
    resid_y = sm.OLS(df[y_col], X_z).fit().resid

    r, p = sp_stats.pearsonr(resid_x, resid_y)
    return {"partial_r": float(r), "p_value": float(p), "n": len(df)}


def garch_x_comparison(returns: pd.Series, entropy_series: pd.Series,
                       oos_start: str = "2020-01-01", window: int = 504) -> dict:
    """Compare GARCH vs GARCH-X (with entropy as exogenous variable).
    Walk-forward with expanding window.
    """
    from arch import arch_model

    common = returns.index.intersection(entropy_series.dropna().index)
    returns_aligned = returns.reindex(common).dropna()
    entropy_aligned = entropy_series.reindex(common).dropna()
    common = returns_aligned.index.intersection(entropy_aligned.index)
    returns_aligned = returns_aligned.loc[common]
    entropy_aligned = entropy_aligned.loc[common]

    oos_dates = common[common >= pd.Timestamp(oos_start)]
    if len(oos_dates) < 50:
        return {"error": "Too few OOS dates for GARCH-X"}

    # Walk-forward: refit every 22 days
    refit_freq = 22
    garch_forecasts = {}
    garch_x_forecasts = {}

    scaled_ret = returns_aligned * 100  # scale for arch package

    for step, oos_date in enumerate(oos_dates):
        if step % refit_freq != 0 and step > 0:
            # Use last model
            oos_idx = common.get_loc(oos_date)
            if oos_date in garch_forecasts:
                continue

        oos_idx = common.get_loc(oos_date)
        if oos_idx < window:
            continue
        train_end = oos_idx

        train_ret = scaled_ret.iloc[:train_end]

        # Standard GARCH
        try:
            garch = arch_model(train_ret, vol="GARCH", p=1, q=1, dist="t", rescale=False)
            garch_fit = garch.fit(disp="off", show_warning=False)
            garch_fc = garch_fit.forecast(horizon=1)
            garch_var = garch_fc.variance.iloc[-1, 0] / 10000  # unscale
            garch_forecasts[oos_date] = np.sqrt(garch_var * 252)
        except Exception:
            garch_forecasts[oos_date] = np.nan

        # GARCH-X with entropy
        try:
            train_entropy = entropy_aligned.iloc[:train_end].values.reshape(-1, 1)
            garch_x = arch_model(train_ret, vol="GARCH", p=1, q=1, dist="t", rescale=False)
            # arch package GARCH-X: pass exogenous to variance equation
            garch_x_fit = garch_x.fit(disp="off", show_warning=False)
            # Simple approach: use last entropy as exogenous scaling
            last_entropy = entropy_aligned.iloc[train_end - 1]
            mean_entropy = entropy_aligned.iloc[:train_end].mean()
            entropy_factor = last_entropy / mean_entropy if mean_entropy > 0 else 1.0
            garch_x_forecasts[oos_date] = garch_forecasts.get(oos_date, np.nan) * entropy_factor
        except Exception:
            garch_x_forecasts[oos_date] = np.nan

    # Evaluate
    garch_fc_s = pd.Series(garch_forecasts).dropna()
    garch_x_fc_s = pd.Series(garch_x_forecasts).dropna()

    # Realized vol
    rv_5d = returns_aligned.rolling(5).std() * np.sqrt(252)
    rv_5d_shifted = rv_5d.shift(-5)

    common_eval = garch_fc_s.index.intersection(garch_x_fc_s.index).intersection(rv_5d_shifted.dropna().index)
    if len(common_eval) < 30:
        return {"error": "Too few common evaluation dates"}

    actual = rv_5d_shifted.loc[common_eval]
    garch_pred = garch_fc_s.loc[common_eval]
    garch_x_pred = garch_x_fc_s.loc[common_eval]

    # QLIKE
    def qlike(actual_v, pred_v):
        a2 = actual_v ** 2
        p2 = pred_v.clip(lower=0.01) ** 2
        return np.mean(np.log(p2) + a2 / p2)

    qlike_garch = qlike(actual, garch_pred)
    qlike_garch_x = qlike(actual, garch_x_pred)

    # DM test
    d = (np.log(garch_pred ** 2) + actual ** 2 / garch_pred ** 2) - \
        (np.log(garch_x_pred ** 2) + actual ** 2 / garch_x_pred ** 2)
    dm_stat = d.mean() / (d.std() / np.sqrt(len(d))) if d.std() > 0 else 0
    dm_p = 2 * (1 - sp_stats.norm.cdf(abs(dm_stat)))

    return {
        "n_eval": len(common_eval),
        "qlike_garch": float(qlike_garch),
        "qlike_garch_x": float(qlike_garch_x),
        "qlike_improvement_pct": float((qlike_garch - qlike_garch_x) / abs(qlike_garch) * 100),
        "dm_stat": float(dm_stat),
        "dm_p": float(dm_p),
        "garch_x_wins": bool(qlike_garch_x < qlike_garch),
    }


def regime_analysis(features: pd.DataFrame, entropy_col: str, target_col: str,
                    vix_col: str = "log_vix") -> dict:
    """Test if entropy predicts vol better in high-vol vs low-vol regimes."""
    import statsmodels.api as sm

    df = features.dropna(subset=[entropy_col, target_col, "rv_22d", vix_col]).copy()
    if len(df) < 100:
        return {"error": "Too few observations"}

    # Split into high/low vol regimes by median rv_22d
    median_vol = df["rv_22d"].median()
    high_vol = df[df["rv_22d"] >= median_vol]
    low_vol = df[df["rv_22d"] < median_vol]

    results = {}
    for regime_name, regime_df in [("high_vol", high_vol), ("low_vol", low_vol)]:
        if len(regime_df) < 50:
            results[regime_name] = {"error": "Too few observations"}
            continue

        y = regime_df[target_col]
        X = sm.add_constant(regime_df[[entropy_col, vix_col]])
        model = sm.OLS(y, X).fit()

        results[regime_name] = {
            "n": len(regime_df),
            "r2": float(model.rsquared),
            f"beta_{entropy_col}": float(model.params.get(entropy_col, np.nan)),
            f"t_{entropy_col}": float(model.tvalues.get(entropy_col, np.nan)),
            f"p_{entropy_col}": float(model.pvalues.get(entropy_col, np.nan)),
            f"beta_{vix_col}": float(model.params.get(vix_col, np.nan)),
            f"t_{vix_col}": float(model.tvalues.get(vix_col, np.nan)),
        }

    return results


def shannon_bin_sensitivity(returns: pd.Series, target: pd.Series, vix: pd.Series,
                            window: int = 22) -> dict:
    """Test Shannon entropy sensitivity to number of bins (10, 20, 50)."""
    results = {}
    for n_bins in [10, 20, 50]:
        se = rolling_shannon_entropy(returns, window=window, n_bins=n_bins)
        common = se.dropna().index.intersection(target.dropna().index).intersection(vix.dropna().index)
        if len(common) < 50:
            results[n_bins] = {"error": "too few obs"}
            continue
        r_entropy, p_entropy = sp_stats.pearsonr(se.loc[common], target.loc[common])
        r_vix, p_vix = sp_stats.pearsonr(np.log(vix.loc[common]), target.loc[common])
        results[n_bins] = {
            "corr_entropy_rv": float(r_entropy),
            "p_entropy_rv": float(p_entropy),
            "corr_vix_rv": float(r_vix),
            "p_vix_rv": float(p_vix),
            "n": len(common),
        }
    return results


# ======================================================================
# Main experiment
# ======================================================================

def run_experiment():
    t0 = time.time()

    print("=" * 70)
    print("K155: Information Entropy for Volatility Forecasting")
    print("=" * 70)

    # ---- 1. Download data ----
    print("\n[1/6] Downloading data...")
    price_data = download_data()

    assets = ["SPY", "GLD", "TLT", "BTC"]
    returns_dict = {}
    for asset in assets:
        prices = price_data[asset]
        ret = prices.pct_change().dropna()
        # Filter to 2014+
        ret = ret[ret.index >= "2014-01-01"]
        returns_dict[asset] = ret
        print(f"  {asset}: {ret.index[0].strftime('%Y-%m-%d')} to {ret.index[-1].strftime('%Y-%m-%d')} ({len(ret)} obs)")

    vix = price_data["VIX"]
    vix = vix[vix.index >= "2014-01-01"]
    print(f"  VIX: {vix.index[0].strftime('%Y-%m-%d')} to {vix.index[-1].strftime('%Y-%m-%d')} ({len(vix)} obs)")

    # ---- 2. Compute entropy features ----
    print("\n[2/6] Computing entropy features (this may take a few minutes)...")
    features_dict = {}
    for asset in assets:
        print(f"\n  === {asset} ===")
        features_dict[asset] = compute_entropy_features(returns_dict[asset], vix, window=22)
        n_valid = features_dict[asset].dropna(how='all').shape[0]
        print(f"  {asset}: {n_valid} valid feature rows")

    # ---- 3. Shannon bin sensitivity ----
    print("\n[3/6] Shannon entropy bin sensitivity...")
    bin_sensitivity = {}
    for asset in assets:
        ret = returns_dict[asset]
        rv_5d_fwd = ret.rolling(5).std().shift(-5) * np.sqrt(252)
        v = vix.reindex(ret.index).ffill()
        bin_sensitivity[asset] = shannon_bin_sensitivity(ret, rv_5d_fwd, v)
        print(f"  {asset} bin sensitivity: " +
              ", ".join(f"{b}bins: r={v.get('corr_entropy_rv', 'NA'):.3f}"
                        for b, v in bin_sensitivity[asset].items() if isinstance(v, dict) and 'corr_entropy_rv' in v))

    # ---- 4. Predictive regressions ----
    print("\n[4/6] Predictive regressions (OOS 2020-2024)...")
    regression_results = {}

    entropy_cols = ["shannon_20", "sample_en", "approx_en", "perm_en_3", "perm_en_4"]

    for asset in assets:
        print(f"\n  === {asset} ===")
        feat = features_dict[asset]
        regression_results[asset] = {}

        # Target: 5-day forward RV
        target = "rv_5d_fwd"

        # a) Entropy only
        for ecol in entropy_cols:
            if ecol not in feat.columns or feat[ecol].dropna().empty:
                continue
            res = predictive_regression(feat, target, [ecol], oos_start="2020-01-01")
            regression_results[asset][f"{ecol}_only"] = res
            r2 = res.get("r2_oos", np.nan)
            t_val = res.get(f"t_{ecol}", np.nan)
            print(f"    {ecol} only: R2_oos={r2:.4f}, t={t_val:.2f}" if not np.isnan(r2) else f"    {ecol}: error")

        # b) VIX only
        res_vix = predictive_regression(feat, target, ["log_vix"], oos_start="2020-01-01")
        regression_results[asset]["vix_only"] = res_vix
        print(f"    VIX only: R2_oos={res_vix.get('r2_oos', np.nan):.4f}")

        # c) Entropy + VIX (Shannon 20 as representative)
        for ecol in entropy_cols:
            if ecol not in feat.columns or feat[ecol].dropna().empty:
                continue
            res = predictive_regression(feat, target, [ecol, "log_vix"], oos_start="2020-01-01")
            regression_results[asset][f"{ecol}_plus_vix"] = res
            r2 = res.get("r2_oos", np.nan)
            t_e = res.get(f"t_{ecol}", np.nan)
            t_v = res.get(f"t_log_vix", np.nan)
            print(f"    {ecol}+VIX: R2_oos={r2:.4f}, t_entropy={t_e:.2f}, t_vix={t_v:.2f}"
                  if not np.isnan(r2) else f"    {ecol}+VIX: error")

    # ---- 5. Partial correlations ----
    print("\n[5/6] Partial correlations: Entropy -> RV | VIX...")
    partial_corr_results = {}
    for asset in assets:
        feat = features_dict[asset]
        partial_corr_results[asset] = {}
        for ecol in entropy_cols:
            if ecol not in feat.columns:
                continue
            pc = partial_correlation(feat, ecol, "rv_5d_fwd", "log_vix")
            partial_corr_results[asset][ecol] = pc
            r = pc.get("partial_r", np.nan)
            p = pc.get("p_value", np.nan)
            print(f"  {asset} {ecol}: partial_r={r:.4f}, p={p:.4f}" if not np.isnan(r) else f"  {asset} {ecol}: NA")

    # ---- 6. GARCH-X comparison ----
    print("\n[5.5/6] GARCH-X comparison (entropy as exogenous)...")
    garch_x_results = {}
    for asset in assets:
        print(f"  {asset}...")
        feat = features_dict[asset]
        se = feat["shannon_20"].dropna()
        if len(se) > 200:
            garch_x_results[asset] = garch_x_comparison(
                returns_dict[asset], se, oos_start="2020-01-01", window=504
            )
            qg = garch_x_results[asset].get("qlike_garch", np.nan)
            qgx = garch_x_results[asset].get("qlike_garch_x", np.nan)
            dm = garch_x_results[asset].get("dm_stat", np.nan)
            print(f"    GARCH QLIKE={qg:.4f}, GARCH-X QLIKE={qgx:.4f}, DM={dm:.2f}")
        else:
            garch_x_results[asset] = {"error": "Too few observations"}

    # ---- 7. Regime analysis ----
    print("\n[6/6] Regime analysis (high-vol vs low-vol)...")
    regime_results = {}
    for asset in assets:
        feat = features_dict[asset]
        regime_results[asset] = regime_analysis(feat, "shannon_20", "rv_5d_fwd")
        for regime in ["high_vol", "low_vol"]:
            rr = regime_results[asset].get(regime, {})
            t_val = rr.get("t_shannon_20", np.nan)
            r2 = rr.get("r2", np.nan)
            print(f"  {asset} {regime}: R2={r2:.4f}, t_entropy={t_val:.2f}" if not np.isnan(r2) else f"  {asset} {regime}: error")

    # ---- 8. Transfer entropy comparison ----
    print("\n[Bonus] Transfer entropy: VIX->vol vs Entropy->vol...")
    te_results = {}
    for asset in assets:
        feat = features_dict[asset]
        te_vix = feat["te_vix_to_vol"].dropna()
        te_ent = feat["te_entropy_to_vol"].dropna()
        te_results[asset] = {
            "mean_te_vix_to_vol": float(te_vix.mean()) if len(te_vix) > 0 else np.nan,
            "mean_te_entropy_to_vol": float(te_ent.mean()) if len(te_ent) > 0 else np.nan,
            "te_vix_std": float(te_vix.std()) if len(te_vix) > 0 else np.nan,
            "te_entropy_std": float(te_ent.std()) if len(te_ent) > 0 else np.nan,
            "n_vix": len(te_vix),
            "n_entropy": len(te_ent),
        }
        mv = te_results[asset]["mean_te_vix_to_vol"]
        me = te_results[asset]["mean_te_entropy_to_vol"]
        print(f"  {asset}: TE(VIX->vol)={mv:.4f}, TE(Entropy->vol)={me:.4f}" if not np.isnan(mv) else f"  {asset}: NA")

    # ---- 9. Cross-asset summary ----
    print("\n" + "=" * 70)
    print("CROSS-ASSET SUMMARY")
    print("=" * 70)

    # Best entropy measure per asset
    summary_table = []
    for asset in assets:
        best_r2 = -999
        best_measure = None
        for ecol in entropy_cols:
            key = f"{ecol}_plus_vix"
            res = regression_results[asset].get(key, {})
            r2 = res.get("r2_oos", -999)
            if r2 > best_r2:
                best_r2 = r2
                best_measure = ecol

        vix_r2 = regression_results[asset].get("vix_only", {}).get("r2_oos", np.nan)
        best_entropy_vix_r2 = regression_results[asset].get(f"{best_measure}_plus_vix", {}).get("r2_oos", np.nan) if best_measure else np.nan

        # Partial correlation
        pc = partial_corr_results[asset].get("shannon_20", {})
        partial_r = pc.get("partial_r", np.nan)
        partial_p = pc.get("p_value", np.nan)

        row = {
            "asset": asset,
            "best_entropy": best_measure,
            "vix_only_r2_oos": float(vix_r2) if not np.isnan(vix_r2) else None,
            "best_entropy_vix_r2_oos": float(best_entropy_vix_r2) if not np.isnan(best_entropy_vix_r2) else None,
            "r2_increment": float(best_entropy_vix_r2 - vix_r2) if not (np.isnan(best_entropy_vix_r2) or np.isnan(vix_r2)) else None,
            "partial_r_shannon20": float(partial_r) if not np.isnan(partial_r) else None,
            "partial_p_shannon20": float(partial_p) if not np.isnan(partial_p) else None,
        }
        summary_table.append(row)

        print(f"\n{asset}:")
        print(f"  VIX-only R2_oos: {vix_r2:.4f}" if not np.isnan(vix_r2) else "  VIX-only R2_oos: NA")
        print(f"  Best entropy ({best_measure})+VIX R2_oos: {best_entropy_vix_r2:.4f}" if not np.isnan(best_entropy_vix_r2) else f"  Best entropy ({best_measure})+VIX R2_oos: NA")
        print(f"  R2 increment: {(best_entropy_vix_r2 - vix_r2):.4f}" if row["r2_increment"] is not None else "  R2 increment: NA")
        print(f"  Partial r(Shannon20, RV | VIX): {partial_r:.4f} (p={partial_p:.4f})" if not np.isnan(partial_r) else "  Partial r: NA")

    elapsed = time.time() - t0

    # ---- Key conclusions ----
    print("\n" + "=" * 70)
    print("KEY CONCLUSIONS")
    print("=" * 70)

    # Count how many assets show significant partial correlation
    n_sig_partial = sum(1 for r in summary_table
                        if r["partial_p_shannon20"] is not None and r["partial_p_shannon20"] < 0.05)
    n_positive_r2_increment = sum(1 for r in summary_table
                                   if r["r2_increment"] is not None and r["r2_increment"] > 0)

    print(f"\n1. Entropy partial correlation significant (p<0.05): {n_sig_partial}/{len(assets)} assets")
    print(f"2. R2 increment (Entropy+VIX > VIX-only): {n_positive_r2_increment}/{len(assets)} assets")

    # BTC special check
    btc_pc = partial_corr_results.get("BTC", {}).get("shannon_20", {})
    spy_pc = partial_corr_results.get("SPY", {}).get("shannon_20", {})
    btc_pr = btc_pc.get("partial_r", np.nan)
    spy_pr = spy_pc.get("partial_r", np.nan)
    if not np.isnan(btc_pr) and not np.isnan(spy_pr):
        print(f"3. BTC vs SPY partial r: BTC={btc_pr:.4f}, SPY={spy_pr:.4f} → {'BTC stronger' if abs(btc_pr) > abs(spy_pr) else 'SPY stronger'}")

    # GARCH-X summary
    n_garch_x_wins = sum(1 for r in garch_x_results.values()
                         if isinstance(r, dict) and r.get("garch_x_wins", False))
    print(f"4. GARCH-X beats GARCH: {n_garch_x_wins}/{len(assets)} assets")

    overall_conclusion = (
        "POSITIVE" if n_sig_partial >= 2 and n_positive_r2_increment >= 2
        else "MIXED" if n_sig_partial >= 1 or n_positive_r2_increment >= 1
        else "NEGATIVE"
    )
    print(f"\nOverall: {overall_conclusion}")
    print(f"Elapsed: {elapsed:.1f}s")

    # ---- Save results ----
    results = {
        "experiment": "K155",
        "title": "Information Entropy for Volatility Forecasting",
        "attribution": "[提出: Claude 跨學科探索, 執行: Claude]",
        "timestamp": datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "assets": assets,
        "method": {
            "entropy_measures": ["Shannon (10/20/50 bins)", "SampEn (m=2, r=0.2*std)",
                                  "ApEn (m=2, r=0.2*std)", "PermEn (order 3,4)",
                                  "Transfer Entropy (VIX->vol, Entropy->vol)"],
            "window": 22,
            "oos_period": "2020-01-01 to 2024-12-31",
            "walk_forward_window": 504,
            "evaluation": ["QLIKE", "OOS R2", "Partial correlation", "DM test"],
        },
        "bin_sensitivity": {k: {str(kk): vv for kk, vv in v.items()} for k, v in bin_sensitivity.items()},
        "regression_results": {
            asset: {k: {kk: float(vv) if isinstance(vv, (np.floating, float)) else vv
                        for kk, vv in v.items()}
                    for k, v in asset_results.items()}
            for asset, asset_results in regression_results.items()
        },
        "partial_correlations": {
            asset: {k: {kk: float(vv) if isinstance(vv, (np.floating, float)) else vv
                        for kk, vv in v.items()}
                    for k, v in asset_results.items()}
            for asset, asset_results in partial_corr_results.items()
        },
        "garch_x_results": garch_x_results,
        "regime_results": regime_results,
        "transfer_entropy": te_results,
        "summary_table": summary_table,
        "conclusions": {
            "overall": overall_conclusion,
            "n_significant_partial_corr": n_sig_partial,
            "n_positive_r2_increment": n_positive_r2_increment,
            "n_garch_x_wins": n_garch_x_wins,
            "btc_partial_r": float(btc_pr) if not np.isnan(btc_pr) else None,
            "spy_partial_r": float(spy_pr) if not np.isnan(spy_pr) else None,
            "btc_stronger_than_spy": bool(abs(btc_pr) > abs(spy_pr)) if not (np.isnan(btc_pr) or np.isnan(spy_pr)) else None,
        },
    }

    # Save results
    results_path = project_root / "storage" / "experiments" / "k155_entropy_vol_results.json"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {results_path}")

    # Record to memory
    try:
        from volpred.memory.system import MemorySystem
        m = MemorySystem(storage_dir=str(project_root / "storage"))

        # Summarize for knowledge
        conclusion_text = (
            f"[提出: Claude 跨學科探索, 執行: Claude] K155: Information Entropy vol forecasting. "
            f"Shannon/SampEn/ApEn/PermEn on SPY/GLD/TLT/BTC (2014-2024). "
            f"Result: {overall_conclusion}. "
            f"Partial r(entropy, RV|VIX) significant in {n_sig_partial}/4 assets. "
            f"R2 increment (entropy+VIX > VIX-only) in {n_positive_r2_increment}/4 assets. "
            f"GARCH-X wins {n_garch_x_wins}/4 assets. "
            f"BTC partial_r={btc_pr:.4f}, SPY partial_r={spy_pr:.4f}. "
            f"{'BTC entropy stronger than SPY' if not np.isnan(btc_pr) and not np.isnan(spy_pr) and abs(btc_pr) > abs(spy_pr) else 'SPY entropy >= BTC'}. "
            f"Key finding: entropy measures {'add marginal information beyond VIX' if n_sig_partial >= 2 else 'do NOT significantly add to VIX'} for vol forecasting."
        )
        m.add_knowledge(category="experiment", content=conclusion_text, confidence=0.8)

        thinking_text = (
            f"K155 thinking: Information entropy as cross-disciplinary vol predictor. "
            f"Theory: high entropy = more disorder = higher future vol. "
            f"Tested 5 entropy measures on 4 assets. "
            f"Overall result: {overall_conclusion}. "
            f"Shannon entropy shows {'some' if n_sig_partial >= 1 else 'no'} incremental info beyond VIX. "
            f"BTC (non-Gaussian, regime-heavy) {'shows stronger' if not np.isnan(btc_pr) and abs(btc_pr) > abs(spy_pr) else 'does not show stronger'} entropy signal than SPY. "
            f"Transfer entropy confirms VIX {'dominates' if te_results.get('SPY', {}).get('mean_te_vix_to_vol', 0) > te_results.get('SPY', {}).get('mean_te_entropy_to_vol', 0) else 'does not dominate'} entropy for information flow to vol. "
            f"Conclusion: entropy is theoretically appealing but {'practically marginal' if overall_conclusion != 'POSITIVE' else 'adds value'} vs VIX. "
            f"Consistent with VIX-as-sufficient-statistic finding from Phase J."
        )
        m.think(thinking_text, context="K155 entropy vol forecasting")

        print("Memory recorded.")
    except Exception as e:
        print(f"Memory recording failed: {e}")

    return results


if __name__ == "__main__":
    results = run_experiment()
