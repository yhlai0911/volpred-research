# Error Log

每次根本修正後更新此檔案。格式：日期 / 問題 / 現象 / 過程 / 解決方法。

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
| 2026-03-24 | Zeabur deploy 缺 .env.production | Build failed: Missing .env.production | frontend-v2-fix/.gitignore 排除了 .env.production，Zeabur deploy 遵循 .gitignore 所以不上傳 | deploy-zeabur-safe.sh 加入 sed 刪除 stage dir .gitignore 中的 .env.production 行 |
| 2026-03-24 | 風險預報數據停在 3/20 | QQQ/EEM 的 last_date 是 3/20 而非 3/23 | `risk_forecast.py` 呼叫 `dm.get_model_data()` 沒加 `force_refresh=True`，DataManager cache 回傳舊數據。daily_update.py 06:03 執行時 yfinance 可能尚未更新某些 ETF，但 cache 會持續回傳過時數據 | 根本修正：(1) `risk_forecast.py` 加 `force_refresh=True` (2) `daily_update.py` 所有 `get_model_data()` 呼叫加 `force_refresh=True`。教訓：**每日更新腳本必須強制刷新數據，不可依賴 cache** |
| 2026-03-24 | 388 篇文章 content 欄位為空 | 前端 Markdown 渲染 fallback 到 description，但 content 空欄位影響 SEO 和搜尋 | `publish-milestone` 把文章內容存在 `description` 而非 `content`，feed.json 的 content 為空 | 修正：批次將 description 複製到 content。根因待修：`publish-milestone` 應同時寫入 content 和 description |
| 2026-03-24 | 重複釋出文章（K203 黃金 2 篇、每日更新 4 篇） | feed 有相同 title 的多篇文章 | `publish_milestone()` 沒有去重機制，每次呼叫都生成新 UUID 直接 append。多個 agent 同時產生同標題文章 | 根本修正：`publisher.py` 加入 24 小時 title 去重檢查，相同 title 在 24h 內只允許發布一次，重複呼叫回傳既有 ID。清理已有重複（刪 3 篇） |
| 2026-03-24 | Portfolio 交易紀錄沒有實際報酬 | 前端 portfolio 頁面 trades=0，所有 portfolio_return=None | `daily_update.py:599` 只同步最後一筆 entry（今天的，return=None），歷史 entry 從未同步。`paper_trades` 不在 CONFLICT_KEYS 裡導致重複 INSERT（7941 筆 vs 預期 7932） | 根本修正：(1) `supabase_sync.py` 加 `paper_trades` 到 CONFLICT_KEYS (2) `daily_update.py` 改為同步最近 30 天 entries（含回補）(3) 全量 PUT 到 `/api/sync/paper_trading.json` 清理歷史數據。教訓：**增量 sync 必須覆蓋「有更新的歷史條目」，不能只同步最新一筆** |
| 2026-03-25 | 4 篇已發佈文章含過時/錯誤宣稱 | K320 content audit 發現 TSMOM claim, 91% trend following, withdrawal rate 矛盾 | 自我修正（K255/K53/K87）後沒有回溯更新已發佈文章 | 根本修正：(1) 修正 4 篇文章並加 ⚠️ 更正聲明 (2) CLAUDE.md 第 9 條研究誠實原則：「自我修正後必須回溯更新已發佈內容」(3) 同步 Supabase。教訓：**自我修正不只是記錄新結論，還要回頭修正舊內容** |
| 2026-03-25 | 所有文章 category=milestone, audience=null | 前端 badge 全顯示 milestone，一般讀者 tab 靠 tags fallback | `publish_milestone()` 硬編碼 category='milestone'，沒有 audience 參數 | 根本修正：(1) `publisher.py` 加 `audience`/`category` 參數（明確傳入優先，fallback 從 tags 推斷）(2) `content.py` ops 層也加參數 (3) 批次修正 518 篇文章 (4) content 欄位同時寫入。教訓：**文章類型應在寫作前決定，不是事後推斷** |
| 2026-03-25 | 誤報「8 小時沒發文」但實際文章正常釋出 | 檢查用 datetime.now()（本地 UTC+8）和 UTC 的 published_at 比較，差 8 小時是時區差 | CLAUDE.md 第 144 行已寫「published_at 存 UTC」但手動檢查時沒遵守 | 根本修正：CLAUDE.md 加強提醒「比較時間必須用 UTC：datetime.now(timezone.utc)」。教訓：**已寫的規則也要遵守** |

