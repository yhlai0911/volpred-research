---
title: "K1582：HARQ / SHARK-style 測量誤差修正 HAR-RV 的台指期日盤試驗"
audience: research
status: draft
phase: research
tags:
  - 波動率預測
  - HAR-RV
  - HARQ
  - QLIKE
  - 台指期
  - 高頻資料
  - 模型比較
experiment_refs:
  - K1582
image_url: experiments/k1582/figures/k1582_qlike_improvement.png
description: "K1582 以 TAIFEX TX active-contract 日盤五分鐘資料測試 HARQ 與 SHARK-style realized-measure 修正。TX_active 顯示 QLIKE 方向性改善，但未通過 Harvey |DM|>3 gate；SPY 與 0050.TW 只可作短樣本流程檢查。"
---

## 摘要

[提出: Claude, 執行: Claude] K1582 檢驗 realized quarticity 測量誤差修正與 signed intraday components，是否能改善標準 HAR-RV 的一步期 realized variance 預測。正式可判斷樣本是 TAIFEX TX active-contract 日盤，原始日資料 2,219 筆，樣本外預測 1,697 筆；SPY 與 0050.TW 只有 51 與 38 筆樣本外預測，本文將它們列為 pipeline diagnostics。TX_active 上，HARQ、HARQ_full、SHARK_like 的 QLIKE 都低於 HAR，其中 SHARK_like 改善 +2.05%，HARQ 改善 +1.94%。但所有候選模型都沒有通過 results.json `statistics.harvey_gate` 定義的專案 gate。整體 verdict 因此維持 `DIRECTIONAL_ONLY`。

## 研究背景

HAR-RV 的日、週、月 realized variance 架構來自 Corsi (2009)。Bollerslev, Patton and Quaedvlieg (2016) 的 HARQ 方向提醒我們：realized variance 本身有測量誤差，realized quarticity 可以作為測量誤差 proxy，讓 HAR 係數隨 measurement precision 調整。Buccheri and Corsi (2021) 的 SHARK-related 方向則鼓勵把 signed components、semivariance、jump-related realized measures 放進 HAR 周邊，檢查日內分解是否提供額外預測資訊。Patton and Zhang (2026) 的 bespoke realized volatility 觀點，也把 realized measure 視為設計選擇，重點在 forecast target 與 measurement-error problem 是否對齊。

K1582 的原始 backlog 假說更強：台指期夜盤 / 日盤微結構可能讓 realized measure 噪音比 SPY 更大，因此測量誤差修正應該更有幫助。本次實驗只完成可 gate 的 TX 日盤長樣本與兩個 2026 年短樣本流程檢查，尚未解決完整夜盤假說。

## 方法與數據

| 項目 | 設定 |
|---|---|
| 實驗 ID | K1582 |
| 核心問題 | RQ-based measurement-error interactions 與 signed intraday components 是否改善 HAR-RV 一步期 RV forecast |
| 主要 target | `RV_t`，由五分鐘 intraday returns 計算 |
| 主要 loss | Patton QLIKE，越低越好 |
| Pairwise test | `volpred.stats.model_evaluation.dm_test`，h=1；負的 DM t 代表 candidate QLIKE 低於 HAR |
| Gate | 依 results.json `statistics.harvey_gate`：candidate 必須同時有正的 QLIKE improvement、通過嚴格 DM 門檻，且留在 MCS |
| MCS | `volpred.stats.mcs.model_confidence_set`，alpha=0.10，n_boot=1000，seed=42 |
| 隨機種子 | 42 |
| Lookahead policy | 所有 daily / weekly / monthly predictors 都由 `.shift(1)` 後的 series 建立；expanding OOS 每列只用 forecast row 之前的訓練列 |

資料面分成三個市場：

| Market | Source | Raw date range | Raw days | Feature rows | OOS forecasts | Gateable? |
|---|---|---:|---:|---:|---:|---|
| TX_active | `~/Dropbox/TAIFEXDATA/TAIFEXDATA/python/Daily_*TX.csv`；以日盤成交量選 active contract | 2017-05-16 至 2026-06-29 | 2,219 | 2,197 | 1,697 | yes |
| SPY | `data/intraday/SPY_5min_2026-*.csv` | 2026-01-14 至 2026-06-29 | 113 | 91 | 51 | no |
| 0050.TW | `data/intraday/0050_TW_5min_2026-*.csv` | 2026-01-20 至 2026-06-26 | 100 | 78 | 38 | no |

