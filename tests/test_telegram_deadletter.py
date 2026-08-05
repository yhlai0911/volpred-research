"""A Telegram update must outlive the failure that stopped it becoming a task.

2026-08-05: two owner messages (updates 351935633/351935634, 09:41 and 09:42
Taipei) raised `cannot import name 'normalize_task_type_value' from
'volpred.ops.next_tasks'` inside `_handle_update`. The poll loop logged one line
to a file nobody watches, advanced the offset anyway, and moved on. Telegram
never hands a consumed update back. The owner found out by asking, hours later,
whether Telegram still accepted tasks -- nothing in the system would ever have
volunteered it.

The import works from every static entry point and the interleaving could not be
reproduced. That is exactly why the fix does not depend on knowing the cause: a
poison message, an ImportError, a full disk and a Supabase outage all have to end
the same way, with the message still there.

The offset still advances on failure -- a message that always fails must not wedge
the loop, and that part of the old behaviour was correct. What changed is that
advancing the offset is no longer the same as discarding the work.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import telegram_poll as tp  # noqa: E402


def _update(update_id: int, text: str = "do the thing") -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id % 10_000,
            "from": {"id": 7941067569, "first_name": "Ivan"},
            "chat": {"id": 7941067569, "type": "private"},
            "date": 1785894074,
            "text": text,
        },
    }


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Never let this suite touch the real deadletter or canonical storage."""
    monkeypatch.setattr(tp, "DEADLETTER", tmp_path / "telegram_failed_updates.jsonl")
    monkeypatch.setattr(tp, "_log", lambda *a, **k: None)
    monkeypatch.setattr(tp, "guard_canonical_write", lambda *a, **k: None)


def test_a_failed_update_is_parked_not_dropped() -> None:
    """The 2026-08-05 shape: the handler raises, the message must survive."""
    boom = ImportError("cannot import name 'normalize_task_type_value'")
    tp._record_failed_update(_update(351935633, "建立這樣的完整功能"), boom)

    rows = tp._load_deadletter()
    assert len(rows) == 1
    assert rows[0]["update"]["update_id"] == 351935633
    assert rows[0]["attempts"] == 1
    assert "normalize_task_type_value" in rows[0]["last_error"]
    # The text itself must be recoverable -- that is the whole point.
    assert "建立這樣的完整功能" in rows[0]["update"]["message"]["text"]


def test_a_transient_failure_self_heals_on_the_next_pass(monkeypatch) -> None:
    """One poll interval of delay, not a lost message."""
    tp._record_failed_update(_update(1), RuntimeError("transient"))
    assert len(tp._load_deadletter()) == 1

    handled: list[int] = []
    monkeypatch.setattr(tp, "_handle_update", lambda u: handled.append(u["update_id"]))

    assert tp._drain_failed_updates() == 1
    assert handled == [1]
    assert tp._load_deadletter() == [], "a recovered update must leave the queue"


def test_a_still_failing_update_stays_parked_and_counts_attempts(monkeypatch) -> None:
    tp._record_failed_update(_update(2), RuntimeError("still broken"))

    def always_fails(_u):
        raise RuntimeError("still broken")

    monkeypatch.setattr(tp, "_handle_update", always_fails)

    assert tp._drain_failed_updates() == 0
    rows = tp._load_deadletter()
    assert len(rows) == 1, "a failing retry must not delete the message"
    assert rows[0]["attempts"] == 2


def test_a_permanently_stuck_update_escalates_but_is_never_deleted(monkeypatch) -> None:
    """Retrying is hard is not a reason to discard something the owner sent."""
    tp._record_failed_update(_update(3, "urgent thing"), RuntimeError("nope"))
    monkeypatch.setattr(tp, "_handle_update", lambda _u: (_ for _ in ()).throw(RuntimeError("nope")))

    warnings: list[tuple] = []
    monkeypatch.setattr(tp, "warn", lambda tag, msg, **ctx: warnings.append((tag, ctx)))

    for _ in range(tp.DEADLETTER_MAX_ATTEMPTS + 2):
        tp._drain_failed_updates()

    rows = tp._load_deadletter()
    assert len(rows) == 1, "still parked, however many times it failed"
    assert rows[0]["attempts"] >= tp.DEADLETTER_MAX_ATTEMPTS
    stuck = [c for tag, c in warnings if tag == "telegram_deadletter_stuck"]
    assert stuck, "a message stuck past the retry budget must become a visible signal"
    assert stuck[-1]["text"].startswith("urgent thing"), (
        "the escalation must carry what the owner actually said, not just an id"
    )


def test_poll_drains_before_asking_telegram_for_more(monkeypatch) -> None:
    """Owed work is finished before new work is taken on."""
    order: list[str] = []
    monkeypatch.setattr(tp, "_drain_failed_updates", lambda: order.append("drain") or 0)
    monkeypatch.setattr(tp, "load_state", lambda: {"update_offset": 1})

    def fake_api(method, params=None, timeout=None):
        order.append("getUpdates")
        return {"ok": True, "result": []}

    monkeypatch.setattr(tp, "api_call", fake_api)
    monkeypatch.setattr(tp, "_record_poll_success", lambda: None)

    tp.poll_pass(timeout=1)
    assert order == ["drain", "getUpdates"]


def test_a_corrupt_row_never_evicts_its_neighbours(monkeypatch) -> None:
    """One bad line must not take the queue down with it."""
    tp.DEADLETTER.parent.mkdir(parents=True, exist_ok=True)
    tp.DEADLETTER.write_text(
        "{not json\n" + json.dumps({"update": _update(9), "attempts": 1}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(tp, "warn", lambda *a, **k: None)

    rows = tp._load_deadletter()
    assert len(rows) == 2
    assert any(r.get("_raw") == "{not json" for r in rows)

    monkeypatch.setattr(tp, "_handle_update", lambda _u: None)
    assert tp._drain_failed_updates() == 1
    remaining = tp._load_deadletter()
    assert [r.get("_raw") for r in remaining] == ["{not json"], (
        "the unparsable row is kept for a human; the good one drained"
    )
