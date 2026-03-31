"""
Model Confidence Set (MCS) — Hansen, Lunde & Nason (2011), Econometrica.

Correct implementation addressing three common pitfalls:
  1. Uses STATIONARY bootstrap (Politis & Romano 1994) for time-series dependence,
     not iid resampling.
  2. Bootstrap test statistic is properly constructed: the resampled statistic
     is computed from block-resampled loss differentials CENTERED at zero
     (H0: equal predictive ability), while the observed statistic uses the
     raw sample means.  This avoids the degenerate-statistic bug where
     centering each draw makes the mean identically zero.
  3. Elimination uses the standardised T_R statistic (worst model by
     t-stat, not by raw average loss).

Reference
---------
Hansen, P. R., Lunde, A., & Nason, J. M. (2011). The Model Confidence Set.
Econometrica, 79(2), 453-497.

Politis, D. N. & Romano, J. P. (1994). The Stationary Bootstrap.
Journal of the American Statistical Association, 89(428), 1303-1313.

Politis, D. N. & White, H. (2004). Automatic Block-Length Selection for
the Dependent Bootstrap. Econometric Reviews, 23(1), 53-70.
"""

from __future__ import annotations

import numpy as np
from typing import Dict, List, Optional, Tuple


# ------------------------------------------------------------------ #
# Stationary bootstrap (Politis & Romano 1994)
# ------------------------------------------------------------------ #

def _auto_block_length(x: np.ndarray) -> float:
    """Heuristic block length ~ 1.75 * T^(1/3) for stationary bootstrap.

    A simplified rule that works well in practice.  For a more rigorous
    approach see Politis & White (2004) with the Patton-Politis-White
    correction, but the T^(1/3) rule is standard in MCS applications.

    Parameters
    ----------
    x : 1-d array (used only for its length)

    Returns
    -------
    Expected geometric block length (>= 2).
    """
    T = len(x)
    bl = max(2.0, 1.75 * T ** (1 / 3))
    return bl


def _stationary_bootstrap_indices(T: int, block_length: float,
                                  rng: np.random.Generator) -> np.ndarray:
    """Draw one stationary-bootstrap resample index vector of length T.

    At each position we either continue the current block (with
    probability 1 - 1/block_length) or jump to a new uniformly random
    start (with probability 1/block_length).

    Parameters
    ----------
    T : sample size
    block_length : expected geometric block length (> 1)
    rng : numpy Generator

    Returns
    -------
    idx : int array of shape (T,)
    """
    p = 1.0 / block_length          # probability of starting a new block
    idx = np.empty(T, dtype=np.intp)
    idx[0] = rng.integers(0, T)
    u = rng.random(T)               # pre-draw all uniform(0,1)
    for t in range(1, T):
        if u[t] < p:
            idx[t] = rng.integers(0, T)   # new block start
        else:
            idx[t] = (idx[t - 1] + 1) % T  # continue (wrap around)
    return idx


# ------------------------------------------------------------------ #
# Core MCS
# ------------------------------------------------------------------ #

