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
| B1 | **Sitemap 1,000 篇 URL 全 404**（UUID 而非可解析路徑）— SEO 入口歸零，本次審計唯一 bug 級 | M5+盈利 | 前端 agent：實測正確 URL 形式 → 改 sitemap.ts → build → safe-deploy → curl 抽測 | 🔄 |
| B2 | 文章頁 og:image / twitter:image 缺失（社群分享無圖）| M5 | 同 B1 agent 一次做 | 🔄 |
| B3 | RSS feed + canonical URL 缺失 | M5 | 同 B1 agent | 🔄 |
| B4 | /feed /papers /strategies 猜測路徑 404 → next.config redirects | M5 | 同 B1 agent | 🔄 |
| B5 | Pool 衛生批次：2 筆 false-failed flip（artifacts 已驗證上線）、K1330 blocked→succeeded（Codex review 6/23 已 PASS）、K1258 receipt 71 天 awaiting_approval 關閉、過時任務批次關閉（TCC crontab / kid_collision K1414 / 2 筆 null-metadata trending / 6 筆 stale FB / K136 K628）| M4 | pool agent（CLI 寫入不手改 JSON）| 🔄 |
| B6 | collect_us 部署版 wrapper 漂移（exit banner 5/29 起消失 = host_cron_fail 盲區）— cp 同步 | M4 | 主線程 | 🔄 |
| B7 | 2 個 stale memory 更新：strategy lookahead audit 其實已完成（6/21 全 reject）、papers submission framing 已從「等投稿決策」變「revision 工作」 | M2/M3 | 主線程 | 🔄 |
| B8 | Paper stage tracker `stage_entered_at` 7/1 被 bulk 重設 — 依 git 證據回填真實日期 | M3 | 主線程 | 🔄 |

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
| C12 | Paper review cycle 佇列：6/11 batch 四篇 + 零 review 兩篇（forecast-tail-divergence / k189_audit）+ vt-insurance-cost 首輪正式 review | M3 | P2 |
| C13 | K1328/K1337 各開 v2 任務（Codex FAIL findings 當 brief）| M2 | P3 |
| C14 | diversity_rule NULL-quartet 冷卻 38 天 → 評估解封 1 筆 ML 實驗試水 | M2 | P3 |

## D. 需老闆 policy 決策（不自主執行）

| # | 項目 | 現況與選項 |
|---|---|---|
| D1 | **金流接通**（變現漏斗末端斷裂：pricing 頁 + tier gating 齊備，但想付錢也無路可付）| 最小可行：Stripe Payment Links 或台灣在地 TapPay/藍新 + webhook 更新 role，先讓 Radar Plus 單一方案可付。需老闆決定：金流商選擇、定價、開收費的時點 |
| D2 | 論文投稿 framing 更正 | 兩篇「submission-ready」其實都已被誠實 re-review 撤回 ready（prg 5/21+6/24 兩次、leverage 7/01-03 三連 FAIL）——目前卡點是 revision 工作不是投稿決策；revision 收斂後會再帶完整狀態請老闆做投稿決策 |
| D3 | 雲端 agent git 分岔（6/24 已同步 0/0）| 建議：停掉雲端 push、改 email-only 報告（本地 push_backlog switch 現在已覆蓋備份監控）。等老闆點頭執行 |

## E. 驗證 gate

- 全量 pytest 綠（背景執行中）
- 前端改動：build 過 + safe-deploy + 線上 curl 抽測 sitemap URL 200 + og tags 存在
- pool 衛生：dashboard blocked/failed 計數下降且無誤關（抽查 3 筆）
- 每項完成寫回本文件狀態欄

*Created 2026-07-04 13:20 台灣時間；owner = interactive main thread。*
