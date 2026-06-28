#!/usr/bin/env python3
"""Backfill storage/work_log.json entries from [codex] git commits.

Codex agents commit experiment / digest / ops cleanup directly without
invoking task_pool_claim.py complete, so work_log.json never sees their
work. This script reconstructs missing entries from git history.

Dedup key = commit SHA (stored in `commit` field). Re-running is safe.

Dry-run by default:
    uv run python scripts/backfill_work_log_from_commits.py

Apply (mutates storage/work_log.json):
    uv run python scripts/backfill_work_log_from_commits.py --apply

Custom window:
    uv run python scripts/backfill_work_log_from_commits.py --since 2026-06-25 --until 2026-06-28 --apply
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
WORK_LOG = REPO_ROOT / "storage" / "work_log.json"

# Classification regex (subject patterns → task_type).
# Order matters — first match wins. Anchor on common codex commit verbs.
PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bcomplete\s+(K\d+[a-z]?)\b", re.IGNORECASE), "experiment"),
    (re.compile(r"\bdraft\s+(K\d+[a-z]?)\s+.*article\b", re.IGNORECASE), "daily_article"),
    (re.compile(r"\bpublish\s+.*digest\b", re.IGNORECASE), "daily_digest"),
    (re.compile(r"\bdigest\b", re.IGNORECASE), "daily_digest"),
    (re.compile(r"\bjournal\s+discovery\b", re.IGNORECASE), "governance"),
    (re.compile(r"\b(blog|article|feed|publish)\s+", re.IGNORECASE), "daily_article"),
    (re.compile(r"\b(error.log|governance|backlog)\b", re.IGNORECASE), "governance"),
]
# Default fallback (catches surface/warn/harden/fix/annotate/align/refresh/...).
DEFAULT_TYPE = "platform_ops"

KID_RE = re.compile(r"\b(K\d+[a-z]?)\b")
CODEX_PREFIX = re.compile(r"^\[codex\]\s+", re.IGNORECASE)
DEFAULT_LOOKBACK_DAYS = 2


def _default_since() -> str:
    local_now = datetime.now().astimezone()
    start = (local_now - timedelta(days=DEFAULT_LOOKBACK_DAYS)).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    return start.strftime("%Y-%m-%d %H:%M %z")


def _default_until() -> str:
    local_now = datetime.now().astimezone()
    end = local_now + timedelta(minutes=5)
    return end.strftime("%Y-%m-%d %H:%M %z")


def classify(subject: str) -> tuple[str, Optional[str]]:
    """Return (task_type, k_id)."""
    body = CODEX_PREFIX.sub("", subject).strip()
    kid_match = KID_RE.search(body)
    k_id = kid_match.group(1) if kid_match else None
    for pattern, task_type in PATTERNS:
        if pattern.search(body):
            return task_type, k_id
    return DEFAULT_TYPE, k_id


def git_log(since: str, until: str) -> list[dict[str, str]]:
    out = subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "log",
            f"--since={since}",
            f"--until={until}",
            "--pretty=format:%H|%aI|%s",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    rows: list[dict[str, str]] = []
    for line in out.splitlines():
        if "|" not in line:
            continue
        sha, iso_ts, subject = line.split("|", 2)
        if not CODEX_PREFIX.match(subject):
            continue
        rows.append({"sha": sha, "ts": iso_ts, "subject": subject})
    return rows


def load_work_log() -> list[dict]:
    if not WORK_LOG.exists():
        return []
    data = json.loads(WORK_LOG.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit(f"work_log.json must be a JSON array, got {type(data)}")
    return data


def existing_commit_shas(entries: list[dict]) -> set[str]:
    shas: set[str] = set()
    for entry in entries:
        commit = entry.get("commit")
        if isinstance(commit, str):
            shas.add(commit)
        commits = entry.get("commits")
        if isinstance(commits, list):
            for c in commits:
                if isinstance(c, str):
                    shas.add(c)
    return shas


def build_entry(row: dict[str, str]) -> dict:
    task_type, k_id = classify(row["subject"])
    subject_clean = CODEX_PREFIX.sub("", row["subject"]).strip()
    entry: dict = {
        "timestamp": row["ts"],
        "task_type": task_type,
        "task_id": f"codex-commit-{row['sha'][:9]}",
        "outcome": "succeeded",
        "summary": subject_clean,
        "commit": row["sha"],
        "owner": "codex",
        "backfilled_at": datetime.now(timezone.utc).isoformat(),
        "backfill_source": "scripts/backfill_work_log_from_commits.py",
    }
    if k_id:
        entry["k_id"] = k_id
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since",
        help=(
            "git log --since. Default: local midnight two days ago with an "
            "explicit timezone; **always** pass explicit tz, naked date defaults to UTC"
        ),
    )
    parser.add_argument("--until", help="git log --until. Default: local now + 5 minutes")
    parser.add_argument("--apply", action="store_true", help="write to work_log.json (default dry-run)")
    args = parser.parse_args()

    since = args.since or _default_since()
    until = args.until or _default_until()

    commits = git_log(since, until)
    if not commits:
        print(f"[backfill] no [codex] commits in window since={since} until={until}")
        return 0

    existing = load_work_log()
    seen_shas = existing_commit_shas(existing)

    new_entries: list[dict] = []
    skipped = 0
    for row in commits:
        if row["sha"] in seen_shas:
            skipped += 1
            continue
        new_entries.append(build_entry(row))

    # Sort by timestamp ascending so chronological order matches existing log.
    new_entries.sort(key=lambda e: e["timestamp"])

    print(f"[backfill] commits scanned={len(commits)} already_in_log={skipped} new={len(new_entries)}")
    for entry in new_entries:
        kid = f" [{entry.get('k_id')}]" if entry.get("k_id") else ""
        print(f"  + {entry['timestamp']}  {entry['task_type']:<14}{kid}  {entry['summary'][:70]}")

    if not args.apply:
        print("[backfill] dry-run; pass --apply to write")
        return 0

    if not new_entries:
        print("[backfill] no new entries to write")
        return 0

    combined = existing + new_entries
    WORK_LOG.write_text(
        json.dumps(combined, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[backfill] wrote {len(new_entries)} entries → {WORK_LOG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
