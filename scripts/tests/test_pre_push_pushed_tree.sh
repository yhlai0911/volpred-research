#!/bin/bash
# Regression: scripts/git_hooks/pre-push must audit the COMMITS BEING PUSHED,
# not the working tree.
#
# 2026-07-10 incident (docs/error_log.md): commit ee407db3a introduced 3 new
# silent fallbacks. The gate blocked the first push. The sites were then fixed in
# the WORKING TREE but could not be committed (a concurrent session held an
# in-progress merge in the shared main checkout, so `git commit` died on
# "unmerged files"). The retried `git push` saw the clean working tree, passed,
# and ee407db3a landed on origin/main still carrying all three violations —
# CI run 29101935680 went red on main. Repaired after the fact by e00b83482.
#
# Core assertion (case 3): a commit carrying a new silent fallback is REJECTED
# even though the working tree is clean. Case 2 pins the counterfactual — the old
# working-tree audit returns new=0 on that same state, i.e. it would have let the
# bad commit through — so case 3 is a real discriminator, not a tautology.
#
# Exit-code discipline (.claude/rules/hooks-exit-code.md): never trust a bare
# pipeline $?; capture each command's own rc / output and count explicit failures.
set -uo pipefail

REPO="$(git -C "$(dirname "$0")/../.." rev-parse --show-toplevel)"
# PREPUSH_HOOK lets you point the suite at another hook revision — used to verify
# the suite really discriminates (the pre-e00b83482 hook must fail case 3).
HOOK="${PREPUSH_HOOK:-$REPO/scripts/git_hooks/pre-push}"
PASS=0
FAIL=0

ok()  { PASS=$((PASS + 1)); echo "PASS: $1"; }
bad() { FAIL=$((FAIL + 1)); echo "FAIL: $1"; }

# Substring test without a pipe. `printf "$big" | grep -q pat` races under
# `set -o pipefail`: grep -q exits at the first match, printf takes EPIPE, and the
# pipeline reports failure even though the match succeeded. That made this suite
# flake ~1-in-10 under parallel load, always on the assertion whose needle sits on
# the first line of the haystack. Never reintroduce that shape here.
contains() {  # $1 = needle, $2 = haystack
  case "$2" in *"$1"*) return 0 ;; *) return 1 ;; esac
}

[ -f "$HOOK" ] || { echo "FATAL: hook not found: $HOOK"; exit 1; }

SB="$(mktemp -d "${TMPDIR:-/tmp}/prepush-test.XXXXXX")" || exit 1
trap 'rm -rf "$SB"' EXIT INT TERM

# Hermetic git environment. Two ways the ambient env silently broke this suite:
#   - GIT_DIR / GIT_WORK_TREE inherited from a caller retarget every `git -C`
#     below at the real repo instead of the sandbox.
#   - git localises its messages. Under pytest the parent env made git speak
#     Traditional Chinese ("錯誤: 無法提交，有未合併的檔案。"), so a grep for
#     "unmerged" missed and the suite failed only when run through pytest.
# Never assert on git's prose; pin the locale anyway so failures read the same
# everywhere. HOME points at the sandbox so a global gitconfig (e.g. a stray
# core.hooksPath) cannot disable the very hook under test.
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
REMOTE="$SB/remote.git"

# ---------------------------------------------------------------------------
# Sandbox repo mirroring the shape the three audits expect:
#   scripts/ + src/ + tests/          (audit_source_encoding.py DEFAULT_ROOTS)
#   scripts/ + src/volpred/           (audit_silent_fallbacks.py DEFAULT_TARGETS)
#   storage/qa/silent_fallback_baseline.json
# ---------------------------------------------------------------------------
git init -q --bare "$REMOTE"
mkdir -p "$WORK"
git -C "$WORK" init -q
git -C "$WORK" symbolic-ref HEAD refs/heads/main
git -C "$WORK" config user.email "test@example.com"
git -C "$WORK" config user.name "prepush test"
git -C "$WORK" config commit.gpgsign false

