#!/usr/bin/env python3
"""NFP 2026-08-07 T-7 evidence, rebuilt from pinned inputs.

The archived producer in ``scripts/gen_nfp_20260807_t7_analysis.py`` left a
complete-looking but non-reproducible package.  This canonical entrypoint keeps
those legacy bytes untouched and fixes two inferential problems:

* control starts are excluded only when their six return intervals overlap the
  event's T-7-close -> T-1-close return intervals; and
* rolling six-day outcomes are serially dependent, so the primary mean-effect
  test is OLS with Newey-West HAC covariance, not an iid two-sample test.

Normal execution is network-free.  ``--bootstrap-snapshots`` is the explicit,
one-time acquisition path used to pin Yahoo Finance VIX closes and the official
ALFRED/FRED release-id-50 calendar before the reproducible run.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
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

EXPERIMENT_ID = "nfp_20260807_t7"
START = "2010-01-01"
SOURCE_END_EXCLUSIVE = "2026-07-31"
AS_OF = "2026-07-30"
TARGET_RELEASE = "2026-08-07"
PRE_LAG = 7
HORIZON = PRE_LAG - 1
PRIMARY_HAC_LAG = 22
HAC_SENSITIVITY_LAGS = (6, 22, 60)

DATA_DIR = EXPERIMENT_DIR / "data"
VIX_SNAPSHOT = DATA_DIR / "vix_close_2010-01-01_2026-07-30.csv"
RELEASE_SNAPSHOT = DATA_DIR / "nfp_release_dates_2010-01-01_2026-07-31.json"
EVENTS_OUTPUT = EXPERIMENT_DIR / f"{EXPERIMENT_ID}_events.csv"
CONTROLS_OUTPUT = EXPERIMENT_DIR / f"{EXPERIMENT_ID}_controls.csv"
FIGURE_OUTPUT = EXPERIMENT_DIR / f"{EXPERIMENT_ID}_regime.png"
CANONICAL_RESULT = f"{EXPERIMENT_ID}_results.json"
LEGACY_RESULT = EXPERIMENT_DIR / "nfp_t7_results.json"

REGIME_BINS = [0.0, 15.0, 20.0, 25.0, 200.0]
REGIME_LABELS = ["<15", "15-20", "20-25", ">=25"]


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def bootstrap_snapshots() -> None:
    """Acquire both inputs once and atomically install a new snapshot directory.

    A pinned input is immutable.  Acquisition therefore refuses even an empty
    pre-existing ``data/`` directory: refreshing a vintage requires a new
    experiment identity, never an in-place overwrite.
    """
    if DATA_DIR.exists():
        raise FileExistsError(
            f"pinned snapshot directory already exists: {DATA_DIR}; "
            "create a new experiment/vintage identity instead of overwriting it"
        )

    from volpred.data.event_dates import nfp_release_dates
    from volpred.data.manager import DataManager

    raw = DataManager().get_price_data("^VIX", START, SOURCE_END_EXCLUSIVE)
    raw.index = pd.to_datetime(raw.index).tz_localize(None).normalize()
    close = raw["close"].astype(float).sort_index().loc[START:AS_OF]
    if close.empty or close.index[-1] != pd.Timestamp(AS_OF):
        raise RuntimeError(
            f"VIX snapshot must end at {AS_OF}; got "
            f"{None if close.empty else close.index[-1].date()}"
        )
    if close.index.has_duplicates or not close.index.is_monotonic_increasing:
        raise RuntimeError("VIX snapshot dates must be unique and increasing")
    invalid = ~np.isfinite(close) | (close <= 0)
    dropped_vix_rows = [d.date().isoformat() for d in close.index[invalid]]
    close = close.loc[~invalid]
    if close.empty or close.index[-1] != pd.Timestamp(AS_OF):
        raise RuntimeError("dropping invalid VIX rows removed the required as-of close")
    releases = nfp_release_dates(START, SOURCE_END_EXCLUSIVE)
    selected = [d.date().isoformat() for d in releases]
    release_payload = json.dumps(
        {
            "source": "FRED/ALFRED release dates API, release id 50 (Employment Situation)",
            "source_query_start": START,
            "source_query_end": SOURCE_END_EXCLUSIVE,
            "selected_rule": "earliest release-id-50 entry in each calendar month",
            "acquired_at": _iso_now(),
            "vix_invalid_rows_dropped": dropped_vix_rows,
            "dates": selected,
        },
        indent=2,
        ensure_ascii=False,
    ) + "\n"

    staged = Path(tempfile.mkdtemp(prefix=".nfp-t7-snapshot-", dir=EXPERIMENT_DIR))
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
    if close.index[-1] != pd.Timestamp(AS_OF):
        raise RuntimeError(f"VIX snapshot as-of drift: {close.index[-1]} != {AS_OF}")
    if not np.isfinite(close).all() or not (close > 0).all():
        raise RuntimeError("VIX snapshot contains non-finite/non-positive closes")

    release_meta = json.loads(RELEASE_SNAPSHOT.read_text(encoding="utf-8"))
    releases = pd.DatetimeIndex(pd.to_datetime(release_meta.get("dates", [])))
    if releases.empty or releases.has_duplicates or not releases.is_monotonic_increasing:
        raise RuntimeError("release snapshot must be non-empty, unique and increasing")
    gaps = pd.Series(releases).diff().dropna().dt.days
    if ((gaps < 13) | (gaps > 110)).any():
        raise RuntimeError("release snapshot failed the canonical 13-110 day cadence gate")
    if releases[-1] > pd.Timestamp(SOURCE_END_EXCLUSIVE):
        raise RuntimeError("release snapshot contains a date after its declared query end")
    if pd.Timestamp(TARGET_RELEASE) <= close.index[-1]:
        raise RuntimeError("target release must be strictly after the T-7 information cutoff")
    return close, releases, release_meta


def _overlapping_control_starts(release_position: int) -> range:
    """Starts whose six return intervals overlap T-7-close -> T-1-close.

    Event returns occupy index intervals ``i-6 .. i-1``.  A control starting
    at ``k`` occupies ``k+1 .. k+6``.  Their intersection is non-empty iff
    ``i-12 <= k <= i-2``.
    """
    return range(release_position - 2 * HORIZON, release_position - 1)


def build_panels(
    close: pd.Series, releases: pd.DatetimeIndex
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    idx = close.index
    event_rows: list[dict[str, Any]] = []
    event_starts: set[pd.Timestamp] = set()
    excluded_controls: set[pd.Timestamp] = set()

    for release in releases:
        i = int(idx.searchsorted(release))
        if i >= len(idx) or idx[i] != release or i - PRE_LAG < 0:
            continue
        start = idx[i - PRE_LAG]
        event_starts.add(start)
        event_rows.append(
            {
                "start_date": start.date().isoformat(),
                "release": release.date().isoformat(),
                "vix_t7": float(close.iloc[i - PRE_LAG]),
                "vix_tm1": float(close.iloc[i - 1]),
                "vix_t0": float(close.iloc[i]),
                "pre_chg_pct": float(close.iloc[i - 1] / close.iloc[i - PRE_LAG] - 1.0) * 100.0,
                "event_day_chg_pct": float(close.iloc[i] / close.iloc[i - 1] - 1.0) * 100.0,
            }
        )
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
    controls = pd.DataFrame(
        {
            "start_date": idx[control_mask],
            "start_vix": close.loc[control_mask].to_numpy(),
            "chg_pct": forward.loc[control_mask].to_numpy(),
        }
    )

    event_panel = pd.DataFrame(
        {
            "start_date": pd.to_datetime(events["start_date"]),
            "start_vix": events["vix_t7"].to_numpy(),
            "chg_pct": events["pre_chg_pct"].to_numpy(),
            "event": 1,
        }
    )
    control_panel = controls.assign(event=0)
    panel = pd.concat([event_panel, control_panel], ignore_index=True).sort_values("start_date")
    return events, controls, panel


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


def holm_adjust(pvalues: dict[str, float]) -> dict[str, float]:
    ordered = sorted(pvalues.items(), key=lambda item: item[1])
    running = 0.0
    adjusted: dict[str, float] = {}
    m = len(ordered)
    for rank, (name, pvalue) in enumerate(ordered):
        running = max(running, min(1.0, (m - rank) * float(pvalue)))
        adjusted[name] = running
    return adjusted


def _summary(values: pd.Series) -> dict[str, float | int]:
    return {
        "n": int(values.count()),
        "mean_pct": float(values.mean()),
        "median_pct": float(values.median()),
        "sd_pct": float(values.std()),
        "share_up_pct": float((values > 0).mean() * 100.0),
    }


def analyze(
    close: pd.Series,
    releases: pd.DatetimeIndex,
    release_meta: dict[str, Any],
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    events, controls, panel = build_panels(close, releases)
    event_values = events["pre_chg_pct"].astype(float)
    control_values = controls["chg_pct"].astype(float)

    naive_welch = stats.ttest_ind(event_values, control_values, equal_var=False)
    naive_mw = stats.mannwhitneyu(event_values, control_values, alternative="two-sided")
    sensitivity = {
        str(lag): hac_effect(panel, lag) for lag in HAC_SENSITIVITY_LAGS
    }

    events["regime"] = pd.cut(
        events["vix_t7"], REGIME_BINS, labels=REGIME_LABELS, right=False
    )
    controls["regime"] = pd.cut(
        controls["start_vix"], REGIME_BINS, labels=REGIME_LABELS, right=False
    )

    regime_rows: list[dict[str, Any]] = []
    raw_pvalues: dict[str, float] = {}
    for label in REGIME_LABELS:
        ev = events.loc[events["regime"] == label, ["start_date", "pre_chg_pct"]].rename(
            columns={"pre_chg_pct": "chg_pct"}
        )
        ev["start_date"] = pd.to_datetime(ev["start_date"])
        ev["event"] = 1
        base = controls.loc[controls["regime"] == label, ["start_date", "chg_pct"]].copy()
        base["event"] = 0
        regime_panel = pd.concat([ev, base], ignore_index=True).sort_values("start_date")
        inference = hac_effect(regime_panel, PRIMARY_HAC_LAG)
        raw_pvalues[label] = float(inference["p_two_sided"])
        regime_rows.append(
            {
                "regime": label,
                "event": _summary(ev["chg_pct"]),
                "control": _summary(base["chg_pct"]),
                "primary_hac": inference,
            }
        )
    adjusted = holm_adjust(raw_pvalues)
    for row in regime_rows:
        row["primary_hac"]["holm_p_four_regimes"] = adjusted[row["regime"]]

    latest_vix = float(close.iloc[-1])
    latest_regime = str(
        pd.cut([latest_vix], REGIME_BINS, labels=REGIME_LABELS, right=False)[0]
    )
    primary = sensitivity[str(PRIMARY_HAC_LAG)]
    legacy = json.loads(LEGACY_RESULT.read_text(encoding="utf-8"))
    results: dict[str, Any] = {
        "experiment_id": EXPERIMENT_ID,
        "generated_for": "NFP_US_2026_08_07 / T-7",
        "analysis_class": "descriptive_event_study_with_HAC_inference",
        "verdict": "NULL_FAILURE_TO_DETECT",
        "data": {
            "vix_source": "Yahoo Finance ^VIX daily close, pinned local snapshot",
            "vix_requested_start": START,
            "vix_as_of": AS_OF,
            "vix_observations": len(close),
            "release_source": release_meta["source"],
            "release_selected_rule": release_meta["selected_rule"],
            "release_snapshot_acquired_at": release_meta["acquired_at"],
            "vix_invalid_rows_dropped": release_meta.get(
                "vix_invalid_rows_dropped", []
            ),
        },
        "sample": {
            "n_releases_matched": len(events),
            "first_release": str(events["release"].iloc[0]),
            "last_release": str(events["release"].iloc[-1]),
        },
        "event_window": {
            "definition": "VIX close at T-7 trading days -> VIX close at T-1",
            **_summary(event_values),
        },
        "control_window": {
            "definition": "all six-return VIX windows whose return intervals do not overlap an NFP T-7->T-1 interval",
            "exclusion_math": "event intervals i-6..i-1; control intervals k+1..k+6; exclude i-12 <= k <= i-2",
            **_summary(control_values),
        },
        "primary_inference": {
            "method": "OLS event indicator with Newey-West HAC covariance",
            "reason": "rolling six-return control outcomes overlap and are not iid",
            **primary,
        },
        "hac_lag_sensitivity": sensitivity,
        "legacy_iid_diagnostics_not_for_inference": {
            "welch_t": {"stat": float(naive_welch.statistic), "p": float(naive_welch.pvalue)},
            "mann_whitney_u": {"stat": float(naive_mw.statistic), "p": float(naive_mw.pvalue)},
            "warning": "Both assume independent observations; retained only to reconcile the archived article calculation.",
        },
        "by_regime": regime_rows,
        "current_state": {
            "as_of": AS_OF,
            "vix_close": latest_vix,
            "regime": latest_regime,
            "next_release": TARGET_RELEASE,
        },
        "event_day_reference": {
            "definition": "VIX close change T-1 -> T+0 (release trading day)",
            **_summary(events["event_day_chg_pct"].astype(float)),
        },
        "legacy_artifacts": {
            "results": "nfp_t7_results.json",
            "events": "nfp_t7_events.csv",
            "figure": "nfp_t7_regime.png",
            "status": "preserved_unmodified; non-reproducible because the raw price snapshot was not archived",
        },
        "published_article_correction": {
            "required": True,
            "article_id": "mile_84e3be0a",
            "reason": (
                "The archived article treated overlapping rolling controls as iid "
                "and its over-broad exclusion rule does not match the stated interval contract."
            ),
            "archived_claims": {
                "control_n": int(legacy["baseline_non_event"]["n"]),
                "control_mean_pct": float(legacy["baseline_non_event"]["mean_pct"]),
                "iid_welch_p": float(legacy["tests"]["welch_t"]["p"]),
            },
            "canonical_claims": {
                "control_n": len(control_values),
                "control_mean_pct": float(control_values.mean()),
                "hac22_p": float(primary["p_two_sided"]),
            },
        },
        "limitations": [
            "Failure to reject is not evidence that the event effect is exactly zero.",
            "Daily closes do not identify intraday announcement reactions.",
            "The study covers VIX only; it does not establish effects for rates, FX, equities or options term structure.",
            "HAC lag choice is finite-sample judgment; lags 6, 22 and 60 are reported.",
        ],
    }
    return results, events, controls, panel


def render_figure(events: pd.DataFrame, controls: pd.DataFrame) -> None:
    apply_cjk_style()
    pre = events["pre_chg_pct"].astype(float)
    baseline = controls["chg_pct"].astype(float)

    event_regime = events.groupby("regime", observed=False)["pre_chg_pct"].mean()
    control_regime = controls.groupby("regime", observed=False)["chg_pct"].mean()

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    ax = axes[0]
    ax.hist(baseline, bins=40, density=True, alpha=0.45, color="#9aa5b1", label="非事件視窗")
    ax.hist(pre, bins=25, density=True, alpha=0.65, color="#d1495b", label="非農前 T-7→T-1")
    ax.axvline(0, color="#333", lw=0.8)
    ax.axvline(pre.mean(), color="#d1495b", ls="--", lw=1.4)
    ax.axvline(baseline.mean(), color="#5a6673", ls="--", lw=1.4)
    ax.set_xlim(-40, 60)
    ax.set_xlabel("VIX 六個交易日變化 (%)")
    ax.set_ylabel("密度")
    ax.set_title("非農前一週 vs 非重疊對照窗")
    ax.legend(fontsize=8)

    ax = axes[1]
    x = np.arange(len(REGIME_LABELS))
    width = 0.38
    ax.bar(x - width / 2, event_regime.reindex(REGIME_LABELS), width=width, color="#d1495b", label="非農前")
    ax.bar(x + width / 2, control_regime.reindex(REGIME_LABELS), width=width, color="#9aa5b1", label="對照")
    ax.set_xticks(x)
    ax.set_xticklabels(REGIME_LABELS)
    ax.axhline(0, color="#333", lw=0.8)
    ax.set_xlabel("視窗起點 VIX")
    ax.set_ylabel("六個交易日平均變化 (%)")
    ax.set_title("相同起點水位：事件窗 vs 對照窗")
    ax.legend(fontsize=8)
    fig.suptitle("非農公佈前一週的 VIX 路徑（官方日期、HAC 修正版）", fontsize=11)
    fig.tight_layout()
    fig.savefig(FIGURE_OUTPUT, dpi=140)
    plt.close(fig)


def run() -> dict[str, Any]:
    started_at = time.time()
    close, releases, release_meta = load_snapshots()
    results, events, controls, _panel = analyze(close, releases, release_meta)
    events.to_csv(EVENTS_OUTPUT, index=False)
    controls.to_csv(CONTROLS_OUTPUT, index=False)
    render_figure(events, controls)
    finalize_experiment(
        results=results,
        entrypoint=__file__,
        canonical_result=CANONICAL_RESULT,
        inputs=[VIX_SNAPSHOT, RELEASE_SNAPSHOT, LEGACY_RESULT],
        outputs=[EVENTS_OUTPUT.name, CONTROLS_OUTPUT.name, FIGURE_OUTPUT.name],
        seeds=[],
        started_at=started_at,
        network="deny",
    )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bootstrap-snapshots",
        action="store_true",
        help="one-time network/cache acquisition; normal reproduction never uses this",
    )
    args = parser.parse_args(argv)
    if args.bootstrap_snapshots:
        bootstrap_snapshots()
        print(f"wrote {VIX_SNAPSHOT.relative_to(REPO_ROOT)}")
        print(f"wrote {RELEASE_SNAPSHOT.relative_to(REPO_ROOT)}")
        return 0
    results = run()
    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
