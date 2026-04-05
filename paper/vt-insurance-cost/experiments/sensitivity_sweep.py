#!/usr/bin/env python3
"""
Paper 4 Sensitivity Sweep: Run K811v2 decomposition at thresholds 0.5, 1.0, 1.5.
Each threshold writes to a SEPARATE output file.

Usage: uv run python paper/vt-insurance-cost/experiments/sensitivity_sweep.py
"""
import json, re, subprocess, sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[3]
SCRIPT = PROJECT / "experiments" / "k811v2_insurance_premium_vov_fixed.py"
OUT_DIR = Path(__file__).parent

for threshold in [0.5, 1.0, 1.5]:
    print(f"\n{'='*60}")
    print(f"Running threshold = {threshold}")
    print(f"{'='*60}")
    
    # Read original script
    code = SCRIPT.read_text()
    
    # Replace threshold (line 172: high_vov = vov_z > 1.0)
    code = re.sub(r'high_vov = vov_z > \d+\.\d+', f'high_vov = vov_z > {threshold}', code)
    
    # Replace output path to write to separate file
    orig_output = 'experiments" / "k811v2_insurance_premium_vov_fixed_results.json'
    new_output = f'paper/vt-insurance-cost/experiments/k811v2_th{str(threshold).replace(".", "_")}_results.json'
    code = code.replace(
        'PROJECT / "experiments" / "k811v2_insurance_premium_vov_fixed_results.json"',
        f'PROJECT / "{new_output}"'
    )
    
    # Write temp script
    tmp = OUT_DIR / f"_tmp_th{threshold}.py"
    tmp.write_text(code)
    
    # Run
    result = subprocess.run(
        ["uv", "run", "python", str(tmp)],
        capture_output=True, text=True, timeout=300,
        cwd=str(PROJECT)
    )
    
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr[-300:]}")
        continue
    
    # Read results
    out_file = PROJECT / new_output
    if out_file.exists():
        with open(out_file) as f:
            d = json.load(f)
        s2 = d["insurance_cost_decomposed"]["S2 VoV-Cond"]
        s1 = d["insurance_cost_decomposed"]["S1 Always VT"]
        opp_share = s2["opportunity_cost_pct_yr"] / s2["total_cost_pct_yr"] * 100
        reduction = (1 - s2["total_cost_pct_yr"] / s1["total_cost_pct_yr"]) * 100
        print(f"  S2 opp: {s2['opportunity_cost_pct_yr']:.3f}%")
        print(f"  S2 total: {s2['total_cost_pct_yr']:.3f}%")
        print(f"  opp_share: {opp_share:.1f}%")
        print(f"  reduction: {reduction:.1f}%")
    
    # Cleanup temp
    tmp.unlink()

print("\n" + "="*60)
print("SENSITIVITY SWEEP COMPLETE")
print("="*60)
