"""_classify_codex_session: coarse, provenance-honest Codex attribution.

Regression for 2026-08-05 (boss email-12201): 47.7% of the weekly bill sat in
one opaque "unclassified" bucket because Codex token_count has no task
metadata. Attribution now derives from session_meta signals only — no
invented task-ids. Locks: each bucket's trigger, precedence (review beats
cwd), and the honest fallback when no signal matches.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "token_usage_report", REPO_ROOT / "scripts" / "token_usage_report.py"
)
tur = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(tur)

C = tur._classify_codex_session
MAIN = "/Users/x/volpred-research"
KWT = "/Users/x/volpred-research/.claude/worktrees/dispatch-slot-1-ab12cd34-k1735"
OWT = "/Users/x/volpred-research/.claude/worktrees/dispatch-slot-1-ab12cd34"


def test_auto_review_model_wins_over_everything():
    assert C(KWT, "codex_exec", "codex-auto-review") == "codex_review"


def test_review_originator_wins():
    assert C(MAIN, "codex_auto_review", "gpt-5.6-sol") == "codex_review"


def test_k_worktree_is_experiment():
    assert C(KWT, "codex_exec", "gpt-5.6-sol") == "experiment"
    assert C(KWT.replace("k1735", "K1746"), "codex_exec", "gpt-5.6-sol") == "experiment"


def test_non_k_worktree_is_agent_ops():
    assert C(OWT, "codex_exec", "gpt-5.6-sol") == "codex_agent_ops"


def test_main_checkout_exec():
    assert C(MAIN, "codex_exec", "gpt-5.6-sol") == "codex_exec"


def test_desktop_variants():
    assert C(MAIN, "codex_work_desktop", "gpt-5.6-sol") == "codex_desktop"
    assert C(MAIN, "Codex Desktop", "gpt-5.6-sol") == "codex_desktop"


def test_no_signal_stays_honestly_unclassified():
    assert C("", "", "") == "unclassified"
    assert C(MAIN, "mystery_tool", "gpt-5.6-sol") == "unclassified"


def test_all_buckets_have_display_labels():
    for cat in ("codex_review", "codex_exec", "codex_agent_ops", "codex_desktop"):
        assert cat in tur.CATEGORY_META, f"{cat} missing from CATEGORY_META"
