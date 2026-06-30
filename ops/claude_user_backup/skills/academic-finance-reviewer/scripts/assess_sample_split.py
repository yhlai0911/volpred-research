#!/usr/bin/env python3
"""
assess_sample_split.py
======================
Assess sample design for empirical financial econometrics research.

Checks:
- In-sample vs out-of-sample split
- Crisis period inclusion/exclusion
- Sample size adequacy for GMM/Hawkes estimation
- Subperiod analysis for robustness

Usage:
    python assess_sample_split.py --start 2010-01-01 --end 2023-12-31 --freq daily
    python assess_sample_split.py --start 2010-01-01 --end 2023-12-31 --freq 5min

Author: Academic Finance Reviewer Skill
"""

import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import warnings


class SampleSplitAssessor:
    """Assess sample design for financial econometrics research."""

    # Known crisis periods (global and Taiwan-specific)
    CRISIS_PERIODS = {
        'global_financial_crisis': ('2007-07-01', '2009-06-30'),
        'eurozone_crisis': ('2010-05-01', '2012-12-31'),
        'china_2015_crash': ('2015-06-01', '2015-09-30'),
        'covid_crash': ('2020-02-01', '2020-04-30'),
        'covid_pandemic': ('2020-01-01', '2021-12-31'),
        'rate_hike_2022': ('2022-01-01', '2023-06-30'),
        'taiwan_presidential_2020': ('2019-10-01', '2020-01-31'),
        'china_tensions_2022': ('2022-08-01', '2022-10-31')
    }

    # Minimum sample sizes for different estimation methods
    MIN_SAMPLE_SIZES = {
        'ols': {
            'daily': 252,  # 1 year
            '5min': 5000,  # ~10 days
            'hourly': 1000  # ~40 days
        },
        'garch': {
            'daily': 500,  # ~2 years
            '5min': 10000,  # ~20 days
            'hourly': 2000  # ~80 days
        },
        'gmm_simple': {
            'daily': 1000,  # ~4 years
            '5min': 20000,  # ~40 days
            'hourly': 4000  # ~160 days
        },
        'gmm_hawkes': {
            'daily': 2500,  # ~10 years (needs jumps)
            '5min': 50000,  # ~100 days
            'hourly': 10000  # ~400 days
        },
        'hawkes_bivariate': {
            'daily': 3000,  # ~12 years (more parameters)
            '5min': 100000,  # ~200 days
            'hourly': 20000  # ~800 days
        }
    }

    # Recommended splits
    RECOMMENDED_SPLITS = {
        'estimation_only': {
            'in_sample': 1.0,
            'out_sample': 0.0,
            'note': 'No forecasting - full sample for estimation'
        },
        'validation': {
            'in_sample': 0.8,
            'out_sample': 0.2,
            'note': 'Basic validation - 80/20 split'
        },
        'forecasting': {
            'in_sample': 0.7,
            'out_sample': 0.3,
            'note': 'Forecasting study - 70/30 split'
        },
        'rolling_window': {
            'in_sample': 'varies',
            'out_sample': 'varies',
            'note': 'Rolling window - specify window size'
        }
    }

    def __init__(self, frequency='daily'):
        """
        Initialize assessor.

        Parameters:
        -----------
        frequency : str
            Data frequency: 'daily', '5min', 'hourly', etc.
        """
        self.frequency = frequency

    def compute_sample_size(self, start_date: str, end_date: str,
                           exclude_weekends=True, exclude_holidays=True) -> Dict:
        """
        Compute expected sample size.

        Parameters:
        -----------
        start_date : str
            Start date (YYYY-MM-DD)
        end_date : str
            End date (YYYY-MM-DD)
        exclude_weekends : bool
            Whether to exclude weekends
        exclude_holidays : bool
            Whether to exclude holidays (~10-15 per year)

        Returns:
        --------
        result : dict
        """
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')

        total_days = (end - start).days + 1

        # Estimate trading days
        if exclude_weekends:
            trading_days = total_days * (5/7)  # Rough estimate
        else:
            trading_days = total_days

        if exclude_holidays:
            years = total_days / 365.25
            holidays_approx = years * 12  # ~12 holidays/year in Taiwan
            trading_days -= holidays_approx

        # Compute observations based on frequency
        if self.frequency == 'daily':
            obs = int(trading_days)
        elif self.frequency == '5min':
            obs = int(trading_days * 78)  # 78 5-min bars per day (09:00-13:30)
        elif self.frequency == '15min':
            obs = int(trading_days * 26)  # 26 15-min bars
        elif self.frequency == '30min':
            obs = int(trading_days * 13)  # 13 30-min bars
        elif self.frequency == 'hourly':
            obs = int(trading_days * 6.5)  # ~6-7 hours per day
        else:
            obs = int(trading_days)  # Default to daily

        return {
            'start_date': start_date,
            'end_date': end_date,
            'total_days': total_days,
            'trading_days': int(trading_days),
            'frequency': self.frequency,
            'estimated_observations': obs,
            'years': total_days / 365.25
        }

    def check_crisis_overlap(self, start_date: str, end_date: str) -> Dict:
        """
        Check which crisis periods overlap with sample.

        Parameters:
        -----------
        start_date : str
            Sample start date
        end_date : str
            Sample end date

        Returns:
        --------
        result : dict
        """
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')

        overlapping_crises = []
        crisis_days = 0

        for crisis_name, (crisis_start, crisis_end) in self.CRISIS_PERIODS.items():
            c_start = datetime.strptime(crisis_start, '%Y-%m-%d')
            c_end = datetime.strptime(crisis_end, '%Y-%m-%d')

            # Check overlap
            overlap_start = max(start, c_start)
            overlap_end = min(end, c_end)

            if overlap_start <= overlap_end:
                overlap_days = (overlap_end - overlap_start).days + 1
                crisis_days += overlap_days

                overlapping_crises.append({
                    'name': crisis_name,
                    'period': (crisis_start, crisis_end),
                    'overlap_days': overlap_days,
                    'overlap_pct': overlap_days / ((end - start).days + 1) * 100
                })

        return {
            'has_crisis': len(overlapping_crises) > 0,
            'num_crises': len(overlapping_crises),
            'overlapping_crises': overlapping_crises,
            'total_crisis_days': crisis_days,
            'crisis_percentage': crisis_days / ((end - start).days + 1) * 100
        }

    def assess_adequacy(self, num_observations: int, method='gmm_hawkes') -> Dict:
        """
        Assess if sample size is adequate for estimation method.

        Parameters:
        -----------
        num_observations : int
            Number of observations
        method : str
            Estimation method: 'ols', 'garch', 'gmm_simple', 'gmm_hawkes', 'hawkes_bivariate'

        Returns:
        --------
        result : dict
        """
        if method not in self.MIN_SAMPLE_SIZES:
            return {'error': f'Unknown method: {method}'}

        min_sizes = self.MIN_SAMPLE_SIZES[method]

        if self.frequency not in min_sizes:
            # Use daily as baseline
            min_required = min_sizes['daily']
            warnings.warn(f"No guideline for frequency '{self.frequency}', using daily baseline")
        else:
            min_required = min_sizes[self.frequency]

        is_adequate = num_observations >= min_required
        excess_ratio = num_observations / min_required

        status = 'adequate' if is_adequate else 'inadequate'
        if excess_ratio > 3:
            status = 'excellent'
        elif excess_ratio > 1.5:
            status = 'good'
        elif excess_ratio > 1:
            status = 'adequate'
        elif excess_ratio > 0.75:
            status = 'marginal'
        else:
            status = 'inadequate'

        return {
            'is_adequate': is_adequate,
            'num_observations': num_observations,
            'min_required': min_required,
            'excess_ratio': excess_ratio,
            'status': status,
            'method': method,
            'frequency': self.frequency
        }

    def recommend_split(self, total_obs: int, purpose='estimation_only') -> Dict:
        """
        Recommend in-sample / out-of-sample split.

        Parameters:
        -----------
        total_obs : int
            Total number of observations
        purpose : str
            'estimation_only', 'validation', 'forecasting', 'rolling_window'

        Returns:
        --------
        recommendation : dict
        """
        if purpose not in self.RECOMMENDED_SPLITS:
            purpose = 'validation'

        split_info = self.RECOMMENDED_SPLITS[purpose]

        if purpose == 'rolling_window':
            return {
                'purpose': purpose,
                'note': split_info['note'],
                'recommendation': 'Specify rolling window size (e.g., 1000 obs) and step size'
            }

        in_sample_obs = int(total_obs * split_info['in_sample'])
        out_sample_obs = int(total_obs * split_info['out_sample'])

        return {
            'purpose': purpose,
            'total_observations': total_obs,
            'in_sample_observations': in_sample_obs,
            'out_sample_observations': out_sample_obs,
            'in_sample_percentage': split_info['in_sample'] * 100,
            'out_sample_percentage': split_info['out_sample'] * 100,
            'note': split_info['note']
        }

    def suggest_subperiods(self, start_date: str, end_date: str,
                          num_subperiods=3, equal_length=True) -> Dict:
        """
        Suggest subperiod splits for robustness checks.

        Parameters:
        -----------
        start_date : str
            Sample start
        end_date : str
            Sample end
        num_subperiods : int
            Number of subperiods
        equal_length : bool
            Whether subperiods should be equal length

        Returns:
        --------
        subperiods : dict
        """
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')

        total_days = (end - start).days + 1

        if equal_length:
            days_per_period = total_days // num_subperiods

            subperiods = []
            for i in range(num_subperiods):
                sub_start = start + timedelta(days=i * days_per_period)
                if i == num_subperiods - 1:
                    sub_end = end
                else:
                    sub_end = start + timedelta(days=(i+1) * days_per_period - 1)

                subperiods.append({
                    'period': i+1,
                    'start': sub_start.strftime('%Y-%m-%d'),
                    'end': sub_end.strftime('%Y-%m-%d'),
                    'days': (sub_end - sub_start).days + 1
                })
        else:
            # Crisis-aware splits (example)
            crisis_info = self.check_crisis_overlap(start_date, end_date)

            subperiods = [
                {
                    'period': 'pre_crisis',
                    'note': 'Normal market conditions'
                },
                {
                    'period': 'crisis',
                    'note': 'Crisis periods'
                },
                {
                    'period': 'post_crisis',
                    'note': 'Recovery period'
                }
            ]

        return {
            'num_subperiods': num_subperiods,
            'equal_length': equal_length,
            'subperiods': subperiods
        }

    def generate_report(self, start_date: str, end_date: str,
                       method='gmm_hawkes', purpose='estimation_only',
                       verbose=True) -> Dict:
        """
        Generate comprehensive sample design assessment report.

        Parameters:
        -----------
        start_date : str
            Start date
        end_date : str
            End date
        method : str
            Estimation method
        purpose : str
            Research purpose
        verbose : bool
            Print report

        Returns:
        --------
        report : dict
        """
        report = {}

        # Sample size
        report['sample_size'] = self.compute_sample_size(start_date, end_date)

        # Crisis overlap
        report['crisis_overlap'] = self.check_crisis_overlap(start_date, end_date)

        # Adequacy
        num_obs = report['sample_size']['estimated_observations']
        report['adequacy'] = self.assess_adequacy(num_obs, method)

        # Split recommendation
        report['split_recommendation'] = self.recommend_split(num_obs, purpose)

        # Subperiod suggestion
        report['subperiods'] = self.suggest_subperiods(start_date, end_date)

        # Overall assessment
        issues = []
        warnings_list = []

        if not report['adequacy']['is_adequate']:
            issues.append(
                f"❌ CRITICAL: Sample size ({num_obs}) insufficient for {method} "
                f"(minimum: {report['adequacy']['min_required']})"
            )

        if report['adequacy']['status'] == 'marginal':
            warnings_list.append(
                f"⚠️  Sample size is marginal for {method}. Consider longer sample period."
            )

        if not report['crisis_overlap']['has_crisis']:
            warnings_list.append(
                "💡 No major crisis periods in sample. Consider including crisis period "
                "for robustness or explicitly justify normal-period focus."
            )

        if report['crisis_overlap']['crisis_percentage'] > 40:
            warnings_list.append(
                f"⚠️  Sample is {report['crisis_overlap']['crisis_percentage']:.1f}% crisis periods. "
                "Ensure results are not overly influenced by crisis dynamics."
            )

        report['overall'] = {
            'is_valid': len(issues) == 0,
            'num_issues': len(issues),
            'num_warnings': len(warnings_list),
            'issues': issues,
            'warnings': warnings_list
        }

        if verbose:
            self.print_report(report)

        return report

    @staticmethod
    def print_report(report: Dict):
        """Print human-readable assessment report."""

        print("\n" + "="*70)
        print("SAMPLE DESIGN ASSESSMENT REPORT")
        print("="*70)

        # Sample size
        ss = report['sample_size']
        print("\n1. SAMPLE SIZE")
        print("-" * 70)
        print(f"   Period:                    {ss['start_date']} to {ss['end_date']}")
        print(f"   Total days:                {ss['total_days']}")
        print(f"   Trading days:              {ss['trading_days']}")
        print(f"   Years:                     {ss['years']:.2f}")
        print(f"   Frequency:                 {ss['frequency']}")
        print(f"   Estimated observations:    {ss['estimated_observations']:,}")

        # Adequacy
        adeq = report['adequacy']
        print("\n2. SAMPLE ADEQUACY")
        print("-" * 70)
        print(f"   Method:                    {adeq['method']}")
        print(f"   Minimum required:          {adeq['min_required']:,}")
        print(f"   Actual:                    {adeq['num_observations']:,}")
        print(f"   Excess ratio:              {adeq['excess_ratio']:.2f}x")
        print(f"   Status:                    {adeq['status'].upper()}")

        status_icon = {
            'excellent': '✅',
            'good': '✅',
            'adequate': '✓',
            'marginal': '⚠️',
            'inadequate': '❌'
        }
        print(f"   {status_icon.get(adeq['status'], '?')} Assessment: {adeq['status']}")

        # Crisis overlap
        crisis = report['crisis_overlap']
        print("\n3. CRISIS PERIOD OVERLAP")
        print("-" * 70)
        if crisis['has_crisis']:
            print(f"   Number of crises:          {crisis['num_crises']}")
            print(f"   Total crisis days:         {crisis['total_crisis_days']}")
            print(f"   Crisis percentage:         {crisis['crisis_percentage']:.1f}%")
            print("\n   Overlapping crises:")
            for c in crisis['overlapping_crises']:
                print(f"   - {c['name']}: {c['overlap_days']} days ({c['overlap_pct']:.1f}%)")
        else:
            print("   ✓ No major crisis periods in sample")

        # Split recommendation
        split = report['split_recommendation']
        print("\n4. SAMPLE SPLIT RECOMMENDATION")
        print("-" * 70)
        print(f"   Purpose:                   {split['purpose']}")
        if 'in_sample_observations' in split:
            print(f"   In-sample:                 {split['in_sample_observations']:,} obs ({split['in_sample_percentage']:.0f}%)")
            print(f"   Out-of-sample:             {split['out_sample_observations']:,} obs ({split['out_sample_percentage']:.0f}%)")
        print(f"   Note: {split['note']}")

        # Subperiods
        sub = report['subperiods']
        print("\n5. ROBUSTNESS CHECK SUBPERIODS")
        print("-" * 70)
        print(f"   Number of subperiods:      {sub['num_subperiods']}")
        for sp in sub['subperiods']:
            if 'start' in sp:
                print(f"   Period {sp['period']}: {sp['start']} to {sp['end']} ({sp['days']} days)")

        # Overall
        print("\n" + "="*70)
        print("OVERALL ASSESSMENT:")
        overall = report['overall']

        if overall['is_valid']:
            print("✅ SAMPLE DESIGN APPEARS ADEQUATE")
        else:
            print(f"❌ FOUND {overall['num_issues']} CRITICAL ISSUE(S)")

        for issue in overall['issues']:
            print(f"   {issue}")

        for warning in overall['warnings']:
            print(f"   {warning}")

        print("="*70 + "\n")


