# [alert] 控制閘 evidence source 失明 — 診斷與待套用修正

- canonical task: `alert_control_gate_source_health_20260802`
- 部門: platform_eng ｜ 產出時間: 2026-08-05 16:xx（台灣時間）
- 狀態: **診斷完成、修正已寫好但未落地**（寫入被權限閘擋下，見文末「阻塞」）

## 1. 症狀與證據（fresh 重驗，非照舊快照）

本輪以原 detector 重跑：

```
uv run python scripts/audit_control_gate_lifecycle.py
→ audit_health.healthy = false, unhealthy_source_count = 2
```

警報仍 breached，非自然解除。兩個失明的 evidence source：

| gate_id | source | error |
|---|---|---|
| `event_reaction_coverage` | `storage/next_tasks.json` | `missing_or_malformed_task_deadlines`（task `event_article_fomc_2026-07-29_tplus0`）|
| `dispatch_worker_ownership` | `storage/ops/incidents.json` | `malformed_instance_transition_rows`（`inc_792a94b0ecf4` transition 9/24/27/34）|

四筆 transition 的實際內容：

```
9 |2026-08-02T12:51:21Z|opened|worker_killed_timeout
24|2026-08-03T08:28:35Z|opened|worker_orphan_gone_or_reused
27|2026-08-03T12:17:25Z|opened|worker_killed_timeout
34|2026-08-04T16:00:13Z|opened|merge_failed
```

## 2. 根因（兩個都是結構性，不是資料髒）

### 2a. `dispatch_worker_ownership` — 詞彙表雙源漂移

- 產生端：`scripts/dispatch_supervisor/workspace.py:4493` `reason = f"worker_{worker_outcome}"`，
  以及整合路徑自己丟出的 reason（`merge_failed`、`gate_red`、`candidate_head_drift` …）。
  outcome 詞彙只以**散文**形式記在 `scripts/dispatch_supervisor/state.py:152-162`。
- 判讀端：`config/control_gate_registry.json` 的
  `incident_transition_reason_prefixes` / `incident_transition_safe_reasons` **手抄一份**。
- 兩份之間沒有任何 gate。producer 每多一個 outcome，
  `_classify_incident_transition_reason()` 就回 `unknown` → audit fail-closed → 三天後由
  `control_gate_source_health` 告警才被發現。
- 與 2026-05-27 `BLOCKED_REASONS` 漂移**同一個 class**：一套詞彙、兩份手抄、中間無閘。
  該次的處置（單一 owner 檔 `src/volpred/ops/blocked_reasons.py`）就是這次該複製的前例。

fail-closed 本身是對的，**不要改成 fail-open**；要修的是「詞彙沒有 owner」。

### 2b. `event_reaction_coverage` — compaction 砍掉下游仍要讀的欄位

`event_article_fomc_2026-07-29_tplus0` 現況：

```json
{"id":"…tplus0","status":"succeeded","tombstone":true,"archived_at":"2026-08-02T08:05:18Z"}
```

- 終態滿 3 天由 `compact_terminal_tasks()` 壓成 tombstone，只留
  `_TOMBSTONE_KEEP_FIELDS`（`src/volpred/ops/next_tasks.py:716`）——**不含 `deadline`**。
- 而 `event_reaction_coverage` 的 `deadline_required=true`，
  `_join_outcomes()`（`control_gate_lifecycle.py:1515-1522`）把「沒有 deadline」判成
  `missing_or_malformed_task_deadlines`。
- 兩邊時窗不對盤：compaction 3 天，gate review window 14 天。任何事件任務跨過第 3 天就永久
  把該 gate 的 evidence source 打成 unhealthy，且**再也不會自己好**（欄位已刪）。
- 這正是 `is_tombstoned()` docstring 已經寫下的 class J（2026-08-03 dreaming 31/32 誤判同因）：
  **凡以「某欄位不存在」下判斷的 reader，必須先問這列是不是 tombstone。**
  已經有 owner（`is_tombstoned`），這個 reader 只是沒呼叫它。

## 3. 待套用修正（四處，全部已定稿）

### P1 — `src/volpred/ops/incident.py`：建立詞彙表單一 owner

