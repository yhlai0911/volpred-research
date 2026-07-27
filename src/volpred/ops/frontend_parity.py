"""Deterministic route/scenario parity audit for the active Next.js frontend."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCHEMA = "frontend-route-scenario-parity.v1"
_REQUIRED_SCENARIOS = frozenset(
    {
        "public_first_paint",
        "auth_callback",
        "member_navigation",
        "admin_observer",
        "seo",
        "mobile_navigation",
        "accessibility_navigation",
    }
)
_HREF = re.compile(
    r"""\bhref\s*(?:=|:)\s*(?:"(?P<double>/[^"]*)"|'(?P<single>/[^']*)')"""
)
_REDIRECT_SOURCE = re.compile(
    r"""\bsource\s*:\s*(?:"(?P<double>/[^"]*)"|'(?P<single>/[^']*)')"""
)
_HREF_TEMPLATE = re.compile(
    r"""\bhref\s*=\s*\{`(?P<template>[^`]*)`\}"""
)
_HREF_EXPRESSION = re.compile(
    r"""\bhref\s*=\s*\{(?P<expression>[^{}\n]+)\}"""
)
_ROUTER_BINDING = re.compile(
    r"""\b(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*"""
    r"""useRouter\s*\(\s*\)"""
)
_HTTP_METHOD = re.compile(
    r"""\bexport\s+(?:async\s+)?(?:function|const)\s+"""
    r"""(?P<method>GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\b"""
)
_TEMPLATE_SLOT = re.compile(r"\$\{[^{}]*\}")
_ACCESS_LEVELS = frozenset({"public", "member", "admin", "service"})


@dataclass(frozen=True)
class _Route:
    canonical_route: str
    surface_route: str
    mode: str
    source_ref: str
    kind: str
    method: str | None = None


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _block(kind: str, **details: object) -> dict[str, object]:
    return {"kind": kind, **details}


def _repo_path(
    repo_root: Path,
    raw: object,
    *,
    blockers: list[dict[str, object]],
    field: str,
    kind: str,
) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        blockers.append(_block("path_contract", field=field, observed=raw))
        return None
    try:
        resolved = (repo_root / raw).resolve()
    except (OSError, RuntimeError):  # silent-ok: typed path_unreadable receipt
        blockers.append(_block("path_unreadable", field=field, source_ref=raw))
        return None
    if not resolved.is_relative_to(repo_root):
        blockers.append(_block("path_escape", field=field, source_ref=raw))
        return None
    if kind == "file" and not resolved.is_file():
        blockers.append(_block("missing_file", field=field, source_ref=raw))
        return None
    if kind == "directory" and not resolved.is_dir():
        blockers.append(
            _block("missing_directory", field=field, source_ref=raw)
        )
        return None
    return resolved


def _web_route(parts: tuple[str, ...]) -> str:
    if not parts:
        return "/"
    return "/" + "/".join(parts)


def _surface_identity(parts: tuple[str, ...]) -> tuple[str, str]:
    if parts and parts[0] == "v3":
        canonical = _web_route(parts[1:])
        surface = "/v3" + (canonical if canonical != "/" else "/")
        return "v3", surface
    return "original", _web_route(parts)


