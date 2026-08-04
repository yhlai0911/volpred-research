"""
K1730 scoring — interval-forecast evaluation.

Coverage tests follow Christoffersen (1998) "Evaluating Interval Forecasts",
which is the paper that defines this exact problem: given a sequence of interval
forecasts, test whether the hit sequence is (a) correctly sized and (b) serially
independent. Kupiec (1995) is the unconditional-coverage half.

The Diebold-Mariano comparison deliberately calls the repo's canonical
``volpred.stats.model_evaluation.dm_test`` rather than a local reimplementation.
The repo froze that decision after K1655: a local DM using ``lag = h-1``
degenerates to *no HAC correction at all* at h=1, which inflated |t| enough to
move 26 of 60 cells across the significance line. There is a CI ratchet
(``scripts/tests/test_dm_hac_lag_ratchet.py``) that fails any new local DM using
that pattern, so the canonical function is both the correct and the required
choice here.
"""
from __future__ import annotations

import numpy as np
from scipy import stats

from volpred.stats.model_evaluation import dm_test as canonical_dm_test


# --------------------------------------------------------------------------
# Coverage tests
# --------------------------------------------------------------------------

def kupiec_uc(hits: np.ndarray, expected_rate: float) -> dict:
    """Kupiec (1995) unconditional-coverage LR test. ``hits`` is 0/1."""
    hits = np.asarray(hits, dtype=float)
    n = len(hits)
    x = float(hits.sum())
    if n == 0:
        return {"lr": np.nan, "p_value": np.nan, "n": 0,
                "observed_rate": np.nan, "expected_rate": expected_rate}
    pi_hat = x / n
    p = expected_rate

    def _ll(prob):
        if prob <= 0 or prob >= 1:
            # Degenerate case: no violations at all, or all violations.
            return (x * np.log(max(prob, 1e-300))
                    + (n - x) * np.log(max(1 - prob, 1e-300)))
        return x * np.log(prob) + (n - x) * np.log(1 - prob)

    lr = -2.0 * (_ll(p) - _ll(pi_hat))
    lr = float(max(lr, 0.0))
    return {"lr": lr, "p_value": float(1 - stats.chi2.cdf(lr, df=1)),
            "n": int(n), "n_violations": int(x),
            "observed_rate": float(pi_hat), "expected_rate": float(p)}


def christoffersen_independence(hits: np.ndarray) -> dict:
    """Christoffersen (1998) independence LR test against a first-order Markov
    alternative — catches violations that cluster in time even when the total
    count is right."""
    h = np.asarray(hits, dtype=int)
    if len(h) < 2:
        return {"lr": np.nan, "p_value": np.nan}
    prev, cur = h[:-1], h[1:]
    n00 = int(np.sum((prev == 0) & (cur == 0)))
    n01 = int(np.sum((prev == 0) & (cur == 1)))
    n10 = int(np.sum((prev == 1) & (cur == 0)))
    n11 = int(np.sum((prev == 1) & (cur == 1)))

    pi01 = n01 / (n00 + n01) if (n00 + n01) > 0 else 0.0
    pi11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0.0
    pi = (n01 + n11) / max(n00 + n01 + n10 + n11, 1)

    def _lg(x, p):
        return x * np.log(p) if x > 0 and p > 0 else 0.0

    ll_null = _lg(n00 + n10, 1 - pi) + _lg(n01 + n11, pi)
    ll_alt = (_lg(n00, 1 - pi01) + _lg(n01, pi01)
              + _lg(n10, 1 - pi11) + _lg(n11, pi11))
    lr = float(max(-2.0 * (ll_null - ll_alt), 0.0))
    return {"lr": lr, "p_value": float(1 - stats.chi2.cdf(lr, df=1)),
            "n00": n00, "n01": n01, "n10": n10, "n11": n11,
            "pi01": float(pi01), "pi11": float(pi11)}


def christoffersen_cc(hits: np.ndarray, expected_rate: float) -> dict:
    """Joint conditional-coverage test: LR_cc = LR_uc + LR_ind ~ chi2(2)."""
    uc = kupiec_uc(hits, expected_rate)
    ind = christoffersen_independence(hits)
    if not np.isfinite(uc["lr"]) or not np.isfinite(ind["lr"]):
        return {"lr": np.nan, "p_value": np.nan, "uc": uc, "independence": ind}
    lr = float(uc["lr"] + ind["lr"])
    return {"lr": lr, "p_value": float(1 - stats.chi2.cdf(lr, df=2)),
            "uc": uc, "independence": ind}


