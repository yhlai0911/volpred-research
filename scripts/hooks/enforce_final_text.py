#!/usr/bin/env python3
"""Stop hook: turn 最終輸出必須是給用戶的文字（CLAUDE.md 最高指引強制層）.

3-STRIKE 結構性修正（2026-07-02）：「turn 以 tool call 收尾、無最終文字回報」
同日第三波復發（2026-06 首糾 → 2026-07-02 上午 6 連問 → 13:15 再犯 → 14:16
symlink 移除後又無回報）。memory 提醒（strike 1）與 CLAUDE.md 固化（strike 2）
都擋不住，故升級為 Stop hook 硬性攔截：偵測到最後一個 assistant 輸出不是
非空文字塊時，block stop 並要求補完整文字回報。

行為：
- stdin 收 Claude Code Stop hook JSON（transcript_path / stop_hook_active）
- stop_hook_active=true 時放行（已 block 過一次，避免無窮迴圈）
- 只讀 transcript 尾端 512KB（transcript 可達數十 MB）
- 最後一條 main-chain assistant 行的最後 content block 是非空 text → 放行
- 否則輸出 {"decision":"block","reason":...} 擋下，讓 Claude 補文字

任何解析失敗一律 fail-open（放行）+ stderr 留 trace（no-silent-fallback）。
Regression test: scripts/tests/test_enforce_final_text.sh
"""
import json
import os
import sys

TAIL_BYTES = 512 * 1024

REASON = (
    "CLAUDE.md 最高指引：turn 的最終輸出必須是「給用戶的完整文字回報」，"
    "寫在所有 tool call（含 ScheduleWakeup）之後。你剛才以 tool call 或空輸出"
    "結束了 turn — 用戶會看到「做了事卻沒回話」。請現在直接輸出最終文字回報："
    "結果摘要 + ⏱ 時間戳 + ⏭ 下次排程。若你正在等 AskUserQuestion 的回覆，"
    "補一句話說明正在等什麼即可。"
)


def _last_assistant_block(transcript_path: str):
    """Return the last content block of the last main-chain assistant line."""
    size = os.path.getsize(transcript_path)
    with open(transcript_path, "rb") as f:
        f.seek(max(0, size - TAIL_BYTES))
        chunk = f.read()
    lines = chunk.split(b"\n")
    if size > TAIL_BYTES and lines:
        lines = lines[1:]  # 丟掉可能被截斷的首行
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        if rec.get("type") != "assistant" or rec.get("isSidechain"):
            continue
        content = (rec.get("message") or {}).get("content")
        if isinstance(content, str):
            return {"type": "text", "text": content}
        if isinstance(content, list) and content:
            return content[-1]
        return None
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError as exc:
        print(f"enforce_final_text: bad hook input, fail-open: {exc}", file=sys.stderr)
        return 0
    if payload.get("stop_hook_active"):
        return 0  # 已 block 過一次 — 放行避免迴圈
    transcript_path = payload.get("transcript_path") or ""
    if not transcript_path or not os.path.isfile(transcript_path):
        print("enforce_final_text: no transcript, fail-open", file=sys.stderr)
        return 0
    try:
        block = _last_assistant_block(transcript_path)
    except OSError as exc:
        print(f"enforce_final_text: read error, fail-open: {exc}", file=sys.stderr)
        return 0
    if block is not None and block.get("type") == "text" and str(block.get("text", "")).strip():
        return 0  # 最終輸出是非空文字 → 合規
    print(json.dumps({"decision": "block", "reason": REASON}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
