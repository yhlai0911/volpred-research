# Error Log

每次根本修正後更新此檔案。格式：日期 / 問題 / 現象 / 過程 / 解決方法。

| 日期 | 問題 | 現象 | 過程 | 解決方法 |
|------|------|------|------|---------|
| 2026-04-18 | Paper 4 reproduce match_rate 44% → 88.9%（yfinance `auto_adjust` 預設改變導致 bundled CSV Close 混淆 adjusted 與 raw） | `paper/vt-insurance-cost/reproduce.py` 以 bundled CSV 的 `Close` 欄位重算 S0 CAGR 得 12.497% 接近 paper 12.51%，但再往下展開 claim 只 match 4/9（44%）；深挖發現 bundled `spy_2012_2024.csv` 的「Close」實際上是 yfinance 新預設 `auto_adjust=True` 的 adjusted close（2012-01-03=99.31），而 paper canonical K811v2 用 raw Close (auto_adjust=False, 2012-01-03=127.50) | yfinance 近期版本 `auto_adjust` 從 False 改為 True，舊 bundle 腳本未顯式 pin `auto_adjust=False`，CSV 的「Close」欄位靜默變成 adjusted series。雖然 CAGR 層級差異小（adjusted 把 dividend 併入），但往下到 VT 比較（VT 用 raw price 算 vol + rebalance，混 adjusted 會錯位 signal／volatility scaling），整條 downstream pipeline 的 S1/S2/S3 比較全受污染 | 修 pipeline 不修 paper（研究誠實 §13）：(1) P4 Sub1 task `task_ff205abe31f0` — 用 `yf.download(..., auto_adjust=False)` 重抓 SPY + GLD 2012-01-03..2025-01-01，CSV 同時保留 `Adj Close` 與 `Close` 兩欄 (2) `paper/vt-insurance-cost/data_sources.md` 明標「raw Close (auto_adjust=False) canonical; K811v2 anchor」(3) `reproduce.py` 原本透過 column name match 讀 "close"，升級後的多欄 CSV 讀到的正是 raw Close，不需改腳本 (4) 重跑 `reproduce.py` → match 8/9 (88.9%)，S0 CAGR 12.497% vs paper 12.51%（Δ=0.013pp），S1 opp cost 4.200 vs paper 4.20 EXACT (5) 殘差 1 項：50/50 SPY/GLD 再平衡溢酬 paper 54 bps vs computed -66.81 bps — 此為 **sample coverage 問題**（paper 54 bps anchor 用 2006-2024，bundle 只含 2012-2024），orthogonal to auto_adjust，屬已知 pre-existing divergence。教訓：所有 yfinance 調用必須顯式 `auto_adjust=False`（或確實意圖 True 時註解說明），CSV bundler 應 commit 原始欄位（Adj Close + Close 兩者）避免歧義；reproduce 驗證應該先 assert bundle 第一筆 raw Close 對得上 paper canonical 數字再往下算 |
| 2026-04-17 | market_daily Supabase sync 連續 5 天靜默 400 失敗（全 10 策略 /portfolio 頁價格空白） | 前端 /portfolio 所有 active 策略的「交易紀錄」欄位（SPY/GLD/0050.TW 價格、σ）從 4/14 起空白。Supabase `market_daily` 表最後日期停在 2026-04-11，但 `paper_trades` 已到 2026-04-17（56 筆 × 4 天正常 sync）| (1) `scripts/supabase_sync.py` 的 `CONFLICT_KEYS` 缺 `market_daily` → `_post` 走 POST 無 `on_conflict`，重複 trade_date 會 409 但 fallback 條件 `if code == 409 and conflict` 為 False，直接吞錯 (2) commit `3d2d3ab9` (2026-04-12) 把 `overnight_gap` / `gap_alert_level` 寫進 `_market_daily`，這兩個欄位不在 `market_daily` schema → PostgREST 回 400 "column does not exist" → `_post` except 吞錯只 print "Supabase market_daily error: 400" (3) `scripts/daily_update.py` 只 sync 今天一筆，歷史失敗永遠無法補 (4) **用戶原初誤判為「缺 portfolio_return / weights」**，但實測本機 + Supabase 所有 10 active 策略的 `weights / portfolio_return / cash_weight / trade_date / data_date` 皆 ≥99.9% 完整；真正缺的是前端 enrich 用的 `market_daily` join source | (1) `CONFLICT_KEYS["market_daily"] = "trade_date"` (2) 新增 `_MARKET_DAILY_COLUMNS` 白名單 + `sync_market_daily()` / `sync_market_daily_backfill()` helpers 剝除未知欄位 (3) `daily_update.py` 改為 backfill 最近 30 天市場數據（inline 版本），未來斷層自動修復 (4) 手動 backfill 2026-04-14..17 四天資料到 Supabase，驗證 ok=4 fail=0。教訓：**sync 失敗被 `except Exception` 吞掉數週**（同 2026-04-11 Mirror API sync bug 再犯），任何 `_post` 失敗都該留 warning；**Schema drift 沒 schema validation 就會炸**，未來新增欄位到 `_market_daily` 要同步更新 `_MARKET_DAILY_COLUMNS` 或 Supabase migration |
| 2026-04-17 | Mirror incremental sync failure still silently drifted local vs remote | 重新驗證時發現 authenticated live `mirror-api` 已通，但 `knowledge.json` 本地 1929 entries、remote 1928 entries；舊版 `MemorySystem._sync_to_remote()` 仍用 `except: pass`，reconcile 也會誤報 `ok` | 2026-04-11 修過端點與 token，但 library path 的靜默吞錯仍未拔除，所以單筆 knowledge 寫入若失敗不會留下任何警告，直到 live smoke test 才暴露 drift | 修正：(1) `MemorySystem._sync_to_remote()` 改為只同步 mirror 支援的 4 個檔案 (2) sync 失敗改印 warning，不再靜默吞掉 (3) `reconcile_remote()` 改為真正回報失敗 (4) 2026-04-17 authenticated `mirror-api` `/health` + `/manifest` 已成功，證明本機 `.env.local` 的 token 與 Zeabur mirror-api 一致 (5) 同日已執行 full reconcile，remote counts 對齊 local（`knowledge.json=1929`）。教訓：**修了端點不等於修完流程，library path 的 silent failure 也要清乾淨** |
| 2026-04-17 | `knowledge.json` 尾端 stray `]}` 導致全系統 JSON parse 失敗 | 檔案尾 3 行為 `]}\n]}\n]\n`（正常只需 `]\n`），python `json.load` 丟 `Extra data: line 26548`，1928 entries 無法讀取，所有 memory-dependent 腳本（daily_update/supabase_sync/memory add）全部會 crash | `MemorySystem._append_to_index` 本身是 atomic load→append→rewrite 不會產生此 pattern。推論：外部手動 jq/sed 操作 append 了 stray token，或某個一次性腳本 `>>` append 而非 `>` overwrite。mtime=Apr 16 16:36，HEAD 28fc3772（04-16）之後發生 | (1) 備份 `knowledge.json.bak_2026-04-17_corrupted` (2) 刪除 line 26548-26549 兩行 stray `]}` (3) python `json.load` 驗證 1928 entries 與 HEAD 一致 (4) 合法 diff 僅 i1b/i3/i9/i10 路徑更新 91 行。**防禦建議待實作**：`_append_to_index` 寫入後加 `json.loads(path.read_text())` sanity check，失敗即 rollback 並 raise。教訓：所有 JSON writer 都應該有 post-write validation |
| 2026-04-13 | IS-based regime cutoffs degenerate when OOS 含 unprecedented volatility（K1128 教訓；K1131/K1130 2026-04-17 雙重否證結構性問題） | K1128 VIX tertile split: IS 2017-2019 VIX 9-37 vs OOS 2020-2021 VIX 15-82 (COVID)，IS quantile cutoff 套 OOS 變 low tertile=0 bars + mid 854 + high 20060 | IS quantile 邊界在 unprecedented event 下失效 — 所有 IS-based threshold 都有此風險 | **2/3 fixes empirically INVALIDATED (2026-04-17)**: (1) ~~IS 擴含 prior crises (2008/2011/2015)~~ → **K1130 INVALIDATED**：Extended IS 2012-2019 max VIX=40.74 仍 disjoint COVID VIX=83; OOS coverage min 0%→1.63% 幾無改善; LRT/DM/coverage 4/4 FAIL (Scenario D) (2) Expanding-window adaptive quantile → K1133 待測（但預期同樣結構失敗） (3) ~~連續 VIX-dependent β via spline~~ → **K1131 INVALIDATED**：spline OOS DM t=-3.94 反向，IS 外推爆炸，AUC=0.4965 below chance (4) Rolling quantile → K1134 待測。**結論：K1128 regime-switching narrative 應放棄**，改 "pooled \|OFI\| continuous microstructure signal" spec (high-tertile within-regime M3 vs M1 DM=+3.49 suggests signal 存在 without regime)。診斷：套 cutoff 前先 `assert OOS_low_count > 0 and OOS_mid_count > 0`。影響範圍：regime-switching GARCH、HMM、K1121 NFCI threshold（需回查）。已記 E064 |
| 2026-04-13 | TAIFEX bar-bucket overflow + active contract selection lookahead（K1124 教訓） | OFI 計算遇到 2 個 subtle bug 都會誇大效果 | (1) DAY_END=13:45 → bar=60 包含收盤後 1 秒，會讓 bar 59 預測 bar 60 (2) Active contract 用整天成交量選最活躍 = 轉倉日用下午 winner 決定早盤訊號 = lookahead | (1) DAY_END 改 13:44:59 (2) active contract 改 T-1 rolling (3) 加 M6/M7 strict lag-1 spec 驗證 beta 仍穩健 → 排除 current-bar leak。教訓：tick-level data 的 timing edge case 多，必須 explicit lag-1 + Codex 審 |
| 2026-04-13 | FRED publication delay = 隱性 lookahead bug（K1121 教訓） | K1121 第一版 alt-data allocation S4 EPU-regime Sharpe 1.250 看似有 edge | NFCI 觀測週五但週三才公佈（5 calendar days delay），需 `shift(5)`；EPU 觀測 X 日 X+1 公佈，需 `shift(2)` | (1) 修正後 S4 Sharpe 1.250→1.283 (tied baseline 1.309) (2) 規則新增：所有 macro/economic 數據查 publication schedule (3) Codex 救援避免 false positive。教訓：「結果太好」第一反應應該是「找 bug」不是「歡呼」（呼應 E059 LRT-DM divergence）。已記 E062 |
| 2026-04-13 | In-sample LRT p<0.001 + DM-HLN t<2 = overfit 警訊（K1100g_d1 → K1100g_d2 教訓） | K1100g_d1 in-sample night→day LRT χ²=12.48 p=0.0004 看起來極度顯著，但同實驗 DM-HLN t=+1.07 不顯著。我接受 finding 並啟動文章 agent。K1100g_d2 OOS expanding-window 驗證：LRT 0.00 (p=1.00) + DM-HLN -0.21（反向）+ QLIKE 惡化 0.48% | K1100g_d1 是 in-sample data mining——free param 增加自動 overfit residual variance 讓 χ² 顯著，但無真 predictive power | (1) K1100g_d1 knowledge entry 加 OOS-rejected warning (2) 立即 stop 文章 agent (還沒發出，幸運) (3) **規則新增：Paper-publishable finding 在啟動文章 agent 前必須 OOS PASS** (4) **回顧 knowledge.json 找其他「LRT 顯著但 DM<2」entries 安排 OOS 驗證**。教訓：LRT 用 全樣本 likelihood 易自動 overfit，必須配 DM-HLN 雙重門檻；divergence > 1.5 即需 OOS |
| 2026-04-13 | K1100g parquet cache 的 night_open/night_close mask-bug 給虛假 σ | K1100g report `σ(r_night)=0.000083` 導致 overnight/intraday ratio = 1.586（看似 night vol 驚人）。K1100g_d1 從 raw tick 重建得正確 σ=0.00581，真 ratio=0.765 | Cache 生成時 mask 邏輯錯位，只抓夜盤末尾幾 tick。K1100g 原 narrative「overnight vol 1.6× day」其實是 gap effect (13:45→15:00 + 05:00→08:45 無交易期間) 誤算 | (1) K1100g knowledge entry 加 ⚠️ warning tag (2) Paper 3 reframe 敘事改為「asymmetric cross-prediction」(night→day LRT χ²=12.5 p=0.0004) 取代「vol ratio」 (3) **未來實驗絕對不能直接讀 K1100g cache 的 night_open/close，必須從 raw tick 重建**。教訓：實驗 cache 中的非 raw return 欄位必須驗證才能 reuse；gap effect ≠ session asymmetry |
| 2026-04-11 | merge_worktree.sh 3 個 bug 導致 silent merge failure | (1) K1049 跑 `merge_worktree.sh .claude/worktrees/agent-xxx` 無效果但無錯誤 (2) K1052 以為已 merge 但實際上沒有（目錄不存在） (3) 20 個 orphan worktree branches 累積 | **Bug 1（致命）**: TARGET 匹配邏輯反轉。`basename("agent-xxx")` 不可能包含完整路徑 `.claude/worktrees/agent-xxx`，所以 targeted merge 永遠 skip。**Bug 2**: `echo \| while` pipe 子 shell 吞錯誤。**Bug 3**: worktree 移除但 branch 殘留 | 修正：(1) TARGET 正規化為 basename + 雙向包含匹配 (2) pipe-while 改為 for-loop + array（macOS bash 3.x compatible） (3) 結尾加 orphan branch cleanup pass。教訓：**Shell script 的 pipe-while 和字串匹配是常見陷阱，必須測試邊界條件** |
| 2026-04-11 | Mirror API sync 全部失敗 | daily_update.py 日誌顯示 "Sync memory/knowledge.json: HTTP Error 400" 等，所有記憶檔案無遠端備份 | (1) `VOLPRED_REMOTE_URL` 指向前端 `volpred-v3.zeabur.app` 而非 Mirror API (2) 端點路徑錯誤：用 `/api/sync/` 但實際是 `/api/mirror/memory/` (3) `RESEARCH_MIRROR_TOKEN` 從未設定（認證失敗 401）| 修正：(1) daily_update.py 改用正確端點 `/api/mirror/memory/{filename}` + PUT 方法 (2) MemorySystem._sync_to_remote 同步修正 (3) 加入 `x-research-mirror-token` header (4) **2026-04-17 已再驗證本機 `.env.local` 帶出的 token 可成功呼叫 live `mirror-api` `/api/mirror/health` 與 `/api/mirror/manifest`，證明 Zeabur mirror-api 同名變數一致**。教訓：sync 失敗被 `except: pass` 吞掉，症狀被遮蔽數週。**所有 sync 失敗都應 print warning** |
| 2026-04-11 | knowledge.json K1032-K1035 條目丟失 | Session sync 後 4 個實驗的知識記錄消失 | merge_worktree.sh 用 `git merge -X ours` — agent 如果違規修改了 knowledge.json（共享 JSON），main 版本會直接覆蓋 agent 新增的內容，不報錯不警告 | 修正：(1) merge 前加共享 JSON 變更檢測+警告 (2) merge 後加 experiments/ 檔案完整性驗證 (3) 手動從 README 恢復 K1032-K1035 知識條目。教訓：**`-X ours` 是安全閥不是萬能藥——違規時應報警，不應靜默** |
| 2026-04-11 | knowledge.json 71.7% 條目無 experiment_id | 搜尋/去重/索引品質全部受影響 | 早期知識系統用 category/item_id/evidence 結構（無 experiment_id），後來改為以實驗為中心但舊資料從未遷移 | 修正：(1) 為 1,310 條舊格式條目加 `legacy: true` 標記 (2) 去除 8 組重複 (3) 未來考慮分離為 knowledge_legacy.json 或回溯關聯 |
| 2026-04-10 | K1016 agent 回報不準確 | Agent 聲稱 QLIKE 改善 +13.7%（DM=+5.46），但 JSON 顯示 QLIKE 惡化（1.616→1.831）。M4/M5 結果完全相同（代碼 bug） | 主線程未在 agent 完成後立即交叉驗證 JSON 數字，直接信任 agent 回報並記入 knowledge + research_program | (1) 修正 knowledge 記錄（降 confidence 到 0.5）(2) 修正 research_program 標注 ⚠️ (3) 需重做 K1016b。**教訓：agent 完成後必須用 python 讀取 results JSON 驗證核心數字，不可只看 agent summary** |
| 2026-04-09 | 數據收集不完整 | FRED 停 23 天、VIXTWN DNS 失敗、QQQ/EEM/N225/VIX3M 不在收集器中 | `collect_us_data.py` 只收 4 個 ticker，FRED 完全沒自動化，`collect_5min_data.py` 不接受命令行參數 | (1) `collect_us_data.py` 擴充到 8 ticker + 週一 FRED 23 指標 (2) `collect_5min_data.py` 加 CLI 參數+ticker 格式修正 (3) 更新 CLAUDE.md 文檔。教訓：**新增研究用到的資產時，必須同步加入收集腳本+crontab** |
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

