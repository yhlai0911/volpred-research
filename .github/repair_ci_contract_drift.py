#!/usr/bin/env python3
"""Apply the data and generated-file repairs for the 2026-08-06 CI drift."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_PATH = ROOT / "storage" / "memory" / "knowledge.json"
RESULT_PATH = ROOT / "experiments" / "K1815" / "K1815_results.json"
REVIEW_PATH = ROOT / "experiments" / "K1815" / "review_verdict.json"
EXPECTED_RESULT_SHA256 = (
    "b2cbbdd43628955f5a78d596357e72c889510a3b69d7291bb1613d9b87c63274"
)
ITEM_ID = "23849d7e"

ENTRY = {
    "item_id": ITEM_ID,
    "category": "experiment_result",
    "content": (
        "[K1815 review=PENDING；verdict=UNVERIFIED；暫定結果=NULL_INCREMENTAL_VALUE] "
        "以 SPY 的 22 日 forward realized volatility 為 target，restricted model 為 "
        "VIX level，augmented model 加入 F10 隔夜 VIX gap "
        "|VIX Open_t−VIX Close_{t−1}|。固定 IS/OOS 切分（IS 至 2018-12-31；"
        "OOS 2019-01-02–2026-05-28，n=1861）下，nested Clark-West "
        "t=-0.4282、one-sided p=0.6657，未達預先指定 Harvey |t|>3.0；"
        "augmented MSPE 82.1366 亦高於 baseline 81.6302。這只支持『本設計下未"
        "偵測到 F10 對 VIX 的樣本外增量預測價值』，不能證明效果不存在。"
        "reproduce_report 顯示 56/56 scalar 在預宣告容忍度內重現，但 "
        "review_verdict.json 仍是 placeholder，故依 K1259 以 UNVERIFIED 收錄；"
        "完成獨立 source-level review 前不得引用為 PASS、不得作正式論文認證。"
    ),
    "evidence": [
        (
            "experiments/K1815/K1815_results.json "
            "(sha256=b2cbbdd43628955f5a78d596357e72c889510a3b69d7291bb1613d9b87c63274)"
        ),
        (
            "experiments/K1815/reproduce_report.json "
            "(status=pass_tolerated; 56/56 scalar matches)"
        ),
        "experiments/K1815/README.md",
        (
            "experiments/K1815/review_verdict.json "
            "(placeholder; independent review pending)"
        ),
    ],
    "confidence": 0.6,
    "created_at": "2026-08-06T17:05:00+08:00",
    "k_id": "K1815",
    "experiment_id": "K1815",
    "experiment_path": "experiments/K1815",
    "verdict": "UNVERIFIED",
    "needs_human": True,
    "gap": (
        "Independent source-level review is not complete; "
        "review_verdict.json is still a placeholder."
    ),
    "provenance": {
        "recorded_by": "main-thread CI repair",
        "scientific_status": "preliminary reproduced result, not review-certified",
        "canonical_result_sha256": EXPECTED_RESULT_SHA256,
    },
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record_k1815() -> bool:
    if _sha256(RESULT_PATH) != EXPECTED_RESULT_SHA256:
        raise RuntimeError("K1815 result bytes no longer match the reviewed repair input")

    review = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
    if str(review.get("verdict", "")).strip().upper() == "PASS":
        raise RuntimeError(
            "K1815 now has a PASS review; replace the provisional record through the "
            "normal knowledge workflow instead of this repair"
        )

    knowledge = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    existing = [
        item
        for item in knowledge
        if item.get("item_id") == ITEM_ID
        or item.get("k_id") == "K1815"
        or item.get("experiment_id") == "K1815"
    ]
    if existing:
        if len(existing) != 1 or existing[0].get("verdict") != "UNVERIFIED":
            raise RuntimeError("K1815 already has a conflicting knowledge record")
        print("K1815 knowledge record already present")
        return False

    knowledge.append(ENTRY)
    KNOWLEDGE_PATH.write_text(
        json.dumps(knowledge, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    print("recorded K1815 as UNVERIFIED with human review pending")
    return True


def _sync_governance() -> None:
    subprocess.run(
        [sys.executable, "scripts/sync_governance.py", "--apply"],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [sys.executable, "scripts/sync_governance.py", "--check"],
        cwd=ROOT,
        check=True,
    )


def main() -> int:
    _record_k1815()
    _sync_governance()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
