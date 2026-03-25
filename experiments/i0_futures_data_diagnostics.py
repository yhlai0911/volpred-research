"""
I0: Futures-Spot Data Diagnostics & GARCH Convergence Check
This should be the FIRST experiment in any hedging study.

Step 1: Basic statistics (distribution, stationarity, autocorrelation, ARCH effects)
Step 2: Spot-futures relationship (cointegration, correlation stability)
Step 3: GARCH estimation convergence (parameter validity, log-likelihood, residual diagnostics)

ONLY proceed to hedging analysis if diagnostics pass.

Data: yfinance, all 15 available pairs
Output: experiments/i0_diagnostics_results.json
"""
import yfinance as yf
import numpy as np
import pandas as pd
from scipy import stats
from arch import arch_model
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
from statsmodels.tsa.stattools import adfuller
from multiprocessing import Pool
import json, warnings
from datetime import datetime, timezone

warnings.filterwarnings('ignore')

def diagnose_pair(args):
    """Full diagnostic for one spot-futures pair."""
    spot_t, fut_t, name = args
    result = {'pair': name, 'spot': spot_t, 'futures': fut_t}

    try:
        spot = yf.download(spot_t, start='2010-01-01', progress=False)
        fut = yf.download(fut_t, start='2010-01-01', progress=False)
    except:
        result['error'] = 'download failed'
        return name, result

    spot_c = spot['Close'].dropna().squeeze()
    fut_c = fut['Close'].dropna().squeeze()

    common = spot_c.index.intersection(fut_c.index)
    if len(common) < 500:
        result['error'] = f'insufficient data ({len(common)})'
        return name, result

    spot_c, fut_c = spot_c.loc[common], fut_c.loc[common]
    s_ret = spot_c.pct_change().dropna()
    f_ret = fut_c.pct_change().dropna().reindex(s_ret.index).fillna(0)
    n = len(s_ret)

    # ========== STEP 1: Basic Statistics ==========
    def basic_stats(ret, label):
        return {
            'n': len(ret),
            'mean_ann': round(float(ret.mean() * 252 * 100), 2),
            'vol_ann': round(float(ret.std() * np.sqrt(252) * 100), 2),
            'skewness': round(float(ret.skew()), 3),
            'kurtosis': round(float(ret.kurtosis()), 3),
            'jb_stat': round(float(stats.jarque_bera(ret.values)[0]), 1),
            'jb_pval': round(float(stats.jarque_bera(ret.values)[1]), 6),
            'adf_stat': round(float(adfuller(ret.values, maxlag=20)[0]), 3),
            'adf_pval': round(float(adfuller(ret.values, maxlag=20)[1]), 6),
            'lb_q10': round(float(acorr_ljungbox(ret.values, lags=10, return_df=True)['lb_pvalue'].iloc[-1]), 4),
        }

    result['spot_stats'] = basic_stats(s_ret, 'spot')
    result['futures_stats'] = basic_stats(f_ret, 'futures')

    # ARCH LM test (is there heteroscedasticity to model?)
    try:
        arch_lm = het_arch(s_ret.values, nlags=5)
        result['spot_arch_lm'] = {
            'stat': round(float(arch_lm[0]), 2),
            'pval': round(float(arch_lm[1]), 6),
            'has_arch': float(arch_lm[1]) < 0.05,
        }
    except:
        result['spot_arch_lm'] = {'error': 'failed'}

    # ========== STEP 2: Spot-Futures Relationship ==========
    corr_full = float(np.corrcoef(s_ret.values, f_ret.values)[0, 1])

    # Rolling 60d correlation stability
    roll_corr = s_ret.rolling(60).corr(f_ret).dropna()
    corr_stability = {
        'full_sample': round(corr_full, 4),
        'mean_rolling': round(float(roll_corr.mean()), 4),
        'min_rolling': round(float(roll_corr.min()), 4),
        'max_rolling': round(float(roll_corr.max()), 4),
        'std_rolling': round(float(roll_corr.std()), 4),
        'pct_below_080': round(float((roll_corr < 0.80).mean() * 100), 1),
        'pct_below_090': round(float((roll_corr < 0.90).mean() * 100), 1),
    }
    result['correlation'] = corr_stability

    # Cointegration (Engle-Granger)
    try:
        adf_resid = adfuller(spot_c.values - (spot_c.values.mean()/fut_c.values.mean()) * fut_c.values, maxlag=20)
        result['cointegration'] = {
            'eg_adf_stat': round(float(adf_resid[0]), 3),
            'eg_adf_pval': round(float(adf_resid[1]), 4),
            'cointegrated': float(adf_resid[1]) < 0.05,
        }
    except:
        result['cointegration'] = {'error': 'failed'}

    # ========== STEP 3: GARCH Convergence ==========
    garch_results = {}
    for label, ret in [('spot', s_ret), ('futures', f_ret)]:
        try:
            ret_scaled = ret * 100
            model = arch_model(ret_scaled, vol='GARCH', p=1, o=1, q=1, mean='Zero', dist='normal')
            res = model.fit(disp='off', show_warning=False)

            # Extract parameters
            omega = float(res.params.get('omega', 0))
            alpha = float(res.params.get('alpha[1]', 0))
            gamma = float(res.params.get('gamma[1]', 0))
            beta = float(res.params.get('beta[1]', 0))
            persistence = alpha + gamma/2 + beta

            # Convergence checks
            converged = res.convergence_flag == 0
            params_valid = (omega > 0) and (alpha >= 0) and (beta >= 0) and (persistence < 1)

            # Residual diagnostics
            std_resid = res.std_resid
            lb_resid = acorr_ljungbox(std_resid**2, lags=10, return_df=True)['lb_pvalue'].iloc[-1]

            garch_results[label] = {
                'converged': converged,
                'convergence_flag': int(res.convergence_flag),
                'omega': round(omega, 6),
                'alpha': round(alpha, 4),
                'gamma': round(gamma, 4),
                'beta': round(beta, 4),
                'persistence': round(persistence, 4),
                'params_valid': params_valid,
                'loglik': round(float(res.loglikelihood), 1),
                'aic': round(float(res.aic), 1),
                'bic': round(float(res.bic), 1),
                'resid_lb_sq_p10': round(float(lb_resid), 4),
                'resid_arch_free': float(lb_resid) > 0.05,
            }
        except Exception as e:
            garch_results[label] = {'error': str(e)[:100]}

    result['garch'] = garch_results

    # ========== OVERALL QUALITY GRADE ==========
    issues = []
    if corr_full < 0.80:
        issues.append(f'LOW correlation ({corr_full:.3f})')
    if corr_stability['pct_below_080'] > 10:
        issues.append(f'UNSTABLE correlation ({corr_stability["pct_below_080"]:.0f}% below 0.80)')
    if not result.get('spot_arch_lm', {}).get('has_arch', True):
        issues.append('No ARCH effects in spot (GARCH unnecessary)')
    for label in ['spot', 'futures']:
        g = garch_results.get(label, {})
        if g.get('error'):
            issues.append(f'{label} GARCH estimation FAILED')
        elif not g.get('converged', False):
            issues.append(f'{label} GARCH did NOT converge')
        elif not g.get('params_valid', False):
            issues.append(f'{label} GARCH params INVALID (persistence≥1)')
        elif not g.get('resid_arch_free', False):
            issues.append(f'{label} GARCH residuals still have ARCH effects')

    grade = 'A' if not issues else 'B' if len(issues) <= 1 else 'C' if len(issues) <= 2 else 'F'
    result['quality_grade'] = grade
    result['issues'] = issues

    return name, result


