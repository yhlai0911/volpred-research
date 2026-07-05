from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "migrate_blocked_lane_terminal.py"
SPEC = importlib.util.spec_from_file_location("migrate_blocked_lane_terminal", MODULE_PATH)
migration = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = migration
SPEC.loader.exec_module(migration)


def test_migrate_deprecated_blocked_to_superseded_and_clears_claim() -> None:
    tasks = [
        {
            "id": "K1_article_general",
            "status": "blocked",
            "blocked_reason": "deprecated",
            "blocked_note": "Already covered by mile_abc123; duplicate.",
            "blocked_until": "2099-01-01",
            "claimed_by": "codex-cli",
            "claimed_at": "2026-05-26T00:00:00+00:00",
            "claim_session_id": "old",
        }
    ]

    stats = migration.migrate_tasks(tasks, now_iso="2026-07-05T00:00:00+00:00")

    assert stats.deprecated_terminalized == 1
    assert stats.to_superseded == 1
    assert stats.stale_claims_cleared == 1
    assert tasks[0]["status"] == "superseded"
    assert tasks[0]["blocked_reason"] == "deprecated"
    assert tasks[0]["terminal_migration_from_status"] == "blocked"
    assert "blocked_until" not in tasks[0]
    assert "claimed_by" not in tasks[0]
    assert tasks[0]["stale_claim_previous_claimed_by"] == "codex-cli"


def test_migrate_deprecated_blocked_to_closed_no_action_when_not_superseded() -> None:
    tasks = [
        {
            "id": "event_article_old",
            "status": "blocked",
            "blocked_reason": "deprecated",
            "blocked_note": "Event window expired; no article needed.",
        }
    ]

    stats = migration.migrate_tasks(tasks, now_iso="2026-07-05T00:00:00+00:00")

    assert stats.deprecated_terminalized == 1
    assert stats.to_closed_no_action == 1
    assert tasks[0]["status"] == "closed_no_action"
    assert tasks[0]["terminal_migration_target_status"] == "closed_no_action"


def test_run_dry_run_does_not_write(tmp_path: Path) -> None:
    path = tmp_path / "next_tasks.json"
    original = [
        {
            "id": "K1_article_general",
            "status": "blocked",
            "blocked_reason": "deprecated",
            "blocked_note": "duplicate",
        }
    ]
    path.write_text(json.dumps(original, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    stats = migration.run(apply=False, path=path)

    assert stats.deprecated_terminalized == 1
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == original
