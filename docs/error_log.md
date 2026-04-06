# Error Log

每次根本修正後更新此檔案。格式：日期 / 問題 / 現象 / 過程 / 解決方法。

| 日期 | 問題 | 現象 | 過程 | 解決方法 |
|------|------|------|------|---------|
| 2026-04-06 | **Worktree 腳本遺失（3次）** | K923/K924/K932 的 .py 腳本在 worktree 清理時永久遺失 | Agent 在 worktree 寫檔案但沒 commit → `git worktree remove --force` 刪除一切 | (1) 建立 `scripts/merge_worktree.sh` 安全合併腳本 (2) 禁止 `--force` remove (3) Agent prompt 必須包含 commit 指令 (4) 更新 SKILL.md + CLAUDE.md |
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
| 2026-04-01 | DM test 自行實作（E40）| K795/K807/K808 各自寫 DM test，非標準 HAC | 已有 `model_evaluation.py` 但 agent 不用 | 建 `strategy_dm_test()` 標準函式。K809+ 開始使用。教訓：統計檢定必須用標準模組 |
| 2026-04-01 | Agent fabricated sanity check | K812 hard-code `lookahead_sharpe=1.938` 假裝計算結果 | Codex 發現代碼中無 shift(0) backtest，數字是造假 | K812v2 實際計算所有 sanity checks。教訓：**Codex 審查必須在記錄 knowledge 之前** |
| 2026-04-01 | GJR state propagation bug | K813/K816 OOS 間 variance 未逐日遞迴 | refit 後用 stale conditional_volatility，不是 h[t]=f(h[t-1],r²[t-1]) | K816v2 修正：逐日遞迴 GJR state。修正後 DM 從 2.96→0.64。教訓：GARCH OOS 必須逐日傳播 state |
| 2026-04-01 | Bayesian prior tautology | K814 P(γ>0)=1.0000 因 HalfNormal prior 強制 γ>0 | Prior support = [0,∞)，後驗不可能有 γ<0 | 正確做法：用 Normal prior 允許 γ<0，看後驗 mass。教訓：先驗必須允許否證 |
| 2026-04-01 | Student-t df 估計缺 scale term | K824 t_dist.logpdf 沒除 sqrt((df-2)/df) | unit-variance 殘差 fit 到 Student-t 不 rescale → df 偏向薄尾 → violations 被高估 | K824v2 修正中。教訓：分配 fit 必須考慮 scale parameter |
| 2026-04-01 | 非標準 Basel traffic light | K824 用自定義閾值，Student-t 通過 Kupiec 但被標 fail | 自行實作的 Basel 規則與標準不同 | 用標準 Basel 250 天回溯（Green<5, Yellow 5-9, Red≥10）。教訓：與 DM 同理——用標準不自己寫 |
| 2026-04-01 | question_articles 連結反覆被覆蓋 | 手動修正 3 次都被 revert | 前端 syncQuestionArticleLinks 讀 details.question_id 重建連結 | 根因：舊文章有 details.question_id，新文章沒有。修正：answer_internal_question 自動寫 details.question_id。5 層保護 |
| 2026-04-01 | 孤兒 Supabase 草稿 | 後台 18 篇 draft 永遠發不出 | 存在 Supabase 但不在本地 feed.json，release_pool 只讀本地 | sync_full 自動清理孤兒 draft（設為 unpublished）。教訓：每次 sync 清理不一致的狀態 |
| 2026-04-02 | Safari 分享按鈕失靈 | Facebook 分享跳轉後未啟動 | `window.open()` 被 Safari iOS 攔截為 popup | 改用 `<a target="_blank">` 標籤。教訓：手機瀏覽器避免 window.open |
| 2026-04-02 | 每日文章重複 | 一天出 2-3 篇每日分析 | daily_update.py 產出「持倉建議」+「策略建議」兩篇 | 合併為一篇。cron 改到 UTC 22:03（美股收盤後）。教訓：同源數據只產出一篇 |
| 2026-03-21 | 手動改 status 導致前端看不到文章 | 前端只看到 2 篇（本地有 10 篇） | 手動改 `feed.json` 的 `status=published` 不觸發 Supabase sync。`release-pool-by-settings` 內建 sync 但被繞過 | 根本修正：(1) feed-publisher skill 規定所有文章一律 `status=draft` (2) 只透過 `release-pool-by-settings` 釋出（內建 sync）(3) 禁止手動改 JSON status。教訓：**修改資料的唯一合法途徑是透過 ops 層 CLI/API，不是直接改檔案** |
| 2026-03-24 | Zeabur deploy 缺 .env.production | Build failed: Missing .env.production | frontend-v2-fix/.gitignore 排除了 .env.production，Zeabur deploy 遵循 .gitignore 所以不上傳 | deploy-zeabur-safe.sh 加入 sed 刪除 stage dir .gitignore 中的 .env.production 行 |
| 2026-03-24 | 風險預報數據停在 3/20 | QQQ/EEM 的 last_date 是 3/20 而非 3/23 | `risk_forecast.py` 呼叫 `dm.get_model_data()` 沒加 `force_refresh=True`，DataManager cache 回傳舊數據。daily_update.py 06:03 執行時 yfinance 可能尚未更新某些 ETF，但 cache 會持續回傳過時數據 | 根本修正：(1) `risk_forecast.py` 加 `force_refresh=True` (2) `daily_update.py` 所有 `get_model_data()` 呼叫加 `force_refresh=True`。教訓：**每日更新腳本必須強制刷新數據，不可依賴 cache** |
| 2026-03-24 | 388 篇文章 content 欄位為空 | 前端 Markdown 渲染 fallback 到 description，但 content 空欄位影響 SEO 和搜尋 | `publish-milestone` 把文章內容存在 `description` 而非 `content`，feed.json 的 content 為空 | 修正：批次將 description 複製到 content。根因待修：`publish-milestone` 應同時寫入 content 和 description |
| 2026-03-24 | 重複釋出文章（K203 黃金 2 篇、每日更新 4 篇） | feed 有相同 title 的多篇文章 | `publish_milestone()` 沒有去重機制，每次呼叫都生成新 UUID 直接 append。多個 agent 同時產生同標題文章 | 根本修正：`publisher.py` 加入 24 小時 title 去重檢查，相同 title 在 24h 內只允許發布一次，重複呼叫回傳既有 ID。清理已有重複（刪 3 篇） |
| 2026-03-24 | Portfolio 交易紀錄沒有實際報酬 | 前端 portfolio 頁面 trades=0，所有 portfolio_return=None | `daily_update.py:599` 只同步最後一筆 entry（今天的，return=None），歷史 entry 從未同步。`paper_trades` 不在 CONFLICT_KEYS 裡導致重複 INSERT（7941 筆 vs 預期 7932） | 根本修正：(1) `supabase_sync.py` 加 `paper_trades` 到 CONFLICT_KEYS (2) `daily_update.py` 改為同步最近 30 天 entries（含回補）(3) 全量 PUT 到 `/api/sync/paper_trading.json` 清理歷史數據。教訓：**增量 sync 必須覆蓋「有更新的歷史條目」，不能只同步最新一筆** |
| 2026-03-25 | 4 篇已發佈文章含過時/錯誤宣稱 | K320 content audit 發現 TSMOM claim, 91% trend following, withdrawal rate 矛盾 | 自我修正（K255/K53/K87）後沒有回溯更新已發佈文章 | 根本修正：(1) 修正 4 篇文章並加 ⚠️ 更正聲明 (2) CLAUDE.md 第 9 條研究誠實原則：「自我修正後必須回溯更新已發佈內容」(3) 同步 Supabase。教訓：**自我修正不只是記錄新結論，還要回頭修正舊內容** |
| 2026-03-25 | 所有文章 category=milestone, audience=null | 前端 badge 全顯示 milestone，一般讀者 tab 靠 tags fallback | `publish_milestone()` 硬編碼 category='milestone'，沒有 audience 參數 | 根本修正：(1) `publisher.py` 加 `audience`/`category` 參數（明確傳入優先，fallback 從 tags 推斷）(2) `content.py` ops 層也加參數 (3) 批次修正 518 篇文章 (4) content 欄位同時寫入。教訓：**文章類型應在寫作前決定，不是事後推斷** |
| 2026-03-25 | 誤報「8 小時沒發文」但實際文章正常釋出 | 檢查用 datetime.now()（本地 UTC+8）和 UTC 的 published_at 比較，差 8 小時是時區差 | CLAUDE.md 第 144 行已寫「published_at 存 UTC」但手動檢查時沒遵守 | 根本修正：CLAUDE.md 加強提醒「比較時間必須用 UTC：datetime.now(timezone.utc)」。教訓：**已寫的規則也要遵守** |

