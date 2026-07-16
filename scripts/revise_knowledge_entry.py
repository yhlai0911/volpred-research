#!/usr/bin/env python3
"""Revise an existing knowledge.json entry in place, through the canonical writer path.

Why this exists (2026-07-17, hourly-slot-1): knowledge.json had an append-only
tool surface. `MemorySystem.add_knowledge` could create an entry; nothing could
correct one. So every review that found a wrong entry ended with the same
recommendation — "主線程用正式 writer 修訂 item_id=X, 禁止 jq/Edit 直改" — naming a
writer that did not exist. The two live examples that forced this script:

- `storage/ops/orphan_collect/k1649_knowledge_proposal.json`: entry 968b552d says
  "expectile 類模型在4個asset-alpha組合中有4個優於LinearQR" — reads as 4/4 cells
  when the fact is 4 of 8 (model x cell) pairs, i.e. 2 of 4 cells. Also inherits
  "calibration可控" from a README the Codex review downgraded to "mixed".
- `storage/ops/orphan_collect/k1630_knowledge_proposal.json`: entry 05c60c6c
  copied an untested decay narrative straight out of a README.

Both were written by `kb_backfill_unrecorded_experiments` (2026-07-14) without
review. Hand-editing them with jq/Edit is exactly the bypass that
`scripts/validate_knowledge_provenance.py` exists to catch, so the only honest
options were "leave the knowledge base wrong" or "build the missing path".

What this guarantees, by reusing `_append_to_index`'s mechanics rather than
reimplementing them:
  - `shared_state_lock` — serialises against Claude/Codex/cron writers
  - `validate_provenance` — the K1259 gate runs on the REVISED entry, so a
    revision cannot introduce a violation an append could not
  - `guard_canonical_write` — canonical-root enforcement
  - atomic tmp -> replace + post-write json.load sanity check
  - one-space indent — preserves the repo format so a one-entry revision does
    not rewrite the whole 3MB file
  - `append_writer_log` — the revision is attributable

Revision history is kept ON the entry (`revisions[]`), not in a side file: a
reader of the entry must be able to see that it was corrected, and why, without
knowing to look somewhere else.

Usage:
    uv run python scripts/revise_knowledge_entry.py \
        --item-id 968b552d \
        --actor hourly-slot-1-<job_id> \
        --reason "Codex CONDITIONAL PASS review: 4/8 pairs misread as 4/4 cells" \
        --set-file content=/tmp/new_content.md \
        --set verdict=NULL \
        --set reviewer='codex (gpt-5.6-sol, high, primary-path)' \
        --dry-run

`--set-file` for prose (Chinese content mangles through shell quoting);
`--set` for short scalars. Both take `field=value`. Values that parse as JSON
are stored as JSON (so `--set confidence=0.85` stores a float, not "0.85");
anything else is stored as a string.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from volpred.canonical_write import guard_canonical_write  # noqa: E402
from volpred.memory.provenance import validate_provenance  # noqa: E402
from volpred.ops.shared_lock import shared_state_lock  # noqa: E402
from volpred.ops.writer_log import append_writer_log  # noqa: E402

# Fields a revision must never silently rewrite: identity and origin.
IMMUTABLE_FIELDS = {"item_id", "created_at", "created_at_source"}


def _coerce(raw: str):
    """JSON if it parses, else the literal string."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw


