#!/usr/bin/env python3
"""Maintain Graphify graphs and an honest query-usage ledger.

``update`` is local AST-only. Semantic document refresh is explicitly separate
because it can consume an LLM/API budget. Query rows distinguish a retrieval
proxy from observed model-token counts; they must never be conflated.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "graphify_integration.json"


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("graphs"), list):
        raise ValueError(f"invalid Graphify config: {path}")
    return data


def graph(config: dict[str, Any], graph_id: str) -> dict[str, Any]:
    for item in config["graphs"]:
        if item.get("id") == graph_id:
            return item
    raise ValueError(f"unknown graph id: {graph_id}")


def report_commit(report: Path) -> str | None:
    if not report.exists():
        return None
    for line in report.read_text(encoding="utf-8", errors="replace").splitlines():
        if "Built from commit:" in line and "`" in line:
            return line.split("`")[1]
    return None


def graph_status(config: dict[str, Any], graph_id: str) -> dict[str, Any]:
    item = graph(config, graph_id)
    output, report = ROOT / item["output"], ROOT / item["report"]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                          text=True, capture_output=True).stdout.strip()
    built = report_commit(report)
    return {"graph_id": graph_id, "graph_exists": (output / "graph.json").exists(),
            "report_exists": report.exists(), "built_from_commit": built, "head": head,
            "fresh": bool(built and head.startswith(built))}


def write_receipt(config: dict[str, Any], payload: dict[str, Any]) -> None:
    path = ROOT / config["freshness_receipt"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update(config: dict[str, Any], graph_ids: list[str]) -> int:
    # Graphify itself can fan out AST workers but does not serialize two separate
    # `graphify update` invocations.  The post-commit hook and the daily safety
    # net are both legitimate callers, so a non-blocking project lock prevents
    # concurrent writers from racing over graph.json/report/manifest.
    lock_path = ROOT / "storage" / "ops" / "locks" / "graphify_update.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(json.dumps({"generated_at": utc_now(), "skipped": "update_already_running"}, ensure_ascii=False))
        lock_handle.close()
        return 0
    runs: list[dict[str, Any]] = []
    try:
        for graph_id in graph_ids:
            command = list(graph(config, graph_id)["update_command"])
            completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
            runs.append({"graph_id": graph_id, "command": command,
                         "returncode": completed.returncode, "stdout_tail": completed.stdout[-2000:],
                         "stderr_tail": completed.stderr[-2000:]})
        receipt = {"generated_at": utc_now(), "runs": runs,
                   "graphs": [graph_status(config, graph_id) for graph_id in graph_ids]}
        write_receipt(config, receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0 if all(run["returncode"] == 0 for run in runs) else 1
    finally:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text.encode("utf-8")) / 4)


def corpus_proxy_tokens(graph_path: Path) -> int:
    data = json.loads(graph_path.read_text(encoding="utf-8"))
    files = {node.get("source_file") for node in data.get("nodes", [])
             if isinstance(node, dict) and isinstance(node.get("source_file"), str)}
    return math.ceil(sum((ROOT / source).stat().st_size for source in files
                         if (ROOT / source).is_file()) / 4)


def append_ledger(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def query(config: dict[str, Any], args: argparse.Namespace) -> int:
    item = graph(config, args.graph)
    graph_path = ROOT / item["output"] / "graph.json"
    if not graph_path.exists():
        raise FileNotFoundError(f"graph missing: {graph_path}; run update first")
    command = ["graphify", "query", args.question, "--budget", str(args.budget),
               "--graph", str(graph_path)]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    sys.stdout.write(completed.stdout)
    if completed.returncode:
        sys.stderr.write(completed.stderr)
        return completed.returncode
    append_ledger(ROOT / config["usage_ledger"], {
        "timestamp": utc_now(), "record_type": "graphify_treatment",
        "comparison_id": args.comparison_id, "graph_id": args.graph, "question": args.question,
        "query_budget": args.budget,
        "retrieval_proxy": {"baseline_full_corpus_tokens_estimate": corpus_proxy_tokens(graph_path),
                              "treatment_returned_tokens_estimate": estimate_tokens(completed.stdout),
                              "method": "UTF-8 bytes / 4; navigation proxy, not billed model usage"},
        "observed_model_tokens": args.observed_model_tokens,
    })
    return 0


def record_control(config: dict[str, Any], args: argparse.Namespace) -> int:
    append_ledger(ROOT / config["usage_ledger"], {
        "timestamp": utc_now(), "record_type": "control", "comparison_id": args.comparison_id,
        "question": args.question, "observed_model_tokens": args.observed_model_tokens,
    })
    return 0


def invalidate(config: dict[str, Any], args: argparse.Namespace) -> int:
    """Append a correction instead of mutating an existing audit record."""
    append_ledger(ROOT / config["usage_ledger"], {
        "timestamp": utc_now(), "record_type": "invalidation",
        "comparison_id": args.comparison_id, "reason": args.reason,
    })
    return 0


def usage_report(config: dict[str, Any]) -> dict[str, Any]:
    path = ROOT / config["usage_ledger"]
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    invalidated = {row.get("comparison_id") for row in rows if row.get("record_type") == "invalidation"}
    treatments = [row for row in rows if row.get("record_type") == "graphify_treatment"
                  and row.get("comparison_id") not in invalidated]
    controls = {row.get("comparison_id") for row in rows if row.get("record_type") == "control"}
    paired = [row for row in treatments if row.get("comparison_id") in controls and row.get("observed_model_tokens") is not None]
    return {"records": len(rows), "invalidated_records": len(invalidated),
            "graphify_treatments": len(treatments),
            "paired_observed_model_ab": len(paired),
            "note": "Retrieval proxy is not billed-token evidence; paired observed records are required for actual model-token A/B."}


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    update_parser = sub.add_parser("update")
    update_parser.add_argument("--graph", choices=["root", "active_frontend", "all"], default="all")
    sub.add_parser("status")
    query_parser = sub.add_parser("query")
    query_parser.add_argument("question")
    query_parser.add_argument("--graph", choices=["root", "active_frontend"], default="root")
    query_parser.add_argument("--budget", type=int, default=1200)
    query_parser.add_argument("--comparison-id")
    query_parser.add_argument("--observed-model-tokens", type=int)
    control_parser = sub.add_parser("record-control")
    control_parser.add_argument("question")
    control_parser.add_argument("--comparison-id", required=True)
    control_parser.add_argument("--observed-model-tokens", type=int, required=True)
    invalidate_parser = sub.add_parser("invalidate")
    invalidate_parser.add_argument("--comparison-id", required=True)
    invalidate_parser.add_argument("--reason", required=True)
    sub.add_parser("usage-report")
    args = parser.parse_args()
    config = load_config()
    if args.command == "update":
        ids = [item["id"] for item in config["graphs"]] if args.graph == "all" else [args.graph]
        return update(config, ids)
    if args.command == "status":
        print(json.dumps({"generated_at": utc_now(), "graphs": [graph_status(config, item["id"]) for item in config["graphs"]]}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "query":
        return query(config, args)
    if args.command == "record-control":
        return record_control(config, args)
    if args.command == "invalidate":
        return invalidate(config, args)
    print(json.dumps(usage_report(config), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
