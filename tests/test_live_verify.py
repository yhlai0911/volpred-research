"""Tests for the post-publish live verify gate (2026-05-19 Three-Strike fix)."""

from __future__ import annotations

import pytest

from volpred.publisher.live_verify import (
    PUBLIC_BASE_URL,
    PUBLIC_PATH_TEMPLATE,
    public_url,
    stamp_verified,
    verify_article_live,
)


def test_public_url_uses_v3_reports_canonical_pattern():
    url = public_url("mile_ba1dc7f8")
    assert url == f"{PUBLIC_BASE_URL}/v3/reports/mile_ba1dc7f8"
    assert "/article/" not in url
    assert PUBLIC_PATH_TEMPLATE == "/v3/reports/{mile_id}"


def test_verify_article_live_returns_true_on_first_200():
    calls = []

    def fake_http(url):
        calls.append(url)
        return 200

    def fake_sleep(_s):
        raise AssertionError("should not sleep on immediate 200")

    ok = verify_article_live(
        "mile_test",
        max_wait_s=60,
        poll_interval_s=10,
        _http_check=fake_http,
        _sleep=fake_sleep,
        _now=lambda: 0.0,
    )
    assert ok is True
    assert len(calls) == 1
    assert calls[0].endswith("/v3/reports/mile_test")


def test_verify_article_live_polls_until_200():
    responses = iter([404, 503, 200])

    def fake_http(_url):
        return next(responses)

    sleeps = []
    times = iter([0.0, 10.0, 20.0, 30.0])

    ok = verify_article_live(
        "mile_test",
        max_wait_s=60,
        poll_interval_s=10,
        _http_check=fake_http,
        _sleep=lambda s: sleeps.append(s),
        _now=lambda: next(times),
    )
    assert ok is True
    assert sleeps == [10, 10]


def test_verify_article_live_returns_false_after_timeout():
    def fake_http(_url):
        return 404

    sleeps = []
    times = iter([0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0])

    ok = verify_article_live(
        "mile_test",
        max_wait_s=30,
        poll_interval_s=10,
        _http_check=fake_http,
        _sleep=lambda s: sleeps.append(s),
        _now=lambda: next(times),
    )
    assert ok is False
    # Should poll a few times then give up at deadline.
    assert len(sleeps) >= 1


def test_verify_article_live_handles_transport_error():
    def fake_http(_url):
        return 0  # signals OSError / URLError fallback path

    times = iter([0.0, 100.0])
    ok = verify_article_live(
        "mile_test",
        max_wait_s=10,
        poll_interval_s=5,
        _http_check=fake_http,
        _sleep=lambda _s: None,
        _now=lambda: next(times),
    )
    assert ok is False


def test_verify_article_live_rejects_empty_id():
    assert verify_article_live("") is False
    assert verify_article_live(None) is False  # type: ignore[arg-type]


def test_stamp_verified_success_sets_iso_timestamp():
    item = {"id": "mile_x"}
    stamp_verified(item, verified=True)
    assert "verified_live_at" in item
    assert "T" in item["verified_live_at"]  # ISO 8601
    assert item.get("live_verify_failed") in (False, None)


def test_stamp_verified_failure_does_not_stamp_timestamp():
    item = {"id": "mile_x"}
    stamp_verified(item, verified=False)
    assert "verified_live_at" not in item
    assert item["live_verify_failed"] is True


def test_stamp_verified_recovery_clears_failure_flag():
    item = {"id": "mile_x", "live_verify_failed": True}
    stamp_verified(item, verified=True)
    assert item["live_verify_failed"] is False
    assert "verified_live_at" in item


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
