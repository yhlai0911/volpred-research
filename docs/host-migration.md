# 換機安裝手冊（新主機從零重建 VolPred）

> **狀態說明（2026-07-23）**：本手冊仍是目前可用的人工 bootstrap，但只能視為
> `contained` 的換機方式，尚未達成功能等價、RPO=0、warm standby、租約防雙主與
> zero-paid provider continuity。正式目標與接管 gate 見
> `docs/adr/0002-zero-paid-provider-continuity-and-host-failover.md` 與
> `docs/platform_optimization_program_2026_07.md`。在新版 guided migration 通過演練前，
> 不得移除本手冊或現行 bootstrap。
>
> 目標：新 Mac 上 **clone → 填環境變數 → 跑 bootstrap → 平台運作**。
> 照本手冊由上到下做即可。每步附確切指令 + 預期結果。
> 2026-06-30 建立（boss 要求）。預設新機是 **macOS、同使用者名稱 `yhlai0911`**；不同 user 名見 §9。

---

## 0. 前置工具（先裝好這些）

```bash
# 0-1 Xcode Command Line Tools（含 git）
xcode-select --install            # 跳視窗就按安裝；已裝會說 already installed

# 0-2 Homebrew（套件管理）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 0-3 uv（Python 套件/環境管理 — 本專案用 uv 不用 pip/venv）
curl -LsSf https://astral.sh/uv/install.sh | sh
# 裝完重開 terminal 或 source ~/.zprofile，確認：uv --version

# 0-4 Node.js（前端 build）
brew install node                 # 確認：node --version（需 ≥ 18）

# 0-5 GitHub CLI（私有 repo 授權用）
brew install gh
```

**預期**：`git --version` / `uv --version` / `node --version` / `gh --version` 都有輸出。

---

## 1. GitHub 授權（repo 是 PRIVATE，clone 必須先授權）

```bash
gh auth login
# 選 GitHub.com → HTTPS → 用瀏覽器登入授權（或貼 Personal Access Token）
gh auth status                    # 確認 Logged in to github.com
```

**預期**：`gh auth status` 顯示已登入 `yhlai0911`。
（替代法：產 SSH key 加到 GitHub，或用 PAT；只要 git clone 私有 repo 能過即可。）

---

## 2. Clone 主 repo

```bash
cd ~                              # ⚠️ 路徑硬編在此：必須是 ~/volpred-research（家目錄根，**禁止放 ~/Desktop/**）
git clone https://github.com/yhlai0911/volpred-research.git
cd volpred-research
```

**預期**：`ls` 看到 `src/ scripts/ config/ storage/ paper/ experiments/ docs/ .claude/ .env.example`。
**⚠️ 路徑**：大量 wrapper / plist / config 硬編 `/Users/yhlai0911/volpred-research`。新機若放別處或別的 user 名 → 見 §9。
**⚠️ TCC 教訓（2026-07-02）**：repo 曾放 `~/Desktop/`（macOS TCC 保護區），launchd/cron job 無 UI 可回應 TCC 授權 → 排程全面癱瘓 5.8 小時後以 3-strike 重構遷至 `~/volpred-research`。**任何新機都不得把 repo 裝回 Desktop/Documents/Downloads 等 TCC 保護目錄。**

---

## 3. 填環境變數（唯一須手動填值的部分）

repo 不含真正密鑰（`.gitignore` 排除 `.env*`），只含範本 `.env.example`。需建**三個檔**：

```bash
# 3-1 用範本當底
cp .env.example .env
```

然後依 `.env.example` 內的「檔案 1/2/3」分組，**建出三個檔並填真值**：

| 檔 | 內容 | 真值哪來 |
|---|---|---|
| `.env` | SMTP（email 通知）+ GOOGLE_CLOUD_API_KEY + OPENAI_API_KEY + META_GRAPH_API + VOLPRED_REMOTE_URL | 舊主機既有 `.env` / 各服務後台 / 密碼管理器 |
| `.env.local` | **SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY**（後端寫入）+ FRED_API_KEY + RESEARCH_MIRROR_TOKEN + VOLPRED_MIRROR_URL + OPS_ADMIN_TOKEN | Supabase 後台 → Settings → API；FRED 官網申請 |
| `frontend-v2-fix/.env.local` / `.env.production` | NEXT_PUBLIC_SUPABASE_URL + NEXT_PUBLIC_SUPABASE_ANON_KEY + SUPABASE_SERVICE_ROLE_KEY + NEXT_PUBLIC_SITE_URL + OPS_ADMIN_EMAILS + **OPS_ADMIN_TOKEN** | 同上 Supabase；anon key 也在 Settings → API；OPS_ADMIN_TOKEN 必須與根目錄 `.env.local` 相同 |

> `frontend-v2-fix/` 此時還不存在（§4 bootstrap 才 clone）。可先把該檔內容記著，bootstrap clone 完前端後再建，或 bootstrap 後補。
> **取得最快法**：若舊主機還在，直接把舊機的 `.env`、`.env.local`、`frontend-v2-fix/.env.local` 三檔 `scp`/`rsync` 過來，最不易漏。

**最低可運作集**：缺 SUPABASE_* → 平台無法讀寫資料（必填）。缺 SMTP_* → 無 email 通知。缺 FRED → 總經資料更新失敗。缺 GOOGLE_CLOUD_API_KEY → 知識索引/Gemini 略過。

