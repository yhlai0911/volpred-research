"""Regression tests for generation-time topic dedup (2026-07-13 trending incident).

The incident: `refill_reader_facing_pool` created the trending task
「AI營收不如預期？科技股選擇權偏斜率（Skew）洩天機」 — the 5th piece on the same
narrative arc within 90 days — and it sat in the pending pool for 20 hours until a
human grep caught it. The generators never looked at the feed.

The non-obvious part, measured before writing the gate (see
arc_dedup.theme_saturation docstring): the ARC gate could not have caught this.
`extract_entities` maps the one underlying subject (AI capex -> tech/semi option
skew) onto near-disjoint entity sets, so the five real articles do not arc-match
EACH OTHER (0 of 10 pairs). Hence the theme-saturation gate. `test_arc_gate_cannot_
catch_the_incident_family` pins that finding so nobody "simplifies" the theme gate
away believing the arc gate covers it.
"""

from __future__ import annotations

import itertools
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from volpred.ops.topic_dedup import (  # noqa: E402
    BLOCK_ARC_DUP,
    BLOCK_K_COVERAGE,
    BLOCK_THEME_SATURATED,
    CLEAN,
    GATE_ERROR,
    UNJUDGED_THIN_SIGNATURE,
    WARN_ARC_DUP,
    WARN_THEME_SATURATED,
    screen_topic,
)
from volpred.publisher.arc_dedup import (  # noqa: E402
    THEME_SATURATION_THRESHOLD,
    find_arc_duplicates,
    theme_saturation,
)


def _recent(days_ago: int = 5) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _article(aid: str, title: str, **kw) -> dict:
    item = {
        "id": aid,
        "title": title,
        "status": "published",
        "published_at": _recent(kw.pop("days_ago", 5)),
        "content": kw.pop("content", ""),
        "tags": kw.pop("tags", []),
    }
    item.update(kw)
    return item


# The five real same-arc articles from the incident (verbatim titles).
INCIDENT_SIBLINGS = [
    ("mile_f5f4cb43", "科技巨頭資本支出爆表，AI 變現期的隱含波動率拐點"),
    ("mile_8a5e80b0", "AI 資本支出的裂縫：指數安靜，個股先吵起來"),
    ("mile_0941e2f0", "半導體修正進行中：選擇權偏斜告訴你市場還沒放心"),
    ("mile_49616ac2", "AI 資本支出狂潮下，期權市場押的是上行而不是下行"),
    ("mile_622a2b73", "資本支出暴增八成，股票卻平靜如水：AI 巨頭的波動率定價迷局"),
]
# Same theme, also live at the time — found during root-cause, not in the original report.
INCIDENT_NEIGHBOURS = [
    ("mile_4901f7bc", "AI 一季燒五百億，該擔心嗎？別看 VIX，看波動率市場真正在怕的三件事"),
    ("mile_e1ff7ef9", "監管警告 AI 估值太貴，那選擇權市場自己怕不怕？一個反直覺的答案"),
    ("mile_bd06ccbc", "VIX 掉回 16.9 的假平靜：科技股才回檔逾一成，該盯的其實是這四件事"),
    ("mile_a30cfe89", "VIX 只有十幾點，選擇權市場卻在偏心加價：偏斜三讀法"),
]

INCIDENT_TITLE = "AI營收不如預期？科技股選擇權偏斜率（Skew）洩天機"
INCIDENT_DESC = "AI 資本支出疑慮升溫，科技股與半導體的選擇權偏斜率(skew)走陡，市場在為下跌買保險。"


# Unrelated filler so the corpus resembles production (832 live articles in 90d)
# rather than a 9-article toy. Corpus size drives the ambient-vocabulary cutoff,
# so a toy corpus exercises a regime the gate never sees in production.
#
# Every filler title must be UNIQUE and thematically dispersed. An earlier version
# repeated 10 titles 6x each; six byte-identical "...季節性" articles then made the
# (genuinely novel) carbon/ETS topic look saturated. Real corpora do not contain
# six identical titles -- duplicated filler manufactures false saturation.
_FILLER_SUBJECTS = [
    "台幣匯率", "黃金", "原油期貨", "公債殖利率", "比特幣", "房地產信託",
    "日圓套利", "新興市場債", "電力期貨", "銅價", "咖啡期貨", "運費指數",
]
_FILLER_ASPECTS = [
    "與出口商避險需求", "在升息循環中的定價", "的倉儲成本與價差", "倒掛後的股債相關",
    "的礦工賣壓估算", "的利率敏感度分解",
]
FILLER_TITLES = [
    f"{s}{a}" for s in _FILLER_SUBJECTS for a in _FILLER_ASPECTS
]  # 72 unique, non-overlapping with any test topic's vocabulary