---

## Paper Trading 頁面 AbortError + 重複資料（2026-03-28）

**問題**：
1. admin/paper-trading 頁面顯示「AbortError: The user aborted a request」
2. 新策略上架後 paper_trades 產生大量重複資料（同策略同日期多筆）
3. Fear DCA 顯示 SPY 15000%（weight 格式錯誤）

**現象**：
- 前端 `fetchAPI` timeout 只有 5 秒，API 回應需要 3.8 秒+網路延遲
- paper_trades 表無 unique constraint，每次 sync 都 INSERT 新行→重複累積
- Fear DCA weight 存為 `{"SPY": 150}` 被前端解讀為 15000%

**根因分析**：
- **timeout**: `frontend-v2-fix/src/lib/api.ts` L11: `AbortSignal.timeout(5000)` 對 portfolio API 太短
- **重複**: `supabase_sync.py` 的 `sync_paper_trade()` 是純 INSERT，CONFLICT_KEYS 有 `paper_trades: "strategy,trade_date"` 但 DB 實際上沒有這個 unique constraint → 每次 POST 帶 `on_conflict` 都 400 error → 改為不帶 on_conflict 的 INSERT → 更多重複
- **格式**: daily_update.py Fear DCA 用 `dca_display = round(dca_multiplier * 100)` 輸出 150，前端再 ×100

**解決方案**（5 層修正）：

| 層 | 修正 | 檔案 |
|---|---|---|
| A. DB constraint | 加 `UNIQUE(strategy, trade_date)` + index | `018_paper_trades_unique.sql` |
| B. Sync 邏輯 | DELETE+INSERT 確保冪等 | `supabase_sync.py` sync_paper_trade() |
| C. CONFLICT_KEYS | 恢復 `paper_trades: "strategy,trade_date"` | `supabase_sync.py` |
| D. 前端 timeout | 5s → 15s | `api.ts` L11 |
| E. Weight 格式 | `{"SPY": 150}` → `{"SPY": 1.50}` | `daily_update.py` Fear DCA |

**待執行**：
- 在 Supabase Dashboard SQL Editor 執行 migration 018（去重+加 constraint+加 index）
- 重新部署前端（timeout 修正）

**教訓**：
1. 上架新策略時必須驗證 Supabase 所有相關表的數據正確性（用 `list_new_strategy.py --verify-only`）
2. DB 表如果有 (A, B) 需要唯一的情境，一開始就要加 unique constraint，不能靠應用層 dedup
3. Weight 格式要統一：portfolio weight 用小數（0~1.0），前端 ×100 顯示百分比
4. API timeout 要設定合理值，考慮最壞情況（多策略 × 3 年 × pagination）

---

## 策略上架品質問題總覽（2026-03-28）

**問題清單**（5 個新策略上架時一次性爆發）：

| # | 問題 | 根因 | 解法 | 狀態 |
|---|------|------|------|------|
| 1 | SPY 15000% | weight 格式 150 vs 1.50 | daily_update.py 改用小數 | ✅ |
| 2 | +undefined% | metrics 缺 best_day | 補完所有 13 策略 | ✅ |
| 3 | 只有 32 天數據 | 回填不足 | 統一 3 年回填 | ✅ |
| 4 | date vs trade_date | 欄位名不一致 | K588 全面統一 | ✅ |
| 5 | paper_trades 重複 | 無 unique constraint | DELETE+INSERT + migration 018 | ✅(程式) ⏳(DB) |
| 6 | AbortError timeout | fetch 5s 太短 | 改為 15s | ✅ |
| 7 | strategy_metrics_cache 缺新策略 | 沒有自動寫入流程 | list_new_strategy.py 自動化 | ✅ |
| 8 | portfolio 看不到新策略 | metrics_cache 空 + paper_trades 不足 | 回填 + cache upsert | ✅ |
| 9 | 台股篩選不到 | TW_TAGS case-sensitive | 加 'taiwan' + normalizeTag | ✅ |
| 10 | 策略無連結文章 | articles 欄位空 | 手動連結 | ✅ |
| 11 | 市場數據冗餘 | 每策略重複 spy_close 等 | _market_daily 正規化 | ✅(local) ⏳(DB) |

