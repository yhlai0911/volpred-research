---
title: VIX 期貨曲線真能當交易訊號嗎？我們抓到自己的 lookahead bug
audience: general
status: draft
tags:
  - VIX
  - 期貨曲線
  - 交易策略
  - Contango
  - 研究誠實
  - 槓桿錯覺
experiment_refs:
  - K671
---

# VIX 期貨曲線真能當交易訊號嗎？我們抓到自己的 lookahead bug

> VIX 期貨經常處在 contango（遠月比近月貴），市場上有不少策略宣稱可以靠這條曲線形狀做擇時。我們在 SPY 上跑了 4482 個交易日的回測，最後得到一個誠實但不討喜的結論：**VIX 期貨曲線訊號本身，沒有比「直接調整槓桿」多帶來任何價值（Newey-West t = 0.37）**。更重要的是，過程中我們抓到自己的程式碼有 lookahead bias，修正後優勢就消失。本文記錄這次「失敗」，因為它比成功更值得寫。

[提出: 賴奕豪, 執行: Claude]

## 一條看似漂亮的訊號

VIX 期貨曲線（VIX term structure）是 vol 圈最常被拿來說嘴的訊號之一。它的故事很簡單：

- 當市場平靜，**遠月 VIX 期貨**（例如 3 個月後到期）會比**近月 VIX**（spot 或最近月）貴一些。這狀態叫 **contango**——投資人對「未來不確定性」要求風險溢酬，所以遠月貴。
- 當市場恐慌，整條曲線會反轉：近月 VIX 飆高，遠月相對偏低。這叫 **backwardation**——大家覺得短期內波動會更可怕。

直覺上，這個形狀看起來就像市場的「體溫計」：曲線越陡峭的 contango，市場越平靜；倒掛得越深，恐慌越濃。

於是一個很自然的策略冒出來：**contango 時加碼股票、backwardation 時減碼**。聽起來合理對吧？這也是我們在 K671 想驗證的核心問題：**VIX 期貨曲線的形狀，到底是不是一個有用的交易訊號？**

## 樣本與資料

- **資產**：SPY（標普 500 ETF）
- **訊號來源**：VIX（^VIX，現貨）與 VIX3M（^VIX3M，3 個月隱含波動率指數）
- **Contango 訊號**：(VIX3M − VIX) / VIX，即 3 個月相對近月的溢價比例
- **樣本期間**：2008-06-04 ~ 2026-03-27，共 **4482** 個交易日
- **資料來源**：yfinance

> 注意：我們用 VIX3M 取代真正的 VIX 期貨曲線，因為 VIX3M 是免費可取得的近似指數（CBOE 編製，模擬 3 個月期 VIX 期貨）。VIX 期貨本身需要付費資料，且涉及期貨展期，把問題複雜化。VIX3M 在學術文獻（Mixon 2007, Johnson 2017）裡是常用的代理變數。

訊號的描述統計：

| 統計量 | 數值 |
|---|---|
| 平均 contango | 11.4% |
| 標準差 | 9.4% |
| 中位數 | 12.1% |
| 最小值 | -30.1% |
| 最大值 | 40.8% |
| 偏態 | -0.53 |
| 超額峰態 | 0.88 |

也就是說，**平均而言遠月比近月貴 11.4%**，是一個系統性的風險溢酬。

更關鍵的是 **regime 分佈**：

| Regime | 天數 | 佔比 |
|---|---|---|
| 全部 contango | 4110 | 89.6% |
| 陡峭 contango（>5%） | 3507 | 76.5% |
| Backwardation | 475 | 10.4% |

**76.5% 的時間市場都處於陡峭 contango**。這個事實會在後面變成關鍵。

## 五個策略 vs. 兩個基準

我們設計了以下策略，都是基於「12/VIX」這個 well-known 的 vol-targeting 邏輯——目標年化波動率 12%，每日權重 = 12/VIX_lagged，capped at 100%：

1. **Buy & Hold SPY**：滿倉 SPY，不擇時。
2. **Standard 12/VIX**（baseline）：純 vol-targeting，不看 contango。
3. **Contango Enhanced**：當 contango > 5% 時把權重再 +20%。
4. **Backwardation Reduced**：當 contango < 0（倒掛）時把權重砍 50%。
5. **Combined**：3 + 4 同時用。
6. **Contango Binary**：只有 contango > 0 才進場。
7. **Leverage-Matched 12/VIX**（這是真正的對照組）：純 vol-targeting，但平均槓桿故意調到跟 Combined 一樣。

第 7 個策略是這次研究的關鍵。後面會解釋為什麼。

## 全期間結果——表面上 contango 訊號「贏了」

