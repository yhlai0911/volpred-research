"""Alert sink — `volpred ops send-alert` shim with per-class dedup window.

All alert functions:
  1. Check `state.should_dedup_alert(key, window_s)` — if dedup hit, return early
  2. Build a structured markdown body for the `--body-md` path (HTML-rendered)
  3. Subprocess `uv run volpred ops send-alert` with --force
  4. Call `state.mark_alert_sent(key)` so the next dedup check sees this send

Dedup windows match `refactor_plan_hourly_dispatch.md §3.3 alerts dedup table`:
  auth_blocked         : 3600s
  hang_killed          : 600s
  silent_death         : 600s
  completion_failure   : 0s     (no dedup — every final failure is visible)
  supervisor_restart   : 60s
  loop_crash           : 300s   (per-component key; crash-loop must not spam)
  orphan_restart       : 60s
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import state

LOG = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
UV_BIN = os.environ.get("UV_BIN", "/Users/yhlai0911/.local/bin/uv")

AUTH_HOTFIX_CMD = (
    'security set-generic-password-partition-list '
    '-S apple-tool:,apple:,launchd:,unsigned: '
    '-s "Claude Code-credentials" -k login.keychain'
)


def _send(level: str, title: str, body_md: str) -> int:
    """Invoke `volpred ops send-alert --body-md <tmp>`. Return CLI exit code."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", prefix="supervisor_alert_", delete=False, encoding="utf-8"
    )
    try:
        tmp.write(body_md)
        tmp.flush()
        tmp.close()
        cmd = [
            UV_BIN, "run", "volpred", "ops", "send-alert",
            "--level", level,
            "--title", title,
            "--body-md", tmp.name,
            "--force",
        ]
        try:
            result = subprocess.run(
                cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=60
            )
            if result.returncode != 0:
                LOG.warning("send-alert exit=%d stderr=%s", result.returncode, result.stderr[:200])
            return result.returncode
        except subprocess.TimeoutExpired:
            LOG.warning("send-alert timeout")
            return -1
        except FileNotFoundError:
            LOG.warning("uv binary not found: %s", UV_BIN)
            return -2
    finally:
        try:
            os.unlink(tmp.name)
        except OSError as exc:
            LOG.warning("alert temp file cleanup failed: path=%s error=%s", tmp.name, exc)


def send_auth_alert(*, log_tail: str = "", state_path: Path = state.STATE_PATH) -> bool:
    """Auth-blocked alert. Dedup 1h. Returns True if alert was sent."""
    key = "auth_blocked"
    if state.should_dedup_alert(key, window_s=3600, path=state_path):
        LOG.info("auth_alert deduped (sent within last 1h)")
        return False
    body = (
        "# Supervisor 偵測到 Claude CLI 認證失敗\n\n"
        "## 觸發條件\n"
        "- Worker subprocess stderr/stdout 含 `Not logged in` 或 `Please run /login`\n"
        "- Auth 類錯誤不會 retry（重試無用）；supervisor 已設 `auth_blocked=true` 暫停未來 hourly fires\n\n"
        "## 影響\n"
        "- 排程派工會持續停擺直到手動解除 auth_blocked + keychain 恢復\n\n"
        "## 建議行動\n\n"
        "```\n" + AUTH_HOTFIX_CMD + "\n```\n\n"
        "解除暫停（確認 auth 恢復後）：\n\n"
        "```\nuv run python -m scripts.dispatch_supervisor.cli unblock-auth\n```\n\n"
        "## Worker log tail\n\n"
        "```\n" + (log_tail[-2000:] if log_tail else "(empty)") + "\n```\n"
    )
    _send("critical", "supervisor auth_blocked", body)
    state.mark_alert_sent(key, path=state_path)
    return True


def send_hang_alert(*, job: dict[str, Any], log_tail: str = "", state_path: Path = state.STATE_PATH) -> bool:
    """Hang-killed alert. Dedup 10min."""
    key = "hang_killed"
    if state.should_dedup_alert(key, window_s=600, path=state_path):
        return False
    body = (
        "# Supervisor SIGKILL'd 一個 worker（hang > 50min cap）\n\n"
        f"## Job\n"
        f"- pid: {job.get('pid')}\n"
        f"- pgid: {job.get('pgid')}\n"
        f"- started_at: {job.get('started_at')}\n"
        f"- attempt: {job.get('attempt')}\n"
        f"- model: {job.get('model')}\n\n"
        "## 影響\n"
        "- 本輪 hourly fire 沒派工成功；pool 沒消化\n"
        "- Supervisor 仍存活，下個整點會嘗試新 fire\n\n"
        "## Worker log tail\n\n"
        "```\n" + (log_tail[-2000:] if log_tail else "(empty)") + "\n```\n"
    )
    _send("critical", "supervisor hang_killed", body)
    state.mark_alert_sent(key, path=state_path)
    return True