**✅ 已完成（2026-04-17 驗證）**：
- Migration 018 已在 live Supabase 生效（MCP `execute_sql` 確認 constraint 與 index 都存在）
- 前端 redeploy 已生效（timeout 已為 15000ms，`volpred.zeabur.app/api/health` 200）

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

**✅ 已完成（2026-04-17 透過 MCP `execute_sql` 驗證）**：
- Migration 018: unique constraint + index 已上線（`paper_trades_strategy_trade_date_key` + `idx_paper_trades_strategy_date` 存在於 `qxhfgdfzazwpkdgesavm`）
- Migration 019: `market_daily` 表已上線，825 rows（2023-01-04 → 2026-04-17）
- Frontend redeploy 已完成，`volpred.zeabur.app/api/health` 200 且 `fetchAPI` timeout 為 15000ms

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
- [x] 建立 K625 更正實驗（`experiments/k625/k625_tx_cost_correction.py`），使用正確成本參數重新計算
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

---

## 2026-04-09: 文章 tags 再次遺失（文章存在，但 article_tags 沒寫入）

### 問題
從 `mile_4cb24c36` 開始，多篇新文章在網站文章頁不再顯示既有 tags；前一篇 `mile_60c48d4c` 仍正常。

### 現象
- `storage/reports/<id>.json` 與通知內容都有 tags
- Supabase `articles` 表已有文章列，`article_tags` 卻是空的
- 前端單篇頁面完全依賴 `article_tags` join table，沒有關聯就不會顯示 tags

