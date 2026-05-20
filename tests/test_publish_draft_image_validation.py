"""Tests for HTTPS image-URL enforcement in publish_draft.py (2026-05-08).

Background (P2 platform_ops, user-reported via volpred.zeabur.app/reports/
mile_53983530): agent-written drafts shipped feed.json articles with image
markdown using LOCAL relative paths (`![](experiments/k547/foo.png)`) instead
of canonical Supabase HTTPS URLs. Frontend resolved these against Supabase
Storage → 404 broken images on 101 articles. Bulk fix repaired 60 + 2
unrecoverable; this module enforces the HTTPS contract at publish time so
the agent-level inconsistency cannot recur.

Fix strategy (Option B, auto-upload over fail-loud-only):
    - Detect every `![alt](path)` ref + `image_url` field in body / frontmatter
    - https://… and http://… → pass-through
    - Relative path → resolve (ROOT/path); upload via charts.upload_chart;
      replace path with returned HTTPS URL (cache so dup refs upload once)
    - Local file missing → FAIL with actionable error message

Tests cover the 7 cases mandated in the platform_ops brief:
    1. clean HTTPS only — pass-through unchanged
    2. mixed HTTPS + relative — only relative uploaded
    3. all relative — all auto-uploaded + replaced
    4. missing local file — raises FileNotFoundError with actionable message
    5. image_url field same treatment (frontmatter scalar, not just body)
    6. apply_update() path — same treatment (regression vs --update mode)
    7. cache: same path 3× in body → upload once
"""
from __future__ import annotations

