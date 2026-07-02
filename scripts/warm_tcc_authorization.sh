#!/bin/bash
# warm_tcc_authorization.sh — SessionStart hook (fix (b) of docs/error_log.md 2026-07-02 10:55).
#
# ROOT CAUSE it mitigates:
#   claude CLI auto-updates every 1-2 days (versions/ shows 6/30, 7/1, 7/2 ...).
#   macOS TCC Desktop-folder grants are bound to the binary path+hash, so each
#   NEW claude version starts UNAUTHORIZED for ~/Desktop. Every launchd-context
#   job (cwd = ~/Desktop/volpred-research, a TCC-protected path) then hangs on a
#   TCC prompt it can never answer (no UI in launchd) → the suspended authreqs
#   drag down tccd → cascade timeout/EINTR across ALL schedules until an
#   interactive session (authorized parent context) re-triggers the grant.
#   On 2026-07-02 that accidental recovery took until 10:48 (outage 05:00-10:48).
#
# WHAT THIS DOES (runs at every interactive SessionStart, authorized context):
#   1. Detect whether the claude symlink target changed since last recorded.
#   2. On change: touch the Desktop repo NOW so the new binary's TCC Desktop
#      grant is (re-)triggered at session start instead of hours later, and
#      record the change so auth-preflight can diagnose a TCC-shaped launchd
#      failure accurately (fix (c)).
#   3. Emit an INFO alert so the operator knows an update happened (and that the
#      launchd schedules were likely down between the overnight update and now).
#
# Cannot fix headlessly: TCC re-authorization fundamentally needs a UI/authorized
# context — this compresses the outage window, it does not eliminate the gap.
# The definitive fix (move repo out of ~/Desktop, or pin the CLI) is a boss call.
#
# Contract: always exit 0, fast, side-effect-safe. Never block a session start.

REPO="/Users/yhlai0911/Desktop/volpred-research"
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

# --- version changed (or first run) → warm the Desktop TCC grant early ---
# Best-effort Desktop access under this authorized session context. The active
# claude session already reads Desktop; this makes the grant deterministic+early.
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

echo "[$(date '+%F %T')] claude version changed: ${PREV##*/} -> ${CUR##*/} — warmed TCC Desktop access at session start" >> "$LOG"

# INFO alert (best-effort, timeout-guarded, never blocks). Only fires on a real
# version change, so it is low-frequency (~once per 1-2 days).
# WARM_TCC_NO_ALERT=1 suppresses the email (tests / silent automated contexts).
if [ -n "$PREV" ] && [ "${WARM_TCC_NO_ALERT:-0}" != "1" ]; then
  BODY="# claude CLI 版本變更偵測

**${PREV##*/} → ${CUR##*/}**（symlink 目標已切換）。

## 為什麼重要
macOS TCC 的 Desktop 授權綁定 binary 路徑+雜湊，新版 claude 對 \`~/Desktop\` **預設無授權**。在此互動 session 開始前的空窗期，所有 cwd 在 Desktop 的 launchd 排程（hourly-dispatch / gmail-poll 等）很可能因 TCC 懸置而逾時或 EINTR 全滅。

## 已自動處理
本 SessionStart hook 已在授權 context 下觸碰 Desktop，將新版 binary 的 TCC 授權**在 session 開始當下重新觸發**（把空窗從『數小時』壓到『本 session 開始』）。

## 根治仍待決策
每 1-2 天一次的 CLI 自動更新會週期性重演此空窗。根治選項（搬 repo 出 Desktop / 停用 CLI 自動更新）見 docs/error_log.md 2026-07-02 條目。"
  ( /usr/bin/perl -e 'alarm shift; exec @ARGV' 30 \
      /Users/yhlai0911/.local/bin/uv run volpred ops send-alert \
      --level info \
      --title "claude CLI 更新偵測 ${PREV##*/}→${CUR##*/} — 已暖授權 Desktop TCC $(date '+%H:%M')" \
      --body "$BODY" >/dev/null 2>&1 ) &
fi

exit 0
