from __future__ import annotations

import hashlib
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from scripts.guided_host_migration import build_parser
from volpred.ops import host_migration
from volpred.ops.host_attestation import (
    HostAttestationError,
    load_trust_policy,
    public_key_from_private,
    sha256_json,
    sign_mapping,
    write_private_key,
)
from volpred.ops.host_migration import (
    CONTINUITY_SCHEMA,
    HostMigrationError,
    assess_continuity_receipt,
    build_guided_plan,
    capture_host,
    compare_hosts,
    load_spec,
    validate_spec,
    write_json,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "config" / "host_migration_manifest.json"
NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
MIGRATION_ID = "issue17-test-migration"
CHALLENGE = "0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def _canonical_migration_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        host_migration,
        "HOST_MIGRATION_STATE_DIR",
        tmp_path / "canonical-host-migration-state",
    )


def _spec() -> dict:
    return {
        "schema_version": "volpred.host-migration-spec.v2",
        "snapshot_max_age_seconds": 900,
        "artifact_groups": [
            {
                "id": "code",
                "paths": ["src"],
                "required": True,
                "parity": "sha256",
                "git_root": ".",
                "git_paths": ["src"],
                "required_json_schema": None,
            },
            {
                "id": "continuity",
                "paths": ["receipt.json"],
                "required": True,
                "parity": "validated_json",
                "git_root": None,
                "git_paths": [],
                "required_json_schema": "primary-authority-outage-cross-host.v4",
            },
        ],
        "ignored_path_names": [".git", "__pycache__"],
        "tools": [
            {
                "id": "python",
                "commands": ["python3"],
                "required": True,
                "parity": "exact_sha256",
                "allowed_install_origins": [
                    "application",
                    "home",
                    "homebrew",
                    "repo",
                    "system",
                ],
                "functional_permission_id": "runtime_toolchain_functional",
            }
        ],
        "secret_references": [
            {
                "id": "runtime",
                "names": ["SERVICE_TOKEN"],
                "locations": [".env.local"],
                "required": True,
                "reauthorization_permission_id": "runtime_reauthorization",
            }
        ],
        "forbidden_agentic_auth_names": ["OPENAI_API_KEY"],
        "permissions": [
            {
                "id": "remote_login",
                "required": True,
                "probe": "signed_manual_attestation",
            },
            {
                "id": "runtime_reauthorization",
                "required": True,
                "probe": "signed_manual_attestation",
            },
            {
                "id": "runtime_toolchain_functional",
                "required": True,
                "probe": "signed_manual_attestation",
            },
        ],
        "continuity": {
            "receipt_max_age_seconds": 3600,
            "rto_seconds_max": 300,
            "rpo_receipts_max": 0,
            "formal_effect_count_min": 1,
            "rollback_steps": ["close target gate", "restore exact-next epoch"],
        },
    }