TX_active 使用完整 `TX` 檔，不用 `TX1`，以避開近月 roll-gap 的已知問題。每個交易日篩日盤 08:45-13:45，依日盤成交量選 active contract month，再用五分鐘 last-tick bar 計算 realized measures。TX 的 median intraday return count 是 59。

## 模型規格

| Model | Features |
|---|---|
| HAR | `log RV_d`, `log RV_w`, `log RV_m` |
| HARQ | HAR + `log RV_d * sqrt(RQ_d) / RV_d` |
| HARQ_full | HAR + daily / weekly / monthly RQ measurement-error interactions |
| SHARK_like | HARQ + lagged semivariance shares、realized semivariance imbalance、signed jump share、absolute jump share |

`SHARK_like` 是 scoped approximation。它用 K1582 腳本能從本地資料穩定構造的 realized measures，近似 SHARK 類型的 rich realized-measure correction；它未完整複製 Buccheri-Corsi 的 full estimator。

## 核心發現一：TX_active 方向性改善存在，但沒有通過嚴格 gate

![K1582 QLIKE improvement vs HAR](experiments/k1582/figures/k1582_qlike_improvement.png)

TX_active 是唯一 gateable market。四個模型的 QLIKE 與 pairwise 統計如下：

| Model | QLIKE | QLIKE improvement vs HAR | DM t vs HAR | DM p | Harvey pass? | MCS status |
|---|---:|---:|---:|---:|---|---|
| HAR | 0.168677 | -- | -- | -- | baseline | eliminated in MCS at p=0.058 |
| HARQ | 0.165409 | +1.94% | -2.60 | 0.0094 | false | member |
| HARQ_full | 0.166079 | +1.54% | -2.25 | 0.0248 | false | member |
| SHARK_like | 0.165226 | +2.05% | -1.77 | 0.0766 | false | member |

MCS 在 alpha=0.10 下排除了 HAR，保留 HARQ、HARQ_full、SHARK_like。這個結果支持「realized-measure corrections 在 TX 日盤有方向性資訊」的說法。但專案 gate 不只看 MCS membership。候選模型還要通過 pairwise Harvey-style DM 門檻；HARQ 的 pairwise t=-2.60，SHARK_like 的 pairwise t=-1.77，都沒有過線。

研究口徑因此要保守：TX_active 不是 null，但也不是 PASS。更準確的分類是 `DIRECTIONAL_ONLY`。

## 核心發現二：SHARK_like 是 best QLIKE，但不是可宣稱的勝利

SHARK_like 的 QLIKE=0.165226，是 TX_active 四個模型中最低；相對 HAR 的改善是 +2.05%。若只看 point estimate，研究者很容易把這個模型寫成 winner。K1582 不這樣處理，原因有三個。

第一，pairwise DM t=-1.77，p=0.0766。方向有利，但統計強度低於 project gate。第二，HARQ 的 DM t=-2.60 比 SHARK_like 更強，雖然 QLIKE 改善略小。第三，HARQ_full 也在 MCS 內，改善 +1.54%，表示「加更多 RQ interaction」並未單調提高結果。這組 diagnostics 指向同一個結論：measurement-error correction 方向值得保留，模型層級排序還不穩。

這個結果也避免了另一種過度詮釋。`SHARK_like` 加入 semivariance shares 與 signed jump controls 後最佳，不能直接推論「jump 或 downside decomposition 是主要機制」。目前證據只說：把 RQ interaction 與 signed realized components 加在 HAR 周邊，TX 日盤 QLIKE 往好的方向移動。要識別機制，下一步需要 nested ablation、夜盤 / 日盤分層，並對 jump / semivariance 子項做穩健性檢查。

## 核心發現三：SPY 與 0050.TW 只能作流程檢查

![K1582 sample gate](experiments/k1582/figures/k1582_lazypack_2_sample_gate.png)

SPY 與 0050.TW 的 local 五分鐘資料只涵蓋 2026 年短區間，OOS forecast 數量分別是 51 與 38，低於 252 的 gateable minimum。K1582 將兩者標成 `INSUFFICIENT_DATA`，不把短樣本輸出當作跨市場推論。

| Market | Best by QLIKE | HAR QLIKE | HARQ improvement | HARQ DM t | SHARK_like improvement | SHARK_like DM t | Verdict |
|---|---|---:|---:|---:|---:|---:|---|
| SPY | HARQ | 0.328711 | +0.58% | -0.04 | -15.04% | +0.95 | INSUFFICIENT_DATA |
| 0050.TW | HAR | 0.231824 | -6.04% | +2.39 | -11.61% | +1.01 | INSUFFICIENT_DATA |