在 `#: Episode threshold at which a NEW episode escalates instead of opening yet` 這行**之前**插入：

```python
# ---------------------------------------------------------------------------
# Instance-transition reason vocabulary (single owner)
# ---------------------------------------------------------------------------
# An instance transition carries the reason that OPENED the edge, and a control
# gate reviews that reason to decide whether the edge belongs to the failure
# family it owns.  Until 2026-08-05 the vocabulary lived in two places that had
# no way to notice each other drifting apart: the producer built the string
# (``scripts/dispatch_supervisor/workspace.py`` -> ``f"worker_{outcome}"`` plus
# the merge/gate remediation reasons) while ``config/control_gate_registry.json``
# hand-listed the ones it recognised.  Every new producer outcome therefore made
# the gate's evidence source unhealthy -- correctly fail-closed, but discovered
# three days later by ``control_gate_source_health`` instead of at the edit that
# caused it (2026-08-02 alert: ``worker_killed_timeout``,
# ``worker_orphan_gone_or_reused``, ``merge_failed``).  Same shape as the
# ``BLOCKED_REASONS`` drift fixed 2026-05-27: one vocabulary, two hand-kept
# copies, no gate between them.
#
# This map is now that single owner.  ``True`` = the edge is genuine ownership
# ambiguity (nobody can say who holds the workspace); ``False`` = a verified,
# expected settlement (the producer's fate is known, including ordinary failure,
# gate red and merge failure).  Adding a producer outcome or remediation reason
# means adding it HERE; ``tests/test_incident_reason_vocabulary.py`` then fails
# until the gate registry classifies it, so the gate can never go blind again.
INSTANCE_TRANSITION_REASONS: dict[str, dict[str, bool]] = {
    "worker_orphaned": {
        # --- ownership ambiguous: the producer's fate is NOT verified ---
        "worker_orphaned": True,
        "worker_unknown_external": True,
        "worker_system_termination_unconfirmed": True,
        "worker_kill_failed_orphan": True,
        "worker_timeout_unverified": True,
        "worker_orphan_unverified_not_killed": True,
        "worker_orphan_unverified_no_pid": True,
        "worker_silent_death": True,
        "worker_reservation_abandoned_no_pid": True,
        # --- verified settlements: producer fate known, workspace not held ---
        "worker_failure": False,
        "worker_killed_timeout": False,
        "worker_killed_supervisor_restart": False,
        "worker_system_terminated": False,
        "worker_superseded": False,
        "worker_superseded_generation": False,
        "worker_orphan_gone_or_reused": False,
        "worker_reservation_lost": False,
        "worker_quota_blocked": False,
        "worker_auth_blocked": False,
        "worker_provider_policy_denied": False,
        "worker_spawn_not_started": False,
        "worker_isolation_preflight_failed": False,
        "worker_fatal_fastfail": False,
        "worker_codex_failover_failed": False,
        "worker_codex_failover_timeout": False,
        # --- verified settlements raised by the integration path itself ---
        "producer_commit_failed": False,
        "changed_path_probe_failed": False,
        "canonical_path_denied": False,
        "task_binding_missing": False,
        "undeclared_output_path": False,
        "candidate_alignment_failed": False,
        "gate_red": False,
        "candidate_head_drift": False,
        "main_advance_retry_exhausted": False,
        "merge_failed": False,
        "merge_timeout": False,
        "merge_spawn_error": False,
        "merge_script_missing": False,
        "integration_lock_busy": False,
        "integration_cas_lost": False,
        "merge_readback_failed": False,
        "post_gate_branch_advanced": False,
        "registration_verify_failed": False,
    },
}


def is_declared_transition_reason(kind: str, reason: str) -> bool:
    """True when ``reason`` is declared for ``kind`` in the vocabulary above."""
    return reason in INSTANCE_TRANSITION_REASONS.get(str(kind), {})
```

詞彙來源（每一條都可回讀，非臆造）：`state.py:152-162` 的 outcome union、
`workspace.py` 的 `_MERGEABLE_OUTCOMES`/`_PRODUCER_*_OUTCOMES`（104-115）、
以及 `workspace.py` 走進 `_remediate_workspace(reason=…)` 的所有分支
（2601/2635/2654/2658/2660/2664、3521/3551、4422、4493/4517/4550/4570/4604/4637/4701）。
分類規則只有一條：**「無法驗證 producer 下場」→ True；「下場已知」→ False。**
不確定時一律給 True（多算一次觸發是看得見的，誤放進 safe 是看不見的）。

