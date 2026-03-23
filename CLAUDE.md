# 自主波動率預測研究系統
原則上使用繁體中文互動

## 專案簡介
Claude Code 驅動的自主研究系統，用於尋找給定資產的最佳波動率預測模型，並建立一般投資人可用的交易策略。

## 網站架構（v4 Supabase + Admin CMS + Mirror API）
- **前端（開發中）**：`frontend-v2-fix/`（Next.js 15 + React 19 + Supabase，正在優化中）
- **前端（線上版）**：`frontend-v2/`（目前部署版本）
- **Mirror API**：`mirror-api.zeabur.app`（研究記憶檔案鏡像，減少 Supabase egress）
- **資料庫**：Supabase（PostgreSQL + Auth + REST API + RPC）
- **Zeabur Dashboard**：https://zeabur.com/projects/69b5b264800a475a1f82b073
- **線上網址**：https://volpred.zeabur.app / https://volpred-v3.zeabur.app
- **舊版**：https://volpred-old.zeabur.app（過渡期保留）

### 前端 v4 架構（frontend-v2-fix/）
- **SSR + CSR 混合**：首頁用 Server Component 初始載入 → `FeedBrowser` 用 `useSWRInfinite` 無限滾動
- **Admin CMS**（10 個核心面板）：analytics / content / ops / strategies / questions / users / papers / paper-trading / health / schedules
- **Legacy 面板**：`program` 已降級為隱藏/過渡功能，不列入主要平台操作入口
- **用戶專區** `/me`：書籤、提問歷史、活動摘要
- **API 路由 45+**：含 `/api/admin/*`（12 端點）、`/api/me/*`（3 端點）、`/api/strategy-overview`、`/api/portfolio-overview`
- **認證**：`admin-auth.ts` 支持 secret-based + session-based 雙模式，角色：admin/user/guest
- **Feed RPC**：`feed_page()` + `feed_tag_counts()` 伺服器端分頁+標籤計數，取代 client-side filter
- **互動追蹤**：`ArticleEngagement` 組件（瀏覽、按讚、收藏、分享）
- **策略視覺化**：`PaperTradingChartIsland` + sparkline 走勢圖（Recharts）
- **論文管理**：`/admin/papers` + `/api/admin/papers` + `/api/admin/papers/upload`，論文頁 metadata 與 PDF 交付都可走平台層

### 資料流
- `storage/` → 本地唯一源頭（JSON）
- `scripts/supabase_sync.py` → Supabase 同步工具（由 daily_update.py 呼叫，不需獨立 cron）
- `scripts/daily_update.py` → 每日 06:03 計算策略權重 + 同步 Supabase + 重算績效指標 + Supabase heartbeat
- `scripts/recalc_metrics.py` → 從 paper_trading.json 重算 Sharpe/MDD 等（daily_update 自動呼叫）
- `src/volpred/ops/` + `uv run volpred ops ...` → agent-first 操作層（真人與本機 agent 共用）
- 前端從 Supabase 讀取策略 metadata，不需靜態檔案同步
- **Mirror 資料流**：`MemorySystem._sync_to_remote()` → 前端 `/api/sync/{file}` → 雙寫 Supabase + Mirror API
  - 平時：增量 append（POST，只送新 entry）
  - 初始/復原：整檔覆蓋（PUT，`reconcile_remote()`）
  - Mirror 存：thinking_journal / knowledge / experiments / research_log（4 個大型記憶檔案）
  - Supabase 存：articles / questions / papers / paper_trades / strategy_signals（產品面向資料）
  - Rollout 文件：`docs/research-mirror-rollout.md`

### 策略管理（DB 驅動，無需重新部署）
- 策略 metadata 唯一來源：`daily_update.py` 頂部的 `STRATEGY_REGISTRY`（display_name, is_active, order）
- Registry 驅動三件事：Feed 文章（只列 active）、Supabase 同步、Paper trading
- **新增策略**：(1) 加入 STRATEGY_REGISTRY (2) 加計算邏輯到 strat_list (3) `add_strategy.py` 寫 DB
- **下架策略**：改 STRATEGY_REGISTRY 的 `is_active=False`（面板隱藏、文章不列、paper trading 繼續記錄）
- **績效指標**：每日由 `daily_update.py` 自動重算 → `strategy_metrics.json`
- 詳細流程見 `.claude/skills/autonomous-research/references/add-strategy-guide.md`

### 發佈流程
1. 研究系統優先寫入 `storage/`，再依需求選擇：
   - `立即發布`
   - `放入文章池草稿（draft）`
   - `排程發布（scheduled）`
2. 平台層釋出優先走：
   - `uv run volpred ops publish-milestone`
   - `uv run volpred ops release-pool-by-settings`
   - `/admin/content`
3. 文章真正進入 `published` 後，平台層會準備管理通知：
   - 單篇新文章通知
   - 每日發文摘要
   - 若未配置 SMTP，會先寫入 `storage/notifications/`，不算真正寄出
4. Feed 發文用 `feed-publisher` skill；若涉及文章池、排程、節奏釋出、下架、釋出規則、管理通知，轉交 `admin-ops`
5. 改前端代碼時：Zeabur CLI 部署 `frontend-v2-fix/`（見下方 Zeabur CLI 指令）
6. 新增策略用 `add_strategy.py`（只寫 DB，不需部署）
7. 測試貼文清理優先走 `uv run volpred ops cleanup-post <pub_id>`，不要手改 feed/DB

### Agent-first Ops Layer
- **本地唯一核心 agent**：`Claude Code + session cron`
- 後台最終形態是 **agent-first control plane**，不是只有真人點擊的 CMS
- **核心原則**：同一套操作能力，同時暴露給本機 agent（CLI / job）與真人 UI
- **CLI 首選入口**：`uv run volpred ops ...`
- 已統一的操作：
  - `ops publish-milestone`
  - `ops release-pool-by-settings`
  - `ops send-article-notification`
  - `ops send-daily-digest`
  - `ops unpublish`
  - `ops cleanup-post`
  - `ops sync-all`
  - `ops daily-update`
  - `ops recalc-metrics`
  - `ops strategy-upsert`
  - `ops strategy-set-active`
  - `ops question-ranking-summary`
  - `ops question-rerank`
  - `ops question-answer`
  - `ops health`