def _git_commit(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Test"],
        check=True,
    )
    subprocess.run(["git", "-C", str(root), "add", "src"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-qm", "fixture"],
        check=True,
    )


def _key(path: Path) -> Path:
    write_private_key(path, Ed25519PrivateKey.generate())
    return path


@dataclass(frozen=True)
class _SigningKeys:
    source: Path
    target: Path
    verifier: Path
    continuity: Path


def _runtime_receipt(
    *,
    schema_version: str = "primary-authority-outage-cross-host.v4",
) -> dict:
    rehearsal_id = "cross-host-test"
    return {
        "schema_version": schema_version,
        "rehearsal_id": rehearsal_id,
        "authority_key": (
            "operations-core-outage-smoke-"
            + hashlib.sha256(rehearsal_id.encode()).hexdigest()[:32]
        ),
        "verified_at": NOW.isoformat(),
        "primary_host_id": "source-mac",
        "primary_host_fingerprint": "source-fingerprint",
        "standby_host_id": "target-mac",
        "standby_host_fingerprint": "target-fingerprint",
        "backend_sha256": "a" * 64,
        "implementation_sha256": "b" * 64,
        "cross_host_readiness_sha256": "c" * 64,
        "primary_epoch": 10,
        "standby_epoch": 11,
        "primary_expires_at": (NOW - timedelta(seconds=1)).isoformat(),
        "standby_acquired_at": NOW.isoformat(),
        "database_clock_handoff_seconds": 1.0,
        "publisher_fence": {
            "effect_family": "publisher.article.supabase.sync",
            "owner": "operations_core",
            "generation": 8,
            "changed_at": (NOW - timedelta(minutes=1)).isoformat(),
        },
        "primary_receipt_sha256": "d" * 64,
        "standby_receipt_sha256": "e" * 64,
        "successful_authority_claims": 2,
        "duplicate_authority_claims": 0,
        "effect_requests": 0,
        "provider_calls": 0,
        "cross_host_verified": True,
    }


def _attestations(
    path: Path,
    *,
    identity: str,
    passed: bool = True,
    observed_at: datetime = NOW,
) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "volpred.host-attestations.v2",
                "migration_id": MIGRATION_ID,
                "challenge": CHALLENGE,
                "signer_identity": identity,
                "observed_at": observed_at.isoformat(),
                "attestations": [
                    {
                        "id": "remote_login",
                        "passed": passed,
                        "evidence_ref": "ssh://host-fingerprint/source",
                    },
                    {
                        "id": "runtime_reauthorization",
                        "passed": passed,
                        "evidence_ref": "receipt://reauthorization/runtime",
                    },
                    {
                        "id": "runtime_toolchain_functional",
                        "passed": passed,
                        "evidence_ref": "receipt://toolchain/functional",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _prepare_host(
    root: Path,
    *,
    key: Path,
    identity: str,
    role: str,
    hostname: str,
    content: str = "same",
    env_extra: str = "",
    secret_symlink: Path | None = None,
    receipt_schema: str = "primary-authority-outage-cross-host.v4",
) -> dict:
    root.mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "module.py").write_text(content, encoding="utf-8")
    (root / "receipt.json").write_text(
        json.dumps(_runtime_receipt(schema_version=receipt_schema)),
        encoding="utf-8",
    )
    env_path = root / ".env.local"
    if secret_symlink is None:
        env_path.write_text(
            "SERVICE_TOKEN=fake-value-never-render\n" + env_extra,
            encoding="utf-8",
        )
        env_path.chmod(0o600)
    else:
        env_path.symlink_to(secret_symlink)
    _git_commit(root)
    attestation_path = _attestations(root / "attestations.json", identity=identity)
    snapshot = capture_host(
        spec=_spec(),
        repo_root=root,
        migration_id=MIGRATION_ID,
        challenge=CHALLENGE,
        signing_key_path=key,
        signer_identity=identity,
        signer_role=role,
        attestations_path=attestation_path,
        environment={},
        captured_at=NOW,
    )
    return _resign_snapshot(
        snapshot,
        key=key,
        identity=identity,
        role=role,
        hostname=hostname,
    )


def _resign_snapshot(
    snapshot: dict,
    *,
    key: Path,
    identity: str,
    role: str,
    hostname: str | None = None,
) -> dict:
    payload = json.loads(json.dumps(snapshot))
    payload.pop("attestation", None)
    payload.pop("snapshot_sha256", None)
    if hostname is not None:
        payload["host"]["hostname"] = hostname
    payload["snapshot_sha256"] = sha256_json(payload)
    payload["attestation"] = sign_mapping(
        payload,
        private_key_path=key,
        signer_identity=identity,
        signer_role=role,
    )
    return payload


def _trust_policy(
    path: Path,
    *,
    keys: _SigningKeys,
) -> object:
    path.write_text(
        json.dumps(
            {
                "schema_version": "volpred.host-migration-trust.v1",
                "migration_id": MIGRATION_ID,
                "challenge": CHALLENGE,
                "valid_from": (NOW - timedelta(minutes=5)).isoformat(),
                "valid_until": (NOW + timedelta(minutes=30)).isoformat(),
                "signers": [
                    {
                        "identity": "source-host",
                        "role": "source",
                        "public_key": public_key_from_private(keys.source),
                    },
                    {
                        "identity": "target-host",
                        "role": "target",
                        "public_key": public_key_from_private(keys.target),
                    },
                    {
                        "identity": "migration-verifier",
                        "role": "verifier",
                        "public_key": public_key_from_private(keys.verifier),
                    },
                    {
                        "identity": "continuity-verifier",
                        "role": "continuity_verifier",
                        "public_key": public_key_from_private(keys.continuity),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return load_trust_policy(path)


def _continuity(
    *,
    source: dict,
    target: dict,
    key: Path,
    rto: float = 42.5,
    lost: int = 0,
    effects: list[dict] | None = None,
) -> dict:
    formal_effects = effects or [
        {
            "effect_id": "effect-test-001",
            "effect_kind": "email.ops_alert",
            "request_sha256": "a" * 64,
            "terminal_receipt_sha256": "b" * 64,
            "status": "acknowledged",
            "duplicate_count": 0,
        }
    ]
    payload = {
        "schema_version": CONTINUITY_SCHEMA,
        "migration_id": MIGRATION_ID,
        "source_snapshot_sha256": source["snapshot_sha256"],
        "target_snapshot_sha256": target["snapshot_sha256"],
        "rehearsal_id": "issue17-formal-rehearsal",
        "authority_key": "operations-core-primary",
        "primary_epoch": 10,
        "standby_epoch": 11,
        "verified_at": NOW.isoformat(),
        "recovery_rto_seconds": rto,
        "formal_effect_receipts_lost": lost,
        "duplicate_authority_claims": 0,
        "formal_effects": formal_effects,
    }
    payload["receipt_sha256"] = sha256_json(payload)
    payload["attestation"] = sign_mapping(
        payload,
        private_key_path=key,
        signer_identity="continuity-verifier",
        signer_role="continuity_verifier",
    )
    return payload


def _pair(tmp_path: Path) -> tuple:
    keys = _SigningKeys(
        source=_key(tmp_path / "source-key"),
        target=_key(tmp_path / "target-key"),
        verifier=_key(tmp_path / "verifier-key"),
        continuity=_key(tmp_path / "continuity-key"),
    )
    source = _prepare_host(
        tmp_path / "source",
        key=keys.source,
        identity="source-host",
        role="source",
        hostname="source.local",
    )
    target = _prepare_host(
        tmp_path / "target",
        key=keys.target,
        identity="target-host",
        role="target",
        hostname="target.local",
    )
    trust = _trust_policy(
        tmp_path / "trust.json",
        keys=keys,
    )
    return keys, source, target, trust


def test_canonical_spec_covers_full_runtime_and_has_no_user_path() -> None:
    spec = load_spec(SPEC_PATH)
    groups = {item["id"]: item for item in spec["artifact_groups"]}
    code_paths = set(groups["operations_code"]["paths"])
    assert {
        "src/volpred",
        "scripts",
        "server.py",
        "pyproject.toml",
        "uv.lock",
        "Dockerfile.api",
        "zbpack.json",
    } <= code_paths
    assert "frontend-v2-fix" in groups["frontend"]["paths"]
    assert "supabase" in groups["supabase_deploy"]["paths"]
    tools = {item["id"]: item for item in spec["tools"]}
    assert {item["parity"] for item in tools.values()} == {"exact_sha256"}
    assert {
        tools["python"]["functional_permission_id"],
        tools["github_cli"]["functional_permission_id"],
        tools["codex_subscription_cli"]["functional_permission_id"],
    } == {
        "runtime_toolchain_functional",
        "github_session",
        "subscription_sessions",
    }
    text = SPEC_PATH.read_text(encoding="utf-8")
    assert "/Users/" not in text
    assert "yhlai0911" not in text


def test_spec_rejects_absolute_artifact_paths() -> None:
    spec = _spec()
    spec["artifact_groups"][0]["paths"] = ["/Users/someone/project"]
    with pytest.raises(HostMigrationError, match="repo-relative"):
        validate_spec(spec)


def test_capture_never_renders_secret_and_scans_env_file_for_forbidden_key(
    tmp_path: Path,
) -> None:
    key = _key(tmp_path / "key")
    snapshot = _prepare_host(
        tmp_path / "host",
        key=key,
        identity="source-host",
        role="source",
        hostname="source.local",
        env_extra="OPENAI_API_KEY=must-never-render\n",
    )
    encoded = json.dumps(snapshot)
    assert "fake-value-never-render" not in encoded
    assert "must-never-render" not in encoded
    assert snapshot["forbidden_agentic_auth_present"] == ["OPENAI_API_KEY"]


def test_secret_symlink_is_not_a_reauthorization_preflight(tmp_path: Path) -> None:
    external = tmp_path / "external.env"
    external.write_text("SERVICE_TOKEN=outside\n", encoding="utf-8")
    external.chmod(0o600)
    key = _key(tmp_path / "key")
    snapshot = _prepare_host(
        tmp_path / "host",
        key=key,
        identity="source-host",
        role="source",
        hostname="source.local",
        secret_symlink=external,
    )
    assert snapshot["secret_references"][0]["preflight_ready"] is False
    assert (
        snapshot["secret_references"][0]["locations"][0]["regular_non_symlink"]
        is False
    )


def test_attestation_passed_must_be_boolean_and_ids_unique(tmp_path: Path) -> None:
    root = tmp_path / "host"
    root.mkdir()
    key = _key(tmp_path / "key")
    (root / "src").mkdir()
    (root / "src" / "module.py").write_text("x", encoding="utf-8")
    (root / "receipt.json").write_text(
        '{"schema_version":"primary-authority-outage-cross-host.v4"}',
        encoding="utf-8",
    )
    (root / ".env.local").write_text("SERVICE_TOKEN=x\n", encoding="utf-8")
    (root / ".env.local").chmod(0o600)
    _git_commit(root)
    path = _attestations(root / "attestations.json", identity="source-host")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["attestations"][0]["passed"] = "false"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HostMigrationError, match="passed must be boolean"):
        capture_host(
            spec=_spec(),
            repo_root=root,
            migration_id=MIGRATION_ID,
            challenge=CHALLENGE,
            signing_key_path=key,
            signer_identity="source-host",
            signer_role="source",
            attestations_path=path,
            captured_at=NOW,
        )


def test_capture_binds_artifacts_to_clean_immutable_git(tmp_path: Path) -> None:
    key = _key(tmp_path / "key")
    clean = _prepare_host(
        tmp_path / "host",
        key=key,
        identity="source-host",
        role="source",
        hostname="source.local",
    )
    assert clean["source_control"]["declared_artifacts_clean_and_immutable"] is True
    (tmp_path / "host" / "src" / "module.py").write_text("dirty", encoding="utf-8")
    dirty = capture_host(
        spec=_spec(),
        repo_root=tmp_path / "host",
        migration_id=MIGRATION_ID,
        challenge=CHALLENGE,
        signing_key_path=key,
        signer_identity="source-host",
        signer_role="source",
        attestations_path=tmp_path / "host" / "attestations.json",
        captured_at=NOW,
    )
    assert dirty["source_control"]["declared_artifacts_clean_and_immutable"] is False
    assert dirty["source_control"]["groups"][0]["head_matches_capture"] is False


def test_target_dirty_worktree_cannot_be_promotion_eligible(tmp_path: Path) -> None:
    keys, source, target, trust = _pair(tmp_path)
    target["source_control"]["declared_artifacts_clean_and_immutable"] = False
    target = _resign_snapshot(
        target,
        key=keys.target,
        identity="target-host",
        role="target",
    )
    report = compare_hosts(
        spec=_spec(),
        source=source,
        target=target,
        trust_policy=trust,
        continuity_receipt=_continuity(
            source=source,
            target=target,
            key=keys.continuity,
        ),
        report_signing_key_path=keys.verifier,
        report_signer_identity="migration-verifier",
        compared_at=NOW,
    )
    assert report["promotion_eligible"] is False
    assert {
        "category": "target_identity",
        "id": "declared_artifacts",
        "reason": "target_not_clean_immutable_git",
    } in report["gaps"]


def test_untrusted_verifier_key_cannot_emit_report(tmp_path: Path) -> None:
    keys, source, target, trust = _pair(tmp_path)
    wrong_key = _key(tmp_path / "wrong-verifier-key")
    with pytest.raises(HostMigrationError, match="fingerprint|signature"):
        compare_hosts(
            spec=_spec(),
            source=source,
            target=target,
            trust_policy=trust,
            continuity_receipt=_continuity(
                source=source,
                target=target,
                key=keys.continuity,
            ),
            report_signing_key_path=wrong_key,
            report_signer_identity="migration-verifier",
            compared_at=NOW,
        )


def test_trust_policy_requires_four_unique_role_keys(tmp_path: Path) -> None:
    key = _key(tmp_path / "shared-key")
    public = public_key_from_private(key)
    policy_path = tmp_path / "trust.json"
    policy_path.write_text(
        json.dumps(
            {
                "schema_version": "volpred.host-migration-trust.v1",
                "migration_id": MIGRATION_ID,
                "challenge": CHALLENGE,
                "valid_from": (NOW - timedelta(minutes=5)).isoformat(),
                "valid_until": (NOW + timedelta(minutes=30)).isoformat(),
                "signers": [
                    {
                        "identity": f"{role}-identity",
                        "role": role,
                        "public_key": public,
                    }
                    for role in (
                        "source",
                        "target",
                        "verifier",
                        "continuity_verifier",
                    )
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(HostAttestationError, match="unique.*key|fingerprint"):
        load_trust_policy(policy_path)


def test_trust_policy_window_is_bounded(tmp_path: Path) -> None:
    keys = _SigningKeys(
        source=_key(tmp_path / "source-key"),
        target=_key(tmp_path / "target-key"),
        verifier=_key(tmp_path / "verifier-key"),
        continuity=_key(tmp_path / "continuity-key"),
    )
    policy_path = tmp_path / "trust.json"
    _trust_policy(policy_path, keys=keys)
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    payload["valid_until"] = (NOW + timedelta(hours=2)).isoformat()
    policy_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HostAttestationError, match="window"):
        load_trust_policy(policy_path)


def test_distinct_signed_hosts_and_formal_receipt_can_pass(tmp_path: Path) -> None:
    keys, source, target, trust = _pair(tmp_path)
    report = compare_hosts(
        spec=_spec(),
        source=source,
        target=target,
        trust_policy=trust,
        continuity_receipt=_continuity(
            source=source,
            target=target,
            key=keys.continuity,
        ),
        report_signing_key_path=keys.verifier,
        report_signer_identity="migration-verifier",
        compared_at=NOW,
    )
    assert report["gaps"] == []
    assert report["promotion_eligible"] is True
    plan = build_guided_plan(
        spec=_spec(),
        report=report,
        trust_policy=trust,
        plan_signing_key_path=keys.verifier,
        plan_signer_identity="migration-verifier",
        created_at=NOW,
    )
    assert plan["promotion_eligible"] is True
    assert plan["authorizes_primary_lease"] is False
    assert plan["performed_mutations"] == []


def test_challenge_can_only_produce_one_guided_plan(tmp_path: Path) -> None:
    keys, source, target, trust = _pair(tmp_path)
    report = compare_hosts(
        spec=_spec(),
        source=source,
        target=target,
        trust_policy=trust,
        continuity_receipt=_continuity(
            source=source,
            target=target,
            key=keys.continuity,
        ),
        report_signing_key_path=keys.verifier,
        report_signer_identity="migration-verifier",
        compared_at=NOW,
    )
    build_guided_plan(
        spec=_spec(),
        report=report,
        trust_policy=trust,
        plan_signing_key_path=keys.verifier,
        plan_signer_identity="migration-verifier",
        created_at=NOW,
    )
    with pytest.raises(HostMigrationError, match="already consumed"):
        build_guided_plan(
            spec=_spec(),
            report=report,
            trust_policy=trust,
            plan_signing_key_path=keys.verifier,
            plan_signer_identity="migration-verifier",
            created_at=NOW,
        )


def test_deleted_ledger_does_not_reopen_consumed_challenge(
    tmp_path: Path,
) -> None:
    keys, source, target, trust = _pair(tmp_path)
    report = compare_hosts(
        spec=_spec(),
        source=source,
        target=target,
        trust_policy=trust,
        continuity_receipt=_continuity(
            source=source,
            target=target,
            key=keys.continuity,
        ),
        report_signing_key_path=keys.verifier,
        report_signer_identity="migration-verifier",
        compared_at=NOW,
    )
    build_guided_plan(
        spec=_spec(),
        report=report,
        trust_policy=trust,
        plan_signing_key_path=keys.verifier,
        plan_signer_identity="migration-verifier",
        created_at=NOW,
    )
    ledger = host_migration.HOST_MIGRATION_STATE_DIR / "challenge_ledger.json"
    ledger.unlink()
    with pytest.raises(HostMigrationError, match="evidence already exists"):
        build_guided_plan(
            spec=_spec(),
            report=report,
            trust_policy=trust,
            plan_signing_key_path=keys.verifier,
            plan_signer_identity="migration-verifier",
            created_at=NOW,
        )


def test_untrusted_plan_signing_key_is_rejected_before_consumption(
    tmp_path: Path,
) -> None:
    keys, source, target, trust = _pair(tmp_path)
    report = compare_hosts(
        spec=_spec(),
        source=source,
        target=target,
        trust_policy=trust,
        continuity_receipt=_continuity(
            source=source,
            target=target,
            key=keys.continuity,
        ),
        report_signing_key_path=keys.verifier,
        report_signer_identity="migration-verifier",
        compared_at=NOW,
    )
    with pytest.raises(HostMigrationError, match="fingerprint|signature"):
        build_guided_plan(
            spec=_spec(),
            report=report,
            trust_policy=trust,
            plan_signing_key_path=_key(tmp_path / "wrong-plan-key"),
            plan_signer_identity="migration-verifier",
            created_at=NOW,
        )
    assert not host_migration.HOST_MIGRATION_STATE_DIR.exists()


def test_challenge_consumption_is_atomic_under_concurrency(tmp_path: Path) -> None:
    keys, source, target, trust = _pair(tmp_path)
    report = compare_hosts(
        spec=_spec(),
        source=source,
        target=target,
        trust_policy=trust,
        continuity_receipt=_continuity(
            source=source,
            target=target,
            key=keys.continuity,
        ),
        report_signing_key_path=keys.verifier,
        report_signer_identity="migration-verifier",
        compared_at=NOW,
    )
    def create_plan() -> str:
        try:
            build_guided_plan(
                spec=_spec(),
                report=report,
                trust_policy=trust,
                plan_signing_key_path=keys.verifier,
                plan_signer_identity="migration-verifier",
                created_at=NOW,
            )
        except HostMigrationError as exc:
            return str(exc)
        return "created"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: create_plan(), range(2)))
    assert outcomes.count("created") == 1
    assert sum("already consumed" in item for item in outcomes) == 1


def test_same_host_or_same_key_cannot_form_pair(tmp_path: Path) -> None:
    keys, source, target, trust = _pair(tmp_path)
    same_hostname = _resign_snapshot(
        target,
        key=tmp_path / "target-key",
        identity="target-host",
        role="target",
        hostname="source.local",
    )
    with pytest.raises(HostMigrationError, match="hostnames must differ"):
        compare_hosts(
            spec=_spec(),
            source=source,
            target=same_hostname,
            trust_policy=trust,
            continuity_receipt=None,
            report_signing_key_path=keys.verifier,
            report_signer_identity="migration-verifier",
            compared_at=NOW,
        )


def test_tampered_snapshot_rehash_still_fails_signature(tmp_path: Path) -> None:
    keys, source, target, trust = _pair(tmp_path)
    target.pop("attestation")
    target["host"]["hostname"] = "forged.local"
    target.pop("snapshot_sha256")
    target["snapshot_sha256"] = sha256_json(target)
    target["attestation"] = source["attestation"]
    with pytest.raises(HostMigrationError, match="attestation"):
        compare_hosts(
            spec=_spec(),
            source=source,
            target=target,
            trust_policy=trust,
            continuity_receipt=None,
            report_signing_key_path=keys.verifier,
            report_signer_identity="migration-verifier",
            compared_at=NOW,
        )


def test_tampered_report_cannot_unblock_plan(tmp_path: Path) -> None:
    keys, source, target, trust = _pair(tmp_path)
    report = compare_hosts(
        spec=_spec(),
        source=source,
        target=target,
        trust_policy=trust,
        continuity_receipt=None,
        report_signing_key_path=keys.verifier,
        report_signer_identity="migration-verifier",
        compared_at=NOW,
    )
    report["gaps"] = []
    report["parity_passed"] = True
    report["promotion_eligible"] = True
    report.pop("attestation")
    report.pop("report_sha256")
    report["report_sha256"] = sha256_json(report)
    with pytest.raises(HostMigrationError, match="fields|attestation"):
        build_guided_plan(
            spec=_spec(),
            report=report,
            trust_policy=trust,
            plan_signing_key_path=keys.verifier,
            plan_signer_identity="migration-verifier",
            created_at=NOW,
        )


@pytest.mark.parametrize("bad_rto", [float("nan"), float("inf"), -1, True, "1"])
def test_continuity_rejects_nonfinite_negative_or_coerced_numbers(
    tmp_path: Path,
    bad_rto,
) -> None:
    keys, source, target, trust = _pair(tmp_path)
    receipt = _continuity(
        source=source,
        target=target,
        key=keys.continuity,
        rto=bad_rto,
    )
    result = assess_continuity_receipt(
        receipt,
        spec=_spec(),
        trust_policy=trust,
        source_snapshot_sha256=source["snapshot_sha256"],
        target_snapshot_sha256=target["snapshot_sha256"],
        now=NOW,
    )
    assert result["promotion_eligible"] is False
    assert result["reason_codes"][0].startswith("formal_continuity_invalid:")


def test_legacy_no_effect_receipt_and_cross_snapshot_replay_fail(tmp_path: Path) -> None:
    keys, source, target, trust = _pair(tmp_path)
    legacy = {
        "schema_version": "primary-authority-outage-cross-host.v4",
        "database_clock_handoff_seconds": 0.5,
        "effect_requests": 1,
    }
    legacy_result = assess_continuity_receipt(
        legacy,
        spec=_spec(),
        trust_policy=trust,
        source_snapshot_sha256=source["snapshot_sha256"],
        target_snapshot_sha256=target["snapshot_sha256"],
        now=NOW,
    )
    assert legacy_result["reason_codes"] == ["formal_continuity_schema_missing"]

    receipt = _continuity(
        source=source,
        target=target,
        key=keys.continuity,
    )
    replay_result = assess_continuity_receipt(
        receipt,
        spec=_spec(),
        trust_policy=trust,
        source_snapshot_sha256="f" * 64,
        target_snapshot_sha256=target["snapshot_sha256"],
        now=NOW,
    )
    assert replay_result["promotion_eligible"] is False
    assert "source snapshot mismatch" in replay_result["reason_codes"][0]


def test_wrong_runtime_artifact_schema_is_a_gap(tmp_path: Path) -> None:
    keys, source, _target, trust = _pair(tmp_path)
    target = _prepare_host(
        tmp_path / "wrong-target",
        key=keys.target,
        identity="target-host",
        role="target",
        hostname="target.local",
        receipt_schema="wrong.v1",
    )
    report = compare_hosts(
        spec=_spec(),
        source=source,
        target=target,
        trust_policy=trust,
        continuity_receipt=None,
        report_signing_key_path=keys.verifier,
        report_signer_identity="migration-verifier",
        compared_at=NOW,
    )
    assert {
        "category": "artifact",
        "id": "continuity",
        "reason": "missing_or_invalid",
    } in report["gaps"]


def test_schema_only_runtime_artifact_is_invalid(tmp_path: Path) -> None:
    key = _key(tmp_path / "key")
    root = tmp_path / "host"
    snapshot = _prepare_host(
        root,
        key=key,
        identity="source-host",
        role="source",
        hostname="source.local",
    )
    (root / "receipt.json").write_text(
        '{"schema_version":"primary-authority-outage-cross-host.v4"}',
        encoding="utf-8",
    )
    snapshot = capture_host(
        spec=_spec(),
        repo_root=root,
        migration_id=MIGRATION_ID,
        challenge=CHALLENGE,
        signing_key_path=key,
        signer_identity="source-host",
        signer_role="source",
        attestations_path=root / "attestations.json",
        environment={},
        captured_at=NOW,
    )
    runtime = next(
        artifact
        for artifact in snapshot["artifacts"]
        if artifact["id"] == "continuity"
    )
    assert runtime["valid"] is False
    assert runtime["files"][0]["json_valid"] is False


def test_invalid_source_runtime_artifact_cannot_be_baseline(
    tmp_path: Path,
) -> None:
    keys, source, target, trust = _pair(tmp_path)
    runtime = next(
        artifact
        for artifact in source["artifacts"]
        if artifact["id"] == "continuity"
    )
    runtime["valid"] = False
    source = _resign_snapshot(
        source,
        key=keys.source,
        identity="source-host",
        role="source",
    )
    report = compare_hosts(
        spec=_spec(),
        source=source,
        target=target,
        trust_policy=trust,
        continuity_receipt=_continuity(
            source=source,
            target=target,
            key=keys.continuity,
        ),
        report_signing_key_path=keys.verifier,
        report_signer_identity="migration-verifier",
        compared_at=NOW,
    )
    assert {
        "category": "artifact",
        "id": "continuity",
        "reason": "missing_or_invalid",
    } in report["gaps"]


def test_git_head_change_during_capture_fails_immutable_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "host"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "module.py").write_text("same", encoding="utf-8")
    (root / "receipt.json").write_text(
        json.dumps(_runtime_receipt()),
        encoding="utf-8",
    )
    (root / ".env.local").write_text("SERVICE_TOKEN=x\n", encoding="utf-8")
    (root / ".env.local").chmod(0o600)
    _git_commit(root)
    real_head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    calls = iter([real_head, "f" * 40])
    monkeypatch.setattr(host_migration, "_git_head", lambda _root: next(calls))
    spec = _spec()
    second = dict(spec["artifact_groups"][0])
    second["id"] = "code_second_group"
    spec["artifact_groups"].insert(1, second)
    key = _key(tmp_path / "key")
    snapshot = capture_host(
        spec=spec,
        repo_root=root,
        migration_id=MIGRATION_ID,
        challenge=CHALLENGE,
        signing_key_path=key,
        signer_identity="source-host",
        signer_role="source",
        attestations_path=_attestations(
            root / "attestations.json",
            identity="source-host",
        ),
        environment={},
        captured_at=NOW,
    )
    assert snapshot["source_control"][
        "declared_artifacts_clean_and_immutable"
    ] is False
    assert snapshot["source_control"]["repositories"][0]["head_stable"] is False


def test_executable_mode_is_part_of_artifact_identity(tmp_path: Path) -> None:
    keys, source, _target, _trust = _pair(tmp_path)
    target_root = tmp_path / "mode-target"
    target = _prepare_host(
        target_root,
        key=keys.target,
        identity="target-host",
        role="target",
        hostname="target.local",
    )
    (target_root / "src" / "module.py").chmod(0o755)
    target = capture_host(
        spec=_spec(),
        repo_root=target_root,
        migration_id=MIGRATION_ID,
        challenge=CHALLENGE,
        signing_key_path=keys.target,
        signer_identity="target-host",
        signer_role="target",
        attestations_path=target_root / "attestations.json",
        environment={},
        captured_at=NOW,
    )
    source_code = next(item for item in source["artifacts"] if item["id"] == "code")
    target_code = next(item for item in target["artifacts"] if item["id"] == "code")
    assert source_code["tree_sha256"] != target_code["tree_sha256"]
    assert target_code["files"][0]["mode"] == "100755"


def test_path_shim_is_not_accepted_as_canonical_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "gh"
    fake.write_text(
        "#!/bin/sh\nprintf 'gh version 2.88.1\\n'\nexit 0\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    spec = _spec()
    spec["tools"] = [
        {
            "id": "github_cli",
            "commands": ["gh"],
            "required": True,
            "parity": "exact_sha256",
            "allowed_install_origins": ["homebrew", "system"],
            "functional_permission_id": "runtime_toolchain_functional",
        }
    ]
    key = _key(tmp_path / "key")
    root = tmp_path / "host"
    root.mkdir()
    (root / "src").mkdir()
    (root / "src" / "module.py").write_text("same", encoding="utf-8")
    (root / "receipt.json").write_text(
        json.dumps(_runtime_receipt()),
        encoding="utf-8",
    )
    (root / ".env.local").write_text("SERVICE_TOKEN=x\n", encoding="utf-8")
    (root / ".env.local").chmod(0o600)
    _git_commit(root)
    monkeypatch.setenv("PATH", str(fake_bin))
    snapshot = capture_host(
        spec=spec,
        repo_root=root,
        migration_id=MIGRATION_ID,
        challenge=CHALLENGE,
        signing_key_path=key,
        signer_identity="source-host",
        signer_role="source",
        attestations_path=_attestations(
            root / "attestations.json",
            identity="source-host",
        ),
        environment={},
        captured_at=NOW,
    )
    assert snapshot["tools"][0]["ready"] is False
    assert snapshot["tools"][0]["install_origin"] == "other"


def test_tool_capture_never_executes_and_accepts_read_only_system_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system_bin = tmp_path / "system-bin"
    system_bin.mkdir()
    executable = system_bin / "tool"
    executable.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    executable.chmod(0o755)
    system_bin.chmod(0o555)
    monkeypatch.setattr(
        host_migration,
        "_resolve_command",
        lambda _tool: executable,
    )
    monkeypatch.setattr(
        host_migration,
        "_install_origin",
        lambda _path, *, repo_root: "system",
    )
    monkeypatch.setattr(
        host_migration.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("tool capture executed untrusted code"),
    )
    try:
        state = host_migration._capture_tool(
            {
                "id": "test_tool",
                "commands": ["tool"],
                "required": True,
                "parity": "exact_sha256",
                "allowed_install_origins": ["system"],
                "functional_permission_id": "runtime_toolchain_functional",
            },
            repo_root=tmp_path,
        )
    finally:
        system_bin.chmod(0o755)
    assert state["ready"] is True
    assert state["install_origin"] == "system"
    assert state["executable_sha256"] == hashlib.sha256(
        executable.read_bytes()
    ).hexdigest()


def test_artifact_symlink_escape_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "host"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("outside", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "module.py").symlink_to("../../outside.py")
    (root / "receipt.json").write_text(
        '{"schema_version":"primary-authority-outage-cross-host.v4"}',
        encoding="utf-8",
    )
    (root / ".env.local").write_text("SERVICE_TOKEN=x\n", encoding="utf-8")
    (root / ".env.local").chmod(0o600)
    _git_commit(root)
    key = _key(tmp_path / "key")
    attest = _attestations(root / "attestations.json", identity="source-host")
    with pytest.raises(HostMigrationError, match="symlink target is unsafe"):
        capture_host(
            spec=_spec(),
            repo_root=root,
            migration_id=MIGRATION_ID,
            challenge=CHALLENGE,
            signing_key_path=key,
            signer_identity="source-host",
            signer_role="source",
            attestations_path=attest,
            captured_at=NOW,
        )


def test_atomic_writer_refuses_symlink_and_handles_concurrency(tmp_path: Path) -> None:
    victim = tmp_path / "victim.json"
    victim.write_text('{"safe":true}\n', encoding="utf-8")
    output = tmp_path / "output.json"
    output.symlink_to(victim)
    with pytest.raises(HostMigrationError, match="non-symlink"):
        write_json(output, {"unsafe": True})
    assert victim.read_text(encoding="utf-8") == '{"safe":true}\n'
    output.unlink()

    payloads = [{"writer": index} for index in range(8)]
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda payload: write_json(output, payload), payloads))
    assert json.loads(output.read_text(encoding="utf-8")) in payloads
    assert not list(tmp_path.glob(".output.json.*.tmp"))


def test_script_module_and_spec_do_not_hardcode_user_home() -> None:
    for relative in [
        "src/volpred/ops/host_attestation.py",
        "src/volpred/ops/host_migration.py",
        "scripts/guided_host_migration.py",
        "config/host_migration_manifest.json",
    ]:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "/Users/" not in text
        assert "yhlai0911" not in text
        assert "$HOME" not in text


def test_operator_cli_accepts_documented_required_arguments() -> None:
    parser = build_parser()
    capture = parser.parse_args(
        [
            "capture",
            "--spec",
            "spec.json",
            "--repo-root",
            ".",
            "--migration-id",
            MIGRATION_ID,
            "--challenge",
            CHALLENGE,
            "--signing-key",
            "source-key",
            "--signer-identity",
            "source-host",
            "--signer-role",
            "source",
            "--attestations",
            "source-attestations.json",
            "--output",
            "source.json",
        ]
    )
    compare = parser.parse_args(
        [
            "compare",
            "--spec",
            "spec.json",
            "--source",
            "source.json",
            "--target",
            "target.json",
            "--continuity-receipt",
            "continuity.json",
            "--trust-policy",
            "trust.json",
            "--signing-key",
            "verifier-key",
            "--signer-identity",
            "migration-verifier",
            "--output",
            "report.json",
        ]
    )
    plan = parser.parse_args(
        [
            "plan",
            "--spec",
            "spec.json",
            "--report",
            "report.json",
            "--trust-policy",
            "trust.json",
            "--signing-key",
            "verifier-key",
            "--signer-identity",
            "migration-verifier",
            "--output",
            "plan.json",
        ]
    )
    assert (
        capture.handler.__name__,
        compare.handler.__name__,
        plan.handler.__name__,
    ) == ("_capture", "_compare", "_plan")
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "plan",
                "--report",
                "report.json",
                "--trust-policy",
                "trust.json",
                "--signing-key",
                "verifier-key",
                "--signer-identity",
                "migration-verifier",
                "--output",
                "plan.json",
                "--challenge-ledger",
                "alternate.json",
            ]
        )


def test_capture_does_not_mutate_repo_or_process_environment(tmp_path: Path) -> None:
    key = _key(tmp_path / "key")
    root = tmp_path / "host"
    snapshot = _prepare_host(
        root,
        key=key,
        identity="source-host",
        role="source",
        hostname="source.local",
    )
    before = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    old_environment = dict(os.environ)
    capture_host(
        spec=_spec(),
        repo_root=root,
        migration_id=MIGRATION_ID,
        challenge=CHALLENGE,
        signing_key_path=key,
        signer_identity="source-host",
        signer_role="source",
        attestations_path=root / "attestations.json",
        environment={},
        captured_at=NOW,
    )
    after = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert before == after
    assert dict(os.environ) == old_environment
    assert snapshot["schema_version"] == "volpred.host-migration-snapshot.v2"