### 根因
1. `scripts/supabase_sync.py` 的 `_get_tag_ids()` 把 `tags.id` 當成 `str` 處理，但 DB schema 裡 `tags.id` 是 `INT`
2. 因為型別不符，tag id 查詢結果全部被丟掉，`article_tags` rows 永遠組不出來
3. `_sync_article_tags()` 外層又用 `except: pass` 靜默吞錯，所以發文看似成功，實際上 tags 已漏寫
4. 另外，`frontend-v2-fix/src/app/api/sync/[...path]/route.ts` 的遠端 sync 只 upsert `articles`，原本完全沒同步 `article_tags`

### 解決
1. `scripts/supabase_sync.py`：改為接受 `INT` tag id，並保留數字字串 fallback
2. `scripts/supabase_sync.py`：tag sync 失敗時改為明確 log warning，不再靜默吞掉
3. `frontend-v2-fix/src/app/api/sync/[...path]/route.ts`：補上 `tags`/`article_tags` 同步
4. 用正式 `sync_article()` 流程重跑受影響的最近 9 篇文章，補回缺失的 `article_tags`

### 教訓
- **Schema 型別要跟同步碼一致**。`UUID`/`INT`/`TEXT` 任何一個判斷寫錯，join table 會無聲失效
- **禁止靜默吞錯**。文章主體寫進去但 tags 沒寫進去，比整體失敗更危險，因為它會假裝成功
- **遠端 sync API 與本地 sync 腳本必須等價**。不能一條路同步 article，另一條路忘了同步 article_tags

