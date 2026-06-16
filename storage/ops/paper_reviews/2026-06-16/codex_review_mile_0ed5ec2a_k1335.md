# Codex Source-Code Review - mile_0ed5ec2a / K1335

- **Article**: VIX 切太早，反而吃掉報酬：用 VIX 期限結構斜率重新校準「保守 VT」
- **Published**: 2026-06-15 03:18 UTC
- **Experiment**: `experiments/K1335/K1335.py`
- **Results**: `experiments/K1335/K1335_results.json`
- **Review timestamp**: 2026-06-16 10:35 台灣時間
- **Verdict**: **CONDITIONAL_PASS**

## Verdict

`CONDITIONAL_PASS` - 核心表格、OOS 期間、lag、成本口徑與 `CONDITIONAL_PASS` caveats 大致對得上 source/result；不需 retract。需要補一個 footnote/edit，修正兩個 unsupported/inaccurate reader-facing 敘述，並把「best slope」是 OOS 三選一講得更明確。

## Lookahead Audit

- **No material lookahead found.**
- `experiments/K1335/K1335.py:130-138`: `signal_vix_level` 用 `df["VIX"].shift(1)`；`signal_slope` 用 `(VIX/VIX3M).shift(1)`。
- `experiments/K1335/K1335.py:75-85`: 回測假設 weights 已 lag，`pnl_t = w_t * SPY_ret_t - tc * |Δw_t|`。
- `experiments/K1335/K1335.py:334-348`: strategies 在 full df 產生後只切 OOS 評估；OOS PnL 仍使用 lagged signal。
- `experiments/K1335/K1335.py:276-285`: regime-return plot 也用 lagged slope/VIX bucket。

## Claim Consistency

- **Table numbers match results.**
  - Article lines 21-29 match `K1335_results.json:22-24,42-105,127-132`: OOS 2018-01-01 to 2026-06-13, `n=2123`, yfinance, seed 42, `tc_per_side=0.001`.
  - Buy & Hold: ann_ret 16.8%, vol 19.2%, Sharpe 0.81, MDD -33.7%.
  - VIX level th=22: ann_ret 6.1%, Sharpe 0.54, MDD -23.0%, turnover 14.72.
  - Slope 1.05: ann_ret 15.5%, Sharpe 0.92, MDD -24.5%, Calmar 0.63, turnover 5.0.
- **Caveats are disclosed.**
  - Article lines 3, 65, 67, 75 disclose bootstrap p=0.096, Bonferroni p≈0.29, `CONDITIONAL_PASS`, IS-tuning asymmetry, and `tc_per_side_not_round_trip`.
  - These match `K1335_results.json:116-136,149-153`.

## Findings

1. **修字：article line 37 的「9% 的報酬差」不等於 source result。**
   - Source: B&H CAGR 16.762% vs slope_1_05 CAGR 15.454% (`K1335_results.json:43,94`)。
   - 差距是 **1.31 percentage points**，或約 **7.8% relative CAGR gap**，不是 9%。
   - MDD 改善是 -33.717% 到 -24.496%，約 **9.22 percentage points**，這部分接近 9pp。
   - 建議改成：「用約 1.3 個百分點的年化報酬差，換約 9.2 個百分點的最大回檔改善。」

2. **修字/補來源：article line 57 的「過去 16 年大概只出現過 50-60 次」不在 results JSON，且同口徑重算不符。**
   - 依同 tickers/date range 重算 `VIX/VIX3M >= 1.05`：
     - full 2010-01-01 to 2026-06-13: **115 trading days**, **36 episodes**。
     - OOS 2018-01-01 to 2026-06-13: **75 trading days**, **21 episodes**。
   - 50-60 既不像 days，也不像 episodes。建議刪掉或改為：「OOS 只出現 75 個交易日、約 21 段 episode。」
   - 若要保留，應把 active-day/episode count 寫入 `K1335_results.json`，避免文章有不可追溯數字。

3. **修字：article line 45 的「2025 末的修正」日期不精準。**
   - 同 SPY OOS 口徑重算，2025 年 B&H drawdown 低點在 **2025-04-08**，不是 2025 年末。
   - 建議改為「2025 年春季/4 月修正」或直接寫「2025 修正」。

4. **Overclaim caveat：`slope_1_05` 是 OOS 三個 slope 閾值中的 best-by-OOS-Sharpe。**
   - Source: `experiments/K1335/K1335.py:355-357` 用 `max(slope_names, key=OOS sharpe)` 選 `best_slope_name`。
   - Article line 19 有說同時測 0.95/1.00/1.05，lines 65-67 有 Bonferroni/multi-test caveat，所以不是 FAIL。
   - 但 line 35「真正有意思的是 1.05」與 line 63「方向性優勢」建議補一句：「1.05 是三個 OOS slope 閾值中表現最好的版本，未經多重比較校正不能視為已證實最佳規則。」

5. **Baseline/DM caveat：article 沒有跑 slope_1_05 vs Buy & Hold 的 Sharpe-diff test。**
   - Source bootstrap 只測 best slope vs tuned VIX level (`experiments/K1335/K1335.py:361-366`)。
   - Article 使用 B&H 做數字對照是合理的，但不要把 `Sharpe 0.92 vs 0.81` 寫成 formal significant outperformance。現文大致沒有這樣寫；維持現有強度即可。

6. **Experiment README stale text：`README.md:44` 寫 `th = 20`，但 source/results/article 都是 IS tuned `th=22`。**
   - 這不是文章錯誤，但應改 README，避免下游 agent 誤讀。

## TX/Baseline Audit

- **TX**: source 與文章一致，`tc_per_side=0.001`，用 `0.001 * |w_t - w_{t-1}|` 扣成本 (`K1335.py:41,83-84`)。文章也揭露需重跑 round-trip/honest TC，沒有隱瞞。
- **Baseline**: B&H 有列入，且文章沒有只拿弱的 VIX-level baseline 來包裝結論。比 K698 的 baseline 風險低。
- **Remaining risk**: 成本語意應在 rerun 中改成更明確的 `cost_per_unit_traded`，並做 5/10/20 bps sensitivity；目前不影響「文章與 source 一致」的主要判斷。

## Required Fixes

**Article-only immediate edits**

1. line 37: `9% 的報酬差` -> `約 1.3 個百分點年化報酬差 / 9.2 個百分點 MDD 改善`。
2. line 57: remove `50-60 次` or replace with active-day/episode count after writing it into results.
3. line 45: `2025 末` -> `2025 年春季/4 月` or `2025 修正`。
4. line 35/63 nearby: add that slope_1_05 is OOS best among three fixed slope thresholds and does not survive Bonferroni.

**Code/results rerun fixes**

1. Add active-day and episode counts for each slope threshold to `K1335_results.json`.
2. Add bootstrap/SPA-style comparison versus Buy & Hold if future article claims B&H outperformance.
3. Fix `experiments/K1335/README.md:44` stale `th = 20` wording.
4. Rerun with explicit cost sensitivity and unambiguous cost naming.

## Retract Decision

- **Retract**: no.
- **Footnote/edit**: yes, required.
- **Do nothing**: no, because article contains at least two reader-facing numeric/date inaccuracies not supported by source results.
