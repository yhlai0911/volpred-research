# 自主波動率預測研究系統
原則上使用繁體中文互動

## 研究誠實原則（最高優先，不可違反）

**一切結果必須真實、嚴謹、可驗證。違反任何一條即視為研究失敗。**

1. **不可造假、不可虛構**：所有數據、統計量、圖表必須來自實際計算，不可編造數字或偽造結果
2. **數據來源透明**：每個實驗必須標明數據來源（yfinance、FRED、CBOE 等）、資料期間、樣本數量。不可用模擬數據冒充實證數據
3. **實驗必須有對應檔案**：每個實驗必須有可執行的程式檔案（`experiments/<experiment_id>.py`）和結果檔案（`experiments/<experiment_id>_results.json`）。不可只用 inline code 跑完就丟——無法指出檔案和資料存檔位置的研究等同虛假研究。Agent worktree 的實驗完成後也必須把腳本和結果複製到主分支
4. **文獻先於實驗，理解先於動手**：每個特定主題的研究開始前，**必須先搜尋並分析相關學術文獻**，不可直接憑直覺設計實驗。具體要求：
   - **搜尋**：用 WebSearch 搜尋 arXiv/SSRN/Google Scholar 該主題的關鍵論文（至少 3-5 篇）
   - **分析**：閱讀方法論、數據來源、核心發現、局限性。用 sci-hub skill 取得全文
   - **文獻探討**：整理已知結論（什麼已經被證實/否定？）、方法論選擇（前人用什麼方法？為什麼？）、我們的差異化（我們能做什麼不同的？）
   - **決定實驗設計**：基於文獻分析決定模型選擇、參數設定、評估指標，而非自行猜測
   - **記錄來源**：實驗腳本和結果 JSON 必須標注參考文獻（作者、年份、期刊、核心方法）
   - **例外**：純探索性實驗（沒有明確主題的跳躍式探索）可以先做再查文獻，但事後仍須補充文獻連結
5. **觀察先於計算，異常觸發覆查**：所有統計分析必須遵循「資料診斷 → 基本統計 → 估計 → 收斂檢查 → 延伸分析」的順序。具體要求：
   - **開始前**：描述性統計（均值/標準差/偏態/峰態）、ADF 定態檢定、ARCH LM 檢定、自相關（Ljung-Box）
   - **估計後**：收斂狀態（convergence flag）、參數有效性（persistence < 1）、殘差診斷（標準化殘差無剩餘 ARCH）
   - **結果異常時**：HE < 0、相關係數不穩定、parameter 在邊界上 → 必須啟動覆查，不能直接報告
   - **期貨避險特別注意**：spot-futures 相關性穩定性（rolling correlation）、共整合檢定、ETF 結構問題（如 USO contango roll）
6. **方法論嚴謹**：每個結論必須經過正規統計檢定（DM test、t-test、bootstrap），不可僅憑觀察就下結論。遵守 Harvey (2016) t>3.0 門檻
7. **區分實證與理論**：明確標示每項分析屬於「實證分析（真實數據）」、「理論推導」或「模擬實驗」。不可混淆
8. **Null result 如實報告**：負面結果同樣重要，必須完整記錄。不可只報告成功、隱藏失敗
9. **發佈內容真實不虛**：Feed 文章、研究摘要、知識記錄的每一項數據和結論都必須可追溯到具體實驗腳本和數據
10. **承認局限**：每個發現都必須說明其局限性（樣本大小、OOS 期間、資產範圍、proxy 變數的假設）
11. **不可過度宣稱**：結論的強度不可超過證據支持的範圍。partial r=0.08 不可宣稱為「突破性發現」
12. **自我修正後回溯更新**：每次推翻或修正先前結論時，必須立即：
   - 搜尋已發佈文章中引用該結論的內容（用 grep 搜尋關鍵詞）
   - 在受影響文章頂部加入 `⚠️ 更正聲明（日期）`，說明修正內容
   - 更新 feed.json 和個別 report JSON 的 content/description
   - 同步到 Supabase（`supabase_sync.py full`）
   - 記錄到 `docs/error_log.md`（自我修正類）

## 專案簡介
Claude Code 驅動的自主研究系統，用於尋找給定資產的最佳波動率預測模型，並建立一般投資人可用的交易策略。

## 網站架構（v4 Supabase + Admin CMS + Mirror API）
- **前端（線上版）**：`frontend-v2-fix/`（Next.js 15 + React 19 + Supabase，部署於 volpred-v3 服務）
- **前端（舊版）**：`frontend-v2/`（已停用，保留參考）
- **Mirror API**：`mirror-api.zeabur.app`（研究記憶檔案鏡像，減少 Supabase egress）
- **資料庫**：Supabase（PostgreSQL + Auth + REST API + RPC）
- **Zeabur Dashboard**：https://zeabur.com/projects/69b5b264800a475a1f82b073
- **線上網址**：https://volpred.zeabur.app
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

### 每日文章產出要求（不可缺少任何一種）

每天必須產出以下三種類型的文章，面向不同讀者群：

