"""Tests for frontmatter experiment_refs parsing + merge in publish_draft.py.

Background (2026-05-08, K703 cross-K incident):
    K703 (mile_6c2bd99e) cross-K aggregation article cited 7 source K
    (K703 + K697/K687/K702/K696/K688/K626/K700). Frontmatter listed all 7,
    but `scripts/publish_draft.py` had two bugs:

      1. New-publish path: `refs = [args.kid] if args.kid else info["experiment_refs"]`
         meant `--kid K703` REPLACED frontmatter — only K703 reached
         details.experiment_refs, the other 6 K were silently dropped.
      2. Update path: apply_update parsed frontmatter but never wrote
         experiment_refs to details, so rewrites couldn't extend K
         provenance even when the agent listed new sources.

    Per CLAUDE.md "永遠修流程，不修資料" the fix is to merge --kid +
    frontmatter (new path) and existing details.experiment_refs +
    frontmatter (update path), normalize K-ids to uppercase, and dedupe
    preserving first occurrence.

Test surface:
    - parse_draft inline-list / block-list / single-value / missing forms
      (sanity-check existing parser; covered minimally to prevent regression)
    - _normalize_refs casing + dedupe
    - new-publish merge: --kid + frontmatter (the K703 bug fix)
    - update-mode merge: existing details + frontmatter
    - legacy --kid only path (must remain backwards-compatible)
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from publish_draft import (  # noqa: E402
    _normalize_refs,
    apply_update,
    parse_draft,
)


# ---------------------------------------------------------------------------
# parse_draft sanity (frontmatter forms)
# ---------------------------------------------------------------------------


def _write_draft(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "draft.md"
    p.write_text(body, encoding="utf-8")
    return p


def test_parse_inline_list(tmp_path):
    """`experiment_refs: [K703, K697, K687]` → 3-element list."""
    p = _write_draft(
        tmp_path,
        "---\n"
        "title: K703 cross-K aggregation\n"
        "audience: research\n"
        "experiment_refs: [K703, K697, K687]\n"
        "---\n\n"
        "Body content here.\n",
    )
    info = parse_draft(p)
    assert info["experiment_refs"] == ["K703", "K697", "K687"]


def test_parse_block_list(tmp_path):
    """Multi-line block YAML list form."""
    p = _write_draft(
        tmp_path,
        "---\n"
        "title: Test\n"
        "audience: general\n"
        "experiment_refs:\n"
        "  - K703\n"
        "  - K697\n"
        "  - K687\n"
        "---\n\n"
        "Body.\n",
    )
    info = parse_draft(p)
    assert info["experiment_refs"] == ["K703", "K697", "K687"]


def test_parse_single_value(tmp_path):
    """Single scalar value treated as 1-element list."""
    p = _write_draft(
        tmp_path,
        "---\ntitle: T\naudience: general\nexperiment_refs: K703\n---\n\nBody.\n",
    )
    info = parse_draft(p)
    assert info["experiment_refs"] == ["K703"]


def test_parse_missing_field_returns_empty_list(tmp_path):
    """Field omitted entirely → empty list (not None)."""
    p = _write_draft(
        tmp_path,
        "---\ntitle: T\naudience: general\n---\n\nBody.\n",
    )
    info = parse_draft(p)
    assert info["experiment_refs"] == []


def test_parse_lowercase_normalized_to_uppercase(tmp_path):
    """`k703` in frontmatter normalizes to `K703`."""
    p = _write_draft(
        tmp_path,
        "---\ntitle: T\naudience: general\nexperiment_refs: [k703, k697]\n---\n\nBody.\n",
    )
    info = parse_draft(p)
    assert info["experiment_refs"] == ["K703", "K697"]


# ---------------------------------------------------------------------------
# _normalize_refs unit tests
# ---------------------------------------------------------------------------


def test_normalize_refs_uppercase_kid():
    assert _normalize_refs(["k703", "K697", "k687"]) == ["K703", "K697", "K687"]


def test_normalize_refs_dedupe_preserves_first_occurrence():
    assert _normalize_refs(["K703", "K697", "K703", "K687", "k697"]) == [
        "K703",
        "K697",
        "K687",
    ]


def test_normalize_refs_drops_empty_and_none():
    assert _normalize_refs(["K703", "", None, "  ", "K697"]) == ["K703", "K697"]


def test_normalize_refs_preserves_non_k_strings():
    """Non-K provenance refs (e.g. 'paper-9', 'fred-vix') passed through."""
    assert _normalize_refs(["K703", "paper-9", "K703"]) == ["K703", "paper-9"]


def test_normalize_refs_preserves_kid_suffix():
    """K222b / K1216c suffixes survive normalization."""
    assert _normalize_refs(["k222b", "K1216c", "k222b"]) == ["K222b", "K1216c"]


# ---------------------------------------------------------------------------
# New-publish merge: --kid + frontmatter (the K703 bug fix)
# ---------------------------------------------------------------------------


def test_kid_plus_frontmatter_merges_no_duplicate():
    """--kid K703 + frontmatter [K703, K697, K687] → ['K703','K697','K687']."""
    info_refs = ["K703", "K697", "K687"]
    kid = "K703"
    refs = _normalize_refs(([kid] if kid else []) + info_refs)
    assert refs == ["K703", "K697", "K687"]


def test_kid_only_legacy_path_still_works():
    """--kid K703 with empty frontmatter list → ['K703'] (backwards-compat)."""
    info_refs = []
    kid = "K703"
    refs = _normalize_refs(([kid] if kid else []) + info_refs)
    assert refs == ["K703"]


def test_frontmatter_only_no_kid():
    """No --kid, frontmatter list → list preserved."""
    info_refs = ["K703", "K697"]
    kid = None
    refs = _normalize_refs(([kid] if kid else []) + info_refs)
    assert refs == ["K703", "K697"]


def test_kid_added_to_frontmatter_list_when_not_present():
    """--kid K700 + frontmatter [K703, K697] → ['K700','K703','K697']."""
    info_refs = ["K703", "K697"]
    kid = "K700"
    refs = _normalize_refs(([kid] if kid else []) + info_refs)
    assert refs == ["K700", "K703", "K697"]


def test_kid_lowercase_normalizes():
    """--kid k703 (legacy lowercase) normalizes to K703 in merged output."""
    info_refs = ["K697"]
    kid = "k703"
    refs = _normalize_refs(([kid] if kid else []) + info_refs)
    assert refs == ["K703", "K697"]


# ---------------------------------------------------------------------------
# Update-mode merge: existing details.experiment_refs + frontmatter
# ---------------------------------------------------------------------------


def test_update_mode_merges_frontmatter_into_existing_refs(tmp_path, monkeypatch):
    """K703 article rewrite adds K700 via frontmatter → details merges both."""
    # Stage feed.json with an existing article
    feed_dir = tmp_path / "storage" / "reports"
    feed_dir.mkdir(parents=True)
    feed_path = feed_dir / "feed.json"
    mile_id = "mile_test703"
    feed_path.write_text(
        json.dumps(
            [
                {
                    "id": mile_id,
                    "title": "K703 cross-K aggregation",
                    "audience": "research",
                    "phase": "aggregation",
                    "tags": ["paper-9"],
                    "status": "published",
                    "content": "Old body.\n\n![chart](a.png)\n![chart](b.png)\n",
                    "details": {"experiment_refs": ["K703", "K697"]},
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # Draft adds K687 + K700, keeps K703 (dedupe must not duplicate)
    draft = tmp_path / "draft.md"
    draft.write_text(
        "---\n"
        "title: K703 cross-K aggregation\n"
        "audience: research\n"
        "experiment_refs: [K703, K687, K700]\n"
        "---\n\n"
        "New body content.\n\n"
        "![chart](https://example.com/a.png)\n"
        "![chart](https://example.com/b.png)\n",
        encoding="utf-8",
    )

    # Patch ROOT so apply_update writes into tmp_path
    import publish_draft

    monkeypatch.setattr(publish_draft, "ROOT", tmp_path)

    args = SimpleNamespace(
        draft_path=str(draft),
        update=mile_id,
        update_action="add_k700_provenance",
        update_summary="Adding K687 + K700 source K to provenance.",
        update_title=None,
        audience=None,
        no_sanitize=False,
        no_image_gate=False,
        dry_run=False,
        sync_supabase=False,
    )
    rc = apply_update(args)
    assert rc == 0

    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    refs = feed[0]["details"]["experiment_refs"]
    # Existing wins ordering; frontmatter contributes K687, K700 in that order
    assert refs == ["K703", "K697", "K687", "K700"]


def test_update_mode_no_frontmatter_refs_preserves_existing(tmp_path, monkeypatch):
    """--update with body-only draft (no frontmatter) leaves details.experiment_refs untouched."""
    feed_dir = tmp_path / "storage" / "reports"
    feed_dir.mkdir(parents=True)
    feed_path = feed_dir / "feed.json"
    mile_id = "mile_legacy"
    feed_path.write_text(
        json.dumps(
            [
                {
                    "id": mile_id,
                    "title": "Legacy article",
                    "audience": "research",
                    "phase": "robustness",
                    "tags": [],
                    "status": "published",
                    "content": "Old.",
                    "details": {"experiment_refs": ["K100"]},
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # Body-only draft — no frontmatter at all
    draft = tmp_path / "draft.md"
    draft.write_text(
        "Updated body.\n\n![chart](https://example.com/a.png)\n![chart](https://example.com/b.png)\n",
        encoding="utf-8",
    )

    import publish_draft

    monkeypatch.setattr(publish_draft, "ROOT", tmp_path)

    args = SimpleNamespace(
        draft_path=str(draft),
        update=mile_id,
        update_action="content_fix",
        update_summary="Fix typo.",
        update_title=None,
        audience=None,
        no_sanitize=False,
        no_image_gate=False,
        dry_run=False,
        sync_supabase=False,
    )
    rc = apply_update(args)
    assert rc == 0

    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    refs = feed[0]["details"]["experiment_refs"]
    # Backwards-compat: no frontmatter contribution → existing untouched
    assert refs == ["K100"]