| 2026-04-05 | Tags 雙重編碼（JSON array 被 comma-split） | tags 顯示 `["研究"` 而非 `研究` | `cli.py:_parse_tags` 只做 `raw.split(",")` 不處理 JSON array 輸入 `'["研究","VIX"]'`，加上 publisher 沒有防護直接寫入 | 三層修復：(1) `_parse_tags` 偵測 JSON array 格式先 `json.loads` (2) `publisher.py` 加 `_sanitize_tags` 防護（strip brackets/quotes） (3) `_sync_all_article_tags` 也加 sanitize。教訓：**輸入解析和輸出寫入都要做 sanitization，不能假設上游是乾淨的** |
| 2026-04-05 | article_tags 大量丟失（80%） | 前端 tag 篩選失效，文章詳情頁不顯示 tags | `_sync_article_tags` 和 `_get_tag_ids` 用 `isinstance(tag_id, str)` 檢查 tag ID 型別，但 Supabase tags 表的 ID 是 integer（serial），不是 UUID string → tag ID 查詢永遠返回空 map → article_tags 永遠不寫入。另外 tags 逐筆 POST（每個 tag 一次 HTTP）容易靜默失敗，且 tag sync 耦合在 article sync 內（文章 upsert 失敗就不同步 tags） | 根本修正三層：(1) `_get_tag_ids` 和 `_sync_all_article_tags` 改為 `tag_id is not None` 取代 `isinstance(tag_id, str)` (2) 新增 `_sync_all_article_tags` 批量函式（chunk 50 筆一次 POST）取代逐筆 POST (3) 將 tag sync 從 `sync_article` 解耦，改在 `sync_full` 中獨立執行（不依賴文章 upsert 結果）。教訓：**型別假設必須匹配實際 DB schema（int vs uuid）；同步步驟不可耦合（A 失敗不應阻止 B）；批量操作取代逐筆（50x 減少 HTTP 往返）** |
| 2026-04-06 | LaTeX 方程式渲染壞掉（`au_t imes g_t`） | 前端 KaTeX 應渲染 `\tau_t \times g_t` 但顯示 `au_t imes g_t` | `publisher.py` L204: `description.replace('\\t', '\t')` 把 JSON 中的 `\tau` → TAB+au。修復過程中產生連鎖問題：(1) 錯誤地把 LaTeX 轉 Unicode (2) 產生 `$$$$` 空 math block (3) Unicode minus `−` 進入 URLs (4) inline math 沒包 `$...$` | 根本修正五層：(1) `publisher.py` 移除 `\\t`→TAB (2) 還原 95 篇 Unicode→LaTeX (3) 清除 19 篇 `$$$$` 空 math block (4) 修復 16 篇 URL Unicode minus (5) 包裝 174 篇 bare inline LaTeX 進 `$...$`。教訓：**批量字串替換極度危險——每次改動都可能產生新問題。應該先在測試文章驗證，確認無誤再批量執行。不可連續做多輪 regex 替換而不驗證中間結果** |

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

