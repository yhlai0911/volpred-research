#!/usr/bin/env python3
"""Basel III VaR Compliance Report Generator.

Runs GJR-GARCH(1,1) w=504 with Student-t VaR and generates
annual Basel III compliance reports.

Usage:
    python scripts/var_report.py                  # Full report (2020-current)
    python scripts/var_report.py --year 2025      # Single year
    python scripts/var_report.py --publish         # Auto-publish to web
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats


def get_var_threshold(sigma: float, df: float = 5.0, sigma_ann_threshold: float = 0.13) -> float:
    """Compute Student-t VaR threshold with adaptive low-vol adjustment.

    Args:
        sigma: Daily standard deviation forecast
        df: Student-t degrees of freedom
        sigma_ann_threshold: Annualized sigma below which to use stricter quantile
    """
    scale = np.sqrt((df - 2) / df)
    sigma_ann = sigma * np.sqrt(252)
    if sigma_ann < sigma_ann_threshold:
        z = -stats.t.ppf(0.005, df) * scale  # Stricter: 0.5% quantile
    else:
        z = -stats.t.ppf(0.01, df) * scale   # Standard: 1% quantile
    return z * sigma


def kupiec_test(violations: np.ndarray, alpha: float = 0.01) -> dict:
    """Kupiec's Proportion of Failures test."""
    T = len(violations)
    n = int(np.sum(violations))
    if n == 0 or n == T:
        return {'statistic': float('inf'), 'p_value': 0.0, 'n': n, 'T': T}
    p_hat = n / T
    lr = -2 * (np.log((1 - alpha) ** (T - n) * alpha ** n) -
               np.log((1 - p_hat) ** (T - n) * p_hat ** n))
    p_value = 1 - stats.chi2.cdf(lr, 1)
    return {'statistic': round(lr, 4), 'p_value': round(p_value, 4), 'n': n, 'T': T}


def basel_zone(n_violations: int) -> str:
    """Determine Basel III zone from violation count."""
    if n_violations <= 4:
        return 'GREEN'
    elif n_violations <= 9:
        return 'YELLOW'
    return 'RED'