def _discover_routes(repo_root: Path, frontend_root: Path) -> list[_Route]:
    app_root = frontend_root / "src" / "app"
    routes: list[_Route] = []
    for page in sorted(app_root.rglob("page.tsx")):
        relative = page.parent.relative_to(app_root)
        parts = tuple(relative.parts)
        mode, surface = _surface_identity(parts)
        canonical = (
            _web_route(parts[1:])
            if mode == "v3"
            else _web_route(parts)
        )
        routes.append(
            _Route(
                canonical_route=canonical,
                surface_route=surface,
                mode=mode,
                source_ref=page.relative_to(repo_root).as_posix(),
                kind="page",
            )
        )
    for handler in sorted(app_root.rglob("route.ts")):
        relative = handler.parent.relative_to(app_root)
        parts = tuple(relative.parts)
        mode, surface = _surface_identity(parts)
        canonical = (
            _web_route(parts[1:])
            if mode == "v3"
            else _web_route(parts)
        )
        methods = sorted(
            {
                match.group("method")
                for match in _HTTP_METHOD.finditer(
                    handler.read_text(encoding="utf-8")
                )
            }
        )
        for method in methods or [None]:
            routes.append(
                _Route(
                    canonical_route=canonical,
                    surface_route=surface,
                    mode=("shared" if mode == "original" else mode),
                    source_ref=handler.relative_to(repo_root).as_posix(),
                    kind="route_handler",
                    method=method,
                )
            )
    sitemap = app_root / "sitemap.ts"
    if sitemap.exists():
        routes.append(
            _Route(
                canonical_route="/sitemap.xml",
                surface_route="/sitemap.xml",
                mode="shared",
                source_ref=sitemap.relative_to(repo_root).as_posix(),
                kind="metadata",
            )
        )
    robots = frontend_root / "public" / "robots.txt"
    if robots.exists():
        routes.append(
            _Route(
                canonical_route="/robots.txt",
                surface_route="/robots.txt",
                mode="shared",
                source_ref=robots.relative_to(repo_root).as_posix(),
                kind="metadata",
            )
        )
    return sorted(
        routes,
        key=lambda item: (
            item.canonical_route,
            item.mode,
            item.source_ref,
            item.method or "",
        ),
    )


def _compile_rules(
    raw_rules: object,
    blockers: list[dict[str, object]],
) -> list[tuple[dict[str, Any], re.Pattern[str]]]:
    if not isinstance(raw_rules, list):
        blockers.append(_block("contract_route_rules", reason="must_be_list"))
        return []
    compiled: list[tuple[dict[str, Any], re.Pattern[str]]] = []
    seen_ids: set[str] = set()
    for index, value in enumerate(raw_rules):
        if not isinstance(value, dict):
            blockers.append(
                _block("contract_route_rule", index=index, reason="must_be_object")
            )
            continue
        rule_id = value.get("id")
        pattern = value.get("pattern")
        if not isinstance(rule_id, str) or not rule_id.strip():
            blockers.append(
                _block("contract_route_rule", index=index, reason="missing_id")
            )
            continue
        if rule_id in seen_ids:
            blockers.append(_block("duplicate_rule_id", rule_id=rule_id))
            continue
        seen_ids.add(rule_id)
        if not isinstance(pattern, str):
            blockers.append(
                _block("contract_route_rule", rule_id=rule_id, reason="missing_pattern")
            )
            continue
        expected_modes = value.get("expected_modes")
        if (
            not isinstance(expected_modes, list)
            or not expected_modes
            or any(
                not isinstance(mode, str)
                or mode not in {"original", "v3", "shared"}
                for mode in expected_modes
            )
        ):
            blockers.append(
                _block("contract_expected_modes", rule_id=rule_id)
            )
            value = {**value, "expected_modes": []}
        if value.get("access") not in _ACCESS_LEVELS:
            blockers.append(_block("contract_access", rule_id=rule_id))
        owner_refs = value.get("authoritative_data_owner_refs")
        if (
            not isinstance(owner_refs, dict)
            or not owner_refs
            or any(
                mode not in value.get("expected_modes", [])
                or not isinstance(refs, list)
                or not refs
                or any(
                    not isinstance(owner_ref, str) or not owner_ref.strip()
                    for owner_ref in refs
                )
                for mode, refs in owner_refs.items()
            )
            or any(
                mode not in owner_refs
                for mode in value.get("expected_modes", [])
            )
        ):
            blockers.append(_block("missing_owner", rule_id=rule_id))
            value = {**value, "authoritative_data_owner_refs": {}}
        method_access = value.get("method_access")
        if method_access is not None and (
            not isinstance(method_access, dict)
            or not method_access
            or any(
                method not in {
                    "*", "GET", "POST", "PUT", "PATCH", "DELETE",
                    "OPTIONS", "HEAD",
                }
                or access not in _ACCESS_LEVELS
                for method, access in method_access.items()
            )
        ):
            blockers.append(_block("contract_method_access", rule_id=rule_id))
            value = {**value, "method_access": {}}
        capabilities = value.get("capabilities")
        if (
            not isinstance(capabilities, list)
            or not capabilities
            or any(
                not isinstance(capability, str) or not capability.strip()
                for capability in capabilities
            )
        ):
            blockers.append(
                _block("contract_capabilities", rule_id=rule_id)
            )
            value = {**value, "capabilities": []}
        mode_advantages = value.get("mode_advantages")
        if not isinstance(mode_advantages, dict):
            blockers.append(
                _block("contract_mode_advantages", rule_id=rule_id)
            )
            value = {**value, "mode_advantages": {}}
        else:
            invalid_advantage_modes = [
                mode
                for mode in value.get("expected_modes", [])
                if not isinstance(mode_advantages.get(mode), list)
                or not mode_advantages[mode]
                or any(
                    not isinstance(advantage, str) or not advantage.strip()
                    for advantage in mode_advantages[mode]
                )
            ]
            if invalid_advantage_modes:
                blockers.append(
                    _block(
                        "contract_mode_advantages",
                        rule_id=rule_id,
                        modes=invalid_advantage_modes,
                    )
                )
        try:
            compiled.append((value, re.compile(pattern)))
        except re.error as error:
            blockers.append(
                _block(
                    "contract_route_rule",
                    rule_id=rule_id,
                    reason="invalid_pattern",
                    error=str(error),
                )
            )
    return compiled


