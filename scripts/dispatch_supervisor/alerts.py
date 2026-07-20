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
  quota_blocked        : outage-scoped (cleared on next success; 7d backstop window)
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


def send_quota_alert(*, log_tail: str = "", state_path: Path = state.STATE_PATH) -> bool:
    """Claude Code quota exhausted. ONE email per outage: the dedup key is
    cleared by the worker on the next success (outage over), with a 7d window
    as backstop. Level warn, not critical: the loop self-resumes at the
    provider's reset time with no manual action."""
    key = "quota_blocked"
    # Outage-scoped dedup: worker clears this key on the next SUCCESS (end of
    # outage), so one outage = one email regardless of length. The 7d window is
    # only a backstop against flapping — NOT the primary semantics (a fixed 4h
    # window would re-email every 4h during a long weekly-quota outage).
    if state.should_dedup_alert(key, window_s=7 * 86400, path=state_path):
        return False
    body = (
        "# Claude Code 額度已用完 — 排程派工自動暫停中\n\n"
        "## 觸發條件\n"
        "- 排程派工的 Claude 回覆「usage limit / weekly limit」類訊息\n"
        "- 額度類錯誤**不會**重試（重試無用），本班直接結束\n\n"
        "## 影響\n"
        "- 每小時派工會持續以「單次輕量嘗試」自動探測；**額度一恢復下一班就自動復工，無需人工處理**\n"
        "- 發文釋出（release pool）不吃 Claude 額度，照常運作\n\n"
        "## 訊息片段\n\n"
        "```\n" + (log_tail[-500:] if log_tail else "(empty)") + "\n```\n"
    )
    _send("warn", "supervisor quota_blocked（額度恢復後自動復工）", body)
    state.mark_alert_sent(key, path=state_path)
    return True


def send_codex_failover_alert(
    *,
    reason: str,
    recovered: bool,
    exit_code: int,
    detail: str,
    attempted: bool = True,
    output_tail: str = "",
    state_path: Path = state.STATE_PATH,
) -> bool:
    """Claude 掛了、Codex 接手（或也接不了）。Dedup 4h per reason.

    `reason` is the Claude-side failure class ("quota" / "auth"), so a quota
    outage and an auth break each get their own email rather than one muting
    the other.
    """
    key = f"codex_failover_{reason}"
    if state.should_dedup_alert(key, window_s=4 * 3600, path=state_path):
        return False
    claude_side = {
        "quota": "Claude Code 額度用完（會在額度重置時自行恢復）",
        "auth": "Claude CLI 認證失效（**需人工處理**）",
    }.get(reason, f"Claude 端失敗（{reason}）")

    if recovered:
        headline = "# Claude 這班派不了工，已由 Codex 接手完成"
        impact = (
            "- 本班的 Codex-eligible 工作已由 Codex 做掉（ChatGPT 帳號額度，與 Claude 完全獨立）\n"
            "- 讀者向文章 / email 回信 / FB / 論文正文仍只能由 Claude 做，會累積到 Claude 恢復\n"
        )
    elif attempted:
        headline = "# Claude 這班派不了工，Codex 也接不了"
        impact = "- 本班的 hourly slot 沒有產出；兩邊都不可用\n"
    else:
        headline = "# Claude 這班派不了工，Codex failover 未啟動"
        impact = "- 本班的 hourly slot 沒有產出；failover 在真正呼叫 Codex 之前就停住了\n"

    body = (
        f"{headline}\n\n"
        "## 發生什麼事\n"
        f"- Claude 端：{claude_side}\n"
        f"- Codex 端：{detail}（exit code {exit_code}）\n\n"
        "## 影響\n" + impact + "\n"
        "## 需要你做什麼\n"
        + (
            "- Claude 認證要人工修復，指令見另一封 `supervisor auth_blocked` 通知\n"
            if reason == "auth"
            else "- 不用做什麼；額度恢復後下一班自動回到 Claude\n"
        )
        + "\n## Codex 輸出片段\n\n"
        "```\n" + (output_tail[-1500:] if output_tail else "(無輸出)") + "\n```\n"
    )
    level = "warn" if recovered else "critical"
    status = "已接手" if recovered else "接手失敗"
    _send(level, f"Claude→Codex failover {status}（Claude 端：{reason}）", body)
    state.mark_alert_sent(key, path=state_path)
    return True


def read_log_tail(log_path: str, *, limit: int = 2000) -> str:
    """Last `limit` chars of the worker log, for alerts whose caller had no tail
    to hand. health.py used to pass the literal string 'see worker log_path' as
    the tail, which is how the hang mail ended up with a useless body."""
    if not log_path:
        return ""
    try:
        return Path(log_path).read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError as exc:
        LOG.warning("hang alert: cannot read worker log %s: %s", log_path, exc)
        return f"(worker log unreadable: {exc})"


