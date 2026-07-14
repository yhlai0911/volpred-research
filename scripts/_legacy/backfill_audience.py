#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FEED_PATH = ROOT / "storage" / "reports" / "feed.json"
OPS_DIR = ROOT / "storage" / "ops"
REPORTS_DIR = ROOT / "storage" / "reports"
ARCHIVE_DIR = REPORTS_DIR / "_archive_mile_files"

AUDIENCE_ALIASES = {
    "一般讀者",
    "general",
    "研究",
    "research",
    "Research",
    "audience=general",
    "audience=research",
}
CANONICAL_AUDIENCE_TAG = {
    "general": "一般讀者",
    "research": "研究",
}


def _load_validator_module():
    path = ROOT / "scripts" / "validate_feed_audience.py"
    spec = importlib.util.spec_from_file_location("validate_feed_audience", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load validator module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_tags(tags: list[Any] | None, *, audience: str) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in tags or []:
        if not isinstance(raw, str):
            continue
        tag = raw.strip()
        if not tag or tag in AUDIENCE_ALIASES:
            continue
        if tag in seen:
            continue
        cleaned.append(tag)
        seen.add(tag)
    canonical = CANONICAL_AUDIENCE_TAG[audience]
    return [canonical, *cleaned]


def candidate_report_paths(article_id: str) -> list[Path]:
    paths: list[Path] = []
    primary = REPORTS_DIR / f"{article_id}.json"
    archive = ARCHIVE_DIR / f"{article_id}.json"
    for path in (primary, archive):
        if path.exists():
            paths.append(path)
    return paths


def patch_article_payload(payload: dict[str, Any], *, article_id: str, run_at: str) -> bool:
    changed = False
    if payload.get("audience") != "research":
        payload["audience"] = "research"
        changed = True

    normalized_tags = normalize_tags(payload.get("tags"), audience="research")
    if normalized_tags != (payload.get("tags") or []):
        payload["tags"] = normalized_tags
        changed = True

    details = payload.get("details")
    if not isinstance(details, dict):
        details = {}
        payload["details"] = details
        changed = True

    if details.get("audience") != "research":
        details["audience"] = "research"
        changed = True

    backfill = details.get("audience_backfill")
    if not isinstance(backfill, dict):
        backfill = {}
        details["audience_backfill"] = backfill
        changed = True

    desired = {
        "applied_at": run_at,
        "reason": "validator_371_historical_backfill",
        "previous_audience": "general",
        "script": "scripts/backfill_audience.py",
        "article_id": article_id,
    }
    # Keep the original applied_at on idempotent re-runs.
    if isinstance(backfill.get("applied_at"), str):
        desired["applied_at"] = backfill["applied_at"]
    if backfill != desired:
        details["audience_backfill"] = desired
        changed = True

    return changed


def build_backfill_plan(feed: list[dict[str, Any]]) -> dict[str, Any]:
    validator = _load_validator_module()
    candidates: list[dict[str, Any]] = []
    for entry in feed:
        is_violation, labels = validator.check_entry(entry)
        if not is_violation:
            continue
        article_id = str(entry.get("id") or "")
        candidates.append(
            {
                "id": article_id,
                "title": str(entry.get("title") or ""),
                "status": str(entry.get("status") or ""),
                "keywords": labels,
                "report_paths": [str(path.relative_to(ROOT)) for path in candidate_report_paths(article_id)],
            }
        )
    return {
        "generated_at": _now_iso(),
        "violations": candidates,
        "count": len(candidates),
    }


def apply_backfill(feed: list[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    run_at = _now_iso()
    patched_feed = 0
    patched_reports = 0
    report_files_touched: list[str] = []

    feed_index = {str(item.get("id") or ""): item for item in feed if isinstance(item, dict)}
    for item in plan["violations"]:
        article_id = item["id"]
        feed_item = feed_index.get(article_id)
        if isinstance(feed_item, dict) and patch_article_payload(feed_item, article_id=article_id, run_at=run_at):
            patched_feed += 1

        for report_path in candidate_report_paths(article_id):
            payload = _load_json(report_path)
            if not isinstance(payload, dict):
                continue
            if patch_article_payload(payload, article_id=article_id, run_at=run_at):
                _write_json(report_path, payload)
                patched_reports += 1
                report_files_touched.append(str(report_path.relative_to(ROOT)))

    _write_json(FEED_PATH, feed)
    return {
        "applied_at": run_at,
        "patched_feed_entries": patched_feed,
        "patched_report_files": patched_reports,
        "report_files_touched": report_files_touched,
    }


def render_markdown(plan: dict[str, Any], apply_result: dict[str, Any] | None) -> str:
    lines = [
        "# Audience Backfill",
        "",
        f"- generated_at: `{plan['generated_at']}`",
        f"- violations: `{plan['count']}`",
    ]
    if apply_result is None:
        lines.append("- mode: `dry-run`")
    else:
        lines.append("- mode: `apply`")
        lines.append(f"- applied_at: `{apply_result['applied_at']}`")
        lines.append(f"- patched feed entries: `{apply_result['patched_feed_entries']}`")
        lines.append(f"- patched report files: `{apply_result['patched_report_files']}`")
    lines.extend(["", "## Sample", ""])
    for item in plan["violations"][:30]:
        lines.append(
            f"- `{item['id']}` [{item['status']}] keywords={item['keywords']} :: {item['title']}"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill historical audience misclassification")
    parser.add_argument("--apply", action="store_true", help="Apply changes to feed/report JSON files")
    parser.add_argument(
        "--output-prefix",
        default="audience_backfill_latest",
        help="artifact prefix under storage/ops/",
    )
    args = parser.parse_args()

    feed = _load_json(FEED_PATH)
    if not isinstance(feed, list):
        raise SystemExit("feed.json is not a list")

    plan = build_backfill_plan(feed)
    apply_result = apply_backfill(feed, plan) if args.apply else None

    OPS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "summary": {
            "violations": plan["count"],
            "mode": "apply" if args.apply else "dry-run",
            **(apply_result or {}),
        },
        **plan,
    }
    json_path = OPS_DIR / f"{args.output_prefix}.json"
    md_path = OPS_DIR / f"{args.output_prefix}.md"
    _write_json(json_path, report)
    md_path.write_text(render_markdown(plan, apply_result), encoding="utf-8")

    print(f"[backfill_audience] mode={'apply' if args.apply else 'dry-run'}")
    print(f"[backfill_audience] violations={plan['count']}")
    if apply_result:
        print(f"[backfill_audience] patched_feed_entries={apply_result['patched_feed_entries']}")
        print(f"[backfill_audience] patched_report_files={apply_result['patched_report_files']}")
    print(f"[backfill_audience] report_json={json_path}")
    print(f"[backfill_audience] report_md={md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
