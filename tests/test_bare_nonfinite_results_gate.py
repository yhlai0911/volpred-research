"""Results files must be readable by a spec-compliant JSON parser, not just Python's.

Python's ``json`` emits and accepts ``NaN`` / ``Infinity`` / ``-Infinity``, so a
results file containing them round-trips through every tool we own and every gate
we have stays green. They are not JSON: RFC 8259 has no such literals, and a
browser's ``JSON.parse``, Go's ``encoding/json``, ``serde_json`` and ``jq`` reject
the **entire document** rather than the offending field. The failure is invisible
locally and total downstream -- the article, the chart or the reviewer sees no
file at all.

A 2026-08-05 full-corpus scan (1527 files) found 52 real violations. The gate is a
ratchet: those 52 are frozen so the class is closed against new work, while the
backlog is cleared file by file. It is deliberately not a batch fix -- several of
those files are pinned by sha256 in reproduce_commit.json / review_verdict.json,
where editing one drifts a certification and forces a re-review.

The criterion is the parser. A regex prefilter flagged 70 files, but in 18 of them
the token sits inside a string value, which is legal JSON that must not be
"fixed" -- so a regex-based gate would have sent someone to damage 18 good files.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GATE_PATH = REPO / "scripts" / "check_experiment_artifacts.py"
BASELINE_PATH = REPO / "config" / "bare_nonfinite_results_baseline.json"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("artifact_gate_under_test", GATE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _experiment(tmp_path: Path, body: str, name: str = "k9999") -> Path:
    exp = tmp_path / "experiments" / name
    exp.mkdir(parents=True)
    (exp / f"{name}_results.json").write_text(body, encoding="utf-8")
    return exp


def test_a_bare_nan_in_a_new_experiment_is_blocked(tmp_path, gate):
    exp = _experiment(tmp_path, '{"qlike": NaN, "n": 500}')

    violation, status = gate._nonfinite_violation(exp, set(), root=tmp_path)

    assert status == "violation"
    assert "NaN" in violation and "JSON.parse" in violation
    assert "producing script" in violation, (
        "the message must point at the producer; telling someone to hand-edit the "
        "JSON is how a pinned result silently drifts"
    )


def test_bare_infinity_counts_too(tmp_path, gate):
    exp = _experiment(tmp_path, '{"ratio": -Infinity}')

    _, status = gate._nonfinite_violation(exp, set(), root=tmp_path)

    assert status == "violation"


def test_the_token_inside_a_string_is_legal_json_and_must_pass(tmp_path, gate):
    """18 of the 70 regex hits were exactly this. A regex gate would break them."""
    exp = _experiment(tmp_path, '{"note": "QLIKE was NaN for 3 days", "n": 500}')

    violation, status = gate._nonfinite_violation(exp, set(), root=tmp_path)

    assert violation is None
    assert status == "clean"


def test_a_frozen_file_stays_mergeable(tmp_path, gate):
    exp = _experiment(tmp_path, '{"qlike": NaN}')
    frozen = {"experiments/k9999/k9999_results.json"}

    violation, status = gate._nonfinite_violation(exp, frozen, root=tmp_path)

    assert violation is None
    assert status == "baseline(1)"


def test_the_ratchet_only_ever_shrinks(gate):
    """Every frozen path must still violate; a fixed one must leave the list.

    Without this the baseline rots into an amnesty list: a path could be fixed,
    or renamed, or deleted, and the entry would sit there forever quietly
    licensing a future file at the same path.
    """
    entries = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))["entries"]
    stale = []
    for rel in entries:
        path = REPO / rel
        if not path.is_file():
            stale.append(f"{rel} (gone)")
            continue
        if not gate.rejects_as_strict_json(path.read_text(encoding="utf-8")):
            stale.append(f"{rel} (now valid JSON — drop it and keep the win)")

    assert not stale, (
        "config/bare_nonfinite_results_baseline.json is out of date; remove:\n  "
        + "\n  ".join(stale)
    )


def test_the_baseline_is_a_backlog_not_a_blank_cheque(gate):
    """A baseline covering everything would be indistinguishable from no gate."""
    entries = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))["entries"]

    assert entries, "an empty baseline means the class is closed — delete the file instead"
    assert len(entries) < 200, (
        "the frozen backlog has grown; the ratchet is supposed to move one way"
    )
    assert all(e.startswith("experiments/") for e in entries), (
        "scope creep: this gate covers experiment results only"
    )
