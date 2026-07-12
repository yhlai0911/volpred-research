#!/usr/bin/env python3
"""Pre-write narrative-arc duplicate check for article agents.

Usage:
    uv run python scripts/check_arc_dedup.py --title "銅博士的波動率版本" \
        --text-file /tmp/draft_or_results_summary.md
    uv run python scripts/check_arc_dedup.py --k-id k1449 --audience general

Exit codes: 0 = no duplicate, 1 = duplicate found (do NOT write/publish
without a deliberate new angle + details['dup_waiver']), 2 = usage error.

Why this exists (2026-06-10 K1449/K1091 incident): title-similarity dedup is
blind to same-story-different-shell duplicates. The publisher now hard-blocks
arc duplicates at publish time, but running this BEFORE writing saves the whole
wasted article. Mandated in the hourly dispatch prompt for daily_article /
gen_article tasks.

Two gates, in order of confidence:

1. K-COVERAGE (hard, exact): does a live feed article already carry this K-id
   for this audience? Per `.claude/rules/dedup-gate-audit.md` a same-K-id hit is
   the hard-block tier — it needs no fuzzy judgement. `find_arc_duplicates` does
   carry a shared-ref signal, but it is gated behind `ex_cls == new_cls`
   (arc_dedup.py ~L951/L962), so a same-K twin whose conclusion wording classifies
   differently slips straight through. 2026-07-11: K1586 and K1605 both passed
   this CLI with exit 0 while `mile_c1ce6550` / `mile_3a7bd6f6` — same K, same
   audience — were already live, and two writer agents were dispatched on top of
   them. Coverage is an exact-match fact; it must not depend on a text classifier.

2. ARC (fuzzy): the narrative-arc signature match, unchanged.

`--audience` narrows both gates. Publishing a research write-up AND a
general-reader write-up of the same K is the product design (many K-ids carry
both live), so an unscoped check judges a general twin against its research
sibling and blocks forever. Pass the audience you are about to write.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from volpred.publisher.arc_dedup import (  # noqa: E402
    _arc_item_audience,
    _normalize_ref,
    _refs_from_feed_item,
    arc_signature,
    classify_narrative_axis,
    extract_entities,
    find_arc_duplicates,
)
from volpred.publisher.publisher import _log_dedup_decision  # noqa: E402

# Feed statuses that are not reader-visible; they cannot constitute coverage.
DEAD_STATUSES = ("unpublished", "retracted")

# Overlap coefficient above which a live article is worth showing the caller as a
# possible same-story hit. Tuned low on purpose: this list is advisory, never a
# block, so a false positive costs one glance and a false negative costs an
# article nobody needed.
LEXICAL_HINT_THRESHOLD = 0.18
LEXICAL_HINT_LIMIT = 5


def _tokens(text: str) -> set[str]:
    """Latin words + CJK character bigrams — a script-agnostic bag of tokens."""
    toks: set[str] = set()
    word = ""
    cjk_run = ""

    def flush_cjk() -> None:
        for i in range(len(cjk_run) - 1):
            toks.add(cjk_run[i : i + 2])

    for ch in text.lower():
        if ch.isascii() and ch.isalnum():
            word += ch
            flush_cjk()
            cjk_run = ""
        elif "一" <= ch <= "鿿":
            cjk_run += ch
            if len(word) >= 3:
                toks.add(word)
            word = ""
        else:
            if len(word) >= 3:
                toks.add(word)
            word = ""
            flush_cjk()
            cjk_run = ""
    if len(word) >= 3:
        toks.add(word)
    flush_cjk()
    return toks


def find_lexical_hints(title: str, text: str, feed: list[dict]) -> list[dict]:
    """Live articles whose titles share a lot of surface vocabulary with this one.

    A crude stand-in for the arc gate, used only when the arc signature is too
    thin for the arc gate to say anything (see Gate 3). Overlap coefficient
    rather than Jaccard, because titles are short and a long draft body would
    otherwise drown every candidate.
    """
    probe = _tokens(f"{title}\n{text[:400]}")
    if not probe:
        return []
    hits: list[dict] = []
    for item in feed:
        if item.get("status") in DEAD_STATUSES:
            continue
        cand_title = str(item.get("title") or "")
        cand = _tokens(cand_title)
        if not cand:
            continue
        shared = probe & cand
        score = len(shared) / min(len(probe), len(cand))
        if score >= LEXICAL_HINT_THRESHOLD:
            hits.append(
                {
                    "id": item.get("id", "?"),
                    "title": cand_title,
                    "status": item.get("status", "?"),
                    "audience": _arc_item_audience(item),
                    "published_at": (item.get("published_at") or item.get("created_at") or "")[:10],
                    "score": round(score, 3),
                }
            )
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:LEXICAL_HINT_LIMIT]


def find_k_coverage(k_id: str, feed: list[dict], audience: str | None) -> list[dict]:
    """Live feed articles already carrying this K-id (optionally same audience).

    Exact-match gate — no text classifier in the path. `audience=None` means
    "any audience", which is the right default only for callers that genuinely
    span audiences; writers should pass the audience they are about to write, or
    a research sibling will look like coverage of a general piece.
    """
    want = _normalize_ref(k_id)
    want_audience = str(audience or "").strip().lower() or None
    hits: list[dict] = []
    for item in feed:
        if item.get("status") in DEAD_STATUSES:
            continue
        if want not in _refs_from_feed_item(item):
            continue
        item_audience = _arc_item_audience(item)
        if want_audience and item_audience not in (want_audience, "uncategorized"):
            continue
        hits.append(
            {
                "id": item.get("id", "?"),
                "title": item.get("title", "?"),
                "status": item.get("status", "?"),
                "audience": item_audience,
                "published_at": (item.get("published_at") or item.get("created_at") or "")[:10],
            }
        )
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--title", default="", help="planned article title / topic")
    ap.add_argument("--text-file", help="draft / results summary file to scan")
    ap.add_argument("--k-id", help="experiment id (reads experiments/<k>/README.md + results)")
    ap.add_argument(
        "--audience",
        help="audience you are about to write (general / research / ...). "
        "Narrows BOTH gates; omit only if the piece genuinely spans audiences.",
    )
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()

    text = ""
    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8", errors="replace")
    if args.k_id:
        kdir = ROOT / "experiments" / args.k_id.lower()
        for name in ("README.md", f"{args.k_id.lower()}_results.json"):
            f = kdir / name
            if f.exists():
                text += "\n" + f.read_text(encoding="utf-8", errors="replace")
        if not text:
            print(f"ERROR: no readable files under {kdir}", file=sys.stderr)
            return 2
    if not (args.title or text):
        ap.print_help()
        return 2

    feed = json.loads((ROOT / "storage" / "reports" / "feed.json").read_text(encoding="utf-8"))
    storage_dir = str(ROOT / "storage")
    full = f"{args.title}\n{text}"
    signature = arc_signature(args.title, text)
    report = {
        "entities": sorted(extract_entities(full)),
        "conclusion_class": signature["conclusion_class"],
        "narrative_axis": classify_narrative_axis(full),
        "entity_groups": signature.get("entity_groups", {}),
        "mechanisms": signature["mechanisms"],
        "time_horizon": signature["time_horizon"],
        "arc_signature": signature,
        "audience_scope": args.audience or "any",
    }

    # Gate 1 — K coverage (exact). Runs before the fuzzy arc gate: if the exact
    # gate already knows this K+audience is covered, the fuzzy verdict is moot.
    coverage = find_k_coverage(args.k_id, feed, args.audience) if args.k_id else []
    report["k_coverage"] = coverage

    # Gate 2 — narrative arc (fuzzy). new_refs/audience have always been
    # parameters of find_arc_duplicates; this CLI simply never passed them.
    new_refs = {_normalize_ref(args.k_id)} if args.k_id else None
    dups = find_arc_duplicates(
        args.title, text, feed, days=args.days, new_refs=new_refs, audience=args.audience
    )
    report["arc_duplicates"] = dups

    # Gate 3 — thin signature. `find_arc_duplicates` bails out with [] when the
    # piece has neither entities nor refs (arc_dedup.py ~L856: "with no entities
    # AND no refs there is nothing to anchor a match on"). That [] means "I could
    # not look", not "I looked and it is clean" — but this CLI used to render both
    # as the same ✅. 2026-07-13: the trending task "AI營收不如預期？科技股選擇權偏斜率"
    # carried no K-id and no ticker, so it scored entities=[] and passed with a
    # green tick while four live articles already told that exact story
    # (mile_8a5e80b0 / mile_0941e2f0 / mile_49616ac2 / mile_622a2b73).
    # Per `.claude/rules/dedup-gate-audit.md` a fuzzy gate must fail OPEN, so this
    # stays exit 0 — a thin signature is not evidence of duplication. What it must
    # not do is claim the piece is clean. Show the lexical near-misses and put the
    # judgement back on the caller, who still owes the 3-layer check either way.
    thin = not report["entities"] and not new_refs
    report["signature_thin"] = thin
    hints = find_lexical_hints(args.title, text, feed) if thin else []
    report["lexical_hints"] = hints
    report["verdict"] = (
        "block_k_coverage" if coverage
        else "block_arc_dup" if dups
        else "unjudged_thin_signature" if thin
        else "clean"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if coverage:
        for hit in coverage:
            _log_dedup_decision(
                storage_dir, "block_k_coverage", args.title, hit["id"],
                f"{args.k_id} already covered for audience={hit['audience']} "
                f"(status={hit['status']})",
            )
        listed = "\n".join(
            f"    - {h['id']} [{h['status']}/{h['audience']}] {h['published_at']} {h['title']}"
            for h in coverage
        )
        print(
            f"\n🚫 K-COVERAGE — {args.k_id} already has {len(coverage)} live "
            f"article(s) for this audience. Do NOT write another:\n{listed}\n"
            f"    Pick a different K, or a genuinely different audience.",
            file=sys.stderr,
        )
        return 1

    if dups:
        for hit in dups:
            _log_dedup_decision(
                storage_dir, "block_arc_dup", args.title, hit.get("id"),
                f"arc match: {hit.get('match_reason', '?')}",
            )
        print(
            f"\n🚫 ARC DUPLICATE — {len(dups)} existing article(s) tell the same "
            f"story. Do not write this piece without a genuinely new angle "
            f"(and details['dup_waiver'] at publish).",
            file=sys.stderr,
        )
        return 1

    if thin:
        _log_dedup_decision(
            storage_dir, "warn_thin_signature", args.title, None,
            f"no entities and no refs -> arc gate cannot judge; "
            f"{len(hints)} lexical hint(s); audience={args.audience or 'any'}",
        )
        listed = "\n".join(
            f"    - {h['id']} [{h['status']}/{h['audience']}] {h['published_at']} "
            f"(overlap {h['score']}) {h['title']}"
            for h in hints
        ) or "    (no lexical near-misses either — but that is still not a clean bill)"
        print(
            "\n⚠️  SIGNATURE TOO THIN — this topic has no experiment ref and no "
            "recognisable entity (asset / ticker / index), so the arc gate had "
            "nothing to match on. It did NOT clear you; it could not look.\n"
            f"    Closest live articles by wording:\n{listed}\n"
            "    Do the 3-layer check by hand (grep feed for the theme, not just "
            "the title) before writing. If the topic is real, anchor it to a K-id "
            "or a concrete asset and re-run — then the gate can actually work.",
            file=sys.stderr,
        )
        return 0

    _log_dedup_decision(
        storage_dir, "pass_prewrite", args.title, None,
        f"k_id={args.k_id} audience={args.audience or 'any'} days={args.days}",
    )
    print("\n✅ no K coverage and no arc duplicate in window", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
