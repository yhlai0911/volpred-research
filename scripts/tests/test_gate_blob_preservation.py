"""Changing a verdict gate must leave the pre-change bytes in the tree, mechanically.

K1708 (2026-07), Codex round 3: the pre-fix verdict gate was never committed, so
"prove the new gate does not turn an old NULL into a positive finding" could only
be answered against ``legacy_derive_verdict()`` — a RECONSTRUCTION of the old gate.
Proving a reconstruction correct using the reconstruction is circular, and review
refused it. Three rounds, no landing.

Two pieces are tested here:

* ``scripts/preserve_gate_blob.py`` — the moment of preservation. Its manifest is a
  claim; the tests insist the blob is re-hashed, because a gate that accepts the
  claim accepts a promise instead of an original.
* ``check_experiment_artifacts._entrypoint_drift_violation`` — the detection. It
  must block a drifted entrypoint with no preserved original, AND must stay silent
  on every pre-convention spec, or 1,256 historical experiments go red at once
  (2026-07-19 already showed what three red dispatch hours cost).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_experiment_artifacts as gate  # noqa: E402
from hooks import gate_edit_guard as edit_guard  # noqa: E402
import preserve_gate_blob as blobs  # noqa: E402

GATE_V1 = "def derive_verdict(p):\n    return 'NULL'\n"
GATE_V2 = "def derive_verdict(p):\n    return 'SUPPORTED'\n"


def _experiment(root: Path, name: str = "k9200", *, entry_source: str = GATE_V1) -> Path:
    exp = root / "experiments" / name
    exp.mkdir(parents=True)
    (exp / f"{name}.py").write_text(entry_source, encoding="utf-8")
    (exp / f"{name}_results.json").write_text(
        json.dumps({"verdict": "NULL"}), encoding="utf-8"
    )
    return exp


def _write_spec(exp: Path, *, sha: str | None) -> None:
    """Spec for the fixture. ``sha=None`` reproduces a pre-2026-07 hand-written spec."""
    entry: dict[str, object] = {"path": f"{exp.name}.py", "args": []}
    if sha is not None:
        entry["sha256"] = sha
    (exp / gate.SPEC_NAME).write_text(json.dumps({
        "schema_version": gate.SPEC_SCHEMA,
        "entrypoint": entry,
        "canonical_result": f"{exp.name}_results.json",
        "inputs": [],
        "timeout_seconds": 900,
        "network": "deny",
        "randomness": {"status": "not_applicable"},
        "comparison": {"rtol": 1e-9, "atol": 1e-12,
                       "ignore_pointers": [], "ignore_reasons": {}},
    }), encoding="utf-8")


def _sha_of(path: Path) -> str:
    return blobs.sha256_of(path)[0]


# --------------------------------------------------------------------------
# preserve_gate_blob
# --------------------------------------------------------------------------

def test_preserve_puts_the_real_bytes_in_the_tree(tmp_path: Path) -> None:
    exp = _experiment(tmp_path)
    entry = exp / "k9200.py"
    original_sha = _sha_of(entry)

    record = blobs.preserve(exp, entry, "verdict comparator switched")

    entry.write_text(GATE_V2, encoding="utf-8")  # the edit the blob protects against
    saved = blobs.blob_dir(exp) / record["blob"]
    assert saved.read_text(encoding="utf-8") == GATE_V1, (
        "the preserved copy tracked the later edit — it is not an original"
    )
    assert original_sha in blobs.preserved_shas(exp)


def test_a_manifest_entry_whose_blob_is_missing_does_not_count(tmp_path: Path) -> None:
    """The manifest is a claim; only the bytes are evidence."""
    exp = _experiment(tmp_path)
    record = blobs.preserve(exp, exp / "k9200.py", "reason")
    (blobs.blob_dir(exp) / record["blob"]).unlink()
    assert blobs.preserved_shas(exp) == set()


def test_a_tampered_blob_does_not_count(tmp_path: Path) -> None:
    exp = _experiment(tmp_path)
    record = blobs.preserve(exp, exp / "k9200.py", "reason")
    (blobs.blob_dir(exp) / record["blob"]).write_text("# edited\n", encoding="utf-8")
    assert blobs.preserved_shas(exp) == set()


def test_preserving_twice_keeps_one_entry_per_sha(tmp_path: Path) -> None:
    exp = _experiment(tmp_path)
    blobs.preserve(exp, exp / "k9200.py", "first")
    blobs.preserve(exp, exp / "k9200.py", "second")
    manifest = blobs.load_manifest(exp)
    assert len(manifest["entries"]) == 1
    assert manifest["entries"][0]["reason"] == "second"


def test_preserve_cli_refuses_an_unlabelled_blob(tmp_path: Path, capsys) -> None:
    """An unexplained original is a file nobody can interpret in six months."""
    exp = _experiment(tmp_path)
    import argparse
    args = argparse.Namespace(path=str(exp / "k9200.py"), reason="  ", exp_dir=str(exp))
    assert blobs.cmd_preserve(args) == 2
    assert "--reason is required" in capsys.readouterr().err


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------

def test_drifted_entrypoint_without_a_preserved_original_is_blocked(tmp_path: Path) -> None:
    exp = _experiment(tmp_path)
    _write_spec(exp, sha=_sha_of(exp / "k9200.py"))
    (exp / "k9200.py").write_text(GATE_V2, encoding="utf-8")  # gate changed, nothing saved

    violation, status = gate._entrypoint_drift_violation(exp)
    assert status == "drifted-unpreserved"
    assert violation is not None and "gate_history/" in violation


def test_drifted_entrypoint_with_the_original_preserved_passes(tmp_path: Path) -> None:
    exp = _experiment(tmp_path)
    entry = exp / "k9200.py"
    _write_spec(exp, sha=_sha_of(entry))

    blobs.preserve(exp, entry, "verdict comparator switched")  # BEFORE the edit
    entry.write_text(GATE_V2, encoding="utf-8")

    violation, status = gate._entrypoint_drift_violation(exp)
    assert violation is None
    assert status == "drifted-preserved"


def test_preserving_the_wrong_bytes_after_the_edit_does_not_satisfy_the_gate(
    tmp_path: Path,
) -> None:
    """The escape hatch the design has to close.

    Nothing stops an author running the tool late. What stops it *working* is that
    the preserved sha must equal the one the spec pins — i.e. the bytes that
    produced the archived results. Post-hoc preservation saves the new gate, which
    is not the sha under contention, so the gate still blocks.
    """
    exp = _experiment(tmp_path)
    entry = exp / "k9200.py"
    _write_spec(exp, sha=_sha_of(entry))

    entry.write_text(GATE_V2, encoding="utf-8")
    blobs.preserve(exp, entry, "preserved too late")

    violation, status = gate._entrypoint_drift_violation(exp)
    assert status == "drifted-unpreserved"
    assert violation is not None


def test_matching_entrypoint_is_clean(tmp_path: Path) -> None:
    exp = _experiment(tmp_path)
    _write_spec(exp, sha=_sha_of(exp / "k9200.py"))
    assert gate._entrypoint_drift_violation(exp) == (None, "clean")


def test_legacy_spec_without_a_runtime_sha_is_never_gated(tmp_path: Path) -> None:
    """The forward ratchet. 1,256 pre-convention experiments must stay untouched."""
    exp = _experiment(tmp_path)
    _write_spec(exp, sha=None)
    (exp / "k9200.py").write_text(GATE_V2, encoding="utf-8")  # drifted, and legacy

    violation, status = gate._entrypoint_drift_violation(exp)
    assert violation is None
    assert status == "skipped-no-sha"


def test_audit_experiment_reports_drift_as_a_violation(tmp_path: Path) -> None:
    """End to end through the real audit entry point, not just the helper."""
    exp = _experiment(tmp_path)
    _write_spec(exp, sha=_sha_of(exp / "k9200.py"))
    (exp / "k9200.py").write_text(GATE_V2, encoding="utf-8")

    record = gate.audit_experiment(exp, knowledge_ids={"k9200"}, exclusions={})
    assert record["entrypoint_drift"] == "drifted-unpreserved"
    assert any("gate_history/" in v for v in record["violations"])
    assert any("preserve_gate_blob.py" in line for line in gate._remedy(record))


def test_a_documented_exclusion_still_short_circuits_the_new_rule(tmp_path: Path) -> None:
    """New rules must respect the existing legacy-backlog escape valve."""
    exp = _experiment(tmp_path)
    _write_spec(exp, sha=_sha_of(exp / "k9200.py"))
    (exp / "k9200.py").write_text(GATE_V2, encoding="utf-8")

    record = gate.audit_experiment(
        exp, knowledge_ids={"k9200"}, exclusions={"k9200": "archived legacy work"}
    )
    assert record["excluded"] is True
    assert record["violations"] == []


def test_drift_is_not_evaluated_when_the_spec_itself_is_broken(tmp_path: Path) -> None:
    """A spec that does not parse has no claim to contradict; report that, not drift."""
    exp = _experiment(tmp_path)
    (exp / gate.SPEC_NAME).write_text("{ not json", encoding="utf-8")
    record = gate.audit_experiment(exp, knowledge_ids={"k9200"}, exclusions={})
    assert record["entrypoint_drift"] is None
    assert any(gate.SPEC_NAME in v for v in record["violations"])


def test_fallback_sha_reader_agrees_with_the_importable_one(tmp_path: Path) -> None:
    """merge_worktree.sh runs bare python3; the inlined copy must not be weaker."""
    exp = _experiment(tmp_path)
    record = blobs.preserve(exp, exp / "k9200.py", "reason")
    assert gate._preserved_shas_fallback(exp) == blobs.preserved_shas(exp)

    (blobs.blob_dir(exp) / record["blob"]).write_text("# edited\n", encoding="utf-8")
    assert gate._preserved_shas_fallback(exp) == set()


# --------------------------------------------------------------------------
# edit-time interception and project wiring
# --------------------------------------------------------------------------

def test_edit_guard_blocks_the_only_uncommitted_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The last copy must be stopped before Edit/Write can overwrite it."""
    exp = _experiment(tmp_path)
    entry = exp / "k9200.py"
    _write_spec(exp, sha=_sha_of(entry))
    monkeypatch.setattr(edit_guard, "_bytes_are_in_git", lambda _path: False)

    verdict = edit_guard.evaluate(entry)
    assert verdict is not None
    assert verdict[0] == _sha_of(entry)


def test_edit_guard_allows_after_preimage_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exp = _experiment(tmp_path)
    entry = exp / "k9200.py"
    _write_spec(exp, sha=_sha_of(entry))
    monkeypatch.setattr(edit_guard, "_bytes_are_in_git", lambda _path: False)
    blobs.preserve(exp, entry, "before comparator change")

    assert edit_guard.evaluate(entry) is None


def test_edit_guard_leaves_git_recoverable_preimage_to_downstream_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exp = _experiment(tmp_path)
    entry = exp / "k9200.py"
    _write_spec(exp, sha=_sha_of(entry))
    monkeypatch.setattr(edit_guard, "_bytes_are_in_git", lambda _path: True)

    assert edit_guard.evaluate(entry) is None


def test_project_settings_register_the_gate_edit_guard() -> None:
    settings_path = Path(__file__).resolve().parents[2] / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    registrations = [
        hook
        for group in settings["hooks"]["PreToolUse"]
        if group.get("matcher") == "Edit|Write|MultiEdit|NotebookEdit"
        for hook in group.get("hooks", [])
    ]
    assert any(
        "scripts/hooks/gate_edit_guard.py" in h.get("command", "")
        for h in registrations
    ), "the edit guard exists but is not wired into PreToolUse"
