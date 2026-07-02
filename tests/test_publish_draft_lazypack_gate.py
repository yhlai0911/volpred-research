"""Tests for the 懶人包 (lazypack) publish gate in publish_draft.py.

Boss hard requirement (2026-06-04, re-raised 2026-06-30 at 12% coverage): every
general-audience reader article must append a 懶人包圖組 (cheat-sheet infographic
SET) at the end. The detection layer (content_quality lazypack coverage) only
WARNED, so this gate enforces it deterministically at the publish chokepoint.

See .claude/rules/publishing.md §4 + lazypack-infographic skill.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from publish_draft import check_lazypack_gate  # noqa: E402

PASS = 0
BLOCK = 6

_LAZYPACK_SECTION = (
    "## 懶人包圖組\n\n"
    "![概念](https://supabase.test/article-images/k1_concept.png)\n\n"
    "![結果](https://supabase.test/article-images/k1_results.png)\n"
)


def test_general_with_lazypack_section_passes():
    body = "# 標題\n\n正文…\n\n" + _LAZYPACK_SECTION
    assert check_lazypack_gate(body, "general", bypass=False) == PASS


def test_general_without_any_lazypack_blocks():
    body = "# 標題\n\n正文…\n\n![圖](https://x/a.png)\n\n## 結論\n收尾。\n"
    assert check_lazypack_gate(body, "general", bypass=False) == BLOCK


def test_general_lazypack_heading_but_no_image_blocks():
    # Heading present but no image after it → empty/placeholder section, must block.
    body = "# 標題\n\n![圖](https://x/a.png)\n\n## 懶人包圖組\n\n（待補圖）\n"
    assert check_lazypack_gate(body, "general", bypass=False) == BLOCK


def test_general_bare_prose_mention_blocks():
    # The word 懶人包 in prose (not a heading) does NOT satisfy the gate.
    body = "# 標題\n\n這篇沒有懶人包，只是順口提到而已。\n\n![圖](https://x/a.png)\n"
    assert check_lazypack_gate(body, "general", bypass=False) == BLOCK


def test_bypass_flag_passes_even_when_missing():
    body = "# 標題\n\n正文，無懶人包。\n"
    assert check_lazypack_gate(body, "general", bypass=True) == PASS


def test_research_audience_exempt():
    body = "# 研究標題\n\n專業內容，無懶人包。\n"
    assert check_lazypack_gate(body, "research", bypass=False) == PASS


def test_member_qa_audience_exempt():
    body = "# 會員問答\n\n回答，無懶人包。\n"
    assert check_lazypack_gate(body, "member_qa", bypass=False) == PASS


def test_image_before_heading_does_not_count():
    # An image that appears BEFORE the 懶人包 heading must not satisfy it.
    body = (
        "# 標題\n\n![前置圖](https://x/a.png)\n\n## 懶人包圖組\n\n（文字，無圖）\n"
    )
    assert check_lazypack_gate(body, "general", bypass=False) == BLOCK


def test_fail_open_on_gate_malfunction():
    # A non-str body makes the internal regex raise TypeError → fail-open (PASS),
    # per no-silent-fallback.md + dedup-gate-audit.md (never over-block on error).
    assert check_lazypack_gate(None, "general", bypass=False) == PASS  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2026-07-02 async pipeline (error_log 15:15 #4): enforcement moved to the
# reader-visible boundary — draft/scheduled pass without the section (render
# runs on compute_queue; release gate holds the flip), published still blocks.
# ---------------------------------------------------------------------------

_NO_LZ_BODY = "# 標題\n\n正文，無懶人包。\n"


def test_draft_status_defers_lazypack_to_async(capsys):
    assert check_lazypack_gate(_NO_LZ_BODY, "general", bypass=False,
                               status="draft") == PASS
    out = capsys.readouterr().out
    assert "lazypack_async_render.py enqueue" in out


def test_scheduled_status_defers_lazypack_to_async():
    assert check_lazypack_gate(_NO_LZ_BODY, "general", bypass=False,
                               status="scheduled") == PASS


def test_published_status_still_blocks():
    assert check_lazypack_gate(_NO_LZ_BODY, "general", bypass=False,
                               status="published") == BLOCK


def test_default_status_is_published_enforce():
    # Callers that do not pass status must get the SAFE default (enforce) —
    # a silently-relaxed default would reopen the 12%-coverage hole.
    assert check_lazypack_gate(_NO_LZ_BODY, "general", bypass=False) == BLOCK


def test_draft_with_lazypack_still_passes_quietly(capsys):
    body = "# 標題\n\n正文…\n\n" + _LAZYPACK_SECTION
    assert check_lazypack_gate(body, "general", bypass=False, status="draft") == PASS
    assert "lazypack_async_render" not in capsys.readouterr().out


def test_lazypack_required_at_boundary_semantics():
    from volpred.publisher.publisher import lazypack_required_at

    assert lazypack_required_at("published") is True
    assert lazypack_required_at(None) is True          # safe default
    assert lazypack_required_at(" Published ") is True
    assert lazypack_required_at("draft") is False
    assert lazypack_required_at("scheduled") is False
