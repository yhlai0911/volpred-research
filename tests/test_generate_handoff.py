from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_generate_handoff():
    module_path = ROOT / "scripts" / "generate_handoff.py"
    spec = importlib.util.spec_from_file_location("generate_handoff", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _write_fixture_files(tmp_path: Path, tasks: list[dict]) -> None:
    (tmp_path / "ops" / "agents").mkdir(parents=True)
    (tmp_path / "worktrees").mkdir()
    (tmp_path / "next_tasks.json").write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "dashboard_latest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "work_log.json").write_text("[]", encoding="utf-8")
    (tmp_path / "gmail_inbox_state.json").write_text("{}", encoding="utf-8")


def _patch_paths(monkeypatch, module, tmp_path: Path) -> None:
    monkeypatch.setattr(module, "NEXT_TASKS", tmp_path / "next_tasks.json")
    monkeypatch.setattr(module, "DASHBOARD", tmp_path / "dashboard_latest.json")
    monkeypatch.setattr(module, "WORK_LOG", tmp_path / "work_log.json")
    monkeypatch.setattr(module, "GMAIL_STATE", tmp_path / "gmail_inbox_state.json")
    monkeypatch.setattr(module, "WORKTREES", tmp_path / "worktrees")
    monkeypatch.setattr(module, "AGENTS_DIR", tmp_path / "ops" / "agents")
    monkeypatch.setattr(module, "_now_local", lambda: "2026-06-22 06:50:00")


def test_handoff_surfaces_codex_eligible_pending_counts(tmp_path, monkeypatch) -> None:
    module = _load_generate_handoff()
    _write_fixture_files(
        tmp_path,
        [
            {"id": "trend", "status": "pending", "task_type": "trending_repost", "priority": 1},
            {"id": "ops", "status": "pending", "task_type": "platform_ops", "priority": 2},
            {"id": "paper", "status": "pending_main_thread", "task_type": "paper_body", "priority": 1},
        ],
    )
    _patch_paths(monkeypatch, module, tmp_path)

    handoff = module.build()

    assert "Codex-eligible pending: 1" in handoff
    assert "Codex-skip pending: 2" in handoff
    assert "**Codex-eligible pending top 8**" in handoff
    assert "`ops` P2 [platform_ops]" in handoff


def test_handoff_warns_codex_when_only_skip_pending_exists(tmp_path, monkeypatch) -> None:
    module = _load_generate_handoff()
    _write_fixture_files(
        tmp_path,
        [
            {"id": "trend", "status": "pending", "task_type": "trending_repost", "priority": 1},
            {"id": "reply", "status": "pending", "task_type": "email_reply", "priority": 1},
        ],
    )
    _patch_paths(monkeypatch, module, tmp_path)

    handoff = module.build()

    assert "Codex-eligible pending: 0" in handoff
    assert "Codex-skip pending: 2" in handoff
    assert "沒有可 claim 的 pending" in handoff
    assert "task_pool_claim.py list --codex-eligible" in handoff


def test_handoff_warns_on_invalid_json_source(tmp_path, monkeypatch, capsys) -> None:
    module = _load_generate_handoff()
    _write_fixture_files(tmp_path, [])
    (tmp_path / "next_tasks.json").write_text("{bad-json", encoding="utf-8")
    _patch_paths(monkeypatch, module, tmp_path)

    handoff = module.build()

    assert "總數**：0" in handoff
    captured = capsys.readouterr()
    assert "[generate_handoff] WARN JSON read failed; using default" in captured.err
    assert "next_tasks.json" in captured.err
    assert "JSONDecodeError" in captured.err


def test_handoff_warns_on_invalid_agent_receipt(tmp_path, monkeypatch, capsys) -> None:
    module = _load_generate_handoff()
    _write_fixture_files(tmp_path, [])
    bad_agent = tmp_path / "ops" / "agents" / "bad-agent.json"
    bad_agent.write_text("{bad-json", encoding="utf-8")
    _patch_paths(monkeypatch, module, tmp_path)

    handoff = module.build()

    assert "slot 占用**：0 / 4" in handoff
    captured = capsys.readouterr()
    assert "[generate_handoff] WARN JSON read failed; skipping agent receipt" in captured.err
    assert "bad-agent.json" in captured.err
    assert "JSONDecodeError" in captured.err


def test_handoff_surfaces_invalid_completed_at_warning(tmp_path, monkeypatch) -> None:
    module = _load_generate_handoff()
    _write_fixture_files(
        tmp_path,
        [
            {
                "id": "bad_completed",
                "status": "succeeded",
                "task_type": "platform_ops",
                "completed_at": "not-a-date",
            }
        ],
    )
    _patch_paths(monkeypatch, module, tmp_path)

    handoff = module.build()

    assert "**task pool warnings" in handoff
    assert "invalid completed_at for succeeded task bad_completed" in handoff
    assert "not-a-date" in handoff


def test_handoff_surfaces_invalid_pending_priority_warning(tmp_path, monkeypatch) -> None:
    module = _load_generate_handoff()
    _write_fixture_files(
        tmp_path,
        [
            {
                "id": "bad_priority",
                "status": "pending",
                "task_type": "platform_ops",
                "priority": "urgent",
                "title": "Bad priority task",
            }
        ],
    )
    _patch_paths(monkeypatch, module, tmp_path)

    handoff = module.build()

    assert "**task pool warnings" in handoff
    assert "invalid priority for pending task bad_priority" in handoff
    assert "urgent" in handoff
    assert "treating as P9" in handoff


def test_handoff_accepts_naive_completed_at_without_warning(tmp_path, monkeypatch) -> None:
    module = _load_generate_handoff()
    _write_fixture_files(
        tmp_path,
        [
            {
                "id": "naive_completed",
                "status": "succeeded",
                "task_type": "platform_ops",
                "completed_at": "2026-05-19T11:49:03.785530",
            },
            {
                "id": "date_only_completed",
                "status": "succeeded",
                "task_type": "platform_ops",
                "completed_at": "2026-05-04",
            },
        ],
    )
    _patch_paths(monkeypatch, module, tmp_path)

    handoff = module.build()

    assert "invalid completed_at" not in handoff
    assert "**task pool warnings" not in handoff


def test_extract_keep_block_warns_when_existing_handoff_cannot_be_read(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_generate_handoff()
    handoff = tmp_path / "handoff_latest.md"
    handoff.write_text("<!-- KEEP -->\nmanual note\n<!-- /KEEP -->", encoding="utf-8")
    original_read_text = Path.read_text

    def fail_read_text(path: Path, *args, **kwargs):
        if path == handoff:
            raise OSError("permission denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    keep = module._extract_keep_block(handoff)

    captured = capsys.readouterr()
    assert keep == ""
    assert "[generate_handoff] WARN handoff read failed" in captured.err
    assert "KEEP block not preserved" in captured.err
    assert "permission denied" in captured.err
