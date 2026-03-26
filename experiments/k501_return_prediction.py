#!/usr/bin/env python3
"""
K501: SSVS for Return Prediction
=================================
[提出: 用戶(新研究方向), 執行: Claude]

背景: 119個K-series實驗全在預測波動率，從未認真嘗試預測return。
K461發現台股mean equation SPY_ret PIP=1.000 (t=10.81)，暗示return prediction信號存在。
K433發現SPY mean equation空模型勝（外生變數冗餘）。

研究問題:
1. 用SSVS選出的變數能否OOS預測SPY/台股的return？
2. 預測力有多強？(OOS R², hit rate for direction)
3. 能否轉化為交易策略？(long/short based on predicted direction)

方法: Welch & Goyal (2008) OOS R² framework
     So, Chen, Liu (2006) SSVS variable selection
     Expanding window (not rolling) for OOS prediction

資產: SPY, 0050.TW, QQQ
模型: Historical mean, AR(1), SSVS-OLS, Kitchen sink Ridge, Direction logistic

Reference:
- Welch & Goyal (2008) "A Comprehensive Look at The Empirical Performance of
  Equity Premium Prediction" RFS
- So, Chen, Liu (2006) "Best Subset Selection of ARX Models Using SSVS" JRSS-C
- Campbell & Thompson (2008) "Predicting Excess Stock Returns Out of Sample" RFS
- Harvey, Liu, Zhu (2016) t>3.0 threshold
- K461 results: SPY_ret_L1 PIP=1.000 for Taiwan
- K433 results: Empty model wins for SPY mean equation
"""

import json
import warnings
import time
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings('ignore')

# ── Configuration ──────────────────────────────────────────────────
OOS_START = '2020-01-02'  # ~5 years OOS (includes COVID, recovery, 2022 bear, 2023-2025 bull)
MIN_IS = 1000  # Minimum in-sample observations for first prediction
RIDGE_ALPHA = 1.0
RANDOM_STATE = 42

# ── Data Collection ────────────────────────────────────────────────
def collect_data():
    """Download all required data from yfinance."""
    print("=" * 70)
    print("K501: SSVS for Return Prediction")
    print("=" * 70)
    print(f"\nCollecting data from yfinance...")

    tickers = {
        'SPY': 'SPY',
        'QQQ': 'QQQ',
        '0050.TW': '0050.TW',
        'VIX': '^VIX',
        'TNX': '^TNX',      # 10Y Treasury yield
        'IRX': '^IRX',      # 13-week T-bill
        'HYG': 'HYG',      # High yield corp bond
        'TLT': 'TLT',      # Long-term treasury
        'USDTWD': 'TWD=X',  # USD/TWD exchange rate
    }

    data = {}
    for name, ticker in tickers.items():
        try:
            df = yf.download(ticker, start='2007-01-01', end='2026-03-27',
                           progress=False, auto_adjust=True)
            if len(df) > 100:
                data[name] = df
                print(f"  {name}: {len(df)} obs ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")
            else:
                print(f"  {name}: insufficient data ({len(df)} obs)")
        except Exception as e:
            print(f"  {name}: FAILED - {e}")

    return data


# ── Helper: flatten yfinance multi-level columns ──────────────────
def get_series(df, col):
    """Extract a single Series from a DataFrame, handling multi-level columns."""
    s = df[col]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    return s


# ── Feature Engineering ────────────────────────────────────────────
def build_features_spy(data):
    """Build predictor matrix for SPY."""
    spy_close = get_series(data['SPY'], 'Close')
    spy_volume = get_series(data['SPY'], 'Volume')
    spy = pd.DataFrame({'close': spy_close, 'volume': spy_volume})
    spy['ret'] = np.log(spy['close'] / spy['close'].shift(1)) * 100  # log return %

    features = pd.DataFrame(index=spy.index)
    features['target'] = spy['ret'].shift(-1)  # Next-day return (to predict)

    # 1. Own lags
    features['ret_L1'] = spy['ret']
    features['ret_L2'] = spy['ret'].shift(1)

    # 2. VIX level (lag 1)
    if 'VIX' in data:
        vix_close = get_series(data['VIX'], 'Close').reindex(spy.index, method='ffill')
        features['vix_level_L1'] = vix_close
        features['vix_change_L1'] = vix_close - vix_close.shift(1)

    # 3. Term spread (TNX - IRX)
    if 'TNX' in data and 'IRX' in data:
        tnx_close = get_series(data['TNX'], 'Close').reindex(spy.index, method='ffill')
        irx_close = get_series(data['IRX'], 'Close').reindex(spy.index, method='ffill')
        features['term_spread_L1'] = (tnx_close - irx_close)

    # 4. Credit spread proxy (HYG - TLT return)
    if 'HYG' in data and 'TLT' in data:
        hyg_close = get_series(data['HYG'], 'Close')
        tlt_close = get_series(data['TLT'], 'Close')
        hyg_ret = np.log(hyg_close / hyg_close.shift(1)) * 100
        tlt_ret = np.log(tlt_close / tlt_close.shift(1)) * 100
        hyg_ret = hyg_ret.reindex(spy.index, method='ffill')
        tlt_ret = tlt_ret.reindex(spy.index, method='ffill')
        features['credit_spread_L1'] = (hyg_ret - tlt_ret)

    # 5. Volume surprise (standardized)
    vol_ma20 = spy['volume'].rolling(20).mean()
    features['vol_surprise_L1'] = (spy['volume'] / vol_ma20 - 1)

    # 6. 5-day momentum
    features['mom5_L1'] = spy['close'].pct_change(5) * 100

    # 7. Overnight return (proxy: open-to-close vs close-to-close)
    # Use close-to-close minus intraday as proxy
    features['ret_abs_L1'] = np.abs(spy['ret'])

    features = features.dropna()
    return features


