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
import fcntl
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from volpred.canonical_write import guard_canonical_write  # noqa: E402
from volpred.ops.common import project_path  # noqa: E402
from volpred.ops.diagnostics import warn  # noqa: E402
from volpred.ops import dreaming_revalidate  # noqa: E402
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
from _claude_project_dir import detect_claude_projects_dir  # noqa: E402


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
# same alert condition fired ≥N times across ≥M days = investigate whether
# an upstream cause persists. An alert_key hashes only level+title, so it is NOT
# itself a root-cause identity. Aligned with detect_repeated_tool_failures' 48h
# recovered guard so a one-off spike that resolved isn't kept alive.
PERSISTENT_ALERT_MIN_FIRE_COUNT = 3
PERSISTENT_ALERT_MIN_SPAN_DAYS = 3
PERSISTENT_ALERT_RECOVERED_HOURS = 48

# Unfiled-incident-class thresholds (WS-F3, refactor_plan_ops_master_2026_07):
# alerts.py appends every alert occurrence (sent AND dedup-skipped) to
# storage/ops/incident_candidates.jsonl. A dedupe key seen >= MIN times whose
# class has no corresponding docs/error_log.md entry means the incident was
# never FILED — so its second occurrence was exactly as blind as its first.
# Distinct from detect_persistent_alerts, which asks "does the condition keep
# recurring?" (>=3 fires over >=3 days, still active); this asks "did anyone
# write the class down?" and fires from the second occurrence regardless of
# span or recency — an unfiled class stays unfiled until someone files it.
UNFILED_INCIDENT_MIN_OCCURRENCES = 2
UNFILED_INCIDENT_WINDOW_DAYS = 30
UNFILED_INCIDENT_MAX_FINDINGS = 8

# Anti-stacking ownership: these umbrella alert titles intentionally aggregate
# heterogeneous incidents, while a more granular detector already owns their
# recurrence. `Host cron failure detected` stores the actual job only in
# details.failing_logs; loop_health.error_recurrence tracks it canonically as
# <log>.log:exit<code>. Feeding the umbrella key through this detector as well
# merges unrelated jobs into one false Three-Strike finding.
PERSISTENT_ALERT_DELEGATED_OWNERS = {
    "Host cron failure detected": "loop_health.error_recurrence",
}

# 2026-07-01 fix (boss email-12419: CRITICAL email for something already fixed):
# memory_skill_gap / memory_hygiene are governance-curation findings, not acute
# runtime failures. A real unowned process may remain open for several reviews,
# while feedback-memory count naturally stays above its threshold. Feeding them through
# the SAME three-strike → critical escalation ladder as detect_repeated_tool_
# failures/detect_persistent_alerts (designed for things that SHOULD reach
# zero) guarantees a false "critical, unresolved" alarm every ~3 runs forever,
# even right after a genuine review pass. Their remediation is an explicit
# MONTHLY cadence (feedback_skill_autonomy memory), not "fix immediately" — so
# they are exempted from ever escalating past their initial severity ("info").
NEVER_CRITICAL_PATTERN_TYPES = frozenset({"memory_skill_gap", "memory_hygiene"})

# Remediation 分類 —— 決定 finding 的**出口**，不是決定「誰被打擾」。
#
# 2026-07-20（boss telegram：「為什麼要我看？你自己處理」）：前一版只有兩類，而
# `propose_only` 同時背了兩個意思 ——「不自動改治理檔」（正確的保守）與「等人來看」
# （把工作退回給老闆）。後者讓 7/19 那輪的 10 筆 propose_only 全被算進「需要你看」，
# 而它們全是 repeated_tool_failure / persistent_alert 這種該開工單去查的東西。
# 治理檔不自動改 ≠ 沒人接手：接手的是 hourly dispatch 派出的 agent，不是老闆。
#
#   auto_dispatch — 機器自己修：開 task，agent 可直接改 code。
#   propose_only  — 治理檔（error_log / rules / knowledge.json）不自動改寫，但**自動
#                   開工單**交 hourly dispatch，由 agent 判斷後決定是否改。
#   human_only    — 唯一需要人的出口：destructive，或需要 policy 決策者拍板。
#                   這類**不自動派工**，數量應趨近 0；每多一筆都要說得出為什麼。
REMEDIATION_AUTO_DISPATCH = "auto_dispatch"
REMEDIATION_PROPOSE_ONLY = "propose_only"
REMEDIATION_HUMAN_ONLY = "human_only"

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
    # propose_only | auto_dispatch | human_only — 三個出口的語意見 REMEDIATION_* 常數。
    remediation: str = "propose_only"
    remediation_ref: str | None = None
    proposal: str | None = None
    # The task this finding is ABOUT (not the task dreaming creates to fix it).
    # An auto-dispatched remediation task records it as `follows_up_on`, which is
    # what lets the next run recognise its own fix instead of re-flagging forever.
    subject_task_id: str | None = None
    governance_target: str | None = None
    occurrences: int = 1
    first_seen: str | None = None
    last_seen: str | None = None
    # ISO timestamp of the underlying signal's latest activity (e.g. an alert's
    # last_sent_at). When set, reconcile() only advances the three-strike counter
    # if this marker ADVANCED since the previous dreaming run — a signature that
    # is decaying toward its auto-clear window (marker frozen) must not keep
    # accumulating strikes and false-escalate to critical (boss email-12688:
    # git-push-backup fired a burst 06-30→07-05 then went quiet, yet three daily
    # dreaming runs still saw it inside the 48h window and escalated to CRITICAL).
    activity_marker: str | None = None
    # Set by reconcile(): the underlying signal did not demonstrably advance since the
    # previous run — the condition has stopped happening and is decaying toward its
    # auto-clear window. reconcile() has always COMPUTED this (to hold the strike) and
    # then thrown it away, so a decaying alert still surfaced as an active warn finding
    # and still woke the boss. Keeping it on the finding is what lets the report say
    # "resolving itself" instead of "9 warnings" (boss email-12141 2026-07-19).
    quiescent: bool = False
    # Task type the queue writer stamps on an auto-dispatched follow-up. Defaults to
    # platform_ops (what every detector before 2026-07-12 wanted). An orphaned
    # experiment needs a RESEARCH closure — Codex review + a knowledge.json entry —
    # so it routes as `experiment` and picks up that type's effort tier.
    task_type: str = "platform_ops"
    # Status of the remediation task this finding owns, read back from the queue by
    # `annotate_task_states()`. None = no task found. This is what lets the report
    # distinguish 「開了單」 from 「修好了」: before 2026-07-21 the email counted both as
    # `machine_handled` and printed 「已自動接手 N」, so seven tasks that had sat pending
    # for four days read to the owner as seven solved problems (boss telegram-1224).
    task_status: str | None = None

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


def _is_followup_id(parent_id: str, candidate_id: str) -> bool:
    """True when candidate_id names a retry of parent_id by id lineage.

    Retries are conventionally named off the parent's id — `K1679-rev`,
    `K1679-rev2`, `k1025_v2`, `k628b`. A suffix must start with a separator or a
    lowercase letter, so a numerically adjacent id (`K16791` vs `K1679`) is not
    mistaken for a descendant.
    """
    if not parent_id or candidate_id == parent_id:
        return False
    if not candidate_id.startswith(parent_id):
        return False
    return bool(re.fullmatch(r"[-_.].+|[a-z][\w-]*", candidate_id[len(parent_id) :]))


