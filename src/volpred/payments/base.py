"""Provider-agnostic payment interface + the master OFF switch.

`PAYMENTS_ENABLED` (env, default off) is the single kill switch. Any adapter
method that would move money or create a chargeable checkout MUST call
`require_payments_enabled()` first, so the feature cannot be triggered while the
platform's monetization goals are unmet — even if a caller wires up the UI by
mistake. Read-only helpers (building a plan list, verifying a callback signature
for reconciliation) are allowed while disabled.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class PaymentsDisabledError(RuntimeError):
    """Raised when a chargeable action is attempted while PAYMENTS_ENABLED is off."""


class PaymentsConfigError(RuntimeError):
    """Raised when required provider credentials/config are missing."""


def payments_enabled() -> bool:
    """True only if PAYMENTS_ENABLED is explicitly set truthy. Default: OFF.

    Deliberately strict — the platform is not ready to charge (goals unmet),
    so anything other than an explicit opt-in reads as disabled.
    """
    return os.environ.get("PAYMENTS_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def require_payments_enabled() -> None:
    if not payments_enabled():
        raise PaymentsDisabledError(
            "payments are not enabled (PAYMENTS_ENABLED is off). This scaffold is "
            "built ahead of the platform's monetization goals being met and is "
            "intentionally not open. See docs/payments_go_live_checklist.md."
        )


@dataclass(frozen=True)
class CheckoutRequest:
    plan_id: str
    order_no: str                 # merchant-side unique order id
    amount_twd: int
    item_name: str
    return_url: str               # where the provider POSTs the async result (server)
    client_back_url: str          # where the buyer's browser returns (client)
    user_id: str | None = None    # Supabase auth uid, for reconciliation
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckoutResponse:
    provider: str
    action_url: str               # form POST target (the buyer's browser submits here)
    fields: dict[str, str]        # hidden form fields incl. the signature
    order_no: str


class PaymentProvider(ABC):
    """One implementation per gateway (ECPay, later Stripe)."""

    name: str = "base"

    @abstractmethod
    def create_subscription_checkout(self, req: CheckoutRequest) -> CheckoutResponse:
        """Build the params + signature for a (recurring) checkout. MUST call
        `require_payments_enabled()` before returning anything chargeable."""

    @abstractmethod
    def verify_callback(self, params: dict[str, str]) -> bool:
        """Verify a provider async-notification signature. Read-only — allowed
        even while payments are disabled, so reconciliation/testing works."""