def _parse_assignment(arg: str, *, from_file: bool) -> tuple[str, object]:
    if "=" not in arg:
        raise SystemExit(f"--set{'-file' if from_file else ''} needs field=value, got: {arg!r}")
    field, raw = arg.split("=", 1)
    field = field.strip()
    if not field:
        raise SystemExit(f"empty field name in: {arg!r}")
    if field in IMMUTABLE_FIELDS:
        raise SystemExit(
            f"refusing to revise {field!r}: identity/origin fields are immutable "
            f"(a correction is not a new entry — see IMMUTABLE_FIELDS)"
        )
    if from_file:
        path = Path(raw)
        if not path.is_file():
            raise SystemExit(f"--set-file {field}: no such file: {raw}")
        return field, path.read_text(encoding="utf-8").strip()
    return field, _coerce(raw)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--item-id", required=True, help="item_id of the entry to revise")
    ap.add_argument("--actor", required=True, help="who is revising (owner token / actor id)")
    ap.add_argument("--reason", required=True, help="why this revision is correct — recorded on the entry")
    ap.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE", help="scalar field assignment")
    ap.add_argument("--set-file", action="append", default=[], metavar="FIELD=PATH", help="field assignment from file")
    ap.add_argument("--path", default=str(ROOT / "storage" / "memory" / "knowledge.json"))
    ap.add_argument("--storage-dir", default=str(ROOT / "storage"))
    ap.add_argument("--dry-run", action="store_true", help="show the diff, write nothing")
    args = ap.parse_args()

    updates: dict[str, object] = {}
    for a in args.set:
        f, v = _parse_assignment(a, from_file=False)
        updates[f] = v
    for a in args.set_file:
        f, v = _parse_assignment(a, from_file=True)
        updates[f] = v
    if not updates:
        raise SystemExit("nothing to revise: pass at least one --set / --set-file")
    if "revisions" in updates:
        raise SystemExit("refusing to overwrite revisions[]: it is this script's audit trail")

    filepath = Path(args.path)
    if not filepath.is_file():
        raise SystemExit(f"knowledge file not found: {filepath}")

    result_label = "ok"
    try:
        with shared_state_lock("memory_knowledge", storage_dir=args.storage_dir):
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)

            idx = [i for i, e in enumerate(data) if isinstance(e, dict) and e.get("item_id") == args.item_id]
            if not idx:
                raise SystemExit(f"item_id={args.item_id!r} not found in {filepath}")
            if len(idx) > 1:
                raise SystemExit(
                    f"item_id={args.item_id!r} matches {len(idx)} entries — refusing to guess which to revise"
                )
            i = idx[0]
            entry = json.loads(json.dumps(data[i]))  # deep copy; original untouched until write

            before = {f: entry.get(f) for f in updates}
            changed = {f: v for f, v in updates.items() if entry.get(f) != v}
            if not changed:
                print(f"[revise] no-op: every field already holds the requested value (item_id={args.item_id})")
                return 0

            entry.update(changed)
            entry.setdefault("revisions", []).append(
                {
                    "revised_at": datetime.now().astimezone().isoformat(),
                    "actor": args.actor,
                    "reason": args.reason,
                    "fields": sorted(changed),
                    "before": {f: before[f] for f in changed},
                }
            )

            # The gate that guards appends must also guard revisions, or a
            # revision becomes the hole an append never was.
            validate_provenance(entry)

            print(f"[revise] item_id={args.item_id} fields={sorted(changed)}")
            for f in sorted(changed):
                old = json.dumps(before[f], ensure_ascii=False, default=str)
                new = json.dumps(changed[f], ensure_ascii=False, default=str)
                print(f"  - {f}:\n      before: {old[:300]}{'…' if len(old) > 300 else ''}")
                print(f"      after : {new[:300]}{'…' if len(new) > 300 else ''}")
            if args.dry_run:
                print("[revise] --dry-run: nothing written")
                return 0

            guard_canonical_write(filepath)
            data[i] = entry
            tmp_path = filepath.with_name(f".{filepath.name}.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1, default=str, ensure_ascii=False)
            with open(tmp_path, encoding="utf-8") as f:
                json.load(f)  # post-write sanity: never replace with unparseable bytes
            tmp_path.replace(filepath)
            print(f"[revise] written: {filepath}")
    except Exception as exc:
        result_label = f"error: {type(exc).__name__}: {exc}"[:200]
        raise
    finally:
        if not args.dry_run:
            append_writer_log(
                subsystem="memory",
                target="memory/knowledge.json",
                record_id=args.item_id,
                result=result_label,
                storage_dir=args.storage_dir,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
