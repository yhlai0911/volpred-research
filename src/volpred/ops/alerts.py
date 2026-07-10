from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from volpred.config import load_runtime_schedules
from volpred.publisher.email_notifier import EmailNotifier

from .boss_facing import boss_facing_alert, plainify_boss_text
from .common import dump_json, load_json, project_path
from .content_quality import (
    DIGEST_TITLE_PREFIX,
    content_quality_snapshot,
)
from .diagnostics import warn
from .release_cadence import (
    get_release_interval_minutes,
    release_cadence_threshold_hours,
    release_interval_timedelta,
)
from .loop_health import loop_health_snapshot
from .health import (
    DISK_USAGE_ALERT_PCT,
    DISK_USAGE_MIN_FREE_GB,
    PAPER_TRADING_GAP_NULL_THRESHOLD,
    check_disk_usage,
    check_paper_trading_gaps,
    check_strategy_metrics_freshness,
)
from .scheduler import get_scheduler_state

ALERT_RECIPIENT = "yihao.lai@gmail.com"
ALERT_LEVELS = ("info", "warn", "critical")
ALERT_DEDUP_WINDOW = timedelta(hours=24)
TELEGRAM_ALERT_MAX_CHARS = 4096
SCHEDULER_STALE_WINDOW = timedelta(minutes=30)
RELEASE_POOL_GAP_BUFFER = timedelta(minutes=60)  # grace on top of configured interval
HOST_CRON_RECENCY_GRACE = timedelta(minutes=10)
WORK_LOG_STALE_WARN_HOURS = 24.0
EVENT_RECEIPT_CLAIMED_WARN = timedelta(hours=24)
EVENT_RECEIPT_TERMINAL_STATUSES = {
    "succeeded",
    "failed",
    "cancelled",
    "expired",
    "done",
    "retracted",
    "skipped",
    "superseded",
    "wont_fix",
}
EVENT_RECEIPT_CLAIMED_STATUSES = {"claimed", "running", "in_progress"}
EVENT_RECEIPT_QUEUE_STATUSES = {
    "queued",
    "pending",
    "pending_main_thread",
    "awaiting_approval",
    "blocked",
}
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
        return None  # silent-ok: parse helper returns None for non-ISO input by design
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
        return None  # silent-ok: parse helper returns None for unrecognized format by design
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


_TELEGRAM_LEVEL_EMOJI = {
    "critical": "🔴",
    "warn": "⚠️",
    "info": "ℹ️",
}

_TABLE_SEPARATOR_RE = re.compile(
    r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$"
)


def _telegram_heading_emoji(text: str) -> str:
    lowered = text.lower()
    if any(token in text for token in ("觸發", "條件", "門檻")):
        return "🚦"
    if any(token in text for token in ("結果", "狀態", "摘要", "進度")):
        return "📊"
    if any(token in text for token in ("行動", "下一步", "修復", "處理", "建議")):
        return "🛠️"
    if any(token in text for token in ("驗證", "測試", "檢查")):
        return "🧪"
    if any(token in text for token in ("風險", "錯誤", "失敗", "異常")) or any(
        token in lowered for token in ("risk", "error", "fail")
    ):
        return "⚠️"
    if any(token in text for token in ("資料", "來源", "連結")):
        return "📎"
    return "📌"


