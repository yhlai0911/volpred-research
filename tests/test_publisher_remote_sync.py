from __future__ import annotations

import gzip
import hashlib
import json
import random
import sys
import types
import urllib.request
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from volpred.ops.alerts import ALERT_RECIPIENT
from volpred.ops.delivery.owned_email import OwnedEmailCommand
from volpred.publisher.publisher import Publisher


def test_sync_feed_to_remote_gzips_large_compressible_feed(
    tmp_path: Path,
    monkeypatch,
):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    feed_path = reports_dir / "feed.json"
    original = b"[" + (b" " * (9 * 1024 * 1024)) + b"]"
    feed_path.write_bytes(original)

    captured: dict[str, object] = {}

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        captured["url"] = req.full_url
        captured["data"] = req.data
        captured["encoding"] = req.get_header("Content-encoding")
        captured["content_type"] = req.get_header("Content-type")
        captured["timeout"] = timeout
        return object()

    monkeypatch.setattr(Publisher, "REMOTE_URL", "https://mirror.example", raising=False)
    monkeypatch.setattr("volpred.mirror_auth.ops_admin_headers", lambda: {"x-test-token": "ok"})
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    Publisher(storage_dir=str(tmp_path))._sync_feed_to_remote()

    assert captured["url"] == "https://mirror.example/api/sync/feed.json"
    assert captured["encoding"] == "gzip"
    assert captured["content_type"] == "application/json"
    payload = captured["data"]
    assert isinstance(payload, bytes)
    assert len(payload) < 8 * 1024 * 1024
    assert gzip.decompress(payload) == original


def test_sync_feed_to_remote_skips_large_incompressible_feed(
    tmp_path: Path,
    monkeypatch,
):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    # Deterministic, high-entropy enough to stay above the 8MB mirror ceiling
    # after gzip. The sync path does not parse the JSON before deciding whether
    # the whole-file mirror PUT is feasible.
    feed_path = reports_dir / "feed.json"
    feed_path.write_bytes(random.Random(42).randbytes(9 * 1024 * 1024))

    calls: list[object] = []

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        calls.append(req)
        return object()

    monkeypatch.setattr(Publisher, "REMOTE_URL", "https://mirror.example", raising=False)
    monkeypatch.setattr("volpred.mirror_auth.ops_admin_headers", lambda: {"x-test-token": "ok"})
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    Publisher(storage_dir=str(tmp_path))._sync_feed_to_remote()

    assert calls == []


def test_sync_report_to_remote_puts_single_article_payload(
    tmp_path: Path,
    monkeypatch,
):
    captured: dict[str, object] = {}

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        captured["url"] = req.full_url
        captured["data"] = req.data
        captured["content_type"] = req.get_header("Content-type")
        captured["timeout"] = timeout
        return object()

    monkeypatch.delenv("VOLPRED_NO_REMOTE_WRITE", raising=False)
    monkeypatch.setattr(Publisher, "REMOTE_URL", "https://mirror.example", raising=False)
    monkeypatch.setattr("volpred.mirror_auth.ops_admin_headers", lambda: {"x-test-token": "ok"})
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    ok = Publisher(storage_dir=str(tmp_path))._sync_report_to_remote(
        "mile_single_sync",
        {
            "id": "mile_single_sync",
            "title": "Single Article",
            "content": "body",
            "status": "published",
            "tags": ["SPY"],
        },
    )

    assert ok is True
    assert captured["url"] == "https://mirror.example/api/sync/reports/mile_single_sync.json"
    assert captured["content_type"] == "application/json"
    payload = captured["data"]
    assert isinstance(payload, bytes)
    decoded = json.loads(payload.decode("utf-8"))
    assert decoded["id"] == "mile_single_sync"
    assert decoded["content"] == "body"


