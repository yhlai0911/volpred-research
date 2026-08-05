"""Ratchet for nested-model comparisons that use raw DM/HLN as inference.

The baseline freezes legacy debt; it is not an assertion that every flagged
path has a wrong numerical result.  New paths fail CI, repaired paths must be
removed, and retired paths cannot return.  The single enforcement owner for
this concern is this file plus ``scripts/audit_nested_dm_misuse.py``.

Run:
    uv run --extra dev python -m pytest \
        scripts/tests/test_nested_dm_misuse_ratchet.py -v
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import audit_nested_dm_misuse as nested_dm  # noqa: E402
from audit_nested_dm_misuse import scan_file, scan_population  # noqa: E402


BASELINE_PATH = REPO_ROOT / "storage" / "ops" / "nested_dm_misuse_baseline.json"


@pytest.fixture(scope="module")
def audit():
    return scan_population()


@pytest.fixture(scope="module")
def flagged(audit) -> set[str]:
    return {finding.file for finding in audit.findings}


@pytest.fixture(scope="module")
def reviewed_nonnested(baseline_payload: dict) -> set[str]:
    return {entry["site"] for entry in baseline_payload["reviewed_nonnested"]}


@pytest.fixture(scope="module")
def affected(flagged: set[str], reviewed_nonnested: set[str]) -> set[str]:
    # The auditor stays lexically broad on purpose: the 2026-07-13 audit showed
    # that narrowing the prose channel enough to silence the false positives
    # also silences 109 genuinely nested comparisons.  False positives are
    # instead retired one at a time, by a recorded adjudication with a reason,
    # never by a marker an author can apply to their own file.
    return flagged - reviewed_nonnested


@pytest.fixture(scope="module")
def safe(audit) -> set[str]:
    return {finding.file for finding in audit.reviewed_safe}


@pytest.fixture(scope="module")
def baseline_payload() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def baseline(baseline_payload: dict) -> set[str]:
    active = baseline_payload["active"]
    return set(active["exposed"]) | set(active["diagnostic_only"])


def test_scan_has_no_silent_errors(audit) -> None:
    assert not audit.scan_errors, "\n".join(audit.scan_errors)


def test_no_new_nested_raw_dm_sites(affected: set[str], baseline: set[str]) -> None:
    new = affected - baseline
    assert not new, (
        "New nested-model site(s) use raw DM/HLN as primary inference:\n\n"
        + "\n".join(f"  - {site}" for site in sorted(new))
        + "\n\nUse a nested-appropriate test and wire it into the verdict. "
        "For squared-error forecast comparisons use Clark-West (2007). "
        "For QLIKE/pinball, do not relabel MSPE-CW: use an appropriate "
        "general-loss/encompassing or recursive-bootstrap design. If raw DM is "
        "only descriptive, make that role explicit with `nested-dm: "
        "diagnostic-only` and ensure it does not feed the claim sink. If the "
        "primary raw DM is legal because its pair is nonnested, segregate and "
        "inventory the pairs; do not add a file-level marker that washes real "
        "nested comparisons clean."
    )


def test_gate_history_blobs_are_never_scanned(audit, tmp_path: Path) -> None:
    """Frozen gate blobs must stay out of the population.

    ``gate_history/`` holds the as-run entrypoint bytes preserved by
    ``scripts/preserve_gate_blob.py``, whose manifest forbids editing a blob --
    an edited original is a reconstruction, which is what K1708 was rejected
    for. A flagged blob therefore demands a repair that is forbidden to make:
    ``test_no_new_nested_raw_dm_sites`` goes red and no legal edit clears it.
    The DM-HAC sibling took main down that way on 2026-08-04 (run
    30911746339), on ``experiments/k1814/gate_history/b1a67269__k1814.py``.

    ``scan_population`` skips those paths, but nothing pinned the skip -- and
    the auditor still classifies a blob when handed one directly, which is the
    negative control below. The same rule for ``experiment_gates.python_files``
    is locked in ``test_experiment_gates_gate_history_exclusion.py``, and for
    ``audit_dm_hac_lag`` in ``test_dm_hac_lag_ratchet.py``.
    """
    donors = sorted(finding.file for finding in audit.findings)
    assert donors, "no flagged site left to build the fixture from"
    source = (REPO_ROOT / donors[0]).read_text(encoding="utf-8")

    experiment = tmp_path / "experiments" / "k9001"
    (experiment / "gate_history").mkdir(parents=True)
    (experiment / "__pycache__").mkdir()
    for relative in (
        "k9001.py",
        "gate_history/deadbeef__k9001.py",
        "__pycache__/k9001.cpython-312.py",
    ):
        (experiment / relative).write_text(source, encoding="utf-8")

    blob = experiment / "gate_history" / "deadbeef__k9001.py"
    assert scan_file(blob, tmp_path) is not None, (
        "negative control failed: the classifier no longer flags this fixture, "
        "so the exclusion below would pass vacuously"
    )

    result = scan_population(tmp_path)
    scanned = {finding.file for finding in result.findings} | {
        finding.file for finding in result.reviewed_safe
    }

    assert "experiments/k9001/k9001.py" in scanned, (
        "the live twin was not scanned, so this fixture proves nothing"
    )
    assert not [p for p in scanned if "gate_history" in p or "__pycache__" in p], (
        f"unrepairable path entered the population: {sorted(scanned)}"
    )


def test_baseline_only_contains_active_sites(
    affected: set[str], baseline: set[str]
) -> None:
    stale = baseline - affected
    assert not stale, (
        "Repaired/stale nested-DM sites must be pruned from the baseline: "
        f"{sorted(stale)}\n\n"
        "If a detector change made these go quiet, that is not a repair. The "
        "2026-07-13 audit adjudicated every baseline site: a narrowing that "
        "silences them is dropping real nested-DM debt on the floor. See "
        "docs/governance/2026-07/nested_dm_fp_narrowing_audit.md before "
        "pruning anything here."
    )


def test_reviewed_nonnested_entries_carry_an_adjudication(
    baseline_payload: dict,
) -> None:
    entries = baseline_payload["reviewed_nonnested"]
    sites = [entry["site"] for entry in entries]
    assert sites == sorted(set(sites))
    assert baseline_payload["reviewed_nonnested_count"] == len(entries)
    for entry in entries:
        assert entry["reason"].strip(), entry["site"]
        assert entry["adjudicated_at"], entry["site"]
        assert entry["audit"], entry["site"]


def test_reviewed_nonnested_cannot_silence_a_baseline_site(
    baseline: set[str], reviewed_nonnested: set[str]
) -> None:
    # The allowlist retires false positives.  It must never be used to make a
    # site that is already frozen as nested debt disappear.
    assert baseline.isdisjoint(reviewed_nonnested)


def test_reviewed_nonnested_sites_are_still_flagged(
    flagged: set[str], reviewed_nonnested: set[str]
) -> None:
    # An allowlisted site that the auditor no longer flags is dead weight: the
    # entry must be deleted rather than left to mask a future regression.
    dead = reviewed_nonnested - flagged
    assert not dead, f"Allowlist entries no longer flagged, delete them: {sorted(dead)}"


def test_retired_sites_cannot_resurrect(
    affected: set[str], baseline: set[str], baseline_payload: dict
) -> None:
    retired = {entry["site"] for entry in baseline_payload.get("retired", [])}
    assert baseline.isdisjoint(retired)
    resurrected = affected & retired
    assert not resurrected, f"Retired sites regressed: {sorted(resurrected)}"


def test_baseline_metadata_is_a_stable_ratchet(baseline_payload: dict) -> None:
    active = baseline_payload["active"]
    exposed = active["exposed"]
    diagnostic = active["diagnostic_only"]
    assert exposed == sorted(set(exposed))
    assert diagnostic == sorted(set(diagnostic))
    assert set(exposed).isdisjoint(diagnostic)
    assert baseline_payload["count"] == len(exposed) + len(diagnostic)
    assert baseline_payload["exposed_count"] == len(exposed)
    assert baseline_payload["diagnostic_only_count"] == len(diagnostic)
    assert baseline_payload["auditor"] == "scripts/audit_nested_dm_misuse.py"
    assert baseline_payload["enforcement_owner"] == (
        "scripts/tests/test_nested_dm_misuse_ratchet.py"
    )


def test_known_raw_primary_sites_are_frozen(affected: set[str]) -> None:
    expected = {
        "experiments/K1343_bdc_pressure_private_credit_vol_signal/K1343.py",
        "experiments/K1344_private_credit_software_spillover/K1344.py",
        "experiments/K1679-rev/K1679-rev.py",
        "experiments/k1518_twse_foreign_flow_sector_vol/k1518.py",
        "experiments/k1616_cointegration_ect_har_rv/k1616_cointegration_ect_har_rv.py",
        "experiments/k1617/k1617.py",
        "experiments/k1681/k1681.py",
        "experiments/k1682/k1682.py",
        "experiments/k1683/k1683.py",
    }
    assert expected <= affected


def test_canonical_dm_delegate_is_still_raw_for_nested_pair(affected: set[str]) -> None:
    # The canonical helper fixes HAC bandwidth; it does not make raw DM valid
    # under a nested-model null.
    assert "experiments/k1518_twse_foreign_flow_sector_vol/k1518.py" in affected


def test_reviewed_cw_controls_are_not_frozen(affected: set[str], safe: set[str]) -> None:
    expected_safe = {
        "experiments/K1679-rev2/K1679-rev2.py",
        "experiments/k1116g/k1116g.py",
        "experiments/k1680/K1680.py",
    }
    assert expected_safe <= safe
    assert expected_safe.isdisjoint(affected)


def test_k1698_nonnested_gate_is_outside_nested_audit_population(
    affected: set[str], safe: set[str]
) -> None:
    site = "experiments/k1698/k1698.py"
    assert site not in affected
    assert site not in safe

    path = REPO_ROOT / site
    assert scan_file(path) is None
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assignments = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id
        in {
            "QLIKE_DM_PAIR_SPECS",
            "QLIKE_NESTED_PAIRS_EXCLUDED_FROM_RAW_DM",
            "FZ0_SAME_FAMILY_PAIRS_EXCLUDED_FROM_RAW_DM",
        }
    }
    specs = assignments["QLIKE_DM_PAIR_SPECS"]
    assert [spec for spec in specs if spec[2].startswith("primary_gate")] == [
        ("HAR-RV", "GJR", "primary_gate_r2_0050_only")
    ]
    assert "HAR-a_vs_HAR-RV" in assignments[
        "QLIKE_NESTED_PAIRS_EXCLUDED_FROM_RAW_DM"
    ]
    fz_excluded = set(assignments["FZ0_SAME_FAMILY_PAIRS_EXCLUDED_FROM_RAW_DM"])
    assert fz_excluded == {
        "GJR+Normal_vs_GJR+CF",
        "GJR+Skewed-t_vs_GJR+CF",
        "GJRf+CF_vs_GJR+CF",
        "GJRf+Normal_vs_GJR+CF",
        "GJRf-a+CF_vs_GJR+CF",
        "GJRf-a+Normal_vs_GJR+CF",
    }

    gate = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "decide_gate_v2"
    )
    gate_source = ast.unparse(gate)
    assert len(gate.args.args) == 2
    assert "model_relation" in gate_source
    assert "inference_role" in gate_source
    assert "primary_nonnested" not in gate_source
    assert "mismatched" not in gate_source


def _write_fixture(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "experiments" / "fixture" / "fixture.py"
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    return path


def test_synthetic_nested_canonical_dm_reaches_claim_sink(tmp_path: Path) -> None:
    path = _write_fixture(
        tmp_path,
        """
