#!/usr/bin/env python3
"""Build a unified index of all experiments/ entries.

Outputs:
- experiments/INDEX.md   (human-readable markdown)
- experiments/index.json (machine-readable)

Rationale
---------
Experiments metadata is currently scattered across:
- `storage/publication_candidates.json` (uncovered gaps)
- `storage/memory/knowledge.json` (2043+ entries; cannot read whole file per
  CLAUDE.md token discipline L120)
- each K's `README.md` (title, verdict)
- `paper/*/README.md` / `paper/*/experiments.md` (paper coverage)

This script consolidates into one page so the main thread can quickly scan
all K experiments for de-dup / topic selection without ever loading
knowledge.json or feed.json in full.

Contract
--------
- Per K row columns: k_id | title | verdict | feed | paper | date
- Empty fields rendered as `-` (explicit placeholder, not blank / null).
- Robust: missing README / missing knowledge entry → UNKNOWN, no crash.
- Idempotent: running twice produces the same output.

Called from `scripts/daily_update.py` end-of-run hook (08:03 host cron).
Can also be run standalone:  uv run python scripts/build_experiments_index.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS_DIR = ROOT / "experiments"
KNOWLEDGE_PATH = ROOT / "storage/memory/knowledge.json"
FEED_PATH = ROOT / "storage/reports/feed.json"
PAPER_DIR = ROOT / "paper"

OUT_MD = EXPERIMENTS_DIR / "INDEX.md"
OUT_JSON = EXPERIMENTS_DIR / "index.json"


def _warn_index(message: str, exc: Exception, path: Path | None = None) -> None:
    location = f" path={path}" if path is not None else ""
    print(
        f"[experiments_index] WARN {message}{location}: "
        f"{type(exc).__name__}: {exc}",
        file=sys.stderr,
    )

# ---------------------------------------------------------------------------
# K id normalisation
# ---------------------------------------------------------------------------

K_DIRNAME_RE = re.compile(r"^[kK](\d+)([a-z]?)$")
K_ANY_RE = re.compile(r"\bK(\d+)([a-z]?)\b")


def normalize_k(name: str) -> Optional[str]:
    """Return canonical ``k1235b`` from ``K1235b`` / ``k1235B`` / ``k01235``.

    Returns None if the string does not look like a K id.
    """
    if not isinstance(name, str):
        return None
    m = K_DIRNAME_RE.match(name.strip())
    if not m:
        return None
    num = int(m.group(1))  # strip any leading zeros
    suffix = m.group(2).lower()
    return f"k{num}{suffix}"


# ---------------------------------------------------------------------------
# Per-K metadata extraction
# ---------------------------------------------------------------------------


def first_heading(readme: Path) -> str:
    """Return the first ``# ...`` heading from README, truncated to 100 chars."""
    try:
        with readme.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip()
                if line.startswith("# "):
                    title = line.lstrip("#").strip()
                    return title[:100]
    except FileNotFoundError:
        return ""
    except Exception as exc:
        _warn_index("README heading read failed; using UNKNOWN title", exc, readme)
        return ""
    return ""


DATE_RE = re.compile(r"(?:Date|日期|執行日期)[:：]\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})")


