"""
K1397: VIX Memorial Day Seasonality Analysis
35-year calendar anomaly analysis (1990-2025)
"""
import pandas as pd
import numpy as np
from scipy import stats
from scipy.stats import binomtest
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

DATA_PATH = "paper/leverage-direction/data/vix_daily.csv"
SEED = 42  # for reproducibility (not used here, pure statistics)


def get_memorial_day(year):
    """Last Monday of May"""
    may_days = pd.date_range(f'{year}-05-01', f'{year}-05-31', freq='D')
    mondays = [d for d in may_days if d.dayofweek == 0]
    return max(mondays) if mondays else None


def run_analysis():
    df = pd.read_csv(DATA_PATH)
    df['date'] = pd.to_datetime(df['date'])
    df['vix'] = pd.to_numeric(df['vix'], errors='coerce')
    df = df[df['vix'].notna()].sort_values('date').reset_index(drop=True)

    memorial_days = {yr: get_memorial_day(yr) for yr in range(1990, 2026)}

    results = []
    for yr, md_date in memorial_days.items():
        if md_date is None:
            continue
        pre_dates = df[df['date'] < md_date]['date'].tail(10)
        post_dates = df[df['date'] > md_date]['date'].head(10)
        if len(pre_dates) < 5 or len(post_dates) < 5:
            continue
        pre_5 = pre_dates.tail(5).values
        post_5 = post_dates.head(5).values
        vals = {}
        for name, arr in [('pre_start', pre_5[0]), ('pre_end', pre_5[-1]),
                           ('post_start', post_5[0]), ('post_end', post_5[-1])]:
            row = df[df['date'] == arr]['vix'].values
            if len(row) == 0:
                break
            vals[name] = row[0]
        else:
            results.append({
                'year': yr,
                'memorial_day': md_date.strftime('%Y-%m-%d'),
                'vix_pre_holiday': round(float(vals['pre_end']), 2),
                'pre_5d_change_pct': round(float((vals['pre_end'] - vals['pre_start']) / vals['pre_start'] * 100), 2),
                'post_5d_change_pct': round(float((vals['post_end'] - vals['post_start']) / vals['post_start'] * 100), 2),
                'vix_post_d1': round(float(vals['post_start']), 2),
                'pre_start_vix': round(float(vals['pre_start']), 2),
            })

    rdf = pd.DataFrame(results)
    pre_chg = rdf['pre_5d_change_pct'].values
    post_chg = rdf['post_5d_change_pct'].values

    t_pre, p_pre = stats.ttest_1samp(pre_chg, 0)
    t_post, p_post = stats.ttest_1samp(post_chg, 0)
    binom_pre = binomtest(int((pre_chg < 0).sum()), len(pre_chg), 0.5)
    binom_post = binomtest(int((post_chg > 0).sum()), len(post_chg), 0.5)

    summary = {
        'n_years': len(rdf),
        'date_range': f"{int(rdf['year'].min())}-{int(rdf['year'].max())}",
        'pre_5d_mean_pct': round(float(pre_chg.mean()), 2),
        'pre_5d_std_pct': round(float(pre_chg.std()), 2),
        'pre_5d_t': round(float(t_pre), 2),
        'pre_5d_p': round(float(p_pre), 3),
        'post_5d_mean_pct': round(float(post_chg.mean()), 2),
        'post_5d_std_pct': round(float(post_chg.std()), 2),
        'post_5d_t': round(float(t_post), 2),
        'post_5d_p': round(float(p_post), 3),
        'pre_compress_n': int((pre_chg < 0).sum()),
        'pre_compress_total': len(pre_chg),
        'pre_compress_pct': round(float((pre_chg < 0).mean() * 100), 1),
        'pre_compress_binom_p': round(float(binom_pre.pvalue), 3),
        'post_rebound_n': int((post_chg > 0).sum()),
        'post_rebound_total': len(post_chg),
        'post_rebound_pct': round(float((post_chg > 0).mean() * 100), 1),
        'post_rebound_binom_p': round(float(binom_post.pvalue), 3),
        'yearly_data': rdf.to_dict('records'),
    }

    with open('experiments/k1397/k1397_results.json', 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    return rdf, summary


if __name__ == '__main__':
    rdf, summary = run_analysis()
    print(f"N={summary['n_years']} years ({summary['date_range']})")
    print(f"Pre: mean={summary['pre_5d_mean_pct']}%, t={summary['pre_5d_t']}, p={summary['pre_5d_p']}")
    print(f"Post: mean={summary['post_5d_mean_pct']}%, t={summary['post_5d_t']}, p={summary['post_5d_p']}")