def build_features_taiwan(data):
    """Build predictor matrix for 0050.TW (with US lag-1 due to timezone)."""
    tw_close = get_series(data['0050.TW'], 'Close')
    tw_volume = get_series(data['0050.TW'], 'Volume')
    tw = pd.DataFrame({'close': tw_close, 'volume': tw_volume})
    tw['ret'] = np.log(tw['close'] / tw['close'].shift(1)) * 100

    features = pd.DataFrame(index=tw.index)
    features['target'] = tw['ret'].shift(-1)

    # 1. Own lags
    features['ret_L1'] = tw['ret']
    features['ret_L2'] = tw['ret'].shift(1)

    # 2. SPY return (lag 1) ← K461: PIP=1.000
    if 'SPY' in data:
        spy_close = get_series(data['SPY'], 'Close')
        spy_ret = np.log(spy_close / spy_close.shift(1)) * 100
        spy_ret = spy_ret.reindex(tw.index, method='ffill')
        features['spy_ret_L1'] = spy_ret
        spy_mom5 = spy_close.pct_change(5) * 100
        spy_mom5 = spy_mom5.reindex(tw.index, method='ffill')
        features['spy_mom5_L1'] = spy_mom5

    # 3. VIX (lag 1)
    if 'VIX' in data:
        vix_close = get_series(data['VIX'], 'Close').reindex(tw.index, method='ffill')
        features['vix_level_L1'] = vix_close
        features['vix_change_L1'] = vix_close - vix_close.shift(1)

    # 4. USD/TWD change
    if 'USDTWD' in data:
        fx_close = get_series(data['USDTWD'], 'Close').reindex(tw.index, method='ffill')
        features['fx_change_L1'] = fx_close.pct_change() * 100

    # 5. Volume surprise
    vol_ma20 = tw['volume'].rolling(20).mean()
    features['vol_surprise_L1'] = (tw['volume'] / vol_ma20 - 1)

    features = features.dropna()
    return features


def build_features_qqq(data):
    """Build predictor matrix for QQQ (similar to SPY)."""
    qqq_close = get_series(data['QQQ'], 'Close')
    qqq_volume = get_series(data['QQQ'], 'Volume')
    qqq = pd.DataFrame({'close': qqq_close, 'volume': qqq_volume})
    qqq['ret'] = np.log(qqq['close'] / qqq['close'].shift(1)) * 100

    features = pd.DataFrame(index=qqq.index)
    features['target'] = qqq['ret'].shift(-1)

    # 1. Own lags
    features['ret_L1'] = qqq['ret']
    features['ret_L2'] = qqq['ret'].shift(1)

    # 2. VIX
    if 'VIX' in data:
        vix_close = get_series(data['VIX'], 'Close').reindex(qqq.index, method='ffill')
        features['vix_level_L1'] = vix_close
        features['vix_change_L1'] = vix_close - vix_close.shift(1)

    # 3. Term spread
    if 'TNX' in data and 'IRX' in data:
        tnx_close = get_series(data['TNX'], 'Close').reindex(qqq.index, method='ffill')
        irx_close = get_series(data['IRX'], 'Close').reindex(qqq.index, method='ffill')
        features['term_spread_L1'] = (tnx_close - irx_close)

    # 4. Credit spread
    if 'HYG' in data and 'TLT' in data:
        hyg_close = get_series(data['HYG'], 'Close')
        tlt_close = get_series(data['TLT'], 'Close')
        hyg_ret = np.log(hyg_close / hyg_close.shift(1)) * 100
        tlt_ret = np.log(tlt_close / tlt_close.shift(1)) * 100
        hyg_ret = hyg_ret.reindex(qqq.index, method='ffill')
        tlt_ret = tlt_ret.reindex(qqq.index, method='ffill')
        features['credit_spread_L1'] = (hyg_ret - tlt_ret)

    # 5. SPY return (cross-asset signal)
    if 'SPY' in data:
        spy_close = get_series(data['SPY'], 'Close')
        spy_ret = np.log(spy_close / spy_close.shift(1)) * 100
        spy_ret = spy_ret.reindex(qqq.index, method='ffill')
        features['spy_ret_L1'] = spy_ret

    # 6. Volume surprise
    vol_ma20 = qqq['volume'].rolling(20).mean()
    features['vol_surprise_L1'] = (qqq['volume'] / vol_ma20 - 1)

    # 7. 5-day momentum
    features['mom5_L1'] = qqq['close'].pct_change(5) * 100

    features = features.dropna()
    return features


