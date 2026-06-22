"""Audit local .release_settings.json vs Supabase content_release_settings (id=default).

Detects drift between the two sources caused by silent PATCH failures
(`_update_content_release_settings` returns False on Supabase 4xx/5xx but does
not raise). Local-first design means subsequent reads succeed, but Supabase row
goes stale → admin UI / cross-session readers see wrong release cadence.

Run modes:
- default: compare, print drift report, exit 0 even on drift (observability)
- --fix:  push local payload to Supabase to repair drift (idempotent PATCH)
- --json: emit structured JSON to stdout for log scrapers / downstream alerts

Drift fields checked: mode, interval_minutes, max_articles_per_run, due_only,
include_drafts, preferred_audiences, last_released_at.

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

    remote = _load_remote()
    if remote is None:
        report = {"status": "no_remote_row", "ok": False, "local_keys": sorted(local.keys())}
        print(json.dumps(report) if args.json else "[audit] supabase content_release_settings.id=default missing")
        return 0

    drift = _diff(local, remote)
    if not drift:
        report = {"status": "ok", "ok": True, "checked_fields": list(_AUDIT_FIELDS)}
        print(json.dumps(report) if args.json else "[audit] release_settings local↔Supabase aligned")
        return 0

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

    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(f"[audit] DRIFT detected: {len(drift)} field(s)")
        for entry in drift:
            print(f"  - {entry['field']}: local={entry['local']!r} remote={entry['remote']!r}")
        if args.fix:
            print(f"[audit] fix_attempted={report.get('fix_attempted')} fix_ok={report.get('fix_ok')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