def interval_coverage_report(y: np.ndarray, lower: np.ndarray, upper: np.ndarray,
                             nominal: float) -> dict:
    """Full coverage report for a two-sided interval at ``nominal`` coverage."""
    y = np.asarray(y, dtype=float)
    inside = (y >= lower) & (y <= upper)
    outside = (~inside).astype(int)
    expected_outside = 1.0 - nominal
    cc = christoffersen_cc(outside, expected_outside)
    return {
        "nominal_coverage": float(nominal),
        "empirical_coverage": float(inside.mean()),
        "n": int(len(y)),
        "n_outside": int(outside.sum()),
        "below_lower": int(np.sum(y < lower)),
        "above_upper": int(np.sum(y > upper)),
        "kupiec_uc": cc["uc"],
        "christoffersen_ind": cc["independence"],
        "christoffersen_cc": {"lr": cc["lr"], "p_value": cc["p_value"]},
        "mean_width": float(np.mean(upper - lower)),
    }


def var_coverage_report(y: np.ndarray, var_level: np.ndarray, p: float) -> dict:
    """One-sided upper-tail (VaR-style) coverage at level ``p``."""
    exceed = (np.asarray(y, dtype=float) > var_level).astype(int)
    cc = christoffersen_cc(exceed, 1.0 - p)
    return {
        "level": float(p),
        "expected_exceedance_rate": float(1.0 - p),
        "empirical_exceedance_rate": float(exceed.mean()),
        "n_exceedances": int(exceed.sum()),
        "kupiec_uc": cc["uc"],
        "christoffersen_ind": cc["independence"],
        "christoffersen_cc": {"lr": cc["lr"], "p_value": cc["p_value"]},
    }


# --------------------------------------------------------------------------
# Loss functions
# --------------------------------------------------------------------------

def pinball_loss(y: np.ndarray, q: np.ndarray, tau: float) -> np.ndarray:
    """Pointwise pinball (quantile / check) loss."""
    d = np.asarray(y, dtype=float) - np.asarray(q, dtype=float)
    return np.where(d >= 0, tau * d, (tau - 1.0) * d)


def mean_pinball_across_taus(y: np.ndarray, q_matrix: np.ndarray,
                             taus: np.ndarray) -> np.ndarray:
    """Pointwise loss averaged over the tau grid → one series per observation.

    Kept pointwise (not pre-averaged over time) because the DM test needs the
    per-observation loss differential, not a scalar.
    """
    out = np.zeros(len(y))
    for k, tau in enumerate(taus):
        out += pinball_loss(y, q_matrix[:, k], float(tau))
    return out / len(taus)


def qrmse(y: np.ndarray, q: np.ndarray) -> float:
    """Root mean squared error of a quantile forecast against realizations.

    Reported because the brief asks for it, with the caveat that RMSE is not a
    consistent scoring rule for a quantile — pinball is. It is a descriptive
    magnitude, not the basis of any ranking claim here.
    """
    d = np.asarray(y, dtype=float) - np.asarray(q, dtype=float)
    return float(np.sqrt(np.mean(d ** 2)))


def es_backtest(y: np.ndarray, var_level: np.ndarray, es_level: np.ndarray,
                seed: int = 42, n_boot: int = 10000) -> dict:
    """McNeil-Frey (2000) exceedance-residual test for expected shortfall.

    Among the observations that breach VaR, the residual ``y - ES`` should
    average zero. The p-value is bootstrapped (seeded) rather than taken from a
    normal approximation, because the number of exceedances is small by
    construction and the residuals are skewed.
    """
    y = np.asarray(y, dtype=float)
    mask = y > var_level
    n_ex = int(mask.sum())
    if n_ex < 5:
        return {"n_exceedances": n_ex, "mean_residual": np.nan,
                "p_value": np.nan, "note": "too few exceedances to test"}

    resid = y[mask] - es_level[mask]
    obs = float(resid.mean())
    centered = resid - obs
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n_ex, size=(n_boot, n_ex))
    boot = centered[idx].mean(axis=1)
    p_two = float(np.mean(np.abs(boot) >= abs(obs)))
    return {
        "n_exceedances": n_ex,
        "mean_residual": obs,
        "mean_realized_exceedance": float(y[mask].mean()),
        "mean_predicted_es": float(es_level[mask].mean()),
        "p_value": p_two,
        "n_boot": n_boot,
        "seed": seed,
    }


# --------------------------------------------------------------------------
# Probability integral transform
# --------------------------------------------------------------------------

