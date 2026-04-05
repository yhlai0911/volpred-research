"""
K892: Verify 0050.TW GJR-GARCH Gamma — Resolve Paper 2 Conflict

Background:
- N120 knowledge entry: 0050.TW gamma = 0.147 (t=2.20)
- Paper body_v2.tex: 0050.TW gamma = 0.087 (t=2.20)
- K636 full-sample OLS Engle-Ng: 0050.TW gamma = 0.411 (different method!)

K636 used OLS regression on r^2 (Engle-Ng specification), NOT MLE GJR-GARCH.
Paper and N120 should use arch package MLE, but values differ.
The identical t-stat (2.20) with different gamma is suspicious.

This experiment re-estimates GJR-GARCH(1,1) via MLE for all assets
under multiple window/sample configurations to find the correct values.

Data source: yfinance (0050.TW, ^TWII, 2330.TW, SPY)
Reference: Glosten, Jagannathan, Runkle (1993)
"""

import json
import warnings
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model

# MUST use clean_tw50_data for 0050.TW
sys.path.insert(0, '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-adc7e97d')
from volpred.utils import clean_tw50_data

warnings.filterwarnings('ignore')

def download_data(ticker, start='2000-01-01', end='2026-04-05'):
    """Download and prepare return data."""
    df = yf.download(ticker, start=start, end=end, progress=False)
    if df.empty:
        raise ValueError(f"No data for {ticker}")

    # Handle multi-level columns from yfinance
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    prices = df['Close'].dropna()
    returns = prices.pct_change().dropna()

    return prices, returns


def estimate_gjr_garch(returns, dist='normal'):
    """
    Estimate GJR-GARCH(1,1) via MLE using arch package.

    GJR-GARCH(1,1):
      h_t = omega + alpha * r_{t-1}^2 + gamma * I(r_{t-1}<0) * r_{t-1}^2 + beta * h_{t-1}

    Returns dict with parameters, standard errors, t-stats.
    """
    # arch package expects returns in percentage points for numerical stability
    # but we can also use raw returns with rescale=True
    ret_pct = returns * 100  # convert to percentage

    am = arch_model(ret_pct, vol='GARCH', p=1, o=1, q=1, dist=dist, mean='Constant')
    res = am.fit(disp='off', options={'maxiter': 5000})

    if not res.convergence_flag == 0:
        print(f"  Warning: convergence flag = {res.convergence_flag}")

    params = res.params
    std_err = res.std_err
    tvalues = res.tvalues

    # Extract GJR parameters
    # arch package names: omega, alpha[1], gamma[1], beta[1]
    omega = params.get('omega', params.iloc[1] if len(params) > 1 else np.nan)
    alpha = params.get('alpha[1]', np.nan)
    gamma = params.get('gamma[1]', np.nan)
    beta = params.get('beta[1]', np.nan)

    omega_se = std_err.get('omega', np.nan)
    alpha_se = std_err.get('alpha[1]', np.nan)
    gamma_se = std_err.get('gamma[1]', np.nan)
    beta_se = std_err.get('beta[1]', np.nan)

    omega_t = tvalues.get('omega', np.nan)
    alpha_t = tvalues.get('alpha[1]', np.nan)
    gamma_t = tvalues.get('gamma[1]', np.nan)
    beta_t = tvalues.get('beta[1]', np.nan)

    persistence = alpha + 0.5 * gamma + beta

    return {
        'omega': float(omega),
        'alpha': float(alpha),
        'gamma': float(gamma),
        'beta': float(beta),
        'omega_se': float(omega_se),
        'alpha_se': float(alpha_se),
        'gamma_se': float(gamma_se),
        'beta_se': float(beta_se),
        'omega_t': float(omega_t),
        'alpha_t': float(alpha_t),
        'gamma_t': float(gamma_t),
        'beta_t': float(beta_t),
        'persistence': float(persistence),
        'n_obs': len(returns),
        'convergence': int(res.convergence_flag),
        'log_likelihood': float(res.loglikelihood),
        'aic': float(res.aic),
        'bic': float(res.bic),
        'dist': dist,
        'note': 'Parameters estimated on returns*100 (percentage). omega is in pct^2 units.'
    }


