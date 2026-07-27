#!/usr/bin/env python3
"""Audit the seven formal Operations Core ownership domains.

The inventory is declaration-only. Claims come from live read-only RPCs or the
live schedule-owner audit. A failed probe never falls back to the declared
owner; it leaves an ``unknown_owner`` blocker.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from volpred.diagnostics import warn
from volpred.ops.authority import FORMAL_PRIMARY_AUTHORITY_KEY
from volpred.ops.authority.supabase import SupabaseAuthorityStore
from volpred.ops.delivery.owned_email import SupabaseOwnedEmailStore
from volpred.ops.delivery.owned_publisher_article import (
    SupabaseOwnedPublisherArticleStore,
)
from volpred.ops.delivery.owned_publisher_delete import (
    SupabaseOwnedPublisherDeleteStore,
)
from volpred.ops.delivery.owned_publisher_reconcile import (
    SupabaseOwnedPublisherReconcileStore,
)
from volpred.ops.delivery.supabase_commit_ownership import (
    SupabaseCommitOwnerStore,
)
from volpred.ops.owner_census import (
    CapabilityClaim,
    CapabilitySpec,
    OwnerCensusInputError,
    build_owner_census,
)
from volpred.ops.schedule_materialization import (
    ScheduleConfigurationError,
    load_schedule_jobs,
    load_schedule_policy,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = ROOT / "config" / "formal_capability_inventory.json"
DEFAULT_SCHEDULES = ROOT / "config" / "runtime_schedules.json"
_ALLOWED_RESOLVERS = frozenset(
    {
        "unresolved",
        "commit_owner_rpc",
        "notification_owner_rpc",
        "publisher_sync_owner_rpc",
        "publisher_reconcile_owner_rpc",
        "publisher_delete_owner_rpc",
        "primary_authority_owner_rpc",
    }
)
_ROOT_CAPABILITIES = frozenset(
    {
        ("task", "work.coordinate"),
        ("commit", "git.commit"),
        ("incident", "incident.lifecycle"),
        ("provider", "provider.execution"),
        ("host_authority", FORMAL_PRIMARY_AUTHORITY_KEY),
    }
)
_EXPECTED_RESOLVERS = {
    ("task", "work.coordinate"): "unresolved",
    ("commit", "git.commit"): "commit_owner_rpc",
    ("effect", "email.ops_alert"): "notification_owner_rpc",
    (
        "effect",
        "publisher.article.supabase.sync",
    ): "publisher_sync_owner_rpc",
    (
        "effect",
        "publisher.article.supabase.reconcile",
    ): "publisher_reconcile_owner_rpc",
    (
        "effect",
        "publisher.article.supabase.delete",
    ): "publisher_delete_owner_rpc",
    ("incident", "incident.lifecycle"): "unresolved",
    ("provider", "provider.execution"): "unresolved",
    (
        "host_authority",
        FORMAL_PRIMARY_AUTHORITY_KEY,
    ): "primary_authority_owner_rpc",
}
_SCHEDULE_PROBE_TIMEOUT_SECONDS = 15
_SCHEDULE_EVIDENCE_MAX_AGE_SECONDS = 30
_CLOCK_SKEW_SECONDS = 5
_NON_EFFECT_OWNED_MODULES = frozenset({"owned_change.py"})


def _load_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OwnerCensusInputError(f"could not read JSON object: {path}") from exc
    if not isinstance(payload, dict):
        raise OwnerCensusInputError(f"expected JSON object: {path}")
    return payload


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OwnerCensusInputError(f"{field} is required")
    if value != value.strip():
        raise OwnerCensusInputError(f"{field} must be normalized")
    return value


def _inventory_rows(
    inventory: Mapping[str, Any],
) -> tuple[tuple[CapabilitySpec, str], ...]:
    if inventory.get("schema_version") != "formal-capability-inventory.v1":
        raise OwnerCensusInputError("unsupported formal capability inventory schema")
    rows = inventory.get("capabilities")
    if not isinstance(rows, list):
        raise OwnerCensusInputError("formal capability inventory requires capabilities")
    result: list[tuple[CapabilitySpec, str]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise OwnerCensusInputError(f"capability row {index} must be an object")
        resolver = _required_text(
            row.get("resolver"),
            field=f"capability row {index} resolver",
        )
        if resolver not in _ALLOWED_RESOLVERS:
            raise OwnerCensusInputError(f"unsupported capability resolver: {resolver}")
        required_owner = _required_text(
            row.get("required_owner", "operations_core"),
            field=f"capability row {index} required_owner",
        )
        if required_owner != "operations_core":
            raise OwnerCensusInputError(
                "formal capability required_owner must be operations_core"
            )
        result.append(
            (
                CapabilitySpec(
                    domain=_required_text(
                        row.get("domain"),
                        field=f"capability row {index} domain",
                    ),
                    capability=_required_text(
                        row.get("capability"),
                        field=f"capability row {index} capability",
                    ),
                    source_ref=_required_text(
                        row.get("source_ref"),
                        field=f"capability row {index} source_ref",
                    ),
                    required_owner=required_owner,
                ),
                resolver,
            )
        )
    return tuple(result)


def _discover_effect_families(root: Path = ROOT) -> frozenset[str]:
    families: set[str] = set()
    module_by_family: dict[str, Path] = {}
    delivery = root / "src" / "volpred" / "ops" / "delivery"
    for path in sorted(delivery.glob("owned_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise OwnerCensusInputError(
                f"could not inspect formal effect owner: {path}"
            ) from exc
        found: list[str] = []
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name)
                    and target.id == "_OWNER_FAMILY"
                    for target in node.targets
                )
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                found.append(node.value.value)
        if path.name in _NON_EFFECT_OWNED_MODULES:
            if found:
                raise OwnerCensusInputError(
                    f"non-effect owned module declares an effect family: {path}"
                )
            continue
        if len(found) != 1:
            raise OwnerCensusInputError(
                "formal effect owner must declare exactly one "
                f"_OWNER_FAMILY: {path}"
            )
        family = found[0]
        previous = module_by_family.get(family)
        if previous is not None:
            raise OwnerCensusInputError(
                "formal effect family has multiple owner modules: "
                f"{family} ({previous}, {path})"
            )
        module_by_family[family] = path
        families.add(family)
    if not families:
        raise OwnerCensusInputError(
            "formal effect-family source audit found no owner families"
        )
    return frozenset(families)


def _audit_inventory_coverage(
    rows: tuple[tuple[CapabilitySpec, str], ...],
    *,
    discovered_effect_families: frozenset[str],
) -> None:
    keys = {(spec.domain, spec.capability) for spec, _resolver in rows}
    resolver_by_key = {
        (spec.domain, spec.capability): resolver
        for spec, resolver in rows
    }
    configured_roots = {
        key for key in keys if key[0] not in {"effect", "schedule"}
    }
    if configured_roots != _ROOT_CAPABILITIES:
        missing = sorted(_ROOT_CAPABILITIES - configured_roots)
        extra = sorted(configured_roots - _ROOT_CAPABILITIES)
        raise OwnerCensusInputError(
            "formal root capability inventory drifted: "
            f"missing={missing}, extra={extra}"
        )
    configured_effects = {
        capability for domain, capability in keys if domain == "effect"
    }
    if configured_effects != discovered_effect_families:
        missing = sorted(discovered_effect_families - configured_effects)
        extra = sorted(configured_effects - discovered_effect_families)
        raise OwnerCensusInputError(
            "formal effect capability inventory drifted: "
            f"missing={missing}, extra={extra}"
        )
    if resolver_by_key != _EXPECTED_RESOLVERS:
        raise OwnerCensusInputError(
            "formal capability resolver bindings drifted"
        )


def _schedule_specs(
    config: Mapping[str, Any],
) -> tuple[CapabilitySpec, ...]:
    return tuple(
        CapabilitySpec(
            domain="schedule",
            capability=f"schedule.{job.id}",
            source_ref=f"config://runtime_schedules.json/system_crontab.items/{job.id}",
        )
        for job in sorted(load_schedule_jobs(config), key=lambda item: item.id)
    )


def _schedule_audit(
    schedule_path: Path,
) -> tuple[dict[str, Any], str | None]:
    try:
        process = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "reconcile_schedule_owners.py"),
                "--config",
                str(schedule_path),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=_SCHEDULE_PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {}, "schedule owner audit timed out"
    except OSError as exc:
        return {}, f"schedule owner audit could not start: {exc}"
    try:
        payload = json.loads(process.stdout)
    except (UnicodeError, json.JSONDecodeError):
        return {}, (
            f"schedule owner audit returned invalid JSON (exit={process.returncode})"
        )
    if not isinstance(payload, dict):
        return {}, "schedule owner audit returned a non-object"
    error = None
    if process.returncode not in {0, 1}:
        error = f"schedule owner audit failed (exit={process.returncode})"
    return payload, error


def _schedule_audit_error(
    audit: Mapping[str, Any],
    *,
    config: Mapping[str, Any],
    audited_at: str,
) -> str | None:
    if audit.get("schema") != 1:
        return "schedule owner audit has unsupported schema"
    try:
        policy = load_schedule_policy(config)
        jobs = load_schedule_jobs(config)
    except ScheduleConfigurationError as exc:
        raise OwnerCensusInputError(
            f"invalid canonical schedule configuration: {exc}"
        ) from exc
    expected_ids = sorted(job.id for job in jobs)
    expected_core = sorted(
        job_id
        for job_id in expected_ids
        if policy.owner_for(job_id) == "operations_core"
    )
    expected_legacy = sorted(set(expected_ids) - set(expected_core))
    expected_label = str(
        (config.get("schedule_materialization") or {}).get("daemon_label")
        or "com.volpred.operations-core-scheduler"
    )
    expected_scalars = {
        "generation": policy.generation,
        "mode": policy.mode,
        "core_daemon_label": expected_label,
    }
    for field, expected in expected_scalars.items():
        if audit.get(field) != expected:
            return f"schedule owner audit {field} drifted"
    expected_lists = {
        "selected_job_ids": expected_ids,
        "operations_core_job_ids": expected_core,
        "legacy_job_ids": expected_legacy,
    }
    for field, expected in expected_lists.items():
        value = audit.get(field)
        if (
            not isinstance(value, list)
            or any(not isinstance(item, str) for item in value)
            or sorted(value) != expected
        ):
            return f"schedule owner audit {field} drifted"
    for field in ("conflicts", "dormant_legacy_surfaces"):
        if not isinstance(audit.get(field), list):
            return f"schedule owner audit omitted {field}"
    known_ids = set(expected_ids)
    for field in ("conflicts", "dormant_legacy_surfaces"):
        for row in audit[field]:
            if not isinstance(row, Mapping):
                return f"schedule owner audit {field} contains a non-object"
            job_id = row.get("job_id")
            if not isinstance(job_id, str):
                return f"schedule owner audit {field} has invalid job_id"
            if field == "dormant_legacy_surfaces" and not job_id:
                return f"schedule owner audit {field} omitted job_id"
            if job_id and job_id not in known_ids:
                return f"schedule owner audit {field} names an unknown job"
            if (
                not isinstance(row.get("surface"), str)
                or not row["surface"].strip()
                or not isinstance(row.get("reason"), str)
                or not row["reason"].strip()
            ):
                return f"schedule owner audit {field} has malformed evidence"
            if (
                field == "conflicts"
                and not job_id
                and (
                    row["surface"] != expected_label
                    or row["reason"]
                    != "operations-core clock not loaded"
                )
            ):
                return (
                    "schedule owner audit has unconsumable "
                    "global conflict"
                )
    conflicts = audit["conflicts"]
    expected_ok = not conflicts
    if audit.get("ok") is not expected_ok:
        return "schedule owner audit ok flag contradicts conflicts"
    expected_status = (
        "owner_surfaces_verified" if expected_ok else "ownership_conflict"
    )
    if audit.get("status") != expected_status:
        return "schedule owner audit status contradicts conflicts"
    observed_raw = audit.get("audited_at")
    if not isinstance(observed_raw, str):
        return "schedule owner audit omitted audited_at"
    try:
        observed = datetime.fromisoformat(observed_raw)
        census_clock = datetime.fromisoformat(audited_at)
    except ValueError:
        return "schedule owner audit has invalid audited_at"
    if (
        observed.tzinfo is None
        or observed.utcoffset() is None
        or census_clock.tzinfo is None
        or census_clock.utcoffset() is None
    ):
        return "schedule owner audit audited_at lacks UTC offset"
    age = (
        census_clock.astimezone(UTC) - observed.astimezone(UTC)
    ).total_seconds()
    if age < -_CLOCK_SKEW_SECONDS:
        return "schedule owner audit is from the future"
    if age > _SCHEDULE_EVIDENCE_MAX_AGE_SECONDS:
        return "schedule owner audit is stale"
    return None


def _schedule_claims(
    *,
    config: Mapping[str, Any],
    audit: Mapping[str, Any],
    observed_at: str,
) -> tuple[CapabilityClaim, ...]:
    policy = load_schedule_policy(config)
    claims: list[CapabilityClaim] = []
    conflicts = {
        str(row.get("job_id")): row
        for row in audit.get("conflicts", [])
        if isinstance(row, Mapping) and row.get("job_id")
    }
    core_missing = any(
        row.get("surface") == audit.get("core_daemon_label")
        for row in audit.get("conflicts", [])
        if isinstance(row, Mapping)
    )
    for job in sorted(load_schedule_jobs(config), key=lambda item: item.id):
        owner = policy.owner_for(job.id)
        if owner == "operations_core" and not core_missing:
            claims.append(
                CapabilityClaim(
                    domain="schedule",
                    capability=f"schedule.{job.id}",
                    owner=owner,
                    source_ref=(
                        "live://launchd/"
                        f"{audit.get('core_daemon_label', 'unknown-core')}"
                    ),
                    observed_at=observed_at,
                )
            )
        elif owner == "legacy":
            claims.append(
                CapabilityClaim(
                    domain="schedule",
                    capability=f"schedule.{job.id}",
                    owner=owner,
                    source_ref="config://runtime_schedules.json/legacy-owner",
                    observed_at=observed_at,
                )
            )
        conflict = conflicts.get(job.id)
        if conflict is not None:
            claims.append(
                CapabilityClaim(
                    domain="schedule",
                    capability=f"schedule.{job.id}",
                    owner="legacy",
                    source_ref=f"live://{conflict.get('surface', 'unknown')}",
                    observed_at=observed_at,
                )
            )
    for row in audit.get("dormant_legacy_surfaces", []):
        if not isinstance(row, Mapping) or not row.get("job_id"):
            continue
        claims.append(
            CapabilityClaim(
                domain="schedule",
                capability=f"schedule.{row['job_id']}",
                owner="legacy",
                source_ref=f"live://{row.get('surface', 'unknown')}",
                observed_at=observed_at,
                state="dormant",
            )
        )
    return tuple(claims)


def _owner_readers() -> dict[str, Callable[[], object]]:
    return {
        "commit_owner_rpc": (
            lambda: SupabaseCommitOwnerStore.from_environment().read_owner()
        ),
        "notification_owner_rpc": (
            lambda: SupabaseOwnedEmailStore.from_environment().read_owner()
        ),
        "publisher_sync_owner_rpc": (
            lambda: SupabaseOwnedPublisherArticleStore.from_environment().read_owner()
        ),
        "publisher_reconcile_owner_rpc": (
            lambda: SupabaseOwnedPublisherReconcileStore.from_environment().read_owner()
        ),
        "publisher_delete_owner_rpc": (
            lambda: SupabaseOwnedPublisherDeleteStore.from_environment().read_owner()
        ),
        "primary_authority_owner_rpc": (
            lambda: SupabaseAuthorityStore.from_environment().read_owner()
        ),
    }


def run_audit(
    *,
    inventory_path: Path = DEFAULT_INVENTORY,
    schedule_path: Path = DEFAULT_SCHEDULES,
    observed_at: str | None = None,
    readers: Mapping[str, Callable[[], object]] | None = None,
    schedule_audit: Mapping[str, Any] | None = None,
    discovered_effect_families: frozenset[str] | None = None,
) -> dict[str, Any]:
    now = observed_at or datetime.now(UTC).isoformat()
    inventory = _load_object(inventory_path)
    rows = _inventory_rows(inventory)
    _audit_inventory_coverage(
        rows,
        discovered_effect_families=(
            discovered_effect_families
            if discovered_effect_families is not None
            else _discover_effect_families()
        ),
    )
    schedule_config = _load_object(schedule_path)
    specs = [spec for spec, _resolver in rows]
    specs.extend(_schedule_specs(schedule_config))
    claims: list[CapabilityClaim] = []
    probe_errors: list[dict[str, str]] = []

    live_schedule_audit = schedule_audit
    schedule_error: str | None = None
    if live_schedule_audit is None:
        live_schedule_audit, schedule_error = _schedule_audit(schedule_path)
    schedule_validation_clock = (
        observed_at or datetime.now(UTC).isoformat()
    )
    if schedule_error is None:
        schedule_error = _schedule_audit_error(
            live_schedule_audit,
            config=schedule_config,
            audited_at=schedule_validation_clock,
        )
    if schedule_error:
        probe_errors.append(
            {"resolver": "schedule_owner_audit", "error": schedule_error}
        )
    else:
        claims.extend(
            _schedule_claims(
                config=schedule_config,
                audit=live_schedule_audit,
                observed_at=str(live_schedule_audit["audited_at"]),
            )
        )

    owner_readers = dict(readers or _owner_readers())
    for spec, resolver in rows:
        if resolver == "unresolved":
            continue
        reader = owner_readers.get(resolver)
        if reader is None:
            probe_errors.append(
                {"resolver": resolver, "error": "owner reader unavailable"}
            )
            continue
        try:
            owner_view = reader()
            owner = _required_text(
                getattr(owner_view, "owner", None),
                field=f"{resolver} owner",
            )
        except Exception as exc:  # noqa: BLE001 - any probe failure blocks.
            warn(
                "formal-owner-census",
                "live owner probe failed; capability remains blocked",
                resolver=resolver,
                error_type=type(exc).__name__,
            )
            probe_errors.append(
                {
                    "resolver": resolver,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        claims.append(
            CapabilityClaim(
                domain=spec.domain,
                capability=spec.capability,
                owner=owner,
                source_ref=spec.source_ref,
                observed_at=now,
            )
        )
    report = build_owner_census(specs=specs, claims=claims).as_dict()
    report["audited_at"] = (
        observed_at or datetime.now(UTC).isoformat()
    )
    report["probe_errors"] = probe_errors
    report["inventory_path"] = str(inventory_path)
    report["schedule_path"] = str(schedule_path)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--schedules", type=Path, default=DEFAULT_SCHEDULES)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = run_audit(
            inventory_path=args.inventory,
            schedule_path=args.schedules,
        )
    except (
        OwnerCensusInputError,
        ScheduleConfigurationError,
        ValueError,
    ) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "formal-owner-census-error.v1",
                    "ok": False,
                    "status": "invalid_inventory",
                    "error": str(exc),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI must emit structured failure.
        print(
            json.dumps(
                {
                    "schema_version": "formal-owner-census-error.v1",
                    "ok": False,
                    "status": "audit_failed",
                    "error": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
