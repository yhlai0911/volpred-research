from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts import check_skill_architecture


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_skill_architecture.py"


def test_project_skills_match_the_active_architecture_contract() -> None:
    completed = subprocess.run(
        [sys.executable, str(CHECKER), "--json"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)
    assert completed.returncode == 0, json.dumps(
        report["issues"],
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    assert report["ok"] is True
    assert report["skills_total"] == len(
        json.loads((ROOT / "config" / "skill_registry.json").read_text())["skills"]
    )


def test_supervisor_dispatch_is_an_exact_registry_projection() -> None:
    registry = json.loads((ROOT / "config" / "skill_registry.json").read_text())
    supervisor = json.loads((ROOT / "config" / "supervisor_rules.json").read_text())

    assert supervisor["skill_dispatch_table"]["by_task_family"] == (
        registry["supervisor_dispatch"]["by_task_family"]
    )
    assert supervisor["skill_dispatch_table"]["by_context"] == (
        registry["supervisor_dispatch"]["by_context"]
    )
    actual_seeds = {
        row["id"]: row["skill"]
        for row in supervisor["seed_sources_priority"]["order"]
        if "skill" in row
    }
    assert actual_seeds == registry["supervisor_dispatch"]["seed_sources_priority"]


def test_supervisor_dispatch_rejects_wrong_registered_primary_and_empty_route() -> None:
    registered = {
        "research-owner": {"routes": ["workflow:research-design"]},
        "wrong-owner": {"routes": ["workflow:deploy-frontend"]},
    }
    issues = check_skill_architecture._supervisor_route_group_issues(
        route_group="by_task_family",
        routes={"research": ["wrong-owner"], "content": []},
        expected_routes={"research": ["wrong-owner"], "content": []},
        required_skill_sequences={
            "research": ["research-owner"],
            "content": ["content-owner"],
        },
        required_route_sequences={
            "research": ["workflow:research-design"],
            "content": ["workflow:feed-publish"],
        },
        required_role_sequences={
            "research": ["orchestrator"],
            "content": ["orchestrator"],
        },
        registered=registered,
    )

    assert {issue.code for issue in issues} >= {
        "supervisor_route_owner_mismatch",
        "supervisor_route_empty",
    }


def test_supervisor_dispatch_rejects_appended_secondary_skill() -> None:
    registered = {
        "content-owner": {
            "role": "orchestrator",
            "routes": ["workflow:feed-publish"],
        },
        "candidate-owner": {"role": "leaf", "routes": ["workflow:publication-scan"]},
        "wrong-extra": {"role": "leaf", "routes": ["workflow:deploy-frontend"]},
    }
    routes = {
        "content": ["content-owner", "candidate-owner", "wrong-extra"],
    }
    issues = check_skill_architecture._supervisor_route_group_issues(
        route_group="by_task_family",
        routes=routes,
        expected_routes=routes,
        required_skill_sequences={
            "content": ["content-owner", "candidate-owner"],
        },
        required_route_sequences={
            "content": ["workflow:feed-publish", "workflow:publication-scan"],
        },
        required_role_sequences={
            "content": ["orchestrator", "leaf"],
        },
        registered=registered,
    )

    assert "supervisor_route_arity_mismatch" in {issue.code for issue in issues}


def test_supervisor_dispatch_rejects_same_route_wrong_role_owner() -> None:
    registered = {
        "compatibility-owner": {
            "role": "compatibility",
            "routes": ["support:paper-submission-pipeline"],
        },
        "leaf-with-same-route": {
            "role": "leaf",
            "routes": ["support:paper-submission-pipeline"],
        },
    }
    routes = {"paper_stage_decision": ["leaf-with-same-route"]}
    issues = check_skill_architecture._supervisor_route_group_issues(
        route_group="by_context",
        routes=routes,
        expected_routes=routes,
        required_skill_sequences={
            "paper_stage_decision": ["compatibility-owner"],
        },
        required_route_sequences={
            "paper_stage_decision": ["support:paper-submission-pipeline"],
        },
        required_role_sequences={
            "paper_stage_decision": ["compatibility"],
        },
        registered=registered,
    )

    assert "supervisor_role_owner_mismatch" in {issue.code for issue in issues}


def test_supervisor_dispatch_rejects_same_route_same_role_impostor() -> None:
    registered = {
        "canonical-owner": {
            "role": "compatibility",
            "routes": ["support:paper-submission-pipeline"],
        },
        "same-shape-impostor": {
            "role": "compatibility",
            "routes": ["support:paper-submission-pipeline"],
        },
    }
    routes = {"paper_stage_decision": ["same-shape-impostor"]}
    issues = check_skill_architecture._supervisor_route_group_issues(
        route_group="by_context",
        routes=routes,
        expected_routes=routes,
        required_skill_sequences={
            "paper_stage_decision": ["canonical-owner"],
        },
        required_route_sequences={
            "paper_stage_decision": ["support:paper-submission-pipeline"],
        },
        required_role_sequences={
            "paper_stage_decision": ["compatibility"],
        },
        registered=registered,
    )

    assert "supervisor_skill_sequence_mismatch" in {
        issue.code for issue in issues
    }


def test_supervisor_dispatch_rejects_non_list_owner_routes() -> None:
    registered = {
        "canonical-owner": {
            "role": "orchestrator",
            "routes": {"workflow:research-design": True},
        },
    }
    routes = {"research": ["canonical-owner"]}
    issues = check_skill_architecture._supervisor_route_group_issues(
        route_group="by_task_family",
        routes=routes,
        expected_routes=routes,
        required_skill_sequences={"research": ["canonical-owner"]},
        required_route_sequences={"research": ["workflow:research-design"]},
        required_role_sequences={"research": ["orchestrator"]},
        registered=registered,
    )

    assert "supervisor_owner_routes_invalid" in {
        issue.code for issue in issues
    }


def test_registry_routes_and_contracts_require_unique_string_lists() -> None:
    routes, contracts, issues = check_skill_architecture._registry_skill_lists(
        {
            "invalid-shape": {
                "routes": {"workflow:research-design": True},
                "contracts": "task_pool",
            },
            "duplicates": {
                "routes": ["workflow:research-design", "workflow:research-design"],
                "contracts": ["task_pool", "task_pool"],
            },
        }
    )

    assert routes["invalid-shape"] == []
    assert contracts["invalid-shape"] == []
    assert {issue.code for issue in issues} == {
        "registry_routes_invalid",
        "registry_contracts_invalid",
        "registry_routes_duplicate",
        "registry_contracts_duplicate",
    }


def test_supervisor_seed_rejects_wrong_registered_owner() -> None:
    registered = {
        "member-owner": {"role": "leaf", "routes": ["workflow:member-qa"]},
        "wrong-owner": {"role": "leaf", "routes": ["workflow:deploy-frontend"]},
        "publication-owner": {
            "role": "leaf",
            "routes": ["workflow:publication-scan"],
        },
    }
    seeds = {
        "member_qa_ranking": "wrong-owner",
        "publication_candidates": "publication-owner",
    }
    issues = check_skill_architecture._supervisor_seed_issues(
        actual_seeds=seeds,
        expected_seeds=seeds,
        registered=registered,
    )

    assert "supervisor_seed_owner_mismatch" in {issue.code for issue in issues}


def test_supervisor_seed_rejects_same_shape_impostor() -> None:
    registered = {
        "same-shape-impostor": {
            "role": "leaf",
            "routes": ["workflow:member-qa"],
        },
        "publication-candidates": {
            "role": "leaf",
            "routes": ["workflow:publication-scan"],
        },
    }
    seeds = {
        "member_qa_ranking": "same-shape-impostor",
        "publication_candidates": "publication-candidates",
    }
    issues = check_skill_architecture._supervisor_seed_issues(
        actual_seeds=seeds,
        expected_seeds=seeds,
        registered=registered,
    )

    assert "supervisor_seed_identity_mismatch" in {
        issue.code for issue in issues
    }


def test_supervisor_seed_ids_are_unique_across_all_rows() -> None:
    actual, issues = check_skill_architecture._parse_skill_backed_seeds(
        [
            {"id": "member_qa_ranking", "source": "first"},
            {"id": "member_qa_ranking", "skill": "member-questions"},
        ]
    )

    assert actual == {"member_qa_ranking": "member-questions"}
    assert "supervisor_seed_duplicate" in {issue.code for issue in issues}


def test_projection_markers_fail_closed_on_wrong_order() -> None:
    projected, issues = check_skill_architecture._marked_projection(
        "<!-- end -->\nbody\n<!-- start -->",
        "<!-- start -->",
        "<!-- end -->",
        path="projection.md",
    )

    assert projected == ""
    assert [issue.code for issue in issues] == ["projection_marker_order"]


def test_projection_markers_fail_closed_on_duplicates() -> None:
    projected, issues = check_skill_architecture._marked_projection(
        "<!-- start --><!-- start -->body<!-- end -->",
        "<!-- start -->",
        "<!-- end -->",
        path="projection.md",
    )

    assert projected == ""
    assert [issue.code for issue in issues] == ["projection_marker_count"]


def test_duplicate_workflow_rows_fail_closed() -> None:
    rows, issues = check_skill_architecture._parse_workflow_projection(
        "\n".join(
            [
                "| Workflow ID | 使用時機 | Detail path |",
                "|---|---|---|",
                "| `research-design` | first | `.claude/skills/autonomous-research/SKILL.md` |",
                "| `research-design` | stale | `.claude/skills/deploy-frontend/SKILL.md` |",
            ]
        ),
        path="workflow-index.md",
    )

    assert rows["research-design"] == (
        "stale",
        ".claude/skills/deploy-frontend/SKILL.md",
    )
    assert [issue.code for issue in issues] == ["workflow_projection_duplicate"]


def test_malformed_workflow_projection_row_fails_closed() -> None:
    _rows, issues = check_skill_architecture._parse_workflow_projection(
        "\n".join(
            [
                "| Workflow ID | 使用時機 | Detail path |",
                "|---|---|---|",
                "| `phantom` | malformed row without detail |",
            ]
        ),
        path="workflow-index.md",
    )

    assert [issue.code for issue in issues] == ["workflow_projection_row_invalid"]


def test_workflow_projection_has_no_phantom_routes() -> None:
    registry = json.loads((ROOT / "config" / "skill_registry.json").read_text())
    projected, issues = check_skill_architecture._workflow_projection_rows()
    expected = {
        route.split(":", 1)[1]
        for metadata in registry["skills"].values()
        for route in metadata["routes"]
        if route.startswith("workflow:")
    }

    assert issues == []
    assert set(projected) == expected
    assert {workflow: usage for workflow, (usage, _path) in projected.items()} == (
        registry["workflow_usage"]
    )