def test_sync_report_to_remote_honors_no_remote_write_guard(
    tmp_path: Path,
    monkeypatch,
):
    calls: list[object] = []

    def fake_urlopen(req: urllib.request.Request, timeout: int):
        calls.append(req)
        return object()

    monkeypatch.setenv("VOLPRED_NO_REMOTE_WRITE", "1")
    monkeypatch.setattr(Publisher, "REMOTE_URL", "https://mirror.example", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    ok = Publisher(storage_dir=str(tmp_path))._sync_report_to_remote(
        "mile_blocked_sync",
        {"id": "mile_blocked_sync", "title": "Blocked"},
    )

    assert ok is False
    assert calls == []


def test_append_to_feed_uses_single_report_sync(
    tmp_path: Path,
    monkeypatch,
):
    # WS-C4: the append path now routes through _mirror_article, which consults
    # _mirror_enabled() BEFORE the PUT (and dead-letters a failure). Arm the
    # mirror so the per-report sync actually runs — the assertion under test is
    # still "single-report sync, never whole-feed sync".
    monkeypatch.delenv("VOLPRED_NO_REMOTE_WRITE", raising=False)
    monkeypatch.setattr(Publisher, "REMOTE_URL", "https://mirror.test", raising=False)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "feed.json").write_text("[]", encoding="utf-8")
    calls: list[tuple[str, str]] = []

    def fail_full_feed_sync(self):
        raise AssertionError("whole-feed sync should not run for single article append")

    def fake_report_sync(self, pub_id: str, item: dict):
        calls.append((pub_id, item["title"]))
        return True

    monkeypatch.setattr(Publisher, "_sync_feed_to_remote", fail_full_feed_sync)
    monkeypatch.setattr(Publisher, "_sync_report_to_remote", fake_report_sync)

    item = {
        "id": "mile_append_single",
        "title": "Append Single",
        "content": "body",
        "description": "excerpt",
        "status": "published",
        "published_at": "2026-06-23T00:00:00+00:00",
        "created_at": "2026-06-23T00:00:00+00:00",
    }

    assert Publisher(storage_dir=str(tmp_path))._append_to_feed(item) == "mile_append_single"
    assert calls == [("mile_append_single", "Append Single")]


def test_article_notification_is_deferred_to_owned_boss_batch(
    tmp_path: Path,
    monkeypatch,
):
    class ForbiddenLegacyNotifier:
        def __init__(self, *args, **kwargs):
            raise AssertionError("automatic article path used direct notifier")

    monkeypatch.setattr(
        "volpred.publisher.email_notifier.EmailNotifier",
        ForbiddenLegacyNotifier,
    )
    pub = Publisher(storage_dir=str(tmp_path))

    result = pub._notify_article_published(
        {"id": "mile_batch", "title": "Batched article"},
        reason="publish_milestone",
    )

    assert result == {
        "article_id": "mile_batch",
        "delivery": "boss_report_4h",
        "coverage": "schedule_anchored_feed_scan",
        "reason": "publish_milestone",
        "status": "deferred",
    }


