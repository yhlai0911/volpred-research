"""Tests for `scripts/dreaming_review.py` — the loop-engineering slow loop.

Covers each detector, baseline diff, three-strike escalation, the auto-vs-
propose compliance boundary (governance findings must be propose-only and the
job must never write governance files), and always-exit-0.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import dreaming_review as dr  # noqa: E402

NOW = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)


def _storage(tmp_path: Path) -> Path:
    s = tmp_path / "storage"
    (s / "logs" / "cron").mkdir(parents=True)
    (s / "ops").mkdir(parents=True)
    return s


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def _cron_log(storage: Path, name: str, code: int, n: int) -> None:
    lines = [
        f"=== [{name}] exit {code} at {(NOW - timedelta(days=i)).strftime('%Y-%m-%d %H:%M:%S')} CST ==="
        for i in range(n)
    ]
    (storage / "logs" / "cron" / f"{name}.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------
def test_detect_repeated_tool_failures(tmp_path):
    storage = _storage(tmp_path)
    _cron_log(storage, "myjob", 1, 6)
    snap = dr.loop_health_snapshot(str(storage), now=NOW)
    findings = dr.detect_repeated_tool_failures(str(storage), snap, NOW)
    assert any(f.pattern_type == "repeated_tool_failure" for f in findings)
    f = findings[0]
    assert f.severity == "warn"  # critical earned via three-strike, not first sight
    assert f.remediation == "propose_only"
    assert f.governance_target == "docs/error_log.md"


def test_detect_stale_knowledge_high_severity(tmp_path):
    storage = _storage(tmp_path)
    _write(
        storage / "content_correction_report.json",
        {"flagged_articles": [{"id": "mile_x", "max_severity": "HIGH"}]},
    )
    findings = dr.detect_stale_knowledge(str(storage), {}, NOW)
    assert len(findings) == 1
    assert findings[0].signature == "stale_knowledge:mile_x"
    assert findings[0].governance_target == "storage/memory/knowledge.json"
    assert findings[0].remediation == "propose_only"


def test_detect_stale_knowledge_skips_broad_review_false_positives(tmp_path):
    """A comprehensive survey keyword-matches dozens of correction fingerprints
    without repeating any specific reversed claim — that is a keyword-overlap
    false positive (boss email-12139: similarity must be semantic, not keyword).
    Broad-review articles (matched_keywords >= floor) must be skipped; a specific
    low-keyword match is still flagged."""
    storage = _storage(tmp_path)
    _write(
        storage / "content_correction_report.json",
        {
            "flagged_articles": [
                {"article_id": "mile_survey", "max_severity": "HIGH",
                 "matched_keywords": [f"kw{i}" for i in range(30)]},  # broad review
                {"article_id": "mile_specific", "max_severity": "HIGH",
                 "matched_keywords": ["VaR", "reversed"]},  # specific claim
            ]
        },
    )
    findings = dr.detect_stale_knowledge(str(storage), {}, NOW)
    sigs = {f.signature for f in findings}
    assert "stale_knowledge:mile_specific" in sigs
    assert "stale_knowledge:mile_survey" not in sigs  # broad-review false positive skipped


def test_detect_missing_retry_strategy_flags_orphaned_failure(tmp_path):
    storage = _storage(tmp_path)
    _write(
        storage / "next_tasks.json",
        [
            # orphaned: failed, no controlled block, no follow-up
            {"id": "T1", "k_id": "K1", "status": "failed", "completed_at": _iso(2)},
            # parked: has controlled blocked_reason → not flagged
            {"id": "T2", "k_id": "K2", "status": "failed", "blocked_reason": "awaiting_external_data", "completed_at": _iso(2)},
            # has follow-up: K3 also has a succeeded sibling → not flagged
            {"id": "T3", "k_id": "K3", "status": "failed", "completed_at": _iso(2)},
            {"id": "T3b", "k_id": "K3", "status": "succeeded", "completed_at": _iso(1)},
        ],
    )
    findings = dr.detect_missing_retry_strategy(str(storage), {}, NOW)
    sigs = {f.signature for f in findings}
    assert "missing_retry_strategy:K1" in sigs
    assert "missing_retry_strategy:K2" not in sigs
    assert "missing_retry_strategy:K3" not in sigs
    assert findings[0].remediation == "auto_dispatch"  # low-risk derived state


def test_detect_missing_retry_strategy_honours_id_lineage(tmp_path):
    """K1679 (2026-07-13): a retried failure carrying no k_id was re-flagged 3 nights.

    Follow-ups are named off the parent id (`K1679-rev`, `k1025_v2`, `k628b`), and
    most tasks have no k_id at all — so k_id-only sibling matching never saw the retry.
    """
    storage = _storage(tmp_path)
    _write(
        storage / "next_tasks.json",
        [
            # the real incident: failed, no k_id, retried as <id>-rev / <id>-rev2
            {"id": "K1679", "status": "failed", "completed_at": _iso(2)},
            {"id": "K1679-rev", "status": "succeeded", "completed_at": _iso(1)},
            {"id": "K1679-rev2", "status": "succeeded", "completed_at": _iso(1)},
            # underscore + bare-letter retry conventions
            {"id": "k1025", "status": "failed", "completed_at": _iso(2)},
            {"id": "k1025_v2", "status": "succeeded", "completed_at": _iso(1)},
            {"id": "k628", "status": "failed", "completed_at": _iso(2)},
            {"id": "k628b", "status": "succeeded", "completed_at": _iso(1)},
            # genuinely orphaned: no descendant at all → must still be flagged
            {"id": "K999", "status": "failed", "completed_at": _iso(2)},
            # a numerically adjacent id is NOT a descendant of K999
            {"id": "K9991", "status": "succeeded", "completed_at": _iso(1)},
            # retry chain whose only descendant also failed → tail still surfaces
            {"id": "K777", "status": "failed", "completed_at": _iso(2)},
            {"id": "K777-rev", "status": "failed", "completed_at": _iso(1)},
        ],
    )
    sigs = {f.signature for f in dr.detect_missing_retry_strategy(str(storage), {}, NOW)}
    assert "missing_retry_strategy:K1679" not in sigs
    assert "missing_retry_strategy:k1025" not in sigs
    assert "missing_retry_strategy:k628" not in sigs
    assert "missing_retry_strategy:K999" in sigs  # no follow-up → still flagged
    assert "missing_retry_strategy:K777" in sigs  # retry failed too → chain still broken
    assert "missing_retry_strategy:K777-rev" in sigs


def test_detect_missing_retry_strategy_sees_its_own_remediation_task(tmp_path):
    """2026-07-14: dreaming re-flagged failures it had already queued a fix for.

    auto_dispatch names the remediation task `dreaming_<pattern>_<parent>` — parent
    in the SUFFIX — but lineage matching only accepted a parent PREFIX. So dreaming
    could not see its own fix, re-flagged the same failure nightly, and the
    three-strike counter false-escalated it to critical (fable0711 ×5). The fix is
    an explicit successor edge (`follows_up_on`), not a smarter string guess.
    """
    storage = _storage(tmp_path)
    _write(
        storage / "next_tasks.json",
        [
            {"id": "fable0711_ftd_e1", "status": "failed", "completed_at": _iso(2)},
            {
                "id": "dreaming_missing_retry_strategy_fable0711_ftd_e1",
                "status": "pending",
                "source": "dreaming",
                "follows_up_on": "fable0711_ftd_e1",
            },
            # a hand-written retry may declare the edge too — id need not resemble the parent
            {"id": "K1684", "status": "failed", "completed_at": _iso(2)},
            {"id": "rerun-of-the-gating-experiment", "status": "pending", "follows_up_on": "K1684"},
            # an edge from a task that ITSELF failed is not a fix → parent stays flagged
            {"id": "K555", "status": "failed", "completed_at": _iso(2)},
            {"id": "K555-retry", "status": "failed", "follows_up_on": "K555", "completed_at": _iso(1)},
        ],
    )
    sigs = {f.signature for f in dr.detect_missing_retry_strategy(str(storage), {}, NOW)}
    assert "missing_retry_strategy:fable0711_ftd_e1" not in sigs
    assert "missing_retry_strategy:K1684" not in sigs
    assert "missing_retry_strategy:K555" in sigs
    assert "missing_retry_strategy:K555-retry" in sigs


def test_auto_dispatch_records_successor_edge(tmp_path):
    """The remediation task must carry `follows_up_on`, or the loop above returns."""
    storage = _storage(tmp_path)
    _write(storage / "next_tasks.json", [])
    finding = dr.DreamFinding(
        pattern_type="missing_retry_strategy",
        signature="missing_retry_strategy:K1684",
        severity="warn",
        remediation="auto_dispatch",
        subject_task_id="K1684",
    )
    dr.apply_auto_dispatch([finding], str(storage), NOW)
    queued = json.loads((storage / "next_tasks.json").read_text(encoding="utf-8"))
    assert [t["follows_up_on"] for t in queued] == ["K1684"]


def test_detect_semantic_concentration_flags_high_rehash(tmp_path, monkeypatch):
    # High semantic rehash rate → finding (boss email-12139 semantic directive).
    monkeypatch.setattr(
        "volpred.ops.topic_similarity.semantic_concentration_report",
        lambda *a, **k: {
            "status": "concentrated", "sample": 20, "rehash_count": 8, "rehash_rate": 0.4,
            "near_twin_pairs": [{"title": "RECH-X 跨市場", "twin": "AI 波動率模型 RECH-X", "similarity": 0.77}],
        },
    )
    findings = dr.detect_semantic_concentration(str(tmp_path / "storage"), {}, NOW)
    assert len(findings) == 1
    assert findings[0].signature == "semantic_concentration:feed"
    assert findings[0].remediation == "propose_only"


def test_detect_semantic_concentration_fail_open(tmp_path, monkeypatch):
    # Embeddings down → no finding (never breaks the run).
    monkeypatch.setattr(
        "volpred.ops.topic_similarity.semantic_concentration_report",
        lambda *a, **k: {"status": "semantic_unavailable", "sample": 20},
    )
    assert dr.detect_semantic_concentration(str(tmp_path / "storage"), {}, NOW) == []


def test_detect_semantic_concentration_low_rate_no_finding(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "volpred.ops.topic_similarity.semantic_concentration_report",
        lambda *a, **k: {"status": "ok", "sample": 20, "rehash_rate": 0.1, "near_twin_pairs": []},
    )
    assert dr.detect_semantic_concentration(str(tmp_path / "storage"), {}, NOW) == []


def test_detect_loop_metric_regression(tmp_path):
    storage = _storage(tmp_path)
    snap = {
        "first_pass_success": {"status": "degrading", "first_pass_rate": 0.4},
        "task_outcome": {"status": "ok"},
        "correction_trend": {"status": "warn"},
    }
    findings = dr.detect_loop_metric_regression(str(storage), snap, NOW)
    sigs = {f.signature for f in findings}
    assert "loop_metric_regression:first_pass_success" in sigs
    assert "loop_metric_regression:correction_trend" in sigs
    assert "loop_metric_regression:task_outcome" not in sigs
    assert all(f.severity == "warn" for f in findings)  # critical via three-strike only


def _write_alert_dedup(storage: Path, alerts: dict) -> None:
    (storage / "ops" / "alert_dedup.json").write_text(
        json.dumps({"alerts": alerts, "updated_at": NOW.isoformat()}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_detect_persistent_alerts_flags_recurring_alert_condition(tmp_path):
    """A recurring single-scope alert is surfaced without inventing causality."""
    storage = _storage(tmp_path)
    _write_alert_dedup(
        storage,
        {
            "abc123def456" + "0" * 52: {
                "title": "Supabase sync queue stuck",
                "send_count": 26,
                "first_sent_at": _iso(60),
                "last_sent_at": _iso(0.5),  # last fire 12h ago — still active
            }
        },
    )
    findings = dr.detect_persistent_alerts(str(storage), {}, NOW)
    assert len(findings) == 1
    f = findings[0]
    assert f.pattern_type == "persistent_alert"
    assert f.severity == "warn"  # critical via three-strike only
    assert f.remediation == "propose_only"
    assert f.governance_target == "docs/error_log.md"
    assert "26" in f.evidence[0]  # send_count surfaced
    assert "key alone does not prove one root cause" in f.proposal


def test_detect_persistent_alerts_skips_host_cron_umbrella_owned_by_error_recurrence(
    tmp_path,
):
    """Host-cron title spans different jobs; per-job recurrence owns the signal."""
    storage = _storage(tmp_path)
    alert_key = (
        "a4a7ca551f8626b22c4d5db9ac9d8bd"
        "0f08d40bf9ce96a5214f73ee575ada4c0"
    )
    _write_alert_dedup(
        storage,
        {
            alert_key: {
                "title": "Host cron failure detected",
                "send_count": 33,
                "first_sent_at": _iso(84.2),
                "last_sent_at": _iso(0.5),
            }
        },
    )

    findings = dr.detect_persistent_alerts(str(storage), {}, NOW)
    assert findings == []

    # The old false aggregate signature resolves naturally on the next run;
    # no historical state file needs a manual patch.
    signature = f"persistent_alert:{alert_key[:16]}"
    baseline = {
        signature: {
            "strike_count": 3,
            "pattern_type": "persistent_alert",
            "first_seen": _iso(3),
            "last_seen": _iso(1),
            "activity_marker": _iso(0.5),
        }
    }
    _, resolved, _ = dr.reconcile(findings, baseline, NOW)
    assert resolved == [signature]
    assert signature not in baseline


def test_host_cron_recurrence_remains_job_scoped(tmp_path):
    """The delegated owner keeps distinct cron jobs in distinct signatures."""
    snapshot = {
        "error_recurrence": {
            "top_recurring": [
                {
                    "signature": "token_report.log:exit1",
                    "known": False,
                    "recovered": False,
                    "count": 5,
                    "first_seen": _iso(5),
                    "last_seen": _iso(0.1),
                    "span_days": 4.9,
                },
                {
                    "signature": "git_push_backup.log:exit1",
                    "known": False,
                    "recovered": False,
                    "count": 1,
                    "first_seen": _iso(0.2),
                    "last_seen": _iso(0.1),
                    "span_days": 0.1,
                },
            ]
        }
    }

    findings = dr.detect_repeated_tool_failures(
        str(tmp_path / "storage"), snapshot, NOW
    )
    assert [f.signature for f in findings] == [
        "repeated_tool_failure:token_report.log:exit1"
    ]


def test_detect_persistent_alerts_skips_recovered_past_incident(tmp_path):
    """Last fire >48h ago = recovered/past incident, no finding."""
    storage = _storage(tmp_path)
    _write_alert_dedup(
        storage,
        {
            "k" * 64: {
                "title": "old spike now quiet",
                "send_count": 10,
                "first_sent_at": _iso(30),
                "last_sent_at": _iso(3),  # 3d ago — beyond 48h recovered cutoff
            }
        },
    )
    findings = dr.detect_persistent_alerts(str(storage), {}, NOW)
    assert findings == []


def test_detect_persistent_alerts_skips_short_burst(tmp_path):
    """5 fires in one hour ≠ multi-day persistence — needs M-day span."""
    storage = _storage(tmp_path)
    _write_alert_dedup(
        storage,
        {
            "b" * 64: {
                "title": "transient burst",
                "send_count": 5,
                "first_sent_at": _iso(0.04),  # ≈1h ago
                "last_sent_at": _iso(0.0),
            }
        },
    )
    findings = dr.detect_persistent_alerts(str(storage), {}, NOW)
    assert findings == []


def test_detect_persistent_alerts_skips_low_send_count(tmp_path):
    """send_count below threshold = not yet recurring, no finding (filters
    out one-off ACK / Re: communication noise even if span happened to be wide)."""
    storage = _storage(tmp_path)
    _write_alert_dedup(
        storage,
        {
            "c" * 64: {
                "title": "[ACK] Re: ... one-off reply",
                "send_count": 2,
                "first_sent_at": _iso(5),
                "last_sent_at": _iso(0.1),
            }
        },
    )
    findings = dr.detect_persistent_alerts(str(storage), {}, NOW)
    assert findings == []


def test_detect_persistent_alerts_fail_open_missing_file(tmp_path):
    """No alert_dedup.json = fresh storage; detector returns [] not raises."""
    storage = _storage(tmp_path)
    # no alert_dedup.json written
    findings = dr.detect_persistent_alerts(str(storage), {}, NOW)
    assert findings == []


# ---------------------------------------------------------------------------
# Baseline reconciliation + three-strike
# ---------------------------------------------------------------------------
def test_reconcile_new_then_persisting(tmp_path):
    f1 = dr.DreamFinding(pattern_type="x", signature="sig:a", severity="warn")
    baseline: dict = {}
    new, resolved, esc = dr.reconcile([f1], baseline, NOW)
    assert [f.signature for f in new] == ["sig:a"]
    assert baseline["sig:a"]["strike_count"] == 1
    # second run: same signature → not new, strike increments
    f1b = dr.DreamFinding(pattern_type="x", signature="sig:a", severity="warn")
    new2, _, _ = dr.reconcile([f1b], baseline, NOW)
    assert new2 == []
    assert baseline["sig:a"]["strike_count"] == 2


def test_three_strike_escalates_to_critical(tmp_path):
    baseline: dict = {}
    esc_final = []
    for _ in range(dr.THREE_STRIKE):
        f = dr.DreamFinding(pattern_type="x", signature="sig:persist", severity="warn")
        _, _, esc = dr.reconcile([f], baseline, NOW)
        esc_final = esc
    assert any(f.signature == "sig:persist" and f.severity == "critical" for f in esc_final)
    assert baseline["sig:persist"]["strike_count"] == dr.THREE_STRIKE


def test_quiescent_activity_marker_holds_strike_no_escalation(tmp_path):
    """Regression (boss email-12688): a persistent_alert that fired a burst then
    went quiet still appears across daily runs inside the 48h auto-clear window,
    but its last_sent_at (activity_marker) is frozen. It must NOT accumulate
    strikes to critical — a decaying alert is resolving itself, not persisting."""
    baseline: dict = {}
    esc_final = []
    frozen_marker = "2026-07-05T12:00:18+00:00"
    # Same frozen marker across THREE_STRIKE+1 daily runs (alert stopped firing).
    for _ in range(dr.THREE_STRIKE + 1):
        f = dr.DreamFinding(
            pattern_type="persistent_alert",
            signature="persistent_alert:quiet",
            severity="warn",
            activity_marker=frozen_marker,
        )
        _, _, esc = dr.reconcile([f], baseline, NOW)
        esc_final = esc
    assert esc_final == []  # never escalates while quiescent
    assert baseline["persistent_alert:quiet"]["strike_count"] == 1  # held at first sight


def test_advancing_activity_marker_still_escalates(tmp_path):
    """An alert that keeps firing (marker advances each run) is genuinely
    persistent and MUST still reach three-strike critical."""
    baseline: dict = {}
    esc_final = []
    for i in range(dr.THREE_STRIKE):
        f = dr.DreamFinding(
            pattern_type="persistent_alert",
            signature="persistent_alert:live",
            severity="warn",
            activity_marker=f"2026-07-0{i + 1}T00:00:00+00:00",  # advances each run
        )
        _, _, esc = dr.reconcile([f], baseline, NOW)
        esc_final = esc
    assert any(f.signature == "persistent_alert:live" and f.severity == "critical" for f in esc_final)
    assert baseline["persistent_alert:live"]["strike_count"] == dr.THREE_STRIKE


def test_legacy_baseline_entry_no_marker_stays_conservative(tmp_path):
    """A pre-existing baseline entry (written before activity_marker existed) at
    strike>=THREE_STRIKE must not false-escalate on the first run after deploy;
    the missing marker is treated as 'advance unknown' → quiescent → hold."""
    baseline = {
        "persistent_alert:legacy": {
            "strike_count": dr.THREE_STRIKE,
            "pattern_type": "persistent_alert",
            "first_seen": "2026-07-01T00:00:00+00:00",
            "last_seen": "2026-07-05T22:00:00+00:00",
            # NOTE: no "activity_marker" key — legacy schema
        }
    }
    f = dr.DreamFinding(
        pattern_type="persistent_alert",
        signature="persistent_alert:legacy",
        severity="warn",
        activity_marker="2026-07-05T12:00:18+00:00",
    )
    _, _, esc = dr.reconcile([f], baseline, NOW)
    assert esc == []  # no false escalation on the migration boundary
    assert baseline["persistent_alert:legacy"]["activity_marker"] == f.activity_marker


def test_reconcile_resolved_when_absent(tmp_path):
    baseline = {"sig:gone": {"strike_count": 2, "pattern_type": "x"}}
    new, resolved, esc = dr.reconcile([], baseline, NOW)
    assert resolved == ["sig:gone"]
    assert "sig:gone" not in baseline  # removed


# ---------------------------------------------------------------------------
# Compliance: governance propose-only + no governance writes
# ---------------------------------------------------------------------------
def test_governance_findings_are_propose_only(tmp_path):
    storage = _storage(tmp_path)
    _cron_log(storage, "myjob", 1, 6)
    _write(
        storage / "content_correction_report.json",
        {"flagged_articles": [{"id": "mile_x", "max_severity": "HIGH"}]},
    )
    snap = dr.loop_health_snapshot(str(storage), now=NOW)
    findings = []
    for det in dr.DETECTORS:
        findings.extend(det(str(storage), snap, NOW))
    governance = [f for f in findings if f.governance_target]
    assert governance, "expected at least one governance finding in this fixture"
    for f in governance:
        assert f.remediation == "propose_only", f"{f.signature} must be propose-only"


def test_main_never_writes_governance_files(tmp_path, monkeypatch):
    storage = _storage(tmp_path)
    _cron_log(storage, "myjob", 1, 6)
    _write(
        storage / "content_correction_report.json",
        {"flagged_articles": [{"id": "mile_x", "max_severity": "HIGH"}]},
    )
    # Tripwire: any write to a governance path raises.
    import builtins

    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        p = str(file)
        if any(g in p for g in ("error_log.md", "/.claude/rules/", "CLAUDE.md", "knowledge.json")):
            if any(m in mode for m in ("w", "a", "x", "+")):
                raise AssertionError(f"dreaming wrote a governance file: {p} ({mode})")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr("volpred.ops.alerts.send_alert", lambda *a, **k: {"sent": True})
    rc = dr.main(storage_dir=str(storage), dry_run=False, now=NOW)
    assert rc == 0


# ---------------------------------------------------------------------------
# main(): always exit 0, dry_run side-effect boundary
# ---------------------------------------------------------------------------
def test_main_dry_run_writes_report_not_baseline(tmp_path, monkeypatch):
    storage = _storage(tmp_path)
    _cron_log(storage, "myjob", 1, 6)
    sent = []
    monkeypatch.setattr("volpred.ops.alerts.send_alert", lambda *a, **k: sent.append(1) or {"sent": True})
    rc = dr.main(storage_dir=str(storage), dry_run=True, now=NOW)
    assert rc == 0
    assert (storage / "ops" / "dreaming" / "2026-06-29.json").exists()
    assert not (storage / "ops" / "dreaming" / "baseline.json").exists()
    assert not (storage / "ops" / "autonomous_decisions.jsonl").exists()
    assert sent == []  # no email on dry-run


def test_main_non_dry_writes_baseline_and_emails(tmp_path, monkeypatch):
    storage = _storage(tmp_path)
    _cron_log(storage, "myjob", 1, 6)
    sent = []
    monkeypatch.setattr("volpred.ops.alerts.send_alert", lambda *a, **k: sent.append(k or a) or {"sent": True})
    rc = dr.main(storage_dir=str(storage), dry_run=False, now=NOW)
    assert rc == 0
    assert (storage / "ops" / "dreaming" / "baseline.json").exists()
    assert (storage / "ops" / "autonomous_decisions.jsonl").exists()
    assert len(sent) == 1  # new findings → one boss email


def test_dispatch_does_not_go_to_the_receipts_trail(tmp_path, monkeypatch):
    """Both of these tests used to assert the contract that broke dreaming.

    This one pinned the `create_task` call shape. `create_task` writes a TaskRecord
    under storage/ops/tasks/, which CLAUDE.md is explicit about: receipts and audit
    trail, never a pending queue. The hourly dispatcher reads next_tasks.json. So the
    call shape was correct and the destination was wrong, and a green test said so
    every run. Assert the destination.
    """
    called = []
    monkeypatch.setattr(
        "volpred.ops.local_control_plane.create_task",
        lambda **k: called.append(k) or {"id": "task_abc123"},
    )
    storage = _storage(tmp_path)
    f = dr.DreamFinding(
        pattern_type="missing_retry_strategy",
        signature="missing_retry_strategy:K9",
        severity="critical",
        remediation="auto_dispatch",
    )
    actions = dr.apply_auto_dispatch([f], str(storage), NOW)

    assert called == [], "the receipts trail is not a queue; nothing dispatches from it"
    assert actions and actions[0]["task_id"] == "dreaming_missing_retry_strategy_k9"
    assert f.remediation_ref == "next_task:dreaming_missing_retry_strategy_k9"
    assert "missing_retry_strategy:K9" in (storage / "next_tasks.json").read_text(encoding="utf-8")


def test_a_warn_level_orphaned_failure_still_gets_queued(tmp_path):
    """The other stale contract: dispatch only on `critical`.

    Every `missing_retry_strategy` finding the detector emits is severity=warn, and
    escalation to critical needs a three-strike that today's report shows firing zero
    times. Critical-only therefore made auto_dispatch unreachable in practice — the
    remediation existed, was tested, and could never run. A warn-level orphaned
    failure is still an experiment that failed and that nobody retried; queuing a
    platform_ops task to look at it is the whole point of detecting it.

    The conservatism that matters is kept elsewhere and still tested: governance files
    are never rewritten, and a propose_only finding waits three nights before it
    becomes work.
    """
    storage = _storage(tmp_path)
    f = dr.DreamFinding(
        pattern_type="missing_retry_strategy",
        signature="missing_retry_strategy:K9",
        severity="warn",
        remediation="auto_dispatch",
    )
    actions = dr.apply_auto_dispatch([f], str(storage), NOW)

    assert [a["action"] for a in actions] == ["queued"]
    queued = json.loads((storage / "next_tasks.json").read_text(encoding="utf-8"))
    assert queued[0]["priority"] == 3, "warn is P3; critical would be P2"


def test_memory_governance_only_flags_unowned_recurring_processes(tmp_path, monkeypatch):
    """Coverage is an audited owner, not a skill-name substring coincidence.

    This locks the 2026-07-16 regression: five already-codified workflows were
    re-queued nightly, while `auto-memory` (an architecture noun) was mistaken for
    a recurring process solely because the old keyword list contained `auto`.
    """
    storage = _storage(tmp_path)
    project = tmp_path / "claude-project"
    memory = project / "memory"
    memory.mkdir(parents=True)
    monkeypatch.setattr(dr, "detect_claude_projects_dir", lambda: project)

    owner = tmp_path / ".claude" / "skills" / "owned" / "SKILL.md"
    owner.parent.mkdir(parents=True)
    owner.write_text("# owner\n\nCross-link: crosslinked_process.md\n", encoding="utf-8")

    (memory / "MEMORY.md").write_text(
        "\n".join(
            [
                "- [architecture.md](architecture.md) — shared auto-memory invariant",
                "- [owned.md](owned.md) — 每日 workflow",
                "- [crosslinked_process.md](crosslinked_process.md) — 每週巡檢",
                "- [invalid_owner.md](invalid_owner.md) — 每月流程",
                "- [unowned.md](unowned.md) — 每日排程",
            ]
        ),
        encoding="utf-8",
    )
    (memory / "architecture.md").write_text("architecture only", encoding="utf-8")
    (memory / "owned.md").write_text(
        "---\nprocess_owner: .claude/skills/owned/SKILL.md\n---\n",
        encoding="utf-8",
    )
    (memory / "crosslinked_process.md").write_text("recurring process", encoding="utf-8")
    (memory / "invalid_owner.md").write_text(
        "---\nprocess_owner: .claude/skills/missing/SKILL.md\n---\n",
        encoding="utf-8",
    )
    (memory / "unowned.md").write_text("recurring process", encoding="utf-8")

    findings = dr.detect_memory_governance(str(storage), {}, NOW)

    gaps = [f for f in findings if f.pattern_type == "memory_skill_gap"]
    evidence = "\n".join(item for gap in gaps for item in gap.evidence)
    signatures = {gap.signature for gap in gaps}
    assert signatures == {
        "memory_skill_gap:invalid_owner",
        "memory_skill_gap:unowned",
    }, "each process needs its own durable task identity"
    assert "invalid_owner.md" in evidence, "a stale owner path must not suppress the gap"
    assert "unowned.md" in evidence
    assert "architecture.md" not in evidence, "`auto-memory` is not a cadence signal"
    assert "[owned.md]" not in evidence
    assert "[crosslinked_process.md]" not in evidence


def test_main_exits_zero_even_when_all_detectors_fail(tmp_path, monkeypatch):
    storage = _storage(tmp_path)

    def _boom(*a, **k):
        raise RuntimeError("boom")

    # Patch the DETECTORS tuple itself (main iterates it) so every detector raises.
    monkeypatch.setattr(dr, "DETECTORS", tuple(_boom for _ in dr.DETECTORS))
    rc = dr.main(storage_dir=str(storage), dry_run=True, now=NOW)
    assert rc == 0


# ---------------------------------------------------------------------------
# The actuator (2026-07-12, email-12126: the owner asked what dreaming is actually
# doing and whether it is optimising anything).
#
# The honest answer was "nothing, and no". Dreaming detected fine, and then its
# actuator was disconnected at both ends: `--apply-auto` defaulted off and the
# `volpred ops dreaming-run` entry point the nightly cron uses never forwarded the
# flag; behind the flag, apply_auto_dispatch wrote a TaskRecord under
# storage/ops/tasks/ (the receipts trail) while the dispatcher picks work out of
# next_tasks.json. So findings could not have become work even fully enabled.
# `memory_skill_gap` was re-proposed on fifteen consecutive nights, actioned zero
# times, and emailed a WARN each morning to say so.
# ---------------------------------------------------------------------------
def _finding(sig: str, *, remediation: str, occurrences: int = 1, severity: str = "warn"):
    return dr.DreamFinding(
        pattern_type="test",
        signature=sig,
        severity=severity,
        evidence=["e1"],
        remediation=remediation,
        occurrences=occurrences,
    )


def _queued_ids(storage: Path) -> list[str]:
    raw = (storage / "next_tasks.json").read_text(encoding="utf-8")
    return [t["id"] for t in json.loads(raw)]


def test_findings_land_in_the_queue_the_dispatcher_actually_reads(tmp_path):
    """The bug in one line: the dispatcher reads next_tasks.json, and dreaming wrote
    somewhere else. A finding that cannot reach the queue cannot become work."""
    storage = _storage(tmp_path)
    actions = dr.apply_auto_dispatch(
        [_finding("missing_retry:K1679", remediation="auto_dispatch")], str(storage), NOW,
    )

    assert [a["action"] for a in actions] == ["queued"]
    queued = json.loads((storage / "next_tasks.json").read_text(encoding="utf-8"))
    assert len(queued) == 1
    assert queued[0]["status"] == "pending", "must be claimable by the hourly dispatcher"
    assert queued[0]["source"] == "dreaming"
    assert queued[0]["task_type"] == "platform_ops"


def test_a_proposal_nobody_read_for_three_nights_becomes_work(tmp_path):
    """`memory_skill_gap` sat at occurrences=15. Persistence is the signal, the same
    rule PHASE-Z uses for a foreign path nobody comes back for."""
    storage = _storage(tmp_path)
    dr.apply_auto_dispatch(
        [
            _finding("memory_skill_gap:uncodified", remediation="propose_only", occurrences=15),
            _finding("seen_once_tonight", remediation="propose_only", occurrences=1),
        ],
        str(storage), NOW,
    )

    ids = _queued_ids(storage)
    assert any("memory_skill_gap" in i for i in ids), "15 nights unread is a backlog item"
    assert not any("seen_once" in i for i in ids), "one sighting is still just a proposal"


def test_queueing_the_same_signature_every_night_does_not_pile_up(tmp_path):
    """Dreaming re-derives its signatures nightly. Without this, one finding becomes
    thirty tasks in a month."""
    storage = _storage(tmp_path)
    f = lambda: _finding("missing_retry:K1679", remediation="auto_dispatch")  # noqa: E731
    dr.apply_auto_dispatch([f()], str(storage), NOW)
    again = dr.apply_auto_dispatch([f()], str(storage), NOW)

    assert again == [], "already queued: say nothing, add nothing"
    assert len(_queued_ids(storage)) == 1


def test_queueing_never_touches_the_real_repo_queue(tmp_path):
    """apply_auto_dispatch is now on by default, so every test that drives main()
    reaches it. The obvious reuse, task_pool_claim._locked_load(), hardcodes the
    production next_tasks.json, which would make this suite write the real queue."""
    storage = _storage(tmp_path)
    dr.apply_auto_dispatch(
        [_finding("sig:x", remediation="auto_dispatch")], str(storage), NOW,
    )
    assert (storage / "next_tasks.json").exists(), "the queue under storage_dir, and only it"

    real = Path(__file__).resolve().parents[1] / "storage" / "next_tasks.json"
    assert "sig:x" not in real.read_text(encoding="utf-8"), "must never write the live queue"


# ---------------------------------------------------------------------------
# detect_orphaned_experiments — research that ran and was then silently dropped
# ---------------------------------------------------------------------------
# Regression cover for the 2026-07-12 owner escalation (Telegram: 「做了研究結果
# 一直變孤兒浪費」). Each test below is one of the conditions that let a finished
# experiment sit unconsumed: no downstream artifact, an owner-less "succeeded"
# task, a producer that died before closing out.
def _experiment(tmp_path: Path, name: str, *, age_days: float, results: bool = True) -> Path:
    d = tmp_path / "experiments" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "README.md").write_text("x", encoding="utf-8")
    if results:
        r = d / f"{name}_results.json"
        r.write_text('{"verdict": "NULL"}', encoding="utf-8")
        mtime = (NOW - timedelta(days=age_days)).timestamp()
        import os

        os.utime(r, (mtime, mtime))
    return d


def _consumers(storage: Path, *, knowledge="[]", feed="[]", tasks=None) -> None:
    _write(storage / "memory" / "knowledge.json", json.loads(knowledge))
    _write(storage / "reports" / "feed.json", json.loads(feed))
    _write(storage / "next_tasks.json", tasks if tasks is not None else [])


def test_orphaned_experiment_with_no_consumer_is_flagged(tmp_path):
    storage = _storage(tmp_path)
    _consumers(storage)
    _experiment(tmp_path, "k1630", age_days=7)
    findings = dr.detect_orphaned_experiments(str(storage), {}, NOW)
    assert [f.signature for f in findings] == ["orphaned_experiment:k1630"]
    f = findings[0]
    # Queued the same night, as a research closure — not a three-strike proposal
    # and not a platform_ops chore.
    assert f.remediation == "auto_dispatch"
    assert f.severity == "warn"
    assert f.task_type == "experiment"


def test_orphaned_experiment_consumed_by_knowledge_is_not_flagged(tmp_path):
    storage = _storage(tmp_path)
    _consumers(storage, knowledge='[{"experiment_id": "K1630", "verdict": "PASS"}]')
    _experiment(tmp_path, "k1630", age_days=7)
    assert dr.detect_orphaned_experiments(str(storage), {}, NOW) == []


def test_orphaned_experiment_with_open_task_is_owned(tmp_path):
    storage = _storage(tmp_path)
    _consumers(storage, tasks=[{"id": "t1", "status": "pending", "title": "close K1630"}])
    _experiment(tmp_path, "k1630", age_days=7)
    assert dr.detect_orphaned_experiments(str(storage), {}, NOW) == []


def test_succeeded_task_without_knowledge_is_still_an_orphan(tmp_path):
    """The exact failure mode: a task claimed closure but left nothing behind."""
    storage = _storage(tmp_path)
    _consumers(storage, tasks=[{"id": "t1", "status": "succeeded", "title": "run K1630"}])
    _experiment(tmp_path, "k1630", age_days=7)
    assert [f.signature for f in dr.detect_orphaned_experiments(str(storage), {}, NOW)] == [
        "orphaned_experiment:k1630"
    ]


def test_just_finished_experiment_is_left_to_settle(tmp_path):
    """A producing fire may still be closing out; don't race it."""
    storage = _storage(tmp_path)
    _consumers(storage)
    _experiment(tmp_path, "k1630", age_days=0.1)  # ~2.4h < 6h settle window
    assert dr.detect_orphaned_experiments(str(storage), {}, NOW) == []


