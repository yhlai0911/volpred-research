"""Ed25519 trust boundary for host-migration evidence.

Integrity hashes beside JSON are not attestations: an attacker can edit both.
This module signs canonical JSON with a host-local Ed25519 private key and
verifies it against an operator-supplied, time-bounded public trust policy.
Private key material is never returned or copied into a migration artifact.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

TRUST_POLICY_SCHEMA = "volpred.host-migration-trust.v1"
ATTESTATION_SCHEMA = "volpred.ed25519-attestation.v1"
CHALLENGE_LEDGER_SCHEMA = "volpred.host-migration-challenge-ledger.v1"
MAX_TRUST_POLICY_WINDOW_SECONDS = 3600
REQUIRED_SIGNER_ROLES = frozenset(
    {"source", "target", "verifier", "continuity_verifier"}
)
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}")
_ROLE = re.compile(r"[a-z][a-z0-9._-]{2,63}")


class HostAttestationError(ValueError):
    """Raised when signed evidence is malformed, untrusted, or invalid."""


@dataclass(frozen=True)
class TrustedSigner:
    identity: str
    role: str
    public_key: str
    public_key_fingerprint: str


@dataclass(frozen=True)
class TrustPolicy:
    migration_id: str
    challenge: str
    valid_from: datetime
    valid_until: datetime
    signers: tuple[TrustedSigner, ...]
    sha256: str

    def signer(self, *, identity: str, role: str) -> TrustedSigner:
        matches = [
            item
            for item in self.signers
            if item.identity == identity and item.role == role
        ]
        if len(matches) != 1:
            raise HostAttestationError(
                f"trust policy has no unique {role!r} signer {identity!r}"
            )
        return matches[0]


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _parse_utc(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise HostAttestationError(f"{field} must be an ISO-8601 string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise HostAttestationError(f"{field} is not ISO-8601") from None
    if parsed.tzinfo is None:
        raise HostAttestationError(f"{field} must include a UTC offset")
    return parsed.astimezone(UTC)


def _load_public_key(text: str) -> Ed25519PublicKey:
    try:
        key = serialization.load_ssh_public_key(text.encode("ascii"))
    except (ValueError, TypeError):
        raise HostAttestationError("public key is not valid OpenSSH") from None
    if not isinstance(key, Ed25519PublicKey):
        raise HostAttestationError("only Ed25519 host attestation keys are allowed")
    return key


def public_key_fingerprint(public_key_text: str) -> str:
    key = _load_public_key(public_key_text)
    raw = key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return "SHA256:" + base64.b64encode(hashlib.sha256(raw).digest()).decode(
        "ascii"
    ).rstrip("=")


def _private_key(path: Path) -> Ed25519PrivateKey:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise HostAttestationError(f"signing key unavailable: {exc}") from None
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise HostAttestationError("signing key must be a regular file")
        if stat.S_IMODE(before.st_mode) & 0o077:
            raise HostAttestationError(
                "signing key permissions must be 0600 or stricter"
            )
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = -1
            data = handle.read()
            after = os.fstat(handle.fileno())
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise HostAttestationError("signing key changed while it was read")
        key = serialization.load_ssh_private_key(data, password=None)
    except (OSError, ValueError, TypeError) as exc:
        if isinstance(exc, HostAttestationError):
            raise
        raise HostAttestationError(
            "signing key is unreadable, encrypted, or malformed"
        ) from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(key, Ed25519PrivateKey):
        raise HostAttestationError("only Ed25519 host attestation keys are allowed")
    return key


def public_key_from_private(path: Path) -> str:
    key = _private_key(path)
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    ).decode("ascii")


def sign_mapping(
    payload: Mapping[str, Any],
    *,
    private_key_path: Path,
    signer_identity: str,
    signer_role: str,
) -> dict[str, Any]:
    if not _IDENTITY.fullmatch(signer_identity):
        raise HostAttestationError("invalid signer identity")
    if not _ROLE.fullmatch(signer_role):
        raise HostAttestationError("invalid signer role")
    if "attestation" in payload:
        raise HostAttestationError("payload is already attested")
    key = _private_key(private_key_path)
    public_text = key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    ).decode("ascii")
    signature = key.sign(canonical_json_bytes(dict(payload)))
    return {
        "schema_version": ATTESTATION_SCHEMA,
        "signer_identity": signer_identity,
        "signer_role": signer_role,
        "public_key_fingerprint": public_key_fingerprint(public_text),
        "signature_base64": base64.b64encode(signature).decode("ascii"),
    }


def load_trust_policy(path: Path) -> TrustPolicy:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HostAttestationError(f"trust policy unreadable: {exc}") from None
    allowed = {
        "schema_version",
        "migration_id",
        "challenge",
        "valid_from",
        "valid_until",
        "signers",
    }
    if not isinstance(payload, dict) or set(payload) != allowed:
        raise HostAttestationError("trust policy fields are malformed")
    if payload["schema_version"] != TRUST_POLICY_SCHEMA:
        raise HostAttestationError("unsupported trust policy schema")
    migration_id = payload["migration_id"]
    challenge = payload["challenge"]
    if not isinstance(migration_id, str) or not _IDENTITY.fullmatch(migration_id):
        raise HostAttestationError("invalid migration id")
    if (
        not isinstance(challenge, str)
        or len(challenge) < 32
        or len(challenge) > 256
        or not re.fullmatch(r"[A-Za-z0-9._:-]+", challenge)
    ):
        raise HostAttestationError("challenge must be a 32-256 character nonce")
    valid_from = _parse_utc(payload["valid_from"], field="valid_from")
    valid_until = _parse_utc(payload["valid_until"], field="valid_until")
    if valid_until <= valid_from:
        raise HostAttestationError("trust policy validity window is inverted")
    if (
        valid_until - valid_from
    ).total_seconds() > MAX_TRUST_POLICY_WINDOW_SECONDS:
        raise HostAttestationError("trust policy validity window exceeds one hour")
    raw_signers = payload["signers"]
    if not isinstance(raw_signers, list) or len(raw_signers) < 4:
        raise HostAttestationError(
            "trust policy needs four independently keyed signer roles"
        )
    signers: list[TrustedSigner] = []
    seen: set[tuple[str, str]] = set()
    fingerprints: set[str] = set()
    for item in raw_signers:
        if not isinstance(item, dict) or set(item) != {
            "identity",
            "role",
            "public_key",
        }:
            raise HostAttestationError("trust signer fields are malformed")
        identity = item["identity"]
        role = item["role"]
        public_key = item["public_key"]
        if not isinstance(identity, str) or not _IDENTITY.fullmatch(identity):
            raise HostAttestationError("invalid trusted signer identity")
        if not isinstance(role, str) or not _ROLE.fullmatch(role):
            raise HostAttestationError("invalid trusted signer role")
        if not isinstance(public_key, str):
            raise HostAttestationError("trusted public key must be text")
        key = (identity, role)
        if key in seen:
            raise HostAttestationError("trusted signer identity/role is duplicated")
        seen.add(key)
        fingerprint = public_key_fingerprint(public_key)
        if fingerprint in fingerprints:
            raise HostAttestationError(
                "every signer role requires a unique public key fingerprint"
            )
        fingerprints.add(fingerprint)
        signers.append(
            TrustedSigner(
                identity=identity,
                role=role,
                public_key=public_key,
                public_key_fingerprint=fingerprint,
            )
        )
    roles = {item.role for item in signers}
    if roles != REQUIRED_SIGNER_ROLES:
        raise HostAttestationError(
            "trust policy signer roles must be source, target, verifier, "
            "and continuity_verifier exactly"
        )
    return TrustPolicy(
        migration_id=migration_id,
        challenge=challenge,
        valid_from=valid_from,
        valid_until=valid_until,
        signers=tuple(signers),
        sha256=sha256_json(payload),
    )


def verify_mapping(
    payload: Mapping[str, Any],
    *,
    trust_policy: TrustPolicy,
    expected_role: str,
) -> TrustedSigner:
    if "attestation" not in payload:
        raise HostAttestationError("signed payload has no attestation")
    attestation = payload["attestation"]
    if not isinstance(attestation, dict) or set(attestation) != {
        "schema_version",
        "signer_identity",
        "signer_role",
        "public_key_fingerprint",
        "signature_base64",
    }:
        raise HostAttestationError("attestation fields are malformed")
    if attestation["schema_version"] != ATTESTATION_SCHEMA:
        raise HostAttestationError("unsupported attestation schema")
    if attestation["signer_role"] != expected_role:
        raise HostAttestationError("attestation signer role mismatch")
    signer = trust_policy.signer(
        identity=attestation["signer_identity"],
        role=expected_role,
    )
    if attestation["public_key_fingerprint"] != signer.public_key_fingerprint:
        raise HostAttestationError("attestation public key fingerprint mismatch")
    unsigned = dict(payload)
    unsigned.pop("attestation")
    try:
        signature = base64.b64decode(
            attestation["signature_base64"],
            validate=True,
        )
    except (TypeError, ValueError):
        raise HostAttestationError("attestation signature is not base64") from None
    try:
        _load_public_key(signer.public_key).verify(
            signature,
            canonical_json_bytes(unsigned),
        )
    except InvalidSignature:
        raise HostAttestationError("attestation signature verification failed") from None
    return signer


def ensure_trust_policy_current(
    policy: TrustPolicy,
    *,
    now: datetime | None = None,
) -> None:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if current < policy.valid_from or current > policy.valid_until:
        raise HostAttestationError("trust policy is not currently valid")


def challenge_consumption_id(policy: TrustPolicy) -> str:
    """Return the non-secret identity used to enforce one-time challenge use."""

    material = f"{policy.migration_id}\0{policy.challenge}".encode()
    return hashlib.sha256(material).hexdigest()


def _atomic_write_private(path: Path, data: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:  # silent-ok: os.replace consumed the temp file
            pass


def _read_private_regular(path: Path) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise HostAttestationError(f"canonical evidence unreadable: {exc}") from None
    try:
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = -1
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise HostAttestationError(
                    "canonical evidence must be a regular file"
                )
            return handle.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def persist_challenge_evidence(
    policy: TrustPolicy,
    *,
    state_dir: Path,
    purpose: str,
    evidence_sha256: str,
    evidence: Mapping[str, Any],
    consumed_at: datetime,
) -> str:
    """Durably persist one canonical plan and consume its host-wide challenge."""

    if not _ROLE.fullmatch(purpose):
        raise HostAttestationError("challenge purpose is malformed")
    if not re.fullmatch(r"[0-9a-f]{64}", evidence_sha256):
        raise HostAttestationError("challenge evidence identity is malformed")
    ensure_trust_policy_current(policy, now=consumed_at)
    if state_dir.is_symlink():
        raise HostAttestationError("canonical migration state must not be a symlink")
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not state_dir.is_dir():
        raise HostAttestationError("canonical migration state is not a directory")
    os.chmod(state_dir, 0o700)
    plans_dir = state_dir / "plans"
    if plans_dir.is_symlink():
        raise HostAttestationError("canonical plan directory must not be a symlink")
    plans_dir.mkdir(exist_ok=True, mode=0o700)
    os.chmod(plans_dir, 0o700)
    ledger_path = state_dir / "challenge_ledger.json"
    evidence_id = challenge_consumption_id(policy)
    evidence_path = plans_dir / f"{evidence_id}.json"
    lock_path = state_dir / ".challenge_ledger.lock"
    try:
        lock_fd = os.open(
            lock_path,
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
            0o600,
        )
    except OSError as exc:
        raise HostAttestationError(f"challenge ledger lock failed: {exc}") from None
    try:
        os.fchmod(lock_fd, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        ledger: dict[str, Any] = {
            "schema_version": CHALLENGE_LEDGER_SCHEMA,
            "consumptions": {},
        }
        if ledger_path.exists():
            try:
                ledger = json.loads(_read_private_regular(ledger_path))
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                TypeError,
            ) as exc:
                if isinstance(exc, HostAttestationError):
                    raise
                raise HostAttestationError(
                    f"challenge ledger is unreadable: {exc}"
                ) from None
        if (
            not isinstance(ledger, dict)
            or set(ledger) != {"schema_version", "consumptions"}
            or ledger["schema_version"] != CHALLENGE_LEDGER_SCHEMA
            or not isinstance(ledger["consumptions"], dict)
        ):
            raise HostAttestationError("challenge ledger fields are malformed")
        if evidence_id in ledger["consumptions"]:
            raise HostAttestationError("migration challenge was already consumed")
        evidence_bytes = canonical_json_bytes(dict(evidence)) + b"\n"
        if evidence_path.exists() or evidence_path.is_symlink():
            existing = _read_private_regular(evidence_path)
            if existing != evidence_bytes:
                raise HostAttestationError(
                    "migration challenge has conflicting canonical evidence"
                )
            raise HostAttestationError(
                "migration challenge evidence already exists without a ledger "
                "receipt; use the canonical plan for recovery"
            )
        _atomic_write_private(evidence_path, evidence_bytes)
        ledger["consumptions"][evidence_id] = {
            "migration_id": policy.migration_id,
            "trust_policy_sha256": policy.sha256,
            "purpose": purpose,
            "evidence_sha256": evidence_sha256,
            "evidence_path": evidence_path.relative_to(state_dir).as_posix(),
            "consumed_at": consumed_at.astimezone(UTC).isoformat(),
        }
        _atomic_write_private(
            ledger_path,
            canonical_json_bytes(ledger) + b"\n",
        )
        return evidence_id
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def write_private_key(path: Path, key: Ed25519PrivateKey) -> None:
    """Test/setup helper: durably write one mode-0600 OpenSSH private key."""

    if path.exists() or path.is_symlink():
        raise HostAttestationError("refusing to overwrite an attestation key")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        data = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)
