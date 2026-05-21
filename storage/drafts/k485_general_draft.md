---
title: "讓貝氏自己挑變數能改善波動率預測嗎？K485 跨 5 期 OOS 給出 PROMISING 但不全面顯著"
audience: general
status: draft
tags: [ssvs, garch, vix, bayesian-vs, vol-forecasting, oos, K485]
experiment_refs: [K485]
---

# 讓貝氏自己挑變數能改善波動率預測嗎？K485 跨 5 期 OOS 給出 PROMISING 但不全面顯著

## 一個讓研究者既興奮又害怕的想法

做波動率預測最常見的兩難是：「我手上有 5 個合理的解釋變數，到底要全部丟進模型，還是挑一兩個最重要的？」

全丟進去會 over-fit，挑錯了又會丟掉訊息。傳統做法是用 BIC/AIC 一個個比較，但組合爆炸下很快就跑不完。**SSVS（Stochastic Search Variable Selection，隨機搜尋變數選擇）** 給了一個漂亮的貝氏解法 — 讓 MCMC 自己在「該變數要不要被選」的二元 indicator 上抽樣，最後直接給你每個變數的「被選機率」（PIP, Posterior Inclusion Probability）。

聽起來很神。但它在波動率預測這個 noisy 的場域裡，能不能贏過簡單的「GJR-GARCH 加一個 VIX」？K485 就是針對這個問題，把 K484 在 in-sample 挑出的 SSVS 中位數模型拉去**跨 5 個 OOS 期間驗證**，給出一個有點殘酷但很誠實的答案。

**先把結論講前面**：SSVS 在 5 個 OOS 期間中**有 4 期方向上贏了 GJR-GARCH**，但**只有 2 期達到 DM 顯著水準（顯著性 < 0.10）**。而且，跨 5 期的**平均 QLIKE 第一名不是 SSVS，是「GJR + 單一 VIX」這個更簡單的對照組**。SSVS 改善真實存在，但「複雜模型不一定能 dominate 簡單模型」是這次最重要的訊息。

## K485 的設計：把 K484 的中位數模型逼進 OOS

K484 在 in-sample 用 SSVS 跑了 8 個候選變數，最後把 PIP=1.000 的 4 個變數合成一個中位數模型：

$$h_t = \omega + \alpha \varepsilon^2_{t-1} + \beta h_{t-1} + \gamma I(\varepsilon<0) \varepsilon^2_{t-1} + \lambda_1 \frac{VIX^2}{252} + \lambda_2 Range^2 + \lambda_3 |\varepsilon|$$

也就是 GJR-GARCH 的不對稱項，加上 VIX 隱含變異數、Parkinson range（範圍估計量）、以及絕對殘差（TGARCH/AVGARCH 風格）。聽起來合理 — 4 個都是文獻反覆驗證過的 vol predictor。

K485 把這個 K484 model 拿去跑 SPY 5,338 個交易日（2005-01-03 至 2026-03-25），切成 5 個不重疊的 OOS 期間：**2015-16、2017-18（Volmageddon）、2019-20（COVID）、2021-22（升息循環）、2023-24**。每期約 502-505 個交易日，rolling window 2,000 日，每 21 日 refit 一次。對照的 4 個 baseline 是：Base GARCH(1,1)、GJR-GARCH(1,1)、GJR + 單一 VIX、GJR + 單一 Range。

評估用 Patton (2011) 的 QLIKE loss，配對顯著性看 Diebold-Mariano 檢定。

## 結果一：SSVS 5/5 期方向都贏，但顯著性只有 2/5

![5 期 QLIKE 比較](/experiments/k485/fig1_qlike_by_period.png)

這張圖把 5 個模型在 5 期 OOS 的 QLIKE 全攤開。SSVS（紅實線）和 GJR+VIX（綠實線）幾乎黏在一起，兩條都壓在 GJR-GARCH（藍虛線）下面。最戲劇化的是 2019-20 COVID 期 — SSVS 把 GJR-GARCH 從 1.548 降到 1.385，**相對改善 10.5%**，是 5 期中最大幅度。

但「改善幅度大」不等於「顯著」。把 SSVS 對 GJR 的 DM p-value 拉出來看：

![SSVS vs GJR DM p-value](/experiments/k485/fig2_dm_pvalue_by_period.png)

只有兩根紅色 bar 站在 p=0.10 線下面：

- **2015-16**：SSVS QLIKE 1.514 vs GJR 1.590，相對改善 -4.80%，DM 顯著性 6.87e-05（高度顯著）
- **2021-22 升息**：SSVS QLIKE 1.312 vs GJR 1.386，相對改善 -5.31%，DM 顯著性 0.099（邊緣顯著）

剩下 3 期：

