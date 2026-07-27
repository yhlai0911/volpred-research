from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "unblock_expired_blocked_tasks.py"
SPEC = importlib.util.spec_from_file_location("unblock_expired_blocked_tasks", MODULE_PATH)
unblock_expired_blocked_tasks = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(unblock_expired_blocked_tasks)


def _write_work_shadow_gate_fixture(
    root: Path,
    *,
    observed_at: list[datetime],
    owner_sha_override: str | None = None,
) -> Path:
    state_path = root / "storage" / "ops" / "task_pool_mode.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_bytes = json.dumps(
        {"schema": 2, "enabled": False, "mode": "queued_execution"},
        sort_keys=True,
    ).encode("utf-8")
    state_path.write_bytes(state_bytes)
    owner_sha = owner_sha_override or hashlib.sha256(state_bytes).hexdigest()
    observations = state_path.parent / "work_shadow_observations"
    observations.mkdir()
    required_dimensions = (
        "priority",
        "claim_ownership",
        "parent",
        "deadline",
        "terminal_disposition",
    )
    for index, timestamp in enumerate(observed_at):
        snapshot_sha = f"{index + 1:064x}"
        receipt = {
            "schema_version": "work-shadow-replay.v4",
            "observation_id": f"scheduled_{index:02d}",
            "observed_at": timestamp.isoformat(),
            "recorded_at": timestamp.isoformat(),
            "selection_scope": "next_tasks",
            "snapshot": {
                "sha256": snapshot_sha,
                "byte_count": 100 + index,
                "source_counts": {
                    "next_tasks": 1,
                    "task_records": 0,
                    "ops_jobs": 0,
                },
            },
            "queue_owner_evidence": {
                "schema_version": "task-pool-owner-evidence.v1",
                "mode": "queued_execution",
                "gate_enabled": False,
                "state_path": str(state_path.resolve()),
                "state_sha256": owner_sha,
                "state_byte_count": len(state_bytes),
            },
            "legacy_selection": {
                "policy": "legacy",
                "snapshot_sha256": snapshot_sha,
                "selected_candidate_ref": "next_tasks:task-1",
                "eligible_candidate_refs": ["next_tasks:task-1"],
            },
            "coordinator_selection": {
                "policy": "work_coordinator",
                "snapshot_sha256": snapshot_sha,
                "selected_candidate_ref": "next_tasks:task-1",
                "eligible_candidate_refs": ["next_tasks:task-1"],
            },
            "selection_difference": None,
            "comparisons": [
                {
                    "candidate_ref": "next_tasks:task-1",
                    "legacy_eligible": True,
                    "coordinator_eligible": True,
                    "dimensions": [
                        {
                            "name": name,
                            "legacy": {"value": "same"},
                            "coordinator": {"value": "same"},
                            "matches": True,
                            "classification": None,
                            "classification_reason_code": None,
                            "legacy_reason_codes": [],
                            "coordinator_reason_codes": [],
                            "evidence_refs": [f"contract://{name}"],
                        }
                        for name in required_dimensions
                    ],
                }
            ],
            "reconciliation_issues": [],
        }
        (observations / f"scheduled_{index:02d}.json").write_text(
            json.dumps(receipt),
            encoding="utf-8",
        )
    return state_path


def test_invalid_blocked_until_warns_and_stays_blocked(tmp_path, monkeypatch, capsys) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "blocked_bad_until",
                    "task_type": "platform_ops",
                    "status": "blocked",
                    "blocked_reason": "awaiting_event_window",
                    "blocked_until": "!!!",
                    "blocked_note": "bad metadata should not unblock",
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(unblock_expired_blocked_tasks, "PATH", next_tasks)

    rc = unblock_expired_blocked_tasks.main(apply=True)

    assert rc == 0
    captured = capsys.readouterr()
    # 2026-07-04: the warn was migrated to the shared structured `warn()`
    # diagnostics helper (no-silent-fallback rule) — wording changed from
    # "invalid blocked_until; keeping task blocked" to a structured line.
    # Assert on the stable semantic fields, not the old prose.
    assert "[unblock] WARN blocked_until parse failed" in captured.err
    assert "task_id=blocked_bad_until" in captured.err
    assert "raw=!!!" in captured.err
    # 2026-07-14: b61789d26 folded tombstone compaction into this script, so the
    # summary line now reports both sweeps under a `[queue-maint]` tag.
    assert "[queue-maint] applied: 0 unblocked" in captured.out
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "blocked"
    assert saved[0]["blocked_reason"] == "awaiting_event_window"
    assert saved[0]["blocked_until"] == "!!!"


