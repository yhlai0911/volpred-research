#!/usr/bin/env python3
"""Deduplicate storage/next_tasks.json by task id, preserving the best receipt.

Why this exists:
- `task_pool_claim.py` assumes task ids are unique.
- A duplicate pending row after a terminal row creates a zombie task:
  dispatcher sees pending, but claim/start resolves to the earlier terminal row.

Two modes:
- default: exact-id dedupe (below).
- ``--semantic``: **report-only** semantic duplicate scan over open tasks, using
  ``volpred.ops.task_signature`` (file + symbol + failure_class + rare ids, with a
  title-anchor false-positive brake). Exact-id dedupe reported
  ``before=3242 / after=3242 / dropped=0`` on a queue that had the same bug filed
  twice under two ids; this mode is what finds those. The steady-state fix is the
  admission gate in ``volpred.ops.next_tasks.append_task_record`` — this scan is
  for the backlog that predates it.

Policy:
- Group by exact `id`.
- Keep the "best" row per id by lifecycle depth:
  terminal (succeeded/failed/blocked) > in_progress > claimed > pending_main_thread > pending > blank
- Break ties by richer receipts (`completed_at`, `started_at`, `claimed_at`, `result` length),
  then preserve the earlier row.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
NEXT_TASKS = ROOT / "storage" / "next_tasks.json"

from volpred.canonical_write import guard_canonical_write  # noqa: E402
from volpred.ops.next_tasks import write_tasks_to_handle  # noqa: E402

STATUS_RANK = {
    "succeeded": 60,
    "failed": 60,
    "blocked": 60,
    "succeeded_null_result": 60,
    "closed": 60,
    "superseded": 60,
    "in_progress": 40,
    "claimed": 30,
    "pending_main_thread": 20,
    "pending": 10,
    "": 0,
}


def _task_key(task: dict[str, Any]) -> str:
    """Return the queue key used by task_pool_claim.py.

    Some legacy rows still use `task_id` instead of `id`; claim/list accepts
    both, so dedupe must group both forms or zombie pending duplicates can
    continue blocking claims.
    """
    return str(task.get("id") or task.get("task_id") or "")


def _utc_iso_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _warn(message: str) -> None:
    print(f"[dedupe_next_tasks] WARN {message}", file=sys.stderr)


def _load_tasks(fh) -> list[Any]:
    fh.seek(0)
    try:
        data = json.load(fh)
    except json.JSONDecodeError as exc:
        _warn(f"next_tasks read failed path={NEXT_TASKS} error={type(exc).__name__}: {exc}")
        raise SystemExit(f"failed to parse {NEXT_TASKS}: {type(exc).__name__}: {exc}") from exc
    if not isinstance(data, list):
        _warn(f"next_tasks schema invalid path={NEXT_TASKS} expected=list actual={type(data).__name__}")
        raise SystemExit("next_tasks.json is not a list")
    return data


def _score(task: dict[str, Any], index: int) -> tuple[int, int, int, int, int]:
    status = str(task.get("status") or "").lower()
    return (
        STATUS_RANK.get(status, 0),
        1 if task.get("completed_at") else 0,
        1 if task.get("started_at") else 0,
        1 if task.get("claimed_at") else 0,
        len(str(task.get("result") or "")) * 100000 - index,
    )


def dedupe(tasks: list[Any]) -> tuple[list[Any], list[dict[str, Any]]]:
    grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    ordered: list[str] = []
    passthrough: list[Any] = []

    for idx, task in enumerate(tasks):
        if not isinstance(task, dict):
            _warn(
                "next_tasks entry schema invalid; preserving passthrough "
                f"index={idx} type={type(task).__name__}"
            )
            passthrough.append(task)
            continue
        task_id = _task_key(task)
        if not task_id:
            passthrough.append(task)
            continue
        if task_id not in grouped:
            grouped[task_id] = []
            ordered.append(task_id)
        grouped[task_id].append((idx, task))

    deduped: list[Any] = []
    dropped: list[dict[str, Any]] = []
    for task_id in ordered:
        entries = grouped[task_id]
        if len(entries) == 1:
            deduped.append(entries[0][1])
            continue
        best_idx, best_task = max(entries, key=lambda pair: _score(pair[1], pair[0]))
        kept = dict(best_task)
        kept["dedup_kept_at"] = kept.get("dedup_kept_at") or _utc_iso_z()
        kept["dedup_kept_reason"] = (
            f"kept among {len(entries)} duplicates by status/receipt precedence; "
            f"statuses={[str(t.get('status') or '') for _, t in entries]}"
        )
        deduped.append(kept)
        for idx, task in entries:
            if idx == best_idx:
                continue
            dropped.append({
                "id": task_id,
                "dropped_status": task.get("status"),
                "kept_status": best_task.get("status"),
                "created_at": task.get("created_at"),
            })

    deduped.extend(passthrough)
    return deduped, dropped


def _render_groups(groups: list[dict], heading_prefix: str) -> list[str]:
    lines: list[str] = []
    for n, g in enumerate(groups, 1):
        keep = g["keep"]
        lines += [
            f"### {heading_prefix} 第 {n} 組（{len(g['members'])} 張）",
            "",
            f"- **保留**：`{g['keep_id']}` — {keep.get('title', '')}",
            f"  - created_at: {keep.get('created_at', '')} / status: {keep.get('status', '')}",
        ]
        for m in g["merge"]:
            lines.append(
                f"- **合併掉**：`{m.get('id', '')}` — {m.get('title', '')}"
                f"（created_at: {m.get('created_at', '')} / status: {m.get('status', '')}）"
            )
        lines += ["", f"- signature: `{g['signature']}`", "- 判定理由："]
        for p in g["pairs"]:
            lines.append(
                f"  - `{p['a_id']}` ≡ `{p['b_id']}` (score={p['score']}, "
                f"anchor={p['anchor']}): {'; '.join(p['reasons'])}"
            )
        lines.append("")
    return lines


def _semantic_report(out_path: Path | None, since: str | None = None) -> int:
    """Report-only semantic duplicate scan over open tasks.

    Never writes next_tasks.json: merge adjudication is a human call, and the
    main thread may hold the queue. Output is a markdown proposal list.
    """
    from volpred.ops.task_signature import OPEN_STATUSES, find_duplicate_groups

    with NEXT_TASKS.open("r", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
        try:
            tasks = _load_tasks(fh)
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    open_tasks = [
        t
        for t in tasks
        if isinstance(t, dict) and str(t.get("status") or "").lower() in OPEN_STATUSES
    ]
    groups = find_duplicate_groups(open_tasks)

    lines: list[str] = [
        "# 任務池語意重複掃描報告",
        "",
        f"- 產生時間：{_utc_iso_z()}",
        f"- 佇列總筆數：{len(tasks)}；掃描範圍（open = pending/in_progress/claimed）：{len(open_tasks)}",
        f"- 判定為語意重複的組數：{len(groups)}"
        f"；涉及單數：{sum(len(g['members']) for g in groups)}"
        f"；建議合併掉：{sum(len(g['merge']) for g in groups)}",
        "",
        "> **本報告不動任何檔案。** 合併裁決需人工確認後再執行。",
        "> signature = 檔案 + 符號 + failure_class + 稀有識別碼，並以「兩張單的**標題**",
        "> 必須共享錨點」作為誤報煞車（寧可漏報不可誤報）。",
        "",
        "## A. 現有 open 任務的建議合併清單（可行動）",
        "",
    ]
    lines += _render_groups(groups, "A") or ["（無）", ""]

    calib_groups: list[dict] = []
    if since:
        window = [
            t
            for t in tasks
            if isinstance(t, dict) and str(t.get("created_at") or "") >= since
        ]
        calib_groups = find_duplicate_groups(window)
        lines += [
            f"## B. 校準掃描：{since} 之後建立的所有任務（含已結案，僅供驗證，不可行動）",
            "",
            f"- 掃描 {len(window)} 張，判定 {len(calib_groups)} 組語意重複。",
            "- 目的：證明偵測器在真實資料上抓得到東西 —— A 區為空時，區別",
            "  「沒有重複」與「偵測器壞掉」的唯一方法。",
            "",
        ]
        lines += _render_groups(calib_groups, "B") or ["（無）", ""]

    text = "\n".join(lines)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        print(
            json.dumps(
                {
                    "ok": True,
                    "mode": "semantic-report",
                    "scanned": len(open_tasks),
                    "groups": len(groups),
                    "would_merge": sum(len(g["merge"]) for g in groups),
                    "calibration_groups": len(calib_groups),
                    "report": str(out_path),
                    "applied": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(text)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="rewrite storage/next_tasks.json in-place")
    ap.add_argument("--json", action="store_true", help="print full JSON summary")
    ap.add_argument(
        "--semantic",
        action="store_true",
        help="report-only semantic duplicate scan over open tasks (never writes the queue)",
    )
    ap.add_argument("--report-out", help="write the --semantic markdown report to this path")
    ap.add_argument(
        "--calibrate-since",
        help="also scan all tasks (any status) created on/after this ISO date, as a "
        "detector-is-alive check appended to the report",
    )
    args = ap.parse_args()

    if args.semantic:
        if args.apply:
            raise SystemExit("--semantic is report-only; merge adjudication is manual")
        return _semantic_report(
            Path(args.report_out) if args.report_out else None,
            since=args.calibrate_since,
        )

    if args.apply:
        guard_canonical_write(NEXT_TASKS)
    mode = "r+" if args.apply else "r"
    with NEXT_TASKS.open(mode, encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX if args.apply else fcntl.LOCK_SH)
        try:
            tasks = _load_tasks(fh)
            deduped, dropped = dedupe(tasks)
            summary = {
                "ok": True,
                "before": len(tasks),
                "after": len(deduped),
                "dropped_count": len(dropped),
                "dropped": dropped,
                "apply": args.apply,
            }
            if args.apply and dropped:
                # WS-A1b: canonical primitive on the already-held LOCK_EX handle
                # (serialize-first + priority normalization + status audits).
                write_tasks_to_handle(fh, deduped)
            if args.json:
                print(json.dumps(summary, ensure_ascii=False, indent=2))
            else:
                print(
                    json.dumps(
                        {
                            "ok": True,
                            "before": len(tasks),
                            "after": len(deduped),
                            "dropped_count": len(dropped),
                            "apply": args.apply,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
