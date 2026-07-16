"""Merge the three K1426 OOS shards into a single results file.

The parent job timed out at 6h before pair_1 finished, so the OOS sweep was
split into three shards (a: pairs 1-2, b: pairs 3-4, c: pairs 5-6). This
merge is idempotent: it recombines the `.pairs` dicts and re-derives the
shared header, so re-running after a shard is refreshed is safe.

Usage: uv run python experiments/k1426/merge_shards.py
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHARDS = ["a", "b", "c"]
OUT = HERE / "k1426_oos_results.json"

# Shared header fields that must agree across shards; a mismatch means the
# shards were produced under different specs and must not be merged.
HEADER_KEYS = ["experiment_id", "title", "data_range", "seed", "spec", "reproduce"]


def main() -> None:
    loaded = {}
    for s in SHARDS:
        path = HERE / f"k1426_oos_shard_{s}.json"
        if not path.exists():
            raise SystemExit(f"shard {s} missing ({path}); refusing to merge partial results")
        loaded[s] = json.loads(path.read_text())

    ref = loaded[SHARDS[0]]
    for key in HEADER_KEYS:
        for s in SHARDS[1:]:
            if loaded[s].get(key) != ref.get(key):
                raise SystemExit(f"shard {s} disagrees with shard a on '{key}'; refusing to merge")

    pairs: dict = {}
    for s in SHARDS:
        for name, payload in loaded[s]["pairs"].items():
            if name in pairs:
                raise SystemExit(f"pair {name} appears in more than one shard")
            pairs[name] = payload

    merged = {key: ref[key] for key in HEADER_KEYS if key in ref}
    merged["pairs"] = dict(sorted(pairs.items()))
    merged["shard_provenance"] = {
        s: {
            "file": f"k1426_oos_shard_{s}.json",
            "pairs": sorted(loaded[s]["pairs"].keys()),
        }
        for s in SHARDS
    }
    # The shard notes carry one stale line: they describe a "Monthly (21-day)"
    # refit cadence while spec.refit_every is 63 (quarterly). The spec governs —
    # it is what the code consumed — so the note is corrected here rather than
    # copied forward.
    merged["notes"] = [
        n for n in ref["notes"] if "Monthly (21-day) refit cadence" not in n
    ] + [
        "Refit cadence is quarterly (refit_every=63 trading days) and multistart is "
        "n_starts=50; both are compute-tractability reductions from the original "
        "21/100 after the parent job timed out at 6h. Parameters remain strictly lagged.",
        "Shard notes in k1426_oos_shard_*.json describe a '21-day' cadence; that line "
        "contradicts spec.refit_every=63 and is superseded by the note above.",
    ]

    OUT.write_text(json.dumps(merged, indent=2) + "\n")
    resolved = sum(1 for p in pairs.values() if "error" not in p)
    print(f"merged {len(pairs)} pairs ({resolved} resolved) -> {OUT.relative_to(HERE.parent.parent)}")
    for name, payload in merged["pairs"].items():
        if "error" in payload:
            print(f"  {name}: ERROR — {payload['error']}")


if __name__ == "__main__":
    main()
