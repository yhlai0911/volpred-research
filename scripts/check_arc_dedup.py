#!/usr/bin/env python3
"""Pre-write narrative-arc duplicate check for article agents.

Usage:
    uv run python scripts/check_arc_dedup.py --title "銅博士的波動率版本" \
        --text-file /tmp/draft_or_results_summary.md
    uv run python scripts/check_arc_dedup.py --k-id k1449 --audience general

Exit codes: 0 = no hard duplicate, 1 = exact coverage found, 2 = usage error.
For event articles, pass ``--event-key`` and ``--event-series-slot`` together:
only the exact structured stage is a hard duplicate; K/arc similarity across
T-7/T-2/T+0/T+1 is advisory because the information state is intentionally new.

Why this exists (2026-06-10 K1449/K1091 incident): title-similarity dedup is
blind to same-story-different-shell duplicates. The publisher now hard-blocks
arc duplicates at publish time, but running this BEFORE writing saves the whole
wasted article. Mandated in the hourly dispatch prompt for daily_article /
gen_article tasks.

Gates and advisory fallbacks, in order of confidence:

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

3. K-COVERAGE METADATA GAP (warn-only): when exact coverage has no hit, inspect
   same-audience live articles that expose no experiment ref at all. Surface
   overlap cannot prove duplication, but it also cannot support a green
   clearance. The CLI lists candidates and returns a warning verdict.

4. ANCHOR-LESS SIGNATURE (warn-only): if the arc matcher has no useful anchor,
   report that it could not judge instead of calling the candidate clean.

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
    DEAD_STATUSES,
    LEXICAL_HINT_LIMIT,
    LEXICAL_HINT_THRESHOLD,
    _normalize_ref,
    arc_signature,
    find_arc_duplicates,
    find_event_stage_coverage,
    find_k_coverage,
    find_k_coverage_gap_hints,
    find_lexical_hints,
    is_arc_anchorless,
    is_arc_near_miss,
    normalize_event_series_slot,
)
from volpred.publisher.arc_dedup import (
    tokenize as _tokens,
)
from volpred.publisher.publisher import _log_dedup_decision  # noqa: E402

# NOTE (2026-07-14): `_tokens` / `find_lexical_hints` / `find_k_coverage` /
# DEAD_STATUSES used to be DEFINED here. They are library-grade and the task
# GENERATORS needed them too, so they now live in volpred.publisher.arc_dedup and
# are re-exported here (same names, same behaviour) for this CLI and its tests.
# One implementation, no drift.
__all__ = [
    "DEAD_STATUSES",
    "LEXICAL_HINT_LIMIT",
    "LEXICAL_HINT_THRESHOLD",
    "_tokens",
    "find_k_coverage",
    "find_k_coverage_gap_hints",
    "find_lexical_hints",
    "main",
]


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
    ap.add_argument(
        "--event-key",
        help="canonical event identity; must be paired with --event-series-slot",
    )
    ap.add_argument(
        "--event-series-slot",
        help="canonical event stage (T-7/T-2/T+0/T+1); must be paired with --event-key",
    )
    args = ap.parse_args()
    if bool(args.event_key) != bool(args.event_series_slot):
        print(
            "ERROR: --event-key and --event-series-slot must be supplied together",
            file=sys.stderr,
        )
        return 2
    if args.event_series_slot:
        try:
            args.event_series_slot = normalize_event_series_slot(
                args.event_series_slot
            )
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

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
    candidate_id = (
        "k:"
        f"{_normalize_ref(args.k_id)}"
        f"|audience:{str(args.audience or 'any').strip().casefold()}"
        if args.k_id
        else None
    )
    event_identity = (
        {
            "event_key": args.event_key,
            "event_series_slot": args.event_series_slot,
        }
        if args.event_key and args.event_series_slot
        else None
    )
    if event_identity:
        candidate_id = (
            f"{str(args.event_key).strip().casefold()}:"
            f"{str(args.event_series_slot).strip().upper().replace(' ', '')}"
        )
    signature = arc_signature(args.title, text)
    report = {
        "entities": signature["entities"],
        "conclusion_class": signature["conclusion_class"],
        "narrative_axis": signature["narrative_axis"],
        "entity_groups": signature.get("entity_groups", {}),
        "mechanisms": signature["mechanisms"],
        "time_horizon": signature["time_horizon"],
        "arc_signature": signature,
        "audience_scope": args.audience or "any",
        "event_identity": event_identity,
    }

    # Gate 0 — event-stage coverage (exact).  Event articles are an intentional
    # multi-stage series, so this structured identity is their only hard lock.
    event_stage_coverage = (
        find_event_stage_coverage(
            args.event_key,
            args.event_series_slot,
            feed,
        )
        if event_identity
        else []
    )
    report["event_stage_coverage"] = event_stage_coverage

    # Gate 1 — K coverage (exact). Runs before the fuzzy arc gate: if the exact
    # gate already knows this K+audience is covered, the fuzzy verdict is moot.
    coverage = find_k_coverage(args.k_id, feed, args.audience) if args.k_id else []
    report["k_coverage"] = coverage
    coverage_gap_hints = (
        find_k_coverage_gap_hints(
            args.title,
            text,
            feed,
            args.audience,
        )
        if args.k_id and not coverage
        else []
    )
    report["k_coverage_metadata_gap_hints"] = coverage_gap_hints

    # Gate 2 — narrative arc (fuzzy). new_refs/audience have always been
    # parameters of find_arc_duplicates; this CLI simply never passed them.
    new_refs = {_normalize_ref(args.k_id)} if args.k_id else None
    arc_matches = find_arc_duplicates(
        args.title,
        text,
        feed,
        days=args.days,
        new_refs=new_refs,
        audience=args.audience,
        include_fuzzy=True,
    )
    dups = [m for m in arc_matches if not is_arc_near_miss(m)]
    near_misses = [m for m in arc_matches if is_arc_near_miss(m)]
    report["arc_duplicates"] = dups
    report["arc_near_misses"] = near_misses

    # Gate 4 — anchor-less signature. When the arc matcher has nothing to anchor
    # on, its [] means "I could not look", not "I looked and it is clean", and
    # this CLI must not render the two as the same ✅.
    #
    # What counts as an anchor is the MATCHER's business, so the predicate lives
    # next to it (`arc_dedup.is_arc_anchorless`) instead of being re-derived here.
    # This CLI used to own its own narrower version — `not entities and not refs`
    # — and it leaked one day later: 2026-07-14's 「AI變現挑戰」 scored
    # entities=[US_EQUITY], which is non-empty but core-only, hence just as
    # unanchorable, so `thin` was False and the CLI printed `clean` against the
    # same four articles the 2026-07-13 fix was written for.
    #
    # Per `.claude/rules/dedup-gate-audit.md` a fuzzy gate must fail OPEN, so this
    # stays exit 0 — anchor-less is not evidence of duplication. What it must not
    # do is claim the piece is clean. Show the lexical near-misses and put the
    # judgement back on the caller, who still owes the 3-layer check either way.
    thin = is_arc_anchorless(signature, new_refs)
    report["signature_thin"] = thin
    hints = find_lexical_hints(args.title, text, feed) if thin else []
    report["lexical_hints"] = hints
    report["verdict"] = (
        "block_event_stage_coverage" if event_stage_coverage
        else "warn_event_k_coverage" if event_identity and coverage
        else "warn_event_arc_dup" if event_identity and dups
        else "block_k_coverage" if coverage
        else "warn_arc_dup" if dups
        else "warn_arc_near_miss" if near_misses
        else "unjudged_thin_signature" if thin
        else "warn_coverage_metadata_gap" if coverage_gap_hints
        else "clean"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if event_stage_coverage:
        receipt_persisted = False
        for hit in event_stage_coverage:
            receipt_persisted = _log_dedup_decision(
                storage_dir,
                "block_event_stage_coverage",
                args.title,
                hit["id"],
                (
                    f"exact event stage already covered: event_key={args.event_key} "
                    f"slot={args.event_series_slot}"
                ),
                candidate_id=candidate_id,
            ) or receipt_persisted
        if not receipt_persisted:
            print(
                "\n⚠️ EVENT STAGE receipt failed — gate fails open; "
                "do not suppress downstream work without an audit trail.",
                file=sys.stderr,
            )
            return 0
        listed = "\n".join(
            f"    - {h['id']} [{h['status']}/{h['audience']}] "
            f"{h['published_at']} {h['title']}"
            for h in event_stage_coverage
        )
        print(
            "\n🚫 EVENT STAGE COVERED — this exact event_key + slot already has "
            f"{len(event_stage_coverage)} active feed row(s):\n{listed}",
            file=sys.stderr,
        )
        return 1

    if coverage and not event_identity:
        receipt_persisted = False
        for hit in coverage:
            receipt_persisted = _log_dedup_decision(
                storage_dir, "block_k_coverage", args.title, hit["id"],
                f"{args.k_id} already covered for audience={hit['audience']} "
                f"(status={hit['status']})",
                candidate_id=candidate_id,
            ) or receipt_persisted
        if not receipt_persisted:
            print(
                "\n⚠️ K-COVERAGE receipt failed — gate fails open; "
                "do not suppress downstream work without an audit trail.",
                file=sys.stderr,
            )
            return 0
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

    if event_identity and (coverage or dups):
        advisory_hits = coverage or dups
        action = "warn_event_k_coverage" if coverage else "warn_event_arc_dup"
        for hit in advisory_hits:
            _log_dedup_decision(
                storage_dir,
                action,
                args.title,
                hit.get("id"),
                (
                    f"cross-stage advisory for event_key={args.event_key} "
                    f"slot={args.event_series_slot}; "
                    f"reason={hit.get('match_reason', 'shared K')}"
                ),
                candidate_id=candidate_id,
            )
        print(
            "\n⚠️  EVENT CROSS-STAGE SIMILARITY — the event identity is new, so "
            "semantic/K overlap is advisory and writing may proceed. "
            "Differentiate this slot's information state.",
            file=sys.stderr,
        )
        return 0

    if dups:
        for hit in dups:
            _log_dedup_decision(
                storage_dir, "warn_arc_dup", args.title, hit.get("id"),
                f"arc match: {hit.get('match_reason', '?')}",
                candidate_id=candidate_id,
            )
        print(
            f"\n⚠️  ARC DUPLICATE — {len(dups)} existing article(s) may tell the "
            "same story. This fuzzy signal is advisory: review and differentiate, "
            "but the gate does not suppress the article.",
            file=sys.stderr,
        )
        return 0

    if near_misses:
        for hit in near_misses:
            _log_dedup_decision(
                storage_dir,
                "warn_arc_near_miss",
                args.title,
                hit.get("id"),
                f"advisory arc match: {hit.get('match_reason', '?')}",
                candidate_id=candidate_id,
            )
        listed = "\n".join(
            f"    - {h.get('id')} {h.get('title')}"
            for h in near_misses[:5]
        )
        print(
            "\n⚠️  ARC NEAR-MISS — shared entity + mechanism is advisory, not "
            f"duplicate evidence. Review these before writing:\n{listed}\n"
            "    The gate remains fail-open, but this is not a green clearance.",
            file=sys.stderr,
        )
        return 0

    if thin:
        _log_dedup_decision(
            storage_dir, "warn_thin_signature", args.title, None,
            f"no entities and no refs -> arc gate cannot judge; "
            f"{len(hints)} lexical hint(s); audience={args.audience or 'any'}",
            candidate_id=candidate_id,
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

    if coverage_gap_hints:
        for hit in coverage_gap_hints:
            _log_dedup_decision(
                storage_dir,
                "warn_coverage_metadata_gap",
                args.title,
                hit.get("id"),
                "legacy article has no extractable experiment ref; "
                f"lexical overlap={hit.get('score')}; "
                f"audience={args.audience or 'any'}",
                candidate_id=candidate_id,
            )
        listed = "\n".join(
            f"    - {h['id']} [{h['status']}/{h['audience']}] "
            f"{h['published_at']} (overlap {h['score']}) {h['title']}"
            for h in coverage_gap_hints
        )
        print(
            "\n⚠️  K-COVERAGE METADATA GAP — exact K coverage found no hit, "
            "but legacy live articles without extractable experiment refs "
            "share candidate wording. This is not a clean clearance and is "
            "not hard-block evidence.\n"
            f"{listed}\n"
            "    Review the listed article(s) before dispatching a writer.",
            file=sys.stderr,
        )
        return 0

    _log_dedup_decision(
        storage_dir, "pass_prewrite", args.title, None,
        f"k_id={args.k_id} audience={args.audience or 'any'} days={args.days}",
        candidate_id=candidate_id,
    )
    print("\n✅ no K coverage and no arc duplicate in window", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
