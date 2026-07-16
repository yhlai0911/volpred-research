"""K1678 HAC bandwidth sensitivity (closeout robustness check, 2026-07-17).

K1678.py:872 sets ``maxlags = horizon - 1`` for every date-clustered HAC fit, so
the four H=1 cells were estimated with maxlags=0.  That truncates the Bartlett
kernel at zero lags, which leaves White heteroskedasticity-robust standard
errors -- still robust to heteroskedasticity, but carrying no serial-correlation
correction whatsoever.  The repo mechanised the
K1655 bandwidth rule on 2026-07-11, one day AFTER K1678 ran, and its ratchet
only classifies hand-written DM loops (``range(1, h)``), so a statsmodels
``cov_type="HAC"`` call with ``maxlags = horizon - 1`` is outside its scope.
This script re-fits the eight predeclared cells from the cached matched-event
CSV under a range of bandwidths, including the repo canonical
``ceil(h**(1/3) * n**(1/3))``, to test whether the NULL verdict is robust to
that choice.  No new data is downloaded and no model is re-estimated from raw
prices: the matched panel is taken as given.

Direction matters both ways (K1655 / k621): positive residual autocorrelation
inflates |t| when uncorrected, but negative autocorrelation deflates it, so a
null result is NOT automatically safe under an omitted HAC correction.

Every fit K1678 ran through ``fit_date_hac`` inherited the same bandwidth, so all
three families are swept rather than argued away from their as-run |t|:
the 8 predeclared ``saliency_diff`` cells, the 16 ``pump_diff`` /
``saliency21_diff`` sensitivity cells, and the 8 intercept-only direct
event-minus-control diagnostics.  Citing an as-run |t| as evidence about other
bandwidths would repeat the exact reasoning error this check exists to catch.

Run: uv run python experiments/K1678/hac_bandwidth_check.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

HERE = Path(__file__).resolve().parent
PAIRS_CSV = HERE / "K1678_matched_events.csv.gz"
RESULTS_JSON = HERE / "K1678_results.json"
OUT_JSON = HERE / "K1678_hac_bandwidth_check.json"

# Verbatim from K1678.py
REGRESSION_BALANCE_CONTROLS = ("ret1_lag1_diff", "log_rv21_lag1_diff", "volume_z_lag1_diff")
OUTCOMES = ("rv", "dsv", "left_tail", "downside_gap")
HORIZONS = (1, 5)
SIGNAL_COL = "saliency_diff"
SENSITIVITY_SIGNALS = ("pump_diff", "saliency21_diff")
STRICT_T = 3.0  # Harvey directional strength gate
FAMILY_SIZE = 8


def standardise(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    out = frame.copy()
    for column in columns:
        mean = float(out[column].mean())
        std = float(out[column].std(ddof=1))
        if not np.isfinite(std) or std <= 0.0:
            raise RuntimeError(f"Cannot standardise {column}: std={std}")
        out[column] = (out[column] - mean) / std
    return out


def date_frame_for(pairs: pd.DataFrame, outcome: str, horizon: int, signal_col: str) -> pd.DataFrame:
    y_col = f"{outcome}_diff"
    subset = pairs[pairs["horizon"] == horizon]
    aggregation = {y_col: "mean", signal_col: "mean"}
    aggregation.update({column: "mean" for column in REGRESSION_BALANCE_CONTROLS})
    frame = (
        subset.groupby("formation_date", as_index=False)
        .agg(aggregation)
        .sort_values("formation_date")
    )
    return frame.dropna(subset=[y_col, signal_col, *REGRESSION_BALANCE_CONTROLS])


def fit(frame: pd.DataFrame, outcome: str, maxlags: int, signal_col: str = SIGNAL_COL) -> dict:
    y_col = f"{outcome}_diff"
    model_columns = [signal_col, *REGRESSION_BALANCE_CONTROLS]
    std_frame = standardise(frame, model_columns)
    x = sm.add_constant(std_frame[model_columns], has_constant="add")
    res = sm.OLS(std_frame[y_col], x).fit(
        cov_type="HAC", cov_kwds={"maxlags": maxlags, "use_correction": True}
    )
    return {
        "beta_per_1sd": float(res.params[signal_col]),
        "se_hac": float(res.bse[signal_col]),
        "t_hac": float(res.tvalues[signal_col]),
        "p_hac_two_sided": float(res.pvalues[signal_col]),
        "resid_acf1": float(pd.Series(res.resid).autocorr(lag=1)),
    }


def fit_direct(frame: pd.DataFrame, outcome: str, maxlags: int) -> dict:
    """Intercept-only event-minus-control diagnostic, mirroring K1678.py:885-888.

    Note this one regresses the UNstandardised outcome difference on a constant,
    exactly as the original does.
    """
    y_col = f"{outcome}_diff"
    res = sm.OLS(frame[y_col], np.ones((len(frame), 1))).fit(
        cov_type="HAC", cov_kwds={"maxlags": maxlags, "use_correction": True}
    )
    return {
        "mean": float(res.params.iloc[0]),
        "t_hac": float(res.tvalues.iloc[0]),
        "p_hac_two_sided": float(res.pvalues.iloc[0]),
    }


def canonical_bandwidth(horizon: int, n: int) -> int:
    """Repo canonical HAC bandwidth: ceil(h^(1/3) * n^(1/3)).

    volpred.stats.model_evaluation.dm_test additionally applies a max(1, .) floor
    and a min(., n // 4) cap.  Neither binds at the sample sizes here (n=302 -> cap
    75; n=242 -> cap 60), so they are omitted rather than silently changing the
    number this check reports; they would bind for n < 64.
    """
    return int(math.ceil((horizon ** (1 / 3)) * (n ** (1 / 3))))


def main() -> None:
    pairs = pd.read_csv(PAIRS_CSV)
    stored = json.loads(RESULTS_JSON.read_text())
    stored_cells = {(c["outcome"], c["horizon"]): c for c in stored["primary_results"]}

    cells: list[dict] = []
    sensitivity_cells: list[dict] = []
    direct_cells: list[dict] = []
    replication_max_abs_diff = 0.0

    for horizon in HORIZONS:
        for outcome in OUTCOMES:
            frame = date_frame_for(pairs, outcome, horizon, SIGNAL_COL)
            n = len(frame)
            as_run = horizon - 1
            canonical = canonical_bandwidth(horizon, n)
            grid = sorted({as_run, canonical, 4, 8, 12, 20})

            # Replicate the stored cell exactly before trusting anything else.
            repl = fit(frame, outcome, as_run)
            stored_cell = stored_cells[(outcome, horizon)]
            diff = abs(repl["t_hac"] - stored_cell["t_hac"])
            replication_max_abs_diff = max(replication_max_abs_diff, diff)

            by_lag = {str(lag): fit(frame, outcome, lag) for lag in grid}
            cells.append(
                {
                    "outcome": outcome,
                    "horizon": horizon,
                    "n_event_date_clusters": n,
                    "maxlags_as_run": as_run,
                    "maxlags_canonical": canonical,
                    "stored_t_hac": stored_cell["t_hac"],
                    "replicated_t_hac": repl["t_hac"],
                    "replication_abs_diff": diff,
                    "resid_acf1": repl["resid_acf1"],
                    "by_maxlags": by_lag,
                    "max_abs_t_over_grid": max(abs(v["t_hac"]) for v in by_lag.values()),
                    "canonical_t_hac": by_lag[str(canonical)]["t_hac"],
                    "canonical_p_hac": by_lag[str(canonical)]["p_hac_two_sided"],
                }
            )

            # The intercept-only direct diagnostic shares the same bandwidth and the
            # same date frame, and the README makes a claim about it, so sweep it too.
            direct_by_lag = {str(lag): fit_direct(frame, outcome, lag) for lag in grid}
            direct_cells.append(
                {
                    "outcome": outcome,
                    "horizon": horizon,
                    "stored_t_hac": stored_cell["direct_event_minus_control_t_hac"],
                    "replicated_t_hac": direct_by_lag[str(as_run)]["t_hac"],
                    "replication_abs_diff": abs(
                        direct_by_lag[str(as_run)]["t_hac"]
                        - stored_cell["direct_event_minus_control_t_hac"]
                    ),
                    "by_maxlags": direct_by_lag,
                    "max_abs_t_over_grid": max(abs(v["t_hac"]) for v in direct_by_lag.values()),
                    "canonical_t_hac": direct_by_lag[str(canonical)]["t_hac"],
                }
            )

            # Secondary saliency definitions inherited the bandwidth as well.
            for signal in SENSITIVITY_SIGNALS:
                sens_frame = date_frame_for(pairs, outcome, horizon, signal)
                sens_n = len(sens_frame)
                sens_canonical = canonical_bandwidth(horizon, sens_n)
                sens_grid = sorted({as_run, sens_canonical, 4, 8, 12, 20})
                sens_by_lag = {
                    str(lag): fit(sens_frame, outcome, lag, signal_col=signal) for lag in sens_grid
                }
                sensitivity_cells.append(
                    {
                        "signal": signal,
                        "outcome": outcome,
                        "horizon": horizon,
                        "n_event_date_clusters": sens_n,
                        "maxlags_as_run": as_run,
                        "maxlags_canonical": sens_canonical,
                        "as_run_t_hac": sens_by_lag[str(as_run)]["t_hac"],
                        "canonical_t_hac": sens_by_lag[str(sens_canonical)]["t_hac"],
                        "by_maxlags": sens_by_lag,
                        "max_abs_t_over_grid": max(abs(v["t_hac"]) for v in sens_by_lag.values()),
                    }
                )

    canonical_p = [c["canonical_p_hac"] for c in cells]
    primary_max = max(c["max_abs_t_over_grid"] for c in cells)
    sens_max = max(c["max_abs_t_over_grid"] for c in sensitivity_cells)
    direct_max = max(c["max_abs_t_over_grid"] for c in direct_cells)
    summary = {
        "generated_by": "experiments/K1678/hac_bandwidth_check.py",
        "purpose": (
            "Test whether K1678's NULL verdict survives the repo canonical HAC bandwidth, "
            "given K1678.py:872 used maxlags = horizon - 1 (= 0 at H=1, which leaves White "
            "heteroskedasticity-robust SEs with no serial-correlation correction)."
        ),
        "replication_max_abs_t_diff_vs_stored": replication_max_abs_diff,
        "harvey_strict_t_gate": STRICT_T,
        "primary_family": {
            "n_cells": len(cells),
            "max_abs_t_any_cell_any_tested_bandwidth": primary_max,
            "n_cells_reaching_strict_t_at_canonical": sum(
                1 for c in cells if abs(c["canonical_t_hac"]) >= STRICT_T
            ),
            "n_cells_reaching_strict_t_any_tested_bandwidth": sum(
                1 for c in cells if c["max_abs_t_over_grid"] >= STRICT_T
            ),
            # Cap at 1.0 exactly as K1678.py:924 does — an uncapped p * m is not a probability.
            "min_bonferroni_p_at_canonical": min(min(1.0, p * FAMILY_SIZE) for p in canonical_p),
        },
        "sensitivity_family": {
            "n_cells": len(sensitivity_cells),
            "max_abs_t_any_cell_any_tested_bandwidth": sens_max,
            "n_cells_reaching_strict_t_any_tested_bandwidth": sum(
                1 for c in sensitivity_cells if c["max_abs_t_over_grid"] >= STRICT_T
            ),
        },
        "direct_diagnostic": {
            "n_cells": len(direct_cells),
            "max_abs_t_any_cell_any_tested_bandwidth": direct_max,
            "note": (
                "Secondary intercept-only event-minus-control diagnostic, outside the predeclared "
                "verdict family and carrying no multiple-testing correction."
            ),
        },
        "verdict_unchanged": primary_max < STRICT_T,
        "cells": cells,
        "sensitivity_cells": sensitivity_cells,
        "direct_cells": direct_cells,
    }
    OUT_JSON.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    print(f"replication max |t| diff vs stored: {replication_max_abs_diff:.2e}")
    print(f"{'outcome':<14}{'H':>2}{'n':>5}{'as_run':>7}{'canon':>6}{'acf1':>8}{'t_run':>9}{'t_canon':>9}{'|t|max':>8}")
    for c in cells:
        print(
            f"{c['outcome']:<14}{c['horizon']:>2}{c['n_event_date_clusters']:>5}"
            f"{c['maxlags_as_run']:>7}{c['maxlags_canonical']:>6}{c['resid_acf1']:>8.3f}"
            f"{c['replicated_t_hac']:>9.3f}{c['canonical_t_hac']:>9.3f}{c['max_abs_t_over_grid']:>8.3f}"
        )
    print(f"\nprimary     ({len(cells):>2} cells): max |t| over tested bandwidths = {primary_max:.3f}")
    print(f"sensitivity ({len(sensitivity_cells):>2} cells): max |t| over tested bandwidths = {sens_max:.3f}")
    print(f"direct diag ({len(direct_cells):>2} cells): max |t| over tested bandwidths = {direct_max:.3f}")
    print(
        "primary cells reaching Harvey t>=3 at canonical bandwidth: "
        f"{summary['primary_family']['n_cells_reaching_strict_t_at_canonical']}/{len(cells)}"
    )
    print(f"NULL verdict unchanged: {summary['verdict_unchanged']}")


if __name__ == "__main__":
    main()
