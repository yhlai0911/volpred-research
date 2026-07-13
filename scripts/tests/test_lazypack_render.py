"""Regression tests for the deterministic, data-bound lazypack renderer."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import lazypack_render as lr  # noqa: E402


def _write_evidence(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "evidence.json"
    path.write_text(
        json.dumps({
            "window": {"start": "2025-01-01", "end": "2025-12-31", "days": 252},
            "result": {"return": 0.1234, "volatility": 0.4567, "names": 6},
            "claim": "描述性統計，不是投資建議",
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _binding(path: str, kind: str, **fmt) -> dict:
    return {"source": "main", "path": path, "format": {"kind": kind, **fmt}}


def _base_plan(tmp_path: Path, *, long_title: bool = False) -> dict:
    evidence, digest = _write_evidence(tmp_path)
    title = (
        "這是一個刻意拉長的繁體中文標題用來確認確定性排版器會先換行再縮字而且所有文字仍完整留在標題區域之內"
        "不會被右側畫布裁掉也不會向下壓到副標題"
        if long_title else "把題材熱度和實際成果分開看"
    )
    common_text = {
        "kind": "text",
        "heading": "先看證據",
        "body": [
            {
                "template": "共同窗口從 {start} 到 {end}",
                "bindings": {
                    "start": _binding("window.start", "date"),
                    "end": _binding("window.end", "date"),
                },
            },
            "所有讀者可見數字都由 JSON 欄位解出，不由自由文字猜測。",
        ],
    }
    return {
        "schema_version": 1,
        "title": "VolPred 懶人包",
        "subtitle": "同一份資料、同一套口徑",
        "evidence": {
            "main": {
                "path": str(evidence),
                "sha256": digest,
                "label": "測試 evidence.json",
            }
        },
        "panels": [
            {
                "name": "1_concept",
                "info": "concept",
                "style": "professional",
                "title": title,
                "alt": "概念框架",
                "sources": ["main"],
                "blocks": [
                    common_text,
                    {
                        "kind": "text",
                        "heading": "再看限制",
                        "body": ["不同欄位互相矛盾時，要追問哪個更接近真實成果。"],
                    },
                    {
                        "kind": "text",
                        "heading": "最後才下結論",
                        "body": ["描述性結果只能回答樣本內發生什麼，不能保證未來。"],
                    },
                ],
            },
            {
                "name": "2_method",
                "info": "method",
                "style": "editorial",
                "title": "固定窗口與計算口徑",
                "alt": "方法與口徑",
                "sources": ["main"],
                "blocks": [
                    common_text,
                    {
                        "kind": "text",
                        "heading": "樣本",
                        "body": [{
                            "template": "共同交易日共 {days} 天",
                            "bindings": {"days": _binding("window.days", "integer")},
                        }],
                    },
                    {
                        "kind": "text",
                        "heading": "界線",
                        "body": [{
                            "template": "{claim}",
                            "bindings": {"claim": _binding("claim", "text")},
                        }],
                    },
                ],
            },
            {
                "name": "3_results",
                "info": "results",
                "style": "bento-grid",
                "title": "結果只回答樣本內的差異",
                "alt": "主要結果",
                "sources": ["main"],
                "blocks": [
                    {
                        "kind": "metric",
                        "label": "期間報酬",
                        "value": _binding("result.return", "percent", digits=1, show_plus=True),
                        "note": "依共同窗口複利",
                    },
                    {
                        "kind": "metric",
                        "label": "年化波動",
                        "value": _binding("result.volatility", "percent", digits=1),
                    },
                    {
                        "kind": "metric",
                        "label": "納入標的",
                        "value": _binding("result.names", "integer", suffix=" 檔"),
                    },
                    {
                        "kind": "text",
                        "heading": "判讀",
                        "body": ["報酬與風險要放在同一頁看，不能只挑較亮眼的一邊。"],
                    },
                ],
            },
            {
                "name": "4_takeaway",
                "info": "takeaway",
                "style": "scientific",
                "title": "一句話結論與研究邊界",
                "alt": "結論與限制",
                "sources": ["main"],
                "blocks": [
                    {
                        "kind": "metric",
                        "label": "觀察標的",
                        "value": _binding("result.names", "integer", suffix=" 檔"),
                    },
                    {
                        "kind": "text",
                        "heading": "結論",
                        "body": ["先確認成果，再談題材純度。"],
                    },
                    {
                        "kind": "text",
                        "heading": "聲明",
                        "body": [{
                            "template": "{claim}",
                            "bindings": {"claim": _binding("claim", "text")},
                        }],
                    },
                ],
            },
        ],
    }


def _write_plan(tmp_path: Path, plan: dict, name: str = "plan.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("field", ["schema_version", "title", "evidence", "panels"])
def test_missing_root_field_raises_with_field_name(tmp_path, field):
    plan = _base_plan(tmp_path)
    del plan[field]
    with pytest.raises(lr.PlanValidationError, match=field):
        lr.validate_plan(plan)


@pytest.mark.parametrize(
    "field", ["name", "info", "style", "title", "alt", "sources", "blocks"],
)
def test_missing_panel_field_raises_with_exact_location(tmp_path, field):
    plan = _base_plan(tmp_path)
    del plan["panels"][0][field]
    with pytest.raises(lr.PlanValidationError, match=rf"panels\[0\].{field}"):
        lr.validate_plan(plan)


def test_missing_evidence_path_raises_in_binding_resolution(tmp_path):
    plan = _base_plan(tmp_path)
    plan["panels"][2]["blocks"][0]["value"]["path"] = "result.not_real"
    path = _write_plan(tmp_path, plan)
    document, evidence = lr.load_plan(path)
    with pytest.raises(lr.EvidenceBindingError, match="result.not_real"):
        lr._resolve_panels(document, evidence)


def test_hash_mismatch_fails_before_render(tmp_path):
    plan = _base_plan(tmp_path)
    plan["evidence"]["main"]["sha256"] = "0" * 64
    path = _write_plan(tmp_path, plan)
    with pytest.raises(lr.PlanValidationError, match="hash mismatch"):
        lr.render_plan(path, tmp_path / "out")


def test_path_traversal_and_duplicate_panel_names_are_rejected(tmp_path):
    plan = _base_plan(tmp_path)
    plan["panels"][0]["name"] = "../escape"
    with pytest.raises(lr.PlanValidationError, match="must match"):
        lr.validate_plan(plan)
    plan = _base_plan(tmp_path)
    plan["panels"][1]["name"] = plan["panels"][0]["name"]
    with pytest.raises(lr.PlanValidationError, match="duplicate"):
        lr.validate_plan(plan)


def test_long_traditional_chinese_title_wraps_without_overflow(tmp_path):
    plan = _base_plan(tmp_path, long_title=True)
    path = _write_plan(tmp_path, plan)
    outputs = lr.render_plan(path, tmp_path / "out")
    assert len(outputs) == 4
    for output in outputs:
        with Image.open(output) as image:
            assert image.size == (1600, 1000)
            assert image.format == "PNG"


def test_same_plan_and_evidence_have_identical_pixel_hashes(tmp_path):
    plan = _base_plan(tmp_path)
    path = _write_plan(tmp_path, plan)
    first = lr.render_plan(path, tmp_path / "out_a")
    second = lr.render_plan(path, tmp_path / "out_b")
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in first] == [
        hashlib.sha256(p.read_bytes()).hexdigest() for p in second
    ]


def test_later_text_fit_failure_leaves_no_partial_final_pngs(tmp_path):
    plan = _base_plan(tmp_path)
    plan["panels"][1]["blocks"][0]["body"] = ["極" * 2000]
    path = _write_plan(tmp_path, plan)
    out = tmp_path / "out"
    with pytest.raises(lr.TextFitError):
        lr.render_plan(path, out)
    assert not list(out.glob("*.png"))


def test_renderer_has_no_agentic_or_subprocess_path():
    source = (SCRIPTS / "lazypack_render.py").read_text(encoding="utf-8")
    assert "import subprocess" not in source
    assert "gen_lazypack_codex" not in source
    assert "codex exec" not in source


@pytest.mark.parametrize("article_id", ["mile_b6a46796", "mile_a8d79d6a"])
def test_migrated_acceptance_plans_render_from_empty_directory(tmp_path, article_id):
    plan = ROOT / "storage" / "lazypack_jobs" / article_id / "plan.json"
    document, _ = lr.load_plan(plan)
    outputs = lr.render_plan(plan, tmp_path / article_id)
    assert [p.name for p in outputs] == [f"{p['name']}.png" for p in document["panels"]]
    for output in outputs:
        with Image.open(output) as image:
            assert image.size == (1600, 1000)
            assert image.format == "PNG"
