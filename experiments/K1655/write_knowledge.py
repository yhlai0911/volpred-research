#!/usr/bin/env python3
"""Append the reviewed K1655 true-PIT correction to knowledge and work_log.

This writer is idempotent.  It preserves the original K1655 knowledge item as an
audit record and appends a SELF-CORRECTION that explicitly supersedes it.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from volpred.memory.system import MemorySystem
from volpred.ops.shared_lock import shared_state_lock


ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = EXPERIMENT_DIR / "K1655_results.json"
KNOWLEDGE_PATH = ROOT / "storage" / "memory" / "knowledge.json"
WORK_LOG_PATH = ROOT / "storage" / "work_log.json"
SUPERSEDES_ITEM_ID = "274f2886"
TASK_ID = "k1655_alfred_pit_rerun"


def _load_json(path: Path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _atomic_write_json(path: Path, payload) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    _load_json(tmp)
    tmp.replace(path)


def _primary_cell(results: dict, horizon: int) -> dict:
    return results["equity_at_risk"]["NFCI"]["oos"][str(horizon)]["tau"]["0.05"]


def _in_sample_cell(results: dict, horizon: int) -> dict:
    key = f"H{horizon}_tau0.05"
    return results["equity_at_risk"]["NFCI"]["in_sample"][key]["nfci"]


def build_entry(results: dict) -> dict:
    if results.get("experiment_id") != "K1655":
        raise RuntimeError("results experiment_id is not K1655")
    if results.get("verdict", {}).get("verdict") != "NULL":
        raise RuntimeError("K1655 true-PIT correction must have statistical verdict NULL")
    if results.get("review_status", {}).get("status") != "PASS":
        raise RuntimeError("K1655 results do not carry the independent post-run PASS")

    provenance = results["data"]["nfci_provenance"]
    alignment = provenance["nfci_pit_alignment"]
    raw = provenance["alfred_revision_history"]
    artifact = results["data"]["forecast_artifact"]
    cells = {h: _primary_cell(results, h) for h in (1, 4, 12)}
    in_sample = {h: _in_sample_cell(results, h) for h in (1, 4, 12)}

    if artifact["verification"]["status"] != "PASS":
        raise RuntimeError("forecast artifact verification is not PASS")
    if not all(alignment["timing_gates"].values()):
        raise RuntimeError("one or more NFCI PIT timing gates failed")
    if any(c["harvey_significant_better"] for c in cells.values()):
        raise RuntimeError("unexpected Harvey-significant primary cell")

    correction_key = f"K1655:{artifact['sha256']}:{SUPERSEDES_ITEM_ID}"
    item_id = hashlib.sha256(correction_key.encode("utf-8")).hexdigest()[:8]

    improvements = "/".join(f"{cells[h]['pinball_reduction_pct']:+.3f}%" for h in (1, 4, 12))
    dm_stats = "/".join(f"{cells[h]['dm_t_hln']:+.3f}" for h in (1, 4, 12))
    in_p = "/".join(f"{in_sample[h]['boot_p']:.3f}" for h in (1, 4, 12))
    sample_start = results["data"]["sample_start"]
    sample_end = results["data"]["sample_end"]
    n_weeks = results["data"]["n_weeks"]

    content = (
        "SELF-CORRECTION／推翻 K1655 舊結論：原始 item 274f2886 使用 final-vintage NFCI "
        "並在指數公開前評分，因此舊 CONDITIONAL_PASS、2000 年起樣本、2008 calibration、"
        "樣本內 GaR fan 顯著與 VIX dominance 敘事全部失效。"
        f"改用 ALFRED output_type=1 真實 revision intervals 後，panel 為 {n_weeks} 週"
        f"（{sample_start}～{sample_end}）；首個 public vintage 前 "
        f"{alignment['pre_first_vintage_origins_excluded']} 個 origins 全排除。"
        "對 ^GSPC 5% return tail，H=1/4/12 的 NFCI OOS pinball 改善為 "
        f"{improvements}，DM-HLN t={dm_stats}，三格都沒有優於 unconditional empirical "
        f"quantile benchmark；PIT 樣本內斜率 p={in_p}，亦不顯著。"
        "最終 statistical verdict=NULL，independent post-run review=PASS。"
        "結論只限此 true-PIT 樣本與基準；沒有檢定 VIX encompassing，也不否定強制去槓桿機制。"
    )

    return {
        "item_id": item_id,
        "category": "growth_at_risk_equity_tail",
        "title": "K1655 true-PIT ALFRED rerun overturns the final-vintage conditional pass [NULL]",
        "content": content,
        "verdict": "NULL",
        "experiment_id": "K1655",
        "experiment_path": "experiments/K1655/",
        "supersedes": SUPERSEDES_ITEM_ID,
        "reviewer": "Codex independent post-run review PASS (2026-07-11)",
        "reviewer_source": "Codex primary-path independent post-run review",
        "codex_review": (
            "PASS limited to the true-PIT ALFRED reconstruction, timing gates, serialized "
            "forecast audit, and the narrow NULL conclusion."
        ),
        "evidence": [
            "experiments/K1655/K1655_results.json",
            "experiments/K1655/K1655_oos_forecasts.csv",
            "experiments/K1655/data/alfred_NFCI_vintage_audit.json",
            "experiments/K1655/reviews/codex_alfred_pit_postrun_2026-07-11.md",
        ],
        "confidence": 0.95,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sample": {
            "start": sample_start,
            "end": sample_end,
            "n_weeks": n_weeks,
        },
        "alfred_audit": {
            "raw_rows": raw["numeric_rows_retained"],
            "pages": raw["pages_fetched"],
            "vintage_dates": raw["vintage_dates_reported"],
            "first_public_vintage": raw["first_public_vintage"],
            "pre_first_vintage_origins_excluded": alignment[
                "pre_first_vintage_origins_excluded"
            ],
            "raw_sha256": raw["cache_sha256"],
            "derived_sha256": alignment["derived_cache_sha256"],
        },
        "primary_oos": {
            str(h): {
                key: cells[h][key]
                for key in (
                    "n",
                    "pinball_cond",
                    "pinball_uncond",
                    "pinball_reduction_pct",
                    "dm_t_hln",
                    "dm_p_hln",
                    "nw_lag",
                    "harvey_significant_better",
                )
            }
            for h in (1, 4, 12)
        },
        "forecast_artifact_sha256": artifact["sha256"],
    }


def append_knowledge(entry: dict) -> str:
    existing = _load_json(KNOWLEDGE_PATH)
    corrections = [
        row
        for row in existing
        if row.get("experiment_id") == "K1655"
        and row.get("supersedes") == SUPERSEDES_ITEM_ID
    ]
    if corrections:
        if len(corrections) != 1 or corrections[0].get("item_id") != entry["item_id"]:
            raise RuntimeError("conflicting K1655 correction already exists in knowledge.json")
        return "already_present"

    MemorySystem(storage_dir=str(ROOT / "storage"))._append_to_index(
        "knowledge.json", entry
    )
    return "appended"


def append_work_log(results: dict, entry: dict) -> str:
    with shared_state_lock("work_log", storage_dir=str(ROOT / "storage")):
        work_log = _load_json(WORK_LOG_PATH)
        matches = [row for row in work_log if row.get("task_id") == TASK_ID]
        if matches:
            if any(row.get("knowledge_item_id") != entry["item_id"] for row in matches):
                raise RuntimeError("conflicting K1655 task entry already exists in work_log")
            return "already_present"

        cells = {h: _primary_cell(results, h) for h in (1, 4, 12)}
        work_log.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "task_type": "experiment",
                "task_id": TASK_ID,
                "k_id": "K1655",
                "title": "K1655 ALFRED true-PIT NFCI correction rerun",
                "status": "succeeded",
                "verdict": "NULL",
                "actor": "codex-vscode",
                "notes": (
                    "True-PIT panel 788 weeks (2011-05-27..2026-06-26); NFCI "
                    "return-tail OOS improvement H1/H4/H12="
                    + "/".join(
                        f"{cells[h]['pinball_reduction_pct']:+.3f}%" for h in (1, 4, 12)
                    )
                    + "; independent numeric verification and post-run review PASS. "
                    "Old final-vintage CONDITIONAL_PASS and associated article claims corrected."
                ),
                "experiment_path": "experiments/K1655/",
                "knowledge_item_id": entry["item_id"],
                "supersedes_knowledge_item_id": SUPERSEDES_ITEM_ID,
            }
        )
        _atomic_write_json(WORK_LOG_PATH, work_log)
    return "appended"


def main() -> None:
    results = _load_json(RESULTS_PATH)
    entry = build_entry(results)
    knowledge_result = append_knowledge(entry)
    work_log_result = append_work_log(results, entry)
    print(
        f"K1655 correction writer PASS: knowledge={knowledge_result}, "
        f"work_log={work_log_result}, item_id={entry['item_id']}"
    )


if __name__ == "__main__":
    main()
