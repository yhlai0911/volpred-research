"""Tests for src/volpred/research/conclusion_lint.py.

Covers:
- Clean conclusions (no warnings)
- Each rule R1-R4 triggers
- DM cross-check both directions (R2)
- K947 OLD (must warn ≥3) vs NEW (must be clean) fixture
- Strict mode env var + flag
- Edge cases: empty, None, multiline, mixed CN/EN, dict payload
"""

from __future__ import annotations

import os

import pytest

from volpred.research.conclusion_lint import (
    extract_conclusion_text,
    lint_conclusion,
    lint_results_payload,
)


# ---------------------------------------------------------------------------
# Clean cases
# ---------------------------------------------------------------------------


def test_clean_conclusion_with_pair_and_numeric():
    text = "MF-GJR vs GJR Harvey t=3.21 (significant). Improvement +5.1%."
    assert lint_conclusion(text) == []


def test_empty_and_none():
    assert lint_conclusion("") == []
    assert lint_conclusion(None) == []


def test_clean_neutral_prose():
    text = "We fit GARCH and GJR on SPY. Fit converged. See dm_table for tests."
    assert lint_conclusion(text) == []


# ---------------------------------------------------------------------------
# R1: trigger words without numeric/pair
# ---------------------------------------------------------------------------


def test_r1_dominates_without_backing():
    text = "Strategy A dominates everything else."
    warnings = lint_conclusion(text)
    assert any(w.startswith("[R1]") for w in warnings)


def test_r1_pass_with_pair_is_clean():
    text = "MF-GJR_vs_GJR PASS at Harvey t=3.5."
    warnings = lint_conclusion(text)
    # Pair + numeric present in same sentence — R1 should not fire
    assert not any(w.startswith("[R1]") for w in warnings)


def test_r1_chinese_trigger():
    text = "本策略主導其他基準。"  # 主導 without numeric / pair
    warnings = lint_conclusion(text)
    assert any(w.startswith("[R1]") for w in warnings)


def test_r1_outperforms_with_percent_is_clean():
    text = "T-GJR outperforms GARCH by 13.7%."
    warnings = lint_conclusion(text)
    assert not any(w.startswith("[R1]") for w in warnings)


# ---------------------------------------------------------------------------
# R2: DM cross-check
# ---------------------------------------------------------------------------


def test_r2_claim_contradicts_dm():
    # GARCH_vs_GJR: t_stat = loss_GARCH - loss_GJR; positive → GJR has lower loss → GJR wins
    # Claim "GARCH dominates GJR" contradicts DM evidence that GJR wins → should warn
    text = "GARCH dominates GJR."
    dm = {"GARCH_vs_GJR": {"t_stat": 2.5, "p_value": 0.01}}
    warnings = lint_conclusion(text, dm_tests=dm)
    assert any(w.startswith("[R2]") for w in warnings)


def test_r2_claim_consistent_with_dm():
    # GARCH_vs_GJR: t_stat negative → GARCH has lower loss → GARCH wins
    # Claim "GARCH dominates GJR" is consistent with DM evidence → no warning
    text = "GARCH dominates GJR."
    dm = {"GARCH_vs_GJR": {"t_stat": -3.5, "p_value": 0.001}}
    warnings = lint_conclusion(text, dm_tests=dm)
    assert not any(w.startswith("[R2]") for w in warnings)


def test_r2_reverse_key_lookup():
    # Key is "GARCH_vs_GJR": t_stat = loss_GARCH - loss_GJR; negative → GARCH wins
    # Claim "GJR beats GARCH" contradicts DM evidence that GARCH wins → should warn
    text = "GJR beats GARCH."
    dm = {"GARCH_vs_GJR": {"t_stat": -2.5}}  # negative ⇒ GARCH wins ⇒ contradicts "GJR beats GARCH"
    warnings = lint_conclusion(text, dm_tests=dm)
    assert any(w.startswith("[R2]") for w in warnings)


# ---------------------------------------------------------------------------
# R3: Harvey without pair specifier
# ---------------------------------------------------------------------------


def test_r3_harvey_no_pair():
    text = "Harvey: Yes."
    warnings = lint_conclusion(text)
    assert any(w.startswith("[R3]") for w in warnings)


def test_r3_harvey_with_pair_clean():
    text = "Harvey on MF-GJR_vs_GJR: t=3.21."
    warnings = lint_conclusion(text)
    assert not any(w.startswith("[R3]") for w in warnings)


def test_r3_chinese_strict_stat():
    text = "嚴格統計通過。"
    warnings = lint_conclusion(text)
    # 嚴格統計 (R3) AND 通過 (R1) both fire
    assert any(w.startswith("[R3]") for w in warnings)


# ---------------------------------------------------------------------------
# R4: vague qualifier alone
# ---------------------------------------------------------------------------


