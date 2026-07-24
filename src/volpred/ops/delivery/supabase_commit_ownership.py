"""Service-role PostgREST adapter for durable Git commit ownership."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import json
import os
from pathlib import Path
from typing import Any
from urllib import error, request

from .owned_change import CommitOwner, CommitOwnershipLost


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _owner_from_payload(payload: Mapping[str, Any]) -> CommitOwner:
    schema_version = _required_text(
        payload.get("schema_version"),
        field="commit owner schema_version",
    )
    capability = _required_text(
        payload.get("capability"),
        field="commit owner capability",
    )
    owner = _required_text(
        payload.get("owner"),
        field="commit owner",
    )
    generation = payload.get("generation")
    changed_at = _required_text(
        payload.get("changed_at"),
        field="commit owner changed_at",
    )
    if schema_version != "commit-owner.v1":
        raise ValueError("unsupported commit owner schema")
    if capability != "git.commit":
        raise ValueError("unsupported commit owner capability")
    if owner not in {"legacy", "operations_core"}:
        raise ValueError("unsupported commit owner")
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation <= 0
    ):
        raise ValueError("commit owner generation must be positive")
    try:
        observed_at = datetime.fromisoformat(changed_at)
    except ValueError as exc:
        raise ValueError(
            "commit owner changed_at must be ISO-8601"
        ) from exc
    if observed_at.tzinfo is None:
        raise ValueError("commit owner changed_at must include UTC offset")
    return CommitOwner(
        schema_version=schema_version,
        capability=capability,
        owner=owner,
        generation=generation,
        changed_at=changed_at,
        changed_by=_required_text(
            payload.get("changed_by"),
            field="commit owner changed_by",
        ),
        change_reason=_required_text(
            payload.get("change_reason"),
            field="commit owner change_reason",
        ),
    )


def _runtime_environment() -> dict[str, str]:
    values = dict(os.environ)
    env_path = Path(__file__).resolve().parents[4] / ".env.local"
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values.setdefault(key.strip(), value.strip().strip("\"'"))
    return values


def _rpc_error_message(payload: bytes) -> str | None:
    try:
        decoded = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError):
        return "response body was not valid JSON"
    if not isinstance(decoded, Mapping):
        return None
    message = decoded.get("message")
    return message if isinstance(message, str) else None


class SupabaseCommitOwnerStore:
    """Read and CAS-transfer Git ownership through service-role-only RPCs."""

    def __init__(
        self,
        *,
        supabase_url: str,
        service_role_key: str,
        timeout_seconds: float = 45.0,
    ) -> None:
        self._url = supabase_url.strip().rstrip("/")
        self._key = service_role_key.strip()
        if not self._url or not self._key:
            raise ValueError(
                "Supabase URL and service-role key are required for "
                "commit ownership"
            )
        if timeout_seconds <= 0:
            raise ValueError("Supabase RPC timeout must be positive")
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_environment(cls) -> SupabaseCommitOwnerStore:
        values = _runtime_environment()
        return cls(
            supabase_url=values.get("SUPABASE_URL", ""),
            service_role_key=values.get("SUPABASE_SERVICE_ROLE_KEY", ""),
            timeout_seconds=float(
                values.get("VOLPRED_OPERATIONS_RPC_TIMEOUT_SEC", "45")
            ),
        )

    def read_owner(self) -> CommitOwner:
        return _owner_from_payload(
            self._rpc("volpred_read_commit_owner", {})
        )

    def transfer_owner(
        self,
        *,
        expected_owner: str,
        expected_generation: int,
        target_owner: str,
        actor_ref: str,
        reason: str,
        rollback_of_generation: int | None = None,
    ) -> CommitOwner:
        return _owner_from_payload(
            self._rpc(
                "volpred_transfer_commit_owner",
                {
                    "p_expected_owner": expected_owner,
                    "p_expected_generation": expected_generation,
                    "p_target_owner": target_owner,
                    "p_actor_ref": actor_ref,
                    "p_reason": reason,
                    "p_rollback_of_generation": rollback_of_generation,
                },
            )
        )

    def _rpc(
        self,
        function: str,
        payload: Mapping[str, object],
    ) -> Mapping[str, Any]:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        call = request.Request(
            f"{self._url}/rest/v1/rpc/{function}",
            data=encoded,
            method="POST",
            headers={
                "apikey": self._key,
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with request.urlopen(
                call,
                timeout=self._timeout_seconds,
            ) as response:
                raw = response.read()
        except error.HTTPError as exc:
            raw = exc.read()
            message = _rpc_error_message(raw) or f"HTTP {exc.code}"
            if message.startswith(
                (
                    "commit ownership",
                    "operations core does not own git.commit",
                )
            ):
                raise CommitOwnershipLost(message) from None
            raise RuntimeError(f"commit ownership RPC failed: {message}")
        except (OSError, error.URLError) as exc:
            raise RuntimeError(
                f"commit ownership RPC unavailable: {exc}"
            ) from exc
        try:
            decoded = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "commit ownership RPC returned invalid JSON"
            ) from exc
        if not isinstance(decoded, Mapping):
            raise RuntimeError(
                "commit ownership RPC returned a non-object response"
            )
        return decoded


__all__ = ["SupabaseCommitOwnerStore"]
