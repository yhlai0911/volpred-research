#!/usr/bin/env python3
"""Build the Graphify code-only pilot artifacts for hourly-dispatch evaluation.

This intentionally scans only src/volpred and scripts. It uses
`graphify update --no-cluster`, which is Graphify's AST-only rebuild path and
does not call an LLM backend.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
DEFAULT_OUT = ROOT / "storage" / "ops" / "graphify_codeonly"
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
TOKEN_USAGE_DIR = ROOT / "storage" / "reports" / "token_usage"
TASK_ID = "platform_ops_graphify_codeonly_pilot_20260702"
FOLLOWUP_ID = "platform_ops_graphify_codeonly_14d_verdict_20260716"
FOLLOWUP_BLOCKED_UNTIL = "2026-07-16T00:00:00+00:00"

from volpred.ops.next_tasks import normalize_task_priorities, normalize_task_priority  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=True)


def _copy_tree(src: Path, dst: Path) -> None:
    _run(
        [
            "rsync",
            "-a",
            "--exclude",
            "__pycache__",
            "--exclude",
            "*.pyc",
            str(src),
            str(dst),
        ]
    )


def _verify_graphify_source(timeout: int = 20) -> dict[str, Any]:
    url = "https://pypi.org/pypi/graphifyy/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # pragma: no cover - network fallback path
        return {
            "ok": False,
            "source": url,
            "error": f"{type(exc).__name__}: {exc}",
        }

    info = payload.get("info") or {}
    project_urls = info.get("project_urls") or {}
    values = [str(info.get("home_page") or ""), *[str(v) for v in project_urls.values()]]
    expected = "https://github.com/safishamsi/graphify"
    return {
        "ok": expected in values,
        "source": url,
        "package": info.get("name"),
        "version": info.get("version"),
        "expected_repository": expected,
        "project_urls": project_urls,
    }


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[graphify-pilot] load_json failed: {path}: {e}", file=sys.stderr)
        return None


def _category_snapshot(path: Path, category: str = "platform_ops") -> dict[str, Any] | None:
    payload = _load_json(path)
    if not payload:
        return None
    cat = (payload.get("by_category") or {}).get(category)
    if not isinstance(cat, dict):
        return None
    messages = int(cat.get("messages") or 0)
    billable_total = int(cat.get("billable_total") or 0)
    cost = float(cat.get("estimated_cost_usd") or 0.0)
    return {
        "file": str(path.relative_to(ROOT)),
        "window": payload.get("week_range") or payload.get("date"),
        "category": category,
        "messages": messages,
        "billable_total": billable_total,
        "estimated_cost_usd": cost,
        "billable_total_per_message": round(billable_total / messages, 2) if messages else None,
        "estimated_cost_usd_per_message": round(cost / messages, 6) if messages else None,
    }


def _build_token_baseline() -> dict[str, Any]:
    weekly = sorted(TOKEN_USAGE_DIR.glob("weekly_*.json"))[-2:]
    daily = sorted(TOKEN_USAGE_DIR.glob("daily_*.json"))[-1:]
    snapshots = [
        snap
        for path in [*weekly, *daily]
        if (snap := _category_snapshot(path)) is not None
    ]
    return {
        "captured_at": _now(),
        "metric_scope": "platform_ops category from scripts/token_usage_report.py",
        "honesty_note": (
            "Current token_usage reports do not isolate hourly-dispatch sessions; "
            "platform_ops is the closest reproducible proxy for this pilot."
        ),
        "baseline_files": snapshots,
    }


def _graph_metrics(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    links = graph.get("links") or graph.get("edges") or []
    source_files = sorted(
        {
            str(n.get("source_file"))
            for n in nodes
            if isinstance(n, dict) and n.get("source_file")
        }
    )
    return {
        "nodes": len(nodes),
        "edges": len(links) if isinstance(links, list) else 0,
        "source_files": len(source_files),
        "roots": ["src/volpred", "scripts"],
    }


def _parse_benchmark(stdout: str) -> dict[str, Any]:
    out: dict[str, Any] = {"raw_stdout": stdout}
    naive = re.search(r"Corpus:\s*([\d,]+) words .*? ~([\d,]+) tokens", stdout)
    avg = re.search(r"Avg query cost:\s*~([\d,]+) tokens", stdout)
    reduction = re.search(r"Reduction:\s*([\d.]+)x fewer tokens", stdout)
    if naive:
        out["corpus_words"] = int(naive.group(1).replace(",", ""))
        out["naive_tokens"] = int(naive.group(2).replace(",", ""))
    if avg:
        out["avg_query_tokens"] = int(avg.group(1).replace(",", ""))
    if reduction:
        out["reduction_x"] = float(reduction.group(1))
    return out


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _ensure_followup_task() -> dict[str, Any]:
    now = _now()
    task = {
        "id": FOLLOWUP_ID,
        "title": "[platform_ops] Graphify code-only pilot 14-day verdict",
        "description": (
            "Follow-up for platform_ops_graphify_codeonly_pilot_20260702. "
            "After the 14-day observation window, compare post-install "
            "platform_ops/hourly-dispatch token proxy against "
            "storage/ops/graphify_codeonly/token_baseline.json. "
            "If reduction is <10%, remove the MCP registration and Graphify pilot. "
            "If reduction is >=10%, write the knowledge entry and propose expansion. "
            "Do not claim before blocked_until expires."
        ),
        "task_type": "platform_ops",
        "priority": 4,
        "status": "blocked",
        "blocked_reason": "waiting_graphify_14d_observation_window",
        "blocked_until": FOLLOWUP_BLOCKED_UNTIL,
        "tags": ["platform_ops", "graphify", "pilot", "followup"],
        "source": "codex_graphify_codeonly_pilot",
        "created_at": now,
        "parent_task_id": TASK_ID,
        "dispatch_lane": "agent",
    }
    normalize_task_priority(task)

    NEXT_TASKS.parent.mkdir(parents=True, exist_ok=True)
    if not NEXT_TASKS.exists():
        NEXT_TASKS.write_text("[]\n", encoding="utf-8")
    with NEXT_TASKS.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            data = json.load(fh)
            if not isinstance(data, list):
                raise RuntimeError("storage/next_tasks.json is not a list")
            existing = next((item for item in data if isinstance(item, dict) and item.get("id") == FOLLOWUP_ID), None)
            if existing:
                return {"created": False, "id": FOLLOWUP_ID, "status": existing.get("status")}
            data.append(task)
            normalize_task_priorities(data)
            fh.seek(0)
            fh.truncate()
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
            return {"created": True, "id": FOLLOWUP_ID, "blocked_until": FOLLOWUP_BLOCKED_UNTIL}
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def build(out_dir: Path, enqueue_followup: bool) -> dict[str, Any]:
    graphify = shutil.which("graphify")
    graphify_mcp = shutil.which("graphify-mcp")
    if not graphify or not graphify_mcp:
        raise SystemExit("graphify/graphify-mcp not found. Run: uv tool install graphifyy")

    out_dir = out_dir.resolve()
    graph_out = out_dir / "graphify-out"
    graph_out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="volpred_graphify_codeonly_") as tmp_raw:
        tmp = Path(tmp_raw)
        (tmp / "src").mkdir()
        _copy_tree(ROOT / "src" / "volpred", tmp / "src/")
        _copy_tree(ROOT / "scripts", tmp / "")

        update = _run([graphify, "update", str(tmp), "--no-cluster"], cwd=ROOT)
        tmp_graph = tmp / "graphify-out" / "graph.json"
        if not tmp_graph.exists():
            raise RuntimeError(f"graphify did not produce {tmp_graph}")
        shutil.copy2(tmp_graph, graph_out / "graph.json")

    graph_path = graph_out / "graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    metrics = _graph_metrics(graph)
    benchmark = _parse_benchmark(_run([graphify, "benchmark", str(graph_path)], cwd=ROOT).stdout)
    baseline = _build_token_baseline()
    source_check = _verify_graphify_source()

    mcp_command = [
        "claude",
        "mcp",
        "add",
        "--scope",
        "local",
        "graphify-volpred-codeonly",
        "--",
        graphify_mcp,
        "--graph",
        str(graph_path),
    ]
    mcp_snippet = {
        "mcpServers": {
            "graphify-volpred-codeonly": {
                "type": "stdio",
                "command": graphify_mcp,
                "args": ["--graph", str(graph_path)],
            }
        }
    }

    followup = _ensure_followup_task() if enqueue_followup else {"created": False, "skipped": True}
    manifest = {
        "generated_at": _now(),
        "task_id": TASK_ID,
        "package": "graphifyy[mcp]",
        "install_command": "uv tool install --python 3.10 'graphifyy[mcp]' --force",
        "graphify_executable": graphify,
        "graphify_mcp_executable": graphify_mcp,
        "source_check": source_check,
        "scan_scope": {
            "included_roots": ["src/volpred", "scripts"],
            "excluded_roots": ["storage", "experiments", "paper", "frontend-v2-fix"],
            "mode": "graphify update --no-cluster (AST-only, no LLM)",
        },
        "graph_path": str(graph_path),
        "graph_metrics": metrics,
        "benchmark": benchmark,
        "mcp_local_add_command": mcp_command,
        "followup_task": followup,
    }

    _write_json(out_dir / "run_manifest.json", manifest)
    _write_json(out_dir / "token_baseline.json", baseline)
    _write_json(out_dir / "mcp_server.local.example.json", mcp_snippet)
    _write_text(out_dir / "mcp_add_command.txt", " ".join(mcp_command) + "\n")
    _write_text(
        out_dir / "pilot_status.md",
        "\n".join(
            [
                "# Graphify Code-only Pilot",
                "",
                f"- Generated at: {manifest['generated_at']}",
                "- Package: graphifyy[mcp]",
                f"- Source check OK: {source_check.get('ok')}",
                "- Scan scope: src/volpred + scripts only",
                "- Mode: graphify update --no-cluster (AST-only, no LLM)",
                f"- Nodes: {metrics['nodes']}",
                f"- Edges: {metrics['edges']}",
                f"- Source files: {metrics['source_files']}",
                f"- Benchmark reduction: {benchmark.get('reduction_x')}x",
                "- Token baseline: token_baseline.json uses platform_ops as proxy; current reports do not isolate hourly dispatch sessions.",
                f"- Follow-up task: {FOLLOWUP_ID} blocked until {FOLLOWUP_BLOCKED_UNTIL}",
                "",
                "Local MCP add command:",
                "",
                "```bash",
                " ".join(mcp_command),
                "```",
                "",
            ]
        ),
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--no-followup", action="store_true")
    args = parser.parse_args()
    manifest = build(args.out_dir, enqueue_followup=not args.no_followup)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
