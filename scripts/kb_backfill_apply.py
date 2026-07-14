"""Apply the kb-backfill proposals (storage/ops/kb_backfill) into knowledge.json.

The agent that produced the proposals is forbidden to write the knowledge base
(CLAUDE.md / K1259); this script is the main-thread writer. It goes through
``MemorySystem._append_to_index``, so every entry passes the same lock, the same
K1259 provenance gate, and the same incremental Mirror sync as any other write.

Two verdict adjustments are made here rather than in the proposals, because both
are provenance facts the proposing agent had no authority to settle:

* ``PASS`` requires reviewer attribution (K1259). Backfilled experiments were
  never reviewed, so a PASS with no ``codex_review.md`` on disk is recorded as
  UNVERIFIED with the artifact's own claim spelled out in the content. Demoting
  the label is the honest move: the result may well hold, but nothing has checked it.
* ``needs_human`` entries carry their gap into the content so a reader who only
  sees the content string still knows the entry is un-adjudicated.

Idempotent: an entry whose item_id is already in the knowledge base is skipped.

    uv run python scripts/kb_backfill_apply.py --dry-run
    uv run python scripts/kb_backfill_apply.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

PROPOSALS = ROOT / "storage/ops/kb_backfill/proposed_entries.json"
KNOWLEDGE = ROOT / "storage/memory/knowledge.json"

REVIEWER_FILENAMES = ("codex_review.md", "codex_review.txt", "review.md")


def _reviewer_path(experiment_id: str) -> str | None:
    """Path of a real review artifact in the experiment dir, if one exists."""
    exp_dir = ROOT / "experiments" / experiment_id
    for name in REVIEWER_FILENAMES:
        if (exp_dir / name).exists():
            return f"experiments/{experiment_id}/{name}"
    return None


def build_record(prop: dict) -> tuple[dict, str | None]:
    """Return (knowledge entry, adjustment note)."""
    verdict = prop["verdict"]
    content = prop["content"]
    note = None
    reviewer = _reviewer_path(prop["experiment_id"])

    if verdict == "PASS" and not reviewer:
        verdict = "UNVERIFIED"
        content = (
            f"{content} 〔backfill provenance：artifact 自報 PASS，但實驗目錄無 reviewer "
            f"覆核紀錄，依 K1259 provenance gate 以 UNVERIFIED 收錄；未經覆核前不得引用為 PASS 證據。〕"
        )
        note = "PASS→UNVERIFIED (no reviewer artifact)"

    if prop.get("needs_human"):
        content = f"[NEEDS_HUMAN 待人工裁決] {content} 〔gap：{prop['gap']}〕"

    record = {
        "item_id": prop["item_id"],
        "category": prop["category"],
        "content": content,
        "evidence": prop["evidence"],
        "confidence": prop["confidence"],
        "created_at": f"{prop['created_at']}T00:00:00",
        "created_at_source": prop["created_at_source"],
        "k_id": prop["k_id"],
        "experiment_id": prop["experiment_id"],
        "experiment_path": prop["experiment_path"],
        "verdict": verdict,
        "needs_human": prop.get("needs_human", False),
        "gap": prop.get("gap", ""),
        "provenance": prop["provenance"],
    }
    if reviewer:
        record["reviewer"] = reviewer
    return record, note


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not (args.apply or args.dry_run):
        parser.error("pass --dry-run or --apply")

    from volpred.memory.provenance import validate_provenance
    from volpred.memory.system import MemorySystem
    from volpred.research.conclusion_lint import lint_conclusion

    proposals = json.loads(PROPOSALS.read_text())
    existing_ids = {
        entry.get("item_id")
        for entry in json.loads(KNOWLEDGE.read_text())
        if isinstance(entry, dict)
    }

    records, notes, lint_hits, skipped = [], [], [], []
    for prop in proposals:
        if prop["item_id"] in existing_ids:
            skipped.append(prop["k_id"])
            continue
        record, note = build_record(prop)
        validate_provenance(record)  # fail fast before any write happens
        if note:
            notes.append(f"{prop['k_id']}: {note}")
        if warnings := lint_conclusion(record["content"]):
            lint_hits.append(f"{prop['k_id']}: {len(warnings)} lint warning(s)")
        records.append(record)

    print(f"to write: {len(records)}  already recorded (skipped): {len(skipped)}")
    print(f"needs_human: {sum(r['needs_human'] for r in records)}")
    print(f"verdict adjustments: {len(notes)}")
    for n in notes:
        print("  -", n)
    print(f"conclusion_lint warnings: {len(lint_hits)}")

    if args.dry_run:
        print("\ndry-run: nothing written")
        return 0

    mem = MemorySystem(storage_dir=str(ROOT / "storage"))
    for i, record in enumerate(records, 1):
        mem._append_to_index("knowledge.json", record)
        if i % 25 == 0:
            print(f"  written {i}/{len(records)}")
    print(f"\nwritten: {len(records)} entries → {KNOWLEDGE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
