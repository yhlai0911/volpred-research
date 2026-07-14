"""Merge kb-backfill shard proposals into a single validated proposal file.

Agents propose prose (content/verdict/category/confidence/needs_human); this script
derives every mechanical field (item_id, created_at) from the artifacts themselves so
no derived value depends on an agent's memory. Run from the repo root:

    uv run python storage/ops/kb_backfill/merge_proposals.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SHARD_DIR = ROOT / "storage/ops/kb_backfill/shards"
OUT = ROOT / "storage/ops/kb_backfill/proposed_entries.json"
KNOWLEDGE = ROOT / "storage/memory/knowledge.json"

DATE_KEYS = (
    "created_at", "timestamp", "run_timestamp", "generated_at", "completed_at",
    "run_date", "date", "as_of", "executed_at", "run_at",
)
ALLOWED_CATEGORIES = {
    "experiment_result", "model_behavior", "vol_prediction", "vt_strategy", "strategy",
    "cross_asset", "data_property", "research_methodology", "market_context", "literature",
}
ALLOWED_VERDICTS = {
    "PASS", "NULL", "CONDITIONAL_PASS", "FAIL", "DOCUMENTED_NEGATIVE",
    "INCONCLUSIVE", "UNVERIFIED",
}


def _find_date(obj, depth: int = 0):
    """First ISO-ish date found in a results artifact, breadth-first over dict keys."""
    if depth > 4:
        return None
    if isinstance(obj, dict):
        for key in DATE_KEYS:
            val = obj.get(key)
            if isinstance(val, str) and re.match(r"^\d{4}-\d{2}-\d{2}", val):
                return val[:10]
        for val in obj.values():
            found = _find_date(val, depth + 1)
            if found:
                return found
    elif isinstance(obj, list):
        for val in obj[:20]:
            found = _find_date(val, depth + 1)
            if found:
                return found
    return None


def main() -> int:
    expected = {
        rec["experiment"]
        for rec in json.loads((ROOT / "storage/ops/kb_backfill/unrecorded.json").read_text())
    }

    proposals: list[dict] = []
    for shard in sorted(SHARD_DIR.glob("shard_*.json")):
        for prop in json.loads(shard.read_text()):
            # Agents were free to write either the dir name or the repo-relative path.
            prop["experiment"] = Path(prop["experiment"]).name
            proposals.append(prop)

    seen = {p["experiment"] for p in proposals}
    problems: list[str] = []
    warnings: list[str] = []
    if missing := expected - seen:
        problems.append(f"missing experiments: {sorted(missing)}")
    if extra := seen - expected:
        problems.append(f"unexpected experiments: {sorted(extra)}")
    if len(seen) != len(proposals):
        problems.append("duplicate experiment entries across shards")

    existing_ids = {
        entry.get("item_id")
        for entry in json.loads(KNOWLEDGE.read_text())
        if isinstance(entry, dict)
    }

    entries: list[dict] = []
    for prop in sorted(proposals, key=lambda p: p["experiment"].lower()):
        exp = prop["experiment"]
        exp_dir = ROOT / "experiments" / Path(exp).name
        item_id = hashlib.sha1(exp.encode()).hexdigest()[:8]
        if item_id in existing_ids:
            problems.append(f"{exp}: item_id {item_id} collides with an existing entry")

        results = sorted(p for p in exp_dir.glob("*results.json") if p.name != "reproduce_report.json")
        created_at, source = None, "file_mtime"
        for path in results:
            try:
                created_at = _find_date(json.loads(path.read_text()))
            except (OSError, ValueError):
                created_at = None
            if created_at:
                source = f"artifact:{path.name}"
                break
        if not created_at:
            mtime = min((p.stat().st_mtime for p in results), default=exp_dir.stat().st_mtime)
            created_at = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d")

        evidence = []
        for rel in prop.get("evidence", []):
            if (ROOT / rel).exists():
                evidence.append(rel)
            else:
                # Dropped, not fatal: the agent cited a file the artifact's own README
                # promised but that was never produced (e.g. a pending codex_review.md).
                warnings.append(f"{exp}: dropped non-existent evidence path {rel}")
        if not evidence:
            problems.append(f"{exp}: no surviving evidence path")

        content = prop.get("content", "")
        k_id = prop.get("k_id", "")
        if k_id and k_id.casefold() not in content.casefold():
            problems.append(f"{exp}: content does not mention {k_id}")
        if prop.get("category") not in ALLOWED_CATEGORIES:
            problems.append(f"{exp}: bad category {prop.get('category')!r}")
        if prop.get("verdict") not in ALLOWED_VERDICTS:
            problems.append(f"{exp}: bad verdict {prop.get('verdict')!r}")
        needs_human = bool(prop.get("needs_human"))
        if needs_human and not prop.get("gap"):
            problems.append(f"{exp}: needs_human without gap")

        entries.append({
            "item_id": item_id,
            "k_id": k_id,
            "experiment_id": exp,
            "experiment_path": f"experiments/{exp_dir.name}/",
            "category": prop["category"],
            "verdict": prop["verdict"],
            "content": content,
            "evidence": evidence,
            "confidence": float(prop.get("confidence", 0.0)),
            "created_at": created_at,
            "created_at_source": source,
            "needs_human": needs_human,
            "gap": prop.get("gap", ""),
            "provenance": "kb_backfill_unrecorded_experiments (2026-07-14)",
        })

    OUT.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n")

    print(f"entries: {len(entries)}  needs_human: {sum(e['needs_human'] for e in entries)}")
    print("created_at from artifact:", sum(e["created_at_source"].startswith("artifact") for e in entries))
    if warnings:
        print(f"\nWARNINGS ({len(warnings)}):")
        for w in warnings:
            print(" -", w)
    if problems:
        print(f"\nPROBLEMS ({len(problems)}):")
        for p in problems:
            print(" -", p)
        return 1
    print("\nvalidation: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
