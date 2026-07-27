"""Service-role PostgREST adapter for incident-lifecycle owner attestation."""

from __future__ import annotations

from volpred.ops.owner_attestation import (
    OwnerAttestation,
    OwnerAttestationContract,
    SupabaseOwnerAttestationStore,
)

IncidentOwnerAttestation = OwnerAttestation


class SupabaseIncidentOwnerStore(SupabaseOwnerAttestationStore):
    """Read the exact pre-cutover Incident Lifecycle owner attestation."""

    contract = OwnerAttestationContract(
        schema_version="incident-owner-attestation.v1",
        capability="incident.lifecycle",
        owner="legacy",
        generation=1,
        contract_ref="contract://issue-13/durable-incident-owner",
        rpc_name="volpred_read_incident_owner",
        label="Incident owner",
    )


__all__ = [
    "IncidentOwnerAttestation",
    "SupabaseIncidentOwnerStore",
]
