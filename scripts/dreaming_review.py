#!/usr/bin/env python3
"""Dreaming review — the slow loop of VolPred's loop-engineering layer.

Background (2026-06-29): the fast loop (`src/volpred/ops/loop_health.py`) answers
"is the loop improving?" each hourly tick. This is the **slow loop**: a daily
batch that reads cross-session audit trails — work_log, cron logs, ops receipts,
loop-health — and mines *recurring* failure patterns the single-tick view can't
see. It then surfaces findings, auto-remediates only the safest derived state,
and **proposes (never auto-applies)** changes to governance files.

Design (mirrors `cron_review.py` per-source scanning + `audit_silent_fallbacks.py`
baseline-diff so already-known patterns don't re-spam every day):

- Five detectors, each fail-open (`warn()` then skip on error):
    repeated_tool_failure | recurring_error | stale_knowledge |
    missing_retry_strategy | loop_metric_regression
- A rolling baseline (`storage/ops/dreaming/baseline.json`) tracks each
  signature's consecutive-run strike count. A signature seen for THREE_STRIKE
  consecutive runs escalates to `critical` (the seed for a refactor_plan).
- Auto vs propose-only HARD boundary (research honesty + 永遠修流程不修資料):
    * AUTO (always safe): write the dated report, append autonomous_decisions.jsonl,
      send the dreaming email.
    * AUTO-DISPATCH (low-risk derived state — create a follow-up task): GATED behind
      --apply-auto (default OFF) so the daily cron run stays propose-only until the
      flow is proven. Never touches governance files.
    * PROPOSE-ONLY (governance: error_log / rules / CLAUDE.md / knowledge.json):
      only a `proposal` string + `governance_target` in the report + email. The
      job NEVER writes those files.
- Always exits 0 (a reporting surface; findings live in the JSON + email, not the
  exit code — so host_cron_fail never false-alarms on it).

Entry points:
    uv run volpred ops dreaming-run [--dry-run]
    uv run python scripts/dreaming_review.py [--dry-run] [--apply-auto]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from volpred.ops.common import project_path  # noqa: E402
from volpred.ops.diagnostics import warn  # noqa: E402
from volpred.ops.loop_health import (  # noqa: E402
    LOOP_HEALTH_WINDOW_DAYS,
    RECURRENCE_DEGRADING_COUNT,
    RECURRENCE_DEGRADING_SPAN_DAYS,
    RECURRENCE_WARN_COUNT,
    _is_execution_failure,
    _load_next_tasks,
    _parse_iso,
    _task_terminal_time,
    loop_health_snapshot,
)


# All output paths are storage_dir-scoped (single source of truth) so the job is
# testable against a tmp storage and never writes outside the target storage dir.
def _dreaming_dir(storage_dir: str):
    return project_path(storage_dir) / "ops" / "dreaming"


def _baseline_path(storage_dir: str):
    return _dreaming_dir(storage_dir) / "baseline.json"


def _decisions_log(storage_dir: str):
    return project_path(storage_dir) / "ops" / "autonomous_decisions.jsonl"


def _correction_report(storage_dir: str):
    return project_path(storage_dir) / "content_correction_report.json"


SCHEMA = "dreaming_review.v1"
THREE_STRIKE = 3
# Above this many matched correction keywords, a flagged article is a broad
# review/survey (keyword-overlap false positive), not a specific reversed claim.
# Observed false positives: 23/34/43 matched keywords on 全景/完整報告/完全指南
# survey articles. A specific disputed claim matches only a handful.
BROAD_REVIEW_KEYWORD_FLOOR = 12
# A cron failure cluster with no occurrence in this many hours has RECOVERED and
# is a past incident, not an active failure — it stops being a finding.
RECOVERED_THRESHOLD_HOURS = 48
# Flag when this fraction of recent NON-daily articles are semantic rehashes.
SEMANTIC_REHASH_WARN_RATE = 0.30
# Persistent-alert detector thresholds (boss email-12281 / handoff 2026-06-30):
# same alert_key fired ≥N times across ≥M days = root cause unhandled, surface
# it before the boss has to. Aligned with detect_repeated_tool_failures' 48h
# recovered guard so a one-off spike that resolved isn't kept alive.
PERSISTENT_ALERT_MIN_FIRE_COUNT = 3
PERSISTENT_ALERT_MIN_SPAN_DAYS = 3
PERSISTENT_ALERT_RECOVERED_HOURS = 48

# 2026-07-01 fix (boss email-12419: CRITICAL email for something already fixed):
# memory_skill_gap / memory_hygiene are periodic-curation findings, not acute
# bug recurrences — their trigger condition (some memory line uses a process
# keyword without an exact skill-name substring match; feedback-memory count
# >= 45) is structurally near-permanent given this project's memory system
# naturally grows past these thresholds and stays there. Feeding them through
# the SAME three-strike → critical escalation ladder as detect_repeated_tool_
# failures/detect_persistent_alerts (designed for things that SHOULD reach
# zero) guarantees a false "critical, unresolved" alarm every ~3 runs forever,
# even right after a genuine review pass. Their remediation is an explicit
# MONTHLY cadence (feedback_skill_autonomy memory), not "fix immediately" — so
# they are exempted from ever escalating past their initial severity ("info").
NEVER_CRITICAL_PATTERN_TYPES = frozenset({"memory_skill_gap", "memory_hygiene"})

# Governance files dreaming may PROPOSE changes to but must NEVER write.
GOVERNANCE_FILES = (
    "docs/error_log.md",
    ".claude/rules/",
    "CLAUDE.md",
    "storage/memory/knowledge.json",
    "docs/refactor_plan_",
)

# blocked_reason controlled vocab (a failed task carrying one of these is
# intentionally parked, not an orphaned failure). Mirrors
# src/volpred/ops/blocked_reasons.py — kept loose (substring) for free-text rows.
_CONTROLLED_BLOCK_HINTS = (
    "awaiting_",
    "deprecated",
    "compute_runtime_incompatible",
    "self_tagged_optional",
    "kid_collision",
    "prior_attempts_failed",
    "codex_quota_reset_pending",
    "paid_data_source_decision_pending",
    "diversity_rule_post_null_quartet",
    "data_source_blocker",
    "data_eta",
    "data_accumulation",
    "prereq",
    "superseded",
)


@dataclass
class DreamFinding:
    pattern_type: str
    signature: str
    severity: str  # info | warn | critical
    evidence: list[str] = field(default_factory=list)
    remediation: str = "propose_only"  # propose_only | auto_dispatch
    remediation_ref: str | None = None
    proposal: str | None = None
    governance_target: str | None = None
    occurrences: int = 1
    first_seen: str | None = None
    last_seen: str | None = None

    def key(self) -> str:
        return self.signature

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Detectors (each fail-open; main() wraps every call in try/warn)
# ---------------------------------------------------------------------------
def detect_repeated_tool_failures(
    storage_dir: str, snapshot: dict[str, Any], now: datetime
) -> list[DreamFinding]:
    """Recurring non-zero cron exits (from loop_health.error_recurrence).

    2026-06-29: recency-aware. A failure cluster that has RECOVERED (no occurrence
    in RECOVERED_THRESHOLD_HOURS) is a PAST incident, not an active failure — it
    must not keep escalating to critical just because the historical spike is still
    inside the 14d window (hourly_dispatch exit1 spiked 06-26/27 on API death, then
    recovered 06-29, yet kept re-escalating). Only ACTIVE recurrences are findings;
    recovered ones drop out (and resolve in the baseline).
    """
    out: list[DreamFinding] = []
    cutoff_recovered = now.astimezone(timezone.utc) - timedelta(hours=RECOVERED_THRESHOLD_HOURS)
    for entry in snapshot.get("error_recurrence", {}).get("top_recurring", []):
        sig = str(entry.get("signature") or "")
        if ":exit" not in sig:  # cron-exit signatures only here
            continue
        if entry.get("known"):  # self-healing (exit142) tracked elsewhere
            continue
        if entry.get("recovered"):  # root fixed + recent fires clean → not active
            continue
        count = int(entry.get("count") or 0)
        if count < RECURRENCE_WARN_COUNT:
            continue
        last_seen = _parse_iso(entry.get("last_seen"))
        if last_seen is not None and last_seen < cutoff_recovered:
            continue  # recovered past incident — not an active failure
        span = entry.get("span_days") or 0
        # 2026-07-01: surface recency explicitly so a reader (or the boss) can
        # tell "still actively failing" from "root-caused, cooling down toward
        # the 48h auto-clear" without having to grep logs — this ambiguity is
        # exactly what caused a false-alarm CRITICAL escalation (boss email-12419)
        # for an issue already fixed hours earlier.
        hours_since_last = (
            (now.astimezone(timezone.utc) - last_seen).total_seconds() / 3600.0
            if last_seen is not None else None
        )
        recency_note = (
            f" — clean for {hours_since_last:.1f}h since last occurrence "
            f"(auto-clears at {RECOVERED_THRESHOLD_HOURS}h if it stays clean)"
            if hours_since_last is not None and hours_since_last >= 1.0
            else ""
        )
        # Severity is "warn" on sight; critical is EARNED by persistence
        # (three-strike across dreaming runs in reconcile), not by a single
        # in-window spike — a job that already recovered shouldn't cry critical.
        out.append(
            DreamFinding(
                pattern_type="repeated_tool_failure",
                signature=f"repeated_tool_failure:{sig}",
                severity="warn",
                evidence=[
                    f"{sig} ×{count} over {span}d "
                    f"(first {entry.get('first_seen')} → last {entry.get('last_seen')})"
                    f"{recency_note}"
                ],
                remediation="propose_only",
                proposal=(
                    f"Cron job `{sig.split(':')[0]}` returned a non-zero exit {count}× in the "
                    f"window. Investigate the wrapper/script root cause (API death / auth / path). "
                    f"If sustained, open docs/refactor_plan_<job>.md (Three-Strike)."
                ),
                governance_target="docs/error_log.md",
            )
        )
    return out


def detect_recurring_errors(
    storage_dir: str, snapshot: dict[str, Any], now: datetime
) -> list[DreamFinding]:
    """Recurring diagnostics tags (from loop_health.error_recurrence diag: sigs)."""
    out: list[DreamFinding] = []
    for entry in snapshot.get("error_recurrence", {}).get("top_recurring", []):
        sig = str(entry.get("signature") or "")
        if not sig.startswith("diag:"):
            continue
        count = int(entry.get("count") or 0)
        if count < RECURRENCE_WARN_COUNT:
            continue
        out.append(
            DreamFinding(
                pattern_type="recurring_error",
                signature=f"recurring_error:{sig}",
                severity="warn",
                evidence=[f"{sig} ×{count} over {entry.get('span_days')}d"],
                remediation="propose_only",
                proposal=(
                    f"Diagnostics tag `{sig[5:]}` fired {count}× — a code path is repeatedly "
                    f"hitting a fallback. Trace the tag's call sites and fix the root cause."
                ),
                governance_target="docs/error_log.md",
            )
        )
    return out


def detect_stale_knowledge(
    storage_dir: str, snapshot: dict[str, Any], now: datetime
) -> list[DreamFinding]:
    """Published articles flagged by the content-correction scanner (HIGH/MEDIUM).

    Reads the EXISTING report (cheap) rather than re-running the full scan inline.
    A HIGH match = a published article likely repeats a reversed/disproved claim →
    propose a knowledge.json review (governance: propose-only).

    2026-06-29 (boss email-12132/12139): broad-review/summary articles (e.g.
    「波動率預測研究全景：150+ 實驗」) keyword-match dozens of correction
    fingerprints simply because a comprehensive survey mentions every methodology
    — that is a KEYWORD-overlap false positive, not a specific reversed claim. The
    boss's principle is that similarity must be SEMANTIC over the whole topic, not
    keyword count. As a first guard (pending full semantic dedup), skip articles
    whose matched-keyword count is high enough to indicate broad coverage rather
    than a specific disputed claim.
    """
    out: list[DreamFinding] = []
    report_path = _correction_report(storage_dir)
    if not report_path.exists():
        return out
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        warn("dreaming", "content_correction_report read failed; skipping", err=str(exc))
        return out
    flagged = report.get("flagged_articles") if isinstance(report, dict) else None
    if not isinstance(flagged, list):
        return out
    for match in flagged:
        if not isinstance(match, dict):
            continue
        sev = str(match.get("max_severity") or match.get("severity") or "").upper()
        if sev not in ("HIGH", "MEDIUM"):
            continue
        # Broad-review guard: a comprehensive survey naturally matches many
        # keywords (keyword-overlap), which is NOT a specific reversed claim.
        matched_kw = match.get("matched_keywords")
        if isinstance(matched_kw, list) and len(matched_kw) >= BROAD_REVIEW_KEYWORD_FLOOR:
            continue
        aid = str(match.get("id") or match.get("article_id") or "unknown")
        out.append(
            DreamFinding(
                pattern_type="stale_knowledge",
                signature=f"stale_knowledge:{aid}",
                severity="warn" if sev == "HIGH" else "info",
                evidence=[f"content_correction_report flagged {aid} severity={sev}"],
                remediation="propose_only",
                proposal=(
                    f"Published article {aid} matches a self-correction fingerprint ({sev}). "
                    f"Review whether it repeats a reversed/disproved claim; if so update "
                    f"knowledge.json and retract/correct the article."
                ),
                governance_target="storage/memory/knowledge.json",
            )
        )
    return out


def detect_missing_retry_strategy(
    storage_dir: str, snapshot: dict[str, Any], now: datetime
) -> list[DreamFinding]:
    """Execution-failed tasks with no controlled block-reason and no follow-up.

    An orphaned failure = a failed task that was never parked (no blocked_reason
    in the controlled vocab) and has no later task sharing its k_id. These silently
    drop work; surfacing them lets the main thread decide to retry or retire.
    """
    out: list[DreamFinding] = []
    cutoff = now.astimezone(timezone.utc) - timedelta(days=LOOP_HEALTH_WINDOW_DAYS)
    tasks = _load_next_tasks(storage_dir)

    # Map k_id → list of (terminal_time, status) to detect a later follow-up.
    by_kid: dict[str, list[tuple[datetime | None, str]]] = {}
    for t in tasks:
        kid = str(t.get("k_id") or "").strip()
        if kid:
            by_kid.setdefault(kid, []).append((_task_terminal_time(t), str(t.get("status") or "")))

    for t in tasks:
        if not _is_execution_failure(t.get("status")):
            continue
        tt = _task_terminal_time(t)
        if tt is None or tt < cutoff:
            continue
        blocked = str(t.get("blocked_reason") or "").strip().lower()
        if blocked and any(hint in blocked for hint in _CONTROLLED_BLOCK_HINTS):
            continue
        # superseded/follow-up check: same k_id with a non-failed later sibling.
        kid = str(t.get("k_id") or "").strip()
        tid = str(t.get("id") or "unknown")
        has_followup = False
        if kid:
            for sib_time, sib_status in by_kid.get(kid, []):
                if sib_status == t.get("status"):
                    continue
                if not _is_execution_failure(sib_status):
                    has_followup = True
                    break
        # status text itself naming a successor (e.g. *_superseded_by_v2)
        if "supersed" in str(t.get("status") or "").lower():
            has_followup = True
        if has_followup:
            continue
        out.append(
            DreamFinding(
                pattern_type="missing_retry_strategy",
                signature=f"missing_retry_strategy:{kid or tid}",
                severity="warn",
                evidence=[
                    f"task {tid} (k_id={kid or '-'}) status={t.get('status')!r}; "
                    f"no controlled blocked_reason, no follow-up sibling"
                ],
                remediation="auto_dispatch",  # low-risk: create an investigate task (gated by --apply-auto)
                proposal=(
                    f"Failed task {tid} has no retry/follow-up and is not parked. "
                    f"Either retry with a clearer brief or mark it blocked with a controlled reason."
                ),
            )
        )
    return out


def detect_loop_metric_regression(
    storage_dir: str, snapshot: dict[str, Any], now: datetime
) -> list[DreamFinding]:
    """Any loop-health metric (except error_recurrence) at warn/degrading."""
    out: list[DreamFinding] = []
    for metric in ("first_pass_success", "task_outcome", "correction_trend"):
        m = snapshot.get(metric, {})
        status = m.get("status")
        if status not in ("warn", "degrading"):
            continue
        out.append(
            DreamFinding(
                pattern_type="loop_metric_regression",
                signature=f"loop_metric_regression:{metric}",
                # warn on sight; critical earned via three-strike persistence.
                severity="warn",
                evidence=[f"{metric} status={status}: {json.dumps(m, ensure_ascii=False)[:200]}"],
                remediation="propose_only",
                proposal=(
                    f"Loop-health metric `{metric}` is {status}. Investigate the underlying "
                    f"work_log / correction trend and address the regression."
                ),
                governance_target="docs/error_log.md",
            )
        )
    return out


def detect_semantic_concentration(
    storage_dir: str, snapshot: dict[str, Any], now: datetime
) -> list[DreamFinding]:
    """Genuine SEMANTIC rehash of recent topics (boss email-12139 directive).

    Unlike keyword cluster cap, this embeds each article's whole topic and flags
    when many recent non-daily articles are the same topic said again (different
    framing). Fail-open: no finding if embeddings are unavailable. Daily-templated
    bulletins are excluded (by-design repetitive). Cost: cached, ~daily.
    """
    out: list[DreamFinding] = []
    try:
        from volpred.ops.topic_similarity import semantic_concentration_report
    except Exception as exc:
        warn("dreaming", "topic_similarity import failed; skipping semantic check", err=str(exc))
        return out
    report = semantic_concentration_report(storage_dir)
    if report.get("status") in ("semantic_unavailable", None):
        return out
    rate = report.get("rehash_rate") or 0.0
    pairs = report.get("near_twin_pairs") or []
    if rate < SEMANTIC_REHASH_WARN_RATE or not pairs:
        return out
    top = "; ".join(
        f"{p['similarity']}: {p['title'][:30]} || {p['twin'][:30]}" for p in pairs[:3]
    )
    out.append(
        DreamFinding(
            pattern_type="semantic_concentration",
            signature="semantic_concentration:feed",
            severity="warn",
            evidence=[
                f"semantic rehash_rate={rate} over {report.get('sample')} non-daily articles; "
                f"top pairs — {top}"
            ],
            remediation="propose_only",
            proposal=(
                f"{report.get('rehash_count')}/{report.get('sample')} recent non-daily articles "
                f"are SEMANTIC rehashes (same topic, different framing) of another recent article "
                f"— keyword clustering misses these. Diversify topic selection; consider a "
                f"semantic dedup gate at publish (near_duplicates) before releasing a rehash."
            ),
        )
    )
    return out


def detect_memory_governance(
    storage_dir: str, snapshot: dict[str, Any], now: datetime
) -> list[DreamFinding]:
    """慢 loop 記憶治理（2026-06-30 用戶）：(a) 萃取「描述 recurring process/cadence 但
    還沒成 skill」的記憶 → 提議 promote 成 skill / 加排程；(b) feedback 記憶量大 → 提議
    整併去重澄清，讓記憶更清楚易用。propose_only（記憶治理敏感，不自動改）。"""
    import pathlib

    out: list[DreamFinding] = []
    mem_dir = (
        pathlib.Path.home() / ".claude" / "projects"
        / "-Users-yhlai0911-Desktop-volpred-research" / "memory"
    )
    index = mem_dir / "MEMORY.md"
    if not index.exists():
        return out  # silent-ok: auto-memory 不在此機就跳過（fail-open）
    skills_dir = pathlib.Path(storage_dir).resolve().parent / ".claude" / "skills"
    skills = (
        {p.name.lower() for p in skills_dir.iterdir() if p.is_dir()}
        if skills_dir.exists() else set()
    )
    lines = [
        ln.strip() for ln in index.read_text(errors="replace").splitlines()
        if ln.strip().startswith("- [")
    ]
    proc_kw = ("流程", "排程", "每日", "每週", "cadence", "持續", "patrol", "巡檢", "workflow", "auto")
    candidates: list[str] = []
    for ln in lines:
        low = ln.lower()
        if not any(k in ln or k in low for k in proc_kw):
            continue
        covered = any(
            s.replace("-", "").replace("_", "") in low.replace("-", "").replace("_", "")
            for s in skills if len(s) > 5
        )
        if not covered:
            candidates.append(ln[:120])
    if candidates:
        out.append(DreamFinding(
            pattern_type="memory_skill_gap",
            signature="memory_skill_gap:uncodified_process",
            severity="info",
            evidence=candidates[:6],
            proposal="這些記憶描述 recurring process/cadence 但無對應 skill；評估 promote 成 "
                     "skill 或加排程/cadence（見 pdca-operations 技能治理 + operations-cadence）。",
            governance_target=".claude/skills/",
            occurrences=len(candidates),
        ))
    feedback = [ln for ln in lines if "feedback_" in ln]
    if len(feedback) >= 45:
        out.append(DreamFinding(
            pattern_type="memory_hygiene",
            signature="memory_hygiene:consolidation_review",
            severity="info",
            evidence=[f"{len(feedback)} 條 feedback 記憶（>=45，疑有重疊）"],
            proposal="feedback 記憶量大：月度做整併/去重/澄清，讓記憶更清楚易用（避免垃圾桶化）。",
            governance_target="memory/",
            occurrences=len(feedback),
        ))
    return out


def detect_persistent_alerts(
    storage_dir: str, snapshot: dict[str, Any], now: datetime
) -> list[DreamFinding]:
    """Same alert_key recurring across multiple days = root cause unhandled.

    Reads `storage/ops/alert_dedup.json` and surfaces any alert where
    `send_count ≥ PERSISTENT_ALERT_MIN_FIRE_COUNT` AND
    `(last_sent - first_sent) ≥ PERSISTENT_ALERT_MIN_SPAN_DAYS days` AND
    `last_sent ≥ now - PERSISTENT_ALERT_RECOVERED_HOURS` (still active).
    Three-strike across consecutive dreaming runs escalates to critical.

    Why (boss email-12281 / handoff 2026-06-30): historical examples that the
    system NEVER surfaced and only the boss caught — "Host cron failure"
    fired 26× over 2 months, "Release pool starved" 6× over 9 days,
    "hourly-dispatch auth preflight failed" 6× over 16 days. Same key
    recurring means the upstream condition isn't being fixed; the dreaming
    slow loop already audits cross-session trails, so this is the right
    place to surface it. Communication noise (ACK / Re: / boss-report
    summaries) is naturally filtered: each carries unique content → a unique
    alert_key with send_count=1, so the threshold excludes them without a
    title allowlist.
    """
    out: list[DreamFinding] = []
    dedup_path = project_path(storage_dir) / "ops" / "alert_dedup.json"
    if not dedup_path.exists():
        return out  # silent-ok: fresh storage or alerts disabled — no signal yet
    try:
        raw = json.loads(dedup_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        warn("dreaming", "alert_dedup read failed; skipping", err=str(exc))
        return out
    alerts = raw.get("alerts") if isinstance(raw, dict) else None
    if not isinstance(alerts, dict):
        return out

    cutoff_recovered = now.astimezone(timezone.utc) - timedelta(
        hours=PERSISTENT_ALERT_RECOVERED_HOURS
    )
    min_span = timedelta(days=PERSISTENT_ALERT_MIN_SPAN_DAYS)

    for key, entry in alerts.items():
        if not isinstance(entry, dict):
            continue
        try:
            send_count = int(entry.get("send_count") or 0)
        except (TypeError, ValueError) as e:
            warn("detect_persistent_alerts", "bad send_count", key=key, val=entry.get("send_count"), err=str(e))
            continue
        if send_count < PERSISTENT_ALERT_MIN_FIRE_COUNT:
            continue
        first = _parse_iso(entry.get("first_sent_at"))
        last = _parse_iso(entry.get("last_sent_at"))
        if first is None or last is None:
            continue
        if last < cutoff_recovered:
            continue  # recovered: last fire >48h ago → past incident, not active
        if (last - first) < min_span:
            continue  # short burst (e.g. 5 fires in one hour) — not multi-day persistence
        title = str(entry.get("title") or "")[:80] or key[:16]
        span_days = (last - first).total_seconds() / 86400
        # 2026-07-01: same recency annotation as detect_repeated_tool_failures —
        # "send_count=N over M days" alone reads as "still broken" even when the
        # last actual send was hours ago and root-caused; make cooldown explicit.
        hours_since_last = (now.astimezone(timezone.utc) - last).total_seconds() / 3600.0
        recency_note = (
            f" — no fire in {hours_since_last:.1f}h "
            f"(auto-clears at {PERSISTENT_ALERT_RECOVERED_HOURS}h if it stays clean)"
            if hours_since_last >= 1.0
            else ""
        )
        out.append(
            DreamFinding(
                pattern_type="persistent_alert",
                signature=f"persistent_alert:{key[:16]}",
                # warn on sight; critical earned via three-strike persistence
                # across dreaming runs (same as detect_repeated_tool_failures).
                severity="warn",
                evidence=[
                    f"alert_key={key[:16]} title={title!r} "
                    f"send_count={send_count} span={span_days:.1f}d "
                    f"(first {entry.get('first_sent_at')} → last {entry.get('last_sent_at')})"
                    f"{recency_note}"
                ],
                remediation="propose_only",
                proposal=(
                    f"Alert `{title}` fired {send_count}× over {span_days:.1f}d — same "
                    f"alert_key recurring = root cause unhandled (fix the source, not "
                    f"the symptom). Investigate the upstream condition; if sustained "
                    f"across 3 dreaming runs, open docs/refactor_plan_<topic>.md "
                    f"(Three-Strike)."
                ),
                governance_target="docs/error_log.md",
            )
        )
    return out


DETECTORS = (
    detect_repeated_tool_failures,
    detect_recurring_errors,
    detect_stale_knowledge,
    detect_missing_retry_strategy,
    detect_loop_metric_regression,
    detect_semantic_concentration,
    detect_memory_governance,
    detect_persistent_alerts,
)


# ---------------------------------------------------------------------------
# Baseline reconciliation + three-strike
# ---------------------------------------------------------------------------
def load_baseline(storage_dir: str) -> dict[str, dict[str, Any]]:
    path = _baseline_path(storage_dir)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        warn("dreaming", "baseline read failed; starting fresh", err=str(exc))
        return {}
    sigs = raw.get("signatures") if isinstance(raw, dict) else None
    return sigs if isinstance(sigs, dict) else {}


def write_baseline(storage_dir: str, baseline: dict[str, dict[str, Any]], now: datetime) -> None:
    _dreaming_dir(storage_dir).mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "dreaming_baseline.v1",
        "description": "Rolling per-signature consecutive-run strike counts. "
        "THREE_STRIKE consecutive runs escalate to critical.",
        "updated_at": now.astimezone(timezone.utc).isoformat(),
        "signatures": baseline,
    }
    path = _baseline_path(storage_dir)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def reconcile(
    findings: list[DreamFinding],
    baseline: dict[str, dict[str, Any]],
    now: datetime,
) -> tuple[list[DreamFinding], list[str], list[DreamFinding]]:
    """Update strike counts; return (new_findings, resolved_signatures, escalations).

    Mutates `baseline` in memory (caller decides whether to persist). A signature
    present this run increments its strike; absent → removed (resolved).
    """
    iso = now.astimezone(timezone.utc).isoformat()
    current_keys = {f.key() for f in findings}
    new_findings: list[DreamFinding] = []
    escalations: list[DreamFinding] = []

    for f in findings:
        prev = baseline.get(f.key())
        if prev is None:
            baseline[f.key()] = {
                "strike_count": 1,
                "pattern_type": f.pattern_type,
                "first_seen": iso,
                "last_seen": iso,
            }
            f.occurrences = 1
            f.first_seen = iso
            f.last_seen = iso
            new_findings.append(f)
        else:
            prev["strike_count"] = int(prev.get("strike_count", 0)) + 1
            prev["last_seen"] = iso
            f.occurrences = prev["strike_count"]
            f.first_seen = prev.get("first_seen")
            f.last_seen = iso
            if prev["strike_count"] >= THREE_STRIKE and f.pattern_type not in NEVER_CRITICAL_PATTERN_TYPES:
                f.severity = "critical"
                escalations.append(f)

    resolved = [sig for sig in list(baseline.keys()) if sig not in current_keys]
    for sig in resolved:
        baseline.pop(sig, None)

    return new_findings, resolved, escalations


# ---------------------------------------------------------------------------
# Report + email + auto-remediation
# ---------------------------------------------------------------------------
def build_report(
    snapshot: dict[str, Any],
    findings: list[DreamFinding],
    new_findings: list[DreamFinding],
    resolved: list[str],
    escalations: list[DreamFinding],
    now: datetime,
    *,
    dry_run: bool,
    auto_actions: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "window_days": LOOP_HEALTH_WINDOW_DAYS,
        "dry_run": dry_run,
        "loop_health": snapshot,
        "findings": [f.to_dict() for f in findings],
        "new_findings": [f.signature for f in new_findings],
        "resolved_findings": resolved,
        "escalations": [f.signature for f in escalations],
        "auto_remediation": auto_actions,
        "counts": {
            "findings": len(findings),
            "new": len(new_findings),
            "resolved": len(resolved),
            "escalations": len(escalations),
            "propose_only": sum(1 for f in findings if f.remediation == "propose_only"),
            "auto_dispatch_eligible": sum(1 for f in findings if f.remediation == "auto_dispatch"),
        },
    }


def write_report(storage_dir: str, report: dict[str, Any], now: datetime) -> Path:
    _dreaming_dir(storage_dir).mkdir(parents=True, exist_ok=True)
    date_str = now.astimezone(timezone.utc).strftime("%Y-%m-%d")
    path = _dreaming_dir(storage_dir) / f"{date_str}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def append_decision(storage_dir: str, now: datetime, report: dict[str, Any]) -> None:
    log = _decisions_log(storage_dir)
    log.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": now.astimezone(timezone.utc).isoformat(),
        "actor": "dreaming",
        "intent": "cross-session 失敗模式盤點 (loop-engineering slow loop)",
        "reasoning": (
            f"{report['counts']['findings']} findings "
            f"({report['counts']['new']} new, {report['counts']['escalations']} escalations); "
            f"governance findings propose-only."
        ),
        "outcome": f"report storage/ops/dreaming/{now.strftime('%Y-%m-%d')}.json",
        "next": "主線程審 proposals;治理檔不自動改",
    }
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def send_dreaming_email(report: dict[str, Any], now: datetime, storage_dir: str) -> dict[str, Any]:
    from volpred.ops.alerts import send_alert

    c = report["counts"]
    level = "critical" if c["escalations"] else ("warn" if c["new"] else "info")
    date_str = now.astimezone(timezone.utc).strftime("%Y-%m-%d")
    title = f"Dreaming review {date_str} — {c['new']} new / {c['escalations']} escalations"

    lines = ["## 觸發條件"]
    lines.append(
        f"- findings={c['findings']}（new={c['new']}, resolved={c['resolved']}, "
        f"escalations={c['escalations']}）；loop-health overall="
        f"{report['loop_health'].get('overall')}"
    )
    for f in report["findings"][:8]:
        gov = f" → propose {f['governance_target']}" if f.get("governance_target") else ""
        lines.append(
            f"  - [{f['severity']}] {f['pattern_type']}: {f['signature']} "
            f"(×{f['occurrences']}){gov}"
        )
    lines.extend(
        [
            "",
            "## 影響",
            "Dreaming 是 loop-engineering 的慢 loop：跨 session 找重複失敗模式，避免「該被系統先抓到、"
            "卻靠老闆人工抓到」的結構性問題。escalations = 連 3 次 dreaming run 仍未解 → Three-Strike "
            "根治候選。直接服務 Mission #2/#4（研究品質 + 運營穩定）。",
            "",
            "## 建議行動",
            f"1. 看完整報告：`storage/ops/dreaming/{date_str}.json`。",
            "2. 治理類 findings（error_log / rules / knowledge.json）為 **propose-only** — 主線程審 "
            "proposal 後手動決定是否套用，dreaming 不自動改。",
            "3. escalations(critical) → 開 `docs/refactor_plan_<topic>.md` 走 Three-Strike 根治。",
            "4. auto_dispatch 類（orphaned failure）→ `--apply-auto` 才會派修復 task（預設關，先人工審）。",
        ]
    )
    return send_alert(level, title, "\n".join(lines), storage_dir=storage_dir)


def apply_auto_dispatch(
    findings: list[DreamFinding], storage_dir: str, now: datetime
) -> list[dict[str, Any]]:
    """Create follow-up tasks for auto_dispatch findings (gated by --apply-auto).

    Uses the canonical `create_task` API; NEVER touches governance files. Only
    escalated (three-strike) auto_dispatch findings dispatch, to stay conservative.

    NOTE (honest limitation): `create_task` writes a control-plane TaskRecord
    under `storage/ops/tasks/` (audit/receipt system), NOT the `next_tasks.json`
    pending queue the hourly dispatcher reads. Bridging the TaskRecord into the
    pending queue is a deliberate follow-up; until then an --apply-auto dispatch
    surfaces the task in the control plane for the main thread to action. This is
    why --apply-auto defaults OFF (the flow is unproven, per the approved design).
    """
    actions: list[dict[str, Any]] = []
    eligible = [f for f in findings if f.remediation == "auto_dispatch" and f.severity == "critical"]
    if not eligible:
        return actions
    try:
        from volpred.ops.local_control_plane import create_task
    except Exception as exc:
        warn("dreaming", "create_task import failed; skipping auto-dispatch", err=str(exc))
        return actions
    for f in eligible:
        try:
            # create_task is keyword-only with a validated vocab: task_family ∈
            # {ops,research,...}, source ∈ {agent,schedule,user}, priority is int
            # (lower = higher; platform_ops convention ≈ 3). dreaming provenance
            # rides in payload since "dreaming" is not a valid TASK_SOURCE.
            task = create_task(
                title=f"[dreaming] 調查 {f.signature}",
                description=f.proposal or f.signature,
                task_family="ops",
                source="agent",
                priority=3,
                preferred_agent="claude",
                payload={"origin": "dreaming", "signature": f.signature, "pattern_type": f.pattern_type},
                storage_dir=storage_dir,
            )
            ref = task.get("id") if isinstance(task, dict) else str(task)
            f.remediation_ref = f"ops_task:{ref}"
            actions.append({"signature": f.signature, "action": "auto_dispatched", "task_id": ref})
        except Exception as exc:
            warn("dreaming", "create_task failed; finding stays propose-only", sig=f.signature, err=str(exc))
    return actions


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(
    storage_dir: str = "storage",
    *,
    dry_run: bool = False,
    apply_auto: bool = False,
    now: datetime | None = None,
) -> int:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    snapshot = loop_health_snapshot(storage_dir, now=current)

    findings: list[DreamFinding] = []
    for detector in DETECTORS:
        try:
            findings.extend(detector(storage_dir, snapshot, current))
        except Exception as exc:  # fail-open: one detector dying ≠ whole run dies
            warn("dreaming", f"detector {detector.__name__} failed; skipping", err=str(exc))

    baseline = load_baseline(storage_dir)
    new_findings, resolved, escalations = reconcile(findings, baseline, current)

    auto_actions: list[dict[str, Any]] = []
    if apply_auto and not dry_run:
        auto_actions = apply_auto_dispatch(findings, storage_dir, current)

    report = build_report(
        snapshot, findings, new_findings, resolved, escalations, current,
        dry_run=dry_run, auto_actions=auto_actions,
    )
    report_path = write_report(storage_dir, report, current)
    try:
        shown = report_path.relative_to(REPO)
    except ValueError:
        shown = report_path  # tmp/sandbox storage outside the repo
    print(f"[dreaming] report → {shown}")
    print(
        f"[dreaming] findings={report['counts']['findings']} "
        f"new={report['counts']['new']} resolved={report['counts']['resolved']} "
        f"escalations={report['counts']['escalations']} dry_run={dry_run}"
    )

    if not dry_run:
        write_baseline(storage_dir, baseline, current)
        try:
            append_decision(storage_dir, current, report)
        except OSError as exc:
            warn("dreaming", "autonomous_decisions append failed", err=str(exc))
        if new_findings or escalations:
            try:
                send_dreaming_email(report, current, storage_dir)
                print("[dreaming] email sent to boss")
            except Exception as exc:
                warn("dreaming", "dreaming email failed; report still written", err=str(exc))

    return 0  # always 0 — reporting surface, fail-open


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Dreaming review — loop-engineering slow loop")
    parser.add_argument("--storage-dir", default="storage")
    parser.add_argument("--dry-run", action="store_true", help="Detect + write report only; no email/dispatch")
    parser.add_argument("--apply-auto", action="store_true", help="Execute auto_dispatch remediation (default off)")
    args = parser.parse_args()
    return main(storage_dir=args.storage_dir, dry_run=args.dry_run, apply_auto=args.apply_auto)


if __name__ == "__main__":
    sys.exit(_cli())
