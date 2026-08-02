"""Service-role PostgREST adapter for provider-execution owner attestation."""

from __future__ import annotations

from volpred.ops.owner_attestation import (
    OwnerAttestation,
    OwnerAttestationContract,
    SupabaseOwnerAttestationStore,
)

ProviderOwnerAttestation = OwnerAttestation


class SupabaseProviderOwnerStore(SupabaseOwnerAttestationStore):
    """Read the exact pre-cutover Provider Execution owner attestation."""

    contract = OwnerAttestationContract(
        schema_version="provider-owner-attestation.v1",
        capability="provider.execution",
        allowed_owners=frozenset({"legacy", "operations_core"}),
        minimum_generation=1,
        contract_ref="contract://issue-12/zero-paid-provider-registry",
        rpc_name="volpred_read_provider_owner",
        label="Provider owner",
    )


__all__ = [
    "ProviderOwnerAttestation",
    "SupabaseProviderOwnerStore",
]