- **Job Queue**（`src/volpred/ops/jobs.py`）：
  - Supabase-backed 任務佇列（`ops_jobs` 表）
  - lifecycle: `queued` → `running` → `succeeded|failed`
  - 支持 dedupe key、dry-run、priority、worker ID
  - CLI: `ops jobs` / `ops job-show` / `ops enqueue` / `ops worker`
- **`ops worker` 定位**：工具/備援層，不代表另一個獨立核心 agent 身分
- **Web Admin**（`frontend-v2-fix/src/app/admin/ops/`）：OpsConsole 瀏覽器端 job 管理
- **Claude 可直接讀的 summary surfaces**：
  - `/api/admin/analytics/summary`
  - `/api/admin/questions/summary`
  - `/api/admin/content`
- 真人 UI 是監看與手動介入層；本機 agent 也走同一套核心流程

### 注意事項
- Feed 發文要用 `feed-publisher` skill（thinking ≠ content）
- **Zeabur reverse proxy 陷阱**：詳見 `docs/zeabur-oauth-gotcha.md`
- Paper trading 用 `portfolio_return`（加權後組合報酬），不是單一資產 return
- 時間處理：`published_at` 存 UTC，前端用 `timeZone: 'Asia/Taipei'` 顯示。詳見 `.claude/skills/autonomous-research/references/data-timing.md`
- 跨市場策略注意 VIX lag（台股用前一天 VIX）
- **5-min 數據回補**：收集腳本自動偵測 gap 並回補（上限 59 天 = yfinance 免費版限制）。macOS 休眠時 cron 不執行，醒來後自動回補
- **Paper trading 多日回補**：daily_update.py 自動回填所有 `portfolio_return=None` 的歷史條目（利用相鄰條目價差）
- **frontend-v2-fix 開發中**：前端代碼修改需同時考慮 `frontend-v2/`（線上）和 `frontend-v2-fix/`（開發），待穩定後統一切換

## 論文
- **第一篇**：`paper/leverage-direction/main.tex`（60 頁，Leverage Direction Matters，目標 JBF）
- **第二篇**：`paper/taiwan-vt/main.tex`（34 頁，Taiwan VT + TZ Information Transmission，目標 PBFJ）
- **第三篇**：`paper/vt-trend-following/main.tex`（24 頁，Is VT Just Trend Following?，目標待定）
- 編譯：`cd paper/<name> && /Library/TeX/texbin/xelatex -interaction=nonstopmode main.tex`（跑兩次解引用）
- 作者：Yi-Hao Lai (Da-Yeh University) + VolPred Research System
- 論文頁 `/paper` 讀 Supabase `papers` table（metadata）；**PDF 放前端 `frontend-v2-fix/public/paper/`**（由 Zeabur CDN serve，不走 Supabase Storage）

### 新策略上線標準程序（發現有效策略後執行）
1. **Cross-OOS 驗證**：至少 5 個 OOS 期間（J9 教訓：單期 OOS 不可靠）
2. **3 年回測**：計算 Sharpe/MDD/Calmar/Sortino/Net Sharpe (after TX)
3. **加入 STRATEGY_REGISTRY**：`daily_update.py` 頂部加一行 (display_name, is_active, order)
4. **加入計算邏輯**：`daily_update.py` 的 strat_list 區塊
5. **寫入 DB**：`add_strategy.py --id xxx --name xxx ...`
6. **更新 CLAUDE.md 策略表 + research_program.md**
7. **發佈 Feed 文章**：用 `feed-publisher` skill
- 詳細流程見 `.claude/skills/autonomous-research/references/add-strategy-guide.md`

### 論文更新標準程序（每次編譯新版都要做）
1. **編譯 PDF**：`cd paper/<name> && xelatex main.tex && xelatex main.tex`
2. **複製 PDF 到前端**：`cp paper/<name>/main.pdf frontend-v2-fix/public/paper/<slug>.pdf`
   - leverage-direction → `leverage-direction-matters.pdf`
   - taiwan-vt → `taiwan-vt-tz-arbitrage.pdf`
   - vt-trend-following → `vt-trend-following.pdf`
3. **更新論文 metadata**（Supabase `papers` table 的 `pdf_url` 指向 `/paper/<slug>.pdf`）
4. **部署前端**（因為 PDF 在 `public/` 裡，需要 redeploy 才會更新）
5. **審查流程**：Codex 審查 → Gemini 審查 → 修正 → 重新編譯 → 重複 1-4

## 快速指令
```bash
# 研究
uv run volpred summary                              # 研究摘要
uv run volpred analyze-data --asset SPY              # 資料特性
uv run volpred run-experiment --asset SPY --model gjr_arch --window 2000
uv run python scripts/build_knowledge_index.py build # 知識索引重建

# 每日運營
uv run python scripts/daily_update.py                # 每日更新（策略計算 + 績效重算 + Supabase 同步）
uv run python scripts/recalc_metrics.py              # 手動重算績效指標
uv run python scripts/supabase_sync.py full          # 手動 incremental sync
uv run python scripts/supabase_sync.py force-full    # 強制全量同步（慎用，IO 大）
uv run volpred ops health                            # 本地營運健康檢查
uv run volpred ops sync-all                          # 統一入口：手動 Supabase sync
uv run volpred ops daily-update                      # 統一入口：每日更新
uv run volpred ops recalc-metrics                    # 統一入口：重算績效指標
uv run volpred ops paper-list                        # 查看論文與 Storage 狀態
uv run volpred ops paper-upsert --paper-id xxx --title "..." --authors "..."
uv run volpred ops paper-upload-pdf --paper-id xxx --file paper/<name>/main.pdf
uv run volpred ops paper-migrate-storage --paper-id xxx

# 策略管理（只寫 DB，不需部署）
uv run python scripts/add_strategy.py --id xxx --name "名稱" --howto "說明" --description "完整說明" --assets '{"SPY":50}' --order N
uv run volpred ops strategy-upsert --strategy-key xxx --strategy-name "名稱" --weights-json '{"SPY":0.5}'
uv run volpred ops strategy-set-active xxx --inactive

# Jobs 與 Worker（agent-first ops）
uv run volpred ops jobs --status queued              # 查看待處理任務
uv run volpred ops job-show <job_id>                 # 查看任務詳情及日誌
uv run volpred ops enqueue --action daily_update     # 手動入隊任務
uv run volpred ops worker --poll-interval 10         # 啟動本地 worker

# Zeabur CLI（部署 + 域名管理）
# Project ID: 69b5b264800a475a1f82b073
# Environment ID: 69b5b2646853f6f4f5f6a16d
# Services: volpred-web (69b5b279e0a0c18cef9d780d), volpred-v2 (69b8ed895a53b5901a3c8d25), volpred-v3 (69be521a1066986b9a1692be)
npx zeabur@latest auth status                    # 確認登入狀態
npx zeabur@latest service list --project-id 69b5b264800a475a1f82b073 --json  # 列出服務
npx zeabur@latest domain list --id <service_id> -i=false --json              # 列出域名
npx zeabur@latest domain create --id <service_id> --domain <subdomain> --env-id 69b5b2646853f6f4f5f6a16d -g -y -i=false  # 綁定 *.zeabur.app 域名（-g 時只寫子域名如 'volpred'，不要寫完整 'volpred.zeabur.app'）
npx zeabur@latest domain delete --id <domain_id> -i=false -y                 # 刪除域名
npx zeabur@latest service redeploy --id <service_id> -i=false -y             # 重新部署
# 部署前端代碼到 volpred-v3:
cd frontend-v2-fix && npx zeabur@latest deploy --project-id 69b5b264800a475a1f82b073 --service-id 69be521a1066986b9a1692be --json
# 注意：所有 CLI 命令加 -i=false 避免互動式 prompt

# 發佈
uv run python scripts/record_and_publish.py --title "標題" --thinking "推理" --knowledge "知識" --phase "Phase_X"
uv run volpred ops publish-milestone --title "標題" --description "Markdown 內容" --phase "Phase_X"
uv run volpred ops release-pool-by-settings --storage-dir storage
uv run volpred ops send-article-notification mile_xxxxxxxx
uv run volpred ops send-daily-digest --target-date 2026-03-21
uv run volpred ops unpublish mile_xxxxxxxx
uv run volpred ops cleanup-post mile_xxxxxxxx --hard-delete

# 會員問題排行
uv run volpred ops question-ranking-summary --limit 20
uv run volpred ops question-rerank --evaluations-json '[...]'
```

