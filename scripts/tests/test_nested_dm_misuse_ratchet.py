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
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

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
