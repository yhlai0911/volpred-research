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
def affected(audit) -> set[str]:
    return {finding.file for finding in audit.findings}


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
        "diagnostic-only` and ensure it does not feed the claim sink."
    )


def test_baseline_only_contains_active_sites(
    affected: set[str], baseline: set[str]
) -> None:
    stale = baseline - affected
    assert not stale, (
        "Repaired/stale nested-DM sites must be pruned from the baseline: "
        f"{sorted(stale)}"
    )


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


def test_parse_failure_is_reported_not_silently_dropped(tmp_path: Path) -> None:
    _write_fixture(tmp_path, "def broken(:\n")
    result = scan_population(tmp_path)
    assert result.scan_errors
    assert "SyntaxError" in result.scan_errors[0]
