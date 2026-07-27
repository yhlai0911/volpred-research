from __future__ import annotations

import json
from pathlib import Path

import volpred.ops.frontend_parity as parity_module
from volpred.ops.frontend_parity import audit_frontend_parity


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fixture_repo(tmp_path: Path) -> tuple[Path, Path]:
    frontend = tmp_path / "web"
    _write(frontend / "src/app/page.tsx", '<a href="/reports/demo">report</a>')
    _write(frontend / "src/app/v3/page.tsx", "export default function Page() {}")
    _write(frontend / "src/app/reports/[id]/page.tsx")
    _write(frontend / "src/app/v3/reports/[id]/page.tsx")
    _write(frontend / "src/lib/feed.ts")
    _write(frontend / "src/components/MobileNav.tsx", 'aria-label="mobile"')
    _write(frontend / "src/app/sitemap.ts")
    _write(frontend / "public/robots.txt")
    targets = {
        "active_frontend": "web",
        "frontends": {"web": {"path": "web", "kind": "nextjs"}},
    }
    _write(
        tmp_path / "config/project_targets.json",
        json.dumps(targets),
    )
    contract = {
        "schema_version": "frontend-route-scenario-parity.v1",
        "frontend_target": "web",
        "source_revision_policy": {"nested_git_required": False},
        "required_scenario_ids": [
            "public_first_paint",
            "auth_callback",
            "member_navigation",
            "admin_observer",
            "seo",
            "mobile_navigation",
            "accessibility_navigation",
        ],
        "route_rules": [
            {
                "id": "home",
                "pattern": "^/$",
                "expected_modes": ["original", "v3"],
                "access": "public",
                "authoritative_data_owner_refs": {
                    "original": ["$surface", "web/src/lib/feed.ts"],
                    "v3": ["$surface", "web/src/lib/feed.ts"],
                },
                "capabilities": ["feed"],
                "mode_advantages": {
                    "original": ["authoritative_first_paint"],
                    "v3": ["editorial_navigation"],
                },
            },
            {
                "id": "report",
                "pattern": "^/reports/\\[id\\]$",
                "expected_modes": ["original", "v3"],
                "access": "public",
                "authoritative_data_owner_refs": {
                    "original": ["$surface", "web/src/lib/feed.ts"],
                    "v3": ["$surface", "web/src/lib/feed.ts"],
                },
                "capabilities": ["report_detail"],
                "mode_advantages": {
                    "original": ["legacy_reader"],
                    "v3": ["editorial_reader"],
                },
            },
            {
                "id": "seo",
                "pattern": "^/(sitemap\\.xml|robots\\.txt)$",
                "expected_modes": ["shared"],
                "access": "public",
                "authoritative_data_owner_refs": {
                    "shared": ["$surface"],
                },
                "capabilities": ["discovery_metadata"],
                "mode_advantages": {
                    "shared": ["single_shared_contract"],
                },
            },
        ],
        "scenarios": [
            {
                "id": scenario_id,
                "required_route_rules": ["home"],
                "required_modes": ["original", "v3"],
                "evidence": [
                    {
                        "path": "web/src/components/MobileNav.tsx",
                        "contains": ["aria-label"],
                    }
                ],
            }
            for scenario_id in (
                "public_first_paint",
                "auth_callback",
                "member_navigation",
                "admin_observer",
                "seo",
                "mobile_navigation",
                "accessibility_navigation",
            )
        ],
    }
    contract_path = tmp_path / "config/frontend_route_scenario_parity.json"
    _write(contract_path, json.dumps(contract))
    return contract_path, tmp_path / "config/project_targets.json"


def test_audit_builds_unique_inventory_and_matches_dynamic_links(
    tmp_path: Path,
) -> None:
    contract, targets = _fixture_repo(tmp_path)

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    assert report["status"] == "passed"
    assert report["blockers"] == []
    home_rows = [
        row
        for row in report["routes"]
        if row["canonical_route"] == "/"
    ]
    assert {
        (row["mode"], tuple(row["capabilities"]))
        for row in home_rows
    } == {
        ("original", ("feed",)),
        ("v3", ("feed",)),
    }
    assert {
        (row["mode"], tuple(row["advantages"]))
        for row in home_rows
    } == {
        ("original", ("authoritative_first_paint",)),
        ("v3", ("editorial_navigation",)),
    }
    assert report["source_revision"]["tree_sha256"]
    assert report["summary"] == {
        "route_count": 6,
        "rule_count": 3,
        "scenario_count": 7,
        "known_gap_count": 0,
        "blocker_count": 0,
    }


