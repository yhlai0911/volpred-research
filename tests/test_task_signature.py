"""Semantic duplicate detection: the two empirical cases, and the brakes.

The empirical cases are the acceptance criteria the boss set on 2026-07-21 —
they are pinned here as fixtures (copied from the queue) so the tests keep
meaning after the live tickets are closed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from volpred.ops.next_tasks import append_task_record
from volpred.ops.task_signature import (
    duplicate_verdict,
    extract_signature,
    find_duplicate_groups,
    is_duplicate,
    is_recurrence_pair,
)

# --------------------------------------------------------------------------
# empirical case 1: same NameError filed twice, 15 minutes apart
# --------------------------------------------------------------------------

CASE1_A = {
    "id": "assign_614e70ee",
    "title": "修 check_alerts NameError：_ci_incident_store_sync 未定義，警報系統整條停擺",
    "description": (
        "根因已定位（2026-07-21 21:36 responder 稽核）：scripts/check_alerts.py:1788 "
        "呼叫 _ci_incident_store_sync 但該函式未定義 → NameError → main() 直接 exit 1。"
        "20:00/21:00 兩輪 cron 連續失敗。"
    ),
    "status": "pending",
    "created_at": "2026-07-21T13:38:16.665265+00:00",
}

CASE1_B = {
    "id": "assign_1d936f52",
    "title": "[P1 回歸] check_alerts.py 呼叫 _ci_incident_store_sync 但該函式不存在 — CI-red alert 路徑必崩",
    "description": (
        "## 症狀\n\nscripts/tests/test_ci_red_watchdog.py 7 條全紅：\n\n"
        "```\nNameError: name '_ci_incident_store_sync' is not defined\n"
        "scripts/check_alerts.py:1788\n```\n\n"
        "`scripts/check_alerts.py` 有 3 個呼叫點；同檔 `def _ci_incident_store_sync` 出現次數 = 0。"
    ),
    "status": "pending",
    "created_at": "2026-07-21T13:53:11.931971+00:00",
}

# --------------------------------------------------------------------------
# empirical case 2: worktree cleanup filed standalone and inside an umbrella
# --------------------------------------------------------------------------

CASE2_A = {
    "id": "assign_a5ddf2b4",
    "title": "收割並清理 3 個未合併 worktree（1+4+18 commits）",
    "description": (
        "老闆 2026-07-21 Telegram 點名「沒用的 worktree 就可以刪了吧」。實查：3 個 worktree "
        "全部有未進 main 的 commit。\n\n"
        "- wt/dispatch-slot-1-20b291d5-snapdup — 1 commit (1c30466ae)\n"
        "- wt/dispatch-slot-1-375ba0e3-k1380 — 4 commits (5070cca52)\n"
        "- wt/dispatch-slot-1-bd00f90a-k1731 — 18 commits (62bcfe5b7)\n\n"
        "做法：逐一走 scripts/merge_worktree.sh 收割。"
    ),
    "status": "pending",
    "created_at": "2026-07-21T13:52:03.874658+00:00",
}

CASE2_B = {
    "id": "assign_de13fd1b",
    "title": "[老闆直令 立即] worktree 回收 + 語意重複單合併 + commit 流程重設計（telegram-1270，三件一班做完）",
    "description": (
        "【1】worktree 回收 — 現存 3 個：\n"
        "- dispatch-slot-1-bd00f90a-k1731：lsof 顯示 cloudcode PID 23534 仍持有檔案 → 活的。\n"
        "- dispatch-slot-1-20b291d5-snapdup：無 process，走 worktree-merge-verification 回收。\n"
        "- dispatch-slot-1-375ba0e3-k1380：無 process，但收件單仍 pending。\n\n"
        "【2】任務池重複 —— scripts/dedupe_next_tasks.py 只比對完全相同的 id。\n"
        "【3】commit 流程重設計。"
    ),
    "status": "in_progress",
    "created_at": "2026-07-21T13:57:35.829313+00:00",
}

# --------------------------------------------------------------------------
# clearly-different control ticket
# --------------------------------------------------------------------------

UNRELATED = {
    "id": "assign_ffff0000",
    "title": "SPY 波動率預測：HAR-RV 加入 jump component 後重跑 QLIKE 與 DM test",
    "description": (
        "資料 2010-2025，比較 HAR-RV 與 HAR-RV-J 的 QLIKE，跑 Diebold-Mariano 檢定，"
        "結果寫入 storage/experiments/。"
    ),
    "status": "pending",
    "created_at": "2026-07-21T10:00:00+00:00",
}


class TestEmpiricalDuplicates:
    """(1) 兩組實證重複案例判為重複"""

    def test_case1_same_nameerror_filed_twice_is_duplicate(self):
        verdict = duplicate_verdict(CASE1_A, CASE1_B)
        assert verdict["duplicate"], verdict
        # matched on the substance, not on surface wording
        assert "check_alerts.py" in extract_signature(CASE1_A).files
        assert "_ci_incident_store_sync" in extract_signature(CASE1_B).symbols
        assert extract_signature(CASE1_A).failure_class == "nameerror"
        assert extract_signature(CASE1_B).failure_class == "nameerror"

    def test_case2_worktree_cleanup_standalone_vs_umbrella_is_duplicate(self):
        verdict = duplicate_verdict(CASE2_A, CASE2_B)
        assert verdict["duplicate"], verdict
        # the evidence is the shared worktree names, which no id comparison sees
        assert "worktree" in verdict["anchor"]

    def test_verdict_is_symmetric(self):
        assert is_duplicate(CASE1_A, CASE1_B) == is_duplicate(CASE1_B, CASE1_A)
        assert is_duplicate(CASE2_A, CASE2_B) == is_duplicate(CASE2_B, CASE2_A)

    def test_normalization_ignores_tag_prefix_and_dates(self):
        sig = extract_signature(CASE1_B)
        # "[P1 回歸]" must not survive into the title anchor
        assert not any(tok.startswith("[") for tok in sig.title_tokens)


class TestNoFalsePositives:
    """(2) 明顯不同的單判為不重複（防誤報）"""

    @pytest.mark.parametrize(
        "a,b",
        [
            (CASE1_A, UNRELATED),
            (CASE2_A, UNRELATED),
            (CASE1_A, CASE2_A),
            (CASE1_B, CASE2_B),
        ],
    )
    def test_unrelated_tasks_are_not_duplicates(self, a, b):
        verdict = duplicate_verdict(a, b)
        assert not verdict["duplicate"], verdict

    def test_umbrella_quoting_another_ticket_is_not_its_duplicate(self):
        """A meta-task that *quotes* a bug is not a duplicate of that bug.

        CASE2_B's body names dedupe_next_tasks.py and describes the duplicate
        problem; without the title-anchor brake it would absorb CASE1_A.
        """
        quoting = dict(CASE2_B)
        quoting["description"] += (
            "\n實證：assign_614e70ee（「修 check_alerts NameError："
            "_ci_incident_store_sync 未定義」）與 assign_1d936f52 是同一個 bug。"
        )
        verdict = duplicate_verdict(CASE1_A, quoting)
        assert not verdict["duplicate"], verdict
        assert any("no shared title anchor" in r for r in verdict["reasons"])

    def test_template_siblings_with_different_subjects_are_not_duplicates(self):
        """One generator, one ticket per item — same boilerplate, different work."""
        a = {
            "id": "dreaming_a",
            "title": "[dreaming] missing_retry_strategy:trending_repost_2026_07_17_債市波動度",
            "description": "knowledge.json 需要補 retry strategy，走 revise_knowledge_entry.py。",
            "status": "pending",
        }
        b = {
            "id": "dreaming_b",
            "title": "[dreaming] missing_retry_strategy:trending_repost_2026_07_18_台股崩跌",
            "description": "knowledge.json 需要補 retry strategy，走 revise_knowledge_entry.py。",
            "status": "pending",
        }
        verdict = duplicate_verdict(a, b)
        assert not verdict["duplicate"], verdict

    def test_scheduled_recurrence_is_not_a_duplicate(self):
        """Today's digest is not yesterday's digest."""
        assert is_recurrence_pair("daily_digest_20260719", "daily_digest_20260721")
        assert is_recurrence_pair("alert_host_cron_fail_20260719", "alert_host_cron_fail_20260720")
        # different jobs must not be swallowed by the recurrence rule
        assert not is_recurrence_pair("daily_digest_20260719", "weekly_digest_20260719")
        assert not is_recurrence_pair("assign_614e70ee", "assign_1d936f52")

    def test_clustering_does_not_chain_through_a_vague_ticket(self):
        """Groups are cliques: A~B and B~C must not imply A~C."""
        vague = {
            "id": "dreaming_vague",
            "title": "[dreaming] missing_retry_strategy:trending_repost",
            "description": "knowledge.json 需要補 retry strategy。",
            "status": "pending",
        }
        a = {
            "id": "dreaming_x",
            "title": "[dreaming] missing_retry_strategy:trending_repost_2026_07_17_債市波動度",
            "description": "knowledge.json 需要補 retry strategy。",
            "status": "pending",
        }
        b = {
            "id": "dreaming_y",
            "title": "[dreaming] missing_retry_strategy:trending_repost_2026_07_18_台股崩跌",
            "description": "knowledge.json 需要補 retry strategy。",
            "status": "pending",
        }
        groups = find_duplicate_groups([vague, a, b])
        for g in groups:
            ids = {g["keep_id"], *g["merge_ids"]}
            assert not {"dreaming_x", "dreaming_y"} <= ids, (
                "x and y are mutually non-duplicate; the vague ticket must not chain them"
            )


class TestFindDuplicateGroups:
    def test_groups_the_empirical_pair_and_keeps_the_earlier_ticket(self):
        groups = find_duplicate_groups([CASE1_B, CASE1_A, UNRELATED])
        assert len(groups) == 1
        assert groups[0]["keep_id"] == "assign_614e70ee"  # earliest created_at
        assert groups[0]["merge_ids"] == ["assign_1d936f52"]

    def test_unrelated_task_forms_no_group(self):
        assert find_duplicate_groups([CASE1_A, UNRELATED]) == []


class TestCreationEntryPointGate:
    """(3) 建單入口確實擋得下重複"""

    @staticmethod
    def _queue(tmp_path: Path) -> Path:
        q = tmp_path / "next_tasks.json"
        q.write_text("[]\n", encoding="utf-8")
        return q

    def test_gate_refuses_semantic_duplicate_at_creation(self, tmp_path):
        queue = self._queue(tmp_path)

        _first, created = append_task_record(dict(CASE1_A), path=queue)
        assert created is True

        second, created = append_task_record(dict(CASE1_B), path=queue)
        assert created is False, "semantic duplicate must not be admitted"
        assert second["duplicate_of"] == "assign_614e70ee"
        assert second["duplicate_reason"]

        rows = json.loads(queue.read_text(encoding="utf-8"))
        assert [r["id"] for r in rows] == ["assign_614e70ee"], "queue must not grow"

    def test_gate_admits_a_genuinely_different_task(self, tmp_path):
        queue = self._queue(tmp_path)
        append_task_record(dict(CASE1_A), path=queue)

        record, created = append_task_record(dict(UNRELATED), path=queue)
        assert created is True
        assert "duplicate_of" not in record

        rows = json.loads(queue.read_text(encoding="utf-8"))
        assert len(rows) == 2

    def test_gate_ignores_closed_tasks(self, tmp_path):
        """A closed ticket is history — refiling the same failure is legitimate."""
        queue = self._queue(tmp_path)
        closed = dict(CASE1_A)
        closed["status"] = "succeeded"
        append_task_record(closed, path=queue)

        _record, created = append_task_record(dict(CASE1_B), path=queue)
        assert created is True
        assert len(json.loads(queue.read_text(encoding="utf-8"))) == 2

    def test_gate_can_be_disabled_explicitly(self, tmp_path):
        queue = self._queue(tmp_path)
        append_task_record(dict(CASE1_A), path=queue)

        _record, created = append_task_record(
            dict(CASE1_B), path=queue, semantic_dedupe=False
        )
        assert created is True

    def test_dedupe_exempt_records_bypass_the_gate(self, tmp_path):
        queue = self._queue(tmp_path)
        append_task_record(dict(CASE1_A), path=queue)

        exempt = dict(CASE1_B)
        exempt["dedupe_exempt"] = True
        _record, created = append_task_record(exempt, path=queue)
        assert created is True

    def test_exact_id_duplicate_still_short_circuits(self, tmp_path):
        """The pre-existing id check must keep working ahead of the new gate."""
        queue = self._queue(tmp_path)
        append_task_record(dict(CASE1_A), path=queue)

        _record, created = append_task_record(dict(CASE1_A), path=queue)
        assert created is False
        assert len(json.loads(queue.read_text(encoding="utf-8"))) == 1
