"""
I11: Full Panel Daily GARCH Re-estimation Hedging (18 pairs)
Uses multiprocessing (M1 Max 10 cores) for proper daily re-estimation.

Academic standard: At each OOS day t, re-estimate GARCH on [t-500, t-1],
forecast σ_s(t), σ_f(t), compute h_t = ρ × σ_s/σ_f. Apply h_t at time t.

Evaluation: Ederington HE, VaR 1% reduction, DM test vs Naive.
15+ pairs across equity/commodity/bond/FX.

Data: yfinance, IS warm-up 500d, OOS 2020-2025
Output: experiments/i11_full_panel_results.json
"""
import yfinance as yf
import numpy as np
import pandas as pd
from scipy import stats
from arch import arch_model
from multiprocessing import Pool, cpu_count
import json, warnings, time
from datetime import datetime, timezone

warnings.filterwarnings('ignore')

def evaluate_pair(args):
    """Evaluate one spot-futures pair. Designed for multiprocessing."""
    spot_t, fut_t, name = args
    try:
        spot = yf.download(spot_t, start='2008-01-01', progress=False)['Close'].dropna().squeeze()
        fut = yf.download(fut_t, start='2008-01-01', progress=False)['Close'].dropna().squeeze()
    except:
        return name, None

    common = spot.index.intersection(fut.index)
    if len(common) < 1000:
        return name, {'error': f'Insufficient data ({len(common)})'}

    spot, fut = spot.loc[common], fut.loc[common]
    s_ret = spot.pct_change().dropna()
    f_ret = fut.pct_change().dropna().reindex(s_ret.index).fillna(0)

    oos_start = '2020-01-01'
    oos_mask = s_ret.index >= oos_start
    n_oos = int(oos_mask.sum())

    if n_oos < 100:
        return name, {'error': f'Insufficient OOS ({n_oos})'}

    s_oos = s_ret[oos_mask]
    f_oos = f_ret[oos_mask]
    corr = float(np.corrcoef(s_oos.values, f_oos.values)[0, 1])
    unhedged_var = float(s_oos.var())

    all_s = s_ret.values
    all_f = f_ret.values
    all_idx = s_ret.index
    oos_start_loc = int(np.where(all_idx >= oos_start)[0][0])

    # === Method 1: Naive ===
    hedged_naive = s_oos - 1.0 * f_oos
    he_naive = float(1 - hedged_naive.var() / unhedged_var)

    # === Method 2: Expanding OLS ===
    h_exp = []
    for t in range(oos_start_loc, len(all_s)):
        cov = np.cov(all_s[:t], all_f[:t])[0, 1]
        var = np.var(all_f[:t], ddof=1)
        h_exp.append(cov / var if var > 0 else 1.0)
    h_exp = pd.Series(h_exp, index=s_oos.index)
    hedged_exp = s_oos - h_exp * f_oos
    he_exp = float(1 - hedged_exp.var() / unhedged_var)

    # === Method 3: EWMA(0.94) ===
    lam = 0.94
    ewma_cov = float(np.cov(all_s[oos_start_loc-252:oos_start_loc], all_f[oos_start_loc-252:oos_start_loc])[0, 1])
    ewma_var = float(np.var(all_f[oos_start_loc-252:oos_start_loc], ddof=1))
    h_ewma = []
    for t in range(oos_start_loc, len(all_s)):
        h_ewma.append(ewma_cov / ewma_var if ewma_var > 0 else 1.0)
        ewma_cov = lam * ewma_cov + (1 - lam) * all_s[t] * all_f[t]
        ewma_var = lam * ewma_var + (1 - lam) * all_f[t]**2
    h_ewma = pd.Series(h_ewma, index=s_oos.index)
    hedged_ewma = s_oos - h_ewma * f_oos
    he_ewma = float(1 - hedged_ewma.var() / unhedged_var)

    # === Method 4: GJR-GARCH (daily re-estimation) ===
    garch_window = 500
    h_garch = []
    for t in range(oos_start_loc, len(all_s)):
        if t >= garch_window:
            try:
                s_g = pd.Series(all_s[t-garch_window:t]) * 100
                f_g = pd.Series(all_f[t-garch_window:t]) * 100
                m_s = arch_model(s_g, vol='GARCH', p=1, o=1, q=1, mean='Zero', dist='normal')
                m_f = arch_model(f_g, vol='GARCH', p=1, o=1, q=1, mean='Zero', dist='normal')
                r_s = m_s.fit(disp='off', show_warning=False)
                r_f = m_f.fit(disp='off', show_warning=False)
                fc_s = r_s.forecast(horizon=1)
                fc_f = r_f.forecast(horizon=1)
                sig_s = float(np.sqrt(fc_s.variance.iloc[-1, 0]))
                sig_f = float(np.sqrt(fc_f.variance.iloc[-1, 0]))
                rho = float(np.corrcoef(all_s[t-60:t], all_f[t-60:t])[0, 1])
                h_val = rho * sig_s / sig_f if sig_f > 0 else 1.0
                h_garch.append(h_val)
            except:
                h_garch.append(h_garch[-1] if h_garch else 1.0)
        else:
            h_garch.append(1.0)
    h_garch = pd.Series(h_garch, index=s_oos.index)
    hedged_garch = s_oos - h_garch * f_oos
    he_garch = float(1 - hedged_garch.var() / unhedged_var)

    # DM tests vs Naive
    def dm_test(hedged_alt, hedged_base):
        sq_base = hedged_base**2
        sq_alt = hedged_alt**2
        d = sq_base - sq_alt
        d = d.dropna()
        if len(d) < 50 or d.std() == 0:
            return 0.0
        return float(d.mean() / (d.std() / np.sqrt(len(d))))

    dm_exp = dm_test(hedged_exp, hedged_naive)
    dm_ewma = dm_test(hedged_ewma, hedged_naive)
    dm_garch = dm_test(hedged_garch, hedged_naive)

    # VaR reduction
    uvar1 = float(np.percentile(s_oos, 1))
    def var1_red(hedged):
        hv = float(np.percentile(hedged, 1))
        return float(1 - abs(hv) / abs(uvar1)) if uvar1 != 0 else 0

    result = {
        'spot': spot_t, 'futures': fut_t, 'n_oos': n_oos,
        'correlation': round(corr, 4),
        'naive': {'HE': round(he_naive, 4), 'avg_h': 1.0, 'VaR1_red': round(var1_red(hedged_naive), 4)},
        'expanding_ols': {'HE': round(he_exp, 4), 'avg_h': round(float(h_exp.mean()), 4), 'VaR1_red': round(var1_red(hedged_exp), 4), 'dm_t': round(dm_exp, 2)},
        'ewma': {'HE': round(he_ewma, 4), 'avg_h': round(float(h_ewma.mean()), 4), 'VaR1_red': round(var1_red(hedged_ewma), 4), 'dm_t': round(dm_ewma, 2)},
        'garch': {'HE': round(he_garch, 4), 'avg_h': round(float(h_garch.mean()), 4), 'VaR1_red': round(var1_red(hedged_garch), 4), 'dm_t': round(dm_garch, 2)},
    }
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

    n_cores = min(cpu_count(), 8)  # Use up to 8 cores (leave 2 for system)
    print(f"I11: Full Panel Daily GARCH Hedge ({len(pairs)} pairs, {n_cores} cores)")
    print("=" * 90)

    start = time.time()
    with Pool(n_cores) as pool:
        results_list = pool.map(evaluate_pair, pairs)
    elapsed = time.time() - start

    print(f"\nCompleted in {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"\n{'Pair':<12} {'Corr':>6} {'Naive HE':>9} {'OLS HE':>8} {'EWMA HE':>8} {'GARCH HE':>9} {'Best DM':>8} {'Winner':>10}")
    print("=" * 78)

    results_dict = {}
    naive_wins = 0
    complex_wins = 0

    for name, res in results_list:
        if res is None or 'error' in res:
            print(f"{name:<12} {'ERROR':>6}: {res.get('error', 'download failed') if res else 'failed'}")
            continue

        results_dict[name] = res
        corr = res['correlation']
        he_n = res['naive']['HE']
        he_o = res['expanding_ols']['HE']
        he_e = res['ewma']['HE']
        he_g = res['garch']['HE']

        # Best dynamic method
        best_dm = max(res['expanding_ols']['dm_t'], res['ewma']['dm_t'], res['garch']['dm_t'])
        if best_dm == res['expanding_ols']['dm_t']:
            best_name = 'OLS'
        elif best_dm == res['ewma']['dm_t']:
            best_name = 'EWMA'
        else:
            best_name = 'GARCH'

        sig = "★" if best_dm > 3 else ""
        winner = best_name if best_dm > 3 else "Naive"
        if best_dm > 3:
            complex_wins += 1
        else:
            naive_wins += 1

        print(f"{name:<12} {corr:>6.3f} {he_n:>8.1%} {he_o:>7.1%} {he_e:>7.1%} {he_g:>8.1%} {best_dm:>7.1f}{sig} {winner:>10}")

    print(f"\n{'='*78}")
    print(f"SUMMARY: Naive wins {naive_wins}/{naive_wins+complex_wins}, Complex wins {complex_wins}/{naive_wins+complex_wins}")
    print(f"Cao & Conlon (2025) prediction: Naive cannot be statistically beaten → ", end="")
    print("PARTIALLY CONFIRMED" if naive_wins > complex_wins else "REJECTED")

    output = {
        'experiment': 'I11',
        'title': 'Full Panel Daily GARCH Hedging (15 pairs, multiprocessing)',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'computation': {'cores': n_cores, 'elapsed_sec': round(elapsed)},
        'data': {'source': 'yfinance', 'oos': '2020-2025'},
        'pairs': results_dict,
        'summary': {'naive_wins': naive_wins, 'complex_wins': complex_wins},
    }

    with open('experiments/i11_full_panel_results.json', 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    print(f"\nResults saved to experiments/i11_full_panel_results.json")
