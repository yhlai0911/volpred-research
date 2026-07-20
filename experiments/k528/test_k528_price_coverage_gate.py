"""Adversarial regression test for the k528 price-data coverage gates.

WHY THIS FILE EXISTS
--------------------
Codex review round 5 returned FAIL with, among others:

    K528-R5-B3 -- 價格資料尾端截短也不 fail closed
    `yf.download` 後沒有 SPY/^VIX 覆蓋範圍或 freshness gate。若 SPY 尾端少一個月，
    後續 NFP 會被歸為 `outside_price_sample` 並繼續產生結論；若 VIX 尾端短缺，
    `ffill()` 可沿用陳舊 VIX。

The calendar had four layers of completeness checking; the price series that the
calendar is joined against had none. A SPY download that stops a month early does
not raise and does not produce NaNs -- the releases past the end are quietly
reclassified as "outside the price sample", counted, and skipped.

Both failure modes are silent in the same specific way: the run still prints a
sample size, and the sample size it prints is internally consistent with the
shortened data. That is the same shape as the calendar defect this experiment
exists to document, one layer down.

NO NETWORK, NO RERUN
--------------------
``k528_nfp_event_study.py`` is a flat top-level script with no ``__main__``
guard, so the two guards are lifted out with ``ast`` and exercised against
synthetic frames. Same technique, and same reason, as
``test_k528_completeness_gate.py``.
"""

from __future__ import annotations

import ast

import numpy as np
import pandas as pd
import pytest

from pathlib import Path

HERE = Path(__file__).parent
SCRIPT = HERE / "k528_nfp_event_study.py"

WANTED = (
    "check_price_coverage",
    "check_vix_forward_fill_age",
    "MAX_PRICE_COVERAGE_SHORTFALL_DAYS",
    "MAX_VIX_FFILL_TRADING_DAYS",
)

SAMPLE_START = "2005-01-01"
SAMPLE_END = "2026-03-27"


def _load():
    src = SCRIPT.read_text()
    tree = ast.parse(src, filename=str(SCRIPT))
    found, chunks = set(), []
    for node in tree.body:
        name = None
        if isinstance(node, ast.FunctionDef):
            name = node.name
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        if name in WANTED:
            found.add(name)
            chunks.append(ast.get_source_segment(src, node))
    missing = set(WANTED) - found
    assert not missing, (
        f"could not lift {sorted(missing)} out of {SCRIPT.name}. The guards were renamed or "
        "inlined; this test is no longer testing what it claims to test."
    )
    ns: dict = {"pd": pd, "np": np}
    exec(compile("\n\n".join(chunks), f"<{SCRIPT.name}>", "exec"), ns)
    return ns


def _sessions(start="2005-01-03", end="2026-03-26"):
    """A stand-in trading calendar: weekdays only, which is close enough."""
    return pd.bdate_range(start=start, end=end)


def _frame(start="2005-01-03", end="2026-03-26"):
    idx = _sessions(start, end)
    return pd.DataFrame({"Close": np.linspace(100.0, 500.0, len(idx))}, index=idx)


# --------------------------------------------------------------------------
# Control. A gate that raises on everything proves nothing.
# --------------------------------------------------------------------------
def test_full_coverage_is_accepted():
    ns = _load()
    out = ns["check_price_coverage"](_frame(), "SPY", SAMPLE_START, SAMPLE_END)
    assert out["head_shortfall_days"] <= ns["MAX_PRICE_COVERAGE_SHORTFALL_DAYS"]
    assert out["tail_shortfall_days"] <= ns["MAX_PRICE_COVERAGE_SHORTFALL_DAYS"]


# --------------------------------------------------------------------------
# The B3 attack: a month missing from an end of the price series.
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kwargs,end",
    [
        ({"end": "2026-02-26"}, "tail"),
        ({"start": "2005-02-03"}, "head"),
    ],
    ids=["tail_month_missing", "head_month_missing"],
)
def test_truncated_price_series_is_rejected(kwargs, end):
    ns = _load()
    with pytest.raises(RuntimeError, match="does not cover the requested window"):
        ns["check_price_coverage"](_frame(**kwargs), "SPY", SAMPLE_START, SAMPLE_END)


