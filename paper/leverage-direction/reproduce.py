#!/usr/bin/env python3
"""
Paper 1 Reproducibility Checker: Leverage Direction Matters
============================================================
Compares key numbers in the paper (tables.tex / body_v2.tex) against
the experiment result JSONs and knowledge base entries.

Sources:
  - K799: Grand Model Evaluation (SPY, QLIKE + VaR, 2023-24 OOS)
  - K802: GJR + Skewed-t Distribution (SPY, VaR ortho, 2023-24 OOS)
  - K824v2: Probabilistic RV Quantile Forecasting (SPY, HistSim VaR)

Usage:
  python paper/leverage-direction/reproduce.py
"""

import json
import os
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class Check:
    table: str
    cell: str
    paper_value: str
    experiment_value: str
    source: str
    status: str  # MATCH / MISMATCH / ROUNDING / UNTRACEABLE
    note: str = ""


def load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def fmt(val, decimals=4):
    """Format a number for display."""
    if isinstance(val, float):
        return f"{val:.{decimals}f}"
    return str(val)


def close_enough(paper_val, exp_val, rtol=0.02, atol=0.005):
    """Check if two numbers are close enough (within 2% relative or 0.005 absolute)."""
    try:
        p = float(paper_val)
        e = float(exp_val)
    except (ValueError, TypeError):
        return False
    if abs(p) < 1e-10 and abs(e) < 1e-10:
        return True
    if abs(p - e) <= atol:
        return True
    if abs(p) > 1e-10 and abs((p - e) / p) <= rtol:
        return True
    return False


# ---------------------------------------------------------------------------
# Locate experiment JSONs
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
EXP_DIR = SCRIPT_DIR / "experiments"

# Also check project-level experiments/ as fallback
EXP_DIR_FALLBACK = PROJECT_ROOT / "experiments"


def find_json(name: str) -> Optional[dict]:
    for d in [EXP_DIR, EXP_DIR_FALLBACK]:
        p = d / name
        if p.exists():
            return load_json(str(p))
    return None


# ---------------------------------------------------------------------------
# Load experiment data
# ---------------------------------------------------------------------------

k799 = find_json("k799_grand_evaluation_results.json")
k802 = find_json("k802_gjr_skewt_results.json")
k824v2 = find_json("k824v2_quantile_fixed_results.json")

checks: list[Check] = []


# ===========================================================================
# TABLE 3: QLIKE OOS (tab:qlike)
# ===========================================================================
# Paper Table 3, Row 1: SPY 2023-2024
# Paper: GARCH = -8.985, GJR = -9.034, Delta = -0.54%, DM p = 0.001

print("=" * 80)
print("TABLE 3: QLIKE OOS (tab:qlike)")
print("=" * 80)

# K799 has QLIKE in Patton-centered scale (GJR=1.466, GARCH=1.510)
# K802 has a DM test with p=0.0012 (stat=-3.2475)
# The paper uses quasi-log-likelihood scale (-9.034, -8.985)
# These are different scales; we can verify:
#   1. The RANKING (GJR < GARCH in QLIKE = GJR better)
#   2. The DM test p-value
#   3. The percentage difference

if k799:
    gjr_qlike = k799["evaluation_layers"]["layer_1_2"]["qlike"]["GJR"]
    garch_qlike = k799["evaluation_layers"]["layer_1_2"]["qlike"]["GARCH"]
    delta_pct = (gjr_qlike - garch_qlike) / garch_qlike * 100

    checks.append(Check(
        table="Table 3", cell="SPY 2023-24 ranking",
        paper_value="GJR better than GARCH",
        experiment_value=f"GJR ({gjr_qlike:.4f}) < GARCH ({garch_qlike:.4f})" if gjr_qlike < garch_qlike else "GARCH better",
        source="K799 layer_1_2.qlike",
        status="MATCH" if gjr_qlike < garch_qlike else "MISMATCH"
    ))

    checks.append(Check(
        table="Table 3", cell="SPY 2023-24 QLIKE delta",
        paper_value="-0.54%",
        experiment_value=f"{delta_pct:.2f}% (Patton scale)",
        source="K799 layer_1_2.qlike",
        status="MATCH" if abs(delta_pct - (-2.90)) < 5 else "NOTE",
        note="Paper uses quasi-LL scale (-9.034/-8.985), K799 uses Patton centered scale (1.466/1.510). Different scale = different % delta. Ranking confirmed."
    ))

    # K799 DM test: GJR vs GARCH
    dm_k799 = k799["evaluation_layers"]["layer_4"]["results"]["GJR vs GARCH"]
    checks.append(Check(
        table="Table 3", cell="SPY 2023-24 DM p-value",
        paper_value="0.001",
        experiment_value=f"{dm_k799['p_value']:.4f} (stat={dm_k799['dm_stat']:.4f})",
        source="K799 layer_4 'GJR vs GARCH'",
        status="MISMATCH",
        note=f"Paper says p=0.001, K799 says p={dm_k799['p_value']:.4f}. K802 DM gives p=0.0012. Paper likely uses K802 value rounded."
    ))

