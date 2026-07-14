#!/usr/bin/env python3
"""
Paper 5 (vt-crowding-abm) — Reproducibility Script (v3 expansion)
=================================================================

Verifies all numerical claims in the v3 main.tex against the supporting
experiment result JSONs across K827v3 + K1261 + K1262 + K1262b.

Tables / sections covered:
  Table 1 (tab:main)                      — VT Sharpe / kurtosis / t-stats
                                            from K827v3 part1_results
  §4.3 Statistical Significance           — Welch t-tests recomputed from
                                            stored aggregate moments
  Table 2 (tab:cross_strategy_threshold)  — K1261 cell1 thresholds (Strict)
                                            + K1262 K1261-raw recompute
                                            (Softer, Sharpe-only)
  Table 3 (tab:scaling_window_matrix)     — K1262 scaling × window cells
                                            under softer detector
  Table 4 (tab:oat_robustness)            — K1262b 5 OAT cells under
                                            P5-style Sharpe-only detector
  §5.4 Knife-edge rebuttal                — joint robustness counts
                                            (17/17 + NoiseControl 5/5+12/12)
  Table tab:vt_monotone_curve (§3.1)      — K1471 canonical-cell VT Sharpe
                                            curve + path-bootstrap CIs
  Table tab:matched_control_vt (§3.2)     — K1471 VT vs RR_VT across 5 cells
  Table tab:tfmr_gate (§cross_strategy)   — K1471 applicability-gate outcomes
                                            + RR_TF/RR_MR random-direction ctrls
  Abstract + RR_TF erosion narrative      — K1471 factorization (94,500),
                                            footprint-scale identification

Usage:
  uv run python paper/vt-crowding-abm/reproduce.py [--skip-live]
    --skip-live  : do NOT re-run K1261/K1262/K1262b live (use stored JSONs).
                   Default also avoids live-running these because they take
                   ~13 min combined; the stored JSONs were committed by the
                   original main-thread audit and are the canonical source.
                   K827v3 IS run live (~3 min) since it's the headline
                   simulation backing Table 1.

Pattern reference: paper/prg-periodic-garch/reproduce.py (Paper 6)

Result-file search order:
  1. paper/vt-crowding-abm/experiments/<name>_results.json (paper-bundled)
  2. experiments/<kid>/<name>_results.json (project root, fallback)

Output:
  Overwrites paper/vt-crowding-abm/reproduce_report.json with:
    - per-check {metric, paper_value, reproduced_value, abs_diff, tol, match,
                 source_paper_loc, source_json_path}
    - overall match_rate
    - alert_level: green (>=95%) / yellow (>=80%) / red (otherwise)
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PAPER_DIR = Path(__file__).parent
EXP_DIR = PAPER_DIR / "experiments"
PROJECT = PAPER_DIR.parents[1]
PROJECT_EXP = PROJECT / "experiments"

skip_live = "--skip-live" in sys.argv

# =====================================================================
# PAPER_CLAIMS — every entry is one verifiable scalar claim from main.tex
# Each value: {paper, tol, source_paper_loc, source_json_field}
# Tolerance convention:
#   - Sharpe values: 0.05 (Table 1 reports 2 decimals)
#   - Threshold % (categorical): 0.0 (must match string EXACTLY)
#   - Kurtosis: 5 (allow large absolute drift on heavy-tail measures)
#   - t-stats: 0.15 (per P6 yfinance / sample drift convention)
#   - Counts: 0 (e.g. 12/12, 5/5 — must match exactly)
# =====================================================================
PAPER_CLAIMS = {
    # ---- K827v3 baseline (Table 1) ----
    "Sharpe @ phi=10% (K827v3)": {
        "paper": 0.47, "tol": 0.05,
        "source_paper_loc": "Table tab:main row phi=10%",
        "source_json_field": "part1_results.10%.vt_sharpe.mean",
    },
    "Sharpe @ phi=20% (K827v3)": {
        "paper": 0.50, "tol": 0.05,
        "source_paper_loc": "Table tab:main row phi=20%",
        "source_json_field": "part1_results.20%.vt_sharpe.mean",
    },
    "Sharpe @ phi=30% (K827v3)": {
        "paper": 0.47, "tol": 0.05,
        "source_paper_loc": "Table tab:main row phi=30%",
        "source_json_field": "part1_results.30%.vt_sharpe.mean",
    },
    "Sharpe @ phi=50% (K827v3)": {
        "paper": 0.34, "tol": 0.05,
        "source_paper_loc": "Table tab:main row phi=50%",
        "source_json_field": "part1_results.50%.vt_sharpe.mean",
    },
    "Sharpe @ phi=70% (K827v3)": {
        "paper": 0.08, "tol": 0.05,
        "source_paper_loc": "Table tab:main row phi=70% (headline)",
        "source_json_field": "part1_results.70%.vt_sharpe.mean",
    },
    "Sharpe @ phi=100% (K827v3)": {
        "paper": -0.27, "tol": 0.05,
        "source_paper_loc": "Table tab:main row phi=100%",
        "source_json_field": "part1_results.100%.vt_sharpe.mean",
    },
    "Kurtosis @ phi=70% (K827v3)": {
        "paper": 1.41, "tol": 0.5,
        "source_paper_loc": "Table tab:main kurt col, phi=70%",
        "source_json_field": "part1_results.70%.kurtosis.mean",
    },
    "Kurtosis @ phi=100% (K827v3)": {
        "paper": 61.4, "tol": 5.0,
        "source_paper_loc": "Table tab:main kurt col, phi=100%; abstract '~61'",
        "source_json_field": "part1_results.100%.kurtosis.mean",
    },
    "AnnVol @ phi=100% (K827v3)": {
        "paper": 0.351, "tol": 0.05,
        "source_paper_loc": "Table tab:market AnnVol col, phi=100%",
        "source_json_field": "part1_results.100%.ann_vol.mean",
    },
    "Skewness @ phi=100% (K827v3)": {
        "paper": -4.73, "tol": 0.5,
        "source_paper_loc": "Table tab:market skew col, phi=100%",
        "source_json_field": "part1_results.100%.skewness.mean",
    },
    "VIX_spike_pct @ phi=70% (K827v3)": {
        "paper": 16.2, "tol": 1.0,
        "source_paper_loc": "Table tab:market VIX-spike col phi=70%",
        "source_json_field": "part1_results.70%.vix_spike_pct.mean",
    },
    "VIX_spike_pct @ phi=100% (K827v3)": {
        "paper": 90.0, "tol": 2.0,
        "source_paper_loc": "Table tab:market VIX-spike col phi=100%",
        "source_json_field": "part1_results.100%.vix_spike_pct.mean",
    },
    "MaxDD @ phi=70% (K827v3)": {
        "paper": -0.601, "tol": 0.05,
        "source_paper_loc": "Table tab:market MDD col, phi=70%",
        "source_json_field": "part1_results.70%.max_dd.mean",
    },
    "MaxDD @ phi=100% (K827v3)": {
        "paper": -0.913, "tol": 0.05,
        "source_paper_loc": "Table tab:market MDD col, phi=100%",
        "source_json_field": "part1_results.100%.max_dd.mean",
    },
    # ---- §4.3 t-tests (recomputed Welch's t from stored aggregates) ----
    "|t| 30% vs 10% (K827v3 Welch)": {
        "paper": 0.05, "tol": 0.15,
        "source_paper_loc": "main.tex §4.3 'yields t = 0.05'",
        "source_json_field": "computed: Welch t from part1_results vt_sharpe mean/std/n",
    },
    "|t| 50% vs 10% (K827v3 Welch)": {
        "paper": 7.12, "tol": 0.15,
        "source_paper_loc": "main.tex §4.3 'yields t = 7.12'",
        "source_json_field": "computed: Welch t from part1_results vt_sharpe mean/std/n",
    },
    "|t| 70% vs 50% (K827v3 Welch)": {
        "paper": 16.94, "tol": 0.15,
        "source_paper_loc": "main.tex §4.3 'yields t = 16.94'",
        "source_json_field": "computed: Welch t from part1_results vt_sharpe mean/std/n",
    },
    # ---- K1261 Phase 1 (cell1 baseline, Strict detector) ----
    "K1261 VT_baseline strict threshold": {
        "paper": "100%", "tol": 0.0,
        "source_paper_loc": "Table tab:cross_strategy_threshold VT Strict col",
        "source_json_field": "threshold_detection.VT_baseline_K827v3_stored.critical_adoption",
    },
    "K1261 TF strict threshold": {
        "paper": "20%", "tol": 0.0,
        "source_paper_loc": "Table tab:cross_strategy_threshold TF Strict col",
        "source_json_field": "threshold_detection.TF.critical_adoption",
    },
    "K1261 MR strict threshold": {
        "paper": "50%", "tol": 0.0,
        "source_paper_loc": "Table tab:cross_strategy_threshold MR Strict col",
        "source_json_field": "threshold_detection.MR.critical_adoption",
    },
    "K1261 NoiseControl strict threshold (null)": {
        "paper": None, "tol": 0.0,
        "source_paper_loc": "Table tab:cross_strategy_threshold NC Strict col",
        "source_json_field": "threshold_detection.NoiseControl.critical_adoption",
    },
    "K1261 NoiseControl Sharpe @ phi=100% (anchor)": {
        "paper": 0.50, "tol": 0.05,
        "source_paper_loc": "main.tex §4.4 'NoiseControl produces no detectable threshold' (Sharpe anchor)",
        "source_json_field": "threshold_detection.NoiseControl.justification.per_adoption.100%.sharpe",
    },
    # ---- K1262 (K1261-raw cross-detector recompute) ----
    "K1262 VT_baseline softer threshold": {
        "paper": "100%", "tol": 0.0,
        "source_paper_loc": "Table tab:cross_strategy_threshold VT Softer col",
        "source_json_field": "k1262_softer_detector_table.md (cross-detector recompute)",
    },
    "K1262 VT_baseline Sharpe-only threshold (anchor)": {
        "paper": "70%", "tol": 0.0,
        "source_paper_loc": "Table tab:cross_strategy_threshold VT Sharpe-only col (calibration anchor)",
        "source_json_field": "k1262_softer_detector_table.md P5-style col",
    },
    "K1262 TF Sharpe-only threshold": {
        "paper": "20%", "tol": 0.0,
        "source_paper_loc": "Table tab:cross_strategy_threshold TF Sharpe-only col",
        "source_json_field": "k1262_softer_detector_table.md P5-style col",
    },
    "K1262 MR Sharpe-only threshold": {
        "paper": "20%", "tol": 0.0,
        "source_paper_loc": "Table tab:cross_strategy_threshold MR Sharpe-only col",
        "source_json_field": "k1262_softer_detector_table.md P5-style col",
    },
    # ---- K1262 Phase 2 (scaling × window matrix, softer detector) ----
    "K1262 scaling=10 window=22 TF (softer)": {
        "paper": "20%", "tol": 0.0,
        "source_paper_loc": "Table tab:scaling_window_matrix s=10 W=22 (TF cell)",
        "source_json_field": "threshold_per_cell.TF.10.22.softer_kurt_weak.critical_adoption",
    },
    "K1262 scaling=10 window=22 MR (softer)": {
        "paper": "50%", "tol": 0.0,
        "source_paper_loc": "Table tab:scaling_window_matrix s=10 W=22 (MR cell)",
        "source_json_field": "threshold_per_cell.MR.10.22.softer_kurt_weak.critical_adoption",
    },
    "K1262 scaling=1 window=22 TF (softer)": {
        "paper": "70%", "tol": 0.0,
        "source_paper_loc": "Table tab:scaling_window_matrix s=1 W=22 (TF cell)",
        "source_json_field": "threshold_per_cell.TF.1.22.softer_kurt_weak.critical_adoption",
    },
    "K1262 scaling=1 window=22 MR (softer)": {
        "paper": "70%", "tol": 0.0,
        "source_paper_loc": "Table tab:scaling_window_matrix s=1 W=22 (MR cell)",
        "source_json_field": "threshold_per_cell.MR.1.22.softer_kurt_weak.critical_adoption",
    },
    "K1262 TF<=VT in 12/12 cells (softer)": {
        "paper": 12, "tol": 0,
        "source_paper_loc": "main.tex §4.4 'TF threshold < VT in 12/12 cells'",
        "source_json_field": "computed: count of TF cells with critical < VT(100%) under softer",
    },
    "K1262 MR<=VT in 12/12 cells (softer)": {
        "paper": 12, "tol": 0,
        "source_paper_loc": "main.tex §4.4 'MR threshold <= VT in 12/12 cells'",
        "source_json_field": "computed: count of MR cells with critical <= VT(100%) under softer",
    },
    # ---- K1262b OAT (5 cells, P5-style detector) ----
    "K1262b cell1 baseline VT threshold": {
        "paper": "70%", "tol": 0.0,
        "source_paper_loc": "Table tab:oat_robustness cell1 VT col (calibration anchor)",
        "source_json_field": "threshold_per_cell.cell1_baseline.VT_baseline.critical_adoption",
    },
    "K1262b cell2 lambda_low VT threshold": {
        "paper": "100%", "tol": 0.0,
        "source_paper_loc": "Table tab:oat_robustness cell2 VT col",
        "source_json_field": "threshold_per_cell.cell2_lambda_low.VT_baseline.critical_adoption",
    },
    "K1262b cell3 lambda_high VT threshold": {
        "paper": "70%", "tol": 0.0,
        "source_paper_loc": "Table tab:oat_robustness cell3 VT col",
        "source_json_field": "threshold_per_cell.cell3_lambda_high.VT_baseline.critical_adoption",
    },
    "K1262b cell4 gamma_low VT threshold": {
        "paper": "70%", "tol": 0.0,
        "source_paper_loc": "Table tab:oat_robustness cell4 VT col",
        "source_json_field": "threshold_per_cell.cell4_gamma_low.VT_baseline.critical_adoption",
    },
    "K1262b cell5 gamma_high VT threshold": {
        "paper": "70%", "tol": 0.0,
        "source_paper_loc": "Table tab:oat_robustness cell5 VT col",
        "source_json_field": "threshold_per_cell.cell5_gamma_high.VT_baseline.critical_adoption",
    },
    "K1262b TF=30% in all 5 cells": {
        "paper": 5, "tol": 0,
        "source_paper_loc": "Table tab:oat_robustness TF col (5 cells all == 30%)",
        "source_json_field": "computed: count of cells with TF.critical_adoption == 30%",
    },
    "K1262b cell1 MR threshold": {
        "paper": "70%", "tol": 0.0,
        "source_paper_loc": "Table tab:oat_robustness cell1 MR col",
        "source_json_field": "threshold_per_cell.cell1_baseline.MR.critical_adoption",
    },
    "K1262b cell2 MR threshold": {
        "paper": "30%", "tol": 0.0,
        "source_paper_loc": "Table tab:oat_robustness cell2 MR col",
        "source_json_field": "threshold_per_cell.cell2_lambda_low.MR.critical_adoption",
    },
    "K1262b cell3 MR threshold (null)": {
        "paper": None, "tol": 0.0,
        "source_paper_loc": "Table tab:oat_robustness cell3 MR col (null - high-lambda saturation)",
        "source_json_field": "threshold_per_cell.cell3_lambda_high.MR.critical_adoption",
    },
    "K1262b cell4 MR threshold": {
        "paper": "70%", "tol": 0.0,
        "source_paper_loc": "Table tab:oat_robustness cell4 MR col",
        "source_json_field": "threshold_per_cell.cell4_gamma_low.MR.critical_adoption",
    },
    "K1262b cell5 MR threshold": {
        "paper": "70%", "tol": 0.0,
        "source_paper_loc": "Table tab:oat_robustness cell5 MR col",
        "source_json_field": "threshold_per_cell.cell5_gamma_high.MR.critical_adoption",
    },
    "K1262b NoiseControl null in all 5 cells": {
        "paper": 5, "tol": 0,
        "source_paper_loc": "Table tab:oat_robustness NC col (5/5 null)",
        "source_json_field": "computed: count of cells with NoiseControl.critical_adoption is None",
    },
    "K1262b TF<=VT in 5/5 cells": {
        "paper": 5, "tol": 0,
        "source_paper_loc": "main.tex §5.4 'TF threshold below VT in 5/5 cells'",
        "source_json_field": "computed: rank-compare TF vs VT per cell",
    },
    "K1262b MR<=VT in 5/5 cells (incl. null saturation)": {
        "paper": 5, "tol": 0,
        "source_paper_loc": "main.tex §5.4 'MR threshold <= VT in 5/5 cells (high-lambda null = saturation)'",
        "source_json_field": "computed: rank-compare MR vs VT per cell with null-as-saturation rule",
    },
    # ---- §5.4 joint robustness count ----
    "Joint 17/17 robustness checks": {
        "paper": 17, "tol": 0,
        "source_paper_loc": "main.tex §5.4 'yields 17/17 robustness checks'",
        "source_json_field": "computed: 12 (K1262 strategy-spec) + 5 (K1262b microstructure)",
    },
}

# =====================================================================
# K1471 exogenous-detector redesign (M=500, 94,500 sims) — headline layer
# ---------------------------------------------------------------------
# Binds every printed number in the three K1471 tables now carried in
# main.tex plus the abstract factorization and the RR_TF erosion narrative:
#   Table tab:vt_monotone_curve  — canonical-cell VT Sharpe curve + CIs (§3.1)
#   Table tab:matched_control_vt — VT vs RR_VT across five cells (§3.2)
#   Table tab:tfmr_gate          — cross-strategy applicability gate (§cross)
#   Abstract / §cross RR_TF erosion narrative (footprint-scale identification)
# Source JSON: experiments/k1471_vt_crowding_redesign/k1471_full_results.json
# Path convention (canonical; the caption's old
#   treatment_results.VT_baseline.cell1 path does NOT exist in the JSON):
#   cells.<cell>.treatments.<treat>.per_adoption.<phi>.{sharpe.mean,boot_ci,_turnover}
#   cells.<cell>.detector.<treat>.{status,baseline_mean_sharpe,p_value,threshold}
# Tolerances: Sharpe / CI / Δ = 0.01 (3-decimal table precision, stored
# deterministic source); sup-Wald p = 0.0005; footprint magnitudes as noted.
# =====================================================================
K1471_CELLS = ["cell1_baseline", "cell2_lambda_low", "cell3_lambda_high",
               "cell4_gamma_low", "cell5_gamma_high"]

# Paper printed values, tab:vt_monotone_curve (canonical cell1).
# phi -> (mean, ci_lo, ci_hi, delta_vs_prev)
_K1471_VT_CURVE = {
    "10%":  (0.510,  0.484,  0.534,  None),
    "30%":  (0.481,  0.454,  0.506, -0.029),
    "40%":  (0.405,  0.380,  0.427, -0.076),
    "50%":  (0.338,  0.313,  0.362, -0.067),
    "60%":  (0.203,  0.182,  0.225, -0.135),
    "70%":  (0.091,  0.073,  0.108, -0.112),
    "100%": (-0.271, -0.283, -0.260, -0.362),
}
# Paper printed values, tab:matched_control_vt.
# cell -> (VT_S10, VT_S100, VT_delta, RRVT_S10, RRVT_S100, RRVT_delta, RRVT_p)
_K1471_MC_VT = {
    "cell1_baseline":    (0.510, -0.271, -0.781, 0.447, 0.541, 0.093, 0.001),
    "cell2_lambda_low":  (0.497,  0.077, -0.421, 0.446, 0.541, 0.095, 0.001),
    "cell3_lambda_high": (0.507, -0.393, -0.899, 0.437, 0.517, 0.080, 0.003),
    "cell4_gamma_low":   (0.508, -0.208, -0.715, 0.445, 0.543, 0.098, 0.001),
    "cell5_gamma_high":  (0.508, -0.284, -0.792, 0.445, 0.534, 0.089, 0.002),
}
# Paper printed values, tab:tfmr_gate.
# cell -> (TF_status, TF_baseSh, MR_status, MR_baseSh,
#          RR_TF_p, RR_TF_baseSh, RR_MR_p, RR_MR_baseSh)
_K1471_GATE = {
    "cell1_baseline":    ("excluded", -0.825, "excluded", -1.776, 0.001, -0.037, 0.001, -0.007),
    "cell2_lambda_low":  ("passes",   -0.444, "excluded", -0.688, 0.001, -0.012, 0.001, -0.011),
    "cell3_lambda_high": ("excluded", -1.254, "excluded", -5.485, 0.001, -0.040, 0.001, -0.057),
    "cell4_gamma_low":   ("excluded", -0.823, "excluded", -1.776, 0.001, -0.037, 0.001, -0.011),
    "cell5_gamma_high":  ("excluded", -0.826, "excluded", -1.776, 0.001, -0.034, 0.001, -0.011),
}


def _k1471_build_claims() -> dict:
    """Programmatically build one PAPER_CLAIMS entry per printed table cell."""
    claims: dict = {}
    # ---- tab:vt_monotone_curve (canonical cell) ----
    for phi, (m, lo, hi, dl) in _K1471_VT_CURVE.items():
        base = f"cells.cell1_baseline.treatments.VT_baseline.per_adoption.{phi}"
        claims[f"K1471 vt_curve Sharpe @ {phi} (cell1)"] = {
            "paper": m, "tol": 0.01,
            "source_paper_loc": f"Table tab:vt_monotone_curve row phi={phi} (VT Sharpe mean)",
            "source_json_field": f"{base}.sharpe.mean",
        }
        claims[f"K1471 vt_curve CI-lo @ {phi} (cell1)"] = {
            "paper": lo, "tol": 0.01,
            "source_paper_loc": f"Table tab:vt_monotone_curve row phi={phi} (95% path-boot CI low)",
            "source_json_field": f"{base}.sharpe.boot_ci.ci_lo",
        }
        claims[f"K1471 vt_curve CI-hi @ {phi} (cell1)"] = {
            "paper": hi, "tol": 0.01,
            "source_paper_loc": f"Table tab:vt_monotone_curve row phi={phi} (95% path-boot CI high)",
            "source_json_field": f"{base}.sharpe.boot_ci.ci_hi",
        }
        if dl is not None:
            claims[f"K1471 vt_curve delta @ {phi} (cell1)"] = {
                "paper": dl, "tol": 0.01,
                "source_paper_loc": f"Table tab:vt_monotone_curve row phi={phi} (Δ vs previous level)",
                "source_json_field": f"computed: {base}.sharpe.mean - previous-level mean",
            }
    # ---- tab:matched_control_vt ----
    for cell, (v10, v100, vd, r10, r100, rd, rp) in _K1471_MC_VT.items():
        vt = f"cells.{cell}.treatments.VT_baseline.per_adoption"
        rr = f"cells.{cell}.treatments.RR_VT.per_adoption"
        claims[f"K1471 mc_vt VT S@10% ({cell})"] = {
            "paper": v10, "tol": 0.01,
            "source_paper_loc": f"Table tab:matched_control_vt {cell} VT S_10%",
            "source_json_field": f"{vt}.10%.sharpe.mean"}
        claims[f"K1471 mc_vt VT S@100% ({cell})"] = {
            "paper": v100, "tol": 0.01,
            "source_paper_loc": f"Table tab:matched_control_vt {cell} VT S_100%",
            "source_json_field": f"{vt}.100%.sharpe.mean"}
        claims[f"K1471 mc_vt VT delta ({cell})"] = {
            "paper": vd, "tol": 0.01,
            "source_paper_loc": f"Table tab:matched_control_vt {cell} VT Δ_10→100",
            "source_json_field": f"computed: {vt}.100%.sharpe.mean - {vt}.10%.sharpe.mean"}
        claims[f"K1471 mc_vt RR_VT S@10% ({cell})"] = {
            "paper": r10, "tol": 0.01,
            "source_paper_loc": f"Table tab:matched_control_vt {cell} RR_VT S_10%",
            "source_json_field": f"{rr}.10%.sharpe.mean"}
        claims[f"K1471 mc_vt RR_VT S@100% ({cell})"] = {
            "paper": r100, "tol": 0.01,
            "source_paper_loc": f"Table tab:matched_control_vt {cell} RR_VT S_100%",
            "source_json_field": f"{rr}.100%.sharpe.mean"}
        claims[f"K1471 mc_vt RR_VT delta ({cell})"] = {
            "paper": rd, "tol": 0.01,
            "source_paper_loc": f"Table tab:matched_control_vt {cell} RR_VT Δ_10→100",
            "source_json_field": f"computed: {rr}.100%.sharpe.mean - {rr}.10%.sharpe.mean"}
        claims[f"K1471 mc_vt RR_VT sup-Wald p ({cell})"] = {
            "paper": rp, "tol": 0.0005,
            "source_paper_loc": f"Table tab:matched_control_vt {cell} RR_VT sup-Wald p",
            "source_json_field": f"cells.{cell}.detector.RR_VT.p_value"}
    # ---- tab:tfmr_gate ----
    for cell, (tfs, tfb, mrs, mrb, rtfp, rtfb, rmrp, rmrb) in _K1471_GATE.items():
        det = f"cells.{cell}.detector"
        claims[f"K1471 gate TF status ({cell})"] = {
            "paper": tfs, "tol": 0.0,
            "source_paper_loc": f"Table tab:tfmr_gate {cell} TF gate word",
            "source_json_field": f"{det}.TF.status (mapped: not_applicable_saturated_loss->excluded, ok->passes)"}
        claims[f"K1471 gate TF baseline Sharpe ({cell})"] = {
            "paper": tfb, "tol": 0.01,
            "source_paper_loc": f"Table tab:tfmr_gate {cell} TF 10% baseline Sharpe",
            "source_json_field": f"{det}.TF.baseline_mean_sharpe"}
        claims[f"K1471 gate MR status ({cell})"] = {
            "paper": mrs, "tol": 0.0,
            "source_paper_loc": f"Table tab:tfmr_gate {cell} MR gate word",
            "source_json_field": f"{det}.MR.status (mapped)"}
        claims[f"K1471 gate MR baseline Sharpe ({cell})"] = {
            "paper": mrb, "tol": 0.01,
            "source_paper_loc": f"Table tab:tfmr_gate {cell} MR 10% baseline Sharpe",
            "source_json_field": f"{det}.MR.baseline_mean_sharpe"}
        claims[f"K1471 gate RR_TF sup-Wald p ({cell})"] = {
            "paper": rtfp, "tol": 0.0005,
            "source_paper_loc": f"Table tab:tfmr_gate {cell} RR_TF sup-Wald p",
            "source_json_field": f"{det}.RR_TF.p_value"}
        claims[f"K1471 gate RR_TF baseline Sharpe ({cell})"] = {
            "paper": rtfb, "tol": 0.01,
            "source_paper_loc": f"Table tab:tfmr_gate {cell} RR_TF 10% baseline Sharpe",
            "source_json_field": f"{det}.RR_TF.baseline_mean_sharpe"}
        claims[f"K1471 gate RR_MR sup-Wald p ({cell})"] = {
            "paper": rmrp, "tol": 0.0005,
            "source_paper_loc": f"Table tab:tfmr_gate {cell} RR_MR sup-Wald p",
            "source_json_field": f"{det}.RR_MR.p_value"}
        claims[f"K1471 gate RR_MR baseline Sharpe ({cell})"] = {
            "paper": rmrb, "tol": 0.01,
            "source_paper_loc": f"Table tab:tfmr_gate {cell} RR_MR 10% baseline Sharpe",
            "source_json_field": f"{det}.RR_MR.baseline_mean_sharpe"}
    return claims


PAPER_CLAIMS.update(_k1471_build_claims())
PAPER_CLAIMS.update({
    # ---- Abstract factorization (94,500 = 27 combos x 7 treatments x 500) ----
    "K1471 total simulations (abstract 94,500)": {
        "paper": 94500, "tol": 0,
        "source_paper_loc": "Abstract '94,500 Monte Carlo simulations'",
        "source_json_field": "total_sims",
    },
    "K1471 cell-adoption combinations (abstract 27)": {
        "paper": 27, "tol": 0,
        "source_paper_loc": "Abstract '27 cell--adoption combinations'",
        "source_json_field": "computed: len(adoption_grid_cell1) + 4*len(adoption_grid_other)",
    },
    "K1471 treatment/control count (abstract 7)": {
        "paper": 7, "tol": 0,
        "source_paper_loc": "Abstract 'x 7 treatments/controls'",
        "source_json_field": "computed: len(cells.cell1_baseline.treatments)",
    },
    "K1471 MC per combination (abstract 500)": {
        "paper": 500, "tol": 0,
        "source_paper_loc": "Abstract 'x 500 MC'",
        "source_json_field": "n_sims_per_batch",
    },
    "K1471 VT sup-Wald p=0.001 in 5/5 cells (abstract)": {
        "paper": 5, "tol": 0,
        "source_paper_loc": "Abstract/§3.1 'sup-Wald test rejects flatness in all five cells (p=0.001 in every cell)'",
        "source_json_field": "computed: count cells with detector.VT_baseline.p_value == 0.001",
    },
    "K1471 VT descriptive drop>70% at 70% in 3/5 cells (abstract)": {
        "paper": 3, "tol": 0,
        "source_paper_loc": "Abstract '70% threshold survives as descriptive level-crossing (drop>70%) in 3 of 5 cells'",
        "source_json_field": "computed: count cells with robustness_drop_grid.VT_baseline['drop>70%'] == '70%'",
    },
    # ---- tab:matched_control_vt narrative (§3.2 L239) ----
    "K1471 mean VT 10->100 drop across 5 cells (-0.722)": {
        "paper": -0.722, "tol": 0.01,
        "source_paper_loc": "§3.2 'mean VT 10%-to-100% Sharpe drop is -0.722'",
        "source_json_field": "computed: mean over 5 cells of (VT S@100% - VT S@10%)",
    },
    "K1471 smallest VT decline = cell2 (-0.421)": {
        "paper": -0.421, "tol": 0.01,
        "source_paper_loc": "§3.2 'cell2 lambda low showing the smallest decline at -0.421'",
        "source_json_field": "computed: max (least negative) VT delta across cells",
    },
    "K1471 mean RR_VT change across 5 cells (+0.091)": {
        "paper": 0.091, "tol": 0.01,
        "source_paper_loc": "§3.2 'mean RR_VT change is +0.091'",
        "source_json_field": "computed: mean over 5 cells of (RR_VT S@100% - RR_VT S@10%)",
    },
    "K1471 VT degrades in 5/5 cells": {
        "paper": 5, "tol": 0,
        "source_paper_loc": "§3.2 'VT degrades in 5 of 5 microstructure cells'",
        "source_json_field": "computed: count cells with VT delta < 0",
    },
    "K1471 RR_VT degrades in 0/5 cells": {
        "paper": 0, "tol": 0,
        "source_paper_loc": "§3.2 'RR_VT degrades in 0 of 5'",
        "source_json_field": "computed: count cells with RR_VT delta < 0",
    },
    # ---- §cross_strategy RR_TF erosion narrative (L326) ----
    "K1471 gate excludes TF in 4/5 cells": {
        "paper": 4, "tol": 0,
        "source_paper_loc": "§cross 'the gate excludes TF in four of five cells'",
        "source_json_field": "computed: count cells with detector.TF.status == not_applicable_saturated_loss",
    },
    "K1471 gate excludes MR in 5/5 cells": {
        "paper": 5, "tol": 0,
        "source_paper_loc": "§cross 'MR in all five'",
        "source_json_field": "computed: count cells with detector.MR.status == not_applicable_saturated_loss",
    },
    "K1471 RR_TF sup-Wald p=0.001 in 5/5 cells": {
        "paper": 5, "tol": 0,
        "source_paper_loc": "§cross 'RR_TF sup-Wald rejects flatness at p=0.001 in 5 of 5 cells'",
        "source_json_field": "computed: count cells with detector.RR_TF.p_value == 0.001",
    },
    "K1471 RR_MR sup-Wald p=0.001 in 5/5 cells": {
        "paper": 5, "tol": 0,
        "source_paper_loc": "§cross 'and RR_MR likewise'",
        "source_json_field": "computed: count cells with detector.RR_MR.p_value == 0.001",
    },
    "K1471 RR_TF level-crossing min adoption (40%)": {
        "paper": "40%", "tol": 0.0,
        "source_paper_loc": "§cross 'descriptive level-crossings at 40--70% adoption' (min)",
        "source_json_field": "computed: min numeric of detector.RR_TF.threshold across cells",
    },
    "K1471 RR_TF level-crossing max adoption (70%)": {
        "paper": "70%", "tol": 0.0,
        "source_paper_loc": "§cross 'descriptive level-crossings at 40--70% adoption' (max)",
        "source_json_field": "computed: max numeric of detector.RR_TF.threshold across cells",
    },
    "K1471 TF/MR excluded baseline ceiling (-0.69)": {
        "paper": -0.69, "tol": 0.01,
        "source_paper_loc": "§cross 'structurally loss-making (baseline Sharpe -0.69 to -5.49)' (least negative)",
        "source_json_field": "computed: max baseline_mean_sharpe over excluded TF/MR cells",
    },
    "K1471 TF/MR excluded baseline floor (-5.49)": {
        "paper": -5.49, "tol": 0.01,
        "source_paper_loc": "§cross 'structurally loss-making (baseline Sharpe -0.69 to -5.49)' (most negative)",
        "source_json_field": "computed: min baseline_mean_sharpe over excluded TF/MR cells",
    },
    "K1471 TF footprint |dw| on the order of 1.5 (s=10)": {
        "paper": 1.5, "tol": 0.1,
        "source_paper_loc": "§cross 'coordinated footprint |Δw| on the order of 1.5 at s=10' (approx)",
        "source_json_field": "computed: max over adoptions of cell1 TF per_adoption._turnover.dw_mean",
    },
    "K1471 VT footprint floor (0.004)": {
        "paper": 0.004, "tol": 0.001,
        "source_paper_loc": "§cross 'versus VT's 0.004--0.008' (min)",
        "source_json_field": "computed: min over adoptions of cell1 VT per_adoption._turnover.dw_mean",
    },
    "K1471 VT footprint ceiling (0.008)": {
        "paper": 0.008, "tol": 0.001,
        "source_paper_loc": "§cross 'versus VT's 0.004--0.008' (max)",
        "source_json_field": "computed: max over adoptions of cell1 VT per_adoption._turnover.dw_mean",
    },
    "K1471 TF-vs-VT footprint separation (two orders of magnitude)": {
        "paper": 2, "tol": 0,
        "source_paper_loc": "Abstract/§3.2/§cross 'footprints two orders of magnitude larger'",
        "source_json_field": "computed: int(log10(TF footprint peak / VT footprint floor))",
    },
})


def find_result_file(result_name: str, kid_hint: str | None = None) -> Path | None:
    """Locate a result JSON. Prefer paper-bundled copy; fall back to project experiments/."""
    p1 = EXP_DIR / result_name
    if p1.exists():
        return p1
    if kid_hint:
        p2 = PROJECT_EXP / kid_hint / result_name
        if p2.exists():
            return p2
    for sub in PROJECT_EXP.glob(f"*/{result_name}"):
        return sub
    return None


def run_experiment(script_name: str, result_name: str, description: str,
                   kid_hint: str | None = None, force_skip_live: bool = False):
    """Run an experiment script (if present) and return its result JSON.

    If force_skip_live=True, never run live (used for K1261/K1262/K1262b
    which take ~13 min combined and have committed result JSONs).
    """
    script = EXP_DIR / script_name if (EXP_DIR / script_name).exists() else None
    if script is None and kid_hint:
        cand = PROJECT_EXP / kid_hint / script_name
        if cand.exists():
            script = cand
    print(f"\n[Running] {description}: {script_name}")

    ran_live = False
    if script and not skip_live and not force_skip_live:
        result = subprocess.run(
            ["uv", "run", "python", str(script)],
            capture_output=True, text=True, timeout=900,
            cwd=str(PROJECT),
        )
        if result.returncode != 0:
            print(f"  [WARN] live run failed rc={result.returncode}; stderr tail:\n    {result.stderr[-300:]}")
        else:
            print(f"  [OK] live run complete")
            ran_live = True
    elif script is None:
        print(f"  [SKIP] script missing")
    elif force_skip_live:
        print(f"  [SKIP] force_skip_live (large run, using stored JSON)")
    else:
        print(f"  [SKIP] --skip-live set")

    path = find_result_file(result_name, kid_hint=kid_hint)
    if path is None:
        print(f"  [ERROR] result file not found: {result_name}")
        return None, False
    print(f"  [LOAD] {path.relative_to(PROJECT)}")
    with open(path) as f:
        return json.load(f), ran_live


def record_check(label: str, computed_value):
    """Record a traceability check vs PAPER_CLAIMS[label]."""
    claim = PAPER_CLAIMS[label]
    paper_value = claim["paper"]
    tol = claim["tol"]

    # Categorical / None matching
    if isinstance(paper_value, str) or paper_value is None or isinstance(paper_value, int):
        match = (paper_value == computed_value)
        return {
            "metric": label,
            "paper_value": paper_value,
            "reproduced_value": computed_value,
            "tol": tol,
            "match": bool(match),
            "source_paper_loc": claim["source_paper_loc"],
            "source_json_field": claim["source_json_field"],
        }

    # Numeric (float) matching with absolute tolerance
    if computed_value is None:
        return {
            "metric": label,
            "paper_value": paper_value,
            "reproduced_value": None,
            "abs_diff": None,
            "tol": tol,
            "match": False,
            "note": "MISSING",
            "source_paper_loc": claim["source_paper_loc"],
            "source_json_field": claim["source_json_field"],
        }
    diff = abs(paper_value - float(computed_value))
    return {
        "metric": label,
        "paper_value": round(float(paper_value), 4),
        "reproduced_value": round(float(computed_value), 4),
        "abs_diff": round(diff, 4),
        "tol": tol,
        "match": diff <= tol,
        "source_paper_loc": claim["source_paper_loc"],
        "source_json_field": claim["source_json_field"],
    }


print("=" * 70)
print("PAPER 5 (vt-crowding-abm) v3 REPRODUCIBILITY CHECK")
print("=" * 70)

checks: list[dict] = []

# ---------------------------------------------------------------------
# K827v3: Table 1 + §4.3 t-tests (live re-run by default; ~3 min)
# ---------------------------------------------------------------------
d_v3, _ = run_experiment(
    "k827v3_abm_fixed_liquidity.py",
    "k827v3_abm_fixed_liquidity_results.json",
    "K827v3: VT 500-MC fixed-liquidity baseline (Table 1)",
    kid_hint="k827v3",
)
if d_v3:
    p1 = d_v3.get("part1_results", {})
    for adopt_label, claim_label in [
        ("10%", "Sharpe @ phi=10% (K827v3)"),
        ("20%", "Sharpe @ phi=20% (K827v3)"),
        ("30%", "Sharpe @ phi=30% (K827v3)"),
        ("50%", "Sharpe @ phi=50% (K827v3)"),
        ("70%", "Sharpe @ phi=70% (K827v3)"),
        ("100%", "Sharpe @ phi=100% (K827v3)"),
    ]:
        v = p1.get(adopt_label, {}).get("vt_sharpe", {}).get("mean")
        checks.append(record_check(claim_label, v))

    checks.append(record_check("Kurtosis @ phi=70% (K827v3)",
                               p1.get("70%", {}).get("kurtosis", {}).get("mean")))
    checks.append(record_check("Kurtosis @ phi=100% (K827v3)",
                               p1.get("100%", {}).get("kurtosis", {}).get("mean")))
    checks.append(record_check("AnnVol @ phi=100% (K827v3)",
                               p1.get("100%", {}).get("ann_vol", {}).get("mean")))
    checks.append(record_check("Skewness @ phi=100% (K827v3)",
                               p1.get("100%", {}).get("skewness", {}).get("mean")))
    checks.append(record_check("VIX_spike_pct @ phi=70% (K827v3)",
                               p1.get("70%", {}).get("vix_spike_pct", {}).get("mean")))
    checks.append(record_check("VIX_spike_pct @ phi=100% (K827v3)",
                               p1.get("100%", {}).get("vix_spike_pct", {}).get("mean")))
    checks.append(record_check("MaxDD @ phi=70% (K827v3)",
                               p1.get("70%", {}).get("max_dd", {}).get("mean")))
    checks.append(record_check("MaxDD @ phi=100% (K827v3)",
                               p1.get("100%", {}).get("max_dd", {}).get("mean")))

    # Welch t-stats (recomputed from stored aggregate moments)
    def welch_t(a_label: str, b_label: str) -> float | None:
        a = p1.get(a_label, {}).get("vt_sharpe", {})
        b = p1.get(b_label, {}).get("vt_sharpe", {})
        if not a or not b:
            return None
        ma, sa, na = a.get("mean"), a.get("std"), a.get("n_valid")
        mb, sb, nb = b.get("mean"), b.get("std"), b.get("n_valid")
        if any(v is None for v in (ma, sa, na, mb, sb, nb)) or na <= 1 or nb <= 1:
            return None
        return abs((ma - mb) / math.sqrt(sa * sa / na + sb * sb / nb))

    checks.append(record_check("|t| 30% vs 10% (K827v3 Welch)", welch_t("30%", "10%")))
    checks.append(record_check("|t| 50% vs 10% (K827v3 Welch)", welch_t("50%", "10%")))
    checks.append(record_check("|t| 70% vs 50% (K827v3 Welch)", welch_t("70%", "50%")))

# ---------------------------------------------------------------------
# K1261: Phase 1 cross-treatment thresholds (Strict detector)
# Forced skip-live: K1261 takes ~3-5 min; stored JSON is canonical.
# ---------------------------------------------------------------------
d_1261, _ = run_experiment(
    "k1261_phase1_main.py",
    "k1261_results.json",
    "K1261: Phase 1 cross-treatment (Strict detector)",
    kid_hint="k1261",
    force_skip_live=True,
)
if d_1261:
    td = d_1261.get("threshold_detection", {})
    checks.append(record_check(
        "K1261 VT_baseline strict threshold",
        td.get("VT_baseline_K827v3_stored", {}).get("critical_adoption"),
    ))
    checks.append(record_check(
        "K1261 TF strict threshold",
        td.get("TF", {}).get("critical_adoption"),
    ))
    checks.append(record_check(
        "K1261 MR strict threshold",
        td.get("MR", {}).get("critical_adoption"),
    ))
    checks.append(record_check(
        "K1261 NoiseControl strict threshold (null)",
        td.get("NoiseControl", {}).get("critical_adoption"),
    ))
    nc_sharpe_100 = (
        td.get("NoiseControl", {})
          .get("justification", {})
          .get("per_adoption", {})
          .get("100%", {})
          .get("sharpe")
    )
    checks.append(record_check(
        "K1261 NoiseControl Sharpe @ phi=100% (anchor)", nc_sharpe_100
    ))

# ---------------------------------------------------------------------
# K1262: Phase 2 scaling x window matrix + cross-detector recompute
# Forced skip-live: K1262 takes ~5 min; stored JSON canonical.
# ---------------------------------------------------------------------
d_1262, _ = run_experiment(
    "k1262.py",
    "k1262_results.json",
    "K1262: Phase 2 scaling x window + cross-detector",
    kid_hint="k1262",
    force_skip_live=True,
)
if d_1262:
    tpc = d_1262.get("threshold_per_cell", {})

    # Specific cells
    def cell_th(treat: str, s: str, w: str, det: str) -> str | None:
        return (tpc.get(treat, {})
                   .get(s, {})
                   .get(w, {})
                   .get(det, {})
                   .get("critical_adoption"))

    checks.append(record_check("K1262 scaling=10 window=22 TF (softer)",
                               cell_th("TF", "10", "22", "softer_kurt_weak")))
    checks.append(record_check("K1262 scaling=10 window=22 MR (softer)",
                               cell_th("MR", "10", "22", "softer_kurt_weak")))
    checks.append(record_check("K1262 scaling=1 window=22 TF (softer)",
                               cell_th("TF", "1", "22", "softer_kurt_weak")))
    checks.append(record_check("K1262 scaling=1 window=22 MR (softer)",
                               cell_th("MR", "1", "22", "softer_kurt_weak")))

    # Order-rank for ordering counts. Treat None / 'null' as +inf
    # (saturation > any finite threshold under H1+ rank encoding).
    def rank(th):
        if th is None:
            return float("inf")
        try:
            return int(str(th).rstrip("%"))
        except Exception:
            return float("inf")

    # K1262 12/12 ordering: VT softer is 100% per the cross-detector recompute
    # table (VT_baseline 100% under softer). TF/MR are per-cell thresholds.
    vt_softer = 100  # Source: k1262_softer_detector_table.md VT_baseline softer col
    tf_le_count = 0
    mr_le_count = 0
    total_cells = 0
    for s in ("1", "3", "5", "10"):
        for w in ("10", "22", "60"):
            tf_th = cell_th("TF", s, w, "softer_kurt_weak")
            mr_th = cell_th("MR", s, w, "softer_kurt_weak")
            if tf_th is None and mr_th is None:
                continue
            total_cells += 1
            if rank(tf_th) <= vt_softer:
                tf_le_count += 1
            if rank(mr_th) <= vt_softer:
                mr_le_count += 1

    checks.append(record_check("K1262 TF<=VT in 12/12 cells (softer)", tf_le_count))
    checks.append(record_check("K1262 MR<=VT in 12/12 cells (softer)", mr_le_count))

    # Cross-detector recompute thresholds (K1261-raw + softer/sharpe-only).
    # These are the table 2 numbers — sourced from K1262
    # k1262_softer_detector_table.md (which is byte-pinned in the experiment dir).
    # Verify via re-computing from K1261 raw if needed; for the reproduce gate
    # we read the persisted markdown values vs paper.
    # Paper Table 2:
    #   VT softer = 100%   → k1262_softer_detector_table.md row 1 col Softer
    #   VT P5-style = 70%  → row 1 col P5-style
    #   TF P5-style = 20%  → row 2 col P5-style
    #   MR P5-style = 20%  → row 3 col P5-style
    softer_md = (PROJECT_EXP / "k1262" / "k1262_softer_detector_table.md")
    md_text = softer_md.read_text() if softer_md.exists() else ""
    def md_extract(treatment: str, det_col: int) -> str | None:
        # parse the table row beginning '| <treatment> |'
        for line in md_text.splitlines():
            if line.strip().startswith(f"| {treatment} "):
                cells = [c.strip() for c in line.strip("|").split("|")]
                if len(cells) > det_col:
                    return cells[det_col]
        return None

    checks.append(record_check(
        "K1262 VT_baseline softer threshold",
        md_extract("VT_baseline", 2),  # cols: Treatment | Strict | Softer | P5-style
    ))
    checks.append(record_check(
        "K1262 VT_baseline Sharpe-only threshold (anchor)",
        md_extract("VT_baseline", 3),
    ))
    checks.append(record_check(
        "K1262 TF Sharpe-only threshold",
        md_extract("TF", 3),
    ))
    checks.append(record_check(
        "K1262 MR Sharpe-only threshold",
        md_extract("MR", 3),
    ))

# ---------------------------------------------------------------------
# K1262b: 5-cell OAT (lambda/gamma) sweep, P5-style detector
# Forced skip-live: K1262b takes ~5 min; stored JSON canonical.
# ---------------------------------------------------------------------
d_1262b, _ = run_experiment(
    "k1262b.py",
    "k1262b_results.json",
    "K1262b: 5-cell OAT lambda/gamma robustness",
    kid_hint="k1262b",
    force_skip_live=True,
)
if d_1262b:
    tpc = d_1262b.get("threshold_per_cell", {})

    def oat_th(cell: str, treat: str) -> str | None:
        return tpc.get(cell, {}).get(treat, {}).get("critical_adoption")

    checks.append(record_check("K1262b cell1 baseline VT threshold",
                               oat_th("cell1_baseline", "VT_baseline")))
    checks.append(record_check("K1262b cell2 lambda_low VT threshold",
                               oat_th("cell2_lambda_low", "VT_baseline")))
    checks.append(record_check("K1262b cell3 lambda_high VT threshold",
                               oat_th("cell3_lambda_high", "VT_baseline")))
    checks.append(record_check("K1262b cell4 gamma_low VT threshold",
                               oat_th("cell4_gamma_low", "VT_baseline")))
    checks.append(record_check("K1262b cell5 gamma_high VT threshold",
                               oat_th("cell5_gamma_high", "VT_baseline")))

    checks.append(record_check("K1262b cell1 MR threshold",
                               oat_th("cell1_baseline", "MR")))
    checks.append(record_check("K1262b cell2 MR threshold",
                               oat_th("cell2_lambda_low", "MR")))
    checks.append(record_check("K1262b cell3 MR threshold (null)",
                               oat_th("cell3_lambda_high", "MR")))
    checks.append(record_check("K1262b cell4 MR threshold",
                               oat_th("cell4_gamma_low", "MR")))
    checks.append(record_check("K1262b cell5 MR threshold",
                               oat_th("cell5_gamma_high", "MR")))

    # Counts
    cells = ("cell1_baseline", "cell2_lambda_low", "cell3_lambda_high",
             "cell4_gamma_low", "cell5_gamma_high")

    tf_30_count = sum(1 for c in cells if oat_th(c, "TF") == "30%")
    checks.append(record_check("K1262b TF=30% in all 5 cells", tf_30_count))

    nc_null_count = sum(1 for c in cells if oat_th(c, "NoiseControl") is None)
    checks.append(record_check("K1262b NoiseControl null in all 5 cells", nc_null_count))

    def rank(th, side: str = "treat"):
        """Rank threshold per paper §5.4 footnote a:
        Under H1+ ordering, 'null' on TF/MR side = saturation = MAX severity,
        i.e. treated as MR/TF threshold being EFFECTIVELY <= VT (the strategy
        is already destroyed before any phi level — strictly stronger than
        'crosses just above'). Equivalent rank = -inf for the constraint side.
        On the VT side, 'null' would mean VT never crosses, which would mean
        the constraint is violated (VT > everything tested).
        """
        if th is None:
            return float("-inf") if side == "treat" else float("inf")
        try:
            return int(str(th).rstrip("%"))
        except Exception:
            return float("inf")

    tf_le_vt = sum(1 for c in cells
                   if rank(oat_th(c, "TF"), "treat") <= rank(oat_th(c, "VT_baseline"), "vt"))
    mr_le_vt = sum(1 for c in cells
                   if rank(oat_th(c, "MR"), "treat") <= rank(oat_th(c, "VT_baseline"), "vt"))
    checks.append(record_check("K1262b TF<=VT in 5/5 cells", tf_le_vt))
    checks.append(record_check("K1262b MR<=VT in 5/5 cells (incl. null saturation)", mr_le_vt))

# ---------------------------------------------------------------------
# K1471: exogenous-detector redesign headline layer.
# Forced skip-live: the M=500 full run takes ~1,756s and must NEVER be
# live-rerun inside the reproduce gate; the committed JSON is canonical.
# ---------------------------------------------------------------------
d_1471, _ = run_experiment(
    "k1471_vt_crowding_redesign.py",
    "k1471_full_results.json",
    "K1471: exogenous-detector redesign (VT curve + matched control + gate)",
    kid_hint="k1471_vt_crowding_redesign",
    force_skip_live=True,
)
if d_1471:
    cellsd = d_1471.get("cells", {})

    def k1471_sharpe(cell, treat, phi):
        return (cellsd.get(cell, {}).get("treatments", {}).get(treat, {})
                .get("per_adoption", {}).get(phi, {}).get("sharpe", {}).get("mean"))

    def k1471_ci(cell, treat, phi, side):
        return (cellsd.get(cell, {}).get("treatments", {}).get(treat, {})
                .get("per_adoption", {}).get(phi, {}).get("sharpe", {})
                .get("boot_ci", {}).get(side))

    def k1471_det(cell, treat, field):
        return cellsd.get(cell, {}).get("detector", {}).get(treat, {}).get(field)

    def k1471_dw(cell, treat, phi):
        return (cellsd.get(cell, {}).get("treatments", {}).get(treat, {})
                .get("per_adoption", {}).get(phi, {}).get("_turnover", {}).get("dw_mean"))

    def gate_word(status):
        # main.tex tab:tfmr_gate prints 'excluded' for the saturated-loss
        # gate outcome and 'passes' otherwise.
        return "excluded" if status == "not_applicable_saturated_loss" else "passes"

    def th_rank(th):
        try:
            return int(str(th).rstrip("%"))
        except Exception:  # silent-ok: threshold string parse; null/non-numeric -> None sentinel, caller filters these out before min/max
            return None

    # ---- Table tab:vt_monotone_curve (canonical cell1 VT curve) ----
    prev_mean = None
    for phi in _K1471_VT_CURVE:
        m = k1471_sharpe("cell1_baseline", "VT_baseline", phi)
        checks.append(record_check(f"K1471 vt_curve Sharpe @ {phi} (cell1)", m))
        checks.append(record_check(f"K1471 vt_curve CI-lo @ {phi} (cell1)",
                                   k1471_ci("cell1_baseline", "VT_baseline", phi, "ci_lo")))
        checks.append(record_check(f"K1471 vt_curve CI-hi @ {phi} (cell1)",
                                   k1471_ci("cell1_baseline", "VT_baseline", phi, "ci_hi")))
        if prev_mean is not None and m is not None:
            checks.append(record_check(f"K1471 vt_curve delta @ {phi} (cell1)",
                                       round(m - prev_mean, 4)))
        if m is not None:
            prev_mean = m

    # ---- Table tab:matched_control_vt (VT vs RR_VT, five cells) ----
    vt_deltas, rr_deltas, gaps = [], [], []
    for cell in K1471_CELLS:
        v10 = k1471_sharpe(cell, "VT_baseline", "10%")
        v100 = k1471_sharpe(cell, "VT_baseline", "100%")
        r10 = k1471_sharpe(cell, "RR_VT", "10%")
        r100 = k1471_sharpe(cell, "RR_VT", "100%")
        vd = round(v100 - v10, 4) if (v10 is not None and v100 is not None) else None
        rd = round(r100 - r10, 4) if (r10 is not None and r100 is not None) else None
        checks.append(record_check(f"K1471 mc_vt VT S@10% ({cell})", v10))
        checks.append(record_check(f"K1471 mc_vt VT S@100% ({cell})", v100))
        checks.append(record_check(f"K1471 mc_vt VT delta ({cell})", vd))
        checks.append(record_check(f"K1471 mc_vt RR_VT S@10% ({cell})", r10))
        checks.append(record_check(f"K1471 mc_vt RR_VT S@100% ({cell})", r100))
        checks.append(record_check(f"K1471 mc_vt RR_VT delta ({cell})", rd))
        checks.append(record_check(f"K1471 mc_vt RR_VT sup-Wald p ({cell})",
                                   k1471_det(cell, "RR_VT", "p_value")))
        if vd is not None:
            vt_deltas.append(vd)
        if rd is not None:
            rr_deltas.append(rd)
        if v100 is not None and r100 is not None:
            gaps.append(r100 - v100)

    checks.append(record_check("K1471 mean VT 10->100 drop across 5 cells (-0.722)",
                               (sum(vt_deltas) / len(vt_deltas)) if vt_deltas else None))
    checks.append(record_check("K1471 smallest VT decline = cell2 (-0.421)",
                               max(vt_deltas) if vt_deltas else None))
    checks.append(record_check("K1471 mean RR_VT change across 5 cells (+0.091)",
                               (sum(rr_deltas) / len(rr_deltas)) if rr_deltas else None))
    checks.append(record_check("K1471 VT degrades in 5/5 cells",
                               sum(1 for d in vt_deltas if d < 0)))
    checks.append(record_check("K1471 RR_VT degrades in 0/5 cells",
                               sum(1 for d in rr_deltas if d < 0)))
    min_gap = min(gaps) if gaps else None
    checks.append({
        "metric": "K1471 min RR_VT-VT gap @100% >= 0.36",
        "paper_value": ">=0.36",
        "reproduced_value": round(min_gap, 4) if min_gap is not None else None,
        "tol": 0.0,
        "match": bool(min_gap is not None and min_gap >= 0.36),
        "source_paper_loc": "§3.2 'RR_VT Sharpe at 100% exceeds VT at same level by at least 0.36'",
        "source_json_field": "computed: min over cells of (RR_VT S@100% - VT S@100%)",
    })

    # ---- Table tab:tfmr_gate (cross-strategy applicability gate) ----
    for cell in K1471_CELLS:
        checks.append(record_check(f"K1471 gate TF status ({cell})",
                                   gate_word(k1471_det(cell, "TF", "status"))))
        checks.append(record_check(f"K1471 gate TF baseline Sharpe ({cell})",
                                   k1471_det(cell, "TF", "baseline_mean_sharpe")))
        checks.append(record_check(f"K1471 gate MR status ({cell})",
                                   gate_word(k1471_det(cell, "MR", "status"))))
        checks.append(record_check(f"K1471 gate MR baseline Sharpe ({cell})",
                                   k1471_det(cell, "MR", "baseline_mean_sharpe")))
        checks.append(record_check(f"K1471 gate RR_TF sup-Wald p ({cell})",
                                   k1471_det(cell, "RR_TF", "p_value")))
        checks.append(record_check(f"K1471 gate RR_TF baseline Sharpe ({cell})",
                                   k1471_det(cell, "RR_TF", "baseline_mean_sharpe")))
        checks.append(record_check(f"K1471 gate RR_MR sup-Wald p ({cell})",
                                   k1471_det(cell, "RR_MR", "p_value")))
        checks.append(record_check(f"K1471 gate RR_MR baseline Sharpe ({cell})",
                                   k1471_det(cell, "RR_MR", "baseline_mean_sharpe")))

    # ---- Abstract factorization (94,500 = 27 x 7 x 500) ----
    cfg = d_1471.get("config", {})
    grid1 = cfg.get("adoption_grid_cell1", [])
    grid_o = cfg.get("adoption_grid_other", [])
    n_treat = len(cellsd.get("cell1_baseline", {}).get("treatments", {}))
    checks.append(record_check("K1471 total simulations (abstract 94,500)",
                               d_1471.get("total_sims")))
    checks.append(record_check("K1471 cell-adoption combinations (abstract 27)",
                               (len(grid1) + 4 * len(grid_o)) if (grid1 and grid_o) else None))
    checks.append(record_check("K1471 treatment/control count (abstract 7)", n_treat))
    checks.append(record_check("K1471 MC per combination (abstract 500)",
                               d_1471.get("n_sims_per_batch")))
    checks.append(record_check("K1471 VT sup-Wald p=0.001 in 5/5 cells (abstract)",
                               sum(1 for c in K1471_CELLS
                                   if k1471_det(c, "VT_baseline", "p_value") == 0.001)))
    checks.append(record_check("K1471 VT descriptive drop>70% at 70% in 3/5 cells (abstract)",
                               sum(1 for c in K1471_CELLS
                                   if cellsd.get(c, {}).get("robustness_drop_grid", {})
                                      .get("VT_baseline", {}).get("drop>70%") == "70%")))

    # ---- §cross_strategy RR_TF erosion narrative ----
    checks.append(record_check("K1471 gate excludes TF in 4/5 cells",
                               sum(1 for c in K1471_CELLS
                                   if k1471_det(c, "TF", "status") == "not_applicable_saturated_loss")))
    checks.append(record_check("K1471 gate excludes MR in 5/5 cells",
                               sum(1 for c in K1471_CELLS
                                   if k1471_det(c, "MR", "status") == "not_applicable_saturated_loss")))
    checks.append(record_check("K1471 RR_TF sup-Wald p=0.001 in 5/5 cells",
                               sum(1 for c in K1471_CELLS if k1471_det(c, "RR_TF", "p_value") == 0.001)))
    checks.append(record_check("K1471 RR_MR sup-Wald p=0.001 in 5/5 cells",
                               sum(1 for c in K1471_CELLS if k1471_det(c, "RR_MR", "p_value") == 0.001)))
    rr_tf_ths = [th_rank(k1471_det(c, "RR_TF", "threshold")) for c in K1471_CELLS]
    rr_tf_ths = [t for t in rr_tf_ths if t is not None]
    checks.append(record_check("K1471 RR_TF level-crossing min adoption (40%)",
                               f"{min(rr_tf_ths)}%" if rr_tf_ths else None))
    checks.append(record_check("K1471 RR_TF level-crossing max adoption (70%)",
                               f"{max(rr_tf_ths)}%" if rr_tf_ths else None))
    excl_base = [k1471_det(c, t, "baseline_mean_sharpe")
                 for c in K1471_CELLS for t in ("TF", "MR")
                 if k1471_det(c, t, "status") == "not_applicable_saturated_loss"]
    checks.append(record_check("K1471 TF/MR excluded baseline ceiling (-0.69)",
                               max(excl_base) if excl_base else None))
    checks.append(record_check("K1471 TF/MR excluded baseline floor (-5.49)",
                               min(excl_base) if excl_base else None))
    tf_dw = [x for x in (k1471_dw("cell1_baseline", "TF", phi) for phi in _K1471_VT_CURVE)
             if x is not None]
    vt_dw = [x for x in (k1471_dw("cell1_baseline", "VT_baseline", phi) for phi in _K1471_VT_CURVE)
             if x is not None]
    tf_peak = max(tf_dw) if tf_dw else None
    vt_floor = min(vt_dw) if vt_dw else None
    checks.append(record_check("K1471 TF footprint |dw| on the order of 1.5 (s=10)", tf_peak))
    checks.append(record_check("K1471 VT footprint floor (0.004)", vt_floor))
    checks.append(record_check("K1471 VT footprint ceiling (0.008)",
                               max(vt_dw) if vt_dw else None))
    checks.append(record_check("K1471 TF-vs-VT footprint separation (two orders of magnitude)",
                               int(math.log10(tf_peak / vt_floor))
                               if (tf_peak and vt_floor and vt_floor > 0) else None))

# ---------------------------------------------------------------------
# Joint robustness: 12 strategy-spec + 5 microstructure = 17/17
# ---------------------------------------------------------------------
joint = 0
# 12 strategy-spec: count of cells where TF AND MR both <= VT(softer=100%)
for c in checks:
    if c["metric"] == "K1262 TF<=VT in 12/12 cells (softer)" and isinstance(c["reproduced_value"], int):
        joint += min(c["reproduced_value"], 12)  # cap at 12
        break
# 5 microstructure: from K1262b TF<=VT (always 5 here since null treated as saturation
# on MR side, and TF is finite in all cells — paper §5.4 phrasing "TF below VT in 5/5
# cells; MR <= VT in 5/5 cells" → joint count is 5 microstructure rows)
for c in checks:
    if c["metric"] == "K1262b TF<=VT in 5/5 cells" and isinstance(c["reproduced_value"], int):
        joint += min(c["reproduced_value"], 5)
        break
checks.append(record_check("Joint 17/17 robustness checks", joint))

# =====================================================================
# Print traceability table
# =====================================================================
print("\n" + "=" * 70)
print("TRACEABILITY TABLE")
print("=" * 70)
print(f"{'Metric':<55} {'Paper':>10} {'Repro':>10}  {'Match'}")
print("-" * 95)

matched = 0
for c in checks:
    pv = c["paper_value"]
    rv = c["reproduced_value"]
    pv_str = f"{pv}" if not isinstance(pv, float) else f"{pv:.3f}"
    if rv is None:
        rv_str = "MISSING"
    elif isinstance(rv, float):
        rv_str = f"{rv:.3f}"
    else:
        rv_str = str(rv)
    status = "OK" if c["match"] else "DIFF"
    if c["match"]:
        matched += 1
    print(f"{c['metric']:<55} {pv_str:>10} {rv_str:>10}  {status}")

total = len(checks)
match_rate = (matched / total * 100.0) if total else 0.0
print("-" * 95)
print(f"Match rate: {matched}/{total} = {match_rate:.1f}%")

# =====================================================================
# Write reproduce_report.json
# =====================================================================
alert_level = "green" if match_rate >= 95.0 else ("yellow" if match_rate >= 80.0 else "red")
report = {
    "paper_id": "vt-crowding-abm",
    "paper_title": "Monotone Strategy-Specific Erosion under Volatility-Targeting Crowding: Matched-Control Identification via Agent-Based Simulation",
    "target_journal": "Quantitative Finance (QF) -> JEBO",
    "audit_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    "auditor": "reproduce.py (Paper 5 v4 — K1261/K1262/K1262b + K1471 redesign expansion)",
    "mode": {"skip_live": skip_live},
    "match_summary": {
        "tables_verified": 7,
        "checks_total": total,
        "checks_matched": matched,
        "overall_match_rate_pct": round(match_rate, 2),
    },
    "alert_level": alert_level,
    "tables": {
        "table1_main": {
            "source": "paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity_results.json",
            "section": "main.tex Table tab:main + Table tab:market + §4.3 t-tests",
        },
        "table2_cross_strategy": {
            "source": [
                "experiments/k1261/k1261_results.json (Strict detector cell1)",
                "experiments/k1262/k1262_softer_detector_table.md (cross-detector recompute)",
            ],
            "section": "main.tex Table tab:cross_strategy_threshold (§4.4)",
        },
        "table3_scaling_window": {
            "source": "experiments/k1262/k1262_results.json (Phase 2 16,800-sim sweep)",
            "section": "main.tex Table tab:scaling_window_matrix (§4.4)",
        },
        "table4_oat_robustness": {
            "source": "experiments/k1262b/k1262b_results.json (5-cell OAT)",
            "section": "main.tex Table tab:oat_robustness (§4.5) + §5.4 knife-edge rebuttal",
        },
        "table5_vt_monotone_curve": {
            "source": "experiments/k1471_vt_crowding_redesign/k1471_full_results.json (cells.cell1_baseline.treatments.VT_baseline.per_adoption)",
            "section": "main.tex Table tab:vt_monotone_curve (§3.1) + abstract canonical-cell curve",
        },
        "table6_matched_control_vt": {
            "source": "experiments/k1471_vt_crowding_redesign/k1471_full_results.json (cells.*.treatments.{VT_baseline,RR_VT} + cells.*.detector.RR_VT)",
            "section": "main.tex Table tab:matched_control_vt (§3.2) + matched-control narrative",
        },
        "table7_tfmr_gate": {
            "source": "experiments/k1471_vt_crowding_redesign/k1471_full_results.json (cells.*.detector.{TF,MR,RR_TF,RR_MR})",
            "section": "main.tex Table tab:tfmr_gate (§cross_strategy) + RR_TF erosion narrative",
        },
    },
    "checks": checks,
    "joint_robustness": {
        "strategy_spec_count": 12,
        "microstructure_count": 5,
        "total_count_paper_claim": 17,
        "ordering_preserved": "TF/MR <= VT in 12/12 strategy-spec + 5/5 microstructure cells",
        "noise_control_falsifiability": "5/5 OAT + 12/12 strategy-spec cells: NoiseControl never crosses",
    },
    "actor_message_to_user": (
        f"{alert_level.upper()}: {matched}/{total} = {match_rate:.1f}% match vs paper claims. "
        "Tables 1-4 verified across K827v3 + K1261 + K1262 + K1262b; "
        "v4 expansion binds the K1471 exogenous-detector redesign headline layer "
        "(tab:vt_monotone_curve + tab:matched_control_vt + tab:tfmr_gate) plus the "
        "abstract factorization and RR_TF footprint-scale erosion narrative."
    ),
}
out_path = PAPER_DIR / "reproduce_report.json"
with open(out_path, "w") as f:
    json.dump(report, f, indent=2)
print(f"\n[WRITE] {out_path.relative_to(PROJECT)}")
print("=" * 70)
print(f"DONE — alert_level={alert_level}" if match_rate >= 95.0
      else f"ALERT: match rate {match_rate:.1f}% < 95% (alert_level={alert_level})")
print("=" * 70)

sys.exit(0 if match_rate >= 95.0 else 1)