def send_hang_alert(*, job: dict[str, Any], log_tail: str = "", state_path: Path = state.STATE_PATH) -> bool:
    """Hang-killed alert. Dedup 10min."""
    key = f"hang_killed:{job.get('job_id') or job.get('pid') or 'unknown'}"
    if state.should_dedup_alert(key, window_s=600, path=state_path):
        return False

    # 2026-07-11: don't assert the kill landed — report what was observed.
    survivors = job.get("survivors") or []
    if survivors:
        headline = "# ⚠️ Worker hang 了，但 SIGKILL 沒殺掉（孤兒還活著）"
        impact = (
            f"- **pid {survivors} 仍在跑** — macOS 拒絕了 killpg（EPERM）。\n"
            f"- 這個孤兒可能還握著 worktree、還在寫 repo。請手動收：`kill -9 {' '.join(map(str, survivors))}`\n"
            + (
                "- 這個 slot 已隔離保留，不會對仍在寫檔的孤兒跑 PHASE-Z；其他 slot 可繼續。\n"
                if job.get("slot_quarantined")
                else "- 派工 slot 已清掉，下個整點照常 fire（但孤兒不會自己消失）\n"
            )
        )
    else:
        headline = "# Supervisor SIGKILL'd 一個 worker（hang > 50min cap）"
        impact = (
            "- 本輪 hourly fire 沒派工成功；pool 沒消化\n"
            "- 該行程已確認消失；Supervisor 仍存活，下個整點會嘗試新 fire\n"
        )

    # WS-A2b: killing a worker now hands its task-pool claim back to pending in
    # the same breath. Report which ids moved so the boss can tell "the task is
    # queued again" from "the task is stranded" without reading next_tasks.json.
    repended = [str(tid) for tid in (job.get("repended_tasks") or []) if tid]
    if repended:
        impact += f"- 已把該 fire 持有的 task claim 退回 pending：{', '.join(repended)}\n"

    log_path = job.get("log_path") or ""
    tail = log_tail or read_log_tail(log_path)
    body = (
        f"{headline}\n\n"
        f"## Job\n"
        f"- pid: {job.get('pid')}\n"
        f"- pgid: {job.get('pgid')}\n"
        f"- started_at: {job.get('started_at')}\n"
        f"- attempt: {job.get('attempt')}\n"
        f"- model: {job.get('model')}\n"
        f"- log: {log_path or '(unknown)'}\n\n"
        "## 影響\n"
        f"{impact}\n"
        "## Worker log tail\n\n"
        "```\n" + (tail[-2000:] if tail else "(empty)") + "\n```\n"
    )
    _send("critical", "supervisor hang_killed", body)
    state.mark_alert_sent(key, path=state_path)
    return True


def send_silent_death_alert(*, job: dict[str, Any], state_path: Path = state.STATE_PATH) -> bool:
    """Worker PID died but no completion record. Dedup 10min."""
    key = f"silent_death:{job.get('job_id') or job.get('pid') or 'unknown'}"
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


def send_supervisor_restart(
    *,
    prev_started: str | None,
    planned_reason: str | None = None,
    state_path: Path = state.STATE_PATH,
) -> bool:
    """Supervisor (re)started under launchd KeepAlive. Dedup 60s.

    `planned_reason` set (a fresh planned-restart marker was consumed at boot)
    means this restart was a deliberate `kickstart -k` reload — deploy noise,
    NOT a crash. Downgrade to a log-only breadcrumb and send NO email. An
    absent/expired marker (`planned_reason is None`) keeps the INFO alert so a
    genuinely unexpected KeepAlive respawn still reaches the owner."""
    if planned_reason is not None:
        LOG.info(
            "supervisor restart suppressed as planned reload (reason=%s, prev_started=%s)",
            planned_reason, prev_started,
        )
        return False
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
    *, job: dict[str, Any], killed: bool, outcome: str = "", state_path: Path = state.STATE_PATH,
) -> bool:
    """Supervisor boot found a stale `current_job` from a crashed prior
    instance (Codex review §10 #3). `killed=True` means the orphan process
    was still alive and identity-verified before being force-killed;
    `killed=False` covers every other case — already gone, pid reused, no
    fingerprint ever recorded (unverified), or the reservation never even
    reached a real pid before the crash (see `procutil.check_identity` and
    the `outcome` string, which names the exact case — passed straight from
    `supervisor._handle_restart_orphan()`'s completion-entry outcome)."""
    key = f"orphan_restart:{job.get('job_id') or job.get('pid') or 'unknown'}"
    if state.should_dedup_alert(key, window_s=60, path=state_path):
        return False
    body = (
        "# Supervisor restart found an orphaned job from a crashed prior instance\n\n"
        f"- pid: {job.get('pid')} pgid: {job.get('pgid')}\n"
        f"- schedule_id: {job.get('schedule_id')} attempt: {job.get('attempt')} model: {job.get('model')}\n"
        f"- started_at: {job.get('started_at')}\n"
        f"- outcome: {outcome or '(unspecified)'}\n"
        f"- action: {'identity-verified SIGKILL issued' if killed else '未發送 kill signal'}\n\n"
        "## 影響\n"
        "- 前一個 supervisor process 非正常結束（crash / OOM-kill / manual kill -9）；"
        "worker 因 `start_new_session=True` 不會隨 supervisor 一起死，此次是補做清理\n"
        + (
            "\n## ⚠️ 需人工檢查\n"
            "- 這個 process 的身分指紋缺失，supervisor 拒絕對無法驗證的 pid 發 kill —— "
            "它可能還活著。照 runbook 處理：`docs/runbooks/dispatch-supervisor-unverified-orphan.md`\n"
            if "unverified" in (outcome or "") else ""
        )
    )
    _send("warn", "supervisor orphan_restart", body)
    state.mark_alert_sent(key, path=state_path)
    return True
