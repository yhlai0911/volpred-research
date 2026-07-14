#!/bin/bash
# Regression: scripts/git_hooks/pre-commit must audit ONLY THE .py FILES THIS
# COMMIT STAGES — never the whole working tree.
#
# 2026-07-13 incident (docs/error_log.md): the 00:07 dispatch fire finished its
# task (K1700 followup) and went to commit its own artifacts. A codex_loop was
# concurrently mid-edit on src/volpred/ops/event_jobs.py in the same shared main
# checkout, and its half-written file carried one new silent fallback. The
# pre-commit gate swept the working tree, found the OTHER author's finding, and
# refused the fire's commit. Author A blocked by author B's unstaged file.
#
# This is the same ownership bug PHASE Z already fixed for `git add -A`: the
# question a commit-time gate must ask is "did MY files pass?", never "is the
# whole tree clean?". Nothing is weakened by the scoping — pre-push audits the
# pushed COMMIT TREE and CI re-runs both audits on the pushed head, so B's file
# is still caught the moment B commits it (case 2) or at push
# (test_pre_push_pushed_tree.sh).
#
# Case 3 pins the counterfactual: the tree-wide audit returns new>=1 on case 1's
# state, i.e. the old gate really did block that commit. Without it, case 1 would
# be a tautology.
#
# Exit-code discipline (.claude/rules/hooks-exit-code.md): never trust a bare
# pipeline $?; capture each command's own rc / output and count explicit failures.
set -uo pipefail

REPO="$(git -C "$(dirname "$0")/../.." rev-parse --show-toplevel)"
# PRECOMMIT_HOOK lets you point the suite at another hook revision — used to
# verify the suite discriminates (the pre-scoping hook must fail case 1).
HOOK="${PRECOMMIT_HOOK:-$REPO/scripts/git_hooks/pre-commit}"
PASS=0
FAIL=0

ok()  { PASS=$((PASS + 1)); echo "PASS: $1"; }
bad() { FAIL=$((FAIL + 1)); echo "FAIL: $1"; }

# Substring test without a pipe: `printf "$big" | grep -q pat` races under
# `set -o pipefail` (grep exits at first match, printf takes EPIPE).
contains() {  # $1 = needle, $2 = haystack
  case "$2" in *"$1"*) return 0 ;; *) return 1 ;; esac
}

[ -f "$HOOK" ] || { echo "FATAL: hook not found: $HOOK"; exit 1; }

SB="$(mktemp -d "${TMPDIR:-/tmp}/precommit-test.XXXXXX")" || exit 1
trap 'rm -rf "$SB"' EXIT INT TERM

# Hermetic git env (see test_pre_push_pushed_tree.sh for the two ways the ambient
# env silently broke that suite: inherited GIT_DIR retargets `git -C` at the real
# repo; localised git prose breaks greps). HOME points at the sandbox so a global
# core.hooksPath cannot disable the hook under test.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY \
      GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_COMMON_DIR GIT_NAMESPACE \
      GIT_CONFIG GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM
export GIT_CONFIG_NOSYSTEM=1
export GIT_TERMINAL_PROMPT=0
export GIT_EDITOR=true
export LC_ALL=C
export LANG=C
export HOME="$SB"

WORK="$SB/work"

# Sandbox repo mirroring what the two audits expect:
#   scripts/ + src/ + tests/   (audit_source_encoding.py DEFAULT_ROOTS)
#   scripts/ + src/volpred/    (audit_silent_fallbacks.py DEFAULT_TARGETS)
#   storage/qa/silent_fallback_baseline.json
mkdir -p "$WORK"
git -C "$WORK" init -q
git -C "$WORK" symbolic-ref HEAD refs/heads/main
git -C "$WORK" config user.email "test@example.com"
git -C "$WORK" config user.name "precommit test"
git -C "$WORK" config commit.gpgsign false

mkdir -p "$WORK/scripts" "$WORK/src/volpred" "$WORK/tests" "$WORK/storage/qa"
cp "$REPO/scripts/audit_silent_fallbacks.py" "$WORK/scripts/"
cp "$REPO/scripts/audit_source_encoding.py" "$WORK/scripts/"
cp "$REPO/scripts/audit_test_imports.py" "$WORK/scripts/"
: > "$WORK/src/volpred/__init__.py"
printf 'def test_placeholder():\n    assert True\n' > "$WORK/tests/test_placeholder.py"

# Fixture with a *diagnosed* fallback → audit reports no finding.
cat > "$WORK/scripts/sandbox_mod.py" <<'PY'
"""Sandbox fixture: fallback with an observable diagnostic."""
import json


