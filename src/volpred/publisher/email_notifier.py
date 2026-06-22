from __future__ import annotations

import json
import os
import smtplib
import re
import sys
from datetime import date, datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from html import escape
from pathlib import Path
from typing import Any

from volpred.config.runtime import get_default_remote_url
from zoneinfo import ZoneInfo


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def _warn_email_notifier(message: str, path: Path, exc: Exception) -> None:
    print(
        f"[email_notifier] WARN {message}: "
        f"path={path} error={type(exc).__name__}: {exc}",
        file=sys.stderr,
    )


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    try:
        for raw_line in path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key or key in os.environ:
                continue
            os.environ[key] = value.strip()
    except Exception as exc:
        _warn_email_notifier("env file read failed; continuing without it", path, exc)
        return


def _prime_project_env() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    for candidate in (
        repo_root / ".env",
        repo_root / ".env.local",
        repo_root / "frontend-v2-fix" / ".env.local",
    ):
        _load_env_file(candidate)


def _parse_csv_env(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _pick_body(article: dict[str, Any]) -> str:
    for key in ("content", "description", "analysis", "summary", "body"):
        value = article.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _strip_markdown(text: str) -> str:
    cleaned = text.replace("\r\n", "\n")
    cleaned = re.sub(r"```.*?```", " ", cleaned, flags=re.S)
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", cleaned, flags=re.M)
    cleaned = re.sub(r"^\s{0,3}>\s?", "", cleaned, flags=re.M)
    cleaned = re.sub(r"^\s*[-*+]\s+", "", cleaned, flags=re.M)
    cleaned = re.sub(r"^\s*\d+\.\s+", "", cleaned, flags=re.M)
    cleaned = re.sub(r"\|", " ", cleaned)
    cleaned = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", cleaned)
    cleaned = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", cleaned)
    cleaned = re.sub(r"\$\$.*?\$\$", " ", cleaned, flags=re.S)
    cleaned = re.sub(r"\$([^$]+)\$", r"\1", cleaned)
    cleaned = re.sub(r"\n{2,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned.strip()


def _extract_summary(markdown_text: str, max_length: int = 220) -> str:
    plain = _strip_markdown(markdown_text)
    if not plain:
        return "此文章已發布，請點擊連結查看完整內容。"
    paragraphs = [segment.strip() for segment in plain.split("\n\n") if segment.strip()]
    skip_titles = {
        "摘要",
        "研究背景",
        "方法與數據",
        "核心發現",
        "實務意義",
        "結論",
        "summary",
        "background",
        "conclusion",
    }
    skip_titles_lower = {item.lower() for item in skip_titles}
    summary = plain
    for paragraph in paragraphs or [plain]:
        lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
        for line in lines:
            normalized = line.strip().strip(":：").lower()
            if normalized in skip_titles_lower:
                continue
            if len(normalized) <= 6 and normalized in skip_titles_lower:
                continue
            summary = line
            break
        if summary != plain:
            break
    parts = re.split(r"(?<=[。！？!?])\s*", summary)
    first_sentence = next((part.strip() for part in parts if part.strip()), summary).strip()
    if first_sentence:
        summary = first_sentence
    if len(summary) <= max_length:
        return summary
    clipped = summary[: max_length - 1].rsplit(" ", 1)[0].strip()
    return (clipped or summary[: max_length - 1]).rstrip("，。、；：") + "…"


def _try_markdown_to_html(markdown_text: str) -> str:
    try:
        from markdown_it import MarkdownIt

        renderer = MarkdownIt("commonmark", {"html": False, "breaks": True})
        renderer.enable("table")
        renderer.enable("strikethrough")
        return renderer.render(markdown_text)
    except Exception:
        paragraphs = [segment.strip() for segment in markdown_text.split("\n\n") if segment.strip()]
        if not paragraphs:
            return "<p></p>"
        return "".join(
            f"<p>{escape(paragraph).replace(chr(10), '<br>')}</p>"
            for paragraph in paragraphs
        )


def _email_shell(title: str, subtitle: str | None, body_html: str) -> str:
    subtitle_html = f'<p style="margin:6px 0 0;color:#6b7280;font-size:14px;">{escape(subtitle)}</p>' if subtitle else ""
    return f"""<!doctype html>
<html lang="zh-Hant">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escape(title)}</title>
  </head>
  <body style="margin:0;background:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#111827;">
    <div style="max-width:880px;margin:0 auto;padding:32px 16px;">
      <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:16px;overflow:hidden;box-shadow:0 8px 30px rgba(15,23,42,.06);">
        <div style="padding:24px 28px;background:linear-gradient(135deg,#0f172a,#111827);color:#ffffff;">
          <div style="font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#86efac;">VolPred 管理通知</div>
          <h1 style="margin:10px 0 0;font-size:28px;line-height:1.2;">{escape(title)}</h1>
          {subtitle_html}
        </div>
        <div style="padding:28px;line-height:1.75;font-size:15px;">
          <style>
            h1,h2,h3{{color:#0f172a;line-height:1.35;margin:1.2em 0 .5em}}
            p{{margin:.8em 0}}
            /* table-layout:fixed + word-break 防 mobile 溢出（2026-05-30 boss 回饋：
               HTML 表格超過頁面寬度且無法捲動）。fixed 讓表格 honor width:100%、
               cell 內長文字/路徑/hash 換行而非撐破容器 viewport。 */
            table{{width:100%;border-collapse:collapse;margin:1em 0;font-size:14px;table-layout:fixed}}
            th,td{{border:1px solid #d1d5db;padding:8px 10px;text-align:left;vertical-align:top;word-break:break-word;overflow-wrap:anywhere}}
            td code,th code{{word-break:break-all;white-space:normal}}
            th{{background:#f9fafb}}
            code{{background:#f3f4f6;color:#111827;border-radius:4px;padding:2px 5px;font-size:13px;font-family:'SF Mono',Menlo,Monaco,Consolas,monospace}}
            pre{{background:#f9fafb;color:#111827;border:1px solid #e5e7eb;padding:14px;border-radius:10px;overflow:auto;font-size:13px;line-height:1.5;font-family:'SF Mono',Menlo,Monaco,Consolas,monospace}}
            pre code{{background:transparent;padding:0;font-size:13px;color:inherit}}
            blockquote{{border-left:5px solid #dc2626;background:#fef2f2;color:#7f1d1d;padding:12px 16px;margin:1em 0;border-radius:6px;font-weight:500}}
            blockquote strong{{color:#991b1b}}
            blockquote{{border-left:4px solid #10b981;padding-left:14px;color:#475569;margin:1em 0}}
            a{{color:#2563eb}}
          </style>
          {body_html}
        </div>
      </div>
    </div>
  </body>
</html>"""


def _format_taipei_time(value: str | None) -> str:
    if not value:
        return "未提供"
    raw = value.strip()
    if not raw:
        return "未提供"

    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return raw

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    local = parsed.astimezone(TAIPEI_TZ)
    return local.strftime("%Y-%m-%d %H:%M 台灣時間")


class EmailNotifier:
    """Email + file-backed notification system for platform operations."""

    def __init__(self, storage_dir: str = "storage"):
        _prime_project_env()
        self.storage_dir = Path(storage_dir)
        self.notifications_dir = self.storage_dir / "notifications"
        self.notifications_dir.mkdir(parents=True, exist_ok=True)
        self.from_email = os.environ.get("EMAIL_FROM", "").strip()
        self.from_name = os.environ.get("EMAIL_FROM_NAME", "VolPred")
        self.smtp_host = os.environ.get("SMTP_HOST", "").strip()
        self.smtp_port = int(os.environ.get("SMTP_PORT", "587") or 587)
        self.smtp_username = os.environ.get("SMTP_USERNAME", "").strip()
        self.smtp_password = os.environ.get("SMTP_PASSWORD", "").strip()
        self.smtp_use_tls = os.environ.get("SMTP_USE_TLS", "true").strip().lower() not in {"0", "false", "no"}
        self.admin_emails = (
            _parse_csv_env("ADMIN_NOTIFICATION_EMAILS")
            or _parse_csv_env("OPS_ADMIN_EMAILS")
        )
        self.site_url = os.environ.get(
            "NEXT_PUBLIC_SITE_URL",
            os.environ.get("VOLPRED_REMOTE_URL", get_default_remote_url()),
        ).strip()

    def is_configured(self) -> bool:
        return bool(self.smtp_host and self.from_email and self.admin_emails)

    def _load_log(self) -> list[dict[str, Any]]:
        log_file = self.notifications_dir / "notification_log.json"
        if not log_file.exists():
            return []
        try:
            return json.loads(log_file.read_text())
        except Exception:
            return []

    def _save_log(self, entries: list[dict[str, Any]]) -> None:
        log_file = self.notifications_dir / "notification_log.json"
        log_file.write_text(json.dumps(entries, indent=2, ensure_ascii=False, default=str))

    def _write_notification_file(self, notification: dict[str, Any]) -> None:
        notif_file = self.notifications_dir / f"{notification['id']}.json"
        notif_file.write_text(json.dumps(notification, indent=2, ensure_ascii=False, default=str))

    def _send_email(
        self,
        *,
        subject: str,
        text_body: str,
        html_body: str | None,
        recipients: list[str],
    ) -> None:
        # 2026-04-20 fix: hard gate against tests + ephemeral runs leaking into
        # user inbox. User reported receiving "First run scheduled article" and
        # "Scheduled article 1" admin notifications — traced to
        # tests/test_content_release_pool.py fixtures `mile_first_run` /
        # `mile_sched_1` triggering release_pool_by_settings → real SMTP send.
        # VOLPRED_NO_EMAIL=1 disables all outbound; honored at send layer so
        # notification bookkeeping (dedup log, notif_id) still records the
        # skip without actually sending. Set automatically in pytest via
        # conftest.py to protect against future test-fixture leaks.
        if os.environ.get("VOLPRED_NO_EMAIL", "").strip() in {"1", "true", "yes"}:
            return

        # 2026-04-20: secondary guard — if storage_dir lives under /tmp/ or
        # pytest-typical tmp paths, skip send. Defense-in-depth in case
        # VOLPRED_NO_EMAIL env is forgotten in new test files.
        storage_str = str(self.storage_dir).lower()
        if any(marker in storage_str for marker in ("/tmp/", "/private/tmp/", "pytest-", "test_")):
            return

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr((self.from_name, self.from_email))
        message["To"] = ", ".join(recipients)
        message.set_content(text_body)
        if html_body:
            message.add_alternative(html_body, subtype="html")

        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=20) as smtp:
            if self.smtp_use_tls:
                smtp.starttls()
            if self.smtp_username:
                smtp.login(self.smtp_username, self.smtp_password)
            smtp.send_message(message)

    def already_sent(self, notification_type: str, key: str) -> bool:
        for item in self._load_log():
            metadata = item.get("metadata") or {}
            if metadata.get("notification_type") == notification_type and metadata.get("notification_key") == key and item.get("sent"):
                return True
        return False

    def notify(
        self,
        subject: str,
        body: str,
        *,
        level: str = "info",
        metadata: dict[str, Any] | None = None,
        html_body: str | None = None,
        recipients: list[str] | None = None,
        dedupe_type: str | None = None,
        dedupe_key: str | None = None,
        force_send: bool = False,
    ) -> str:
        import uuid

        metadata = dict(metadata or {})
        if dedupe_type and dedupe_key:
            metadata.setdefault("notification_type", dedupe_type)
            metadata.setdefault("notification_key", dedupe_key)
            if not force_send and self.already_sent(dedupe_type, dedupe_key):
                notif_id = f"skip_{uuid.uuid4().hex[:8]}"
                notification = {
                    "id": notif_id,
                    "subject": subject,
                    "body": body,
                    "html_body": html_body,
                    "level": level,
                    "metadata": metadata,
                    "timestamp": _utc_now(),
                    "sent": False,
                    "skipped": True,
                    "skip_reason": "duplicate",
                }
                self._write_notification_file(notification)
                log = self._load_log()
                log.append(notification)
                self._save_log(log)
                return notif_id

        notif_id = uuid.uuid4().hex[:8]
        target_recipients = recipients or list(self.admin_emails)
        notification = {
            "id": notif_id,
            "subject": subject,
            "body": body,
            "text_body": body,
            "html_body": html_body,
            "level": level,
            "metadata": metadata,
            "timestamp": _utc_now(),
            "recipients": target_recipients,
            "sent": False,
            "configured": self.is_configured(),
        }

        send_error = None
        if target_recipients and self.is_configured():
            try:
                self._send_email(
                    subject=subject,
                    text_body=body,
                    html_body=html_body,
                    recipients=target_recipients,
                )
                notification["sent"] = True
            except Exception as exc:
                send_error = str(exc)
                notification["send_error"] = send_error

        self._write_notification_file(notification)
        log = self._load_log()
        log.append(notification)
        self._save_log(log)
        return notif_id

    def get_notifications(self, limit: int = 20, level: str | None = None) -> list[dict]:
        log = self._load_log()
        if level:
            log = [item for item in log if item.get("level") == level]
        log.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return log[:limit]

    def notify_article_published(
        self,
        article: dict[str, Any],
        *,
        reason: str = "published",
        force_send: bool = False,
    ) -> str:
        body_markdown = _pick_body(article)
        title = str(article.get("title") or article.get("id") or "未命名文章")
        article_id = str(article.get("id") or "")
        published_at = str(article.get("published_at") or article.get("created_at") or "")
        published_at_local = _format_taipei_time(published_at)
        tags = article.get("tags") or []
        tag_line = ", ".join(str(tag) for tag in tags) if isinstance(tags, list) else ""
        category = str(article.get("category") or "article")
        audience = str(article.get("audience") or (article.get("details") or {}).get("audience") or "未分類")
        summary = _extract_summary(body_markdown)
        subtitle = f"{category} | {published_at_local}" if published_at else category
        article_url = f"{self.site_url.rstrip('/')}/reports/{article_id}" if article_id else self.site_url

        intro_html = (
            f"<p><strong>文章標題：</strong>{escape(title)}</p>"
            f"<p><strong>文章 ID：</strong>{escape(article_id)}</p>"
            f"<p><strong>發布時間：</strong>{escape(published_at_local)}</p>"
            f"<p><strong>Audience：</strong>{escape(audience)}</p>"
            f"<p><strong>標籤：</strong>{escape(tag_line or '—')}</p>"
            f"<p><strong>摘要：</strong>{escape(summary)}</p>"
            f"<p><a href=\"{escape(article_url)}\">查看網站文章頁</a></p>"
        )
        html_body = _email_shell(
            f"新文章發布：{title}",
            subtitle,
            intro_html,
        )
        text_body = "\n".join(
            [
                f"新文章發布：{title}",
                f"文章標題：{title}",
                f"文章 ID：{article_id}",
                f"發布時間：{published_at_local}",
                f"Audience：{audience}",
                f"標籤：{tag_line or '—'}",
                f"摘要：{summary}",
                f"查看文章：{article_url}",
            ]
        ).strip()
        return self.notify(
            subject=f"[VolPred] 新文章發布：{title}",
            body=text_body,
            html_body=html_body,
            level="milestone",
            metadata={
                "notification_type": "article_published",
                "notification_key": article_id,
                "article_id": article_id,
                "reason": reason,
                "status": article.get("status"),
            },
            dedupe_type="article_published",
            dedupe_key=article_id,
            force_send=force_send,
        )

    def send_daily_digest(
        self,
        articles: list[dict[str, Any]],
        *,
        digest_date: date | None = None,
        force_send: bool = False,
    ) -> dict[str, Any]:
        target_date = digest_date or datetime.now().date()
        digest_key = target_date.isoformat()
        if not articles:
            return {
                "date": digest_key,
                "sent": False,
                "skipped": True,
                "reason": "no_articles",
                "count": 0,
            }

        sections_html: list[str] = []
        sections_text: list[str] = []
        for index, article in enumerate(articles, start=1):
            title = str(article.get("title") or article.get("id") or f"文章 {index}")
            article_id = str(article.get("id") or "")
            article_url = f"{self.site_url.rstrip('/')}/reports/{article_id}" if article_id else self.site_url
            body_markdown = _pick_body(article)
            summary = _extract_summary(body_markdown, max_length=180)
            published_at = str(article.get("published_at") or article.get("created_at") or "")
            published_at_local = _format_taipei_time(published_at)
            sections_html.append(
                "<section style=\"margin:0 0 36px;\">"
                f"<h2 style=\"margin:0 0 8px;font-size:22px;\">{index}. {escape(title)}</h2>"
                f"<p style=\"margin:0 0 10px;color:#6b7280;\">{escape(published_at_local)}</p>"
                f"<p style=\"margin:0 0 10px;\"><strong>文章標題：</strong>{escape(title)}</p>"
                f"<p style=\"margin:0 0 12px;line-height:1.7;\">{escape(summary)}</p>"
                f"<p style=\"margin:0 0 14px;\"><a href=\"{escape(article_url)}\">查看文章頁</a></p>"
                "</section>"
            )
            sections_text.append(
                "\n".join(
                    [
                        f"{index}. {title}",
                        f"文章標題：{title}",
                        f"發布時間：{published_at_local}",
                        f"摘要：{summary}",
                        f"文章頁：{article_url}",
                    ]
                ).strip()
            )

        html_body = _email_shell(
            f"{target_date.isoformat()} 當日發文摘要",
            f"共 {len(articles)} 篇，格式比照管理通知電子報。",
            "".join(sections_html),
        )
        text_body = (
            f"{target_date.isoformat()} 當日發文摘要\n"
            f"共 {len(articles)} 篇文章\n\n" + "\n\n" + ("\n\n---\n\n".join(sections_text))
        )
        notif_id = self.notify(
            subject=f"[VolPred] {target_date.isoformat()} 當日發文摘要",
            body=text_body,
            html_body=html_body,
            level="info",
            metadata={
                "notification_type": "daily_digest",
                "notification_key": digest_key,
                "date": digest_key,
                "article_ids": [str(article.get("id") or "") for article in articles],
                "count": len(articles),
            },
            dedupe_type="daily_digest",
            dedupe_key=digest_key,
            force_send=force_send,
        )
        return {
            "date": digest_key,
            "notification_id": notif_id,
            "sent": self.already_sent("daily_digest", digest_key),
            "skipped": False,
            "count": len(articles),
        }
