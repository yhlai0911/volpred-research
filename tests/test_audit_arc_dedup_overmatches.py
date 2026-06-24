from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import audit_arc_dedup_overmatches as audit  # noqa: E402


def test_find_overmatches_reports_different_narrative_axis():
    feed = [
        {
            "id": "mile_2849a7b5",
            "title": "K1417: Stationary Bootstrap 驗證 Paper 三 MDD Retention CI 穩健性",
            "description": (
                "Paper 三 reviewer H2，SPY VIX TSMOM momentum，stationary bootstrap，"
                "canonical K1192 baseline，MDD retention 不成立。"
            ),
            "status": "published",
        },
        {
            "id": "mile_k1547_draft",
            "title": "CTA ETF 比 SPY 更耐跌嗎？KMLM、DBMF 給的是一半答案",
            "description": (
                "免費 ETF proxy 下 CTA managed-futures trend-following 在 lagged VIX "
                "stress regime 沒有 robust crisis alpha，momentum overlay 相對 SPY 不顯著。"
            ),
            "status": "draft",
            "details": {
                "release_arc_dedup_of": "mile_2849a7b5",
                "release_dedup_skipped_at": "2026-06-24T08:00:00+00:00",
            },
        },
    ]

    hits = audit.find_overmatches(
        feed,
        days=30,
        now=datetime(2026, 6, 24, 9, tzinfo=timezone.utc),
    )

    assert len(hits) == 1
    assert hits[0]["candidate_id"] == "mile_k1547_draft"
    assert hits[0]["candidate_narrative_axis"] == "product_myth"
    assert hits[0]["blocked_by_narrative_axis"] == "methodology_robustness"
    assert hits[0]["recommendation"] == "review_dup_waiver_or_fresh_arc_rewrite"


def test_find_overmatches_ignores_same_axis_arc_skip():
    feed = [
        {
            "id": "mile_cta_old",
            "title": "CTA ETF 的 crisis alpha 沒有想像中穩",
            "description": "DBMF、KMLM、CTA managed-futures ETF proxy 在 VIX stress regime 不顯著。",
            "status": "published",
        },
        {
            "id": "mile_cta_new",
            "title": "免費 CTA ETF 真有避險 alpha 嗎？",
            "description": "DBMF、KMLM、CTA 的 managed-futures ETF proxy 沒有 robust crisis alpha。",
            "status": "draft",
            "details": {
                "release_arc_dedup_of": "mile_cta_old",
                "release_dedup_skipped_at": "2026-06-24T08:00:00+00:00",
            },
        },
    ]

    hits = audit.find_overmatches(
        feed,
        days=30,
        now=datetime(2026, 6, 24, 9, tzinfo=timezone.utc),
    )

    assert hits == []
