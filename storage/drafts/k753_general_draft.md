---
title: "成交量能不能預測明天的波動？技術上『可以』，實際上『不行』"
audience: general
status: draft
description: "K753 在 SPY 上做了 5-part 全面測試。成交量與當日波動同步性確實存在（MDH 假說），但對下一日波動的偏相關只剩 0.089，所有以成交量為核心的策略 Sharpe 都輸給 VIX 基準。VIX 已經把成交量裡的訊息壓縮進去。"
tags:
  - volume
  - liquidity
  - MDH
  - predictor
  - null-result
  - VIX-sufficiency
experiment_refs:
  - K753
---

# 成交量能不能預測明天的波動？技術上『可以』，實際上『不行』

## 一句話結論

「成交量大、波動就大」是直覺，也確實成立。但問題是：**今天的成交量能不能預測明天的波動？**我們在 SPY 上做了 20 年、5,090 個交易日的 5-part 全面測試。答案是：**統計上「微弱地可以」，實務上「不行」**。VIX 已經把成交量裡能用的資訊全部吸收掉了。

## 為什麼要花力氣再驗證一次

成交量與波動之間的關係，是金融計量裡最古老也最直覺的話題之一：

- **Lamoureux & Lastrapes (1990, JoF)** 在 GARCH 模型裡放成交量，發現成交量會把 GARCH 的記憶性「吃掉」
- **Gallant, Rossi & Tauchen (1992, RFS)** 用半參數方法證實成交量與波動同步聚集

這些經典文獻奠定了 **MDH（Mixture of Distributions Hypothesis，混合分布假說）**：成交量與波動同源於「市場資訊到達的速率」，所以它們**同期**會同步。

但教科書裡很少正面回答一個更實用的問題：**那能不能用今天的成交量，預測明天的波動，並轉成可獲利的策略？** 我們把這個問題拆成 5 個 part 一一檢驗。

> 防誤讀：本實驗所有「預測」都是嚴格的 t-1 → t 設定。也就是用昨天收盤後才知道的成交量，去預測今天的波動。代碼裡有明確的 `signal.shift(1)` lag —— 不會有用今天 volume 算今天 return 的先見之明偏誤。

## Part A：MDH 假說 — 成交量與當日波動同步（這部分成立）

第一步先確認教科書事實。我們把每天的 SPY 成交量轉成 z-score（剔除趨勢與星期效應），按高低分成 5 組，計算每組當天的 |return|：

![Part A 成交量五分位 vs 當日 |return| — MDH 同步性](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k753_chart_a_quintile.png)

| 成交量分位 | 當日 \|return\| 平均 |
|---|---|
| Q1（最低量） | **0.50%** |
| Q2 | 0.59% |
| Q3 | 0.71% |
| Q4 | 0.85% |
| Q5（最高量） | **1.25%** |

從 Q1 到 Q5，|return| 單調遞增 2.5 倍。同期相關係數 **0.333**（5,090 個觀察值，t 統計遠超任何門檻）。**MDH 確認**。

**但請注意：這只是同步性。** 它告訴你「波動大的日子，成交量也會大」，但完全沒回答「成交量能不能領先波動」。同步相關 ≠ 預測力，這是這篇文章接下來要追的重點。

## Part B：偏相關 0.089 — 統計顯著，經濟意義微小

把 t-1 的成交量當作**預測子**來預測 t 日的 |return|，並控制 VIX 之後，得到的偏相關（partial correlation）是：

| 量 | 數值 | 解讀 |
|---|---|---|
| Volume → next \|return\| 偏相關（控制 VIX） | **0.089** | 達顯著水準（p≈0.001 以下） |
| 增量 R²（VIX 加上 Volume vs 只有 VIX） | 0.325 → **0.331**（+0.005） | 模型解釋力幾乎沒進步 |
| 兩模型比較顯著性檢定 | p = **0.045** | 邊緣顯著 |
| 成交量「**變化**」對下一日 \|return\| 相關 | **−0.009** | 完全無關 |

這正是「**統計顯著 ≠ 經濟顯著**」的經典案例。樣本數 5,090 大到能把 0.089 這種微弱訊號「壓出」達顯著水準的星號，但增量 R² 只有 **0.5%**。換成白話：

> 知道昨天的成交量，能讓我們對今天波動的解釋力從 32.5% 提升到 33.1%。差距 0.6 個百分點。對任何要付手續費、要承擔交易成本的策略來說，這個訊號太弱。

更值得注意的是：**「成交量變化」（Δvolume）的預測力是零**（r = −0.009）。也就是說，「今天突然爆量」並不會領先「明天波動爆增」—— 兩者是同一件事。

## Part C：反直覺發現 — 極端量日後 VIX 反而最 calm

民間常聽到「成交量縮小，是暴風雨前的寧靜」（calm before the storm）—— 認為 volume 萎縮是後續波動爆發的前兆。我們直接檢驗：

![Part C 五種成交量 regime 後的 VIX spike 機率](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k753_chart_c_regime.png)

定義「VIX spike」為 VIX 次日上漲 ≥ 10%。20 年無條件平均機率 ≈ **21.0%**。各 regime 後的條件機率：

| 當日成交量 regime | 次日 VIX spike 機率 |
|---|---|
| 極低量 | 22.1% |
| 低量 | 22.0% |
| 正常量 | 20.1% |
| 高量 | 20.0% |
| **極端量** | **12.6%** ← 反而最低 |

**Calm before storm 沒有被證實**：成交量驟降後 VIX spike 的 lift 只有 **1.19 倍**，遠低於可操作門檻（一般要 ≥ 1.5x）。

