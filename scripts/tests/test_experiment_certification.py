#!/usr/bin/env python
"""Merge-time gate: an experiment enters main only with a PASS verdict bound to its bytes.

The incident this ratchet freezes (2026-07-14, docs/error_log.md)
----------------------------------------------------------------
K1709 was reviewed by Codex and FAILed on two CRITICALs.  It was merged into
main anyway -- nothing on the merge path ever read the verdict -- and the
nested-DM ratchet then reddened every push for three consecutive dispatch
hours until the experiment was withdrawn by hand.

The naive fix ("FAIL blocks merge") is not enough, and the reason is the
second half of the same day: the agent *fixed* both CRITICALs afterwards.  The
recorded verdict still said FAIL, but it said FAIL about ``k1709.py``
@e42b0885 -- a file that no longer existed.  Codex's own review even pinned the
hash it judged and warned the file had changed underneath it.  So the repo held
a verdict that certified nothing, and both readings of it were wrong:

  - honour the stale FAIL  -> block a snapshot that was already repaired, and
    teach agents that the way through is to delete the review file;
  - ignore the stale FAIL  -> exactly K1709's original sin, merging uncertified
    work because someone asserted "I fixed it".

A verdict is only worth its snapshot.  So certification pins sha256 over the
whole claim surface -- code, README, results, rendered figures -- and drift is a block:
"reviewed one thing, shipped another" is not a certification.  That also makes
it safe for the agent to invoke the reviewer itself: edit after the PASS and
the hashes stop matching.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "scripts" / "experiment_gates.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import experiment_gates as gates  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _experiment(tmp_path: Path, kid: str = "k1709") -> Path:
    """A minimal but complete experiment: code, write-up, numbers, figure."""
    exp = tmp_path / "experiments" / kid
    exp.mkdir(parents=True)
    (exp / f"{kid}.py").write_text("print('flow -> rv')\n", encoding="utf-8")
    (exp / "README.md").write_text("# K1709\n\n**Verdict: INCONCLUSIVE**\n", encoding="utf-8")
    (exp / f"{kid}_results.json").write_text(
        json.dumps({"verdict": "INCONCLUSIVE_NO_EXACT_NULL_CLAIM"}), encoding="utf-8"
    )
    (exp / "fig1_result.png").write_bytes(b"reader-facing result figure")
    return exp


def _certify(exp: Path, verdict: str = "PASS", *, files: list[Path] | None = None) -> Path:
    surface = files if files is not None else gates.claim_surface(exp)
    cert = exp / gates.CERT_FILENAME
    cert.write_text(
        json.dumps(
            {
                "kid": exp.name,
                "verdict": verdict,
                "reviewer": "codex/gpt-5.6-sol",
                "reviewed_at": "2026-07-14T13:42:00+08:00",
                "review_artifact": "codex_review_rev1_20260714.txt",
                "reviewed_sha256": {str(p.relative_to(exp)): _sha(p) for p in surface},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return cert


def _verdicts(exp: Path) -> list[str]:
    return [v.verdict for v in gates.certification_violations(exp)]


# --- the three ways in, all of them closed -----------------------------------


def test_pass_verdict_bound_to_current_bytes_is_the_only_way_through(tmp_path: Path) -> None:
    exp = _experiment(tmp_path)
    _certify(exp, "PASS")
    assert gates.certification_violations(exp) == []


def test_fail_verdict_blocks_merge(tmp_path: Path) -> None:
    """K1709's original sin: Codex said FAIL, it was merged, CI went red 4x."""
    exp = _experiment(tmp_path)
    _certify(exp, "FAIL")
    assert any("not PASS" in v for v in _verdicts(exp))


def test_uncertified_experiment_blocks_merge(tmp_path: Path) -> None:
    exp = _experiment(tmp_path)
    assert any("no review_verdict.json" in v for v in _verdicts(exp))


@pytest.mark.parametrize(
    "target", ["k1709.py", "README.md", "k1709_results.json", "fig1_result.png"]
)
def test_pass_verdict_goes_stale_when_the_reviewed_bytes_change(
    tmp_path: Path, target: str
) -> None:
    """The dangling-verdict case. Fix the code after the review and you are
    uncertified again -- for the code, and equally for the write-up and the
    numbers, because an overclaim reaches a human through the README."""
    exp = _experiment(tmp_path)
    _certify(exp, "PASS")
    assert gates.certification_violations(exp) == []

    (exp / target).write_bytes(b"repaired after the reviewer looked\n")

    stale = _verdicts(exp)
    assert any("changed after review" in v for v in stale), stale


# --- the ways around it, also closed -----------------------------------------


def test_new_claim_bearing_file_slipped_in_after_review_blocks(tmp_path: Path) -> None:
    """Ship a second script the reviewer never saw and the surface no longer matches."""
    exp = _experiment(tmp_path)
    _certify(exp, "PASS")
    (exp / "k1709_extra_analysis.py").write_text("print('unreviewed claim')\n", encoding="utf-8")
    assert any("never reviewed" in v for v in _verdicts(exp))


def test_new_reader_facing_figure_slipped_in_after_review_blocks(tmp_path: Path) -> None:
    exp = _experiment(tmp_path)
    _certify(exp, "PASS")
    (exp / "fig2_unreviewed_claim.svg").write_text(
        "<svg><text>unreviewed claim</text></svg>", encoding="utf-8"
    )
    assert any("never reviewed" in v for v in _verdicts(exp))


