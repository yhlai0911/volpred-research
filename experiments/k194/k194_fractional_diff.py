"""
K194: Fractional Differentiation for Volatility Features (de Prado 2018)
=========================================================================
[提出: 用戶, 執行: Claude]

Research Question:
  Does fractionally differentiating log(RV) — preserving long-range dependence
  while achieving stationarity — improve next-day realized-vol forecasting
  relative to EWMA and GJR-GARCH?

Background:
  Marcos López de Prado (2018), "Advances in Financial Machine Learning",
  proposed Fixed-Width Window Fractional Differentiation (FFD) to balance
  stationarity vs. memory preservation. Standard d=1 differencing destroys
  long-range dependence; fractional d (0 < d < 1) retains it.

Methodology:
  1. Compute daily RV proxy = |r_t| (absolute return, robust proxy)
  2. FFD: X^(d)_t = Σ_{k=0}^{K} w_k * X_{t-k}
     Weights w_k = Π_{j=0}^{k-1} ((-d+j)/(j+1)),  w_0 = 1
     Truncate when |w_k| < 1e-5
  3. Apply to log(RV) with d = 0.1, 0.2, ..., 0.9
  4. ADF test to find minimum d for stationarity (p < 0.05) = d*
  5. Rolling OLS: RV_{t+1} = a + b * FFD(log(RV), d*) + e
  6. Compare QLIKE vs EWMA(0.94) and GJR-GARCH(1,1)
  7. Also test: fractionally differenced VIX as predictor
  8. DM test for pairwise comparison; cross-asset validation

Data: SPY, QQQ, GLD, TLT, BTC-USD daily from yfinance.
OOS: 2023-01-01 to 2024-12-31.
All data sourced from Yahoo Finance (yfinance).
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from pathlib import Path
from scipy import stats
from scipy.special import gamma as gamma_func
from statsmodels.tsa.stattools import adfuller
from arch import arch_model

warnings.filterwarnings('ignore')

# ============================================================
# 0. CONFIGURATION
# ============================================================
ASSETS = ['SPY', 'QQQ', 'GLD', 'TLT', 'BTC-USD']
DATA_START = '2007-01-01'
DATA_END = '2025-03-23'
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
WINDOW = 500  # rolling OLS window
GARCH_WINDOW = 2000
REFIT_FREQ = 22
D_VALUES = np.arange(0.1, 1.0, 0.1)  # 0.1 to 0.9
WEIGHT_THRESHOLD = 1e-5

RESULTS_DIR = Path(__file__).resolve().parent


# ============================================================
# 1. FFD IMPLEMENTATION (de Prado 2018, Chapter 5)
# ============================================================
def compute_ffd_weights(d, threshold=WEIGHT_THRESHOLD):
    """
    Compute FFD weights using the recursive formula:
    w_0 = 1
    w_k = w_{k-1} * (-d + k - 1) / k  for k >= 1

    This is equivalent to the binomial series expansion of (1-B)^d.
    Truncate when |w_k| < threshold.
    """
    weights = [1.0]
    k = 1
    while True:
        w_new = weights[-1] * (-d + k - 1) / k
        if abs(w_new) < threshold:
            break
        weights.append(w_new)
        k += 1
        if k > 10000:  # safety
            break
    return np.array(weights)


def ffd_series(series, d, threshold=WEIGHT_THRESHOLD):
    """
    Apply Fixed-Width Window Fractional Differentiation to a series.

    FFD(X, d)_t = Σ_{k=0}^{K} w_k * X_{t-k}

    Returns a pandas Series with the same index (NaN for insufficient history).
    """
    weights = compute_ffd_weights(d, threshold)
    K = len(weights)
    result = pd.Series(index=series.index, dtype=float)

    for i in range(K - 1, len(series)):
        # X[i], X[i-1], ..., X[i-K+1] dot product with weights
        window = series.values[i - K + 1:i + 1][::-1]  # reverse to align w_0 with X_t
        result.iloc[i] = np.dot(weights, window)

    return result


def find_min_d_for_stationarity(series, d_values, threshold=WEIGHT_THRESHOLD):
    """
    Find minimum d such that ADF test rejects unit root at p < 0.05.
    Returns (d_star, adf_results_dict).
    """
    adf_results = {}
    d_star = None

    for d in d_values:
        ffd = ffd_series(series, d, threshold)
        ffd_clean = ffd.dropna()

        if len(ffd_clean) < 100:
            adf_results[round(d, 2)] = {'adf_stat': np.nan, 'p_value': 1.0, 'n_obs': len(ffd_clean)}
            continue

        try:
            adf_stat, p_value, _, _, crit_values, _ = adfuller(ffd_clean, maxlag=20, regression='c')
            adf_results[round(d, 2)] = {
                'adf_stat': float(adf_stat),
                'p_value': float(p_value),
                'n_obs': int(len(ffd_clean)),
                'crit_1pct': float(crit_values['1%']),
                'crit_5pct': float(crit_values['5%']),
            }
            if p_value < 0.05 and d_star is None:
                d_star = round(d, 2)
        except Exception as e:
            adf_results[round(d, 2)] = {'adf_stat': np.nan, 'p_value': 1.0, 'error': str(e)}

    return d_star, adf_results


# ============================================================
# 2. BENCHMARK MODELS
# ============================================================
def ewma_forecast(returns_sq, lam=0.94):
    """EWMA(lambda) variance forecast. Returns next-day forecast aligned to returns index."""
    var_ewma = pd.Series(index=returns_sq.index, dtype=float)
    var_ewma.iloc[0] = returns_sq.iloc[0]
    for i in range(1, len(returns_sq)):
        var_ewma.iloc[i] = lam * var_ewma.iloc[i - 1] + (1 - lam) * returns_sq.iloc[i]
    # Forecast for t+1 is the EWMA value at time t
    return var_ewma


def gjr_garch_rolling_forecast(returns_pct, oos_dates, window=GARCH_WINDOW, refit_freq=REFIT_FREQ):
    """
    Rolling GJR-GARCH(1,1) 1-step variance forecast.
    Returns dict date -> variance forecast (in decimal, not pct^2).
    """
    forecasts = {}
    n = len(returns_pct)
    oos_locs = [returns_pct.index.get_loc(d) for d in oos_dates if d in returns_pct.index]

    last_params = None
    for i, loc in enumerate(oos_locs):
        if loc < window:
            continue

        # Refit every refit_freq or on first iteration
        if i % refit_freq == 0 or last_params is None:
            train = returns_pct.iloc[loc - window:loc]
            try:
                am = arch_model(train, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Zero')
                res = am.fit(disp='off', show_warning=False)
                last_params = res
            except Exception:
                continue

        # Forecast
        try:
            # Re-apply params to full history up to loc
            train_full = returns_pct.iloc[max(0, loc - window):loc]
            am2 = arch_model(train_full, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Zero')
            res2 = am2.fit(disp='off', show_warning=False,
                           starting_values=last_params.params.values)
            fc = res2.forecast(horizon=1)
            var_forecast = fc.variance.iloc[-1, 0] / 1e4  # pct^2 -> decimal
            forecasts[oos_dates[i]] = var_forecast
        except Exception:
            pass

    return forecasts


# ============================================================
# 3. LOSS FUNCTIONS & STATISTICAL TESTS
# ============================================================
def qlike(actual_var, forecast_var):
    """QLIKE loss: log(forecast) + actual/forecast. Lower is better."""
    mask = (forecast_var > 0) & (actual_var > 0) & np.isfinite(actual_var) & np.isfinite(forecast_var)
    a = actual_var[mask]
    f = forecast_var[mask]
    return np.mean(np.log(f) + a / f)


def mse_loss(actual_var, forecast_var):
    """MSE loss."""
    mask = np.isfinite(actual_var) & np.isfinite(forecast_var)
    return np.mean((actual_var[mask] - forecast_var[mask]) ** 2)


def dm_test(loss1, loss2, h=1):
    """
    Diebold-Mariano test. H0: equal predictive ability.
    Returns (t_stat, p_value). Negative t means model 1 is better.
    """
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 30:
        return np.nan, np.nan

    d_bar = np.mean(d)

    # HAC variance (Newey-West with h-1 lags)
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k

    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        var_d = gamma_0 / n

    t_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))

    return float(t_stat), float(p_value)


# ============================================================
# 4. MAIN EXPERIMENT
# ============================================================
def run_experiment():
    print("=" * 70)
    print("K194: Fractional Differentiation for Volatility Features")
    print("        (de Prado 2018 — FFD Method)")
    print("=" * 70)
    print(f"Assets: {ASSETS}")
    print(f"OOS: {OOS_START} to {OOS_END}")
    print(f"d values tested: {[round(d, 1) for d in D_VALUES]}")
    print(f"Weight threshold: {WEIGHT_THRESHOLD}")
    print()

    all_results = {}

    for ticker in ASSETS:
        print(f"\n{'=' * 65}")
        print(f"  ASSET: {ticker}")
        print(f"{'=' * 65}")

        # ----- Download data -----
        start = DATA_START if ticker != 'BTC-USD' else '2015-01-01'
        df = yf.download(ticker, start=start, end=DATA_END, auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]

        if len(df) < 1000:
            print(f"  Insufficient data: {len(df)} rows. Skipping.")
            continue

        print(f"  Data: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")

        # ----- Returns and RV proxy -----
        returns = np.log(df['close'] / df['close'].shift(1)).dropna()
        rv_proxy = returns ** 2  # squared returns = daily RV proxy
        abs_returns = returns.abs()
        log_rv = np.log(rv_proxy.replace(0, np.nan)).dropna()

        print(f"  Returns: N={len(returns)}")
        print(f"  log(RV) series: N={len(log_rv)}")

        # ----- Step 1: Check stationarity of raw log(RV) -----
        adf_raw = adfuller(log_rv.dropna(), maxlag=20, regression='c')
        print(f"\n  [1] Raw log(RV) ADF: stat={adf_raw[0]:.4f}, p={adf_raw[1]:.6f}")
        if adf_raw[1] < 0.05:
            print(f"      -> Already stationary! (p<0.05)")
        else:
            print(f"      -> NOT stationary (p={adf_raw[1]:.4f})")

        # ----- Step 2: FFD for each d, find d* -----
        print(f"\n  [2] FFD stationarity sweep (d=0.1 to 0.9):")
        d_star, adf_results = find_min_d_for_stationarity(log_rv, D_VALUES)

        for d_val, res in sorted(adf_results.items()):
            stat_str = f"ADF={res['adf_stat']:.3f}" if not np.isnan(res.get('adf_stat', np.nan)) else "ADF=NaN"
            p_str = f"p={res['p_value']:.4f}"
            marker = " *** d*" if d_val == d_star else ""
            print(f"      d={d_val:.1f}: {stat_str}, {p_str}, n={res.get('n_obs', '?')}{marker}")

        if d_star is None:
            # If log(RV) is already stationary, use d=0.3 as a reasonable default
            if adf_raw[1] < 0.05:
                d_star = 0.3
                print(f"      Using d*=0.3 (raw series already stationary, test memory preservation)")
            else:
                d_star = 0.5
                print(f"      No d achieved stationarity. Using d*=0.5 as default.")

        print(f"\n  d* = {d_star} for {ticker}")

        # ----- Step 3: Compute FFD features for d* -----
        ffd_feature = ffd_series(log_rv, d_star)

        # Also test additional d values for comparison
        d_candidates = [d_star]
        if d_star != 0.3:
            d_candidates.append(0.3)
        if d_star != 0.5:
            d_candidates.append(0.5)
        d_candidates = sorted(set(d_candidates))

        # ----- Step 4: OOS forecasting -----
        oos_mask = returns.index >= OOS_START
        oos_idx = returns.index[oos_mask]

        if len(oos_idx) < 100:
            print(f"  OOS too short: {len(oos_idx)} days. Skipping.")
            continue

        # Actual next-day RV
        actual_rv = rv_proxy.shift(-1)  # RV at t+1

        # ---- Model A: FFD rolling OLS ----
        ffd_model_results = {}
        for d_test in d_candidates:
            ffd_feat = ffd_series(log_rv, d_test)
            forecasts_ffd = pd.Series(index=oos_idx, dtype=float)

            for i, date in enumerate(oos_idx):
                loc = returns.index.get_loc(date)
                if loc < WINDOW + 50:  # need enough history
                    continue

                # Training window for OLS
                train_start = max(0, loc - WINDOW)
                train_idx = returns.index[train_start:loc]

                # Align features and target
                y_train = rv_proxy.reindex(train_idx).shift(-1).iloc[:-1]  # RV_{t+1}
                x_train = ffd_feat.reindex(train_idx).iloc[:-1]  # FFD(log(RV))_t

                # Remove NaN
                valid = y_train.notna() & x_train.notna() & np.isfinite(y_train) & np.isfinite(x_train)
                y_t = y_train[valid].values
                x_t = x_train[valid].values

                if len(y_t) < 50:
                    continue

                # OLS: y = a + b*x
                X_mat = np.column_stack([np.ones(len(x_t)), x_t])
                try:
                    beta = np.linalg.lstsq(X_mat, y_t, rcond=None)[0]
                except Exception:
                    continue

                # Forecast
                x_now = ffd_feat.get(date, np.nan)
                if np.isnan(x_now) or not np.isfinite(x_now):
                    continue

                forecast = beta[0] + beta[1] * x_now
                if forecast > 0 and np.isfinite(forecast):
                    forecasts_ffd[date] = forecast

            ffd_model_results[d_test] = forecasts_ffd
            n_valid = forecasts_ffd.notna().sum()
            print(f"  FFD(d={d_test:.1f}) OLS: {n_valid} valid forecasts")

        # ---- Model B: EWMA(0.94) ----
        ewma_var = ewma_forecast(rv_proxy, lam=0.94)
        # Forecast for t+1 = EWMA value at t
        forecasts_ewma = ewma_var.reindex(oos_idx)

        # ---- Model C: GJR-GARCH ----
        ret_pct = returns * 100
        print(f"\n  Fitting rolling GJR-GARCH (window={GARCH_WINDOW}, refit={REFIT_FREQ})...")
        garch_dict = gjr_garch_rolling_forecast(ret_pct, oos_idx.tolist())
        forecasts_garch = pd.Series(garch_dict).reindex(oos_idx)
        print(f"  GJR-GARCH: {forecasts_garch.notna().sum()} valid forecasts")

        # ---- Model D: FFD(VIX) as predictor (SPY/QQQ only) ----
        forecasts_ffd_vix = pd.Series(dtype=float)
        if ticker in ['SPY', 'QQQ']:
            print(f"\n  [Extra] FFD(VIX) predictor for {ticker}...")
            vix_df = yf.download('^VIX', start=start, end=DATA_END, auto_adjust=True, progress=False)
            if isinstance(vix_df.columns, pd.MultiIndex):
                vix_df.columns = vix_df.columns.get_level_values(0)
            vix_df.columns = [c.lower() for c in vix_df.columns]

            if len(vix_df) > 500:
                vix_close = vix_df['close'].reindex(returns.index).ffill()
                log_vix = np.log(vix_close.replace(0, np.nan)).dropna()

                # Find d* for VIX
                d_star_vix, adf_vix = find_min_d_for_stationarity(log_vix, D_VALUES)
                if d_star_vix is None:
                    d_star_vix = 0.4
                print(f"  VIX d* = {d_star_vix}")

                ffd_vix = ffd_series(log_vix, d_star_vix)

                forecasts_ffd_vix = pd.Series(index=oos_idx, dtype=float)
                for i, date in enumerate(oos_idx):
                    loc = returns.index.get_loc(date)
                    if loc < WINDOW + 50:
                        continue

                    train_start = max(0, loc - WINDOW)
                    train_idx = returns.index[train_start:loc]

                    y_train = rv_proxy.reindex(train_idx).shift(-1).iloc[:-1]
                    x_train = ffd_vix.reindex(train_idx).iloc[:-1]

                    valid = y_train.notna() & x_train.notna() & np.isfinite(y_train) & np.isfinite(x_train)
                    y_t = y_train[valid].values
                    x_t = x_train[valid].values

                    if len(y_t) < 50:
                        continue

                    X_mat = np.column_stack([np.ones(len(x_t)), x_t])
                    try:
                        beta = np.linalg.lstsq(X_mat, y_t, rcond=None)[0]
                    except Exception:
                        continue

                    x_now = ffd_vix.get(date, np.nan)
                    if np.isnan(x_now) or not np.isfinite(x_now):
                        continue

                    forecast = beta[0] + beta[1] * x_now
                    if forecast > 0 and np.isfinite(forecast):
                        forecasts_ffd_vix[date] = forecast

                print(f"  FFD(VIX, d={d_star_vix}) OLS: {forecasts_ffd_vix.notna().sum()} valid forecasts")

        # ---- Model E: Log(RV) raw OLS (no differentiation, baseline) ----
        forecasts_raw_ols = pd.Series(index=oos_idx, dtype=float)
        for i, date in enumerate(oos_idx):
            loc = returns.index.get_loc(date)
            if loc < WINDOW + 50:
                continue

            train_start = max(0, loc - WINDOW)
            train_idx = returns.index[train_start:loc]

            y_train = rv_proxy.reindex(train_idx).shift(-1).iloc[:-1]
            x_train = log_rv.reindex(train_idx).iloc[:-1]

            valid = y_train.notna() & x_train.notna() & np.isfinite(y_train) & np.isfinite(x_train)
            y_t = y_train[valid].values
            x_t = x_train[valid].values

            if len(y_t) < 50:
                continue

            X_mat = np.column_stack([np.ones(len(x_t)), x_t])
            try:
                beta = np.linalg.lstsq(X_mat, y_t, rcond=None)[0]
            except Exception:
                continue

            x_now = log_rv.get(date, np.nan)
            if np.isnan(x_now) or not np.isfinite(x_now):
                continue

            forecast = beta[0] + beta[1] * x_now
            if forecast > 0 and np.isfinite(forecast):
                forecasts_raw_ols[date] = forecast

        print(f"  Raw log(RV) OLS: {forecasts_raw_ols.notna().sum()} valid forecasts")

        # ============================================================
        # 5. EVALUATION
        # ============================================================
        print(f"\n  [3] OOS Evaluation (QLIKE & MSE)")
        print(f"  {'-' * 55}")

        actual = actual_rv.reindex(oos_idx)

        # Collect all model forecasts
        models = {}
        models['EWMA(0.94)'] = forecasts_ewma
        models['GJR-GARCH'] = forecasts_garch
        models['Raw_logRV_OLS'] = forecasts_raw_ols

        for d_test in d_candidates:
            models[f'FFD(d={d_test:.1f})_OLS'] = ffd_model_results[d_test]

        if len(forecasts_ffd_vix) > 0 and forecasts_ffd_vix.notna().sum() > 50:
            models[f'FFD(VIX,d={d_star_vix:.1f})_OLS'] = forecasts_ffd_vix

        # Compute losses
        model_losses = {}
        model_qlike_series = {}

        for name, fc in models.items():
            # Align
            common = actual.index.intersection(fc.dropna().index)
            if len(common) < 50:
                print(f"  {name}: insufficient overlap ({len(common)} days)")
                continue

            a = actual.reindex(common).values
            f = fc.reindex(common).values

            valid = (a > 0) & (f > 0) & np.isfinite(a) & np.isfinite(f)
            a_v, f_v = a[valid], f[valid]

            if len(a_v) < 50:
                continue

            q = float(np.mean(np.log(f_v) + a_v / f_v))
            m = float(np.mean((a_v - f_v) ** 2))
            mae = float(np.mean(np.abs(a_v - f_v)))

            # Mincer-Zarnowitz R²
            slope, intercept, r_value, p_value, std_err = stats.linregress(f_v, a_v)
            mz_r2 = r_value ** 2

            model_losses[name] = {
                'qlike': q,
                'mse': m,
                'mae': mae,
                'mz_r2': float(mz_r2),
                'mz_slope': float(slope),
                'n_obs': int(len(a_v)),
            }

            # Store per-obs QLIKE for DM test
            qlike_per_obs = np.log(f_v) + a_v / f_v
            model_qlike_series[name] = pd.Series(qlike_per_obs, index=common[valid])

            print(f"  {name:25s}  QLIKE={q:.4f}  MSE={m:.2e}  MAE={mae:.4e}  MZ-R²={mz_r2:.4f}  n={len(a_v)}")

        # ---- DM tests: FFD vs benchmarks ----
        print(f"\n  [4] Diebold-Mariano Tests")
        print(f"  {'-' * 55}")

        dm_results = {}
        ffd_best_name = f'FFD(d={d_star:.1f})_OLS'

        if ffd_best_name in model_qlike_series:
            for bench_name in ['EWMA(0.94)', 'GJR-GARCH', 'Raw_logRV_OLS']:
                if bench_name not in model_qlike_series:
                    continue

                # Align
                common_dm = model_qlike_series[ffd_best_name].index.intersection(
                    model_qlike_series[bench_name].index
                )
                if len(common_dm) < 50:
                    continue

                loss1 = model_qlike_series[ffd_best_name].reindex(common_dm).values
                loss2 = model_qlike_series[bench_name].reindex(common_dm).values

                t_stat, p_val = dm_test(loss1, loss2, h=1)
                dm_results[f'{ffd_best_name}_vs_{bench_name}'] = {
                    'dm_t': t_stat,
                    'dm_p': p_val,
                    'n_obs': int(len(common_dm)),
                    'ffd_better': bool(t_stat < 0) if not np.isnan(t_stat) else None,
                }

                direction = "FFD better" if t_stat < 0 else "Benchmark better"
                sig = "***" if p_val < 0.01 else ("**" if p_val < 0.05 else ("*" if p_val < 0.10 else "n.s."))
                print(f"  {ffd_best_name} vs {bench_name}: DM t={t_stat:.3f}, p={p_val:.4f} {sig} ({direction})")

        # ----- Memory preservation analysis -----
        print(f"\n  [5] Memory Analysis")
        print(f"  {'-' * 55}")

        # Autocorrelation at various lags
        memory_analysis = {}
        for d_test in [0.0] + list(d_candidates):
            if d_test == 0.0:
                series_test = log_rv
                label = 'raw_logRV'
            else:
                series_test = ffd_series(log_rv, d_test)
                label = f'FFD(d={d_test:.1f})'

            series_clean = series_test.dropna()
            if len(series_clean) < 200:
                continue

            acf_vals = {}
            for lag in [1, 5, 10, 22, 44, 66]:
                if len(series_clean) > lag + 10:
                    corr = series_clean.autocorr(lag=lag)
                    acf_vals[f'lag_{lag}'] = float(corr) if not np.isnan(corr) else None

            memory_analysis[label] = acf_vals
            lag1 = acf_vals.get('lag_1', 'N/A')
            lag22 = acf_vals.get('lag_22', 'N/A')
            lag66 = acf_vals.get('lag_66', 'N/A')
            print(f"  {label:20s}  ACF(1)={lag1:.3f}  ACF(22)={lag22:.3f}  ACF(66)={lag66:.3f}" if isinstance(lag1, float) else f"  {label:20s}  Insufficient data")

        # ============================================================
        # 6. STORE RESULTS
        # ============================================================
        weights_info = {}
        for d_test in d_candidates:
            w = compute_ffd_weights(d_test)
            weights_info[f'd={d_test:.1f}'] = {
                'n_weights': len(w),
                'first_5': [float(x) for x in w[:5]],
                'last_weight': float(w[-1]),
                'sum_weights': float(np.sum(w)),
            }

        asset_result = {
            'ticker': ticker,
            'data_range': f"{df.index[0].date()} to {df.index[-1].date()}",
            'n_total': int(len(df)),
            'oos_range': f"{OOS_START} to {OOS_END}",
            'raw_adf': {
                'adf_stat': float(adf_raw[0]),
                'p_value': float(adf_raw[1]),
                'stationary': bool(adf_raw[1] < 0.05),
            },
            'd_star': d_star,
            'adf_sweep': adf_results,
            'model_losses': model_losses,
            'dm_tests': dm_results,
            'memory_analysis': memory_analysis,
            'weights_info': weights_info,
        }

        all_results[ticker] = asset_result

    # ============================================================
    # 7. CROSS-ASSET SUMMARY
    # ============================================================
    print(f"\n\n{'=' * 70}")
    print("CROSS-ASSET SUMMARY")
    print(f"{'=' * 70}")

    # Summary table: d*, best model, FFD vs GARCH DM
    print(f"\n{'Ticker':10s} {'d*':>5s} {'Raw Stationary?':>16s} {'Best QLIKE Model':>25s} {'FFD vs GARCH DM':>18s}")
    print("-" * 80)

    cross_asset_summary = {}
    ffd_wins_qlike = 0
    total_comparisons = 0

    for ticker, res in all_results.items():
        d_star = res.get('d_star', '?')
        raw_stat = 'Yes' if res.get('raw_adf', {}).get('stationary', False) else 'No'

        # Find best model by QLIKE
        losses = res.get('model_losses', {})
        if losses:
            best_model = min(losses, key=lambda k: losses[k]['qlike'])
            best_qlike = losses[best_model]['qlike']
        else:
            best_model = 'N/A'
            best_qlike = np.nan

        # FFD vs GARCH DM result
        dm_key = f'FFD(d={d_star})_OLS_vs_GJR-GARCH'
        dm_res = res.get('dm_tests', {}).get(dm_key, {})
        if dm_res:
            dm_str = f"t={dm_res['dm_t']:.2f}, p={dm_res['dm_p']:.3f}"
            if dm_res.get('ffd_better'):
                ffd_wins_qlike += 1
            total_comparisons += 1
        else:
            dm_str = 'N/A'

        print(f"{ticker:10s} {str(d_star):>5s} {raw_stat:>16s} {best_model:>25s} {dm_str:>18s}")

        cross_asset_summary[ticker] = {
            'd_star': d_star,
            'raw_stationary': raw_stat == 'Yes',
            'best_model': best_model,
            'best_qlike': float(best_qlike) if not np.isnan(best_qlike) else None,
        }

    # Harvey (2016) threshold check
    print(f"\n\nHarvey (2016) Multiple Testing Threshold: |t| > 3.0")
    print("-" * 50)
    harvey_passes = 0
    for ticker, res in all_results.items():
        for dm_key, dm_val in res.get('dm_tests', {}).items():
            t = dm_val.get('dm_t', np.nan)
            if not np.isnan(t):
                passes = abs(t) > 3.0
                if passes:
                    harvey_passes += 1
                print(f"  {ticker} {dm_key}: |t|={abs(t):.2f} {'PASS' if passes else 'FAIL'}")

    # Final verdict
    print(f"\n\n{'=' * 70}")
    print("CONCLUSION")
    print(f"{'=' * 70}")
    print(f"  FFD wins (lower QLIKE) vs GJR-GARCH: {ffd_wins_qlike}/{total_comparisons}")
    print(f"  Harvey threshold passes: {harvey_passes}")

    if ffd_wins_qlike < total_comparisons / 2:
        verdict = ("Fractional differentiation does NOT improve vol forecasting over "
                    "GJR-GARCH. The GARCH family already captures vol clustering via its "
                    "recursive structure. FFD preserves long memory but daily RV proxy "
                    "(squared returns) is too noisy for the memory structure to help in "
                    "linear OLS forecasting.")
    elif harvey_passes == 0:
        verdict = ("FFD shows marginal QLIKE improvements for some assets but NO "
                    "result passes the Harvey (2016) |t|>3.0 threshold. Consistent "
                    "with de Prado's original use case (ML classification features, "
                    "not standalone vol forecasting).")
    else:
        verdict = ("FFD shows statistically significant improvement over GARCH "
                    "for some assets. Worth further investigation with multi-feature "
                    "models combining FFD with GARCH conditional variance.")

    print(f"\n  {verdict}")

    # ============================================================
    # 8. SAVE RESULTS
    # ============================================================
    output = {
        'experiment': 'K194',
        'title': 'Fractional Differentiation for Volatility Features (de Prado 2018)',
        'attribution': '[提出: 用戶, 執行: Claude]',
        'timestamp': datetime.now().isoformat(),
        'methodology': {
            'ffd_method': 'Fixed-Width Window (FFD)',
            'weight_threshold': WEIGHT_THRESHOLD,
            'd_range': [0.1, 0.9],
            'ols_window': WINDOW,
            'garch_window': GARCH_WINDOW,
            'oos_period': f'{OOS_START} to {OOS_END}',
            'rv_proxy': 'squared daily returns (r_t^2)',
            'data_source': 'Yahoo Finance via yfinance',
        },
        'cross_asset_summary': cross_asset_summary,
        'ffd_wins_vs_garch': f'{ffd_wins_qlike}/{total_comparisons}',
        'harvey_passes': harvey_passes,
        'verdict': verdict,
        'detailed_results': {},
    }

    # Serialize detailed results (convert numpy types)
    for ticker, res in all_results.items():
        output['detailed_results'][ticker] = res

    # Save to canonical experiment directory.
    results_path = RESULTS_DIR / 'k194_fractional_diff_results.json'
    with open(results_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved to: {results_path}")

    return output


if __name__ == '__main__':
    results = run_experiment()
