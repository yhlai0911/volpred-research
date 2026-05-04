"""Publish a markdown draft from storage/drafts/ via volpred ops publish-milestone.

Background: agent-written drafts go to storage/drafts/<kid>_<audience>_draft.md
with YAML frontmatter; main thread runs this helper to sanitize banned terms,
extract metadata, and invoke the publisher CLI. Replaces the per-publish
Python heredoc that we wrote 3+ times manually.

Sanitizer covers the publisher.py L46-52 strict-audit ban list for
audience=general so that agents that "almost" complied still publish cleanly:

  - p=N        → 達顯著水準（p≈N）
  - p<N        → 達顯著水準（p<N）
  - t=N        → 統計強度 N
  - t-stat     → 統計強度
  - \\|t\\|    → 統計強度
  - Harvey     → 嚴格統計
  - Diebold-Mariano (test) → 兩模型比較顯著
  - DM test    → 比較檢定

Sanitizer is NOT applied to audience=research (those terms are required for
academic readers per .claude/skills/feed-publisher/SKILL.md).

Usage:
  uv run python scripts/publish_draft.py storage/drafts/k1033_general_draft.md \\
      --phase robustness --tags 'garch,refit,robustness,paper-9' --kid K1033

Optional flags:
  --status (default draft) | published | scheduled
  --audience (default from frontmatter) | general | research | daily
  --dry-run  print what would be published, do not call CLI
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GENERAL_BAN_REPLACEMENTS = [
    (re.compile(r'\bp\s*=\s*(\d[\d.]*)'), r'達顯著水準（p≈\1）'),
    (re.compile(r'\bp\s*<\s*(\d[\d.]*)'), r'達顯著水準（p<\1）'),
    (re.compile(r'\bt\s*=\s*(-?\d[\d.]*)'), r'統計強度 \1'),
    (re.compile(r'\bHarvey\s+threshold\b'), r'嚴格統計檢驗門檻'),
    (re.compile(r'\bHarvey\b'), r'嚴格統計'),
    (re.compile(r'\bDiebold-Mariano(?:\s+test)?\b'), r'兩模型比較顯著'),
    (re.compile(r'\bDM\s*test\b', re.IGNORECASE), r'比較檢定'),
    (re.compile(r'\\\|t\\\|', re.IGNORECASE), r'統計強度'),
    (re.compile(r'\bt-stat\b', re.IGNORECASE), r'統計強度'),
]


def sanitize_general(text: str) -> tuple[str, list[str]]:
    """Apply general-audience ban-list replacements. Return (text, applied_rules)."""
    applied = []
    for pat, rep in GENERAL_BAN_REPLACEMENTS:
        new = pat.sub(rep, text)
        if new != text:
            applied.append(pat.pattern)
            text = new
    return text, applied


def parse_draft(path: Path) -> dict:
    """Extract frontmatter + body from a markdown draft."""
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not m:
        raise SystemExit(f"error: no YAML frontmatter in {path}")
    fm_block, body = m.group(1), m.group(2).lstrip()

    # Manual two-pass YAML parse: scalar `key: value` pairs + multi-line
    # list form `key:\n  - item1\n  - item2`. PyYAML would be cleaner but
    # we keep the script dependency-light.
    fm: dict[str, object] = {}
    lines = fm_block.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            key = k.strip()
            val = v.strip().strip('"').strip("'")
            if val:
                fm[key] = val
                i += 1
                continue
            # Empty value → look ahead for `  - item` lines
            collected: list[str] = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j]
                stripped = nxt.lstrip()
                if stripped.startswith("- "):
                    collected.append(stripped[2:].strip().strip('"').strip("'"))
                    j += 1
                elif not nxt.strip():
                    j += 1
                else:
                    break
            if collected:
                fm[key] = collected
            i = j
        else:
            i += 1

    def _list_from(field: str) -> list[str]:
        v = fm.get(field, [])
        if isinstance(v, list):
            return v
        # Inline form: "[a, b, c]"
        s = str(v).strip().strip("[]")
        return [t.strip().strip('"').strip("'") for t in s.split(",") if t.strip()]

    tags = _list_from("tags")
    # Drop any K-id tags — publisher auto-extracts to details.experiment_refs
    tags = [t for t in tags if not re.match(r"^K\d", t)]
    refs = _list_from("experiment_refs")

    return {
        "title": fm.get("title", "").strip('"').strip("'"),
        "audience": fm.get("audience", "general"),
        "status_default": fm.get("status", "draft"),
        "tags": tags[:8],  # publisher cap
        "experiment_refs": refs,
        "body": body,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft_path", help="path to markdown draft (relative or absolute)")
    parser.add_argument("--phase", required=True, help="research phase tag (e.g. robustness, tail-risk)")
    parser.add_argument("--audience", default=None, help="override frontmatter audience")
    parser.add_argument("--status", default=None,
                        choices=["draft", "published", "scheduled"],
                        help="override frontmatter status")
    parser.add_argument("--tags", default=None,
                        help="comma-separated; overrides frontmatter tags entirely")
    parser.add_argument("--kid", default=None,
                        help="K-id for experiment_refs; overrides frontmatter")
    parser.add_argument("--no-sanitize", action="store_true",
                        help="skip ban-list sanitizer (default applies for audience=general)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print metadata + sanitize report; do not invoke CLI")
    args = parser.parse_args()

    draft_path = Path(args.draft_path)
    if not draft_path.is_absolute():
        draft_path = ROOT / draft_path
    if not draft_path.exists():
        print(f"error: draft not found: {draft_path}", file=sys.stderr)
        return 1

    info = parse_draft(draft_path)
    audience = args.audience or info["audience"]
    status = args.status or info["status_default"]
    tags = args.tags or ",".join(info["tags"])
    refs = [args.kid] if args.kid else info["experiment_refs"]

    body = info["body"]
    applied = []
    if audience == "general" and not args.no_sanitize:
        body, applied = sanitize_general(body)

    print(f"[publish_draft] file={draft_path.relative_to(ROOT)}")
    print(f"[publish_draft] title={info['title'][:80]}")
    print(f"[publish_draft] audience={audience} status={status} phase={args.phase}")
    print(f"[publish_draft] tags={tags}")
    print(f"[publish_draft] experiment_refs={refs}")
    print(f"[publish_draft] body_chars={len(body)}  sanitize_applied={len(applied)}")
    if applied:
        for p in applied:
            print(f"  - replaced pattern: {p}")

    if args.dry_run:
        print("[publish_draft] dry-run: not invoking CLI")
        return 0

    cmd = [
        "uv", "run", "volpred", "ops", "publish-milestone",
        "--title", info["title"],
        "--description", body,
        "--phase", args.phase,
        "--audience", audience,
        "--status", status,
        "--tags", tags,
        "--details-json", json.dumps({"experiment_refs": refs}),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"\n[publish_draft] rc={result.returncode}")
    if result.stdout:
        print(f"[publish_draft] stdout: {result.stdout[-400:]}")
    if result.returncode != 0 and result.stderr:
        print(f"[publish_draft] stderr: {result.stderr[-700:]}", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
