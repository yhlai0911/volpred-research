from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

import scripts.audit_formal_owners as audit_module
from scripts.audit_formal_owners import run_audit
from volpred.ops.owner_census import OwnerCensusInputError


@dataclass(frozen=True)
class _Owner:
    owner: str


@dataclass(frozen=True)
class _PrimaryOwner:
    owner: str = "operations_core"
    backend_sha256: str = "a" * 64
    attested_at: str = "2026-07-27T08:59:55+00:00"


_EFFECT_FAMILIES = frozenset(
    {
        "email.ops_alert",
        "publisher.article.supabase.sync",
        "publisher.article.supabase.reconcile",
        "publisher.article.supabase.delete",
    }
)


def _readers() -> dict[str, Callable[[], object]]:
    return {
        "commit_owner_rpc": lambda: _Owner("operations_core"),
        "notification_owner_rpc": lambda: _Owner("operations_core"),
        "publisher_sync_owner_rpc": lambda: _Owner("operations_core"),
        "publisher_reconcile_owner_rpc": lambda: _Owner(
            "operations_core"
        ),
        "publisher_delete_owner_rpc": lambda: _Owner("operations_core"),
        "primary_authority_owner_rpc": _PrimaryOwner,
    }


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _inventory(path: Path) -> None:
    _write_json(
        path,
        {
            "schema_version": "formal-capability-inventory.v1",
            "capabilities": [
                {
                    "domain": "task",
                    "capability": "work.coordinate",
                    "source_ref": "test://task",
                    "resolver": "unresolved",
                },
                {
                    "domain": "commit",
                    "capability": "git.commit",
                    "source_ref": "test://commit",
                    "resolver": "commit_owner_rpc",
                },
                {
                    "domain": "effect",
                    "capability": "email.ops_alert",
                    "source_ref": "test://effect",
                    "resolver": "notification_owner_rpc",
                },
                {
                    "domain": "effect",
                    "capability": "publisher.article.supabase.sync",
                    "source_ref": "test://effect-sync",
                    "resolver": "publisher_sync_owner_rpc",
                },
                {
                    "domain": "effect",
                    "capability": "publisher.article.supabase.reconcile",
                    "source_ref": "test://effect-reconcile",
                    "resolver": "publisher_reconcile_owner_rpc",
                },
                {
                    "domain": "effect",
                    "capability": "publisher.article.supabase.delete",
                    "source_ref": "test://effect-delete",
                    "resolver": "publisher_delete_owner_rpc",
                },
                {
                    "domain": "incident",
                    "capability": "incident.lifecycle",
                    "source_ref": "test://incident",
                    "resolver": "unresolved",
                },
                {
                    "domain": "provider",
                    "capability": "provider.execution",
                    "source_ref": "test://provider",
                    "resolver": "unresolved",
                },
                {
                    "domain": "host_authority",
                    "capability": "operations-core-primary",
                    "source_ref": (
                        "supabase://backend-sha256/"
                        f"{'a' * 64}/rpc/"
                        "volpred_read_primary_authority_owner"
                    ),
                    "resolver": "primary_authority_owner_rpc",
                },
            ],
        },
    )


def _schedules(path: Path) -> None:
    _write_json(
        path,
        {
            "schedule_materialization": {
                "schema": 1,
                "generation": "test-v1",
                "mode": "active",
                "active_since": "2026-07-27T08:00:00Z",
                "active_jobs": {},
            },
            "system_crontab": {
                "items": [
                    {
                        "id": "one",
                        "cron": "* * * * *",
                        "wrapper_script": "/tmp/one.sh",
                    }
                ]
            },
            "daemons": [],
        },
    )


def _schedule_audit(*, conflicts: list[dict] | None = None) -> dict:
    conflict_rows = conflicts or []
    return {
        "schema": 1,
        "generation": "test-v1",
        "mode": "active",
        "selected_job_ids": ["one"],
        "operations_core_job_ids": ["one"],
        "legacy_job_ids": [],
        "core_daemon_label": "com.volpred.operations-core-scheduler",
        "conflicts": conflict_rows,
        "dormant_legacy_surfaces": [],
        "ok": not conflict_rows,
        "status": (
            "ownership_conflict"
            if conflict_rows
            else "owner_surfaces_verified"
        ),
        "audited_at": "2026-07-27T09:00:00+00:00",
    }


