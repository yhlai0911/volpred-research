#!/usr/bin/env python3
"""DEPRECATED (2026-07-10 memory-unify)：Telegram 專用長期記憶已廢棄。

記憶已統一到 **auto-memory**（`~/.claude/projects/-Users-yhlai0911-volpred-research/memory/`）——
headless `telegram_responder` 啟動時 `claude -p` 會自動載入同一份大腦（MEMORY.md 索引 +
CLAUDE.md），與老闆在 VS Code 互動 session 用的是**同一份記憶**。老闆經 Telegram 交代的
長期指示，由 responder 用其 system 內建的 memory 系統寫進 auto-memory（一檔一事實 +
MEMORY.md pointer），不再走這個平行 append-only 檔。

為什麼廢：原本假設「headless session 沒有 auto-memory 自動注入」→ 才另建 telegram_memory.md。
2026-07-10 實測推翻該假設（headless `-p` 預設載入 auto-memory；只有 `--bare` 才跳過）。平行
記憶造成「兩個大腦」——Telegram 寫的本機看不到、靠主線程手動搬。統一後兩管道共讀共寫同一份。

此 stub 保留只為 **fail-loud**：若仍有殘留 caller，印警告（不 silent 消失）；`add` 的內容
落進 deprecation log 避免遺失。原內容歷史存檔見 `storage/ops/telegram_memory.md`（tombstone）。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEPRECATION_LOG = ROOT / "storage" / "ops" / "telegram_memory_deprecated_writes.jsonl"
MEM_DIR = "~/.claude/projects/-Users-yhlai0911-volpred-research/memory/"
MSG = (
    "[telegram_memory.py DEPRECATED 2026-07-10] 記憶已統一到 auto-memory "
    f"({MEM_DIR})。telegram_responder 啟動時自動載入同一份大腦；長期指示改用內建 "
    "memory 系統寫入（一檔一事實 + MEMORY.md pointer）。"
)


def _list() -> None:
    print(MSG, file=sys.stderr)
    print("(no entries — 記憶已遷移至 auto-memory；讀 MEMORY.md 索引)")


def _add(content: str) -> None:
    print(MSG, file=sys.stderr)
    # fail-loud + 不遺失：殘留寫入落進 deprecation log，供人工遷移到 auto-memory
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "content": content,
        "note": "written to DEPRECATED telegram_memory.py; migrate to auto-memory",
    }
    with open(DEPRECATION_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(
        f"[WARN] telegram_memory.py 已廢棄；此內容暫存到 {DEPRECATION_LOG.name}，"
        "請改用 auto-memory 記憶系統。",
        file=sys.stderr,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="DEPRECATED — 記憶已統一到 auto-memory")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="[廢棄] 內容落 deprecation log")
    a.add_argument("content")
    sub.add_parser("list", help="[廢棄] 提示改讀 auto-memory")
    args = ap.parse_args()
    if args.cmd == "add":
        _add(args.content)
    elif args.cmd == "list":
        _list()


if __name__ == "__main__":
    main()
