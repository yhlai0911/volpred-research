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
* **Short failover cap (10min, not the 50min hourly cap).** If the ChatGPT API is
  also down, the fire ends with room to spare before the next hourly slot.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

LOG = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]

# nvm-installed codex is not on the LaunchAgent PATH; keep the absolute path as
# the last resort after $CODEX_BIN and a PATH lookup.
_NVM_CODEX = "/Users/yhlai0911/.nvm/versions/node/v22.20.0/bin/codex"

PROMPT_PATH = ROOT / "scripts" / "cron_hourly_dispatch_codex_failover_prompt.md"

# Used only if the prompt file is missing — keeps failover functional rather than
# skipping the slot over a deleted file.
FALLBACK_PROMPT = (
    "新一輪 hourly tick（Claude dispatch 失敗 failover）。cat storage/ops/handoff_latest.md，"
    "依同樣流程 claim 下一個 Codex-eligible pending task → 完整完成 → complete → commit [codex]。"
    "reader-facing / email_reply / FB / paper_body 類留給 Claude，不要碰。"
)

PREFLIGHT_TIMEOUT_S = int(os.environ.get("CODEX_PREFLIGHT_TIMEOUT_SEC", "30"))
FAILOVER_CAP_S = int(os.environ.get("CODEX_FAILOVER_CAP_SEC", "600"))

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


@dataclass
class FailoverResult:
    attempted: bool
    recovered: bool
    exit_code: int
    detail: str          # human-readable, goes into the alert body
    duration_s: float = 0.0
    output_tail: str = ""


def resolve_codex_bin() -> str | None:
    """First of $CODEX_BIN, `which codex`, the known nvm path — or None."""
    for candidate in (os.environ.get("CODEX_BIN"), shutil.which("codex"), _NVM_CODEX):
        if candidate and os.access(candidate, os.X_OK):
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


def _read_prompt(prompt_path: Path) -> str:
    try:
        text = prompt_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        LOG.warning("failover prompt unreadable path=%s error=%s — using inline fallback", prompt_path, exc)
        return FALLBACK_PROMPT
    if not text:
        LOG.warning("failover prompt empty path=%s — using inline fallback", prompt_path)
        return FALLBACK_PROMPT
    return text


def run_codex_failover(
    *,
    reason: str,
    prompt_path: Path = PROMPT_PATH,
    cap_s: int = FAILOVER_CAP_S,
    preflight_timeout_s: int = PREFLIGHT_TIMEOUT_S,
    enabled: bool | None = None,
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

    LOG.info("codex failover start reason=%s cap=%ds version=%s", reason, cap_s, detail)
    started = time.time()
    prompt = _read_prompt(prompt_path)
    try:
        result = subprocess.run(
            [codex_bin, "exec", "--skip-git-repo-check", "-s", "workspace-write", prompt],
            cwd=str(ROOT), capture_output=True, text=True, timeout=cap_s,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.time() - started
        tail = (exc.output or "")[-2000:] if isinstance(exc.output, str) else ""
        LOG.warning("codex exec timed out after %ds", cap_s)
        return FailoverResult(
            True, False, RC_PREFLIGHT_TIMEOUT,
            f"`codex exec` 逾時（{cap_s}s 上限）——ChatGPT 端可能同時不可用",
            duration, tail,
        )
    except OSError as exc:
        duration = time.time() - started
        return FailoverResult(True, False, RC_BINARY_MISSING, f"`codex exec` 無法啟動：{exc}", duration)

    duration = time.time() - started
    combined = ((result.stdout or "") + (result.stderr or ""))[-2000:]
    recovered = result.returncode == 0
    LOG.info("codex failover rc=%d recovered=%s duration=%.1fs", result.returncode, recovered, duration)
    return FailoverResult(
        True, recovered, result.returncode,
        "Codex 接手成功" if recovered else f"`codex exec` rc={result.returncode}",
        duration, combined,
    )