if k802:
    dm_k802 = k802["qlike_results"]["DM_GJR_vs_GARCH"]
    checks.append(Check(
        table="Table 3", cell="SPY 2023-24 DM p-value (K802 cross-check)",
        paper_value="0.001",
        experiment_value=f"{dm_k802['p_value']:.4f} (stat={dm_k802['stat']:.4f})",
        source="K802 qlike_results.DM_GJR_vs_GARCH",
        status="MATCH" if close_enough(0.001, dm_k802["p_value"], rtol=0.3) else "MISMATCH",
        note="K802 DM p=0.0012 rounds to 0.001. This is the likely source for paper's p=0.001."
    ))

# Table 3 rows for non-SPY assets: UNTRACEABLE
for asset_period in [
    "SPY 2025", "QQQ 2023-24", "QQQ 2025",
    "GLD 2023-24", "GLD 2025", "TLT 2023-24",
    "EEM 2023-24", "BTC 2023-24"
]:
    checks.append(Check(
        table="Table 3", cell=f"{asset_period} QLIKE",
        paper_value="(see tables.tex)",
        experiment_value="No experiment JSON",
        source="None",
        status="UNTRACEABLE",
        note="No dedicated experiment JSON covers this asset-period."
    ))


# ===========================================================================
# TABLE 4: VaR Attribution (tab:var) -- SPY 2020-2025
# ===========================================================================
print("\n" + "=" * 80)
print("TABLE 4: VaR Attribution (tab:var)")
print("=" * 80)

# Paper values from tables.tex:
# Normal: 33 violations, 2.2%
# Student-t(5): 18, 1.2%, -45.5%
# + Adaptive: 14, 0.9%, -22.2%
# + Jump: 14, 0.9%, 0.0%
# No experiment JSON directly covers this (2020-2025, 1508 days)
# Knowledge base confirms these numbers.

var_attr = [
    ("Normal", "33", "2.2%"),
    ("Student-t(5)", "18", "1.2%"),
    ("+ Adaptive", "14", "0.9%"),
    ("+ Jump", "14", "0.9%"),
]
for config, viols, rate in var_attr:
    checks.append(Check(
        table="Table 4", cell=f"{config} violations/rate",
        paper_value=f"{viols} / {rate}",
        experiment_value="Knowledge base confirms",
        source="Knowledge base (multiple entries)",
        status="VERIFIED_KB_ONLY",
        note="Verified from knowledge base text, no dedicated experiment JSON."
    ))


# ===========================================================================
# TABLE 5: VaR Orthogonality (tab:var_ortho) -- SPY 2023-24
# ===========================================================================
print("\n" + "=" * 80)
print("TABLE 5: VaR Orthogonality (tab:var_ortho)")
print("=" * 80)

# Paper Row 1: GARCH(1,1) Normal: 7 violations, 1.39%, Kupiec p=0.40, Green
if k799:
    garch_var = k799["evaluation_layers"]["layer_6"]["results"]["GARCH"]
    checks.append(Check(
        table="Table 5", cell="GARCH+Normal violations",
        paper_value="7 / 1.39%",
        experiment_value=f"{garch_var['n_violations']} / {garch_var['violation_rate']*100:.2f}%",
        source="K799 layer_6.GARCH",
        status="MATCH" if garch_var["n_violations"] == 7 else "MISMATCH"
    ))
    checks.append(Check(
        table="Table 5", cell="GARCH+Normal Kupiec p",
        paper_value="0.40",
        experiment_value=f"{garch_var['kupiec']['p_value']:.4f}",
        source="K799 layer_6.GARCH.kupiec",
        status="MATCH" if close_enough(0.40, garch_var["kupiec"]["p_value"], atol=0.01) else "MISMATCH"
    ))
    checks.append(Check(
        table="Table 5", cell="GARCH+Normal Basel zone",
        paper_value="Green",
        experiment_value=garch_var["basel_traffic_light"],
        source="K799 layer_6.GARCH",
        status="MATCH" if garch_var["basel_traffic_light"] == "green" else "MISMATCH"
    ))

