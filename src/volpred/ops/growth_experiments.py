"""Receipt-backed Operations Core client for natural-growth experiments."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from volpred.ops.delivery.supabase_rpc import (
    ServiceRoleRpcClient,
    runtime_environment,
)

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")
_CLOSE_REASONS = frozenset(
    {"window_ended", "stop_rule_reached", "manual_safety_stop"}
)


class _RpcClient(Protocol):
    def call(
        self,
        function: str,
        payload: Mapping[str, object],
    ) -> object: ...


def _timestamp(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"growth {field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(
            f"growth {field} must be an ISO-8601 timestamp"
        ) from None
    if parsed.tzinfo is None:
        raise ValueError(f"growth {field} must include a timezone")
    return value


def _identifier(value: str, field: str) -> str:
    normalized = value.strip()
    if not _ID.fullmatch(normalized):
        raise ValueError(f"growth {field} is invalid")
    return normalized


def _digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "\\x" + hashlib.sha256(encoded).hexdigest()


class GrowthExperimentRegistry:
    """Expose the lifecycle without exposing tables or ad-hoc SQL."""

    def __init__(
        self,
        *,
        rpc: _RpcClient
        | Callable[[str, Mapping[str, object]], object],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._rpc = rpc
        self._clock = clock or (lambda: datetime.now(UTC))

    @classmethod
    def from_environment(cls) -> GrowthExperimentRegistry:
        values = runtime_environment()
        return cls(
            rpc=ServiceRoleRpcClient(
                supabase_url=values.get("SUPABASE_URL", ""),
                service_role_key=values.get(
                    "SUPABASE_SERVICE_ROLE_KEY", ""
                ),
                timeout_seconds=float(
                    values.get(
                        "VOLPRED_OPERATIONS_RPC_TIMEOUT_SEC", "45"
                    )
                ),
            )
        )

    def _call(
        self,
        function: str,
        payload: Mapping[str, object],
    ) -> object:
        caller = getattr(self._rpc, "call", self._rpc)
        return caller(function, payload)

    @staticmethod
    def _receipt(
        value: object,
        *,
        command_id: str,
        action: str,
        experiment_id: str,
        status: str,
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise TypeError("growth command returned an invalid receipt")
        expected = {
            "contract": "growth-command-receipt.v1",
            "command_id": command_id,
            "action": action,
            "experiment_id": experiment_id,
            "status": status,
        }
        if any(value.get(key) != expected_value for key, expected_value in expected.items()):
            raise RuntimeError("growth command returned an invalid receipt")
        if not isinstance(value.get("duplicate"), bool):
            raise TypeError("growth command returned an invalid receipt")
        _timestamp(value.get("applied_at"), "receipt applied_at")
        return dict(value)

    def _command(
        self,
        *,
        command_id: str,
        action: str,
        payload: Mapping[str, object],
        observed_at: str,
        status: str,
    ) -> dict[str, Any]:
        command = _identifier(command_id, "command_id")
        experiment = _identifier(
            str(payload.get("experiment_id", "")),
            "experiment_id",
        )
        observed = _timestamp(observed_at, "observed_at")
        result = self._call(
            "command_volpred_growth_experiment",
            {
                "p_command_id": command,
                "p_action": action,
                "p_payload": dict(payload),
                "p_request_digest": _digest(payload),
                "p_now": observed,
            },
        )
        return self._receipt(
            result,
            command_id=command,
            action=action,
            experiment_id=experiment,
            status=status,
        )

    def preregister(
        self,
        *,
        command_id: str,
        spec: Mapping[str, object],
    ) -> dict[str, Any]:
        if spec.get("status") != "preregistered":
            raise ValueError("growth spec status must be preregistered")
        preregistered_at = _timestamp(
            spec.get("preregistered_at"),
            "preregistered_at",
        )
        return self._command(
            command_id=command_id,
            action="preregister",
            payload=spec,
            observed_at=preregistered_at,
            status="preregistered",
        )

    def preregister_template(
        self,
        *,
        command_id: str,
        template: Mapping[str, object],
    ) -> dict[str, Any]:
        """Materialize the receipt timestamp without backdating the template."""

        if "preregistered_at" in template:
            raise ValueError(
                "growth preregistration template must not contain "
                "preregistered_at"
            )
        existing = self.read_command_receipt(command_id)
        if existing is not None:
            if existing.get("action") != "preregister":
                raise RuntimeError(
                    "growth command_id was reused for another action"
                )
            stored_payload = existing.get("request_payload")
            if not isinstance(stored_payload, Mapping):
                raise RuntimeError(
                    "growth command receipt omitted its request payload"
                )
            stored_template = dict(stored_payload)
            stored_template.pop("preregistered_at", None)
            if stored_template != dict(template):
                raise RuntimeError(
                    "growth command_id was reused for another template"
                )
            receipt = existing.get("receipt")
            if not isinstance(receipt, Mapping):
                raise RuntimeError(
                    "growth command receipt readback is invalid"
                )
            recovered = self._receipt(
                receipt,
                command_id=_identifier(command_id, "command_id"),
                action="preregister",
                experiment_id=_identifier(
                    str(template.get("experiment_id", "")),
                    "experiment_id",
                ),
                status="preregistered",
            )
            recovered["duplicate"] = True
            return recovered
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("growth registry clock must include a timezone")
        observed_at = (
            now.astimezone(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
        if observed_at.endswith(".000000Z"):
            observed_at = observed_at.replace(".000000Z", "Z")
        materialized = dict(template)
        materialized["preregistered_at"] = observed_at
        return self.preregister(
            command_id=command_id,
            spec=materialized,
        )

    def read_command_receipt(
        self,
        command_id: str,
    ) -> dict[str, Any] | None:
        normalized = _identifier(command_id, "command_id")
        result = self._call(
            "read_volpred_growth_command_receipt",
            {"p_command_id": normalized},
        )
        if result is None:
            return None
        if (
            not isinstance(result, Mapping)
            or result.get("contract")
            != "growth-command-receipt-read.v1"
            or result.get("command_id") != normalized
            or result.get("action")
            not in {"preregister", "activate", "stop", "close"}
            or not isinstance(result.get("request_payload"), Mapping)
            or not isinstance(result.get("receipt"), Mapping)
        ):
            raise RuntimeError(
                "growth command receipt readback is invalid"
            )
        return dict(result)

    def activate(
        self,
        *,
        command_id: str,
        experiment_id: str,
        observed_at: str,
    ) -> dict[str, Any]:
        return self._command(
            command_id=command_id,
            action="activate",
            payload={"experiment_id": experiment_id},
            observed_at=observed_at,
            status="active",
        )

    def close(
        self,
        *,
        command_id: str,
        experiment_id: str,
        reason: str,
        observed_at: str,
    ) -> dict[str, Any]:
        if reason not in _CLOSE_REASONS:
            raise ValueError("growth close reason is invalid")
        return self._command(
            command_id=command_id,
            action="close",
            payload={
                "experiment_id": experiment_id,
                "reason": reason,
            },
            observed_at=observed_at,
            status="closed",
        )

    def stop(
        self,
        *,
        command_id: str,
        experiment_id: str,
        reason: str,
        observed_at: str,
    ) -> dict[str, Any]:
        if reason not in _CLOSE_REASONS:
            raise ValueError("growth stop reason is invalid")
        return self._command(
            command_id=command_id,
            action="stop",
            payload={
                "experiment_id": experiment_id,
                "reason": reason,
            },
            observed_at=observed_at,
            status="observing",
        )

    def read(self, experiment_id: str) -> dict[str, Any]:
        normalized = _identifier(experiment_id, "experiment_id")
        result = self._call(
            "read_volpred_growth_experiment",
            {"p_experiment_id": normalized},
        )
        if (
            not isinstance(result, Mapping)
            or result.get("contract") != "growth-experiment-read.v1"
            or result.get("experiment_id") != normalized
            or result.get("status")
            not in {"preregistered", "active", "observing", "closed"}
        ):
            raise RuntimeError("growth registry returned an invalid snapshot")
        return dict(result)


__all__ = ["GrowthExperimentRegistry"]