這兩組短樣本仍有工程價值。它們確認資料處理、feature construction、OOS loop、DM/MCS 評估可以跨市場跑通，也提醒後續研究不能拿短快照補足跨市場敘事。K1582 的正式結論只來自 TX_active。

## Lookahead 與 reproducibility 檢查

K1582.py 的 timing 設計有三層防線。

1. `add_forecast_features()` 先對 `rv`、`me`、`rs_minus_share`、`rs_imbalance`、`signed_jump_share`、`abs_jump_share` 做 `.shift(1)`，再建立 daily / weekly / monthly features。
2. Weekly 與 monthly features 是 lagged series 的 rolling mean，因此 row t 的 weekly feature 是 `t-5` 到 `t-1`，monthly feature 是 `t-22` 到 `t-1`。
3. `expanding_oos_forecasts()` 對第 `pos` 列 forecast 時，只用 `features.iloc[:pos]` 訓練，再對 `features.iloc[[pos]]` 預測。Forecast row 的 target 不進訓練集。

本文引用的所有統計數字來自 `experiments/k1582/K1582_results.json`。主要圖檔由 `experiments/k1582/K1582.py` 產生，文章圖表則由發布流程上傳到 Supabase Storage。

## 實務意義

K1582 對後續研究有兩個直接用途。

第一，HARQ 類 measurement-error correction 值得保留在 TX realized-volatility pipeline。TX_active 的 HARQ 與 SHARK_like 都降低 QLIKE，MCS 也排除 baseline HAR；即使 gate 不允許 PASS，這不是完全沒有訊號的方向。

第二，研究設計必須把「模型改良」與「資料可 gate」分開。SPY 與 0050.TW 在這輪只是流程檢查，不能補強跨市場論文敘事。若要真正檢驗「台灣市場因日夜盤微結構而更需要 measurement-error correction」，至少需要可 gate 的 SPY / ETF intraday panels，並把 TX day session、night session、roll handling、active contract selection 全部分層。

對交易或風控系統而言，K1582 還不到上線訊號。比較合理的工程位置是 candidate feature family：保留 HARQ / SHARK_like variants，進入下一輪 ablation 與 longer-panel validation，而非直接替代 HAR baseline。

## 限制與下一步

- TX 只使用日盤 08:45-13:45。原始 hypothesis 關心夜盤 / 日盤 microstructure，尚未被完整測試。
- SPY 與 0050.TW local five-minute panels 太短，不能支持 publication-grade cross-market inference。
- `SHARK_like` 是 approximation。若要與 Buccheri-Corsi full SHARK estimator 對話，需要重新實作更完整的 estimator 或明確改名成 realized-measure enriched HARQ。
- MCS 使用 n_boot=1000。這是 hourly task 可接受的 runtime trade-off；paper-grade rerun 應提高 bootstrap budget。
- 目前只使用 QLIKE / DM / MCS。後續可加入 density forecast、tail-risk loss，或檢查 forecast combination 是否比單一修正版更穩。

下一輪最有價值的實驗，是把 K1582 拆成可解釋的 ablation grid：HARQ only、HARQ_full、semivariance only、signed jump only、day/night split、roll-date exclusion，並在每個規格上保留同一套 `shift(1)` 與 expanding OOS gate。

## 延伸文獻與內部連結

- Corsi (2009), *A Simple Approximate Long-Memory Model of Realized Volatility*: HAR-RV baseline。
- Bollerslev, Patton and Quaedvlieg (2016), *Exploiting the errors*: HARQ 與 realized quarticity measurement-error correction。
- Buccheri and Corsi (2021), SHARK-related realized-volatility forecasting work: rich realized measures 與 signed components。
- Patton and Zhang (2026), *Bespoke Realized Volatility*: realized measure 應配合 forecast target 與 measurement-error problem 設計。
- 一般讀者版：<https://volpred.zeabur.app/v3/reports/mile_b88ee7bc>。

![K1582 result gate](experiments/k1582/figures/k1582_lazypack_3_results.png)

---

*本文基於實驗 K1582（腳本：`experiments/k1582/K1582.py`，結果：`experiments/k1582/K1582_results.json`）。資料來源：TAIFEX TX active-contract 日盤 tick 檔、本機 SPY / 0050.TW five-minute snapshots。主要樣本：TX_active 2017-05-16 至 2026-06-29，OOS forecasts=1,697。所有 forecast features 均使用 t-1 與更早資訊。*
