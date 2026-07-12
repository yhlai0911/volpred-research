#!/usr/bin/env python3
"""Stationary-bootstrap 95% CI for the opportunity-cost share of the VT premium.

Statistic (same construction as reproduce.summarize_cost_components; the common
annualization factor cancels in the ratio):

    share = OPP / (OPP + TX),  OPP = sum_t opp_t,  TX = sum_t tx_t

summed over regime-known days (the "Unknown" warm-up prefix — the first 60
expanding-z-score days — is excluded from the sums in reproduce.py and is
likewise excluded from the resampled series here, so the bootstrap acts on a
contiguous stationary subseries rather than on zero-padded warm-up rows).
opp_t = spy_ret_t - w_t * spy_ret_t (gross), tx_t = 5 bps turnover cost.

Point estimates use unrounded sums: S1 90.755%, S2 57.115%. reproduce_report's
derived claim 90.752% is the same quantity computed from 3-dp-rounded
components (4.200/4.628); the difference is rounding path only.

Bootstrap: Politis-Romano (1994) stationary bootstrap on the day-level pairs
(opp_t, tx_t), circular, expected block length 21 trading days (p = 1/21),
B = 10,000, seed = 42. S1 and S2 shares are recomputed on the SAME resampled
index paths, so the two CIs are draw-for-draw comparable.

Pole handling (important): share is a ratio whose denominator OPP + TX can
cross zero in resamples, so raw share percentiles mix values from both sides
of the pole at R = OPP/TX = -1 and are meaningless. TX > 0 in every resample,
so the CI is built on R = OPP/TX (always well defined) and mapped through
share = R/(1+R), which is increasing on each branch of R != -1 — the
percentile CI is transformation-respecting whenever [R_lo, R_hi] avoids the
pole. If the R interval contains -1, no bounded connected 95% CI for the
share exists (the confidence set is unbounded/disconnected); that case is
reported honestly, together with the R interval and the annualized
total-premium CI as the interpretable substitutes.

Output: k811v2_share_bootstrap_ci_results.json (same directory).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np

from k811v2_paper_panel import build_daily_panel

OUT_PATH = Path(__file__).resolve().parent / "k811v2_share_bootstrap_ci_results.json"

SEED = 42
N_REPS = 10_000
EXPECTED_BLOCK_LEN = 21  # trading days ~ 1 month
CHUNK = 1_000            # reps per vectorized chunk (memory control)
TRADING_DAYS = 252


def stationary_bootstrap_indices(
    rng: np.random.Generator, n_obs: int, n_reps: int, p_restart: float
) -> np.ndarray:
    """(n_reps, n_obs) index paths of the circular stationary bootstrap."""
    starts = rng.integers(0, n_obs, size=(n_reps, n_obs))
    restart = rng.random((n_reps, n_obs)) < p_restart
    restart[:, 0] = True
    pos = np.arange(n_obs)
    last_restart = np.maximum.accumulate(np.where(restart, pos, -1), axis=1)
    anchor = np.take_along_axis(starts, last_restart, axis=1)
    return (anchor + (pos - last_restart)) % n_obs


def share_from_ratio(ratio: float) -> float:
    return ratio / (1.0 + ratio) * 100.0


def main() -> None:
    panel = build_daily_panel()
    n_total = len(panel.spy_rets)  # reproduce.py annualizes by the FULL panel
    known = panel.regimes != "Unknown"
    assert not known[: int(np.argmax(known))].any() and known[int(np.argmax(known)):].all(), (
        "Unknown days are expected to be a contiguous warm-up prefix; the "
        "resampled subseries would otherwise not be contiguous in time"
    )
    n_known = int(known.sum())
    ann_factor = TRADING_DAYS * 100.0 / n_total

    components = {
        "S1": ((panel.spy_rets - panel.s1_gross)[known], panel.s1_tx[known]),
        "S2": ((panel.spy_rets - panel.s2_gross)[known], panel.s2_tx[known]),
    }

    points = {
        name: float(opp.sum() / (opp.sum() + tx.sum()) * 100.0)
        for name, (opp, tx) in components.items()
    }
    print(f"  n_days={n_total} (regime-known {n_known})  point shares: "
          f"S1 {points['S1']:.3f}%  S2 {points['S2']:.3f}%")

    rng = np.random.default_rng(SEED)
    p_restart = 1.0 / EXPECTED_BLOCK_LEN
    opp_sums: dict[str, list[np.ndarray]] = {name: [] for name in components}
    tx_sums: dict[str, list[np.ndarray]] = {name: [] for name in components}
    for chunk_start in range(0, N_REPS, CHUNK):
        n_chunk = min(CHUNK, N_REPS - chunk_start)
        idx = stationary_bootstrap_indices(rng, n_known, n_chunk, p_restart)
        for name, (opp, tx) in components.items():
            opp_sums[name].append(opp[idx].sum(axis=1))
            tx_sums[name].append(tx[idx].sum(axis=1))

    results: dict[str, object] = {
        "experiment": "K811v2 share bootstrap CI",
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "statistic": (
            "opportunity-cost share of total VT insurance premium, %; "
            "share = OPP / (OPP + TX) over regime-known days"
        ),
        "data": {
            "source": "paper/vt-insurance-cost/data/*.csv bundled raw-Close snapshot",
            "period_start": str(panel.dates[0].date()),
            "period_end": str(panel.dates[-1].date()),
            "n_days": n_total,
            "n_regime_known_days": n_known,
            "resampled_series": (
                "contiguous regime-known subseries only; the Unknown warm-up "
                "prefix is excluded before resampling"
            ),
        },
        "bootstrap": {
            "method": "stationary bootstrap (Politis-Romano 1994), circular",
            "expected_block_length_days": EXPECTED_BLOCK_LEN,
            "p_restart": p_restart,
            "n_reps": N_REPS,
            "seed": SEED,
            "ci_method": (
                "percentile (2.5, 97.5) on R = OPP/TX, mapped through "
                "share = R/(1+R) (increasing on each branch of R != -1); when "
                "the R interval contains the pole at -1, no bounded connected "
                "95% CI for the share exists and none is reported"
            ),
            "joint_resampling": (
                "S1 and S2 shares computed on identical resampled index paths"
            ),
        },
    }

    for name in components:
        opp_draws = np.concatenate(opp_sums[name])
        tx_draws = np.concatenate(tx_sums[name])
        assert tx_draws.min() > 0.0, f"{name}: resample with zero direct cost"

        ratio_draws = opp_draws / tx_draws
        r_lo, r_hi = np.percentile(ratio_draws, [2.5, 97.5])
        n_beyond_pole = int((ratio_draws <= -1.0).sum())  # total premium <= 0
        ci_bounded = not (r_lo <= -1.0 <= r_hi)

        total_ann = (opp_draws + tx_draws) * ann_factor
        total_lo, total_hi = np.percentile(total_ann, [2.5, 97.5])
        opp_ann = opp_draws * ann_factor
        opp_lo, opp_hi = np.percentile(opp_ann, [2.5, 97.5])

        entry: dict[str, object] = {
            "point_estimate_pct": round(points[name], 3),
            "share_ci95_bounded": bool(ci_bounded),
            "opp_to_direct_ratio_point": round(
                float(components[name][0].sum() / components[name][1].sum()), 4
            ),
            "opp_to_direct_ratio_ci95": [round(float(r_lo), 4), round(float(r_hi), 4)],
            "n_reps_total_premium_le_0": n_beyond_pole,
            "opportunity_cost_pct_yr_ci95": [
                round(float(opp_lo), 3), round(float(opp_hi), 3)
            ],
            "total_premium_pct_yr_ci95": [
                round(float(total_lo), 3), round(float(total_hi), 3)
            ],
        }
        if ci_bounded:
            entry["ci95_lower_pct"] = round(share_from_ratio(float(r_lo)), 3)
            entry["ci95_upper_pct"] = round(share_from_ratio(float(r_hi)), 3)
            print(
                f"  {name}: share {points[name]:.2f}%  "
                f"95% CI [{entry['ci95_lower_pct']:.2f}%, "
                f"{entry['ci95_upper_pct']:.2f}%]  "
                f"(total premium <= 0 in {n_beyond_pole}/{N_REPS} draws)"
            )
        else:
            entry["ci95_lower_pct"] = None
            entry["ci95_upper_pct"] = None
            entry["no_bounded_ci_reason"] = (
                "R interval contains the pole at -1: the total premium is not "
                "bounded away from zero under resampling "
                f"({n_beyond_pole}/{N_REPS} draws with total premium <= 0), so "
                "no bounded connected 95% CI for the share exists. Use the "
                "total-premium CI for the robustness statement instead."
            )
            print(
                f"  {name}: share {points[name]:.2f}%  no bounded 95% CI "
                f"(total premium <= 0 in {n_beyond_pole}/{N_REPS} draws; "
                f"total premium 95% CI [{total_lo:.2f}, {total_hi:.2f}] %/yr)"
            )
        results[f"{name.lower()}_share"] = entry

    OUT_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    print(f"  wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