def test_unknown_route_and_missing_mode_are_blockers(tmp_path: Path) -> None:
    contract, targets = _fixture_repo(tmp_path)
    _write(tmp_path / "web/src/app/pricing/page.tsx")
    (tmp_path / "web/src/app/v3/reports/[id]/page.tsx").unlink()

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    assert report["status"] == "blocked"
    assert {item["kind"] for item in report["blockers"]} >= {
        "unknown_route",
        "missing_mode",
    }


def test_explicit_known_gap_is_reported_but_not_silently_blocked(
    tmp_path: Path,
) -> None:
    contract, targets = _fixture_repo(tmp_path)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["route_rules"][1]["mode_dispositions"] = {
        "v3": {
            "status": "known_gap",
            "reason": "tracked by the first-paint ticket",
        }
    }
    contract.write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "web/src/app/v3/reports/[id]/page.tsx").unlink()

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    assert report["status"] == "passed"
    assert report["known_gaps"][0]["rule_id"] == "report"
    assert report["known_gaps"][0]["mode"] == "v3"


def test_duplicate_rule_missing_owner_and_dead_link_fail_closed(
    tmp_path: Path,
) -> None:
    contract, targets = _fixture_repo(tmp_path)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["route_rules"].append(
        {
            "id": "duplicate-home",
            "pattern": "^/$",
                "expected_modes": ["original", "v3"],
                "access": "public",
                "authoritative_data_owner_refs": {
                    "original": ["$surface", "web/src/lib/missing.ts"],
                    "v3": ["$surface"],
                },
                "capabilities": ["duplicate"],
                "mode_advantages": {
                    "original": ["none"],
                    "v3": ["none"],
                },
        }
    )
    contract.write_text(json.dumps(payload), encoding="utf-8")
    _write(
        tmp_path / "web/src/components/Broken.tsx",
        '<a href="/does-not-exist">broken</a>',
    )

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    assert report["status"] == "blocked"
    assert {item["kind"] for item in report["blockers"]} >= {
        "duplicate_route_owner",
        "missing_owner_ref",
        "dead_internal_link",
    }


def test_scenario_evidence_and_active_target_drift_fail_closed(
    tmp_path: Path,
) -> None:
    contract, targets = _fixture_repo(tmp_path)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["frontend_target"] = "other"
    payload["scenarios"][0]["evidence"][0]["contains"] = ["aria-expanded"]
    contract.write_text(json.dumps(payload), encoding="utf-8")

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    assert report["status"] == "blocked"
    assert {item["kind"] for item in report["blockers"]} >= {
        "active_target_drift",
        "scenario_evidence_mismatch",
    }


def test_contract_schema_drift_fails_closed(tmp_path: Path) -> None:
    contract, targets = _fixture_repo(tmp_path)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["schema_version"] = "frontend-route-scenario-parity.v0"
    contract.write_text(json.dumps(payload), encoding="utf-8")

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    assert report["status"] == "blocked"
    assert report["blockers"][0]["kind"] == "contract_schema"


def test_malformed_nested_json_returns_typed_blockers(tmp_path: Path) -> None:
    contract, targets = _fixture_repo(tmp_path)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["route_rules"][0]["expected_modes"] = [{"not": "hashable"}]
    payload["scenarios"][0]["required_route_rules"] = [{"not": "hashable"}]
    payload["scenarios"][0]["evidence"][0]["contains"] = None
    contract.write_text(json.dumps(payload), encoding="utf-8")

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    assert report["status"] == "blocked"
    assert {item["kind"] for item in report["blockers"]} >= {
        "contract_expected_modes",
        "scenario_coverage_contract",
        "scenario_evidence_contract",
    }
    targets.write_text(
        json.dumps({"active_frontend": "web", "frontends": []}),
        encoding="utf-8",
    )
    target_report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )
    assert any(
        item["kind"] == "project_targets_schema"
        for item in target_report["blockers"]
    )


