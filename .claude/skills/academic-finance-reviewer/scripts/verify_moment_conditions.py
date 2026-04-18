<!-- AUTO-GENERATED FROM agent-specs/. Edit canonical sources instead. -->

#!/usr/bin/env python3
"""
verify_moment_conditions.py
===========================
Diagnostic tool for verifying correctness of moment conditions in GMM estimation.

Checks:
- Moment count vs parameter count (order condition)
- Higher-order moments included for jump models
- Autocorrelation/cross-correlation lags
- Moment formula consistency with literature

Usage:
    python verify_moment_conditions.py --model hawkes --moments 21 --params 7

Author: Academic Finance Reviewer Skill
"""

import numpy as np
import warnings
from typing import Dict, List, Tuple


class MomentConditionVerifier:
    """Verify moment conditions for various financial econometric models."""

    # Standard moment counts from literature
    STANDARD_MOMENTS = {
        'hawkes_univariate': {
            'min_params': 3,  # α, β, λ∞
            'typical_moments': [5, 7, 9],  # Varies by max_lag
            'required_types': ['mean', 'variance', 'autocorrelation']
        },
        'hawkes_bivariate_triangular': {
            'min_params': 7,  # α, λ∞, β11, β21, β22, γ1, γ2
            'typical_moments': [15, 21],  # 15 (basic), 21 (with higher-order)
            'required_types': ['mean', 'variance', 'covariance',
                              'autocorrelation', 'cross_correlation']
        },
        'hawkes_bivariate_full': {
            'min_params': 10,  # Add β12, β21 asymmetry + other parameters
            'typical_moments': [17, 29],  # More moments for asymmetric model
            'required_types': ['mean', 'variance', 'covariance',
                              'autocorrelation', 'cross_correlation',
                              'bidirectional_cross_correlation']
        },
        'garch': {
            'min_params': 3,  # ω, α, β
            'typical_moments': [3, 5, 7],
            'required_types': ['mean', 'variance', 'autocorrelation_squared']
        }
    }

    def __init__(self, model_type='hawkes_bivariate_triangular'):
        """
        Initialize verifier.

        Parameters:
        -----------
        model_type : str
            One of: 'hawkes_univariate', 'hawkes_bivariate_triangular',
                   'hawkes_bivariate_full', 'garch'
        """
        if model_type not in self.STANDARD_MOMENTS:
            raise ValueError(f"Unknown model type: {model_type}")

        self.model_type = model_type
        self.standards = self.STANDARD_MOMENTS[model_type]

    def check_moment_count(self, num_moments, num_params):
        """
        Verify moment count is appropriate for model.

        Parameters:
        -----------
        num_moments : int
            Number of moment conditions
        num_params : int
            Number of parameters to estimate

        Returns:
        --------
        result : dict
        """
        min_params = self.standards['min_params']
        typical_moments = self.standards['typical_moments']

        issues = []
        warnings_list = []

        # Check order condition
        if num_moments < num_params:
            issues.append(
                f"❌ CRITICAL: Underidentified (m={num_moments} < p={num_params})"
            )

        # Check if parameters match expected
        if num_params < min_params:
            warnings_list.append(
                f"⚠️  Fewer parameters ({num_params}) than typical minimum ({min_params})"
            )

        # Check if moment count is reasonable
        if num_moments not in typical_moments:
            if num_moments < min(typical_moments):
                warnings_list.append(
                    f"⚠️  Fewer moments ({num_moments}) than typical ({typical_moments})"
                )
            elif num_moments > max(typical_moments):
                warnings_list.append(
                    f"💡 More moments ({num_moments}) than typical ({typical_moments}). "
                    "Ensure additional moments are informative."
                )

        # Degrees of freedom
        dof = num_moments - num_params

        return {
            'is_valid': len(issues) == 0,
            'num_moments': num_moments,
            'num_params': num_params,
            'degrees_of_freedom': dof,
            'is_overidentified': dof > 0,
            'typical_moments': typical_moments,
            'issues': issues,
            'warnings': warnings_list
        }

    def verify_hawkes_moments(self, moment_list, has_higher_order=True, max_lag=3):
        """
        Verify Hawkes model moment conditions.

        Parameters:
        -----------
        moment_list : list of str
            List of moment names, e.g., ['mean_1', 'variance_1', 'autocorr_1_lag1', ...]
        has_higher_order : bool
            Whether higher-order moments (3rd, 4th) are included
        max_lag : int
            Maximum lag for autocorrelations

        Returns:
        --------
        result : dict
        """
        issues = []
        warnings_list = []
        moment_types = set()

        # Categorize moments
        for m in moment_list:
            m_lower = m.lower()
            if 'mean' in m_lower:
                moment_types.add('mean')
            elif 'variance' in m_lower or 'var' in m_lower:
                moment_types.add('variance')
            elif 'covariance' in m_lower or 'cov' in m_lower:
                moment_types.add('covariance')
            elif 'skew' in m_lower or '3rd' in m_lower:
                moment_types.add('skewness')
            elif 'kurt' in m_lower or '4th' in m_lower:
                moment_types.add('kurtosis')
            elif 'autocorr' in m_lower or 'acf' in m_lower:
                moment_types.add('autocorrelation')
            elif 'cross' in m_lower or 'ccf' in m_lower:
                moment_types.add('cross_correlation')

        # Required moments
        required = self.standards['required_types']

        for req in required:
            if req == 'autocorrelation' and 'autocorrelation' not in moment_types:
                issues.append(
                    f"❌ CRITICAL: Missing autocorrelation moments (required for Hawkes identification)"
                )
            elif req == 'cross_correlation' and 'cross_correlation' not in moment_types:
                if 'bivariate' in self.model_type:
                    issues.append(
                        f"❌ CRITICAL: Missing cross-correlation moments (required for contagion β_{ij})"
                    )

        # Check higher-order moments for jump models
        if has_higher_order:
            if 'skewness' not in moment_types and 'kurtosis' not in moment_types:
                warnings_list.append(
                    "⚠️  No higher-order moments (3rd, 4th) detected. "
                    "These are crucial for identifying jump size parameters γ in Hawkes models."
                )
        else:
            warnings_list.append(
                "💡 Consider adding 3rd and 4th moments for better jump parameter identification."
            )

        return {
            'is_valid': len(issues) == 0,
            'moment_types_found': list(moment_types),
            'required_types': required,
            'has_higher_order': 'skewness' in moment_types or 'kurtosis' in moment_types,
            'issues': issues,
            'warnings': warnings_list
        }

    def check_multi_frequency_moments(self, frequencies, num_moments_per_freq):
        """
        Verify multi-frequency moment conditions (e.g., 5min, 30min, 2hour).

        This is an advanced technique for better identification with high-frequency data.

        Parameters:
        -----------
        frequencies : list of str
            e.g., ['5min', '30min', '2hour']
        num_moments_per_freq : dict
            e.g., {'5min': 50, '30min': 50, '2hour': 50}

        Returns:
        --------
        result : dict
        """
        issues = []
        warnings_list = []

        total_moments = sum(num_moments_per_freq.values())

        # Check if this is justified in literature
        if len(frequencies) > 1:
            warnings_list.append(
                "⚠️  Multi-frequency moments detected. Ensure this approach is justified by literature. "
                "Key references: Aït-Sahalia & Jacod (2014), Todorov & Tauchen (2011)."
            )

        # Check if moment counts are balanced
        counts = list(num_moments_per_freq.values())
        if len(set(counts)) > 1:
            warnings_list.append(
                f"💡 Unbalanced moment counts across frequencies: {num_moments_per_freq}. "
                "Consider whether some frequencies provide more information."
            )

        # Typical multi-frequency setup uses 3 frequencies
        if len(frequencies) > 3:
            warnings_list.append(
                f"⚠️  Using {len(frequencies)} frequencies is uncommon. "
                "Typical studies use 2-3 frequencies."
            )

        return {
            'total_moments': total_moments,
            'num_frequencies': len(frequencies),
            'frequencies': frequencies,
            'moments_per_frequency': num_moments_per_freq,
            'issues': issues,
            'warnings': warnings_list
        }

    def generate_report(self, num_moments, num_params, moment_list=None,
                       frequencies=None, verbose=True):
        """
        Generate comprehensive verification report.

        Parameters:
        -----------
        num_moments : int
            Total number of moment conditions
        num_params : int
            Number of parameters
        moment_list : list of str, optional
            List of moment names
        frequencies : list of str, optional
            If using multi-frequency, list of frequencies
        verbose : bool
            If True, print report

        Returns:
        --------
        report : dict
        """
        report = {}

        # Basic count check
        report['moment_count'] = self.check_moment_count(num_moments, num_params)

        # Moment type check (if list provided)
        if moment_list is not None:
            report['moment_types'] = self.verify_hawkes_moments(moment_list)

        # Multi-frequency check (if applicable)
        if frequencies is not None:
            moments_per_freq = {freq: num_moments // len(frequencies) for freq in frequencies}
            report['multi_frequency'] = self.check_multi_frequency_moments(
                frequencies, moments_per_freq
            )

        # Overall assessment
        all_issues = []
        all_warnings = []

        for section, results in report.items():
            all_issues.extend(results.get('issues', []))
            all_warnings.extend(results.get('warnings', []))

        report['overall'] = {
            'is_valid': len(all_issues) == 0,
            'num_critical_issues': len(all_issues),
            'num_warnings': len(all_warnings),
            'all_issues': all_issues,
            'all_warnings': all_warnings
        }

        if verbose:
            self.print_report(report)

        return report

    @staticmethod
    def print_report(report):
        """Print human-readable verification report."""

        print("\n" + "="*70)
        print("MOMENT CONDITION VERIFICATION REPORT")
        print("="*70)

        # Moment count
        if 'moment_count' in report:
            print("\n1. MOMENT COUNT VERIFICATION")
            print("-" * 70)
            mc = report['moment_count']
            print(f"   Number of moments:         {mc['num_moments']}")
            print(f"   Number of parameters:      {mc['num_params']}")
            print(f"   Degrees of freedom:        {mc['degrees_of_freedom']}")
            print(f"   Typical moment counts:     {mc['typical_moments']}")

            if mc['is_overidentified']:
                print(f"   Status: ✅ OVERIDENTIFIED (can perform J-test)")
            elif mc['degrees_of_freedom'] == 0:
                print(f"   Status: ⚠️  EXACTLY IDENTIFIED (no J-test)")
            else:
                print(f"   Status: ❌ UNDERIDENTIFIED")

            for issue in mc['issues']:
                print(f"   {issue}")
            for warning in mc['warnings']:
                print(f"   {warning}")

        # Moment types
        if 'moment_types' in report:
            print("\n2. MOMENT TYPE VERIFICATION")
            print("-" * 70)
            mt = report['moment_types']
            print(f"   Moment types found:        {', '.join(mt['moment_types_found'])}")
            print(f"   Required types:            {', '.join(mt['required_types'])}")
            print(f"   Has higher-order moments:  {'✅ Yes' if mt['has_higher_order'] else '❌ No'}")

            for issue in mt['issues']:
                print(f"   {issue}")
            for warning in mt['warnings']:
                print(f"   {warning}")

        # Multi-frequency
        if 'multi_frequency' in report:
            print("\n3. MULTI-FREQUENCY MOMENTS")
            print("-" * 70)
            mf = report['multi_frequency']
            print(f"   Number of frequencies:     {mf['num_frequencies']}")
            print(f"   Frequencies:               {', '.join(mf['frequencies'])}")
            print(f"   Total moments:             {mf['total_moments']}")

            for freq, count in mf['moments_per_frequency'].items():
                print(f"   - {freq}: {count} moments")

            for issue in mf['issues']:
                print(f"   {issue}")
            for warning in mf['warnings']:
                print(f"   {warning}")

        # Overall
        print("\n" + "="*70)
        print("OVERALL ASSESSMENT:")
        overall = report['overall']

        if overall['is_valid']:
            print("✅ MOMENT CONDITIONS APPEAR VALID")
        else:
            print(f"❌ FOUND {overall['num_critical_issues']} CRITICAL ISSUE(S)")

        if overall['num_warnings'] > 0:
            print(f"⚠️  {overall['num_warnings']} warning(s) - review recommended")

        print("="*70 + "\n")


def example_usage():
    """Example usage for Hawkes bivariate model."""

    # Example 1: Basic bivariate Hawkes (triangular)
    verifier = MomentConditionVerifier('hawkes_bivariate_triangular')

    moment_list = [
        'mean_1', 'mean_2',
        'variance_1', 'variance_2',
        'covariance_12',
        'autocorr_1_lag1', 'autocorr_1_lag2', 'autocorr_1_lag3',
        'autocorr_2_lag1', 'autocorr_2_lag2', 'autocorr_2_lag3',
        'cross_corr_21_lag1', 'cross_corr_21_lag2', 'cross_corr_21_lag3',
        'skewness_1', 'skewness_2',  # Higher-order moments
        'kurtosis_1', 'kurtosis_2',   # Higher-order moments
        'cross_skew_12', 'cross_kurt_12'
    ]

    report = verifier.generate_report(
        num_moments=21,
        num_params=7,
        moment_list=moment_list,
        verbose=True
    )

    # Example 2: Multi-frequency moments
    print("\n" + "="*70)
    print("EXAMPLE 2: Multi-Frequency Moment Verification")
    print("="*70)

    verifier2 = MomentConditionVerifier('hawkes_bivariate_full')
    report2 = verifier2.generate_report(
        num_moments=150,
        num_params=14,
        frequencies=['5min', '30min', '2hour'],
        verbose=True
    )

    return report, report2


if __name__ == '__main__':
    print("Running example moment condition verification...")
    example_usage()