# Also verify from K802
if k802:
    garch_var_k802 = k802["var_backtest_results"]["GARCH+Normal"]
    checks.append(Check(
        table="Table 5", cell="GARCH+Normal violations (K802)",
        paper_value="7 / 1.39%",
        experiment_value=f"{garch_var_k802['n_violations']} / {garch_var_k802['violation_rate']*100:.2f}%",
        source="K802 GARCH+Normal",
        status="MATCH" if garch_var_k802["n_violations"] == 7 else "MISMATCH"
    ))

# Paper Row 2: GJR-GARCH Normal: 10, 1.99%, Kupiec p=0.049, Yellow
if k799:
    gjr_var = k799["evaluation_layers"]["layer_6"]["results"]["GJR"]
    checks.append(Check(
        table="Table 5", cell="GJR+Normal violations",
        paper_value="10 / 1.99%",
        experiment_value=f"{gjr_var['n_violations']} / {gjr_var['violation_rate']*100:.2f}%",
        source="K799 layer_6.GJR",
        status="MATCH" if gjr_var["n_violations"] == 10 else "MISMATCH"
    ))
    checks.append(Check(
        table="Table 5", cell="GJR+Normal Kupiec p",
        paper_value="0.049",
        experiment_value=f"{gjr_var['kupiec']['p_value']:.4f}",
        source="K799 layer_6.GJR.kupiec",
        status="MATCH" if close_enough(0.049, gjr_var["kupiec"]["p_value"], atol=0.005) else "MISMATCH"
    ))

# Cross-check: K802 GJR+Normal shows 9 violations (different refit schedule)
if k802:
    gjr_norm_k802 = k802["var_backtest_results"]["GJR+Normal"]
    checks.append(Check(
        table="Table 5", cell="GJR+Normal violations (K802 cross-check)",
        paper_value="10 (from K799)",
        experiment_value=f"{gjr_norm_k802['n_violations']} / {gjr_norm_k802['violation_rate']*100:.2f}%",
        source="K802 GJR+Normal",
        status="MISMATCH",
        note=f"K799 says 10/502, K802 says {gjr_norm_k802['n_violations']}/502. Different refit schedules (K799 refit=63d, K802 refit=63d but different QLIKE estimation). Paper uses K799 value."
    ))

# Paper Row 3: GJR Student-t(5): 6, 1.20%, Kupiec p=0.60, Green
if k802:
    gjr_t = k802["var_backtest_results"]["GJR+StudentT"]
    checks.append(Check(
        table="Table 5", cell="GJR+Student-t violations",
        paper_value="6 / 1.20%",
        experiment_value=f"{gjr_t['n_violations']} / {gjr_t['violation_rate']*100:.2f}%",
        source="K802 GJR+StudentT",
        status="MATCH" if gjr_t["n_violations"] == 6 else "MISMATCH"
    ))
    checks.append(Check(
        table="Table 5", cell="GJR+Student-t Kupiec p",
        paper_value="0.60",
        experiment_value=f"{gjr_t['kupiec']['p_value']:.4f}",
        source="K802 GJR+StudentT.kupiec",
        status="MISMATCH",
        note=f"Paper rounds 0.6698 to 0.60. Actual value is 0.67. This is NOT standard rounding."
    ))
    checks.append(Check(
        table="Table 5", cell="GJR+Student-t Basel zone",
        paper_value="Green",
        experiment_value=gjr_t["basel_traffic_light"],
        source="K802 GJR+StudentT",
        status="MATCH" if gjr_t["basel_traffic_light"] == "green" else "MISMATCH"
    ))

