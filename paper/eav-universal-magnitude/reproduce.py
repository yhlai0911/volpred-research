"""
Reproducibility verification script for:
  "Earnings-Announcement Volatility Amplification: A Cross-Market Regularity
   with Magnitude Ordering — Evidence from Taiwan, U.S., and Japan Equity Markets"

Usage:
    python reproduce.py

Output:
    reproduce_report.json  — match_rate, alert_level, per-cell breakdown

This script reads from the local experiment JSON files (no live data fetch).
All source paths are relative to the project root.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent  # project root
PAPER_DIR = Path(__file__).parent
REPORT_PATH = PAPER_DIR / "reproduce_report.json"

# ── Reference values locked to paper claims (Table 1, Table 2, Table 3) ──────
# Format: {label: (expected_value, tolerance_fraction, source_path, json_key_chain)}
REFERENCE_TABLE = [
    # Table 1 — Main IS estimates
    {
        "label": "theta_eav_TW",
        "expected": 6.362165248598386e-05,
        "rtol": 1e-4,
        "source": "experiments/k1145/k1145_results.json",
        "keys": ["main_fit_eav_window_1", "theta_eav"],
        "paper_loc": "Table 1, TW row, θ̂_EAV",
    },
    {
        "label": "cluster_t_TW",
        "expected": 5.24205446767625,
        "rtol": 1e-4,
        "source": "experiments/k1145/k1145_results.json",
        "keys": ["cluster_bootstrap", "t_stat"],
        "paper_loc": "Table 1, TW row, cluster-boot t",
    },
    {
        "label": "ci_lo_TW",
        "expected": 4.1306308727984814e-05,
        "rtol": 1e-3,
        "source": "experiments/k1145/k1145_results.json",
        "keys": ["cluster_bootstrap", "ci_95", 0],
        "paper_loc": "Table 1, TW row, 95% CI lower",
    },
    {
        "label": "ci_hi_TW",
        "expected": 9.380079088948486e-05,
        "rtol": 1e-3,
        "source": "experiments/k1145/k1145_results.json",
        "keys": ["cluster_bootstrap", "ci_95", 1],
        "paper_loc": "Table 1, TW row, 95% CI upper",
    },
    {
        "label": "theta_eav_US",
        "expected": 0.00019089860360002893,
        "rtol": 1e-4,
        "source": "experiments/k1147/k1147_results.json",
        "keys": ["main_fit_eav_window_1", "theta_eav"],
        "paper_loc": "Table 1, US row, θ̂_EAV",
    },
    {
        "label": "cluster_t_US",
        "expected": 4.495682046447166,
        "rtol": 1e-4,
        "source": "experiments/k1147/k1147_results.json",
        "keys": ["cluster_bootstrap", "t_stat"],
        "paper_loc": "Table 1, US row, cluster-boot t",
    },
    {
        "label": "ci_lo_US",
        "expected": 0.00012854708414741794,
        "rtol": 1e-3,
        "source": "experiments/k1147/k1147_results.json",
        "keys": ["cluster_bootstrap", "ci_95", 0],
        "paper_loc": "Table 1, US row, 95% CI lower",
    },
    {
        "label": "ci_hi_US",
        "expected": 0.00027972115868475005,
        "rtol": 1e-3,
        "source": "experiments/k1147/k1147_results.json",
        "keys": ["cluster_bootstrap", "ci_95", 1],
        "paper_loc": "Table 1, US row, 95% CI upper",
    },
    {
        "label": "theta_eav_JP",
        "expected": 0.00014127865441754286,
        "rtol": 1e-4,
        "source": "experiments/k1150/k1150_results.json",
        "keys": ["main_fit_eav_window_1", "theta_eav"],
        "paper_loc": "Table 1, JP row, θ̂_EAV",
    },
    {
        "label": "cluster_t_JP",
        "expected": 11.988711745888638,
        "rtol": 1e-4,
        "source": "experiments/k1150/k1150_results.json",
        "keys": ["cluster_bootstrap", "t_stat"],
        "paper_loc": "Table 1, JP row, cluster-boot t",
    },
    {
        "label": "ci_lo_JP",
        "expected": 0.00012905130436150728,
        "rtol": 1e-3,
        "source": "experiments/k1150/k1150_results.json",
        "keys": ["cluster_bootstrap", "ci_95", 0],
        "paper_loc": "Table 1, JP row, 95% CI lower",
    },
    {
        "label": "ci_hi_JP",
        "expected": 0.00017575756620675766,
        "rtol": 1e-3,
        "source": "experiments/k1150/k1150_results.json",
        "keys": ["cluster_bootstrap", "ci_95", 1],
        "paper_loc": "Table 1, JP row, 95% CI upper",
    },
    # Table 2 — Placebo permutation
    {
        "label": "placebo_n_TW",
        "expected": 60,
        "rtol": 0,
        "source": "experiments/k1145/k1145_placebo_results.json",
        "keys": ["n_placebo"],
        "paper_loc": "Table 2, TW row, n_placebo",
    },
    {
        "label": "placebo_rejection_TW",
        "expected": 0.0,
        "rtol": 0,
        "source": "experiments/k1145/k1145_placebo_results.json",
        "keys": ["rejection_rate_one_sided"],
        "paper_loc": "Table 2, TW row, rejection rate",
    },
    {
        "label": "placebo_z_US",
        "expected": 70.74197260419099,
        "rtol": 1e-3,
        "source": "experiments/k1147/k1147_placebo_results.json",
        "keys": ["z_observed_relative_to_placebo"],
        "paper_loc": "Table 2, US row, placebo z",
    },
    {
        "label": "placebo_z_JP",
        "expected": 38.64792142936809,
        "rtol": 1e-3,
        "source": "experiments/k1150/k1150_placebo_results.json",
        "keys": ["z_observed_relative_to_placebo"],
        "paper_loc": "Table 2, JP row, placebo z",
    },
    # Table 3 — Factor absorption (K1149)
    {
        "label": "h1_absorption_US_is_t",
        "expected": 23.812069612851634,
        "rtol": 1e-4,
        "source": "experiments/k1149/k1149_results.json",
        "keys": ["h1_absorption", "us", "t_is"],
        "paper_loc": "Table 3, US row, IS t (factor absorption)",
    },
    {
        "label": "h1_absorption_TW_is_t",
        "expected": 10.618801224466884,
        "rtol": 1e-4,
        "source": "experiments/k1149/k1149_results.json",
        "keys": ["h1_absorption", "tw", "t_is"],
        "paper_loc": "Table 3, TW row, IS t (factor absorption)",
    },
    {
        "label": "h3_interaction_US_t",
        "expected": 5.038263489525833,
        "rtol": 1e-4,
        "source": "experiments/k1149/k1149_results.json",
        "keys": ["h3_interaction", "us", "t_stress"],
        "paper_loc": "Table 3, US row, stress-interaction t",
    },
    {
        "label": "h3_interaction_TW_t",
        "expected": -0.38525445175650225,
        "rtol": 1e-4,
        "source": "experiments/k1149/k1149_results.json",
        "keys": ["h3_interaction", "tw", "t_stress"],
        "paper_loc": "Table 3, TW row, stress-interaction t",
    },
]


def get_nested(obj, keys):
    """Navigate nested dict/list using a list of keys (str or int)."""
    for k in keys:
        obj = obj[k]
    return obj


def check_match(expected, actual, rtol):
    """Return True if actual is within rtol of expected (absolute for rtol==0)."""
    if rtol == 0:
        return expected == actual
    if expected == 0:
        return abs(actual) < 1e-12
    return abs(actual - expected) / abs(expected) <= rtol


def run():
    results = []
    n_pass = 0

    for ref in REFERENCE_TABLE:
        src_path = ROOT / ref["source"]
        try:
            data = json.loads(src_path.read_text())
            actual = get_nested(data, ref["keys"])
            match = check_match(ref["expected"], actual, ref["rtol"])
            status = "MATCH" if match else "MISMATCH"
            if match:
                n_pass += 1
            results.append(
                {
                    "label": ref["label"],
                    "status": status,
                    "expected": ref["expected"],
                    "actual": actual,
                    "rtol": ref["rtol"],
                    "paper_loc": ref["paper_loc"],
                    "source": ref["source"],
                }
            )
            sym = "✓" if match else "✗"
            print(f"  {sym} {ref['label']}: expected={ref['expected']:.4g}, actual={actual:.4g}")
        except (FileNotFoundError, KeyError, IndexError, TypeError) as e:
            results.append(
                {
                    "label": ref["label"],
                    "status": "ERROR",
                    "error": str(e),
                    "paper_loc": ref["paper_loc"],
                    "source": ref["source"],
                }
            )
            print(f"  ✗ {ref['label']}: ERROR — {e}")

    n_total = len(REFERENCE_TABLE)
    match_rate = n_pass / n_total
    alert_level = (
        "green" if match_rate >= 0.95
        else "yellow" if match_rate >= 0.80
        else "red"
    )

    report = {
        "paper": "eav-universal-magnitude",
        "match_rate": round(match_rate, 4),
        "n_pass": n_pass,
        "n_total": n_total,
        "alert_level": alert_level,
        "cells": results,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2))

    print(f"\nMatch rate: {n_pass}/{n_total} = {match_rate:.1%}  [{alert_level.upper()}]")
    print(f"Report written to: {REPORT_PATH}")
    return 0 if alert_level == "green" else 1


if __name__ == "__main__":
    os.chdir(ROOT)
    sys.exit(run())