base_cols = ["har"]
aug_cols = base_cols + ["signal"]
def evaluate(loss_base, loss_aug):
    dm_t, dm_p = dm_test(loss_aug, loss_base, h=1)
    verdict = "PASS" if dm_t < -3 else "NULL"
    return {"verdict": verdict, "dm_t": dm_t}
""",
    )
    finding = scan_file(path, tmp_path)
    assert finding is not None
    assert finding.test_role == "primary_raw_dm"


def test_synthetic_nonnested_dm_is_not_flagged(tmp_path: Path) -> None:
    path = _write_fixture(
        tmp_path,
        """
def compare(arima_loss, garch_loss):
    dm_t, dm_p = dm_test(arima_loss, garch_loss, h=1)
    return dm_t, dm_p
""",
    )
    assert scan_file(path, tmp_path) is None


def test_cw_keyword_alone_does_not_sanitize_primary_dm(tmp_path: Path) -> None:
    path = _write_fixture(
        tmp_path,
        '"""Nested model. Clark-West is computed for one sensitivity cell."""\n'
        "base_cols = ['har']\n"
        "aug_cols = base_cols + ['signal']\n"
        "def classify(loss_base, loss_aug):\n"
        "    dm_t, dm_p = dm_test(loss_aug, loss_base, h=1)\n"
        "    verdict = 'PASS' if dm_t < -3 else 'NULL'\n"
        "    return verdict\n",
    )
    finding = scan_file(path, tmp_path)
    assert finding is not None
    assert finding.test_role == "primary_raw_dm"


def test_explicit_dm_diagnostic_with_cw_primary_is_safe(tmp_path: Path) -> None:
    path = _write_fixture(
        tmp_path,
        '"""Nested model; ordinary DM is descriptive only."""\n'
        "base_cols = ['har']\n"
        "aug_cols = base_cols + ['signal']\n"
        "def evaluate(loss_base, loss_aug, cw_t):\n"
        "    dm_t, dm_p = dm_test(loss_aug, loss_base, h=1)\n"
        "    verdict = 'PASS' if cw_t > 3 else 'NULL'\n"
        "    return {'verdict': verdict, 'dm_direction': dm_t}\n",
    )
    finding = scan_file(path, tmp_path)
    assert finding is not None
    assert finding.test_role == "diagnostic_with_cw_primary"


def test_nonnested_word_is_not_nesting_evidence(tmp_path: Path) -> None:
    path = _write_fixture(
        tmp_path,
        '"""Compare nonnested models."""\n'
        "def classify(loss_har, loss_gjr):\n"
        "    dm_t, _ = dm_test(loss_har, loss_gjr, h=1)\n"
        "    return 'PASS' if dm_t < -3 else 'NULL'\n",
    )
    assert scan_file(path, tmp_path) is None


def test_hyphenated_non_nested_word_is_not_nesting_evidence(tmp_path: Path) -> None:
    path = _write_fixture(
        tmp_path,
        '"""Primary comparison is non-nested."""\n'
        "def classify(loss_har, loss_gjr):\n"
        "    dm_t, _ = dm_test(loss_har, loss_gjr, h=1)\n"
        "    return 'PASS' if dm_t < -3 else 'NULL'\n",
    )
    assert scan_file(path, tmp_path) is None


def test_nonnested_markers_cannot_impersonate_nested_safe_markers(tmp_path: Path) -> None:
    path = _write_fixture(
        tmp_path,
        '"""nonnested-dm: none; nonnested-dm: diagnostic-only."""\n'
        "base_cols = ['har']\n"
        "aug_cols = base_cols + ['scale']\n"
        "def classify(loss_base, loss_aug):\n"
        "    dm_t, _ = dm_test(loss_aug, loss_base, h=1)\n"
        "    return 'PASS' if dm_t < -3 else 'NULL'\n",
    )
    finding = scan_file(path, tmp_path)
    assert finding is not None
    assert finding.test_role == "primary_raw_dm"


def test_bibliographic_nested_title_is_not_local_nesting(tmp_path: Path) -> None:
    path = _write_fixture(
        tmp_path,
        "reference = {'title': 'Tests of Equal Forecast Accuracy and "
        "Encompassing for Nested Models'}\n"
        "def evaluate(loss_a, loss_b):\n"
        "    dm_t, dm_p = dm_test(loss_a, loss_b, h=1)\n"
        "    verdict = 'PASS' if dm_t < -3 else 'NULL'\n"
        "    return verdict\n",
    )
    assert scan_file(path, tmp_path) is None


def test_generic_hac_mean_test_of_paired_error_difference_is_detected(
    tmp_path: Path,
) -> None:
    path = _write_fixture(
        tmp_path,
        "base_cols = ['x']\n"
        "aug_cols = base_cols + ['signal']\n"
        "def equal_accuracy(err_base, err_aug):\n"
        "    delta = err_aug - err_base\n"
        "    result = OLS(delta, ones(len(delta))).fit(cov_type='HAC')\n"
        "    return result.pvalues[0]\n"
        "def decide(err_base, err_aug):\n"
        "    p = equal_accuracy(err_base, err_aug)\n"
        "    return 'PASS' if p < 0.05 else 'NULL'\n",
    )
    finding = scan_file(path, tmp_path)
    assert finding is not None
    assert finding.test_role in {"review_required", "primary_raw_dm"}


_MASK_ESTIMATION = (
    "import numpy as np\n"
    "def refit(y, X, sc, n_beta, n_macro):\n"
    "    active = np.ones(n_beta)\n"
    "    active[n_beta - n_macro:] = 0.0\n"
    "    return fit_gev_reg(y, X, sc, active=active)\n"
)
_MASK_INFERENCE = (
    "def evaluate(loss_macro, loss_gev_har):\n"
    "    dm_t, dm_p = dm_test(loss_macro, loss_gev_har, h=1)\n"
    "    verdict = 'PASS' if dm_p < 0.05 else 'HOLD'\n"
    "    return {'verdict': verdict, 'dm_t': dm_t}\n"
)


def test_coefficient_mask_restriction_is_nesting_evidence(tmp_path: Path) -> None:
    path = _write_fixture(tmp_path, _MASK_ESTIMATION + _MASK_INFERENCE)
    finding = scan_file(path, tmp_path)
    assert finding is not None
    assert finding.test_role == "primary_raw_dm"
    assert any("active[" in evidence.text for evidence in finding.nested_evidence)


def test_coefficient_mask_is_the_only_nesting_channel(tmp_path: Path) -> None:
    path = _write_fixture(tmp_path, _MASK_INFERENCE)
    assert scan_file(path, tmp_path) is None


def test_zeroed_sample_weight_is_not_nesting(tmp_path: Path) -> None:
    path = _write_fixture(
        tmp_path,
        "import numpy as np\n"
        "def refit(y, X, burn_in):\n"
        "    weights = np.ones(len(y))\n"
        "    weights[:burn_in] = 0.0\n"
        "    return fit_model(y, X, sample_weight=weights)\n" + _MASK_INFERENCE,
    )
    assert scan_file(path, tmp_path) is None


def test_zeroed_restriction_not_passed_to_estimator_is_not_nesting(
    tmp_path: Path,
) -> None:
    path = _write_fixture(
        tmp_path,
        "import numpy as np\n"
        "def summarise(n_beta, n_macro):\n"
        "    active = np.ones(n_beta)\n"
        "    active[n_beta - n_macro:] = 0.0\n"
        "    return {'n_active': int(active.sum())}\n" + _MASK_INFERENCE,
    )
    assert scan_file(path, tmp_path) is None


def test_parse_failure_is_reported_not_silently_dropped(tmp_path: Path) -> None:
    _write_fixture(tmp_path, "def broken(:\n")
    result = scan_population(tmp_path)
    assert result.scan_errors
    assert "SyntaxError" in result.scan_errors[0]


# ---------------------------------------------------------------------------
# Third role: unconditional GW/DM with a bounded-memory forecasting method
# ---------------------------------------------------------------------------
def _fixed_memory_manifest() -> dict:
    return {
        "schema": nested_dm.FIXED_MEMORY_MANIFEST_SCHEMA,
        "role": nested_dm.FIXED_MEMORY_ROLE,
        "claim_scope": "unconditional_average_loss_only",
        "conditional_predictive_ability_tested": False,
        "regime_offsetting_effects_excluded": False,
        "implementation": {
            "paired_forecast_function": "paired_oos",
            "statistic_function": "gw_unconditional_dm",
            "gate_registry_inference": "gw_fixed",
            "train_window_constant": "TRAIN_WINDOW",
            "model_spec_registry": "MODEL_SPECS",
            "base_model_parameter": "base",
            "augmented_model_parameter": "alt",
            "paired_result_variable": "po",
            "gate_function": "evaluate_cell",
            "registry_record_constructor": "TestRecord",
            "gate_eligibility_variable": "gate_eligible",
            "whole_method_eligibility_variable": "whole_method_fixed_memory",
            "bounded_memory_parameter": "bounded_memory",
            "paired_audit_attribute": "audit",
            "paired_eligibility_key": "gw_fixed_memory_eligible",
            "base_design_variable": "Xb",
            "augmented_design_variable": "Xa",
            "fit_function": "fit",
            "runtime_evidence_file": "fixture_results.json",
            "runtime_evidence_key": "nested_dm_fixed_memory_evidence_v1",
            "runtime_cell_inventory": "primary_cells",
            "runtime_gate_inventory": "multiple_testing.primary_family",
            "runtime_registry_inventory": "multiple_testing.full_family_holm",
            "runtime_claim_record": "verdict_basis",
            "runtime_statistic_record": "primary_inference",
            "runtime_multiple_testing_record": "multiple_testing",
            "claim_surface_files": ["fixture.py", "fixture_results.json"],
        },
        "method_contract": {
            "estimation_scheme": "fixed_rolling",
            "train_window": 50,
            "window_data_dependent": False,
            "shared_complete_case_mask": True,
            "shared_training_dates": True,
            "forward_label_embargo": True,
            "loss": "generic proper loss",
            "runtime_estimand": "E[loss_aug - loss_base]",
            "loss_differential": "loss_aug_minus_loss_base",
            "hac_kernel": "Bartlett",
            "hac_bandwidth_rule": "max(h-1, canonical_bandwidth(h,n))",
            "reference_distribution": "standard_normal",
            "estimand": "unconditional average proper-loss differential",
        },
        "decision_contract": {
            "gate_direction": "lower",
            "raw_p_field": "p_value_one_sided_flow_better",
            "multiplicity": "Holm",
            "family_alpha": 0.05,
            "critical_value": -1.645,
            "gate_flag_field": "passes_flow_gate",
            "holm_adjusted_p_field": "holm_adjusted_p",
            "registry_stat_field": "stat",
            "registry_stat_decimals": 4,
            "registry_raw_p_field": "p_one_sided_raw",
            "gate_count_field": "n_gate_eligible_gw_tests",
            "claim_family_count_field": "cells_in_primary_family",
            "claim_pass_count_field": "cells_passing_flow_gate",
        },
        "feature_stages": [
            {
                "id": "state",
                "role": "predictor_feature",
                "outputs": ["x"],
                "memory": "finite_lag",
                "max_observations": 2,
            },
            {
                "id": "signal",
                "role": "predictor_feature",
                "outputs": ["s"],
                "memory": "finite_lag",
                "max_observations": 5,
            },
            {
                "id": "paired_log_variance_fit",
                "role": "paired_final_estimator",
                "outputs": ["forecast_base", "forecast_aug"],
                "memory": "fixed_rolling",
                "max_observations": 50,
            },
        ],
        "expected_primary_cell_count": 1,
        "primary_cells": [
            {
                "id": "primary|BTC_h1|AUG|rv|fl1",
                "id_components": ["primary", "BTC_h1", "AUG", "rv", "fl1"],
                "family": "primary",
                "base": "BASE",
                "augmented": "AUG",
                "strictly_nested": True,
                "horizon": 1,
                "feeds_gate": True,
                "base_predictors": ["x"],
                "augmented_predictors": ["x", "s"],
                "used_stage_ids": [
                    "state",
                    "signal",
                    "paired_log_variance_fit",
                ],
            }
        ],
    }


def _fixed_memory_runtime(manifest: dict) -> dict:
    cell_id = manifest["primary_cells"][0]["id"]
    digest = "a" * 64
    audit = {
        "scheme": "fixed_rolling",
        "train_window": 50,
        "n_origins": 80,
        "fixed_window_held": True,
        "same_training_dates_for_both_models": True,
        "min_origin_minus_last_train_label_end_days": 1,
        "embargo_ok": True,
        "common_complete_case_mask_sha256": digest,
        "base_training_schedule_sha256": digest,
        "aug_training_schedule_sha256": digest,
        "origin_schedule_sha256": digest,
    }
    statistic = {
        "test": "equal unconditional predictive ability",
        "loss": "generic proper loss",
        "estimand": "E[loss_aug - loss_base]",
        "forecast_scheme": "paired fixed rolling estimation window",
        "n": 80,
        "mean_loss_diff_aug_minus_base": 0.01,
        "standard_error": 0.02,
        "z_stat": 0.5,
        "p_value_one_sided_flow_better": 0.6914624612740131,
        "p_value_two_sided": 0.6170750774519738,
        "hac_lag_used": 5,
        "hac_kernel": "Bartlett",
        "hac_bandwidth_rule": "max(h-1, canonical_bandwidth(h,n))",
        "reference_distribution": "standard_normal",
    }
    cell = {
        "cell": cell_id,
        "family": "primary",
        "asset": "BTC",
        "horizon": 1,
        "rv_proxy": "rv",
        "base": "BASE",
        "alt": "AUG",
        "state_lag": 1,
        "flow_lag": 1,
        "smearing": "own",
        "bounded_memory": True,
        "n_oos": 80,
        "oos_audit": audit,
        "primary_inference": statistic,
    }
    gate = {
        "cell": cell_id,
        "family": "primary",
        "asset": "BTC",
        "horizon": 1,
        "base": "BASE",
        "alt": "AUG",
        "inference": "gw_fixed",
        "estimand": "E[loss_aug - loss_base]",
        "feeds_gate": True,
        "bounded_memory": True,
        "claim_role": "primary_unconditional_detection_gate",
        "n": 80,
        "stat": 0.5,
        "p_one_sided_raw": 0.6914624612740131,
        "holm_adjusted_p": 0.6914624612740131,
        "passes_flow_gate": False,
    }
    envelope_cell = {
        "id": cell_id,
        "common_complete_case_mask_sha256": digest,
        "base_training_schedule_sha256": digest,
        "aug_training_schedule_sha256": digest,
        "origin_schedule_sha256": digest,
        "eligibility": "whole_method_fixed_memory_verified",
        "base_predictors": ["x"],
        "augmented_predictors": ["x", "s"],
    }
    return {
        "primary_cells": [cell],
        "multiple_testing": {
            "primary_family": [copy.deepcopy(gate)],
            "full_family_holm": [copy.deepcopy(gate)],
            "n_gate_eligible_gw_tests": 1,
        },
        "verdict_basis": {
            "claim_strength": "No unconditional predictive evidence was found.",
            "does_say_1": "No unconditional predictive evidence was found.",
            "cells_in_primary_family": 1,
            "cells_passing_flow_gate": 0,
            "does_not_say_1": (
                "Conditional ability was not tested; regime-offsetting effects "
                "are not excluded."
            ),
        },
        "nested_dm_fixed_memory_evidence_v1": {
            "schema": nested_dm.FIXED_MEMORY_RUNTIME_SCHEMA,
            "manifest_sha256": nested_dm._canonical_sha256(manifest),
            "cell_inventory": "primary_cells",
            "gate_inventory": "multiple_testing.primary_family",
            "registry_inventory": "multiple_testing.full_family_holm",
            "statistic_record": "primary_inference",
            "claim_record": "verdict_basis",
            "claim_scope": "unconditional_average_loss_only",
            "cells": [envelope_cell],
        },
    }


def _fixed_memory_source(manifest: dict | None = None) -> str:
    manifest = manifest or _fixed_memory_manifest()
    return f'''import hashlib
import json

TRAIN_WINDOW = 50
MODEL_SPECS = {{"BASE": ["x"], "AUG": ["x", "s"]}}
NESTED_DM_FIXED_MEMORY_MANIFEST_V1 = {manifest!r}
conditional_predictive_ability_not_tested = "regime effects are NOT EXCLUDED"

def _canonical_object_sha256(value):
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

class Paired:
    def __init__(self, audit):
        self.audit = audit

class TestRecord:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

def paired_oos(data, base, alt, train_window=TRAIN_WINDOW):
    if not set(MODEL_SPECS[base]) < set(MODEL_SPECS[alt]):
        raise ValueError("nested models required")
    Xb = (data, MODEL_SPECS[base])
    Xa = (data, MODEL_SPECS[alt])
    origins, start, end, index = data, 0, train_window, train_window
    def fit(design, row_dates, first, last, origin):
        return design
    fit(Xb, origins, start, end, index)
    fit(Xa, origins, start, end, index)
    fixed_window_held = train_window == TRAIN_WINDOW
    same_dates = start == start
    embargo_ok = end <= index
    digest = "a" * 64
    eligible = fixed_window_held and same_dates and embargo_ok
    audit = {{
        "fixed_window_held": fixed_window_held,
        "same_training_dates_for_both_models": same_dates,
        "embargo_ok": embargo_ok,
        "base_training_schedule_sha256": digest,
        "aug_training_schedule_sha256": digest,
        "common_complete_case_mask_sha256": digest,
        "origin_schedule_sha256": digest,
        "gw_fixed_memory_eligible": eligible,
    }}
    return Paired(audit)

def gw_unconditional_dm(loss_aug, loss_base, h):
    bartlett_lrv = "Bartlett"
    normal_reference = "standard_normal"
    return {{
        "loss": "generic proper loss",
        "estimand": "E[loss_aug - loss_base]",
        "mean_loss_diff_aug_minus_base": 0.0,
        "hac_lag_used": 1,
        "standard_error": 1.0,
        "hac_kernel": "Bartlett",
        "hac_bandwidth_rule": "max(h-1, canonical_bandwidth(h,n))",
        "reference_distribution": "standard_normal",
    }}

def evaluate_cell(data, base, alt, family, register_gate=True, bounded_memory=True):
    po = paired_oos(data, base, alt)
    whole_method_fixed_memory = bool(
        bounded_memory and po.audit.get("gw_fixed_memory_eligible") is True
    )
    gate_eligible = bool(
        register_gate and family == "primary" and whole_method_fixed_memory
    )
    TestRecord(
        inference="gw_fixed",
        feeds_gate=gate_eligible,
        bounded_memory=whole_method_fixed_memory,
    )

expected_ids = [
    cell["id"] for cell in NESTED_DM_FIXED_MEMORY_MANIFEST_V1["primary_cells"]
]
manifest_sha256 = _canonical_object_sha256(NESTED_DM_FIXED_MEMORY_MANIFEST_V1)
'''


def test_fixed_memory_source_contract_accepts_the_canonical_protocol() -> None:
    source = _fixed_memory_source()
    tree = ast.parse(source)
    assert nested_dm._fixed_memory_source_errors(
        tree, source, _fixed_memory_manifest()
    ) == []


@pytest.mark.parametrize(
    ("old", "new", "needle"),
    [
        (
            'register_gate and family == "primary" and whole_method_fixed_memory',
            'True or (register_gate and family == "primary" and whole_method_fixed_memory)',
            "provenance conjunction",
        ),
        (
            'po.audit.get("gw_fixed_memory_eligible")',
            'evil.audit.get("gw_fixed_memory_eligible")',
            "upstream or paired-fit provenance",
        ),
        (
            'Xb = (data, MODEL_SPECS[base])',
            'Xb = (data, MODEL_SPECS[alt])',
            "design Xb is not bound",
        ),
    ],
)
def test_fixed_memory_source_contract_rejects_decoy_wiring(
    old: str, new: str, needle: str
) -> None:
    source = _fixed_memory_source().replace(old, new)
    errors = nested_dm._fixed_memory_source_errors(
        ast.parse(source), source, _fixed_memory_manifest()
    )
    assert any(needle in error for error in errors), errors


@pytest.mark.parametrize(
    "payload",
    [
        'alias = NESTED_DM_FIXED_MEMORY_MANIFEST_V1\nalias.clear()',
        '[row.clear() for row in NESTED_DM_FIXED_MEMORY_MANIFEST_V1["primary_cells"]]',
        'for row in NESTED_DM_FIXED_MEMORY_MANIFEST_V1["primary_cells"]:\n    row.clear()',
        'def evil(m=NESTED_DM_FIXED_MEMORY_MANIFEST_V1):\n    m.clear()',
        'def evil():\n    yield NESTED_DM_FIXED_MEMORY_MANIFEST_V1',
        'if (alias := NESTED_DM_FIXED_MEMORY_MANIFEST_V1):\n    alias.clear()',
        'match NESTED_DM_FIXED_MEMORY_MANIFEST_V1:\n    case {"primary_cells": rows}:\n        rows.clear()',
    ],
)
def test_fixed_memory_manifest_cannot_be_aliased_or_mutated(payload: str) -> None:
    source = _fixed_memory_source() + "\n" + payload + "\n"
    errors = nested_dm._fixed_memory_source_errors(
        ast.parse(source), source, _fixed_memory_manifest()
    )
    assert any("manifest" in error for error in errors), errors


def test_fixed_memory_manifest_is_cell_level_and_fail_closed() -> None:
    manifest = _fixed_memory_manifest()
    assert nested_dm._fixed_memory_manifest_errors(manifest) == []

    expanding = copy.deepcopy(manifest)
    expanding["feature_stages"][1]["memory"] = "expanding"
    assert any(
        "not bounded" in error
        for error in nested_dm._fixed_memory_manifest_errors(expanding)
    )

    boolean_window = copy.deepcopy(manifest)
    boolean_window["method_contract"]["train_window"] = True
    assert nested_dm._fixed_memory_manifest_errors(boolean_window)

    missing_lineage = copy.deepcopy(manifest)
    missing_lineage["primary_cells"][0]["used_stage_ids"].remove("signal")
    assert any(
        "without a used predictor-feature stage" in error
        for error in nested_dm._fixed_memory_manifest_errors(missing_lineage)
    )

    wrong_final_memory = copy.deepcopy(manifest)
    wrong_final_memory["feature_stages"][-1]["memory"] = "finite_lag"
    assert any(
        "final-estimator memory must be fixed_rolling" in error
        for error in nested_dm._fixed_memory_manifest_errors(wrong_final_memory)
    )

    malformed_stage_memory = copy.deepcopy(manifest)
    malformed_stage_memory["feature_stages"][0]["memory"] = []
    assert nested_dm._fixed_memory_manifest_errors(malformed_stage_memory)

    final_stage_as_predictor = copy.deepcopy(manifest)
    final_stage_as_predictor["primary_cells"][0]["augmented_predictors"].append(
        "forecast_aug"
    )
    assert any(
        "used predictor-feature stage" in error
        for error in nested_dm._fixed_memory_manifest_errors(final_stage_as_predictor)
    )

    malformed_predictors = copy.deepcopy(manifest)
    malformed_predictors["primary_cells"][0]["augmented_predictors"] = [["x"]]
    assert nested_dm._fixed_memory_manifest_errors(malformed_predictors)

    duplicate_parameters = copy.deepcopy(manifest)
    duplicate_parameters["implementation"]["augmented_model_parameter"] = "base"
    assert any(
        "model parameters must be distinct" in error
        for error in nested_dm._fixed_memory_manifest_errors(duplicate_parameters)
    )

    loose_alpha = copy.deepcopy(manifest)
    loose_alpha["decision_contract"]["family_alpha"] = 0.99
    loose_alpha["decision_contract"]["critical_value"] = 99.0
    assert nested_dm._fixed_memory_manifest_errors(loose_alpha)

    huge_horizon = copy.deepcopy(manifest)
    huge_horizon["primary_cells"][0]["horizon"] = 10**1000
    assert nested_dm._fixed_memory_manifest_errors(huge_horizon)


def test_complete_fixed_memory_runtime_envelope_is_valid(tmp_path: Path) -> None:
    manifest = _fixed_memory_manifest()
    path = tmp_path / "fixture.py"
    path.write_text("# fixture", encoding="utf-8")
    (tmp_path / "fixture_results.json").write_text(
        json.dumps(_fixed_memory_runtime(manifest)), encoding="utf-8"
    )
    assert nested_dm._fixed_memory_runtime_errors(path, manifest) == []


def test_reader_facing_figure_cannot_escape_the_review_receipt(tmp_path: Path) -> None:
    manifest = _fixed_memory_manifest()
    path = tmp_path / "fixture.py"
    path.write_text("# fixture", encoding="utf-8")
    (tmp_path / "fixture_results.json").write_text("{}", encoding="utf-8")
    (tmp_path / "fig1_result.png").write_bytes(b"stale reader-facing claim")

    errors = nested_dm._fixed_memory_claim_surface_errors(path, manifest)
    assert any("claim surface does not match" in error for error in errors)

    manifest["implementation"]["claim_surface_files"].append("fig1_result.png")
    assert nested_dm._fixed_memory_claim_surface_errors(path, manifest) == []


def test_deep_runtime_json_fails_closed_without_recursion_crash(tmp_path: Path) -> None:
    manifest = _fixed_memory_manifest()
    path = tmp_path / "fixture.py"
    path.write_text("# fixture", encoding="utf-8")
    payload = '{"deep":' + "[" * 5000 + "0" + "]" * 5000 + "}"
    (tmp_path / "fixture_results.json").write_text(payload, encoding="utf-8")
    errors = nested_dm._fixed_memory_runtime_errors(path, manifest)
    assert errors


@pytest.mark.parametrize(
    ("mutation", "needle"),
    [
        ("different_schedule", "base/aug training schedules differ"),
        ("unbounded_gate", "an unbounded record reaches a gate"),
        ("bool_standard_error", "standard_error is not finite-positive"),
        ("conditional_claim", "conditional/regime caveat"),
        ("extra_primary", "registry primary-cell set"),
        ("unmanifested_robustness", "unmanifested non-primary record reaches a gate"),
        ("primary_feeds_false", "gate-bearing set does not exactly match"),
        ("overflow_standard_error", "implied long-run variance"),
        ("wrong_hac_kernel", "hac_kernel disagrees"),
        ("wrong_hac_lag", "declared canonical rule"),
        ("wrong_z", "z does not equal mean/SE"),
        ("wrong_raw_p", "one-sided p-value disagrees"),
        ("wrong_holm", "gate Holm-adjusted p-value"),
        ("wrong_registry_holm", "registry Holm-adjusted p-value"),
        ("positive_headline_zero_pass", "polarity contradicts zero"),
        ("conditional_conclusion", "not locally unconditional"),
        ("shadow_gate", "outside the manifest-pinned inventories"),
        ("truthy_non_boolean_gate", "non-boolean feeds_gate"),
        ("missing_multiple_testing", "multiple-testing record is missing"),
    ],
)
def test_fixed_memory_runtime_evidence_is_adversarial(
    tmp_path: Path, mutation: str, needle: str
) -> None:
    manifest = _fixed_memory_manifest()
    runtime = _fixed_memory_runtime(manifest)
    if mutation == "different_schedule":
        runtime["nested_dm_fixed_memory_evidence_v1"]["cells"][0][
            "aug_training_schedule_sha256"
        ] = "b" * 64
    elif mutation == "unbounded_gate":
        runtime["multiple_testing"]["full_family_holm"][0]["bounded_memory"] = False
    elif mutation == "bool_standard_error":
        runtime["primary_cells"][0]["primary_inference"]["standard_error"] = True
    elif mutation == "conditional_claim":
        runtime["verdict_basis"]["does_not_say_1"] = "No further limitation."
    elif mutation == "extra_primary":
        extra = copy.deepcopy(runtime["multiple_testing"]["full_family_holm"][0])
        extra["cell"] = "primary|BTC_h1|OTHER|rv|fl1"
        runtime["multiple_testing"]["full_family_holm"].append(extra)
        runtime["multiple_testing"]["n_gate_eligible_gw_tests"] = 2
    elif mutation == "unmanifested_robustness":
        extra = copy.deepcopy(runtime["multiple_testing"]["full_family_holm"][0])
        extra.update(
            {
                "cell": "robustness|BTC_h1|AUG|rv|fl1",
                "family": "robustness",
                "claim_role": "non_primary_diagnostic_only",
            }
        )
        runtime["multiple_testing"]["full_family_holm"].append(extra)
        runtime["multiple_testing"]["n_gate_eligible_gw_tests"] = 2
    elif mutation == "primary_feeds_false":
        runtime["multiple_testing"]["full_family_holm"][0]["feeds_gate"] = False
    elif mutation == "overflow_standard_error":
        runtime["primary_cells"][0]["primary_inference"]["standard_error"] = 1e308
    elif mutation == "wrong_hac_kernel":
        runtime["primary_cells"][0]["primary_inference"]["hac_kernel"] = "Parzen"
    elif mutation == "wrong_hac_lag":
        runtime["primary_cells"][0]["primary_inference"]["hac_lag_used"] = 1
    elif mutation == "wrong_z":
        runtime["primary_cells"][0]["primary_inference"]["z_stat"] = 1.0
    elif mutation == "wrong_raw_p":
        runtime["primary_cells"][0]["primary_inference"][
            "p_value_one_sided_flow_better"
        ] = 0.1
    elif mutation == "wrong_holm":
        runtime["multiple_testing"]["primary_family"][0]["holm_adjusted_p"] = 0.1
    elif mutation == "wrong_registry_holm":
        runtime["multiple_testing"]["full_family_holm"][0]["holm_adjusted_p"] = 0.1
    elif mutation == "positive_headline_zero_pass":
        runtime["verdict_basis"]["claim_strength"] = (
            "Overwhelming UNCONDITIONAL predictive evidence was found."
        )
    elif mutation == "conditional_conclusion":
        runtime["verdict_basis"]["conclusion"] = (
            "Strong evidence proves the augmented model is better in every regime."
        )
    elif mutation == "shadow_gate":
        runtime["multiple_testing"]["full_family_holm"][0]["shadow"] = {
            "cell": "evil",
            "feeds_gate": True,
            "bounded_memory": False,
        }
    elif mutation == "truthy_non_boolean_gate":
        runtime["multiple_testing"]["full_family_holm"][0]["feeds_gate"] = 1
    elif mutation == "missing_multiple_testing":
        runtime["multiple_testing"] = None
    path = tmp_path / "fixture.py"
    path.write_text("# fixture", encoding="utf-8")
    (tmp_path / "fixture_results.json").write_text(
        json.dumps(runtime), encoding="utf-8"
    )
    errors = nested_dm._fixed_memory_runtime_errors(path, manifest)
    assert any(needle in error for error in errors), errors


@pytest.mark.parametrize(
    "declaration",
    [
        "NESTED_DM_FIXED_MEMORY_MANIFEST_V1 = {'schema': 'fake'}",
        "NESTED_DM_FIXED_MEMORY_MANIFEST_V1 = dict(schema='fake')",
        (
            "NESTED_DM_FIXED_MEMORY_MANIFEST_V1 = {'schema': 'fake'}\n"
            "NESTED_DM_FIXED_MEMORY_MANIFEST_V1 = {'schema': 'second'}"
        ),
    ],
)
def test_invalid_third_role_cannot_fall_through_a_safe_marker(
    tmp_path: Path, declaration: str
) -> None:
    path = _write_fixture(
        tmp_path,
        '"""Nested model; ordinary DM is descriptive only; nested-dm: cw-primary.\n'
        'PRIMARY family uses GW/DM for the verdict."""\n'
        f"{declaration}\n"
        "base_cols = ['x']\n"
        "aug_cols = base_cols + ['s']\n"
        "def classify(loss_base, loss_aug):\n"
        "    dm_t, _ = dm_test(loss_aug, loss_base, h=1)\n"
        "    return 'PASS' if dm_t < -3 else 'NULL'\n",
    )
    finding = scan_file(path, tmp_path, trust_root=tmp_path)
    assert finding is not None
    assert finding.test_role == "invalid_fixed_memory_evidence"
    assert finding.role_validation_errors