def send_silent_death_alert(*, job: dict[str, Any], state_path: Path = state.STATE_PATH) -> bool:
    """Worker PID died but no completion record. Dedup 10min."""
    key = "silent_death"
    if state.should_dedup_alert(key, window_s=600, path=state_path):
        return False
    body = (
        "# Supervisor 偵測到 worker silent death\n\n"
        f"- worker PID {job.get('pid')} 已不存在但 state 仍有 current_job\n"
        f"- pgid: {job.get('pgid')} started_at: {job.get('started_at')}\n"
        "- 已強制 record_completion(exit=-1, outcome=failure) 釋放 supervisor slot\n"
    )
    _send("warn", "supervisor silent_death", body)
    state.mark_alert_sent(key, path=state_path)
    return True


def send_completion_failure(*, entry: dict[str, Any], log_tail: str = "", state_path: Path = state.STATE_PATH) -> bool:
    """Final-attempt failure (after retry ladder exhausted). No dedup."""
    body = (
        "# Hourly-dispatch 全 attempt 失敗\n\n"
        f"- final exit_code: `{entry.get('exit_code')}`\n"
        f"- outcome: {entry.get('outcome')}\n"
        f"- attempts: {entry.get('attempts')}\n"
        f"- final_model: {entry.get('final_model')}\n"
        f"- duration_s: {entry.get('duration_s')}\n\n"
        "## Worker log tail\n\n"
        "```\n" + (log_tail[-2000:] if log_tail else "(empty)") + "\n```\n"
    )
    _send("critical", f"supervisor completion_failure exit={entry.get('exit_code')}", body)
    return True


def send_supervisor_restart(*, prev_started: str | None, state_path: Path = state.STATE_PATH) -> bool:
    """Supervisor (re)started under launchd KeepAlive. Dedup 60s."""
    key = "supervisor_restart"
    if state.should_dedup_alert(key, window_s=60, path=state_path):
        return False
    body = (
        "# Supervisor restarted under launchd KeepAlive\n\n"
        f"- previous_started_at: {prev_started or '(none — first boot)'}\n"
        f"- now: {state._now()}\n"
        "- 若短時間內反覆 restart，檢查 `~/.volpred/logs/dispatch_supervisor.log` 找 crash trace\n"
    )
    _send("info", "supervisor restart", body)
    state.mark_alert_sent(key, path=state_path)
    return True


def send_loop_crash(component: str, traceback_text: str, *, state_path: Path = state.STATE_PATH) -> bool:
    """A supervisor async loop (scheduler_loop / health_loop / main) crashed on
    an exception the loop's own broad `except` caught. Dedup 5min per
    component so a crash-loop doesn't spam — but unlike the old
    `LOG.exception`-only behaviour (Codex review §10 #7), this is now
    ALWAYS visible outside the log file at least once per window."""
    key = f"loop_crash:{component}"
    if state.should_dedup_alert(key, window_s=300, path=state_path):
        return False
    body = (
        f"# Supervisor `{component}` crashed on an unhandled exception\n\n"
        "## 影響\n"
        f"- `{component}` 的 broad except 接住了，loop 沒死（下一 tick 會繼續），但這代表"
        "該保護層剛才有一段時間沒在運作 — 若是 health_loop，代表 hang 偵測暫時失效；"
        "若是 scheduler_loop，代表本輪 fire 決策被跳過。\n\n"
        "## Traceback\n\n"
        "```\n" + traceback_text[-3000:] + "\n```\n"
    )
    _send("critical", f"supervisor loop_crash {component}", body)
    state.mark_alert_sent(key, path=state_path)
    return True


def send_orphan_restart_alert(
    *, job: dict[str, Any], killed: bool, state_path: Path = state.STATE_PATH,
) -> bool:
    """Supervisor boot found a stale `current_job` from a crashed prior
    instance (Codex review §10 #3). `killed=True` means the orphan process
    was still alive and identity-verified before being force-killed;
    `killed=False` covers every other case — already gone, pid reused, no
    fingerprint ever recorded (unverified), or the reservation never even
    reached a real pid before the crash (see `procutil.check_identity`)."""
    key = "orphan_restart"
    if state.should_dedup_alert(key, window_s=60, path=state_path):
        return False
    body = (
        "# Supervisor restart found an orphaned job from a crashed prior instance\n\n"
        f"- pid: {job.get('pid')} pgid: {job.get('pgid')}\n"
        f"- schedule_id: {job.get('schedule_id')} attempt: {job.get('attempt')} model: {job.get('model')}\n"
        f"- started_at: {job.get('started_at')}\n"
        f"- action: {'identity-verified SIGKILL issued' if killed else '已不存在 / pid 已被回收，未發送 kill signal'}\n\n"
        "## 影響\n"
        "- 前一個 supervisor process 非正常結束（crash / OOM-kill / manual kill -9）；"
        "worker 因 `start_new_session=True` 不會隨 supervisor 一起死，此次是補做清理\n"
    )
    _send("warn", "supervisor orphan_restart", body)
    state.mark_alert_sent(key, path=state_path)
    return True
