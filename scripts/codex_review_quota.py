#!/usr/bin/env python3
"""Fail-closed handling for Codex review quota exhaustion.

The review runner calls ``handle`` after recognizing a usage-limit response.
This module parses the reset clock, blocks related pending tasks through the
canonical task CLI, and emits a deduplicated ops alert.  ``scan`` repairs legacy
zero-byte artifacts produced before the runner used atomic output.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
REVIEW_DIR = ROOT / "storage" / "ops" / "codex_reviews"
MARK_BLOCKED = ROOT / "scripts" / "mark_task_blocked.py"
TAIPEI = ZoneInfo("Asia/Taipei")

USAGE_LIMIT_RE = re.compile(
    r"you.ve hit your usage limit|usage limit.*try again at", re.IGNORECASE | re.DOTALL
)
RESET_RE = re.compile(
    r"try again at\s+([A-Z][a-z]{2})\s+(\d{1,2})(?:st|nd|rd|th)?,\s*"
    r"(\d{4})\s+(\d{1,2}):(\d{2})\s*([AP]M)",
    re.IGNORECASE,
)
KID_RE = re.compile(r"(?i)(?<![a-z0-9])k\d{3,5}[a-z]?(?![a-z0-9])")
DEPENDENCY_RE = re.compile(r"codex|review|verdict|審查|複審|送審|裁決", re.IGNORECASE)
PENDING_STATUSES = {"pending", "pending_main_thread"}


def is_usage_limit(text: str) -> bool:
    return bool(USAGE_LIMIT_RE.search(text))


def parse_reset_at(text: str) -> datetime | None:
    """Parse Codex's English reset timestamp as the host's Taipei time."""
    match = RESET_RE.search(text)
    if not match:
        return None
    month, day, year, hour, minute, meridiem = match.groups()
    raw = f"{month} {day} {year} {hour}:{minute} {meridiem.upper()}"
    try:
        return datetime.strptime(raw, "%b %d %Y %I:%M %p").replace(tzinfo=TAIPEI)
    except ValueError:  # silent-ok: handle() logs unparseable reset clocks and fails closed.
        return None


def _task_text(task: dict) -> str:
    return "\n".join(
        str(task.get(key) or "")
        for key in ("title", "description", "result")
    )


def find_dependent_task_ids(
    tasks: Iterable[object], *, hints: Iterable[str], explicit_ids: Iterable[str] = ()
) -> list[str]:
    """Find pending review dependants without globally blocking unrelated work."""
    explicit = {item.strip() for item in explicit_ids if item.strip()}
    # Only path-sized hints identify the review.  Prompt bodies often mention
    # dozens of comparison K-ids; treating every citation as a dependency would
    # freeze unrelated remediation work when one review hits quota.
    identity_hints = {
        hint.strip() for hint in hints if hint.strip() and "\n" not in hint and len(hint) < 512
    }
    hint_text = "\n".join(identity_hints)
    kids = {match.group(0).lower() for match in KID_RE.finditer(hint_text)}
    found: list[str] = []
    for item in tasks:
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("id") or "")
        if str(item.get("status") or "").lower() not in PENDING_STATUSES:
            continue
        text = _task_text(item)
        title = str(item.get("title") or "")
        title_lower = title.lower()
        exact_artifact_reference = any(hint in text for hint in identity_hints)
        same_kid_review_title = any(kid in title_lower for kid in kids) and bool(
            DEPENDENCY_RE.search(title)
        )
        if task_id in explicit or exact_artifact_reference or (
            same_kid_review_title
        ):
            found.append(task_id)
    return sorted(set(found))


def _load_tasks() -> list[object]:
    payload = json.loads(NEXT_TASKS.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("next_tasks.json root must be a list")
    return payload


def _block_tasks(task_ids: Iterable[str], reset_at: datetime, source: Path) -> list[str]:
    blocked: list[str] = []
    until = reset_at.isoformat(timespec="minutes")
    for task_id in task_ids:
        result = subprocess.run(
            [
                sys.executable,
                str(MARK_BLOCKED),
                "--id",
                task_id,
                "--reason",
                "codex_quota_reset_pending",
                "--until",
                until,
                "--note",
                f"Codex usage limit reported by {source.relative_to(ROOT)}; auto-recheck after reset.",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            print(result.stderr or result.stdout, file=sys.stderr, end="")
            continue
        blocked.append(task_id)
    return blocked


def _emit_alert(*, reset_at: datetime, stderr_paths: list[Path], blocked: list[str]) -> None:
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from volpred.ops.alerts import send_alert

        shown = ", ".join(str(path.relative_to(ROOT)) for path in stderr_paths)
        task_summary = ", ".join(blocked) if blocked else "none inferred"
        send_alert(
            "critical",
            "Codex review quota exhausted",
            "Codex primary-path review is unavailable.\n\n"
            f"- reset_at: {reset_at.isoformat()}\n"
            f"- evidence: {shown}\n"
            f"- blocked_pending_tasks: {task_summary}\n"
            "- verdict publication: suppressed (fail closed)",
        )
    except Exception as exc:  # Alert transport must not hide the quota classification.
        print(f"[codex-quota] WARN alert failed: {type(exc).__name__}: {exc}", file=sys.stderr)


def _companion_prompt(out: Path) -> Path | None:
    name = out.name
    for old, new in (("_verdict.md", "_prompt.md"), ("_review.md", "_prompt.md")):
        if name.endswith(old):
            candidate = out.with_name(name[: -len(old)] + new)
            if candidate.is_file():
                return candidate
    return None


def handle(stderr_path: Path, prompt: Path, out: Path, explicit_ids: list[str]) -> int:
    stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
    if not is_usage_limit(stderr_text):
        print("[codex-quota] stderr is not a usage-limit response", file=sys.stderr)
        return 2
    reset_at = parse_reset_at(stderr_text)
    if reset_at is None:
        print("[codex-quota] usage limit found but reset timestamp is unparseable", file=sys.stderr)
        return 3
    if out.exists() and out.stat().st_size == 0:
        out.unlink()
    prompt_text = prompt.read_text(encoding="utf-8", errors="replace") if prompt.is_file() else ""
    tasks = _load_tasks()
    task_ids = find_dependent_task_ids(
        tasks,
        hints=(str(prompt), str(out), prompt_text),
        explicit_ids=explicit_ids,
    )
    blocked = _block_tasks(task_ids, reset_at, stderr_path)
    _emit_alert(reset_at=reset_at, stderr_paths=[stderr_path], blocked=blocked)
    # These markers flow to the compute worker's stderr.  The raw Codex quota
    # line lives in <verdict>.stderr, not the worker log, so without an explicit
    # marker the outer queue can only classify the non-zero exit as generic.
    print(f"[CODEX_QUOTA_RESET_AT] {reset_at.isoformat()}", file=sys.stderr)
    print("[FAILURE_CLASS] quota", file=sys.stderr)
    print(
        json.dumps(
            {
                "status": "codex_quota_exhausted",
                "reset_at": reset_at.isoformat(),
                "artifact_published": False,
                "blocked_tasks": blocked,
            },
            ensure_ascii=False,
        )
    )
    return 0


def scan_existing(*, apply: bool) -> int:
    records: list[tuple[Path, Path, Path | None, str, datetime]] = []
    for stderr_path in sorted(REVIEW_DIR.glob("*.stderr")):
        text = stderr_path.read_text(encoding="utf-8", errors="replace")
        reset_at = parse_reset_at(text)
        if not is_usage_limit(text) or reset_at is None:
            continue
        out = Path(str(stderr_path)[: -len(".stderr")])
        if out.exists() and out.stat().st_size == 0:
            records.append((stderr_path, out, _companion_prompt(out), text, reset_at))

    if not apply:
        print(json.dumps({"zero_byte_quota_artifacts": [str(r[1]) for r in records]}))
        return 0

    tasks = _load_tasks()
    blocked_all: set[str] = set()
    latest_reset: datetime | None = None
    evidence: list[Path] = []
    for stderr_path, out, prompt, _text, reset_at in records:
        out.unlink()
        evidence.append(stderr_path)
        latest_reset = max(latest_reset, reset_at) if latest_reset else reset_at
        prompt_text = prompt.read_text(encoding="utf-8", errors="replace") if prompt else ""
        ids = find_dependent_task_ids(
            tasks, hints=(str(out), str(prompt or ""), prompt_text)
        )
        blocked_all.update(_block_tasks(ids, reset_at, stderr_path))
    if evidence and latest_reset:
        _emit_alert(reset_at=latest_reset, stderr_paths=evidence, blocked=sorted(blocked_all))
    print(
        json.dumps(
            {
                "removed_zero_byte_artifacts": [str(r[1]) for r in records],
                "blocked_tasks": sorted(blocked_all),
            },
            ensure_ascii=False,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    handler = sub.add_parser("handle")
    handler.add_argument("--stderr", type=Path, required=True)
    handler.add_argument("--prompt", type=Path, required=True)
    handler.add_argument("--out", type=Path, required=True)
    handler.add_argument("--task-id", action="append", default=[])
    scanner = sub.add_parser("scan")
    scanner.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.command == "handle":
        return handle(args.stderr, args.prompt, args.out, args.task_id)
    return scan_existing(apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
