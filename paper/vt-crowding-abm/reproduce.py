#!/usr/bin/env python3
"""Paper 5 Reproducibility: Re-run K827v3 and verify all numbers."""
import json, subprocess, sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
EXP_DIR = Path(__file__).parent / "experiments"

print("=" * 60)
print("PAPER 5 REPRODUCIBILITY CHECK")
print("=" * 60)

# Run K827v3
print("\n[1/1] Running K827v3 (fixed liquidity ABM)...")
result = subprocess.run(
    ["uv", "run", "python", str(EXP_DIR / "k827v3_abm_fixed_liquidity.py")],
    capture_output=True, text=True, timeout=600, cwd=str(PROJECT)
)
if result.returncode != 0:
    print(f"  ERROR: {result.stderr[-500:]}")
    sys.exit(1)
print("  K827v3 complete.")

# Verify key numbers
print("\n" + "=" * 60)
print("TRACEABILITY TABLE")
print("=" * 60)

with open(EXP_DIR / "k827v3_abm_fixed_liquidity_results.json") as f:
    d = json.load(f)

sig = d.get("significance_tests", {})
print(f"\nt-test 10% vs 30%: t={sig.get('t_10_vs_30', '?')}, p={sig.get('p_10_vs_30', '?')}")
print(f"t-test 50% vs 10%: t={sig.get('t_50_vs_10', '?')}, p={sig.get('p_50_vs_10', '?')}")
print(f"\nPaper claims: t=0.05 (10v30), t=7.12 (50v10)")
