from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from volpred.config import load_runtime_schedules
from volpred.publisher.email_notifier import EmailNotifier

from .common import dump_json, load_json, project_path
from .scheduler import get_scheduler_state

ALERT_RECIPIENT = "yihao.lai@gmail.com"
ALERT_LEVELS = ("info", "warn", "critical")
ALERT_DEDUP_WINDOW = timedelta(hours=24)
SCHEDULER_STALE_WINDOW = timedelta(minutes=30)
RELEASE_POOL_GAP_BUFFER = timedelta(minutes=60)  # grace on top of configured interval
# 2026-05-17 bump 30→60min: piggy-back release fires only on check_alerts
# hourly cron tick (`0 * * * *`). With 180min interval + 30min buffer = 210min
# threshold, normal cycle could routinely hit 210-240min (release at HH:XX,
# age reaches interval-5 at HH+2:55, next hourly tick at HH'+:00 → gap up to
# interval+59min). Three consecutive same-pattern alerts (23:55/03:59/07:58
# CST 2026-05-16/17) triggered warn just BEFORE next auto-piggy fire.
# Buffer must be ≥ check_alerts cadence (60min) to absorb the fence-post.

_TAIPEI_TZ = ZoneInfo("Asia/Taipei")
_RELEASE_POOL_FIRE_RE = re.compile(
    r"^=== \[release[-_]pool\] (?:fire|piggy-back fire|check_alerts fallback fire) at (.+) ===$"
)
# Matches the canonical cron-wrapper end banner:
#   === [<job>] exit <N> at <timestamp> (duration=<X>s) ===
# The old pattern `^=== exit (\d+) at (.+) ===$` matched NOTHING — every
# wrapper emits the `[<job>]`-prefixed form — so host_cron_fail was silently
# dead and 2026-05-20's 8/12 hourly-dispatch failures never alerted. The
# `(duration=...)` suffix is optional. group(1)=exit code, group(2)=timestamp.
_CRON_EXIT_RE = re.compile(
    r"^=== \[[^\]]+\] exit (\d+) at (.+?)(?: \(duration=[^)]*\))? ===$"
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_datetime(raw: str | None) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_shell_timestamp(raw: str | None) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None

    trimmed = raw.strip()
    iso_candidate = _parse_iso_datetime(trimmed)
    if iso_candidate is not None:
        return iso_candidate

    normalized = re.sub(r"\s+[A-Z]{2,5}\s+", " ", trimmed, count=1)
    try:
        parsed = datetime.strptime(normalized, "%a %b %d %H:%M:%S %Y")
    except ValueError:
        return None
    return parsed.replace(tzinfo=_TAIPEI_TZ).astimezone(timezone.utc)


def _storage_root(storage_dir: str = "storage") -> Path:
    return project_path(storage_dir)


def _ops_path(storage_dir: str = "storage", *parts: str) -> Path:
    return _storage_root(storage_dir).joinpath("ops", *parts)


def _cron_logs_dir(storage_dir: str = "storage") -> Path:
    return _storage_root(storage_dir).joinpath("logs", "cron")


def _alert_dedup_path(storage_dir: str = "storage") -> Path:
    return _ops_path(storage_dir, "alert_dedup.json")


def _release_pool_preview_for_alert(storage_dir: str) -> dict[str, Any]:
    try:
        from .content import preview_release_pool_by_settings

        preview = preview_release_pool_by_settings(storage_dir=storage_dir)
    except Exception as exc:
        return {"preview_error": f"{type(exc).__name__}: {str(exc)[:200]}"}

    pool_counts = preview.get("pool_counts") if isinstance(preview, dict) else None
    next_candidates = preview.get("next_candidates") if isinstance(preview, dict) else None
    return {
        "pool_counts": pool_counts if isinstance(pool_counts, dict) else {},
        "next_candidates": next_candidates if isinstance(next_candidates, list) else [],
    }


def _notification_path(storage_dir: str, notification_id: str) -> Path:
    return _storage_root(storage_dir).joinpath("notifications", f"{notification_id}.json")


def _relative_repo_path(path: Path) -> str:
    try:
        return str(path.relative_to(project_path()))
    except ValueError:
        return str(path)


def _alert_key(level: str, title: str) -> str:
    payload = f"{level.strip().lower()}\0{title.strip()}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_alert_dedup(storage_dir: str = "storage") -> dict[str, Any]:
    path = _alert_dedup_path(storage_dir)
    data = load_json(path, {"updated_at": None, "alerts": {}})
    alerts = data.get("alerts")
    if not isinstance(alerts, dict):
        alerts = {}
    return {
        "updated_at": data.get("updated_at"),
        "alerts": alerts,
    }


def _save_alert_dedup(storage_dir: str, payload: dict[str, Any]) -> None:
    payload["updated_at"] = _utc_now().isoformat()
    dump_json(_alert_dedup_path(storage_dir), payload)


def _dispatch_alert_email(
    *,
    level: str,
    title: str,
    body: str,
    recipient: str,
    storage_dir: str,
) -> dict[str, Any]:
    notifier = EmailNotifier(storage_dir=storage_dir)
    subject = f"[VolPred Alert][{level.upper()}] {title}"
    text_body = "\n".join(
        [
            f"Alert level: {level}",
            f"Title: {title}",
            "",
            body.strip(),
        ]
    ).strip()

    # Build HTML body via markdown→HTML + _email_shell wrapper (per user
    # 2026-05-25 directive: 所有 Claude 寄出的信都用 HTML 高資訊性編排)
    try:
        from volpred.publisher.email_notifier import _email_shell, _try_markdown_to_html
        inner_html = _try_markdown_to_html(body.strip())
        level_color = {"info": "#2563eb", "warn": "#d97706", "critical": "#dc2626"}.get(level, "#6b7280")
        # Level badge + body content
        body_html = (
            f'<div style="display:inline-block;padding:4px 12px;border-radius:6px;'
            f'background:{level_color};color:#fff;font-size:12px;font-weight:600;'
            f'letter-spacing:1px;margin-bottom:12px;">{level.upper()}</div>'
            f'<div style="color:#1f2937;font-size:14px;line-height:1.65;">'
            f'{inner_html}'
            f'</div>'
        )
        subtitle = f"Alert level: {level}"
        html_body = _email_shell(title, subtitle, body_html)
    except Exception:
        html_body = None  # fallback to plain text only

    notification_id = notifier.notify(
        subject=subject,
        body=text_body,
        html_body=html_body,
        level=level,
        metadata={
            "notification_type": "ops_alert",
            "alert_level": level,
            "alert_title": title,
            "recipient": recipient,
        },
        recipients=[recipient],
    )
    notification = load_json(
        _notification_path(storage_dir, notification_id),
        {
            "id": notification_id,
            "sent": False,
            "configured": False,
            "send_error": None,
        },
    )
    return {
        "notification_id": notification_id,
        "subject": subject,
        "sent": bool(notification.get("sent")),
        "configured": bool(notification.get("configured")),
        "send_error": notification.get("send_error"),
    }


def send_alert(
    level: str,
    title: str,
    body: str,
    recipient: str = ALERT_RECIPIENT,
    *,
    storage_dir: str = "storage",
    force_send: bool = False,
) -> dict[str, Any]:
    normalized_level = level.strip().lower()
    normalized_title = title.strip()
    normalized_recipient = recipient.strip() or ALERT_RECIPIENT
    if normalized_level not in ALERT_LEVELS:
        raise ValueError(f"Unsupported alert level: {level}")
    if not normalized_title:
        raise ValueError("Alert title must not be empty")

    now = _utc_now()
    dedup_key = _alert_key(normalized_level, normalized_title)
    dedup_state = _load_alert_dedup(storage_dir)
    existing = dedup_state["alerts"].get(dedup_key) or {}
    last_sent_at = _parse_iso_datetime(existing.get("last_sent_at"))

    if (
        not force_send
        and last_sent_at is not None
        and now - last_sent_at < ALERT_DEDUP_WINDOW
    ):
        existing["last_skipped_at"] = now.isoformat()
        existing["skip_count"] = int(existing.get("skip_count", 0) or 0) + 1
        dedup_state["alerts"][dedup_key] = existing
        _save_alert_dedup(storage_dir, dedup_state)
        return {
            "level": normalized_level,
            "title": normalized_title,
            "recipient": normalized_recipient,
            "alert_key": dedup_key,
            "sent": False,
            "skipped": True,
            "skip_reason": "dedup_24h",
            "notification_id": existing.get("last_notification_id"),
            "dedup_path": str(_alert_dedup_path(storage_dir)),
            "last_sent_at": existing.get("last_sent_at"),
        }

    delivery = _dispatch_alert_email(
        level=normalized_level,
        title=normalized_title,
        body=body,
        recipient=normalized_recipient,
        storage_dir=storage_dir,
    )
    result = {
        "level": normalized_level,
        "title": normalized_title,
        "recipient": normalized_recipient,
        "alert_key": dedup_key,
        "sent": delivery["sent"],
        "skipped": False,
        "notification_id": delivery["notification_id"],
        "subject": delivery["subject"],
        "configured": delivery["configured"],
        "send_error": delivery.get("send_error"),
        "dedup_path": str(_alert_dedup_path(storage_dir)),
        "timestamp": now.isoformat(),
    }
    if delivery["sent"]:
        dedup_state["alerts"][dedup_key] = {
            "level": normalized_level,
            "title": normalized_title,
            "recipient": normalized_recipient,
            "first_sent_at": existing.get("first_sent_at") or now.isoformat(),
            "last_sent_at": now.isoformat(),
            "last_notification_id": delivery["notification_id"],
            "send_count": int(existing.get("send_count", 0) or 0) + 1,
            "last_skipped_at": existing.get("last_skipped_at"),
            "skip_count": int(existing.get("skip_count", 0) or 0),
        }
        _save_alert_dedup(storage_dir, dedup_state)
    return result


def _parse_release_pool_state(storage_dir: str, now: datetime) -> dict[str, Any]:
    log_path = _cron_logs_dir(storage_dir).joinpath("release_pool.log")
    last_fire_at = None
    if log_path.exists():
        try:
            for raw_line in log_path.read_text(encoding="utf-8").splitlines():
                match = _RELEASE_POOL_FIRE_RE.match(raw_line.strip())
                if match:
                    last_fire_at = _parse_shell_timestamp(match.group(1))
        except OSError:
            last_fire_at = None

    # Piggy-back release path (check_alerts.py `_auto_trigger_release_pool_if_due`)
    # writes .release_settings.json.last_released_at but not release_pool.log.
    # Fall back to settings-recorded timestamp so piggy-back releases are visible
    # to the alert condition and don't false-positive release_pool_gap.
    settings_path = project_path(storage_dir, ".release_settings.json")
    settings_data = load_json(settings_path, {})
    settings_last = _parse_iso_datetime(settings_data.get("last_released_at")) if isinstance(settings_data, dict) else None
    if settings_last is not None and (last_fire_at is None or settings_last > last_fire_at):
        last_fire_at = settings_last

    # 2026-06-19: separate "did the release machinery run" from "did an article
    # get released". release-pool-by-settings rewrites `.release_settings.json`
    # `updated_at` on EVERY run — even when the dedup gate correctly skips all
    # due drafts (theme-saturated pool) and 0 articles are released. The legacy
    # gap check keyed only on `last_released_at` (success-only) + an ancient log
    # fire marker, so it false-positived CRITICAL whenever (a) the draft pool was
    # theme-saturated and the cron was healthily releasing nothing, or (b) a
    # targeted `release-pool --pub-id` release happened (does not touch settings).
    # Decompose: machinery-staleness = genuine cron outage (critical); cron
    # healthy but nothing released for >2x interval = release starvation (warn,
    # a content problem routed to fresh-theme drafts, NOT a cron outage).
    settings_updated = (
        _parse_iso_datetime(settings_data.get("updated_at")) if isinstance(settings_data, dict) else None
    )
    machinery_last = last_fire_at  # log fire marker ∪ last_released fallback
    if settings_updated is not None and (machinery_last is None or settings_updated > machinery_last):
        machinery_last = settings_updated
    release_last = settings_last  # last actual successful release

    machinery_gap_hours = (
        round((now - machinery_last).total_seconds() / 3600.0, 2) if machinery_last is not None else None
    )
    release_gap_hours = (
        round((now - release_last).total_seconds() / 3600.0, 2) if release_last is not None else None
    )

    # 2026-04-20: threshold derives from configured release interval + buffer
    # (was hardcoded 2h, which false-positived every fire after user changed
    # cadence 2h→12h). Alert fires only when gap exceeds the cadence the user
    # actually chose. Critical tier = 2x interval (genuine silent outage).
    interval_minutes = 120  # default fallback
    if isinstance(settings_data, dict):
        try:
            interval_minutes = int(settings_data.get("interval_minutes") or 120)
        except (TypeError, ValueError):
            interval_minutes = 120
    interval_td = timedelta(minutes=max(5, interval_minutes))
    warn_threshold = interval_td + RELEASE_POOL_GAP_BUFFER
    critical_threshold = interval_td * 2
    threshold_hours = round(warn_threshold.total_seconds() / 3600.0, 2)
    critical_hours = round(critical_threshold.total_seconds() / 3600.0, 1)

    base_details = {
        "machinery_last_at": machinery_last.isoformat() if machinery_last else None,
        "machinery_gap_hours": machinery_gap_hours,
        "last_released_at": release_last.isoformat() if release_last else None,
        "release_gap_hours": release_gap_hours,
        "interval_minutes": interval_minutes,
        "warn_threshold_hours": threshold_hours,
        "log_path": _relative_repo_path(log_path),
    }

    # 1) Genuine cron outage: the release machinery itself stopped firing.
    machinery_stale = machinery_last is None or (now - machinery_last) > warn_threshold
    if machinery_stale:
        level = "critical" if machinery_last is None or (now - machinery_last) > critical_threshold else "warn"
        title = f"Release pool cron gap > {threshold_hours}h (interval={interval_minutes}min)"
        machinery_text = machinery_last.isoformat() if machinery_last else "missing"
        body = "\n".join(
            [
                "## 觸發條件",
                f"release_pool 機器 fire gap 已超過 {threshold_hours} 小時門檻 (interval={interval_minutes}min + 60min grace)。",
                f"- machinery_last_at (updated_at ∪ log fire): {machinery_text}",
                f"- machinery_gap_hours: {machinery_gap_hours if machinery_gap_hours is not None else 'missing'}",
                f"- configured_interval_minutes: {interval_minutes}",
                f"- log_path: {_relative_repo_path(log_path)}",
                "",
                "## 影響",
                "釋出機器停擺（cron 未 fire）= 文章完全不釋出、讀者端平台停滯、搜尋索引停滯；",
                f"Mission 第 1 條（內容）與第 5 條（流量）直接受損。若持續 >{critical_hours}h 會累積多篇 draft 排隊延遲。",
                "",
                "## 建議行動",
                "1. 立即手動釋出（最快復原）：",
                "   VOLPRED_ACTOR=claude uv run volpred ops release-pool-by-settings",
                "2. 診斷 host cron 是否仍在跑：",
                f"   tail -20 {_relative_repo_path(log_path)}",
                "   crontab -l | grep release_pool",
                "3. 若 cron daemon 卡住：重新 install crontab 或 launchd job",
            ]
        )
        return {
            "id": "release_pool_gap",
            "breached": True,
            "level": level,
            "title": title,
            "body": body,
            "details": base_details,
        }

    # 2) Machinery healthy but nothing released for >2x interval → release
    #    starvation. Draft pool is theme-saturated (dedup correctly skipping) or
    #    due-order keeps surfacing saturated themes without falling through to
    #    fresh-theme drafts. Content problem (Mission #1/#5), surfaced as WARN.
    release_starved = release_last is None or (now - release_last) > critical_threshold
    if release_starved:
        title = f"Release pool starved > {critical_hours}h (cron healthy)"
        release_text = release_last.isoformat() if release_last else "missing"
        preview_summary = _release_pool_preview_for_alert(storage_dir)
        pool_counts = preview_summary.get("pool_counts", {})
        preview_error = preview_summary.get("preview_error")
        if pool_counts:
            preview_lines = [
                f"- draft: {pool_counts.get('draft', 'unknown')}",
                f"- scheduled: {pool_counts.get('scheduled', 'unknown')}",
                f"- eligible_before_dedup: {pool_counts.get('eligible_before_dedup', 'unknown')}",
                f"- dedup_flagged: {pool_counts.get('dedup_flagged', 'unknown')}",
                f"- eligible_after_dedup: {pool_counts.get('eligible', 'unknown')}",
            ]
        elif preview_error:
            preview_lines = [f"- preview_error: {preview_error}"]
        else:
            preview_lines = ["- preview unavailable"]
        body = "\n".join(
            [
                "## 觸發條件",
                f"釋出機器 cron 正常 fire（machinery_gap={machinery_gap_hours}h），但已超過 {critical_hours}h 沒有任何文章成功釋出。",
                f"- last_released_at: {release_text}",
                f"- release_gap_hours: {release_gap_hours if release_gap_hours is not None else 'missing'}",
                f"- machinery_last_at: {machinery_last.isoformat() if machinery_last else 'missing'}",
                "",
                "## release preview",
                *preview_lines,
                "",
                "## 影響",
                "通常是 due 草稿全落在已飽和主題、dedup 正確 skip 但釋出算法未 fall-through 到 fresh-theme 草稿；",
                "讀者端看不到新內容（Mission 第 1/5 條），但這不是 cron 停擺，是內容釋出層問題。",
                "",
                "## 建議行動",
                "1. 若 eligible_after_dedup=0：不要強行釋出已被 dedup TTL 排除的草稿，先補 fresh-theme draft 或等 TTL 到期。",
                "2. 若還有 eligible_after_dedup>0：定向釋出一篇 fresh-theme 草稿（避開 model_complexity / vt_strategy / spy / vix / garch）：",
                "   jq '[.[]|select(.status==\"draft\")]|.[].title' storage/reports/feed.json 挑非飽和主題",
                "   VOLPRED_ACTOR=claude uv run volpred ops release-pool --pub-id <id> --include-drafts",
                "3. 若 draft 池主題全飽和：派 daily_article 補 fresh-theme 草稿（publication-candidates skill）。",
            ]
        )
        return {
            "id": "release_pool_gap",
            "breached": True,
            "level": "warn",
            "title": title,
            "body": body,
            "details": {**base_details, "release_preview": preview_summary},
        }

    # 3) Healthy: machinery firing + content released within cadence.
    return {
        "id": "release_pool_gap",
        "breached": False,
        "level": "info",
        "title": f"Release pool cron gap > {threshold_hours}h (interval={interval_minutes}min)",
        "body": "",
        "details": base_details,
    }


def _parse_draft_pool_state(storage_dir: str) -> dict[str, Any]:
    feed_path = _storage_root(storage_dir).joinpath("reports", "feed.json")
    feed = load_json(feed_path, [])
    if not isinstance(feed, list):
        feed = []
    draft_count = sum(1 for item in feed if isinstance(item, dict) and item.get("status") == "draft")
    scheduled_count = sum(1 for item in feed if isinstance(item, dict) and item.get("status") == "scheduled")
    eligible_count = draft_count + scheduled_count
    breached = draft_count < 4
    level = "critical" if draft_count == 0 else "warn"
    body = "\n".join(
        [
            "## 觸發條件",
            "Draft 池已低於最小門檻（<4 篇）。",
            f"- draft_count: {draft_count}",
            f"- scheduled_count: {scheduled_count}",
            f"- eligible_count: {eligible_count}",
            f"- feed_path: {_relative_repo_path(feed_path)}",
            "",
            "## 影響",
            "release_pool cron 即使正常 fire 也沒 content 可釋 → 發文節奏中斷。",
            "draft_count=0 時下一次 release tick 會空轉，讀者看到平台無新內容；",
            "Mission 第 1 條（內容產出）+ 第 5 條（流量）連動受損。",
            "",
            "## 建議行動",
            "1. 跑選題 SOP（雙軌來源：研究驅動 + 事件驅動）：",
            "   see .claude/skills/publication-candidates/SKILL.md 5-step flow",
            "2. 快速選題（看未覆蓋的 K 編號）：",
            "   grep '| - | - |' experiments/INDEX.md | head -10",
            "3. 看 novelty 候選（20% contrarian quota）：",
            "   head -60 docs/topic_diversity_audit.md",
            "4. 派 general-purpose agent 寫 2-3 篇 draft（主題軸各異）：",
            "   每篇 2000+ 字研究文 / 1500+ 字 general、2 張真實圖表、標數據來源 + K 編號。",
            "5. 走正式入口 feed-publisher SKILL，不要繞路寫 feed.json。",
        ]
    )
    return {
        "id": "draft_pool_low",
        "breached": breached,
        "level": level if breached else "info",
        "title": "Draft pool below threshold (<4)",
        "body": body if breached else "",
        "details": {
            "draft_count": draft_count,
            "scheduled_count": scheduled_count,
            "eligible_count": eligible_count,
            "feed_path": _relative_repo_path(feed_path),
        },
    }


def _latest_cron_exit(log_path: Path) -> dict[str, Any] | None:
    if not log_path.exists():
        return None
    last_exit: dict[str, Any] | None = None
    try:
        for raw_line in log_path.read_text(encoding="utf-8").splitlines():
            match = _CRON_EXIT_RE.match(raw_line.strip())
            if not match:
                continue
            last_exit = {
                "log_path": _relative_repo_path(log_path),
                "exit_code": int(match.group(1)),
                "exited_at": _parse_shell_timestamp(match.group(2)),
            }
    except OSError:
        return None
    if last_exit and isinstance(last_exit.get("exited_at"), datetime):
        last_exit["exited_at"] = last_exit["exited_at"].isoformat()
    return last_exit


def _trailing_authoritative_exit_codes(log_path: Path, n: int = 6) -> list[int]:
    """Last n authoritative `=== ... exit N at ... ===` exit codes (oldest→newest).

    Used to distinguish a single self-recovering hang from a sustained outage.
    """
    if not log_path.exists():
        return []
    codes: list[int] = []
    try:
        for raw_line in log_path.read_text(encoding="utf-8").splitlines():
            m = _CRON_EXIT_RE.match(raw_line.strip())
            if m:
                codes.append(int(m.group(1)))
    except OSError:
        return []
    return codes[-n:]


def _trailing_consecutive_failures(codes: list[int]) -> int:
    consec = 0
    for c in reversed(codes):
        if c != 0:
            consec += 1
        else:
            break
    return consec


def _findings_exit_logs_from_schedule_config(config: dict[str, Any] | None = None) -> set[str]:
    """Return cron log names whose non-zero exit is a findings signal.

    Audit jobs keep the historical `audit_*.log` convention. Non-audit jobs must
    declare `exit_semantics: "findings"` in config/runtime_schedules.json so the
    alert layer does not grow another hardcoded registry.
    """
    if config is None:
        try:
            config = load_runtime_schedules()
        except Exception:
            return set()

    def iter_items() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for value in config.values():
            if isinstance(value, dict) and isinstance(value.get("items"), list):
                items.extend(item for item in value["items"] if isinstance(item, dict))
        if isinstance(config.get("cron_jobs"), list):
            items.extend(item for item in config["cron_jobs"] if isinstance(item, dict))
        return items

    logs: set[str] = set()
    for item in iter_items():
        if str(item.get("exit_semantics") or "").strip().lower() != "findings":
            continue
        for key in ("log_path", "log"):
            raw = item.get(key)
            if isinstance(raw, str) and raw.strip():
                logs.add(Path(raw).name)
    return logs


def _parse_host_cron_state(storage_dir: str, now: datetime) -> dict[str, Any]:
    logs_dir = _cron_logs_dir(storage_dir)
    failing_logs: list[dict[str, Any]] = []
    # 2026-06-15 (host_cron_fail severity calibration — email-11745 incident):
    # A single hourly-dispatch SIGALRM hang (exit=142) is killed by the perl-alarm
    # cap and the NEXT hourly cron self-recovers by design (no-retry abort). Firing
    # CRITICAL on one transient self-healing hang = noise (44 historical 142s, each
    # recovered next hour). Severity is now: CRITICAL only when the failure is
    # SUSTAINED (>=2 consecutive authoritative failures = automation actually down
    # ~2h) OR a NON-hang failure (exit != 142: permission/path/FDA errors don't
    # self-heal). A lone exit=142 → WARN. The underlying recurring hang itself is
    # tracked structurally in docs/refactor_plan_hourly_dispatch.md (Three-Strike).
    max_consec_fail = 0
    any_non_hang_fail = False
    # 2026-06-07 (strike-2 structural fix): audit_* scripts use the exit code as a
    # FINDINGS signal by convention — audit_fb_pipeline.py returns 1 when it finds
    # stale-pending FB posts (scripts/audit_fb_pipeline.py:132); audit_publish_sync.py
    # returns 1 when it finds published-vs-live mismatches (mismatch_total>0). That is
    # NOT an infra-failure signal. Those findings are surfaced via their own dashboard
    # sections / report JSON. host_cron_fail is about *infrastructure* health
    # (dispatch/collect/sync), so treating "audit found a backlog/mismatch" as a
    # CRITICAL host-cron-failure is a false-critical.
    #
    # Originally this was a hardcoded set {"audit_fb_pipeline.log"}; the same
    # false-positive recurred on audit_publish_sync.log (strike 2) — so exclude ANY
    # log whose script follows the audit-exit-as-findings convention via the
    # `audit_*.log` name prefix, instead of whack-a-mole adding each file.
    # 2026-06-20 (STRIKE-3 — host_cron_fail false-critical on exit-as-findings jobs):
    # Same class as audit_* (strike-1 audit_fb_pipeline, strike-2 audit_publish_sync):
    # a daily pipeline that RAN FINE but returns non-zero to SIGNAL benign findings/
    # skips (and self-sends its own WARN) is NOT a dispatch/collect/sync infra failure.
    # indicator_arena_daily.py exits 1 when a signal is skipped — e.g. "^VIX stale"
    # (data-timing: VIX lags SPY basis by a day) or a duplicate already-emitted signal.
    # Those are findings, surfaced via the job's own WARN + report JSON; firing
    # host_cron_fail CRITICAL on them is a false-critical (email-noise → erodes trust
    # in alerting). Non-audit jobs now self-declare this via runtime_schedules.json.
    findings_exit_logs = _findings_exit_logs_from_schedule_config()

    def _is_audit_signal_log(name: str) -> bool:
        return name.startswith("audit_") or name in findings_exit_logs

    if logs_dir.exists():
        for log_path in sorted(logs_dir.glob("*.log")):
            if _is_audit_signal_log(log_path.name):
                continue
            latest = _latest_cron_exit(log_path)
            if latest and int(latest.get("exit_code", 0)) != 0:
                failing_logs.append(latest)
                codes = _trailing_authoritative_exit_codes(log_path)
                consec = _trailing_consecutive_failures(codes)
                max_consec_fail = max(max_consec_fail, consec)
                latest_code = int(latest.get("exit_code", 0))
                # exit=142 = SIGALRM hang-kill that self-recovers next hourly fire.
                # A NON-142 failure (126 perm / 1 error / FDA) does not self-heal.
                if latest_code != 142:
                    any_non_hang_fail = True
                latest["trailing_exit_codes"] = codes
                latest["consecutive_failures"] = consec

    # v12 (2026-04-19): shared_scheduler_tick cron removed; scheduler-tick now advisory-only.
    # scheduler_state staleness 不再視為 host_cron_fail — checker 改只看實際 cron log exit codes。
    # 保留 scheduler_state readout 供 body info，但不貢獻 breach judgement。
    scheduler_state = get_scheduler_state(storage_dir=storage_dir)
    scheduler_last_tick_at = _parse_iso_datetime(scheduler_state.get("last_tick_at"))
    scheduler_last_status = str(scheduler_state.get("last_status") or "never")
    scheduler_age_minutes = None
    scheduler_issue = None  # v12: 永遠 None，scheduler-tick 不再作為 alert 條件
    if scheduler_last_tick_at is not None:
        scheduler_age = now - scheduler_last_tick_at
        scheduler_age_minutes = round(scheduler_age.total_seconds() / 60.0, 1)

    breached = bool(failing_logs)  # v12: 只看 cron log exit codes，不看 scheduler staleness
    # Severity calibration (2026-06-15): a lone self-recovering SIGALRM hang → warn;
    # sustained (>=2 consecutive) or any non-hang failure → critical.
    host_cron_level = "critical" if (max_consec_fail >= 2 or any_non_hang_fail) else "warn"
    body_lines = [
        "## 觸發條件",
        f"偵測到 host cron 失敗（最新 exit code != 0）。severity={host_cron_level}"
        f"（max_consecutive_failures={max_consec_fail}；non_hang_failure={any_non_hang_fail}）。",
        "註：exit=142 = SIGALRM hang-kill，單次會由下一輪 hourly fire 自我恢復（→warn）；"
        "≥2 連續失敗或非-142 失敗才升 critical。反覆 142 結構根因見 docs/refactor_plan_hourly_dispatch.md。",
        f"- scheduler_last_tick_at: {scheduler_last_tick_at.isoformat() if scheduler_last_tick_at else 'missing'}（僅供參考，v12 後不作為 breach 判準）",
        f"- scheduler_last_status: {scheduler_last_status}",
        f"- scheduler_age_minutes: {scheduler_age_minutes if scheduler_age_minutes is not None else 'missing'}",
    ]
    if scheduler_issue:
        body_lines.append(f"- scheduler_issue: {scheduler_issue}")
    if failing_logs:
        body_lines.append("- failing_logs:")
        for row in failing_logs:
            body_lines.append(
                f"  - {row['log_path']} exit={row['exit_code']} at {row.get('exited_at') or 'unknown'}"
            )

    body_lines.extend(
        [
            "",
            "## 影響",
            "資料收集 / daily_update / release_pool 等 host cron 斷鏈 → 下游 metrics、前端顯示、",
            "Supabase mirror sync 可能顯示過期資料；若失敗的是 release_pool，會同步觸發",
            "release_pool_gap alert，發文節奏中斷。",
            "",
            "## 建議行動",
            "1. 查失敗 log： tail -20 <failing_log 路徑>",
            "2. 權限問題（exit=126）： chmod +x scripts/<script>.sh",
            "3. macOS Sequoia+ FDA（exit=1 + Operation not permitted）：",
            "   System Settings > Privacy & Security > Full Disk Access 加 script 路徑",
            "4. 手動跑 failed command 驗證修復： uv run <command>",
            "5. 比對 canonical schedule： crontab -l  vs config/runtime_schedules.json",
        ]
    )

    return {
        "id": "host_cron_fail",
        "breached": breached,
        "level": host_cron_level if breached else "info",
        "title": "Host cron failure detected",
        "body": "\n".join(body_lines) if breached else "",
        "details": {
            "scheduler_last_tick_at": scheduler_last_tick_at.isoformat() if scheduler_last_tick_at else None,
            "scheduler_last_status": scheduler_last_status,
            "scheduler_age_minutes": scheduler_age_minutes,
            "scheduler_issue": scheduler_issue,
            "failing_logs": failing_logs,
        },
    }


def _parse_member_qa_state(storage_dir: str, now: datetime) -> dict[str, Any]:
    """Detect member questions stuck in pending/evaluating > 24h.

    Lesson 2026-04-26: question 29cbeb5c (proposer=yaoxk1431) sat in
    `evaluating` status for 5 days because the question_research cron
    prompt was review-only ("若有 pending 再看 workflow") and no alert
    surfaced the gap. After this fix, pending older than 24h is `warn`
    and older than 72h is `critical`, with auto-action listed in
    .claude/rules/alert.md so the main thread runs evaluate→rerank
    immediately on the next tick instead of paging the user.
    """
    try:
        from .questions import get_member_question_ranking_summary

        summary = get_member_question_ranking_summary(source="user", limit=20)
    except Exception as exc:  # noqa: BLE001 — alert pipeline must not crash
        return {
            "id": "member_qa_stale",
            "breached": False,
            "level": "info",
            "title": "Member Q&A pending check unavailable",
            "body": "",
            "details": {"error": str(exc)},
        }

    pending = summary.get("pending_questions") or []
    stale: list[dict[str, Any]] = []
    for item in pending:
        created = _parse_iso_datetime(item.get("created_at"))
        if created is None:
            continue
        age_h = (now - created).total_seconds() / 3600.0
        if age_h >= 24:
            stale.append(
                {
                    "question_id": item.get("question_id"),
                    "proposer": item.get("proposer"),
                    "age_hours": round(age_h, 1),
                    "status": item.get("status"),
                }
            )

    if not stale:
        return {
            "id": "member_qa_stale",
            "breached": False,
            "level": "info",
            "title": "Member Q&A pending stale",
            "body": "",
            "details": {
                "stale_count": 0,
                "pending_total": len(pending),
            },
        }

    max_age = max(s["age_hours"] for s in stale)
    level = "critical" if max_age >= 72 else "warn"
    examples_lines = [
        f"- {s['question_id']} (proposer={s['proposer']}, age={s['age_hours']:.1f}h, status={s['status']})"
        for s in stale[:5]
    ]
    body = "\n".join(
        [
            "## 觸發條件",
            f"有 {len(stale)} 個 member question pending 超過 24h 未進入 ranked。",
            f"- max_age_hours: {max_age:.1f}",
            *examples_lines,
            "",
            "## 影響",
            "Mission 第 1 條（內容產出）+ 第 4 條（平台運營）受損：member 提問長時間無回應 = 平台失信號。",
            "Question pipeline 卡在 evaluating → 不進 researching → 不進 answered → user 看不到答覆。",
            "",
            "## 建議行動",
            "1. 主線程立即跑 4 維度評分：",
            "   uv run volpred ops question-ranking-workflow --source user --output-json /tmp/q_workflow.json",
            "2. 寫 evaluation JSON（每題 4 維度 1-10 score）→ /tmp/q_evals.json",
            "3. uv run volpred ops question-rerank --evaluations-json /tmp/q_evals.json",
            "4. ranked>0 後 dispatch claude subagent 跑 research stage（claim → answer → finish）",
        ]
    )
    return {
        "id": "member_qa_stale",
        "breached": True,
        "level": level,
        "title": f"Member Q&A pending stale (max {max_age:.0f}h)",
        "body": body,
        "details": {
            "stale_count": len(stale),
            "pending_total": len(pending),
            "max_age_hours": max_age,
            "examples": stale[:5],
        },
    }


def _parse_supabase_sync_state(storage_dir: str) -> dict[str, Any]:
    """Detect failed Supabase syncs queued in `.failed_supabase_syncs.json`.

    Wired 2026-04-30 after K1021 incident where release_pool's sync_article
    silently lost status='published' updates. Both publisher.publish_milestone
    and release_pool now record failed pub_ids here; this alert surfaces them
    for main-thread reconciliation.
    """
    failed_path = _storage_root(storage_dir).joinpath(".failed_supabase_syncs.json")
    failed = load_json(failed_path, [])
    if not isinstance(failed, list):
        failed = []
    pending = [str(x) for x in failed if x]
    breached = len(pending) > 0
    level = "critical" if len(pending) >= 3 else ("warn" if breached else "info")
    body = ""
    if breached:
        body = "\n".join(
            [
                "## 觸發條件",
                f".failed_supabase_syncs.json 累積 {len(pending)} 篇 article sync 失敗。",
                f"- pending_ids (前 5): {pending[:5]}",
                f"- queue_path: {_relative_repo_path(failed_path)}",
                "",
                "## 影響",
                "本地 feed.json 已更新（status=published / draft）但 Supabase 行可能停在舊狀態，",
                "造成讀者讀到的網站 status 與本地真值不一致。Mission 第 4 條（平台運營）+",
                "第 1 條（文章正確）受損。",
                "",
                "## 建議行動",
                "1. 看單篇 divergence：",
                "   uv run python -c \"from scripts.supabase_sync import _select_rows; "
                "print(_select_rows('articles', select='slug,status,published_at', slug='<id>'))\"",
                "2. 對齊本地 feed -> Supabase：",
                "   uv run python -c \"import json; from pathlib import Path; "
                "from scripts.supabase_sync import sync_article; "
                "feed=json.loads(Path('storage/reports/feed.json').read_text()); "
                "[sync_article(it, 'storage') for it in feed if it.get('id') in <list>]\"",
                "3. sync 成功後從 .failed_supabase_syncs.json 移除對應 id。",
                "4. 若連續 3 次 retry 仍 fail，查 supabase_sync log + Supabase service status。",
            ]
        )
    return {
        "id": "supabase_sync_fail",
        "breached": breached,
        "level": level,
        "title": (
            f"Supabase sync queue has {len(pending)} pending"
            if breached
            else "Supabase sync queue clean"
        ),
        "body": body,
        "details": {
            "pending_count": len(pending),
            "pending_ids": pending[:10],
            "queue_path": _relative_repo_path(failed_path),
        },
    }


def _parse_knowledge_stale_state(storage_dir: str, now: datetime) -> dict[str, Any]:
    """M2 closure staleness — knowledge.json 多天無新 entry = 研究 closure 停滯.

    2026-06-21 (boss email-11851/11854 incident): knowledge.json 連續 3 天無新
    entry，但 host_cron/release/draft 全綠 → M2 停滯完全無 alert 訊號，主線程能反覆
    用「正常研究變異 / 測量 bug」silent 解釋掉而不實際 closure。此 alert 讓 M2 closure
    停滯變成 actionable breach（不可再 deflect）。Mission L5-9：研究永遠不輸 ops。
    判定用 entries 的 max created_at（真實 closure 時間，非 mtime — mtime 會被 sync/
    其他寫入 touch 而失真）。
    """
    kj_path = _storage_root(storage_dir).joinpath("memory", "knowledge.json")
    entries = load_json(kj_path, [])
    if not isinstance(entries, list):
        entries = []
    latest: datetime | None = None
    for e in entries:
        if not isinstance(e, dict):
            continue
        ts = _parse_iso_datetime(e.get("created_at"))
        if ts is not None and (latest is None or ts > latest):
            latest = ts
    gap_days = round((now - latest).total_seconds() / 86400.0, 2) if latest is not None else None
    # >2d warn (研究該每隔一兩天 close 點什麼), >4d critical (研究線真的斷了)
    breached = latest is None or (now - latest) > timedelta(days=2)
    if not breached:
        return {
            "id": "knowledge_stale",
            "breached": False,
            "level": "info",
            "title": "Knowledge closure fresh",
            "body": "",
            "details": {"latest_entry_at": latest.isoformat() if latest else None, "gap_days": gap_days, "n_entries": len(entries)},
        }
    level = "critical" if latest is None or (now - latest) > timedelta(days=4) else "warn"
    latest_text = latest.isoformat() if latest else "missing"
    body = "\n".join(
        [
            "## 觸發條件",
            f"knowledge.json 已 {gap_days if gap_days is not None else '?'} 天無新 entry（最後 closure: {latest_text}）。",
            f"- n_entries: {len(entries)}",
            "",
            "## 影響",
            "M2（研究與實驗做好）closure 停滯 = 實驗有跑但結論沒寫進知識庫，研究產出不可見、",
            "不累積。Mission L5-9：研究與論文永遠不輸 ops。**此 breach 不可用「正常變異/測量 bug」"
            "解釋掉**，必須實際 close 實驗到 knowledge.json。",
            "",
            "## 建議行動（立即執行，不可 defer）",
            "1. 找已 review 但未 closure 的實驗：`for k in experiments/k*/; do test -f $k/codex_review.md && ! grep -ql $(basename $k) ...; done`",
            "2. 對 complete + reviewed 實驗（含 NULL/PILOT — null 如實報告）寫 knowledge：",
            "   MemorySystem(storage_dir='storage').add_knowledge(category, content, evidence, confidence)",
            "3. PASS/CONDITIONAL_PASS 需符 provenance gate（experiment_id + reviewer，見 experiments.md K1259）。",
            "4. 若無可 close 實驗 → 主線程 dispatch 新實驗並跑到 closure，不是空等。",
        ]
    )
    return {
        "id": "knowledge_stale",
        "breached": True,
        "level": level,
        "title": f"M2 knowledge closure stale > {gap_days}d",
        "body": body,
        "details": {"latest_entry_at": latest.isoformat() if latest else None, "gap_days": gap_days, "n_entries": len(entries)},
    }


def _parse_paper_stale_state(now: datetime, paper_root: Path | None = None) -> dict[str, Any]:
    """M3 paper-line staleness — 整個 paper/ 目錄多天無 manuscript/review 活動 = 論文線停滯.

    2026-06-21 (boss email-11851/11854 incident 的對稱補強): boss 同時點名 M2 *和* M3
    閒置 6-10 天。M2 已有 knowledge_stale alert，但 M3（論文）停滯一樣完全無訊號 → 主線程
    能反覆 deflect。此 alert 讓「所有論文連續多天無 .tex/.md 變動」變成 actionable breach。
    與 knowledge_stale 對稱：研究與論文永遠不輸 ops（Mission L5-9）。

    訊號 = paper/*/ 下所有 .tex / .md 檔的 max mtime（manuscript 編輯 + review 紀錄 +
    decision/errata 文件都算 M3 活動；figure .pdf/.png 與 data .csv 會被 regen 故排除）。
    取「整條論文線最近一次活動」而非 per-paper（單篇論文 review 等待期可合理靜置），
    所以只要任一篇有動就不 breach。threshold 較 knowledge 寬（論文比 closure 慢）：
    >7d warn、>14d critical。
    """
    paper_root = paper_root if paper_root is not None else project_path("paper")
    latest: datetime | None = None
    latest_file: str | None = None
    if paper_root.is_dir():
        for path in paper_root.rglob("*"):
            if path.suffix not in (".tex", ".md"):
                continue
            if not path.is_file():
                continue
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if latest is None or mtime > latest:
                latest = mtime
                latest_file = str(path.relative_to(paper_root))
    gap_days = round((now - latest).total_seconds() / 86400.0, 2) if latest is not None else None
    breached = latest is None or (now - latest) > timedelta(days=7)
    details = {
        "latest_activity_at": latest.isoformat() if latest else None,
        "latest_file": latest_file,
        "gap_days": gap_days,
    }
    if not breached:
        return {
            "id": "paper_stale",
            "breached": False,
            "level": "info",
            "title": "Paper line fresh",
            "body": "",
            "details": details,
        }
    level = "critical" if latest is None or (now - latest) > timedelta(days=14) else "warn"
    latest_text = latest.isoformat() if latest else "missing"
    body = "\n".join(
        [
            "## 觸發條件",
            f"paper/ 整條論文線已 {gap_days if gap_days is not None else '?'} 天無 .tex/.md 變動",
            f"（最後活動: {latest_text}，檔案: {latest_file or 'none'}）。",
            "",
            "## 影響",
            "M3（論文寫好）停滯 = 投稿 pipeline 沒前進，研究無法轉化為學術權威（→ 機構信任",
            "→ premium tier 背書）。Mission L5-9：研究與論文永遠不輸 ops。**此 breach 不可用",
            "「正常變異 / 等 review」解釋掉**，必須對最成熟的論文做實際下一步。",
            "",
            "## 建議行動（立即執行，不可 defer）",
            "1. 找最成熟論文的 next step：`grep -l ready_for_submission paper/*/README.md`、",
            "   各 paper README『下一步』段、`docs/paper_audit_*.md`。",
            "2. 主線程做實際推進（禁 background agent 寫 .tex）：paper-review-cycle v-round 複審、",
            "   reproduce gate 驗證、R1-track MEDIUM 修正、cover letter / submission package 定稿。",
            "3. 跑完務必 commit（mtime 才會刷新清除此 alert）；review-only 也寫 review_history/*.md。",
            "4. 若所有論文都已 submission-ready 且純等外部 → 在 README 標明並推進下一篇 draft。",
        ]
    )
    return {
        "id": "paper_stale",
        "breached": True,
        "level": level,
        "title": f"M3 paper line stale > {gap_days}d",
        "body": body,
        "details": details,
    }


def build_alert_condition_report(
    *,
    storage_dir: str = "storage",
    now: datetime | None = None,
    paper_root: Path | None = None,
) -> dict[str, Any]:
    current = now.astimezone(timezone.utc) if now is not None else _utc_now()
    conditions = [
        _parse_release_pool_state(storage_dir, current),
        _parse_draft_pool_state(storage_dir),
        _parse_host_cron_state(storage_dir, current),
        _parse_member_qa_state(storage_dir, current),
        _parse_supabase_sync_state(storage_dir),
        _parse_knowledge_stale_state(storage_dir, current),
        _parse_paper_stale_state(current, paper_root),
    ]
    return {
        "generated_at": current.isoformat(),
        "recipient": ALERT_RECIPIENT,
        "conditions": conditions,
        "breach_count": sum(1 for item in conditions if item.get("breached")),
    }


def check_alert_conditions(
    *,
    storage_dir: str = "storage",
    recipient: str = ALERT_RECIPIENT,
    now: datetime | None = None,
    paper_root: Path | None = None,
) -> dict[str, Any]:
    report = build_alert_condition_report(
        storage_dir=storage_dir, now=now, paper_root=paper_root
    )
    alerts: list[dict[str, Any]] = []
    for condition in report["conditions"]:
        if not condition.get("breached"):
            continue
        alerts.append(
            send_alert(
                str(condition["level"]),
                str(condition["title"]),
                str(condition["body"]),
                recipient=recipient,
                storage_dir=storage_dir,
            )
        )

    report["alerts"] = alerts
    report["sent_count"] = sum(1 for item in alerts if item.get("sent"))
    report["skipped_count"] = sum(1 for item in alerts if item.get("skipped"))
    report["dedup_path"] = str(_alert_dedup_path(storage_dir))
    return report
