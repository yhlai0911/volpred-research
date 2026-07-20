"""Regression tests for the deterministic, data-bound lazypack renderer."""
from __future__ import annotations

import copy
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
    """Exercise rendering with a real CJK font available on each test host.

    Production deliberately resolves ``Heiti TC`` with fallback disabled so a
    missing CJK font cannot silently produce tofu.  GitHub's Ubuntu runner gets
    Noto Sans CJK from the workflow; the development Mac uses Heiti TC.  Never
    fall back to DejaVu because its missing-glyph boxes would make layout tests
    pass without exercising Traditional Chinese glyphs.
    """
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
        pytest.fail("render tests require a font with real Traditional Chinese glyphs")
    monkeypatch.setattr(lr, "_FONT_PATH", str(path))
    lr._FONT_CACHE.clear()
    yield
    lr._FONT_CACHE.clear()


def test_font_resolution_probes_every_approved_family_and_never_falls_back(monkeypatch):
    """A host with no CJK font must fail loudly, not draw 豆腐字.

    Naming a single macOS-only family here is what kept CI red on 2026-07-13: the
    Ubuntu runner had Noto CJK installed but the renderer only ever asked for Heiti
    TC. So the contract is now: probe every approved family, each with fallback
    disabled, and raise if none resolve.
    """
    probed = []

    def missing_font(properties, *, fallback_to_default):
        probed.append((properties.get_family(), fallback_to_default))
        raise ValueError("font unavailable")

    monkeypatch.setattr(lr.font_manager, "findfont", missing_font)
    monkeypatch.setattr(lr, "_FONT_PATH", None)
    with pytest.raises(RuntimeError, match="豆腐字"):
        lr._font_path()

    assert [family for family, _ in probed] == [
        [family] for family in lr.FONT_FAMILY_CANDIDATES
    ], "every approved CJK family must be tried"
    assert all(fallback is False for _, fallback in probed), "fallback must stay disabled"


def test_font_resolution_takes_the_first_available_family(monkeypatch):
    """CI has no Heiti TC but does have Noto — that must resolve, not raise."""
    monkeypatch.setattr(lr, "_FONT_PATH", None)

    def only_noto(properties, *, fallback_to_default):
        family = properties.get_family()[0]
        if family != "Noto Sans CJK TC":
            raise ValueError("font unavailable")
        return "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"

    monkeypatch.setattr(lr.font_manager, "findfont", only_noto)
    assert lr._font_path().endswith("NotoSansCJK-Regular.ttc")


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


@pytest.mark.parametrize("version", [True, 1.0, "1"])
def test_schema_version_is_strict_integer(tmp_path, version):
    plan = _base_plan(tmp_path)
    plan["schema_version"] = version
    with pytest.raises(lr.PlanValidationError, match="schema_version"):
        lr.validate_plan(plan)


def test_duplicate_json_keys_fail_loud(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(lr.PlanValidationError, match="duplicate JSON key"):
        lr.load_plan(path)


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


def test_unbound_reader_visible_number_is_rejected(tmp_path):
    plan = _base_plan(tmp_path)
    plan["panels"][0]["blocks"][0]["body"][1] = "這裡偷偷硬寫 12.3%，不應通過。"
    with pytest.raises(lr.PlanValidationError, match="unbound numeric literal"):
        lr.validate_plan(plan)


@pytest.mark.parametrize("literal", ["結果 {12.3%}", "結果 12.3%"])
def test_braces_cannot_hide_unbound_numbers(tmp_path, literal):
    plan = _base_plan(tmp_path)
    plan["panels"][0]["blocks"][0]["body"][1] = literal
    with pytest.raises(lr.PlanValidationError, match="unbound numeric literal"):
        lr.validate_plan(plan)


def test_template_format_spec_and_numeric_suffix_are_rejected(tmp_path):
    plan = _base_plan(tmp_path)
    metric = plan["panels"][2]["blocks"][0]
    metric["note"] = {
        "template": "結果 {x:.2}",
        "bindings": {"x": _binding("result.return", "percent", digits=1)},
    }
    with pytest.raises(lr.PlanValidationError, match="format specifiers"):
        lr.validate_plan(plan)

    plan = _base_plan(tmp_path)
    plan["panels"][2]["blocks"][0]["value"]["format"]["suffix"] = "／999"
    with pytest.raises(lr.PlanValidationError, match="unbound numeric literal"):
        lr.validate_plan(plan)


def test_template_binding_names_must_be_plain_identifiers(tmp_path):
    plan = _base_plan(tmp_path)
    plan["panels"][0]["blocks"][0]["body"][0] = {
        "template": "共同窗口 {x.y}",
        "bindings": {"x.y": _binding("window.start", "date")},
    }
    with pytest.raises(lr.PlanValidationError, match="bindings key must match"):
        lr.validate_plan(plan)


def test_root_bound_subtitle_is_rejected_to_keep_panel_sources_complete(tmp_path):
    plan = _base_plan(tmp_path)
    plan["subtitle"] = {
        "template": "{claim}",
        "bindings": {"claim": _binding("claim", "text")},
    }
    with pytest.raises(lr.PlanValidationError, match="must be literal text"):
        lr.validate_plan(plan)


def test_integer_format_does_not_round_float_counts(tmp_path):
    plan = _base_plan(tmp_path)
    plan["panels"][2]["blocks"][2]["value"] = _binding(
        "result.volatility", "integer"
    )
    path = _write_plan(tmp_path, plan)
    document, evidence = lr.load_plan(path)
    with pytest.raises(lr.EvidenceBindingError, match="requires an integer"):
        lr._resolve_panels(document, evidence)


def test_binding_source_must_be_disclosed_in_panel_footer(tmp_path):
    plan = _base_plan(tmp_path)
    plan["evidence"]["other"] = copy.deepcopy(plan["evidence"]["main"])
    plan["panels"][2]["blocks"][0]["value"]["source"] = "other"
    with pytest.raises(lr.PlanValidationError, match="unknown evidence 'other'"):
        lr.validate_plan(plan)


def test_json_pointer_reaches_evidence_keys_containing_dots(tmp_path):
    plan = _base_plan(tmp_path)
    evidence_path = Path(plan["evidence"]["main"]["path"])
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["weights"] = {"1515.TW": {"share": 0.25}}
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    plan["evidence"]["main"]["sha256"] = hashlib.sha256(
        evidence_path.read_bytes()
    ).hexdigest()
    plan["panels"][2]["blocks"][0]["value"] = _binding(
        "/weights/1515.TW/share", "percent", digits=1
    )
    path = _write_plan(tmp_path, plan)
    document, loaded = lr.load_plan(path)
    resolved = lr._resolve_panels(document, loaded)
    assert resolved[2]["blocks"][0]["value"] == "25.0%"


def test_path_traversal_and_duplicate_panel_names_are_rejected(tmp_path):
    plan = _base_plan(tmp_path)
    plan["panels"][0]["name"] = "../escape"
    with pytest.raises(lr.PlanValidationError, match="must match"):
        lr.validate_plan(plan)
    plan = _base_plan(tmp_path)
    plan["panels"][1]["name"] = plan["panels"][0]["name"]
    with pytest.raises(lr.PlanValidationError, match="duplicate"):
        lr.validate_plan(plan)


def test_long_traditional_chinese_title_wraps_without_overflow(
    tmp_path, cjk_test_font
):
    plan = _base_plan(tmp_path, long_title=True)
    path = _write_plan(tmp_path, plan)
    outputs = lr.render_plan(path, tmp_path / "out")
    assert len(outputs) == 4
    for output in outputs:
        with Image.open(output) as image:
            assert image.size == (1600, 1000)
            assert image.format == "PNG"


def test_same_plan_and_evidence_have_identical_pixel_hashes(
    tmp_path, cjk_test_font
):
    plan = _base_plan(tmp_path)
    path = _write_plan(tmp_path, plan)
    first = lr.render_plan(path, tmp_path / "out_a")
    second = lr.render_plan(path, tmp_path / "out_b")
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in first] == [
        hashlib.sha256(p.read_bytes()).hexdigest() for p in second
    ]