def test_apply_unblocks_expired_iso_timestamp(tmp_path, monkeypatch, capsys) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "blocked_expired",
                    "task_type": "platform_ops",
                    "status": "blocked",
                    "blocked_reason": "awaiting_event_window",
                    "blocked_at": "2026-01-01T00:00:00+00:00",
                    "blocked_until": "2000-01-01T00:00:00+00:00",
                    "blocked_note": "expired",
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(unblock_expired_blocked_tasks, "PATH", next_tasks)

    rc = unblock_expired_blocked_tasks.main(apply=True)

    assert rc == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "[queue-maint] applied: 1 unblocked" in captured.out
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "pending"
    assert "blocked_reason" not in saved[0]
    assert "blocked_at" not in saved[0]
    assert "blocked_until" not in saved[0]
    assert "blocked_note" not in saved[0]
    assert saved[0]["status_history"][-1]["from"] == "blocked"
    assert saved[0]["status_history"][-1]["to"] == "pending"


def test_expired_named_gate_stays_blocked_until_live_probe_is_ready(
    tmp_path, monkeypatch, capsys
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "shadow_soak",
                    "task_type": "platform_ops",
                    "status": "blocked",
                    "blocked_reason": "awaiting_event_window",
                    "blocked_until": "2000-01-01T00:00:00+00:00",
                    "unblock_gate": "work_shadow_cutover_ready_v1",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(unblock_expired_blocked_tasks, "PATH", next_tasks)
    calls: list[str] = []

    def not_ready(task: dict) -> tuple[bool, str, str | None]:
        calls.append(task["id"])
        return False, "observation_window_too_short", None

    monkeypatch.setattr(
        unblock_expired_blocked_tasks,
        "_probe_unblock_gate",
        not_ready,
    )

    assert unblock_expired_blocked_tasks.main(apply=True) == 0

    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert calls == ["shadow_soak"]
    assert saved[0]["status"] == "blocked"
    assert saved[0]["unblock_gate"] == "work_shadow_cutover_ready_v1"
    assert saved[0]["blocked_until"] == "2000-01-01T00:00:00+00:00"
    assert "1 live gate(s) retained" in capsys.readouterr().out


def test_expired_shadow_gate_rearms_to_new_clean_window(
    tmp_path, monkeypatch
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_eligible_at = "2099-08-03T12:40:16+00:00"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "shadow_soak",
                    "task_type": "platform_ops",
                    "status": "blocked",
                    "blocked_reason": "awaiting_event_window",
                    "blocked_until": "2000-01-01T00:00:00+00:00",
                    "unblock_gate": "work_shadow_cutover_ready_v1",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(unblock_expired_blocked_tasks, "PATH", next_tasks)
    monkeypatch.setattr(
        unblock_expired_blocked_tasks,
        "_probe_unblock_gate",
        lambda _task: (
            False,
            "observation_window_too_short",
            next_eligible_at,
        ),
    )

    assert unblock_expired_blocked_tasks.main(apply=True) == 0

    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "blocked"
    assert saved[0]["blocked_until"] == next_eligible_at
    assert saved[0]["unblock_gate"] == "work_shadow_cutover_ready_v1"
    assert saved[0]["status_history"][-1]["reason"] == (
        f"unblock_gate_rearmed_until ({next_eligible_at})"
    )


def test_expired_named_gate_unblocks_only_after_live_probe_is_ready(
    tmp_path, monkeypatch
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "shadow_soak",
                    "task_type": "platform_ops",
                    "status": "blocked",
                    "blocked_reason": "awaiting_event_window",
                    "blocked_until": "2000-01-01T00:00:00+00:00",
                    "unblock_gate": "work_shadow_cutover_ready_v1",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(unblock_expired_blocked_tasks, "PATH", next_tasks)
    monkeypatch.setattr(
        unblock_expired_blocked_tasks,
        "_probe_unblock_gate",
        lambda _task: (True, "ready_for_cutover", None),
    )

    assert unblock_expired_blocked_tasks.main(apply=True) == 0

    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "pending"
    assert "unblock_gate" not in saved[0]
    assert (
        saved[0]["status_history"][-1]["reason"]
        == "unblock_gate_satisfied (work_shadow_cutover_ready_v1)"
    )


def test_unexpired_named_gate_is_not_probed(
    tmp_path, monkeypatch
) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    original = [
        {
            "id": "shadow_soak",
            "task_type": "platform_ops",
            "status": "blocked",
            "blocked_reason": "awaiting_event_window",
            "blocked_until": "2999-01-01T00:00:00+00:00",
            "unblock_gate": "work_shadow_cutover_ready_v1",
        }
    ]
    next_tasks.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(unblock_expired_blocked_tasks, "PATH", next_tasks)

    def unexpected_probe(_task: dict) -> tuple[bool, str]:
        raise AssertionError("a not-before timestamp must gate the live probe")

    monkeypatch.setattr(
        unblock_expired_blocked_tasks,
        "_probe_unblock_gate",
        unexpected_probe,
    )

    assert unblock_expired_blocked_tasks.main(apply=True) == 0
    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "blocked"
    assert saved[0]["blocked_until"] == original[0]["blocked_until"]
    assert saved[0]["unblock_gate"] == original[0]["unblock_gate"]


def test_unknown_unblock_gate_fails_closed_without_execution() -> None:
    ready, detail, next_eligible_at = (
        unblock_expired_blocked_tasks._probe_unblock_gate(
            {
                "id": "unsafe",
                "unblock_gate": "shell:touch /tmp/unsafe",
            }
        )
    )

    assert ready is False
    assert detail.startswith("unknown_unblock_gate:")
    assert next_eligible_at is None


def test_production_work_shadow_gate_maps_ready_assessment(
    tmp_path, monkeypatch
) -> None:
    now = datetime.now(timezone.utc)
    _write_work_shadow_gate_fixture(
        tmp_path,
        observed_at=[now - timedelta(days=day) for day in range(7, -1, -1)],
    )
    monkeypatch.setattr(
        unblock_expired_blocked_tasks,
        "_REPO_ROOT",
        tmp_path,
    )

    assert unblock_expired_blocked_tasks._probe_unblock_gate(
        {"unblock_gate": "work_shadow_cutover_ready_v1"}
    ) == (True, "ready_for_cutover", None)


def test_production_work_shadow_gate_maps_short_window_fail_closed(
    tmp_path, monkeypatch
) -> None:
    now = datetime.now(timezone.utc)
    _write_work_shadow_gate_fixture(
        tmp_path,
        observed_at=[now - timedelta(hours=1), now],
    )
    monkeypatch.setattr(
        unblock_expired_blocked_tasks,
        "_REPO_ROOT",
        tmp_path,
    )

    ready, detail, next_eligible_at = (
        unblock_expired_blocked_tasks._probe_unblock_gate(
            {"unblock_gate": "work_shadow_cutover_ready_v1"}
        )
    )

    assert ready is False
    assert detail == "observation_window_too_short"
    assert next_eligible_at is not None


def test_production_work_shadow_gate_rejects_owner_mismatch(
    tmp_path, monkeypatch
) -> None:
    now = datetime.now(timezone.utc)
    _write_work_shadow_gate_fixture(
        tmp_path,
        observed_at=[now - timedelta(days=day) for day in range(7, -1, -1)],
        owner_sha_override="f" * 64,
    )
    monkeypatch.setattr(
        unblock_expired_blocked_tasks,
        "_REPO_ROOT",
        tmp_path,
    )

    ready, detail, next_eligible_at = (
        unblock_expired_blocked_tasks._probe_unblock_gate(
            {"unblock_gate": "work_shadow_cutover_ready_v1"}
        )
    )

    assert ready is False
    assert "no_observations" in detail
    assert next_eligible_at is None


def test_production_work_shadow_gate_rejects_unreadable_owner_evidence(
    tmp_path, monkeypatch
) -> None:
    state_path = _write_work_shadow_gate_fixture(
        tmp_path,
        observed_at=[datetime.now(timezone.utc)],
    )
    state_path.unlink()
    monkeypatch.setattr(
        unblock_expired_blocked_tasks,
        "_REPO_ROOT",
        tmp_path,
    )

    ready, detail, next_eligible_at = (
        unblock_expired_blocked_tasks._probe_unblock_gate(
            {"unblock_gate": "work_shadow_cutover_ready_v1"}
        )
    )

    assert ready is False
    assert detail.startswith("work_shadow_assessment_unavailable:")
    assert next_eligible_at is None


def test_successful_codex_probe_unblocks_before_reset_date(tmp_path, monkeypatch, capsys) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "quota_future_a",
                    "task_type": "paper_review",
                    "status": "blocked",
                    "blocked_reason": "codex_quota_reset_pending",
                    "blocked_until": "2999-01-01T00:00:00+00:00",
                },
                {
                    "id": "ordinary_future",
                    "task_type": "platform_ops",
                    "status": "blocked",
                    "blocked_reason": "awaiting_event_window",
                    "blocked_until": "2999-01-01T00:00:00+00:00",
                },
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(unblock_expired_blocked_tasks, "PATH", next_tasks)
    monkeypatch.setattr(
        unblock_expired_blocked_tasks,
        "_probe_codex_available",
        lambda: (True, "ChatGPT answered"),
    )

    assert unblock_expired_blocked_tasks.main(apply=True) == 0

    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "pending"
    assert "blocked_until" not in saved[0]
    assert saved[0]["status_history"][-1]["reason"] == "codex_reachability_probe_succeeded"
    assert saved[1]["status"] == "blocked"
    assert "codex quota probe: available; blocked=1" in capsys.readouterr().out


def test_failed_codex_probe_keeps_expired_quota_blocked(tmp_path, monkeypatch, capsys) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    next_tasks.write_text(
        json.dumps(
            [
                {
                    "id": "quota_expired_but_still_down",
                    "task_type": "paper_review",
                    "status": "blocked",
                    "blocked_reason": "codex_quota_reset_pending",
                    "blocked_until": "2000-01-01T00:00:00+00:00",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(unblock_expired_blocked_tasks, "PATH", next_tasks)
    monkeypatch.setattr(
        unblock_expired_blocked_tasks,
        "_probe_codex_available",
        lambda: (False, "usage limit still active"),
    )

    assert unblock_expired_blocked_tasks.main(apply=True) == 0

    saved = json.loads(next_tasks.read_text(encoding="utf-8"))
    assert saved[0]["status"] == "blocked"
    assert saved[0]["blocked_until"] == "2000-01-01T00:00:00+00:00"
    assert "codex quota probe: unavailable; blocked=1" in capsys.readouterr().out


def test_dry_run_reports_quota_probe_without_calling_it(tmp_path, monkeypatch, capsys) -> None:
    next_tasks = tmp_path / "next_tasks.json"
    original = [
        {
            "id": "quota_dry_run",
            "task_type": "paper_review",
            "status": "blocked",
            "blocked_reason": "codex_quota_reset_pending",
            "blocked_until": "2000-01-01T00:00:00+00:00",
        }
    ]
    next_tasks.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(unblock_expired_blocked_tasks, "PATH", next_tasks)

    def unexpected_probe() -> tuple[bool, str]:
        raise AssertionError("dry-run must not spend a Codex probe")

    monkeypatch.setattr(unblock_expired_blocked_tasks, "_probe_codex_available", unexpected_probe)

    assert unblock_expired_blocked_tasks.main(apply=False) == 0

    assert json.loads(next_tasks.read_text(encoding="utf-8")) == original
    assert "would actively probe Codex for 1 quota-blocked task(s); no probe sent" in capsys.readouterr().out
