#!/usr/bin/env python3
"""
One-off: apply rewrite_complete to mile_d716099a.

Pattern matches storage/reports/feed.json mile_d70be85c (K237 rewrite, 2026-05-07):
  - Replace .content with new draft body (markdown)
  - Update .errata: action='rewrite_complete', add rewrite_at + rewrite_summary
  - Add .details.rewrite_at + .details.rewrite_reason
  - Append "errata" tag if absent

Also writes a single-article file storage/reports/mile_d716099a.json (parallel
source-of-truth that supabase_sync.py reads).
"""
from __future__ import annotations
import json, copy, sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "storage" / "reports" / "feed.json"
DRAFT = ROOT / "storage" / "drafts" / "mile_d716099a_rewrite_draft.md"
SINGLE = ROOT / "storage" / "reports" / "mile_d716099a.json"

NEW_CONTENT = DRAFT.read_text()
NOW_ISO = datetime.now(timezone.utc).isoformat()

# Use the markdown sanitizer (table escapes for |t|, etc.)
sys.path.insert(0, str(ROOT / "src"))
try:
    from volpred.publisher.markdown_table_sanitizer import sanitize_markdown_tables
    NEW_CONTENT_SAN, fixes = sanitize_markdown_tables(NEW_CONTENT)
    if fixes:
        print(f"[sanitizer] applied {len(fixes)} fixes:")
        for f in fixes:
            print(f"  {f}")
except Exception as e:
    print(f"[sanitizer] skipped: {e}")
    NEW_CONTENT_SAN = NEW_CONTENT

REWRITE_SUMMARY = (
    "各 number 已加 provenance（公司 IR / SEC 8-K / earnings call URL）；"
    "Meta capex prior range 從 $114-118B 修正為 $115-135B（CRITICAL fix）；"
    "$725B aggregate 改寫為 4 家公司自身 FY2026 guides 加總（不再說 from SEC 8-K）；"
    "MSFT +123% / Alphabet Cloud +63% / AWS +28% 等每個 % 均加 claim-level URL；"
    "新增第五節 ex-items NI 表給出 'earnings 縮水' 具體百分比 math；"
    "3 張新圖（capex guide range / NI vs capex / AI growth bar）含 source 標註。"
)

NEW_ERRATA_FIELDS = {
    "rewrite_at": NOW_ISO,
    "verdict": "rewrite_complete",
    "action": "rewrite_complete",
    "rewrite_summary": REWRITE_SUMMARY,
    "rewrite_critical_fix": "Meta FY2026 capex prior range 114-118B -> 115-135B (per investor.atmeta.com Q1 2026 press release).",
    "rewrite_major_fixes": [
        "$725B re-attributed: 4 hyperscalers self-disclosed FY2026 guides sum (Meta 145 + MSFT 190 + GOOGL 190 + AMZN 200), not SEC 8-K aggregate.",
        "MSFT AI +123% claim now cites news.microsoft.com 2026-04-29 (Nadella earnings call AI run-rate $37B).",
        "Alphabet Cloud +63% claim now cites Q1 2026 release PDF + SEC 8-K Ex-99.1.",
        "Section 5 added: per-company GAAP NI -> ex-items NI math (Meta -30.2%, Amazon -45 to -57%, Alphabet -55 to -62%).",
    ],
}

DETAILS_UPDATE = {
    "rewrite_at": NOW_ISO,
    "rewrite_reason": (
        "Codex paper review 2026-05-07 FAIL (1 CRITICAL Meta capex prior range + 4 MAJOR provenance issues). "
        "Re-sourced all numbers to official Q1 2026 press releases / SEC 8-K filings. "
        "Added per-company net income vs capex math + 3 charts."
    ),
    "experiment_refs_extra": ["mag7_q1_2026_followup"],
}

# ── Load feed ──
print(f"[load] {FEED}")
feed = json.loads(FEED.read_text())

found_idx = None
for i, art in enumerate(feed):
    if art.get("id") == "mile_d716099a":
        found_idx = i
        break
if found_idx is None:
    print("ERROR: mile_d716099a not found in feed.json", file=sys.stderr)
    sys.exit(1)

art = feed[found_idx]
old_len = len(art.get("content", ""))
print(f"[match] index={found_idx}, old content len={old_len}")

# Patch content
art["content"] = NEW_CONTENT_SAN

# Patch errata (preserve original FAIL fields, add rewrite_complete fields)
errata = art.setdefault("errata", {})
errata.update(NEW_ERRATA_FIELDS)

# Patch details
details = art.setdefault("details", {})
details.update({k: v for k, v in DETAILS_UPDATE.items() if k != "experiment_refs_extra"})
# Keep experiment_refs as-is; add the followup tag if missing
refs = details.setdefault("experiment_refs", [])
for r in DETAILS_UPDATE["experiment_refs_extra"]:
    if r not in refs:
        refs.append(r)

# Append errata tag if missing
tags = art.setdefault("tags", [])
if "errata" not in tags:
    tags.append("errata")
if "研究誠實" not in tags:
    tags.append("研究誠實")

# Write back
print(f"[write] new content len={len(NEW_CONTENT_SAN)}")
FEED.write_text(json.dumps(feed, ensure_ascii=False, indent=2))
print(f"[done] feed.json patched")

# Also write single-article file
single_doc = copy.deepcopy(art)
SINGLE.write_text(json.dumps(single_doc, ensure_ascii=False, indent=2))
print(f"[done] single-article file written: {SINGLE}")