| 類型 | 目標讀者 | 每日數量 | 內容要求 | tags 必含 |
|------|---------|---------|---------|----------|
| **一般讀者** (general) | 非專業投資人 | 4 篇 | 800-1200 字、爆款標題、具體場景、一個核心 takeaway、CTA。基於研究數據但用類比解釋 | `一般讀者` |
| **研究發現** (research) | 有金融背景的讀者 | 2-4 篇 | 實驗結果報告，含統計數據、表格、方法論。每個重要實驗（★+）都應有對應文章 | `研究` |
| **每日建議** (daily) | 所有讀者 | 1 篇 | 當日策略權重、VIX regime、持倉建議。由 `daily_update.py` 自動產生 | `每日建議` |

**執行規則**：
- 所有文章一律 `status=draft` 進文章池，由每小時 cron 按節奏釋出
- **每篇文章必須附圖表**：用 matplotlib 生成 → 上傳 Supabase Storage → content 中用 `![desc](url)` 嵌入。一般讀者至少 1 張，研究文章 2-3 張。不附圖的文章閱讀價值大幅降低
- 一般讀者文章的主題**不可重疊**——每篇必須有獨立的核心 insight
- 用 LanceDB 搜尋確認主題未被寫過同類型文章
- 研究文章在實驗完成後**立刻撰寫**，不要累積
- **每 5 個實驗後必須補充文章池**——檢查池中草稿數量，若 <3 篇則立刻寫 2 篇（1 general + 1 research）
- 每個 session 開始時檢查今日各類型文章產出是否達標
- **池子不可空超過 3 小時**——若空池超過 3 小時等於網站停止更新

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
  - **⚠️ 比較時間必須用 UTC**：`datetime.now(timezone.utc)` 不是 `datetime.now()`。後者是本地台灣時間（UTC+8），會差 8 小時
  - 檢查「多久沒發文」的正確寫法：`(datetime.now(timezone.utc) - datetime.fromisoformat(pub_at).replace(tzinfo=timezone.utc))`
- 跨市場策略注意 VIX lag（台股用前一天 VIX）
- **5-min 數據回補**：收集腳本自動偵測 gap 並回補（上限 59 天 = yfinance 免費版限制）。macOS 休眠時 cron 不執行，醒來後自動回補
- **Paper trading 多日回補**：daily_update.py 自動回填所有 `portfolio_return=None` 的歷史條目（利用相鄰條目價差）
- **frontend-v2-fix 已部署**：`volpred.zeabur.app` 綁定到 volpred-v3 服務（frontend-v2-fix），前端修改只需改 `frontend-v2-fix/`

## 論文
- **第一篇**：`paper/leverage-direction/main.tex`（60 頁，Leverage Direction Matters，目標 JBF）
- **第二篇**：`paper/taiwan-vt/main.tex`（34 頁，Taiwan VT + TZ Information Transmission，目標 PBFJ）
- **第三篇**：`paper/vt-trend-following/main.tex`（24 頁，Is VT Just Trend Following?，目標待定）
- 編譯：`cd paper/<name> && /Library/TeX/texbin/xelatex -interaction=nonstopmode main.tex`（跑兩次解引用）
- 作者：Yi-Hao Lai (Da-Yeh University) + VolPred Research System
- 論文頁 `/paper` 讀 Supabase `papers` table（metadata）；**PDF 放前端 `frontend-v2-fix/public/paper/`**（由 Zeabur CDN serve，不走 Supabase Storage）

### 新策略上線標準程序（發現有效策略後執行）
**不要輕易上架——交易策略必須多次確認，上架後發現錯誤會損害信譽。**
1. **Cross-OOS 驗證**：至少 5 個 OOS 期間（J9 教訓：單期 OOS 不可靠；K459/K474/K476 教訓：cross-OOS 抓到 53% false positive）
2. **3 年回測**：計算 Sharpe/MDD/Calmar/Sortino/Net Sharpe (after TX)
3. **Sensitivity 分析**：不同 TX cost、不同 rebalancing 頻率（K499）、不同起始日期
4. **Out-of-sample 最終確認**：在最近 6 個月的真實數據上確認（不是回測）
5. **加入 STRATEGY_REGISTRY**：`daily_update.py` 頂部加一行 (display_name, is_active, order)
6. **加入計算邏輯**：`daily_update.py` 的 strat_list 區塊
7. **寫入 DB**：`add_strategy.py --id xxx --name xxx ...`
8. **更新 CLAUDE.md 策略表 + research_program.md**
9. **發佈 Feed 文章**：用 `feed-publisher` skill
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
uv run volpred ops article-backups --repair          # 確保每篇已發布文章都有本地單篇 JSON，可用於 DB 災難復原
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
# 安全部署前端代碼到 live service（volpred.zeabur.app -> volpred-v3 service）:
cd frontend-v2-fix && ./scripts/deploy-zeabur-safe.sh
# 文件：docs/zeabur-safe-deploy.md
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