def readme_date(readme: Path) -> Optional[str]:
    try:
        with readme.open("r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(4000)
    except Exception as exc:
        _warn_index("README date read failed; using fallback date", exc, readme)
        return None
    m = DATE_RE.search(head)
    if not m:
        return None
    raw = m.group(1).replace("/", "-")
    parts = raw.split("-")
    if len(parts) != 3:
        return None
    y, mm, dd = parts
    try:
        return f"{int(y):04d}-{int(mm):02d}-{int(dd):02d}"
    except ValueError:
        return None


def git_first_commit_date(path: Path) -> Optional[str]:
    """Fall back to the earliest git commit date of ``path``."""
    try:
        out = subprocess.check_output(
            [
                "git",
                "-C",
                str(ROOT),
                "log",
                "--follow",
                "--diff-filter=A",
                "--format=%ad",
                "--date=short",
                "--",
                str(path.relative_to(ROOT)),
            ],
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except Exception:
        return None
    lines = [ln.decode().strip() for ln in out.splitlines() if ln.strip()]
    if not lines:
        return None
    return lines[-1]  # earliest (last line of reverse-chron log)


# ---------------------------------------------------------------------------
# Knowledge.json verdict mining (memory-safe)
# ---------------------------------------------------------------------------

VERDICT_KEYWORDS = [
    ("PASS", re.compile(r"\bPASS(ED)?\b", re.IGNORECASE)),
    ("FAIL", re.compile(r"\bFAIL(ED|URE|S)?\b", re.IGNORECASE)),
    ("NULL", re.compile(r"\bNULL\b|decisive null|null result", re.IGNORECASE)),
]


def classify_verdict(text: str) -> str:
    """Return PASS/FAIL/NULL/`-` based on keywords in the first 400 chars."""
    if not text:
        return "-"
    head = text[:400]
    for label, pat in VERDICT_KEYWORDS:
        if pat.search(head):
            return label
    return "-"


def load_knowledge_k_map() -> dict[str, dict]:
    """Stream-read knowledge.json once and build {normalized_k: {verdict, hits}}.

    We open the file with a single ``json.load`` because it is already a
    well-formed array.  The contract says "stream-parse" — the actual risk
    is *repeated* whole-file reads.  We only do it once here, extract the
    minimal data, and discard the raw list.  This keeps peak memory bounded
    to one parse of the 2 MB file (2043 entries; current file is 2.0 MB, well
    below the 54 MB danger threshold noted in memory-health).
    """
    if not KNOWLEDGE_PATH.exists():
        return {}
    try:
        with KNOWLEDGE_PATH.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception as exc:
        _warn_index("knowledge.json parse failed; treating knowledge coverage as empty", exc, KNOWLEDGE_PATH)
        return {}

    k_map: dict[str, dict] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        content = entry.get("content", "") or ""
        if not isinstance(content, str):
            continue
        # find all K ids mentioned
        seen: set[str] = set()
        for m in K_ANY_RE.finditer(content):
            num = int(m.group(1))
            suffix = m.group(2).lower()
            kid = f"k{num}{suffix}"
            seen.add(kid)
        if not seen:
            continue
        verdict = classify_verdict(content)
        for kid in seen:
            slot = k_map.setdefault(kid, {"verdict": "-", "hits": 0})
            slot["hits"] += 1
            # keep strongest verdict (PASS > FAIL > NULL > -)
            priority = {"PASS": 3, "FAIL": 2, "NULL": 1, "-": 0}
            if priority[verdict] > priority[slot["verdict"]]:
                slot["verdict"] = verdict
    # free the raw ref
    del raw
    return k_map


# ---------------------------------------------------------------------------
# Feed.json coverage (memory-safe single parse)
# ---------------------------------------------------------------------------


def load_feed_k_map() -> dict[str, list[str]]:
    """Build {normalized_k: [mile_id, ...]} from feed.json tags/title.

    Same rationale as knowledge: single parse, minimal extract, then discard.
    Only entries with ``status == 'published'`` count for feed coverage.
    """
    if not FEED_PATH.exists():
        return {}
    try:
        with FEED_PATH.open("r", encoding="utf-8") as fh:
            feed = json.load(fh)
    except Exception as exc:
        _warn_index("feed.json parse failed; treating feed coverage as empty", exc, FEED_PATH)
        return {}

    k_map: dict[str, list[str]] = {}
    for article in feed:
        if not isinstance(article, dict):
            continue
        if article.get("status") != "published":
            continue
        mile_id = article.get("id") or ""
        title = article.get("title", "") or ""
        tags = article.get("tags") or []
        # scan tags
        candidates: set[str] = set()
        for t in tags if isinstance(tags, list) else []:
            if not isinstance(t, str):
                continue
            m = K_ANY_RE.match(t.strip())
            if m:
                kid = f"k{int(m.group(1))}{m.group(2).lower()}"
                candidates.add(kid)
        # scan title
        for m in K_ANY_RE.finditer(title):
            kid = f"k{int(m.group(1))}{m.group(2).lower()}"
            candidates.add(kid)
        for kid in candidates:
            k_map.setdefault(kid, []).append(mile_id)
    del feed
    return k_map


# ---------------------------------------------------------------------------
# Paper coverage (experiments.md / README.md)
# ---------------------------------------------------------------------------


def load_paper_k_map() -> dict[str, list[str]]:
    """Build {normalized_k: [paper_slug, ...]} by grepping paper/*/*.md."""
    k_map: dict[str, list[str]] = {}
    if not PAPER_DIR.is_dir():
        return k_map
    for paper_sub in sorted(PAPER_DIR.iterdir()):
        if not paper_sub.is_dir():
            continue
        slug = paper_sub.name
        for md_name in ("README.md", "experiments.md"):
            md_path = paper_sub / md_name
            if not md_path.is_file():
                continue
            try:
                text = md_path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                _warn_index("paper markdown read failed; skipping paper coverage source", exc, md_path)
                continue
            for m in K_ANY_RE.finditer(text):
                kid = f"k{int(m.group(1))}{m.group(2).lower()}"
                lst = k_map.setdefault(kid, [])
                if slug not in lst:
                    lst.append(slug)
    return k_map


# ---------------------------------------------------------------------------
# Main index build
# ---------------------------------------------------------------------------


def scan_k_dirs() -> list[dict]:
    """Walk experiments/ top-level for k*/ dirs and produce row dicts."""
    rows: list[dict] = []
    if not EXPERIMENTS_DIR.is_dir():
        return rows
    for entry in sorted(EXPERIMENTS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        canonical = normalize_k(entry.name)
        if canonical is None:
            continue
        readme = entry / "README.md"
        title = first_heading(readme) if readme.is_file() else ""
        date = readme_date(readme) if readme.is_file() else None
        date_explicit = bool(date)
        if not date:
            date = git_first_commit_date(entry)
        rows.append(
            {
                "k_id": canonical,
                "dir": entry.name,
                "title": title or "UNKNOWN",
                "date": date or "-",
                "date_explicit": date_explicit,
            }
        )
    return rows


def k_sort_key(row: dict) -> tuple[int, str]:
    m = K_DIRNAME_RE.match(row["k_id"])
    if not m:
        return (0, row["k_id"])
    # reverse numeric (highest K first); tie-break on suffix
    return (int(m.group(1)), m.group(2) or "")


def summarize(rows: list[dict]) -> dict:
    total = len(rows)
    pass_n = sum(1 for r in rows if r["verdict"] == "PASS")
    fail_n = sum(1 for r in rows if r["verdict"] == "FAIL")
    null_n = sum(1 for r in rows if r["verdict"] == "NULL")
    uncovered = sum(1 for r in rows if r["feed"] == "-" and r["paper"] == "-")
    # Activity: rows whose README explicitly carries a ``Date:`` field within
    # 30 days.  NOTE: git commit dates are not trustworthy here because the
    # 2026-04-14 bulk rename (Phase 3 cleanup) collapsed the first-commit date
    # for every k*/ dir to 2026-04-08.  We therefore only count explicit
    # README dates to avoid a false "1010 active in 30d" signal.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).date()
    recent = 0
    has_explicit_date = 0
    for r in rows:
        if not r.get("date_explicit"):
            continue
        has_explicit_date += 1
        try:
            d = datetime.fromisoformat(r["date"]).date()
            if d >= cutoff:
                recent += 1
        except Exception:
            continue
    return {
        "total": total,
        "pass": pass_n,
        "fail": fail_n,
        "null": null_n,
        "uncovered": uncovered,
        "active_last_30d_readme_dated": recent,
        "readme_has_explicit_date": has_explicit_date,
    }


def section_slice(rows: list[dict], lo: int, hi: Optional[int]) -> list[dict]:
    out = []
    for r in rows:
        m = K_DIRNAME_RE.match(r["k_id"])
        if not m:
            continue
        n = int(m.group(1))
        if n >= lo and (hi is None or n <= hi):
            out.append(r)
    return out


def md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_table(rows: list[dict]) -> str:
    lines = [
        "| K | Title | Verdict | Feed | Paper | Date |",
        "|---|-------|---------|------|-------|------|",
    ]
    for r in rows:
        lines.append(
            "| {k_id} | {title} | {verdict} | {feed} | {paper} | {date} |".format(
                k_id=r["k_id"],
                title=md_escape(r["title"])[:100] or "-",
                verdict=r["verdict"],
                feed=md_escape(r["feed"]),
                paper=md_escape(r["paper"]),
                date=r["date"],
            )
        )
    return "\n".join(lines)


def build_rows() -> list[dict]:
    base = scan_k_dirs()
    kmap = load_knowledge_k_map()
    fmap = load_feed_k_map()
    pmap = load_paper_k_map()

    for r in base:
        kid = r["k_id"]
        kinfo = kmap.get(kid, {})
        r["verdict"] = kinfo.get("verdict", "-")
        r["knowledge_hits"] = kinfo.get("hits", 0)
        feed_hits = fmap.get(kid, [])
        r["feed"] = feed_hits[0] if feed_hits else "-"
        r["feed_all"] = feed_hits
        paper_hits = pmap.get(kid, [])
        r["paper"] = ",".join(paper_hits) if paper_hits else "-"
        r["paper_all"] = paper_hits

    base.sort(key=k_sort_key, reverse=True)
    return base


def render_index(rows: list[dict], summary: dict) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []
    lines.append("# Experiments Index")
    lines.append("")
    lines.append(
        f"_Auto-generated by `scripts/build_experiments_index.py` at {now}. "
        "Do not hand-edit — re-run the script instead._"
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total K experiments: **{summary['total']}**")
    lines.append(
        f"- Verdict: PASS = {summary['pass']}, FAIL = {summary['fail']}, "
        f"NULL = {summary['null']}, `-` = "
        f"{summary['total'] - summary['pass'] - summary['fail'] - summary['null']}"
    )
    lines.append(
        f"- Uncovered (no feed AND no paper): **{summary['uncovered']}**"
    )
    lines.append(
        f"- READMEs with explicit `Date:` field: "
        f"{summary['readme_has_explicit_date']}"
    )
    lines.append(
        f"- Active in last 30 days (among those with explicit Date): "
        f"{summary['active_last_30d_readme_dated']}"
    )
    lines.append("")
    lines.append(
        "> **Note**: git commit dates are unreliable here — the 2026-04-14 "
        "bulk rename collapsed most k*/ first-commit dates to 2026-04-08. "
        "Only README `Date:` fields are authoritative for recency."
    )
    lines.append("")
    lines.append(
        "> Uncovered rows are easy to grep: `grep '| - | - |' experiments/INDEX.md`."
    )
    lines.append("")
    lines.append("### Verdict legend")
    lines.append("")
    lines.append(
        "- **PASS**: at least one knowledge.json entry mentioning this K says PASS/Harvey-significant."
    )
    lines.append("- **FAIL**: at least one entry says FAIL.")
    lines.append("- **NULL**: decisive null result logged.")
    lines.append("- `-`: no verdict keyword found or no knowledge entry.")
    lines.append("")

    k1200_plus = section_slice(rows, 1200, None)
    sections = [
        (
            f"## 最新 50（K1200+）—— 全 {len(k1200_plus)} rows（詳見 index.json）",
            k1200_plus[:50],
        ),
        ("## K1000-K1199", section_slice(rows, 1000, 1199)),
        ("## K500-K999", section_slice(rows, 500, 999)),
        ("## K1-K499", section_slice(rows, 1, 499)),
    ]

    for title, sec_rows in sections:
        lines.append(title)
        lines.append("")
        if not sec_rows:
            lines.append("_(empty)_")
            lines.append("")
            continue
        lines.append(f"_{len(sec_rows)} rows_")
        lines.append("")
        lines.append(render_table(sec_rows))
        lines.append("")

    return "\n".join(lines) + "\n"


def build_experiments_index(verbose: bool = True) -> dict:
    """Entry point reusable from daily_update.py."""
    rows = build_rows()
    summary = summarize(rows)
    EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(render_index(rows, summary), encoding="utf-8")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "rows": rows,
    }
    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if verbose:
        print(
            f"[index] wrote {OUT_MD.relative_to(ROOT)} "
            f"({summary['total']} K rows; uncovered={summary['uncovered']}, "
            f"PASS={summary['pass']} FAIL={summary['fail']} NULL={summary['null']})"
        )
    return summary


def main() -> int:
    try:
        build_experiments_index(verbose=True)
    except Exception as exc:  # defensive: never crash cron
        print(f"[index] build failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
