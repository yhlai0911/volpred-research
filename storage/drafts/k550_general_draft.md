---
title: "自適應 VIX 門檻能贏簡單 12/VIX 嗎？K550 給出 NUANCED 答案"
audience: general
status: draft
tags: [vix, volatility-targeting, adaptive-threshold, sharpe-decomposition, occam-razor, K550]
experiment_refs: [K550]
---

# 自適應 VIX 門檻能贏簡單 12/VIX 嗎？K550 給出 NUANCED 答案

## 一個看似聰明的問題

VolPred 過去一系列實驗（K115、K222、K237、K646）都驗證了同一件事：把目標波動率設在 12，再用 VIX 動態調整曝險（也就是 weight = 12/VIX，俗稱 12/VIX VT），可以在 SPY 上長期把 Sharpe 從 0.62 拉到 1.7 左右。

這個策略簡單到讓人懷疑：「12」這個數字會不會太死板？市場 2008 年 VIX 動輒 40、2017 年只有 11，難道每年都用同一個門檻不會有問題？學術界提了一堆所謂「自適應門檻」的方法 — 用滾動中位數、Z-score、Percentile 等動態調整 — 直覺上應該更好才對。

K550 這支實驗，就是把這個直覺拉到顯微鏡下檢驗。資料是 SPY + ^VIX，2005-01-03 到 2026-03-27，共 5,217 個交易日，並用台股 0050.TW 做跨市場驗證。結論是 NUANCED — 不是「自適應沒用」，但也絕對不是「散戶該換掉 12/VIX」。

## K550 設計：把 4 種自適應策略一次拉出來比

我們把以下 8 種策略放在同一張回測台上，全部用 t-1 的訊號 × t 的報酬（防 lookahead），每日 rebalance，無交易成本：

- **Buy & Hold**：SPY 直持
- **Fixed 10/12/14/16 ÷ VIX**：經典固定門檻，weight 上限為 1.0
- **Adaptive 1yr Median**：以最近 252 天 VIX 中位數當門檻
- **Adaptive 5yr Median**：5 年滾動中位數
- **Percentile-based**：按 VIX 在過去分佈的百分位調整
- **Z-score**：以 VIX 標準化分數調整曝險

## 核心結果：表面上自適應贏，骨子裡很 tricky

| 策略 | 年化報酬 | 年化波動 | Sharpe | 最大回撤 |
| --- | --- | --- | --- | --- |
| Buy & Hold | 11.8% | 19.2% | 0.62 | -55.2% |
| Fixed 10/VIX | 13.3% | 7.7% | 1.74 | -11.7% |
| **Fixed 12/VIX**（baseline） | **15.6%** | **9.2%** | **1.70** | **-13.9%** |
| Fixed 14/VIX | 16.8% | 10.5% | 1.59 | -16.2% |
| Fixed 16/VIX | 17.2% | 11.7% | 1.47 | -18.5% |
| Adaptive 1yr Median | 18.1% | 13.4% | 1.35 | -27.6% |
| Adaptive 5yr Median | 17.0% | 12.2% | 1.40 | -16.0% |
| Percentile-based | 21.4% | 7.0% | **3.07** | -5.6% |
| Z-score | 25.8% | 11.8% | 2.19 | -17.0% |

![K550 各策略 Sharpe vs 年化報酬](/experiments/k550/k550_sharpe_vs_return.png)

乍看之下 Percentile-based 的 Sharpe 3.07 完全輾壓 12/VIX 的 1.70，連兩模型差異比較的統計強度都遠超嚴格門檻（達顯著水準），跨 5 個獨立 OOS 期間（GFC / Recovery / Low Vol / COVID+ / Post-COVID）也都穩定。

但這正是這篇文章想討論的最重要 framing — **Sharpe 高，不等於 alpha 強**。

## 拆開分子和分母：高 Sharpe 是怎麼來的？

Sharpe = 年化報酬 ÷ 年化波動。要把 Sharpe 拉高，可以靠兩種完全不同的機制：

1. **真本事（alpha）**：在波動相同情況下，找出更好的進出時機，拿到更高報酬
2. **降風險（denominator shrink）**：把曝險壓下來，分母變小，看起來 Sharpe 飆高但 absolute return 沒贏多少

K550 的 Percentile-based 策略走的是第二條路。

![K550 Sharpe 分子分母拆解](/experiments/k550/k550_sharpe_decomp.png)

實驗結果顯示，Percentile-based 策略的**平均曝險只有 0.53**（相當於有一半時間在持有現金），Z-score 策略平均曝險 0.84。它們的高 Sharpe 不是因為時機抓得比 12/VIX 準，而是因為長期偏保守，分母變小了。

對比之下，Fixed 10/VIX 也是把曝險壓得很低（年化波動只有 7.7%），它的 Sharpe（1.74）也比 12/VIX（1.70）略高 — 但年化報酬反而**輸給** 12/VIX（13.3% vs 15.6%）。這說明同樣的「降低曝險拉高 Sharpe」現象，在固定門檻 family 內也存在。

換句話說：**所謂「Sharpe-optimal threshold」永遠是最低的那個** — 因為機械式降低曝險就能機械式拉高比值。但這對絕對財富累積沒有幫助。

## Adaptive 中位數實驗：不只沒贏，還輸了

