"""Audit the dedup/publish gate decision trail — rule §4 of dedup-gate-audit.md.

Pattern this defends: the 2026-06-23 dedup-gate 8-day content black hole
(`docs/error_log_archive/2026-Q2.md`). The gates now write every decision to
``storage/logs/dedup_decisions.jsonl`` (writers: volpred.publisher.publisher,
volpred.publisher.throttle, volpred.ops.topic_dedup, volpred.ops.content,
volpred.ops.event_jobs), but until WS-F2 nothing ever *read* that trail — an
audit log nobody audits is still a black hole, just a better-documented one.

This module is the single adjudicator for the three §4 conditions:

1. **block rate > 30 %** over the lookback window (default 7 days, the rule's
   weekly cadence) → the gate may have drifted from too-loose to too-strict.
   Only *hard* blocks count in the numerator; warn-only decisions publish and
   are therefore allows. ``hold`` (release pacing) and ``skip`` (event
   coverage) are neither — they are tracked under ``other`` so pacing holds
   cannot fake a dedup-severity signal. A minimum sample (default 10 real
   decisions) guards against one quiet day tripping the ratio.
2. **no pass for N consecutive hours** (default 24) *while the gate is
   actively blocking* → critical, the black-hole recurrence signature. Both
   halves are required: zero allow-class decisions in the window AND at least
   one block-class decision in it. A window with no entries at all is NOT this
   breach — a silent pipeline is the publishing_freshness dead-man switch's
   concern (outcome-level), not the gate audit's.
3. **same narrative arc blocks ≥ 3 distinct candidates** (default) in the
   window → the arc anchor (``matched_id``) keeps swallowing new content;
   review whether it deserves a manual unlock. Retries/probes of one candidate
   are one decision for this condition, not evidence of three swallowed ideas.

The trail mixes two schemas (legacy ``action`` records and structured
``gate``/``decision`` records, plus ``task_generation`` records that carry an
authoritative ``blocked`` bool); ``_classify`` normalizes all of them. The
audit itself is fail-open in the spirit of the rule: unreadable lines are
counted and skipped, and a missing log file is a healthy no-data verdict, not
a breach.

Alert egress is NOT here. Per `.claude/rules/alert.md` the single alert owner
is ``volpred.ops.alerts`` — its ``_parse_dedup_gate_health_state`` condition
calls :func:`audit_dedup_decisions` and routes any breach through the normal
hourly check_alerts dedup/send machinery. CLI wrapper for humans/cron:
``scripts/audit_dedup_gate_decisions.py``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .common import project_path

# Rule §4 defaults. The rule fixes 30% and ≥3; N hours is unpinned there — 24h
# catches a recurrence on the first missed day (the incident ran 8 days).
BLOCK_RATE_THRESHOLD = 0.30
BLOCK_RATE_MIN_DECISIONS = 10
NO_PASS_CRITICAL_HOURS = 24.0
ARC_REPEAT_BLOCK_THRESHOLD = 3
LOOKBACK_DAYS = 7

_ALLOW_DECISIONS = {"pass", "warn"}
_BLOCK_DECISIONS = {"block"}
_OTHER_DECISIONS = {"hold", "skip"}


def _parse_ts_strict(raw: Any) -> datetime:
    """Parse an entry timestamp; raises ValueError so the caller can COUNT the
    failure in the verdict (an audit that quietly drops rows can't be trusted
    to find a black hole)."""
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"missing/non-string ts: {raw!r}")
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _classify(entry: dict[str, Any]) -> tuple[str, str, str | None]:
    """Normalize one trail record to ``(klass, gate_name, arc_id)``.

    klass ∈ {"allow", "block", "other"}: allow = content went through (pass or
    warn-only), block = content was hard-refused, other = neither a publish
    allow nor a dedup refusal (pacing hold, coverage skip, unknown shapes).
    """
    action = str(entry.get("action") or "")
    gate = str(entry.get("gate") or (f"legacy:{action}" if action else "legacy:unknown"))
    arc_id: str | None = None
    for key in ("matched_id", "dup_of"):
        value = entry.get(key)
        if isinstance(value, str) and value:
            arc_id = value
            break
    if arc_id is None:
        matched_ids = entry.get("matched_ids")
        if isinstance(matched_ids, list) and matched_ids and isinstance(matched_ids[0], str):
            arc_id = matched_ids[0]

    # task_generation-style records carry an authoritative bool.
    blocked = entry.get("blocked")
    if isinstance(blocked, bool):
        return ("block" if blocked else "allow"), gate, arc_id

    decision = entry.get("decision")
    if isinstance(decision, str) and decision:
        if decision in _ALLOW_DECISIONS:
            return "allow", gate, arc_id
        if decision in _BLOCK_DECISIONS:
            return "block", gate, arc_id
        if decision in _OTHER_DECISIONS:
            return "other", gate, arc_id
        return "other", gate, arc_id

    if action.startswith("block_"):
        return "block", gate, arc_id
    if action.startswith(("warn_", "pass_", "allow_")) or action == "clean":
        return "allow", gate, arc_id
    return "other", gate, arc_id


def _log_path(storage_dir: str) -> Path:
    # project_path anchors a relative storage_dir to the repo root (cwd-safe —
    # the K1618 cwd-drift class) and passes an absolute one through untouched.
    return project_path(storage_dir, "logs", "dedup_decisions.jsonl")


def _candidate_identity(entry: dict[str, Any]) -> str | None:
    """Return a durable id, never a mutable authoring title.

    One K can legitimately move through ``TBD``, ``K1366 article``, and its
    final headline while the gate is retried. Titles therefore cannot prove
    that separate candidates were blocked.
    """
    for key in ("candidate_id", "target_id"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return f"id:{value.strip()}"
    return None


def audit_dedup_decisions(
    *,
    storage_dir: str = "storage",
    now: datetime | None = None,
    lookback_days: int = LOOKBACK_DAYS,
    no_pass_hours: float = NO_PASS_CRITICAL_HOURS,
    block_rate_threshold: float = BLOCK_RATE_THRESHOLD,
    block_rate_min_decisions: int = BLOCK_RATE_MIN_DECISIONS,
    arc_block_threshold: int = ARC_REPEAT_BLOCK_THRESHOLD,
) -> dict[str, Any]:
    """Adjudicate the three rule-§4 conditions over the decision trail.

    Returns a JSON-able verdict; never raises on trail content (fail-open:
    unparseable lines are counted, a missing file is a healthy no-data run).
    """
    current = now.astimezone(timezone.utc) if now is not None else datetime.now(timezone.utc)
    path = _log_path(storage_dir)
    window_start = current - timedelta(days=lookback_days)
    blackhole_start = current - timedelta(hours=no_pass_hours)

    allows = 0
    blocks = 0
    others = 0
    unparseable = 0
    parse_errors: list[str] = []
    scanned = 0
    recent_allows = 0
    recent_blocks = 0
    last_allow_ts: datetime | None = None
    last_block_ts: datetime | None = None
    earliest_ts: datetime | None = None
    blocking_gates: dict[str, int] = {}
    arc_blocks: dict[str, dict[str, Any]] = {}
    unidentified_arc_blocks = 0

    log_exists = path.exists()
    if log_exists:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
            log_exists = False
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                parse_errors.append(f"bad json line: {exc}")
                unparseable += 1
                continue
            if not isinstance(entry, dict):
                unparseable += 1
                continue
            try:
                ts = _parse_ts_strict(entry.get("ts"))
            except (TypeError, ValueError) as exc:
                parse_errors.append(f"bad ts: {exc}")
                unparseable += 1
                continue
            if ts < window_start or ts > current:
                continue
            scanned += 1
            if earliest_ts is None or ts < earliest_ts:
                earliest_ts = ts
            klass, gate, arc_id = _classify(entry)
            if klass == "allow":
                allows += 1
                if last_allow_ts is None or ts > last_allow_ts:
                    last_allow_ts = ts
                if ts >= blackhole_start:
                    recent_allows += 1
            elif klass == "block":
                blocks += 1
                if last_block_ts is None or ts > last_block_ts:
                    last_block_ts = ts
                if ts >= blackhole_start:
                    recent_blocks += 1
                blocking_gates[gate] = blocking_gates.get(gate, 0) + 1
                if arc_id:
                    candidate = _candidate_identity(entry)
                    bucket = arc_blocks.setdefault(
                        arc_id,
                        {
                            "arc_id": arc_id,
                            "candidates": set(),
                            "raw_blocks": 0,
                            "gates": set(),
                            "last_ts": ts,
                        },
                    )
                    if candidate is None:
                        unidentified_arc_blocks += 1
                    else:
                        bucket["candidates"].add(candidate)
                    bucket["raw_blocks"] += 1
                    bucket["gates"].add(gate)
                    if ts > bucket["last_ts"]:
                        bucket["last_ts"] = ts
            else:
                others += 1

    # §4-1 block rate — hard blocks over real (allow+block) decisions.
    decisions = allows + blocks
    block_rate = (blocks / decisions) if decisions else 0.0
    rate_breached = decisions >= block_rate_min_decisions and block_rate > block_rate_threshold

    # §4-2 black hole — the gate is firing, and nothing has passed for N hours.
    blackhole_breached = recent_blocks > 0 and recent_allows == 0
    # Streak = hours since the last allow; with no allow anywhere in the
    # window, the best honest lower bound is "since the oldest scanned entry".
    streak_anchor = last_allow_ts or earliest_ts
    streak_hours = (
        (current - streak_anchor).total_seconds() / 3600.0 if streak_anchor else 0.0
    )

    # §4-3 same-arc repeat blocks.
    repeat_arcs = sorted(
        (
            {
                "arc_id": info["arc_id"],
                "blocks": info["raw_blocks"],
                "distinct_candidates": len(info["candidates"]),
                "gates": sorted(info["gates"]),
                "last_block_ts": info["last_ts"].isoformat(),
            }
            for info in arc_blocks.values()
            if len(info["candidates"]) >= arc_block_threshold
        ),
        key=lambda item: (item["distinct_candidates"], item["blocks"]),
        reverse=True,
    )
    arc_breached = bool(repeat_arcs)

    findings: list[dict[str, str]] = []
    if blackhole_breached:
        findings.append({
            "id": "no_pass_blackhole",
            "level": "critical",
            "summary": (
                f"最近 {no_pass_hours:.0f}h 內 gate 有 {recent_blocks} 次 block、0 次放行 —"
                " 2026-06-23 內容黑洞的復發特徵"
            ),
        })
    if rate_breached:
        findings.append({
            "id": "block_rate",
            "level": "warn",
            "summary": (
                f"近 {lookback_days} 天 block rate {block_rate:.0%} > {block_rate_threshold:.0%}"
                f"（{blocks}/{decisions}）— gate 可能過嚴"
            ),
        })
    if arc_breached:
        worst = repeat_arcs[0]
        findings.append({
            "id": "arc_repeat_block",
            "level": "warn",
            "summary": (
                f"{len(repeat_arcs)} 個 narrative arc 擋下"
                f" ≥{arc_block_threshold} 個不同候選"
                f"（最多 {worst['arc_id']}："
                f"{worst['distinct_candidates']} 候選／{worst['blocks']} raw blocks）"
                "— review 是否人工 unlock"
            ),
        })

    return {
        "generated_at": current.isoformat(),
        "log_path": str(path),
        "log_exists": log_exists,
        "window": {"lookback_days": lookback_days, "no_pass_hours": no_pass_hours},
        "totals": {
            "scanned": scanned,
            "allow": allows,
            "block": blocks,
            "other": others,
            "unparseable": unparseable,
        },
        "parse_errors": parse_errors,
        "conditions": {
            "block_rate": {
                "breached": rate_breached,
                "rate": round(block_rate, 4),
                "threshold": block_rate_threshold,
                "blocks": blocks,
                "allows": allows,
                "decisions": decisions,
                "min_decisions": block_rate_min_decisions,
                "top_blocking_gates": dict(
                    sorted(blocking_gates.items(), key=lambda kv: kv[1], reverse=True)[:5]
                ),
            },
            "no_pass_blackhole": {
                "breached": blackhole_breached,
                "streak_hours": round(streak_hours, 1),
                "threshold_hours": no_pass_hours,
                "recent_blocks": recent_blocks,
                "recent_allows": recent_allows,
                "last_allow_ts": last_allow_ts.isoformat() if last_allow_ts else None,
                "last_block_ts": last_block_ts.isoformat() if last_block_ts else None,
            },
            "arc_repeat_block": {
                "breached": arc_breached,
                "threshold": arc_block_threshold,
                "unidentified_blocks": unidentified_arc_blocks,
                "repeat_arcs": repeat_arcs[:10],
            },
        },
        "findings": findings,
        "healthy": not findings,
    }
