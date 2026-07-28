from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from volpred.ops.execution.registry import (
    DEFAULT_REGISTRY_PATH,
    authorize_provider_spawn,
)


CONTRACT_CASES = (
    ("execution-brief.claude", "claude-opus-5", "claude-cli"),
    ("execution-brief.codex", "gpt-5.6-sol", "codex-cli"),
    ("lazypack.codex", "gpt-5.6-sol", "codex-cli"),
    ("lazypack.agy", "gemini-3.6-flash-high", "agy-cli"),
    ("trending-scan.agy", "gemini-3.6-flash-high", "agy-cli"),
    ("member-qa-adjudicator.agy", "gemini-3.6-flash-high", "agy-cli"),
    ("prepublish-audit.agy", "gemini-3.6-flash-high", "agy-cli"),
    ("bounded-codex.agentic", "gpt-5.6-sol", "codex-cli"),
    ("telegram-responder.claude", "claude-opus-5", "claude-cli"),
    ("telegram-responder.codex", "gpt-5.6-sol", "codex-cli"),
)


@pytest.fixture
def portable_registry(tmp_path: Path) -> Path:
    payload = json.loads(DEFAULT_REGISTRY_PATH.read_text())
    executable = str(Path(sys.executable).resolve())
    executable_sha = hashlib.sha256(Path(executable).read_bytes()).hexdigest()
    for provider in payload["providers"]:
        provider["executables"] = [
            {"realpath": executable, "sha256": executable_sha}
        ]
    path = tmp_path / "provider_registry.json"
    path.write_text(json.dumps(payload))
    return path


@pytest.mark.parametrize(
    ("contract_id", "model_id", "provider_id"),
    CONTRACT_CASES,
)
def test_every_business_launcher_has_an_explicit_zero_paid_contract(
    portable_registry: Path,
    contract_id: str,
    model_id: str,
    provider_id: str,
) -> None:
    receipt = authorize_provider_spawn(
        contract_id=contract_id,
        model_id=model_id,
        executable_path=sys.executable,
        environment={},
        path=portable_registry,
    )

    assert receipt.contract_id == contract_id
    assert receipt.provider_id == provider_id
    assert receipt.formal_gate_eligible is False
    assert receipt.environment()["VOLPRED_PROVIDER_REGISTRY_SHA256"]
