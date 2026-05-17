#!/usr/bin/env python3
"""
K1370c — N_start=10 vs N_start=100 sensitivity micro-test.

Codex residual concern from K1370 v2 review: reduced N_start (10 vs canonical
100 per K1302/K1302b) might introduce optimization noise that inflates CI.

This script picks 20 selected boot_seeds from K1370 v2 (B=1000 × N_start=10)
results and re-runs them with N_start=100 multistart per series. Compares
per-replicate amplification ratio.

If max |delta| < 0.1× on amplification AND CI bounds shift < 0.1× → close
Codex concern, declare N_start=10 sufficient for K1370.

Runtime estimate: 20 reps × 10 series × 100 starts = 20,000 arch fits ≈ 8min.

Uses k1370.py functions directly (no re-implementation).
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "experiments" / "k1370"))

# Import K1370 v2 machinery (need to clean import path)
import importlib.util
spec = importlib.util.spec_from_file_location("k1370_mod", PROJECT_ROOT / "experiments" / "k1370" / "k1370.py")
k1370 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(k1370)

OUT_DIR = Path(__file__).resolve().parent
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    print(f"[K1370c] N_start sensitivity micro-test", flush=True)
    print(f"[K1370c] Date: {datetime.now(timezone.utc).isoformat()}", flush=True)

    # Load v2 replicate-level results
    v2_path = PROJECT_ROOT / "experiments" / "k1370" / "k1370_replicates.json"
    v2 = json.loads(v2_path.read_text())
    v2_reps = v2["replicates"]
    print(f"[K1370c] Loaded {len(v2_reps)} v2 replicates (N_start=10)", flush=True)

    # Pick 20 evenly-spaced boot_seeds from v2 (deterministic selection)
    step = len(v2_reps) // 20
    selected_indices = list(range(0, len(v2_reps), step))[:20]
    print(f"[K1370c] Selected v2 indices: {selected_indices[:5]}...{selected_indices[-3:]} (20 total)", flush=True)

    # Load data once (re-use k1370 data pipeline)
    print(f"[K1370c] [1/3] Loading data via k1370 pipeline...", flush=True)
    paper_df = k1370.load_paper_csv()
    series = {}
    series[k1370.INDEX_TICKER] = k1370.load_series(k1370.INDEX_TICKER, k1370.INDEX_PAPER_COL, paper_df)
    for tk in k1370.INDIVIDUAL_TICKERS:
        col = tk.lower().replace(".", "_") + "_adj_close"
        series[tk] = k1370.load_series(tk, col, paper_df)
    import pandas as pd
    returns_by_ticker = {}
    for tk, px in series.items():
        px = px.loc[(px.index >= k1370.SAMPLE_START) & (px.index <= k1370.SAMPLE_END)].dropna()
        r = k1370.compute_log_returns(px)
        returns_by_ticker[tk] = r.values
    print(f"[K1370c] data loaded; running {len(selected_indices)} reps × N_start=100", flush=True)

    # Run each selected replicate with N_start=100
    N_START_HIGH = 100
    multistart_seeds_high = list(range(N_START_HIGH))
    results = []
    t0 = time.time()
    for i, v2_idx in enumerate(selected_indices):
        v2_rep = v2_reps[v2_idx]
        boot_seed = v2_rep["boot_seed"]
        # Subagent-flagged hold-constant guard (2026-05-17): explicit assert that
        # v2 boot_seed formula (boot_seed = seed_base + rep_idx) holds for the
        # rep we are comparing against. Survives any future k1370.run_replicate
        # refactor that changes seed derivation.
        derived_boot_seed = k1370.GLOBAL_SEED + v2_idx
        assert derived_boot_seed == boot_seed, (
            f"hold-constant violation: derived boot_seed {derived_boot_seed} != "
            f"v2 record {boot_seed} at v2_idx={v2_idx}; K1370c comparison invalid"
        )
        out = k1370.run_replicate(
            rep_idx=v2_idx,
            returns_by_ticker=returns_by_ticker,
            block_length=k1370.BLOCK_LENGTH,
            multistart_seeds=multistart_seeds_high,
            seed_base=k1370.GLOBAL_SEED,
        )
        elapsed = time.time() - t0
        rep_eta = (elapsed / (i+1)) * (len(selected_indices) - i - 1)
        print(f"[K1370c]   rep {i+1}/20  v2_idx={v2_idx}  seed={boot_seed}  amp_v2={v2_rep['amplification']:.3f}  amp_100={out['amplification']:.3f}  delta={out['amplification']-v2_rep['amplification']:+.3f}  elapsed={elapsed:.0f}s  ETA={rep_eta:.0f}s", flush=True)
        results.append({
            "v2_idx": v2_idx,
            "boot_seed": boot_seed,
            "amp_n10_v2": v2_rep["amplification"],
            "amp_n100": out["amplification"],
            "delta": out["amplification"] - v2_rep["amplification"],
            "abs_delta": abs(out["amplification"] - v2_rep["amplification"]),
            "n_indiv_converged_v2": v2_rep["n_indiv_converged"],
            "n_indiv_converged_n100": out["n_indiv_converged"],
        })
    print(f"[K1370c] all {len(selected_indices)} reps done in {time.time()-t0:.0f}s", flush=True)

    import statistics
    abs_deltas = [r["abs_delta"] for r in results]
    deltas = [r["delta"] for r in results]
    summary = {
        "experiment_id": "K1370c",
        "title": "K1370 N_start=10 vs N_start=100 sensitivity micro-test",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "n_replicates_tested": len(selected_indices),
            "N_start_baseline": k1370.N_START,
            "N_start_alternative": N_START_HIGH,
            "selection": "evenly-spaced indices from k1370_replicates.json (deterministic)",
        },
        "sensitivity": {
            "max_abs_delta": max(abs_deltas),
            "mean_abs_delta": statistics.mean(abs_deltas),
            "median_abs_delta": statistics.median(abs_deltas),
            "max_signed_delta": max(deltas),
            "min_signed_delta": min(deltas),
            "n_delta_gt_0_1": sum(1 for d in abs_deltas if d > 0.1),
            "n_delta_gt_0_5": sum(1 for d in abs_deltas if d > 0.5),
        },
        "v2_amplification_stats": {
            "median": statistics.median([r["amp_n10_v2"] for r in results]),
            "mean": statistics.mean([r["amp_n10_v2"] for r in results]),
        },
        "n100_amplification_stats": {
            "median": statistics.median([r["amp_n100"] for r in results]),
            "mean": statistics.mean([r["amp_n100"] for r in results]),
        },
        "verdict": "PENDING",  # set below
        "verdict_logic": "PASS if max_abs_delta < 0.1× AND mean_abs_delta < 0.05×; FAIL if max > 0.5× or mean > 0.1×; CONDITIONAL otherwise",
        "per_replicate": results,
        "runtime_seconds": time.time() - t0,
    }

    # Determine verdict
    max_d = summary["sensitivity"]["max_abs_delta"]
    mean_d = summary["sensitivity"]["mean_abs_delta"]
    if max_d < 0.1 and mean_d < 0.05:
        summary["verdict"] = "PASS — N_start=10 sufficient; Codex residual concern closed"
    elif max_d > 0.5 or mean_d > 0.1:
        summary["verdict"] = "FAIL — N_start=10 introduces material noise; recommend re-run K1370 with N_start=100"
    else:
        summary["verdict"] = "CONDITIONAL — within tolerance band; honest disclosure in paper preferred"
    print(f"[K1370c] verdict: {summary['verdict']}", flush=True)
    print(f"[K1370c] max_abs_delta={max_d:.3f}  mean_abs_delta={mean_d:.3f}", flush=True)

    out_path = OUT_DIR / "k1370c_results.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[K1370c] results saved to {out_path}", flush=True)


if __name__ == "__main__":
    main()
