#!/usr/bin/env python3
"""
Paper 5: When Volatility Targeting Crowds — Reproducibility Script

Runs K827v3 from the paper's own experiments/ directory.
Results copied back to paper directory for traceability.

Usage: uv run python paper/vt-crowding-abm/reproduce.py
"""
import json, subprocess, sys, shutil
from pathlib import Path

PAPER_DIR = Path(__file__).parent
EXP_DIR = PAPER_DIR / "experiments"
PROJECT = PAPER_DIR.parents[1]

print("=" * 60)
print("PAPER 5 REPRODUCIBILITY CHECK")
print("=" * 60)

# Run K827v3 from paper's experiments/ directory
script = EXP_DIR / "k827v3_abm_fixed_liquidity.py"
print(f"\n[1/1] Running {script.name}...")
result = subprocess.run(
    ["uv", "run", "python", str(script)],
    capture_output=True, text=True, timeout=600,
    cwd=str(PROJECT)
)
if result.returncode != 0:
    print(f"  ERROR: {result.stderr[-500:]}")
    sys.exit(1)

# Copy result JSON back to paper directory
src = PROJECT / "experiments" / "k827v3_abm_fixed_liquidity_results.json"
dst = EXP_DIR / "k827v3_abm_fixed_liquidity_results.json"
if src.exists():
    shutil.copy2(src, dst)
print("  Complete. Results in paper directory.")

# Verify key numbers
print("\n" + "=" * 60)
print("TRACEABILITY TABLE")
print("=" * 60)

with open(dst) as f:
    d = json.load(f)

sig = d.get("analysis", {}).get("significance_tests", {})

checks = {
    "t-test 30% vs 10% (t)": (0.05, sig.get("30%", {}).get("t_stat")),
    "t-test 50% vs 10% (t)": (7.12, sig.get("50%", {}).get("t_stat")),
}

all_pass = True
print(f"\n{'Claim':<30} {'Paper':>8} {'Computed':>12} {'Match':>6}")
print("-" * 60)
for claim, (paper_val, computed_val) in checks.items():
    if computed_val is None:
        print(f"{claim:<30} {paper_val:>8.2f} {'MISSING':>12} {'❌':>6}")
        all_pass = False
    else:
        match = abs(paper_val - round(computed_val, 2)) < 0.02
        if not match:
            all_pass = False
        print(f"{claim:<30} {paper_val:>8.2f} {computed_val:>12.4f} {'✅' if match else '❌':>6}")

print("\n" + "=" * 60)
print("ALL KEY NUMBERS VERIFIED ✅" if all_pass else "⚠️ SOME NUMBERS DO NOT MATCH")
print("=" * 60)
