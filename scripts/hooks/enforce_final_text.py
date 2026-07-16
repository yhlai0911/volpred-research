#!/usr/bin/env python3
"""Stop hook: enforce final text and speak one short interactive completion brief.

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
- 合規文字只在 canonical main cwd 的互動 session 播報一次；worktree / scratch /
  hourly / Telegram responder 不播，避免背景 agent 噪音
- 播報用 argv 直呼 `/usr/bin/say`，不經 shell；task label 會去標記、去敏感字、截長

任何解析失敗一律 fail-open（放行）+ stderr 留 trace（no-silent-fallback）。
Regression test: scripts/tests/test_enforce_final_text.sh
"""
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

TAIL_BYTES = 512 * 1024
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SPEECH_STATE = Path.home() / ".volpred" / "run" / "claude_stop_speech.json"
SPEECH_MAX_LABEL_CHARS = 24

_NON_COMPLETION_MARKERS = (
    "尚未完成",
    "目前無法",
    "無法繼續",
    "需要你提供",
    "請先提供",
    "等待你的",
    "blocked on",
    "session limit",
    "額度未恢復",
)
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
    for rec in _tail_records(transcript_path):
        if rec.get("type") != "assistant" or rec.get("isSidechain"):
            continue
        content = (rec.get("message") or {}).get("content")
        if isinstance(content, str):
            return {"type": "text", "text": content}
        if isinstance(content, list) and content:
            return content[-1]
        return None
    return None


def _last_user_text(transcript_path: str) -> str:
    """Return the latest real user text, ignoring tool-result pseudo-user rows."""
    for rec in _tail_records(transcript_path):
        if rec.get("type") != "user" or rec.get("isSidechain"):
            continue
        content = (rec.get("message") or {}).get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if not isinstance(content, list):
            continue
        parts = [
            str(block.get("text", "")).strip()
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
            and str(block.get("text", "")).strip()
        ]
        if parts:
            return " ".join(parts)
    return ""


def _task_label(user_text: str) -> str:
    """Derive a short, local-only spoken label without shell interpretation."""
    quoted = re.findall(r"「([^」]{2,80})」", user_text)
    candidate = quoted[0] if quoted else next(
        (line.strip() for line in user_text.splitlines() if line.strip()),
        "目前任務",
    )
    candidate = re.sub(r"<[^>]+>", " ", candidate)
    candidate = re.sub(r"https?://\S+|/[A-Za-z0-9_.~/-]+", " ", candidate)
    candidate = re.sub(r"^\s*\([A-Za-z0-9]+\)\s*", "", candidate)
    candidate = re.sub(r"^[#>*_`\-\s]+", "", candidate)
    candidate = re.sub(r"^(?:請你|請|幫我|麻煩|你要|現在)\s*", "", candidate)
    candidate = re.split(r"[。！？!?；;]\s*", candidate, maxsplit=1)[0]
    candidate = re.sub(r"[^0-9A-Za-z\u3400-\u9fff +_.-]", " ", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip(" ._-")
    lowered = candidate.lower()
    if not candidate or any(marker in lowered for marker in _SENSITIVE_LABEL_MARKERS):
        return "目前"
    return candidate[:SPEECH_MAX_LABEL_CHARS].rstrip()


def _looks_complete(final_text: str) -> bool:
    lowered = final_text.strip().lower()
    if not lowered:
        return False
    if any(marker in lowered for marker in _NON_COMPLETION_MARKERS):
        return False
    if lowered.endswith(("?", "？")) and "已完成" not in lowered:
        return False
    return True


def _speak_completion(payload: dict, transcript_path: str, final_text: str) -> None:
    """Speak at most once per completed interactive turn; all failures fail-open."""
    if os.environ.get("VOLPRED_DISABLE_TASK_SPEECH", "").lower() in {"1", "true", "yes"}:
        return
    canonical = Path(os.environ.get("VOLPRED_SPEECH_CANONICAL_CWD", str(REPO_ROOT))).resolve()
    cwd_text = str(payload.get("cwd") or "")
    if not cwd_text or Path(cwd_text).resolve() != canonical:
        return
    if not _looks_complete(final_text):
        return
    try:
        user_text = _last_user_text(transcript_path)
    except OSError as exc:
        print(f"enforce_final_text: speech user-text read failed: {exc}", file=sys.stderr)
        return
    label = _task_label(user_text)
    phrase = f"主人，{label}任務已完成"
    session_id = str(payload.get("session_id") or "unknown")
    fingerprint = hashlib.sha256(f"{session_id}\0{final_text}".encode("utf-8")).hexdigest()
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
            subprocess.run(
                [say_bin, phrase],
                check=True,
                timeout=6,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            next_state = {"recent": (recent + [fingerprint])[-50:]}
            tmp_path = state_path.with_suffix(state_path.suffix + f".{os.getpid()}.tmp")
            tmp_path.write_text(json.dumps(next_state, ensure_ascii=False), encoding="utf-8")
            tmp_path.replace(state_path)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"enforce_final_text: speech failed, fail-open: {exc}", file=sys.stderr)


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
        final_text = str(block.get("text", "")).strip()
        _speak_completion(payload, transcript_path, final_text)
        return 0  # 最終輸出是非空文字 → 合規
    print(json.dumps({"decision": "block", "reason": REASON}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
