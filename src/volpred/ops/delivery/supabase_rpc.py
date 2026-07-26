"""Small service-role-only transport for Operations Core PostgREST RPCs."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
from urllib import error, request


_READ_ONLY_RPCS = frozenset(
    {
        "volpred_diagnose_publisher_article_compare_delete",
        "volpred_read_change_set",
        "volpred_read_change_set_by_idempotency_key",
        "volpred_read_commit_owner",
        "volpred_read_notification_owner",
        "volpred_read_publisher_article_delete_approval",
        "volpred_read_publisher_article_delete_candidate",
        "volpred_read_publisher_article_delete_owner",
        "volpred_read_publisher_article_reconcile_owner",
        "volpred_read_publisher_article_sync_owner",
        "volpred_read_work_snapshot",
    }
)


class SupabaseRpcError(RuntimeError):
    """A PostgREST RPC returned a structured database error."""


def runtime_environment() -> dict[str, str]:
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


class ServiceRoleRpcClient:
    """Call public RPC wrappers without exposing service credentials."""

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
                "Supabase URL and service-role key are required"
            )
        if timeout_seconds <= 0:
            raise ValueError("Supabase RPC timeout must be positive")
        self._timeout_seconds = timeout_seconds

    @property
    def backend_sha256(self) -> str:
        """Return a credential-free identity for the exact RPC backend."""

        return hashlib.sha256(self._url.encode("utf-8")).hexdigest()

    def call(
        self,
        function: str,
        payload: Mapping[str, object],
    ) -> object:
        if (
            function not in _READ_ONLY_RPCS
            and _remote_mutations_disabled()
        ):
            raise RuntimeError(
                "Operations Core RPC remote writes are disabled"
            )
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
            raise SupabaseRpcError(message) from None
        except (OSError, error.URLError) as exc:
            raise RuntimeError(
                f"Operations Core RPC unavailable: {exc}"
            ) from exc
        try:
            return json.loads(raw)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "Operations Core RPC returned invalid JSON"
            ) from exc


def _remote_mutations_disabled() -> bool:
    return (
        os.environ.get("VOLPRED_NO_REMOTE_WRITE") == "1"
        or "PYTEST_CURRENT_TEST" in os.environ
        or "PYTEST_VERSION" in os.environ
    )


__all__ = [
    "ServiceRoleRpcClient",
    "SupabaseRpcError",
    "runtime_environment",
]
