#!/usr/bin/env python3
"""
check_identification.py
=======================
Diagnostic tool for assessing parameter identification in GMM estimation.

Usage:
    python check_identification.py --params <param_file> --moments <moment_file>

    Or import as module:
    from check_identification import check_identification
    result = check_identification(params, moment_func, data)

Author: Academic Finance Reviewer Skill
"""

import numpy as np
from scipy.optimize import approx_fprime
import warnings


def compute_jacobian(params, moment_func, epsilon=1e-7):
    """
    Compute Jacobian matrix of moment conditions with respect to parameters.

    Parameters:
    -----------
    params : array-like
        Parameter vector (length p)
    moment_func : callable
        Function that computes moment conditions: moment_func(params) -> array of length m
    epsilon : float
        Step size for numerical differentiation

    Returns:
    --------
    jacobian : ndarray, shape (m, p)
        Jacobian matrix ∂g/∂θ
    """
    params = np.asarray(params)
    p = len(params)

    # Compute moments at current parameters
    g0 = moment_func(params)
    m = len(g0)

    # Initialize Jacobian matrix
    jacobian = np.zeros((m, p))

    # Compute numerical gradient for each parameter
    for j in range(p):
        def f(theta_j):
            theta_temp = params.copy()
            theta_temp[j] = theta_j
            return moment_func(theta_temp)

        jacobian[:, j] = approx_fprime(params[j:j+1], f, epsilon)

    return jacobian


def check_rank_condition(jacobian, tolerance=1e-10):
    """
    Check rank condition for identification.

    For GMM identification, we need rank(Jacobian) = p (number of parameters).

    Parameters:
    -----------
    jacobian : ndarray, shape (m, p)
        Jacobian matrix
    tolerance : float
        Tolerance for considering singular values as zero

    Returns:
    --------
    result : dict
        - is_identified : bool
        - rank : int
        - num_params : int
        - singular_values : ndarray
        - condition_number : float
    """
    m, p = jacobian.shape

    # Compute SVD
    U, s, Vt = np.linalg.svd(jacobian, full_matrices=False)

    # Count non-zero singular values
    rank = np.sum(s > tolerance)

    # Condition number (ratio of largest to smallest non-zero singular value)
    if rank > 0:
        s_nonzero = s[s > tolerance]
        condition_number = s_nonzero[0] / s_nonzero[-1] if len(s_nonzero) > 1 else 1.0
    else:
        condition_number = np.inf

    is_identified = (rank == p)

    return {
        'is_identified': is_identified,
        'rank': rank,
        'num_params': p,
        'num_moments': m,
        'singular_values': s,
        'condition_number': condition_number,
        'min_singular_value': s[-1] if len(s) > 0 else 0,
        'max_singular_value': s[0] if len(s) > 0 else 0
    }


def check_order_condition(num_moments, num_params):
    """
    Check order condition (necessary but not sufficient for identification).

    For GMM, we need m >= p (at least as many moments as parameters).

    Parameters:
    -----------
    num_moments : int
        Number of moment conditions
    num_params : int
        Number of parameters to estimate

    Returns:
    --------
    result : dict
        - is_satisfied : bool
        - num_moments : int
        - num_params : int
        - degrees_of_freedom : int
        - is_overidentified : bool
    """
    dof = num_moments - num_params

    return {
        'is_satisfied': num_moments >= num_params,
        'num_moments': num_moments,
        'num_params': num_params,
        'degrees_of_freedom': dof,
        'is_overidentified': dof > 0,
        'is_exactly_identified': dof == 0,
        'is_underidentified': dof < 0
    }


def diagnose_weak_identification(jacobian, threshold_condition=1e6):
    """
    Diagnose potential weak identification issues.

    Parameters:
    -----------
    jacobian : ndarray
        Jacobian matrix
    threshold_condition : float
        Threshold for condition number to flag weak identification

    Returns:
    --------
    diagnosis : dict
        - has_weak_identification : bool
        - problematic_params : list of int
            Indices of parameters that may be weakly identified
        - recommendations : list of str
    """
    m, p = jacobian.shape

    # Compute column norms (sensitivity of moments to each parameter)
    column_norms = np.linalg.norm(jacobian, axis=0)

    # Identify parameters with small column norms
    mean_norm = np.mean(column_norms)
    std_norm = np.std(column_norms)
    weak_threshold = mean_norm - 2 * std_norm

    problematic_params = np.where(column_norms < weak_threshold)[0].tolist()

    # Check condition number
    U, s, Vt = np.linalg.svd(jacobian, full_matrices=False)
    condition_number = s[0] / s[-1] if len(s) > 0 and s[-1] > 0 else np.inf

    has_weak_id = (condition_number > threshold_condition) or (len(problematic_params) > 0)

    recommendations = []
    if condition_number > threshold_condition:
        recommendations.append(
            f"⚠️  High condition number ({condition_number:.2e}) indicates potential "
            "numerical instability. Consider parameter transformations or adding more informative moments."
        )

    if len(problematic_params) > 0:
        recommendations.append(
            f"⚠️  Parameters {problematic_params} show weak sensitivity to moment conditions. "
            "Consider adding moments specifically targeted at these parameters."
        )

    if not has_weak_id:
        recommendations.append("✅ No obvious weak identification issues detected.")

    return {
        'has_weak_identification': has_weak_id,
        'condition_number': condition_number,
        'problematic_params': problematic_params,
        'column_norms': column_norms,
        'recommendations': recommendations
    }


