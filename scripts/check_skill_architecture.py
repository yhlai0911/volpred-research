#!/usr/bin/env python3
"""Fail closed when project skills drift from the active platform architecture."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / ".claude" / "skills"
REGISTRY_PATH = ROOT / "config" / "skill_registry.json"
WORKFLOW_INDEX = ROOT / "docs" / "workflow-index.md"
SKILL_REGISTRY_DOC = ROOT / "docs" / "skill-registry.md"
SUPERVISOR_RULES = ROOT / "config" / "supervisor_rules.json"

MAX_DESCRIPTION_CHARS = 800
MAX_SKILL_LINES = 500

TASK_FAMILY_SKILL_SEQUENCES = {
    "research": ["autonomous-research"],
    "content": ["feed-publisher", "publication-candidates"],
    "member": ["member-questions"],
    "paper": [
        "paper-submission-pipeline",
        "paper-update",
        "finance-paper-quality",
    ],
    "review": [
        "paper-review-cycle",
        "latex-academic-reviewer",
        "citation-verifier",
        "agent-result-verification",
    ],
    "code": ["agent-result-verification"],
    "ops": ["platform-ops-manager", "admin-ops", "memory-health"],
    "strategy": ["strategy-lifecycle"],
}
TASK_FAMILY_ROUTE_SEQUENCES = {
    "research": ["workflow:research-design"],
    "content": ["workflow:feed-publish", "workflow:publication-scan"],
    "member": ["workflow:member-qa"],
    "paper": [
        "workflow:paper-submission",
        "workflow:paper-update",
        "workflow:paper-quality",
    ],
    "review": [
        "workflow:paper-review-round",
        "workflow:latex-review",
        "workflow:citation-check",
        "workflow:agent-result-check",
    ],
    "code": ["workflow:agent-result-check"],
    "ops": ["workflow:platform-ops", "workflow:ops-triage", "workflow:memory-health"],
    "strategy": ["workflow:strategy-lifecycle"],
}
TASK_FAMILY_ROLE_SEQUENCES = {
    "research": ["orchestrator"],
    "content": ["orchestrator", "leaf"],
    "member": ["leaf"],
    "paper": ["orchestrator", "leaf", "cross-cutting"],
    "review": ["leaf", "leaf", "cross-cutting", "cross-cutting"],
    "code": ["cross-cutting"],
    "ops": ["orchestrator", "orchestrator", "leaf"],
    "strategy": ["leaf"],
}
CONTEXT_SKILL_SEQUENCES = {
    "external_data_fetch": ["external-data-sources"],
    "taiwan_macro": ["external-data-sources"],
    "experiment_numbers_produced": ["agent-result-verification"],
    "worktree_merge": ["worktree-merge-verification"],
    "paper_stage_decision": ["paper-stage-classifier"],
    "methodology_peer_review": [
        "finance-paper-quality",
        "latex-academic-reviewer",
    ],
}
CONTEXT_ROUTE_SEQUENCES = {
    "external_data_fetch": ["workflow:data-source-lookup"],
    "taiwan_macro": ["workflow:data-source-lookup"],
    "experiment_numbers_produced": ["workflow:agent-result-check"],
    "worktree_merge": ["support:agent-result-verification"],
    "paper_stage_decision": ["support:paper-submission-pipeline"],
    "methodology_peer_review": ["workflow:paper-quality", "workflow:latex-review"],
}
CONTEXT_ROLE_SEQUENCES = {
    "external_data_fetch": ["leaf"],
    "taiwan_macro": ["leaf"],
    "experiment_numbers_produced": ["cross-cutting"],
    "worktree_merge": ["compatibility"],
    "paper_stage_decision": ["compatibility"],
    "methodology_peer_review": ["cross-cutting", "leaf"],
}
SEED_REQUIRED_OWNERS = {
    "member_qa_ranking": {
        "skill": "member-questions",
        "route": "workflow:member-qa",
        "role": "leaf",
    },
    "publication_candidates": {
        "skill": "publication-candidates",
        "route": "workflow:publication-scan",
        "role": "leaf",
    },
}


@dataclass(frozen=True)
class Issue:
    code: str
    detail: str
    skill: str | None = None
    path: str | None = None
    line: int | None = None


FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "retired_croncreate",
        re.compile(r"\bCronCreate\s*\("),
        "Session-local CronCreate is retired; use the Operations Core contract.",
    ),
    (
        "retired_piggyback_owner",
        re.compile(r"\brun_due_jobs\.py\b"),
        "run_due_jobs.py is rollback compatibility, not an active skill path.",
    ),
    (
        "unsafe_worktree_removal",
        re.compile(r"git\s+worktree\s+remove\s+(?:--force|-f|-ff)\b"),
        "Worktree integration must use the canonical merge workflow.",
    ),
    (
        "bare_cherry_pick",
        re.compile(r"(?m)^\s*(?:\$\s*)?git\s+cherry-pick\b"),
        "Do not document a bare cherry-pick path.",
    ),
    (
        "bare_branch_delete",
        re.compile(r"(?m)^\s*(?:\$\s*)?git\s+branch\s+-D\b"),
        "Do not document destructive branch deletion.",
    ),
    (
        "bare_git_mutation",
        re.compile(r"(?m)^\s*(?:\$\s*)?git\s+(?:add|commit|push)\b"),
        "Shared-checkout Git mutation must use scripts/git_writer_lock.py.",
    ),
    (
        "legacy_deploy_entry",
        re.compile(r"scripts/deploy_zeabur\.sh"),
        "Resolve the safe deploy entry from the active frontend contract.",
    ),
    (
        "legacy_browser_owner",
        re.compile(r"claude-in-chrome", re.IGNORECASE),
        "Facebook delivery is owned by scripts/fb_realchrome_post.py.",
    ),
    (
        "unsupported_paper_stage_flag",
        re.compile(r"paper-upsert[^\n]*--stage"),
        "Do not document a paper transition flag that the live CLI does not expose.",
    ),
    (
        "legacy_queue_semantics",
        re.compile(
            r"next_tasks\.json[^\n]*(?:legacy|非\s*canonical|不是正式|not\s+canonical)",
            re.IGNORECASE,
        ),
        "Resolve queue semantics from storage/ops/task_pool_mode.json.",
    ),
    (
        "legacy_task_api",
        re.compile(r"\bTaskCreate\s*\("),
        "Use the canonical task-pool ingress and lifecycle.",
    ),
    (
        "wrong_zeabur_service",
        re.compile(r"6a15c5a9938e05c2b6854116"),
        "Never embed a service ID; resolve config/project_targets.json.",
    ),
    (
        "legacy_paper_compiler",
        re.compile(r"\btectonic\s+main\.tex\b"),
        "Resolve the current paper build workflow instead of copying an old compiler command.",
    ),
)


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _frontmatter(skill_md: Path) -> tuple[dict[str, str], list[Issue]]:
    lines = skill_md.read_text(encoding="utf-8").splitlines()
    issues: list[Issue] = []
    skill = skill_md.parent.name
    if not lines or lines[0].strip() != "---":
        return {}, [
            Issue(
                code="frontmatter_missing",
                detail="SKILL.md must begin with YAML frontmatter.",
                skill=skill,
                path=_relative(skill_md),
                line=1,
            )
        ]
    try:
        end = lines.index("---", 1)
    except ValueError:
        return {}, [
            Issue(
                code="frontmatter_unclosed",
                detail="SKILL.md frontmatter has no closing delimiter.",
                skill=skill,
                path=_relative(skill_md),
                line=1,
            )
        ]

    data: dict[str, str] = {}
    current: str | None = None
    for raw in lines[1:end]:
        match = re.match(r"^([A-Za-z0-9_-]+):(?:\s*(.*))?$", raw)
        if match:
            current = match.group(1)
            data[current] = (match.group(2) or "").strip().strip("\"'")
            continue
        if current and raw.startswith((" ", "\t")):
            fragment = raw.strip().lstrip("|>").strip()
            if fragment:
                data[current] = f"{data[current]} {fragment}".strip()
    return data, issues


def _iter_skill_markdown(skill_dir: Path) -> Iterable[Path]:
    yield from sorted(skill_dir.rglob("*.md"))


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _workflow_projection_rows() -> tuple[dict[str, tuple[str, str]], list[Issue]]:
    if not WORKFLOW_INDEX.exists():
        return {}, [
            Issue(
                code="workflow_projection_missing",
                detail="docs/workflow-index.md is missing.",
                path=_relative(WORKFLOW_INDEX),
            )
        ]
    text = WORKFLOW_INDEX.read_text(encoding="utf-8")
    text, issues = _marked_projection(
        text,
        "<!-- skill-workflows:start -->",
        "<!-- skill-workflows:end -->",
        path=_relative(WORKFLOW_INDEX),
    )
    rows, row_issues = _parse_workflow_projection(
        text,
        path=_relative(WORKFLOW_INDEX),
    )
    return rows, [*issues, *row_issues]


def _parse_workflow_projection(
    text: str,
    *,
    path: str,
) -> tuple[dict[str, tuple[str, str]], list[Issue]]:
    rows: dict[str, tuple[str, str]] = {}
    issues: list[Issue] = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    expected_preamble = [
        "| Workflow ID | 使用時機 | Detail path |",
        "|---|---|---|",
    ]
    if lines[:2] != expected_preamble:
        issues.append(
            Issue(
                code="workflow_projection_header_invalid",
                detail="Workflow projection header or separator does not match its schema.",
                path=path,
            )
        )
    row_pattern = re.compile(
        r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*`([^`]+)`\s*\|$"
    )
    for line in lines[2:]:
        match = row_pattern.fullmatch(line)
        if match is None:
            issues.append(
                Issue(
                    code="workflow_projection_row_invalid",
                    detail=f"Unparseable workflow projection row: {line!r}.",
                    path=path,
                )
            )
            continue
        workflow, usage, detail_path = match.groups()
        if workflow in rows:
            issues.append(
                Issue(
                    code="workflow_projection_duplicate",
                    detail=f"Workflow {workflow!r} appears more than once in the projection.",
                    path=path,
                )
            )
        rows[workflow] = (usage.strip(), detail_path)
    return rows, issues


def _registry_projection_rows() -> tuple[dict[str, tuple[str, str, str]], list[Issue]]:
    if not SKILL_REGISTRY_DOC.exists():
        return {}, [
            Issue(
                code="registry_projection_missing",
                detail="docs/skill-registry.md is missing.",
                path=_relative(SKILL_REGISTRY_DOC),
            )
        ]
    text = SKILL_REGISTRY_DOC.read_text(encoding="utf-8")
    text, issues = _marked_projection(
        text,
        "<!-- skill-registry:start -->",
        "<!-- skill-registry:end -->",
        path=_relative(SKILL_REGISTRY_DOC),
    )
    rows, row_issues = _parse_registry_projection(
        text,
        path=_relative(SKILL_REGISTRY_DOC),
    )
    return rows, [*issues, *row_issues]


def _parse_registry_projection(
    text: str,
    *,
    path: str,
) -> tuple[dict[str, tuple[str, str, str]], list[Issue]]:
    rows: dict[str, tuple[str, str, str]] = {}
    issues: list[Issue] = []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    expected_preamble = [
        "| Skill | Role | Domain | Route |",
        "|---|---|---|---|",
    ]
    if lines[:2] != expected_preamble:
        issues.append(
            Issue(
                code="registry_projection_header_invalid",
                detail="Skill projection header or separator does not match its schema.",
                path=path,
            )
        )
    row_pattern = re.compile(
        r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$"
    )
    for line in lines[2:]:
        match = row_pattern.fullmatch(line)
        if match is None:
            issues.append(
                Issue(
                    code="registry_projection_row_invalid",
                    detail=f"Unparseable skill projection row: {line!r}.",
                    path=path,
                )
            )
            continue
        skill, role, domain, route = match.groups()
        if skill in rows:
            issues.append(
                Issue(
                    code="registry_projection_duplicate",
                    detail=f"Skill {skill!r} appears more than once in the projection.",
                    skill=skill,
                    path=path,
                )
            )
        rows[skill] = (role.strip(), domain.strip(), route.strip().strip("`"))
    return rows, issues


def _marked_projection(
    text: str,
    start: str,
    end: str,
    *,
    path: str,
) -> tuple[str, list[Issue]]:
    issues: list[Issue] = []
    start_count = text.count(start)
    end_count = text.count(end)
    if start_count != 1 or end_count != 1:
        issues.append(
            Issue(
                code="projection_marker_count",
                detail=(
                    f"Projection requires exactly one start and one end marker; "
                    f"found start={start_count}, end={end_count}."
                ),
                path=path,
            )
        )
        return "", issues
    start_offset = text.index(start)
    end_offset = text.index(end)
    if start_offset >= end_offset:
        issues.append(
            Issue(
                code="projection_marker_order",
                detail="Projection end marker must occur after its start marker.",
                path=path,
            )
        )
        return "", issues
    return text[start_offset + len(start) : end_offset], issues


def _supervisor_route_group_issues(
    *,
    route_group: str,
    routes: object,
    expected_routes: object,
    required_skill_sequences: dict[str, list[str]],
    required_route_sequences: dict[str, list[str]],
    required_role_sequences: dict[str, list[str]],
    registered: dict[str, dict],
) -> list[Issue]:
    issues: list[Issue] = []
    if not isinstance(routes, dict):
        issues.append(
            Issue(
                code="supervisor_route_group_missing",
                detail=f"Supervisor route group {route_group!r} is missing or invalid.",
                path=_relative(SUPERVISOR_RULES),
            )
        )
        routes = {}
    if not isinstance(expected_routes, dict):
        issues.append(
            Issue(
                code="supervisor_contract_group_missing",
                detail=(
                    f"Registry supervisor_dispatch group {route_group!r} "
                    "is missing or invalid."
                ),
                path=_relative(REGISTRY_PATH),
            )
        )
        expected_routes = {}
    required_keys = set(required_skill_sequences)
    if (
        set(required_route_sequences) != required_keys
        or set(required_role_sequences) != required_keys
    ):
        issues.append(
            Issue(
                code="supervisor_checker_contract_drift",
                detail=(
                    f"Checker skill/route/role vocabularies for {route_group} "
                    "must have identical keys."
                ),
                path=_relative(Path(__file__)),
            )
        )
    if set(routes) != required_keys:
        issues.append(
            Issue(
                code="supervisor_route_keys_drift",
                detail=(
                    f"Supervisor {route_group} keys {sorted(routes)} must equal "
                    f"the required vocabulary {sorted(required_keys)}."
                ),
                path=_relative(SUPERVISOR_RULES),
            )
        )
    if set(expected_routes) != required_keys:
        issues.append(
            Issue(
                code="supervisor_contract_keys_drift",
                detail=(
                    f"Registry {route_group} keys {sorted(expected_routes)} must equal "
                    f"the required vocabulary {sorted(required_keys)}."
                ),
                path=_relative(REGISTRY_PATH),
            )
        )
    if routes != expected_routes:
        issues.append(
            Issue(
                code="supervisor_dispatch_drift",
                detail=(
                    f"Supervisor {route_group} must exactly match "
                    "config/skill_registry.json supervisor_dispatch."
                ),
                path=_relative(SUPERVISOR_RULES),
            )
        )
    for route_name, skill_names in sorted(routes.items()):
        if not isinstance(skill_names, list) or any(
            not isinstance(skill_name, str) for skill_name in skill_names
        ):
            issues.append(
                Issue(
                    code="supervisor_route_invalid",
                    detail=(
                        f"Supervisor {route_group}.{route_name} must be "
                        "an array of skill names."
                    ),
                    path=_relative(SUPERVISOR_RULES),
                )
            )
            continue
        if not skill_names:
            issues.append(
                Issue(
                    code="supervisor_route_empty",
                    detail=f"Supervisor {route_group}.{route_name} may not be empty.",
                    path=_relative(SUPERVISOR_RULES),
                )
            )
            continue
        required_skills = required_skill_sequences.get(route_name) or []
        required_routes = required_route_sequences.get(route_name) or []
        required_roles = required_role_sequences.get(route_name) or []
        if (
            len(skill_names) != len(required_skills)
            or len(skill_names) != len(required_routes)
            or len(skill_names) != len(required_roles)
        ):
            issues.append(
                Issue(
                    code="supervisor_route_arity_mismatch",
                    detail=(
                        f"Supervisor {route_group}.{route_name} has {len(skill_names)} "
                        f"skills; its skill/route/role contract requires "
                        f"{len(required_skills)}/{len(required_routes)}/"
                        f"{len(required_roles)}."
                    ),
                    path=_relative(SUPERVISOR_RULES),
                )
            )
        if skill_names != required_skills:
            issues.append(
                Issue(
                    code="supervisor_skill_sequence_mismatch",
                    detail=(
                        f"Supervisor {route_group}.{route_name} must use exact "
                        f"skill sequence {required_skills}; found {skill_names}."
                    ),
                    path=_relative(SUPERVISOR_RULES),
                )
            )
        for index, required_route in enumerate(required_routes):
            if index >= len(skill_names):
                break
            skill_name = skill_names[index]
            metadata = registered.get(skill_name)
            owned_routes = (
                metadata.get("routes") if isinstance(metadata, dict) else None
            )
            if not isinstance(owned_routes, list) or any(
                not isinstance(route, str) for route in owned_routes
            ):
                issues.append(
                    Issue(
                        code="supervisor_owner_routes_invalid",
                        detail=(
                            f"Supervisor owner {skill_name!r} must declare routes "
                            "as list[str]."
                        ),
                        skill=skill_name,
                        path=_relative(REGISTRY_PATH),
                    )
                )
                continue
            if required_route not in owned_routes:
                issues.append(
                    Issue(
                        code="supervisor_route_owner_mismatch",
                        detail=(
                            f"Supervisor {route_group}.{route_name}[{index}] must own "
                            f"{required_route!r}; found {skill_name!r}."
                        ),
                        skill=skill_name,
                        path=_relative(SUPERVISOR_RULES),
                    )
                )
        for index, required_role in enumerate(required_roles):
            if index >= len(skill_names):
                break
            skill_name = skill_names[index]
            observed_role = registered.get(skill_name, {}).get("role")
            if observed_role != required_role:
                issues.append(
                    Issue(
                        code="supervisor_role_owner_mismatch",
                        detail=(
                            f"Supervisor {route_group}.{route_name}[{index}] requires "
                            f"role {required_role!r}; {skill_name!r} has "
                            f"{observed_role!r}."
                        ),
                        skill=skill_name,
                        path=_relative(SUPERVISOR_RULES),
                    )
                )
        for skill_name in skill_names:
            if skill_name not in registered:
                issues.append(
                    Issue(
                        code="supervisor_skill_missing",
                        detail=(
                            f"Supervisor {route_group}.{route_name} routes to "
                            f"unregistered skill {skill_name!r}."
                        ),
                        skill=skill_name,
                        path=_relative(SUPERVISOR_RULES),
                    )
                )
    return issues


def _supervisor_seed_issues(
    *,
    actual_seeds: dict[str, str],
    expected_seeds: object,
    registered: dict[str, dict],
) -> list[Issue]:
    issues: list[Issue] = []
    if not isinstance(expected_seeds, dict):
        issues.append(
            Issue(
                code="supervisor_seed_contract_missing",
                detail=(
                    "Registry supervisor_dispatch.seed_sources_priority "
                    "is missing or invalid."
                ),
                path=_relative(REGISTRY_PATH),
            )
        )
        expected_seeds = {}
    if set(actual_seeds) != set(SEED_REQUIRED_OWNERS):
        issues.append(
            Issue(
                code="supervisor_seed_keys_drift",
                detail=(
                    f"Skill-backed seed keys {sorted(actual_seeds)} must equal "
                    f"{sorted(SEED_REQUIRED_OWNERS)}."
                ),
                path=_relative(SUPERVISOR_RULES),
            )
        )
    if set(expected_seeds) != set(SEED_REQUIRED_OWNERS):
        issues.append(
            Issue(
                code="supervisor_seed_contract_keys_drift",
                detail=(
                    f"Registry seed keys {sorted(expected_seeds)} must equal "
                    f"{sorted(SEED_REQUIRED_OWNERS)}."
                ),
                path=_relative(REGISTRY_PATH),
            )
        )
    if actual_seeds != expected_seeds:
        issues.append(
            Issue(
                code="supervisor_seed_dispatch_drift",
                detail=(
                    "Skill-backed supervisor seeds must exactly match "
                    "config/skill_registry.json supervisor_dispatch."
                ),
                path=_relative(SUPERVISOR_RULES),
            )
        )
    for row_id, skill_name in sorted(actual_seeds.items()):
        if skill_name not in registered:
            issues.append(
                Issue(
                    code="supervisor_seed_skill_missing",
                    detail=(
                        f"Supervisor seed {row_id!r} routes to unregistered "
                        f"skill {skill_name!r}."
                    ),
                    skill=skill_name,
                    path=_relative(SUPERVISOR_RULES),
                )
            )
        required = SEED_REQUIRED_OWNERS.get(row_id) or {}
        required_skill = required.get("skill")
        if required_skill is not None and skill_name != required_skill:
            issues.append(
                Issue(
                    code="supervisor_seed_identity_mismatch",
                    detail=(
                        f"Supervisor seed {row_id!r} must use exact skill "
                        f"{required_skill!r}; found {skill_name!r}."
                    ),
                    skill=skill_name,
                    path=_relative(SUPERVISOR_RULES),
                )
            )
        required_route = required.get("route")
        metadata = registered.get(skill_name)
        owned_routes = metadata.get("routes") if isinstance(metadata, dict) else None
        routes_are_valid = isinstance(owned_routes, list) and all(
            isinstance(route, str) for route in owned_routes
        )
        if not routes_are_valid:
            issues.append(
                Issue(
                    code="supervisor_seed_routes_invalid",
                    detail=(
                        f"Supervisor seed owner {skill_name!r} must declare "
                        "routes as list[str]."
                    ),
                    skill=skill_name,
                    path=_relative(REGISTRY_PATH),
                )
            )
        if (
            required_route is not None
            and routes_are_valid
            and required_route not in owned_routes
        ):
            issues.append(
                Issue(
                    code="supervisor_seed_owner_mismatch",
                    detail=(
                        f"Supervisor seed {row_id!r} must route to the owner of "
                        f"{required_route!r}; found {skill_name!r}."
                    ),
                    skill=skill_name,
                    path=_relative(SUPERVISOR_RULES),
                )
            )
        required_role = required.get("role")
        observed_role = registered.get(skill_name, {}).get("role")
        if required_role is not None and observed_role != required_role:
            issues.append(
                Issue(
                    code="supervisor_seed_role_mismatch",
                    detail=(
                        f"Supervisor seed {row_id!r} requires role "
                        f"{required_role!r}; {skill_name!r} has "
                        f"{observed_role!r}."
                    ),
                    skill=skill_name,
                    path=_relative(SUPERVISOR_RULES),
                )
            )
    return issues


def _registry_skill_lists(
    registered: dict[str, dict],
) -> tuple[dict[str, list[str]], dict[str, list[str]], list[Issue]]:
    routes_by_skill: dict[str, list[str]] = {}
    contracts_by_skill: dict[str, list[str]] = {}
    issues: list[Issue] = []
    for skill, metadata in sorted(registered.items()):
        routes = metadata.get("routes")
        if not isinstance(routes, list) or any(
            not isinstance(route, str) or not route for route in routes
        ):
            issues.append(
                Issue(
                    code="registry_routes_invalid",
                    detail="Skill routes must be a list of non-empty strings.",
                    skill=skill,
                    path=_relative(REGISTRY_PATH),
                )
            )
            routes_by_skill[skill] = []
        else:
            routes_by_skill[skill] = routes
            if not routes:
                issues.append(
                    Issue(
                        code="route_missing",
                        detail="Every skill needs at least one workflow or support route.",
                        skill=skill,
                        path=_relative(REGISTRY_PATH),
                    )
                )
            if len(routes) != len(set(routes)):
                issues.append(
                    Issue(
                        code="registry_routes_duplicate",
                        detail="Skill routes must be unique.",
                        skill=skill,
                        path=_relative(REGISTRY_PATH),
                    )
                )

        contracts = metadata.get("contracts")
        if not isinstance(contracts, list) or any(
            not isinstance(contract, str) or not contract for contract in contracts
        ):
            issues.append(
                Issue(
                    code="registry_contracts_invalid",
                    detail="Skill contracts must be a list of non-empty strings.",
                    skill=skill,
                    path=_relative(REGISTRY_PATH),
                )
            )
            contracts_by_skill[skill] = []
        else:
            contracts_by_skill[skill] = contracts
            if len(contracts) != len(set(contracts)):
                issues.append(
                    Issue(
                        code="registry_contracts_duplicate",
                        detail="Skill contracts must be unique.",
                        skill=skill,
                        path=_relative(REGISTRY_PATH),
                    )
                )
    return routes_by_skill, contracts_by_skill, issues


def _parse_skill_backed_seeds(seed_rows: object) -> tuple[dict[str, str], list[Issue]]:
    issues: list[Issue] = []
    if not isinstance(seed_rows, list):
        return {}, [
            Issue(
                code="supervisor_seed_sources_missing",
                detail="Supervisor seed_sources_priority.order is missing or invalid.",
                path=_relative(SUPERVISOR_RULES),
            )
        ]

    actual_seeds: dict[str, str] = {}
    seen_ids: set[str] = set()
    for row in seed_rows:
        if not isinstance(row, dict):
            issues.append(
                Issue(
                    code="supervisor_seed_invalid",
                    detail="Every supervisor seed row must be an object.",
                    path=_relative(SUPERVISOR_RULES),
                )
            )
            continue
        row_id = row.get("id")
        if not isinstance(row_id, str) or not row_id:
            issues.append(
                Issue(
                    code="supervisor_seed_invalid",
                    detail="Every supervisor seed row requires a non-empty string id.",
                    path=_relative(SUPERVISOR_RULES),
                )
            )
            continue
        if row_id in seen_ids:
            issues.append(
                Issue(
                    code="supervisor_seed_duplicate",
                    detail=f"Supervisor seed id {row_id!r} appears more than once.",
                    path=_relative(SUPERVISOR_RULES),
                )
            )
        seen_ids.add(row_id)
        if "skill" not in row:
            continue
        skill_name = row.get("skill")
        if not isinstance(skill_name, str) or not skill_name:
            issues.append(
                Issue(
                    code="supervisor_seed_invalid",
                    detail="Skill-backed seed rows require a non-empty string skill.",
                    path=_relative(SUPERVISOR_RULES),
                )
            )
            continue
        actual_seeds[row_id] = skill_name
    return actual_seeds, issues


def collect_issues() -> list[Issue]:
    issues: list[Issue] = []

    if not REGISTRY_PATH.exists():
        return [
            Issue(
                code="registry_missing",
                detail=f"Missing {_relative(REGISTRY_PATH)}.",
                path=_relative(REGISTRY_PATH),
            )
        ]

    registry = _load_registry()
    raw_registered = registry.get("skills")
    registered: dict[str, dict] = {}
    if not isinstance(raw_registered, dict):
        issues.append(
            Issue(
                code="registry_skills_invalid",
                detail="config/skill_registry.json skills must be an object.",
                path=_relative(REGISTRY_PATH),
            )
        )
    else:
        for skill, metadata in raw_registered.items():
            if not isinstance(skill, str) or not skill or not isinstance(metadata, dict):
                issues.append(
                    Issue(
                        code="registry_skill_metadata_invalid",
                        detail=(
                            "Every registry skill needs a non-empty string id "
                            "and object metadata."
                        ),
                        skill=skill if isinstance(skill, str) else None,
                        path=_relative(REGISTRY_PATH),
                    )
                )
                if isinstance(skill, str) and skill:
                    registered[skill] = {}
                continue
            registered[skill] = metadata
    role_vocab = set(registry.get("role_vocabulary", []))
    contract_tokens: dict[str, str] = registry.get("contract_tokens", {})
    skill_routes, skill_contracts, metadata_issues = _registry_skill_lists(registered)
    issues.extend(metadata_issues)
    actual = {
        path.parent.name
        for path in SKILLS_DIR.glob("*/SKILL.md")
        if path.is_file()
    }

    if not SUPERVISOR_RULES.exists():
        issues.append(
            Issue(
                code="supervisor_rules_missing",
                detail="The live skill dispatch table is missing.",
                path=_relative(SUPERVISOR_RULES),
            )
        )
    else:
        supervisor = json.loads(SUPERVISOR_RULES.read_text(encoding="utf-8"))
        dispatch = supervisor.get("skill_dispatch_table") or {}
        expected_dispatch = registry.get("supervisor_dispatch")
        if not isinstance(expected_dispatch, dict):
            issues.append(
                Issue(
                    code="supervisor_contract_missing",
                    detail="config/skill_registry.json must define supervisor_dispatch.",
                    path=_relative(REGISTRY_PATH),
                )
            )
            expected_dispatch = {}
        family_sources = [
            {
                key
                for key in (supervisor.get("family_to_worker_routing") or {})
                if not key.startswith("_")
            },
            {
                key
                for key in ((supervisor.get("family_minimums") or {}).get("floors") or {})
                if not key.startswith("_")
            },
            {
                key
                for key in (
                    (supervisor.get("family_minimums") or {}).get("weekly_caps") or {}
                )
                if not key.startswith("_")
            },
            set(TASK_FAMILY_ROUTE_SEQUENCES),
        ]
        if any(keys != family_sources[0] for keys in family_sources[1:]):
            issues.append(
                Issue(
                    code="supervisor_family_vocabulary_drift",
                    detail=(
                        "family_to_worker_routing, family_minimums floors/caps, and "
                        "the skill-dispatch family vocabulary must match."
                    ),
                    path=_relative(SUPERVISOR_RULES),
                )
            )
        issues.extend(
            _supervisor_route_group_issues(
                route_group="by_task_family",
                routes=dispatch.get("by_task_family"),
                expected_routes=expected_dispatch.get("by_task_family"),
                required_skill_sequences=TASK_FAMILY_SKILL_SEQUENCES,
                required_route_sequences=TASK_FAMILY_ROUTE_SEQUENCES,
                required_role_sequences=TASK_FAMILY_ROLE_SEQUENCES,
                registered=registered,
            )
        )
        issues.extend(
            _supervisor_route_group_issues(
                route_group="by_context",
                routes=dispatch.get("by_context"),
                expected_routes=expected_dispatch.get("by_context"),
                required_skill_sequences=CONTEXT_SKILL_SEQUENCES,
                required_route_sequences=CONTEXT_ROUTE_SEQUENCES,
                required_role_sequences=CONTEXT_ROLE_SEQUENCES,
                registered=registered,
            )
        )

        seed_rows = (supervisor.get("seed_sources_priority") or {}).get("order")
        expected_seeds = expected_dispatch.get("seed_sources_priority")
        actual_seeds, seed_issues = _parse_skill_backed_seeds(seed_rows)
        issues.extend(seed_issues)
        issues.extend(
            _supervisor_seed_issues(
                actual_seeds=actual_seeds,
                expected_seeds=expected_seeds,
                registered=registered,
            )
        )

    for missing in sorted(set(registered) - actual):
        issues.append(
            Issue(
                code="registered_skill_missing",
                detail="Registry entry has no matching .claude/skills directory.",
                skill=missing,
                path=_relative(REGISTRY_PATH),
            )
        )
    for unregistered in sorted(actual - set(registered)):
        issues.append(
            Issue(
                code="skill_unregistered",
                detail="Skill directory is absent from config/skill_registry.json.",
                skill=unregistered,
                path=_relative(SKILLS_DIR / unregistered / "SKILL.md"),
            )
        )

    registry_projection, registry_projection_issues = _registry_projection_rows()
    issues.extend(registry_projection_issues)
    declared_doc = set(registry_projection)
    for missing in sorted(actual - declared_doc):
        issues.append(
            Issue(
                code="registry_projection_missing",
                detail="Skill is missing from docs/skill-registry.md.",
                skill=missing,
                path=_relative(SKILL_REGISTRY_DOC),
            )
        )
    for phantom in sorted(declared_doc - actual):
        issues.append(
            Issue(
                code="registry_projection_phantom",
                detail="docs/skill-registry.md names a skill directory that does not exist.",
                skill=phantom,
                path=_relative(SKILL_REGISTRY_DOC),
            )
        )

    workflow_projection, workflow_projection_issues = _workflow_projection_rows()
    issues.extend(workflow_projection_issues)
    workflows = set(workflow_projection)
    canonical_workflows = {
        route.split(":", 1)[1]
        for routes in skill_routes.values()
        for route in routes
        if route.startswith("workflow:")
    }
    workflow_usage = registry.get("workflow_usage")
    if not isinstance(workflow_usage, dict):
        issues.append(
            Issue(
                code="workflow_usage_contract_missing",
                detail="config/skill_registry.json must define workflow_usage.",
                path=_relative(REGISTRY_PATH),
            )
        )
        workflow_usage = {}
    if set(workflow_usage) != canonical_workflows:
        issues.append(
            Issue(
                code="workflow_usage_keys_drift",
                detail=(
                    f"workflow_usage keys {sorted(workflow_usage)} must equal "
                    f"registered workflows {sorted(canonical_workflows)}."
                ),
                path=_relative(REGISTRY_PATH),
            )
        )
    for phantom in sorted(workflows - canonical_workflows):
        issues.append(
            Issue(
                code="workflow_projection_phantom",
                detail=(
                    f"Workflow {phantom!r} is projected but no registered skill owns it."
                ),
                path=_relative(WORKFLOW_INDEX),
            )
        )
    for skill, metadata in sorted(registered.items()):
        role = metadata.get("role")
        if role not in role_vocab:
            issues.append(
                Issue(
                    code="invalid_role",
                    detail=f"Role {role!r} is outside role_vocabulary.",
                    skill=skill,
                    path=_relative(REGISTRY_PATH),
                )
            )
        routes = skill_routes.get(skill, [])
        for route in routes:
            if route.startswith("support:"):
                owner = route.split(":", 1)[1]
                if owner not in registered:
                    issues.append(
                        Issue(
                            code="support_owner_missing",
                            detail=f"Support owner {owner!r} is not registered.",
                            skill=skill,
                            path=_relative(REGISTRY_PATH),
                        )
                    )
            elif route.startswith("workflow:"):
                workflow = route.split(":", 1)[1]
                if workflow not in workflows:
                    issues.append(
                        Issue(
                            code="workflow_route_missing",
                            detail=f"Workflow {workflow!r} is absent from docs/workflow-index.md.",
                            skill=skill,
                            path=_relative(WORKFLOW_INDEX),
                        )
                    )
            else:
                issues.append(
                    Issue(
                        code="invalid_route",
                        detail=f"Route {route!r} must use workflow: or support:.",
                        skill=skill,
                        path=_relative(REGISTRY_PATH),
                    )
                )

        projected = registry_projection.get(skill)
        if projected:
            projected_role, projected_domain, projected_route = projected
            expected_workflows = [
                route.split(":", 1)[1]
                for route in routes
                if route.startswith("workflow:")
            ]
            expected_route = expected_workflows[0] if expected_workflows else "support"
            if projected_role != role:
                issues.append(
                    Issue(
                        code="registry_role_drift",
                        detail=f"Projection role {projected_role!r} != canonical {role!r}.",
                        skill=skill,
                        path=_relative(SKILL_REGISTRY_DOC),
                    )
                )
            if projected_domain != metadata.get("domain"):
                issues.append(
                    Issue(
                        code="registry_domain_drift",
                        detail=(
                            f"Projection domain {projected_domain!r} != "
                            f"canonical {metadata.get('domain')!r}."
                        ),
                        skill=skill,
                        path=_relative(SKILL_REGISTRY_DOC),
                    )
                )
            if projected_route != expected_route:
                issues.append(
                    Issue(
                        code="registry_route_drift",
                        detail=(
                            f"Projection route {projected_route!r} != canonical "
                            f"{expected_route!r}."
                        ),
                        skill=skill,
                        path=_relative(SKILL_REGISTRY_DOC),
                    )
                )

        for route in routes:
            if not route.startswith("workflow:"):
                continue
            workflow = route.split(":", 1)[1]
            expected_detail = f".claude/skills/{skill}/SKILL.md"
            projected = workflow_projection.get(workflow)
            if not projected:
                continue
            projected_usage, projected_detail = projected
            expected_usage = workflow_usage.get(workflow)
            if projected_usage != expected_usage:
                issues.append(
                    Issue(
                        code="workflow_usage_drift",
                        detail=(
                            f"Workflow {workflow!r} usage {projected_usage!r} != "
                            f"canonical {expected_usage!r}."
                        ),
                        skill=skill,
                        path=_relative(WORKFLOW_INDEX),
                    )
                )
            if projected_detail != expected_detail:
                issues.append(
                    Issue(
                        code="workflow_detail_drift",
                        detail=(
                            f"Workflow {workflow!r} points to {projected_detail!r}; "
                            f"expected {expected_detail!r}."
                        ),
                        skill=skill,
                        path=_relative(WORKFLOW_INDEX),
                    )
                )

        unknown_contracts = set(skill_contracts.get(skill, [])) - set(contract_tokens)
        for contract in sorted(unknown_contracts):
            issues.append(
                Issue(
                    code="unknown_contract",
                    detail=f"Contract {contract!r} has no contract token.",
                    skill=skill,
                    path=_relative(REGISTRY_PATH),
                )
            )

    for skill in sorted(actual):
        skill_dir = SKILLS_DIR / skill
        skill_md = skill_dir / "SKILL.md"
        fields, fm_issues = _frontmatter(skill_md)
        issues.extend(fm_issues)
        if fields.get("name") != skill:
            issues.append(
                Issue(
                    code="name_mismatch",
                    detail=f"Frontmatter name {fields.get('name')!r} must match the directory.",
                    skill=skill,
                    path=_relative(skill_md),
                )
            )
        description = fields.get("description", "").strip()
        if not description:
            issues.append(
                Issue(
                    code="description_missing",
                    detail="Frontmatter description is required.",
                    skill=skill,
                    path=_relative(skill_md),
                )
            )
        elif len(description) > MAX_DESCRIPTION_CHARS:
            issues.append(
                Issue(
                    code="description_too_long",
                    detail=(
                        f"Description has {len(description)} characters; "
                        f"maximum is {MAX_DESCRIPTION_CHARS}."
                    ),
                    skill=skill,
                    path=_relative(skill_md),
                )
            )
        for dynamic_field in ("model", "effort"):
            if dynamic_field in fields:
                issues.append(
                    Issue(
                        code="static_runtime_routing",
                        detail=(
                            f"Frontmatter {dynamic_field!r} duplicates dynamic routing; "
                            "resolve it from config/models.json and scripts/model_router.py."
                        ),
                        skill=skill,
                        path=_relative(skill_md),
                    )
                )

        line_count = len(skill_md.read_text(encoding="utf-8").splitlines())
        if line_count > MAX_SKILL_LINES:
            issues.append(
                Issue(
                    code="skill_too_long",
                    detail=f"SKILL.md has {line_count} lines; maximum is {MAX_SKILL_LINES}.",
                    skill=skill,
                    path=_relative(skill_md),
                )
            )

        combined_parts: list[str] = []
        for md_path in _iter_skill_markdown(skill_dir):
            text = md_path.read_text(encoding="utf-8")
            combined_parts.append(text)
            for code, pattern, detail in FORBIDDEN_PATTERNS:
                for match in pattern.finditer(text):
                    issues.append(
                        Issue(
                            code=code,
                            detail=detail,
                            skill=skill,
                            path=_relative(md_path),
                            line=_line_number(text, match.start()),
                        )
                    )
        combined = "\n".join(combined_parts)
        for contract in skill_contracts.get(skill, []):
            token = contract_tokens.get(contract)
            if token and token not in combined:
                issues.append(
                    Issue(
                        code="contract_reference_missing",
                        detail=f"Skill does not point to canonical {contract!r} owner {token}.",
                        skill=skill,
                        path=_relative(skill_md),
                    )
                )

    return issues


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit a JSON report.")
    return parser


def main() -> int:
    args = _parser().parse_args()
    issues = collect_issues()
    report = {
        "schema_version": 1,
        "ok": not issues,
        "skills_total": len(list(SKILLS_DIR.glob("*/SKILL.md"))),
        "registry_path": _relative(REGISTRY_PATH),
        "issues": [asdict(issue) for issue in issues],
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    elif issues:
        print(f"Skill architecture: FAIL ({len(issues)} issue(s))")
        for issue in issues:
            location = issue.path or "<unknown>"
            if issue.line is not None:
                location = f"{location}:{issue.line}"
            skill = f"[{issue.skill}] " if issue.skill else ""
            print(f"- {issue.code}: {skill}{location}: {issue.detail}")
    else:
        print(f"Skill architecture: PASS ({report['skills_total']} skills)")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
