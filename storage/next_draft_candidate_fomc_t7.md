# Next Draft Candidate: FOMC 04/28-29 T-7 Preview (Event-Driven)

> **🔒 CONSUMED 2026-04-20 01:10 UTC** — Article published as `mile_a0dccb21` (audience=research, status=**published** event-driven, 2,339 CJK, 2 real matplotlib charts HTTP 200 OK, phase=Event_FOMC_2026_04). Dispatched via Claude general-purpose agent `a9b6291b1ed401ba2` per user's "stop hold, dispatch" feedback. **差異化敘事**: 20 年 173 場 FOMC × 8-day event window = 1,384 obs（超 brief 預期 20 年 pattern 規模）；findings: T-6..T-2 無 pre-meeting vol build-up、2026 regime 最像 2010/2016/2019 三場 hold；含 position sizing decision tree + 跨三子期間 robustness + T-2/T+0 預告. Supabase synced via feed-sync --apply (updated=1).

**Prepared 2026-04-19 20:07 UTC** as agent brief for **event_article** dispatch tomorrow (2026-04-20 UTC = 2026-04-21 CST, T-7 window for FOMC 2026-04-28/29).

## Event Overview

**FOMC 2026-04-28/29** (2-day meeting). Decision announced 2026-04-29. Today=2026-04-19 UTC → FOMC in 9-10 days.

**T-series windows** (per `.claude/rules/publish-checklist.md`「事件驅動文章配額」):
- **T-7 = 2026-04-21** ← **THIS MEMO target**
- T-2 = 2026-04-26
- T+0 = 2026-04-28 (or 04-29)
- T+1 = 2026-04-30 (optional)

**Already published** (pre-T-7 early window, 2/3-4 budget used):
- `mile_78d649c4` 2026-04-17 (T-12 FOMC 前瞻 Powell 盯嘴 94.8% 不降息)
- `mile_f7bc6e6a` 2026-04-18 (T-11 VT 保險 + |報酬| 加碼 28% + VIX 54 percentile)

**Remaining budget**: T-7 + T-2 + T+0 + (T+1 optional) — **3-4 slot remaining**

## T-7 Preview Brief（agent 執行時讀）

### Topic angle (differentiation 關鍵)

前 2 篇都聚焦「94.8% 不降息」+ VT 保險不啟動 framing。T-7 切換主題軸：

1. **歷史基線**：過去 20 年 FOMC 前 7 天 SPY 波動率 pattern（mean-reversion vs pre-announcement drift）
2. **2026 對比**：目前 VIX 16-18（低波動），符合「94.8% 不降息」的 expected quiet regime
3. **風險 asymmetry**：若 surprise cut（4.2% 機率）— VIX 往哪方向？過去案例估計
4. **具體 actionable**：T-7 到 T+0 的 position sizing schedule（不是事件減倉，是 normal-size 維持；若 VIX >25 才需調整）

### Data sources

- yfinance SPY + VIX 2005-2026 daily（for FOMC day isolation）
- `experiments/k185/` FOMC vol effect baseline (若存在，先確認)
- `storage/sentiment/` FOMC calendar 若有
- FedFutures futures implied probability （WebSearch verify at dispatch time）

### Structure (1500-2000 CJK, general audience 或 research)

1. **Intro**: 9 天後 FOMC，讀者該關心什麼？
2. **T-7 的意義**: 過去 20 年 FOMC 前 7 天 SPY/VIX pattern 統計（表格）
3. **2026 對比 2024-2025 vs 2023 降息週期**: 現在哪個更接近
4. **94.8% 不降息情境**: 若真不降息（basecase），post-announcement vol 預期
5. **4.2% surprise cut 情境**: VIX 爆漲 vs 股市 rally 的 2023 7 月案例對比
6. **T-7 → T+0 position sizing recommendation**: 不動 / 減半 / 加碼 的實戰規則
7. **T-2 和 T+0 會寫什麼**（預告下 2 篇）

### Charts needed (2 real)

1. 過去 20 年 FOMC 前 7 天 SPY daily return distribution box plot（event day T-6/-5/.../-1/0 by calendar）
2. VIX regime prob heatmap：當前 VIX level vs fut implied prob 的 2x2 decision matrix

## Hard rules (dispatch 時 agent briefing template)

- **event-driven → status=`published` 立即發**（不進 draft pool）
- 2000+ CJK (research) 或 1500+ CJK (general) — 此篇適合 **research** audience（數據驅動 historical baseline）
- 2 real matplotlib charts 上傳 Supabase
- tags: `FOMC`, `2026-04-28`, `T-7`, `event-driven`, `VIX`, `SPY`, `風險管理`, `研究`
- 標題含「FOMC 04/28-29」+「T-7」保持可搜尋
- 禁止重複 mile_78d649c4 / mile_f7bc6e6a 的 94.8% 不降息 framing — 本篇主軸是 **歷史 T-7 pattern + 2026 regime 對比**
- 結尾預告下 2 篇（T-2 + T+0）

## Dispatch when

- **2026-04-21 CST 01:00 UTC 前後**（台灣時間 09:00+）
- OR 若用戶 explicit request

## Cross-reference

- Historical FOMC analysis:
  - `mile_fa23c3b2` 2026-04-02「事件減倉反直覺代價：FOMC/NFP/CPI 避險全面劣於被動」
  - `mile_7012b52a` 2026-04-02「FOMC 前先賣股？少賺 3.5%」
  - `mile_027b6ad8` 2026-03-24 K185「FOMC 波動率效應」
- 近期 FOMC 前瞻：
  - `mile_78d649c4` 2026-04-17 T-12
  - `mile_f7bc6e6a` 2026-04-18 T-11

## Novelty guard

檢查避重：agent dispatch 前 grep feed.json 確認無 "T-7 FOMC" 或 "FOMC 前 7 天" 已存在。
