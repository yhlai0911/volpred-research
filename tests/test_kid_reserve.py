from __future__ import annotations

import concurrent.futures
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "kid_reserve.py"
SPEC = importlib.util.spec_from_file_location("kid_reserve", MODULE_PATH)
kid_reserve = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(kid_reserve)


def test_reserve_uses_registry_and_legacy_sources(tmp_path, monkeypatch) -> None:
    root = tmp_path
    (root / "experiments" / "k100").mkdir(parents=True)
    (root / ".claude" / "worktrees" / "agent-a" / "experiments" / "k101").mkdir(parents=True)
    next_tasks = root / "storage" / "next_tasks.json"
    next_tasks.parent.mkdir(parents=True)
    next_tasks.write_text(
        json.dumps(
            [
                {"id": "K102_article_general"},
                {"k_id": "K103"},
                {"description": "claimed K104 in brief"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    registry = root / "storage" / "ops" / "k_id_registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "last_k_id": 105,
                "reservations": [{"k_id": "K106", "number": 106}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(kid_reserve, "_scan_git_log_k_ids", lambda *_args, **_kwargs: {107})

    record = kid_reserve.reserve_k_id(
        claimed_by="pytest",
        topic="biodiversity crash-risk topic",
        root=root,
        registry_path=registry,
        next_tasks_path=next_tasks,
    )

    assert record["k_id"] == "K108"
    saved = json.loads(registry.read_text(encoding="utf-8"))
    assert saved["last_k_id"] == 108
    assert saved["reservations"][-1]["topic_hash"]
    assert saved["reservations"][-1]["source_max"] == 107


def test_reserve_honors_minimum_floor(tmp_path, monkeypatch) -> None:
    root = tmp_path
    registry = root / "storage" / "ops" / "k_id_registry.json"
    next_tasks = root / "storage" / "next_tasks.json"
    next_tasks.parent.mkdir(parents=True)
    next_tasks.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(kid_reserve, "_scan_git_log_k_ids", lambda *_args, **_kwargs: set())

    first = kid_reserve.reserve_k_id(
        claimed_by="pytest",
        root=root,
        registry_path=registry,
        next_tasks_path=next_tasks,
        minimum=1302,
    )
    second = kid_reserve.reserve_k_id(
        claimed_by="pytest",
        root=root,
        registry_path=registry,
        next_tasks_path=next_tasks,
        minimum=1302,
    )

    assert first["k_id"] == "K1302"
    assert first["source_max"] == 1301
    assert second["k_id"] == "K1303"


def test_reserve_cli_is_process_atomic(tmp_path) -> None:
    root = tmp_path
    registry = root / "storage" / "ops" / "k_id_registry.json"
    next_tasks = root / "storage" / "next_tasks.json"
    next_tasks.parent.mkdir(parents=True)
    next_tasks.write_text("[]", encoding="utf-8")

    def reserve(i: int) -> str:
        result = subprocess.run(
            [
                sys.executable,
                str(MODULE_PATH),
                "reserve",
                "--owner",
                f"worker-{i}",
                "--topic",
                f"topic-{i}",
                "--root",
                str(root),
                "--registry",
                str(registry),
                "--next-tasks",
                str(next_tasks),
                "--git-log-limit",
                "0",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)["k_id"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(reserve, range(8)))

    assert len(ids) == 8
    assert len(set(ids)) == 8
    assert sorted(int(k[1:]) for k in ids) == list(range(1, 9))
    saved = json.loads(registry.read_text(encoding="utf-8"))
    assert len(saved["reservations"]) == 8


def test_corrupt_registry_fails_closed(tmp_path) -> None:
    registry = tmp_path / "storage" / "ops" / "k_id_registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text("{bad json", encoding="utf-8")

    with pytest.raises(ValueError, match="registry unreadable"):
        kid_reserve.reserve_k_id(
            claimed_by="pytest",
            root=tmp_path,
            registry_path=registry,
            git_log_limit=0,
        )
