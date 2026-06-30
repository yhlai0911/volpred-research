#!/usr/bin/env python3
"""Paper-submission pipeline stall detector + gate-state reporter.

Reads ``storage/paper_pipeline_status.json`` (the canonical stage tracker for the
paper-submission-pipeline process, see ``.claude/skills/paper-submission-pipeline/SKILL.md``)
and reports, per paper: its stage, days-in-stage, blocker, owner-decision flag, and
whether it is STALLED (days-in-stage > STALL_DAYS).

Loop-engineering intent: make "papers are stalled" an *auto-surfaced* signal instead
of something the owner has to notice. When any paper sits at one stage too long, this
check flags it and (optionally) fires a warn alert.

Exit semantics (FINDINGS, not infra failure):
    exit 1  -> at least one paper is STALLED (or a data problem was found)
    exit 0  -> no stalled papers

  IMPORTANT — if this script is ever placed on host cron, its runtime_schedules.json
  entry MUST carry ``exit_semantics: "findings"`` so host_cron_fail does not misread
  the findings exit-1 as a cron crash (2026-06-30 host_cron_fail lesson, docs/error_log.md).

Usage:
    uv run python scripts/paper_pipeline_check.py            # print JSON report, exit 1 if stalled
    uv run python scripts/paper_pipeline_check.py --alert    # also send warn alert if stalled
    uv run python scripts/paper_pipeline_check.py --status path.json

Importable:
    from scripts.paper_pipeline_check import build_report, load_status
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("paper_pipeline_check")

STALL_DAYS = 7
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATUS_PATH = REPO_ROOT / "storage" / "paper_pipeline_status.json"

# Terminal stages do not "stall" — a paper legitimately rests here.
TERMINAL_STAGES = {"accepted", "rejected"}
# Stages where the next move is owner-timed (submission decision); we still report
# days-in-stage but do not scream STALL purely on age, to avoid nagging on
# owner-gated waits. Stall is reported but tagged owner_gated for context.
OWNER_GATED_STAGES = {"under_journal_review"}


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp; warn (never silent) on failure per no-silent-fallback."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        logger.warning("parse_iso_failed: %s | value=%r", exc, value)
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_status(status_path: Path | str = DEFAULT_STATUS_PATH) -> dict[str, Any]:
    """Load the pipeline status JSON. Raises on missing/corrupt file (fail-loud)."""
    path = Path(status_path)
    if not path.exists():
        raise FileNotFoundError(f"paper pipeline status not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def build_report(
    status: dict[str, Any],
    *,
    now: datetime | None = None,
    stall_days: int | None = None,
) -> dict[str, Any]:
    """Build the stall/gate report from a loaded status dict."""
    now = now or datetime.now(timezone.utc)
    meta = status.get("_meta", {}) or {}
    if stall_days is None:
        stall_days = int(meta.get("stall_days", STALL_DAYS))

    papers = status.get("papers", []) or []
    rows: list[dict[str, Any]] = []
    stalled: list[dict[str, Any]] = []
    data_issues: list[str] = []

    for entry in papers:
        name = entry.get("paper", "<unknown>")
        stage = entry.get("stage", "<unknown>")
        entered = _parse_iso(entry.get("stage_entered_at"))

        if entered is None:
            days_in_stage: float | None = None
            data_issues.append(f"{name}: unparseable stage_entered_at")
        else:
            days_in_stage = round((now - entered).total_seconds() / 86400.0, 2)

        is_terminal = stage in TERMINAL_STAGES
        owner_gated = stage in OWNER_GATED_STAGES
        is_stalled = (
            days_in_stage is not None
            and days_in_stage > stall_days
            and not is_terminal
        )

        row = {
            "paper": name,
            "journal_target": entry.get("journal_target", "decide"),
            "stage": stage,
            "days_in_stage": days_in_stage,
            "blocker": entry.get("blocker", ""),
            "owner_decision_pending": bool(entry.get("owner_decision_pending", False)),
            "owner_gated": owner_gated,
            "stalled": is_stalled,
        }
        rows.append(row)
        if is_stalled:
            stalled.append(row)

    rows.sort(key=lambda r: (r["days_in_stage"] is not None, r["days_in_stage"] or 0.0), reverse=True)
    stalled.sort(key=lambda r: r["days_in_stage"] or 0.0, reverse=True)

    return {
        "generated_at": now.isoformat(),
        "stall_days": stall_days,
        "total_papers": len(rows),
        "stalled_count": len(stalled),
        "data_issues": data_issues,
        "stalled_papers": stalled,
        "papers": rows,
    }


def _format_alert_body(report: dict[str, Any]) -> str:
    lines = [
        f"Stalled papers ({report['stalled_count']} / {report['total_papers']}), "
        f"STALL_DAYS={report['stall_days']}:",
        "",
    ]
    for row in report["stalled_papers"]:
        gated = " [owner-gated]" if row["owner_gated"] else ""
        lines.append(
            f"- **{row['paper']}** ({row['journal_target']}) — stage `{row['stage']}`, "
            f"{row['days_in_stage']}d in stage{gated}\n  blocker: {row['blocker']}"
        )
    if report["data_issues"]:
        lines.append("")
        lines.append("Data issues:")
        for issue in report["data_issues"]:
            lines.append(f"- {issue}")
    return "\n".join(lines)


def maybe_send_alert(report: dict[str, Any]) -> dict[str, Any] | None:
    """Send a warn alert listing stalled papers. Warn-before-fallback on import error."""
    if report["stalled_count"] == 0:
        return None
    try:
        from volpred.ops.alerts import send_alert
    except Exception as exc:  # pragma: no cover - import-time only
        logger.warning("send_alert_import_failed: %s | skipping alert", exc)
        return None

    title = f"論文 pipeline stall: {report['stalled_count']} 篇卡關 > {report['stall_days']}d"
    return send_alert(level="warn", title=title, body=_format_alert_body(report))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paper-submission pipeline stall detector")
    parser.add_argument("--status", default=str(DEFAULT_STATUS_PATH), help="path to status JSON")
    parser.add_argument("--alert", action="store_true", help="send warn alert if any paper stalled")
    parser.add_argument("--stall-days", type=int, default=None, help="override STALL_DAYS")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    status = load_status(args.status)
    report = build_report(status, stall_days=args.stall_days)

    if args.alert:
        result = maybe_send_alert(report)
        report["alert_sent"] = bool(result and result.get("sent"))

    print(json.dumps(report, ensure_ascii=False, indent=2))

    # FINDINGS semantics: exit 1 when there are stalled papers or data issues.
    return 1 if (report["stalled_count"] > 0 or report["data_issues"]) else 0


if __name__ == "__main__":
    sys.exit(main())
