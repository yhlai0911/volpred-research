# Next Draft Candidate: FOMC 04/28-29 T-2 Preview (Event-Driven)

**Prepared 2026-04-20 03:24 UTC** as agent brief for **event_article** dispatch around 2026-04-26 CST morning (UTC 2026-04-26 ≈ T-2 window for FOMC decision 2026-04-28/29).

## Event Overview

**FOMC 2026-04-28/29** (2-day meeting). Decision announced 2026-04-29 US market afternoon ≈ 2026-04-30 CST morning. Today=2026-04-20 UTC → FOMC in 8-9 days.

**T-series windows** (per `.claude/rules/publish-checklist.md`「事件驅動文章配額」):
- ~~T-12 = 2026-04-17~~ ← `mile_78d649c4` 94.8% 不降息、盯 Powell
- ~~T-11 = 2026-04-18~~ ← `mile_f7bc6e6a` VT 保險 + \|報酬\| + VIX 54pct
- ~~T-7 = 2026-04-20~~ ← `mile_a0dccb21` 20 年 173 場 FOMC / 會前 5 天 no vol build-up / 2010/2016/2019 regime match
- **T-2 = 2026-04-26 CST 晨** ← **THIS MEMO target**
- T+0 = 2026-04-29 US afternoon / 2026-04-30 CST 晨
- T+1 = 2026-04-30 (optional)

**配額現況**：一事件 3-4 篇 cap。已用 3 篇 (T-12/T-11/T-7)，剩 **1-2 slot** = T-2 必寫、T+0 必寫、T+1 optional。

## T-2 差異化主題軸

T-7 已用「20 年 173 場 FOMC 歷史 baseline + regime match」。T-12/T-11 已用「94.8% 不降息 expected quiet」。T-2 必須換軸：

### 主軸候選（選一，agent dispatch 時決定）

**候選 A（推薦）**：Scenario-conditional 具體數字預期
- 94.8% hold 情境：post-announcement SPY/VIX 1-day move distribution（過去 20 年 hold 場次）
- 4.2% surprise cut 情境：post-announcement SPY/VIX 1-day move（過去 4-5 場 dovish surprise: 2019 Q3, 2020 emergency, 2024 Sep -50bp outcut）
- 5-σ tail cut-100bp 情境（極低機率）：COVID-2020 emergency 參考
- 具體 number grid：hold → SPY ±0.3%, VIX −1pt; dovish cut → SPY +1.2%, VIX −2pt; hawkish hold → SPY −1.5%, VIX +3pt

**候選 B**：Fed Funds futures implied path vs dot plot gap
- 04-29 單次 meeting 之外，市場 implied 2026 年底 rate path vs FOMC dot plot median 有多大 gap?
- Gap 大小過去與 VIX term structure 的關係
- 本次 dot plot 更新 vs market expectations 的 narrative risk

**候選 C**：Event-day position sizing (T-2 → T+0 tactical)
- 根據 mile_fa23c3b2 結論（event trimming 劣於 buy-and-hold）強化主張
- T-2 到 T+0 不減倉的 explicit 規則 + 例外 trigger（e.g. IV 爆至 percentile 90+）
- 與用戶現有 VT / TAIFEX 策略的具體 action table

### Data sources

- yfinance SPY + ^VIX 2005-2026 daily（for 20 yr FOMC day isolation）
- FedFuturesFFR 2026-04-29 contract implied prob (WebSearch at dispatch time for up-to-date number — 現在 memo preparation 時 94.8% hold per T-12)
- FOMC historical decision log 2005-2026（internal `storage/sentiment/` if exists，否則 WebSearch official Fed meeting outcomes）
- `experiments/k185/` FOMC vol effect baseline（確認存在 + 讀 key stats）
- OIS curve for 2026 rate path（Bloomberg / CME FedWatch）

### Structure (2000+ CJK research audience 或 1500+ CJK general — 建議 general，時效導向)

1. **Intro**: 2 天後 FOMC 答案就揭曉。讀者該關心 3 個具體數字
2. **94.8% hold 情境**: 過去 20 年 hold 場次 1-day post-announce SPY/VIX 數字（具體表格 + distribution）
3. **4.2% surprise cut 情境**: dovish cut history 4-5 場 + VIX 反應（2019 Q3 / 2024 Sep / 2020 emergency）
4. **極端 tail**: >50bp cut 或 hike 100bp 的 regime triggers（機率 <1% 但 tail risk briefing）
5. **T-2 → T+0 position sizing**: 不減倉明確規則 + exception trigger
6. **T+0 會看什麼**: 發佈當天 watch checklist（dot plot, SEP, Powell press conf, Q&A）

### Charts needed (2 real matplotlib PNG 上傳 Supabase)

1. **Scenario-conditional SPY/VIX 1-day return box plot** — hold / dovish cut / hawkish hold 三組，y=return, dots overlay past 20 yr
2. **FFR futures implied prob curve** — x=meeting date (next 4 FOMC), y=implied cut prob, annotate current level + dot plot median

### Hard rules (dispatch 時 agent briefing template)

- **event-driven → status=`published` 立即發**（不進 draft pool）
- 2000+ CJK (research) 或 1500+ CJK (general) — 此篇建議 **general**（時效導向、具體數字讀者友善）
- 2 real matplotlib charts 上傳 Supabase
- tags: `FOMC`, `2026-04-28`, `T-2`, `event-driven`, `VIX`, `SPY`, `情境分析`, `position-sizing`
- 標題含「FOMC 04/28-29」+「T-2」或「會前 2 天」保持可搜尋
- **禁止重複**：
  - mile_a0dccb21 (T-7) 的「會前 5 天 no vol build-up」+「regime 匹配 2010/2016/2019」
  - mile_78d649c4 / mile_f7bc6e6a 的「94.8% 不降息」framing
  - mile_027b6ad8 K185 FOMC vol effect baseline（引用 OK，勿重寫）
- 結尾預告 T+0（發佈當天）

## Dispatch when

- **2026-04-26 UTC 清晨**（台灣時間 08:00-10:00，週日早上 CST）
- 主線程 ~2026-04-26 00:00 UTC 派 general-purpose agent，用此 brief

## Cross-reference

- FOMC series (published):
  - `mile_78d649c4` 2026-04-17 T-12
  - `mile_f7bc6e6a` 2026-04-18 T-11
  - `mile_a0dccb21` 2026-04-20 T-7 (latest, anchor for differentiation)
- Historical FOMC analysis:
  - `mile_fa23c3b2` 2026-04-02「事件減倉反直覺代價」← 本篇 position sizing 可引用
  - `mile_7012b52a` 2026-04-02「FOMC 前先賣股？少賺 3.5%」← 同上
  - `mile_64b710d3` 2026-03-17 FOMC-VIX 不可交易
  - `mile_c5abaed7` 2026-03-17 123 次會議 VIX 無信號

## Novelty guard

檢查避重（主線程 dispatch 前 3-layer dedup）：
- 層 1: `grep -i "T-2 FOMC\|會前 2 天\|FOMC 04/28.*T-2" storage/reports/feed.json | head` 應 0 hits
- 層 2: publication_candidates 查 "FOMC 情境" uncovered
- 層 3: 主題 matrix 本篇分配軸「**scenario-conditional number grid + position sizing**」(T-7 軸=歷史 baseline, T-11 軸=prob+VT 保險, T-12 軸=政策解讀)

## Memo status

- [x] T-2 brief prepared 2026-04-20 03:24 UTC
- [ ] Dispatch 2026-04-26 UTC 晨
- [ ] Mark CONSUMED when published
