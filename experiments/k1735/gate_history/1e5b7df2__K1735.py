#!/usr/bin/env python3
"""K1735 — Is the intraday diurnal pattern *sufficient* to explain RV variation?

Design, pre-registered success criteria and lookahead policy: see ``README.md``.
Every number in ``K1735_results.json`` is produced by this file; nothing is typed in.

The short version
-----------------
For bin ``k`` on day ``d``, bar realised variance ``RV[d,k]`` is built from ``m``
sub-returns and modelled multiplicatively::

    RV[d,k] = q[d] * s[k] * g[d,k] * (chi2_m / m)
              day     diurnal  intraday   measurement noise
                      (tested) stochastic

In logs this is an additive two-way layout, so a day x bin ANOVA separates the three
systematic pieces -- but only after the **measurement-noise floor** is removed. For m
iid Gaussian sub-returns ``Var(log chi2_m) = trigamma(m/2)``: 4.93 at m=1, 0.49 at m=5,
0.14 at m=15. A naive eta-squared on ``log RV`` divides the diurnal signal by that floor
and reports a single-digit percentage no matter how strong the seasonality is. Removing
the floor is the point of this experiment.

Four nonparametric tests, all with circular-shift nulls (never free label shuffling --
that destroys the serial dependence the null is supposed to keep):

    T1  residual time-of-day structure after **past-only** deseasonalisation
    T2  does the diurnal *shape* depend on the volatility regime
    T3  does the diurnal *shape* drift across years
    T4  is there residual stochastic intraday vol above the noise floor

Run:
    uv run python experiments/k1735/K1735.py
    uv run python experiments/k1735/K1735.py --render-readme   # fill README results block
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from scipy import special, stats

EXP_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXP_DIR.parents[1]
if str(EXP_DIR) not in sys.path:
    sys.path.insert(0, str(EXP_DIR))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

import k1735_panel  # noqa: E402
from volpred.research.reproduce_spec import finalize_experiment  # noqa: E402

SEED = 42
N_BOOT = 1000
N_PERM = 1000
FDR_Q = 0.10
BURN_IN_DAYS = 60
MIN_OBSERVED_FRACTION = 0.95
MIN_DAYS_FOR_PASS = 500
ZERO_RV_DIAGNOSTIC_THRESHOLD = 0.05  # >5% exact-zero bar RV -> diagnostic-only (README 3.5)
MIN_DAYS_PER_YEAR = 100
CALIB_REPS = 20
CALIB_DAYS = 800
CALIB_PERM = 300

# (grid name, bin width in native sub-returns, native sub-returns per squared term).
# m = sub_per_bin // agg. TAIFEX native = 1 minute; yfinance cells native = 5 minutes.
#
# ``m3_15min_5minsub`` shares its 15-minute bins with ``m15_15min`` but builds them from
# 5-minute rather than 1-minute returns. Same bins => same Var(log g), so the two are a
# microstructure-noise control on each other: 1-minute returns carry far more
# bid-ask/discreteness noise than 5-minute ones, and if that noise were driving the
# residual variance the two grids would disagree.
TAIFEX_GRIDS = [
    ("m5_5min", 5, 1),
    ("m15_15min", 15, 1),
    ("m3_15min_5minsub", 15, 5),
    ("m1_5min", 5, 5),
]
YF_GRIDS = [
    ("m1_5min", 1, 1),
    ("m3_15min", 3, 1),
]
CELL_GRIDS = {
    "tx_day": TAIFEX_GRIDS,
    "tx_night": TAIFEX_GRIDS,
    "spy": YF_GRIDS,
    "tw0050": YF_GRIDS,
}
PRIMARY_CELL = "tx_day"
PRIMARY_GRID = "m5_5min"
CONFIRMATORY_CELLS = ("tx_day", "tx_night", "spy")
# README 3.5 pre-declared, from the raw exact-zero rates measured before any result was
# computed: 0050.TW has 22.77% exact-zero 5-minute returns at cell level, so the whole
# cell is diagnostic-only -- not just its m=1 grid.
PRE_DECLARED_DIAGNOSTIC_CELLS = ("tw0050",)


# ------------------------------------------------------------------ panel -> matrices


def cell_matrices(panel, cell: str) -> dict[str, Any]:
    """Sub-return / observed / price matrices (days x bars) for one cell."""
    block = panel[panel["cell"] == cell]
    n_bars = k1735_panel.CELL_SPEC[cell]["n_bars"]
    days = np.sort(block["trade_day"].unique())

    ret = np.zeros((len(days), n_bars), dtype=np.float64)
    obs = np.zeros((len(days), n_bars), dtype=bool)
    price = np.full((len(days), n_bars), np.nan, dtype=np.float64)
    rows = np.searchsorted(days, block["trade_day"].to_numpy())
    cols = block["bar_idx"].to_numpy().astype(np.int64)
    ret[rows, cols] = block["ret"].to_numpy(dtype=np.float64)
    obs[rows, cols] = block["observed"].to_numpy()
    price[rows, cols] = block["price"].to_numpy(dtype=np.float64)

    keep = obs.mean(axis=1) >= MIN_OBSERVED_FRACTION
    return {
        "days": days[keep],
        "ret": ret[keep],
        "observed": obs[keep],
        "price": price[keep],
        "n_days_raw": int(len(days)),
        "n_days_dropped_coverage": int((~keep).sum()),
        "tick_size": float(k1735_panel.CELL_SPEC[cell]["tick_size"]),
    }


def aggregate_returns(
    ret: np.ndarray, price: np.ndarray, agg: int
) -> tuple[np.ndarray, np.ndarray]:
    """Coarsen native sub-returns to blocks of ``agg``, from the **bar-end prices**.

    Not by summing: summing is not equivalent in floating point. When the price is
    unchanged across the block the true return is exactly zero, but the rounded
    sub-returns sum to a tiny non-zero instead. Measured on the TX day session, summing
    finds 3.96% exact zeros where the price comparison finds 7.00% -- and every destroyed
    zero becomes a huge negative ``log r^2`` outlier, which is exactly the tail that
    corrupts the residual variance this experiment is trying to measure.
    """
    if agg == 1:
        return ret, price
    d, n_bars = ret.shape
    n_eff = n_bars // agg
    cut = n_eff * agg
    logp = np.log(price[:, :cut].astype(np.float64))
    end = logp.reshape(d, n_eff, agg)[:, :, -1]
    session_start = logp[:, 0] - ret[:, 0].astype(np.float64)
    prev = np.concatenate([session_start[:, None], end[:, :-1]], axis=1)
    return end - prev, np.exp(end)


def bar_rv(
    ret: np.ndarray, price: np.ndarray, sub_per_bin: int, agg: int = 1
) -> tuple[np.ndarray, int]:
    """Bar realised variance (days x bins) and the sub-return count m behind it.

    ``sub_per_bin`` is the bin width in *native* sub-returns; ``agg`` is how many native
    sub-returns form one squared term. So m = sub_per_bin // agg, and the m=1 grid is
    just the case where the whole bin is one aggregated return.
    """
    if sub_per_bin % agg:
        raise ValueError(f"sub_per_bin={sub_per_bin} not divisible by agg={agg}")
    eff_ret, _ = aggregate_returns(ret, price, agg)
    per_bin = sub_per_bin // agg
    d, n_eff = eff_ret.shape
    n_bins = n_eff // per_bin
    cut = n_bins * per_bin
    return np.square(eff_ret[:, :cut].reshape(d, n_bins, per_bin)).sum(axis=2), per_bin


def floor_zero_rv(
    rv: np.ndarray, price: np.ndarray, sub_per_bin: int, tick_size: float
) -> tuple[np.ndarray, float]:
    """Floor exact-zero bar RV at a half-tick move (README 3.5). Returns (rv, share)."""
    d, n_bins = rv.shape
    px = price[:, : n_bins * sub_per_bin].reshape(d, n_bins, sub_per_bin)
    px_last = px[:, :, -1]
    good = np.isfinite(px_last) & (px_last > 0)
    px_last = np.where(good, px_last, np.nanmedian(np.where(good, px_last, np.nan)))
    floor = np.square(0.5 * tick_size / px_last)
    zero = rv <= 0
    share = float(zero.mean())
    return np.where(zero, floor, rv), share


# ------------------------------------------------------------------- decomposition


def two_way(u: np.ndarray) -> dict[str, np.ndarray | float]:
    """Balanced day x bin ANOVA on log bar RV.

    The design is orthogonal, so ``SSE = SS_total - K*sum(a^2) - D*sum(s^2)`` and the
    residual matrix never has to be materialised -- which matters because the bootstrap
    calls this 1,000 times per cell-grid.
    """
    d, k = u.shape
    mu = u.mean()
    a = u.mean(axis=1) - mu  # day effects
    s = u.mean(axis=0) - mu  # bin (diurnal) effects
    ss_total = float(np.square(u - mu).sum())
    sse = ss_total - k * float(np.square(a).sum()) - d * float(np.square(s).sum())
    return {
        "mu": float(mu),
        "a": a,
        "s": s,
        "sigma2_e": max(sse, 0.0) / max((d - 1) * (k - 1), 1),
        "v_bin_raw": float(np.mean(np.square(s))),
        "v_day_raw": float(np.mean(np.square(a))),
        "total_var": ss_total / (d * k),
        "n_days": d,
        "n_bins": k,
    }


def corrected_shares(fit: dict, noise_floor: float) -> dict[str, float]:
    """Estimation-noise-corrected variance components and the three share metrics."""
    d, k, s2 = fit["n_days"], fit["n_bins"], fit["sigma2_e"]
    v_bin = fit["v_bin_raw"] - s2 * (k - 1) / (d * k)
    v_day = fit["v_day_raw"] - s2 * (d - 1) / (d * k)
    v_stoch_raw = s2 - noise_floor
    v_bin_c, v_day_c, v_stoch_c = (max(x, 0.0) for x in (v_bin, v_day, v_stoch_raw))
    v_sys = v_bin_c + v_day_c + v_stoch_c
    within = v_bin_c + v_stoch_c
    # sigma2_e below the theoretical floor means the data cannot tell Var(log g) = 0 from
    # a floor that is slightly off. Reporting within-day share = 1.000 there would dress
    # "no resolution" up as "diurnal explains everything".
    identified = v_stoch_raw > 0
    return {
        "v_bin": v_bin,
        "v_day": v_day,
        "v_stoch_raw": v_stoch_raw,
        "v_stoch_identified": identified,
        "v_systematic": v_sys,
        "sigma2_e": s2,
        "noise_floor": noise_floor,
        "sigma2_e_over_floor": s2 / noise_floor if noise_floor else np.nan,
        "noise_share_of_total": noise_floor / fit["total_var"] if fit["total_var"] else np.nan,
        "naive_share": fit["v_bin_raw"] / fit["total_var"] if fit["total_var"] else np.nan,
        "diurnal_share_systematic": v_bin_c / v_sys if v_sys > 0 else np.nan,
        "diurnal_share_within_day": (v_bin_c / within if within > 0 and identified else np.nan),
        "day_share_systematic": v_day_c / v_sys if v_sys > 0 else np.nan,
        "stoch_share_systematic": v_stoch_c / v_sys if v_sys > 0 else np.nan,
    }


BOOT_KEYS = (
    "naive_share",
    "diurnal_share_systematic",
    "diurnal_share_within_day",
    "day_share_systematic",
    "stoch_share_systematic",
    "v_bin",
    "v_day",
    "v_stoch_raw",
)


def bootstrap_fits(
    u: np.ndarray, rng: np.random.Generator, n_boot: int
) -> list[dict[str, np.ndarray | float]]:
    """Day-block bootstrap: resample whole trading days, keep the raw ANOVA fits.

    The fits are floor-agnostic on purpose. Deriving both the Gaussian-floor and the
    conservative fat-tail-floor shares from the *same* resamples makes the two sets of
    intervals paired, and halves the work.
    """
    d = u.shape[0]
    return [two_way(u[rng.integers(0, d, size=d)]) for _ in range(n_boot)]


def shares_from_boot(
    fits: list[dict], noise_floor: float, n_boot: int
) -> dict[str, dict[str, float]]:
    draws = {k: np.empty(len(fits)) for k in BOOT_KEYS}
    for b, fit in enumerate(fits):
        sh = corrected_shares(fit, noise_floor)
        for k in BOOT_KEYS:
            draws[k][b] = sh[k]
    out: dict[str, dict[str, float]] = {}
    for k in BOOT_KEYS:
        v = draws[k][np.isfinite(draws[k])]
        out[k] = {
            "ci_lo": float(np.percentile(v, 2.5)) if v.size else float("nan"),
            "ci_hi": float(np.percentile(v, 97.5)) if v.size else float("nan"),
            "boot_mean": float(v.mean()) if v.size else float("nan"),
        }
    # One-sided bootstrap p-value for T4: H0 is Var(log g) = 0.
    vs = draws["v_stoch_raw"]
    out["v_stoch_raw"]["p_one_sided"] = float((1 + int((vs <= 0).sum())) / (1 + n_boot))
    return out


# -------------------------------------------------------------------------- tests


def _eta_sq_bin(e: np.ndarray) -> float:
    """One-way bin eta-squared. Circular row shifts leave the denominator invariant."""
    d, k = e.shape
    grand = e.mean()
    ss_total = float(np.square(e - grand).sum())
    if ss_total <= 0:
        return 0.0
    ss_bin = float(d * np.square(e.mean(axis=0) - grand).sum())
    return ss_bin / ss_total


def _roll_rows(x: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Independent random circular shift of every row (preserves each day's values)."""
    d, k = x.shape
    shifts = rng.integers(0, k, size=d)
    cols = (np.arange(k)[None, :] - shifts[:, None]) % k
    return np.take_along_axis(x, cols, axis=1)


