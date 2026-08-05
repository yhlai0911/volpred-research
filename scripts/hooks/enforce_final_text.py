#!/usr/bin/env python3
"""Stop hook runner: project final-text gate + user-global completion speech mode.

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
- default mode 只做既有 project final-text gate
- `--speech-only` 由 user-level Stop hook 呼叫；只接受 Desktop/VSCode final text 尾端的
  `<!-- task-done:極簡任務名 -->` 明確完成訊號，SDK/headless/API error 全部靜音
- speech 以 assistant UUID 去重，鎖外 detached argv 直呼 `/usr/bin/say`，不經 shell

**2026-08-05 flush-race 修正**（同一 session 內連續 4 次誤 block 合規文字收尾後發現）：
Stop 事件觸發的當下，harness 把最終 text 記錄寫進 transcript JSONL 的動作可能還沒
flush 完；hook 這時讀到的 tail 尾端不是不完整（不會走既有的 parse-fail silent-skip
分支），而是那筆記錄根本還沒寫進磁碟 —— fallback 到「前一筆」有效紀錄（通常是
一個 tool_use），誤判 turn 以 tool call 收尾。事後重讀同一份 transcript 可證實：
真正的最終文字記錄確實存在且非空，只是讀取當下比寫入快。修法：判定為
「非合規」時不立刻 block，改成短暫、有上限的重試讀取，給 writer 時間追上；
仍不合規才真的 block。

任何解析失敗一律 fail-open（放行）+ stderr 留 trace（no-silent-fallback）。
Regression test: scripts/tests/test_enforce_final_text.sh
"""
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

TAIL_BYTES = 512 * 1024
# flush-race 重試：Stop 觸發當下最終文字記錄可能還沒寫進 transcript 磁碟檔。
# 4 次 × 0.1s = 至多多等 0.3s（不含最後一次判定），對互動 session 無感，
# 遠低於曾觀測到的誤 block 造成的來回成本。
BLOCK_RETRY_ATTEMPTS = 4
BLOCK_RETRY_DELAY_SEC = 0.1
DEFAULT_SPEECH_STATE = Path.home() / ".claude" / "state" / "task_completion_speech.json"
SPEECH_MAX_LABEL_CHARS = 24
INTERACTIVE_ENTRYPOINTS = frozenset({"claude-desktop", "claude-vscode"})
TASK_DONE_MARKER = re.compile(r"<!--\s*task-done:\s*([^<>\r\n]{1,80}?)\s*-->\s*$", re.IGNORECASE)
_SENSITIVE_LABEL_MARKERS = (
    "password", "passwd", "secret", "token", "api key", "apikey",
    "密碼", "金鑰", "驗證碼", "信用卡", "私鑰",
)

REASON = (
    "CLAUDE.md 最高指引：turn 的最終輸出必須是「給用戶的完整文字回報」，"
    "寫在所有 tool call（含 ScheduleWakeup）之後。你剛才以 tool call 或空輸出"
    "結束了 turn — 用戶會看到「做了事卻沒回話」。請現在直接輸出最終文字回報："
    "結果摘要 + ⏱ 時間戳 + ⏭ 下次排程。若你正在等 AskUserQuestion 的回覆，"
    "補一句話說明正在等什麼即可。"
)


def _tail_records(transcript_path: str):
    """Yield parsed transcript records newest-first from a bounded tail."""
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
            continue  # silent-ok: tail read may split a record mid-line
        yield rec


def _last_assistant_block(transcript_path: str):
    """Return the last content block of the last main-chain assistant line."""
    rec = _last_assistant_record(transcript_path)
    return _last_content_block(rec) if rec is not None else None


def _last_assistant_record(transcript_path: str):
    for rec in _tail_records(transcript_path):
        if rec.get("type") == "assistant" and not rec.get("isSidechain"):
            return rec
    return None


def _last_content_block(rec: dict):
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, str):
        return {"type": "text", "text": content}
    if isinstance(content, list) and content:
        return content[-1]
    return None


