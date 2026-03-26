"""
K460: Semivariance Cross-OOS Validation (5 OOS Periods)

Background:
  K449: RS⁻ significantly beats RV for SPY (DM p=0.007) and QQQ (p=0.003)
  K453: Cross-asset shows semivariance advantage is equity-specific (4/5 equities)
  K459: VRP "statistically significant" ≠ "predictive improvement" (cross-OOS failure)

  Must apply same rigorous cross-OOS framework to validate semivariance findings.

Design:
  5 OOS periods (same as K459):
    1. 2015-2016 (low volatility)
    2. 2017-2018 (Volmageddon)
    3. 2019-2020 (COVID)
    4. 2021-2022 (rate hikes)
    5. 2023-2025 (post-COVID)

  For each period:
    IS: preceding 2000 trading days (~8 years)
    OOS: ~500 trading days (~2 years)

  Models:
    1. Baseline: lagged RV21 → next-day |return|
    2. RS⁻ model: lagged RS⁻_21 → next-day |return|
    3. HAR-semi: RS⁻_5 + RS⁻_21 + RS⁺_5 + RS⁺_21
    4. GJR-GARCH(1,1) with t-distribution (arch package)

  Metrics:
    - QLIKE with Parkinson proxy (K441 recommendation: range-based vol estimator)
    - MSE
    - DM test: RS⁻ vs baseline, HAR-semi vs baseline, RS⁻ vs GJR

  Assets: SPY (primary) + QQQ (validation)

  Judgment:
    ≥4/5 periods significant → robust, can go in paper
    ≤2/5 periods → period-specific, must downgrade (like VRP)

Data: yfinance, 2005-01-01 to present
Author: [Proposed: User, Executed: Claude]
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import het_arch, acorr_ljungbox
from arch import arch_model

warnings.filterwarnings('ignore')

print("=" * 70)
print("K460: Semivariance Cross-OOS Validation (5 OOS Periods)")
print("  Publication-critical: Does RS⁻ advantage hold across all regimes?")
print("=" * 70)

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
ASSETS = {
    'SPY': {'name': 'US Large Cap (primary)', 'start': '2005-01-01'},
    'QQQ': {'name': 'US Tech (validation)', 'start': '2005-01-01'},
}

OOS_PERIODS = [
    {"name": "2015-2016 (low vol)", "start": "2015-01-01", "end": "2016-12-31"},
    {"name": "2017-2018 (Volmageddon)", "start": "2017-01-01", "end": "2018-12-31"},
    {"name": "2019-2020 (COVID)", "start": "2019-01-01", "end": "2020-12-31"},
    {"name": "2021-2022 (rate hikes)", "start": "2021-01-01", "end": "2022-12-31"},
    {"name": "2023-2025 (post-COVID)", "start": "2023-01-01", "end": "2025-12-31"},
]

IS_WINDOW = 2000  # trading days (~8 years)

print("\n[1] Downloading data...")
data = {}
for ticker, info in ASSETS.items():
    raw = yf.download(ticker, start=info['start'], progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    data[ticker] = raw
    print(f"  {ticker}: {raw.index[0].date()} to {raw.index[-1].date()} ({len(raw)} obs)")


# ============================================================
# 2. HELPER FUNCTIONS
# ============================================================
def dm_test_losses(loss1, loss2, h=1):
    """Diebold-Mariano test on loss series.
    Positive t-stat = model 1 has LARGER loss → model 2 is BETTER.
    Returns (t_stat, p_value).
    """
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan
    d_mean = np.mean(d)

    # HAC variance (Newey-West with h-1 lags)
    gamma_0 = np.var(d, ddof=1)
    hac_var = gamma_0
    for k in range(1, max(h, 2)):
        if k < n:
            gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
            hac_var += 2 * (1 - k / max(h, 2)) * gamma_k

    if hac_var <= 0:
        return 0.0, 1.0

    t_stat = d_mean / np.sqrt(hac_var / n)
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_value)


def qlike_loss(rv_actual, rv_forecast):
    """QLIKE loss: log(forecast) + actual/forecast. Lower is better."""
    rv_forecast = np.maximum(rv_forecast, 1e-12)
    rv_actual = np.maximum(rv_actual, 1e-12)
    return np.log(rv_forecast) + rv_actual / rv_forecast


def mse_loss(rv_actual, rv_forecast):
    """MSE loss: (actual - forecast)^2."""
    return (rv_actual - rv_forecast) ** 2


def parkinson_vol(high, low):
    """Parkinson range-based variance estimator (daily).
    σ² = (1/4ln2) * [ln(H/L)]²
    Returns per-observation variance.
    """
    log_hl = np.log(np.maximum(high, 1e-10) / np.maximum(low, 1e-10))
    return (1 / (4 * np.log(2))) * log_hl ** 2


# ============================================================
# 3. MAIN ANALYSIS LOOP
# ============================================================
all_asset_results = {}

for ticker, info in ASSETS.items():
    print(f"\n{'#' * 70}")
    print(f"# ASSET: {ticker} ({info['name']})")
    print(f"{'#' * 70}")

    df = data[ticker].copy()
    price = df['Close']
    high = df['High']
    low = df['Low']
    ret = price.pct_change().dropna()
    abs_ret = ret.abs()

    # ============================
    # 3a. Data diagnostics
    # ============================
    print(f"\n[2] Data diagnostics for {ticker}...")
    ret_vals = ret.values.flatten()

    desc_stats = {
        'n_obs': len(ret_vals),
        'mean_pct': round(float(np.mean(ret_vals) * 100), 6),
        'std_pct': round(float(np.std(ret_vals) * 100), 6),
        'skewness': round(float(stats.skew(ret_vals)), 4),
        'kurtosis': round(float(stats.kurtosis(ret_vals)), 4),
    }

    print(f"  N={desc_stats['n_obs']}, Mean={desc_stats['mean_pct']:.4f}%, "
          f"Std={desc_stats['std_pct']:.4f}%")
    print(f"  Skewness={desc_stats['skewness']:.4f}, "
          f"Excess Kurtosis={desc_stats['kurtosis']:.4f}")

    # ADF test
    adf_stat, adf_p = adfuller(ret_vals[:5000])[:2]
    desc_stats['adf_stat'] = round(float(adf_stat), 4)
    desc_stats['adf_p'] = round(float(adf_p), 8)
    print(f"  ADF: stat={adf_stat:.4f}, p={adf_p:.8f} "
          f"{'(stationary)' if adf_p < 0.05 else '(NON-STATIONARY!)'}")

    # ARCH LM test
    arch_lm = het_arch(ret_vals[:5000], nlags=5)
    desc_stats['arch_lm_stat'] = round(float(arch_lm[0]), 4)
    desc_stats['arch_lm_p'] = round(float(arch_lm[1]), 8)
    print(f"  ARCH LM(5): stat={arch_lm[0]:.4f}, p={arch_lm[1]:.8f} "
          f"{'(ARCH effects)' if arch_lm[1] < 0.05 else '(no ARCH)'}")

    # Ljung-Box on squared returns
    lb_sq = acorr_ljungbox(ret_vals[:5000] ** 2, lags=[5, 10], return_df=True)
    desc_stats['ljungbox_sq_5_stat'] = round(float(lb_sq.iloc[0, 0]), 4)
    desc_stats['ljungbox_sq_5_p'] = round(float(lb_sq.iloc[0, 1]), 8)
    print(f"  Ljung-Box(5) r²: stat={lb_sq.iloc[0, 0]:.4f}, p={lb_sq.iloc[0, 1]:.8f}")

    # Negative return fraction
    neg_frac = float((ret_vals < 0).mean())
    desc_stats['neg_return_fraction'] = round(neg_frac, 4)
    print(f"  Negative return fraction: {neg_frac:.4f}")

    # ============================
    # 3b. Build features
    # ============================
    print(f"\n[3] Building features for {ticker}...")

    # Daily squared returns
    ret_sq = ret ** 2

    # Semivariance components (daily)
    ret_neg_sq = ret.apply(lambda x: x ** 2 if x < 0 else 0.0)
    ret_pos_sq = ret.apply(lambda x: x ** 2 if x >= 0 else 0.0)

    # Rolling windows
    rv_21 = ret_sq.rolling(21).mean()
    rs_neg_5 = ret_neg_sq.rolling(5).mean()
    rs_neg_21 = ret_neg_sq.rolling(21).mean()
    rs_pos_5 = ret_pos_sq.rolling(5).mean()
    rs_pos_21 = ret_pos_sq.rolling(21).mean()

    # Parkinson range-based volatility (target proxy, K441 recommendation)
    park_var = parkinson_vol(high, low)

    # Build feature DataFrame with 1-day lag (no look-ahead)
    features = pd.DataFrame({
        'rv_21': rv_21.shift(1),
        'rs_neg_5': rs_neg_5.shift(1),
        'rs_neg_21': rs_neg_21.shift(1),
        'rs_pos_5': rs_pos_5.shift(1),
        'rs_pos_21': rs_pos_21.shift(1),
        'target_abs_ret': abs_ret,
        'target_parkinson': park_var,
    }, index=price.index).dropna()

    print(f"  Feature matrix: {len(features)} obs "
          f"({features.index[0].date()} to {features.index[-1].date()})")

    # Semivariance diagnostics
    is_full = features[features.index < '2023-01-01']
    if len(is_full) > 100:
        rs_neg_mean = is_full['rs_neg_21'].mean()
        rs_pos_mean = is_full['rs_pos_21'].mean()
        rv_mean = is_full['rv_21'].mean()
        print(f"  IS semivariance: RS⁻_21={rs_neg_mean:.8f}, RS⁺_21={rs_pos_mean:.8f}, "
              f"ratio RS⁻/RV={rs_neg_mean/rv_mean:.3f}")

    # ============================
    # 3c. Cross-OOS loop
    # ============================
    period_results = {}

    for p_idx, period in enumerate(OOS_PERIODS):
        pname = period['name']
        print(f"\n{'=' * 60}")
        print(f"  Period {p_idx + 1}/5: {pname}")
        print(f"{'=' * 60}")

        oos_mask = (features.index >= period['start']) & (features.index <= period['end'])
        oos_data = features[oos_mask]
        n_oos = len(oos_data)

        if n_oos < 50:
            print(f"  SKIP: only {n_oos} OOS observations")
            continue

        # IS window: preceding IS_WINDOW days
        first_oos_pos = features.index.get_loc(oos_data.index[0])
        if isinstance(first_oos_pos, slice):
            first_oos_pos = first_oos_pos.start
        is_start = max(0, first_oos_pos - IS_WINDOW)
        is_data = features.iloc[is_start:first_oos_pos]
        n_is = len(is_data)

        print(f"  IS: {n_is} obs ({is_data.index[0].date()} to {is_data.index[-1].date()})")
        print(f"  OOS: {n_oos} obs ({oos_data.index[0].date()} to {oos_data.index[-1].date()})")

        if n_is < 500:
            print(f"  WARNING: IS < 500 obs, results may be unstable")

        # ---- Train models on IS ----
        y_is = is_data['target_abs_ret'].values
        y_oos = oos_data['target_abs_ret'].values
        y_oos_park = oos_data['target_parkinson'].values

        # M1: Baseline (RV21)
        X_is_m1 = sm.add_constant(is_data[['rv_21']].values)
        m1_fit = sm.OLS(y_is, X_is_m1).fit()
        X_oos_m1 = sm.add_constant(oos_data[['rv_21']].values)
        pred_m1 = np.maximum(m1_fit.predict(X_oos_m1), 1e-12)
        m1_r2_is = float(m1_fit.rsquared)

        # M2: RS⁻_21
        X_is_m2 = sm.add_constant(is_data[['rs_neg_21']].values)
        m2_fit = sm.OLS(y_is, X_is_m2).fit()
        X_oos_m2 = sm.add_constant(oos_data[['rs_neg_21']].values)
        pred_m2 = np.maximum(m2_fit.predict(X_oos_m2), 1e-12)
        m2_r2_is = float(m2_fit.rsquared)
        m2_coef = float(m2_fit.params[1])
        m2_tstat = float(m2_fit.tvalues[1])

        # M3: HAR-semi (RS⁻_5 + RS⁻_21 + RS⁺_5 + RS⁺_21)
        har_cols_idx = ['rs_neg_5', 'rs_neg_21', 'rs_pos_5', 'rs_pos_21']
        X_is_m3 = sm.add_constant(is_data[har_cols_idx].values)
        m3_fit = sm.OLS(y_is, X_is_m3).fit()
        X_oos_m3 = sm.add_constant(oos_data[har_cols_idx].values)
        pred_m3 = np.maximum(m3_fit.predict(X_oos_m3), 1e-12)
        m3_r2_is = float(m3_fit.rsquared)

        # Extract HAR-semi IS coefficients
        har_coefs = {}
        har_tstats = {}
        for i, col in enumerate(har_cols_idx):
            har_coefs[col] = round(float(m3_fit.params[i + 1]), 8)
            har_tstats[col] = round(float(m3_fit.tvalues[i + 1]), 4)

        # M4: GJR-GARCH(1,1)
        # Fit on IS period returns
        is_ret_pct = ret.loc[is_data.index[0]:is_data.index[-1]] * 100
        is_ret_pct = is_ret_pct.dropna()
        pred_m4 = np.full(n_oos, np.nan)
        gjr_converged = False
        gjr_params = {}

        try:
            gjr_mod = arch_model(is_ret_pct, vol='GARCH', p=1, o=1, q=1,
                                 dist='t', mean='AR', lags=1)
            gjr_res = gjr_mod.fit(disp='off', options={'maxiter': 1000})

            if gjr_res.convergence_flag == 0:
                gjr_converged = True
                gjr_params = {
                    'alpha': round(float(gjr_res.params.get('alpha[1]', 0)), 6),
                    'gamma': round(float(gjr_res.params.get('gamma[1]', 0)), 6),
                    'beta': round(float(gjr_res.params.get('beta[1]', 0)), 6),
                }
                persistence = (gjr_params['alpha'] + gjr_params['gamma'] / 2
                               + gjr_params['beta'])
                gjr_params['persistence'] = round(persistence, 6)

                # Check persistence < 1
                if persistence >= 1.0:
                    print(f"  WARNING: GJR persistence={persistence:.4f} >= 1.0!")

                # Forecast OOS: rolling 1-step-ahead
                oos_ret_pct = ret.loc[oos_data.index[0]:oos_data.index[-1]] * 100
                oos_ret_pct = oos_ret_pct.dropna()

                # Combined IS+OOS returns for rolling forecast
                all_ret_pct = pd.concat([is_ret_pct, oos_ret_pct])
                oos_start_idx = len(is_ret_pct)

                # Re-fit on expanding window for GJR forecasts
                # For efficiency: fit once on IS, then use forecast()
                # arch package forecast: h-step ahead
                forecasts = gjr_res.forecast(horizon=1, start=None, reindex=False)
                # For rolling forecast, we need to use the conditional variance
                # from the last IS observation and recursively update

                # Alternative: use the fitted model's conditional variance
                # and extend into OOS using the recursion
                omega = gjr_res.params.get('omega', 0)
                alpha_p = gjr_res.params.get('alpha[1]', 0)
                gamma_p = gjr_res.params.get('gamma[1]', 0)
                beta_p = gjr_res.params.get('beta[1]', 0)

                # Get last IS conditional variance and residual
                cond_var = gjr_res.conditional_volatility ** 2
                last_var = float(cond_var.iloc[-1])
                last_resid = float(gjr_res.resid.iloc[-1])
                last_neg = 1.0 if last_resid < 0 else 0.0

                # Rolling 1-step forecast into OOS
                pred_m4_list = []
                h_t = last_var
                eps_prev = last_resid
                neg_prev = last_neg

                for i in range(n_oos):
                    # Forecast: h_{t+1} = omega + alpha*eps_t² + gamma*eps_t²*I(eps_t<0) + beta*h_t
                    h_next = omega + alpha_p * eps_prev**2 + gamma_p * eps_prev**2 * neg_prev + beta_p * h_t

                    # Convert from % variance to decimal variance
                    pred_var_decimal = h_next / (100 ** 2)
                    pred_abs_ret = np.sqrt(pred_var_decimal) * np.sqrt(2 / np.pi)
                    pred_m4_list.append(max(pred_abs_ret, 1e-12))

                    # Update with actual OOS return
                    if i < len(oos_ret_pct):
                        eps_prev = float(oos_ret_pct.iloc[i])
                        neg_prev = 1.0 if eps_prev < 0 else 0.0
                        h_t = h_next
                    else:
                        # Use forecast variance as substitute
                        eps_prev = 0.0
                        neg_prev = 0.0
                        h_t = h_next

                pred_m4 = np.array(pred_m4_list)
                print(f"  GJR-GARCH: converged, alpha={gjr_params['alpha']:.4f}, "
                      f"gamma={gjr_params['gamma']:.4f}, beta={gjr_params['beta']:.4f}, "
                      f"persist={gjr_params['persistence']:.4f}")
            else:
                print(f"  GJR-GARCH: FAILED TO CONVERGE (flag={gjr_res.convergence_flag})")
        except Exception as e:
            print(f"  GJR-GARCH: ERROR — {e}")

        # ---- Compute OOS errors ----
        e_m1 = y_oos - pred_m1
        e_m2 = y_oos - pred_m2
        e_m3 = y_oos - pred_m3
        valid_m4 = ~np.isnan(pred_m4)

        # ---- OOS R² ----
        ss_total = np.sum((y_oos - np.mean(y_oos)) ** 2)
        r2_oos_m1 = 1 - np.sum(e_m1 ** 2) / ss_total
        r2_oos_m2 = 1 - np.sum(e_m2 ** 2) / ss_total
        r2_oos_m3 = 1 - np.sum(e_m3 ** 2) / ss_total
        if valid_m4.all():
            e_m4 = y_oos - pred_m4
            r2_oos_m4 = 1 - np.sum(e_m4 ** 2) / ss_total
        else:
            e_m4 = np.full(n_oos, np.nan)
            r2_oos_m4 = np.nan

        # ---- QLIKE (Parkinson proxy, K441) ----
        # Use Parkinson as the "true" variance proxy
        park_proxy = np.maximum(y_oos_park, 1e-12)

        # For QLIKE, we need variance forecasts (pred² since we predict |r|)
        pred_var_m1 = pred_m1 ** 2
        pred_var_m2 = pred_m2 ** 2
        pred_var_m3 = pred_m3 ** 2
        pred_var_m4_arr = pred_m4 ** 2 if valid_m4.all() else np.full(n_oos, np.nan)

        ql_m1 = qlike_loss(park_proxy, pred_var_m1)
        ql_m2 = qlike_loss(park_proxy, pred_var_m2)
        ql_m3 = qlike_loss(park_proxy, pred_var_m3)
        if valid_m4.all():
            ql_m4 = qlike_loss(park_proxy, pred_var_m4_arr)
        else:
            ql_m4 = np.full(n_oos, np.nan)

        # ---- MSE (on |return|) ----
        mse_m1 = mse_loss(y_oos, pred_m1)
        mse_m2 = mse_loss(y_oos, pred_m2)
        mse_m3 = mse_loss(y_oos, pred_m3)
        if valid_m4.all():
            mse_m4 = mse_loss(y_oos, pred_m4)
        else:
            mse_m4 = np.full(n_oos, np.nan)

        # Mean losses
        mean_ql = {
            'M1_RV21': float(np.nanmean(ql_m1)),
            'M2_RS_neg': float(np.nanmean(ql_m2)),
            'M3_HAR_semi': float(np.nanmean(ql_m3)),
        }
        mean_mse = {
            'M1_RV21': float(np.nanmean(mse_m1)),
            'M2_RS_neg': float(np.nanmean(mse_m2)),
            'M3_HAR_semi': float(np.nanmean(mse_m3)),
        }
        if valid_m4.all():
            mean_ql['M4_GJR'] = float(np.nanmean(ql_m4))
            mean_mse['M4_GJR'] = float(np.nanmean(mse_m4))

        print(f"\n  QLIKE (Parkinson proxy, lower=better):")
        for m, v in sorted(mean_ql.items(), key=lambda x: x[1]):
            print(f"    {m:15s}: {v:.6f}")

        print(f"\n  MSE (|return|, lower=better):")
        for m, v in sorted(mean_mse.items(), key=lambda x: x[1]):
            print(f"    {m:15s}: {v:.4e}")

        print(f"\n  OOS R²:")
        print(f"    M1(RV21):    {r2_oos_m1:+.6f}")
        print(f"    M2(RS⁻):    {r2_oos_m2:+.6f}")
        print(f"    M3(HAR-semi):{r2_oos_m3:+.6f}")
        if not np.isnan(r2_oos_m4):
            print(f"    M4(GJR):     {r2_oos_m4:+.6f}")

        # ---- DM Tests ----
        # QLIKE-based DM tests
        dm_m2_vs_m1_ql = dm_test_losses(ql_m1, ql_m2)  # positive = M2 better
        dm_m3_vs_m1_ql = dm_test_losses(ql_m1, ql_m3)
        dm_m2_vs_m1_mse = dm_test_losses(mse_m1, mse_m2)
        dm_m3_vs_m1_mse = dm_test_losses(mse_m1, mse_m3)

        # RS⁻ vs GJR
        if valid_m4.all():
            dm_m2_vs_m4_ql = dm_test_losses(ql_m4, ql_m2)  # positive = M2 better than M4
            dm_m2_vs_m4_mse = dm_test_losses(mse_m4, mse_m2)
            dm_m3_vs_m4_ql = dm_test_losses(ql_m4, ql_m3)
        else:
            dm_m2_vs_m4_ql = (np.nan, np.nan)
            dm_m2_vs_m4_mse = (np.nan, np.nan)
            dm_m3_vs_m4_ql = (np.nan, np.nan)

        print(f"\n  DM Tests (positive t = alt model BETTER):")
        print(f"    RS⁻ vs Baseline (QLIKE): t={dm_m2_vs_m1_ql[0]:+.4f}, p={dm_m2_vs_m1_ql[1]:.4f}"
              f" {'***' if dm_m2_vs_m1_ql[1] < 0.01 else '**' if dm_m2_vs_m1_ql[1] < 0.05 else 'NS'}")
        print(f"    RS⁻ vs Baseline (MSE):   t={dm_m2_vs_m1_mse[0]:+.4f}, p={dm_m2_vs_m1_mse[1]:.4f}"
              f" {'***' if dm_m2_vs_m1_mse[1] < 0.01 else '**' if dm_m2_vs_m1_mse[1] < 0.05 else 'NS'}")
        print(f"    HAR vs Baseline (QLIKE):  t={dm_m3_vs_m1_ql[0]:+.4f}, p={dm_m3_vs_m1_ql[1]:.4f}"
              f" {'***' if dm_m3_vs_m1_ql[1] < 0.01 else '**' if dm_m3_vs_m1_ql[1] < 0.05 else 'NS'}")
        print(f"    HAR vs Baseline (MSE):    t={dm_m3_vs_m1_mse[0]:+.4f}, p={dm_m3_vs_m1_mse[1]:.4f}"
              f" {'***' if dm_m3_vs_m1_mse[1] < 0.01 else '**' if dm_m3_vs_m1_mse[1] < 0.05 else 'NS'}")
        if not np.isnan(dm_m2_vs_m4_ql[0]):
            print(f"    RS⁻ vs GJR (QLIKE):      t={dm_m2_vs_m4_ql[0]:+.4f}, p={dm_m2_vs_m4_ql[1]:.4f}"
                  f" {'***' if dm_m2_vs_m4_ql[1] < 0.01 else '**' if dm_m2_vs_m4_ql[1] < 0.05 else 'NS'}")
            print(f"    RS⁻ vs GJR (MSE):        t={dm_m2_vs_m4_mse[0]:+.4f}, p={dm_m2_vs_m4_mse[1]:.4f}"
                  f" {'***' if dm_m2_vs_m4_mse[1] < 0.01 else '**' if dm_m2_vs_m4_mse[1] < 0.05 else 'NS'}")
            print(f"    HAR vs GJR (QLIKE):      t={dm_m3_vs_m4_ql[0]:+.4f}, p={dm_m3_vs_m4_ql[1]:.4f}"
                  f" {'***' if dm_m3_vs_m4_ql[1] < 0.01 else '**' if dm_m3_vs_m4_ql[1] < 0.05 else 'NS'}")

        # ---- HAR-semi IS coefficients ----
        print(f"\n  HAR-semi IS coefficients:")
        for col in har_cols_idx:
            sig = "***" if abs(har_tstats[col]) > 3.0 else \
                  "**" if abs(har_tstats[col]) > 2.0 else "NS"
            print(f"    {col:>12}: coef={har_coefs[col]:+.8f}, t={har_tstats[col]:+.4f} {sig}")

        # IS R² comparison
        print(f"\n  IS R²: M1={m1_r2_is:.6f}, M2={m2_r2_is:.6f}, M3={m3_r2_is:.6f}")
        print(f"  IS R² gain (M2-M1): {m2_r2_is - m1_r2_is:+.6f}")
        print(f"  IS R² gain (M3-M1): {m3_r2_is - m1_r2_is:+.6f}")

        # Store
        period_result = {
            "name": pname,
            "oos_start": period["start"],
            "oos_end": period["end"],
            "n_is": n_is,
            "n_oos": n_oos,
            "is_r2": {"M1": round(m1_r2_is, 6), "M2": round(m2_r2_is, 6), "M3": round(m3_r2_is, 6)},
            "oos_r2": {
                "M1_RV21": round(r2_oos_m1, 6),
                "M2_RS_neg": round(r2_oos_m2, 6),
                "M3_HAR_semi": round(r2_oos_m3, 6),
                "M4_GJR": round(r2_oos_m4, 6) if not np.isnan(r2_oos_m4) else None,
            },
            "qlike": {k: round(v, 6) for k, v in mean_ql.items()},
            "mse": {k: round(v, 10) for k, v in mean_mse.items()},
            "qlike_ranking": sorted(mean_ql.items(), key=lambda x: x[1]),
            "mse_ranking": sorted(mean_mse.items(), key=lambda x: x[1]),
            "dm_tests": {
                "M2_vs_M1_qlike": {"t_stat": round(dm_m2_vs_m1_ql[0], 4), "p_value": round(dm_m2_vs_m1_ql[1], 6)},
                "M2_vs_M1_mse": {"t_stat": round(dm_m2_vs_m1_mse[0], 4), "p_value": round(dm_m2_vs_m1_mse[1], 6)},
                "M3_vs_M1_qlike": {"t_stat": round(dm_m3_vs_m1_ql[0], 4), "p_value": round(dm_m3_vs_m1_ql[1], 6)},
                "M3_vs_M1_mse": {"t_stat": round(dm_m3_vs_m1_mse[0], 4), "p_value": round(dm_m3_vs_m1_mse[1], 6)},
                "M2_vs_M4_qlike": {
                    "t_stat": round(dm_m2_vs_m4_ql[0], 4) if not np.isnan(dm_m2_vs_m4_ql[0]) else None,
                    "p_value": round(dm_m2_vs_m4_ql[1], 6) if not np.isnan(dm_m2_vs_m4_ql[1]) else None,
                },
                "M2_vs_M4_mse": {
                    "t_stat": round(dm_m2_vs_m4_mse[0], 4) if not np.isnan(dm_m2_vs_m4_mse[0]) else None,
                    "p_value": round(dm_m2_vs_m4_mse[1], 6) if not np.isnan(dm_m2_vs_m4_mse[1]) else None,
                },
                "M3_vs_M4_qlike": {
                    "t_stat": round(dm_m3_vs_m4_ql[0], 4) if not np.isnan(dm_m3_vs_m4_ql[0]) else None,
                    "p_value": round(dm_m3_vs_m4_ql[1], 6) if not np.isnan(dm_m3_vs_m4_ql[1]) else None,
                },
            },
            "har_semi_is_coefs": har_coefs,
            "har_semi_is_tstats": har_tstats,
            "m2_is_coef": round(m2_coef, 8),
            "m2_is_tstat": round(m2_tstat, 4),
            "gjr_params": gjr_params if gjr_converged else None,
            "gjr_converged": gjr_converged,
        }

        period_results[f"period_{p_idx + 1}"] = period_result

    # ============================
    # 3d. Cross-OOS Summary for this asset
    # ============================
    print(f"\n{'=' * 70}")
    print(f"  CROSS-OOS SUMMARY — {ticker}")
    print(f"{'=' * 70}")

    n_periods = len(period_results)
    n_m2_wins_ql = 0
    n_m2_wins_mse = 0
    n_m3_wins_ql = 0
    n_m3_wins_mse = 0
    n_m2_sig_ql = 0
    n_m2_sig_mse = 0
    n_m3_sig_ql = 0
    n_m3_sig_mse = 0
    n_m2_harvey_ql = 0
    n_m2_vs_gjr_wins = 0
    all_dm_m2_ql = []
    all_dm_m3_ql = []
    all_dm_m2_mse = []
    all_dm_m3_mse = []

    header = (f"{'Period':<30} {'QL best':>12} {'MSE best':>12} "
              f"{'DM(RS⁻/BL,QL)':>15} {'DM(HAR/BL,QL)':>15} {'RS⁻ vs GJR':>12}")
    print(f"\n{header}")
    print("-" * 100)

    for key, res in period_results.items():
        ql_rank = res['qlike_ranking']
        mse_rank = res['mse_ranking']
        ql_best = ql_rank[0][0]
        mse_best = mse_rank[0][0]

        dm_m2_ql = res['dm_tests']['M2_vs_M1_qlike']
        dm_m3_ql = res['dm_tests']['M3_vs_M1_qlike']
        dm_m2_mse_r = res['dm_tests']['M2_vs_M1_mse']
        dm_m3_mse_r = res['dm_tests']['M3_vs_M1_mse']
        dm_m2_gjr = res['dm_tests']['M2_vs_M4_qlike']

        # Count wins
        if 'M2' in ql_best:
            n_m2_wins_ql += 1
        if 'M2' in mse_best:
            n_m2_wins_mse += 1
        if 'M3' in ql_best:
            n_m3_wins_ql += 1
        if 'M3' in mse_best:
            n_m3_wins_mse += 1

        # Count significance (positive t = alt model better)
        if dm_m2_ql['p_value'] < 0.05 and dm_m2_ql['t_stat'] > 0:
            n_m2_sig_ql += 1
        if dm_m2_mse_r['p_value'] < 0.05 and dm_m2_mse_r['t_stat'] > 0:
            n_m2_sig_mse += 1
        if dm_m3_ql['p_value'] < 0.05 and dm_m3_ql['t_stat'] > 0:
            n_m3_sig_ql += 1
        if dm_m3_mse_r['p_value'] < 0.05 and dm_m3_mse_r['t_stat'] > 0:
            n_m3_sig_mse += 1

        # Harvey threshold (|t| > 3)
        if dm_m2_ql['p_value'] < 0.01 and abs(dm_m2_ql['t_stat']) > 3.0 and dm_m2_ql['t_stat'] > 0:
            n_m2_harvey_ql += 1

        # RS⁻ vs GJR
        if dm_m2_gjr['t_stat'] is not None and dm_m2_gjr['p_value'] is not None:
            if dm_m2_gjr['t_stat'] > 0 and dm_m2_gjr['p_value'] < 0.05:
                n_m2_vs_gjr_wins += 1

        all_dm_m2_ql.append(dm_m2_ql['t_stat'])
        all_dm_m3_ql.append(dm_m3_ql['t_stat'])
        all_dm_m2_mse.append(dm_m2_mse_r['t_stat'])
        all_dm_m3_mse.append(dm_m3_mse_r['t_stat'])

        # Format
        dm_m2_str = f"t={dm_m2_ql['t_stat']:+.3f} p={dm_m2_ql['p_value']:.3f}"
        dm_m3_str = f"t={dm_m3_ql['t_stat']:+.3f} p={dm_m3_ql['p_value']:.3f}"
        if dm_m2_gjr['t_stat'] is not None:
            gjr_str = f"t={dm_m2_gjr['t_stat']:+.3f}"
        else:
            gjr_str = "N/A"

        print(f"  {res['name']:<28} {ql_best:>12} {mse_best:>12} "
              f"{dm_m2_str:>15} {dm_m3_str:>15} {gjr_str:>12}")

    print("-" * 100)

    print(f"\n  RS⁻ (M2) wins QLIKE: {n_m2_wins_ql}/{n_periods}")
    print(f"  RS⁻ (M2) wins MSE:   {n_m2_wins_mse}/{n_periods}")
    print(f"  RS⁻ sig (p<0.05, QLIKE): {n_m2_sig_ql}/{n_periods}")
    print(f"  RS⁻ sig (p<0.05, MSE):   {n_m2_sig_mse}/{n_periods}")
    print(f"  RS⁻ Harvey (|t|>3, QLIKE): {n_m2_harvey_ql}/{n_periods}")
    print(f"  RS⁻ beats GJR (p<0.05): {n_m2_vs_gjr_wins}/{n_periods}")
    print(f"  HAR-semi wins QLIKE: {n_m3_wins_ql}/{n_periods}")
    print(f"  HAR-semi sig (p<0.05, QLIKE): {n_m3_sig_ql}/{n_periods}")
    print(f"  Mean DM t (RS⁻ vs BL, QLIKE): {np.mean(all_dm_m2_ql):.4f}")
    print(f"  Mean DM t (HAR vs BL, QLIKE):  {np.mean(all_dm_m3_ql):.4f}")

    # Verdict for this asset
    if n_m2_sig_ql >= 4:
        m2_verdict = "ROBUST: RS⁻ significantly better in ≥4/5 periods"
    elif n_m2_sig_ql >= 3:
        m2_verdict = "MODERATE: RS⁻ significantly better in 3/5 periods"
    elif n_m2_sig_ql >= 2:
        m2_verdict = "WEAK: RS⁻ significantly better in only 2/5 periods — period-specific"
    else:
        m2_verdict = "FAILED: RS⁻ NOT robust across periods (≤1/5 significant)"

    if n_m3_sig_ql >= 4:
        m3_verdict = "ROBUST: HAR-semi significantly better in ≥4/5 periods"
    elif n_m3_sig_ql >= 3:
        m3_verdict = "MODERATE: HAR-semi significantly better in 3/5 periods"
    elif n_m3_sig_ql >= 2:
        m3_verdict = "WEAK: HAR-semi period-specific (2/5)"
    else:
        m3_verdict = "FAILED: HAR-semi NOT robust (≤1/5 significant)"

    print(f"\n  VERDICT (RS⁻): {m2_verdict}")
    print(f"  VERDICT (HAR-semi): {m3_verdict}")

    # Also check: does RS⁻ win QLIKE ranking consistently even if not significant?
    # (i.e., directionally consistent even if DM not significant)
    n_m2_directionally_better_ql = sum(
        1 for k, r in period_results.items()
        if r['qlike']['M2_RS_neg'] < r['qlike']['M1_RV21']
    )
    print(f"  RS⁻ directionally better (QLIKE): {n_m2_directionally_better_ql}/{n_periods}")

    all_asset_results[ticker] = {
        'diagnostics': desc_stats,
        'period_results': period_results,
        'cross_oos_summary': {
            'n_periods': n_periods,
            'M2_RS_neg': {
                'wins_qlike': n_m2_wins_ql,
                'wins_mse': n_m2_wins_mse,
                'sig_qlike_p05': n_m2_sig_ql,
                'sig_mse_p05': n_m2_sig_mse,
                'harvey_qlike_t3': n_m2_harvey_ql,
                'beats_gjr_p05': n_m2_vs_gjr_wins,
                'directionally_better_qlike': n_m2_directionally_better_ql,
                'mean_dm_t_qlike': round(float(np.mean(all_dm_m2_ql)), 4),
                'mean_dm_t_mse': round(float(np.mean(all_dm_m2_mse)), 4),
                'verdict': m2_verdict,
            },
            'M3_HAR_semi': {
                'wins_qlike': n_m3_wins_ql,
                'wins_mse': n_m3_wins_mse,
                'sig_qlike_p05': n_m3_sig_ql,
                'sig_mse_p05': n_m3_sig_mse,
                'mean_dm_t_qlike': round(float(np.mean(all_dm_m3_ql)), 4),
                'mean_dm_t_mse': round(float(np.mean(all_dm_m3_mse)), 4),
                'verdict': m3_verdict,
            },
            'all_dm_t_m2_qlike': [round(x, 4) for x in all_dm_m2_ql],
            'all_dm_t_m3_qlike': [round(x, 4) for x in all_dm_m3_ql],
            'all_dm_t_m2_mse': [round(x, 4) for x in all_dm_m2_mse],
            'all_dm_t_m3_mse': [round(x, 4) for x in all_dm_m3_mse],
        },
    }


# ============================================================
# 4. FINAL CROSS-ASSET COMPARISON
# ============================================================
print(f"\n{'#' * 70}")
print(f"# FINAL CROSS-ASSET COMPARISON")
print(f"{'#' * 70}")

for ticker, res in all_asset_results.items():
    summary = res['cross_oos_summary']
    print(f"\n  {ticker}:")
    print(f"    RS⁻ verdict: {summary['M2_RS_neg']['verdict']}")
    print(f"    HAR-semi verdict: {summary['M3_HAR_semi']['verdict']}")
    print(f"    RS⁻ sig QLIKE: {summary['M2_RS_neg']['sig_qlike_p05']}/5")
    print(f"    RS⁻ beats GJR: {summary['M2_RS_neg']['beats_gjr_p05']}/5")
    print(f"    Mean DM t (RS⁻ vs BL): {summary['M2_RS_neg']['mean_dm_t_qlike']:.4f}")

# Publication readiness assessment
print(f"\n{'=' * 70}")
print("  PUBLICATION READINESS ASSESSMENT")
print(f"{'=' * 70}")

spy_summary = all_asset_results.get('SPY', {}).get('cross_oos_summary', {})
qqq_summary = all_asset_results.get('QQQ', {}).get('cross_oos_summary', {})

spy_sig = spy_summary.get('M2_RS_neg', {}).get('sig_qlike_p05', 0)
qqq_sig = qqq_summary.get('M2_RS_neg', {}).get('sig_qlike_p05', 0)

if spy_sig >= 4 and qqq_sig >= 3:
    pub_verdict = "PUBLICATION READY: Semivariance finding is robust across periods and assets"
elif spy_sig >= 3:
    pub_verdict = "CONDITIONAL: RS⁻ moderately robust for SPY, additional conditions needed"
elif spy_sig >= 2:
    pub_verdict = "NEEDS DOWNGRADE: K449 finding (p=0.007) is period-specific, like VRP (K459)"
else:
    pub_verdict = "REJECTED: Semivariance advantage is NOT robust. K449 was an artifact."

print(f"\n  SPY RS⁻ significant periods: {spy_sig}/5")
print(f"  QQQ RS⁻ significant periods: {qqq_sig}/5")
print(f"\n  FINAL VERDICT: {pub_verdict}")

if spy_sig < 4:
    print(f"\n  ⚠️ K449's p=0.007 may have been driven by specific period(s).")
    print(f"     Check which periods drive significance and which don't.")
    print(f"     If only 2023-2025 is significant → likely artifact (same issue as VRP K459).")


# ============================================================
# 5. SAVE RESULTS
# ============================================================
print("\n[SAVE] Writing results...")

final_output = {
    "experiment_id": "K460",
    "title": "Semivariance Cross-OOS Validation (5 Periods × 2 Assets)",
    "date": datetime.now(timezone.utc).isoformat(),
    "data_source": "yfinance",
    "methodology": {
        "is_window": IS_WINDOW,
        "oos_periods": OOS_PERIODS,
        "models": {
            "M1_RV21": "OLS: next-day |return| ~ const + RV_21(lagged)",
            "M2_RS_neg": "OLS: next-day |return| ~ const + RS⁻_21(lagged)",
            "M3_HAR_semi": "OLS: next-day |return| ~ const + RS⁻_5 + RS⁻_21 + RS⁺_5 + RS⁺_21 (all lagged)",
            "M4_GJR": "GJR-GARCH(1,1) with t-dist, 1-step ahead rolling forecast",
        },
        "metrics": ["QLIKE (Parkinson proxy)", "MSE (|return|)", "OOS R²"],
        "significance": "Diebold-Mariano test with HAC variance",
        "parkinson_proxy": "σ² = [ln(H/L)]² / (4*ln2) — K441 recommendation for unbiased vol proxy",
    },
    "assets": {},
    "publication_verdict": pub_verdict,
    "comparison_with_K449": {
        "k449_claim": "RS⁻ significantly beats RV for SPY (DM p=0.007)",
        "k449_oos_period": "2023-2025 only (single period)",
        "k460_verdict": pub_verdict,
        "spy_sig_periods": spy_sig,
        "qqq_sig_periods": qqq_sig,
    },
    "comparison_with_K459": {
        "k459_finding": "VRP weekly significance NOT robust across periods",
        "k460_question": "Does semivariance daily share the same fragility?",
        "answer": "See per-period results",
    },
    "limitations": [
        "Only 2 assets tested (SPY, QQQ) — both US large-cap equities",
        "Daily frequency — may differ at weekly/monthly horizons",
        "Parkinson proxy assumes no overnight gaps (approximation for daily data)",
        "GJR-GARCH forecast uses recursive update (not re-estimation per day)",
        "OLS models are single-feature regressions (parsimonious but limited)",
        "Harvey (2016) threshold t>3.0 not applied to DM tests (standard 5% used for counting)",
    ],
}

# Add per-asset results (clean for JSON)
for ticker, res in all_asset_results.items():
    asset_data = dict(res)
    # Clean period results for JSON serialization
    for pk, pv in asset_data.get('period_results', {}).items():
        if 'qlike_ranking' in pv:
            pv['qlike_ranking'] = [[k, v] for k, v in pv['qlike_ranking']]
        if 'mse_ranking' in pv:
            pv['mse_ranking'] = [[k, v] for k, v in pv['mse_ranking']]
    final_output['assets'][ticker] = asset_data

output_path = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a989d08d/experiments/k460_semivar_cross_oos_results.json'
with open(output_path, 'w') as f:
    json.dump(final_output, f, indent=2, default=str)

print(f"  Saved to: {output_path}")
print(f"\n  FINAL VERDICT: {pub_verdict}")
print("\nK460 complete.")