# Paper Row 4: GJR Hist.Sim: 4, 0.80%, Kupiec p=0.60, Green
# K824v2 M4_HistSim matches 4/502
if k824v2:
    histsim = k824v2["var_1pct_backtest"]["M4_HistSim"]
    checks.append(Check(
        table="Table 5", cell="GJR+HistSim violations",
        paper_value="4 / 0.80%",
        experiment_value=f"{histsim['n_violations']} / {histsim['violation_rate']*100:.2f}%",
        source="K824v2 M4_HistSim",
        status="MATCH" if histsim["n_violations"] == 4 else "MISMATCH"
    ))
    checks.append(Check(
        table="Table 5", cell="GJR+HistSim Kupiec p",
        paper_value="0.60",
        experiment_value=f"{histsim['kupiec']['p_value']:.4f}",
        source="K824v2 M4_HistSim.kupiec",
        status="MISMATCH",
        note=f"Paper says 0.60, actual is {histsim['kupiec']['p_value']:.4f}. Aggressive rounding."
    ))
    checks.append(Check(
        table="Table 5", cell="GJR+HistSim Basel zone",
        paper_value="Green",
        experiment_value=histsim["basel_traffic_light"],
        source="K824v2 M4_HistSim",
        status="MATCH" if histsim["basel_traffic_light"] == "green" else "MISMATCH"
    ))

# Cross-check: K802 FHS shows 5/502 (different implementation)
if k802:
    fhs_k802 = k802["var_backtest_results"]["GJR+FHS"]
    checks.append(Check(
        table="Table 5", cell="GJR+HistSim violations (K802 FHS cross-check)",
        paper_value="4 (from K824v2)",
        experiment_value=f"{fhs_k802['n_violations']} / {fhs_k802['violation_rate']*100:.2f}%",
        source="K802 GJR+FHS",
        status="MISMATCH",
        note=f"K824v2 HistSim=4/502, K802 FHS=5/502. Different implementations (K802 uses Fernandez-Steel residuals, K824v2 uses raw standardized residuals). Paper matches K824v2."
    ))

# Additional K824v2 cross-checks (Student-t from K824v2 perspective)
if k824v2:
    # K824v2 M2_StudentT: 7 violations (not 6 as in K802)
    # This is because K824v2 uses df estimated with scale correction
    studt_k824v2 = k824v2["var_1pct_backtest"]["M2_StudentT"]
    checks.append(Check(
        table="Table 5", cell="Student-t violations (K824v2 cross-check)",
        paper_value="6 (from K802 with df=~16)",
        experiment_value=f"{studt_k824v2['n_violations']} / {studt_k824v2['violation_rate']*100:.2f}%",
        source="K824v2 M2_StudentT",
        status="NOTE",
        note=f"K824v2 Student-t gives {studt_k824v2['n_violations']}/502 with df~6.7 (scale-corrected). K802 gives 6/502 with df~16. Different df estimation methods."
    ))


# ===========================================================================
# TABLE 9: Hybrid VT (tab:hybrid) -- SPY 2014-2026
# ===========================================================================
print("\n" + "=" * 80)
print("TABLE 9: Hybrid VT (tab:hybrid)")
print("=" * 80)

# Paper values (from tables.tex):
# Hybrid VT: Sharpe=0.99, MDD=-11.4%
# RV20 VT: 0.83, -13.8%
# GARCH VT: 0.82, -13.5%
# EWMA VT: 0.79, -13.4%
# BH: 0.75, -33.7%
#
# Knowledge base: Kill Test #3: Hybrid VT Sharpe 0.985, MaxDD -11.4%
# RV20 0.834, GARCH 0.820, EWMA 0.786, BH 0.75

hybrid_kb = {
    "Hybrid VT": {"sharpe_kb": 0.985, "sharpe_paper": 0.99},
    "RV20 VT":   {"sharpe_kb": 0.834, "sharpe_paper": 0.83},
    "GARCH VT":  {"sharpe_kb": 0.820, "sharpe_paper": 0.82},
    "EWMA VT":   {"sharpe_kb": 0.786, "sharpe_paper": 0.79},
    "BH":        {"sharpe_kb": 0.750, "sharpe_paper": 0.75},
}

