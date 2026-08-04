#!/usr/bin/env bash
# Bounded `agy --print` — the only sanctioned way to call agy from a Bash tool call.
#
# Why this exists (2026-08-04):
# codex had `codex_exec_bounded.sh`, agy had nothing. So when Codex was denied by
# provider policy mid-session, the most convenient way to reach the fallback was
# `subprocess.run(["agy", ...])` straight to the binary — which skips
# `authorize_provider_spawn` entirely. Three independent experiment reviews
# (K1746, K1747, K1735) ran that way. No paid API was touched (agy is Google
# subscription OAuth), but the control was bypassed rather than satisfied, and a
# missing wrapper is what made bypassing the path of least resistance.
#
# Owner principle: claude, codex and agy all run on subscription OAuth quota.
# Never a metered API key.
#
# Environment sanitisation (the substantive difference from the codex wrapper):
# the registry denies a spawn when the parent environment carries any of the 28
# forbidden API-key / alternate-endpoint variables. Inside a Claude Code session
# ANTHROPIC_BASE_URL is always present — injected by the harness and set to the
# official default endpoint — so the check fails on a variable that grants
# nothing. Denying is also weaker than it looks: it stops the sanctioned path
# while an unsanctioned direct call inherits the whole environment anyway.
# This wrapper strips those variables BEFORE authorising, and spawns with that
# same stripped environment. The attested environment and the real child
# environment are identical, and the child provably cannot reach a paid API.
#
# Usage:
#   bash scripts/agy_exec_bounded.sh [--timeout N] [--contract ID] <agy args...>
#   printf '%s' "$PROMPT" | bash scripts/agy_exec_bounded.sh --timeout 600 --print -
#
# Default timeout 600s, default contract prepublish-audit.agy (research-review).
# Exit 124 = timed out. Exit 126 = provider policy denied. Exit 127 = agy missing.
#
# For heavy work you would not sit and watch, enqueue it instead:
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
CONTRACT_ID="prepublish-audit.agy"
while [[ "${1:-}" == --timeout || "${1:-}" == --contract ]]; do
  case "$1" in
    --timeout)  TIMEOUT_S="${2:?--timeout needs a value}"; shift 2 ;;
    --contract) CONTRACT_ID="${2:?--contract needs a value}"; shift 2 ;;
  esac
done

if [[ $# -eq 0 ]]; then
  echo "usage: $0 [--timeout N] [--contract ID] <agy args...>" >&2
  exit 2
fi

export VOLPRED_AGY_CONTRACT="$CONTRACT_ID"

# Python watchdog rather than gtimeout: macOS ships no coreutils timeout, and
# start_new_session + killpg takes down the whole tree instead of only the
# direct child, while keeping the GNU-timeout exit convention callers check.
exec "$PYTHON_BIN" -c '
import json, os, shutil, signal, subprocess, sys
repo_root = os.environ["VOLPRED_REPO_ROOT"]
sys.path.insert(0, os.path.join(repo_root, "src"))
from volpred.ops import termination
from volpred.ops.execution.registry import (
    DEFAULT_REGISTRY_PATH,
    ProviderRegistryError,
    authorize_provider_spawn,
    sanitize_provider_spawn_environment,
    verify_spawn_receipt,
)

def resolve_agy():
    found = os.environ.get("AGY_BIN")
    if found and os.access(found, os.X_OK):
        return found
    for cand in (
        os.path.expanduser("~/.local/bin/agy"),
        "/opt/homebrew/bin/agy",
        "/usr/local/bin/agy",
    ):
        if os.access(cand, os.X_OK):
            return cand
    found = shutil.which("agy")
    return found or "agy"

def registered_model(provider_id):
    """Only the model id; env stripping belongs to the canonical sanitizer."""
    payload = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
    for provider in payload["providers"]:
        if provider.get("provider_id") == provider_id:
            models = provider.get("model_ids") or []
            if not models:
                raise ProviderRegistryError(
                    f"provider {provider_id!r} registers no model_ids"
                )
            return models[0]
    raise ProviderRegistryError(f"provider {provider_id!r} absent from registry")

timeout = float(sys.argv[1])
contract_id = os.environ["VOLPRED_AGY_CONTRACT"]
agy_bin = resolve_agy()

try:
    model_id = registered_model("agy-cli")
    # Canonical owner: registry.sanitize_provider_spawn_environment. Do not
    # reimplement the stripping here -- one owner per concern.
    clean_env, stripped = sanitize_provider_spawn_environment(
        contract_id=contract_id, environment=os.environ,
    )
    receipt = authorize_provider_spawn(
        contract_id=contract_id,
        model_id=model_id,
        executable_path=agy_bin,
        environment=clean_env,
    )
    verify_spawn_receipt(receipt)
except ProviderRegistryError as exc:
    print(f"ERROR: provider policy denied agy: {exc}", file=sys.stderr)
    sys.exit(126)

if stripped:
    print(
        "[agy_exec_bounded] stripped from child env: " + ", ".join(stripped),
        file=sys.stderr,
    )

child_env = {**clean_env, **receipt.environment(), "ANTIGRAVITY_MODEL": model_id}
try:
    proc = subprocess.Popen(
        [receipt.resolved_executable, *sys.argv[2:]],
        start_new_session=True,
        env=child_env,
    )
except FileNotFoundError:
    print("ERROR: agy CLI not found on PATH", file=sys.stderr)
    sys.exit(127)

try:
    sys.exit(proc.wait(timeout=timeout))
except subprocess.TimeoutExpired:
    intent = termination.arm(
        target_kind="pgid", target_id=proc.pid,
        reason="bounded_agy_timeout", actor="agy_exec_bounded",
        signal_sequence=[signal.SIGKILL],
    )
    try:
        termination.send_pgid(intent, signal.SIGKILL)
    except (ProcessLookupError, PermissionError) as exc:
        print(f"WARN: killpg failed ({exc}); killing pid only", file=sys.stderr)
        pid_intent = termination.arm(
            target_kind="pid", target_id=proc.pid,
            reason="bounded_agy_timeout_pid_fallback",
            actor="agy_exec_bounded", signal_sequence=[signal.SIGKILL],
        )
        termination.send_pid(pid_intent, signal.SIGKILL)
    proc.wait()
    print(f"\nERROR: agy exceeded {timeout:.0f}s — killed", file=sys.stderr)
    sys.exit(124)
' "$TIMEOUT_S" "$@"