def load(raw):
    try:
        return json.loads(raw)
    except Exception as exc:
        print(f"load failed: {exc}")
        return None
PY

PY="$(command -v python3 2>/dev/null)"
[ -n "${PY:-}" ] && [ -x "$PY" ] || { echo "FATAL: no python3"; exit 1; }
# The hook resolves `uv run python` when uv is on PATH. Shadow uv with a stub that
# delegates to the system python3, so the sandbox never resolves the real repo's
# .venv (which would import a different volpred than the fixtures here). The stub
# must SUCCEED — an exit-127 stub makes every audit look like a failure and the
# gate blocks everything, which silently turns this suite green for the wrong
# reason.
export PATH="$SB/bin:$PATH"
mkdir -p "$SB/bin"
cat > "$SB/bin/uv" <<'SH'
#!/bin/bash
# emulate `uv run python <args>`
if [ "${1:-}" = "run" ] && [ "${2:-}" = "python" ]; then
  shift 2
fi
exec python3 "$@"
SH
chmod +x "$SB/bin/uv"

BASELINE="$WORK/storage/qa/silent_fallback_baseline.json"
"$PY" "$WORK/scripts/audit_silent_fallbacks.py" --write-baseline "$BASELINE" >/dev/null 2>&1 \
  || { echo "FATAL: could not seed sandbox baseline"; exit 1; }

install -m 0755 "$HOOK" "$WORK/.git/hooks/pre-commit"

git -C "$WORK" add -A
git -C "$WORK" commit --no-verify -qm "base: clean tree" >/dev/null 2>&1 \
  || { echo "FATAL: base commit rejected by hook"; exit 1; }

# A new *undiagnosed* fallback — the exact shape the audit flags.
write_violation() {  # $1 = path
  cat > "$1" <<'PY'
"""Fixture: bare fallback, no diagnostic — audit must flag this."""
import json


def load(raw):
    try:
        return json.loads(raw)
    except Exception:
        return None
PY
}

# ---------------------------------------------------------------------------
# Case 1 (the incident): another author's UNSTAGED file carries a violation.
#   My staged .py is clean → my commit must be ALLOWED.
# ---------------------------------------------------------------------------
write_violation "$WORK/src/volpred/other_author_wip.py"   # dirty, never staged
printf 'def mine():\n    return 1\n' > "$WORK/scripts/my_clean_change.py"
git -C "$WORK" add scripts/my_clean_change.py

OUT1="$(cd "$WORK" && git commit -m "mine: clean staged py" 2>&1)"
RC1=$?
if [ "$RC1" -eq 0 ]; then
  ok "case 1: clean staged .py commits despite another author's dirty violation"
else
  bad "case 1: commit blocked by an UNSTAGED file this commit does not touch"
  echo "$OUT1" | sed 's/^/      /' | head -8
fi

# ---------------------------------------------------------------------------
# Case 3 (counterfactual, run before the tree is cleaned): the tree-wide audit
#   sees new>=1 on case 1's state — so case 1 is a real discriminator, not a
#   tautology. The old gate would (and did) block that commit.
# ---------------------------------------------------------------------------
TREE_OUT="$(cd "$WORK" && "$PY" scripts/audit_silent_fallbacks.py --strict --baseline "$BASELINE" 2>&1)"
TREE_RC=$?
if [ "$TREE_RC" -ne 0 ] && contains "other_author_wip.py" "$TREE_OUT"; then
  ok "case 3: tree-wide audit DOES flag the other author's file (case 1 discriminates)"
else
  bad "case 3: tree-wide audit did not flag other_author_wip.py — case 1 proves nothing"
  echo "$TREE_OUT" | sed 's/^/      /' | head -5
fi

rm -f "$WORK/src/volpred/other_author_wip.py"

# ---------------------------------------------------------------------------
# Case 2: the violation is in MY staged file → commit must be BLOCKED.
#   (Scoping must not become a hole.)
# ---------------------------------------------------------------------------
write_violation "$WORK/src/volpred/my_violation.py"
git -C "$WORK" add src/volpred/my_violation.py

OUT2="$(cd "$WORK" && git commit -m "mine: staged violation" 2>&1)"
RC2=$?
if [ "$RC2" -ne 0 ] && contains "silent fallback" "$OUT2"; then
  ok "case 2: staged .py carrying a new silent fallback is still BLOCKED"
else
  bad "case 2: staged violation slipped through (rc=$RC2) — scoping opened a hole"
  echo "$OUT2" | sed 's/^/      /' | head -8