## 2026-04-11: 會員提問文章 badge 不一致 + article_tags 更新後舊 tags 殘留

### 問題
會員提問文章的 badge（category）有三種值（milestone / qa / 會員提問），前端顯示不一致。

### 根因（流程缺陷，共 3 處）
1. `publisher.py`：`audience=member_qa` 沒有專屬 category 映射，fallback 到 `milestone`；也不自動在 tags 中加入「會員提問」，導致前端 v2 的 `resolveBadge()` 無法匹配
2. `_sync_article_tags()`：只 upsert 不 delete，tags 變更後舊的 article_tags 關聯殘留
3. `member-questions/skill.md`：發文指令沒有 `--category member_qa`

### 解決
1. `publisher.py`：加入 `_audience_tag_map`，發文時自動確保正確的 category tag 在 tags 首位（同時移除衝突的 category tags）；category 自動映射 member_qa
2. `_sync_article_tags()`：改為先 `_delete_where` 再 `_post`，確保 tags 更新時舊關聯被清除
3. `member-questions/skill.md`：加入 `--category member_qa`
4. `frontend-v2-fix/`：會員提問 badge 改為金色（yellow-300）
5. 既有 8 篇文章 category/tags 統一修正並重新同步 Supabase

### 教訓
- **修流程不修資料**（CLAUDE.md 明確規定）。手動改 JSON 只是治標，根因在 publisher 邏輯
- **tag 同步必須 delete-then-insert**。只做 upsert 的 join table 永遠不會清除舊關聯
- **前端改 `frontend-v2-fix/`**，不是 `frontend/`（舊版）。部署用 `frontend-v2-fix/scripts/deploy-zeabur-safe.sh`
- **遇到 error 第一步查 error_log**——這次的 article_tags 殘留問題跟 2026-04-09 同根源