@pytest.fixture
def crowded_feed() -> list[dict]:
    """Feed where the AI/tech-skew theme is saturated, inside a realistic corpus."""
    feed = [_article(aid, title) for aid, title in INCIDENT_SIBLINGS + INCIDENT_NEIGHBOURS]
    for j, t in enumerate(FILLER_TITLES):
        feed.append(_article(f"mile_filler_{j}", t, days_ago=10 + (j % 40)))
    return feed


# --- (a) the duplicate topic is blocked AND carries an audit reason -----------


def test_theme_saturation_catches_the_incident_family(crowded_feed):
    """The core new capability, tested directly: the theme IS measurably crowded.

    On the real 90d corpus this scored 11 (threshold 6). Here we assert the gate
    fires on the real titles, independent of which verdict `screen_topic` reaches.
    """
    result = theme_saturation(INCIDENT_TITLE, INCIDENT_DESC, crowded_feed, days=90)
    assert result["saturation"] >= THEME_SATURATION_THRESHOLD, (
        f"incident theme scored {result['saturation']}, "
        f"below threshold {THEME_SATURATION_THRESHOLD} — gate would miss the incident"
    )
    assert result["theme_terms"], "gate must expose the theme it judged on"


def test_theme_gate_is_load_bearing_when_arc_is_blind(monkeypatch, crowded_feed):
    """Pins the INCIDENT'S ACTUAL CONDITION: arc returns nothing, theme must catch it.

    On the real feed the arc gate returned [] for this topic (measured), because
    it is entity-anchored and the descriptive path demands a strong same-article
    signal. So we force arc to be blind — exactly as it was — and require the
    theme gate to block anyway. If the theme gate were removed, this fails.
    """
    import volpred.ops.topic_dedup as td

    monkeypatch.setattr(td, "find_arc_duplicates", lambda *a, **kw: [])
    screen = td.screen_topic(INCIDENT_TITLE, INCIDENT_DESC, feed=crowded_feed, mode="block")

    assert screen.blocked is True, "arc was blind and nothing else caught it — the incident recurs"
    assert screen.verdict == BLOCK_THEME_SATURATED
    # Not a silent skip: the reason must name the evidence.
    assert screen.reason, "a block with no reason is a silent skip"
    assert str(screen.saturation) in screen.reason
    assert screen.matches, "block must expose the articles it matched against"
    assert screen.theme_terms, "block must expose the theme it judged on"


def test_incident_topic_is_blocked_with_reason(crowded_feed):
    """Whichever gate fires, the topic must not become a task, and must say why."""
    screen = screen_topic(INCIDENT_TITLE, INCIDENT_DESC, feed=crowded_feed, mode="block")

    assert screen.blocked is True
    assert screen.verdict in (BLOCK_ARC_DUP, BLOCK_THEME_SATURATED)
    assert screen.reason, "a block with no reason is a silent skip"
    assert screen.matches, "block must expose the articles it matched against"


def test_blocked_topic_exposes_audit_blob(crowded_feed):
    """as_task_field() is what downstream sees — it must carry the why."""
    screen = screen_topic(INCIDENT_TITLE, INCIDENT_DESC, feed=crowded_feed, mode="block")
    blob = screen.as_task_field()
    assert blob["verdict"] in (BLOCK_ARC_DUP, BLOCK_THEME_SATURATED)
    assert blob["reason"]
    assert blob["near_misses"]
    assert blob["screened_at"]


# --- (b) a genuinely new topic is NOT blocked --------------------------------


@pytest.mark.parametrize(
    "title,desc,expected",
    [
        # The extractor knows carbon/ETS, so the arc gate could look and found nothing.
        ("碳權市場的波動結構：歐盟 ETS 期貨的季節性",
         "檢視歐盟碳排放權交易體系 ETS 期貨的波動率季節性與到期效應。",
         CLEAN),
        # It has NO vocabulary for USDT/USDC/DeFi -> entities=[] -> the arc gate
        # never looked. It still must not block (that is what this test guards),
        # but calling it `clean` was the 2026-07-13/14 lie: "I could not look" is
        # not "I looked and it is clean". Documents a real blind spot — the entity
        # vocabulary covers no crypto at all, so no crypto topic is arc-judgeable.
        ("穩定幣脫鉤事件的流動性傳染",
         "USDT/USDC 脫鉤時，DeFi 池的流動性如何跨鏈傳染。",
         UNJUDGED_THIN_SIGNATURE),
    ],
)
def test_novel_topic_passes(crowded_feed, title, desc, expected):
    """The contract is NOT-BLOCKED. The verdict says whether the gate could see it."""
    screen = screen_topic(title, desc, feed=crowded_feed, mode="block")
    assert screen.blocked is False
    assert screen.verdict == expected


