#!/bin/bash
# 從 ops/claude_user_backup/ 還原 user-level ~/.claude（換機後在新主機跑）。
# 對應 backup_user_claude.sh。不覆蓋既有檔前先備份成 .bak。
# 用法：bash scripts/restore_user_claude.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO_ROOT/ops/claude_user_backup"
DEST="$HOME/.claude"

[ -d "$SRC" ] || { echo "✗ 無備份 $SRC（先在舊主機跑 backup_user_claude.sh 並 commit）"; exit 1; }
mkdir -p "$DEST"

# memory 路徑用「當前主機」的絕對路徑（換 user 名會不同）
PROJ_KEY="$(echo "$REPO_ROOT" | sed 's#/#-#g')"
PROJ_MEMORY="$DEST/projects/$PROJ_KEY/memory"

restore() {  # $1=src $2=dest
  [ -e "$1" ] || return 0
  [ -e "$2" ] && cp -R "$2" "$2.bak.$(date +%s)" 2>/dev/null || true
  rm -rf "$2"; mkdir -p "$(dirname "$2")"; cp -R "$1" "$2"; echo "✓ restored $2"
}

restore "$SRC/CLAUDE.md" "$DEST/CLAUDE.md"
restore "$SRC/skills"    "$DEST/skills"
restore "$SRC/agents"    "$DEST/agents"
restore "$SRC/memory"    "$PROJ_MEMORY"

echo ""
echo "還原完成。settings.json 請手動參考 $SRC/settings.json.ref（密鑰 / 機器專屬值自行填）。"
echo "memory 還原到：$PROJ_MEMORY"
