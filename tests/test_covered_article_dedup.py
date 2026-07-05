"""Regression: pending `*_article_<audience>` tasks already covered in feed
must be retired as terminal superseded rows so the dispatcher never offers a duplicate.

Root incident (2026-07-01): K1590_article_general created 11:23Z, article
mile_4518e9d8 (audience=general, refs=['K1590']) written 11:30Z (7-min race).
The stale task stayed pending and was still an agentable candidate at 20:08.
"""
from __future__ import annotations

from contextlib import contextmanager
import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "mark_covered_article_tasks.py"
SPEC = importlib.util.spec_from_file_location("mark_covered_article_tasks_module", MODULE_PATH)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def _task(task_id: str, status: str = "pending", **extra) -> dict:
    t = {"id": task_id, "task_type": "daily_article", "status": status}
    t.update(extra)
    return t


def _patch_coverage(monkeypatch, general=None, research=None, mile_maps=None):
    general = {k.upper() for k in (general or [])}
    research = {k.upper() for k in (research or [])}
    monkeypatch.setattr(
        mod,
        "_kids_with_audience_article",
        lambda aud: general if aud == "general" else research,
    )
    mile_maps = mile_maps or {}
    monkeypatch.setattr(mod, "_covering_mile_ids", lambda aud: mile_maps.get(aud, {}))


def test_split_article_task_id():
    assert mod._split_article_task_id("K1590_article_general") == ("K1590", "general")
    assert mod._split_article_task_id("K1509_article_research") == ("K1509", "research")
    # suffixed retry
    assert mod._split_article_task_id("K1157_article_general_v2") == ("K1157", "general")
    # compound k-id
    assert mod._split_article_task_id("K1100g_d9_article_research") == ("K1100G_D9", "research")
    # not an article task
    assert mod._split_article_task_id("experiment_har_gnn") is None
    assert mod._split_article_task_id("paper_review_mile_abc") is None
    # unknown audience
    assert mod._split_article_task_id("K1_article_internal") is None


def test_covered_general_task_is_flagged(monkeypatch):
    _patch_coverage(monkeypatch, general=["K1590"], mile_maps={"general": {"K1590": "mile_4518e9d8"}})
    hits = mod.find_covered([_task("K1590_article_general")])
    assert len(hits) == 1
    assert hits[0]["kid"] == "K1590"
    assert hits[0]["audience"] == "general"
    assert hits[0]["mile_id"] == "mile_4518e9d8"


def test_uncovered_task_is_left_alone(monkeypatch):
    _patch_coverage(monkeypatch, general=["K9999"])
    hits = mod.find_covered([_task("K1590_article_general")])
    assert hits == []


def test_audience_specific_general_does_not_cover_research(monkeypatch):
    # K1590 has a general article but the pending task wants a research article.
    _patch_coverage(monkeypatch, general=["K1590"], research=[])
    hits = mod.find_covered([_task("K1590_article_research")])
    assert hits == []


def test_non_pending_status_is_ignored(monkeypatch):
    _patch_coverage(monkeypatch, general=["K1590"])
    hits = mod.find_covered([_task("K1590_article_general", status="succeeded")])
    assert hits == []


def test_already_blocked_task_is_not_reflagged(monkeypatch):
    _patch_coverage(monkeypatch, general=["K1590"])
    hits = mod.find_covered(
        [_task("K1590_article_general", blocked_reason="deprecated")]
    )
    assert hits == []


def test_non_article_task_ignored(monkeypatch):
    _patch_coverage(monkeypatch, general=["K1590"])
    hits = mod.find_covered([_task("experiment_har_gnn"), _task("paper_body_x")])
    assert hits == []


def test_sweep_apply_marks_covered_task_superseded(monkeypatch):
    _patch_coverage(monkeypatch, general=["K1590"], mile_maps={"general": {"K1590": "mile_4518e9d8"}})
    payload = [_task("K1590_article_general")]

    @contextmanager
    def fake_lock(_name):
        yield

    def fake_load():
        return payload, payload

    def fake_save(_payload, _tasks):
        return None

    monkeypatch.setattr(mod, "shared_state_lock", fake_lock)
    monkeypatch.setattr(mod, "_load", fake_load)
    monkeypatch.setattr(mod, "_save", fake_save)

    result = mod.sweep(apply=True)

    assert result["count"] == 1
    assert payload[0]["status"] == "superseded"
    assert payload[0]["blocked_reason"] == "deprecated"
    assert payload[0]["terminalized_reason"] == "deprecated"
    assert payload[0]["status_history"][-1]["to"] == "superseded"
