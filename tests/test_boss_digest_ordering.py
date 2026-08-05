"""The owner's digest must lead with decisions, not with whatever arrived first.

2026-08-05: the digest rendered 1931 lines from 122 manager-inbox items. Every
one of the 54 P1 reports was in it, and none of them was visible: entries were
listed in filename (= arrival) order, and the 41 department-to-department cc
copies had arrived earliest, so the whole top of the message was org
bookkeeping. The manager read the top of it and reported the boss channel as
carrying "nothing but P3 cc" -- a correct reading of a broken presentation.

The failure mode is worth naming because it survives every "is the data there?"
check: nothing was dropped, nothing was corrupt, no exception was raised. Only
the order was wrong, and order is what makes a 1931-line message readable or
not. So the assertions here are about order and exclusion, not about content.

Everything runs against a tmp_path org root; the canonical storage/org tree is
never read or written by this test.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "org" / "boss_digest.py"
BULLET = re.compile(r"^- \[(P\d)\] \*\*([^*]+)\*\*: (.*)$")


@pytest.fixture(scope="module")
def boss_digest():
    spec = importlib.util.spec_from_file_location("boss_digest_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _org_root(tmp_path: Path, items: list[dict]) -> Path:
    root = tmp_path / "org"
    inbox = root / "manager" / "inbox"
    inbox.mkdir(parents=True)
    (root / "manager" / "outbox" / "proposals").mkdir(parents=True)
    # Filenames carry the timestamp, and sorted() over them is the arrival order
    # the old renderer used. Numbering them here reproduces that order exactly.
    for index, item in enumerate(items):
        (inbox / f"item_{index:04d}.json").write_text(
            json.dumps(item, ensure_ascii=False), encoding="utf-8"
        )
    (root / "registry.json").write_text(
        json.dumps({"departments": {"platform_eng": {"status": "active"}}}),
        encoding="utf-8",
    )
    return root


def _bullets(text: str) -> list[tuple[str, str, str]]:
    return [m.groups() for m in (BULLET.match(line) for line in text.splitlines()) if m]


def test_a_late_p1_outranks_an_early_cc_and_an_early_p3(tmp_path, boss_digest):
    """The exact 2026-08-05 shape: noise first on the clock, decisions last."""
    root = _org_root(tmp_path, [
        {"from": "governance", "kind": "cc", "priority": "P3", "task": "（知會）A → B：…"},
        {"from": "content", "kind": "report", "priority": "P3", "task": "池深 9→10"},
        {"from": "member_success", "kind": "report", "priority": "P1",
         "task": "註冊漏斗斷點"},
    ])

    bullets = _bullets(boss_digest.render(root))

    assert [b[0] for b in bullets] == ["P1", "P3"], (
        "P1 must lead and cc must not appear; got " + repr(bullets)
    )
    assert bullets[0][1] == "member_success"


def test_cc_is_excluded_but_counted_never_silently_dropped(tmp_path, boss_digest):
    root = _org_root(tmp_path, [
        {"from": "a", "kind": "cc", "priority": "P3", "task": "（知會）one"},
        {"from": "b", "kind": "cc", "priority": "P3", "task": "（知會）two"},
        {"from": "c", "kind": "report", "priority": "P2", "task": "real"},
    ])

    text = boss_digest.render(root)

    assert len(_bullets(text)) == 1
    assert "另有 2 則部門間知會" in text, (
        "dropping cc silently would make the digest look complete when it is not"
    )


def test_boss_items_stay_out_of_the_department_section(tmp_path, boss_digest):
    """The owner's own messages are input to the org, not a report back to them."""
    root = _org_root(tmp_path, [
        {"from": "boss", "kind": "assignment", "priority": "P1", "task": "急件"},
        {"from": "research", "kind": "report", "priority": "P1", "task": "K1734"},
    ])

    bullets = _bullets(boss_digest.render(root))

    assert [b[1] for b in bullets] == ["research"]


def test_each_item_is_one_scannable_line(tmp_path, boss_digest):
    """122 untruncated bodies became 1931 lines, which is how the P1s vanished."""
    root = _org_root(tmp_path, [
        {"from": "x", "kind": "report", "priority": "P1", "task": "首行\n" + "詳" * 400},
    ])

    text = boss_digest.render(root)
    bullets = _bullets(text)

    assert len(bullets) == 1
    assert "\n" not in bullets[0][2]
    assert len(bullets[0][2]) <= boss_digest.HEADLINE_CHARS


def test_missing_priority_is_treated_as_lowest_not_as_a_crash(tmp_path, boss_digest):
    """A hand-written item without a priority must not reorder or break the digest."""
    root = _org_root(tmp_path, [
        {"from": "legacy", "kind": "report", "task": "no priority field"},
        {"from": "governance", "kind": "report", "priority": "P1", "task": "裁決"},
    ])

    bullets = _bullets(boss_digest.render(root))

    assert [b[0] for b in bullets] == ["P1", "P3"]
