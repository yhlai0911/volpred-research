#!/usr/bin/env python3
"""Standing audit: compare local feed.json published vs Supabase vs live URL.

Cron: hourly. Alerts if mismatch detected.

Surfaces:
- A: local published but NOT in supabase (sync failed)
- B: local published, IN supabase, but live URL not 200 (cache / route issue)
- C: in supabase but no local entry (orphan)

Every run atomically publishes a typed convergence receipt.  Transport or
credential failures are ``unavailable`` observations, never an empty remote
projection and therefore never false drift evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Callable
from urllib import request, error
from urllib.parse import quote
from uuid import uuid4

REPO = Path(__file__).parent.parent
FEED = REPO / "storage" / "reports" / "feed.json"
RECEIPT = REPO / "storage" / "ops" / "publisher_projection_convergence_latest.json"
LIVE_URL_TEMPLATE = "https://volpred.zeabur.app/v3/reports/{mile_id}"
SUPA_REST_TEMPLATE = "{base}/rest/v1/articles?select=slug,status&slug=in.({ids})"
WINDOW_HOURS = 72  # only audit articles published in last N hours
RECEIPT_SCHEMA = "publisher-projection-convergence.v1"


class RemoteObservationUnavailable(RuntimeError):
    """A remote surface could not be observed, so convergence is unknown."""


def _warn_publish_sync(message, *, exc=None, **context):
    parts = [f"{key}={value}" for key, value in context.items() if value is not None]
    if exc is not None:
        parts.append(f"error={type(exc).__name__}: {exc}")
    suffix = f" {' '.join(parts)}" if parts else ""
    print(f"[publish-sync-audit] WARN {message}{suffix}", file=sys.stderr)


def load_env():
    env = {}
    for fname in (".env.local", ".env"):
        p = REPO / fname
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def http_status(url, timeout=10):
    try:
        req = request.Request(url, method="GET")
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except error.HTTPError as e:
        return e.code
    except Exception as e:
        _warn_publish_sync("live URL check failed", url=url, exc=e)
        raise RemoteObservationUnavailable(
            "live_url_observation_unavailable"
        ) from e


def fetch_supabase_slugs(env, mile_ids):
    base = env.get("SUPABASE_URL") or env.get("NEXT_PUBLIC_SUPABASE_URL")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_KEY")
    if not mile_ids:
        return set()
    if not (base and key):
        raise RemoteObservationUnavailable(
            "supabase_credentials_unavailable"
        )
    ids_csv = ",".join(mile_ids)
    url = SUPA_REST_TEMPLATE.format(base=base.rstrip("/"), ids=quote(ids_csv, safe=","))
    req = request.Request(url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
    try:
        with request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return {r["slug"] for r in data if r.get("status") == "published"}
    except Exception as e:
        _warn_publish_sync(
            "supabase slug fetch failed",
            article_count=len(mile_ids),
            exc=e,
        )
        raise RemoteObservationUnavailable(
            "supabase_observation_unavailable"
        ) from e


def _atomic_write_receipt(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    try:
        temporary.write_text(payload, encoding="utf-8")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved != report:
            raise RuntimeError(
                "publisher convergence receipt failed exact read-back"
            )
    finally:
        temporary.unlink(missing_ok=True)


def run_audit(
    *,
    feed_path: Path = FEED,
    receipt_path: Path = RECEIPT,
    now: float | None = None,
    env: dict[str, str] | None = None,
    supabase_fetch: Callable[[dict[str, str], list[str]], set[str]] = (
        fetch_supabase_slugs
    ),
    live_status: Callable[[str], int] = http_status,
) -> tuple[dict, int]:
    """Observe the publisher projection and persist one typed receipt."""

    feed_bytes = feed_path.read_bytes()
    feed = json.loads(feed_bytes)
    if isinstance(feed, dict):
        feed = feed.get("items", [])
    if not isinstance(feed, list):
        raise ValueError("canonical feed must be a list or contain an items list")

    now = time.time() if now is None else now
    cutoff_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - WINDOW_HOURS * 3600))

    # Local published in window
    local_pub = []
    for item in feed:
        if not isinstance(item, dict):
            continue
        if item.get("status") != "published":
            continue
        pub_at = item.get("published_at", "")
        if pub_at < cutoff_iso:
            continue
        mile_id = item.get("id") or item.get("slug")
        if not mile_id:
            continue
        local_pub.append(mile_id)
    local_set = set(local_pub)

    observation_errors: list[dict[str, str]] = []
    supa_set: set[str] = set()
    supabase_available = True
    try:
        supa_set = supabase_fetch(
            load_env() if env is None else env,
            sorted(local_set),
        )
    except RemoteObservationUnavailable as exc:
        supabase_available = False
        observation_errors.append(
            {
                "surface": "supabase",
                "reason": str(exc),
            }
        )

    # A: local pub not in supabase
    missing_supa = (
        sorted(local_set - supa_set)
        if supabase_available
        else []
    )

    # B: in supabase but live URL not 200
    live_check = (
        sorted(local_set & supa_set)
        if supabase_available
        else []
    )
    live_404 = []
    for mid in live_check:
        try:
            s = live_status(LIVE_URL_TEMPLATE.format(mile_id=mid))
        except RemoteObservationUnavailable as exc:
            observation_errors.append(
                {
                    "surface": "live_url",
                    "subject": mid,
                    "reason": str(exc),
                }
            )
            continue  # silent-ok: typed unavailable evidence is persisted and exits 2
        if s != 200:
            live_404.append({"mile_id": mid, "status_code": s})

    mismatches = len(missing_supa) + len(live_404)
    if observation_errors:
        convergence_status = "unavailable"
        exit_code = 2
    elif mismatches:
        convergence_status = "drifted"
        exit_code = 1
    else:
        convergence_status = "converged"
        exit_code = 0
    report = {
        "schema_version": RECEIPT_SCHEMA,
        "audit": "publish_sync",
        "convergence_status": convergence_status,
        "window_hours": WINDOW_HOURS,
        "feed_sha256": hashlib.sha256(feed_bytes).hexdigest(),
        "local_published_count": len(local_set),
        "supabase_synced_count": len(supa_set),
        "missing_supabase": missing_supa,
        "live_404": live_404,
        "observation_errors": observation_errors,
        "mismatch_total": mismatches,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
    }
    _atomic_write_receipt(receipt_path, report)
    return report, exit_code


def main():
    report, exit_code = run_audit()
    print(json.dumps(report, ensure_ascii=False, indent=2))

    # Alert if >=3 mismatches (avoid noise on 1-off transient)
    mismatches = report["mismatch_total"]
    missing_supa = report["missing_supabase"]
    live_404 = report["live_404"]
    if mismatches >= 3:
        body = (
            "## 觸發條件\n"
            f"publish-sync audit 過去 {WINDOW_HOURS}h 發現 {mismatches} 篇 mismatch (missing_supabase={len(missing_supa)} live_404={len(live_404)})\n"
            f"- missing_supabase: {', '.join(missing_supa) or '無'}\n"
            f"- live_404: {', '.join(x['mile_id'] for x in live_404) or '無'}\n\n"
            "## 影響\n"
            "讀者點擊 FB / 外部分享連結會 404；Mission 1 (文章) + 5 (曝光) 漏接\n\n"
            "## 建議行動\n"
            "1. uv run python scripts/supabase_sync.py full\n"
            "2. 5 min 後重跑 audit；仍 missing → 查 supabase_sync.py log\n"
            "3. 404 但 supabase OK → 查 frontend route + Zeabur cache"
        )
        try:
            from src.volpred.ops.alerts import send_alert
            send_alert(level="warn", title=f"Publish sync mismatch: {mismatches} articles", body=body)
        except Exception as e:
            print(f"alert send failed: {e}", file=sys.stderr)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
