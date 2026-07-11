#!/usr/bin/env python3
"""Full-population audit of self-written Diebold-Mariano / HLN implementations.

Bug class (K1655, 2026-07-11): a local DM helper that sets its Newey-West
bandwidth to ``lag = h - 1`` silently applies *no* HAC correction when h == 1,
because the correction loop ``range(1, h)`` is then empty. The canonical
implementation (``volpred.stats.model_evaluation.dm_test``) floors the bandwidth
at 1 -- ``max_lag = max(1, min(ceil(h**(1/3) * n**(1/3)), n // 4))`` -- so it
never degenerates.

That matters whenever the loss differential is autocorrelated for reasons other
than overlapping forecast windows (misspecified model vs benchmark, persistent
predictors like NFCI / VIX). In K1655 the differential had acf(1) = 0.68 and the
missing HAC correction inflated |t|: 26 of 60 DM cells read as Harvey-significant
before the fix, 18 after.

This script classifies every local DM in ``experiments/`` by its bandwidth rule
so the class can be triaged as a population rather than one file at a time.
Static analysis only -- it never imports or executes experiment code.

Usage:
    uv run python scripts/audit_dm_hac_lag.py                    # human summary
    uv run python scripts/audit_dm_hac_lag.py --json report.json # machine report
    uv run python scripts/audit_dm_hac_lag.py --affected-only    # only real bugs
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from volpred.ops.diagnostics import warn  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS_DIR = REPO_ROOT / "experiments"

# Function names that plausibly implement a DM / HLN test locally.
DM_NAME_RE = re.compile(r"(^|_)(dm|hln|diebold|mariano)(_|$)", re.IGNORECASE)

# Names an author would bind a Newey-West bandwidth to.
LAG_NAME_RE = re.compile(
    r"^(nw_)?(max_)?(lag|lags|bandwidth|band|q|trunc|truncation)$", re.IGNORECASE
)

# Verdicts, ordered worst -> best.
DEGENERATE = "degenerate_at_h1"  # lag = h-1 with no floor: zero HAC when h=1
H_INCLUSIVE = "h_lags_inclusive"  # range(1, h+1): keeps lag 1, but never scales with n
HARDCODED = "hardcoded"  # fixed integer bandwidth, independent of h and n
CANONICAL_LIKE = "canonical_like"  # n**(1/3) style rule, or floored at >= 1
DELEGATES = "delegates_to_canonical"  # imports volpred canonical dm_test
UNKNOWN = "unknown"  # DM-ish def found, no bandwidth binding recognised
NOT_A_TEST = "not_a_dm_test"  # name matched but the body computes no test statistic

SEVERITY = {
    DEGENERATE: 0,
    UNKNOWN: 1,
    H_INCLUSIVE: 2,
    HARDCODED: 3,
    CANONICAL_LIKE: 4,
    DELEGATES: 5,
    NOT_A_TEST: 6,
}

# A real DM implementation has to touch the loss differential's second moment.
# Plotting / formatting / classification helpers whose name merely contains "dm"
# do not, and must not inflate the population count.
TEST_MACHINERY_RE = re.compile(
    r"\b(np\.var|\.var\(|np\.cov|\.cov\(|gamma|autocov|t_stat|tstat|dm_stat"
    r"|stats\.t\.|norm\.cdf|p_value|pval)\b"
)

CANONICAL_IMPORT_RE = re.compile(
    r"from\s+volpred\.stats\.model_evaluation\s+import[^\n]*\bdm_test\b"
    r"|from\s+volpred\.stats\s+import[^\n]*\bmodel_evaluation\b"
)

# Evidence that the file actually evaluates a one-step-ahead horizon, which is
# the only place lag = h-1 fully degenerates.
H1_RE = re.compile(
    r"\bh\s*=\s*1\b|\bhorizon\s*=\s*1\b|\bHORIZONS?\s*[:=]\s*[\[\(]\s*1\b"
    r"|\bhorizons?\s*[:=]\s*[\[\(]\s*1\b|\bH\s*=\s*1\b",
)


@dataclass
class Finding:
    file: str
    function: str
    lineno: int
    verdict: str
    lag_expr: str | None
    exercises_h1: bool
    notes: list[str] = field(default_factory=list)

    @property
    def exposed(self) -> bool:
        """Structurally exposed: applies zero HAC correction on a one-step cell.

        This is exposure, not a proven error. At h == 1 the textbook DM statistic
        legitimately uses no HAC term, because a correctly specified one-step
        forecast has a serially uncorrelated loss differential. The correction
        only matters when that assumption fails -- a misspecified challenger, or a
        persistent predictor. Whether it fails at any given site is an empirical
        question about that site's loss differential (K1655: acf(1) = 0.68), and
        static analysis cannot answer it. Confirming materiality means re-running
        the experiment and measuring the autocorrelation.
        """
        return self.verdict == DEGENERATE and self.exercises_h1


def _classify_lag_expr(src: str) -> tuple[str, list[str]]:
    """Classify a bandwidth expression by its source text."""
    notes: list[str] = []
    compact = src.replace(" ", "")

    canonical_shape = (
        "**(1/3)" in compact
        or "**(1./3" in compact
        or "ceil" in compact.lower()
        or "n//4" in compact
    )
    minus_one = re.search(r"\b(h|horizon|H)\s*-\s*1\b", src) is not None
    floored = compact.startswith("max(") or "max(1," in compact or "max(1 ," in compact

    if canonical_shape and not minus_one:
        return CANONICAL_LIKE, notes
    if minus_one and floored:
        notes.append("h-1 present but floored via max() -- does not degenerate")
        return CANONICAL_LIKE, notes
    if minus_one and canonical_shape:
        notes.append("h-1 combined with a canonical-shaped bound")
        return CANONICAL_LIKE, notes
    if minus_one:
        notes.append("lag = h-1 with no floor: HAC loop is empty when h == 1")
        return DEGENERATE, notes
    if re.fullmatch(r"\d+", compact):
        notes.append(f"bandwidth fixed at {compact}, ignores h and sample size")
        return HARDCODED, notes
    if floored:
        return CANONICAL_LIKE, notes
    return UNKNOWN, notes


def _scan_function(fn: ast.FunctionDef, path: Path, exercises_h1: bool) -> Finding | None:
    """Find the bandwidth binding inside one DM-ish function."""
    body_src = ast.unparse(fn)

    if not TEST_MACHINERY_RE.search(body_src):
        return Finding(
            file=str(path.relative_to(REPO_ROOT)),
            function=fn.name,
            lineno=fn.lineno,
            verdict=NOT_A_TEST,
            lag_expr=None,
            exercises_h1=exercises_h1,
            notes=["name matched but body computes no test statistic"],
        )

    lag_expr: str | None = None

    for node in ast.walk(fn):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and LAG_NAME_RE.match(target.id):
                    if node.value is not None:
                        lag_expr = ast.unparse(node.value)

    # A HAC loop written inline as `for lag in range(1, h)` binds no name but is
    # the same defect -- range(1, 1) is empty.
    if lag_expr is None:
        for node in ast.walk(fn):
            if isinstance(node, ast.For) and isinstance(node.iter, ast.Call):
                callee = node.iter.func
                if isinstance(callee, ast.Name) and callee.id == "range":
                    args = node.iter.args
                    if len(args) < 2:
                        continue
                    upper = ast.unparse(args[1])
                    bare_h = re.fullmatch(r"\s*(h|horizon|H)\s*", upper)
                    h_plus_1 = re.fullmatch(r"\s*(h|horizon|H)\s*\+\s*1\s*", upper)
                    if not (bare_h or h_plus_1):
                        continue
                    if bare_h:
                        verdict = DEGENERATE
                        notes = ["inline `range(1, h)`: HAC loop is empty when h == 1"]
                    else:
                        verdict = H_INCLUSIVE
                        notes = [
                            "inline `range(1, h+1)`: keeps lag 1 at h == 1, so no zero-HAC "
                            "degeneracy, but the bandwidth never grows with the sample"
                        ]
                    return Finding(
                        file=str(path.relative_to(REPO_ROOT)),
                        function=fn.name,
                        lineno=fn.lineno,
                        verdict=verdict,
                        lag_expr=f"range(1, {upper})",
                        exercises_h1=exercises_h1,
                        notes=notes,
                    )

    if lag_expr is None:
        return Finding(
            file=str(path.relative_to(REPO_ROOT)),
            function=fn.name,
            lineno=fn.lineno,
            verdict=UNKNOWN,
            lag_expr=None,
            exercises_h1=exercises_h1,
            notes=["no bandwidth binding recognised -- inspect by hand"],
        )

    verdict, notes = _classify_lag_expr(lag_expr)
    return Finding(
        file=str(path.relative_to(REPO_ROOT)),
        function=fn.name,
        lineno=fn.lineno,
        verdict=verdict,
        lag_expr=lag_expr,
        exercises_h1=exercises_h1,
        notes=notes,
    )


def scan_file(path: Path) -> list[Finding]:
    # A skipped file is a false negative for a bug-class audit: it silently
    # shrinks the population being certified. Never drop one without a trace.
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        warn("audit_dm_hac_lag", "unreadable file skipped", path=str(path), err=str(exc))
        return []

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        warn("audit_dm_hac_lag", "unparseable file skipped", path=str(path), err=str(exc))
        return []

    exercises_h1 = H1_RE.search(source) is not None
    delegates = CANONICAL_IMPORT_RE.search(source) is not None

    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not DM_NAME_RE.search(node.name):
            continue
        finding = _scan_function(node, path, exercises_h1)
        if finding is None:
            continue
        if delegates and finding.verdict == UNKNOWN:
            finding.verdict = DELEGATES
            finding.notes = ["wraps the canonical volpred dm_test"]
        findings.append(finding)

    return findings


def scan_population(root: Path = EXPERIMENTS_DIR) -> list[Finding]:
    findings: list[Finding] = []
    for path in sorted(root.rglob("*.py")):
        findings.extend(scan_file(path))
    findings.sort(key=lambda f: (SEVERITY[f.verdict], not f.exercises_h1, f.file))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="write the full report here")
    parser.add_argument(
        "--affected-only",
        action="store_true",
        help="print only structurally exposed sites (degenerate bandwidth AND an h=1 cell)",
    )
    args = parser.parse_args()

    findings = [f for f in scan_population() if f.verdict != NOT_A_TEST]
    exposed = [f for f in findings if f.exposed]

    counts: dict[str, int] = {}
    for f in findings:
        counts[f.verdict] = counts.get(f.verdict, 0) + 1

    if args.json:
        payload = {
            "scan_scope": "experiments/**/*.py (full population, static AST)",
            "bug_class": "DM HAC bandwidth lag=h-1 applies zero HAC correction at h=1",
            "canonical_owner": "volpred.stats.model_evaluation.dm_test",
            "materiality_caveat": (
                "Exposure is structural, not a proven error. Zero HAC at h=1 is the "
                "textbook DM formula and is only wrong when the loss differential is "
                "actually autocorrelated. Confirming materiality at any site requires "
                "re-running it and measuring the differential's acf."
            ),
            "total_local_dm_functions": len(findings),
            "verdict_counts": counts,
            "structurally_exposed": len(exposed),
            "findings": [asdict(f) for f in findings],
        }
        args.json.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"[audit] report written: {args.json}")

    shown = exposed if args.affected_only else findings
    print(f"[audit] local DM implementations found: {len(findings)}")
    for verdict, count in sorted(counts.items(), key=lambda kv: SEVERITY[kv[0]]):
        print(f"[audit]   {verdict:<24} {count}")
    print(
        f"[audit] STRUCTURALLY EXPOSED (zero HAC on an h=1 cell): {len(exposed)}"
        " -- materiality needs a re-run, see --json caveat"
    )

    for f in shown:
        flag = "EXPO" if f.exposed else "    "
        h1 = "h=1" if f.exercises_h1 else "   "
        print(f"{flag} [{f.verdict:<22}] {h1} {f.file}:{f.lineno} {f.function}()")
        if f.lag_expr:
            print(f"        lag = {f.lag_expr}")
        for note in f.notes:
            print(f"        -- {note}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
