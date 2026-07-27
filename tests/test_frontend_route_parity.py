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
        "route_rules": [
            {
                "id": "home",
                "pattern": "^/$",
                "expected_modes": ["original", "v3"],
                "access": "public",
                "authoritative_data_owner_refs": ["web/src/lib/feed.ts"],
            },
            {
                "id": "report",
                "pattern": "^/reports/\\[id\\]$",
                "expected_modes": ["original", "v3"],
                "access": "public",
                "authoritative_data_owner_refs": ["web/src/lib/feed.ts"],
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