def test_repo_path_traversal_and_symlink_escape_fail_closed(
    tmp_path: Path,
) -> None:
    contract, targets = _fixture_repo(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    _write(outside / "owner.ts")
    (tmp_path / "escaped-owner.ts").symlink_to(outside / "owner.ts")
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["route_rules"][0]["authoritative_data_owner_refs"] = {
        "original": ["$surface", "escaped-owner.ts", "../outside-owner.ts"],
        "v3": ["$surface"],
    }
    payload["scenarios"][0]["evidence"][0]["path"] = str(
        outside / "owner.ts"
    )
    contract.write_text(json.dumps(payload), encoding="utf-8")

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    escapes = [
        item for item in report["blockers"] if item["kind"] == "path_escape"
    ]
    assert {item["field"] for item in escapes} >= {
        "authoritative_data_owner_ref",
        "scenario_evidence",
    }


def test_active_frontend_path_cannot_escape_repo(tmp_path: Path) -> None:
    contract, targets = _fixture_repo(tmp_path)
    target_payload = json.loads(targets.read_text(encoding="utf-8"))
    target_payload["frontends"]["web"]["path"] = "../external-web"
    targets.write_text(json.dumps(target_payload), encoding="utf-8")

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    assert report["status"] == "blocked"
    assert any(
        item["kind"] == "path_escape"
        and item["field"] == "active_frontend"
        for item in report["blockers"]
    )


def test_required_scenario_taxonomy_cannot_be_deleted_or_emptied(
    tmp_path: Path,
) -> None:
    contract, targets = _fixture_repo(tmp_path)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["scenarios"] = []
    contract.write_text(json.dumps(payload), encoding="utf-8")

    missing = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    assert any(
        item["kind"] == "missing_required_scenario"
        and item["scenario_id"] == "mobile_navigation"
        for item in missing["blockers"]
    )

    contract, targets = _fixture_repo(tmp_path)
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["scenarios"][0]["required_route_rules"] = []
    payload["scenarios"][0]["required_modes"] = []
    payload["scenarios"][0]["evidence"] = []
    contract.write_text(json.dumps(payload), encoding="utf-8")
    empty = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )
    assert {item["kind"] for item in empty["blockers"]} >= {
        "scenario_coverage_contract",
        "scenario_evidence_contract",
    }


def test_unresolved_navigation_expression_fails_closed(tmp_path: Path) -> None:
    contract, targets = _fixture_repo(tmp_path)
    _write(
        tmp_path / "web/src/components/VariableLink.tsx",
        "const href = '/missing'; export const X = () => <a href={href}>x</a>;",
    )

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    assert any(
        item["kind"] == "unresolved_internal_navigation"
        and item["source_ref"].endswith("VariableLink.tsx")
        for item in report["blockers"]
    )


def test_api_links_use_real_dynamic_route_inventory(tmp_path: Path) -> None:
    contract, targets = _fixture_repo(tmp_path)
    _write(
        tmp_path / "web/src/app/api/jobs/[id]/route.ts",
        "export async function GET() { return Response.json({}); }",
    )
    _write(
        tmp_path / "web/src/components/ApiLinks.tsx",
        '<a href="/api/jobs/123">ok</a><a href="/api/missing">bad</a>',
    )
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["route_rules"].append(
        {
            "id": "api_jobs",
            "pattern": "^/api/jobs/\\[id\\]$",
            "expected_modes": ["shared"],
            "access": "service",
            "method_access": {"GET": "service"},
            "authoritative_data_owner_refs": {"shared": ["$surface"]},
            "capabilities": ["job_read"],
            "mode_advantages": {
                "shared": ["single_api_contract"],
            },
        }
    )
    contract.write_text(json.dumps(payload), encoding="utf-8")

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    dead_paths = {
        item["path"]
        for item in report["blockers"]
        if item["kind"] == "dead_internal_link"
    }
    assert dead_paths == {"/api/missing"}


def test_route_handler_access_is_classified_per_http_method(
    tmp_path: Path,
) -> None:
    contract, targets = _fixture_repo(tmp_path)
    _write(
        tmp_path / "web/src/app/api/questions/route.ts",
        """
        export async function GET() { return Response.json([]); }
        export async function POST() { return Response.json({}); }
        """,
    )
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["route_rules"].append(
        {
            "id": "api_questions",
            "pattern": "^/api/questions$",
            "expected_modes": ["shared"],
            "access": "public",
            "method_access": {"GET": "public", "POST": "member"},
            "authoritative_data_owner_refs": {"shared": ["$surface"]},
            "capabilities": ["question_read", "question_write"],
            "mode_advantages": {"shared": ["single_api_contract"]},
        }
    )
    contract.write_text(json.dumps(payload), encoding="utf-8")

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    rows = [
        row for row in report["routes"]
        if row["canonical_route"] == "/api/questions"
    ]
    assert {(row["method"], row["access"]) for row in rows} == {
        ("GET", "public"),
        ("POST", "member"),
    }


