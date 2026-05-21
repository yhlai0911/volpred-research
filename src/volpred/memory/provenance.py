"""Knowledge.json provenance validator (K1259 audit follow-up T3).

Background:
- v1 audit found 208 hard provenance violations (V1=200 + V2=7 + V3=1)
- v2 audit found +76 numeric-near-keyword (VIOLATION) + 47 weak (WEAK) entries
- Hard baseline = 284 violations as of 2026-05-17
- Root cause: writers accepted PASS/CONDITIONAL_PASS verdicts without
  requiring experiment_id / k_id / experiment_path provenance
- Data-side fix (B1) landed in 92e7cb52; B2-B8 deferred
- This module = process-side gate to stop new violations accumulating

Rule (only applied to NEW entries via _append_to_index):
1. If verdict in {"PASS", "CONDITIONAL_PASS"}: entry MUST carry at least one of
   experiment_id / experiment_ids / k_id / experiment_path / experiment_file /
   experiment_files / experiment_script / related_experiments / source_experiments
2. If verdict == "PASS": entry MUST also carry at least one of
   reviewer / reviewer_source / codex_review / codex_verdict /
   codex_review_verdict / codex_reviewed

NULL / FAIL / MIXED / SUPPORT / CONFIRMED / etc. are NOT gated — only the
PASS-family is, because that's the verdict class that anchors downstream
publication / paper claims and must be provenance-traceable.

See: .claude/rules/experiments.md (K1259 section)
"""
from __future__ import annotations

from typing import Any

# Verdict values that require provenance (matches audit baseline)
GATED_VERDICTS = {"PASS", "CONDITIONAL_PASS"}

# Verdict values that ADDITIONALLY require a reviewer field
REVIEWER_REQUIRED_VERDICTS = {"PASS"}

# Any of these non-empty satisfies the experiment-provenance requirement
PROVENANCE_FIELDS = (
    "experiment_id",
    "experiment_ids",
    "k_id",
    "experiment_path",
    "experiment_file",
    "experiment_files",
    "experiment_script",
    "related_experiments",
    "source_experiments",
)

# Any of these non-empty satisfies the reviewer requirement for PASS
REVIEWER_FIELDS = (
    "reviewer",
    "reviewer_source",
    "codex_review",
    "codex_verdict",
    "codex_review_verdict",
    "codex_reviewed",
)

# Audit-confirmed hard violation count as of 2026-05-17 (B1 partially applied).
# The CI invariant script must NEVER allow the count to exceed this.
KNOWN_VIOLATION_BASELINE = 284

_RULE_REF = ".claude/rules/experiments.md (K1259)"


def _has_nonempty(entry: dict[str, Any], fields: tuple[str, ...]) -> bool:
    for f in fields:
        v = entry.get(f)
        if v is None:
            continue
        if isinstance(v, str) and v.strip() == "":
            continue
        if isinstance(v, (list, tuple, dict)) and len(v) == 0:
            continue
        return True
    return False


def validate_provenance(entry: dict[str, Any]) -> None:
    """Raise ValueError if entry violates K1259 provenance rule.

    Only PASS / CONDITIONAL_PASS verdicts are gated. Entries without a
    `verdict` field, or with NULL / FAIL / MIXED / etc., pass through.
    """
    if not isinstance(entry, dict):
        # Defensive: non-dict slipped past upstream — let json.dump fail later
        return

    verdict_raw = entry.get("verdict")
    if verdict_raw is None:
        return
    verdict = str(verdict_raw).strip().upper()

    # Many historical verdicts carry suffixes ("PASS_NULL", "CONDITIONAL_PASS (SIMULATION)..." etc.)
    # We gate strictly on canonical PASS / CONDITIONAL_PASS prefixes to avoid
    # over-broad gating that would hit suffix-modified historical labels.
    is_pass = verdict == "PASS"
    is_cond_pass = verdict == "CONDITIONAL_PASS"
    if not (is_pass or is_cond_pass):
        return

    if not _has_nonempty(entry, PROVENANCE_FIELDS):
        raise ValueError(
            f"K1259 provenance violation: verdict={verdict!r} requires one of "
            f"{PROVENANCE_FIELDS} to be non-empty. "
            f"item_id={entry.get('item_id') or entry.get('id') or '?'!r}. "
            f"See {_RULE_REF}."
        )

    if is_pass and not _has_nonempty(entry, REVIEWER_FIELDS):
        raise ValueError(
            f"K1259 provenance violation: verdict='PASS' requires one of "
            f"{REVIEWER_FIELDS} to be non-empty (reviewer attribution). "
            f"item_id={entry.get('item_id') or entry.get('id') or '?'!r}. "
            f"See {_RULE_REF}."
        )


def count_violations(entries: list[dict[str, Any]]) -> int:
    """Count entries that would FAIL validate_provenance. Does not raise."""
    n = 0
    for e in entries:
        try:
            validate_provenance(e)
        except ValueError:
            n += 1
    return n
