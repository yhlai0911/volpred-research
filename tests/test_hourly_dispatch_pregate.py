from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY_SCRIPTS = ROOT / "scripts" / "_legacy"
if str(LEGACY_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(LEGACY_SCRIPTS))

import hourly_dispatch_pregate as pregate  # type: ignore


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# ── has_critical(): 2026-07-01 bug fix regression coverage ──
# Root cause: previously read nonexistent breach_count/breaches/critical/
# critical_count keys (always 0) and fell through to overall_status != ok,
# which is "warn" almost continuously (loop_health soft-tracking, reference-
# only host_cron_fail false-positive) -> signal was always True, defeating
# the gate. Fix reads the REAL scripts/ops_dashboard.py field
# `section_critical` (count of sections whose status is literally "critical").
def test_has_critical_false_when_only_warn_sections(tmp_path, monkeypatch):
    dashboard = tmp_path / "dashboard_latest.json"
    _write_json(dashboard, {"overall_status": "warn", "section_breaches": 2, "section_critical": 0})
    monkeypatch.setattr(pregate, "DASHBOARD", dashboard)
    assert pregate.has_critical() is False


def test_has_critical_true_when_section_critical_positive(tmp_path, monkeypatch):
    dashboard = tmp_path / "dashboard_latest.json"
    _write_json(dashboard, {"overall_status": "critical", "section_breaches": 3, "section_critical": 1})
    monkeypatch.setattr(pregate, "DASHBOARD", dashboard)
    assert pregate.has_critical() is True


def test_has_critical_unparseable_section_critical_fails_open(tmp_path, monkeypatch):
    dashboard = tmp_path / "dashboard_latest.json"
    _write_json(dashboard, {"overall_status": "warn", "section_critical": "not-a-number"})
    monkeypatch.setattr(pregate, "DASHBOARD", dashboard)
    assert pregate.has_critical() is True


def test_has_critical_falls_back_to_overall_status_when_field_missing(tmp_path, monkeypatch):
    # Older/missing schema without section_critical at all.
    dashboard = tmp_path / "dashboard_latest.json"
    _write_json(dashboard, {"overall_status": "warn"})
    monkeypatch.setattr(pregate, "DASHBOARD", dashboard)
    assert pregate.has_critical() is True

    _write_json(dashboard, {"overall_status": "ok"})
    assert pregate.has_critical() is False


# ── has_email_backlog() ──
def test_has_email_backlog_detects_pending_email_reply():
    tasks = [{"task_type": "email_reply", "status": "pending"}, {"task_type": "experiment", "status": "pending"}]
    assert pregate.has_email_backlog(tasks) is True


def test_has_email_backlog_false_when_none_pending():
    tasks = [{"task_type": "email_reply", "status": "succeeded"}, {"task_type": "experiment", "status": "pending"}]
    assert pregate.has_email_backlog(tasks) is False