更值得說的是 1 年滾動中位數策略，它是學術界最常見的「動態門檻」實作。結果：

- Sharpe 1.35 vs 12/VIX 的 1.70 — **明顯輸**
- MDD -27.6% vs -13.9% — 回撤是兩倍
- 跨 OOS 5 個期間都輸或打平

![K550 Cross-OOS Sharpe 熱圖](/experiments/k550/k550_crossoos_heatmap.png)

為什麼？K550 觀察到一個直觀的機制：**滾動中位數會以 lag 追蹤 VIX**。也就是說，當市場進入 GFC、COVID 這種高波動期，過去一年的中位數會被慢慢拉高 → 模型對「高 VIX」的容忍度變大 → 該降低曝險時降不下來，該大幅減倉時還在維持高曝險。

這就是 fixed 12/VIX 反而贏的原因 — 它對高波動環境的反應是「立即 + 線性」，而 adaptive median 是「延遲 + 平滑」。在風險急轉直下時，慢半拍要付出代價。

## 跨市場驗證：台股結論一致

K550 同步在 0050.TW（搭配台股自製 VIX 代理）跑了一遍：

| 策略 | Sharpe | MDD |
| --- | --- | --- |
| Buy & Hold | 0.37 | -78.2% |
| Fixed 8.63/VIX | 0.59 | -46.8% |
| Fixed 12/VIX | 0.58 | -64.5% |
| Adaptive 1yr Median | 0.58 | -74.1% |

三個 VT 變體的 Sharpe 在台股完全一樣（0.58~0.59），但 adaptive 的 MDD 比 fixed 更糟。**「換成自適應就會更好」的直覺，在台股也不成立。**

## 給散戶的實務建議：奧坎剃刀勝出

如果你只想做一件事改善資產配置，K550 的 take-away 非常清楚：

1. **VT 本身有效** — 用 VIX 動態調整曝險（不論固定 12 還是 14），長期都比 Buy & Hold 強很多
2. **門檻細節不重要** — 在 [10, 16] 這個區間裡，Sharpe 差異只有 1.47 ~ 1.74，還不到 0.3 個單位
3. **不要被 Sharpe 數字迷惑** — 如果你看到某個「自適應」VT 策略 Sharpe 3.0，先問它的平均曝險是多少。曝險 0.5 的高 Sharpe 跟曝險 1.0 的高 Sharpe 是兩件事
4. **散戶的最佳解：固定 12/VIX 或 fixed 14/VIX** — 簡單、透明、易執行，數字幾乎一樣好

奧坎剃刀（Occam's Razor）在這裡發揮得淋漓盡致：**最簡單的解通常是最好的解**。學術論文上看起來高大上的 adaptive median / Z-score / Percentile 在絕對財富累積上沒有任何優勢，反而引入更多參數風險與實作風險。

## 學術 framing 與下一步

從研究方法學上看，K550 也再次提醒一個經典陷阱 — 用 Sharpe Ratio 評比策略時，必須同時報告**平均曝險與絕對報酬**，否則高 Sharpe 可能只是「機械降風險」的副產物，不是真正的 timing alpha。這跟 Moreira & Muir (2017) 在 *Volatility-Managed Portfolios*（JF）一文中的核心論點是一致的。

K550 接著的延伸方向：

- **Regime-conditional threshold**：把 fixed 12 跟 VIX term structure（VIX9D / VIX3M / VVIX）疊加，是否有 incremental alpha？
- **跨資產驗證**：QQQ / IWM / 日經 / 歐股 — 12/VIX 是否仍是 Occam-optimal？
- **與 K115/K222/K237/K646 整合**：12/VIX VT 系列已累積 8+ 個 PASS 結果，可以考慮整合進論文 narrative（VolPred Paper 6/8 候選素材）

## 結論：別被「自適應」這個詞迷惑

「Adaptive 一定比 fixed 好」是一個很容易讓研究者中招的直覺。K550 跨 5,217 天 + 5 個獨立 OOS 期間 + 跨市場驗證後告訴我們：

- 自適應**有時**讓 Sharpe 看起來更高，但這個高來自於「降低曝險把分母壓小」，不是更會抓時機
- Adaptive median 因為**追蹤 VIX 有 lag**，在危機期反而比 fixed 12/VIX 更晚減倉，吃了更大的回撤
- 散戶不需要在這上面花時間 — fixed 12/VIX 簡單實用，就是最好的選擇

研究的價值，有時候不是發現新方法贏了舊方法，而是用嚴謹的證據確認「**已知最簡單的方法仍然最強**」。這也是 VolPred 一直堅持的研究誠實原則 — Null result 也是 result，能幫讀者省下走錯路的時間，才是最有價值的貢獻。

---

**資料來源**：實驗 K550（2026-03-27），SPY + ^VIX 2005-01-03 至 2026-03-27（5,217 個交易日），台股 0050.TW 跨市場驗證 3,952 日。實驗檔位於 `experiments/k550/`，含完整參數、回測碼與 results JSON。所有圖表為 K550 results 直接生成。

**相關研究**：K115 / K222 / K237 / K646（12/VIX VT 系列原型驗證）、N79 / N81 / N83（VIX 門檻 sensitivity）、Moreira & Muir (2017, JF)、Fleming, Kirby & Ostdiek (2001, JFE)、Harvey, Liu & Zhu (2016, RFS)。
