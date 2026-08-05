#!/usr/bin/env python3
"""RETIRED 2026-08-05 — use scripts/org/inbox_archive.py instead.

This was a stopgap that lived inside one department's subtree while every
department needed it. A shared need parked in one department's turf makes that
department's permission problem into everyone's; the canonical CLI is the fix.

  uv run python scripts/org/inbox_archive.py <role> --id <item id>
"""
import sys

sys.exit(
    "已退役。改用 canonical CLI（七個部門與經理都能跑）：\n"
    "  uv run python scripts/org/inbox_archive.py <部門|manager> --id <item id>\n"
    "它會擋下『請求／裁決還沒回覆就歸檔』並印出該打的回覆指令。"
)
