"""Compatibility surface for the dependency-neutral projection contract."""

from volpred.public_article_projection_contract import (
    DEFAULT_CONTRACT_PATH,
    PROJECT_ROOT,
    PublicArticleProjectionContractError,
    audit_frontend_public_article_projection_contract,
    load_public_article_projection_contract,
    public_projection_contract_evidence_matches,
)

__all__ = [
    "DEFAULT_CONTRACT_PATH",
    "PROJECT_ROOT",
    "PublicArticleProjectionContractError",
    "audit_frontend_public_article_projection_contract",
    "load_public_article_projection_contract",
    "public_projection_contract_evidence_matches",
]
