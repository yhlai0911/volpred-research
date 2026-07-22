#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "storage" / "ops"
FEED_PATH = ROOT / "storage" / "reports" / "feed.json"
sys.path.insert(0, str(ROOT / "src"))

from volpred.ops.content_actuator_audits import (  # noqa: E402
    build_audience_report as _actuated_build_report,
    render_audience_markdown as _actuated_render_markdown,
    score_item as _actuated_score_item,
)


# One decision owner: keep this CLI as the report writer while the hourly
# content-quality alert chain consumes the exact same scoring functions.
def score_item(item: dict) -> dict:
    return _actuated_score_item(item, repo_root=ROOT)


def build_report(feed: list[dict]) -> dict:
    return _actuated_build_report(
        feed, repo_root=ROOT, source_feed=str(FEED_PATH.relative_to(ROOT))
    )


render_markdown = _actuated_render_markdown


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit feed audience misclassification")
    parser.add_argument("--output-prefix", default="audience_audit_latest", help="report prefix under storage/ops/")
    args = parser.parse_args()

    feed = json.loads(FEED_PATH.read_text())
    report = build_report(feed)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORT_DIR / f"{args.output_prefix}.json"
    md_path = REPORT_DIR / f"{args.output_prefix}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    md_path.write_text(render_markdown(report) + "\n")

    print(f"[audience_audit] report_json={json_path}")
    print(f"[audience_audit] report_md={md_path}")
    print(f"[audience_audit] summary={report['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