### P2 — `src/volpred/ops/incident.py`：寫入端不再沉默

`route_breach()` 內 `_record_instance_transition(...)` 呼叫之後（約 615 行）加：

```python
            if reason_text and not is_declared_transition_reason(
                normalized_kind, reason_text
            ):
                warn(
                    "incident_store",
                    "instance transition reason is not in the declared "
                    "vocabulary; the owning control gate will read it as "
                    "unknown and fail its evidence source closed",
                    kind=normalized_kind,
                    reason=reason_text,
                    incident_id=str(row.get("incident_id") or ""),
                )
```

（把現有 inline 的 `str(instance_detail.get("reason") …)` 先抽成 `reason_text` 區域變數再傳入。）
目的：詞彙缺口在**寫入當下**就留下可搜尋的診斷，而不是三天後由 audit 才發現——
符合 `.claude/rules/no-silent-fallback.md`。

### P3 — `config/control_gate_registry.json`（`dispatch_worker_ownership.review_policy`）

`incident_transition_reason_prefixes` 追加兩條：

```json
"worker_silent_death",
"worker_reservation_abandoned_no_pid"
```

`incident_transition_safe_reasons` 換成完整已驗證集合（即 P1 表中所有 `False` 的 key）：

```json
[
  "worker_failure", "worker_killed_timeout", "worker_killed_supervisor_restart",
  "worker_system_terminated", "worker_superseded", "worker_superseded_generation",
  "worker_orphan_gone_or_reused", "worker_reservation_lost", "worker_quota_blocked",
  "worker_auth_blocked", "worker_provider_policy_denied", "worker_spawn_not_started",
  "worker_isolation_preflight_failed", "worker_fatal_fastfail",
  "worker_codex_failover_failed", "worker_codex_failover_timeout",
  "producer_commit_failed", "changed_path_probe_failed", "canonical_path_denied",
  "task_binding_missing", "undeclared_output_path", "candidate_alignment_failed",
  "gate_red", "candidate_head_drift", "main_advance_retry_exhausted",
  "merge_failed", "merge_timeout", "merge_spawn_error", "merge_script_missing",
  "integration_lock_busy", "integration_cas_lost", "merge_readback_failed",
  "post_gate_branch_advanced", "registration_verify_failed"
]
```

注意 prefix 是前綴比對：`worker_orphan_unverified` 已涵蓋
`worker_orphan_unverified_{not_killed,no_pid}`，且**不會**誤吃
`worker_orphan_gone_or_reused`。

### P4 — `src/volpred/ops/control_gate_lifecycle.py`：reader 先問是不是 tombstone

`_join_outcomes()` 內（1515 行附近）：

```python
            deadline_raw = task.get("deadline")
            deadline, malformed_deadline = _try_parse_time(deadline_raw)
            if malformed_deadline or (
                deadline_required and deadline is None
            ):
```

改為：

```python
            deadline_raw = task.get("deadline")
            deadline, malformed_deadline = _try_parse_time(deadline_raw)
            # A tombstone structurally lost ``deadline`` at compaction (3 days,
            # ``_TOMBSTONE_KEEP_FIELDS``) while gate review windows run to 14.
            # Reading that deliberate deletion as "this evidence source is
            # malformed" makes every deadline-required gate permanently
            # unhealthy from day 3 on.  The row is terminal, so no deadline
            # join below depends on it either.  Same class as the dreaming
            # false positive fixed 2026-08-03 -- see ``is_tombstoned``.
            if not is_tombstoned(task) and (
                malformed_deadline or (deadline_required and deadline is None)
            ):
```

並在 import 區（30 行 `from .shared_lock import shared_state_lock` 附近）加：

```python
from .next_tasks import is_tombstoned
```

（無循環相依：`next_tasks.py` 不 import `control_gate_lifecycle`。）

### P5 — 新檔 `tests/test_incident_reason_vocabulary.py`（機械 gate）