def _clean_telegram_inline(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1: \2", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _trim_telegram_alert_text(text: str, max_chars: int = TELEGRAM_ALERT_MAX_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    suffix = "\n\n…（已截斷，完整內容請看 email）"
    if max_chars <= len(suffix):
        return suffix[-max_chars:]
    return f"{text[: max_chars - len(suffix)].rstrip()}{suffix}"


def _format_telegram_alert_text(
    *, level: str, title: str, body: str, max_chars: int = TELEGRAM_ALERT_MAX_CHARS
) -> str:
    """Format the Telegram mirror from the same boss-facing alert text as email."""
    title, body = boss_facing_alert(title, body, level)
    level_emoji = _TELEGRAM_LEVEL_EMOJI.get(level, "🔔")
    lines: list[str] = [f"{level_emoji} [{level.upper()}] {title.strip()}"]

    for raw_line in (body or "").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if lines[-1] != "":
                lines.append("")
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            text = _clean_telegram_inline(heading.group(2))
            if lines[-1] != "":
                lines.append("")
            lines.append(f"{_telegram_heading_emoji(text)} {text}")
            continue

        if _TABLE_SEPARATOR_RE.match(stripped):
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [
                _clean_telegram_inline(cell)
                for cell in stripped.strip("|").split("|")
                if _clean_telegram_inline(cell)
            ]
            if not cells:
                continue
            if len(cells) == 1:
                lines.append(f"• {cells[0]}")
            else:
                lines.append(f"• {cells[0]}: {' | '.join(cells[1:])}")
            continue

        bullet = re.match(r"^(?:[-*+]|\u2022)\s+(.+)$", stripped)
        if bullet:
            lines.append(f"• {_clean_telegram_inline(bullet.group(1))}")
            continue

        numbered = re.match(r"^(\d+)[.)]\s+(.+)$", stripped)
        if numbered:
            lines.append(f"{numbered.group(1)}. {_clean_telegram_inline(numbered.group(2))}")
            continue

        quote = re.match(r"^>\s+(.+)$", stripped)
        if quote:
            lines.append(f"💬 {_clean_telegram_inline(quote.group(1))}")
            continue

        lines.append(_clean_telegram_inline(stripped))

    rendered = "\n".join(lines).strip()
    rendered = re.sub(r"\n{3,}", "\n\n", rendered)
    return _trim_telegram_alert_text(rendered, max_chars=max_chars)


def _dispatch_alert_email(
    *,
    level: str,
    title: str,
    body: str,
    recipient: str,
    storage_dir: str,
) -> dict[str, Any]:
    notifier = EmailNotifier(storage_dir=storage_dir)
    display_title, display_body = boss_facing_alert(title, body, level)
    subject = f"[VolPred Alert][{level.upper()}] {display_title}"
    text_body = "\n".join(
        [
            f"Alert level: {level}",
            f"Title: {display_title}",
            "",
            display_body.strip(),
        ]
    ).strip()

    # Build HTML body via markdown→HTML + _email_shell wrapper (per user
    # 2026-05-25 directive: 所有 Claude 寄出的信都用 HTML 高資訊性編排)
    try:
        from volpred.publisher.email_notifier import (
            _email_shell,
            _try_markdown_to_html,
            highlight_email_keywords,
        )
        inner_html = _try_markdown_to_html(display_body.strip())
        # 2026-06-29 (email-12143): 對 body 套 keyword highlighter，
        # CRITICAL/WARN/INFO/PASS/FAIL/中文狀態詞/emoji 都會自動染色加粗
        inner_html = highlight_email_keywords(inner_html)
        level_color = {"info": "#2563eb", "warn": "#d97706", "critical": "#dc2626"}.get(level, "#6b7280")
        level_glyph = {"info": "ℹ", "warn": "⚠", "critical": "✖"}.get(level, "•")
        # Level badge + body content
        body_html = (
            f'<div style="display:inline-flex;align-items:center;gap:8px;padding:6px 14px;border-radius:999px;'
            f'background:{level_color};color:#fff;font-size:12px;font-weight:700;'
            f'letter-spacing:1.5px;margin-bottom:18px;box-shadow:0 2px 4px rgba(15,23,42,.12);">'
            f'<span style="font-size:14px;line-height:1;">{level_glyph}</span>'
            f'<span>{level.upper()}</span>'
            f'</div>'
            f'<div style="color:#1f2937;font-size:14.5px;line-height:1.7;">'
            f'{inner_html}'
            f'</div>'
        )
        subtitle = f"Alert level: {level}"
        html_body = _email_shell(display_title, subtitle, body_html)
    except Exception as exc:
        # silent-ok: HTML 編排失敗 fallback 純文字（已有 text_body）
        # 但留 stderr trace，避免 invisible failure（no-silent-fallback rule）
        import sys as _sys
        print(f"[alerts] html_render_failed level={level} err={exc}", file=_sys.stderr)
        html_body = None

    notification_id = notifier.notify(
        subject=subject,
        body=text_body,
        html_body=html_body,
        level=level,
        metadata={
            "notification_type": "ops_alert",
            "alert_level": level,
            "alert_title": display_title,
            "alert_title_raw": title,
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
    # 2026-07-02 (boss): mirror every alert to Telegram when the transport is
    # configured (bot token + captured chat_id). Fail-open: a TG hiccup must
    # never break the email path — email stays canonical, TG is the mirror.
    telegram_result: dict[str, Any] | None = None
    try:
        from volpred.ops.telegram import send_telegram
        tg_text = _format_telegram_alert_text(
            level=normalized_level,
            title=normalized_title,
            body=body,
        )
        # info 級靜音送達（不響鈴），warn/critical 才推播出聲 — 防 routine tick 騷擾
        telegram_result = send_telegram(
            tg_text, storage_dir=storage_dir,
            disable_notification=(normalized_level == "info"),
        )
    except Exception as _tg_exc:  # noqa: BLE001 — mirror only, never fatal
        warn("telegram_mirror", "alert mirror failed", err=str(_tg_exc)[:200])
        telegram_result = {"sent": False, "reason": str(_tg_exc)[:200]}

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
        "telegram": telegram_result,
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
    interval_minutes = get_release_interval_minutes(
        storage_dir,
        settings=settings_data if isinstance(settings_data, dict) else None,
        warn_key="release_pool_gap",
    )
    interval_td = release_interval_timedelta(
        storage_dir,
        settings=settings_data if isinstance(settings_data, dict) else None,
        warn_key="release_pool_gap",
    )
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
    alert_floor = 4
    # 2026-07-03 (boss telegram-49 follow-up): the dispatcher/refill loop now
    # self-heals non-empty draft deficits. Keep draft_count=0 as the actionable
    # page-worthy condition, but avoid noisy warn/critical alerts while 1-3 drafts
    # still exist and the pool can refill without interrupting the release path.
    self_healing_deficit = 0 < draft_count < alert_floor
    breached = draft_count == 0
    level = "critical" if breached else "info"
    body = "\n".join(
        [
            "## 觸發條件",
            "Draft 池已空（draft_count=0）。",
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
            "alert_floor": alert_floor,
            "self_healing": self_healing_deficit,
            "escalates_when_draft_count": 0,
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
    except OSError as exc:
        warn("alerts", "cron log read failed", path=str(log_path), err=str(exc))
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
    except OSError as exc:
        warn("alerts", "cron log read failed for trailing exits", path=str(log_path), err=str(exc))
        return []
    return codes[-n:]


def _trailing_consecutive_failures(
    codes: list[int], ignore_codes: tuple[int, ...] = ()
) -> int:
    """Count trailing consecutive non-zero exit codes (newest→oldest).

    ``ignore_codes`` are treated as chain-breakers, exactly like a clean exit 0.
    Used so an expected, scheduled self-recovering gap (e.g. exit=75 Claude Max
    session-limit quota window) does NOT accumulate toward the ">=2 consecutive
    = sustained outage" CRITICAL threshold, while genuine failures (incl. exit=142
    SIGALRM hang) still do.
    """
    consec = 0
    for c in reversed(codes):
        if c != 0 and c not in ignore_codes:
            consec += 1
        else:
            break
    return consec


def _findings_exit_logs_from_schedule_config(config: dict[str, Any] | None = None) -> set[str]:
    """Return cron log names whose non-zero exit is a findings signal.

    Runtime schedule metadata is the canonical source. The parser still keeps the
    historical `audit_*.log` fallback below for old logs/configs, but every current
    findings-as-exit cron should declare `exit_semantics: "findings"` in
    config/runtime_schedules.json so the alert layer does not grow another
    hardcoded registry.
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


def _iter_runtime_schedule_items(config: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for value in config.values():
        if isinstance(value, dict) and isinstance(value.get("items"), list):
            items.extend(item for item in value["items"] if isinstance(item, dict))
    if isinstance(config.get("cron_jobs"), list):
        items.extend(item for item in config["cron_jobs"] if isinstance(item, dict))
    return items


def _schedule_items_by_log_name(config: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    if config is None:
        try:
            config = load_runtime_schedules()
        except Exception as e:
            warn("alerts_schedule_by_log", "load_runtime_schedules failed", err=str(e))
            return {}

    by_log: dict[str, dict[str, Any]] = {}
    for item in _iter_runtime_schedule_items(config):
        for key in ("log_path", "log"):
            raw = item.get(key)
            if isinstance(raw, str) and raw.strip():
                by_log[Path(raw).name] = item
    return by_log


def _parse_latest_exit_time(latest: dict[str, Any]) -> datetime | None:
    raw = latest.get("exited_at")
    if isinstance(raw, datetime):
        return raw.astimezone(timezone.utc) if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str):
        return _parse_iso_datetime(raw)
    return None


def _stale_cron_exit_reason(
    latest: dict[str, Any],
    *,
    now: datetime,
    schedule_by_log: dict[str, dict[str, Any]],
) -> str | None:
    """Return a reason when a non-zero exit marker is too old to represent current state.

    A low-frequency cron can fail once and then not write a new marker for days. Without
    a recency gate, host_cron_fail re-alerts on that stale non-zero line every hour.
    We suppress only when the schedule is known and at least one subsequent scheduled
    fire should already have occurred.
    """
    exited_at = _parse_latest_exit_time(latest)
    if exited_at is None:
        return None

    log_name = Path(str(latest.get("log_path") or "")).name
    item = schedule_by_log.get(log_name)
    cron_expr = (item.get("cron") or item.get("schedule")) if item else None
    if not isinstance(cron_expr, str) or not cron_expr.strip():
        return None

    try:
        from croniter import croniter

        exited_local = exited_at.astimezone(_TAIPEI_TZ)
        next_fire = croniter(cron_expr.strip(), exited_local).get_next(datetime)
    except Exception as e:
        warn("alerts_host_cron_recency", "croniter next-fire calc failed", cron=cron_expr, err=str(e))
        return None

    if next_fire.tzinfo is None:
        next_fire = next_fire.replace(tzinfo=_TAIPEI_TZ)
    stale_after = next_fire.astimezone(timezone.utc) + HOST_CRON_RECENCY_GRACE
    if now.astimezone(timezone.utc) > stale_after:
        return (
            f"stale_exit_after_next_scheduled_fire: exited_at={exited_at.isoformat()} "
            f"next_fire={next_fire.astimezone(timezone.utc).isoformat()} "
            f"grace={HOST_CRON_RECENCY_GRACE}"
        )
    return None


# 2026-07-02 (host_cron_fail false-critical on Claude Max quota window):
# The hourly-dispatch auth-preflight probe returns exit=1 when the Claude Max
# subscription hits its rolling 5h session limit ("You've hit your session limit
# · resets 8:20pm"). That is NOT an infra failure — it is an expected, scheduled,
# self-resetting quota window (the wrapper hands the slot to Codex failover in the
# meantime, and Claude auth comes back on its own at the reset). The wrapper now
# emits a distinct exit=75 (EX_TEMPFAIL) for that path so it is classified like the
# self-recovering SIGALRM hang (142) rather than a hard failure. Both are self-
# recovering per-fire; additionally 75 is EXCLUDED from the consecutive-failure
# escalation because a quota window legitimately spans >=2 fires, whereas a hang
# spanning 2 fires does mean automation is stuck.
_QUOTA_EXHAUSTED_EXIT_CODE = 75
_SELF_RECOVERING_EXIT_CODES = frozenset({142, _QUOTA_EXHAUSTED_EXIT_CODE})

# 2026-07-03 (host_cron_fail false-critical on git_push_backup held push — same
# class as the 2026-06-20 STRIKE-3 exit-as-findings false-critical, new instance):
# cron_git_push_backup.sh protectively HOLDS a push when HEAD carries a NEW silent
# fallback (audit_silent_fallbacks new>0) so red code never reaches origin and CI
# never goes red. That hold is the guard WORKING AS DESIGNED — the wrapper RAN FINE
# and self-sends its own targeted WARN ("push held — N new silent fallbacks: <list>").
# It is NOT a cron infra failure. But the wrapper previously exit 1'd the hold, which
# is indistinguishable from its REAL failures (origin divergence, real push failure),
# so host_cron_fail escalated to CRITICAL after 2 fires — a single line-38 false-
# positive silent-fallback flag on _claude_project_dir.py cascaded into 28x CRITICAL
# over 4 days (2026-06-29 → 07-03). Per-log findings exemption (_is_audit_signal_log)
# is too coarse here because the OTHER exit-1 paths are genuine failures we DO want to
# alert on. So the wrapper now emits a distinct code 120 for the held path only, and
# that code is treated as a benign, self-reported findings signal: fully exempt from
# host_cron_fail (job self-reports via its own WARN), while exit 1 (divergence / real
# push failure) still fires CRITICAL. Global sentinel like 75/142, not a hardcoded
# log-name registry.
_PUSH_HELD_EXIT_CODE = 120
_BENIGN_FINDINGS_EXIT_CODES = frozenset({_PUSH_HELD_EXIT_CODE})

_PUSH_BACKLOG_WARN_HOURS = 3.0
_PUSH_BACKLOG_CRITICAL_HOURS = 8.0


def _parse_push_backlog_state(storage_dir: str, now: datetime) -> dict[str, Any]:
    """git-push-backup dead-man switch — watches UNPUSHED-BACKLOG AGE, not exit codes.

    2026-07-04 incident: the pre-push silent-fallback gate correctly HELD pushes
    (exit=120 — deliberately exempt from host_cron_fail as a benign self-reported
    finding) for 26 consecutive hourly fires (~26h, 47-commit backlog). The gate
    did its job; the gap was that nothing ESCALATED a persistent hold — the job's
    own warn email was deduped for 24h, and each hourly session that saw it had
    legitimate anti-clobber reasons not to touch mid-edit files. This condition
    measures the harm directly (age of the oldest commit not on origin), so ANY
    cause of a growing backlog — held gate, divergence, auth, network — surfaces
    the same way without re-litigating exit-code semantics:
      oldest unpushed >= 3h → warn (3+ consecutive held/failed hourly fires)
      oldest unpushed >= 8h → critical (a working day of local-only work at risk)
    """
    import subprocess  # noqa: WPS433 — deferred; keeps module import light for offline tests

    repo_root = _storage_root(storage_dir).parent
    breached = False
    level = "info"
    ahead_count = 0
    oldest_age_hours: float | None = None
    note = ""
    try:
        rev_list = subprocess.run(
            ["git", "-C", str(repo_root), "rev-list", "--count", "origin/main..main"],
            capture_output=True, text=True, timeout=15,
        )
        if rev_list.returncode != 0:
            # No origin/main ref (fresh clone / detached test env) — nothing to measure.
            note = f"rev-list unavailable: {rev_list.stderr.strip()[:120]}"
        else:
            ahead_count = int(rev_list.stdout.strip() or 0)
            if ahead_count > 0:
                log_ct = subprocess.run(
                    ["git", "-C", str(repo_root), "log", "origin/main..main", "--format=%ct"],
                    capture_output=True, text=True, timeout=15,
                )
                stamps = [int(s) for s in log_ct.stdout.split() if s.strip().isdigit()]
                if stamps:
                    oldest = datetime.fromtimestamp(min(stamps), tz=timezone.utc)
                    oldest_age_hours = (now - oldest).total_seconds() / 3600.0
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        warn("push_backlog", "git backlog probe failed", err=str(exc))
        note = f"probe failed: {exc}"

    if oldest_age_hours is not None and oldest_age_hours >= _PUSH_BACKLOG_WARN_HOURS:
        breached = True
        level = "critical" if oldest_age_hours >= _PUSH_BACKLOG_CRITICAL_HOURS else "warn"

    if breached:
        title = f"push_backlog: {ahead_count} 個 commit 已 {oldest_age_hours:.1f} 小時推不上 GitHub"
        body = "\n".join([
            "## 觸發條件",
            f"- 未推上 GitHub 的 commit 數：{ahead_count}",
            f"- 最老一筆已滯留：{oldest_age_hours:.1f} 小時（警戒 {_PUSH_BACKLOG_WARN_HOURS:.0f}h / 嚴重 {_PUSH_BACKLOG_CRITICAL_HOURS:.0f}h）",
            "- 來源：`git rev-list origin/main..main`（每小時 check-alerts 巡檢）",
            "",
            "## 影響",
            "每小時自動備份推送連續多班沒成功（品質關卡擋下 / 分岔 / 認證 / 網路）。"
            "本機工作越久沒上雲端，機器故障時遺失的研究與程式就越多——直接威脅可復現性承諾。",
            "",
            "## 建議行動",
            "1. `tail -40 storage/logs/cron/git_push_backup.log` 看最近被擋/失敗原因",
            "2. 若是 `HELD: N new silent fallback(s)`：跑 `uv run python scripts/audit_silent_fallbacks.py"
            " --strict --baseline storage/qa/silent_fallback_baseline.json`，把 NEW 位置按"
            " `.claude/rules/no-silent-fallback.md` 修掉（加 log 或 `# silent-ok:` 標註）並 commit",
            "3. 手動重跑解封：`bash scripts/cron_git_push_backup.sh`",
            "4. 確認 `git rev-list --count origin/main..main` 回 0",
        ])
    else:
        title = "push_backlog ok"
        body = ""

    return {
        "id": "push_backlog",
        "breached": breached,
        "level": level,
        "title": title,
        "body": body,
        "details": {
            "ahead_count": ahead_count,
            "oldest_unpushed_age_hours": round(oldest_age_hours, 2) if oldest_age_hours is not None else None,
            "note": note,
        },
    }


_ORPHAN_BRANCH_WARN_HOURS = 2.0
_ORPHAN_BRANCH_CRITICAL_HOURS = 24.0


def _parse_orphan_branch_state(storage_dir: str, now: datetime) -> dict[str, Any]:
    """Worktree removed, branch left behind with unmerged commits — nobody owns it.

    2026-07-10 incident: two `claude/*` branches (`cron-marker-truth`,
    `eloquent-chatterjee-32e858`) survived their worktrees' cleanup carrying
    `wip(rescue)` commits — 188-line `cron_mark_last_run.py` + its 240-line test,
    and a 195-line isolation-guard test — none of it on main. They were found by
    hand. The worktree-removal path is guarded six ways (K1032/K1114/K1262/K1618)
    but every guard protects the *worktree*; once it is gone the branch has no
    owner and no signal. `git branch -d` refuses to help because it only knows
    "unmerged", and today's two orphans were BOTH parallel re-implementations
    whose merge would have been actively harmful — so this cannot auto-remediate.
    It escalates by the age of the newest unmerged commit (how long the work has
    sat unclaimed), not by orphan-detection time, which we cannot observe:
      newest unmerged commit >= 2h  → warn  (the merging session moved on)
      newest unmerged commit >= 24h → critical (a day of work with no owner)
    Branches whose worktree still exists are excluded — they are being worked on.
    Fully-merged orphans are counted in details but never breach: they are
    deletable housekeeping, not endangered work.
    """
    import subprocess  # noqa: WPS433 — deferred; keeps module import light for offline tests

    repo_root = _storage_root(storage_dir).parent
    breached = False
    level = "info"
    note = ""
    orphans: list[dict[str, Any]] = []
    merged_deletable: list[str] = []

    def _git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True, text=True, timeout=15,
        )

    try:
        heads = _git("for-each-ref", "--format=%(refname:short)", "refs/heads/claude/")
        if heads.returncode != 0:
            note = f"for-each-ref unavailable: {heads.stderr.strip()[:120]}"
        else:
            wt = _git("worktree", "list", "--porcelain")
            attached = {
                line.split(" ", 1)[1].strip().removeprefix("refs/heads/")
                for line in wt.stdout.splitlines()
                if line.startswith("branch ")
            }
            for branch in (b.strip() for b in heads.stdout.splitlines() if b.strip()):
                if branch in attached:
                    continue  # a live worktree owns it
                counted = _git("rev-list", "--count", branch, "^main")
                if counted.returncode != 0:
                    warn("orphan_branch", "rev-list failed", branch=branch, err=counted.stderr.strip()[:120])
                    continue
                unmerged = int(counted.stdout.strip() or 0)
                if unmerged == 0:
                    merged_deletable.append(branch)
                    continue
                stamps_out = _git("log", f"main..{branch}", "--format=%ct")
                stamps = [int(s) for s in stamps_out.stdout.split() if s.strip().isdigit()]
                if not stamps:
                    warn("orphan_branch", "no commit timestamps", branch=branch)
                    continue
                newest = datetime.fromtimestamp(max(stamps), tz=timezone.utc)
                orphans.append({
                    "branch": branch,
                    "unmerged_commits": unmerged,
                    "newest_commit_age_hours": round((now - newest).total_seconds() / 3600.0, 2),
                })
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        warn("orphan_branch", "git orphan-branch probe failed", err=str(exc))
        note = f"probe failed: {exc}"

    aged = [o for o in orphans if o["newest_commit_age_hours"] >= _ORPHAN_BRANCH_WARN_HOURS]
    if aged:
        breached = True
        worst = max(o["newest_commit_age_hours"] for o in aged)
        level = "critical" if worst >= _ORPHAN_BRANCH_CRITICAL_HOURS else "warn"

    if breached:
        total_commits = sum(o["unmerged_commits"] for o in aged)
        title = f"orphan_branch: {len(aged)} 條 branch 有 {total_commits} 個未合併 commit，但 worktree 已被刪除"
        lines = [
            "## 觸發條件",
            f"- 沒有 worktree、但仍帶未合併 commit 的 claude/* branch：{len(aged)} 條"
            f"（警戒 {_ORPHAN_BRANCH_WARN_HOURS:.0f}h / 嚴重 {_ORPHAN_BRANCH_CRITICAL_HOURS:.0f}h）",
        ]
        for o in sorted(aged, key=lambda x: -x["newest_commit_age_hours"]):
            lines.append(
                f"  - `{o['branch']}`：{o['unmerged_commits']} 個 commit，"
                f"最後一次提交在 {o['newest_commit_age_hours']:.1f} 小時前"
            )
        lines += [
            "- 來源：`git for-each-ref refs/heads/claude/` 比對 `git worktree list`（每小時巡檢）",
            "",
            "## 影響",
            "worktree 被清掉時，branch 上的工作沒有任何人接手 —— 移除流程的六層防護全都在保護 worktree，"
            "worktree 一消失，branch 就失去 owner 也失去訊號。這些 commit 常是清理前臨時搶救的 `wip(rescue)`，"
            "內容可能是別處沒有的測試或工具。研究可復現性直接受威脅。",
            "",
            "## 建議行動",
            "1. 先查是否已被別的路徑取代（今天兩條都是平行實作）："
            "`git diff main <branch> -- <關鍵檔>`、`git log --oneline main..<branch>`",
            "2. 若內容仍獨有 → 從 repo root 正常合併，並在合併後逐檔 `git cat-file -e HEAD:<path>` 驗證真的進了 main",
            "3. 若已被取代 → `git branch -D <branch>`（commit object 仍在 reflog 內可救回）",
            "4. ⚠️ 不可直接 `git merge` 平行實作：衝突檔會被人工審視，**不衝突的檔會被靜默採用**，"
            "混合兩套設計會在執行期才炸（見 error_log 2026-07-10 ffaad8 entry）",
        ]
        body = "\n".join(lines)
    else:
        title = "orphan_branch ok"
        body = ""

    return {
        "id": "orphan_branch",
        "breached": breached,
        "level": level,
        "title": title,
        "body": body,
        "details": {
            "orphan_count": len(orphans),
            "aged_orphan_count": len(aged),
            "orphans": orphans,
            "merged_deletable": merged_deletable,
            "note": note,
        },
    }


def _parse_host_cron_state(storage_dir: str, now: datetime) -> dict[str, Any]:
    logs_dir = _cron_logs_dir(storage_dir)
    failing_logs: list[dict[str, Any]] = []
    stale_logs: list[dict[str, Any]] = []
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
    # 2026-06-07 (strike-2 structural fix): audit_* scripts may use the exit code as
    # a FINDINGS signal — audit_fb_pipeline.py returns 1 when it finds stale-pending
    # FB posts; audit_publish_sync.py returns 1 when it finds published-vs-live
    # mismatches. That is NOT an infra-failure signal. Those findings are surfaced
    # via their own dashboard sections / report JSON. host_cron_fail is about
    # *infrastructure* health (dispatch/collect/sync), so treating "audit found a
    # backlog/mismatch" as a CRITICAL host-cron-failure is a false-critical.
    #
    # Originally this was a hardcoded set {"audit_fb_pipeline.log"}; the same
    # false-positive recurred on audit_publish_sync.log (strike 2). Current
    # runtime_schedules entries should self-declare exit_semantics=findings; the
    # `audit_*.log` name prefix remains as a legacy fallback.
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
    schedule_by_log = _schedule_items_by_log_name()

    def _is_audit_signal_log(name: str) -> bool:
        return name.startswith("audit_") or name in findings_exit_logs

    if logs_dir.exists():
        for log_path in sorted(logs_dir.glob("*.log")):
            if _is_audit_signal_log(log_path.name):
                continue
            latest = _latest_cron_exit(log_path)
            if latest and int(latest.get("exit_code", 0)) != 0:
                latest_exit_time = _parse_latest_exit_time(latest)
                if latest_exit_time is None:
                    latest["recency_status"] = "unknown_exited_at"
                    latest["recency_gate"] = "cap_warn"
                else:
                    stale_reason = _stale_cron_exit_reason(
                        latest,
                        now=now,
                        schedule_by_log=schedule_by_log,
                    )
                    if stale_reason:
                        latest["recency_status"] = "stale"
                        latest["recency_gate"] = "ignored"
                        latest["recency_reason"] = stale_reason
                        stale_logs.append(latest)
                        continue
                    latest["recency_status"] = "fresh_or_unscheduled"
                # Benign, self-reported findings signal (e.g. git_push_backup HELD a
                # push due to a new silent fallback and self-sent its own WARN). The
                # cron ran fine and made a correct protective decision — not an infra
                # failure. Fully exempt from host_cron_fail so the job's own targeted
                # WARN is the single signal (avoids redundant + misleading CRITICAL).
                if int(latest.get("exit_code", 0)) in _BENIGN_FINDINGS_EXIT_CODES:
                    continue
                failing_logs.append(latest)
                codes = _trailing_authoritative_exit_codes(log_path)
                # Quota-window fires (exit=75) break the consecutive-failure chain:
                # a Claude Max session-limit gap spanning >=2 fires is expected, not
                # a sustained outage. A 142 hang chain is still counted (stuck != gap).
                consec = _trailing_consecutive_failures(
                    codes,
                    ignore_codes=(_QUOTA_EXHAUSTED_EXIT_CODE, *_BENIGN_FINDINGS_EXIT_CODES),
                )
                max_consec_fail = max(max_consec_fail, consec)
                latest_code = int(latest.get("exit_code", 0))
                # Self-recovering codes: exit=142 = SIGALRM hang-kill (self-recovers
                # next hourly fire); exit=75 = Claude Max quota window (self-resets on
                # schedule, Codex covers the gap). A hard failure (126 perm / 1 error /
                # FDA) does not self-heal.
                if (
                    latest.get("recency_status") != "unknown_exited_at"
                    and latest_code not in _SELF_RECOVERING_EXIT_CODES
                ):
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
    # Severity calibration (2026-07-04, boss Telegram msg 114/121/141 — repeated
    # CRITICAL noise on self-recovering hangs): a self-recovering exit code (142
    # SIGALRM hang / 75 Claude Max quota window) NEVER escalates to CRITICAL, even
    # consecutive. By definition these self-recover on the next hourly fire (proven
    # 2026-07-04: 13:57+14:57 CST both exit=142 → 15:47 exit=0 recovered on its own).
    # The 2026-06-15 calibration only downgraded a LONE 142→warn but kept
    # 2x-consecutive-142→CRITICAL; that residual still paged the boss every time two
    # transient hangs landed back-to-back before self-recovering. Genuine *sustained*
    # outage (automation truly down for hours) is already covered by the outcome-level
    # dead-man switches (release_pool_gap, publishing_freshness) which fire on ACTUAL
    # stalled output regardless of cause — so a consecutive-142 CRITICAL here is pure
    # redundant noise. The recurring 142 hang *class* itself is a structural problem
    # tracked/fixed by the worker-daemon refactor (docs/refactor_plan_hourly_dispatch.md,
    # cutover 2026-07-04 17:17), NOT an every-hour CRITICAL page. Rule now: ONLY a
    # non-self-recovering hard failure (exit != {142,75}: permission/path/FDA/push
    # error — these do not self-heal) fires CRITICAL. A self-recovering chain → WARN.
    host_cron_level = "critical" if any_non_hang_fail else "warn"
    body_lines = [
        "## 觸發條件",
        f"偵測到 host cron 失敗（最新 exit code != 0）。severity={host_cron_level}"
        f"（max_consecutive_failures={max_consec_fail}；non_hang_failure={any_non_hang_fail}）。",
        "註：exit=142 = SIGALRM hang-kill，會由下一輪 hourly fire 自我恢復；"
        "exit=75 = Claude Max session-limit 額度窗口（排程自我重置，期間由 Codex failover 接手）；"
        "這兩類自我恢復碼不論連幾次都只升 warn，不升 critical（真正持續斷線由發文脫班／"
        "release_pool_gap 這類 outcome-level dead-man switch 抓）。只有非自我恢復的硬失敗"
        "（exit != {142,75}：權限／路徑／FDA／push 錯誤）才升 critical。"
        f"若非零 exit 已超過下一個預定 fire + {HOST_CRON_RECENCY_GRACE}，視為 stale marker，"
        "不再每小時重判。"
        "反覆 142 結構根因見 docs/refactor_plan_hourly_dispatch.md。",
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
                f" recency={row.get('recency_status', 'unknown')}"
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
            "stale_logs": stale_logs,
            "host_cron_recency_grace_minutes": int(HOST_CRON_RECENCY_GRACE.total_seconds() // 60),
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
            except OSError as exc:
                warn("alerts", "paper file stat failed", path=str(path), err=str(exc))
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


# ── 2026-07-01 STRUCTURAL（boss loop-engineering / PDCA directive）──
# Root cause: 論文投稿「決策真相」在 storage/paper_pipeline_status.json（journal_target/stage），
# 但公開網頁「展示真相」在 Supabase papers 表（target_journal/status），兩者**無 reconciliation**。
# incident（2026-07-01）：leverage-direction 投稿決策 JBF→IJF 且 downgrade 回 revision，但網頁仍
# 停在 target_journal=JBF + status=ready_for_submission（over-claim），且無任何 check 會發現 —— 靠
# boss 人工抓到。這是「dual source, no single-source-of-truth」結構缺陷。此 detector 讓「網頁高估
# 論文成熟度」變 auto-surfaced breach。誠實設計：**只在網頁 status 高於 pipeline stage 對應的可接受
# 上限時 breach**（over-claim = 研究誠實紅線）；網頁落後（under-claim，如 pipeline=under_review 但
# 網頁保守顯 working）只 info 不 breach（未經驗證前寧可保守）。journal 全名 vs 縮寫模糊比對不做
# breach（寧漏報不誤報洗版），只在「pipeline 有明確 primary 但網頁 null」時附註。
_WEBSITE_STATUS_RANK = {
    "working": 0,
    "ready_for_submission": 1,
    "submitted": 2,
    "accepted": 3,
    "published": 4,
}
_RANK_TO_STATUS = {v: k for k, v in _WEBSITE_STATUS_RANK.items()}
# 每個 pipeline stage（paper_pipeline_status.json 的 11 態）允許的網頁 status 上限（rank）。
# 網頁 status rank 超過此上限 = over-claim。
_PIPELINE_STAGE_MAX_WEBSITE_RANK = {
    "draft": 0,
    "revision": 0,
    "compliance_scrub": 0,
    "multi_round_review": 0,
    "review_converged": 1,
    "arxiv_ready": 1,
    "arxiv_posted": 2,
    "journal_submitted": 2,
    "under_journal_review": 2,
    "accepted": 3,
    "rejected": 0,
    "published": 4,
}


def _parse_paper_website_drift_state(now: datetime) -> dict[str, Any]:
    """公開網頁論文卡是否 over-claim（status 高於 pipeline 決策該有的成熟度）。

    決策真相 = storage/paper_pipeline_status.json；展示真相 = Supabase papers 表。
    只抓 over-claim（網頁高估）→ warn；under-claim（網頁保守）不 breach。
    Fail-open：pipeline 讀失敗或 Supabase 連不上 → warn(diagnostics) + 標 degraded，不 crash、不誤 breach。
    """
    pipeline_path = project_path("storage/paper_pipeline_status.json")
    try:
        pipeline = load_json(pipeline_path, None)
        if not isinstance(pipeline, dict):
            raise ValueError(f"pipeline status missing or malformed: {pipeline_path}")
        pipeline_papers = {
            str(p.get("paper")): p
            for p in (pipeline.get("papers") or [])
            if p.get("paper")
        }
    except Exception as exc:  # noqa: BLE001 — fail-open per no-silent-fallback.md
        warn("alerts", "paper_website_drift pipeline read failed", path=str(pipeline_path), err=str(exc))
        return {
            "id": "paper_website_drift",
            "breached": False,
            "level": "info",
            "title": "paper_website_drift degraded (pipeline unreadable)",
            "body": "",
            "details": {"degraded": True, "reason": "pipeline_read_failed"},
        }

    website_rows: dict[str, dict[str, Any]] = {}
    degraded = False
    try:
        from .papers import list_papers

        for row in list_papers():
            pid = str(row.get("id") or "")
            if pid:
                website_rows[pid] = row
    except Exception as exc:  # noqa: BLE001 — Supabase 外部依賴 fail-open
        warn("alerts", "paper_website_drift supabase read failed", err=str(exc))
        degraded = True

    over_claims: list[dict[str, Any]] = []
    journal_gaps: list[dict[str, Any]] = []
    if not degraded:
        for pid, ppaper in pipeline_papers.items():
            row = website_rows.get(pid)
            if row is None:
                continue  # pipeline 有、網頁未上架 = 可能故意，不算 drift
            stage = str(ppaper.get("stage") or "").strip()
            max_rank = _PIPELINE_STAGE_MAX_WEBSITE_RANK.get(stage)
            web_status = str(row.get("status") or "working").strip()
            web_rank = _WEBSITE_STATUS_RANK.get(web_status)
            if max_rank is not None and web_rank is not None and web_rank > max_rank:
                over_claims.append(
                    {
                        "paper": pid,
                        "pipeline_stage": stage,
                        "website_status": web_status,
                        "max_acceptable_status": _RANK_TO_STATUS.get(max_rank, "working"),
                    }
                )
            j_target = str(ppaper.get("journal_target") or "").strip()
            if (
                j_target
                and j_target.lower() not in ("decide", "tbd", "none")
                and not row.get("target_journal")
            ):
                journal_gaps.append({"paper": pid, "pipeline_journal_target": j_target})

    breached = bool(over_claims)
    details = {
        "over_claims": over_claims,
        "journal_gaps": journal_gaps,
        "degraded": degraded,
        "checked": len(pipeline_papers),
    }
    if not breached:
        if degraded:
            title = "paper_website_drift degraded (supabase unreadable)"
        else:
            title = "Paper website in sync with pipeline"
        return {
            "id": "paper_website_drift",
            "breached": False,
            "level": "info",
            "title": title,
            "body": "",
            "details": details,
        }

    lines = [
        "## 觸發條件",
        f"{len(over_claims)} 篇論文的公開網頁 status **高於** pipeline 決策該有的成熟度（over-claim）：",
        "",
    ]
    for oc in over_claims:
        lines.append(
            f"- **{oc['paper']}**：網頁顯示 `{oc['website_status']}`，但 pipeline stage="
            f"`{oc['pipeline_stage']}` 最多只該到 `{oc['max_acceptable_status']}`"
        )
    if journal_gaps:
        lines.append("")
        lines.append("附註（journal 缺漏，非 breach 判準）：")
        for jg in journal_gaps:
            lines.append(
                f"- {jg['paper']}：pipeline target=`{jg['pipeline_journal_target']}` 但網頁 target_journal 為空"
            )
    lines += [
        "",
        "## 影響",
        "公開網頁高估論文成熟度 = 對讀者/機構過度宣稱（違反研究誠實）。投稿決策改了、網頁沒同步 =",
        "M3 學術權威線 credibility 受損。",
        "",
        "## 建議行動（主線程判斷後執行，非自動 sync）",
        "1. 對每篇 over-claim 確認 pipeline stage 是否為真實狀態（非 aspirational）。",
        "2. 用 canonical CLI 對齊（**非**手改 DB）：",
        "   `uv run volpred ops paper-upsert --paper-id <id> --status <working|ready_for_submission|"
        "submitted> [--target-journal <name>]`",
        "3. 不自動 sync 的原因：pipeline stage 有時 aspirational（如 under_journal_review 但未驗證真",
        "   投），自動推公開網頁會反向製造 over-claim；由主線程判斷哪些該公開。",
    ]
    return {
        "id": "paper_website_drift",
        "breached": True,
        "level": "warn",
        "title": f"網頁論文 over-claim {len(over_claims)} 篇（決策改了網頁沒同步）",
        "body": "\n".join(lines),
        "details": details,
    }


# ── 2026-06-22 STRUCTURAL（boss directive「禁止脫班，徹底從底層架構解決」/ Three-Strike）──
# 既有 alert 全部監看「機器/流程」（job 是否 fire）：release-pool-by-settings 每次 run
# 都改寫 updated_at → machinery 永遠不顯 stale，即使 0 篇發出；沒有任何 check 監看
# 「實際產出」（最新發佈文章新鮮度）。2026-06-22 incident：hourly dispatch 的 pinned
# claude binary 被 auto-update 刪 → generator 整日產 0 → release filter 擋住老化池 →
# 12h 只發 1 篇，但 breach_count=0（每個 job exit 0）。以下兩個 check 直接監看 OUTCOME
# （feed 新鮮度，active-window aware，CRITICAL）+ generator binary 源頭健康，與 job
# exit code 完全脫鉤，補上這層盲區。
PUBLISH_FRESHNESS_CRITICAL_HOURS = 5.0  # legacy floor; 實際門檻 = release interval + grace（見下）
PUBLISH_FRESHNESS_GRACE_HOURS = 2.0  # dead-man switch buffer on top of release cadence
_TAIPEI_TZ = ZoneInfo("Asia/Taipei")
PUBLISH_ACTIVE_START_HOUR = 9   # 台北時間：此窗內才預期有新內容
PUBLISH_ACTIVE_END_HOUR = 23


def _parse_publishing_freshness_state(storage_dir: str, now: datetime) -> dict[str, Any]:
    feed_path = _storage_root(storage_dir).joinpath("reports", "feed.json")
    feed = load_json(feed_path, [])
    if not isinstance(feed, list):
        feed = []
    pub_times: list[datetime] = []
    for item in feed:
        if not isinstance(item, dict) or item.get("status") != "published":
            continue
        ts = _parse_iso_datetime(item.get("published_at") or item.get("created_at"))
        if ts is not None:
            pub_times.append(ts)
    newest = max(pub_times) if pub_times else None
    gap_hours = round((now - newest).total_seconds() / 3600.0, 2) if newest is not None else None
    tpe_hour = now.astimezone(_TAIPEI_TZ).hour
    in_active_window = PUBLISH_ACTIVE_START_HOUR <= tpe_hour < PUBLISH_ACTIVE_END_HOUR
    # 2026-06-30: 門檻須跟 boss-configured release cadence 對齊（同 release_pool_gap
    # 2026-04-20 教訓：hardcoded 門檻在 cadence 變更後 false-positive）。boss 改 6h 後，
    # 固定 5h 門檻 < 6h interval → 每個 release cycle 末（5h 後、下個 release 前）誤報。
    # threshold = interval + grace（dead-man switch 要避免 false critical，給足 buffer）。
    interval_min = get_release_interval_minutes(storage_dir, warn_key="publishing_freshness")
    threshold_hours = release_cadence_threshold_hours(
        storage_dir,
        grace_hours=PUBLISH_FRESHNESS_GRACE_HOURS,
        floor_hours=PUBLISH_FRESHNESS_CRITICAL_HOURS,
        precision=1,
        warn_key="publishing_freshness",
    )
    breached = bool(
        in_active_window
        and (newest is None or (gap_hours is not None and gap_hours > threshold_hours))
    )
    newest_text = newest.isoformat() if newest else "missing"
    body = "\n".join(
        [
            "## 觸發條件",
            f"作用窗（台北 {PUBLISH_ACTIVE_START_HOUR}:00–{PUBLISH_ACTIVE_END_HOUR}:00）內，feed 最新已發佈文章距今 > {threshold_hours}h（= release interval {round(interval_min/60,1)}h + {PUBLISH_FRESHNESS_GRACE_HOURS}h grace）。",
            f"- newest_published_at: {newest_text}",
            f"- publish_gap_hours: {gap_hours if gap_hours is not None else 'missing'}",
            f"- threshold_hours: {threshold_hours}",
            f"- feed_path: {_relative_repo_path(feed_path)}",
            "",
            "## 影響",
            "這是『發文脫班』的 outcome-level dead-man switch：不論成因（dispatch generator 死、",
            "auth 失效、release cluster-filter 擋住、draft 池空），只要『實際沒發文』就觸發。",
            "直接打 Mission 第 1 條（內容）＋第 5 條（流量）。2026-06-22 整日脫班即此盲區。",
            "",
            "## 系統已自動修復（無需老闆手動介入）",
            "本 alert 是 outcome-level dead-man switch；hourly check（scripts/check_alerts.py）",
            "在寄出此信之前，已自動跑完補救階梯（scripts/remediate_publish_drought.py）：",
            "1. 已 force 釋出草稿池 — drought circuit-breaker 挑最不重複的草稿發佈。",
            "2. 若草稿池空 / 全是已發過主題的重寫（無新可發）→ 已自動補 fresh 研究主題進",
            "   task pool，下一班 hourly dispatch（每小時 :07）會自動生成並發佈。",
            "",
            "你會收到此信，代表本班沒有現成 fresh 草稿可即時發、補救已排入下一班生成。",
            "系統會自繼續修復；**只有連續 2 班 hourly dispatch 後仍脫班**才需人工檢查",
            "generator：tail -5 storage/logs/cron/hourly_dispatch.log（看是否 auth-preflight",
            "fail / binary-not-found 秒退）。",
        ]
    )
    return {
        "id": "publishing_freshness",
        "breached": breached,
        "level": "critical" if breached else "info",
        # title 必須穩定（不含動態數字）— 否則 sha256(level+title) 24h dedup 失效、
        # 持續 breach 時每小時洗版。動態 gap 放 body / details（2026-06-23 dedup 修正）。
        "title": (
            "發文脫班（無新文超過 release 節奏門檻）"
            if breached
            else "publishing_freshness ok"
        ),
        "body": body if breached else "",
        "details": {
            "newest_published_at": newest_text,
            "publish_gap_hours": gap_hours,
            "in_active_window": in_active_window,
            "tpe_hour": tpe_hour,
            "threshold_hours": threshold_hours,
        },
    }


# Must stay identical to `scripts/dispatch_supervisor/worker.py::CLAUDE_BIN`'s
# default — pinned mechanically by
# `tests/test_dispatch_binary_health_source.py::test_alerts_default_matches_worker`.
# A literal (not an import) because `check_alerts.py` lives inside `scripts/`,
# which has no `__init__.py`, so `import scripts.dispatch_supervisor.worker`
# resolves only under pytest's rootdir sys.path, not in the cron process.
DISPATCH_CLAUDE_BIN_DEFAULT = "/Users/yhlai0911/.local/bin/claude"


def _parse_dispatch_health_state(storage_dir: str, now: datetime) -> dict[str, Any]:
    """Is the binary the dispatcher shells out to actually resolvable?

    2026-07-10: this used to grep `CLAUDE_BIN` out of
    `~/.volpred/bin/cron_hourly_dispatch.sh` — the legacy shell wrapper that the
    2026-07-04 daemon cutover retired. The file still sits on disk (its
    LaunchAgent is unloaded, so nothing fires it), and the daemon resolves its
    binary from `worker.py::CLAUDE_BIN` instead. The alert was therefore
    validating a dead artifact and only happened to be right because both named
    the same path. That is precisely the failure mode of the 2026-07-08 false
    stale-dispatch alert (a monitor still pointed at a post-cutover corpse), so
    it is fixed here before it can bite: resolve the binary by the SAME rule the
    daemon uses (`CLAUDE_BIN` env, else the shared default).

    Caveat: `check_alerts` is a separate process from the daemon, so a
    `CLAUDE_BIN` set only in the supervisor's plist environment would not be
    visible here. The plist sets no such variable today; if that ever changes,
    this check must read it from the same place the daemon does.
    """
    claude_bin = os.environ.get("CLAUDE_BIN", DISPATCH_CLAUDE_BIN_DEFAULT)
    resolved = Path(claude_bin)
    try:
        target = resolved.resolve()
        exists = target.exists()
    except OSError:
        target = resolved
        exists = False
    breached = not exists
    body = "\n".join(
        [
            "## 觸發條件",
            "hourly dispatch 的 generator binary 無法解析到實際檔案。",
            f"- CLAUDE_BIN: {claude_bin}",
            f"- resolved: {target}",
            f"- exists: {exists}",
            "",
            "## 影響",
            "generator binary 不存在 → 每小時 dispatch `claude -p` binary-not-found 秒退、",
            "0 內容生成（舊版 alert 看不到，因 job exit 0）。這是 2026-06-22 整日脫班的源頭。",
            "",
            "## 建議行動",
            "1. 確認現行版本：ls -la ~/.local/bin/claude && claude --version",
            "2. 修 scripts/dispatch_supervisor/worker.py 的 CLAUDE_BIN 指向 always-current",
            "   symlink ~/.local/bin/claude（不要 pin 死版本），再重啟 daemon：",
            "   bash scripts/reload_dispatch_supervisor.sh --reason claude_bin_fix",
            "   （不要用 raw launchctl kickstart：wrapper 會寫 planned-restart marker，",
            "    否則這次部署會被誤報成非預期崩潰；wrapper 也會拒絕殺掉在飛的 worker。）",
            "   （alerts.py 的 DISPATCH_CLAUDE_BIN_DEFAULT 要一起改；只改一邊會被",
            "    test_alerts_default_matches_worker 擋下。）",
            "3. 驗證：env -i HOME=$HOME PATH=/usr/bin:/bin CLAUDE_CODE_OAUTH_TOKEN=… <bin> -p 'say AUTHOK'",
        ]
    )
    return {
        "id": "dispatch_binary_health",
        "breached": breached,
        "level": "critical" if breached else "info",
        "title": (f"Dispatch generator binary 不存在：{claude_bin}" if breached else "dispatch_binary_health ok"),
        "body": body if breached else "",
        "details": {"claude_bin": claude_bin, "resolved": str(target), "exists": exists},
    }


# Must stay identical to `scripts/dispatch_supervisor/codex_failover.py::_NVM_CODEX`,
# pinned mechanically by
# `tests/test_dispatch_binary_health_source.py::test_alerts_codex_default_matches_failover`.
# A literal for the same reason as DISPATCH_CLAUDE_BIN_DEFAULT above.
CODEX_FAILOVER_BIN_DEFAULT = "/Users/yhlai0911/.nvm/versions/node/v22.20.0/bin/codex"
CODEX_FAILOVER_PROBE_TIMEOUT_S = 20


def _resolve_codex_bin() -> str | None:
    """Same resolution order as `codex_failover.resolve_codex_bin()`."""
    for candidate in (os.environ.get("CODEX_BIN"), shutil.which("codex"), CODEX_FAILOVER_BIN_DEFAULT):
        if candidate and os.access(candidate, os.X_OK):
            return candidate
    return None


def _parse_codex_failover_ready_state(storage_dir: str, now: datetime) -> dict[str, Any]:
    """Can the Claude→Codex failover actually run, right now?

    2026-07-10. The failover (`scripts/dispatch_supervisor/codex_failover.py`) runs
    only when Claude returns quota_blocked or auth_blocked. That makes it a textbook
    silent guardian: on a healthy day it is a no-op that emits nothing, so "it is
    broken" and "it was never needed" look identical from outside. It sat orphaned
    by the 2026-07-04 cutover for six days — every quota outage silently dropped its
    hourly slot — and nothing signalled that, because a guardian that never runs
    also never fails.

    Its two hard prerequisites are exactly the ones that rot without a signal:

      - the codex binary path (a HARDCODED nvm path pinned to node v22.20.0 — one
        `nvm install` away from vanishing), and
      - a working node runtime behind that binary's `#!/usr/bin/env node` shebang.

    So probe both on the monitor's normal cadence: resolve the binary exactly the
    way the failover does, then actually run `codex --version` (~0.3s). Existence
    alone would not catch a broken node runtime, which is the failure the shebang
    makes possible.

    Severity is **warn, not critical** (per `.claude/rules/alert.md` taxonomy): the
    primary dispatch path is unaffected. What is lost is the backup that covers
    quota windows — real damage, but bounded and not user-facing.
    """
    codex_bin = _resolve_codex_bin()
    version = ""
    rc: int | None = None
    if codex_bin is None:
        reason = "binary_missing"
    else:
        try:
            probe = subprocess.run(
                [codex_bin, "--version"],
                capture_output=True, text=True, timeout=CODEX_FAILOVER_PROBE_TIMEOUT_S,
            )
            rc = probe.returncode
            version = (probe.stdout or "").strip()
            reason = "ok" if rc == 0 else "version_nonzero"
        except subprocess.TimeoutExpired:
            reason = "version_timeout"
        except OSError as exc:
            reason = f"exec_failed:{type(exc).__name__}"

    breached = reason != "ok"
    body = "\n".join(
        [
            "## 觸發條件",
            "Claude→Codex 失效轉移所需的 codex binary 無法執行。",
            f"- 解析到的 binary：{codex_bin or '(找不到)'}",
            f"- `codex --version` rc：{rc if rc is not None else '(未取得)'}",
            f"- 原因：{reason}",
            "",
            "## 影響",
            "這條備援只在 Claude 額度用盡或認證失效時才會走，壞掉時平常完全沒有症狀。"
            "要等到下一次額度中斷，整排每小時的派工才會再次被靜默丟掉"
            "（2026-07-04 cutover 後就這樣連丟六天）。主要派工路徑不受影響，故列 warn。",
            "",
            "## 建議行動",
            "1. `which codex && codex --version`（預期 codex-cli 0.144.1）",
            "2. 路徑消失多半是 nvm 換了 node 版本：",
            "   `npm install -g @openai/codex@latest --include=optional`",
            "3. 更新 `scripts/dispatch_supervisor/codex_failover.py::_NVM_CODEX`，",
            "   `alerts.py::CODEX_FAILOVER_BIN_DEFAULT` 必須同時改",
            "   （只改一邊會被 test_alerts_codex_default_matches_failover 擋下）。",
            "4. 不必等額度中斷就能驗整條路徑：用無害 prompt 呼叫",
            "   `run_codex_failover(reason='smoke', prompt_path=..., enabled=True)`。",
        ]
    )
    return {
        "id": "codex_failover_ready",
        "breached": breached,
        "level": "warn" if breached else "info",
        "title": (f"Codex 失效轉移不可用：{reason}" if breached else "codex_failover_ready ok"),
        "body": body if breached else "",
        "details": {"codex_bin": codex_bin, "reason": reason, "version": version, "rc": rc},
    }


# health_loop beats every 30s, and (since 2026-07-10) keeps beating while a
# worker is in flight — so a 10min warn is a ~20x margin over the cadence and a
# launchd restart (ThrottleInterval 60s + one beat) can never trip it.
DISPATCH_SUPERVISOR_HEARTBEAT_WARN_MINUTES = 10.0
DISPATCH_SUPERVISOR_HEARTBEAT_CRITICAL_MINUTES = 30.0

# Grace before an un-reloaded edit is called a breach: long enough that an agent
# mid-edit (or a `cp` that only touched mtime) never trips it, short enough that
# the next hourly check_alerts still catches a forgotten reload.
DISPATCH_SUPERVISOR_STALE_CODE_WARN_MINUTES = 20.0
DISPATCH_SUPERVISOR_STALE_CODE_CRITICAL_MINUTES = 120.0
DISPATCH_SUPERVISOR_SRC_DIR = Path(__file__).resolve().parents[3] / "scripts" / "dispatch_supervisor"


def _parse_dispatch_supervisor_stale_code_state(
    storage_dir: str,
    now: datetime,
    *,
    supervisor_dir: Path | None = None,
) -> dict[str, Any]:
    """Dead-man switch for "the fix was written but never went live" (2026-07-10).

    The supervisor daemon executes the copy of `scripts/dispatch_supervisor/*.py`
    it imported at boot. Editing those files changes nothing until someone runs
    `scripts/reload_dispatch_supervisor.sh`. Only `config/` is hot-reloaded per
    tick.

    On 2026-07-10 three separate fixes — quota no-retry, the gmail fire-request
    double-dispatch race, and the restart-alert noise suppression — were written,
    committed, and their tasks closed as "solved", while the running daemon kept
    executing code from hours earlier. Nobody noticed for over three hours,
    because a daemon running stale code looks exactly like a healthy one: fresh
    heartbeat, jobs completing, zero alerts. The rule "code written != deployed"
    was added to `.claude/rules/control-plane.md` that same morning and was
    violated three times before the day was out. Prose does not survive a handoff
    between agents; this does.

    Compares each source file's mtime against `supervisor_started_at`. Anything
    newer than the boot is, by definition, not the code that is running.
    """
    src_dir = supervisor_dir or DISPATCH_SUPERVISOR_SRC_DIR
    state_path = Path(storage_dir) / "ops" / "dispatch_state.json"

    snapshot: dict[str, Any] | None = None
    try:
        raw = load_json(state_path, None)
        if isinstance(raw, dict):
            snapshot = raw
    except (OSError, ValueError) as exc:
        warn("dispatch_supervisor_stale_code", "dispatch state unreadable", path=str(state_path), err=str(exc))

    boot = _parse_iso_datetime(snapshot.get("supervisor_started_at")) if snapshot else None

    stale: list[dict[str, Any]] = []
    if boot is not None and src_dir.is_dir():
        for src in sorted(src_dir.glob("*.py")):
            try:
                mtime = datetime.fromtimestamp(src.stat().st_mtime, tz=timezone.utc)
            except OSError as exc:
                # Raced a writer that unlinked/replaced the file between glob()
                # and stat(). Skipping is right — but a vanished daemon source
                # file is worth a word, not a shrug.
                warn(
                    "dispatch_supervisor_stale_code",
                    "supervisor source unreadable during scan",
                    path=str(src),
                    err=str(exc),
                )
                continue
            if mtime <= boot:
                continue
            stale.append({
                "file": src.name,
                "edited_at": mtime.isoformat(),
                "age_minutes": round((now - mtime).total_seconds() / 60.0, 2),
            })

    # An edit made seconds ago is an agent still working, not a forgotten deploy.
    settled = [s for s in stale if s["age_minutes"] > DISPATCH_SUPERVISOR_STALE_CODE_WARN_MINUTES]
    oldest = max((s["age_minutes"] for s in settled), default=0.0)

    # A beating daemon that has lost its boot time is not "nothing to compare" —
    # it is a daemon whose state was reset out from under it, and with `boot is
    # None` the loop above silently finds zero stale files. 2026-07-10 23:02: a
    # test wrote `_empty_state()` over the canonical file; `supervisor_started_at`
    # went null, `completions` emptied, `last_fire_at` cleared (re-firing an
    # already-completed slot) — and this condition reported `ok`. It went blind at
    # the exact moment it was needed. A file that exists and is beating, with no
    # boot time, is anomalous. An ABSENT file is a daemon that never ran, which
    # `dispatch_supervisor_heartbeat` owns; stay quiet there, don't double-alert.
    boot_lost = boot is None and snapshot is not None and bool(snapshot.get("last_heartbeat_at"))

    breached = bool(settled) or boot_lost
    is_critical = oldest > DISPATCH_SUPERVISOR_STALE_CODE_CRITICAL_MINUTES
    level = "critical" if is_critical else ("warn" if breached else "info")

    body = "\n".join(
        [
            "## 觸發條件",
            (
                "派工程式的狀態檔失去了開機時間 —— 它還在跳心跳，卻不記得自己何時啟動。"
                "通常代表狀態檔被覆寫過（例如某個測試寫到了正式檔案）。這種情況下無法"
                "判斷程式碼有沒有生效，所以直接告警。"
                if boot_lost
                else "派工程式的程式碼被改過，但那個常駐程式還在跑舊版 —— 改動沒有生效。"
            ),
            f"- daemon 開機時間: {boot.isoformat() if boot else '未知（狀態檔疑似被重置）'}",
            f"- 改了但沒生效的檔案: {[s['file'] for s in settled] or '無'}",
            f"- 最久的一個已經放置: {oldest} 分鐘",
            f"- 門檻: warn>{DISPATCH_SUPERVISOR_STALE_CODE_WARN_MINUTES}分 / critical>{DISPATCH_SUPERVISOR_STALE_CODE_CRITICAL_MINUTES}分",
            "",
            "## 影響",
            "常駐程式讀的是它啟動當下的程式碼。改了檔案不重載，等於沒改 —— 而且它看起來",
            "完全正常：心跳新鮮、任務照跑、零告警。2026-07-10 有三個修好的問題就這樣躺了",
            "三個多小時沒生效，沒有任何訊號。",
            "",
            "## 建議行動",
            "1. 確認沒有派工正在跑：uv run python -m scripts.dispatch_supervisor.cli status",
            "2. 重載：bash scripts/reload_dispatch_supervisor.sh --reason <為什麼>",
            "   （它會拒絕殺掉在飛的工作，也會避免這次重啟被誤報成崩潰）",
            "3. 若那些改動是刻意不上線的，把它們 revert 或說明，別讓磁碟與線上長期分岔。",
        ]
    )
    return {
        "id": "dispatch_supervisor_stale_code",
        "breached": breached,
        "level": level,
        "title": (
            "派工程式狀態檔失去開機時間（疑似被覆寫）"
            if boot_lost
            else "派工程式有改動沒生效（daemon 未重載）"
            if breached
            else "dispatch_supervisor_stale_code ok"
        ),
        "body": body if breached else "",
        "details": {
            "supervisor_started_at": boot.isoformat() if boot else None,
            "stale_files": settled,
            "unsettled_files": [s for s in stale if s not in settled],
            "oldest_age_minutes": oldest,
            "warn_minutes": DISPATCH_SUPERVISOR_STALE_CODE_WARN_MINUTES,
            "critical_minutes": DISPATCH_SUPERVISOR_STALE_CODE_CRITICAL_MINUTES,
        },
    }

GMAIL_POLL_STALE_WARN_HOURS = 2.0
GMAIL_POLL_STALE_CRITICAL_HOURS = 6.0
TELEGRAM_POLL_STALE_WARN_HOURS = 2.0
TELEGRAM_POLL_STALE_CRITICAL_HOURS = 6.0


def _parse_dispatch_supervisor_heartbeat_state(storage_dir: str, now: datetime) -> dict[str, Any]:
    """Dead-man switch for the dispatch-supervisor daemon loop (2026-07-10).

    `dispatch_state.json.last_heartbeat_at` is the daemon's own liveness proof,
    written by `health.health_loop()` every 30s. Nothing read it until now:
    `state.get_supervisor_age_seconds()` was written for "an external monitor"
    that never existed, and this module's only dispatch condition
    (`dispatch_binary_health`) checks the generator binary, not the daemon.

    Why it stayed unwired: until 2026-07-10 the heartbeat was stamped only by
    the scheduler tick, which awaits the worker to completion — so it froze for
    the whole dispatch (798s observed on a healthy fire) and any staleness
    alert would have false-fired on every normal hourly run. Moving the beat to
    the non-blocking health loop is what makes this switch safe to arm.

    `cron_review.py` already flags a daemon that has vanished from launchctl,
    but launchd's `KeepAlive` restarts a vanished process, so that case largely
    self-heals. The dangerous, previously-undetected case is a daemon whose
    process is alive while its loops are wedged — which only a stale heartbeat
    reveals.
    """
    state_path = Path(storage_dir) / "ops" / "dispatch_state.json"
    # A corrupt state file must degrade to "cannot prove alive" (→ breach), never
    # raise and take the whole alert report down with it.
    snapshot: dict[str, Any] | None = None
    try:
        raw = load_json(state_path, None)
        if isinstance(raw, dict):
            snapshot = raw
    except (OSError, ValueError) as exc:
        warn("dispatch_supervisor_heartbeat", "dispatch state unreadable", path=str(state_path), err=str(exc))

    beat = _parse_iso_datetime(snapshot.get("last_heartbeat_at")) if snapshot else None
    age_minutes = round((now - beat).total_seconds() / 60.0, 2) if beat else None
    supervisor_pid = snapshot.get("supervisor_pid") if snapshot else None
    running = bool(snapshot.get("current_job")) if snapshot else False

    # A missing file / never-written heartbeat is NOT a breach here: a running
    # daemon recreates `dispatch_state.json` within one 30s beat, so its absence
    # means the daemon is not running at all — which `cron_review.py` already
    # owns via its launchctl check. This switch's unique job is the case that
    # check cannot see: process alive, heartbeat stale. (Mirrors the
    # telegram_poll "not yet observed" convention, not gmail's missing→critical.)
    missing = age_minutes is None
    is_critical = (not missing) and age_minutes > DISPATCH_SUPERVISOR_HEARTBEAT_CRITICAL_MINUTES
    breached = (not missing) and age_minutes > DISPATCH_SUPERVISOR_HEARTBEAT_WARN_MINUTES
    level = "critical" if is_critical else ("warn" if breached else "info")

    body = "\n".join(
        [
            "## 觸發條件",
            "dispatch-supervisor 這個常駐派工程式，超過預期時間沒有回報「我還活著」。",
            f"- 狀態檔: {state_path}",
            f"- 上次回報距今: {age_minutes if age_minutes is not None else '檔案不存在/心跳未寫入'} 分鐘",
            f"- 門檻: warn>{DISPATCH_SUPERVISOR_HEARTBEAT_WARN_MINUTES}分 / critical>{DISPATCH_SUPERVISOR_HEARTBEAT_CRITICAL_MINUTES}分",
            f"- 程式編號 (supervisor_pid): {supervisor_pid}",
            f"- 目前是否正在派工: {'是' if running else '否'}",
            "",
            "## 影響",
            "這個程式負責每小時派出一個 agent 做研究、寫文章、跑實驗。它每 30 秒回報一次",
            "心跳；心跳停了代表它雖然還在，但內部已經卡死 —— 派工會整個停擺，而且不會有",
            "任何其他警報（launchctl 看得到行程還在，所以舊的檢查抓不到）。",
            "",
            "## 建議行動",
            "1. 確認行程還在不在：ps -p <supervisor_pid>",
            "2. 看它最後在做什麼：tail -50 ~/.volpred/logs/dispatch_supervisor.log",
            "3. 重啟：bash scripts/reload_dispatch_supervisor.sh --reason wedged_daemon",
            "   （wrapper 會寫 planned-restart marker 避免這次部署被誤報成崩潰，",
            "    並在 current_job 非 null 時拒絕執行，不會殺掉在飛的 worker。",
            "    真要殺一個卡死的 worker 才加 --force。）",
            "4. 讀全量狀態：uv run python -m scripts.dispatch_supervisor.cli status",
        ]
    )
    return {
        "id": "dispatch_supervisor_heartbeat",
        "breached": breached,
        "level": level,
        # 動態 age 只放 body/details，title 維持穩定 → sha256(level+title) 的 24h
        # dedup 才不會在持續 breach 時每小時洗版（沿用 gmail_poll_freshness 慣例）。
        "title": (
            "派工程式心跳停止（dispatch-supervisor 疑似卡死）"
            if breached
            else "dispatch_supervisor_heartbeat ok"
        ),
        "body": body if breached else "",
        "details": {
            "state_path": str(state_path),
            "age_minutes": age_minutes,
            "supervisor_pid": supervisor_pid,
            "current_job_running": running,
            "warn_minutes": DISPATCH_SUPERVISOR_HEARTBEAT_WARN_MINUTES,
            "critical_minutes": DISPATCH_SUPERVISOR_HEARTBEAT_CRITICAL_MINUTES,
        },
    }


def _parse_gmail_poll_freshness_state(storage_dir: str, now: datetime) -> dict[str, Any]:
    """Dead-man switch for the boss-email ingestion pipeline (2026-06-22).

    gmail-poll runs every 15min (24/7) via LaunchAgent and updates
    storage/ops/gmail_inbox_state.json on every successful poll (even when
    nothing new is queued). If that file's mtime falls behind, the poll is
    silently failing — e.g. the wrapper's alarm-timeout SIGALRM-kills every fire
    before completion (2026-06-22: 60s cap too tight for ~20 sequential IMAP
    fetches → state froze 2.5h, zero alerts). No active-window gate: the poll is
    expected to run around the clock.
    """
    state_path = Path(storage_dir) / "ops" / "gmail_inbox_state.json"
    age_hours: float | None = None
    if state_path.exists():
        try:
            mtime = datetime.fromtimestamp(state_path.stat().st_mtime, tz=timezone.utc)
            age_hours = round((now - mtime).total_seconds() / 3600.0, 2)
        except OSError:
            age_hours = None

    missing = age_hours is None
    is_critical = missing or age_hours > GMAIL_POLL_STALE_CRITICAL_HOURS
    breached = missing or age_hours > GMAIL_POLL_STALE_WARN_HOURS
    level = "critical" if is_critical else ("warn" if breached else "info")

    body = "\n".join(
        [
            "## 觸發條件",
            "gmail-poll 的 state 檔（boss email 自動 queue pipeline 的 liveness 訊號）過期。",
            f"- state 檔: {state_path}",
            f"- 距今: {age_hours if age_hours is not None else '檔案不存在/不可讀'} 小時",
            f"- 門檻: warn>{GMAIL_POLL_STALE_WARN_HOURS}h / critical>{GMAIL_POLL_STALE_CRITICAL_HOURS}h",
            "",
            "## 影響",
            "poll 每 15min 跑、每次成功都更新此檔；mtime 落後代表 poll 連續失敗（通常是",
            "wrapper alarm-timeout 把序列 IMAP fetch 砍掉，exit=142）。boss 回信不會被自動",
            "queue 成 task → 老闆指示 silent 漏接（違反 AI 全自動運營 mission）。",
            "",
            "## 建議行動",
            "1. 看 ~/.volpred/logs/gmail_poll.log 是否有 'Alarm clock' / exit=142（timeout）。",
            "2. 手動補 gap：uv run python scripts/gmail_inbox_poll.py --max 20（確認可完成）。",
            "3. 若反覆 timeout，放寬 ~/.volpred/bin/cron_gmail_poll.sh 的 perl alarm 秒數，",
            "   並考慮收斂 SINCE 窗 / 批次 IMAP fetch。詳 docs/error_log.md gmail-poll entry。",
        ]
    )
    return {
        "id": "gmail_poll_freshness",
        "breached": breached,
        "level": level,
        # title 穩定（不含動態 age）— 維持 sha256(level+title) 24h dedup 有效，避免持續
        # breach 時每小時洗版；動態 age 放 body/details（2026-06-23 dedup 修正）。
        # warn→critical 升級時 level 變→各寄一次（可接受），非每小時重寄。
        "title": (
            "gmail-poll 停擺（state 過期未更新）"
            if breached
            else "gmail_poll_freshness ok"
        ),
        "body": body if breached else "",
        "details": {
            "state_path": str(state_path),
            "age_hours": age_hours,
            "warn_hours": GMAIL_POLL_STALE_WARN_HOURS,
            "critical_hours": GMAIL_POLL_STALE_CRITICAL_HOURS,
        },
    }


def _parse_telegram_poll_freshness_state(storage_dir: str, now: datetime) -> dict[str, Any]:
    """Dead-man switch for Telegram inbound polling (2026-07-06).

    scripts/telegram_poll.py writes storage/ops/telegram_state.json:last_success_at
    after each successful getUpdates call, including empty polls. Missing
    last_success_at means an older state file has not observed the new heartbeat
    yet, so it stays informational to avoid a first-deploy false alarm.
    """
    state_path = Path(storage_dir) / "ops" / "telegram_state.json"
    age_hours: float | None = None
    last_success_raw: str | None = None
    read_error: str | None = None

    try:
        raw_state = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(raw_state, dict):
            read_error = f"expected dict, got {type(raw_state).__name__}"
            raw_state = {}
    except FileNotFoundError:
        read_error = "missing_state_file"
        raw_state = {}
    except (OSError, ValueError) as exc:
        read_error = str(exc)
        raw_state = {}

    candidate = raw_state.get("last_success_at")
    if isinstance(candidate, str):
        last_success_raw = candidate
    last_success_at = _parse_iso_datetime(last_success_raw)
    invalid_timestamp = bool(last_success_raw and last_success_at is None)
    if last_success_at is not None:
        age_hours = round((now - last_success_at).total_seconds() / 3600.0, 2)

    is_critical = age_hours is not None and age_hours > TELEGRAM_POLL_STALE_CRITICAL_HOURS
    breached = invalid_timestamp or (
        age_hours is not None and age_hours > TELEGRAM_POLL_STALE_WARN_HOURS
    )
    level = "critical" if is_critical else ("warn" if breached else "info")

    if invalid_timestamp:
        trigger_line = "Telegram 訊息輪詢的成功心跳時間無法解析。"
    elif age_hours is None:
        trigger_line = "Telegram 訊息輪詢尚未觀測到成功心跳。"
    else:
        trigger_line = f"Telegram 訊息輪詢 {age_hours} 小時沒有成功回應。"

    body = "\n".join(
        [
            "## 觸發條件",
            trigger_line,
            f"- state 檔: {state_path}",
            f"- last_success_at: {last_success_raw or '缺失'}",
            f"- 門檻: warn>{TELEGRAM_POLL_STALE_WARN_HOURS}h / critical>{TELEGRAM_POLL_STALE_CRITICAL_HOURS}h",
            "",
            "## 影響",
            "Telegram 即時訊息入口可能已經停擺；老闆傳來的訊息可能不會自動進任務池。",
            "",
            "## 建議行動",
            "1. 看 Telegram poller log 是否有 getUpdates failed 或 poll_pass error。",
            "2. 手動跑：uv run python scripts/telegram_poll.py --once。",
            "3. 若 token/API/network 正常但心跳仍不更新，檢查 LaunchAgent / daemon 是否還在跑。",
        ]
    )
    return {
        "id": "telegram_poll_freshness",
        "breached": breached,
        "level": level,
        "title": (
            "Telegram 訊息輪詢停擺（成功心跳過期）"
            if breached
            else "telegram_poll_freshness ok"
        ),
        "body": body if breached else "",
        "details": {
            "state_path": str(state_path),
            "last_success_at": last_success_raw,
            "age_hours": age_hours,
            "warn_hours": TELEGRAM_POLL_STALE_WARN_HOURS,
            "critical_hours": TELEGRAM_POLL_STALE_CRITICAL_HOURS,
            "read_error": read_error,
            "invalid_timestamp": invalid_timestamp,
        },
    }


def _parse_work_log_freshness_state(storage_dir: str, now: datetime) -> dict[str, Any]:
    """work_log latest timestamp >24h (or unreadable) → stale (warn).

    `storage/work_log.json` drives diversity rotation and handoff context. A
    stale log means completed Codex/Claude work is no longer visible to the
    dispatcher, which was the root of the 2026-06-28 rotation bug.
    """
    work_log_path = Path(storage_dir) / "work_log.json"
    newest: datetime | None = None
    entry_count = 0
    read_error: str | None = None

    try:
        raw = json.loads(work_log_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            read_error = f"expected list, got {type(raw).__name__}"
            raw = []
    except FileNotFoundError:
        read_error = "missing"
        raw = []
    except Exception as exc:
        read_error = f"{type(exc).__name__}: {str(exc)[:160]}"
        raw = []

    if isinstance(raw, list):
        entry_count = len(raw)
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            parsed = _parse_iso_datetime(entry.get("timestamp"))
            if parsed is not None and (newest is None or parsed > newest):
                newest = parsed

    age_hours: float | None = None
    if newest is not None:
        age_hours = round((now - newest).total_seconds() / 3600.0, 2)

    breached = read_error is not None or age_hours is None or age_hours > WORK_LOG_STALE_WARN_HOURS
    newest_text = newest.isoformat() if newest else "missing"
    body = "\n".join(
        [
            "## 觸發條件",
            f"storage/work_log.json 最新 entry 距今 > {WORK_LOG_STALE_WARN_HOURS}h，或檔案缺失/不可讀。",
            f"- 檔案: {_relative_repo_path(work_log_path)}",
            f"- entry_count: {entry_count}",
            f"- newest_timestamp: {newest_text}",
            f"- age_hours: {age_hours if age_hours is not None else 'missing'}",
            f"- read_error: {read_error or 'none'}",
            "",
            "## 影響",
            "work_log 是 dispatch diversity rotation 與 handoff 最近工作脈絡的輸入。它停更時，"
            "系統會誤以為某些 task_type 長時間沒做，導致重複派工或需要事後 backfill 才能修正。",
            "",
            "## 建議行動",
            "1. 先跑兜底：uv run python scripts/backfill_work_log_from_commits.py --apply。",
            "2. 查 Codex loop hook：tail -80 ~/.volpred/logs/codex_loop.log（找 [work-log-hook]）。",
            "3. 若 daily 兜底也沒跑，確認 config/runtime_schedules.json 的 codex_work_log_backfill job。",
        ]
    )
    return {
        "id": "work_log_freshness",
        "breached": breached,
        "level": "warn" if breached else "info",
        "title": (
            "work_log 停止更新（最新 entry 超過 24h）"
            if breached
            else "work_log_freshness ok"
        ),
        "body": body if breached else "",
        "details": {
            "path": str(work_log_path),
            "entry_count": entry_count,
            "newest_timestamp": newest_text,
            "age_hours": age_hours,
            "warn_hours": WORK_LOG_STALE_WARN_HOURS,
            "read_error": read_error,
        },
    }


def _parse_strategy_metrics_freshness_state(storage_dir: str) -> dict[str, Any]:
    """storage/strategy_metrics.json mtime > 26h (or missing) → stale (warn).

    Migrated 2026-06-24 from the disabled cloud platform-ops-patrol routine.
    """
    check = check_strategy_metrics_freshness(storage_dir)
    breached = check.get("status") == "stale"
    age = check.get("age_hours")
    metrics_path = _storage_root(storage_dir).joinpath("strategy_metrics.json")
    schedule = check.get("schedule") or "daily_update (canonical config cron)"
    last_expected = check.get("last_expected_refresh_utc") or "n/a"
    body = "\n".join(
        [
            "## 觸發條件",
            "strategy_metrics.json mtime 落後於最近一次「排定」的 daily_update 刷新（schedule-aware，",
            "非固定 26h；週日不誤報，因前次排定 fire 是週六）。",
            f"- 檔案: {_relative_repo_path(metrics_path)}",
            f"- exists: {check.get('exists')}",
            f"- age_hours: {age if age is not None else '不可讀/不存在'}",
            f"- 排程: {schedule}",
            f"- 最近排定刷新(UTC): {last_expected}",
            "",
            "## 影響",
            "此檔由 daily_update job 重寫；mtime 落後於排定刷新代表該 job 停擺，",
            "線上策略卡 metrics 與排序會用到過期數據（違反 Mission 第 4 條：策略表現公正）。",
            "",
            "## 建議行動",
            "1. 查刷新 job log：tail -20 storage/logs/cron/daily_update.log。",
            "2. 確認排程是否該跑：uv run volpred ops schedule-due daily_update。",
            "3. 若確為 miss，手動補：VOLPRED_ALLOW_OFFSCHEDULE_DAILY_UPDATE=1 ~/.volpred/bin/cron_daily_update.sh。",
            "4. 確認 cron schedule 仍 active：config/runtime_schedules.json。",
        ]
    )
    return {
        "id": "strategy_metrics_freshness",
        "breached": breached,
        "level": "warn" if breached else "info",
        "title": (
            "策略 metrics 過期（strategy_metrics.json 停止更新）"
            if breached
            else "strategy_metrics_freshness ok"
        ),
        "body": body if breached else "",
        "details": check,
    }


def _parse_paper_trading_gaps_state(storage_dir: str) -> dict[str, Any]:
    """Per strategy, >2 nulls in last 3 paper_trading entries → gap alert (warn).

    Migrated 2026-06-24 from the disabled cloud platform-ops-patrol routine.
    """
    check = check_paper_trading_gaps(storage_dir)
    gap_strategies = check.get("gap_strategies", [])
    breached = check.get("status") == "gap"
    gap_lines = [
        f"- {g.get('strategy')}: {g.get('null_count')} nulls"
        for g in gap_strategies
    ] or ["- (none)"]
    body = "\n".join(
        [
            "## 觸發條件",
            f"某策略最後 3 筆 paper_trading entries 中 > {PAPER_TRADING_GAP_NULL_THRESHOLD} 筆 "
            "portfolio_return 為 null。",
            *gap_lines,
            f"- 檔案: {_relative_repo_path(_storage_root(storage_dir).joinpath('paper_trading.json'))}",
            "",
            "## 影響",
            "1 個 trailing null 是週末結算 lag（正常），>2 代表該策略 forward-tracking "
            "/ recalc pipeline 卡住、績效曲線停更（違反 Mission 第 4 條：策略表現公正、第 2 條：可復現）。",
            "",
            "## 建議行動",
            "1. 不要手補 JSON（違反『永遠修流程不修資料』）— 讓 forward tracking / recalc 自然修正。",
            "2. 查 recalc job：tail -20 storage/logs/cron/*.log；確認 paper_trading 更新 job 有 fire。",
            "3. 手動觸發 recalc（對應 CLI），驗證 null 被填回。",
        ]
    )
    return {
        "id": "paper_trading_gaps",
        "breached": breached,
        "level": "warn" if breached else "info",
        # title 穩定（不含動態策略名/數量）— 維持 24h dedup 有效，明細放 body/details。
        "title": (
            "Paper trading 績效斷層（策略 forward-tracking 停更）"
            if breached
            else "paper_trading_gaps ok"
        ),
        "body": body if breached else "",
        "details": check,
    }


def _parse_disk_usage_state(storage_dir: str) -> dict[str, Any]:
    """Disk usage > 85% AND free < 50GB → alert (warn, 雙條件避免大碟誤報).

    Migrated 2026-06-24 from the disabled cloud platform-ops-patrol routine.
    2026-06-24 改雙條件：純百分比對大碟（926GB）在 85% 時仍有上百 GB free 卻誤報。
    """
    check = check_disk_usage(storage_dir)
    pct = check.get("pct")
    free_gb = check.get("free_gb")
    breached = check.get("status") == "alert"
    body = "\n".join(
        [
            "## 觸發條件",
            f"磁碟使用率 > {DISK_USAGE_ALERT_PCT}% 且剩餘空間 < {DISK_USAGE_MIN_FREE_GB}GB（雙條件）。",
            f"- 使用率: {pct if pct is not None else '不可讀'}%",
            f"- 剩餘空間: {free_gb if free_gb is not None else '不可讀'}GB",
            f"- 門檻: 使用率 > {DISK_USAGE_ALERT_PCT}% 且 free < {DISK_USAGE_MIN_FREE_GB}GB",
            "",
            "## 影響",
            "磁碟接近滿載 → experiment 輸出 / log / sync 寫入可能失敗，造成 silent data loss "
            "或 pipeline 中斷（影響全 Mission：研究/論文/平台運營皆需可寫盤）。",
            "",
            "## 建議行動",
            "1. 查大檔：du -sh storage/logs/* storage/ops/* | sort -h | tail -20。",
            "2. 清過期 log / 暫存（不刪 storage/ 的 canonical 資料）。",
            "3. 評估 knowledge.json / log rotation（memory-health skill）。",
        ]
    )
    return {
        "id": "disk_usage",
        "breached": breached,
        "level": "warn" if breached else "info",
        # title 穩定（不含動態值）— 維持 24h dedup 有效，動態值放 body/details。
        "title": (
            f"磁碟空間不足（使用率 > {DISK_USAGE_ALERT_PCT}% 且剩餘 < {DISK_USAGE_MIN_FREE_GB}GB）"
            if breached
            else "disk_usage ok"
        ),
        "body": body if breached else "",
        "details": check,
    }


def _parse_content_quality_state(
    storage_dir: str, now: datetime
) -> dict[str, Any]:
    """Content-quality patrol breach (2026-06-24 meta-fix).

    Aggregates `content_quality_snapshot` into the alert chain. Breach
    severity follows the worst sub-check:

    - `duplicate` daily digest → warn (today's mile_f3e389cf dup case)
    - `digest_prefix_duplicates_section_header` title finding → warn
    - rhythm `burst` or `drought` → warn
    - any other title format issue → info-level note (no breach)

    Body lists the breached sub-checks plus pointers; details carries the
    full snapshot for `ops_dashboard` consumers.
    """
    # Frontend probe is a network call — opt in only on the hourly alert path
    # (check_alerts sets VOLPRED_FRONTEND_PROBE=1); off by default so tests and
    # the dashboard stay offline/deterministic.
    probe_frontend = os.environ.get("VOLPRED_FRONTEND_PROBE", "").strip().lower() in ("1", "true", "yes", "on")
    snapshot = content_quality_snapshot(storage_dir, now=now, probe_frontend=probe_frontend)
    digest = snapshot["daily_digest_uniqueness"]
    rhythm = snapshot["publish_rhythm"]
    title = snapshot["title_format"]
    arc = snapshot.get("arc_diversity", {})
    release = snapshot.get("release_deadlock", {})
    frontend = snapshot.get("frontend_render", {})
    completeness = snapshot.get("content_completeness", {})
    lazypack_gap = bool(completeness.get("lazypack", {}).get("below_threshold"))

    breached_subchecks: list[str] = []
    critical_subchecks: list[str] = []
    if digest["status"] == "duplicate":
        breached_subchecks.append("daily_digest_uniqueness")
    if rhythm["status"] in ("burst", "drought"):
        breached_subchecks.append(f"publish_rhythm:{rhythm['status']}")
    if any(
        f["issue"] == "digest_prefix_duplicates_section_header"
        for f in title["findings"]
    ):
        breached_subchecks.append("title_format:digest_prefix")
    # 2026-06-29 patrol completion: 4 new checks wired into the breach decision.
    if release.get("status") == "deadlock":
        breached_subchecks.append("release_deadlock")
        critical_subchecks.append("release_deadlock")
    if frontend.get("status") == "error":
        breached_subchecks.append("frontend_render")
        critical_subchecks.append("frontend_render")
    if arc.get("status") == "concentrated":
        breached_subchecks.append("arc_diversity")
    if lazypack_gap:
        breached_subchecks.append("content_completeness:lazypack_gap")
    # Missing-chart/source content_completeness is a heuristic (frontend-rendered
    # charts can't be seen from feed content) → surfaced as context, NOT an
    # independent breach driver. Lazypack coverage is deterministic because it uses
    # the same section parser as the publish gate, so low coverage is a WARN breach.

    breached = bool(breached_subchecks)

    lines = ["## 觸發條件"]
    if digest["status"] == "duplicate":
        ids = ", ".join(x.get("id", "?") for x in digest["items"])
        lines.append(
            f"- daily_digest: 同日（TPE {digest['date_tpe']}）published "
            f"{digest['published_count']} 篇 `{DIGEST_TITLE_PREFIX}`: {ids}"
        )
    if rhythm["status"] == "burst":
        lines.append(
            f"- publish_rhythm: burst — {len(rhythm['burst_pairs'])} 對 "
            f"間距 < {rhythm['burst_gap_threshold_min']}min（最新間距列表："
            f"{rhythm['gaps_min_newest_first'][:3]}）"
        )
    if rhythm["status"] == "drought":
        lines.append(
            f"- publish_rhythm: drought — 距最新發文 "
            f"{rhythm['age_since_newest_min']}min "
            f"> {rhythm['drought_gap_threshold_hours']}h 門檻"
            f"（作用窗 TPE hour={rhythm['tpe_hour']}）"
        )
    if any(
        f["issue"] == "digest_prefix_duplicates_section_header"
        for f in title["findings"]
    ):
        dup_titles = [
            f for f in title["findings"]
            if f["issue"] == "digest_prefix_duplicates_section_header"
        ]
        lines.append(
            f"- title_format: {len(dup_titles)} 篇 digest title 重複前端區塊"
            "標頭 `每日精選導讀`"
        )
    if release.get("status") == "deadlock":
        lines.append(
            f"- release_deadlock: publication_candidates 來源枯竭 "
            f"(total={release.get('total')}, {release.get('candidate_counts')}) "
            "→ 釋出池上游將斷貨"
        )
    if frontend.get("status") == "error":
        lines.append(
            f"- frontend_render: 線上首頁異常 (http={frontend.get('http_status')}, "
            f"react_error={frontend.get('react_error')}, url={frontend.get('url')})"
        )
    if arc.get("status") == "concentrated":
        lines.append(
            f"- arc_diversity: 近 {arc.get('sample')} 篇最高 arc `{arc.get('top_axis')}` "
            f"佔 {arc.get('top_share')} > {arc.get('threshold')} 門檻（主題過度集中）"
        )
    if completeness.get("status") == "incomplete":
        miss = completeness.get("findings", [])
        lines.append(
            f"- (context) content_completeness: {len(miss)}/{completeness.get('scanned')} "
            "篇缺圖表或來源 marker（heuristic，可能含 frontend-rendered chart 誤判，供人工複查）"
        )
    if lazypack_gap:
        lz = completeness.get("lazypack", {})
        examples = ", ".join(x.get("id", "?") for x in lz.get("missing_examples", [])[:5])
        lines.append(
            f"- content_completeness:lazypack_gap — general 文章懶人包覆蓋 "
            f"{lz.get('coverage')} < {lz.get('threshold')} "
            f"({lz.get('with_lazypack')}/{lz.get('general_total')}); "
            f"待回補 examples: {examples or 'n/a'}"
        )
    if not breached:
        lines.append("- (none)")

    lines.extend(
        [
            "",
            "## 影響",
            "內容品質直接打 Mission 第 1 條（內容）+ 第 5 條（流量）。Boss 在 "
            "2026-06-24 一日內人工 spot 4 個內容問題；此 patrol 補上系統主動巡檢層，"
            "未來這類問題不再倚賴人工發現。",
            "",
            "## 建議行動（主線程 auto-remediation）",
            "1. `daily_digest_uniqueness=duplicate` → 檢視 `storage/ops/"
            "content_quality_report.json` items，挑 1 篇 retract："
            "`uv run volpred ops unpublish --mile-id <id>`；同時排查為何"
            " enqueue_daily_digest.py 既有冪等被繞過（race / 雙源 dispatcher）。",
            "2. `publish_rhythm=burst` → 派工節流，下一輪 hourly 跳過 reader-facing；"
            "查 dispatch log 是否雙 session 同時 fire。",
            "3. `publish_rhythm=drought` → 立即 `release-pool-by-settings` 或派 "
            "fresh-arc daily_article 補位；同時查 release deadlock "
            "(`docs/refactor_plan_release_layer_deadlock.md`)。",
            "4. `title_format:digest_prefix` → 前端 header 與 title 擇一移除前綴；"
            "前端在 `frontend-v2-fix/src/app/page.tsx` + `digest/[id]/page.tsx`。",
            "5. `content_completeness:lazypack_gap` → 針對 missing_examples 走 "
            "`lazypack-infographic`/NotebookLM 生圖，append `## 懶人包圖組` 後 "
            "用正式 publish/update 流程同步；新 general 文會被 publish gate 阻擋。",
        ]
    )

    body = plainify_boss_text("\n".join(lines))
    plain_subchecks = [plainify_boss_text(item) for item in breached_subchecks]
    return {
        "id": "content_quality",
        "breached": breached,
        "level": "critical" if critical_subchecks else ("warn" if breached else "info"),
        "title": (
            "內容品質巡檢：" + " / ".join(plain_subchecks)
            if breached
            else "內容品質巡檢正常"
        ),
        "body": body if breached else "",
        "details": snapshot,
    }


def _event_receipt_deadlines(storage_dir: str) -> dict[str, datetime]:
    ledger_root = _ops_path(storage_dir, "event_ledger")
    deadlines: dict[str, datetime] = {}
    if not ledger_root.exists():
        return deadlines

    for path in sorted(ledger_root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - alert parser must stay non-fatal
            warn("alerts", "event ledger read failed; skipping", path=str(path), err=str(exc))
            continue
        if not isinstance(payload, dict):
            continue
        task_id = str(payload.get("task_id") or "").strip()
        deadline = _parse_iso_datetime(payload.get("deadline"))
        if not task_id or deadline is None:
            continue
        current = deadlines.get(task_id)
        if current is None or deadline < current:
            deadlines[task_id] = deadline
    return deadlines


def _is_event_receipt_task(task: dict[str, Any], *, ledger_task_ids: set[str]) -> bool:
    task_id = str(task.get("id") or "")
    if task_id in ledger_task_ids:
        return True

    payload = task.get("payload")
    if isinstance(payload, dict) and (
        payload.get("event_key") or payload.get("event_job_id") or payload.get("event_type")
    ):
        return True

    title = str(task.get("title") or "").lower()
    return title.startswith("event article:") or "event article" in title


def _event_receipt_deadline(task: dict[str, Any], deadlines: dict[str, datetime]) -> datetime | None:
    task_id = str(task.get("id") or "").strip()
    direct = _parse_iso_datetime(task.get("deadline"))
    if direct is not None:
        return direct

    payload = task.get("payload")
    if isinstance(payload, dict):
        for key in ("deadline", "event_deadline"):
            parsed = _parse_iso_datetime(payload.get(key))
            if parsed is not None:
                return parsed

    return deadlines.get(task_id)


def _parse_event_receipt_state(storage_dir: str, now: datetime) -> dict[str, Any]:
    """Warn on event receipts stuck after claim or past event deadline.

    This folds the detector into the existing check_alerts owner instead of
    adding another watchdog. It catches the two 2026-07-05 incident classes:
    a claimed FOMC T+0 zombie and queued NFP tasks whose deadline passed.
    """
    tasks_root = _ops_path(storage_dir, "tasks")
    deadlines = _event_receipt_deadlines(storage_dir)
    ledger_task_ids = set(deadlines)
    stale: list[dict[str, Any]] = []
    checked = 0
    read_errors: list[str] = []

    if tasks_root.exists():
        for path in sorted(tasks_root.glob("*.json")):
            try:
                task = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001 - alert parser must stay non-fatal
                warn(
                    "event_receipt_parse",
                    "task receipt json decode failed",
                    path=_relative_repo_path(path),
                    err=f"{type(exc).__name__}: {exc}",
                )
                read_errors.append(f"{_relative_repo_path(path)}: {type(exc).__name__}")
                continue
            if not isinstance(task, dict):
                continue
            if not _is_event_receipt_task(task, ledger_task_ids=ledger_task_ids):
                continue
            checked += 1

            status = str(task.get("status") or "").strip().lower()
            if status in EVENT_RECEIPT_TERMINAL_STATUSES:
                continue

            task_id = str(task.get("id") or path.stem)
            title = str(task.get("title") or task_id)
            claimed_at = _parse_iso_datetime(task.get("claimed_at")) or _parse_iso_datetime(
                task.get("started_at")
            )
            deadline = _event_receipt_deadline(task, deadlines)

            reasons: list[str] = []
            age_hours: float | None = None
            if status in EVENT_RECEIPT_CLAIMED_STATUSES and claimed_at is not None:
                age_hours = round((now - claimed_at).total_seconds() / 3600.0, 2)
                if now - claimed_at > EVENT_RECEIPT_CLAIMED_WARN:
                    reasons.append("claimed_over_24h")

            if status in EVENT_RECEIPT_QUEUE_STATUSES and deadline is not None and now > deadline:
                reasons.append("queued_past_deadline")

            if reasons:
                overdue_hours = (
                    round((now - deadline).total_seconds() / 3600.0, 2)
                    if deadline is not None and now > deadline
                    else None
                )
                stale.append(
                    {
                        "task_id": task_id,
                        "status": status,
                        "title": title,
                        "reasons": reasons,
                        "claimed_at": claimed_at.isoformat() if claimed_at else None,
                        "claimed_age_hours": age_hours,
                        "deadline": deadline.isoformat() if deadline else None,
                        "deadline_overdue_hours": overdue_hours,
                        "path": _relative_repo_path(path),
                    }
                )

    breached = bool(stale)
    reason_names = sorted({reason for item in stale for reason in item["reasons"]})
    lines = [
        "## 觸發條件",
        "掃描 `storage/ops/tasks/*.json` event receipts；claimed/running 超過 "
        "24h 或 queued/blocked/awaiting_approval 超過 event deadline 即 warn。",
        f"- checked_event_receipts: {checked}",
        f"- stale_count: {len(stale)}",
    ]
    for item in stale[:10]:
        lines.append(
            f"- {item['task_id']} [{item['status']}]: {', '.join(item['reasons'])}; "
            f"claimed_age_h={item['claimed_age_hours']}; "
            f"deadline_overdue_h={item['deadline_overdue_hours']}; "
            f"title={item['title']}"
        )
    if len(stale) > 10:
        lines.append(f"- ... {len(stale) - 10} more")
    if read_errors:
        lines.append(f"- read_errors: {len(read_errors)}")

    lines.extend(
        [
            "",
            "## 影響",
            "事件型文章/任務有時效性；claimed zombie 會佔用 ownership，queued "
            "past-deadline 會讓市場事件過期後仍留在任務池，造成 dispatch 噪音與錯過發文窗口。",
            "",
            "## 建議行動",
            "1. 若仍有時效價值：立即接手完成或重派。",
            "2. 若已過時：用正式 task close / expire 流程關閉，不要手改 JSON。",
            "3. 檢查 event_jobs / event_ledger 是否缺 deadline 或 close path。",
        ]
    )

    return {
        "id": "event_receipt_watchdog",
        "breached": breached,
        "level": "warn" if breached else "info",
        "title": (
            "Event receipt watchdog stale (" + " / ".join(reason_names) + ")"
            if breached
            else "event_receipt_watchdog ok"
        ),
        "body": "\n".join(lines) if breached else "",
        "details": {
            "checked_event_receipts": checked,
            "stale_count": len(stale),
            "stale": stale,
            "read_errors": read_errors,
            "claimed_warn_hours": EVENT_RECEIPT_CLAIMED_WARN.total_seconds() / 3600.0,
        },
    }


def _parse_loop_health_state(storage_dir: str, now: datetime) -> dict[str, Any]:
    """Loop-health regression breach (2026-06-29 loop-engineering layer).

    Aggregates `loop_health_snapshot` — "is the autonomous loop *improving*?" —
    into the alert chain. This is the fast loop; the slow loop that mines
    cross-session patterns and proposes fixes is `scripts/dreaming_review.py`.

    Breach drivers are deliberately scoped to signals NOT already owned by
    another condition, to avoid duplicate alerting:
    - `task_outcome` degrading/warn (recent terminal success share dropping)
    - `correction_trend` worsening (boss/self catching more content errors)
    - `first_pass_success` degrading/warn — only when coverage is sufficient
      (low_coverage self-suppresses; it's info, never a breach)

    `error_recurrence` is intentionally NOT a breach driver here: real-time
    cron-exit failures are owned by `host_cron_fail`, and cross-run three-strike
    escalation is owned by the dreaming job. It is still shown in the body as
    context and carried in details for the dashboard + dreaming consumers.

    Title lists the breached metric NAMES (stable across runs) so the
    sha256(level+title) dedup key is stable; numbers live in the body.
    """
    snapshot = loop_health_snapshot(storage_dir, now=now)
    first_pass = snapshot["first_pass_success"]
    task_outcome = snapshot["task_outcome"]
    recurrence = snapshot["error_recurrence"]
    correction = snapshot["correction_trend"]

    breached_metrics: list[str] = []
    if task_outcome.get("status") in ("warn", "degrading"):
        breached_metrics.append("task_outcome")
    if correction.get("status") == "warn":
        breached_metrics.append("correction_trend")
    if first_pass.get("status") in ("warn", "degrading"):
        breached_metrics.append("first_pass_success")

    breached = bool(breached_metrics)

    lines = ["## 觸發條件"]
    if "task_outcome" in breached_metrics:
        lines.append(
            f"- task_outcome: 近 {task_outcome.get('window_days')}d 任務終態成功率 "
            f"{task_outcome.get('success_rate')}（success={task_outcome.get('success')} "
            f"/ fail={task_outcome.get('fail')} / blocked={task_outcome.get('blocked')}）"
            f"→ {task_outcome.get('status')}"
        )
    if "correction_trend" in breached_metrics:
        lines.append(
            f"- correction_trend: 近 {correction.get('weeks')} 週糾正事件上升 "
            f"(weekly recent-first {correction.get('weekly_counts_recent_first')}, "
            f"slope={correction.get('slope_per_week')}/wk)"
        )
    if "first_pass_success" in breached_metrics:
        lines.append(
            f"- first_pass_success: 一次完成率 {first_pass.get('first_pass_rate')} "
            f"(traced={first_pass.get('traced')}, coverage={first_pass.get('coverage')}) "
            f"→ {first_pass.get('status')}"
        )
    if not breached:
        lines.append("- (none — loop-health ok)")

    # error_recurrence context (informational, never the sole breach driver here).
    top = recurrence.get("top_recurring") or []
    if top:
        worst = top[0]
        lines.append(
            f"- (context) error_recurrence={recurrence.get('status')}; 最高重複簽章 "
            f"`{worst.get('signature')}` ×{worst.get('count')}"
            f"{'（已知自癒）' if worst.get('known') else ''} — cron-exit 即時告警由 "
            "host_cron_fail 負責，跨 run 升級由 dreaming 負責。"
        )

    lines.extend(
        [
            "",
            "## 影響",
            "Loop-health 衡量「系統有沒有在變好」（一次完成率 / 任務成功率 / 同類錯誤重複 "
            "/ 糾正趨勢）。退化代表自主迴圈品質下滑，會增加老闆人工介入、拖慢內容與研究產出"
            "（Mission #2 研究 + #1 內容 + #4 運營）。",
            "",
            "## 建議行動",
            "1. `task_outcome` 退化 → 查 `storage/work_log.json` 近 14d failed/blocked "
            "task 的共同根因（資料源死 / agent brief 不清 / 重複 dispatch）。",
            "2. `correction_trend` 上升 → 內容糾正變多，查 `content_correction_report.json` "
            "HIGH/MEDIUM 命中，補 publish 前 gate 或退回相關文章。",
            "3. `first_pass_success` 退化 → 任務反覆重試，查 dispatch brief 品質。",
            "4. 完整跨 session 模式分析 → `uv run volpred ops dreaming-run`（slow loop，"
            "產 findings + proposal，治理檔只建議不自動改）。",
        ]
    )

    body = "\n".join(lines)
    return {
        "id": "loop_health",
        "breached": breached,
        "level": "warn" if breached else "info",
        "title": (
            "Loop-health 退化（" + " / ".join(breached_metrics) + "）"
            if breached
            else "loop_health ok"
        ),
        "body": body if breached else "",
        "details": snapshot,
    }


def _parse_cluster_cap_drift_state(storage_dir: str) -> dict[str, Any]:
    """Topic-cluster 30d overshoot vs hard cap → drift alert (2026-06-29 added).

    Why: K1333 publish attempt (hourly-00 fire) discovered vix cluster 92/15 =
    6.1x overshoot and spy 83/10 = 8.3x. Cluster cooldown gate blocks new
    `general`/`research` publishes, but timely event/trending publishes bypass
    the gate — so cap can drift far above ceiling without anyone noticing.

    Severity ladder (worst overshoot wins, aligned with publisher soft cap
    SOFT_CAP_MULTIPLIER=2.5 → publisher blocks even timely types at 2.5x):
    - ratio >= 2.5x → critical (soft cap hit, even timely types now blocked)
    - ratio >= 1.5x → warn (release pacing drifting toward soft cap)
    - ratio >= 1x → info (at hard cap, blocking discretionary publishes —
      expected; timely still allowed up to soft cap)
    - else → ok

    Reads cluster state via `volpred.topic_clusters.recent_cluster_counts`.
    """
    try:
        from volpred.topic_clusters import (
            CLUSTER_HARD_CAPS,
            SOFT_CAP_MULTIPLIER,
            cluster_cap,
            cluster_soft_cap,
            recent_cluster_counts,
        )
    except Exception as exc:
        return {
            "id": "cluster_cap_drift",
            "breached": False,
            "level": "info",
            "title": "cluster_cap_drift unavailable",
            "body": "",
            "details": {"import_error": str(exc)},
        }

    counts, total = recent_cluster_counts(days=30)
    rows: list[dict[str, Any]] = []
    for cluster_name in CLUSTER_HARD_CAPS:
        count = counts.get(cluster_name, 0)
        cap = cluster_cap(cluster_name)
        soft_cap = cluster_soft_cap(cluster_name)
        ratio = (count / cap) if cap else 0.0
        rows.append({
            "cluster": cluster_name,
            "count": count,
            "cap": cap,
            "soft_cap": soft_cap,
            "overshoot_ratio": round(ratio, 2),
            "share": round((count / total) if total else 0.0, 4),
        })
    rows.sort(key=lambda r: -r["overshoot_ratio"])
    worst_ratio = rows[0]["overshoot_ratio"] if rows else 0.0

    if worst_ratio >= SOFT_CAP_MULTIPLIER:
        level = "critical"
        breached = True
    elif worst_ratio >= 1.5:
        level = "warn"
        breached = True
    else:
        level = "info"
        breached = False

    overshoot_rows = [r for r in rows if r["overshoot_ratio"] >= 1.5]

    if breached:
        title = (
            f"Topic-cluster 30d 嚴重 overshoot（worst {worst_ratio:.1f}x cap）"
        )
        lines = [
            "## 觸發條件",
            f"30d feed items = {total}；soft cap = hard×{SOFT_CAP_MULTIPLIER}（"
            f"timely / topic-bound types 自 2026-06-29 起亦受此擋）。ratio ≥ 1.5x"
            "→ warn；≥ 2.5x → critical（soft cap hit）。",
        ]
        for r in overshoot_rows[:5]:
            lines.append(
                f"- {r['cluster']}: {r['count']}/{r['cap']} "
                f"(soft_cap={r['soft_cap']}) = "
                f"{r['overshoot_ratio']:.1f}x hard, share={r['share']:.1%}"
            )
        lines.extend([
            "",
            "## 影響",
            "Publisher 2026-06-29 已對 timely 類型加 soft cap (hard×2.5)。soft "
            "cap 觸及後即便 trending_repost / event_article / member_qa / daily_* "
            "也會被擋，除非 caller 顯式 `details['cluster_waiver']='<reason>'`。"
            "此狀態：(a) Mission 第 1 條（文章品質）+ 第 5 條（曝光多樣性）已啟動"
            "保護；(b) 真實事件（FOMC / CPI）可走 waiver 不受影響；(c) discretionary "
            "K-experiment general 文章重獲 release slot。",
            "",
            "## 建議行動",
            "1. 自動：dispatcher 下輪自動 rotate 非熱門 cluster K（research backlog "
            "已 184+ uncovered，refill_task_pool 永不缺源）。",
            "2. 觀察：`tail -50 storage/logs/dedup_decisions.jsonl | grep "
            "block_cluster_soft_cap` 看哪些 timely 被擋；若是真實事件 → "
            "在 caller 加 cluster_waiver。",
            "3. 評估 `CLUSTER_HARD_CAPS`（vix=15 / spy=10）是否仍合理；若 timely "
            "已合理消耗，重新校準 hard cap 或細分 sub-cluster。",
        ])
        body = "\n".join(lines)
    else:
        title = "cluster_cap_drift ok"
        body = ""

    return {
        "id": "cluster_cap_drift",
        "breached": breached,
        "level": level,
        "title": title,
        "body": body,
        "details": {
            "total_30d": total,
            "rows": rows,
            "worst_overshoot_ratio": worst_ratio,
        },
    }


def _parse_series_registry_state(storage_dir: str) -> dict[str, Any]:
    """Article-series registry drift → warn (2026-07-06 added).

    Why: the 迷思實驗室 incident (wrong name / under-scope / bogus EP numbers /
    wrong dedup keeper — 4 mistakes same root cause) happened because series
    identity was IMPLICIT (title conventions + internal codenames + Telegram
    chat), so every session re-derived it from titles and guessed wrong. Fix =
    a machine-readable registry `config/article_series.json` as single source of
    truth + `scripts/series_registry.py` audit. This condition runs that audit
    hourly so drift surfaces automatically: a registered member that lost its
    prefix, an excluded dup that became visible again, an orphan-branded article
    (prefix but unregistered), or a digest title that double-headers the masthead.

    Warn-only — series branding is a content-quality issue, not an outage.
    """
    try:
        import importlib.util
        repo_root = Path(__file__).resolve().parents[3]
        spec = importlib.util.spec_from_file_location(
            "_series_registry_audit", str(repo_root / "scripts" / "series_registry.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # Read the feed through `storage_dir`, not the module's hardcoded production
        # path. `mod._load_feed()` ignored the argument this condition is given, so
        # an isolated fixture still audited the real feed and the breach count moved
        # with whatever happened to be published — the 2026-07-10 CI run went red on
        # exactly that (green on the dev mac, 4 breaches on the runner).
        feed_path = Path(storage_dir) / "reports" / "feed.json"
        feed = json.loads(feed_path.read_text(encoding="utf-8"))
        findings = mod.audit(mod._load_registry(), feed)
    except Exception as exc:
        return {
            "id": "series_registry", "breached": False, "level": "info",
            "title": "series_registry audit unavailable", "body": "",
            "details": {"error": str(exc)},
        }
    if not findings:
        return {
            "id": "series_registry", "breached": False, "level": "info",
            "title": "series_registry ok", "body": "", "details": {"drift": 0},
        }
    kinds: dict[str, int] = {}
    for f in findings:
        kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
    lines = [
        "## 觸發條件",
        f"config/article_series.json 登記的系列與 feed.json 有 {len(findings)} 處漂移：",
    ]
    for f in findings[:10]:
        lines.append(f"- [{f['kind']}] {f['series']}/{f.get('id')}: {f['detail']}")
    lines += [
        "",
        "## 影響",
        "系列品牌（迷思實驗室｜等）是讀者辨識與回訪的錨（Mission #1 內容 + #5 流量）；"
        "member 掉前綴／下架的 dup 重新可見／orphan brand 會讓系列看起來散亂或重複。",
        "",
        "## 系統已自動可修",
        "主線程收到後：`uv run python scripts/series_registry.py --apply` 自動補回缺失前綴；"
        "`dup_still_visible` → 設該文 status='unpublished'（非 draft）；`orphan_brand` → "
        "把該文加進 registry 或改標題。根因＋schema 見 config/article_series.json + "
        "docs/error_log.md 2026-07-06 series 條目。",
    ]
    return {
        "id": "series_registry", "breached": True, "level": "warn",
        "title": f"文章系列品牌漂移（{len(findings)} 處）",
        "body": "\n".join(lines),
        "details": {"drift": len(findings), "kinds": kinds, "findings": findings[:20]},
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
        _parse_publishing_freshness_state(storage_dir, current),  # 2026-06-22 outcome dead-man switch (禁止脫班)
        _parse_dispatch_health_state(storage_dir, current),       # 2026-06-22 generator binary 源頭健康
        _parse_codex_failover_ready_state(storage_dir, current),  # 2026-07-10 備援只在額度中斷時才走 → 平時無訊號，主動探測
        _parse_dispatch_supervisor_heartbeat_state(storage_dir, current),  # 2026-07-10 daemon loop 卡死 dead-man switch（launchctl 抓不到）
        _parse_dispatch_supervisor_stale_code_state(storage_dir, current), # 2026-07-10 「修好了但沒重載」dead-man switch（三次靜默違反同日規則）
        _parse_gmail_poll_freshness_state(storage_dir, current),  # 2026-06-22 boss-email pipeline dead-man switch
        _parse_telegram_poll_freshness_state(storage_dir, current),  # 2026-07-06 boss-request: Telegram poller dead-man switch
        _parse_host_cron_state(storage_dir, current),
        _parse_push_backlog_state(storage_dir, current),          # 2026-07-04 26h push-hold incident: persistent unpushed-backlog escalation
        _parse_orphan_branch_state(storage_dir, current),         # 2026-07-10 worktree 清掉、branch 留下未合併工作，無人接手
        _parse_work_log_freshness_state(storage_dir, current),    # 2026-06-28 Codex/dispatch diversity dead-man switch
        _parse_event_receipt_state(storage_dir, current),         # 2026-07-05 event jobs: claimed zombie / queued past deadline
        _parse_member_qa_state(storage_dir, current),
        _parse_supabase_sync_state(storage_dir),
        _parse_knowledge_stale_state(storage_dir, current),
        _parse_paper_stale_state(current, paper_root),
        _parse_paper_website_drift_state(current),                # 2026-07-01 loop-eng: 網頁論文卡 status 是否 over-claim vs pipeline 決策
        _parse_strategy_metrics_freshness_state(storage_dir),     # 2026-06-24 migrated from cloud platform-ops-patrol
        _parse_paper_trading_gaps_state(storage_dir),             # 2026-06-24 migrated from cloud platform-ops-patrol
        _parse_disk_usage_state(storage_dir),                     # 2026-06-24 migrated from cloud platform-ops-patrol
        _parse_content_quality_state(storage_dir, current),       # 2026-06-24 meta-fix: content patrol layer
        _parse_cluster_cap_drift_state(storage_dir),              # 2026-06-29 K1333 publish discovered vix 6.1x / spy 8.3x overshoot
        _parse_loop_health_state(storage_dir, current),           # 2026-06-29 loop-engineering: is the loop improving?
        _parse_series_registry_state(storage_dir),                # 2026-07-06 迷思實驗室 4-mistake incident: series-brand drift detector (SoT = config/article_series.json)
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
