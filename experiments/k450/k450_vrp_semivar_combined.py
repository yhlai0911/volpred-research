"""
K450: Combined VRP + Semivariance Model for Volatility Prediction

Background:
  K436: VRP (VIX - RV21) confirmed as daily vol predictor (DM p=0.018, bootstrap p=0.000)
  K449: RS⁻ (bad vol) significantly beats RV for SPY (DM p=0.007), HAR-semi R²=0.148 vs RV 0.027

Hypothesis:
  VRP captures forward-looking risk premium (options market information).
  RS⁻ captures backward-looking asymmetry (bad vs good news vol differential).
  These are orthogonal information dimensions — combining them may yield synergistic improvement.

Literature:
  - Bollerslev, Tauchen, Zhou (2009) RFS — VRP predicts excess returns
  - Patton & Sheppard (2015) — Semivariance decomposition
  - No direct combined model in literature → original contribution

Data: yfinance (SPY, QQQ, ^VIX), 2005-01-01 to present
OOS: 2023-01-01 to 2025-12-31
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
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
from sklearn.linear_model import Ridge

warnings.filterwarnings('ignore')

print("=" * 70)
print("K450: Combined VRP + Semivariance Model")
print("  Synergy test: forward-looking VRP × backward-looking RS⁻")
print("=" * 70)

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("\n[1] Downloading data...")
spy_raw = yf.download('SPY', start='2005-01-01', progress=False)
qqq_raw = yf.download('QQQ', start='2005-01-01', progress=False)
vix_raw = yf.download('^VIX', start='2005-01-01', progress=False)

# Handle MultiIndex columns
for df_raw in [spy_raw, qqq_raw, vix_raw]:
    if isinstance(df_raw.columns, pd.MultiIndex):
        df_raw.columns = df_raw.columns.get_level_values(0)

print(f"  SPY: {spy_raw.index[0].date()} to {spy_raw.index[-1].date()} ({len(spy_raw)} obs)")
print(f"  QQQ: {qqq_raw.index[0].date()} to {qqq_raw.index[-1].date()} ({len(qqq_raw)} obs)")
print(f"  VIX: {vix_raw.index[0].date()} to {vix_raw.index[-1].date()} ({len(vix_raw)} obs)")


def build_features(price_df, vix_df, asset_name):
    """Build VRP + Semivariance features for a given asset."""
    ret = price_df['Close'].pct_change()

    # === Realized Volatility ===
    rv_5 = ret.rolling(5).std() * np.sqrt(252) * 100
    rv_21 = ret.rolling(21).std() * np.sqrt(252) * 100

    # === VIX and VRP ===
    vix_close = vix_df['Close'].reindex(price_df.index)
    vrp = vix_close - rv_21  # Variance Risk Premium
    vrp_lagged = vrp.shift(1)

    # === Semivariance features (Patton & Sheppard 2015) ===
    ret_vals = ret.values
    # Negative semivariance: squared returns when ret < 0
    rs_neg = np.where(ret_vals < 0, ret_vals ** 2, 0.0)
    # Positive semivariance: squared returns when ret >= 0
    rs_pos = np.where(ret_vals >= 0, ret_vals ** 2, 0.0)

    rs_neg_s = pd.Series(rs_neg, index=price_df.index)
    rs_pos_s = pd.Series(rs_pos, index=price_df.index)

    # Rolling semivariances (annualized, in % units)
    rs_neg_5 = rs_neg_s.rolling(5).mean() * 252 * 100  # annualized %²
    rs_neg_21 = rs_neg_s.rolling(21).mean() * 252 * 100
    rs_pos_5 = rs_pos_s.rolling(5).mean() * 252 * 100
    rs_pos_21 = rs_pos_s.rolling(21).mean() * 252 * 100

    # Asymmetry ratio: RS⁻ / RS⁺ (>1 means more bad vol)
    asym_ratio = rs_neg_21 / (rs_pos_21 + 1e-10)

    # === Target: next-day absolute return (in %, no overlap) ===
    abs_ret_next = ret.abs().shift(-1) * 100

    # === Target: next 21-day RV (for 21-day horizon) ===
    rv_21_future = ret.rolling(21).std().shift(-21) * np.sqrt(252) * 100

    df = pd.DataFrame({
        'ret': ret,
        'rv_5': rv_5,
        'rv_21': rv_21,
        'vix': vix_close,
        'vrp': vrp,
        'vrp_lagged': vrp_lagged,
        'rs_neg_5': rs_neg_5,
        'rs_neg_21': rs_neg_21,
        'rs_pos_5': rs_pos_5,
        'rs_pos_21': rs_pos_21,
        'asym_ratio': asym_ratio,
        'abs_ret_next': abs_ret_next,
        'rv_21_future': rv_21_future,
    }, index=price_df.index)

    return df


# ============================================================
# 2. DESCRIPTIVE STATISTICS & DIAGNOSTICS
# ============================================================
def run_diagnostics(df, asset_name):
    """Pre-estimation diagnostics: descriptive stats, ADF, ARCH LM."""
    print(f"\n{'='*60}")
    print(f"  Diagnostics for {asset_name}")
    print(f"{'='*60}")

    diag = {}

    key_vars = ['vrp', 'rs_neg_21', 'rs_pos_21', 'asym_ratio', 'abs_ret_next']
    for var in key_vars:
        s = df[var].dropna()
        desc = {
            'mean': float(s.mean()),
            'std': float(s.std()),
            'skew': float(s.skew()),
            'kurtosis': float(s.kurtosis()),
            'min': float(s.min()),
            'max': float(s.max()),
            'N': int(len(s)),
        }
        # ADF test
        try:
            adf_stat, adf_pval, _, _, _, _ = adfuller(s, maxlag=21)
            desc['adf_stat'] = float(adf_stat)
            desc['adf_pval'] = float(adf_pval)
        except:
            desc['adf_stat'] = None
            desc['adf_pval'] = None

        diag[var] = desc
        print(f"\n  {var}: mean={desc['mean']:.4f}, std={desc['std']:.4f}, "
              f"skew={desc['skew']:.2f}, kurt={desc['kurtosis']:.2f}, N={desc['N']}")
        if desc['adf_pval'] is not None:
            print(f"    ADF: stat={desc['adf_stat']:.3f}, p={desc['adf_pval']:.4f} "
                  f"{'[stationary]' if desc['adf_pval'] < 0.05 else '[non-stationary!]'}")

    # ARCH LM test on returns
    ret_clean = df['ret'].dropna()
    try:
        arch_lm = het_arch(ret_clean, nlags=5)
        diag['arch_lm'] = {'stat': float(arch_lm[0]), 'pval': float(arch_lm[1])}
        print(f"\n  ARCH LM (returns): stat={arch_lm[0]:.2f}, p={arch_lm[1]:.4f}")
    except:
        diag['arch_lm'] = None

    # Ljung-Box on absolute returns
    abs_ret = ret_clean.abs()
    try:
        lb = acorr_ljungbox(abs_ret, lags=[10], return_df=True)
        lb_stat = float(lb['lb_stat'].values[0])
        lb_pval = float(lb['lb_pvalue'].values[0])
        diag['ljung_box_abs_ret'] = {'stat': lb_stat, 'pval': lb_pval}
        print(f"  Ljung-Box (|ret|, lag=10): stat={lb_stat:.2f}, p={lb_pval:.4f}")
    except:
        diag['ljung_box_abs_ret'] = None

    # Correlation matrix between VRP and semivariance features
    corr_vars = ['vrp_lagged', 'rs_neg_5', 'rs_neg_21', 'rs_pos_5', 'rs_pos_21', 'asym_ratio']
    corr_df = df[corr_vars].dropna()
    corr_matrix = corr_df.corr()

    print(f"\n  Feature correlations (VRP vs Semivariance):")
    print(f"    vrp_lagged ↔ rs_neg_21: {corr_matrix.loc['vrp_lagged', 'rs_neg_21']:.3f}")
    print(f"    vrp_lagged ↔ rs_pos_21: {corr_matrix.loc['vrp_lagged', 'rs_pos_21']:.3f}")
    print(f"    vrp_lagged ↔ asym_ratio: {corr_matrix.loc['vrp_lagged', 'asym_ratio']:.3f}")
    print(f"    rs_neg_21 ↔ rs_pos_21: {corr_matrix.loc['rs_neg_21', 'rs_pos_21']:.3f}")

    diag['feature_correlations'] = {
        'vrp_lagged_vs_rs_neg_21': float(corr_matrix.loc['vrp_lagged', 'rs_neg_21']),
        'vrp_lagged_vs_rs_pos_21': float(corr_matrix.loc['vrp_lagged', 'rs_pos_21']),
        'vrp_lagged_vs_asym_ratio': float(corr_matrix.loc['vrp_lagged', 'asym_ratio']),
        'rs_neg_21_vs_rs_pos_21': float(corr_matrix.loc['rs_neg_21', 'rs_pos_21']),
    }

    return diag


# ============================================================
# 3. MODEL DEFINITIONS
# ============================================================
def ols_forecast_expanding(df, features, target, oos_start, min_train=504):
    """
    Expanding window OLS forecast.
    Returns forecast series, actual series, and IS diagnostics.
    """
    oos_mask = df.index >= oos_start
    cols = features + [target]
    clean = df[cols].dropna()

    oos_idx = clean.index[clean.index >= oos_start]

    forecasts = []
    actuals = []
    dates = []

    for i, date in enumerate(oos_idx):
        pos = clean.index.get_loc(date)
        if pos < min_train:
            continue

        train = clean.iloc[:pos]
        X_train = train[features].values
        y_train = train[target].values
        X_test = clean.loc[date, features].values.reshape(1, -1)
        y_test = clean.loc[date, target]

        # Add constant (manually for X_test to avoid sm.add_constant single-row bug)
        X_train_c = sm.add_constant(X_train)
        X_test_c = np.hstack([np.ones((1, 1)), X_test])

        try:
            model = sm.OLS(y_train, X_train_c).fit()
            yhat = model.predict(X_test_c)[0]
            # Ensure non-negative vol forecast
            yhat = max(yhat, 0.01)
            forecasts.append(yhat)
            actuals.append(y_test)
            dates.append(date)
        except:
            continue

    return pd.Series(forecasts, index=dates), pd.Series(actuals, index=dates)


def ridge_forecast_expanding(df, features, target, oos_start, min_train=504, alpha=1.0):
    """
    Expanding window Ridge regression forecast.
    """
    oos_mask = df.index >= oos_start
    cols = features + [target]
    clean = df[cols].dropna()

    oos_idx = clean.index[clean.index >= oos_start]

    forecasts = []
    actuals = []
    dates = []

    for i, date in enumerate(oos_idx):
        pos = clean.index.get_loc(date)
        if pos < min_train:
            continue

        train = clean.iloc[:pos]
        X_train = train[features].values
        y_train = train[target].values
        X_test = clean.loc[date, features].values.reshape(1, -1)
        y_test = clean.loc[date, target]

        try:
            model = Ridge(alpha=alpha)
            model.fit(X_train, y_train)
            yhat = model.predict(X_test)[0]
            yhat = max(yhat, 0.01)
            forecasts.append(yhat)
            actuals.append(y_test)
            dates.append(date)
        except:
            continue

    return pd.Series(forecasts, index=dates), pd.Series(actuals, index=dates)


def gjr_garch_forecast(price_df, oos_start):
    """GJR-GARCH(1,1) expanding window forecast."""
    from arch import arch_model

    ret = price_df['Close'].pct_change().dropna() * 100  # in %
    oos_idx = ret.index[ret.index >= oos_start]

    forecasts = []
    actuals = []
    dates = []

    # Use monthly reestimation for speed
    last_model_params = None
    reestimate_every = 21
    count = 0

    for date in oos_idx:
        pos = ret.index.get_loc(date)
        if pos < 504:
            continue

        train = ret.iloc[:pos]
        actual_abs = abs(ret.iloc[pos]) if pos < len(ret) else None

        if actual_abs is None:
            continue

        if count % reestimate_every == 0 or last_model_params is None:
            try:
                am = arch_model(train, vol='GARCH', p=1, o=1, q=1, dist='t', mean='Zero')
                res = am.fit(disp='off', show_warning=False)
                last_model_params = res
            except:
                if last_model_params is None:
                    continue

        try:
            fcast = last_model_params.forecast(horizon=1, reindex=False)
            cond_vol = np.sqrt(fcast.variance.values[-1, 0])
            # Convert from % to daily absolute return scale
            forecasts.append(cond_vol)
            actuals.append(actual_abs)
            dates.append(date)
        except:
            continue

        count += 1

    return pd.Series(forecasts, index=dates), pd.Series(actuals, index=dates)


# ============================================================
# 4. EVALUATION METRICS
# ============================================================
def qlike(actual, forecast):
    """QLIKE loss: actual/forecast - log(actual/forecast) - 1
    Filters out actual=0 (zero return days) to avoid log(0)."""
    mask = actual > 0
    a = actual[mask]
    f = forecast[mask]
    ratio = a / f
    return np.mean(ratio - np.log(ratio) - 1)


def mse(actual, forecast):
    """Mean Squared Error."""
    return np.mean((actual - forecast) ** 2)


def r2_oos(actual, forecast):
    """Out-of-sample R² (Campbell & Thompson 2008)."""
    ss_res = np.sum((actual - forecast) ** 2)
    ss_tot = np.sum((actual - actual.mean()) ** 2)
    return 1 - ss_res / ss_tot


def dm_test(loss1, loss2, h=1):
    """
    Diebold-Mariano test with HAC (Newey-West) standard errors.
    H0: loss1 = loss2, H1: loss1 != loss2
    Returns t-stat, p-value
    """
    d = loss1 - loss2
    n = len(d)

    # HAC bandwidth (Newey-West)
    lag = int(np.ceil(4 * (n / 100) ** (2/9)))
    lag = max(lag, h)

    d_mean = d.mean()

    # HAC variance (Newey-West)
    gamma_0 = np.mean((d - d_mean) ** 2)
    gamma_sum = 0
    for k in range(1, lag + 1):
        w = 1 - k / (lag + 1)  # Bartlett kernel
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        gamma_sum += 2 * w * gamma_k

    var_d = (gamma_0 + gamma_sum) / n

    if var_d <= 0:
        return 0.0, 1.0

    t_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))

    return float(t_stat), float(p_value)


def block_bootstrap_pvalue(loss1, loss2, n_bootstrap=10000, block_size=21, seed=42):
    """
    Block bootstrap test for loss difference.
    H0: E[loss1 - loss2] = 0
    """
    rng = np.random.RandomState(seed)
    d = (loss1 - loss2).values
    n = len(d)
    observed_mean = d.mean()

    n_blocks = int(np.ceil(n / block_size))
    boot_means = np.zeros(n_bootstrap)

    for b in range(n_bootstrap):
        # Centered residuals for bootstrap under H0
        d_centered = d - observed_mean
        starts = rng.randint(0, n - block_size + 1, size=n_blocks)
        boot_sample = np.concatenate([d_centered[s:s + block_size] for s in starts])[:n]
        boot_means[b] = boot_sample.mean()

    # Two-sided p-value
    p_value = np.mean(np.abs(boot_means) >= np.abs(observed_mean))

    return float(p_value)


def forecast_encompassing(loss1, loss2, forecast1, forecast2, actual):
    """
    Forecast encompassing test (Fair & Shiller 1990).
    Regress actual on forecast1 and forecast2.
    If forecast2 coefficient is significant, forecast1 does NOT encompass forecast2.
    Returns: lambda (weight on forecast2), t-stat for lambda, p-value
    """
    X = np.column_stack([forecast1.values, forecast2.values])
    X_c = sm.add_constant(X)
    y = actual.values

    try:
        model = sm.OLS(y, X_c).fit(cov_type='HAC', cov_kwds={'maxlags': 21})
        lambda_coef = model.params[2]
        t_stat = model.tvalues[2]
        p_value = model.pvalues[2]
        return float(lambda_coef), float(t_stat), float(p_value)
    except:
        return None, None, None


# ============================================================
# 5. MAIN ANALYSIS FOR EACH ASSET
# ============================================================
def analyze_asset(price_df, vix_df, asset_name, oos_start='2023-01-01'):
    """Run full 7-model comparison for one asset."""

    print(f"\n{'#'*70}")
    print(f"# ASSET: {asset_name}")
    print(f"{'#'*70}")

    # Build features
    df = build_features(price_df, vix_df, asset_name)

    # Diagnostics
    diag = run_diagnostics(df, asset_name)

    # ============================================================
    # Define 7 models
    # ============================================================
    # Target: daily |return| (next day), no overlap issue
    target = 'abs_ret_next'

    models = {
        'M1_rv21_only': ['rv_21'],
        'M2_vrp_only': ['vrp_lagged', 'rv_21'],
        'M3_semi_only': ['rs_neg_5', 'rs_neg_21', 'rs_pos_5', 'rs_pos_21'],
        'M4_vrp_semi_combined': ['vrp_lagged', 'rs_neg_5', 'rs_neg_21', 'rs_pos_5', 'rs_pos_21'],
        'M5_kitchen_sink': ['vrp_lagged', 'vix', 'rs_neg_5', 'rs_neg_21', 'rs_pos_5', 'rs_pos_21', 'asym_ratio'],
    }

    print(f"\n[3] Running 7 models (OOS from {oos_start})...")

    results = {}
    forecasts_dict = {}
    actuals_dict = {}

    # Models 1-5: OLS
    for model_name, features in models.items():
        print(f"  {model_name}: {features}")
        fc, ac = ols_forecast_expanding(df, features, target, oos_start)

        if len(fc) < 50:
            print(f"    WARNING: Only {len(fc)} OOS observations, skipping")
            continue

        q = qlike(ac, fc)
        m = mse(ac, fc)
        r2 = r2_oos(ac, fc)

        results[model_name] = {
            'features': features,
            'n_oos': int(len(fc)),
            'qlike': float(q),
            'mse': float(m),
            'r2_oos': float(r2),
        }
        forecasts_dict[model_name] = fc
        actuals_dict[model_name] = ac

        print(f"    QLIKE={q:.4f}, MSE={m:.4f}, R²_OOS={r2:.4f}, N_oos={len(fc)}")

    # Model 6: GJR-GARCH
    print(f"  M6_gjr_garch: GJR-GARCH(1,1,1)")
    try:
        fc_gjr, ac_gjr = gjr_garch_forecast(price_df, oos_start)
        if len(fc_gjr) >= 50:
            q = qlike(ac_gjr, fc_gjr)
            m = mse(ac_gjr, fc_gjr)
            r2 = r2_oos(ac_gjr, fc_gjr)
            results['M6_gjr_garch'] = {
                'features': ['GJR-GARCH(1,1,1)'],
                'n_oos': int(len(fc_gjr)),
                'qlike': float(q),
                'mse': float(m),
                'r2_oos': float(r2),
            }
            forecasts_dict['M6_gjr_garch'] = fc_gjr
            actuals_dict['M6_gjr_garch'] = ac_gjr
            print(f"    QLIKE={q:.4f}, MSE={m:.4f}, R²_OOS={r2:.4f}, N_oos={len(fc_gjr)}")
        else:
            print(f"    WARNING: Only {len(fc_gjr)} OOS observations")
    except Exception as e:
        print(f"    ERROR: {e}")

    # Model 7: Ridge with all features
    print(f"  M7_ridge_all: Ridge(alpha=1.0)")
    all_features = ['vrp_lagged', 'rv_5', 'rv_21', 'vix',
                    'rs_neg_5', 'rs_neg_21', 'rs_pos_5', 'rs_pos_21', 'asym_ratio']
    fc_ridge, ac_ridge = ridge_forecast_expanding(df, all_features, target, oos_start)
    if len(fc_ridge) >= 50:
        q = qlike(ac_ridge, fc_ridge)
        m = mse(ac_ridge, fc_ridge)
        r2 = r2_oos(ac_ridge, fc_ridge)
        results['M7_ridge_all'] = {
            'features': all_features,
            'n_oos': int(len(fc_ridge)),
            'qlike': float(q),
            'mse': float(m),
            'r2_oos': float(r2),
        }
        forecasts_dict['M7_ridge_all'] = fc_ridge
        actuals_dict['M7_ridge_all'] = ac_ridge
        print(f"    QLIKE={q:.4f}, MSE={m:.4f}, R²_OOS={r2:.4f}, N_oos={len(fc_ridge)}")

    # ============================================================
    # Pairwise DM tests + Bootstrap
    # ============================================================
    print(f"\n[4] DM Tests & Bootstrap (block=21, 10000 reps)...")

    dm_results = {}
    bootstrap_results = {}

    # Key comparisons
    comparisons = [
        ('M4_vrp_semi_combined', 'M1_rv21_only', 'Combined vs Baseline'),
        ('M4_vrp_semi_combined', 'M2_vrp_only', 'Combined vs VRP-only'),
        ('M4_vrp_semi_combined', 'M3_semi_only', 'Combined vs Semi-only'),
        ('M2_vrp_only', 'M1_rv21_only', 'VRP vs Baseline'),
        ('M3_semi_only', 'M1_rv21_only', 'Semi vs Baseline'),
        ('M2_vrp_only', 'M3_semi_only', 'VRP vs Semi'),
        ('M5_kitchen_sink', 'M4_vrp_semi_combined', 'Kitchen Sink vs Combined'),
    ]

    # Add GJR comparisons if available
    if 'M6_gjr_garch' in forecasts_dict:
        comparisons.append(('M4_vrp_semi_combined', 'M6_gjr_garch', 'Combined vs GJR-GARCH'))
    if 'M7_ridge_all' in forecasts_dict:
        comparisons.append(('M4_vrp_semi_combined', 'M7_ridge_all', 'Combined vs Ridge'))

    for m_a, m_b, label in comparisons:
        if m_a not in forecasts_dict or m_b not in forecasts_dict:
            continue

        # Align dates
        common_idx = forecasts_dict[m_a].index.intersection(forecasts_dict[m_b].index)
        if len(common_idx) < 50:
            continue

        fc_a = forecasts_dict[m_a].reindex(common_idx)
        fc_b = forecasts_dict[m_b].reindex(common_idx)
        ac = actuals_dict[m_a].reindex(common_idx)

        # QLIKE losses (filter out actual=0 to avoid log(0))
        valid = ac > 0
        fc_a = fc_a[valid]
        fc_b = fc_b[valid]
        ac = ac[valid]
        loss_a = ac / fc_a - np.log(ac / fc_a) - 1
        loss_b = ac / fc_b - np.log(ac / fc_b) - 1

        t_stat, p_val = dm_test(loss_a, loss_b, h=1)
        boot_p = block_bootstrap_pvalue(loss_a, loss_b, n_bootstrap=10000, block_size=21)

        key = f"{m_a}_vs_{m_b}"
        dm_results[key] = {
            'label': label,
            'dm_t': t_stat,
            'dm_p': p_val,
            'mean_loss_diff': float((loss_a - loss_b).mean()),
            'n_common': int(len(common_idx)),
        }
        bootstrap_results[key] = {
            'label': label,
            'boot_p': boot_p,
        }

        sig = '***' if p_val < 0.01 else '**' if p_val < 0.05 else '*' if p_val < 0.10 else ''
        harvey_pass = '✓ Harvey' if abs(t_stat) > 3.0 else ''
        print(f"  {label}: DM t={t_stat:.3f}, p={p_val:.4f}{sig} | Boot p={boot_p:.4f} | {harvey_pass}")

    # ============================================================
    # Forecast Encompassing Tests
    # ============================================================
    print(f"\n[5] Forecast Encompassing Tests...")

    encompassing = {}
    encomp_pairs = [
        ('M2_vrp_only', 'M3_semi_only', 'VRP encompassed by Semi?'),
        ('M3_semi_only', 'M2_vrp_only', 'Semi encompassed by VRP?'),
    ]

    for m_base, m_add, label in encomp_pairs:
        if m_base not in forecasts_dict or m_add not in forecasts_dict:
            continue

        common_idx = forecasts_dict[m_base].index.intersection(forecasts_dict[m_add].index)
        if len(common_idx) < 50:
            continue

        fc_base = forecasts_dict[m_base].reindex(common_idx)
        fc_add = forecasts_dict[m_add].reindex(common_idx)
        ac = actuals_dict[m_base].reindex(common_idx)

        lam, t, p = forecast_encompassing(None, None, fc_base, fc_add, ac)

        if lam is not None:
            encompassing[f"{m_base}_add_{m_add}"] = {
                'label': label,
                'lambda': lam,
                't_stat': t,
                'p_value': p,
            }
            sig = '***' if p < 0.01 else '**' if p < 0.05 else '*' if p < 0.10 else ''
            print(f"  {label}: λ={lam:.4f}, t={t:.3f}, p={p:.4f}{sig}")
            if p < 0.05:
                print(f"    → {m_add} adds significant info beyond {m_base}")
            else:
                print(f"    → {m_add} does NOT add significant info beyond {m_base}")

    # ============================================================
    # 21-day horizon test (as robustness)
    # ============================================================
    print(f"\n[6] 21-day horizon test (monthly non-overlapping)...")

    target_21d = 'rv_21_future'
    models_21d = {
        'M1_rv21_21d': ['rv_21'],
        'M2_vrp_21d': ['vrp_lagged', 'rv_21'],
        'M3_semi_21d': ['rs_neg_21', 'rs_pos_21'],
        'M4_combined_21d': ['vrp_lagged', 'rs_neg_21', 'rs_pos_21'],
    }

    results_21d = {}
    for model_name, features in models_21d.items():
        fc, ac = ols_forecast_expanding(df, features, target_21d, oos_start)

        # Non-overlapping: take every 21st obs
        if len(fc) > 21:
            fc_no = fc.iloc[::21]
            ac_no = ac.iloc[::21]
        else:
            fc_no = fc
            ac_no = ac

        if len(fc_no) < 10:
            continue

        q = qlike(ac_no, fc_no)
        m = mse(ac_no, fc_no)
        r2 = r2_oos(ac_no, fc_no)

        results_21d[model_name] = {
            'features': features,
            'n_oos': int(len(fc_no)),
            'qlike': float(q),
            'mse': float(m),
            'r2_oos': float(r2),
        }
        print(f"  {model_name}: QLIKE={q:.4f}, R²_OOS={r2:.4f}, N={len(fc_no)}")

    # DM test: combined vs individuals (21d)
    dm_21d = {}
    if 'M4_combined_21d' in results_21d:
        for m_other in ['M2_vrp_21d', 'M3_semi_21d', 'M1_rv21_21d']:
            if m_other not in results_21d:
                continue
            # Re-run with full overlapping data for more power in DM test
            fc4, ac4 = ols_forecast_expanding(df, models_21d['M4_combined_21d'], target_21d, oos_start)
            fc_o, ac_o = ols_forecast_expanding(df, models_21d[m_other], target_21d, oos_start)

            common = fc4.index.intersection(fc_o.index)
            if len(common) < 50:
                continue

            fc4a = fc4.reindex(common)
            fc_oa = fc_o.reindex(common)
            aca = ac4.reindex(common)

            loss4 = aca / fc4a - np.log(aca / fc4a) - 1
            loss_o = aca / fc_oa - np.log(aca / fc_oa) - 1

            t_stat, p_val = dm_test(loss4, loss_o, h=21)
            dm_21d[f"M4_vs_{m_other}"] = {
                'dm_t': float(t_stat),
                'dm_p': float(p_val),
                'n': int(len(common)),
            }
            sig = '***' if p_val < 0.01 else '**' if p_val < 0.05 else '*' if p_val < 0.10 else ''
            print(f"  DM(21d): M4_combined vs {m_other}: t={t_stat:.3f}, p={p_val:.4f}{sig}")

    # ============================================================
    # Summary
    # ============================================================
    print(f"\n{'='*60}")
    print(f"  SUMMARY for {asset_name}")
    print(f"{'='*60}")

    # Rank by QLIKE
    ranked = sorted(results.items(), key=lambda x: x[1]['qlike'])
    print(f"\n  Ranking by QLIKE (lower is better):")
    for rank, (name, r) in enumerate(ranked, 1):
        print(f"    {rank}. {name}: QLIKE={r['qlike']:.4f}, R²_OOS={r['r2_oos']:.4f}")

    return {
        'diagnostics': diag,
        'daily_results': results,
        'dm_tests': dm_results,
        'bootstrap': bootstrap_results,
        'encompassing': encompassing,
        'horizon_21d_results': results_21d,
        'horizon_21d_dm': dm_21d,
    }


# ============================================================
# 6. RUN FOR BOTH ASSETS
# ============================================================
all_results = {}

for asset_name, price_df in [('SPY', spy_raw), ('QQQ', qqq_raw)]:
    all_results[asset_name] = analyze_asset(price_df, vix_raw, asset_name)


# ============================================================
# 7. CROSS-ASSET SYNTHESIS
# ============================================================
print("\n" + "#" * 70)
print("# CROSS-ASSET SYNTHESIS")
print("#" * 70)

for asset in ['SPY', 'QQQ']:
    res = all_results[asset]
    daily = res['daily_results']

    if 'M4_vrp_semi_combined' in daily:
        m4 = daily['M4_vrp_semi_combined']
        m2 = daily.get('M2_vrp_only', {})
        m3 = daily.get('M3_semi_only', {})
        m1 = daily.get('M1_rv21_only', {})

        print(f"\n  {asset}:")
        print(f"    Baseline (RV21): QLIKE={m1.get('qlike','N/A')}, R²={m1.get('r2_oos','N/A')}")
        print(f"    VRP-only:        QLIKE={m2.get('qlike','N/A')}, R²={m2.get('r2_oos','N/A')}")
        print(f"    Semi-only:       QLIKE={m3.get('qlike','N/A')}, R²={m3.get('r2_oos','N/A')}")
        print(f"    Combined:        QLIKE={m4['qlike']:.4f}, R²={m4['r2_oos']:.4f}")

        # Check for synergy
        dm_comb_vrp = res['dm_tests'].get('M4_vrp_semi_combined_vs_M2_vrp_only', {})
        dm_comb_semi = res['dm_tests'].get('M4_vrp_semi_combined_vs_M3_semi_only', {})

        if dm_comb_vrp and dm_comb_semi:
            comb_beats_vrp = dm_comb_vrp.get('dm_p', 1) < 0.05
            comb_beats_semi = dm_comb_semi.get('dm_p', 1) < 0.05

            if comb_beats_vrp and comb_beats_semi:
                print(f"    → TRUE SYNERGY: Combined significantly beats BOTH VRP-only AND Semi-only")
            elif comb_beats_vrp or comb_beats_semi:
                print(f"    → PARTIAL SYNERGY: Combined beats one but not both")
            else:
                print(f"    → NO SYNERGY: Combined does not significantly beat individuals")


# ============================================================
# 8. CONCLUSIONS
# ============================================================
print("\n" + "=" * 70)
print("K450 CONCLUSIONS")
print("=" * 70)

# Determine overall conclusion
synergy_found = False
for asset in ['SPY', 'QQQ']:
    res = all_results[asset]
    dm = res['dm_tests']

    comb_vs_vrp = dm.get('M4_vrp_semi_combined_vs_M2_vrp_only', {})
    comb_vs_semi = dm.get('M4_vrp_semi_combined_vs_M3_semi_only', {})

    if comb_vs_vrp.get('dm_p', 1) < 0.05 and comb_vs_semi.get('dm_p', 1) < 0.05:
        synergy_found = True
        break

if synergy_found:
    print("\n  POSITIVE: VRP + Semivariance combination shows synergistic improvement")
    print("  → Forward-looking (options) + backward-looking (asymmetry) are complementary")
else:
    print("\n  Evaluating partial results...")
    for asset in ['SPY', 'QQQ']:
        res = all_results[asset]
        dm = res['dm_tests']
        encomp = res['encompassing']

        # Check encompassing
        vrp_by_semi = encomp.get('M2_vrp_only_add_M3_semi_only', {})
        semi_by_vrp = encomp.get('M3_semi_only_add_M2_vrp_only', {})

        if vrp_by_semi.get('p_value', 1) < 0.05 and semi_by_vrp.get('p_value', 1) < 0.05:
            print(f"  {asset}: Neither encompasses the other → both carry unique info")
        elif vrp_by_semi.get('p_value', 1) < 0.05:
            print(f"  {asset}: Semi adds info beyond VRP (but not vice versa)")
        elif semi_by_vrp.get('p_value', 1) < 0.05:
            print(f"  {asset}: VRP adds info beyond Semi (but not vice versa)")
        else:
            print(f"  {asset}: Redundant information — no significant unique contribution")

# Harvey threshold check
print("\n  Harvey (2016) t>3.0 check:")
for asset in ['SPY', 'QQQ']:
    res = all_results[asset]
    key_dm = res['dm_tests'].get('M4_vrp_semi_combined_vs_M1_rv21_only', {})
    t_val = abs(key_dm.get('dm_t', 0))
    passes = t_val > 3.0
    print(f"    {asset} Combined vs Baseline: |t|={t_val:.3f} {'PASSES' if passes else 'FAILS'} Harvey threshold")


# ============================================================
# 9. SAVE RESULTS
# ============================================================
output = {
    'experiment_id': 'k450',
    'title': 'Combined VRP + Semivariance Model for Volatility Prediction',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance (SPY, QQQ, ^VIX)',
    'oos_start': '2023-01-01',
    'reference_experiments': ['K436 (VRP robustness)', 'K449 (Semivariance)'],
    'literature': [
        'Bollerslev, Tauchen, Zhou (2009) RFS — VRP',
        'Patton & Sheppard (2015) — Semivariance decomposition',
    ],
    'hypothesis': 'VRP (forward-looking options info) + RS⁻ (backward-looking asymmetry) are complementary for vol prediction',
    'methodology': {
        'models': ['M1: RV21 baseline', 'M2: VRP+RV21', 'M3: Semivariance',
                   'M4: VRP+Semi combined', 'M5: Kitchen sink', 'M6: GJR-GARCH', 'M7: Ridge all'],
        'evaluation': 'QLIKE, MSE, R²_OOS',
        'statistical_tests': 'DM (HAC), Block bootstrap (b=21, 10000 reps), Forecast encompassing',
        'oos_window': 'Expanding, min_train=504',
        'daily_target': '|return|_{t+1} (no overlap)',
        '21d_target': 'RV_{t+1:t+21} (non-overlapping for robustness)',
    },
    'results': all_results,
}

# Make JSON serializable
def make_serializable(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, pd.Timestamp):
        return str(obj)
    elif isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_serializable(v) for v in obj]
    return obj

output = make_serializable(output)

results_path = 'experiments/k450_vrp_semivar_combined_results.json'
with open(results_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to {results_path}")
print("\nK450 COMPLETE.")