def check_identification(params, moment_func, epsilon=1e-7,
                        condition_threshold=1e6, verbose=True):
    """
    Comprehensive identification check for GMM estimation.

    Parameters:
    -----------
    params : array-like
        Parameter vector
    moment_func : callable
        Function computing moment conditions: moment_func(params) -> array
    epsilon : float
        Step size for numerical Jacobian
    condition_threshold : float
        Threshold for condition number warning
    verbose : bool
        If True, print diagnostic report

    Returns:
    --------
    report : dict
        Complete identification diagnostic report
    """
    params = np.asarray(params)
    p = len(params)

    # Compute moments
    g = moment_func(params)
    m = len(g)

    # Order condition
    order = check_order_condition(m, p)

    # Compute Jacobian
    try:
        jac = compute_jacobian(params, moment_func, epsilon)
    except Exception as e:
        return {
            'error': f"Failed to compute Jacobian: {str(e)}",
            'order_condition': order
        }

    # Rank condition
    rank = check_rank_condition(jac)

    # Weak identification diagnosis
    weak = diagnose_weak_identification(jac, condition_threshold)

    # Overall assessment
    is_identified = order['is_satisfied'] and rank['is_identified']

    report = {
        'is_identified': is_identified,
        'order_condition': order,
        'rank_condition': rank,
        'weak_identification': weak,
        'jacobian': jac
    }

    if verbose:
        print_identification_report(report)

    return report


def print_identification_report(report):
    """Print human-readable identification diagnostic report."""

    print("\n" + "="*70)
    print("GMM PARAMETER IDENTIFICATION DIAGNOSTIC REPORT")
    print("="*70)

    if 'error' in report:
        print(f"\n❌ ERROR: {report['error']}")
        return

    # Order condition
    print("\n1. ORDER CONDITION (Necessary)")
    print("-" * 70)
    order = report['order_condition']
    print(f"   Number of moments (m):     {order['num_moments']}")
    print(f"   Number of parameters (p):  {order['num_params']}")
    print(f"   Degrees of freedom (m-p):  {order['degrees_of_freedom']}")

    if order['is_satisfied']:
        print(f"   Status: ✅ SATISFIED (m >= p)")
        if order['is_overidentified']:
            print(f"   Note: Model is OVERIDENTIFIED (can perform J-test)")
        elif order['is_exactly_identified']:
            print(f"   Note: Model is EXACTLY IDENTIFIED (no J-test)")
    else:
        print(f"   Status: ❌ VIOLATED (m < p) - Model is UNDERIDENTIFIED")

    # Rank condition
    print("\n2. RANK CONDITION (Necessary & Sufficient)")
    print("-" * 70)
    rank_cond = report['rank_condition']
    print(f"   Rank of Jacobian:          {rank_cond['rank']}")
    print(f"   Required rank:             {rank_cond['num_params']}")
    print(f"   Condition number:          {rank_cond['condition_number']:.2e}")
    print(f"   Min singular value:        {rank_cond['min_singular_value']:.2e}")
    print(f"   Max singular value:        {rank_cond['max_singular_value']:.2e}")

    if rank_cond['is_identified']:
        print(f"   Status: ✅ SATISFIED (rank = p)")
    else:
        print(f"   Status: ❌ VIOLATED (rank < p)")
        print(f"   ⚠️  WARNING: Parameters are NOT IDENTIFIED")

    # Weak identification
    print("\n3. WEAK IDENTIFICATION DIAGNOSIS")
    print("-" * 70)
    weak = report['weak_identification']

    for rec in weak['recommendations']:
        print(f"   {rec}")

    if weak['problematic_params']:
        print(f"\n   Problematic parameter indices: {weak['problematic_params']}")
        print(f"   Column norms: {weak['column_norms']}")

    # Overall conclusion
    print("\n" + "="*70)
    print("OVERALL IDENTIFICATION STATUS:")
    if report['is_identified'] and not weak['has_weak_identification']:
        print("✅ PARAMETERS ARE WELL-IDENTIFIED")
    elif report['is_identified'] and weak['has_weak_identification']:
        print("⚠️  PARAMETERS ARE IDENTIFIED BUT WEAKLY")
        print("    Consider adding more informative moments or parameter transformations")
    else:
        print("❌ PARAMETERS ARE NOT IDENTIFIED")
        print("    Model cannot be estimated without modifications")
    print("="*70 + "\n")


def example_usage():
    """Example usage with Hawkes jump-diffusion model."""

    # Example: Simple Hawkes model with 3 parameters
    # θ = (α, β, λ∞)

    def hawkes_moments(theta, data_moments=None):
        """
        Compute theoretical moments for univariate Hawkes model.

        Returns difference between sample and theoretical moments.
        """
        alpha, beta, lambda_inf = theta

        # Stationarity constraint
        if alpha <= beta or alpha <= 0:
            return np.array([1e10, 1e10, 1e10, 1e10, 1e10])

        # Theoretical moments (simplified)
        lambda_avg = alpha * lambda_inf / (alpha - beta)

        # Sample moments (placeholder - in real use, compute from data)
        if data_moments is None:
            data_moments = np.array([0.05, 0.01, 0.005, 0.002, 0.001])

        theoretical = np.array([
            lambda_avg,  # Mean jump intensity
            lambda_avg * (1 + beta / (alpha - beta)),  # Variance
            beta / (alpha - beta),  # Autocorrelation lag 1
            beta**2 / (alpha - beta)**2,  # Autocorrelation lag 2
            beta**3 / (alpha - beta)**3   # Autocorrelation lag 3
        ])

        return data_moments - theoretical

    # Test parameters
    theta_test = np.array([20.0, 10.0, 0.3])

    # Run identification check
    report = check_identification(theta_test, hawkes_moments, verbose=True)

    return report


if __name__ == '__main__':
    print("Running example identification check for Hawkes model...")
    example_usage()