def test_theme_gate_does_not_fire_on_legit_event_topic(crowded_feed):
    """The THEME gate must not fire on an FOMC preview. Calibration anchor.

    Scoped deliberately to `theme_saturation`, the gate this change ADDS, rather
    than to the whole screen. On the real corpus the FOMC topic scores saturation
    2 (vs the incident's 9-12) — comfortably clean — but the PRE-EXISTING arc gate
    blocks it anyway via `descriptive_strict`, matching an NFP piece and a VIX
    explainer. That arc behaviour is identical at 30d and 90d (measured), so it is
    not a regression from this change and is not this gate's to fix; asserting
    `screen.blocked is False` here would be asserting something untrue of the real
    feed. The event lane — where FOMC actually lives — is warn-only, so it is
    insulated either way (see test_event_lane_warns_but_never_blocks).
    """
    result = theme_saturation(
        "FOMC 前夕：市場在為降息還是鷹派押注？",
        "本週 FOMC 利率決議前，選擇權市場的定價與波動率結構。",
        crowded_feed,
        days=90,
    )
    assert result["saturation"] < THEME_SATURATION_THRESHOLD, (
        "theme gate is too tight — it would block a legitimate event topic"
    )


# --- (c) same K, different audience is NOT a duplicate (product design) -------


def test_same_k_different_audience_is_not_duplicate():
    """Research + general write-ups of one K is the product design, not a dup."""
    feed = [
        _article(
            "mile_research",
            "K1700: GJR-GARCH 對 SPY 的 QLIKE 改善",
            audience="research",
            experiment_refs=["k1700"],
        )
    ]
    # Writing the GENERAL twin of the same K must be allowed.
    general = screen_topic(
        "波動率模型換一個，散戶看得懂的差別在哪",
        "用白話解釋 SPY 波動率預測。",
        feed=feed,
        k_id="k1700",
        audience="general",
        mode="block",
    )
    assert general.blocked is False, "same K, different audience must not be blocked"
    assert general.verdict != BLOCK_K_COVERAGE

    # But a second RESEARCH piece on the same K is genuine coverage -> block.
    research = screen_topic(
        "K1700 再談 GJR-GARCH 的 QLIKE",
        "同一個 K 的研究版。",
        feed=feed,
        k_id="k1700",
        audience="research",
        mode="block",
    )
    assert research.blocked is True
    assert research.verdict == BLOCK_K_COVERAGE
    assert "k1700" in research.reason.lower()


# --- lane policy: event warns, never blocks ----------------------------------


def test_event_lane_warns_but_never_blocks(crowded_feed):
    """Event articles are a designed T-7/T-2/T+0 series; a block = content hole."""
    screen = screen_topic(INCIDENT_TITLE, INCIDENT_DESC, feed=crowded_feed, mode="warn")
    assert screen.blocked is False, "event lane must never block (P1 time-sensitive)"
    assert screen.verdict in (WARN_ARC_DUP, WARN_THEME_SATURATED)
    assert screen.matches, "warn must still surface the near misses to the writer"


def test_event_lane_warns_on_saturated_theme(monkeypatch, crowded_feed):
    """Same arc-blind condition, event lane: warn + expose, still never block."""
    import volpred.ops.topic_dedup as td

    monkeypatch.setattr(td, "find_arc_duplicates", lambda *a, **kw: [])
    screen = td.screen_topic(INCIDENT_TITLE, INCIDENT_DESC, feed=crowded_feed, mode="warn")
    assert screen.blocked is False
    assert screen.verdict == WARN_THEME_SATURATED
    assert screen.matches


# --- fail-open, but never silent ---------------------------------------------


def test_missing_corpus_fails_open_but_reports_it():
    screen = screen_topic(INCIDENT_TITLE, INCIDENT_DESC, feed=[], mode="block")
    assert screen.blocked is False
    assert screen.verdict == GATE_ERROR
    assert "could not" in screen.reason.lower() or "fail-open" in screen.reason.lower()


