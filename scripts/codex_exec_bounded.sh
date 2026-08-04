#!/usr/bin/env bash
# Bounded `codex exec` — the only sanctioned way to call codex from a Bash tool call.
#
# Why this exists (2026-07-11, boss Telegram msg 465):
# a hourly agent ran `codex exec` inline to re-render a lazypack. The call hung
# with zero output for >30 min, the agent sat blocked in Bash with no timeout of
# its own, and it rode straight into the supervisor's 3000s hard cap → SIGKILL →
# hang_killed. The agent had no way to bound it: macOS ships no coreutils
# `timeout`, so "just add a timeout" was not actually available to anyone.
# Now it is, and `.claude/hooks/pretooluse-bash-optimizer.sh` denies the bare form.
#
# Usage:
#   bash scripts/codex_exec_bounded.sh [--timeout N] <codex exec args...>
#   bash scripts/codex_exec_bounded.sh --timeout 300 -s workspace-write "review this"
#   printf '%s' "$PROMPT" | bash scripts/codex_exec_bounded.sh --timeout 600 -s read-only -
#
# Default timeout: 600s. Exit 124 = timed out (same convention as GNU timeout).
#
# For HEAVY agentic work (lazypack renders, long reviews, anything you would not
# sit and watch), do not use this at all — enqueue it:
#   uv run python scripts/compute_queue.py enqueue --script <path> --timeout 1800
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "ERROR: repo Python missing: $PYTHON_BIN" >&2
  exit 127
fi
export VOLPRED_REPO_ROOT="$REPO_ROOT"

TIMEOUT_S=600
if [[ "${1:-}" == "--timeout" ]]; then
  TIMEOUT_S="${2:?--timeout needs a value}"
  shift 2
fi

if [[ $# -eq 0 ]]; then
  echo "usage: $0 [--timeout N] <codex exec args...>" >&2
  exit 2
fi

# A python watchdog rather than gtimeout/perl-alarm, for two reasons found while
# testing this script: perl's `alarm` + `exec` leaves a pending SIGALRM in the
# EXEC'D process, so the handler is gone and the shell reports 142 (128+SIGALRM)
# instead of 124 — and either way only codex itself is signalled, not the tools
# it spawned. `start_new_session` + `killpg` takes the whole tree down and keeps
# the GNU-timeout exit convention that callers actually check for.
exec "$PYTHON_BIN" -c '
import glob, os, shutil, signal, subprocess, sys
repo_root = os.environ["VOLPRED_REPO_ROOT"]
sys.path.insert(0, os.path.join(repo_root, "src"))
from volpred.ops import termination
from volpred.ops.execution.registry import (
    ProviderRegistryError,
    authorize_provider_spawn,
    verify_spawn_receipt,
)

def resolve_codex():
    # Prefer the owner-pinned nvm surface. Codex Desktop injects its bundled
    # binary ahead of nvm in some sessions; that is a different executable
    # identity and must not silently replace the registry-pinned CLI.
    found = os.environ.get("CODEX_BIN")
    if found and os.access(found, os.X_OK):
        return found
    for pattern in (os.path.expanduser("~/.nvm/versions/node/*/bin/codex"),):
        for cand in glob.glob(pattern):
            if os.access(cand, os.X_OK):
                return cand
    found = shutil.which("codex")
    if found and os.access(found, os.X_OK):
        return found
    for pattern in ("/opt/homebrew/bin/codex", "/usr/local/bin/codex"):
        for cand in glob.glob(pattern):
            if os.access(cand, os.X_OK):
                return cand
    return "codex"

timeout = float(sys.argv[1])
codex_bin = resolve_codex()
# codex has an `env node` shebang: without the nvm bin dir on PATH, an absolute
# codex still dies with "env: node: No such file". Put its own dir on PATH too.
bin_dir = os.path.dirname(os.path.abspath(codex_bin))  # NOT realpath: bin/codex is a symlink into lib/node_modules, where node is not
if bin_dir and bin_dir not in os.environ.get("PATH", "").split(os.pathsep):
    os.environ["PATH"] = os.pathsep.join([bin_dir, os.environ.get("PATH", "")])
model = "gpt-5.6-sol"
contract_id = os.environ.get(
    "VOLPRED_CODEX_EXEC_CONTRACT",
    "bounded-codex.agentic",
)
def forbidden_env_for(provider_id):
    """Read the forbidden set from the registry so this cannot drift from policy."""
    import json
    from volpred.ops.execution.registry import DEFAULT_REGISTRY_PATH
    payload = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    for provider in payload["providers"]:
        if provider.get("provider_id") == provider_id:
            return frozenset(provider["auth"]["forbidden_env"])
    raise ProviderRegistryError(f"provider {provider_id!r} absent from registry")

# Strip the forbidden API-key / alternate-endpoint variables BEFORE authorising,
# and spawn with that same stripped environment, so the attested environment and
# the real child environment are identical. Inside a Claude Code session
# ANTHROPIC_BASE_URL is always present (harness-injected, pointing at the official
# default endpoint), which denied every sanctioned codex spawn while granting the
# child nothing. Denying was also weaker than it looked: it blocked the wrapper
# while a raw `codex exec` inherited the whole environment. Owner principle
# (2026-08-04): claude, codex and agy all run on subscription OAuth quota.
try:
    forbidden = forbidden_env_for("codex-cli")
    clean_env = {k: v for k, v in os.environ.items() if k not in forbidden}
    stripped = sorted(set(os.environ) & forbidden)
    receipt = authorize_provider_spawn(
        contract_id=contract_id,
        model_id=model,
        executable_path=codex_bin,
        environment=clean_env,
    )
    verify_spawn_receipt(receipt)
except ProviderRegistryError as exc:
    print(f"ERROR: provider policy denied codex: {exc}", file=sys.stderr)
    sys.exit(126)
if stripped:
    print(
        "[codex_exec_bounded] stripped from child env: " + ", ".join(stripped),
        file=sys.stderr,
    )
child_env = {**clean_env, **receipt.environment()}
proc = subprocess.Popen(
    [receipt.resolved_executable, "exec", "-m", model, *sys.argv[2:]],
    start_new_session=True,
    env=child_env,
)
try:
    sys.exit(proc.wait(timeout=timeout))
except subprocess.TimeoutExpired:
    intent = termination.arm(
        target_kind="pgid", target_id=proc.pid,
        reason="bounded_codex_timeout", actor="codex_exec_bounded",
        signal_sequence=[signal.SIGKILL],
    )
    try:
        termination.send_pgid(intent, signal.SIGKILL)
    except (ProcessLookupError, PermissionError) as exc:
        print(f"WARN: killpg failed ({exc}); killing pid only", file=sys.stderr)
        pid_intent = termination.arm(
            target_kind="pid", target_id=proc.pid,
            reason="bounded_codex_timeout_pid_fallback",
            actor="codex_exec_bounded", signal_sequence=[signal.SIGKILL],
        )
        termination.send_pid(pid_intent, signal.SIGKILL)
    proc.wait()
    print(f"\nERROR: codex exec exceeded {timeout:.0f}s — killed", file=sys.stderr)
    sys.exit(124)
except FileNotFoundError:
    print("ERROR: codex CLI not found on PATH", file=sys.stderr)
    sys.exit(127)
' "$TIMEOUT_S" "$@"