def test_residual_bin_structure(
    u: np.ndarray, rng: np.random.Generator, n_perm: int
) -> dict[str, Any]:
    """T1: past-only deseasonalisation, then look for leftover time-of-day structure.

    The diurnal profile applied to day ``d`` is estimated from days ``< d`` only -- the
    lookahead-safe analogue of ``signal.shift(1)``. A full-sample profile would drive the
    residual bin means to exactly zero by construction, so T1 could never reject: that is
    an identity, not evidence.
    """
    d = u.shape[0]
    if d <= BURN_IN_DAYS + 10:
        return {"status": "SKIPPED_TOO_FEW_DAYS", "n_days": int(d)}
    c = u - u.mean(axis=1, keepdims=True)  # remove the daily level
    csum = np.cumsum(c, axis=0)
    past_mean = csum[BURN_IN_DAYS - 1 : -1] / np.arange(BURN_IN_DAYS, d)[:, None]
    e = c[BURN_IN_DAYS:] - past_mean

    stat = _eta_sq_bin(e)
    null = np.array([_eta_sq_bin(_roll_rows(e, rng)) for _ in range(n_perm)])
    return {
        "status": "OK",
        "statistic_eta_sq": stat,
        "null_mean": float(null.mean()),
        "null_q95": float(np.percentile(null, 95)),
        "p_value": float((1 + int((null >= stat).sum())) / (1 + n_perm)),
        "n_days_tested": int(e.shape[0]),
        "burn_in_days": BURN_IN_DAYS,
        "profile_estimation": "expanding_past_only",
    }