**修正行動（已完成 2026-03-27）**：
- [x] 建立 K625 更正實驗（`experiments/k625_tx_cost_correction.py`），使用正確成本參數重新計算
- [x] 修正 12 個 Python 實驗檔案中的台股成本常數：
  - k502, k506, k515, k516, k517, k499, k238, k263, taiwan_paper_fixes, tsmc_concentration_test
- [x] 在 25 篇已發佈文章頂部加入「⚠️ 更正聲明（2026-03-27）」
- [x] 更新 research_program.md 中的成本引用
- [x] 更新 storage/experiments/taiwan_vt_guide.json 中的稅率
- [x] 標注 write_k604_k597_k598_articles.py 和 publish_98_experiments_guide.py 為過時

**K625 更正後結果**：
- 台灣 VT (0050.TW)：Sharpe 減少僅 4.7%（K604 因錯誤成本高估了衰減）
- 台灣 Hybrid Leverage：淨 Sharpe **2.310**（升為全策略第一）
- 最低資金門檻：從 $977K/$823K 降至 **$5,000**（0050.TW 零股）
- 台股策略平均營運成本：0.88%/年（仍高於美股 0.34%/年，但差距從 13x 縮小至 ~2.6x）

## 2026-03-29: 文章發佈管線故障（7 小時斷檔 + 空白內容）

