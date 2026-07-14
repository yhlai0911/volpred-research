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
            "runtime_evidence_file": "fixture_results.json",
            "runtime_evidence_key": "nested_dm_fixed_memory_evidence_v1",
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
            "hac_bandwidth_rule": "max(h-1, fixed rule)",
            "reference_distribution": "standard_normal",
            "estimand": "unconditional average proper-loss differential",
        },
        "feature_stages": [
            {
                "id": "state",
                "outputs": ["x"],
                "memory": "finite_lag",
                "max_observations": 2,
            },
            {
                "id": "signal",
                "outputs": ["s"],
                "memory": "finite_lag",
                "max_observations": 5,
            },
            {
                "id": "paired_log_variance_fit",
                "outputs": ["forecast_base", "forecast_aug"],
                "memory": "fixed_rolling",
                "max_observations": 50,
            },
        ],
        "expected_primary_cell_count": 1,
        "primary_cells": [
            {
                "id": "primary|BTC_h1|AUG|rv|fl1",
                "family": "primary",
                "asset": "BTC",
                "base": "BASE",
                "augmented": "AUG",
                "strictly_nested": True,
                "horizon": 1,
                "rv_proxy": "rv",
                "state_lag": 1,
                "flow_lag": 1,
                "smearing": "own",
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
        "hac_lag_used": 2,
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
    }
    envelope_cell = {
        "id": cell_id,
        "common_complete_case_mask_sha256": digest,
        "base_training_schedule_sha256": digest,
        "aug_training_schedule_sha256": digest,
        "origin_schedule_sha256": digest,
        "eligibility": "whole_method_fixed_memory_verified",
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
        "without a used stage" in error
        for error in nested_dm._fixed_memory_manifest_errors(missing_lineage)
    )


def test_complete_fixed_memory_runtime_envelope_is_valid(tmp_path: Path) -> None:
    manifest = _fixed_memory_manifest()
    path = tmp_path / "fixture.py"
    path.write_text("# fixture", encoding="utf-8")
    (tmp_path / "fixture_results.json").write_text(
        json.dumps(_fixed_memory_runtime(manifest)), encoding="utf-8"
    )
    assert nested_dm._fixed_memory_runtime_errors(path, manifest) == []


@pytest.mark.parametrize(
    ("mutation", "needle"),
    [
        ("different_schedule", "base/aug training schedules differ"),
        ("unbounded_gate", "an unbounded record reaches a gate"),
        ("bool_standard_error", "standard_error is not finite-positive"),
        ("conditional_claim", "conditional/regime caveat"),
        ("extra_primary", "registry primary-cell set"),
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
    errors, _ = nested_dm._fixed_memory_receipt_errors(source, trusted, manifest)
    assert any("registry unavailable" in error for error in errors)
