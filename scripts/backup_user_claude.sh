#!/bin/bash
# 快照 user-level ~/.claude 的關鍵檔 → ops/claude_user_backup/（進 main repo 版控）。
# 為何：~/.claude（global CLAUDE.md / user skills / auto-memory）不在任何 git repo，
# 換機只 clone 專案會丟掉。本腳本把「本專案相關」的部分快照進 repo，隨 main repo 轉移。
# 用法：bash scripts/backup_user_claude.sh   （換機前在舊主機跑，然後 commit）
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$REPO_ROOT/ops/claude_user_backup"
SRC="$HOME/.claude"
AGENT_SKILLS_ROOT="$HOME/.agents/skills"
# 動態推導當前 repo 對應的 Claude Code session memory 目錄。
# 2026-07-03 修：原 hardcode 舊 Desktop 路徑（-Users-yhlai0911-Desktop-volpred-research），
# repo 2026-07-02 搬到 ~/volpred-research 後 stale → 每日 cron 用錯 source + 有人把
# ops/claude_user_backup/memory 改成 symlink（破壞 git 快照與換機可攜性）。改動態偵測治本。
PROJ_SLUG="$(printf '%s' "$REPO_ROOT" | sed 's:/:-:g')"
PROJ_MEMORY="$SRC/projects/$PROJ_SLUG/memory"

mkdir -p "$DEST"

# 1. global CLAUDE.md（user-level 指引）
[ -f "$SRC/CLAUDE.md" ] && cp "$SRC/CLAUDE.md" "$DEST/CLAUDE.md" && echo "✓ CLAUDE.md"

# 2. user-level skills
if [ -d "$SRC/skills" ]; then
  # The controlled walker follows only links that remain under the two skill
  # roots, catches nested escapes/cycles and builds under .git before swapping
  # the complete symlink-free snapshot into the tracked tree.
  _PYTHON="$REPO_ROOT/.venv/bin/python3"
  [ -x "$_PYTHON" ] || _PYTHON="$(command -v python3)"
  _GIT_DIR="$(git -C "$REPO_ROOT" rev-parse --absolute-git-dir)"
  "$_PYTHON" "$REPO_ROOT/scripts/snapshot_skill_tree.py" \
    --source "$SRC/skills" \
    --destination "$DEST/skills" \
    --approved-root "$SRC/skills" \
    --approved-root "$AGENT_SKILLS_ROOT" \
    --temp-root "$_GIT_DIR"
  echo "✓ skills ($(find "$DEST/skills" -type f | wc -l | tr -d ' ') 檔)"
fi

# 3. user-level agents（如有）
[ -d "$SRC/agents" ] && { rm -rf "$DEST/agents"; cp -R "$SRC/agents" "$DEST/agents"; echo "✓ agents"; }

# 4. auto-memory（本專案；100+ 檔，含 MEMORY.md 索引）
if [ -d "$PROJ_MEMORY" ]; then
  rm -rf "$DEST/memory"; cp -R "$PROJ_MEMORY" "$DEST/memory"
  echo "✓ memory ($(find "$DEST/memory" -type f | wc -l | tr -d ' ') 檔)"
fi

# 5. settings（去敏感：只留 schema 參考，不含 token）
[ -f "$SRC/settings.json" ] && cp "$SRC/settings.json" "$DEST/settings.json.ref" && echo "✓ settings.json.ref（檢查無密鑰再 commit）"

echo ""
echo "快照完成 → $DEST"
echo "下一步：git add ops/claude_user_backup && git commit -m 'backup: user-level ~/.claude snapshot'"
echo "⚠️ commit 前確認 settings.json.ref 無 token/密鑰"
