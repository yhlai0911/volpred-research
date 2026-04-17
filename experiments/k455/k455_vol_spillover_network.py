"""
K455: Volatility Spillover Network US → Asia
Diebold-Yilmaz (2009, 2012) Spillover Index

Research Questions:
1. How strong is US vol spillover to Asian markets?
2. Does spillover vary over time (crisis vs calm)?
3. Which Asian market is most affected by US vol?
4. Is vol spillover more stable than return spillover?

Assets: SPY (US), EWJ (Japan), EWT (Taiwan), EWY (Korea), EWH (HK), EWA (Australia), FXI (China)
All US-listed ETFs to avoid timezone issues.

Method: VAR forecast error variance decomposition (Diebold-Yilmaz 2009)
Data: yfinance, 2007-2026, squared returns as vol proxy

Prior work:
- K7: Granger-based vol spillover network (SPY dominant hub, TW50 most affected)
- K84: Vol spillover statistically significant but economically insignificant
- T32/T33: US→Asia lead-lag confirmed (SPY→N225 r=+0.419)
- This experiment uses FEVD framework (different from Granger approach)

[提出: Claude(K455), 執行: Claude]
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from statsmodels.tsa.api import VAR
from scipy import stats
import warnings
warnings.filterwarnings('ignore')


def download_data(tickers, start='2007-01-01', end='2026-03-26'):
    """Download and align data for all tickers."""
    print(f"Downloading data for {tickers} from {start} to {end}...")
    data = yf.download(tickers, start=start, end=end, auto_adjust=True)

    # Handle multi-level columns from yfinance
    if isinstance(data.columns, pd.MultiIndex):
        close = data['Close']
    else:
        close = data

    # Drop rows with any NaN
    close = close.dropna()

    # Calculate returns
    returns = close.pct_change().dropna()

    print(f"Data shape: {returns.shape}, Period: {returns.index[0].strftime('%Y-%m-%d')} to {returns.index[-1].strftime('%Y-%m-%d')}")
    return returns


def descriptive_stats(returns):
    """Diagnostic: descriptive statistics for all series."""
    stats_dict = {}
    for col in returns.columns:
        s = returns[col]
        stats_dict[col] = {
            'n': len(s),
            'mean': float(s.mean()),
            'std': float(s.std()),
            'skew': float(s.skew()),
            'kurtosis': float(s.kurtosis()),
            'min': float(s.min()),
            'max': float(s.max()),
        }
    return stats_dict


def adf_test(series):
    """Augmented Dickey-Fuller test."""
    from statsmodels.tsa.stattools import adfuller
    result = adfuller(series, autolag='AIC')
    return {'adf_stat': float(result[0]), 'p_value': float(result[1]), 'stationary': result[1] < 0.05}


def diebold_yilmaz_spillover(data_df, var_lag=5, forecast_h=10):
    """
    Diebold-Yilmaz (2009) Spillover Index based on generalized FEVD.

    Uses Pesaran & Shin (1998) generalized impulse responses (order-invariant).

    Parameters:
    -----------
    data_df : DataFrame of (squared) returns
    var_lag : int, VAR lag order
    forecast_h : int, forecast horizon for FEVD

    Returns:
    --------
    dict with total_spillover, from_others, to_others, net, pairwise table
    """
    # Fit VAR
    model = VAR(data_df)
    result = model.fit(maxlags=var_lag, ic=None)

    n = data_df.shape[1]
    names = list(data_df.columns)

    # Get coefficient matrices and residual covariance
    # VAR(p): y_t = A_1 y_{t-1} + ... + A_p y_{t-p} + u_t
    # Companion form for MA representation

    # Compute generalized FEVD (Pesaran & Shin 1998)
    # This is order-invariant unlike Cholesky-based FEVD

    sigma = np.array(result.sigma_u)  # residual covariance (n x n)

    # Get MA coefficients via IRF
    # irf_coefs[h] is the n x n matrix Psi_h
    irf = result.irf(forecast_h)
    ma_coefs = irf.irfs  # shape: (forecast_h+1, n, n)

    # Generalized FEVD (Pesaran & Shin 1998)
    # theta_{ij}^g(H) = sigma_{jj}^{-1} * sum_{h=0}^{H-1} (e_i' Psi_h Sigma e_j)^2
    #                  / sum_{h=0}^{H-1} (e_i' Psi_h Sigma Psi_h' e_i)

    theta = np.zeros((n, n))

    for i in range(n):
        # Denominator: total forecast error variance of variable i
        denom = 0.0
        for h in range(forecast_h):
            psi_h = ma_coefs[h]  # (n, n)
            denom += psi_h[i, :] @ sigma @ psi_h[i, :]

        for j in range(n):
            # Numerator: contribution of shock j to FEV of i
            numer = 0.0
            for h in range(forecast_h):
                psi_h = ma_coefs[h]
                numer += (psi_h[i, :] @ sigma[:, j]) ** 2

            theta[i, j] = (1.0 / sigma[j, j]) * numer / denom if denom > 0 else 0.0

    # Normalize rows to sum to 1 (generalized FEVD doesn't guarantee this)
    row_sums = theta.sum(axis=1, keepdims=True)
    theta_norm = theta / row_sums

    # Total spillover index
    total_spillover = (theta_norm.sum() - np.trace(theta_norm)) / n * 100

    # Directional spillover: FROM others to i
    from_others = {}
    for i, name in enumerate(names):
        from_others[name] = float((theta_norm[i, :].sum() - theta_norm[i, i]) / n * 100)

    # Directional spillover: TO others from j
    to_others = {}
    for j, name in enumerate(names):
        to_others[name] = float((theta_norm[:, j].sum() - theta_norm[j, j]) / n * 100)

    # Net spillover
    net = {}
    for name in names:
        net[name] = to_others[name] - from_others[name]

    # Pairwise table
    table = {}
    for i, ni in enumerate(names):
        table[ni] = {}
        for j, nj in enumerate(names):
            table[ni][nj] = float(theta_norm[i, j] * 100)

    return {
        'total_spillover': float(total_spillover),
        'from_others': from_others,
        'to_others': to_others,
        'net': net,
        'table': table,
        'var_lag': var_lag,
        'forecast_h': forecast_h,
        'n_obs': len(data_df),
        'convergence': True
    }


def rolling_spillover(data_df, window=252, step=21, var_lag=5, forecast_h=10):
    """
    Rolling window Diebold-Yilmaz spillover index.

    Parameters:
    -----------
    window : int, rolling window size (252 = 1 year)
    step : int, step size (21 = ~1 month)
    """
    n_obs = len(data_df)
    results = []

    dates = []
    total_spillovers = []
    from_spy = []

    names = list(data_df.columns)

    print(f"Rolling spillover: window={window}, step={step}, total windows={(n_obs - window) // step + 1}")

    for start in range(0, n_obs - window, step):
        end = start + window
        window_data = data_df.iloc[start:end]

        try:
            sp = diebold_yilmaz_spillover(window_data, var_lag=var_lag, forecast_h=forecast_h)

            date_str = data_df.index[end - 1].strftime('%Y-%m-%d')
            dates.append(date_str)
            total_spillovers.append(sp['total_spillover'])

            # Track SPY's net spillover (positive = net transmitter)
            from_spy.append(sp['net'].get('SPY', 0))

            results.append({
                'date': date_str,
                'total_spillover': sp['total_spillover'],
                'spy_net': sp['net'].get('SPY', 0),
                'from_others': sp['from_others'],
                'to_others': sp['to_others'],
                'net': sp['net']
            })
        except Exception as e:
            continue

    print(f"Computed {len(results)} rolling windows")
    return results


def crisis_vs_calm_analysis(rolling_results):
    """
    Compare spillover during crisis vs calm periods.
    Crisis periods: GFC (2008-2009), COVID (2020-03 to 2020-06),
    2022 rate hikes (2022-01 to 2022-10)
    """
    crisis_periods = [
        ('GFC', '2008-01-01', '2009-06-30'),
        ('COVID', '2020-02-01', '2020-06-30'),
        ('Rate_Hikes_2022', '2022-01-01', '2022-10-31'),
    ]

    crisis_spillovers = {}
    calm_spillovers = []

    for r in rolling_results:
        date = r['date']
        is_crisis = False
        for name, start, end in crisis_periods:
            if start <= date <= end:
                if name not in crisis_spillovers:
                    crisis_spillovers[name] = []
                crisis_spillovers[name].append(r['total_spillover'])
                is_crisis = True
                break
        if not is_crisis:
            calm_spillovers.append(r['total_spillover'])

    analysis = {
        'calm': {
            'mean': float(np.mean(calm_spillovers)),
            'std': float(np.std(calm_spillovers)),
            'n': len(calm_spillovers)
        }
    }

    for name, spills in crisis_spillovers.items():
        if len(spills) > 0:
            crisis_mean = np.mean(spills)
            calm_mean = np.mean(calm_spillovers)

            # Welch t-test: crisis vs calm
            if len(spills) > 1:
                t_stat, p_val = stats.ttest_ind(spills, calm_spillovers, equal_var=False)
            else:
                t_stat, p_val = np.nan, np.nan

            analysis[name] = {
                'mean': float(crisis_mean),
                'std': float(np.std(spills)),
                'n': len(spills),
                'diff_vs_calm': float(crisis_mean - calm_mean),
                't_stat': float(t_stat) if not np.isnan(t_stat) else None,
                'p_value': float(p_val) if not np.isnan(p_val) else None
            }

    return analysis


def return_vs_vol_spillover(returns_df):
    """
    Compare spillover based on returns vs squared returns (vol proxy).
    """
    print("\n=== Return Spillover ===")
    return_sp = diebold_yilmaz_spillover(returns_df, var_lag=5, forecast_h=10)

    print("\n=== Volatility Spillover (squared returns) ===")
    vol_df = returns_df ** 2
    vol_sp = diebold_yilmaz_spillover(vol_df, var_lag=5, forecast_h=10)

    # Also try absolute returns as vol proxy
    print("\n=== Volatility Spillover (absolute returns) ===")
    abs_df = returns_df.abs()
    abs_sp = diebold_yilmaz_spillover(abs_df, var_lag=5, forecast_h=10)

    return {
        'return_spillover': {
            'total': return_sp['total_spillover'],
            'net': return_sp['net'],
            'from_others': return_sp['from_others'],
            'to_others': return_sp['to_others']
        },
        'vol_spillover_sq': {
            'total': vol_sp['total_spillover'],
            'net': vol_sp['net'],
            'from_others': vol_sp['from_others'],
            'to_others': vol_sp['to_others']
        },
        'vol_spillover_abs': {
            'total': abs_sp['total_spillover'],
            'net': abs_sp['net'],
            'from_others': abs_sp['from_others'],
            'to_others': abs_sp['to_others']
        }
    }


def pairwise_us_to_asia(spillover_result, us_ticker='SPY'):
    """Extract pairwise US → Asia spillover from the full table."""
    table = spillover_result['table']
    names = list(table.keys())
    asia_tickers = [n for n in names if n != us_ticker]

    pairwise = {}
    for asia in asia_tickers:
        # table[asia][us_ticker] = % of asia's FEV explained by US shocks
        us_to_asia = table[asia][us_ticker]
        asia_to_us = table[us_ticker][asia]
        pairwise[asia] = {
            'us_to_asia': float(us_to_asia),
            'asia_to_us': float(asia_to_us),
            'net_us_to_asia': float(us_to_asia - asia_to_us),
            'own_share': float(table[asia][asia])
        }

    return pairwise


def rolling_stability_test(rolling_results, returns_df, window=252, step=21, var_lag=5, forecast_h=10):
    """
    Compare stability: rolling return spillover vs rolling vol spillover.
    Measure coefficient of variation (CV) of total spillover over time.
    """
    vol_df = returns_df ** 2

    # We already have vol rolling results
    vol_totals = [r['total_spillover'] for r in rolling_results]

    # Compute rolling return spillover
    n_obs = len(returns_df)
    ret_totals = []

    for start in range(0, n_obs - window, step):
        end = start + window
        window_data = returns_df.iloc[start:end]
        try:
            sp = diebold_yilmaz_spillover(window_data, var_lag=var_lag, forecast_h=forecast_h)
            ret_totals.append(sp['total_spillover'])
        except:
            continue

    # Match lengths
    min_len = min(len(vol_totals), len(ret_totals))
    vol_totals = vol_totals[:min_len]
    ret_totals = ret_totals[:min_len]

    vol_cv = float(np.std(vol_totals) / np.mean(vol_totals)) if np.mean(vol_totals) > 0 else np.nan
    ret_cv = float(np.std(ret_totals) / np.mean(ret_totals)) if np.mean(ret_totals) > 0 else np.nan

    # Correlation between return and vol spillover over time
    corr = float(np.corrcoef(vol_totals, ret_totals)[0, 1])

    return {
        'vol_spillover_cv': vol_cv,
        'ret_spillover_cv': ret_cv,
        'vol_more_stable': vol_cv < ret_cv,
        'vol_mean': float(np.mean(vol_totals)),
        'vol_std': float(np.std(vol_totals)),
        'ret_mean': float(np.mean(ret_totals)),
        'ret_std': float(np.std(ret_totals)),
        'correlation_vol_ret_spillover': corr,
        'n_windows': min_len
    }


def optimal_var_lag(data_df, max_lag=10):
    """Select optimal VAR lag using information criteria."""
    model = VAR(data_df)
    results = {}
    for ic in ['aic', 'bic', 'hqic']:
        try:
            selected = model.select_order(maxlags=max_lag)
            results[ic] = int(getattr(selected, ic))
        except:
            results[ic] = 5  # default
    return results


def main():
    print("=" * 70)
    print("K455: Volatility Spillover Network US → Asia")
    print("Method: Diebold-Yilmaz (2009, 2012) Spillover Index")
    print("=" * 70)

    # ---- 1. Data Download ----
    tickers = ['SPY', 'EWJ', 'EWT', 'EWY', 'EWH', 'EWA', 'FXI']
    returns = download_data(tickers, start='2007-01-01', end='2026-03-26')

    # ---- 2. Descriptive Statistics (Diagnostic) ----
    print("\n--- Descriptive Statistics ---")
    desc_stats = descriptive_stats(returns)
    for ticker, st in desc_stats.items():
        print(f"  {ticker}: mean={st['mean']*100:.3f}%/d, std={st['std']*100:.2f}%/d, "
              f"skew={st['skew']:.2f}, kurt={st['kurtosis']:.2f}, n={st['n']}")

    # ADF tests (returns should be stationary)
    print("\n--- ADF Tests (Returns) ---")
    adf_results = {}
    for col in returns.columns:
        adf = adf_test(returns[col])
        adf_results[col] = adf
        print(f"  {col}: ADF={adf['adf_stat']:.2f}, p={adf['p_value']:.4f}, stationary={adf['stationary']}")

    # ADF tests for squared returns
    print("\n--- ADF Tests (Squared Returns / Vol Proxy) ---")
    sq_returns = returns ** 2
    adf_sq_results = {}
    for col in sq_returns.columns:
        adf = adf_test(sq_returns[col])
        adf_sq_results[col] = adf
        print(f"  {col}: ADF={adf['adf_stat']:.2f}, p={adf['p_value']:.4f}, stationary={adf['stationary']}")

    # ---- 3. Optimal VAR Lag Selection ----
    print("\n--- VAR Lag Selection (squared returns) ---")
    lag_selection = optimal_var_lag(sq_returns, max_lag=10)
    print(f"  AIC: {lag_selection['aic']}, BIC: {lag_selection['bic']}, HQIC: {lag_selection['hqic']}")
    var_lag = lag_selection['bic']  # Use BIC for parsimony
    print(f"  Using lag = {var_lag} (BIC)")

    # ---- 4. Full-Sample Spillover Index ----
    print("\n" + "=" * 70)
    print("4. FULL-SAMPLE DIEBOLD-YILMAZ SPILLOVER INDEX")
    print("=" * 70)

    # Vol spillover (squared returns)
    print("\n--- Volatility Spillover (squared returns) ---")
    vol_sp = diebold_yilmaz_spillover(sq_returns, var_lag=var_lag, forecast_h=10)

    print(f"\n  Total Spillover Index: {vol_sp['total_spillover']:.1f}%")
    print(f"\n  Directional: FROM others | TO others | NET")
    for name in tickers:
        f = vol_sp['from_others'][name]
        t = vol_sp['to_others'][name]
        n = vol_sp['net'][name]
        role = "NET TRANSMITTER" if n > 0 else "NET RECEIVER"
        print(f"  {name:5s}: {f:6.1f}% | {t:6.1f}% | {n:+6.1f}% ({role})")

    # Spillover table
    print(f"\n  Spillover Table (% of FEV of row explained by column shock):")
    header = "       " + "  ".join(f"{t:>7s}" for t in tickers)
    print(header)
    for i, ti in enumerate(tickers):
        row = f"  {ti:5s}"
        for j, tj in enumerate(tickers):
            val = vol_sp['table'][ti][tj]
            row += f"  {val:7.1f}"
        row += f"  | FROM={vol_sp['from_others'][ti]:.1f}%"
        print(row)
    to_row = "  TO   "
    for tj in tickers:
        to_row += f"  {vol_sp['to_others'][tj]:7.1f}"
    print(to_row)

    # ---- 5. Pairwise US → Asia ----
    print("\n" + "=" * 70)
    print("5. PAIRWISE US → ASIA SPILLOVER")
    print("=" * 70)

    pairwise = pairwise_us_to_asia(vol_sp, us_ticker='SPY')
    print(f"\n  {'Market':6s} | US→Asia | Asia→US | Net(US→) | Own%")
    print(f"  {'-'*50}")
    for asia, pw in sorted(pairwise.items(), key=lambda x: -x[1]['net_us_to_asia']):
        print(f"  {asia:6s} | {pw['us_to_asia']:6.1f}%  | {pw['asia_to_us']:6.1f}%  | {pw['net_us_to_asia']:+6.1f}%  | {pw['own_share']:.1f}%")

    # ---- 6. Rolling Spillover ----
    print("\n" + "=" * 70)
    print("6. ROLLING SPILLOVER (252-day window, 21-day step)")
    print("=" * 70)

    rolling_results = rolling_spillover(sq_returns, window=252, step=21, var_lag=var_lag, forecast_h=10)

    if rolling_results:
        totals = [r['total_spillover'] for r in rolling_results]
        spy_nets = [r['spy_net'] for r in rolling_results]

        print(f"\n  Total Spillover - Mean: {np.mean(totals):.1f}%, Std: {np.std(totals):.1f}%")
        print(f"  Total Spillover - Min: {np.min(totals):.1f}%, Max: {np.max(totals):.1f}%")
        print(f"  SPY Net Spillover - Mean: {np.mean(spy_nets):.1f}%, always positive: {all(s > 0 for s in spy_nets)}")

        # Find peak spillover dates
        max_idx = np.argmax(totals)
        min_idx = np.argmin(totals)
        print(f"\n  Peak spillover: {totals[max_idx]:.1f}% on {rolling_results[max_idx]['date']}")
        print(f"  Min spillover: {totals[min_idx]:.1f}% on {rolling_results[min_idx]['date']}")

    # ---- 7. Crisis vs Calm ----
    print("\n" + "=" * 70)
    print("7. CRISIS VS CALM PERIODS")
    print("=" * 70)

    crisis_analysis = crisis_vs_calm_analysis(rolling_results)

    print(f"\n  Calm periods: mean={crisis_analysis['calm']['mean']:.1f}%, "
          f"std={crisis_analysis['calm']['std']:.1f}%, n={crisis_analysis['calm']['n']}")

    for period in ['GFC', 'COVID', 'Rate_Hikes_2022']:
        if period in crisis_analysis:
            ca = crisis_analysis[period]
            sig = "***" if (ca.get('p_value') and ca['p_value'] < 0.01) else \
                  "**" if (ca.get('p_value') and ca['p_value'] < 0.05) else \
                  "*" if (ca.get('p_value') and ca['p_value'] < 0.10) else ""
            print(f"  {period}: mean={ca['mean']:.1f}%, diff={ca['diff_vs_calm']:+.1f}%, "
                  f"t={ca.get('t_stat', 'N/A')}, p={ca.get('p_value', 'N/A')}{sig}")

    # ---- 8. Return vs Vol Spillover ----
    print("\n" + "=" * 70)
    print("8. RETURN VS VOL SPILLOVER COMPARISON")
    print("=" * 70)

    rv_comparison = return_vs_vol_spillover(returns)

    print(f"\n  Return spillover total: {rv_comparison['return_spillover']['total']:.1f}%")
    print(f"  Vol spillover (sq ret): {rv_comparison['vol_spillover_sq']['total']:.1f}%")
    print(f"  Vol spillover (abs ret): {rv_comparison['vol_spillover_abs']['total']:.1f}%")

    print(f"\n  SPY Net Spillover:")
    print(f"    Returns: {rv_comparison['return_spillover']['net']['SPY']:+.1f}%")
    print(f"    Vol (sq): {rv_comparison['vol_spillover_sq']['net']['SPY']:+.1f}%")
    print(f"    Vol (abs): {rv_comparison['vol_spillover_abs']['net']['SPY']:+.1f}%")

    # ---- 9. Stability: Vol vs Return Spillover ----
    print("\n" + "=" * 70)
    print("9. STABILITY: VOL VS RETURN SPILLOVER OVER TIME")
    print("=" * 70)

    stability = rolling_stability_test(rolling_results, returns, window=252, step=21,
                                        var_lag=var_lag, forecast_h=10)

    print(f"\n  Vol spillover CV: {stability['vol_spillover_cv']:.3f}")
    print(f"  Ret spillover CV: {stability['ret_spillover_cv']:.3f}")
    print(f"  Vol more stable: {stability['vol_more_stable']}")
    print(f"  Correlation (vol vs ret spillover): {stability['correlation_vol_ret_spillover']:.3f}")

    # ---- 10. Sub-period analysis ----
    print("\n" + "=" * 70)
    print("10. SUB-PERIOD ANALYSIS")
    print("=" * 70)

    sub_periods = [
        ('Pre-GFC', '2007-01-01', '2007-12-31'),
        ('GFC', '2008-01-01', '2009-12-31'),
        ('Recovery', '2010-01-01', '2014-12-31'),
        ('Pre-COVID', '2015-01-01', '2019-12-31'),
        ('COVID+Post', '2020-01-01', '2021-12-31'),
        ('Rate_Hikes', '2022-01-01', '2023-12-31'),
        ('Recent', '2024-01-01', '2026-03-26'),
    ]

    sub_results = {}
    for name, start, end in sub_periods:
        mask = (returns.index >= start) & (returns.index <= end)
        sub_data = (returns[mask]) ** 2
        if len(sub_data) > 60:  # need minimum observations for VAR
            try:
                sp = diebold_yilmaz_spillover(sub_data, var_lag=min(var_lag, 3), forecast_h=10)
                sub_results[name] = {
                    'total_spillover': sp['total_spillover'],
                    'spy_net': sp['net'].get('SPY', 0),
                    'n_obs': len(sub_data),
                    'from_others': sp['from_others'],
                    'net': sp['net']
                }
                print(f"  {name:15s}: Total={sp['total_spillover']:5.1f}%, SPY net={sp['net'].get('SPY',0):+5.1f}%, n={len(sub_data)}")
            except Exception as e:
                print(f"  {name:15s}: FAILED ({e})")
                sub_results[name] = {'error': str(e)}

    # ---- 11. Robustness: Different forecast horizons ----
    print("\n" + "=" * 70)
    print("11. ROBUSTNESS: FORECAST HORIZON SENSITIVITY")
    print("=" * 70)

    robustness_h = {}
    for h in [5, 10, 15, 20]:
        sp = diebold_yilmaz_spillover(sq_returns, var_lag=var_lag, forecast_h=h)
        robustness_h[h] = {
            'total_spillover': sp['total_spillover'],
            'spy_net': sp['net'].get('SPY', 0)
        }
        print(f"  H={h:2d}: Total={sp['total_spillover']:5.1f}%, SPY net={sp['net'].get('SPY',0):+5.1f}%")

    # ---- 12. Robustness: Different VAR lags ----
    print("\n" + "=" * 70)
    print("12. ROBUSTNESS: VAR LAG SENSITIVITY")
    print("=" * 70)

    robustness_lag = {}
    for lag in [1, 3, 5, 7, 10]:
        sp = diebold_yilmaz_spillover(sq_returns, var_lag=lag, forecast_h=10)
        robustness_lag[lag] = {
            'total_spillover': sp['total_spillover'],
            'spy_net': sp['net'].get('SPY', 0)
        }
        print(f"  Lag={lag:2d}: Total={sp['total_spillover']:5.1f}%, SPY net={sp['net'].get('SPY',0):+5.1f}%")

    # ---- Compile Results ----
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    # Determine which Asian market is most affected
    most_affected = max(pairwise.items(), key=lambda x: x[1]['us_to_asia'])
    least_affected = min(pairwise.items(), key=lambda x: x[1]['us_to_asia'])

    print(f"\n  1. Total vol spillover: {vol_sp['total_spillover']:.1f}%")
    print(f"  2. SPY is {'net transmitter' if vol_sp['net']['SPY'] > 0 else 'net receiver'} "
          f"(net={vol_sp['net']['SPY']:+.1f}%)")
    print(f"  3. Most affected by US: {most_affected[0]} ({most_affected[1]['us_to_asia']:.1f}%)")
    print(f"  4. Least affected by US: {least_affected[0]} ({least_affected[1]['us_to_asia']:.1f}%)")
    print(f"  5. Vol vs return spillover: vol={rv_comparison['vol_spillover_sq']['total']:.1f}%, "
          f"ret={rv_comparison['return_spillover']['total']:.1f}%")
    print(f"  6. Vol spillover stability (CV): {stability['vol_spillover_cv']:.3f} vs "
          f"ret: {stability['ret_spillover_cv']:.3f}")

    # Rolling spillover summary for JSON
    rolling_summary = {
        'mean': float(np.mean(totals)),
        'std': float(np.std(totals)),
        'min': float(np.min(totals)),
        'max': float(np.max(totals)),
        'peak_date': rolling_results[max_idx]['date'],
        'trough_date': rolling_results[min_idx]['date'],
        'spy_always_net_transmitter': all(s > 0 for s in spy_nets),
        'spy_net_mean': float(np.mean(spy_nets)),
        'n_windows': len(rolling_results),
        # Save a subset of rolling data points for reference
        'time_series': [
            {'date': r['date'], 'total': r['total_spillover'], 'spy_net': r['spy_net']}
            for r in rolling_results[::3]  # every 3rd window to keep size manageable
        ]
    }

    results = {
        'experiment_id': 'k455',
        'title': 'Volatility Spillover Network US → Asia (Diebold-Yilmaz)',
        'method': 'Diebold-Yilmaz (2009, 2012) Spillover Index based on generalized FEVD',
        'data_source': 'yfinance (US-listed ETFs)',
        'data_period': f"{returns.index[0].strftime('%Y-%m-%d')} to {returns.index[-1].strftime('%Y-%m-%d')}",
        'n_observations': int(len(returns)),
        'tickers': tickers,
        'var_lag_selected': var_lag,
        'lag_selection': lag_selection,
        'forecast_horizon': 10,
        'vol_proxy': 'squared returns',
        'diagnostics': {
            'descriptive_stats': desc_stats,
            'adf_returns': adf_results,
            'adf_squared_returns': adf_sq_results,
        },
        'full_sample_spillover': {
            'total_spillover': vol_sp['total_spillover'],
            'from_others': vol_sp['from_others'],
            'to_others': vol_sp['to_others'],
            'net': vol_sp['net'],
            'spillover_table': vol_sp['table'],
        },
        'pairwise_us_asia': pairwise,
        'rolling_spillover': rolling_summary,
        'crisis_vs_calm': crisis_analysis,
        'return_vs_vol_comparison': rv_comparison,
        'stability_comparison': stability,
        'sub_period_analysis': sub_results,
        'robustness_forecast_horizon': robustness_h,
        'robustness_var_lag': robustness_lag,
        'conclusions': {},  # will fill after seeing results
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'references': [
            'Diebold & Yilmaz (2009) "Measuring Financial Asset Return and Volatility Spillovers" Economic Journal',
            'Diebold & Yilmaz (2012) "Better to Give than to Receive" International Journal of Forecasting',
            'Pesaran & Shin (1998) "Generalized Impulse Response Analysis in Linear Multivariate Models"'
        ]
    }

    # Fill conclusions based on actual results
    results['conclusions'] = {
        'q1_us_vol_spillover_strength': f"Total vol spillover index = {vol_sp['total_spillover']:.1f}%. "
            f"SPY is {'net transmitter' if vol_sp['net']['SPY'] > 0 else 'net receiver'} "
            f"with net spillover = {vol_sp['net']['SPY']:+.1f}%.",
        'q2_time_variation': f"Rolling spillover ranges from {np.min(totals):.1f}% to {np.max(totals):.1f}% "
            f"(mean {np.mean(totals):.1f}%, CV={stability['vol_spillover_cv']:.3f}). "
            f"Peak on {rolling_results[max_idx]['date']}.",
        'q3_most_affected_asian_market': f"{most_affected[0]} receives {most_affected[1]['us_to_asia']:.1f}% "
            f"of its FEV from US shocks. Least affected: {least_affected[0]} ({least_affected[1]['us_to_asia']:.1f}%).",
        'q4_vol_vs_return_stability': f"Vol spillover CV={stability['vol_spillover_cv']:.3f} vs "
            f"return spillover CV={stability['ret_spillover_cv']:.3f}. "
            f"Vol spillover is {'more' if stability['vol_more_stable'] else 'less'} stable.",
        'limitations': [
            'US-listed ETFs may not perfectly reflect local market dynamics',
            'Squared returns is a noisy vol proxy (realized vol from high-freq data would be better)',
            'VAR assumes linear relationships',
            'Generalized FEVD can give different results from Cholesky-based FEVD',
            'ETF liquidity and tracking error may affect spillover estimates',
            'Sample includes multiple structural breaks (GFC, COVID, rate hikes)'
        ],
        'relation_to_prior_work': {
            'K7': 'K7 used Granger causality. This uses FEVD (Diebold-Yilmaz). Both should identify SPY as dominant.',
            'K84': 'K84 found vol spillover statistically significant but economically insignificant. DY index quantifies overall interconnectedness.',
            'T32_T33': 'T32/T33 found US→Asia return lead-lag. This tests vol dimension of that relationship.'
        }
    }

    # Save results
    output_path = 'experiments/k455_vol_spillover_results.json'
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")

    return results


if __name__ == '__main__':
    results = main()
