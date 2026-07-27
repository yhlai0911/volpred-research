"""Canonical timing and rolling-budget rules for provider capability probes."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class ProbeAdmissionDecision:
    acquired: bool
    reason: str
    next_probe_at: datetime | None


@dataclass(frozen=True)
class ProbePolicy:
    minimum_interval: timedelta = timedelta(minutes=5)
    maximum_backoff: timedelta = timedelta(hours=1)
    window: timedelta = timedelta(hours=1)
    max_probe_cost_units: int = 6
    probe_reservation_ttl: timedelta = timedelta(minutes=2)

    def __post_init__(self) -> None:
        if self.minimum_interval <= timedelta(0):
            raise ValueError("minimum probe interval must be positive")
        if self.maximum_backoff < self.minimum_interval:
            raise ValueError("maximum probe backoff must cover the minimum interval")
        if self.window <= timedelta(0) or self.max_probe_cost_units <= 0:
            raise ValueError("probe window and cost budget must be positive")
        if (
            self.probe_reservation_ttl <= timedelta(0)
            or self.probe_reservation_ttl > self.minimum_interval
        ):
            raise ValueError(
                "probe reservation TTL must be positive and no longer than "
                "the minimum interval"
            )

    @classmethod
    def from_seconds(
        cls,
        *,
        minimum_interval_seconds: int,
        maximum_backoff_seconds: int,
        window_seconds: int,
        max_probe_cost_units: int,
        reservation_ttl_seconds: int,
    ) -> ProbePolicy:
        return cls(
            minimum_interval=timedelta(seconds=minimum_interval_seconds),
            maximum_backoff=timedelta(seconds=maximum_backoff_seconds),
            window=timedelta(seconds=window_seconds),
            max_probe_cost_units=max_probe_cost_units,
            probe_reservation_ttl=timedelta(seconds=reservation_ttl_seconds),
        )

    def backoff_delay(self, consecutive_failures: int) -> timedelta:
        if consecutive_failures < 0:
            raise ValueError("consecutive probe failures cannot be negative")
        if consecutive_failures == 0:
            return self.minimum_interval
        ratio = (
            self.maximum_backoff.total_seconds()
            / self.minimum_interval.total_seconds()
        )
        saturation_exponent = max(0, math.ceil(math.log2(ratio)))
        exponent = max(0, consecutive_failures - 1)
        if exponent >= saturation_exponent:
            return self.maximum_backoff
        return self.minimum_interval * (2**exponent)

    def budget_next_at(
        self,
        *,
        now: datetime,
        requested_cost_units: int,
        events: list[tuple[datetime, int]],
    ) -> datetime | None:
        if requested_cost_units <= 0:
            raise ValueError("probe cost must be positive")
        active = sorted(
            (
                (occurred_at, cost)
                for occurred_at, cost in events
                if occurred_at > now - self.window
            ),
            key=lambda item: item[0],
        )
        used = sum(cost for _, cost in active)
        if used + requested_cost_units <= self.max_probe_cost_units:
            return None
        for occurred_at, cost in active:
            used -= cost
            if used + requested_cost_units <= self.max_probe_cost_units:
                return occurred_at + self.window
        return now + self.window

    def admission(
        self,
        *,
        now: datetime,
        requested_cost_units: int,
        active_until: datetime | None,
        latest_started_at: datetime | None,
        latest_next_probe_at: datetime | None,
        latest_was_healthy: bool | None,
        events: list[tuple[datetime, int]],
    ) -> ProbeAdmissionDecision:
        """Apply the one canonical ordering for probe admission gates."""
        if active_until is not None and now < active_until:
            return ProbeAdmissionDecision(
                acquired=False,
                reason="probe_in_progress",
                next_probe_at=active_until,
            )
        if latest_started_at is not None:
            interval_end = latest_started_at + self.minimum_interval
            if now < interval_end:
                return ProbeAdmissionDecision(
                    acquired=False,
                    reason="minimum_interval",
                    next_probe_at=interval_end,
                )
        if latest_next_probe_at is not None and now < latest_next_probe_at:
            return ProbeAdmissionDecision(
                acquired=False,
                reason=(
                    "minimum_interval"
                    if latest_was_healthy
                    else "backoff"
                ),
                next_probe_at=latest_next_probe_at,
            )
        budget_next = self.budget_next_at(
            now=now,
            requested_cost_units=requested_cost_units,
            events=events,
        )
        if budget_next is not None:
            return ProbeAdmissionDecision(
                acquired=False,
                reason="budget_exhausted",
                next_probe_at=budget_next,
            )
        return ProbeAdmissionDecision(
            acquired=True,
            reason="acquired",
            next_probe_at=None,
        )

    def budget_snapshot(
        self,
        *,
        now: datetime,
        events: list[tuple[datetime, int]],
    ) -> tuple[datetime, int]:
        active = sorted(
            (
                (occurred_at, cost)
                for occurred_at, cost in events
                if occurred_at > now - self.window
            ),
            key=lambda item: item[0],
        )
        if not active:
            return now, 0
        return active[0][0], sum(cost for _, cost in active)
