#!/usr/bin/env python3
"""Audit nested forecast comparisons that use raw DM/HLN as claim evidence.

Clark and West (2007) show that, under the null for nested forecasting models,
the larger model's extra estimated coefficients add forecast noise.  A raw
Diebold--Mariano loss-difference statistic therefore does not have the usual
equal-accuracy interpretation.  HLN changes the small-sample scaling; it does
not remove this nesting bias.  This auditor finds path-level sites where three
pieces coexist:

1. strong evidence that the augmented model contains the baseline model;
2. raw DM/HLN, or an equivalent HAC mean test of an unadjusted loss difference;
3. a verdict/claim sink fed by that evidence (or a site requiring manual review).

This is deliberately a conservative static audit.  It never imports experiment
code.  Findings are keyed by file because model construction, DM computation,
and verdict logic are commonly split across functions.  Explicitly reviewed
sites where Clark--West governs the verdict and raw DM is only directional or
descriptive are returned separately as safe controls.  Nonnested comparisons
are outside the audit population rather than being washed clean by a marker.

Usage:
    uv run python scripts/audit_nested_dm_misuse.py
    uv run python scripts/audit_nested_dm_misuse.py --json /tmp/nested-dm.json
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
from volpred.ops.diagnostics import warn  # noqa: E402

SCAN_GLOB = "experiments/**/*.py"

BASE_WORDS = r"(?:base(?:line)?|restricted|small|parsimonious|null)"
AUG_WORDS = r"(?:aug(?:mented)?|full|unrestricted|large|challenger)"

EXPLICIT_NESTED_RE = re.compile(
    r"(?<!non-)\bnested[- ](?:model|forecast|comparison|ladder)|"
    r"(?:model|forecast)s?\s+(?:are|is)\s+nested|"
    r"巢狀(?:模型|比較)|嵌套(?:模型|比較)",
    re.IGNORECASE,
)
BASE_AUG_PROSE_RE = re.compile(
    rf"{BASE_WORDS}.{{0,100}}{AUG_WORDS}|{AUG_WORDS}.{{0,100}}{BASE_WORDS}|"
    r"\bbaseline\b.{0,100}\+\s*[A-Za-z_]",
    re.IGNORECASE,
)

# A reference-list entry citing Clark--West is bibliography, not a statement
# that this file compares nested models.  Everything else in the nesting
# channel stays deliberately broad: the 2026-07-13 audit
# (docs/governance/2026-07/nested_dm_fp_narrowing_audit.md) established that a
# lexical narrowing tight enough to drop the false positives also drops 109
# genuinely nested comparisons.  False positives are retired by recorded
# adjudication in storage/ops/nested_dm_misuse_baseline.json, not by loosening
# what counts as evidence here.
BIBLIOGRAPHIC_NESTED_RE = re.compile(
    r"[\"']?title[\"']?\s*:|Tests of Equal Forecast Accuracy and "
    r"Encompassing for Nested Models",
    re.IGNORECASE,
)

RAW_DM_CALL_RE = re.compile(
    r"(?:^|_)(?:dm(?:_test(?:_func|_hac)?|_hln|_stat)?|hln_dm|"
    r"diebold_mariano(?:_test)?|mariano_test)(?:_|$)",
    re.IGNORECASE,
)
NON_TEST_DM_CALL_RE = re.compile(
    r"plot|fig|chart|heatmap|format|classif|reader|ledger|bootstrap|"
    r"non_dm|path_is|^(?:get|read|load|extract|find|collect)_",
    re.IGNORECASE,
)
RAW_DM_TEXT_RE = re.compile(
    r"diebold.?mariano|\bDM(?:[_ -]?(?:test|stat|t|p|HLN))?\b|"
    r"\bHLN\b|dm_test|dm_hln|hln_dm|DM_t|DM_p|"
    r"loss_diff|mean_loss_diff|\bdloss\b",
    re.IGNORECASE,
)
GENERIC_LOSS_TEST_RE = re.compile(
    r"(?:hac|newey|one_sample|mean_test|t_test|ttest|intercept).{0,50}"
    r"(?:loss_diff|dloss|mean_loss_diff)|"
    r"(?:loss_diff|dloss|mean_loss_diff).{0,50}"
    r"(?:hac|newey|one_sample|mean_test|t_test|ttest|intercept)",
    re.IGNORECASE,
)

CLAIM_WORD_RE = re.compile(
    r"verdict|conclusion|summary|evidence|decision|recommendation|"
    r"primary|decisive|headline|gate|pass|reject|significant|"
    r"predictive|incremental|better|worse|harvey|\bnull\b|\bfail\b",
    re.IGNORECASE,
)
CLAIM_TARGET_RE = re.compile(
    r"verdict|conclusion|summary|evidence|decision|recommendation|"
    r"(?:primary|harvey|gate|significant|reject|pass)(?:_|$)|"
    r"(?:_|^)(?:primary|harvey|gate|significant|reject|pass)",
    re.IGNORECASE,
)
CLAIM_FUNCTION_RE = re.compile(
    r"classif|summari|verdict|conclu|decid|adjudicat|evaluate|main",
    re.IGNORECASE,
)

# These are intentionally demanding declarations, not a mere file-level CW
# keyword.  K1679-rev contains Clark-West for only selected cells and must not
# be washed clean.  The safe controls explicitly say DM is non-governing or CW
# covers every primary comparison.
DM_DIAGNOSTIC_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?:ordinary\s+)?DM.{0,120}(?:directional cross-check|descriptive only|"
    r"diagnostic(?:[- ]only| only))|"
    r"(?:directional cross-check|descriptive only|diagnostic(?:[- ]only| only))"
    r".{0,120}(?<![A-Za-z0-9_-])(?:ordinary\s+)?DM|"
    r"(?<![A-Za-z0-9_-])nested-dm:\s*diagnostic[- ]only",
    re.IGNORECASE | re.DOTALL,
)
FULL_CW_PRIMARY_RE = re.compile(
    r"Clark[- ]West.{0,80}(?:EVERY|ALL)\s+primary|"
    r"(?:EVERY|ALL)\s+primary.{0,80}Clark[- ]West|"
    r"nested-dm:\s*cw-primary",
    re.IGNORECASE | re.DOTALL,
)
PRIMARY_DM_DECL_RE = re.compile(
    r"\bPRIMARY\b.{0,80}\b(?:DM|HLN)\b|\b(?:DM|HLN)\b.{0,80}\bPRIMARY\b",
    re.IGNORECASE,
)
@dataclass(frozen=True)
class Evidence:
    line: int
    text: str


@dataclass
class Finding:
    file: str
    test_role: str
    nested_evidence: list[Evidence] = field(default_factory=list)
    raw_dm_evidence: list[Evidence] = field(default_factory=list)
    claim_evidence: list[Evidence] = field(default_factory=list)
    safe_role_evidence: list[Evidence] = field(default_factory=list)


@dataclass
class AuditResult:
    findings: list[Finding]
    reviewed_safe: list[Finding]
    scan_errors: list[str]
    scanned_files: int


def _line(source_lines: list[str], lineno: int) -> Evidence:
    idx = max(0, min(len(source_lines) - 1, lineno - 1))
    return Evidence(lineno, source_lines[idx].strip()[:240])


def _target_tokens(node: ast.AST) -> list[str]:
    tokens: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            tokens.append(child.id)
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            tokens.append(child.value)
        elif isinstance(child, ast.Attribute):
            tokens.append(child.attr)
    return tokens


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _nested_ast_evidence(tree: ast.AST, lines: list[str]) -> list[Evidence]:
    evidence: list[Evidence] = []
    all_names = {node.id.lower() for node in ast.walk(tree) if isinstance(node, ast.Name)}

    # Paired identifiers are strong path-level evidence even if construction and
    # evaluation live in separate functions.
    paired_prefixes = (("base", "aug"), ("baseline", "augmented"), ("restricted", "unrestricted"))
    for left, right in paired_prefixes:
        left_names = {name for name in all_names if left in name}
        right_names = {name for name in all_names if right in name}
        left_shapes = {name.replace(left, "<model>") for name in left_names}
        right_shapes = {name.replace(right, "<model>") for name in right_names}
        shared_shapes = left_shapes & right_shapes
        if shared_shapes:
            paired_names = {
                name
                for name in left_names | right_names
                if name.replace(left, "<model>").replace(right, "<model>") in shared_shapes
            }
            first = next(
                (
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Name)
                    and node.id.lower() in paired_names
                ),
                None,
            )
            if first is not None:
                evidence.append(_line(lines, first.lineno))
            break

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        target_text = " ".join(_target_tokens(ast.Tuple(elts=targets, ctx=ast.Load()))).lower()
        value_text = ast.unparse(value).lower() if value is not None else ""
        target_is_aug = bool(re.search(AUG_WORDS, target_text, re.IGNORECASE))
        value_has_base = bool(re.search(BASE_WORDS, value_text, re.IGNORECASE))
        is_subset_build = target_is_aug and value_has_base and (
            isinstance(value, (ast.BinOp, ast.List, ast.Tuple, ast.Call))
            or ".assign(" in value_text
            or "[*" in value_text
        )
        if is_subset_build:
            evidence.append(_line(lines, node.lineno))

    return _dedupe(evidence)


def _raw_dm_ast_evidence(tree: ast.AST, lines: list[str]) -> list[Evidence]:
    evidence: list[Evidence] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        call_text = ast.unparse(node)
        parentish = call_text.lower()
        source_line = lines[node.lineno - 1] if 0 < node.lineno <= len(lines) else ""
        raw_name = (
            bool(RAW_DM_CALL_RE.search(name))
            and not NON_TEST_DM_CALL_RE.search(name)
            and not re.search(r"clark|(?:^|_)cw(?:_|$)", name, re.IGNORECASE)
        )
        generic_loss_test = bool(GENERIC_LOSS_TEST_RE.search(parentish)) or bool(
            re.search(r"\bdm\w*\s*(?:,\s*\w+)?\s*=", source_line, re.I)
            and re.search(r"hac|newey|one_sample|mean_test|intercept|ols_hac", name, re.I)
        )
        if raw_name or generic_loss_test:
            evidence.append(_line(lines, node.lineno))
    return _dedupe(evidence)


def _claim_ast_evidence(tree: ast.AST, lines: list[str]) -> list[Evidence]:
    evidence: list[Evidence] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body = "\n".join(ast.unparse(stmt) for stmt in node.body)
            if CLAIM_FUNCTION_RE.search(node.name) and RAW_DM_TEXT_RE.search(body) and CLAIM_WORD_RE.search(body):
                evidence.append(_line(lines, node.lineno))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            target_text = " ".join(_target_tokens(ast.Tuple(elts=targets, ctx=ast.Load())))
            value_text = ast.unparse(node.value) if node.value is not None else ""
            if CLAIM_TARGET_RE.search(target_text) and RAW_DM_TEXT_RE.search(value_text):
                evidence.append(_line(lines, node.lineno))
        elif isinstance(node, ast.If):
            test_text = ast.unparse(node.test)
            body_text = "\n".join(ast.unparse(stmt) for stmt in [*node.body, *node.orelse])
            if RAW_DM_TEXT_RE.search(test_text) and CLAIM_WORD_RE.search(body_text):
                evidence.append(_line(lines, node.lineno))
    return _dedupe(evidence)


def _regex_evidence(pattern: re.Pattern[str], lines: list[str]) -> list[Evidence]:
    return [
        Evidence(i, line.strip()[:240])
        for i, line in enumerate(lines, start=1)
        if pattern.search(line)
    ]


def _dedupe(items: list[Evidence], limit: int = 8) -> list[Evidence]:
    seen: set[tuple[int, str]] = set()
    out: list[Evidence] = []
    for item in items:
        key = (item.line, item.text)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def scan_file(path: Path, root: Path = REPO_ROOT) -> Finding | None:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))

    nested = [
        evidence
        for evidence in _regex_evidence(EXPLICIT_NESTED_RE, lines)
        if not BIBLIOGRAPHIC_NESTED_RE.search(evidence.text)
    ]
    if not nested:
        prose = _regex_evidence(BASE_AUG_PROSE_RE, lines)
        nested.extend(prose[:3])
    nested.extend(_nested_ast_evidence(tree, lines))
    nested = _dedupe(nested)
    if not nested:
        return None

    raw = _raw_dm_ast_evidence(tree, lines)
    # Result keys and generic one-sample loss tests can be split over lines, so
    # retain narrow textual evidence as a second channel.
    raw.extend(_regex_evidence(GENERIC_LOSS_TEST_RE, lines))
    raw = _dedupe(raw)
    if not raw:
        return None

    claim = _claim_ast_evidence(tree, lines)
    for i, line in enumerate(lines, start=1):
        if RAW_DM_TEXT_RE.search(line) and CLAIM_WORD_RE.search(line):
            claim.append(Evidence(i, line.strip()[:240]))
    claim = _dedupe(claim)

    full_cw = _regex_evidence(FULL_CW_PRIMARY_RE, lines)
    diagnostic = _regex_evidence(DM_DIAGNOSTIC_RE, lines)
    safe = full_cw or (diagnostic if not PRIMARY_DM_DECL_RE.search(source) else [])
    safe = _dedupe(safe)
    if full_cw or (diagnostic and not PRIMARY_DM_DECL_RE.search(source)):
        role = "diagnostic_with_cw_primary"
    else:
        role = "primary_raw_dm" if claim else "review_required"
    return Finding(
        file=path.relative_to(root).as_posix(),
        test_role=role,
        nested_evidence=nested,
        raw_dm_evidence=raw,
        claim_evidence=claim,
        safe_role_evidence=safe,
    )


def scan_population(root: Path = REPO_ROOT) -> AuditResult:
    findings: list[Finding] = []
    reviewed_safe: list[Finding] = []
    errors: list[str] = []
    paths = sorted(root.glob(SCAN_GLOB))
    for path in paths:
        try:
            finding = scan_file(path, root)
        except (OSError, UnicodeError, SyntaxError) as exc:
            message = (
                f"{path.relative_to(root).as_posix()}: "
                f"{type(exc).__name__}: {exc}"
            )
            warn(
                "audit_nested_dm_misuse",
                "experiment file could not be scanned",
                path=path.relative_to(root).as_posix(),
                err=str(exc),
            )
            errors.append(message)
            continue
        if finding is None:
            continue
        if finding.test_role == "diagnostic_with_cw_primary":
            reviewed_safe.append(finding)
        else:
            findings.append(finding)
    return AuditResult(findings, reviewed_safe, errors, len(paths))


def _payload(result: AuditResult) -> dict:
    roles: dict[str, int] = {}
    for finding in [*result.findings, *result.reviewed_safe]:
        roles[finding.test_role] = roles.get(finding.test_role, 0) + 1
    return {
        "schema": "nested_dm_misuse_audit.v1",
        "scan_scope": [SCAN_GLOB],
        "scanned_files": result.scanned_files,
        "affected_count": len(result.findings),
        "reviewed_safe_count": len(result.reviewed_safe),
        "role_counts": dict(sorted(roles.items())),
        "scan_errors": result.scan_errors,
        "findings": [asdict(finding) for finding in result.findings],
        "reviewed_safe": [asdict(finding) for finding in result.reviewed_safe],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="write the complete machine report")
    parser.add_argument("--affected-only", action="store_true")
    args = parser.parse_args()

    result = scan_population()
    payload = _payload(result)
    if args.json:
        args.json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"scanned_python_files={result.scanned_files}")
    print(f"affected_paths={len(result.findings)}")
    print(f"reviewed_safe_paths={len(result.reviewed_safe)}")
    print(f"scan_errors={len(result.scan_errors)}")
    for finding in result.findings:
        print(f"{finding.test_role:18s} {finding.file}")
    if not args.affected_only:
        for finding in result.reviewed_safe:
            print(f"{'reviewed_safe':18s} {finding.file}")
    if result.scan_errors:
        for error in result.scan_errors:
            print(f"SCAN_ERROR {error}")
        return 2

    # This is a reporter, and its exit code says so: a clean exit here means the
    # scan ran, NOT that the population is clean. Enforcement deliberately lives
    # elsewhere, and saying where is the difference between a report and a gate
    # somebody mistook for one.
    print(
        "\n[note] exit 0 = scan completed; it is NOT a pass. Enforcement owners:\n"
        "  repo-wide  scripts/tests/test_nested_dm_misuse_ratchet.py\n"
        "  per-path   scripts/experiment_gates.py run --path experiments/<kid>"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
