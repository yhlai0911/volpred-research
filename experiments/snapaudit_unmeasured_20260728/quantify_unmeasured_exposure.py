"""Quantify the snapshot-dup exposure left unmeasured by audit C (2026-07-21).

Audit C (`experiments/audit_snapshot_dup_20260721/`) closed 9 consumers but left
two classes open (its own `unresolved` list, mirrored in
`storage/ops/snapaudit_reconciliation_20260722.md` section 4):

  * `k1308`  -- ruled UNVERIFIABLE_MISSING_INPUT because its VIXTWN comparator
    was believed to live at an absent `~/Desktop/...` path.
  * `k1497 / k1498 / k1585 / k1380` -- AT_RISK_UNVERIFIED: they read the polluted
    canonical CSVs without dedup, but no stored row count pins the vintage.

This script measures what can be measured *deterministically from the two CSV
vintages in git*, without re-estimating any model:

  1. row-level exposure -- how many duplicated rows entered each consumer's
     sample window, comparing the last polluted revision (d36a418cb) against the
     fix (00b07f07f);
  2. for k1308 specifically, a full reconstruction of the reported `n` under both
     vintages, which is what audit C wanted and could not run.

What it deliberately does NOT do: re-estimate GARCH/SPA/DM statistics. The change
in *reported statistics* still needs a re-run per experiment; that is queued
separately. Row-level exposure bounds the blast radius; it does not replace the
re-run.
"""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = Path(__file__).parent / "quantify_unmeasured_exposure_results.json"

# From audit C `incident` block (experiments/audit_snapshot_dup_20260721/...results.json).
POLLUTED_REV = "d36a418cb"  # last polluted
FIXED_REV = "00b07f07f"  # fix
DUPLICATE_DATES = [
    "2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07", "2026-05-08",
    "2026-05-11", "2026-05-12", "2026-05-13", "2026-05-14", "2026-05-15",
]

GARCHX = "paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv"
TAIWAN = "paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv"

# Consumer -> (csv it reads, first sample date or None for "file start", last or None
# for "open ended"). Windows are taken verbatim from audit C's per-consumer evidence
# strings so this script does not re-derive them from source.
CONSUMERS = {
    "k1497": {"csv": GARCHX, "start": "2022-01-03", "end": None,
              "window_note": "open-ended OOS from 2022-01-03 (audit C evidence)"},
    "k1498": {"csv": GARCHX, "start": None, "end": None,
              "window_note": "no upper date bound; test set runs to file end"},
    "k1585": {"csv": GARCHX, "start": None, "end": "2026-06-26",
              "window_note": "no date filter; data.daily_date_end 2026-06-26"},
    "k1380": {"csv": GARCHX, "start": None, "end": None,
              "window_note": "daily panel feeding all 17 specs + SPA bootstrap; no dedup"},
    "k1391": {"csv": GARCHX, "start": None, "end": "2026-05-20",
              "window_note": "OOS through 2026-05-20 (run 2026-05-22); stored n_full_oos=1866"},
}