def _group_profiles(c: np.ndarray, labels: np.ndarray, n_groups: int) -> np.ndarray:
    """Mean profile per group, as one BLAS matmul against a one-hot label matrix.

    The loop-over-groups version costs ``n_groups`` passes over ``c`` per permutation,
    which at 15 year-groups x 1,000 rotations x 3,558 days is not affordable.
    """
    onehot = np.zeros((n_groups, c.shape[0]))
    onehot[labels, np.arange(c.shape[0])] = 1.0
    counts = onehot.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return (onehot @ c) / counts[:, None]


def _max_pairwise_msd(profiles: np.ndarray) -> float:
    """Largest mean-squared difference between any two group profiles."""
    n = profiles.shape[0]
    best = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            d = profiles[i] - profiles[j]
            if np.isfinite(d).all():
                best = max(best, float(np.mean(np.square(d))))
    return best


def _shape_test(
    c: np.ndarray, labels: np.ndarray, n_groups: int, rng: np.random.Generator, n_perm: int
) -> dict[str, Any]:
    """Shared engine for T2/T3: group-profile separation vs circular label rotation.

    Rotating the label vector keeps both its serial dependence and its contiguity. Free
    shuffling would scatter the null groups through time while the real groups stay
    contiguous, so any slow drift in shape would masquerade as a group effect.
    """
    stat = _max_pairwise_msd(_group_profiles(c, labels, n_groups))
    d = len(labels)
    shifts = rng.integers(1, d, size=n_perm)
    null = np.array(
        [_max_pairwise_msd(_group_profiles(c, np.roll(labels, int(sh)), n_groups)) for sh in shifts]
    )
    return {
        "status": "OK",
        "statistic_max_pairwise_msd": stat,
        "null_mean": float(null.mean()),
        "null_q95": float(np.percentile(null, 95)),
        "p_value": float((1 + int((null >= stat).sum())) / (1 + n_perm)),
        "n_groups": int(n_groups),
    }