mkdir -p "$WORK/scripts" "$WORK/src/volpred" "$WORK/tests" "$WORK/storage/qa"
cp "$REPO/scripts/audit_silent_fallbacks.py" "$WORK/scripts/"
cp "$REPO/scripts/audit_source_encoding.py" "$WORK/scripts/"
cp "$REPO/scripts/audit_test_imports.py" "$WORK/scripts/"
: > "$WORK/src/volpred/__init__.py"
printf 'def test_placeholder():\n    assert True\n' > "$WORK/tests/test_placeholder.py"

# A module with a *diagnosed* fallback → audit reports no finding.
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

# Resolve the interpreter exactly as the hook does (sandbox has no .venv → python3),
# so the baseline we freeze and the baseline the hook diffs are byte-comparable.
PY="$WORK/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3 2>/dev/null)"
[ -n "${PY:-}" ] && [ -x "$PY" ] || { echo "FATAL: no python3"; exit 1; }

BASELINE="$WORK/storage/qa/silent_fallback_baseline.json"
"$PY" "$WORK/scripts/audit_silent_fallbacks.py" --write-baseline "$BASELINE" >/dev/null 2>&1 \
  || { echo "FATAL: could not seed sandbox baseline"; exit 1; }

git -C "$WORK" add -A
git -C "$WORK" commit -qm "base: clean tree"
git -C "$WORK" remote add origin "$REMOTE"

# Seed one trusted parent before installing the hook. Gate 3 deliberately fails
# closed for a root commit because there is no immutable parent auditor.
git -C "$WORK" push --no-verify -q origin main \
  || { echo "FATAL: could not seed trusted parent"; exit 1; }
install -m 0755 "$HOOK" "$WORK/.git/hooks/pre-push"
printf 'CLEAN_PROBE = True\n' > "$WORK/scripts/clean_probe.py"
git -C "$WORK" add scripts/clean_probe.py
git -C "$WORK" commit -qm "clean: exercise installed gate"
BASE_SHA="$(git -C "$WORK" rev-parse HEAD)"

audit_working_tree_new() {   # legacy gate's decision function
  "$PY" "$WORK/scripts/audit_silent_fallbacks.py" --strict --baseline "$BASELINE" 2>&1 \
    | grep -oE 'new=[0-9]+' | head -1 | cut -d= -f2
}

# ---------------------------------------------------------------------------
# Case 1 — positive control: a clean commit pushes fine (gate is not a brick).
# ---------------------------------------------------------------------------
OUT="$(git -C "$WORK" push origin main 2>&1)"; RC=$?
if [ "$RC" -eq 0 ]; then ok "clean commit pushes"; else bad "clean commit blocked (rc=$RC): $OUT"; fi

# ---------------------------------------------------------------------------
# Commit a NEW silent fallback, then repair it ONLY in the working tree.
# This is the 2026-07-10 state: bad commit, clean disk, fix uncommittable.
# ---------------------------------------------------------------------------
cat > "$WORK/scripts/bad_mod.py" <<'PY'
"""Introduces a new silent fallback: except → return None, no diagnostic."""
import json


def load(raw):
    try:
        return json.loads(raw)
    except Exception:
        return None
PY
git -C "$WORK" add scripts/bad_mod.py
git -C "$WORK" commit -qm "bad: new silent fallback"
BAD_SHA="$(git -C "$WORK" rev-parse HEAD)"

# Repair on disk; deliberately DO NOT commit.
cat > "$WORK/scripts/bad_mod.py" <<'PY'
"""Working-tree copy is clean; the fix is deliberately left uncommitted."""
import json


def load(raw):
    try:
        return json.loads(raw)
    except Exception:
        return None  # silent-ok: regression fixture
PY

