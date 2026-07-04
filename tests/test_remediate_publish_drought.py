"""Regression gate for the publish-drought auto-remediation ladder.

Boss directive email-12559 (2026-07-03, 「你應該不是建議行動 而是你應該要直接行動」):
the 發文脫班 (publishing_freshness) dead-man switch must DIRECTLY REMEDIATE, not
email the boss a to-do list. These tests assert the ladder in
`scripts/remediate_publish_drought.py`:

  * no-op when the feed is NOT in an active-window drought;
  * on drought → force-release; if release publishes something, does NOT refill;
  * on drought → force-release returns 0 (empty pool / all arc-dup rehashes) →
    refill one emergency reader-facing daily_article for the next dispatcher;
  * if force-release and reader-facing refill both return 0, send a critical alert.
"""
from __future__ import annotations

import fcntl
import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load_remediate_module():
    spec = importlib.util.spec_from_file_location(
        "remediate_publish_drought", SCRIPTS / "remediate_publish_drought.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def mod():
    return _load_remediate_module()


def _patch_freshness(monkeypatch, *, breached: bool, gap: float):
    import volpred.ops.alerts as alerts

    def _fake_state(storage_dir, now):
        return {
            "id": "publishing_freshness",
            "breached": breached,
            "level": "critical" if breached else "info",
            "details": {
                "publish_gap_hours": gap,
                "in_active_window": True,
                "threshold_hours": 6.0,
            },
        }

    monkeypatch.setattr(alerts, "_parse_publishing_freshness_state", _fake_state)


def test_no_op_when_not_in_drought(mod, monkeypatch):
    _patch_freshness(monkeypatch, breached=False, gap=1.2)
    res = mod.remediate(apply=True)
    assert res["attempted"] is False
    assert res["reason"] == "no_drought"


def test_drought_release_success_skips_refill(mod, monkeypatch):
    _patch_freshness(monkeypatch, breached=True, gap=7.5)

    import volpred.ops as ops

    monkeypatch.setattr(
        ops,
        "release_pool_by_settings",
        lambda **kw: {"released_count": 1, "released": [{"id": "mile_x"}]},
    )
    # refill must NOT be called when release published something
    import refill_task_pool

    def _boom(*a, **k):  # pragma: no cover - asserts it is never reached
        raise AssertionError("refill should not run when release succeeded")

    monkeypatch.setattr(refill_task_pool, "refill", _boom)

    res = mod.remediate(apply=True)
    assert res["attempted"] is True
    steps = {s["step"]: s for s in res["steps"]}
    assert steps["force_release"]["released"] == 1
    assert "refill_fresh" not in steps


def test_drought_release_empty_triggers_reader_facing_refill(mod, monkeypatch):
    _patch_freshness(monkeypatch, breached=True, gap=8.1)

    import volpred.ops as ops

    monkeypatch.setattr(
        ops,
        "release_pool_by_settings",
        lambda **kw: {"released_count": 0, "released": []},
    )
    import refill_task_pool

    calls = []

    def fake_refill(target, dry_run=False, **kwargs):
        calls.append({"target": target, "dry_run": dry_run, **kwargs})
        return {
            "added": 1,
            "added_ids": ["K999_article_general"],
            "reason": "ok",
            "reader_facing_only": kwargs.get("reader_facing_only"),
        }

    monkeypatch.setattr(refill_task_pool, "refill", fake_refill)

    res = mod.remediate(apply=True)
    steps = {s["step"]: s for s in res["steps"]}
    assert steps["force_release"]["released"] == 0
    assert steps["refill_reader_facing"]["added"] == 1
    assert steps["refill_reader_facing"]["added_ids"] == ["K999_article_general"]
    assert calls == [
        {
            "target": 1,
            "dry_run": False,
            "reader_facing_only": True,
            "emergency": True,
        }
    ]
    assert "critical_alert" not in steps


def test_drought_release_empty_and_refill_empty_sends_critical_alert(mod, monkeypatch):
    _patch_freshness(monkeypatch, breached=True, gap=8.4)

    import volpred.ops as ops

    monkeypatch.setattr(
        ops,
        "release_pool_by_settings",
        lambda **kw: {"released_count": 0, "released": []},
    )
    import refill_task_pool

    monkeypatch.setattr(
        refill_task_pool,
        "refill",
        lambda *args, **kwargs: {
            "added": 0,
            "added_ids": [],
            "reason": "no_reader_facing_candidates_passing_filter",
            "reader_facing_only": True,
        },
    )

    import volpred.ops.alerts as alerts

    sent = []

    def fake_send_alert(level, title, body, **kwargs):
        sent.append({"level": level, "title": title, "body": body, **kwargs})
        return {
            "sent": True,
            "alert_key": "critical:test",
            "telegram": {"sent": True},
        }

    monkeypatch.setattr(alerts, "send_alert", fake_send_alert)

    res = mod.remediate(apply=True)
    steps = {s["step"]: s for s in res["steps"]}
    assert steps["force_release"]["released"] == 0
    assert steps["refill_reader_facing"]["added"] == 0
    assert steps["critical_alert"]["ok"] is True
    assert res["escalated"] is True
    assert res["reason"] == "force_release_and_reader_facing_refill_empty"
    assert sent and sent[0]["level"] == "critical"
    assert sent[0]["force_send"] is True
    assert "force_release.released: 0" in sent[0]["body"]
    assert "refill_reader_facing.added: 0" in sent[0]["body"]


def test_dry_run_takes_no_action(mod, monkeypatch):
    _patch_freshness(monkeypatch, breached=True, gap=9.0)
    res = mod.remediate(apply=False)
    assert res["attempted"] is True
    assert res["steps"][0]["dry_run"] is True


def test_apply_skips_when_remediation_lock_is_held(mod, monkeypatch, tmp_path: Path):
    _patch_freshness(monkeypatch, breached=True, gap=9.0)
    import volpred.ops as ops

    def _boom_release(**kw):  # pragma: no cover - asserts it is never reached
        raise AssertionError("force release should not run while lock is held")

    monkeypatch.setattr(ops, "release_pool_by_settings", _boom_release)

    lock_path = tmp_path / "ops" / "remediate_publish_drought.lock"
    lock_path.parent.mkdir(parents=True)
    with lock_path.open("a+", encoding="utf-8") as lock_fh:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            res = mod.remediate(apply=True, storage_dir=str(tmp_path))
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)

    assert res["attempted"] is False
    assert res["reason"] == "remediation_already_running"