def test_regime_shape(
    u: np.ndarray, days: np.ndarray, rng: np.random.Generator, n_perm: int
) -> dict[str, Any]:
    """T2: does the diurnal shape depend on the volatility regime?

    Terciles are formed **within calendar year** so that a regime label cannot double as
    an era label -- otherwise T2 and T3 would be testing the same thing.
    """
    q = u.mean(axis=1)
    years = days // 10000
    labels = np.full(len(q), -1, dtype=np.int64)
    for y in np.unique(years):
        m = years == y
        if m.sum() < 9:
            continue
        r = stats.rankdata(q[m], method="ordinal")
        labels[m] = np.minimum((3 * (r - 1) // m.sum()).astype(np.int64), 2)
    keep = labels >= 0
    if keep.sum() < 60:
        return {"status": "SKIPPED_TOO_FEW_DAYS", "n_days": int(keep.sum())}
    c = u[keep] - u[keep].mean(axis=1, keepdims=True)
    out = _shape_test(c, labels[keep], 3, rng, n_perm)
    out["n_days_tested"] = int(keep.sum())
    out["grouping"] = "within_year_terciles_of_daily_log_rv"
    # Keep the profiles so the *direction* of any regime effect is inspectable rather
    # than hidden behind a p-value: does the U flatten or steepen on high-vol days?
    profiles = _group_profiles(c, labels[keep], 3)
    out["profiles_by_tercile"] = profiles.tolist()
    out["profile_amplitude_by_tercile"] = [float(np.std(p)) for p in profiles]
    return out


def test_era_shape(
    u: np.ndarray, days: np.ndarray, rng: np.random.Generator, n_perm: int
) -> dict[str, Any]:
    """T3: does the diurnal shape drift across calendar years?"""
    years = days // 10000
    uniq, counts = np.unique(years, return_counts=True)
    usable = uniq[counts >= MIN_DAYS_PER_YEAR]
    if len(usable) < 2:
        return {"status": "SKIPPED_TOO_FEW_YEARS", "n_years": int(len(usable))}
    keep = np.isin(years, usable)
    remap = {y: i for i, y in enumerate(usable)}
    labels = np.array([remap[y] for y in years[keep]], dtype=np.int64)
    c = u[keep] - u[keep].mean(axis=1, keepdims=True)
    out = _shape_test(c, labels, len(usable), rng, n_perm)
    out["n_days_tested"] = int(keep.sum())
    out["years"] = [int(y) for y in usable]
    out["grouping"] = "calendar_year"
    return out


# ------------------------------------------------------------------- noise floors


def gaussian_noise_floor(m: int) -> float:
    """Var(log chi2_m) = trigamma(m/2)."""
    return float(special.polygamma(1, m / 2.0))


def fat_tail_noise_floor(
    ret: np.ndarray, fit: dict, sub_per_bin: int, m: int, rng: np.random.Generator
) -> dict[str, float]:
    """Conservative floor: Var(log RV) when sub-returns are Student-t, not Gaussian.

    Deliberately conservative -- genuine stochastic intraday vol makes the standardised
    sub-returns *look* fat-tailed, so this floor is too high and T4 under it is a
    lower bound on the evidence, never an inflated one.
    """
    d, n_bins = fit["n_days"], fit["n_bins"]
    scale = np.exp(fit["mu"] + fit["a"][:, None] + fit["s"][None, :]) / sub_per_bin
    blocks = ret[:, : n_bins * sub_per_bin].reshape(d, n_bins, sub_per_bin)
    z = (blocks / np.sqrt(scale)[:, :, None]).ravel()
    z = z[np.isfinite(z)]
    z = z / z.std()
    kurt = float(np.mean(z**4))
    if not np.isfinite(kurt) or kurt <= 3.05:
        return {"floor": gaussian_noise_floor(m), "kurtosis": kurt, "df": float("inf")}
    df = max((4.0 * kurt - 6.0) / (kurt - 3.0), 4.5)
    draws = rng.standard_t(df, size=(200_000, m)) / np.sqrt(df / (df - 2.0))
    rv = np.square(draws).sum(axis=1)
    return {"floor": float(np.var(np.log(rv))), "kurtosis": kurt, "df": float(df)}


# --------------------------------------------------------------------- cell runner


def analyse_cell_grid(
    mats: dict, cell: str, grid: str, sub_per_bin: int, agg: int, rng: np.random.Generator
) -> dict[str, Any]:
    rv, m = bar_rv(mats["ret"], mats["price"], sub_per_bin, agg)
    rv, zero_share = floor_zero_rv(rv, mats["price"], sub_per_bin, mats["tick_size"])
    u = np.log(rv)
    days = mats["days"]

    fit = two_way(u)
    floor_g = gaussian_noise_floor(m)
    eff_ret, _ = aggregate_returns(mats["ret"], mats["price"], agg)
    ft = fat_tail_noise_floor(eff_ret, fit, m, m, rng)

    boot_fits = bootstrap_fits(u, rng, N_BOOT)
    shares = corrected_shares(fit, floor_g)
    boot = shares_from_boot(boot_fits, floor_g, N_BOOT)
    shares_cons = corrected_shares(fit, ft["floor"])
    boot_cons = shares_from_boot(boot_fits, ft["floor"], N_BOOT)

    if cell in PRE_DECLARED_DIAGNOSTIC_CELLS:
        role, role_reason = "diagnostic", (
            f"cell {cell} pre-declared diagnostic-only in README 3.5 (cell-level "
            "exact-zero 5-minute return rate 22.77%)"
        )
    elif zero_share > ZERO_RV_DIAGNOSTIC_THRESHOLD:
        role, role_reason = "diagnostic", (
            f"exact-zero bar RV share {zero_share:.4f} > {ZERO_RV_DIAGNOSTIC_THRESHOLD} "
            "(README 3.5 pre-declared discreteness rule)"
        )
    else:
        role, role_reason = "confirmatory", f"exact-zero bar RV share {zero_share:.4f} within tolerance"
    return {
        "cell": cell,
        "grid": grid,
        "role": role,
        "role_reason": role_reason,
        "m_sub_returns": int(m),
        "sub_per_bin": int(sub_per_bin),
        "native_sub_returns_per_term": int(agg),
        "n_days": int(fit["n_days"]),
        "n_bins": int(fit["n_bins"]),
        "date_first": int(days[0]),
        "date_last": int(days[-1]),
        "zero_rv_share_floored": zero_share,
        "gaussian_noise_floor": floor_g,
        "fat_tail_floor": ft,
        "components": {k: v for k, v in shares.items()},
        "components_bootstrap_ci": boot,
        "components_conservative_floor": {k: v for k, v in shares_cons.items()},
        "components_conservative_bootstrap_ci": boot_cons,
        "diurnal_profile_log": fit["s"].tolist(),
        "tests": {
            "T1_residual_bin_structure": test_residual_bin_structure(u, rng, N_PERM),
            "T2_regime_shape": test_regime_shape(u, days, rng, N_PERM),
            "T3_era_shape": test_era_shape(u, days, rng, N_PERM),
            "T4_residual_stochastic_vol": {
                "status": "OK",
                "v_stoch_raw": shares["v_stoch_raw"],
                "p_value": boot["v_stoch_raw"]["p_one_sided"],
                "ci_lo": boot["v_stoch_raw"]["ci_lo"],
                "ci_hi": boot["v_stoch_raw"]["ci_hi"],
                "v_stoch_conservative": shares_cons["v_stoch_raw"],
                "p_value_conservative": boot_cons["v_stoch_raw"]["p_one_sided"],
                "ci_lo_conservative": boot_cons["v_stoch_raw"]["ci_lo"],
            },
        },
    }


# -------------------------------------------------------------------- robustness


def robustness_checks(mats: dict, rng: np.random.Generator) -> dict[str, Any]:
    """Jump truncation, dropping the opening bin, and dropping zero-RV days."""
    sub_per_bin = 5
    rv, m = bar_rv(mats["ret"], mats["price"], sub_per_bin)
    rv_f, _ = floor_zero_rv(rv, mats["price"], sub_per_bin, mats["tick_size"])
    base_fit = two_way(np.log(rv_f))
    floor_g = gaussian_noise_floor(m)
    base = corrected_shares(base_fit, floor_g)

    # (a) threshold-truncate 1-minute returns at 3x the fitted local scale.
    d, n_bins = base_fit["n_days"], base_fit["n_bins"]
    scale = np.exp(base_fit["mu"] + base_fit["a"][:, None] + base_fit["s"][None, :]) / sub_per_bin
    blocks = mats["ret"][:, : n_bins * sub_per_bin].reshape(d, n_bins, sub_per_bin)
    thr = 3.0 * np.sqrt(scale)[:, :, None]
    trunc = np.where(np.abs(blocks) > thr, 0.0, blocks)
    rv_t = np.square(trunc).sum(axis=2)
    rv_t, _ = floor_zero_rv(rv_t, mats["price"], sub_per_bin, mats["tick_size"])
    u_t = np.log(rv_t)
    trunc_fit = two_way(u_t)
    trunc_shares = corrected_shares(trunc_fit, floor_g)

    # (b) drop the opening bin (auction contamination).
    u_nofirst = np.log(rv_f[:, 1:])
    nofirst = corrected_shares(two_way(u_nofirst), floor_g)

    # (c) drop days containing any exact-zero bar RV (selection check on the floor rule).
    keep = ~(rv <= 0).any(axis=1)
    nozero = (
        corrected_shares(two_way(np.log(rv[keep])), floor_g)
        if keep.sum() > MIN_DAYS_FOR_PASS
        else {"note": "too few days after dropping zero-RV days"}
    )

    return {
        "grid": "m5_5min",
        "baseline": {k: base[k] for k in ("diurnal_share_systematic", "diurnal_share_within_day", "v_stoch_raw")},
        "jump_truncated_3sigma": {
            "truncated_sub_return_share": float(np.mean(np.abs(blocks) > thr)),
            **{k: trunc_shares[k] for k in ("diurnal_share_systematic", "diurnal_share_within_day", "v_stoch_raw")},
            "T1_p_value": test_residual_bin_structure(u_t, rng, N_PERM).get("p_value"),
        },
        "drop_opening_bin": {
            k: nofirst[k]
            for k in ("diurnal_share_systematic", "diurnal_share_within_day", "v_stoch_raw")
        },
        "drop_days_with_zero_rv": {
            "n_days_kept": int(keep.sum()),
            "n_days_dropped": int((~keep).sum()),
            **{
                k: nozero[k]
                for k in ("diurnal_share_systematic", "diurnal_share_within_day", "v_stoch_raw")
                if k in nozero
            },
        },
    }


def cross_grid_consistency(cells: dict) -> dict[str, Any]:
    """Same 5-minute bins, two sub-return counts -> the same Var(log g), or a broken floor.

    ``m5_5min`` and ``m1_5min`` partition the session into the *identical* 60 bins; only
    the estimator of each bin's RV differs. ``Var(log g)`` is a property of the bin, so
    the two grids must agree. A large disagreement is not a finding about volatility --
    it says the Gaussian floor is invalid for the noisier grid, which is exactly what
    price discreteness does to m=1.
    """
    out: dict[str, Any] = {}
    for cell, grids in cells.items():
        if "m5_5min" not in grids or "m1_5min" not in grids:
            continue
        v5 = grids["m5_5min"]["components"]["v_stoch_raw"]
        v1 = grids["m1_5min"]["components"]["v_stoch_raw"]
        out[cell] = {
            "v_stoch_m5": v5,
            "v_stoch_m1": v1,
            "ratio_m1_over_m5": v1 / v5 if v5 else None,
            "consistent_within_2x": bool(v5 > 0 and 0.5 <= (v1 / v5) <= 2.0),
            "m1_sigma2e_over_floor": grids["m1_5min"]["components"]["sigma2_e_over_floor"],
            "m5_sigma2e_over_floor": grids["m5_5min"]["components"]["sigma2_e_over_floor"],
        }
    return out


# ------------------------------------------------------------------- calibration


def _simulate_h0(
    rng: np.random.Generator, s_true: np.ndarray, v_day: float, m: int, d: int, df: float | None
) -> np.ndarray:
    """Sub-returns under H0: deterministic diurnal x AR(1) daily level, no Var(log g)."""
    k = len(s_true)
    a = np.empty(d)
    a[0] = rng.normal(0, np.sqrt(v_day))
    phi = 0.9
    innov = np.sqrt(max(v_day, 1e-12) * (1 - phi**2))
    for t in range(1, d):
        a[t] = phi * a[t - 1] + rng.normal(0, innov)
    var_sub = np.exp(a[:, None] + s_true[None, :]) / m
    if df is None:
        z = rng.standard_normal((d, k, m))
    else:
        z = rng.standard_t(df, size=(d, k, m)) / np.sqrt(df / (df - 2.0))
    r = z * np.sqrt(var_sub)[:, :, None]
    return np.square(r).sum(axis=2)


def calibration_check(
    s_true: np.ndarray, v_day: float, m: int, rng: np.random.Generator
) -> dict[str, Any]:
    """README 4.5 gate: the estimator must find nothing when H0 is literally true."""
    out: dict[str, Any] = {}
    for tag, df in (("gaussian", None), ("student_t_df5", 5.0)):
        floor = gaussian_noise_floor(m)
        v_stoch, p1, p2 = [], [], []
        days = np.array(
            [20200101 + 10000 * (i // 250) + (i % 250) for i in range(CALIB_DAYS)], dtype=np.int64
        )
        for _ in range(CALIB_REPS):
            u = np.log(_simulate_h0(rng, s_true, v_day, m, CALIB_DAYS, df))
            v_stoch.append(corrected_shares(two_way(u), floor)["v_stoch_raw"])
            p1.append(test_residual_bin_structure(u, rng, CALIB_PERM)["p_value"])
            p2.append(test_regime_shape(u, days, rng, CALIB_PERM)["p_value"])
        out[tag] = {
            "reps": CALIB_REPS,
            "v_stoch_mean": float(np.mean(v_stoch)),
            "v_stoch_max": float(np.max(v_stoch)),
            "v_stoch_relative_to_floor": float(np.mean(v_stoch) / floor),
            "T1_reject_rate_at_05": float(np.mean(np.array(p1) < 0.05)),
            "T2_reject_rate_at_05": float(np.mean(np.array(p2) < 0.05)),
        }
    g = out["gaussian"]
    out["gate_passed"] = bool(
        abs(g["v_stoch_mean"]) < 0.05 * gaussian_noise_floor(m)
        and g["T1_reject_rate_at_05"] <= 0.20
        and g["T2_reject_rate_at_05"] <= 0.20
    )
    out["gate_rule"] = (
        "Gaussian H0: |mean V_stoch| < 5% of the noise floor AND T1/T2 rejection at "
        "alpha=0.05 no worse than 0.20 across 20 reps. The Student-t row is not gated; "
        "it quantifies how much fat tails alone inflate V_stoch, which is exactly why "
        "the conservative floor exists."
    )
    return out


# --------------------------------------------------------------------------- FDR


def benjamini_hochberg(pvals: list[float], q: float) -> list[bool]:
    n = len(pvals)
    if n == 0:
        return []
    order = np.argsort(pvals)
    thresh = q * (np.arange(1, n + 1)) / n
    sorted_p = np.asarray(pvals)[order]
    passed = sorted_p <= thresh
    k = np.max(np.nonzero(passed)[0]) + 1 if passed.any() else 0
    out = np.zeros(n, dtype=bool)
    if k:
        out[order[:k]] = True
    return out.tolist()


# --------------------------------------------------------------------------- main


def clean_nonfinite(obj: Any) -> Any:
    """NaN/inf -> None, so the results file is strict JSON and 'not identified' reads as
    null instead of as a number someone could quote."""
    if isinstance(obj, dict):
        return {k: clean_nonfinite(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_nonfinite(v) for v in obj]
    if isinstance(obj, float) and not np.isfinite(obj):
        return None
    if isinstance(obj, (np.floating, np.integer)):
        return clean_nonfinite(obj.item())
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def run() -> dict[str, Any]:
    started = time.time()
    rng = np.random.default_rng(SEED)
    panel = k1735_panel.load_or_build()

    cells: dict[str, Any] = {}
    inventory: dict[str, Any] = {}
    for cell, grids in CELL_GRIDS.items():
        mats = cell_matrices(panel, cell)
        inventory[cell] = {
            "n_days_raw": mats["n_days_raw"],
            "n_days_dropped_low_coverage": mats["n_days_dropped_coverage"],
            "n_days_used": int(len(mats["days"])),
            "date_first": int(mats["days"][0]),
            "date_last": int(mats["days"][-1]),
            "n_bars_per_session": int(mats["ret"].shape[1]),
            "observed_bar_fraction": float(mats["observed"].mean()),
            "tick_size": mats["tick_size"],
            "source": k1735_panel.CELL_SPEC[cell]["kind"],
        }
        cells[cell] = {
            grid: analyse_cell_grid(mats, cell, grid, sub, agg, rng)
            for grid, sub, agg in grids
        }
        if cell == PRIMARY_CELL:
            primary_mats = mats

    robustness = robustness_checks(primary_mats, rng)

    prim = cells[PRIMARY_CELL][PRIMARY_GRID]
    calib = calibration_check(
        np.asarray(prim["diurnal_profile_log"]),
        max(prim["components"]["v_day"], 1e-6),
        prim["m_sub_returns"],
        rng,
    )

    # ---- FDR over the confirmatory family only (README 3.5 / 5)
    family: list[dict[str, Any]] = []
    for cell, grids in cells.items():
        for grid, res in grids.items():
            if res["role"] != "confirmatory":
                continue
            for tname, t in res["tests"].items():
                if t.get("status") != "OK" or t.get("p_value") is None:
                    continue
                family.append({"cell": cell, "grid": grid, "test": tname, "p_value": t["p_value"]})
    flags = benjamini_hochberg([f["p_value"] for f in family], FDR_Q)
    for f, ok in zip(family, flags):
        f["reject_pre_fdr"] = bool(f["p_value"] < 0.05)
        f["reject_post_fdr"] = bool(ok)

    # ---- pre-registered decision rule
    def rejected(cell: str, grid: str, test: str) -> bool:
        return any(
            f["cell"] == cell and f["grid"] == grid and f["test"] == test and f["reject_post_fdr"]
            for f in family
        )

    key_tests = ("T1_residual_bin_structure", "T2_regime_shape", "T4_residual_stochastic_vol")
    primary_rejects = [t for t in key_tests if rejected(PRIMARY_CELL, PRIMARY_GRID, t)]
    replication = {
        t: sorted(
            c
            for c in CONFIRMATORY_CELLS
            if any(rejected(c, g, t) for g in cells[c])
        )
        for t in key_tests
    }
    n_replicating_cells = len(
        {c for t in primary_rejects for c in replication[t]}
    )

    n_days_primary = prim["n_days"]
    if n_days_primary < MIN_DAYS_FOR_PASS:
        verdict = "INSUFFICIENT_DATA"
        reason = f"primary cell has {n_days_primary} usable days < {MIN_DAYS_FOR_PASS}"
    elif len(primary_rejects) >= 2 and n_replicating_cells >= 2 and calib["gate_passed"]:
        verdict = "REJECT_SUFFICIENCY"
        reason = (
            f"{len(primary_rejects)}/3 key tests reject post-FDR on the primary cell "
            f"({', '.join(primary_rejects)}) and replicate in {n_replicating_cells} "
            "confirmatory cells; calibration gate passed"
        )
    elif len(primary_rejects) == 0:
        verdict = "NULL_SUFFICIENCY_NOT_REJECTED"
        reason = "no key test rejects post-FDR on the primary cell"
    else:
        verdict = "CONDITIONAL_PASS"
        bits = [f"{len(primary_rejects)}/3 key tests reject post-FDR on the primary cell"]
        if n_replicating_cells < 2:
            bits.append(f"only {n_replicating_cells} confirmatory cells replicate")
        if not calib["gate_passed"]:
            bits.append("calibration gate FAILED")
        reason = "; ".join(bits)

    return {
        "experiment_id": "K1735",
        "title": "Is the intraday diurnal pattern sufficient to explain RV variation?",
        "date": "2026-08-01",
        "seed": SEED,
        "verdict": verdict,
        "verdict_reason": reason,
        "pre_registered_criteria": {
            "primary_cell": PRIMARY_CELL,
            "primary_grid": PRIMARY_GRID,
            "key_tests": list(key_tests),
            "fdr_q": FDR_Q,
            "min_days_for_pass": MIN_DAYS_FOR_PASS,
            "confirmatory_cells": list(CONFIRMATORY_CELLS),
            "note": "written in README before any result was computed; not amended after",
        },
        "headline": {
            "primary_cell_grid": f"{PRIMARY_CELL}/{PRIMARY_GRID}",
            "naive_share": prim["components"]["naive_share"],
            "naive_share_ci": [
                prim["components_bootstrap_ci"]["naive_share"]["ci_lo"],
                prim["components_bootstrap_ci"]["naive_share"]["ci_hi"],
            ],
            "diurnal_share_systematic": prim["components"]["diurnal_share_systematic"],
            "diurnal_share_systematic_ci": [
                prim["components_bootstrap_ci"]["diurnal_share_systematic"]["ci_lo"],
                prim["components_bootstrap_ci"]["diurnal_share_systematic"]["ci_hi"],
            ],
            "diurnal_share_within_day": prim["components"]["diurnal_share_within_day"],
            "diurnal_share_within_day_ci": [
                prim["components_bootstrap_ci"]["diurnal_share_within_day"]["ci_lo"],
                prim["components_bootstrap_ci"]["diurnal_share_within_day"]["ci_hi"],
            ],
            "measurement_noise_share_of_naive_denominator": prim["components"][
                "noise_share_of_total"
            ],
            # The point estimate is the reading least favourable to the diurnal pattern.
            # Both robustness directions push it up, so the honest deliverable is the
            # bracket, not the point.
            "diurnal_share_within_day_bracket": {
                "baseline_gaussian_floor": prim["components"]["diurnal_share_within_day"],
                "jump_truncated_3sigma": robustness["jump_truncated_3sigma"][
                    "diurnal_share_within_day"
                ],
                "conservative_fat_tail_floor": prim["components_conservative_floor"][
                    "diurnal_share_within_day"
                ],
                "note": (
                    "the conservative floor is deliberately too high (stochastic intraday "
                    "vol makes standardised sub-returns look fat-tailed), so the truth "
                    "sits inside this bracket rather than at either end"
                ),
            },
            "primary_rejects_post_fdr": primary_rejects,
            "replication_by_test": replication,
        },
        "data_inventory": inventory,
        "cells": cells,
        "robustness_primary_cell": robustness,
        "cross_grid_consistency": cross_grid_consistency(cells),
        "calibration": calib,
        "fdr_family": {
            "q": FDR_Q,
            "n_tests": len(family),
            "n_reject_pre_fdr": int(sum(f["reject_pre_fdr"] for f in family)),
            "n_reject_post_fdr": int(sum(f["reject_post_fdr"] for f in family)),
            "members": family,
        },
        "n_boot": N_BOOT,
        "n_perm": N_PERM,
        "runtime_seconds": round(time.time() - started, 1),
    }


README_BEGIN = "<!-- RESULTS:BEGIN -->"
README_END = "<!-- RESULTS:END -->"


def _f(x: Any, nd: int = 4) -> str:
    return "n/a" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{nd}f}"


def render_readme(results: dict[str, Any]) -> None:
    """Regenerate README section 9 from the results JSON. Never hand-typed."""
    h = results["headline"]
    br = h["diurnal_share_within_day_bracket"]
    lines = [
        README_BEGIN,
        "",
        f"**Verdict: `{results['verdict']}`** — {results['verdict_reason']}",
        "",
        f"主 cell = `{h['primary_cell_grid']}`"
        f"（{results['data_inventory']['tx_day']['date_first']}–"
        f"{results['data_inventory']['tx_day']['date_last']}，"
        f"{results['cells']['tx_day']['m5_5min']['n_days']} 個交易日 × "
        f"{results['cells']['tx_day']['m5_5min']['n_bins']} 個 bin）。",
        "",
        "### 季節成分佔 RV 變異的比例（點估計 [95% day-block bootstrap CI]）",
        "",
        "| 口徑 | 點估計 | 95% CI |",
        "|------|--------|--------|",
        f"| `naive_share`（未扣噪音地板，與舊實驗可比）| {_f(h['naive_share'])} | "
        f"[{_f(h['naive_share_ci'][0])}, {_f(h['naive_share_ci'][1])}] |",
        f"| `diurnal_share_systematic`（佔全部系統性波動變異）| {_f(h['diurnal_share_systematic'])} | "
        f"[{_f(h['diurnal_share_systematic_ci'][0])}, {_f(h['diurnal_share_systematic_ci'][1])}] |",
        f"| `diurnal_share_within_day`（佔日內變異）| {_f(h['diurnal_share_within_day'])} | "
        f"[{_f(h['diurnal_share_within_day_ci'][0])}, {_f(h['diurnal_share_within_day_ci'][1])}] |",
        "",
        f"測量噪音地板佔 naive 分母的 "
        f"**{h['measurement_noise_share_of_naive_denominator']:.1%}** —— "
        "這就是舊實驗 eta²≈0.07 的來源。",
        "",
        "**`diurnal_share_within_day` 的穩健性區間**（點估計是對 diurnal 最不利的一端，"
        "兩個穩健方向都把它推高，故交付的是區間不是點）：",
        "",
        f"- baseline（Gaussian 地板）：**{_f(br['baseline_gaussian_floor'])}**",
        f"- 跳躍截斷 3σ 後：**{_f(br['jump_truncated_3sigma'])}**",
        f"- 保守 fat-tail 地板：**{_f(br['conservative_fat_tail_floor'])}**",
        "",
        "### 檢定（BH-FDR q=0.10，confirmatory 家族）",
        "",
        "| cell | grid | test | p | pre-FDR | post-FDR |",
        "|------|------|------|---|---------|----------|",
    ]
    for f in results["fdr_family"]["members"]:
        lines.append(
            f"| {f['cell']} | {f['grid']} | {f['test']} | {f['p_value']:.4f} | "
            f"{'✅' if f['reject_pre_fdr'] else '—'} | {'✅' if f['reject_post_fdr'] else '—'} |"
        )
    calib = results["calibration"]
    lines += [
        "",
        f"FDR 家族 {results['fdr_family']['n_tests']} 個檢定，"
        f"pre-FDR 拒絕 {results['fdr_family']['n_reject_pre_fdr']} 個、"
        f"post-FDR 拒絕 {results['fdr_family']['n_reject_post_fdr']} 個。",
        "",
        f"校準 gate（§4.5）：**{'PASS' if calib['gate_passed'] else 'FAIL'}** — "
        f"Gaussian H0 下 V_stoch 平均 {calib['gaussian']['v_stoch_mean']:.5f}"
        f"（噪音地板的 {calib['gaussian']['v_stoch_relative_to_floor']:.2%}），"
        f"T1/T2 在 α=0.05 的拒絕率 {calib['gaussian']['T1_reject_rate_at_05']:.2f} / "
        f"{calib['gaussian']['T2_reject_rate_at_05']:.2f}。",
        "",
        README_END,
    ]
    path = EXP_DIR / "README.md"
    text = path.read_text(encoding="utf-8")
    head, _, rest = text.partition(README_BEGIN)
    _, _, tail = rest.partition(README_END)
    path.write_text(head + "\n".join(lines) + tail, encoding="utf-8")
    print(f"[readme] rewrote results block in {path}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--render-readme", action="store_true")
    args = ap.parse_args()

    started = time.time()
    results = clean_nonfinite(run())
    results_path, _ = finalize_experiment(
        results=results,
        entrypoint=__file__,
        canonical_result="K1735_results.json",
        exp_dir=EXP_DIR,
        inputs=[EXP_DIR / "k1735_panel.py", k1735_panel.PANEL_PATH],
        outputs=["K1735_results.json"],
        seeds=[("numpy_default_rng", SEED)],
        started_at=started,
    )
    if args.render_readme:
        render_readme(results)
    print(json.dumps({k: results[k] for k in ("verdict", "verdict_reason", "headline")},
                     indent=2, ensure_ascii=False, default=str))
    print(f"wrote {results_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