```python
"""The gate registry must classify every declared incident-transition reason.

2026-08-02 ``control_gate_source_health`` fired because three reasons the
dispatch supervisor emits (``worker_killed_timeout``,
``worker_orphan_gone_or_reused``, ``merge_failed``) were absent from the
``dispatch_worker_ownership`` policy, so its evidence source failed closed and
the gate went blind.  The vocabulary now has one owner
(``incident.INSTANCE_TRANSITION_REASONS``); this test is the gate between that
owner and ``config/control_gate_registry.json``, so the next added reason fails
here at commit time instead of alerting three days later.
"""
from __future__ import annotations

import json
from pathlib import Path

from volpred.ops.incident import (
    CONTROL_GATE_BY_KIND,
    INSTANCE_TRANSITION_REASONS,
)

REGISTRY = Path(__file__).resolve().parents[1] / "config/control_gate_registry.json"


def _policy(gate_id: str) -> dict:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    gates = payload["gates"] if isinstance(payload, dict) else payload
    rows = gates.values() if isinstance(gates, dict) else gates
    for row in rows:
        if row.get("gate_id") == gate_id or row.get("id") == gate_id:
            return row.get("review_policy") or {}
    raise AssertionError(f"gate {gate_id} not found in {REGISTRY}")


def test_every_declared_reason_is_classified_by_its_gate() -> None:
    for kind, reasons in INSTANCE_TRANSITION_REASONS.items():
        gate_id = CONTROL_GATE_BY_KIND[kind]
        policy = _policy(gate_id)
        prefixes = tuple(policy.get("incident_transition_reason_prefixes") or ())
        safe = set(policy.get("incident_transition_safe_reasons") or ())
        assert prefixes, f"{gate_id} declares no owned reason prefixes"
        for reason, ambiguous in reasons.items():
            owned = any(reason.startswith(p) for p in prefixes)
            if ambiguous:
                assert owned, (
                    f"{gate_id}: ownership-ambiguous reason {reason!r} matches no "
                    "owned prefix; the gate would silently exclude a real trigger"
                )
            else:
                assert owned or reason in safe, (
                    f"{gate_id}: settled reason {reason!r} is neither owned nor "
                    "safe-listed; the audit will read it as unknown and fail the "
                    "evidence source closed"
                )
```

容器形狀已回讀確認：`config/control_gate_registry.json` 頂層鍵為
`discovery,gates,owner,review_task,schema_version`，`.gates` 是 29 筆的**陣列**，
每筆帶 `gate_id`——上面的 `_policy()` 取值方式與之相符，不需再改。

### P6 — 驗證與制度化（套用者必做）

```bash
uv run --extra dev pytest tests/test_incident_reason_vocabulary.py -q
uv run --extra dev pytest tests/test_control_gate_lifecycle.py -q     # 既有回歸
uv run python scripts/audit_control_gate_lifecycle.py | tail -30      # 回讀
```

結案條件：`audit_health.healthy == true` 且 `unhealthy_source_count == 0`。
另需在 `docs/error_log.md` 記一條（class：compaction 砍掉下游仍需的欄位 / 詞彙雙源漂移），
並確認下一輪巡檢自動解除 `control_gate_source_health`。

## 4. 阻塞（本部門無法自行落地）

平台工程部在 registry 的 `owned_paths` 只有 `frontend-v2-fix/`，但本部門擁有
`platform_ops` task_type，而這張 canonical 任務的修復面全部落在
`src/volpred/ops/`、`config/`、`tests/`。本輪對 `src/volpred/ops/incident.py` 的 `Edit`
被權限閘擋下（與 2026-08-05 稍早對 `scripts/token_usage_report.py` 的拒絕同型）。

**因此：診斷與修正已全部備妥（本檔），但一行都沒有落地，警報仍在 breached。**
需要經理裁決其一：

1. 把 `src/volpred/ops/`、`config/control_gate_registry.json`、`tests/` 納入
   platform_eng 的 `owned_paths`（推薦——擁有 task_type 卻不能寫對應程式碼，
   等於這個部門所有 platform_ops 任務都無法結案）；
2. 或指派有寫入權的執行體照本檔 P1–P6 套用。
