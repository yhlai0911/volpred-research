#!/bin/bash
# Regression gate for scripts/git_hooks/pre-push.
#
# The 2026-07-10 incident this pins down: the hook audited the WORKING TREE, so a
# commit carrying a new silent fallback pushed cleanly as long as the fix had been
# written to disk but not committed. Case 2 below is that exact shape — commit
# dirty, tree clean — and it must be REJECTED.
#
# Runs entirely in a throwaway repo pair (work + bare remote). It never touches
# the real checkout, which matters: several Claude sessions share it.
#
# Usage: bash scripts/tests/test_pre_push_gate.sh
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Seam: point at an older hook to confirm this test actually catches the bug.
# A test that passes against the broken implementation is not a test.
#   git show <old-sha>:scripts/git_hooks/pre-push > /tmp/old && \
#     PREPUSH_HOOK=/tmp/old bash scripts/tests/test_pre_push_gate.sh   # must FAIL
HOOK="${PREPUSH_HOOK:-$REPO_ROOT/scripts/git_hooks/pre-push}"
PASS=0
FAIL=0

ok()   { PASS=$((PASS + 1)); echo "  ok   — $1"; }
bad()  { FAIL=$((FAIL + 1)); echo "  FAIL — $1"; }

# HERMETIC ISOLATION — mandatory for any git-driving test (2026-07-10 incident).
# If this process inherits GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE pointing at
# the real repo — from a hostile-env probe, a parent hook that `export`ed GIT_DIR,
# or a flaky sibling test — then every `git commit`/`git push origin main` below
# runs against the REAL repo instead of the sandbox, and a 6-file skeleton gets
# force-pushed to the real origin/main. That actually happened (docs/error_log.md,
# author "prepush test"). Unset them, and give git a sandbox HOME so no global
# config or credential helper can reach a network remote.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_COMMON_DIR
export GIT_CONFIG_NOSYSTEM=1

TMPROOT="$(mktemp -d "${TMPDIR:-/tmp}/prepush-gate-test.XXXXXX")" || exit 1
trap 'rm -rf "$TMPROOT"' EXIT

export HOME="$TMPROOT/home"   # sandbox global config away from the real one
mkdir -p "$HOME"

REMOTE="$TMPROOT/remote.git"
WORK="$TMPROOT/work"

git init --quiet --bare "$REMOTE"
git init --quiet "$WORK"
cd "$WORK" || exit 1
git config user.email "test@volpred.local"
git config user.name "pre-push-gate-test"
git config commit.gpgsign false
git remote add origin "$REMOTE"

# A miniature repo shaped like the real one: the audits anchor to
# Path(__file__).parents[1], and each scan root must exist as a tracked path.
mkdir -p scripts src/volpred tests .claude/hooks storage/qa
cp "$REPO_ROOT/scripts/audit_silent_fallbacks.py" scripts/
cp "$REPO_ROOT/scripts/audit_source_encoding.py" scripts/
printf '' > src/volpred/__init__.py
printf 'def test_noop():\n    assert True\n' > tests/test_noop.py
printf 'HOOK_NOOP = True\n' > .claude/hooks/noop.py

install -m 0755 "$HOOK" .git/hooks/pre-push

# Freeze the current findings as the baseline, so only NEW ones can block.
python3 scripts/audit_silent_fallbacks.py --write-baseline storage/qa/silent_fallback_baseline.json >/dev/null 2>&1

git add -A && git commit --quiet -m "baseline"

echo "case 1 — clean commit pushes"
if git push --quiet origin main >/dev/null 2>&1 || git push --quiet origin master >/dev/null 2>&1; then
  ok "clean commit accepted"
else
  bad "clean commit was rejected (gate is over-blocking)"
fi
BRANCH="$(git rev-parse --abbrev-ref HEAD)"

echo "case 2 — commit carries a violation, working tree is CLEAN (the 2026-07-10 bug)"
cat > scripts/offender.py <<'PY'
def parse(raw):
    try:
        return int(raw)
    except Exception:
        return None
PY
git add scripts/offender.py && git commit --quiet -m "introduce a silent fallback"

# Now repair the working tree WITHOUT committing. This is what made the old hook
# pass: on-disk state is clean, the commit being pushed is not.
cat > scripts/offender.py <<'PY'
def parse(raw):
    try:
        return int(raw)
    except Exception as exc:
        print(f"parse failed: {exc}")
        return None
PY

# Sanity: the working tree really is clean by the audit's own reckoning.
if python3 scripts/audit_silent_fallbacks.py --strict \
     --baseline storage/qa/silent_fallback_baseline.json 2>&1 | grep -q 'new=0'; then
  ok "fixture is honest: working tree audits clean while the commit does not"
else
  bad "fixture broken: working tree should audit clean (new=0)"
fi

PUSH_OUT="$(git push origin "$BRANCH" 2>&1)"
PUSH_RC=$?
if [ "$PUSH_RC" -ne 0 ]; then
  ok "push rejected despite clean working tree"
  if printf '%s' "$PUSH_OUT" | grep -q 'BLOCKED'; then
    ok "rejection is reported as a block"
  else
    bad "rejection message lacks BLOCKED: $PUSH_OUT"
  fi
  if printf '%s' "$PUSH_OUT" | grep -q 'scripts/offender.py'; then
    ok "rejection names the offending file"
  else
    bad "rejection does not name scripts/offender.py"
  fi
  if printf '%s' "$PUSH_OUT" | grep -q 'audits the COMMIT'; then
    ok "rejection explains that fixing the tree alone is not enough"
  else
    bad "rejection does not explain the commit-vs-tree distinction"
  fi
else
  bad "PUSH SUCCEEDED — the gate is auditing the working tree again (2026-07-10 regression)"
fi

echo "case 3 — commit the fix, push is accepted"
git add scripts/offender.py && git commit --quiet -m "add observable trace"
if git push --quiet origin "$BRANCH" >/dev/null 2>&1; then
  ok "push accepted once the fix is committed"
else
  bad "push still rejected after committing the fix"
fi

echo "case 4 — branch deletion is not audited"
git push --quiet origin "$BRANCH:refs/heads/scratch" >/dev/null 2>&1
if git push --quiet origin :refs/heads/scratch >/dev/null 2>&1; then
  ok "deletion (all-zero sha) skipped cleanly"
else
  bad "deletion was blocked — the zero-sha guard is broken"
fi

echo "case 5 — a degraded gate says so out loud"
# "gate did not run" must never be indistinguishable from "gate passed". Starve
# it of an interpreter and confirm it warns on stderr rather than exiting quietly.
DEG_OUT="$(PATH="/nonexistent" /bin/bash .git/hooks/pre-push origin "$REMOTE" \
            < /dev/null 2>&1)"
if printf '%s' "$DEG_OUT" | grep -q 'WARN gate degraded'; then
  ok "fail-open path announces itself"
else
  bad "fail-open path was silent: ${DEG_OUT:-<no output>}"
fi

echo ""
echo "pre-push gate: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
