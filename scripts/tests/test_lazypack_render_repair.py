"""Bounded mechanical self-repair for the deterministic lazypack renderer.

Regression anchor (assign_5195e5ae D1, 2026-07-20): job lazypack-mile_fa098fc8
died permanently because the layout guard raised OVERLAP (metric value 「0.5%」
on its own note, 59% of the smaller box) and the renderer had zero self-repair —
the same plan re-rendered identically forever, so the article stayed stranded
in draft.  ``render_plan`` now retunes (taller canvas, smaller fonts) for at
most ``MAX_REPAIR_ROUNDS`` rounds, pure code, zero LLM calls.

The synthetic plan below reproduces the incident geometry: a ``method`` panel
with nine blocks (one text + eight metrics, one metric carrying a note) lays
out as a 2-column, 5-row grid whose squeezed rows collide the metric value with
its note at the baseline tuning — exactly the mile_fa098fc8 defect class.

Run: uv run --extra dev python -m pytest scripts/tests/test_lazypack_render_repair.py -v
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from matplotlib import font_manager
from PIL import Image, ImageFont

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


def _overlap_plan(tmp_path: Path) -> Path:
    """A plan whose first render round MUST trip OVERLAP (incident geometry)."""
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
                # rows → each row's metric card is short enough that the value
                # area's 38px floor extends into the note area.
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


def test_synthetic_plan_fails_round_zero_with_overlap(tmp_path, cjk_test_font):
    """Without repair rounds the incident plan must still die on OVERLAP.

    This pins the synthetic plan to the defect class it claims to reproduce —
    if a future geometry change makes round 0 pass, the repair test below
    would silently stop exercising the repair path.
    """
    plan = _overlap_plan(tmp_path)
    with pytest.raises(RuntimeError, match="OVERLAP"):
        lr.render_plan(plan, tmp_path / "out0", max_repair_rounds=0)
    assert not list((tmp_path / "out0").glob("*.png"))


def test_repair_rounds_recover_the_overlap_plan(tmp_path, cjk_test_font):
    plan = _overlap_plan(tmp_path)
    paths, report = lr.render_plan_with_report(plan, tmp_path / "out")
    assert [p.name for p in paths] == ["1_concept.png", "2_turnover.png"]
    assert report["repair_rounds_used"] >= 1
    assert report["canvas_height"] > lr.HEIGHT
    # Every failed round must leave an inspectable trace naming the defect.
    assert report["repair_log"], "failed rounds must be logged, never silent"
    assert any("OVERLAP" in v for entry in report["repair_log"]
               for v in entry["violations"])
    for path in paths:
        with Image.open(path) as image:
            assert image.format == "PNG"
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
