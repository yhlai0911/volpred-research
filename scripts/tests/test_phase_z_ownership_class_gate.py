"""Class-level gate for the PHASE-Z ownership bug class (error_log §B).

This file does NOT test behaviour. It pins a *design decision* so the next person
cannot quietly extend the abstraction that has already failed six times.

Background — `docs/governance/2026-07/phase_z_ownership_external_review.md`:
PHASE-Z decides authorship with ``owned = dirty_now - baseline``, i.e. "first
observed dirty inside this window". On a checkout shared by ~24 machine writers a
day plus human and codex sessions that is not ownership at all, and no amount of
after-the-fact reasoning recovers it. The external review's verdict, verbatim:

    你一直在讓 cleanup layer 解 ownership。Ownership 必須由 execution isolation
    產生，不能由 cleanup layer 事後推理。

Every previous fix in this class added one more way to *guess* the producer from
a result feature — directory, suffix, mtime, receipt, "this file turns a test
green". Each shipped tests, closed green, and the pile-up came back. So the rule
this file enforces is D1 of that document: **stop adding guesses**.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PHASE_Z = REPO_ROOT / "scripts" / "dispatch_supervisor" / "phase_z.py"
NAMESPACES = REPO_ROOT / "config" / "orphan_namespaces.json"
DECISION_DOC = "docs/governance/2026-07/phase_z_ownership_external_review.md"

# The complete, deliberately frozen census of "infer the producer from a result
# feature" sites. Adding a fourth is the exact move that failed six times; the
# fix direction is D4 (producer-scoped workspace), not a fourth guess.
KNOWN_PROVENANCE_GUESSES = frozenset({"_adopt_orphan_halves"})

# Directories whose contents the reaper may adopt on directory membership alone.
KNOWN_ADOPTABLE_NAMESPACES = frozenset({"drafts", "experiments", "paper"})

# The symbol D2 will introduce: an immutable ref that stuck foreign bytes are
# checkpointed to. Pinned by name so the xfail below flips on the real landing,
# not on the word "quarantine" appearing anywhere (it already does, for corrupt
# receipts — an unrelated use).
QUARANTINE_MARKER = "_FOREIGN_QUARANTINE_REF_PREFIX"


def _phase_z_tree() -> ast.Module:
    return ast.parse(PHASE_Z.read_text(encoding="utf-8"))


def test_no_new_adoption_heuristic_is_added_to_phase_z() -> None:
    """A new ``_adopt_*`` helper = a new way to guess authorship. Read D1 first."""
    adopters = {
        node.name
        for node in ast.walk(_phase_z_tree())
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_adopt_")
    }
    assert adopters == KNOWN_PROVENANCE_GUESSES, (
        f"phase_z.py adoption heuristics changed: {sorted(adopters)}.\n"
        f"Adding one is the move that has already failed 6 times — see {DECISION_DOC} §4 D1.\n"
        "If you genuinely need it, update this gate in the same commit and say why in the body."
    )


def test_orphan_namespaces_stays_a_declaration_not_a_recognizer_zoo() -> None:
    """`experiments/` membership is *semantics-as-provenance* — a directory cannot
    prove authorship, completeness or readiness. K1380's eight stranded files,
    three of them explicitly named ``*_INVALID_20260716.*``, are the live
    counter-example. The registry may stay declarative; it may not grow code."""
    payload = json.loads(NAMESPACES.read_text(encoding="utf-8"))
    declared = {entry["id"] for entry in payload["namespaces"]}
    assert declared == KNOWN_ADOPTABLE_NAMESPACES, (
        f"orphan_namespaces.json membership changed: {sorted(declared)}.\n"
        f"A directory cannot prove authorship — see {DECISION_DOC} §6. Widening the\n"
        "registry is allowed, but it is a judgement call about *someone else's* unfinished\n"
        "work, so make it deliberately: update this set in the same commit and justify it."
    )


def test_decision_document_exists() -> None:
    """The gate is only meaningful while the reasoning behind it is reachable."""
    doc = REPO_ROOT / DECISION_DOC
    assert doc.is_file(), f"missing {DECISION_DOC} — this gate's rationale is gone"
    text = doc.read_text(encoding="utf-8")
    assert "Ownership 必須由 execution isolation 產生" in text


def test_stuck_foreign_paths_have_a_durable_exit_besides_alerting() -> None:
    """A dirty working tree is not preservation: the bytes can be overwritten by
    the next writer, reset by a human, or swept by a cleanup pass. Until an
    uncertain path is checkpointed somewhere immutable, "never lose" is 0/1 —
    we only satisfy "never sweep into main".

    D2 landed on 2026-07-19, so the xfail-strict this used to carry became a real
    assertion (the docstring above it said to flip it on landing). What it pins is
    only that the *exit exists* in phase_z.py and that the stuck-path branch
    actually reaches it — the behavioural proof (working tree byte-identical, HEAD
    unmoved, content retrievable via ``git show``, live-flock paths skipped) is in
    ``scripts/tests/test_phase_z_quarantine_checkpoint.py`` against real git.
    """
    source = PHASE_Z.read_text(encoding="utf-8")
    assert QUARANTINE_MARKER in source, (
        f"the durable exit for stuck foreign paths is gone — see {DECISION_DOC} §4 D2.\n"
        "Alerting alone is what produced 78 fires of zero action."
    )
    tree = _phase_z_tree()
    checkpointers = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and "quarantine" in node.name
    }
    assert checkpointers, "the quarantine constant exists but nothing implements it"
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert checkpointers & called, (
        f"quarantine helpers {sorted(checkpointers)} are defined but never called — "
        "a preservation path nothing invokes is the same 0/1 as no path at all."
    )