def test_r4_vague_alone():
    text = "結果明顯改善。"
    warnings = lint_conclusion(text)
    assert any(w.startswith("[R4]") for w in warnings)


def test_r4_vague_with_numeric_clean():
    text = "結果明顯改善 +5.2%。"
    warnings = lint_conclusion(text)
    assert not any(w.startswith("[R4]") for w in warnings)


# ---------------------------------------------------------------------------
# Multiline / mixed-language
# ---------------------------------------------------------------------------


def test_multiline_only_problem_sentence_flagged():
    text = (
        "We tested GARCH and GJR on SPY 2010-2025.\n"
        "Strategy outperforms baseline.\n"  # vague
        "DM result: GARCH_vs_GJR t=2.1, p=0.04."
    )
    warnings = lint_conclusion(text)
    assert any("outperforms" in w for w in warnings)


def test_mixed_chinese_english():
    text = "K947 PASS Harvey threshold 通過 with t=3.5 on MF-GJR_vs_GJR."
    warnings = lint_conclusion(text)
    # has pair + numeric → all rules silent
    assert warnings == []


# ---------------------------------------------------------------------------
# K947 OLD vs NEW fixture
# ---------------------------------------------------------------------------


# K947 OLD (pre-fix) — the actual ambiguous form that triggered the incident.
K947_OLD_CONCLUSION = (
    "Threshold GARCH 結果：Harvey: Yes. "
    "MF-GJR 顯著勝過 GARCH。模型主導其他基準。"
)

# K947 NEW (post-fix) — pair + numeric backing in each sentence.
K947_NEW_CONCLUSION = (
    "Threshold GARCH on MF-GJR_vs_GJR: Harvey t=3.21 (PASS at t>3.0). "
    "MF-GJR vs GARCH improvement +6.6% (DM p=0.001). "
    "Other thresholds (c=15/18/20/22/25) tested but none exceed Harvey on MF-GJR_vs_GARCH."
)


def test_k947_old_warns_at_least_three():
    warnings = lint_conclusion(K947_OLD_CONCLUSION)
    assert len(warnings) >= 3, f"expected ≥3 warnings, got {len(warnings)}: {warnings}"


def test_k947_new_clean():
    warnings = lint_conclusion(K947_NEW_CONCLUSION)
    assert warnings == [], f"expected clean, got {warnings}"


# ---------------------------------------------------------------------------
# extract_conclusion_text
# ---------------------------------------------------------------------------


def test_extract_from_dict_conclusion():
    payload = {
        "experiment_id": "K999",
        "conclusion": {
            "main": "GARCH dominates GJR.",
            "secondary": "see dm table.",
        },
    }
    text = extract_conclusion_text(payload)
    assert text and "dominates" in text


def test_extract_handles_missing():
    assert extract_conclusion_text({"experiment_id": "K1"}) is None


def test_extract_from_list_conclusions_field():
    payload = {
        "conclusions": ["A dominates B.", "ratio 2.5x."],
    }
    text = extract_conclusion_text(payload)
    assert text and "dominates" in text and "2.5x" in text


# ---------------------------------------------------------------------------
# lint_results_payload + strict mode
# ---------------------------------------------------------------------------


def test_lint_results_payload_warn_only_default():
    payload = {"conclusion": "Strategy dominates baseline."}
    warnings = lint_results_payload(payload)
    assert len(warnings) >= 1


def test_lint_results_payload_strict_flag_raises():
    payload = {"conclusion": "Strategy dominates baseline."}
    with pytest.raises(ValueError, match="strict mode"):
        lint_results_payload(payload, strict=True)


def test_lint_results_payload_strict_env_var_raises(monkeypatch):
    monkeypatch.setenv("VOLPRED_LINT_STRICT", "1")
    payload = {"conclusion": "Strategy dominates baseline."}
    with pytest.raises(ValueError):
        lint_results_payload(payload)


def test_lint_results_payload_strict_clean_passes(monkeypatch):
    monkeypatch.setenv("VOLPRED_LINT_STRICT", "1")
    payload = {
        "conclusion": "MF-GJR_vs_GJR Harvey t=3.21 PASS, improvement +6.6%."
    }
    # No warnings → no raise even in strict
    assert lint_results_payload(payload) == []


def test_lint_results_payload_dm_tests_used():
    # t_stat = +2.0 → positive → GJR wins (lower loss) → contradicts "GARCH dominates GJR" → [R2] fires
    payload = {
        "conclusion": "GARCH dominates GJR.",
        "dm_tests": {"GARCH_vs_GJR": {"t_stat": 2.0}},
    }
    warnings = lint_results_payload(payload)
    assert any(w.startswith("[R2]") for w in warnings)


def test_lint_results_payload_no_conclusion_field():
    # 199 INDETERMINATE files in audit — must not warn
    payload = {"experiment_id": "K1000", "metrics": {"QLIKE": 1.5}}
    assert lint_results_payload(payload) == []
