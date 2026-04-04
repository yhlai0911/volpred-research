# 自主波動率預測研究系統
原則上使用繁體中文互動

## 研究誠實原則（最高優先，不可違反）

**一切結果必須真實、嚴謹、可驗證。違反任何一條即視為研究失敗。**

1. **不可造假、不可虛構**：所有數據、統計量、圖表必須來自實際計算，不可編造數字或偽造結果
2. **數據來源透明**：每個實驗必須標明數據來源（yfinance、FRED、CBOE 等）、資料期間、樣本數量。不可用模擬數據冒充實證數據
3. **實驗必須有對應檔案 + 知識庫記錄 + 經驗記錄**：每個實驗完成後，**必須同時產出三項**：
   - **檔案**：`experiments/<experiment_id>.py`（腳本）+ `experiments/<experiment_id>_results.json`（結果）。Agent worktree 完成後複製到主分支
   - **知識庫**（`storage/memory/knowledge.json`）：含 experiment_id、title、content 摘要（200-300字）、tags、data_source。記錄**發現了什麼**（結論、數據、統計量）
   - **經驗庫**（`storage/memory/experiment_experiences.json`，Exxx 編號）：記錄**學到了什麼**（為什麼成功/失敗、踩了什麼坑、下次該怎麼做）。每 5-10 個實驗彙整一條經驗記錄
   - 不可只存 results JSON 而不進知識庫——2026-03 曾發現 85/124 實驗只有 results 但不在知識庫中
   - **Knowledge = 發現（what），Experience = 教訓（why + how to avoid）**
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
6b. **模型比較必須公平（Patton 2011 標準）**：不同類型的波動率模型（GARCH 預測 σ²、MEM/HAR 預測 |r| 或 RV）必須在公平框架下比較，**不可只用單一 target**。每次模型比較實驗必須包含：
   - **各模型在原生 target 上的表現**（GARCH on r²、MEM on |r|、HAR on RV）——展示各自最佳表現
   - **QLIKE on r²**（Patton 2011 proxy-robust：r² 是 σ² 的無偏估計，排名一致性有理論保證）
   - **Spearman rank correlation**（分配無關，不需轉換假設）
   - **DM test + Harvey t>3.0**（每對模型）
   - 如有日內數據：**QLIKE on 5-min RV**（Hansen & Lunde 2005 gold standard）
   - 如有多模型：**MCS（Model Confidence Set）**（控制多重比較）
   - **不可只報告對自己有利的 target**——必須報告所有 target 的結果，包括模型表現差的
   - **經濟顯著性（VaR/ES）評估**：每個模型預測不同東西，轉換到 VaR 時**必須做適當處理**：
     - GARCH（σ²）→ VaR = σ × z_α（z_α 取決於創新分配：Normal/Student-t/Skewed-t）
     - MEM(|r|) → 先轉 σ = E[|r|] / C（C 來自 MEM 的 Gamma 分配，非 Normal 的 √(2/π)），再 VaR = σ × z_α
     - HAR-RV → σ = √RV，VaR 需考慮 HAR 殘差分配（通常 log-normal 或 F）
     - **不可直接把模型預測值當 VaR**——必須經過正確的分配轉換
     - VaR backtesting: Kupiec + Christoffersen + Basel traffic light
     - 如有日內數據：Hansen & Lunde (2005) 最優加權 RV_total 作為真實 σ² 的最佳估計
7. **區分實證與理論**：明確標示每項分析屬於「實證分析（真實數據）」、「理論推導」或「模擬實驗」。不可混淆
8. **Null result 如實報告**：負面結果同樣重要，必須完整記錄。不可只報告成功、隱藏失敗
9. **發佈內容真實不虛**：Feed 文章、研究摘要、知識記錄的每一項數據和結論都必須可追溯到具體實驗腳本和數據
10. **承認局限**：每個發現都必須說明其局限性（樣本大小、OOS 期間、資產範圍、proxy 變數的假設）
11. **不可過度宣稱**：結論的強度不可超過證據支持的範圍。partial r=0.08 不可宣稱為「突破性發現」
12. **Lookahead Bias 檢查（最常見錯誤）**：所有策略回測必須確認信號 lag：
   - **Signal from t-1, return at t**：weight 基於昨天的 VIX，今天的 return
   - **禁止 same-day**：weight 基於今天 VIX × 今天 return = 未來資訊（lookahead）
   - 歷史教訓：K679 VIX Percentile Sharpe 1.68→修正 lag 後 0.355（100% artifact）
   - **不修改歷史數據**：K693 嘗試修改 9935 筆歷史 portfolio_return 導致更多問題（metrics 不同步、Supabase 不一致）→ 已 revert。正確做法是讓 forward tracking 自然修正
   - **Codex 審查已 4 次抓到 lookahead**（K618, K621, K679, K698）——同 session 犯 4 次相同錯誤
   - **實驗代碼寫完後、執行前，必須先讓 Codex 審查代碼**。不是跑完出結果才審。流程：寫代碼 → Codex 審 → 修正 → 才跑 → 記錄 → 才發文
   - **代碼中必須有明確的 `signal.shift(1)`**——lag 驗證靠代碼結構，不靠事後記憶
   - **Sharpe > 2x baseline = 幾乎一定有 bug**——先停下來檢查，不要先歡呼
