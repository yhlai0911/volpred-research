#!/bin/bash
# warm_tcc_authorization.sh — SessionStart hook.
#
# HISTORY (2026-07-02): the repo used to live in ~/Desktop/volpred-research, a
# macOS TCC-protected path. Because TCC Desktop grants are bound to the claude
# binary's path+hash, every ~1-2-day CLI auto-update started UNAUTHORIZED for
# ~/Desktop, so launchd-context jobs (cwd on Desktop) hung on a TCC prompt no
# one could answer → cascade EINTR/timeout across all schedules (outage
# 05:00-10:48 on 2026-07-02). This hook warmed the Desktop grant early at each
# interactive SessionStart to compress that window, and emitted an INFO alert.
#
# STATUS (2026-07-02 → present): the DEFINITIVE fix shipped — the repo was moved
# OUT of Desktop to ~/volpred-research (all 20 launchd plists now have
# WorkingDirectory=~/volpred-research; the ~/Desktop/volpred-research symlink is
# gone). TCC no longer applies to the repo, so the Desktop-outage this hook
# guarded against CANNOT recur. The old "已暖授權 Desktop TCC / 排程可能全滅"
# alert was therefore stale + self-contradicting (it stat'd ~/volpred-research,
# not Desktop) and only spread false alarm on every CLI update — retired
# 2026-07-15 (boss email email-12126, "為什麼跟 desktop 還有關係").
#
# WHAT THIS DOES NOW (runs at every interactive SessionStart, authorized context):
#   1. Detect whether the claude symlink target changed since last recorded.
#   2. On change: record it to claude_version_state.json so auth-preflight can
#      still diagnose a TCC-shaped launchd failure accurately (fix (c)), and
#      append a line to warm_tcc.log. NO email alert (repo is off Desktop → no
#      outage to warn about; a version bump is not actionable).
#
# Contract: always exit 0, fast, side-effect-safe. Never block a session start.

REPO="/Users/yhlai0911/volpred-research"
STATE="$REPO/storage/ops/claude_version_state.json"
LINK="$HOME/.local/bin/claude"
LOG="$HOME/.volpred/logs/warm_tcc.log"

mkdir -p "$(dirname "$LOG")" 2>/dev/null

CUR=$(readlink "$LINK" 2>/dev/null)
# No symlink / can't resolve → nothing to do (don't churn state).
[ -z "$CUR" ] && exit 0

PREV=""
if [ -f "$STATE" ]; then
  PREV=$(/usr/bin/perl -ne 'print $1 if /"claude_symlink_target"\s*:\s*"([^"]*)"/' "$STATE" 2>/dev/null)
fi

NOW=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

if [ "$CUR" = "$PREV" ]; then
  # Unchanged — keep a heartbeat but do not re-warm / re-alert.
  exit 0
fi

# --- version changed (or first run) → record it (repo is off Desktop; no TCC
# warming needed anymore). Lightweight stat kept only as a cheap repo liveness
# touch; it hits ~/volpred-research, NOT a TCC-protected path.
( cd "$REPO" 2>/dev/null && /usr/bin/stat "$REPO/CLAUDE.md" >/dev/null 2>&1 )

# Record new state (perl writes valid JSON; avoids jq dependency in hook path).
/usr/bin/perl -e '
  my ($cur,$prev,$now,$state)=@ARGV;
  open(my $fh, ">", $state) or exit 0;
  $cur=~s/"/\\"/g; $prev=~s/"/\\"/g;
  print $fh "{\n";
  print $fh "  \"claude_symlink_target\": \"$cur\",\n";
  print $fh "  \"previous_target\": \"$prev\",\n";
  print $fh "  \"changed_at\": \"$now\",\n";
  print $fh "  \"warmed_by\": \"warm_tcc_authorization.sh (SessionStart)\"\n";
  print $fh "}\n";
  close($fh);
' "$CUR" "$PREV" "$NOW" "$STATE"

echo "[$(date '+%F %T')] claude version changed: ${PREV##*/} -> ${CUR##*/} — recorded (repo off Desktop; no TCC action, no alert)" >> "$LOG"

# NO email alert. The repo left ~/Desktop on 2026-07-02, so a CLI version bump no
# longer risks the Desktop-TCC launchd outage this hook once warned about. The
# version-change record above (state file + log) is all downstream diagnostics
# (auth-preflight fix (c)) needs. Retired the misleading INFO email 2026-07-15.

exit 0
