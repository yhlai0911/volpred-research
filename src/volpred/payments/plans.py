"""Membership plan catalog — single source of truth for tiers + pricing.

Mirrors the frontend `getPricingPlans()` in
`frontend-v2-fix/src/lib/radar-data.ts` (Free / Radar Plus / Research Pro).
Kept here so the payment backend, entitlement checks, and any admin tooling
read ONE definition instead of duplicating price/tier facts. If the frontend
plan list changes, update BOTH (there is a test that pins these ids/prices so
a silent drift is caught).

Prices are TWD (NT$) monthly. `role` is the Supabase `profiles.role` an active
subscriber of that plan maps to (free → 'free', paid → 'premium'). Research Pro
and Radar Plus both map to 'premium' today; a finer-grained entitlement split
(e.g. 'premium' vs 'pro') is a follow-up when the gated feature sets diverge.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    plan_id: str          # canonical id (matches frontend plan.id)
    name: str
    price_twd_monthly: int  # 0 for Free
    role: str             # Supabase profiles.role a subscriber maps to
    recurring: bool       # True → needs ECPay 定期定額 (periodic) auth


# Order matches the pricing page top-to-bottom.
PLANS: tuple[Plan, ...] = (
    Plan(plan_id="free", name="Free", price_twd_monthly=0, role="free", recurring=False),
    Plan(plan_id="radar_plus", name="Radar Plus", price_twd_monthly=299, role="premium", recurring=True),
    Plan(plan_id="research_pro", name="Research Pro", price_twd_monthly=599, role="premium", recurring=True),
)

_BY_ID = {p.plan_id: p for p in PLANS}


def plan_by_id(plan_id: str) -> Plan | None:
    return _BY_ID.get(plan_id)


def plan_for_role(role: str) -> Plan:
    """Lowest-priced plan granting `role` (used for display / downgrade logic)."""
    for plan in PLANS:
        if plan.role == role:
            return plan
    return PLANS[0]  # default Free


def role_for_plan(plan_id: str) -> str:
    plan = plan_by_id(plan_id)
    return plan.role if plan else "free"