## 思維模式：永遠修流程，不修資料

**任何問題都不能用手動修正解決。** 必須追溯到底層流程，使修正可以自動化、流程化、規格化。

**絕對禁止的手動操作**：
- 直接改 JSON 檔案的 status/content/metadata → 用 ops CLI/API
- 用 session cron workaround 繞過 DB/系統限制 → 改 DB schema + 程式碼
- 手動 PATCH Supabase 修正資料 → 修正 sync 流程讓它自動正確
- 繞過文章池直接 `status=published` → 用 `release-pool-by-settings` 釋出

| 層次 | 錯誤做法 | 正確做法 |
|------|---------|---------|
| 資料錯誤 | 手動改 JSON/DB | 修正產生資料的程式碼，讓下次自動正確 |
| 發佈失敗 | 手動 sync 到 Supabase | 修正 publisher.py 讓它自動 sync + retry |
| 格式問題 | 手動修文章內容 | 修正 serialization 邏輯（如 `\\n` 雙重轉義）|
| 缺欄位 | 手動 PATCH DB | 修正 sync 函式讓它帶正確欄位 |
| 排版壞掉 | 手動清理 metadata | 修正 publisher.py 自動 sanitize |
| DB schema 不支援 | 用 session cron 繞過 DB 限制 | 改 DB schema（migration） + 改程式碼適配 |
| 流程缺失 | 手動逐篇操作 | 寫入 skill/config 讓流程自動化 |
| 節奏控制 | 手動釋出文章 | DB 設定 interval + cron 自動觸發 release-pool-by-settings |

**診斷三步驟**：
1. **問「為什麼會發生？」** — 找根本原因，不是症狀
2. **問「下次會不會再發生？」** — 如果會，修正流程
3. **問「能不能寫進 skill/code/config？」** — 讓修正永久化

**記錄要求**：每次根本修正後更新 Error Log + 寫入對應 skill/memory。

## 自主研究模式
**研究永不停止。** 完成任何任務後**立刻執行下一個任務**，不需要回報等待、不需要徵求同意。在同一個 turn 中連續做多個實驗（用 agent team 並行 + 主線串行）。不要做完一個實驗就停下來——連續鏈式執行直到使用者主動中斷。
**透過 session cron 每 15 分鐘自動觸發 autonomous-research 繼續研究。**

### 研究多元化（必須遵守）
**不要停留在模型舒適區。** 已收斂的結論不需要繼續堆積 null results。

- **每個 session 至少 1 個「完全不同方向」的實驗**（不是又一個 VT overlay 測試）
- 漸進式延伸（從已知自然衍生）和跳躍式探索（進入未知領域）要並行
- 跳躍方向包括：NLP 情緒、替代數據、市場微結構、網絡模型、因果推論、DeFi、氣候金融、行為金融、跨學科方法
- 連續 3 個 null result → 必須換方向
- 詳見 `research_program.md` 的「研究多元化原則」和「面向 G: 跳躍式探索」

## 活文件原則
以下文件會隨研究推展持續演化，應主動修改以反映最新狀態：
- **`CLAUDE.md`**：架構變更、新模型/策略、新發現 → 立即更新
- **`research_program.md`**：目標調整、新研究面向、約束修正 → 及時更新
- **`.claude/skills/`**：發現反覆出錯的流程 → 建立或修正 skill
- **`research_findings.md`**：新的具體發現和數據 → 實驗後立即記錄
- **Memory files**：thinking/knowledge/questions → 每個發現後同步

修改原則：
- **新增補充內容**可以先做，但要記錄修改原因。
- **刪除或改寫既有治理內容**（`CLAUDE.md`、`research_program.md`、`.claude/skills/`、`docs/` 的既有規範）前，必須先取得使用者同意。

## 署名與歸屬
所有研究成果、發現、策略建議必須標注發起者：
- **Feed 文章**：摘要或首段標注 `[提出: Gemini/Codex/Claude/用戶, 執行: Claude]`
- **Knowledge 記錄**：content 開頭標注 `[提出: XXX, 執行: Claude]`
- **Open Questions**：記錄是誰提出的問題
- **論文**：作者為 Yi-Hao Lai + VolPred Research System，致謝 Codex/Gemini
- **研究方向**：記錄建議來源（例：N182 Excess Fear Signal 由 Gemini 提出）

