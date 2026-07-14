"""K1709-rev — Spot BTC/ETH ETF net flow shocks and next-day realized volatility.

Research question
-----------------
Do daily *net creation/redemption flows* of spot Bitcoin/Ethereum ETFs carry
incremental **unconditional average-loss** predictive content for BTC/ETH
realized volatility at t+1 and t+5, once the standard HAR-RV volatility
dynamics are controlled for? Conditional/state-dependent predictive ability is
a different question and is not tested here.

Orthogonality declaration
-------------------------
This is NOT the "ETF-ization changed the trading clock / session structure"
line of work. The treatment here is the *flow* itself (dollar creations minus
redemptions), not the calendar/microstructure of ETF trading hours.

Inference design (this is what v1 got wrong)
--------------------------------------------
`HAR+ctrl` and `HAR+ctrl+flow` are STRICTLY NESTED. What breaks an ordinary
loss-difference statistic here is not nesting by itself: it is nesting COMBINED
WITH AN ESTIMATION SCHEME THAT DRIVES ESTIMATION ERROR TO ZERO. Under an
expanding (recursive) window the two methods' forecasts converge under the null,
the loss differential degenerates, and the statistic tilts toward the smaller
model. Under a FIXED ROLLING window the estimation error never vanishes, the
loss differential keeps a non-degenerate variance, and the comparison is legal
again -- that is precisely Giacomini-White's (2006) construction. v1 pushed an
expanding-window QLIKE loss through a raw Diebold-Mariano statistic and then
bolted on a Clark-West helper that actually scores *variance-level squared
error* -- three different estimands fused into a single NULL gate. See
`codex_review_20260714.md` and the K1701 lesson in `docs/error_log.md`
(2026-07-13 05:47).

  nested-dm: diagnostic-only  -- every raw Diebold-Mariano number in this file is
  descriptive and is tagged `feeds_gate=False`. None of them reaches a verdict.
  Two DIFFERENT reasons sit behind that one tag, and they must not be conflated:
  the EXPANDING-window statistic is diagnostic because it is INVALID (degenerate
  null); the FIXED-window statistic is diagnostic because the verdict is carried
  by the pre-registered Giacomini-White object, NOT because it is invalid -- it
  runs on the same GW-legal loss stream and agrees with the gate statistic to ~3
  decimals.

What the claim actually rests on:
  * Giacomini-White (2006) equal-unconditional-predictive-ability test on Patton
    QLIKE, computed from a PAIRED FIXED ROLLING WINDOW. GW keeps estimation
    uncertainty in the limiting experiment, which is exactly what makes it legal
    for nested *methods* where a vanishing-estimation-error scheme is not.
    Bounded estimator memory is a condition on the whole FORECASTING METHOD, not
    just on the final regression: the two asset-specific robustness rows whose
    regressors are built from expanding-window AR(5) fits
    (`flow_transform/unexpected_z`) therefore do NOT satisfy it, are flagged as
    such in the registry (`bounded_memory=false`), and are diagnostic-only. None
    of the 10 primary cells uses them.
  * A pre-specified one-sided MATERIAL-GAIN EXCLUSION test. Failing to reject
    equal accuracy is not evidence of equality; only this test can license a
    bound on the UNCONDITIONAL average QLIKE-loss estimand. It cannot bound
    conditional or regime-specific gains.
  * Clark-West is retained but reported strictly as evidence about a SEPARATE
    MSPE estimand. It is never relabelled as a QLIKE general-loss test.

Power is reported (>=1000 simulated OOS paths, with a false-positive check at
beta = 0) but it is a statement about the DESIGN, not about the effect: power
cannot prove that the effect is smaller than the minimum detectable effect. v1
made exactly that inversion. Its SCOPE is deliberately narrow and must be quoted
as such: h = 1 only (the primary family also contains h = 5), a single injected
|flow| shock (the H2 asymmetry and the cross-asset H4 alternatives are NOT
simulated), and a SINGLE-CELL nominal gate. It is NOT the power of the ten-cell
Holm-corrected family, which is strictly lower. The beta = 0 row is a
FALSE-POSITIVE DIAGNOSTIC, not a size calibration -- see `false_positive_note`.

Information set / lookahead
---------------------------
Farside publishes day-t flows after the US close (~20:00-21:00 UTC on day t).
We therefore set the forecast origin at 00:00 UTC ending calendar day t:
    - flow_t          known (published ~21:00 UTC, i.e. before 24:00 UTC)
    - RV_t (UTC day)  known (the UTC day just closed)
    - target RV_{t+1} lies entirely in the future
State controls and the flow carry SEPARATE lags (`state_lag`, `flow_lag`): if a
flow only becomes usable one day later, that does not un-observe yesterday's
realized volatility.

Run:  uv run python experiments/k1709/k1709.py
"""

from __future__ import annotations

import io
import hashlib
import json
import math
import os
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import exchange_calendars as xcals  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402
import yfinance as yf  # noqa: E402
from scipy import stats  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from volpred.stats.model_evaluation import (  # noqa: E402
    clark_west_test,
    dm_test,
    qlike_pointwise,
)

warnings.filterwarnings("ignore")

SEED = 1709
np.random.seed(SEED)

OUT = Path(__file__).resolve().parent
UA = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}
FARSIDE = {
    "BTC": "https://farside.co.uk/bitcoin-etf-flow-all-data/",
    "ETH": "https://farside.co.uk/ethereum-etf-flow-all-data/",
}
TICKER = {"BTC": "BTC-USD", "ETH": "ETH-USD"}

# HAR-RV lag structure (Corsi 2009), in calendar days (crypto trades 24/7).
HAR_W, HAR_M = 5, 22
Z_WINDOW = 20            # rolling window for the flow-shock scaling (flow days)
HORIZONS = (1, 5)
EPS = 1e-12
VAR_FLOOR = 1e-12
STATE_LAG = 1            # RV/return controls are always known one day ahead

# --- Giacomini-White design constants -------------------------------------
# GW's asymptotics require BOUNDED estimator memory: the forecasting *method*
# must re-estimate on a fixed-length rolling window, not an expanding one. 250
# flow days (~1 trading year) is the longest window that still leaves ETH -- the
# shorter series -- with enough origins for the test's n>=60 requirement.
GW_TRAIN_WINDOW = 250
GW_MIN_LOSSES = 60

# Pre-specified BEFORE looking at the exclusion results: the same "minimum
# meaningful relative QLIKE gain" margin K1701 uses. It is a project standard,
# not a number tuned until the null passed.
MATERIAL_GAIN_MARGIN = 0.01

# Power-simulation grid. beta is the true coefficient on |z| in the log-variance
# equation, so a one-sd flow shock multiplies RV by exp(beta).
POWER_REPS = 1000
POWER_BETAS = (0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.45, 0.60)
POWER_GATE_Z = -1.645    # one-sided 5% GW gate, pre-specified

# Machine-readable contract for the narrow third nested-DM role accepted by the
# repo auditor. This object cannot self-waive the ratchet: the auditor also
# validates the frozen per-cell runtime inventory and a trusted-main external
# adjudication receipt bound to these exact source/claim-surface bytes.
NESTED_DM_FIXED_MEMORY_MANIFEST_V1 = {
    "schema": "nested_dm_fixed_memory.v1",
    "role": "primary_unconditional_gw_dm_fixed_memory",
    "claim_scope": "unconditional_average_loss_only",
    "conditional_predictive_ability_tested": False,
    "regime_offsetting_effects_excluded": False,
    "implementation": {
        "paired_forecast_function": "paired_oos",
        "statistic_function": "gw_unconditional_dm",
        "gate_registry_inference": "giacomini_white_qlike_fixed_window",
        "train_window_constant": "GW_TRAIN_WINDOW",
        "model_spec_registry": "SPECS",
        "base_model_parameter": "base",
        "augmented_model_parameter": "alt",
        "paired_result_variable": "po",
        "gate_function": "evaluate_cell",
        "registry_record_constructor": "TestRecord",
        "gate_eligibility_variable": "gate_eligible",
        "whole_method_eligibility_variable": "whole_method_fixed_memory",
        "bounded_memory_parameter": "bounded_memory",
        "paired_audit_attribute": "audit",
        "paired_eligibility_key": "gw_fixed_memory_eligible",
        "base_design_variable": "Xb",
        "augmented_design_variable": "Xa",
        "fit_function": "fit",
        "runtime_evidence_file": "k1709_results.json",
        "runtime_evidence_key": "nested_dm_fixed_memory_evidence_v1",
        "runtime_cell_inventory": "primary_cells",
        "runtime_gate_inventory": "multiple_testing.primary_family",
        "runtime_registry_inventory": "multiple_testing.full_family_holm",
        "runtime_claim_record": "verdict_basis",
        "runtime_statistic_record": "primary_inference_gw_qlike",
        "runtime_multiple_testing_record": "multiple_testing",
        "claim_surface_files": [
            "README.md",
            "k1709.py",
            "k1709_results.json",
            "render_readme.py",
            "test_k1709.py",
        ],
    },
    "method_contract": {
        "estimation_scheme": "fixed_rolling",
        "train_window": 250,
        "window_data_dependent": False,
        "shared_complete_case_mask": True,
        "shared_training_dates": True,
        "forward_label_embargo": True,
        "loss": "Patton QLIKE",
        "runtime_estimand": "E[QLIKE_aug - QLIKE_base]",
        "loss_differential": "loss_aug_minus_loss_base",
        "hac_kernel": "Bartlett",
        "hac_bandwidth_rule": "max(h-1, canonical_bandwidth(h,n))",
        "reference_distribution": "standard_normal",
        "estimand": "unconditional average QLIKE loss differential",
    },
    "decision_contract": {
        "gate_direction": "lower",
        "raw_p_field": "p_value_one_sided_flow_better",
        "multiplicity": "Holm",
        "family_alpha": 0.05,
        "critical_value": -1.645,
        "gate_flag_field": "passes_flow_gate",
        "holm_adjusted_p_field": "holm_adjusted_p",
        "registry_stat_field": "stat",
        "registry_stat_decimals": 4,
        "registry_raw_p_field": "p_one_sided_raw",
        "gate_count_field": "n_gate_eligible_gw_tests",
        "claim_family_count_field": "cells_in_primary_family",
        "claim_pass_count_field": "cells_passing_flow_gate",
    },
    "feature_stages": [
        {
            "id": "state_har_return",
            "role": "predictor_feature",
            "outputs": ["har_d", "har_w", "har_m", "ret", "abs_ret"],
            "memory": "finite_lag",
            "max_observations": 22,
        },
        {
            "id": "own_flow_z",
            "role": "predictor_feature",
            "outputs": ["abs_z", "z_neg"],
            "memory": "finite_lag",
            "max_observations": 21,
        },
        {
            "id": "btc_flow_z",
            "role": "predictor_feature",
            "outputs": ["abs_z_btc"],
            "memory": "finite_lag",
            "max_observations": 21,
        },
        {
            "id": "paired_log_variance_fit",
            "role": "paired_final_estimator",
            "outputs": ["forecast_base", "forecast_aug"],
            "memory": "fixed_rolling",
            "max_observations": 250,
        },
    ],
    "expected_primary_cell_count": 10,
    "primary_cells": [
        {
            "id": "primary|BTC_h1|H1_absflow|rv_gk|fl1",
            "id_components": ["primary", "BTC_h1", "H1_absflow", "rv_gk", "fl1"],
            "family": "primary",
            "base": "HAR+ctrl",
            "augmented": "H1_absflow",
            "strictly_nested": True,
            "horizon": 1,
            "feeds_gate": True,
            "base_predictors": ["har_d", "har_w", "har_m", "ret", "abs_ret"],
            "augmented_predictors": ["har_d", "har_w", "har_m", "ret", "abs_ret", "abs_z"],
            "used_stage_ids": ["state_har_return", "own_flow_z", "paired_log_variance_fit"],
        },
        {
            "id": "primary|BTC_h1|H2_asym|rv_gk|fl1",
            "id_components": ["primary", "BTC_h1", "H2_asym", "rv_gk", "fl1"],
            "family": "primary",
            "base": "HAR+ctrl",
            "augmented": "H2_asym",
            "strictly_nested": True,
            "horizon": 1,
            "feeds_gate": True,
            "base_predictors": ["har_d", "har_w", "har_m", "ret", "abs_ret"],
            "augmented_predictors": ["har_d", "har_w", "har_m", "ret", "abs_ret", "abs_z", "z_neg"],
            "used_stage_ids": ["state_har_return", "own_flow_z", "paired_log_variance_fit"],
        },
        {
            "id": "primary|BTC_h5|H1_absflow|rv_gk|fl1",
            "id_components": ["primary", "BTC_h5", "H1_absflow", "rv_gk", "fl1"],
            "family": "primary",
            "base": "HAR+ctrl",
            "augmented": "H1_absflow",
            "strictly_nested": True,
            "horizon": 5,
            "feeds_gate": True,
            "base_predictors": ["har_d", "har_w", "har_m", "ret", "abs_ret"],
            "augmented_predictors": ["har_d", "har_w", "har_m", "ret", "abs_ret", "abs_z"],
            "used_stage_ids": ["state_har_return", "own_flow_z", "paired_log_variance_fit"],
        },
        {
            "id": "primary|BTC_h5|H2_asym|rv_gk|fl1",
            "id_components": ["primary", "BTC_h5", "H2_asym", "rv_gk", "fl1"],
            "family": "primary",
            "base": "HAR+ctrl",
            "augmented": "H2_asym",
            "strictly_nested": True,
            "horizon": 5,
            "feeds_gate": True,
            "base_predictors": ["har_d", "har_w", "har_m", "ret", "abs_ret"],
            "augmented_predictors": ["har_d", "har_w", "har_m", "ret", "abs_ret", "abs_z", "z_neg"],
            "used_stage_ids": ["state_har_return", "own_flow_z", "paired_log_variance_fit"],
        },
        {
            "id": "primary|ETH_h1|H1_absflow|rv_gk|fl1",
            "id_components": ["primary", "ETH_h1", "H1_absflow", "rv_gk", "fl1"],
            "family": "primary",
            "base": "HAR+ctrl",
            "augmented": "H1_absflow",
            "strictly_nested": True,
            "horizon": 1,
            "feeds_gate": True,
            "base_predictors": ["har_d", "har_w", "har_m", "ret", "abs_ret"],
            "augmented_predictors": ["har_d", "har_w", "har_m", "ret", "abs_ret", "abs_z"],
            "used_stage_ids": ["state_har_return", "own_flow_z", "paired_log_variance_fit"],
        },
        {
            "id": "primary|ETH_h1|H2_asym|rv_gk|fl1",
            "id_components": ["primary", "ETH_h1", "H2_asym", "rv_gk", "fl1"],
            "family": "primary",
            "base": "HAR+ctrl",
            "augmented": "H2_asym",
            "strictly_nested": True,
            "horizon": 1,
            "feeds_gate": True,
            "base_predictors": ["har_d", "har_w", "har_m", "ret", "abs_ret"],
            "augmented_predictors": ["har_d", "har_w", "har_m", "ret", "abs_ret", "abs_z", "z_neg"],
            "used_stage_ids": ["state_har_return", "own_flow_z", "paired_log_variance_fit"],
        },
        {
            "id": "primary|ETH_h1|H4_plus_btc|rv_gk|fl1",
            "id_components": ["primary", "ETH_h1", "H4_plus_btc", "rv_gk", "fl1"],
            "family": "primary",
            "base": "H4_own",
            "augmented": "H4_plus_btc",
            "strictly_nested": True,
            "horizon": 1,
            "feeds_gate": True,
            "base_predictors": ["har_d", "har_w", "har_m", "ret", "abs_ret", "abs_z"],
            "augmented_predictors": ["har_d", "har_w", "har_m", "ret", "abs_ret", "abs_z", "abs_z_btc"],
            "used_stage_ids": ["state_har_return", "own_flow_z", "btc_flow_z", "paired_log_variance_fit"],
        },
        {
            "id": "primary|ETH_h5|H1_absflow|rv_gk|fl1",
            "id_components": ["primary", "ETH_h5", "H1_absflow", "rv_gk", "fl1"],
            "family": "primary",
            "base": "HAR+ctrl",
            "augmented": "H1_absflow",
            "strictly_nested": True,
            "horizon": 5,
            "feeds_gate": True,
            "base_predictors": ["har_d", "har_w", "har_m", "ret", "abs_ret"],
            "augmented_predictors": ["har_d", "har_w", "har_m", "ret", "abs_ret", "abs_z"],
            "used_stage_ids": ["state_har_return", "own_flow_z", "paired_log_variance_fit"],
        },
        {
            "id": "primary|ETH_h5|H2_asym|rv_gk|fl1",
            "id_components": ["primary", "ETH_h5", "H2_asym", "rv_gk", "fl1"],
            "family": "primary",
            "base": "HAR+ctrl",
            "augmented": "H2_asym",
            "strictly_nested": True,
            "horizon": 5,
            "feeds_gate": True,
            "base_predictors": ["har_d", "har_w", "har_m", "ret", "abs_ret"],
            "augmented_predictors": ["har_d", "har_w", "har_m", "ret", "abs_ret", "abs_z", "z_neg"],
            "used_stage_ids": ["state_har_return", "own_flow_z", "paired_log_variance_fit"],
        },
        {
            "id": "primary|ETH_h5|H4_plus_btc|rv_gk|fl1",
            "id_components": ["primary", "ETH_h5", "H4_plus_btc", "rv_gk", "fl1"],
            "family": "primary",
            "base": "H4_own",
            "augmented": "H4_plus_btc",
            "strictly_nested": True,
            "horizon": 5,
            "feeds_gate": True,
            "base_predictors": ["har_d", "har_w", "har_m", "ret", "abs_ret", "abs_z"],
            "augmented_predictors": ["har_d", "har_w", "har_m", "ret", "abs_ret", "abs_z", "abs_z_btc"],
            "used_stage_ids": ["state_har_return", "own_flow_z", "btc_flow_z", "paired_log_variance_fit"],
        },
    ],
}


# ---------------------------------------------------------------------------
# 0. Test registry — the single source of the multiple-testing family (C6)
# ---------------------------------------------------------------------------
@dataclass
class TestRecord:
    """One statistical test. The family is DERIVED from this list, never hand-listed.

    v1 hand-enumerated "EVERY DM test" and silently missed the 8 smearing tests.
    Every test in this study now registers itself here, and the multiple-testing
    families are built by filtering this registry.

    `feeds_gate` is the honest bit: only tests whose inference is valid for a
    nested comparison are allowed to reach the verdict. Raw Diebold-Mariano
    records are registered with feeds_gate=False so they show up in the audit
    trail without contaminating the claim.

    `p_one_sided` is stored RAW (unrounded). v1 fed 4-decimal rounded p-values
    into Holm.

    `bounded_memory` records whether the FORECASTING METHOD behind this test has
    the bounded estimator memory Giacomini-White assumes. It is a property of the
    whole method, not of the final regression: a cell whose regressor is itself
    built by an expanding-window fit does not have it, even though every column
    is strictly backward-looking. Flagging it here is what lets the write-up stop
    claiming, in one blanket sentence, that every registered test is a
    bounded-memory test. Such a record remains visible but is made gate-ineligible
    from provenance before its p-value is inspected.
    """

    family: str
    cell: str
    asset: str
    horizon: int
    base: str
    alt: str
    inference: str
    estimand: str
    scheme: str
    stat: float
    p_one_sided: float
    feeds_gate: bool
    qlike_improve_pct: float | None = None
    n: int | None = None
    bounded_memory: bool = True


REGISTRY: list[TestRecord] = []

# Paired QLIKE loss streams, keyed by cell. Kept so a confidence bound can be
# re-inverted at any alpha AFTER the family size is known (the Bonferroni level
# depends on how many cells there turned out to be). Never serialized.
LOSS_CACHE: dict[str, tuple[np.ndarray, np.ndarray, int]] = {}


def register(rec: TestRecord) -> TestRecord:
    REGISTRY.append(rec)
    return rec


def qlike_gain_upper_bound_from_cell(cell: str, alpha: float) -> float | None:
    la, lb, h = LOSS_CACHE[cell]
    return qlike_gain_upper_bound(la, lb, h, alpha=alpha)


def _assert_unique_cell(
    family: str,
    p,
    alt: str,
    smearing: str,
    train_window: int | None,
    variant: str,
) -> str:
    """Build the cell key and refuse to let two cells share one.

    The key joins the registry, the loss cache and the verdict. When it was just
    `{asset}_h{h}_{alt}`, the same string named the primary BTC h=1 cell AND its
    rv-proxy, flow-lag, threshold and window variants -- so the dict that carried
    exclusion statistics into the verdict silently kept whichever cell was written
    LAST. The primary family was being adjudicated with a robustness cell's
    numbers. Uniqueness is now a precondition, not a hope.
    """
    parts = [family, f"{p.asset}_h{p.horizon}", alt, p.rv_col, f"fl{p.flow_lag}"]
    if smearing != "own":
        parts.append(smearing)
    if train_window != GW_TRAIN_WINDOW:
        parts.append(f"tw{train_window}")
    if variant:
        parts.append(variant)
    cell = "|".join(parts)
    if cell in LOSS_CACHE:
        raise AssertionError(
            f"duplicate cell key {cell!r}: two comparisons would collide in the "
            "registry/loss-cache join. Pass a distinguishing `variant=`."
        )
    return cell


def holm(pvals: list[float]) -> list[float]:
    """Holm step-down. Takes RAW p-values; rounding happens only at serialization."""
    m = len(pvals)
    if m == 0:
        return []
    order = np.argsort(pvals)
    adj = np.empty(m)
    running = 0.0
    for rank, idx in enumerate(order):
        running = max(running, (m - rank) * pvals[idx])
        adj[idx] = min(running, 1.0)
    return [float(a) for a in adj]


