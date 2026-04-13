# 網站架構（v4 Supabase + Admin CMS + Mirror API）

完整細節見 `docs/architecture.md`

- **前端（線上版）**：`frontend-v2-fix/`（Next.js 15 + React 19 + Supabase，部署於 volpred-v3 服務）
- **Mirror API**：`mirror-api.zeabur.app`（研究記憶檔案鏡像，減少 Supabase egress）
- **資料庫**：Supabase（PostgreSQL + Auth + REST API + RPC）
- **線上網址**：https://volpred.zeabur.app
- **Zeabur Dashboard**：https://zeabur.com/projects/69b5b264800a475a1f82b073

## 前端頁面列表
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

## 資料流核心規則
- `storage/` → 本地唯一源頭（JSON）
- `scripts/supabase_sync.py` → Supabase 同步（由 daily_update.py 呼叫）
  - **文章同步**：只讀取 `storage/reports/feed.json`（唯一源頭，`storage/feed.json` 已廢除）
  - **Paper trades 同步**：自動剝離市場數據，只存策略 weights + returns
  - **Draft 同步**：用 `published_at OR created_at` 過濾
- `scripts/daily_update.py` → 每日 00:03 UTC（台灣 08:03）美股收盤後計算策略權重 + 同步 Supabase + 重算績效指標。每日只產出一篇「每日策略建議」（含市場快照+持倉表+VIX分析），不再分兩篇
- **Paper Trading 資料結構**：
  - `paper_trading.json` 是唯一源頭，不可手動修改歷史數據
  - `daily_update.py` 正確使用 next-day return（K692 驗證），forward tracking 自動修正
  - `recalc_metrics.py` 每次執行自動 sync 到 Supabase `strategy_metrics_cache`
  - 市場數據統一存在 `_market_daily`（key=日期），不在每個 entry 重複
- **新策略評估**：必須用 `scripts/evaluate_new_strategy.py` 在 COMMON_START（2023-01-04）~ 今天同期間比較
- **Mirror 資料流**：`MemorySystem._sync_to_remote()` → PUT 到 Mirror API（`/api/mirror/memory/{filename}`）

## Supabase 資料庫表
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

## 策略管理（DB 驅動，無需重新部署）
- 策略 metadata 唯一來源：`daily_update.py` 頂部的 `STRATEGY_REGISTRY`
- Registry 驅動：Feed 文章（只列 active）、Supabase 同步、Paper trading
- **新增策略**：(1) 加入 STRATEGY_REGISTRY (2) 加計算邏輯到 strat_list (3) `add_strategy.py` 寫 DB
- **下架策略**：改 `is_active=False`（面板隱藏、文章不列、paper trading 繼續記錄）

## Agent-first Ops Layer
- **CLI 首選入口**：`uv run volpred ops ...`
- 已統一操作：publish-milestone / release-pool-by-settings / sync-all / daily-update / recalc-metrics / strategy-upsert / strategy-set-active / question-ranking-summary / question-rerank / question-answer / health / cleanup-post / unpublish / send-article-notification / send-daily-digest
- **Job Queue**（`src/volpred/ops/jobs.py`）：Supabase-backed，lifecycle: `queued` → `running` → `succeeded|failed`

## 程式碼架構
- **Python CLI (volpred)**：研究引擎（實驗、評估、記憶、發佈）
- **storage/**：唯一資料源頭（JSON），跨 session 保存
- **frontend-v2-fix/**：Next.js 15 前端（線上版，volpred-v3 服務）
- **scripts/supabase_sync.py**：資料同步到 Supabase
- **src/volpred/ops/jobs.py**：Supabase-backed job queue（agent + human 共用）
- **research_program.md**：研究策略文件（北極星）
- **paper/**：學術論文（按子目錄組織）

## 注意事項
- Feed 發文要用 `feed-publisher` skill（thinking ≠ content）
- **Zeabur reverse proxy 陷阱**：詳見 `docs/zeabur-oauth-gotcha.md`
- Paper trading 用 `portfolio_return`（加權後組合報酬），不是單一資產 return
- 跨市場策略注意 VIX lag（台股用前一天 VIX）
- **外部數據來源**：→ 完整操作手冊見 `.claude/skills/external-data-sources/SKILL.md`
- **⚠️ 0050.TW 數據品質**：Yahoo Finance 1:4 分割只回溯到 2014，2013 前未調整。**所有 0050.TW 實驗必須 `from volpred.utils import clean_tw50_data`**
- **TAIFEX 期貨轉倉（必須處理）**：不要直接用 TX1，要用 TX 全合約，每日按成交量選最活躍的合約月份
- **frontend-v2-fix 已部署**：`volpred.zeabur.app` 綁定到 volpred-v3 服務

## 每日文章產出要求

| 類型 | 目標讀者 | 每日數量 | 內容要求 | tags 必含 |
|------|---------|---------|---------|----------|
| **一般讀者** (general) | 非專業投資人 | 4 篇 | 800-1200 字、爆款標題、具體場景、一個核心 takeaway、CTA | `一般讀者` |
| **研究發現** (research) | 有金融背景的讀者 | 2-4 篇 | 實驗結果報告，含統計數據、表格、方法論 | `研究` |
| **每日建議** (daily) | 所有讀者 | 1 篇 | 當日策略權重、VIX regime、持倉建議。由 `daily_update.py` 自動產生 | `每日建議` |

**執行規則**：
- 非時效性文章一律 `status=draft` 進文章池，由每 2 小時 cron 按節奏釋出
- **事件驅動文章（NFP/FOMC/CPI/TSMC 營收等）必須立即 `status=published`** + Supabase sync
- 每篇文章必須附真正的圖表：`from volpred.charts import generate_bar_chart, upload_chart, embed_chart`
- 每篇文章必須標注數據來源和實驗檔案
- 主題重複檢查必須在「決定主題後、啟動寫作 agent 前」完成（LanceDB 語義搜尋 + grep）
- research_program.md 每月初存檔瘦身（目標 < 500 行）

## 目前 STRATEGY_REGISTRY（14 筆，10 個 active）
完整上架流程見 `docs/strategy-registry.md`

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

## 上架必須通過的 5 項檢驗

| # | 檢驗 | 通過標準 | 工具 |
|---|------|---------|------|
| 1 | **同期間比較** | Sharpe >= 已上架策略中位數 | `evaluate_new_strategy.py` |
| 2 | **Cross-OOS** | 5 個非重疊 2 年期間，勝 BH 50/50 >= 3/5 | 回測腳本 |
| 3 | **Codex 審查** | 無 HIGH severity bug | `/codex:rescue` |
| 4 | **Sensitivity** | 參數 +-20% Sharpe 不降 > 30% | 回測腳本 |
| 5 | **MDD 可接受** | 同期間 MDD < -20% | `evaluate_new_strategy.py` |

## Zeabur 服務 ID
- Project: 69b5b264800a475a1f82b073
- Environment: 69b5b2646853f6f4f5f6a16d
- volpred-web: 69b5b279e0a0c18cef9d780d
- volpred-v2: 69b8ed895a53b5901a3c8d25
- volpred-v3: 69be521a1066986b9a1692be
- volpred-mirror: 69c105e1ceee47754dacb2af