def test_route_handler_without_method_contract_fails_closed(
    tmp_path: Path,
) -> None:
    contract, targets = _fixture_repo(tmp_path)
    _write(
        tmp_path / "web/src/app/api/jobs/route.ts",
        "export async function POST() { return Response.json({}); }",
    )
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["route_rules"].append(
        {
            "id": "api_jobs",
            "pattern": "^/api/jobs$",
            "expected_modes": ["shared"],
            "access": "service",
            "authoritative_data_owner_refs": {"shared": ["$surface"]},
            "capabilities": ["job_write"],
            "mode_advantages": {"shared": ["single_api_contract"]},
        }
    )
    contract.write_text(json.dumps(payload), encoding="utf-8")

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    assert any(
        item["kind"] == "missing_method_access"
        and item["route"] == "/api/jobs"
        and item["method"] == "POST"
        for item in report["blockers"]
    )


def test_declared_http_method_must_still_be_exported(tmp_path: Path) -> None:
    contract, targets = _fixture_repo(tmp_path)
    _write(
        tmp_path / "web/src/app/api/questions/route.ts",
        "export async function GET() { return Response.json([]); }",
    )
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["route_rules"].append(
        {
            "id": "api_questions",
            "pattern": "^/api/questions$",
            "expected_modes": ["shared"],
            "access": "public",
            "method_access": {"GET": "public", "POST": "member"},
            "authoritative_data_owner_refs": {"shared": ["$surface"]},
            "capabilities": ["questions"],
            "mode_advantages": {"shared": ["single_api_contract"]},
        }
    )
    contract.write_text(json.dumps(payload), encoding="utf-8")

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    assert any(
        item["kind"] == "missing_route_handler_method"
        and item["methods"] == ["POST"]
        for item in report["blockers"]
    )


def test_declared_methods_are_required_on_each_handler_surface(
    tmp_path: Path,
) -> None:
    contract, targets = _fixture_repo(tmp_path)
    _write(
        tmp_path / "web/src/app/api/jobs/route.ts",
        "export async function GET() { return Response.json({}); }",
    )
    _write(
        tmp_path / "web/src/app/v3/api/jobs/route.ts",
        "export async function POST() { return Response.json({}); }",
    )
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["route_rules"].append(
        {
            "id": "api_jobs",
            "pattern": "^/api/jobs$",
            "expected_modes": ["shared", "v3"],
            "access": "service",
            "method_access": {"GET": "service", "POST": "service"},
            "authoritative_data_owner_refs": {
                "shared": ["$surface"],
                "v3": ["$surface"],
            },
            "capabilities": ["jobs"],
            "mode_advantages": {
                "shared": ["shared_handler"],
                "v3": ["v3_handler"],
            },
        }
    )
    contract.write_text(json.dumps(payload), encoding="utf-8")

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    gaps = {
        (item["mode"], tuple(item["methods"]))
        for item in report["blockers"]
        if item["kind"] == "missing_route_handler_method"
    }
    assert gaps == {("shared", ("POST",)), ("v3", ("GET",))}


def test_http_method_discovery_ignores_text_and_supports_alias_export(
    tmp_path: Path,
) -> None:
    contract, targets = _fixture_repo(tmp_path)
    _write(
        tmp_path / "web/src/app/api/jobs/route.ts",
        """
        // export async function DELETE() {}
        const example = "export async function PATCH() {}"
        async function readJob() { return Response.json({}); }
        export { readJob as GET }
        """,
    )
    payload = json.loads(contract.read_text(encoding="utf-8"))
    payload["route_rules"].append(
        {
            "id": "api_jobs",
            "pattern": "^/api/jobs$",
            "expected_modes": ["shared"],
            "access": "service",
            "method_access": {"GET": "service"},
            "authoritative_data_owner_refs": {"shared": ["$surface"]},
            "capabilities": ["job_read"],
            "mode_advantages": {"shared": ["single_api_contract"]},
        }
    )
    contract.write_text(json.dumps(payload), encoding="utf-8")

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    rows = [
        row for row in report["routes"]
        if row["canonical_route"] == "/api/jobs"
    ]
    assert [(row["method"], row["access"]) for row in rows] == [
        ("GET", "service")
    ]


