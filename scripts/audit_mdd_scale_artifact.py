"""Audit the raw-max-drawdown scale-artifact bug class across the whole repo.

BUG CLASS
---------
Raw max drawdown is not comparable across two return series that run at different
exposure.  A vol-managed / de-levered / partially-in-cash strategy shows a shallower
drawdown for purely arithmetic reasons.  Reporting that as evidence of risk-management
skill is a scale artifact.

  - K1702 §5.4 : factor zoo, raw MDD improved 5/6 factors; per unit of realized vol, 1/6.
  - K1265b     : SPY VIX-managed, K1265's "50-62% MDD reduction" collapses to a 9.8-22.1pp
                 gap against a same-realized-volatility benchmark, and no spec survives
                 Holm correction against a circular-shift null.

WHAT THIS SCRIPT DOES
---------------------
Walks every ``experiments/**/*.py`` and ``src/**/*.py``, finds every site that computes a
max drawdown, and classifies whether that site COMPARES drawdowns across series and, if so,
whether it also emits a scale-invariant companion (MDD / realized vol, or an
exposure-matched benchmark, or a delegation to volpred.stats.drawdown).

Verdicts:
  DELEGATES      - uses volpred.stats.drawdown (the canonical helper). Always fine.
  NORMALIZED     - computes a scale-invariant companion alongside the raw MDD. Fine.
  SINGLE_SERIES  - computes MDD but never compares it to another series. Not in class.
  RAW_COMPARISON - compares MDD across >= 2 series with NO scale-invariant companion.
                   *** This is the violation. ***
  UNKNOWN        - could not parse / could not tell. Treated as in-class for the ratchet,
                   because a bug-class audit that silently skips files is a false negative.

A NOTE ON WHAT STATIC ANALYSIS CANNOT DO
----------------------------------------
The substantive rule is runtime: "if the two series' realized vols differ by more than 20%,
you must report the scale-invariant statistic".  No AST can evaluate that.  What this audit
enforces instead is the *only* statically checkable version of it: a site that compares
drawdowns across series must ALSO compute a scale-invariant companion, so that the 20% rule
can even be checked.  The 20% threshold itself is enforced at runtime by
``volpred.stats.drawdown.compare_max_drawdown`` / ``assert_drawdown_comparison_is_fair``.

Run:
    uv run python scripts/audit_mdd_scale_artifact.py
    uv run python scripts/audit_mdd_scale_artifact.py --json /tmp/mdd_audit.json
    uv run python scripts/audit_mdd_scale_artifact.py --violations-only
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_ROOTS = ["experiments", "src", "scripts"]

DELEGATES = "DELEGATES"
NORMALIZED = "NORMALIZED"
SINGLE_SERIES = "SINGLE_SERIES"
RAW_COMPARISON = "RAW_COMPARISON"
UNKNOWN = "UNKNOWN"

#: verdicts the ratchet refuses to let grow
RATCHET_VERDICTS = {RAW_COMPARISON, UNKNOWN}

# --- signatures --------------------------------------------------------------------
# Merely MENTIONING "drawdown" (a tag list, a topic keyword, a docstring) is not a site.
# A site must actually COMPUTE a drawdown.  These are the ways that is done in this repo.
DRAWDOWN_COMPUTE = re.compile(
    r"""(
        cummax | cummin | maximum\.accumulate | minimum\.accumulate
      | expanding\(\s*\)\s*\.\s*max | running_max | peak_to_trough
      | \b\w*max_?draw_?down\w*\s*\(          # calling a max_drawdown-ish function
      | \b\w*_?mdd\w*\s*\(                    # calling an mdd-ish function
      | \bdrawdown\w*\s*=                     # assigning a computed drawdown
      | \b\w*_?mdd\w*\s*=                     # assigning an mdd
    )""",
    re.X | re.I,
)

# Cheap pre-filter so we do not AST-parse the whole repo.
DRAWDOWN_TOKENS = ("drawdown", "max_dd", "maxdd", "mdd", "cummax", "peak_to_trough")

# Identifiers that mean "there is a benchmark / second series in this comparison".
BENCHMARK_TOKENS = (
    "buy_hold",
    "buyhold",
    "buy_and_hold",
    "bh_mdd",
    "mdd_bh",
    "unmanaged",
    "unmgd",
    "benchmark_mdd",
    "mdd_benchmark",
    "baseline_mdd",
    "mdd_baseline",
)

# Identifiers that only exist because two drawdowns are being differenced / ratioed.
COMPARISON_TOKENS = BENCHMARK_TOKENS + (
    "delta_mdd",
    "mdd_delta",
    "mdd_ratio",
    "mdd_diff",
    "mdd_reduction",
    "mdd_retention",
    "mdd_improve",
    "drawdown_reduction",
    "drawdown_improve",
    "relative_mdd",
)

# A site emits a scale-invariant companion, i.e. it is doing the honest thing.
# NOTE: Calmar is deliberately NOT here.  Calmar improvement does not rescue an MDD claim
# (K1265 reported Calmar for every managed spec and still failed the audit); accepting it
# is precisely the false-OK that let K1265 through the first classification pass.
NORMALIZED_TOKENS = (
    "mdd_per_vol",
    "mdd_per_annual_vol",
    "max_drawdown_per_annual_vol",
    "drawdown_per_vol",
    "per_annual_vol",
    "per_unit_vol",
    "scale_invariant",
    "scale-invariant",
    "vol_normalized",
    "vol_normalised",
    "exposure_matched",
    "matched_exposure",
    "matched_vol",
    "vol_matched",
    "same_vol",
    "equal_vol",
    "matched_lambda",
    "matched_bh",
    "matched_benchmark",
    "same_risk",
    "constant_leverage",
    "circular_shift",
    "weight_shuffle",
)

CANONICAL_MODULE = "volpred.stats.drawdown"
CANONICAL_NAMES = (
    "compare_max_drawdown",
    "assert_drawdown_comparison_is_fair",
    "DrawdownComparison",
)


@dataclass
class Finding:
    file: str
    scope: str  # function name, or "<module>"
    lineno: int
    verdict: str
    reasons: list[str]

    def key(self) -> str:
        return f"{self.file}::{self.scope}"


def _src(node: ast.AST, lines: list[str]) -> str:
    start = getattr(node, "lineno", 1) - 1
    end = getattr(node, "end_lineno", start + 1)
    return "\n".join(lines[start:end])


def _has_token(src_lower: str, tokens: tuple[str, ...]) -> list[str]:
    return [t for t in tokens if t in src_lower]


def _delegates(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and CANONICAL_MODULE in node.module:
            return True
        if isinstance(node, ast.Import):
            for a in node.names:
                if CANONICAL_MODULE in a.name:
                    return True
    return False


#: an mdd-ish identifier being bound to a value
MDD_ASSIGN = re.compile(
    r"^\s*(\w*(?:max_?draw_?down|_?mdd)\w*)\s*(?::[^=]+)?=(?!=)", re.I | re.M
)
#: an mdd-ish key being written into a dict literal / results payload
MDD_KEY = re.compile(r"""["'](\w*(?:max_?draw_?down|mdd)\w*)["']\s*:""", re.I)


def _strip_comments_and_docstrings(src: str) -> str:
    """Prose is not code.  A tag list saying 'drawdown' is not a drawdown computation."""
    out = re.sub(r"#.*$", "", src, flags=re.M)
    out = re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "", out)
    return out


def classify_scope(scope_src: str, module_delegates: bool) -> tuple[str, list[str]]:
    code = _strip_comments_and_docstrings(scope_src)
    low = code.lower()

    if not DRAWDOWN_COMPUTE.search(code):
        return "", []  # mentions drawdown, does not compute one -> not a site

    reasons = ["computes a drawdown"]

    if module_delegates and any(n.lower() in low for n in CANONICAL_NAMES):
        reasons.append(f"delegates to {CANONICAL_MODULE}")
        return DELEGATES, reasons

    norm = _has_token(low, NORMALIZED_TOKENS)
    if norm:
        reasons.append(f"scale-invariant companion present: {sorted(set(norm))[:4]}")
        return NORMALIZED, reasons

    # Does this scope hold TWO drawdowns at once?  Either it names a benchmark drawdown,
    # or it derives a delta/ratio between drawdowns, or it binds >= 2 distinct mdd-ish
    # identifiers/keys (the ubiquitous `{spec: metrics(...) for spec in specs}` shape ends
    # up here through its result keys).
    cmp_ = _has_token(low, COMPARISON_TOKENS)
    bound = {m.group(1).lower() for m in MDD_ASSIGN.finditer(code)}
    bound |= {m.group(1).lower() for m in MDD_KEY.finditer(code)}

    if cmp_:
        reasons.append(f"benchmark/delta identifiers: {sorted(set(cmp_))[:4]}")
        return RAW_COMPARISON, reasons
    if len(bound) >= 2:
        reasons.append(f"binds {len(bound)} distinct drawdown values: {sorted(bound)[:4]}")
        return RAW_COMPARISON, reasons

    reasons.append("single drawdown, no benchmark comparison detected")
    return SINGLE_SERIES, reasons


def scan_file(path: Path) -> list[Finding]:
    rel = str(path.relative_to(REPO_ROOT))
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # A skipped file is a false negative for a bug-class audit. Surface it loudly.
        return [Finding(rel, "<unreadable>", 1, UNKNOWN, [f"could not read: {exc}"])]

    low_all = text.lower()
    if not any(t in low_all for t in DRAWDOWN_TOKENS):
        return []

    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [Finding(rel, "<unparseable>", 1, UNKNOWN, [f"syntax error: {exc}"])]

    lines = text.splitlines()
    delegates = _delegates(tree)
    findings: list[Finding] = []

    functions = [
        n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    covered: set[int] = set()
    for fn in functions:
        src = _src(fn, lines)
        verdict, reasons = classify_scope(src, delegates)
        if not verdict:
            continue
        findings.append(Finding(rel, fn.name, fn.lineno, verdict, reasons))
        covered.update(range(fn.lineno, (fn.end_lineno or fn.lineno) + 1))

    # Module-level drawdown code that lives outside any function is a real site too --
    # scripts written as a flat top-to-bottom program are exactly where this bug hides.
    module_only = "\n".join(
        line for i, line in enumerate(lines, start=1) if i not in covered
    )
    verdict, reasons = classify_scope(module_only, delegates)
    if verdict:
        findings.append(Finding(rel, "<module>", 1, verdict, reasons))

    return findings


def scan_population(root: Path = REPO_ROOT) -> list[Finding]:
    findings: list[Finding] = []
    for sub in SCAN_ROOTS:
        base = root / sub
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts or ".claude/worktrees" in str(path):
                continue
            findings.extend(scan_file(path))
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=Path, help="write the full report here")
    ap.add_argument("--violations-only", action="store_true")
    args = ap.parse_args()

    findings = scan_population()
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.verdict] = counts.get(f.verdict, 0) + 1

    violations = [f for f in findings if f.verdict in RATCHET_VERDICTS]

    print(f"scanned roots     : {SCAN_ROOTS}")
    print(f"drawdown sites    : {len(findings)}")
    for v in (DELEGATES, NORMALIZED, SINGLE_SERIES, RAW_COMPARISON, UNKNOWN):
        print(f"  {v:<15s}: {counts.get(v, 0)}")
    print(f"\nratchet-tracked (RAW_COMPARISON + UNKNOWN): {len(violations)}")

    shown = violations if args.violations_only else findings
    for f in sorted(shown, key=lambda x: (x.verdict, x.file)):
        if args.violations_only or f.verdict in RATCHET_VERDICTS:
            print(f"  [{f.verdict:<14s}] {f.file}:{f.lineno} :: {f.scope}")

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "concern": "raw max-drawdown compared across different exposure (scale artifact)",
                    "enforcement_owner": "scripts/tests/test_mdd_scale_artifact_ratchet.py",
                    "canonical": f"{CANONICAL_MODULE}.compare_max_drawdown",
                    "counts": counts,
                    "sites": [asdict(f) for f in findings],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        print(f"\nwritten -> {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