def _route_pattern(route: str) -> re.Pattern[str]:
    pieces: list[str] = []
    for part in route.strip("/").split("/"):
        if not part:
            continue
        if part.startswith("[...") and part.endswith("]"):
            pieces.append(r".+")
        elif part.startswith("[") and part.endswith("]"):
            pieces.append(r"[^/]+")
        else:
            pieces.append(re.escape(part))
    return re.compile(r"^/" + "/".join(pieces) + r"/?$")


def _redirect_sources(frontend_root: Path) -> set[str]:
    config = frontend_root / "next.config.js"
    if not config.exists():
        return set()
    text = config.read_text(encoding="utf-8")
    return {
        (match.group("double") or match.group("single")).rstrip("/") or "/"
        for match in _REDIRECT_SOURCE.finditer(text)
    }


def _valid_internal_path(
    raw: str,
    *,
    valid_patterns: list[re.Pattern[str]],
    valid_exact: set[str],
) -> bool:
    if not raw.startswith("/") or raw.startswith("//"):
        return True
    path = raw.split("#", 1)[0].split("?", 1)[0]
    path = path.rstrip("/") or "/"
    return (
        path in valid_exact
        or any(pattern.fullmatch(path) for pattern in valid_patterns)
    )


def _expression_path(expression: str) -> str | None:
    value = expression.strip()
    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in {"'", '"'}
    ):
        return value[1:-1]
    if len(value) >= 2 and value[0] == value[-1] == "`":
        return _TEMPLATE_SLOT.sub("sample", value[1:-1])
    return None


def _call_arguments(text: str, call_pattern: re.Pattern[str]) -> list[str]:
    """Return complete first arguments for calls, including multiline calls."""

    arguments: list[str] = []
    for match in call_pattern.finditer(text):
        start = match.end()
        depth = 1
        quote: str | None = None
        escaped = False
        cursor = start
        while cursor < len(text):
            character = text[cursor]
            if escaped:
                escaped = False
            elif character == "\\" and quote is not None:
                escaped = True
            elif quote is not None:
                if character == quote:
                    quote = None
            elif character in {"'", '"', "`"}:
                quote = character
            elif character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    arguments.append(text[start:cursor].strip())
                    break
            cursor += 1
    return arguments


