"""Regression tests for the pre-write dedup gate's K-coverage check.

2026-07-11 incident: `check_arc_dedup.py --k-id K1586` returned exit 0 while
`mile_c1ce6550` (same K, same audience, published) was already live, and the
same held for K1605 / `mile_3a7bd6f6`. Two writer agents were dispatched on top
of existing articles before an agent caught it by hand.

Root cause: the only same-K signal lived inside `find_arc_duplicates`, gated
behind `ex_cls == new_cls` (arc_dedup.py ~L951/L962). A same-K twin whose
conclusion wording classifies into a different bucket bypassed it entirely — so
the most certain form of duplicate depended on a text classifier agreeing with
itself across two documents. Coverage is now an exact-match gate that runs first.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_arc_dedup as cli  # noqa: E402
from check_arc_dedup import find_k_coverage  # noqa: E402


def _item(mile_id, k_ids, audience, status="published", title="t"):
    return {
        "id": mile_id,
        "title": title,
        "status": status,
        "audience": audience,
        "published_at": "2026-07-02T00:00:00+00:00",
        "details": {"experiment_refs": list(k_ids)},
    }


# The two articles that were live on 2026-07-11 while the gate said "go".
FEED = [
    _item("mile_c1ce6550", ["K1586"], "general",
          title="USDC 脫鉤那幾天：1-3 年短券日波動飆 2.8 倍"),
    _item("mile_cfa5eb89", ["K1586"], "research",
          title="K1586：穩定幣儲備變化與短端 T-bill realized vol"),
    _item("mile_3a7bd6f6", ["K1605"], "general", status="draft",
          title="銀行的帳面價值慢半拍"),
    _item("mile_80cae4cb", ["K1605"], "research",
          title="K1605：區域銀行 M/B 折價與後續波動"),
    _item("mile_dead0001", ["K1591"], "general", status="retracted",
          title="retracted piece"),
]


def test_k1586_general_is_covered():
    """The exact miss: a published general twin must be found."""
    hits = find_k_coverage("K1586", FEED, "general")
    assert [h["id"] for h in hits] == ["mile_c1ce6550"]


def test_k1605_general_draft_counts_as_coverage():
    """A draft already sitting in the release pool is coverage — writing a second
    one would put two versions of the same piece in the queue."""
    hits = find_k_coverage("K1605", FEED, "general")
    assert [h["id"] for h in hits] == ["mile_3a7bd6f6"]
    assert hits[0]["status"] == "draft"


def test_research_sibling_does_not_block_general():
    """Product design: one K legitimately carries both a research and a general
    write-up. Scoping to the audience is what keeps the gate from blocking the
    twin forever."""
    feed = [i for i in FEED if i["id"] != "mile_c1ce6550"]  # general twin not yet written
    assert find_k_coverage("K1586", feed, "general") == []
    assert [h["id"] for h in find_k_coverage("K1586", feed, "research")] == ["mile_cfa5eb89"]


def test_unscoped_check_sees_every_audience():
    ids = {h["id"] for h in find_k_coverage("K1586", FEED, None)}
    assert ids == {"mile_c1ce6550", "mile_cfa5eb89"}


def test_retracted_article_is_not_coverage():
    """Retracted/unpublished pieces are not reader-visible, so the K is uncovered
    again — otherwise a retraction would permanently forbid a correct rewrite."""
    assert find_k_coverage("K1591", FEED, "general") == []


def test_uncovered_k_passes():
    assert find_k_coverage("K9999", FEED, "general") == []


@pytest.mark.parametrize("raw", ["k1586", "K1586", " K1586 "])
def test_k_id_normalisation(raw):
    assert [h["id"] for h in find_k_coverage(raw, FEED, "general")] == ["mile_c1ce6550"]


def test_k_id_matched_from_body_when_refs_missing():
    """Older articles pre-date details.experiment_refs; the K-id lives in the
    title/content. _refs_from_feed_item already backfills from text — make sure
    coverage inherits that rather than silently under-reporting."""
    legacy = [{
        "id": "mile_legacy",
        "title": "K1234：某個舊研究",
        "status": "published",
        "audience": "general",
        "published_at": "2026-01-01T00:00:00+00:00",
    }]
    assert [h["id"] for h in find_k_coverage("K1234", legacy, "general")] == ["mile_legacy"]


def test_cli_logs_normalized_k_as_stable_candidate_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Headline edits must not turn retries of one K into separate candidates."""
    (tmp_path / "storage" / "reports").mkdir(parents=True)
    (tmp_path / "storage" / "reports" / "feed.json").write_text(
        json.dumps([]),
        encoding="utf-8",
    )
    experiment = tmp_path / "experiments" / "k1366"
    experiment.mkdir(parents=True)
    (experiment / "README.md").write_text("VIX result", encoding="utf-8")
    logged: list[dict] = []
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(
        cli,
        "find_k_coverage",
        lambda *_a, **_k: [
            {
                "id": "mile_prior",
                "audience": "general",
                "status": "published",
                "published_at": "2026-07-01",
                "title": "prior",
            }
        ],
    )
    monkeypatch.setattr(
        cli,
        "_log_dedup_decision",
        lambda *_a, **kwargs: logged.append(kwargs),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_arc_dedup.py",
            "--k-id",
            "k1366",
            "--audience",
            "general",
            "--title",
            "TBD",
        ],
    )

    assert cli.main() == 1
    assert logged == [{"candidate_id": "K1366"}]