## 2026-04-18: 文章 3-source divergence → Contentlayer 模式（P1/P2/P3/P4）

### 問題
`storage/reports/feed.json`、`storage/reports/mile_*.json`（1010 個單檔）、Supabase `articles` 三個地方同時存在文章資料，無事務保證：
- feed.json 925 筆 / mile_*.json 含 42 個 draft (status != feed 的 status) / Supabase 965 筆
- 25 筆 feed=published 但單檔 status=draft（release_pool 同步缺口）
- 16 筆單檔 orphan（不在 feed.json）
- 40 筆 Supabase 有但 feed 沒（admin/手動 PATCH 繞過 publisher）
- Monitor 抓 `feed.json.status=='draft'` 永遠 0（target 12 → 錯報 "pool 緊急"）

### 根因（反模式）
1. **Publisher 同時寫 3 處**（feed + 單檔 + Supabase），無原子性；任一步失敗不 rollback
2. **admin CMS / 手動 PATCH** 可反向寫 Supabase，不回流 feed
3. **Supabase `article_impressions.article_id` FK 原為 NO ACTION**（migration 001 疏漏），`DELETE FROM articles` 直接 409，導致同步工具失敗
4. **feed.json 5.4MB**（170 萬 token），Claude session 誤讀即燒滿 context

### 解決（Contentlayer 模式，4 phase）
**Phase 1**：新 `src/volpred/ops/feed_sync.py` + `ops feed-sync` CLI，單向 feed → Supabase reconcile（timestamp-normalized 比對避免 Postgres trim 微秒尾零 false-positive）；套用 reconcile 歷史 drift（1 insert / 78 update / 40 delete）。
**Phase 1b**：migration 021 將 `article_impressions.article_id` FK 改為 ON DELETE CASCADE（從 Python 補丁升級成 schema 底層修）。BUG-001 正式 resolved。
**Phase 2**：Monitor 改查 real feed↔Supabase drift，不再抓 `feed.json.status=='draft'` count。Session cron `11 */2` 重命名為「繼續任務」涵蓋非研究類。
**Phase 3**：publisher.py / content.py / supabase_sync.py 移除所有單檔讀寫；1010 個 `mile_*.json` 移到 `storage/reports/_archive_mile_files/`（git rename 保留歷史）；`article_backups.py` 整檔成 deprecation stub。
**Phase 4**：migration 022 declarative 記錄 articles RLS（service_role-only write；anon/auth read-only）。daily_update.py 清 dead code（不再 read archived singles）。

### 教訓
- **保留 feed.json 的 Contentlayer 模式最佳**：canonical + git audit + DB 是唯讀 projection，一次性砍單檔+封 RLS，永久無 divergence 風險
- **Supabase FK 必須 ON DELETE CASCADE 或顯式 pre-delete**：Python 補丁易被 canonical re-render 蓋掉（f00fb286 → 19ac8e49 覆蓋），修 schema 才穩固
- **timestamp 比對用 datetime parse，不用字串相等**：Postgres 返回 `.862770` → `.86277`（微秒尾零被 trim）
- **廢棄 code 先做 deprecation stub，不要立刻刪除函式**：保護既有 caller 不 break（article_backups）
- **3-source 模式天生反架構**。商業標準：單一 DB SoT（Headless CMS）或單一 Git SoT + read-only projection（Contentlayer / Astro）。混合多源沒事務 = 必定漂移

### 驗證
- `uv run volpred ops feed-sync` → feed=925 / db=925 / drift=0
- `Publisher.get_report(mile_xxx)` → 從 feed 讀 5314 字 content
- Monitor 每小時查 drift，0 alert = 健康
- Commits: f497a873 (Phase 1-2), 8450e5f6 (cron rename), 3eeeecce (Phase 3), e74ab077 (Phase 4)

