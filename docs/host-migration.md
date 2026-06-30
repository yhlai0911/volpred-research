# 換機 / 新主機重建指南（Host Migration & Full Preservation）

2026-06-30 建立（boss 問「換機可行嗎？哪些被 gitignore？skills/agents 如何完全保留？」）。

## TL;DR — 三層資產

| 層 | 內容 | 在哪 | 換機如何取得 |
|---|---|---|---|
| **A. 程式 + 研究資料** | src / scripts / experiments / paper / config / storage(feed,knowledge,paper_trading,next_tasks) / **project-level `.claude/`(skills 64,rules 13,commands,agents)** | main repo `github.com/yhlai0911/volpred-research` | `git clone` ✓ |
| **B. 前端** | `frontend-v2-fix/` | 獨立 repo `github.com/yhlai0911/volpred-v2`（主 repo gitignore 它） | 另 `git clone` 進專案根 ✓ |
| **C. gitignore 掉、需手動** | secrets / 大資料 / runtime / **user-level `~/.claude`** | 不在任何 repo | 見下 §3 ✗ |

**結論**：可以換機，但 C 層必須手動處理 —— 主要是 **secrets**、**user-level `~/.claude`（含 100 個 memory 檔 + global CLAUDE.md + 6 user skills）**、**data/intraday 948MB**、**LaunchAgents/crontab**。

## 1. 取得 A + B（git）

```bash
git clone https://github.com/yhlai0911/volpred-research.git
cd volpred-research
git clone https://github.com/yhlai0911/volpred-v2.git frontend-v2-fix   # 前端獨立 repo
uv sync                                    # Python deps（重建 .venv）
cd frontend-v2-fix && npm install && cd .. # 前端 deps（重建 node_modules）
```

## 2. Secrets（gitignore，**無真值在 git**）

複製 `.env.example` → 填真值 → 拆成三檔（`.env` / `.env.local` / `frontend-v2-fix/.env.local`，欄位分組見 `.env.example` 內註解）。真值從舊主機既有 `.env*` 或密碼管理器取得。**關鍵**：`SUPABASE_*`（後端寫入 + 前端）、`SMTP_*`（email 通知）、`FRED_API_KEY`、`RESEARCH_MIRROR_TOKEN`、`GOOGLE_CLOUD_API_KEY`。

## 3. user-level `~/.claude`（**最易被忽略 — 不在 project repo**）

換機若只 clone repo，會**丟掉**：global `~/.claude/CLAUDE.md`、`~/.claude/skills/`(6 個 user skill)、`~/.claude/projects/<proj>/memory/`(**100 個 auto-memory 檔**)、`~/.claude/settings.json`、plugins。

**保存法（換機前在舊主機跑）**：
```bash
bash scripts/backup_user_claude.sh   # 快照 ~/.claude 關鍵檔 → ops/claude_user_backup/（進 main repo 版控）
```
換機後還原：`bash scripts/restore_user_claude.sh`（從 repo 還原到 ~/.claude）。
> 為何不直接把 ~/.claude 變 git repo：它含跨專案內容 + 不該全進本 repo；快照只取本專案相關的 CLAUDE.md / skills / memory。

## 4. 大資料 data/intraday（948MB，untracked，**非 ignore 只是太大沒 add**）

TWSE order-flow(MI_5MINS) + 0050/SPY 5min 歷史。**可回補不必搬**：
```bash
uv run python scripts/collect_twse_orderflow.py --backfill --start 20120102  # 慢，rate-limited
```
要快就從舊主機 `rsync` 整個 `data/intraday/`。

## 5. Runtime：LaunchAgents + host crontab（repo 外，有重建腳本）

```bash
bash scripts/install_launchd_jobs.sh    # 重裝 15 個 com.volpred.* LaunchAgent
bash scripts/install_host_crontab.sh    # 重裝 host crontab（從 config/runtime_schedules.json）
# cron wrapper 實體：~/.volpred/bin/cron_*.sh（TCC 規定不可放 Desktop）— install 腳本會 cp
```
⚠️ macOS TCC：新機要給 `cron`/`bash` Full Disk Access + 重開機後 FileVault 解鎖（輸密碼）。
⚠️ 路徑硬編：多數 wrapper / plist / config 寫死 `/Users/yhlai0911/...` —— 換**使用者名稱**要全域改（grep `yhlai0911`）。

## 6. 部署目標（換 Zeabur 機器才需）

`config/project_targets.json` 的 `deploy` 三個 ID（project/env/service）。換機不必動，除非也換 Zeabur 專案（見 memory `reference_zeabur_deploy_target`）。

## 7. 重建衍生物（都可從 A 層 regenerate）

```bash
uv run python scripts/build_knowledge_index.py update   # LanceDB 知識索引（storage/knowledge_index/，gitignore）
# .venv / node_modules / .next 由 §1 的 uv sync + npm install + npm build 重建
```

## 驗證換機成功

1. `uv run volpred ops daily-checkup` → overall ok
2. `uv run volpred ops check-alerts` → 不 crash、能寄 email（SMTP 設對）
3. 前端 `cd frontend-v2-fix && npm run build` → 過
4. `launchctl list | grep volpred` → 15 個 job loaded
5. Supabase 連線：`uv run python scripts/supabase_sync.py ...` 能讀寫
