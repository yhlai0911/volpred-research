#!/bin/bash
# 換機一鍵 bootstrap。流程：git clone 主 repo → 複製 .env.example 填上真值（API keys 等）
# → 跑本腳本 → 平台即可運作。idempotent，可重跑。
#
# 用法：
#   git clone https://github.com/yhlai0911/volpred-research.git && cd volpred-research
#   cp .env.example .env   # 然後依 .env.example 內註解拆出 .env / .env.local / frontend .env.local 並填真值
#   bash scripts/bootstrap_new_host.sh
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
ok=0; warn=0
say(){ echo "[$1] $2"; }

echo "=== VolPred 換機 bootstrap ($(date '+%F %T')) ==="

# 0. 必要 env 檔檢查（boss 手動填值的部分）
for f in .env .env.local frontend-v2-fix/.env.local; do
  if [ -f "$f" ]; then say OK "env 存在: $f"; ok=$((ok+1));
  else say MISSING "缺 $f —— 依 .env.example 填真值（API key/Supabase/SMTP 等），否則部分功能無法運作"; warn=$((warn+1)); fi
done

# 0b. 使用者名稱硬編檢查（換 user 名必踩）
if [ "$(whoami)" != "yhlai0911" ]; then
  say WARN "目前使用者 $(whoami) ≠ yhlai0911 —— wrapper/plist/config 多處硬編路徑，須全域改：grep -rl yhlai0911 scripts config ~/.volpred ~/Library/LaunchAgents"
  warn=$((warn+1))
fi

# 1. Python deps
say RUN "uv sync ..."; uv sync >/dev/null 2>&1 && say OK "Python deps 就緒" || { say FAIL "uv sync 失敗（先裝 uv: https://docs.astral.sh/uv/）"; warn=$((warn+1)); }

# 2. 前端（獨立 repo volpred-v2）
if [ ! -d frontend-v2-fix/.git ]; then
  say RUN "clone 前端 volpred-v2 ..."; git clone https://github.com/yhlai0911/volpred-v2.git frontend-v2-fix >/dev/null 2>&1 && say OK "前端 clone 完成" || { say FAIL "前端 clone 失敗（檢查 GitHub 權限）"; warn=$((warn+1)); }
fi
[ -d frontend-v2-fix ] && (cd frontend-v2-fix && npm install >/dev/null 2>&1) && say OK "前端 npm deps 就緒" || say WARN "前端 npm install 略過/失敗"

# 3. user-level ~/.claude 還原（global CLAUDE.md + user skills + memory）
if [ -d ops/claude_user_backup ]; then
  bash scripts/restore_user_claude.sh >/dev/null 2>&1 && say OK "~/.claude 還原（CLAUDE.md/skills/memory）" || say WARN "~/.claude 還原失敗（手動跑 restore_user_claude.sh）"
fi

# 4. runtime wrapper + 排程（LaunchAgent + host crontab）
mkdir -p "$HOME/.volpred/bin"
cp scripts/cron_*.sh "$HOME/.volpred/bin/" 2>/dev/null && chmod +x "$HOME/.volpred/bin/"*.sh 2>/dev/null && say OK "cron wrapper → ~/.volpred/bin"
say NOTE "排程需手動跑（會碰 macOS TCC 權限提示，須給 Full Disk Access）："
say NOTE "  bash scripts/install_launchd_jobs.sh   # 15 個 com.volpred.* LaunchAgent"
say NOTE "  bash scripts/install_host_crontab.sh   # host crontab"

# 5. 知識索引（LanceDB，gitignore，rebuild）
uv run python scripts/build_knowledge_index.py update >/dev/null 2>&1 && say OK "知識索引 rebuilt" || say WARN "知識索引 rebuild 略過（缺 GOOGLE_CLOUD_API_KEY？）"

# 6. 驗證
echo ""; echo "=== 驗證 ==="
uv run python scripts/daily_checkup.py 2>&1 | tail -3 || true

echo ""
echo "=== bootstrap 完成：OK=$ok WARN=$warn ==="
echo "下一步（手動）：1) 確認三個 .env* 填妥  2) 跑 install_launchd_jobs.sh + install_host_crontab.sh（TCC 授權）"
echo "  3) 換 user 名須改硬編路徑  4) data/intraday(948MB) 要 rsync 或 --backfill（非必要、實驗才用）"
echo "完整說明見 docs/host-migration.md"
