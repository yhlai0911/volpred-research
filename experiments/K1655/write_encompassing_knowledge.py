#!/usr/bin/env python3
"""Append the reviewed K1655 VIX/NFCI encompassing addendum to memory.

This writer is append-only and idempotent.  It extends the true-PIT K1655
correction instead of superseding it because the underlying NFCI NULL remains
valid; the addendum resolves only the previously untested VIX comparison.
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
RESULTS_PATH = EXPERIMENT_DIR / "K1655_vix_nfci_encompassing_results.json"
KNOWLEDGE_PATH = ROOT / "storage" / "memory" / "knowledge.json"
WORK_LOG_PATH = ROOT / "storage" / "work_log.json"
EXTENDS_ITEM_ID = "98a3e103"
TASK_ID = "k1655_vix_nfci_encompassing"
HORIZONS = (1, 4, 12)


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


def _primary(results: dict, section: str, horizon: int) -> dict:
    return results["analysis"][section][str(horizon)]


def build_entry(results: dict) -> dict:
    if results.get("experiment_id") != "K1655_VIX_NFCI_ENCOMPASSING":
        raise RuntimeError("unexpected encompassing experiment_id")
    if results.get("review_status", {}).get("status") != "PASS":
        raise RuntimeError("encompassing results do not carry post-run PASS")

    verdict = results["analysis"]["verdict"]
    if verdict.get("overall") != "NULL_NO_DOMINANCE_OR_INCREMENTAL_EVIDENCE":
        raise RuntimeError("unexpected encompassing verdict")
    if any(verdict["pair_pass_by_horizon"].values()):
        raise RuntimeError("unexpected paired-dominance pass")
    if any(verdict["encompassing_pass_by_horizon"].values()):
        raise RuntimeError("unexpected encompassing pass")

    artifact = results["data"]["output_forecast_artifact"]
    if artifact.get("rows") != 4_970:
        raise RuntimeError("unexpected encompassing artifact row count")
    if len(artifact.get("sha256", "")) != 64:
        raise RuntimeError("missing encompassing artifact hash")

    paired = {
        h: _primary(results, "frozen_expanding_vix_vs_nfci", h)
        for h in HORIZONS
    }
    rolling = {
        h: _primary(results, "rolling_primary_vix_nfci_vs_vix_dm_diagnostic", h)
        for h in HORIZONS
    }
    cqfe = {h: _primary(results, "rolling_primary_cqfe", h) for h in HORIZONS}

    if any(paired[h]["pair_pass"] for h in HORIZONS):
        raise RuntimeError("paired result contradicts double-null verdict")
    if any(cqfe[h]["nfci_incremental_information_pass"] for h in HORIZONS):
        raise RuntimeError("CQFE result contradicts double-null verdict")
    if any(cqfe[h]["bootstrap"]["successful"] != 1_999 for h in HORIZONS):
        raise RuntimeError("incomplete CQFE bootstrap")

    identity = (
        f"K1655_VIX_NFCI_ENCOMPASSING:{artifact['sha256']}:{EXTENDS_ITEM_ID}"
    )
    item_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8]

    paired_improvement = "/".join(
        f"{paired[h]['candidate_improvement_pct']:+.3f}%" for h in HORIZONS
    )
    paired_dm = "/".join(f"{paired[h]['canonical_dm_t']:+.3f}" for h in HORIZONS)
    rolling_improvement = "/".join(
        f"{rolling[h]['candidate_improvement_pct']:+.3f}%" for h in HORIZONS
    )
    full_holm = "/".join(
        f"{cqfe[h]['vix_encompasses_joint_null']['bootstrap_p_holm']:.3f}"
        for h in HORIZONS
    )
    incremental_holm = "/".join(
        f"{cqfe[h]['incremental_lambda_joint_zero_subtest']['bootstrap_p_holm']:.3f}"
        for h in HORIZONS
    )

    content = (
        "K1655 VIX/NFCI follow-up（extends true-PIT correction 98a3e103）："
        "在相同 expanding origins 上，VIX-only 相對 NFCI-only 的 H=1/4/12 "
        f"pinball 點估改善為 {paired_improvement}，canonical DM t={paired_dm}，"
        "三格都未過 t<−3 或 Holm p<.05，因此沒有穩健 VIX dominance。"
        "固定 rolling R=400、weekly refit、strict j+H<i 的 VIX+NFCI 相對 VIX-only "
        f"點估改善為 {rolling_improvement}；CQFE 1,999-rep circular-block bootstrap "
        f"full-null Holm p={full_holm}，lambda_joint=0 Holm p={incremental_holm}。"
        "最終為雙重 null：無穩健 VIX dominance，也無 NFCI beyond-VIX 增量證據。"
        "failure to reject 不是 VIX 已涵蓋、吸收或取代 NFCI 的證明；"
        "chi-square 漸近 p 只作診斷，正式 CQFE 推論以 block bootstrap 為主。"
    )

    return {
        "item_id": item_id,
        "category": "growth_at_risk_equity_tail",
        "title": "K1655 VIX/NFCI direct comparison and CQFE yield a double null",
        "content": content,
        "verdict": verdict["overall"],
        "experiment_id": "K1655",
        "experiment_addendum_id": results["experiment_id"],
        "experiment_path": "experiments/K1655/",
        "task_id": TASK_ID,
        "extends": EXTENDS_ITEM_ID,
        "reviewer": "Codex independent numeric verification and post-run review PASS (2026-07-11)",
        "reviewer_source": "Codex primary-path independent post-run review",
        "codex_review": (
            "PASS limited to frozen-input integrity, paired loss reconstruction, "
            "fixed-window CQFE, deterministic block bootstrap, and the double-null wording."
        ),
        "evidence": [
            "experiments/K1655/K1655_vix_nfci_encompassing_results.json",
            "experiments/K1655/K1655_vix_nfci_encompassing_oos.csv",
            "experiments/K1655/K1655_vix_nfci_encompassing.py",
            "experiments/K1655/reviews/codex_vix_nfci_encompassing_postrun_2026-07-11.md",
        ],
        "confidence": 0.95,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sample": results["data"]["sample"],
        "forecast_artifact_sha256": artifact["sha256"],
        "primary_paired_vix_vs_nfci": {
            str(h): {
                key: paired[h][key]
                for key in (
                    "n",
                    "candidate_mean_loss",
                    "benchmark_mean_loss",
                    "candidate_improvement_pct",
                    "canonical_dm_t",
                    "canonical_dm_p_two_sided",
                    "canonical_dm_p_two_sided_holm",
                    "pair_pass",
                )
            }
            for h in HORIZONS
        },
        "rolling_r400_joint_vs_vix": {
            str(h): {
                "n": rolling[h]["n"],
                "candidate_improvement_pct": rolling[h]["candidate_improvement_pct"],
                "canonical_dm_t": rolling[h]["canonical_dm_t"],
                "cqfe_full_bootstrap_p_holm": cqfe[h][
                    "vix_encompasses_joint_null"
                ]["bootstrap_p_holm"],
                "cqfe_incremental_bootstrap_p_holm": cqfe[h][
                    "incremental_lambda_joint_zero_subtest"
                ]["bootstrap_p_holm"],
                "nfci_incremental_information_pass": cqfe[h][
                    "nfci_incremental_information_pass"
                ],
            }
            for h in HORIZONS
        },
    }


def append_knowledge(entry: dict) -> str:
    existing = _load_json(KNOWLEDGE_PATH)
    matches = [row for row in existing if row.get("task_id") == TASK_ID]
    if matches:
        if len(matches) != 1 or matches[0].get("item_id") != entry["item_id"]:
            raise RuntimeError("conflicting K1655 encompassing knowledge item")
        return "already_present"

    MemorySystem(storage_dir=str(ROOT / "storage"))._append_to_index(
        "knowledge.json", entry
    )
    return "appended"


def append_work_log(entry: dict) -> str:
    with shared_state_lock("work_log", storage_dir=str(ROOT / "storage")):
        work_log = _load_json(WORK_LOG_PATH)
        matches = [row for row in work_log if row.get("task_id") == TASK_ID]
        if matches:
            if any(row.get("knowledge_item_id") != entry["item_id"] for row in matches):
                raise RuntimeError("conflicting K1655 encompassing work-log item")
            return "already_present"

        work_log.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "task_type": "experiment",
                "task_id": TASK_ID,
                "k_id": "K1655",
                "title": "K1655 VIX versus true-PIT NFCI encompassing follow-up",
                "status": "succeeded",
                "verdict": entry["verdict"],
                "actor": "codex-vscode",
                "notes": (
                    "Same-origin paired DM found no robust VIX dominance; rolling R=400 "
                    "CQFE found no NFCI incremental evidence beyond VIX. Independent numeric "
                    "verification and post-run review PASS."
                ),
                "experiment_path": "experiments/K1655/",
                "knowledge_item_id": entry["item_id"],
                "extends_knowledge_item_id": EXTENDS_ITEM_ID,
            }
        )
        _atomic_write_json(WORK_LOG_PATH, work_log)
    return "appended"


def main() -> None:
    results = _load_json(RESULTS_PATH)
    entry = build_entry(results)
    knowledge_result = append_knowledge(entry)
    work_log_result = append_work_log(entry)
    print(
        f"K1655 encompassing writer PASS: knowledge={knowledge_result}, "
        f"work_log={work_log_result}, item_id={entry['item_id']}"
    )


if __name__ == "__main__":
    main()
