#!/usr/bin/env python3
"""NFP 2026-08-07 T-2 evidence: does the ramp live in the final two sessions?

The sibling study ``experiments/nfp_20260807_t7`` tested the whole pre-event
week (T-7 close -> T-1 close, six returns) and failed to detect an effect.  A
six-return average can, in principle, dilute a move that only happens in the
last 48 hours, and that shorter window is exactly the one still actionable at
the T-2 publishing slot.  This experiment therefore tests the final two
sessions on their own (T-3 close -> T-1 close, two returns) with the same
overlap-aware control construction and Newey-West HAC inference, then
decomposes the week into its early and late halves so the two studies can be
read against each other.

Vintage discipline follows the sibling: pinned inputs are immutable, so a newer
as-of date requires a new experiment identity rather than an in-place refresh.
Normal execution is network-free; ``--bootstrap-snapshots`` is the explicit
one-time acquisition path.

Publishing-slot label vs information set: ``event_series_slot=T-2`` is a
calendar-stage label.  The conditioning variable here is the last close that
exists when the slot is written, 2026-08-04, which is the third trading day
before the release (T-3).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

EXPERIMENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXPERIMENT_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from plot_style import apply_cjk_style

from volpred.research.reproduce_spec import finalize_experiment
from volpred.stats.inference import holm_step_down

EXPERIMENT_ID = "nfp_20260807_t2"
START = "2010-01-01"
SOURCE_END_EXCLUSIVE = "2026-08-05"
VIX_SNAPSHOT_THROUGH = "2026-08-04"
TARGET_RELEASE = "2026-08-07"
# The T-2 publishing slot is written from the 2026-08-04 close, which is the
# third trading day before the 2026-08-07 release.
TARGET_AS_OF = "2026-08-04"

PRE_LAG = 3          # conditioning close: T-3
HORIZON = PRE_LAG - 1  # two returns: T-3 close -> T-1 close
WEEK_LAG = 7         # sibling window, used only for the decomposition
PRIMARY_HAC_LAG = 22
HAC_SENSITIVITY_LAGS = (6, 22, 60)
REGIME_BINS = [0.0, 15.0, 20.0, 25.0, 200.0]
REGIME_LABELS = ["<15", "15-20", "20-25", ">=25"]

DATA_DIR = EXPERIMENT_DIR / "data"
VIX_SNAPSHOT = DATA_DIR / f"vix_close_{START}_{VIX_SNAPSHOT_THROUGH}.csv"
RELEASE_SNAPSHOT = DATA_DIR / f"nfp_release_dates_{START}_{SOURCE_END_EXCLUSIVE}.json"
EVENTS_OUTPUT = EXPERIMENT_DIR / f"{EXPERIMENT_ID}_events.csv"
CONTROLS_OUTPUT = EXPERIMENT_DIR / f"{EXPERIMENT_ID}_controls.csv"
FIGURE_OUTPUT = EXPERIMENT_DIR / f"{EXPERIMENT_ID}_window.png"
CANONICAL_RESULT = f"{EXPERIMENT_ID}_results.json"


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def bootstrap_snapshots() -> None:
    """Acquire both inputs once and atomically install a new snapshot directory."""
    if DATA_DIR.exists():
        raise FileExistsError(
            f"pinned snapshot directory already exists: {DATA_DIR}; "
            "create a new experiment/vintage identity instead of overwriting it"
        )

    from volpred.data.event_dates import nfp_release_dates
    from volpred.data.manager import DataManager

    raw = DataManager().get_price_data("^VIX", START, SOURCE_END_EXCLUSIVE)
    raw.index = pd.to_datetime(raw.index).tz_localize(None).normalize()
    close = raw["close"].astype(float).sort_index().loc[START:VIX_SNAPSHOT_THROUGH]
    if close.empty or close.index[-1] != pd.Timestamp(VIX_SNAPSHOT_THROUGH):
        raise RuntimeError(
            f"VIX snapshot must end at {VIX_SNAPSHOT_THROUGH}; got "
            f"{None if close.empty else close.index[-1].date()}"
        )
    if close.index.has_duplicates or not close.index.is_monotonic_increasing:
        raise RuntimeError("VIX snapshot dates must be unique and increasing")
    invalid = ~np.isfinite(close) | (close <= 0)
    dropped_vix_rows = [d.date().isoformat() for d in close.index[invalid]]
    close = close.loc[~invalid]
    if close.empty or close.index[-1] != pd.Timestamp(VIX_SNAPSHOT_THROUGH):
        raise RuntimeError("dropping invalid VIX rows removed the required as-of close")

    releases = nfp_release_dates(START, SOURCE_END_EXCLUSIVE)
    release_payload = json.dumps(
        {
            "source": "FRED/ALFRED release dates API, release id 50 (Employment Situation)",
            "source_query_start": START,
            "source_query_end": SOURCE_END_EXCLUSIVE,
            "selected_rule": "earliest release-id-50 entry in each calendar month",
            "acquired_at": _iso_now(),
            "vix_invalid_rows_dropped": dropped_vix_rows,
            "dates": [d.date().isoformat() for d in releases],
        },
        indent=2,
        ensure_ascii=False,
    ) + "\n"

    staged = Path(tempfile.mkdtemp(prefix=".nfp-t2-snapshot-", dir=EXPERIMENT_DIR))
    try:
        pd.DataFrame(
            {"date": close.index.strftime("%Y-%m-%d"), "close": close.values}
        ).to_csv(staged / VIX_SNAPSHOT.name, index=False)
        (staged / RELEASE_SNAPSHOT.name).write_text(release_payload, encoding="utf-8")
        staged.rename(DATA_DIR)
    except Exception:
        shutil.rmtree(staged, ignore_errors=True)
        raise


def load_snapshots() -> tuple[pd.Series, pd.DatetimeIndex, dict[str, Any]]:
    """Load pinned inputs and fail closed on timing or identity-shape drift."""
    missing = [p for p in (VIX_SNAPSHOT, RELEASE_SNAPSHOT) if not p.is_file()]
    if missing:
        names = ", ".join(str(p.relative_to(REPO_ROOT)) for p in missing)
        raise RuntimeError(
            f"pinned inputs missing: {names}; run --bootstrap-snapshots once, "
            "then commit the snapshots before normal reproduction"
        )

    frame = pd.read_csv(VIX_SNAPSHOT)
    if list(frame.columns) != ["date", "close"]:
        raise RuntimeError("VIX snapshot schema must be exactly [date, close]")
    dates = pd.DatetimeIndex(pd.to_datetime(frame["date"], errors="raise"))
    close = pd.Series(pd.to_numeric(frame["close"], errors="raise").to_numpy(), index=dates)
    if close.index.has_duplicates or not close.index.is_monotonic_increasing:
        raise RuntimeError("VIX snapshot dates must be unique and increasing")
    if close.index[-1] != pd.Timestamp(VIX_SNAPSHOT_THROUGH):
        raise RuntimeError(
            f"VIX snapshot as-of drift: {close.index[-1]} != {VIX_SNAPSHOT_THROUGH}"
        )
    if not np.isfinite(close).all() or not (close > 0).all():
        raise RuntimeError("VIX snapshot contains non-finite/non-positive closes")
    if pd.Timestamp(TARGET_AS_OF) not in close.index:
        raise RuntimeError(f"target conditioning close missing from snapshot: {TARGET_AS_OF}")

    release_meta = json.loads(RELEASE_SNAPSHOT.read_text(encoding="utf-8"))
    releases = pd.DatetimeIndex(pd.to_datetime(release_meta.get("dates", [])))
    if releases.empty or releases.has_duplicates or not releases.is_monotonic_increasing:
        raise RuntimeError("release snapshot must be non-empty, unique and increasing")
    gaps = pd.Series(releases).diff().dropna().dt.days
    if ((gaps < 13) | (gaps > 110)).any():
        raise RuntimeError("release snapshot failed the canonical 13-110 day cadence gate")
    if releases[-1] > pd.Timestamp(SOURCE_END_EXCLUSIVE):
        raise RuntimeError("release snapshot contains a date after its declared query end")
    if pd.Timestamp(TARGET_RELEASE) <= pd.Timestamp(TARGET_AS_OF):
        raise RuntimeError("target release must be strictly after the conditioning cutoff")
    return close, releases, release_meta


def _overlapping_control_starts(release_position: int) -> range:
    """Control starts whose return intervals overlap T-3-close -> T-1-close.

    Event returns occupy index intervals ``i-HORIZON .. i-1``.  A control
    starting at ``k`` occupies ``k+1 .. k+HORIZON``.  The intersection is
    non-empty iff ``i-2*HORIZON <= k <= i-2``.
    """
    return range(release_position - 2 * HORIZON, release_position - 1)


def build_panels(
    close: pd.Series, releases: pd.DatetimeIndex
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    idx = close.index
    release_positions = set()
    event_rows: list[dict[str, Any]] = []
    event_starts: set[pd.Timestamp] = set()
    excluded_controls: set[pd.Timestamp] = set()

    for release in releases:
        i = int(idx.searchsorted(release))
        if i >= len(idx) or idx[i] != release:
            continue
        release_positions.add(i)
        if i - WEEK_LAG < 0:
            continue
        start = idx[i - PRE_LAG]
        event_starts.add(start)
        row = {
            "start_date": start.date().isoformat(),
            "release": release.date().isoformat(),
            "vix_t7": float(close.iloc[i - WEEK_LAG]),
            "vix_t3": float(close.iloc[i - PRE_LAG]),
            "vix_tm1": float(close.iloc[i - 1]),
            "vix_t0": float(close.iloc[i]),
            # final two sessions, the window still actionable at the T-2 slot
            "final2_chg_pct": float(close.iloc[i - 1] / close.iloc[i - PRE_LAG] - 1.0) * 100.0,
            # early half of the sibling week: T-7 close -> T-3 close (four returns)
            "early4_chg_pct": float(close.iloc[i - PRE_LAG] / close.iloc[i - WEEK_LAG] - 1.0) * 100.0,
            "week_chg_pct": float(close.iloc[i - 1] / close.iloc[i - WEEK_LAG] - 1.0) * 100.0,
            "event_day_chg_pct": float(close.iloc[i] / close.iloc[i - 1] - 1.0) * 100.0,
        }
        row["next_day_chg_pct"] = (
            float(close.iloc[i + 1] / close.iloc[i] - 1.0) * 100.0
            if i + 1 < len(idx)
            else float("nan")
        )
        event_rows.append(row)
        for k in _overlapping_control_starts(i):
            if 0 <= k < len(idx):
                excluded_controls.add(idx[k])

    events = pd.DataFrame(event_rows)
    if events.empty:
        raise RuntimeError("no official NFP releases matched the pinned trading calendar")

    forward = (close.shift(-HORIZON) / close - 1.0) * 100.0
    control_mask = (
        forward.notna()
        & ~idx.isin(excluded_controls)
        & ~idx.isin(event_starts)
    )
    # A control window starting at k spans the returns dated idx[k+1] .. idx[k+HORIZON];
    # flag the ones that swallow an actual release-day return.
    positions = np.arange(len(idx))
    contains_release = np.array(
        [
            any((p + step) in release_positions for step in range(1, HORIZON + 1))
            for p in positions
        ]
    )
    controls = pd.DataFrame(
        {
            "start_date": idx[control_mask],
            "start_vix": close.loc[control_mask].to_numpy(),
            "chg_pct": forward.loc[control_mask].to_numpy(),
            "contains_release_return": contains_release[control_mask.to_numpy()],
        }
    )

    event_panel = pd.DataFrame(
        {
            "start_date": pd.to_datetime(events["start_date"]),
            "start_vix": events["vix_t3"].to_numpy(),
            "chg_pct": events["final2_chg_pct"].to_numpy(),
            "event": 1,
        }
    )
    control_panel = controls[["start_date", "start_vix", "chg_pct"]].assign(event=0)
    panel = pd.concat([event_panel, control_panel], ignore_index=True).sort_values("start_date")
    return events, controls, panel


def weekday_controlled_effect(
    daily: pd.DataFrame, indicator: str, drop_flag: str, lag: int
) -> dict[str, Any]:
    """Test one daily-return indicator with weekday fixed effects.

    NFP releases land almost entirely on Fridays, so an unconditional
    release-day mean is confounded with whatever VIX does on Fridays.  The
    weekday dummies absorb that composition; ``drop_flag`` removes the other
    event-adjacent rows so the baseline is ordinary trading days.
    """
    sample = daily.loc[~daily[drop_flag]].copy()
    dummies = pd.get_dummies(sample["weekday"], prefix="wd", drop_first=True).astype(float)
    design = sm.add_constant(
        pd.concat([sample[indicator].astype(float), dummies], axis=1)
    )
    fit = sm.OLS(sample["ret_pct"].astype(float), design).fit(
        cov_type="HAC", cov_kwds={"maxlags": lag, "use_correction": True}
    )
    ci = fit.conf_int().loc[indicator]
    flagged = sample.loc[sample[indicator]]
    return {
        "n": int(len(sample)),
        "n_flagged": int(len(flagged)),
        "weekday_mix_of_flagged": {
            str(k): int(v) for k, v in flagged["weekday"].value_counts().sort_index().items()
        },
        "raw_flagged_mean_pct": float(flagged["ret_pct"].mean()),
        "raw_baseline_mean_pct": float(sample.loc[~sample[indicator], "ret_pct"].mean()),
        "lag": int(lag),
        "effect_pct_points": float(fit.params[indicator]),
        "hac_se": float(fit.bse[indicator]),
        "hac_t": float(fit.tvalues[indicator]),
        "p_two_sided": float(fit.pvalues[indicator]),
        "ci95_low": float(ci.iloc[0]),
        "ci95_high": float(ci.iloc[1]),
    }


def build_daily_frame(close: pd.Series, releases: pd.DatetimeIndex) -> pd.DataFrame:
    idx = close.index
    positions = {int(idx.searchsorted(r)) for r in releases if int(idx.searchsorted(r)) < len(idx)}
    positions = {p for p in positions if idx[p] in set(releases)}
    daily = pd.DataFrame(
        {
            "ret_pct": (close / close.shift(1) - 1.0) * 100.0,
            "weekday": idx.dayofweek,
        }
    ).iloc[1:]
    pos_of = {d: i for i, d in enumerate(idx)}
    daily["is_release"] = [pos_of[d] in positions for d in daily.index]
    daily["is_day_after"] = [(pos_of[d] - 1) in positions for d in daily.index]
    return daily


def hac_effect(panel: pd.DataFrame, lag: int) -> dict[str, float | int]:
    if panel["event"].nunique() != 2:
        raise RuntimeError("HAC panel needs both event and control observations")
    design = sm.add_constant(panel["event"].astype(float))
    fit = sm.OLS(panel["chg_pct"].astype(float), design).fit(
        cov_type="HAC",
        cov_kwds={"maxlags": lag, "use_correction": True},
    )
    ci = fit.conf_int().loc["event"]
    return {
        "n": len(panel),
        "n_event": int(panel["event"].sum()),
        "n_control": int((panel["event"] == 0).sum()),
        "lag": int(lag),
        "effect_pct_points": float(fit.params["event"]),
        "hac_se": float(fit.bse["event"]),
        "hac_t": float(fit.tvalues["event"]),
        "p_two_sided": float(fit.pvalues["event"]),
        "ci95_low": float(ci.iloc[0]),
        "ci95_high": float(ci.iloc[1]),
    }


def _summary(values: pd.Series) -> dict[str, float | int]:
    values = values.astype(float).dropna()
    return {
        "n": int(values.count()),
        "mean_pct": float(values.mean()),
        "median_pct": float(values.median()),
        "sd_pct": float(values.std()),
        "share_up_pct": float((values > 0).mean() * 100.0),
        "mean_abs_pct": float(values.abs().mean()),
    }


def analyze(
    close: pd.Series,
    releases: pd.DatetimeIndex,
    release_meta: dict[str, Any],
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    events, controls, panel = build_panels(close, releases)
    daily = build_daily_frame(close, releases)
    event_values = events["final2_chg_pct"].astype(float)
    control_values = controls["chg_pct"].astype(float)

    naive_welch = stats.ttest_ind(event_values, control_values, equal_var=False)
    naive_mw = stats.mannwhitneyu(event_values, control_values, alternative="two-sided")
    sensitivity = {str(lag): hac_effect(panel, lag) for lag in HAC_SENSITIVITY_LAGS}

    # Sensitivity: controls that never swallow a release-day return.
    clean = controls.loc[~controls["contains_release_return"]]
    clean_panel = pd.concat(
        [
            panel.loc[panel["event"] == 1],
            clean[["start_date", "start_vix", "chg_pct"]].assign(event=0),
        ],
        ignore_index=True,
    ).sort_values("start_date")
    release_clean = hac_effect(clean_panel, PRIMARY_HAC_LAG)

    events["regime"] = pd.cut(events["vix_t3"], REGIME_BINS, labels=REGIME_LABELS, right=False)
    controls["regime"] = pd.cut(controls["start_vix"], REGIME_BINS, labels=REGIME_LABELS, right=False)

    regime_rows: list[dict[str, Any]] = []
    raw_pvalues: dict[str, float] = {}
    for label in REGIME_LABELS:
        ev = events.loc[events["regime"] == label, ["start_date", "final2_chg_pct"]].rename(
            columns={"final2_chg_pct": "chg_pct"}
        )
        ev["start_date"] = pd.to_datetime(ev["start_date"])
        ev["event"] = 1
        base = controls.loc[controls["regime"] == label, ["start_date", "chg_pct"]].copy()
        base["event"] = 0
        regime_panel = pd.concat([ev, base], ignore_index=True).sort_values("start_date")
        inference = hac_effect(regime_panel, PRIMARY_HAC_LAG)
        raw_pvalues[label] = float(inference["p_two_sided"])
        subset = events.loc[events["regime"] == label]
        regime_rows.append(
            {
                "regime": label,
                "n_event": int(len(subset)),
                "event_final2_mean_pct": float(subset["final2_chg_pct"].mean()),
                "control_final2_mean_pct": float(
                    controls.loc[controls["regime"] == label, "chg_pct"].mean()
                ),
                "event_day_mean_pct": float(subset["event_day_chg_pct"].mean()),
                "event_day_mean_abs_pct": float(subset["event_day_chg_pct"].abs().mean()),
                "next_day_mean_pct": float(subset["next_day_chg_pct"].mean()),
                **{f"hac_{k}": v for k, v in inference.items()},
            }
        )
    # Holm step-down comes from the canonical implementation, not a local copy.
    # A hand-written one lived here and was numerically identical, which is
    # precisely why it was a liability: a private copy of a shared statistical
    # definition drifts silently, and the divergence only shows up when two
    # experiments disagree about a number that should have exactly one meaning.
    # holm_step_down also validates its inputs (finite, in [0,1]) where the copy
    # did not, so a malformed p-value now raises instead of being adjusted.
    holm_names = list(raw_pvalues)
    holm_result = holm_step_down([raw_pvalues[name] for name in holm_names])
    holm = dict(zip(holm_names, holm_result.adjusted_p_values))
    for row in regime_rows:
        row["hac_p_holm"] = float(holm[row["regime"]])

    target_vix = float(close.loc[pd.Timestamp(TARGET_AS_OF)])
    target_regime = str(pd.cut([target_vix], REGIME_BINS, labels=REGIME_LABELS, right=False)[0])
    target_row = next(r for r in regime_rows if r["regime"] == target_regime)

    primary = sensitivity[str(PRIMARY_HAC_LAG)]
    verdict = (
        "EFFECT_DETECTED"
        if primary["p_two_sided"] < 0.05
        else "NULL_FAILURE_TO_DETECT"
    )

    results: dict[str, Any] = {
        "experiment_id": EXPERIMENT_ID,
        "generated_for": f"NFP_US_2026_08_07 / {'T-2'}",
        "question": (
            "Does the pre-NFP VIX ramp live in the final two sessions (T-3 close -> "
            "T-1 close), i.e. in the part of the week a T-2 reader can still act on?"
        ),
        "analysis_class": "descriptive_event_study_with_HAC_inference",
        "verdict": verdict,
        "sibling_study": {
            "experiment_id": "nfp_20260807_t7",
            "window": "T-7 close -> T-1 close (six returns)",
            "verdict": "NULL_FAILURE_TO_DETECT",
            "relation": (
                "this study shortens the window to the final two sessions to test the "
                "dilution explanation for the sibling's null"
            ),
        },
        "data": {
            "vix_source": "Yahoo Finance ^VIX daily close, pinned local snapshot",
            "vix_requested_start": START,
            "vix_as_of": VIX_SNAPSHOT_THROUGH,
            "vix_observations": int(len(close)),
            "vix_invalid_rows_dropped": release_meta.get("vix_invalid_rows_dropped", []),
            "release_source": release_meta.get("source"),
            "release_selected_rule": release_meta.get("selected_rule"),
            "release_snapshot_acquired_at": release_meta.get("acquired_at"),
        },
        "sample": {
            "n_releases_matched": int(len(events)),
            "first_release": events["release"].iloc[0],
            "last_release": events["release"].iloc[-1],
        },
        "event_window": {
            "definition": "VIX close at T-3 trading days -> VIX close at T-1 (two returns)",
            **_summary(events["final2_chg_pct"]),
        },
        "control_window": {
            "definition": (
                "all two-return VIX windows whose return intervals do not overlap an "
                "NFP T-3->T-1 interval"
            ),
            "exclusion_math": (
                "event intervals i-2..i-1; control intervals k+1..k+2; exclude i-4 <= k <= i-2"
            ),
            **_summary(controls["chg_pct"]),
        },
        "primary_inference": {
            "method": "OLS event indicator with Newey-West HAC covariance",
            "reason": "rolling two-return control outcomes overlap and are not iid",
            **primary,
        },
        "hac_lag_sensitivity": sensitivity,
        "release_clean_control_sensitivity": {
            "definition": (
                "controls additionally dropped when either of their two returns is a "
                "release-day return"
            ),
            "n_control_dropped": int(controls["contains_release_return"].sum()),
            **release_clean,
        },
        "naive_iid_reference": {
            "note": "reported only to show what an unadjusted test would have claimed",
            "welch_t": float(naive_welch.statistic),
            "welch_p": float(naive_welch.pvalue),
            "mannwhitney_p": float(naive_mw.pvalue),
        },
        "week_decomposition": {
            "note": (
                "same 191-ish releases, week split into its early four returns and its "
                "final two returns; per-return means make the halves comparable"
            ),
            "early_T7_to_T3": {
                **_summary(events["early4_chg_pct"]),
                "n_returns": WEEK_LAG - PRE_LAG,
                "mean_per_return_pct": float(events["early4_chg_pct"].mean() / (WEEK_LAG - PRE_LAG)),
            },
            "final_T3_to_T1": {
                **_summary(events["final2_chg_pct"]),
                "n_returns": HORIZON,
                "mean_per_return_pct": float(events["final2_chg_pct"].mean() / HORIZON),
            },
            "full_T7_to_T1": {
                **_summary(events["week_chg_pct"]),
                "n_returns": WEEK_LAG - 1,
                "mean_per_return_pct": float(events["week_chg_pct"].mean() / (WEEK_LAG - 1)),
            },
        },
        "event_day_and_decay": {
            "definition": (
                "event_day = VIX close T-1 -> T-0; next_day = VIX close T-0 -> T+1"
            ),
            "event_day": _summary(events["event_day_chg_pct"]),
            "next_day": _summary(events["next_day_chg_pct"]),
            "weekday_controlled": {
                "note": (
                    "NFP releases are almost all Fridays, so the unconditional means above "
                    "are confounded with weekday seasonality; these regressions add weekday "
                    "fixed effects and HAC standard errors"
                ),
                "event_day_vs_ordinary_days": weekday_controlled_effect(
                    daily, "is_release", "is_day_after", PRIMARY_HAC_LAG
                ),
                "day_after_vs_ordinary_days": weekday_controlled_effect(
                    daily, "is_day_after", "is_release", PRIMARY_HAC_LAG
                ),
            },
        },
        "regime_conditional": regime_rows,
        "target": {
            "release": TARGET_RELEASE,
            "publishing_slot": "T-2",
            "conditioning_close": TARGET_AS_OF,
            "conditioning_trading_day_label": "T-3",
            "vix": target_vix,
            "regime": target_regime,
            "matched_regime_stats": target_row,
        },
        "limitations": [
            "Failure to reject is not evidence that the event effect is exactly zero.",
            "Daily closes do not identify intraday announcement reactions; a ramp that "
            "starts and ends inside the T-1 session is invisible here.",
            "VIX only: nothing here establishes effects for rates, FX, single stocks or "
            "the options term structure.",
            "Regime cells are conditioned on a realised VIX level, so they are "
            "descriptive comparisons, not a causal decomposition.",
            "HAC lag choice is finite-sample judgment; lags 6, 22 and 60 are reported.",
        ],
    }
    return results, events, controls, panel


def render_figure(events: pd.DataFrame, controls: pd.DataFrame, results: dict[str, Any]) -> None:
    apply_cjk_style()
    final2 = events["final2_chg_pct"].astype(float)
    baseline = controls["chg_pct"].astype(float)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))

    ax = axes[0]
    ax.hist(baseline, bins=50, density=True, alpha=0.45, color="#9aa5b1", label="非事件兩日窗")
    ax.hist(final2, bins=25, density=True, alpha=0.65, color="#d1495b", label="非農前 T-3→T-1")
    ax.axvline(0, color="#333", lw=0.8)
    ax.axvline(final2.mean(), color="#d1495b", ls="--", lw=1.4)
    ax.axvline(baseline.mean(), color="#5a6673", ls="--", lw=1.4)
    ax.set_xlim(-25, 30)
    ax.set_xlabel("VIX 兩個交易日變化 (%)")
    ax.set_ylabel("密度")
    ax.set_title("最後兩個交易日 vs 非重疊對照窗")
    ax.legend(fontsize=8)

    ax = axes[1]
    decomp = results["week_decomposition"]
    labels = ["T-7→T-3\n(前四個交易日)", "T-3→T-1\n(最後兩個交易日)", "T-0 當天"]
    values = [
        decomp["early_T7_to_T3"]["mean_per_return_pct"],
        decomp["final_T3_to_T1"]["mean_per_return_pct"],
        results["event_day_and_decay"]["event_day"]["mean_pct"],
    ]
    colors = ["#9aa5b1", "#d1495b", "#2f4858"]
    bars = ax.bar(np.arange(len(labels)), values, color=colors, width=0.55)
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + (0.04 if value >= 0 else -0.10),
            f"{value:+.2f}%",
            ha="center",
            fontsize=9,
        )
    ax.set_xticks(np.arange(len(labels)))
    ax.set_xticklabels(labels, fontsize=8)
    ax.axhline(0, color="#333", lw=0.8)
    ax.set_ylabel("每個交易日平均 VIX 變化 (%)")
    ax.set_title("把公佈前那一週拆開：位移在哪一段")
    fig.suptitle(
        f"非農公佈前最後兩個交易日的 VIX（{results['sample']['n_releases_matched']} 次官方公佈日）",
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(FIGURE_OUTPUT, dpi=140)
    plt.close(fig)


def run() -> dict[str, Any]:
    started_at = time.time()
    close, releases, release_meta = load_snapshots()
    results, events, controls, _panel = analyze(close, releases, release_meta)
    events.to_csv(EVENTS_OUTPUT, index=False)
    controls.to_csv(CONTROLS_OUTPUT, index=False)
    render_figure(events, controls, results)
    finalize_experiment(
        results=results,
        entrypoint=__file__,
        canonical_result=CANONICAL_RESULT,
        inputs=[VIX_SNAPSHOT, RELEASE_SNAPSHOT],
        outputs=[EVENTS_OUTPUT.name, CONTROLS_OUTPUT.name, FIGURE_OUTPUT.name],
        seeds=[],
        started_at=started_at,
        network="deny",
    )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bootstrap-snapshots",
        action="store_true",
        help="one-time network acquisition of the pinned VIX and release-calendar inputs",
    )
    args = parser.parse_args()
    if args.bootstrap_snapshots:
        bootstrap_snapshots()
        return
    results = run()
    print(json.dumps(results["primary_inference"], indent=2))
    print(json.dumps(results["week_decomposition"], indent=2, ensure_ascii=False))
    print(json.dumps(results["target"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
