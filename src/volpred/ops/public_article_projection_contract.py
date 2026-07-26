"""Versioned parent-side contract for reader-visible article details."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTRACT_PATH = (
    PROJECT_ROOT / "config" / "public_article_projection_contract.json"
)
_EXACT_BLOCK = re.compile(
    r"const INTERNAL_DETAIL_EXACT = new Set\(\[(.*?)\]\);",
    re.DOTALL,
)
_PREFIX_BLOCK = re.compile(
    r"const INTERNAL_DETAIL_PREFIXES = \[(.*?)\];",
    re.DOTALL,
)
_QUOTED_VALUE = re.compile(r"['\"]([^'\"]+)['\"]")


class PublicArticleProjectionContractError(RuntimeError):
    """The versioned parent/frontend projection policies do not agree."""


def load_public_article_projection_contract(
    path: Path = DEFAULT_CONTRACT_PATH,
) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublicArticleProjectionContractError(
            f"public article projection contract unavailable: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise PublicArticleProjectionContractError(
            "public article projection contract must be an object"
        )
    exact = payload.get("forbidden_detail_exact")
    prefixes = payload.get("forbidden_detail_prefixes")
    if (
        payload.get("schema_version")
        != "public-article-projection-contract.v1"
        or not _valid_unique_strings(exact)
        or not _valid_unique_strings(prefixes)
    ):
        raise PublicArticleProjectionContractError(
            "public article projection contract has invalid fields"
        )
    canonical = {
        "schema_version": payload["schema_version"],
        "forbidden_detail_exact": exact,
        "forbidden_detail_prefixes": prefixes,
    }
    digest = hashlib.sha256(
        json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    if payload.get("policy_sha256") != digest:
        raise PublicArticleProjectionContractError(
            "public article projection contract digest drifted"
        )
    return {
        **canonical,
        "policy_sha256": digest,
    }


def audit_frontend_public_article_projection_contract(
    frontend_source: Path,
    *,
    contract_path: Path = DEFAULT_CONTRACT_PATH,
) -> dict:
    """Fail closed when the nested frontend policy drifts from the parent pin."""

    contract = load_public_article_projection_contract(contract_path)
    try:
        source = frontend_source.read_text(encoding="utf-8")
    except OSError as exc:
        raise PublicArticleProjectionContractError(
            f"frontend projection source unavailable: {frontend_source}"
        ) from exc
    exact = _extract_policy_values(source, _EXACT_BLOCK, "exact")
    prefixes = _extract_policy_values(
        source,
        _PREFIX_BLOCK,
        "prefix",
    )
    if (
        exact != contract["forbidden_detail_exact"]
        or prefixes != contract["forbidden_detail_prefixes"]
    ):
        raise PublicArticleProjectionContractError(
            "nested frontend INTERNAL_DETAIL policy drifted from parent pin"
        )
    return {
        "schema_version": contract["schema_version"],
        "policy_sha256": contract["policy_sha256"],
        "frontend_source": str(frontend_source),
        "matches": True,
    }


def public_projection_contract_evidence_matches(
    value: object,
    *,
    contract_path: Path = DEFAULT_CONTRACT_PATH,
) -> bool:
    contract = load_public_article_projection_contract(contract_path)
    return bool(
        isinstance(value, Mapping)
        and value.get("matches") is True
        and value.get("schema_version") == contract["schema_version"]
        and value.get("policy_sha256") == contract["policy_sha256"]
    )


def _extract_policy_values(
    source: str,
    block_pattern: re.Pattern[str],
    label: str,
) -> list[str]:
    match = block_pattern.search(source)
    if match is None:
        raise PublicArticleProjectionContractError(
            f"frontend {label} policy block is missing"
        )
    values = _QUOTED_VALUE.findall(match.group(1))
    if not _valid_unique_strings(values):
        raise PublicArticleProjectionContractError(
            f"frontend {label} policy block is invalid"
        )
    return values


def _valid_unique_strings(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item for item in value)
        and len(value) == len(set(value))
    )


__all__ = [
    "PublicArticleProjectionContractError",
    "audit_frontend_public_article_projection_contract",
    "load_public_article_projection_contract",
    "public_projection_contract_evidence_matches",
]
