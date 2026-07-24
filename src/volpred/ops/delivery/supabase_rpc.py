"""Small service-role-only transport for Operations Core PostgREST RPCs."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
from urllib import error, request


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

    def call(
        self,
        function: str,
        payload: Mapping[str, object],
    ) -> object:
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


__all__ = [
    "ServiceRoleRpcClient",
    "SupabaseRpcError",
    "runtime_environment",
]
