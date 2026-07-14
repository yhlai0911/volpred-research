#!/usr/bin/env python3
"""Send an email with file attachment(s) via the project's SMTP creds.

WHY (2026-06-04): the existing email paths (`volpred ops send-alert` /
`EmailNotifier`) only send text/HTML bodies — no attachment support. The boss
asked to receive a zipped skill by email, and "deliver a file by email" is a
recurring need (export a skill, ship a report, send a chart bundle). This is the
canonical reusable entry for it instead of a throwaway one-off.

SMTP secrets are read ONLY from .env / .env.local (per .claude/rules/alert.md —
never hardcode credentials). Default recipient is the project alert recipient.

Usage:
    uv run python scripts/send_email_attachment.py \
        --to yihao.lai@gmail.com \
        --subject "anti-ai-style skill" \
        --body "整包附上" \
        --attach /tmp/anti-ai-style_skill.zip
"""
from __future__ import annotations

import argparse
import mimetypes
import smtplib
import sys
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECIPIENT = "yihao.lai@gmail.com"


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for fname in (".env", ".env.local"):
        p = ROOT / fname
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def send(to: str, subject: str, body: str, attachments: list[Path]) -> bool:
    env = _load_env()
    host = env.get("SMTP_HOST")
    port = int(env.get("SMTP_PORT", "587") or "587")
    user = env.get("SMTP_USERNAME")
    pwd = env.get("SMTP_PASSWORD")
    use_tls = env.get("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes"}
    from_email = env.get("EMAIL_FROM") or user
    from_name = env.get("EMAIL_FROM_NAME", "VolPred")
    if not host or not from_email:
        print("ERROR: SMTP_HOST / EMAIL_FROM missing from .env", file=sys.stderr)
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = to
    msg.set_content(body)

    for path in attachments:
        if not path.exists():
            print(f"ERROR: attachment not found: {path}", file=sys.stderr)
            return False
        ctype, encoding = mimetypes.guess_type(str(path))
        if ctype is None or encoding is not None:
            ctype = "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(
            path.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=path.name,
        )

    with smtplib.SMTP(host, port, timeout=30) as smtp:
        if use_tls:
            smtp.starttls()
        if user:
            smtp.login(user, pwd)
        smtp.send_message(msg)
    print(f"OK: sent to {to} with {len(attachments)} attachment(s): "
          f"{[p.name for p in attachments]}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--to", default=DEFAULT_RECIPIENT)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--body", default="")
    ap.add_argument("--attach", action="append", required=True,
                    help="path to attach; repeatable")
    a = ap.parse_args()
    paths = [Path(x) for x in a.attach]
    return 0 if send(a.to, a.subject, a.body, paths) else 1


if __name__ == "__main__":
    raise SystemExit(main())
