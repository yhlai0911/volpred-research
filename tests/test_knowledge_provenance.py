"""Tests for K1259 audit follow-up T3 — knowledge.json provenance gate.

Verifies:
- PASS verdict without experiment_id → ValueError
- PASS verdict with experiment_id but no reviewer → ValueError
- PASS verdict with full provenance → passes
- CONDITIONAL_PASS without experiment_id → ValueError
- CONDITIONAL_PASS with experiment_id (no reviewer required) → passes
- NULL / FAIL / MIXED verdicts without provenance → passes (not gated)
- Entry without `verdict` field → passes
- _append_to_index path enforces the same gate when filename=='knowledge.json'
- Other memory files (thinking_journal etc.) are NOT gated

See: docs/knowledge_k1259_audit_2026_05_17.md
     docs/knowledge_k1259_audit_v2_2026_05_17.md
     .claude/rules/experiments.md (K1259 section)
"""
from __future__ import annotations

import pytest

from volpred.memory.provenance import (
    KNOWN_VIOLATION_BASELINE,
    count_violations,
    validate_provenance,
)


# ---------------------------------------------------------------------------
# Direct validate_provenance() — fast unit
# ---------------------------------------------------------------------------


def test_pass_without_experiment_id_raises():
    entry = {"item_id": "abc123", "verdict": "PASS", "content": "claim"}
    with pytest.raises(ValueError, match="K1259 provenance violation"):
        validate_provenance(entry)


def test_pass_with_experiment_id_but_no_reviewer_raises():
    entry = {
        "item_id": "abc124",
        "verdict": "PASS",
        "experiment_id": "K9999",
        "content": "claim",
    }
    with pytest.raises(ValueError, match="reviewer attribution"):
        validate_provenance(entry)


def test_pass_with_full_provenance_ok():
    entry = {
        "item_id": "abc125",
        "verdict": "PASS",
        "experiment_id": "K9999",
        "reviewer_source": "Codex review",
        "content": "claim",
    }
    validate_provenance(entry)  # no raise


def test_pass_with_codex_review_ok():
    entry = {
        "item_id": "abc126",
        "verdict": "PASS",
        "experiment_ids": ["K9999"],
        "codex_review": "PASS - no issues",
        "content": "claim",
    }
    validate_provenance(entry)  # no raise


def test_conditional_pass_without_experiment_id_raises():
    entry = {"item_id": "abc127", "verdict": "CONDITIONAL_PASS", "content": "claim"}
    with pytest.raises(ValueError, match="K1259 provenance violation"):
        validate_provenance(entry)


def test_conditional_pass_with_experiment_id_no_reviewer_ok():
    # CONDITIONAL_PASS only needs provenance, not reviewer (less strict)
    entry = {
        "item_id": "abc128",
        "verdict": "CONDITIONAL_PASS",
        "experiment_id": "K9999",
        "content": "claim",
    }
    validate_provenance(entry)  # no raise


def test_null_verdict_without_provenance_ok():
    entry = {"item_id": "abc129", "verdict": "NULL", "content": "null result"}
    validate_provenance(entry)  # no raise


def test_fail_verdict_without_provenance_ok():
    entry = {"item_id": "abc130", "verdict": "FAIL", "content": "did not work"}
    validate_provenance(entry)  # no raise


def test_mixed_verdict_without_provenance_ok():
    entry = {"item_id": "abc131", "verdict": "MIXED", "content": "partial"}
    validate_provenance(entry)  # no raise


def test_no_verdict_field_ok():
    entry = {"item_id": "abc132", "content": "narrative", "category": "observation"}
    validate_provenance(entry)  # no raise — legacy unstructured entries unaffected


def test_pass_with_empty_string_experiment_id_raises():
    entry = {
        "item_id": "abc133",
        "verdict": "PASS",
        "experiment_id": "",
        "reviewer": "Codex",
        "content": "claim",
    }
    with pytest.raises(ValueError, match="K1259 provenance violation"):
        validate_provenance(entry)


def test_pass_with_empty_list_experiment_ids_raises():
    entry = {
        "item_id": "abc134",
        "verdict": "PASS",
        "experiment_ids": [],
        "reviewer": "Codex",
        "content": "claim",
    }
    with pytest.raises(ValueError, match="K1259 provenance violation"):
        validate_provenance(entry)


def test_verdict_with_suffix_not_gated():
    # PASS_NULL / "CONDITIONAL_PASS (SIMULATION)..." are historical suffix
    # variants — we gate only the canonical strings to avoid over-broad
    # gating. Suffix variants pass through (not the design target of T3).
    entry = {"item_id": "abc135", "verdict": "PASS_NULL", "content": "x"}
    validate_provenance(entry)  # no raise


# ---------------------------------------------------------------------------
# Integration — _append_to_index respects the gate for knowledge.json only
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_memory(tmp_path, monkeypatch):
    """Spin up a MemorySystem in an isolated temp dir, no network sync."""
    # Disable Mirror sync entirely to keep test offline + fast
    monkeypatch.setenv("VOLPRED_MIRROR_URL", "")
    monkeypatch.setenv("RESEARCH_MIRROR_TOKEN", "")
    from volpred.memory.system import MemorySystem

    return MemorySystem(storage_dir=str(tmp_path))


def test_append_to_knowledge_rejects_unprovenanced_pass(isolated_memory):
    bad = {"item_id": "bad1", "verdict": "PASS", "content": "claim"}
    with pytest.raises(ValueError, match="K1259 provenance violation"):
        isolated_memory._append_to_index("knowledge.json", bad)


def test_append_to_knowledge_accepts_clean_pass(isolated_memory):
    good = {
        "item_id": "good1",
        "verdict": "PASS",
        "experiment_id": "K9999",
        "reviewer_source": "Codex review",
        "content": "claim",
    }
    isolated_memory._append_to_index("knowledge.json", good)  # no raise

    # Verify it landed
    items = isolated_memory.get_knowledge()
    assert any(i.get("item_id") == "good1" for i in items)


def test_append_to_thinking_journal_not_gated(isolated_memory):
    # thinking_journal entries do not have verdicts, but even a hypothetical
    # one with PASS-no-provenance should pass — gate is knowledge.json only.
    entry = {"id": "tj1", "verdict": "PASS", "thought": "spec test"}
    isolated_memory._append_to_index("thinking_journal.json", entry)  # no raise


def test_append_to_knowledge_null_verdict_ok(isolated_memory):
    entry = {"item_id": "n1", "verdict": "NULL", "content": "null result"}
    isolated_memory._append_to_index("knowledge.json", entry)  # no raise


# ---------------------------------------------------------------------------
# count_violations sanity
# ---------------------------------------------------------------------------


def test_count_violations_sanity():
    entries = [
        {"item_id": "1", "verdict": "PASS"},  # violation (no prov)
        {"item_id": "2", "verdict": "PASS", "experiment_id": "K1", "reviewer": "C"},  # ok
        {"item_id": "3", "verdict": "NULL"},  # ok
        {"item_id": "4", "verdict": "CONDITIONAL_PASS"},  # violation
    ]
    assert count_violations(entries) == 2


def test_baseline_constant_matches_audit():
    # Hard baseline 284 documented in docs/knowledge_k1259_audit_v2_2026_05_17.md
    # (v1 V1 200 + V2 7 + V3 1 + v2 numeric-near-keyword 76 = 284).
    # If audit re-counts move this number, update this constant + the audit doc.
    assert KNOWN_VIOLATION_BASELINE == 284
