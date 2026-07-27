from __future__ import annotations

import json
from pathlib import Path

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
        "required_scenario_ids": ["mobile_navigation"],
        "route_rules": [
            {
                "id": "home",
                "pattern": "^/$",
                "expected_modes": ["original", "v3"],
                "access": "public",
                "authoritative_data_owner_refs": ["web/src/lib/feed.ts"],
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
                "authoritative_data_owner_refs": ["web/src/lib/feed.ts"],
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
                "authoritative_data_owner_refs": [
                    "web/src/app/sitemap.ts",
                    "web/public/robots.txt",
                ],
                "capabilities": ["discovery_metadata"],
                "mode_advantages": {
                    "shared": ["single_shared_contract"],
                },
            },
        ],
        "scenarios": [
            {
                "id": "mobile_navigation",
                "required_route_rules": ["home"],
                "required_modes": ["original", "v3"],
                "evidence": [
                    {
                        "path": "web/src/components/MobileNav.tsx",
                        "contains": ["aria-label"],
                    }
                ],
            }
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
        "scenario_count": 1,
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
                "authoritative_data_owner_refs": ["web/src/lib/missing.ts"],
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
    payload["route_rules"][0]["authoritative_data_owner_refs"] = [
        "escaped-owner.ts",
        "../outside-owner.ts",
    ]
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
