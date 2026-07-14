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
import subprocess
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


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _logical_experiment_site(path: Path, root: Path) -> str:
    """Strip a worktree prefix so one receipt binds the eventual merge path."""
    resolved = path.resolve()
    try:
        parts = resolved.relative_to(root.resolve()).parts
    except ValueError:
        parts = resolved.parts
    try:
        index = len(parts) - 1 - tuple(reversed(parts)).index("experiments")
    except ValueError:
        return resolved.as_posix()
    return Path(*parts[index:]).as_posix()


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


def _function(tree: ast.AST, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    matches = [
        node
        for node in getattr(tree, "body", [])
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    return matches[0] if len(matches) == 1 else None


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
        "runtime_evidence_file",
        "runtime_evidence_key",
        "claim_surface_files",
    }
    if set(implementation) != expected_implementation:
        errors.append("implementation keys do not match the v1 schema")
    for key in (
        "paired_forecast_function",
        "statistic_function",
        "gate_registry_inference",
        "train_window_constant",
        "runtime_evidence_file",
        "runtime_evidence_key",
    ):
        if not isinstance(implementation.get(key), str) or not implementation[key].strip():
            errors.append(f"implementation.{key} is missing")
    claim_files = implementation.get("claim_surface_files")
    if (
        not isinstance(claim_files, list)
        or not claim_files
        or any(not isinstance(name, str) or Path(name).name != name for name in claim_files)
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
    if type(method.get("train_window")) is not int or method.get("train_window", 0) <= 0:
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
    estimand = str(method.get("estimand", "")).lower()
    if "unconditional" not in estimand or "average" not in estimand:
        errors.append("method_contract.estimand must say unconditional average loss")

    stages = manifest.get("feature_stages")
    if not isinstance(stages, list) or not stages:
        errors.append("feature_stages must be a non-empty list")
        stages = []
    stage_by_id: dict[str, dict] = {}
    output_owner: dict[str, str] = {}
    bounded_stage_roles = {"observed", "finite_lag", "fixed_rolling"}
    for index, stage in enumerate(stages):
        prefix = f"feature_stages[{index}]"
        if not isinstance(stage, dict):
            errors.append(f"{prefix} is not an object")
            continue
        if set(stage) != {"id", "outputs", "memory", "max_observations"}:
            errors.append(f"{prefix} keys do not match the v1 schema")
        stage_id = stage.get("id")
        if not isinstance(stage_id, str) or not stage_id:
            errors.append(f"{prefix}.id is missing")
            continue
        if stage_id in stage_by_id:
            errors.append(f"duplicate feature stage id: {stage_id}")
        stage_by_id[stage_id] = stage
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
        if stage.get("memory") not in bounded_stage_roles:
            errors.append(f"{prefix}.memory is not bounded")
        if (
            type(stage.get("max_observations")) is not int
            or stage.get("max_observations", 0) <= 0
        ):
            errors.append(f"{prefix}.max_observations must be positive")

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
        "family",
        "asset",
        "base",
        "augmented",
        "strictly_nested",
        "horizon",
        "rv_proxy",
        "state_lag",
        "flow_lag",
        "smearing",
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
        for key in ("family", "asset", "base", "augmented", "rv_proxy", "smearing"):
            if not isinstance(cell.get(key), str) or not cell[key].strip():
                errors.append(f"{prefix}.{key} is missing")
        expected_id = (
            f"{cell.get('family')}|{cell.get('asset')}_h{cell.get('horizon')}|"
            f"{cell.get('augmented')}|{cell.get('rv_proxy')}|fl{cell.get('flow_lag')}"
        )
        if cell_id != expected_id:
            errors.append(f"{prefix}.id is not derivable from its declared fields")
        if cell.get("family") != "primary":
            errors.append(f"{prefix}.family must be primary")
        if cell.get("base") == cell.get("augmented"):
            errors.append(f"{prefix} does not name a proper nested augmentation")
        if cell.get("strictly_nested") is not True:
            errors.append(f"{prefix}.strictly_nested must be true")
        if cell.get("feeds_gate") is not True:
            errors.append(f"{prefix}.feeds_gate must be true")
        for key in ("horizon", "state_lag", "flow_lag"):
            if type(cell.get(key)) is not int or cell.get(key, 0) <= 0:
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
        if isinstance(base_predictors, list) and isinstance(aug_predictors, list):
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
        if "paired_log_variance_fit" not in used:
            errors.append(f"{prefix} omits the paired final-estimation stage")
        if isinstance(aug_predictors, list):
            uncovered = [
                predictor
                for predictor in aug_predictors
                if output_owner.get(predictor) not in set(used)
            ]
            if uncovered:
                errors.append(f"{prefix} has predictors without a used stage: {uncovered}")
    if len(ids) != len(set(ids)):
        errors.append("primary cell ids are not unique")
    if "expanding" in json.dumps(manifest, sort_keys=True).lower():
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
    return type(value) in (int, float) and math.isfinite(value)


def _fixed_memory_runtime_errors(path: Path, manifest: dict) -> list[str]:
    errors: list[str] = []
    implementation = manifest["implementation"]
    method = manifest["method_contract"]
    runtime_name = implementation["runtime_evidence_file"]
    if Path(runtime_name).name != runtime_name:
        return ["runtime evidence file must be a sibling basename"]
    runtime_path = path.parent / runtime_name
    try:
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
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
    }
    metadata_map = {
        "family": "family",
        "asset": "asset",
        "horizon": "horizon",
        "rv_proxy": "rv_proxy",
        "base": "base",
        "augmented": "alt",
        "state_lag": "state_lag",
        "flow_lag": "flow_lag",
        "smearing": "smearing",
    }
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
        for key in digest_keys - {"id", "eligibility"}:
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
            if "fixed rolling" not in str(statistic.get("forecast_scheme", "")).lower():
                errors.append(f"{cell_id}: statistic is not tied to fixed rolling estimation")
            mean = statistic.get("mean_loss_diff_aug_minus_base")
            standard_error = statistic.get("standard_error")
            if not _finite_number(mean):
                errors.append(f"{cell_id}: statistic mean loss differential is not finite")
            if not _finite_number(standard_error) or standard_error <= 0:
                errors.append(f"{cell_id}: statistic standard_error is not finite-positive")
            if _finite_number(standard_error) and type(n_origins) is int:
                implied_lrv = standard_error**2 * n_origins
                if not math.isfinite(implied_lrv) or implied_lrv <= 0:
                    errors.append(f"{cell_id}: implied long-run variance is not finite-positive")
            if (
                type(statistic.get("hac_lag_used")) is not int
                or statistic.get("hac_lag_used", -1) < declared["horizon"] - 1
            ):
                errors.append(f"{cell_id}: HAC lag is missing or below h-1")

        for key in ("family", "asset", "horizon", "base"):
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

    primary_registry_ids = {
        cell_id for cell_id, row in registry.items() if row.get("family") == "primary"
    }
    if primary_registry_ids != expected_ids:
        errors.append("registry primary-cell set does not exactly match the manifest")
    for cell_id, row in registry.items():
        if row.get("inference") != inference:
            errors.append(f"{cell_id}: registry inventory contains a foreign inference")
            continue
        if row.get("feeds_gate") is True and row.get("bounded_memory") is not True:
            errors.append(f"{cell_id}: an unbounded record reaches a gate")
        if row.get("bounded_memory") is False:
            if row.get("feeds_gate") is not False or row.get("claim_role") != (
                "invalid_for_nested_inference_diagnostic_only"
            ):
                errors.append(f"{cell_id}: unbounded record is not locally diagnostic-only")
        elif cell_id in expected_ids:
            if row.get("claim_role") != "primary_unconditional_detection_gate":
                errors.append(f"{cell_id}: primary registry claim role is wrong")
        elif row.get("claim_role") != "robustness_unconditional_sensitivity":
            errors.append(f"{cell_id}: non-primary registry claim role is undeclared")
    multiple_testing = runtime.get("multiple_testing")
    if isinstance(multiple_testing, dict):
        true_gate_count = sum(row.get("feeds_gate") is True for row in registry.values())
        if multiple_testing.get("n_gate_eligible_gw_tests") != true_gate_count:
            errors.append("registry gate-eligible count disagrees with its rows")

    if not isinstance(claims, dict):
        errors.append("runtime claim record is missing")
    else:
        for key, value in claims.items():
            lower = str(value).lower()
            if (
                isinstance(value, str)
                and value
                and "predict" in lower
                and (key.startswith("does_say_") or "claim" in key)
                and "unconditional" not in lower
            ):
                errors.append(f"runtime final claim is not locally unconditional: {key}")
        headline = str(claims.get("claim_strength", "")).lower()
        if "unconditional" not in headline or "evidence" not in headline:
            errors.append("runtime headline is not an unconditional evidence statement")
        all_claim_text = " ".join(str(value).lower() for value in claims.values())
        if not all(token in all_claim_text for token in ("conditional", "regime", "not excluded")):
            errors.append("runtime final summary omits the conditional/regime caveat")
    return errors


def _fixed_memory_claim_surface_errors(path: Path, manifest: dict) -> list[str]:
    """Require the same mechanically discovered surface as review certification."""
    actual = {
        candidate.relative_to(path.parent).as_posix()
        for candidate in path.parent.rglob("*")
        if candidate.is_file()
        and "__pycache__" not in candidate.parts
        and candidate.name != "review_verdict.json"
        and (
            candidate.suffix == ".py"
            or candidate.name == "README.md"
            or candidate.name.endswith("_results.json")
        )
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

    window, _, window_error = _literal_assignment(tree, window_name)
    if window_error or window != method["train_window"]:
        errors.append("source train-window constant does not match the manifest")

    _, manifest_line, _ = _literal_assignment(tree, FIXED_MEMORY_MANIFEST_NAME)
    for node in ast.walk(tree):
        if getattr(node, "lineno", 0) <= (manifest_line or 0):
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = (
                node.targets
                if isinstance(node, ast.Assign)
                else [node.target]
            )
            for target in targets:
                root = target
                while isinstance(root, (ast.Subscript, ast.Attribute)):
                    root = root.value
                if isinstance(root, ast.Name) and root.id == FIXED_MEMORY_MANIFEST_NAME:
                    errors.append("fixed-memory manifest is mutated after declaration")
                value = getattr(node, "value", None)
                if isinstance(value, ast.Name) and value.id == FIXED_MEMORY_MANIFEST_NAME:
                    errors.append("fixed-memory manifest is aliased for later mutation")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == FIXED_MEMORY_MANIFEST_NAME
            and node.func.attr in {"update", "setdefault", "pop", "clear"}
        ):
            errors.append("fixed-memory manifest is mutated after declaration")

    specs, _, specs_error = _literal_assignment(tree, "SPECS")
    if specs_error or not isinstance(specs, dict):
        errors.append("source SPECS registry is missing or non-literal")
    else:
        for cell in manifest["primary_cells"]:
            if specs.get(cell["base"]) != cell["base_predictors"]:
                errors.append(f"{cell['id']}: source base predictors disagree with manifest")
            if specs.get(cell["augmented"]) != cell["augmented_predictors"]:
                errors.append(
                    f"{cell['id']}: source augmented predictors disagree with manifest"
                )

    paired = _function(tree, paired_name)
    if paired is None:
        errors.append("paired forecast function is missing or duplicated")
    else:
        args = [arg.arg for arg in paired.args.args]
        if "train_window" not in args:
            errors.append("paired forecast function has no train_window argument")
        else:
            defaults = dict(zip(args[-len(paired.args.defaults) :], paired.args.defaults))
            default = defaults.get("train_window")
            if not isinstance(default, ast.Name) or default.id != window_name:
                errors.append("paired forecast train_window does not default to the fixed constant")

        fit_spans = {
            tuple(ast.unparse(arg) for arg in call.args[:4])
            for call in ast.walk(paired)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "fit"
            and len(call.args) >= 4
        }
        if not {
            ("Xb", "origins", "start", "end"),
            ("Xa", "origins", "start", "end"),
        } <= fit_spans:
            errors.append(
                "base and augmented fits do not visibly share row ids/start/end windows"
            )

        paired_text = ast.unparse(paired)
        required_tokens = (
            ".dropna(subset=cols)",
            "end - train_window",
            "fixed_window_held",
            "same_training_dates_for_both_models",
            "embargo_ok",
            "base_training_schedule_sha256",
            "aug_training_schedule_sha256",
            "common_complete_case_mask_sha256",
            "gw_fixed_memory_eligible",
        )
        for token in required_tokens:
            if token not in paired_text:
                errors.append(f"paired forecast provenance token missing: {token}")
        for node in ast.walk(paired):
            if not isinstance(node, ast.Dict):
                continue
            mapping = {
                key.value: value
                for key, value in zip(node.keys, node.values)
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            same_dates = mapping.get("same_training_dates_for_both_models")
            if same_dates is not None and isinstance(same_dates, ast.Constant):
                errors.append("same_training_dates_for_both_models is hardcoded, not derived")

    statistic = _function(tree, statistic_name)
    if statistic is None:
        errors.append("unconditional GW/DM statistic function is missing or duplicated")
    else:
        statistic_text = ast.unparse(statistic)
        for token in (
            "_bartlett_lrv",
            "stats.norm",
            "mean_loss_diff_aug_minus_base",
            "hac_lag_used",
            "standard_error",
            "E[QLIKE_aug - QLIKE_base]",
        ):
            if token not in statistic_text:
                errors.append(f"statistic provenance token missing: {token}")

    inference = implementation["gate_registry_inference"]
    gate_records = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) != "TestRecord":
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
        if not isinstance(feed, ast.Name) or feed.id != "gate_eligible":
            errors.append("fixed-memory TestRecord gate sink is not derived from eligibility")
        if not isinstance(bounded, ast.Name) or bounded.id != "whole_method_fixed_memory":
            errors.append("fixed-memory TestRecord does not carry whole-method provenance")

    gate_assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "gate_eligible" for target in node.targets)
    ]
    if len(gate_assignments) != 1:
        errors.append("gate_eligible must have exactly one source assignment")
    else:
        gate_text = ast.unparse(gate_assignments[0].value)
        if "register_gate" not in gate_text or "whole_method_fixed_memory" not in gate_text:
            errors.append("gate_eligible is not the provenance conjunction")
    whole_assignments = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "whole_method_fixed_memory"
            for target in node.targets
        )
    ]
    if len(whole_assignments) != 1:
        errors.append("whole_method_fixed_memory must have exactly one source assignment")
    else:
        whole_text = ast.unparse(whole_assignments[0].value)
        if "bounded_memory" not in whole_text or "gw_fixed_memory_eligible" not in whole_text:
            errors.append("whole-method eligibility omits upstream or paired-fit provenance")

    lower = source.lower()
    if "unconditional" not in lower or "conditional_predictive_ability_not_tested" not in lower:
        errors.append("reader-facing source does not constrain the claim to unconditional ability")
    if "regime" not in lower or "not excluded" not in lower:
        errors.append("reader-facing source omits the regime-offsetting caveat")
    return errors