def _dead_links(
    repo_root: Path,
    frontend_root: Path,
    routes: list[_Route],
) -> list[dict[str, object]]:
    valid_patterns = [
        _route_pattern(route.surface_route)
        for route in routes
        if route.kind in {"page", "route_handler"}
    ]
    valid_exact = {
        route.surface_route.rstrip("/") or "/"
        for route in routes
        if route.kind != "page"
    } | _redirect_sources(frontend_root)
    findings: list[dict[str, object]] = []
    source_files = sorted(
        path
        for path in (frontend_root / "src").rglob("*")
        if path.suffix in {".ts", ".tsx", ".js", ".jsx"}
    )
    for source in source_files:
        text = source.read_text(encoding="utf-8")
        for match in _HREF.finditer(text):
            raw = match.group("double") or match.group("single")
            if _valid_internal_path(
                raw,
                valid_patterns=valid_patterns,
                valid_exact=valid_exact,
            ):
                continue
            findings.append(
                _block(
                    "dead_internal_link",
                    path=raw,
                    source_ref=source.relative_to(repo_root).as_posix(),
                )
            )
        expression_spans: list[tuple[int, int]] = []
        for match in _HREF_TEMPLATE.finditer(text):
            expression_spans.append(match.span())
            raw = _TEMPLATE_SLOT.sub("sample", match.group("template"))
            if not _valid_internal_path(
                raw,
                valid_patterns=valid_patterns,
                valid_exact=valid_exact,
            ):
                findings.append(
                    _block(
                        "dead_internal_link",
                        path=raw,
                        source_ref=source.relative_to(repo_root).as_posix(),
                    )
                )
        for match in _HREF_EXPRESSION.finditer(text):
            expression_spans.append(match.span())
            raw = _expression_path(match.group("expression"))
            if raw is not None and _valid_internal_path(
                raw,
                valid_patterns=valid_patterns,
                valid_exact=valid_exact,
            ):
                continue
            findings.append(
                _block(
                    "unresolved_internal_navigation",
                    expression=match.group("expression").strip(),
                    source_ref=source.relative_to(repo_root).as_posix(),
                )
            )
        for occurrence in re.finditer(r"\bhref\s*=\s*\{", text):
            if any(
                start <= occurrence.start() < end
                for start, end in expression_spans
            ):
                continue
            findings.append(
                _block(
                    "unresolved_internal_navigation",
                    expression="<nested-or-multiline>",
                    source_ref=source.relative_to(repo_root).as_posix(),
                )
            )
        router_names = {
            binding.group("name")
            for binding in _ROUTER_BINDING.finditer(text)
        }
        navigation_patterns = [
            re.compile(
                rf"\b{re.escape(name)}\.(?:push|replace)\s*\("
            )
            for name in sorted(router_names)
        ]
        for navigation in navigation_patterns:
            for expression in _call_arguments(text, navigation):
                raw = _expression_path(expression)
                if raw is not None and _valid_internal_path(
                    raw,
                    valid_patterns=valid_patterns,
                    valid_exact=valid_exact,
                ):
                    continue
                findings.append(
                    _block(
                        "unresolved_internal_navigation",
                        expression=expression,
                        source_ref=source.relative_to(repo_root).as_posix(),
                    )
                )
    return findings