## 2026-04-13: merge_worktree.sh K1032 bug 再現 (K1114)
- 現象：agent commit 5c6a5c8c (K1114 完整實驗檔) 真實存在於 worktree branch，但 merge_worktree.sh 在 detect-new-commits 階段判「沒有新的 commits 可安全移除」，執行 worktree force-delete + branch delete，主分支 experiments/k1114/ 不存在
- 過程：通知收到 → bash scripts/merge_worktree.sh agent-a96a6532 → ls experiments/k1114/ 報 No such file → git reflog --all 找回 commit 5c6a5c8c → git checkout worktree-agent-a96a6532 -- experiments/k1114/ → git add + commit recover
- 解決：當下用 reflog 救回；長期需修 merge_worktree.sh 改用 git rev-list --count main..<branch> 確切數新 commits（K1143 任務）
- 經驗：E067（infrastructure 類）；worktree-merge-verification skill 必加「merge 後立即 ls experiments/<latest> 驗證」

## 2026-04-19: merge_worktree.sh K1032 bug **第三次再現** → K1143-v2 systemic fix

### 現象
Paper 8 diagnostic session 發現 K903/K904 robustness scripts 的 `json.dump` 輸出寫到 `.claude/worktrees/agent-aa0c111f/experiments/...` 從未 merge 回 main；同 session agent-aa9aeb5d 也留下 untracked `experiments/k1100g_d9/` (refit-cadence robustness) 從未 commit。**跨 paper、跨 agent、跨 session 反覆發生** = systemic bug。

### Root cause（K1143-v1 修復不夠）
K1114 修復只處理 `git log` vs `rev-list` 不一致的 silent failure，但漏掉幾個路徑：

1. **`--force` fallback 還在 line 126**：`git worktree remove "$wt_path" 2>/dev/null || git worktree remove --force "$wt_path" 2>/dev/null` — 違反 CLAUDE.md L168 明文禁止。當 auto-commit 漏偵時，script 走到 line 123「可安全移除」路徑 → 吞掉未 commit 的工作目錄。
2. **`git status --porcelain 2>/dev/null || true`** (line 78)：status 失敗會變空字串 → `has_uncommitted=false` → skip auto-commit → rev-list=0 → line 126 `--force remove` → silent loss。
3. **Auto-commit 成功但 HEAD 沒前進**：worktree 若 detached 或 add 無東西可 commit，舊 code 不檢查 HEAD 差異，後續 rev-list=0 誤判。
4. **rev-list=0 不代表工作目錄乾淨**：auto-commit 失敗或 gitignore 吃掉檔的情況下，worktree `experiments/<kXXX>/` 仍有 orphan 但 rev-list 看不到。
5. **Orphan branch cleanup `git branch --list | tr -d ' '`** (line 355)：不清 checked-out 標記 `+` → 產出 `+worktree-agent-xxx` 錯誤名稱，後續 rev-list / branch -d silent 失敗。

### K1143-v2 fix (2026-04-19)
1. 移除 `--force` fallback（line 126 區塊），remove 失敗直接 abort + 提示手動處理
2. `git status` 失敗嚴格 abort，不 silent skip
3. Auto-commit 後驗證 HEAD 前進，未前進 abort
4. rev-list=0 path 加 pre-remove 掃 `experiments/<kXXX>/`，有 orphan 資料夾或 worktree-only 檔就 abort
5. Orphan branch cleanup 改用 `git for-each-ref --format='%(refname:short)'`
6. 新增 `scripts/tests/test_merge_worktree.sh`：4 cases / 7 assertions，含 K1100g_d9 bug reproducer（gitignore-hidden orphan）

### 驗證
- `bash scripts/tests/test_merge_worktree.sh` → 7/7 PASS
- Dry-run `bash scripts/merge_worktree.sh --dry-run agent-aa9aeb5d` → 正確 ABORT 並指認 k1100g_d9 orphan
- Orphan branch cleanup 正確列出 `worktree-agent-afab0431` (不是 `+worktree-agent-aa9aeb5d`)

### Recovery actions needed
- **K1100g_d9** (refit-cadence robustness, N225/SPY Hansen skewed-t DM rerun)：worktree `experiments/k1100g_d9/` 有完整 README + script + run.log，主目錄無 → 需 copy + commit 到 main (follow-up task)
- **K903/K904** Paper 8 robustness：用戶稱 agent-aa0c111f 已經不在，若確認 worktree 已 remove 且 commit 未進 main → 需回溯檢查 reflog / git fsck --dangling 看能否找回；若無法救回 → 需重跑 robustness experiments
- **K1032/K1114** 過去修復：已 cherry-pick 救回，無遺留問題

### 經驗（E069 歸類）
- E067 (K1032/K1114) 不夠徹底 — 第三次再現才發現 `--force` fallback + status silent skip + orphan workdir 三個 attack surface
- 規則：**workflow script 修 bug 必須寫 test case 反覆驗證，不能只 patch 單一已知路徑**


## [FIXED 2026-04-18] BUG-001 cleanup-post FK cascade

`scripts/supabase_sync.py` `delete_article` 改為 cascade：
- 先 `_get_article_id(slug)` 拿 UUID
- 再 `_delete_where("article_impressions", {"article_id": uuid})`（唯一非 CASCADE FK，per migrations/001 line 85-252）
- 最後 `_delete_where("articles", {"slug": slug})`
- articles DELETE 失敗時 print `[BUG-001 guard]` 警告，不再 silent success