def _safe_marker_label(raw: str) -> str:
    candidate = unicodedata.normalize("NFKC", raw)
    candidate = "".join(ch for ch in candidate if not unicodedata.category(ch).startswith("C"))
    candidate = re.sub(r"https?://\S+|/[A-Za-z0-9_.~/-]+", " ", candidate)
    candidate = re.sub(r"[^0-9A-Za-z\u3400-\u9fff +_.-]", " ", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip(" ._-")
    candidate = re.sub(r"(?:任務|工作)$", "", candidate).rstrip()
    lowered = candidate.lower()
    if not candidate or any(marker in lowered for marker in _SENSITIVE_LABEL_MARKERS):
        return "目前"
    return candidate[:SPEECH_MAX_LABEL_CHARS].rstrip()


def _speak_marked_completion(payload: dict, rec: dict, final_text: str) -> None:
    """Consume one explicit completion marker and launch nonblocking local speech."""
    if os.environ.get("CLAUDE_DISABLE_TASK_SPEECH", "").lower() in {"1", "true", "yes"}:
        return
    if payload.get("agent_id") or rec.get("isApiErrorMessage"):
        return
    if payload.get("background_tasks") or payload.get("session_crons"):
        return
    if rec.get("entrypoint") not in INTERACTIVE_ENTRYPOINTS:
        return
    marker = TASK_DONE_MARKER.search(final_text)
    if not marker:
        return
    label = _safe_marker_label(marker.group(1))
    session_id = str(payload.get("session_id") or rec.get("sessionId") or "")
    assistant_uuid = str(rec.get("uuid") or "")
    if not session_id or not assistant_uuid:
        print("enforce_final_text: speech missing session/assistant identity; skip", file=sys.stderr)
        return
    fingerprint = f"{session_id}:{assistant_uuid}"
    state_path = Path(os.environ.get("VOLPRED_SPEECH_STATE_PATH", str(DEFAULT_SPEECH_STATE)))
    lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    say_bin = os.environ.get("VOLPRED_SAY_BIN", "/usr/bin/say")

    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            recent: list[str] = []
            if state_path.exists():
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                    if not isinstance(state, dict):
                        raise TypeError(f"expected object, got {type(state).__name__}")
                    recent = [str(item) for item in state.get("recent", []) if item]
                except (OSError, ValueError, TypeError) as exc:
                    print(f"enforce_final_text: speech state read failed; rebuilding: {exc}", file=sys.stderr)
            if fingerprint in recent:
                return
            next_state = {"recent": (recent + [fingerprint])[-50:]}
            tmp_path = state_path.with_suffix(state_path.suffix + f".{os.getpid()}.tmp")
            tmp_path.write_text(json.dumps(next_state, ensure_ascii=False), encoding="utf-8")
            tmp_path.replace(state_path)
    except OSError as exc:
        print(f"enforce_final_text: speech state failed, fail-open: {exc}", file=sys.stderr)
        return

    phrase = f"主人，{label}任務已完成"
    try:
        subprocess.Popen(
            [say_bin, phrase],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        print(f"enforce_final_text: speech launch failed, fail-open: {exc}", file=sys.stderr)


def main(*, speech_only: bool = False) -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError as exc:
        print(f"enforce_final_text: bad hook input, fail-open: {exc}", file=sys.stderr)
        return 0
    transcript_path = payload.get("transcript_path") or ""
    if not transcript_path or not os.path.isfile(transcript_path):
        print("enforce_final_text: no transcript, fail-open", file=sys.stderr)
        return 0
    try:
        rec = _last_assistant_record(transcript_path)
    except OSError as exc:
        print(f"enforce_final_text: read error, fail-open: {exc}", file=sys.stderr)
        return 0
    block = _last_content_block(rec) if rec is not None else None
    if speech_only:
        if block is not None and block.get("type") == "text" and str(block.get("text", "")).strip():
            _speak_marked_completion(payload, rec, str(block.get("text", "")).strip())
        return 0
    if payload.get("stop_hook_active"):
        return 0  # project final-text gate 已 block 過一次 — 放行避免迴圈
    if block is not None and block.get("type") == "text" and str(block.get("text", "")).strip():
        return 0  # 最終輸出是非空文字 → 合規
    # 尚未合規：可能是真違規，也可能是 flush race（最終文字記錄還沒寫進磁碟）。
    # 短暫重試讀取，避免把「讀太快」誤判成「turn 以 tool call 收尾」。
    for attempt in range(1, BLOCK_RETRY_ATTEMPTS):
        time.sleep(BLOCK_RETRY_DELAY_SEC)
        try:
            rec = _last_assistant_record(transcript_path)
        except OSError as exc:
            print(f"enforce_final_text: retry read error, fail-open: {exc}", file=sys.stderr)
            return 0
        block = _last_content_block(rec) if rec is not None else None
        if block is not None and block.get("type") == "text" and str(block.get("text", "")).strip():
            print(
                f"enforce_final_text: compliant text found on retry {attempt} "
                "(flush-race avoided, not a real violation)",
                file=sys.stderr,
            )
            return 0
    print(json.dumps({"decision": "block", "reason": REASON}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args not in ([], ["--speech-only"]):
        print(f"enforce_final_text: unsupported arguments {args}; fail-open", file=sys.stderr)
        sys.exit(0)
    sys.exit(main(speech_only=(args == ["--speech-only"])))