def run_report(asset: str = 'SPY', start_year: int = 2020, end_date: str | None = None,
               single_year: int | None = None, df: float = 5.0, publish: bool = False):
    """Generate Basel III VaR compliance report."""
    if end_date is None:
        end_date = datetime.now().strftime('%Y-%m-%d')

    # Need 504 days before start_year for initial window
    data_start = f'{start_year - 3}-01-01'
    data = yf.download(asset, start=data_start, end=end_date, progress=False)
    data['return'] = data['Close'].pct_change()
    data = data.dropna()

    # Run rolling GJR-GARCH(1,1) w=504
    from arch import arch_model

    oos_start = f'{start_year}-01-01'
    if single_year:
        oos_start = f'{single_year}-01-01'
        oos_end = f'{single_year}-12-31'
    else:
        oos_end = end_date

    oos_mask = (data.index >= oos_start) & (data.index <= oos_end)
    oos_dates = data.index[oos_mask]

    if len(oos_dates) == 0:
        print(f'No data for {oos_start} to {oos_end}')
        return

    returns_pct = data['return'] * 100
    window = 504

    print(f'Running GJR-GARCH(1,1) w={window} for {asset}...')
    print(f'OOS: {oos_dates[0].strftime("%Y-%m-%d")} to {oos_dates[-1].strftime("%Y-%m-%d")} ({len(oos_dates)} days)')

    forecasts = []
    for date in oos_dates:
        idx = data.index.get_loc(date)
        if idx < window:
            continue
        train = returns_pct.iloc[idx - window:idx]
        try:
            am = arch_model(train, vol='GARCH', p=1, q=1, o=1, dist='normal', mean='Zero')
            res = am.fit(disp='off')
            sigma_daily = res.forecast(horizon=1).variance.iloc[-1, 0] ** 0.5 / 100
            forecasts.append({
                'date': date,
                'sigma': sigma_daily,
                'return': data['return'].iloc[idx]
            })
        except Exception:
            continue

    if not forecasts:
        print('No forecasts generated')
        return

    dates = [f['date'] for f in forecasts]
    sigmas = np.array([f['sigma'] for f in forecasts])
    returns = np.array([f['return'] for f in forecasts])

    # Compute VaR (Normal and Student-t Adaptive)
    var_normal = -stats.norm.ppf(0.01) * sigmas
    var_studentt = np.array([get_var_threshold(s, df=df) for s in sigmas])

    viol_normal = (returns < -var_normal).astype(int)
    viol_studentt = (returns < -var_studentt).astype(int)

    # Per-year results
    years_arr = pd.DatetimeIndex(dates).year
    unique_years = sorted(set(years_arr))

    print()
    print(f'{"=" * 72}')
    print(f' {asset} Basel III VaR Backtest Report')
    print(f' Model: GJR-GARCH(1,1) w={window}, Student-t(df={df:.1f}) + Adaptive')
    print(f' Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print(f'{"=" * 72}')
    print()
    print(f'{"Year":>6} | {"Days":>4} | {"Normal":>8} | {"Student-t":>10} | {"Zone":>8} | {"Kupiec p":>9}')
    print('-' * 60)

    report_data = []
    for yr in unique_years:
        mask = years_arr == yr
        n = mask.sum()
        vn = viol_normal[mask].sum()
        vt = viol_studentt[mask].sum()
        zone = basel_zone(vt)
        kup = kupiec_test(viol_studentt[mask], alpha=0.01)
        kup_str = f'{kup["p_value"]:.4f}' if kup['p_value'] > 0 else 'N/A'

        print(f'{yr:>6} | {n:>4} | {vn:>3} ({vn/n*100:.1f}%) | {vt:>5} ({vt/n*100:.1f}%) | {zone:>8} | {kup_str:>9}')
        report_data.append({
            'year': yr, 'days': n,
            'violations_normal': int(vn), 'violations_studentt': int(vt),
            'zone': zone, 'kupiec_p': kup['p_value']
        })

    print('-' * 60)
    total = len(returns)
    tn = viol_normal.sum()
    tt = viol_studentt.sum()
    overall_kup = kupiec_test(viol_studentt, alpha=0.01)
    print(f'{"Total":>6} | {total:>4} | {tn:>3} ({tn/total*100:.1f}%) | {tt:>5} ({tt/total*100:.1f}%) | {"":>8} | {overall_kup["p_value"]:.4f}')

    green_count = sum(1 for r in report_data if r['zone'] == 'GREEN')
    print(f'\nResult: {green_count}/{len(unique_years)} years in Green Zone')

    if green_count == len(unique_years):
        print('*** ALL YEARS GREEN ZONE ***')

    # Save report
    report = {
        'asset': asset,
        'model': f'GJR-GARCH(1,1) w={window}',
        'distribution': f'Student-t(df={df:.1f}) Adaptive',
        'generated_at': datetime.now().isoformat(),
        'years': report_data,
        'total_days': total,
        'total_violations_normal': int(tn),
        'total_violations_studentt': int(tt),
        'kupiec_p_overall': overall_kup['p_value'],
        'green_zone_ratio': f'{green_count}/{len(unique_years)}'
    }

    report_path = Path('storage/reports/var_compliance_report.json')
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    print(f'\nReport saved to {report_path}')

    if publish:
        try:
            sys.path.insert(0, '.')
            from src.volpred.publisher.publisher import Publisher
            p = Publisher()
            title = f'{asset} Basel III VaR Report: {green_count}/{len(unique_years)} Green Zone'
            desc = f'GJR w={window} + Student-t(df={df:.1f}). '
            desc += f'Total: {tt}/{total} violations ({tt/total*100:.1f}%). '
            desc += f'Kupiec p={overall_kup["p_value"]:.4f}.'
            p.publish_milestone(title=title, description=desc, phase='J6',
                              details=report)
            print('Published to web platform')
        except Exception as e:
            print(f'Publish failed: {e}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Basel III VaR Compliance Report')
    parser.add_argument('--asset', default='SPY', help='Asset ticker')
    parser.add_argument('--year', type=int, help='Single year to report')
    parser.add_argument('--start-year', type=int, default=2020, help='Start year (default: 2020)')
    parser.add_argument('--df', type=float, default=5.0, help='Student-t degrees of freedom')
    parser.add_argument('--publish', action='store_true', help='Publish to web platform')
    args = parser.parse_args()

    run_report(
        asset=args.asset,
        start_year=args.start_year,
        single_year=args.year,
        df=args.df,
        publish=args.publish,
    )