驗證：`article_reactions`、`question_articles`、`article_tags`、`comments` 都是 ON DELETE CASCADE，不需 manual cascade。

**測試 TODO**（未執行）：下次 cleanup-post 用有 impression 的 draft 驗證 Supabase row 真刪。

## 2026-04-19 Paper 4 Table 2 K732/K736 底層 pipeline bug

**症狀**: Paper 4 vix-sufficiency main_v2.tex Table 2 的 K732/K736 行數字與 source JSON 明顯不 match。
- K732 `IS t-stat=1.64` 實為 `dm_stat_oos=1.637` 抄錯格
- K736 整列 composite salad：跨 3 sub-experiments 混搭欄位

**底層 root cause**（非單一 paper bug）：
1. **Paper body 寫作 pipeline 缺 reproduce gate**：改 body.tex 沒強制跑 reproduce check 比對 claimed numbers vs JSON
2. **Table row 與 JSON source 無 traceable binding**：row column 來源是哪個 JSON / field 沒標，造成複製錯
3. **Reproduce.py 驗證範圍不夠**：只檢 match rate 總體 %，沒做 claim-to-source strict mapping
4. **Review 流程沒抓**：R1/R2 review cycle 沒要求作者提供 Table row → JSON field 對應表

**底層修法**（進 paper-workflow rule）：
- 新 gate：paper-update CLI 改 body.tex 時自動跑 reproduce_report.json + 驗證每個 claimed number **必有** source JSON field path (`experiments/kXXX/xxx_results.json` + `.field_name`)
- Table row 旁加 `% source: experiments/kXXX/results.json.field_name` inline comment
- reproduce.py 輸出 strict mapping: {table_row: {column: {paper_value, source_path, source_value, match}}}

**未來踩坑預防**: 每個 Table 裡每個數字都要 self-contained traceable 到 JSON source。

## 2026-04-19 release-pool-by-settings last_released_at 不更新

**症狀**: 2026-04-19 15:17 `uv run volpred ops release-pool-by-settings` 成功 release mile_67b6a9a6，但 `storage/.release_settings.json last_released_at` 仍停在 09:27（前次實 release 時間）。
16:03 host cron fire 時被 "interval_not_due" 誤判 skip。

**根因**（推測，需 Codex 修）：release-pool-by-settings 命令實際 released article 後未更新 settings last_released_at；或 update 有 race condition。

**影響**: cron 每 2h fire 但幾乎永遠 "interval_not_due" 因 settings stale → release cadence 斷鏈。

**Fix 方向**:
1. Audit `src/volpred/ops/release_pool.py` (或 corresponding) release 命令完成後應 `settings['last_released_at'] = now` + save
2. 或 settings 動態從 feed.json 推（`max(published_at for status=published)` as last_released）— 避免 stale state

**暫時 workaround**: 手動改 settings 當 release 後（違反「不手改資料」rule，不推薦）；或 Codex 修 code（推薦）。

## 2026-04-19 release-pool-by-settings fix RESOLVED (Codex task_fdf87e79f019)

**Fix commit (pending)**: `src/volpred/ops/content.py` +80 lines: release 命令完成後 `settings['last_released_at'] = datetime.now(timezone.utc).isoformat()` + save + feed 自癒 fallback（settings 缺 last_released_at 時從 `feed.json` published_at max 推斷）。新 regression gate `tests/test_content_release_pool.py`（3 venv 模擬案例全 pass）。

**驗證方式**: 跑 release-pool-by-settings → `cat storage/.release_settings.json` 驗 last_released_at = now ISO。

## 2026-04-19 Cross-session paper gate fix 大批處理（本 session）

**背景**: 9 papers 有 7 doing reproduce gate 未過 95% green。Session 系統性 fix:

| Paper | Before | After | Fix summary |
|---|---|---|---|
| P1 leverage-direction | 53.4% (7 MISMATCH + 19 UNTRACE) | 21 MATCH / **0 MISMATCH** / 9 NOTE / 20 UNTRACE | K1256 3-spec HM, Kupiec rounding, 5 cross-source NOTE reclass |
| P3 vt-trend-following | 80.7% (4 MISMATCH) | 83% (**0 MISMATCH**) | M5 BAB hybrid proxy disclosure, Table 3 dual-window errata |
| P4 vix-sufficiency | 44% (5 MISMATCH) | **98% GREEN** | Sub1-6: bundle+dividend, Table 6 K752 rewrite, narrative reframe |
| P5 vt-crowding-abm | 100% ✅ | **100% ✅ sustained** | v2 revise: 4 MAJOR + 3 DOI + 4 MED → 4.3★ FRL |
| P6 prg-periodic-garch | R2 / 15/15 reproduce | 13/15 (86.7% amber yfinance), PRS continuity + FRL 11pt both RESOLVED | v2 revise 2 MAJOR + 6 MED + 17 DOIs, PRS §6, 11pt 16pp→13pp |
| P8 volatility-absorption | 50.7% RED | 61.3% AMBER | Sub6 T6 5 (a) fix + T5 (c) footnote |
| P9 garch-x-vix | 84.6% | 53.8% RED (snapshot revealed drift) | Codex snapshot-first integration exposed K997/K1085 T-stats drift, errata pending |