def _fixed_memory_receipt_errors(
    path: Path, trust_root: Path, manifest: dict
) -> tuple[list[str], dict | None]:
    errors: list[str] = []
    registry_path = trust_root / FIXED_MEMORY_ADJUDICATIONS
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"external adjudication registry unavailable: {exc}"], None
    if not isinstance(registry, dict):
        return ["external adjudication registry is not a JSON object"], None
    if registry.get("schema") != "nested_dm_fixed_memory_adjudications.v1":
        return ["external adjudication registry has the wrong schema"], None
    logical_site = _logical_experiment_site(path, trust_root)
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
        artifact = (trust_root / artifact_rel).resolve()
        try:
            artifact.relative_to(trust_root.resolve())
        except ValueError:
            errors.append("external adjudication artifact escapes the repository")
        else:
            if not artifact.is_file():
                errors.append("external adjudication artifact is missing")
            elif hashlib.sha256(artifact.read_bytes()).hexdigest() != artifact_hash:
                errors.append("external adjudication artifact hash is stale")
            else:
                try:
                    receipt = json.loads(artifact.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
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
        committed_files = {
            logical_site: entry.get("source_sha256"),
            **{
                (Path(logical_site).parent / name).as_posix(): claim_hashes.get(name)
                for name in claim_files
                if isinstance(claim_hashes, dict)
            },
        }
        for relative, expected_hash in committed_files.items():
            proc = subprocess.run(
                ["git", "show", f"{reviewed_commit}:{relative}"],
                cwd=trust_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
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
    path: Path, scan_root: Path, trust_root: Path, tree: ast.AST, source: str
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
        receipt_errors, receipt = _fixed_memory_receipt_errors(
            path, trust_root, manifest
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
    trust_root: Path = REPO_ROOT,
) -> Finding | None:
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
    fixed_memory_safe: list[Evidence] = []
    fixed_memory_errors: list[str] = []
    fixed_memory_declared = FIXED_MEMORY_MANIFEST_NAME in source
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