def detect_missing_retry_strategy(
    storage_dir: str, snapshot: dict[str, Any], now: datetime
) -> list[DreamFinding]:
    """Execution-failed tasks with no controlled block-reason and no follow-up.

    An orphaned failure = a failed task that was never parked (no blocked_reason
    in the controlled vocab) and has no successor. A successor is either a task
    sharing its k_id, or one whose id descends from it (`K1679` → `K1679-rev`).
    Tasks carrying no k_id are the common case, so id lineage — not k_id alone —
    is what keeps a retried failure from being re-flagged every night. These
    silently drop work; surfacing them lets the main thread decide to retry or
    retire.
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

    ids_and_status = [(str(t.get("id") or ""), str(t.get("status") or "")) for t in tasks]

    # Explicit follow-up edges: task.follows_up_on == <parent id>. This is the
    # authoritative successor link. Before it existed (pre-2026-07-14) lineage was
    # guessed from the id string, which only matched a PREFIX — so dreaming's own
    # remediation task (`dreaming_missing_retry_strategy_<parent>`, parent in the
    # SUFFIX) was invisible to it. It re-flagged the failure it had already queued
    # a fix for, every night, until the three-strike counter false-escalated to
    # critical (fable0711_ftd_e1_scale_gating ×5).
    followed_up: set[str] = set()
    for t in tasks:
        parent = str(t.get("follows_up_on") or "").strip()
        if parent and not _is_execution_failure(t.get("status")):
            followed_up.add(parent)

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
        has_followup = tid in followed_up
        if not has_followup and kid:
            for sib_time, sib_status in by_kid.get(kid, []):
                if sib_status == t.get("status"):
                    continue
                if not _is_execution_failure(sib_status):
                    has_followup = True
                    break
        # id lineage: a descendant task (K1679 → K1679-rev / K1679-rev2) that did
        # not itself fail is the retry. Covers the (common) k_id-less tasks.
        if not has_followup:
            for cand_id, cand_status in ids_and_status:
                if _is_followup_id(tid, cand_id) and not _is_execution_failure(cand_status):
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
                subject_task_id=tid,
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


_PROCESS_MEMORY_KEYWORDS = (
    "流程", "排程", "每日", "每週", "每月", "cadence", "持續", "patrol", "巡檢", "workflow",
)
_MEMORY_LINK_RE = re.compile(r"\]\(([^)]+\.md)\)")
_SKILL_PATH_RE = re.compile(r"(?:~/)?\.claude/skills/[A-Za-z0-9_./-]+")


def _process_owner_exists(raw_owner: str, repo_root: Path) -> bool:
    """Resolve an audited process owner declared by a memory note.

    `process_owner` is deliberately a path, not a free-text skill label: the
    detector can verify that the canonical skill/rule/schedule still exists.
    Relative owners are repo-relative; user-level Claude skills may use `~/`.
    """
    value = raw_owner.strip().strip("`\"'").rstrip(".,;:，。；：")
    if not value:
        return False
    owner = Path(value).expanduser()
    if not owner.is_absolute():
        owner = repo_root / owner
    return owner.exists()


def _memory_process_is_covered(
    line: str,
    *,
    mem_dir: Path,
    repo_root: Path,
    skill_names: set[str],
    skill_corpus: str,
) -> bool:
    """Return True only when a recurring-process memory has a verifiable owner.

    The old detector considered a memory covered only when its index line happened
    to contain a skill *directory name*. That missed references and user-level
    skills, so already-codified workflows became the same nightly backlog item.
    """
    normalized_line = line.lower().replace("-", "").replace("_", "")
    if any(
        name.replace("-", "").replace("_", "") in normalized_line
        for name in skill_names
        if len(name) > 5
    ):
        return True

    link = _MEMORY_LINK_RE.search(line)
    if not link:
        return False
    memory_path = mem_dir / Path(link.group(1)).name
    memory_stem = memory_path.stem.lower()
    if memory_stem and memory_stem in skill_corpus:
        return True
    try:
        body = memory_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        warn(
            "dreaming",
            "memory process note read failed; treating as unowned",
            path=str(memory_path),
            err=str(exc),
        )
        return False

    declared = re.search(r"(?m)^process_owner:\s*(.+?)\s*$", body)
    if declared and _process_owner_exists(declared.group(1), repo_root):
        return True

    # Backward compatibility for notes that already point directly at their
    # canonical skill but predate the structured `process_owner` field.
    return any(
        _process_owner_exists(match.group(0), repo_root)
        for match in _SKILL_PATH_RE.finditer(body)
    )


def detect_memory_governance(
    storage_dir: str, snapshot: dict[str, Any], now: datetime
) -> list[DreamFinding]:
    """慢 loop 記憶治理（2026-06-30 用戶）：(a) 萃取「描述 recurring process/cadence 但
    還沒成 skill」的記憶 → 提議 promote 成 skill / 加排程；(b) feedback 記憶量大 → 提議
    整併去重澄清，讓記憶更清楚易用。propose_only（記憶治理敏感，不自動改）。"""
    out: list[DreamFinding] = []
    mem_dir = detect_claude_projects_dir() / "memory"
    index = mem_dir / "MEMORY.md"
    if not index.exists():
        return out  # silent-ok: auto-memory 不在此機就跳過（fail-open）
    repo_root = Path(storage_dir).resolve().parent
    skills_dir = repo_root / ".claude" / "skills"
    skills = (
        {p.name.lower() for p in skills_dir.iterdir() if p.is_dir()}
        if skills_dir.exists() else set()
    )
    skill_corpus_parts: list[str] = []
    if skills_dir.exists():
        for path in skills_dir.rglob("*.md"):
            try:
                skill_corpus_parts.append(path.read_text(encoding="utf-8", errors="replace").lower())
            except OSError as exc:
                warn(
                    "dreaming",
                    "skill coverage file read failed; excluding from owner index",
                    path=str(path),
                    err=str(exc),
                )
                continue
    skill_corpus = "\n".join(skill_corpus_parts)
    lines = [
        ln.strip() for ln in index.read_text(errors="replace").splitlines()
        if ln.strip().startswith("- [")
    ]
    candidates: list[tuple[str, str]] = []
    for ln in lines:
        low = ln.lower()
        if not any(k in ln or k in low for k in _PROCESS_MEMORY_KEYWORDS):
            continue
        if not _memory_process_is_covered(
            ln,
            mem_dir=mem_dir,
            repo_root=repo_root,
            skill_names=skills,
            skill_corpus=skill_corpus,
        ):
            link = _MEMORY_LINK_RE.search(ln)
            identity = Path(link.group(1)).stem if link else re.sub(r"[^a-z0-9]+", "_", low)[:60]
            candidates.append((identity, ln[:120]))
    for identity, evidence in candidates:
        out.append(DreamFinding(
            pattern_type="memory_skill_gap",
            # One process per signature/task. The old aggregate signature meant a
            # succeeded July task permanently swallowed every future, unrelated gap.
            signature=f"memory_skill_gap:{identity}",
            severity="info",
            evidence=[evidence],
            proposal="這筆記憶描述 recurring process/cadence 但無對應 owner；評估 promote 成 "
                     "skill 或加排程/cadence（見 pdca-operations 技能治理 + operations-cadence）。",
            governance_target=".claude/skills/",
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
    """Surface alert conditions that recur across multiple days.

    Reads `storage/ops/alert_dedup.json` and surfaces any alert where
    `send_count ≥ PERSISTENT_ALERT_MIN_FIRE_COUNT` AND
    `(last_sent - first_sent) ≥ PERSISTENT_ALERT_MIN_SPAN_DAYS days` AND
    `last_sent ≥ now - PERSISTENT_ALERT_RECOVERED_HOURS` (still active).
    Three-strike across consecutive dreaming runs escalates to critical.

    Why (boss email-12281 / handoff 2026-06-30): historical examples that the
    system NEVER surfaced and only the boss caught include "Release pool
    starved" firing 6× over 9 days and "hourly-dispatch auth preflight failed"
    firing 6× over 16 days. A key hashes level+title, not the alert body: its
    recurrence proves a condition class recurred, but does not by itself prove
    one root cause remained open. Umbrella classes with a granular canonical
    owner are excluded here to prevent duplicate/false Three-Strike findings.
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
        raw_title = str(entry.get("title") or "")
        if raw_title in PERSISTENT_ALERT_DELEGATED_OWNERS:
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
        title = raw_title[:80] or key[:16]
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
                    f"Alert `{title}` fired {send_count}× over {span_days:.1f}d — the "
                    f"same alert condition recurred. The key alone does not prove one "
                    f"root cause: inspect per-fire evidence, then fix the responsible "
                    f"source rather than the symptom. If the same cause is sustained "
                    f"across 3 dreaming runs, open docs/refactor_plan_<topic>.md "
                    f"(Three-Strike)."
                ),
                governance_target="docs/error_log.md",
                # Freeze the strike counter once the alert stops firing: only an
                # advancing last_sent_at counts as an ACTIVE recurrence.
                activity_marker=str(entry.get("last_sent_at") or "") or None,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Unfiled incident classes — alerts that recur but were never written down
