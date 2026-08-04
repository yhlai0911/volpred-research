"""Persistent incident for foreign paths PHASE-Z can never clear (decision doc §4 D3).

外部第二意見的逐字結論：**「若 CRITICAL 不會改變 scheduler 行為，它只是紅色日誌。」**

PHASE-Z 對「某些檔案卡在工作區、沒有人會回來收」這件事，本來只做了一件事：發
CRITICAL 信（3/6/12/24… 班退避）。警報有正常送出，78 班零行動 —— 因為那是
*notification*，不是 *控制流程*：

* 沒有單一 owner（信寄給所有人＝寄給沒有人）；
* 沒有 deadline（永遠不會逾期，所以永遠不急）；
* 對 scheduler 零影響（工作區越髒，派工照樣全速）；
* 未解決不影響後續 fire（下一班照跑，把同一批檔案再數一次）。

這個模組把那封信換成一張**持久 incident**，並讓它變成 scheduler 讀得到的訊號：

1. **一組卡住路徑 = 一張任務**（``upsert_incident``）。dedup key 是路徑集合的穩定
   fingerprint，不是標題、不是時間。第 2..N 班是**更新**（班數 / quarantine ref /
   last_seen_at），不是新增。路徑集合真的改變時可建立 successor row，但只要同類
   incident family 仍有未關 row，``page_required`` 就維持 False：owner、close
   condition 與 scheduler consequence 都已存在，重寄 CRITICAL 只是在堆疊通知管道。
2. **未關 → 降載**（``open_incidents``）。唯一 enforcement owner 是
   ``scripts/dispatch_slot_budget.py``，形狀比照既有的 ``auth_blocked → DERATE_CAP``。
   這裡只**提供訊號**，不自己開第二個 gate。
3. **關閉條件是機械可驗的**（``incident_closeable``），不是「有人覺得處理完了」。
   每個 dirty path 必須有 live workspace **或** immutable quarantine ref 覆蓋，
   而且不能還髒在 main checkout 裡。少一個就關不掉。

刻意不做的事：這裡沒有任何「這些 bytes 是誰的」推測。D1 明令停止猜測式收編，
incident 只回答「還卡著嗎 / 收拾乾淨了嗎」，不回答「該不該進 main」。
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import re
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from volpred.canonical_write import guard_canonical_write

from .diagnostics import warn
from .next_tasks import (
    TERMINAL_COMPACTABLE_STATUSES,
    append_task_record,
    write_tasks_to_handle,
)

#: 這類 incident 在任務池裡的識別標記（存在 ``payload`` 裡，不靠標題比對）。
INCIDENT_KIND = "phase_z_foreign_stuck"

#: PHASE-Z quarantine checkpoint 的 ref namespace。單一 owner 在這裡，
#: ``phase_z._FOREIGN_QUARANTINE_REF_PREFIX`` 是它的別名 —— 兩份字面值會在
#: 其中一份被改時無聲分岔，而分岔的後果是「保存了但檢查不到」。
QUARANTINE_REF_PREFIX = "refs/volpred/quarantine"

#: 終局狀態＝incident 已關。``blocked`` / ``blocked_on_user`` 刻意**不算關閉**：
#: 檔案還卡著，降載就該繼續生效，否則「先擋著」會變成靜音鍵。
_CLOSED_STATUSES = TERMINAL_COMPACTABLE_STATUSES

_GIT_TIMEOUT_S = 30
_FAMILY_PAGE_CLAIM_SCHEMA = 2
_FAMILY_PAGE_LEASE_TTL = timedelta(minutes=10)

#: 一個**已被覆蓋**的 dirty path 多久沒被動過，才算「沒有人會回來收」。
#:
#: 關閉條件原本只問「還髒不髒」，而髒有兩種完全不同的成因：沒人要的殘留，和作者
#: 正在寫的活躍碼。對後者收緊只會兩頭落空 —— 作者每存一次檔，deadline 就重置一次，
#: 於是 incident 永遠關不掉（沒有出口，違反本 class 自己的「有限班數內必達 terminal
#: state」），而代價是每班 slot cap 減半，懲罰的正是**還在工作的人**。
#: 2026-07-21：``scripts/detect_price_split_breaks.py`` 已 quarantine（bytes 取得回）、
#: 2 小時前才改過、狀態 ``MM``，卻是全池唯一的 blocker，把整條排程壓在 DERATE_CAP。
#:
#: 用 mtime 而不是自我宣告：這一樣是機械判準，不是「有人覺得處理完了」。而且它會
#: 自己過期 —— 作者收尾（檔案進 commit，不再 dirty）或放手（超過寬限，重新變成
#: blocker），兩條路都通往 terminal state。
LIVE_AUTHORING_GRACE_S = 24 * 3600


# ── fingerprint ──────────────────────────────────────────────────────────────

def fingerprint(paths: Iterable[str]) -> str:
    """Stable id for one *set* of stuck paths.

    去重複、排序後 hash：同一批檔案不論這班以什麼順序被列出、streak 數字怎麼變，
    fingerprint 都一樣，所以第 2..N 班找得到第 1 班那張單。反過來，卡住的檔案集合
    真的變了（多一個 / 少一個），那就是**另一個**狀況，理當是另一張單 —— 用內容
    而不是時間當 key，就是為了讓這兩件事自動分開。
    """
    unique = sorted({str(p) for p in paths if str(p)})
    digest = hashlib.sha256("\n".join(unique).encode("utf-8")).hexdigest()
    return digest[:16]


# ── task-pool access ─────────────────────────────────────────────────────────

def _load_tasks(handle) -> list[Any]:
    handle.seek(0)
    raw = handle.read().strip()
    tasks = json.loads(raw) if raw else []
    if not isinstance(tasks, list):
        raise ValueError("next_tasks.json root is not a list")
    return tasks


def _is_incident(task: Any) -> bool:
    if not isinstance(task, dict):
        return False
    payload = task.get("payload")
    return isinstance(payload, dict) and payload.get("incident_kind") == INCIDENT_KIND


def _is_open(task: dict) -> bool:
    return str(task.get("status") or "").strip().lower() not in _CLOSED_STATUSES


def _ensure_dispatch_contract(task: dict[str, Any]) -> bool:
    """Materialize the supervisor contract owned by a PHASE-Z incident.

    These incidents never own repository mutations: ownership decisions must go
    through ``foreign_disposition`` on the canonical checkout.  The task is
    still agent-dispatchable, so the contract has to say that explicitly.  The
    helper only fills fields that this incident generator owns and leaves a
    conflicting non-empty value untouched; the dispatcher will then fail closed
    instead of silently changing an operator's declared write intent.

    Returning whether anything changed lets callers wake the supervisor exactly
    once when repairing rows created by older versions of this generator.
    """
    changed = False
    defaults: dict[str, Any] = {
        "dispatch_lane": "agent",
        "dispatch_preempt": True,
        "write_intent": "observe_only",
        "declared_output_paths": [],
        "post_merge_actions": [],
    }
    for key, expected in defaults.items():
        current = task.get(key)
        missing = key not in task or current is None or current == ""
        if missing:
            # Lists must be copied per task; sharing the default list would let
            # one caller mutate the contract of every later incident.
            task[key] = list(expected) if isinstance(expected, list) else expected
            changed = True
    return changed


def _repair_dispatch_contract(path: Path, task_id: str) -> bool:
    """Repair one legacy incident row through the canonical queue writer."""
    guard_canonical_write(path)
    with path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            tasks = _load_tasks(handle)
            target = next(
                (
                    task for task in tasks
                    if isinstance(task, dict) and str(task.get("id") or "") == task_id
                ),
                None,
            )
            if target is None or not _is_incident(target):
                return False
            changed = _ensure_dispatch_contract(target)
            if changed:
                write_tasks_to_handle(handle, tasks)
            return changed
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _request_incident_dispatch(path: Path, task_id: str, fingerprint_value: str) -> dict[str, Any]:
    """Wake the single supervisor after an incident is created or repaired.

    This is only a durable out-of-band wake-up.  ``request_fire`` never claims
    or spawns a parallel worker; an occupied slot remains authoritative.
    Scratch/test queues are explicitly prevented from touching production state.
    """
    # Refractory: episode 2+ of a fingerprint means a fire was already burned
    # on episode 1 and did not discharge it. Waking the supervisor again buys
    # a repeat of the same read-only diagnosis at the cost of a whole slot —
    # four fires went that way on 2026-08-04 alone. The durable row stays (a
    # cron fire or the repair task can still pick it up); only the out-of-band
    # wake-up is suppressed.
    episode = re.search(r"-e(\d+)$", task_id)
    if episode and int(episode.group(1)) >= 2:
        return {"requested": False, "reason": "repeat_episode_refractory"}
    repo_root = Path(__file__).resolve().parents[3]
    canonical = (repo_root / "storage" / "next_tasks.json").resolve()
    try:
        if path.resolve() != canonical:
            return {"requested": False, "reason": "non_production_storage"}
    except OSError:
        return {"requested": False, "reason": "queue_path_unresolvable"}
    try:
        from scripts.dispatch_supervisor import state as dispatch_state

        dispatch_state.request_fire(
            f"phase_z_incident:{fingerprint_value}:{task_id}"[:200]
        )
    except Exception as exc:  # noqa: BLE001 — durable task remains, wake failure stays visible
        warn(
            "foreign_incident",
            "incident task admitted but dispatcher wake failed",
            task_id=task_id,
            fingerprint=fingerprint_value,
            err=f"{type(exc).__name__}: {exc}",
        )
        return {"requested": False, "reason": "dispatch_wake_failed", "error": str(exc)}
    return {"requested": True, "reason": "incident_task_admitted_dispatch_requested"}


def open_incidents(tasks_path: str | Path) -> list[dict]:
    """Every unclosed PHASE-Z stuck-path incident in the queue.

    Read-only and never raises: this is on the scheduler's hot path, and a queue
    it cannot parse must not take dispatch down. An unreadable queue means "no
    incident signal" and says so out loud (no silent fallback).
    """
    path = Path(tasks_path)
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        warn("foreign_incident", f"讀不到任務池 {path} ({exc}) — 當作沒有未關 incident")
        return []
    try:
        tasks = json.loads(raw) if raw else []
    except json.JSONDecodeError as exc:
        warn("foreign_incident", f"任務池 {path} 無法解析 ({exc}) — 當作沒有未關 incident")
        return []
    if not isinstance(tasks, list):
        warn("foreign_incident", f"任務池 {path} 根節點不是 list — 當作沒有未關 incident")
        return []
    return [t for t in tasks if _is_incident(t) and _is_open(t)]


def _page_leases(payload: dict[str, Any]) -> list[dict[str, str]]:
    """Read canonical list leases plus the bounded scalar pre-schema shape."""
    leases: list[dict[str, str]] = []
    raw = payload.get("family_page_leases")
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            token = str(item.get("token") or "")
            leased_at = str(item.get("leased_at") or "")
            if token and leased_at:
                leases.append(
                    {
                        "token": token,
                        "leased_at": leased_at,
                        "by": str(item.get("by") or ""),
                        "transport_id": str(
                            item.get("transport_id")
                            or payload.get("family_transport_id")
                            or ""
                        ),
                    }
                )
    scalar_token = str(payload.get("family_page_lease_token") or "")
    scalar_at = str(payload.get("family_page_lease_at") or "")
    if scalar_token and scalar_at and not any(
        lease["token"] == scalar_token for lease in leases
    ):
        leases.append(
            {
                "token": scalar_token,
                "leased_at": scalar_at,
                "by": str(payload.get("family_page_lease_by") or ""),
                "transport_id": str(
                    payload.get("family_transport_id") or ""
                ),
            }
        )
    return leases


def _family_transport_ids(
    payload: dict[str, Any],
    *,
    fallback: str = "",
) -> list[str]:
    """Return the stable primary id plus every predecessor transport alias."""
    candidates = [
        str(payload.get("family_transport_id") or fallback),
        *[
            str(value)
            for value in (payload.get("family_transport_alias_ids") or [])
            if isinstance(value, str)
        ],
        *[
            str(lease.get("transport_id") or "")
            for lease in _page_leases(payload)
        ],
    ]
    return list(dict.fromkeys(value for value in candidates if value))


def _store_family_transport_ids(
    payload: dict[str, Any],
    transport_ids: Sequence[str],
) -> str:
    """Persist one primary identity without discarding merged-family aliases."""
    unique = list(
        dict.fromkeys(str(value) for value in transport_ids if str(value))
    )
    if not unique:
        payload.pop("family_transport_id", None)
        payload.pop("family_transport_alias_ids", None)
        return ""
    primary = unique[0]
    payload["family_transport_id"] = primary
    if len(unique) > 1:
        payload["family_transport_alias_ids"] = unique[1:]
    else:
        payload.pop("family_transport_alias_ids", None)
    return primary


def _store_page_leases(
    payload: dict[str, Any],
    leases: Sequence[dict[str, str]],
) -> None:
    payload.pop("family_page_lease_token", None)
    payload.pop("family_page_lease_at", None)
    payload.pop("family_page_lease_by", None)
    deduped = {
        str(lease.get("token") or ""): {
            "token": str(lease.get("token") or ""),
            "leased_at": str(lease.get("leased_at") or ""),
            "by": str(lease.get("by") or ""),
            "transport_id": str(lease.get("transport_id") or ""),
        }
        for lease in leases
        if str(lease.get("token") or "")
        and str(lease.get("leased_at") or "")
    }
    if deduped:
        payload["family_page_leases"] = list(deduped.values())
    else:
        payload.pop("family_page_leases", None)


def _claim_related_family_page(
    tasks_path: Path,
    task_id: str,
    *,
    now: datetime,
) -> tuple[bool, bool, str | None, str | None, list[str]]:
    """Atomically lease one page for the target's overlapping incident component.

    Exact path-set fingerprints identify task rows, not notification episodes.
    An episode is the transitive connected component of open rows that share at
    least one path. Thus ``{A}`` → ``{A, B}`` → ``{B}`` stays one page, while a
    disjoint ``{C}`` remains a genuinely new condition and gets its own page.

    The lease is persisted under the queue's ``LOCK_EX``. This closes both races:
    concurrent different fingerprints cannot each page one overlapping episode,
    and two callers deduped to the same task id cannot both page it.

    Rows created before this schema already used ``created=True`` to page. Their
    missing schema marker is migrated as already delivered, preventing a one-time
    rollout resend. A new claim is only a ten-minute lease; ``settle_family_page``
    turns it into a durable delivery acknowledgement after ``alert_fn`` returns.
    A crash or failed delivery therefore expires/retries instead of silently
    suppressing the episode forever.
    """
    with tasks_path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            tasks = _load_tasks(handle)
            rows = [
                task
                for task in tasks
                if _is_incident(task) and _is_open(task)
            ]
            target = next(
                (task for task in rows if str(task.get("id") or "") == task_id),
                None,
            )
            if target is None:
                return False, False, None, None, []

            component: list[dict] = [target]
            component_ids = {str(target.get("id") or "")}
            component_paths = set((target.get("payload") or {}).get("paths") or [])
            changed = True
            while changed:
                changed = False
                for row in rows:
                    row_id = str(row.get("id") or "")
                    if row_id in component_ids:
                        continue
                    row_paths = set((row.get("payload") or {}).get("paths") or [])
                    if component_paths.isdisjoint(row_paths):
                        continue
                    component.append(row)
                    component_ids.add(row_id)
                    component_paths.update(row_paths)
                    changed = True

            owner = min(
                component,
                key=lambda task: (
                    str(task.get("created_at") or ""),
                    str(task.get("id") or ""),
                ),
            )
            owner_payload = owner.setdefault("payload", {})
            transport_ids = _family_transport_ids(
                owner_payload,
                fallback=str(owner.get("id") or task_id),
            )
            for row in component:
                row_payload = row.setdefault("payload", {})
                for candidate in _family_transport_ids(
                    row_payload,
                    fallback=str(row.get("id") or ""),
                ):
                    if candidate not in transport_ids:
                        transport_ids.append(candidate)
            transport_id = transport_ids[0]
            for row in component:
                _store_family_transport_ids(
                    row.setdefault("payload", {}),
                    transport_ids,
                )

            delivered_row = next(
                (
                    row
                    for row in component
                    if (row.get("payload") or {}).get(
                        "family_page_delivered_at"
                    )
                ),
                None,
            )
            if delivered_row is not None:
                delivered_payload = delivered_row.get("payload") or {}
                for row in component:
                    row_payload = row.setdefault("payload", {})
                    row_payload["family_page_delivered_at"] = (
                        delivered_payload["family_page_delivered_at"]
                    )
                    row_payload["family_page_delivered_by"] = (
                        delivered_payload.get("family_page_delivered_by")
                        or "component_delivery_projection"
                    )
                    _store_family_transport_ids(row_payload, transport_ids)
                write_tasks_to_handle(handle, tasks)
                return True, False, None, transport_id, transport_ids

            legacy_component = any(
                int(
                    (row.get("payload") or {}).get(
                        "family_page_claim_schema", 0
                    )
                    or 0
                )
                == 0
                for row in component
            )
            if legacy_component:
                delivered_at = str(owner.get("created_at") or now.isoformat())
                for row in component:
                    row_payload = row.setdefault("payload", {})
                    row_payload["family_page_claim_schema"] = (
                        _FAMILY_PAGE_CLAIM_SCHEMA
                    )
                    row_payload["family_page_delivered_at"] = delivered_at
                    row_payload["family_page_delivered_by"] = (
                        "legacy_created_receipt_migration"
                    )
                    _store_family_transport_ids(row_payload, transport_ids)
                write_tasks_to_handle(handle, tasks)
                return True, False, None, transport_id, transport_ids

            active_leases: list[dict[str, str]] = []
            for row in component:
                row_payload = row.get("payload") or {}
                row_payload["family_page_claim_schema"] = (
                    _FAMILY_PAGE_CLAIM_SCHEMA
                )
                active_leases.extend(
                    lease
                    for lease in _page_leases(row_payload)
                    if _page_lease_is_active(lease, now=now)
                )
                _store_page_leases(row_payload, [])

            # Normalize every in-flight predecessor token onto the component
            # owner before successor retirement. This makes outstanding leases
            # visible to the next open-component election and prevents a third
            # pager while another root's receipt is still in flight.
            _store_page_leases(owner_payload, active_leases)
            if active_leases:
                write_tasks_to_handle(handle, tasks)
                return True, False, None, transport_id, transport_ids

            token = uuid.uuid4().hex
            _store_page_leases(
                owner_payload,
                [
                    {
                        "token": token,
                        "leased_at": now.isoformat(),
                        "by": task_id,
                        "transport_id": transport_id,
                    }
                ],
            )
            write_tasks_to_handle(handle, tasks)
            return True, True, token, transport_id, transport_ids
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _page_lease_is_active(lease: dict[str, str], *, now: datetime) -> bool:
    token = str(lease.get("token") or "")
    raw = lease.get("leased_at")
    if not token or not isinstance(raw, str):
        return False
    try:
        leased_at = datetime.fromisoformat(raw)
    except ValueError:  # silent-ok: malformed/old lease is stale evidence and must not suppress retry
        return False
    if leased_at.tzinfo is None or leased_at.utcoffset() is None:
        return False
    age = now - leased_at.astimezone(timezone.utc)
    # Concurrent callers capture ``now`` before waiting for the queue lock. The
    # later lock holder can therefore carry a timestamp a few microseconds older
    # than the lease it observes. Treat bounded negative skew as active; only a
    # lease implausibly far in the future is corrupt/stale evidence.
    return -_FAMILY_PAGE_LEASE_TTL < age < _FAMILY_PAGE_LEASE_TTL


def settle_family_page(
    tasks_path: str | Path,
    *,
    token: str,
    delivered: bool,
    now: datetime | None = None,
) -> bool:
    """Acknowledge delivery or release the lease so the next fire can retry."""
    if not token:
        return False
    current = now or datetime.now(timezone.utc)
    path = Path(tasks_path)
    guard_canonical_write(path)
    with path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            tasks = _load_tasks(handle)
            owner = next(
                (
                    task
                    for task in tasks
                    if _is_incident(task)
                    and any(
                        lease["token"] == token
                        for lease in _page_leases(task.get("payload") or {})
                    )
                ),
                None,
            )
            if owner is None:
                return False
            payload = owner.setdefault("payload", {})
            _store_page_leases(
                payload,
                [
                    lease
                    for lease in _page_leases(payload)
                    if lease["token"] != token
                ],
            )
            if delivered:
                # A wider set can connect two independently leased components.
                # One token moves onto the successor; additional tokens remain
                # on their superseded rows. Follow ``superseded_by`` so success
                # from *any* predecessor acknowledges the live representative,
                # rather than disappearing into a terminal audit row.
                by_id = {
                    str(task.get("id") or ""): task
                    for task in tasks
                    if isinstance(task, dict)
                }
                destination = owner
                seen: set[str] = set()
                while True:
                    destination_id = str(destination.get("id") or "")
                    if destination_id in seen:
                        break
                    seen.add(destination_id)
                    successor_id = str(
                        destination.get("superseded_by") or ""
                    )
                    successor = by_id.get(successor_id)
                    if successor is None or not _is_incident(successor):
                        break
                    destination = successor

                # Delivery belongs to the whole currently-open overlap
                # component, not merely the row that happened to own the token.
                # AB and BC are the same notification family even though neither
                # is a subset; projecting under this same queue lock ensures BC
                # cannot lose the acknowledgement if AB closes immediately.
                component = [destination]
                component_ids = {str(destination.get("id") or "")}
                component_paths = set(
                    (destination.get("payload") or {}).get("paths") or []
                )
                changed = True
                while changed:
                    changed = False
                    for row in tasks:
                        if not (
                            isinstance(row, dict)
                            and _is_incident(row)
                            and _is_open(row)
                        ):
                            continue
                        row_id = str(row.get("id") or "")
                        if row_id in component_ids:
                            continue
                        row_paths = set(
                            (row.get("payload") or {}).get("paths") or []
                        )
                        if component_paths.isdisjoint(row_paths):
                            continue
                        component.append(row)
                        component_ids.add(row_id)
                        component_paths.update(row_paths)
                        changed = True

                transport_ids = _family_transport_ids(
                    payload,
                    fallback=str(owner.get("id") or ""),
                )
                for row in component:
                    for candidate in _family_transport_ids(
                        row.setdefault("payload", {}),
                        fallback=str(row.get("id") or ""),
                    ):
                        if candidate not in transport_ids:
                            transport_ids.append(candidate)
                for row in component:
                    row_payload = row.setdefault("payload", {})
                    row_payload["family_page_claim_schema"] = (
                        _FAMILY_PAGE_CLAIM_SCHEMA
                    )
                    row_payload["family_page_delivered_at"] = (
                        current.isoformat()
                    )
                    row_payload["family_page_delivered_by"] = "alert_receipt"
                    _store_family_transport_ids(row_payload, transport_ids)
                    _store_page_leases(row_payload, [])
            write_tasks_to_handle(handle, tasks)
            return True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _describe(paths: Sequence[str], streaks: dict[str, int], fires: int,
              quarantine_refs: Sequence[str]) -> str:
    worst = max((streaks.get(p, 0) for p in paths), default=0)
    lines = [
        "## 發生什麼",
        f"{len(paths)} 個未提交檔案不是任何一班 fire 產出的，最長已連續 {worst} 班還在工作區。"
        "連續多班沒清，代表沒有人會回來收；工作區越髒，每一班「誰擁有這個檔案」的判斷就越不可靠。",
        "",
        "## 為什麼是一張任務而不是一封信",
        "這張單未關就會**壓低 scheduler 的 slot cap**（`scripts/dispatch_slot_budget.py`）。"
        "也就是說，不處理它的代價是每班能派的工變少 —— 這是它和以前那封 CRITICAL 的唯一差別。",
        "",
        "## 關閉條件（機械可驗，不是自我宣告）",
        "`uv run python -m volpred.ops.foreign_incident --check` 全綠才可關：",
        "每個路徑都要有 live workspace 或 quarantine ref 覆蓋，且不得還髒在 main checkout。",
        "",
        f"## 卡住的檔案（連續班數；本班第 {fires} 次觀察到這組）",
        *[f"- {p} — {streaks.get(p, 0)} 班" for p in paths[:30]],
        *(["- …"] if len(paths) > 30 else []),
    ]
    if quarantine_refs:
        lines += [
            "",
            "## 已保存（可取回）",
            "bytes 已 checkpoint 進不可變 ref（保存，不是收養，也進不了 main）：",
            *[f"- `git show {ref}:<路徑>`" for ref in quarantine_refs[-5:]],
        ]
    return "\n".join(lines)


def upsert_incident(
    *,
    paths: Sequence[str],
    streaks: dict[str, int] | None = None,
    quarantine_ref: str | None = None,
    tasks_path: str | Path = "storage/next_tasks.json",
    now: datetime | None = None,
) -> dict[str, Any]:
    """建/更新**一張** incident。回傳 receipt，含 ``created``（是否為新單）。

    ``page_required`` 是 alert 收編的開關；為 true 時同時回傳
    ``page_claim_token``。caller 只有在 alert receipt 證明 delivered／deduped 後，
    才能用 ``settle_family_page`` 把 lease 轉成 durable acknowledgement。第 2..N 班
    找到同 fingerprint 的未關單，就只更新班數 / ref / last_seen_at；集合增減而建立
    successor row 時，也沿用同一個已通知 episode，不再發信。

    建立走 ``next_tasks.append_task_record``（canonical record append gateway），
    並以 fingerprint + episode generation 衍生 deterministic id、關閉 generic
    semantic dedupe：incident 自己的 exact fingerprint 是較強的 identity，generic
    matcher 把普通 task 當成 duplicate 會造成「沒有 incident、沒有 page、沒有
    derate」的黑洞。generation 讓 terminal episode 保留 audit row 後，同路徑再次
    發生仍能重開；concurrent reopen 在同一 snapshot 算出相同 id，由 gateway 去重。
    更新走 ``write_tasks_to_handle``（唯一 canonical serializer）。這裡沒有第二條
    寫入路徑，因為任務池被截斷過一次就夠了（incident 2026-07-05）。
    """
    now = now or datetime.now(timezone.utc)
    ordered = sorted({str(p) for p in paths if str(p)})
    receipt: dict[str, Any] = {
        "fingerprint": None, "task_id": None, "created": False,
        "updated": False, "page_required": False, "page_claim_token": None,
        "page_transport_id": None, "page_transport_alias_ids": [],
        "reason": "", "fires": 0,
        "dispatch_request": {"requested": False, "reason": "not_needed"},
    }
    if not ordered:
        receipt["reason"] = "no_stuck_paths"
        return receipt

    fp = fingerprint(ordered)
    receipt["fingerprint"] = fp
    streaks = streaks or {}
    path = Path(tasks_path)
    guard_canonical_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("[]\n", encoding="utf-8")

    # Phase 1: 同 fingerprint 的未關單存在 → 就地更新，鎖內完成。
    existing_task_id: str | None = None
    episode_generation = 1
    with path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            tasks = _load_tasks(handle)
            same_fingerprint = [
                task
                for task in tasks
                if _is_incident(task)
                and (task.get("payload") or {}).get("fingerprint") == fp
            ]
            existing = next(
                (task for task in same_fingerprint if _is_open(task)),
                None,
            )
            if existing is not None:
                payload = existing["payload"]
                contract_repaired = _ensure_dispatch_contract(existing)
                payload["fires"] = int(payload.get("fires", 1)) + 1
                payload["streaks"] = {p: int(streaks.get(p, 0)) for p in ordered}
                payload["last_seen_at"] = now.isoformat()
                if quarantine_ref:
                    refs = payload.setdefault("quarantine_refs", [])
                    if quarantine_ref not in refs:
                        refs.append(quarantine_ref)
                existing["description"] = _describe(
                    ordered, payload["streaks"], payload["fires"],
                    payload.get("quarantine_refs", []),
                )
                existing["updated_at"] = now.isoformat()
                write_tasks_to_handle(handle, tasks)
                receipt.update({
                    "task_id": existing.get("id"), "updated": True,
                    "reason": "updated_existing", "fires": payload["fires"],
                })
                receipt["contract_repaired"] = contract_repaired
                existing_task_id = str(existing.get("id") or "")
            else:
                generations = [
                    int((task.get("payload") or {}).get("episode_generation"))
                    for task in same_fingerprint
                    if isinstance(
                        (task.get("payload") or {}).get("episode_generation"),
                        int,
                    )
                ]
                episode_generation = max(
                    [len(same_fingerprint), *generations],
                    default=0,
                ) + 1
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    if existing_task_id is not None:
        persisted, page_required, page_token, transport_id, transport_ids = (
            _claim_related_family_page(
                path, existing_task_id, now=now,
            )
        )
        receipt["page_required"] = persisted and page_required
        receipt["page_claim_token"] = page_token
        receipt["page_transport_id"] = transport_id
        receipt["page_transport_alias_ids"] = [
            value for value in transport_ids if value != transport_id
        ]
        if receipt.get("contract_repaired"):
            receipt["dispatch_request"] = _request_incident_dispatch(
                path, existing_task_id, fp,
            )
        return receipt

    # Phase 2: 沒有未關的同 fingerprint 單 → 走 canonical append gateway。
    # 鎖已釋放才呼叫（同一支 flock 在同 process 內重入會鎖死自己）。
    payload = {
        "incident_kind": INCIDENT_KIND,
        "fingerprint": fp,
        "paths": ordered,
        "streaks": {p: int(streaks.get(p, 0)) for p in ordered},
        "quarantine_refs": [quarantine_ref] if quarantine_ref else [],
        "fires": 1,
        "first_seen_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "family_page_claim_schema": _FAMILY_PAGE_CLAIM_SCHEMA,
        "episode_generation": episode_generation,
        "family_transport_id": (
            f"phase-z-foreign-{fp}-e{episode_generation}"
        ),
    }
    record, created = append_task_record(
        {
            "id": f"phase-z-foreign-{fp}-e{episode_generation}",
        # 標題刻意不帶班數／檔案數：會浮動的數字進標題，等於每班一個新 dedup key，
        # 那正是舊 CRITICAL 變成連環通知的機制。浮動的東西全放 description。
            "title": f"PHASE-Z 卡住檔案 incident（{fp}）— 未關則 scheduler 降載",
            "description": _describe(
                ordered, payload["streaks"], 1, payload["quarantine_refs"],
            ),
            "task_type": "platform_ops",
            "priority": 1,
            "status": "pending",
            "source": "phase_z",
            "dispatch_lane": "agent",
            "dispatch_preempt": True,
            "write_intent": "observe_only",
            "declared_output_paths": [],
            "post_merge_actions": [],
            "created_at": now.isoformat(),
            "payload": payload,
        },
        path=path,
        if_exists="skip",
        semantic_dedupe=False,
    )
    candidate_id = str(record.get("id") or "")
    # An append race can return a legacy row created before the execution
    # contract existed.  Repair that row under the same canonical writer rather
    # than leaving the incident permanently invisible to the dispatcher.
    contract_repaired = False
    if not created:
        contract_repaired = _repair_dispatch_contract(path, candidate_id)
    persisted, page_required, page_token, transport_id, transport_ids = (
        _claim_related_family_page(
            path, candidate_id, now=now,
        )
    )
    receipt.update({
        "task_id": candidate_id,
        "created": created and persisted,
        "page_required": persisted and page_required,
        "page_claim_token": page_token,
        "page_transport_id": transport_id,
        "page_transport_alias_ids": [
            value for value in transport_ids if value != transport_id
        ],
        "reason": "created" if created else "existing_after_append_race",
        "fires": 1,
        "contract_repaired": contract_repaired,
    })
    if persisted and (created or contract_repaired):
        receipt["dispatch_request"] = _request_incident_dispatch(
            path, candidate_id, fp,
        )
    receipt["superseded"] = (
        _supersede_subsumed(
            path, keep_id=candidate_id, paths=set(ordered), now=now,
        )
        if persisted
        else []
    )
    return receipt


def _supersede_subsumed(path: Path, *, keep_id: str, paths: set[str],
                        now: datetime) -> list[str]:
    """卡住的檔案集合長大時，把被完全涵蓋的舊 incident 標成 superseded。

    沒有這一步，「又多一個檔案卡住」就會是一張全新的單，而舊的那張永遠沒有關閉
    條件可滿足 —— 一年後任務池裡躺著幾十張同一件事的 incident，降載訊號變成常態
    背景，於是又回到「紅色日誌」。只在**子集**時 supersede：那是可以機械證明「新
    單完全涵蓋舊單」的唯一情況，不是猜的。
    """
    superseded: list[str] = []
    with path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            tasks = _load_tasks(handle)
            keep = next(
                (
                    task
                    for task in tasks
                    if _is_incident(task) and task.get("id") == keep_id
                ),
                None,
            )
            for task in tasks:
                if not (_is_incident(task) and _is_open(task)):
                    continue
                if task.get("id") == keep_id:
                    continue
                old = set((task.get("payload") or {}).get("paths") or [])
                if not old or not old <= paths:
                    continue
                old_payload = task.get("payload") or {}
                keep_payload = keep.setdefault("payload", {}) if keep is not None else {}
                if (
                    old_payload.get("family_page_delivered_at")
                    or _page_leases(old_payload)
                    or old_payload.get("family_transport_id")
                ):
                    # The successor remains the live representative of the same
                    # overlapping episode. Preserve delivery/lease state before
                    # retiring its predecessor, or the next exact-set update
                    # would see an unacknowledged singleton and page again.
                    keep_payload["family_page_claim_schema"] = (
                        _FAMILY_PAGE_CLAIM_SCHEMA
                    )
                    transport_ids = _family_transport_ids(
                        keep_payload,
                        fallback=str(keep.get("id") or "")
                        if keep is not None
                        else keep_id,
                    )
                    for candidate in _family_transport_ids(
                        old_payload,
                        fallback=str(task.get("id") or ""),
                    ):
                        if candidate not in transport_ids:
                            transport_ids.append(candidate)
                    _store_family_transport_ids(keep_payload, transport_ids)
                    for field in (
                        "family_page_delivered_at",
                        "family_page_delivered_by",
                    ):
                        if old_payload.get(field) and not keep_payload.get(field):
                            keep_payload[field] = old_payload[field]
                    _store_page_leases(
                        keep_payload,
                        [
                            *_page_leases(keep_payload),
                            *_page_leases(old_payload),
                        ],
                    )
                    _store_page_leases(old_payload, [])
                task["status"] = "superseded"
                task["superseded_at"] = now.isoformat()
                task["superseded_by"] = keep_id
                task["completed_at"] = now.isoformat()
                task["result"] = "subsumed_by_wider_stuck_path_set"
                superseded.append(str(task.get("id")))
            if superseded:
                write_tasks_to_handle(handle, tasks)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return superseded


# ── mechanical close condition ───────────────────────────────────────────────

def _git_lines(
    repo_root: Path,
    *args: str,
    runner=subprocess.run,
    ok_returncodes: tuple[int, ...] = (0,),
) -> list[str]:
    try:
        # core.quotePath=false: git C-quotes non-ASCII pathnames by default
        # ("\346\226\207..."), so CJK paths from status/ls-tree never matched
        # the raw UTF-8 dirty-path set — two incidents were mathematically
        # uncloseable and pinned the dispatch derate forever (2026-08-04).
        proc = runner(
            ["git", "-C", str(repo_root), "-c", "core.quotePath=false", *args],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_S, check=False,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        warn("foreign_incident", f"git {args[0]} 失敗 ({exc}) — 視為無覆蓋證據")
        return []
    if proc.returncode not in ok_returncodes:
        warn("foreign_incident",
             f"git {args[0]} rc={proc.returncode} — 視為無覆蓋證據",
             err=(proc.stderr or "")[-200:])
        return []
    return [line for line in (proc.stdout or "").splitlines() if line]


def quarantine_covered_paths(repo_root: Path, *, runner=subprocess.run) -> set[str]:
    """Every path retrievable from some immutable quarantine ref."""
    covered: set[str] = set()
    refs = _git_lines(repo_root, "for-each-ref", "--format=%(refname)",
                      QUARANTINE_REF_PREFIX, runner=runner)
    for ref in refs:
        covered.update(_git_lines(repo_root, "ls-tree", "-r", "--name-only", ref,
                                  runner=runner))
    return covered


def live_workspace_paths(repo_root: Path, paths: Iterable[str], *,
                         runner=subprocess.run) -> dict[str, str]:
    """``rel -> workspace`` for paths that exist in a registered git worktree.

    「Live workspace」= ``git worktree list`` 認得的工作區（不是 ``.claude/worktrees/``
    底下隨便一個目錄 —— 目錄是**產物**，registration 才是關係）。一個檔案還在某人的
    工作區裡，就不是「沒人收的遺留」，它有地方可去。
    """
    worktrees: list[Path] = []
    for line in _git_lines(repo_root, "worktree", "list", "--porcelain", runner=runner):
        if line.startswith("worktree "):
            wt = Path(line[len("worktree "):].strip())
            if wt.resolve() != repo_root.resolve():
                worktrees.append(wt)
    found: dict[str, str] = {}
    for rel in paths:
        for wt in worktrees:
            if (wt / rel).exists():
                found[rel] = str(wt)
                break
    return found


def dirty_paths(repo_root: Path, *, runner=subprocess.run) -> set[str]:
    """Paths still uncommitted in the main checkout."""
    out: set[str] = set()
    for line in _git_lines(repo_root, "status", "--porcelain",
                           "--untracked-files=all", runner=runner):
        rel = line[3:].strip().strip('"')
        if " -> " in rel:
            rel = rel.split(" -> ", 1)[1]
        out.add(rel)
    return out


#: 活性分類的取值。``unknown`` 不存在是刻意的 —— 分類器只在有正面證據時說 live，
#: 沒有證據就是 dead，因為「不確定」若進了指示文字，執行者仍得自己猜，而這張單存在
#: 的理由正是不要再讓執行者猜。
LIVENESS_LIVE = "live"
LIVENESS_DEAD = "dead"

#: 只有像碼的東西值得問「有沒有人在用」。備份檔、編輯器暫存檔沒有 importer 可言。
_CODEISH_SUFFIXES = (".py", ".sh", ".js", ".ts", ".sql")


def _reference_needles(rel: str) -> list[str]:
    """一個路徑會以哪些字面形式出現在別的碼裡。

    三種都要找，因為 repo 內三種寫法都真實存在：dotted import
    （``from volpred.ops.foreign_incident import ...``）、裸模組名（``import
    foreign_incident``、``monkeypatch.setattr(MODULE, ...)`` 前的 import），以及
    直接寫死的相對路徑（``subprocess`` 呼叫 ``scripts/xxx.py`` 是本 repo 的常態）。
    只找 dotted 會漏掉 ``scripts/`` 底下所有東西 —— 而 ``phase_z.py`` 正是那類。
    """
    p = Path(rel)
    needles = [rel]
    if p.suffix == ".py":
        stem = p.stem
        if stem != "__init__":
            needles.append(stem)
        parts = list(p.with_suffix("").parts)
        if parts[:1] == ["src"]:
            needles.append(".".join(parts[1:]))
    return [n for n in needles if n]


def referenced_by_tracked(repo_root: Path, paths: Iterable[str], *,
                          runner=subprocess.run) -> dict[str, str]:
    """``rel -> 引用它的 tracked 檔``，找不到就不在 dict 裡。

    這是最強的活性訊號，也是 2026-07-20 那次的特徵：``foreign_incident.py`` 當時是
    untracked，卻被 tracked 的 ``dispatch_slot_budget.py`` import —— 那層關係**寫在
    已提交的碼裡**，不需要猜任何人的意圖就看得到。

    ``git grep`` 預設只搜 tracked 檔，正是這裡要的語意：由**已提交**的碼背書，才算
    數。untracked 檔互相引用不構成活性（那可能只是同一坨無主殘留自己抱團）。
    """
    found: dict[str, str] = {}
    for rel in paths:
        if rel in found or not rel.endswith(_CODEISH_SUFFIXES):
            continue
        for needle in _reference_needles(rel):
            # pathspec 限定在碼與設定：doc 或 next_tasks.json 提到一個檔名，只代表有人
            # 寫過它，不代表有人在跑它。把那種提及當活性證據，等於讓任何被寫進舊任務
            # 描述的殘留檔永久免疫於清除 —— 分類器會很少說 dead，也就等於沒有分類。
            # git grep exits 1 on "no match" — a normal negative result, not a
            # probe failure; only rc>=2 means the evidence is actually missing.
            hits = _git_lines(repo_root, "grep", "-l", "-F", needle, "--",
                              "*.py", "*.sh", "*.js", "*.ts", "*.toml", "*.cfg",
                              "*.json", ":(exclude)storage/**", ":(exclude)docs/**",
                              runner=runner, ok_returncodes=(0, 1))
            # 自己引用自己不算；一個 tracked 檔提到自己只表示它被提交了。
            other = [h for h in hits if h != rel]
            if other:
                found[rel] = other[0]
                break
    return found


def _has_passing_test_file(repo_root: Path, rel: str) -> str | None:
    """對應的測試檔在不在。存在就回傳它的路徑。

    只看**存在**、不實際跑：關閉條件會被逐班重跑，在裡面跑 pytest 會把一個判斷變成
    一次 CI。存在本身已是夠強的次要訊號 —— 沒有人會為一坨要刪的殘留寫測試。
    """
    p = Path(rel)
    if p.suffix != ".py":
        return None
    if p.stem.startswith("test_") and "tests" in p.parts:
        # 反向：測試檔不會被任何碼 import，所以 referenced_by_tracked 對它永遠是空的
        # —— 2026-07-20 那 53 個路徑裡，整組測試就是這樣被算成無主殘留的。
        # 這裡刻意不去解析它到底測哪個模組（``test_phase_z_foreign_incident`` 這種
        # 複合命名解不出來，而解錯就退回誤判）。不對稱是刻意的：把一個沒用的測試留著
        # 只是雜訊，把一個有用的測試安靜刪掉是這張單要防的那種錯。
        return str(p)
    for base in ("scripts/tests", "tests"):
        cand = f"{base}/test_{p.stem}.py"
        if (repo_root / cand).exists():
            return cand
    return None


def classify_path_liveness(repo_root: Path, paths: Iterable[str], *,
                           runner=subprocess.run) -> dict[str, dict[str, Any]]:
    """逐路徑判「這是無主殘留，還是未提交的活躍碼」。

    ``incident_closeable`` 原本的三個訊號（quarantined / live_workspace /
    still_dirty_in_main）在這兩種狀態下**取值完全相同**，於是關閉條件對後者給出的
    指示是「保存後清除」—— 照做會刪掉正在運行的系統碼。2026-07-20 那次是靠人停下來
    查身分才沒鑄成大錯。

    這裡不猜擁有者（D1 停止猜測式收編仍然成立），只問活性，而活性是機械可判的：
    有沒有已提交的碼在用它，有沒有人為它寫過測試。判斷結果**只改變給執行者的指示
    文字**，不自動 commit 也不自動刪 —— 收養與否是決策，不是本函式的權限。

    刻意不採 mtime：``foreign_incident.py`` 自己就曾經 untracked 存活 78 班，那時它的
    mtime 早就過任何寬限，但它每小時都在跑。時間訊號回答的是「有人剛動過嗎」，不是
    「這東西活著嗎」。
    """
    ordered = sorted({str(p) for p in paths if str(p)})
    referenced = referenced_by_tracked(repo_root, ordered, runner=runner)
    out: dict[str, dict[str, Any]] = {}
    for rel in ordered:
        evidence: list[str] = []
        importer = referenced.get(rel)
        if importer:
            evidence.append(f"被已提交的 {importer} 引用")
        test_file = _has_passing_test_file(repo_root, rel)
        if test_file == rel:
            evidence.append("本身是測試檔（tests/ 下的 test_*.py）")
        elif test_file:
            evidence.append(f"有對應測試 {test_file}")
        out[rel] = {
            "liveness": LIVENESS_LIVE if evidence else LIVENESS_DEAD,
            "referenced_by": importer,
            "test_file": test_file,
            "liveness_evidence": evidence,
        }
    return out


def _seconds_since_authored(repo_root: Path, rel: str, *, now: datetime) -> float | None:
    """這個路徑在 main checkout 裡多久沒被動過；檔案不在就回 ``None``。

    ``None`` 代表「沒有活躍跡象」而不是「剛動過」—— 一個 dirty 但工作區已無此檔的
    路徑（例如已暫存的刪除）沒有作者活動可言，寬限不該套用在它身上。
    """
    try:
        mtime = (repo_root / rel).stat().st_mtime
    except OSError:  # silent-ok: 檔案不在 = 沒有作者活動可言，None 是設計上的答案（見 docstring）
        return None
    return max(0.0, now.timestamp() - mtime)


def incident_closeable(
    repo_root: Path,
    paths: Sequence[str],
    *,
    runner=subprocess.run,
    grace_s: float = LIVE_AUTHORING_GRACE_S,
    now: datetime | None = None,
) -> dict[str, Any]:
    """一張 incident 可否關閉 —— 機械判定，逐路徑給證據。

    ``closeable`` 為 True 的充要條件：

    * **每一個** dirty path 都被覆蓋 —— 存在於某個 live workspace，或可從某個
      immutable quarantine ref 取回（``git show <ref>:<path>``）；**且**
    * 這些路徑都不再髒在 main checkout 裡。

    第二條是這張單真正的 forcing function。只有 quarantine 覆蓋、檔案卻還躺在工作
    區，是「保存了但沒收拾」—— 那正是 78 班期間的狀態，而它不該算解決。少一個路徑
    沒覆蓋就 False：關閉條件必須是全稱的，否則「大部分處理完了」會變成關單理由。

    **但「還髒著」不等於「沒人要」。** 一個已覆蓋、且 ``grace_s`` 內還被改過的路徑
    算 *live authoring*，進 ``deferred`` 而不是 ``blockers``（見 ``LIVE_AUTHORING_GRACE_S``）。

    兩者的差別是**誰該付代價**，因此回傳兩個不同的判斷：

    * ``closeable`` —— 路徑真的收乾淨了嗎（嚴格：全覆蓋且全不髒）。這決定 incident
      關不關。live authoring **不會**讓它變 True：檔案還在工作區，事情就還沒完，
      而每班關掉再重開會讓同一件事每小時換一張單，dedup 就白做了。
    * ``derates`` —— 現在還值得壓 scheduler 嗎（只看 ``blockers``）。作者正在寫的檔案
      不是「沒有人會回來收」，把整條排程壓在半速只會懲罰還在工作的人，而且沒有出口
      （每存一次檔 deadline 就重置）。2026-07-21 ``detect_price_split_breaks.py`` 就是
      這個形狀：quarantine 過、2 小時前才改過、全池唯一 blocker。

    寬限不是放水：未覆蓋的路徑無論多新一律進 ``blockers``，因為寬限的安全前提正是
    「bytes 已經有地方取回」。而寬限會自己過期 —— 作者收尾或放手，都通往 terminal state。
    """
    now = now or datetime.now(timezone.utc)
    ordered = sorted({str(p) for p in paths if str(p)})
    quarantined = quarantine_covered_paths(repo_root, runner=runner)
    workspaces = live_workspace_paths(repo_root, ordered, runner=runner)
    still_dirty = dirty_paths(repo_root, runner=runner)
    liveness = classify_path_liveness(repo_root, ordered, runner=runner)

    evidence: dict[str, dict[str, Any]] = {}
    blockers: list[str] = []
    deferred: list[str] = []
    head_tracked = set(
        _git_lines(repo_root, "ls-files", "--", *ordered, runner=runner)
    )
    for rel in ordered:
        in_quarantine = rel in quarantined
        workspace = workspaces.get(rel)
        dirty = rel in still_dirty
        # A path committed to HEAD and no longer dirty is preserved in the
        # strongest form there is — requiring a quarantine ref on top of git
        # history left landed paths permanently "uncovered" (2026-08-04).
        landed = rel in head_tracked and not dirty
        covered = bool(in_quarantine or workspace or landed)
        idle_s = _seconds_since_authored(repo_root, rel, now=now) if dirty else None
        live_authoring = bool(covered and dirty
                              and idle_s is not None and idle_s < grace_s)
        live_code = liveness[rel]
        evidence[rel] = {
            "quarantined": in_quarantine,
            "live_workspace": workspace,
            "still_dirty_in_main": dirty,
            "covered": covered,
            "live_authoring": live_authoring,
            "idle_s": None if idle_s is None else round(idle_s, 1),
            **live_code,
        }
        if not covered:
            blockers.append(f"{rel}: 沒有 live workspace，也沒有 quarantine ref 可取回")
        elif dirty and live_authoring:
            deferred.append(f"{rel}: 已保存，且 {idle_s / 3600:.1f} 小時內還在改 — 活躍碼，不算無主殘留")
        elif dirty and live_code["liveness"] == LIVENESS_LIVE:
            # 指示改了，判定沒改：路徑還髒著，incident 就還沒收乾淨（closeable 仍 False）。
            # 改的是叫執行者做什麼 —— 「保存後清除」對一份正在運行的碼是錯的指令，
            # 而它錯得很安靜。收養是決策，所以這裡只呈現證據，不自動 commit。
            blockers.append(
                f"{rel}: 已保存但仍髒在 main checkout —— 這是**未提交的活躍碼，需要收養決策，不要清除**"
                f"（活性證據：{'；'.join(live_code['liveness_evidence'])}）"
            )
        elif dirty:
            blockers.append(f"{rel}: 已保存但仍髒在 main checkout — 尚未收拾")

    return {
        # 嚴格：還有東西髒著就不算收乾淨，deferred 也算。
        "closeable": bool(ordered) and not blockers and not deferred,
        # 只有真正無主的殘留才值得壓 scheduler。
        "derates": bool(blockers),
        "paths": evidence,
        "blockers": blockers,
        "deferred": deferred,
        "checked": ordered,
        "grace_s": grace_s,
    }


def check_open_incidents(repo_root: Path, *, tasks_path: str | Path | None = None,
                         runner=subprocess.run,
                         grace_s: float = LIVE_AUTHORING_GRACE_S,
                         now: datetime | None = None) -> list[dict[str, Any]]:
    """跑每一張未關 incident 的關閉條件，回傳逐張結果。"""
    tasks_path = tasks_path or (repo_root / "storage" / "next_tasks.json")
    out: list[dict[str, Any]] = []
    for task in open_incidents(tasks_path):
        payload = task.get("payload") or {}
        result = incident_closeable(repo_root, payload.get("paths") or [],
                                    runner=runner, grace_s=grace_s, now=now)
        result["task_id"] = task.get("id")
        result["fingerprint"] = payload.get("fingerprint")
        out.append(result)
    return out


def reconcile_incidents(
    repo_root: Path,
    *,
    tasks_path: str | Path | None = None,
    runner=subprocess.run,
    grace_s: float = LIVE_AUTHORING_GRACE_S,
    now: datetime | None = None,
) -> dict[str, Any]:
    """對每張未關 incident 重跑判準：收乾淨的關掉，其餘更新降載旗標。

    沒有這一步，``incident_closeable`` 就是這個模組自己在批評的東西：一個沒有接上
    控制流程的判準。2026-07-21 實測 —— 唯一那張 incident 的 close condition 全綠，
    slot cap 仍卡在 ``DERATE_CAP``，因為**沒有任何呼叫者**會去關它（``incident_closeable``
    除了測試與 CLI 零 caller）。降載於是從 forcing function 退化成常態背景，正是
    78 班那封 CRITICAL 的失敗形狀，只是換了個資料結構。

    ``derates`` 寫進 payload 而不是讓 scheduler 自己算：``dispatch_slot_budget`` 在
    派工熱路徑上，且刻意只讀佇列、不碰 git（讀不懂佇列都不該讓派工掛掉，何況 subprocess）。
    這裡每班本來就在做 git 檢查，順手把結論留下，讓那邊維持 read-only 且零 git。

    關閉是**機械判定的結果**，不是自我宣告：只有 ``incident_closeable`` 全綠才動，
    證據原封不動寫進 ``close_evidence``，讓「為什麼這張單關了」事後查得到。
    """
    now = now or datetime.now(timezone.utc)
    path = Path(tasks_path or (repo_root / "storage" / "next_tasks.json"))
    guard_canonical_write(path)
    verdicts = {
        str(t.get("id")): incident_closeable(
            repo_root, (t.get("payload") or {}).get("paths") or [],
            runner=runner, grace_s=grace_s, now=now,
        )
        for t in open_incidents(path)
    }
    if not verdicts:
        return {"closed": [], "deferred": []}

    closed: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    repaired_fingerprints: dict[str, str] = {}
    with path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            tasks = _load_tasks(handle)
            dirty = False
            for task in tasks:
                tid = str(task.get("id"))
                # 重讀後再確認一次仍未關：鎖外算的判準，鎖內才可信。
                if tid not in verdicts or not (_is_incident(task) and _is_open(task)):
                    continue
                if _ensure_dispatch_contract(task):
                    repaired_fingerprints[tid] = str(
                        (task.get("payload") or {}).get("fingerprint") or "unknown"
                    )
                    dirty = True
                verdict = verdicts[tid]
                if verdict["closeable"]:
                    task["status"] = "succeeded"
                    task["completed_at"] = now.isoformat()
                    task["result"] = (
                        f"關閉條件機械滿足：{len(verdict['checked'])} 個路徑全部有覆蓋"
                        "（quarantine ref 或 live workspace），且無未收拾的殘留。"
                    )
                    task["close_evidence"] = verdict
                    closed.append({"task_id": tid, "verdict": verdict})
                    dirty = True
                    continue
                payload = task.setdefault("payload", {})
                if payload.get("derates") != verdict["derates"]:
                    payload["derates"] = verdict["derates"]
                    payload["derates_updated_at"] = now.isoformat()
                    dirty = True
                payload["deferred"] = verdict["deferred"]
                if not verdict["derates"]:
                    deferred.append({"task_id": tid, "verdict": verdict})
            if dirty:
                write_tasks_to_handle(handle, tasks)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    for task_id, fp in repaired_fingerprints.items():
        _request_incident_dispatch(
            path, task_id, fp,
        )
    return {"closed": closed, "deferred": deferred}


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="對每張未關 incident 跑關閉條件；有任一張關不掉則 exit 1")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[3]))
    ap.add_argument("--grace-hours", type=float,
                    default=LIVE_AUTHORING_GRACE_S / 3600,
                    help="已覆蓋的 dirty path 多久沒動過才算無主殘留（預設 24 小時）")
    ap.add_argument("--reconcile", action="store_true",
                    help="收乾淨的 incident 標 succeeded，其餘更新降載旗標")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo)
    grace_s = args.grace_hours * 3600
    if args.reconcile:
        outcome = reconcile_incidents(repo_root, grace_s=grace_s)
        print(json.dumps(
            {"closed": [c["task_id"] for c in outcome["closed"]],
             "derate_lifted": [d["task_id"] for d in outcome["deferred"]]},
            ensure_ascii=False, indent=2))
        return 0
    results = check_open_incidents(repo_root, grace_s=grace_s)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    if not args.check:
        return 0
    return 0 if all(r["closeable"] for r in results) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