| 策略 | CAGR | 年化波動 | Sharpe | 最大回撤 | 平均權重 |
|---|---|---|---|---|---|
| Buy & Hold | 11.0% | 19.9% | 0.475 | -50.7% | 1.00 |
| Standard 12/VIX | 6.95% | 9.49% | 0.603 | -23.2% | 0.69 |
| Contango Enhanced | 8.00% | 10.78% | 0.621 | -24.6% | 0.81 |
| Backwardation Reduced | 7.02% | 8.76% | 0.660 | -17.9% | 0.67 |
| **Combined** | 8.07% | 10.15% | **0.667** | -19.4% | 0.79 |
| Contango Binary | 7.13% | 8.50% | 0.692 | -16.6% | 0.65 |
| **Leverage-Matched 12/VIX** | 7.82% | 10.83% | 0.603 | -26.1% | 0.79 |

乍看 Combined 策略 Sharpe 0.667 比 Standard 0.603 好，看起來 contango 訊號真的有效——直到你看 Leverage-Matched 那一行。

## 為什麼 Combined 看起來贏？因為它**槓桿比較高**

這是整個故事的轉捩點。

仔細看 **平均權重**那一欄：
- Standard 12/VIX：0.69（保守）
- Combined：0.79（明顯加碼）
- Leverage-Matched 12/VIX：0.79（**故意調成跟 Combined 一樣**）

也就是說，Combined 平均槓桿是 Standard 的 **1.14 倍**。它表面上的 Sharpe 優勢，可能單純是因為**它平均吃了更多市場 beta**，而不是 contango 訊號真的在做什麼擇時。

於是我們做了 **Leverage-Matched 對照**：把 Standard 12/VIX 的權重等比例放大，讓平均權重 = 0.79（跟 Combined 一樣），但**不看 contango 訊號**。結果：

- Combined Sharpe = **0.667**
- Leverage-Matched Sharpe = **0.603**

差距只剩 +0.064。

接著跑 **Newey-West 修正後的 t 檢定**（針對日報酬序列相關性穩健）：

| 比較 | 年化日均報酬差（bps） | NW t-stat | NW p-value |
|---|---|---|---|
| Combined vs Standard | +1.05 | 1.748 | 0.081 |
| **Combined vs LevMatch（公平比較）** | **+0.24** | **0.368** | **0.713** |

**0.368 的 t 值，p = 0.71。這在統計上完全不顯著。**

## 這就是 NULL：訊號 ≈ 槓桿

研究誠實的結論很清楚：

**VIX 期貨曲線的 contango/backwardation 訊號，沒有比「直接把 vol-targeting 槓桿開大」帶來任何額外價值。**

為什麼？回頭看 regime 分佈——**76.5% 的時間都是陡峭 contango**。這代表「contango > 5% 就 +20% 權重」這個規則，幾乎等於「永遠 +20% 權重」。它根本不是擇時訊號，只是一個**換了名字的槓桿提升**。

換句話說，Contango Enhanced 策略真正在做的事是：「平均把槓桿從 0.69 拉到 0.81，順便丟一些 backwardation 期間的減碼」。前者貢獻了大部分績效；後者貢獻了背景雜訊。

## Cross-OOS 驗證再補一刀

我們把樣本切成 6 個子期間（GFC 復甦、長牛、COVID、後疫情、2024-2026 等），看 Combined vs Leverage-Matched 在每段的 Sharpe 差距：

| 期間 | Δ Sharpe（Combined - LevMatch） |
|---|---|
| 2014-2015 | -0.06 |
| 2016-2017 | -0.04 |
| 2018-2019 | -0.00 |
| 2020-2021 | +0.27 |
| 2022-2023 | -0.06 |
| 2024-2026 | +0.15 |

**6 段裡只有 2 段贏（33%）**。如果 contango 訊號真的有資訊量，這個 win rate 應該要顯著高於 50%。33% 看起來更像隨機——而且 2020-2021 那段「贏」很可能是因為 COVID 期間 backwardation 訊號剛好抓到一兩次大恐慌（樣本只有 253 天，雜訊很大）。

## 我們抓到自己的 Lookahead Bug

研究做到這裡，故事還沒講完。最值得寫的其實是這段。

最初的版本，我們用「**今天**的 contango 訊號」來決定「**今天**的權重」。乍看沒問題——資料本來就是日資料，contango 是當天計算的。

但仔細想：如果你想用 contango 訊號決定今天的部位，**你必須在開盤前就知道今天的 contango**。可是 contango 是用 VIX 和 VIX3M 計算的，而 VIX/VIX3M 都是市場交易期間動態變動，**今天的收盤值要等收盤後才知道**。

如果你用「今天的收盤 contango」決定「今天日內的部位」，你就是用未來資訊在交易。這就是經典的 **lookahead bias**。