def test_pass_verdict_pinning_nothing_certifies_nothing(tmp_path: Path) -> None:
    exp = _experiment(tmp_path)
    _certify(exp, "PASS", files=[])
    assert any("certifies nothing" in v for v in _verdicts(exp))


def test_malformed_verdict_fails_closed(tmp_path: Path) -> None:
    exp = _experiment(tmp_path)
    (exp / gates.CERT_FILENAME).write_text("{not json", encoding="utf-8")
    assert any("malformed" in v for v in _verdicts(exp))


def test_pycache_is_not_part_of_the_claim_surface(tmp_path: Path) -> None:
    """Byte-code churn must not invalidate a real verdict."""
    exp = _experiment(tmp_path)
    _certify(exp, "PASS")
    cache = exp / "__pycache__"
    cache.mkdir()
    (cache / "k1709.cpython-313.pyc").write_bytes(b"\x00garbage")
    assert gates.certification_violations(exp) == []


# --- the schema the reviewer writes against ----------------------------------
#
# Second half of the same K1709 day: Codex reviewed the frozen c97d690c for half
# an hour and wrote `final_verdict` / `claim_surface_sha256` (two files pinned)
# because the brief described the schema by hand and the description had drifted
# from the gate.  That verdict was FAIL, so nothing unsafe merged -- but a PASS
# in that shape would have certified nothing and burnt the round.  The fix is
# not a second reader for the old key names: it is that the gate emits the
# skeleton, so there is nothing left to transcribe.


def test_the_generated_template_is_the_verdict_the_gate_accepts(tmp_path: Path) -> None:
    """Fill in the template, say PASS, and you are through. This is the ratchet:

    if anyone changes the schema on one side only, this test fails.
    """
    exp = _experiment(tmp_path)
    template = gates.verdict_template(exp)
    template["verdict"] = "PASS"
    template["blocking_defects"] = []
    (exp / gates.CERT_FILENAME).write_text(json.dumps(template, indent=2), encoding="utf-8")

    assert gates.certification_violations(exp) == []


def test_the_template_pins_the_whole_claim_surface(tmp_path: Path) -> None:
    exp = _experiment(tmp_path)
    pinned = gates.verdict_template(exp)["reviewed_sha256"]

    assert set(pinned) == {
        "k1709.py",
        "README.md",
        "k1709_results.json",
        "fig1_result.png",
    }
    assert pinned["k1709.py"] == _sha(exp / "k1709.py")


def test_a_verdict_in_the_old_hand_written_shape_names_its_own_drift(tmp_path: Path) -> None:
    """Blocked either way -- but say WHY, or the next reviewer re-derives it from scratch."""
    exp = _experiment(tmp_path)
    (exp / gates.CERT_FILENAME).write_text(
        json.dumps({
            "final_verdict": "PASS",
            "claim_surface_sha256": {"k1709.py": _sha(exp / "k1709.py")},
        }, indent=2),
        encoding="utf-8",
    )

    verdicts = _verdicts(exp)
    assert any("final_verdict" in v and "schema drift" in v for v in verdicts)


def test_verdict_template_cli_writes_a_gate_shaped_file(tmp_path: Path) -> None:
    exp = _experiment(tmp_path)
    out = tmp_path / "verdict.json"

    proc = subprocess.run(
        [sys.executable, str(GATE), "verdict-template", "--path", str(exp), "--out", str(out)],
        capture_output=True, text=True,
    )

    assert proc.returncode == 0, proc.stderr
    written = json.loads(out.read_text(encoding="utf-8"))
    assert set(written["reviewed_sha256"]) == {
        "k1709.py",
        "README.md",
        "k1709_results.json",
        "fig1_result.png",
    }
    assert written["verdict"].startswith("FILL")


# --- the CLI the merge path actually calls -----------------------------------


def test_cli_exit_codes(tmp_path: Path) -> None:
    exp = _experiment(tmp_path)

    blocked = subprocess.run(
        [sys.executable, str(GATE), "certify", "--path", str(exp)],
        capture_output=True, text=True,
    )
    assert blocked.returncode == 1
    assert "BLOCKED" in blocked.stderr

    _certify(exp, "PASS")
    ok = subprocess.run(
        [sys.executable, str(GATE), "certify", "--path", str(exp)],
        capture_output=True, text=True,
    )
    assert ok.returncode == 0, ok.stderr
    assert "PASS" in ok.stdout


def test_certify_cli_is_stdlib_only(tmp_path: Path) -> None:
    """The merge hook uses bare python3, outside the project's uv environment.

    ``-I -S`` removes cwd, PYTHONPATH, user site and site-packages.  A PASS here
    proves the certify subcommand does not eagerly import the audit stack (some
    auditors import ``volpred``); only the separate ``run`` subcommand may do so.
    """
    exp = _experiment(tmp_path)
    _certify(exp, "PASS")

    isolated = subprocess.run(
        [sys.executable, "-I", "-S", str(GATE), "certify", "--path", str(exp)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert isolated.returncode == 0, isolated.stderr
    assert "PASS" in isolated.stdout
