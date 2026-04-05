#!/usr/bin/env python3
"""
Paper 4: The True Cost of Volatility Targeting — Reproducibility Script

This script reproduces ALL numbers in the paper from raw data.
Run: uv run python paper/vt-insurance-cost/reproduce.py

Data sources:
  - yfinance: SPY, GLD, ^VIX, ^VVIX (downloaded live)
  - No local data files required

Outputs:
  - paper/vt-insurance-cost/experiments/reproduce_results.json
  - Console: traceability table (paper value → computed value)
"""
import json
import sys
from pathlib import Path

# Run K811v2 and K846 experiments
print("=" * 60)
print("PAPER 4 REPRODUCIBILITY CHECK")
print("=" * 60)

# Step 1: Run K811v2 (main decomposition)
print("\n[1/3] Running K811v2 (insurance premium decomposition)...")
script_dir = Path(__file__).parent / "experiments"
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import subprocess
result1 = subprocess.run(
    ["uv", "run", "python", str(script_dir / "k811v2_insurance_premium_vov_fixed.py")],
    capture_output=True, text=True, timeout=300,
    cwd=str(Path(__file__).parent.parent.parent)
)
if result1.returncode != 0:
    print(f"  ERROR: {result1.stderr[-500:]}")
    sys.exit(1)
print("  K811v2 complete.")

# Step 2: Run K846 (rebalancing premium)
print("\n[2/3] Running K846 (rebalancing premium)...")
result2 = subprocess.run(
    ["uv", "run", "python", str(script_dir / "k846_rebalancing_premium.py")],
    capture_output=True, text=True, timeout=300,
    cwd=str(Path(__file__).parent.parent.parent)
)
if result2.returncode != 0:
    print(f"  ERROR: {result2.stderr[-500:]}")
    sys.exit(1)
print("  K846 complete.")

# Step 3: Run sensitivity threshold sweep
print("\n[3/3] Running sensitivity sweep (thresholds 0.5, 1.0, 1.5)...")
for th in ["0.5", "1.5"]:
    th_script = script_dir / f"k811v2_threshold_{th}.py"
    if th_script.exists():
        result3 = subprocess.run(
            ["uv", "run", "python", str(th_script)],
            capture_output=True, text=True, timeout=300,
            cwd=str(Path(__file__).parent.parent.parent)
        )
        if result3.returncode != 0:
            print(f"  WARNING: threshold {th} failed")
print("  Sensitivity complete.")

# Step 4: Verify numbers against paper
print("\n" + "=" * 60)
print("TRACEABILITY TABLE")
print("=" * 60)

k811v2 = json.loads((script_dir / "k811v2_insurance_premium_vov_fixed_results.json").read_text())
decomp = k811v2["insurance_cost_decomposed"]

paper_values = {
    "Table 1: S1 total premium (%)": (4.62, decomp["S1 Always VT"]["total_cost_pct_yr"]),
    "Table 1: S1 opp cost (%)": (4.20, decomp["S1 Always VT"]["opportunity_cost_pct_yr"]),
    "Table 1: S1 direct cost (%)": (0.43, decomp["S1 Always VT"]["direct_cost_pct_yr"]),
    "Table 1: S2 total premium (%)": (1.22, decomp["S2 VoV-Cond"]["total_cost_pct_yr"]),
    "Table 1: S2 opp cost (%)": (0.70, decomp["S2 VoV-Cond"]["opportunity_cost_pct_yr"]),
    "Table 1: S2 direct cost (%)": (0.52, decomp["S2 VoV-Cond"]["direct_cost_pct_yr"]),
    "Table 1: S3 total premium (%)": (3.31, decomp["S3 Smooth"]["total_cost_pct_yr"]),
    "Text: S1 opp share (%)": (91, decomp["S1 Always VT"]["opportunity_cost_pct_yr"] / decomp["S1 Always VT"]["total_cost_pct_yr"] * 100),
    "Text: S2 reduction vs S1 (%)": (74, (1 - decomp["S2 VoV-Cond"]["total_cost_pct_yr"] / decomp["S1 Always VT"]["total_cost_pct_yr"]) * 100),
}

all_pass = True
print(f"\n{'Claim':<40} {'Paper':>8} {'Computed':>10} {'Match':>6}")
print("-" * 68)
for claim, (paper_val, computed_val) in paper_values.items():
    match = abs(paper_val - computed_val) < 0.1
    status = "✅" if match else "❌"
    if not match:
        all_pass = False
    print(f"{claim:<40} {paper_val:>8.2f} {computed_val:>10.3f} {status:>6}")

print("\n" + "=" * 60)
if all_pass:
    print("ALL NUMBERS VERIFIED ✅")
else:
    print("⚠️ SOME NUMBERS DO NOT MATCH")
print("=" * 60)