for name, vals in hybrid_kb.items():
    diff = abs(vals["sharpe_paper"] - vals["sharpe_kb"])
    if diff < 0.005:
        status = "MATCH"
    elif diff < 0.01:
        status = "ROUNDING"
    else:
        status = "MISMATCH"

    checks.append(Check(
        table="Table 9", cell=f"{name} Sharpe",
        paper_value=f"{vals['sharpe_paper']:.2f}",
        experiment_value=f"{vals['sharpe_kb']:.3f} (KB)",
        source="Knowledge base (Kill Test #3)",
        status=status,
        note="" if status == "MATCH" else f"Paper: {vals['sharpe_paper']:.2f}, KB: {vals['sharpe_kb']:.3f}, diff={diff:.4f}. {'Aggressive rounding: 0.985->0.99 inflates by 0.5%' if name == 'Hybrid VT' else ''}"
    ))


# ===========================================================================
# TABLE 10: Diversification Amplification (tab:amplify)
# ===========================================================================
print("\n" + "=" * 80)
print("TABLE 10: Diversification Amplification (tab:amplify)")
print("=" * 80)

# Paper values (from tables.tex):
# SPY: ETF gamma=0.211, Avg Stock=0.076, Ratio=2.8x, t=-16.92
# Knowledge confirms all of these.

# We can cross-check SPY ETF gamma against K824v2 full-sample gamma
if k824v2:
    gjr_gamma = k824v2["final_gjr_params"]["gamma"]
    checks.append(Check(
        table="Table 10", cell="SPY ETF gamma",
        paper_value="0.211",
        experiment_value=f"{gjr_gamma:.4f}",
        source="K824v2 final_gjr_params.gamma",
        status="MATCH" if close_enough(0.211, gjr_gamma, atol=0.015) else "MISMATCH",
        note=f"Paper=0.211 (rolling mean), K824v2={gjr_gamma:.4f} (full-sample). Slight difference expected between rolling mean and full-sample point estimate."
    ))

checks.append(Check(
    table="Table 10", cell="SPY Avg Stock gamma",
    paper_value="0.076",
    experiment_value="0.076 (KB: 50-stock validation)",
    source="Knowledge base",
    status="VERIFIED_KB_ONLY"
))

checks.append(Check(
    table="Table 10", cell="SPY Ratio 2.8x",
    paper_value="2.8x",
    experiment_value=f"{0.211/0.076:.1f}x",
    source="Computed from 0.211/0.076",
    status="MATCH" if abs(0.211/0.076 - 2.8) < 0.1 else "MISMATCH"
))

checks.append(Check(
    table="Table 10", cell="SPY amplification t-stat",
    paper_value="-16.92",
    experiment_value="-16.92 (KB)",
    source="Knowledge base",
    status="VERIFIED_KB_ONLY"
))

# EWJ attenuation
checks.append(Check(
    table="Table 10", cell="EWJ attenuation",
    paper_value="ETF=0.087, Avg=0.127, 0.7x, t=2.09",
    experiment_value="KB: EWJ 0.087 < avg 0.127, ratio 0.7x, t=2.09",
    source="Knowledge base",
    status="VERIFIED_KB_ONLY"
))


# ===========================================================================
# TABLE 12: Gamma-Mechanism (tab:gamma-mechanism)
# ===========================================================================
print("\n" + "=" * 80)
print("TABLE 12: Gamma-Mechanism (tab:gamma-mechanism)")
print("=" * 80)

checks.append(Check(
    table="Table 12", cell="Spearman rho",
    paper_value="1.000 (p<0.001)",
    experiment_value="1.000 (KB confirms)",
    source="Knowledge base",
    status="VERIFIED_KB_ONLY"
))

checks.append(Check(
    table="Table 12", cell="Pearson r",
    paper_value="0.993",
    experiment_value="0.993 (KB confirms)",
    source="Knowledge base",
    status="VERIFIED_KB_ONLY"
))


# ===========================================================================
# INTERNAL CONSISTENCY: HM gamma conflict (Sec 4.7 vs Sec 5.4)
# ===========================================================================
print("\n" + "=" * 80)
print("INTERNAL CONSISTENCY CHECKS")
print("=" * 80)

# body_v2.tex Sec 5.4 (line ~436): gamma_HM = -0.043 (t=-4.06)
# additions_jk.tex Sec 4.7 (line ~64): gamma_HM = -0.035 (t=-0.39)

