"""Tests for the pre-publish content-vs-source provenance gate.

3-Strike regression (2026-06-03, docs/refactor_plan_prepublish_content_gate.md).
Covers the four historical incident triggers:
  - K562  : a headline statistic not in any results.json -> Tier-1 finding.
  - K1413 : numbers that DO exist in source -> no Tier-1 false positive.
  - unit  : 42.4% article value vs 0.4244 source -> matched (no false alarm).
  - no-K  : no cited K-id -> skipped, never blocks.
  - years : 2023/2024 are not mistaken for statistics.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from volpred.publisher.prepublish_audit import (
    audit_content_provenance,
    extract_numeric_claims,
    load_source_values,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
K1413_RESULTS = REPO_ROOT / "experiments" / "k1413" / "k1413_results.json"


@pytest.fixture
def k562_root(tmp_path: Path) -> Path:
    """A fake experiments/ tree with a small K562 results.json."""
    exp = tmp_path / "experiments" / "k562"
    exp.mkdir(parents=True)
    (exp / "k562_results.json").write_text(
        json.dumps(
            {
                "experiment_id": "k562",
                "strategy": {"sharpe": 0.83, "annualized_return": 0.115},
                "baseline": {"sharpe": 0.61},
                "n_obs": 855,
            }
        )
    )
    return tmp_path


def test_k562_fabricated_sharpe_is_flagged(k562_root: Path):
    # Article claims a Sharpe of 1.42 that appears in NO results.json.
    content = (
        "æˆ‘å€‘çš„ç­–ç•¥åœ¨æ¨£æœ¬å…§å–å¾—äº† Sharpe 1.42 çš„å„ªç•°è¡¨ç¾ï¼Œ"
        "é¡¯è‘—å„ªæ–¼ baseline çš„ Sharpe 0.61ã€‚"
    )
    result = audit_content_provenance(content, ["K562"], root=str(k562_root))
    assert result["skipped"] is False
    raws = {f["raw"] for f in result["tier1_findings"]}
    assert "1.42" in raws  # fabricated number caught
    assert "0.61" not in raws  # the legitimate one is NOT flagged


def test_real_k1413_numbers_all_hit():
    # All three numbers exist in k1413_results.json:
    #   0.517 = full_period_annualized_vol['L3 åŸºç¤è¨­æ–½']
    #   0.4244 = rolling_vol_summary['L2 æ™¶ç‰‡'].latest
    #   0.6452 = avg_cross_layer_corr_by_period['2025è‡³ä»Š']
    content = (
        "åŸºç¤è¨­æ–½å±¤çš„å…¨æœŸå¹´åŒ–æ³¢å‹•ç‡é” 0.517ï¼Œæ˜¯å››ç±ƒä¸­æœ€é«˜ã€‚"
        "æ™¶ç‰‡å±¤æœ€æ–°å¹´åŒ–æ³¢å‹•ç‡ç‚º 0.4244ã€‚"
        "2025 å¹´ä»¥ä¾†çš„å¹³å‡è·¨å±¤ç›¸é—œä¿‚æ•¸å‡è‡³ 0.6452ã€‚"
    )
    result = audit_content_provenance(content, ["K1413"], root=str(REPO_ROOT))
    assert result["skipped"] is False
    assert result["tier1_findings"] == [], (
        f"unexpected findings: {result['tier1_findings']}"
    )
    assert result["n_claims"] >= 3


def test_percent_unit_conversion_no_false_alarm():
    # Article writes 42.4% ; source stores 0.4244 (L2 æ™¶ç‰‡ latest).
    content = "æ™¶ç‰‡å±¤æœ€æ–°å¹´åŒ–æ³¢å‹•ç‡ç´„ç‚º 42.4%ã€‚"
    result = audit_content_provenance(content, ["K1413"], root=str(REPO_ROOT))
    assert result["skipped"] is False
    assert result["tier1_findings"] == [], (
        f"42.4% should match 0.4244 within tolerance, got {result['tier1_findings']}"
    )


def test_no_cited_k_id_is_skipped():
    content = "å¸‚å ´ä»Šå¤©çš„æ³¢å‹•ç‡æ˜é¡¯æ”¾å¤§ï¼ŒVIX ä¾†åˆ° 18.5 çš„æ°´æº–ã€‚"
    result = audit_content_provenance(content, [], root=str(REPO_ROOT))
    assert result["skipped"] is True
    assert result["reason"] == "no_cited_source"
    assert result["tier1_findings"] == []


def test_missing_results_file_is_skipped(tmp_path: Path):
    # Cited K-id but no results.json on disk -> skip, do not block.
    result = audit_content_provenance(
        "Sharpe 2.0 çš„ç­–ç•¥ã€‚", ["K9999"], root=str(tmp_path)
    )
    assert result["skipped"] is True
    assert result["reason"] == "no_cited_source"


def test_years_not_treated_as_statistics():
    claims = extract_numeric_claims(
        "æˆ‘å€‘åœ¨ 2023 èˆ‡ 2024 å¹´çš„æ¨£æœ¬ä¸Šè¨ˆç®—æ³¢å‹•ç‡ï¼Œ2025 å¹´å»¶çºŒè¶¨å‹¢ã€‚"
    )
    values = {c["value"] for c in claims}
    # Bare years must be excluded even with æ³¢å‹•ç‡ nearby.
    assert 2023.0 not in values
    assert 2024.0 not in values
    assert 2025.0 not in values


def test_extract_requires_stat_context():
    # No stat keyword near the number -> not extracted.
    claims = extract_numeric_claims("é€™æœ¬æ›¸ä¸€å…±æœ‰ 300 é ã€‚")
    assert claims == []
    # Stat keyword present -> extracted.
    claims2 = extract_numeric_claims("å¹´åŒ–å ±é…¬ç‚º 30.0%ã€‚")
    assert any(c["value"] == 30.0 for c in claims2)


def test_load_source_values_is_verbatim_only():
    # Code-review Issue 1 (2026-06-03): source values are VERBATIM only â€” NO
    # blanket *100 / /100 seeding (which created a cross-scale false-match
    # cloud). 0.517 is present; its 51.7 cloud variant must NOT be seeded.
    vals = load_source_values(["K1413"], root=str(REPO_ROOT))
    assert any(abs(v - 0.517) < 1e-9 for v in vals)
    assert not any(abs(v - 51.7) < 1e-9 for v in vals)


def test_fabricated_bare_number_not_rescued_by_unit_cloud():
    # The fraction<->percent flexibility lives on the CLAIM side and only for
    # %-tagged numbers. A fabricated BARE Sharpe that happens to equal a source
    # leaf * 100 must still be flagged (no source-side cloud to rescue it).
    import json, tempfile
    from pathlib import Path
    d = tempfile.mkdtemp()
    kdir = Path(d) / "experiments" / "k9999"
    kdir.mkdir(parents=True)
    (kdir / "k9999_results.json").write_text(
        json.dumps({"corr": 0.025, "vol": 0.517, "sharpe": 0.83})
    )
    bad = audit_content_provenance("æœ¬ç­–ç•¥ Sharpe 2.5 é å‹å¤§ç›¤ã€‚", ["K9999"], root=d)
    assert [f["raw"] for f in bad["tier1_findings"]] == ["2.5"]
    # A %-tagged number still resolves via the claim-side /100 path.
    good = audit_content_provenance("å¹´åŒ–æ³¢å‹•ç‡é” 51.7%ã€‚", ["K9999"], root=d)
    assert good["tier1_findings"] == []


def test_negative_number_claims_match_verbatim_source():
    import json, tempfile
    from pathlib import Path
    d = tempfile.mkdtemp()
    kdir = Path(d) / "experiments" / "k725"
    kdir.mkdir(parents=True)
    (kdir / "k725_results.json").write_text(
        json.dumps({"strategy": {"high_sharpe": -6.66, "delta": -8.41}})
    )

    content = "å±æ©ŸæœŸ high_sharpe -6.66ï¼Œdelta -8.41ï¼Œä»£è¡¨ç­–ç•¥è¡¨ç¾æ€¥åŠ‡æƒ¡åŒ–ã€‚"
    result = audit_content_provenance(content, ["K725"], root=d)
    assert result["skipped"] is False
    assert result["tier1_findings"] == []


def test_negative_claim_without_source_match_is_flagged():
    import json, tempfile
    from pathlib import Path
    d = tempfile.mkdtemp()
    kdir = Path(d) / "experiments" / "k725"
    kdir.mkdir(parents=True)
    (kdir / "k725_results.json").write_text(
        json.dumps({"strategy": {"high_sharpe": -6.66, "delta": -8.41}})
    )

    bad = audit_content_provenance("å±æ©ŸæœŸ high_sharpe -7.00ã€‚", ["K725"], root=d)
    assert [f["raw"] for f in bad["tier1_findings"]] == ["-7.00"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))


# ï¿½”€ï¿½”€ image-URL gate (2026-06-08 ç¼ºï¿½œ– incident) ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€
from volpred.publisher.prepublish_audit import audit_image_urls


def test_experiments_path_image_blocked():
    c = "![ï¿½œ–1](https://volpred.zeabur.app/experiments/k674/k674_dd_heatmap.png)"
    r = audit_image_urls(c)
    assert r["total"] == 1
    assert len(r["broken"]) == 1
    assert "experiments" in r["broken"][0]["reason"]


def test_supabase_article_images_passes():
    c = "![ï¿½œ–1](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k674_dd_heatmap.png)"
    r = audit_image_urls(c)
    assert r["total"] == 1
    assert r["broken"] == []


def test_frontend_charts_passes():
    for url in (
        "https://volpred.zeabur.app/charts/k1046_timing_comparison.png",
        "/charts/k957_sankey.png",
    ):
        r = audit_image_urls(f"![c]({url})")
        assert r["broken"] == [], url


def test_placeholder_and_api_storage_and_local_blocked():
    c = (
        "![a](k674_PLACEHOLDER.png)\n"
        "![b](https://volpred.zeabur.app/api/storage/foo.png)\n"
        "![c](/Users/yhlai0911/Desktop/x.png)"
    )
    r = audit_image_urls(c)
    assert r["total"] == 3
    assert len(r["broken"]) == 3


def test_no_images_is_clean():
    r = audit_image_urls("ï¿½”ï¿½–‡ï¿½­—ï¿½’ï¿½œ‰ï¿½œ–ï¿½€‚")
    assert r["total"] == 0
    assert r["broken"] == []


# ï¿½”€ï¿½”€ non-stat label exclusions (2026-06-08 K1423 false-positive fix) ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€ï¿½”€
def test_tw_ticker_not_flagged_as_stat():
    # 0050 / 2330.TW next to å ±ï¿½…ï¿½/è¿´ï¿½­ï¿½ must NOT be a provenance claim.
    from volpred.publisher.prepublish_audit import extract_numeric_claims
    c = "ï¿½Šï¿½ï¿½”ï¿½ƒï¿½­ï¿½ 0050 ï¿½š„ alpha ï¿½€ï¿½–‹ï¿½‹å°±ï¿½é¡¯ï¿½‘—ï¿½›ï¿½ï¿½ï¿½ï¿½›ï¿½ 2330.TW å¹´ï¿½Œ–å ±ï¿½…ï¿½ï¿½€‚"
    raws = {x["raw"] for x in extract_numeric_claims(c)}
    assert "0050" not in raws
    assert "2330" not in raws


def test_index_name_500_not_flagged():
    from volpred.publisher.prepublish_audit import extract_numeric_claims
    c = "ï¿½ï¿½™ï¿½™ï¿½ 500ï¿½ˆSPYï¿½‰ï¿½šè¿´ï¿½­ï¿½ï¿½Œå¹´ï¿½Œ– alpha ï¿½„ 9.2%ï¿½€‚"
    raws = {x["raw"] for x in extract_numeric_claims(c)}
    assert "500" not in raws
    assert "9.2%" in raws  # real stat still caught


def test_methodology_constants_not_flagged():
    from volpred.publisher.prepublish_audit import extract_numeric_claims
    c = "t ï¿½€ï¿½ï¿½”ï¿½ Newey-West HACï¿½ˆlag=5ï¿½‰ï¿½—ï¿½›å¹´ï¿½Œ– alpha = ï¿½—ï¿½ alpha ï¿½— 252ï¿½€‚"
    raws = {x["raw"] for x in extract_numeric_claims(c)}
    assert "5" not in raws
    assert "252" not in raws