def test_third_role_declaration_cannot_bypass_validation_without_nesting_words(
    tmp_path: Path,
) -> None:
    path = _write_fixture(
        tmp_path,
        "NESTED_DM_FIXED_MEMORY_MANIFEST_V1 = {}\n"
        "PRIMARY_SCORE = raw_test(loss_a, loss_b)\n",
    )
    finding = scan_file(path, tmp_path, trust_root=tmp_path)
    assert finding is not None
    assert finding.test_role == "invalid_fixed_memory_evidence"
    assert finding.role_validation_errors


def test_importing_the_protocol_name_is_not_a_third_role_declaration(
    tmp_path: Path,
) -> None:
    path = _write_fixture(
        tmp_path,
        "from protocol import NESTED_DM_FIXED_MEMORY_MANIFEST_V1\n"
        "VALUE = NESTED_DM_FIXED_MEMORY_MANIFEST_V1\n",
    )
    assert scan_file(path, tmp_path, trust_root=tmp_path) is None


def test_function_local_locals_mapping_is_not_a_module_declaration(
    tmp_path: Path,
) -> None:
    path = _write_fixture(
        tmp_path,
        "def local_only():\n"
        "    locals().update(NESTED_DM_FIXED_MEMORY_MANIFEST_V1={})\n"
        "    vars().update(NESTED_DM_FIXED_MEMORY_MANIFEST_V1={})\n",
    )
    assert scan_file(path, tmp_path, trust_root=tmp_path) is None


