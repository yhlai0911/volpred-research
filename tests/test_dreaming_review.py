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


def test_main_exits_zero_even_when_all_detectors_fail(tmp_path, monkeypatch):
    storage = _storage(tmp_path)

    def _boom(*a, **k):
        raise RuntimeError("boom")

    # Patch the DETECTORS tuple itself (main iterates it) so every detector raises.
    monkeypatch.setattr(dr, "DETECTORS", tuple(_boom for _ in dr.DETECTORS))
    rc = dr.main(storage_dir=str(storage), dry_run=True, now=NOW)
    assert rc == 0
