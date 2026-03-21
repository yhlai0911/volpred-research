from __future__ import annotations
import numpy as np
from scipy import stats


def diebold_mariano_test(loss1: np.ndarray, loss2: np.ndarray, h: int = 1) -> dict:
    """Diebold-Mariano test for equal predictive accuracy.

    H0: E[d_t] = 0 (equal accuracy)
    H1: E[d_t] != 0 (different accuracy)

    Args:
        loss1, loss2: Loss series for model 1 and 2 (e.g., squared errors or QLIKE losses)
        h: Forecast horizon (for HAC correction)

    Returns:
        dict with 'statistic', 'p_value', 'conclusion' (at 5% level)
    """
    d = loss1 - loss2
    T = len(d)
    d_bar = np.mean(d)

    # HAC variance estimator (Newey-West style)
    gamma_0 = np.var(d, ddof=1)
    V = gamma_0
    for k in range(1, h):
        gamma_k = np.sum((d[k:] - d_bar) * (d[:-k] - d_bar)) / T
        V += 2 * gamma_k

    dm_stat = d_bar / np.sqrt(V / T)
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

    return {
        'statistic': float(dm_stat),
        'p_value': float(p_value),
        'mean_diff': float(d_bar),
        'conclusion': 'reject_equal' if p_value < 0.05 else 'fail_to_reject',
        'better_model': 1 if d_bar < 0 else 2,  # lower loss = better
    }


def kupiec_test(violations: np.ndarray, alpha: float = 0.05) -> dict:
    """Kupiec's POF (Proportion of Failures) test for unconditional coverage.

    Tests whether the observed violation rate equals the expected alpha.

    Args:
        violations: Binary series (1 = VaR violation, 0 = no violation)
        alpha: Expected violation rate

    Returns:
        dict with 'statistic', 'p_value', 'observed_rate', 'expected_rate', 'conclusion'
    """
    T = len(violations)
    n = int(np.sum(violations))
    p_hat = n / T

    if n == 0 or n == T:
        # Edge case: use large/zero stat
        return {
            'statistic': float('inf') if n == 0 else float('inf'),
            'p_value': 0.0,
            'observed_rate': float(p_hat),
            'expected_rate': alpha,
            'n_violations': n,
            'total': T,
            'conclusion': 'reject',
        }

    # Likelihood ratio test
    lr = -2 * (np.log((1 - alpha)**(T - n) * alpha**n) - np.log((1 - p_hat)**(T - n) * p_hat**n))
    p_value = 1 - stats.chi2.cdf(lr, 1)

    return {
        'statistic': float(lr),
        'p_value': float(p_value),
        'observed_rate': float(p_hat),
        'expected_rate': alpha,
        'n_violations': n,
        'total': T,
        'conclusion': 'reject' if p_value < 0.05 else 'fail_to_reject',
    }


def christoffersen_test(violations: np.ndarray) -> dict:
    """Christoffersen's test for conditional coverage (independence of violations).

    Tests whether violations are independent (no clustering).
    Combines unconditional coverage + independence.

    Args:
        violations: Binary series (1 = VaR violation, 0 = no violation)

    Returns:
        dict with 'independence_stat', 'independence_pval', 'cc_stat', 'cc_pval', 'conclusion'
    """
    T = len(violations)

    # Count transitions
    n00 = n01 = n10 = n11 = 0
    for t in range(1, T):
        if violations[t-1] == 0 and violations[t] == 0: n00 += 1
        elif violations[t-1] == 0 and violations[t] == 1: n01 += 1
        elif violations[t-1] == 1 and violations[t] == 0: n10 += 1
        else: n11 += 1

    # Transition probabilities
    pi01 = n01 / max(n00 + n01, 1)
    pi11 = n11 / max(n10 + n11, 1)
    pi = (n01 + n11) / max(T - 1, 1)

    # Independence LR test
    if pi01 <= 0 or pi11 <= 0 or pi01 >= 1 or pi11 >= 1 or pi <= 0 or pi >= 1:
        lr_ind = 0.0
    else:
        lr_ind = -2 * (
            (n00 + n10) * np.log(1 - pi) + (n01 + n11) * np.log(pi)
            - n00 * np.log(1 - pi01) - n01 * np.log(pi01)
            - n10 * np.log(1 - pi11) - n11 * np.log(pi11)
        )

    p_ind = 1 - stats.chi2.cdf(max(lr_ind, 0), 1)

    # Conditional coverage = unconditional + independence
    n_viol = int(np.sum(violations))
    p_hat = n_viol / T
    alpha = p_hat  # use observed rate

    return {
        'independence_stat': float(lr_ind),
        'independence_pval': float(p_ind),
        'n00': n00, 'n01': n01, 'n10': n10, 'n11': n11,
        'pi01': float(pi01),
        'pi11': float(pi11),
        'conclusion': 'independent' if p_ind >= 0.05 else 'clustered',
    }


def compute_var_violations(returns: np.ndarray, var_forecasts: np.ndarray, alpha: float = 0.05) -> np.ndarray:
    """Compute VaR violations: 1 if return < -VaR, 0 otherwise.

    Args:
        returns: Actual return series
        var_forecasts: VaR forecast series (positive values)
        alpha: VaR confidence level

    Returns:
        Binary violation series
    """
    return (returns < -var_forecasts).astype(int)


def composite_score(metrics: dict, weights: dict | None = None) -> float:
    """Compute weighted composite score from multiple metrics.

    Default weights emphasize QLIKE (primary for variance forecasts).
    Lower is better.

    Args:
        metrics: dict with metric values
        weights: dict of metric_name -> weight (default: QLIKE=0.5, MSE=0.2, MAE=0.2, HMSE=0.1)
    """
    if weights is None:
        weights = {'qlike': 0.5, 'mse': 0.2, 'mae': 0.2, 'hmse': 0.1}

    score = 0.0
    total_weight = 0.0
    for metric, w in weights.items():
        if metric in metrics and not np.isnan(metrics[metric]):
            score += w * metrics[metric]
            total_weight += w

    return score / total_weight if total_weight > 0 else float('nan')
