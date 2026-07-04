#!/usr/bin/env python3
"""Telegram 專用長期記憶 helper（2026-07-05）。

老闆透過 Telegram 交代、想長期記住的偏好 / 指示 / 事實，append 到
storage/ops/telegram_memory.md。telegram_responder 每次啟動先讀它 —— headless
short-lived session 沒有 interactive memory 自動注入，這是它唯一的跨 session
記憶通道。

Anti-stacking：不是新記憶系統 —— 是既有 telegram 雙向頻道（telegram_poll +
telegram_responder）補上的一個 channel-專屬記憶檔，contract 極簡（append-only
markdown + list）。研究 / 一般記憶各有其家（storage/memory/*.json、~/.claude memory）。

用法：
  python scripts/telegram_memory.py add "老闆說的長期偏好/指示"
  python scripts/telegram_memory.py list
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEM = ROOT / "storage" / "ops" / "telegram_memory.md"


def _taipei_stamp() -> str:
    """台灣時間戳，取自實際 date 命令（研究誠實：時間也是數據，不臆造）。"""
    out = subprocess.run(
        ["date", "+%Y-%m-%d %H:%M"],
        env={"TZ": "Asia/Taipei", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip() + " 台灣"


def add(content: str) -> None:
    content = content.strip()
    if not content:
        print("空內容，不寫入", file=sys.stderr)
        sys.exit(1)
    if not MEM.exists():
        print(f"記憶檔不存在：{MEM}", file=sys.stderr)
        sys.exit(1)
    line = f"- [{_taipei_stamp()}] {content}\n"
    with open(MEM, "a", encoding="utf-8") as f:
        f.write(line)
    print(f"已記入 Telegram 長期記憶：{line.strip()}")


def list_() -> None:
    if not MEM.exists():
        print("(記憶檔尚未建立)")
        return
    sys.stdout.write(MEM.read_text(encoding="utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser(description="Telegram 專用長期記憶 helper")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="append 一條長期記憶")
    a.add_argument("content", help="要記住的內容")
    sub.add_parser("list", help="印出全部記憶")
    args = ap.parse_args()
    if args.cmd == "add":
        add(args.content)
    elif args.cmd == "list":
        list_()


if __name__ == "__main__":
    main()
