"""Deterministic route/scenario parity audit for the active Next.js frontend."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCHEMA = "frontend-route-scenario-parity.v1"
_HREF = re.compile(
    r"""\bhref\s*(?:=|:)\s*(?:"(?P<double>/[^"]*)"|'(?P<single>/[^']*)')"""
)
_REDIRECT_SOURCE = re.compile(
    r"""\bsource\s*:\s*(?:"(?P<double>/[^"]*)"|'(?P<single>/[^']*)')"""
)


@dataclass(frozen=True)
class _Route:
    canonical_route: str
    surface_route: str
    mode: str
    source_ref: str
    kind: str


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _block(kind: str, **details: object) -> dict[str, object]:
    return {"kind": kind, **details}


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
        if parts and parts[0] == "api":
            continue
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
                mode=("shared" if mode == "original" else mode),
                source_ref=handler.relative_to(repo_root).as_posix(),
                kind="route_handler",
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


def _dead_links(
    repo_root: Path,
    frontend_root: Path,
    routes: list[_Route],
) -> list[dict[str, object]]:
    valid_patterns = [
        _route_pattern(route.surface_route)
        for route in routes
        if route.kind == "page"
    ]
    valid_exact = {
        route.surface_route.rstrip("/") or "/"
        for route in routes
        if route.kind != "page"
    } | _redirect_sources(frontend_root)
    findings: list[dict[str, object]] = []
    for source in sorted((frontend_root / "src").rglob("*.tsx")):
        text = source.read_text(encoding="utf-8")
        for match in _HREF.finditer(text):
            raw = match.group("double") or match.group("single")
            path = raw.split("#", 1)[0].split("?", 1)[0]
            path = path.rstrip("/") or "/"
            if (
                path.startswith("/api/")
                or path in valid_exact
                or any(pattern.fullmatch(path) for pattern in valid_patterns)
            ):
                continue
            findings.append(
                _block(
                    "dead_internal_link",
                    path=path,
                    source_ref=source.relative_to(repo_root).as_posix(),
                )
            )
    return findings


def _scenario_blockers(
    repo_root: Path,
    scenarios: object,
    rule_ids: set[str],
    rule_modes: dict[str, set[str]],
) -> tuple[list[dict[str, object]], int]:
    if not isinstance(scenarios, list):
        return [_block("contract_scenarios", reason="must_be_list")], 0
    blockers: list[dict[str, object]] = []
    seen: set[str] = set()
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
        if not isinstance(required_rules, list) or not isinstance(
            required_modes, list
        ):
            blockers.append(
                _block(
                    "scenario_coverage_contract",
                    scenario_id=scenario_id,
                )
            )
            continue
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
            missing_modes = sorted(
                {
                    mode
                    for mode in required_modes
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
        for evidence in scenario.get("evidence", []):
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
            path = repo_root / evidence["path"]
            if not path.is_file():
                blockers.append(
                    _block(
                        "scenario_evidence_missing",
                        scenario_id=scenario_id,
                        source_ref=evidence["path"],
                    )
                )
                continue
            text = path.read_text(encoding="utf-8")
            missing = [
                token
                for token in evidence.get("contains", [])
                if not isinstance(token, str) or token not in text
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
    active = targets.get("active_frontend")
    expected = contract.get("frontend_target")
    if active != expected:
        blockers.append(
            _block(
                "active_target_drift",
                expected=expected,
                observed=active,
            )
        )
    frontend_spec = targets.get("frontends", {}).get(active, {})
    frontend_path = frontend_spec.get("path")
    if not isinstance(frontend_path, str):
        blockers.append(_block("active_target_missing", target=active))
        return _report([], [], blockers, 0, 0)
    frontend_root = repo_root / frontend_path
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
        route_rows.append(
            {
                "canonical_route": route.canonical_route,
                "surface_route": route.surface_route,
                "mode": route.mode,
                "source_ref": route.source_ref,
                "kind": route.kind,
                "rule_id": rule_id,
                "access": matched_rule.get("access"),
                "authoritative_data_owner_refs": matched_rule.get(
                    "authoritative_data_owner_refs",
                    [],
                ),
            }
        )
    known_gaps: list[dict[str, object]] = []
    for rule, _pattern in compiled:
        rule_id = rule["id"]
        owner_refs = rule.get("authoritative_data_owner_refs")
        if not isinstance(owner_refs, list) or not owner_refs:
            blockers.append(_block("missing_owner", rule_id=rule_id))
        else:
            for owner_ref in owner_refs:
                if not isinstance(owner_ref, str) or not (
                    repo_root / owner_ref
                ).exists():
                    blockers.append(
                        _block(
                            "missing_owner_ref",
                            rule_id=rule_id,
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
    )
    blockers.extend(scenario_findings)
    return _report(
        route_rows,
        known_gaps,
        blockers,
        len(compiled),
        scenario_count,
    )


def _report(
    routes: list[dict[str, object]],
    known_gaps: list[dict[str, object]],
    blockers: list[dict[str, object]],
    rule_count: int,
    scenario_count: int,
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
        "summary": {
            "route_count": len(routes),
            "rule_count": rule_count,
            "scenario_count": scenario_count,
            "known_gap_count": len(known_gaps),
            "blocker_count": len(blockers),
        },
    }


__all__ = ["audit_frontend_parity"]
