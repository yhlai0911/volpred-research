"""Payment integration scaffold — BUILT BUT NOT OPEN (2026-07-04).

The platform's monetization goals (trust, traffic, funnel) are not yet met, so
checkout is NOT enabled. This package is the plumbing built ahead of time so
that flipping payments on later is a config change, not a build project.

Everything is gated behind the `PAYMENTS_ENABLED` env flag (default off). While
off, `provider.create_subscription_checkout(...)` raises `PaymentsDisabledError`
so nothing can accidentally charge a user. The frontend pricing page's own
`paymentEnabled: false` per-plan flags are the second, independent gate.

Provider decision (see docs/payments_go_live_checklist.md for the full rationale):
  - PRIMARY = ECPay 綠界 — Taiwan-native, TWD, credit card + ATM + 超商 + 定期定額
    (recurring), official Python SDK. No MCP/CLI, but the right fit for a
    Taiwan-based platform charging TWD memberships.
  - ALTERNATIVE = Stripe — best AI tooling (official MCP server + CLI + agent
    toolkit, native in Claude Code) but limited Taiwan merchant support
    (card-only, payout restrictions). Kept as a future adapter behind the same
    interface if the platform goes international/USD.

Public API is intentionally small; adapters implement `PaymentProvider`.
"""
from __future__ import annotations

from .base import (
    PaymentProvider,
    PaymentsDisabledError,
    PaymentsConfigError,
    payments_enabled,
)
from .plans import PLANS, Plan, plan_by_id, plan_for_role, role_for_plan

__all__ = [
    "PaymentProvider",
    "PaymentsDisabledError",
    "PaymentsConfigError",
    "payments_enabled",
    "PLANS",
    "Plan",
    "plan_by_id",
    "plan_for_role",
    "role_for_plan",
]