def test_experiment_without_results_is_not_an_orphan(tmp_path):
    storage = _storage(tmp_path)
    _consumers(storage)
    _experiment(tmp_path, "k1630", age_days=7, results=False)
    assert dr.detect_orphaned_experiments(str(storage), {}, NOW) == []


def test_non_k_evidence_dirs_are_ignored(tmp_path):
    """trending_* / event_article_* dirs are article evidence, not K-experiments."""
    storage = _storage(tmp_path)
    _consumers(storage)
    _experiment(tmp_path, "trending_mag7_jun2026_vol", age_days=7)
    _experiment(tmp_path, "event_article_nfp_2026_07_03_t1", age_days=7)
    assert dr.detect_orphaned_experiments(str(storage), {}, NOW) == []


def test_orphan_findings_are_capped_but_backlog_is_disclosed(tmp_path):
    """No silent caps: the full backlog count ships in the evidence."""
    storage = _storage(tmp_path)
    _consumers(storage)
    for i in range(8):
        _experiment(tmp_path, f"k17{i:02d}", age_days=2 + i)
    findings = dr.detect_orphaned_experiments(str(storage), {}, NOW)
    assert len(findings) == dr.ORPHAN_EXPERIMENT_MAX_FINDINGS
    # freshest first — closure is cheapest while the context is warm
    assert findings[0].signature == "orphaned_experiment:k1700"
    assert any("orphan backlog this run: 8" in e for e in findings[0].evidence)


