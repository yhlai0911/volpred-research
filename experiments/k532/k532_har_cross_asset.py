"""K532: HAR-VIX Cross-Asset Validation — Does K530's HAR breakthrough hold across 7+ assets?

Background:
  K530 found HAR-ABS beats GJR-GARCH with DM=-15.45 for SPY and DM=-14.3 for 0050.TW.
  This is the strongest result in our knowledge base. But cross-asset validation is required
  (CLAUDE.md: >= 7 assets for cross-sectional claims).

K530 key findings to validate:
  1. HAR with |r_t| proxy >> HAR with r²_t proxy (3x QLIKE difference)
  2. HAR-VIX is the best single model (adds VIX as regressor)
  3. β5 (5-day) dominates, β1 slightly negative (mean-reversion)
  4. Bad vol predicts future vol 4.8x more than good vol (semivariance)

Literature basis:
  - Corsi (2009, JFE): Original HAR-RV — multi-scale RV decomposition
  - Patton & Sheppard (2015): Semivariance decomposition (good/bad vol)
  - Andersen, Bollerslev, Diebold & Labys (2003): Realized volatility
  - K529: HAR-Rough beat GJR-GARCH (DM=-7.04)
  - K530: HAR-ABS DM=-15.45 vs GJR (SPY), DM=-14.3 (0050.TW)

Assets (7):
  SPY   — US large-cap equity (benchmark)
  QQQ   — US tech equity (high vol)
  EFA   — International developed equity
  EWZ   — Emerging market equity (Brazil, very high vol)
  GLD   — Gold (commodity/safe-haven)
  TLT   — US Treasury bonds (rates)
  0050.TW — Taiwan large-cap equity

Models tested:
  HAR-ABS:      c + β1·|r1| + β5·RV5_abs + β22·RV22_abs
  HAR-SQ:       Same with r² proxy
  HAR-RS:       Semivariance (pos + neg) + RV22_sq
  HAR-VIX:      HAR-ABS + VIX (SPY only — VIX is US-specific)
  HAR-LEVERAGE: HAR-ABS + leverage term (neg return × RV)
  GJR-GARCH(1,1): Standard benchmark
  EWMA(0.94):    Strong baseline per K529

Method: OLS rolling window w=500 for HAR, w=2000 for GJR, OOS 2023-2024
Evaluation: QLIKE + DM test (pairwise, HAR-ABS as reference)

Cross-sectional analysis:
  - Spearman rank correlation of model rankings across assets
  - Is HAR advantage universal or equity-specific?
  - β coefficient stability across assets

Usage:
    uv run python experiments/k532_har_cross_asset.py

Data source: yfinance (daily), 2005-2026 where available
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

# ============================================================
#  Configuration
# ============================================================

ASSETS = ["SPY", "QQQ", "EFA", "EWZ", "GLD", "TLT", "0050.TW"]
HAR_WINDOW = 500
GJR_WINDOW = 2000
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
EWMA_LAMBDA = 0.94
GJR_REFIT_EVERY = 21

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
        return (0.0, 1.0)
    dm_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(dm_stat), df=T - 1))
    return (float(dm_stat), float(p_value))


# ============================================================
#  Data Loading
# ============================================================

def load_asset_data(ticker: str, start: str = "2004-01-01") -> pd.DataFrame | None:
    """Load daily data from yfinance."""
    import yfinance as yf
    print(f"  Downloading {ticker}...", end=" ", flush=True)
    try:
        df = yf.download(ticker, start=start, auto_adjust=True, progress=False)
        if df.empty or len(df) < 600:
            print(f"SKIP (only {len(df)} obs)")
            return None
        # Handle MultiIndex columns from yfinance
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[["Close"]].dropna()
        df["log_return"] = np.log(df["Close"] / df["Close"].shift(1))
        df = df.dropna()
        print(f"OK ({len(df)} obs, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")
        return df
    except Exception as e:
        print(f"ERROR: {e}")
        return None


def load_vix(start: str = "2004-01-01") -> pd.Series | None:
    """Load VIX index for HAR-VIX model."""
    import yfinance as yf
    try:
        vix = yf.download("^VIX", start=start, auto_adjust=True, progress=False)
        if isinstance(vix.columns, pd.MultiIndex):
            vix.columns = vix.columns.get_level_values(0)
        return vix["Close"].dropna()
    except Exception:
        return None


# ============================================================
#  HAR Feature Construction (vectorized for speed)
# ============================================================

def build_har_features(df: pd.DataFrame, vix_series: pd.Series | None = None) -> pd.DataFrame:
    """Build HAR features from daily data. Vectorized implementation."""
    r = df["log_return"].values.copy()

    abs_r = np.abs(r)
    sq_r = r ** 2

    # Rolling averages (vectorized via pandas)
    abs_s = pd.Series(abs_r, index=df.index)
    sq_s = pd.Series(sq_r, index=df.index)

    rv1_abs = abs_r.copy()
    rv5_abs = abs_s.rolling(5).mean().values
    rv22_abs = abs_s.rolling(22).mean().values

    rv1_sq = sq_r.copy()
    rv5_sq = sq_s.rolling(5).mean().values
    rv22_sq = sq_s.rolling(22).mean().values

    # Semivariance: positive and negative components (rolling 5-day)
    rs_pos = np.where(r > 0, sq_r, 0.0)
    rs_neg = np.where(r < 0, sq_r, 0.0)
    rs_pos_5 = pd.Series(rs_pos, index=df.index).rolling(5).mean().values
    rs_neg_5 = pd.Series(rs_neg, index=df.index).rolling(5).mean().values

    # Leverage term: I(r<0) * |r| * rv5_abs
    leverage = np.where(r < 0, abs_r * rv5_abs, 0.0)

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
        "leverage": leverage,
        "target_abs": target_abs,
        "target_sq": target_sq,
    }, index=df.index)

    # Add VIX if available (aligned by date)
    if vix_series is not None:
        # Align VIX to asset dates
        vix_aligned = vix_series.reindex(df.index).ffill()
        features["vix"] = vix_aligned.values / 100.0 / np.sqrt(252)  # annualized → daily scale

    return features


# ============================================================
#  HAR Model Definitions
# ============================================================

def ols_fit(X: np.ndarray, y: np.ndarray) -> np.ndarray:
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
    return max(pred, 1e-10)


# Feature extraction functions (vectorized version - operate on full arrays)
HAR_MODEL_SPECS = {
    "HAR-ABS": {
        "cols": ["rv1_abs", "rv5_abs", "rv22_abs"],
        "target": "target_abs",
    },
    "HAR-SQ": {
        "cols": ["rv1_sq", "rv5_sq", "rv22_sq"],
        "target": "target_sq",
    },
    "HAR-RS": {
        "cols": ["rs_pos_5", "rs_neg_5", "rv22_sq"],
        "target": "target_sq",
    },
    "HAR-VIX": {
        "cols": ["rv1_abs", "rv5_abs", "rv22_abs", "vix"],
        "target": "target_abs",
        "requires_vix": True,
    },
    "HAR-LEVERAGE": {
        "cols": ["rv1_abs", "rv5_abs", "rv22_abs", "leverage"],
        "target": "target_abs",
    },
}


# ============================================================
#  Rolling OOS Evaluation (vectorized)
# ============================================================

def run_har_oos(features_df: pd.DataFrame, model_name: str, model_spec: dict,
                window: int = 500, oos_start: str = "2023-01-01") -> dict | None:
    """Run rolling OOS for a HAR model. Vectorized OLS for speed."""
    cols = model_spec["cols"]
    target_col = model_spec["target"]

    # Check if required columns exist
    for c in cols:
        if c not in features_df.columns:
            return None

    # Find OOS indices
    oos_mask = features_df.index >= oos_start
    oos_indices = features_df.index[oos_mask]

    if len(oos_indices) == 0:
        return None

    forecasts = []
    realized = []

    for date in oos_indices:
        idx = features_df.index.get_loc(date)
        if idx < window:
            continue

        # Training window
        train_slice = features_df.iloc[idx - window:idx]

        # Get X, y columns
        X_all = train_slice[cols].values
        y_all = train_slice[target_col].values

        # Remove NaN rows
        finite_mask = np.isfinite(X_all).all(axis=1) & np.isfinite(y_all)
        X_train = X_all[finite_mask]
        y_train = y_all[finite_mask]

        if len(y_train) < 50:
            continue

        # Fit OLS
        beta = ols_fit(X_train, y_train)

        # Predict using current-day features
        x_new = features_df.iloc[idx][cols].values.astype(float)
        if not np.all(np.isfinite(x_new)):
            continue

        pred = ols_predict(x_new, beta)

        # Actual realized value (next day)
        actual = features_df.iloc[idx][target_col]
        if np.isnan(actual) or actual <= 0:
            continue

        forecasts.append(pred)
        realized.append(actual)

    if len(forecasts) < 50:
        return None

    forecasts = np.array(forecasts)
    realized = np.array(realized)

    ql = qlike_loss(realized, forecasts)
    ql_array = qlike_loss_array(realized, forecasts)

    return {
        "model": model_name,
        "n_obs": len(forecasts),
        "qlike": ql,
        "qlike_array": ql_array,
        "forecasts": forecasts,
        "realized": realized,
    }


# ============================================================
#  Benchmark Models
# ============================================================

def gjr_garch_forecast(returns: np.ndarray, window: int = 2000, refit_every: int = 21) -> np.ndarray:
    """GJR-GARCH(1,1) rolling forecast."""
    from arch import arch_model

    n = len(returns)
    forecasts = np.full(n, np.nan)

    omega, alpha, gamma_p, beta_p = 0.01, 0.05, 0.05, 0.90
    last_var = np.var(returns[:min(window, n)]) * 1e4
    last_ret = returns[min(window, n) - 1] * 100

    start = min(window, n)
    for t in range(start, n):
        if (t - start) % refit_every == 0:
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


def ewma_forecast(returns: np.ndarray, lam: float = 0.94) -> np.ndarray:
    """EWMA(lambda) variance forecast."""
    n = len(returns)
    var = np.full(n, np.nan)
    var[21] = np.var(returns[:22])
    for t in range(22, n):
        var[t] = lam * var[t - 1] + (1 - lam) * returns[t - 1] ** 2
    return var


def run_benchmark_oos(returns: np.ndarray, dates: pd.DatetimeIndex,
                      model_name: str, forecast_fn, oos_start: str = "2023-01-01",
                      **kwargs) -> dict | None:
    """Run OOS for benchmark models (GJR, EWMA)."""
    var_forecasts = forecast_fn(returns, **kwargs)

    realized_var = returns ** 2

    oos_mask = dates >= oos_start
    oos_idx = np.where(oos_mask)[0]

    valid_forecasts = []
    valid_realized = []
    for t in oos_idx:
        if t >= len(var_forecasts) or np.isnan(var_forecasts[t]):
            continue
        if t + 1 >= len(realized_var):
            continue
        rv = realized_var[t + 1]
        if rv <= 0:
            rv = 1e-10
        valid_forecasts.append(var_forecasts[t])
        valid_realized.append(rv)

    if len(valid_forecasts) < 50:
        return None

    forecasts = np.maximum(np.array(valid_forecasts), 1e-10)
    realized = np.array(valid_realized)

    ql = qlike_loss(realized, forecasts)
    ql_array = qlike_loss_array(realized, forecasts)

    return {
        "model": model_name,
        "n_obs": len(forecasts),
        "qlike": ql,
        "qlike_array": ql_array,
        "forecasts": forecasts,
        "realized": realized,
    }


# ============================================================
#  In-Sample Coefficient Analysis
# ============================================================

def insample_coefficients(features_df: pd.DataFrame, model_name: str,
                          cols: list, target_col: str) -> dict | None:
    """Fit full-sample OLS and return coefficient analysis."""
    # Use all available data before OOS
    train = features_df[features_df.index < OOS_START].copy()
    X = train[cols].values
    y = train[target_col].values
    finite = np.isfinite(X).all(axis=1) & np.isfinite(y)
    X = X[finite]
    y = y[finite]

    if len(y) < 100:
        return None

    n, k = X.shape
    X_aug = np.column_stack([np.ones(n), X])
    try:
        beta = np.linalg.lstsq(X_aug, y, rcond=None)[0]
    except np.linalg.LinAlgError:
        return None

    # Compute standard errors
    residuals = y - X_aug @ beta
    s2 = np.sum(residuals ** 2) / (n - k - 1)
    try:
        cov_beta = s2 * np.linalg.inv(X_aug.T @ X_aug)
    except np.linalg.LinAlgError:
        return None

    se = np.sqrt(np.diag(cov_beta))
    t_stats = beta / se
    p_values = 2 * (1 - stats.t.cdf(np.abs(t_stats), df=n - k - 1))

    # R-squared
    ss_res = np.sum(residuals ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    r_sq = 1 - ss_res / ss_tot
    adj_r_sq = 1 - (1 - r_sq) * (n - 1) / (n - k - 1)

    coef_names = ["const"] + cols
    coef_dict = {}
    for i, name in enumerate(coef_names):
        coef_dict[name] = {
            "coef": float(beta[i]),
            "se": float(se[i]),
            "t": float(t_stats[i]),
            "p": float(p_values[i]),
        }

    return {
        "r_squared": float(r_sq),
        "adj_r_squared": float(adj_r_sq),
        "n_obs": int(n),
        "coefficients": coef_dict,
    }


# ============================================================
#  Main
# ============================================================

def main():
    t0 = time.time()
    print_section("K532: HAR Cross-Asset Validation")
    print(f"  Assets: {ASSETS}")
    print(f"  OOS: {OOS_START} to {OOS_END}")
    print(f"  HAR window: {HAR_WINDOW}, GJR window: {GJR_WINDOW}")

    # ----------------------------------------------------------
    # 1. Load data
    # ----------------------------------------------------------
    print_section("1. Data Loading")

    # Load VIX first
    vix_series = load_vix()
    if vix_series is not None:
        print(f"  VIX loaded: {len(vix_series)} obs")
    else:
        print("  WARNING: VIX not available")

    asset_data = {}
    for ticker in ASSETS:
        df = load_asset_data(ticker)
        if df is not None:
            asset_data[ticker] = df

    print(f"\n  Successfully loaded {len(asset_data)}/{len(ASSETS)} assets")

    # ----------------------------------------------------------
    # 2. Descriptive Statistics
    # ----------------------------------------------------------
    print_section("2. Descriptive Statistics")
    desc_stats = {}
    for ticker, df in asset_data.items():
        r = df["log_return"].values
        abs_r = np.abs(r)
        desc = {
            "n_obs": len(r),
            "start": df.index[0].strftime("%Y-%m-%d"),
            "end": df.index[-1].strftime("%Y-%m-%d"),
            "mean_return": float(np.mean(r)),
            "std_return": float(np.std(r)),
            "skewness": float(stats.skew(r)),
            "kurtosis": float(stats.kurtosis(r)),
            "mean_abs_r": float(np.mean(abs_r)),
            "mean_r_sq": float(np.mean(r ** 2)),
            "annualized_vol": float(np.std(r) * np.sqrt(252)),
        }
        desc_stats[ticker] = desc
        print(f"  {ticker:8s}: n={desc['n_obs']}, σ={desc['std_return']:.4f}, "
              f"skew={desc['skewness']:.2f}, kurt={desc['kurtosis']:.1f}, "
              f"ann_vol={desc['annualized_vol']:.1%}")

    # ----------------------------------------------------------
    # 3. Run all models for each asset
    # ----------------------------------------------------------
    print_section("3. Model Evaluation (Rolling OOS)")

    all_results = {}  # asset -> model -> result dict
    all_insample = {}  # asset -> model -> insample coefficients

    for ticker, df in asset_data.items():
        print(f"\n  --- {ticker} ---")
        returns = df["log_return"].values
        dates = df.index

        # Only add VIX for SPY (VIX is US-specific for HAR-VIX model)
        use_vix = (ticker == "SPY") and (vix_series is not None)
        features = build_har_features(df, vix_series if use_vix else None)

        asset_results = {}
        asset_insample = {}

        # HAR models
        for model_name, spec in HAR_MODEL_SPECS.items():
            if spec.get("requires_vix") and not use_vix:
                print(f"    {model_name:16s}: SKIP (no VIX)")
                continue

            print(f"    {model_name:16s}: ", end="", flush=True)
            t1 = time.time()
            result = run_har_oos(features, model_name, spec,
                                 window=HAR_WINDOW, oos_start=OOS_START)
            elapsed = time.time() - t1

            if result is not None:
                asset_results[model_name] = result
                print(f"QLIKE={result['qlike']:.6f}, n={result['n_obs']}, "
                      f"({elapsed:.1f}s)")

                # In-sample coefficient analysis
                is_result = insample_coefficients(features, model_name,
                                                  spec["cols"], spec["target"])
                if is_result:
                    asset_insample[model_name] = is_result
            else:
                print("FAILED")

        # Benchmark: GJR-GARCH
        print(f"    {'GJR-GARCH':16s}: ", end="", flush=True)
        t1 = time.time()
        gjr_result = run_benchmark_oos(returns, dates, "GJR-GARCH",
                                        gjr_garch_forecast,
                                        oos_start=OOS_START,
                                        window=GJR_WINDOW,
                                        refit_every=GJR_REFIT_EVERY)
        elapsed = time.time() - t1
        if gjr_result:
            asset_results["GJR-GARCH"] = gjr_result
            print(f"QLIKE={gjr_result['qlike']:.6f}, n={gjr_result['n_obs']}, "
                  f"({elapsed:.1f}s)")
        else:
            print("FAILED")

        # Benchmark: EWMA
        print(f"    {'EWMA(0.94)':16s}: ", end="", flush=True)
        t1 = time.time()
        ewma_result = run_benchmark_oos(returns, dates, "EWMA(0.94)",
                                         ewma_forecast, oos_start=OOS_START,
                                         lam=EWMA_LAMBDA)
        elapsed = time.time() - t1
        if ewma_result:
            asset_results["EWMA(0.94)"] = ewma_result
            print(f"QLIKE={ewma_result['qlike']:.6f}, n={ewma_result['n_obs']}, "
                  f"({elapsed:.1f}s)")
        else:
            print("FAILED")

        all_results[ticker] = asset_results
        all_insample[ticker] = asset_insample

    # ----------------------------------------------------------
    # 4. Cross-Asset QLIKE Rankings
    # ----------------------------------------------------------
    print_section("4. Cross-Asset QLIKE Rankings")

    # Determine all models tested
    all_models = set()
    for asset_results in all_results.values():
        all_models.update(asset_results.keys())
    all_models = sorted(all_models)

    # Build QLIKE matrix
    qlike_matrix = {}
    rank_matrix = {}

    for ticker in asset_data:
        if ticker not in all_results:
            continue
        asset_results = all_results[ticker]
        qlikes = {}
        for m in all_models:
            if m in asset_results:
                qlikes[m] = asset_results[m]["qlike"]
        qlike_matrix[ticker] = qlikes

        # Rank (1 = best)
        sorted_models = sorted(qlikes.items(), key=lambda x: x[1])
        ranks = {m: i + 1 for i, (m, _) in enumerate(sorted_models)}
        rank_matrix[ticker] = ranks

    # Print QLIKE table
    print(f"\n  {'Model':16s}", end="")
    for ticker in asset_data:
        if ticker in qlike_matrix:
            print(f"  {ticker:>10s}", end="")
    print(f"  {'Avg Rank':>10s}")
    print("  " + "-" * (16 + 12 * (len(qlike_matrix) + 1)))

    avg_ranks = {}
    for m in all_models:
        print(f"  {m:16s}", end="")
        ranks_list = []
        for ticker in asset_data:
            if ticker in qlike_matrix and m in qlike_matrix[ticker]:
                ql = qlike_matrix[ticker][m]
                rank = rank_matrix[ticker][m]
                ranks_list.append(rank)
                # Highlight best
                marker = "*" if rank == 1 else " "
                print(f"  {ql:9.6f}{marker}", end="")
            else:
                print(f"  {'N/A':>10s}", end="")

        avg_rank = np.mean(ranks_list) if ranks_list else float('nan')
        avg_ranks[m] = avg_rank
        print(f"  {avg_rank:10.2f}")

    # ----------------------------------------------------------
    # 5. DM Tests: HAR-ABS vs each benchmark, per asset
    # ----------------------------------------------------------
    print_section("5. Diebold-Mariano Tests (HAR-ABS vs Others)")

    dm_results = {}  # asset -> {model: {dm_stat, p_value}}
    reference_model = "HAR-ABS"

    for ticker in asset_data:
        if ticker not in all_results:
            continue
        asset_results = all_results[ticker]
        if reference_model not in asset_results:
            continue

        ref_loss = asset_results[reference_model]["qlike_array"]
        dm_asset = {}

        for m in all_models:
            if m == reference_model or m not in asset_results:
                continue

            other_loss = asset_results[m]["qlike_array"]
            # Align lengths (take min)
            n_common = min(len(ref_loss), len(other_loss))
            dm_stat, p_val = dm_test(ref_loss[:n_common], other_loss[:n_common])
            dm_asset[m] = {"dm_stat": dm_stat, "p_value": p_val}

        dm_results[ticker] = dm_asset

    # Print DM table
    print(f"\n  DM stat (negative = HAR-ABS better)")
    print(f"\n  {'Model':16s}", end="")
    for ticker in asset_data:
        if ticker in dm_results:
            print(f"  {ticker:>10s}", end="")
    print()
    print("  " + "-" * (16 + 12 * len(dm_results)))

    for m in all_models:
        if m == reference_model:
            continue
        print(f"  {m:16s}", end="")
        for ticker in asset_data:
            if ticker in dm_results and m in dm_results[ticker]:
                dm = dm_results[ticker][m]
                sig = "***" if dm["p_value"] < 0.001 else "**" if dm["p_value"] < 0.01 else "*" if dm["p_value"] < 0.05 else ""
                print(f"  {dm['dm_stat']:7.2f}{sig:>3s}", end="")
            else:
                print(f"  {'N/A':>10s}", end="")
        print()

    # ----------------------------------------------------------
    # 6. Cross-Sectional Rank Correlation (Spearman)
    # ----------------------------------------------------------
    print_section("6. Cross-Sectional Rank Correlation (Spearman)")

    # For each pair of assets, compute Spearman correlation of model rankings
    assets_with_results = [t for t in asset_data if t in rank_matrix]
    n_assets = len(assets_with_results)

    # Build rank vectors (only for models common to both assets)
    rank_corr_matrix = np.full((n_assets, n_assets), np.nan)

    for i, t1 in enumerate(assets_with_results):
        for j, t2 in enumerate(assets_with_results):
            common_models = set(rank_matrix[t1].keys()) & set(rank_matrix[t2].keys())
            if len(common_models) < 3:
                continue
            common = sorted(common_models)
            r1 = [rank_matrix[t1][m] for m in common]
            r2 = [rank_matrix[t2][m] for m in common]
            corr, p = stats.spearmanr(r1, r2)
            rank_corr_matrix[i, j] = corr

    print(f"\n  {'':10s}", end="")
    for t in assets_with_results:
        print(f"  {t:>8s}", end="")
    print()
    for i, t1 in enumerate(assets_with_results):
        print(f"  {t1:10s}", end="")
        for j in range(n_assets):
            if np.isnan(rank_corr_matrix[i, j]):
                print(f"  {'N/A':>8s}", end="")
            else:
                print(f"  {rank_corr_matrix[i, j]:8.3f}", end="")
        print()

    avg_corr = np.nanmean(rank_corr_matrix[np.triu_indices(n_assets, k=1)])
    print(f"\n  Average pairwise rank correlation: {avg_corr:.3f}")

    # ----------------------------------------------------------
    # 7. Coefficient Analysis Across Assets
    # ----------------------------------------------------------
    print_section("7. HAR-ABS Coefficient Analysis Across Assets")

    coef_summary = {}
    for ticker in asset_data:
        if ticker in all_insample and "HAR-ABS" in all_insample[ticker]:
            coefs = all_insample[ticker]["HAR-ABS"]["coefficients"]
            coef_summary[ticker] = {
                "const": coefs["const"]["coef"],
                "rv1_abs": coefs["rv1_abs"]["coef"],
                "rv5_abs": coefs["rv5_abs"]["coef"],
                "rv22_abs": coefs["rv22_abs"]["coef"],
                "rv1_abs_t": coefs["rv1_abs"]["t"],
                "rv5_abs_t": coefs["rv5_abs"]["t"],
                "rv22_abs_t": coefs["rv22_abs"]["t"],
                "r_squared": all_insample[ticker]["HAR-ABS"]["r_squared"],
            }

    if coef_summary:
        print(f"\n  {'Asset':10s} {'β1(rv1)':>10s} {'β5(rv5)':>10s} {'β22(rv22)':>10s} "
              f"{'t(β1)':>8s} {'t(β5)':>8s} {'t(β22)':>8s} {'R²':>8s}")
        print("  " + "-" * 84)

        for ticker, c in coef_summary.items():
            print(f"  {ticker:10s} {c['rv1_abs']:10.4f} {c['rv5_abs']:10.4f} {c['rv22_abs']:10.4f} "
                  f"{c['rv1_abs_t']:8.2f} {c['rv5_abs_t']:8.2f} {c['rv22_abs_t']:8.2f} "
                  f"{c['r_squared']:8.4f}")

        # Check K530 claim: β5 dominates, β1 slightly negative
        n_beta1_neg = sum(1 for c in coef_summary.values() if c["rv1_abs"] < 0)
        n_beta5_largest = sum(1 for c in coef_summary.values()
                              if c["rv5_abs"] > c["rv22_abs"] and c["rv5_abs"] > abs(c["rv1_abs"]))
        print(f"\n  β1 negative in {n_beta1_neg}/{len(coef_summary)} assets "
              f"(K530 claim: β1 slightly negative → mean-reversion)")
        print(f"  β5 dominates in {n_beta5_largest}/{len(coef_summary)} assets "
              f"(K530 claim: weekly component is strongest)")

    # ----------------------------------------------------------
    # 8. Semivariance Analysis (HAR-RS)
    # ----------------------------------------------------------
    print_section("8. Semivariance Analysis (HAR-RS) Across Assets")

    semi_summary = {}
    for ticker in asset_data:
        if ticker in all_insample and "HAR-RS" in all_insample[ticker]:
            coefs = all_insample[ticker]["HAR-RS"]["coefficients"]
            bad_coef = coefs["rs_neg_5"]["coef"]
            good_coef = coefs["rs_pos_5"]["coef"]
            ratio = bad_coef / good_coef if good_coef != 0 else float('inf')
            semi_summary[ticker] = {
                "good_vol": good_coef,
                "bad_vol": bad_coef,
                "bad_good_ratio": ratio,
                "good_t": coefs["rs_pos_5"]["t"],
                "bad_t": coefs["rs_neg_5"]["t"],
            }

    if semi_summary:
        print(f"\n  {'Asset':10s} {'Good(β+)':>10s} {'Bad(β-)':>10s} {'Bad/Good':>10s} "
              f"{'t(Good)':>8s} {'t(Bad)':>8s}")
        print("  " + "-" * 64)

        for ticker, s in semi_summary.items():
            print(f"  {ticker:10s} {s['good_vol']:10.4f} {s['bad_vol']:10.4f} "
                  f"{s['bad_good_ratio']:10.2f} {s['good_t']:8.2f} {s['bad_t']:8.2f}")

        avg_ratio = np.mean([s["bad_good_ratio"] for s in semi_summary.values()
                             if np.isfinite(s["bad_good_ratio"]) and s["good_vol"] != 0])
        print(f"\n  Average bad/good ratio: {avg_ratio:.2f}x "
              f"(K530 claim: 4.8x for SPY)")

    # ----------------------------------------------------------
    # 9. Summary & Conclusions
    # ----------------------------------------------------------
    print_section("9. Summary")

    # Count how many assets HAR-ABS beats GJR-GARCH
    har_beats_gjr = 0
    har_beats_ewma = 0
    total_assets = 0

    for ticker in asset_data:
        if ticker not in all_results:
            continue
        ar = all_results[ticker]
        if "HAR-ABS" not in ar:
            continue
        total_assets += 1

        if "GJR-GARCH" in ar:
            if ar["HAR-ABS"]["qlike"] < ar["GJR-GARCH"]["qlike"]:
                har_beats_gjr += 1
        if "EWMA(0.94)" in ar:
            if ar["HAR-ABS"]["qlike"] < ar["EWMA(0.94)"]["qlike"]:
                har_beats_ewma += 1

    print(f"\n  HAR-ABS beats GJR-GARCH: {har_beats_gjr}/{total_assets} assets")
    print(f"  HAR-ABS beats EWMA(0.94): {har_beats_ewma}/{total_assets} assets")

    # DM significance count
    sig_count_gjr = 0
    sig_count_ewma = 0
    for ticker in dm_results:
        if "GJR-GARCH" in dm_results[ticker]:
            if dm_results[ticker]["GJR-GARCH"]["p_value"] < 0.05 and \
               dm_results[ticker]["GJR-GARCH"]["dm_stat"] < 0:
                sig_count_gjr += 1
        if "EWMA(0.94)" in dm_results[ticker]:
            if dm_results[ticker]["EWMA(0.94)"]["p_value"] < 0.05 and \
               dm_results[ticker]["EWMA(0.94)"]["dm_stat"] < 0:
                sig_count_ewma += 1

    print(f"  HAR-ABS sig. better than GJR (DM p<0.05): {sig_count_gjr}/{total_assets}")
    print(f"  HAR-ABS sig. better than EWMA (DM p<0.05): {sig_count_ewma}/{total_assets}")

    # Best model per asset
    print(f"\n  Best model per asset (by QLIKE):")
    best_models = {}
    for ticker in asset_data:
        if ticker not in qlike_matrix:
            continue
        qlikes = qlike_matrix[ticker]
        best = min(qlikes, key=qlikes.get)
        best_models[ticker] = best
        print(f"    {ticker:10s}: {best:16s} (QLIKE={qlikes[best]:.6f})")

    # HAR-ABS universality
    har_best_count = sum(1 for m in best_models.values() if m.startswith("HAR"))
    print(f"\n  HAR variant is best in {har_best_count}/{len(best_models)} assets")

    elapsed = time.time() - t0
    print(f"\n  Total elapsed: {elapsed:.1f}s")

    # ----------------------------------------------------------
    # 10. Save Results
    # ----------------------------------------------------------
    print_section("10. Saving Results")

    # Prepare serializable results
    results_json = {
        "experiment_id": "K532",
        "title": "HAR Cross-Asset Validation (7 assets)",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "data_source": "yfinance (daily)",
        "references": [
            "Corsi (2009, JFE): Original HAR-RV model",
            "Patton & Sheppard (2015): Semivariance decomposition",
            "Andersen, Bollerslev, Diebold & Labys (2003): Realized volatility",
            "K530: HAR-ABS DM=-15.45 vs GJR (SPY)",
        ],
        "method": {
            "assets": ASSETS,
            "assets_loaded": list(asset_data.keys()),
            "har_models": list(HAR_MODEL_SPECS.keys()),
            "benchmarks": ["GJR-GARCH(1,1)", "EWMA(0.94)"],
            "har_window": HAR_WINDOW,
            "garch_window": GJR_WINDOW,
            "oos_period": f"{OOS_START} to {OOS_END}",
            "evaluation": "QLIKE + DM test (HAR-ABS as reference)",
        },
        "results": {},
    }

    # Per-asset results
    for ticker in asset_data:
        asset_json = {
            "descriptive_stats": desc_stats.get(ticker, {}),
        }

        # QLIKE per model
        if ticker in qlike_matrix:
            asset_json["qlike_by_model"] = qlike_matrix[ticker]
        if ticker in rank_matrix:
            asset_json["rank_by_model"] = rank_matrix[ticker]

        # DM tests
        if ticker in dm_results:
            dm_clean = {}
            for m, d in dm_results[ticker].items():
                dm_clean[m] = {
                    "dm_stat": round(d["dm_stat"], 4),
                    "p_value": round(d["p_value"], 6),
                    "significant_5pct": d["p_value"] < 0.05,
                    "har_abs_better": d["dm_stat"] < 0,
                }
            asset_json["dm_tests_vs_har_abs"] = dm_clean

        # In-sample coefficients
        if ticker in all_insample:
            is_clean = {}
            for m, is_data in all_insample[ticker].items():
                is_clean[m] = {
                    "r_squared": round(is_data["r_squared"], 6),
                    "adj_r_squared": round(is_data["adj_r_squared"], 6),
                    "n_obs": is_data["n_obs"],
                    "coefficients": {
                        k: {kk: round(vv, 8) if isinstance(vv, float) else vv
                             for kk, vv in v.items()}
                        for k, v in is_data["coefficients"].items()
                    },
                }
            asset_json["insample_coefficients"] = is_clean

        results_json["results"][ticker] = asset_json

    # Cross-sectional analysis
    results_json["cross_sectional"] = {
        "avg_rank_by_model": {m: round(r, 4) for m, r in avg_ranks.items()},
        "best_model_per_asset": best_models,
        "har_abs_beats_gjr": f"{har_beats_gjr}/{total_assets}",
        "har_abs_beats_ewma": f"{har_beats_ewma}/{total_assets}",
        "har_abs_sig_better_gjr": f"{sig_count_gjr}/{total_assets}",
        "har_abs_sig_better_ewma": f"{sig_count_ewma}/{total_assets}",
        "spearman_rank_corr_avg": round(float(avg_corr), 4) if not np.isnan(avg_corr) else None,
        "har_variant_best_count": f"{har_best_count}/{len(best_models)}",
    }

    # Coefficient stability
    if coef_summary:
        results_json["coefficient_stability"] = {
            "har_abs_coefficients": {
                t: {k: round(v, 6) for k, v in c.items()}
                for t, c in coef_summary.items()
            },
            "beta1_negative_count": f"{n_beta1_neg}/{len(coef_summary)}",
            "beta5_dominates_count": f"{n_beta5_largest}/{len(coef_summary)}",
        }

    # Semivariance
    if semi_summary:
        results_json["semivariance_analysis"] = {
            t: {k: round(v, 6) for k, v in s.items()}
            for t, s in semi_summary.items()
        }
        results_json["semivariance_analysis"]["avg_bad_good_ratio"] = round(float(avg_ratio), 4) if np.isfinite(avg_ratio) else None

    # K530 validation summary
    results_json["k530_validation"] = {
        "claim_1_abs_beats_sq": "To be evaluated from QLIKE comparison",
        "claim_2_vix_best": "SPY-only, evaluated in results",
        "claim_3_beta5_dominates": f"{n_beta5_largest}/{len(coef_summary)} assets" if coef_summary else "N/A",
        "claim_4_bad_vol_4_8x": f"avg ratio={avg_ratio:.2f}x" if semi_summary and np.isfinite(avg_ratio) else "N/A",
    }

    # Evaluate claim 1: ABS vs SQ
    abs_beats_sq_count = 0
    abs_sq_total = 0
    for ticker in asset_data:
        if ticker not in qlike_matrix:
            continue
        qlikes = qlike_matrix[ticker]
        if "HAR-ABS" in qlikes and "HAR-SQ" in qlikes:
            abs_sq_total += 1
            if qlikes["HAR-ABS"] < qlikes["HAR-SQ"]:
                abs_beats_sq_count += 1
    results_json["k530_validation"]["claim_1_abs_beats_sq"] = f"{abs_beats_sq_count}/{abs_sq_total} assets"

    # Save
    out_path = Path(__file__).parent / "k532_har_cross_asset_results.json"
    with open(out_path, "w") as f:
        json.dump(results_json, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")

    # ----------------------------------------------------------
    # Final verdict
    # ----------------------------------------------------------
    print_section("VERDICT")
    print(f"""
  K530 Claim Validation:
  1. ABS >> SQ:           {results_json['k530_validation']['claim_1_abs_beats_sq']}
  2. HAR-VIX best (SPY):  Check SPY rankings above
  3. β5 dominates:        {results_json['k530_validation']['claim_3_beta5_dominates']}
  4. Bad vol >> Good vol:  {results_json['k530_validation']['claim_4_bad_vol_4_8x']}

  Cross-Asset Universality:
  - HAR-ABS beats GJR:    {har_beats_gjr}/{total_assets} assets
  - HAR variant #1:       {har_best_count}/{len(best_models)} assets
  - Avg rank correlation: {avg_corr:.3f}
  - HAR sig. > GJR (DM):  {sig_count_gjr}/{total_assets} assets
""")


if __name__ == "__main__":
    main()