def test_manual_article_notification_uses_formal_owned_email(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "feed.json").write_text(
        json.dumps(
            [
                {
                    "id": "mile_manual",
                    "title": "Manual article",
                    "description": "Evidence-bound summary",
                    "status": "published",
                }
            ]
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    class ForbiddenLegacyNotifier:
        def __init__(self, *args, **kwargs):
            raise AssertionError("manual article path used direct notifier")

    def fake_dispatch(command, *, storage_dir):
        captured["command"] = command
        captured["storage_dir"] = storage_dir
        return {
            "delivery_owner": "operations_core",
            "effect_status": "delivered",
            "sent": True,
        }

    monkeypatch.setattr(
        "volpred.publisher.email_notifier.EmailNotifier",
        ForbiddenLegacyNotifier,
    )
    monkeypatch.setattr(
        "volpred.ops.delivery.owned_email.dispatch_email_by_current_owner",
        fake_dispatch,
    )
    result = Publisher(storage_dir=str(tmp_path)).send_article_notification(
        "mile_manual"
    )

    command = captured["command"]
    assert command.idempotency_key == (
        "manual-article-notification:mile_manual"
    )
    assert command.title.startswith("[新架構派發]")
    assert command.actor_ref == "manual:article-notification:mile_manual"
    assert captured["storage_dir"] == str(tmp_path)
    assert result["delivery_owner"] == "operations_core"
    assert result["effect_status"] == "delivered"


def test_manual_daily_digest_uses_formal_owned_email(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "feed.json").write_text(
        json.dumps(
            [
                {
                    "id": "mile_digest_a",
                    "title": "Digest A",
                    "description": "First summary",
                    "status": "published",
                    "published_at": "2026-07-30T01:00:00+00:00",
                },
                {
                    "id": "mile_digest_other_day",
                    "title": "Other day",
                    "status": "published",
                    "published_at": "2026-07-29T01:00:00+00:00",
                },
            ]
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    class ForbiddenLegacyNotifier:
        def __init__(self, *args, **kwargs):
            raise AssertionError("manual digest path used direct notifier")

    def fake_dispatch(command, *, storage_dir):
        captured["command"] = command
        captured["storage_dir"] = storage_dir
        return {
            "delivery_owner": "operations_core",
            "effect_status": "delivered",
            "sent": True,
        }

    monkeypatch.setattr(
        "volpred.publisher.email_notifier.EmailNotifier",
        ForbiddenLegacyNotifier,
    )
    monkeypatch.setattr(
        "volpred.ops.delivery.owned_email.dispatch_email_by_current_owner",
        fake_dispatch,
    )
    monkeypatch.setattr(
        "volpred.ops.delivery.owned_email.read_existing_owned_email_request",
        lambda _key: None,
    )

    result = Publisher(storage_dir=str(tmp_path)).send_daily_digest(
        target_date=date(2026, 7, 30)
    )

    command = captured["command"]
    assert command.idempotency_key.startswith(
        "manual-daily-digest:2026-07-30:to-"
    )
    assert command.title == (
        "[新架構派發][VolPred] 2026-07-30 當日發文摘要"
    )
    assert command.actor_ref == "manual:daily-digest:2026-07-30"
    assert "Digest A" in command.text_body
    assert "Other day" not in command.text_body
    assert command.html_body is not None
    assert captured["storage_dir"] == str(tmp_path)
    assert result["date"] == "2026-07-30"
    assert result["count"] == 1
    assert result["article_ids"] == ["mile_digest_a"]
    assert result["delivery_owner"] == "operations_core"
    assert result["effect_status"] == "delivered"


def test_manual_daily_digest_replays_original_snapshot_when_feed_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    feed_path = reports_dir / "feed.json"
    first_article = {
        "id": "mile_digest_original",
        "title": "Original snapshot",
        "description": "Original summary",
        "status": "published",
        "published_at": "2026-07-30T01:00:00+00:00",
    }
    later_article = {
        "id": "mile_digest_later",
        "title": "Later article",
        "description": "Must wait for another owned batch",
        "status": "published",
        "published_at": "2026-07-30T02:00:00+00:00",
    }
    feed_path.write_text(json.dumps([first_article]), encoding="utf-8")
    state: dict[str, object] = {}
    dispatched: list[object] = []

    class Existing:
        def __init__(self, command):
            self.command = command

    def fake_read(_key):
        command = state.get("command")
        return Existing(command) if command is not None else None

    def fake_dispatch(command, *, storage_dir):
        dispatched.append(command)
        state.setdefault("command", command)
        return {
            "delivery_owner": "operations_core",
            "effect_status": "delivered",
            "sent": True,
        }

    monkeypatch.setattr(
        "volpred.ops.delivery.owned_email.read_existing_owned_email_request",
        fake_read,
    )
    monkeypatch.setattr(
        "volpred.ops.delivery.owned_email.dispatch_email_by_current_owner",
        fake_dispatch,
    )

    publisher = Publisher(storage_dir=str(tmp_path))
    first = publisher.send_daily_digest(target_date=date(2026, 7, 30))
    feed_path.write_text(
        json.dumps([first_article, later_article]),
        encoding="utf-8",
    )
    replay = publisher.send_daily_digest(target_date=date(2026, 7, 30))

    assert len(dispatched) == 2
    assert dispatched[1] == dispatched[0]
    assert first["article_ids"] == ["mile_digest_original"]
    assert replay["article_ids"] is None
    assert replay["count"] is None
    assert replay["replayed_existing"] is True
    assert "Later article" not in dispatched[1].text_body


def test_manual_daily_digest_concurrent_materialization_replays_winner(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from volpred.ops.delivery.owned_email import (
        OwnedEmailCommandConflict,
    )

    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "feed.json").write_text(
        json.dumps(
            [
                {
                    "id": "mile_digest_race",
                    "title": "Race-safe snapshot",
                    "description": "Only one immutable winner",
                    "status": "published",
                    "published_at": "2026-07-30T01:00:00+00:00",
                }
            ]
        ),
        encoding="utf-8",
    )
    state: dict[str, object] = {}
    dispatch_count = 0

    class Existing:
        def __init__(self, command):
            self.command = command
            self.request = type(
                "Request",
                (),
                {"request_sha256": "winner-sha256"},
            )()

    def fake_read(_key):
        command = state.get("winner")
        return Existing(command) if command is not None else None

    def fake_dispatch(command, *, storage_dir):
        nonlocal dispatch_count
        dispatch_count += 1
        if dispatch_count == 1:
            state["winner"] = command
            raise OwnedEmailCommandConflict("concurrent winner committed")
        assert command == state["winner"]
        return {
            "delivery_owner": "operations_core",
            "effect_status": "delivered",
            "sent": True,
        }

    monkeypatch.setattr(
        "volpred.ops.delivery.owned_email.read_existing_owned_email_request",
        fake_read,
    )
    monkeypatch.setattr(
        "volpred.ops.delivery.owned_email.dispatch_email_by_current_owner",
        fake_dispatch,
    )

    result = Publisher(storage_dir=str(tmp_path)).send_daily_digest(
        target_date=date(2026, 7, 30)
    )

    assert dispatch_count == 2
    assert result["replayed_existing"] is True
    assert result["durable_request_sha256"] == "winner-sha256"
    assert result["sent"] is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("idempotency_key", "manual-daily-digest:wrong"),
        ("recipient", "wrong-recipient@example.com"),
        ("actor_ref", "manual:daily-digest:wrong-date"),
        ("level", "critical"),
        ("title", "[新架構派發][VolPred] wrong digest"),
    ],
)
def test_manual_daily_digest_rejects_durable_command_identity_drift(
    tmp_path: Path,
    monkeypatch,
    field: str,
    value: str,
) -> None:
    recipient_digest = hashlib.sha256(
        ALERT_RECIPIENT.encode("utf-8")
    ).hexdigest()[:16]
    command = OwnedEmailCommand(
        idempotency_key=(
            "manual-daily-digest:2026-07-30:"
            f"to-{recipient_digest}"
        ),
        level="info",
        title=(
            "[新架構派發][VolPred] "
            "2026-07-30 當日發文摘要"
        ),
        recipient=ALERT_RECIPIENT,
        text_body="immutable",
        html_body="<p>immutable</p>",
        actor_ref="manual:daily-digest:2026-07-30",
    )
    drifted = replace(command, **{field: value})

    class Existing:
        def __init__(self):
            self.command = drifted

    monkeypatch.setattr(
        "volpred.ops.delivery.owned_email.read_existing_owned_email_request",
        lambda _key: Existing(),
    )
    monkeypatch.setattr(
        "volpred.ops.delivery.owned_email.dispatch_email_by_current_owner",
        lambda *_args, **_kwargs: pytest.fail(
            "drifted command reached provider router"
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="durable daily-digest command drift",
    ):
        Publisher(storage_dir=str(tmp_path)).send_daily_digest(
            target_date=date(2026, 7, 30)
        )


def test_unpublish_supabase_sync_failure_is_queued(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "feed.json").write_text(
        json.dumps(
            [
                {
                    "id": "mile_unpublish_fail",
                    "title": "Unpublish failure",
                    "status": "published",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fail_sync_article(*args, **kwargs):
        raise RuntimeError("postgrest down")

    fake_supabase_sync = types.SimpleNamespace(sync_article=fail_sync_article)
    monkeypatch.setitem(sys.modules, "supabase_sync", fake_supabase_sync)
    monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda self: None)

    assert Publisher(storage_dir=str(tmp_path)).unpublish("mile_unpublish_fail") is True

    queue = json.loads((tmp_path / ".failed_supabase_syncs.json").read_text(encoding="utf-8"))
    feed = json.loads((reports_dir / "feed.json").read_text(encoding="utf-8"))
    captured = capsys.readouterr()

    assert queue == ["mile_unpublish_fail"]
    assert feed[0]["status"] == "unpublished"
    assert "Supabase unpublish sync exception for mile_unpublish_fail" in captured.out
    assert "recorded to .failed_supabase_syncs.json" in captured.out


def test_publish_milestone_bad_existing_timestamp_keeps_exact_title_gate(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "feed.json").write_text(
        json.dumps(
            [
                {
                    "id": "mile_bad_timestamp",
                    "title": "Same Title",
                    "status": "published",
                    "published_at": "not-a-date",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)

    result = Publisher(storage_dir=str(tmp_path)).publish_milestone(
        title="Same Title",
        description="新的文章不應穿過 exact-title duplicate gate。",
        phase="research",
        status="draft",
    )

    captured = capsys.readouterr()
    assert result == "mile_bad_timestamp"
    assert "Duplicate title timestamp parse failed" in captured.out