if __name__ == '__main__':
    pairs = [
        ('SPY', 'ES=F', 'SPY-ES'), ('QQQ', 'NQ=F', 'QQQ-NQ'), ('DIA', 'YM=F', 'DIA-YM'),
        ('GLD', 'GC=F', 'GLD-GC'), ('SLV', 'SI=F', 'SLV-SI'),
        ('USO', 'CL=F', 'USO-CL'), ('UNG', 'NG=F', 'UNG-NG'),
        ('TLT', 'ZN=F', 'TLT-ZN'), ('TLT', 'ZB=F', 'TLT-ZB'),
        ('SHY', 'ZT=F', 'SHY-ZT'), ('IEF', 'ZF=F', 'IEF-ZF'),
        ('FXE', '6E=F', 'FXE-EUR'), ('FXY', '6J=F', 'FXY-JPY'),
        ('FXB', '6B=F', 'FXB-GBP'), ('FXA', '6A=F', 'FXA-AUD'),
    ]

    print(f"I0: Futures-Spot Data Diagnostics ({len(pairs)} pairs)")
    print("=" * 90)

    with Pool(8) as pool:
        results_list = pool.map(diagnose_pair, pairs)

    # Print summary
    print(f"\n{'Pair':<12} {'Corr':>6} {'Corr Min':>9} {'ARCH?':>6} {'S Conv':>7} {'F Conv':>7} {'S Pers':>7} {'F Pers':>7} {'Grade':>6}")
    print("=" * 78)

    all_results = {}
    for name, res in results_list:
        all_results[name] = res
        if 'error' in res:
            print(f"{name:<12} ERROR: {res['error']}")
            continue

        corr = res['correlation']['full_sample']
        corr_min = res['correlation']['min_rolling']
        arch = "Y" if res.get('spot_arch_lm', {}).get('has_arch', False) else "N"
        s_conv = "Y" if res.get('garch', {}).get('spot', {}).get('converged', False) else "N"
        f_conv = "Y" if res.get('garch', {}).get('futures', {}).get('converged', False) else "N"
        s_pers = res.get('garch', {}).get('spot', {}).get('persistence', 0)
        f_pers = res.get('garch', {}).get('futures', {}).get('persistence', 0)
        grade = res.get('quality_grade', '?')

        issues_str = '; '.join(res.get('issues', []))
        print(f"{name:<12} {corr:>6.3f} {corr_min:>9.3f} {arch:>6} {s_conv:>7} {f_conv:>7} {s_pers:>7.3f} {f_pers:>7.3f} {grade:>6}")
        if issues_str:
            print(f"             Issues: {issues_str}")

    # Count grades
    grades = [r.get('quality_grade', '?') for _, r in results_list if 'error' not in r]
    print(f"\nGrade summary: A={grades.count('A')}, B={grades.count('B')}, C={grades.count('C')}, F={grades.count('F')}")

    # Save
    output = {
        'experiment': 'I0',
        'title': 'Futures-Spot Data Diagnostics & GARCH Convergence',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'data': {'source': 'yfinance', 'period': '2010-2025'},
        'pairs': all_results,
    }

    with open('experiments/i0_diagnostics_results.json', 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    print(f"\nResults saved to experiments/i0_diagnostics_results.json")