# ---------------------------------------------------------------------------
def _error_log_blob(storage_dir: str) -> str:
    """docs/error_log.md (+ archives), lowercased, for filed-or-not checks.

    Missing files read as empty: a fresh checkout has nothing filed yet, and
    the detector should say so rather than crash.
    """
    root = project_path(storage_dir).parent
    parts: list[str] = []
    main_log = root / "docs" / "error_log.md"
    if main_log.is_file():
        try:
            parts.append(main_log.read_text(encoding="utf-8"))
        except OSError as exc:
            warn("dreaming", "error_log read failed", err=str(exc))
    archive_dir = root / "docs" / "error_log_archive"
    if archive_dir.is_dir():
        for f in sorted(archive_dir.glob("*.md")):
            try:
                parts.append(f.read_text(encoding="utf-8"))
            except OSError as exc:
                warn("dreaming", "error_log archive read failed", path=str(f), err=str(exc))
    return "\n".join(parts).lower()


def detect_unfiled_incident_class(
    storage_dir: str, snapshot: dict[str, Any], now: datetime
) -> list[DreamFinding]:
    """Alert classes that occurred >=2 times but were never filed in error_log.

    WS-F3 (refactor_plan_ops_master_2026_07): "a class nobody filed makes its
    second occurrence identical to its first" — the error_log is the memory
    that turns occurrence N into pattern recognition, and filing used to depend
    entirely on main-thread discipline at alert time. alerts.py now appends
    every occurrence to storage/ops/incident_candidates.jsonl (the draft
    stream); this detector closes the loop by flagging any dedupe key with
    >=UNFILED_INCIDENT_MIN_OCCURRENCES occurrences in the window whose title
    (or dedupe-key prefix) appears nowhere in docs/error_log.md or its
    archives. Filing stays propose-only: what queues is a task asking an agent
    to adjudicate the candidate into a real entry (or record why not).

    The filing contract that makes this loop CLOSEABLE: an entry counts as
    filed when it contains the alert title verbatim or the dedupe key's first
    16 hex chars. The queued proposal says so explicitly.
    """
    path = project_path(storage_dir) / "ops" / "incident_candidates.jsonl"
    if not path.is_file():
        return []  # silent-ok: no alert has ever fired on this storage — no signal yet
    cutoff = now.astimezone(timezone.utc) - timedelta(days=UNFILED_INCIDENT_WINDOW_DAYS)
    groups: dict[str, dict[str, Any]] = {}
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        warn("dreaming", "incident_candidates read failed; skipping", err=str(exc))
        return []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError as exc:
            warn("dreaming", "incident_candidates malformed line skipped",
                 err=str(exc)[:120], head=line[:80])
            continue
        if not isinstance(record, dict):
            warn("dreaming", "incident_candidates non-dict line skipped", head=line[:80])
            continue
        key = str(record.get("dedupe_key") or "")
        if not key:
            continue
        at = _parse_iso(record.get("at"))
        if at is None or at < cutoff:
            continue
        group = groups.setdefault(
            key,
            {"count": 0, "first": at, "last": at, "title": "", "level": ""},
        )
        group["count"] += 1
        group["first"] = min(group["first"], at)
        group["last"] = max(group["last"], at)
        # Latest record wins for presentation fields (titles are stable per key
        # by construction — the key hashes level+title).
        group["title"] = str(record.get("title") or group["title"])
        group["level"] = str(record.get("level") or group["level"])

    candidates = [
        (key, g) for key, g in groups.items()
        if g["count"] >= UNFILED_INCIDENT_MIN_OCCURRENCES and g["title"].strip()
    ]
    if not candidates:
        return []

    blob = _error_log_blob(storage_dir)
    out: list[DreamFinding] = []
    candidates.sort(key=lambda kv: kv[1]["count"], reverse=True)
    for key, g in candidates:
        title = g["title"].strip()
        filed = title.lower() in blob or key[:16] in blob
        if filed:
            continue  # class already has an error_log entry — do not re-propose
        if len(out) >= UNFILED_INCIDENT_MAX_FINDINGS:
            break
        span_days = (g["last"] - g["first"]).total_seconds() / 86400
        out.append(
            DreamFinding(
                pattern_type="unfiled_incident_class",
                signature=f"unfiled_incident_class:{key[:16]}",
                severity="warn",
                remediation="propose_only",
                evidence=[
                    f"dedupe_key={key[:16]} title={title!r} occurred {g['count']}x "
                    f"over {span_days:.1f}d (first {g['first'].isoformat()} → "
                    f"last {g['last'].isoformat()}) with NO docs/error_log.md entry"
                ],
                proposal=(
                    f"Alert class `{title}` occurred {g['count']}x but was never filed in "
                    f"docs/error_log.md — the class has no institutional memory, so each "
                    f"recurrence restarts diagnosis from zero. Adjudicate the candidate "
                    f"(storage/ops/incident_candidates.jsonl, dedupe_key {key[:16]}...) "
                    f"into a real error_log entry: root cause, lesson, enforcement owner. "
                    f"Include the alert title verbatim (or the dedupe-key prefix "
                    f"{key[:16]}) in the entry so this detector recognises the filing. "
                    f"If the class is deliberately not worth filing, record that decision "
                    f"in the entry instead — silence is the only wrong answer."
                ),
                governance_target="docs/error_log.md",
                # Strike only while the class keeps occurring; a decayed one holds.
                activity_marker=g["last"].isoformat(),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Observation ledger — shadow/deprecated states past their decision deadline
# ---------------------------------------------------------------------------
def detect_observation_ledger_breach(
    storage_dir: str, snapshot: dict[str, Any], now: datetime
) -> list[DreamFinding]:
    """Observation items past deadline with no decision (WS-F5, principle 5).

    storage/ops/observation_ledger.json (owner: volpred.ops.observation_ledger;
    CLI `volpred ops observation`) registers every shadow / disabled-but-alive /
    deprecated state WITH a deadline and an action-on-expiry. This detector is
    the enforcement half: an item still `observing` past its deadline — or an
    observing item whose deadline is missing/unparseable (only possible by
    editing the JSON around the CLI) — is a breach. `permanent` items are
    exempt by definition (their exemption is a recorded ruling, e.g. pregate
    shadow after the token_ops_waste gate adjudication); `decided` items are
    closed. The queued task's job is to either execute action_on_expiry or
    extend the deadline explicitly with a reason — limbo is the only breach.
    """
    try:
        from volpred.ops import observation_ledger as obs
    except ImportError as exc:  # fail-open: dreaming must not die on this
        warn("dreaming", "observation_ledger import failed; skipping", err=str(exc))
        return []
    try:
        overdue = obs.overdue_items(storage_dir, now=now)
    except (OSError, ValueError) as exc:
        warn("dreaming", "observation_ledger read failed; skipping", err=str(exc))
        return []
    out: list[DreamFinding] = []
    for item in overdue:
        item_id = str(item.get("id") or "").strip() or "unknown"
        deadline = obs.parse_deadline(item.get("deadline"))
        if deadline is None:
            breach_desc = "deadline missing/unparseable — deadline-less limbo"
            overdue_note = ""
        else:
            days_over = (now.astimezone(timezone.utc) - deadline).total_seconds() / 86400
            breach_desc = f"deadline {item.get('deadline')} passed"
            overdue_note = f" ({days_over:.1f}d overdue)"
        action = str(item.get("action_on_expiry") or "").strip() or "(no action recorded)"
        out.append(
            DreamFinding(
                pattern_type="observation_ledger_breach",
                signature=f"observation_ledger_breach:{item_id}",
                severity="warn",
                # The expiry action is concrete, pre-declared work an agent can
                # execute (retire a legacy path, run an acceptance check) — not
                # a governance-file rewrite, so it dispatches directly.
                remediation="auto_dispatch",
                evidence=[
                    f"observation item `{item_id}`: {breach_desc}{overdue_note} — "
                    f"what: {str(item.get('what') or '')[:160]}"
                ],
                proposal=(
                    f"觀察項 `{item_id}` 逾期未決策。到期動作：{action}。"
                    f"二選一，不准留在 limbo：(a) 執行到期動作並 "
                    f"`uv run volpred ops observation resolve --id {item_id} "
                    f"--resolution <做了什麼>`；(b) 有充分理由才 "
                    f"`uv run volpred ops observation extend --id {item_id} "
                    f"--deadline <ISO> --reason <為什麼>`（展期紀錄留在帳本上）。"
                ),
                activity_marker=None,  # an overdue item IS active until decided
            )
        )
    return out


# ---------------------------------------------------------------------------
# Orphaned experiments — research that was done and then silently dropped
# ---------------------------------------------------------------------------
# Ownership of a RESULT used to be bound, implicitly, to the lifetime of the
# process that produced it. Producers die: a fire hits its 3000s cap and is
# SIGKILLed, an agent exits, a worktree is left behind on a stale base. Whatever
# they made then belongs to nobody, because nothing outside the producer was ever
# told it exists. The artifacts do reach main (file-level harvest works) — and
# then nothing happens to them: no knowledge entry, no article, no paper cite, no
# open task. The experiment ran, cost real tokens, and produced nothing anyone can
# use. That is the waste the owner named on 2026-07-12 (Telegram: 「做了研究結果
# 一直變孤兒浪費」/「這到底又要出現幾次孤兒 立刻從底層改好」).
#
# The fix is a domain-model correction, not another alert: a result belongs to a
# TASK, never to a process. This detector is the reaper that re-attaches an owner.
# It emits a closure TASK (auto_dispatch → queued the same night, no three-strike
# wait — a finished-but-dropped experiment is unambiguous, and making it sit three
# nights to even be noticed IS the waste), so nobody has to remember and the owner
# never has to triage an alert.
ORPHAN_EXPERIMENT_SETTLE_HOURS = 6  # a just-finished run may still be in flight
ORPHAN_EXPERIMENT_MAX_AGE_DAYS = 30  # older = historical backlog; a separate sweep owns it
ORPHAN_EXPERIMENT_MAX_FINDINGS = 5  # per run — the FULL count always ships in evidence
_K_EXPERIMENT_DIR = re.compile(r"^(k\d{3,4})(?:[_-]|$)", re.IGNORECASE)


def _consumer_blob(storage_dir: str) -> str:
    """Everything downstream that could be consuming an experiment, lowercased.

    knowledge.json / feed.json / paper .tex are the real downstream artifacts. An
    OPEN task (pending|in_progress) counts too — someone is on their way to it, so
    it is owned, not orphaned. A `succeeded` task that referenced the experiment
    but left no artifact behind is deliberately NOT a consumer: "closed" without a
    knowledge entry is exactly the failure this detector exists to catch.
    """
    # Delegated so the detector and the pre-dispatch revalidator cannot drift about
    # what "consumer" means — a revalidator using a WIDER definition would clear
    # tasks the detector would still flag, and a narrower one would clear none.
    # No exclusions here: at detection time this finding has no task yet.
    return dreaming_revalidate.consumer_blob(storage_dir)


def detect_orphaned_experiments(
    storage_dir: str, snapshot: dict[str, Any], now: datetime
) -> list[DreamFinding]:
    """Experiments with results on disk that nothing downstream consumes."""
    root = project_path(storage_dir).parent
    exp_root = root / "experiments"
    if not exp_root.is_dir():
        return []
    try:
        consumers = _consumer_blob(storage_dir)
    except (OSError, ValueError) as exc:  # fail-open: dreaming must not die on this
        warn("dreaming", "orphan_experiments: consumer scan failed; skipping", err=str(exc))
        return []

    orphans: list[tuple[float, str, str]] = []  # (age_days, dir_name, kid)
    aged_out = 0
    for d in sorted(exp_root.iterdir()):
        m = _K_EXPERIMENT_DIR.match(d.name) if d.is_dir() else None
        if not m:
            continue  # article / paper evidence dirs are not K-experiments
        results = [
            f for f in d.iterdir()
            if f.is_file() and (f.name.endswith("_results.json") or f.name == "results.json")
        ]
        if not results:
            continue  # never finished — an unfinished run is not an orphaned result
        try:
            newest = max(f.stat().st_mtime for f in results)
        except OSError as exc:
            warn("dreaming", "orphan_experiments: stat failed", path=str(d), err=str(exc))
            continue
        age_days = (now - datetime.fromtimestamp(newest, tz=timezone.utc)).total_seconds() / 86400
        if age_days < ORPHAN_EXPERIMENT_SETTLE_HOURS / 24:
            continue  # still settling; the producing fire may not have closed out yet
        kid = m.group(1).lower()
        if kid in consumers:
            continue  # someone downstream is using it, or an open task owns it
        if age_days > ORPHAN_EXPERIMENT_MAX_AGE_DAYS:
            aged_out += 1
            continue
        orphans.append((age_days, d.name, kid))

    if not orphans:
        return []
    orphans.sort()  # freshest first — closure is cheapest while the context is warm
    shown = orphans[:ORPHAN_EXPERIMENT_MAX_FINDINGS]
    out: list[DreamFinding] = []
    for age_days, name, kid in shown:
        out.append(
            DreamFinding(
                pattern_type="orphaned_experiment",
                signature=f"orphaned_experiment:{kid}",
                severity="warn",
                remediation="auto_dispatch",
                task_type="experiment",
                evidence=[
                    f"experiments/{name}/ has results but no consumer "
                    f"(knowledge.json / feed.json / paper / open task all miss '{kid}')",
                    f"finished {age_days:.1f} days ago",
                    f"orphan backlog this run: {len(orphans)} within "
                    f"{ORPHAN_EXPERIMENT_MAX_AGE_DAYS}d (queueing "
                    f"{len(shown)}), plus {aged_out} older than "
                    f"{ORPHAN_EXPERIMENT_MAX_AGE_DAYS}d not queued",
                ],
                proposal=(
                    f"收尾 experiments/{name}/：讀 results.json → Codex review "
                    f"（CONDITIONAL PASS 以上才可寫）→ 寫 knowledge.json（含 experiment_id "
                    f"+ reviewer provenance）。Null result 照實寫，null 也是結果。"
                    f"若結論可發佈，另排文章 task。收尾後此 K 就不再是孤兒。"
                ),
                governance_target="storage/memory/knowledge.json",
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
    detect_unfiled_incident_class,
    detect_observation_ledger_breach,
    detect_orphaned_experiments,
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


# Sentinel distinguishing a legacy baseline entry (no activity_marker key) from
# one that explicitly stored `None`.
_MARKER_MISSING = object()
# Sentinel for a signature seen for the FIRST time — there is no previous run to
# compare against, so quiescence must be answered in its absolute form.
_NO_PREVIOUS_RUN = object()

# Dreaming runs once a day (cron 05:25). This is the width of "did the signal
# advance since we last looked" — the unit the relative quiescence test measures
# implicitly, and the one the absolute test has to state explicitly.
DREAMING_RUN_INTERVAL_HOURS = 24


def _is_quiescent(activity_marker: str | None, prev_marker: Any, now: datetime) -> bool:
    """quiescent ⟺ 底層訊號在最近一個 run interval 內沒有推進 —— 對外音量的事實基礎。

    這是 quiescence 的**唯一** owner。一個問題（「這個 signal 還在發生嗎？」），
    三種證據來源，依可靠度排序：

    1. 有前一輪 marker → **相對**：marker 沒推進 = 已停火。最可靠，直接觀察到兩個
       時點之間沒有新活動。
    2. legacy baseline entry（marker 欄位還沒寫進去）→ advance 未知 → 保守 hold，
       避免 deploy 邊界上記一次假 strike；下一輪就有 marker 可比，自我修正。
    3. 首見（沒有前一輪）→ **絕對**：marker 距今已超過一個 run interval，等價於
       「若上一輪就看得到它，這一輪比對必然判 quiescent」。

    第 3 條就是 2026-07-19 boss email-12144 點名的洞。舊版只實作第 1 條，於是
    「初見即已停火」的 alert 必吵一次、隔晚才靜音。當時判斷補它要另立一套判定、
    會和 reconcile 的 marker 邏輯變成雙 owner（anti-stacking）—— 那個判斷錯在把
    相對式當成 quiescence 的定義本身。定義其實是「一個 run interval 內沒推進」，
    相對式只是它在「有前值」時的特例。統一成這個問法之後，第 3 條是同一個判準
    換一種證據，不是第二個 owner。
    """
    if not activity_marker:
        return False  # 沒有 marker → 無從判定活躍度，一律當活躍（寧可吵人）
    if prev_marker is _MARKER_MISSING:
        return True  # 見規則 2
    if prev_marker is _NO_PREVIOUS_RUN:
        ts = _parse_iso(activity_marker)
        if ts is None:
            return False  # marker 無法解析 → 不敢判 quiescent，fail toward 通知人
        age_hours = (now.astimezone(timezone.utc) - ts).total_seconds() / 3600.0
        return age_hours >= DREAMING_RUN_INTERVAL_HOURS
    return prev_marker == activity_marker  # 見規則 1


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
                "activity_marker": f.activity_marker,
            }
            f.occurrences = 1
            f.first_seen = iso
            f.last_seen = iso
            # 首見也要判 quiescent：一個「初見即已停火」的 signal 沒有任何行動可做，
            # 不該因為「這是第一次看到它」就當成活躍警報寄出去（boss email-12144）。
            f.quiescent = _is_quiescent(f.activity_marker, _NO_PREVIOUS_RUN, now)
            new_findings.append(f)
        else:
            # A finding that carries an activity_marker only counts as an ACTIVE
            # recurrence when that marker advanced since we last recorded it. If it
            # is frozen (the underlying alert stopped firing and is decaying toward
            # its auto-clear window), hold the strike — do not increment, do not
            # escalate. Prevents a single burst from false-escalating to critical
            # just because it lingers across daily runs inside the 48h window.
            prev_marker = prev.get("activity_marker", _MARKER_MISSING)
            quiescent = _is_quiescent(f.activity_marker, prev_marker, now)
            f.quiescent = quiescent
            if not quiescent:
                prev["strike_count"] = int(prev.get("strike_count", 0)) + 1
            prev["last_seen"] = iso
            prev["activity_marker"] = f.activity_marker
            f.occurrences = prev["strike_count"]
            f.first_seen = prev.get("first_seen")
            f.last_seen = iso
            if (
                not quiescent
                and prev["strike_count"] >= THREE_STRIKE
                and f.pattern_type not in NEVER_CRITICAL_PATTERN_TYPES
            ):
                f.severity = "critical"
                escalations.append(f)

    resolved = [sig for sig in list(baseline.keys()) if sig not in current_keys]
    for sig in resolved:
        baseline.pop(sig, None)

    return new_findings, resolved, escalations


# ---------------------------------------------------------------------------
# Report + email + auto-remediation
# ---------------------------------------------------------------------------
def needs_human_attention(finding: DreamFinding | dict[str, Any]) -> bool:
    """這個 finding 是否需要「人」看？—— dreaming 對外音量的唯一判準。

    設計目標（`loop-health-and-dreaming.md` §Auto vs Propose）把責任切得很清楚：
    `auto_dispatch` 是機器的事（actuator 自 2026-07-12 預設開，finding 一出現就自己
    進 next_tasks），`propose_only` 是人的事（治理檔只有主線程能改）。舊的寄信條件
    `if new_findings or escalations` 判的卻是「有沒有新東西」，於是機器正在處理的、
    以及已經自己停火的，全都照樣寄。

    2026-07-19 boss email-12141 那封 WARN 就是這個 bug 的完整標本：9 個 finding =
    4 個 auto_dispatch（機器已派 task）+ 5 個 quiescent persistent_alert（停火
    12.8–46.5h，48h 自清），escalations=0。零項需要老闆，信照寄，而且信裡自己寫著
    「escalations=0 → 不需要重構」。**一封告訴收件人「你不用做事」的 WARN，就是雜訊。**

    2026-07-20（boss telegram：「為什麼要我看？你自己處理」）補上第三條修正：
    `propose_only` 不再算「要人」。它現在會自動進 next_tasks（見 apply_auto_dispatch），
    所以已經有人接手了 —— 只是那個人是 agent。舊版把它算進「需要你看」，7/19 那輪就
    產生了「需要你看 10」，而那 10 筆全是該開工單去查的 repeated_tool_failure /
    persistent_alert，沒有一筆需要老闆的判斷。

    三條規則，由強到弱：
    1. escalated（severity=critical）→ 要人：連 3 次未解的 Three-Strike 種子，
       要不要動根是 policy 決策，正是這層存在的理由。
    2. quiescent → 不要人：條件已經停止發生，正在自清。回報過去式沒有行動可做。
    3. 其餘 → 只有 human_only 要人（destructive / policy）；auto_dispatch 與
       propose_only 都已經有機器出口。

    接受 DreamFinding 或它的 `to_dict()` 形式：報告寫出去之後（build_report / 寄信）
    手上只剩 dict，而這條規則必須只有一個實作 —— 排序時重寫一次條件，就是文案與行為
    分屬兩處、只有一處被改的老毛病。
    """
    if isinstance(finding, dict):
        severity = finding.get("severity")
        quiescent = bool(finding.get("quiescent"))
        remediation = finding.get("remediation")
    else:
        severity, quiescent, remediation = finding.severity, finding.quiescent, finding.remediation
    if severity == "critical":
        return True
    if quiescent:
        return False
    return remediation == REMEDIATION_HUMAN_ONLY


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
    machine = [
        f
        for f in findings
        if f.remediation in (REMEDIATION_AUTO_DISPATCH, REMEDIATION_PROPOSE_ONLY)
        and not f.quiescent
        and not needs_human_attention(f)
    ]
    machine_fixed = [f for f in machine if f.task_status in TASK_STATES_FIXED]
    machine_stalled = [f for f in machine if f.task_status in TASK_STATES_STALLED]
    # Unknown status (no task row found yet, or the queue was unreadable) counts as
    # NOT DONE. Erring the other way would let a missing row read as a fix.
    machine_queued = [
        f
        for f in machine
        if f.task_status not in TASK_STATES_FIXED and f.task_status not in TASK_STATES_STALLED
    ]
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
            "propose_only": sum(1 for f in findings if f.remediation == REMEDIATION_PROPOSE_ONLY),
            "auto_dispatch_eligible": sum(
                1 for f in findings if f.remediation == REMEDIATION_AUTO_DISPATCH
            ),
            # human_only 是唯一還會落到人身上的類別（destructive / policy）。單獨數，
            # 因為它是這套分類的健康指標：長期應趨近 0，不該悄悄長回去。
            "human_only": sum(1 for f in findings if f.remediation == REMEDIATION_HUMAN_ONLY),
            # 音量控制的三個讀數（見 needs_human_attention）。`actionable_new` 是寄信閘門：
            # 「新」不再等於「值得打擾」，只有新 **且** 需要人判斷的才算。
            "actionable": sum(1 for f in findings if needs_human_attention(f)),
            "actionable_new": sum(1 for f in new_findings if needs_human_attention(f)),
            "quiescent": sum(1 for f in findings if f.quiescent),
            # 機器接手 = auto_dispatch 或 propose_only（後者自 2026-07-20 起也自動開單）。
            # 與 quiescent 互斥：停火中的東西沒有人也沒有機器在動它，兩個數字要能相加。
            #
            # `machine_handled` 只說「機器擁有它」，不說「已經修好」—— 它從一開始就是
            # 這個語意，但 email 把它印成「已自動接手 N」，讀起來像 N 個問題已解決，
            # 實際上那 N 張單可能 pending 好幾天（boss telegram-1224）。所以下面把它
            # 依實際 task status 拆成三個互斥的數，`machine_handled` 保留為三者之和，
            # 舊報告重寄時仍讀得到。
            "machine_handled": len(machine),
            "machine_queued": len(machine_queued),
            "machine_fixed": len(machine_fixed),
            "machine_stalled": len(machine_stalled),
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
            f"({report['counts']['new']} new, {report['counts']['escalations']} escalations, "
            f"{report['counts'].get('actionable', 0)} actionable / "
            f"{report['counts'].get('machine_handled', 0)} machine-handled / "
            f"{report['counts'].get('quiescent', 0)} quiescent); "
            f"propose_only auto-queued; governance files unwritten."
        ),
        "outcome": f"report storage/ops/dreaming/{now.strftime('%Y-%m-%d')}.json",
        "next": "propose_only 已自動開工單交 hourly dispatch;治理檔仍不自動改",
    }
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


@dataclass(frozen=True)
class DreamingSeverityTier:
    """一級嚴重度 → 郵件 level + 該級專屬的建議行動。

    2026-07-18（boss telegram-942）：這段原本是 `level = ... if ... else ...` 加上一組
    寫死的模板字串、再加一個 if/else 文案分支。每次老闆糾正一次文案，就多插一個分支 ——
    這正是「反射式修補」的遺留來源。改成資料表後，新增一級嚴重度或一條行動 = 加一筆資料，
    而且 level 與文案由同一筆資料決定，不會再出現「兩處各自 if、語意漂移」。
    """

    name: str
    # 命中條件只看 report["counts"]，順序由上而下第一個命中者勝（最後一筆必須是 catch-all）。
    matches: Callable[[dict[str, int]], bool]
    alert_level: str  # critical | warn | info（送進 send_alert 的 level）
    # 該級專屬行動；以 str.format(**ctx) 展開，ctx = report["counts"] + date_str
    # （由 send_dreaming_email 組好後傳給 render_dreaming_actions）。
    actions: tuple[str, ...]


# 不論嚴重度都要講的行動（報告位置、propose-only 邊界）。放在專屬行動之前。
_DREAMING_COMMON_ACTIONS_HEAD: tuple[str, ...] = (
    "看完整報告：`storage/ops/dreaming/{date_str}.json`。",
    # 2026-07-20（boss telegram：「為什麼要我看？你自己處理」）：這行原本寫「主線程審
    # proposal 後手動決定」，把治理檔的寫入邊界講成了「等人」。邊界沒變，接手的人變了。
    "治理檔（error_log / rules / knowledge.json）dreaming 仍**不自動改寫** —— 但 "
    "propose_only findings 已**自動開工單**進 `storage/next_tasks.json`，由 hourly "
    "dispatch 派 agent 判斷後決定是否改。**不需要你動手**。",
)

# 放在專屬行動之後的通用行動。
_DREAMING_COMMON_ACTIONS_TAIL: tuple[str, ...] = (
    # 2026-07-19：這行原本寫「`--apply-auto` 才會派修復 task（預設關，先人工審）」，
    # 但 actuator 自 2026-07-12 起 apply_auto 預設 ON。信裡對老闆描述了一個一週前就
    # 不存在的系統。文案與行為分屬兩處、只有一處被改 —— 與 tier 表要修的是同一個病。
    "auto_dispatch 類（orphaned failure / missing retry）→ actuator **預設開啟**，"
    "已自動進 `storage/next_tasks.json`，不需要你動手；`--no-apply-auto` 才會關掉。",
    "唯一還會落到你身上的是 **human_only**（destructive / 需要 policy 決策）"
    "—— 本輪 {human_only} 筆。這個數字長期應該是 0；不是 0 就代表有東西該被機械化而還沒。",
)

# escalations=0 時 findings 都是小型/漸進處理（補 retry 策略、memory 整併），反射式推
# 「從底層重構」是過度反應（boss email-12149 2026-07-18）。warn 與 info 兩級共用這條，
# 所以抽成常數而非在兩筆資料裡各貼一份字串。
_NO_REFACTOR_ACTION = (
    "**escalations=0 → 不需要重構**。本輪 findings 為小型/漸進處理（補 retry 策略、"
    "memory 整併等），依 finding 個別 propose 即可，**不啟動 Three-Strike / refactor_plan**。"
    "找到問題 ≠ 從底層重構。"
)

# 建議行動要與嚴重度成比例。由上而下第一個 matches 命中者決定 level 與專屬行動。
DREAMING_SEVERITY_TIERS: tuple[DreamingSeverityTier, ...] = (
    DreamingSeverityTier(
        name="escalated",
        matches=lambda c: bool(c.get("escalations")),
        alert_level="critical",
        actions=(
            "**escalations={escalations}（critical）** → 開 `docs/refactor_plan_<topic>.md` "
            "走 Three-Strike 根治；這是連 3 次 dreaming run 仍未解的結構性問題，才值得動根。",
        ),
    ),
    DreamingSeverityTier(
        name="new_findings",
        # 判 `actionable_new` 而非 `new`：新的 auto_dispatch / quiescent finding 會寫進
        # 報告，但不構成 warn —— 沒有人需要為它做任何事（見 needs_human_attention）。
        matches=lambda c: bool(c.get("actionable_new")),
        alert_level="warn",
        actions=(_NO_REFACTOR_ACTION,),
    ),
    DreamingSeverityTier(
        name="steady",
        matches=lambda c: True,  # catch-all：沒有 new、沒有 escalation 的例行回報
        alert_level="info",
        actions=(_NO_REFACTOR_ACTION,),
    ),
)


def select_dreaming_tier(counts: dict[str, Any]) -> DreamingSeverityTier:
    """回傳第一個命中的 tier；表尾的 catch-all 保證一定有結果。"""
    for tier in DREAMING_SEVERITY_TIERS:
        if tier.matches(counts):
            return tier
    return DREAMING_SEVERITY_TIERS[-1]


def render_dreaming_actions(tier: DreamingSeverityTier, ctx: dict[str, Any]) -> list[str]:
    """把 tier 的行動展開成編號行。編號由順序決定，不寫死在字串裡。"""
    actions = (*_DREAMING_COMMON_ACTIONS_HEAD, *tier.actions, *_DREAMING_COMMON_ACTIONS_TAIL)
    return [f"{i}. {a.format(**ctx)}" for i, a in enumerate(actions, start=1)]


def send_dreaming_email(report: dict[str, Any], now: datetime, storage_dir: str) -> dict[str, Any]:
    from volpred.ops.alerts import send_alert

    c = report["counts"]
    date_str = now.astimezone(timezone.utc).strftime("%Y-%m-%d")
    tier = select_dreaming_tier(c)
    level = tier.alert_level
    title = f"Dreaming review {date_str} — {c['new']} new / {c['escalations']} escalations"

    lines = ["## 觸發條件"]
    # 「需要你決策」只認 human_only。critical escalation 雖然也會觸發寄信，但它
    # 早就有 task 在跑 —— 把它算進「需要你決策」會讓一個應為 0 的健康指標長期不是 0，
    # 指標一旦說謊就沒人再看它（這正是 7/19「需要你看 10」的翻版）。
    #
    # 「已自動開單」與「已修復」必須分開講。舊版只印一個 `machine_handled`，標題是
    # 「已自動接手 N」—— 那個數字只代表 N 張單進了 next_tasks.json，不代表任何一個
    # 問題被解決；2026-07-21 那 7 張已經 pending 四天，老闆卻讀成 7 個已解決
    # (telegram-1224)。舊報告沒有新欄位時 fall back 到 machine_handled 並全部算作
    # 「尚未執行」——不確定時只能往「還沒好」猜，不能往「已修好」猜。
    machine_total = c.get("machine_handled", 0)
    queued = c.get("machine_queued", machine_total)
    fixed = c.get("machine_fixed", 0)
    stalled = c.get("machine_stalled", 0)
    stalled_txt = f"工單未成 {stalled}（failed / cancelled，需要重開）、" if stalled else ""
    lines.append(
        f"- findings={c['findings']}（**已自動開單 {queued}（尚未執行）**、"
        f"已修復 {fixed}、{stalled_txt}"
        f"自清中 {c.get('quiescent', 0)}、"
        f"需要你決策 {c.get('human_only', 0)}（destructive / policy，應為 0）；"
        f"new={c['new']}, resolved={c['resolved']}, escalations={c['escalations']}）；"
        f"loop-health overall={report['loop_health'].get('overall')}"
    )
    # 需要人的排前面，其餘標明「為什麼不需要你動手」—— 一封信裡混著兩種東西而不說明
    # 差別，收件人就得自己一條一條判，等於把分類工作退回給人。
    ranked = sorted(report["findings"], key=lambda f: not needs_human_attention(f))
    for f in ranked[:8]:
        gov = f" → propose {f['governance_target']}" if f.get("governance_target") else ""
        # 逐筆的 note 同樣不得把「開了單」寫成「已派修復」/「接手」—— 那正是表頭誤導的
        # 逐行版本。單一事實來源是 task_status：沒有 status 就只能說「已開單，尚未執行」。
        status = f.get("task_status")
        if f.get("quiescent"):
            note = " — 已停火、自清中"
        elif f.get("remediation") in (REMEDIATION_AUTO_DISPATCH, REMEDIATION_PROPOSE_ONLY):
            if status in TASK_STATES_FIXED:
                note = f" — 工單已完成（{status}）"
            elif status in TASK_STATES_STALLED:
                note = f" — 工單未成（{status}），需要重開"
            elif status:
                note = f" — 已開工單，尚未執行（status={status}）"
            else:
                note = " — 已開工單，尚未執行（排隊中）"
        else:
            note = " — **需要你決策**（destructive / policy）"
        lines.append(
            f"  - [{f['severity']}] {f['pattern_type']}: {f['signature']} "
            f"(×{f['occurrences']}){gov}{note}"
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
        ]
    )
    # human_only 補預設：舊報告（無此 count）重寄時不該因 KeyError 整封信寄不出去。
    lines.extend(render_dreaming_actions(tier, {"human_only": 0, **c, "date_str": date_str}))
    return send_alert(level, title, "\n".join(lines), storage_dir=storage_dir)


