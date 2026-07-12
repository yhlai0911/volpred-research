"""Primary-review regression gates for the K1684 R3 rescue."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
EXP_DIR = ROOT / "experiments" / "k1684"
SCRIPT = EXP_DIR / "k1684_ftd_e1_scale_gating.py"
RESULTS = EXP_DIR / "k1684_ftd_e1_scale_gating_results.json"
R3_RECEIPT = EXP_DIR / "k1684_rerun_r3_receipt.json"

sys.path.insert(0, str(EXP_DIR))
spec = importlib.util.spec_from_file_location("k1684_r3_review_target", SCRIPT)
assert spec is not None and spec.loader is not None
k1684 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(k1684)


def test_common_support_is_symmetric_and_strictly_pre_origin() -> None:
    a = np.array([1.0, 1.0, np.nan, 1.0, 1.0, 1.0])
    b = np.array([1.0, 0.0, 1.0, 1.0, np.nan, 1.0])
    r = np.array([0.1, 0.2, 0.3, np.nan, 0.5, 0.6])

    forward = k1684._common_support(0, 5, a, b, r)
    reverse = k1684._common_support(0, 5, b, a, r)

    assert forward.tolist() == [0]
    assert np.array_equal(forward, reverse)
    assert 5 not in forward  # ``hi`` is the forecast origin and must stay excluded.


def test_rv_information_set_requires_same_day_as_well_as_clock_time() -> None:
    idx = pd.DatetimeIndex(["2026-01-05", "2026-01-06"])
    base = pd.DataFrame(
        {
            "path_end_hhmmss": [133000, 120000],
            "path_start_hhmmss": [133000, 133000],
            "path_end_ts": ["2026-01-05 13:30:00", "2026-01-07 12:00:00"],
        },
        index=idx,
    )
    audit = k1684.rv_information_set_audit(base)

    assert audit["n_days_path_ends_after_1330"] == 0
    assert audit["n_days_path_end_date_mismatch"] == 1
    assert audit["passed"] is False

    base.loc[idx[1], "path_end_ts"] = "2026-01-06 12:00:00"
    fixed = k1684.rv_information_set_audit(base)
    assert fixed["n_days_path_end_date_mismatch"] == 0
    assert fixed["passed"] is True


def test_trinity_is_kupiec_plus_cc_joint_plus_basel() -> None:
    r = np.zeros(450)
    r[[5, 18, 31, 44, 57, 70, 83, 96, 109, 122, 135, 148, 161, 174, 187,
       200, 213, 226, 239, 252, 265, 278]] = -2.0
    out = k1684.var_backtest_r2(r, np.full(450, -1.0), 0.05)

    expected = (out["kupiec"]["pass"]
                and out["christoffersen_cc_joint"]["pass"]
                and out["basel_traffic_light"] == "green")
    assert out["trinity_pass"] is expected
    assert "conditional-coverage joint" in out["trinity_definition"]


def test_acerbi_szekely_z1_detects_materially_shallow_es() -> None:
    r = np.zeros(500)
    r[np.arange(0, 500, 20)] = -2.0  # exactly 5% exceedances
    var = np.full(500, -1.0)

    calibrated = k1684.acerbi_szekely_z1_test(r, var, np.full(500, -2.0), 0.05)
    shallow = k1684.acerbi_szekely_z1_test(r, var, np.full(500, -1.1), 0.05)

    assert abs(calibrated["z1"]) < 1e-12
    assert calibrated["pass"] is True
    assert shallow["pass"] is False


def _gate_fixture(placebo_histsim_pass: bool) -> tuple[dict, dict, dict]:
    cells = {"1%": {}, "5%": {}}
    for alpha in cells:
        for variant in ["HAR", "HAR-a", "HAR-b", "HAR-c"]:
            for tail in k1684.TAIL_LAYERS:
                cells[alpha][f"{variant}+{tail}"] = {
                    "trinity_pass": False,
                    "kupiec": {"pass": False},
                }
        for name in ["GJR+CF", "GJR+Normal", "GJR+Skewed-t"]:
            cells[alpha][name] = {
                "trinity_pass": name == "GJR+CF",
                "kupiec": {"pass": name == "GJR+CF"},
            }
        cells[alpha]["GJRf-a+HistSim"] = {
            "trinity_pass": placebo_histsim_pass,
            "kupiec": {"pass": placebo_histsim_pass},
        }
    aligned = {"HAR-RV_vs_GJR": {"t_stat": 1.5, "p_value": 0.14, "n": 436}}
    mismatched = {"HAR-RV_vs_GJR": {"t_stat": -2.1, "p_value": 0.04, "n": 450}}
    return cells, aligned, mismatched


def test_placebo_histsim_cannot_influence_decide_gate() -> None:
    args_false = _gate_fixture(False)
    args_true = _gate_fixture(True)

    false_gate = k1684.decide_gate(*args_false)
    true_gate = k1684.decide_gate(*args_true)

    assert false_gate == true_gate
    assert false_gate["verdict"] == "H2_UNSUPPORTED"


def test_r3_artifacts_and_five_run_null_are_synchronized() -> None:
    results = json.loads(RESULTS.read_text())
    receipt = json.loads(R3_RECEIPT.read_text())

    assert results["revision"].startswith("R3")
    assert receipt["rerun"].startswith("R3")
    assert receipt["gate_verdict_r3"] == "H2_UNSUPPORTED"
    assert results["rv_information_set_audit"]["n_days_path_end_date_mismatch"] == 0
    assert results["rv_information_set_audit"]["passed"] is True
    assert all(run["gate"]["verdict"] == "H2_UNSUPPORTED"
               for run in results["runs"].values())

    alpha_cell_records = 0
    for run in results["runs"].values():
        for level in run["var_es_results"].values():
            for cell in level.values():
                alpha_cell_records += 1
                expected_trinity = (cell["kupiec"]["pass"]
                                    and cell["christoffersen_cc_joint"]["pass"]
                                    and cell["basel_traffic_light"] == "green")
                assert cell["trinity_pass"] is expected_trinity
                assert "acerbi_szekely_z1" in cell["es"]
    assert alpha_cell_records == 214

    rescued = {
        name: (run["gate"]["leg2_tail"]["n_variants_rescuing_har"],
               run["gate"]["leg2_tail"]["n_variants_estimable"])
        for name, run in results["runs"].items()
    }
    assert rescued == {
        "primary": (0, 3),
        "sens_theta_short": (1, 2),
        "sens_daily_refresh": (0, 3),
        "sens_burnin_tailpool": (3, 3),
        "sens_legacy_rv": (0, 3),
    }
    equivariance = results["runs"]["primary"]["histsim_scale_equivariance_check"]
    assert all(check["invariant"] is True for check in equivariance.values())
    assert max(check["max_abs_diff_vs_baseline_histsim"]
               for check in equivariance.values()) < 1e-15
