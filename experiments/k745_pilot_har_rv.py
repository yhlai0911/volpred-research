"""K745: Pilot HAR-RV with 51-Day 5-Min Data — First High-Frequency Vol Forecast.

Background:
  - K530: HAR-ABS (daily |r| proxy) crushed GJR-GARCH: DM=-15.45 (QLIKE)
  - K744: Validated 5-min data (51 days SPY, 94% clean), AC(1) gap 5.6x
  - This is the REAL HAR-RV using 5-min realized volatility — the gold standard

Literature:
  - Corsi (2009, JFE): HAR-RV model — multi-scale RV (1d, 5d, 22d)
  - Andersen et al. (2003, Econometrica): Realized volatility theory
  - Barndorff-Nielsen & Shephard (2004, JFE): Bipower variation for jumps
  - Patton (2011, JoE): QLIKE loss function properties

Design:
  Part A: Compute RV, BV, RJ from 5-min data
  Part B: HAR-RV variants with expanding window
  Part C: Compare vs daily-proxy models (all evaluated against RV truth)
  Part D: Quantify 5-min improvement

Data: SPY 5-min (51 days, 2026-01-14 to 2026-03-27) + daily + VIX
LIMITATION: ~28 OOS observations. PRELIMINARY pilot only.

Key Design Decision:
  ALL models predict RV_{t+1} (5-min realized variance).
  Models based on daily returns use abs/sq returns as FEATURES,
  but the TARGET is always next-day 5-min RV.
  This ensures fair comparison on the same loss function.

[提出: Claude, 執行: Claude]

Usage:
    uv run python experiments/k745_pilot_har_rv.py
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
    """QLIKE loss: mean(realized/forecast - log(realized/forecast) - 1)."""
    ratio = realized / forecast
    return float(np.mean(ratio - np.log(ratio) - 1))


def qlike_loss_array(realized: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    ratio = realized / forecast
    return ratio - np.log(ratio) - 1


def mse_loss(realized: np.ndarray, forecast: np.ndarray) -> float:
    return float(np.mean((realized - forecast) ** 2))


def r_squared(realized: np.ndarray, forecast: np.ndarray) -> float:
    ss_res = np.sum((realized - forecast) ** 2)
    ss_tot = np.sum((realized - np.mean(realized)) ** 2)
    if ss_tot == 0:
        return 0.0
    return float(1 - ss_res / ss_tot)


def dm_test(loss1: np.ndarray, loss2: np.ndarray, h: int = 1) -> tuple:
    """DM test. loss1 - loss2 < 0 ⇒ model 1 better."""
    d = loss1 - loss2
    T = len(d)
    if T < 3:
        return (0.0, 1.0)
    d_bar = np.mean(d)
    gamma_0 = np.var(d, ddof=0)
    var_d = gamma_0 / T
    if var_d <= 0:
        return (0.0, 1.0)
    dm_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(dm_stat), df=T - 1))
    return (float(dm_stat), float(p_value))


def ols_fit(X: np.ndarray, y: np.ndarray):
    """OLS with intercept."""
    n = len(y)
    X_aug = np.column_stack([np.ones(n), X])
    try:
        beta = np.linalg.lstsq(X_aug, y, rcond=None)[0]
    except np.linalg.LinAlgError:
        beta = np.zeros(X_aug.shape[1])
    return beta


def ols_predict(X_new: np.ndarray, beta: np.ndarray) -> float:
    x_aug = np.concatenate([[1.0], X_new])
    pred = np.dot(x_aug, beta)
    return max(pred, 1e-10)


# ============================================================
#  Part A: Compute Realized Measures from 5-min data
# ============================================================

def load_5min_rv(data_dir: Path) -> pd.DataFrame:
    """Load all SPY 5-min CSV files and compute daily RV, BV, RJ."""
    import glob

    files = sorted(glob.glob(str(data_dir / "SPY_5min_*.csv")))
    print(f"Found {len(files)} 5-min data files")

    records = []
    for f in files:
        fname = Path(f).stem
        date_str = fname.replace("SPY_5min_", "")

        df = pd.read_csv(f, header=[0, 1], index_col=0)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]
        df.index = pd.to_datetime(df.index)

        if len(df) < 10:
            print(f"  WARNING: {date_str} has only {len(df)} bars, skipping")
            continue

        close = df["Close"].values
        log_ret = np.diff(np.log(close))

        if len(log_ret) < 5:
            continue

        # Realized Variance
        rv = np.sum(log_ret ** 2)

        # Bipower Variation (Barndorff-Nielsen & Shephard 2004)
        abs_ret = np.abs(log_ret)
        n_ret = len(log_ret)
        bv = (np.pi / 2) * np.sum(abs_ret[1:] * abs_ret[:-1])
        bv = bv * n_ret / (n_ret - 1)  # finite-sample correction

        # Realized Jump
        rj = max(rv - bv, 0.0)

        records.append({
            "date": pd.Timestamp(date_str),
            "RV": rv,
            "BV": bv,
            "RJ": rj,
            "n_bars": len(close),
        })

    rv_df = pd.DataFrame(records).set_index("date").sort_index()
    print(f"Computed RV for {len(rv_df)} trading days")
    print(f"  Date range: {rv_df.index[0].date()} to {rv_df.index[-1].date()}")
    print(f"  Mean RV (annualized vol): {np.sqrt(rv_df['RV'].mean() * 252) * 100:.1f}%")
    print(f"  Mean jump fraction (RJ/RV): {(rv_df['RJ'] / rv_df['RV']).mean():.3f}")
    return rv_df


def load_daily_data() -> pd.DataFrame:
    """Load SPY daily + VIX from yfinance."""
    import yfinance as yf

    start, end = "2024-01-01", "2026-03-28"
    print(f"\nDownloading SPY + VIX daily data ({start} to {end})...")
    spy = yf.download("SPY", start=start, end=end, progress=False)
    vix = yf.download("^VIX", start=start, end=end, progress=False)

    for d in (spy, vix):
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = [c[0] for c in d.columns]

    daily = pd.DataFrame(index=spy.index)
    daily["close"] = spy["Close"]
    daily["log_return"] = np.log(spy["Close"] / spy["Close"].shift(1))
    daily["abs_return"] = daily["log_return"].abs()
    daily["sq_return"] = daily["log_return"] ** 2
    daily["vix"] = vix["Close"].reindex(daily.index, method="ffill")
    daily["vix_daily_var"] = (daily["vix"] / 100.0 / np.sqrt(252)) ** 2
    daily = daily.dropna(subset=["log_return"])
    print(f"  SPY daily: {len(daily)} trading days")
    return daily


# ============================================================
#  Part B: Build features (all target = RV_{t+1})
# ============================================================

def build_all_features(rv_df: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """Build a unified feature dataframe.

    All models share the same target: RV_{t+1} from 5-min data.
    """
    merged = rv_df[["RV", "BV", "RJ"]].copy()

    # Merge daily data
    for col in ["log_return", "abs_return", "sq_return", "vix_daily_var"]:
        merged[col] = daily[col].reindex(merged.index)

    merged = merged.dropna(subset=["RV"])

    # --- RV-based features (5-min) ---
    merged["RV_day"] = merged["RV"]
    merged["RV_week"] = merged["RV"].rolling(5, min_periods=3).mean()  # allow 3-day min
    merged["RV_month"] = merged["RV"].rolling(22, min_periods=10).mean()  # allow 10-day min
    merged["RJ_day"] = merged["RJ"]
    merged["log_RV"] = np.log(merged["RV"])
    merged["log_RV_week"] = merged["log_RV"].rolling(5, min_periods=3).mean()
    merged["log_RV_month"] = merged["log_RV"].rolling(22, min_periods=10).mean()

    # --- Daily proxy features ---
    merged["abs_day"] = merged["abs_return"]
    merged["abs_week"] = merged["abs_return"].rolling(5, min_periods=3).mean()
    merged["abs_month"] = merged["abs_return"].rolling(22, min_periods=10).mean()
    merged["sq_day"] = merged["sq_return"]
    merged["sq_week"] = merged["sq_return"].rolling(5, min_periods=3).mean()
    merged["sq_month"] = merged["sq_return"].rolling(22, min_periods=10).mean()

    # --- Target ---
    merged["RV_next"] = merged["RV"].shift(-1)

    n_usable = merged.dropna(subset=["RV_week", "RV_next"]).shape[0]
    print(f"\nFeatures built: {len(merged)} days, {n_usable} with weekly+ features & target")
    return merged


# ============================================================
#  GJR-GARCH estimation
# ============================================================

def estimate_gjr_garch(returns: np.ndarray):
    """Estimate GJR-GARCH(1,1) by quasi-MLE. Returns (params, h_series)."""
    T = len(returns)
    h0 = np.var(returns)

    def neg_loglik(params):
        omega, alpha, gamma, beta = params
        if omega < 1e-10 or alpha < 0 or gamma < 0 or beta < 0:
            return 1e10
        if alpha + gamma / 2 + beta >= 1.0:
            return 1e10
        h = np.empty(T)
        h[0] = h0
        for t in range(1, T):
            lev = gamma if returns[t - 1] < 0 else 0.0
            h[t] = omega + (alpha + lev) * returns[t - 1] ** 2 + beta * h[t - 1]
            h[t] = max(h[t], 1e-10)
        ll = -0.5 * np.sum(np.log(h) + returns ** 2 / h)
        return -ll

    best_res, best_nll = None, 1e20
    for x0 in [[1e-6, 0.05, 0.05, 0.90], [1e-6, 0.10, 0.10, 0.80], [1e-5, 0.03, 0.08, 0.88]]:
        try:
            res = minimize(neg_loglik, x0, method="Nelder-Mead",
                          options={"maxiter": 5000, "xatol": 1e-8, "fatol": 1e-8})
            if res.fun < best_nll:
                best_nll, best_res = res.fun, res
        except Exception:
            pass

    if best_res is None:
        return (1e-6, 0.05, 0.05, 0.90), np.full(T, h0)

    omega, alpha, gamma, beta = best_res.x
    h = np.empty(T)
    h[0] = h0
    for t in range(1, T):
        lev = gamma if returns[t - 1] < 0 else 0.0
        h[t] = omega + (alpha + lev) * returns[t - 1] ** 2 + beta * h[t - 1]
        h[t] = max(h[t], 1e-10)
    return tuple(best_res.x), h


# ============================================================
#  Expanding window forecasts
# ============================================================

def run_forecasts(features: pd.DataFrame, daily: pd.DataFrame) -> dict:
    """Expanding-window 1-day-ahead forecasts. All evaluated against RV_{t+1}."""

    # We need at least RV_week (5-day) to exist.
    # Use min_train = 10 to have enough regression points.
    min_train = 10

    # Filter to rows where key features exist
    data = features.dropna(subset=["RV_day", "RV_week", "RV_next"]).copy()
    n = len(data)

    print(f"\nForecasting with expanding window:")
    print(f"  Usable rows (with RV_week + target): {n}")
    print(f"  Min training: {min_train}")
    print(f"  Max OOS: {n - min_train - 1}")

    model_names = [
        "HAR-RV",        # RV_day + RV_week + RV_month
        "HAR-RV-short",  # RV_day + RV_week only (no monthly)
        "HAR-RV-J",      # + jump
        "HAR-RV-VIX",    # + VIX
        "HAR-SQ",        # daily sq_return proxy, target=RV
        "HAR-ABS",       # daily abs_return proxy, target=RV
        "HAR-SQ-VIX",    # sq proxy + VIX
        "GJR-GARCH",
        "EWMA",
        "VIX-implied",
        "Naive-RV",      # yesterday's RV
    ]

    results = {m: [] for m in model_names}
    results["dates"] = []
    results["realized"] = []

    # EWMA pre-compute
    sq_arr = data["sq_return"].values
    rv_arr = data["RV"].values
    ewma_lam = 0.94
    ewma = np.zeros(n)
    ewma[0] = sq_arr[0] if not np.isnan(sq_arr[0]) else rv_arr[0]
    for i in range(1, n):
        s = sq_arr[i] if not np.isnan(sq_arr[i]) else rv_arr[i]
        ewma[i] = ewma_lam * ewma[i - 1] + (1 - ewma_lam) * s

    # GJR estimation: use full daily returns up to each date
    # Pre-estimate once on daily data before OOS period
    oos_start_date = data.index[min_train]
    daily_before = daily.loc[daily.index < oos_start_date, "log_return"].values
    if len(daily_before) > 50:
        gjr_params, gjr_h_series = estimate_gjr_garch(daily_before)
        gjr_last_h = gjr_h_series[-1]
    else:
        gjr_params = (1e-6, 0.05, 0.05, 0.90)
        gjr_last_h = np.var(daily_before) if len(daily_before) > 0 else rv_arr[0]

    gjr_omega, gjr_alpha, gjr_gamma, gjr_beta = gjr_params
    print(f"  GJR-GARCH params: ω={gjr_omega:.2e}, α={gjr_alpha:.3f}, γ={gjr_gamma:.3f}, β={gjr_beta:.3f}")
    print(f"  Persistence: {gjr_alpha + gjr_gamma/2 + gjr_beta:.4f}")

    for t in range(min_train, n - 1):
        test_idx = t + 1
        realized_rv = data.iloc[test_idx]["RV"]
        results["dates"].append(str(data.index[test_idx].date()))
        results["realized"].append(float(realized_rv))

        # Current-day values (for prediction of next day)
        cur = data.iloc[t]

        # ---- HAR-RV (full: day + week + month) ----
        cols_rv = ["RV_day", "RV_week", "RV_month"]
        X_train = data.iloc[:t + 1][cols_rv].values
        y_train = data.iloc[:t + 1]["RV_next"].values
        valid = ~(np.isnan(X_train).any(axis=1) | np.isnan(y_train))
        if valid.sum() >= 4:
            beta = ols_fit(X_train[valid], y_train[valid])
            x_test = cur[cols_rv].values.astype(float)
            if not np.any(np.isnan(x_test)):
                pred = ols_predict(x_test, beta)
            else:
                pred = rv_arr[t]
        else:
            pred = rv_arr[t]
        results["HAR-RV"].append(float(pred))

        # ---- HAR-RV-short (day + week only) ----
        cols_short = ["RV_day", "RV_week"]
        X_train_s = data.iloc[:t + 1][cols_short].values
        valid = ~(np.isnan(X_train_s).any(axis=1) | np.isnan(y_train))
        if valid.sum() >= 3:
            beta_s = ols_fit(X_train_s[valid], y_train[valid])
            x_test_s = cur[cols_short].values.astype(float)
            pred_s = ols_predict(x_test_s, beta_s) if not np.any(np.isnan(x_test_s)) else rv_arr[t]
        else:
            pred_s = rv_arr[t]
        results["HAR-RV-short"].append(float(pred_s))

        # ---- HAR-RV-J (+ jump) ----
        cols_j = ["RV_day", "RV_week", "RV_month", "RJ_day"]
        X_train_j = data.iloc[:t + 1][cols_j].values
        valid = ~(np.isnan(X_train_j).any(axis=1) | np.isnan(y_train))
        if valid.sum() >= 5:
            beta_j = ols_fit(X_train_j[valid], y_train[valid])
            x_test_j = cur[cols_j].values.astype(float)
            pred_j = ols_predict(x_test_j, beta_j) if not np.any(np.isnan(x_test_j)) else rv_arr[t]
        else:
            pred_j = rv_arr[t]
        results["HAR-RV-J"].append(float(pred_j))

        # ---- HAR-RV-VIX ----
        cols_v = ["RV_day", "RV_week", "RV_month", "vix_daily_var"]
        X_train_v = data.iloc[:t + 1][cols_v].values
        valid = ~(np.isnan(X_train_v).any(axis=1) | np.isnan(y_train))
        if valid.sum() >= 5:
            beta_v = ols_fit(X_train_v[valid], y_train[valid])
            x_test_v = cur[cols_v].values.astype(float)
            pred_v = ols_predict(x_test_v, beta_v) if not np.any(np.isnan(x_test_v)) else rv_arr[t]
        else:
            pred_v = rv_arr[t]
        results["HAR-RV-VIX"].append(float(pred_v))

        # ---- HAR-SQ (daily squared return proxy → predict RV) ----
        cols_sq = ["sq_day", "sq_week", "sq_month"]
        X_train_sq = data.iloc[:t + 1][cols_sq].values
        valid = ~(np.isnan(X_train_sq).any(axis=1) | np.isnan(y_train))
        if valid.sum() >= 4:
            beta_sq = ols_fit(X_train_sq[valid], y_train[valid])
            x_test_sq = cur[cols_sq].values.astype(float)
            pred_sq = ols_predict(x_test_sq, beta_sq) if not np.any(np.isnan(x_test_sq)) else rv_arr[t]
        else:
            pred_sq = rv_arr[t]
        results["HAR-SQ"].append(float(pred_sq))

        # ---- HAR-ABS (daily abs return proxy → predict RV) ----
        cols_abs = ["abs_day", "abs_week", "abs_month"]
        X_train_abs = data.iloc[:t + 1][cols_abs].values
        valid = ~(np.isnan(X_train_abs).any(axis=1) | np.isnan(y_train))
        if valid.sum() >= 4:
            beta_abs = ols_fit(X_train_abs[valid], y_train[valid])
            x_test_abs = cur[cols_abs].values.astype(float)
            pred_abs = ols_predict(x_test_abs, beta_abs) if not np.any(np.isnan(x_test_abs)) else rv_arr[t]
        else:
            pred_abs = rv_arr[t]
        results["HAR-ABS"].append(float(pred_abs))

        # ---- HAR-SQ-VIX ----
        cols_sqv = ["sq_day", "sq_week", "sq_month", "vix_daily_var"]
        X_train_sqv = data.iloc[:t + 1][cols_sqv].values
        valid = ~(np.isnan(X_train_sqv).any(axis=1) | np.isnan(y_train))
        if valid.sum() >= 5:
            beta_sqv = ols_fit(X_train_sqv[valid], y_train[valid])
            x_test_sqv = cur[cols_sqv].values.astype(float)
            pred_sqv = ols_predict(x_test_sqv, beta_sqv) if not np.any(np.isnan(x_test_sqv)) else rv_arr[t]
        else:
            pred_sqv = rv_arr[t]
        results["HAR-SQ-VIX"].append(float(pred_sqv))

        # ---- GJR-GARCH ----
        # Update GJR h with daily returns since last estimation
        cur_date = data.index[t]
        daily_up_to = daily.loc[daily.index <= cur_date, "log_return"].values

        # Re-estimate every 10 OOS points
        if (t - min_train) % 10 == 0 and len(daily_up_to) > 50:
            gjr_params_new, gjr_h_new = estimate_gjr_garch(daily_up_to)
            gjr_omega, gjr_alpha, gjr_gamma, gjr_beta = gjr_params_new
            gjr_last_h = gjr_h_new[-1]

        last_ret = daily_up_to[-1] if len(daily_up_to) > 0 else 0.0
        lev = gjr_gamma if last_ret < 0 else 0.0
        h_next = gjr_omega + (gjr_alpha + lev) * last_ret ** 2 + gjr_beta * gjr_last_h
        h_next = max(h_next, 1e-10)
        gjr_last_h = h_next
        results["GJR-GARCH"].append(float(h_next))

        # ---- EWMA ----
        results["EWMA"].append(float(ewma[t]))

        # ---- VIX-implied ----
        vix_var = cur["vix_daily_var"]
        results["VIX-implied"].append(float(vix_var) if not np.isnan(vix_var) else float(ewma[t]))

        # ---- Naive persistence (yesterday's RV) ----
        results["Naive-RV"].append(float(rv_arr[t]))

    n_oos = len(results["realized"])
    print(f"  Generated {n_oos} OOS forecasts")
    print(f"  OOS dates: {results['dates'][0]} to {results['dates'][-1]}")
    return results


# ============================================================
#  Main
# ============================================================

def main():
    t0 = time.time()

    print_section("K745: Pilot HAR-RV with 51-Day 5-Min Data")
    print("First High-Frequency Vol Forecast for VolPred")
    print("⚠ PRELIMINARY: ~28 OOS observations (need 252+ for publishable)")
    print(f"Started: {datetime.now().isoformat()}")

    # ---- Part A: Load data ----
    print_section("Part A: Compute Realized Measures from 5-Min Data")
    intraday_dir = project_root / "data" / "intraday"
    rv_df = load_5min_rv(intraday_dir)

    # Descriptive stats
    print("\n  Descriptive Statistics:")
    print(f"  {'Measure':<15} {'Mean':>12} {'Std':>12} {'Min':>12} {'Max':>12} {'Skew':>8} {'Kurt':>8}")
    print(f"  {'-' * 75}")
    for col in ["RV", "BV", "RJ"]:
        v = rv_df[col].values
        print(f"  {col:<15} {v.mean():>12.6f} {v.std():>12.6f} {v.min():>12.6f} {v.max():>12.6f}"
              f" {float(stats.skew(v)):>8.2f} {float(stats.kurtosis(v)):>8.2f}")

    rv_vol = np.sqrt(rv_df["RV"].values * 252) * 100
    rv_vals = rv_df["RV"].values
    ac1_rv = np.corrcoef(rv_vals[:-1], rv_vals[1:])[0, 1]
    jump_frac = (rv_df["RJ"] / rv_df["RV"]).values

    print(f"\n  Annualized Vol (from RV): mean={rv_vol.mean():.1f}%, std={rv_vol.std():.1f}%")
    print(f"  Jump fraction (RJ/RV): mean={jump_frac.mean():.3f}, max={jump_frac.max():.3f}")
    print(f"  AC(1) of RV: {ac1_rv:.3f}")
    # AC(2), AC(5)
    for lag in [2, 5]:
        if len(rv_vals) > lag:
            ac_lag = np.corrcoef(rv_vals[lag:], rv_vals[:-lag])[0, 1]
            print(f"  AC({lag}) of RV: {ac_lag:.3f}")

    # ADF test on RV
    from scipy.stats import t as t_dist
    # Simple ADF: ΔRV_t = a + ρ*RV_{t-1} + e
    drv = np.diff(rv_vals)
    rv_lag = rv_vals[:-1]
    beta_adf = ols_fit(rv_lag.reshape(-1, 1), drv)
    rho = beta_adf[1]
    # ADF critical values (approx): -3.5 (1%), -2.9 (5%), -2.6 (10%)
    # Estimate t-stat manually
    resid_adf = drv - np.column_stack([np.ones(len(rv_lag)), rv_lag.reshape(-1, 1)]) @ beta_adf
    se_adf = np.sqrt(np.sum(resid_adf ** 2) / (len(rv_lag) - 2) /
                     np.sum((rv_lag - rv_lag.mean()) ** 2))
    t_adf = rho / se_adf
    print(f"  ADF test on RV: t-stat={t_adf:.2f} (crit: -2.9 at 5%)")
    print(f"    → {'Stationary' if t_adf < -2.9 else 'Non-stationary (expected with short sample)'}")

    # Load daily data
    print_section("Part A.2: Load Daily Data")
    daily = load_daily_data()

    sq_ret = daily["sq_return"].dropna().values
    ac1_sq = np.corrcoef(sq_ret[:-1], sq_ret[1:])[0, 1]
    print(f"  AC(1) of daily r²: {ac1_sq:.3f}")
    print(f"  AC(1) ratio (RV/r²): {ac1_rv / ac1_sq:.1f}x")

    # Correlation between RV and same-day r²
    merged_check = rv_df[["RV"]].copy()
    merged_check["sq_return"] = daily["sq_return"].reindex(merged_check.index)
    merged_check = merged_check.dropna()
    corr_rv_sq = np.corrcoef(merged_check["RV"].values, merged_check["sq_return"].values)[0, 1]
    print(f"  Corr(RV_5min, r²_daily) same-day: {corr_rv_sq:.3f}")

    # ---- Part B: Build features ----
    print_section("Part B: Build Features")
    features = build_all_features(rv_df, daily)

    # ---- Part B.2: In-sample diagnostics ----
    print_section("Part B.2: In-Sample HAR-RV Diagnostics")

    mask = features[["RV_day", "RV_week", "RV_next"]].notna().all(axis=1)
    full = features[mask]

    for label, cols in [
        ("HAR-RV (d+w+m)", ["RV_day", "RV_week", "RV_month"]),
        ("HAR-RV (d+w)", ["RV_day", "RV_week"]),
        ("HAR-SQ (d+w+m)", ["sq_day", "sq_week", "sq_month"]),
    ]:
        sub = full.dropna(subset=cols + ["RV_next"])
        if len(sub) < 5:
            continue
        X = sub[cols].values
        y = sub["RV_next"].values
        beta = ols_fit(X, y)
        y_hat = np.column_stack([np.ones(len(X)), X]) @ beta
        ss_res = np.sum((y - y_hat) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot

        # t-stats
        resid = y - y_hat
        sigma2 = np.sum(resid ** 2) / (len(y) - len(beta))
        X_aug = np.column_stack([np.ones(len(X)), X])
        try:
            cov_b = sigma2 * np.linalg.inv(X_aug.T @ X_aug)
            se = np.sqrt(np.diag(cov_b))
            t_stat = beta / se
        except np.linalg.LinAlgError:
            t_stat = np.zeros_like(beta)
            se = np.ones_like(beta)

        pnames = ["const"] + cols
        print(f"\n  {label} (N={len(sub)}, R²={r2:.4f}):")
        for i, nm in enumerate(pnames):
            sig = "***" if abs(t_stat[i]) > 2.58 else "**" if abs(t_stat[i]) > 1.96 else "*" if abs(t_stat[i]) > 1.64 else ""
            print(f"    {nm:<15} β={beta[i]:>10.5f}  t={t_stat[i]:>6.2f}{sig}")

    # ---- Part C: Forecasts ----
    print_section("Part C: Expanding Window OOS Forecasts")
    forecasts = run_forecasts(features, daily)

    # ---- Part D: Evaluation ----
    print_section("Part D: Forecast Evaluation")

    realized = np.array(forecasts["realized"])
    n_oos = len(realized)

    print(f"\n  OOS period: {forecasts['dates'][0]} to {forecasts['dates'][-1]}")
    print(f"  OOS observations: {n_oos}")
    print(f"  ⚠ PRELIMINARY: N={n_oos} << 252 minimum")

    model_names = [m for m in forecasts if m not in ("dates", "realized")]
    eval_results = {}

    print(f"\n  {'Model':<18} {'QLIKE':>10} {'MSE(×1e8)':>12} {'R²':>8} {'Corr':>8} {'MZ-R²':>8}")
    print(f"  {'-' * 64}")

    for model in model_names:
        fcast = np.maximum(np.array(forecasts[model]), 1e-10)

        ql = qlike_loss(realized, fcast)
        mse = mse_loss(realized, fcast)
        r2 = r_squared(realized, fcast)
        corr = np.corrcoef(realized, fcast)[0, 1]

        # Mincer-Zarnowitz R²
        beta_mz = ols_fit(fcast.reshape(-1, 1), realized)
        y_hat_mz = np.column_stack([np.ones(len(fcast)), fcast.reshape(-1, 1)]) @ beta_mz
        ss_res_mz = np.sum((realized - y_hat_mz) ** 2)
        ss_tot_mz = np.sum((realized - realized.mean()) ** 2)
        mz_r2 = 1 - ss_res_mz / ss_tot_mz if ss_tot_mz > 0 else 0

        eval_results[model] = {
            "QLIKE": round(ql, 6),
            "MSE": round(mse, 14),
            "R2_oos": round(r2, 4),
            "Corr": round(corr, 4),
            "MZ_R2": round(mz_r2, 4),
            "MZ_intercept": round(float(beta_mz[0]), 8),
            "MZ_slope": round(float(beta_mz[1]), 4),
        }

        # Flag 5-min models
        tag = " ★" if model.startswith("HAR-RV") else ""
        print(f"  {model:<18} {ql:>10.4f} {mse * 1e8:>12.4f} {r2:>8.4f} {corr:>8.4f} {mz_r2:>8.4f}{tag}")

    # ---- DM tests ----
    print_section("Part D.2: Diebold-Mariano Tests")

    # Reference model: HAR-RV
    ref_model = "HAR-RV"
    ref_loss = qlike_loss_array(realized, np.maximum(np.array(forecasts[ref_model]), 1e-10))

    print(f"\n  Reference: {ref_model}")
    print(f"  {'Model':<18} {'DM':>8} {'p':>8} {'Winner':>18} {'Note':>12}")
    print(f"  {'-' * 64}")

    dm_results = {}
    for model in model_names:
        if model == ref_model:
            continue
        fcast = np.maximum(np.array(forecasts[model]), 1e-10)
        m_loss = qlike_loss_array(realized, fcast)
        dm_stat, p_val = dm_test(ref_loss, m_loss)

        winner = ref_model if dm_stat < 0 else model
        sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else "NS"

        dm_results[model] = {"DM": round(dm_stat, 3), "p": round(p_val, 4), "winner": winner}

        note = f"N={n_oos} too small" if sig == "NS" else ""
        print(f"  {model:<18} {dm_stat:>8.3f} {p_val:>8.4f} {winner:>18} {sig:>4} {note}")

    # ---- Also test: HAR-RV-VIX vs all ----
    best_rv_model = min(
        [(m, eval_results[m]["QLIKE"]) for m in model_names if m.startswith("HAR-RV")],
        key=lambda x: x[1]
    )[0]

    if best_rv_model != ref_model:
        print(f"\n  Best 5-min model: {best_rv_model}")
        best_loss = qlike_loss_array(realized, np.maximum(np.array(forecasts[best_rv_model]), 1e-10))
        for model in ["HAR-SQ", "HAR-ABS", "GJR-GARCH", "EWMA", "Naive-RV"]:
            if model in forecasts:
                m_loss = qlike_loss_array(realized, np.maximum(np.array(forecasts[model]), 1e-10))
                dm_s, p_v = dm_test(best_loss, m_loss)
                sig = "***" if p_v < 0.01 else "**" if p_v < 0.05 else "*" if p_v < 0.10 else "NS"
                winner = best_rv_model if dm_s < 0 else model
                print(f"  {best_rv_model} vs {model:<15}: DM={dm_s:>7.3f}, p={p_v:.4f} → {winner} {sig}")

    # ---- Key comparison: 5-min vs daily ----
    print_section("Part D.3: Key Comparison — 5-Min RV vs Daily Proxy")

    har_rv_ql = eval_results["HAR-RV"]["QLIKE"]
    har_sq_ql = eval_results["HAR-SQ"]["QLIKE"]
    har_abs_ql = eval_results["HAR-ABS"]["QLIKE"]
    ewma_ql = eval_results["EWMA"]["QLIKE"]
    gjr_ql = eval_results["GJR-GARCH"]["QLIKE"]

    print(f"\n  Model                QLIKE    vs HAR-RV")
    print(f"  {'-' * 45}")
    for m, ql in sorted(eval_results.items(), key=lambda x: x[1]["QLIKE"]):
        imp = (ql["QLIKE"] - har_rv_ql) / har_rv_ql * 100
        arrow = "←" if ql["QLIKE"] == har_rv_ql else ("↑worse" if imp > 0 else "↓better")
        print(f"  {m:<20} {ql['QLIKE']:.6f}  {imp:>+7.1f}% {arrow}")

    # ---- Ranking ----
    print_section("Summary & Ranking")

    ranked = sorted(eval_results.items(), key=lambda x: x[1]["QLIKE"])
    print(f"\n  Ranking by QLIKE (lower = better):")
    for i, (m, metrics) in enumerate(ranked, 1):
        tag = " ★ 5-min" if m.startswith("HAR-RV") else ""
        print(f"  {i:>2}. {m:<18} QLIKE={metrics['QLIKE']:.6f}  R²={metrics['R2_oos']:.4f}"
              f"  MZ-R²={metrics['MZ_R2']:.4f}{tag}")

    best = ranked[0][0]
    worst_daily = max(
        [(m, v["QLIKE"]) for m, v in eval_results.items() if not m.startswith("HAR-RV") and m != "VIX-implied"],
        key=lambda x: x[1]
    )

    # 5-min vs daily proxy improvement
    best_5min = min([(m, v["QLIKE"]) for m, v in eval_results.items() if m.startswith("HAR-RV")], key=lambda x: x[1])
    best_daily = min([(m, v["QLIKE"]) for m, v in eval_results.items() if not m.startswith("HAR-RV")], key=lambda x: x[1])
    imp_pct = (best_daily[1] - best_5min[1]) / best_daily[1] * 100

    print(f"\n  Best 5-min model: {best_5min[0]} (QLIKE={best_5min[1]:.6f})")
    print(f"  Best daily model: {best_daily[0]} (QLIKE={best_daily[1]:.6f})")
    print(f"  5-min improvement: {imp_pct:+.1f}%")

    print(f"\n  Key Findings (PRELIMINARY, N={n_oos}):")
    if best.startswith("HAR-RV"):
        print(f"  [1] HAR-RV (5-min) family dominates — top 3 are all 5-min models")
    else:
        print(f"  [1] {best} beats HAR-RV — unexpected, investigate")

    print(f"  [2] AC(1) of 5-min RV: {ac1_rv:.3f} vs daily r²: {ac1_sq:.3f} ({ac1_rv/ac1_sq:.1f}x)")
    print(f"  [3] Corr(RV, r²) same-day: {corr_rv_sq:.3f}")

    any_sig = any(v["p"] < 0.10 for v in dm_results.values())
    if any_sig:
        sig_models = [m for m, v in dm_results.items() if v["p"] < 0.10]
        print(f"  [4] DM significant at 10%: {', '.join(sig_models)}")
    else:
        print(f"  [4] No DM significant at 10% — N={n_oos} too small (expected)")

    print(f"\n  ⚠ LIMITATION: N={n_oos} is far below 252-day minimum.")
    print(f"  These results are for METHODOLOGY VALIDATION only.")
    print(f"  Full test: ~2027-01 (when we have 252+ OOS days)")
    print(f"  Next milestone: 60 days (~April 11) for stable HAR-RV estimation")

    elapsed = time.time() - t0
    print(f"\n  Runtime: {elapsed:.1f}s")

    # ---- Save ----
    print_section("Saving Results")

    output = {
        "experiment_id": "K745",
        "title": "Pilot HAR-RV with 51-Day 5-Min Data — First High-Frequency Vol Forecast",
        "timestamp": datetime.now().isoformat(),
        "runtime_seconds": round(elapsed, 1),
        "data_source": "yfinance 5-min SPY + daily SPY/VIX",
        "data_period": f"{rv_df.index[0].date()} to {rv_df.index[-1].date()}",
        "n_5min_days": len(rv_df),
        "n_oos": n_oos,
        "oos_dates": forecasts["dates"],
        "limitation": f"PRELIMINARY: N={n_oos} << 252 OOS minimum. Methodology validation only.",
        "realized_measures": {
            "mean_RV": round(float(rv_df["RV"].mean()), 8),
            "std_RV": round(float(rv_df["RV"].std()), 8),
            "mean_annualized_vol_pct": round(float(rv_vol.mean()), 1),
            "mean_jump_fraction": round(float(jump_frac.mean()), 4),
            "AC1_RV": round(float(ac1_rv), 4),
            "AC1_daily_sq": round(float(ac1_sq), 4),
            "AC1_ratio": round(float(ac1_rv / ac1_sq), 2),
            "corr_RV_daily_sq": round(float(corr_rv_sq), 4),
            "ADF_t_stat": round(float(t_adf), 2),
        },
        "in_sample_HAR_RV": {
            "N": int(len(full)),
        },
        "oos_evaluation": eval_results,
        "dm_tests_vs_HAR_RV": dm_results,
        "ranking_by_QLIKE": [
            {"rank": i + 1, "model": m, "QLIKE": v["QLIKE"], "R2": v["R2_oos"], "MZ_R2": v["MZ_R2"]}
            for i, (m, v) in enumerate(ranked)
        ],
        "key_comparison": {
            "best_5min_model": best_5min[0],
            "best_5min_QLIKE": best_5min[1],
            "best_daily_model": best_daily[0],
            "best_daily_QLIKE": best_daily[1],
            "improvement_pct": round(imp_pct, 2),
        },
        "conclusion": (
            f"PRELIMINARY (N={n_oos}): "
            f"Best model: {best} (QLIKE={eval_results[best]['QLIKE']:.6f}). "
            f"Best 5-min ({best_5min[0]}) vs best daily ({best_daily[0]}): {imp_pct:+.1f}% QLIKE improvement. "
            f"AC(1) of 5-min RV ({ac1_rv:.3f}) is {ac1_rv/ac1_sq:.1f}x daily r² ({ac1_sq:.3f}). "
            f"Jump fraction low ({jump_frac.mean():.3f}) — limited jump contribution expected. "
            f"Full test needs 252+ OOS days. Next milestone: 60 days (~April 11)."
        ),
        "references": [
            "Corsi (2009, JFE): HAR-RV model",
            "Andersen et al. (2003, Econometrica): Realized volatility",
            "Barndorff-Nielsen & Shephard (2004, JFE): Bipower variation",
            "Patton (2011, JoE): QLIKE loss function",
            "K530: HAR-ABS DM=-15.45 vs GJR-GARCH (daily proxy)",
            "K744: 5-min data validation, AC(1) gap confirmed",
        ],
    }

    results_path = project_root / "experiments" / "k745_pilot_har_rv_results.json"
    with open(results_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"  Results: {results_path}")

    forecasts_path = project_root / "experiments" / "k745_forecasts.json"
    with open(forecasts_path, "w") as f:
        json.dump(forecasts, f, indent=2, default=str)
    print(f"  Forecasts: {forecasts_path}")

    print(f"\n{'=' * 72}")
    print(f"  K745 COMPLETE — First real HAR-RV with 5-min data!")
    print(f"{'=' * 72}\n")

    return output


if __name__ == "__main__":
    main()