更反直覺的是：**極端高量日**之後，VIX spike 的條件機率竟然是 **12.6%**，比無條件平均 21% 還低 8 個百分點。這對應到實務上常見的「**volume exhaustion**」現象 —— 一根量爆的紅 K 通常已經把恐慌與資訊一次釋放完，後面反而是冷靜期，而不是更大的風暴。

這個發現恰好和「calm-before-storm」民俗智慧**反向**。

## Part D：5 種策略 Sharpe 比較 — 成交量策略最差

統計檢定再嚴謹，最後也要看「能不能換成錢」。我們設計了 5 個月度再平衡的波動率目標策略，全部 5 bp 交易成本、嚴格 `signal.shift(1)` lag：

![Part D 五種策略 Sharpe 比較](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k753_chart_b_sharpe.png)

| 策略 | Sharpe | 年化報酬 | 最大回撤 |
|---|---|---|---|
| Volume 單一策略 | **0.581** ← 最差 | 7.4% | −50.7% |
| Volume + VIX combo | 0.626 | 5.2% | −28.6% |
| Buy & Hold SPY | 0.681 | 10.3% | −50.8% |
| **12/VIX 基準** | 0.729 | 6.7% | −28.2% |
| 50/50 SPY/GLD | 0.918 | 11.1% | −25.6% |

**3 個關鍵觀察**：

1. Volume 單一策略 Sharpe **0.581**，是 5 個策略裡**最差**的
2. 把 Volume 加進 VIX 變 combo，Sharpe 從 0.729 掉到 0.626 —— **不只沒幫上忙，反而拖累**
3. Bootstrap Sharpe 差檢定：Volume 比 VIX 好的機率只有 **11.8%**（即 88.2% 的 bootstrap 樣本下 VIX 表現更佳）

策略層面的結論非常乾脆：**成交量沒有任何在 VIX 之上的增量價值，加進去甚至會傷害組合**。

## Part E：Granger 因果檢定 — 不顯著

最後跑 Granger 因果檢定（在 AR(1) VIX 模型加上 Volume 落後項）：

| 量 | 數值 |
|---|---|
| F 統計 | 2.27 |
| p-value | **0.132** |
| Volume 係數 | −0.005 |

**Granger 不顯著**。也就是說：在控制 VIX 自身的時間序列動態後，成交量對 VIX 沒有額外的領先資訊。

## 為什麼會這樣？VIX 是「資訊壓縮機」

把 5 個 part 串起來，故事其實很乾淨：

1. **成交量確實與波動相關**（MDH 同步性，corr = 0.333 教科書事實）
2. **但這些資訊已經被 VIX 吸收了** —— VIX 是選擇權市場的隱含波動率，反映的就是「**未來不確定性的市場價格**」。當大家在交易、在下注未來時，量、波動、VIX 是同一塊拼圖
3. **所以「在 VIX 之上加 Volume」近乎徒勞** —— 增量 R² = 0.5%，Granger 不顯著，策略表現變差

這個結論和我們先前的研究一致：

- **K710**：成交量 z-score 增量 R² = 0.0023（更小）
- **K711 / K722** 系列：多種「VIX 替代訊號」都被 VIX 本身打敗

我們把這個現象稱為 **VIX-sufficiency**：在月度／日度的低中頻策略上，VIX 幾乎是個「**充分統計量**」—— 能拿到 VIX 的人，再去找成交量、買賣價差、市場深度等替代訊號的邊際效益非常有限。

## 給讀者的 3 個教訓

**1. 統計顯著 ≠ 經濟顯著**

樣本數 5,090 能把 0.089 這種微弱相關壓到達顯著水準，但增量 R² 只有 0.5%。下次看到「我們發現 X 對 Y 顯著預測」時，請記得追問：增量 R² 多少？換成 Sharpe 是多少？經得起交易成本嗎？

**2. 同步相關 ≠ 預測力**

「volume 與 |return| 同步相關 0.333」是 MDH 教科書事實。但能不能領先預測，是完全不同的問題。**永遠分清楚 contemporaneous 與 predictive**。

**3. VIX 已經幫你做完很多事**

如果你的策略已經納入 VIX，那再去找成交量、買賣價差、市場深度等「替代波動訊號」的邊際效益會非常小。把研究時間花在 VIX 還沒覆蓋的維度（例如：跨資產 spillover、tail risk 結構、極端事件後的 mean-reversion 速度）會更有效率。

## 反直覺彩蛋：極端量是冷靜期

最值得記在筆記本上的單一發現：**極端量日（z-score 在最極端 5% 以上）之後，VIX spike 機率只有 12.6%，是 5 個 regime 中最低**。一般人以為「量爆 = 後面更亂」，數據說正好相反。

如果你做日內交易、看到當天 SPY 量爆出歷史水位，下一個交易日**統計上更可能**是個冷靜的整理日，而不是延續性的恐慌。當然這只是條件機率 12.6% 不是 0%，僅供參考，不構成投資建議。

---

**研究數據**：SPY / VIX，2006-01-03 至 2026-03-27，共 5,090 個交易日，yfinance 來源
**研究 ID**：K753（5-part comprehensive test）
**親緣研究**：K710（成交量 z-score null result）、K711 / K722（VIX-sufficiency 系列）
**參考文獻**：
- Lamoureux, C. G., & Lastrapes, W. D. (1990). *Heteroskedasticity in stock return data: Volume versus GARCH effects*. Journal of Finance, 45(1), 221–229.
- Gallant, A. R., Rossi, P. E., & Tauchen, G. (1992). *Stock prices and volume*. Review of Financial Studies, 5(2), 199–242.
