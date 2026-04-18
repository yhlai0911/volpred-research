"""K767: HAR-RV with 5-Day Realized Volatility — Avoiding Intraday Data Requirement.

Background:
  - K745: HAR-ABS beats HAR-RV at N=37 using 5-min data (preliminary, small sample)
  - K530: HAR-ABS (daily proxy) crushed GJR-GARCH (DM=-15.45)
  - This experiment uses PROPER multi-day RV from daily squared returns — no intraday data needed
  - Multi-horizon: 5d (weekly), 22d (monthly), 66d (quarterly)

Literature:
  - Corsi (2009, JFE): HAR-RV — multi-scale RV (1d, 5d, 22d)
  - Andersen et al. (2003, Econometrica): Realized volatility theory
  - Patton (2011, JoE): QLIKE loss function — robust to noise in proxy
  - Hansen & Lunde (2005, JBES): GARCH(1,1) hard to beat for daily equity vol
  - Bollerslev, Patton & Quaedvlieg (2016, JoE): Realized GARCH — combined model

Design:
  RV Definitions (all from daily squared log returns):
    RV_5d(t)  = sum(r²_{t-4}..r²_t)       — 5 trading days
    RV_22d(t) = sum(r²_{t-21}..r²_t)       — 22 trading days (monthly)
    RV_66d(t) = sum(r²_{t-65}..r²_t)       — 66 trading days (quarterly)

  HAR-5d Model (Corsi 2009 adapted):
    RV_5d(t+5) = β₀ + β₁×RV_5d(t) + β₂×RV_22d(t) + β₃×RV_66d(t) + ε

  Multi-Horizon Models:
    1. 5-day ahead:  HAR-5d vs GARCH-5step vs EWMA-5d vs VIX/sqrt(52)
    2. 22-day ahead: HAR-22d vs GARCH-22step vs EWMA-22d vs VIX/sqrt(12)
    3. 66-day ahead: HAR-66d vs simple historical 66d

  Cross-Asset: SPY, GLD, 0050.TW
  OOS: expanding window, minimum 504 training days
  Evaluation: QLIKE, MSE, R²_OOS, DM test (Harvey t>3.0 threshold)

Data: yfinance, 2006-2026 (start 2006 to have 66d buffer + training by 2009)

[提出: 用戶, 執行: Claude]

Usage:
    uv run python experiments/k767_har_5day_rv.py
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
from scipy.optimize import minimize

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
    """QLIKE loss: mean(realized/forecast - log(realized/forecast) - 1).
    Lower is better. Both inputs must be positive."""
    mask = (realized > 0) & (forecast > 0)
    r, f = realized[mask], forecast[mask]
    if len(r) == 0:
        return np.nan
    ratio = r / f
    return float(np.mean(ratio - np.log(ratio) - 1))


def qlike_loss_array(realized: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    """Element-wise QLIKE loss."""
    ratio = realized / forecast
    return ratio - np.log(ratio) - 1


def mse_loss(realized: np.ndarray, forecast: np.ndarray) -> float:
    return float(np.mean((realized - forecast) ** 2))


def r_squared_oos(realized: np.ndarray, forecast: np.ndarray) -> float:
    ss_res = np.sum((realized - forecast) ** 2)
    ss_tot = np.sum((realized - np.mean(realized)) ** 2)
    if ss_tot == 0:
        return 0.0
    return float(1 - ss_res / ss_tot)


def dm_test(loss1: np.ndarray, loss2: np.ndarray, h: int = 1) -> tuple:
    """Diebold-Mariano test. loss1 - loss2 < 0 => model 1 is better.
    Returns (DM_stat, p_value). h = forecast horizon for HAC correction."""
    d = loss1 - loss2
    T = len(d)
    if T < 10:
        return (0.0, 1.0)
    d_bar = np.mean(d)
    # Newey-West HAC with h-1 lags
    gamma_0 = np.mean((d - d_bar) ** 2)
    gamma_sum = 0.0
    for k in range(1, h):
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        gamma_sum += 2 * gamma_k
    var_d = (gamma_0 + gamma_sum) / T
    if var_d <= 0:
        return (0.0, 1.0)
    dm_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(dm_stat), df=T - 1))
    return (float(dm_stat), float(p_value))


def mz_regression(realized: np.ndarray, forecast: np.ndarray) -> dict:
    """Mincer-Zarnowitz regression: realized = a + b*forecast + e.
    Perfect forecast: a=0, b=1, R²=1."""
    from numpy.linalg import lstsq
    X = np.column_stack([np.ones(len(forecast)), forecast])
    coef, _, _, _ = lstsq(X, realized, rcond=None)
    pred = X @ coef
    ss_res = np.sum((realized - pred) ** 2)
    ss_tot = np.sum((realized - np.mean(realized)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {"intercept": float(coef[0]), "slope": float(coef[1]), "R2": float(r2)}


# ============================================================
#  Data download
# ============================================================

def download_data(ticker: str, start: str = "2006-01-01", end: str = "2026-04-01") -> pd.DataFrame:
    """Download daily price data from yfinance.
    Filters extreme returns (|r| > 50%) which are likely data artifacts
    (e.g., unadjusted splits in yfinance for 0050.TW 2014-01-02: -138.9%)."""
    import yfinance as yf
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Close"]].dropna()
    df["log_return"] = np.log(df["Close"] / df["Close"].shift(1))
    df = df.dropna()
    # Filter data artifacts: |log_return| > 50% is almost certainly wrong data
    n_before = len(df)
    extreme = df["log_return"].abs() > 0.50
    if extreme.any():
        n_removed = extreme.sum()
        dates_removed = df.index[extreme].strftime("%Y-%m-%d").tolist()
        print(f"  WARNING: Removed {n_removed} extreme return(s) for {ticker}: {dates_removed}")
        df = df[~extreme]
    return df


def download_vix(start: str = "2006-01-01", end: str = "2026-04-01") -> pd.Series:
    """Download VIX index."""
    import yfinance as yf
    df = yf.download("^VIX", start=start, end=end, progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df["Close"].dropna()


# ============================================================
#  Realized Volatility construction (from daily returns)
# ============================================================

def construct_rv_series(log_returns: pd.Series) -> pd.DataFrame:
    """Construct multi-scale RV from daily squared log returns.

    RV_Nd(t) = sum(r²_{t-N+1} ... r²_t)

    Returns DataFrame with RV_1d, RV_5d, RV_22d, RV_66d columns.
    """
    r2 = log_returns ** 2  # daily squared returns

    rv = pd.DataFrame(index=log_returns.index)
    rv["r2"] = r2
    rv["RV_1d"] = r2  # 1-day RV = daily squared return
    rv["RV_5d"] = r2.rolling(5, min_periods=5).sum()
    rv["RV_22d"] = r2.rolling(22, min_periods=22).sum()
    rv["RV_66d"] = r2.rolling(66, min_periods=66).sum()

    return rv.dropna()


def construct_forward_rv(log_returns: pd.Series, horizon: int) -> pd.Series:
    """Forward-looking RV_Nd(t+N) = sum(r²_{t+1} ... r²_{t+N}).
    This is the TARGET we predict — no overlap with features at time t."""
    r2 = log_returns ** 2
    # Sum of next N days' squared returns
    fwd = r2.rolling(horizon, min_periods=horizon).sum().shift(-horizon)
    return fwd


# ============================================================
#  HAR-RV Model (OLS, expanding window)
# ============================================================

def har_forecast_expanding(
    rv_df: pd.DataFrame,
    target: pd.Series,
    features: list[str],
    min_train: int = 504,
    use_log: bool = False,
) -> pd.Series:
    """Expanding-window HAR-RV OLS forecast.

    Args:
        rv_df: DataFrame with feature columns (RV_5d, RV_22d, RV_66d, etc.)
        target: Forward RV to predict (aligned index)
        features: List of column names to use as regressors
        min_train: Minimum training window
        use_log: If True, use log-HAR specification (more robust):
                 log(RV_target) = β₀ + β₁×log(RV_5d) + ... + ε
                 Then exponentiate with bias correction.

    Returns:
        Series of OOS forecasts
    """
    # Align data
    common_idx = rv_df.index.intersection(target.dropna().index)
    X_all = rv_df.loc[common_idx, features].values
    y_all = target.loc[common_idx].values
    dates = common_idx

    n = len(common_idx)
    if n <= min_train:
        return pd.Series(dtype=float)

    # For log-HAR, transform both features and target
    if use_log:
        X_all = np.log(np.maximum(X_all, 1e-12))
        y_all_log = np.log(np.maximum(y_all, 1e-12))
    else:
        y_all_log = y_all  # unused but same variable name for clarity

    forecasts = {}
    for t in range(min_train, n):
        if use_log:
            X_train = np.column_stack([np.ones(t), X_all[:t]])
            y_train = y_all_log[:t]
        else:
            X_train = np.column_stack([np.ones(t), X_all[:t]])
            y_train = y_all[:t]

        # Check for valid data
        valid = np.isfinite(X_train).all(axis=1) & np.isfinite(y_train)
        X_tr = X_train[valid]
        y_tr = y_train[valid]

        if len(y_tr) < 50:
            continue

        try:
            coef, _, _, _ = np.linalg.lstsq(X_tr, y_tr, rcond=None)
            x_new = np.concatenate([[1.0], X_all[t]])
            pred = float(x_new @ coef)

            if use_log:
                # Bias correction: E[exp(log_pred + sigma²/2)]
                resid = y_tr - X_tr @ coef
                sigma2_resid = np.var(resid)
                pred = np.exp(pred + sigma2_resid / 2)
            else:
                # Floor at 10% of training mean to avoid QLIKE explosion
                train_mean = np.mean(y_all[:t][y_all[:t] > 0])
                pred = max(pred, 0.1 * train_mean)

            forecasts[dates[t]] = float(pred)
        except Exception:
            continue

    return pd.Series(forecasts)


# ============================================================
#  GARCH multi-step forecast (using arch library for speed)
# ============================================================

def garch_multi_step_forecast(
    log_returns: pd.Series,
    horizon: int,
    min_train: int = 504,
    refit_every: int = 22,
) -> pd.Series:
    """GJR-GARCH(1,1) multi-step ahead variance forecast (expanding window).

    Uses arch library for fast estimation. Refits every `refit_every` days
    to keep runtime manageable. Between refits, uses last fitted params
    with updated sigma² recursion.

    For h-step ahead: sum sigma²_{t+1|t} ... sigma²_{t+h|t}
    """
    from arch import arch_model

    returns_pct = log_returns * 100  # arch uses percentage returns
    dates = log_returns.index
    n = len(returns_pct)

    forecasts = {}
    last_params = None
    last_fit_t = 0

    for t in range(min_train, n - horizon):
        # Refit model periodically
        if last_params is None or (t - last_fit_t) >= refit_every:
            try:
                am = arch_model(returns_pct.iloc[:t], vol="GARCH", p=1, o=1, q=1,
                               mean="Zero", dist="normal")
                res = am.fit(disp="off", show_warning=False)
                omega = res.params.get("omega", None)
                alpha = res.params.get("alpha[1]", None)
                gamma = res.params.get("gamma[1]", 0.0)
                beta = res.params.get("beta[1]", None)
                if any(v is None for v in [omega, alpha, beta]):
                    continue
                last_params = (omega, alpha, gamma, beta)
                last_fit_t = t
            except Exception:
                if last_params is None:
                    continue

        omega, alpha, gamma, beta = last_params

        # Compute sigma² up to time t using current params (in pct² scale)
        r_vals = returns_pct.iloc[:t].values
        T = len(r_vals)
        sigma2 = np.empty(T)
        sigma2[0] = np.var(r_vals)
        for i in range(1, T):
            ind = 1.0 if r_vals[i-1] < 0 else 0.0
            sigma2[i] = omega + alpha * r_vals[i-1]**2 + gamma * r_vals[i-1]**2 * ind + beta * sigma2[i-1]
            sigma2[i] = max(sigma2[i], 1e-8)

        last_sigma2 = sigma2[-1]

        # Multi-step forecast (pct² scale)
        persistence = alpha + gamma / 2 + beta
        if persistence >= 1:
            persistence = 0.999
        long_run_var = omega / (1 - persistence) if (1 - persistence) > 0 else np.var(r_vals)

        ind_last = 1.0 if r_vals[-1] < 0 else 0.0
        sigma2_1 = omega + alpha * r_vals[-1]**2 + gamma * r_vals[-1]**2 * ind_last + beta * last_sigma2

        total_var_pct = 0.0
        for k in range(1, horizon + 1):
            if k == 1:
                s2k = sigma2_1
            else:
                s2k = long_run_var + persistence**(k-1) * (sigma2_1 - long_run_var)
            total_var_pct += s2k

        # Convert from pct² back to decimal²
        total_var = total_var_pct / (100**2)
        forecasts[dates[t]] = max(total_var, 1e-10)

    return pd.Series(forecasts)


# ============================================================
#  EWMA multi-day forecast
# ============================================================

def ewma_forecast(
    log_returns: pd.Series,
    horizon: int,
    lam: float = 0.94,
    min_train: int = 504,
) -> pd.Series:
    """EWMA (RiskMetrics) h-step forecast.
    EWMA sigma² uses lambda=0.94.
    h-step ahead sum = h * EWMA_sigma²(t) (flat forecast).
    Vectorized: compute full EWMA path once, then slice."""
    returns = log_returns.values
    dates = log_returns.index
    n = len(returns)

    # Compute full EWMA path
    sigma2_path = np.empty(n)
    sigma2_path[0] = returns[0] ** 2
    for i in range(1, n):
        sigma2_path[i] = lam * sigma2_path[i-1] + (1 - lam) * returns[i] ** 2

    forecasts = {}
    for t in range(min_train, n - horizon):
        forecasts[dates[t]] = max(horizon * sigma2_path[t-1], 1e-10)

    return pd.Series(forecasts)


# ============================================================
#  VIX-based forecast
# ============================================================

def vix_forecast(
    vix: pd.Series,
    dates: pd.Index,
    horizon: int,
    min_train: int = 504,
) -> pd.Series:
    """VIX-implied variance for h-day horizon.
    VIX = annualized vol in % => daily var = (VIX/100)²/252
    h-day var = h * daily_var = h * (VIX/100)² / 252
    """
    forecasts = {}
    for dt in dates:
        if dt in vix.index:
            v = vix.loc[dt]
            daily_var = (v / 100) ** 2 / 252
            forecasts[dt] = max(horizon * daily_var, 1e-10)
    return pd.Series(forecasts)


# ============================================================
#  Historical Volatility baseline
# ============================================================

def hist_vol_forecast(
    log_returns: pd.Series,
    horizon: int,
    window: int = 252,
    min_train: int = 504,
) -> pd.Series:
    """Simple historical variance: use trailing `window` days average r² * horizon."""
    r2 = log_returns ** 2
    avg_r2 = r2.rolling(window, min_periods=window).mean()
    dates = log_returns.index
    n = len(dates)

    forecasts = {}
    for t in range(min_train, n - horizon):
        dt = dates[t]
        if dt in avg_r2.index and np.isfinite(avg_r2.loc[dt]):
            forecasts[dt] = max(horizon * avg_r2.loc[dt], 1e-10)
    return pd.Series(forecasts)


# ============================================================
#  Run experiment for one asset
# ============================================================

def run_asset_experiment(
    ticker: str,
    log_returns: pd.Series,
    vix: pd.Series | None = None,
    min_train: int = 504,
) -> dict:
    """Run full HAR multi-horizon experiment for one asset."""
    print_section(f"Asset: {ticker}")

    # === Part A: Construct RV series ===
    print("\n[A] Constructing multi-scale RV from daily squared returns...")
    rv_df = construct_rv_series(log_returns)
    print(f"  RV data: {rv_df.index[0].strftime('%Y-%m-%d')} to {rv_df.index[-1].strftime('%Y-%m-%d')}")
    print(f"  N = {len(rv_df)} days with all RV scales available")

    # Descriptive stats
    for col in ["RV_5d", "RV_22d", "RV_66d"]:
        vals = rv_df[col]
        ann_vol = np.sqrt(vals.mean() * 252 / int(col.split("_")[1].replace("d", ""))) * 100
        print(f"  {col}: mean={vals.mean():.6f}, std={vals.std():.6f}, "
              f"ann.vol≈{ann_vol:.1f}%, AC(1)={vals.autocorr(1):.3f}")

    # === Part B & C: Multi-horizon forecasting ===
    horizons = {
        "5d": {"h": 5, "features": ["RV_5d", "RV_22d", "RV_66d"]},
        "22d": {"h": 22, "features": ["RV_5d", "RV_22d", "RV_66d"]},
        "66d": {"h": 66, "features": ["RV_5d", "RV_22d", "RV_66d"]},
    }

    asset_results = {
        "ticker": ticker,
        "n_total": len(rv_df),
        "data_start": rv_df.index[0].strftime("%Y-%m-%d"),
        "data_end": rv_df.index[-1].strftime("%Y-%m-%d"),
        "descriptive_stats": {},
        "horizons": {},
    }

    for col in ["RV_5d", "RV_22d", "RV_66d"]:
        vals = rv_df[col]
        asset_results["descriptive_stats"][col] = {
            "mean": float(vals.mean()),
            "std": float(vals.std()),
            "skew": float(vals.skew()),
            "kurtosis": float(vals.kurtosis()),
            "AC1": float(vals.autocorr(1)),
            "AC5": float(vals.autocorr(5)),
        }

    for hz_name, hz_cfg in horizons.items():
        h = hz_cfg["h"]
        features = hz_cfg["features"]

        print_section(f"Horizon: {hz_name} ({h} trading days ahead)", char="-")

        # Construct forward RV target
        fwd_rv = construct_forward_rv(log_returns, h)

        # Align with features
        common_idx = rv_df.index.intersection(fwd_rv.dropna().index)
        fwd_rv_aligned = fwd_rv.loc[common_idx]
        rv_aligned = rv_df.loc[common_idx]

        print(f"  Forward RV_{hz_name}: {len(fwd_rv_aligned)} observations")
        print(f"  Mean forward RV: {fwd_rv_aligned.mean():.6f}")

        # ---- Model 1: HAR-RV (full: 5d + 22d + 66d) ----
        print("  Fitting HAR-RV (full)...")
        har_full = har_forecast_expanding(rv_aligned, fwd_rv_aligned, features, min_train)

        # ---- Model 2: HAR-RV (short: 5d only) ----
        print("  Fitting HAR-RV (5d only)...")
        har_short = har_forecast_expanding(rv_aligned, fwd_rv_aligned, ["RV_5d"], min_train)

        # ---- Model 3: HAR-RV (5d + 22d) ----
        print("  Fitting HAR-RV (5d + 22d)...")
        har_mid = har_forecast_expanding(rv_aligned, fwd_rv_aligned, ["RV_5d", "RV_22d"], min_train)

        # ---- Model 4: log-HAR (full) — Corsi (2009) log specification ----
        print("  Fitting log-HAR (full)...")
        log_har_full = har_forecast_expanding(rv_aligned, fwd_rv_aligned, features, min_train, use_log=True)

        # ---- Model 5: GARCH multi-step ----
        print("  Fitting GJR-GARCH multi-step...")
        garch_fc = garch_multi_step_forecast(log_returns, h, min_train)

        # ---- Model 6: EWMA ----
        print("  Fitting EWMA...")
        ewma_fc = ewma_forecast(log_returns, h, lam=0.94, min_train=min_train)

        # ---- Model 7: Historical Vol ----
        print("  Fitting Historical Vol...")
        hist_fc = hist_vol_forecast(log_returns, h, window=252, min_train=min_train)

        # ---- Model 8: VIX-based (only for SPY) ----
        vix_fc = None
        if vix is not None and ticker == "SPY":
            print("  Computing VIX-implied forecast...")
            vix_fc = vix_forecast(vix, rv_aligned.index, h, min_train)

        # === Evaluation ===
        # Find common dates across all models
        all_models = {
            "HAR-full": har_full,
            "HAR-5d": har_short,
            "HAR-5d+22d": har_mid,
            "log-HAR": log_har_full,
            "GJR-GARCH": garch_fc,
            "EWMA": ewma_fc,
            "HistVol": hist_fc,
        }
        if vix_fc is not None:
            all_models["VIX-implied"] = vix_fc

        # Get common dates
        common_eval = fwd_rv_aligned.dropna().index
        for name, fc in all_models.items():
            if len(fc) > 0:
                common_eval = common_eval.intersection(fc.index)

        n_oos = len(common_eval)
        print(f"\n  Common OOS observations: {n_oos}")

        if n_oos < 50:
            print(f"  WARNING: Too few OOS obs ({n_oos}), skipping horizon {hz_name}")
            asset_results["horizons"][hz_name] = {"n_oos": n_oos, "status": "insufficient_data"}
            continue

        realized = fwd_rv_aligned.loc[common_eval].values

        hz_results = {
            "horizon_days": h,
            "n_oos": n_oos,
            "oos_start": common_eval[0].strftime("%Y-%m-%d"),
            "oos_end": common_eval[-1].strftime("%Y-%m-%d"),
            "models": {},
            "dm_tests": {},
        }

        print(f"  OOS period: {common_eval[0].strftime('%Y-%m-%d')} to {common_eval[-1].strftime('%Y-%m-%d')}")
        print(f"\n  {'Model':<16} {'QLIKE':>10} {'MSE':>14} {'R²_OOS':>8} {'Corr':>8} {'MZ_R²':>8} {'MZ_b':>8}")
        print(f"  {'-'*74}")

        best_qlike = np.inf
        best_model = ""
        model_losses = {}

        for name, fc in all_models.items():
            if len(fc) == 0:
                continue
            pred = fc.loc[common_eval].values

            q = qlike_loss(realized, pred)
            m = mse_loss(realized, pred)
            r2 = r_squared_oos(realized, pred)
            corr = float(np.corrcoef(realized, pred)[0, 1])
            mz = mz_regression(realized, pred)

            hz_results["models"][name] = {
                "QLIKE": round(q, 6),
                "MSE": float(f"{m:.6e}"),
                "R2_OOS": round(r2, 4),
                "Corr": round(corr, 4),
                "MZ_R2": round(mz["R2"], 4),
                "MZ_slope": round(mz["slope"], 4),
                "MZ_intercept": float(f"{mz['intercept']:.6e}"),
            }

            print(f"  {name:<16} {q:10.6f} {m:14.6e} {r2:8.4f} {corr:8.4f} {mz['R2']:8.4f} {mz['slope']:8.4f}")

            model_losses[name] = qlike_loss_array(realized, pred)

            if q < best_qlike:
                best_qlike = q
                best_model = name

        hz_results["best_model"] = best_model
        hz_results["best_QLIKE"] = round(best_qlike, 6)

        # DM tests: best model vs each other
        print(f"\n  Best model: {best_model} (QLIKE={best_qlike:.6f})")
        print(f"\n  DM Tests (best={best_model} vs others, h={h}):")
        print(f"  {'Comparison':<35} {'DM':>8} {'p-value':>10} {'Sig':>5}")
        print(f"  {'-'*60}")

        for name in all_models:
            if name == best_model or name not in model_losses:
                continue
            dm_stat, p_val = dm_test(model_losses[best_model], model_losses[name], h=h)
            sig = "***" if abs(dm_stat) > 3.0 else ("**" if abs(dm_stat) > 2.58 else ("*" if abs(dm_stat) > 1.96 else ""))
            print(f"  {best_model} vs {name:<20} {dm_stat:8.3f} {p_val:10.4f} {sig:>5}")

            hz_results["dm_tests"][f"{best_model}_vs_{name}"] = {
                "DM_stat": round(dm_stat, 4),
                "p_value": round(p_val, 4),
                "significant_harvey": abs(dm_stat) > 3.0,
            }

        # Sub-period stability (split OOS in half)
        mid = n_oos // 2
        for period_name, start_idx, end_idx in [("first_half", 0, mid), ("second_half", mid, n_oos)]:
            sub_realized = realized[start_idx:end_idx]
            sub_results = {}
            for name, fc in all_models.items():
                if len(fc) == 0:
                    continue
                sub_pred = fc.loc[common_eval[start_idx:end_idx]].values
                sub_results[name] = round(qlike_loss(sub_realized, sub_pred), 6)
            hz_results[f"sub_{period_name}_QLIKE"] = sub_results

        asset_results["horizons"][hz_name] = hz_results

    return asset_results


# ============================================================
#  Main
# ============================================================

def main():
    t0 = time.time()
    print_section("K767: HAR-RV with 5-Day Realized Volatility")
    print("  Multi-horizon vol prediction using daily-frequency data only")
    print("  No intraday data required — accessible to all investors")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # === Download data ===
    print_section("Data Download")

    assets = {
        "SPY": "SPY",
        "GLD": "GLD",
        "0050.TW": "0050.TW",
    }

    vix = download_vix()
    print(f"  VIX: {vix.index[0].strftime('%Y-%m-%d')} to {vix.index[-1].strftime('%Y-%m-%d')}, N={len(vix)}")

    asset_data = {}
    for name, ticker in assets.items():
        df = download_data(ticker)
        print(f"  {name}: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, N={len(df)}")
        asset_data[name] = df

    # === Run experiments ===
    all_results = {
        "experiment_id": "K767",
        "title": "HAR-RV with 5-Day Realized Volatility — Avoiding Intraday Data",
        "timestamp": datetime.now().isoformat(),
        "data_source": "yfinance (daily)",
        "methodology": {
            "rv_construction": "RV_Nd = sum(r²_{t-N+1}...r²_t) from daily log returns",
            "har_model": "RV_h(t+h) = β₀ + β₁×RV_5d(t) + β₂×RV_22d(t) + β₃×RV_66d(t)",
            "estimation": "OLS, expanding window, min 504 training days",
            "evaluation": "QLIKE (primary), MSE, R²_OOS, MZ regression",
            "horizons": "5d (weekly), 22d (monthly), 66d (quarterly)",
            "dm_test": "HAC-corrected with h-1 lags, Harvey (2016) t>3.0 threshold",
        },
        "literature": [
            "Corsi (2009, JFE) — HAR-RV model",
            "Andersen et al. (2003, Econometrica) — Realized volatility theory",
            "Patton (2011, JoE) — QLIKE loss function",
            "Hansen & Lunde (2005, JBES) — GARCH(1,1) benchmark",
            "Harvey (2016) — t>3.0 threshold for multiple testing",
        ],
        "assets": {},
    }

    for name, df in asset_data.items():
        vix_for_asset = vix if name == "SPY" else None
        result = run_asset_experiment(name, df["log_return"], vix_for_asset, min_train=504)
        all_results["assets"][name] = result

    # === Cross-asset summary ===
    print_section("Cross-Asset Summary")
    print(f"\n  {'Asset':<10} {'Horizon':<8} {'Best Model':<16} {'QLIKE':>10} {'R²_OOS':>8} {'Corr':>8}")
    print(f"  {'-'*62}")

    summary_table = []
    for asset_name, asset_res in all_results["assets"].items():
        for hz_name, hz_res in asset_res["horizons"].items():
            if "best_model" not in hz_res:
                continue
            best = hz_res["best_model"]
            metrics = hz_res["models"].get(best, {})
            row = {
                "asset": asset_name,
                "horizon": hz_name,
                "best_model": best,
                "QLIKE": metrics.get("QLIKE", np.nan),
                "R2_OOS": metrics.get("R2_OOS", np.nan),
                "Corr": metrics.get("Corr", np.nan),
            }
            summary_table.append(row)
            print(f"  {asset_name:<10} {hz_name:<8} {best:<16} {row['QLIKE']:10.6f} {row['R2_OOS']:8.4f} {row['Corr']:8.4f}")

    all_results["cross_asset_summary"] = summary_table

    # === Key findings ===
    print_section("Key Findings")

    findings = []

    # Check if HAR beats GARCH consistently
    har_wins = 0
    total_comparisons = 0
    for asset_name, asset_res in all_results["assets"].items():
        for hz_name, hz_res in asset_res["horizons"].items():
            if "models" not in hz_res:
                continue
            models = hz_res["models"]
            if "HAR-full" in models and "GJR-GARCH" in models:
                total_comparisons += 1
                if models["HAR-full"]["QLIKE"] < models["GJR-GARCH"]["QLIKE"]:
                    har_wins += 1

    if total_comparisons > 0:
        pct = har_wins / total_comparisons * 100
        f1 = f"HAR-full beats GJR-GARCH in {har_wins}/{total_comparisons} ({pct:.0f}%) asset-horizon combinations (QLIKE)"
        findings.append(f1)
        print(f"  1. {f1}")

    # Check horizon effect
    for asset_name, asset_res in all_results["assets"].items():
        for hz_name, hz_res in asset_res["horizons"].items():
            if "models" not in hz_res:
                continue
            models = hz_res["models"]
            if "HAR-full" in models:
                f = f"{asset_name} {hz_name}: HAR R²_OOS={models['HAR-full']['R2_OOS']:.3f}, Corr={models['HAR-full']['Corr']:.3f}"
                findings.append(f)
                print(f"  - {f}")

    # Check significance
    sig_count = 0
    total_dm = 0
    for asset_name, asset_res in all_results["assets"].items():
        for hz_name, hz_res in asset_res["horizons"].items():
            if "dm_tests" not in hz_res:
                continue
            for test_name, test_res in hz_res["dm_tests"].items():
                total_dm += 1
                if test_res.get("significant_harvey", False):
                    sig_count += 1

    f_sig = f"{sig_count}/{total_dm} DM tests significant at Harvey t>3.0"
    findings.append(f_sig)
    print(f"  2. {f_sig}")

    all_results["findings"] = findings

    elapsed = time.time() - t0
    all_results["runtime_seconds"] = round(elapsed, 1)
    print(f"\n  Total runtime: {elapsed:.1f} seconds")

    # === Save results ===
    out_path = project_root / "experiments" / "k767_har_5day_rv_results.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n  Results saved to: {out_path}")

    return all_results


if __name__ == "__main__":
    results = main()
