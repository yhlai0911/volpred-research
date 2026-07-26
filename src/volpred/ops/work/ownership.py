"""Durable owner identity for the Work Coordinator mutation capability."""

from __future__ import annotations

from dataclasses import dataclass


class WorkOwnershipLost(RuntimeError):
    """The requested Work Coordinator owner generation is no longer current."""


@dataclass(frozen=True)
class WorkOwner:
    schema_version: str
    capability: str
    owner: str
    generation: int
    cutover_manifest_sha256: str | None
    changed_at: str
    changed_by: str
    change_reason: str

    @property
    def owner_ref(self) -> str:
        return f"work-owner:{self.capability}:generation-{self.generation}"


__all__ = ["WorkOwner", "WorkOwnershipLost"]
