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
from urllib.parse import urlencode
from uuid import uuid4

from volpred.ops.public_article_projection_contract import (
    PublicArticleProjectionContractError,
    audit_frontend_public_article_projection_contract,
    public_projection_contract_evidence_matches,
)

REPO = Path(__file__).parent.parent
FEED = REPO / "storage" / "reports" / "feed.json"
RECEIPT = REPO / "storage" / "ops" / "publisher_projection_convergence_latest.json"
LIVE_URL_TEMPLATE = "https://volpred.zeabur.app/v3/reports/{mile_id}"
WINDOW_HOURS = 72  # only audit articles published in last N hours
SUPABASE_PAGE_SIZE = 1000
RECEIPT_SCHEMA = "publisher-projection-convergence.v2"


class RemoteObservationUnavailable(RuntimeError):
    """A remote surface could not be observed, so convergence is unknown."""


def audit_projection_contract() -> dict:
    return audit_frontend_public_article_projection_contract(
        REPO / "frontend-v2-fix" / "src" / "lib" / "data-server.ts"
    )


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


def fetch_supabase_slugs(env, cutoff_iso):
    base = env.get("SUPABASE_URL") or env.get("NEXT_PUBLIC_SUPABASE_URL")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_KEY")
    if not (base and key):
        raise RemoteObservationUnavailable(
            "supabase_credentials_unavailable"
        )
    query = urlencode(
        {
            "select": "slug,status,published_at",
            "status": "eq.published",
            "published_at": f"gte.{cutoff_iso}",
            "order": "slug.asc",
        },
        safe=",:.-TZ",
    )
    url = f"{base.rstrip('/')}/rest/v1/articles?{query}"
    try:
        slugs = set()
        offset = 0
        while True:
            req = request.Request(
                url,
                headers={
                    "apikey": key,
                    "Authorization": f"Bearer {key}",
                    "Prefer": "count=exact",
                    "Range-Unit": "items",
                    "Range": (
                        f"{offset}-{offset + SUPABASE_PAGE_SIZE - 1}"
                    ),
                },
            )
            with request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                if not isinstance(data, list):
                    raise ValueError(
                        "Supabase articles response must be a list"
                    )
                slugs.update(
                    r["slug"]
                    for r in data
                    if r.get("status") == "published"
                )
                content_range = getattr(
                    getattr(resp, "headers", None),
                    "get",
                    lambda key: None,
                )("Content-Range")

            offset += len(data)
            if not data:
                break
            if content_range:
                total_text = content_range.rsplit("/", 1)[-1]
                if total_text != "*" and offset >= int(total_text):
                    break
            elif len(data) < SUPABASE_PAGE_SIZE:
                break
        return slugs
    except Exception as e:
        _warn_publish_sync(
            "supabase slug fetch failed",
            window_start=cutoff_iso,
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
    projection_contract_audit: Callable[[], dict] = (
        audit_projection_contract
    ),
) -> tuple[dict, int]:
    """Observe the publisher projection and persist one typed receipt."""

    feed_bytes = feed_path.read_bytes()
    feed = json.loads(feed_bytes)
    if isinstance(feed, dict):
        feed = feed.get("items", [])
    if not isinstance(feed, list):
        raise ValueError("canonical feed must be a list or contain an items list")

    now = time.time() if now is None else now
    cutoff_iso = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(now - WINDOW_HOURS * 3600),
    )

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
    projection_contract_evidence: dict | None = None
    try:
        projection_contract_evidence = projection_contract_audit()
        if not public_projection_contract_evidence_matches(
            projection_contract_evidence
        ):
            raise PublicArticleProjectionContractError(
                "public projection contract evidence is invalid"
            )
    except PublicArticleProjectionContractError as exc:
        projection_contract_evidence = None
        observation_errors.append(
            {
                "surface": "public_projection_contract",
                "reason": str(exc),
            }
        )
    supa_set: set[str] = set()
    supabase_available = True
    try:
        supa_set = supabase_fetch(
            load_env() if env is None else env,
            cutoff_iso,
        )
    except RemoteObservationUnavailable as exc:
        supabase_available = False
        observation_errors.append(
            {
                "surface": "supabase",
                "reason": str(exc),
            }
        )

    # A: local pub not in Supabase
    missing_supa = (
        sorted(local_set - supa_set)
        if supabase_available
        else []
    )
    orphan_supa = (
        sorted(supa_set - local_set)
        if supabase_available
        else []
    )

    # B: in Supabase but live URL not 200
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

    # C: published in Supabase's same window but absent from canonical feed
    mismatches = len(missing_supa) + len(orphan_supa) + len(live_404)
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
        "window_start": cutoff_iso,
        "feed_sha256": hashlib.sha256(feed_bytes).hexdigest(),
        "local_published_count": len(local_set),
        "supabase_published_count": len(supa_set),
        "missing_supabase": missing_supa,
        "orphan_supabase": orphan_supa,
        "live_404": live_404,
        "observation_errors": observation_errors,
        "public_projection_contract": projection_contract_evidence,
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
    orphan_supa = report["orphan_supabase"]
    live_404 = report["live_404"]
    if mismatches >= 3:
        body = (
            "## 觸發條件\n"
            f"publish-sync audit 過去 {WINDOW_HOURS}h 發現 {mismatches} 篇 mismatch "
            f"(missing_supabase={len(missing_supa)} "
            f"orphan_supabase={len(orphan_supa)} live_404={len(live_404)})\n"
            f"- missing_supabase: {', '.join(missing_supa) or '無'}\n"
            f"- orphan_supabase: {', '.join(orphan_supa) or '無'}\n"
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
