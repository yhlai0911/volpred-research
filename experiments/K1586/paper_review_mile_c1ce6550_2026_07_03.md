# K1586 — 24h-of-publish Codex review (mile_c1ce6550)

- **Task**: `paper_review_mile_c1ce6550` (Codex 24h-rule)
- **Reviewer**: Codex (`codex exec`, gpt-5.4) — 2026-07-03
- **Article**: 「USDC 脫鉤那 5 天：1-3 年短券波動率飆 2.8 倍，1-3 個月卻沒事」 (published 2026-07-02)

## Verdict: CONDITIONAL_PASS

The core computation is reproducible and the headline `2.83x` / `1.17x` numbers match
`K1586_results.json`, but the public article needs wording fixes before the result is
methodologically clean: the event window is `ED±5` business days (11 observations), not
"that 5 days", and the causal duration/fire-sale interpretation is stronger than the
single-event evidence can support.

## Checks

| Focus | Conclusion |
|---|---|
| Event window | CONDITIONAL — code/README define a symmetric `ED-5..ED+5` event window and symmetric `[ED-30, ED-6] ∪ [ED+6, ED+30]` controls, but the article title/table/body call this "5 days"; actual `event_n=11`. |
| `2.8x` calculation | PASS with caveat — numerator/denominator use the same mean absolute daily log-return bps proxy within SHY, with no annualization mismatch; H2 is not a 22d rolling RV statistic. |
| SHY vs BIL comparison | PASS as a maturity-split association; CONDITIONAL as mechanism — SHY and BIL ratios are within-instrument event/control ratios, so the 2.83x is not mechanically caused by comparing different duration vol levels, but attributing the split to USDC reserve liquidation is not identified. |
| Statistical significance | CONDITIONAL — Welch + Bonferroni and seeded block bootstrap pass for SHY, BIL is null; still a single event without CI/placebo stress-event comparison, so it cannot be generalized as a stablecoin transmission law. |
| Claim vs evidence | CONDITIONAL — article numbers match JSON and "1-3 months quiet" is supported; article wording overstates the event-window length and causal channel. |
| Seed / sample / sources | PASS — seed, sample, and public data sources are recorded. |

## Findings

1. **Must fix — article event-window wording is wrong/misleading.** The experiment defines `EVENT_WIN = 5` as `ED ± 5` (`experiments/K1586/K1586.py:57`-`60`) and slices `event_idx - EVENT_WIN` through `event_idx + EVENT_WIN + 1` (`experiments/K1586/K1586.py:310`-`317`); README states this is 11 business days (`experiments/K1586/README.md:65`-`68`) and results record `event_n=11` for both SHY/BIL (`experiments/K1586/K1586_results.json:212`-`219`, `:233`-`:235`), but the article title/table/body say "那 5 天" / "脫鉤 5 天" (`storage/reports/feed.json:848`-`850`).

2. **Must fix — causal duration/fire-sale language exceeds identification.** K1586 observes SHY/BIL absolute-return differences around the SVB/USDC event (`experiments/K1586/K1586.py:296`-`364`); it does not use Circle reserve holdings, Treasury flow data, placebo banking-stress controls, or other depeg events, while the article says USDC reserve composition concentrated pressure in 1-3 year bonds and "SHY 被壓到了" (`storage/reports/feed.json:850`). This should be phrased as "consistent with a duration channel during the SVB/USDC event", not as identified stablecoin selling pressure.

3. **Non-blocking caveat — statistical evidence supports the event contrast, not a rule.** SHY passes Welch/Bonferroni and block bootstrap (`experiments/K1586/K1586_results.json:217`-`230`; gate at `experiments/K1586/K1586.py:414`-`430`), and BIL is clearly null (`experiments/K1586/K1586_results.json:233`-`247`), but no confidence interval for the ratio, placebo windows, or cross-event stress comparison is recorded. The article should keep the claim at single-event event-study strength.

4. **No issue — the `2.83x` and BIL-null numbers match the experiment.** SHY is 37.2406 / 13.1759 = 2.8264 (`experiments/K1586/K1586_results.json:217`-`230`), and BIL is 2.2825 / 1.9490 = 1.1711 with Bonferroni/bootstrap p-values not significant (`experiments/K1586/K1586_results.json:233`-`247`). "1-3 個月卻沒事" is numerically supported if stated as "not statistically significant".

5. **No issue — reproducibility metadata is present.** Results record `seed=42`, `2020-04-06` to `2026-06-26`, `n_business_days=1557`, and DefiLlama/FRED/yfinance sources (`experiments/K1586/K1586_results.json:1`-`19`).

## Required fixes

- Revise public article title/table/body from "那 5 天" / "脫鉤 5 天" to "SVB/USDC 事件前後 ±5 個交易日（11 個交易日事件窗）".
- Replace causal wording such as "SHY 被壓到了" and unsupported reserve-bucket language with "SHY showed a significant event-window increase; this is consistent with, but does not identify, a duration channel."
- If the article wants to retain forward-looking language about future depegs, add sensitivity/placebo evidence or explicitly label the inference as single-event and descriptive.

## Resolution — fixes applied & live (2026-07-03, hourly-21)

前輪只留下 review + required fixes，未套用。本輪主線程套用全部必修並上線（研究誠實 §6 回溯更正）：

1. 標題/描述：「脫鉤那 5 天…波動率飆」→「脫鉤那幾天…日波動飆」。
2. 事件窗正名：內文+表頭寫「事件窗 = 脫鉤日 ±5 交易日、共 11 天」，對照組 ±30 交易日（排除事件窗）。
3. Metric 正名：H2「波動」= 每日絕對變動幅度(bps) 波動代理，與 H1 滾動月度 RV 明確區分。
4. 移除事實錯誤前提「USDC 儲備集中 1-3 年期公債」（Circle 儲備以 <3mo bills+repo 為主），因果段改寫成「一個開放問題」（duration 機械效應 vs 儲備賣壓兩候選，明講後者證據不足）。
5. 加單事件 caveat（n=1、無跨事件 CI/placebo、因果不可識別）。

**流程**：feed.json(canonical) → `sync-all` → Supabase 上線。**線上驗證** `GET /rest/v1/articles?slug=eq.mile_c1ce6550` → title 已更新。anti-ai-gate PASS。README H2 摘要行同步軟化。