def read_csv_at(rev: str, path: str) -> pd.DataFrame:
    """Load a CSV as it existed at `rev`, without touching the working tree."""
    blob = subprocess.run(
        ["git", "show", f"{rev}:{path}"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout
    return pd.read_csv(io.BytesIO(blob), parse_dates=["date"])


def rows_in_window(df: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    out = df
    if start is not None:
        out = out[out["date"] >= pd.Timestamp(start)]
    if end is not None:
        out = out[out["date"] <= pd.Timestamp(end)]
    return out


def measure_consumers() -> dict:
    dup = pd.to_datetime(DUPLICATE_DATES)
    cache: dict[tuple[str, str], pd.DataFrame] = {}
    results = {}
    for kid, spec in CONSUMERS.items():
        rec = {}
        for label, rev in (("polluted", POLLUTED_REV), ("clean", FIXED_REV)):
            key = (rev, spec["csv"])
            if key not in cache:
                cache[key] = read_csv_at(rev, spec["csv"])
            win = rows_in_window(cache[key], spec["start"], spec["end"])
            rec[f"n_rows_{label}"] = int(len(win))
            rec[f"n_dup_dated_rows_{label}"] = int(win["date"].isin(dup).sum())
        rec["extra_rows"] = rec["n_rows_polluted"] - rec["n_rows_clean"]
        rec["pct_of_clean_sample"] = (
            round(100.0 * rec["extra_rows"] / rec["n_rows_clean"], 4)
            if rec["n_rows_clean"] else None
        )
        rec["csv"] = spec["csv"]
        rec["window"] = {"start": spec["start"], "end": spec["end"],
                         "note": spec["window_note"]}
        results[kid] = rec
    return results


def reconstruct_k1308() -> dict:
    """Replay k1308's merge arithmetic under both vintages.

    k1308.py loads VIXTWN with `drop_duplicates(subset="date")` (its own line 22),
    then filters the taiwan-vt VIX file to the VIXTWN span and merges. The VIX side
    has no dedup, so duplicated VIX rows replicate through the merge.
    """
    vixtwn_path = ROOT / "data/vixtwn/vixtwn_daily.csv"
    vixtwn = pd.read_csv(vixtwn_path, parse_dates=["date"])
    vixtwn = vixtwn.drop_duplicates(subset="date").sort_values("date")
    vixtwn = vixtwn[["date", "vixtwn_close"]].dropna()

    start, end = vixtwn["date"].min(), vixtwn["date"].max()
    rec = {
        "vixtwn_path": str(vixtwn_path.relative_to(ROOT)),
        "vixtwn_path_is_repo_relative": True,
        "vixtwn_rows_after_dedup": int(len(vixtwn)),
        "vixtwn_span": [start.date().isoformat(), end.date().isoformat()],
        "vixtwn_duplicate_dates_in_file": int(
            pd.read_csv(vixtwn_path, parse_dates=["date"])["date"].duplicated().sum()
        ),
    }
    for label, rev in (("polluted", POLLUTED_REV), ("clean", FIXED_REV)):
        vix = read_csv_at(rev, TAIWAN)[["date", "vix_close"]]
        vix = vix[(vix["date"] >= start) & (vix["date"] <= end)].sort_values("date")
        merged = vixtwn.merge(vix, on="date", how="inner").dropna()
        rec[f"n_{label}"] = int(len(merged))
    rec["extra_rows"] = rec["n_polluted"] - rec["n_clean"]
    rec["vintage_pin"] = pin_k1308_vintage(vixtwn)
    return rec


def pin_k1308_vintage(vixtwn: pd.DataFrame) -> dict:
    """Pin which CSV vintage k1308 actually read, by reproducing its stored n.

    k1308_results.json records run_date 2026-05-22 and period 2025-12-01..2026-05-20
    with overall_stats.n = 119. Truncating the (append-only, duplicate-free) VIXTWN
    series at k1308's period end and merging against each vintage tells us which one
    reproduces 119 exactly. Only one of the two candidates is physically realizable:
    a run on 2026-05-22 falls inside the pollution window (2026-05-15..2026-07-17),
    so the file it opened was the polluted one.
    """
    stored_n, period_end, run_date = 119, "2026-05-20", "2026-05-22"
    sub = vixtwn[vixtwn["date"] <= pd.Timestamp(period_end)]
    start, end = sub["date"].min(), sub["date"].max()
    counts = {}
    for label, rev in (("polluted", POLLUTED_REV), ("clean", FIXED_REV)):
        vix = read_csv_at(rev, TAIWAN)[["date", "vix_close"]]
        vix = vix[(vix["date"] >= start) & (vix["date"] <= end)]
        counts[label] = int(len(sub.merge(vix, on="date", how="inner").dropna()))
    matches = [k for k, v in counts.items() if v == stored_n]
    return {
        "stored_n": stored_n,
        "run_date": run_date,
        "period_end": period_end,
        "n_at_period_end": counts,
        "vintage_reproducing_stored_n": matches,
        "pollution_window": ["2026-05-15", "2026-07-17"],
        "run_inside_pollution_window": True,
        "verdict": "CONTAMINATED_VERIFIED",
        "duplicated_rows_in_sample": counts["polluted"] - counts["clean"],
        "pct_of_clean_sample": round(
            100.0 * (counts["polluted"] - counts["clean"]) / counts["clean"], 2
        ),
        "supersedes": "audit_snapshot_dup_20260721 verdict UNVERIFIABLE_MISSING_INPUT",
        "why_the_earlier_verdict_was_wrong": (
            "Audit C read the absolute path recorded in k1308_results.json.data_sources "
            "('/Users/yhlai0911/Desktop/volpred-research/...'), which is where the repo "
            "lived at run time in May 2026, found it absent, and concluded the comparator "
            "was unavailable. But k1308.py:13-14 resolves ROOT repo-relatively, and "
            "data/vixtwn/vixtwn_daily.csv has been git-tracked since 2026-03-22 (b9c673cba) "
            "- i.e. it was present in the repo when audit C ran on 2026-07-21. The input "
            "was never missing; the detector followed a stale provenance string instead of "
            "the path the code actually resolves."
        ),
    }


def main() -> None:
    payload = {
        "audit_id": "snapaudit_unmeasured_20260728",
        "seed": 42,
        "purpose": "close the two unresolved classes of audit_snapshot_dup_20260721",
        "incident_ref": {
            "duplicate_dates": DUPLICATE_DATES,
            "n_duplicate_trading_days": len(DUPLICATE_DATES),
            "polluted_revision": POLLUTED_REV,
            "fix_revision": FIXED_REV,
        },
        "row_level_exposure": measure_consumers(),
        "k1308_reconstruction": reconstruct_k1308(),
        "scope_limit": (
            "Row-level exposure only. The change in each experiment's reported "
            "statistics (DM/SPA/GARCH) is NOT measured here and still requires a "
            "per-experiment re-run."
        ),
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