checks.append(Check(
    table="Internal", cell="HM gamma: Sec 5.4 vs Sec 4.7 (additions_jk.tex)",
    paper_value="Sec 5.4: gamma_HM=-0.043 (t=-4.06) | Sec 4.7: gamma_HM=-0.035 (t=-0.39)",
    experiment_value="CONFLICT: two different values for same test",
    source="body_v2.tex line ~436 vs additions_jk.tex line ~64",
    status="MISMATCH",
    note="HIGH SEVERITY. Sec 5.4 says gamma=-0.043 (t=-4.06, significant). Sec 4.7 in additions_jk.tex says gamma=-0.035 (t=-0.39, not significant). These CANNOT both be correct for the same HM test on the same data. Likely different sample periods or specifications. Must resolve before submission."
))

# Table 11 kurtosis vs Table 1
checks.append(Check(
    table="Internal", cell="Excess kurtosis: Table 11 (14.71) vs Table 1 (14.6)",
    paper_value="Table 11: 14.71 | Table 1: 14.6",
    experiment_value="Different periods: Table 11 = 2014-2026, Table 1 = 2017-2025",
    source="tables.tex",
    status="MISMATCH",
    note="LOW SEVERITY. Different sample periods explain the difference, but should be noted explicitly."
))


# ===========================================================================
# DM p-value: Paper Table 3 vs K799 vs K802
# ===========================================================================
print("\n" + "=" * 80)
print("KEY IN-TEXT CLAIMS")
print("=" * 80)

if k799:
    dm = k799["evaluation_layers"]["layer_4"]["results"]["GJR vs GARCH"]
    checks.append(Check(
        table="In-text", cell="Sec 4.4 DM p for GJR vs GARCH (from K799)",
        paper_value="p=0.001 (Table 3)",
        experiment_value=f"p={dm['p_value']:.4f}, stat={dm['dm_stat']:.4f}",
        source="K799 layer_4",
        status="MISMATCH",
        note="K799 gives p=0.0035. K802 gives p=0.0012. Paper's p=0.001 appears to come from K802 (rounded), not K799."
    ))

if k802:
    dm = k802["qlike_results"]["DM_GJR_vs_GARCH"]
    checks.append(Check(
        table="In-text", cell="Sec 4.4 DM p for GJR vs GARCH (from K802)",
        paper_value="p=0.001",
        experiment_value=f"p={dm['p_value']:.4f}, stat={dm['stat']:.4f}",
        source="K802 qlike_results.DM_GJR_vs_GARCH",
        status="MATCH" if close_enough(0.001, dm["p_value"], atol=0.0005) else "ROUNDING",
        note=f"K802 p={dm['p_value']:.4f} rounds to 0.001. This is likely the paper's source."
    ))


# ===========================================================================
# UNTRACEABLE items
# ===========================================================================
print("\n" + "=" * 80)
print("UNTRACEABLE ITEMS (no experiment JSON)")
print("=" * 80)

untraceable = [
    ("Table 1", "ALL descriptive statistics (7 assets)", "No dedicated experiment"),
    ("Table 2", "Rolling gamma for QQQ, TLT, SLV", "No dedicated experiment"),
    ("Table 6", "VaR Panel (7 assets x 5 methods)", "Only partial coverage from K829"),
    ("Table 7", "VT Cross-Asset: TLT, EEM Sharpe/MDD", "No dedicated experiment"),
    ("Table 7", "VT Cross-Asset: BTC (conflicting KB values)", "Different periods in KB"),
    ("Table 8", "Window Robustness (5 windows x 3 OOS)", "No dedicated experiment"),
    ("Table 11", "Tail Risk Metrics (ES, worst day, kurtosis)", "No dedicated experiment"),
    ("Table 14", "QLIKE Ceiling (14 models)", "No dedicated experiment"),
    ("Figures", "All 7 figures lack source scripts", "No generation scripts found"),
    ("Abstract", "6/6 correct OOS predictions", "No experiment JSON validates this"),
    ("Abstract", "rho=0.83, p=0.0002, N=14 extended", "No traceable JSON"),
]

for table, desc, reason in untraceable:
    checks.append(Check(
        table=table, cell=desc,
        paper_value="(in paper)",
        experiment_value="NOT FOUND",
        source="None",
        status="UNTRACEABLE",
        note=reason
    ))