# ---------------------------------------------------------------------------
# Case 2 — counterfactual: the OLD gate audited the working tree, which is now
# clean, so it would have reported new=0 and allowed the bad commit through.
# ---------------------------------------------------------------------------
WT_NEW="$(audit_working_tree_new)"
if [ "$WT_NEW" = "0" ]; then
  ok "working tree audits clean (new=0) — the old gate would have allowed the bad commit"
else
  bad "fixture broken: working tree should audit clean, got new=$WT_NEW"
fi

# ---------------------------------------------------------------------------
# Case 3 — THE REGRESSION: the new gate audits the pushed commit and blocks.
# ---------------------------------------------------------------------------
BEFORE_STATUS="$(git -C "$WORK" status --porcelain)"
BEFORE_HEAD="$(git -C "$WORK" rev-parse HEAD)"
BEFORE_STAGED="$(git -C "$WORK" diff --cached --name-status)"
BEFORE_FILE="$(cat "$WORK/scripts/bad_mod.py")"
BEFORE_WT_COUNT="$(git -C "$WORK" worktree list | wc -l | tr -d ' ')"

OUT="$(git -C "$WORK" push origin main 2>&1)"; RC=$?

if [ "$RC" -ne 0 ]; then ok "bad commit is rejected even though the working tree is clean"
else bad "bad commit was ACCEPTED (rc=0) — hook still audits the working tree"; fi

if contains 'BLOCKED' "$OUT"; then ok "block message printed"
else bad "no BLOCKED message: $OUT"; fi

if contains 'new silent fallback' "$OUT"; then ok "block names the violation"
else bad "block message does not name the violation: $OUT"; fi

if contains 'scripts/bad_mod.py' "$OUT"; then ok "block names the offending file"
else bad "block message does not name scripts/bad_mod.py: $OUT"; fi

REMOTE_SHA="$(git -C "$REMOTE" rev-parse refs/heads/main 2>/dev/null)"
if [ "$REMOTE_SHA" = "$BASE_SHA" ]; then ok "remote did not advance to the bad commit"
else bad "remote advanced to $REMOTE_SHA (bad=$BAD_SHA, base=$BASE_SHA)"; fi

# ---------------------------------------------------------------------------
# Case 4 — shared-checkout safety: the hook mutates nothing.
# ---------------------------------------------------------------------------
[ "$(git -C "$WORK" status --porcelain)" = "$BEFORE_STATUS" ] \
  && ok "working tree status unchanged by the hook" || bad "hook changed working tree status"
[ "$(git -C "$WORK" rev-parse HEAD)" = "$BEFORE_HEAD" ] \
  && ok "HEAD unchanged by the hook" || bad "hook moved HEAD"
[ "$(git -C "$WORK" diff --cached --name-status)" = "$BEFORE_STAGED" ] \
  && ok "index unchanged by the hook" || bad "hook mutated the index"
[ "$(cat "$WORK/scripts/bad_mod.py")" = "$BEFORE_FILE" ] \
  && ok "working-tree file contents preserved" || bad "hook rewrote a working-tree file"
[ -z "$(git -C "$WORK" stash list)" ] \
  && ok "hook created no stash" || bad "hook left a stash entry"
[ "$(git -C "$WORK" worktree list | wc -l | tr -d ' ')" = "$BEFORE_WT_COUNT" ] \
  && ok "hook registered no git worktree" || bad "hook left worktree metadata behind"

# ---------------------------------------------------------------------------
# Case 5 — the exact blocker from the incident: an in-progress merge in the
# shared checkout makes `git commit` impossible. The gate must still audit the
# commit (block), and must leave the merge state intact.
# ---------------------------------------------------------------------------
# Build the side branch with plumbing: `git checkout -b` would refuse to switch
# while scripts/bad_mod.py carries the uncommitted repair, and we must keep that
# repair on disk — it is the whole point of the fixture.
TIDX="$SB/tmp-index"
SIDE_BLOB="$(printf 'side\n' | git -C "$WORK" hash-object -w --stdin)"
env GIT_INDEX_FILE="$TIDX" git -C "$WORK" read-tree "$BAD_SHA"
env GIT_INDEX_FILE="$TIDX" git -C "$WORK" update-index --add --cacheinfo "100644,$SIDE_BLOB,conflict.txt"
SIDE_TREE="$(env GIT_INDEX_FILE="$TIDX" git -C "$WORK" write-tree)"
SIDE_SHA="$(git -C "$WORK" commit-tree "$SIDE_TREE" -p "$BAD_SHA" -m "side: conflict.txt")"
git -C "$WORK" branch -f side "$SIDE_SHA"
rm -f "$TIDX"

