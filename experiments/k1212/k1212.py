"""K1212: research_program.md Session Delta Draft — stats computation.

Pure consolidation task. No numerical model, no random process.
Outputs `k1212_session_stats.json` with session tallies extracted from
`storage/memory/knowledge.json` and `storage/next_tasks.json`.

Seed 42 declared nominally (no randomness in fact).
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from pathlib import Path

random.seed(42)

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_PATH = WORKTREE_ROOT / "storage" / "memory" / "knowledge.json"
NEXT_TASKS_PATH = WORKTREE_ROOT / "storage" / "next_tasks.json"
OUTPUT_PATH = Path(__file__).parent / "k1212_session_stats.json"

# Session boundary: 2026-04-17 onward (this-session window per agent brief).
SESSION_START = "2026-04-17T00:00"

K_RE = re.compile(r"K\d{3,4}[a-z_]*")


def load_json(path: Path):
    with path.open("r") as fh:
        return json.load(fh)


def session_knowledge_entries(knowledge: list[dict]):
    return [e for e in knowledge if e.get("created_at", "") >= SESSION_START]


def extract_k_mentions(entries: list[dict]) -> Counter:
    c: Counter = Counter()
    for e in entries:
        content = e.get("content", "")
        for m in K_RE.findall(content):
            c[m] += 1
    return c


def category_counts(entries: list[dict]) -> Counter:
    return Counter(e.get("category", "unknown") for e in entries)


def tasks_by_status(tasks: list[dict]) -> Counter:
    return Counter(t.get("status", "unknown") for t in tasks)


def narrative_decision_tasks(tasks: list[dict]):
    out = []
    for t in tasks:
        status = t.get("status", "")
        if "decision" in status or "awaiting_body_rewrite" in status:
            out.append({
                "id": t.get("id"),
                "status": status,
                "title": (t.get("title") or "")[:140],
            })
    return out


def main() -> None:
    knowledge = load_json(KNOWLEDGE_PATH)
    tasks = load_json(NEXT_TASKS_PATH)

    entries = session_knowledge_entries(knowledge)
    k_mentions = extract_k_mentions(entries)
    cat_counts = category_counts(entries)

    # Filter K mentions to session-relevant band (K1100-K1299).
    band = {k: c for k, c in k_mentions.items() if 1100 <= int(re.match(r"K(\d+)", k).group(1)) <= 1299}

    stats = {
        "experiment_id": "K1212",
        "purpose": "research_program.md session delta draft for main-thread review",
        "session_window_start": SESSION_START,
        "seed": 42,
        "knowledge_entries_in_session": len(entries),
        "knowledge_categories": dict(cat_counts.most_common()),
        "k_mentions_session_band_K1100_K1299": dict(sorted(band.items())),
        "unique_k_ids_session_band": len(band),
        "tasks_total": len(tasks),
        "tasks_by_status": dict(tasks_by_status(tasks)),
        "narrative_decision_tasks": narrative_decision_tasks(tasks),
        "papers_touched": [
            "leverage-direction (Paper 1)",
            "taiwan-vt (Paper 2)",
            "vt-trend-following (Paper 3)",
            "vix-sufficiency (Paper 4)",
            "prg-periodic-garch (Paper 6)",
            "garch-x-vix (Paper 9)",
            "btc-gas-negative (candidate)",
        ],
        "narrative_state_transitions": {
            "paper1_batch1_committed": "0a442356",
            "paper1_batch2_draft_pending": "K1209",
            "paper2_foundry_NULL_stack": "5 layers (K1108/K1108b/K1108c/K1108d/K1108e/K1108f)",
            "paper2_s5_decision": "decision_made_awaiting_body_rewrite (user 2026-04-17 Option 4)",
            "paper3_K1128_pivot_gate": "met (4 branches: K1128/K1131/K1142/K1199)",
            "paper3_strategic_A_B_C": "decision_ready_user_input_needed",
            "paper4_UNIVERSAL_NULL": "7/7 declared (channel-specific pivot conflict flagged as CONFLICT-A4)",
            "paper6_defensibility": "CONFIRMED via K1200 K880v2 two-phase timing",
            "btc_gas_new_paper": "candidate (needs user slot decision)",
        },
        "methodology_upgrades": [
            "PIT alignment triple-gate (K1116-family)",
            "Sector-FE decomposition standard (K1207)",
            "Two-phase forecast timing (K1200 K880v2)",
            "Synthesis agent pattern (K1204/K1205/K1208/K1209/K1211/K1212)",
        ],
        "blocked_persistent": [
            "K1100h (Dropbox tick TAIFEX 2017-2021)",
            "K1116d (FRED_API_KEY)",
            "K1161b (paid options data)",
            "K1175 legacy (GDELT / GCP BigQuery capacity)",
            "I4 VIX futures roll yield (yfinance no data)",
        ],
        "conflicts_flagged": {
            "CONFLICT_A4": "Paper 4 body_v4 narrative = channel-specific (user) vs UNIVERSAL_NULL (session) — main thread clarify",
        },
    }

    OUTPUT_PATH.write_text(json.dumps(stats, indent=2, ensure_ascii=False))
    print(f"Wrote {OUTPUT_PATH}")
    print(f"Session knowledge entries: {stats['knowledge_entries_in_session']}")
    print(f"Unique K ids in K1100-K1299 band: {stats['unique_k_ids_session_band']}")
    print(f"Tasks total: {stats['tasks_total']}")


if __name__ == "__main__":
    main()
