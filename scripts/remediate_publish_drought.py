"""發文脫班（publishing_freshness）dead-man switch 的 auto-remediation ladder。

Boss directive email-12559（2026-07-03，「你應該不是建議行動 而是你應該要直接行動吧？」）：
outcome-level alert 必須**直接行動**修復 breach，不是把 to-do list email 給老闆。

此腳本是「發文脫班補救」的**唯一 owner**（single enforcement owner，per anti-stacking
rule）。由 `scripts/check_alerts.py` 每小時在寄出 publishing_freshness alert email **之前**
以 bounded subprocess 呼叫，也會由 `continue-task-maintain` heartbeat 在 breach 出現時即時觸發；
腳本內建 non-blocking lock，避免兩條路徑同時補救。也可手動跑：

    uv run python scripts/remediate_publish_drought.py --apply --json
    uv run python scripts/remediate_publish_drought.py --dry-run   # 只報 drought 狀態

補救階梯：
  1. 若 feed 未在 active-window（台北 09:00–23:00）脫班 → no-op（不瞎補）。
  2. force `release_pool_by_settings(force=True)` — 觸發 `_maybe_drought_release`
     circuit-breaker，釋出 least-dup-like 的 dedup-blocked 草稿。
  3. 若 released == 0（草稿池空 / 全是已發過主題的 arc-dup 重寫，breaker 無可釋出）→
     `refill_task_pool.refill()` 補 fresh 研究主題進 task pool，下一班 hourly dispatch
     （每小時 :07）自動生成並發佈。

每步結果寫入回傳 summary + `diagnostics.warn` log；publishing_freshness alert body
讀「系統已自動修復」框架，不再對老闆下 imperative 指令。
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
# Allow importing sibling script `refill_task_pool.py`.
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _acquire_apply_lock(storage_dir: str):
    lock_path = Path(storage_dir) / "ops" / "remediate_publish_drought.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None  # silent-ok: lock held by concurrent run — single-flight by design
    handle.seek(0)
    handle.truncate()
    handle.write(
        json.dumps(
            {"pid": os.getpid(), "locked_at": datetime.now(timezone.utc).isoformat()},
            ensure_ascii=False,
        )
        + "\n"
    )
    handle.flush()
    return handle


def _release_apply_lock(handle) -> None:
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def remediate(*, apply: bool, storage_dir: str = "storage") -> dict:
    """Run (or preview) the publish-drought remediation ladder.

    Returns a summary dict. Never raises for operational failures — each step's
    error is captured in `steps[].error` and logged via diagnostics.warn so the
    caller (check_alerts hourly fire) stays observable and non-fatal.
    """
    from volpred.ops.alerts import _parse_publishing_freshness_state
    from volpred.ops.diagnostics import warn

    now = datetime.now(timezone.utc)
    state = _parse_publishing_freshness_state(storage_dir, now)
    details = state.get("details") or {}
    gap = details.get("publish_gap_hours")
    in_active_window = details.get("in_active_window")

    if not state.get("breached"):
        return {
            "attempted": False,
            "reason": "no_drought",
            "gap_hours": gap,
            "in_active_window": in_active_window,
        }

    result: dict = {
        "attempted": True,
        "gap_hours": gap,
        "threshold_hours": details.get("threshold_hours"),
        "apply": apply,
        "steps": [],
    }

    if not apply:
        result["steps"].append({"step": "would_force_release_then_refill", "dry_run": True})
        return result

    lock_handle = None
    try:
        lock_handle = _acquire_apply_lock(storage_dir)
    except Exception as exc:  # noqa: BLE001
        warn("remediate_drought", "apply lock failed", err=str(exc))
        return {
            "attempted": False,
            "reason": "lock_failed",
            "error": str(exc),
            "gap_hours": gap,
            "threshold_hours": details.get("threshold_hours"),
            "apply": apply,
        }
    if lock_handle is None:
        return {
            "attempted": False,
            "reason": "remediation_already_running",
            "gap_hours": gap,
            "threshold_hours": details.get("threshold_hours"),
            "apply": apply,
        }

    try:
        # Step 1: force release. release_pool_articles internally runs the drought
        # circuit-breaker (_maybe_drought_release), which force-releases the least
        # dup-like dedup-blocked draft. max_articles_per_run + the breaker's own
        # anti-thrash window make this safe to call even if the interval piggy-back
        # already released this hour (it will simply release 0 more).
        released = 0
        try:
            from volpred.ops import release_pool_by_settings

            rel = release_pool_by_settings(force=True, storage_dir=storage_dir)
            released = int(rel.get("released_count") or 0)
            result["steps"].append(
                {
                    "step": "force_release",
                    "ok": True,
                    "released": released,
                    "released_ids": [a.get("id") for a in (rel.get("released") or [])],
                }
            )
        except Exception as exc:  # noqa: BLE001 — must not crash the alert fire
            warn("remediate_drought", "force_release failed", err=str(exc))
            result["steps"].append({"step": "force_release", "ok": False, "error": str(exc)})

        # Step 2: nothing published (empty pool / all drafts are arc-dup rehashes of
        # live content → breaker withholds). Auto-supply fresh research topics so the
        # NEXT hourly dispatch generates + publishes genuinely new content. This is
        # the wire that was missing — previously the alert just emailed the boss a
        # to-do list to "派 daily_article 補非飽和主題" (email-12559 complaint).
        if released == 0:
            try:
                from refill_task_pool import refill

                rf = refill(4, dry_run=False)
                result["steps"].append(
                    {
                        "step": "refill_fresh",
                        "ok": True,
                        "added": rf.get("added", 0),
                        "added_ids": rf.get("added_ids", []),
                        "reason": rf.get("reason"),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                warn("remediate_drought", "refill_fresh failed", err=str(exc))
                result["steps"].append({"step": "refill_fresh", "ok": False, "error": str(exc)})
    finally:
        _release_apply_lock(lock_handle)

    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="execute the remediation ladder")
    ap.add_argument("--dry-run", action="store_true", help="report drought state only, take no action")
    ap.add_argument("--storage-dir", default="storage")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON summary")
    args = ap.parse_args()

    apply = args.apply and not args.dry_run
    res = remediate(apply=apply, storage_dir=args.storage_dir)

    if args.json:
        print(json.dumps(res, ensure_ascii=False))
    elif not res.get("attempted"):
        print(f"[remediate-drought] no drought (gap={res.get('gap_hours')}h) — no action")
    else:
        print(f"[remediate-drought] DROUGHT gap={res.get('gap_hours')}h apply={apply}")
        for step in res.get("steps", []):
            print(f"  - {step}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
