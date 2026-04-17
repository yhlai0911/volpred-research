#!/usr/bin/env python3
"""
K629: Disposition Effect and Volatility Dynamics
==================================================
[提出: Claude(跳躍式探索-行為金融), 執行: Claude]

背景:
Disposition effect (Shefrin & Statman 1985) 指投資人傾向過早賣出獲利部位、
過久持有虧損部位。這種行為模式會在市場上產生系統性的成交量不對稱：
- 獲利時：賣壓增加 → 供給增加 → 波動率可能降低
- 虧損時：持有不賣 → 流動性降低 → 波動率可能升高

這與 leverage effect（下跌→高波動）在現象上相似，但機制不同：
- Leverage effect: 財務槓桿（負債/權益比上升）
- Disposition effect: 行為偏誤（心理帳戶+損失規避）

研究問題:
1. Disposition proxies（CGO, UGF, AsymVol）能否預測未來波動率？
2. 是否提供 GJR gamma（已捕捉 leverage effect）之外的增量信息？
3. 行為解釋 vs 財務解釋：哪個更好描述波動率不對稱？

方法:
- Capital Gains Overhang (CGO): Grinblatt & Han (2005) JFE
- Unrealized Gain Fraction (UGF): 過去252天收盤價低於當前的比例
- Asymmetric Volume Signal (AsymVol): 上漲日/下跌日成交量比
- HAR-RV + CGO 模型 vs GJR-GARCH baseline
- Rolling OOS evaluation (w=2000, refit every 21 days)

Reference:
- Shefrin & Statman (1985) "The Disposition to Sell Winners Too Early and
  Ride Losers Too Long" JF
- Grinblatt & Han (2005) "Prospect Theory, Mental Accounting, and Momentum" JFE
- An, Argyle, Bali, et al. (2020) "Capital Gains Overhang and Expected Returns" working paper
- Frazzini (2006) "The Disposition Effect and Underreaction to News" JF
- Harvey, Liu, Zhu (2016) t>3.0 threshold
"""

import json
import warnings
import time
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from arch import arch_model

warnings.filterwarnings('ignore')

# ── Configuration ──────────────────────────────────────────────────
DATA_START = '2006-01-01'
DATA_END = '2026-03-27'
OOS_START = '2023-01-03'
OOS_END = '2024-12-31'
WINDOW = 2000          # rolling estimation window
REFIT_EVERY = 21       # refit every 21 days
CGO_LAMBDA = 1 / 252   # daily turnover proxy for reference price
UGF_LOOKBACK = 252     # 1 year lookback for UGF
ASYM_VOL_LOOKBACK = 22 # 1 month for asymmetric volume