# main adds the same path with different content → add/add conflict on merge.
printf 'main\n' > "$WORK/conflict.txt"
git -C "$WORK" add conflict.txt
git -C "$WORK" commit -qm "main: conflict.txt"
git -C "$WORK" merge side >/dev/null 2>&1   # leaves an unmerged index

if [ -f "$WORK/.git/MERGE_HEAD" ]; then
  ok "sandbox reproduces an in-progress merge"

  # Assert on machine state, never on git's (localisable) prose: the commit must
  # not happen and the merge must still be pending.
  HEAD_PRE_COMMIT="$(git -C "$WORK" rev-parse HEAD)"
  CO="$(git -C "$WORK" commit -qm "attempt" 2>&1)"; CRC=$?
  HEAD_POST_COMMIT="$(git -C "$WORK" rev-parse HEAD)"
  if [ "$CRC" -ne 0 ] && [ "$HEAD_POST_COMMIT" = "$HEAD_PRE_COMMIT" ] && [ -f "$WORK/.git/MERGE_HEAD" ]; then
    ok "git commit refuses while the merge is unresolved (exact incident precondition)"
  else
    bad "commit unexpectedly succeeded during merge (rc=$CRC): $CO"
  fi

  OUT="$(git -C "$WORK" push origin main 2>&1)"; RC=$?
  if [ "$RC" -ne 0 ] && contains 'BLOCKED' "$OUT"; then
    ok "gate still blocks the bad commit while a merge is in progress"
  else
    bad "gate passed during in-progress merge (rc=$RC): $OUT"
  fi

  MSTATUS="$(git -C "$WORK" status --porcelain)"
  if [ -f "$WORK/.git/MERGE_HEAD" ] && { contains 'AA ' "$MSTATUS" || contains 'UU ' "$MSTATUS"; }; then
    ok "in-progress merge survived the hook"
  else
    bad "hook destroyed the in-progress merge state"
  fi
  git -C "$WORK" merge --abort >/dev/null 2>&1
else
  # Never let the dependent assertions pass by accident when setup failed.
  bad "could not set up in-progress merge (dependent merge-safety cases not exercised)"
  bad "SKIPPED: git commit refuses with 'unmerged files'"
  bad "SKIPPED: gate blocks while a merge is in progress"
  bad "SKIPPED: in-progress merge survives the hook"
fi

# ---------------------------------------------------------------------------
# Case 6 — committing the fix unblocks the push (gate is satisfiable, and it
# audits the ref TIP, not every ancestor: the bad commit stays in history).
# ---------------------------------------------------------------------------
cat > "$WORK/scripts/bad_mod.py" <<'PY'
"""Fix is now committed."""
import json


def load(raw):
    try:
        return json.loads(raw)
    except Exception:
        return None  # silent-ok: regression fixture
PY
git -C "$WORK" add scripts/bad_mod.py
git -C "$WORK" commit -qm "fix: mark the fallback silent-ok"
OUT="$(git -C "$WORK" push origin main 2>&1)"; RC=$?
if [ "$RC" -eq 0 ]; then ok "committing the fix unblocks the push"
else bad "push still blocked after committing the fix (rc=$RC): $OUT"; fi

if git -C "$WORK" merge-base --is-ancestor "$BAD_SHA" "$(git -C "$REMOTE" rev-parse refs/heads/main)"; then
  ok "tip-only semantics: bad ancestor is on the remote, tip tree is clean (matches CI)"