def test_gate_error_fails_open_and_is_reported(monkeypatch):
    import volpred.ops.topic_dedup as td

    def boom(*a, **kw):
        raise RuntimeError("corpus exploded")

    monkeypatch.setattr(td, "find_arc_duplicates", boom)
    screen = td.screen_topic("t", "d", feed=[_article("mile_x", "x")], mode="block")
    assert screen.blocked is False, "a broken gate must not create a content hole"
    assert screen.verdict == GATE_ERROR
    assert "corpus exploded" in screen.reason


# --- every generator path is actually wired to the screen ---------------------


def test_event_task_is_screened_when_feed_supplied(crowded_feed, tmp_path):
    """build_pending_event_task must annotate (not block) a saturated event topic."""
    from volpred.ops.event_jobs import build_pending_event_task

    item = {
        "id": "evt_ai_skew",
        "event_key": "ai_capex",
        "task_template": {
            "title": INCIDENT_TITLE,
            "description": INCIDENT_DESC,
            "payload_patch": {
                "event_type": "ai_capex",
                "event_date": "2026-07-20",
                "event_series_slot": "T-2",
            },
        },
    }
    task = build_pending_event_task(
        item, now=datetime.now(timezone.utc), feed=crowded_feed, storage_dir=str(tmp_path)
    )
    assert task["task_type"] == "event_article"
    assert task["priority"] == 1, "event tasks stay P1 time-sensitive"
    assert "dedup_screen" in task, "saturated event topic must be annotated for the writer"
    assert task["dedup_screen"]["near_misses"], "annotation must name the near misses"


def test_event_task_without_feed_is_unscreened_but_still_built():
    """No corpus -> no annotation, but the event still ships (fail-open)."""
    from volpred.ops.event_jobs import build_pending_event_task

    item = {
        "id": "evt_x",
        "event_key": "fomc",
        "task_template": {
            "title": "FOMC 前夕",
            "description": "利率決議前的定價。",
            "payload_patch": {
                "event_type": "fomc",
                "event_date": "2026-07-20",
                "event_series_slot": "T-2",
            },
        },
    }
    task = build_pending_event_task(item, now=datetime.now(timezone.utc), feed=None)
    assert task["task_type"] == "event_article"
    assert "dedup_screen" not in task


def test_refill_event_path_passes_the_feed():
    """Regression: `_build_event_task` once called the builder WITHOUT a feed,
    leaving that second event path silently unscreened — the screen was dead code
    on it. Pin the wiring, not just the gate."""
    import importlib.util
    import inspect

    path = ROOT / "scripts" / "refill_reader_facing_pool.py"
    spec = importlib.util.spec_from_file_location("reader_facing_refill_dedupcheck", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    src = inspect.getsource(mod._build_event_task)
    assert "feed=" in src, "_build_event_task must pass a feed or the screen never runs"


# --- the finding that justifies this gate's existence ------------------------


def test_arc_gate_cannot_catch_the_incident_family():
    """Pins the root cause: the arc gate is entity-anchored and misses this family.

    If this ever starts failing, the arc gate got better and the theme gate's
    justification should be re-examined — do NOT just delete the assertion.
    """
    arts = {aid: _article(aid, title) for aid, title in INCIDENT_SIBLINGS}
    matched = 0
    for a, b in itertools.combinations(arts, 2):
        if find_arc_duplicates(arts[a]["title"], "", [arts[b]], days=3650):
            matched += 1
    assert matched == 0, (
        "arc gate now matches the incident siblings; re-evaluate theme gate rationale"
    )


def test_arc_dup_still_blocks_when_signature_is_rich():
    """The arc gate is still wired in and still does its job when it CAN anchor."""
    feed = [
        _article(
            "mile_arc",
            "SPY 的波動率目標策略在 OOS 崩潰：Sharpe 變雜訊",
            content="我們檢驗 SPY volatility targeting 策略，OOS 期間 Sharpe 崩潰，結論為無效。",
        )
    ]
    screen = screen_topic(
        "SPY 波動率目標策略的 OOS 崩潰",
        "SPY volatility targeting 在樣本外 Sharpe 崩潰，策略無效。",
        feed=feed,
        mode="block",
    )
    assert screen.verdict in (BLOCK_ARC_DUP, BLOCK_THEME_SATURATED)
    assert screen.blocked is True