def test_multiline_router_navigation_is_audited(tmp_path: Path) -> None:
    contract, targets = _fixture_repo(tmp_path)
    _write(
        tmp_path / "web/src/components/RouterLinks.tsx",
        """
        const router =
          useRouter()
        router.push(
          "/reports/demo"
        )
        router.replace(
          target
        )
        """,
    )

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    unresolved = [
        item for item in report["blockers"]
        if item["kind"] == "unresolved_internal_navigation"
        and item["source_ref"].endswith("RouterLinks.tsx")
    ]
    assert [item["expression"] for item in unresolved] == ["target"]


def test_typed_destructured_and_direct_router_navigation_fail_closed(
    tmp_path: Path,
) -> None:
    contract, targets = _fixture_repo(tmp_path)
    _write(
        tmp_path / "web/src/components/RouterVariants.tsx",
        """
        const typed: AppRouterInstance = useRouter()
        typed.push(typedTarget)
        const { push: navigate, replace } = useRouter()
        navigate(destructuredTarget)
        replace("/reports/demo")
        useRouter().push(directTarget)
        """,
    )

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    unresolved = {
        item["expression"]
        for item in report["blockers"]
        if item["kind"] == "unresolved_internal_navigation"
        and item["source_ref"].endswith("RouterVariants.tsx")
    }
    assert unresolved == {
        "typedTarget",
        "destructuredTarget",
        "directTarget",
    }


def test_router_options_and_next_redirects_are_audited(tmp_path: Path) -> None:
    contract, targets = _fixture_repo(tmp_path)
    _write(
        tmp_path / "web/src/components/Redirects.tsx",
        """
        import {
          redirect,
          permanentRedirect,
        } from "next/navigation"
        const router = useRouter()
        router.push("/reports/demo", { scroll: false })
        redirect(redirectTarget)
        permanentRedirect("/reports/demo")
        // redirect(commentTarget)
        """,
    )

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    unresolved = [
        item["expression"]
        for item in report["blockers"]
        if item["kind"] == "unresolved_internal_navigation"
        and item["source_ref"].endswith("Redirects.tsx")
    ]
    assert unresolved == ["redirectTarget"]


def test_router_indirection_and_navigation_import_alias_fail_closed(
    tmp_path: Path,
) -> None:
    contract, targets = _fixture_repo(tmp_path)
    _write(
        tmp_path / "web/src/components/RouterAliases.tsx",
        """
        import { redirect as navigate } from "next/navigation"
        const router = useRouter()
        const alias = router
        alias.push(aliasTarget)
        router?.push(optionalTarget)
        router["replace"](bracketTarget)
        navigate(redirectTarget)
        """,
    )

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    scoped = [
        item
        for item in report["blockers"]
        if str(item.get("source_ref", "")).endswith("RouterAliases.tsx")
    ]
    assert any(
        item["kind"] == "unresolved_router_reference"
        and item["symbol"] == "router"
        for item in scoped
    )
    assert any(
        item["kind"] == "unresolved_internal_navigation"
        and item["expression"] == "redirectTarget"
        for item in scoped
    )


def test_namespace_navigation_and_reexport_cannot_silently_pass(
    tmp_path: Path,
) -> None:
    contract, targets = _fixture_repo(tmp_path)
    _write(
        tmp_path / "web/src/components/NamespaceNavigation.tsx",
        """
        import * as nav from "next/navigation"
        nav.redirect(namespaceTarget)
        """,
    )
    _write(
        tmp_path / "web/src/lib/navigation-export.ts",
        """
        export {
          redirect as navigate,
        } from "next/navigation"
        """,
    )
    _write(
        tmp_path / "web/src/lib/navigation-export-all.ts",
        """
        export *
        from "next/navigation"
        """,
    )
    _write(
        tmp_path / "web/src/lib/navigation-export-namespace.ts",
        """
        export *
        as navigation
        from "next/navigation"
        """,
    )

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    assert any(
        item["kind"] == "unresolved_internal_navigation"
        and item["expression"] == "namespaceTarget"
        for item in report["blockers"]
    )
    assert any(
        item["kind"] == "unsupported_next_navigation_binding"
        and item["source_ref"].endswith("navigation-export.ts")
        for item in report["blockers"]
    )
    assert any(
        item["kind"] == "unsupported_next_navigation_binding"
        and item["source_ref"].endswith("navigation-export-all.ts")
        for item in report["blockers"]
    )
    assert any(
        item["kind"] == "unsupported_next_navigation_binding"
        and item["source_ref"].endswith("navigation-export-namespace.ts")
        for item in report["blockers"]
    )