**Data snapshot infra 新增**（Codex task_4e75）: `scripts/snapshot_yfinance.py` + 5 paper `data/` CSVs（P1/P2/P8/P9/P_insurance）。多 paper reproduce.py snapshot-first fallback 整合。

**Net impact**: Paper 4 投稿 gate 過，P5 維持 green，P1/P3 mismatch 清零，P6 blocker 全解。P8/P9 的剩餘 red/amber 都是 K-experiment 重估需求（非 paper body 錯誤）。

## 2026-04-19 11:50 UTC — Codex quota exhausted until 2026-04-24

**症狀**: Codex P30 release-task CLI bg (`task-mo5opt7l-w9vbt0`) fail 3s after start: "You've hit your usage limit... try again at Apr 24th, 2026 10:27 AM".

**影響**:
- 所有 queued codex-preferred tasks 無法派出 ~5 days
- 剩 task_7d2c (P25 crypto-fear audit) + task_0658 (P30 release-task CLI) 需等 quota reset
- Claude slot 雖 free 但 queue 無 claude-preferred items

**本 session 在 quota 耗盡前已達成（Codex side）**:
- P12 data snapshot infra (task_4e75) ✅
- P15 release-pool last_released_at fix (task_fdf8) ✅
- P10 Paper 6 pre-submission audit (task_361a) ✅
- P30 session-bootstrap v11 cleanup (task_9b07) ✅
- P25 claim-next parent guard (task_6e7c) ✅

**延後工作**: task_0658 release-task CLI 補齊 task state machine (手動 release claim-後-誤抓 task)

**暫時 workaround**: 主線程 `finish-task --status failed` 仍是唯一 recover path until release-task CLI 上線。

## 2026-04-19 13:20 UTC — Host cron selective skip: release_pool stalled while check_alerts working

**症狀**: 兩 wrapper 同目錄 (`~/.volpred/bin/`)、同格式、同 owner、同 chmod +x，但 cron daemon 選擇性不 fire release_pool：

| Cron entry | Expected fires today (dow=0 Sunday) | Actual fires | Status |
|---|---|---|---|
| `0 * * * * cron_check_alerts.sh` | 每小時 ~22 次 | 233 log lines ✓ | Working |
| `3 */2 * * * cron_release_pool.sh` | 每 2h ~8 次 | 12 log lines，last 09:30 CST (stale 12h) | **Broken** |
| `0 15 * * 1-5 cron_collect_tw.sh` | dow=1-5，Sunday skip | 0 lines | Expected skip |
| `3 7 * * 2-6 cron_collect_us.sh` | dow=2-6，Sunday skip | 0 lines | Expected skip |
| `3 8 * * 2-6 cron_daily_update.sh` | dow=2-6，Sunday skip | 0 lines | Expected skip |
| `0 8 * * 1 cron_market_cal.sh` | Monday only | 0 lines | Expected skip |

**已知 mitigations 無效**（本次 session 發現）：
- wrapper 放在 `~/.volpred/bin/`（避開 Desktop FDA 限制）— 不夠
- chmod +x 正確
- Binary `uv` 絕對路徑（/opt/homebrew/bin/uv）
- `cd` 到 repo root
- Manual invocation 正常（本次 13:20 UTC 手動跑 released mile_2d35fcc4 成功）

**alert_dedup 狀態**：`Release pool cron gap > 2h` 自 05:41 UTC 後 skip_count=12 — check_alerts 每小時偵測到問題但 24h 內 dedup 不 re-send email（anti-spam）。**User email inbox 不會再收到警報直到 dedup 過期**。

**Root cause 假說**（需下 session 驗證）：
1. macOS cron daemon 對 `*/2` 時間表達式有 bug（unlikely，常用 pattern）
2. 系統休眠期間所有 cron job 跳過，`*/2` 遇到的 slot 剛好都是休眠（巧合？）
3. release_pool.sh `exec uv run` 的 `exec` replaces shell，cron 認為 exit code 非零（但 uv exit 0 should OK）
4. cron 有 stdin/tty issue 特定於 release_pool 的 terminal interactive prompts？（release-pool-by-settings 有時問 Supabase auth）

**Workaround (current session)**: 每次 `*/4 繼續任務` cron tick 時主線程檢查 `last_released_at` age，若 > 150 min 主動跑 `~/.volpred/bin/cron_release_pool.sh` 手動補。本 session 已執行 1 次手動釋出 at 13:20 UTC。

**Fix direction (next session)**:
1. 改用 launchctl + launchd plist 代替 crontab（macOS 推薦）— deferred
2. ✅ **IMPLEMENTED 2026-04-19 13:27 UTC**: `scripts/check_alerts.py` 加 `_auto_trigger_release_pool_if_due()` piggy-back。Hourly check_alerts cron（reliable）現會在 `last_released_at` age ≥ `interval_minutes` 時 subprocess run `uv run volpred ops release-pool-by-settings`。Test verified: 當前 gap < interval → correctly skip; 預期 16:00 UTC 起 effective cadence 穩定 2-3h（延遲 upper bound 1h = check_alerts hourly + interval boundary crossing 時間差）。
3. 或改 cron 時間為 hourly（`3 */1 * * *`）避開 `*/2` 可能 parsing 問題 — deferred (option 2 已足夠)
