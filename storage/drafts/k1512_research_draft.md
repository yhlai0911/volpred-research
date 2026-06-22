---
title: "K1512：Double-ML 因子檢定顯示 ETF 層級沒有確認的非零效應"
audience: research
status: draft
tags: [DoubleML, factor-investing, MTUM, QUAL, VLUE]
experiment_refs: [K1512]
description: "K1512 以 DoubleMLPLR repeated cross-fitting 檢查 MTUM、VLUE、QUAL 的近一年自身動能能否解釋下一月相對 SPY 的超額報酬。三個 ETF 都未通過 Bonferroni-adjusted Newey-West gate，QUAL 的初始邊緣訊號在重複 cross-fitting 後消失。"
---

# K1512：Double-ML 因子檢定顯示 ETF 層級沒有確認的非零效應

[提出: research_program.md 期刊主題挖掘 batch，執行: Claude，Codex 審查]

## 摘要

K1512 檢查一個很窄的因子問題：在 ETF 層級，`MTUM`、`VLUE`、`QUAL` 過去一年自身報酬是否能解釋下一個月相對 `SPY` 的超額報酬。實驗使用 DoubleMLPLR partialling-out，把 VIX、term spread、上一月 `SPY` 報酬與上一月自身報酬列為控制項，並在 Codex review 後改用 repeated cross-fitting。

結果是 `CONDITIONAL_PASS`，但研究含義接近 null result。`MTUM`、`VLUE`、`QUAL` 的 Newey-West 95% 信賴區間都跨過 0，三個 Newey-West p-value 分別為 0.322、0.593、0.286，沒有任何一個通過 Bonferroni 門檻 0.0167。`QUAL` 在單次 cross-fitting 的初版曾出現邊緣負向訊號，重複切分後估計值縮小，t-stat 絕對值降到約一半。這個變化是本文的主要方法論資訊：小樣本 ETF 月資料上的 DML 結果對 fold randomness 很敏感。

![K1512 DML theta estimates with Newey-West confidence intervals](experiments/k1512/fig_a_dml_theta_with_ci.png)

## 研究問題

因子 ETF 常被當成可交易的風格暴露。動能、價值、品質各有長期資產定價文獻支持，但 ETF 層級的可交易問題更窄：投資人能否只靠某檔因子 ETF 的近期自身表現，在下一個月取得相對 `SPY` 的超額報酬。

K1512 把 treatment 定義為 ETF 在月份 t 的 trailing-year return，outcome 定義為下一個月份的 ETF return minus `SPY` return。這個設計把問題限制在月頻、ETF 層級、next-month relative performance。它不檢驗完整的股票橫斷面因子溢酬，也不宣稱可替代 Fama-French 或 characteristic-sorted portfolio 的標準檢定。

這個限制很重要，因為 ETF 層級樣本很短。`MTUM` 與 `VLUE` 的可用估計樣本是 2014-04-30 到 2026-04-30，共 145 個月；`QUAL` 是 2014-07-31 到 2026-04-30，共 142 個月。對月頻 DML 來說，這是探索性樣本，不適合用單次切分的顯著性直接支撐強結論。

## 方法

實驗使用 DoubleMLPLR with RandomForestRegressor nuisance learners。Nuisance learner 設定為 `n_estimators=100`、`max_depth=4`、`min_samples_leaf=5`，避免在 142 到 145 筆月資料上放任樹模型過度擬合。Cross-fitting 使用 `n_folds=2` 並重複切分，隨機種子固定為 42。

控制變數包含四項：月末 `^VIX`、term spread、上一月 `SPY` 報酬、上一月自身 ETF 報酬。結果檔記錄 `term_spread_available=false`，因為本次執行的 FRED 端點失敗，term spread 在流程中退回常數 0。這使宏觀利率斜率控制失效，是解讀結果時需要保留的限制。

Lookahead policy 採用 next-month outcome：`Y` 由下一月報酬建立，報酬控制項使用上一月資訊。VIX 與 term spread 是同月份月末控制，若轉成交易策略，執行時點必須在月末資料可觀測之後。本文把 K1512 當成因子機制檢查，不把它當成即時交易規則。

標準誤使用 DML influence score 的 Newey-West 修正，並檢查多個 lag 設定。主要 gate 使用 Newey-West 結果，三個 ETF 同時檢定時用 Bonferroni-adjusted alpha = 0.0167。Per-factor pass 條件要求 Bonferroni pass 且 Newey-West 95% CI 不含 0。

## 結果

三個 ETF 的估計方向不同，但統計結論一致：沒有確認的非零 effect。

