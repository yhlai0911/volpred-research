# 平台優化執行計劃 — 2026-07-04

**來源**：boss 指令「還有什麼要修的？都徹底修好。有什麼對這專案、平台運作的優化措施，也規劃好做成執行計劃後執行」。
**依據**：5-agent 深度體檢（pool 衛生 / 線上健康 / 資料新鮮度 / 論文管線 / 變現漏斗）+ 當日 incident 修復記錄。
**對照 Mission**：每項標註服務的 mission（M1 文章 / M2 研究 / M3 論文 / M4 平台 / M5 流量）與 monetization 貢獻。

## A. 當日已修完（本文件建立前）

| # | 項目 | 狀態 |
|---|---|---|
| A1 | Push 被 silent-fallback gate 擋 26h（47 commits 積壓）— 8 處 fallback 修復 + 解封 | ✅ 已推上，13:00 班 exit 0 |
| A2 | `push_backlog` dead-man switch（>3h warn / >8h critical）進 check_alerts + 5 tests | ✅ live 驗證 |
| A3 | dispatch_supervisor Codex round-2 全部 findings（冪等清理 / lockfile inode 驗證 / unverified runbook / probe-failed sentinel）| ✅ 93/93 tests，shadow daemon 已載新碼 |
| A4 | Pool 乾涸 — 期刊挖掘 11 條新弧線 + refill 0→6 pending | ✅ |
| A5 | `test_audience_inference.py` 3 failed + 1 hang（live_verify 對線上站輪詢 120s/篇）| ✅ 30/30，hang 根因修在 live_verify 的 NO_REMOTE_WRITE skip |
| A6 | silent-fallback baseline 72→63 | ✅ |

## B. 立即執行（本 session，quick/high-impact）

| # | 項目 | Mission | 執行方式 | 狀態 |
|---|---|---|---|---|
| B1 | **Sitemap 1,000 篇 URL 全 404**（UUID 而非可解析路徑）— SEO 入口歸零，本次審計唯一 bug 級 | M5+盈利 | sitemap.ts 改 slug → build(node22) → safe-deploy → 線上抽測 3 URL 全 200 | ✅ **已上線驗證** |
| B2 | 文章頁 og:image / twitter:image 缺失（社群分享無圖）| M5 | reports/[id]/page.tsx generateMetadata | ✅ 線上 og:image 生效 |
| B3 | RSS feed + canonical URL 缺失 | M5 | 新增 rss.xml/route.ts + layout discovery link | ✅ /rss.xml 200 合法 XML |
| B4 | /feed /papers /strategies 猜測路徑 404 → next.config redirects | M5 | next.config 308 redirects | ✅ /feed→308→首頁 |
| B5 | Pool 衛生：blocked lane 永不被 sync 重掃的結構盲區（K1330 blocked 11 天） | M4 | **結構性修法**：sync_next_tasks_status 擴充掃 blocked review-gate + 2 tests；K1330 由 FLOW 自動關閉（下次非-hourly sync 執行）| ✅ code+test 完成，data 待下次 sync run |
| B6 | collect_us 部署版 wrapper 漂移（exit banner 5/29 起消失 = host_cron_fail 盲區）— cp 同步 | M4 | 主線程 | ✅ 已同步部署 |
| B7 | 2 個 stale memory 更新：strategy lookahead audit 已完成、papers submission framing 更正 | M2/M3 | 主線程 | ✅ 兩 memory + MEMORY.md 已更新 |
| B8 | Paper stage tracker `stage_entered_at` 7/1 被 bulk 重設 — 依 git 證據回填真實日期 | M3 | 主線程 | 🔄 排入 C 區 |

**額外完成（體檢外，本 session 發現並修）**：
- **分類 bug（真 product bug）**：`classify_topic_cluster` 裸子字串比對讓 2-3 字元 ASCII 關鍵詞誤中（`es`⊂timestamp、`var`⊂variance→誤入 risk_mgmt），silently 汙染 cluster 計數/caps/dedup。改 ASCII 詞界匹配 + regression test。✅
- **17 個 stale/flaky 測試修復**：全套從 15 紅→綠（depth-gate 誤傷、cap 15→80 漂移、event-config/registry 真檔洩漏、warn 措辭升級、live_verify 對線上輪詢 hang）。✅
- **live_verify test hang**：`VOLPRED_NO_REMOTE_WRITE=1` 時對線上站輪詢 120s/篇造成 3 分鐘 pytest hang，加 skip。✅

## C. 排入 task pool（medium — hourly dispatcher / compute worker 消化）