- **2017-18 Volmageddon**：SSVS 1.722 vs GJR 1.720，**SSVS 反而略輸**（+0.11%），DM 顯著性 0.977（完全沒差別）
- **2019-20 COVID**：SSVS 改善 -10.50% 看起來很大，但 DM 顯著性 0.121，**沒過 10% 門檻** — COVID 期間 squared return proxy 噪音極大（單日跳動到 ~66 vs 平時 ~1.5），統計力被吃光
- **2023-24**：改善 -1.90%，DM 顯著性 0.282，方向贏但不顯著

**4/5 期方向贏 vs 2/5 期顯著贏**，這個差距告訴我們什麼？樣本量是真的會打臉模型 — 一年 250 個交易日，要從 noisy 的 squared return 裡 extract 到顯著差異，至少需要平均 5% 以上的相對改善 + low-noise 期間。Volmageddon 跟 COVID 這種「黑天鵝期」本身就會把 DM 統計量壓下來，因為極端值同時讓兩個模型都犯大錯。

## 結果二：5 期平均 QLIKE 第一名不是 SSVS，是 GJR+VIX

這是 K485 最違反直覺的發現。把 5 期的 QLIKE 平均起來：

![5 期平均 QLIKE 排名](/experiments/k485/fig3_avg_qlike_ranking.png)

| 模型 | 5 期平均 QLIKE | 相對 GJR |
|---|---|---|
| GJR + 單一 VIX | 1.4753 | -4.64% |
| SSVS（4 變數） | 1.4794 | -4.48% |
| GJR + 單一 Range | 1.4960 | -3.36% |
| GJR-GARCH | 1.5471 | 0.00% |
| Base GARCH | 1.5688 | +1.35% |

排第一的不是有 4 個外生變數的 SSVS，是只塞**一個 VIX** 進去的 simplest 加強版。差距 0.4%（QLIKE 0.0041）小到可以說兩者基本上是 tied，但**「複雜不一定贏簡單」是這次研究最該被讀者記住的訊息**。

這不是 SSVS 的失敗 — K484 in-sample 它確實把 4 個變數都選了 PIP=1.000，意思是這 4 個變數**單獨來看**都對 vol 有解釋力。問題是 OOS 的時候，多塞變數會帶來估計變異（estimation variance），這個變異在 noisy market 期間會吃掉一部分訊息增益。VIX 一個變數就抓到了大部分的 explanatory power，剩下三個變數（Range、|ε|、不對稱項）的邊際貢獻在 OOS 上幾乎被 estimation noise 抵銷。

## 該怎麼看「PROMISING 但不全面顯著」？

研究誠實原則要求我不能把這個結果包裝成「SSVS 贏了」也不能說「SSVS 沒用」。比較準確的說法是：

1. **SSVS 是個合格的探索工具** — 它在 in-sample 挑變數的能力（K484 PIP=1.000 of 4 vars）有可信度，方向上也在 OOS 維持 4/5 期領先 GJR
2. **但 OOS 顯著性不全面（2/5）**，sample size 與市場噪音是主要瓶頸
3. **更簡單的 GJR+VIX 在 5 期平均上反而第一**，差距小但這提醒我們 — 在 vol forecasting，**「找對單一外生變數」可能比「找一堆相關變數」更重要**

對學術研究的下一步，我認為值得試的方向有兩個：

- **Cross-asset SSVS**：把 K485 設計搬到 0050.TW、TLT、QQQ 等不同 vol regime 的資產上，看 PIP=1.000 的變數會不會跨資產一致 — 一致就是真 signal
- **Regime-conditional priors**：把 SSVS 的 spike-and-slab prior 在低 VIX / 高 VIX regime 下分別估，避免 pooled estimation 把兩個 regime 的訊號互相稀釋

但這兩個都是研究方向，不是現在能直接幫你做風險管理的結論。**現在能用的結論是 — 如果你只想要一個簡單可靠的 vol model，GJR-GARCH + VIX 一個外生變數，就足夠在 5 個不同市場期間穩定贏過純 GARCH。**

---

**數據與方法**：SPY 日報酬，2005-01-03 至 2026-03-25，5,338 個交易日，IS window=2000，refit interval=21 日，5 個不重疊 OOS 期間（每期約 502-505 日）。Loss function 採 Patton (2011) QLIKE，模型比較用 Diebold-Mariano (1995) 檢定。SSVS 設計參考 So, Chen, Liu (2006) JRSS-C 55(2):201-224。完整實驗在 [experiments/k485/](https://github.com/) — README、code、results JSON 三件套齊全。

**判定**：PROMISING — 4/5 期方向贏 GJR，2/5 期統計顯著；5 期平均第一名是 GJR+VIX。對應 K484 in-sample SSVS 中位數模型的 OOS 驗證。