## 架構
- **Python CLI (volpred)**：研究引擎（實驗、評估、記憶、發佈）
- **storage/**：唯一資料源頭（JSON），跨 session 保存
- **frontend-v2-fix/**：Next.js 15 前端（開發優化中，Admin CMS + 用戶專區 + SSR）
- **frontend-v2/**：目前線上部署版本
- **frontend/**：舊版前端（已棄用）
- **scripts/supabase_sync.py**：資料同步到 Supabase
- **src/volpred/ops/jobs.py**：Supabase-backed job queue（agent + human 共用）
- **research_program.md**：研究策略文件（北極星）
- **paper/**：學術論文（按子目錄組織）

### Supabase 資料庫表
| 表名 | 用途 |
|------|------|
| `articles` + `article_tags` | 文章（feed）+ 標籤 |
| `strategy_signals` | 策略即時信號（權重、VIX、sigma） |
| `paper_trades` | Paper trading 每日記錄 |
| `strategy_metrics_cache` | 預計算的績效指標 + sparkline |
| `questions` + `question_articles` | 會員問答系統 |
| `memory_entries` | 研究記憶（thinking/knowledge/experiments） |
| `profiles` + `quota_usage` | 用戶角色（admin/premium/free）+ 配額 |
| `article_impressions` + `article_reactions` | 互動追蹤（瀏覽/按讚/收藏） |
| `ops_jobs` + `ops_job_logs` + `ops_audit_logs` | Job queue + 審計紀錄 |
| `papers` | 論文 metadata（論文頁 DB 驅動） |
| RPC: `feed_page()`, `feed_tag_counts()` | 伺服器端分頁查詢 |

### Supabase Migrations
- `004_deep_efficiency.sql` — 索引 + feed RPC + strategy_metrics_cache
- `005_ops_control_plane.sql` — ops_jobs + audit logs
- `006_reload_postgrest_schema.sql` — schema refresh

## AI 協作模式（Claude + Codex + Gemini）

三個 AI 各有分工，不只是評審——也是研究夥伴：

| AI | 角色 | 使用方式 | 擅長 |
|---|---|---|---|
| **Claude**（主研究員）| 實驗執行、分析、記憶管理、論文寫作 | 直接執行 | 深度分析、code、持續研究 |
| **Codex (GPT)**| 嚴格審查、策略建議、新方向 | `/codex-cli` | 找漏洞、結構性問題、editorial advice |
| **Gemini** | 方法論建議、文獻連結、robustness 建議 | `/gemini-cli` | 學術框架、cross-reference、新測試建議 |

### 協作場景
- **論文審查**：三方各自審查 → Claude 整合修正
- **研究方向探索**：問 Codex/Gemini「接下來該研究什麼？」「有什麼盲點？」
- **新策略發想**：讓 Gemini 建議新的投資策略或風控方法
- **方法論驗證**：Gemini 建議用 EGARCH 驗證 → Claude 執行 → 確認 proposition robust
- **系統功能**：讓 Codex 幫忙寫程式、debug、優化架構

### 不要只當評審用
Codex 和 Gemini 可以：
- 提出新研究假說
- 建議尚未探索的文獻方向
- 幫忙設計實驗
- 生成論文段落草稿
- 延伸研究到新資產/新市場

### 研究主題來源（必須多元，不能只靠 Claude 自選）
研究主題的來源應該包括：
1. **Codex/Gemini 建議**：每 5-10 個實驗主動問一次「接下來該研究什麼方向？」，將建議寫入 research_program.md
2. **用戶指定**：用戶提出的方向優先執行
3. **會員問題**：每 6 小時 cron 自動評估會員提問
4. **文獻搜索**：WebSearch arXiv/SSRN 發現的前沿方向
5. **Claude 自選**：基於 research_program.md 的待探索方向
6. **跨 AI 交叉驗證**：一個 AI 提出假說 → 另一個 AI 設計實驗 → Claude 執行

**標準流程**：每開始新一輪實驗前，先問 Codex 或 Gemini「給我 3-5 個研究方向」→ 從中選擇 → 標注 `[提出: Codex/Gemini]` → 執行

## 硬體資源

| 項目 | 規格 |
|------|------|
| CPU | Apple M1 Max · 10 核心 |
| RAM | 64 GB |
| 平行 agent 建議 | 3-4 個 worktree agent 同時跑（每個 ~1GB RAM） |
| GARCH 估計速度 | ~6ms/model（單核） |
| Bootstrap 10,000 reps | ~2-5 秒 |
| 大規模 sweep（100 configs） | ~1 分鐘（單核串行） |

設計分析程式時參考：
- 可用 `multiprocessing` 平行化 cross-asset sweep（10 核 → 10 資產同時跑）
- 64GB RAM 足以載入全部資產的完整歷史（~500MB total）
- Agent worktree 每個 ~800MB，同時 4 個 = 3.2GB（無壓力）

## Agent Team 工作分派

Claude Code 的 Agent 工具可啟動獨立子程序（subagent），有自己的 context window 和工具權限。
核心參數：
- **`isolation: "worktree"`**：在獨立 git worktree 執行，不影響主分支檔案
- **`run_in_background: true`**：背景執行，主對話可繼續其他工作，完成時自動通知
- **`subagent_type`**：`general-purpose`（預設，可寫檔）、`Explore`（唯讀，快速搜尋）、`Plan`（規劃）
- **`resume: "agentId"`**：用之前的 agent ID 恢復已完成 agent 的 context 繼續工作
- 多個獨立 Agent 可在同一訊息中**並行啟動**，大幅提升效率

| 任務類型 | Agent 設定 | 說明 |
|----------|-----------|------|
| 研究實驗 | `isolation="worktree"` | 跑 GARCH、統計測試，不影響主目錄 |
| 並行實驗 | 多個 `isolation="worktree"` 同時發送 | 同時跑多資產/多模型 |
| 背景部署 | `run_in_background=true` | upload-codebase frontend-v2，不阻塞研究 |
| 代碼探索 | `subagent_type="Explore"` | 快速搜尋代碼結構（唯讀） |
| AI 協作 | `/codex-cli`, `/gemini-cli` | 研究建議、審查、新方向 |
| 文獻搜尋 | `Agent + WebSearch` | 最新方法、論文 |
| 高品質發文 | 用 `feed-publisher` skill | Agent 寫完整文章再發佈 |

## 自動化排程
### 永久任務（系統 crontab — 無人值守也會跑）
```
0 15 * * 1-5   collect_tw_data.py      # 台股收盤後 15:00（0050.TW + VIXTWN + 5min，留 1.5h 給 yfinance 更新）
30 5 * * 2-6   collect_us_data.py      # 美股收盤後 05:30（SPY/GLD/VIX + 5min）
3 6 * * 2-6    daily_update.py         # 所有數據就緒 06:03（6 策略 + Supabase sync）
3,18,33,48 * * * *  release-pool-by-settings  # 文章池定時釋出：每 15 分鐘 1 篇（不受 session 影響）
```
注意：美股 cron 用 `2-6`（週二至六），因為美股週五收盤 = 台北週六 04:00。
注意：文章釋出用 system crontab 而非 session cron，確保不受 Claude 工作狀態干擾。

### Session Cron（每次新 session 重建，需 Claude 活躍）

#### 最小啟動集（保守模式，建議先採用）
```
CronCreate(cron="13 */6 * * *", prompt="會員問題研究")               # :13 每6小時
CronCreate(cron="37 */6 * * *", prompt="平台巡檢")                   # :37 每6小時（ops health + platform-cycle-summary）
CronCreate(cron="47 */2 * * *", prompt="每2小時 git commit")        # :47
CronCreate(cron="7 * * * *", prompt="知識索引更新")                 # :07（auto 偵測變化，無變化不 rebuild）
```

#### 全速模式（確認穩定後加入）
```
CronCreate(cron="5,20,35,50 8-23 * * *", prompt="繼續研究")         # 08-23時 每15分鐘
CronCreate(cron="5 0-7 * * *", prompt="繼續研究")                   # 00-07時 每小時
CronCreate(cron="37 */2 * * *", prompt="網站健康檢查（含自動修復）")   # :37（升級為每2小時）
```
注意：一次性 cron（如 FOMC 提醒）必須先確認事件的確切時間再換算台灣時間（UTC+8）。

## 模型體系（持續探索，非線性階段）

### 波動率預測模型
| 模型 | 用途 | 狀態 | 備註 |
|------|------|------|------|
| **GJR-GARCH** | γ>0.10 資產（SPY/QQQ/EEM）| 主力 | MCS superior, EGARCH 驗證一致 |
| **GARCH** | γ<0.10 資產（GLD）| 主力 | DM test 無顯著差異時優先 |
| **MF2-GARCH** | 多成分 vol cycle | 已測試 null | Conrad & Engle 2025 JAE。K141 TLT +0.30% 是 estimation artifact（K144: proper joint QML 6 assets → GJR 5/6 勝）。QLIKE ceiling 全面確認 |
| **EGARCH** | Robustness check | 輔助 | γ 符號相反但結果一致 |
| **HAR-RV** | 5-min realized vol | 待驗證 | 需 60+ 天 5-min 數據（SPY 46 天 / 0050.TW 34 天，持續累積中）|
| **Realized GARCH** | 5-min RV + GARCH | blocked | 需 252+ 天（~2027 Q1）|
| **LSTM/GRU** | Deep learning | 已測試失敗 | 日頻殘差 iid，DL 無增量（但數據增加後可重試）|
| **GARCH-LSTM Hybrid** | 結合統計+DL | 已測試失敗 | LSTM factor 不穩定（std=1.16）|
| **XGBoost+HAR** | ML vol forecast | 已測試失敗 | K142: GJR 3/3 勝。日頻 r² 信噪比太低，第 4 次 ML 失敗 |
| **組合預測** | 70/30 GJR+HAR | 已測試 | 約束條件下最佳，但改善微小 |
| **EWMA(λ=0.97)** | 零售簡易 VT | 輔助 | J6/J9: Sharpe 等效但 GJR 贏 crisis MDD。一行 Excel，TX 省 150bps/yr |
| **EWMA(λ=0.94)** | RiskMetrics 標準 | 輔助 | HL=11d，比 0.97 略差 |
| **BTC RV-VT** | BTC 自身 realized vol VT | 已測試 | 用 22d RV，非 VIX。MDD 顯著改善(p=0.003)，Sharpe 不顯著 |

### VT 策略模型
| 策略 | Sharpe | MDD | 適用 |
|------|--------|-----|------|
| **12/VIX + SHY** | 0.68 | -27% | 美股單資產（最簡單）|
| **★ 50/50 SPY/GLD 12/VIX** | 0.83 | -16% | 美股最佳零售組合（Q21 推薦）|
| **40/30/30 SPY/QQQ/GLD** | 0.82 | -18% | 美股多資產（QQQ 增加 tail risk）|
| **Conditional TLT** | 1.08 | -19% | 利率下降時加 TLT（5/5 穩健）|
| **~~10d SPY Mom (台股)~~** | ~~1.47 (net)~~ | ~~-10.0%~~ | ⚠️ c2c Sharpe 含 timing bias，可實施 o2o Sharpe=0.87 (FAIL Harvey) |
| **~~10d SPY Mom (日經)~~** | ~~1.31 (net)~~ | ~~-14.0%~~ | ⚠️ 同上，需用 o2o 重新驗證 |
| **~~TW+JP 50/50 TZ~~** | ~~1.81 (net)~~ | ~~-11.9%~~ | ⚠️ 基於 biased c2c，需重新計算 |
| **~~Global US VT + TW TZ~~** | ~~1.61 (net)~~ | ~~-8.4%~~ | ⚠️ 同上 |
| **8.63/VIX (0050.TW)** | 0.69 | -15% | 台灣市場（VIX proxy, monthly rebal, lagged, TX 0.585%）|
| **VIX Step Rule** | 0.69 | -21% | 零計算（VIX<15→100%, 15-25→70%）|
| **BTC RV VT(15%)** | 0.50 | -42% | 加密貨幣（用自身 RV，非 VIX）|
| **BTC Asym VT(25/10)** | 0.68 | -53% | 加密動量+VT（t=2.0, fails Harvey）|

⚠️ **Same-day timing bias warning (Q10)**: VIX_t→r_t 的回測 Sharpe 會被 ρ(VIX,SPY)=+0.65 膨脹 ~1.0。
正確做法：VIX_t 決定 r_{t+1} 的權重。上表已使用 lagged weights。

### 報酬預測信號
| 信號 | In-sample t | OOS t | 狀態 |
|------|------------|-------|------|
| **Excess Fear (VIX/GARCH Z>1.5)** [Gemini] | 4.48 | 2.61 | 有前景但 OOS 衰減 |
| **SPY(t)→tw50(t+1)** [用戶] | — | r=0.376 | ⚠️ 信息傳遞有效 (gap R²=0.35) 但不可交易 (o2o Sharpe=0.87) |
| Vol→Return 直接預測 | -0.002 | — | 失敗（r≈0）|
| VRP timing | — | — | 失敗（N90, Q10, T9 reconfirmed）|

### 參數設定
- Window=2000 預設（w=504 有 persistence bias -3%）
- Student-t 固定 df：**df=4 優於 df=5**（J20: 9/11 vs 7/11 Kupiec pass）。但 Skewed-t MLE 最佳 (10/11)
- **★ Skewed Student-t 是最佳 VaR 方法**——6/6 資產通過 Kupiec（唯一全通過），優於 CF-VaR (5/6)。通過 MLE 同時估計 df + skewness，自動適應所有資產
- CF-VaR（Cornish-Fisher）是次佳——5/6 通過，但 QQQ 過度保守。在 0050.TW w=2000 時會發散，需 winsorization
- 12/VIX threshold=12（不是 cherry-pick，target 6-20 全部有效）
- **多頻率研究**：不限日頻——週/月/季/年都要探索。低頻模型注意樣本數（月頻≥60 obs, GARCH 可能不穩定）
- **資料時效**：OOS 延伸到最新。cache/存檔不到最近日期時用 `force_refresh=True` 重抓
- **跨資產假日**：多資產投組中某資產無當日價格 → forward-fill 前一交易日價格，return=0

## 評估體系

### A. 統計性評估（預測準確性）
| 指標 | 公式/說明 | 用途 | 備註 |
|------|----------|------|------|
| **QLIKE** | Σ(log(σ²) + r²/σ²) | **主要 loss function** | 對低估波動率懲罰更重（asymmetric），proxy-robust（Patton 2011）|
| **MSE** | Σ(σ² - r²)² | 輔助 loss function | Symmetric，對極值敏感 |
| **MAE** | Σ|σ² - r²| | 輔助 | 比 MSE 更 robust to outliers |
| **HMSE** | Σ(1 - r²/σ²)² | Scale-invariant | 消除 proxy 尺度差異（R11 驗證）|
| **Mincer-Zarnowitz R²** | 回歸 r² = a + b·σ² 的 R² | 校準檢定 | b=1, a=0 為完美校準 |
| **DM test** | Diebold-Mariano t-stat | 兩模型比較 | 單邊 p<0.05 為顯著 |
| **MCS** | Model Confidence Set | 多模型比較 | Hansen et al. (2011)，控制 data snooping |
| **GW test** | Giacomini-White | 條件預測能力 | 比 DM 更 general（允許 estimation uncertainty）|

### B. 風險管理評估（VaR/ES）
| 指標 | 說明 | 門檻 | 備註 |
|------|------|------|------|
| **Kupiec LR_uc** | 違反次數 vs 期望次數 | p>0.05 通過 | Unconditional coverage |
| **Christoffersen LR_cc** | 違反的獨立性 | p>0.05 通過 | Conditional coverage（含 clustering）|
| **DQ test** | Dynamic Quantile | p>0.05 通過 | Engle & Manganelli (2004)，最嚴格 |
| **Trinity test** | Kupiec + CC + DQ 三重 | 3/3 通過 | 我們的標準（T21 Master Panel）|
| **Fissler-Ziegel** | Joint VaR+ES loss | 越低越好 | O16: coverage vs efficiency trade-off |
| **Acerbi-Szekely** | ES backtest (Z1/Z2) | p>0.05 通過 | O14: 三種分配全 pass |
| **Basel traffic light** | 250天違反次數 | GREEN ≤4 | 實務監管標準 |

### C. 經濟性評估（策略績效）
| 指標 | 說明 | 門檻 | 備註 |
|------|------|------|------|
| **Sharpe ratio** | (E[r]-rf)/σ | Harvey 2016: t>3.0 | SE ≈ 1/√N_years，多重檢定要 Bonferroni |
| **MDD** | 最大回撤 | bootstrap p<0.001 | Mechanical effect（Q20: 100% sims positive）|
| **Calmar** | return/|MDD| | — | 結合報酬與風險 |
| **Sortino** | (E[r]-rf)/σ_downside | — | 只懲罰下行風險 |
| **CRRA utility** | E[W^(1-γ)]/(1-γ) | γ=3,5,10 | 考慮投資人風險偏好 |
| **Certainty Equivalent** | CE return | — | 投資人願意接受的確定報酬 |
| **Information Ratio** | α/TE | — | 相對 benchmark 的超額報酬 |
| **Win Rate** | % positive return days | — | 輔助 |
| **Turnover** | Σ|Δw| / N_years | — | 交易頻率，影響 TX cost |
| **Net Sharpe** | Sharpe after TX cost | — | J10: monthly 12/VIX net 0.792 最佳 |

### D. 跨資產 / 跨模型比較
| 指標 | 說明 | 備註 |
|------|------|------|
| **Gamma-mechanism** | γ → VT Sharpe (equity only) | Q19: pure equity ρ=0.886 (p=0.019) |
| **VIX correlation** | corr(asset, ΔVIX) → VT effectiveness | Q16: best cross-asset predictor (r=0.54) |
| **CCS Score** | Complexity Ceiling Score | Q22: 31 模型評分，52% 零/負價值 |
| **FDR audit** | Benjamini-Hochberg correction | Q12: 30/32 findings survive q=0.05 |
| **Cross-OOS** | 多期間 OOS 一致性 | J9: 5 periods mandatory for strategy claims |
| **Weight path StdΔw** | 權重路徑波動度 | J7: 不是 MDD 的因果因子 |

## 核心研究發現（details in `storage/memory/knowledge.json`）
- GJR-GARCH 是最佳 realized vol 模型（MCS superior, p=0.044）
- 12/VIX 打敗 GARCH VT（5/7 OOS periods）
- Gamma-mechanism proposition 已修正：全樣本(N=12) rho=-0.45 (n.s.)，但純股票(N=6) rho=+0.886 (p=0.019)。跨資產類別時 VIX correlation 才是真正驅動因子
- VT Sharpe 不顯著（t=0.33）但 MDD 顯著（bootstrap p=0.0004）
- MDD improvement 是 mechanical（99% under null）
- 台灣 amplification 4.6x（vs US 2.8x）
- CASH 是唯一通用避險（6 場危機 4 種類型）
- 12/VIX+SHY 全面勝 60/40
- Excess Fear Signal t=4.48 in-sample（Gemini 提出）
- FHS 是唯一通過 Kupiec+Christoffersen+DQ 三重 VaR 檢驗的方法（7/7 資產全通，Codex 提出）
- BTC 正偏態不穩定（regime-dependent, 55% 時間正），coskewness=-0.61（惡化組合尾部）
- BTC VT(15% target) MDD: -84%→-42% (p=0.003)，Sharpe 改善不顯著 (t=1.45)
- |Skewness|→VaR method 宣稱已推翻（N=12 rho=-0.87 → N=21 rho=-0.086, p=0.71）
- ~~SPY Overnight Momentum for Taiwan: 5d SPY Mom net Sharpe 1.62, Harvey t=3.25~~ → **I8 降級**: c2c Sharpe 含 timing bias，o2o 僅 0.87 (FAIL Harvey)。信息傳遞通道有效但不可交易
- **⚠️ TZ Momentum Timing Bias (I8)**：c2c Sharpe 包含不可捕獲的隔夜跳空（78% alpha）。所有可實施策略 FAIL Harvey。TZ 是學術發現，非可交易策略。3 策略 inactive
- **★★★ Phase J 核心發現**：
  - J5→J6→J7→J9 完整弧：EWMA(0.97) Sharpe ≈ GARCH，但 GJR 在危機中贏 MDD (4-5/5 periods)。Smoothness 假說被推翻（ρ=-0.007），真正機制 = crisis reactivity + signal quality
  - 12/VIX 是 VT 的 irreducible kernel（J13: 6 種 conditional VT 全 null）
  - 50/50 SPY/GLD static 是最難打敗的月度基準（J1: Sharpe 0.810）
  - VIX 是月度以下的 sufficient statistic（21 次確認：J3/J4/J8/J14/J17/J18/K1/G3/G5/T11/T13/T14 + K148 Climate/K149 ICL/K151 CSVD/K152 Liquidity/K153 MOVE-VECM）
  - 月度再平衡優於日度（J10: net Sharpe 0.792 > 0.679，TC 省 0.72%/yr）
  - EWMA(0.97) 是零售最安全 default（J12: best MDD 4/7 assets, never worst）
  - VIX sufficient statistic 需限定範圍：「relative to tested alternatives at this horizon」（Codex 建議）
  - 253 起始日 100% MDD win rate（K14）——VT 不是 backtest fishing
  - **跨資產 VT 地圖**：equity ✓(10 markets), carry ✓(K18), commodity ✗(K21), HY bond ✗(K24), intl equity US VIX universal(K25)
  - Multi-period VT 數學上等價（K23: sqrt(h) 相消）
  - 50/50 SPY/GLD 經 8 次獨立驗證不可動搖（K2/K16/K19/K24/K54/K63/K64/K89）
  - ★★★ K41→K91 VT Insurance Pricing 修正: 76 年均值 ~1%/yr（非 4%/yr），VIX 時代 2-4%/yr，高度不穩定 (std=2.54%)。MDD 保護 8/8 十年全勝
  - K36/K39/K40 trilogy reframed: 不是「VT 長期有害」，而是「保險費會複合」
  - K85→K87 退休修正: VT 不翻倍提領率，只提供更穩定的 4% 存活率
  - K102 Vol→Return: VIX 預測報酬 R²<2%，VT 是風險管理不是報酬增強
  - 0DTE 沒有破壞 VT（K38: VIX-SPY corr 不變 -0.729）
- **AI 協作建議（Codex+Gemini 第 5 次審查）**：
  - **Codex**：論文 framing 改為 criterion-dependent model selection；pre-register primary claims；停止 VT overlay search
  - **Gemini**：VVIX tail-guard overlay、correlation breakdown penalty、FHS-VaR targeting 取代 σ-targeting
  - **共識下一步**：(1) 5-min data pipeline 優先 (2) options-implied surface (VVIX/SKEW/VIX term structure) (3) FHS-VaR targeting (4) 驗證 df=5 跨資產 robustness

## 網站優化待辦（詳見 `docs/website-optimization-plan.md` + `docs/execution_backlog_2026-03-20.md`）

### v4 重構（frontend-v2-fix 進度）
- [x] V0.1: 策略面板 sparkline 走勢圖 → `PaperTradingChartIsland` + `strategy_metrics_cache`
- [x] V0.4: Portfolio 頁面 → `PaperTradingStrategyChart` + `PaperTradingTradeLog`
- [x] V0.5: FTS 搜尋改 server-side → `feed_page()` RPC
- [x] Admin CMS：9 個核心面板（analytics/content/ops/strategies/questions/users/paper-trading/health/schedules）+ program legacy
- [x] 用戶專區 `/me`：書籤、提問、活動摘要
- [x] 互動追蹤：瀏覽/按讚/收藏/分享（`ArticleEngagement` 組件）
- [x] Ops Control Plane：`OpsConsole` + `ops_jobs` 表 + job 生命週期
- [ ] V0.7: Feature gating 前端 enforce
- [ ] V0.9: API rate limiting
- [ ] V0.10: Supabase heartbeat cron 防 pause

### 最高優先（SEO — 目前 Google 完全找不到）
- [ ] W1.1: robots.txt + sitemap.xml + favicon + manifest.json
- [ ] W1.2: OG tags（全站預設 + 文章動態 generateMetadata）
- [ ] W1.3: JSON-LD 結構化資料（Article, FAQPage, WebSite）

### 高優先（產品化 + 留存）
- [ ] W2.1: 首頁 Hero Section（價值主張 + CTA）
- [ ] W2.2: 首頁預設「一般讀者」tab + 精選文章置頂
- [ ] W2.3: 清理重複的每日建議（同日只留最新）
- [ ] W3.2: 文章分享按鈕（LINE / FB / Twitter）
- [ ] W5.1: 加入 Plausible/Umami Analytics

### 中優先（信任 + 體驗）
- [ ] W4.1: 「關於」頁面（研究背景、團隊）
- [ ] W3.1: Email/LINE 訂閱系統
- [ ] W3.3: 新手指南頁面（`/guide`）
- [ ] W4.3: 免責聲明頁面
- [ ] W5.3: 亮色模式修復 + 手機導覽優化

## Error Log

| 日期 | 問題 | 現象 | 過程 | 解決方法 |
|------|------|------|------|---------|
| 2026-03-16 | Thinking page crash | experiment_ids undefined → 頁面閃退 | experiment_ids 欄位在部分 entry 不存在 | 加 optional chaining `?.` + `&&` guard |
| 2026-03-16 | Feed 文章缺 content | 網頁顯示空白文章 | `record_and_publish.py` 只用 `--thinking` 當 content | 個別檔案 + feed.json 都要有完整 Markdown content |
| 2026-03-16 | Citation errors | 論文引用 6 處錯誤 | Cederburg fabricated, Kim wrong, etc. | `/citation-verifier` + WebSearch 驗證每筆引用 |
| 2026-03-16 | Same-day timing bias | 12/VIX Sharpe 從 0.96 膨脹到 1.98 | VIX_t 和 r_t 同日 → 前瞻偏誤 | 必須用 lagged weights (VIX_t → r_{t+1}) |
| 2026-03-16 | LanceDB ArrowInvalid | knowledge index build 失敗 | confidence/category 欄位混合 int/str 類型 | 統一 confidence=float, category=str |
| 2026-03-16 | Worktree 累積 11GB | VS Code 顯示大量未 commit 檔案 | Agent worktree 未清理 | 實驗完成後清理 worktree（已寫入 skill Rule #23）|
| 2026-03-17 | Feed 文章又變純文字 | 最近 3 篇文章只有 80-100 字 | 持續用 `record_and_publish.py --thinking` 快速發文 | 完整文章必須用 `feed-publisher` skill 或直接寫 content JSON。`record_and_publish.py` 只適合里程碑通知 |
| 2026-03-17 | |Skewness| 小樣本膨脹 | N=12 rho=-0.87 看似顯著 | 未遵守 N≥15 cross-sectional 約束 | 擴展到 N=21 後 rho=-0.086 (NS)。教訓：尊重自設統計門檻 |
| 2026-03-17 | 5-min 數據未收集 | storage/5min_data/ 空資料夾，42天數據全部遺失 | crontab cd 沒生效，python 找不到 scripts/ | 需修正 crontab 用絕對路徑：`.venv/bin/python /full/path/scripts/collect_5min_data.py` |
| 2026-03-17 | GBM ceiling crack FALSE ALARM | SPY -18.7% 看似 breakthrough | 單一資產+單一 OOS 不可信。Cross-asset 15 cells: 0/15 GBM 顯著贏 | 永遠做 cross-asset + cross-OOS 驗證再宣布結論。Rule #16 必須執行 |
| 2026-03-17 | Zeabur OAuth redirect localhost:8080 | Google OAuth 登入後導向 `localhost:8080#access_token=...` | Zeabur reverse proxy 內部跑 port 8080，`new URL(request.url).origin` 拿到內部地址 | callback route 改用 `x-forwarded-host` header 或 `NEXT_PUBLIC_SITE_URL` env var 取得真正外部 URL。詳見 `docs/zeabur-oauth-gotcha.md` |
| 2026-03-18 | 策略上線流程 4 個問題 | 面板有策略但績效表空/交易紀錄消失 | (1) DB strategy_key=null (2) 回測沒合併到 paper_trading.json (3) API route 用 last-wins 覆蓋 entries (4) Supabase 預設 1000 行 limit | (1) 用 add_strategy.py 補填 key (2) 回測後必須合併+recalc (3) API 改 push to array (4) 加 pagination while loop。教訓：SOP 每個步驟都要驗證 |
| 2026-03-18 | TZ Momentum timing bias | c2c Sharpe 3.09 但 o2o 僅 0.87 (-72%) | SPY(T) 5am 收盤→信號生成，台灣 9am 開盤已 price-in (gap R²=0.35)。c2c 回測假設 close(T) 建倉=比信號早 15.5h | 所有可實施策略 FAIL Harvey: o2o=0.87, o2c=0.73, SPY(T-1)+c2c=0.95。TZ alpha 被開盤競價機制捕獲。月度 VT 不受影響（慢信號+長持倉期）。教訓：跨時區策略必須用 open-to-open 驗證 |
| 2026-03-18 | Supabase Disk IO 瓶頸 | 全部 API timeout | 每小時全量 upsert 417 articles + 2620 memory entries + 7000 paper trades | (1) incremental sync（只 sync 新增/變更）(2) strategy-metrics 5 分鐘 cache (3) sync 頻率降為每 3 小時 (4) paper-trading API 加 COMMON_START filter。教訓：全量 upsert 在資料量成長後不可持續 |
| 2026-03-18 | Daily update 3 個系統性問題 | (1) yfinance 快取永不更新 (2) Supabase updated_at 不自動刷新 (3) 策略 metadata 散落三處 | DataManager.get_price_data 的 cache-first 邏輯讓 collect_us_data.py 永遠讀舊快取；sync_strategy_signal 沒傳 updated_at；feed 文章用 internal key + 沒過濾 TZ | (1) collect/daily_update 加 force_refresh=True (2) sync_strategy_signal 明確傳 updated_at (3) 建立 STRATEGY_REGISTRY 單一來源，驅動 feed 文章 + Supabase + paper trading。教訓：資料收集腳本必須 force refresh；metadata 不能 hardcode 在多處 |
| 2026-03-20 | 5-min 數據不會回補 | 0050.TW 只有 7 天 5-min 數據（應有 60 天） | `collect_5min_data.py` 硬寫 `days_back=7`，沒有 gap detection。paper trading 也只回填前一天 | (1) 加 `_detect_gap_days()` 自動偵測最後收集日期，回補至 59 天 (2) 0050.TW 立即回補到 34 天 (3) daily_update.py 改為回填所有 `portfolio_return=None` 的條目。教訓：資料收集腳本必須考慮停機回補 |
| 2026-03-21 | DB interval_hours 不支援 15 分鐘 | 用 session cron 繞過 DB integer 限制 | DB `interval_hours` 是 integer，存不了 0.25。Claude 用 cron `--include-drafts` 繞過 | 根本修正：(1) DB migration `interval_hours`→`interval_minutes` (integer) (2) Python+TS normalize 改為 minutes (min=5) (3) `timedelta(minutes=)` 取代 `timedelta(hours=)`。教訓：**絕不用 workaround 繞過系統限制，改底層設計** |
| 2026-03-21 | 手動改 status 導致前端看不到文章 | 前端只看到 2 篇（本地有 10 篇） | 手動改 `feed.json` 的 `status=published` 不觸發 Supabase sync。`release-pool-by-settings` 內建 sync 但被繞過 | 根本修正：(1) feed-publisher skill 規定所有文章一律 `status=draft` (2) 只透過 `release-pool-by-settings` 釋出（內建 sync）(3) 禁止手動改 JSON status。教訓：**修改資料的唯一合法途徑是透過 ops 層 CLI/API，不是直接改檔案** |
