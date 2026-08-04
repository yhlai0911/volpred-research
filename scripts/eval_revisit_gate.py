#!/usr/bin/env python3
"""Evaluate a registered revisit gate from a checkpoint's own results file.

The point of this CLI is that nobody hand-writes a revisit condition again.
Inputs are (a) the policy in ``config/revisit_gates.json`` and (b) the observed
statistic in the checkpoint's archived ``*_results.json``. The decision is
computed by ``volpred.research.revisit_gate``.

Usage::

    uv run python scripts/eval_revisit_gate.py --pipeline tw50_5min_har_rv
    uv run python scripts/eval_revisit_gate.py --pipeline tw50_5min_har_rv --write
    uv run python scripts/eval_revisit_gate.py --list

``--write`` emits ``experiments/<latest_checkpoint>/revisit_gate.json``. That
file is generated, never edited: it is the pipeline's live revisit decision,
kept separate from the archived results file so that re-deciding the gate never
rewrites the measurements of a run that has already been published.

Exit codes: 0 = gate met, 1 = wait / design change (i.e. do not re-run yet),
2 = usage or data error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from volpred.research.revisit_gate import (  # noqa: E402
    GateVerdict,
    evaluate_registered_pipeline,
    load_registry,
    read_latest_checkpoint,
)


def _emit(
    pipeline: str,
    entry: Dict[str, Any],
    checkpoint: Dict[str, Any],
    current_total_days: int,
    current_total_days_source: str,
) -> Dict[str, Any]:
    evaluation = evaluate_registered_pipeline(
        pipeline, current_total_days=current_total_days
    )
    payload = evaluation.to_dict()
    payload["generated_by"] = "scripts/eval_revisit_gate.py"
    payload["policy_source"] = "config/revisit_gates.json"
    payload["evidence"] = {
        "experiment_id": checkpoint["experiment_id"],
        "results_path": checkpoint["results_path"],
        "observed_dm_hln_t": checkpoint["observed_t"],
        "current_total_days_source": current_total_days_source,
    }
    payload["supersedes"] = entry.get("supersedes")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipeline", help="pipeline key in config/revisit_gates.json")
    parser.add_argument(
        "--list", action="store_true", help="list registered pipelines and exit"
    )
    parser.add_argument(
        "--current-total-days",
        type=int,
        default=None,
        help="raw trading days available today (default: the checkpoint's own count)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="write experiments/<checkpoint>/revisit_gate.json",
    )
    parser.add_argument("--json", action="store_true", help="print the payload as JSON")
    args = parser.parse_args()

    registry = load_registry()
    pipelines = registry.get("pipelines", {})

    if args.list:
        for key, entry in sorted(pipelines.items()):
            print(f"{key}: {entry.get('description', '')}")
        return 0

    if not args.pipeline:
        parser.error("--pipeline is required (or use --list)")

    if args.pipeline not in pipelines:
        print(f"[gate] unknown pipeline {args.pipeline!r}", file=sys.stderr)
        return 2

    entry = pipelines[args.pipeline]
    try:
        checkpoint = read_latest_checkpoint(args.pipeline)
    except (OSError, KeyError, ValueError) as exc:
        print(f"[gate] cannot read checkpoint: {exc}", file=sys.stderr)
        return 2

    if args.current_total_days is not None:
        current_total = args.current_total_days
        source = "--current-total-days override"
    else:
        current_total = checkpoint["current_total_days"]
        source = f"{checkpoint['results_path']} at time of that run"

    payload = _emit(args.pipeline, entry, checkpoint, current_total, source)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"[gate] pipeline    : {payload['pipeline']}")
        print(f"[gate] verdict     : {payload['verdict']}")
        print(
            f"[gate] observed    : |t|={payload['observed_abs_t']:.3f} "
            f"@ n_test={payload['observed_test_days']} "
            f"(n_total={payload['current_total_days']})"
        )
        print(
            f"[gate] required    : n_test>={payload['required_test_days']} "
            f"(~{payload['required_total_days']} raw trading days)"
        )
        ci = payload["required_test_days_ci"]
        print(
            f"[gate] requirement CI: optimistic {ci['optimistic_test_days']} .. "
            f"pessimistic {ci['pessimistic_test_days'] or 'unbounded'} test days"
        )
        print(f"[gate] rationale   : {payload['rationale']}")

    if args.write:
        out_dir = PROJECT_ROOT / "experiments" / checkpoint["experiment_id"]
        out_path = out_dir / "revisit_gate.json"
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print(f"[gate] wrote {out_path.relative_to(PROJECT_ROOT)}")

    return 0 if payload["verdict"] == GateVerdict.GATE_MET else 1


if __name__ == "__main__":
    raise SystemExit(main())