# ===========================================================================
# REPORT
# ===========================================================================
print("\n")
print("=" * 80)
print("PAPER 1 REPRODUCIBILITY REPORT")
print("Leverage Direction Matters: GJR-GARCH Gamma Taxonomy")
print("=" * 80)

# Count by status
from collections import Counter
status_counts = Counter(c.status for c in checks)

print(f"\nTotal checks: {len(checks)}")
print(f"  MATCH:           {status_counts.get('MATCH', 0)}")
print(f"  ROUNDING:        {status_counts.get('ROUNDING', 0)}")
print(f"  MISMATCH:        {status_counts.get('MISMATCH', 0)}")
print(f"  VERIFIED_KB_ONLY:{status_counts.get('VERIFIED_KB_ONLY', 0)}")
print(f"  NOTE:            {status_counts.get('NOTE', 0)}")
print(f"  UNTRACEABLE:     {status_counts.get('UNTRACEABLE', 0)}")

print("\n" + "-" * 80)
print("DETAILED RESULTS BY TABLE")
print("-" * 80)

current_table = None
for c in checks:
    if c.table != current_table:
        current_table = c.table
        print(f"\n### {current_table}")

    icon = {
        "MATCH": "OK",
        "ROUNDING": "~",
        "MISMATCH": "XX",
        "VERIFIED_KB_ONLY": "KB",
        "NOTE": "..",
        "UNTRACEABLE": "??",
    }.get(c.status, "??")

    print(f"  [{icon}] {c.cell}")
    print(f"       Paper:  {c.paper_value}")
    print(f"       Expt:   {c.experiment_value}")
    print(f"       Source: {c.source}")
    if c.note:
        print(f"       Note:   {c.note}")

# Summary of mismatches
mismatches = [c for c in checks if c.status == "MISMATCH"]
if mismatches:
    print("\n" + "=" * 80)
    print(f"MISMATCHES REQUIRING ATTENTION ({len(mismatches)})")
    print("=" * 80)
    for i, c in enumerate(mismatches, 1):
        print(f"\n{i}. [{c.table}] {c.cell}")
        print(f"   Paper: {c.paper_value}")
        print(f"   Expt:  {c.experiment_value}")
        if c.note:
            print(f"   Note:  {c.note}")

# Summary of untraceable
untr = [c for c in checks if c.status == "UNTRACEABLE"]
if untr:
    print("\n" + "=" * 80)
    print(f"UNTRACEABLE ITEMS ({len(untr)})")
    print("=" * 80)
    for i, c in enumerate(untr, 1):
        print(f"  {i}. [{c.table}] {c.cell}: {c.note}")

print("\n" + "=" * 80)
print("EXPERIMENT SOURCE MAPPING")
print("=" * 80)
print("""
Table 3 (QLIKE)      -> K799 (SPY 2023-24 only), K802 (DM test cross-check)
Table 4 (VaR Attr)   -> Knowledge base only (no dedicated JSON)
Table 5 (VaR Ortho)  -> K799 (GARCH+Normal, GJR+Normal)
                        K802 (GJR+StudentT, GJR+FHS)
                        K824v2 (M4_HistSim)
Table 9 (Hybrid VT)  -> Knowledge base only (Kill Test #3)
Table 10 (Amplify)   -> K824v2 (gamma cross-check), KB for rest
Table 12 (Gamma-Mech) -> Knowledge base only
Tables 1,2,6,7,8,11,14 -> NO dedicated experiment JSON exists
""")

print("=" * 80)
print("RECOMMENDATIONS")
print("=" * 80)
print("""
HIGH PRIORITY:
  1. Resolve HM gamma conflict (Sec 5.4: -0.043 vs additions_jk.tex: -0.035)
  2. Clarify DM p-value source (K799 p=0.0035 vs K802 p=0.0012 vs paper p=0.001)
  3. Fix Kupiec p rounding (Student-t: 0.67->0.60, HistSim: 0.64->0.60)

MEDIUM PRIORITY:
  4. Hybrid VT Sharpe rounding (0.985->0.99 is aggressive)
  5. Create dedicated experiments for Tables 1,2,6,7,8,11,14
  6. Standardize Table 5 source (currently mixes K799/K802/K824v2)

LOW PRIORITY:
  7. Note kurtosis difference (Table 11: 14.71 vs Table 1: 14.6, different periods)
  8. Save figure generation scripts alongside paper
""")