修正方式很簡單：**所有訊號都 lag 一天**——用 t-1 的 contango 決定 t 的權重，用 t-1 的 VIX 決定 t 的 vol-targeting。

修正前的版本，Combined Sharpe 看起來更漂亮一些；修正後（也就是上面所有數字），訊號優勢就消失了。Results JSON 裡明確記錄：`"look_ahead_bias_fix": "All weights use lagged (t-1) contango and VIX signals"`。

這就是研究誠實原則的具體展現。如果我們選擇「不修正、發 paper、宣稱訊號有效」，數字會比較好看，但結論會是錯的。

## 為什麼要寫這篇文章？

因為**研究失敗的故事比成功的故事更重要**。

第一，市場上有不少 ETF 和策略宣稱用 VIX term structure 做訊號（VXX/VIXY 的 backwardation 反向策略、SVXY 的 contango harvesting 等等）。它們是不是真的有訊號價值？還是只是把「結構性放空 vol」這個 beta 換個包裝？K671 的結果暗示：**先把槓桿對齊，再來談訊號**。

第二，**lookahead bias 是量化研究最常見也最隱蔽的 bug**。它不會讓你的程式 crash，不會讓回測結果看起來離譜，它只會讓你的 Sharpe 多 0.05~0.2。然後你發 paper、上 strategy、開始虧錢，才意識到問題。我們在 K671 抓到了，但下一個實驗還會再犯——所以我們把每個訊號的 lag 規則寫進團隊的 `experiments.md`，作為 hard rule 持續檢查。

第三，**「槓桿錯覺」是策略比較最常被忽視的陷阱**。如果你比較兩個策略，但平均權重不一樣，那你比較的就不是「訊號好壞」而是「槓桿大小」。這個錯誤在 vol-targeting / risk-parity / managed futures 文獻裡反覆出現，學界已經有專門的 leverage-matched benchmark 慣例。我們希望透過 K671 把這個 discipline 帶進個人交易者的視野。

## 對讀者的實務建議

1. 看到任何宣稱「XX 訊號改善 Sharpe」的策略時，先問：**「跟 leverage-matched baseline 比過了嗎？」** 如果沒有，這個 Sharpe 改善很可能只是槓桿錯覺。
2. **76.5% 的時間都是 contango**——所以「contango 時加碼」幾乎等於「永遠加碼」。這不是擇時，這是更積極的部位。
3. 對波動率 ETF（VIXY、VXX、SVXY）感興趣的讀者：roll yield 是真實的——市場確實長期會付出 contango 溢酬給空 vol 的人。但這是 **risk premium 不是 alpha**。它的代價是 backwardation 期間的尾部風險（2018 年 2 月 XIV 的 96% 一日跌幅就是經典案例）。
4. 自己做回測時，**所有訊號都先 lag 一天**作為預設規則。如果你的策略加了 lag 後優勢就消失，那它本來就不是訊號，只是 lookahead。

## 結論

**VIX 期貨 contango/backwardation 訊號，在 SPY 擇時這個情境下，沒有比簡單的槓桿調整提供額外價值（NW t = 0.37, p = 0.71，6 個 OOS 段 win rate 33%）。**

這不是說 VIX 期貨曲線沒有任何資訊——它對波動率本身的預測（K638 在這方面有後續結果）、對 VIX 期貨展期收益的解釋、對市場恐慌程度的描繪，都還是有價值。但**用它來擇時 SPY 部位**這個特定應用，過了 leverage-matched 公平比較這一關後，就站不住腳了。

研究做到這裡，最該被記住的其實不是哪個 Sharpe 數字，而是兩件事：**先做 lag、再做比較**。前者防 lookahead bias，後者防槓桿錯覺。這兩個 discipline，比任何單一策略結果都更值得長期內化。

## 資料來源

- **實驗代號**：K671（VolPred 研究系統）
- **資料**：SPY、^VIX、^VIX3M（yfinance）
- **樣本期間**：2008-06-04 ~ 2026-03-27（4482 個交易日）
- **方法**：日頻 vol-targeting + contango 訊號疊加，Newey-West HAC 修正 t 檢定，6 段 cross-OOS 驗證
- **相關實驗**：K638（VIX term structure slope 對波動率本身的預測力，VolPred 內部研究）
- **學術參考**：Mixon (2007) JEF "The implied volatility term structure"、Johnson (2017) JFQA "VIX term structure"、Alexander & Korovilas (2013) JoR "Diversification of equity with VIX futures"

## 圖表

![K671 全期間 6 策略風險調整後報酬與最大回撤對比](experiments/k671/k671_strategy_summary.png)

![Cross-OOS 子期間：Combined 策略 vs 基準](experiments/k671/k671_cross_oos.png)
