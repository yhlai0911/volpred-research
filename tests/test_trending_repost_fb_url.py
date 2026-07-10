"""Trending-repost FB comment URL invariants.

Hard rule (2026-05-19 incident):
- FB first-comment link MUST use https://volpred.zeabur.app/v3/reports/<mile_id>
- /article/<mile_id> path returns 404 and is BANNED.

Covers both `fb_comment_link` and `fb_comment_draft` fields in
storage/reports/trending_repost_log.json plus a regex assertion
helper that publisher callers should use before posting.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ALLOWED_URL_RE = re.compile(
    r"^https://volpred\.zeabur\.app/v3/reports/mile_[a-z0-9]+$"
)
BANNED_SUBSTR = "/article/"


def assert_fb_comment_url(url: str) -> None:
    """Publisher entry-point invariant — raise if URL is malformed.

    Use this from any code path that prepares an FB first-comment link.
    """
    if not isinstance(url, str):
        raise TypeError(f"fb comment url must be str, got {type(url).__name__}")
    if BANNED_SUBSTR in url:
        raise ValueError(
            f"banned URL path '/article/' detected (returns 404): {url!r} — "
            "use /v3/reports/<mile_id> instead"
        )
    if not ALLOWED_URL_RE.match(url):
        raise ValueError(
            f"fb comment url does not match {ALLOWED_URL_RE.pattern}: {url!r}"
        )


def _extract_fb_urls_from_log(log_path: Path) -> list[tuple[str, str, str]]:
    """Return (mile_id, field_name, url) rows from an injected FB log fixture.

    The production trending log is gitignored operational state. Unit tests must
    exercise the parser and URL invariant with deterministic input instead of
    treating a missing live file as a passing CI result.
    """
    data = json.loads(log_path.read_text(encoding="utf-8"))
    out: list[tuple[str, str, str]] = []
    for entry in data:
        mile_id = entry.get("mile_id", "<unknown>")
        for field in ("fb_comment_link", "fb_comment_draft"):
            val = entry.get(field)
            if not isinstance(val, str) or not val:
                continue
            # fb_comment_draft is freeform text with URL embedded; extract URL(s)
            for url in re.findall(r"https?://\S+", val):
                # strip trailing punctuation like 」),.
                url = url.rstrip("。」),.、")
                out.append((mile_id, field, url))
    return out


@pytest.fixture
def fb_log_path(tmp_path: Path) -> Path:
    path = tmp_path / "trending_repost_log.json"
    path.write_text(
        json.dumps(
            [
                {
                    "mile_id": "mile_abc123",
                    "fb_comment_link": "https://volpred.zeabur.app/v3/reports/mile_abc123",
                },
                {
                    "mile_id": "mile_def456",
                    "fb_comment_draft": (
                        "完整圖表：https://volpred.zeabur.app/v3/reports/mile_def456。"
                    ),
                },
                {
                    "mile_id": "mile_external",
                    "fb_comment_draft": "來源：https://example.com/reference).",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_extract_fb_urls_from_injected_log(fb_log_path: Path) -> None:
    assert _extract_fb_urls_from_log(fb_log_path) == [
        (
            "mile_abc123",
            "fb_comment_link",
            "https://volpred.zeabur.app/v3/reports/mile_abc123",
        ),
        (
            "mile_def456",
            "fb_comment_draft",
            "https://volpred.zeabur.app/v3/reports/mile_def456",
        ),
        ("mile_external", "fb_comment_draft", "https://example.com/reference"),
    ]


def test_no_banned_article_path_in_log(fb_log_path: Path) -> None:
    bad = [
        (mile_id, field, url)
        for mile_id, field, url in _extract_fb_urls_from_log(fb_log_path)
        if BANNED_SUBSTR in url and "volpred.zeabur.app" in url
    ]
    assert not bad, f"banned /article/ URLs found in log: {bad}"


def test_all_volpred_fb_urls_match_canonical_pattern(fb_log_path: Path) -> None:
    failures: list[tuple[str, str, str]] = []
    for mile_id, field, url in _extract_fb_urls_from_log(fb_log_path):
        if "volpred.zeabur.app" not in url:
            continue
        if not ALLOWED_URL_RE.match(url):
            failures.append((mile_id, field, url))
    assert not failures, (
        f"volpred FB urls not matching {ALLOWED_URL_RE.pattern}: {failures}"
    )


def test_assert_fb_comment_url_accepts_canonical() -> None:
    assert_fb_comment_url("https://volpred.zeabur.app/v3/reports/mile_abc12345")


def test_assert_fb_comment_url_rejects_article_path() -> None:
    with pytest.raises(ValueError, match="banned URL path"):
        assert_fb_comment_url("https://volpred.zeabur.app/article/mile_abc12345")


def test_assert_fb_comment_url_rejects_other_paths() -> None:
    with pytest.raises(ValueError, match="does not match"):
        assert_fb_comment_url("https://volpred.zeabur.app/reports/mile_abc12345")
    with pytest.raises(ValueError, match="does not match"):
        assert_fb_comment_url("https://example.com/v3/reports/mile_abc12345")


def test_assert_fb_comment_url_rejects_non_str() -> None:
    with pytest.raises(TypeError):
        assert_fb_comment_url(None)  # type: ignore[arg-type]
