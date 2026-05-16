from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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
_RELEASE_POOL_FIRE_RE = re.compile(r"^=== \[release-pool\] fire at (.+) ===$")
_CRON_EXIT_RE = re.compile(r"^=== exit (\d+) at (.+) ===$")


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
    notification_id = notifier.notify(
        subject=subject,
        body=text_body,
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

    gap_hours = None
    if last_fire_at is not None:
        gap_hours = round((now - last_fire_at).total_seconds() / 3600.0, 2)

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

    breached = last_fire_at is None or (now - last_fire_at) > warn_threshold
    threshold_hours = round(warn_threshold.total_seconds() / 3600.0, 2)
    title = f"Release pool cron gap > {threshold_hours}h (interval={interval_minutes}min)"
    if not breached:
        return {
            "id": "release_pool_gap",
            "breached": False,
            "level": "info",
            "title": title,
            "body": "",
            "details": {
                "last_fire_at": last_fire_at.isoformat() if last_fire_at else None,
                "gap_hours": gap_hours,
                "interval_minutes": interval_minutes,
                "warn_threshold_hours": threshold_hours,
                "log_path": _relative_repo_path(log_path),
            },
        }

    level = "critical" if last_fire_at is None or (now - last_fire_at) > critical_threshold else "warn"
    last_fire_text = last_fire_at.isoformat() if last_fire_at else "missing"
    body = "\n".join(
        [
            "## 觸發條件",
            f"release_pool host cron fire gap 已超過 {threshold_hours} 小時門檻 (interval={interval_minutes}min + 30min grace)。",
            f"- last_fire_at: {last_fire_text}",
            f"- gap_hours: {gap_hours if gap_hours is not None else 'missing'}",
            f"- configured_interval_minutes: {interval_minutes}",
            f"- log_path: {_relative_repo_path(log_path)}",
            "",
            "## 影響",
            "文章釋出中斷 = 讀者端看到平台停滯、搜尋索引停滯；Mission 第 1 條（文章品質）",
            f"與第 5 條（曝光流量）直接受損。若持續 >{round(critical_threshold.total_seconds() / 3600, 1)}h 會累積多篇 draft 排隊延遲。",
            "",
            "## 建議行動",
            "1. 立即手動釋出（最快復原）：",
            "   VOLPRED_ACTOR=claude uv run volpred ops release-pool-by-settings",
            "2. 診斷 host cron 是否仍在跑：",
            f"   tail -20 {_relative_repo_path(log_path)}",
            "   crontab -l | grep release_pool",
            "3. 若 cron daemon 卡住：重新 install crontab 或 launchd job",
            "4. 若 draft 池也空（配合 draft_pool_low alert）：先補池，見 publish-checklist",
            "   與 .claude/skills/publication-candidates/SKILL.md 的 5-step 選題流程。",
        ]
    )
    return {
        "id": "release_pool_gap",
        "breached": True,
        "level": level,
        "title": title,
        "body": body,
        "details": {
            "last_fire_at": last_fire_at.isoformat() if last_fire_at else None,
            "gap_hours": gap_hours,
            "interval_minutes": interval_minutes,
            "warn_threshold_hours": threshold_hours,
            "log_path": _relative_repo_path(log_path),
        },
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


def _parse_host_cron_state(storage_dir: str, now: datetime) -> dict[str, Any]:
    logs_dir = _cron_logs_dir(storage_dir)
    failing_logs: list[dict[str, Any]] = []
    if logs_dir.exists():
        for log_path in sorted(logs_dir.glob("*.log")):
            latest = _latest_cron_exit(log_path)
            if latest and int(latest.get("exit_code", 0)) != 0:
                failing_logs.append(latest)

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
    body_lines = [
        "## 觸發條件",
        "偵測到 host cron 失敗（最新 exit code != 0）。",
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
        "level": "critical" if breached else "info",
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


def build_alert_condition_report(
    *,
    storage_dir: str = "storage",
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now.astimezone(timezone.utc) if now is not None else _utc_now()
    conditions = [
        _parse_release_pool_state(storage_dir, current),
        _parse_draft_pool_state(storage_dir),
        _parse_host_cron_state(storage_dir, current),
        _parse_member_qa_state(storage_dir, current),
        _parse_supabase_sync_state(storage_dir),
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
) -> dict[str, Any]:
    report = build_alert_condition_report(storage_dir=storage_dir)
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
