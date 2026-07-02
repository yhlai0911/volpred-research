#!/usr/bin/env python3
"""PreToolUse hook: 互動 turn 禁用 ScheduleWakeup（機械 enforce）.

背景（2026-07-02 五犯）：ScheduleWakeup 的工具回應「Nothing more to do this
turn」會讓模型把 tool call 當回合終點 — 用戶的問題被執行了、回覆卻永遠沒寫
出來，老闆得連發兩則訊息才拿到回應。Stop hook 只能下一 turn 事後提醒，救不了
當回合；CLAUDE.md 規則（prose）連改兩版都擋不住。此 hook 把規則升級為 L1 機械
層：**當前 turn 的觸發訊息不是 autonomous fire 時，直接 deny 這個 tool call**。

判定：讀 transcript 尾端，找最後一條真人 user 訊息（排除 tool_result /
system-reminder-only），內容含 autonomous-loop sentinel（"<<autonomous-loop"
或 "autonomous-loop-dynamic"）→ autonomous fire turn → 放行；否則 deny。

Fail-open：任何解析失敗一律放行（寧可漏擋，不可誤擋 autonomous 迴圈的正當排程）。
Regression: scripts/tests/test_deny_wakeup_interactive.sh
"""
import json
import os
import sys

TAIL_BYTES = 512 * 1024
AUTONOMOUS_MARKERS = ("<<autonomous-loop", "autonomous-loop-dynamic")

DENY_MSG = (
    "互動 turn 禁用 ScheduleWakeup（CLAUDE.md 最高指引，2026-07-02 五犯後機械 enforce）。"
    "用戶正在等回覆 — 這個 tool call 會讓你把回合收掉、回覆永遠寫不出來。"
    "自主迴圈由 OS backbone（hourly-dispatch LaunchAgent 等）維持，不需要 session 內 wakeup。"
    "直接繼續完成工作，然後以文字回覆收尾。"
)


def _last_user_text(transcript_path: str) -> str:
    size = os.path.getsize(transcript_path)
    with open(transcript_path, "rb") as f:
        f.seek(max(0, size - TAIL_BYTES))
        chunk = f.read()
    lines = chunk.split(b"\n")
    if size > TAIL_BYTES and lines:
        lines = lines[1:]
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue  # silent-ok: tail read may split a record mid-line
        if rec.get("type") != "user" or rec.get("isSidechain"):
            continue
        content = (rec.get("message") or {}).get("content")
        texts: list[str] = []
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            has_tool_result = False
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        texts.append(str(block.get("text", "")))
                    elif block.get("type") == "tool_result":
                        has_tool_result = True
            if has_tool_result and not any(t.strip() for t in texts):
                continue  # tool_result 行不是真人訊息，往前找
        joined = "\n".join(texts).strip()
        if joined:
            return joined
    return ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0  # fail-open
    if payload.get("tool_name") != "ScheduleWakeup":
        return 0
    transcript_path = payload.get("transcript_path") or ""
    if not transcript_path or not os.path.isfile(transcript_path):
        return 0  # fail-open
    try:
        last_user = _last_user_text(transcript_path)
    except OSError:
        return 0  # fail-open
    if any(m in last_user for m in AUTONOMOUS_MARKERS):
        return 0  # autonomous fire turn — 放行
    print(DENY_MSG, file=sys.stderr)
    return 2  # exit 2 = deny tool call, stderr 餵回模型


if __name__ == "__main__":
    sys.exit(main())