# ── Data Collection ────────────────────────────────────────────────
def collect_data():
    """Download SPY and VIX from yfinance."""
    print("=" * 70)
    print("K629: Disposition Effect and Volatility Dynamics")
    print("=" * 70)
    print(f"\nData source: yfinance")
    print(f"Period: {DATA_START} to {DATA_END}")

    spy = yf.download('SPY', start=DATA_START, end=DATA_END, progress=False)
    vix = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)

    # Handle multi-level columns
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    df = pd.DataFrame(index=spy.index)
    df['close'] = spy['Close']
    df['volume'] = spy['Volume']
    df['vix'] = vix['Close'].reindex(spy.index, method='ffill')
    df['ret'] = np.log(df['close'] / df['close'].shift(1))
    df['ret_pct'] = df['close'].pct_change()
    df = df.dropna()

    print(f"SPY observations: {len(df)}")
    print(f"Date range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

    return df


# ── Disposition Proxies ────────────────────────────────────────────
def compute_cgo(prices, lam=CGO_LAMBDA):
    """
    Capital Gains Overhang (Grinblatt & Han 2005).
    CGO_t = (P_t - RP_t) / P_t
    RP_t = λ * P_{t-1} + (1-λ) * RP_{t-1}
    """
    n = len(prices)
    rp = np.full(n, np.nan)
    rp[0] = prices[0]
    for i in range(1, n):
        rp[i] = lam * prices[i - 1] + (1 - lam) * rp[i - 1]
    cgo = (prices - rp) / prices
    return cgo, rp


def compute_ugf(prices, lookback=UGF_LOOKBACK):
    """
    Unrealized Gain Fraction: fraction of past `lookback` days where
    price was below current price (i.e., those holders are sitting on gains).
    """
    n = len(prices)
    ugf = np.full(n, np.nan)
    for i in range(lookback, n):
        window = prices[i - lookback:i]
        ugf[i] = np.mean(window < prices[i])
    return ugf


def compute_asym_vol(returns, volumes, lookback=ASYM_VOL_LOOKBACK):
    """
    Asymmetric Volume Signal:
    vol_up = avg volume on up days (last `lookback` days)
    vol_down = avg volume on down days (last `lookback` days)
    AsymVol = vol_up / vol_down
    """
    n = len(returns)
    asym = np.full(n, np.nan)
    for i in range(lookback, n):
        r_w = returns[i - lookback:i]
        v_w = volumes[i - lookback:i]
        up_mask = r_w > 0
        down_mask = r_w < 0
        if up_mask.sum() > 0 and down_mask.sum() > 0:
            asym[i] = v_w[up_mask].mean() / v_w[down_mask].mean()
    return asym


# ── Realized Volatility Measures ──────────────────────────────────
def compute_rv_measures(returns):
    """Compute realized variance and HAR components."""
    n = len(returns)
    rv = returns ** 2  # daily RV proxy

    # HAR components
    rv5 = rv.rolling(5).mean()
    rv22 = rv.rolling(22).mean()

    # Forward-looking target: next-day RV
    rv_next = rv.shift(-1)

    # 5-day forward RV (for medium-term tests)
    rv5_next = rv.rolling(5).mean().shift(-5)

    # 22-day forward RV
    rv22_next = rv.rolling(22).mean().shift(-22)

    return rv, rv5, rv22, rv_next, rv5_next, rv22_next


# ── Descriptive Statistics ─────────────────────────────────────────
def descriptive_stats(df):
    """Print descriptive statistics for all variables."""
    print("\n" + "=" * 70)
    print("STEP 1: Descriptive Statistics")
    print("=" * 70)

    vars_to_describe = ['ret', 'rv', 'cgo', 'ugf', 'asym_vol', 'vix']
    labels = ['Log Return', 'Realized Var (r²)', 'CGO', 'UGF', 'Asym Volume', 'VIX']

    stats_list = []
    for var, label in zip(vars_to_describe, labels):
        s = df[var].dropna()
        stats_list.append({
            'Variable': label,
            'N': len(s),
            'Mean': s.mean(),
            'Std': s.std(),
            'Skew': s.skew(),
            'Kurt': s.kurtosis(),
            'Min': s.min(),
            'Max': s.max()
        })

    stats_df = pd.DataFrame(stats_list)
    print(stats_df.to_string(index=False, float_format='{:.6f}'.format))

    # Correlation matrix
    print("\nCorrelation Matrix (disposition proxies + vol):")
    corr_vars = ['cgo', 'ugf', 'asym_vol', 'rv', 'rv_next', 'vix']
    corr_labels = ['CGO', 'UGF', 'AsymVol', 'RV_t', 'RV_{t+1}', 'VIX']
    corr_df = df[corr_vars].dropna()
    corr_matrix = corr_df.corr()
    corr_matrix.index = corr_labels
    corr_matrix.columns = corr_labels
    print(corr_matrix.round(4).to_string())

    return stats_df, corr_matrix


# ── In-Sample Regression Analysis ─────────────────────────────────
def in_sample_regression(df):
    """Run in-sample regressions of future RV on disposition proxies."""
    print("\n" + "=" * 70)
    print("STEP 2: In-Sample Regression Analysis")
    print("=" * 70)

    # Prepare data
    reg_df = df[['rv', 'rv_next', 'rv5_next', 'rv22_next', 'cgo', 'ugf',
                  'asym_vol', 'vix', 'ret', 'rv5', 'rv22']].dropna()

    results = {}

    # ── Model 1: Univariate CGO → RV_{t+1}
    from numpy.linalg import lstsq

    def ols_with_stats(y, X, var_names):
        """OLS with HAC standard errors (Newey-West)."""
        n, k = X.shape
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        resid = y - X @ beta
        sse = np.sum(resid ** 2)
        mse = sse / (n - k)
        r2 = 1 - sse / np.sum((y - y.mean()) ** 2)
        adj_r2 = 1 - (1 - r2) * (n - 1) / (n - k - 1)

        # Newey-West HAC standard errors (lag = int(4*(n/100)^(2/9)))
        nw_lag = int(4 * (n / 100) ** (2 / 9))
        S = np.zeros((k, k))
        for j in range(nw_lag + 1):
            weight = 1 - j / (nw_lag + 1) if j > 0 else 1
            for t in range(j, n):
                xt = X[t].reshape(-1, 1)
                xt_j = X[t - j].reshape(-1, 1) if j > 0 else xt
                S += weight * (resid[t] * resid[t - j] * (xt @ xt_j.T + xt_j @ xt.T)) if j > 0 else \
                     (resid[t] ** 2 * xt @ xt.T)
        S /= n
        XtX_inv = np.linalg.inv(X.T @ X / n)
        V = XtX_inv @ S @ XtX_inv / n
        se = np.sqrt(np.diag(V))
        t_stats = beta / se
        p_values = 2 * (1 - stats.t.cdf(np.abs(t_stats), n - k))

        return {
            'beta': beta, 'se': se, 't_stat': t_stats, 'p_value': p_values,
            'r2': r2, 'adj_r2': adj_r2, 'n': n, 'var_names': var_names
        }

    def print_regression(name, res):
        print(f"\n--- {name} ---")
        print(f"N = {res['n']}, R² = {res['r2']:.6f}, Adj R² = {res['adj_r2']:.6f}")
        print(f"{'Variable':<15} {'Beta':>12} {'SE(NW)':>12} {'t-stat':>10} {'p-value':>10}")
        for i, vn in enumerate(res['var_names']):
            sig = ''
            if res['p_value'][i] < 0.01:
                sig = '***'
            elif res['p_value'][i] < 0.05:
                sig = '**'
            elif res['p_value'][i] < 0.10:
                sig = '*'
            print(f"{vn:<15} {res['beta'][i]:>12.6f} {res['se'][i]:>12.6f} "
                  f"{res['t_stat'][i]:>10.3f} {res['p_value'][i]:>10.4f} {sig}")

    y = reg_df['rv_next'].values

    # Model 1: CGO only
    X1 = np.column_stack([np.ones(len(y)), reg_df['cgo'].values])
    res1 = ols_with_stats(y, X1, ['const', 'CGO'])
    print_regression("Model 1: RV_{t+1} = α + β₁·CGO_t", res1)
    results['m1_cgo_only'] = {
        'beta_cgo': float(res1['beta'][1]), 't_cgo': float(res1['t_stat'][1]),
        'r2': float(res1['r2'])
    }

    # Model 2: UGF only
    X2 = np.column_stack([np.ones(len(y)), reg_df['ugf'].values])
    res2 = ols_with_stats(y, X2, ['const', 'UGF'])
    print_regression("Model 2: RV_{t+1} = α + β₁·UGF_t", res2)
    results['m2_ugf_only'] = {
        'beta_ugf': float(res2['beta'][1]), 't_ugf': float(res2['t_stat'][1]),
        'r2': float(res2['r2'])
    }

    # Model 3: AsymVol only
    X3 = np.column_stack([np.ones(len(y)), reg_df['asym_vol'].values])
    res3 = ols_with_stats(y, X3, ['const', 'AsymVol'])
    print_regression("Model 3: RV_{t+1} = α + β₁·AsymVol_t", res3)
    results['m3_asymvol_only'] = {
        'beta_asym': float(res3['beta'][1]), 't_asym': float(res3['t_stat'][1]),
        'r2': float(res3['r2'])
    }

    # Model 4: HAR-RV baseline
    X4 = np.column_stack([np.ones(len(y)), reg_df['rv'].values,
                           reg_df['rv5'].values, reg_df['rv22'].values])
    res4 = ols_with_stats(y, X4, ['const', 'RV_d', 'RV_w', 'RV_m'])
    print_regression("Model 4: HAR-RV (baseline)", res4)
    results['m4_har'] = {
        'r2': float(res4['r2']),
        'betas': {n: float(b) for n, b in zip(res4['var_names'], res4['beta'])}
    }

    # Model 5: HAR-RV + CGO
    X5 = np.column_stack([np.ones(len(y)), reg_df['rv'].values,
                           reg_df['rv5'].values, reg_df['rv22'].values,
                           reg_df['cgo'].values])
    res5 = ols_with_stats(y, X5, ['const', 'RV_d', 'RV_w', 'RV_m', 'CGO'])
    print_regression("Model 5: HAR-RV + CGO", res5)
    results['m5_har_cgo'] = {
        'r2': float(res5['r2']),
        'beta_cgo': float(res5['beta'][4]), 't_cgo': float(res5['t_stat'][4]),
        'r2_improvement': float(res5['r2'] - res4['r2'])
    }

    # Model 6: HAR-RV + all disposition proxies
    X6 = np.column_stack([np.ones(len(y)), reg_df['rv'].values,
                           reg_df['rv5'].values, reg_df['rv22'].values,
                           reg_df['cgo'].values, reg_df['ugf'].values,
                           reg_df['asym_vol'].values])
    res6 = ols_with_stats(y, X6, ['const', 'RV_d', 'RV_w', 'RV_m', 'CGO', 'UGF', 'AsymVol'])
    print_regression("Model 6: HAR-RV + All Disposition Proxies", res6)
    results['m6_har_all_disp'] = {
        'r2': float(res6['r2']),
        'beta_cgo': float(res6['beta'][4]), 't_cgo': float(res6['t_stat'][4]),
        'beta_ugf': float(res6['beta'][5]), 't_ugf': float(res6['t_stat'][5]),
        'beta_asym': float(res6['beta'][6]), 't_asym': float(res6['t_stat'][6]),
        'r2_improvement': float(res6['r2'] - res4['r2'])
    }

    # Model 7: HAR-RV + CGO + VIX (controlling for VIX)
    X7 = np.column_stack([np.ones(len(y)), reg_df['rv'].values,
                           reg_df['rv5'].values, reg_df['rv22'].values,
                           reg_df['cgo'].values, reg_df['vix'].values])
    res7 = ols_with_stats(y, X7, ['const', 'RV_d', 'RV_w', 'RV_m', 'CGO', 'VIX'])
    print_regression("Model 7: HAR-RV + CGO + VIX", res7)
    results['m7_har_cgo_vix'] = {
        'r2': float(res7['r2']),
        'beta_cgo': float(res7['beta'][4]), 't_cgo': float(res7['t_stat'][4]),
        'beta_vix': float(res7['beta'][5]), 't_vix': float(res7['t_stat'][5]),
    }

    return results


# ── CGO vs Leverage Effect ─────────────────────────────────────────
def cgo_vs_leverage(df):
    """Compare CGO's predictive power with GJR gamma (leverage effect)."""
    print("\n" + "=" * 70)
    print("STEP 3: CGO vs Leverage Effect (GJR Gamma)")
    print("=" * 70)

    # Fit GJR-GARCH to get conditional variance
    rets_pct = df['ret'].values * 100

    # Full-sample GJR-GARCH
    am = arch_model(rets_pct, vol='GARCH', p=1, o=1, q=1, mean='Constant', dist='normal')
    res = am.fit(disp='off')

    print(f"\nGJR-GARCH(1,1,1) full-sample estimation:")
    print(f"  omega = {res.params['omega']:.6f}")
    print(f"  alpha = {res.params['alpha[1]']:.6f}")
    print(f"  gamma = {res.params['gamma[1]']:.6f}")
    print(f"  beta  = {res.params['beta[1]']:.6f}")
    print(f"  persistence = {res.params['alpha[1]'] + res.params['gamma[1]']/2 + res.params['beta[1]']:.6f}")

    gamma = res.params['gamma[1]']
    cond_var = res.conditional_volatility ** 2 / 10000  # back to decimal

    # CGO-leverage correlation
    valid = df[['cgo', 'ret']].dropna()
    neg_ret = (valid['ret'] < 0).astype(float)  # leverage indicator
    corr_cgo_negret = valid['cgo'].corr(neg_ret)
    print(f"\nCorr(CGO, I(ret<0)): {corr_cgo_negret:.4f}")
    print("  (Negative means: when CGO < 0 → losses → more likely ret < 0 → leverage)")

    # Is CGO just a proxy for past returns?
    cum_ret_22 = df['ret'].rolling(22).sum()
    cum_ret_63 = df['ret'].rolling(63).sum()
    cum_ret_252 = df['ret'].rolling(252).sum()

    corr_cgo_22 = df['cgo'].corr(cum_ret_22)
    corr_cgo_63 = df['cgo'].corr(cum_ret_63)
    corr_cgo_252 = df['cgo'].corr(cum_ret_252)

    print(f"\nCorr(CGO, cumulative returns):")
    print(f"  22-day cumret:  {corr_cgo_22:.4f}")
    print(f"  63-day cumret:  {corr_cgo_63:.4f}")
    print(f"  252-day cumret: {corr_cgo_252:.4f}")

    results = {
        'gjr_gamma': float(gamma),
        'gjr_persistence': float(res.params['alpha[1]'] + res.params['gamma[1]']/2 + res.params['beta[1]']),
        'corr_cgo_neg_return': float(corr_cgo_negret),
        'corr_cgo_cumret22': float(corr_cgo_22),
        'corr_cgo_cumret63': float(corr_cgo_63),
        'corr_cgo_cumret252': float(corr_cgo_252),
    }

    return results, cond_var


# ── Out-of-Sample Evaluation ──────────────────────────────────────
def oos_evaluation(df):
    """Rolling OOS comparison: HAR vs HAR+CGO vs GJR-GARCH."""
    print("\n" + "=" * 70)
    print("STEP 4: Out-of-Sample Evaluation")
    print(f"  OOS period: {OOS_START} to {OOS_END}")
    print(f"  Window: {WINDOW}, Refit: every {REFIT_EVERY} days")
    print("=" * 70)

    oos_mask = (df.index >= OOS_START) & (df.index <= OOS_END)
    oos_indices = df.index[oos_mask]

    if len(oos_indices) == 0:
        print("ERROR: No OOS observations found!")
        return {}

    print(f"  OOS observations: {len(oos_indices)}")

    # Pre-compute arrays for speed
    all_rv = df['rv'].values
    all_rv5 = df['rv5'].values
    all_rv22 = df['rv22'].values
    all_cgo = df['cgo'].values
    all_ret_pct = df['ret'].values * 100

    # Store forecasts
    fc_har = []
    fc_har_cgo = []
    fc_gjr = []
    actuals = []
    dates = []

    # Find integer positions for OOS
    all_dates = df.index
    oos_start_idx = all_dates.get_loc(oos_indices[0])

    last_fit = -REFIT_EVERY  # force fit on first iteration
    har_betas = None
    har_cgo_betas = None
    gjr_model_result = None

    n_fit = 0

    for i, oos_date in enumerate(oos_indices):
        t = all_dates.get_loc(oos_date)

        if t < WINDOW + 1:
            continue

        # Check if we have next-day RV
        if t + 1 >= len(all_rv):
            continue

        actual_rv = all_rv[t + 1]
        if np.isnan(actual_rv):
            continue

        # Refit models periodically
        if i - last_fit >= REFIT_EVERY:
            last_fit = i
            n_fit += 1

            # Training window
            train_start = t - WINDOW
            train_end = t

            # HAR-RV training
            y_train = all_rv[train_start + 1:train_end + 1]  # next-day RV
            X_train_har = np.column_stack([
                np.ones(WINDOW),
                all_rv[train_start:train_end],
                all_rv5[train_start:train_end],
                all_rv22[train_start:train_end]
            ])

            # Remove NaNs
            valid = ~(np.isnan(y_train) | np.isnan(X_train_har).any(axis=1))
            if valid.sum() < 100:
                continue

            har_betas = np.linalg.lstsq(X_train_har[valid], y_train[valid], rcond=None)[0]

            # HAR + CGO training
            X_train_cgo = np.column_stack([
                X_train_har,
                all_cgo[train_start:train_end]
            ])
            valid_cgo = valid & ~np.isnan(all_cgo[train_start:train_end])
            if valid_cgo.sum() < 100:
                har_cgo_betas = har_betas  # fallback
            else:
                har_cgo_betas = np.linalg.lstsq(X_train_cgo[valid_cgo], y_train[valid_cgo], rcond=None)[0]

            # GJR-GARCH training
            train_rets = all_ret_pct[train_start:train_end]
            try:
                am = arch_model(train_rets, vol='GARCH', p=1, o=1, q=1,
                               mean='Constant', dist='normal')
                gjr_model_result = am.fit(disp='off', show_warning=False)
            except Exception:
                gjr_model_result = None

        if har_betas is None:
            continue

        # Generate forecasts
        x_har = np.array([1, all_rv[t], all_rv5[t], all_rv22[t]])
        if np.any(np.isnan(x_har)):
            continue

        fc_h = x_har @ har_betas
        fc_h = max(fc_h, 1e-10)

        # HAR + CGO forecast
        if np.isnan(all_cgo[t]):
            fc_hc = fc_h
        else:
            x_cgo = np.append(x_har, all_cgo[t])
            fc_hc = x_cgo @ har_cgo_betas
            fc_hc = max(fc_hc, 1e-10)

        # GJR forecast
        if gjr_model_result is not None:
            try:
                omega = gjr_model_result.params['omega']
                alpha = gjr_model_result.params['alpha[1]']
                gamma_p = gjr_model_result.params['gamma[1]']
                beta_p = gjr_model_result.params['beta[1]']

                # One-step forecast using last observation
                last_ret = all_ret_pct[t]
                last_var = gjr_model_result.conditional_volatility.iloc[-1] ** 2
                indicator = 1.0 if last_ret < 0 else 0.0
                fc_g = omega + alpha * last_ret ** 2 + gamma_p * indicator * last_ret ** 2 + beta_p * last_var
                fc_g = max(fc_g / 10000, 1e-10)  # convert to decimal
            except Exception:
                fc_g = fc_h
        else:
            fc_g = fc_h

        fc_har.append(fc_h)
        fc_har_cgo.append(fc_hc)
        fc_gjr.append(fc_g)
        actuals.append(actual_rv)
        dates.append(oos_date)

    print(f"  Number of refits: {n_fit}")
    print(f"  Number of OOS forecasts: {len(actuals)}")

    if len(actuals) < 50:
        print("ERROR: Too few OOS observations!")
        return {}

    actuals = np.array(actuals)
    fc_har = np.array(fc_har)
    fc_har_cgo = np.array(fc_har_cgo)
    fc_gjr = np.array(fc_gjr)

    # QLIKE loss: L = log(σ²_f) + σ²_a / σ²_f
    def qlike(actual, forecast):
        f = np.maximum(forecast, 1e-12)
        return np.mean(np.log(f) + actual / f)

    # MSE loss
    def mse(actual, forecast):
        return np.mean((actual - forecast) ** 2)

    qlike_har = qlike(actuals, fc_har)
    qlike_har_cgo = qlike(actuals, fc_har_cgo)
    qlike_gjr = qlike(actuals, fc_gjr)

    mse_har = mse(actuals, fc_har)
    mse_har_cgo = mse(actuals, fc_har_cgo)
    mse_gjr = mse(actuals, fc_gjr)

    print(f"\n  OOS Loss Comparison:")
    print(f"  {'Model':<20} {'QLIKE':>12} {'MSE (×1e8)':>12}")
    print(f"  {'-' * 44}")
    print(f"  {'HAR-RV':<20} {qlike_har:>12.6f} {mse_har * 1e8:>12.4f}")
    print(f"  {'HAR-RV + CGO':<20} {qlike_har_cgo:>12.6f} {mse_har_cgo * 1e8:>12.4f}")
    print(f"  {'GJR-GARCH':<20} {qlike_gjr:>12.6f} {mse_gjr * 1e8:>12.4f}")

    # Diebold-Mariano test: HAR+CGO vs HAR
    def dm_test(actual, fc1, fc2, loss='qlike'):
        if loss == 'qlike':
            d = (np.log(np.maximum(fc1, 1e-12)) + actual / np.maximum(fc1, 1e-12)) - \
                (np.log(np.maximum(fc2, 1e-12)) + actual / np.maximum(fc2, 1e-12))
        else:
            d = (actual - fc1) ** 2 - (actual - fc2) ** 2
        n = len(d)
        d_mean = d.mean()
        # Newey-West variance
        nw_lag = int(4 * (n / 100) ** (2 / 9))
        gamma0 = np.mean((d - d_mean) ** 2)
        gamma_sum = 0
        for j in range(1, nw_lag + 1):
            gamma_j = np.mean((d[j:] - d_mean) * (d[:-j] - d_mean))
            gamma_sum += 2 * (1 - j / (nw_lag + 1)) * gamma_j
        var_d = (gamma0 + gamma_sum) / n
        if var_d <= 0:
            return 0, 1.0
        t_stat = d_mean / np.sqrt(var_d)
        p_val = 2 * (1 - stats.norm.cdf(abs(t_stat)))
        return t_stat, p_val

    # DM: HAR vs HAR+CGO (positive t → HAR worse, CGO helps)
    dm_qlike_t, dm_qlike_p = dm_test(actuals, fc_har, fc_har_cgo, 'qlike')
    dm_mse_t, dm_mse_p = dm_test(actuals, fc_har, fc_har_cgo, 'mse')

    # DM: GJR vs HAR+CGO
    dm_gjr_t, dm_gjr_p = dm_test(actuals, fc_gjr, fc_har_cgo, 'qlike')

    print(f"\n  Diebold-Mariano Tests:")
    print(f"  HAR vs HAR+CGO (QLIKE): t={dm_qlike_t:.4f}, p={dm_qlike_p:.4f}")
    print(f"  HAR vs HAR+CGO (MSE):   t={dm_mse_t:.4f}, p={dm_mse_p:.4f}")
    print(f"  GJR vs HAR+CGO (QLIKE): t={dm_gjr_t:.4f}, p={dm_gjr_p:.4f}")

    cgo_beats_har = qlike_har_cgo < qlike_har
    print(f"\n  CGO adds value over HAR? {cgo_beats_har} (QLIKE improvement: {(1 - qlike_har_cgo/qlike_har)*100:.4f}%)")

    results = {
        'n_oos': len(actuals),
        'n_refits': n_fit,
        'qlike': {
            'har': float(qlike_har),
            'har_cgo': float(qlike_har_cgo),
            'gjr': float(qlike_gjr),
        },
        'mse': {
            'har': float(mse_har),
            'har_cgo': float(mse_har_cgo),
            'gjr': float(mse_gjr),
        },
        'dm_test': {
            'har_vs_har_cgo_qlike': {'t': float(dm_qlike_t), 'p': float(dm_qlike_p)},
            'har_vs_har_cgo_mse': {'t': float(dm_mse_t), 'p': float(dm_mse_p)},
            'gjr_vs_har_cgo_qlike': {'t': float(dm_gjr_t), 'p': float(dm_gjr_p)},
        },
        'cgo_beats_har': bool(cgo_beats_har),
    }

    return results


# ── CGO Predicts Vol Direction ─────────────────────────────────────
def vol_direction_prediction(df):
    """Test if CGO predicts whether volatility goes up or down."""
    print("\n" + "=" * 70)
    print("STEP 5: Does CGO Predict Volatility Direction?")
    print("=" * 70)

    analysis_df = df[['cgo', 'ugf', 'asym_vol', 'rv', 'rv_next']].dropna()

    # Vol direction: 1 if rv_next > rv, 0 otherwise
    analysis_df = analysis_df.copy()
    analysis_df['vol_up'] = (analysis_df['rv_next'] > analysis_df['rv']).astype(int)

    # Simple threshold analysis
    cgo_median = analysis_df['cgo'].median()

    # When CGO < median (more holders at loss) → expect higher vol
    low_cgo = analysis_df[analysis_df['cgo'] < cgo_median]
    high_cgo = analysis_df[analysis_df['cgo'] >= cgo_median]

    vol_up_rate_low = low_cgo['vol_up'].mean()
    vol_up_rate_high = high_cgo['vol_up'].mean()

    # Average next-day RV by CGO quintile
    analysis_df['cgo_quintile'] = pd.qcut(analysis_df['cgo'], 5, labels=['Q1(loss)', 'Q2', 'Q3', 'Q4', 'Q5(gain)'])
    quintile_rv = analysis_df.groupby('cgo_quintile')['rv_next'].agg(['mean', 'std', 'count'])

    print(f"\nCGO median: {cgo_median:.6f}")
    print(f"Vol-up rate when CGO < median (holders at loss): {vol_up_rate_low:.4f}")
    print(f"Vol-up rate when CGO >= median (holders at gain): {vol_up_rate_high:.4f}")
    print(f"Difference: {vol_up_rate_low - vol_up_rate_high:.4f}")

    # Chi-squared test
    contingency = pd.crosstab(analysis_df['cgo'] < cgo_median, analysis_df['vol_up'])
    chi2, chi2_p, _, _ = stats.chi2_contingency(contingency)
    print(f"Chi-squared test: χ² = {chi2:.4f}, p = {chi2_p:.4f}")

    print(f"\nNext-Day RV by CGO Quintile:")
    print(quintile_rv.to_string(float_format='{:.8f}'.format))

    # Monotonicity test: is Q1 > Q2 > ... > Q5?
    q_means = quintile_rv['mean'].values
    monotonic = all(q_means[i] >= q_means[i + 1] for i in range(len(q_means) - 1))

    # Rank correlation
    quintile_rank = np.arange(1, 6)
    spearman_r, spearman_p = stats.spearmanr(quintile_rank, q_means)

    print(f"\nMonotonic (Q1 > Q5)? {monotonic}")
    print(f"Spearman rank correlation: r = {spearman_r:.4f}, p = {spearman_p:.4f}")
    print(f"Q1(loss) mean RV: {q_means[0]:.8f}, Q5(gain) mean RV: {q_means[-1]:.8f}")
    print(f"Ratio Q1/Q5: {q_means[0] / q_means[-1]:.4f}")

    results = {
        'cgo_median': float(cgo_median),
        'vol_up_rate_low_cgo': float(vol_up_rate_low),
        'vol_up_rate_high_cgo': float(vol_up_rate_high),
        'chi2': float(chi2),
        'chi2_p': float(chi2_p),
        'quintile_mean_rv': {str(k): float(v) for k, v in zip(quintile_rv.index, q_means)},
        'monotonic': bool(monotonic),
        'spearman_r': float(spearman_r),
        'spearman_p': float(spearman_p),
        'q1_q5_ratio': float(q_means[0] / q_means[-1]),
    }

    return results


# ── Sub-period Stability ───────────────────────────────────────────
def subperiod_analysis(df):
    """Check if disposition-vol relationship is stable across periods."""
    print("\n" + "=" * 70)
    print("STEP 6: Sub-Period Stability Analysis")
    print("=" * 70)

    periods = {
        'Pre-GFC (2006-2007)': ('2006-01-01', '2007-12-31'),
        'GFC (2008-2009)': ('2008-01-01', '2009-12-31'),
        'Recovery (2010-2012)': ('2010-01-01', '2012-12-31'),
        'Low Vol (2013-2017)': ('2013-01-01', '2017-12-31'),
        'COVID era (2018-2021)': ('2018-01-01', '2021-12-31'),
        'Recent (2022-2025)': ('2022-01-01', '2025-12-31'),
    }

    period_results = {}
    print(f"\n{'Period':<25} {'Corr(CGO,RV+1)':>15} {'Corr(UGF,RV+1)':>15} {'β_CGO (in HAR)':>15} {'N':>6}")
    print("-" * 80)

    for name, (start, end) in periods.items():
        sub = df[(df.index >= start) & (df.index <= end)].copy()
        sub = sub[['rv', 'rv5', 'rv22', 'rv_next', 'cgo', 'ugf', 'asym_vol']].dropna()

        if len(sub) < 50:
            print(f"{name:<25} {'N/A':>15} {'N/A':>15} {'N/A':>15} {len(sub):>6}")
            continue

        corr_cgo = sub['cgo'].corr(sub['rv_next'])
        corr_ugf = sub['ugf'].corr(sub['rv_next'])

        # HAR + CGO regression in sub-period
        y = sub['rv_next'].values
        X = np.column_stack([
            np.ones(len(y)),
            sub['rv'].values,
            sub['rv5'].values,
            sub['rv22'].values,
            sub['cgo'].values
        ])
        valid = ~np.isnan(X).any(axis=1) & ~np.isnan(y)
        beta = np.linalg.lstsq(X[valid], y[valid], rcond=None)[0]
        beta_cgo = beta[4]

        print(f"{name:<25} {corr_cgo:>15.4f} {corr_ugf:>15.4f} {beta_cgo:>15.6f} {len(sub):>6}")

        period_results[name] = {
            'n': len(sub),
            'corr_cgo_rv': float(corr_cgo),
            'corr_ugf_rv': float(corr_ugf),
            'beta_cgo_in_har': float(beta_cgo),
        }

    return period_results


# ── Economic Intuition Check ───────────────────────────────────────
def economic_intuition(df):
    """Verify the economic story: CGO < 0 → higher vol, CGO > 0 → lower vol."""
    print("\n" + "=" * 70)
    print("STEP 7: Economic Intuition Verification")
    print("=" * 70)

    analysis = df[['cgo', 'rv', 'rv_next', 'ret', 'ugf', 'asym_vol', 'vix']].dropna()

    # Regime analysis
    print("\n--- CGO Regime Analysis ---")
    loss_regime = analysis[analysis['cgo'] < 0]
    gain_regime = analysis[analysis['cgo'] >= 0]

    print(f"\nCGO < 0 (holders at loss): N = {len(loss_regime)}")
    print(f"  Mean next-day RV: {loss_regime['rv_next'].mean():.8f}")
    print(f"  Median next-day RV: {loss_regime['rv_next'].median():.8f}")
    print(f"  Mean VIX: {loss_regime['vix'].mean():.2f}")
    print(f"  Mean AsymVol: {loss_regime['asym_vol'].mean():.4f}")

    print(f"\nCGO >= 0 (holders at gain): N = {len(gain_regime)}")
    print(f"  Mean next-day RV: {gain_regime['rv_next'].mean():.8f}")
    print(f"  Median next-day RV: {gain_regime['rv_next'].median():.8f}")
    print(f"  Mean VIX: {gain_regime['vix'].mean():.2f}")
    print(f"  Mean AsymVol: {gain_regime['asym_vol'].mean():.4f}")

    # T-test for difference
    t_rv, p_rv = stats.ttest_ind(loss_regime['rv_next'], gain_regime['rv_next'])
    t_vix, p_vix = stats.ttest_ind(loss_regime['vix'], gain_regime['vix'])

    print(f"\nT-test (loss vs gain regime):")
    print(f"  RV difference: t = {t_rv:.4f}, p = {p_rv:.6f}")
    print(f"  VIX difference: t = {t_vix:.4f}, p = {p_vix:.6f}")

    # AsymVol analysis: does disposition predict vol_up > vol_down?
    print(f"\n--- Asymmetric Volume Analysis ---")
    print(f"Mean AsymVol: {analysis['asym_vol'].mean():.4f}")
    print(f"AsymVol > 1 (more selling on up days): {(analysis['asym_vol'] > 1).mean()*100:.1f}% of days")

    # Does AsymVol > 1 confirm disposition? (selling winners)
    asym_above = analysis[analysis['asym_vol'] > 1]
    asym_below = analysis[analysis['asym_vol'] <= 1]

    print(f"\nWhen AsymVol > 1 (selling winners):")
    print(f"  Mean CGO: {asym_above['cgo'].mean():.6f}")
    print(f"  Mean next-day RV: {asym_above['rv_next'].mean():.8f}")
    print(f"When AsymVol <= 1:")
    print(f"  Mean CGO: {asym_below['cgo'].mean():.6f}")
    print(f"  Mean next-day RV: {asym_below['rv_next'].mean():.8f}")

    # Disposition vs leverage: conditional analysis
    print(f"\n--- Disposition vs Leverage Effect ---")
    # After negative returns: is CGO adding info beyond the sign of return?
    neg_ret = analysis[analysis['ret'] < 0]
    neg_high_cgo = neg_ret[neg_ret['cgo'] >= neg_ret['cgo'].median()]
    neg_low_cgo = neg_ret[neg_ret['cgo'] < neg_ret['cgo'].median()]

    print(f"\nAfter negative returns (leverage effect active):")
    print(f"  High CGO (still at gain despite drop): mean RV_next = {neg_high_cgo['rv_next'].mean():.8f}")
    print(f"  Low CGO (at loss): mean RV_next = {neg_low_cgo['rv_next'].mean():.8f}")
    t_cond, p_cond = stats.ttest_ind(neg_low_cgo['rv_next'], neg_high_cgo['rv_next'])
    print(f"  T-test: t = {t_cond:.4f}, p = {p_cond:.6f}")

    results = {
        'loss_regime': {
            'n': len(loss_regime),
            'mean_rv_next': float(loss_regime['rv_next'].mean()),
            'median_rv_next': float(loss_regime['rv_next'].median()),
            'mean_vix': float(loss_regime['vix'].mean()),
        },
        'gain_regime': {
            'n': len(gain_regime),
            'mean_rv_next': float(gain_regime['rv_next'].mean()),
            'median_rv_next': float(gain_regime['rv_next'].median()),
            'mean_vix': float(gain_regime['vix'].mean()),
        },
        'ttest_rv': {'t': float(t_rv), 'p': float(p_rv)},
        'ttest_vix': {'t': float(t_vix), 'p': float(p_vix)},
        'asym_vol_above_1_pct': float((analysis['asym_vol'] > 1).mean() * 100),
        'conditional_analysis': {
            'neg_ret_high_cgo_rv': float(neg_high_cgo['rv_next'].mean()),
            'neg_ret_low_cgo_rv': float(neg_low_cgo['rv_next'].mean()),
            'ttest_conditional': {'t': float(t_cond), 'p': float(p_cond)},
        }
    }

    return results


# ── Longer Horizon Tests ───────────────────────────────────────────
def longer_horizon(df):
    """Test CGO prediction at 5-day and 22-day horizons."""
    print("\n" + "=" * 70)
    print("STEP 8: Longer Horizon Prediction (5-day, 22-day)")
    print("=" * 70)

    results = {}

    for horizon, target_col in [(5, 'rv5_next'), (22, 'rv22_next')]:
        sub = df[['cgo', 'ugf', 'rv', 'rv5', 'rv22', target_col]].dropna()

        if len(sub) < 100:
            print(f"\n{horizon}-day: insufficient data (N={len(sub)})")
            continue

        y = sub[target_col].values

        # CGO only
        X_cgo = np.column_stack([np.ones(len(y)), sub['cgo'].values])
        beta_cgo = np.linalg.lstsq(X_cgo, y, rcond=None)[0]
        resid_cgo = y - X_cgo @ beta_cgo
        r2_cgo = 1 - np.sum(resid_cgo ** 2) / np.sum((y - y.mean()) ** 2)

        # HAR
        X_har = np.column_stack([np.ones(len(y)), sub['rv'].values,
                                  sub['rv5'].values, sub['rv22'].values])
        beta_har = np.linalg.lstsq(X_har, y, rcond=None)[0]
        resid_har = y - X_har @ beta_har
        r2_har = 1 - np.sum(resid_har ** 2) / np.sum((y - y.mean()) ** 2)

        # HAR + CGO
        X_both = np.column_stack([X_har, sub['cgo'].values])
        beta_both = np.linalg.lstsq(X_both, y, rcond=None)[0]
        resid_both = y - X_both @ beta_both
        r2_both = 1 - np.sum(resid_both ** 2) / np.sum((y - y.mean()) ** 2)

        corr_cgo = sub['cgo'].corr(sub[target_col])

        print(f"\n{horizon}-day horizon (N={len(sub)}):")
        print(f"  Corr(CGO, RV_{horizon}d): {corr_cgo:.4f}")
        print(f"  R² (CGO only): {r2_cgo:.6f}")
        print(f"  R² (HAR): {r2_har:.6f}")
        print(f"  R² (HAR+CGO): {r2_both:.6f}")
        print(f"  R² improvement: {r2_both - r2_har:.6f} ({(r2_both - r2_har)/r2_har*100:.3f}%)")

        results[f'{horizon}d'] = {
            'n': len(sub),
            'corr_cgo': float(corr_cgo),
            'r2_cgo_only': float(r2_cgo),
            'r2_har': float(r2_har),
            'r2_har_cgo': float(r2_both),
            'r2_improvement': float(r2_both - r2_har),
        }

    return results


# ── Main ───────────────────────────────────────────────────────────
def main():
    start_time = time.time()

    # Step 0: Data collection
    df = collect_data()

    # Compute disposition proxies
    print("\nComputing disposition proxies...")
    prices = df['close'].values
    returns = df['ret'].values
    volumes = df['volume'].values

    cgo_values, ref_prices = compute_cgo(prices)
    df['cgo'] = cgo_values
    df['ref_price'] = ref_prices

    ugf_values = compute_ugf(prices)
    df['ugf'] = ugf_values

    asym_vol_values = compute_asym_vol(returns, volumes)
    df['asym_vol'] = asym_vol_values

    # Compute RV measures
    rv, rv5, rv22, rv_next, rv5_next, rv22_next = compute_rv_measures(df['ret'])
    df['rv'] = rv
    df['rv5'] = rv5
    df['rv22'] = rv22
    df['rv_next'] = rv_next
    df['rv5_next'] = rv5_next
    df['rv22_next'] = rv22_next

    print(f"CGO range: [{df['cgo'].min():.4f}, {df['cgo'].max():.4f}]")
    print(f"UGF range: [{df['ugf'].min():.4f}, {df['ugf'].max():.4f}]")
    print(f"AsymVol range: [{df['asym_vol'].min():.4f}, {df['asym_vol'].max():.4f}]")

    # Step 1: Descriptive statistics
    desc_stats, corr_matrix = descriptive_stats(df)

    # Step 2: In-sample regression
    is_results = in_sample_regression(df)

    # Step 3: CGO vs leverage
    leverage_results, cond_var = cgo_vs_leverage(df)

    # Step 4: OOS evaluation
    oos_results = oos_evaluation(df)

    # Step 5: Vol direction prediction
    direction_results = vol_direction_prediction(df)

    # Step 6: Sub-period stability
    period_results = subperiod_analysis(df)

    # Step 7: Economic intuition
    econ_results = economic_intuition(df)

    # Step 8: Longer horizon
    horizon_results = longer_horizon(df)

    elapsed = time.time() - start_time

    # ── Summary ────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("SUMMARY: K629 Disposition Effect and Volatility Dynamics")
    print("=" * 70)

    # Key findings
    cgo_sign = is_results.get('m5_har_cgo', {}).get('beta_cgo', 0)
    cgo_t = is_results.get('m5_har_cgo', {}).get('t_cgo', 0)
    r2_improve = is_results.get('m5_har_cgo', {}).get('r2_improvement', 0)

    print(f"\n1. CGO β in HAR+CGO: {cgo_sign:.6f} (t={cgo_t:.3f})")
    if cgo_sign < 0:
        print("   → Negative: higher CGO (gains) → lower future vol ✓ (consistent with disposition)")
    else:
        print("   → Positive: higher CGO → higher future vol (inconsistent with disposition)")

    print(f"\n2. R² improvement (HAR → HAR+CGO): {r2_improve:.6f}")

    if oos_results:
        print(f"\n3. OOS QLIKE:")
        print(f"   HAR:     {oos_results['qlike']['har']:.6f}")
        print(f"   HAR+CGO: {oos_results['qlike']['har_cgo']:.6f}")
        print(f"   GJR:     {oos_results['qlike']['gjr']:.6f}")
        dm = oos_results['dm_test']['har_vs_har_cgo_qlike']
        print(f"   DM test (HAR vs HAR+CGO): t={dm['t']:.4f}, p={dm['p']:.4f}")

    print(f"\n4. CGO-leverage correlation: {leverage_results['corr_cgo_cumret252']:.4f} (with 252d cumret)")

    q1_q5 = direction_results.get('q1_q5_ratio', 0)
    print(f"\n5. Q1(loss)/Q5(gain) RV ratio: {q1_q5:.4f}")

    passes_harvey = abs(cgo_t) > 3.0
    print(f"\n6. Harvey (2016) threshold: |t| = {abs(cgo_t):.3f} {'> 3.0 ✓' if passes_harvey else '< 3.0 ✗'}")

    print(f"\nRuntime: {elapsed:.1f}s")

    # ── Save Results ───────────────────────────────────────────────
    final_results = {
        'experiment_id': 'K629',
        'title': 'Disposition Effect and Volatility Dynamics',
        'proposer': 'Claude (behavioral finance jump exploration)',
        'executor': 'Claude',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'data_source': 'yfinance (SPY, ^VIX)',
        'data_period': f'{DATA_START} to {DATA_END}',
        'sample_size': len(df),
        'analysis_type': 'empirical (real data)',
        'methodology': {
            'cgo_lambda': CGO_LAMBDA,
            'ugf_lookback': UGF_LOOKBACK,
            'asym_vol_lookback': ASYM_VOL_LOOKBACK,
            'oos_window': WINDOW,
            'oos_period': f'{OOS_START} to {OOS_END}',
            'refit_frequency': REFIT_EVERY,
        },
        'references': [
            'Shefrin & Statman (1985) JF - Disposition effect theory',
            'Grinblatt & Han (2005) JFE - Capital Gains Overhang',
            'Frazzini (2006) JF - Disposition effect and underreaction',
            'An, Argyle, Bali et al. (2020) - CGO and expected returns',
            'Harvey, Liu, Zhu (2016) - t>3.0 threshold',
        ],
        'descriptive_stats': {
            'correlation_matrix': {str(k): {str(k2): float(v2) for k2, v2 in row.items()}
                                   for k, row in corr_matrix.to_dict().items()},
        },
        'in_sample_results': is_results,
        'cgo_vs_leverage': leverage_results,
        'oos_results': oos_results,
        'vol_direction': direction_results,
        'subperiod_stability': period_results,
        'economic_intuition': econ_results,
        'longer_horizon': horizon_results,
        'key_findings': {
            'cgo_beta_in_har': float(cgo_sign),
            'cgo_t_stat': float(cgo_t),
            'passes_harvey_threshold': bool(passes_harvey),
            'r2_improvement': float(r2_improve),
            'cgo_beats_har_oos': oos_results.get('cgo_beats_har', False) if oos_results else False,
            'q1_q5_rv_ratio': float(q1_q5),
            'cgo_corr_cumret252': float(leverage_results['corr_cgo_cumret252']),
        },
        'limitations': [
            'CGO reference price uses fixed λ=1/252; actual turnover varies',
            'SPY as ETF has different disposition dynamics than individual stocks',
            'Single asset (SPY); cross-sectional effects not tested',
            'RV proxy (r²) is noisy; intraday RV would be better',
            'UGF and CGO are highly correlated with past returns',
        ],
        'runtime_seconds': round(elapsed, 1),
    }

    output_path = 'experiments/k629_results.json'
    with open(output_path, 'w') as f:
        json.dump(final_results, f, indent=2, ensure_ascii=False)

    print(f"\nResults saved to {output_path}")

    return final_results


if __name__ == '__main__':
    main()
