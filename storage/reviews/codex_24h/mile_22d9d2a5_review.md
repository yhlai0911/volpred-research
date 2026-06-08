# Codex 24h Review — mile_22d9d2a5 (K1407)

- **Article**: 定期定額的報酬率，什麼時候被高估、什麼時候被低估
- **Draft source**: `storage/reports/feed.json` (`mile_22d9d2a5`)
- **Task**: `paper_review_mile_22d9d2a5`
- **Reviewed**: 2026-06-08 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **CONDITIONAL_PASS**

## 結論摘要

這篇的核心教育重點是對的，而且 `K1407` 的方法與大多數主數字都對得上 source：DCA 下 TWR 與 IRR 會分歧、方向取決於路徑、單筆投入 IRR= CAGR，這些都成立。

問題出在前言有一句把台灣市場的方向講反。文章原文寫「平台高估了你的成績，而且台灣投資人特別容易碰到那個情況」，但 `K1407` 的 0050 結果是 16/16 個進場年份都屬於 **TWR 低估 IRR**，完全沒有高估反例。高估反例只出現在 SPY 的 2019 與 2023 兩個進場年份。

因此這篇不需要整體退稿，但需要把前言改正，避免讀者在還沒讀到中段表格前就先收到錯誤方向。

## Numeric verification

下列主數字已對上 `experiments/k1407/k1407_results.json`：

| Claim | Source | Match |
|---|---|---|
| 0050：16/16 年都是 IRR > TWR | `assets["0050.TW"].summary.twr_lt_irr_count=16`, `twr_gt_irr_count=0` | ✓ |
| 0050 中位數差距 9.2 pp | `twr_minus_irr_pp_median=-9.1674` | ✓ |
| 0050 2022 差距 19.5 pp | `2022.dca.twr_minus_irr_pp=-19.4961` | ✓ |
| SPY：18 年 IRR > TWR、2 年 TWR > IRR | `twr_lt_irr_count=18`, `twr_gt_irr_count=2` | ✓ |
| SPY 反例是 2019 / 2023 | `2019=+0.2816`, `2023=+0.5077` | ✓ |
| 路徑診斷相關係數 +0.56 | `verdict.corr_earlyMinusLate_vs_twrMinusIrr=0.5622` | ✓ |
| 單筆投入 36/36 都 IRR = CAGR | `lump_sum.irr_equals_cagr=true` for all 36 entries | ✓ |

## Findings

1. **Intro overstates the Taiwan direction and conflicts with source** — `storage/reports/feed.json` article intro, `experiments/k1407/k1407_results.json`

   原文寫：
   - 「多數情況下，平台秀的數字低估了你的真實年化；但有一種情況是反的，平台高估了你的成績，而且台灣投資人特別容易碰到那個情況。」

   但 source 顯示：
   - `0050.TW`: `twr_gt_irr_count = 0`, `twr_lt_irr_count = 16`
   - `SPY`: `twr_gt_irr_count = 2`（2019、2023）

   也就是說，本樣本裡「平台高估」不是台灣更常見，反而只出現在 SPY。這屬於 reader-facing direction error，不是語氣問題。

2. **Core thesis remains valid after correction** — `experiments/k1407/k1407.py:167-227`, `experiments/k1407/k1407.py:364-411`

   DCA 的 TWR 因子鏈、IRR 求法、路徑機制診斷都自洽；文章其餘主段落與結果一致。修正前言後，整篇主論述可成立，不需要下架。

## Lookahead audit

- PASS — 這是歷史描述性分析，不是預測回測，沒有 signal-at-t × return-at-t 類型的 tradable lookahead 問題。
- PASS — DCA IRR 用實際投入現金流與期末市值解年化 IRR；單筆投入則單獨驗證 `irr_equals_cagr`，見 [k1407.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1407/k1407.py:141)。
- PASS — 路徑診斷只用同一持有期內的前半/後半累積報酬做 ex-post 解釋，沒有偷帶未來資訊到交易規則。

## Action taken

1. 已把文章前言改成與 source 一致的版本。
2. 已在 `details.errata_24h_review` 記錄本次 24h review 與修正內容。

## Recommended follow-up

1. 若之後有同步流程，應把這次更正推到對外前台版本。
2. 未來這類 reader-facing IRR/TWR 文，前言先用 per-asset summary 自動生成，避免把 pooled 直覺寫成資產別結論。