def test_aged_out_orphans_are_counted_not_queued(tmp_path):
    storage = _storage(tmp_path)
    _consumers(storage)
    _experiment(tmp_path, "k1400", age_days=90)
    findings = dr.detect_orphaned_experiments(str(storage), {}, NOW)
    assert findings == []


def test_orphan_finding_queues_as_experiment_task_type(tmp_path):
    """The queue writer must honour DreamFinding.task_type (default stays platform_ops)."""
    storage = _storage(tmp_path)
    _write(storage / "next_tasks.json", [])
    orphan = dr.DreamFinding(
        pattern_type="orphaned_experiment",
        signature="orphaned_experiment:k1630",
        severity="warn",
        remediation="auto_dispatch",
        task_type="experiment",
    )
    chore = dr.DreamFinding(
        pattern_type="missing_retry_strategy",
        signature="missing_retry_strategy:k9",
        severity="warn",
        remediation="auto_dispatch",
    )
    dr.apply_auto_dispatch([orphan, chore], str(storage), NOW)
    queued = {t["id"]: t for t in json.loads((storage / "next_tasks.json").read_text())}
    types = {t["title"]: t["task_type"] for t in queued.values()}
    assert types["[dreaming] orphaned_experiment:k1630"] == "experiment"
    assert types["[dreaming] missing_retry_strategy:k9"] == "platform_ops"