def test_live_probes_do_not_fill_unresolved_capabilities(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.json"
    schedules = tmp_path / "runtime.json"
    _inventory(inventory)
    _schedules(schedules)

    report = run_audit(
        inventory_path=inventory,
        schedule_path=schedules,
        observed_at="2026-07-27T09:00:00+00:00",
        readers=_readers(),
        schedule_audit=_schedule_audit(),
        discovered_effect_families=_EFFECT_FAMILIES,
    )

    assert report["ok"] is False
    assert {blocker["capability"] for blocker in report["blockers"]} == {
        "work.coordinate",
        "incident.lifecycle",
        "provider.execution",
    }
    assert report["probe_errors"] == []
    primary = next(
        item
        for item in report["capabilities"]
        if item["capability"] == "operations-core-primary"
    )
    assert primary["claims"][0]["observed_at"] == "2026-07-27T08:59:55Z"


def test_primary_authority_probe_failure_remains_unknown_owner(
    tmp_path: Path,
) -> None:
    inventory = tmp_path / "inventory.json"
    schedules = tmp_path / "runtime.json"
    _inventory(inventory)
    _schedules(schedules)

    def failed() -> object:
        raise RuntimeError("attestation unavailable")

    report = run_audit(
        inventory_path=inventory,
        schedule_path=schedules,
        observed_at="2026-07-27T09:00:00+00:00",
        readers={
            **_readers(),
            "primary_authority_owner_rpc": failed,
        },
        schedule_audit=_schedule_audit(),
        discovered_effect_families=_EFFECT_FAMILIES,
    )

    row = next(
        item
        for item in report["capabilities"]
        if item["capability"] == "operations-core-primary"
    )
    assert row["status"] == "unknown_owner"
    assert report["probe_errors"] == [
        {
            "resolver": "primary_authority_owner_rpc",
            "error": "RuntimeError: attestation unavailable",
        }
    ]


@pytest.mark.parametrize(
    ("reader", "message"),
    [
        (
            lambda: _PrimaryOwner(backend_sha256="b" * 64),
            "backend identity drifted",
        ),
        (
            lambda: _PrimaryOwner(
                attested_at="2026-07-27T08:58:00+00:00"
            ),
            "attestation is stale",
        ),
        (
            lambda: _PrimaryOwner(
                attested_at="2026-07-27T09:00:06+00:00"
            ),
            "attestation is from the future",
        ),
    ],
)
def test_primary_authority_evidence_identity_and_time_fail_closed(
    tmp_path: Path,
    reader: Callable[[], object],
    message: str,
) -> None:
    inventory = tmp_path / "inventory.json"
    schedules = tmp_path / "runtime.json"
    _inventory(inventory)
    _schedules(schedules)

    report = run_audit(
        inventory_path=inventory,
        schedule_path=schedules,
        observed_at="2026-07-27T09:00:00+00:00",
        readers={
            **_readers(),
            "primary_authority_owner_rpc": reader,
        },
        schedule_audit=_schedule_audit(),
        discovered_effect_families=_EFFECT_FAMILIES,
    )

    row = next(
        item
        for item in report["capabilities"]
        if item["capability"] == "operations-core-primary"
    )
    assert row["status"] == "unknown_owner"
    assert message in report["probe_errors"][0]["error"]


def test_probe_failure_is_visible_and_fails_closed(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.json"
    schedules = tmp_path / "runtime.json"
    _inventory(inventory)
    _schedules(schedules)

    def failed() -> object:
        raise RuntimeError("backend unavailable")

    report = run_audit(
        inventory_path=inventory,
        schedule_path=schedules,
        observed_at="2026-07-27T09:00:00+00:00",
        readers={**_readers(), "commit_owner_rpc": failed},
        schedule_audit=_schedule_audit(),
        discovered_effect_families=_EFFECT_FAMILIES,
    )

    assert any(blocker["capability"] == "git.commit" for blocker in report["blockers"])
    assert report["probe_errors"] == [
        {
            "resolver": "commit_owner_rpc",
            "error": "RuntimeError: backend unavailable",
        }
    ]


def test_invalid_schedule_probe_cannot_fall_back_to_declared_owner(
    tmp_path: Path,
) -> None:
    inventory = tmp_path / "inventory.json"
    schedules = tmp_path / "runtime.json"
    _inventory(inventory)
    _schedules(schedules)

    report = run_audit(
        inventory_path=inventory,
        schedule_path=schedules,
        observed_at="2026-07-27T09:00:00+00:00",
        readers=_readers(),
        schedule_audit={},
        discovered_effect_families=_EFFECT_FAMILIES,
    )

    row = next(
        item for item in report["capabilities"] if item["capability"] == "schedule.one"
    )
    assert row["status"] == "unknown_owner"
    assert report["probe_errors"] == [
        {
            "resolver": "schedule_owner_audit",
            "error": "schedule owner audit has unsupported schema",
        }
    ]


def test_live_legacy_schedule_surface_creates_duplicate_blocker(
    tmp_path: Path,
) -> None:
    inventory = tmp_path / "inventory.json"
    schedules = tmp_path / "runtime.json"
    _inventory(inventory)
    _schedules(schedules)

    report = run_audit(
        inventory_path=inventory,
        schedule_path=schedules,
        observed_at="2026-07-27T09:00:00+00:00",
        readers=_readers(),
        schedule_audit=_schedule_audit(
            conflicts=[
                {
                    "job_id": "one",
                    "surface": "host_crontab",
                    "reason": "legacy owner still installed",
                }
            ]
        ),
        discovered_effect_families=_EFFECT_FAMILIES,
    )

    row = next(
        item for item in report["capabilities"] if item["capability"] == "schedule.one"
    )
    assert row["status"] == "duplicate_owner"
    assert row["active_claim_count"] == 2


def test_code_discovered_effect_family_cannot_be_omitted(
    tmp_path: Path,
) -> None:
    inventory = tmp_path / "inventory.json"
    schedules = tmp_path / "runtime.json"
    _inventory(inventory)
    _schedules(schedules)

    with pytest.raises(
        OwnerCensusInputError,
        match="formal effect capability inventory drifted",
    ):
        run_audit(
            inventory_path=inventory,
            schedule_path=schedules,
            observed_at="2026-07-27T09:00:00+00:00",
            readers=_readers(),
            schedule_audit=_schedule_audit(),
            discovered_effect_families=(
                _EFFECT_FAMILIES | {"effect.new"}
            ),
        )


def test_duplicate_effect_family_modules_are_rejected(
    tmp_path: Path,
) -> None:
    delivery = tmp_path / "src" / "volpred" / "ops" / "delivery"
    delivery.mkdir(parents=True)
    (delivery / "owned_one.py").write_text(
        '_OWNER_FAMILY = "effect.same"\n',
        encoding="utf-8",
    )
    (delivery / "owned_two.py").write_text(
        '_OWNER_FAMILY = "effect.same"\n',
        encoding="utf-8",
    )

    with pytest.raises(
        OwnerCensusInputError,
        match="multiple owner modules",
    ):
        audit_module._discover_effect_families(tmp_path)


def test_capability_cannot_borrow_another_live_resolver(
    tmp_path: Path,
) -> None:
    inventory = tmp_path / "inventory.json"
    schedules = tmp_path / "runtime.json"
    _inventory(inventory)
    _schedules(schedules)
    payload = json.loads(inventory.read_text(encoding="utf-8"))
    payload["capabilities"][0]["resolver"] = "notification_owner_rpc"
    _write_json(inventory, payload)

    with pytest.raises(
        OwnerCensusInputError,
        match="resolver bindings drifted",
    ):
        run_audit(
            inventory_path=inventory,
            schedule_path=schedules,
            observed_at="2026-07-27T09:00:00+00:00",
            readers=_readers(),
            schedule_audit=_schedule_audit(),
            discovered_effect_families=_EFFECT_FAMILIES,
        )


def test_inventory_cannot_redefine_legacy_as_the_required_owner(
    tmp_path: Path,
) -> None:
    inventory = tmp_path / "inventory.json"
    schedules = tmp_path / "runtime.json"
    _inventory(inventory)
    _schedules(schedules)
    payload = json.loads(inventory.read_text(encoding="utf-8"))
    payload["capabilities"][1]["required_owner"] = "legacy"
    _write_json(inventory, payload)

    with pytest.raises(
        OwnerCensusInputError,
        match="required_owner must be operations_core",
    ):
        run_audit(
            inventory_path=inventory,
            schedule_path=schedules,
            observed_at="2026-07-27T09:00:00+00:00",
            readers=_readers(),
            schedule_audit=_schedule_audit(),
            discovered_effect_families=_EFFECT_FAMILIES,
        )


def test_stale_schedule_evidence_cannot_mint_current_claims(
    tmp_path: Path,
) -> None:
    inventory = tmp_path / "inventory.json"
    schedules = tmp_path / "runtime.json"
    _inventory(inventory)
    _schedules(schedules)
    stale = _schedule_audit()
    stale["audited_at"] = "2026-07-27T08:00:00+00:00"

    report = run_audit(
        inventory_path=inventory,
        schedule_path=schedules,
        observed_at="2026-07-27T09:00:00+00:00",
        readers=_readers(),
        schedule_audit=stale,
        discovered_effect_families=_EFFECT_FAMILIES,
    )

    row = next(
        item
        for item in report["capabilities"]
        if item["capability"] == "schedule.one"
    )
    assert row["status"] == "unknown_owner"
    assert report["probe_errors"] == [
        {
            "resolver": "schedule_owner_audit",
            "error": "schedule owner audit is stale",
        }
    ]


@pytest.mark.parametrize("job_id", [None, 0, [], ""])
def test_unconsumable_schedule_conflict_cannot_be_discarded(
    tmp_path: Path,
    job_id: object,
) -> None:
    inventory = tmp_path / "inventory.json"
    schedules = tmp_path / "runtime.json"
    _inventory(inventory)
    _schedules(schedules)
    malformed = _schedule_audit(
        conflicts=[
            {
                "job_id": job_id,
                "surface": "host_crontab",
                "reason": "legacy owner still installed",
            }
        ]
    )

    report = run_audit(
        inventory_path=inventory,
        schedule_path=schedules,
        observed_at="2026-07-27T09:00:00+00:00",
        readers=_readers(),
        schedule_audit=malformed,
        discovered_effect_families=_EFFECT_FAMILIES,
    )

    row = next(
        item
        for item in report["capabilities"]
        if item["capability"] == "schedule.one"
    )
    assert row["status"] == "unknown_owner"
    assert report["probe_errors"][0]["resolver"] == (
        "schedule_owner_audit"
    )


def test_schedule_subprocess_timeout_becomes_probe_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def timeout(*_args: object, **_kwargs: object) -> object:
        raise audit_module.subprocess.TimeoutExpired(["audit"], 15)

    monkeypatch.setattr(audit_module.subprocess, "run", timeout)

    payload, error = audit_module._schedule_audit(tmp_path / "runtime.json")

    assert payload == {}
    assert error == "schedule owner audit timed out"


@pytest.mark.parametrize(
    ("report", "expected"),
    [
        ({"ok": True}, 0),
        ({"ok": False}, 1),
    ],
)
def test_cli_exit_matches_valid_census_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    report: dict[str, bool],
    expected: int,
) -> None:
    monkeypatch.setattr(audit_module, "run_audit", lambda **_kwargs: report)

    assert audit_module.main([]) == expected
    assert json.loads(capsys.readouterr().out)["ok"] is report["ok"]


def test_cli_input_failure_is_structured_exit_two(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(**_kwargs: object) -> object:
        raise audit_module.ScheduleConfigurationError("bad schedule")

    monkeypatch.setattr(audit_module, "run_audit", fail)

    assert audit_module.main([]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "invalid_inventory"
    assert payload["error"] == "bad schedule"


def test_cli_unexpected_audit_failure_is_structured_exit_two(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(**_kwargs: object) -> object:
        raise RuntimeError("probe crashed")

    monkeypatch.setattr(audit_module, "run_audit", fail)

    assert audit_module.main([]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "audit_failed"
    assert payload["error"] == "RuntimeError: probe crashed"
