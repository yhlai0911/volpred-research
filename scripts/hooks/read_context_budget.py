#!/usr/bin/env python3
"""PreToolUse(Read): give unbounded whole-file reads a default line budget.

Why this exists
---------------
2026-07-14 token forensics over 7 days of transcripts (17,570 tool results):

    Read            3,679,357 tok   n=2,005   avg=1,835   <- 51% of ALL tool-result tokens
      no limit/offset   2,713,755 tok   n=1,015   avg=2,673   (73.8% of Read tokens)
      with limit/offset   965,602 tok   n=  990   avg=  975

The bill is not driven by the size of CLAUDE.md (a one-time prefix, amortised by
cache_read at 0.1x).  It is driven by how many tokens each turn *appends* to the
conversation, because every appended token is written into the cache at least
once (cache_create, 1.25-2x) and re-written in full every time a long-running
session crosses the cache TTL.  Measured weekly cache_create (33.3M) is ~3x the
total new content (~11M), i.e. each token entering context is paid for roughly
three times.  Cutting tool-result volume therefore saves a multiple of its size.

The single biggest line item is a Read with no `limit` on a file that turns out
to be long: p90 of an unbounded read is 8,045 tokens.  The top file alone --
storage/ops/handoff_latest.md, a machine-generated ops digest every session is
told to read -- costs 457K tokens/week in whole-file reads.

Policy (measured against the same 7-day window):

    trigger: file > 250 lines and caller passed neither limit nor offset
    action : inject limit=200 and tell the caller how to get the rest
    effect : touches 273 of 1,015 unbounded reads, saves ~1.12M raw tokens/week

Function is preserved, which is the whole point (owner directive 2026-07-14:
"要確實重構優化流程提高運作效率，但又不損當前的功能").  An explicit `limit` or
`offset` is ALWAYS honoured untouched -- this only supplies a default where the
caller expressed no intent, exactly like Read's own built-in 2000-line cap.  The
caller is told the true line count and how to page, so nothing becomes
unreachable; it just stops being free to slurp.

Fail-open by construction: any unreadable path, odd format, or unexpected error
emits `{}` (no-op).  A hook that breaks Read is far more expensive than a hook
that occasionally fails to save tokens.
"""

from __future__ import annotations

import json
import os
import sys

TRIGGER_LINES = 250
DEFAULT_LIMIT = 200

# Formats where a line budget is meaningless or actively wrong: Read renders
# images visually, pages PDFs via `pages`, and expands notebooks into cells.
# Injecting `limit` into those would change behaviour rather than bound it.
SKIP_SUFFIXES = {
    ".pdf",
    ".ipynb",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".svg",
}

NOOP = "{}"


def _noop() -> None:
    print(NOOP)
    sys.exit(0)


def _count_lines(path: str) -> int | None:
    """Return the line count, or None if the file is binary / unreadable.

    Reads in blocks rather than splitlines() on the whole file: the point of
    this hook is to stop paying for large files, so it must not itself load one.
    """
    lines = 0
    with open(path, "rb") as fh:
        first = fh.read(8192)
        if b"\x00" in first:  # binary: line budget is meaningless
            return None
        block = first
        while block:
            lines += block.count(b"\n")
            block = fh.read(1 << 20)
    return lines + 1  # trailing fragment counts as a line


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        _noop()

    if payload.get("tool_name") != "Read":
        _noop()

    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        _noop()

    # Explicit caller intent is sacred. If the model said how much it wants,
    # it gets exactly that -- the budget only fills a vacuum.
    if tool_input.get("limit") is not None or tool_input.get("offset") is not None:
        _noop()

    path = tool_input.get("file_path")
    if not path or not isinstance(path, str):
        _noop()

    if os.path.splitext(path)[1].lower() in SKIP_SUFFIXES:
        _noop()

    try:
        if not os.path.isfile(path):
            _noop()
        total_lines = _count_lines(path)
    except Exception:
        _noop()

    if total_lines is None or total_lines <= TRIGGER_LINES:
        _noop()

    reason = (
        f"context budget: {os.path.basename(path)} is {total_lines} lines; "
        f"reading the first {DEFAULT_LIMIT} instead of the whole file"
    )
    guidance = (
        f"📏 Context budget applied — `{path}` is **{total_lines} lines**, so this Read was "
        f"bounded to the first {DEFAULT_LIMIT} lines.\n"
        f"Nothing is out of reach; you just have to ask for it:\n"
        f"- more of this file → Read again with `offset`/`limit` (e.g. offset={DEFAULT_LIMIT + 1})\n"
        f"- looking for something specific → Grep the file instead of paging through it\n"
        f"- you genuinely need it all → Read with an explicit `limit` (explicit limits are never overridden)\n"
        f"Why: unbounded whole-file Reads are 51% of all tool-result tokens, and every token "
        f"entering context is re-written into the prompt cache ~3x."
    )

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "permissionDecisionReason": reason,
                    "updatedInput": {**tool_input, "limit": DEFAULT_LIMIT},
                    "additionalContext": guidance,
                }
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never let a token optimisation take Read down with it.
        print(NOOP)
