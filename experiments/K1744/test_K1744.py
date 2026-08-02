"""Scoped regression checks for the K1744 feasibility artifact."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pandas as pd

HERE = Path(__file__).resolve().parent


def load_json(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def load_entrypoint() -> ModuleType:
    spec = importlib.util.spec_from_file_location("k1744_entrypoint", HERE / "K1744.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_proxy_was_locked_before_outcomes_and_hash_pinned() -> None:
    prereg = load_json("proxy_preregistration.json")
    result = load_json("K1744_results.json")
    observed = hashlib.sha256((HERE / "proxy_preregistration.json").read_bytes()).hexdigest()

    assert prereg["outcome_data_inspected_before_lock"] is False
    assert prereg["outcome_data_request_made_before_lock"] is False
    assert observed == result["inputs"]["proxy_preregistration"]["sha256"]
    assert result["data"]["outcome_series_requested"] is False
    assert result["data"]["outcome_series_loaded"] is False
    assert result["data"]["sample"]["outcome_rows"] == 0


def test_zero_salvage_is_not_reclassified_as_null_or_success() -> None:
    result = load_json("K1744_results.json")

    assert result["recovery"]["prior_job_classification"] == "ZERO_SALVAGE"
    assert result["recovery"]["prior_job_artifacts_used"] == []
    assert result["recovery"]["prior_job_code_or_data_read"] is False
    assert result["recovery"]["zero_salvage_is_not_success"] is True
    assert result["recovery"]["zero_salvage_is_not_scientific_null"] is True
    assert result["conclusion_grade"] == "INCONCLUSIVE"
    assert result["scientific_null"] is False


def test_signal_path_is_explicitly_lagged() -> None:
    module = load_entrypoint()
    signal = pd.Series([1.0, 2.0, 4.0], index=pd.period_range("2020-01", periods=3, freq="M"))
    lagged = module.prepare_exposure_for_outcome(signal)

    assert pd.isna(lagged.iloc[0])
    assert lagged.iloc[1:].tolist() == [1.0, 2.0]
    assert "return exposure.shift(1)" in (HERE / "K1744.py").read_text(encoding="utf-8")


def test_failed_gate_preserves_unknown_counts_and_empty_inference() -> None:
    result = load_json("K1744_results.json")
    feasibility = result["proxy"]["feasibility"]

    assert feasibility["status"] == "FAILED_BEFORE_OUTCOME_LOADING"
    assert feasibility["passed"] is False
    assert feasibility["unknown_counts_are_not_zero"] is True
    assert all(value is None for value in feasibility["observed"].values())
    assert result["design"]["primary_family"]["cells"] == 9
    assert result["design"]["primary_family"]["multiplicity"].startswith("Holm")
    assert result["estimates"]["primary_cells"] == []
    assert result["estimates"]["raw_p_values"] == []
    assert result["estimates"]["holm_adjusted_p_values"] == []
    assert result["estimates"]["primary_adjusted_p_value"] is None
    assert result["robustness"]["status"] == "NOT_RUN"


def test_full_universe_and_channel_separation_are_frozen() -> None:
    prereg = load_json("proxy_preregistration.json")

    assert prereg["fixed_market_universe"] == [
        "ILF",
        "EWW",
        "ECH",
        "EPU",
        "EWZ",
        "CEW",
        "EMLC",
        "EMB",
        "UUP",
    ]
    assert prereg["channel_definitions"]["equity"] == [
        "ILF",
        "EWW",
        "ECH",
        "EPU",
        "EWZ",
    ]
    assert prereg["channel_definitions"]["fx_local_bond"] == ["CEW", "EMLC"]
    assert prereg["channel_definitions"]["hard_currency_bond"] == ["EMB"]
    assert prereg["channel_definitions"]["usd_factor_only"] == ["UUP"]


def test_readme_claims_match_results_and_have_json_pointers() -> None:
    result = load_json("K1744_results.json")
    diagnostics = load_json("diagnostics.json")
    readme = (HERE / "README.md").read_text(encoding="utf-8")

    assert diagnostics["checks"]["readme_result_consistency"] is True
    assert result["proxy"]["feasibility"]["exact_failure_reason"] in readme
    assert f"outcome rows 為 **{result['data']['sample']['outcome_rows']}**" in readme
    assert f"固定為 **{result['design']['primary_family']['cells']}** cells" in readme
    assert "JSON: `/estimates`" in readme
    assert "JSON `/limitations`" in readme


def test_runtime_result_spec_and_commit_are_byte_consistent() -> None:
    result_bytes = (HERE / "K1744_results.json").read_bytes()
    spec_bytes = (HERE / "reproduce_spec.json").read_bytes()
    entrypoint_bytes = (HERE / "K1744.py").read_bytes()
    result = json.loads(result_bytes)
    reproduce_spec = json.loads(spec_bytes)
    commit = load_json("reproduce_commit.json")

    result_sha = hashlib.sha256(result_bytes).hexdigest()
    spec_sha = hashlib.sha256(spec_bytes).hexdigest()
    entrypoint_sha = hashlib.sha256(entrypoint_bytes).hexdigest()

    assert result["code_trace"]["sha256"] == entrypoint_sha
    assert reproduce_spec["entrypoint"]["sha256"] == entrypoint_sha
    assert reproduce_spec["canonical_result_identity"]["sha256"] == result_sha
    assert commit["canonical_result_identity"]["sha256"] == result_sha
    assert commit["spec_identity"]["sha256"] == spec_sha
    assert result["artifact_generation"]["generation_id"] == commit["generation_id"]


def test_recovery_worker_did_not_create_review_verdict() -> None:
    assert not (HERE / "review_verdict.json").exists()