# ── SSVS Variable Selection (Bayesian) ────────────────────────────
def ssvs_variable_selection(y, X, n_iter=15000, burnin=3000):
    """
    Simplified SSVS for mean equation variable selection.
    Returns PIPs and selected variables.
    """
    n, p = X.shape

    # OLS for initial estimates and tau calibration
    from numpy.linalg import lstsq
    beta_ols, _, _, _ = lstsq(X, y, rcond=None)
    resid = y - X @ beta_ols
    sigma2_ols = np.var(resid)

    # Standard errors from OLS
    try:
        XtX_inv = np.linalg.inv(X.T @ X)
        se_ols = np.sqrt(np.diag(XtX_inv) * sigma2_ols)
    except np.linalg.LinAlgError:
        se_ols = np.abs(beta_ols) * 0.5 + 0.01

    # SSVS parameters
    tau = se_ols  # spike width
    c = 10.0      # slab/spike ratio
    p_prior = 0.5  # prior inclusion probability

    # Initialize
    gamma = np.ones(p)  # inclusion indicators
    beta = beta_ols.copy()
    sigma2 = sigma2_ols

    # Storage
    gamma_samples = np.zeros((n_iter - burnin, p))

    for it in range(n_iter):
        # Update each gamma_j
        for j in range(p):
            # Conditional on beta_j, compute inclusion probability
            log_p1 = (np.log(p_prior) - 0.5 * np.log(2 * np.pi * (c * tau[j])**2)
                      - beta[j]**2 / (2 * (c * tau[j])**2))
            log_p0 = (np.log(1 - p_prior) - 0.5 * np.log(2 * np.pi * tau[j]**2)
                      - beta[j]**2 / (2 * tau[j]**2))

            log_max = max(log_p1, log_p0)
            p1 = np.exp(log_p1 - log_max)
            p0 = np.exp(log_p0 - log_max)
            prob = p1 / (p1 + p0)

            gamma[j] = 1 if np.random.random() < prob else 0

        # Update beta via GLS
        D = np.diag([(c * tau[j])**2 if gamma[j] == 1 else tau[j]**2 for j in range(p)])
        try:
            D_inv = np.diag([1.0 / D[j, j] for j in range(p)])
            V_post = np.linalg.inv(X.T @ X / sigma2 + D_inv)
            m_post = V_post @ (X.T @ y / sigma2)
            beta = np.random.multivariate_normal(m_post, V_post)
        except (np.linalg.LinAlgError, ValueError):
            pass  # keep previous beta

        # Update sigma2 (inverse gamma)
        resid = y - X @ beta
        shape = n / 2
        scale = np.sum(resid**2) / 2
        sigma2 = 1.0 / np.random.gamma(shape, 1.0 / scale)

        if it >= burnin:
            gamma_samples[it - burnin] = gamma

    pips = gamma_samples.mean(axis=0)
    return pips