def estimate_rolling(returns, window=2000):
    """
    Estimate GJR-GARCH with rolling window.
    Returns the LAST window estimate (most recent) and statistics across windows.
    """
    n = len(returns)
    if n < window + 100:
        return None, None

    gammas = []
    gamma_ts = []
    all_params = []

    # Estimate at several points: every 250 days
    step = 250
    for end_idx in range(window, n, step):
        start_idx = end_idx - window
        ret_window = returns.iloc[start_idx:end_idx]

        try:
            result = estimate_gjr_garch(ret_window)
            gammas.append(result['gamma'])
            gamma_ts.append(result['gamma_t'])
            all_params.append(result)
        except Exception as e:
            continue

    if not gammas:
        return None, None

    # Also get the last window estimate (most recent 2000 obs)
    last_ret = returns.iloc[-window:]
    try:
        last_result = estimate_gjr_garch(last_ret)
    except Exception:
        last_result = all_params[-1] if all_params else None

    rolling_stats = {
        'n_windows': len(gammas),
        'gamma_mean': float(np.mean(gammas)),
        'gamma_median': float(np.median(gammas)),
        'gamma_std': float(np.std(gammas)),
        'gamma_min': float(np.min(gammas)),
        'gamma_max': float(np.max(gammas)),
        'gamma_positive_pct': float(np.mean(np.array(gammas) > 0) * 100),
        'gamma_significant_pct': float(np.mean(np.array(gamma_ts) > 1.96) * 100),
        'gamma_t_mean': float(np.mean(gamma_ts)),
        'gamma_t_median': float(np.median(gamma_ts)),
    }

    return last_result, rolling_stats