12. **自我修正後回溯更新**：每次推翻或修正先前結論時，必須立即：
   - 搜尋已發佈文章中引用該結論的內容（用 grep 搜尋關鍵詞）
   - 在受影響文章頂部加入 `⚠️ 更正聲明（日期）`，說明修正內容
   - 更新 feed.json 和個別 report JSON 的 content/description
   - 同步到 Supabase（`supabase_sync.py full`）
   - 記錄到 `docs/error_log.md`（自我修正類）

## 專案簡介
Claude Code 驅動的自主研究系統，用於尋找給定資產的最佳波動率預測模型，並建立一般投資人可用的交易策略。

## 網站架構（v4 Supabase + Admin CMS + Mirror API）
→ 完整細節見 `docs/architecture.md`

- **前端（線上版）**：`frontend-v2-fix/`（Next.js 15 + React 19 + Supabase，部署於 volpred-v3 服務）
- **Mirror API**：`mirror-api.zeabur.app`（研究記憶檔案鏡像，減少 Supabase egress）
- **資料庫**：Supabase（PostgreSQL + Auth + REST API + RPC）
- **線上網址**：https://volpred.zeabur.app
- **Zeabur Dashboard**：https://zeabur.com/projects/69b5b264800a475a1f82b073

### 前端頁面列表
| 路徑 | 說明 |
|------|------|
| `/` | 首頁 Feed（SSR + `FeedBrowser` 無限滾動） |
| `/about` | 關於頁面（研究背景、團隊） |
| `/admin/*` | Admin CMS（10 面板：analytics/content/ops/strategies/questions/users/papers/paper-trading/health/schedules） |
| `/disclaimer` | 免責聲明 |
| `/me` | 用戶專區（書籤、提問、活動摘要） |
| `/paper` | 論文頁（讀 Supabase `papers` table） |
| `/portfolio` | 投資組合總覽（`PaperTradingStrategyChart` + `PaperTradingTradeLog`） |
| `/questions` | 會員問答 |
| `/risk-forecast` | 風險預測儀表板 |
| `/strategy-selector` | 策略選擇器 |
| `/vix-calculator` | VIX 計算器 |
| `/vt-calculator` | VT 計算器 |

### 資料流核心規則
- `storage/` → 本地唯一源頭（JSON）
- `scripts/supabase_sync.py` → Supabase 同步（由 daily_update.py 呼叫）
  - **文章同步**：只讀取 `storage/reports/feed.json`（唯一源頭，`storage/feed.json` 已廢除）
  - **Paper trades 同步**：自動剝離市場數據，只存策略 weights + returns
  - **Draft 同步**：用 `published_at OR created_at` 過濾
- `scripts/daily_update.py` → 每日 22:03 UTC（台灣 06:03）美股收盤後計算策略權重 + 同步 Supabase + 重算績效指標。每日只產出一篇「每日策略建議」（含市場快照+持倉表+VIX分析），不再分兩篇
- **Paper Trading 資料結構**：
  - `paper_trading.json` 是唯一源頭，不可手動修改歷史數據
  - `daily_update.py` 正確使用 next-day return（K692 驗證），forward tracking 自動修正
  - `recalc_metrics.py` 每次執行自動 sync 到 Supabase `strategy_metrics_cache`
  - 市場數據統一存在 `_market_daily`（key=日期），不在每個 entry 重複
- **新策略評估**：必須用 `scripts/evaluate_new_strategy.py` 在 COMMON_START（2023-01-04）~ 今天同期間比較
- **Mirror 資料流**：`MemorySystem._sync_to_remote()` → 雙寫 Supabase + Mirror API

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

### 策略管理（DB 驅動，無需重新部署）
- 策略 metadata 唯一來源：`daily_update.py` 頂部的 `STRATEGY_REGISTRY`
- Registry 驅動：Feed 文章（只列 active）、Supabase 同步、Paper trading
- **新增策略**：(1) 加入 STRATEGY_REGISTRY (2) 加計算邏輯到 strat_list (3) `add_strategy.py` 寫 DB
- **下架策略**：改 `is_active=False`（面板隱藏、文章不列、paper trading 繼續記錄）

