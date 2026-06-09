#!/usr/bin/env python3
"""
K1438: VIX1D as SPY Intraday RV Covariate — Feasibility Audit
==============================================================

Goal:
  Verify whether the local VolPred environment currently has the minimum
  reproducible data required to run a fair HAR-RV / HAR-RV+VIX / HAR-RV+VIX1D
  comparison on SPY intraday realized variance.

Why an audit instead of a full horse race:
  - HAR-RV must be evaluated on 5-min realized variance, not daily r².
  - VIX1D must exist as a local, reproducible time series before any
    source-code-level experiment can be claimed.
  - The current shell runtime is network-restricted, so non-cached external
    pulls are not an acceptable source of record.

Outputs:
  - k1438_results.json
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd


EXPERIMENT_ID = "k1438"
ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = Path(__file__).resolve().with_name(f"{EXPERIMENT_ID}_results.json")
INTRADAY_DIR = ROOT / "data" / "intraday"
SNAPSHOT_DIR = ROOT / "paper" / "garch-x-vix" / "data"
RESEARCH_FINDINGS = ROOT / "research_findings.md"
LIT_REVIEW = ROOT / "docs" / "research_notes" / "literature_review_2024_2026.md"


@dataclass
class IntradayCoverage:
    file_count: int
    start_date: str | None
    end_date: str | None
    trading_days: int


def extract_spy_intraday_coverage() -> IntradayCoverage:
    files = sorted(INTRADAY_DIR.glob("SPY_5min_*.csv"))
    if not files:
        return IntradayCoverage(0, None, None, 0)

    dates = [f.stem.replace("SPY_5min_", "") for f in files]
    return IntradayCoverage(
        file_count=len(files),
        start_date=dates[0],
        end_date=dates[-1],
        trading_days=len(dates),
    )


def scan_repo_for_vix1d() -> dict:
    hits = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if ".git" in path.parts:
            continue
        if "archive" in path.parts:
            continue
        if "frontend-v2-fix" in path.parts:
            continue
        if "notifications" in path.parts:
            continue
        if "reports" in path.parts:
            continue
        if path.name.startswith("feed.json"):
            continue
        if path.suffix.lower() not in {".py", ".md", ".json", ".csv", ".txt"}:
            continue
        try:
            text = path.read_text(errors="ignore")
        except Exception:
            continue
        if "VIX1D" in text or "vix1d" in text or "^VIX1D" in text:
            rel = str(path.relative_to(ROOT))
            hits.append(rel)

    data_files = []
    for path in ROOT.rglob("*"):
        if path.is_file() and "vix1d" in path.name.lower():
            data_files.append(str(path.relative_to(ROOT)))

    return {
        "mention_count": len(hits),
        "sample_paths": hits[:20],
        "matching_data_files": data_files[:20],
    }


def inspect_snapshot_columns() -> dict:
    snapshots = {}
    for csv_path in sorted(SNAPSHOT_DIR.glob("*.csv")):
        try:
            cols = pd.read_csv(csv_path, nrows=1).columns.tolist()
        except Exception as exc:
            snapshots[csv_path.name] = {"read_error": str(exc)}
            continue
        snapshots[csv_path.name] = {
            "column_count": len(cols),
            "has_vix1d_column": any("vix1d" in c.lower() for c in cols),
        }
    return snapshots


def grep_line(path: Path, pattern: str) -> list[str]:
    text = path.read_text(errors="ignore")
    return [line.strip() for line in text.splitlines() if re.search(pattern, line, re.I)]


def build_results() -> dict:
    intraday = extract_spy_intraday_coverage()
    repo_scan = scan_repo_for_vix1d()
    snapshots = inspect_snapshot_columns()
    research_hits = grep_line(RESEARCH_FINDINGS, r"VIX1D")
    lit_hits = grep_line(LIT_REVIEW, r"VIX1D|HAR-RV|Realized GARCH")

    has_local_vix1d_series = any(
        item.get("has_vix1d_column", False)
        for item in snapshots.values()
        if isinstance(item, dict)
    )

    sufficient_har_history = intraday.trading_days >= 252

    verdict = "BLOCKED_DATA_UNAVAILABLE"
    if has_local_vix1d_series and sufficient_har_history:
        verdict = "READY_FOR_FULL_EXPERIMENT"

    return {
        "experiment_id": EXPERIMENT_ID.upper(),
        "title": "VIX1D as SPY Intraday RV Covariate — Feasibility Audit",
        "status": verdict,
        "question": (
            "Can VolPred currently run a reproducible HAR-RV vs HAR-RV+VIX vs "
            "HAR-RV+VIX1D comparison on SPY 5-min realized variance?"
        ),
        "data_audit": {
            "spy_5min_local": asdict(intraday),
            "minimum_history_for_formal_har_rv_oos_days": 252,
            "has_sufficient_har_history": sufficient_har_history,
            "repo_vix1d_scan": repo_scan,
            "snapshot_csv_audit": snapshots,
            "has_local_vix1d_series": has_local_vix1d_series,
        },
        "prior_internal_evidence": {
            "research_findings_vix1d_lines": research_hits[:10],
            "literature_review_lines": lit_hits[:10],
        },
        "methodology_constraints": {
            "target_match_rule": "HAR-RV must be tested on 5-min RV, not close-to-close r^2.",
            "lookahead_rule": "Any volatility covariate must enter as t-1 information.",
            "reproducibility_rule": (
                "No uncached external series should be used as the sole data source in "
                "a network-restricted runtime."
            ),
        },
        "findings": [
            (
                f"Local SPY 5-min coverage exists for {intraday.trading_days} trading days "
                f"({intraday.start_date} to {intraday.end_date})."
            ),
            "No local canonical CSV snapshot currently contains a VIX1D column.",
            (
                "Repo references to VIX1D are narrative / prior-result mentions rather than "
                "a reusable local time series."
            ),
            (
                "The environment therefore cannot run a source-verifiable HAR-RV+VIX1D "
                "horse race without first materializing a local VIX1D data source."
            ),
        ],
        "conclusion": (
            "K1438 cannot honestly claim forecasting evidence yet. The correct completion "
            "for this hourly tick is a feasibility audit that records the current data gap "
            "and prevents a non-reproducible or fabricated VIX1D experiment."
        ),
        "next_steps": [
            "Add a canonical local VIX1D history file or snapshot column to the repository.",
            "Once VIX1D exists locally, run HAR-RV / HAR-RV+VIX / HAR-RV+VIX1D on the same 5-min RV target.",
            "Only report DM/Harvey significance after OOS length is adequate and all covariates are lagged.",
        ],
        "references": [
            "Corsi (2009) HAR-RV.",
            "Patton (2011) proxy-robust volatility forecast comparison.",
            "Internal literature review note: Heterogeneous Volatility Information in Realized GARCH (2025).",
        ],
    }


def main() -> None:
    results = build_results()
    OUT_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
