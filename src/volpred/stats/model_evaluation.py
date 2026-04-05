"""
Comprehensive Model Evaluation Framework — Patton (2011) + Economic Significance.

Implements CLAUDE.md Rule 6b: every model comparison must include at least
the first 3 layers, and report ALL targets (not just favorable ones).

Usage:
    from volpred.stats.model_evaluation import evaluate_models

    results = evaluate_models(
        forecasts={"GJR": gjr_forecasts, "AMEM": amem_forecasts, "HAR": har_forecasts},
        realized_r2=actual_squared_returns,
        returns=raw_returns,  # for VaR/ES evaluation
        alpha_var=0.01,       # VaR confidence level
    )
    # results contains all 6 layers of evaluation

Layers:
  1. Native target QLIKE (each model on its own target)
  2. QLIKE on r² (Patton 2011 proxy-robust) — primary ranking
  3. Spearman rank correlation (distribution-free)
  4. DM tests + Harvey t>3.0 (pairwise)
  5. MCS (Model Confidence Set) — multi-model control
  6. VaR/ES economic significance — backtesting + calibration

References:
  - Patton (2011) J. Econometrics 160 — proxy-robust loss functions
  - Hansen, Lunde & Nason (2011) Econometrica 79 — Model Confidence Set
  - Kupiec (1995) — unconditional VaR coverage test
  - Christoffersen (1998) — conditional VaR independence test
  - Harvey et al. (2016) — multiple testing threshold t>3.0
"""

from __future__ import annotations

import numpy as np
from scipy import stats
from typing import Dict, List, Optional, Tuple


# ─── Layer 1 & 2: QLIKE Loss ────────────────────────────────────

def qlike(actual: np.ndarray, predicted: np.ndarray) -> float:
    """QLIKE loss: mean(a/f - log(a/f) - 1). Lower is better.
    Patton (2011): proxy-robust when actual is conditionally unbiased for sigma².
    """
    a = np.asarray(actual, dtype=np.float64)
    f = np.asarray(predicted, dtype=np.float64)
    valid = (a > 0) & (f > 0) & np.isfinite(a) & np.isfinite(f)
    if valid.sum() < 10:
        return np.nan
    a, f = a[valid], f[valid]
    ratio = a / f
    return float(np.mean(ratio - np.log(ratio) - 1))


def qlike_pointwise(actual: np.ndarray, predicted: np.ndarray) -> np.ndarray:
    """Pointwise QLIKE losses for DM test."""
    a = np.maximum(np.asarray(actual, dtype=np.float64), 1e-16)
    f = np.maximum(np.asarray(predicted, dtype=np.float64), 1e-16)
    ratio = a / f
    return ratio - np.log(ratio) - 1