def test_mid_promotion_failure_rolls_back_complete_old_set(
    tmp_path, monkeypatch, cjk_test_font
):
    plan = _base_plan(tmp_path)
    path = _write_plan(tmp_path, plan)
    out = tmp_path / "out"
    out.mkdir()
    expected_old = {}
    for panel in plan["panels"]:
        target = out / f"{panel['name']}.png"
        payload = f"old-{panel['name']}".encode()
        target.write_bytes(payload)
        expected_old[target] = payload

    original_replace = lr.os.replace
    promoted = 0
    failed = False

    def flaky_replace(source, target):
        nonlocal promoted, failed
        source_path = Path(source)
        target_path = Path(target)
        if (
            target_path.parent == out and target_path.suffix == ".png"
            and not source_path.name.startswith(".backup-")
        ):
            promoted += 1
            if promoted == 2 and not failed:
                failed = True
                raise OSError("injected promotion fault")
        return original_replace(source, target)

    monkeypatch.setattr(lr.os, "replace", flaky_replace)
    with pytest.raises(OSError, match="injected promotion fault"):
        lr.render_plan(path, out)
    assert {target: target.read_bytes() for target in expected_old} == expected_old


def test_render_receipt_binds_nonce_plan_and_output_hashes(
    tmp_path, cjk_test_font
):
    plan = _base_plan(tmp_path)
    path = _write_plan(tmp_path, plan)
    outputs = lr.render_plan(path, tmp_path / "out")
    receipt = lr.write_render_receipt(
        tmp_path / "receipt.json", run_token="nonce", plan_path=path, paths=outputs
    )
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["run_token"] == "nonce"
    assert payload["plan_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert [x["name"] for x in payload["panels"]] == [x.name for x in outputs]


def test_later_text_fit_failure_leaves_no_partial_final_pngs(
    tmp_path, cjk_test_font
):
    plan = _base_plan(tmp_path)
    plan["panels"][1]["blocks"][0]["body"] = ["極" * 2000]
    path = _write_plan(tmp_path, plan)
    out = tmp_path / "out"
    # Repair disabled: this test pins ATOMICITY (a late text-fit fault leaves
    # no partial finals) — the mechanical repair rounds' taller canvas could
    # legitimately fit this copy, which is covered by
    # test_lazypack_render_repair.py instead.
    with pytest.raises(lr.TextFitError):
        lr.render_plan(path, out, max_repair_rounds=0)
    assert not list(out.glob("*.png"))


def test_renderer_has_no_agentic_or_subprocess_path():
    source = (SCRIPTS / "lazypack_render.py").read_text(encoding="utf-8")
    assert "import subprocess" not in source
    assert "gen_lazypack_codex" not in source
    assert "codex exec" not in source


@pytest.mark.parametrize("article_id", ["mile_b6a46796", "mile_a8d79d6a"])
def test_migrated_acceptance_plans_render_from_empty_directory(
    tmp_path, article_id, cjk_test_font
):
    plan = ROOT / "storage" / "lazypack_jobs" / article_id / "plan.json"
    document, _ = lr.load_plan(plan)
    outputs = lr.render_plan(plan, tmp_path / article_id)
    assert [p.name for p in outputs] == [f"{p['name']}.png" for p in document["panels"]]
    for output in outputs:
        with Image.open(output) as image:
            assert image.size == (1600, 1000)
            assert image.format == "PNG"