# ── OOS Prediction Framework (Welch & Goyal 2008) ─────────────────
def expanding_window_forecast(features_df, oos_start, min_is=1000):
    """
    Run expanding window OOS forecasts using multiple models.
    Returns a dict of model_name -> (dates, actual, predicted).
    """
    oos_mask = features_df.index >= pd.Timestamp(oos_start)
    oos_dates = features_df.index[oos_mask]

    target = features_df['target'].values
    predictor_cols = [c for c in features_df.columns if c != 'target']
    X_all = features_df[predictor_cols].values

    n_total = len(features_df)
    oos_indices = np.where(oos_mask)[0]

    if len(oos_indices) == 0 or oos_indices[0] < min_is:
        print(f"  Warning: Not enough IS data. First OOS index: {oos_indices[0] if len(oos_indices) > 0 else 'N/A'}, min_is: {min_is}")
        return None

    n_oos = len(oos_indices)

    # Storage for predictions
    models = {
        'hist_mean': np.zeros(n_oos),
        'ar1': np.zeros(n_oos),
        'ssvs_ols': np.zeros(n_oos),
        'ridge': np.zeros(n_oos),
        'logistic_direction': np.zeros(n_oos),
    }
    actuals = np.zeros(n_oos)

    # SSVS variable selection (done once on initial IS period)
    first_oos = oos_indices[0]
    y_is_init = target[:first_oos]
    X_is_init = X_all[:first_oos]

    # Standardize for SSVS
    scaler_init = StandardScaler()
    X_is_scaled = scaler_init.fit_transform(X_is_init)

    print(f"  Running SSVS variable selection (IS n={first_oos})...")
    pips = ssvs_variable_selection(y_is_init, X_is_scaled, n_iter=15000, burnin=3000)

    # Select variables with PIP > 0.5 (median model)
    selected = pips > 0.5
    n_selected = np.sum(selected)

    pip_dict = {}
    for i, col in enumerate(predictor_cols):
        pip_dict[col] = {
            'PIP': round(float(pips[i]), 4),
            'selected': bool(selected[i])
        }

    print(f"  SSVS selected {n_selected}/{len(predictor_cols)} variables (PIP>0.5):")
    for col, info in sorted(pip_dict.items(), key=lambda x: -x[1]['PIP']):
        marker = "★" if info['selected'] else " "
        print(f"    {marker} {col}: PIP={info['PIP']:.4f}")

    # Re-run SSVS at midpoint for stability check
    mid_oos = oos_indices[len(oos_indices)//2]
    y_mid = target[:mid_oos]
    X_mid = X_all[:mid_oos]
    scaler_mid = StandardScaler()
    X_mid_scaled = scaler_mid.fit_transform(X_mid)
    pips_mid = ssvs_variable_selection(y_mid, X_mid_scaled, n_iter=10000, burnin=2000)
    selected_mid = pips_mid > 0.5

    # Expanding window OOS predictions
    print(f"  Running expanding window OOS predictions (n_oos={n_oos})...")

    for i, t in enumerate(oos_indices):
        y_train = target[:t]
        X_train = X_all[:t]
        actual_t = target[t]
        X_test = X_all[t:t+1]

        actuals[i] = actual_t

        # Model 1: Historical mean
        models['hist_mean'][i] = np.mean(y_train)

        # Model 2: AR(1) — only use ret_L1
        ar1_idx = predictor_cols.index('ret_L1') if 'ret_L1' in predictor_cols else 0
        X_ar1_train = X_train[:, ar1_idx:ar1_idx+1]
        X_ar1_test = X_test[:, ar1_idx:ar1_idx+1]
        try:
            X_ar1_aug = np.column_stack([np.ones(len(X_ar1_train)), X_ar1_train])
            beta_ar1 = np.linalg.lstsq(X_ar1_aug, y_train, rcond=None)[0]
            models['ar1'][i] = beta_ar1[0] + beta_ar1[1] * X_ar1_test[0, 0]
        except:
            models['ar1'][i] = np.mean(y_train)

        # Model 3: SSVS-selected OLS
        if n_selected > 0:
            X_ssvs_train = X_train[:, selected]
            X_ssvs_test = X_test[:, selected]
            try:
                X_aug = np.column_stack([np.ones(len(X_ssvs_train)), X_ssvs_train])
                beta_ssvs = np.linalg.lstsq(X_aug, y_train, rcond=None)[0]
                models['ssvs_ols'][i] = beta_ssvs[0] + X_ssvs_test[0] @ beta_ssvs[1:]
            except:
                models['ssvs_ols'][i] = np.mean(y_train)
        else:
            models['ssvs_ols'][i] = np.mean(y_train)  # Empty model

        # Model 4: Kitchen sink Ridge
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        ridge = Ridge(alpha=RIDGE_ALPHA, fit_intercept=True)
        ridge.fit(X_train_scaled, y_train)
        models['ridge'][i] = ridge.predict(X_test_scaled)[0]

        # Model 5: Direction logistic regression
        y_dir = (y_train > 0).astype(int)
        if len(np.unique(y_dir)) > 1:
            try:
                logit = LogisticRegression(C=1.0, max_iter=500, random_state=RANDOM_STATE)
                logit.fit(X_train_scaled, y_dir)
                prob_up = logit.predict_proba(X_test_scaled)[0, 1]
                # Convert probability to return prediction: sign * hist_mean_abs
                mean_abs_ret = np.mean(np.abs(y_train))
                models['logistic_direction'][i] = (2 * prob_up - 1) * mean_abs_ret
            except:
                models['logistic_direction'][i] = np.mean(y_train)
        else:
            models['logistic_direction'][i] = np.mean(y_train)

    return {
        'dates': oos_dates,
        'actuals': actuals,
        'models': models,
        'pip_dict': pip_dict,
        'n_selected': int(n_selected),
        'selected_vars': [predictor_cols[i] for i in range(len(predictor_cols)) if selected[i]],
        'pip_stability': {
            'initial_selected': [predictor_cols[i] for i in range(len(predictor_cols)) if selected[i]],
            'midpoint_selected': [predictor_cols[i] for i in range(len(predictor_cols)) if selected_mid[i]],
            'pip_correlation': float(np.corrcoef(pips, pips_mid)[0, 1]),
        }
    }


# ── Evaluation Metrics ─────────────────────────────────────────────
def evaluate_forecasts(results):
    """Compute OOS R², direction accuracy, DM test, and strategy metrics."""
    actuals = results['actuals']
    n_oos = len(actuals)

    # Benchmark: historical mean
    hist_mean_preds = results['models']['hist_mean']
    sse_benchmark = np.sum((actuals - hist_mean_preds)**2)

    eval_results = {}

    for model_name, preds in results['models'].items():
        sse_model = np.sum((actuals - preds)**2)

        # OOS R² (Welch & Goyal 2008): 1 - SSE_model / SSE_benchmark
        if model_name == 'hist_mean':
            oos_r2 = 0.0  # By definition
        else:
            oos_r2 = 1.0 - sse_model / sse_benchmark if sse_benchmark > 0 else 0.0

        # MSFE ratio
        msfe_model = sse_model / n_oos
        msfe_bench = sse_benchmark / n_oos
        msfe_ratio = msfe_model / msfe_bench if msfe_bench > 0 else 1.0

        # Direction accuracy (hit rate)
        pred_dir = np.sign(preds)
        actual_dir = np.sign(actuals)
        # Exclude zero returns
        nonzero = actual_dir != 0
        if np.sum(nonzero) > 0:
            hits = np.sum(pred_dir[nonzero] == actual_dir[nonzero])
            hit_rate = hits / np.sum(nonzero)
            n_nonzero = int(np.sum(nonzero))

            # Binomial test: H0: hit_rate = 0.5
            binom_p = stats.binom_test(hits, n_nonzero, 0.5) if hasattr(stats, 'binom_test') else \
                       stats.binomtest(int(hits), n_nonzero, 0.5).pvalue
        else:
            hit_rate = 0.5
            binom_p = 1.0
            n_nonzero = 0

        # DM test vs historical mean (Diebold-Mariano)
        if model_name != 'hist_mean':
            e_bench = (actuals - hist_mean_preds)**2
            e_model = (actuals - preds)**2
            d = e_bench - e_model  # positive = model better

            # Newey-West standard error (lag = int(n^{1/3}))
            lag = max(1, int(n_oos**(1/3)))
            d_mean = np.mean(d)

            # Autocovariance
            gamma_0 = np.var(d)
            gamma_sum = gamma_0
            for k in range(1, lag + 1):
                gamma_k = np.cov(d[k:], d[:-k])[0, 1]
                gamma_sum += 2 * (1 - k / (lag + 1)) * gamma_k

            dm_se = np.sqrt(gamma_sum / n_oos) if gamma_sum > 0 else 1e-10
            dm_stat = d_mean / dm_se
            dm_p = 2 * (1 - stats.norm.cdf(np.abs(dm_stat)))
        else:
            dm_stat = 0.0
            dm_p = 1.0

        # Long/short strategy
        # Long when predicted return > 0, short when < 0
        strategy_ret = np.sign(preds) * actuals
        strat_mean = np.mean(strategy_ret)
        strat_std = np.std(strategy_ret)
        strat_sharpe = strat_mean / strat_std * np.sqrt(252) if strat_std > 0 else 0.0

        # Buy-and-hold benchmark
        bnh_mean = np.mean(actuals)
        bnh_std = np.std(actuals)
        bnh_sharpe = bnh_mean / bnh_std * np.sqrt(252) if bnh_std > 0 else 0.0

        # Cumulative strategy return
        cum_strat = np.cumsum(strategy_ret)
        cum_bnh = np.cumsum(actuals)

        # Max drawdown of strategy
        cum_max = np.maximum.accumulate(cum_strat)
        drawdown = cum_strat - cum_max
        max_dd = np.min(drawdown) if len(drawdown) > 0 else 0.0

        # t-stat for strategy mean return
        strat_t = strat_mean / (strat_std / np.sqrt(n_oos)) if strat_std > 0 else 0.0

        # Clark-West test (for nested models: adjusted MSFE)
        if model_name != 'hist_mean':
            cw_adj = (actuals - hist_mean_preds)**2 - ((actuals - preds)**2 - (hist_mean_preds - preds)**2)
            cw_mean = np.mean(cw_adj)
            cw_se = np.std(cw_adj) / np.sqrt(n_oos)
            cw_stat = cw_mean / cw_se if cw_se > 0 else 0.0
            cw_p = 1 - stats.norm.cdf(cw_stat)  # One-sided
        else:
            cw_stat = 0.0
            cw_p = 1.0

        eval_results[model_name] = {
            'oos_r2_pct': round(oos_r2 * 100, 4),
            'msfe_ratio': round(msfe_ratio, 6),
            'hit_rate': round(hit_rate, 4),
            'hit_rate_n': n_nonzero,
            'binom_p': round(binom_p, 6),
            'dm_stat': round(dm_stat, 4),
            'dm_p': round(dm_p, 6),
            'cw_stat': round(cw_stat, 4),
            'cw_p': round(cw_p, 6),
            'strategy_sharpe_ann': round(strat_sharpe, 4),
            'strategy_mean_daily_pct': round(strat_mean, 6),
            'strategy_t_stat': round(strat_t, 4),
            'strategy_max_dd_pct': round(max_dd, 2),
            'strategy_cum_return_pct': round(cum_strat[-1], 2) if len(cum_strat) > 0 else 0,
            'bnh_sharpe_ann': round(bnh_sharpe, 4),
            'bnh_cum_return_pct': round(cum_bnh[-1], 2) if len(cum_bnh) > 0 else 0,
            'passes_harvey': abs(dm_stat) > 3.0 if model_name != 'hist_mean' else False,
        }

    return eval_results


# ── Descriptive Statistics ─────────────────────────────────────────
def descriptive_stats(features_df, asset_name):
    """Compute descriptive statistics for the target variable."""
    target = features_df['target'].dropna()

    stats_dict = {
        'asset': asset_name,
        'n_total': len(target),
        'mean_pct': round(float(np.mean(target)), 6),
        'std_pct': round(float(np.std(target)), 6),
        'skewness': round(float(stats.skew(target)), 4),
        'excess_kurtosis': round(float(stats.kurtosis(target)), 4),
        'min_pct': round(float(np.min(target)), 4),
        'max_pct': round(float(np.max(target)), 4),
        'pct_positive': round(float(np.mean(target > 0) * 100), 2),
        'adf_stat': round(float(stats.pearsonr(target[:-1], target[1:])[0]), 4),  # autocorrelation
    }

    # ADF test
    from statsmodels.tsa.stattools import adfuller
    adf_result = adfuller(target, maxlag=10)
    stats_dict['adf_stat'] = round(float(adf_result[0]), 4)
    stats_dict['adf_p'] = float(adf_result[1])

    # Ljung-Box (autocorrelation)
    from statsmodels.stats.diagnostic import acorr_ljungbox
    lb = acorr_ljungbox(target, lags=[5, 10, 20], return_df=True)
    stats_dict['ljung_box_5'] = round(float(lb['lb_pvalue'].iloc[0]), 6)
    stats_dict['ljung_box_10'] = round(float(lb['lb_pvalue'].iloc[1]), 6)
    stats_dict['ljung_box_20'] = round(float(lb['lb_pvalue'].iloc[2]), 6)

    # First-order autocorrelation
    stats_dict['autocorr_1'] = round(float(np.corrcoef(target[:-1], target[1:])[0, 1]), 6)

    return stats_dict


# ── Rolling Stability Analysis ─────────────────────────────────────
def rolling_hit_rate_analysis(actuals, preds, dates, window=252):
    """Compute rolling hit rate for stability check."""
    n = len(actuals)
    if n < window:
        return {'mean': 0.5, 'std': 0, 'min': 0.5, 'max': 0.5, 'n_windows': 0}

    pred_dir = np.sign(preds)
    actual_dir = np.sign(actuals)

    rolling_hits = []
    for i in range(n - window + 1):
        subset_pred = pred_dir[i:i+window]
        subset_actual = actual_dir[i:i+window]
        nonzero = subset_actual != 0
        if np.sum(nonzero) > 0:
            hr = np.sum(subset_pred[nonzero] == subset_actual[nonzero]) / np.sum(nonzero)
            rolling_hits.append(hr)

    if rolling_hits:
        return {
            'mean': round(float(np.mean(rolling_hits)), 4),
            'std': round(float(np.std(rolling_hits)), 4),
            'min': round(float(np.min(rolling_hits)), 4),
            'max': round(float(np.max(rolling_hits)), 4),
            'pct_above_55': round(float(np.mean(np.array(rolling_hits) > 0.55) * 100), 1),
            'pct_above_50': round(float(np.mean(np.array(rolling_hits) > 0.50) * 100), 1),
            'n_windows': len(rolling_hits),
        }
    return {'mean': 0.5, 'std': 0, 'min': 0.5, 'max': 0.5, 'n_windows': 0}


# ── Sub-period Analysis ────────────────────────────────────────────
def subperiod_analysis(actuals, preds, dates):
    """Split OOS into sub-periods for robustness."""
    dates_arr = np.array(dates)

    periods = {
        'COVID_2020': (pd.Timestamp('2020-01-01'), pd.Timestamp('2020-12-31')),
        'Recovery_2021': (pd.Timestamp('2021-01-01'), pd.Timestamp('2021-12-31')),
        'Bear_2022': (pd.Timestamp('2022-01-01'), pd.Timestamp('2022-12-31')),
        'Bull_2023': (pd.Timestamp('2023-01-01'), pd.Timestamp('2023-12-31')),
        'Bull_2024': (pd.Timestamp('2024-01-01'), pd.Timestamp('2024-12-31')),
        'Recent_2025_26': (pd.Timestamp('2025-01-01'), pd.Timestamp('2026-12-31')),
    }

    results = {}
    for name, (start, end) in periods.items():
        mask = (dates_arr >= start) & (dates_arr <= end)
        if np.sum(mask) > 20:
            a = actuals[mask]
            p = preds[mask]

            pred_dir = np.sign(p)
            actual_dir = np.sign(a)
            nonzero = actual_dir != 0
            hr = np.sum(pred_dir[nonzero] == actual_dir[nonzero]) / np.sum(nonzero) if np.sum(nonzero) > 0 else 0.5

            strat_ret = np.sign(p) * a
            cum_strat = np.sum(strat_ret)
            cum_bnh = np.sum(a)

            results[name] = {
                'n': int(np.sum(mask)),
                'hit_rate': round(float(hr), 4),
                'strategy_cum_pct': round(float(cum_strat), 2),
                'bnh_cum_pct': round(float(cum_bnh), 2),
                'strategy_beats_bnh': float(cum_strat) > float(cum_bnh),
            }

    return results


# ── Main Execution ─────────────────────────────────────────────────
def main():
    t_start = time.time()

    # Step 1: Collect data
    data = collect_data()

    # Step 2: Build features for each asset
    print("\n" + "=" * 70)
    print("Building features...")

    asset_features = {}
    builders = {
        'SPY': build_features_spy,
        '0050.TW': build_features_taiwan,
        'QQQ': build_features_qqq,
    }

    for asset, builder in builders.items():
        if asset in data or (asset == '0050.TW' and '0050.TW' in data):
            try:
                features = builder(data)
                asset_features[asset] = features
                print(f"  {asset}: {len(features)} obs, {len(features.columns)-1} predictors")
                print(f"    Predictors: {[c for c in features.columns if c != 'target']}")
            except Exception as e:
                print(f"  {asset}: FAILED to build features - {e}")
                import traceback
                traceback.print_exc()

    # Step 3: Descriptive statistics
    print("\n" + "=" * 70)
    print("Descriptive Statistics (daily log returns %):")
    print("=" * 70)

    desc_stats = {}
    for asset, features in asset_features.items():
        ds = descriptive_stats(features, asset)
        desc_stats[asset] = ds
        print(f"\n  {asset}:")
        print(f"    N={ds['n_total']}, Mean={ds['mean_pct']:.4f}%, Std={ds['std_pct']:.4f}%")
        print(f"    Skew={ds['skewness']:.3f}, Kurtosis={ds['excess_kurtosis']:.2f}")
        print(f"    %Positive={ds['pct_positive']:.1f}%, AutoCorr(1)={ds['autocorr_1']:.4f}")
        print(f"    ADF={ds['adf_stat']:.2f} (p={ds['adf_p']:.4f})")
        print(f"    Ljung-Box p: lag5={ds['ljung_box_5']:.4f}, lag10={ds['ljung_box_10']:.4f}, lag20={ds['ljung_box_20']:.4f}")

    # Step 4: OOS prediction for each asset
    print("\n" + "=" * 70)
    print("OOS Return Prediction")
    print(f"OOS start: {OOS_START}, Min IS: {MIN_IS}")
    print("=" * 70)

    all_results = {}

    for asset, features in asset_features.items():
        print(f"\n{'─' * 50}")
        print(f"Asset: {asset}")
        print(f"{'─' * 50}")

        oos_results = expanding_window_forecast(features, OOS_START, MIN_IS)

        if oos_results is None:
            print(f"  SKIPPED (insufficient data)")
            continue

        # Evaluate
        eval_res = evaluate_forecasts(oos_results)

        # Print results table
        print(f"\n  Results (n_oos={len(oos_results['actuals'])}):")
        print(f"  {'Model':<22} {'OOS R²%':>8} {'Hit%':>8} {'Binom_p':>10} {'DM_t':>8} {'DM_p':>10} {'CW_t':>8} {'CW_p':>10} {'Sharpe':>8} {'Harvey':>8}")
        print(f"  {'─'*108}")

        for model_name in ['hist_mean', 'ar1', 'ssvs_ols', 'ridge', 'logistic_direction']:
            r = eval_res[model_name]
            harvey = "PASS" if r.get('passes_harvey', False) else ""
            print(f"  {model_name:<22} {r['oos_r2_pct']:>8.3f} {r['hit_rate']*100:>7.2f}% {r['binom_p']:>10.4f} "
                  f"{r['dm_stat']:>8.3f} {r['dm_p']:>10.4f} {r['cw_stat']:>8.3f} {r['cw_p']:>10.4f} "
                  f"{r['strategy_sharpe_ann']:>8.3f} {harvey:>8}")

        # Best model
        best_model = max(
            [(m, r) for m, r in eval_res.items() if m != 'hist_mean'],
            key=lambda x: x[1]['oos_r2_pct']
        )
        print(f"\n  Best model by OOS R²: {best_model[0]} (R²={best_model[1]['oos_r2_pct']:.3f}%)")

        best_hr = max(
            [(m, r) for m, r in eval_res.items()],
            key=lambda x: x[1]['hit_rate']
        )
        print(f"  Best model by Hit Rate: {best_hr[0]} (HR={best_hr[1]['hit_rate']*100:.2f}%)")

        # SSVS details
        print(f"\n  SSVS selected variables ({oos_results['n_selected']}):")
        for var in oos_results['selected_vars']:
            pip = oos_results['pip_dict'][var]['PIP']
            print(f"    ★ {var}: PIP={pip:.4f}")

        # PIP stability
        stab = oos_results['pip_stability']
        print(f"\n  PIP stability (initial vs midpoint):")
        print(f"    Correlation: {stab['pip_correlation']:.4f}")
        print(f"    Initial selected: {stab['initial_selected']}")
        print(f"    Midpoint selected: {stab['midpoint_selected']}")

        # Rolling hit rate for best model
        best_model_name = best_hr[0]
        rolling_hr = rolling_hit_rate_analysis(
            oos_results['actuals'],
            oos_results['models'][best_model_name],
            oos_results['dates']
        )
        print(f"\n  Rolling hit rate ({best_model_name}, 252-day window):")
        print(f"    Mean={rolling_hr['mean']:.4f}, Std={rolling_hr['std']:.4f}")
        print(f"    Range=[{rolling_hr['min']:.4f}, {rolling_hr['max']:.4f}]")
        if 'pct_above_55' in rolling_hr:
            print(f"    % windows > 55%: {rolling_hr['pct_above_55']:.1f}%")
            print(f"    % windows > 50%: {rolling_hr['pct_above_50']:.1f}%")

        # Sub-period analysis
        subperiod = subperiod_analysis(
            oos_results['actuals'],
            oos_results['models'][best_model_name],
            oos_results['dates']
        )
        if subperiod:
            print(f"\n  Sub-period analysis ({best_model_name}):")
            for period, info in subperiod.items():
                beats = "✓" if info['strategy_beats_bnh'] else "✗"
                print(f"    {period}: n={info['n']}, HR={info['hit_rate']*100:.1f}%, "
                      f"Strat={info['strategy_cum_pct']:+.1f}%, BnH={info['bnh_cum_pct']:+.1f}% {beats}")

        all_results[asset] = {
            'n_oos': len(oos_results['actuals']),
            'oos_period': f"{oos_results['dates'][0].strftime('%Y-%m-%d')} to {oos_results['dates'][-1].strftime('%Y-%m-%d')}",
            'ssvs': {
                'pip_dict': oos_results['pip_dict'],
                'n_selected': oos_results['n_selected'],
                'selected_vars': oos_results['selected_vars'],
                'pip_stability': oos_results['pip_stability'],
            },
            'evaluation': eval_res,
            'rolling_hit_rate': rolling_hr,
            'subperiod': subperiod,
        }

    # Step 5: Cross-asset comparison
    print("\n" + "=" * 70)
    print("Cross-Asset Comparison")
    print("=" * 70)

    print(f"\n  {'Asset':<12} {'Best Model':<22} {'OOS R²%':>8} {'Hit%':>8} {'DM_t':>8} {'Sharpe':>8} {'Harvey':>8}")
    print(f"  {'─'*78}")

    cross_asset = {}
    for asset, res in all_results.items():
        best = max(
            [(m, r) for m, r in res['evaluation'].items() if m != 'hist_mean'],
            key=lambda x: x[1]['oos_r2_pct']
        )
        harvey = "PASS" if best[1].get('passes_harvey', False) else "FAIL"
        print(f"  {asset:<12} {best[0]:<22} {best[1]['oos_r2_pct']:>8.3f} "
              f"{best[1]['hit_rate']*100:>7.2f}% {best[1]['dm_stat']:>8.3f} "
              f"{best[1]['strategy_sharpe_ann']:>8.3f} {harvey:>8}")

        cross_asset[asset] = {
            'best_model': best[0],
            'oos_r2_pct': best[1]['oos_r2_pct'],
            'hit_rate': best[1]['hit_rate'],
            'dm_stat': best[1]['dm_stat'],
            'strategy_sharpe': best[1]['strategy_sharpe_ann'],
            'passes_harvey': best[1].get('passes_harvey', False),
        }

    elapsed = time.time() - t_start

    # Step 6: Overall conclusions
    print("\n" + "=" * 70)
    print("CONCLUSIONS")
    print("=" * 70)

    any_harvey = any(ca.get('passes_harvey', False) for ca in cross_asset.values())
    any_positive_r2 = any(ca['oos_r2_pct'] > 0 for ca in cross_asset.values())
    any_hit_above_55 = any(ca['hit_rate'] > 0.55 for ca in cross_asset.values())

    conclusions = []
    if any_harvey:
        conclusions.append("★★★ At least one model passes Harvey (2016) t>3.0 threshold")
    if any_positive_r2:
        conclusions.append("★★ Positive OOS R² found (model beats historical mean)")
    elif not any_positive_r2:
        conclusions.append("OOS R² all ≤ 0 (historical mean cannot be beaten)")
    if any_hit_above_55:
        conclusions.append("★★ Direction accuracy > 55% found (economically meaningful)")

    for c in conclusions:
        print(f"  {c}")

    print(f"\n  Computation time: {elapsed:.1f}s")

    # Step 7: Save results
    results_json = {
        'experiment_id': 'K501',
        'title': 'SSVS for Return Prediction (Welch-Goyal Framework)',
        'attribution': '[提出: 用戶(新研究方向), 執行: Claude]',
        'hypothesis': 'SSVS-selected variables can predict OOS returns, especially for Taiwan (K461: SPY_ret PIP=1.000)',
        'references': [
            'Welch & Goyal (2008) "Comprehensive Look at Equity Premium Prediction" RFS',
            'So, Chen, Liu (2006) "Best Subset Selection of ARX" JRSS-C 55(2):201-224',
            'Campbell & Thompson (2008) "Predicting Excess Stock Returns OOS" RFS',
            'Harvey, Liu, Zhu (2016) t>3.0 threshold',
            'K461: SSVS Taiwan SPY_ret PIP=1.000 (t=10.81)',
            'K433: SSVS SPY empty model wins for mean equation',
        ],
        'data': {
            'source': 'yfinance (empirical)',
            'assets': list(asset_features.keys()),
            'oos_start': OOS_START,
            'min_is': MIN_IS,
            'ridge_alpha': RIDGE_ALPHA,
        },
        'descriptive_stats': desc_stats,
        'asset_results': all_results,
        'cross_asset_comparison': cross_asset,
        'conclusions': conclusions,
        'any_harvey_pass': any_harvey,
        'any_positive_oos_r2': any_positive_r2,
        'any_direction_above_55pct': any_hit_above_55,
        'limitations': [
            'SSVS variable selection done once (not re-estimated each period) for efficiency',
            'Logistic regression uses all features, not SSVS-selected (direction model)',
            'No transaction costs in strategy evaluation',
            'OOS R² benchmarked against expanding historical mean (prevailing mean)',
            'Small OOS R² (0-3%) is typical for return prediction literature',
            'Daily returns inherently noisy — weekly/monthly may show clearer patterns',
            'Timezone lag for Taiwan features is approximate (trading day alignment)',
        ],
        'computation_time_seconds': round(elapsed, 1),
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }

    results_path = 'experiments/k501_return_prediction_results.json'
    with open(results_path, 'w') as f:
        json.dump(results_json, f, indent=2, default=str)

    print(f"\n  Results saved to {results_path}")

    return results_json


if __name__ == '__main__':
    results = main()