### 實驗前必做：查詢知識庫（不可跳過）
**每個實驗開始前，必須先查詢知識庫確認該主題的過去成果：**
1. `grep -i '關鍵詞' storage/memory/knowledge.json | grep title | head -10`
2. 確認：是否已有相關成果？過去結論是什麼？有無自我修正？
3. 在 agent prompt 中**引用相關 K 編號**，讓 agent 建立在已有基礎上
4. 避免重複實驗、避免被已推翻的結論誤導

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
- **frontend-v2-fix/**：Next.js 15 前端（線上版，volpred-v3 服務）
- **frontend-v2/**：舊版前端（已停用）
- **frontend/**：最舊版前端（已棄用）
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
2. **用戶指定**：用戶提出的方向**優先執行**，且**必須立刻寫入 research_program.md**（不能只口頭回應或只在記憶中記錄）
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
**優先使用 agent team 並行分派任務**，同時推進 3-4 個方向以最大化效率。

### 模型選擇原則（必須遵守）
**根據任務複雜度與難易度選擇適當模型：**

| 任務類型 | 模型 | 原因 |
|---------|------|------|
| **研究實驗**（GARCH、統計檢定、策略回測） | `model: "opus"` | 精確性與專業性要求高 |
| **程式開發**（前端、後端、bug 修復） | `model: "opus"` | 程式碼正確性關鍵 |
| **統計分析**（DM test、bootstrap、cross-OOS） | `model: "opus"` | 數學嚴謹性不可妥協 |
| **論文寫作/審查** | `model: "opus"` | 學術品質要求 |
| **知識合成**（meta-analysis、投資指南） | `model: "opus"` | 需要深度推理 |
| 簡單搜尋（grep、檔案查找） | `subagent_type: "Explore"` | 快速唯讀，不需重模型 |
| 簡單文章撰寫（feed 文章） | `model: "sonnet"` 可接受 | 創意寫作彈性較大 |
| 規劃與架構 | `subagent_type: "Plan"` | 結構化思考 |

**規則：研究、分析、程式等精確性與專業性工作，務必使用 opus 模型。不確定時預設 opus。**

核心參數：
- **`isolation: "worktree"`**：在獨立 git worktree 執行，不影響主分支檔案
- **`run_in_background: true`**：背景執行，主對話可繼續其他工作，完成時自動通知
- **`model: "opus"`**：指定使用 Opus 4.6 (1M context) 模型（研究/分析/程式必用）
- **`subagent_type`**：`general-purpose`（預設，可寫檔）、`Explore`（唯讀，快速搜尋）、`Plan`（規劃）
- **`resume: "agentId"`**：用之前的 agent ID 恢復已完成 agent 的 context 繼續工作
- 多個獨立 Agent 可在同一訊息中**並行啟動**，大幅提升效率

| 任務類型 | Agent 設定 | 說明 |
|----------|-----------|------|
| 研究實驗 | `isolation="worktree"`, `model="opus"` | 跑 GARCH、統計測試，不影響主目錄 |
| 並行實驗 | 多個 `isolation="worktree"`, `model="opus"` 同時發送 | 同時跑多資產/多模型 |
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
3 * * * *            release-pool-by-settings  # 文章池定時釋出：每 1 小時 1 篇（不受 session 影響）
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

## 研究方法論與模型

**所有模型清單、策略績效數字、參數估計結果、評估指標定義 → 見 `research_program.md`**

CLAUDE.md 不放具體的 Sharpe/MDD 數字或模型參數值——這些會隨數據更新而過時。
研究約束（統計門檻、OOS 規範、Harvey threshold）見 `research_program.md` 約束區。

## 研究成果
**所有研究發現、實驗結果、Phase 進度、AI 協作建議 → 見 `research_program.md`（北極星文件）。**

CLAUDE.md 不重複研究內容。需要查閱研究結論時直接讀 `research_program.md`。
知識細節在 `storage/memory/knowledge.json`（1000+ 筆，含完整實驗條件和數據）。

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
- [x] W1.1: robots.txt + sitemap.xml + favicon + manifest.json
- [x] W1.2: OG tags（全站預設 + 文章動態 generateMetadata）
- [x] W1.3: JSON-LD 結構化資料（Article, WebSite）
- [ ] W1.4: Google Search Console 註冊 + 提交 sitemap（需手動）

### 高優先（產品化 + 留存）
- [ ] W2.1: 首頁 Hero Section（價值主張 + CTA）
- [ ] W2.2: 首頁預設「一般讀者」tab + 精選文章置頂
- [ ] W2.3: 清理重複的每日建議（同日只留最新）
- [ ] W3.2: 文章分享按鈕（LINE / FB / Twitter）
- [ ] W5.1: 加入 Plausible/Umami Analytics

### 中優先（信任 + 體驗）
- [x] W4.1: 「關於」頁面（研究背景、團隊）
- [ ] W3.1: Email/LINE 訂閱系統
- [ ] W3.3: 新手指南頁面（`/guide`）
- [x] W4.3: 免責聲明頁面
- [ ] W5.3: 亮色模式修復 + 手機導覽優化

## Error Log

**詳細記錄見 `docs/error_log.md`。** 每次根本修正後更新該檔案（問題、現象、過程、解決方法）。

**⚠️ 遇到任何 error 無法立即修好時，第一步永遠是先查 `docs/error_log.md`——同樣的問題可能已經解決過。不要重複踩坑。**
