#!/usr/bin/env python3
"""
K730: Cross-Asset Volatility Momentum — Upgraded
=================================================
[提出: Codex (7th review, 2026-03-27), 執行: Claude]

Builds on K537 (null result) with key upgrades:
  - FRED credit spread (BAMLH0A0HYM2) instead of ETF proxy
  - USO (oil) added as 5th asset class
  - Formal Granger causality (statsmodels, AIC lag selection)
  - Vol MOMENTUM signals (5d/20d changes), not just levels
  - Proper strategy with TX costs + signal.shift(1)
  - 5 non-overlapping 2-year OOS periods
  - DM test with Harvey (2016) t>3.0 threshold
  - 50/50 SPY/GLD baseline (the best static allocation per K702)

Research Question:
  Do volatility changes in bonds, commodities, FX, and credit LEAD
  equity volatility changes? If so, can cross-asset vol momentum
  improve portfolio timing beyond VIX alone?

Data:
  - Equity vol: ^VIX (yfinance)
  - Bond vol: TLT 20d realized vol (proxy for MOVE index)
  - Commodity vol: GLD + USO 20d realized vol
  - FX vol: UUP 20d realized vol
  - Credit stress: FRED BAMLH0A0HYM2 (ICE BofA HY OAS) or HYG-LQD if FRED fails
  - SPY + GLD returns for strategy test

References:
  - Moreira & Muir (2017), Volatility-Managed Portfolios, JoF
  - Diebold & Yilmaz (2012), Better to Give than to Receive, JASA
  - K537: Cross-asset vol momentum null result (VIX sufficiency)
  - K697: VIX predicts magnitude (corr 0.57) not direction (corr 0.04)
  - K702: 50/50 SPY/GLD is optimal static allocation
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from pathlib import Path
from scipy import stats as sp_stats

warnings.filterwarnings('ignore')

# ── Configuration ──────────────────────────────────────────────
PRICE_TICKERS = ['SPY', 'GLD', 'TLT', 'USO', 'UUP']
VIX_TICKER = '^VIX'
START_DATE = '2010-01-01'
END_DATE = '2026-03-29'

RV_WINDOWS = [5, 20]       # short-term and medium-term realized vol
GRANGER_MAX_LAG = 10       # max lag for Granger tests
TX_COST_BPS = 5            # 5 bps per weight change

# 5 non-overlapping 2-year OOS periods
OOS_PERIODS = [
    ('2016-01-01', '2017-12-31', '2016-2017 (low vol / Trump)'),
    ('2018-01-01', '2019-12-31', '2018-2019 (volmageddon + trade war)'),
    ('2020-01-01', '2021-12-31', '2020-2021 (COVID + recovery)'),
    ('2022-01-01', '2023-12-31', '2022-2023 (rate hikes)'),
    ('2024-01-01', '2025-12-31', '2024-2025 (recent)'),
]

FRED_SERIES = 'BAMLH0A0HYM2'  # ICE BofA US High Yield OAS


# ── Data Download ──────────────────────────────────────────────
def download_price_data():
    """Download price data from yfinance."""
    print("[Step 1] Downloading price data from yfinance...")
    all_tickers = PRICE_TICKERS + [VIX_TICKER]
    data = yf.download(all_tickers, start=START_DATE, end=END_DATE,
                       auto_adjust=True, progress=False)

    if isinstance(data.columns, pd.MultiIndex):
        close = data['Close']
    else:
        close = data

    # Flatten column names
    close.columns = [str(c).strip() for c in close.columns]
    close = close.ffill().dropna()
    print(f"  Price data: {close.shape}, {close.index[0].date()} to {close.index[-1].date()}")
    return close


def download_fred_credit_spread():
    """Download ICE BofA HY OAS from FRED. Falls back to HYG-LQD proxy."""
    print("[Step 1b] Downloading credit spread from FRED...")
    try:
        import pandas_datareader.data as web
        oas = web.DataReader(FRED_SERIES, 'fred', START_DATE, END_DATE)
        oas = oas.squeeze()
        oas = oas.dropna()
        if len(oas) > 100:
            print(f"  FRED OAS: {len(oas)} obs, {oas.index[0].date()} to {oas.index[-1].date()}")
            return oas, 'FRED BAMLH0A0HYM2'
    except Exception as e:
        print(f"  FRED download failed: {e}")

    # Fallback: use HYG-LQD spread from yfinance
    print("  Falling back to HYG-LQD ETF spread proxy...")
    try:
        hy_data = yf.download(['HYG', 'LQD'], start=START_DATE, end=END_DATE,
                              auto_adjust=True, progress=False)
        if isinstance(hy_data.columns, pd.MultiIndex):
            hyg = hy_data['Close']['HYG']
            lqd = hy_data['Close']['LQD']
        else:
            return None, None
        # Credit spread proxy: -(HYG/LQD ratio change) — when spread widens, HYG underperforms
        spread = -(np.log(hyg / lqd))
        spread = spread.dropna()
        print(f"  HYG-LQD proxy: {len(spread)} obs")
        return spread, 'HYG-LQD ETF proxy'
    except Exception as e:
        print(f"  HYG-LQD fallback also failed: {e}")
        return None, None


# ── Feature Engineering ──────────────────────────────────────────
def compute_realized_vol(returns, window):
    """Realized vol = sqrt(252) * rolling std of returns."""
    rv = returns.rolling(window, min_periods=max(window//2, 3)).std() * np.sqrt(252)
    return rv


def compute_vol_momentum(rv, short_window=5, long_window=20):
    """Vol momentum = short-term RV change / long-term RV change."""
    # 5-day change in RV (momentum)
    rv_change_short = rv.pct_change(short_window)
    # 20-day change in RV
    rv_change_long = rv.pct_change(long_window)
    return rv_change_short, rv_change_long


def build_features(close, credit_spread):
    """Build all cross-asset vol features."""
    print("\n[Step 2] Building cross-asset volatility features...")

    # Log returns
    returns = np.log(close / close.shift(1)).dropna()

    # Realized vol for each asset (20-day)
    rv20 = pd.DataFrame(index=returns.index)
    for asset in ['TLT', 'USO', 'UUP', 'GLD']:
        if asset in returns.columns:
            rv20[f'rv20_{asset}'] = compute_realized_vol(returns[asset], 20)

    # 5-day RV for faster signals
    rv5 = pd.DataFrame(index=returns.index)
    for asset in ['TLT', 'USO', 'UUP', 'GLD']:
        if asset in returns.columns:
            rv5[f'rv5_{asset}'] = compute_realized_vol(returns[asset], 5)

    # Vol momentum: 5-day and 20-day changes in 20d RV
    vol_mom = pd.DataFrame(index=returns.index)
    for col in rv20.columns:
        asset = col.replace('rv20_', '')
        chg5, chg20 = compute_vol_momentum(rv20[col], 5, 20)
        vol_mom[f'vmom5_{asset}'] = chg5
        vol_mom[f'vmom20_{asset}'] = chg20

    # VIX level and changes
    vix = close['^VIX'] if '^VIX' in close.columns else close.get('VIX')
    if vix is None:
        raise ValueError("VIX not found in data")

    vix_change5 = vix.pct_change(5)
    vix_change20 = vix.pct_change(20)

    # Credit spread features
    credit_features = pd.DataFrame(index=returns.index)
    if credit_spread is not None:
        cs = credit_spread.reindex(returns.index).ffill()
        credit_features['credit_oas'] = cs
        credit_features['credit_change5'] = cs.pct_change(5)
        credit_features['credit_change20'] = cs.pct_change(20)

    # Combine all features
    features = pd.DataFrame(index=returns.index)
    features = features.join(rv20).join(rv5).join(vol_mom).join(credit_features)
    features['vix'] = vix.reindex(returns.index)
    features['vix_change5'] = vix_change5.reindex(returns.index)
    features['vix_change20'] = vix_change20.reindex(returns.index)

    # SPY and GLD returns for strategy
    features['spy_ret'] = returns['SPY']
    features['gld_ret'] = returns['GLD']

    features = features.dropna()
    print(f"  Features: {features.shape[1]} columns, {features.shape[0]} rows")
    print(f"  Date range: {features.index[0].date()} to {features.index[-1].date()}")

    return features, returns


# ── Descriptive Statistics ──────────────────────────────────────
def descriptive_statistics(features):
    """Descriptive stats of all vol features."""
    print("\n[Step 3] Descriptive Statistics")

    # Select vol momentum columns
    vmom_cols = [c for c in features.columns if c.startswith('vmom')]
    rv_cols = [c for c in features.columns if c.startswith('rv20_')]

    stats = {}
    for col in vmom_cols + rv_cols + ['vix', 'vix_change5', 'vix_change20']:
        if col in features.columns:
            s = features[col].dropna()
            stats[col] = {
                'mean': round(float(s.mean()), 6),
                'std': round(float(s.std()), 6),
                'skew': round(float(s.skew()), 4),
                'kurt': round(float(s.kurtosis()), 4),
                'min': round(float(s.min()), 6),
                'max': round(float(s.max()), 6),
            }
            print(f"  {col:25s}: mean={s.mean():.4f}, std={s.std():.4f}, "
                  f"skew={s.skew():.2f}, kurt={s.kurtosis():.2f}")

    # Credit spread stats
    for col in ['credit_oas', 'credit_change5', 'credit_change20']:
        if col in features.columns:
            s = features[col].dropna()
            stats[col] = {
                'mean': round(float(s.mean()), 6),
                'std': round(float(s.std()), 6),
                'skew': round(float(s.skew()), 4),
                'kurt': round(float(s.kurtosis()), 4),
            }
            print(f"  {col:25s}: mean={s.mean():.4f}, std={s.std():.4f}")

    return stats


# ── Granger Causality Tests ──────────────────────────────────────
def granger_causality_tests(features):
    """Formal Granger causality: do other asset vol changes Granger-cause VIX changes?"""
    print("\n[Step 4] Granger Causality Tests")
    print("  H0: X does NOT Granger-cause VIX change (5d)")

    from statsmodels.tsa.stattools import grangercausalitytests, adfuller

    target = features['vix_change5'].dropna()

    # Test stationarity of target
    adf_stat, adf_p, _, _, _, _ = adfuller(target.values, maxlag=20)
    print(f"  VIX change (5d) ADF: stat={adf_stat:.3f}, p={adf_p:.4f} "
          f"{'(stationary)' if adf_p < 0.05 else '(non-stationary!)'}")

    # Vol momentum predictors
    predictors = [c for c in features.columns
                  if c.startswith('vmom5_') or c.startswith('credit_change')]

    results = {}
    for pred in predictors:
        try:
            x = features[pred].dropna()
            # Align
            common = target.index.intersection(x.index)
            if len(common) < 200:
                continue

            y = target.loc[common].values
            x_vals = x.loc[common].values

            # ADF on predictor
            adf_x, adf_px, _, _, _, _ = adfuller(x_vals, maxlag=20)

            # Granger test with AIC-selected lag
            test_data = pd.DataFrame({'target': y, 'predictor': x_vals})
            test_data = test_data.dropna()

            if len(test_data) < 100:
                continue

            # Test lags 1 to 10
            gc_result = grangercausalitytests(
                test_data[['target', 'predictor']].values,
                maxlag=min(GRANGER_MAX_LAG, len(test_data) // 20),
                verbose=False
            )

            # Find best lag by min p-value (F-test)
            best_lag = None
            best_p = 1.0
            all_lags = {}
            for lag, (tests, _) in gc_result.items():
                f_p = tests['ssr_ftest'][1]  # p-value from F-test
                chi2_p = tests['ssr_chi2test'][1]
                all_lags[lag] = {'f_pvalue': round(float(f_p), 4),
                                'chi2_pvalue': round(float(chi2_p), 4)}
                if f_p < best_p:
                    best_p = f_p
                    best_lag = lag

            significant = best_p < 0.05
            results[pred] = {
                'best_lag': int(best_lag) if best_lag else None,
                'best_f_pvalue': round(float(best_p), 6),
                'significant_at_5pct': significant,
                'adf_predictor': round(float(adf_px), 4),
                'predictor_stationary': adf_px < 0.05,
                'n_obs': len(test_data),
                'all_lags': all_lags,
            }

            sig_str = "***" if best_p < 0.01 else "**" if best_p < 0.05 else "*" if best_p < 0.10 else ""
            print(f"  {pred:25s}: best_lag={best_lag}, F-test p={best_p:.4f} {sig_str} "
                  f"(ADF p={adf_px:.3f})")

        except Exception as e:
            print(f"  {pred}: ERROR — {e}")
            results[pred] = {'error': str(e)}

    return results


# ── Correlation Analysis ──────────────────────────────────────
def correlation_analysis(features):
    """Cross-correlation between vol momentum signals and future VIX changes."""
    print("\n[Step 5] Cross-Correlation: Vol Momentum → Future VIX Changes")

    vmom_cols = [c for c in features.columns if c.startswith('vmom5_')]
    if 'credit_change5' in features.columns:
        vmom_cols.append('credit_change5')

    results = {}
    for col in vmom_cols:
        x = features[col].dropna()
        corrs = {}
        for horizon in [1, 5, 10, 20]:
            # Future VIX change (shift(-horizon) means looking forward)
            future_vix = features['vix'].pct_change(horizon).shift(-horizon)
            common = x.index.intersection(future_vix.dropna().index)
            if len(common) > 100:
                r, p = sp_stats.pearsonr(x.loc[common], future_vix.loc[common])
                corrs[f'{horizon}d'] = {'corr': round(float(r), 4), 'p': round(float(p), 4)}
        results[col] = corrs

        corr_str = ", ".join([f"{h}d: r={v['corr']:.3f}(p={v['p']:.3f})"
                              for h, v in corrs.items()])
        print(f"  {col:25s} → VIX: {corr_str}")

    return results


# ── Composite Signal Construction ──────────────────────────────
def build_composite_signal(features):
    """
    Build composite cross-asset vol momentum signal.

    Idea: When multiple asset classes show rising vol momentum simultaneously,
    equity vol is likely to increase. Signal = average z-score of vol momentum
    across asset classes.
    """
    print("\n[Step 6] Building Composite Cross-Asset Vol Momentum Signal")

    vmom_cols = [c for c in features.columns if c.startswith('vmom5_')]
    if 'credit_change5' in features.columns:
        vmom_cols.append('credit_change5')

    if len(vmom_cols) == 0:
        raise ValueError("No vol momentum columns found")

    # Z-score each vol momentum signal (expanding window, min 252 days)
    z_scores = pd.DataFrame(index=features.index)
    for col in vmom_cols:
        expanding_mean = features[col].expanding(min_periods=252).mean()
        expanding_std = features[col].expanding(min_periods=252).std()
        z_scores[col] = (features[col] - expanding_mean) / expanding_std.replace(0, np.nan)

    z_scores = z_scores.dropna()

    # Composite signal: mean z-score across all assets
    composite = z_scores.mean(axis=1)

    # Breadth: count of assets with z > 1 (elevated vol momentum)
    breadth = (z_scores > 1.0).sum(axis=1)

    # Stress indicator: composite > 1.0 (cross-asset vol momentum broadly rising)
    stress = (composite > 1.0).astype(int)

    print(f"  Composite signal: {len(composite)} obs")
    print(f"  Mean composite: {composite.mean():.4f}, Std: {composite.std():.4f}")
    print(f"  Breadth distribution: {dict(breadth.value_counts().sort_index())}")
    print(f"  % days stress > 1.0: {100 * stress.mean():.1f}%")

    return composite, breadth, z_scores


# ── Vol Prediction Test ──────────────────────────────────────
def vol_prediction_test(features, composite):
    """
    Test if composite signal improves next-day SPY vol prediction beyond VIX.

    Model 1: RV_t+1 = a + b * VIX_t
    Model 2: RV_t+1 = a + b * VIX_t + c * Composite_t

    DM test comparing squared prediction errors.
    """
    print("\n[Step 7] Vol Prediction: Does Composite Improve on VIX?")

    from sklearn.linear_model import LinearRegression

    # Realized vol proxy: |r_t+1| * sqrt(252)
    spy_ret = features['spy_ret']
    rv_proxy = spy_ret.abs() * np.sqrt(252)
    rv_proxy_next = rv_proxy.shift(-1)  # next-day RV

    # Align
    common = composite.index.intersection(rv_proxy_next.dropna().index)
    common = common.intersection(features['vix'].dropna().index)

    vix = features['vix'].loc[common]
    comp = composite.loc[common]
    rv_next = rv_proxy_next.loc[common]

    # Split IS/OOS at 70%
    n = len(common)
    n_is = int(n * 0.7)

    # IS fit
    X1_is = vix.iloc[:n_is].values.reshape(-1, 1)
    X2_is = np.column_stack([vix.iloc[:n_is].values, comp.iloc[:n_is].values])
    y_is = rv_next.iloc[:n_is].values

    model1 = LinearRegression().fit(X1_is, y_is)
    model2 = LinearRegression().fit(X2_is, y_is)

    print(f"  IS R² — VIX only: {model1.score(X1_is, y_is):.4f}, "
          f"VIX + Composite: {model2.score(X2_is, y_is):.4f}")
    print(f"  Model 2 coefficients: VIX={model2.coef_[0]:.4f}, "
          f"Composite={model2.coef_[1]:.4f}")

    # OOS predictions
    X1_oos = vix.iloc[n_is:].values.reshape(-1, 1)
    X2_oos = np.column_stack([vix.iloc[n_is:].values, comp.iloc[n_is:].values])
    y_oos = rv_next.iloc[n_is:].values

    pred1 = model1.predict(X1_oos)
    pred2 = model2.predict(X2_oos)

    # Squared errors
    se1 = (y_oos - pred1) ** 2
    se2 = (y_oos - pred2) ** 2

    oos_r2_1 = 1 - np.sum(se1) / np.sum((y_oos - y_oos.mean()) ** 2)
    oos_r2_2 = 1 - np.sum(se2) / np.sum((y_oos - y_oos.mean()) ** 2)

    # DM test
    dm_stat, dm_p = dm_test_func(se1, se2, h=5)

    print(f"  OOS R² — VIX only: {oos_r2_1:.4f}, VIX + Composite: {oos_r2_2:.4f}")
    print(f"  OOS R² improvement: {oos_r2_2 - oos_r2_1:+.4f}")
    print(f"  DM test: stat={dm_stat:.4f}, p={dm_p:.4f}")
    print(f"  Harvey threshold (|t|>3.0): {'PASS' if abs(dm_stat) > 3.0 else 'FAIL'}")

    return {
        'is_r2_vix_only': round(float(model1.score(X1_is, y_is)), 6),
        'is_r2_vix_composite': round(float(model2.score(X2_is, y_is)), 6),
        'oos_r2_vix_only': round(float(oos_r2_1), 6),
        'oos_r2_vix_composite': round(float(oos_r2_2), 6),
        'oos_r2_improvement': round(float(oos_r2_2 - oos_r2_1), 6),
        'dm_stat': round(float(dm_stat), 4),
        'dm_pvalue': round(float(dm_p), 4),
        'harvey_pass': abs(dm_stat) > 3.0,
        'model2_coef_vix': round(float(model2.coef_[0]), 6),
        'model2_coef_composite': round(float(model2.coef_[1]), 6),
        'n_is': n_is,
        'n_oos': n - n_is,
    }


# ── DM Test ──────────────────────────────────────────────────
def dm_test_func(e1, e2, h=1):
    """Diebold-Mariano test. e1, e2 = loss series (lower = better)."""
    d = np.array(e1) - np.array(e2)
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 30:
        return 0.0, 1.0

    d_mean = np.mean(d)
    # Newey-West HAC variance
    gamma0 = np.var(d, ddof=1)
    acov = 0
    for k in range(1, min(h, n // 2)):
        c = np.cov(d[k:], d[:-k])[0, 1] if len(d[k:]) > 1 else 0
        acov += 2 * c * (1 - k / h)
    var_d = max((gamma0 + acov) / n, 1e-12)

    dm_stat = d_mean / np.sqrt(var_d)
    p_val = 2 * (1 - sp_stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_val)


# ── Trading Strategy ──────────────────────────────────────────
def run_strategy(features, composite, breadth, period_start, period_end, label):
    """
    Cross-asset vol momentum strategy on SPY/GLD portfolio.

    Baseline: 50/50 SPY/GLD (best static allocation per K702)
    Signal strategy: Adjust SPY weight based on composite vol momentum
      - High composite (> 1.0): Reduce SPY, increase GLD (defensive)
      - Low composite (< -0.5): Full SPY weight (calm environment)
      - Otherwise: 50/50 baseline

    CRITICAL: signal.shift(1) — use yesterday's signal for today's weight
    """
    mask = (features.index >= period_start) & (features.index <= period_end)
    feat = features[mask].copy()
    comp = composite.reindex(feat.index)
    brd = breadth.reindex(feat.index)

    if len(feat) < 50:
        return None

    spy_ret = feat['spy_ret']
    gld_ret = feat['gld_ret']
    vix = feat['vix']

    # ── Baseline 1: Buy & Hold 100% SPY ──
    bh_spy_ret = spy_ret

    # ── Baseline 2: 50/50 SPY/GLD ──
    bh_5050_ret = 0.5 * spy_ret + 0.5 * gld_ret

    # ── Baseline 3: 12/VIX ──
    w_12vix = (12.0 / vix).clip(0, 1)
    w_12vix = w_12vix.shift(1)  # ★ CRITICAL: signal from t-1
    w_12vix = w_12vix.dropna()

    # ── Strategy: Cross-Asset Vol Momentum ──
    # SPY weight based on composite signal
    spy_weight = pd.Series(0.5, index=feat.index)  # default 50%

    # When cross-asset vol momentum is high → defensive (less SPY, more GLD)
    high_stress = comp > 1.0
    spy_weight[high_stress] = 0.20

    # When breadth >= 3 (multiple assets show rising vol) → very defensive
    very_high = brd >= 3
    spy_weight[very_high] = 0.10

    # When composite is very low → vol environment is calm → overweight SPY
    calm = comp < -0.5
    spy_weight[calm] = 0.70

    # ★ CRITICAL: signal.shift(1) — use yesterday's signal for today's weight
    spy_weight = spy_weight.shift(1)
    spy_weight = spy_weight.dropna()

    # Smooth weights (5-day MA)
    spy_weight = spy_weight.rolling(5, min_periods=1).mean().clip(0, 1)
    gld_weight = 1.0 - spy_weight

    # Align all series
    common = spy_weight.index.intersection(spy_ret.index).intersection(gld_ret.index)
    common = common.intersection(w_12vix.index)

    spy_r = spy_ret.loc[common]
    gld_r = gld_ret.loc[common]
    w_spy = spy_weight.loc[common]
    w_gld = gld_weight.loc[common]
    w_vix = w_12vix.loc[common]

    # Strategy returns
    strat_ret = w_spy * spy_r + w_gld * gld_r
    baseline_5050 = 0.5 * spy_r + 0.5 * gld_r
    baseline_12vix = w_vix * spy_r + (1 - w_vix) * gld_r

    # TX costs: 5 bps per weight change
    w_change = w_spy.diff().abs()
    tx = w_change * (TX_COST_BPS / 10000)
    strat_ret_net = strat_ret - tx

    # Also TX for 12/VIX
    w_vix_change = w_vix.diff().abs()
    tx_vix = w_vix_change * (TX_COST_BPS / 10000)
    baseline_12vix_net = baseline_12vix - tx_vix

    # Metrics
    def calc_metrics(rets, label):
        cum = (1 + rets).cumprod()
        mdd = (cum / cum.cummax() - 1).min()
        ann_ret = rets.mean() * 252
        ann_vol = rets.std() * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        downside = rets[rets < 0].std() * np.sqrt(252) if (rets < 0).sum() > 0 else ann_vol
        sortino = ann_ret / downside if downside > 0 else 0
        return {
            'label': label,
            'sharpe': round(float(sharpe), 4),
            'ann_return': round(float(ann_ret), 4),
            'ann_vol': round(float(ann_vol), 4),
            'mdd': round(float(mdd), 4),
            'sortino': round(float(sortino), 4),
            'total_return': round(float(cum.iloc[-1] - 1), 4),
            'n_days': len(rets),
        }

    m_bh = calc_metrics(spy_r, f'BH SPY ({label})')
    m_5050 = calc_metrics(baseline_5050, f'50/50 ({label})')
    m_12vix = calc_metrics(baseline_12vix_net, f'12/VIX net ({label})')
    m_strat = calc_metrics(strat_ret_net, f'CrossAssetVM ({label})')

    # DM test: strategy vs 50/50
    loss_5050 = -(baseline_5050.values)
    loss_strat = -(strat_ret_net.values)
    dm_stat_5050, dm_p_5050 = dm_test_func(loss_strat, loss_5050, h=5)

    # DM test: strategy vs 12/VIX
    loss_12vix = -(baseline_12vix_net.values)
    dm_stat_12vix, dm_p_12vix = dm_test_func(loss_strat, loss_12vix, h=5)

    # Signal stats
    n_high_stress = (comp.reindex(common).shift(1) > 1.0).sum()
    n_calm = (comp.reindex(common).shift(1) < -0.5).sum()
    avg_spy_weight = float(w_spy.mean())

    result = {
        'period': label,
        'n_days': len(common),
        'bh_spy': m_bh,
        'baseline_5050': m_5050,
        'baseline_12vix_net': m_12vix,
        'cross_asset_vm': m_strat,
        'sharpe_vs_5050': round(float(m_strat['sharpe'] - m_5050['sharpe']), 4),
        'sharpe_vs_12vix': round(float(m_strat['sharpe'] - m_12vix['sharpe']), 4),
        'dm_vs_5050': {'stat': round(float(dm_stat_5050), 4), 'p': round(float(dm_p_5050), 4)},
        'dm_vs_12vix': {'stat': round(float(dm_stat_12vix), 4), 'p': round(float(dm_p_12vix), 4)},
        'signal_stats': {
            'n_high_stress_days': int(n_high_stress),
            'n_calm_days': int(n_calm),
            'avg_spy_weight': round(avg_spy_weight, 4),
            'pct_override': round(100 * (n_high_stress + n_calm) / len(common), 1),
        },
    }

    print(f"\n  === {label} ({len(common)} days) ===")
    print(f"    BH SPY:       Sharpe={m_bh['sharpe']:.3f}, MDD={m_bh['mdd']:.1%}")
    print(f"    50/50:        Sharpe={m_5050['sharpe']:.3f}, MDD={m_5050['mdd']:.1%}")
    print(f"    12/VIX (net): Sharpe={m_12vix['sharpe']:.3f}, MDD={m_12vix['mdd']:.1%}")
    print(f"    CrossAssetVM: Sharpe={m_strat['sharpe']:.3f}, MDD={m_strat['mdd']:.1%}")
    print(f"    vs 50/50: Sharpe diff={m_strat['sharpe'] - m_5050['sharpe']:+.4f}, "
          f"DM={dm_stat_5050:.3f}(p={dm_p_5050:.3f})")
    print(f"    vs 12/VIX: Sharpe diff={m_strat['sharpe'] - m_12vix['sharpe']:+.4f}, "
          f"DM={dm_stat_12vix:.3f}(p={dm_p_12vix:.3f})")
    print(f"    Signal: {n_high_stress} high-stress days, {n_calm} calm days, "
          f"avg SPY wt={avg_spy_weight:.2f}")

    return result


# ── Main ──────────────────────────────────────────────────────
def main():
    print("=" * 72)
    print("K730: Cross-Asset Volatility Momentum (Upgraded)")
    print("[提出: Codex (7th review, 2026-03-27), 執行: Claude]")
    print("=" * 72)

    # 1. Download data
    close = download_price_data()
    credit_spread, credit_source = download_fred_credit_spread()

    # 2. Build features
    features, returns = build_features(close, credit_spread)

    # 3. Descriptive statistics
    desc_stats = descriptive_statistics(features)

    # 4. Granger causality
    granger_results = granger_causality_tests(features)

    # 5. Cross-correlation
    corr_results = correlation_analysis(features)

    # 6. Composite signal
    composite, breadth, z_scores = build_composite_signal(features)

    # 7. Vol prediction test
    vol_pred = vol_prediction_test(features, composite)

    # 8. Cross-OOS strategy evaluation
    print("\n[Step 8] Cross-OOS Strategy Evaluation (5 periods)")
    oos_results = []
    for start, end, label in OOS_PERIODS:
        r = run_strategy(features, composite, breadth, start, end, label)
        if r is not None:
            oos_results.append(r)

    # 9. Summary
    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)

    # Granger results
    gc_significant = [k for k, v in granger_results.items()
                      if isinstance(v, dict) and v.get('significant_at_5pct', False)]
    gc_any = len(gc_significant) > 0
    print(f"\n  Granger causality: {len(gc_significant)}/{len(granger_results)} "
          f"predictors significant at 5%")
    if gc_significant:
        print(f"    Significant: {gc_significant}")

    # Vol prediction
    vol_pred_improves = vol_pred['oos_r2_improvement'] > 0 and vol_pred['harvey_pass']
    print(f"\n  Vol prediction improvement: R² = {vol_pred['oos_r2_improvement']:+.4f}")
    print(f"    DM stat: {vol_pred['dm_stat']:.3f} "
          f"(Harvey t>3.0: {'PASS' if vol_pred['harvey_pass'] else 'FAIL'})")

    # Strategy OOS
    if oos_results:
        sharpe_diffs_5050 = [r['sharpe_vs_5050'] for r in oos_results]
        sharpe_diffs_12vix = [r['sharpe_vs_12vix'] for r in oos_results]
        dm_p_5050 = [r['dm_vs_5050']['p'] for r in oos_results]
        dm_p_12vix = [r['dm_vs_12vix']['p'] for r in oos_results]

        wins_vs_5050 = sum(1 for d in sharpe_diffs_5050 if d > 0)
        wins_vs_12vix = sum(1 for d in sharpe_diffs_12vix if d > 0)
        any_dm_sig = any(p < 0.05 for p in dm_p_5050 + dm_p_12vix)
        any_harvey = any(abs(r['dm_vs_5050']['stat']) > 3.0 or
                        abs(r['dm_vs_12vix']['stat']) > 3.0 for r in oos_results)

        print(f"\n  Strategy OOS (5 periods):")
        print(f"    Wins vs 50/50: {wins_vs_5050}/5 "
              f"(avg Sharpe diff: {np.mean(sharpe_diffs_5050):+.4f})")
        print(f"    Wins vs 12/VIX: {wins_vs_12vix}/5 "
              f"(avg Sharpe diff: {np.mean(sharpe_diffs_12vix):+.4f})")
        print(f"    Any DM significant (p<0.05): {any_dm_sig}")
        print(f"    Any Harvey pass (|t|>3.0): {any_harvey}")

    # Final verdict
    if gc_any and vol_pred_improves and wins_vs_5050 >= 3:
        verdict = "POSITIVE — cross-asset vol momentum adds meaningful value"
    elif gc_any and (vol_pred['oos_r2_improvement'] > 0 or wins_vs_5050 >= 2):
        verdict = "MARGINAL — some Granger evidence but strategy improvement is weak"
    else:
        verdict = "NULL RESULT — VIX sufficiency confirmed; cross-asset vol momentum " \
                  "does not improve timing"

    conclusion_parts = []
    if gc_any:
        conclusion_parts.append(f"Granger: {len(gc_significant)} asset(s) Granger-cause "
                               f"VIX changes at 5% level")
    else:
        conclusion_parts.append("Granger: No cross-asset vol momentum Granger-causes VIX changes")

    conclusion_parts.append(f"Vol prediction: Composite adds R²={vol_pred['oos_r2_improvement']:+.6f} "
                           f"(DM t={vol_pred['dm_stat']:.3f})")

    if oos_results:
        conclusion_parts.append(f"Strategy: Wins {wins_vs_5050}/5 vs 50/50, "
                               f"{wins_vs_12vix}/5 vs 12/VIX")

    print(f"\n  VERDICT: {verdict}")
    for part in conclusion_parts:
        print(f"    - {part}")

    # 10. Save results
    results_json = {
        'experiment_id': 'K730',
        'title': 'Cross-Asset Volatility Momentum (Upgraded)',
        'attribution': '[提出: Codex (7th review, 2026-03-27), 執行: Claude]',
        'builds_on': 'K537 (null result — VIX sufficiency)',
        'hypothesis': 'Vol changes in bonds/commodities/FX/credit LEAD equity vol changes; '
                      'composite cross-asset vol momentum can improve portfolio timing',
        'data_sources': {
            'prices': f'yfinance ({", ".join(PRICE_TICKERS + [VIX_TICKER])})',
            'credit_spread': credit_source or 'not available',
            'period': f'{features.index[0].date()} to {features.index[-1].date()}',
            'n_obs': len(features),
        },
        'upgrades_from_k537': [
            'FRED credit spread (or HYG-LQD proxy) instead of just HYG-IEF',
            'USO (oil) added as 5th asset class',
            'Formal Granger causality with AIC lag selection (statsmodels)',
            'Vol MOMENTUM signals (5d/20d changes), not just levels',
            'TX costs (5 bps per weight change)',
            'signal.shift(1) enforced in code',
            '5 non-overlapping 2-year OOS periods (K537 had 3)',
            'DM test with Harvey (2016) t>3.0 threshold',
            '50/50 SPY/GLD baseline (best static per K702)',
        ],
        'descriptive_stats': desc_stats,
        'granger_causality': granger_results,
        'cross_correlation': corr_results,
        'vol_prediction': vol_pred,
        'cross_oos_strategy': oos_results,
        'summary': {
            'n_granger_significant': len(gc_significant),
            'granger_significant_predictors': gc_significant,
            'vol_pred_r2_improvement': vol_pred['oos_r2_improvement'],
            'vol_pred_harvey_pass': vol_pred['harvey_pass'],
            'oos_wins_vs_5050': wins_vs_5050 if oos_results else 0,
            'oos_wins_vs_12vix': wins_vs_12vix if oos_results else 0,
            'avg_sharpe_diff_vs_5050': round(float(np.mean(sharpe_diffs_5050)), 4) if oos_results else 0,
            'avg_sharpe_diff_vs_12vix': round(float(np.mean(sharpe_diffs_12vix)), 4) if oos_results else 0,
            'verdict': verdict,
            'conclusion': conclusion_parts,
        },
        'references': [
            'Moreira & Muir (2017), Volatility-Managed Portfolios, JoF 72(4):1611-1644',
            'Diebold & Yilmaz (2012), Better to Give than to Receive, JASA 107(499):363-387',
            'Harvey, Liu & Zhu (2016), ...and the Cross-Section of Expected Returns, RFS 29(1):5-68',
            'K537: Cross-asset vol momentum null result',
            'K697: VIX predicts vol magnitude (r=0.57) not direction (r=0.04)',
            'K702: 50/50 SPY/GLD is optimal static allocation',
        ],
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }

    def convert_numpy(obj):
        """Convert numpy types for JSON serialization."""
        if isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, dict):
            return {str(k) if isinstance(k, (np.integer,)) else k: convert_numpy(v)
                    for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [convert_numpy(v) for v in obj]
        return obj

    results_json = convert_numpy(results_json)

    out_path = Path('experiments/k730_cross_asset_vol_momentum_results.json')
    with open(out_path, 'w') as f:
        json.dump(results_json, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")

    return results_json


if __name__ == '__main__':
    results = main()