### 問題
1. 新文章 7 小時沒發佈
2. 2 篇文章以空白 content 發佈到線上

### 現象
- System crontab `release-pool-by-settings` 每小時正常執行，但 "Released 0 articles"
- Supabase 的 draft 數量為 0（新文章沒進入 Supabase）
- 已發佈的 `mile_1458be07` content 為空

### 根因
1. **雙 feed.json 問題**：Agent worktree 寫文章到 `storage/feed.json`，但 `supabase_sync.py` 只讀 `storage/reports/feed.json`
2. **Draft 不被 sync**：Incremental sync 用 `published_at` 過濾，draft 沒有 `published_at` → 永遠被跳過
3. **Report 個別檔案無 content**：Agent worktree 產生的 report JSON 只有 metadata 沒有 content body

### 修正
1. `supabase_sync.py`：改為同時讀取 `storage/feed.json` + `storage/reports/feed.json`（雙源合併）
2. `supabase_sync.py`：Filter 改用 `published_at OR created_at`（支持 draft sync）
3. `scripts/merge_feed_files.py`：新增自動合併腳本（作為保險）
4. `feed-publisher SKILL.md`：明確要求寫到 `storage/reports/feed.json` + report 個別檔案必須有 content + 寫完後執行 sync
5. 手動修復 28 篇 Supabase 文章 content + 2 篇重寫 content

### 預防
- feed-publisher skill 已更新發文 checklist
- `supabase_sync.py` 雙源讀取永久化
- 未來 agent 寫文章 prompt 必須指定 `storage/reports/feed.json`

## 2026-03-29: K693 不應修改歷史數據

### 問題
K693 修改了 paper_trading.json 中 9,935 筆歷史 portfolio_return（same-day → next-day），導致：
1. Supabase strategy_metrics_cache 與本地不同步
2. 需要手動 PATCH Supabase（違反自動化原則）
3. 評估期間前後不一致（舊 810 筆 vs 新 809 筆）
4. 網站上策略績效數字突然大幅變化（Piecewise 3.16→1.56）

### 根因
- 認為歷史數據「有 bug」就應該修正——但正確做法是**不修改歷史數據**
- daily_update.py 的 forward tracking 本身是正確的（K692 驗證）
- 歷史數據的 lookahead 會隨新的正確條目累積自然稀釋

### 解決
1. Revert paper_trading.json 到 K693 前的 backup
2. `recalc_metrics.py` 加入自動 sync 到 Supabase（底層修正）
3. 建立 `evaluate_new_strategy.py`（新策略在同期間公平比較）
4. CLAUDE.md 加入「不修改歷史數據」原則

### 教訓
- **不修改歷史數據**。Forward tracking 讓 metrics 自然收斂。
- **新舊策略比較必須同期間**。不是修正舊數據，是在同一個框架下重新模擬。
- **Metrics 必須是數據的衍生品**，不可手動 PATCH。recalc_metrics.py 是唯一寫入路徑。
- **修流程不修資料**——改 recalc_metrics 的 sync 邏輯，不是手動改 Supabase。

---

## 2026-03-31: Session Cron 空轉 6-8 小時

### 問題
「繼續研究」cron 每 15 分鐘觸發，但 Claude 只 check status 回「系統穩定」，連續空轉 6-8 小時。

### 現象
- 23 個實驗完成後，連續 ~30 次 cron 觸發都只檢查草稿數
- 沒有啟動任何實驗、文章、或其他工作
- research_program.md 有 160+ 未完成項目但完全沒讀
- 實驗衍生的 18 個新方向沒寫回 research_program.md
- 已完成項目沒做 archive（877 行 vs 目標 500 行）