def test_importing_the_protocol_name_cannot_hide_primary_raw_dm(
    tmp_path: Path,
) -> None:
    path = _write_fixture(
        tmp_path,
        "from protocol import NESTED_DM_FIXED_MEMORY_MANIFEST_V1\n"
        "base_cols = ['x']\n"
        "aug_cols = base_cols + ['signal']\n"
        "def classify(loss_base, loss_aug):\n"
        "    dm_t, dm_p = dm_test(loss_aug, loss_base, h=1)\n"
        "    verdict = 'PASS' if dm_p < 0.05 else 'NULL'\n"
        "    return verdict\n",
    )
    finding = scan_file(path, tmp_path, trust_root=tmp_path)
    assert finding is not None
    assert finding.test_role == "primary_raw_dm"


@pytest.mark.parametrize(
    "wrapped_declaration",
    [
        "if True:\n    NESTED_DM_FIXED_MEMORY_MANIFEST_V1 = {}\n",
        (
            "try:\n    NESTED_DM_FIXED_MEMORY_MANIFEST_V1 = {}\n"
            "except Exception:\n    pass\n"
        ),
        "for _ in [0]:\n    NESTED_DM_FIXED_MEMORY_MANIFEST_V1 = {}\n",
        "match 1:\n    case 1:\n        NESTED_DM_FIXED_MEMORY_MANIFEST_V1 = {}\n",
        "f = lambda x=(NESTED_DM_FIXED_MEMORY_MANIFEST_V1 := {}): x\n",
        "globals()['NESTED_DM_FIXED_MEMORY_MANIFEST_V1'] = {}\n",
        "globals()[f'NESTED_DM_FIXED_MEMORY_MANIFEST_V1'] = {}\n",
        (
            "globals().__setitem__(\n"
            "    'NESTED_DM_FIXED_' + 'MEMORY_MANIFEST_V1', {}\n"
            ")\n"
        ),
        "exec('NESTED_DM_FIXED_MEMORY_MANIFEST_V1 = {}')\n",
        (
            "import builtins\n"
            "builtins.exec(\n"
            "    'NESTED_DM_FIXED_MEMORY_MANIFEST_V1 = {}', globals()\n"
            ")\n"
        ),
        (
            "def bind():\n"
            "    global NESTED_DM_FIXED_MEMORY_MANIFEST_V1\n"
            "    NESTED_DM_FIXED_MEMORY_MANIFEST_V1 = {}\n"
            "bind()\n"
        ),
        (
            "def bind():\n"
            "    globals()['NESTED_DM_FIXED_MEMORY_MANIFEST_V1'] = {}\n"
            "bind()\n"
        ),
        (
            "def bind():\n"
            "    exec('NESTED_DM_FIXED_MEMORY_MANIFEST_V1 = {}', globals())\n"
            "bind()\n"
        ),
        (
            "import sys\n"
            "def bind():\n"
            "    exec('NESTED_DM_FIXED_MEMORY_MANIFEST_V1 = {}', "
            "sys.modules[__name__].__dict__)\n"
            "bind()\n"
        ),
        (
            "import sys\n"
            "def bind():\n"
            "    exec('NESTED_DM_FIXED_MEMORY_MANIFEST_V1 = {}', "
            "vars(sys.modules[__name__]))\n"
            "bind()\n"
        ),
        (
            "def bind():\n"
            "    exec('global NESTED_DM_FIXED_MEMORY_MANIFEST_V1\\n"
            "NESTED_DM_FIXED_MEMORY_MANIFEST_V1 = {}')\n"
            "bind()\n"
        ),
        (
            "def bind():\n"
            "    exec(\"globals()['NESTED_DM_FIXED_MEMORY_MANIFEST_V1'] = {}\")\n"
            "bind()\n"
        ),
        (
            "def bind():\n"
            "    exec('globals().__setitem__(\""
            "NESTED_DM_FIXED_MEMORY_MANIFEST_V1\", {})')\n"
            "bind()\n"
        ),
        (
            "bind = lambda: globals().__setitem__(\n"
            "    'NESTED_DM_FIXED_MEMORY_MANIFEST_V1', {}\n"
            ")\n"
            "bind()\n"
        ),
        (
            "def bind():\n"
            "    globals().update(\n"
            "        NESTED_DM_FIXED_MEMORY_MANIFEST_V1={}\n"
            "    )\n"
            "bind()\n"
        ),
        (
            "import sys\n"
            "sys.modules[__name__].NESTED_DM_FIXED_MEMORY_MANIFEST_V1 = {}\n"
        ),
        (
            "import sys\n"
            "setattr(\n"
            "    sys.modules.get(__name__),\n"
            "    'NESTED_DM_FIXED_MEMORY_MANIFEST_V1', {}\n"
            ")\n"
        ),
        (
            "import sys\n"
            "setattr(\n"
            "    sys.modules.__getitem__(__name__),\n"
            "    'NESTED_DM_FIXED_MEMORY_MANIFEST_V1', {}\n"
            ")\n"
        ),
        (
            "import operator\n"
            "import sys\n"
            "setattr(\n"
            "    operator.getitem(sys.modules, __name__),\n"
            "    'NESTED_DM_FIXED_MEMORY_MANIFEST_V1', {}\n"
            ")\n"
        ),
        "locals().update(NESTED_DM_FIXED_MEMORY_MANIFEST_V1={})\n",
        "vars().update(NESTED_DM_FIXED_MEMORY_MANIFEST_V1={})\n",
        (
            "globals().update(**{\n"
            "    'NESTED_DM_FIXED_MEMORY_MANIFEST_V1': {}\n"
            "})\n"
        ),
        (
            "dict.update(\n"
            "    globals(), NESTED_DM_FIXED_MEMORY_MANIFEST_V1={}\n"
            ")\n"
        ),
        (
            "globals().update(\n"
            "    dict(NESTED_DM_FIXED_MEMORY_MANIFEST_V1={})\n"
            ")\n"
        ),
        (
            "globals().update(\n"
            "    **dict(NESTED_DM_FIXED_MEMORY_MANIFEST_V1={})\n"
            ")\n"
        ),
        (
            "dict.__setitem__(\n"
            "    globals(), 'NESTED_DM_FIXED_MEMORY_MANIFEST_V1', {}\n"
            ")\n"
        ),
        (
            "globals().__ior__({\n"
            "    'NESTED_DM_FIXED_MEMORY_MANIFEST_V1': {}\n"
            "})\n"
        ),
        (
            "import operator\n"
            "operator.setitem(\n"
            "    globals(), 'NESTED_DM_FIXED_MEMORY_MANIFEST_V1', {}\n"
            ")\n"
        ),
        (
            "import operator\n"
            "operator.ior(globals(), {\n"
            "    'NESTED_DM_FIXED_MEMORY_MANIFEST_V1': {}\n"
            "})\n"
        ),
    ],
)
def test_module_scope_wrapped_declaration_cannot_fall_through_safe_marker(
    tmp_path: Path, wrapped_declaration: str
) -> None:
    path = _write_fixture(
        tmp_path,
        '"""Nested PRIMARY GW/DM verdict; nested-dm: cw-primary."""\n'
        + wrapped_declaration
        + "base_cols = ['x']\n"
        + "aug_cols = base_cols + ['signal']\n"
        + "def classify(loss_base, loss_aug):\n"
        + "    dm_t, dm_p = dm_test(loss_aug, loss_base, h=1)\n"
        + "    return 'PASS' if dm_p < 0.05 else 'NULL'\n",
    )
    finding = scan_file(path, tmp_path, trust_root=tmp_path)
    assert finding is not None
    assert finding.test_role == "invalid_fixed_memory_evidence"
    assert finding.role_validation_errors