---

## 4. 跑一鍵 bootstrap

```bash
bash scripts/bootstrap_new_host.sh
```

**它自動做**：檢查三個 `.env*`、`uv sync`（建 .venv + Python deps）、clone 前端 `volpred-v2` →
`frontend-v2-fix/` + `npm install`、還原 `~/.claude`（global CLAUDE.md + user skills + memory，
從 `ops/claude_user_backup/`）、cp cron wrapper 到 `~/.volpred/bin/`、rebuild 知識索引、跑 daily-checkup。

**預期尾段**：`=== bootstrap 完成：OK=N WARN=M ===` + daily-checkup 輸出。
WARN 多半是「缺某個 .env 值」或「launchd 需手動裝」（正常，往下做）。

> 跑完才補 `frontend-v2-fix/.env.local`（前端此時已 clone 出來）：
> `cp .env.example frontend-v2-fix/.env.local` 後留下「檔案 3」那段並填值（或從舊機 scp）。

---

## 5. 安裝排程（LaunchAgent + host crontab）

平台靠這些定時跑（資料收集、發文、巡檢、自動 push）。**會跳 macOS 權限視窗**：

```bash
bash scripts/install_launchd_jobs.sh     # 裝 15 個 com.volpred.* LaunchAgent
bash scripts/install_host_crontab.sh     # 裝 host crontab（從 config/runtime_schedules.json）
```

**預期**：`launchctl list | grep volpred` 看到 ~15 個 job；`crontab -l | grep volpred` 有 volpred 區段。

---

## 6. macOS 權限（一次性，但必做否則 cron 不跑）

1. **Full Disk Access**：System Settings → Privacy & Security → Full Disk Access →
   加入 `/bin/bash`、`/usr/sbin/cron`（按 + → Cmd+Shift+G 輸入路徑）。
   （否則 cron 無法讀 Desktop 下檔案 → 排程靜默失敗，這是踩過的坑。）
2. **FileVault**：若開啟，重開機後須輸入一次登入密碼解鎖，排程才會在背景跑。
3. 裝完 launchd 後可 `launchctl kickstart -k gui/$(id -u)/com.volpred.daily-update` 手動觸發測一個 job。

---

## 7. 驗證換機成功（逐項打勾）

```bash
# 7-1 系統健康
uv run volpred ops daily-checkup            # → overall=ok
# 7-2 alert 系統 + email（SMTP 設對才會寄）
uv run volpred ops check-alerts             # 不 crash
# 7-3 Supabase 連線（資料讀寫）
uv run python -c "from supabase_sync import SUPABASE_URL; print('SB:', SUPABASE_URL[:30])"
# 7-4 前端能 build
cd frontend-v2-fix && npm run build && cd ..   # → Compiled successfully
# 7-5 排程已載入
launchctl list | grep volpred | wc -l       # → ~15
```

**全過 = 換機成功，平台開始自主運作。**

---

## 8.（選配）歷史盤中資料 data/intraday（948MB，不在 git）

TWSE order-flow + 5min 歷史，**只有特定實驗用，平台運作不需要**。要的話：
```bash
# 法 A：從舊主機 rsync（快）
rsync -av oldhost:~/volpred-research/data/intraday/ data/intraday/
# 法 B：重新回補（慢，rate-limited，可斷點續傳）
uv run python scripts/collect_twse_orderflow.py --backfill --start 20120102
```

---

## 9.（只在「不同 user 名 / 不同路徑」時）修硬編

預設假設 `~/volpred-research` + user `yhlai0911`（2026-07-02 起；Desktop 為 TCC 保護區已棄用）。若不同：
```bash
grep -rl yhlai0911 scripts ~/.volpred ~/Library/LaunchAgents config | head -40
# 全域替換（先備份）：把 /Users/yhlai0911 換成 /Users/<新user>，路徑同理
```
影響面：cron wrapper（`~/.volpred/bin/cron_*.sh`）、LaunchAgent plist（`ProgramArguments`/`WorkingDirectory`/log 路徑）、`config/project_targets.json`、`config/runtime_schedules.json` 的 `wrapper_script`。改完重跑 §5。

---

## 附錄：什麼在 repo、什麼要手動（換機資產地圖）

| 資產 | 在哪 | 換機 |
|---|---|---|
| 程式 src/scripts/experiments/paper/config | main repo | clone ✓ |
| 研究資料 storage(feed/knowledge/paper_trading/next_tasks) | main repo | clone ✓ |
| **project-level `.claude/`**（skills 64/rules 13/commands/agents） | main repo | clone ✓ |
| **user-level `~/.claude`**（CLAUDE.md/skills/memory 100 檔） | main repo `ops/claude_user_backup/`（每日 05:35 自動快照） | bootstrap 自動還原 ✓ |
| 前端 | 獨立 repo `volpred-v2` | bootstrap 自動 clone ✓ |
| **secrets**（.env / .env.local / frontend .env.local） | 不在 repo | **§3 手動填**（或 scp 舊機） |
| cron wrapper / LaunchAgent / crontab | scripts/ 有 canonical | bootstrap cp + §5 install ✓ |
| data/intraday 948MB | 不在 git | §8 選配 |
| .venv / node_modules / 知識索引 | 不在 git | bootstrap 自動重建 ✓ |