# ---------------------------------------------------------------------------
# 1. US equity session calendar (C3)
# ---------------------------------------------------------------------------
def us_equity_sessions(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    """NYSE session days over [start, end].

    Farside keeps a row for US market holidays with every fund column showing a
    dash and `Total` showing 0.0. `sum(skipna=True)` over an all-NaN row is 0.0,
    so the parser cross-check cannot see it either: the holiday looks exactly
    like a genuine zero-flow day. Those fake zeros then enter the 20-flow-day
    rolling sd that scales every shock.

    A "flow day" is by construction a day the ETFs could trade, i.e. an NYSE
    session. Anything else is MISSING, not zero.
    """
    cal = xcals.get_calendar("XNYS")
    sess = cal.sessions_in_range(
        pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    )
    idx = pd.DatetimeIndex(sess)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx.normalize()


def filter_to_sessions(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Keep only NYSE session rows; report exactly what was dropped.

    Split out of `fetch_flows` so it can be tested without hitting the network:
    a data-integrity rule that only runs behind an HTTP call is a rule nobody
    ever tests.
    """
    sessions = us_equity_sessions(df.index.min(), df.index.max())
    is_session = df.index.isin(sessions)
    dropped = df.index[~is_session]
    detail = [
        {
            "date": str(d.date()),
            "weekday": d.day_name(),
            "farside_total_musd": float(df.loc[d, "flow"]),
            "all_fund_columns_dash": (
                bool(df.loc[d, "all_dash"]) if "all_dash" in df.columns else None
            ),
        }
        for d in dropped
    ]
    diag = {
        "n_nonsession_rows_dropped": len(detail),
        "n_nonsession_rows_with_nonzero_total": int(
            (df.loc[~is_session, "flow"].abs() > 1e-9).sum()
        ),
        "nonsession_rows_dropped": detail,
    }
    keep = df[is_session]
    if "all_dash" in keep.columns:
        keep = keep.drop(columns=["all_dash"])
    return keep, diag


# ---------------------------------------------------------------------------
# 2. Farside flow parsing (the traps live here)
# ---------------------------------------------------------------------------
def _parse_money(x) -> float:
    """Farside cell -> float ($M).

    Traps handled:
      '(95.1)'  -> -95.1      negative flows are written in parentheses
      '(27,332)'-> -27332.0   thousands separators
      '-' / '–' -> NaN        fund not trading / no data  (NOT zero)
      '0.0'     -> 0.0        a genuine zero flow  (NOT missing)
    """
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return np.nan
    s = str(x).strip()
    # em/en dash and bare hyphen mean "no data", not zero.
    if s in {"", "-", "–", "—", "nan", "NaN"}:
        return np.nan
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "").replace("$", "").replace("*", "")
    try:
        v = float(s)
    except ValueError:
        return np.nan
    return -v if neg else v


def fetch_flows(asset: str) -> tuple[pd.DataFrame, dict]:
    """Download and parse the Farside all-data flow table for `asset`."""
    resp = requests.get(FARSIDE[asset], headers=UA, timeout=60)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    raw = max(tables, key=lambda t: t.shape[0] * t.shape[1])
    n_raw = len(raw)

    # ETH ships a MultiIndex header (issuer / ticker / fee). Keep the ticker row.
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [
            c[1] if not str(c[1]).startswith("Unnamed") else c[0] for c in raw.columns
        ]
    raw.columns = [str(c).strip() for c in raw.columns]
    date_col = raw.columns[0]
    raw = raw.rename(columns={date_col: "Date"})

    # Drop the 'Total' footer row and the 'Seed' row (seed capital, not daily flow).
    lbl = raw["Date"].astype(str).str.strip()
    n_total_rows = int(lbl.str.fullmatch("Total", case=False).sum())
    n_seed_rows = int(lbl.str.fullmatch("Seed", case=False).sum())
    raw = raw[~lbl.str.fullmatch("Total|Seed", case=False)]

    dt = pd.to_datetime(raw["Date"], format="%d %b %Y", errors="coerce")
    n_unparsed = int(dt.isna().sum())
    raw = raw.assign(date=dt).dropna(subset=["date"])

    fund_cols = [c for c in raw.columns if c not in {"Date", "date", "Total"}]
    parsed = raw[fund_cols].map(_parse_money)
    total = raw["Total"].map(_parse_money)

    # Parser self-check: Farside's own Total must equal the sum of the fund
    # columns (NaN = fund not trading = contributes nothing). A mismatch means
    # the paren/comma/dash handling above is wrong -- fail loud, do not proceed.
    #
    # NOTE this check is BLIND to the market-holiday trap: an all-dash row sums
    # to 0.0 and Farside's own Total also reads 0.0, so the residual is 0. That
    # is precisely why the session-calendar filter below is a separate layer.
    recomputed = parsed.sum(axis=1, skipna=True)
    resid = (total - recomputed).abs()
    max_resid = float(resid.max())
    if max_resid > 1.0:  # $1M tolerance for Farside's own rounding
        worst = resid.idxmax()
        raise AssertionError(
            f"[{asset}] flow parser failed cross-check: max |Total - sum(funds)| = "
            f"{max_resid:.3f} $M on {raw.loc[worst, 'date'].date()}"
        )

    # Gross churn = sum of |fund-level flow|. Net flow can be ~0 while one issuer
    # creates and another redeems heavily -- that is a real liquidity event that
    # the NET series is blind to. Keeping it lets us test whether the null is an
    # artifact of netting (Warther 1995: only flow INNOVATIONS should inform).
    gross = parsed.abs().sum(axis=1, skipna=True)
    all_dash = parsed.isna().all(axis=1)

    df = pd.DataFrame(
        {"flow": total.values, "gross": gross.values, "all_dash": all_dash.values},
        index=pd.DatetimeIndex(raw["date"].values),
    )
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df = df.dropna(subset=["flow"])

    df, session_diag = filter_to_sessions(df)
    dropped_detail = session_diag["nonsession_rows_dropped"]
    n_dropped_nonzero = session_diag["n_nonsession_rows_with_nonzero_total"]

    diag = {
        "source_url": FARSIDE[asset],
        "raw_rows": n_raw,
        "dropped_total_rows": n_total_rows,
        "dropped_seed_rows": n_seed_rows,
        "dropped_unparseable_dates": n_unparsed,
        "session_calendar": "XNYS (exchange_calendars)",
        "n_nonsession_rows_dropped": len(dropped_detail),
        "n_nonsession_rows_with_nonzero_total": n_dropped_nonzero,
        "nonsession_rows_dropped": dropped_detail,
        "session_filter_note": (
            "Farside emits a row for every US market holiday with all fund "
            "columns dashed and Total = 0.0. skipna summation makes the parser "
            "cross-check read 0.0 - 0.0 = 0, so it cannot detect them. These are "
            "MISSING flow days, not genuine zero-flow days, and they were "
            "polluting the 20-flow-day rolling sd used to scale every shock."
        ),
        "n_obs": int(len(df)),
        "date_min": str(df.index.min().date()),
        "date_max": str(df.index.max().date()),
        "parser_crosscheck_max_abs_resid_musd": round(max_resid, 4),
        "total_flow_musd": {
            "mean": round(float(df["flow"].mean()), 3),
            "std": round(float(df["flow"].std()), 3),
            "min": round(float(df["flow"].min()), 3),
            "max": round(float(df["flow"].max()), 3),
            "median": round(float(df["flow"].median()), 3),
        },
        "share_negative": round(float((df["flow"] < 0).mean()), 4),
        "share_exact_zero_on_session_days": round(float((df["flow"] == 0).mean()), 4),
        "n_fund_columns": len(fund_cols),
    }
    return df, diag


# ---------------------------------------------------------------------------
# 3. Realized volatility proxies
# ---------------------------------------------------------------------------
def fetch_rv(asset: str) -> tuple[pd.DataFrame, dict]:
    """Calendar-daily (UTC) RV proxies for `asset`.

    Primary  : Garman-Klass variance from OHLC (spans the full sample).
    Robust 1 : true realized variance from 24 hourly log returns (2024-07-15+).
    Robust 2 : squared daily close-to-close log return.

    Note on the hourly RV: for a 24/7 market there is no session gap, so the
    return spanning the UTC midnight boundary is a genuine return, not an
    overnight jump. We therefore diff the *continuous* hourly series and assign
    each return to the UTC date of its end stamp (24 returns/day). This is the
    opposite of the 2026-07-11 0050.TW fix, and deliberately so: that market
    closes overnight, this one does not. Days without exactly 24 returns are
    dropped to avoid a scaling bias.
    """
    px = yf.download(
        TICKER[asset], start="2023-06-01", interval="1d", progress=False, auto_adjust=False
    )
    if isinstance(px.columns, pd.MultiIndex):
        px.columns = px.columns.get_level_values(0)
    px = px[["Open", "High", "Low", "Close"]].dropna()
    px.index = pd.DatetimeIndex(px.index).tz_localize(None).normalize()

    # (a) Drop the still-open current UTC day. Yahoo serves a PARTIAL bar for
    #     today, whose High/Low have not finished widening -- it systematically
    #     understates GK variance. Only fully-closed UTC days may enter.
    today_utc = pd.Timestamp.utcnow().tz_localize(None).normalize()
    n_open_bar = int((px.index >= today_utc).sum())
    px = px[px.index < today_utc]

    # (b) Reindex onto a COMPLETE daily calendar. BTC/ETH trade 24/7, so every
    #     calendar day should exist -- but Yahoo does drop days (2026-07-13 was
    #     missing at the time of writing). Without this, `.shift(1)` would shift
    #     by ROW POSITION, not by one calendar day, and a gap would silently turn
    #     a t+1 target into a t+2 target. Missing days become NaN and are dropped
    #     from the panel, instead of compressing the timeline.
    full = pd.date_range(px.index.min(), px.index.max(), freq="D")
    n_missing = int(len(full.difference(px.index)))
    missing_days = [str(d.date()) for d in full.difference(px.index)]
    px = px.reindex(full)

    ln_hl = np.log(px["High"] / px["Low"])
    ln_co = np.log(px["Close"] / px["Open"])
    gk = 0.5 * ln_hl**2 - (2 * np.log(2) - 1) * ln_co**2
    park = ln_hl**2 / (4 * np.log(2))
    ret = np.log(px["Close"]).diff()

    out = pd.DataFrame(
        {"rv_gk": gk, "rv_park": park, "rv_r2": ret**2, "ret": ret}, index=px.index
    )

    # --- hourly true RV -----------------------------------------------------
    hr = yf.download(
        TICKER[asset], interval="1h", period="730d", progress=False, auto_adjust=False
    )
    n_hourly_days = 0
    if len(hr):
        if isinstance(hr.columns, pd.MultiIndex):
            hr.columns = hr.columns.get_level_values(0)
        close = hr["Close"].dropna().sort_index()
        r = np.log(close).diff().dropna()               # continuous: 24/7, no gap
        day = pd.DatetimeIndex(r.index).tz_convert("UTC").tz_localize(None).normalize()
        grp = pd.DataFrame({"r2": r.values**2, "day": day}).groupby("day")
        rv_h = grp["r2"].sum()
        cnt = grp["r2"].size()
        rv_h = rv_h[cnt == 24]                          # complete UTC days only
        n_hourly_days = int(len(rv_h))
        out["rv_hourly"] = rv_h.reindex(out.index)
    else:
        out["rv_hourly"] = np.nan

    neg_gk = int((out["rv_gk"] < 0).sum())
    # QLIKE has a -log(actual) term, so a near-zero "actual" blows it up. Track
    # how many observations each proxy floors: r^2 is a chi^2(1) proxy and hits
    # near-zero on quiet days, which is one reason it is a NOISY variance target
    # and is reported only as robustness, never as the headline.
    clipped = {c: int((out[c] < EPS).sum()) for c in ("rv_gk", "rv_park", "rv_r2", "rv_hourly")}
    for c in ("rv_gk", "rv_park", "rv_r2", "rv_hourly"):
        out[c] = out[c].clip(lower=EPS)

    diag = {
        "ticker": TICKER[asset],
        "n_daily_obs": int(len(out)),
        "date_min": str(out.index.min().date()),
        "date_max": str(out.index.max().date()),
        "n_negative_gk_clipped": neg_gk,
        "n_open_partial_bars_dropped": n_open_bar,
        "n_missing_calendar_days_reindexed": n_missing,
        "missing_calendar_days": missing_days,
        "n_obs_floored_at_eps_by_proxy": clipped,
        "qlike_noise_note": (
            "r^2 is a chi^2(1) variance proxy: its QLIKE level runs ~7x that of "
            "hourly RV, so it is reported as robustness only."
        ),
        "n_hourly_complete_days": n_hourly_days,
        "hourly_coverage_start": (
            str(out["rv_hourly"].dropna().index.min().date())
            if out["rv_hourly"].notna().any()
            else None
        ),
        "ann_vol_gk_pct": round(float(np.sqrt(out["rv_gk"].mean() * 365) * 100), 2),
        "corr_gk_vs_hourly": (
            round(
                float(np.log(out[["rv_gk", "rv_hourly"]].dropna()).corr().iloc[0, 1]), 4
            )
            if out["rv_hourly"].notna().sum() > 30
            else None
        ),
    }
    return out, diag


# ---------------------------------------------------------------------------
# 4. Flow features — computed ONCE, reused by every panel
# ---------------------------------------------------------------------------
@dataclass
class FlowFeatures:
    """Flow-derived regressors, indexed by FLOW DAY (= NYSE session).

    These depend only on the flow series, never on RV, so they are computed once
    and reused. That matters for the power simulation, which rebuilds the RV side
    thousands of times: recomputing the rolling AR(5) each rep would dominate the
    runtime and, worse, tempt a divergent panel-construction path.
    """

    flow: pd.Series
    z: pd.Series
    z_unexp: pd.Series
    z_gross: pd.Series | None = None


def flow_zscore(flow: pd.Series) -> pd.Series:
    """Scale each flow by the sd of the previous Z_WINDOW *flow days*.

    `.shift(1)` on the rolling sd keeps the scaler strictly backward-looking:
    z_t = flow_t / sd(flow_{t-20..t-1}), so nothing on day t enters its own
    denominator. The window is indexed by flow days (weekends and US market
    holidays carry no flow), which is why this is computed BEFORE reindexing
    onto the 24/7 crypto calendar.
    """
    sd_prior = flow.rolling(Z_WINDOW).std().shift(1)
    return flow / sd_prior


def ar_residual(flow: pd.Series, p: int = 5) -> pd.Series:
    """Rolling AR(p) forecast error of `flow` -- the 'surprise' in each day's flow.

    The AR is refitted every day on a STRICTLY PRIOR window (targets f[p:i], so
    day i's own value never enters its own fit). The design matrix columns are
    ordered [lag1, lag2, ..., lagp], so the prediction vector must be
    f[i-1], f[i-2], ..., f[i-p] -- the reversed slice below produces exactly
    that. Getting this ordering wrong silently multiplies the lag-p coefficient
    by the lag-1 value; `test_unexpected_flow_ar5_lag_ordering` guards it.
    """
    f = flow.to_numpy(float)
    n = len(f)
    resid = np.full(n, np.nan)
    for i in range(Z_WINDOW + p, n):
        y = f[p:i]                                   # targets strictly before i
        X = np.column_stack([f[p - k : i - k] for k in range(1, p + 1)])
        if len(y) < 40:
            continue
        Xc = np.column_stack([np.ones(len(y)), X])
        beta = np.linalg.lstsq(Xc, y, rcond=None)[0]
        lags = f[i - 1 : i - p - 1 : -1] if i - p - 1 >= 0 else f[i - 1 :: -1][:p]
        resid[i] = f[i] - float(np.r_[1.0, lags] @ beta)   # surprise on day i
    return pd.Series(resid, index=flow.index)


def make_flow_features(flow: pd.DataFrame) -> FlowFeatures:
    """Warther (1995): only the UNEXPECTED component of flow should carry news.

    Flow is strongly autocorrelated, so raw net flow is largely predictable from
    its own past. We strip that out with the rolling AR(5) and z-score the
    residual by its own strictly-prior rolling sd. If our null were merely an
    artifact of feeding the model the *predictable* part of flow, this variable
    would rescue it.
    """
    # CAVEAT (Codex, rev1 review). This AR(5) refits on an EXPANDING window of flow
    # history. The regressor is still strictly backward-looking -- day i's own value
    # never enters its own fit, so there is no lookahead -- but the FORECASTING
    # METHOD that uses `z_unexp` therefore does not have bounded estimator memory.
    # GW's limiting experiment formally wants it to. The 10 primary cells do not use
    # this column at all; only the `flow_transform/unexpected_z` robustness cell
    # does, and its GW p-value is reported with that caveat attached rather than
    # being quietly counted as a bounded-memory test.
    r = ar_residual(flow["flow"], p=5)
    return FlowFeatures(
        flow=flow["flow"],
        z=flow_zscore(flow["flow"]),
        z_unexp=r / r.rolling(Z_WINDOW).std().shift(1),
        z_gross=flow_zscore(flow["gross"]) if "gross" in flow.columns else None,
    )


# ---------------------------------------------------------------------------
# 5. Panel construction — the alignment layer
# ---------------------------------------------------------------------------
@dataclass
class Panel:
    df: pd.DataFrame           # indexed by TARGET date tau
    rv_col: str
    horizon: int
    asset: str
    state_lag: int = STATE_LAG
    flow_lag: int = 1


STATE_COLS = ["har_d", "har_w", "har_m", "ret", "abs_ret"]
FLOW_COLS = ["flow", "z", "z_unexp", "z_gross", "z_btc"]


def assert_calendar_is_complete(idx: pd.DatetimeIndex, label: str) -> None:
    """Guard the assumption every `.shift()` in this file relies on.

    `.shift(k)` moves by ROW POSITION. It equals "k calendar days back" only if
    the index is a complete, sorted, duplicate-free daily range. Codex's review
    showed `assert_no_lookahead` alone could not prove this: it re-checks the
    same src_date the shift itself produced. This checks the PRECONDITION, before
    any rolling or shifting happens.
    """
    if not idx.is_monotonic_increasing:
        raise AssertionError(f"[{label}] calendar index is not sorted")
    if idx.has_duplicates:
        dupes = idx[idx.duplicated()][:5]
        raise AssertionError(f"[{label}] duplicate calendar dates: {list(dupes)}")
    full = pd.date_range(idx.min(), idx.max(), freq="D")
    if len(full) != len(idx) or not full.equals(pd.DatetimeIndex(idx)):
        missing = full.difference(idx)[:5]
        raise AssertionError(
            f"[{label}] calendar has {len(full) - len(idx)} hole(s); "
            f"`.shift()` would move by row position, not by one day. "
            f"First missing: {list(missing)}"
        )


def build_panel(
    rv: pd.DataFrame,
    ff: FlowFeatures,
    rv_col: str,
    horizon: int,
    asset: str,
    flow_lag: int = 1,
    state_lag: int = STATE_LAG,
    btc_z: pd.Series | None = None,
) -> Panel:
    """Assemble the design matrix, indexed by the *target* date tau.

    C4 fix. v1 had a single `pub_lag` that shifted EVERYTHING, so the
    conservative "flow is only published at the end of day t+1" run also pushed
    the HAR and return controls back to t-1 -- but RV_{t+1} and ret_{t+1} are
    obviously known by then. That handicapped the baseline and made the
    robustness run answer a question nobody asked.

    Now:
      state_lag : RV/return controls. ALWAYS 1 -- yesterday's realized
                  volatility is known today, whatever the flow vendor does.
      flow_lag  : 1 (baseline: flow_t usable from the end of day t)
                  2 (conservative: flow_t only usable from the end of day t+1)
    """
    assert_calendar_is_complete(pd.DatetimeIndex(rv.index), f"{asset} rv")
    cal = rv.copy()

    # --- HAR features, computed on calendar days, as of the END of each day ---
    lr = np.log(cal[rv_col])
    cal["har_d"] = lr
    cal["har_w"] = lr.rolling(HAR_W).mean()
    cal["har_m"] = lr.rolling(HAR_M).mean()
    cal["abs_ret"] = cal["ret"].abs()

    # --- flow shocks, reindexed from flow-day space onto the 24/7 calendar ---
    cal["flow"] = ff.flow.reindex(cal.index)     # NaN on non-flow calendar days
    cal["z"] = ff.z.reindex(cal.index)
    cal["z_unexp"] = ff.z_unexp.reindex(cal.index)
    if ff.z_gross is not None:
        cal["z_gross"] = ff.z_gross.reindex(cal.index)
    if btc_z is not None:
        cal["z_btc"] = btc_z.reindex(cal.index)

    # --- the two visible lags ------------------------------------------------
    state = [c for c in STATE_COLS if c in cal.columns]
    flow_c = [c for c in FLOW_COLS if c in cal.columns]
    day = pd.Series(cal.index, index=cal.index)

    X = cal[state].shift(state_lag)
    X[flow_c] = cal[flow_c].shift(flow_lag)
    X["state_src_date"] = day.shift(state_lag)
    X["flow_src_date"] = day.shift(flow_lag)

    # --- target: average RV over the next `horizon` calendar days ------------
    # tau is the FIRST day of the target window; the window is [tau, tau+h-1].
    fwd = cal[rv_col].rolling(horizon).mean().shift(-(horizon - 1))
    X["y"] = fwd
    X["y_end_date"] = day.shift(-(horizon - 1))

    # Derived flow-shock regressors
    X["abs_z"] = X["z"].abs()
    X["z_neg"] = X["abs_z"] * (X["z"] < 0)     # extra loading on redemptions
    X["z_signed"] = X["z"]                     # directional (not magnitude)
    X["z_sq"] = X["z"] ** 2                    # convex in shock size
    X["abs_z_unexp"] = X["z_unexp"].abs()      # Warther: unexpected component
    if "z_gross" in X.columns:
        X["abs_z_gross"] = X["z_gross"].abs()  # gross churn, blind to netting
    if btc_z is not None:
        X["abs_z_btc"] = X["z_btc"].abs()

    X["dow_src"] = X["flow_src_date"].dt.dayofweek   # 4 = Friday flow day
    panel = X.dropna(subset=["y", "har_m", "z", "y_end_date"])
    return Panel(panel, rv_col, horizon, asset, state_lag=state_lag, flow_lag=flow_lag)


def assert_no_lookahead(p: Panel) -> None:
    """Re-derive the timing guarantee from the data itself.

    Checks, per Codex's review:
      (1) state gap == state_lag exactly. `<` would be lookahead; `>` would mean
          `.shift()` moved by row position across a calendar hole, silently
          turning a t+1 target into a t+2 target. An inequality check would miss
          the second, which is exactly how the 2026-07-13 Yahoo gap slipped past.
      (2) flow gap == flow_lag exactly, verified SEPARATELY. v1 only had one
          src_date, so it could not have caught a state/flow lag mixup.
      (3) the target window closes exactly h-1 days after it opens -- not merely
          "at or after". A calendar hole inside the rolling target window would
          stretch a 5-day window across 6 calendar days and the old `>=` check
          would have waved it through.
    """
    d = p.df
    for src, lag, name in (
        ("state_src_date", p.state_lag, "state"),
        ("flow_src_date", p.flow_lag, "flow"),
    ):
        gap = (d.index - d[src]).dt.days
        if (gap != lag).any():
            bad = d.loc[gap != lag]
            raise AssertionError(
                f"[{p.asset} h={p.horizon}] {len(bad)} rows have a {name} "
                f"source->target gap != {lag} day(s) "
                f"(min={gap.min()}, max={gap.max()}). First offender: "
                f"target={bad.index[0].date()} src={bad[src].iloc[0].date()}"
            )
    span = (d["y_end_date"] - d.index).dt.days
    if (span != p.horizon - 1).any():
        bad = d.loc[span != p.horizon - 1]
        raise AssertionError(
            f"[{p.asset} h={p.horizon}] {len(bad)} target windows do not span "
            f"exactly {p.horizon} calendar days (min={span.min()}, max={span.max()})"
        )


# ---------------------------------------------------------------------------
# 6. Estimation
# ---------------------------------------------------------------------------
SPECS: dict[str, list[str]] = {
    "HAR":        ["har_d", "har_w", "har_m"],
    "HAR+ctrl":   ["har_d", "har_w", "har_m", "ret", "abs_ret"],
    "H1_absflow": ["har_d", "har_w", "har_m", "ret", "abs_ret", "abs_z"],
    "H2_asym":    ["har_d", "har_w", "har_m", "ret", "abs_ret", "abs_z", "z_neg"],
    "H4_own":     ["har_d", "har_w", "har_m", "ret", "abs_ret", "abs_z"],
    "H4_plus_btc": [
        "har_d", "har_w", "har_m", "ret", "abs_ret", "abs_z", "abs_z_btc",
    ],
}


def _ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.linalg.lstsq(np.column_stack([np.ones(len(X)), X]), y, rcond=None)[0]


def _hac_se(X: np.ndarray, y: np.ndarray, beta: np.ndarray, lag: int) -> np.ndarray:
    """Newey-West standard errors (needed: overlapping targets when h>1)."""
    Xc = np.column_stack([np.ones(len(X)), X])
    u = y - Xc @ beta
    XtX_inv = np.linalg.pinv(Xc.T @ Xc)
    S = (Xc * u[:, None]).T @ (Xc * u[:, None])
    for L in range(1, lag + 1):
        w = 1 - L / (lag + 1)
        A = (Xc[L:] * u[L:, None]).T @ (Xc[:-L] * u[:-L, None])
        S += w * (A + A.T)
    V = XtX_inv @ S @ XtX_inv
    return np.sqrt(np.maximum(np.diag(V), 0))


def canonical_bandwidth(h: int, n: int) -> int:
    """The repo's canonical HAC bandwidth (see .claude/rules/experiments.md).

    `h-1` alone degenerates to ZERO at h=1, i.e. no HAC at all, which is the
    K1655 trap. Every long-run variance in this file uses max(h-1, this).
    """
    return max(1, min(int(np.ceil(h ** (1 / 3) * n ** (1 / 3))), n // 4))


def in_sample(p: Panel, spec: str) -> dict:
    cols = SPECS[spec]
    d = p.df.dropna(subset=cols)
    X = d[cols].to_numpy(float)
    y = np.log(d["y"].to_numpy(float))
    beta = _ols(X, y)
    lag = max(p.horizon - 1, canonical_bandwidth(p.horizon, len(d)))
    se = _hac_se(X, y, beta, lag)
    names = ["const"] + cols
    yhat = np.column_stack([np.ones(len(X)), X]) @ beta
    ss = 1 - np.sum((y - yhat) ** 2) / np.sum((y - y.mean()) ** 2)
    return {
        "spec": spec,
        "n": int(len(d)),
        "r2": round(float(ss), 4),
        "hac_lag": int(lag),
        "coef": {
            nm: {"beta": round(float(b), 5), "t": round(float(b / s) if s > 0 else 0.0, 3)}
            for nm, b, s in zip(names, beta, se)
        },
    }


# ---------------------------------------------------------------------------
# 7. Paired fixed-window OOS — the estimator GW requires (C1)
# ---------------------------------------------------------------------------
@dataclass
class PairedOOS:
    actual: np.ndarray
    pred_base: np.ndarray
    pred_aug: np.ndarray
    origins: pd.DatetimeIndex
    audit: dict = field(default_factory=dict)


def _string_sequence_sha256(values) -> str:
    """Stable digest for an ordered provenance sequence, never for estimates."""
    payload = json.dumps(
        [str(value) for value in values], ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _date_index_sha256(values) -> str:
    dates = pd.DatetimeIndex(values).strftime("%Y-%m-%d")
    return _string_sequence_sha256(dates)


def paired_oos(
    p: Panel,
    base: str,
    alt: str,
    train_window: int | None = GW_TRAIN_WINDOW,
    smearing: str = "own",
) -> PairedOOS:
    """Both models, one estimation window, identical training dates.

    `train_window=None` reproduces v1's EXPANDING window. It is retained for one
    purpose only: to show, in the results file, what the design change did to the
    statistic. Expanding-window losses never feed a verdict here -- see
    `gw_unconditional_dm` for why the scheme is the whole ballgame.

    Why fixed and not expanding (this is the whole point of the C1 fix):
    Giacomini-White (2006) tests equal UNCONDITIONAL predictive ability of
    FORECASTING METHODS here -- estimation error included -- and its asymptotics
    need the estimator to have bounded memory. An expanding window does not. v1
    ran an expanding window and then applied a test whose null assumed otherwise.

    Both specs are fit on the AUGMENTED model's complete-case mask, so they see
    the exact same rows, the exact same targets, and the exact same embargo. That
    common sample is part of the nested comparison, not a cosmetic detail.

    Embargo: with overlapping h-day targets, "every row before i" would let the
    model train on a label window that overlaps the forecast day. A training row
    is eligible at origin i only once its whole label window has closed:
    `y_end_date < origin_i`.

    Smearing (log -> variance level). The augmented spec has more parameters ->
    lower training residual variance -> a smaller exp(s^2/2) multiplier -> lower
    variance forecasts. QLIKE is asymmetric, so this channel could in principle
    bias the UNCONDITIONAL average QLIKE comparison against flow and make a
    negative finding look stronger. It cannot manufacture a conditional claim,
    and this study reports an INCONCLUSIVE verdict rather than a null.
      "own"    -- each spec uses its own s^2  (primary)
      "none"   -- no smearing at all, forecast = exp(mu)
      "shared" -- both specs use the BASELINE's s^2, neutralising the channel
    The dof correction (N - k) is what makes E[s^2] spec-invariant under the
    null: with RSS/N a richer spec gets a mechanically smaller s^2 even when its
    extra regressor is pure noise.
    """
    if not set(SPECS[base]) < set(SPECS[alt]):
        raise ValueError(
            f"GW requires strict nesting: {base} must be a proper subset of {alt}"
        )
    if smearing not in {"own", "none", "shared"}:
        raise ValueError(f"unknown smearing mode: {smearing}")

    burn_in = GW_TRAIN_WINDOW if train_window is None else train_window
    cols = list(dict.fromkeys([*SPECS[alt], "y", "y_end_date"]))
    d = p.df.dropna(subset=cols)
    if len(d) < burn_in + GW_MIN_LOSSES:
        return PairedOOS(np.array([]), np.array([]), np.array([]), pd.DatetimeIndex([]))

    Xb = np.column_stack([np.ones(len(d)), d[SPECS[base]].to_numpy(float)])
    Xa = np.column_stack([np.ones(len(d)), d[SPECS[alt]].to_numpy(float)])
    yraw = d["y"].to_numpy(float)
    yfit = np.log(np.clip(yraw, VAR_FLOOR, None))
    origins = d.index
    y_end = d["y_end_date"].to_numpy()

    if not pd.Series(y_end).is_monotonic_increasing:
        raise AssertionError(f"[{p.asset}] y_end_date is not monotonic; searchsorted invalid")

    n_clip = 0

    def fit(x_all, row_dates, start, end, i, s2_override=None):
        nonlocal n_clip
        xtr, ytr = x_all[start:end], yfit[start:end]
        training_schedule_sha256 = _date_index_sha256(row_dates[start:end])
        # Normal equations, not SVD. The power simulation re-runs this loop
        # ~16k times, and an SVD per origin makes that a half-hour job. There is
        # exactly ONE estimation path in this file -- the simulation must not be
        # allowed to quietly use a different estimator than the headline result.
        # `test_normal_equations_match_lstsq` pins this to the SVD solution.
        gram = xtr.T @ xtr
        try:
            beta = np.linalg.solve(gram, xtr.T @ ytr)
        except np.linalg.LinAlgError:
            beta = np.linalg.lstsq(xtr, ytr, rcond=None)[0]
        resid = ytr - xtr @ beta
        # dof-corrected: E[s2] is then spec-invariant under the null
        s2 = float(resid @ resid / max(len(ytr) - x_all.shape[1], 1))
        mu = float(x_all[i] @ beta)
        # Trap runaway extrapolation BEFORE exponentiating: a regressor far
        # outside its training range can otherwise produce an astronomical
        # variance forecast and let two origins dominate the whole QLIKE mean.
        # Bounds come from training values only and are applied identically to
        # both specs, so neither is advantaged. `n_clipped` reports how often it
        # binds -- if that is 0, this is a pure no-op safety net.
        lo, hi = float(ytr.min()) - 1.0, float(ytr.max()) + 1.0
        if not (lo <= mu <= hi):
            n_clip += 1
            mu = min(max(mu, lo), hi)
        use = s2 if s2_override is None else s2_override
        if smearing == "none":
            return math.exp(mu), s2, training_schedule_sha256, len(ytr)
        return (
            max(math.exp(mu + 0.5 * use), VAR_FLOOR),
            s2,
            training_schedule_sha256,
            len(ytr),
        )

    act, fb, fa, dates, gaps = [], [], [], [], []
    base_sizes, aug_sizes = [], []
    base_schedules, aug_schedules = [], []
    for i in range(burn_in, len(d)):
        # Forward-label embargo: a training row is usable only once its whole
        # label window has closed strictly before this origin.
        end = int(np.searchsorted(y_end, origins[i].to_datetime64(), side="left"))
        end = min(end, i)
        start = 0 if train_window is None else end - train_window
        if start < 0 or end - start < GW_MIN_LOSSES:
            continue
        pb, s2b, base_schedule, base_size = fit(Xb, origins, start, end, i)
        # "shared" forces the BASELINE's s^2 onto the augmented spec too
        pa, _, aug_schedule, aug_size = fit(
            Xa,
            origins,
            start,
            end,
            i,
            s2_override=s2b if smearing == "shared" else None,
        )
        act.append(float(yraw[i]))
        fb.append(pb)
        fa.append(pa)
        dates.append(origins[i])
        base_sizes.append(base_size)
        aug_sizes.append(aug_size)
        base_schedules.append(base_schedule)
        aug_schedules.append(aug_schedule)
        gaps.append((origins[i] - pd.Timestamp(y_end[end - 1])).days)

    base_schedule_sha256 = _string_sequence_sha256(base_schedules)
    aug_schedule_sha256 = _string_sequence_sha256(aug_schedules)
    same_training_dates = bool(
        base_schedules
        and base_schedules == aug_schedules
        and base_schedule_sha256 == aug_schedule_sha256
    )
    fixed_window_held = bool(
        train_window is not None
        and base_sizes
        and aug_sizes
        and min(base_sizes) == max(base_sizes) == train_window
        and min(aug_sizes) == max(aug_sizes) == train_window
    )
    embargo_ok = bool(gaps and min(gaps) >= 1)
    audit = {
        "scheme": "expanding" if train_window is None else "fixed_rolling",
        "train_window": None if train_window is None else int(train_window),
        "n_origins": len(act),
        "fixed_window_held": fixed_window_held,
        "same_training_dates_for_both_models": same_training_dates,
        "common_complete_case_mask_sha256": _date_index_sha256(origins),
        "base_training_schedule_sha256": base_schedule_sha256,
        "aug_training_schedule_sha256": aug_schedule_sha256,
        "origin_schedule_sha256": _date_index_sha256(dates),
        "min_origin_minus_last_train_label_end_days": int(min(gaps)) if gaps else None,
        "embargo_ok": embargo_ok,
        "gw_fixed_memory_eligible": bool(
            fixed_window_held and same_training_dates and embargo_ok
        ),
        "smearing": smearing,
        "n_forecasts_clipped_to_training_range": n_clip,
    }
    return PairedOOS(
        np.array(act), np.array(fb), np.array(fa), pd.DatetimeIndex(dates), audit
    )


# ---------------------------------------------------------------------------
# 8. Inference
# ---------------------------------------------------------------------------
def _bartlett_lrv(x: np.ndarray, max_lag: int) -> float:
    x = np.asarray(x, dtype=np.float64)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 10:
        raise ValueError("long-run variance needs >=10 finite observations")
    c = x - float(np.mean(x))
    lrv = float(c @ c / n)
    for lag in range(1, min(max_lag, n - 1) + 1):
        w = 1.0 - lag / (max_lag + 1.0)
        lrv += 2.0 * w * float(c[lag:] @ c[:-lag] / n)
    if not np.isfinite(lrv) or lrv <= 0:
        raise ValueError(f"non-positive long-run variance: {lrv}")
    return lrv


def gw_unconditional_dm(loss_aug: np.ndarray, loss_base: np.ndarray, h: int) -> dict:
    """GW (2006) Sec 3.4 UNCONDITIONAL special case: instrument h_t = 1.

    WHAT THIS IS NOT (rev3, after independent review).
    This is NOT the conditional Giacomini-White test. No instrument vector h_t is
    ever constructed; there is no q x q moment covariance, no Wald statistic and
    no chi-square_q reference distribution anywhere in this file. Calling the
    output a "GW gate" without that qualifier -- as rev2's README did -- claims
    conditional, state-dependent predictive ability that this design cannot
    deliver, and would let a positive and a negative effect in different regimes
    cancel to nothing while the write-up reports "no predictive content".
    What is implemented is the h_t = 1 special case GW themselves flag (Sec 3.4),
    in which their statistic coincides with a HAC Diebold-Mariano t. It targets
    exactly one null/estimand: equality of *unconditional* expected loss. Failure
    to reject that null does not license a claim of equality; it licenses only an
    evidence statement about the average loss differential.

    So why say GW at all? Because under NESTING the formula is not what makes the
    test legal -- the ESTIMATION SCHEME is. GW compare forecasting METHODS, with
    fitted-parameter noise part of the object being compared rather than a
    nuisance to be purged, and that limiting experiment requires the estimator to
    have BOUNDED MEMORY, i.e. a fixed-length rolling window. Fed fixed-window
    forecasts, the statistic is asymptotically standard normal even for nested
    models. Fed EXPANDING-window forecasts -- what v1 did -- the nested null is
    degenerate, the statistic is biased toward the smaller model, and no
    reference distribution rescues it. Same arithmetic, different scheme,
    different null, different validity. The expanding-window value is reported
    alongside as a diagnostic so a reader can see what the scheme change did.

    Moment: E[L_aug - L_base] = 0.  Negative z favours the flow model.
    """
    aug = np.asarray(loss_aug, float)
    base = np.asarray(loss_base, float)
    if aug.shape != base.shape:
        raise ValueError("loss arrays must have identical shapes")
    fin = np.isfinite(aug) & np.isfinite(base)
    diff = aug[fin] - base[fin]
    n = len(diff)
    if n < GW_MIN_LOSSES:
        raise ValueError(f"GW requires >={GW_MIN_LOSSES} losses; got {n}")
    bw = max(h - 1, canonical_bandwidth(h, n))
    lrv = _bartlett_lrv(diff, bw)
    se = math.sqrt(lrv / n)
    z = float(np.mean(diff)) / se
    return {
        "test": "Giacomini-White (2006) equal unconditional predictive ability",
        "loss": "Patton QLIKE",
        "estimand": "E[QLIKE_aug - QLIKE_base]",
        "forecast_scheme": "paired fixed rolling estimation window",
        "null": "equal expected QLIKE loss for the two forecasting METHODS",
        "direction": "negative z favours the flow model",
        "n": int(n),
        "mean_loss_diff_aug_minus_base": float(np.mean(diff)),
        "z_stat": float(z),
        "p_value_two_sided": float(2.0 * stats.norm.sf(abs(z))),
        "p_value_one_sided_flow_better": float(stats.norm.cdf(z)),
        "hac_lag_used": int(bw),
        "hac_kernel": "Bartlett",
        "hac_bandwidth_rule": "max(h-1, canonical_bandwidth(h,n))",
        "reference_distribution": "standard_normal",
        "standard_error": float(se),
    }


def build_claim_surface_prose(
    *,
    n_cells: int = 10,
    margin_pct: float = 100 * MATERIAL_GAIN_MARGIN,
    family_bound: float | None = None,
    unbounded_memory_cells: tuple[str, ...] | list[str] = (),
    n_registered_tests: int = 0,
    n_gate_eligible_tests: int = 0,
    n_full_family_significant: int = 0,
    n_diagnostic_tests: int = 0,
) -> dict[str, str]:
    """Single author for every substantive claim-scope sentence.

    The renderer, live experiment, and ``--relabel`` path all consume these exact
    strings.  In particular, every quantitative QLIKE bound names its estimand
    locally: an UNCONDITIONAL average loss differential.  A blanket disclaimer
    elsewhere in the README is deliberately not treated as sufficient.
    """
    margin = f"{margin_pct:.0f}%"
    material_gain_null = (
        "the flow method's UNCONDITIONAL expected QLIKE loss is at least "
        f"{margin} lower than the baseline's"
    )
    material_gain_alternative = (
        "the UNCONDITIONAL average relative QLIKE-loss gain is smaller than "
        f"{margin}"
    )
    upper_bound_note = (
        "One-sided 95% upper confidence bound on the UNCONDITIONAL average "
        "relative QLIKE-loss gain, obtained by inverting the exclusion test. "
        "Gains above it on that estimand are excluded by the data; gains below it "
        "are not. Conditional or regime-specific gains are not bounded. None = "
        "even a 90% unconditional average gain cannot be excluded."
    )
    if family_bound is not None:
        family_bound_statement = (
            "For the UNCONDITIONAL average-loss estimand, holding "
            f"**simultaneously across all {n_cells} cells** (Bonferroni), the "
            "relative QLIKE-loss gain from adding ETF flow is "
            f"**≤ {family_bound:.1f}%**. Anything larger on that estimand is "
            "ruled out; anything smaller is not. Gains that vary by regime or "
            "state are outside this result."
        )
    else:
        family_bound_statement = (
            "For the UNCONDITIONAL average-loss estimand, **no simultaneous "
            "family bound can be stated at all**: at least one cell cannot exclude "
            "even a 90% relative QLIKE-loss gain. Gains that vary by regime or "
            "state are likewise not bounded by this design."
        )

    unbounded = tuple(sorted(unbounded_memory_cells))
    n_unbounded = len(unbounded)
    if n_unbounded:
        rows = "`, `".join(unbounded)
        bounded_memory_heading = (
            f"{n_unbounded} registered diagnostic "
            f"{'row fails' if n_unbounded == 1 else 'rows fail'} the "
            "bounded-memory gate"
        )
        bounded_memory_issue = (
            "GW's limiting experiment assumes the forecasting METHOD has bounded "
            "estimator memory. Every final regression here uses a fixed 250-day "
            "rolling window, but the condition is on the whole method. "
            f"`{rows}` "
            f"{'builds its regressor' if n_unbounded == 1 else 'build their regressors'} "
            "from an AR(5) refitted on an EXPANDING window of flow history. There "
            "is no lookahead, but "
            f"{'that row is' if n_unbounded == 1 else 'those rows are'} not "
            "bounded-memory forecasting methods. It would therefore be false to "
            f"call all {n_registered_tests} registered tests bounded-memory. The "
            "affected rows are diagnostic-only and cannot enter a verdict."
        )
    else:
        bounded_memory_heading = "All registered methods pass the bounded-memory gate"
        bounded_memory_issue = (
            "Every registered forecasting method has bounded estimator memory."
        )

    return {
        "bounded_null_test_scope": (
            "One-sided exclusion of a pre-specified material UNCONDITIONAL average "
            f"relative QLIKE-loss gain of {margin}. This is the only test here that "
            "can license an upper bound on that estimand; it does not bound "
            "conditional or regime-specific gains."
        ),
        "c2_fix_summary": (
            "A repeated-sampling power simulation plus a pre-specified exclusion "
            "test and inverted confidence bound for the UNCONDITIONAL average "
            "QLIKE-loss estimand. Only the latter two can bound that estimand; none "
            "of them bounds conditional or regime-specific gains."
        ),
        "gw_name_explanation": (
            "**Why the word Giacomini-White appears when the statistic has HAC-DM "
            "form.** With h_t=1, GW (2006) Sec. 3.4 reduces to a mean loss "
            "differential over a Bartlett HAC standard error and targets only "
            "UNCONDITIONAL expected loss. This file builds no non-trivial instrument "
            "vector, q x q moment covariance, Wald statistic, or chi-square_q "
            "reference distribution, so it performs no conditional GW test and "
            "licenses no conditional or state-dependent claim."
        ),
        "nested_fixed_memory_explanation": (
            "Validity under nesting comes from the estimation scheme, not the "
            "DM-form arithmetic. GW compares forecasting methods with fitted-"
            "parameter noise included, and this limiting experiment requires "
            "bounded estimator memory. The paired fixed rolling window satisfies "
            "that condition; an expanding window does not and produces a degenerate "
            "nested null. Expanding-window values are retained only as "
            "diagnostic, feeds_gate=false records."
        ),
        "endogeneity_claim_scope": (
            "Flow is contemporaneously correlated with the same day's return and "
            "volatility, so a contemporaneous regression of RV on flow is "
            "uninterpretable. Every inferential predictive claim below concerns "
            "the UNCONDITIONAL average loss differential of paired out-of-sample "
            "forecasting methods relative to a HAR-RV baseline; no conditional or "
            "state-dependent predictive-ability claim is made."
        ),
        "primary_section_heading": (
            "Primary family — does flow improve UNCONDITIONAL average OOS QLIKE?"
        ),
        "primary_design_scope": (
            f"{n_cells} pre-specified cells. `H1` adds |z| (flow-shock magnitude); "
            "`H2` adds an extra loading on redemptions; `H4` asks whether BTC flow "
            "improves ETH's UNCONDITIONAL average out-of-sample QLIKE after "
            "controlling for ETH's own flow. None tests conditional or "
            "state-dependent predictive ability."
        ),
        "qlike_delta_interpretation": (
            "`QLIKE Δ` is the sample-average QLIKE-loss improvement of the flow "
            "method over the baseline; a negative value means worse average QLIKE. "
            "Negative unconditional GW/DM z favours flow. The gate requires "
            "`z < -1.645`, Holm `p < 0.05`, and positive QLIKE Δ."
        ),
        "primary_table_header": (
            "| Cell | n OOS | QLIKE Δ | uncond. GW/DM z | Holm p | Rules out "
            f"≥{margin} UNCONDITIONAL average QLIKE gain? |"
        ),
        "bound_section_heading": (
            "The UNCONDITIONAL average QLIKE-loss bound: what can be ruled out"
        ),
        "bound_test_intro": (
            "Failing to reject equal UNCONDITIONAL expected loss is not evidence of "
            "equality. A bound on the average QLIKE-loss estimand requires reversing "
            "the burden of proof and testing the material-gain null directly; this "
            "does not bound conditional or regime-specific gains."
        ),
        "bound_ci_heading": (
            "What CAN be bounded: the UNCONDITIONAL average-loss confidence interval"
        ),
        "exclusion_table_header": (
            "| Cell | exclusion z | p (unadjusted, IU) | excludes? | p (Holm, "
            "conservative) | 95% upper bound on the UNCONDITIONAL average QLIKE "
            "gain |"
        ),
        "in_sample_claim_scope": (
            "Descriptive only. The verdict rests on the UNCONDITIONAL average loss "
            "differential of paired out-of-sample forecasting methods, not on an "
            "in-sample coefficient; conditional or state-dependent predictive "
            "ability is not tested."
        ),
        "h3_weekend_claim_scope": (
            "In-sample only. The study's verdict concerns the UNCONDITIONAL average "
            "loss differential of paired out-of-sample forecasting methods, so "
            "this weekend coefficient is descriptive and enters no verdict. It "
            "does not test conditional or state-dependent predictive ability."
        ),
        "material_gain_null": material_gain_null,
        "material_gain_alternative": material_gain_alternative,
        "material_gain_rejection_interpretation": (
            "Rejecting H0 rules out a gain that large only for the UNCONDITIONAL "
            "average-loss estimand."
        ),
        "material_gain_scope": (
            "rules out a material UNCONDITIONAL average relative QLIKE-loss gain; "
            "does NOT prove exact equality and does not bound conditional or "
            "regime-specific gains or RV-uplift magnitude"
        ),
        "upper_bound_note": upper_bound_note,
        "exclusion_multiplicity_readme": (
            "**Why these p-values are unadjusted, while the detection ones above "
            "are Holm-corrected.** The two UNCONDITIONAL average-loss claims have "
            "opposite logical structure. *\"Flow improves average loss somewhere\"* "
            "is a **union** of alternatives — ten shots at finding an effect — so "
            "the family-wise error rate must be controlled. *\"Flow improves "
            f"average loss nowhere by ≥{margin}\"* is an **intersection**: it may "
            "be asserted only if every cell rejects its own exclusion null. That "
            "intersection-union test holds at level alpha with each cell tested "
            "unadjusted (Berger 1982). Holm there would inflate type-II error and "
            "buy no type-I protection; its values are reported only as a "
            "conservative sensitivity. Neither claim addresses conditional or "
            "regime-specific gains."
        ),
        "upper_bound_explanation_readme": (
            "The last column is the one-sided 95% **upper confidence bound** on the "
            "UNCONDITIONAL average relative QLIKE-loss gain, obtained by inverting "
            "the exclusion test. Gains larger than the bound on that estimand are "
            "excluded; gains smaller than it are not. Unlike a power curve, this "
            "is an inference about the average-loss estimand rather than a property "
            "of the design under an assumed truth. It says nothing about "
            "conditional or regime-specific gains."
        ),
        "family_bound_statement": family_bound_statement,
        "bound_literal_scope": (
            "**Read the bound literally.** It lives in QLIKE-loss space and bounds "
            "only UNCONDITIONAL average forecast accuracy. It does not bound a "
            "conditional or regime-specific gain, an RV uplift per flow shock, or "
            "the true effect at exactly zero."
        ),
        "power_scope_warning": (
            "POWER IS NOT AN EXCLUSION. This says how often the gate fires against "
            "an effect of a given size; it does not bound the truth at the 80%-power "
            "point. The only upper bound this study defends is produced by the "
            "material-gain exclusion test, lives in QLIKE-loss space, and applies "
            "only to the UNCONDITIONAL average-loss estimand — not to conditional "
            "or regime-specific gains. The simulation is per-cell power at the "
            "nominal 5% gate, h=1, against one injected alternative. The actual "
            f"verdict applies Holm across {n_cells} cells, includes h=5, and includes "
            "alternatives not simulated here, so family-wise power is lower."
        ),
        "power_dgp_readme": (
            f"{POWER_REPS} simulated OOS paths per point. The DGP is the fitted "
            "calendar-day HAR law of motion with block-bootstrapped innovations; "
            "real flow shocks and returns are retained, and the effect is injected "
            "into the law of motion so it propagates through HAR lags."
        ),
        "power_grid_note": (
            "The beta grid is coarse, so 80%- and 90%-power crossings are intervals, "
            "not thresholds. No point estimate of a crossing is reported."
        ),
        "power_false_positive_note": (
            "The beta=0 row is not textbook size. Under the fixed-window method-level "
            "null, an irrelevant extra regressor raises the augmented method's "
            "UNCONDITIONAL expected loss through estimation cost, so the one-sided "
            "flow-favouring gate is conservative. A rejection rate materially above "
            "5% would be alarming; a lower rate does not establish conditional or "
            "state-dependent validity."
        ),
        "power_section_heading": (
            "Power — one h=1 cell, one injected alternative, nominal gate"
        ),
        "power_curve_intro": (
            "Per-beta rejection rates for the h=1, one-cell nominal gate:"
        ),
        "power_curve_table_header": (
            "| Assumed RV uplift per 1-sd shock | BTC one-cell power | ETH one-cell "
            "power |"
        ),
        "power_is_not_exclusion_readme": (
            "**Power is not an exclusion.** This table says how often a one-cell "
            "gate fires against an assumed effect. It does not bound the true "
            "effect at the 80%-power point. The separate material-gain test bounds "
            "only the UNCONDITIONAL average relative QLIKE-loss gain; conditional "
            "or regime-specific gains are not bounded. The primary family also "
            f"applies Holm across {n_cells} cells, so family-wise power is lower "
            "than the table shows."
        ),
        "smearing_scope": (
            "The augmented method has more parameters, which can lower its training "
            "residual variance and lognormal smearing multiplier. Because QLIKE is "
            "asymmetric, that channel could bias the UNCONDITIONAL average QLIKE "
            "comparison against flow. The residual variance is dof-corrected; two "
            "diagnostic panels also remove smearing or force the baseline multiplier "
            "onto both methods. Those non-gate diagnostics do not change the "
            "INCONCLUSIVE primary verdict, and they say nothing about conditional "
            "or regime-specific gains."
        ),
        "h3_motivation": (
            "Crypto trades through the weekend but the ETFs do not, so Friday flow "
            "is the last ETF-flow observation before a two-day gap. This in-sample "
            "descriptive coefficient asks where an association might be most "
            "visible; it does not test out-of-sample, conditional, or "
            "state-dependent predictive ability."
        ),
        "bounded_memory_heading": bounded_memory_heading,
        "bounded_memory_issue": bounded_memory_issue,
        "robustness_registry_intro": (
            "Every robustness row is registered with the primary family, but only "
            "pre-specified, bounded-memory primary rows can feed the claim gate. "
            "Non-primary rows remain diagnostic regardless of their p-values."
        ),
        "robustness_table_header": (
            "| Diagnostic family | Rows | Best flow-favouring UNCONDITIONAL z |"
        ),
        "robustness_outcome_readme": (
            f"Across all **{n_gate_eligible_tests}** gate-eligible tests of the "
            "UNCONDITIONAL average QLIKE-loss differential, "
            f"**{n_full_family_significant}** survive Holm in the flow-favouring "
            f"direction. Another {n_diagnostic_tests} registered tests are "
            "diagnostic-only and barred from every claim gate. This result does not "
            "address gains that vary by regime or state."
        ),
        "smearing_heading": (
            "Could smearing bias the UNCONDITIONAL average QLIKE comparison?"
        ),
    }


def material_gain_exclusion(
    loss_aug: np.ndarray,
    loss_base: np.ndarray,
    h: int,
    margin: float = MATERIAL_GAIN_MARGIN,
) -> dict:
    """Can a pre-specified UNCONDITIONAL average QLIKE gain be ruled out? (C2b)

    This is the only test in the file that can license a bounded null, and it is
    the one v1 never ran.

    H0: the flow method improves expected QLIKE by at least `margin`,
        E[L_aug] <= (1 - margin) * E[L_base].
    Rejecting H0 (positive z, small p) means a gain that large is NOT there.

    Note what this does and does not buy. It reverses the burden of proof, so a
    rejection is a genuine upper bound on the UNCONDITIONAL average-loss
    estimand -- but the bound lives in QLIKE-LOSS space ("no >=1% average relative
    QLIKE improvement"), NOT in conditional/regime-specific or RV-uplift space.
    v1's "we can rule out a >=16% RV rise per 1-sd shock" came from reading a
    power curve backwards, which is not an inference at all. Failing to reject
    equal accuracy never proves equality; only this does, and only for what it
    actually measures.
    """
    if not 0 < margin < 1:
        raise ValueError("margin must lie strictly in (0, 1)")
    aug = np.asarray(loss_aug, float)
    base = np.asarray(loss_base, float)
    fin = np.isfinite(aug) & np.isfinite(base)
    moment = aug[fin] - (1.0 - margin) * base[fin]
    n = len(moment)
    if n < GW_MIN_LOSSES:
        raise ValueError(f"exclusion test requires >={GW_MIN_LOSSES} losses; got {n}")
    bw = max(h - 1, canonical_bandwidth(h, n))
    lrv = _bartlett_lrv(moment, bw)
    se = math.sqrt(lrv / n)
    z = float(np.mean(moment)) / se
    prose = build_claim_surface_prose(margin_pct=100 * margin)
    return {
        "test": "one-sided material-gain exclusion (fixed-window GW moment)",
        "margin_relative_qlike": float(margin),
        "null": prose["material_gain_null"],
        "alternative": prose["material_gain_alternative"],
        "n": int(n),
        "mean_margin_moment": float(np.mean(moment)),
        "z_stat": float(z),
        "p_value_one_sided": float(stats.norm.sf(z)),
        "hac_lag_used": int(bw),
        "scope": prose["material_gain_scope"],
    }


def qlike_gain_upper_bound(
    loss_aug: np.ndarray, loss_base: np.ndarray, h: int, alpha: float = 0.05
) -> float | None:
    """Upper confidence bound on the UNCONDITIONAL average QLIKE gain, in %.

    This inverts `material_gain_exclusion`: it returns the supremum of the margins
    whose one-sided null is not rejected. Gains larger than the bound are excluded
    only for this unconditional average-loss estimand; gains smaller than it are
    not. Conditional or regime-specific gains are not bounded.

    Why this and not the power curve. Both answer "how big an effect could this
    design have seen?", but only ONE of them is an inference about the effect. A
    power curve is a property of the design under an assumed truth; a confidence
    bound is a statement about the unconditional average-loss estimand given the
    data. v1 reached for the power curve and read it backwards. This is the object
    it should have reported.

    Returns None when even a 90% gain cannot be excluded, i.e. the design says
    essentially nothing about the effect size.

    The HAC denominator changes with the margin, so z(m) need not be monotone.
    The earlier binary search silently assumed that it was. Here the full
    rejection topology is solved instead. For

        moment(m) = (loss_aug - loss_base) + m * loss_base,

    the Bartlett long-run variance is quadratic in m and the mean is linear.
    Consequently z(m) = z_crit has at most two algebraic roots. We enumerate all
    admissible roots, classify every interval between them, and return the
    supremum of the NON-rejected confidence set. A non-rejected interval touching
    90% means that no finite bound is supported on the searched domain.
    """
    if not 0 < alpha < 1:
        raise ValueError("alpha must lie strictly in (0, 1)")
    aug = np.asarray(loss_aug, float)
    base = np.asarray(loss_base, float)
    if aug.shape != base.shape:
        raise ValueError("loss arrays must have identical shapes")
    fin = np.isfinite(aug) & np.isfinite(base)
    aug, base = aug[fin], base[fin]
    n = len(base)
    if n < GW_MIN_LOSSES:
        raise ValueError(f"bound inversion requires >={GW_MIN_LOSSES} losses; got {n}")

    diff = aug - base
    bw = max(h - 1, canonical_bandwidth(h, n))
    # v(m) = c + 2*d*m + e*m^2. Three evaluations recover the exact
    # quadratic (up to floating-point arithmetic) without assuming monotonicity.
    c = _bartlett_lrv(diff, bw)
    v_plus = _bartlett_lrv(diff + base, bw)
    v_minus = _bartlett_lrv(diff - base, bw)
    d = 0.25 * (v_plus - v_minus)
    e = 0.5 * (v_plus + v_minus) - c
    a = float(np.mean(diff))
    b = float(np.mean(base))
    z_crit = float(stats.norm.ppf(1 - alpha))

    def z_of(m: float) -> float:
        variance = c + 2.0 * d * m + e * m * m
        if not np.isfinite(variance) or variance <= 0:
            raise ValueError(f"non-positive inverted-test long-run variance: {variance}")
        return math.sqrt(n) * (a + b * m) / math.sqrt(variance)

    # Squaring z(m)=z_crit gives a quadratic. Retain only roots with a
    # non-negative numerator; the negative branch solves z=-z_crit instead.
    coeff = np.array(
        [
            n * b * b - z_crit * z_crit * e,
            2.0 * n * a * b - 2.0 * z_crit * z_crit * d,
            n * a * a - z_crit * z_crit * c,
        ],
        dtype=float,
    )
    scale = max(1.0, float(np.max(np.abs(coeff))))
    if abs(coeff[0]) <= 1e-12 * scale:
        algebraic = [] if abs(coeff[1]) <= 1e-12 * scale else [-coeff[2] / coeff[1]]
    else:
        algebraic = np.roots(coeff[:]).tolist()

    lo, hi = 1e-4, 0.90
    roots: list[float] = []
    for candidate in algebraic:
        if abs(complex(candidate).imag) > 1e-9:
            continue
        root = float(complex(candidate).real)
        if lo < root < hi and a + b * root >= 0:
            # Do not evaluate z exactly at the root: with a perfectly
            # proportional planted gain both its numerator and HAC denominator
            # can be zero there, even though the one-sided limits are defined.
            roots.append(root)
    roots = sorted(set(round(root, 14) for root in roots))

    cuts = [lo, *roots, hi]
    intervals: list[tuple[float, float, bool]] = []
    for left, right in zip(cuts[:-1], cuts[1:]):
        midpoint = 0.5 * (left + right)
        intervals.append((left, right, z_of(midpoint) >= z_crit))

    non_rejected = [(left, right) for left, right, rejected in intervals if not rejected]
    if non_rejected and math.isclose(non_rejected[-1][1], hi, abs_tol=1e-12):
        return None
    if not non_rejected:
        return lo * 100.0

    bound = max(right for _, right in non_rejected)
    # The bound is valid only if every open interval above it rejects. This is
    # the topology check the former monotone binary search omitted.
    if any(not rejected for left, _, rejected in intervals if left >= bound):
        raise RuntimeError("QLIKE inversion did not produce an upper-tail rejection set")
    return bound * 100.0


def block_bootstrap_ci(
    loss_aug: np.ndarray, loss_base: np.ndarray, h: int, seed: int, reps: int = 1999
) -> dict:
    """Paired circular moving-block CI for the relative QLIKE improvement."""
    aug = np.asarray(loss_aug, float)
    base = np.asarray(loss_base, float)
    fin = np.isfinite(aug) & np.isfinite(base)
    aug, base = aug[fin], base[fin]
    n = len(aug)
    if n < GW_MIN_LOSSES:
        raise ValueError(f"bootstrap requires >={GW_MIN_LOSSES} losses; got {n}")
    bl = max(int(h), int(math.ceil(n ** (1 / 3))))
    nb = int(math.ceil(n / bl))
    rng = np.random.default_rng(seed)
    off = np.arange(bl)
    draws = np.empty(reps)
    for b in range(reps):
        starts = rng.integers(0, n, size=nb)
        idx = ((starts[:, None] + off[None, :]) % n).ravel()[:n]
        bm = float(np.mean(base[idx]))
        draws[b] = 100.0 * (bm - float(np.mean(aug[idx]))) / bm
    pb = float(np.mean(base))
    return {
        "method": "paired circular moving-block bootstrap of fixed-window QLIKE losses",
        "seed": int(seed),
        "reps": int(reps),
        "block_length": int(bl),
        "point_improvement_pct": 100.0 * (pb - float(np.mean(aug))) / pb,
        "ci95_improvement_pct": [float(x) for x in np.quantile(draws, [0.025, 0.975])],
        "scope": "uncertainty diagnostic; forecasts are not re-estimated inside the bootstrap",
    }


def raw_dm_diagnostic(
    loss_aug: np.ndarray, loss_base: np.ndarray, h: int, scheme: str = "fixed"
) -> dict:
    """Ordinary Diebold-Mariano on the QLIKE loss difference. DESCRIPTIVE ONLY.

    `scheme` decides WHY it is descriptive, and the two reasons are not the same
    reason. Writing one label for both is how a file ends up contradicting
    itself.

      scheme="expanding"  The statistic is INVALID for this comparison. An
                          expanding window drives estimation error to zero, the
                          nested null degenerates, and the statistic is biased
                          toward the smaller model. It is kept only to show what
                          v1's design produced.

      scheme="fixed"      The statistic is VALID and is simply not the object the
                          verdict was pre-registered on. It runs on the very loss
                          stream the Giacomini-White gate runs on -- a fixed
                          rolling window, so estimation error survives in the
                          limit and there is NO bias toward the smaller model
                          here. It differs from the gate statistic only in the
                          HAC small-sample scaling and in taking a Student-t
                          rather than a normal reference, which is why the two
                          agree to ~3 decimals. Calling this one "biased toward
                          the smaller model" would be importing the expanding-
                          window pathology into a design that was changed
                          specifically to avoid it.

    Either way `feeds_gate=False`: exactly one object reaches the verdict, and it
    is the one whose reference distribution was justified in advance.

    C5 -- naming. `volpred.stats.model_evaluation.dm_test` is a HAC-DM statistic
    combined with the Harvey-Liu-Zhu (2016) |t| > 3 heuristic threshold. It does
    NOT apply the Harvey-Leybourne-Newbold (1997) finite-sample correction
    factor, so v1 was wrong to call it "HLN modified DM". We report it under its
    true name. The one-sided p-value is taken from the SAME Student-t(n-1)
    distribution the helper uses for its two-sided p -- v1 switched to a normal
    CDF here, so its two p-values disagreed with each other.
    """
    if scheme not in ("fixed", "expanding"):
        raise ValueError(f"scheme must be 'fixed' or 'expanding'; got {scheme!r}")
    t, p_two = dm_test(loss_aug, loss_base, h=h)
    n = int(np.isfinite(np.asarray(loss_aug) - np.asarray(loss_base)).sum())
    role = {
        "fixed": (
            "diagnostic-only BY DESIGN, not by invalidity: same estimand and same "
            "fixed-rolling-window loss stream as the Giacomini-White gate, "
            "differing only in the HAC small-sample scaling and a Student-t "
            "reference. A fixed window keeps estimation error in the limiting "
            "experiment, so this statistic is NOT biased toward the smaller model. "
            "It does not feed the gate because the verdict was pre-registered on "
            "the object with the justified reference distribution."
        ),
        "expanding": (
            "diagnostic-only BECAUSE INVALID: an expanding window drives estimation "
            "error to zero, the nested null is degenerate, and the statistic is "
            "biased toward the smaller model. Reported only to show what v1's "
            "design produced."
        ),
    }[scheme]
    return {
        "statistic": "HAC-DM (canonical bandwidth) + Harvey-Liu-Zhu |t|>3 heuristic",
        "estimation_scheme": scheme,
        "not_hln": (
            "This is NOT Harvey-Leybourne-Newbold modified DM: no finite-sample "
            "correction factor is applied. v1 mislabelled it."
        ),
        "role": role,
        "valid_for_this_nested_comparison": scheme == "fixed",
        "feeds_gate": False,
        "t_stat": float(t),
        "p_two_sided_student_t": float(p_two),
        "p_one_sided_flow_better_student_t": float(stats.t.cdf(t, df=max(n - 1, 1))),
        "df": n - 1,
    }


# ---------------------------------------------------------------------------
# 9. The cell — one nested comparison, fully inferred
# ---------------------------------------------------------------------------
def evaluate_cell(
    p: Panel,
    base: str,
    alt: str,
    family: str,
    train_window: int = GW_TRAIN_WINDOW,
    smearing: str = "own",
    variant: str = "",
    register_gate: bool = True,
    bounded_memory: bool = True,
) -> dict | None:
    """Run one nested comparison end to end and register its tests.

    `variant` disambiguates cells that share an (asset, horizon, spec) signature
    but not a panel -- the four shock-threshold dummies, for instance. The cell
    key MUST be globally unique: it is the join key between the registry, the
    loss cache and the verdict, and a silent collision would let a robustness
    cell's exclusion statistics be wired into the primary family. That is not
    hypothetical -- it happened, and it is why `_assert_unique_cell` below now
    fails loudly instead of letting the last writer win.

    `bounded_memory=False` marks a cell whose forecasting METHOD does not satisfy
    GW's bounded-estimator-memory condition (see `TestRecord`). Such a cell is
    registered as an invalid-for-gating diagnostic, but it can never enter a GW
    family or verdict. Eligibility is fixed by method provenance before its p-value
    is inspected, so this is not result-dependent test deletion.
    """
    po = paired_oos(p, base, alt, train_window, smearing)
    if len(po.actual) < GW_MIN_LOSSES:
        return None

    lb = qlike_pointwise(po.actual, po.pred_base)
    la = qlike_pointwise(po.actual, po.pred_aug)
    h = p.horizon
    qb, qa = float(np.mean(lb)), float(np.mean(la))
    improve = (qb - qa) / qb * 100.0

    gw = gw_unconditional_dm(la, lb, h)
    excl = material_gain_exclusion(la, lb, h)
    excl["qlike_gain_upper_bound_95pct"] = qlike_gain_upper_bound(la, lb, h, alpha=0.05)
    excl["upper_bound_note"] = build_claim_surface_prose()["upper_bound_note"]
    boot = block_bootstrap_ci(la, lb, h, seed=SEED + h)
    dm = raw_dm_diagnostic(la, lb, h, scheme="fixed")

    # v1's design, re-run purely so the results file can show what changed. An
    # expanding window breaks GW's bounded-memory condition, so a HAC t-test on
    # these losses is NOT a valid nested test -- whatever it happens to say.
    exp_po = paired_oos(p, base, alt, train_window=None, smearing=smearing)
    expanding = None
    if len(exp_po.actual) >= GW_MIN_LOSSES:
        exp_lb = qlike_pointwise(exp_po.actual, exp_po.pred_base)
        exp_la = qlike_pointwise(exp_po.actual, exp_po.pred_aug)
        exp_dm = raw_dm_diagnostic(exp_la, exp_lb, h, scheme="expanding")
        expanding = {
            "scheme": "expanding window (v1's design)",
            "valid_for_nested_inference": False,
            "why_invalid": (
                "GW's limiting experiment needs bounded estimator memory. An "
                "expanding window has none, so the nested null is degenerate and "
                "the statistic is biased toward the smaller model."
            ),
            "feeds_gate": False,
            "n_oos": int(len(exp_po.actual)),
            "qlike_improvement_pct": float(
                (np.mean(exp_lb) - np.mean(exp_la)) / np.mean(exp_lb) * 100.0
            ),
            "hac_t_stat": exp_dm["t_stat"],
        }

    # Clark-West: a DIFFERENT estimand. CW adjusts the MSPE of variance-level
    # forecasts; it is not a QLIKE general-loss test and is not relabelled as one.
    cw = clark_west_test(po.actual, po.pred_base, po.pred_aug, h=h)

    cell = _assert_unique_cell(family, p, alt, smearing, train_window, variant)
    LOSS_CACHE[cell] = (la, lb, h)
    whole_method_fixed_memory = bool(
        bounded_memory and po.audit.get("gw_fixed_memory_eligible") is True
    )
    gate_eligible = bool(
        register_gate and family == "primary" and whole_method_fixed_memory
    )
    if family == "primary" and register_gate and not gate_eligible:
        raise AssertionError(
            f"primary cell {cell} requested a gate without fixed-memory provenance"
        )
    register(
        TestRecord(
            family=family, cell=cell, asset=p.asset, horizon=h, base=base, alt=alt,
            inference="giacomini_white_qlike_fixed_window",
            estimand="E[QLIKE_aug - QLIKE_base]",
            scheme="paired fixed rolling window",
            stat=gw["z_stat"], p_one_sided=gw["p_value_one_sided_flow_better"],
            feeds_gate=gate_eligible, qlike_improve_pct=improve, n=gw["n"],
            bounded_memory=whole_method_fixed_memory,
        )
    )
    register(
        TestRecord(
            family=family, cell=cell, asset=p.asset, horizon=h, base=base, alt=alt,
            inference="raw_dm_qlike",
            estimand="E[QLIKE_aug - QLIKE_base] (same stream as GW; Student-t reference)",
            scheme="paired fixed rolling window",
            stat=dm["t_stat"], p_one_sided=dm["p_one_sided_flow_better_student_t"],
            feeds_gate=False, qlike_improve_pct=improve, n=gw["n"],
            bounded_memory=whole_method_fixed_memory,
        )
    )
    register(
        TestRecord(
            family=family, cell=cell, asset=p.asset, horizon=h, base=base, alt=alt,
            inference="clark_west_mspe",
            estimand="MSPE of variance-level forecasts (NOT QLIKE)",
            scheme="paired fixed rolling window",
            stat=float(cw["t_stat"]),
            p_one_sided=float(cw.get("p_value_one_sided", np.nan)),
            feeds_gate=False, qlike_improve_pct=improve, n=gw["n"],
            bounded_memory=whole_method_fixed_memory,
        )
    )

    return {
        "asset": p.asset,
        "horizon": h,
        "rv_proxy": p.rv_col,
        "base": base,
        "alt": alt,
        "cell": cell,
        "family": family,
        "state_lag": p.state_lag,
        "flow_lag": p.flow_lag,
        "smearing": smearing,
        "bounded_memory": whole_method_fixed_memory,
        "n_oos": int(len(po.actual)),
        "oos_start": str(po.origins.min().date()),
        "oos_end": str(po.origins.max().date()),
        "qlike_base": qb,
        "qlike_alt": qa,
        "qlike_improvement_pct": improve,
        "oos_audit": po.audit,
        "primary_inference_gw_qlike": gw,
        "material_gain_exclusion": excl,
        "bootstrap_ci": boot,
        "raw_dm_diagnostic": dm,
        "expanding_window_diagnostic_v1_design": expanding,
        "statistic_coincidence_note": (
            "raw_dm_diagnostic.t_stat and primary_inference_gw_qlike.z_stat are the "
            "same statistic up to a small-sample HAC scaling (the GW long-run "
            "variance divides each lag covariance by n, the canonical DM helper by "
            "n-lag), and they are computed on the SAME fixed-window loss stream. "
            "They therefore agree to ~3 decimal places. That is expected, not a "
            "relabelling: what separates a valid nested test from an invalid one "
            "here is the ESTIMATION SCHEME and the null, not the arithmetic. The "
            "raw statistic is nevertheless tagged feeds_gate=false so that the "
            "verdict is carried by the object whose reference distribution is "
            "justified. Compare with expanding_window_diagnostic_v1_design to see "
            "what the scheme change actually did."
        ),
        "clark_west_mspe_separate_estimand": {
            "t_stat": float(cw["t_stat"]),
            "p_one_sided": float(cw.get("p_value_one_sided", np.nan)),
            "estimand": "MSPE (variance level), not QLIKE",
            "feeds_gate": False,
            "note": (
                "Clark-West corrects the MSPE of the nested comparison. It is "
                "evidence about a different loss than the one the verdict uses, "
                "and is reported as such."
            ),
        },
    }


# ---------------------------------------------------------------------------
# 10. Power simulation (C2a) — a statement about the DESIGN, not the effect
# ---------------------------------------------------------------------------
def fit_calendar_har(rv: pd.DataFrame, rv_col: str) -> dict:
    """Fit the HAR+ctrl recursion on CALENDAR days. This is the simulation DGP.

    Distinct from `in_sample`, which fits on PANEL rows (flow days only). The
    simulation has to step the volatility process forward on every calendar day,
    including the weekends when no flow prints, so it needs a calendar-day law of
    motion.
    """
    lr = np.log(rv[rv_col])
    frame = pd.DataFrame(
        {
            "y": lr,
            "har_d": lr.shift(1),
            "har_w": lr.rolling(HAR_W).mean().shift(1),
            "har_m": lr.rolling(HAR_M).mean().shift(1),
            "ret": rv["ret"].shift(1),
            "abs_ret": rv["ret"].abs().shift(1),
        }
    ).dropna()
    cols = ["har_d", "har_w", "har_m", "ret", "abs_ret"]
    X = frame[cols].to_numpy(float)
    y = frame["y"].to_numpy(float)
    beta = _ols(X, y)
    resid = y - np.column_stack([np.ones(len(X)), X]) @ beta
    persistence = float(beta[1] + beta[2] + beta[3])
    if persistence >= 1.0:
        raise AssertionError(
            f"calendar HAR is non-stationary (phi_d+phi_w+phi_m = {persistence:.4f}); "
            "the simulated paths would explode"
        )
    return {
        "beta": beta,
        "resid": resid,
        "n": int(len(frame)),
        "persistence": persistence,
        "resid_sd": float(np.std(resid)),
    }


def _block_resample(resid: np.ndarray, n_out: int, rng, block: int) -> np.ndarray:
    """Circular moving-block resample: keeps the innovation autocorrelation."""
    nb = int(math.ceil(n_out / block))
    starts = rng.integers(0, len(resid), size=nb)
    idx = ((starts[:, None] + np.arange(block)[None, :]) % len(resid)).ravel()[:n_out]
    return resid[idx]


def simulate_lrv(
    lr_seed: np.ndarray,
    ret_lag: np.ndarray,
    aret_lag: np.ndarray,
    shock: np.ndarray,
    dgp: dict,
    beta_flow: float,
    rng,
    bounds: tuple[float, float],
) -> tuple[np.ndarray, int]:
    """One simulated calendar log-RV path carrying a KNOWN flow effect.

    The effect is injected into the LAW OF MOTION, so it propagates into
    tomorrow's HAR features exactly as a genuine effect would. That matters: the
    HAR baseline partially absorbs a real effect through its own lags, which
    makes the effect HARDER to detect. Injecting into the target only -- without
    propagation -- would overstate power, which is the optimistic direction and
    therefore the dangerous one.
    """
    b = dgp["beta"]
    n = len(shock)
    lrv = np.empty(n)
    lrv[:HAR_M] = lr_seed[:HAR_M]
    e = _block_resample(dgp["resid"], n, rng, block=max(2, int(math.ceil(n ** (1 / 3)))))
    lo, hi = bounds
    n_clip = 0
    sw = float(lrv[HAR_M - HAR_W : HAR_M].sum())
    sm = float(lrv[:HAR_M].sum())
    for d in range(HAR_M, n):
        v = (
            b[0]
            + b[1] * lrv[d - 1]
            + b[2] * (sw / HAR_W)
            + b[3] * (sm / HAR_M)
            + b[4] * ret_lag[d]
            + b[5] * aret_lag[d]
            + beta_flow * shock[d]
            + e[d]
        )
        if not (lo <= v <= hi):
            n_clip += 1
            v = min(max(v, lo), hi)
        lrv[d] = v
        sw += lrv[d] - lrv[d - HAR_W]
        sm += lrv[d] - lrv[d - HAR_M]
    return lrv, n_clip


def power_simulation(
    rv: pd.DataFrame,
    ff: FlowFeatures,
    asset: str,
    horizon: int = 1,
    reps: int = POWER_REPS,
    betas: tuple[float, ...] = POWER_BETAS,
) -> dict:
    """Simulated power of ONE cell's GW gate, plus a false-positive check at beta=0.

    v1's "MDE" was not a power analysis at all: it injected each beta ONCE into
    the single realised noise path and took the first crossing. No repeated
    sampling, no false-positive check, no confidence interval -- and the resulting
    curve was not even monotone in beta, which is a tell that it was reading
    noise. It then INVERTED the logic and claimed the null "excludes effects
    >= the MDE". Power cannot do that. Only the exclusion test can, and it is
    reported separately.

    SCOPE -- what this is NOT (quote it with these limits or not at all):
      * It is the power of a SINGLE CELL against the NOMINAL one-sided 5% gate
        (z < -1.645). The verdict runs a ten-cell Holm-corrected family, whose
        power is strictly LOWER. This is not "the power of the study".
      * `horizon` defaults to 1. The primary family also contains h = 5 cells,
        which are not simulated here.
      * The injected effect is a single |flow| shock entering the HAR law of
        motion -- the H1-style alternative. The H2 asymmetry and the cross-asset
        H4 alternative are NOT simulated, so this curve says nothing about the
        design's power against THEM.
      * The beta = 0 row is a FALSE-POSITIVE DIAGNOSTIC, not a size calibration:
        under GW's method-level null with a fixed window, an irrelevant regressor
        raises the augmented method's UNCONDITIONAL expected loss, so the
        flow-favouring one-sided test is CONSERVATIVE at beta = 0 by construction.
        A rate below 5% there is the expected behaviour, not evidence about a
        conditional test or calibrated textbook size.

    What this function establishes: for an effect of size beta, how often would
    that one gate fire? Nothing more.
    """
    dgp = fit_calendar_har(rv, "rv_gk")
    idx = rv.index
    lr_real = np.log(rv["rv_gk"])
    lr_seed = lr_real.ffill().bfill().to_numpy()
    missing = rv["rv_gk"].isna().to_numpy()

    z_cal = ff.z.reindex(idx)
    shock = z_cal.abs().shift(1).fillna(0.0).to_numpy()     # |z_{d-1}|, as in H1
    ret_lag = rv["ret"].shift(1).fillna(0.0).to_numpy()
    aret_lag = rv["ret"].abs().shift(1).fillna(0.0).to_numpy()

    # Keep simulated log-variance inside a generous envelope of what the asset has
    # actually done. Without it a draw from the tail of the innovation block can
    # walk a persistent HAR into absurd territory and one path dominates the
    # rejection rate. `clip_rate` reports how often it binds.
    obs = lr_real.dropna()
    bounds = (float(obs.min()) - 3.0, float(obs.max()) + 3.0)

    rows = []
    for b in betas:
        rng = np.random.default_rng(SEED + int(round(b * 10_000)))
        zs, clips, fails = [], 0, 0
        for _ in range(reps):
            lrv, nc = simulate_lrv(
                lr_seed, ret_lag, aret_lag, shock, dgp, b, rng, bounds
            )
            clips += nc
            sim = rv[["ret"]].copy()
            sim["rv_gk"] = np.exp(lrv)
            sim.loc[missing, "rv_gk"] = np.nan     # preserve the real missingness
            try:
                p = build_panel(sim, ff, "rv_gk", horizon, asset)
                po = paired_oos(p, "HAR+ctrl", "H1_absflow")
                if len(po.actual) < GW_MIN_LOSSES:
                    fails += 1
                    continue
                gw = gw_unconditional_dm(
                    qlike_pointwise(po.actual, po.pred_aug),
                    qlike_pointwise(po.actual, po.pred_base),
                    horizon,
                )
                zs.append(gw["z_stat"])
            except (ValueError, AssertionError):
                fails += 1
        z = np.asarray(zs)
        n_ok = len(z)
        rej_5 = float(np.mean(z < POWER_GATE_Z)) if n_ok else float("nan")
        rej_h = float(np.mean(z < -3.0)) if n_ok else float("nan")
        rows.append(
            {
                "beta": b,
                "rv_uplift_per_1sd_shock_pct": round((math.exp(b) - 1) * 100, 2),
                "reps_completed": n_ok,
                "reps_failed": fails,
                "power_gw_one_sided_5pct": rej_5,
                "power_gw_se": (
                    float(math.sqrt(max(rej_5 * (1 - rej_5), 0) / n_ok)) if n_ok else None
                ),
                "power_gw_harvey_z_lt_minus3": rej_h,
                "median_gw_z": float(np.median(z)) if n_ok else None,
                "clip_rate_per_path": round(clips / max(n_ok, 1) / len(idx), 6),
            }
        )

    size = next((r for r in rows if r["beta"] == 0.0), None)

    def _first_at(power: float) -> dict | None:
        return next((r for r in rows if r["power_gw_one_sided_5pct"] >= power), None)

    def _bracket(power: float) -> dict:
        """The INTERVAL that contains the power crossing. Never a point.

        The grid is coarse (8 betas), so the effect size at which power first
        reaches a target is only ever bracketed: it lies strictly between the last
        grid point BELOW the target and the first grid point AT OR ABOVE it. v1's
        signature error was turning a coarse curve into a precise-sounding number;
        reporting the upper grid point as "the 80%-power effect" would be a smaller
        version of the same move, so no point estimate is emitted at all -- only
        `lower_rv_uplift_pct` / `upper_rv_uplift_pct`, and `upper` is None when the
        grid never reaches the target (the crossing is then beyond the grid, or
        does not exist).
        """
        hit = _first_at(power)
        below = [r for r in rows if hit is None or r["beta"] < hit["beta"]]
        prev = below[-1] if below else None
        reached = hit is not None
        return {
            "target_power": power,
            "reached_on_grid": reached,
            "lower_rv_uplift_pct": prev["rv_uplift_per_1sd_shock_pct"] if prev else None,
            "lower_grid_power": prev["power_gw_one_sided_5pct"] if prev else None,
            "upper_rv_uplift_pct": hit["rv_uplift_per_1sd_shock_pct"] if reached else None,
            "upper_grid_power": hit["power_gw_one_sided_5pct"] if reached else None,
            "lower_beta": prev["beta"] if prev else None,
            "upper_beta": hit["beta"] if reached else None,
            "note": (
                (
                    "The crossing lies strictly INSIDE this interval. It is a bracket, "
                    "not a solved threshold, and must never be quoted as a single "
                    "number."
                )
                if reached
                else (
                    f"Power never reaches {power:.0%} anywhere on the grid (the "
                    f"largest effect simulated is +"
                    f"{rows[-1]['rv_uplift_per_1sd_shock_pct']}% RV uplift, where power "
                    f"is only {rows[-1]['power_gw_one_sided_5pct']:.2f}). No bracket "
                    "exists; the honest statement is 'not reached', not a number."
                )
            ),
        }

    return {
        "asset": asset,
        "horizon": horizon,
        "design": (
            "Semi-parametric DGP: calendar-day HAR+ctrl law of motion fitted on the "
            "real series, innovations drawn by circular moving-block bootstrap, real "
            "flow shocks and real returns retained, effect injected into the law of "
            "motion so it propagates through the HAR lags."
        ),
        "reps_per_beta": reps,
        "seed": SEED,
        "gate": (
            f"SINGLE-CELL nominal GW gate: z < {POWER_GATE_Z} (one-sided 5%), "
            "pre-specified. This is NOT the ten-cell Holm-corrected gate that "
            "produces the verdict."
        ),
        "scope": {
            "what_this_is": (
                "The power of ONE pre-specified cell's gate against a single "
                "injected alternative, at one horizon."
            ),
            "what_this_is_not": (
                "The power of the study. The verdict is adjudicated on a ten-cell "
                "family with a Holm correction, which is strictly less powerful than "
                "the nominal single-cell gate simulated here. No number in this "
                "object may be quoted as the design's family-wise power."
            ),
            "horizon_simulated": horizon,
            "primary_family_horizons": list(HORIZONS),
            "horizons_not_simulated": [h for h in HORIZONS if h != horizon],
            "alternative_simulated": (
                "a single |flow| z-shock injected into the HAR law of motion "
                "(the H1-style alternative)"
            ),
            "alternatives_not_simulated": [
                "H2_asym (signed / asymmetric flow response)",
                "H4_plus_btc (cross-asset BTC flow spillover into ETH)",
            ],
            "multiplicity_in_the_simulated_gate": "none (nominal 5%, single cell)",
            "multiplicity_in_the_actual_verdict": "Holm across the 10-cell family",
        },
        "dgp_persistence_phi_sum": round(dgp["persistence"], 4),
        "dgp_resid_sd": round(dgp["resid_sd"], 4),
        "false_positive_rate_at_beta_0": size["power_gw_one_sided_5pct"] if size else None,
        "false_positive_note": build_claim_surface_prose()[
            "power_false_positive_note"
        ],
        "curve": rows,
        "power_80pct_bracket": _bracket(0.80),
        "power_90pct_bracket": _bracket(0.90),
        "grid_note": build_claim_surface_prose()["power_grid_note"],
        "max_beta_tested": max(betas),
        "max_uplift_tested_pct": round((math.exp(max(betas)) - 1) * 100, 2),
        "scope_warning": build_claim_surface_prose()["power_scope_warning"],
    }


# ---------------------------------------------------------------------------
# 11. Main
# ---------------------------------------------------------------------------
def _serialize(rec: TestRecord, holm_p: float | None = None) -> dict:
    d = {
        "family": rec.family,
        "cell": rec.cell,
        "asset": rec.asset,
        "horizon": rec.horizon,
        "base": rec.base,
        "alt": rec.alt,
        "inference": rec.inference,
        "estimand": rec.estimand,
        "scheme": rec.scheme,
        "stat": round(rec.stat, 4) if np.isfinite(rec.stat) else None,
        "p_one_sided_raw": rec.p_one_sided,
        "feeds_gate": rec.feeds_gate,
        "bounded_memory": rec.bounded_memory,
        "qlike_improve_pct": (
            round(rec.qlike_improve_pct, 4) if rec.qlike_improve_pct is not None else None
        ),
        "n": rec.n,
    }
    if holm_p is not None:
        d["holm_adjusted_p"] = holm_p
    return d


def build_verdict_basis(
    verdict: str,
    *,
    n_cells: int,
    n_pass: int,
    n_excl: int,
    n_excl_holm: int,
    margin_pct: float,
    family_bound: float | None,
    per_cell_upper_bounds: dict,
    unbounded_memory_cells: tuple[str, ...] | list[str],
    n_registered_tests: int,
    n_gate_eligible_tests: int,
    n_full_family_significant: int,
    n_diagnostic_tests: int,
) -> dict:
    """Counts/provenance in, every substantive claim-scope sentence out.

    Final summary bullets, quantitative bounds, in-sample/OOS scope statements,
    power warnings, bounded-memory provenance and inferential figure labels are
    returned here. The renderer and frozen result record consume the exact strings
    instead of independently paraphrasing them.

    This separation makes a wording-only correction possible without fetching an
    unarchived, later vendor vintage. ``--relabel`` derives these strings from the
    frozen counts and refuses to write if any pre-existing non-string leaf moves.
    """
    prose = build_claim_surface_prose(
        n_cells=n_cells,
        margin_pct=margin_pct,
        family_bound=family_bound,
        unbounded_memory_cells=unbounded_memory_cells,
        n_registered_tests=n_registered_tests,
        n_gate_eligible_tests=n_gate_eligible_tests,
        n_full_family_significant=n_full_family_significant,
        n_diagnostic_tests=n_diagnostic_tests,
    )
    if verdict == "BOUNDED_NULL_NO_MATERIAL_QLIKE_GAIN":
        claim = (
            f"BOUNDED NULL. No primary cell clears the pre-specified Holm-adjusted "
            f"UNCONDITIONAL detection gate, and all {n_excl}/{n_cells} primary "
            f"cells REJECT the "
            "hypothesis that adding ETF flow improves UNCONDITIONAL expected QLIKE "
            "by at least "
            f"{margin_pct:.0f}% (intersection-union test, each cell unadjusted; "
            f"{n_excl_holm}/{n_cells} also survive the conservative Holm variant). "
            f"Defensible claim: 'spot BTC/ETH ETF net flow buys no material "
            f"({margin_pct:.0f}%+) UNCONDITIONAL average QLIKE-loss improvement "
            f"over a HAR-RV baseline, out of sample.' The bound does not cover "
            "conditional or regime-specific gains, RV-uplift magnitude, or exact "
            "zero."
        )
        detection_outcome = (
            f"The bounded-null verdict follows because no primary cell clears the "
            f"detection gate and all {n_excl}/{n_cells} cells clear the exclusion "
            f"test."
        )
        does_say_1 = (
            "On the UNCONDITIONAL average-loss estimand, spot BTC/ETH ETF net flow "
            "buys no material improvement in out-of-sample volatility forecast "
            "accuracy over a HAR-RV baseline: a "
            f">={margin_pct:.0f}% relative QLIKE gain is ruled out in all {n_cells} "
            "primary cells. This is a QLIKE-loss bound, not proof of exact zero."
        )
        does_say_2 = ""
        does_say_3 = ""
        exclusion_outcome_readme = (
            f"**{n_excl} / {n_cells}** cells reject H0 at the pre-specified "
            f"{margin_pct:.0f}% UNCONDITIONAL average relative QLIKE-loss margin. "
            "That margin was carried from K1701 and fixed before these results. "
            "Because every cell rejects it, the intersection-union bounded-null "
            "condition is established for that estimand only."
        )
    elif verdict == "INCONCLUSIVE_NO_EXACT_NULL_CLAIM":
        bound_txt = prose["family_bound_statement"]
        claim = (
            f"INCONCLUSIVE. No primary cell clears the pre-specified Holm-adjusted "
            f"UNCONDITIONAL detection gate, but only {n_excl}/{n_cells} primary "
            f"cells can rule out the pre-specified {margin_pct:.0f}% UNCONDITIONAL "
            "average relative QLIKE-loss gain, so "
            f"the bounded null is NOT established. Failure to reject equal accuracy "
            f"is not evidence of equality. The honest headline is: 'no robust "
            f"incremental UNCONDITIONAL predictive evidence was found for spot "
            f"BTC/ETH ETF flow over a HAR-RV baseline' -- a negative finding, not a "
            f"proven zero. {bound_txt}"
        )
        detection_outcome = (
            "The verdict is INCONCLUSIVE because the detection family finds no "
            "Holm-adjusted evidence and the exclusion conjunction does not hold in "
            "every cell."
        )
        does_say_1 = (
            "**No robust incremental UNCONDITIONAL predictive evidence was found** "
            "for spot BTC/ETH ETF net flow over a HAR-RV baseline. Not one of the "
            f"{n_cells} primary cells clears the pre-specified Holm-adjusted "
            "detection gate; the point estimates mostly run the wrong way."
        )
        does_say_2 = (
            "For the UNCONDITIONAL average-loss estimand, gains larger than "
            f"**{family_bound:.1f}%** in relative QLIKE are excluded "
            f"simultaneously across all {n_cells} cells."
            if family_bound is not None
            else ""
        )
        does_say_3 = (
            "For the UNCONDITIONAL average-loss estimand, only "
            f"{n_excl}/{n_cells} cells can rule out the pre-specified "
            f"{margin_pct:.0f}% gain, so this is a **negative finding, not a "
            "proven zero**. Calling it a null result would overstate the evidence."
        )
        exclusion_outcome_readme = (
            f"**{n_excl} / {n_cells}** cells reject H0 at the pre-specified "
            f"{margin_pct:.0f}% UNCONDITIONAL average relative QLIKE-loss margin. "
            "That margin was carried from K1701 and fixed before these results. "
            "Because the intersection-union conjunction fails, **the bounded null "
            "is not established** and the verdict is `INCONCLUSIVE`, not `NULL`."
        )
    else:
        claim = (
            f"POSITIVE. {n_pass}/{n_cells} primary cells clear the pre-specified "
            f"flow gate, providing Holm-adjusted evidence of incremental "
            f"UNCONDITIONAL predictive ability."
        )
        detection_outcome = (
            f"The positive verdict follows because {n_pass}/{n_cells} primary cells "
            "clear the pre-specified detection gate."
        )
        does_say_1 = claim
        does_say_2 = ""
        does_say_3 = ""
        exclusion_outcome_readme = (
            f"{n_excl}/{n_cells} cells reject the pre-specified UNCONDITIONAL "
            f"average relative QLIKE-loss margin of {margin_pct:.0f}%. That margin "
            "was carried from K1701 and fixed before these results."
        )

    return {
        **prose,
        "test": (
            "TWO pre-specified objects, with OPPOSITE multiplicity treatments, and "
            "the verdict is a function of both. (1) DETECTION -- Giacomini-White "
            "(2006) Sec 3.4 UNCONDITIONAL special case (instrument h_t = 1, which "
            "coincides with a HAC Diebold-Mariano t; NOT the conditional GW test -- "
            "no instrument vector, no Wald statistic, no chi-square_q), one-sided "
            "and flow-favouring, HOLM-ADJUSTED across the 10-cell family (a union "
            "of alternatives: ten shots at finding an effect). (2) EXCLUSION -- the "
            "pre-specified one-sided material-gain test, run as an INTERSECTION-UNION "
            "test with each cell UNADJUSTED (Berger 1982): the bounded null may be "
            "asserted only if EVERY cell rejects its own exclusion null, which needs "
            "no correction. Holm-adjusted exclusion p-values are also reported as a "
            "conservative sensitivity, but they are NOT the test. The verdict is "
            f"determined by those two objects. {detection_outcome}"
        ),
        "test_detection": (
            "Giacomini-White (2006) Sec 3.4 unconditional special case (h_t = 1; "
            "equals HAC Diebold-Mariano), one-sided flow-favouring, Holm-adjusted "
            "across the 10-cell primary family"
        ),
        "test_exclusion": (
            "pre-specified one-sided material-gain exclusion, intersection-union "
            "across the 10-cell primary family, each cell UNADJUSTED"
        ),
        "conditional_predictive_ability_not_tested": (
            "The conditional GW test (h_t a non-trivial instrument, q x q moment "
            "covariance, Wald chi-square_q) is NOT run anywhere in this study. Every "
            "claim below is therefore UNCONDITIONAL: it is about the AVERAGE loss "
            "differential over the OOS sample. A flow effect that helps in one "
            "regime and hurts in another, netting to zero on average, would be "
            "invisible to this design and is NOT excluded by it."
        ),
        "loss": "Patton QLIKE on the variance level",
        "estimation_scheme": (
            f"paired fixed rolling window of {GW_TRAIN_WINDOW} flow days; both specs "
            "share the augmented complete-case mask, the training dates and the "
            "forward-label embargo (y_end_date < forecast origin). Every one of the "
            f"{n_cells} primary cells is therefore a BOUNDED-MEMORY forecasting "
            "method, which "
            "is the condition GW's limiting experiment needs. Every non-primary "
            "robustness row is `feeds_gate=false` and cannot broaden that claim. The "
            "two asset-specific `flow_transform/unexpected_z` rows are additionally "
            "`bounded_memory=false` because their regressor comes from an "
            "expanding-window AR(5); they are invalid-for-nested-inference diagnostics."
        ),
        "gate": (
            f"qlike_improve > 0 AND unconditional GW/DM z < {POWER_GATE_Z} "
            "AND Holm p < 0.05"
        ),
        "cells_in_primary_family": n_cells,
        "cells_passing_flow_gate": n_pass,
        "cells_excluding_material_gain": n_excl,
        "cells_excluding_material_gain_holm_conservative": n_excl_holm,
        "primary_detection_outcome_readme": (
            "For the UNCONDITIONAL average-loss primary family, "
            f"**{n_pass} / {n_cells}** cells pass the pre-specified Holm-adjusted "
            "flow-detection gate."
        ),
        "exclusion_outcome_readme": exclusion_outcome_readme,
        "exclusion_multiplicity_rationale": (
            "The exclusion family is an INTERSECTION-UNION test (Berger 1982): the "
            "bounded-null claim requires EVERY cell to reject its own exclusion null, "
            "so the conjunction holds at level alpha with each cell tested "
            "unadjusted. A Holm adjustment here would buy no type-I protection and "
            "only inflate type-II error. The detection family is the mirror image -- "
            "a union of alternatives, ten shots at finding an effect -- so it IS "
            "Holm-adjusted. Both numbers are reported; "
            f"{n_excl}/{n_cells} cells exclude unadjusted, "
            f"{n_excl_holm}/{n_cells} under the conservative Holm variant."
        ),
        "material_gain_margin_pct": margin_pct,
        "qlike_gain_upper_bound_95pct_per_cell": per_cell_upper_bounds,
        "qlike_gain_upper_bound_family_simultaneous_pct": family_bound,
        "upper_bound_method": (
            "Inverted one-sided exclusion test (Bonferroni alpha/m across the "
            f"{n_cells} primary cells). This -- not the power curve -- is the object "
            "that can bound the UNCONDITIONAL average-loss estimand. It lives in "
            "QLIKE-LOSS space, not conditional/regime-specific or RV-uplift space."
        ),
        "claim_strength": claim,
        "does_say_1_primary_evidence": does_say_1,
        "does_say_2_family_bound": does_say_2,
        "does_say_3_inconclusive_scope": does_say_3,
        "does_say_4_robustness": (
            "The flow-transform, RV-proxy, smearing, publication-lag and threshold "
            "panels are reported as diagnostics only; none broadens the 10-cell "
            "primary UNCONDITIONAL average-loss claim."
        ),
        "does_not_say_1_exact_zero": (
            "That the true effect is exactly zero. No test here establishes that."
        ),
        "does_not_say_2_rv_uplift": (
            "That an RV uplift of any particular size is excluded. The only reported "
            "bound is on the UNCONDITIONAL average relative QLIKE-loss gain."
        ),
        "does_not_say_3_conditional_effect": (
            "That flow lacks conditional or state-dependent predictive ability. The "
            "conditional GW test is not run; regime-specific effects that help in one "
            "state and hurt in another, netting to zero on average, are invisible to "
            "this design and are NOT excluded."
        ),
        "does_not_say_4_etf_level_effect": (
            "Anything about the level effect of ETF-ization on crypto volatility. "
            "The treatment here is flow, not the trading clock or session structure."
        ),
        "figure_3_stat_label": "uncond. GW/DM z={z:.2f}",
        "figure_3_title": (
            "Does ETF flow improve HAR out-of-sample average QLIKE?\n"
            "GW (2006) Sec. 3.4 UNCONDITIONAL / HAC-DM-form statistic, paired fixed "
            "rolling window (gate: z < -1.645 and Holm p < 0.05)"
        ),
        "figure_4_title": (
            "UNCONDITIONAL GW/DM z by shock threshold (negative = flow helps on "
            "average)"
        ),
        "figure_4_colorbar_label": "unconditional GW/DM z",
        "figure_5_power_label": (
            "power of one-cell UNCONDITIONAL GW/DM gate (z < -1.645)"
        ),
        "figure_5_bracket_label": (
            "80% one-cell power in +{lower}...+{upper}% RV-uplift bracket"
        ),
        "figure_5_panel_title": (
            "{asset}: one-cell power (beta=0 rejection rate {false_positive})"
        ),
        "figure_5_x_label": "assumed RV uplift per 1-sd flow shock (%)",
        "figure_5_y_label": "one-cell rejection rate",
        "figure_5_80_line_label": "80% one-cell power",
        "figure_5_nominal_line_label": "nominal 5% one-cell gate level",
        "figure_5_suptitle": (
            f"Power scope: one h=1 cell, one injected alternative, {POWER_REPS} "
            "simulated OOS paths per point, nominal gate. The 10-cell Holm family "
            "is less powerful. Power is not an exclusion and does not bound either "
            "UNCONDITIONAL average or conditional/regime-specific effects."
        ),
        "reproducibility_limitation": (
            "Neither the Farside flow response nor the Yahoo price response was "
            "archived point-in-time. The source URLs and sample endpoint identify "
            "what was queried, but cannot reconstruct the exact vendor bytes. Any "
            "live rerun may therefore change any statistic, gate count, bound or "
            "verdict; only --relabel and JSON-only rendering preserve this frozen "
            "numerical artefact."
        ),
        "fig2_event_day_limitation": (
            "The frozen fig2 is descriptive and has a one-day label shift: its x=0 "
            "is the first RV target day after the lagged flow observation, so the "
            "actual flow day is x=-1. It feeds no estimate, test or verdict. Future "
            "renders centre x=0 on the recorded flow source date explicitly."
        ),
        "bound_inversion_limitation": (
            "The frozen UNCONDITIONAL average-loss QLIKE upper bounds were produced "
            "by a binary inversion that assumed the rejection set was an upper "
            "tail. The primary streams were later found mildly non-monotone; a "
            "dense independent audit found one crossing per stream, so the "
            "published crossings did not move, but the frozen JSON does not archive "
            "the loss paths needed to reproduce that audit. Future runs verify the "
            "full rejection topology before reporting a bound."
        ),
        "withdrawn_v1_claim": (
            "v1 claimed it could 'rule out an RV uplift of >= +16.2% per 1-sd flow "
            "shock'. That number came from reading a single-path power curve "
            "backwards. Power is not an exclusion. The claim is WITHDRAWN and is not "
            "replaced by an RV-space bound of any size."
        ),
        "four_way_alignment": (
            "test = GW(2006) Sec 3.4 unconditional special case (= HAC DM) | "
            "loss = Patton QLIKE | scheme = paired fixed rolling window | "
            "claim = no robust evidence of UNCONDITIONAL incremental predictive "
            "ability, with any bound stated in QLIKE-loss space only. These four "
            "match by construction; v1's did not, and rev2's claim was broader than "
            "its test."
        ),
    }


def _apply_canonical_claim_surface_strings(res: dict, verdict_basis: dict) -> None:
    """Write canonical claim prose into every frozen JSON presentation site.

    Only strings are assigned. ``--relabel`` snapshots all typed leaves before
    calling this function and aborts if any number, boolean, null or container
    shape moves.
    """
    res["inference_design"]["bounded_null_test"] = verdict_basis[
        "bounded_null_test_scope"
    ]
    res["inference_design"]["power_is_not_exclusion"] = verdict_basis[
        "power_scope_warning"
    ]
    res["endogeneity_note"] = verdict_basis["endogeneity_claim_scope"]
    res["in_sample_note"] = verdict_basis["in_sample_claim_scope"]

    for collection in ("primary_cells", "all_cells"):
        for cell in res.get(collection, []):
            exclusion = cell.get("material_gain_exclusion")
            if not isinstance(exclusion, dict):
                continue
            exclusion["null"] = verdict_basis["material_gain_null"]
            exclusion["alternative"] = verdict_basis["material_gain_alternative"]
            exclusion["scope"] = verdict_basis["material_gain_scope"]
            exclusion["upper_bound_note"] = verdict_basis["upper_bound_note"]

    for row in res.get("h3_weekend_in_sample", {}).values():
        row["note"] = verdict_basis["h3_weekend_claim_scope"]
    for row in res.get("power_simulation", {}).values():
        row["scope_warning"] = verdict_basis["power_scope_warning"]
        row["grid_note"] = verdict_basis["power_grid_note"]
        row["false_positive_note"] = verdict_basis["power_false_positive_note"]

    sensitivity = res.get("multiple_testing", {}).get(
        "bounded_memory_sensitivity"
    )
    if isinstance(sensitivity, dict):
        sensitivity["issue"] = verdict_basis["bounded_memory_issue"]


def _non_string_leaf_surface(value, path: tuple = ()) -> dict:
    """Canonical path/type/value map for every non-string JSON leaf."""
    if isinstance(value, dict):
        out = {}
        for key, child in value.items():
            out.update(_non_string_leaf_surface(child, (*path, str(key))))
        return out
    if isinstance(value, list):
        out = {}
        for index, child in enumerate(value):
            out.update(_non_string_leaf_surface(child, (*path, index)))
        return out
    if isinstance(value, str):
        return {}
    return {path: (type(value).__name__, json.dumps(value, sort_keys=True))}


def _canonical_object_sha256(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _reconstruct_frozen_primary_training_provenance(res: dict) -> None:
    """Recover schedule hashes from already-frozen calendar metadata.

    The vendor values are not fetched. The frozen diagnostics establish that each
    flow series contains exactly every XNYS session between its recorded endpoints;
    the panel rule then fixes every eligible target and training date. We reproduce
    only those dates, assert their count/range against every frozen primary cell,
    and add string digests. No estimate or test statistic is recomputed.
    """
    by_asset: dict[str, pd.DatetimeIndex] = {}
    for asset in ("BTC", "ETH"):
        flow_diag = res["data_diagnostics"]["flows"][asset]
        sessions = us_equity_sessions(
            pd.Timestamp(flow_diag["date_min"]), pd.Timestamp(flow_diag["date_max"])
        )
        if len(sessions) != flow_diag["n_obs"]:
            raise AssertionError(
                f"{asset}: frozen flow count no longer matches the XNYS calendar"
            )
        by_asset[asset] = sessions

    rv_max = {
        asset: pd.Timestamp(res["data_diagnostics"]["rv"][asset]["date_max"])
        for asset in ("BTC", "ETH")
    }
    for cell in res["primary_cells"]:
        asset = cell["asset"]
        horizon = cell["horizon"]
        flow_lag = cell["flow_lag"]
        dates = pd.DatetimeIndex(
            by_asset[asset][Z_WINDOW:] + pd.Timedelta(days=flow_lag)
        )
        dates = dates[
            dates + pd.Timedelta(days=horizon - 1) <= rv_max[asset]
        ]
        y_end = (dates + pd.Timedelta(days=horizon - 1)).to_numpy()
        origins: list[pd.Timestamp] = []
        schedules: list[str] = []
        for i in range(GW_TRAIN_WINDOW, len(dates)):
            end = int(
                np.searchsorted(y_end, dates[i].to_datetime64(), side="left")
            )
            end = min(end, i)
            start = end - GW_TRAIN_WINDOW
            if start < 0 or end - start < GW_MIN_LOSSES:
                continue
            origins.append(dates[i])
            schedules.append(_date_index_sha256(dates[start:end]))

        origin_index = pd.DatetimeIndex(origins)
        expected = (
            len(origin_index),
            str(origin_index.min().date()),
            str(origin_index.max().date()),
        )
        observed = (cell["n_oos"], cell["oos_start"], cell["oos_end"])
        if expected != observed or cell["oos_audit"]["n_origins"] != expected[0]:
            raise AssertionError(
                f"{cell['cell']}: reconstructed schedule {expected} != frozen {observed}"
            )
        schedule_sha256 = _string_sequence_sha256(schedules)
        cell["oos_audit"].update(
            {
                "common_complete_case_mask_sha256": _date_index_sha256(dates),
                "base_training_schedule_sha256": schedule_sha256,
                "aug_training_schedule_sha256": schedule_sha256,
                "origin_schedule_sha256": _date_index_sha256(origin_index),
            }
        )


def build_fixed_memory_runtime_evidence(res: dict) -> dict:
    """Build the generic, versioned evidence envelope consumed by the ratchet."""
    cells = {cell["cell"]: cell for cell in res["primary_cells"]}
    expected_ids = [
        cell["id"] for cell in NESTED_DM_FIXED_MEMORY_MANIFEST_V1["primary_cells"]
    ]
    if set(cells) != set(expected_ids) or len(cells) != len(expected_ids):
        raise AssertionError("runtime primary-cell inventory differs from the manifest")
    evidence_cells = []
    for cell_id in expected_ids:
        runtime_cell = cells[cell_id]
        audit = runtime_cell["oos_audit"]
        evidence_cells.append(
            {
                "id": cell_id,
                "common_complete_case_mask_sha256": audit[
                    "common_complete_case_mask_sha256"
                ],
                "base_training_schedule_sha256": audit[
                    "base_training_schedule_sha256"
                ],
                "aug_training_schedule_sha256": audit[
                    "aug_training_schedule_sha256"
                ],
                "origin_schedule_sha256": audit["origin_schedule_sha256"],
                "eligibility": "whole_method_fixed_memory_verified",
                "base_predictors": list(SPECS[runtime_cell["base"]]),
                "augmented_predictors": list(SPECS[runtime_cell["alt"]]),
            }
        )
    manifest_sha256 = _canonical_object_sha256(
        NESTED_DM_FIXED_MEMORY_MANIFEST_V1
    )
    return {
        "schema": "nested_dm_fixed_memory_runtime.v1",
        "manifest_sha256": manifest_sha256,
        "cell_inventory": "primary_cells",
        "gate_inventory": "multiple_testing.primary_family",
        "registry_inventory": "multiple_testing.full_family_holm",
        "statistic_record": "primary_inference_gw_qlike",
        "claim_record": "verdict_basis",
        "claim_scope": "unconditional_average_loss_only",
        "cells": evidence_cells,
    }


def _repair_frozen_gate_metadata(res: dict) -> set[tuple]:
    """Constrain gate metadata to the pre-registered primary family only."""
    before = _non_string_leaf_surface(res)
    invalid_cells = set(
        res["multiple_testing"]["bounded_memory_sensitivity"][
            "unbounded_memory_cells"
        ]
    )
    rows = res["multiple_testing"]["full_family_holm"]
    newly_diagnostic = 0
    for index, row in enumerate(rows):
        if row["family"] == "primary":
            if row.get("bounded_memory") is not True:
                raise AssertionError(f"{row['cell']}: primary record is not bounded")
            row["claim_role"] = "primary_unconditional_detection_gate"
            continue
        if before.get(
            ("multiple_testing", "full_family_holm", index, "feeds_gate")
        ) == ("bool", "true"):
            newly_diagnostic += 1
        row["feeds_gate"] = False
        if row["cell"] in invalid_cells:
            if row.get("bounded_memory") is not False:
                raise AssertionError(f"{row['cell']}: expected unbounded-memory record")
            row["claim_role"] = "invalid_for_nested_inference_diagnostic_only"
        else:
            row["claim_role"] = "non_primary_diagnostic_only"
    for row in res["multiple_testing"]["primary_family"]:
        row["claim_role"] = "primary_unconditional_detection_gate"
    for cell in res["primary_cells"]:
        statistic = cell["primary_inference_gw_qlike"]
        statistic.update(
            {
                "hac_kernel": "Bartlett",
                "hac_bandwidth_rule": "max(h-1, canonical_bandwidth(h,n))",
                "reference_distribution": "standard_normal",
            }
        )
    res["multiple_testing"]["n_gate_eligible_gw_tests"] = sum(
        bool(row["feeds_gate"]) for row in rows
    )
    res["multiple_testing"]["n_diagnostic_only_tests"] += newly_diagnostic
    res["multiple_testing"]["bounded_memory_sensitivity"][
        "n_gw_tests_bounded_memory"
    ] = sum(row["feeds_gate"] is True for row in rows)
    res["multiple_testing"]["registry_note"] = (
        "The primary family and gate-eligible count are registry-derived. The "
        "frozen full_family_holm array remains as a historical 54-row sensitivity "
        "inventory. Only the 10 pre-registered primary rows are gate-eligible; every "
        "non-primary row is feeds_gate=false. The two expanding-preprocessing rows "
        "are additionally marked invalid for nested inference."
    )
    res["multiple_testing"]["bounded_memory_sensitivity"]["note"] = (
        "Eligibility is decided from whole-method provenance before p-values are "
        "inspected. All robustness rows remain visible in the historical "
        "sensitivity array, but feeds_gate=false keeps them outside the claim sink. "
        "The two expanding-preprocessing rows are also invalid for nested inference."
    )
    res["rev1_review_residuals_fixed"]["R6_bounded_memory"] = (
        "Two asset-specific `flow_transform/unexpected_z` rows use an "
        "expanding-window AR(5) to build their regressor, so their forecasting "
        "methods are not bounded-memory. They remain visible but are flagged "
        "`bounded_memory=false`, `feeds_gate=false` and diagnostic-only before "
        "their p-values are read."
    )
    for cell in res["all_cells"]:
        if cell.get("bounded_memory") is False:
            cell["bounded_memory_caveat"] = (
                "The AR(5) that builds this regressor refits on an EXPANDING "
                "window of flow history. There is no lookahead, but the whole "
                "forecasting method is not bounded-memory. This row is retained "
                "as a diagnostic with feeds_gate=false and cannot enter a verdict."
            )
    after = _non_string_leaf_surface(res)
    return {path for path in set(before) | set(after) if before.get(path) != after.get(path)}


def relabel_frozen_results() -> None:
    """Migrate frozen labels/provenance without recomputing an estimate.

    String claims and schedule digests may be added. The only permitted typed-leaf
    correction is the audited gate-scope repair: all 44 non-primary rows are
    ``feeds_gate=false`` and three registry counts are reconciled. Every estimate,
    test statistic, p-value, bound, and all other typed leaves remain identical.
    """
    path = OUT / "k1709_results.json"
    with open(path) as fh:
        res = json.load(fh)
    repaired_paths = _repair_frozen_gate_metadata(res)
    allowed_repairs = {
        ("multiple_testing", "n_gate_eligible_gw_tests"),
        ("multiple_testing", "n_diagnostic_only_tests"),
        (
            "multiple_testing",
            "bounded_memory_sensitivity",
            "n_gw_tests_bounded_memory",
        ),
        *{
            ("multiple_testing", "full_family_holm", index, "feeds_gate")
            for index, row in enumerate(res["multiple_testing"]["full_family_holm"])
            if row.get("family") != "primary"
        },
    }
    if repaired_paths - allowed_repairs:
        raise SystemExit(
            "frozen gate-metadata repair touched an unapproved non-string leaf: "
            f"{sorted(repaired_paths - allowed_repairs, key=repr)}"
        )
    _reconstruct_frozen_primary_training_provenance(res)
    frozen_non_strings = _non_string_leaf_surface(res)
    old = res["verdict_basis"]
    new = build_verdict_basis(
        res["verdict"],
        n_cells=old["cells_in_primary_family"],
        n_pass=old["cells_passing_flow_gate"],
        n_excl=old["cells_excluding_material_gain"],
        n_excl_holm=old["cells_excluding_material_gain_holm_conservative"],
        margin_pct=old["material_gain_margin_pct"],
        family_bound=old["qlike_gain_upper_bound_family_simultaneous_pct"],
        per_cell_upper_bounds=old["qlike_gain_upper_bound_95pct_per_cell"],
        unbounded_memory_cells=res["multiple_testing"][
            "bounded_memory_sensitivity"
        ]["unbounded_memory_cells"],
        n_registered_tests=res["multiple_testing"]["n_tests_registered_total"],
        n_gate_eligible_tests=res["multiple_testing"][
            "n_gate_eligible_gw_tests"
        ],
        n_full_family_significant=res["multiple_testing"][
            "n_full_family_holm_significant_at_05"
        ],
        n_diagnostic_tests=res["multiple_testing"]["n_diagnostic_only_tests"],
    )
    res["verdict_basis"] = new
    _apply_canonical_claim_surface_strings(res, new)
    res["nested_dm_fixed_memory_evidence_v1"] = (
        build_fixed_memory_runtime_evidence(res)
    )
    tmp = OUT / "k1709_results.json.tmp"
    with open(tmp, "w") as fh:
        json.dump(res, fh, indent=2, default=str)
    with open(tmp) as fh:
        back = json.load(fh)
    if _non_string_leaf_surface(back) != frozen_non_strings:
        tmp.unlink(missing_ok=True)
        raise SystemExit("relabel moved a non-string JSON leaf -- refusing")
    os.replace(tmp, path)
    changed = [
        k
        for k, v in old.items()
        if isinstance(v, str) and k in new and new[k] != v
    ]
    removed = [k for k in old if k not in new]
    added = [k for k in new if k not in old]
    print(f"relabelled {len(changed)} claim sentence(s): {', '.join(changed)}")
    if removed:
        print(f"removed obsolete claim sentence(s): {', '.join(removed)}")
    if added:
        print(f"added: {', '.join(added)}")
    print(
        "all estimates unchanged; only allowlisted non-primary gate flags and "
        "their three registry counts may differ from the pre-migration freeze"
    )


def main() -> None:
    res: dict = {
        "experiment_id": "k1709",
        "revision": (
            "rev4 — frozen-estimate claim-surface repair after the 2026-07-14 "
            "independent rev3 review"
        ),
        "title": "Spot BTC/ETH ETF net flow shocks and realized volatility",
        "seed": SEED,
        "orthogonality": (
            "Treatment is the ETF creation/redemption FLOW itself, not the "
            "trading-clock / session-structure effect of ETF-ization."
        ),
        "information_set": (
            "Forecast origin = 00:00 UTC ending calendar day t. Farside publishes "
            "day-t flows ~21:00 UTC on day t, so flow_t and the completed UTC day-t "
            "RV are both known; target RV_{t+1..t+h} lies entirely ahead. State "
            "controls carry state_lag=1 always; only the flow carries flow_lag."
        ),
        "inference_design": {
            "problem": (
                "HAR+ctrl vs HAR+ctrl+flow is a STRICTLY NESTED comparison of "
                "forecasting methods. What breaks an ordinary loss-difference "
                "statistic is nesting COMBINED WITH an estimation scheme whose "
                "estimation error vanishes: under an expanding (recursive) window the "
                "two methods' forecasts converge under the null, the loss "
                "differential degenerates and the statistic tilts toward the smaller "
                "model. That is v1's design. Under a FIXED ROLLING window the "
                "estimation error survives in the limit, the loss differential keeps "
                "a non-degenerate variance, and the comparison is legal again -- "
                "which is exactly why the scheme was changed, and why it would be "
                "wrong to keep calling the fixed-window statistic 'biased toward the "
                "smaller model'."
            ),
            "claim_bearing_test": (
                "Giacomini-White (2006) equal unconditional predictive ability on "
                "Patton QLIKE, from a PAIRED FIXED ROLLING WINDOW (both specs share "
                "the augmented complete-case mask, the training dates, the embargo "
                "and the window length)."
            ),
            "bounded_null_test": build_claim_surface_prose()[
                "bounded_null_test_scope"
            ],
            "diagnostic_only": (
                "Raw Diebold-Mariano (HAC, canonical bandwidth) and Clark-West are "
                "reported but tagged feeds_gate=false -- for two DIFFERENT reasons, "
                "which the results file keeps apart. The EXPANDING-window statistic "
                "is diagnostic because it is invalid (degenerate null). The "
                "FIXED-window statistic is diagnostic because the verdict was "
                "pre-registered on the Giacomini-White object, NOT because it is "
                "invalid: it runs on the same legal loss stream and matches the gate "
                "statistic to ~3 decimals. Clark-West scores a DIFFERENT estimand "
                "(variance-level MSPE), so it is never relabelled as a QLIKE "
                "general-loss test -- that relabelling is what the review flagged as "
                "CRITICAL in v1."
            ),
            "power_is_not_exclusion": build_claim_surface_prose()[
                "power_scope_warning"
            ],
        },
        "v1_defects_fixed": {
            "C1": "nested comparison no longer inferred with raw DM / mislabelled CW",
            "C2": "MDE replaced by a real power simulation + a real exclusion test",
            "C3": "US market holidays no longer counted as genuine zero-flow days",
            "C4": "state_lag and flow_lag are now separate",
            "C5": "HLN mislabelling corrected; one-sided p unified to Student-t",
            "C6": "Holm uses raw p; the family is derived from a single test registry",
            "C7": "README numbers regenerated from the results JSON",
        },
        "rev1_review_residuals_fixed": {
            "note": (
                "Six methodology/wording residuals found by an independent re-review "
                "of the frozen commit 34c291a4. NOT ONE OF THEM CHANGED AN ESTIMATE -- "
                "they are all about what a reader is entitled to conclude from the "
                "estimates, which is the failure mode that got v1 FAILed. Be precise "
                "about the one thing that did move between the two runs: it was the "
                "DATA, not the fixes. Yahoo back-filled a calendar day it had "
                "previously dropped (2026-07-12 -> 2026-07-13), which adds one "
                "out-of-sample observation to the h=5 cells and shifts their GW z in "
                "the third decimal. The h=1 statistics, the verdict, every gate count "
                "and the family-wide bound are bit-identical across the two runs."
            ),
            "R1_power_overclaim": (
                "The power curve is now explicitly scoped: single cell, h = 1, one "
                "injected alternative, nominal gate. It was being read as the study's "
                "power. See power_simulation.scope."
            ),
            "R2_spurious_precision": (
                "The 80%/90%-power effect sizes are now BRACKETS only. The point "
                "fields (`rv_uplift_at_80pct_power_pct` and friends) are DELETED, not "
                "merely annotated -- a coarse grid cannot produce a point estimate, "
                "and leaving one in the JSON invites exactly the quotation it warns "
                "against."
            ),
            "R3_beta0_is_not_size": (
                "The beta = 0 row is a false-positive diagnostic, not a size "
                "calibration. The 'size-calibrated' wording is gone from the module "
                "docstring and the figure legend."
            ),
            "R4_fixed_window_dm_mislabelled": (
                "The fixed-window raw Diebold-Mariano statistic was tagged 'biased "
                "toward the smaller model', which contradicts the very reason the "
                "scheme was changed. The role text is now scheme-specific: the "
                "expanding one is invalid, the fixed one is valid-but-not-the-gate."
            ),
            "R5_verdict_basis_alignment": (
                "verdict_basis.test named only the Holm-adjusted detection family, "
                "although the verdict is co-determined by the unadjusted "
                "intersection-union exclusion test. Both are now named, with their "
                "opposite multiplicity treatments."
            ),
            "R6_bounded_memory": (
                "Two asset-specific `flow_transform/unexpected_z` rows use an "
                "expanding-window AR(5) to build their regressor, so their forecasting "
                "methods are not bounded-memory. They remain visible but are flagged "
                "`bounded_memory=false`, `feeds_gate=false` and diagnostic-only before "
                "their p-values are read."
            ),
        },
    }

    flows, fdiag, rvs, rdiag, feats = {}, {}, {}, {}, {}
    for a in ("BTC", "ETH"):
        flows[a], fdiag[a] = fetch_flows(a)
        rvs[a], rdiag[a] = fetch_rv(a)
        feats[a] = make_flow_features(flows[a])
        print(
            f"[{a}] flow n={fdiag[a]['n_obs']} "
            f"{fdiag[a]['date_min']}..{fdiag[a]['date_max']} "
            f"neg={fdiag[a]['share_negative']:.1%} "
            f"(dropped {fdiag[a]['n_nonsession_rows_dropped']} non-session rows) | "
            f"rv n={rdiag[a]['n_daily_obs']}"
        )
    res["data_diagnostics"] = {"flows": fdiag, "rv": rdiag}

    # --- endogeneity diagnostic: does flow chase contemporaneous vol/return? --
    endo = {}
    for a in ("BTC", "ETH"):
        j = pd.DataFrame(
            {
                "flow": flows[a]["flow"],
                "rv": rvs[a]["rv_gk"].reindex(flows[a].index),
                "ret": rvs[a]["ret"].reindex(flows[a].index),
            }
        ).dropna()
        endo[a] = {
            "corr_flow_vs_same_day_return": round(float(j["flow"].corr(j["ret"])), 4),
            "corr_flow_vs_same_day_logrv": round(
                float(j["flow"].corr(np.log(j["rv"]))), 4
            ),
            "corr_absflow_vs_same_day_logrv": round(
                float(j["flow"].abs().corr(np.log(j["rv"]))), 4
            ),
            "n": int(len(j)),
        }
    res["endogeneity_diagnostic"] = endo
    res["endogeneity_note"] = build_claim_surface_prose()[
        "endogeneity_claim_scope"
    ]

    btc_z_cal = feats["BTC"].z

    panels: dict[tuple, Panel] = {}
    for a in ("BTC", "ETH"):
        for h in HORIZONS:
            bz = btc_z_cal if a == "ETH" else None
            p = build_panel(rvs[a], feats[a], "rv_gk", h, a, flow_lag=1, btc_z=bz)
            assert_no_lookahead(p)
            panels[(a, h)] = p
            print(
                f"  panel {a} h={h}: n={len(p.df)} "
                f"{p.df.index.min().date()}..{p.df.index.max().date()}"
            )

    # --- in-sample (descriptive) ---------------------------------------------
    insample = {}
    for (a, h), p in panels.items():
        for spec in ("HAR", "HAR+ctrl", "H1_absflow", "H2_asym"):
            insample[f"{a}_h{h}_{spec}"] = in_sample(p, spec)
    res["in_sample"] = insample
    res["in_sample_note"] = build_claim_surface_prose()["in_sample_claim_scope"]

    # --- PRIMARY family: H1 / H2 on both assets and horizons ------------------
    cells = []
    for (a, h), p in panels.items():
        for alt in ("H1_absflow", "H2_asym"):
            c = evaluate_cell(p, "HAR+ctrl", alt, family="primary")
            if c:
                cells.append(c)

    # --- PRIMARY family: BTC flow -> ETH RV spillover -------------------------
    for h in HORIZONS:
        p = panels[("ETH", h)]
        pf = Panel(
            p.df.dropna(subset=["abs_z_btc"]), p.rv_col, h, "ETH",
            state_lag=p.state_lag, flow_lag=p.flow_lag,
        )
        c = evaluate_cell(pf, "H4_own", "H4_plus_btc", family="primary")
        if c:
            c["description"] = "BTC flow shock -> ETH RV, controlling ETH's own flow"
            cells.append(c)
    # A COPY. `= cells` aliased the same list object, so every robustness cell
    # appended below silently landed in "primary_cells" too.
    res["primary_cells"] = list(cells)
    primary_cell_keys = {c["cell"] for c in cells}

    # --- ROBUSTNESS: RV proxy ------------------------------------------------
    for a in ("BTC", "ETH"):
        for col in ("rv_park", "rv_r2", "rv_hourly"):
            if rvs[a][col].notna().sum() < 300:
                continue
            p = build_panel(rvs[a], feats[a], col, 1, a, flow_lag=1)
            assert_no_lookahead(p)
            c = evaluate_cell(p, "HAR+ctrl", "H1_absflow", family="rv_proxy")
            if c:
                cells.append(c)

    # --- ROBUSTNESS: conservative publication lag (C4 — flow only) ------------
    for a in ("BTC", "ETH"):
        for h in HORIZONS:
            p = build_panel(rvs[a], feats[a], "rv_gk", h, a, flow_lag=2, state_lag=1)
            assert_no_lookahead(p)
            c = evaluate_cell(p, "HAR+ctrl", "H1_absflow", family="flow_lag2")
            if c:
                c["description"] = (
                    "flow_lag=2 (flow usable only at the end of t+1) while "
                    "state_lag stays 1: RV_{t+1} and ret_{t+1} ARE known by then. "
                    "v1 wrongly lagged the state controls too, handicapping its own "
                    "baseline."
                )
                cells.append(c)

    # --- ROBUSTNESS: smearing (is the null an artifact of the log->level map?) -
    for a in ("BTC", "ETH"):
        for h in HORIZONS:
            for sm in ("none", "shared"):
                c = evaluate_cell(
                    panels[(a, h)], "HAR+ctrl", "H1_absflow",
                    family=f"smearing_{sm}", smearing=sm,
                )
                if c:
                    cells.append(c)

    # --- ROBUSTNESS: flow transforms (Warther 1995) ---------------------------
    CTRL = SPECS["HAR+ctrl"]
    TRANSFORMS = {
        "signed_z": "z_signed",
        "squared_z": "z_sq",
        "gross_churn_z": "abs_z_gross",
        "unexpected_z": "abs_z_unexp",
    }
    for a in ("BTC", "ETH"):
        p = panels[(a, 1)]
        for label, col in TRANSFORMS.items():
            if col not in p.df.columns:
                continue
            SPECS[f"T_{label}"] = CTRL + [col]
            pt = Panel(
                p.df.dropna(subset=[col]), p.rv_col, 1, a,
                state_lag=p.state_lag, flow_lag=p.flow_lag,
            )
            # The AR(5)-unexpected transform is the one cell in the whole study
            # whose forecasting METHOD lacks bounded estimator memory: the AR(5)
            # that builds the regressor refits on an expanding window of flow
            # history. Its statistic is registered as a transparent diagnostic,
            # but method provenance makes it gate-ineligible before its p-value is
            # inspected. It cannot enter a GW family or verdict.
            c = evaluate_cell(
                pt, "HAR+ctrl", f"T_{label}", family="flow_transform",
                bounded_memory=(label != "unexpected_z"),
            )
            if c:
                c["transform"] = label
                c["in_sample_t"] = in_sample(pt, f"T_{label}")["coef"][col]["t"]
                if label == "unexpected_z":
                    c["bounded_memory_caveat"] = (
                        "The AR(5) that builds this regressor refits on an EXPANDING "
                        "window of flow history. There is no lookahead (day i's own "
                        "value never enters its own fit), but the forecasting METHOD "
                        "does not have the bounded estimator memory GW formally "
                        "assumes. Read this cell's statistic as diagnostic only. None "
                        "of the 10 primary cells uses this column; method provenance "
                        "sets `feeds_gate=false` before the p-value is read."
                    )
                cells.append(c)

    # --- ROBUSTNESS: shock-threshold dummies ---------------------------------
    for (a, h), p in panels.items():
        for thr in (1.0, 1.5, 2.0, 2.5):
            d = p.df.copy()
            d["abs_z"] = (d["abs_z"] >= thr).astype(float)   # shock DUMMY
            pt = Panel(d, p.rv_col, h, a, state_lag=p.state_lag, flow_lag=p.flow_lag)
            c = evaluate_cell(
                pt, "HAR+ctrl", "H1_absflow", family="threshold",
                variant=f"thr{thr}",
            )
            if c:
                c["threshold"] = thr
                c["n_shock_days"] = int((p.df["abs_z"] >= thr).sum())
                cells.append(c)

    # --- ROBUSTNESS: shorter ETH burn-in --------------------------------------
    for h in HORIZONS:
        c = evaluate_cell(
            panels[("ETH", h)], "HAR+ctrl", "H1_absflow",
            family="eth_window", train_window=200,
        )
        if c:
            cells.append(c)

    res["all_cells"] = cells

    # --- H3: Friday flow -> weekend RV (IN-SAMPLE, descriptive) ---------------
    h3 = {}
    for a in ("BTC", "ETH"):
        p = build_panel(rvs[a], feats[a], "rv_gk", 2, a, flow_lag=1)   # Sat+Sun mean
        assert_no_lookahead(p)
        fri = p.df[p.df["dow_src"] == 4].copy()
        cols = SPECS["H1_absflow"]
        fri = fri.dropna(subset=cols)
        Xf = fri[cols].to_numpy(float)
        yf_ = np.log(fri["y"].to_numpy(float))
        b = _ols(Xf, yf_)
        se = _hac_se(Xf, yf_, b, max(1, canonical_bandwidth(1, len(fri))))
        names = ["const"] + cols
        i_z = names.index("abs_z")
        t_z = float(b[i_z] / se[i_z]) if se[i_z] > 0 else 0.0
        h3[a] = {
            "description": "Friday ETF flow -> mean GK RV over Sat+Sun (weekend gap)",
            "inference": "in-sample HAC t on the abs_z coefficient",
            "feeds_gate": False,
            "note": build_claim_surface_prose()["h3_weekend_claim_scope"],
            "n_fridays": int(len(fri)),
            "coef": {
                nm: {
                    "beta": round(float(bb), 5),
                    "t": round(float(bb / ss) if ss > 0 else 0.0, 3),
                }
                for nm, bb, ss in zip(names, b, se)
            },
            "abs_z_t": round(t_z, 3),
            "abs_z_p_two_sided": float(
                2 * stats.t.sf(abs(t_z), df=max(len(fri) - len(names), 1))
            ),
        }
    res["h3_weekend_in_sample"] = h3

    # --- Multiple testing, derived from the registry (C6) ----------------------
    gw_registered = [
        r for r in REGISTRY if r.inference == "giacomini_white_qlike_fixed_window"
    ]
    gw_all = [r for r in gw_registered if r.feeds_gate]
    gw_primary = [r for r in gw_all if r.family == "primary"]
    if not gw_primary:
        raise AssertionError("primary family is empty — nothing to adjudicate")

    holm_primary = holm([r.p_one_sided for r in gw_primary])
    holm_full = holm([r.p_one_sided for r in gw_all])

    by_cell = {c["cell"]: c for c in cells}
    if len(by_cell) != len(cells):
        raise AssertionError("cell keys are not unique; the verdict join is unsafe")
    # every primary GW record must resolve to a cell that really is primary
    for rec in gw_primary:
        if rec.cell not in primary_cell_keys:
            raise AssertionError(
                f"primary registry record {rec.cell!r} does not resolve to a primary "
                "cell -- the registry/loss-cache join has drifted"
            )
    excl_p = [
        by_cell[r.cell]["material_gain_exclusion"]["p_value_one_sided"]
        for r in gw_primary
    ]
    excl_z = [by_cell[r.cell]["material_gain_exclusion"]["z_stat"] for r in gw_primary]
    holm_excl = holm(excl_p)

    # The two families need OPPOSITE multiplicity treatments, because the two
    # claims have opposite logical structure. This asymmetry is not a convenience;
    # it is what the claims actually require.
    #
    #   "flow helps SOMEWHERE"     -> a UNION of alternatives. Ten shots at finding
    #                                 an effect, so the family-wise error must be
    #                                 controlled: Holm on the GW p-values.
    #
    #   "flow helps NOWHERE by >=m" -> an INTERSECTION of alternatives, i.e. an
    #                                 intersection-union test (Berger 1982). We may
    #                                 assert it only if EVERY cell rejects its own
    #                                 exclusion null. Under any configuration where
    #                                 the global claim is false, at least one null is
    #                                 true, and we wrongly reject it with probability
    #                                 <= alpha. The conjunction therefore holds at
    #                                 level alpha with NO adjustment -- and adjusting
    #                                 anyway would inflate type-II error while buying
    #                                 no type-I protection at all.
    #
    # Holm-adjusted exclusion p-values are still reported as a conservative
    # sensitivity, so the choice is auditable rather than asserted.
    primary_rows = []
    for r, hp, hz, hx, praw in zip(
        gw_primary, holm_primary, excl_z, holm_excl, excl_p
    ):
        row = _serialize(r, holm_p=hp)
        row["passes_flow_gate"] = bool(
            r.qlike_improve_pct is not None
            and r.qlike_improve_pct > 0
            and r.stat < POWER_GATE_Z
            and hp < 0.05
        )
        row["excludes_material_gain"] = bool(hz > 0 and praw < 0.05)   # IU: unadjusted
        row["material_gain_exclusion_p_raw"] = praw
        row["material_gain_exclusion_holm_p"] = hx
        row["excludes_material_gain_holm_conservative"] = bool(hz > 0 and hx < 0.05)
        ex = by_cell[r.cell]["material_gain_exclusion"]
        row["qlike_gain_upper_bound_95pct"] = ex["qlike_gain_upper_bound_95pct"]
        primary_rows.append(row)

    # Simultaneous (Bonferroni) upper bounds: each cell's one-sided bound computed
    # at alpha/m so the whole family holds jointly at 95%. Conservative on purpose.
    m = len(gw_primary)
    simultaneous = [
        qlike_gain_upper_bound_from_cell(r.cell, alpha=0.05 / m) for r in gw_primary
    ]
    for row, b in zip(primary_rows, simultaneous):
        row["qlike_gain_upper_bound_simultaneous"] = b
    finite = [b for b in simultaneous if b is not None]
    # The family-wide statement is only as strong as its WEAKEST cell: a bound that
    # holds for 9 cells and fails for the 10th does not hold for the family.
    family_bound = max(finite) if len(finite) == m else None

    n_pass = int(sum(r["passes_flow_gate"] for r in primary_rows))
    n_excl = int(sum(r["excludes_material_gain"] for r in primary_rows))
    n_excl_holm = int(
        sum(r["excludes_material_gain_holm_conservative"] for r in primary_rows)
    )
    all_excl = bool(primary_rows) and all(
        r["excludes_material_gain"] for r in primary_rows
    )

    # Bounded-memory audit. The AR(5)-unexpected transform is registered for
    # transparency but excluded from `gw_all` ex ante because its upstream fit is
    # expanding. This eligibility decision is provenance-based, not p-value-based.
    gw_bm = [r for r in gw_registered if r.bounded_memory and r.feeds_gate]
    gw_unbounded = [r for r in gw_registered if not r.bounded_memory]
    holm_bm = holm([r.p_one_sided for r in gw_bm])
    n_sig_all = int(sum(hp < 0.05 and r.stat < 0 for r, hp in zip(gw_all, holm_full)))
    n_sig_bm = int(sum(hp < 0.05 and r.stat < 0 for r, hp in zip(gw_bm, holm_bm)))

    res["multiple_testing"] = {
        "registry_note": (
            "The families below are DERIVED from the in-code test registry, not "
            "hand-listed. v1 hand-listed 'EVERY DM test' and missed 8 of them. Holm "
            "runs on RAW p-values; rounding happens only at serialization."
        ),
        "n_tests_registered_total": len(REGISTRY),
        "n_gate_eligible_gw_tests": len(gw_all),
        "n_diagnostic_only_tests": len([r for r in REGISTRY if not r.feeds_gate]),
        "primary_family": primary_rows,
        "full_family_holm": [
            _serialize(r, holm_p=hp) for r, hp in zip(gw_all, holm_full)
        ],
        "n_full_family_holm_significant_at_05": n_sig_all,
        "bounded_memory_sensitivity": {
            "issue": build_claim_surface_prose(
                unbounded_memory_cells=tuple(sorted({r.cell for r in gw_unbounded})),
                n_registered_tests=len(REGISTRY),
            )["bounded_memory_issue"],
            "n_gw_tests_all": len(gw_registered),
            "n_gw_tests_bounded_memory": len(gw_bm),
            "unbounded_memory_cells": sorted(
                {r.cell for r in gw_unbounded}
            ),
            "n_full_family_holm_significant_at_05": n_sig_all,
            "n_full_family_holm_significant_at_05_bounded_memory_only": n_sig_bm,
            "conclusion_depends_on_the_unbounded_cell": bool(n_sig_all != n_sig_bm),
            "note": (
                "The expanding-preprocessing rows remain visible diagnostics, but "
                "whole-method provenance sets feeds_gate=false before their p-values "
                "are read. They cannot enter a GW family or verdict."
            ),
            "primary_family_is_entirely_bounded_memory": bool(
                all(r.bounded_memory for r in gw_primary)
            ),
        },
    }

    # --- Power (design sensitivity, NOT an exclusion) -------------------------
    print(
        f"\nrunning power simulation ({POWER_REPS} reps x "
        f"{len(POWER_BETAS)} betas x 2 assets)..."
    )
    res["power_simulation"] = {
        a: power_simulation(rvs[a], feats[a], a, horizon=1) for a in ("BTC", "ETH")
    }

    # --- VERDICT --------------------------------------------------------------
    if n_pass > 0:
        verdict = "POSITIVE_INCREMENTAL_PREDICTIVE_CONTENT"
    elif all_excl:
        verdict = "BOUNDED_NULL_NO_MATERIAL_QLIKE_GAIN"
    else:
        verdict = "INCONCLUSIVE_NO_EXACT_NULL_CLAIM"
    res["verdict"] = verdict

    verdict_basis = build_verdict_basis(
        verdict,
        n_cells=len(primary_rows),
        n_pass=n_pass,
        n_excl=n_excl,
        n_excl_holm=n_excl_holm,
        margin_pct=100 * MATERIAL_GAIN_MARGIN,
        family_bound=family_bound,
        per_cell_upper_bounds={
            row["cell"]: row["qlike_gain_upper_bound_95pct"] for row in primary_rows
        },
        unbounded_memory_cells=res["multiple_testing"][
            "bounded_memory_sensitivity"
        ]["unbounded_memory_cells"],
        n_registered_tests=res["multiple_testing"]["n_tests_registered_total"],
        n_gate_eligible_tests=res["multiple_testing"][
            "n_gate_eligible_gw_tests"
        ],
        n_full_family_significant=res["multiple_testing"][
            "n_full_family_holm_significant_at_05"
        ],
        n_diagnostic_tests=res["multiple_testing"]["n_diagnostic_only_tests"],
    )
    res["verdict_basis"] = verdict_basis
    _apply_canonical_claim_surface_strings(res, verdict_basis)
    res["nested_dm_fixed_memory_evidence_v1"] = (
        build_fixed_memory_runtime_evidence(res)
    )

    make_plots(flows, rvs, panels, res)

    tmp = OUT / "k1709_results.json.tmp"
    with open(tmp, "w") as fh:
        json.dump(res, fh, indent=2, default=str)
    with open(tmp) as fh:
        json.load(fh)                      # parse before replacing
    os.replace(tmp, OUT / "k1709_results.json")

    print("\n" + "=" * 78)
    print("PRIMARY FAMILY (paired fixed-window UNCONDITIONAL GW/DM on QLIKE):")
    for r in primary_rows:
        label = f"{r['asset']} h={r['horizon']} {r['alt']}"
        ub = r["qlike_gain_upper_bound_95pct"]
        print(
            f"  {label:24s} QLIKE {r['qlike_improve_pct']:+7.3f}%  "
            f"uncond. GW/DM z={r['stat']:+6.2f} "
            f"(Holm p={r['holm_adjusted_p']:.3f})  "
            f"excl({verdict_basis['material_gain_margin_pct']:.0f}%)="
            f"{'Y' if r['excludes_material_gain'] else 'n'}  "
            f"ub95={'n/a' if ub is None else f'{ub:.2f}%'}"
        )
    for a in ("BTC", "ETH"):
        pw = res["power_simulation"][a]
        br = pw["power_80pct_bracket"]
        if br["reached_on_grid"]:
            band = (
                f"between +{br['lower_rv_uplift_pct']}% and "
                f"+{br['upper_rv_uplift_pct']}% RV uplift"
            )
        else:
            band = f"NOT REACHED even at +{pw['max_uplift_tested_pct']}%"
        print(
            f"  power[{a}] (h={pw['horizon']}, single cell, nominal gate): "
            f"fires on pure noise {pw['false_positive_rate_at_beta_0']:.3f}  |  "
            f"80% power {band}"
        )
    print(f"\nVERDICT: {verdict}")
    print(verdict_basis["claim_strength"])


# ---------------------------------------------------------------------------
# 12. Figures
# ---------------------------------------------------------------------------
def make_plots(flows, rvs, panels, res) -> None:
    # Fig 1 — flow vs RV time series
    fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
    for ax, a in zip(axes, ("BTC", "ETH")):
        ax.bar(flows[a].index, flows[a]["flow"], width=1.0,
               color=np.where(flows[a]["flow"] >= 0, "#2a9d8f", "#e76f51"), alpha=.8)
        ax.set_ylabel(f"{a} ETF net flow ($M)")
        ax2 = ax.twinx()
        v = np.sqrt(rvs[a]["rv_gk"] * 365) * 100
        ax2.plot(v.index, v.rolling(7).mean(), color="#264653", lw=1.2,
                 label="GK vol (7d MA, ann. %)")
        ax2.set_ylabel("annualised GK vol (%)")
        ax2.legend(loc="upper right", fontsize=8)
        ax.set_title(f"{a}: spot-ETF net creation/redemption flow vs realized volatility")
    axes[1].set_xlabel("date")
    fig.tight_layout()
    fig.savefig(OUT / "fig1_flow_vs_rv.png", dpi=130)
    plt.close(fig)

    # Fig 2 — event-window mean RV path around large flow shocks
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.4))
    for ax, a in zip(axes, ("BTC", "ETH")):
        rv = rvs[a]["rv_gk"]
        lv = np.log(rv)
        z = panels[(a, 1)].df["z"]
        base = lv.rolling(60).mean()
        for lab, mask, col in [
            ("|z| > 2 inflow", z > 2, "#2a9d8f"),
            ("|z| > 2 outflow", z < -2, "#e76f51"),
        ]:
            # `z` is already lagged onto the next-day forecast origin. Centre the
            # descriptive event study on its recorded source date, not on the
            # target origin one day later.
            ev = panels[(a, 1)].df.loc[mask.fillna(False), "flow_src_date"]
            paths = []
            for d in ev:
                i = rv.index.get_indexer([d], method="nearest")[0]
                if i - 5 < 0 or i + 6 >= len(rv) or np.isnan(base.iloc[i]):
                    continue
                paths.append((lv.iloc[i - 5 : i + 6].to_numpy() - base.iloc[i]))
            if paths:
                m = np.nanmean(np.vstack(paths), axis=0)
                ax.plot(range(-5, 6), m, marker="o", ms=3.5, color=col,
                        label=f"{lab} (n={len(paths)})")
        ax.axvline(0, color="grey", ls="--", lw=.8)
        ax.axhline(0, color="k", lw=.6)
        ax.set_title(f"{a}: log-RV around flow shocks")
        ax.set_xlabel("days from flow-shock day (0 = recorded flow source date)")
        ax.set_ylabel("log RV − 60d mean")
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "fig2_event_window.png", dpi=130)
    plt.close(fig)

    make_frozen_result_plots(res)


def make_frozen_result_plots(res: dict) -> None:
    """Render figures 3--5 from frozen JSON only; never fetch vendor data."""
    vb = res["verdict_basis"]

    # Fig 3 — OOS QLIKE + the unconditional GW/DM statistic, primary cells
    prim = [c for c in res["primary_cells"]]
    fig, ax = plt.subplots(figsize=(12, 4.8))
    labs = [f"{c['asset']}\nh={c['horizon']}\n{c['alt']}" for c in prim]
    x = np.arange(len(prim))
    ax.bar(x - .2, [c["qlike_base"] for c in prim], .4,
           label="baseline (HAR+ctrl)", color="#264653")
    ax.bar(x + .2, [c["qlike_alt"] for c in prim], .4,
           label="+ ETF flow", color="#e9c46a")
    for i, c in enumerate(prim):
        ax.text(i, max(c["qlike_base"], c["qlike_alt"]) * 1.02,
                vb["figure_3_stat_label"].format(
                    z=c["primary_inference_gw_qlike"]["z_stat"]
                ),
                ha="center", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(labs, fontsize=7.5)
    ax.set_ylabel("out-of-sample QLIKE (lower = better)")
    ax.set_title(vb["figure_3_title"])
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "fig3_oos_qlike.png", dpi=130)
    plt.close(fig)

    # Fig 4 — threshold sensitivity heatmap (unconditional GW/DM z)
    sw = [c for c in res["all_cells"] if c["family"] == "threshold"]
    if sw:
        df = pd.DataFrame(
            [
                {
                    "asset": c["asset"], "horizon": c["horizon"],
                    "threshold": c["threshold"],
                    "gw_z": c["primary_inference_gw_qlike"]["z_stat"],
                }
                for c in sw
            ]
        )
        piv = df.pivot_table(index=["asset", "horizon"], columns="threshold", values="gw_z")
        fig, ax = plt.subplots(figsize=(7.5, 3.6))
        im = ax.imshow(piv.to_numpy(), cmap="RdBu_r", vmin=-3.5, vmax=3.5, aspect="auto")
        ax.set_xticks(range(len(piv.columns)))
        ax.set_xticklabels([f"|z|≥{c}" for c in piv.columns])
        ax.set_yticks(range(len(piv.index)))
        ax.set_yticklabels([f"{a} h={h}" for a, h in piv.index])
        for i in range(piv.shape[0]):
            for j in range(piv.shape[1]):
                ax.text(j, i, f"{piv.to_numpy()[i, j]:.2f}",
                        ha="center", va="center", fontsize=9)
        ax.set_title(vb["figure_4_title"])
        fig.colorbar(im, label=vb["figure_4_colorbar_label"])
        fig.tight_layout()
        fig.savefig(OUT / "fig4_threshold_sensitivity.png", dpi=130)
        plt.close(fig)

    # Fig 5 — SIMULATED POWER (replaces v1's single-path "MDE" curve)
    pw = res.get("power_simulation")
    if pw:
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), sharey=True)
        for ax, a in zip(axes, ("BTC", "ETH")):
            cur = pd.DataFrame(pw[a]["curve"])
            x = cur["rv_uplift_per_1sd_shock_pct"]
            y = cur["power_gw_one_sided_5pct"]
            se = cur["power_gw_se"].fillna(0)
            ax.plot(
                x,
                y,
                marker="o",
                ms=4.5,
                color="#2a9d8f",
                label=vb["figure_5_power_label"],
            )
            ax.fill_between(x, y - 1.96 * se, y + 1.96 * se, color="#2a9d8f", alpha=.18)
            ax.axhline(
                0.80,
                color="#e76f51",
                ls="--",
                lw=1.0,
                label=vb["figure_5_80_line_label"],
            )
            ax.axhline(0.05, color="grey", ls=":", lw=1.0,
                       label=vb["figure_5_nominal_line_label"])
            fp = pw[a]["false_positive_rate_at_beta_0"]
            # The 80%-power effect is BRACKETED by the grid, never solved. Draw the
            # interval, not a line: a vline here would redraw the exact "coarse
            # curve, precise number" claim the write-up withdraws.
            br = pw[a]["power_80pct_bracket"]
            if br["reached_on_grid"] and br["lower_rv_uplift_pct"] is not None:
                ax.axvspan(
                    br["lower_rv_uplift_pct"], br["upper_rv_uplift_pct"],
                    color="#264653", alpha=.12,
                    label=vb["figure_5_bracket_label"].format(
                        lower=br["lower_rv_uplift_pct"],
                        upper=br["upper_rv_uplift_pct"],
                    ),
                )
            ax.set_title(
                vb["figure_5_panel_title"].format(
                    asset=a, false_positive=f"{fp:.1%}"
                )
            )
            ax.set_xlabel(vb["figure_5_x_label"])
            ax.set_ylim(0, 1.02)
            ax.legend(fontsize=7.5, loc="lower right")
        axes[0].set_ylabel(vb["figure_5_y_label"])
        fig.suptitle(vb["figure_5_suptitle"], fontsize=9.5)
        fig.tight_layout()
        fig.savefig(OUT / "fig5_simulated_power.png", dpi=130)
        plt.close(fig)


if __name__ == "__main__":
    if "--relabel" in sys.argv:
        relabel_frozen_results()
    elif "--render-frozen-figures" in sys.argv:
        with open(OUT / "k1709_results.json") as fh:
            make_frozen_result_plots(json.load(fh))
    else:
        main()
