# Codex 24h Review — mile_778a9b85 (K1117)

- **Article**: 市場最恐慌那幾天，我們還是沒找到另類數據的增量價值
- **Task**: `paper_review_mile_778a9b85`
- **Reviewed**: 2026-06-04 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **PASS**

## Summary

這篇文章和 `K1117` source 基本對齊，核心結論也守住了證據邊界。VIX jump 定義明確採用 `shift(1)` 防 lookahead，主樣本 `181` 個 jump days、`156` 個 matched controls、`113` 組正式 paired tests 都和 results 一致；六個另類指標在 jump-day、control-day、以及 interaction test 全部未過關，文章沒有把這個 NULL 講成「永遠沒用」，而是準確表述成「在這組資料與這個設計裡沒看到增量價值」。

## Numeric verification

下列主張與 `experiments/k1117/k1117_results.json` 一致：

| Draft claim | Source | Match |
|---|---|---|
| 樣本期間 2010-01-05 至 2025-12-30 | `period` | ✓ |
| jump-day 定義用前一日資訊的 252 日 rolling sigma | `k1117.py:218-234` | ✓ |
| jump days = 181 | `jump_counts.primary_2sigma` | ✓ |
| matched = 156 | `match_quality.n_matched` | ✓ |
| usable formal pairs = 113 | `tests` table + README summary | ✓ |
| 最佳 jump-day 挑戰者 VVIX，DM t = 1.35 | `tests.vvix.H1_DM_t` | ✓ |
| 次佳 WLEMU，DM t = 1.21 | `tests.WLEMU.H1_DM_t` | ✓ |
| control-day 最大 t = 0.56 | `tests.WLEMU.H2_DM_t` | ✓ |
| 全體 verdict = FULL_NULL | `verdict` | ✓ |

## Findings

1. **Core claim is source-aligned and appropriately conservative** — `/tmp/mile_778a9b85.md:23-30`, `experiments/k1117/k1117_results.json`
   文章把六個 alt-data 在 jump days 都未跨過研究採用的嚴格門檻，並指出 interaction test 也失敗，這和 source 完全一致。`max H1 t = 1.35`、`max H2 t = 0.56`、所有 H3 BH-p 都遠高於顯著水準，支撐「沒有穩定增量價值」這個結論。

2. **Lookahead control is explicitly and correctly described** — `/tmp/mile_778a9b85.md:13`, `experiments/k1117/k1117.py:221-226`
   文中點出 jump-day 門檻是用「前一天資料算出的 252 日滾動標準差」，並明講 `shift(1)` 的目的。這和 source implementation 完全一致，是這篇最重要的 methodological honesty 段落之一。

3. **Sample-size wording is acceptable, but one sentence could be more precise** — `/tmp/mile_778a9b85.md:15`, `/tmp/mile_778a9b85.md:38`
   文中先交代 `181` 個 jump days、`156` 天配對成功、`113` 組正式檢定，主敘事並沒有隱藏有效樣本縮水。  
   只有第 38 行「只挑市場最不平靜的那 181 天來看」若要更嚴格，可補一句「正式 matched-pair inference 以 113 組可用事件對為主」，避免讀者把 regime identification 和 final inferential sample 混成同一件事。

4. **Narrative stays within evidence bounds** — `/tmp/mile_778a9b85.md:42-58`
   文章沒有把單一 null result 上升成「另類數據永遠沒用」，而是限定在 SPY 短期波動、這組變數、這個 matched-pair 設計。限制段也有清楚承認：事件是用 VIX jump 定義，不是用 alt-data 自己的 jump 定義；且樣本只有 113 組 usable pairs。這樣的 caveat 強度足夠。

## Lookahead audit

- PASS — jump threshold uses `dvix.shift(1).rolling(252).std()`，沒有 same-day leakage，見 [k1117.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1117/k1117.py:218)。
- PASS — matched controls 排除了 jump day 前後 `±5` 天，並對 month / VIX level / weekday 做配對，沒有明顯 selection bug，見 [k1117.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1117/k1117.py:241)。

## Recommended tweaks

1. 把「只挑市場最不平靜的那 181 天來看」微調成「先識別 181 個 jump days，再以其中 113 組可用 matched pairs 做正式檢定」，敘述會更精確。
2. 若要再強一點，可以在圖 2 或限制段順手補一句「BH-adjusted multiple testing 後依然全數不顯著」，讓讀者更清楚這不是只靠單一 t 值判斷。
