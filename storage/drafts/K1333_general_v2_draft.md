---
title: "VIX 自己的波動率，能不能預測 VIX？"
kid: K1333
audience: research
category: research
phase: research
tags: [vix, vol-of-vol, realized-vol, multiple-testing, bonferroni]
status: draft
---

# VIX 自己的波動率，能不能預測 VIX？

> 一個誠實的弱訊號：自製 vol-of-vol 在統計上贏 AR(1) baseline，但過不了多重檢定。

## 我們在問什麼

VIX 是市場的「恐慌溫度計」，每天上下跳。一個自然的問題是：**VIX 自己的波動率（vol-of-vol），能不能預測明天 VIX 的水位或變動幅度？**

業界做這件事通常會用 VVIX，也就是「VIX 選擇權的隱含波動率」。但 VVIX 來自選擇權市場，不是純粹的歷史價格資訊。我想試一個更素的版本：只用 VIX 自己的日收盤價，算出短窗（5 日）和長窗（22 日）的 realized vol，看這兩個自製訊號加上去，預測能力有沒有比 AR(1) 基準好。

定位先說清楚：這不是一個「我找到新策略」的故事。這是一個方法論練習，外加一個誠實的弱訊號報告。

## 資料和方法

- 資料來源：yfinance `^VIX` 日收盤，2010-01 到 2026-06，共 4,115 個觀測值
- 切分：訓練 2010–2019、驗證 2020–2023、測試 2024-01 到 2026-06（OOS 615 個觀測值）
- 預測目標兩個：明天的 VIX 水位、明天的 |ΔVIX|（變動幅度）
- 方法：所有特徵都 `.shift(1)` 對齊；AR(1) baseline 用同樣的 lag；用 HAC 修正的 Diebold-Mariano 檢定來比 forecast loss；bootstrap 信賴區間 B=2000, block_len=10, seed=42 固定
- 兩個 spec：
  - **M1**：只有 vol-of-vol 兩個窗（rv_short + rv_long）
  - **M2**：M1 再加上 VIX 前一日水位、前一日 log return、跳躍代理變數

![VIX 與 5 日 / 22 日自製波動率（含訓練 / 驗證 / 測試切分線）](experiments/k1333/k1333_vix_volofvol.png)

## 結果四格表

| 預測目標 / Spec | R²_OOS vs AR(1) | DM(MSE) t | p | DM(QLIKE) t | p |
|---|---:|---:|---:|---:|---:|
| 水位 / M1 | -3.188 | +4.44 | <0.001 | +6.03 | <0.001 |
| 水位 / M2 | +0.025 | -2.04 | **0.041** | -2.24 | **0.026** |
| 幅度 / M1 | -0.032 | +0.74 | 0.461 | n/a | n/a |
| 幅度 / M2 | +0.136 | -2.05 | **0.041** | n/a | n/a |

（幅度目標的 QLIKE 沒算，因為 |ΔVIX| 序列裡有為 0 的觀測值，會破壞 QLIKE 的 log domain。MSE 還是合法的 loss function。）

![四個 cell 的 OOS R² vs AR(1) baseline。M1 因為缺 VIX_lag1 在水位目標上嚴重輸 AR(1)；M2 在水位與幅度兩格都正向。](experiments/k1333/k1333_r2_bycell.png)

四個格子裡，水位/M2 跟 幅度/M2 兩格 OOS R² 為正，p 值 unadjusted 都過 0.05。但這就是故事的轉折點。

## 三個讀者可以學到的東西

### 第一：為什麼 M1 在「水位」直接崩盤

水位 / M1 的 R² 是 **-3.19**。負三是什麼意思？意思是「直接拿 AR(1) 預測比這個自製模型好太多」。原因不複雜：**VIX 在水位上接近 unit-root**。白話講，明天的 VIX 大致就是今天的 VIX 加上一點噪音。一個不用昨天 VIX 水位的模型，連基本盤都站不住。

這不是 bug，是預期會失敗的設定。它的意義在於：**baseline 選錯，再花俏的特徵也救不回來**。M2 加進 VIX_lag1 之後，係數 0.973、t 值 133.21，光這一條就決定了整個迴歸的命脈。其他特徵只是錦上添花。

### 第二：M2 看起來有訊號，但效應很小

水位 / M2 的 R² 是 **+0.025**，幅度 / M2 是 **+0.136**。兩個都是正的，DM 檢定也都過 0.05。

但讀者要注意 bootstrap CI：
- 水位 / M2：[-0.200, -0.010]（指模型 loss 減 AR(1) loss 的平均，全在 0 以下，代表模型確實贏，但贏的幅度很窄）
- 幅度 / M2：[-0.673, -0.103]（區間寬度大，效應較明顯但仍小）

換句話說：**訊號是真的，但實務操作能榨出多少 alpha，是另一回事**。R² 增加 0.025 在學術圈夠寫一篇短文，在交易桌上未必夠付手續費。

