# VolPred — 自主波動率預測研究平台

由 AI（Claude + Codex）完全自主運營的波動率與交易策略研究平台：研究 → 論文 → 策略 → 文章 → 發佈 → 曝光，全自動且結果可復現。

- **線上站點**：https://volpred.zeabur.app
- **前端**：獨立 repo [`volpred-v2`](https://github.com/yhlai0911/volpred-v2)（本 repo 以 git submodule 概念並存，clone 後另取）
- **語言**：繁體中文為主

---

## 🚀 換機 / 新主機安裝（clone → 填 env → 運作）

> 完整逐步手冊（含前置工具、權限、驗證、疑難排解）見 **[`docs/host-migration.md`](docs/host-migration.md)**。
> 以下是濃縮版三步：

```bash
# 1. 前置工具（macOS）：git / uv / node / gh — 見 docs/host-migration.md §0
#    gh auth login   # repo 是 PRIVATE，clone 前先授權

# 2. Clone + 填 secrets
cd ~/Desktop                                              # ⚠️ 路徑硬編，須放這
git clone https://github.com/yhlai0911/volpred-research.git
cd volpred-research
cp .env.example .env                                     # 依 .env.example 註解拆成
                                                          # .env / .env.local / frontend-v2-fix/.env.local 並填真值

# 3. 一鍵 bootstrap（uv sync / clone 前端 / npm / 還原 ~/.claude / rebuild 索引 / 驗證）
bash scripts/bootstrap_new_host.sh

# 4. 排程（會跳 macOS 權限視窗，須給 Full Disk Access）
bash scripts/install_launchd_jobs.sh
bash scripts/install_host_crontab.sh
```

**驗證成功**：`uv run volpred ops daily-checkup` → overall=ok；`launchctl list | grep volpred` → ~15 job。

**什麼在 repo、什麼要手動**：程式 + 研究資料 + project-level `.claude/`（skills/rules/agents）+ user-level `~/.claude` 快照（`ops/claude_user_backup/`，每日自動保鮮）都在 repo；**只有 secrets（`.env*`）需手動填**（或從舊機 scp）。資產地圖見 host-migration 附錄。

---

## 📁 專案結構

| 路徑 | 內容 |
|---|---|
| `src/volpred/` | 研究引擎 + ops CLI（`uv run volpred ops ...`） |
| `scripts/` | 收集 / 發佈 / 排程 / 維運腳本（含 `cron_*.sh` wrapper） |
| `experiments/` | 實驗三件套（`<id>/{README, <id>.py, results.json}`） |
| `paper/` | 學術論文（LaTeX，self-contained replication package） |
| `storage/` | 唯一本地資料源（feed / knowledge / paper_trading / next_tasks / memory） |
| `config/` | `project_targets.json`（部署目標）+ `runtime_schedules.json`（排程唯一來源） |
| `frontend-v2-fix/` | Next.js 前端（獨立 git repo，bootstrap 自動 clone） |
| `.claude/` | project-level skills / rules / commands / agents（AI 運營用） |
| `ops/claude_user_backup/` | user-level `~/.claude` 每日快照（換機保留） |

---

## 📖 關鍵文件

| 文件 | 用途 |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | AI 運營最高指導原則 + 規則（自主運營經理讀） |
| [`docs/host-migration.md`](docs/host-migration.md) | **換機完整安裝手冊** |
| [`docs/architecture.md`](docs/architecture.md) | 網站架構 / 資料流 / Supabase / Mirror |
| [`docs/quick-commands.md`](docs/quick-commands.md) | 常用命令 |
| [`research_program.md`](research_program.md) | 研究北極星 / 重大發現 / 方法論約束 / backlog |
| [`docs/error_log.md`](docs/error_log.md) | 已知錯誤 / 教訓 / 根因修正 |
| [`docs/strategy-registry.md`](docs/strategy-registry.md) | active 策略與上架 gate |

---

## ⚙️ 運作概覽

- **排程**：macOS LaunchAgent + host crontab（唯一可靠 `0 * * * *`，其餘走 `run_due_jobs.py` piggy-back）；唯一來源 `config/runtime_schedules.json`。
- **部署**：前端走 `frontend-v2-fix/scripts/deploy-zeabur-safe.sh` 到 Zeabur。
- **研究記憶**：Supabase + Mirror API 雙寫 + 本地 `storage/memory/`。
- **自主迴圈**：主 agent 每 tick 跑 PDCA（大體檢 → triage → 派工 → 收斂），詳見 `.claude/skills/pdca-operations`。

> 本平台由 AI 完全自主運營；人類為所有者 / 最終仲裁者。日常執行決策由主 agent 自主判斷（見 `CLAUDE.md`）。
