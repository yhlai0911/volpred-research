"""Tests for description sync logic in publish_draft.py --update mode.

Background (2026-05-08, K703 mile_6c2bd99e edge case):
    Update mode previously wrote `art["content"]` only, leaving the
    separate `art["description"]` field stale. Some surfaces (frontend
    list views, Supabase row search, social share previews) render
    `description` as the article snippet — so an updated article would
    keep showing the OLD description body. Per CLAUDE.md "永遠修流程，
    不修資料" the publisher script must keep description in sync, not a
    manual per-article patch.

Resolution priority (first non-empty wins):
    1. --no-update-description flag  → preserve old description
    2. --update-description "<text>" → CLI override
    3. frontmatter `description: ""` → frontmatter override
    4. Default                        → first paragraph of new content (≤200 ch)

Test surface:
    - extract_description: paragraph extraction, length cap, link strip,
      heading skip, blockquote handling, image-only line skip, emphasis strip
    - apply_update: default extraction, CLI override, preserve flag,
      frontmatter override, single-article JSON parity (storage/reports/<id>.json)
    - Existing test files (citation_sanitizer / experiment_refs) unaffected
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from publish_draft import (  # noqa: E402
    apply_update,
    extract_description,
    parse_draft,
)


# ---------------------------------------------------------------------------
# extract_description unit tests
# ---------------------------------------------------------------------------


def test_extract_description_first_paragraph():
    body = (
        "## Heading\n\n"
        "這是第一段內容，描述了實驗的背景與動機。\n\n"
        "這是第二段，不應該出現在 description。"
    )
    assert extract_description(body) == "這是第一段內容，描述了實驗的背景與動機。"


def test_extract_description_skips_h1_h2_h3():
    body = (
        "# Big title\n"
        "## Section\n"
        "### Subsection\n\n"
        "Real content paragraph one."
    )
    assert extract_description(body) == "Real content paragraph one."


def test_extract_description_strips_image_refs():
    body = (
        "![chart](https://example.com/a.png)\n\n"
        "First real paragraph here."
    )
    assert extract_description(body) == "First real paragraph here."


def test_extract_description_inline_image_within_paragraph():
    """Inline image within a paragraph is stripped; whitespace collapsed."""
    body = "Paragraph with ![img](url) inline image.\n\nNext."
    # Image stripped → "Paragraph with  inline image." → whitespace collapsed
    assert extract_description(body) == "Paragraph with inline image."


def test_extract_description_replaces_inline_links_with_text():
    body = "See [research_program.md](docs/research_program.md) for details.\n\nNext."
    out = extract_description(body)
    assert "research_program.md" in out
    assert "(docs/" not in out


def test_extract_description_handles_blockquote_tldr():
    body = (
        "> 跑了 19 年的市場資料、做了 82 個實驗，這是一份濃縮總結。\n\n"
        "正文段落開始。"
    )
    out = extract_description(body)
    assert out.startswith("跑了 19 年的市場資料")
    assert ">" not in out


def test_extract_description_skips_metadata_marker():
    body = (
        "[提出: Claude, 執行: Claude]\n\n"
        "正文第一段內容。"
    )
    assert extract_description(body) == "正文第一段內容。"


def test_extract_description_strips_emphasis():
    body = "**Bold text** and *italic* and `code` here.\n\nNext."
    out = extract_description(body)
    assert "Bold text" in out
    assert "**" not in out
    assert "`" not in out


def test_extract_description_truncates_with_ellipsis_when_too_long():
    """Long body without sentence boundaries in window → hard-truncate + …."""
    body = "很長" * 200  # 400 chars, no punctuation
    out = extract_description(body, max_chars=200)
    assert len(out) <= 201  # 200 + ellipsis
    assert out.endswith("…")


def test_extract_description_truncates_at_sentence_boundary():
    """Long body with sentence period inside window → cut at 。."""
    # Build body: 100 chars then 。 at position ~150, then more
    prefix = "起始段落" * 35  # 140 chars
    middle = "重要的句子。" * 5  # contains 。 around chars 140-200
    body = prefix + middle
    out = extract_description(body, max_chars=200)
    assert len(out) <= 200
    # Should cut at 。 boundary
    assert out.endswith("。")


def test_extract_description_empty_body_returns_empty():
    assert extract_description("") == ""
    assert extract_description("   \n\n   ") == ""
    # Image-only body: no paragraph
    assert extract_description("![chart](a.png)\n![chart](b.png)") == ""


def test_extract_description_respects_max_chars_param():
    body = "A" * 500
    out = extract_description(body, max_chars=50)
    assert len(out) <= 51  # 50 + ellipsis


# ---------------------------------------------------------------------------
# apply_update description sync — full integration
# ---------------------------------------------------------------------------


def _stage_feed(tmp_path: Path, mile_id: str, **art_overrides) -> Path:
    """Write a feed.json with one article into tmp_path/storage/reports/."""
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


def _write_draft(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "draft.md"
    p.write_text(body, encoding="utf-8")
    return p


def _make_args(draft_path: Path, mile_id: str, **overrides):
    base = dict(
        draft_path=str(draft_path),
        update=mile_id,
        update_action="test_action",
        update_summary="Test summary.",
        update_title=None,
        update_description=None,
        no_update_description=False,
        audience=None,
        no_sanitize=False,
        no_image_gate=False,
        dry_run=False,
        sync_supabase=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_default_first_paragraph_extraction(tmp_path, monkeypatch):
    """Default behavior: description = first paragraph of new content."""
    mile_id = "mile_default"
    feed_path = _stage_feed(tmp_path, mile_id)

    draft = _write_draft(
        tmp_path,
        "## 結論\n\n"
        "這是更新後的第一段，描述新發現。應該成為新的 description。\n\n"
        "第二段不應該被選中。\n\n"
        "![chart](https://example.com/a.png)\n"
        "![chart](https://example.com/b.png)\n",
    )

    import publish_draft
    monkeypatch.setattr(publish_draft, "ROOT", tmp_path)

    args = _make_args(draft, mile_id)
    rc = apply_update(args)
    assert rc == 0

    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    new_desc = feed[0]["description"]
    assert new_desc == "這是更新後的第一段，描述新發現。應該成為新的 description。"
    assert feed[0]["description"] != "Old description snippet."


def test_update_description_cli_override(tmp_path, monkeypatch):
    """--update-description "<text>" overrides default extraction."""
    mile_id = "mile_cli"
    feed_path = _stage_feed(tmp_path, mile_id)

    draft = _write_draft(
        tmp_path,
        "Auto-extractable first paragraph here.\n\n"
        "![chart](https://example.com/a.png)\n"
        "![chart](https://example.com/b.png)\n",
    )

    import publish_draft
    monkeypatch.setattr(publish_draft, "ROOT", tmp_path)

    custom_desc = "Hand-curated SEO meta description for social share."
    args = _make_args(draft, mile_id, update_description=custom_desc)
    rc = apply_update(args)
    assert rc == 0

    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    assert feed[0]["description"] == custom_desc


def test_no_update_description_preserves_old(tmp_path, monkeypatch):
    """--no-update-description keeps existing description verbatim."""
    mile_id = "mile_preserve"
    feed_path = _stage_feed(
        tmp_path, mile_id, description="Curated SEO meta — do not touch."
    )

    draft = _write_draft(
        tmp_path,
        "Body content was rewritten substantially.\n\n"
        "![chart](https://example.com/a.png)\n"
        "![chart](https://example.com/b.png)\n",
    )

    import publish_draft
    monkeypatch.setattr(publish_draft, "ROOT", tmp_path)

    args = _make_args(draft, mile_id, no_update_description=True)
    rc = apply_update(args)
    assert rc == 0

    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    assert feed[0]["description"] == "Curated SEO meta — do not touch."


def test_frontmatter_description_override(tmp_path, monkeypatch):
    """Frontmatter `description: "..."` overrides default extraction."""
    mile_id = "mile_fm"
    feed_path = _stage_feed(tmp_path, mile_id)

    draft = _write_draft(
        tmp_path,
        "---\n"
        "title: Test\n"
        "audience: research\n"
        "description: \"Frontmatter-specified meta description.\"\n"
        "---\n\n"
        "Body first paragraph that would be auto-extracted otherwise.\n\n"
        "![chart](https://example.com/a.png)\n"
        "![chart](https://example.com/b.png)\n",
    )

    import publish_draft
    monkeypatch.setattr(publish_draft, "ROOT", tmp_path)

    args = _make_args(draft, mile_id)
    rc = apply_update(args)
    assert rc == 0

    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    assert feed[0]["description"] == "Frontmatter-specified meta description."


def test_single_article_json_mirrors_feed(tmp_path, monkeypatch):
    """storage/reports/<mile_id>.json must have same description as feed.json."""
    mile_id = "mile_parity"
    feed_path = _stage_feed(tmp_path, mile_id)

    draft = _write_draft(
        tmp_path,
        "Updated first paragraph for parity check.\n\n"
        "![chart](https://example.com/a.png)\n"
        "![chart](https://example.com/b.png)\n",
    )

    import publish_draft
    monkeypatch.setattr(publish_draft, "ROOT", tmp_path)

    args = _make_args(draft, mile_id)
    rc = apply_update(args)
    assert rc == 0

    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    single_path = tmp_path / "storage" / "reports" / f"{mile_id}.json"
    assert single_path.exists()
    single = json.loads(single_path.read_text(encoding="utf-8"))
    # Both surfaces must have identical description
    assert feed[0]["description"] == single["description"]
    assert feed[0]["content"] == single["content"]
    assert single["description"] == "Updated first paragraph for parity check."


def test_cli_override_beats_frontmatter(tmp_path, monkeypatch):
    """--update-description wins over frontmatter description (priority order)."""
    mile_id = "mile_priority"
    feed_path = _stage_feed(tmp_path, mile_id)

    draft = _write_draft(
        tmp_path,
        "---\n"
        "title: Test\n"
        "description: \"Frontmatter desc — should NOT win.\"\n"
        "---\n\n"
        "Body paragraph.\n\n"
        "![chart](https://example.com/a.png)\n"
        "![chart](https://example.com/b.png)\n",
    )

    import publish_draft
    monkeypatch.setattr(publish_draft, "ROOT", tmp_path)

    args = _make_args(
        draft, mile_id,
        update_description="CLI-specified description wins.",
    )
    rc = apply_update(args)
    assert rc == 0

    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    assert feed[0]["description"] == "CLI-specified description wins."


def test_no_update_description_beats_all(tmp_path, monkeypatch):
    """--no-update-description has highest priority — even with frontmatter."""
    mile_id = "mile_noupdate_wins"
    feed_path = _stage_feed(
        tmp_path, mile_id, description="ORIGINAL preserved."
    )

    draft = _write_draft(
        tmp_path,
        "---\n"
        "title: Test\n"
        "description: \"Frontmatter desc — ignored due to --no-update-description.\"\n"
        "---\n\n"
        "Body paragraph that would normally be extracted.\n\n"
        "![chart](https://example.com/a.png)\n"
        "![chart](https://example.com/b.png)\n",
    )

    import publish_draft
    monkeypatch.setattr(publish_draft, "ROOT", tmp_path)

    args = _make_args(draft, mile_id, no_update_description=True)
    rc = apply_update(args)
    assert rc == 0

    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    assert feed[0]["description"] == "ORIGINAL preserved."


def test_history_records_description_change(tmp_path, monkeypatch):
    """errata.update_history entry includes description_changed + description_source."""
    mile_id = "mile_history"
    feed_path = _stage_feed(tmp_path, mile_id)

    draft = _write_draft(
        tmp_path,
        "Brand new first paragraph.\n\n"
        "![chart](https://example.com/a.png)\n"
        "![chart](https://example.com/b.png)\n",
    )

    import publish_draft
    monkeypatch.setattr(publish_draft, "ROOT", tmp_path)

    args = _make_args(draft, mile_id)
    rc = apply_update(args)
    assert rc == 0

    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    history = feed[0]["errata"]["update_history"]
    assert len(history) == 1
    entry = history[0]
    assert entry["description_changed"] is True
    assert entry["description_source"] == "auto (first paragraph)"


def test_update_can_clear_content_audit_flag(tmp_path, monkeypatch):
    """Explicit update flag clears stale content_audit_flagged after a fix."""
    mile_id = "mile_flagged"
    feed_path = _stage_feed(tmp_path, mile_id, content_audit_flagged=True)

    draft = _write_draft(
        tmp_path,
        "Corrected first paragraph.\n\n"
        "![chart](https://example.com/a.png)\n"
        "![chart](https://example.com/b.png)\n",
    )

    import publish_draft
    monkeypatch.setattr(publish_draft, "ROOT", tmp_path)

    args = _make_args(draft, mile_id, clear_content_audit_flag=True)
    rc = apply_update(args)
    assert rc == 0

    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    assert "content_audit_flagged" not in feed[0]
    history = feed[0]["errata"]["update_history"]
    assert history[-1]["content_audit_flag_cleared"] is True

    single_path = tmp_path / "storage" / "reports" / f"{mile_id}.json"
    single = json.loads(single_path.read_text(encoding="utf-8"))
    assert "content_audit_flagged" not in single


def test_parse_draft_extracts_description_from_frontmatter(tmp_path):
    """parse_draft surfaces frontmatter description field."""
    draft = tmp_path / "draft.md"
    draft.write_text(
        "---\n"
        "title: T\n"
        "audience: research\n"
        "description: \"Snippet for SEO.\"\n"
        "---\n\n"
        "Body.\n",
        encoding="utf-8",
    )
    info = parse_draft(draft)
    assert info["description"] == "Snippet for SEO."


def test_parse_draft_missing_description_returns_empty_string(tmp_path):
    """parse_draft handles absent description field as empty string."""
    draft = tmp_path / "draft.md"
    draft.write_text(
        "---\ntitle: T\naudience: research\n---\n\nBody.\n",
        encoding="utf-8",
    )
    info = parse_draft(draft)
    assert info["description"] == ""
