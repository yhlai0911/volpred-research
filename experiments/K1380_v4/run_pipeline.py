#!/usr/bin/env python3
"""Canonical, fail-detectable K1380_v4 full-chain entrypoint.

The pipeline rebuilds every forecast and loss, performs corrected max-type inference,
then emits one run-time reproduce spec that identifies the complete chain.  Each stage
file is atomic, but the multi-file chain is not an atomic set swap: interruption can
leave new stage outputs beside the preceding spec.  That state fails the hash-bound
artifact gate and cannot masquerade as complete.  The child scripts refuse standalone
execution so neither can replace the full-chain provenance with a partial-stage spec.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from volpred.research.reproduce_spec import finalize_experiment

EXPERIMENT_DIR = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[2]
BASE_SCRIPT = EXPERIMENT_DIR / "k1380_v4.py"
CORRECTION_SCRIPT = EXPERIMENT_DIR / "k1380_v4_rc_correction.py"
CANONICAL_RESULT = "k1380_v4_rc_correction_results.json"
BOOTSTRAP_SEED = 42


def _run_child(script: Path) -> None:
    environment = os.environ.copy()
    environment["K1380_PIPELINE_CHILD"] = "1"
    subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        env=environment,
        check=True,
    )


def main() -> None:
    started_at = time.time()
    _run_child(BASE_SCRIPT)
    _run_child(CORRECTION_SCRIPT)

    result_path = EXPERIMENT_DIR / CANONICAL_RESULT
    results = json.loads(result_path.read_text(encoding="utf-8"))
    results["pipeline"] = {
        "entrypoint": "run_pipeline.py",
        "stages": ["k1380_v4.py", "k1380_v4_rc_correction.py"],
        "atomic_stage_outputs": True,
        "full_chain_atomic": False,
        "partial_failure_detection": (
            "reproduce_spec and reproduce_commit hash-bind every declared output"
        ),
    }

    out_path, _spec = finalize_experiment(
        results=results,
        entrypoint=__file__,
        canonical_result=CANONICAL_RESULT,
        inputs=[
            ROOT / "paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv",
            BASE_SCRIPT,
            CORRECTION_SCRIPT,
            ROOT / "src/volpred/research/optimization.py",
            ROOT / "src/volpred/models/garch/fixed_span_midas.py",
            ROOT / "src/volpred/stats/inference.py",
            ROOT / "src/volpred/research/reproduce_spec.py",
        ],
        outputs=["k1380_v4_results.json", "k1380_v4_losses_all.npy"],
        seeds=[("numpy", BOOTSTRAP_SEED)],
        started_at=started_at,
        network="deny",
    )
    print(f"[pipeline] canonical artifact written: {out_path}")


if __name__ == "__main__":
    main()
