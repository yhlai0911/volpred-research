"""Regression coverage for the 2026-07-14 arc-gate calibration audit."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from volpred.ops import topic_dedup as topic_gate
from volpred.publisher.arc_dedup import (
    ARC_SIGNATURE_SCHEMA_VERSION,
    _signature_from_feed_item,
    arc_signature,
    extract_entities,
    find_arc_duplicates,
    is_arc_near_miss,
    strip_exclusion_scopes,
)


def _article(aid: str, title: str, content: str = "", **extra) -> dict:
    item = {
        "id": aid,
        "title": title,
        "content": content,
        "status": "published",
        "published_at": datetime.now(timezone.utc).isoformat(),
    }
    item.update(extra)
    return item


@pytest.mark.parametrize(
    "text,expected",
    [
        ("USDT 與 Tether 脫鉤", {"STABLECOIN"}),
        ("USDC / USD Coin liquidity", {"STABLECOIN"}),
        ("stablecoins 與穩定幣、稳定币", {"STABLECOIN"}),
        ("DeFi decentralized finance 去中心化金融", {"DEFI"}),
        ("USDC 的 DeFi 流動性池", {"STABLECOIN", "DEFI"}),
    ],
)
def test_crypto_entity_surfaces(text, expected):
    assert expected <= extract_entities(text)


def test_crypto_ascii_word_boundaries_do_not_match_substrings():
    assert "DEFI" not in extract_entities("a definite conclusion")
    assert "STABLECOIN" not in extract_entities("stablecoinage is not a token")


def test_bank_is_not_silver_but_unambiguous_silver_surfaces_are():
    assert "SILVER" not in extract_entities("銀行財報與存款流失")
    assert "SILVER" in extract_entities("白銀與銀價")
    assert "SILVER" in extract_entities("SLV 銀期貨")


def test_negated_exclusion_list_does_not_change_signature():
    title = "選擇權到期日曆效應"
    body = "研究美股選擇權到期日曆效應與盤中定價。"
    base = arc_signature(title, body)
    scoped = arc_signature(
        title,
        body + " 不涉及油價、財報、Fed、VIX 與其他資產的波動傳導。",
    )
    assert scoped == base


@pytest.mark.parametrize(
    "text,expected,absent",
    [
        ("不是 VIX 或 Fed，而是 USDT 與 DeFi", {"STABLECOIN", "DEFI"}, {"VIX", "FOMC"}),
        ("不是 VIX 而是 USDC", {"STABLECOIN"}, {"VIX"}),
        ("This does not cover VIX; USDC and DeFi remain.", {"STABLECOIN", "DEFI"}, {"VIX"}),
        ("本文不採用 VIX 作控制，USDC 仍顯著", {"STABLECOIN"}, {"VIX"}),
        ("不做 FOMC，但採用 SPY", {"US_EQUITY"}, {"FOMC"}),
    ],
)
def test_exclusion_scope_keeps_positive_clause(text, expected, absent):
    entities = extract_entities(text)
    assert expected <= entities
    assert not (absent & entities)


def test_negation_normalizer_preserves_positive_dependency_and_event_terms():
    assert extract_entities("不看 VIX 就無法理解 USDC") == {"VIX", "STABLECOIN"}
    assert extract_entities("不能排除 Fed 與 VIX 的影響") == {"FOMC", "VIX"}
    assert "非農" in strip_exclusion_scopes("非農公布後 SPY 盤中波動")
    assert "結果不顯著" in strip_exclusion_scopes("結果不顯著，但樣本仍完整")


def test_macro_mechanism_overlap_is_visible_near_miss_not_hard_block():
    existing = _article(
        "mile_nfp",
        "非農後 Fed 政策選擇權怎麼走",
        "Fed 政策與 FOMC 前後的利率選擇權定價結構。",
        audience="general",
    )
    title = "FOMC 前夕：市場在為降息還是鷹派押注？"
    content = "本週 FOMC 利率決議前，選擇權市場的定價與波動率結構。"

    assert find_arc_duplicates(title, content, [existing], audience="general") == []
    matches = find_arc_duplicates(
        title,
        content,
        [existing],
        audience="general",
        include_fuzzy=True,
    )
    assert matches
    assert all(is_arc_near_miss(m) for m in matches)
    assert matches[0]["match_reason"] == "descriptive_fuzzy_mechanism"


def test_old_v3_signature_recomputes_with_v4_vocabulary_without_legacy_fallback():
    existing = _article(
        "mile_usdc",
        "USDC 脫鉤時 DeFi 流動性如何傳染",
        "USDC stablecoin 與 DeFi pool 的流動性傳染。",
        details={
            "arc_signature": {
                "schema_version": "arc_dedup_v3",
                "entities": [],
                "entity_groups": {"reader_narrative": [], "paper_methodology": []},
                "conclusion_class": "descriptive",
                "narrative_axis": "unspecified",
                "mechanisms": [],
                "time_horizon": "unspecified",
            }
        },
    )
    recomputed = _signature_from_feed_item(existing)
    assert recomputed["schema_version"] == ARC_SIGNATURE_SCHEMA_VERSION
    assert {"STABLECOIN", "DEFI"} <= set(recomputed["entities"])

    matches = find_arc_duplicates(
        "USDC 脫鉤時 DeFi 流動性如何傳染",
        "USDC stablecoin 與 DeFi pool 的流動性傳染。",
        [existing],
    )
    assert matches
    assert matches[0]["match_reason"] == "descriptive_strict"


def test_default_arc_scan_does_not_hide_matches_after_first_300_items():
    fillers = [
        _article(f"mile_filler_{i}", f"無關主題 {i}", "純方法介紹。")
        for i in range(300)
    ]
    target = _article(
        "mile_usdc_oldest",
        "USDC 脫鉤時 DeFi 流動性如何傳染",
        "USDC stablecoin 與 DeFi pool 的流動性傳染。",
        published_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    )
    feed = fillers + [target]
    args = (
        "USDC 脫鉤時 DeFi 流動性如何傳染",
        "USDC stablecoin 與 DeFi pool 的流動性傳染。",
        feed,
    )

    assert find_arc_duplicates(*args)[0]["id"] == "mile_usdc_oldest"
    assert find_arc_duplicates(*args, max_scan=300) == []


def test_calibration_probe_contract(monkeypatch):
    def fake_theme(title, description, feed, days=90):
        if "非農" in title:
            return {
                "theme_terms": ["美元", "nfp", "就業", "日內", "非農", "實現"],
                "saturation": 3,
                "matches": [],
                "corpus_size": 831,
            }
        return {
            "theme_terms": ["科技", "資本", "capex", "定價", "支出", "巨頭"],
            "saturation": 8,
            "matches": [],
            "corpus_size": 831,
        }

    monkeypatch.setattr(topic_gate, "theme_saturation", fake_theme)
    monkeypatch.setattr(
        topic_gate,
        "find_arc_duplicates",
        lambda *a, **kw: [
            {"id": "mile_macro", "match_level": "near_miss", "match_reason": "descriptive_fuzzy_mechanism"}
        ],
    )
    result = topic_gate.audit_topic_dedup_calibration([{}])
    assert result["ok"] is True
    assert result["metrics"]["incident_margin"] == 3
    assert result["metrics"]["incident_screen_blocked"] is True
    assert result["metrics"]["incident_screen_verdict"] == topic_gate.BLOCK_THEME_SATURATED
    assert result["metrics"]["nfp_control_saturation"] == 3
    assert result["metrics"]["nfp_screen_blocked"] is False
    assert result["metrics"]["fomc_hard_matches"] == 0
    assert result["metrics"]["fomc_near_misses"] == 1
    assert result["metrics"]["fomc_screen_verdict"] == topic_gate.WARN_THEME_SATURATED


def test_calibration_probe_warns_on_threshold_margin_drift(monkeypatch):
    monkeypatch.setattr(
        topic_gate,
        "theme_saturation",
        lambda *a, **kw: {
            "theme_terms": ["科技", "資本", "capex"],
            "saturation": topic_gate.THEME_SATURATION_THRESHOLD,
            "matches": [],
            "corpus_size": 831,
        },
    )
    monkeypatch.setattr(topic_gate, "find_arc_duplicates", lambda *a, **kw: [])
    result = topic_gate.audit_topic_dedup_calibration([{}])
    assert result["ok"] is False
    assert any("margin" in issue for issue in result["issues"])


def test_calibration_probe_warns_when_incident_final_verdict_stops_blocking(monkeypatch):
    real_screen = topic_gate.screen_topic

    def fake_screen(title, *args, **kwargs):
        if title == topic_gate._CALIBRATION_AI_TITLE:
            return topic_gate.TopicScreen(
                verdict=topic_gate.WARN_THEME_SATURATED,
                blocked=False,
                reason="simulated policy drift",
            )
        return real_screen(title, *args, **kwargs)

    monkeypatch.setattr(topic_gate, "screen_topic", fake_screen)
    result = topic_gate.audit_topic_dedup_calibration([{}])

    assert result["ok"] is False
    assert any("calibrated theme block" in issue for issue in result["issues"])


def test_calibration_probe_rejects_fomc_gate_error(monkeypatch):
    real_screen = topic_gate.screen_topic

    def fake_screen(title, *args, **kwargs):
        if "FOMC" in title:
            return topic_gate.TopicScreen(
                verdict=topic_gate.GATE_ERROR,
                blocked=False,
                reason="simulated dependency failure",
            )
        return real_screen(title, *args, **kwargs)

    monkeypatch.setattr(topic_gate, "screen_topic", fake_screen)
    result = topic_gate.audit_topic_dedup_calibration([{}])

    assert result["ok"] is False
    assert any("calibrated warning" in issue for issue in result["issues"])


def test_calibration_probe_rejects_nfp_hard_block(monkeypatch):
    real_screen = topic_gate.screen_topic

    def fake_screen(title, *args, **kwargs):
        if "非農" in title:
            return topic_gate.TopicScreen(
                verdict=topic_gate.BLOCK_ARC_DUP,
                blocked=True,
                reason="simulated arc regression",
            )
        return real_screen(title, *args, **kwargs)

    monkeypatch.setattr(topic_gate, "screen_topic", fake_screen)
    result = topic_gate.audit_topic_dedup_calibration([{}])

    assert result["ok"] is False
    assert any("NFP/DXY" in issue for issue in result["issues"])