else
  bad "expected the bad commit to remain an ancestor of the pushed tip"
fi

# ---------------------------------------------------------------------------
# Case 7 — tag pushes are out of scope. CI triggers on pull_request + push to a
# branch, so a tag can never turn CI red; gating tags would block pushing an
# archival tag whose tree predates storage/qa/silent_fallback_baseline.json.
# ---------------------------------------------------------------------------
git -C "$WORK" tag bad-archive "$BAD_SHA"
OUT="$(git -C "$WORK" push origin refs/tags/bad-archive 2>&1)"; RC=$?
if [ "$RC" -eq 0 ]; then ok "tag pointing at the bad commit pushes (tags are not gated)"
else bad "tag push was blocked (rc=$RC): $OUT"; fi

# ---------------------------------------------------------------------------
# Case 8 — replacing the candidate auditor with an always-green stub cannot
# judge the same pushed candidate. The immutable parent auditor must still see
# the missing implementation referenced by the new test.
# ---------------------------------------------------------------------------
REMOTE_BEFORE_WEAKEN="$(git -C "$REMOTE" rev-parse refs/heads/main)"
cat > "$WORK/scripts/audit_test_imports.py" <<'PY'
#!/usr/bin/env python3
print("[audit-test-imports] 1 test files checked, 1 dependencies resolved, 0 bad")
PY
printf 'from scripts import pushed_missing\n' > "$WORK/tests/test_weakened_gate.py"
git -C "$WORK" add scripts/audit_test_imports.py tests/test_weakened_gate.py
git -C "$WORK" commit -qm "bad: weaken test dependency gate"
OUT="$(git -C "$WORK" push origin main 2>&1)"; RC=$?
if [ "$RC" -ne 0 ] && contains 'pushed_missing' "$OUT"; then
  ok "pushed candidate cannot weaken its immutable parent auditor"
else
  bad "candidate auditor weakening was not blocked (rc=$RC): $OUT"
fi
REMOTE_AFTER_WEAKEN="$(git -C "$REMOTE" rev-parse refs/heads/main)"
if [ "$REMOTE_AFTER_WEAKEN" = "$REMOTE_BEFORE_WEAKEN" ]; then
  ok "remote did not advance to the weakened-auditor commit"
else
  bad "remote advanced after auditor weakening ($REMOTE_BEFORE_WEAKEN -> $REMOTE_AFTER_WEAKEN)"
fi

# ---------------------------------------------------------------------------
# Case 9 — the pushed candidate cannot delete the auditor that judges test/
# implementation closure. This check is candidate-tree-local and therefore
# still fails closed even though case 8 left a fake auditor in its parent.
# ---------------------------------------------------------------------------
REMOTE_BEFORE_DELETE="$REMOTE_AFTER_WEAKEN"
git -C "$WORK" rm -q scripts/audit_test_imports.py
git -C "$WORK" commit -qm "bad: remove test dependency gate"
OUT="$(git -C "$WORK" push origin main 2>&1)"; RC=$?
if [ "$RC" -ne 0 ] && contains 'removes scripts/audit_test_imports.py' "$OUT"; then
  ok "pushed commit cannot delete its own test-dependency auditor"
else
  bad "auditor deletion was not blocked (rc=$RC): $OUT"
fi
REMOTE_AFTER_DELETE="$(git -C "$REMOTE" rev-parse refs/heads/main)"
if [ "$REMOTE_AFTER_DELETE" = "$REMOTE_BEFORE_DELETE" ]; then
  ok "remote did not advance to the auditor-deletion commit"
else
  bad "remote advanced after auditor deletion ($REMOTE_BEFORE_DELETE -> $REMOTE_AFTER_DELETE)"
fi

# ---------------------------------------------------------------------------
echo ""
echo "pre-push pushed-tree gate: PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