### 根因
1. Claude 自己判斷「方向窮盡」而不看文件 — 實際有 160+ 待辦
2. cron prompt 太弱：「繼續研究」沒有強制讀 research_program.md
3. 沒有「反空轉」機制：允許連續多次只回 status check
4. 實驗完成流程缺少「寫回新方向」和「archive 舊方向」步驟

### 解決方法
1. **CLAUDE.md 更新**：加入反空轉規則（禁止連續兩次空轉）+ 實驗完成必做流程
2. **Cron prompt 加強**：明確要求「讀 research_program.md → 選一個 → 啟動」
3. **Feedback memory**：feedback_never_idle_loop.md
4. **Error log**：本條記錄

### 教訓
- **「沒事做」是不存在的** — research_program.md 是北極星，永遠有未完成項目
- **Cron prompt 要具體到操作步驟**，不能只是「繼續研究」這種模糊指令
- **流程完整性**：實驗 → 記錄 → 衍生方向 → archive → 下一個。少一步就會斷鏈
| 2026-04-04 | Badge 不一致（Feed vs 文章頁） | Feed 顯示「一般讀者」但文章內頁顯示「milestone」或「general」 | 三層問題：(1) supabase_sync category 預設 "milestone" (2) 前端 Feed 用 tags、文章頁用 category 兩個不同 data source (3) force-full sync 用舊代碼沒修正既有資料 | (1) sync 改為 classify_audience() (2) 前端統一用 resolveBadge(tags, audience) 函式 (3) force-full sync 重跑 |
| 2026-04-04 | Paper pages=None | 新論文頁數不顯示 | papers.py 用 subprocess 呼叫 python3 import fitz，但 pymupdf 只在系統 Python 有，不在 .venv。except:pass 靜默吞錯。之前靠碰巧系統 PATH 先找到系統 python3 才成功。 | 把 pymupdf 加入 pyproject.toml（uv add pymupdf），確保 .venv 內也有。教訓：所有 import 的套件必須在 pyproject.toml 宣告，不能靠系統安裝。 |
| 2026-04-04 | 文章圖片 404 | K838/K840 文章圖表顯示破圖 | Agent 呼叫 upload_chart(path, "custom.png") 但第二參數是 bucket 不是 filename，導致上傳到錯誤 bucket。另外 worktree agent 的圖片路徑和主分支不同。 | 新增 remote_filename 參數到 upload_chart()。重新上傳 3 張圖。310/310 恢復。 |
| 2026-04-04 | 論文 abstract 空白 | Paper 4/5 在前端無摘要 | _count_tex_metrics 只提取 pages+citations 不提取 abstract。update_paper_full 不傳 abstract。 | 加入 LaTeX abstract 自動提取（regex）+ 傳給 upsert。7 篇論文全更新。 |

## K849 "Proxy Ceiling Paradigm Shift" 過度宣稱（2026-04-05 發現）

**問題**：K849 將 HAR-RV 在 RV target 上勝過 GJR 宣稱為「paradigm shift」和「800 個實驗用錯 target」。

**根因**：
1. GARCH 預測 close-to-close σ²，用 r² 評估是**正確的**
2. HAR-RV 預測日內 RV，用 5-min RV 評估是**正確的**
3. 不同模型在各自原生 target 上贏是**設計的必然**，不是「發現」
4. research_program.md 第 24-36 行早就寫了「不同模型預測不同 target」的公平比較標準
5. 第 749-753 行早就寫了 Hansen & Lunde (2005) 的調整方法
6. 但 K849 實驗前沒有回讀這些方法論約束，agent prompt 也沒引用

**流程失敗點**：
- 實驗前 checklist 沒有「結果是否為模型設計的必然」這一條
- agent prompt 沒引用 research_program.md 的方法論標準
- Codex adversarial review 只查代碼 bug，沒質疑框架合理性
- 結果出來後興奮過頭，沒自問「這跟我們已知的矛盾嗎？」

**修正**：
1. CLAUDE.md Step 0 加入「模型-Target 匹配」和「結果是否為設計必然」檢查
2. 修正所有 proxy ceiling paradigm shift 敘事
3. K849 真正有價值的部分：K850 prediction-VaR paradox、K852 RealGARCH、夜盤 decomposition

## TAIFEX TX1 轉倉 Roll Gap 未處理（2026-04-05 用戶指出）