def pit_diagnostics(y: np.ndarray, q_matrix: np.ndarray, taus: np.ndarray,
                    n_bins: int = 10) -> dict:
    """Diebold-Gunther-Tay PIT calibration over the whole predictive distribution.

    Coverage tests only interrogate the distribution at the two quantiles that
    bound the interval. The PIT asks the sharper question — is the *entire*
    predictive distribution right? — by mapping each realization to its own
    predicted CDF value. Under correct calibration those values are uniform on
    [0,1], so a departure localizes exactly which part of the distribution is
    wrong rather than merely reporting that something is.

    The predicted CDF is recovered by interpolating the tau grid, so resolution
    is limited by the grid (here 0.005 at the extremes). Values are clipped to
    the grid range, which makes the outermost bins conservative.

    **The chi-square p-value is biased toward rejection and must not be read as
    an exact test.** Linear interpolation across a 13-point tau grid cannot
    reproduce a curved quantile function, and that discretization error lands in
    the histogram. Measured on synthetic *correctly specified* Gaussian
    forecasts with n=4000, this routine returns chi2 p ~ 0.02 — a nominal
    rejection with nothing whatsoever wrong with the model. So a small p here is
    not evidence of miscalibration on its own; what carries information is the
    *shape* of the histogram, i.e. which region of the distribution the mass
    piles up in, and comparisons of that shape across models scored on the
    identical grid. Treat this as a descriptive diagnostic, not a hypothesis
    test, and lean on Kupiec/Christoffersen for the formal coverage claims.
    """
    y = np.asarray(y, dtype=float)
    pit = np.empty(len(y))
    for i in range(len(y)):
        q = q_matrix[i]
        order = np.argsort(q)
        pit[i] = float(np.interp(y[i], q[order], np.asarray(taus)[order]))

    counts, _ = np.histogram(pit, bins=n_bins, range=(0.0, 1.0))
    expected = len(y) / n_bins
    chi2_stat = float(np.sum((counts - expected) ** 2 / expected))
    ks = stats.kstest(pit, "uniform")

    return {
        "n": int(len(y)),
        "mean": float(pit.mean()),          # 0.5 under correct calibration
        "std": float(pit.std()),            # 1/sqrt(12) = 0.2887
        "bin_counts": [int(c) for c in counts],
        "expected_per_bin": float(expected),
        "chi2_stat": chi2_stat,
        "chi2_p_value": float(1 - stats.chi2.cdf(chi2_stat, df=n_bins - 1)),
        "ks_stat": float(ks.statistic),
        "ks_p_value": float(ks.pvalue),
        "frac_below_5pct": float(np.mean(pit < 0.05)),
        "frac_above_95pct": float(np.mean(pit > 0.95)),
        "_pit": pit,
    }


# --------------------------------------------------------------------------
# Diebold-Mariano
# --------------------------------------------------------------------------

def dm_with_diagnostics(loss_model: np.ndarray, loss_bench: np.ndarray,
                        h: int = 1) -> dict:
    """Canonical DM test plus the autocorrelation evidence behind the HAC lag.

    The repo's rule is ``lag = max(h-1, ceil(h^(1/3) n^(1/3)))`` and requires the
    loss differential's autocorrelation to be *measured and reported*, not
    assumed away — omitting HAC is a two-way error, so "it was null anyway" is
    not a reason to skip it. Lag sensitivity is reported alongside.
    """
    l1 = np.asarray(loss_model, dtype=float)
    l2 = np.asarray(loss_bench, dtype=float)
    valid = np.isfinite(l1) & np.isfinite(l2)
    l1, l2 = l1[valid], l2[valid]
    d = l1 - l2
    n = len(d)
    if n < 10:
        return {"t_stat": np.nan, "p_value": np.nan, "n": n}

    t_stat, p_value = canonical_dm_test(l1, l2, h=h)

    dc = d - d.mean()
    var0 = float(np.mean(dc ** 2))
    acf = [float(np.mean(dc[l:] * dc[:-l]) / var0) if var0 > 0 else 0.0
           for l in range(1, 6)]

    # Sensitivity: recompute the HAC t at a range of bandwidths.
    sens = {}
    for lag in (0, 1, 5, 10, 20):
        v = var0
        for l in range(1, lag + 1):
            w = 1.0 - l / (lag + 1.0)
            v += 2.0 * w * float(np.mean(dc[l:] * dc[:-l]))
        se = np.sqrt(max(v, 1e-300) / n)
        sens[f"lag_{lag}"] = float(d.mean() / se) if se > 0 else np.nan

    return {
        "t_stat": float(t_stat),
        "p_value": float(p_value),
        "n": int(n),
        "mean_loss_differential": float(d.mean()),
        "favours": "model" if d.mean() < 0 else "benchmark",
        "canonical_hac_lag": int(max(1, min(int(np.ceil(h ** (1 / 3) * n ** (1 / 3))), n // 4))),
        "loss_diff_acf_1_to_5": acf,
        "t_stat_by_hac_lag": sens,
        "harvey_significant": bool(abs(t_stat) > 3.0),
    }
