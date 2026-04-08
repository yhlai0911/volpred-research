"""
K952: Threshold ARMA for Volatility — Chen, Liu, Gerlach (2011) direction
==========================================================================
Problem: K947 used threshold switching on GARCH parameters (failed, smooth MF better).
TARMA models |r_t| directly with regime-switching ARMA, which may capture MA components
and nonlinear regime effects that GARCH misses.

Models:
1. AR(5) for |r_t| — baseline autoregressive
2. ARMA(2,1) for |r_t| — add MA component
3. TARMA(2,1) threshold = |r_{t-1}|, c = rolling median
4. TARMA(2,1) threshold = VIX_{t-1}, c = 20
5. GJR(1,1,1) from arch package, predict σ², convert to |r| via √σ² × √(2/π)
6. MF-GJR(VIX) — best known model from K889

Data: SPY 2006-2026, yfinance
Window: 2000, Refit every 21 days
OOS: 2016-01-01 ~ 2025-12-31
Target: |r_t| (absolute return)

References:
- Chen, Liu, Gerlach (2011): Bayesian Subset Selection for TARMA,
  Computational Statistics, 26, 1-30
- Patton (2011): Volatility forecast comparison using imperfect volatility proxies

Author: VolPred Research System
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import os
import warnings
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime
from arch import arch_model
from scipy import stats
from sklearn.linear_model import LinearRegression

np.random.seed(42)
warnings.filterwarnings('ignore')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 1. Data
# ============================================================
print("=" * 60)
print("K952: Threshold ARMA for Volatility")
print("=" * 60)

print("\n[1] Downloading data...")
spy = yf.download('SPY', start='2004-01-01', end='2026-04-06', progress=False)
vix = yf.download('^VIX', start='2004-01-01', end='2026-04-06', progress=False)

# Handle multi-level columns
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

spy['ret'] = np.log(spy['Close'] / spy['Close'].shift(1))
spy['abs_ret'] = spy['ret'].abs()
spy['ret_sq'] = spy['ret'] ** 2

# Merge VIX
spy['VIX'] = vix['Close']
spy = spy.dropna(subset=['ret', 'VIX'])

print(f"Total observations: {len(spy)}")
print(f"Date range: {spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')}")

# ============================================================
# 2. Descriptive Statistics
# ============================================================
print("\n[2] Descriptive Statistics for |r_t|:")
abs_ret = spy['abs_ret']
print(f"  Mean:     {abs_ret.mean():.6f}")
print(f"  Std:      {abs_ret.std():.6f}")
print(f"  Skewness: {stats.skew(abs_ret):.4f}")
print(f"  Kurtosis: {stats.kurtosis(abs_ret):.4f}")
print(f"  Median:   {abs_ret.median():.6f}")

# ============================================================
# 3. Model Definitions
# ============================================================

class ARModel:
    """AR(p) for |r_t|"""
    def __init__(self, p=5):
        self.p = p
        self.coefs = None
        self.intercept = None

    def fit(self, y):
        """Fit AR(p) by OLS"""
        n = len(y)
        X = np.column_stack([y[self.p - i - 1:n - i - 1] for i in range(self.p)])
        Y = y[self.p:]
        reg = LinearRegression().fit(X, Y)
        self.coefs = reg.coef_
        self.intercept = reg.intercept_
        return self

    def predict_one(self, y_history):
        """One-step-ahead forecast given last p values"""
        x = y_history[-self.p:][::-1]  # most recent first
        return self.intercept + np.dot(self.coefs, x)


class ARMAModel:
    """ARMA(p,q) for |r_t| using iterative residual estimation"""
    def __init__(self, p=2, q=1):
        self.p = p
        self.q = q
        self.ar_coefs = None
        self.ma_coefs = None
        self.intercept = None
        self.residuals = None

    def fit(self, y, max_iter=10):
        """Fit ARMA(p,q) iteratively"""
        n = len(y)
        start = max(self.p, self.q)

        # Initialize residuals to zero
        resids = np.zeros(n)

        for iteration in range(max_iter):
            # Build design matrix: AR lags + MA lags (residuals)
            X_list = []
            for i in range(self.p):
                X_list.append(y[start - i - 1:n - i - 1])
            for j in range(self.q):
                X_list.append(resids[start - j - 1:n - j - 1])

            X = np.column_stack(X_list)
            Y = y[start:]

            reg = LinearRegression().fit(X, Y)
            fitted = reg.predict(X)
            new_resids = np.zeros(n)
            new_resids[start:] = Y - fitted

            # Check convergence
            if np.max(np.abs(new_resids - resids)) < 1e-8:
                break
            resids = new_resids

        self.ar_coefs = reg.coef_[:self.p]
        self.ma_coefs = reg.coef_[self.p:]
        self.intercept = reg.intercept_
        self.residuals = resids
        return self

    def predict_one(self, y_history, resid_history):
        """One-step-ahead forecast"""
        ar_part = sum(self.ar_coefs[i] * y_history[-(i+1)] for i in range(self.p))
        ma_part = sum(self.ma_coefs[j] * resid_history[-(j+1)] for j in range(self.q))
        return self.intercept + ar_part + ma_part


class TARMAModel:
    """Threshold ARMA(p,q) with threshold variable"""
    def __init__(self, p=2, q=1):
        self.p = p
        self.q = q
        self.regime1 = None  # (intercept, ar_coefs, ma_coefs)
        self.regime2 = None
        self.residuals = None

    def fit(self, y, threshold_var, c, max_iter=10):
        """Fit TARMA by regime-specific iterative OLS"""
        n = len(y)
        start = max(self.p, self.q)

        # Determine regimes
        regime_indicator = threshold_var[start:] <= c

        resids = np.zeros(n)

        for iteration in range(max_iter):
            # Build design matrix
            X_list = []
            for i in range(self.p):
                X_list.append(y[start - i - 1:n - i - 1])
            for j in range(self.q):
                X_list.append(resids[start - j - 1:n - j - 1])

            X = np.column_stack(X_list)
            Y = y[start:]

            # Fit regime 1
            mask1 = regime_indicator
            if mask1.sum() > self.p + self.q + 2:
                reg1 = LinearRegression().fit(X[mask1], Y[mask1])
                coefs1 = (reg1.intercept_, reg1.coef_[:self.p], reg1.coef_[self.p:])
            else:
                reg1_all = LinearRegression().fit(X, Y)
                coefs1 = (reg1_all.intercept_, reg1_all.coef_[:self.p], reg1_all.coef_[self.p:])

            # Fit regime 2
            mask2 = ~regime_indicator
            if mask2.sum() > self.p + self.q + 2:
                reg2 = LinearRegression().fit(X[mask2], Y[mask2])
                coefs2 = (reg2.intercept_, reg2.coef_[:self.p], reg2.coef_[self.p:])
            else:
                reg2_all = LinearRegression().fit(X, Y)
                coefs2 = (reg2_all.intercept_, reg2_all.coef_[:self.p], reg2_all.coef_[self.p:])

            # Compute residuals
            new_resids = np.zeros(n)
            for t_idx in range(len(Y)):
                if regime_indicator[t_idx]:
                    pred = coefs1[0] + np.dot(coefs1[1], X[t_idx, :self.p]) + np.dot(coefs1[2], X[t_idx, self.p:])
                else:
                    pred = coefs2[0] + np.dot(coefs2[1], X[t_idx, :self.p]) + np.dot(coefs2[2], X[t_idx, self.p:])
                new_resids[start + t_idx] = Y[t_idx] - pred

            if np.max(np.abs(new_resids - resids)) < 1e-8:
                break
            resids = new_resids

        self.regime1 = coefs1
        self.regime2 = coefs2
        self.residuals = resids
        return self

    def predict_one(self, y_history, resid_history, threshold_val, c):
        """One-step-ahead forecast based on regime"""
        if threshold_val <= c:
            coefs = self.regime1
        else:
            coefs = self.regime2

        ar_part = sum(coefs[1][i] * y_history[-(i+1)] for i in range(self.p))
        ma_part = sum(coefs[2][j] * resid_history[-(j+1)] for j in range(self.q))
        return coefs[0] + ar_part + ma_part


# ============================================================
# 4. OOS Forecasting
# ============================================================
print("\n[3] Out-of-sample forecasting...")

WINDOW = 2000
REFIT_EVERY = 21
OOS_START = '2016-01-01'

y_all = spy['abs_ret'].values
ret_all = spy['ret'].values
vix_all = spy['VIX'].values
dates = spy.index

oos_start_idx = np.where(dates >= OOS_START)[0][0]
n_total = len(y_all)

print(f"  OOS start index: {oos_start_idx} ({dates[oos_start_idx].strftime('%Y-%m-%d')})")
print(f"  OOS observations: {n_total - oos_start_idx}")

# Storage for forecasts
models_names = ['AR(5)', 'ARMA(2,1)', 'TARMA(|r|)', 'TARMA(VIX)', 'GJR(1,1,1)', 'MF-GJR(VIX)']
forecasts = {name: [] for name in models_names}
actuals = []
actual_dates = []

# Pre-compute rolling medians for threshold
SQRT_2_PI = np.sqrt(2.0 / np.pi)

last_fit_step = -REFIT_EVERY  # Force initial fit

# Model state
ar_model = None
arma_model = None
tarma_abs_model = None
tarma_vix_model = None
gjr_params = None
mfgjr_params = None

# Residual histories for MA models
arma_resid_history = np.zeros(10)
tarma_abs_resid_history = np.zeros(10)
tarma_vix_resid_history = np.zeros(10)

# GJR recursive variance
gjr_h_prev = None
mfgjr_h_prev = None
mfgjr_fitted = False

n_oos = n_total - oos_start_idx
print(f"  Running {n_oos} OOS predictions...")

for step, t in enumerate(range(oos_start_idx, n_total)):
    if step % 500 == 0:
        print(f"    Step {step}/{n_oos}...")

    # Current window
    w_start = max(0, t - WINDOW)
    y_win = y_all[w_start:t]
    ret_win = ret_all[w_start:t]
    vix_win = vix_all[w_start:t]

    need_refit = (step - last_fit_step >= REFIT_EVERY) or (step == 0)

    if need_refit:
        last_fit_step = step

        # --- AR(5) ---
        ar_model = ARModel(p=5).fit(y_win)

        # --- ARMA(2,1) ---
        arma_model = ARMAModel(p=2, q=1).fit(y_win)
        arma_resid_history = arma_model.residuals[-10:].copy()

        # --- TARMA(|r|) with threshold = |r_{t-1}|, c = rolling median ---
        median_abs = np.median(y_win)
        tarma_abs_model = TARMAModel(p=2, q=1)
        # threshold_var aligned: threshold_var[i] corresponds to y[i]'s threshold (|r_{i-1}|)
        thresh_var_abs = np.concatenate([[y_win[0]], y_win[:-1]])
        tarma_abs_model.fit(y_win, thresh_var_abs, median_abs)
        tarma_abs_resid_history = tarma_abs_model.residuals[-10:].copy()
        tarma_abs_c = median_abs

        # --- TARMA(VIX) with threshold = VIX_{t-1}, c = 20 ---
        tarma_vix_model = TARMAModel(p=2, q=1)
        thresh_var_vix = np.concatenate([[vix_win[0]], vix_win[:-1]])
        tarma_vix_model.fit(y_win, thresh_var_vix, 20.0)
        tarma_vix_resid_history = tarma_vix_model.residuals[-10:].copy()

        # --- GJR(1,1,1) ---
        try:
            gjr = arch_model(ret_win * 100, vol='GARCH', p=1, o=1, q=1,
                           dist='t', mean='Zero')
            gjr_res = gjr.fit(disp='off', show_warning=False)
            gjr_params = {
                'omega': gjr_res.params['omega'],
                'alpha': gjr_res.params['alpha[1]'],
                'gamma': gjr_res.params['gamma[1]'],
                'beta': gjr_res.params['beta[1]'],
            }
            # Use last conditional variance from the fitted model
            gjr_h_prev = np.asarray(gjr_res.conditional_volatility).flatten()[-1] ** 2
        except Exception as e:
            if step == 0:
                print(f"    WARNING: GJR fit failed: {e}")

        # --- MF-GJR(VIX) ---
        # Two-component model: σ²_t = τ_t × g_t
        # τ_t = exp(m0 + m1 × log(VIX_t))  [long-run, driven by VIX]
        # g_t follows GJR dynamics on de-meaned returns
        try:
            log_vix = np.log(vix_win + 1e-10)
            # Step 1: Estimate tau via regression of log(r²) on log(VIX)
            ret_sq = ret_win ** 2
            valid = (ret_sq > 1e-20) & np.isfinite(log_vix)
            if valid.sum() > 100:
                log_ret_sq = np.log(ret_sq[valid])
                log_vix_valid = log_vix[valid]
                finite = np.isfinite(log_ret_sq) & np.isfinite(log_vix_valid)
                if finite.sum() > 50:
                    reg_mf = LinearRegression().fit(
                        log_vix_valid[finite].reshape(-1, 1),
                        log_ret_sq[finite]
                    )
                    mfgjr_m0 = reg_mf.intercept_
                    mfgjr_m1 = reg_mf.coef_[0]

                    # Compute tau (in return scale, not ×100)
                    tau = np.exp(mfgjr_m0 + mfgjr_m1 * log_vix)
                    tau = np.maximum(tau, 1e-20)

                    # Step 2: Standardize returns by sqrt(tau) and scale to %
                    ret_std = ret_win / np.sqrt(tau) * 100

                    # Step 3: Fit GJR on standardized returns
                    gjr_sr = arch_model(ret_std, vol='GARCH', p=1, o=1, q=1,
                                       dist='t', mean='Zero')
                    gjr_sr_res = gjr_sr.fit(disp='off', show_warning=False)
                    mfgjr_params = {
                        'm0': mfgjr_m0,
                        'm1': mfgjr_m1,
                        'omega': gjr_sr_res.params['omega'],
                        'alpha': gjr_sr_res.params['alpha[1]'],
                        'gamma': gjr_sr_res.params['gamma[1]'],
                        'beta': gjr_sr_res.params['beta[1]'],
                    }
                    mfgjr_h_prev = np.asarray(gjr_sr_res.conditional_volatility).flatten()[-1] ** 2
                    mfgjr_fitted = True
                else:
                    mfgjr_fitted = False
            else:
                mfgjr_fitted = False
        except Exception as e:
            mfgjr_fitted = False
            if step == 0:
                print(f"    WARNING: MF-GJR fit failed: {e}")

    # === Predictions at time t (using info up to t-1) ===
    actual_val = y_all[t]
    actuals.append(actual_val)
    actual_dates.append(dates[t])

    # --- AR(5) ---
    pred_ar = ar_model.predict_one(y_all[t-5:t])
    forecasts['AR(5)'].append(max(pred_ar, 1e-8))

    # --- ARMA(2,1) ---
    pred_arma = arma_model.predict_one(y_all[t-2:t], arma_resid_history)
    forecasts['ARMA(2,1)'].append(max(pred_arma, 1e-8))
    # Update residual
    arma_resid = actual_val - pred_arma
    arma_resid_history = np.append(arma_resid_history[1:], arma_resid)

    # --- TARMA(|r|) ---
    thresh_val_abs = y_all[t-1]  # |r_{t-1}|
    pred_tarma_abs = tarma_abs_model.predict_one(
        y_all[t-2:t], tarma_abs_resid_history, thresh_val_abs, tarma_abs_c
    )
    forecasts['TARMA(|r|)'].append(max(pred_tarma_abs, 1e-8))
    tarma_abs_resid = actual_val - pred_tarma_abs
    tarma_abs_resid_history = np.append(tarma_abs_resid_history[1:], tarma_abs_resid)

    # --- TARMA(VIX) ---
    thresh_val_vix = vix_all[t-1]  # VIX_{t-1}
    pred_tarma_vix = tarma_vix_model.predict_one(
        y_all[t-2:t], tarma_vix_resid_history, thresh_val_vix, 20.0
    )
    forecasts['TARMA(VIX)'].append(max(pred_tarma_vix, 1e-8))
    tarma_vix_resid = actual_val - pred_tarma_vix
    tarma_vix_resid_history = np.append(tarma_vix_resid_history[1:], tarma_vix_resid)

    # --- GJR(1,1,1) --- recursive h[t] = omega + alpha*r²[t-1] + gamma*r²[t-1]*I + beta*h[t-1]
    if gjr_params is not None and gjr_h_prev is not None:
        r_prev = ret_all[t-1] * 100
        indicator = 1.0 if r_prev < 0 else 0.0
        gjr_h_t = (gjr_params['omega'] +
                   gjr_params['alpha'] * r_prev**2 +
                   gjr_params['gamma'] * r_prev**2 * indicator +
                   gjr_params['beta'] * gjr_h_prev)
        gjr_sigma = np.sqrt(gjr_h_t) / 100.0  # back to decimal
        pred_gjr = gjr_sigma * SQRT_2_PI
        gjr_h_prev = gjr_h_t
    else:
        pred_gjr = np.mean(y_all[w_start:t])
    forecasts['GJR(1,1,1)'].append(max(pred_gjr, 1e-8))

    # --- MF-GJR(VIX) ---
    if mfgjr_params is not None and mfgjr_h_prev is not None:
        # tau uses current VIX (known at t-1 close)
        log_vix_prev = np.log(vix_all[t-1] + 1e-10)
        tau_t = np.exp(mfgjr_params['m0'] + mfgjr_params['m1'] * log_vix_prev)
        tau_t = max(tau_t, 1e-20)

        # Standardize previous return
        r_prev_std = ret_all[t-1] / np.sqrt(tau_t) * 100
        indicator = 1.0 if ret_all[t-1] < 0 else 0.0
        g_t = (mfgjr_params['omega'] +
               mfgjr_params['alpha'] * r_prev_std**2 +
               mfgjr_params['gamma'] * r_prev_std**2 * indicator +
               mfgjr_params['beta'] * mfgjr_h_prev)

        # Total variance: tau_t * g_t (g_t is in %² scale)
        # sigma in decimal = sqrt(tau_t * g_t) / 100
        mfgjr_sigma = np.sqrt(tau_t * g_t + 1e-20) / 100.0
        pred_mfgjr = mfgjr_sigma * SQRT_2_PI
        mfgjr_h_prev = g_t
    else:
        pred_mfgjr = np.mean(y_all[w_start:t])
    forecasts['MF-GJR(VIX)'].append(max(pred_mfgjr, 1e-8))

print(f"  Completed {len(actuals)} OOS predictions.")

# ============================================================
# 5. Evaluation
# ============================================================
print("\n[4] Evaluation on |r_t| target:")

actuals_arr = np.array(actuals)
results = {}

for name in models_names:
    preds = np.array(forecasts[name])

    # MSE
    mse = np.mean((actuals_arr - preds) ** 2)
    # MAE
    mae = np.mean(np.abs(actuals_arr - preds))
    # Spearman rank correlation
    spearman_r, spearman_p = stats.spearmanr(actuals_arr, preds)

    # QLIKE on r² (convert |r| prediction to σ² prediction: σ² = (|r|/√(2/π))²)
    sigma2_pred = (preds / SQRT_2_PI) ** 2
    r_sq = (ret_all[oos_start_idx:n_total]) ** 2
    # QLIKE = mean(r²/σ² - log(r²/σ²) - 1)
    ratio = r_sq / (sigma2_pred + 1e-20)
    qlike = np.mean(ratio - np.log(ratio + 1e-20) - 1)

    results[name] = {
        'MSE': float(mse),
        'MAE': float(mae),
        'Spearman_rho': float(spearman_r),
        'Spearman_p': float(spearman_p),
        'QLIKE_r2': float(qlike),
    }

    print(f"\n  {name}:")
    print(f"    MSE:          {mse:.8f}")
    print(f"    MAE:          {mae:.6f}")
    print(f"    Spearman ρ:   {spearman_r:.4f} (p={spearman_p:.2e})")
    print(f"    QLIKE(r²):    {qlike:.4f}")

# ============================================================
# 6. DM Tests (pairwise vs AR(5) baseline)
# ============================================================
print("\n[5] Diebold-Mariano Tests vs AR(5) baseline:")

baseline_preds = np.array(forecasts['AR(5)'])
baseline_errors = (actuals_arr - baseline_preds) ** 2

dm_results = {}
for name in models_names:
    if name == 'AR(5)':
        continue
    preds = np.array(forecasts[name])
    errors = (actuals_arr - preds) ** 2

    d = baseline_errors - errors  # positive = model better than baseline
    n_d = len(d)
    d_mean = np.mean(d)

    # Newey-West HAC variance (lag = int(n^(1/3)))
    max_lag = int(n_d ** (1/3))
    gamma_0 = np.var(d, ddof=1)
    nw_var = gamma_0
    for lag in range(1, max_lag + 1):
        w = 1 - lag / (max_lag + 1)
        gamma_l = np.cov(d[lag:], d[:-lag])[0, 1]
        nw_var += 2 * w * gamma_l

    dm_stat = d_mean / np.sqrt(nw_var / n_d)
    dm_pval = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

    # Harvey (2016) small-sample correction
    harvey_correction = np.sqrt((n_d + 1 - 2*1 + 1*(1-1)/n_d) / n_d)
    dm_stat_adj = dm_stat * harvey_correction

    significant = abs(dm_stat_adj) > 3.0

    dm_results[name] = {
        'DM_stat': float(dm_stat_adj),
        'DM_pval': float(dm_pval),
        'significant_Harvey': significant,
        'better_than_baseline': d_mean > 0,
    }

    sig_str = "***" if significant else ""
    direction = "BETTER" if d_mean > 0 else "worse"
    print(f"  {name} vs AR(5): DM={dm_stat_adj:.3f}, p={dm_pval:.4f} {sig_str} [{direction}]")

# Also DM tests: TARMA models vs GJR and MF-GJR
print("\n[6] Key pairwise DM tests:")
key_pairs = [
    ('TARMA(|r|)', 'GJR(1,1,1)'),
    ('TARMA(VIX)', 'GJR(1,1,1)'),
    ('TARMA(|r|)', 'MF-GJR(VIX)'),
    ('TARMA(VIX)', 'MF-GJR(VIX)'),
    ('TARMA(VIX)', 'TARMA(|r|)'),
    ('ARMA(2,1)', 'GJR(1,1,1)'),
]

pairwise_dm = {}
for name_a, name_b in key_pairs:
    preds_a = np.array(forecasts[name_a])
    preds_b = np.array(forecasts[name_b])
    errors_a = (actuals_arr - preds_a) ** 2
    errors_b = (actuals_arr - preds_b) ** 2

    d = errors_b - errors_a  # positive = A better
    n_d = len(d)
    d_mean = np.mean(d)

    max_lag = int(n_d ** (1/3))
    gamma_0 = np.var(d, ddof=1)
    nw_var = gamma_0
    for lag in range(1, max_lag + 1):
        w = 1 - lag / (max_lag + 1)
        gamma_l = np.cov(d[lag:], d[:-lag])[0, 1]
        nw_var += 2 * w * gamma_l

    dm_stat = d_mean / np.sqrt(nw_var / n_d)
    harvey_correction = np.sqrt((n_d + 1 - 2 + 1*(0)/n_d) / n_d)
    dm_stat_adj = dm_stat * harvey_correction
    dm_pval = 2 * (1 - stats.norm.cdf(abs(dm_stat_adj)))

    significant = abs(dm_stat_adj) > 3.0
    winner = name_a if d_mean > 0 else name_b

    key = f"{name_a}_vs_{name_b}"
    pairwise_dm[key] = {
        'DM_stat': float(dm_stat_adj),
        'DM_pval': float(dm_pval),
        'significant_Harvey': significant,
        'winner': winner,
    }

    sig_str = "***" if significant else ""
    print(f"  {name_a} vs {name_b}: DM={dm_stat_adj:.3f}, winner={winner} {sig_str}")

# ============================================================
# 7. Regime Analysis (TARMA)
# ============================================================
print("\n[7] Regime analysis:")

# TARMA(|r|) regime stats
oos_abs_thresh = y_all[oos_start_idx-1:n_total-1]  # |r_{t-1}|
final_median = np.median(y_all[oos_start_idx-WINDOW:oos_start_idx])
regime1_mask = oos_abs_thresh <= final_median
regime2_mask = ~regime1_mask

print(f"\n  TARMA(|r|) threshold = median(|r|) = {final_median:.6f}")
print(f"    Regime 1 (low vol): {regime1_mask.sum()} obs ({regime1_mask.mean()*100:.1f}%)")
print(f"    Regime 2 (high vol): {regime2_mask.sum()} obs ({regime2_mask.mean()*100:.1f}%)")

# TARMA(VIX) regime stats
oos_vix_thresh = vix_all[oos_start_idx-1:n_total-1]
vix_r1_mask = oos_vix_thresh <= 20
vix_r2_mask = ~vix_r1_mask

print(f"\n  TARMA(VIX) threshold c=20")
print(f"    Regime 1 (VIX<=20): {vix_r1_mask.sum()} obs ({vix_r1_mask.mean()*100:.1f}%)")
print(f"    Regime 2 (VIX>20): {vix_r2_mask.sum()} obs ({vix_r2_mask.mean()*100:.1f}%)")

# Per-regime MSE
for model_name, mask_name, mask in [
    ('TARMA(|r|)', 'Low vol', regime1_mask[:len(actuals_arr)]),
    ('TARMA(|r|)', 'High vol', regime2_mask[:len(actuals_arr)]),
    ('TARMA(VIX)', 'VIX<=20', vix_r1_mask[:len(actuals_arr)]),
    ('TARMA(VIX)', 'VIX>20', vix_r2_mask[:len(actuals_arr)]),
]:
    if mask.sum() > 0:
        preds = np.array(forecasts[model_name])
        mse_regime = np.mean((actuals_arr[mask] - preds[mask]) ** 2)
        mae_regime = np.mean(np.abs(actuals_arr[mask] - preds[mask]))
        print(f"    {model_name} [{mask_name}]: MSE={mse_regime:.8f}, MAE={mae_regime:.6f}")

# ============================================================
# 8. Plots
# ============================================================
print("\n[8] Generating plots...")

fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# 8a. MSE comparison bar chart
ax = axes[0, 0]
mse_vals = [results[n]['MSE'] for n in models_names]
colors = ['#2196F3', '#4CAF50', '#FF9800', '#F44336', '#9C27B0', '#795548']
bars = ax.bar(range(len(models_names)), mse_vals, color=colors, alpha=0.8)
ax.set_xticks(range(len(models_names)))
ax.set_xticklabels(models_names, rotation=30, ha='right', fontsize=9)
ax.set_ylabel('MSE')
ax.set_title('MSE on |r_t| (lower is better)')
# Add value labels
for bar, val in zip(bars, mse_vals):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
            f'{val:.6f}', ha='center', va='bottom', fontsize=8)

# 8b. Spearman correlation
ax = axes[0, 1]
spearman_vals = [results[n]['Spearman_rho'] for n in models_names]
bars = ax.bar(range(len(models_names)), spearman_vals, color=colors, alpha=0.8)
ax.set_xticks(range(len(models_names)))
ax.set_xticklabels(models_names, rotation=30, ha='right', fontsize=9)
ax.set_ylabel('Spearman ρ')
ax.set_title('Rank Correlation with |r_t| (higher is better)')
for bar, val in zip(bars, spearman_vals):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
            f'{val:.4f}', ha='center', va='bottom', fontsize=8)

# 8c. QLIKE on r²
ax = axes[1, 0]
qlike_vals = [results[n]['QLIKE_r2'] for n in models_names]
bars = ax.bar(range(len(models_names)), qlike_vals, color=colors, alpha=0.8)
ax.set_xticks(range(len(models_names)))
ax.set_xticklabels(models_names, rotation=30, ha='right', fontsize=9)
ax.set_ylabel('QLIKE')
ax.set_title('QLIKE on r² (lower is better)')
for bar, val in zip(bars, qlike_vals):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
            f'{val:.4f}', ha='center', va='bottom', fontsize=8)

# 8d. Rolling 252-day MSE comparison (selected models)
ax = axes[1, 1]
selected = ['AR(5)', 'TARMA(VIX)', 'GJR(1,1,1)', 'MF-GJR(VIX)']
sel_colors = ['#2196F3', '#F44336', '#9C27B0', '#795548']
for name, c in zip(selected, sel_colors):
    preds = np.array(forecasts[name])
    sq_err = (actuals_arr - preds) ** 2
    rolling_mse = pd.Series(sq_err).rolling(252).mean().values
    ax.plot(actual_dates, rolling_mse, label=name, alpha=0.8, linewidth=1, color=c)
ax.legend(fontsize=8)
ax.set_ylabel('Rolling 252-day MSE')
ax.set_title('Rolling MSE Comparison')

plt.tight_layout()
plot_path = os.path.join(SCRIPT_DIR, 'k952_comparison.png')
plt.savefig(plot_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {plot_path}")

# ============================================================
# 9. Save Results
# ============================================================
print("\n[9] Saving results...")

output = {
    'experiment_id': 'K952',
    'title': 'Threshold ARMA for Volatility — Chen et al. (2011)',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance (SPY, ^VIX)',
    'data_period': f"{spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')}",
    'oos_period': f"{actual_dates[0].strftime('%Y-%m-%d')} to {actual_dates[-1].strftime('%Y-%m-%d')}",
    'n_oos': len(actuals),
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'target': '|r_t| (absolute return)',
    'seed': 42,
    'models': models_names,
    'evaluation': results,
    'dm_tests_vs_baseline': dm_results,
    'pairwise_dm_tests': pairwise_dm,
    'references': [
        'Chen, Liu, Gerlach (2011): Bayesian Subset Selection for TARMA, Computational Statistics, 26, 1-30',
        'Patton (2011): Volatility forecast comparison using imperfect volatility proxies',
    ],
    'conclusion': '',  # Will be filled after analysis
}

# Determine conclusion
best_mse = min(results, key=lambda x: results[x]['MSE'])
best_mae = min(results, key=lambda x: results[x]['MAE'])
best_spearman = max(results, key=lambda x: results[x]['Spearman_rho'])
best_qlike = min(results, key=lambda x: results[x]['QLIKE_r2'])

conclusion_lines = [
    f"Best MSE: {best_mse} ({results[best_mse]['MSE']:.8f})",
    f"Best MAE: {best_mae} ({results[best_mae]['MAE']:.6f})",
    f"Best Spearman: {best_spearman} ({results[best_spearman]['Spearman_rho']:.4f})",
    f"Best QLIKE(r²): {best_qlike} ({results[best_qlike]['QLIKE_r2']:.4f})",
]

# Check if any TARMA beats GJR/MF-GJR significantly
tarma_beats_gjr = False
tarma_beats_mfgjr = False
for key, val in pairwise_dm.items():
    if 'TARMA' in key and 'GJR(1,1,1)' in key and val['significant_Harvey'] and 'TARMA' in val['winner']:
        tarma_beats_gjr = True
    if 'TARMA' in key and 'MF-GJR' in key and val['significant_Harvey'] and 'TARMA' in val['winner']:
        tarma_beats_mfgjr = True

if tarma_beats_mfgjr:
    conclusion_lines.append("TARMA significantly beats MF-GJR(VIX) — major finding!")
elif tarma_beats_gjr:
    conclusion_lines.append("TARMA significantly beats GJR but not MF-GJR(VIX).")
else:
    conclusion_lines.append("TARMA does not significantly beat GARCH-family models at Harvey |t|>3.0 threshold.")

output['conclusion'] = '; '.join(conclusion_lines)

results_path = os.path.join(SCRIPT_DIR, 'k952_results.json')
with open(results_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"  Saved: {results_path}")

# ============================================================
# 10. Summary
# ============================================================
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
for line in conclusion_lines:
    print(f"  {line}")
print("=" * 60)