| # | 項目 | Mission | Priority |
|---|---|---|---|
| C1 | event-receipt watchdog：check_alerts 加 detector（claimed>24h / queued 過 deadline 的 storage/ops/tasks receipt）+ gc 標 expired；FOMC T+0 zombie 關閉 | M4 | P2 |
| C2 | blocked lane 結構清理：deprecated(71 筆)→terminal 遷移 script + mark_task_blocked 強制 blocked_until + schema guard（擋 null reason）| M4 | P2 |
| C3 | sync_next_tasks_status 擴充：掃 blocked awaiting_codex_review（review 檔存在即解封）+ --sweep-failed（暫時性失敗 artifact re-verify）| M4 | P2 |
| C4 | K506 resurrect（P1 原值：只差 EWT 2010-2021 資料下載）→ compute queue 抓資料後重跑 | M2 | P1 |
| C5 | K1380_v4 重跑（Paper 9 C3；results.json 截斷 = agent 中途死亡）+ 實驗 results 寫檔改 tmp+rename 原子寫入 | M2/M3 | P2 |
| C6 | daily_update sync-health calendar-aware（消「2 tables drifted」假日噪音）| M4 | P3 |
| C7 | indicator_arena 假日日曆降噪 | M4 | P3 |
| C8 | priority 欄位型別統一（int/字串混雜 sweep + 寫入端 normalize）| M4 | P3 |
| C9 | Analytics 回饋閉環：scripts/pull_reader_metrics.py 每日拉 top-N impressions/read-time → storage/analytics/ → 接進選題與 daily checkup | M1+M5+盈利 | P2 |
| C10 | Newsletter Phase 1：Supabase newsletter_subscribers 表 + 文章頁尾 email capture + 週報 email（複用 email_notifier pipeline）| M5+盈利 | P2 |
| C11 | Mirror sync 401：對齊 mirror-api Zeabur env OPS_ADMIN_TOKEN（既有 pool 任務，需 Zeabur console 權限確認）| M4 | P3 |
| C12 | Paper review cycle 佇列：6/11 batch 四篇 + forecast-tail-divergence（outline，待成稿）+ vt-insurance-cost 首輪正式 review；`k189_audit` 已於 2026-07-12 確認為文章審查紀錄並移出 paper pipeline | M3 | P2 |
| C13 | K1328/K1337 各開 v2 任務（Codex FAIL findings 當 brief）| M2 | P3 |
| C14 | diversity_rule NULL-quartet 冷卻 38 天 → 評估解封 1 筆 ML 實驗試水 | M2 | P3 |

## D. 需老闆 policy 決策（不自主執行）

| # | 項目 | 現況與選項 |
|---|---|---|
| D1 | **金流接通**（變現漏斗末端斷裂）| **後端骨架已建（2026-07-04，關閉狀態）**：`src/volpred/payments/` 綠界 adapter + CheckMacValue（官方向量驗證）+ PAYMENTS_ENABLED off，見 `docs/payments_go_live_checklist.md`。仍需老闆決定：達標時點、申請正式綠界商戶、開收費 |
| D2 | 論文投稿 framing 更正 | 無立即待決策項——目前無任何論文 submission-ready（garch-x-vix 已投稿審查中，其餘皆 revision/draft）。將來會來的決策：(a) 7 篇 journal_target="decide" 的目標期刊（我提案、老闆核可）；(b) 某篇真正 ready 時的「投不投 X 期刊」（outward-facing 不自動投） |
| D3 | ~~雲端 agent git 分岔~~ | **已於 2026-06-24 由老闆決定解決**（停雲端 push、4 routines disabled、本地 git_push_backup 接手）。我先前誤列為待決策——實際無待辦，唯一殘餘是 disabled routines 可到 claude.ai 完全刪除（非必要） |

## E. 驗證 gate（本 session 達成情況）

- ✅ 全量 pytest：15 紅 → 全綠（修 17 個 stale/flaky 測試 + 1 個真 classification bug + live_verify hang）
- ✅ 前端改動：node22 build 過 + safe-deploy + 線上抽測 sitemap 3 URL 全 200、RSS 200、og:image 存在、/feed→308；SEO commit 已 push GitHub
- ✅ dispatch_supervisor：3 輪 Codex review 全 finding 修畢（95/95），shadow run live
- ✅ pool 衛生：結構性 sync 盲區已修（code+test）；K1330 由 flow 自動關閉
- 🔄 C 區 medium 項排入 task pool，由 hourly/compute worker 消化

## F. 本 session 未做、明確交接（誠實列出）

- **C 區 14 項** medium 優化排入 pool（event-receipt watchdog / blocked-lane terminal 遷移 / K506·K1380_v4 resurrect / analytics 回饋閉環 / newsletter Phase 1 / paper review 佇列等）
- **D 區 policy 項**待老闆決策：金流接通（漏斗末端斷裂，pricing+gating 齊全但無付款路徑）、論文投稿（兩篇需先 revision 收斂）、雲端 agent git 分岔處置
- **sync_next_tasks_status 自動排程化**：目前只手動跑；應 wire 進 ops 迴圈讓 blocked-lane 對帳自動化（C 區補充項）
- **B8 paper stage_entered_at 回填**：排入 C 區

*Created 2026-07-04 13:20；末次更新 14:23 台灣時間；owner = interactive main thread。*