def _frontend_revision(
    *,
    repo_root: Path,
    frontend_root: Path,
    nested_git_required: bool,
    blockers: list[dict[str, object]],
) -> dict[str, object]:
    relevant = sorted(
        [
            path
            for path in (frontend_root / "src").rglob("*")
            if path.is_file()
            and path.suffix in {".ts", ".tsx", ".js", ".jsx"}
        ]
        + [
            path
            for path in (
                frontend_root / "next.config.js",
                frontend_root / "public" / "robots.txt",
            )
            if path.is_file()
        ]
    )
    digest = hashlib.sha256()
    for path in relevant:
        relative = path.relative_to(frontend_root).as_posix().encode()
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    revision: dict[str, object] = {
        "kind": "nested_git" if nested_git_required else "filesystem",
        "tree_sha256": digest.hexdigest(),
        "file_count": len(relevant),
    }
    if not nested_git_required:
        return revision
    commands = {
        "top_level": ["git", "rev-parse", "--show-toplevel"],
        "head": ["git", "rev-parse", "--verify", "HEAD^{commit}"],
        "status": ["git", "status", "--porcelain=v1", "--untracked-files=all"],
    }
    outputs: dict[str, str] = {}
    for key, command in commands.items():
        try:
            completed = subprocess.run(
                command,
                cwd=frontend_root,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            blockers.append(
                _block("frontend_revision_unreadable", operation=key)
            )
            return revision
        if completed.returncode != 0:
            blockers.append(
                _block("frontend_revision_unreadable", operation=key)
            )
            return revision
        outputs[key] = completed.stdout.strip()
    try:
        observed_top = Path(outputs["top_level"]).resolve()
    except (OSError, RuntimeError):
        observed_top = Path("/")
    if observed_top != frontend_root:
        blockers.append(
            _block(
                "frontend_revision_boundary",
                expected=frontend_root.relative_to(repo_root).as_posix(),
            )
        )
    status_bytes = outputs["status"].encode()
    revision.update(
        {
            "git_head": outputs["head"],
            "dirty": bool(outputs["status"]),
            "status_sha256": hashlib.sha256(status_bytes).hexdigest(),
        }
    )
    return revision


def _scenario_blockers(
    repo_root: Path,
    scenarios: object,
    rule_ids: set[str],
    rule_modes: dict[str, set[str]],
    required_scenario_ids: object,
) -> tuple[list[dict[str, object]], int]:
    if not isinstance(scenarios, list):
        return [_block("contract_scenarios", reason="must_be_list")], 0
    blockers: list[dict[str, object]] = []
    seen: set[str] = set()
    if (
        not isinstance(required_scenario_ids, list)
        or any(
            not isinstance(scenario_id, str) or not scenario_id.strip()
            for scenario_id in required_scenario_ids
        )
        or set(required_scenario_ids) != _REQUIRED_SCENARIOS
    ):
        blockers.append(
            _block(
                "required_scenario_contract",
                expected=sorted(_REQUIRED_SCENARIOS),
            )
        )
        required_scenario_ids = sorted(_REQUIRED_SCENARIOS)
    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, dict):
            blockers.append(
                _block("contract_scenario", index=index, reason="must_be_object")
            )
            continue
        scenario_id = scenario.get("id")
        if not isinstance(scenario_id, str) or not scenario_id:
            blockers.append(
                _block("contract_scenario", index=index, reason="missing_id")
            )
            continue
        if scenario_id in seen:
            blockers.append(
                _block("duplicate_scenario_id", scenario_id=scenario_id)
            )
        seen.add(scenario_id)
        required_rules = scenario.get("required_route_rules", [])
        required_modes = scenario.get("required_modes", [])
        required_rule_modes = scenario.get("required_rule_modes", {})
        if (
            not isinstance(required_rules, list)
            or not required_rules
            or any(not isinstance(rule_id, str) for rule_id in required_rules)
            or not isinstance(required_modes, list)
            or not required_modes
            or any(
                not isinstance(mode, str)
                or mode not in {"original", "v3", "shared"}
                for mode in required_modes
            )
            or not isinstance(required_rule_modes, dict)
        ):
            blockers.append(
                _block(
                    "scenario_coverage_contract",
                    scenario_id=scenario_id,
                )
            )
            required_rules = [
                rule_id
                for rule_id in required_rules
                if isinstance(rule_id, str)
            ] if isinstance(required_rules, list) else []
            required_modes = [
                mode
                for mode in required_modes
                if isinstance(mode, str)
                and mode in {"original", "v3", "shared"}
            ] if isinstance(required_modes, list) else []
            required_rule_modes = (
                required_rule_modes
                if isinstance(required_rule_modes, dict)
                else {}
            )
        for rule_id in required_rules:
            if rule_id not in rule_ids:
                blockers.append(
                    _block(
                        "scenario_unknown_rule",
                        scenario_id=scenario_id,
                        rule_id=rule_id,
                    )
                )
                continue
            rule_required_modes = required_rule_modes.get(
                rule_id,
                required_modes,
            )
            if (
                not isinstance(rule_required_modes, list)
                or any(
                    not isinstance(mode, str)
                    or mode not in {"original", "v3", "shared"}
                    for mode in rule_required_modes
                )
            ):
                blockers.append(
                    _block(
                        "scenario_coverage_contract",
                        scenario_id=scenario_id,
                        rule_id=rule_id,
                    )
                )
                continue
            missing_modes = sorted(
                {
                    mode
                    for mode in rule_required_modes
                    if mode not in rule_modes.get(rule_id, set())
                }
            )
            if missing_modes:
                blockers.append(
                    _block(
                        "scenario_mode_gap",
                        scenario_id=scenario_id,
                        rule_id=rule_id,
                        missing_modes=missing_modes,
                    )
                )
        evidence_rows = scenario.get("evidence")
        if not isinstance(evidence_rows, list) or not evidence_rows:
            blockers.append(
                _block(
                    "scenario_evidence_contract",
                    scenario_id=scenario_id,
                )
            )
            evidence_rows = []
        for evidence in evidence_rows:
            if not isinstance(evidence, dict) or not isinstance(
                evidence.get("path"), str
            ):
                blockers.append(
                    _block(
                        "scenario_evidence_contract",
                        scenario_id=scenario_id,
                    )
                )
                continue
            contains = evidence.get("contains")
            if (
                not isinstance(contains, list)
                or not contains
                or any(not isinstance(token, str) for token in contains)
            ):
                blockers.append(
                    _block(
                        "scenario_evidence_contract",
                        scenario_id=scenario_id,
                        source_ref=evidence["path"],
                    )
                )
                continue
            path = _repo_path(
                repo_root,
                evidence["path"],
                blockers=blockers,
                field="scenario_evidence",
                kind="file",
            )
            if path is None:
                continue
            text = path.read_text(encoding="utf-8")
            missing = [
                token
                for token in contains
                if token not in text
            ]
            if missing:
                blockers.append(
                    _block(
                        "scenario_evidence_mismatch",
                        scenario_id=scenario_id,
                        source_ref=evidence["path"],
                        missing=missing,
                    )
                )
    for required_id in required_scenario_ids:
        if required_id not in seen:
            blockers.append(
                _block(
                    "missing_required_scenario",
                    scenario_id=required_id,
                )
            )
    return blockers, len(scenarios)


