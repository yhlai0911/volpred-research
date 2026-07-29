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
import logging
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from experiment_claim_surface import is_experiment_claim_surface_file  # noqa: E402

BASELINE_DIR = REPO_ROOT / "storage" / "ops"


@dataclass(frozen=True)
class Violation:
    gate: str
    site: str
    verdict: str
    remedy: str


def baseline_sites_from_payload(payload: object) -> set[str]:
    """Every non-retired Python site frozen in one baseline payload."""
    sites: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, str):
            head = node.split("::", 1)[0]
            if head.endswith(".py"):
                sites.add(node)
        elif isinstance(node, dict):
            for key, value in node.items():
                # A retired site is deliberately no longer frozen. Including
                # it here would let a previously-fixed defect re-enter through
                # the per-experiment gate even while the repo-wide ratchet
                # correctly rejects it.
                if key == "retired":
                    continue
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return sites


def _baseline_sites(name: str) -> set[str]:
    """Read one baseline, then apply the shared payload interpretation."""
    path = BASELINE_DIR / name
    if not path.exists():
        print(f"[gate] WARNING: baseline missing, treating as empty: {path}", file=sys.stderr)
        return set()
    return baseline_sites_from_payload(
        json.loads(path.read_text(encoding="utf-8"))
    )


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _candidate_root(path: Path) -> Path:
    cwd = path if path.is_dir() else path.parent
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return REPO_ROOT
    if proc.returncode == 0:
        return Path(proc.stdout.strip()).resolve()
    return REPO_ROOT


# --- gate adapters -----------------------------------------------------------
# Each adapter yields (site_key, verdict) for the violating sites in one file.
# Detection and verdict semantics come from the auditor module; nothing is
# re-implemented here.


def _scan_nested_dm(path: Path) -> Iterable[tuple[str, str]]:
    # Keep auditor imports on the ``run`` path.  ``certify`` is called by
    # merge_worktree.sh with bare python3 and must remain stdlib-only even when
    # the volpred package has not been installed in that interpreter.
    import audit_nested_dm_misuse as nested_dm

    finding = nested_dm.scan_file(path, _candidate_root(path))
    if finding is not None and finding.test_role not in nested_dm.SAFE_ROLES:
        yield finding.file, finding.test_role


def _scan_dm_hac(path: Path) -> Iterable[tuple[str, str]]:
    import audit_dm_hac_lag as dm_hac

    for finding in dm_hac.scan_file(path, _candidate_root(path)):
        if finding.verdict in dm_hac.RATCHET_VERDICTS:
            yield f"{finding.file}::{finding.function}", finding.verdict


def _scan_mdd(path: Path) -> Iterable[tuple[str, str]]:
    import audit_mdd_scale_artifact as mdd

    for finding in mdd.scan_file(path, _candidate_root(path)):
        if finding.verdict in mdd.RATCHET_VERDICTS:
            yield finding.key(), finding.verdict


def _scan_fevd(path: Path) -> Iterable[tuple[str, str]]:
    import audit_fevd_ordering as fevd

    site = fevd.classify(path, _candidate_root(path))
    if site is not None and site.classification in ("VIOLATION", "MISLABELED"):
        yield site.path, site.classification


@dataclass(frozen=True)
class Gate:
    name: str
    scan: Callable[[Path], Iterable[tuple[str, str]]]
    baseline: str
    remedy: str
    certify: bool = False


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
            "A naked max-drawdown comparison across differently exposed return "
            "series is a scale artifact, not evidence of protection. Use "
            "volpred.stats.drawdown.compare_max_drawdown (or an equivalent "
            "scale/exposure companion) and keep raw MDD out of the claim sink "
            "when exposure_mismatch is true. A positive exposure-matched gap "
            "still needs its own phase/randomization null before it supports a "
            "timing claim. "
            "Owner: scripts/tests/test_mdd_scale_artifact_ratchet.py"
        ),
        certify=True,
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

# ``merge_worktree.sh`` calls ``certify`` with bare system Python so merge
# admission cannot depend on uv/site-packages. The MDD owner is deliberately
# stdlib-only and is therefore safe to arm there. Other methodology gates stay
# on ``run`` until their import chains meet the same contract.
CERTIFY_GATES: tuple[Gate, ...] = tuple(gate for gate in GATES if gate.certify)


def python_files(target: Path) -> list[Path]:
    if target.is_file():
        return [target] if target.suffix == ".py" else []
    return [
        p
        for p in sorted(target.rglob("*.py"))
        if "__pycache__" not in p.parts
    ]


