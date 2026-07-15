from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

from PIL import Image


HERE = Path(__file__).resolve().parent
RESULTS = HERE / "k1396_results.json"
AUDIT = HERE / "k1396_scope_audit.json"
EXPECTED_RESULT_SHA = "c2816e6e0d2a2f7b18d3b78421e342ff9606c8c39fd5fab9064574042c7c1a10"
EXPECTED_K1379_SHA = "bc430da7b03ba23a0090b246641a0a5899b712281c80dc8551befe1b844b8517"


def _load_scope_repair():
    spec = importlib.util.spec_from_file_location("k1396_scope_repair", HERE / "scope_repair.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_historical_result_is_byte_preserved() -> None:
    assert hashlib.sha256(RESULTS.read_bytes()).hexdigest() == EXPECTED_RESULT_SHA


def test_scope_audit_contract_matches_frozen_and_corrected_evidence() -> None:
    payload = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert payload["status"] == "SUPERSEDED_HISTORICAL_DIAGNOSTIC_ONLY"
    assert payload["public_claim_verdict"] == "FAIL_PUBLIC_CLAIM"
    assert payload["historical_artifact"]["sha256"] == EXPECTED_RESULT_SHA
    assert payload["protocol_scope"]["canonical_intraday_realized_variance"] is False
    assert payload["protocol_scope"]["matches_k988_exactly"] is False
    assert payload["superseded_by"]["experiment_id"] == "K1379"
    assert payload["superseded_by"]["results_sha256"] == EXPECTED_K1379_SHA
    corrected = payload["superseded_by"]["a4f_vs_daily_r2_har"]
    assert corrected["dm_t"] == -7.698554350280959
    assert corrected["qlike_advantage_pct"] == 8.176565354166426
    assert corrected["winner"] == "A4f"


def test_scope_repair_builder_is_deterministic_and_non_mutating() -> None:
    module = _load_scope_repair()
    before = RESULTS.read_bytes()
    legacy, corrected = module.load_inputs()
    first = module.build_audit(legacy, corrected)
    second = module.build_audit(legacy, corrected)
    assert first == second
    assert RESULTS.read_bytes() == before


def test_legacy_source_cannot_overwrite_frozen_result() -> None:
    source = (HERE / "k1396.py").read_text(encoding="utf-8")
    assert "k1396_legacy_rerun_results.json" in source
    assert "does not match K988 exactly" in source
    assert "not equivalence" in source
    assert "steady-state g on every OOS date" in source
    assert "legacy_dm_hac_screen" in source


def test_readme_withdraws_unsupported_public_claims() -> None:
    readme = (HERE / "README.md").read_text(encoding="utf-8")
    assert "SUPERSEDED_HISTORICAL_DIAGNOSTIC_ONLY" in readme
    assert "FAIL_PUBLIC_CLAIM" in readme
    assert "does not supply the canonical HAR-RV benchmark" in readme
    assert "did not establish" in readme
    assert "K1379" in readme
    assert EXPECTED_RESULT_SHA in readme


def test_corrected_charts_exist_at_publication_resolution() -> None:
    for name in ("k1396_general_article_chart.png", "k1396_scope_correction_chart.png"):
        path = HERE / name
        assert path.exists()
        with Image.open(path) as image:
            assert image.width >= 2400
            assert image.height >= 1200