**⏳ 需要 Supabase Dashboard 操作**：
- Migration 018: unique constraint + index
- Migration 019: market_daily 表

**策略上架完整 SOP（更新版）**：
1. STRATEGY_REGISTRY + 計算邏輯
2. `list_new_strategy.py --key xxx --name xxx --order N`
3. 3 年歷史回填（backfill_new_strategies.py 或新腳本）
4. recalc_metrics.py
5. strategy_metrics_cache upsert（含 best_day/worst_day/sparkline）
6. paper_trades 全量上傳到 Supabase（非只 30 天）
7. strategy_signals 填入 description + howto + articles
8. articles 欄位連結對應的 feed 文章
9. `list_new_strategy.py --key xxx --verify-only` 驗證所有表
10. 部署前端
11. 手動確認 portfolio 頁面顯示正確

### 策略上架 SOP v2（2026-03-28 更新，加入專文步驟）

**完整 12 步（缺一不可）**：

1. STRATEGY_REGISTRY + 計算邏輯（daily_update.py）
2. `list_new_strategy.py` 或 `ops strategy-upsert`
3. 3 年歷史回填（backfill script）
4. recalc_metrics.py
5. strategy_metrics_cache upsert（含 sparkline + best_day/worst_day）
6. paper_trades 全量上傳到 Supabase
7. strategy_signals 填入 description + howto
8. **寫策略專文（至少 1 篇研究 + 1 篇一般讀者）**
9. articles 欄位連結對應文章
10. `list_new_strategy.py --verify-only` 驗證
11. 部署前端
12. 手動確認 portfolio 頁面顯示正確

**第 8 步：策略專文要求**：
- 研究文章：完整驗證數據（Harvey t-stat、cross-OOS、sensitivity、bootstrap）
- 一般讀者文章：白話解說策略邏輯、適用對象、操作方式、風險提醒
- 兩篇都要有真實 matplotlib 圖表
- 發佈為 draft 進入文章池

### 策略面板 Badge 問題（2026-03-28）

**問題**：策略面板的適用標的和交易頻率 badge 是前端 hardcode（`stratMeta` 物件），不是 DB-driven。
- 新增策略要改前端代碼 → 違反「不需重新部署就能管理策略」原則
- 50/50 SPY/GLD 被標錯為「月頻」（實際日頻）

**正確做法**：
1. `strategy_signals` 表加入 `assets` (jsonb) 和 `rebalance_freq` (text) 欄位
2. 前端從 API 讀取，不 hardcode
3. 策略上架 SOP 第 7 步加入：填寫 assets + rebalance_freq

**暫時解法**：前端 hardcode `stratMeta`（已修正 50/50 頻率）
**永久解法**：DB migration 加欄位 + 前端改讀 API

**加入 SOP**：
- 第 7 步更新為：填寫 description + howto + **assets + rebalance_freq** + articles

---

## 台股交易成本計算錯誤（2026-03-28）

**問題**：K604 實驗和多篇文章中使用的台股交易成本有 2 個嚴重錯誤。

**錯誤 1：ETF 證交稅率**
- 我們用的：0.3%（一般股票稅率）
- 實際：**0.1%**（ETF 優惠稅率，2024 年起）
- 高估 3 倍

**錯誤 2：手續費計算方式**
- 我們用的：固定 $20/trade
- 實際：**成交金額 × 0.1425% × 折扣（多數券商 2.8-6 折）**
- 實際成本範例：100 萬交易 × 0.1425% × 3 折 = 427 元（買+賣各一次 = 854 元）

**正確的台股交易成本**：
- 買入：手續費 = 成交金額 × 0.1425% × 折扣
- 賣出：手續費 + 證交稅 = 成交金額 × (0.1425% × 折扣 + 0.1%)
- 單次來回總成本（3 折手續費）≈ 0.1425% × 0.3 × 2 + 0.1% ≈ **0.185%**

**影響**：
- K604 的「台灣策略 13x 更貴」結論需要修正
- 實際台灣 ETF 來回成本 ~18.5bp vs 美股 ~2bp = 約 9x（不是 13x）
- 台股最低資金門檻可能低於我們估計的 $80 萬

**修正行動**：
- 更新 K604 實驗的成本假設
- 更新受影響文章
- 更新策略說明中的「建議帳戶 80 萬以上」
