"""Hermetic tests for scripts/analyze_reader_preferences.py.

No Supabase, no .env.local: only the pure functions (feature extraction,
sample-size gate, output/report assembly) are exercised, via synthetic records.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "analyze_reader_preferences.py"
    spec = importlib.util.spec_from_file_location("analyze_reader_preferences", script_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)  # must not require any DB credentials
    return mod


MOD = _load_module()


def _record(slug, features, views, impressions=None, member=0, read_time=60.0, reactions=0):
    return {
        "slug": slug,
        "features": features,
        "views": views,
        "impressions": impressions if impressions is not None else views,
        "member_impressions": member,
        "median_read_time": read_time,
        "reactions_total": reactions,
    }


# 1. Feature extraction ------------------------------------------------------
def test_feature_extraction_from_article_dict():
    article = {
        "title": "🧪 迷思實驗室｜黃金是股災保險箱嗎？3 個反例",
        "audience": "general",
        "tags": ["黃金", "避險", "SPY"],
        "content": (
            "本文檢驗一個常見迷思。\n\n"
            "![chart1](a.png)\n![chart2](b.png)\n\n"
            "| 資產 | 報酬 |\n| --- | --- |\n| GLD | 1.2 |\n\n"
            "## 懶人包\n這是懶人包段落。\n\n"
            "延伸自 K1523 的實驗結果。"
        ),
        "details": {"experiment_refs": ["K1523"]},
    }
    f = MOD.extract_features(article)
    assert f["series"] == "迷思實驗室"
    assert f["audience"] == "general"
    assert f["title_is_question"] is True          # contains ？
    assert f["title_has_number"] is True           # contains 3
    assert f["chart_count"] == 2 and f["chart_bucket"] == "1-2"
    assert f["table_count"] == 1 and f["has_table"] is True
    assert f["has_lazypack"] is True
    assert f["research_vs_narrative"] == "research"  # experiment_refs + K1523
    assert set(f["tags"]) == {"黃金", "避險", "SPY"}

    # A plain narrative article with no series / table / K-id.
    plain = MOD.extract_features({
        "title": "市場今日回顧與展望",
        "audience": "daily",
        "content": "純文字內容，沒有圖也沒有表。" * 3,
        "tags": ["市場"],
    })
    assert plain["series"] == "無系列"
    assert plain["research_vs_narrative"] == "narrative"
    assert plain["has_table"] is False
    assert plain["chart_bucket"] == "0"
    assert plain["title_is_question"] is False


# 2. Min-sample gate ---------------------------------------------------------
def test_min_sample_gate_excludes_small_buckets():
    assert MOD.MIN_ARTICLES == 10 and MOD.MIN_IMPRESSIONS == 30

    # Bucket A: 12 articles, 60 impressions -> qualifies.
    # Bucket B: 3 articles, 9 impressions   -> insufficient.
    records = []
    for i in range(12):
        records.append(_record(f"a{i}", {"tags": [], "audience": "general", "series": "無系列",
                                          "title_is_question": True, "title_has_number": False,
                                          "title_has_exclamation": False, "title_len_bucket": "中",
                                          "content_len_bucket": "中", "chart_bucket": "1-2",
                                          "table_bucket": "1", "has_lazypack": False,
                                          "research_vs_narrative": "research"}, views=5))
    for i in range(3):
        records.append(_record(f"b{i}", {"tags": [], "audience": "research", "series": "無系列",
                                          "title_is_question": False, "title_has_number": False,
                                          "title_has_exclamation": False, "title_len_bucket": "中",
                                          "content_len_bucket": "中", "chart_bucket": "0",
                                          "table_bucket": "0", "has_lazypack": False,
                                          "research_vs_narrative": "narrative"}, views=3))

    dims = MOD.aggregate_buckets(records)
    audience = dims["audience"]["buckets"]
    assert audience["general"]["sample_ok"] is True
    assert audience["general"]["n_articles"] == 12
    assert audience["research"]["insufficient_sample"] is True

    conclusions, insufficient = MOD.build_conclusions(dims)
    # The 3-article research audience bucket must appear in insufficient, never in conclusions.
    insuf_pairs = {(r["dimension"], r["bucket"]) for r in insufficient}
    assert ("audience", "research") in insuf_pairs
    for c in conclusions:
        # No conclusion may reference an insufficient bucket.
        assert (c["dimension"], c["higher_bucket"]) not in insuf_pairs
        assert (c["dimension"], c["lower_bucket"]) not in insuf_pairs


# 3. Report generation -------------------------------------------------------
def test_report_generation_emits_qualified_conclusion_with_samples():
    # question=yes (high views) vs question=no (low views), both qualifying.
    records = []
    for i in range(12):
        records.append(_record(f"q{i}", {"tags": ["vol"], "audience": "general", "series": "無系列",
                                          "title_is_question": True, "title_has_number": False,
                                          "title_has_exclamation": False, "title_len_bucket": "中",
                                          "content_len_bucket": "中", "chart_bucket": "1-2",
                                          "table_bucket": "1", "has_lazypack": True,
                                          "research_vs_narrative": "research"}, views=20, read_time=90.0))
    for i in range(12):
        records.append(_record(f"n{i}", {"tags": ["vol"], "audience": "general", "series": "無系列",
                                          "title_is_question": False, "title_has_number": False,
                                          "title_has_exclamation": False, "title_len_bucket": "中",
                                          "content_len_bucket": "中", "chart_bucket": "0",
                                          "table_bucket": "0", "has_lazypack": False,
                                          "research_vs_narrative": "narrative"}, views=4, read_time=30.0))

    meta = {"generated_at": "2026-07-15T00:00:00+00:00", "window_days": 365,
            "since_date": "2025-07-15", "data_source_errors": {}, "feature_source_counts": {}}
    payload, md = MOD.build_outputs(records, meta)

    conclusions = payload["qualified_conclusions"]
    assert conclusions, "expected at least one qualified conclusion"
    qdim = {c["dimension"]: c for c in conclusions}
    assert "title_is_question" in qdim
    c = qdim["title_is_question"]
    assert c["higher_bucket"] == "yes" and c["lower_bucket"] == "no"
    assert c["higher_value"] > c["lower_value"]
    # Every conclusion must carry sample sizes and the non-causal caveat.
    assert c["higher_sample"]["n_articles"] == 12
    assert c["higher_sample"]["total_impressions"] >= 30
    assert "非因果" in c["caveat"]

    # Markdown report structure + honesty markers.
    assert "# 讀者偏好分析報告" in md
    assert "合格結論" in md
    assert "樣本不足清單" in md
    assert "非因果" in md
    # Totals present.
    assert payload["totals"]["articles_with_activity"] == 24
    assert payload["gate"]["min_articles"] == 10


def test_empty_records_yield_no_conclusions_not_error():
    meta = {"generated_at": "t", "window_days": 365, "since_date": "d",
            "data_source_errors": {}, "feature_source_counts": {}}
    payload, md = MOD.build_outputs([], meta)
    assert payload["qualified_conclusions"] == []
    assert payload["totals"]["articles_with_activity"] == 0
    assert "沒有任何維度達到合格樣本門檻" in md