def audit_frontend_parity(
    *,
    repo_root: Path,
    contract_path: Path,
    targets_path: Path,
) -> dict[str, object]:
    """Audit the active frontend against the versioned parity contract."""

    repo_root = repo_root.resolve()
    blockers: list[dict[str, object]] = []
    try:
        contract = _load_json(contract_path)
    except (OSError, json.JSONDecodeError) as error:
        return {
            "schema_version": "frontend-route-scenario-parity-report.v1",
            "status": "blocked",
            "blockers": [
                _block("contract_unreadable", error=type(error).__name__)
            ],
            "known_gaps": [],
            "routes": [],
            "summary": {
                "route_count": 0,
                "rule_count": 0,
                "scenario_count": 0,
                "known_gap_count": 0,
                "blocker_count": 1,
            },
        }
    if not isinstance(contract, dict) or contract.get("schema_version") != _SCHEMA:
        blockers.append(
            _block(
                "contract_schema",
                expected=_SCHEMA,
                observed=(
                    contract.get("schema_version")
                    if isinstance(contract, dict)
                    else None
                ),
            )
        )
        return _report([], [], blockers, 0, 0)
    try:
        targets = _load_json(targets_path)
    except (OSError, json.JSONDecodeError) as error:
        blockers.append(
            _block("project_targets_unreadable", error=type(error).__name__)
        )
        return _report([], [], blockers, 0, 0)
    if not isinstance(targets, dict):
        blockers.append(
            _block("project_targets_schema", reason="root_must_be_object")
        )
        return _report([], [], blockers, 0, 0)
    active = targets.get("active_frontend")
    expected = contract.get("frontend_target")
    if not isinstance(active, str) or not isinstance(expected, str):
        blockers.append(
            _block(
                "project_targets_schema",
                reason="active_frontend_must_be_text",
            )
        )
        return _report([], [], blockers, 0, 0)
    if active != expected:
        blockers.append(
            _block(
                "active_target_drift",
                expected=expected,
                observed=active,
            )
        )
    frontends = targets.get("frontends")
    if not isinstance(frontends, dict):
        blockers.append(
            _block("project_targets_schema", reason="frontends_must_be_object")
        )
        return _report([], [], blockers, 0, 0)
    frontend_spec = frontends.get(active, {})
    if not isinstance(frontend_spec, dict):
        blockers.append(
            _block(
                "project_targets_schema",
                reason="frontend_spec_must_be_object",
            )
        )
        return _report([], [], blockers, 0, 0)
    frontend_path = frontend_spec.get("path")
    if not isinstance(frontend_path, str):
        blockers.append(_block("active_target_missing", target=active))
        return _report([], [], blockers, 0, 0)
    frontend_root = _repo_path(
        repo_root,
        frontend_path,
        blockers=blockers,
        field="active_frontend",
        kind="directory",
    )
    if frontend_root is None:
        return _report([], [], blockers, 0, 0)
    revision_policy = contract.get("source_revision_policy")
    if (
        not isinstance(revision_policy, dict)
        or not isinstance(
            revision_policy.get("nested_git_required"),
            bool,
        )
    ):
        blockers.append(
            _block(
                "source_revision_contract",
                reason="nested_git_required_must_be_boolean",
            )
        )
        nested_git_required = True
    else:
        nested_git_required = revision_policy["nested_git_required"]
    source_revision = _frontend_revision(
        repo_root=repo_root,
        frontend_root=frontend_root,
        nested_git_required=nested_git_required,
        blockers=blockers,
    )
    routes = _discover_routes(repo_root, frontend_root)
    compiled = _compile_rules(contract.get("route_rules"), blockers)
    route_rows: list[dict[str, object]] = []
    by_rule_route: dict[tuple[str, str], set[str]] = defaultdict(set)
    for route in routes:
        matched = [
            rule
            for rule, pattern in compiled
            if pattern.fullmatch(route.canonical_route)
        ]
        if not matched:
            blockers.append(
                _block(
                    "unknown_route",
                    route=route.canonical_route,
                    mode=route.mode,
                    source_ref=route.source_ref,
                )
            )
            rule_id = None
        elif len(matched) > 1:
            blockers.append(
                _block(
                    "duplicate_route_owner",
                    route=route.canonical_route,
                    mode=route.mode,
                    rule_ids=sorted(rule["id"] for rule in matched),
                )
            )
            rule_id = None
        else:
            rule_id = matched[0]["id"]
            by_rule_route[(rule_id, route.canonical_route)].add(route.mode)
        matched_rule = matched[0] if len(matched) == 1 else {}
        owner_contract = matched_rule.get(
            "authoritative_data_owner_refs",
            {},
        )
        configured_owners = (
            owner_contract.get(route.mode, [])
            if isinstance(owner_contract, dict)
            else []
        )
        per_mode_owners = [
            route.source_ref if owner_ref == "$surface" else owner_ref
            for owner_ref in configured_owners
            if isinstance(owner_ref, str)
        ]
        method_access = matched_rule.get("method_access")
        access = matched_rule.get("access")
        if route.kind == "route_handler":
            if route.method is None:
                blockers.append(
                    _block(
                        "route_handler_method_unknown",
                        route=route.canonical_route,
                        source_ref=route.source_ref,
                    )
                )
                access = None
            elif not isinstance(method_access, dict):
                blockers.append(
                    _block(
                        "missing_method_access",
                        route=route.canonical_route,
                        method=route.method,
                        rule_id=rule_id,
                    )
                )
                access = None
            else:
                access = method_access.get(
                    route.method,
                    method_access.get("*"),
                )
                if access not in _ACCESS_LEVELS:
                    blockers.append(
                        _block(
                            "missing_method_access",
                            route=route.canonical_route,
                            method=route.method,
                            rule_id=rule_id,
                        )
                    )
                    access = None
        mode_advantages = matched_rule.get("mode_advantages", {})
        route_rows.append(
            {
                "canonical_route": route.canonical_route,
                "surface_route": route.surface_route,
                "mode": route.mode,
                "source_ref": route.source_ref,
                "kind": route.kind,
                "method": route.method,
                "rule_id": rule_id,
                "access": access,
                "authoritative_data_owner_refs": list(
                    dict.fromkeys(per_mode_owners)
                ),
                "capabilities": matched_rule.get("capabilities", []),
                "advantages": (
                    mode_advantages.get(route.mode, [])
                    if isinstance(mode_advantages, dict)
                    else []
                ),
            }
        )
    known_gaps: list[dict[str, object]] = []
    for rule, _pattern in compiled:
        rule_id = rule["id"]
        owner_refs = rule.get("authoritative_data_owner_refs")
        if not isinstance(owner_refs, dict) or not owner_refs:
            blockers.append(_block("missing_owner", rule_id=rule_id))
        else:
            for mode, mode_owner_refs in owner_refs.items():
                if not isinstance(mode_owner_refs, list):
                    continue
                for owner_ref in mode_owner_refs:
                    if owner_ref == "$surface":
                        continue
                    resolved_owner = _repo_path(
                        repo_root,
                        owner_ref,
                        blockers=blockers,
                        field="authoritative_data_owner_ref",
                        kind="path",
                    )
                    if (
                        resolved_owner is not None
                        and not resolved_owner.is_file()
                    ):
                        blockers.append(
                            _block(
                                "missing_owner_ref",
                                rule_id=rule_id,
                                mode=mode,
                                source_ref=owner_ref,
                            )
                        )
        expected_modes = rule.get("expected_modes", [])
        if not isinstance(expected_modes, list) or not expected_modes:
            blockers.append(
                _block("contract_expected_modes", rule_id=rule_id)
            )
            continue
        matched_routes = {
            canonical
            for current_rule, canonical in by_rule_route
            if current_rule == rule_id
        }
        if not matched_routes:
            blockers.append(_block("route_rule_without_routes", rule_id=rule_id))
            continue
        dispositions = rule.get("mode_dispositions", {})
        for canonical in sorted(matched_routes):
            observed_modes = by_rule_route[(rule_id, canonical)]
            for mode in expected_modes:
                if mode in observed_modes:
                    continue
                disposition = (
                    dispositions.get(mode)
                    if isinstance(dispositions, dict)
                    else None
                )
                if (
                    isinstance(disposition, dict)
                    and disposition.get("status") == "known_gap"
                    and isinstance(disposition.get("reason"), str)
                    and disposition["reason"].strip()
                ):
                    known_gaps.append(
                        {
                            "rule_id": rule_id,
                            "route": canonical,
                            "mode": mode,
                            "reason": disposition["reason"],
                        }
                    )
                else:
                    blockers.append(
                        _block(
                            "missing_mode",
                            rule_id=rule_id,
                            route=canonical,
                            mode=mode,
                        )
                    )
    blockers.extend(_dead_links(repo_root, frontend_root, routes))
    scenario_findings, scenario_count = _scenario_blockers(
        repo_root,
        contract.get("scenarios"),
        {rule["id"] for rule, _pattern in compiled},
        {
            rule_id: {
                mode
                for (current_rule, _canonical), modes in by_rule_route.items()
                if current_rule == rule_id
                for mode in modes
            }
            for rule_id in {rule["id"] for rule, _pattern in compiled}
        },
        contract.get("required_scenario_ids"),
    )
    blockers.extend(scenario_findings)
    post_revision = _frontend_revision(
        repo_root=repo_root,
        frontend_root=frontend_root,
        nested_git_required=nested_git_required,
        blockers=blockers,
    )
    revision_keys = {
        "kind",
        "tree_sha256",
        "file_count",
        "git_head",
        "dirty",
        "status_sha256",
    }
    stable_revision = {
        key: source_revision.get(key) for key in revision_keys
    } == {
        key: post_revision.get(key) for key in revision_keys
    }
    source_revision["stable"] = stable_revision
    if not stable_revision:
        blockers.append(
            _block(
                "frontend_source_drift",
                before_tree_sha256=source_revision.get("tree_sha256"),
                after_tree_sha256=post_revision.get("tree_sha256"),
                before_status_sha256=source_revision.get("status_sha256"),
                after_status_sha256=post_revision.get("status_sha256"),
            )
        )
        source_revision["post_audit"] = post_revision
    return _report(
        route_rows,
        known_gaps,
        blockers,
        len(compiled),
        scenario_count,
        source_revision=source_revision,
    )


def _report(
    routes: list[dict[str, object]],
    known_gaps: list[dict[str, object]],
    blockers: list[dict[str, object]],
    rule_count: int,
    scenario_count: int,
    *,
    source_revision: dict[str, object] | None = None,
) -> dict[str, object]:
    blockers = sorted(
        blockers,
        key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
    )
    known_gaps = sorted(
        known_gaps,
        key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
    )
    return {
        "schema_version": "frontend-route-scenario-parity-report.v1",
        "status": "blocked" if blockers else "passed",
        "blockers": blockers,
        "known_gaps": known_gaps,
        "routes": routes,
        "source_revision": source_revision,
        "summary": {
            "route_count": len(routes),
            "rule_count": rule_count,
            "scenario_count": scenario_count,
            "known_gap_count": len(known_gaps),
            "blocker_count": len(blockers),
        },
    }


__all__ = ["audit_frontend_parity"]
