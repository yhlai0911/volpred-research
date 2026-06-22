"""Build feed index — human-readable INDEX.md + machine-readable index.json.

Motivation:
    `storage/reports/feed.json` is large (900+ articles, ~7MB) and is
    forbidden from full Python load (see .claude/rules/context-hygiene.md).
    This script uses `jq` to stream only the metadata we need, then writes:

        storage/reports/INDEX.md    (markdown, human browsing)
        storage/reports/index.json  (structured, machine/jq queryable)

Fields per article:
    id, date (published_at | created_at), title, audience, category, status,
    tags (list[str]), length_chars (content), thumbnail_url (details.chart_url).

Usage:
    uv run python scripts/build_feed_index.py

Idempotent: re-running overwrites outputs cleanly.

Hook: invoked from scripts/daily_update.py tail so host cron (08:03) rebuilds
the index daily.
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent
FEED_PATH = ROOT / "storage" / "reports" / "feed.json"
OUT_MD = ROOT / "storage" / "reports" / "INDEX.md"
OUT_JSON = ROOT / "storage" / "reports" / "index.json"

# jq program: emit one compact JSON per article with just the metadata we need.
# Handles `details` being null, object (with chart_url), or string.
JQ_PROGRAM = r"""
.[] | {
  id: .id,
  title: .title,
  date: (.published_at // .created_at),
  audience: .audience,
  category: .category,
  status: .status,
  tags: (.tags // []),
  length_chars: ((.content // "") | length),
  thumbnail_url: (
    if (.details | type) == "object" then (.details.chart_url // null)
    else null end
  )
}
"""


def _jq_stream() -> list[dict[str, Any]]:
    """Invoke jq on feed.json and return list of metadata dicts.

    Uses -c (compact) to keep memory small; we still collect all records, but
    each is ~300 bytes of metadata rather than full content (~10KB).
    """
    if not FEED_PATH.exists():
        print(f"[feed-index] feed.json not found at {FEED_PATH}", file=sys.stderr)
        return []
    try:
        proc = subprocess.run(
            ["jq", "-c", JQ_PROGRAM, str(FEED_PATH)],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("[feed-index] jq binary not found — install jq to build feed index",
              file=sys.stderr)
        return []
    except subprocess.CalledProcessError as e:
        print(f"[feed-index] jq failed: {e.stderr[:400]}", file=sys.stderr)
        return []

    records: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(
                "[feed-index] WARN jq output JSON line parse failed; skipping "
                f"line={line[:200]!r} error={type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            continue
    return records


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        # Accept both with and without timezone; normalize to UTC.
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _quarter_label(dt: datetime) -> str:
    q = (dt.month - 1) // 3 + 1
    return f"{dt.year}-Q{q}"


def _bucket(records: list[dict[str, Any]], now: datetime) -> dict[str, list[dict[str, Any]]]:
    """Group records into Recent-30d / quarterly buckets."""
    cutoff_30 = now - timedelta(days=30)
    buckets: dict[str, list[dict[str, Any]]] = {"最近 30 天": []}
    for rec in records:
        dt = _parse_date(rec.get("date"))
        if dt is None:
            buckets.setdefault("日期缺失", []).append(rec)
            continue
        if dt >= cutoff_30:
            buckets["最近 30 天"].append(rec)
        else:
            buckets.setdefault(_quarter_label(dt), []).append(rec)
    return buckets


def _sort_bucket_keys(keys: list[str]) -> list[str]:
    """Order: 最近 30 天 first, quarters desc, date-missing last."""

    def rank(k: str) -> tuple[int, str]:
        if k == "最近 30 天":
            return (0, "")
        if k == "日期缺失":
            return (2, "")
        # quarter label like 2026-Q1 → sort by year desc then quarter desc
        try:
            year, q = k.split("-Q")
            return (1, f"{9999 - int(year):04d}-Q{9 - int(q)}")
        except ValueError:
            return (1, k)

    return sorted(keys, key=rank)


def _safe_title(t: str | None) -> str:
    if not t:
        return ""
    # Strip pipes so Markdown tables don't break.
    return t.replace("|", "/").strip()


def _fmt_row(rec: dict[str, Any]) -> str:
    dt = _parse_date(rec.get("date"))
    date_str = dt.strftime("%Y-%m-%d") if dt else "?"
    tags = rec.get("tags") or []
    tags_str = ", ".join(tags[:6])  # cap display
    thumb = "Y" if rec.get("thumbnail_url") else ""
    audience = rec.get("audience") or "-"
    category = rec.get("category") or "-"
    status = rec.get("status") or "-"
    length = rec.get("length_chars") or 0
    title = _safe_title(rec.get("title"))
    rid = rec.get("id") or ""
    return (
        f"| {date_str} | `{rid}` | {title} | {audience} | {category} | "
        f"{status} | {length} | {thumb} | {tags_str} |"
    )


MD_TABLE_HEADER = (
    "| 日期 | id | 標題 | audience | category | status | 字數 | 縮圖 | tags |\n"
    "|---|---|---|---|---|---|---|---|---|"
)


def _build_summary(records: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    status_ctr: Counter[str] = Counter()
    audience_ctr: Counter[str] = Counter()
    category_ctr: Counter[str] = Counter()
    last30 = 0
    cutoff_30 = now - timedelta(days=30)
    total_len = 0
    with_thumb = 0
    for rec in records:
        status_ctr[rec.get("status") or "unknown"] += 1
        audience_ctr[rec.get("audience") or "unknown"] += 1
        category_ctr[rec.get("category") or "unknown"] += 1
        if rec.get("thumbnail_url"):
            with_thumb += 1
        total_len += rec.get("length_chars") or 0
        dt = _parse_date(rec.get("date"))
        if dt and dt >= cutoff_30:
            last30 += 1
    return {
        "total": len(records),
        "last_30_days": last30,
        "status": dict(status_ctr.most_common()),
        "audience": dict(audience_ctr.most_common()),
        "category": dict(category_ctr.most_common()),
        "with_thumbnail": with_thumb,
        "total_chars": total_len,
    }


def _build_markdown(records: list[dict[str, Any]], summary: dict[str, Any], now: datetime) -> str:
    lines: list[str] = []
    lines.append(f"# Feed Index")
    lines.append("")
    lines.append(
        f"_Last built: {now.strftime('%Y-%m-%d %H:%M UTC')} — "
        f"source: `storage/reports/feed.json` (do NOT read full; use this index)_"
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total articles: **{summary['total']}**  (with thumbnail: {summary['with_thumbnail']})")
    lines.append(f"- Last 30 days: **{summary['last_30_days']}**")
    lines.append(f"- Total chars (content): {summary['total_chars']:,}")
    lines.append("")
    lines.append("**Status**: " + ", ".join(f"{k}={v}" for k, v in summary["status"].items()))
    lines.append("")
    lines.append("**Audience**: " + ", ".join(f"{k}={v}" for k, v in summary["audience"].items()))
    lines.append("")
    lines.append("**Category**: " + ", ".join(f"{k}={v}" for k, v in summary["category"].items()))
    lines.append("")

    buckets = _bucket(records, now)

    # Sort inside each bucket by date desc.
    def sort_key(r: dict[str, Any]) -> str:
        return r.get("date") or ""

    for b in buckets.values():
        b.sort(key=sort_key, reverse=True)

    ordered = _sort_bucket_keys(list(buckets.keys()))
    for idx, key in enumerate(ordered):
        bucket = buckets[key]
        if not bucket:
            continue
        # Collapse older quarters via <details>.
        collapsed = key not in {"最近 30 天"}
        count = len(bucket)
        if collapsed:
            lines.append(f"<details><summary>## {key} ({count})</summary>")
            lines.append("")
        else:
            lines.append(f"## {key} ({count})")
            lines.append("")
        lines.append(MD_TABLE_HEADER)
        for rec in bucket:
            lines.append(_fmt_row(rec))
        lines.append("")
        if collapsed:
            lines.append("</details>")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "_Generated by `scripts/build_feed_index.py`; triggered daily from "
        "`scripts/daily_update.py`. Re-run manually: "
        "`uv run python scripts/build_feed_index.py`._"
    )
    return "\n".join(lines) + "\n"


def build_feed_index() -> dict[str, Any]:
    """Entry point — safe to call from daily_update.main(). Never raises."""
    try:
        records = _jq_stream()
        if not records:
            print("[feed-index] no records — skip write", file=sys.stderr)
            return {"total": 0}

        # Sort all records date desc for the JSON output.
        records.sort(key=lambda r: r.get("date") or "", reverse=True)

        now = datetime.now(timezone.utc)
        summary = _build_summary(records, now)

        payload = {
            "generated_at": now.isoformat(),
            "source": str(FEED_PATH.relative_to(ROOT)),
            "summary": summary,
            "articles": records,
        }
        OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

        md = _build_markdown(records, summary, now)
        OUT_MD.write_text(md)

        print(
            f"[feed-index] wrote {OUT_MD.name} + {OUT_JSON.name} "
            f"({summary['total']} articles, last30={summary['last_30_days']})"
        )
        return summary
    except Exception as e:  # noqa: BLE001
        print(f"[feed-index] build failed: {e}", file=sys.stderr)
        return {"error": str(e)}


if __name__ == "__main__":
    build_feed_index()