def _dreaming_task_id(signature: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", signature.lower()).strip("_")[:60]
    return f"dreaming_{slug}"


# severity → queue priority. Sole owner of this mapping: it is read once when a task
# is first queued AND again on every later run to re-check an existing row (see
# apply_auto_dispatch), so it must not be inlined twice.
# info 級（memory 整併等月度治理）壓在 P4：propose_only 每晚都會開單，不分級就會把 P3
# 淹掉，急件反而排在後面。
_SEVERITY_PRIORITY = {"critical": 2, "warn": 3}
_SEVERITY_PRIORITY_DEFAULT = 4


def _dreaming_priority(severity: str) -> int:
    return _SEVERITY_PRIORITY.get(severity, _SEVERITY_PRIORITY_DEFAULT)


# Statuses that mean the remediation actually landed. Anything else is either still
# queued or died — neither of which may be reported as fixed.
TASK_STATES_FIXED = frozenset({"succeeded", "succeeded_null_result"})
# Terminal but NOT a fix. Counted separately so a failed/cancelled remediation cannot
# hide inside 「排隊中」 and look like progress that is merely slow.
TASK_STATES_STALLED = frozenset(
    {"failed", "cancelled", "superseded", "expired", "closed_no_action"}
)


def annotate_task_states(findings: list[DreamFinding], storage_dir: str) -> None:
    """Stamp each finding with the status of the remediation task it owns.

    The finding→task edge is `_dreaming_task_id(signature)`, which is deterministic,
    so no extra mapping file is needed — but it was only ever materialised on the run
    that FIRST queued the task (`remediation_ref` was set inside the loop the
    `continue` skipped). Every later run therefore reported `remediation_ref=None` for
    a task that plainly existed, which is why the report could not answer 「修好了嗎」.
    Setting both here makes the edge survive re-runs.

    Read-only, and reuses loop_health's `_load_next_tasks` rather than adding a second
    queue parser.
    """
    try:
        tasks = _load_next_tasks(storage_dir)
    except Exception as exc:  # fail-open: status is a nicety, findings are the payload
        warn("dreaming", "could not read queue for task states", err=str(exc))
        return
    by_id = {str(t.get("id")): t for t in tasks if t.get("id")}
    for f in findings:
        task = by_id.get(_dreaming_task_id(f.signature))
        if task is None:
            continue
        f.task_status = str(task.get("status") or "").strip().lower() or None
        f.remediation_ref = f"next_task:{_dreaming_task_id(f.signature)}"


def apply_auto_dispatch(
    findings: list[DreamFinding], storage_dir: str, now: datetime
) -> list[dict[str, Any]]:
    """Turn findings into pending work. NEVER touches governance files.

    2026-07-12 — the owner asked what dreaming actually does and whether it is
    optimising anything (email-12126: 「那你 dreaming 到底在做什麼？你有在立刻優化嗎？」).
    The honest answer was no, and the reason was structural: dreaming was a detector
    whose actuator was disconnected at BOTH ends.

      1. `--apply-auto` defaults off, and the cron wrapper never passed it.
      2. Behind that switch, this function called `create_task`, which writes a
         TaskRecord under `storage/ops/tasks/` — the receipts/audit trail. The hourly
         dispatcher picks work out of `next_tasks.json`. So even fully enabled, a
         dispatched finding landed in a directory nothing dispatches from. The old
         docstring knew ("bridging the TaskRecord into the pending queue is a
         deliberate follow-up") and shipped anyway.

    Net effect: `memory_skill_gap` and `memory_hygiene` were re-proposed on fifteen
    consecutive nights and acted on zero times. That is not a slow loop, it is an
    open one, and it emailed the owner a WARN every morning to prove it.

    So findings are written to the pending queue now — the file the dispatcher reads.
    The propose-only boundary for GOVERNANCE FILES stands, and matters: nothing here
    rewrites error_log / rules / knowledge.json. What lands is a *task* asking an
    agent to look, which is exactly the human-in-the-loop the boundary was protecting,
    minus the part where nobody ever looks.

    2026-07-20 (boss telegram: 「為什麼要我看？你自己處理」) closed the remaining gap.
    `propose_only` used to wait three nights before becoming work, on the
    theory that persistence is the signal. But the thing doing the waiting was the
    owner's inbox: for those three nights the finding was reported as 「需要你看」, i.e.
    the queue it sat in was a human one. Waiting to see whether a cron job keeps
    exiting non-zero is not judgement worth a person's morning — it is a ticket.
    So propose_only queues on sight too, and the wait is gone rather than moved.

    What still does NOT queue is `human_only` (destructive / policy). That is the one
    exception, it is explicit, and its count should stay near zero.

    Qualifying classes:
      * `auto_dispatch`  — designed for this from the start (warn and up; a warn-level
        orphaned failure is still a failure nobody retried).
      * `propose_only`   — queues on sight. Governance files stay unwritten; what lands
        is a task asking an agent to look.
    """
    actions: list[dict[str, Any]] = []
    eligible = [
        f for f in findings
        if (f.remediation == REMEDIATION_AUTO_DISPATCH and f.severity in ("warn", "critical"))
        or f.remediation == REMEDIATION_PROPOSE_ONLY
    ]
    if not eligible:
        return actions

    # drain-first 水位閘（boss msg 1237：抑制 platform_ops 自我改善提案）。
    # critical 不受閘 —— 那是「現在有東西壞了」，不是 backlog；把它跟改善提案一起
    # 壓住，池子是變淺了，但代價是壞掉的東西沒人修，那不是老闆要的。
    from volpred.ops.pool_pressure import pool_admits_new_work

    queue_path = Path(storage_dir) / "next_tasks.json"
    admission = pool_admits_new_work(
        "dreaming",
        path=queue_path,
        state_path=Path(storage_dir) / "ops" / "drain_first_state.json",
    )
    if not admission.admitted:
        suppressed = [f for f in eligible if f.severity != "critical"]
        eligible = [f for f in eligible if f.severity == "critical"]
        if suppressed:
            warn(
                "dreaming",
                f"drain_first: 抑制 {len(suppressed)} 筆非 critical 提案入池 "
                f"({admission.reason})",
            )
        if not eligible:
            return actions

    # The queue lives under `storage_dir`, not at a module-level constant. Reaching for
    # task_pool_claim._locked_load() here would have been the obvious reuse — and it
    # hardcodes the real repo's next_tasks.json, so every test that drove main() would
    # have written the production queue (the exact bug class the canonical-write gate
    # exists for). What is worth reusing is the hardened serializer underneath it:
    # write_tasks_to_handle serializes fully before truncating, so a crash mid-write
    # cannot leave a half a queue behind (incident 2026-07-05).
    from volpred.ops.next_tasks import write_tasks_to_handle

    queue = Path(storage_dir) / "next_tasks.json"
    guard_canonical_write(queue)
    try:
        queue.parent.mkdir(parents=True, exist_ok=True)
        if not queue.exists():
            queue.write_text("[]", encoding="utf-8")
        with queue.open("r+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)  # same lock every queue writer takes
            try:
                tasks = json.load(fh)
                if not isinstance(tasks, list):
                    warn("dreaming", "next_tasks.json is not a list; refusing to queue")
                    return []
                existing = {
                    str(t.get("id")): t for t in tasks if isinstance(t, dict) and t.get("id")
                }
                for f in eligible:
                    task_id = _dreaming_task_id(f.signature)
                    prior = existing.get(task_id)
                    if prior is not None:
                        # dreaming re-derives the same signature nightly — queue once.
                        # But priority was frozen at the severity the finding had on the
                        # night it was FIRST queued, and reconcile() escalates a signature
                        # to `critical` on its third strike. So a finding that went
                        # warn→critical kept its P3 row and its 72h starvation threshold
                        # while the alert stayed red (2026-07-21: three critical-derived
                        # rows sat at P3 — persistent_alert:8e08e46929dc07ef,
                        # persistent_alert:e2f24397a43d4962 and
                        # repeated_tool_failure:release_settings_audit.log:exit1).
                        # Re-checking severity here keeps priority assignment in its one
                        # owner instead of bolting a second escalation gate onto the
                        # dispatcher, which already owns starvation via STARVATION_HOURS.
                        f.remediation_ref = f"next_task:{task_id}"
                        want = _dreaming_priority(f.severity)
                        cur = prior.get("priority")
                        cur_int = cur if isinstance(cur, int) else None
                        open_row = str(prior.get("status") or "").strip().lower() not in (
                            TASK_STATES_FIXED | TASK_STATES_STALLED
                        )
                        # Only ever tighten, and only while the row is still open —
                        # re-queueing or demoting a finished task would resurrect it.
                        if open_row and cur_int is not None and want < cur_int:
                            prior["priority"] = want
                            prior["priority_note"] = (
                                f"dreaming: severity escalated to {f.severity} "
                                f"on {now.date().isoformat()} (was P{cur_int})"
                            )
                            actions.append(
                                {
                                    "signature": f.signature,
                                    "action": "reprioritized",
                                    "task_id": task_id,
                                    "from_priority": cur_int,
                                    "to_priority": want,
                                }
                            )
                        continue
                    task: dict[str, Any] = {
                        "id": task_id,
                        "title": f"[dreaming] {f.signature}",
                        "description": (
                            f"{f.proposal or f.signature}\n\n"
                            f"— dreaming 連續 {f.occurrences} 晚偵測到此模式（首見 {f.first_seen}）。\n"
                            f"證據：{'; '.join(f.evidence) if f.evidence else '(無)'}\n"
                            f"治理檔（error_log / rules / knowledge.json）仍是 propose-only："
                            f"接手的 agent 判斷後決定是否改，dreaming 不自動改。\n\n"
                            f"{dreaming_revalidate.REVALIDATION_INSTRUCTION}"
                        ),
                        "task_type": f.task_type,
                        "priority": _dreaming_priority(f.severity),
                        "status": "pending",
                        "source": "dreaming",
                        "created_at": now.isoformat(),
                        "dreaming": {
                            "signature": f.signature,
                            "pattern_type": f.pattern_type,
                            "occurrences": f.occurrences,
                            "governance_target": f.governance_target,
                        },
                    }
                    if f.subject_task_id:
                        # Explicit successor edge — without it the next run cannot
                        # see that this failure already has a fix queued.
                        task["follows_up_on"] = f.subject_task_id
                    tasks.append(task)
                    existing[task_id] = task
                    f.remediation_ref = f"next_task:{task_id}"
                    actions.append({"signature": f.signature, "action": "queued", "task_id": task_id})
                if actions:
                    write_tasks_to_handle(fh, tasks)
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except (OSError, ValueError) as exc:
        warn("dreaming", "queue write failed; findings stay propose-only", err=str(exc))
        return []
    return actions


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(
    storage_dir: str = "storage",
    *,
    dry_run: bool = False,
    # Default ON since 2026-07-12. It was off, and the `volpred ops dreaming-run`
    # entry point the nightly cron uses did not forward the flag at all — so the one
    # path that runs every night had no way to reach the actuator, and fifteen nights
    # of findings went nowhere. A default that every caller must remember to override
    # is how a loop stays open. What this enables writes tasks, never governance files.
    apply_auto: bool = True,
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

    # Read the queue back AFTER dispatch so the report describes the queue as it now
    # stands. Runs on dry runs too — it is read-only, and a dry run that cannot say
    # whether last night's tasks landed is exactly the blind spot being closed here.
    annotate_task_states(findings, storage_dir)

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
        # 寄信閘門 = 「有人得動手嗎」，不是「有新東西嗎」（見 needs_human_attention）。
        # 靜默不等於黑洞：報告照寫、decision log 照記，dashboard / ops_snapshot 讀得到，
        # 而且 skip 的理由會印在 cron log 上。
        if escalations or report["counts"]["actionable_new"]:
            try:
                send_dreaming_email(report, current, storage_dir)
                print("[dreaming] email sent to boss")
            except Exception as exc:
                warn("dreaming", "dreaming email failed; report still written", err=str(exc))
        else:
            print(
                "[dreaming] email skipped — nothing needs a human "
                f"(machine_handled={report['counts']['machine_handled']}, "
                f"quiescent={report['counts']['quiescent']}, "
                f"new={report['counts']['new']}); report still written"
            )

    return 0  # always 0 — reporting surface, fail-open


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Dreaming review — loop-engineering slow loop")
    parser.add_argument("--storage-dir", default="storage")
    parser.add_argument("--dry-run", action="store_true", help="Detect + write report only; no email/dispatch")
    parser.add_argument(
        "--no-apply-auto", dest="apply_auto", action="store_false",
        help="Detect and report, but do not queue findings as tasks (they then go nowhere)",
    )
    args = parser.parse_args()
    return main(storage_dir=args.storage_dir, dry_run=args.dry_run, apply_auto=args.apply_auto)


if __name__ == "__main__":
    sys.exit(_cli())
