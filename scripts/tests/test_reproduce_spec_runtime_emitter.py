"""The spec must be a side effect of RUNNING, not something written afterwards.

K1708 (2026-07) failed Codex primary-path review three rounds. One root cause was
purely procedural: ``reproduce_spec.json`` was hand-written after the run, and by
then the script had moved. ``K1708_results.json`` pins ``code_trace`` sha
``43bffdd...`` at 91,752 bytes; ``experiments/k1708/K1708.py`` is 126,998 bytes.
The spec describes a program that did not produce the results it claims to pin.

``volpred.research.reproduce_spec.finalize_experiment`` removes the gap by writing
both artifacts from ONE ``trace_file()`` call. The property under test is not "the
helper works" but "the two artifacts cannot disagree" — so the central test mutates
the script between the two writes and asserts they still agree, which is exactly
what a post-hoc writer would get wrong.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reproduce_check as rc

from volpred.research import reproduce_spec as rs


def _experiment(tmp_path: Path, name: str = "k9100") -> tuple[Path, Path]:
    """A minimal experiment dir laid out like the real ones (repo/experiments/<kid>)."""
    exp = tmp_path / "experiments" / name
    exp.mkdir(parents=True)
    entry = exp / f"{name}.py"
    entry.write_text("print('science')\n", encoding="utf-8")
    return exp, entry


def test_trace_file_reports_sha_and_size_of_the_bytes_it_hashed(tmp_path: Path) -> None:
    target = tmp_path / "run.py"
    target.write_bytes(b"abcdef")
    trace = rs.trace_file(target, root=tmp_path)
    assert trace["size_bytes"] == 6
    assert trace["sha256"] == (
        "bef57ec7f53a6d40beb640a780a639c83bc29ac8a9816f1fc6c5c6dcd93c4721"
    )
    assert trace["path"] == "run.py"


def test_finalize_writes_results_and_spec_that_pin_identical_bytes(tmp_path: Path) -> None:
    exp, entry = _experiment(tmp_path)
    results_path, spec = rs.finalize_experiment(
        results={"qlike": 0.42, "verdict": "NULL"},
        entrypoint=entry,
        canonical_result="k9100_results.json",
        exp_dir=exp,
        seeds=[("numpy", 9100)],
        runtime_seconds=12.5,
    )
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    assert payload["code_trace"]["sha256"] == spec["entrypoint"]["sha256"]
    assert payload["code_trace"]["size_bytes"] == spec["entrypoint"]["size_bytes"]
    assert spec["entrypoint"]["size_bytes"] == len(entry.read_bytes())
    assert payload["qlike"] == 0.42


def test_finalize_pins_the_complete_canonical_result_bytes(tmp_path: Path) -> None:
    """A results-only number edit must break an independent runtime commitment."""
    exp, entry = _experiment(tmp_path)
    results_path, spec = rs.finalize_experiment(
        results={
            "cw": {"t_stat": 1.968775},
            "qlike": 0.42,
            "verdict": {"label": "NULL"},
        },
        entrypoint=entry,
        canonical_result="k9100_results.json",
        exp_dir=exp,
    )

    result_bytes = results_path.read_bytes()
    assert spec["canonical_result_identity"] == {
        "path": "k9100_results.json",
        "sha256": hashlib.sha256(result_bytes).hexdigest(),
        "size_bytes": len(result_bytes),
    }


def test_finalize_binds_declared_outputs_and_writes_completion_receipt(
    tmp_path: Path,
) -> None:
    """A generation is complete only when every declared output is hash-bound."""
    exp, entry = _experiment(tmp_path)
    figure = exp / "figures" / "chart.png"
    figure.parent.mkdir()
    figure.write_bytes(b"chart-v1")

    results_path, spec = rs.finalize_experiment(
        results={"verdict": "NULL"},
        entrypoint=entry,
        canonical_result="k9100_results.json",
        exp_dir=exp,
        outputs=["figures/chart.png"],
    )

    identities = spec["artifact_generation"]["output_identities"]
    assert identities == [
        {
            "path": "figures/chart.png",
            "sha256": hashlib.sha256(b"chart-v1").hexdigest(),
            "size_bytes": len(b"chart-v1"),
        }
    ]
    commit = json.loads((exp / rs.COMMIT_NAME).read_text(encoding="utf-8"))
    assert commit["generation_id"] == spec["artifact_generation"]["generation_id"]
    assert commit["canonical_result_identity"] == spec["canonical_result_identity"]
    assert commit["spec_identity"]["sha256"] == hashlib.sha256(
        (exp / rs.SPEC_NAME).read_bytes()
    ).hexdigest()
    assert hashlib.sha256(results_path.read_bytes()).hexdigest() == commit[
        "canonical_result_identity"
    ]["sha256"]


def test_writer_pins_an_existing_canonical_result(tmp_path: Path) -> None:
    """The lower-level public writer must enforce the same result identity."""
    exp, entry = _experiment(tmp_path)
    results_path = exp / "k9100_results.json"
    result_bytes = b'{"cw":{"t_stat":1.968775},"verdict":"NULL"}\n'
    results_path.write_bytes(result_bytes)

    spec = rs.write_reproduce_spec(
        exp_dir=exp,
        entrypoint=entry,
        canonical_result=results_path.name,
    )

    assert spec["canonical_result_identity"] == {
        "path": results_path.name,
        "sha256": hashlib.sha256(result_bytes).hexdigest(),
        "size_bytes": len(result_bytes),
    }


def test_result_identity_rejects_a_non_hex_digest(tmp_path: Path) -> None:
    exp, entry = _experiment(tmp_path)
    with pytest.raises(ValueError, match="canonical_result_trace"):
        rs.build_reproduce_spec(
            exp_dir=exp,
            entrypoint=entry,
            canonical_result="k9100_results.json",
            canonical_result_trace={
                "path": "k9100_results.json",
                "sha256": "z" * 64,
                "size_bytes": 42,
            },
        )


def test_the_k1708_divergence_cannot_be_reproduced_through_this_helper(
    tmp_path: Path,
) -> None:
    """Edit the script, re-finalize: BOTH artifacts move together, or neither does.

    The K1708 shape is results pinning sha A while the file on disk is sha B. Here
    the first run pins A; after the edit the second run pins B in results AND spec.
    At no point does one artifact describe bytes the other does not.
    """
    exp, entry = _experiment(tmp_path)
    first_results, first_spec = rs.finalize_experiment(
        results={"stage": 1},
        entrypoint=entry,
        canonical_result="k9100_results.json",
        exp_dir=exp,
    )
    sha_a = json.loads(first_results.read_text(encoding="utf-8"))["code_trace"]["sha256"]
    assert first_spec["entrypoint"]["sha256"] == sha_a

    entry.write_text("print('science')\n# gate comparator changed\n", encoding="utf-8")
    second_results, second_spec = rs.finalize_experiment(
        results={"stage": 2},
        entrypoint=entry,
        canonical_result="k9100_results.json",
        exp_dir=exp,
    )
    sha_b = json.loads(second_results.read_text(encoding="utf-8"))["code_trace"]["sha256"]
    assert sha_b != sha_a
    assert second_spec["entrypoint"]["sha256"] == sha_b


def test_emitted_spec_validates_against_the_real_schema_validator(tmp_path: Path) -> None:
    """A spec this helper writes must load in reproduce_check, or it is decoration.

    reproduce_check resolves inputs against ``exp_dir.parents[1]``, so the fixture
    mirrors the repo's ``<root>/experiments/<kid>/`` layout rather than a flat dir.
    """
    exp, entry = _experiment(tmp_path)
    data = exp / "data"
    data.mkdir()
    (data / "in.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    rs.finalize_experiment(
        results={"qlike": 1.0},
        entrypoint=entry,
        canonical_result="k9100_results.json",
        exp_dir=exp,
        inputs=[data / "in.csv"],
        seeds=[("numpy", 42)],
        runtime_seconds=3.0,
    )
    spec, err = rc.load_spec(exp)
    assert err is None, f"emitter produced a spec the validator rejects: {err}"
    assert spec is not None
    assert spec["entrypoint"]["path"] == "k9100.py"


def test_timeout_is_bounded_by_the_validator_ceiling_not_by_raw_runtime() -> None:
    """A declared timeout must clear the observed runtime and stay inside the schema."""
    assert rs.MAX_TIMEOUT_SECONDS == rc.MAX_TIMEOUT_SECONDS, (
        "the duplicated ceiling drifted from reproduce_check — the emitter can now "
        "write timeouts the validator rejects"
    )
    assert rs._timeout_seconds(10.0) > 10
    assert rs._timeout_seconds(1e9) == rs.MAX_TIMEOUT_SECONDS
    assert rs._timeout_seconds(None) >= 1


def test_randomness_status_is_declared_only_when_seeds_actually_are() -> None:
    """'not_applicable' is a scientific claim; the helper may not guess it."""
    assert rs._randomness_block(None)["status"] == "not_applicable"
    declared = rs._randomness_block([("numpy", 7)])
    assert declared["status"] == "declared"
    assert declared["seeds"] == [{"library": "numpy", "value": 7}]


def test_entrypoint_outside_the_experiment_dir_is_refused(tmp_path: Path) -> None:
    """The v1 schema needs an experiment-relative entrypoint; emit loudly or not at all."""
    exp, _ = _experiment(tmp_path)
    stray = tmp_path / "elsewhere.py"
    stray.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not inside experiment dir"):
        rs.build_reproduce_spec(
            exp_dir=exp, entrypoint=stray, canonical_result="k9100_results.json"
        )


def test_comparison_override_must_keep_pointers_and_reasons_in_step(tmp_path: Path) -> None:
    """load_spec demands set equality; catching it here beats an unloadable artifact."""
    exp, entry = _experiment(tmp_path)
    with pytest.raises(ValueError, match="ignore_reasons"):
        rs.build_reproduce_spec(
            exp_dir=exp,
            entrypoint=entry,
            canonical_result="k9100_results.json",
            comparison={"ignore_pointers": ["/x"]},
        )