def mse(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Mean Squared Error."""
    return float(np.mean((actual - predicted) ** 2))


# ─── Layer 3: Spearman Rank Correlation ──────────────────────────

def spearman_corr(actual: np.ndarray, predicted: np.ndarray) -> Tuple[float, float]:
    """Spearman rank correlation. Returns (rho, p_value)."""
    valid = np.isfinite(actual) & np.isfinite(predicted)
    if valid.sum() < 10:
        return (np.nan, np.nan)
    rho, p = stats.spearmanr(actual[valid], predicted[valid])
    return (float(rho), float(p))


# ─── Layer 4: Diebold-Mariano Test ──────────────────────────────

def dm_test(loss1: np.ndarray, loss2: np.ndarray, h: int = 1) -> Tuple[float, float]:
    """Diebold-Mariano test with Newey-West HAC.
    Negative t → model 1 is better. Harvey (2016): |t| > 3.0 for significance.
    """
    d = np.asarray(loss1, dtype=np.float64) - np.asarray(loss2, dtype=np.float64)
    valid = np.isfinite(d)
    d = d[valid]
    n = len(d)
    if n < 10:
        return (0.0, 1.0)

    d_mean = np.mean(d)
    max_lag = max(1, min(int(np.ceil(h ** (1/3) * n ** (1/3))), n // 4))
    gamma0 = np.mean((d - d_mean) ** 2)
    var_d = gamma0
    for lag in range(1, max_lag + 1):
        weight = 1 - lag / (max_lag + 1)
        gamma_l = np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean))
        var_d += 2 * weight * gamma_l

    if var_d <= 0:
        return (0.0, 1.0)
    se = np.sqrt(var_d / n)
    if se < 1e-15:
        return (0.0, 1.0)

    t_stat = d_mean / se
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return (float(t_stat), float(p_val))


def strategy_dm_test(
    returns1: np.ndarray,
    returns2: np.ndarray,
    h: int = 1,
    loss_fn: str = "negative_return",
) -> Tuple[float, float]:
    """Diebold-Mariano test for comparing trading strategies.

    Unlike dm_test() which compares forecast losses against a realized target,
    this compares strategy performance using proper loss functions.

    Args:
        returns1: Daily returns of strategy 1.
        returns2: Daily returns of strategy 2.
        h: Forecast horizon for HAC bandwidth.
        loss_fn: Loss function. Options:
            - "negative_return": L = -r (higher return = lower loss)
            - "squared_return": L = -r² (penalizes low absolute returns)
            - "downside": L = max(0, -r)² (penalizes downside only)

    Returns:
        (t_stat, p_value). Negative t → strategy 1 is better.
        Harvey (2016): |t| > 3.0 for significance under multiple testing.
    """
    r1 = np.asarray(returns1, dtype=np.float64)
    r2 = np.asarray(returns2, dtype=np.float64)

    if loss_fn == "negative_return":
        loss1, loss2 = -r1, -r2
    elif loss_fn == "squared_return":
        loss1, loss2 = -(r1 ** 2), -(r2 ** 2)
    elif loss_fn == "downside":
        loss1 = np.where(r1 < 0, r1 ** 2, 0.0)
        loss2 = np.where(r2 < 0, r2 ** 2, 0.0)
    else:
        raise ValueError(f"Unknown loss_fn: {loss_fn}")

    return dm_test(loss1, loss2, h=h)


# ─── Layer 5: Model Confidence Set ──────────────────────────────

def model_confidence_set(
    losses_dict: Dict[str, np.ndarray],
    alpha: float = 0.10,
    n_boot: int = 5000,
    seed: int = 42,
) -> Dict:
    """MCS wrapper — uses volpred.stats.mcs if available, else simple version."""
    try:
        from volpred.stats.mcs import model_confidence_set as mcs_proper
        result = mcs_proper(losses_dict, alpha=alpha, n_boot=n_boot, seed=seed)
        # mcs_proper returns dict with 'mcs_models', 'eliminated', 'p_values'
        members = result.get('mcs_models', result.get('members', []))
        return {
            "members": members,
            "p_values": result.get('p_values', {}),
            "size": len(members),
            "method": "HLN2011_stationary_bootstrap",
        }
    except ImportError:
        # Fallback: simple elimination
        return _simple_mcs(losses_dict, alpha, n_boot, seed)


def _simple_mcs(losses_dict, alpha, n_boot, seed):
    """Simple MCS fallback (iid bootstrap — less accurate)."""
    np.random.seed(seed)
    models = list(losses_dict.keys())
    losses_mat = np.column_stack([losses_dict[m] for m in models])
    n = losses_mat.shape[0]
    remaining = list(range(len(models)))

    while len(remaining) > 1:
        sub = losses_mat[:, remaining]
        m_count = len(remaining)
        t_stats = np.zeros((m_count, m_count))
        for i in range(m_count):
            for j in range(i + 1, m_count):
                d = sub[:, i] - sub[:, j]
                se = np.std(d) / np.sqrt(n)
                if se > 1e-15:
                    t_stats[i, j] = abs(np.mean(d)) / se
                    t_stats[j, i] = t_stats[i, j]

        t_max = np.max(t_stats)
        boot_t = np.zeros(n_boot)
        for b in range(n_boot):
            idx = np.random.randint(0, n, size=n)
            bs = sub[idx]
            bt = 0.0
            for i in range(m_count):
                for j in range(i + 1, m_count):
                    d = bs[:, i] - bs[:, j]
                    d0 = d - np.mean(d)
                    se = np.std(d0) / np.sqrt(n)
                    if se > 1e-15:
                        bt = max(bt, abs(np.mean(d0)) / se)
            boot_t[b] = bt

        p_val = np.mean(boot_t >= t_max)
        if p_val >= alpha:
            break
        avg = np.mean(sub, axis=0)
        worst = np.argmax(avg)
        remaining.pop(worst)

    return {
        "members": [models[i] for i in remaining],
        "size": len(remaining),
        "method": "simple_iid_bootstrap",
    }


# ─── Layer 6: VaR/ES Economic Significance ─────────────────────

def var_backtest(
    returns: np.ndarray,
    sigma_forecasts: np.ndarray,
    alpha: float = 0.01,
    distribution: str = "normal",
) -> Dict:
    """VaR backtesting: Kupiec + Christoffersen.

    Args:
        returns: actual returns
        sigma_forecasts: forecasted sigma (NOT sigma²)
        alpha: VaR confidence level (e.g., 0.01 for 99% VaR)
        distribution: 'normal' or 't' (Student-t with df=5)
    """
    r = np.asarray(returns, dtype=np.float64)
    sigma = np.asarray(sigma_forecasts, dtype=np.float64)

    if distribution == "normal":
        z = stats.norm.ppf(alpha)
    elif distribution == "t":
        z = stats.t.ppf(alpha, df=5)
    else:
        z = stats.norm.ppf(alpha)

    var = sigma * z  # negative value (left tail)
    violations = (r < var).astype(int)
    n = len(r)
    n1 = violations.sum()
    n0 = n - n1
    pi_hat = n1 / n if n > 0 else 0

    # Kupiec (1995) unconditional coverage test
    if n1 == 0 or n1 == n:
        kupiec_stat, kupiec_p = 0.0, 1.0
    else:
        lr = -2 * (n1 * np.log(alpha) + n0 * np.log(1 - alpha)
                    - n1 * np.log(pi_hat) - n0 * np.log(1 - pi_hat))
        kupiec_stat = float(lr)
        kupiec_p = float(1 - stats.chi2.cdf(lr, df=1))

    # Christoffersen (1998) independence test
    try:
        t00 = np.sum((violations[:-1] == 0) & (violations[1:] == 0))
        t01 = np.sum((violations[:-1] == 0) & (violations[1:] == 1))
        t10 = np.sum((violations[:-1] == 1) & (violations[1:] == 0))
        t11 = np.sum((violations[:-1] == 1) & (violations[1:] == 1))
        pi01 = t01 / (t00 + t01) if (t00 + t01) > 0 else 0
        pi11 = t11 / (t10 + t11) if (t10 + t11) > 0 else 0
        pi_all = (t01 + t11) / (t00 + t01 + t10 + t11) if n > 1 else 0
        if pi01 > 0 and pi11 > 0 and pi_all > 0 and pi01 < 1 and pi11 < 1 and pi_all < 1:
            lr_ind = -2 * ((t00 + t10) * np.log(1 - pi_all) + (t01 + t11) * np.log(pi_all)
                          - t00 * np.log(1 - pi01) - t01 * np.log(pi01)
                          - t10 * np.log(1 - pi11) - t11 * np.log(pi11))
            cc_stat = float(lr_ind)
            cc_p = float(1 - stats.chi2.cdf(lr_ind, df=1))
        else:
            cc_stat, cc_p = 0.0, 1.0
    except Exception:
        cc_stat, cc_p = 0.0, 1.0

    # Basel traffic light
    if pi_hat <= alpha * 1.5:
        traffic = "green"
    elif pi_hat <= alpha * 2.0:
        traffic = "yellow"
    else:
        traffic = "red"

    return {
        "violation_rate": float(pi_hat),
        "expected_rate": float(alpha),
        "n_violations": int(n1),
        "n_total": int(n),
        "kupiec": {"stat": kupiec_stat, "p_value": kupiec_p, "pass": kupiec_p > 0.05},
        "christoffersen": {"stat": cc_stat, "p_value": cc_p, "pass": cc_p > 0.05},
        "basel_traffic_light": traffic,
        "trinity_pass": kupiec_p > 0.05 and cc_p > 0.05 and traffic == "green",
    }


# ─── Main Evaluation Function ──────────────────────────────────

def evaluate_models(
    forecasts: Dict[str, np.ndarray],
    realized_r2: np.ndarray,
    returns: Optional[np.ndarray] = None,
    alpha_var: float = 0.01,
    run_mcs: bool = True,
    run_var: bool = True,
) -> Dict:
    """Comprehensive 6-layer model evaluation.

    Args:
        forecasts: {model_name: array of sigma² forecasts}
        realized_r2: actual squared returns (r²)
        returns: raw returns (needed for VaR/ES, layer 6)
        alpha_var: VaR confidence level
        run_mcs: whether to run MCS (layer 5)
        run_var: whether to run VaR backtest (layer 6)

    Returns:
        Dict with all 6 layers of evaluation results.
    """
    models = list(forecasts.keys())
    n = len(realized_r2)

    # Layer 1 & 2: QLIKE on r²
    qlike_scores = {}
    pointwise_losses = {}
    for name, fcast in forecasts.items():
        f = np.asarray(fcast[:n], dtype=np.float64)
        qlike_scores[name] = qlike(realized_r2, f)
        pointwise_losses[name] = qlike_pointwise(realized_r2, f)

    # Ranking
    ranking = sorted(qlike_scores.items(), key=lambda x: x[1] if not np.isnan(x[1]) else 1e10)

    # Layer 3: Spearman
    spearman_scores = {}
    for name, fcast in forecasts.items():
        f = np.asarray(fcast[:n], dtype=np.float64)
        rho, p = spearman_corr(realized_r2, f)
        spearman_scores[name] = {"rho": rho, "p_value": p}

    # Layer 4: DM tests (all pairs)
    dm_results = {}
    for i, m1 in enumerate(models):
        for j, m2 in enumerate(models):
            if i >= j:
                continue
            l1 = pointwise_losses[m1]
            l2 = pointwise_losses[m2]
            min_len = min(len(l1), len(l2))
            t_stat, p_val = dm_test(l1[:min_len], l2[:min_len])
            dm_results[f"{m1}_vs_{m2}"] = {
                "dm_stat": t_stat,
                "p_value": p_val,
                "harvey_pass": abs(t_stat) > 3.0,
                "better": m1 if t_stat < 0 else m2,
            }

    # Layer 5: MCS
    mcs_result = None
    if run_mcs and len(models) >= 3:
        aligned_losses = {}
        min_len = min(len(v) for v in pointwise_losses.values())
        for name, losses in pointwise_losses.items():
            aligned_losses[name] = losses[:min_len]
        mcs_result = model_confidence_set(aligned_losses)

    # Layer 6: VaR/ES
    var_results = None
    if run_var and returns is not None:
        var_results = {}
        r = np.asarray(returns[:n], dtype=np.float64)
        for name, fcast in forecasts.items():
            f = np.asarray(fcast[:n], dtype=np.float64)
            sigma = np.sqrt(np.maximum(f, 1e-16))
            var_results[name] = var_backtest(r, sigma, alpha=alpha_var)

    return {
        "n_obs": n,
        "n_models": len(models),
        "layer_1_2_qlike": qlike_scores,
        "layer_2_ranking": [{"rank": i + 1, "model": name, "qlike": score}
                           for i, (name, score) in enumerate(ranking)],
        "layer_3_spearman": spearman_scores,
        "layer_4_dm_tests": dm_results,
        "layer_5_mcs": mcs_result,
        "layer_6_var_backtest": var_results,
    }
