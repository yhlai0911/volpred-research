from __future__ import annotations

import concurrent.futures
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "topic_claim.py"
SPEC = importlib.util.spec_from_file_location("topic_claim", MODULE_PATH)
topic_claim = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(topic_claim)


def test_claim_blocks_normalized_duplicate(tmp_path) -> None:
    ledger = tmp_path / "storage" / "ops" / "topic_claims.json"

    first = topic_claim.claim_topic(
        topic=" Biodiversity   Transition-Risk Commodity Proxy ",
        claimed_by="worker-a",
        k_id="K1536",
        ledger_path=ledger,
    )
    second = topic_claim.claim_topic(
        topic="biodiversity transition-risk commodity proxy",
        claimed_by="worker-b",
        k_id="K1537",
        ledger_path=ledger,
    )

    assert first["ok"] is True
    assert second == {
        "ok": False,
        "reason": "already_claimed",
        "topic_hash": first["topic_hash"],
        "existing_k_id": "K1536",
        "existing_claimed_by": "worker-a",
        "existing_status": "claimed",
    }
    saved = json.loads(ledger.read_text(encoding="utf-8"))
    assert len(saved["claims"]) == 1


def test_released_topic_can_be_reclaimed(tmp_path) -> None:
    ledger = tmp_path / "storage" / "ops" / "topic_claims.json"
    topic_claim.claim_topic(topic="same topic", claimed_by="worker-a", ledger_path=ledger)
    released = topic_claim.set_topic_status(
        topic="same topic",
        status="released",
        updated_by="worker-a",
        ledger_path=ledger,
    )
    second = topic_claim.claim_topic(topic="same topic", claimed_by="worker-b", ledger_path=ledger)

    assert released["ok"] is True
    assert second["ok"] is True
    assert second["claimed_by"] == "worker-b"
    saved = json.loads(ledger.read_text(encoding="utf-8"))
    assert len(saved["claims"]) == 2


def test_claim_cli_is_process_atomic(tmp_path) -> None:
    ledger = tmp_path / "storage" / "ops" / "topic_claims.json"

    def claim(i: int) -> dict[str, object]:
        result = subprocess.run(
            [
                sys.executable,
                str(MODULE_PATH),
                "claim",
                "--topic",
                "Friday triple-witching closing auction concentration",
                "--owner",
                f"worker-{i}",
                "--k-id",
                f"K{1536 + i}",
                "--ledger",
                str(ledger),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(claim, range(8)))

    winners = [r for r in results if r["ok"] is True]
    losers = [r for r in results if r["ok"] is False]
    assert len(winners) == 1
    assert len(losers) == 7
    assert {r["reason"] for r in losers} == {"already_claimed"}
    assert {r["existing_k_id"] for r in losers} == {winners[0]["k_id"]}
    saved = json.loads(ledger.read_text(encoding="utf-8"))
    assert len(saved["claims"]) == 1


def test_corrupt_ledger_fails_closed(tmp_path) -> None:
    ledger = tmp_path / "storage" / "ops" / "topic_claims.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("{bad json", encoding="utf-8")

    with pytest.raises(ValueError, match="ledger unreadable"):
        topic_claim.claim_topic(topic="same topic", claimed_by="pytest", ledger_path=ledger)
