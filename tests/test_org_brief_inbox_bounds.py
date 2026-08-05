"""A bounded brief must say what it left out.

The brief is written into --append-system-prompt-file at attach and paid for on
every cached turn by every pane at once. On 2026-08-05 the inbox block alone was
104KB (~38k tokens) for platform_eng and 59.5KB for the manager, because every
item was rendered in full -- the same failure as reading feed.json whole, only
applied to the org's own product.

Bounding it is easy. Bounding it *safely* is the part worth testing: a brief
that quietly shows 12 of 85 items is indistinguishable from a brief with 12
items, so a role would finish its shift believing the inbox was drained. Losing
a work item costs far more than the tokens saved, which is why every assertion
below is about the omission being visible, not about the size.

All fixtures build a throwaway org root under tmp_path; canonical storage/org is
never read or written here.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

CORE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "org" / "_core.py"


@pytest.fixture(scope="module")
def core():
    spec = importlib.util.spec_from_file_location("org_core_under_test", CORE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _dept_root(tmp_path: Path, count: int, *, task: str = "工作內容") -> Path:
    root = tmp_path / "org"
    dept = root / "departments" / "widgets"
    (dept / "inbox").mkdir(parents=True)
    (dept / "memory").mkdir()
    (dept / "charter.md").write_text("charter", encoding="utf-8")
    (dept / "journal.md").write_text("journal", encoding="utf-8")
    (dept / "memory" / "notes.md").write_text("notes", encoding="utf-8")
    (root / "policy.md").write_text("policy", encoding="utf-8")
    (root / "registry.json").write_text(
        json.dumps({"departments": {"widgets": {"status": "active", "title": "小工具部"}}}),
        encoding="utf-8",
    )
    for index in range(count):
        (dept / "inbox" / f"item_{index:03d}.json").write_text(
            json.dumps(
                {
                    "id": f"item_{index:03d}",
                    "from": "manager",
                    "kind": "assignment",
                    "priority": "P2",
                    "created_at": f"2026-08-05T00:{index:02d}:00Z",
                    "task": f"{task} {index}",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return root


def test_an_overflowing_inbox_names_the_count_it_left_out(tmp_path, core):
    total = core.INBOX_RENDER_LIMIT_DEPT + 7
    root = _dept_root(tmp_path, total)

    text = core.work_prompt(root, "widgets")

    assert f"另有 {total - core.INBOX_RENDER_LIMIT_DEPT} 件未列出" in text, (
        "a capped inbox that does not announce the cap reads as a drained inbox"
    )
    assert "inbox" in text, "the omitted items must be reachable, not just counted"
    assert str(total) in text, "the header must still report the true item count"


def test_a_short_inbox_is_rendered_whole_with_no_omission_notice(tmp_path, core):
    root = _dept_root(tmp_path, 3)

    text = core.work_prompt(root, "widgets")

    assert "未列出" not in text
    for index in range(3):
        assert f"item_{index:03d}" in text


def test_the_cap_keeps_the_top_priority_not_the_oldest(tmp_path, core):
    """The cap decides what a role sees, so it must not be a clock."""
    root = _dept_root(tmp_path, core.INBOX_RENDER_LIMIT_DEPT + 5)
    late_p1 = root / "departments" / "widgets" / "inbox" / "item_999.json"
    late_p1.write_text(
        json.dumps(
            {
                "id": "item_999",
                "from": "boss",
                "kind": "assignment",
                "priority": "P1",
                "created_at": "2026-08-05T23:59:00Z",
                "task": "最後才到的急件",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    text = core.work_prompt(root, "widgets")

    assert "item_999" in text, "a late P1 must survive the cap that drops early P2s"


def test_a_long_item_is_clipped_and_says_so(core):
    clipped = core.clip_task("字" * 900)

    assert len(clipped) < 900
    assert "截斷" in clipped and "900" in clipped, (
        "a clipped body must be recognisable as clipped, or it reads as the whole item"
    )


def test_a_short_item_is_left_exactly_alone(core):
    assert core.clip_task("短短一句") == "短短一句"


def test_newlines_do_not_break_the_one_line_bullet(core):
    assert "\n" not in core.clip_task("第一行\n第二行\n第三行")
