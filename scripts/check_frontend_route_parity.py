#!/usr/bin/env python3
"""Run the active frontend route/scenario parity contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from volpred.ops.frontend_parity import audit_frontend_parity  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--contract",
        type=Path,
        default=ROOT / "config" / "frontend_route_scenario_parity.json",
    )
    parser.add_argument(
        "--targets",
        type=Path,
        default=ROOT / "config" / "project_targets.json",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit_frontend_parity(
        repo_root=ROOT,
        contract_path=args.contract,
        targets_path=args.targets,
    )
    rendered = json.dumps(
        report,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
