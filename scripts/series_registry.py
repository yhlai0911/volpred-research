#!/usr/bin/env python3
"""Article-series registry audit + apply — enforcement for config/article_series.json.

The registry (config/article_series.json) is the SINGLE SOURCE OF TRUTH for
reader-facing article series. This tool makes series branding mechanical instead
of hand-retitled (which caused the 2026-07-06 迷思實驗室 4-mistake incident):

  --audit  (default) : report drift — registered members missing their prefix,
                       members with the wrong status, orphan-branded articles
                       (carry a series prefix but aren't registered), digest
                       titles that wrongly start with the masthead name, and
                       excluded dups that aren't 'unpublished'. Exit 1 if drift.
  --apply            : idempotently prepend each title_prefix series' prefix to
                       its registered members (published + draft) that lack it,
                       and keep matching reports/<id>.json in sync. Byte-exact
                       indent=2 round-trip on feed.json.

Ground-truth rule: membership + status are read from the registry + feed.json,
never inferred from titles or published_at.

Usage:
  uv run python scripts/series_registry.py            # audit
  uv run python scripts/series_registry.py --apply    # apply branding
  uv run python scripts/series_registry.py --json      # machine-readable audit
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "config" / "article_series.json"
FEED = ROOT / "storage" / "reports" / "feed.json"
REPORTS = ROOT / "storage" / "reports"


def _load_registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8")).get("series", {})


def _load_feed() -> list:
    return json.loads(FEED.read_text(encoding="utf-8"))


def audit(series: dict, feed: list) -> list[dict]:
    """Return a list of drift findings (empty = clean)."""
    by_id = {a.get("id"): a for a in feed}
    prefixed_series = {  # prefix -> series_key (title_prefix series only)
        s["prefix"]: k for k, s in series.items()
        if s.get("branding") == "title_prefix" and s.get("prefix")
    }
    findings: list[dict] = []

    for key, s in series.items():
        branding = s.get("branding")

        if branding == "title_prefix":
            prefix = s.get("prefix") or ""
            # 1. explicit members must carry the prefix + have the expected status
            for status_field, ids in (("published", s.get("members_published", [])),
                                      ("draft", s.get("members_draft", []))):
                for aid in ids:
                    art = by_id.get(aid)
                    if art is None:
                        findings.append({"series": key, "id": aid, "kind": "member_missing", "detail": f"registered {status_field} member not in feed"})
                        continue
                    if not (art.get("title") or "").startswith(prefix):
                        findings.append({"series": key, "id": aid, "kind": "missing_prefix", "detail": f"member lacks prefix '{prefix}'"})
                    if art.get("status") != status_field:
                        findings.append({"series": key, "id": aid, "kind": "wrong_status", "detail": f"registry says {status_field}, feed says '{art.get('status')}'"})
            # 2. excluded dups must be unpublished
            for aid, why in (s.get("excluded_dups") or {}).items():
                art = by_id.get(aid)
                if art and art.get("status") not in ("unpublished", "archived", "retracted"):
                    findings.append({"series": key, "id": aid, "kind": "dup_still_visible", "detail": f"excluded dup status='{art.get('status')}' (want unpublished): {why}"})

        elif branding == "frontend_masthead":
            # digest-style: titles MUST NOT start with the masthead name
            bad_prefix = f"{s.get('display_name')}｜"
            ct = (s.get("membership_criteria") or "")
            for art in feed:
                if art.get("details", {}).get("content_type") == key or \
                   (key == "daily_digest" and art.get("details", {}).get("content_type") == "daily_digest"):
                    if (art.get("title") or "").startswith(bad_prefix):
                        findings.append({"series": key, "id": art.get("id"), "kind": "masthead_double_header", "detail": f"title starts with '{bad_prefix}' but branding is frontend masthead"})

    # 3. orphan brand: a PUBLISHED article carries a registered prefix but is not a registered member
    for art in feed:
        if art.get("status") != "published":
            continue
        title = art.get("title") or ""
        for prefix, skey in prefixed_series.items():
            if title.startswith(prefix):
                s = series[skey]
                registered = set(s.get("members_published", [])) | set(s.get("members_draft", []))
                # member_qa/by-content-type series: membership is by content_type, not explicit list
                by_ct = "content_type" in (s.get("membership_criteria") or "")
                if art.get("id") not in registered and not by_ct:
                    findings.append({"series": skey, "id": art.get("id"), "kind": "orphan_brand", "detail": f"published with prefix '{prefix}' but not a registered member"})
    return findings


def _strip_existing_prefix(title: str, display_name: str, emoji: str) -> str:
    """Return the base title with any leading series prefix removed, tolerant of
    emoji variants — so changing the registry prefix (e.g. adding/removing/moving
    the emoji) MIGRATES cleanly instead of double-prefixing.

    Handles: `<emoji> <name>｜`, `<emoji><name>｜`, `<name> <emoji>｜`, `<name>｜`.
    """
    e = emoji or ""
    variants = [
        f"{e} {display_name}｜",
        f"{e}{display_name}｜",
        f"{display_name} {e}｜",
        f"{display_name}｜",
    ]
    for v in variants:
        if v.strip() and title.startswith(v):
            return title[len(v):]
    return title


def apply(series: dict, feed: list) -> tuple[int, list[str]]:
    """Idempotently apply the registry prefix to title_prefix members, MIGRATING
    any existing series prefix variant (emoji add/remove/move). Returns (n_changed, log)."""
    by_id = {a.get("id"): a for a in feed}
    log: list[str] = []
    changed = 0
    report_updates: dict[str, str] = {}
    for key, s in series.items():
        if s.get("branding") != "title_prefix" or not s.get("prefix"):
            continue
        prefix = s["prefix"]
        display_name = s.get("display_name", "")
        emoji = s.get("emoji", "")
        for aid in list(s.get("members_published", [])) + list(s.get("members_draft", [])):
            art = by_id.get(aid)
            if art is None:
                log.append(f"  !! {key}/{aid} not in feed")
                continue
            title = art.get("title") or ""
            base = _strip_existing_prefix(title, display_name, emoji)
            new_title = prefix + base
            if new_title == title:
                continue
            art["title"] = new_title
            report_updates[aid] = new_title
            changed += 1
            log.append(f"  ~ {key}/{aid}: {title[:24]}… -> {new_title[:24]}…")
    if changed:
        FEED.write_text(json.dumps(feed, ensure_ascii=False, indent=2), encoding="utf-8")
        for aid, new_title in report_updates.items():
            rp = REPORTS / f"{aid}.json"
            if rp.exists():
                rj = json.loads(rp.read_text(encoding="utf-8"))
                if isinstance(rj, dict):
                    rj["title"] = new_title
                    rp.write_text(json.dumps(rj, ensure_ascii=False, indent=2), encoding="utf-8")
                    log.append(f"    synced reports/{aid}.json")
    return changed, log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="apply branding (default is audit-only)")
    ap.add_argument("--json", action="store_true", help="machine-readable audit output")
    args = ap.parse_args()

    series = _load_registry()
    feed = _load_feed()

    if args.apply:
        n, log = apply(series, feed)
        print("\n".join(log) if log else "no changes (all registered members already branded)")
        print(f"\napplied: {n} title change(s)")
        return 0

    findings = audit(series, feed)
    if args.json:
        print(json.dumps({"drift": len(findings), "findings": findings}, ensure_ascii=False, indent=2))
    else:
        if not findings:
            print("series registry audit: CLEAN — all registered series match feed.json")
        else:
            print(f"series registry audit: {len(findings)} DRIFT finding(s):")
            for f in findings:
                print(f"  [{f['kind']}] {f['series']}/{f.get('id')}: {f['detail']}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