# ── decide(): integration, real dashboard schema, gate now produces a meaningful skip ──
def test_decide_would_skip_true_when_all_signals_quiet(tmp_path, monkeypatch):
    dashboard = tmp_path / "dashboard_latest.json"
    next_tasks = tmp_path / "next_tasks.json"
    work_log = tmp_path / "work_log.json"
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=1)).isoformat()

    _write_json(dashboard, {"overall_status": "warn", "section_breaches": 1, "section_critical": 0})
    _write_json(
        next_tasks,
        [
            {"task_type": "experiment", "status": "succeeded", "priority": 3},
            {
                "task_type": "daily_article",
                "status": "succeeded",
                "claimed_by": "hourly-dispatch",
                # 2026-07-10: cadence is keyed on COMPLETION, not claim — a claim
                # that never finished produced no output. (Also: no real claimer
                # is named 'hourly-*'; cadence is now actor-agnostic.)
                "completed_at": recent,
            },
        ],
    )
    _write_json(work_log, [])

    monkeypatch.setattr(pregate, "DASHBOARD", dashboard)
    monkeypatch.setattr(pregate, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(pregate, "WORK_LOG", work_log)
    monkeypatch.setattr(pregate, "has_high_prio", lambda tasks: False)
    # isolate the 2026-07-10 signals so this unit test never touches the real
    # compute queue / alerts module
    monkeypatch.setattr(pregate, "COMPUTE_QUEUE", tmp_path / "no_queue")
    monkeypatch.setattr(pregate, "has_publish_drought", lambda: False)
    monkeypatch.setattr(pregate, "free_slots", lambda: 4)

    result = pregate.decide(window_hours=3.0)
    assert result["proceed"] is False
    assert result["reasons"]["critical"] is False
    assert result["reasons"]["cadence_due"] is False


def test_decide_proceeds_on_true_critical(tmp_path, monkeypatch):
    dashboard = tmp_path / "dashboard_latest.json"
    next_tasks = tmp_path / "next_tasks.json"
    work_log = tmp_path / "work_log.json"
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=1)).isoformat()

    _write_json(dashboard, {"overall_status": "critical", "section_breaches": 3, "section_critical": 1})
    _write_json(
        next_tasks,
        [
            {
                "task_type": "daily_article",
                "status": "succeeded",
                "claimed_by": "hourly-dispatch",
                "completed_at": recent,
            }
        ],
    )
    _write_json(work_log, [])

    monkeypatch.setattr(pregate, "DASHBOARD", dashboard)
    monkeypatch.setattr(pregate, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(pregate, "WORK_LOG", work_log)
    monkeypatch.setattr(pregate, "has_high_prio", lambda tasks: False)
    monkeypatch.setattr(pregate, "COMPUTE_QUEUE", tmp_path / "no_queue")
    monkeypatch.setattr(pregate, "has_publish_drought", lambda: False)
    monkeypatch.setattr(pregate, "STATE", tmp_path / "pregate_state.json")
    monkeypatch.setattr(pregate, "free_slots", lambda: 4)

    result = pregate.decide(window_hours=3.0)
    assert result["proceed"] is True
    # critical alone must carry the fire — cadence is quiet here
    assert result["reasons"]["cadence_due"] is False
    assert result["reasons"]["critical"] is True


# ── invoker attribution（2026-07-10 pregate-observability）──────────────────


def _isolate_main(tmp_path, monkeypatch):
    """main() 級測試的完整路徑隔離 — 絕不寫 production log。"""
    dashboard = tmp_path / "dashboard_latest.json"
    next_tasks = tmp_path / "next_tasks.json"
    work_log = tmp_path / "work_log.json"
    log = tmp_path / "hourly_pregate.jsonl"
    _write_json(dashboard, {"section_critical": 0})
    _write_json(next_tasks, [])
    _write_json(work_log, [])
    monkeypatch.setattr(pregate, "DASHBOARD", dashboard)
    monkeypatch.setattr(pregate, "NEXT_TASKS", next_tasks)
    monkeypatch.setattr(pregate, "WORK_LOG", work_log)
    monkeypatch.setattr(pregate, "LOG", log)
    # main() persists the novelty baseline on every proceed — isolate it or a
    # test run overwrites the production gate's state file.
    monkeypatch.setattr(pregate, "STATE", tmp_path / "pregate_state.json")
    monkeypatch.setattr(pregate, "free_slots", lambda: 4)
    # absolute-demand signals read repo-global paths — left live, a real compute
    # followup or drought forces PROCEED and the skip assertions depend on what
    # the production queue happens to hold (2026-07-20: exactly that flake).
    monkeypatch.setattr(pregate, "COMPUTE_QUEUE", tmp_path / "no_queue")
    monkeypatch.setattr(pregate, "has_publish_drought", lambda: False)
    return log


# ── 2026-07-10 root-cause fix: cadence was structurally always-due ──────────
# Old `_last_substantive_dispatch` only counted tasks whose `claimed_by`
# startswith 'hourly' (and work_log actors containing 'hourly'). NO claimer in
# this repo is named that way (real owners: codex-cli 535 claims, codex-vscode,
# interactive-claude, telegram-responder, main-session). So cadence_due was True
# on 20/20 supervisor fires and the gate could never skip. It was wired, tested,
# deployed — and a structural no-op.


def _cadence_env(tmp_path, monkeypatch, tasks, work_log=None):
    """Isolate every path decide()/cadence touches. Never reads production."""
    nt, wl, dash = tmp_path / "next_tasks.json", tmp_path / "work_log.json", tmp_path / "dash.json"
    _write_json(nt, tasks)
    _write_json(wl, work_log if work_log is not None else [])
    _write_json(dash, {"section_critical": 0})
    monkeypatch.setattr(pregate, "NEXT_TASKS", nt)
    monkeypatch.setattr(pregate, "WORK_LOG", wl)
    monkeypatch.setattr(pregate, "DASHBOARD", dash)
    monkeypatch.setattr(pregate, "COMPUTE_QUEUE", tmp_path / "no_queue")
    monkeypatch.setattr(pregate, "has_publish_drought", lambda: False)
    monkeypatch.setattr(pregate, "has_high_prio", lambda tasks: False)
    # STATE holds the novelty baseline. Left unpatched, decide() reads — and
    # main() WRITES — the production storage/ops/pregate_state.json, so a test
    # run would silently move the real gate's baseline.
    monkeypatch.setattr(pregate, "STATE", tmp_path / "pregate_state.json")
    monkeypatch.setattr(pregate, "free_slots", lambda: 4)


def _task(*, ttype="experiment", status="succeeded", completed_at=None, claimed_by="codex-cli"):
    t = {"task_type": ttype, "status": status, "priority": 3, "claimed_by": claimed_by}
    if completed_at:
        t["completed_at"] = completed_at
    return t


def test_cadence_counts_non_hourly_claimers(tmp_path, monkeypatch):
    """THE regression: work finished by codex-cli must reset the cadence clock."""
    recent = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    _cadence_env(tmp_path, monkeypatch, [_task(completed_at=recent, claimed_by="codex-cli")])
    result = pregate.decide(window_hours=3.0)
    assert result["reasons"]["cadence_due"] is False
    assert result["proceed"] is False  # nothing else demands a fire -> skip


def test_cadence_ignores_claimed_but_unfinished(tmp_path, monkeypatch):
    """A claim that never completed is not output — it must not reset cadence."""
    recent = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    _cadence_env(tmp_path, monkeypatch,
                 [_task(status="in_progress", completed_at=recent)])
    assert pregate.decide(window_hours=3.0)["reasons"]["cadence_due"] is True


def test_cadence_ignores_ops_types(tmp_path, monkeypatch):
    """platform_ops/governance are overhead — research can still be starving."""
    recent = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    _cadence_env(tmp_path, monkeypatch, [_task(ttype="platform_ops", completed_at=recent)])
    assert pregate.decide(window_hours=3.0)["reasons"]["cadence_due"] is True


def test_cadence_reads_status_history_when_completed_at_missing(tmp_path, monkeypatch):
    recent = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    t = _task()
    t.pop("completed_at", None)
    t["status_history"] = [{"ts": recent, "from": "in_progress", "to": "succeeded"}]
    _cadence_env(tmp_path, monkeypatch, [t])
    assert pregate.decide(window_hours=3.0)["reasons"]["cadence_due"] is False


def test_cadence_from_work_log_naive_timestamp_is_host_local(tmp_path, monkeypatch):
    """Bare `2026-07-08T03:16` rows are host wall clock (Asia/Taipei), not UTC."""
    local_recent = datetime.now(pregate._HOST_TZ) - timedelta(minutes=30)
    wl = [{"ts": local_recent.replace(tzinfo=None).isoformat(),
           "task_type": "daily_article", "outcome": "succeeded"}]
    _cadence_env(tmp_path, monkeypatch, [], work_log=wl)
    r = pregate.decide(window_hours=3.0)["reasons"]
    assert r["cadence_due"] is False
    assert 0 <= r["cadence_hours_since"] < 1.0  # not shifted 8h


def test_cadence_future_timestamp_fails_open(tmp_path, monkeypatch):
    """Clock skew must never manufacture a skip."""
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    _cadence_env(tmp_path, monkeypatch, [_task(completed_at=future)])
    r = pregate.decide(window_hours=3.0)["reasons"]
    assert r["cadence_hours_since"] < 0
    assert r["cadence_due"] is True


# ── new demand signals: the hourly fire also owns these repairs ─────────────


def test_compute_followup_pending_forces_proceed(tmp_path, monkeypatch):
    recent = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    _cadence_env(tmp_path, monkeypatch, [_task(completed_at=recent)])
    q = tmp_path / "queue"
    q.mkdir()
    _write_json(q / "job.json", {"status": "completed", "claude_followup": {"brief": "x"},
                                 "followup_dispatched": False})
    monkeypatch.setattr(pregate, "COMPUTE_QUEUE", q)
    result = pregate.decide(window_hours=3.0)
    assert result["reasons"]["compute_followup"] is True
    assert result["proceed"] is True  # would have skipped on cadence alone


def test_compute_followup_ignores_dispatched_and_running(tmp_path, monkeypatch):
    recent = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    _cadence_env(tmp_path, monkeypatch, [_task(completed_at=recent)])
    q = tmp_path / "queue"
    q.mkdir()
    _write_json(q / "a.json", {"status": "completed", "claude_followup": {"b": 1},
                               "followup_dispatched": True})
    _write_json(q / "b.json", {"status": "running", "claude_followup": {"b": 1}})
    _write_json(q / "c.json", {"status": "completed", "claude_followup": None})
    monkeypatch.setattr(pregate, "COMPUTE_QUEUE", q)
    assert pregate.decide(window_hours=3.0)["reasons"]["compute_followup"] is False


def test_compute_followup_bad_file_does_not_mask_pending(tmp_path, monkeypatch):
    q = tmp_path / "queue"
    q.mkdir()
    (q / "corrupt.json").write_text("{not json", encoding="utf-8")
    _write_json(q / "ok.json", {"status": "completed", "claude_followup": {"b": 1},
                                "followup_dispatched": False})
    monkeypatch.setattr(pregate, "COMPUTE_QUEUE", q)
    assert pregate.has_compute_followup() is True


def test_publish_drought_forces_proceed(tmp_path, monkeypatch):
    recent = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    _cadence_env(tmp_path, monkeypatch, [_task(completed_at=recent)])
    monkeypatch.setattr(pregate, "has_publish_drought", lambda: True)
    result = pregate.decide(window_hours=3.0)
    assert result["reasons"]["publish_drought"] is True
    assert result["proceed"] is True


def test_new_signal_read_failure_fails_open(tmp_path, monkeypatch):
    """A crashing signal reads as unknown (None) -> demand -> proceed."""
    recent = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    _cadence_env(tmp_path, monkeypatch, [_task(completed_at=recent)])

    def boom():
        raise RuntimeError("alerts module exploded")

    monkeypatch.setattr(pregate, "has_publish_drought", boom)
    result = pregate.decide(window_hours=3.0)
    assert result["reasons"]["publish_drought"] is None
    assert result["proceed"] is True


def test_substantive_types_single_source_with_crosscheck():
    """The audit tool must measure the exact population the gate measures."""
    import crosscheck_pregate_outcomes as cc  # type: ignore

    assert cc.SUBSTANTIVE is pregate.SUBSTANTIVE_TYPES
    assert "daily_digest" in pregate.SUBSTANTIVE_TYPES


# ------ 15-minute cadence semantics--2026-07-20, telegram-1198--------------------------------------------------
# The gate was demand-only ("is there work?"), which is the right question at
# 60 minutes and the wrong one at 15: the pool always holds P1/P2, so
# high_prio was true on 164/164 fires and would_skip was 0. capacity + novelty
# ask "can a fire add throughput?" and "has anything changed?" instead.


def _fifteen_min_env(tmp_path, monkeypatch, tasks, *, free=4, critical=0):
    """decide() env for the sub-hourly signals, with cadence deliberately quiet."""
    recent = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    _cadence_env(tmp_path, monkeypatch,
                 [_task(completed_at=recent)] + list(tasks))
    _write_json(tmp_path / "dash.json", {"section_critical": critical,
                                         "sections": [{"section": "s1", "status": "critical"}] * critical})
    monkeypatch.setattr(pregate, "free_slots", lambda: free)
    monkeypatch.setattr(pregate, "has_high_prio", lambda tasks: True)


def _p1(task_id):
    return {"id": task_id, "task_type": "experiment", "status": "pending", "priority": 1}


def test_unchanged_world_skips_the_second_fire(tmp_path, monkeypatch):
    """THE 15-min fix: an identical pool + no new work must not re-fire."""
    _fifteen_min_env(tmp_path, monkeypatch, [_p1("a"), _p1("b")])

    first = pregate.decide(window_hours=3.0)
    assert first["proceed"] is True and first["reasons"]["novel"] is True
    pregate._write_signature(first["signature"])

    second = pregate.decide(window_hours=3.0)
    assert second["reasons"]["novel"] is False
    assert second["proceed"] is False


def test_changed_pool_breaks_novelty_immediately(tmp_path, monkeypatch):
    """Keyed on identity, not counts: swapping one P1 for another IS a change."""
    _fifteen_min_env(tmp_path, monkeypatch, [_p1("a"), _p1("b")])
    pregate._write_signature(pregate.decide(window_hours=3.0)["signature"])

    _fifteen_min_env(tmp_path, monkeypatch, [_p1("a"), _p1("c")])  # same count
    after = pregate.decide(window_hours=3.0)
    assert after["reasons"]["novel"] is True
    assert after["proceed"] is True


def test_no_free_slot_vetoes_the_high_prio_path(tmp_path, monkeypatch):
    """Demand without capacity is a queue, not work."""
    _fifteen_min_env(tmp_path, monkeypatch, [_p1("a")], free=0)
    result = pregate.decide(window_hours=3.0)
    assert result["reasons"]["capacity"] is False
    assert result["proceed"] is False


def test_email_backlog_ignores_both_vetoes(tmp_path, monkeypatch):
    """Absolute demand: a queue this fire drains. Responsiveness invariant."""
    _fifteen_min_env(tmp_path, monkeypatch,
                     [{"id": "e1", "task_type": "email_reply", "status": "pending"}],
                     free=0)
    pregate._write_signature(pregate.decide(window_hours=3.0)["signature"])

    repeat = pregate.decide(window_hours=3.0)
    assert repeat["reasons"]["novel"] is False and repeat["reasons"]["capacity"] is False
    assert repeat["proceed"] is True  # still fires --- email is never vetoed


def test_repeat_critical_stops_re_firing_but_a_new_one_does_not(tmp_path, monkeypatch):
    """critical is an incident STATE, not a queue --- identical set buys nothing."""
    _fifteen_min_env(tmp_path, monkeypatch, [], critical=1)
    monkeypatch.setattr(pregate, "has_high_prio", lambda tasks: False)
    pregate._write_signature(pregate.decide(window_hours=3.0)["signature"])

    repeat = pregate.decide(window_hours=3.0)
    assert repeat["reasons"]["critical"] is True
    assert repeat["proceed"] is False  # same incident, no second cold-load

    _write_json(tmp_path / "dash.json",
                {"section_critical": 2,
                 "sections": [{"section": "s1", "status": "critical"},
                              {"section": "s2", "status": "critical"}]})
    escalated = pregate.decide(window_hours=3.0)
    assert escalated["reasons"]["novel"] is True
    assert escalated["proceed"] is True  # a NEW critical fires at once


def test_cadence_due_overrides_both_vetoes(tmp_path, monkeypatch):
    """The starvation floor: a static pool can never stall research forever."""
    stale = (datetime.now(timezone.utc) - timedelta(hours=9)).isoformat()
    _cadence_env(tmp_path, monkeypatch, [_task(completed_at=stale), _p1("a")])
    monkeypatch.setattr(pregate, "free_slots", lambda: 0)
    monkeypatch.setattr(pregate, "has_high_prio", lambda tasks: True)
    pregate._write_signature(pregate.decide(window_hours=3.0)["signature"])

    result = pregate.decide(window_hours=3.0)
    assert result["reasons"]["novel"] is False and result["reasons"]["capacity"] is False
    assert result["reasons"]["cadence_due"] is True
    assert result["proceed"] is True


def test_slot_read_failure_fails_open_to_capacity_available(tmp_path, monkeypatch):
    _fifteen_min_env(tmp_path, monkeypatch, [_p1("a")])

    def boom():
        raise RuntimeError("slot budget exploded")

    monkeypatch.setattr(pregate, "free_slots", boom)
    result = pregate.decide(window_hours=3.0)
    assert result["reasons"]["free_slots"] is None
    assert result["reasons"]["capacity"] is True
    assert result["proceed"] is True


def test_retired_cli_cannot_emit_a_gate_decision(tmp_path, monkeypatch, capsys):
    """The retained evaluator is evidence-only; its CLI cannot resurrect authority."""
    log = _isolate_main(tmp_path, monkeypatch)
    state = tmp_path / "pregate_state.json"
    _write_json(state, {"last_proceed_signature": "stale-baseline"})

    rc = pregate.main(["--invoker", "test"])  # real mode
    captured = capsys.readouterr()

    assert rc == 2
    assert "retired" in captured.err.lower()
    assert json.loads(state.read_text())["last_proceed_signature"] == "stale-baseline"
    assert not log.exists()
