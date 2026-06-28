from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_backfill_module():
    module_path = ROOT / "scripts" / "backfill_work_log_from_commits.py"
    spec = importlib.util.spec_from_file_location("backfill_work_log_from_commits", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_classify_codex_commit_subject_patterns():
    module = _load_backfill_module()

    cases = [
        ("[codex] complete K1556 macro cojump proxy", ("experiment", "K1556")),
        ("[codex] draft K1406 DCA vs lump sum article", ("daily_article", "K1406")),
        ("[codex] publish daily digest for 2026-06-28", ("daily_digest", None)),
        ("[codex] journal discovery adds variance-risk backlog", ("governance", None)),
        ("[codex] update error.log with release guardrail", ("governance", None)),
        ("[codex] annotate supervisor health process races", ("platform_ops", None)),
    ]

    for subject, expected in cases:
        assert module.classify(subject) == expected


def test_build_entry_records_commit_metadata_and_clean_summary():
    module = _load_backfill_module()
    row = {
        "sha": "abcdef1234567890",
        "ts": "2026-06-28T10:30:00+00:00",
        "subject": "[codex] complete K1556 macro cojump proxy",
    }

    entry = module.build_entry(row)

    assert entry["timestamp"] == row["ts"]
    assert entry["task_type"] == "experiment"
    assert entry["task_id"] == "codex-commit-abcdef123"
    assert entry["summary"] == "complete K1556 macro cojump proxy"
    assert entry["commit"] == row["sha"]
    assert entry["owner"] == "codex"
    assert entry["k_id"] == "K1556"
    assert entry["backfill_source"] == "scripts/backfill_work_log_from_commits.py"
    assert "backfilled_at" in entry
