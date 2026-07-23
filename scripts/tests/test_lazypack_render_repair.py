"""Bounded mechanical self-repair for the deterministic lazypack renderer.

Regression anchor (assign_5195e5ae D1, 2026-07-20): job lazypack-mile_fa098fc8
died permanently because the layout guard raised OVERLAP (metric value 「0.5%」
on its own note, 59% of the smaller box) and the renderer had zero self-repair —
the same plan re-rendered identically forever, so the article stayed stranded
in draft.  ``render_plan`` now retunes (taller canvas, smaller fonts) for at
most ``MAX_REPAIR_ROUNDS`` rounds, pure code, zero LLM calls.

Two separate properties are anchored here, and keeping them separate is the
point (2026-07-21, CI run 29797353050):

1. The DEFECT is gone — a metric card can never draw its value through its
   note.  Pinned directly on ``_draw_metric_card`` over a sweep of card
   heights: each height must either render without OVERLAP or refuse with
   ``TextFitError``.  Never a silent collision.
2. The REPAIR LOOP works — a defective baseline is retuned, recovered, and
   logged.  Pinned by INJECTING a round-0 fault, not by hoping a plan's
   geometry happens to be defective on this host.

The earlier version of this file fused the two: it asserted that a synthetic
"incident geometry" plan must fail at round 0, then used that failure to drive
the repair loop.  That made the repair coverage a hostage of host font metrics
— and when 77c6eefc54d0 removed the value band's 38px floor (the actual
mile_fa098fc8 bug), the plan stopped being defective at all.  CI went red
asserting the bug still reproduced, which is exactly backwards: the fix landing
should not look like a regression.  A test for a fix must not be written as
"the bug still happens".

Run: uv run --extra dev python -m pytest scripts/tests/test_lazypack_render_repair.py -v
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from matplotlib import font_manager
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import lazypack_render as lr  # noqa: E402


@pytest.fixture
def cjk_test_font(monkeypatch):
    """Same probe as test_lazypack_render.py: real CJK glyphs or fail loud."""
    path = None
    for family in (lr.FONT_FAMILY, "Noto Sans CJK TC", "Noto Sans CJK JP"):
        try:
            candidate = font_manager.findfont(
                font_manager.FontProperties(family=[family]),
                fallback_to_default=False,
            )
        except ValueError:
            continue  # silent-ok: test fixture probes approved CJK font candidates
        probe = ImageFont.truetype(candidate, size=48)
        signatures = {bytes(probe.getmask(char)) for char in "這繁體"}
        if len(signatures) == 3:
            path = candidate
            break
    if path is None:
        pytest.fail("repair tests require a font with real Traditional Chinese glyphs")
    monkeypatch.setattr(lr, "_FONT_PATH", str(path))
    lr._FONT_CACHE.clear()
    yield
    lr._FONT_CACHE.clear()


def _metric(label: str, path: str, note: str | None = None, **fmt) -> dict:
    block = {
        "kind": "metric",
        "label": label,
        "value": {"source": "main", "path": path,
                  "format": {"kind": "percent", "digits": 1, **fmt}},
    }
    if note is not None:
        block["note"] = note
    return block


def _incident_plan(tmp_path: Path) -> Path:
    """The mile_fa098fc8 geometry: 9 blocks in a `method` panel, one with a note.

    Kept as a realistic end-to-end shape, NOT as a guaranteed failure. Whether
    its rows are tight enough to trip a guard depends on the host font's advance
    widths, so nothing here may assert that a round fails — only that if a round
    does fail, it is never with OVERLAP.
    """
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps({
            "grid": {"a": 0.021, "b": 0.104, "c": 0.076, "d": 0.941},
            "low": {"threshold": 0.005, "lo": 0.189, "hi": 0.567, "drop": 0.801},
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    plan = {
        "schema_version": 1,
        "title": "自我修復回歸測試懶人包",
        "evidence": {
            "main": {"path": str(evidence), "sha256": digest,
                     "label": "合成回歸測試 evidence.json"},
        },
        "panels": [
            {
                "name": "1_concept",
                "info": "concept",
                "style": "professional",
                "title": "先確認問題再看數字",
                "alt": "概念框架",
                "sources": ["main"],
                "blocks": [
                    {"kind": "text", "heading": "背景",
                     "body": ["這個面板只是湊足面板數量下限，重點在第二張。"]},
                    {"kind": "text", "heading": "定位",
                     "body": ["第二張面板複製事故幾何：擠扁的卡片讓數值壓到註解。"]},
                ],
            },
            {
                # The incident panel class: method + 9 blocks → 2 columns × 5
                # rows → each row's metric card is short. Under the old 38px
                # value-band floor that shortness became an overlap; the bands
                # are measured now, so it can only become an honest TextFitError.
                "name": "2_turnover",
                "info": "method",
                "style": "editorial",
                "title": "越勤勞賺得越少的換手掃描",
                "alt": "換手掃描",
                "sources": ["main"],
                "blocks": [
                    {"kind": "text", "heading": "掃描方式",
                     "body": ["固定成本假設下，把觸發門檻與傾斜幅度做成網格逐格回測。",
                              "多抓到的反轉次數，最後多半付給了交易成本。"]},
                    _metric("網格最佳點 觸發門檻", "grid.a"),
                    _metric("最佳點 年化換手", "grid.b"),
                    _metric("最佳點 真的動手的日子", "grid.c"),
                    _metric("最佳點 風險調整後分數", "grid.d"),
                    _metric("低門檻情境 觸發門檻", "low.threshold",
                            note="幾乎每兩天就要動一次"),
                    _metric("低門檻情境 年化換手（最低）", "low.lo"),
                    _metric("低門檻情境 年化換手（最高）", "low.hi"),
                    _metric("低門檻情境 分數掉回", "low.drop"),
                ],
            },
        ],
    }
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


@pytest.mark.parametrize("card_height", [120, 150, 180, 210, 260, 320, 400])
def test_metric_card_never_draws_its_value_through_its_note(
    card_height, cjk_test_font,
):
    """The mile_fa098fc8 defect itself: a short card must refuse, not collide.

    This is the direct pin for the fix in 77c6eefc54d0. The old code sized the
    value band as ``max(38, remaining)``; in a short card the honest remainder
    was 2px, the 38px floor won, and the value ran straight through the note.
    Bands are measured and laid out sequentially now, so for EVERY card height
    the outcome must be one of exactly two things — a clean render, or a loud
    ``TextFitError``. A floor that outgrows its container is not a layout.

    Asserting an implication ("if it renders, no OVERLAP") rather than a
    failure ("this height must break") is what makes this hold on every host:
    which heights are tight depends on the font, but "never silently collide"
    does not.
    """
    from lazypack_layout_guard import find_pil_violations, install

    install(collect=False, write_clean=True)
    image = Image.new("RGB", (lr.WIDTH, lr.HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    rect = lr.Rect(60, 60, 420, card_height)
    block = {
        "kind": "metric",
        "label": "低門檻情境 觸發門檻",
        "value": "18.9%",
        "note": "幾乎每兩天就要動一次",
    }
    try:
        lr._draw_metric_card(draw, rect, block, lr.THEMES["editorial"], lr.RenderTuning())
    except lr.TextFitError:  # silent-ok: test — refusing to fit IS the assertion here
        return  # refusing is the correct outcome for a card with no room
    overlaps = [v for v in find_pil_violations(image) if "OVERLAP" in v]
    assert not overlaps, (
        f"metric card {rect.w}x{card_height}px drew colliding ink instead of "
        f"refusing: {overlaps}"
    )


def test_repair_rounds_recover_a_defective_baseline(tmp_path, cjk_test_font, monkeypatch):
    """The repair contract, with the round-0 fault injected rather than hoped for.

    Injecting is what decouples this from host font metrics. The loop's promise
    is 'a defective baseline gets retuned, recovered, and logged' — that promise
    is the same whether the baseline failed because of Noto's advance widths or
    because this test said so.
    """
    real_render_all = lr._render_all_panels

    def fail_baseline_only(document, panels, evidence, tuning):
        if tuning.label == "baseline":
            raise lr.TextFitError("injected round-0 fault: 'X' cannot fit 670x23px at 27pt")
        return real_render_all(document, panels, evidence, tuning)

    monkeypatch.setattr(lr, "_render_all_panels", fail_baseline_only)

    plan = _incident_plan(tmp_path)
    paths, report = lr.render_plan_with_report(plan, tmp_path / "out")

    assert [p.name for p in paths] == ["1_concept.png", "2_turnover.png"]
    assert report["repair_rounds_used"] == 1
    assert report["canvas_height"] > lr.HEIGHT
    # Every failed round must leave an inspectable trace naming the defect.
    assert report["repair_log"], "failed rounds must be logged, never silent"
    assert report["repair_log"][0]["tuning"] == "baseline"
    assert any("injected round-0 fault" in v
               for v in report["repair_log"][0]["violations"])
    for path in paths:
        with Image.open(path) as image:
            assert image.format == "PNG"
            assert image.size == (lr.WIDTH, report["canvas_height"])


def test_incident_plan_renders_and_never_reports_an_overlap(tmp_path, cjk_test_font):
    """End-to-end on the real incident geometry, asserted host-independently.

    The plan must ship. Whether it needs a repair round is the host font's
    business, but no round may ever report OVERLAP — that collision class is
    what 77c6eefc54d0 removed, and its return is the regression worth catching.
    """
    plan = _incident_plan(tmp_path)
    paths, report = lr.render_plan_with_report(plan, tmp_path / "out")

    assert [p.name for p in paths] == ["1_concept.png", "2_turnover.png"]
    overlaps = [v for entry in report["repair_log"] for v in entry["violations"]
                if "OVERLAP" in v]
    assert not overlaps, f"metric value/note collision is back: {overlaps}"
    for path in paths:
        with Image.open(path) as image:
            assert image.size == (lr.WIDTH, report["canvas_height"])


def test_clean_plan_keeps_house_geometry(tmp_path, cjk_test_font):
    """Repair must not engage when the baseline layout is already green."""
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"x": 0.123}) + "\n", encoding="utf-8")
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    plan = {
        "schema_version": 1,
        "title": "乾淨基準",
        "evidence": {"main": {"path": str(evidence), "sha256": digest,
                              "label": "測試 evidence.json"}},
        "panels": [
            {"name": "1_a", "info": "concept", "style": "professional",
             "title": "簡短標題", "alt": "概念", "sources": ["main"],
             "blocks": [{"kind": "text", "heading": "重點",
                         "body": ["一句話就講完的內容。"]}]},
            {"name": "2_b", "info": "results", "style": "scientific",
             "title": "單一數字", "alt": "結果", "sources": ["main"],
             "blocks": [_metric("樣本內報酬", "x")]},
        ],
    }
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    paths, report = lr.render_plan_with_report(path, tmp_path / "out")
    assert report["repair_rounds_used"] == 0
    assert report["canvas_height"] == lr.HEIGHT
    for png in paths:
        with Image.open(png) as image:
            assert image.size == (lr.WIDTH, lr.HEIGHT)