### Agent-first Ops Layer
- **CLI 首選入口**：`uv run volpred ops ...`
- 已統一操作：publish-milestone / release-pool-by-settings / sync-all / daily-update / recalc-metrics / strategy-upsert / strategy-set-active / question-ranking-summary / question-rerank / question-answer / health / cleanup-post / unpublish / send-article-notification / send-daily-digest
- **Job Queue**（`src/volpred/ops/jobs.py`）：Supabase-backed，lifecycle: `queued` → `running` → `succeeded|failed`

### 程式碼架構
- **Python CLI (volpred)**：研究引擎（實驗、評估、記憶、發佈）
- **storage/**：唯一資料源頭（JSON），跨 session 保存
- **frontend-v2-fix/**：Next.js 15 前端（線上版，volpred-v3 服務）
- **scripts/supabase_sync.py**：資料同步到 Supabase
- **src/volpred/ops/jobs.py**：Supabase-backed job queue（agent + human 共用）
- **research_program.md**：研究策略文件（北極星）
- **paper/**：學術論文（按子目錄組織）

### 重要研究結論

**VT 策略是 drawdown insurance，不是 alpha generator（K687/K697/K700）。**
- K697：VIX 預測 vol magnitude（corr 0.57）但不預測 direction（corr 0.04）——daily alpha 不可能
- K687：正確 lag 後，沒有 VT 策略在 Sharpe 上打敗 BH 50/50（0.545）
- K688：但 VT 在 CRRA utility 框架 gamma>=5 時勝出（風險厭惡投資人受益）
- K702：50/50 SPY/GLD 是最佳靜態配置（grid search 確認）
- K700：Codex 審查防止 3 個 false breakthrough（37.5% false positive rate without review）
- **Smooth-weight 策略（12/VIX, Risk Parity）幾乎不受 lag 影響——這是最可靠的設計原則**
- K846：50/50 的三重護城河（分散化 r=0.057 + 再平衡溢酬 54bps/yr + 黃金危機 alpha）

**★★★ Proxy Ceiling Paradigm Shift（2026-04-03~04 K847-K849）**
- **K849：HAR-RV 壓倒 GJR（DM t=-11.14）**——之前 800+ 實驗說 GJR 不可動搖是 proxy ceiling 不是 model ceiling。r² 只捕捉 29% true vol（K848）
- **K847：隔夜 gap 61% 可交易**——用 TAIFEX 夜盤期貨可捕捉。Slot C（美股時段）佔 39.8%
- **K848：夜盤 vol 佔比 24%→57%**（2017→2026）——台灣市場正在全球化
- **K844：TX 期貨 VT 空頭期全勝**——交易成本省 97%，機構投資人應用期貨執行
- **台灣 vol 模型評估必須用 5-min RV 做 target，不能用 r²**

### 注意事項
- Feed 發文要用 `feed-publisher` skill（thinking ≠ content）
- **Zeabur reverse proxy 陷阱**：詳見 `docs/zeabur-oauth-gotcha.md`
- Paper trading 用 `portfolio_return`（加權後組合報酬），不是單一資產 return
- 時間處理：`published_at` 存 UTC，前端用 `timeZone: 'Asia/Taipei'` 顯示。詳見 `.claude/skills/autonomous-research/references/data-timing.md`
  - **⚠️ 比較時間必須用 UTC**：`datetime.now(timezone.utc)` 不是 `datetime.now()`。後者是本地台灣時間（UTC+8），會差 8 小時
  - 檢查「多久沒發文」的正確寫法：`(datetime.now(timezone.utc) - datetime.fromisoformat(pub_at).replace(tzinfo=timezone.utc))`
- 跨市場策略注意 VIX lag（台股用前一天 VIX）
- **外部數據來源**：→ 完整操作手冊見 `.claude/skills/external-data-sources/SKILL.md`
  - **yfinance**：股價/ETF/VIX（免費，無需 key）
  - **FRED**：`pandas_datareader` 讀取數千個總經指標（免費，無需 key）
  - **TAIFEX tick**：台指期日內 tick（`~/Dropbox/TAIFEXDATA/TAIFEXDATA/python/`，✅ 本地 33G；選擇權 41G ❌ 僅雲端）
  - **CBOE**：VIX/VVIX/VIX3M/SKEW（透過 yfinance）
  - **DGBAS 主計總處**：台灣 GDP/CPI/就業（需 Chrome 自動化，見 `taiwan-macro-data` skill）
  - **Congressional trades**：`data/congressional_trades_house.csv`
- **⚠️ 0050.TW 數據品質**：Yahoo Finance 1:4 分割只回溯到 2014，2013 前未調整。**所有 0050.TW 實驗必須 `from volpred.utils import clean_tw50_data`**
- **5-min 數據回補**：`collect_5min_data.py` 自動偵測 gap 回補（上限 59 天）
- **TAIFEX 格式陷阱**：2012 是 9 欄/2014 起 10 欄、時間格式 2017 夜盤前後不同、2011 特殊編碼。**必須用 header 判斷，不可硬編碼 index**。詳見 skill
- **Paper trading 多日回補**：daily_update.py 自動回填所有 `portfolio_return=None` 的歷史條目（利用相鄰條目價差）
- **frontend-v2-fix 已部署**：`volpred.zeabur.app` 綁定到 volpred-v3 服務（frontend-v2-fix），前端修改只需改 `frontend-v2-fix/`

### 每日文章產出要求（不可缺少任何一種）

每天必須產出以下三種類型的文章，面向不同讀者群：

| 類型 | 目標讀者 | 每日數量 | 內容要求 | tags 必含 |
|------|---------|---------|---------|----------|
| **一般讀者** (general) | 非專業投資人 | 4 篇 | 800-1200 字、爆款標題、具體場景、一個核心 takeaway、CTA。基於研究數據但用類比解釋 | `一般讀者` |
| **研究發現** (research) | 有金融背景的讀者 | 2-4 篇 | 實驗結果報告，含統計數據、表格、方法論。每個重要實驗（★+）都應有對應文章 | `研究` |
| **每日建議** (daily) | 所有讀者 | 1 篇 | 當日策略權重、VIX regime、持倉建議。由 `daily_update.py` 自動產生 | `每日建議` |

**執行規則**：
- **非時效性文章**一律 `status=draft` 進文章池，由每小時 cron 按節奏釋出
- **⚠️ 事件驅動文章（NFP/FOMC/CPI/TSMC 營收等）必須立即 `status=published`** + Supabase sync。延遲 = 過期（2026-04-03 教訓：NFP 文章延遲 10 小時釋出）
- **每篇文章必須附真正的圖表（不可用 ASCII/文字表格替代）**：
  - 使用共用模組 `from volpred.charts import generate_bar_chart, upload_chart, embed_chart`
  - 可用函式：`generate_bar_chart`、`generate_grouped_bar_chart`、`generate_line_chart`、`generate_heatmap`
  - 流程：`path = generate_bar_chart(...) → url = upload_chart(path) → content = embed_chart(content, url, '描述')`
  - 一般讀者至少 1 張真實圖表，研究文章 2-3 張
  - **禁止用 ASCII art、文字方框、或純 Markdown 表格冒充圖表**——這些不是圖表
- **每篇文章必須標注數據來源和實驗檔案**：
  - 研究文章：文末必須列出 `實驗腳本: experiments/kXXX.py` 和 `結果數據: experiments/kXXX_results.json`
  - 一般讀者文章：文末用 `*本文基於實驗 KXXX 的實證結果（數據來源：yfinance，期間：YYYY-YYYY）*` 格式標注
  - 不標注來源的文章等同「無法追溯」，違反研究誠實原則第 9 條
- 一般讀者文章的主題**不可重疊**——每篇必須有獨立的核心 insight
- **⚠️ 主題重複檢查必須在「決定主題後、啟動寫作 agent 前」完成（不是發佈時才檢查）：**
  1. **LanceDB 語義搜尋**（主要）：`uv run python scripts/build_knowledge_index.py search --query "主題描述"` — 看前 5 筆是否有高度相似的已發佈文章
  2. **grep 輔助**：`grep -i '關鍵詞' storage/reports/feed.json | grep title | head -10`
  3. 若找到同 audience 相似文章 → **不啟動 agent**，除非有明確的新觀點
  4. 若有部分重疊 → 在 agent prompt 中明確指出「已有 XXX 文章講過 Y，這次要從 Z 角度切入」
  5. 高頻重複主題（50/50 配置 10+篇、VT 保險 5+篇、隔夜波動 3+篇）→ **原則上不再寫，除非有新實驗數據**
  6. 浪費資源寫完才發現重複 = 流程失敗（2026-04-01 教訓：K791 隔夜波動文章與 K772 重複）
- **research_program.md 每月初存檔瘦身**：將已完成 Phase/Session 記錄移至 `docs/research_archive/completed_phases_YYYY-MM.md`，只保留活躍內容（目標 < 500 行）。查詢追蹤表指向存檔位置。**存檔前必須先確認所有實驗都已進入 knowledge.json + experiment_experiences.json**——不可以存檔未記錄的內容（2026-03 教訓：先存檔才發現 85 個實驗不在知識庫）
- **重要事件前後必須安排研究與文章**：每月初用 WebSearch 查詢未來一個月的重要政治/經濟/金融事件（FOMC、CPI、NFP、GDP、央行決議、大型法說會），事前 2-3 天發佈預告文章，事後 1 天發佈解讀文章。具體事件日曆記在 `research_program.md`，**每次查詢新月份時覆蓋更新（不累積），只保留當月和下月**
- 研究文章在實驗完成後**立刻撰寫**，不要累積
- **每 5 個實驗後必須補充文章池**——檢查池中草稿數量，若 <3 篇則立刻寫 2 篇（1 general + 1 research）
- 每個 session 開始時檢查今日各類型文章產出是否達標
- **池子不可空超過 3 小時**——若空池超過 3 小時等於網站停止更新

## 論文
→ 論文列表、版本命名、PDF slug 詳見 `docs/paper-guide.md`

### 論文更新標準程序（每次修訂都要完整執行，不可跳步）

**審查 → 修正 → 版本化 → 平台同步，一氣呵成。**

```
1. 審查：/latex-academic-reviewer + /citation-verifier → review_v1.tex + citation_check.md
2. 修正：body_v2.tex（保留原版）+ v1_to_v2_diff.tex（差異報告）
3. 編譯：cd paper/<name> && xelatex main_v2.tex && xelatex main_v2.tex
4. **一鍵同步**：uv run volpred ops paper-update --paper-id <id>
   （自動：計算 pages + citations → 上傳 PDF → 更新 metadata → 複製到前端）
5. Git commit：含 review + diff + v2 所有檔案
6. 驗證：curl API 確認 pages/citations/pdf_url 正確
```

**⚠️ 步驟 4 的 `paper-update` 自動完成原本的步驟 4-6，不需要手動跑 3 個命令。**
**⚠️ 修正完不更新平台 = 沒修。步驟 4-6 不可省略。**

### 目前 STRATEGY_REGISTRY（14 筆，10 個 active）
→ 完整上架流程見 `docs/strategy-registry.md`

| key | display_name | is_active | order |
|-----|-------------|-----------|-------|
| `slow_vt` | GARCH VT (SPY) | True | 0 |
| `risk_parity` | Risk Parity (SPY+GLD) | True | 1 |
| `simple_12vix` | 12/VIX (SPY) | True | 2 |
| `recommended_5050` | 50/50 SPY/GLD | True | 3 |
| `taiwan_8.63vix` | 台灣 VT (0050.TW) | True | 4 |
| `taiwan_spy_momentum` | 台股動量 (0050.TW) | False | 5 |
| `tz_tw_jp_5050` | TW+JP 50/50 TZ | False | 6 |
| `global_vt_tz` | Global US VT + TW TZ | False | 7 |
| `vix_leading_guard` | VIX+景氣領先 (0050.TW) | True | 8 |
| `vix_cond_leverage` | VIX 條件槓桿（月頻） | True | 9 |
| `taiwan_hybrid_leverage` | 台股混合槓桿 | True | 10 |
| `piecewise_conservative` | 保守型 VT（Piecewise） | True | 11 |
| `fear_dca` | 恐慌加碼定期定額 | True | 12 |
| `adaptive_tier` | 自適應三階 VT | True | 13 |

### 上架必須通過的 5 項檢驗（ALL PASS 才可上架）

| # | 檢驗 | 通過標準 | 工具 |
|---|------|---------|------|
| 1 | **同期間比較** | `evaluate_new_strategy.py` Sharpe **>= 已上架策略中位數** | `uv run python scripts/evaluate_new_strategy.py` |
| 2 | **Cross-OOS** | 5 個非重疊 2 年期間，勝 BH 50/50 **>= 3/5** | 回測腳本（可用 2006-2026） |
| 3 | **Codex 審查** | 無 HIGH severity bug（lag/lookahead/TX） | `/codex:rescue` 或 `codex exec -s read-only` |
| 4 | **Sensitivity** | 參數 +-20% 變動後 Sharpe 不降 > 30% | 回測腳本 |
| 5 | **MDD 可接受** | 同期間 MDD **< -20%** | `evaluate_new_strategy.py` 輸出 |

### 新策略上線標準程序

## 快速指令
→ 完整指令見 `docs/quick-commands.md`

```bash
# 研究
uv run volpred summary                              # 研究摘要
uv run volpred analyze-data --asset SPY              # 資料特性
uv run volpred run-experiment --asset SPY --model gjr_arch --window 2000
uv run python scripts/build_knowledge_index.py auto  # 知識索引（增量，偵測變化才重建，省 API）

# 每日運營
uv run python scripts/daily_update.py                # 每日更新（策略計算 + 績效重算 + Supabase 同步）
uv run python scripts/recalc_metrics.py              # 手動重算績效指標
uv run python scripts/supabase_sync.py full          # 手動 incremental sync
uv run python scripts/supabase_sync.py force-full    # 強制全量同步（慎用，IO 大）
uv run volpred ops health                            # 本地營運健康檢查
uv run volpred ops article-backups --repair          # 確保每篇已發布文章都有本地單篇 JSON
uv run volpred ops sync-all                          # 統一入口：手動 Supabase sync
uv run volpred ops daily-update                      # 統一入口：每日更新
uv run volpred ops recalc-metrics                    # 統一入口：重算績效指標
uv run volpred ops paper-list                        # 查看論文與 Storage 狀態
uv run volpred ops paper-upsert --paper-id xxx --title "..." --authors "..."
uv run volpred ops paper-upload-pdf --paper-id xxx --file paper/<name>/main.pdf

# 策略管理（只寫 DB，不需部署）
uv run python scripts/list_new_strategy.py --list-all                          # 查看所有策略上線狀態
uv run python scripts/list_new_strategy.py --key xxx --verify-only             # 驗證單一策略
uv run python scripts/list_new_strategy.py --key xxx --name "名稱" --howto "說明" --description "完整說明" --assets '{"SPY":50}' --order N  # 一鍵上架
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
npx zeabur@latest service redeploy --id <service_id> -i=false -y             # 重新部署
cd frontend-v2-fix && ./scripts/deploy-zeabur-safe.sh  # 安全部署前端

# 發佈
uv run volpred ops publish-milestone --title "標題" --description "Markdown 內容" --phase "Phase_X"
uv run volpred ops release-pool-by-settings --storage-dir storage
uv run volpred ops send-article-notification mile_xxxxxxxx
uv run volpred ops send-daily-digest --target-date 2026-03-21
uv run volpred ops edit-article mile_xxxxxxxx --title "新標題" --content "新內容" --audience research
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

**⚠️ 反空轉原則（2026-03-31 教訓）：**
- **「方向窮盡」是假象** — research_program.md 永遠有 100+ 未完成項目。不要靠腦中判斷「沒事做」，要讀文件。
- **每次 cron 觸發必須做事** — 讀 research_program.md 選一個待辦，啟動 agent 或自己做。禁止只回「系統穩定」。
- **實驗衍生方向必須寫回** — 每個實驗完成後，提取 2-3 個新方向寫入 research_program.md。不寫 = 知識流失。
- **完成項目必須 archive** — 移到 `docs/research_archive/`，保持 research_program.md < 700 行。

### 實驗前必做：防錯 + 查詢知識庫 + 搜尋文獻（不可跳過，違反即無效）
**每個實驗/新主題路線開始前，必須完成以下步驟，缺一不可：**

**Step 0: Error Log 防錯檢查（最重要，必須在 agent prompt 中包含）**
0. **讀 `docs/error_log.md` 的常見錯誤**，在 agent prompt 中明確列出適用的防錯規則：
   - **DM test**：必須用 `from volpred.stats.model_evaluation import strategy_dm_test`，不自己寫
   - **0050.TW**：必須呼叫 `from volpred.utils import clean_tw50_data`
   - **跨市場**：必須用 open-to-close return（不是 close-to-close）
   - **GARCH OOS**：必須逐日遞迴 h[t]=f(h[t-1],r²[t-1])，不能用 stale variance
   - **Bayesian prior**：必須允許否證（不能用 HalfNormal 然後說 P(>0)=1.0）
   - **Sanity check**：必須實際計算（shift(0) lookahead vs shift(1)），絕不 hard-code
   - **分配 fit**：Student-t 必須考慮 scale term sqrt((df-2)/df)
   - **Basel/統計檢定**：用標準實作，不自定義閾值
   - **Sharpe > 2x baseline**：幾乎一定有 bug，先停下來檢查
1. 在 agent prompt 中**明確寫出**：「此實驗需注意的 error log 規則：XXX」

**Step 1: 知識庫搜尋（過去成果）**
1. `grep -i '關鍵詞' storage/memory/knowledge.json | grep title | head -10`
2. 確認：是否已有相關成果？過去結論是什麼？有無自我修正？
3. 在 agent prompt 中**引用相關 K 編號**，讓 agent 建立在已有基礎上
4. 避免重複實驗、避免被已推翻的結論誤導

**Step 2: 學術文獻搜尋（方法論與概念）**
5. 用 WebSearch 搜尋該主題的學術文獻（至少 3 篇）
6. 分析方法論：前人用什麼方法？為什麼？有什麼已知結論？
7. 用 sci-hub skill 取得全文（如果需要細節）
8. 基於文獻分析決定實驗設計，不自行猜測

**Step 3: 概念驗證（先想清楚再動手）**
9. 問自己：「這個實驗跟過去哪個 K 最像？那個 K 的結論是什麼？」
10. 如果知識庫已有非常相似的實驗 → 不重複，除非有明確的差異化理由
11. 如果文獻說某方法在某條件下不 work → 不盲目嘗試

**反面教材**：K503（VIX mean-reversion）如果先查知識庫就會發現 12/VIX 本身就是 MR trade；K504（STLFSI4）如果先查會發現 VIX 已被確認 31 次 sufficient。這些 null results 本可避免。

**Step 4: 跨市場驗證（美股無效 ≠ 其他市場無效）**
12. 在美股測完的方法，如果有潛力也要在**台股（0050.TW）**測試——特別是使用外生變數的方法（K461 SSVS 在台股選出 SPY PIP=1.000，美股選空模型）
13. 台股特性：高波動（amplification 4.6x）、US lead-lag、不同 gamma、外部驅動

**Step 5: 效率檢查（超時 ≠ 方法無效）**
14. Agent 超時（exit 144）時，先檢查**代碼效率**（向量化、refit 頻率、numba），不要直接下「方法無效」結論（K419→K426 教訓：1.5s vs timeout）
15. 設計實驗時預估運行時間，控制在合理範圍（< 3-5 分鐘）

**Step 6: 錯誤處理與 AI 協作規則**
16. 程式跑不出結果或產生錯誤時，**必須用 `/codex:review` 或 `/codex:rescue` 檢查並修正**——不要自己猜、不要反覆重試同一個錯
17. Gemini API 額度用完時，**轉由 Codex 協助**（`/codex:rescue` 委派任務）
18. 為避免 Gemini API 額度快速用完：知識索引用 `auto`（增量）不用 `build`（全量），每 session 論文修訂任務**不可過於集中**（分散在不同時段執行）

### 實驗完整流程（強制，不可跳步）

```
寫代碼 → Codex 審代碼 → 修正 → 跑實驗 → 驗證結果 → 記錄 knowledge → 才寫文章
```

**實驗中必做（寫代碼時）：**
1. 策略回測代碼必須有 `signal = signal.shift(1)` 或等效 lag——**在代碼裡強制，不靠記憶**
2. TX cost 必須在每次 weight 變化時扣除
3. Baseline 用相同的 lag convention（如果新策略 lag=1，baseline 也要 lag=1）
4. `evaluate_new_strategy.py` 已內建正確 lag——優先使用

**實驗後必做（跑完後、記錄前）：**
1. **Codex 審查代碼**（不是審結果——審代碼本身有沒有 bug）
   - `/codex-cli -s read-only "Review experiments/kXXX.py for lag, TX, baseline bugs"`
2. **結果合理性檢查**：Sharpe > 2x baseline → 90% 有 bug，先停下來
3. **Codex 通過後才記錄** knowledge
4. **Knowledge 記錄後才寫文章**
5. **文章存 draft**，由 cron 釋出——不直接 publish

**2026-03-29 教訓**：93 個實驗中 8 個被推翻（10%），全部因為跳過「Codex 先審代碼」這一步。如果每個實驗都先審再跑，推翻率應該趨近 0%。

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

## AI 協作模式（Claude + Codex + Gemini）
→ 完整協作場景見 `docs/ai-collaboration.md`

| AI | 角色 | 使用方式 | 擅長 |
|---|---|---|---|
| **Claude**（主研究員）| 實驗執行、分析、記憶管理、論文寫作 | 直接執行 | 深度分析、code、持續研究 |
| **Codex (GPT)**| 針對性審查、第二意見、新方向 | `/codex:rescue`、`/codex:review`、`codex exec` | 找漏洞、結構性問題、editorial advice |
| **Gemini** | 方法論建議、文獻連結、robustness 建議 | `/gemini-cli` | 學術框架、cross-reference、新測試建議 |

### Codex Plugin 可用命令（openai/codex-plugin-cc v1.0.1）
| 命令 | 用途 |
|------|------|
| `/codex:rescue` | 委派特定任務（審查、診斷、修正建議） |
| `/codex:review` | Git diff 代碼審查（需指定 scope） |
| `/codex:adversarial-review` | 對抗性審查（挑戰設計決策） |
| `/codex:status` | 查看背景任務進度 |
| `/codex:result` | 取得背景任務結果 |
| `/codex:cancel` | 取消背景任務 |
| `/codex:setup` | 檢查 Codex 就緒狀態 |

**使用原則**：針對特定目標，不掃全專案。不要用 `--scope working-tree`。不要無目標地「讓 Codex 看看」。

### 研究主題來源（必須多元）
1. **Codex/Gemini 建議**：每 5-10 個實驗主動問一次
2. **用戶指定**：優先執行，必須立刻寫入 research_program.md
3. **會員問題**：每 6 小時 cron 自動評估
4. **文獻搜索**：WebSearch arXiv/SSRN 前沿方向
5. **Claude 自選**：基於 research_program.md 待探索方向
6. **跨 AI 交叉驗證**：一個 AI 提出假說 → 另一個 AI 設計實驗 → Claude 執行

## 硬體資源與 Agent Team
→ 完整 Agent 設定對照表見 `docs/hardware.md`

| 項目 | 規格 |
|------|------|
| CPU | Apple M1 Max · 10 核心 |
| RAM | 64 GB |
| 平行 agent 建議 | 3-4 個 worktree agent 同時跑（每個 ~1GB RAM） |
| GARCH 估計速度 | ~6ms/model（單核） |
| Bootstrap 10,000 reps | ~2-5 秒 |

### 模型選擇原則（必須遵守）

| 任務類型 | 模型 | 原因 |
|---------|------|------|
| **研究實驗**（GARCH、統計檢定、策略回測） | `model: "opus"` | 精確性與專業性要求高 |
| **程式開發**（前端、後端、bug 修復） | `model: "opus"` | 程式碼正確性關鍵 |
| **統計分析**（DM test、bootstrap、cross-OOS） | `model: "opus"` | 數學嚴謹性不可妥協 |
| **論文寫作/審查** | `model: "opus"` | 學術品質要求 |
| **知識合成**（meta-analysis、投資指南） | `model: "opus"` | 需要深度推理 |
| 簡單搜尋（grep、檔案查找） | `subagent_type: "Explore"` | 快速唯讀 |
| 簡單文章撰寫（feed 文章） | `model: "sonnet"` 可接受 | 創意寫作彈性較大 |
| 規劃與架構 | `subagent_type: "Plan"` | 結構化思考 |

**規則：研究、分析、程式等精確性與專業性工作，務必使用 opus 模型。不確定時預設 opus。**
**優先使用 agent team 並行分派任務**，同時推進 3-4 個方向以最大化效率。

## 自動化排程
### 永久任務（系統 crontab — 無人值守也會跑）
```
0 15 * * 1-5   collect_tw_data.py      # 台股收盤後 15:00
30 5 * * 2-6   collect_us_data.py      # 美股收盤後 05:30
3 22 * * 1-5   daily_update.py         # 美股收盤後 22:03 UTC（台灣 06:03），用當日收盤數據
3 * * * *      release-pool-by-settings # 文章池定時釋出：每 1 小時 1 篇
```

### Session Cron（每次新 session 重建，需 Claude 活躍）

#### 雲端觸發（RemoteTrigger，無需 session 活躍）
```
platform-ops-patrol: 0 */6 * * *  # 平台巡檢（已遷移至雲端 trigger trig_01HzWX2ZUmsGHnzwciGpHeNz）
```

#### 最小啟動集
```
CronCreate(cron="13 */6 * * *", prompt="會員問題研究")
CronCreate(cron="47 */2 * * *", prompt="每2小時 git commit")
CronCreate(cron="7 * * * *", prompt="知識索引更新")
```

#### 全速模式（確認穩定後加入）
```
CronCreate(cron="5,20,35,50 8-23 * * *", prompt="繼續研究：(1) 讀 research_program.md 的未完成項目 (2) 從中選一個啟動 (3) 絕對不可只 check status 就結束——必須有 agent 在跑或有實際產出")
CronCreate(cron="5 0-7 * * *", prompt="繼續研究（夜間）：讀 research_program.md 未完成項目，啟動 1 個低強度任務。不可空轉。")
```

#### 反空轉規則（2026-03-31 教訓）
**每次「繼續研究」cron 觸發後，必須滿足以下至少一項才算完成：**
1. 有新 agent 在背景跑（實驗、文章、論文修訂）
2. 有實際的 git diff（不是只改 session_state.json）
3. 有新的知識庫/經驗庫記錄
4. 有新的 research_program.md 內容更新

**禁止連續兩次 cron 觸發都只回覆 status check。** 如果上一次沒做事，這一次必須補上。

#### 實驗完成後的必做流程（不可跳步）
```
實驗完成 → Codex 審查 → 記錄 knowledge → 記錄 experience（如適用）
         → 衍生新方向寫入 research_program.md
         → 已完成項目從 research_program.md 移到 archive
         → research_program.md 保持 < 700 行
```

## 研究方法論與模型

**所有模型清單、策略績效數字、參數估計結果、評估指標定義 → 見 `research_program.md`**

CLAUDE.md 不放具體的 Sharpe/MDD 數字或模型參數值——這些會隨數據更新而過時。
研究約束（統計門檻、OOS 規範、Harvey threshold）見 `research_program.md` 約束區。

## 研究成果
**所有研究發現、實驗結果、Phase 進度、AI 協作建議 → 見 `research_program.md`（北極星文件）。**

CLAUDE.md 不重複研究內容。需要查閱研究結論時直接讀 `research_program.md`。
知識細節在 `storage/memory/knowledge.json`（1000+ 筆，含完整實驗條件和數據）。

## 網站優化待辦
→ 詳見 `docs/website-optimization-plan.md` + `docs/execution_backlog_2026-03-20.md`

## Error Log

**詳細記錄見 `docs/error_log.md`。** 每次根本修正後更新該檔案（問題、現象、過程、解決方法）。

**⚠️ 遇到任何 error 無法立即修好時，第一步永遠是先查 `docs/error_log.md`——同樣的問題可能已經解決過。不要重複踩坑。**
