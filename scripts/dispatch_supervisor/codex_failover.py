"""Claude→Codex failover — hand the hourly slot to `codex exec` when Claude can't run.

Ported from `cron_hourly_dispatch.sh::run_codex_failover()` (2026-06-28 owner
directive「claude -p 失敗 → codex exec 重跑同任務」). The 2026-07-04 cutover moved
dispatch onto the supervisor daemon but left failover behind in the retired shell
wrapper: worker.py classified quota/auth correctly, then only aborted the fire and
emailed. Result — every quota outage silently dropped its hourly slots even though
Codex authenticates through ChatGPT (`~/.codex`), an entirely separate quota.

Design notes carried over from the shell version (both were incident fixes):

* **Local-binary preflight** (`codex --version`, ~80ms, 0 tokens) so a missing or
  broken binary aborts before we spend a task on it.
* **Timeout ≠ broken binary.** A preflight that exceeds its ceiling means the host
  is loaded, not that codex is dead — reported as warn, retried next fire.

2026-07-12 — two bugs, one root cause (owner: 「立刻找出原因 為什麼 codex exec 不能用」):

The original design note here read *"short failover cap (10min, not the 50min hourly
cap): if the ChatGPT API is also down, the fire ends with room to spare."* That makes
the cap do a job it cannot do. The cap measures how long the WORK takes; the thing it
was asked to detect is whether the API is UP. Those come apart immediately, because
the prompt we hand Codex is a full hourly task — claim a pending task, finish it,
commit — and a real task takes 20-60 minutes. So a perfectly healthy Codex was being
SIGKILLed at 600s on every failover, and the timeout branch then reported the one
thing it had no evidence for: 「ChatGPT 端可能同時不可用」. It is the same shape as the
3-STRIKE the hourly prompt already carries — a 60-minute job in a 10-minute container —
and the false diagnosis is what sent the owner looking for a CLI regression that was
never there (`codex exec` answered a smoke prompt in 13s the morning of the report).

So the two concerns are now measured separately, each by something that can actually
see it:

* **Reachability probe** — a trivial `codex exec` round-trip. This is the only thing
  here that touches ChatGPT, so it is the only thing entitled to claim the API is
  down. Cheap (a few hundred tokens) and bounded in seconds.
* **Work cap** — sized for the task we actually hand over, and applied only once the
  probe says the API answers. A timeout past that point means the task ran long, and
  says so; it no longer indicts an API that just proved it was alive.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import identity, isolation, procutil
from .report_contract import inject_external_report_contract

LOG = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]

# nvm-installed codex is not on the LaunchAgent PATH; keep the absolute path as
# the last resort after $CODEX_BIN and a PATH lookup.
_NVM_CODEX = "/Users/yhlai0911/.nvm/versions/node/v22.20.0/bin/codex"

PROMPT_PATH = ROOT / "scripts" / "cron_hourly_dispatch_codex_failover_prompt.md"

# Used only if the prompt file is missing — keeps failover functional rather than
# skipping the slot over a deleted file.
FALLBACK_PROMPT = inject_external_report_contract(
    "新一輪 hourly tick（Claude dispatch 失敗 failover）。cat storage/ops/handoff_latest.md，"
    "依同樣流程 claim 下一個 Codex-eligible pending task → 完整完成 → complete → "
    "用 scripts/git_writer_lock.py commit 提交 [codex]。"
    "reader-facing / email_reply / FB / paper_body 類留給 Claude，不要碰。"
)

PREFLIGHT_TIMEOUT_S = int(os.environ.get("CODEX_PREFLIGHT_TIMEOUT_SEC", "30"))

# Does ChatGPT answer at all? A round-trip with a throwaway prompt — the cheapest
# question whose answer is the one the timeout branch used to guess at.
REACHABILITY_TIMEOUT_S = int(os.environ.get("CODEX_REACHABILITY_TIMEOUT_SEC", "90"))
REACHABILITY_PROMPT = "reply with exactly: OK"

# Sized for the work, now that reachability is measured on its own. The handover
# prompt is a whole hourly task (claim → finish → commit); at 600s it could only ever
# have killed healthy work mid-flight. Kept under the fire's own 3000s ceiling so the
# supervisor still ends the slot with room before the next hour.
FAILOVER_CAP_S = int(os.environ.get("CODEX_FAILOVER_CAP_SEC", "2400"))

# Escape hatch: VOLPRED_CODEX_FAILOVER=0 disables failover without a code change.
ENABLED = os.environ.get("VOLPRED_CODEX_FAILOVER", "1") != "0"

# Safe default under pytest. `codex exec` is not a read-only probe — it claims a
# task from next_tasks.json, does real work, and commits. Any test that drives
# worker.run_worker() down the quota/auth branch without patching this module
# would otherwise dispatch real work from a test run (caught 2026-07-10, when
# the existing `test_worker_auth_blocks_without_retry` began spawning codex).
# Tests that mean to exercise failover pass `enabled=True` explicitly.
def _under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "PYTEST_VERSION" in os.environ

# Sentinel exit codes (distinct from any codex exit code we'd act on)
RC_BINARY_MISSING = 127
RC_PREFLIGHT_TIMEOUT = 142  # matches the shell version's perl SIGALRM code
RC_DISABLED = -3
RC_UNREACHABLE = -4   # the probe could not get an answer out of ChatGPT
RC_WORK_TIMEOUT = -5  # ChatGPT answered the probe; the task itself then ran long


@dataclass
class FailoverResult:
    attempted: bool
    recovered: bool
    exit_code: int
    detail: str          # human-readable, goes into the alert body
    duration_s: float = 0.0
    output_tail: str = ""
    process_active: bool = False  # tracked Popen may still be alive after refused kill


def resolve_codex_bin() -> str | None:
    """First of $CODEX_BIN, `which codex`, the known nvm path — or None.

    Also puts the binary's own dir on PATH: codex's shebang is `env node`, so a
    caller without the nvm bin dir cannot run even an absolute codex.
    """
    for candidate in (os.environ.get("CODEX_BIN"), shutil.which("codex"), _NVM_CODEX):
        if candidate and os.access(candidate, os.X_OK):
            # NOT .resolve(): bin/codex symlinks into lib/node_modules/, no node there.
            bin_dir = str(Path(candidate).absolute().parent)
            parts = os.environ.get("PATH", "").split(os.pathsep)
            if bin_dir not in parts:
                os.environ["PATH"] = os.pathsep.join([bin_dir, *parts])
            return candidate
    return None


def preflight(codex_bin: str, *, timeout_s: int = PREFLIGHT_TIMEOUT_S) -> tuple[bool, int, str]:
    """`codex --version`. Returns (ok, rc, detail)."""
    try:
        result = subprocess.run(
            [codex_bin, "--version"],
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return False, RC_PREFLIGHT_TIMEOUT, (
            f"`codex --version` 逾時（{timeout_s}s 上限）——通常是主機負載過高，"
            "不是 binary 損壞；下一班會自行重試"
        )
    except OSError as exc:
        return False, RC_BINARY_MISSING, f"無法執行 codex binary：{exc}"
    if result.returncode != 0:
        return False, result.returncode, (
            f"`codex --version` rc={result.returncode}（非逾時）——binary 或 node runtime 可能損壞"
        )
    return True, 0, (result.stdout or "").strip()


def check_reachable(codex_bin: str, *, timeout_s: int = REACHABILITY_TIMEOUT_S) -> tuple[bool, int, str]:
    """Can we get an answer out of ChatGPT? Returns (ok, rc, detail).

    `codex --version` never leaves the host, so nothing in the old preflight could
    tell a dead API from a slow task — and the exec timeout branch filled that gap by
    guessing. This is the probe that actually knows: a throwaway round-trip, bounded
    in seconds, whose failure is real evidence the API is unavailable.
    """
    try:
        result = subprocess.run(
            [codex_bin, "exec", "--skip-git-repo-check", REACHABILITY_PROMPT],
            cwd=str(ROOT), capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return False, RC_UNREACHABLE, (
            f"ChatGPT 沒有回應（{timeout_s}s 內連一句話都答不出來）——"
            "Codex 這條路這班走不通，下一班重試"
        )
    except OSError as exc:
        return False, RC_BINARY_MISSING, f"`codex exec` 無法啟動：{exc}"
    if result.returncode != 0:
        tail = ((result.stdout or "") + (result.stderr or "")).strip()[-400:]
        return False, RC_UNREACHABLE, (
            f"ChatGPT 拒絕回應（rc={result.returncode}）——通常是額度用完或認證過期。"
            f"輸出：{tail or '(無)'}"
        )
    return True, 0, "ChatGPT 有回應"


def _read_prompt(prompt_path: Path) -> str:
    try:
        text = prompt_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        LOG.warning("failover prompt unreadable path=%s error=%s — using inline fallback", prompt_path, exc)
        return FALLBACK_PROMPT
    if not text:
        LOG.warning("failover prompt empty path=%s — using inline fallback", prompt_path)
        return FALLBACK_PROMPT
    return inject_external_report_contract(text)


def run_codex_failover(
    *,
    reason: str,
    prompt_path: Path = PROMPT_PATH,
    cap_s: int = FAILOVER_CAP_S,
    preflight_timeout_s: int = PREFLIGHT_TIMEOUT_S,
    reachability_timeout_s: int = REACHABILITY_TIMEOUT_S,
    enabled: bool | None = None,
    slot_id: str | None = None,
    job_id: str | None = None,
    on_process_started: Callable[[int, int], bool] | None = None,
    on_process_finished: Callable[[int], None] | None = None,
    workdir: Path | None = None,
    isolated_workspace: dict | None = None,
) -> FailoverResult:
    """Try to let `codex exec` cover this hourly slot. Never raises."""
    if enabled is None:
        if _under_pytest():
            LOG.warning("codex failover suppressed under pytest (pass enabled=True to exercise it)")
            return FailoverResult(False, False, RC_DISABLED, "failover 在 pytest 下預設停用")
        enabled = ENABLED
    if not enabled:
        LOG.info("codex failover disabled via VOLPRED_CODEX_FAILOVER=0")
        return FailoverResult(False, False, RC_DISABLED, "failover 已由 VOLPRED_CODEX_FAILOVER=0 停用")

    codex_bin = resolve_codex_bin()
    if not codex_bin:
        LOG.warning("codex binary not found — cannot failover")
        return FailoverResult(False, False, RC_BINARY_MISSING, "找不到可執行的 codex binary")

    ok, rc, detail = preflight(codex_bin, timeout_s=preflight_timeout_s)
    if not ok:
        LOG.warning("codex preflight failed rc=%d: %s", rc, detail)
        return FailoverResult(False, False, rc, detail)
    version = detail

    # Ask ChatGPT whether it is there, before betting the slot on it. `attempted=False`:
    # no task was claimed, so this is a skipped slot, not a failed handover.
    reachable, rc, detail = check_reachable(codex_bin, timeout_s=reachability_timeout_s)
    if not reachable:
        LOG.warning("codex unreachable rc=%d: %s", rc, detail)
        return FailoverResult(False, False, rc, detail)

    LOG.info("codex failover start reason=%s cap=%ds version=%s", reason, cap_s, version)
    started = time.time()
    prompt = _read_prompt(prompt_path)
    launch_cwd = (workdir or ROOT).resolve()
    if slot_id and job_id:
        prefix = f"dispatch-{slot_id}-{job_id[:8]}"
        prompt = (
            "[Supervisor multi-slot context]\n"
            f"slot_id={slot_id}; job_id={job_id}; worktree_prefix={prefix}.\n"
            f"launcher_cwd={launch_cwd}（刻意不是 shared main）；canonical_root={ROOT}.\n"
            "用絕對路徑在 canonical_root 完成 task，禁止裸 Git mutation；依下方第 5 步"
            "用 canonical exact-path locked commit helper 提交。只有 routing 明定 experiment/"
            "worktree 時才建立 worktree，且本輪須用正式 merge_worktree.sh 整合完畢。"
            "task-pool CLI 必須使用 canonical_root 的絕對 script path。\n\n"
            + prompt
        )
    argv = [codex_bin, "exec", "--skip-git-repo-check", "-s", "danger-full-access", prompt]
    child_env = {**os.environ}
    if slot_id and job_id:
        child_env.update({
            "VOLPRED_ACTOR": f"codex-failover:{slot_id}:{job_id[:8]}",
            "VOLPRED_DISPATCH_SLOT": slot_id,
            "VOLPRED_DISPATCH_JOB_ID": job_id,
            "VOLPRED_TASK_CLAIM_OWNER": identity.task_claim_owner(
                role="codex-failover", slot_id=slot_id, job_id=job_id,
            ),
        })
    if isolated_workspace is not None:
        expected_workspace = Path(
            str(isolated_workspace.get("path") or "")
        ).resolve()
        if workdir is None or launch_cwd != expected_workspace or not job_id:
            return FailoverResult(
                True,
                False,
                RC_DISABLED,
                "Codex failover isolation identity mismatch; refusing unisolated execution",
            )
        isolation_receipt = {
            key.removeprefix("isolation_"): value
            for key, value in isolated_workspace.items()
            if key.startswith("isolation_")
        }
        try:
            if not isinstance(isolation_receipt, dict):
                raise isolation.IsolationUnavailable(
                    "Codex failover isolation was not prepared during admission"
                )
            argv = isolation.wrap_prepared(argv, isolation_receipt)
        except isolation.IsolationUnavailable as exc:
            return FailoverResult(
                True,
                False,
                RC_DISABLED,
                f"Codex failover isolation unavailable: {exc}",
            )
        child_env = isolation.isolated_environment(child_env, isolation_receipt)
    tracked_pid: int | None = None
    process_confirmed_finished = False
    try:
        if on_process_started is None:
            result = subprocess.run(
                argv, cwd=str(launch_cwd), capture_output=True, text=True,
                timeout=cap_s, env=child_env,
            )
        else:
            proc = subprocess.Popen(
                argv, cwd=str(launch_cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=True, start_new_session=True, env=child_env,
            )
            tracked_pid = proc.pid
            pgid = os.getpgid(proc.pid)
            if not on_process_started(proc.pid, pgid):
                group_drained = procutil.kill_pgid(pgid)
                stdout, _ = proc.communicate(timeout=10)
                process_confirmed_finished = group_drained
                result = subprocess.CompletedProcess(argv, proc.returncode or 1, stdout, "")
            else:
                try:
                    stdout, _ = proc.communicate(timeout=cap_s)
                except subprocess.TimeoutExpired as exc:
                    group_drained = procutil.kill_pgid(pgid)
                    stdout, _ = proc.communicate(timeout=15)
                    process_confirmed_finished = group_drained
                    raise subprocess.TimeoutExpired(
                        cmd=exc.cmd, timeout=cap_s, output=stdout,
                    ) from exc
                result = subprocess.CompletedProcess(argv, proc.returncode, stdout, "")
                process_confirmed_finished = procutil.pgid_members_checked(pgid) == []
    except subprocess.TimeoutExpired as exc:
        duration = time.time() - started
        tail = (exc.output or "")[-2000:] if isinstance(exc.output, str) else ""
        LOG.warning("codex exec timed out after %ds", cap_s)
        # ChatGPT answered the probe minutes ago, so this is NOT an outage — it is a
        # task that ran past its ceiling. Saying otherwise is what sent the owner
        # hunting a CLI regression that did not exist (2026-07-12).
        return FailoverResult(
            True, False, RC_WORK_TIMEOUT,
            f"Codex 接手了，但任務沒在 {cap_s // 60} 分鐘內做完（ChatGPT 本身是通的——"
            "接手前已測過）。任務可能太大，需要切小或改走 compute queue",
            duration, tail,
            process_active=tracked_pid is not None and not process_confirmed_finished,
        )
    except OSError as exc:
        duration = time.time() - started
        return FailoverResult(
            True, False, RC_BINARY_MISSING, f"`codex exec` 無法啟動：{exc}", duration,
            process_active=tracked_pid is not None and not process_confirmed_finished,
        )
    finally:
        if tracked_pid is not None and process_confirmed_finished and on_process_finished is not None:
            try:
                on_process_finished(tracked_pid)
            except Exception as exc:  # callback is observability, never mask result
                LOG.warning("codex failover finish callback failed pid=%s: %s", tracked_pid, exc)

    duration = time.time() - started
    combined = ((result.stdout or "") + (result.stderr or ""))[-2000:]
    if tracked_pid is not None and not process_confirmed_finished:
        return FailoverResult(
            True, False, RC_WORK_TIMEOUT,
            "Codex parent 已退出，但同一 process group 仍有程序或無法確認已清空；"
            "保留 PID 並隔離此 slot，禁止 PHASE-Z。",
            duration, combined, process_active=True,
        )
    recovered = result.returncode == 0
    LOG.info("codex failover rc=%d recovered=%s duration=%.1fs", result.returncode, recovered, duration)
    return FailoverResult(
        True, recovered, result.returncode,
        "Codex 接手成功" if recovered else f"`codex exec` rc={result.returncode}",
        duration, combined,
    )