def test_empty_download_is_rejected():
    ns = _load()
    with pytest.raises(RuntimeError, match="no rows"):
        ns["check_price_coverage"](pd.DataFrame({"Close": []}), "SPY", SAMPLE_START, SAMPLE_END)


def test_a_short_holiday_gap_is_still_accepted():
    """Anti-over-fitting: the tolerance must not be so tight that a real calendar trips it.

    2005-01-01 is a Saturday and yfinance's `end` is exclusive, so a few days of
    slack at each edge is structural, not sloppiness.
    """
    ns = _load()
    out = ns["check_price_coverage"](_frame("2005-01-05", "2026-03-24"), "SPY", SAMPLE_START, SAMPLE_END)
    assert out["n_rows"] > 0


# --------------------------------------------------------------------------
# The other half of B3: a stale VIX carried by ffill.
# --------------------------------------------------------------------------
def test_vix_with_no_gaps_is_accepted():
    ns = _load()
    idx = _sessions("2020-01-01", "2020-06-30")
    s = pd.Series(np.linspace(15.0, 30.0, len(idx)), index=idx)
    filled, audit = ns["check_vix_forward_fill_age"](s)
    assert audit["max_consecutive_ffill_trading_days"] == 0
    assert filled.equals(s)


def test_short_vix_gap_is_forward_filled():
    """A one-session hole is what ffill is for. It must not raise."""
    ns = _load()
    idx = _sessions("2020-01-01", "2020-06-30")
    s = pd.Series(np.linspace(15.0, 30.0, len(idx)), index=idx)
    s.iloc[10] = np.nan
    filled, audit = ns["check_vix_forward_fill_age"](s)
    assert audit["max_consecutive_ffill_trading_days"] == 1
    assert filled.iloc[10] == s.iloc[9]


def test_truncated_vix_tail_is_rejected_instead_of_carried():
    """The B3 failure mode, exactly.

    A ^VIX series that stops a month early leaves the last real quote stamped on
    every session after it. Without this gate the regime split and the
    correlation run on a constant, and nothing in the output says so.
    """
    ns = _load()
    idx = _sessions("2020-01-01", "2020-06-30")
    s = pd.Series(np.linspace(15.0, 30.0, len(idx)), index=idx)
    s.iloc[-22:] = np.nan  # roughly one month of sessions
    with pytest.raises(RuntimeError, match="consecutive SPY sessions"):
        ns["check_vix_forward_fill_age"](s)


def test_vix_missing_at_the_start_is_rejected():
    """ffill cannot repair a leading gap -- it would leave NaN, or worse, be back-filled."""
    ns = _load()
    idx = _sessions("2020-01-01", "2020-06-30")
    s = pd.Series(np.linspace(15.0, 30.0, len(idx)), index=idx)
    s.iloc[:2] = np.nan
    with pytest.raises(RuntimeError, match="still have no VIX after forward fill"):
        ns["check_vix_forward_fill_age"](s)


def test_the_gate_is_what_rejects_the_truncation_not_the_ffill_itself():
    """Anti-vacuity.

    Neutralise the age limit and the truncated tail sails through as filled data:
    no NaN, no error, a constant VIX for the last month. This is the pre-fix
    behaviour, and without it the test above could not distinguish "the gate
    works" from "pandas would have complained anyway".
    """
    ns = _load()
    idx = _sessions("2020-01-01", "2020-06-30")
    s = pd.Series(np.linspace(15.0, 30.0, len(idx)), index=idx)
    s.iloc[-22:] = np.nan
    last_real = s.iloc[-23]
    filled = s.ffill()
    assert not filled.isna().any(), "ffill silently produces a complete-looking series"
    assert (filled.iloc[-22:] == last_real).all(), "every one of them is the same stale quote"
