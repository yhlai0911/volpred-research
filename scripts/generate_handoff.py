#!/usr/bin/env python3
"""Auto-generate storage/ops/handoff_latest.md every hour.

Sections:
  1. 當前時間 + 系統角色
  2. 任務池快照（pending / claimed / in_progress / 最近完成）
  3. 進行中 agent（.claude/worktrees + storage/ops/agents/）
  4. 待處理 email_reply 任務（從 gmail 收進來）
  5. 最近 critical/warn dashboard 訊號
  6. 接續提示詞（一段可直接貼回主 session 的指令）

Run:
  uv run python scripts/generate_handoff.py
Cron: HH:50 every hour (10 min before hourly-dispatch fires at :07 next hour).
"""
from __future__ import annotations

import fcntl
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / "storage" / "ops" / "handoff_latest.md"
HANDOFF_ARCHIVE = ROOT / "storage" / "ops" / "handoff_archive"
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
TASK_POOL_MODE = ROOT / "storage" / "ops" / "task_pool_mode.json"
DASHBOARD = ROOT / "storage" / "ops" / "dashboard_latest.json"
WORK_LOG = ROOT / "storage" / "work_log.json"
WORKTREES = ROOT / ".claude" / "worktrees"
AGENTS_DIR = ROOT / "storage" / "ops" / "agents"
GMAIL_STATE = ROOT / "storage" / "ops" / "gmail_inbox_state.json"

TAIPEI = ZoneInfo("Asia/Taipei")

SCRIPTS_DIR = str(ROOT / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)
from task_pool_claim import _is_codex_eligible_task  # noqa: E402


def _now_local() -> str:
    return datetime.now(TAIPEI).strftime("%Y-%m-%d %H:%M:%S")


def _warn_json_read_failed(path: Path, exc: Exception, *, action: str) -> None:
    print(
        "[generate_handoff] WARN JSON read failed; "
        f"{action} path={path} error={type(exc).__name__}: {exc}",
        file=sys.stderr,
    )


def _warn_handoff_read_failed(path: Path, exc: Exception, *, action: str) -> None:
    print(
        "[generate_handoff] WARN handoff read failed; "
        f"{action} path={path} error={type(exc).__name__}: {exc}",
        file=sys.stderr,
    )


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        _warn_json_read_failed(path, exc, action="using default")
        return default


