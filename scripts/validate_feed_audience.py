#!/usr/bin/env python3
"""CI invariant: validate feed.json audience consistency.

Scans storage/reports/feed.json for entries where audience='general' but
title/content contains ≥2 academic keywords. These are mis-tagged entries
that should be 'research' but slipped through as 'general'.

Exit codes:
  0 — PASS (no violations found)
  1 — FAIL (violations found, list printed to stdout)

Invocation examples:
  # Ad-hoc check:
  uv run python scripts/validate_feed_audience.py

  # From hourly cron (suggested addition to audit_publish_sync):
  uv run python scripts/validate_feed_audience.py || echo "FEED AUDIENCE VIOLATIONS DETECTED"

  # From CI:
  uv run python scripts/validate_feed_audience.py
  # exit 1 if violations present
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Duplicate of publisher._ACADEMIC_KEYWORDS to avoid import side effects.
# Keep in sync with src/volpred/publisher/publisher.py _ACADEMIC_KEYWORDS.
_ACADEMIC_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'K\d+', re.IGNORECASE), 'K-id'),
    (re.compile(r'\bp[\s-]?value\b', re.IGNORECASE), 'p-value'),
    (re.compile(r'\bt[-\s]?stat\b', re.IGNORECASE), 't-stat'),
    (re.compile(r'\bQlike\b', re.IGNORECASE), 'QLIKE'),
    (re.compile(r'\bSharpe\b', re.IGNORECASE), 'Sharpe'),
    (re.compile(r'\bBonferroni\b', re.IGNORECASE), 'Bonferroni'),
    (re.compile(r'\bbootstrap\b', re.IGNORECASE), 'bootstrap'),
    (re.compile(r'\bMLE\b'), 'MLE'),
    (re.compile(r'\bcointegration\b', re.IGNORECASE), 'cointegration'),
    (re.compile(r'\bGARCH[-\s]?X\b', re.IGNORECASE), 'GARCH-X'),
    (re.compile(r'\bHarvey\b'), 'Harvey'),
    (re.compile(r'\bDiebold[-\s]?Mariano\b', re.IGNORECASE), 'Diebold-Mariano'),
    (re.compile(r'\bDM\s+test\b', re.IGNORECASE), 'DM test'),
    (re.compile(r'\bHAR[-\s]?RV\b', re.IGNORECASE), 'HAR-RV'),
    (re.compile(r'\bGJR[-\s]?GARCH\b', re.IGNORECASE), 'GJR-GARCH'),
    (re.compile(r'\bEGARCH\b', re.IGNORECASE), 'EGARCH'),
    (re.compile(r'\bGARCH\b', re.IGNORECASE), 'GARCH'),
    (re.compile(r'\bMCS\b'), 'MCS'),
    (re.compile(r'\bVaR\b'), 'VaR'),
]
_THRESHOLD = 2


def count_academic_hits(text: str) -> tuple[int, list[str]]:
    """Count distinct academic keyword hits in text. Returns (count, labels)."""
    hits: list[str] = []
    seen: set[str] = set()
    for pattern, label in _ACADEMIC_PATTERNS:
        if label in seen:
            continue
        if pattern.search(text):
            hits.append(label)
            seen.add(label)
    return len(hits), hits


def check_entry(entry: dict) -> tuple[bool, list[str]]:
    """Return (is_violation, hit_labels) for a single feed entry.

    Violation = audience=='general' AND ≥2 academic keywords in combined
    title + content + description text.
    """
    if entry.get('audience') != 'general':
        return False, []
    if entry.get('status') in ('unpublished', 'archived', 'retracted'):
        return False, []  # skip non-visible entries

    combined = ' '.join(filter(None, [
        entry.get('title', ''),
        entry.get('content', ''),
        entry.get('description', ''),
    ]))
    count, labels = count_academic_hits(combined)
    if count >= _THRESHOLD:
        return True, labels
    return False, []


def main(feed_path: str | None = None) -> int:
    """Scan feed.json and report violations. Returns exit code."""
    if feed_path is None:
        # Default: project root / storage/reports/feed.json
        project_root = Path(__file__).resolve().parent.parent
        feed_path = str(project_root / 'storage' / 'reports' / 'feed.json')

    path = Path(feed_path)
    if not path.exists():
        print(f"[validate_feed_audience] feed.json not found at {path}")
        print("PASS (no feed to validate)")
        return 0

    try:
        with open(path) as f:
            feed = json.load(f)
    except Exception as e:
        print(f"[validate_feed_audience] ERROR reading feed.json: {e}")
        return 1

    violations: list[dict] = []
    for entry in feed:
        is_violation, labels = check_entry(entry)
        if is_violation:
            violations.append({
                'id': entry.get('id', '?'),
                'title': entry.get('title', '')[:80],
                'audience': entry.get('audience'),
                'status': entry.get('status'),
                'academic_keywords': labels,
            })

    if violations:
        print(f"[validate_feed_audience] FAIL — {len(violations)} violation(s) found:")
        print()
        for v in violations:
            print(f"  id={v['id']}")
            print(f"    title   : {v['title']}")
            print(f"    audience: {v['audience']}  (should be 'research')")
            print(f"    status  : {v['status']}")
            print(f"    keywords: {v['academic_keywords']}")
            print()
        print(f"Total violations: {len(violations)}")
        print("These entries have audience='general' but contain ≥2 academic keywords.")
        print("Fix: re-publish with audience='research', or backfill via patch script.")
        return 1
    else:
        total = len(feed)
        general_count = sum(1 for e in feed if e.get('audience') == 'general')
        print(
            f"[validate_feed_audience] PASS — {total} total entries, "
            f"{general_count} general, 0 violations."
        )
        return 0


if __name__ == '__main__':
    feed_arg = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(main(feed_arg))
