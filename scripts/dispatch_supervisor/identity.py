"""Stable identities shared by the hourly dispatcher and its Codex failover."""
from __future__ import annotations


_CLAIM_OWNER_ROLES = frozenset({"hourly", "codex-failover"})


def task_claim_owner(*, role: str, slot_id: str, job_id: str) -> str:
    """Return the unique, retry-stable owner for one reserved supervisor fire.

    The task-pool owner is an ownership token, not a display label.  It must be
    unique across simultaneous slots and remain unchanged when the same fire
    moves from one retry attempt to the next.  The reservation's slot/job pair
    supplies exactly those semantics.

    Codex roles intentionally retain the ``codex-`` prefix: task_pool_claim.py
    uses it to enforce the mechanical Codex eligibility gate.
    """
    normalized_role = str(role or "").strip().lower()
    normalized_slot = str(slot_id or "").strip()
    normalized_job = str(job_id or "").strip()
    if normalized_role not in _CLAIM_OWNER_ROLES:
        raise ValueError(f"unsupported task-claim owner role: {role!r}")
    if not normalized_slot or not normalized_job:
        raise ValueError("task-claim owner requires non-empty slot_id and job_id")
    return f"{normalized_role}-{normalized_slot}-{normalized_job}"


def task_claim_owners_for_job(*, slot_id: str, job_id: str) -> tuple[str, ...]:
    """Every owner token one supervisor fire could have issued for this slot.

    A fire starts on Claude (``hourly``) and may hand the SAME slot/job to the
    Codex failover mid-flight, so a reclaim path that only knows slot+job (the
    health monitor's kill path — it never sees which executor actually claimed)
    must consider both roles.  Deterministically ordered so logs are stable.
    """
    return tuple(
        task_claim_owner(role=role, slot_id=slot_id, job_id=job_id)
        for role in sorted(_CLAIM_OWNER_ROLES)
    )