| ETF | n | theta_hat | NW SE | NW t | NW p | NW 95% CI | verdict |
|---|---:|---:|---:|---:|---:|---|---|
| `MTUM` | 145 | 0.0164 | 0.0166 | 0.990 | 0.322 | [-0.0161, 0.0489] | NULL |
| `VLUE` | 145 | 0.0178 | 0.0333 | 0.534 | 0.593 | [-0.0474, 0.0830] | NULL |
| `QUAL` | 142 | -0.0065 | 0.0061 | -1.066 | 0.286 | [-0.0186, 0.0055] | EXPLORATORY_SIGNAL |

`QUAL` 的 `EXPLORATORY_SIGNAL` label 來自方向與 t-stat 的弱訊號，不代表通過多重檢定。三個 p-value 都高於 0.0167，Bonferroni gate 全部失敗。OLS 對照也沒有支持非零效果：`MTUM` p=0.609、`VLUE` p=0.460、`QUAL` p=0.261。

![K1512 p-value gate after Bonferroni correction](experiments/k1512/fig_b_pvalue_gate.png)

第二張圖把 Newey-West p-value 放在同一個 gate 下。若研究者只看未校正 p-value，`QUAL` 初版的單次 cross-fitting 結果可能會被誤讀成可討論的邊緣顯著；在三個因子同時搜索的設定下，這種解讀過度樂觀。K1512 採用的 gate 要求每個 ETF 都承受相同的 multiple-testing penalty。

## Codex review 後的主要修正

Codex review 指出五個需要修正或揭露的點：VIX 與 term spread 是 same-date controls；2-fold DML 在小樣本上只能作探索；Newey-West influence score 應 mean-center 並回報 lag sensitivity；原始 aggregate verdict gate 對 Bonferroni correction 太寬；sample metadata 應以每個 DML estimation frame 為準。

主線程修正後，`k1512.py` 把 cross-fitting 從單次改為 repeated cross-fitting，對 influence score 做 mean-centering，新增 NW lag sensitivity，移除過寬的 `PASS_PRELIMINARY` gate，並把 sample period 改成 per-factor metadata。修正後沒有任何 factor 通過 Bonferroni gate，aggregate verdict 降為 `CONDITIONAL_PASS`。

最關鍵的是 `QUAL`。初版單次 cross-fitting 看起來像品質 ETF 的短期均值回歸。Repeated cross-fitting 後，theta 變成 -0.0065，NW t = -1.066，p = 0.286。這說明原始訊號高度依賴資料切分。對只有 142 個月的 ETF 樣本，fold randomness 本身就是一個需要報告的結果。

## 解讀

K1512 沒有否定因子投資，也沒有否定動能、價值、品質在股票橫斷面上的長期文獻。它只檢查 ETF 層級的 next-month relative return。此處的 treatment 是 ETF 自身 trailing-year return，並非個股 characteristic、portfolio sort、或 firm-level exposure。

在這個窄設定下，K1512 的證據支持兩個較保守的判斷。第一，`MTUM`、`VLUE`、`QUAL` 的近期自身表現不能被當成下月打敗 `SPY` 的穩健訊號。第二，小樣本 DML 應把 repeated cross-fitting、multiple-testing gate、HAC 標準誤列為基本防線；單次 fold 的邊緣顯著不應直接進入研究結論或策略 registry。

對後續研究，較合理的延伸有三條。第一，回到股票橫斷面資料，用 firm-level characteristics 建立更接近因子文獻的 treatment。第二，測試 blocked 或 time-ordered cross-fitting，降低隨機 fold 對時間序列估計的干擾。第三，補回 term spread 資料源，並加入 VIX regime subsample，檢查品質與價值效果是否只在壓力區間出現。

## 結論

K1512 的結論應寫成 null-biased conditional pass：實驗流程經 Codex review 後更穩健，但三個 ETF 的效果沒有通過嚴格 gate。`QUAL` 的初始負向訊號在 repeated cross-fitting 後消失，提供一個具體例子：在短月頻樣本上，DML 的 model selection 與 fold split 可以把弱訊號放大成看似可發表的結果。

資料來源：`experiments/k1512/k1512.py` 與 `experiments/k1512/k1512_results.json`。市場資料來自 yfinance（`MTUM`、`VLUE`、`QUAL`、`SPY`、`^VIX`）；FRED term spread 於本次執行不可用，流程以常數 0 fallback。圖表為 `experiments/k1512/fig_a_dml_theta_with_ci.png` 與 `experiments/k1512/fig_b_pvalue_gate.png`。隨機種子固定為 42。
