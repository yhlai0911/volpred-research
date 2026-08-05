#!/usr/bin/env python3
"""ops_snapshot — session 定位的單一儀器（stdlib-only，<1s）。

refactor_plan_token_ops_waste WS1b（2026-07-14）：token 週報顯示 repo-navigation
bash 一週 1,945 則 / 10.1M billable —— 每個新 session 都用十幾則 ls / git status /
jq 重新自我定位。本 script 把「session 開頭需要知道的運營狀態」聚合成一份 compact
JSON，一次呼叫取代整輪翻抽屜。

用法：
    uv run python scripts/ops_snapshot.py            # compact JSON to stdout
    uv run python scripts/ops_snapshot.py --pretty   # 縮排版（人讀）

結構化子查詢（ops-master G2, 2026-07-20）—— 取代 session 內散彈 jq/grep：
    --task <id_or_title_substr>   # next_tasks 單任務定位（id/status/priority/lane/claimed_by/result 前 200 字）
    --article <mile_id_or_slug>   # feed.json 文章定位（id/title/status/published_at/audience；絕不回 content）
    --job <schedule_id>           # runtime_schedules spec + job_liveness() 判活（D1 單一 evidence 源）
    --worktrees                   # 各 worktree 名/branch/unmerged/dirty/age，一列一個
    --receipts N                  # dispatch_state completions 尾 N 筆精簡欄位
    --queue [--status S --type T --limit N]  # 佇列計數 + 精簡列表
子查詢一律回「決策需要的極簡欄位」，嚴禁整檔 dump —— 單次輸出設計上 <2KB
（tests/test_ops_snapshot_queries.py 有 size 斷言 gate，防儀器自己變 token 黑洞）。

定位邊界（anti-stacking）：本 script 是「狀態定位」，不是健康裁決 ——
result-level 健康檢查的 owner 是 scripts/daily_checkup.py，alert 裁決的 owner 是
scripts/check_alerts.py，liveness evidence merge 的 owner 是
volpred.ops.schedules.job_liveness（本 script 只轉述它的結果）。
本 script 只讀不寫、不寄信、不判 breach。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
STORAGE = ROOT / "storage"
TPE = ZoneInfo("Asia/Taipei")

# 子查詢輸出紀律：截斷上限（欄位級），防單筆長 result/description 撐爆輸出
_RESULT_CLIP = 200
_TITLE_CLIP = 80
_MATCH_CAP = 5
_RECEIPT_CAP = 20


def _clip(value, n: int):
    if value is None:
        return None
    s = str(value)
    return s if len(s) <= n else s[: n - 1] + "…"


def _read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception as e:  # noqa: BLE001
        return {"_error": f"{type(e).__name__}: {e}"}


def _age_min(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        ts = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - ts).total_seconds() / 60, 1)
    except Exception as e:  # noqa: BLE001
        print(f"[ops_snapshot] WARN bad timestamp {iso!r}: {e}", file=sys.stderr)
        return None


def _git(args: list[str]) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10
        ).stdout.strip()
    except Exception as e:  # noqa: BLE001
        return f"_error:{type(e).__name__}"


def backbone() -> dict:
    st = _read_json(STORAGE / "ops" / "dispatch_state.json")
    if "_error" in st:
        return {"error": st["_error"]}
    return {
        "heartbeat_age_min": _age_min(st.get("last_heartbeat_at")),
        "current_job": st.get("current_job"),
        "current_jobs_n": len(st.get("current_jobs") or []),
        "last_fire_age_min": _age_min(st.get("last_fire_at")),
        "auth_blocked": st.get("auth_blocked"),
        "last_completions": [
            {
                "at": c.get("completed_at") or c.get("finished_at"),
                "status": c.get("verdict") or c.get("status") or c.get("outcome"),
            }
            for c in (st.get("completions") or [])[-3:]
        ],
    }


def queue(path: Path | None = None) -> dict:
    tasks = _load_tasks(path)
    if isinstance(tasks, dict):
        return {"error": tasks["_error"]}
    # dispatch-lanes R4（2026-07-21）：lane 可視化重用唯一判定 owner（task_urgency /
    # next_tasks lane vocab），不在這裡複製條件。Deferred import 同 --job 的慣例，
    # base snapshot 維持 stdlib-fast 啟動。
    src = ROOT / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from volpred.ops.next_tasks import (  # noqa: PLC0415 (deferred: base snapshot stays stdlib-fast)
        MAIN_THREAD_DISPATCH_LANES,
        normalize_dispatch_lane,
    )
    from volpred.ops.task_urgency import LANE_URGENT, classify  # noqa: PLC0415

    out: dict[str, object] = {}
    pending = [t for t in tasks if t.get("status") == "pending"]
    by_prio: dict[str, int] = {}
    for t in pending:
        k = f"p{t.get('priority', '?')}"
        by_prio[k] = by_prio.get(k, 0) + 1
    out["pending"] = len(pending)
    out["pending_by_priority"] = dict(sorted(by_prio.items()))
    # boss 急件（LANE_URGENT）待派數：>0 且下一班還沒 fire = 有人在等
    out["urgent_pending"] = sum(1 for t in pending if classify(t) == LANE_URGENT)
    # 互動主線程收件匣：headless fire 清不掉的 backlog，session 開頭要看得見。
    # 兩種表徵都算（漏一種 = 儀器 false-empty）：dispatch_lane=main_thread 的
    # pending，加上 handoff-main-thread CLI 轉出的 status=pending_main_thread。
    out["main_thread_inbox"] = sum(
        1
        for t in tasks
        if (
            t.get("status") == "pending"
            and normalize_dispatch_lane(t) in MAIN_THREAD_DISPATCH_LANES
        )
        or t.get("status") == "pending_main_thread"
    )
    out["in_flight"] = sum(1 for t in tasks if t.get("status") in ("claimed", "in_progress"))
    out["blocked"] = sum(1 for t in tasks if t.get("status") == "blocked")
    out["top_pending"] = [
        {"id": t.get("id"), "p": t.get("priority"), "type": t.get("task_type")}
        for t in sorted(pending, key=lambda x: (x.get("priority", 9)))[:5]
    ]
    return out


def content_pool() -> dict:
    feed = STORAGE / "reports" / "feed.json"
    if not feed.exists():
        return {"error": "feed.json missing"}
    try:
        # 只數 status，不載整檔進 caller context —— 這正是本儀器存在的理由
        d = json.loads(feed.read_text())
        arts = d.get("articles", d) if isinstance(d, dict) else d
        drafts = sum(1 for a in arts if a.get("status") == "draft")
        published_today = sum(
            1
            for a in arts
            if a.get("status") == "published"
            and str(a.get("published_at", ""))[:10]
            == datetime.now(TPE).strftime("%Y-%m-%d")
        )
        return {"drafts": drafts, "published_today": published_today}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def alerts_state(path: Path | None = None) -> dict:
    dedup = _read_json(path or STORAGE / "ops" / "alert_dedup.json")
    alerts = dedup.get("alerts") or {}
    if not isinstance(alerts, dict):
        return {"recent": []}
    now_recent = []
    for v in alerts.values():
        age = _age_min(v.get("sent_at") or v.get("ts") or v.get("last_sent_at") or v.get("first_sent_at"))
        if age is not None and age < 24 * 60:
            now_recent.append(
                {"level": v.get("level"), "title": str(v.get("title", ""))[:60], "age_min": age}
            )
    now_recent.sort(key=lambda x: x["age_min"])
    return {"sent_last_24h": len(now_recent), "recent": now_recent[:5]}


def git_state() -> dict:
    ahead = _git(["rev-list", "--count", "origin/main..main"])
    dirty = _git(["status", "--porcelain"])
    wts = _git(["worktree", "list", "--porcelain"]).count("worktree ")
    return {
        "branch": _git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "ahead_of_origin": ahead,
        "dirty_files": len(dirty.splitlines()) if dirty and not dirty.startswith("_error") else 0,
        "worktrees": wts,
        "head": _git(["log", "-1", "--format=%h %s"])[:80],
    }


def pointers() -> dict:
    hand = STORAGE / "ops" / "handoff_latest.md"
    out = {}
    if hand.exists():
        out["handoff_age_min"] = round(
            (datetime.now(timezone.utc).timestamp() - hand.stat().st_mtime) / 60, 1
        )
    out["health_instrument"] = "uv run python scripts/daily_checkup.py"
    out["dispatcher"] = "uv run python scripts/continue_task_dispatch.py --dry-run"
    return out


# ── 結構化子查詢（ops-master G2）─────────────────────────────────────────────


def _load_tasks(path: Path | None = None) -> list | dict:
    d = _read_json(path or STORAGE / "next_tasks.json")
    if isinstance(d, dict) and "_error" in d:
        return d
    tasks = d.get("tasks", d) if isinstance(d, dict) else d
    if not isinstance(tasks, list):
        return {"_error": "unexpected next_tasks shape"}
    return tasks


def _task_row(t: dict) -> dict:
    row = {
        "id": t.get("id"),
        "status": t.get("status"),
        "priority": t.get("priority"),
        "type": t.get("task_type"),
        "lane": t.get("dispatch_lane") or t.get("lane"),
        "claimed_by": t.get("claimed_by"),
        "title": _clip(t.get("title"), _TITLE_CLIP),
        "result": _clip(t.get("result") or t.get("result_summary"), _RESULT_CLIP),
    }
    if t.get("tombstone"):
        row["tombstone"] = True
    return {k: v for k, v in row.items() if v is not None}


def task_query(needle: str, *, path: Path | None = None) -> dict:
    """單任務定位：exact id 優先，否則 id/title case-insensitive substring。"""
    tasks = _load_tasks(path)
    if isinstance(tasks, dict):
        return {"error": tasks["_error"]}
    exact = [t for t in tasks if t.get("id") == needle]
    if exact:
        hits = exact
    else:
        low = needle.lower()
        hits = [
            t
            for t in tasks
            if low in str(t.get("id", "")).lower() or low in str(t.get("title", "")).lower()
        ]
    return {
        "query": needle,
        "matched": len(hits),
        "tasks": [_task_row(t) for t in hits[:_MATCH_CAP]],
    }


def article_query(needle: str, *, path: Path | None = None) -> dict:
    """feed 文章定位（不含 content）：id exact → id/slug substring → title substring。"""
    feed_path = path or STORAGE / "reports" / "feed.json"
    d = _read_json(feed_path)
    if isinstance(d, dict) and "_error" in d:
        return {"error": d["_error"]}
    arts = d.get("articles", d) if isinstance(d, dict) else d
    if not isinstance(arts, list):
        return {"error": "unexpected feed shape"}

    def _slug(a: dict) -> str:
        det = a.get("details")
        return str(det.get("slug", "")) if isinstance(det, dict) else ""

    exact = [a for a in arts if a.get("id") == needle]
    if exact:
        hits = exact
    else:
        low = needle.lower()
        hits = [
            a
            for a in arts
            if low in str(a.get("id", "")).lower() or low in _slug(a).lower()
        ] or [a for a in arts if low in str(a.get("title", "")).lower()]
    return {
        "query": needle,
        "matched": len(hits),
        "articles": [
            {
                "id": a.get("id"),
                "title": _clip(a.get("title"), _TITLE_CLIP),
                "status": a.get("status"),
                "published_at": a.get("published_at"),
                "audience": a.get("audience"),
            }
            for a in hits[:_MATCH_CAP]
        ],
    }


def job_query(
    schedule_id: str,
    *,
    config: dict | None = None,
    marker_state: dict | None = None,
    repo_root: Path | None = None,
) -> dict:
    """runtime_schedules spec + D1 job_liveness()（單一 liveness evidence 源）。"""
    src = ROOT / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from volpred.ops.schedules import job_liveness  # noqa: PLC0415 (deferred: base snapshot stays stdlib-fast)

    if config is None:
        from volpred.config import load_runtime_schedules  # noqa: PLC0415

        config = load_runtime_schedules()

    found: tuple[str, dict] | None = None
    substr: tuple[str, dict] | None = None
    low = schedule_id.lower()
    for section_name, section in config.items():
        items = section.get("items") if isinstance(section, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id", ""))
            if item_id == schedule_id:
                found = (section_name, item)
                break
            if substr is None and low in item_id.lower():
                substr = (section_name, item)
        if found:
            break
    picked = found or substr
    if picked is None:
        return {"query": schedule_id, "matched": 0}
    section_name, item = picked
    live = job_liveness(item, marker_state=marker_state, repo_root=repo_root or ROOT)
    spec = {
        "id": item.get("id"),
        "section": section_name,
        "cron": item.get("cron"),
        "label": _clip(item.get("label"), _TITLE_CLIP),
        "wrapper_script": item.get("wrapper_script"),
        "log_path": item.get("log_path") or item.get("log"),
        "host_crontab_managed": item.get("host_crontab_managed"),
        "piggy_back_enabled": item.get("piggy_back_enabled"),
    }
    return {
        "query": schedule_id,
        "matched": 1,
        "spec": {k: v for k, v in spec.items() if v is not None},
        "liveness": {
            "last_success": live.last_success.isoformat() if live.last_success else None,
            "last_success_age_min": _age_min(
                live.last_success.isoformat() if live.last_success else None
            ),
            "success_source": live.success_source,
            "last_activity": live.last_activity.isoformat() if live.last_activity else None,
            "last_activity_age_min": _age_min(
                live.last_activity.isoformat() if live.last_activity else None
            ),
            "marker_eligible": live.marker_eligible,
        },
    }


def worktrees_query(*, repo_root: Path | None = None, main_branch: str = "main") -> dict:
    """各 worktree 一列：name/branch/unmerged(ahead of main)/dirty/age_h。"""
    root = repo_root or ROOT

    def _g(args: list[str], cwd: Path) -> str:
        try:
            return subprocess.run(
                ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=15
            ).stdout.strip()
        except Exception as e:  # noqa: BLE001
            print(f"[ops_snapshot] WARN git {args[:2]} failed: {e}", file=sys.stderr)
            return ""

    porcelain = _g(["worktree", "list", "--porcelain"], root)
    entries: list[dict] = []
    cur: dict = {}
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            if cur:
                entries.append(cur)
            cur = {"path": line.split(" ", 1)[1]}
        elif line.startswith("branch "):
            cur["branch"] = line.split(" ", 1)[1].removeprefix("refs/heads/")
        elif line == "detached":
            cur["branch"] = "(detached)"
    if cur:
        entries.append(cur)

    rows = []
    for e in entries[1:]:  # git 保證第一個 entry 是主 repo，跳過
        p = Path(e["path"])
        branch = e.get("branch", "?")
        ahead: int | None = None
        if branch not in ("?", "(detached)"):
            raw = _g(["rev-list", "--count", f"{main_branch}..{branch}"], root)
            ahead = int(raw) if raw.isdigit() else None
        status = _g(["status", "--porcelain"], p) if p.is_dir() else ""
        age_h = None
        try:
            age_h = round(
                (datetime.now(timezone.utc).timestamp() - p.stat().st_mtime) / 3600, 1
            )
        except OSError as exc:
            print(f"[ops_snapshot] WARN worktree stat failed {p}: {exc}", file=sys.stderr)
        row = {
            "name": p.name,
            "unmerged": ahead,
            "dirty": len(status.splitlines()) if status else 0,
            "age_h": age_h,
        }
        if branch not in (f"worktree-{p.name}", f"wt/{p.name}"):
            row["branch"] = _clip(branch, 48)  # 非慣例命名才值得多佔欄位
        rows.append(row)
    return {"n": len(rows), "worktrees": rows}


def receipts_query(n: int, *, path: Path | None = None) -> dict:
    """dispatch_state completions 尾 n 筆精簡欄位（execution receipts）。"""
    st = _read_json(path or STORAGE / "ops" / "dispatch_state.json")
    if "_error" in st:
        return {"error": st["_error"]}
    comps = st.get("completions") or []
    n = max(1, min(int(n), _RECEIPT_CAP))
    rows = [
        {
            "at": c.get("completed_at"),
            "job": str(c.get("job_id", ""))[:8] or None,
            "slot": c.get("slot_id"),
            "reason": _clip(c.get("fire_reason"), 48),
            "exit": c.get("exit_code"),
            "outcome": c.get("outcome"),
            "dur_s": c.get("duration_s"),
        }
        for c in comps[-n:]
    ]
    return {"total": len(comps), "shown": len(rows), "receipts": rows}


def queue_query(
    status: str | None = None,
    task_type: str | None = None,
    limit: int = 10,
    *,
    path: Path | None = None,
) -> dict:
    """佇列計數 + 精簡列表。預設 status=pending；limit 上限 20。"""
    tasks = _load_tasks(path)
    if isinstance(tasks, dict):
        return {"error": tasks["_error"]}
    status = status or "pending"
    limit = max(1, min(int(limit), 20))
    hits = [
        t
        for t in tasks
        if t.get("status") == status
        and (task_type is None or t.get("task_type") == task_type)
    ]
    hits.sort(key=lambda t: (t.get("priority", 9), str(t.get("created_at", ""))))
    counts = queue(path)
    counts.pop("top_pending", None)  # 與下方 tasks 列表重複，砍掉省輸出
    rows = []
    for t in hits[:limit]:
        row = _task_row(t)
        row.pop("result", None)  # 列表模式不帶 result，單任務細節走 --task
        row.pop("status", None)  # 已由 filter 隱含
        rows.append(row)
    return {
        "filter": {"status": status, **({"type": task_type} if task_type else {})},
        "matched": len(hits),
        "counts": counts,
        "tasks": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pretty", action="store_true")
    ap.add_argument("--task", metavar="ID_OR_TITLE", help="next_tasks 單任務定位")
    ap.add_argument("--article", metavar="ID_OR_SLUG", help="feed 文章定位（不含 content）")
    ap.add_argument("--job", metavar="SCHEDULE_ID", help="排程 spec + liveness")
    ap.add_argument("--worktrees", action="store_true", help="worktree 清單（一列一個）")
    ap.add_argument("--receipts", type=int, metavar="N", help="dispatch completions 尾 N 筆")
    ap.add_argument("--queue", action="store_true", help="佇列計數 + 精簡列表")
    ap.add_argument("--status", help="--queue 的 status filter（預設 pending）")
    ap.add_argument("--type", dest="task_type", help="--queue 的 task_type filter")
    ap.add_argument("--limit", type=int, default=10, help="--queue 列表上限（預設 10，cap 20）")
    args = ap.parse_args()

    out: dict = {}
    if args.task:
        out["task"] = task_query(args.task)
    if args.article:
        out["article"] = article_query(args.article)
    if args.job:
        out["job"] = job_query(args.job)
    if args.worktrees:
        out["worktrees"] = worktrees_query()
    if args.receipts is not None:
        out["receipts"] = receipts_query(args.receipts)
    if args.queue:
        out["queue"] = queue_query(args.status, args.task_type, args.limit)

    if not out:  # 無子查詢 → 完整定位 snapshot（原行為）
        out = {
            "ts_taipei": datetime.now(TPE).strftime("%Y-%m-%d %H:%M:%S"),
            "backbone": backbone(),
            "queue": queue(),
            "content_pool": content_pool(),
            "alerts": alerts_state(),
            "git": git_state(),
            "pointers": pointers(),
        }
    print(json.dumps(out, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
