"""Audit local .release_settings.json vs Supabase content_release_settings (id=default).

Detects drift between the two sources caused by silent PATCH failures
(`_update_content_release_settings` returns False on Supabase 4xx/5xx but does
not raise). Local-first design means subsequent reads succeed, but Supabase row
goes stale → admin UI / cross-session readers see wrong release cadence.

Run modes:
- default: compare, print drift report, exit 0 even on drift (observability)
- --fix:  push local payload to Supabase to repair drift (idempotent PATCH),
          and queue one idempotent P3 repair task per starved draft (WS-I
          actuator — the starved exit 1 must have an exit path, not just a
          verdict; see _open_starved_tasks)
- --json: emit structured JSON to stdout for log scrapers / downstream alerts

Drift fields checked: mode, interval_minutes, max_articles_per_run, due_only,
include_drafts, preferred_audiences, last_released_at.

Beyond field drift (added 2026-07-19, R4), two checks that exit 1 because
nothing downstream repairs them:
- cadence: the real trigger cadence (LaunchAgent plist, plus any crontab entry
  driving the pool) must be at least as frequent as interval_minutes, or the
  configured rate is unreachable and a fallback is silently carrying it.
- starved drafts: any draft/scheduled article the release loop has skipped more
  than five times.

Hook: suitable for hourly piggy-back via run_due_jobs (add an entry to
config/runtime_schedules.json with cron='17 */6 * * *' if frequent audit needed).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


_AUDIT_FIELDS = (
    "mode",
    "interval_minutes",
    "max_articles_per_run",
    "due_only",
    "include_drafts",
    "preferred_audiences",
    "last_released_at",
)


def _warn_audit(message: str, *, path: Path | None = None, exc: Exception | None = None) -> None:
    details = []
    if path is not None:
        details.append(f"path={path}")
    if exc is not None:
        details.append(f"error={type(exc).__name__}: {exc}")
    suffix = " " + " ".join(details) if details else ""
    print(f"[audit] WARN {message}{suffix}", file=sys.stderr)


def _load_local() -> dict | None:
    path = PROJECT_ROOT / "storage" / ".release_settings.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        _warn_audit("local release settings read failed; treating local settings as unavailable", path=path, exc=exc)
        return None
    if not isinstance(data, dict):
        _warn_audit(
            "local release settings schema is not an object; treating local settings as unavailable",
            path=path,
        )
        return None
    return data


def _load_remote() -> dict | None:
    from scripts.supabase_sync import _select_rows  # type: ignore

    try:
        rows = _select_rows("content_release_settings", id="default")
    except Exception as exc:  # noqa: BLE001
        print(f"[audit] supabase select error: {exc}", file=sys.stderr)
        return None
    return rows[0] if rows else None


def _diff(local: dict, remote: dict) -> list[dict]:
    drift = []
    for field in _AUDIT_FIELDS:
        lv = local.get(field)
        rv = remote.get(field)
        # Local 'auto' maps to remote 'scheduled' on the wire (Supabase CHECK
        # constraint); not a real drift.
        if field == "mode" and lv == "auto" and rv == "scheduled":
            continue
        if isinstance(lv, list) and isinstance(rv, list):
            if list(lv) != list(rv):
                drift.append({"field": field, "local": lv, "remote": rv})
        elif lv != rv:
            drift.append({"field": field, "local": lv, "remote": rv})
    return drift


def _push_fix(local: dict) -> bool:
    from scripts.supabase_sync import _patch_where  # type: ignore

    payload = {field: local.get(field) for field in _AUDIT_FIELDS}
    payload["updated_at"] = local.get("updated_at")
    # Match _update_content_release_settings: Supabase mode CHECK rejects 'auto'
    if payload.get("mode") == "auto":
        payload["mode"] = "scheduled"
    try:
        return bool(_patch_where("content_release_settings", {"id": "default"}, payload))
    except Exception as exc:  # noqa: BLE001
        print(f"[audit] patch error: {exc}", file=sys.stderr)
        return False


_RELEASE_PLIST = "com.volpred.release-pool.plist"
_RELEASE_CRON_MARKERS = ("cron_release_pool.sh", "release-pool", "release_pool")
_STARVED_SKIP_THRESHOLD = 5


def _launchagent_gap_minutes() -> tuple[int | None, list[str]]:
    """Largest gap (minutes) between consecutive release-pool LaunchAgent fires."""
    import plistlib

    path = Path.home() / "Library" / "LaunchAgents" / _RELEASE_PLIST
    if not path.exists():
        return None, []
    try:
        plist = plistlib.loads(path.read_bytes())
    except Exception as exc:  # noqa: BLE001
        _warn_audit("release-pool plist unreadable", path=path, exc=exc)
        return None, []

    if isinstance(plist.get("StartInterval"), int):
        secs = int(plist["StartInterval"])
        return secs // 60, [f"StartInterval={secs}s"]

    entries = plist.get("StartCalendarInterval") or []
    if isinstance(entries, dict):
        entries = [entries]
    minutes: list[int] = []
    for e in entries:
        if not isinstance(e, dict) or "Hour" not in e:
            # A calendar entry without an Hour fires every hour; cadence is then
            # at most 60min and never the binding constraint here.
            return 60, ["hourly calendar entry"]
        minutes.append(int(e["Hour"]) * 60 + int(e.get("Minute") or 0))
    if not minutes:
        return None, []
    minutes.sort()
    if len(minutes) == 1:
        return 24 * 60, [f"single daily fire at {minutes[0] // 60:02d}:{minutes[0] % 60:02d}"]
    gaps = [b - a for a, b in zip(minutes, minutes[1:])]
    gaps.append(minutes[0] + 24 * 60 - minutes[-1])  # wrap past midnight
    labels = [f"{m // 60:02d}:{m % 60:02d}" for m in minutes]
    return max(gaps), [f"LaunchAgent fires at {', '.join(labels)}"]


def _crontab_release_lines() -> list[str]:
    import subprocess

    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
    except Exception as exc:  # noqa: BLE001
        # 空 list 與「crontab 真的沒有 release line」無法區分 —— 不講出來，
        # audit 就會把「查不到」報成「沒有」。
        from volpred.ops.diagnostics import warn

        warn(f"crontab -l 執行失敗，本次 audit 略過 crontab 來源：{exc}")
        return []
    if out.returncode != 0:
        return []
    return [
        line.strip()
        for line in (out.stdout or "").splitlines()
        if any(m in line for m in _RELEASE_CRON_MARKERS) and not line.strip().startswith("#")
    ]


def _cadence_check(local: dict) -> dict:
    """Does the real trigger cadence actually honour interval_minutes?

    2026-07-19 R4 (boss 20:14): this audit only compared settings fields, so it
    printed `ok` for nine hours while the pool released nothing. The reason was
    never a drifted field — the LaunchAgent fires every 6h while
    interval_minutes says 4h, so the documented cadence was unreachable and the
    hourly check_alerts fallback was quietly carrying the whole release rate. An
    audit that cannot see its own trigger is checking the map, not the road.
    """
    interval = local.get("interval_minutes")
    gap, notes = _launchagent_gap_minutes()
    cron_lines = _crontab_release_lines()
    result: dict = {
        "interval_minutes": interval,
        "launchagent_max_gap_minutes": gap,
        "trigger_notes": notes,
        "crontab_release_entries": cron_lines,
        "ok": True,
    }
    if not isinstance(interval, int) or gap is None:
        result["status"] = "unknown"
        return result
    if cron_lines:
        # A crontab entry that also drives the pool tightens the real cadence;
        # its schedule is not parsed here, so do not claim misalignment.
        result["status"] = "cron_present_not_parsed"
        return result
    if gap > interval:
        result["ok"] = False
        result["status"] = "cadence_misaligned"
        result["detail"] = (
            f"trigger fires at most every {gap}min but interval_minutes="
            f"{interval}min — the configured cadence is unreachable on the "
            f"regular path; anything above that rate is coming from a fallback"
        )
    else:
        result["status"] = "aligned"
    return result


def _starved_drafts(limit: int = 10) -> list[dict]:
    """Drafts the release loop keeps skipping — the symptom R4 could not see."""
    feed_path = PROJECT_ROOT / "storage" / "reports" / "feed.json"
    if not feed_path.exists():
        return []
    try:
        feed = json.loads(feed_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        _warn_audit("feed read failed; starved-draft check skipped", path=feed_path, exc=exc)
        return []
    starved = []
    for item in feed if isinstance(feed, list) else []:
        if not isinstance(item, dict) or item.get("status") not in ("draft", "scheduled"):
            continue
        skips = ((item.get("details") or {}).get("release_audit_skipped_count")) or 0
        if isinstance(skips, int) and skips > _STARVED_SKIP_THRESHOLD:
            starved.append({
                "id": item.get("id"),
                "title": str(item.get("title") or "")[:60],
                "skipped": skips,
            })
    starved.sort(key=lambda x: -x["skipped"])
    return starved[:limit]


def _open_starved_tasks(starved: list[dict], *, queue_path: Path | None = None) -> list[dict]:
    """Actuator: starved-draft findings → pending repair tasks (WS-I, 2026-07-20).

    The starved check used to exit 1 with no consumer: mile_47c4bc3e was skipped
    20 times over repeated audit fires and nothing ever queued a repair — the
    exit code was a verdict without an exit path. One idempotent P3 task per
    starved article (id ``starved_draft_<article_id>``) gives the block a way
    out; re-runs while the task is queued are no-ops. Append failures are loud
    (no-silent-fallback) and land in the per-article receipt.
    """
    from datetime import datetime, timezone

    from volpred.ops.next_tasks import append_task_record

    path = (
        queue_path
        if queue_path is not None
        else PROJECT_ROOT / "storage" / "next_tasks.json"
    )
    now_iso = datetime.now(timezone.utc).isoformat()
    receipts: list[dict] = []
    for d in starved:
        art_id = d.get("id")
        if not art_id:
            _warn_audit("starved draft entry without id; cannot open repair task")
            receipts.append({"article_id": None, "created": False, "error": "missing article id"})
            continue
        task = {
            "id": f"starved_draft_{art_id}",
            "task_type": "platform_ops",
            "priority": 3,
            "source": "auto_discovered",
            "status": "pending",
            "created_at": now_iso,
            "created_by": "audit_release_settings",
            "title": f"release 連續跳過 {d.get('skipped')} 次：{art_id} 卡池裁決",
            "description": (
                f"文章 {art_id}（{d.get('title', '')}）已被 release loop 跳過 "
                f"{d.get('skipped')} 次（門檻 {_STARVED_SKIP_THRESHOLD}）。裁決出口三選一，"
                "不准繼續讓它空轉：\n"
                "1. 修 gate：查 feed 該篇 details.release_audit_* 的 skip 原因，若是 gate "
                "誤攔（audience/dedup/quality 判錯）修 gate 後讓它自然釋出；\n"
                "2. 手動釋出：內容確實可發 → 走正式 release pool / feed-publisher 流程發佈；\n"
                "3. retire：內容不該發（過時/重複/品質不足，寫明理由）→ 正式下架該 draft。\n"
                "裁決寫進本 task 的 result。來源：scripts/audit_release_settings.py --fix（WS-I）。"
            ),
        }
        receipt = {"article_id": art_id, "task_id": task["id"]}
        try:
            _, created = append_task_record(task, path=path, if_exists="skip")
            receipt["created"] = created
        except Exception as exc:  # noqa: BLE001 — 一單失敗不擋其他單，但必留 trace
            _warn_audit(f"starved-draft task append failed for {art_id}", exc=exc)
            receipt["created"] = False
            receipt["error"] = f"{type(exc).__name__}: {exc}"
        receipts.append(receipt)
    return receipts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true", help="Push local → Supabase if drift detected")
    parser.add_argument("--json", action="store_true", help="Emit JSON report to stdout")
    args = parser.parse_args()

    local = _load_local()
    if local is None:
        report = {"status": "no_local_file", "ok": False}
        print(json.dumps(report) if args.json else "[audit] no local .release_settings.json")
        return 0

    # Two checks that do not depend on Supabase being reachable, and that the
    # settings-only audit was structurally blind to (2026-07-19 R4).
    cadence = _cadence_check(local)
    starved = _starved_drafts()
    # --fix is repair mode: starvation findings must land as queued repair
    # tasks, not just an exit code (WS-I actuator; observability-only runs
    # stay read-only).
    starved_tasks = _open_starved_tasks(starved) if (args.fix and starved) else []

    remote = _load_remote()
    if remote is None:
        report = {"status": "no_remote_row", "ok": False, "local_keys": sorted(local.keys())}
        return _emit(report, cadence, starved, args, starved_tasks=starved_tasks)

    drift = _diff(local, remote)
    if not drift:
        report = {"status": "ok", "ok": True, "checked_fields": list(_AUDIT_FIELDS)}
        return _emit(report, cadence, starved, args, starved_tasks=starved_tasks)

    report = {
        "status": "drift",
        "ok": False,
        "drift_count": len(drift),
        "drift": drift,
    }

    if args.fix:
        ok = _push_fix(local)
        report["fix_attempted"] = True
        report["fix_ok"] = ok
        if ok:
            # Re-verify after patch
            remote_after = _load_remote() or {}
            remaining = _diff(local, remote_after)
            report["drift_after_fix"] = len(remaining)
            report["status"] = "fixed" if not remaining else "drift_after_fix"

    if not args.json:
        print(f"[audit] DRIFT detected: {len(drift)} field(s)")
        for entry in drift:
            print(f"  - {entry['field']}: local={entry['local']!r} remote={entry['remote']!r}")
        if args.fix:
            print(f"[audit] fix_attempted={report.get('fix_attempted')} fix_ok={report.get('fix_ok')}")
    return _emit(report, cadence, starved, args, starved_tasks=starved_tasks)


def _emit(
    report: dict,
    cadence: dict,
    starved: list[dict],
    args,
    *,
    starved_tasks: list[dict] | None = None,
) -> int:
    """Print the report and decide the exit code.

    Field drift stays exit 0 (it has always been observability, and a --fix run
    repairs it). A cadence that cannot reach the configured interval, or drafts
    the loop has skipped more than five times, are different: they fail — and
    since WS-I (2026-07-20) a --fix run also queues one idempotent repair task
    per starved draft, so the failing exit code has an exit path instead of
    being a verdict nobody consumes.
    """
    report["cadence"] = cadence
    report["starved_drafts"] = starved
    report["starved_draft_tasks"] = starved_tasks or []
    blocking = (not cadence.get("ok", True)) or bool(starved)
    if blocking:
        report["ok"] = False
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        if report.get("status") == "ok":
            print("[audit] release_settings local↔Supabase aligned")
        elif report.get("status") == "no_remote_row":
            print("[audit] supabase content_release_settings.id=default missing")
        if not cadence.get("ok", True):
            print(f"[audit] CADENCE FAIL: {cadence.get('detail')}")
            for note in cadence.get("trigger_notes") or []:
                print(f"  - {note}")
        elif cadence.get("status") == "aligned":
            print(f"[audit] cadence ok (max gap "
                  f"{cadence['launchagent_max_gap_minutes']}min <= "
                  f"interval {cadence['interval_minutes']}min)")
        if starved:
            print(f"[audit] STARVED DRAFTS: {len(starved)} skipped >"
                  f"{_STARVED_SKIP_THRESHOLD} times")
            for d in starved:
                print(f"  - {d['id']} skipped={d['skipped']} {d['title']}")
        for t in starved_tasks or []:
            mark = "opened" if t.get("created") else ("ERROR" if t.get("error") else "already queued")
            print(f"[audit] repair task {t.get('task_id')}: {mark}"
                  + (f" ({t['error']})" if t.get("error") else ""))
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