import json
import struct
import sys
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from publish_draft import (  # noqa: E402
    apply_update,
    main,
    normalize_image_paths,
    normalize_image_url_field,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_png(path: Path) -> Path:
    """Write a minimal valid 1x1 PNG to `path`. No matplotlib dep needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Smallest valid PNG: signature + IHDR + IDAT + IEND
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    raw = b"\x00\x00"  # filter byte + 1 grey pixel
    idat = zlib.compress(raw)
    png = sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    path.write_bytes(png)
    return path


class _FakeUploader:
    """Records calls; returns deterministic HTTPS URL per source filename."""

    def __init__(self, base: str = "https://supabase.test/storage/v1/object/public/article-images"):
        self.base = base
        self.calls: list[str] = []

    def __call__(self, local_path: str) -> str:
        self.calls.append(local_path)
        return f"{self.base}/{Path(local_path).name}"


# ---------------------------------------------------------------------------
# Case 1 — clean HTTPS only: pass-through unchanged
# ---------------------------------------------------------------------------


def test_normalize_passthrough_https_only(tmp_path):
    body = (
        "## 結論\n\n"
        "![chart](https://supabase.test/article-images/clean.png)\n"
        "![other](https://example.com/x.png)\n"
    )
    uploader = _FakeUploader()
    out, uploads = normalize_image_paths(body, tmp_path, uploader=uploader)
    assert out == body
    assert uploads == []
    assert uploader.calls == []


def test_normalize_passthrough_http_too(tmp_path):
    """http:// (not just https://) also passes through untouched."""
    body = "![x](http://example.com/img.png)"
    uploader = _FakeUploader()
    out, uploads = normalize_image_paths(body, tmp_path, uploader=uploader)
    assert out == body
    assert uploads == []


# ---------------------------------------------------------------------------
# Case 2 — mixed HTTPS + relative: only relative uploaded
# ---------------------------------------------------------------------------


def test_normalize_mixed_only_relative_uploaded(tmp_path):
    png = _make_png(tmp_path / "experiments" / "k001" / "chart.png")
    body = (
        "![already_uploaded](https://supabase.test/article-images/k000.png)\n"
        "![local](experiments/k001/chart.png)\n"
        "![also_https](https://example.com/y.png)\n"
    )
    uploader = _FakeUploader()
    out, uploads = normalize_image_paths(body, tmp_path, uploader=uploader)

    # https URLs untouched
    assert "https://supabase.test/article-images/k000.png" in out
    assert "https://example.com/y.png" in out
    # local replaced with uploaded URL
    assert "experiments/k001/chart.png" not in out
    assert "https://supabase.test/storage/v1/object/public/article-images/chart.png" in out
    assert uploads == ["experiments/k001/chart.png"]
    # Only the local path was uploaded (str(absolute_path) passed in)
    assert len(uploader.calls) == 1
    assert uploader.calls[0].endswith("chart.png")


# ---------------------------------------------------------------------------
# Case 3 — all relative: all auto-uploaded + replaced
# ---------------------------------------------------------------------------


def test_normalize_all_relative_uploaded(tmp_path):
    a = _make_png(tmp_path / "experiments" / "k002" / "a.png")
    b = _make_png(tmp_path / "experiments" / "k002" / "b.png")
    body = (
        "![chart_a](experiments/k002/a.png)\n"
        "![chart_b](experiments/k002/b.png)\n"
    )
    uploader = _FakeUploader()
    out, uploads = normalize_image_paths(body, tmp_path, uploader=uploader)

    assert "experiments/k002/a.png" not in out
    assert "experiments/k002/b.png" not in out
    assert out.count("supabase.test/storage/v1/object/public/article-images/") == 2
    assert "/a.png" in out and "/b.png" in out
    assert sorted(uploads) == ["experiments/k002/a.png", "experiments/k002/b.png"]
    assert len(uploader.calls) == 2


# ---------------------------------------------------------------------------
# Case 4 — missing local file: actionable error
# ---------------------------------------------------------------------------


def test_normalize_missing_file_raises_with_actionable_message(tmp_path):
    body = "![chart](experiments/k999/missing.png)"
    uploader = _FakeUploader()
    with pytest.raises(FileNotFoundError) as exc_info:
        normalize_image_paths(body, tmp_path, uploader=uploader)
    msg = str(exc_info.value)
    # Error message must include the failed path verbatim and a hint
    assert "experiments/k999/missing.png" in msg
    assert "Aborting publish" in msg
    assert "Upload" in msg or "fix" in msg
    # No upload was attempted for the missing file
    assert uploader.calls == []


# ---------------------------------------------------------------------------
# Case 5 — image_url field (frontmatter scalar) gets same treatment
# ---------------------------------------------------------------------------


def test_normalize_image_url_field_passthrough_https(tmp_path):
    uploader = _FakeUploader()
    out = normalize_image_url_field(
        "https://supabase.test/article-images/x.png", tmp_path, uploader=uploader
    )
    assert out == "https://supabase.test/article-images/x.png"
    assert uploader.calls == []


def test_normalize_image_url_field_local_uploaded(tmp_path):
    png = _make_png(tmp_path / "experiments" / "k003" / "feature.png")
    uploader = _FakeUploader()
    out = normalize_image_url_field(
        "experiments/k003/feature.png", tmp_path, uploader=uploader
    )
    assert out.startswith("https://")
    assert out.endswith("/feature.png")
    assert len(uploader.calls) == 1


def test_normalize_image_url_field_missing_raises(tmp_path):
    uploader = _FakeUploader()
    with pytest.raises(FileNotFoundError) as exc_info:
        normalize_image_url_field(
            "experiments/k999/missing.png", tmp_path, uploader=uploader
        )
    assert "experiments/k999/missing.png" in str(exc_info.value)


def test_normalize_image_url_field_empty_passthrough(tmp_path):
    uploader = _FakeUploader()
    assert normalize_image_url_field("", tmp_path, uploader=uploader) == ""
    assert uploader.calls == []


# ---------------------------------------------------------------------------
# Case 6 — apply_update path enforcement (--update mode regression)
# ---------------------------------------------------------------------------


def _stage_feed(tmp_path: Path, mile_id: str, **art_overrides) -> Path:
    feed_dir = tmp_path / "storage" / "reports"
    feed_dir.mkdir(parents=True, exist_ok=True)
    feed_path = feed_dir / "feed.json"
    art = {
        "id": mile_id,
        "title": "Test article",
        "audience": "research",
        "phase": "robustness",
        "tags": ["paper-9"],
        "status": "published",
        "content": "Old content.",
        "description": "Old description snippet.",
        "details": {"experiment_refs": ["K100"]},
    }
    art.update(art_overrides)
    feed_path.write_text(
        json.dumps([art], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return feed_path


def _write_draft(tmp_path: Path, body: str, fm: dict | None = None) -> Path:
    p = tmp_path / "draft.md"
    if fm:
        fm_lines = []
        for k, v in fm.items():
            fm_lines.append(f"{k}: {v}")
        p.write_text("---\n" + "\n".join(fm_lines) + "\n---\n" + body, encoding="utf-8")
    else:
        p.write_text(body, encoding="utf-8")
    return p


def _make_args(draft_path: Path, mile_id: str, uploader, **overrides):
    base = dict(
        draft_path=str(draft_path),
        update=mile_id,
        update_action="image_path_test",
        update_summary="Test summary.",
        update_title=None,
        update_description=None,
        no_update_description=False,
        audience=None,
        no_sanitize=False,
        no_image_gate=False,
        dry_run=False,
        sync_supabase=False,
        _image_uploader=uploader,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_apply_update_uploads_local_image_paths(tmp_path, monkeypatch):
    """--update mode auto-uploads relative refs and persists HTTPS URLs."""
    mile_id = "mile_test_update"
    feed_path = _stage_feed(tmp_path, mile_id)
    a = _make_png(tmp_path / "experiments" / "k200" / "a.png")
    b = _make_png(tmp_path / "experiments" / "k200" / "b.png")

    body = (
        "## 結論\n\n"
        "First paragraph for description extraction here.\n\n"
        "![chart_a](experiments/k200/a.png)\n"
        "![chart_b](experiments/k200/b.png)\n"
    )
    draft = _write_draft(tmp_path, body)

    import publish_draft
    monkeypatch.setattr(publish_draft, "ROOT", tmp_path)

    uploader = _FakeUploader()
    args = _make_args(draft, mile_id, uploader)
    rc = apply_update(args)
    assert rc == 0

    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    new_content = feed[0]["content"]
    assert "experiments/k200/a.png" not in new_content
    assert "experiments/k200/b.png" not in new_content
    assert new_content.count("supabase.test") == 2
    assert len(uploader.calls) == 2


def test_apply_update_missing_image_fails_with_code(tmp_path, monkeypatch):
    """--update mode FAILS publish with rc=6 when local PNG is gone."""
    mile_id = "mile_test_missing"
    _stage_feed(tmp_path, mile_id)
    # Only create one of the two referenced files
    _make_png(tmp_path / "experiments" / "k201" / "a.png")

    body = (
        "Body paragraph.\n\n"
        "![ok](experiments/k201/a.png)\n"
        "![broken](experiments/k201/b.png)\n"
    )
    draft = _write_draft(tmp_path, body)

    import publish_draft
    monkeypatch.setattr(publish_draft, "ROOT", tmp_path)

    uploader = _FakeUploader()
    args = _make_args(draft, mile_id, uploader)
    rc = apply_update(args)
    # Per 2026-05-08 review MED-3: assert rc==6 specifically to prove failure
    # is the missing-image-path gate, not e.g. the image-count gate (rc=5).
    assert rc == 6, f"expected rc=6 (missing local image), got rc={rc}"


def test_apply_update_image_url_frontmatter_field(tmp_path, monkeypatch):
    """frontmatter image_url: relative → uploaded; persisted on art.image_url."""
    mile_id = "mile_test_imgurl"
    feed_path = _stage_feed(tmp_path, mile_id)
    _make_png(tmp_path / "experiments" / "k202" / "feature.png")
    _make_png(tmp_path / "experiments" / "k202" / "body.png")

    body = (
        "Body paragraph.\n\n"
        "![chart](experiments/k202/body.png)\n"
        "![chart2](https://supabase.test/article-images/extra.png)\n"
    )
    draft = _write_draft(
        tmp_path,
        body,
        fm={"image_url": "experiments/k202/feature.png"},
    )

    import publish_draft
    monkeypatch.setattr(publish_draft, "ROOT", tmp_path)

    uploader = _FakeUploader()
    args = _make_args(draft, mile_id, uploader)
    rc = apply_update(args)
    assert rc == 0

    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    assert feed[0]["image_url"].startswith("https://")
    assert feed[0]["image_url"].endswith("/feature.png")
    # Two distinct uploads (feature + body image), https stays
    assert len(uploader.calls) == 2


# ---------------------------------------------------------------------------
# Case 7 — cache: same path appearing 3× → upload once
# ---------------------------------------------------------------------------


def test_normalize_caches_repeated_path(tmp_path):
    _make_png(tmp_path / "experiments" / "k300" / "shared.png")
    body = (
        "![first](experiments/k300/shared.png)\n"
        "More text.\n"
        "![second](experiments/k300/shared.png)\n"
        "Even more.\n"
        "![third](experiments/k300/shared.png)\n"
    )
    uploader = _FakeUploader()
    out, uploads = normalize_image_paths(body, tmp_path, uploader=uploader)

    # All three rewritten
    assert "experiments/k300/shared.png" not in out
    assert out.count("/shared.png") == 3  # Three URL embeds (same URL repeated)
    # Upload called exactly ONCE despite 3 references
    assert len(uploader.calls) == 1
    # Returned uploads list dedupes
    assert uploads == ["experiments/k300/shared.png"]


def test_normalize_image_url_field_shares_cache_with_body(tmp_path):
    """image_url + body ref to same file → upload once (shared cache)."""
    _make_png(tmp_path / "experiments" / "k301" / "shared.png")

    body = "![chart](experiments/k301/shared.png)\n"
    uploader = _FakeUploader()
    cache: dict[str, str] = {}

    new_body, _ = normalize_image_paths(
        body, tmp_path, uploader=uploader, cache=cache
    )
    new_url = normalize_image_url_field(
        "experiments/k301/shared.png", tmp_path, uploader=uploader, cache=cache,
    )
    # Body and image_url field point to same URL
    assert new_url in new_body
    # Single upload only
    assert len(uploader.calls) == 1


# ---------------------------------------------------------------------------
# Bonus: --no-image-gate bypass also skips the upload step (coherent behaviour)
# ---------------------------------------------------------------------------


def test_apply_update_no_image_gate_bypasses_upload(tmp_path, monkeypatch):
    """--no-image-gate skips upload, allowing legacy text-only or
    deliberately-broken drafts to pass (mirrors existing image-count bypass)."""
    mile_id = "mile_test_bypass"
    feed_path = _stage_feed(tmp_path, mile_id)

    # Body has a relative path that does NOT exist on disk.
    body = "Some text only.\n\n![ghost](experiments/k404/missing.png)\n"
    draft = _write_draft(tmp_path, body)

    import publish_draft
    monkeypatch.setattr(publish_draft, "ROOT", tmp_path)

    uploader = _FakeUploader()
    args = _make_args(draft, mile_id, uploader, no_image_gate=True)
    rc = apply_update(args)
    # Bypassed: upload skipped, gate skipped, write succeeds
    assert rc == 0
    assert uploader.calls == []  # No upload attempted
    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    assert "experiments/k404/missing.png" in feed[0]["content"]
