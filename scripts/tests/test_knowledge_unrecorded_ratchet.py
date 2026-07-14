"""Mechanical gate: a finished experiment must reach knowledge.json (2026-07-14).

THE BUG CLASS
-------------
An experiment with an archived ``*_results.json`` but no entry in
``storage/memory/knowledge.json`` is invisible to topic dedup and article selection --
so the pipeline happily re-runs it, and its null result never stops anyone.

The 2026-07-14 kb-backfill audit found **136 such experiments** (~11% of all finished
work), accumulated silently because writing the knowledge base was a prose instruction
("完成實驗後...才寫 knowledge") with no mechanical owner. The backlog was written in
(``scripts/kb_backfill_apply.py``, receipts in ``storage/ops/kb_backfill/``), taking the
count to zero.

Clearing the stock is not the fix. Without a gate the hole regrows at the same rate --
so this ratchet freezes the class at zero: an experiment that lands finished results
without a knowledge entry turns CI red in the same fire that produced it, while the
author is still there to write the entry.

Per anti-stacking this is the SINGLE enforcement owner for this concern. Do not add a
second watchdog -- extend this one.

Run:
    uv run --extra dev python -m pytest scripts/tests/test_knowledge_unrecorded_ratchet.py -v

If this fails, the fix is to WRITE THE KNOWLEDGE ENTRY (main thread, never an agent --
CLAUDE.md / K1259), not to widen the baseline.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import reproduce_check  # noqa: E402

# Frozen at zero on 2026-07-14 after the 136-entry backfill. This number may only
# ever go DOWN. Raising it means someone chose to let finished research stay invisible.
BASELINE = 0


def test_no_finished_experiment_is_missing_from_the_knowledge_base() -> None:
    inventory = reproduce_check.build_inventory(ROOT)
    unrecorded = inventory["results_without_knowledge"]
    names = sorted(
        item if isinstance(item, str) else item.get("experiment", "?") for item in unrecorded
    )
    assert len(names) <= BASELINE, (
        f"{len(names)} finished experiment(s) have archived results but no knowledge.json "
        f"entry, so dedup and topic selection cannot see them: {names[:10]}"
        f"{' ...' if len(names) > 10 else ''}\n"
        "Write the entry from the main thread (agents must not write knowledge.json — K1259); "
        "do not raise BASELINE."
    )
