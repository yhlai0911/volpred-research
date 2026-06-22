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

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / "storage" / "ops" / "handoff_latest.md"
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"
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


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


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

    def _prio_key(x: dict[str, Any]) -> tuple[int, str]:
        p = x.get("priority")
        try:
            return (int(p), x.get("id") or "")
        except (TypeError, ValueError):
            return (9, x.get("id") or "")
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
            except json.JSONDecodeError:
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
    tasks = _load_json(NEXT_TASKS, [])
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
    lines.append("")

    # 1. 任務池快照
    lines.append("## 1. 任務池快照（`storage/next_tasks.json`）")
    lines.append("")
    sc = snap["status_counts"]
    lines.append(f"- **總數**：{sum(sc.values())}")
    for s in ("pending", "pending_main_thread", "claimed", "in_progress", "succeeded", "failed", "blocked", "blocked_on_user"):
        if sc.get(s):
            lines.append(f"  - {s}: {sc[s]}")
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
    lines.append(
        f"- **Codex-eligible pending**：{snap['codex_eligible_pending_count']}；"
        f"**Codex-skip pending**：{snap['codex_skip_pending_count']}"
    )
    if snap["codex_eligible_pending_count"] == 0 and snap["codex_skip_pending_count"] > 0:
        lines.append("> Codex worker：此 snapshot 沒有可 claim 的 pending；先跑 `task_pool_claim.py list --codex-eligible`，仍為 0 才走 error_log fallback。")
    if snap["codex_eligible_pending"]:
        lines.append("")
        lines.append("**Codex-eligible pending top 8**：")
        for t in snap["codex_eligible_pending"]:
            lines.append(_format_task_line(t))
        lines.append("")
        lines.append("**All pending top 8**：")
    if snap["pending_top"]:
        for t in snap["pending_top"]:
            lines.append(_format_task_line(t))
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
    lines.append("（此區由人工 / 互動 session 編輯。只有放在 KEEP 註解標記區段內的手寫內容會被 auto-regen 保留，其餘自動章節每 :50 覆寫。標記語法見 generate_handoff.py `_extract_keep_block` 或 docs；標記本身不寫在此說明以免與 extractor 自我衝突。）")
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
    except Exception:
        return ""
    start = txt.find("<!-- KEEP -->")
    if start == -1:
        return ""
    end = txt.find("<!-- /KEEP -->", start)
    if end == -1:
        return txt[start:].rstrip()
    return txt[start:end + len("<!-- /KEEP -->")]


def main() -> int:
    HANDOFF.parent.mkdir(parents=True, exist_ok=True)
    keep = _extract_keep_block(HANDOFF)
    content = build()
    if keep:
        content = content.rstrip() + "\n\n" + keep + "\n"
    HANDOFF.write_text(content, encoding="utf-8")
    print(f"handoff regenerated: {HANDOFF}  bytes={len(content)}  keep_preserved={bool(keep)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
