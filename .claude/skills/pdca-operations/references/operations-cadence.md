# 運營 Cadence 規劃表（所有常態工作 × 週期 × skill × 觸發 × 監控）

2026-06-30 用戶教訓：**skill 建了還要真的被觸發**（靠排程 cron + 每日大體檢/pdca loop 主動 invoke，不是放著就會跑）；**流程要分 cadence**（有些每天、有些每週/每月）。沒排程 = 不會執行；沒人 invoke = skill 不會自己觸發。

**自主運營經理的責任**：盤點所有工作 → 每個指派 cadence + skill + 觸發機制 + 納入大體檢監控 → 自己在對的週期 invoke（不等用戶推）。這份表是 single source；新增常態工作必加進來。

每個 autonomous tick / 每日，先跑大體檢，再對照本表「今天/本週該做什麼還沒做」→ 主動 invoke 對應 skill / 派工。

## 每日（DAILY）

| 工作 | skill / 工具 | 觸發 | 大體檢監控 |
|---|---|---|---|
| 大體檢（result-level 7 維度） | `pdca-operations` / `scripts/daily_checkup.py` | **GAP**：wrapper 已有、host schedule 尚未 materialize（task `platform_ops_materialize_daily_checkup_schedule`）；目前每 tick / 手動 | 自己 |
| 資料收集（美股/台股 EOD + 盤後） | `data-collection-ops` | cron collect_us(07:03)/collect_tw(15:00)/daily_update(08:03+15:05) | data_freshness |
| 內容釋出（6h 一篇） | `feed-publisher` | cron release_pool（`7 */6`，piggy-back） | content_pipeline |
| 補草稿池（< 4 即補） | `publication-candidates`+`feed-publisher` | cron reader_facing_refill + 大體檢 finding | content_pipeline |
| 每日精選導讀 | `feed-publisher` | cron digest_daily_enqueue(09:00) | content_pipeline |
| Alert 巡檢 + auto-remediation | `pdca-operations`+`platform-ops-manager` | cron check_alerts(`0 * * * *`) | cron_completion |
| 研究實驗推進（hourly 派工） | `autonomous-research` | hourly_dispatch | mission_progress |
| FB / 曝光巡檢 | `trending-repost` | cron audit_fb_pipeline | — |
| Boss report | — | cron boss_report_4h | — |
| Email 回覆（PHASE 0） | — | gmail_poll → email_reply task | — |

## 每週（WEEKLY）

| 工作 | skill | 觸發 | 備註 |
|---|---|---|---|
| **研究主題挖掘（期刊）** | `research-topic-discovery` | cron journal_topic_scan（週一/四）+ backlog<3 | 財金+實務+**經濟頂刊**+計量四群；落檔 research_program.md。深度版用 workflow econ-journal-topic-mining |
| 論文審查 cycle | `paper-review-cycle` | refresh_paper_snapshots + stage 到 review | — |
| 策略 lifecycle 審查（上/下架） | `admin-ops` | 週度 + 新策略/MDD>20% | project_strategy_lifecycle_standing_directive |
| 趨勢部落格掃描 | `trending-repost` | 週度 | reference_trending_blog_sources |
| arXiv 前沿掃描 | — | cron arxiv_scan | 技術精進來源 |
| 運作指示文件 doc-drift audit | `pdca-operations` Act | 日期化 successor 先以 `blocked_until` 等待；hourly `unblock_expired_blocked_tasks.py --apply` 到期轉 pending | 比對 CLAUDE/rules/skills 與實作、驗 path-trigger、縮已機械化 prose、合併矛盾；輸出 `docs/governance/YYYY-MM/` 報告。不得重用 task id 或立即 pending |

## 每月（MONTHLY）

| 工作 | skill | 觸發 |
|---|---|---|
| **Skill 審查（增/刪/併/拆，避免 proliferation）** | `pdca-operations` skill 治理段 | 每月 1st session（CLAUDE.md 規則）。重點 audit：8 個 paper-* skill 是否整併 |
| Memory health / drift | `memory-health` | cron memory_health_daily（彙整月度） |
| Error log governance sweep | — | 月度 |
| 論文 portfolio tier 檢視 | `paper-stage-classifier` | 月度 |

## 不定期 / 事件驅動（EVENT）

| 工作 | skill | 觸發 |
|---|---|---|
| 事件文章（FOMC/CPI/NFP/財報） | `feed-publisher` event-templates | populate_events_weekly → event_jobs |
| 用戶糾正後制度化（PDCA Act） | `pdca-operations` | 用戶 feedback |
| 平台新功能/網頁新呈現/新服務 | `web-ui-ux-review`+對應 | 主動發現（沒人開也要做） |
| 資料 recovery | `data-collection-ops` | 大體檢 data_freshness finding |

## Gap 維護

新增任何常態工作 → 問三件事並補齊：(1) 有對應 skill 嗎？(2) cadence 是什麼、有 cron/觸發嗎？(3) 大體檢哪個維度監控它？三者缺一 = 會被遺忘/不執行。補完更新本表。