**問題**：K849/K851/K852b/K868 使用 TX1（近月合約）tick 數據計算 5-min RV，但沒有處理每月第三個週三的轉倉（rollover）。

**影響**：
- 每月結算日，TX1 從到期月合約切換到下月合約
- 例：2020/01/15 TX1=202001 price=12174 → 01/16 TX1=202002 price=12067（roll gap -107 點 = -0.88%）
- 這個價差不是真實波動，但被計入 RV 計算
- 每年 12 次轉倉，每次可能 0.5-1.0% 假波動→RV 被系統性高估

**正確處理方式**：
1. **排除轉倉日**：偵測「到期月份」欄位變化的交易日，該日跨合約 return 不計入 RV
2. **用同合約銜接**：轉倉前用舊合約最後價格，轉倉後用新合約第一價格，不跨合約算 return
3. **比例調整**：ratio-adjusted continuous futures

**受影響實驗**：K849, K851, K852b, K868
**根因**：實驗前 checklist 沒有「期貨轉倉處理」這一條。preamble 也沒提及。

## K880 缺少 ES 評估（2026-04-05 用戶指出）

**問題**：K880（SPY PRG 驗證）只做了 VaR backtesting，沒做 ES（Expected Shortfall）。

**根因**：
1. CLAUDE.md 沒有明確寫 ES 是必做
2. research_program.md 第 86 行只列了名字（Acerbi-Szekely, Fissler-Ziegel）但沒標「必做」
3. experiment preamble 在 K880 發出後才加入 VaR+ES 評估表
4. Agent prompt 沒包含 ES 規則，agent 自然不做

**修正**：
1. CLAUDE.md 加入「VaR + ES 都是必做」規則
2. research_program.md ES 改為「必做 + Basel III 依據」
3. experiment preamble 已有完整 VaR+ES 表
4. K880b 補做 ES 評估

## K880 PRG Lookahead + VaR Cov 缺失 + MLE 約束不足（2026-04-05 Codex 審查）

**問題**：Codex adversarial review 發現 K880 PRG 實作有 3 個嚴重問題。

**[CRITICAL] Lookahead**：
- PRG 的 h_intraday_t 用了 r2_overnight[t]（當天隔夜 return）
- 但 GJR/HAR 沒有這個當天資訊
- PRG 的 DM t=6.00 可能是 lookahead artifact（見 K679 前例）
- 修正：h_total_t 必須只用 t-1 close 的資訊集

**[HIGH] VaR Cov 缺失**：
- σ²_fullday = Var(overnight) + Var(intraday) + 2×Cov(overnight,intraday)
- 代碼只用 Var(overnight) + Var(intraday)，假設 Cov=0
- 修正：估計 Cov 或在相同 target 上評估

**[HIGH] MLE 參數約束不足**：
- 沒有 periodic stationarity 約束
- h <= 0 時 clip 到 1e-12 而非 reject
- 修正：重參數化或加非線性約束

**受影響**：K880, K881, K874c/d/e（所有 PRG 實驗）
**狀態**：需修正後重跑，所有 PRG DM 結果暫時標記為 UNVERIFIED

## Codex 誤判 PRG Lookahead（2026-04-05 用戶糾正）

**問題**：Codex adversarial review 將 PRG 使用 r_overnight_t 預測 h_intraday_t 判定為 lookahead。

**為什麼 Codex 是錯的**：
- PRG/PRS 是 **session 頻率模型**，不是日頻模型
- 在日盤開盤（8:45）時，隔夜 session 已經結束，r_overnight_t 是已實現的資訊
- 用已完成 session 的資訊預測下一個 session 是 periodic switching 的核心設計
- 這跟「8:45 的交易者已經看到隔夜 gap」完全一致
- 參見 Lai, Wang & Chang (2024 APFM) PRS 模型的 Section 2

**根因**：
1. Codex 用日頻思維（「day-t 的所有資訊都是未來」）審查 session 頻率模型
2. 我沒有在 Codex prompt 中說明 periodic model 的 information set
3. 我讀了用戶的 PRS 論文但沒有內化其核心機制就去實作

**教訓**：
- Codex review 也可能出錯——特別是對非標準模型結構
- 要在 Codex prompt 中明確說明模型的 information set 和時間結構
- **讀論文要讀懂，不是掃過就行**