def test_unrecognized_use_router_shape_cannot_silently_pass(
    tmp_path: Path,
) -> None:
    contract, targets = _fixture_repo(tmp_path)
    _write(
        tmp_path / "web/src/components/RouterEscape.tsx",
        "const routers = [useRouter()]; routers[0].push(target)",
    )

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    assert any(
        item["kind"] == "unresolved_router_binding"
        and item["source_ref"].endswith("RouterEscape.tsx")
        for item in report["blockers"]
    )


def test_redirect_and_href_examples_in_non_code_do_not_change_results(
    tmp_path: Path,
) -> None:
    contract, targets = _fixture_repo(tmp_path)
    _write(
        tmp_path / "web/next.config.js",
        """
        // { source: '/retired', destination: '/' }
        const example = "source: '/retired'"
        module.exports = { async redirects() { return [] } }
        """,
    )
    _write(
        tmp_path / "web/src/components/Examples.tsx",
        """
        // <Link href="/comment-only" />
        const docs = '<a href="/string-only">example</a>'
        export const Real = () => <a href="/retired">retired</a>
        """,
    )

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    dead_paths = {
        item["path"]
        for item in report["blockers"]
        if item["kind"] == "dead_internal_link"
    }
    assert dead_paths == {"/retired"}


def test_frontend_source_symlink_escape_fails_closed(tmp_path: Path) -> None:
    contract, targets = _fixture_repo(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-source-outside"
    _write(outside / "page.tsx", "export default function Page() {}")
    escaped = tmp_path / "web/src/app/escaped/page.tsx"
    escaped.parent.mkdir(parents=True, exist_ok=True)
    escaped.symlink_to(outside / "page.tsx")

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    assert any(
        item["kind"] == "frontend_source_escape"
        and item["source_ref"].endswith("escaped/page.tsx")
        for item in report["blockers"]
    )


def test_frontend_reader_uses_resolved_path_after_symlink_check(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _contract, _targets = _fixture_repo(tmp_path)
    inside = tmp_path / "web/src/components/Inside.tsx"
    outside = tmp_path.parent / f"{tmp_path.name}-swap-outside.tsx"
    _write(inside, "export const X = () => null")
    _write(outside, '<a href="/external-after-check">outside</a>')
    link = tmp_path / "web/src/components/Swappable.tsx"
    link.symlink_to(inside)
    original = parity_module._safe_frontend_file
    swapped = False

    def swap_after_resolve(path: Path, **kwargs):
        nonlocal swapped
        resolved = original(path, **kwargs)
        if path == link and resolved is not None and not swapped:
            link.unlink()
            link.symlink_to(outside)
            swapped = True
        return resolved

    monkeypatch.setattr(
        parity_module,
        "_safe_frontend_file",
        swap_after_resolve,
    )
    routes = parity_module._discover_routes(
        tmp_path,
        tmp_path / "web",
        [],
    )

    findings = parity_module._dead_links(
        tmp_path,
        tmp_path / "web",
        routes,
    )

    assert not any(
        item.get("path") == "/external-after-check"
        for item in findings
    )


def test_source_mutation_during_audit_invalidates_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    contract, targets = _fixture_repo(tmp_path)
    original = parity_module._discover_routes

    def mutate_then_discover(
        repo_root: Path,
        frontend_root: Path,
        blockers: list[dict[str, object]],
    ):
        _write(frontend_root / "src/app/late/page.tsx")
        return original(repo_root, frontend_root, blockers)

    monkeypatch.setattr(
        parity_module,
        "_discover_routes",
        mutate_then_discover,
    )

    report = audit_frontend_parity(
        repo_root=tmp_path,
        contract_path=contract,
        targets_path=targets,
    )

    assert report["source_revision"]["stable"] is False
    assert any(
        item["kind"] == "frontend_source_drift"
        for item in report["blockers"]
    )
