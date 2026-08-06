"""docs/governance/2026-08-05_tex_carveout_proposal.md §4: apply_paper_edits.py must
prove a batch of FIND/REPLACE edits is mechanical (unchanged target, unique anchors,
equal line counts, confined diff) without widening who is allowed to write .tex prose.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    script_path = PROJECT_ROOT / "scripts" / "apply_paper_edits.py"
    spec = importlib.util.spec_from_file_location("apply_paper_edits_test", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_target(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _write_instructions(
    root: Path,
    *,
    target_rel: str,
    target_bytes: bytes,
    round_evidence_rel: str,
    edits: list[tuple[str, str, str]],
    instructions_rel: str = "storage/org/departments/publications/work/demo_edit_instructions.md",
) -> Path:
    """edits: list of (label, find, replace)."""
    sha = _sha256(target_bytes)
    lines = [
        f"**Target file**: `{target_rel}`\n\n",
        "| 項目 | 期望值 |\n|---|---|\n",
        f"| sha256 | `{sha}` |\n",
        f"| bytes | `{len(target_bytes)}` |\n\n",
        f"**Round evidence**: `{round_evidence_rel}`\n\n",
    ]
    for i, (label, find, replace) in enumerate(edits, start=1):
        lines.append(f"## Edit {i} — `x:{i}` — {label}\n\n")
        lines.append(f"**Original**\n\n```latex\n{find}\n```\n\n")
        lines.append(f"**Replacement**\n\n```latex\n{replace}\n```\n\n")
    path = root / instructions_rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")
    return path


def test_c1_stale_hash_blocks_before_any_parsing_of_edits(mod, tmp_path):
    original = "alpha beta\ngamma\n"
    target = _write_target(tmp_path, "paper/demo/main.tex", original)
    instructions = _write_instructions(
        tmp_path,
        target_rel="paper/demo/main.tex",
        target_bytes=b"not the real bytes",
        round_evidence_rel="../review_rounds/demo/v1",
        edits=[("L1", "alpha beta", "ALPHA BETA")],
    )
    parsed = mod.parse_instructions(instructions)
    problem = mod.check_c1_staleness(parsed, root=tmp_path)
    assert problem is not None
    assert "stale" in problem
    assert target.read_text(encoding="utf-8") == original


def test_c2_non_unique_find_is_rejected(mod, tmp_path):
    original = "dup line\ndup line\n"
    _write_target(tmp_path, "paper/demo/main.tex", original)
    instructions = _write_instructions(
        tmp_path,
        target_rel="paper/demo/main.tex",
        target_bytes=original.encode("utf-8"),
        round_evidence_rel="../review_rounds/demo/v1",
        edits=[("dup", "dup line", "DUP LINE")],
    )
    parsed = mod.parse_instructions(instructions)
    assert mod.check_c1_staleness(parsed, root=tmp_path) is None
    problems = mod.check_c2_c3(parsed, original)
    assert any("matches 2 times" in p for p in problems)


def test_c3_unequal_line_count_is_rejected(mod, tmp_path):
    original = "one line here\n"
    _write_target(tmp_path, "paper/demo/main.tex", original)
    instructions = _write_instructions(
        tmp_path,
        target_rel="paper/demo/main.tex",
        target_bytes=original.encode("utf-8"),
        round_evidence_rel="../review_rounds/demo/v1",
        edits=[("grow", "one line here", "one line\nhere now, two lines")],
    )
    parsed = mod.parse_instructions(instructions)
    problems = mod.check_c2_c3(parsed, original)
    assert any("equal-line-count" in p for p in problems)


def test_missing_edit_section_raises_instructions_error(mod, tmp_path):
    path = tmp_path / "bad.md"
    path.write_text(
        "**Target file**: `paper/demo/main.tex`\n\n"
        "| 項目 | 期望值 |\n|---|---|\n"
        "| sha256 | `" + "a" * 64 + "` |\n| bytes | `10` |\n\n"
        "**Round evidence**: `../review_rounds/demo/v1`\n",
        encoding="utf-8",
    )
    with pytest.raises(mod.InstructionsError, match="no `## Edit N"):
        mod.parse_instructions(path)


def test_dry_run_default_writes_nothing(mod, tmp_path, capsys):
    original = "The quick fox\njumps.\n"
    target = _write_target(tmp_path, "paper/demo/main.tex", original)
    instructions = _write_instructions(
        tmp_path,
        target_rel="paper/demo/main.tex",
        target_bytes=original.encode("utf-8"),
        round_evidence_rel="../review_rounds/demo/v1",
        edits=[("fix", "quick fox", "slow fox")],
    )
    (tmp_path / "review_rounds" / "demo" / "v1").mkdir(parents=True)

    rc = mod.main([str(instructions), "--root", str(tmp_path)])

    assert rc == 0
    assert target.read_text(encoding="utf-8") == original, "dry-run must not write"
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "-The quick fox" in out
    assert "+The slow fox" in out


def test_apply_writes_atomically_and_report_lands_in_round_evidence(mod, tmp_path, monkeypatch):
    original = "The quick fox\njumps over.\n"
    target = _write_target(tmp_path, "paper/demo/main.tex", original)
    evidence_dir = tmp_path / "storage/org/departments/publications/review_rounds/demo/v1"
    evidence_dir.mkdir(parents=True)
    instructions = _write_instructions(
        tmp_path,
        target_rel="paper/demo/main.tex",
        target_bytes=original.encode("utf-8"),
        round_evidence_rel="../review_rounds/demo/v1",
        edits=[("fix", "quick fox", "slow fox")],
    )

    calls = []

    def fake_run(cmd, cwd=None, capture_output=None, text=None):
        calls.append(cmd)
        class R:
            returncode = 0
            stderr = ""
        return R()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    rc = mod.main([str(instructions), "--apply", "--root", str(tmp_path)])

    assert rc == 0
    assert target.read_text(encoding="utf-8") == "The slow fox\njumps over.\n"
    reports = list(evidence_dir.glob("apply_report_*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["target_file"] == "paper/demo/main.tex"
    assert report["changed_line_numbers_post_apply"] == [1]
    assert len(calls) == 1, "exactly one dept_send delivery, not zero and not a retry storm"
    assert "publications" in calls[0], "deciding department derived from the instructions path"


def test_apply_refuses_to_write_when_no_reply_flag_still_verifies_c4(mod, tmp_path):
    """--no-reply must still perform the write and the C4 confinement check -- it only
    skips delivery, it is not a shortcut around verification."""
    original = "keep\nreplace me\nkeep\n"
    target = _write_target(tmp_path, "paper/demo/main.tex", original)
    evidence_dir = tmp_path / "storage/org/departments/publications/review_rounds/demo/v1"
    evidence_dir.mkdir(parents=True)
    instructions = _write_instructions(
        tmp_path,
        target_rel="paper/demo/main.tex",
        target_bytes=original.encode("utf-8"),
        round_evidence_rel="../review_rounds/demo/v1",
        edits=[("mid", "replace me", "replaced now")],
    )

    rc = mod.main([str(instructions), "--apply", "--no-reply", "--root", str(tmp_path)])

    assert rc == 0
    assert target.read_text(encoding="utf-8") == "keep\nreplaced now\nkeep\n"
    reports = list(evidence_dir.glob("apply_report_*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["changed_line_numbers_post_apply"] == [2]


def test_multi_edit_batch_applies_in_order_against_the_real_fixture_shape(mod, tmp_path):
    """Mirrors the six-edit prg-v8 batch shape: independent, non-overlapping,
    equal-line-count edits applied against one target file in one pass."""
    original = "first sentence.\nsecond sentence.\nthird sentence.\n"
    target = _write_target(tmp_path, "paper/demo/main.tex", original)
    evidence_dir = tmp_path / "storage/org/departments/publications/review_rounds/demo/v1"
    evidence_dir.mkdir(parents=True)
    instructions = _write_instructions(
        tmp_path,
        target_rel="paper/demo/main.tex",
        target_bytes=original.encode("utf-8"),
        round_evidence_rel="../review_rounds/demo/v1",
        edits=[
            ("e1", "first sentence.", "FIRST SENTENCE."),
            ("e2", "third sentence.", "THIRD SENTENCE."),
        ],
    )

    rc = mod.main([str(instructions), "--apply", "--no-reply", "--root", str(tmp_path)])

    assert rc == 0
    assert target.read_text(encoding="utf-8") == (
        "FIRST SENTENCE.\nsecond sentence.\nTHIRD SENTENCE.\n"
    )


def test_real_prg_v8_fixture_parses_and_dry_runs_clean(mod):
    """Acceptance fixture named in the task: the real publications hand-off file must
    parse end-to-end and pass C1/C2/C3 against the live repo state, dry-run only."""
    instructions = (
        PROJECT_ROOT
        / "storage/org/departments/publications/work/prg_v8_edit_instructions.md"
    )
    if not instructions.is_file():
        pytest.skip("reference fixture not present in this checkout")

    parsed = mod.parse_instructions(instructions)
    assert parsed["target_rel"] == "paper/prg-periodic-garch/main.tex"
    assert len(parsed["edits"]) == 6

    rc = mod.main([str(instructions)])  # no --apply: must not touch the real paper
    assert rc == 0