def test_candidate_local_receipt_cannot_self_waive(tmp_path: Path) -> None:
    manifest = _fixed_memory_manifest()
    candidate = tmp_path / "candidate"
    trusted = tmp_path / "trusted"
    source = candidate / "experiments" / "fixture" / "fixture.py"
    source.parent.mkdir(parents=True)
    trusted.mkdir()
    source.write_text("# candidate", encoding="utf-8")
    (source.parent / "fixture_results.json").write_text("{}", encoding="utf-8")
    local_registry = candidate / nested_dm.FIXED_MEMORY_ADJUDICATIONS
    local_registry.parent.mkdir(parents=True)
    local_registry.write_text(
        json.dumps(
            {
                "schema": "nested_dm_fixed_memory_adjudications.v1",
                "entries": [{"site": "experiments/fixture/fixture.py"}],
            }
        ),
        encoding="utf-8",
    )
    errors, _ = nested_dm._fixed_memory_receipt_errors(
        source, trusted, "experiments/fixture/fixture.py", manifest
    )
    assert any("registry unavailable" in error for error in errors)


def _trusted_receipt_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, dict, Path, Path]:
    manifest = _fixed_memory_manifest()
    candidate = tmp_path / "candidate"
    trusted = tmp_path / "trusted"
    source = candidate / "experiments" / "fixture" / "fixture.py"
    source.parent.mkdir(parents=True)
    trusted.mkdir()
    source.write_text("# independently reviewed source\n", encoding="utf-8")
    runtime = source.parent / "fixture_results.json"
    runtime.write_text(json.dumps(_fixed_memory_runtime(manifest)), encoding="utf-8")
    claim_hashes = {
        name: hashlib.sha256((source.parent / name).read_bytes()).hexdigest()
        for name in manifest["implementation"]["claim_surface_files"]
    }
    entry = {
        "verdict": "PASS",
        "decision": "accepted",
        "role": nested_dm.FIXED_MEMORY_ROLE,
        "site": "experiments/fixture/fixture.py",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "manifest_sha256": nested_dm._canonical_sha256(manifest),
        "runtime_evidence": {
            "file": "fixture_results.json",
            "schema": nested_dm.FIXED_MEMORY_RUNTIME_SCHEMA,
            "sha256": hashlib.sha256(runtime.read_bytes()).hexdigest(),
        },
        "claim_surface_sha256": claim_hashes,
        "primary_cells": ["primary|BTC_h1|AUG|rv|fl1"],
        "reviewer": "independent-test-reviewer",
        "reviewed_commit": "1" * 40,
    }
    artifact_rel = "storage/ops/codex_reviews/fixed_memory_fixture.json"
    artifact = trusted / artifact_rel
    artifact.parent.mkdir(parents=True)
    receipt = {"schema": "nested_dm_fixed_memory_receipt.v1", **entry}
    artifact.write_text(json.dumps(receipt), encoding="utf-8")
    entry.update(
        {
            "review_artifact": artifact_rel,
            "review_artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        }
    )
    registry = trusted / nested_dm.FIXED_MEMORY_ADJUDICATIONS
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(
        json.dumps(
            {
                "schema": "nested_dm_fixed_memory_adjudications.v1",
                "entries": [entry],
            }
        ),
        encoding="utf-8",
    )

    def fake_git_show(command, **_kwargs):
        if command[1:3] == ["cat-file", "-t"]:
            return SimpleNamespace(returncode=0, stdout=b"commit\n", stderr=b"")
        relative = command[2].split(":", 1)[1]
        file_path = candidate / relative
        if not file_path.is_file():
            return SimpleNamespace(returncode=1, stdout=b"", stderr=b"missing")
        return SimpleNamespace(returncode=0, stdout=file_path.read_bytes(), stderr=b"")

    monkeypatch.setattr(nested_dm.subprocess, "run", fake_git_show)
    return source, trusted, manifest, artifact, registry


def test_trusted_pass_receipt_binds_reviewed_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, trusted, manifest, _, _ = _trusted_receipt_fixture(tmp_path, monkeypatch)
    errors, entry = nested_dm._fixed_memory_receipt_errors(
        source, trusted, "experiments/fixture/fixture.py", manifest
    )
    assert errors == []
    assert entry is not None and entry["verdict"] == "PASS"

    source.write_text("# drift after review\n", encoding="utf-8")
    errors, _ = nested_dm._fixed_memory_receipt_errors(
        source, trusted, "experiments/fixture/fixture.py", manifest
    )
    assert any("source hash is stale" in error for error in errors)
    assert any("claim-surface hash is stale" in error for error in errors)


def test_receipt_with_fail_verdict_never_accepts_the_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, trusted, manifest, artifact, registry = _trusted_receipt_fixture(
        tmp_path, monkeypatch
    )
    receipt = json.loads(artifact.read_text())
    receipt["verdict"] = "FAIL"
    artifact.write_text(json.dumps(receipt), encoding="utf-8")
    registry_payload = json.loads(registry.read_text())
    registry_payload["entries"][0]["verdict"] = "FAIL"
    registry_payload["entries"][0]["review_artifact_sha256"] = hashlib.sha256(
        artifact.read_bytes()
    ).hexdigest()
    registry.write_text(json.dumps(registry_payload), encoding="utf-8")
    errors, _ = nested_dm._fixed_memory_receipt_errors(
        source, trusted, "experiments/fixture/fixture.py", manifest
    )
    assert any("verdict is not PASS" in error for error in errors)


def test_receipt_rejects_an_invalid_artifact_path_without_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, trusted, manifest, _, registry = _trusted_receipt_fixture(
        tmp_path, monkeypatch
    )
    payload = json.loads(registry.read_text())
    payload["entries"][0]["review_artifact"] = "bad\x00path"
    registry.write_text(json.dumps(payload), encoding="utf-8")
    errors, _ = nested_dm._fixed_memory_receipt_errors(
        source, trusted, "experiments/fixture/fixture.py", manifest
    )
    assert any("artifact path is invalid" in error for error in errors), errors


def test_receipt_reviewed_object_must_be_a_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, trusted, manifest, _, _ = _trusted_receipt_fixture(tmp_path, monkeypatch)
    candidate = source.parents[2]

    def fake_git(command, **_kwargs):
        if command[1:3] == ["cat-file", "-t"]:
            return SimpleNamespace(returncode=0, stdout=b"tree\n", stderr=b"")
        relative = command[2].split(":", 1)[1]
        file_path = candidate / relative
        return SimpleNamespace(
            returncode=0 if file_path.is_file() else 1,
            stdout=file_path.read_bytes() if file_path.is_file() else b"",
            stderr=b"",
        )

    monkeypatch.setattr(nested_dm.subprocess, "run", fake_git)
    errors, _ = nested_dm._fixed_memory_receipt_errors(
        source, trusted, "experiments/fixture/fixture.py", manifest
    )
    assert any("not a commit object" in error for error in errors), errors


def test_third_role_has_no_candidate_local_trust_root(tmp_path: Path) -> None:
    assert nested_dm._trusted_repo_root(tmp_path) is None
