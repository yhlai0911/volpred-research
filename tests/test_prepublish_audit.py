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
        "我們的策略在樣本內取得了 Sharpe 1.42 的優異表現，"
        "顯著優於 baseline 的 Sharpe 0.61。"
    )
    result = audit_content_provenance(content, ["K562"], root=str(k562_root))
    assert result["skipped"] is False
    raws = {f["raw"] for f in result["tier1_findings"]}
    assert "1.42" in raws  # fabricated number caught
    assert "0.61" not in raws  # the legitimate one is NOT flagged


def test_real_k1413_numbers_all_hit():
    # All three numbers exist in k1413_results.json:
    #   0.517 = full_period_annualized_vol['L3 基礎設施']
    #   0.4244 = rolling_vol_summary['L2 晶片'].latest
    #   0.6452 = avg_cross_layer_corr_by_period['2025至今']
    content = (
        "基礎設施層的全期年化波動率達 0.517，是四籃中最高。"
        "晶片層最新年化波動率為 0.4244。"
        "2025 年以來的平均跨層相關係數升至 0.6452。"
    )
    result = audit_content_provenance(content, ["K1413"], root=str(REPO_ROOT))
    assert result["skipped"] is False
    assert result["tier1_findings"] == [], (
        f"unexpected findings: {result['tier1_findings']}"
    )
    assert result["n_claims"] >= 3


def test_percent_unit_conversion_no_false_alarm():
    # Article writes 42.4% ; source stores 0.4244 (L2 晶片 latest).
    content = "晶片層最新年化波動率約為 42.4%。"
    result = audit_content_provenance(content, ["K1413"], root=str(REPO_ROOT))
    assert result["skipped"] is False
    assert result["tier1_findings"] == [], (
        f"42.4% should match 0.4244 within tolerance, got {result['tier1_findings']}"
    )


def test_no_cited_k_id_is_skipped():
    content = "市場今天的波動率明顯放大，VIX 來到 18.5 的水準。"
    result = audit_content_provenance(content, [], root=str(REPO_ROOT))
    assert result["skipped"] is True
    assert result["reason"] == "no_cited_source"
    assert result["tier1_findings"] == []


def test_missing_results_file_is_skipped(tmp_path: Path):
    # Cited K-id but no results.json on disk -> skip, do not block.
    result = audit_content_provenance(
        "Sharpe 2.0 的策略。", ["K9999"], root=str(tmp_path)
    )
    assert result["skipped"] is True
    assert result["reason"] == "no_cited_source"


def test_years_not_treated_as_statistics():
    claims = extract_numeric_claims(
        "我們在 2023 與 2024 年的樣本上計算波動率，2025 年延續趨勢。"
    )
    values = {c["value"] for c in claims}
    # Bare years must be excluded even with 波動率 nearby.
    assert 2023.0 not in values
    assert 2024.0 not in values
    assert 2025.0 not in values


def test_extract_requires_stat_context():
    # No stat keyword near the number -> not extracted.
    claims = extract_numeric_claims("這本書一共有 300 頁。")
    assert claims == []
    # Stat keyword present -> extracted.
    claims2 = extract_numeric_claims("年化報酬為 30.0%。")
    assert any(c["value"] == 30.0 for c in claims2)


def test_load_source_values_seeds_unit_variants():
    vals = load_source_values(["K1413"], root=str(REPO_ROOT))
    # 0.517 present; *100 and /100 variants seeded.
    assert any(abs(v - 0.517) < 1e-9 for v in vals)
    assert any(abs(v - 51.7) < 1e-9 for v in vals)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
