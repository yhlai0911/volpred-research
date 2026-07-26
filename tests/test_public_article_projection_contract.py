from __future__ import annotations

import json

import pytest

from volpred.ops.public_article_projection_contract import (
    PublicArticleProjectionContractError,
    audit_frontend_public_article_projection_contract,
    load_public_article_projection_contract,
)


EXACT = [
    "source_inspiration",
    "content_type",
    "auto_generated",
    "gap_alert_level",
    "experiment_refs",
    "view_display",
]
PREFIXES = [
    "arc_signature",
    "audience",
    "topic_cluster",
    "cluster_waiver",
    "dup_waiver",
    "release_dedup",
    "release_theme",
    "release_arc_dedup",
    "retracted",
]


def _frontend_source(exact=EXACT, prefixes=PREFIXES) -> str:
    exact_values = ",\n".join(repr(value) for value in exact)
    prefix_values = ",\n".join(repr(value) for value in prefixes)
    return (
        "const INTERNAL_DETAIL_EXACT = new Set(["
        f"{exact_values}"
        "]);\n"
        "const INTERNAL_DETAIL_PREFIXES = ["
        f"{prefix_values}"
        "];\n"
    )


def test_versioned_contract_digest_is_self_verifying() -> None:
    contract = load_public_article_projection_contract()

    assert contract["forbidden_detail_exact"] == EXACT
    assert contract["forbidden_detail_prefixes"] == PREFIXES
    assert len(contract["policy_sha256"]) == 64


def test_frontend_policy_is_mechanically_bound_to_parent_pin(
    tmp_path,
) -> None:
    frontend = tmp_path / "data-server.ts"
    frontend.write_text(_frontend_source(), encoding="utf-8")

    evidence = audit_frontend_public_article_projection_contract(frontend)

    assert evidence["matches"] is True
    assert len(evidence["policy_sha256"]) == 64


def test_frontend_policy_drift_fails_closed(tmp_path) -> None:
    frontend = tmp_path / "data-server.ts"
    frontend.write_text(
        _frontend_source(exact=[*EXACT, "new_internal_key"]),
        encoding="utf-8",
    )

    with pytest.raises(
        PublicArticleProjectionContractError,
        match="drifted from parent pin",
    ):
        audit_frontend_public_article_projection_contract(frontend)


def test_tampered_parent_policy_digest_fails_closed(tmp_path) -> None:
    contract = load_public_article_projection_contract()
    contract["forbidden_detail_exact"].append("tampered")
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")

    with pytest.raises(
        PublicArticleProjectionContractError,
        match="digest drifted",
    ):
        load_public_article_projection_contract(path)
