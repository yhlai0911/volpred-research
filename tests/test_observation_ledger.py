"""Tests for volpred.ops.observation_ledger (WS-F5, refactor_plan_ops_master_2026_07).

Design principle 5: every observation window carries a deadline + action-on-expiry
at creation time; permanent-observational items are the explicit, ruling-backed
exception. The module is the single schema/validation owner — the CLI
(`volpred ops observation`) and the dreaming detector both go through it.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from volpred.ops import observation_ledger as obs

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


def _storage(tmp_path: Path) -> str:
    s = tmp_path / "storage"
    (s / "ops").mkdir(parents=True)
    return str(s)


def test_observing_item_requires_deadline(tmp_path):
    storage = _storage(tmp_path)
    with pytest.raises(ValueError, match="deadline"):
        obs.add_item(storage, item_id="x", what="w", action_on_expiry="a")


def test_observing_item_requires_action_on_expiry(tmp_path):
    storage = _storage(tmp_path)
    with pytest.raises(ValueError, match="action_on_expiry"):
        obs.add_item(storage, item_id="x", what="w", deadline=NOW.isoformat())


def test_permanent_item_forbids_deadline_and_requires_ruling_note(tmp_path):
    storage = _storage(tmp_path)
    with pytest.raises(ValueError, match="deadline"):
        obs.add_item(
            storage, item_id="p", what="w", status=obs.STATUS_PERMANENT,
            deadline=NOW.isoformat(), note="ruling",
        )
    with pytest.raises(ValueError, match="ruling"):
        obs.add_item(storage, item_id="p", what="w", status=obs.STATUS_PERMANENT)
    item = obs.add_item(
        storage, item_id="p", what="w", status=obs.STATUS_PERMANENT, note="gate ruling ref"
    )
    assert item["status"] == "permanent"
    assert item["deadline"] is None


def test_duplicate_id_rejected(tmp_path):
    storage = _storage(tmp_path)
    obs.add_item(storage, item_id="dup", what="w", deadline=NOW.isoformat(), action_on_expiry="a")
    with pytest.raises(ValueError, match="already exists"):
        obs.add_item(storage, item_id="dup", what="w2", deadline=NOW.isoformat(), action_on_expiry="a")


def test_overdue_includes_past_deadline_and_malformed_but_not_future_or_permanent(tmp_path):
    storage = _storage(tmp_path)
    obs.add_item(storage, item_id="past", what="w", deadline=(NOW - timedelta(days=1)).isoformat(),
                 action_on_expiry="a", now=NOW - timedelta(days=5))
    obs.add_item(storage, item_id="future", what="w", deadline=(NOW + timedelta(days=1)).isoformat(),
                 action_on_expiry="a", now=NOW)
    obs.add_item(storage, item_id="perm", what="w", status=obs.STATUS_PERMANENT, note="ruling", now=NOW)
    # malformed observing row (only possible by editing the JSON around the CLI)
    ledger = obs.load_ledger(storage)
    ledger["items"].append({"id": "limbo", "what": "w", "status": "observing",
                            "deadline": "not-a-date", "action_on_expiry": "a"})
    obs.save_ledger(storage, ledger)

    overdue_ids = {i["id"] for i in obs.overdue_items(storage, now=NOW)}
    assert overdue_ids == {"past", "limbo"}


def test_resolve_closes_item(tmp_path):
    storage = _storage(tmp_path)
    obs.add_item(storage, item_id="r", what="w", deadline=(NOW - timedelta(days=1)).isoformat(),
                 action_on_expiry="a", now=NOW - timedelta(days=3))
    item = obs.resolve_item(storage, "r", resolution="did the thing", now=NOW)
    assert item["status"] == "decided"
    assert item["resolution"] == "did the thing"
    assert obs.overdue_items(storage, now=NOW) == []
    with pytest.raises(ValueError, match="not found"):
        obs.resolve_item(storage, "missing", resolution="x")


def test_extend_requires_reason_and_keeps_audit_trail(tmp_path):
    storage = _storage(tmp_path)
    old_deadline = (NOW - timedelta(days=1)).isoformat()
    new_deadline = (NOW + timedelta(days=7)).isoformat()
    obs.add_item(storage, item_id="e", what="w", deadline=old_deadline,
                 action_on_expiry="a", now=NOW - timedelta(days=3))
    with pytest.raises(ValueError, match="reason"):
        obs.extend_deadline(storage, "e", deadline=new_deadline, reason="  ")
    item = obs.extend_deadline(storage, "e", deadline=new_deadline, reason="acceptance blocked on data", now=NOW)
    assert item["deadline"] == new_deadline
    assert item["extensions"][0]["from"] == old_deadline
    assert item["extensions"][0]["reason"] == "acceptance blocked on data"
    assert obs.overdue_items(storage, now=NOW) == []
    # permanent/decided items cannot be extended
    obs.resolve_item(storage, "e", resolution="done", now=NOW)
    with pytest.raises(ValueError, match="only observing"):
        obs.extend_deadline(storage, "e", deadline=new_deadline, reason="r")


def test_ledger_file_shape_matches_spec(tmp_path):
    """Spec fields {id, what, started_at, deadline, action_on_expiry, status}
    are all present on disk for every item."""
    storage = _storage(tmp_path)
    obs.add_item(storage, item_id="shape", what="w", deadline=(NOW + timedelta(days=1)).isoformat(),
                 action_on_expiry="a", now=NOW)
    raw = json.loads((Path(storage) / "ops" / "observation_ledger.json").read_text(encoding="utf-8"))
    assert raw["schema"] == obs.SCHEMA
    item = raw["items"][0]
    for field in ("id", "what", "started_at", "deadline", "action_on_expiry", "status"):
        assert field in item
