#!/usr/bin/env python
"""Single entry point for the repo's experiment-integrity gates.

    uv run python scripts/experiment_gates.py run --path experiments/k1709

Why this file exists
--------------------
The repo already owns detectors for the ways an experiment can be quietly
wrong (nested-model DM misuse, missing HAC in DM, Cholesky-FEVD ordering
artifacts, MDD scale artifacts).  Each one has a ratchet under
``scripts/tests/`` that freezes legacy debt and fails on anything new.  Those
ratchets were correct and they still never fired for the work that mattered:
a dispatched agent runs in a git worktree, runs *its own* ``test_kXXXX.py``,
and never runs ``scripts/tests/``.  The branch is not merged, so CI never sees
it either.  K1701 was caught by hand; K1709 reproduced the identical mistake
30 hours later and the ratchet that would have caught it verbatim sat unrun.
An entire xhigh experiment was wasted (docs/error_log.md 2026-07-14).

So the gap was never detection.  It was that the gate lived somewhere the
agent could not reach.  This module is that reach: one command, callable from
an agent brief, from the compute-queue runner, from CI, from pre-push.

Single-owner contract (anti-stacking)
-------------------------------------
This is NOT a second detector.  Every scan function, every verdict set and
every baseline below is *imported from the auditor module that owns it*.  If a
detector changes, this file changes with it for free.  What this file adds is
only: scope the scan to one path, ask "is this site already frozen as legacy
debt", and turn the answer into an exit code.

Scoping rule
------------
A site fails the gate unless it is already in that auditor's frozen baseline.
A new experiment's path can never appear in a baseline, so for the case this
gate exists to serve -- fresh agent work -- the rule reduces to "any violation
fails".  For already-frozen legacy paths the repo-wide ratchets under
``scripts/tests/`` remain the enforcement owner; this gate stays lenient there
on purpose, so it can never block an agent for debt it did not create.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

BASELINE_DIR = REPO_ROOT / "storage" / "ops"


@dataclass(frozen=True)
class Violation:
    gate: str
    site: str
    verdict: str
    remedy: str


def _baseline_sites(name: str) -> set[str]:
    """Every site string frozen anywhere in an auditor's baseline.

    The four baselines have four different shapes (``sites``, ``active.exposed``,
    ``blindspot_sites``, ``reviewed_nonnested``...).  Rather than restate each
    schema here -- a fifth place to drift -- walk the JSON and collect every
    string that names a Python site.  Over-collecting is safe in the one
    direction that matters: it can only make the gate *more* lenient toward
    paths that are already recorded, and a brand-new experiment's path appears
    in no baseline at all.
    """
    path = BASELINE_DIR / name
    if not path.exists():
        print(f"[gate] WARNING: baseline missing, treating as empty: {path}", file=sys.stderr)
        return set()

    sites: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, str):
            head = node.split("::", 1)[0]
            if head.endswith(".py"):
                sites.add(node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads(path.read_text(encoding="utf-8")))
    return sites


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


# --- gate adapters -----------------------------------------------------------
# Each adapter yields (site_key, verdict) for the violating sites in one file.
# Detection and verdict semantics come from the auditor module; nothing is
# re-implemented here.


def _scan_nested_dm(path: Path) -> Iterable[tuple[str, str]]:
    # Keep auditor imports on the ``run`` path.  ``certify`` is called by
    # merge_worktree.sh with bare python3 and must remain stdlib-only even when
    # the volpred package has not been installed in that interpreter.
    import audit_nested_dm_misuse as nested_dm

    finding = nested_dm.scan_file(path, REPO_ROOT)
    if finding is not None and finding.test_role not in nested_dm.SAFE_ROLES:
        yield finding.file, finding.test_role


def _scan_dm_hac(path: Path) -> Iterable[tuple[str, str]]:
    import audit_dm_hac_lag as dm_hac

    for finding in dm_hac.scan_file(path):
        if finding.verdict in dm_hac.RATCHET_VERDICTS:
            yield f"{finding.file}::{finding.function}", finding.verdict


def _scan_mdd(path: Path) -> Iterable[tuple[str, str]]:
    import audit_mdd_scale_artifact as mdd

    for finding in mdd.scan_file(path):
        if finding.verdict in mdd.RATCHET_VERDICTS:
            yield finding.key(), finding.verdict


def _scan_fevd(path: Path) -> Iterable[tuple[str, str]]:
    import audit_fevd_ordering as fevd

    site = fevd.classify(path)
    if site is not None and site.classification in ("VIOLATION", "MISLABELED"):
        yield site.path, site.classification


@dataclass(frozen=True)
class Gate:
    name: str
    scan: Callable[[Path], Iterable[tuple[str, str]]]
    baseline: str
    remedy: str


GATES: tuple[Gate, ...] = (
    Gate(
        name="nested-dm-misuse",
        scan=_scan_nested_dm,
        baseline="nested_dm_misuse_baseline.json",
        remedy=(
            "Raw DM/HLN is not valid inference under a nested-model null. Use "
            "Clark-West (2007) for squared-error, or a general-loss / "
            "recursive-bootstrap design for QLIKE/pinball, and wire THAT into "
            "the verdict. If the DM is descriptive only, say so with "
            "`nested-dm: diagnostic-only` and keep it out of the claim sink. "
            "A primary unconditional GW/DM statistic under nesting is accepted "
            "only with the versioned fixed-memory cell manifest, matching runtime "
            "provenance, locally narrow claims, and a trusted external PASS receipt. "
            "Owner: scripts/tests/test_nested_dm_misuse_ratchet.py"
        ),
    ),
    Gate(
        name="dm-hac-lag",
        scan=_scan_dm_hac,
        baseline="dm_hac_lag_baseline.json",
        remedy=(
            "A DM statistic without a HAC variance (or with a degenerate lag) "
            "overstates significance. Use the canonical delegate with an "
            "explicit HAC bandwidth. "
            "Owner: scripts/tests/test_dm_hac_lag_ratchet.py"
        ),
    ),
    Gate(
        name="mdd-scale-artifact",
        scan=_scan_mdd,
        baseline="mdd_scale_artifact_baseline.json",
        remedy=(
            "Comparing max-drawdown across series at different scales is an "
            "artifact, not a result. Normalise before comparing. "
            "Owner: scripts/tests/test_mdd_scale_artifact_ratchet.py"
        ),
    ),
    Gate(
        name="fevd-ordering",
        scan=_scan_fevd,
        baseline="fevd_ordering_baseline.json",
        remedy=(
            "Directional claims (NET / transmitter / receiver) cannot rest on a "
            "Cholesky FEVD: the NET value cannot separate a true transmitter "
            "from whatever was ordered first (K865 died on this). Hand-roll a "
            "KPPS generalized FEVD, or report an order-invariant total "
            "spillover index. A comment saying 'generalized' does not count. "
            "Owner: scripts/tests/test_fevd_ordering_ratchet.py"
        ),
    ),
)


def python_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target] if target.suffix == ".py" else []
    return [
        p
        for p in sorted(target.rglob("*.py"))
        if "__pycache__" not in p.parts
    ]


def run_gates(target: Path) -> list[Violation]:
    """Run every experiment-integrity gate over `target`, newest debt only."""
    files = python_files(target)
    violations: list[Violation] = []
    for gate in GATES:
        frozen = _baseline_sites(gate.baseline)
        for path in files:
            for site, verdict in gate.scan(path):
                if site in frozen:
                    continue
                violations.append(
                    Violation(gate=gate.name, site=site, verdict=verdict, remedy=gate.remedy)
                )
    return violations


CERT_FILENAME = "review_verdict.json"

CERT_REMEDY = (
    "An experiment may only enter main carrying a review verdict that is bound "
    "to the bytes it reviewed. Generate the skeleton — do not transcribe it:\n"
    "      uv run python scripts/experiment_gates.py verdict-template "
    f"--path experiments/<kid> --out experiments/<kid>/{CERT_FILENAME}\n"
    "    Have the reviewer (Codex) read the FROZEN experiment and fill it in:\n"
    '      {"kid": "k1709", "verdict": "PASS", "reviewer": "codex/gpt-5.6-sol",\n'
    '       "reviewed_at": "<ISO8601>", "review_artifact": "<the review file>",\n'
    '       "reviewed_sha256": {"<relpath>": "<sha256>", ...}}\n'
    "    Every file in the claim surface (*.py, README.md, *_results.json) must "
    "be listed with its sha256 AT REVIEW TIME. If you then edit or re-run the "
    "experiment, the hashes stop matching and this gate blocks again — that is "
    "the point. Re-review the new bytes; do not hand-edit the verdict.\n"
    "    Owner: scripts/tests/test_experiment_certification.py"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def claim_surface(exp_dir: Path) -> list[Path]:
    """The files a reader would believe. Code, the write-up, and the numbers.

    A verdict that only pins the .py is not worth much: README and the results
    JSON are where an overclaim actually reaches a human (K1709 v1 shipped a
    README asserting a bound the code never established).
    """
    out: list[Path] = []
    for path in sorted(exp_dir.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.name == CERT_FILENAME:
            continue
        if path.suffix == ".py" or path.name == "README.md" or path.name.endswith("_results.json"):
            out.append(path)
    return out


LEGACY_VERDICT_KEYS = ("final_verdict", "claim_surface_sha256")


def verdict_template(exp_dir: Path) -> dict[str, Any]:
    """The verdict skeleton `certify` accepts, with the claim surface already pinned.

    The reviewer used to copy this schema out of a hand-written brief, and on
    2026-07-14 the copy drifted: Codex reviewed k1709 @c97d690c for half an hour
    and wrote `final_verdict` / `claim_surface_sha256` (two files pinned) where
    the gate reads `verdict` / `reviewed_sha256` (whole claim surface). The
    verdict was FAIL so nothing unsafe merged — but a PASS would have certified
    nothing and burnt the round. A schema that lives in two places drifts; emit
    it from the module that enforces it and there is only one place.
    """
    return {
        "kid": exp_dir.name,
        "verdict": "FILL: PASS or FAIL — anything but PASS blocks the merge",
        "reviewer": "FILL: model / effort",
        "reviewed_at": "FILL: ISO8601",
        "reviewed_commit": "FILL: the frozen SHA you read",
        "review_artifact": "FILL: relpath of the written review",
        "blocking_defects": ["FILL: one entry per defect that makes this a FAIL; [] if PASS"],
        "reviewed_sha256": {
            str(p.relative_to(exp_dir)): _sha256(p) for p in claim_surface(exp_dir)
        },
    }


def certification_violations(exp_dir: Path) -> list[Violation]:
    """Block unless a PASS verdict exists for EXACTLY these bytes.

    Three ways in, all of them closed:
      - no verdict            -> uncertified
      - FAIL verdict          -> the reviewer said no (K1709: merged anyway, CI red 4x)
      - PASS but hashes drift -> reviewed one snapshot, shipped another. This is
        the subtle one: on 2026-07-14 Codex FAILed k1709.py @e42b0885, the agent
        fixed the two CRITICALs, and the stale FAIL was left dangling over code
        that no longer existed. A verdict not bound to a snapshot certifies nothing.
    """
    site = _rel(exp_dir)
    cert_path = exp_dir / CERT_FILENAME

    if not cert_path.exists():
        return [Violation(gate="review-certification", site=site,
                          verdict="uncertified: no review_verdict.json", remedy=CERT_REMEDY)]

    try:
        cert = json.loads(cert_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [Violation(gate="review-certification", site=_rel(cert_path),
                          verdict=f"malformed verdict file: {exc}", remedy=CERT_REMEDY)]

    if not isinstance(cert, dict):
        return [Violation(gate="review-certification", site=_rel(cert_path),
                          verdict="malformed verdict file: not a JSON object", remedy=CERT_REMEDY)]

    verdict = str(cert.get("verdict", "")).strip().upper()
    if verdict != "PASS":
        shown = verdict or "<missing>"
        drifted = sorted(k for k in LEGACY_VERDICT_KEYS if k in cert)
        if not verdict and drifted:
            shown = f"<missing> (found {', '.join(drifted)} — schema drift, not this gate's schema)"
        return [Violation(gate="review-certification", site=site,
                          verdict=f"reviewer verdict is {shown}, not PASS", remedy=CERT_REMEDY)]

    recorded = cert.get("reviewed_sha256")
    if not isinstance(recorded, dict) or not recorded:
        return [Violation(gate="review-certification", site=_rel(cert_path),
                          verdict="PASS verdict pins no reviewed_sha256 — certifies nothing",
                          remedy=CERT_REMEDY)]

    violations: list[Violation] = []
    current = {str(p.relative_to(exp_dir)): p for p in claim_surface(exp_dir)}

    for rel_name in sorted(set(recorded) - set(current)):
        violations.append(Violation(
            gate="review-certification", site=f"{site}/{rel_name}",
            verdict="reviewed file is gone from the experiment", remedy=CERT_REMEDY))

    for rel_name, path in sorted(current.items()):
        want = recorded.get(rel_name)
        if want is None:
            violations.append(Violation(
                gate="review-certification", site=f"{site}/{rel_name}",
                verdict="in the claim surface but never reviewed", remedy=CERT_REMEDY))
            continue
        got = _sha256(path)
        if str(want).lower() != got:
            violations.append(Violation(
                gate="review-certification", site=f"{site}/{rel_name}",
                verdict=f"changed after review (reviewed {str(want)[:12]}…, now {got[:12]}…)",
                remedy=CERT_REMEDY))

    return violations


def cmd_certify(args: argparse.Namespace) -> int:
    target = Path(args.path)
    if not target.is_absolute():
        target = REPO_ROOT / target
    if not target.is_dir():
        print(f"[cert] error: not an experiment directory: {target}", file=sys.stderr)
        return 2

    violations = certification_violations(target)

    if args.json:
        Path(args.json).write_text(json.dumps({
            "path": _rel(target),
            "violations": [
                {"gate": v.gate, "site": v.site, "verdict": v.verdict} for v in violations
            ],
            "passed": not violations,
        }, indent=2), encoding="utf-8")

    if not violations:
        print(f"[cert] PASS — {_rel(target)} carries a PASS verdict bound to its current bytes.")
        return 0

    print(f"[cert] BLOCKED — {_rel(target)} is not certified for main:\n", file=sys.stderr)
    for v in violations:
        print(f"    - {v.site}  ({v.verdict})", file=sys.stderr)
    print(f"\n  → {CERT_REMEDY}", file=sys.stderr)
    return 1


def cmd_verdict_template(args: argparse.Namespace) -> int:
    target = Path(args.path)
    if not target.is_absolute():
        target = REPO_ROOT / target
    if not target.is_dir():
        print(f"[cert] error: not an experiment directory: {target}", file=sys.stderr)
        return 2

    surface = claim_surface(target)
    if not surface:
        print(f"[cert] error: {_rel(target)} has no claim surface to review "
              "(no *.py, README.md, or *_results.json)", file=sys.stderr)
        return 2

    rendered = json.dumps(verdict_template(target), indent=2, ensure_ascii=False)
    if args.out:
        out = Path(args.out)
        if not out.is_absolute():
            out = REPO_ROOT / out
        out.write_text(rendered + "\n", encoding="utf-8")
        print(f"[cert] wrote verdict template for {len(surface)} claim-surface file(s) → {_rel(out)}")
    else:
        print(rendered)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    target = Path(args.path)
    if not target.is_absolute():
        target = REPO_ROOT / target
    if not target.exists():
        print(f"[gate] error: path does not exist: {target}", file=sys.stderr)
        return 2

    violations = run_gates(target)
    scanned = len(python_files(target))

    if args.json:
        report = {
            "path": _rel(target),
            "files_scanned": scanned,
            "gates": [g.name for g in GATES],
            "violations": [
                {"gate": v.gate, "site": v.site, "verdict": v.verdict} for v in violations
            ],
            "passed": not violations,
        }
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")

    if not violations:
        print(
            f"[gate] PASS — {scanned} file(s) under {_rel(target)} cleared "
            f"{len(GATES)} experiment-integrity gates."
        )
        return 0

    print(
        f"[gate] FAIL — {len(violations)} violation(s) under {_rel(target)}:\n",
        file=sys.stderr,
    )
    for gate in GATES:
        hits = [v for v in violations if v.gate == gate.name]
        if not hits:
            continue
        print(f"  [{gate.name}]", file=sys.stderr)
        for v in hits:
            print(f"    - {v.site}  ({v.verdict})", file=sys.stderr)
        print(f"    → {gate.remedy}\n", file=sys.stderr)
    print(
        "This experiment is not accepted. Your own tests passing only shows it "
        "ran the way you meant it to; these gates check it does not break a "
        "rule the repo already learned the hard way.",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="Run all experiment-integrity gates over a path.")
    run.add_argument("--path", required=True, help="experiments/<kid> directory or a .py file")
    run.add_argument("--json", help="write a machine-readable report here")
    run.set_defaults(func=cmd_run)
    cert = sub.add_parser(
        "certify",
        help="Merge-time gate: refuse an experiment that has no PASS verdict "
             "bound to its current bytes.",
    )
    cert.add_argument("--path", required=True, help="experiments/<kid> directory")
    cert.add_argument("--json", help="write a machine-readable report here")
    cert.set_defaults(func=cmd_certify)
    tmpl = sub.add_parser(
        "verdict-template",
        help="Print the review_verdict.json skeleton `certify` accepts, with the "
             "claim surface pinned. Give this to the reviewer instead of describing "
             "the schema in a brief — a described schema drifts, a generated one cannot.",
    )
    tmpl.add_argument("--path", required=True, help="experiments/<kid> directory")
    tmpl.add_argument("--out", help="write the template here instead of stdout")
    tmpl.set_defaults(func=cmd_verdict_template)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
