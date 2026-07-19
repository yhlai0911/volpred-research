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
import hashlib
import json
import math
import re
import statistics
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))
from experiment_claim_surface import is_experiment_claim_surface_file  # noqa: E402
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

# Coefficient-mask nesting. A restricted model is sometimes built without any
# base/augmented naming: the author zeroes a coefficient block and hands that
# indicator to an estimator. The channel deliberately requires both halves so
# ordinary zeroed arrays (sample weights, burn-in masks, padding) stay quiet.
COEF_MASK_NAME_RE = re.compile(
    r"active|mask|restrict|unrestrict|constrain|nest|"
    r"switch_?off|zero_?out|coef_?flags?|include_?flags?|"
    r"free_?(?:params?|coefs?|betas?)|fixed_?(?:params?|coefs?|betas?)",
    re.IGNORECASE,
)
MASK_FIT_CALL_RE = re.compile(
    r"fit|estimate|refit|train|calibrate|regress|ssvs|mle|glm|ols",
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

FIXED_MEMORY_ROLE = "primary_unconditional_gw_dm_fixed_memory"
FIXED_MEMORY_MANIFEST_NAME = "NESTED_DM_FIXED_MEMORY_MANIFEST_V1"
FIXED_MEMORY_MANIFEST_SCHEMA = "nested_dm_fixed_memory.v1"
FIXED_MEMORY_RUNTIME_SCHEMA = "nested_dm_fixed_memory_runtime.v1"
FIXED_MEMORY_ADJUDICATIONS = (
    Path("storage") / "ops" / "nested_dm_fixed_memory_adjudications.json"
)
SAFE_ROLES = {"diagnostic_with_cw_primary", FIXED_MEMORY_ROLE}


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
    role_validation_errors: list[str] = field(default_factory=list)


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


def _is_zero_like(node: ast.AST | None) -> bool:
    if isinstance(node, ast.Constant):
        value = node.value
        return isinstance(value, (int, float, bool)) and value == 0
    if isinstance(node, ast.Call):
        return bool(
            re.fullmatch(r"zeros(?:_like)?", _call_name(node), re.IGNORECASE)
        )
    return False


def _coef_mask_ast_evidence(tree: ast.AST, lines: list[str]) -> list[Evidence]:
    """Find a zeroed coefficient block that reaches an estimator restriction."""
    zeroed: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if not _is_zero_like(node.value):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if not isinstance(target, ast.Subscript):
                continue
            name = _root_name(target.value)
            if name is not None:
                zeroed.setdefault(name, node.lineno)
    if not zeroed:
        return []

    evidence: list[Evidence] = []

    def record(name: str, call_lineno: int) -> None:
        evidence.append(_line(lines, zeroed[name]))
        evidence.append(_line(lines, call_lineno))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not MASK_FIT_CALL_RE.search(
            _call_name(node)
        ):
            continue
        for keyword in node.keywords:
            name = _root_name(keyword.value)
            if name not in zeroed:
                continue
            if (keyword.arg and COEF_MASK_NAME_RE.search(keyword.arg)) or (
                COEF_MASK_NAME_RE.search(name)
            ):
                record(name, node.lineno)
        for argument in node.args:
            name = _root_name(argument)
            if name in zeroed and COEF_MASK_NAME_RE.search(name):
                record(name, node.lineno)
    return evidence


def _nested_ast_evidence(tree: ast.AST, lines: list[str]) -> list[Evidence]:
    evidence: list[Evidence] = _coef_mask_ast_evidence(tree, lines)
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
    paired_differences: set[str] = set()
    aug_re = re.compile(r"aug|alt|unrestricted|candidate|new_model", re.I)
    base_re = re.compile(r"base|restricted|benchmark|old_model", re.I)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not isinstance(value, ast.BinOp) or not isinstance(value.op, ast.Sub):
            continue
        left = ast.unparse(value.left)
        right = ast.unparse(value.right)
        if not (
            (aug_re.search(left) and base_re.search(right))
            or (base_re.search(left) and aug_re.search(right))
        ):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        paired_differences.update(
            target.id for target in targets if isinstance(target, ast.Name)
        )
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
        paired_hac_mean_test = bool(
            paired_differences
            and any(re.search(rf"\b{re.escape(variable)}\b", call_text) for variable in paired_differences)
            and re.search(r"hac|newey|cov_type|ols|mean|intercept|ttest", call_text, re.I)
        )
        if raw_name or generic_loss_test or paired_hac_mean_test:
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


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _logical_experiment_site(path: Path, root: Path) -> str:
    """Return the exact scan-root-relative site; never collapse repeated segments."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _canonical_experiment_site(site: str) -> bool:
    parts = Path(site).parts
    return (
        len(parts) >= 3
        and parts[0] == "experiments"
        and parts.count("experiments") == 1
        and parts[-1].endswith(".py")
    )


def _trusted_repo_root(scan_root: Path) -> Path | None:
    """Resolve the shared main checkout, never a candidate worktree registry."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=scan_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError as exc:
        warn(
            "audit_nested_dm_misuse",
            "trusted repository root cannot be resolved",
            scan_root=str(scan_root),
            err=str(exc),
        )
        return None
    if proc.returncode == 0:
        common_dir = Path(proc.stdout.strip()).resolve()
        if common_dir.name == ".git" and common_dir.parent.is_dir():
            return common_dir.parent
    return None


def _literal_assignment(tree: ast.AST, name: str) -> tuple[object | None, int | None, str | None]:
    matches: list[ast.AST] = []
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            matches.append(node)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            matches.append(node)
    if len(matches) != 1:
        return None, None, f"expected exactly one top-level {name} assignment"
    node = matches[0]
    try:
        return ast.literal_eval(node.value), node.lineno, None
    except (ValueError, TypeError) as exc:
        return None, node.lineno, f"{name} is not an AST-literal manifest: {exc}"


class _ModuleBindingVisitor(ast.NodeVisitor):
    """Find a binding executed in module scope without entering local scopes."""

    def __init__(self, name: str):
        self.name = name
        self.found = False

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store) and node.id == self.name:
            self.found = True

    @staticmethod
    def _zero_arg_call(node: ast.AST, name: str) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == name
            and not node.args
            and not node.keywords
        )

    def _static_string_value(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            values = [self._static_string_value(value) for value in node.values]
            return "".join(values) if all(value is not None for value in values) else None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self._static_string_value(node.left)
            right = self._static_string_value(node.right)
            return left + right if left is not None and right is not None else None
        return None

    def _globals_subscript_store(
        self, node: ast.AST, *, module_locals: bool = False
    ) -> bool:
        return (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Store)
            and self._current_module_mapping(
                node.value, module_locals=module_locals
            )
            and self._static_string_value(node.slice) == self.name
        )

    @staticmethod
    def _sys_modules_mapping(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "sys"
            and node.attr == "modules"
        )

    @classmethod
    def _current_module_object(cls, node: ast.AST) -> bool:
        direct_subscript = (
            isinstance(node, ast.Subscript)
            and cls._sys_modules_mapping(node.value)
            and isinstance(node.slice, ast.Name)
            and node.slice.id == "__name__"
        )
        mapping_method = (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and cls._sys_modules_mapping(node.func.value)
            and node.func.attr in {"get", "__getitem__", "setdefault"}
            and 1 <= len(node.args) <= 2
            and not node.keywords
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "__name__"
        )
        operator_getitem = (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "operator"
            and node.func.attr == "getitem"
            and len(node.args) == 2
            and not node.keywords
            and cls._sys_modules_mapping(node.args[0])
            and isinstance(node.args[1], ast.Name)
            and node.args[1].id == "__name__"
        )
        return direct_subscript or mapping_method or operator_getitem

    def _current_module_mapping(
        self, node: ast.AST, *, module_locals: bool = False
    ) -> bool:
        return (
            self._zero_arg_call(node, "globals")
            or (
                module_locals
                and (
                    self._zero_arg_call(node, "locals")
                    or self._zero_arg_call(node, "vars")
                )
            )
            or (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "vars"
                and len(node.args) == 1
                and not node.keywords
                and self._current_module_object(node.args[0])
            )
            or (
                isinstance(node, ast.Attribute)
                and node.attr == "__dict__"
                and self._current_module_object(node.value)
            )
        )

    def _namespace_mutation_binding(
        self, node: ast.AST, *, module_locals: bool = False
    ) -> bool:
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.ctx, ast.Store)
            and node.attr == self.name
            and self._current_module_object(node.value)
        ):
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "setattr"
            and len(node.args) >= 3
            and self._current_module_object(node.args[0])
            and self._static_string_value(node.args[1]) == self.name
        ):
            return True
        if not isinstance(node, ast.Call):
            return False

        method: str | None = None
        args = node.args
        if (
            isinstance(node.func, ast.Attribute)
            and self._current_module_mapping(
                node.func.value, module_locals=module_locals
            )
        ):
            method = node.func.attr
        elif (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "dict"
            and node.args
            and self._current_module_mapping(
                node.args[0], module_locals=module_locals
            )
        ):
            # Unbound built-in descriptor calls mutate their first argument:
            # dict.update(globals(), NAME=value), dict.__setitem__(...), etc.
            method = node.func.attr
            args = node.args[1:]
        elif (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "operator"
            and node.func.attr in {"setitem", "ior"}
            and node.args
            and self._current_module_mapping(
                node.args[0], module_locals=module_locals
            )
        ):
            # operator.setitem/ior are the public function forms of the same
            # mutations. Keep them in the same matcher so aliases cannot make
            # the protocol declaration fail open accidentally.
            method = "__setitem__" if node.func.attr == "setitem" else "__ior__"
            args = node.args[1:]
        if method is None:
            return False

        if method in {"__setitem__", "setdefault"}:
            return bool(
                args
                and self._static_string_value(args[0]) == self.name
            )
        if method in {"update", "__ior__", "__init__"}:
            if any(keyword.arg == self.name for keyword in node.keywords):
                return True
            if any(
                keyword.arg is None
                and self._tree_mentions_static_key(keyword.value)
                for keyword in node.keywords
            ):
                return True
            return any(self._tree_mentions_static_key(argument) for argument in args)
        return False

    def _tree_mentions_static_key(self, node: ast.AST) -> bool:
        """Recognize literal mapping keys, including ``dict(NAME=value)``."""
        return any(
            (
                self._static_string_value(child) == self.name
            )
            or (
                isinstance(child, ast.keyword)
                and child.arg == self.name
            )
            for child in ast.walk(node)
        )

    def _static_exec_binding(self, node: ast.AST, *, require_globals: bool) -> bool:
        if not isinstance(node, ast.Call):
            return False
        builtin_exec = (
            isinstance(node.func, ast.Name)
            and node.func.id in {"exec", "eval"}
        ) or (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in {"builtins", "__builtins__"}
            and node.func.attr in {"exec", "eval"}
        )
        if not builtin_exec or not node.args:
            return False
        payload = self._static_string_value(node.args[0])
        if payload is None:
            return False
        direct_assignment = bool(
            re.search(
                rf"\b{re.escape(self.name)}\b\s*(?::=|=)", payload
            )
        )
        explicit_namespace = any(
            self._current_module_mapping(argument, module_locals=False)
            for argument in node.args[1:]
        )
        payload_global = False
        try:
            payload_tree = ast.parse(payload)
        except SyntaxError:
            payload_tree = None
        if payload_tree is not None:
            payload_global = any(
                (
                    isinstance(child, ast.Global)
                    and self.name in child.names
                )
                or self._globals_subscript_store(
                    child, module_locals=not require_globals or explicit_namespace
                )
                or self._namespace_mutation_binding(
                    child, module_locals=not require_globals or explicit_namespace
                )
                for child in ast.walk(payload_tree)
            )
        if payload_global:
            return True
        return direct_assignment and (not require_globals or explicit_namespace)

    def _scan_skipped_scope_for_global_bindings(self, node: ast.AST) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Global) and self.name in child.names:
                self.found = True
            elif self._globals_subscript_store(child):
                self.found = True
            elif self._namespace_mutation_binding(child):
                self.found = True
            elif self._static_exec_binding(child, require_globals=True):
                self.found = True

    def _visit_definition_expressions(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        if node.name == self.name:
            self.found = True
        for expression in node.decorator_list:
            self.visit(expression)
        for expression in (*node.args.defaults, *node.args.kw_defaults):
            if expression is not None:
                self.visit(expression)
        annotations = [
            *(arg.annotation for arg in node.args.posonlyargs),
            *(arg.annotation for arg in node.args.args),
            *(arg.annotation for arg in node.args.kwonlyargs),
            node.args.vararg.annotation if node.args.vararg else None,
            node.args.kwarg.annotation if node.args.kwarg else None,
            node.returns,
        ]
        for annotation in annotations:
            if annotation is not None:
                self.visit(annotation)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_definition_expressions(node)
        self._scan_skipped_scope_for_global_bindings(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_definition_expressions(node)
        self._scan_skipped_scope_for_global_bindings(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name == self.name:
            self.found = True
        for expression in (*node.decorator_list, *node.bases):
            self.visit(expression)
        for keyword in node.keywords:
            self.visit(keyword.value)
        self._scan_skipped_scope_for_global_bindings(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        # Defaults execute in the surrounding scope when the lambda is created;
        # its body and parameter bindings remain local.
        for expression in (*node.args.defaults, *node.args.kw_defaults):
            if expression is not None:
                self.visit(expression)
        self._scan_skipped_scope_for_global_bindings(node.body)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        # Straightforward dynamic module binding: globals()["NAME"] = value.
        if self._globals_subscript_store(node, module_locals=True):
            self.found = True
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if self._namespace_mutation_binding(node, module_locals=True):
            self.found = True
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # A static protocol assignment hidden in exec/eval otherwise bypasses
        # every normal AST assignment channel. Dynamically constructed strings
        # remain outside what a non-executing auditor can prove.
        if self._static_exec_binding(node, require_globals=False):
            self.found = True
        if self._namespace_mutation_binding(node, module_locals=True):
            self.found = True
        self.generic_visit(node)

    def _visit_comprehension(self, node: ast.AST) -> None:
        # Generator targets are local to the comprehension. Its expressions are
        # evaluated in the surrounding scope, where a named expression can bind.
        for generator in node.generators:
            self.visit(generator.iter)
            for condition in generator.ifs:
                self.visit(condition)
        for attribute in ("elt", "key", "value"):
            expression = getattr(node, attribute, None)
            if expression is not None:
                self.visit(expression)

    visit_ListComp = _visit_comprehension
    visit_SetComp = _visit_comprehension
    visit_DictComp = _visit_comprehension
    visit_GeneratorExp = _visit_comprehension

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name == self.name:
            self.found = True
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name == self.name:
            self.found = True
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name == self.name:
            self.found = True

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest == self.name:
            self.found = True
        self.generic_visit(node)


def _has_module_scope_binding(tree: ast.AST, name: str) -> bool:
    """Imports/references are harmless; any module-scope binding is a declaration."""
    visitor = _ModuleBindingVisitor(name)
    visitor.visit(tree)
    return visitor.found


def _function(tree: ast.AST, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    matches = [
        node
        for node in getattr(tree, "body", [])
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    return matches[0] if len(matches) == 1 else None


def _root_name(node: ast.AST | None) -> str | None:
    while isinstance(node, (ast.Subscript, ast.Attribute)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _contains_name(node: ast.AST | None, name: str) -> bool:
    return node is not None and any(
        isinstance(child, ast.Name) and child.id == name for child in ast.walk(node)
    )


def _safe_manifest_id_projection(node: ast.AST | None) -> bool:
    """Allow only ``[row['id'] for row in MANIFEST[...]]`` as a non-aliasing read."""
    if not isinstance(node, ast.ListComp) or len(node.generators) != 1:
        return False
    generator = node.generators[0]
    if generator.ifs or generator.is_async or not isinstance(generator.target, ast.Name):
        return False
    if _root_name(generator.iter) != FIXED_MEMORY_MANIFEST_NAME:
        return False
    elt = node.elt
    return (
        isinstance(elt, ast.Subscript)
        and isinstance(elt.value, ast.Name)
        and elt.value.id == generator.target.id
        and isinstance(elt.slice, ast.Constant)
        and elt.slice.value == "id"
    )


def _unwrap_bool_call(node: ast.AST) -> ast.AST | None:
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "bool"
        and len(node.args) == 1
        and not node.keywords
    ):
        return node.args[0]
    return None


def _canonical_hash_helper_is_pure(tree: ast.AST, name: str) -> bool:
    helper = _function(tree, name)
    if (
        helper is None
        or len(helper.args.args) != 1
        or helper.args.defaults
        or helper.args.kw_defaults
        or helper.decorator_list
        or len(helper.body) != 2
        or not isinstance(helper.body[0], ast.Assign)
        or not isinstance(helper.body[1], ast.Return)
    ):
        return False
    argument = helper.args.args[0].arg
    assignment = helper.body[0]
    if len(assignment.targets) != 1 or not isinstance(assignment.targets[0], ast.Name):
        return False
    payload_name = assignment.targets[0].id
    encode = assignment.value
    if not (
        isinstance(encode, ast.Call)
        and isinstance(encode.func, ast.Attribute)
        and encode.func.attr == "encode"
        and len(encode.args) == 1
        and isinstance(encode.args[0], ast.Constant)
        and encode.args[0].value == "utf-8"
        and not encode.keywords
    ):
        return False
    dump = encode.func.value
    if not (
        isinstance(dump, ast.Call)
        and isinstance(dump.func, ast.Attribute)
        and isinstance(dump.func.value, ast.Name)
        and dump.func.value.id == "json"
        and dump.func.attr == "dumps"
        and len(dump.args) == 1
        and isinstance(dump.args[0], ast.Name)
        and dump.args[0].id == argument
    ):
        return False
    keywords = {keyword.arg: keyword.value for keyword in dump.keywords}
    separators = keywords.get("separators")
    if not (
        set(keywords) == {"sort_keys", "ensure_ascii", "separators"}
        and isinstance(keywords["sort_keys"], ast.Constant)
        and keywords["sort_keys"].value is True
        and isinstance(keywords["ensure_ascii"], ast.Constant)
        and keywords["ensure_ascii"].value is False
        and isinstance(separators, ast.Tuple)
        and len(separators.elts) == 2
        and all(isinstance(item, ast.Constant) for item in separators.elts)
        and tuple(item.value for item in separators.elts) == (",", ":")
    ):
        return False
    returned = helper.body[1].value
    return bool(
        isinstance(returned, ast.Call)
        and isinstance(returned.func, ast.Attribute)
        and returned.func.attr == "hexdigest"
        and not returned.args
        and not returned.keywords
        and isinstance(returned.func.value, ast.Call)
        and isinstance(returned.func.value.func, ast.Attribute)
        and isinstance(returned.func.value.func.value, ast.Name)
        and returned.func.value.func.value.id == "hashlib"
        and returned.func.value.func.attr == "sha256"
        and len(returned.func.value.args) == 1
        and isinstance(returned.func.value.args[0], ast.Name)
        and returned.func.value.args[0].id == payload_name
        and not returned.func.value.keywords
    )


def _safe_manifest_hash_call(node: ast.AST | None, helper: str, pure: bool) -> bool:
    return bool(
        pure
        and isinstance(node, ast.Call)
        and _call_name(node) == helper
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == FIXED_MEMORY_MANIFEST_NAME
        and not node.keywords
    )


def _fixed_memory_manifest_errors(manifest: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["fixed-memory manifest is not an object"]
    expected_top = {
        "schema",
        "role",
        "claim_scope",
        "conditional_predictive_ability_tested",
        "regime_offsetting_effects_excluded",
        "implementation",
        "method_contract",
        "decision_contract",
        "feature_stages",
        "expected_primary_cell_count",
        "primary_cells",
    }
    if set(manifest) != expected_top:
        errors.append("manifest top-level keys do not match the v1 schema")
    if manifest.get("schema") != FIXED_MEMORY_MANIFEST_SCHEMA:
        errors.append(f"manifest schema must be {FIXED_MEMORY_MANIFEST_SCHEMA}")
    if manifest.get("role") != FIXED_MEMORY_ROLE:
        errors.append(f"manifest role must be {FIXED_MEMORY_ROLE}")
    if manifest.get("claim_scope") != "unconditional_average_loss_only":
        errors.append("claim_scope is not unconditional_average_loss_only")
    if manifest.get("conditional_predictive_ability_tested") is not False:
        errors.append("manifest must state conditional predictive ability is not tested")
    if manifest.get("regime_offsetting_effects_excluded") is not False:
        errors.append("manifest must state regime-offsetting effects are not excluded")

    implementation = manifest.get("implementation")
    if not isinstance(implementation, dict):
        errors.append("implementation contract is missing")
        implementation = {}
    expected_implementation = {
        "paired_forecast_function",
        "statistic_function",
        "gate_registry_inference",
        "train_window_constant",
        "model_spec_registry",
        "base_model_parameter",
        "augmented_model_parameter",
        "paired_result_variable",
        "gate_function",
        "registry_record_constructor",
        "gate_eligibility_variable",
        "whole_method_eligibility_variable",
        "bounded_memory_parameter",
        "paired_audit_attribute",
        "paired_eligibility_key",
        "base_design_variable",
        "augmented_design_variable",
        "fit_function",
        "runtime_evidence_file",
        "runtime_evidence_key",
        "runtime_cell_inventory",
        "runtime_gate_inventory",
        "runtime_registry_inventory",
        "runtime_claim_record",
        "runtime_statistic_record",
        "runtime_multiple_testing_record",
        "claim_surface_files",
    }
    if set(implementation) != expected_implementation:
        errors.append("implementation keys do not match the v1 schema")
    for key in (
        "paired_forecast_function",
        "statistic_function",
        "gate_registry_inference",
        "train_window_constant",
        "model_spec_registry",
        "base_model_parameter",
        "augmented_model_parameter",
        "paired_result_variable",
        "gate_function",
        "registry_record_constructor",
        "gate_eligibility_variable",
        "whole_method_eligibility_variable",
        "bounded_memory_parameter",
        "paired_audit_attribute",
        "paired_eligibility_key",
        "base_design_variable",
        "augmented_design_variable",
        "fit_function",
        "runtime_evidence_file",
        "runtime_evidence_key",
        "runtime_cell_inventory",
        "runtime_gate_inventory",
        "runtime_registry_inventory",
        "runtime_claim_record",
        "runtime_statistic_record",
        "runtime_multiple_testing_record",
    ):
        if not isinstance(implementation.get(key), str) or not implementation[key].strip():
            errors.append(f"implementation.{key} is missing")
    identifier_keys = {
        "paired_forecast_function",
        "statistic_function",
        "train_window_constant",
        "model_spec_registry",
        "base_model_parameter",
        "augmented_model_parameter",
        "paired_result_variable",
        "gate_function",
        "registry_record_constructor",
        "gate_eligibility_variable",
        "whole_method_eligibility_variable",
        "bounded_memory_parameter",
        "paired_audit_attribute",
        "paired_eligibility_key",
        "base_design_variable",
        "augmented_design_variable",
        "fit_function",
    }
    for key in identifier_keys:
        value = implementation.get(key)
        if isinstance(value, str) and not value.isidentifier():
            errors.append(f"implementation.{key} must be a Python identifier")
    if implementation.get("base_model_parameter") == implementation.get(
        "augmented_model_parameter"
    ):
        errors.append("implementation model parameters must be distinct")
    claim_files = implementation.get("claim_surface_files")
    if (
        not isinstance(claim_files, list)
        or not claim_files
        or any(not isinstance(name, str) or Path(name).name != name for name in claim_files)
        or len(claim_files) != len(set(claim_files))
    ):
        errors.append("implementation.claim_surface_files must be non-empty basenames")

    method = manifest.get("method_contract")
    if not isinstance(method, dict):
        errors.append("method_contract is missing")
        method = {}
    expected_method = {
        "estimation_scheme",
        "train_window",
        "window_data_dependent",
        "shared_complete_case_mask",
        "shared_training_dates",
        "forward_label_embargo",
        "loss",
        "runtime_estimand",
        "loss_differential",
        "hac_kernel",
        "hac_bandwidth_rule",
        "reference_distribution",
        "estimand",
    }
    if set(method) != expected_method:
        errors.append("method_contract keys do not match the v1 schema")
    exact = {
        "estimation_scheme": "fixed_rolling",
        "window_data_dependent": False,
        "shared_complete_case_mask": True,
        "shared_training_dates": True,
        "forward_label_embargo": True,
        "loss_differential": "loss_aug_minus_loss_base",
        "hac_kernel": "Bartlett",
        "reference_distribution": "standard_normal",
    }
    for key, expected in exact.items():
        if method.get(key) != expected:
            errors.append(f"method_contract.{key} must equal {expected!r}")
    if (
        type(method.get("train_window")) is not int
        or method.get("train_window", 0) <= 0
        or method.get("train_window", 0) > 1_000_000_000
    ):
        errors.append("method_contract.train_window must be a positive fixed integer")
    if not isinstance(method.get("loss"), str) or not method["loss"].strip():
        errors.append("method_contract.loss is missing")
    if (
        not isinstance(method.get("runtime_estimand"), str)
        or not method["runtime_estimand"].strip()
    ):
        errors.append("method_contract.runtime_estimand is missing")
    if not isinstance(method.get("hac_bandwidth_rule"), str) or not method[
        "hac_bandwidth_rule"
    ].strip():
        errors.append("method_contract.hac_bandwidth_rule is missing")
    elif method["hac_bandwidth_rule"] != "max(h-1, canonical_bandwidth(h,n))":
        errors.append("method_contract.hac_bandwidth_rule is not a supported canonical rule")
    estimand = str(method.get("estimand", "")).lower()
    if "unconditional" not in estimand or "average" not in estimand:
        errors.append("method_contract.estimand must say unconditional average loss")

    decision = manifest.get("decision_contract")
    expected_decision = {
        "gate_direction",
        "raw_p_field",
        "multiplicity",
        "family_alpha",
        "critical_value",
        "gate_flag_field",
        "holm_adjusted_p_field",
        "registry_stat_field",
        "registry_stat_decimals",
        "registry_raw_p_field",
        "gate_count_field",
        "claim_family_count_field",
        "claim_pass_count_field",
    }
    if not isinstance(decision, dict) or set(decision) != expected_decision:
        errors.append("decision_contract keys do not match the v1 schema")
        decision = {}
    if decision.get("gate_direction") != "lower":
        errors.append("decision_contract.gate_direction must be lower")
    if decision.get("raw_p_field") != "p_value_one_sided_flow_better":
        errors.append("decision_contract.raw_p_field is unsupported")
    if decision.get("multiplicity") != "Holm":
        errors.append("decision_contract.multiplicity must be Holm")
    if type(decision.get("family_alpha")) is not float or not 0 < decision.get(
        "family_alpha", 0
    ) <= 0.05:
        errors.append("decision_contract.family_alpha must be a float in (0,0.05]")
    if type(decision.get("critical_value")) not in (int, float) or not _finite_number(
        decision.get("critical_value")
    ):
        errors.append("decision_contract.critical_value must be finite")
    elif type(decision.get("family_alpha")) is float and 0 < decision["family_alpha"] <= 0.05:
        expected_critical = statistics.NormalDist().inv_cdf(decision["family_alpha"])
        if not math.isclose(
            float(decision["critical_value"]), expected_critical, abs_tol=0.001
        ):
            errors.append("decision_contract.critical_value disagrees with family_alpha")
    if decision.get("gate_flag_field") != "passes_flow_gate":
        errors.append("decision_contract.gate_flag_field is unsupported")
    if decision.get("holm_adjusted_p_field") != "holm_adjusted_p":
        errors.append("decision_contract.holm_adjusted_p_field is unsupported")
    if decision.get("registry_stat_field") != "stat":
        errors.append("decision_contract.registry_stat_field is unsupported")
    if (
        type(decision.get("registry_stat_decimals")) is not int
        or not 3 <= decision.get("registry_stat_decimals", -1) <= 12
    ):
        errors.append("decision_contract.registry_stat_decimals is invalid")
    if decision.get("registry_raw_p_field") != "p_one_sided_raw":
        errors.append("decision_contract.registry_raw_p_field is unsupported")
    for key in ("gate_count_field", "claim_family_count_field", "claim_pass_count_field"):
        value = decision.get(key)
        if not isinstance(value, str) or not value or not value.isidentifier():
            errors.append(f"decision_contract.{key} must be a field identifier")

    stages = manifest.get("feature_stages")
    if not isinstance(stages, list) or not stages:
        errors.append("feature_stages must be a non-empty list")
        stages = []
    stage_by_id: dict[str, dict] = {}
    output_owner: dict[str, str] = {}
    final_stage_ids: set[str] = set()
    bounded_stage_roles = {"observed", "finite_lag", "fixed_rolling"}
    for index, stage in enumerate(stages):
        prefix = f"feature_stages[{index}]"
        if not isinstance(stage, dict):
            errors.append(f"{prefix} is not an object")
            continue
        if set(stage) != {"id", "role", "outputs", "memory", "max_observations"}:
            errors.append(f"{prefix} keys do not match the v1 schema")
        stage_id = stage.get("id")
        if not isinstance(stage_id, str) or not stage_id:
            errors.append(f"{prefix}.id is missing")
            continue
        if stage_id in stage_by_id:
            errors.append(f"duplicate feature stage id: {stage_id}")
        stage_by_id[stage_id] = stage
        if stage.get("role") == "paired_final_estimator":
            final_stage_ids.add(stage_id)
            if stage.get("memory") != "fixed_rolling":
                errors.append(f"{prefix} final-estimator memory must be fixed_rolling")
            if stage.get("max_observations") != method.get("train_window"):
                errors.append(
                    f"{prefix} final-estimator memory must equal method_contract.train_window"
                )
        elif stage.get("role") != "predictor_feature":
            errors.append(f"{prefix}.role is not recognised")
        outputs = stage.get("outputs")
        if (
            not isinstance(outputs, list)
            or not outputs
            or any(not isinstance(value, str) or not value for value in outputs)
            or len(outputs) != len(set(outputs))
        ):
            errors.append(f"{prefix}.outputs must be unique non-empty strings")
            outputs = []
        for output in outputs:
            if output in output_owner:
                errors.append(f"feature output has multiple owners: {output}")
            output_owner[output] = stage_id
        if (
            not isinstance(stage.get("memory"), str)
            or stage.get("memory") not in bounded_stage_roles
        ):
            errors.append(f"{prefix}.memory is not bounded")
        if (
            type(stage.get("max_observations")) is not int
            or stage.get("max_observations", 0) <= 0
        ):
            errors.append(f"{prefix}.max_observations must be positive")
    if len(final_stage_ids) != 1:
        errors.append("feature_stages must declare exactly one paired_final_estimator")

    cells = manifest.get("primary_cells")
    if not isinstance(cells, list) or not cells:
        return [*errors, "primary_cells must be a non-empty list"]
    if (
        type(manifest.get("expected_primary_cell_count")) is not int
        or manifest.get("expected_primary_cell_count") != len(cells)
    ):
        errors.append("expected_primary_cell_count does not equal the manifest cell count")
    ids: list[str] = []
    cell_keys = {
        "id",
        "id_components",
        "family",
        "base",
        "augmented",
        "strictly_nested",
        "horizon",
        "feeds_gate",
        "base_predictors",
        "augmented_predictors",
        "used_stage_ids",
    }
    for index, cell in enumerate(cells):
        prefix = f"primary_cells[{index}]"
        if not isinstance(cell, dict):
            errors.append(f"{prefix} is not an object")
            continue
        if set(cell) != cell_keys:
            errors.append(f"{prefix} keys do not match the v1 schema")
        cell_id = cell.get("id")
        if not isinstance(cell_id, str) or not cell_id.strip():
            errors.append(f"{prefix}.id is missing")
        else:
            ids.append(cell_id)
        for key in ("family", "base", "augmented"):
            if not isinstance(cell.get(key), str) or not cell[key].strip():
                errors.append(f"{prefix}.{key} is missing")
        components = cell.get("id_components")
        if (
            not isinstance(components, list)
            or len(components) < 3
            or any(not isinstance(value, str) or not value for value in components)
        ):
            errors.append(f"{prefix}.id_components must be at least three strings")
            components = []
        expected_id = "|".join(components)
        if cell_id != expected_id:
            errors.append(f"{prefix}.id is not derivable from its declared fields")
        if components and (
            components[0] != cell.get("family")
            or cell.get("augmented") not in components
        ):
            errors.append(f"{prefix}.id_components omit family or augmented model")
        if cell.get("family") != "primary":
            errors.append(f"{prefix}.family must be primary")
        if cell.get("base") == cell.get("augmented"):
            errors.append(f"{prefix} does not name a proper nested augmentation")
        if cell.get("strictly_nested") is not True:
            errors.append(f"{prefix}.strictly_nested must be true")
        if cell.get("feeds_gate") is not True:
            errors.append(f"{prefix}.feeds_gate must be true")
        for key in ("horizon",):
            if (
                type(cell.get(key)) is not int
                or cell.get(key, 0) <= 0
                or cell.get(key, 0) > 1_000_000
            ):
                errors.append(f"{prefix}.{key} must be a positive integer")
        base_predictors = cell.get("base_predictors")
        aug_predictors = cell.get("augmented_predictors")
        for key, predictors in (
            ("base_predictors", base_predictors),
            ("augmented_predictors", aug_predictors),
        ):
            if (
                not isinstance(predictors, list)
                or not predictors
                or any(not isinstance(value, str) or not value for value in predictors)
                or len(predictors) != len(set(predictors))
            ):
                errors.append(f"{prefix}.{key} must contain unique predictor names")
        if (
            isinstance(base_predictors, list)
            and isinstance(aug_predictors, list)
            and all(isinstance(value, str) for value in [*base_predictors, *aug_predictors])
        ):
            if not set(base_predictors) < set(aug_predictors):
                errors.append(f"{prefix} predictor lists are not a proper subset")
        used = cell.get("used_stage_ids")
        if (
            not isinstance(used, list)
            or not used
            or any(not isinstance(value, str) or not value for value in used)
            or len(used) != len(set(used))
        ):
            errors.append(f"{prefix}.used_stage_ids must be unique and non-empty")
            used = []
        unknown = set(used) - set(stage_by_id)
        if unknown:
            errors.append(f"{prefix} uses unknown feature stages: {sorted(unknown)}")
        if not final_stage_ids <= set(used):
            errors.append(f"{prefix} omits the paired final-estimation stage")
        if isinstance(aug_predictors, list) and all(
            isinstance(predictor, str) for predictor in aug_predictors
        ):
            uncovered = [
                predictor
                for predictor in aug_predictors
                if output_owner.get(predictor) not in set(used)
                or stage_by_id.get(output_owner.get(predictor), {}).get("role")
                != "predictor_feature"
            ]
            if uncovered:
                errors.append(
                    f"{prefix} has predictors without a used predictor-feature stage: "
                    f"{uncovered}"
                )
    if len(ids) != len(set(ids)):
        errors.append("primary cell ids are not unique")
    try:
        manifest_text = json.dumps(manifest, sort_keys=True)
    except (TypeError, ValueError) as exc:
        errors.append(f"fixed-memory manifest is not canonical JSON: {exc}")
    else:
        if "expanding" in manifest_text.lower():
            errors.append("primary fixed-memory manifest contains an expanding stage")
    return errors


def _resolve_runtime_path(value: object, dotted: object) -> object | None:
    if not isinstance(dotted, str) or not dotted:
        return None
    current = value
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _finite_number(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError) as exc:
        warn(
            "audit_nested_dm_misuse",
            "runtime numeric evidence cannot be checked for finiteness",
            value_type=type(value).__name__,
            err=str(exc),
        )
        return False


def _numbers_close(left: object, right: object, *, abs_tol: float = 1e-12) -> bool:
    return (
        _finite_number(left)
        and _finite_number(right)
        and math.isclose(float(left), float(right), rel_tol=1e-10, abs_tol=abs_tol)
    )


def _fixed_memory_runtime_errors(path: Path, manifest: dict) -> list[str]:
    errors: list[str] = []
    implementation = manifest["implementation"]
    method = manifest["method_contract"]
    decision = manifest["decision_contract"]
    runtime_name = implementation["runtime_evidence_file"]
    if Path(runtime_name).name != runtime_name:
        return ["runtime evidence file must be a sibling basename"]
    runtime_path = path.parent / runtime_name
    try:
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        return [f"runtime evidence unavailable: {exc}"]
    if not isinstance(runtime, dict):
        return ["runtime evidence is not a JSON object"]

    envelope = runtime.get(implementation["runtime_evidence_key"])
    envelope_keys = {
        "schema",
        "manifest_sha256",
        "cell_inventory",
        "gate_inventory",
        "registry_inventory",
        "statistic_record",
        "claim_record",
        "claim_scope",
        "cells",
    }
    if not isinstance(envelope, dict):
        return ["versioned fixed-memory runtime evidence envelope is missing"]
    if set(envelope) != envelope_keys:
        errors.append("runtime evidence envelope keys do not match the v1 schema")
    if envelope.get("schema") != FIXED_MEMORY_RUNTIME_SCHEMA:
        errors.append(f"runtime evidence schema must be {FIXED_MEMORY_RUNTIME_SCHEMA}")
    if envelope.get("manifest_sha256") != _canonical_sha256(manifest):
        errors.append("runtime evidence manifest hash is stale")
    if envelope.get("claim_scope") != manifest.get("claim_scope"):
        errors.append("runtime evidence claim scope disagrees with the manifest")
    envelope_bindings = {
        "cell_inventory": "runtime_cell_inventory",
        "gate_inventory": "runtime_gate_inventory",
        "registry_inventory": "runtime_registry_inventory",
        "claim_record": "runtime_claim_record",
        "statistic_record": "runtime_statistic_record",
    }
    for envelope_key, implementation_key in envelope_bindings.items():
        if envelope.get(envelope_key) != implementation.get(implementation_key):
            errors.append(
                f"runtime evidence {envelope_key} is not the manifest-pinned path"
            )

    cells = _resolve_runtime_path(runtime, envelope.get("cell_inventory"))
    gate_rows = _resolve_runtime_path(runtime, envelope.get("gate_inventory"))
    registry_rows = _resolve_runtime_path(runtime, envelope.get("registry_inventory"))
    claims = _resolve_runtime_path(runtime, envelope.get("claim_record"))
    evidence_cells = envelope.get("cells")
    for label, value in (
        ("cell inventory", cells),
        ("primary gate inventory", gate_rows),
        ("registry inventory", registry_rows),
        ("runtime evidence cells", evidence_cells),
    ):
        if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
            errors.append(f"{label} is missing or malformed")

    def indexed(rows: object, key: str, label: str) -> dict[str, dict]:
        if not isinstance(rows, list):
            return {}
        out: dict[str, dict] = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get(key), str):
                errors.append(f"{label} has a non-string id")
                continue
            if row[key] in out:
                errors.append(f"{label} has a duplicate id: {row[key]}")
            out[row[key]] = row
        return out

    by_id = indexed(cells, "cell", "runtime cell inventory")
    gates = indexed(gate_rows, "cell", "runtime gate inventory")
    registry = indexed(registry_rows, "cell", "runtime registry inventory")
    runtime_evidence = indexed(evidence_cells, "id", "runtime evidence envelope")
    manifest_cells = {cell["id"]: cell for cell in manifest["primary_cells"]}
    expected_ids = set(manifest_cells)

    allowed_true_gate_prefixes = {
        tuple(implementation["runtime_gate_inventory"].split(".")),
        tuple(implementation["runtime_registry_inventory"].split(".")),
    }

    stack: list[tuple[object, tuple[str, ...]]] = [(runtime, ())]
    visited_nodes = 0
    while stack:
        value, path_parts = stack.pop()
        visited_nodes += 1
        if visited_nodes > 1_000_000:
            errors.append("runtime evidence exceeds the audit node limit")
            break
        if isinstance(value, dict):
            if "feeds_gate" in value and type(value["feeds_gate"]) is not bool:
                errors.append("runtime contains a non-boolean feeds_gate field")
            if value.get("feeds_gate") is True and not any(
                len(path_parts) == len(prefix) + 1
                and path_parts[: len(prefix)] == prefix
                and path_parts[-1].isdigit()
                for prefix in allowed_true_gate_prefixes
            ):
                errors.append(
                    "runtime contains a gate-bearing row outside the manifest-pinned inventories"
                )
            stack.extend(
                (child, (*path_parts, str(key))) for key, child in value.items()
            )
        elif isinstance(value, list):
            stack.extend(
                (child, (*path_parts, str(index)))
                for index, child in enumerate(value)
            )
    for label, inventory in (
        ("runtime primary cell", by_id),
        ("runtime claim-bearing gate", gates),
        ("runtime evidence", runtime_evidence),
    ):
        if set(inventory) != expected_ids:
            errors.append(f"{label} set does not exactly match the manifest")

    train_window = method["train_window"]
    inference = implementation["gate_registry_inference"]
    statistic_key = envelope.get("statistic_record")
    digest_keys = {
        "id",
        "common_complete_case_mask_sha256",
        "base_training_schedule_sha256",
        "aug_training_schedule_sha256",
        "origin_schedule_sha256",
        "eligibility",
        "base_predictors",
        "augmented_predictors",
    }
    metadata_map = {
        "family": "family",
        "horizon": "horizon",
        "base": "base",
        "augmented": "alt",
    }
    raw_p_by_id: dict[str, float] = {}
    z_by_id: dict[str, float] = {}
    for cell_id in sorted(expected_ids):
        declared = manifest_cells[cell_id]
        cell = by_id.get(cell_id)
        gate = gates.get(cell_id)
        evidence = runtime_evidence.get(cell_id)
        if not isinstance(cell, dict) or not isinstance(gate, dict) or not isinstance(evidence, dict):
            continue
        for manifest_key, runtime_key in metadata_map.items():
            if cell.get(runtime_key) != declared.get(manifest_key):
                errors.append(
                    f"{cell_id}: runtime {runtime_key} disagrees with manifest {manifest_key}"
                )
        if cell.get("bounded_memory") is not True:
            errors.append(f"{cell_id}: runtime cell is not fixed-memory eligible")
        audit = cell.get("oos_audit")
        if not isinstance(audit, dict):
            errors.append(f"{cell_id}: runtime OOS audit is missing")
            continue
        required_audit = {
            "scheme": "fixed_rolling",
            "train_window": train_window,
            "fixed_window_held": True,
            "same_training_dates_for_both_models": True,
            "embargo_ok": True,
        }
        for key, expected in required_audit.items():
            if audit.get(key) != expected:
                errors.append(f"{cell_id}: oos_audit.{key} != {expected!r}")
        n_origins = audit.get("n_origins")
        if type(n_origins) is not int or n_origins <= 0:
            errors.append(f"{cell_id}: oos_audit.n_origins is not positive")
        if (
            type(audit.get("min_origin_minus_last_train_label_end_days")) is not int
            or audit.get("min_origin_minus_last_train_label_end_days", 0) < 1
        ):
            errors.append(f"{cell_id}: forward-label embargo provenance is insufficient")
        if set(evidence) != digest_keys:
            errors.append(f"{cell_id}: runtime evidence cell keys are malformed")
        if evidence.get("eligibility") != "whole_method_fixed_memory_verified":
            errors.append(f"{cell_id}: runtime eligibility is not verified")
        if evidence.get("base_predictors") != declared["base_predictors"]:
            errors.append(f"{cell_id}: runtime base predictors disagree with manifest")
        if evidence.get("augmented_predictors") != declared["augmented_predictors"]:
            errors.append(f"{cell_id}: runtime augmented predictors disagree with manifest")
        for key in digest_keys - {
            "id",
            "eligibility",
            "base_predictors",
            "augmented_predictors",
        }:
            digest = evidence.get(key)
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                errors.append(f"{cell_id}: {key} is not a SHA-256 digest")
            if audit.get(key) != digest:
                errors.append(f"{cell_id}: {key} disagrees with the OOS audit")
        if evidence.get("base_training_schedule_sha256") != evidence.get(
            "aug_training_schedule_sha256"
        ):
            errors.append(f"{cell_id}: base/aug training schedules differ")

        statistic = cell.get(statistic_key) if isinstance(statistic_key, str) else None
        if not isinstance(statistic, dict):
            errors.append(f"{cell_id}: runtime GW/DM statistic provenance is missing")
        else:
            if "unconditional" not in str(statistic.get("test", "")).lower():
                errors.append(f"{cell_id}: statistic is not explicitly unconditional")
            if statistic.get("loss") != method["loss"]:
                errors.append(f"{cell_id}: statistic loss disagrees with the manifest")
            if statistic.get("estimand") != method["runtime_estimand"]:
                errors.append(f"{cell_id}: statistic estimand disagrees with the manifest")
            for key in ("hac_kernel", "hac_bandwidth_rule", "reference_distribution"):
                if statistic.get(key) != method[key]:
                    errors.append(
                        f"{cell_id}: statistic {key} disagrees with the manifest"
                    )
            if "fixed rolling" not in str(statistic.get("forecast_scheme", "")).lower():
                errors.append(f"{cell_id}: statistic is not tied to fixed rolling estimation")
            mean = statistic.get("mean_loss_diff_aug_minus_base")
            standard_error = statistic.get("standard_error")
            z_stat = statistic.get("z_stat")
            raw_p = statistic.get(decision["raw_p_field"])
            two_sided_p = statistic.get("p_value_two_sided")
            if not _finite_number(mean):
                errors.append(f"{cell_id}: statistic mean loss differential is not finite")
            if not _finite_number(standard_error) or standard_error <= 0:
                errors.append(f"{cell_id}: statistic standard_error is not finite-positive")
            if _finite_number(standard_error) and type(n_origins) is int:
                try:
                    implied_lrv = standard_error * standard_error * n_origins
                except (OverflowError, TypeError, ValueError):
                    implied_lrv = math.inf
                if not _finite_number(implied_lrv) or implied_lrv <= 0:
                    errors.append(f"{cell_id}: implied long-run variance is not finite-positive")
            if not _finite_number(z_stat):
                errors.append(f"{cell_id}: statistic z is not finite")
            elif _finite_number(mean) and _finite_number(standard_error) and standard_error > 0:
                expected_z = float(mean) / float(standard_error)
                if not _numbers_close(z_stat, expected_z):
                    errors.append(f"{cell_id}: statistic z does not equal mean/SE")
                expected_one_sided = 0.5 * (
                    1.0 + math.erf(float(z_stat) / math.sqrt(2.0))
                )
                expected_two_sided = math.erfc(abs(float(z_stat)) / math.sqrt(2.0))
                if not _numbers_close(raw_p, expected_one_sided):
                    errors.append(
                        f"{cell_id}: one-sided p-value disagrees with the normal reference"
                    )
                if not _numbers_close(two_sided_p, expected_two_sided):
                    errors.append(
                        f"{cell_id}: two-sided p-value disagrees with the normal reference"
                    )
                if _finite_number(raw_p) and 0 <= raw_p <= 1:
                    raw_p_by_id[cell_id] = float(raw_p)
                    z_by_id[cell_id] = float(z_stat)
            lag = statistic.get("hac_lag_used")
            if type(lag) is not int or type(n_origins) is not int or n_origins <= 0:
                errors.append(f"{cell_id}: HAC lag cannot be verified")
            elif declared["horizon"] >= n_origins or n_origins > 1_000_000_000:
                errors.append(f"{cell_id}: horizon/sample size is outside audit bounds")
            else:
                h = declared["horizon"]
                canonical = max(1, min(math.ceil(h ** (1 / 3) * n_origins ** (1 / 3)), n_origins // 4))
                expected_lag = max(h - 1, canonical)
                if lag != expected_lag or not (h - 1 <= lag < n_origins):
                    errors.append(
                        f"{cell_id}: HAC lag does not implement the declared canonical rule"
                    )

        for key in ("family", "horizon", "base"):
            if gate.get(key) != cell.get(key):
                errors.append(f"{cell_id}: gate {key} disagrees with the runtime cell")
        if gate.get("alt") != cell.get("alt"):
            errors.append(f"{cell_id}: gate alt disagrees with the runtime cell")
        if gate.get("inference") != inference:
            errors.append(f"{cell_id}: gate inference does not match the manifest")
        if gate.get("estimand") != method["runtime_estimand"]:
            errors.append(f"{cell_id}: gate estimand does not match the manifest")
        if gate.get("feeds_gate") is not True or gate.get("bounded_memory") is not True:
            errors.append(f"{cell_id}: gate record lacks fixed-memory eligibility")
        for key, value in (("cell.n_oos", cell.get("n_oos")), ("gate.n", gate.get("n"))):
            if value != n_origins:
                errors.append(f"{cell_id}: {key} disagrees with n_origins")
        if isinstance(statistic, dict) and statistic.get("n") != n_origins:
            errors.append(f"{cell_id}: statistic.n disagrees with n_origins")
        if isinstance(statistic, dict):
            decimals = decision["registry_stat_decimals"]
            runtime_z = statistic.get("z_stat")
            for label, row in (("gate", gate), ("registry", registry.get(cell_id, {}))):
                if _finite_number(runtime_z):
                    expected_rounded_z = round(float(runtime_z), decimals)
                    if not _numbers_close(
                        row.get(decision["registry_stat_field"]),
                        expected_rounded_z,
                        abs_tol=0.5 * 10 ** (-decimals) + 1e-12,
                    ):
                        errors.append(f"{cell_id}: {label} statistic disagrees with runtime z")
                if not _numbers_close(
                    row.get(decision["registry_raw_p_field"]),
                    statistic.get(decision["raw_p_field"]),
                ):
                    errors.append(f"{cell_id}: {label} raw p-value disagrees with runtime")

    primary_registry_ids = {
        cell_id for cell_id, row in registry.items() if row.get("family") == "primary"
    }
    if primary_registry_ids != expected_ids:
        errors.append("registry primary-cell set does not exactly match the manifest")
    feed_registry_ids = {
        cell_id for cell_id, row in registry.items() if row.get("feeds_gate") is True
    }
    if feed_registry_ids != expected_ids:
        errors.append("registry gate-bearing set does not exactly match the manifest")
    for cell_id, row in registry.items():
        if row.get("inference") != inference:
            errors.append(f"{cell_id}: registry inventory contains a foreign inference")
            continue
        if row.get("feeds_gate") is True and row.get("bounded_memory") is not True:
            errors.append(f"{cell_id}: an unbounded record reaches a gate")
        if cell_id not in expected_ids and row.get("feeds_gate") is True:
            errors.append(f"{cell_id}: an unmanifested non-primary record reaches a gate")
        if row.get("bounded_memory") is False:
            if row.get("feeds_gate") is not False or row.get("claim_role") != (
                "invalid_for_nested_inference_diagnostic_only"
            ):
                errors.append(f"{cell_id}: unbounded record is not locally diagnostic-only")
        elif cell_id in expected_ids:
            if row.get("claim_role") != "primary_unconditional_detection_gate":
                errors.append(f"{cell_id}: primary registry claim role is wrong")
            cell = by_id.get(cell_id, {})
            gate = gates.get(cell_id, {})
            for key in ("family", "horizon", "base", "alt"):
                if row.get(key) != cell.get(key) or row.get(key) != gate.get(key):
                    errors.append(
                        f"{cell_id}: primary registry {key} disagrees with cell/gate"
                    )
            for key in ("inference", "estimand", "n", "feeds_gate", "bounded_memory"):
                if row.get(key) != gate.get(key):
                    errors.append(
                        f"{cell_id}: primary registry {key} disagrees with gate"
                    )
        elif row.get("feeds_gate") is not False or row.get("claim_role") != (
            "non_primary_diagnostic_only"
        ):
            errors.append(f"{cell_id}: non-primary registry claim role is undeclared")

    if set(raw_p_by_id) != expected_ids:
        errors.append("primary raw p-value family is incomplete")
    else:
        ordered = sorted(raw_p_by_id, key=lambda cell_id: (raw_p_by_id[cell_id], cell_id))
        adjusted: dict[str, float] = {}
        running = 0.0
        family_size = len(ordered)
        for rank, cell_id in enumerate(ordered):
            running = max(running, (family_size - rank) * raw_p_by_id[cell_id])
            adjusted[cell_id] = min(1.0, running)
        alpha = decision["family_alpha"]
        critical = decision["critical_value"]
        gate_flag = decision["gate_flag_field"]
        holm_field = decision["holm_adjusted_p_field"]
        for cell_id in expected_ids:
            gate = gates.get(cell_id, {})
            expected_pass = bool(
                z_by_id[cell_id] < critical and adjusted[cell_id] < alpha
            )
            for label, row in (("gate", gate), ("registry", registry.get(cell_id, {}))):
                if not _numbers_close(row.get(holm_field), adjusted[cell_id]):
                    errors.append(
                        f"{cell_id}: {label} Holm-adjusted p-value is not reproducible"
                    )
                if label == "gate" or gate_flag in row:
                    if row.get(gate_flag) is not expected_pass:
                        errors.append(
                            f"{cell_id}: {label} flag is not derived from z and Holm p"
                        )
    multiple_testing = _resolve_runtime_path(
        runtime, implementation["runtime_multiple_testing_record"]
    )
    if isinstance(multiple_testing, dict):
        true_gate_count = sum(row.get("feeds_gate") is True for row in registry.values())
        if multiple_testing.get(decision["gate_count_field"]) != true_gate_count:
            errors.append("registry gate-eligible count disagrees with its rows")
        if true_gate_count != len(expected_ids):
            errors.append("registry gate-eligible count does not equal the manifest family")
    else:
        errors.append("runtime multiple-testing record is missing")

    if not isinstance(claims, dict):
        errors.append("runtime claim record is missing")
    else:
        observed_pass_count = sum(
            gates.get(cell_id, {}).get(decision["gate_flag_field"]) is True
            for cell_id in expected_ids
        )
        claim_keys = {
            key
            for key, value in claims.items()
            if isinstance(value, str)
            and value
            and (
                key.startswith("does_say_")
                or key == "claim_strength"
                or re.search(r"headline|conclusion|verdict|evidence", key, re.I)
            )
        }
        for key in claim_keys:
            lower = str(claims[key]).lower()
            if "unconditional" not in lower:
                errors.append(f"runtime final claim is not locally unconditional: {key}")
            if re.search(r"\bevery regime\b|\bstate[- ]dependent\b|(?<!un)\bconditional\b", lower):
                errors.append(f"runtime final claim overreaches into conditional ability: {key}")
        headline = str(claims.get("claim_strength", "")).lower()
        if "unconditional" not in headline or "evidence" not in headline:
            errors.append("runtime headline is not an unconditional evidence statement")
        if observed_pass_count == 0:
            if not (
                "inconclusive" in headline
                or "negative finding" in headline
                or re.search(r"\bno\b.{0,80}\bevidence\b", headline)
            ):
                errors.append("runtime headline polarity contradicts zero passing cells")
            if re.search(
                r"\b(?:strong|overwhelming|positive|robust)\b.{0,60}\bevidence\b"
                r".{0,30}\b(?:was found|supports|shows|proves)\b",
                headline,
            ) and not re.search(r"\bno\b.{0,60}\bevidence\b", headline):
                errors.append("runtime headline asserts positive evidence with zero passing cells")
        elif re.search(r"\bno\b.{0,80}\bevidence\b", headline):
            errors.append("runtime headline denies evidence despite passing cells")
        all_claim_text = " ".join(str(value).lower() for value in claims.values())
        if not all(token in all_claim_text for token in ("conditional", "regime", "not excluded")):
            errors.append("runtime final summary omits the conditional/regime caveat")
        if claims.get(decision["claim_family_count_field"]) != len(expected_ids):
            errors.append("runtime claim primary-family count is stale")
        if claims.get(decision["claim_pass_count_field"]) != observed_pass_count:
            errors.append("runtime claim passing-cell count is stale")
        verdict = runtime.get("verdict")
        if observed_pass_count > 0 and verdict != "POSITIVE_INCREMENTAL_PREDICTIVE_CONTENT":
            errors.append("runtime verdict does not reflect passing primary cells")
        if observed_pass_count == 0 and verdict == "POSITIVE_INCREMENTAL_PREDICTIVE_CONTENT":
            errors.append("runtime positive verdict has no passing primary cell")
    return errors


def _fixed_memory_claim_surface_errors(path: Path, manifest: dict) -> list[str]:
    """Require the same mechanically discovered surface as review certification."""
    actual = {
        candidate.relative_to(path.parent).as_posix()
        for candidate in path.parent.rglob("*")
        if candidate.is_file()
        and "__pycache__" not in candidate.parts
        and candidate.name != "review_verdict.json"
        and is_experiment_claim_surface_file(candidate)
    }
    declared = set(manifest["implementation"]["claim_surface_files"])
    if declared != actual:
        return [
            "manifest claim surface does not match mechanical discovery: "
            f"declared={sorted(declared)}, actual={sorted(actual)}"
        ]
    return []


def _fixed_memory_source_errors(tree: ast.AST, source: str, manifest: dict) -> list[str]:
    errors: list[str] = []
    implementation = manifest["implementation"]
    method = manifest["method_contract"]
    paired_name = implementation["paired_forecast_function"]
    statistic_name = implementation["statistic_function"]
    window_name = implementation["train_window_constant"]
    base_parameter = implementation["base_model_parameter"]
    augmented_parameter = implementation["augmented_model_parameter"]
    result_variable = implementation["paired_result_variable"]
    gate_function_name = implementation["gate_function"]
    record_constructor = implementation["registry_record_constructor"]
    gate_variable = implementation["gate_eligibility_variable"]
    whole_variable = implementation["whole_method_eligibility_variable"]
    bounded_parameter = implementation["bounded_memory_parameter"]
    audit_attribute = implementation["paired_audit_attribute"]
    eligibility_key = implementation["paired_eligibility_key"]
    base_design = implementation["base_design_variable"]
    augmented_design = implementation["augmented_design_variable"]
    fit_function = implementation["fit_function"]

    window, _, window_error = _literal_assignment(tree, window_name)
    if window_error or window != method["train_window"]:
        errors.append("source train-window constant does not match the manifest")

    _, manifest_line, _ = _literal_assignment(tree, FIXED_MEMORY_MANIFEST_NAME)
    mutator_methods = {
        "append",
        "extend",
        "insert",
        "remove",
        "pop",
        "clear",
        "sort",
        "reverse",
        "update",
        "setdefault",
        "__setitem__",
        "__delitem__",
    }
    canonical_hash_helper = "_canonical_object_sha256"
    canonical_hash_is_pure = _canonical_hash_helper_is_pure(
        tree, canonical_hash_helper
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.NamedExpr) and _contains_name(
            node.value, FIXED_MEMORY_MANIFEST_NAME
        ):
            errors.append("fixed-memory manifest is aliased by an assignment expression")
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
            )
            for target in targets:
                is_declaration = (
                    getattr(node, "lineno", 0) == manifest_line
                    and isinstance(target, ast.Name)
                    and target.id == FIXED_MEMORY_MANIFEST_NAME
                )
                if not is_declaration and _root_name(target) == FIXED_MEMORY_MANIFEST_NAME:
                    errors.append("fixed-memory manifest is mutated after declaration")
                value = getattr(node, "value", None)
                if (
                    not is_declaration
                    and _contains_name(value, FIXED_MEMORY_MANIFEST_NAME)
                    and not _safe_manifest_id_projection(value)
                    and not _safe_manifest_hash_call(
                        value, canonical_hash_helper, canonical_hash_is_pure
                    )
                ):
                    errors.append("fixed-memory manifest is aliased for later mutation")
        if isinstance(node, ast.Delete) and any(
            _root_name(target) == FIXED_MEMORY_MANIFEST_NAME for target in node.targets
        ):
            errors.append("fixed-memory manifest is mutated after declaration")
        if isinstance(node, (ast.For, ast.AsyncFor)) and _contains_name(
            node.iter, FIXED_MEMORY_MANIFEST_NAME
        ):
            errors.append("fixed-memory manifest is aliased by iteration")
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            if any(
                _contains_name(generator.iter, FIXED_MEMORY_MANIFEST_NAME)
                for generator in node.generators
            ) and not _safe_manifest_id_projection(node):
                errors.append("fixed-memory manifest is aliased by a comprehension")
        if isinstance(node, ast.Match) and _contains_name(
            node.subject, FIXED_MEMORY_MANIFEST_NAME
        ):
            errors.append("fixed-memory manifest is aliased by pattern matching")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            defaults = [*node.args.defaults, *node.args.kw_defaults]
            if any(
                _contains_name(default, FIXED_MEMORY_MANIFEST_NAME)
                for default in defaults
                if default is not None
            ):
                errors.append("fixed-memory manifest is captured in a callable default")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and _contains_name(node.func.value, FIXED_MEMORY_MANIFEST_NAME)
            and node.func.attr in mutator_methods
        ):
            errors.append("fixed-memory manifest is mutated after declaration")
        if isinstance(node, ast.Call) and any(
            _contains_name(argument, FIXED_MEMORY_MANIFEST_NAME)
            for argument in [*node.args, *(keyword.value for keyword in node.keywords)]
        ) and not (
            _call_name(node) == canonical_hash_helper and canonical_hash_is_pure
        ):
            errors.append("fixed-memory manifest is passed to an unverified callable")
        if (
            isinstance(node, (ast.Return, ast.Yield, ast.YieldFrom))
            and _contains_name(node.value, FIXED_MEMORY_MANIFEST_NAME)
            and not _safe_manifest_hash_call(
                node.value, canonical_hash_helper, canonical_hash_is_pure
            )
        ):
            errors.append("fixed-memory manifest escapes from a callable")

    spec_name = implementation["model_spec_registry"]
    specs, spec_line, specs_error = _literal_assignment(tree, spec_name)
    if specs_error or not isinstance(specs, dict):
        errors.append("source model-spec registry is missing or non-literal")
        specs = {}
    primary_spec_names: set[str] = set()
    for cell in manifest["primary_cells"]:
        primary_spec_names.update((cell["base"], cell["augmented"]))
        if specs.get(cell["base"]) != cell["base_predictors"]:
            errors.append(f"{cell['id']}: source base predictors disagree with manifest")
        if specs.get(cell["augmented"]) != cell["augmented_predictors"]:
            errors.append(f"{cell['id']}: source augmented predictors disagree with manifest")
    for node in ast.walk(tree):
        targets: list[ast.AST] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        elif isinstance(node, ast.Delete):
            targets = list(node.targets)
        for target in targets:
            if (
                getattr(node, "lineno", 0) == spec_line
                and isinstance(target, ast.Name)
                and target.id == spec_name
            ):
                continue
            if _root_name(target) != spec_name:
                continue
            key = target.slice if isinstance(target, ast.Subscript) else None
            safe_nonprimary_key = (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and key.value not in primary_spec_names
            )
            if isinstance(key, ast.JoinedStr):
                prefix = ""
                for part in key.values:
                    if isinstance(part, ast.Constant) and isinstance(part.value, str):
                        prefix += part.value
                    else:
                        break
                safe_nonprimary_key = bool(prefix) and not any(
                    name.startswith(prefix) for name in primary_spec_names
                )
            if not safe_nonprimary_key:
                errors.append("source mutates a primary model-spec binding")

    paired = _function(tree, paired_name)
    if paired is None:
        errors.append("paired forecast function is missing or duplicated")
    else:
        args = [arg.arg for arg in paired.args.args]
        if base_parameter not in args or augmented_parameter not in args:
            errors.append("paired forecast function omits declared model parameters")
        if "train_window" not in args:
            errors.append("paired forecast function has no train_window argument")
        else:
            defaults = dict(zip(args[-len(paired.args.defaults) :], paired.args.defaults))
            default = defaults.get("train_window")
            if not isinstance(default, ast.Name) or default.id != window_name:
                errors.append("paired forecast train_window does not default to the fixed constant")

        required_audit_keys = {
            "fixed_window_held",
            "same_training_dates_for_both_models",
            "embargo_ok",
            "base_training_schedule_sha256",
            "aug_training_schedule_sha256",
            "common_complete_case_mask_sha256",
            "origin_schedule_sha256",
            "gw_fixed_memory_eligible",
        }
        audit_mappings: list[dict[str, ast.AST]] = []
        for node in ast.walk(paired):
            if not isinstance(node, ast.Dict):
                continue
            mapping = {
                key.value: value
                for key, value in zip(node.keys, node.values)
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            if required_audit_keys <= set(mapping):
                audit_mappings.append(mapping)
        if len(audit_mappings) != 1:
            errors.append("paired forecast function must emit one complete audit record")
        else:
            audit_mapping = audit_mappings[0]
            for key in (
                "fixed_window_held",
                "same_training_dates_for_both_models",
                "embargo_ok",
                "gw_fixed_memory_eligible",
            ):
                if isinstance(audit_mapping[key], ast.Constant):
                    errors.append(f"paired forecast provenance is hardcoded: {key}")
        registry_reads = {
            node.slice.id
            for node in ast.walk(paired)
            if isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == spec_name
            and isinstance(node.slice, ast.Name)
            and node.slice.id in {base_parameter, augmented_parameter}
        }
        if registry_reads != {base_parameter, augmented_parameter}:
            errors.append("paired forecast function does not read both declared model specs")
        design_bindings: dict[str, list[ast.AST]] = {base_design: [], augmented_design: []}
        for node in ast.walk(paired):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in design_bindings:
                    design_bindings[target.id].append(node.value)
        expected_design_params = {
            base_design: base_parameter,
            augmented_design: augmented_parameter,
        }
        for design_name, parameter in expected_design_params.items():
            bindings = design_bindings[design_name]
            if len(bindings) != 1 or not any(
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id == spec_name
                and isinstance(node.slice, ast.Name)
                and node.slice.id == parameter
                for node in ast.walk(bindings[0])
            ):
                errors.append(
                    f"paired forecast design {design_name} is not bound to {parameter}"
                )
        expected_subset = f"set({spec_name}[{base_parameter}]) < set({spec_name}[{augmented_parameter}])"
        if not any(
            isinstance(node, ast.Compare)
            and len(node.ops) == 1
            and isinstance(node.ops[0], ast.Lt)
            and ast.unparse(node) == expected_subset
            for node in ast.walk(paired)
        ):
            errors.append("paired forecast function does not enforce strict predictor nesting")
        fit_calls: dict[str, list[ast.Call]] = {base_design: [], augmented_design: []}
        for node in ast.walk(paired):
            if (
                isinstance(node, ast.Call)
                and _call_name(node) == fit_function
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id in fit_calls
            ):
                fit_calls[node.args[0].id].append(node)
        if any(len(calls) != 1 for calls in fit_calls.values()):
            errors.append("paired forecast function must fit each declared design exactly once")
        else:
            base_call = fit_calls[base_design][0]
            augmented_call = fit_calls[augmented_design][0]
            if (
                len(base_call.args) < 5
                or len(augmented_call.args) < 5
                or [ast.dump(arg) for arg in base_call.args[1:5]]
                != [ast.dump(arg) for arg in augmented_call.args[1:5]]
            ):
                errors.append("base and augmented fits do not share the paired schedule")

    statistic = _function(tree, statistic_name)
    if statistic is None:
        errors.append("unconditional GW/DM statistic function is missing or duplicated")
    else:
        statistic_text = ast.unparse(statistic).lower()
        statistic_literals = {
            node.value
            for node in ast.walk(statistic)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        for token in (
            "mean_loss_diff_aug_minus_base",
            "hac_lag_used",
            "standard_error",
            "hac_kernel",
            "hac_bandwidth_rule",
            "reference_distribution",
            method["runtime_estimand"],
            method["loss"],
            method["hac_kernel"],
            method["hac_bandwidth_rule"],
            method["reference_distribution"],
        ):
            if token not in statistic_literals:
                errors.append(f"statistic provenance token missing: {token}")
        if "bartlett" not in statistic_text or "norm" not in statistic_text:
            errors.append("statistic source does not visibly implement Bartlett/normal inference")

    inference = implementation["gate_registry_inference"]
    gate_function = _function(tree, gate_function_name)
    gate_tree: ast.AST = gate_function if gate_function is not None else tree
    if gate_function is None:
        errors.append("gate function is missing or duplicated")
    else:
        gate_args = {arg.arg for arg in gate_function.args.args}
        required_gate_args = {
            "register_gate",
            "family",
            bounded_parameter,
            base_parameter,
            augmented_parameter,
        }
        if not required_gate_args <= gate_args:
            errors.append("gate function omits provenance/model parameters")
        paired_result_assignments = [
            node
            for node in ast.walk(gate_function)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == result_variable
                for target in node.targets
            )
            and isinstance(node.value, ast.Call)
            and _call_name(node.value) == paired_name
        ]
        if len(paired_result_assignments) != 1:
            errors.append("gate function does not bind exactly one paired forecast result")
        else:
            paired_call_names = {
                node.id
                for argument in paired_result_assignments[0].value.args
                for node in ast.walk(argument)
                if isinstance(node, ast.Name)
            }
            if not {base_parameter, augmented_parameter} <= paired_call_names:
                errors.append("gate function does not pass both declared model specs")
    gate_records = []
    for node in ast.walk(gate_tree):
        if not isinstance(node, ast.Call) or _call_name(node) != record_constructor:
            continue
        keywords = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        value = keywords.get("inference")
        if isinstance(value, ast.Constant) and value.value == inference:
            gate_records.append(keywords)
    if not gate_records:
        errors.append("no TestRecord wires the manifest inference into the registry")
    for record in gate_records:
        feed = record.get("feeds_gate")
        bounded = record.get("bounded_memory")
        if not isinstance(feed, ast.Name) or feed.id != gate_variable:
            errors.append("fixed-memory TestRecord gate sink is not derived from eligibility")
        if not isinstance(bounded, ast.Name) or bounded.id != whole_variable:
            errors.append("fixed-memory TestRecord does not carry whole-method provenance")

    gate_assignments = [
        node
        for node in ast.walk(gate_tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == gate_variable for target in node.targets)
    ]
    if len(gate_assignments) != 1:
        errors.append("gate_eligible must have exactly one source assignment")
    else:
        gate_expr = _unwrap_bool_call(gate_assignments[0].value)
        valid_family = lambda node: (
            isinstance(node, ast.Compare)
            and len(node.ops) == 1
            and isinstance(node.ops[0], ast.Eq)
            and len(node.comparators) == 1
            and (
                (
                    isinstance(node.left, ast.Name)
                    and node.left.id == "family"
                    and isinstance(node.comparators[0], ast.Constant)
                    and node.comparators[0].value == "primary"
                )
                or (
                    isinstance(node.left, ast.Constant)
                    and node.left.value == "primary"
                    and isinstance(node.comparators[0], ast.Name)
                    and node.comparators[0].id == "family"
                )
            )
        )
        if not (
            isinstance(gate_expr, ast.BoolOp)
            and isinstance(gate_expr.op, ast.And)
            and len(gate_expr.values) == 3
            and sum(isinstance(value, ast.Name) and value.id == "register_gate" for value in gate_expr.values) == 1
            and sum(isinstance(value, ast.Name) and value.id == whole_variable for value in gate_expr.values) == 1
            and sum(valid_family(value) for value in gate_expr.values) == 1
        ):
            errors.append("gate_eligible is not the provenance conjunction")
    whole_assignments = [
        node
        for node in ast.walk(gate_tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == whole_variable
            for target in node.targets
        )
    ]
    if len(whole_assignments) != 1:
        errors.append("whole_method_fixed_memory must have exactly one source assignment")
    else:
        whole_expr = _unwrap_bool_call(whole_assignments[0].value)
        provenance_compare = False
        bounded_operand = False
        if isinstance(whole_expr, ast.BoolOp) and isinstance(whole_expr.op, ast.And):
            bounded_operand = sum(
                isinstance(value, ast.Name) and value.id == bounded_parameter
                for value in whole_expr.values
            ) == 1
            provenance_compare = sum(
                isinstance(value, ast.Compare)
                and len(value.ops) == 1
                and isinstance(value.ops[0], ast.Is)
                and len(value.comparators) == 1
                and isinstance(value.comparators[0], ast.Constant)
                and value.comparators[0].value is True
                and isinstance(value.left, ast.Call)
                and isinstance(value.left.func, ast.Attribute)
                and value.left.func.attr == "get"
                and isinstance(value.left.func.value, ast.Attribute)
                and isinstance(value.left.func.value.value, ast.Name)
                and value.left.func.value.value.id == result_variable
                and value.left.func.value.attr == audit_attribute
                and len(value.left.args) == 1
                and isinstance(value.left.args[0], ast.Constant)
                and value.left.args[0].value == eligibility_key
                for value in whole_expr.values
            ) == 1
        if not (
            isinstance(whole_expr, ast.BoolOp)
            and isinstance(whole_expr.op, ast.And)
            and len(whole_expr.values) == 2
            and bounded_operand
            and provenance_compare
        ):
            errors.append("whole-method eligibility omits upstream or paired-fit provenance")

    lower = source.lower()
    if "unconditional" not in lower or "conditional_predictive_ability_not_tested" not in lower:
        errors.append("reader-facing source does not constrain the claim to unconditional ability")
    if "regime" not in lower or "not excluded" not in lower:
        errors.append("reader-facing source omits the regime-offsetting caveat")
    return errors


def _fixed_memory_receipt_errors(
    path: Path, trust_root: Path, logical_site: str, manifest: dict
) -> tuple[list[str], dict | None]:
    errors: list[str] = []
    registry_path = trust_root / FIXED_MEMORY_ADJUDICATIONS
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        return [f"external adjudication registry unavailable: {exc}"], None
    if not isinstance(registry, dict):
        return ["external adjudication registry is not a JSON object"], None
    if registry.get("schema") != "nested_dm_fixed_memory_adjudications.v1":
        return ["external adjudication registry has the wrong schema"], None
    if not _canonical_experiment_site(logical_site):
        return [f"candidate site is not canonical: {logical_site}"], None
    raw_entries = registry.get("entries")
    if not isinstance(raw_entries, list) or any(
        not isinstance(entry, dict) for entry in raw_entries
    ):
        return ["external adjudication entries are malformed"], None
    entries = [entry for entry in raw_entries if entry.get("site") == logical_site]
    if len(entries) != 1:
        return [f"expected one external adjudication for {logical_site}; found {len(entries)}"], None
    entry = entries[0]
    if entry.get("decision") != "accepted":
        errors.append("external adjudication decision is not accepted")
    if entry.get("verdict") != "PASS":
        errors.append("external adjudication verdict is not PASS")
    if entry.get("role") != FIXED_MEMORY_ROLE:
        errors.append("external adjudication role does not match")
    if entry.get("source_sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
        errors.append("external adjudication source hash is stale")
    if entry.get("manifest_sha256") != _canonical_sha256(manifest):
        errors.append("external adjudication manifest hash is stale")
    runtime_name = manifest["implementation"]["runtime_evidence_file"]
    runtime_path = path.parent / runtime_name
    runtime_record = entry.get("runtime_evidence")
    if not isinstance(runtime_record, dict) or runtime_record.get("file") != runtime_name:
        errors.append("external adjudication runtime evidence path does not match")
    elif runtime_record.get("schema") != FIXED_MEMORY_RUNTIME_SCHEMA:
        errors.append("external adjudication runtime evidence schema does not match")
    elif (
        not runtime_path.is_file()
        or runtime_record.get("sha256")
        != hashlib.sha256(runtime_path.read_bytes()).hexdigest()
    ):
        errors.append("external adjudication runtime evidence hash is stale")

    claim_files = manifest["implementation"]["claim_surface_files"]
    claim_hashes = entry.get("claim_surface_sha256")
    if not isinstance(claim_hashes, dict) or set(claim_hashes) != set(claim_files):
        errors.append("external adjudication claim-surface inventory does not match")
    else:
        for name in claim_files:
            claim_path = path.parent / name
            if not claim_path.is_file():
                errors.append(f"external adjudication claim-surface file is missing: {name}")
            elif claim_hashes[name] != hashlib.sha256(claim_path.read_bytes()).hexdigest():
                errors.append(f"external adjudication claim-surface hash is stale: {name}")

    manifest_cells = sorted(cell["id"] for cell in manifest["primary_cells"])
    if entry.get("primary_cells") != manifest_cells:
        errors.append("external adjudication primary cell inventory does not match")
    reviewed_commit = str(entry.get("reviewed_commit", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", reviewed_commit):
        errors.append("external adjudication reviewed_commit is missing")
    if not str(entry.get("reviewer", "")).strip():
        errors.append("external adjudication reviewer is missing")
    artifact_rel = entry.get("review_artifact")
    artifact_hash = entry.get("review_artifact_sha256")
    if not isinstance(artifact_rel, str) or not artifact_rel:
        errors.append("external adjudication review_artifact is missing")
    else:
        try:
            artifact = (trust_root / artifact_rel).resolve()
            artifact.relative_to(trust_root.resolve())
        except (OSError, ValueError) as exc:
            errors.append(f"external adjudication artifact path is invalid: {exc}")
        else:
            if not artifact.is_file():
                errors.append("external adjudication artifact is missing")
            elif hashlib.sha256(artifact.read_bytes()).hexdigest() != artifact_hash:
                errors.append("external adjudication artifact hash is stale")
            else:
                try:
                    receipt = json.loads(artifact.read_text(encoding="utf-8"))
                except (OSError, ValueError, RecursionError) as exc:
                    errors.append(f"external adjudication artifact is not JSON: {exc}")
                else:
                    if not isinstance(receipt, dict):
                        errors.append("external adjudication receipt is not a JSON object")
                    elif receipt.get("schema") != "nested_dm_fixed_memory_receipt.v1":
                        errors.append("external adjudication receipt has the wrong schema")
                    else:
                        for key in (
                            "verdict",
                            "decision",
                            "role",
                            "site",
                            "source_sha256",
                            "manifest_sha256",
                            "runtime_evidence",
                            "claim_surface_sha256",
                            "primary_cells",
                            "reviewer",
                            "reviewed_commit",
                        ):
                            if receipt.get(key) != entry.get(key):
                                errors.append(
                                    f"external adjudication receipt disagrees on {key}"
                                )

    if re.fullmatch(r"[0-9a-f]{40}", reviewed_commit):
        try:
            object_type = subprocess.run(
                ["git", "cat-file", "-t", reviewed_commit],
                cwd=trust_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        except OSError as exc:
            errors.append(f"external adjudication commit cannot be inspected: {exc}")
            object_type = subprocess.CompletedProcess([], 127, b"", b"")
        if object_type.returncode != 0 or object_type.stdout.strip() != b"commit":
            errors.append("external adjudication reviewed_commit is not a commit object")
        committed_files = {
            logical_site: entry.get("source_sha256"),
            **{
                (Path(logical_site).parent / name).as_posix(): claim_hashes.get(name)
                for name in claim_files
                if isinstance(claim_hashes, dict)
            },
        }
        for relative, expected_hash in committed_files.items():
            try:
                proc = subprocess.run(
                    ["git", "show", f"{reviewed_commit}:{relative}"],
                    cwd=trust_root,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
            except OSError as exc:
                errors.append(
                    f"external adjudication commit file cannot be inspected: {relative}: {exc}"
                )
                warn(
                    "audit_nested_dm_misuse",
                    "external adjudication commit file cannot be inspected",
                    relative=relative,
                    err=str(exc),
                )
                continue
            if proc.returncode != 0:
                errors.append(
                    f"external adjudication commit does not contain reviewed file: {relative}"
                )
            elif hashlib.sha256(proc.stdout).hexdigest() != expected_hash:
                errors.append(
                    f"external adjudication commit bytes disagree for {relative}"
                )
    return errors, entry


def _fixed_memory_role_evidence(
    path: Path,
    scan_root: Path,
    trust_root: Path | None,
    tree: ast.AST,
    source: str,
) -> tuple[list[Evidence], list[str]]:
    manifest, line, literal_error = _literal_assignment(
        tree, FIXED_MEMORY_MANIFEST_NAME
    )
    if literal_error:
        return [], [literal_error]
    errors = _fixed_memory_manifest_errors(manifest)
    if not errors:
        errors.extend(_fixed_memory_claim_surface_errors(path, manifest))
    if not errors:
        errors.extend(_fixed_memory_source_errors(tree, source, manifest))
    if not errors:
        errors.extend(_fixed_memory_runtime_errors(path, manifest))
    receipt = None
    if not errors:
        if trust_root is None:
            errors.append("trusted repository root cannot be established")
        else:
            receipt_errors, receipt = _fixed_memory_receipt_errors(
                path,
                trust_root,
                _logical_experiment_site(path, scan_root),
                manifest,
            )
            errors.extend(receipt_errors)
    if errors:
        return [], errors
    return [
        Evidence(line or 0, f"validated {FIXED_MEMORY_MANIFEST_NAME}"),
        Evidence(0, f"external adjudication: {receipt['review_artifact']}"),
    ], []


def scan_file(
    path: Path,
    root: Path = REPO_ROOT,
    *,
    trust_root: Path | None = None,
) -> Finding | None:
    trust_root = trust_root.resolve() if trust_root is not None else _trusted_repo_root(root)
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))
    fixed_memory_declared = _has_module_scope_binding(
        tree, FIXED_MEMORY_MANIFEST_NAME
    )

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
    if not nested and not fixed_memory_declared:
        return None

    raw = _raw_dm_ast_evidence(tree, lines)
    # Result keys and generic one-sample loss tests can be split over lines, so
    # retain narrow textual evidence as a second channel.
    raw.extend(_regex_evidence(GENERIC_LOSS_TEST_RE, lines))
    raw = _dedupe(raw)
    if not raw and not fixed_memory_declared:
        return None

    claim = _claim_ast_evidence(tree, lines)
    for i, line in enumerate(lines, start=1):
        if RAW_DM_TEXT_RE.search(line) and CLAIM_WORD_RE.search(line):
            claim.append(Evidence(i, line.strip()[:240]))
    claim = _dedupe(claim)

    full_cw = _regex_evidence(FULL_CW_PRIMARY_RE, lines)
    diagnostic = _regex_evidence(DM_DIAGNOSTIC_RE, lines)
    fixed_memory_safe: list[Evidence] = []
    fixed_memory_errors: list[str] = []
    if fixed_memory_declared:
        fixed_memory_safe, fixed_memory_errors = _fixed_memory_role_evidence(
            path, root, trust_root, tree, source
        )
    if fixed_memory_declared:
        # A malformed third-role claim fails closed. It cannot fall through to a
        # looser CW/diagnostic lexical marker in the same file.
        safe = fixed_memory_safe
    else:
        safe = full_cw or (
            diagnostic if not PRIMARY_DM_DECL_RE.search(source) else []
        )
    safe = _dedupe(safe)
    if fixed_memory_safe:
        role = FIXED_MEMORY_ROLE
    elif fixed_memory_declared:
        role = "invalid_fixed_memory_evidence"
    elif full_cw or (diagnostic and not PRIMARY_DM_DECL_RE.search(source)):
        role = "diagnostic_with_cw_primary"
    else:
        role = "primary_raw_dm" if claim else "review_required"
    return Finding(
        file=_logical_experiment_site(path, root),
        test_role=role,
        nested_evidence=nested,
        raw_dm_evidence=raw,
        claim_evidence=claim,
        safe_role_evidence=safe,
        role_validation_errors=fixed_memory_errors,
    )


def scan_population(root: Path = REPO_ROOT) -> AuditResult:
    findings: list[Finding] = []
    reviewed_safe: list[Finding] = []
    errors: list[str] = []
    paths = sorted(root.glob(SCAN_GLOB))
    for path in paths:
        try:
            finding = scan_file(path, root)
        except (OSError, UnicodeError, SyntaxError, RecursionError) as exc:
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
        if finding.test_role in SAFE_ROLES:
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