def run_gates(
    target: Path,
    gates: Iterable[Gate] = GATES,
    *,
    baseline_sites: Mapping[str, set[str]] | None = None,
) -> list[Violation]:
    """Run selected integrity gates (all by default), newest debt only."""
    files = python_files(target)
    violations: list[Violation] = []
    for gate in gates:
        frozen = (
            baseline_sites[gate.baseline]
            if baseline_sites is not None
            else _baseline_sites(gate.baseline)
        )
        for path in files:
            for site, verdict in gate.scan(path):
                if site in frozen and verdict != "invalid_fixed_memory_evidence":
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
    "    Every file in the claim surface (*.py, README.md, *_results.json, and "
    "reader-facing figures) must "
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
    """The files a reader would believe: code, prose, numbers, and figures.

    A verdict that only pins the .py is not worth much: README and the results
    JSON and rendered figures are where an overclaim actually reaches a human
    (K1709 v1 shipped a README asserting a bound the code never established;
    rev4 initially left stale scope labels inside its tracked power figure).
    """
    out: list[Path] = []
    for path in sorted(exp_dir.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.name == CERT_FILENAME:
            continue
        if is_experiment_claim_surface_file(path):
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


def _review_certification_violations(exp_dir: Path) -> list[Violation]:
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


# K-ids below this predate the registry becoming the only legal allocator for
# ad-hoc dispatch (K1719 collision 2026-07-17; second collision k1732 2026-07-19,
# hand-picked by scanning worktrees while the registry had reserved it for a
# different topic). From here on, a numeric kid entering main must exist in the
# registry — kid_reserve.py is the write-side guard, this gate is the read-side
# enforcement that finally wires it to every dispatch path (assign_762984a5).
KID_REGISTRY_ENFORCE_FROM = 1719
_KID_REGISTRY_REMEDY = (
    "Reserve the K-id BEFORE the experiment: uv run python scripts/kid_reserve.py "
    "reserve --owner <who> --topic '<topic>'. If this kid was picked by hand and "
    "collided, repair with `kid_reserve.py reassign` (see its --help)."
)


def _canonical_registry_path() -> Path:
    """The LIVE registry in the main checkout, not a worktree's stale branch copy."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True, text=True, timeout=10, check=True,
        )
        common = Path(proc.stdout.strip())
        if not common.is_absolute():
            common = (Path(__file__).resolve().parent / common).resolve()
        return common.parent / "storage" / "ops" / "k_id_registry.json"
    except (OSError, subprocess.SubprocessError) as exc:
        logging.warning("kid-registry: git common-dir resolution failed (%s); using local path", exc)
        return REPO_ROOT / "storage" / "ops" / "k_id_registry.json"


def kid_registry_numbers_from_payload(payload: object) -> set[int] | None:
    if not isinstance(payload, dict):
        return None
    try:
        return {
            int(row.get("number") or 0)
            for row in payload.get("reservations", [])
            if isinstance(row, dict)
        }
    except (TypeError, ValueError):  # silent-ok: caller turns invalid schema into a fail-closed violation.
        return None


def _kid_registry_violations(
    exp_dir: Path,
    *,
    registry_numbers: set[int] | None = None,
) -> list[Violation]:
    m = re.fullmatch(r"k(\d+)[a-z]?(?:_.*)?", exp_dir.name)
    if not m:
        return []  # named experiments (member_qa_*, vt_*) are outside the numeric allocator
    number = int(m.group(1))
    if number < KID_REGISTRY_ENFORCE_FROM:
        return []
    registry_path = _canonical_registry_path()
    if registry_numbers is None:
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            numbers = kid_registry_numbers_from_payload(registry)
        except (OSError, ValueError) as exc:
            return [Violation(gate="kid-registry", site=_rel(exp_dir),
                              verdict=f"registry unreadable ({exc}) — cannot verify K-id allocation",
                              remedy=_KID_REGISTRY_REMEDY)]
        if numbers is None:
            return [Violation(
                gate="kid-registry",
                site=_rel(exp_dir),
                verdict="registry schema invalid — cannot verify K-id allocation",
                remedy=_KID_REGISTRY_REMEDY,
            )]
    else:
        numbers = registry_numbers
    if number not in numbers:
        return [Violation(
            gate="kid-registry", site=_rel(exp_dir),
            verdict=(f"K{number} has no reservation in {registry_path.name} — "
                     "hand-picked K-ids collide with queued reservations (K1719, k1732)"),
            remedy=_KID_REGISTRY_REMEDY)]
    return []


def certification_violations(
    exp_dir: Path,
    *,
    baseline_sites: Mapping[str, set[str]] | None = None,
    registry_numbers: set[int] | None = None,
) -> list[Violation]:
    """Merge admission = methodology hard gates plus byte-bound review.

    K1695 exposed the remaining path split: compute-queue completion ran the
    methodology ``run`` command, while worktree merge called only ``certify``.
    A perfectly shaped PASS receipt could therefore admit a new naked raw-MDD
    comparison. Run the stdlib-compatible merge gates from the trusted main
    checkout before accepting the review receipt. Auditor import/scan failures
    are intentionally not swallowed: a gate that cannot run must block merge.
    """
    return [
        *run_gates(
            exp_dir,
            CERTIFY_GATES,
            baseline_sites=baseline_sites,
        ),
        *_review_certification_violations(exp_dir),
        *_kid_registry_violations(
            exp_dir,
            registry_numbers=registry_numbers,
        ),
    ]


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
        print(
            f"[cert] PASS — {_rel(target)} carries a PASS verdict bound to its "
            f"current bytes and cleared {len(CERTIFY_GATES)} merge-time "
            "integrity gate(s)."
        )
        return 0

    print(f"[cert] BLOCKED — {_rel(target)} is not certified for main:\n", file=sys.stderr)
    for v in violations:
        print(f"    - [{v.gate}] {v.site}  ({v.verdict})", file=sys.stderr)
    remedies: dict[str, str] = {}
    for violation in violations:
        remedies.setdefault(violation.gate, violation.remedy)
    for gate_name, remedy in remedies.items():
        print(f"\n  → [{gate_name}] {remedy}", file=sys.stderr)
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
