from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "backfill_feed_audience.py"
    spec = importlib.util.spec_from_file_location("backfill_feed_audience", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _research_row(article_id: str = "mile_rewrite") -> dict:
    return {
        "id": article_id,
        "title": "一般題目",
        "content": "正文比較 QLIKE 與 GARCH。",
        "description": "",
        "audience": "general",
        "category": "general",
        "status": "published",
        "tags": ["一般讀者", "GARCH", "風險"],
        "details": {"experiment_refs": ["K3001"]},
    }


def _plan() -> dict:
    return {
        "schema_version": 1,
        "task_id": "content_audience_test",
        "corrections": [
            {
                "id": "mile_rewrite",
                "expected_audience": "research",
                "disposition": "rewrite_general",
                "experiment_refs": ["K3001", "K3002"],
            },
            {
                "id": "mile_member",
                "expected_audience": "member_qa",
                "disposition": "type_correction",
                "experiment_refs": ["K3003"],
            },
        ],
    }


def _member_row() -> dict:
    return {
        "id": "mile_member",
        "title": "會員提問",
        "content": "K3003 的 bootstrap 與 GARCH 結果。",
        "audience": "general",
        "category": "general",
        "status": "published",
        "tags": ["一般讀者", "會員"],
        "details": {"content_type": "member_qa", "experiment_refs": ["K3003"]},
    }


def test_reviewed_apply_normalizes_metadata_and_marks_rewrite_gap() -> None:
    mod = _load_module()
    feed = [_research_row(), _member_row()]
    changed = mod.apply_reviewed_corrections(
        feed,
        _plan(),
        applied_at="2026-07-15T06:00:00+00:00",
    )
    assert changed == ["mile_rewrite", "mile_member"]

    research = feed[0]
    assert research["audience"] == "research"
    assert research["category"] == "milestone"
    assert research["tags"][0] == "研究"
    assert "一般讀者" not in research["tags"]
    assert research["details"]["content_type"] == "research_article"
    assert research["details"]["experiment_refs"] == ["K3001", "K3002"]
    marker = research["details"]["audience_correction"]
    assert marker["requires_general_rewrite"] is True
    assert marker["previous_audience"] == "general"
    assert marker["corrected_audience"] == "research"

    member = feed[1]
    assert member["audience"] == "member_qa"
    assert member["category"] == "member_qa"
    assert member["details"]["content_type"] == "member_qa"
    assert member["tags"][0] == "會員提問"


def test_daily_type_correction_is_supported_and_normalized(tmp_path: Path) -> None:
    mod = _load_module()
    feed = [
        {
            "id": "mile_daily",
            "title": "每日策略建議",
            "content": "GARCH、VaR 與 Sharpe 每日模板。",
            "audience": "general",
            "category": "general",
            "status": "published",
            "tags": ["一般讀者", "每日建議"],
            "details": {},
        }
    ]
    plan = {
        "schema_version": 1,
        "task_id": "content_audience_test",
        "corrections": [
            {
                "id": "mile_daily",
                "expected_audience": "daily",
                "disposition": "type_correction",
                "experiment_refs": [],
            }
        ],
    }

    plan_path = tmp_path / "daily-plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    assert mod.load_review_plan(plan_path) == plan
    changed = mod.apply_reviewed_corrections(
        feed, plan, applied_at="2026-07-15T06:00:00+00:00"
    )
    assert changed == ["mile_daily"]
    assert feed[0]["audience"] == "daily"
    assert feed[0]["category"] == "general"
    assert feed[0]["tags"][0] == "每日建議"
    assert feed[0]["details"]["content_type"] == "daily_update"


def test_apply_is_idempotent_after_first_correction() -> None:
    mod = _load_module()
    feed = [_research_row(), _member_row()]
    first = mod.apply_reviewed_corrections(
        feed, _plan(), applied_at="2026-07-15T06:00:00+00:00"
    )
    snapshot = json.dumps(feed, ensure_ascii=False, sort_keys=True)
    second = mod.apply_reviewed_corrections(
        feed, _plan(), applied_at="2026-07-15T07:00:00+00:00"
    )
    assert first == ["mile_rewrite", "mile_member"]
    assert second == []
    assert json.dumps(feed, ensure_ascii=False, sort_keys=True) == snapshot


def test_unreviewed_current_mismatch_fails_closed() -> None:
    mod = _load_module()
    feed = [_research_row(), _member_row(), _research_row("mile_unreviewed")]
    with pytest.raises(ValueError, match="unreviewed audience mismatch"):
        mod.validate_plan_against_feed(feed, _plan())


def test_rewrite_task_materialization_is_idempotent(tmp_path: Path) -> None:
    mod = _load_module()
    feed = [_research_row(), _member_row()]
    mod.apply_reviewed_corrections(
        feed, _plan(), applied_at="2026-07-15T06:00:00+00:00"
    )
    feed_by_id = {row["id"]: row for row in feed}
    tasks = tmp_path / "next_tasks.json"
    tasks.write_text("[]\n", encoding="utf-8")

    changes = mod.reconcile_rewrite_tasks(
        tasks,
        feed_by_id,
        _plan(),
        created_at="2026-07-15T06:00:00+00:00",
    )
    assert changes == {
        "created": ["K3001_article_general_audience_rewrite_rewrite"],
        "superseded": [],
        "conflicts": [],
    }
    rows = json.loads(tasks.read_text(encoding="utf-8"))
    assert len(rows) == 1
    assert rows[0]["task_type"] == "daily_article"
    assert rows[0]["source"] == "audience_correction_backfill"
    assert rows[0]["experiment_refs"] == ["K3001", "K3002"]
    assert rows[0]["k_id"] == "K3001"
    assert rows[0]["experiment_id"] == "K3002"
    assert "sanitize_applied=0" in rows[0]["description"]

    assert mod.reconcile_rewrite_tasks(
        tasks,
        feed_by_id,
        _plan(),
        created_at="2026-07-15T07:00:00+00:00",
    ) == {"created": [], "superseded": [], "conflicts": []}
    assert len(json.loads(tasks.read_text(encoding="utf-8"))) == 1

    feed_path = tmp_path / "feed.json"
    plan_path = tmp_path / "plan.json"
    feed_path.write_text(json.dumps(feed, ensure_ascii=False), encoding="utf-8")
    plan_path.write_text(json.dumps(_plan(), ensure_ascii=False), encoding="utf-8")
    dry_run = mod.run(
        feed_path=feed_path,
        tasks_path=tasks,
        plan_path=plan_path,
        apply=False,
        enqueue_rewrites=True,
    )
    assert dry_run["would_correct"] == 0
    assert dry_run["would_enqueue_rewrites"] == 0
    assert dry_run["would_supersede_rewrites"] == 0
    assert dry_run["rewrite_task_conflicts"] == []


def test_existing_general_coverage_removes_rewrite_need_and_supersedes_pending(
    tmp_path: Path,
) -> None:
    mod = _load_module()
    feed = [
        _research_row(),
        _member_row(),
        {
            "id": "mile_other_general",
            "title": "另一篇真正的一般版",
            "content": "白話內容",
            "audience": "general",
            "category": "general",
            "status": "published",
            "tags": ["一般讀者"],
            "details": {"experiment_refs": ["K3001", "K3002"]},
        },
    ]
    mod.apply_reviewed_corrections(
        feed, _plan(), applied_at="2026-07-15T06:00:00+00:00"
    )
    marker = feed[0]["details"]["audience_correction"]
    assert marker["requires_general_rewrite"] is False
    assert marker["uncovered_experiment_refs"] == []

    task_id = "K3001_article_general_audience_rewrite_rewrite"
    tasks = tmp_path / "next_tasks.json"
    tasks.write_text(
        json.dumps(
            [
                {
                    "id": task_id,
                    "title": "now redundant",
                    "priority": 3,
                    "status": "pending",
                    "task_type": "daily_article",
                    "source": "audience_correction_backfill",
                }
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    changes = mod.reconcile_rewrite_tasks(
        tasks,
        {row["id"]: row for row in feed},
        _plan(),
        created_at="2026-07-15T07:00:00+00:00",
    )
    assert changes == {"created": [], "superseded": [task_id], "conflicts": []}
    stored = json.loads(tasks.read_text(encoding="utf-8"))[0]
    assert stored["status"] == "superseded"
    assert stored["status_history"][-1]["to"] == "superseded"
