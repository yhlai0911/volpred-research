#!/bin/bash
# Regression: graphify-first nudge in pretooluse-bash-optimizer (2026-08-05, boss email-12201).
# Locks: recursive/dir-wide code greps get the HINT (additionalContext, never deny);
# single-file greps and graphify-mentioning commands stay silent; deny rules untouched.
set -euo pipefail
HOOK="$(cd "$(dirname "$0")/../.." && pwd)/.claude/hooks/pretooluse-bash-optimizer.sh"
pass=0; fail=0

run_hook() { printf '%s' "$1" | /bin/bash "$HOOK"; }
mk() { jq -nc --arg c "$1" '{tool_input:{command:$c}, cwd:"/tmp"}'; }

expect_hint() {
  out="$(run_hook "$(mk "$1")")"
  if printf '%s' "$out" | jq -e '.hookSpecificOutput.additionalContext // ""' | grep -q graphify \
     && ! printf '%s' "$out" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1; then
    pass=$((pass+1)); echo "PASS hint: $1"
  else
    fail=$((fail+1)); echo "FAIL hint: $1 -> $out"
  fi
}
expect_silent() {
  out="$(run_hook "$(mk "$1")")"
  if printf '%s' "$out" | jq -e '(.hookSpecificOutput.additionalContext // "")' 2>/dev/null | grep -q graphify; then
    fail=$((fail+1)); echo "FAIL silent: $1 -> $out"
  else
    pass=$((pass+1)); echo "PASS silent: $1"
  fi
}

expect_hint 'rg -n "authorize_provider_spawn" src/'
expect_hint 'grep -rn "worker_orphaned" scripts/dispatch_supervisor/'
expect_hint 'ugrep -rl foo src/volpred/ops'
expect_silent 'grep -n "def main" scripts/ops_snapshot.py'
expect_silent 'rg -n foo src/ | head; uv run python scripts/graphify_integration.py query "foo"'
expect_silent 'ls -la storage/'
expect_silent 'grep -rn pattern docs/'

echo "summary: pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