def main():
    print("=" * 70)
    print("K892: Verify 0050.TW GJR-GARCH Gamma")
    print("=" * 70)

    results = {
        'experiment_id': 'K892',
        'title': 'Verify 0050.TW GJR-GARCH Gamma — Resolve Paper 2 Conflict',
        'date': datetime.now(timezone.utc).isoformat(),
        'data_source': 'yfinance (0050.TW, ^TWII, 2330.TW, SPY)',
        'method': 'GJR-GARCH(1,1) MLE via arch package, Normal innovations',
        'purpose': 'Resolve conflict: N120 gamma=0.147 vs Paper gamma=0.087 vs K636 gamma=0.411',
        'references': [
            'Glosten, Jagannathan, Runkle (1993) - GJR-GARCH',
            'N120 knowledge entry: 0050.TW gamma=0.147 (t=2.20)',
            'Paper body_v2.tex Table 2: 0050.TW gamma=0.087 (t=2.20)',
            'K636: OLS Engle-Ng gamma=0.411 (DIFFERENT METHOD - not MLE)',
        ],
        'assets': {},
        'conflict_resolution': {}
    }

    # ============================================================
    # 1. Download data
    # ============================================================
    assets = {
        '0050.TW': {'start': '2003-01-01', 'needs_clean': True},
        '^TWII': {'start': '1997-01-01', 'needs_clean': False},
        '2330.TW': {'start': '2000-01-01', 'needs_clean': False},
        'SPY': {'start': '2000-01-01', 'needs_clean': False},
    }

    data = {}
    for ticker, config in assets.items():
        print(f"\nDownloading {ticker}...")
        prices, returns = download_data(ticker, start=config['start'])

        if config['needs_clean']:
            print(f"  Applying clean_tw50_data for {ticker}...")
            prices, returns = clean_tw50_data(prices, returns)

        # Drop any NaN/inf
        returns = returns.replace([np.inf, -np.inf], np.nan).dropna()

        data[ticker] = {
            'prices': prices,
            'returns': returns,
        }

        print(f"  Period: {returns.index[0].strftime('%Y-%m-%d')} to {returns.index[-1].strftime('%Y-%m-%d')}")
        print(f"  N obs: {len(returns)}")
        print(f"  Ann vol: {returns.std() * np.sqrt(252):.4f}")

    # ============================================================
    # 2. Full sample estimation for each asset
    # ============================================================
    print("\n" + "=" * 70)
    print("FULL SAMPLE GJR-GARCH(1,1) MLE ESTIMATION")
    print("=" * 70)

    for ticker in assets:
        returns = data[ticker]['returns']
        print(f"\n--- {ticker} (N={len(returns)}, {returns.index[0].strftime('%Y-%m-%d')} to {returns.index[-1].strftime('%Y-%m-%d')}) ---")

        try:
            result = estimate_gjr_garch(returns)
            print(f"  omega  = {result['omega']:.6f} (t={result['omega_t']:.3f})")
            print(f"  alpha  = {result['alpha']:.6f} (t={result['alpha_t']:.3f})")
            print(f"  gamma  = {result['gamma']:.6f} (t={result['gamma_t']:.3f})")
            print(f"  beta   = {result['beta']:.6f} (t={result['beta_t']:.3f})")
            print(f"  persistence = {result['persistence']:.6f}")
            print(f"  convergence = {result['convergence']}")

            results['assets'][ticker] = {'full_sample': result}
        except Exception as e:
            print(f"  ERROR: {e}")
            results['assets'][ticker] = {'full_sample': {'error': str(e)}}

    # ============================================================
    # 3. Rolling window w=2000 estimation
    # ============================================================
    print("\n" + "=" * 70)
    print("ROLLING WINDOW (w=2000) GJR-GARCH(1,1) ESTIMATION")
    print("=" * 70)

    for ticker in assets:
        returns = data[ticker]['returns']
        print(f"\n--- {ticker} ---")

        try:
            last_result, rolling_stats = estimate_rolling(returns, window=2000)

            if last_result is None:
                print(f"  Insufficient data for w=2000 rolling")
                results['assets'][ticker]['rolling_w2000'] = {'error': 'insufficient data'}
                continue

            print(f"  Last window estimate (most recent 2000 obs):")
            print(f"    gamma  = {last_result['gamma']:.6f} (t={last_result['gamma_t']:.3f})")
            print(f"    alpha  = {last_result['alpha']:.6f}")
            print(f"    beta   = {last_result['beta']:.6f}")
            print(f"    persistence = {last_result['persistence']:.6f}")
            print(f"  Rolling statistics ({rolling_stats['n_windows']} windows):")
            print(f"    gamma mean   = {rolling_stats['gamma_mean']:.6f}")
            print(f"    gamma median = {rolling_stats['gamma_median']:.6f}")
            print(f"    gamma std    = {rolling_stats['gamma_std']:.6f}")
            print(f"    gamma range  = [{rolling_stats['gamma_min']:.6f}, {rolling_stats['gamma_max']:.6f}]")
            print(f"    gamma > 0    = {rolling_stats['gamma_positive_pct']:.1f}%")
            print(f"    gamma signif = {rolling_stats['gamma_significant_pct']:.1f}%")

            results['assets'][ticker]['rolling_w2000'] = {
                'last_window': last_result,
                'rolling_stats': rolling_stats,
            }
        except Exception as e:
            print(f"  ERROR: {e}")
            results['assets'][ticker]['rolling_w2000'] = {'error': str(e)}

    # ============================================================
    # 4. Expanding window estimation (check stability)
    # ============================================================
    print("\n" + "=" * 70)
    print("EXPANDING WINDOW GJR-GARCH(1,1) ESTIMATION")
    print("=" * 70)

    for ticker in ['0050.TW', 'SPY']:
        returns = data[ticker]['returns']
        print(f"\n--- {ticker} ---")

        # Estimate with different end dates to check stability
        expanding_results = []
        years_to_test = [2010, 2014, 2018, 2020, 2022, 2024, 2026]

        for end_year in years_to_test:
            end_date = f'{end_year}-01-01'
            ret_subset = returns[returns.index < end_date]

            if len(ret_subset) < 500:
                continue

            try:
                result = estimate_gjr_garch(ret_subset)
                period_str = f"{ret_subset.index[0].strftime('%Y')}-{ret_subset.index[-1].strftime('%Y')}"
                print(f"  {period_str} (N={len(ret_subset)}): gamma={result['gamma']:.6f} (t={result['gamma_t']:.3f})")
                expanding_results.append({
                    'period': period_str,
                    'n_obs': len(ret_subset),
                    'gamma': result['gamma'],
                    'gamma_t': result['gamma_t'],
                    'alpha': result['alpha'],
                    'beta': result['beta'],
                    'persistence': result['persistence'],
                })
            except Exception as e:
                print(f"  {end_year}: ERROR {e}")

        results['assets'][ticker]['expanding'] = expanding_results

    # ============================================================
    # 5. Paper-specific estimation: 0050.TW 2008-2026, w=2000
    # ============================================================
    print("\n" + "=" * 70)
    print("PAPER-SPECIFIC: 0050.TW 2008-2026 (Paper Table 2 specification)")
    print("=" * 70)

    # The paper says "0050.TW (2008-2026)" — let's match that exactly
    tw50_returns = data['0050.TW']['returns']
    tw50_2008 = tw50_returns[tw50_returns.index >= '2008-01-01']
    print(f"  0050.TW 2008-2026: N={len(tw50_2008)}")
    print(f"  Period: {tw50_2008.index[0].strftime('%Y-%m-%d')} to {tw50_2008.index[-1].strftime('%Y-%m-%d')}")

    # Full sample for this period
    try:
        result_2008 = estimate_gjr_garch(tw50_2008)
        print(f"\n  Full sample (2008-2026):")
        print(f"    omega  = {result_2008['omega']:.6f} (se={result_2008['omega_se']:.6f}, t={result_2008['omega_t']:.3f})")
        print(f"    alpha  = {result_2008['alpha']:.6f} (se={result_2008['alpha_se']:.6f}, t={result_2008['alpha_t']:.3f})")
        print(f"    gamma  = {result_2008['gamma']:.6f} (se={result_2008['gamma_se']:.6f}, t={result_2008['gamma_t']:.3f})")
        print(f"    beta   = {result_2008['beta']:.6f} (se={result_2008['beta_se']:.6f}, t={result_2008['beta_t']:.3f})")
        print(f"    persistence = {result_2008['persistence']:.6f}")

        results['paper_specific'] = {
            'tw50_2008_2026_full': result_2008,
        }
    except Exception as e:
        print(f"  ERROR: {e}")
        results['paper_specific'] = {'error': str(e)}

    # Also try Student-t distribution
    print(f"\n  With Student-t innovations:")
    try:
        result_t = estimate_gjr_garch(tw50_2008, dist='t')
        print(f"    omega  = {result_t['omega']:.6f} (t={result_t['omega_t']:.3f})")
        print(f"    alpha  = {result_t['alpha']:.6f} (t={result_t['alpha_t']:.3f})")
        print(f"    gamma  = {result_t['gamma']:.6f} (t={result_t['gamma_t']:.3f})")
        print(f"    beta   = {result_t['beta']:.6f} (t={result_t['beta_t']:.3f})")
        print(f"    persistence = {result_t['persistence']:.6f}")
        results['paper_specific']['tw50_2008_2026_t'] = result_t
    except Exception as e:
        print(f"    ERROR: {e}")

    # With last 2000 obs window
    if len(tw50_2008) >= 2000:
        tw50_last2000 = tw50_2008.iloc[-2000:]
        print(f"\n  Last 2000 obs of 2008-2026 period:")
        print(f"    Period: {tw50_last2000.index[0].strftime('%Y-%m-%d')} to {tw50_last2000.index[-1].strftime('%Y-%m-%d')}")
        try:
            result_w2000 = estimate_gjr_garch(tw50_last2000)
            print(f"    omega  = {result_w2000['omega']:.6f} (t={result_w2000['omega_t']:.3f})")
            print(f"    alpha  = {result_w2000['alpha']:.6f} (t={result_w2000['alpha_t']:.3f})")
            print(f"    gamma  = {result_w2000['gamma']:.6f} (t={result_w2000['gamma_t']:.3f})")
            print(f"    beta   = {result_w2000['beta']:.6f} (t={result_w2000['beta_t']:.3f})")
            print(f"    persistence = {result_w2000['persistence']:.6f}")
            results['paper_specific']['tw50_last2000_of_2008'] = result_w2000
        except Exception as e:
            print(f"    ERROR: {e}")

    # ============================================================
    # 6. Check N120 specification: w=2000, 2018-2026
    # ============================================================
    print("\n" + "=" * 70)
    print("N120 SPECIFICATION CHECK: 0050.TW w=2000, 2018-2026")
    print("=" * 70)

    tw50_2018 = tw50_returns[tw50_returns.index >= '2018-01-01']
    print(f"  0050.TW 2018-2026: N={len(tw50_2018)}")

    if len(tw50_2018) >= 500:
        try:
            result_n120 = estimate_gjr_garch(tw50_2018)
            print(f"  gamma  = {result_n120['gamma']:.6f} (t={result_n120['gamma_t']:.3f})")
            print(f"  alpha  = {result_n120['alpha']:.6f}")
            print(f"  beta   = {result_n120['beta']:.6f}")
            print(f"  persistence = {result_n120['persistence']:.6f}")
            results['n120_check'] = {
                'tw50_2018_2026': result_n120,
            }
        except Exception as e:
            print(f"  ERROR: {e}")

    # Also try the first 2000 obs from 2008 (roughly 2008-2016)
    tw50_first2000 = tw50_2008.iloc[:2000]
    print(f"\n  First 2000 obs from 2008 ({tw50_first2000.index[0].strftime('%Y-%m-%d')} to {tw50_first2000.index[-1].strftime('%Y-%m-%d')}):")
    try:
        result_first = estimate_gjr_garch(tw50_first2000)
        print(f"  gamma  = {result_first['gamma']:.6f} (t={result_first['gamma_t']:.3f})")
        results['n120_check']['tw50_first2000_from_2008'] = result_first
    except Exception as e:
        print(f"  ERROR: {e}")

    # ============================================================
    # 7. SPY control (known gamma ≈ 0.211)
    # ============================================================
    print("\n" + "=" * 70)
    print("SPY CONTROL (expected gamma ≈ 0.211)")
    print("=" * 70)

    spy_returns = data['SPY']['returns']

    # Full sample
    print(f"  Full sample: N={len(spy_returns)}")
    spy_full = results['assets']['SPY']['full_sample']
    print(f"    gamma = {spy_full['gamma']:.6f} (t={spy_full['gamma_t']:.3f})")

    # 2008-2026 (same period as paper)
    spy_2008 = spy_returns[spy_returns.index >= '2008-01-01']
    try:
        result_spy_2008 = estimate_gjr_garch(spy_2008)
        print(f"\n  2008-2026 (N={len(spy_2008)}):")
        print(f"    gamma = {result_spy_2008['gamma']:.6f} (t={result_spy_2008['gamma_t']:.3f})")
        results['spy_control'] = {
            'spy_2008_2026': result_spy_2008,
        }
    except Exception as e:
        print(f"  ERROR: {e}")

    # ============================================================
    # 8. TWII and TSMC
    # ============================================================
    print("\n" + "=" * 70)
    print("TWII AND TSMC ESTIMATES")
    print("=" * 70)

    for ticker in ['^TWII', '2330.TW']:
        returns = data[ticker]['returns']
        # 2008-2026 subset
        ret_2008 = returns[returns.index >= '2008-01-01']
        print(f"\n  {ticker} 2008-2026 (N={len(ret_2008)}):")
        try:
            result = estimate_gjr_garch(ret_2008)
            print(f"    gamma = {result['gamma']:.6f} (t={result['gamma_t']:.3f})")
            print(f"    alpha = {result['alpha']:.6f}")
            print(f"    beta  = {result['beta']:.6f}")
            print(f"    persistence = {result['persistence']:.6f}")
            results['assets'][ticker]['period_2008_2026'] = result
        except Exception as e:
            print(f"    ERROR: {e}")

        # Full sample
        print(f"  {ticker} full sample (N={len(returns)}):")
        full = results['assets'][ticker]['full_sample']
        print(f"    gamma = {full['gamma']:.6f} (t={full['gamma_t']:.3f})")

    # ============================================================
    # 9. CONFLICT RESOLUTION ANALYSIS
    # ============================================================
    print("\n" + "=" * 70)
    print("CONFLICT RESOLUTION")
    print("=" * 70)

    # Gather all 0050.TW gamma estimates
    tw50_gammas = {}

    # Full sample (all available data)
    fs = results['assets']['0050.TW']['full_sample']
    tw50_gammas['full_sample_all'] = {'gamma': fs['gamma'], 't': fs['gamma_t'], 'n': fs['n_obs']}

    # 2008-2026 full
    ps = results['paper_specific']['tw50_2008_2026_full']
    tw50_gammas['2008_2026_full'] = {'gamma': ps['gamma'], 't': ps['gamma_t'], 'n': ps['n_obs']}

    # 2018-2026
    if 'tw50_2018_2026' in results.get('n120_check', {}):
        n1 = results['n120_check']['tw50_2018_2026']
        tw50_gammas['2018_2026'] = {'gamma': n1['gamma'], 't': n1['gamma_t'], 'n': n1['n_obs']}

    # Last 2000 of 2008
    if 'tw50_last2000_of_2008' in results.get('paper_specific', {}):
        lw = results['paper_specific']['tw50_last2000_of_2008']
        tw50_gammas['last_2000_of_2008'] = {'gamma': lw['gamma'], 't': lw['gamma_t'], 'n': lw['n_obs']}

    # Rolling w=2000 last window
    if 'rolling_w2000' in results['assets']['0050.TW']:
        rw = results['assets']['0050.TW']['rolling_w2000']
        if 'last_window' in rw and rw['last_window']:
            lw2 = rw['last_window']
            tw50_gammas['rolling_w2000_last'] = {'gamma': lw2['gamma'], 't': lw2['gamma_t'], 'n': lw2['n_obs']}

    print("\n  All 0050.TW gamma estimates:")
    print(f"  {'Configuration':<30} {'gamma':>10} {'t-stat':>10} {'N':>8}")
    print(f"  {'-'*30} {'-'*10} {'-'*10} {'-'*8}")
    for key, val in tw50_gammas.items():
        print(f"  {key:<30} {val['gamma']:>10.6f} {val['t']:>10.3f} {val['n']:>8}")

    print(f"\n  Paper claims: gamma=0.087 (t=2.20)")
    print(f"  N120 claims:  gamma=0.147 (t=2.20)")
    print(f"  K636 claims:  gamma=0.411 (t=14.85) — OLS Engle-Ng, NOT MLE")

    # Determine which is correct
    closest_to_paper = min(tw50_gammas.items(), key=lambda x: abs(x[1]['gamma'] - 0.087))
    closest_to_n120 = min(tw50_gammas.items(), key=lambda x: abs(x[1]['gamma'] - 0.147))

    print(f"\n  Closest to paper (0.087): {closest_to_paper[0]} = {closest_to_paper[1]['gamma']:.6f}")
    print(f"  Closest to N120 (0.147):  {closest_to_n120[0]} = {closest_to_n120[1]['gamma']:.6f}")

    # Check if any estimate has t-stat ≈ 2.20
    t_matches = {k: v for k, v in tw50_gammas.items() if abs(v['t'] - 2.20) < 0.5}
    if t_matches:
        print(f"\n  Estimates with t-stat ≈ 2.20 (±0.5):")
        for k, v in t_matches.items():
            print(f"    {k}: gamma={v['gamma']:.6f}, t={v['t']:.3f}")

    results['conflict_resolution'] = {
        'all_tw50_gammas': tw50_gammas,
        'paper_value': {'gamma': 0.087, 't': 2.20},
        'n120_value': {'gamma': 0.147, 't': 2.20},
        'k636_value': {'gamma': 0.411, 't': 14.85, 'note': 'OLS Engle-Ng, not MLE'},
        'closest_to_paper': {'config': closest_to_paper[0], **closest_to_paper[1]},
        'closest_to_n120': {'config': closest_to_n120[0], **closest_to_n120[1]},
        't_stat_matches': {k: v for k, v in tw50_gammas.items() if abs(v['t'] - 2.20) < 0.5},
    }

    # ============================================================
    # 10. Summary comparison table
    # ============================================================
    print("\n" + "=" * 70)
    print("SUMMARY: GJR-GARCH(1,1) PARAMETERS (Full Sample, Normal dist)")
    print("=" * 70)

    print(f"\n  {'Asset':<15} {'omega':>10} {'alpha':>10} {'gamma':>10} {'beta':>10} {'persist':>10} {'gamma_t':>10} {'N':>8}")
    print(f"  {'-'*15} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*8}")

    for ticker in assets:
        fs = results['assets'][ticker]['full_sample']
        if 'error' not in fs:
            print(f"  {ticker:<15} {fs['omega']:>10.6f} {fs['alpha']:>10.6f} {fs['gamma']:>10.6f} {fs['beta']:>10.6f} {fs['persistence']:>10.6f} {fs['gamma_t']:>10.3f} {fs['n_obs']:>8}")

    # Save results
    output_path = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-adc7e97d/experiments/k892_verify_tw_gamma_results.json'

    # Convert any remaining numpy types
    def convert_numpy(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, dict):
            return {k: convert_numpy(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_numpy(i) for i in obj]
        return obj

    results_clean = convert_numpy(results)

    with open(output_path, 'w') as f:
        json.dump(results_clean, f, indent=2, default=str)

    print(f"\n\nResults saved to: {output_path}")
    print("\nDone.")


if __name__ == '__main__':
    main()