fi

git -C "$WORK" reset -q
rm -f "$WORK/src/volpred/my_violation.py"

# ---------------------------------------------------------------------------
# Case 4: encoding gate still fires on a staged mojibake file. Guards the
#   audit_source_encoding.py change that made --roots accept FILES as well as
#   dirs: if it had kept rejecting file paths it would exit 2 ("root not found")
#   and the gate would pass on a corrupt file — a gate scanning nothing.
# ---------------------------------------------------------------------------
printf '# comment: \xe5\x28\xa5 broken\ndef f():\n    return 1\n' > "$WORK/scripts/mojibake.py"
git -C "$WORK" add scripts/mojibake.py

OUT4="$(cd "$WORK" && git commit -m "mine: mojibake" 2>&1)"
RC4=$?
if [ "$RC4" -ne 0 ] && contains "non-UTF-8" "$OUT4"; then
  ok "case 4: staged non-UTF-8 .py is still BLOCKED (scoped --roots accepts files)"
else
  bad "case 4: mojibake file slipped through (rc=$RC4) — encoding gate scanned nothing"
  echo "$OUT4" | sed 's/^/      /' | head -8
fi

git -C "$WORK" reset -q
rm -f "$WORK/scripts/mojibake.py"

# ---------------------------------------------------------------------------
# Case 5: a test is staged while the implementation it imports exists only in
# the working tree.  The candidate INDEX is incomplete and must be BLOCKED.
# ---------------------------------------------------------------------------
printf 'X = 1\n' > "$WORK/scripts/worktree_only.py"  # deliberately untracked
printf 'from scripts import worktree_only\n' > "$WORK/tests/test_partial_dependency.py"
git -C "$WORK" add tests/test_partial_dependency.py

OUT5="$(cd "$WORK" && git commit -m "mine: partial test dependency" 2>&1)"
RC5=$?
if [ "$RC5" -ne 0 ] && contains "dependency drift" "$OUT5" && contains "worktree_only" "$OUT5"; then
  ok "case 5: working-tree-only implementation cannot satisfy candidate-index test"
else
  bad "case 5: partial test commit was not blocked (rc=$RC5)"
  echo "$OUT5" | sed 's/^/      /' | head -10
fi

git -C "$WORK" reset -q
rm -f "$WORK/tests/test_partial_dependency.py" "$WORK/scripts/worktree_only.py"

# ---------------------------------------------------------------------------
# Case 6: the candidate cannot delete the gate that judges it.
# ---------------------------------------------------------------------------
git -C "$WORK" rm -q scripts/audit_test_imports.py
OUT6="$(cd "$WORK" && git commit -m "mine: remove dependency gate" 2>&1)"
RC6=$?
if [ "$RC6" -ne 0 ] && contains "removes its own test-import gate" "$OUT6"; then
  ok "case 6: deleting the candidate-index auditor fails closed"
else
  bad "case 6: candidate removed its own auditor (rc=$RC6)"
  echo "$OUT6" | sed 's/^/      /' | head -10
fi

git -C "$WORK" reset -q HEAD -- scripts/audit_test_imports.py
git -C "$WORK" checkout -q -- scripts/audit_test_imports.py

# ---------------------------------------------------------------------------
# Case 7: replacing the candidate auditor with an always-green stub cannot
# judge the same candidate.  The immutable HEAD auditor must still catch the
# missing implementation.
# ---------------------------------------------------------------------------
cat > "$WORK/scripts/audit_test_imports.py" <<'PY'
#!/usr/bin/env python3
print("[audit-test-imports] 1 test files checked, 1 dependencies resolved, 0 bad")
PY
printf 'from scripts import still_missing\n' > "$WORK/tests/test_weakened_gate.py"
git -C "$WORK" add scripts/audit_test_imports.py tests/test_weakened_gate.py

OUT7="$(cd "$WORK" && git commit -m "mine: weaken dependency gate" 2>&1)"
RC7=$?
if [ "$RC7" -ne 0 ] && contains "still_missing" "$OUT7"; then
  ok "case 7: candidate cannot weaken the trusted HEAD auditor"
else
  bad "case 7: weakened candidate auditor bypassed dependency closure (rc=$RC7)"
  echo "$OUT7" | sed 's/^/      /' | head -10
fi

git -C "$WORK" reset -q HEAD -- scripts/audit_test_imports.py tests/test_weakened_gate.py
git -C "$WORK" checkout -q -- scripts/audit_test_imports.py
rm -f "$WORK/tests/test_weakened_gate.py"

echo
echo "pre-commit staged-scope: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
