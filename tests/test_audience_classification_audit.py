from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_audience_classification.py"
SPEC = importlib.util.spec_from_file_location("audience_audit_module", MODULE_PATH)
assert SPEC and SPEC.loader
aud = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(aud)


def test_score_item_flags_research_grade_general_content():
    item = {
        "id": "mile_test_high",
        "title": "GARCH-X 與 QLIKE 比較：K771 的 Harvey 檢驗",
        "audience": "general",
        "description": "這篇文章比較 GARCH-X、QLIKE、Harvey 與 DM test，並引用 K771 與 K124 的結果。" * 40,
        "details": {"experiment_refs": ["K771"]},
        "tags": ["一般讀者"],
    }
    scored = aud.score_item(item)

    assert scored["tier"] in {"HIGH", "MEDIUM"}
    assert scored["recommended_audience"] == "research"
    assert scored["experiment_readme_exists"] is True


def test_score_item_keeps_plain_language_article_low():
    item = {
        "id": "mile_test_low",
        "title": "市場大跌時，保險和分散化到底差在哪裡",
        "audience": "general",
        "description": "這篇文章用白話說明資產配置、保險成本與風險承受度，不討論模型細節。" * 10,
        "details": {},
        "tags": ["一般讀者", "資產配置"],
    }
    scored = aud.score_item(item)

    assert scored["tier"] == "LOW"
    assert scored["recommended_audience"] == "general"
