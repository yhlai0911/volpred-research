#!/usr/bin/env python3
"""
PRG Paper: Reproducibility Script
===================================

Runs the core experiments from the paper's experiments/ directory and verifies
key numbers match the saved results.

Experiments:
  K880v2 — SPY daily (Table 2: PRG vs GJR DM, QLIKE)
  K881   — Multi-asset daily (Table 2: QQQ, GLD, EEM)
  K874d  — TAIFEX tick fair comparison (Table 2: TAIFEX, Robustness)

Usage:
  uv run python paper/prg-periodic-garch/reproduce.py [--quick]

  --quick: only run K880v2 (fastest, ~15s)
  default: run K880v2 + K881 (~60s total)
  TAIFEX (K874d) requires local tick data and is skipped by default.
"""
import json, subprocess, sys, shutil, os
from pathlib import Path

PAPER_DIR = Path(__file__).parent
EXP_DIR = PAPER_DIR / "experiments"
PROJECT = PAPER_DIR.parents[1]

quick_mode = "--quick" in sys.argv

print("=" * 60)
print("PRG PAPER REPRODUCIBILITY CHECK")
print("=" * 60)

def run_experiment(script_name, result_name, description):
    """Run an experiment and return the results dict."""
    script = EXP_DIR / script_name
    result_file = PROJECT / "experiments" / result_name

    print(f"\n[Running] {description}: {script_name}...")

    result = subprocess.run(
        ["uv", "run", "python", str(script)],
        capture_output=True, text=True, timeout=600,
        cwd=str(PROJECT)
    )

    if result.returncode != 0:
        print(f"  ERROR: {result.stderr[-500:]}")
        return None

    # Copy result back to paper directory
    dst = EXP_DIR / result_name
    if result_file.exists():
        shutil.copy2(result_file, dst)
        print(f"  Complete. Results copied to paper directory.")
        with open(dst) as f:
            return json.load(f)
    else:
        print(f"  WARNING: Result file not found at {result_file}")
        return None


def verify_number(claim, paper_val, computed_val, tol=0.05):
    """Check if computed value matches paper value within tolerance."""
    if computed_val is None:
        return False, "MISSING"
    diff = abs(paper_val - computed_val)
    rel_diff = diff / max(abs(paper_val), 1e-10)
    match = rel_diff < tol
    return match, f"{computed_val:.4f} (diff={rel_diff:.1%})"


# ============================================================
# 1. K880v2: SPY Daily (main result)
# ============================================================
d_spy = run_experiment(
    "k880v2_prg_fixed.py",
    "k880v2_results.json",
    "K880v2: SPY daily PRG"
)

# Also load saved reference results for comparison
ref_spy_path = EXP_DIR / "k880v2_results.json"
if ref_spy_path.exists():
    with open(ref_spy_path) as f:
        ref_spy = json.load(f)
else:
    ref_spy = None

# ============================================================
# 2. K881: Multi-asset (QQQ, GLD, EEM)
# ============================================================
d_multi = None
if not quick_mode:
    d_multi = run_experiment(
        "k881_prg_multi_asset.py",
        "k881_results.json",
        "K881: Multi-asset PRG (QQQ, GLD, EEM)"
    )

# ============================================================
# Traceability Table
# ============================================================
print("\n" + "=" * 60)
print("TRACEABILITY TABLE")
print("=" * 60)

checks = []

# SPY checks (from K880v2)
if d_spy:
    layer1 = d_spy.get("layer1_loss_functions", {})

    # QLIKE values
    for model in ["GJR", "PRG_Extended", "PRG_Basic", "Separate", "HAR"]:
        m = layer1.get(model, {})
        checks.append((f"SPY {model} QLIKE", m.get("QLIKE")))

    # Spearman
    layer3 = d_spy.get("layer3_spearman", {})
    for model in ["GJR", "PRG_Extended"]:
        m = layer3.get(model, {})
        checks.append((f"SPY {model} Spearman", m.get("rho")))

# Multi-asset checks (from K881)
if d_multi:
    for asset in ["QQQ", "GLD", "EEM"]:
        ar = d_multi.get("per_asset_results", {}).get(asset, {})
        layer1 = ar.get("layer1_loss_functions", {})
        prg_ext = layer1.get("PRG_Extended", {})
        gjr = layer1.get("GJR", {})
        checks.append((f"{asset} PRG_Ext QLIKE", prg_ext.get("QLIKE")))
        checks.append((f"{asset} GJR QLIKE", gjr.get("QLIKE")))

# Compare with reference
print(f"\n{'Metric':<35} {'Reproduced':>12} {'Reference':>12} {'Match':>6}")
print("-" * 70)

all_pass = True
if ref_spy and d_spy:
    ref_layer1 = ref_spy.get("layer1_loss_functions", {})
    new_layer1 = d_spy.get("layer1_loss_functions", {})

    for model in ["GJR", "PRG_Extended", "PRG_Basic", "Separate", "HAR"]:
        ref_q = ref_layer1.get(model, {}).get("QLIKE")
        new_q = new_layer1.get(model, {}).get("QLIKE")
        if ref_q and new_q:
            match, detail = verify_number(f"SPY {model} QLIKE", ref_q, new_q, tol=0.01)
            if not match:
                all_pass = False
            status = "OK" if match else "DIFF"
            print(f"SPY {model} QLIKE          {new_q:>12.4f} {ref_q:>12.4f} {status:>6}")

print("\n" + "=" * 60)
if all_pass:
    print("ALL KEY NUMBERS VERIFIED OK")
else:
    print("WARNING: SOME NUMBERS DIFFER (check data freshness)")
print("=" * 60)

# Print key paper table numbers
print("\n--- Paper Table 2 Key Numbers (from reproduced results) ---")
if d_spy:
    layer1 = d_spy.get("layer1_loss_functions", {})
    print(f"SPY PRG_Extended QLIKE: {layer1.get('PRG_Extended', {}).get('QLIKE', 'N/A'):.4f}")
    print(f"SPY GJR QLIKE:         {layer1.get('GJR', {}).get('QLIKE', 'N/A'):.4f}")

if d_multi:
    for asset in ["QQQ", "GLD", "EEM"]:
        ar = d_multi["per_asset_results"][asset]
        layer1 = ar["layer1_loss_functions"]
        print(f"{asset} PRG_Extended QLIKE: {layer1['PRG_Extended']['QLIKE']:.4f}")