def _load_task_pool_mode_snapshot() -> tuple[dict[str, Any], bool]:
    if not TASK_POOL_MODE.exists():
        return {}, True
    try:
        payload = json.loads(TASK_POOL_MODE.read_bytes().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("task-pool owner state must be an object")
        enabled = payload.get("enabled", False)
        mode = payload.get("mode", "queued_execution")
        if not isinstance(enabled, bool):
            raise ValueError("task-pool owner enabled must be boolean")
        if not isinstance(mode, str) or not mode:
            raise ValueError("task-pool owner mode must be a non-empty string")
        if enabled and mode not in {
            "direct_execution",
            "restore_in_progress",
        }:
            raise ValueError(f"unsupported enabled task-pool mode {mode!r}")
        return payload, True
    except (
        json.JSONDecodeError,
        OSError,
        UnicodeError,
        ValueError,
    ) as exc:
        _warn_json_read_failed(
            TASK_POOL_MODE,
            exc,
            action="using fail-closed owner snapshot",
        )
        return {}, False


def _load_task_pool_snapshot() -> tuple[list[Any], Any, bool, bool]:
    """Read owner state and queue bytes under one queue snapshot lock."""

    if not NEXT_TASKS.exists():
        task_pool_mode, state_valid = _load_task_pool_mode_snapshot()
        return [], task_pool_mode, False, state_valid
    try:
        with NEXT_TASKS.open("rb") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
            try:
                task_pool_mode, state_valid = (
                    _load_task_pool_mode_snapshot()
                )
                try:
                    payload = json.loads(handle.read().decode("utf-8"))
                    if not isinstance(payload, list):
                        raise ValueError("task queue root must be a list")
                except (
                    json.JSONDecodeError,
                    OSError,
                    UnicodeError,
                    ValueError,
                ) as exc:
                    _warn_json_read_failed(
                        NEXT_TASKS,
                        exc,
                        action="using fail-closed empty snapshot",
                    )
                    return [], task_pool_mode, False, state_valid
                return payload, task_pool_mode, True, state_valid
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        _warn_json_read_failed(
            NEXT_TASKS,
            exc,
            action="using fail-closed empty snapshot",
        )
        task_pool_mode, state_valid = _load_task_pool_mode_snapshot()
        return [], task_pool_mode, False, state_valid


def _parse_completed_at(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("completed_at must be a non-empty ISO string")
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _task_pool_snapshot(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    status_counter = Counter()
    type_counter = Counter()
    pending_top: list[dict[str, Any]] = []
    codex_eligible_pending: list[dict[str, Any]] = []
    codex_skip_pending: list[dict[str, Any]] = []
    claimed: list[dict[str, Any]] = []
    in_progress: list[dict[str, Any]] = []
    email_replies: list[dict[str, Any]] = []
    recently_completed: list[dict[str, Any]] = []
    warnings: list[str] = []

    now = datetime.now(timezone.utc)

    for t in tasks:
        status = (t.get("status") or "").lower()
        status_counter[status or "unknown"] += 1
        type_counter[t.get("task_type") or "unknown"] += 1

        if t.get("task_type") == "email_reply" and status in {"pending", "pending_main_thread", "claimed"}:
            email_replies.append(t)

        if status in {"pending", "pending_main_thread"}:
            pending_top.append(t)
            if _is_codex_eligible_task(t):
                codex_eligible_pending.append(t)
            else:
                codex_skip_pending.append(t)
        elif status == "claimed":
            claimed.append(t)
        elif status == "in_progress":
            in_progress.append(t)
        elif status == "succeeded":
            completed_at = t.get("completed_at")
            if completed_at:
                try:
                    age_h = (now - _parse_completed_at(completed_at)).total_seconds() / 3600
                    if age_h <= 24:
                        recently_completed.append(t)
                except (TypeError, ValueError) as exc:
                    warnings.append(
                        "invalid completed_at for succeeded task "
                        f"{t.get('id') or '(missing-id)'}: {completed_at!r} ({exc.__class__.__name__})"
                    )

    invalid_priority_ids: set[str] = set()

    def _prio_key(x: dict[str, Any]) -> tuple[int, str]:
        p = x.get("priority")
        task_id = x.get("id") or "(missing-id)"
        # 2026-07-05: coerce string "P<n>" first — 90 pool entries carry that
        # form; ValueError→P9 buried a boss-assigned P1 at the queue tail.
        s = str(p).strip()
        if s.upper().startswith("P") and s[1:].isdigit():
            return (int(s[1:]), task_id)
        try:
            return (int(p), task_id)
        except (TypeError, ValueError) as exc:
            if task_id not in invalid_priority_ids:
                invalid_priority_ids.add(task_id)
                warnings.append(
                    "invalid priority for pending task "
                    f"{task_id}: {p!r} ({exc.__class__.__name__}); treating as P9"
                )
            return (9, task_id)
    pending_top.sort(key=_prio_key)
    codex_eligible_pending.sort(key=_prio_key)
    codex_skip_pending.sort(key=_prio_key)
    recently_completed.sort(key=lambda x: x.get("completed_at") or "", reverse=True)

    return {
        "status_counts": dict(status_counter),
        "type_counts": dict(type_counter),
        "pending_top": pending_top[:8],
        "codex_eligible_pending": codex_eligible_pending[:8],
        "codex_eligible_pending_count": len(codex_eligible_pending),
        "codex_skip_pending_count": len(codex_skip_pending),
        "claimed": claimed,
        "in_progress": in_progress,
        "email_replies": email_replies,
        "recently_completed": recently_completed[:5],
        "warnings": warnings[:5],
    }


def _direct_mode_receipt_drift(
    tasks: list[dict[str, Any]],
    mode: dict[str, Any],
) -> dict[str, Any]:
    """Compare live task identities with the direct-mode activation receipt."""

    preserve_raw = mode.get("preserve_task_ids", [])
    receipt_valid = isinstance(preserve_raw, list) and all(
        isinstance(task_id, str) and task_id
        for task_id in preserve_raw
    )
    preserve = set(preserve_raw) if receipt_valid else set()
    identity_counts: Counter[str] = Counter()
    anonymous_rows = 0
    for task in tasks:
        task_id = task.get("id")
        if isinstance(task_id, str) and task_id:
            identity_counts[task_id] += 1
        else:
            anonymous_rows += 1
    unexpected = sorted(set(identity_counts) - preserve)
    duplicates = sorted(
        task_id for task_id, count in identity_counts.items() if count > 1
    )
    return {
        "breached": not receipt_valid
        or bool(unexpected)
        or bool(duplicates)
        or anonymous_rows > 0,
        "receipt_valid": receipt_valid,
        "unexpected_task_ids": unexpected,
        "duplicate_task_ids": duplicates,
        "anonymous_rows": anonymous_rows,
    }


def _active_agents() -> dict[str, Any]:
    worktrees: list[str] = []
    if WORKTREES.exists():
        for p in WORKTREES.iterdir():
            if p.is_dir() and not p.name.startswith("."):
                worktrees.append(p.name)

    agents: list[dict[str, Any]] = []
    if AGENTS_DIR.exists():
        for f in sorted(AGENTS_DIR.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                _warn_json_read_failed(f, exc, action="skipping agent receipt")
                continue
            status = (data.get("status") or "").lower()
            if status in {"running", "active", "in_progress", "claimed"}:
                agents.append({
                    "id": f.stem,
                    "status": status,
                    "task_type": data.get("task_type"),
                    "started_at": data.get("started_at") or data.get("claimed_at"),
                })
    return {"worktrees": worktrees, "agents": agents, "occupied": len(worktrees) + len(agents)}


def _dashboard_signals(dashboard: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if not dashboard:
        return ["(no dashboard_latest.json)"]

    # Current canonical schema (check_alerts dashboard): overall_status + section_breaches +
    # section_critical + sections[]. 寫在前面確保新 schema 優先識別。
    overall = dashboard.get("overall_status")
    if overall is not None:
        gen_at = dashboard.get("dashboard_generated_at", "?")
        breaches = dashboard.get("section_breaches", 0)
        critical = dashboard.get("section_critical", 0)
        out.append(
            f"overall_status={overall} (breaches={breaches}, critical={critical}, generated={gen_at})"
        )
        # 列出非 ok 的 section（status != "ok"），最多 5 條
        sections = dashboard.get("sections") or []
        if isinstance(sections, list):
            non_ok = [s for s in sections if isinstance(s, dict) and s.get("status") not in (None, "ok")]
            for s in non_ok[:5]:
                tag = "CRITICAL" if s.get("status") == "critical" else "WARN"
                name = s.get("section") or s.get("name") or "?"
                tldr = s.get("tldr") or s.get("status")
                out.append(f"{tag}: section={name} :: {tldr if isinstance(tldr, str) else json.dumps(tldr, ensure_ascii=False)[:160]}")

    # Legacy / alternative shapes（向後相容；只在新 schema 無訊息時補上）
    for key in ("critical", "criticals", "alerts_critical"):
        if dashboard.get(key):
            for item in dashboard[key][:5]:
                out.append(f"CRITICAL: {item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)[:160]}")
    for key in ("warn", "warns", "warnings", "alerts_warn"):
        if dashboard.get(key):
            for item in dashboard[key][:5]:
                out.append(f"WARN: {item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)[:160]}")

    if not out:
        summary = dashboard.get("summary") or dashboard.get("status")
        if summary:
            out.append(f"summary: {summary if isinstance(summary, str) else json.dumps(summary, ensure_ascii=False)[:200]}")
        else:
            out.append("(dashboard_latest.json present but no recognized schema)")
    return out


def _recent_work_log(log: Any, n: int = 5) -> list[str]:
    if not isinstance(log, list):
        return []
    out: list[str] = []
    for entry in log[-n:]:
        if not isinstance(entry, dict):
            continue
        ts = entry.get("timestamp", "")[:16]
        ttype = entry.get("task_type", "?")
        title = (entry.get("title") or entry.get("task_id") or "?")[:80]
        out.append(f"- `{ts}` [{ttype}] {title}")
    return list(reversed(out))


def _format_task_line(t: dict[str, Any]) -> str:
    tid = t.get("id", "?")
    prio = t.get("priority", "?")
    ttype = t.get("task_type", "?")
    title = (t.get("title") or "(no title)")[:100]
    owner = t.get("claimed_by")
    suffix = f" — claimed_by={owner}" if owner else ""
    return f"- `{tid}` P{prio} [{ttype}] {title}{suffix}"


def build() -> str:
    (
        tasks,
        task_pool_mode,
        queue_readable,
        state_valid,
    ) = _load_task_pool_snapshot()
    active_direct_execution = bool(
        isinstance(task_pool_mode, dict)
        and task_pool_mode.get("enabled") is True
        and task_pool_mode.get("mode") == "direct_execution"
    )
    restore_in_progress = bool(
        isinstance(task_pool_mode, dict)
        and task_pool_mode.get("enabled") is True
        and task_pool_mode.get("mode") == "restore_in_progress"
    )
    snapshot_unreadable = not queue_readable or not state_valid
    direct_mode = (
        active_direct_execution or restore_in_progress or snapshot_unreadable
    )
    direct_mode_drift = (
        _direct_mode_receipt_drift(
            tasks if isinstance(tasks, list) else [],
            task_pool_mode,
        )
        if active_direct_execution and queue_readable
        else None
    )
    dashboard = _load_json(DASHBOARD, {})
    work_log = _load_json(WORK_LOG, [])
    gmail = _load_json(GMAIL_STATE, {})

    snap = _task_pool_snapshot(tasks if isinstance(tasks, list) else [])
    agents = _active_agents()
    dash_signals = _dashboard_signals(dashboard)
    recent_work = _recent_work_log(work_log)

    lines: list[str] = []
    lines.append(f"# Handoff — {_now_local()} 台灣時間")
    lines.append("")
    lines.append("**角色**：VolPred 自主運營經理（用戶 = 老闆 / report-only / full autonomy）")
    lines.append("")
    lines.append("> 此檔由 `scripts/generate_handoff.py` 每小時 :50 自動產生。手寫補充請放本檔末段「## 候補 / 手動補充」並標時間戳。")
    lines.append("> 建議讀法：開工只讀下方 §1–§9（到第一條 `---` 為止）；候補區按任務關鍵字搜尋，歷史內容見 `storage/ops/handoff_archive/`。")
    lines.append("")

    # 1. 任務池快照
    lines.append("## 1. 任務池快照（`storage/next_tasks.json`）")
    lines.append("")
    if direct_mode:
        if restore_in_progress:
            lines.append(
                "- **RESTORE TRANSACTION：IN PROGRESS** — admission 與 claim 維持封鎖；"
                "必須完成 receipt 綁定的 restore 後才可恢復 queued execution。"
            )
            lines.append(
                "  - restore_started_at: "
                f"{task_pool_mode.get('restore_started_at') or '(unknown)'}"
            )
        elif active_direct_execution:
            lines.append(
                "- **DIRECT EXECUTION MODE：ACTIVE** — 新任務入池與 claim 已機械封鎖；"
                "只允許既有控制任務收尾。"
            )
        else:
            lines.append(
                "- **TASK POOL SNAPSHOT：UNREADABLE** — owner/queue snapshot "
                "不可安全對帳；禁止 claim、refill 或以空池 fallback。"
            )
        if snapshot_unreadable:
            lines.append(
                "  - queue_snapshot: unreadable or missing (fail closed)"
            )
        lines.append(
            f"  - activated_at: {task_pool_mode.get('activated_at') or '(unknown)'}"
        )
        lines.append(
            f"  - backup_sha256: {task_pool_mode.get('backup_sha256') or '(unknown)'}"
        )
        if direct_mode_drift and direct_mode_drift["breached"]:
            lines.append(
                "- **DIRECT MODE RECEIPT：BREACHED** — live queue 不只包含 activation "
                "receipt 允許的控制任務；這些 row 是 drift，不是可 claim 工作。"
            )
            if not direct_mode_drift["receipt_valid"]:
                lines.append("  - preserve_task_ids: INVALID")
            if direct_mode_drift["unexpected_task_ids"]:
                lines.append(
                    "  - unexpected_task_ids: "
                    + ", ".join(direct_mode_drift["unexpected_task_ids"][:8])
                )
            if direct_mode_drift["duplicate_task_ids"]:
                lines.append(
                    "  - duplicate_task_ids: "
                    + ", ".join(direct_mode_drift["duplicate_task_ids"][:8])
                )
            if direct_mode_drift["anonymous_rows"]:
                lines.append(
                    f"  - anonymous_rows: {direct_mode_drift['anonymous_rows']}"
                )
        else:
            lines.append("  - direct_mode_receipt: clean (preserved rows only)")
    sc = snap["status_counts"]
    lines.append(f"- **總數**：{sum(sc.values())}")
    for s in ("pending", "pending_main_thread", "claimed", "in_progress", "succeeded", "failed", "blocked", "blocked_on_user"):
        if sc.get(s):
            lines.append(f"  - {s}: {sc[s]}")
    if direct_mode:
        pending_rows = (
            snap["codex_eligible_pending_count"] + snap["codex_skip_pending_count"]
        )
        row_context = (
            "restore-transaction rows"
            if restore_in_progress
            else (
                "unreadable-snapshot rows"
                if snapshot_unreadable
                else "direct-mode pending rows"
            )
        )
        lines.append(f"  - {row_context} (claimable=0): {pending_rows}")
    else:
        lines.append(f"  - Codex-eligible pending: {snap['codex_eligible_pending_count']}")
        lines.append(f"  - Codex-skip pending: {snap['codex_skip_pending_count']}")
    lines.append("")
    lines.append("**type 分佈（top 6）**：")
    for ttype, cnt in Counter(snap["type_counts"]).most_common(6):
        lines.append(f"  - {ttype}: {cnt}")
    if snap["warnings"]:
        lines.append("")
        lines.append("**task pool warnings（top 5）**：")
        for warning in snap["warnings"]:
            lines.append(f"  - WARN: {warning}")
    lines.append("")

    # 2. 進行中 claim
    lines.append("## 2. 已 claim / in_progress 任務")
    lines.append("")
    if snap["claimed"] or snap["in_progress"]:
        for t in snap["claimed"]:
            lines.append(_format_task_line(t))
        for t in snap["in_progress"]:
            lines.append(_format_task_line(t))
    else:
        lines.append("- (無 — 任務池閒置)")
    lines.append("")

    # 3. Email reply 待處理（用戶硬性指示優先處理）
    lines.append("## 3. Email 回信任務（**優先處理**）")
    lines.append("")
    if snap["email_replies"]:
        for t in snap["email_replies"]:
            lines.append(_format_task_line(t))
    else:
        lines.append("- (無未處理回信)")
    lp = gmail.get("last_poll_at")
    lines.append("")
    lines.append(f"_Gmail 最後 poll：{lp or '(無紀錄)'}_")
    lines.append("")

    # 4. Pending top
    lines.append("## 4. Pending 任務 top 8（依 priority asc）")
    lines.append("")
    if direct_mode:
        pending_rows = (
            snap["codex_eligible_pending_count"] + snap["codex_skip_pending_count"]
        )
        if restore_in_progress:
            lines.append(
                f"- **Restore recovery rows**：{pending_rows}；**claimable**：0"
            )
        elif snapshot_unreadable:
            lines.append(
                f"- **Unreadable snapshot rows**：{pending_rows}；**claimable**：0"
            )
        else:
            lines.append(
                f"- **Direct-mode pending drift rows**：{pending_rows}；"
                "**claimable**：0"
            )
    else:
        lines.append(
            f"- **Codex-eligible pending**：{snap['codex_eligible_pending_count']}；"
            f"**Codex-skip pending**：{snap['codex_skip_pending_count']}"
        )
    if (
        not direct_mode
        and snap["codex_eligible_pending_count"] == 0
        and snap["codex_skip_pending_count"] > 0
    ):
        lines.append("> Codex worker：此 snapshot 沒有可 claim 的 pending；先跑 `task_pool_claim.py list --codex-eligible`，仍為 0 才走 error_log fallback。")
    if snap["codex_eligible_pending"] and not direct_mode:
        lines.append("")
        lines.append("**Codex-eligible pending top 8**：")
        for t in snap["codex_eligible_pending"]:
            lines.append(_format_task_line(t))
        lines.append("")
        lines.append("**All pending top 8**：")
    if direct_mode and snap["pending_top"]:
        if restore_in_progress:
            lines.append(
                "> 以下 row 是尚未 finalise 的 restore recovery data；禁止 claim。"
                "先執行 `task_pool_control.py status` 取得 state_sha256，再以同一 "
                "receipt 綁定參數重跑 `task_pool_control.py restore`。"
            )
        else:
            lines.append(
                "> 以下 row 只供 drift 對帳；禁止 claim。先執行 "
                "`task_pool_control.py status` 取得 state_sha256，再以 "
                "`task_pool_control.py reconcile-direct --expected-state-sha256 <SHA>` "
                "收斂並回讀 status。"
            )
        for t in snap["pending_top"]:
            lines.append(_format_task_line(t))
    elif snap["pending_top"]:
        for t in snap["pending_top"]:
            lines.append(_format_task_line(t))
    elif direct_mode:
        if restore_in_progress:
            lines.append(
                "- (restore 尚未完成 — queue 可暫時為空，不得自行補池或 claim)"
            )
        elif snapshot_unreadable:
            lines.append(
                "- (queue snapshot 不可讀 — 不得視為空池、補池或 claim)"
            )
        else:
            lines.append("- (direct execution mode — 任務池保持清空，不得自行補池)")
    else:
        lines.append("- (任務池空 — hourly dispatch 必須自主生新題)")
    lines.append("")

    # 5. 進行中 agent
    lines.append("## 5. 進行中 agent / worktree")
    lines.append("")
    lines.append(f"- **slot 占用**：{agents['occupied']} / 4")
    if agents["worktrees"]:
        lines.append("- worktrees:")
        for w in agents["worktrees"]:
            lines.append(f"  - `{w}`")
    if agents["agents"]:
        lines.append("- agents:")
        for a in agents["agents"]:
            lines.append(f"  - `{a['id']}` status={a['status']} type={a['task_type']} started={a['started_at']}")
    if not agents["worktrees"] and not agents["agents"]:
        lines.append("- (slot 全空)")
    lines.append("")

    # 6. 最近完成
    lines.append("## 6. 最近 24h 完成（top 5）")
    lines.append("")
    if snap["recently_completed"]:
        for t in snap["recently_completed"]:
            lines.append(_format_task_line(t))
    else:
        lines.append("- (24h 內無 succeeded 紀錄)")
    lines.append("")

    # 7. Dashboard 訊號
    lines.append("## 7. Dashboard 訊號")
    lines.append("")
    for s in dash_signals:
        lines.append(f"- {s}")
    lines.append("")

    # 8. 最近 work_log
    lines.append("## 8. 最近 work_log（5 筆，新→舊）")
    lines.append("")
    if recent_work:
        lines.extend(recent_work)
    else:
        lines.append("- (work_log 為空或不可讀)")
    lines.append("")

    # 9. 接續提示詞 — 給 hourly dispatch 用
    lines.append("## 9. 接續提示詞（hourly dispatch / 互動 session 共用）")
    lines.append("")
    lines.append("```")
    if direct_mode:
        if restore_in_progress:
            lines.append("RESTORE TRANSACTION 尚未完成：")
        elif snapshot_unreadable:
            lines.append("TASK POOL SNAPSHOT 不可安全讀取：")
        else:
            lines.append("DIRECT EXECUTION MODE 已啟用：")
        lines.append("  1. 禁止 claim、refill、建立或恢復 legacy task-pool 任務。")
        if restore_in_progress:
            lines.append(
                "  2. 先以 `task_pool_control.py status` 取得最新 state_sha256，"
                "再用原 backup／actor／reason 重跑 `task_pool_control.py restore`。"
            )
        elif snapshot_unreadable:
            lines.append(
                "  2. 先用 `task_pool_control.py status` 回讀 owner state；"
                "修復前不得把解析失敗當成空池。"
            )
        else:
            lines.append("  2. 只直接續做老闆已指定的 operations-core 重構與 live 驗證。")
        lines.append(
            "  3. 先用 `uv run python scripts/task_pool_control.py status` 回讀 gate；"
            "不得因池空走 error_log fallback。"
        )
        if direct_mode_drift and direct_mode_drift["breached"]:
            lines.append(
                "     §1 若標示 RECEIPT BREACHED：禁止 claim；以 "
                "`task_pool_control.py reconcile-direct "
                "--expected-state-sha256 <status.state_sha256>` "
                "收斂後再次回讀 status。"
            )
        if restore_in_progress:
            lines.append(
                "  4. 重試會依 transaction receipt 覆寫空白／部分／已完整還原的 "
                "queue，read-back 後才重開 admission；期間不得碰 queue。"
            )
        elif snapshot_unreadable:
            lines.append(
                "  4. 只走 receipt/state 綁定的 recovery；禁止手改 queue 或直接補池。"
            )
        else:
            lines.append(
                "  4. 回復舊池只准用 receipt 綁定的 `task_pool_control.py restore`，"
                "必須傳 `--expected-state-sha256 <status.state_sha256>`，"
                "且 live pool 必須為空。"
            )
    else:
        lines.append("讀 storage/ops/handoff_latest.md 後依以下優先序選工：")
        lines.append("")
        lines.append("優先序 (HARD)：")
        lines.append("  1. Section 3 Email reply 任務（task_type=email_reply）— 若有 pending，立即 claim + 處理（讀 description 的「用戶回信內容」+「原始助理寄出內容」，依用戶指示回應 / 修正 / 派工 / 寄回信）")
        lines.append("  2. Section 7 Dashboard CRITICAL — 立即 triage")
        lines.append("  3. Section 4 Pending 任務 top 8 — 依 priority asc + work_log diversity（last-3 task_type rotate）")
        lines.append("")
        lines.append("Claim 流程（避免雙 session 撞題）：")
        lines.append("  uv run python scripts/task_pool_claim.py claim --id <task_id> --owner <hourly|interactive|agent-name>")
        lines.append("  uv run python scripts/task_pool_claim.py start --id <task_id>")
        lines.append("  ... 執行 ...")
        lines.append("  uv run python scripts/task_pool_claim.py complete --id <task_id> --status succeeded --result '...摘要...'")
        lines.append("")
        lines.append("完整完成原則：派 agent 後 wait 完成、驗證、寫 knowledge.json / work_log、commit。50min cap。Heavy compute 走 compute_queue。")
    lines.append("```")
    lines.append("")

    # 10. 手動補充區（保留）
    lines.append("---")
    lines.append("")
    lines.append("## 候補 / 手動補充")
    lines.append("")
    lines.append("（此區由人工 / 互動 session 編輯。KEEP 內的 `###` 條目標題必須帶 `YYYY-MM-DD`；超過 14 天、標為 RESOLVED 或未標日期者會自動移至 `storage/ops/handoff_archive/YYYY-MM.md`。）")
    lines.append("")

    return "\n".join(lines)


def _extract_keep_block(path: Path) -> str:
    """跨 regen 保留手動內容：包在 <!-- KEEP --> ... <!-- /KEEP --> 之間的區段。

    回傳 KEEP 區段（含 marker），無則回 ""。
    缺結尾 marker 時，從 <!-- KEEP --> 保留到 EOF（容錯）。
    2026-05-29 修：原 main() 直接覆寫整檔、從不讀回舊內容，導致檔內「會保留
    KEEP 區段」的說明是假的，手寫 handoff 補充每 :50 被清空。
    """
    if not path.exists():
        return ""
    try:
        txt = path.read_text(encoding="utf-8")
    except Exception as exc:
        _warn_handoff_read_failed(path, exc, action="KEEP block not preserved")
        return ""
    start = txt.find("<!-- KEEP -->")
    if start == -1:
        return ""
    end = txt.find("<!-- /KEEP -->", start)
    if end == -1:
        return txt[start:].rstrip()
    return txt[start:end + len("<!-- /KEEP -->")]


_KEEP_START = "<!-- KEEP -->"
_KEEP_END = "<!-- /KEEP -->"
_MANUAL_ENTRY = re.compile(r"(?=^###\s+)", re.MULTILINE)
_ENTRY_DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")


def _split_keep_entries(keep: str) -> tuple[str, list[str]]:
    """Return marker-adjacent preamble and ``###`` manual-entry chunks."""
    body = keep.strip()
    if body.startswith(_KEEP_START):
        body = body[len(_KEEP_START):].lstrip("\n")
    if body.endswith(_KEEP_END):
        body = body[:-len(_KEEP_END)].rstrip()
    first_entry = re.search(r"^###\s+", body, flags=re.MULTILINE)
    if first_entry is None:
        return body.strip(), []
    preamble = body[:first_entry.start()].strip()
    entries = [chunk.strip() for chunk in _MANUAL_ENTRY.split(body[first_entry.start():]) if chunk.strip()]
    return preamble, entries


def _archive_month_for_entry(entry: str, now: datetime) -> tuple[str | None, bool]:
    """Return archive month and whether an entry has crossed rotation policy."""
    heading = entry.splitlines()[0] if entry else ""
    match = _ENTRY_DATE.search(heading)
    entry_date = None
    if match:
        try:
            entry_date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
        except ValueError:
            entry_date = None
    resolved = "resolved" in heading.casefold()
    expired = entry_date is not None and entry_date < (now.date() - timedelta(days=14))
    # Manual supplements are required to carry a heading timestamp. Undated
    # entries cannot prove they are within the 14-day live window, so archive
    # them rather than letting relative labels such as "tomorrow" live forever.
    undated = entry_date is None
    if not (resolved or expired or undated):
        return None, False
    month = entry_date.strftime("%Y-%m") if entry_date is not None else now.strftime("%Y-%m")
    return month, True


def _append_archive_entries(archive_dir: Path, grouped: dict[str, list[str]]) -> None:
    """Append rotated entries once; exact-content dedupe makes crash retry safe."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    for month, entries in sorted(grouped.items()):
        path = archive_dir / f"{month}.md"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if not existing:
            existing = f"# Handoff manual supplement archive — {month}\n"
        changed = False
        for entry in entries:
            if entry not in existing:
                existing = existing.rstrip() + "\n\n" + entry.rstrip() + "\n"
                changed = True
        if changed or not path.exists():
            path.write_text(existing, encoding="utf-8")


def _rotate_keep_block(keep: str, archive_dir: Path, now: datetime) -> str:
    """Archive stale/resolved manual entries and return the compact KEEP block."""
    if not keep:
        return ""
    preamble, entries = _split_keep_entries(keep)
    active: list[str] = []
    archived: dict[str, list[str]] = {}
    for entry in entries:
        month, rotate = _archive_month_for_entry(entry, now)
        if rotate and month is not None:
            archived.setdefault(month, []).append(entry)
        else:
            active.append(entry)
    if archived:
        _append_archive_entries(archive_dir, archived)
    parts = [_KEEP_START]
    if preamble:
        parts.append(preamble)
    parts.extend(active)
    parts.append(_KEEP_END)
    return "\n\n".join(parts)


def main() -> int:
    HANDOFF.parent.mkdir(parents=True, exist_ok=True)
    keep = _rotate_keep_block(
        _extract_keep_block(HANDOFF), HANDOFF_ARCHIVE, datetime.now(TAIPEI)
    )
    content = build()
    if keep:
        content = content.rstrip() + "\n\n" + keep + "\n"
    HANDOFF.write_text(content, encoding="utf-8")
    print(f"handoff regenerated: {HANDOFF}  bytes={len(content)}  keep_preserved={bool(keep)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