def model_confidence_set(
    losses: Dict[str, np.ndarray],
    alpha: float = 0.10,
    n_boot: int = 5000,
    block_size: Optional[float] = None,
    seed: int = 42,
) -> Dict:
    """Hansen, Lunde & Nason (2011) Model Confidence Set (T_R variant).

    Iteratively eliminates the model with the largest standardised
    relative loss until the equal-predictive-ability null cannot be
    rejected for the surviving set.

    Parameters
    ----------
    losses : dict  {model_name: 1-d array of pointwise losses}
        All arrays must have the same length T.
    alpha : float
        Significance level for elimination (default 0.10).
    n_boot : int
        Number of stationary-bootstrap replications (default 5000).
    block_size : float or None
        Expected geometric block length for the stationary bootstrap.
        If None, auto-selected via ~ 1.75 * T^(1/3).
    seed : int
        Random seed for reproducibility.

    Returns
    -------
    dict with keys:
        'mcs_models'  : list[str] — models surviving in the MCS
        'eliminated'  : list[tuple(str, float)] — (model, p_value) in
                        elimination order (first eliminated = worst)
        'p_values'    : dict[str, float] — MCS p-value for every model
                        (surviving models get p >= alpha)
    """
    # ---- input validation ------------------------------------------------
    models = list(losses.keys())
    if len(models) < 2:
        return {
            "mcs_models": models,
            "eliminated": [],
            "p_values": {models[0]: 1.0} if models else {},
        }

    T = len(losses[models[0]])
    for m in models:
        if len(losses[m]) != T:
            raise ValueError(
                f"Loss arrays must all have length {T}; "
                f"model '{m}' has length {len(losses[m])}"
            )

    loss_mat = np.column_stack([np.asarray(losses[m], dtype=np.float64)
                                for m in models])

    if block_size is None:
        block_size = _auto_block_length(loss_mat[:, 0])

    rng = np.random.default_rng(seed)

    # ---- iterative elimination -------------------------------------------
    remaining = list(range(len(models)))   # indices into `models`
    eliminated: List[Tuple[str, float]] = []
    p_values: Dict[str, float] = {}

    # Track the maximum p-value seen so far (for MCS p-value monotonicity)
    max_p_so_far = 0.0

    while len(remaining) > 1:
        M = len(remaining)
        sub = loss_mat[:, remaining]  # (T, M)

        # -- observed T_R statistic ----------------------------------------
        #
        # d_i. = (1/M) sum_j (L_i - L_j) = L_i - L_bar  for each model i
        # where L_bar = mean across the M models at each t.
        #
        # d_i_bar = mean_t(d_i.) ,  var_i = HAC-var(d_i.)
        # t_i = d_i_bar / sqrt(var_i / T)
        # T_R = max_i t_i     (eliminate model with largest positive t_i)
        #
        d_it = sub - sub.mean(axis=1, keepdims=True)  # (T, M) deviations
        d_bar = d_it.mean(axis=0)                      # (M,) mean over time

        se = np.zeros(M)
        for k in range(M):
            se[k] = _hac_se(d_it[:, k], T)

        # Avoid zero-division
        with np.errstate(divide="ignore", invalid="ignore"):
            t_stats = np.where(se > 1e-15, d_bar / se, 0.0)

        t_R_obs = np.max(t_stats)

        # -- bootstrap distribution of T_R under H0 -----------------------
        #
        # Per HLN (2011, Section 3.1):
        #   1. Resample d_it using stationary bootstrap → d_it*
        #   2. Center at zero (impose H0): d_it_c* = d_it* - d_bar
        #      This shifts the resampled differentials so their expected
        #      mean is zero under H0, but the bootstrap *sample* mean
        #      is generally non-zero — that non-zero value IS the
        #      bootstrap test statistic.
        #   3. Compute T_R* from d_it_c*
        #
        # CRITICAL: Do NOT subtract the bootstrap sample mean from d_it_c*
        # (that would make the mean identically zero → degenerate statistic).
        #
        boot_t_R = np.empty(n_boot)

        for b in range(n_boot):
            idx = _stationary_bootstrap_indices(T, block_size, rng)
            # Resample the loss differentials (not raw losses)
            boot_d = d_it[idx, :]                               # (T, M)
            # Center at original sample mean → impose H0: E[d_i.] = 0
            boot_d_centered = boot_d - d_bar[np.newaxis, :]     # (T, M)
            # Bootstrap sample mean (non-zero — this is the signal)
            boot_d_bar_c = boot_d_centered.mean(axis=0)         # (M,)

            boot_se = np.zeros(M)
            for k in range(M):
                boot_se[k] = _hac_se(boot_d_centered[:, k], T)

            with np.errstate(divide="ignore", invalid="ignore"):
                boot_t = np.where(boot_se > 1e-15,
                                  boot_d_bar_c / boot_se, 0.0)
            boot_t_R[b] = np.max(boot_t)

        # -- p-value -------------------------------------------------------
        p_val = float(np.mean(boot_t_R >= t_R_obs))
        # MCS p-values must be monotonically non-decreasing
        p_val = max(p_val, max_p_so_far)

        if p_val >= alpha:
            # Cannot reject H0 — all remaining models are in the MCS
            for idx_r in remaining:
                p_values[models[idx_r]] = max(p_val, alpha)
            break

        # Eliminate the model with the largest t_stat (worst standardised)
        worst_local = int(np.argmax(t_stats))
        worst_global = remaining[worst_local]
        eliminated.append((models[worst_global], p_val))
        p_values[models[worst_global]] = p_val
        max_p_so_far = p_val
        remaining.pop(worst_local)

    else:
        # Only one model left — it survives with p = 1
        p_values[models[remaining[0]]] = 1.0

    mcs_models = [models[i] for i in remaining]

    return {
        "mcs_models": mcs_models,
        "eliminated": eliminated,
        "p_values": p_values,
    }


# ------------------------------------------------------------------ #
# HAC standard error (Newey-West, auto bandwidth)
# ------------------------------------------------------------------ #

def _hac_se(x: np.ndarray, T: int) -> float:
    """Newey-West HAC standard error with automatic bandwidth.

    Bandwidth = floor(T^(1/3)) following Andrews (1991) rule of thumb.
    """
    x_dm = x - x.mean()
    bw = max(1, int(T ** (1 / 3)))

    gamma0 = float(np.dot(x_dm, x_dm) / T)
    V = gamma0
    for lag in range(1, bw + 1):
        w = 1.0 - lag / (bw + 1)          # Bartlett kernel
        gamma_lag = float(np.dot(x_dm[lag:], x_dm[:-lag]) / T)
        V += 2 * w * gamma_lag

    V = max(V, 1e-20)  # floor at tiny positive
    return float(np.sqrt(V / T))
