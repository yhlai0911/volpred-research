#!/usr/bin/env python3
"""
Reproducibility gate for paper/vt-trend-following/body_v3.tex.

Scope:
  - Current canonical numeric claims backed by K55 / K1192 / K1193 / K1376 /
    K1417 / K1457
  - Figure artifact presence after regeneration

This intentionally audits the manuscript's current canonical bindings rather
than legacy v2/v3 superseded numbers. It overwrites reproduce_report.json.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isclose
from pathlib import Path


PAPER_DIR = Path(__file__).resolve().parent
ROOT = PAPER_DIR.parents[1]
REPORT_PATH = PAPER_DIR / "reproduce_report.json"

ABS_TOL = 0.02


def load_json(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def approx(lhs, rhs, tol=ABS_TOL) -> bool:
    if lhs is None or rhs is None:
        return False
    return isclose(float(lhs), float(rhs), abs_tol=tol, rel_tol=0.0)


@dataclass
class CheckRow:
    section: str
    field: str
    expected: object
    actual: object
    status: str
    note: str = ""


class Audit:
    def __init__(self) -> None:
        self.rows: list[CheckRow] = []

    def check(self, section: str, field: str, expected, actual, tol=ABS_TOL, note="") -> None:
        status = "match" if approx(expected, actual, tol) else "mismatch"
        self.rows.append(CheckRow(section, field, expected, actual, status, note))

    def bool_check(self, section: str, field: str, expected: bool, actual: bool, note="") -> None:
        status = "match" if expected is actual else "mismatch"
        self.rows.append(CheckRow(section, field, expected, actual, status, note))

    def finalize(self) -> dict:
        total = len(self.rows)
        matched = sum(r.status == "match" for r in self.rows)
        mismatches = [r for r in self.rows if r.status == "mismatch"]
        match_rate = round(matched / total * 100, 1) if total else 0.0
        alert_level = "green" if not mismatches and match_rate >= 95.0 else ("yellow" if match_rate >= 80.0 else "red")
        gate_status = "pass" if alert_level == "green" else "fail"
        by_section: dict[str, dict[str, int]] = {}
        for row in self.rows:
            bucket = by_section.setdefault(row.section, {"match": 0, "mismatch": 0})
            bucket[row.status] += 1

        report = {
            "paper_id": "vt-trend-following",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "scope": [
                "Table 2 full-sample, split-sample, and K1457 continuous-vs-dummy checks",
                "Table 3 / Figure 1 / K1417 / Table 6 canonical MDD-retention numbers",
                "Bundled figure artifacts after regeneration",
            ],
            "alert_level": alert_level,
            "gate_status": gate_status,
            "total_checks": total,
            "matched_checks": matched,
            "mismatched_checks": len(mismatches),
            "match_rate_pct": match_rate,
            "traceable_match_rate_pct": match_rate,
            "by_section": by_section,
            "mismatches": [
                {
                    "section": r.section,
                    "field": r.field,
                    "expected": r.expected,
                    "actual": r.actual,
                    "note": r.note,
                }
                for r in mismatches
            ],
            "notes": [
                "This gate now targets the current canonical manuscript bindings, not superseded v2 numbers.",
                "Non-numeric citation and narrative issues remain outside the scope of this script.",
            ],
        }
        REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        return report


def verify_table2(audit: Audit, k55: dict, k1193: dict, k1457: dict) -> None:
    section = "Table 2 / Section 3.2"
    bt = k55["cross_sectional_analysis"]["beta_tsmom_orth_vs_gamma"]
    reg = k55["cross_sectional_analysis"]["cs_regression_orth"]
    split = k1193["results"]
    m1a = k1457["specifications"]["M1a_dummy_only"]
    m1 = k1457["specifications"]["M1_gamma_plus_dummy"]

    audit.check(section, "Full-sample Pearson r", 0.564, bt["pearson_r"], tol=0.001)
    audit.check(section, "Full-sample Pearson p", 0.006, bt["pearson_p"], tol=0.001)
    audit.check(section, "Full-sample Spearman rho", 0.544, bt["spearman_rho"], tol=0.001)
    audit.check(section, "Full-sample CI lower", 0.263, bt["pearson_ci_95"][0], tol=0.002)
    audit.check(section, "Full-sample CI upper", 0.772, bt["pearson_ci_95"][1], tol=0.002)
    audit.check(section, "Baseline gamma slope", 0.568, reg["gamma1"], tol=0.001)
    audit.check(section, "Baseline gamma t", 3.06, reg["gamma1_t"], tol=0.02)

    audit.check(section, "Split-sample Pearson r", 0.793, split["pearson_r"], tol=0.002)
    audit.check(section, "Split-sample CI lower", 0.589, split["ci_lo"], tol=0.002)
    audit.check(section, "Split-sample CI upper", 0.919, split["ci_hi"], tol=0.002)
    audit.check(section, "Split-sample Spearman rho", 0.749, split["spearman_rho"], tol=0.002)

    audit.check(section, "Dummy-only R2", 0.205, m1a["r2"], tol=0.002)
    audit.check(section, "Dummy-only coefficient", -0.075, m1a["coefficients"]["dummy_non_eq"]["coef"], tol=0.002)
    audit.check(section, "Dummy-only classical t", -2.27, m1a["coefficients"]["dummy_non_eq"]["t_classical"], tol=0.02)
    audit.check(section, "Dummy-only HC3 t", -1.84, m1a["coefficients"]["dummy_non_eq"]["t_hc3"], tol=0.02)

    audit.check(section, "Gamma+dummy gamma coefficient", 0.457, m1["coefficients"]["gamma"]["coef"], tol=0.002)
    audit.check(section, "Gamma+dummy gamma t", 2.00, m1["coefficients"]["gamma"]["t_classical"], tol=0.02)
    audit.check(section, "Gamma+dummy gamma HC3 t", 2.03, m1["coefficients"]["gamma"]["t_hc3"], tol=0.02)
    audit.check(section, "Gamma+dummy dummy coefficient", -0.032, m1["coefficients"]["dummy_non_eq"]["coef"], tol=0.002)
    audit.check(section, "Gamma attenuation pct", 19.5, k1457["pct_attenuation_gamma1"], tol=0.1)


def verify_table3_and_figure1(audit: Audit, k1192: dict) -> None:
    section = "Table 3 / Figure 1"
    expected = {
        "SPY": {"bh": -55.2, "vt": -26.3, "hedged": -25.3, "retention": 103.7, "total_pp": 28.9, "retained_pp": 29.9},
        "50/50": {"bh": -32.5, "vt": -16.8, "hedged": -17.5, "retention": 95.6, "total_pp": 15.7, "retained_pp": 15.0},
        "DIA": {"retention": 106.2},
        "QQQ": {"retention": 109.0},
        "IWM": {"retention": 102.2},
    }
    for asset, vals in expected.items():
        point = k1192["assets"][asset]["bootstrap_results"]["point_estimates"]
        if "bh" in vals:
            audit.check(section, f"{asset} B&H MDD", vals["bh"], point["bh_mdd_pct"], tol=0.1)
            audit.check(section, f"{asset} VT MDD", vals["vt"], point["vt_mdd_pct"], tol=0.1)
            audit.check(section, f"{asset} Hedged VT MDD", vals["hedged"], point["hedged_mdd_pct"], tol=0.1)
            total_pp = abs(point["bh_mdd_pct"]) - abs(point["vt_mdd_pct"])
            retained_pp = abs(point["bh_mdd_pct"]) - abs(point["hedged_mdd_pct"])
            audit.check(section, f"{asset} MDD protection pp", vals["total_pp"], total_pp, tol=0.1)
            audit.check(section, f"{asset} MDD retained pp", vals["retained_pp"], retained_pp, tol=0.1)
        audit.check(section, f"{asset} retention pct", vals["retention"], point["a_retention"], tol=0.1)


def verify_table6(audit: Audit, k1376: dict) -> None:
    section = "Table 6 / K1376"
    checks = {
        "SPY": {"point": 103.7, "median": 115.8, "lo": 93.0, "hi": 182.2},
        "50/50": {"point": 95.6, "median": 103.6, "lo": 76.0, "hi": 189.9},
        "XLE": {"point": 223.4, "median": 100.0, "lo": 37.7, "hi": 202.9},
        "SLV": {"point": 116.8, "median": 100.5, "lo": -2.5, "hi": 164.2},
        "VNQ": {"point": 126.4, "median": 109.1, "lo": 89.4, "hi": 186.8},
    }
    for asset, vals in checks.items():
        boot = k1376["results"][asset]["bootstrap"]
        audit.check(section, f"{asset} point", vals["point"], boot["point_estimates"]["a_retention"], tol=0.1)
        audit.check(section, f"{asset} median", vals["median"], boot["def_a_retention_fraction"]["median"], tol=0.1)
        audit.check(section, f"{asset} lo", vals["lo"], boot["def_a_retention_fraction"]["lo"], tol=0.1)
        audit.check(section, f"{asset} hi", vals["hi"], boot["def_a_retention_fraction"]["hi"], tol=0.1)


def verify_k1417(audit: Audit, k1192: dict, k1417: dict) -> None:
    section = "K1417 stationary-bootstrap table"
    expected = {
        "SPY": (93.0, 115.4, 97.1, 103.8, 97.7, 103.7),
        "50/50": (76.0, 103.6, 84.7, 95.6, 89.8, 95.6),
        "DIA": (82.3, 110.9, 91.3, 106.2, 93.4, 106.2),
        "QQQ": (89.0, 119.4, 97.5, 109.0, 97.5, 109.0),
        "IWM": (87.4, 108.2, 97.3, 103.3, 100.0, 102.9),
    }
    for asset, vals in expected.items():
        k1192_ret = k1192["assets"][asset]["bootstrap_results"]["def_a_retention_fraction"]
        b756 = k1417["assets"][asset]["by_mean_block"]["756"]["def_a_retention_fraction"]
        b1260 = k1417["assets"][asset]["by_mean_block"]["1260"]["def_a_retention_fraction"]
        audit.check(section, f"{asset} fixed252 lo", vals[0], k1192_ret["lo"], tol=0.1)
        audit.check(section, f"{asset} fixed252 median", vals[1], k1192_ret["median"], tol=0.1)
        audit.check(section, f"{asset} stat756 lo", vals[2], b756["lo"], tol=0.1)
        audit.check(section, f"{asset} stat756 median", vals[3], b756["median"], tol=0.1)
        audit.check(section, f"{asset} stat1260 lo", vals[4], b1260["lo"], tol=0.1)
        audit.check(section, f"{asset} stat1260 median", vals[5], b1260["median"], tol=0.1)

    shifts = [
        k1417["assets"][asset]["by_mean_block"]["1260"]["def_a_retention_fraction"]["lo"]
        - k1192["assets"][asset]["bootstrap_results"]["def_a_retention_fraction"]["lo"]
        for asset in ["SPY", "50/50", "DIA", "QQQ", "IWM"]
    ]
    shifts_sorted = sorted(shifts)
    median_shift = shifts_sorted[len(shifts_sorted) // 2]
    audit.check(section, "Mean lower-bound shift", 10.1, sum(shifts) / len(shifts), tol=0.1)
    audit.check(section, "Median lower-bound shift", 11.1, median_shift, tol=0.1)


def verify_figures(audit: Audit) -> None:
    section = "Figure artifacts"
    figures_dir = PAPER_DIR / "figures"
    audit.bool_check(section, "generate_figures.py exists", True, (figures_dir / "generate_figures.py").exists())
    audit.bool_check(section, "fig1_return_decomposition.pdf exists", True, (figures_dir / "fig1_return_decomposition.pdf").exists())
    audit.bool_check(section, "fig2_cross_asset_scatter.pdf exists", True, (figures_dir / "fig2_cross_asset_scatter.pdf").exists())


def main() -> int:
    k55 = load_json(PAPER_DIR / "experiments" / "vt_tsmom_final_n22.json")
    k1192 = load_json(ROOT / "experiments" / "k1192" / "k1192_results.json")
    k1193 = load_json(ROOT / "experiments" / "k1193" / "k1193_results.json")
    k1376 = load_json(ROOT / "experiments" / "k1376" / "k1376_results.json")
    k1417 = load_json(ROOT / "experiments" / "k1417" / "k1417_results.json")
    k1457 = load_json(ROOT / "experiments" / "k1457" / "k1457_results.json")

    audit = Audit()
    verify_table2(audit, k55, k1193, k1457)
    verify_table3_and_figure1(audit, k1192)
    verify_table6(audit, k1376)
    verify_k1417(audit, k1192, k1417)
    verify_figures(audit)

    report = audit.finalize()
    print(f"Match rate: {report['match_rate_pct']:.1f}%")
    print(f"Alert level: {report['alert_level']}")
    print(f"Gate status: {report['gate_status']}")
    print(f"reproduce_report.json written to {REPORT_PATH}")
    return 0 if report["gate_status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