def example_usage():
    """Example usage for Hawkes estimation."""

    # Example 1: Daily data, long sample
    assessor1 = SampleSplitAssessor(frequency='daily')

    print("="*70)
    print("EXAMPLE 1: Daily Data (2003-2023, 20 years)")
    print("="*70)

    report1 = assessor1.generate_report(
        start_date='2003-01-01',
        end_date='2023-12-31',
        method='hawkes_bivariate',
        purpose='estimation_only',
        verbose=True
    )

    # Example 2: High-frequency data, shorter sample
    assessor2 = SampleSplitAssessor(frequency='5min')

    print("\n" + "="*70)
    print("EXAMPLE 2: 5-Minute Data (2020-2023, 3 years)")
    print("="*70)

    report2 = assessor2.generate_report(
        start_date='2020-01-01',
        end_date='2023-12-31',
        method='hawkes_bivariate',
        purpose='validation',
        verbose=True
    )

    # Example 3: Insufficient sample
    assessor3 = SampleSplitAssessor(frequency='daily')

    print("\n" + "="*70)
    print("EXAMPLE 3: Too Short Sample (Should flag inadequacy)")
    print("="*70)

    report3 = assessor3.generate_report(
        start_date='2022-01-01',
        end_date='2023-12-31',
        method='hawkes_bivariate',
        purpose='estimation_only',
        verbose=True
    )


if __name__ == '__main__':
    example_usage()