# ---------------------------------------------------------------------------
# Email 建議行動：嚴重度 → level + 行動，由 DREAMING_SEVERITY_TIERS 這張表決定。
# 2026-07-18 重構後的迴歸鎖：level 與文案必須來自同一筆 tier，不再兩處各自 if。
# ---------------------------------------------------------------------------
def _email_report(new: int, escalations: int) -> dict:
    return {
        "counts": {"findings": new, "new": new, "resolved": 0, "escalations": escalations},
        "findings": [
            {
                "severity": "critical" if escalations else "warn",
                "pattern_type": "repeated_tool_failure",
                "signature": "host_cron_fail:myjob",
                "occurrences": 3 if escalations else 1,
                "governance_target": None,
            }
        ][:new],
        "loop_health": {"overall": "degrading" if escalations else "ok"},
    }


def _capture_email(monkeypatch, report):
    sent = {}

    def _fake(level, title, body, **kw):
        sent.update(level=level, title=title, body=body)
        return {"sent": True}

    monkeypatch.setattr("volpred.ops.alerts.send_alert", _fake)
    dr.send_dreaming_email(report, NOW, storage_dir="/tmp")
    return sent


def test_email_with_escalation_routes_to_three_strike(monkeypatch):
    sent = _capture_email(monkeypatch, _email_report(new=1, escalations=1))
    assert sent["level"] == "critical"
    assert "refactor_plan" in sent["body"]
    assert "Three-Strike" in sent["body"]
    assert "不需要重構" not in sent["body"]


def test_email_without_escalation_explicitly_declines_refactor(monkeypatch):
    sent = _capture_email(monkeypatch, _email_report(new=1, escalations=0))
    assert sent["level"] == "warn"
    assert "不需要重構" in sent["body"]
    # 只有「不啟動 refactor_plan」的否定句，不得出現「開 refactor_plan」的指示。
    assert "docs/refactor_plan_" not in sent["body"]
    assert "不啟動 Three-Strike / refactor_plan" in sent["body"]


def test_email_quiet_run_is_info_and_still_declines_refactor(monkeypatch):
    sent = _capture_email(monkeypatch, _email_report(new=0, escalations=0))
    assert sent["level"] == "info"
    assert "不需要重構" in sent["body"]


def test_action_numbering_is_positional_not_hardcoded():
    """加一條 tier 行動時編號自動遞延 —— 這是「加資料不改邏輯」的實證。"""
    tier = dr.select_dreaming_tier({"escalations": 1, "new": 1})
    lines = dr.render_dreaming_actions(tier, {"escalations": 1, "new": 1, "date_str": "2026-07-18"})
    assert [line.split(".")[0] for line in lines] == ["1", "2", "3", "4"]
