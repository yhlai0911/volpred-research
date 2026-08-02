"""The artifact-completeness gate must block, and must block only what it should.

2026-07-19 CI went red three dispatch hours in a row because experiments reached
main while their knowledge entry / reproduce_spec did not (k1732, then k1719).
``scripts/check_experiment_artifacts.py`` freezes that class at both doors
(``merge_worktree.sh`` and ``.github/workflows/experiment-artifacts.yml``).

Two failure modes are tested here, and the second matters as much as the first:
a gate that blocks a result-less directory forces someone to invent a knowledge
entry for a run that produced no finding — fabricated history is the exact thing
this gate exists to prevent.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import check_experiment_artifacts as gate

from volpred.research import reproduce_spec as rs


def _experiment(root: Path, name: str, *, results: bool = True, spec: bool = True) -> Path:
    exp = root / "experiments" / name
    exp.mkdir(parents=True)
    if results:
        (exp / f"{name}_results.json").write_text(
            json.dumps({"qlike": 0.42}), encoding="utf-8"
        )
    if spec:
        (exp / "run.py").write_text("print('ok')\n", encoding="utf-8")
        # Shape copied from experiments/k1719 — the gate validates through
        # reproduce_check.load_spec when it can import it, so a spec that only
        # satisfies the structural fallback would pass here and fail in CI.
        (exp / gate.SPEC_NAME).write_text(json.dumps({
            "schema_version": gate.SPEC_SCHEMA,
            "entrypoint": {"path": "run.py", "args": []},
            "canonical_result": f"{name}_results.json",
            "inputs": [],
            "timeout_seconds": 900,
            "network": "deny",
            "randomness": {"status": "not_applicable"},
            "comparison": {"rtol": 1e-9, "atol": 1e-12,
                           "ignore_pointers": [], "ignore_reasons": {}},
        }), encoding="utf-8")
    return exp


def test_experiment_with_results_but_no_knowledge_entry_is_blocked(tmp_path: Path) -> None:
    exp = _experiment(tmp_path, "k9001", spec=True)
    record = gate.audit_experiment(exp, knowledge_ids=set(), exclusions={})
    assert record["gated"] is True
    assert record["has_knowledge_entry"] is False
    assert any("knowledge.json" in v for v in record["violations"])


def test_experiment_without_reproduce_spec_is_blocked(tmp_path: Path) -> None:
    exp = _experiment(tmp_path, "k9002", spec=False)
    record = gate.audit_experiment(exp, knowledge_ids={"k9002"}, exclusions={})
    assert record["gated"] is True
    assert any(gate.SPEC_NAME in v for v in record["violations"])


def test_complete_experiment_passes(tmp_path: Path) -> None:
    exp = _experiment(tmp_path, "k9003")
    record = gate.audit_experiment(exp, knowledge_ids={"k9003"}, exclusions={})
    assert record["gated"] is True
    assert record["violations"] == []


def test_runtime_result_number_tamper_is_blocked(tmp_path: Path) -> None:
    """K1708-class edits must fail even when the producing code is unchanged."""
    exp = tmp_path / "experiments" / "k9010"
    exp.mkdir(parents=True)
    entry = exp / "k9010.py"
    entry.write_text("print('science')\n", encoding="utf-8")
    results_path, _spec = rs.finalize_experiment(
        results={
            "cw": {"t_stat": 1.968775},
            "qlike": 0.42,
            "verdict": {"label": "NULL"},
        },
        entrypoint=entry,
        canonical_result="k9010_results.json",
        exp_dir=exp,
    )
    before = gate.audit_experiment(
        exp,
        knowledge_ids={"k9010"},
        exclusions={},
    )
    assert before["violations"] == []
    assert before["canonical_result_identity"] == "clean"

    tampered = json.loads(results_path.read_text(encoding="utf-8"))
    tampered["cw"]["t_stat"] = 3.5
    results_path.write_text(
        json.dumps(tampered, indent=2) + "\n",
        encoding="utf-8",
    )

    record = gate.audit_experiment(
        exp,
        knowledge_ids={"k9010"},
        exclusions={},
    )

    assert any(
        "canonical result identity" in violation
        for violation in record["violations"]
    )


def test_runtime_declared_output_tamper_is_blocked(tmp_path: Path) -> None:
    exp = tmp_path / "experiments" / "k9011"
    exp.mkdir(parents=True)
    entry = exp / "k9011.py"
    entry.write_text("print('science')\n", encoding="utf-8")
    chart = exp / "chart.png"
    chart.write_bytes(b"chart-v1")
    rs.finalize_experiment(
        results={"verdict": "NULL"},
        entrypoint=entry,
        canonical_result="k9011_results.json",
        exp_dir=exp,
        outputs=["chart.png"],
    )
    chart.write_bytes(b"chart-v2")

    record = gate.audit_experiment(exp, knowledge_ids={"k9011"}, exclusions={})
    assert record["artifact_generation"] == "output-mismatch"
    assert any("declared output identity mismatch" in v for v in record["violations"])


def test_runtime_partial_generation_is_blocked_by_completion_receipt(
    tmp_path: Path,
) -> None:
    exp = tmp_path / "experiments" / "k9012"
    exp.mkdir(parents=True)
    entry = exp / "k9012.py"
    entry.write_text("print('science')\n", encoding="utf-8")
    results_path, _ = rs.finalize_experiment(
        results={"stage": 1},
        entrypoint=entry,
        canonical_result="k9012_results.json",
        exp_dir=exp,
    )
    # Simulate termination after a new result became visible but before the
    # completion receipt was promoted.
    results_path.write_text('{"stage": 2}\n', encoding="utf-8")

    record = gate.audit_experiment(exp, knowledge_ids={"k9012"}, exclusions={})
    assert record["artifact_generation"] in {"result-mismatch", "commit-mismatch"}
    assert record["violations"]


def test_directory_with_no_results_is_not_gated(tmp_path: Path) -> None:
    """No archived result = no finding to record and no output to pin.

    Gating these would demand a knowledge entry for a run that produced nothing —
    the 2026-07-19 sweep found 232 such directories (paper-writing sessions,
    ``.gitkeep`` placeholders, abandoned stubs).
    """
    exp = _experiment(tmp_path, "k9004", results=False, spec=False)
    record = gate.audit_experiment(exp, knowledge_ids=set(), exclusions={})
    assert record["gated"] is False
    assert record["violations"] == []


def test_documented_exclusion_is_skipped(tmp_path: Path) -> None:
    exp = _experiment(tmp_path, "k9005", spec=False)
    record = gate.audit_experiment(
        exp, knowledge_ids=set(), exclusions={"k9005": "archived legacy run"}
    )
    assert record["excluded"] is True
    assert record["violations"] == []


def test_directory_without_a_k_id_still_needs_a_spec_but_not_a_knowledge_entry(
    tmp_path: Path,
) -> None:
    """``paper2_taiwan_indiv_rolling_gamma`` has results but no K-id.

    knowledge.json is keyed by K-id, so "an entry mentioning paper2_..." is a demand
    the gate's own lookup could never satisfy — and an unsatisfiable gate gets
    bypassed rather than obeyed. The reproduce_spec half still applies: the run
    produced real output that must stay pinnable.
    """
    complete = _experiment(tmp_path, "paper2_rolling_gamma")
    record = gate.audit_experiment(complete, knowledge_ids=set(), exclusions={})
    assert record["k_id"] is None
    assert record["violations"] == []

    specless = _experiment(tmp_path, "paper2_other_analysis", spec=False)
    record = gate.audit_experiment(specless, knowledge_ids=set(), exclusions={})
    assert [v for v in record["violations"] if gate.SPEC_NAME in v]
    assert not [v for v in record["violations"] if "knowledge.json" in v]


def test_unreadable_knowledge_base_blocks_rather_than_waves_through(tmp_path: Path) -> None:
    """A gate that cannot read its evidence must not approve the merge."""
    exp = _experiment(tmp_path, "k9006")
    record = gate.audit_experiment(exp, knowledge_ids=None, exclusions={})
    assert record["violations"], "unreadable knowledge.json must block"


def test_cmd_check_exits_nonzero_and_prints_a_runnable_remedy(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """End-to-end: the CLI both callers invoke fails, and says how to fix it."""
    exp = _experiment(tmp_path, "k9007", spec=False)
    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(gate, "load_knowledge_ids", lambda root=None: set())
    monkeypatch.setattr(gate, "load_exclusions", lambda root=None: {})

    args = argparse.Namespace(path=[str(exp)], changed_since=None)
    assert gate.cmd_check(args) == 1
    err = capsys.readouterr().err
    assert "BLOCKED" in err
    assert "k9007" in err
    assert gate.EXCLUSIONS_REL.as_posix() in err, "the exemption path must be offered"


def test_cmd_check_passes_when_nothing_was_touched(monkeypatch, capsys) -> None:
    args = argparse.Namespace(path=[], changed_since=None)
    assert gate.cmd_check(args) == 0
    assert "PASS" in capsys.readouterr().out


@pytest.mark.parametrize("name,expected", [
    ("k1719", "k1719"),
    ("K1538_bond_fund_contagion", "k1538"),
    ("paper_notes", None),
])
def test_k_id_extraction(name: str, expected: str | None) -> None:
    assert gate.k_id(name) == expected