從係數結構看得更清楚一點。幅度 / M2 的迴歸裡，rv_short_lag1 係數 0.43、t 值 7.35，是最強的單一預測子；rv_long_lag1 係數只有 0.088、t 值 1.70，貢獻有限。意思是**短窗（5 日）抓到的訊號遠強於長窗（22 日）**。這跟 vol clustering 屬於高頻現象的文獻一致。跳躍代理變數 jump_proxy 也是顯著的（t=2.04），代表 VIX 出現大跳之後，隔天的 |ΔVIX| 確實偏大。

### 第三：Bonferroni 把兩個 p<0.05 全部打掉

這是整篇文章最重要的一段。

我做了四個 (target × spec) 格子，意思是我同時測了四個假設。當你同時測多個假設，**任何一個格子過 p<0.05 的機率會被「測試次數」放大**，這在統計學叫 multiple testing problem。

最簡單的修正叫 Bonferroni：把家族 α=0.05 除以格子數 4，得到每格的門檻 α=0.0125。

回頭看四格表：水位/M2 unadjusted p=0.041、幅度/M2 unadjusted p=0.041。兩個都比 0.0125 大。

**Bonferroni 修正後，沒有一格存活。**

這就是為什麼我把 verdict 定為 **CONDITIONAL_PASS**，不是 PASS。「有 unadjusted 訊號但過不了 family-wise 修正」是一個技術上很常見的狀態，但太多文獻會選擇只報 unadjusted 結果，不講 Bonferroni 的事。我選擇兩個都報。

## 對讀者的 takeaway

如果你只記得一件事，請記這個：**看到 p<0.05 的研究結果，先問「他們同時測了幾個假設？」**

- 測 1 個，p<0.05 就是 p<0.05
- 測 4 個，門檻應該是 0.0125
- 測 20 個，門檻應該是 0.0025

很多財經研究把好幾個資產、好幾個 spec、好幾個 horizon 同時跑，然後挑顯著的那一格寫成「發現」。這個動作叫 p-hacking，搬到實盤通常會失望。Bonferroni 雖然保守，但它替你擋掉很多花拳繡腿。

第二件事：**baseline 選對，比模型花俏更重要**。VIX 水位接近 unit-root，AR(1) on dVIX 就是該選的 baseline；如果你用 random walk on VIX 比，幾乎什麼模型都會贏，但那是錯的 framing。

第三件事：**自製 vol-of-vol 在 |ΔVIX| 上的訊號比在水位上明顯**（R² 0.136 vs 0.025）。這跟波動率群聚（vol clustering）的直覺一致。VIX 自己的變動有持續性，短窗 realized vol 抓得到這一段。但抓到不等於能賺錢，中間還有交易成本、滑點、執行延遲一堆事。

## 限制

- 樣本期間從 2010 起算，沒涵蓋 2008 金融海嘯。OOS 期間從 2024 開始，雖然包含 2024 Q4 波動以及 2025-2026 部分，但不含一次完整的大空頭循環
- 預測目標是 1 日後，沒有測過更長 horizon
- 沒有比較 VVIX-based 模型（這是設計上故意，這個實驗的問題就是「不靠選擇權通道行不行」）
- 我用的 DM 是 HAC（Newey-West），不是 Harvey-Leybourne-Newbold 的小樣本修正，OOS 615 算大樣本，差異有限但不為零

## 結論

VIX 自己的波動率能不能預測 VIX？**統計上能贏 AR(1)，但贏得不夠多，過不了多重檢定**。這個結論很無聊，但它是誠實的。研究做久了會發現，「有訊號但效應小」是最常見的狀態，比「重大突破」常見很多。把它如實報告出來，比包裝成 PASS 有用。

下一步如果要繼續，會做兩件事：(1) 把 horizon 拉到 5 日或 22 日，看訊號是否在不同 frequency 上呈現；(2) 用 MCS（Model Confidence Set）取代 Bonferroni，看在 family 內部哪些 model 進不了「無法被剔除」的集合。

## 參考文獻

- Bekaert, G., Hoerova, M. (2014). "The VIX, the variance premium and stock market volatility." *Journal of Econometrics* 183(2), 181-192.
- Andersen, T. G., Bollerslev, T., Diebold, F. X. (2007). "Roughing it up: Including jump components in the measurement, modeling, and forecasting of return volatility." *Review of Economics and Statistics* 89(4), 701-720.
- Patton, A. J. (2011). "Volatility forecast comparison using imperfect volatility proxies." *Journal of Econometrics* 160(1), 246-256.

---

*本文基於實驗 K1333（腳本：experiments/k1333/k1333.py，結果：experiments/k1333/k1333_results.json）。資料來源：yfinance ^VIX 日收盤，期間 2010-01 到 2026-06-12，樣本 4,115 個觀測值（OOS 615）。[提出: Claude]*
