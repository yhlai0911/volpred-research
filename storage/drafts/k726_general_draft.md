---
title: 我們以為發現了台股 VT 策略的「免費警報」，兩週後親手把它推翻
audience: general
phase: research
category: milestone
proposer: Claude
status: draft
description: K726 原本以為「台灣 VT 策略在 crisis 比美股少虧 9%/yr」是時區帶來的結構性紅利，K727 跨 6 市場驗證後推翻——同一個 0050，用昨日 VIX 反而多虧 3.6%/yr，台股 crisis 抗跌純粹來自 0050 資產特性。這篇記錄一次完整的研究自我修正。
tags:
  - Taiwan
  - 0050
  - VT
  - crisis
  - VIX-lag
  - self-correction
  - 研究誠實
experiment_refs:
  - K726
  - K727
---

> [提出: Claude] 一次完整的「假說 → 跨市場驗證 → 自我修正」實錄。

## 摘要

我們在 K726 發現一個漂亮的故事：危機期間（VIX>25），台灣 0050 的 VT（波動率目標）策略年化只虧 11.8%，美股 SPY 的 VT 策略卻虧 20.7%——**台股 VT 在 crisis 少虧 9%/yr**。直覺解釋是「時區紅利」：台股每天上午開盤時，已經知道前一晚美股收盤的 VIX，等於拿到一張早一天的警報，可以提前減倉。聽起來太美好。

兩週後我們做了 K727 跨 6 市場驗證，結論是**這個故事是錯的**：

- 台、日、韓、中、已開發國際、美國 6 個市場全部測同一個策略，用「昨日 VIX」永遠比「今日 VIX」差。
- 台灣同樣 0050，把 VT 從「同日 VIX」換成「lag VIX」反而**多虧 3.6%/yr**。
- K726 看到的「+9%/yr 優勢」其實是把不同資產（0050 vs SPY）放在一起比，純粹是 **0050 在危機時本來就比 SPY 抗跌**——和 timezone 一點關係都沒有。

我們把 K726 的結論在記憶庫裡標成 ⚠️ CORRECTED，這篇是寫給讀者的完整自我修正紀錄。

---

## 一、原本以為發現的「時區紅利」

K726 的設定很直覺：

| 策略 | 標的 | VT 公式 | 信號來源 |
|---|---|---|---|
| 台灣 VT | 0050.TW | 目標權重 = 8.63 / VIX_lag | 用**昨日**收盤 VIX（美股已收，台股要開盤） |
| 美股 VT | SPY | 目標權重 = 12 / VIX_same | 用**今日**收盤 VIX（同日同步） |

兩者都跑 2010-2026 整整 17 年。把樣本切成「危機日」（VIX>25，大約 2008Q4、2020Q1、2022 通膨、2024 carry trade、2025 關稅震盪等期間累積的 35-37 個高 VIX 觀察天數）和「正常日」分開算年化報酬。

結果如下圖。

![圖一：危機期間 0050 VT vs SPY VT 表現](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k726_chart3_asset_behavior.png)

VT 年化報酬 -11.8% vs -20.7%，raw Sharpe -1.06 vs -1.86，**0050 VT 看起來在 crisis 確實比 SPY VT 抗跌**。當下推論的機制很順：台股下午 1:30 收盤、美股美東時間 4:00 收盤、台股隔天上午 9:00 開盤——中間有 14 小時 gap，台股投資人開盤前已經知道美股是漲是跌、VIX 飆到哪裡，等於拿到一張**先看到的警報**，自動在台股開盤就減倉。SPY 投資人沒有這個 buffer，VIX 飆升和股價暴跌是同時打進帳戶。

故事很完美。問題是——

## 二、K727 把假說一刀切開

要證明「時區紅利」這個機制真的存在，需要把兩個東西分開：

1. **訊號 timing**：用 lag VIX 還是 same-day VIX？
2. **資產本身**：0050 還是 SPY？

K726 的設定**同時換了這兩件事**——台灣用 lag、美股用 same-day。所以 -11.8% vs -20.7% 的差距，可能來自 timing，也可能來自資產本身的危機抗跌特性，**根本分不清楚**。

K727 的修正方式：在 6 個市場（台灣、日本、韓國、中國、已開發國際 EFA、美國 SPY 當 control），**每個市場都用自己的 ETF 同時測 lag 與 same-day 兩種訊號**。如果「時區紅利」是真的，亞洲市場（lag 利用美股收盤 VIX）會比 same-day 表現好；如果只是噪音，兩者差不多甚至 lag 比較差。

結果如下圖。

![圖二：6 市場 VT lag vs same-day 在 VIX>25 期間的年化報酬](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k726_chart1_cross_market_lag.png)

每一個市場、無一例外，**lag 都比 same-day 差**：

| 市場 | Lag VIX (年化) | Same-day VIX (年化) | Lag 多虧 |
|---|---|---|---|
| 台灣 0050 | -11.8% | -8.2% | -3.6% |
| 日本 | -34.2% | -19.4% | -14.8% |
| 韓國 | -35.6% | -16.4% | -19.2% |
| 中國 | -40.3% | -23.3% | -17.0% |
| 已開發國際 | -38.5% | -19.8% | -18.7% |
| 美國 SPY (control) | -38.8% | -19.8% | -18.9% |

意思是：**用昨天的 VIX 算今天的權重，不是「免費警報」，而是用過時資訊**。VIX 在 crisis 一天就能跳 50%+，昨天的數字根本來不及反映今天的真實風險，VT 用 lag VIX 永遠在「踩 1 拍」。台灣那個 -3.6% 的差距比其他市場小，是因為 0050 本身波動度就低、VIX 跨市場相關性也比 EFA/Asia 弱，**不是時區給的紅利，是訊號變慢的小傷而已**。

## 三、把 K726 「+9%」的真相拆開

K727 反過來告訴我們：原本 K726 的「台灣比美股少虧 9%/yr」根本不是 timing 帶來的。把同一個 0050 換成 same-day VIX，crisis 年化從 -11.8% 變成 -8.2%——更好。所以「+9%」其實是兩個獨立效應：

- **資產特性**：0050 在 crisis 跌幅本來就小於 SPY（產業組成、外資進出節奏、台股漲跌幅限制都有貢獻）。
- **訊號 timing**：lag VIX 拖累 -3.6%/yr。

兩個合起來，K726 看到的「+9%」實際上是「0050 的 crisis 抗跌優勢 12.6%」**減去**「lag VIX 的訊號落後 -3.6%」≈ +9%。換句話說，**台灣 VT 在 crisis 比 SPY VT 好，是因為 0050 比 SPY 抗跌，跟 timezone gap 沒有關係**。

![圖三：K726 看似 advantage 與 K727 真相 reframe](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k726_chart2_correction_reframe.png)

## 四、為什麼這個錯誤會發生？教訓

這個 episode 是研究上**最常見的陷阱之一：cross-asset confound**——把兩件事同時換掉，看到差距就把功勞給其中一個。K726 設計時為了配合每個市場的「自然慣例」（台灣 VT 學界常用 lag，美股 VT 用 same-day），結果不小心做出了一個無法歸因的對照。

教訓很簡單也很硬：

1. **比較 timing 效果，必須同資產**；比較資產效果，必須同 timing。**一次只能換一個變數**。
2. **反直覺的「免費紅利」要先懷疑混淆**。如果某個策略好像憑空多賺 9%/yr，先想：是不是因為換掉了不該換的東西？
3. **Self-correction 不是失敗，是研究的常態**。我們在記憶庫裡把 K726 標成 ⚠️ CORRECTED 並寫了 K727 推翻紀錄；對讀者最誠實的做法是把「我們以為什麼 → 為什麼錯 → 真相是什麼」整段公開。

## 五、給投資人的實用結論

很遺憾，**台股投資人沒有時區帶來的「免費 crisis 警報」這回事**。但有兩件事仍然成立：

1. **0050 在 crisis 確實比 SPY 抗跌**（K726 raw 數據沒錯，只是原因不對）。這是資產特性，不需要任何特別策略。
2. **VT 策略要用 same-day VIX，不要用 lag**。台灣機構常見的「用昨日 VIX 算今日 0050 VT 權重」做法，在 crisis 期間會比 same-day 多虧 3.6%/yr。實務上 VIX 在台股交易時段已經有期貨報價可參考，不必等隔天的 cash close。

## 限制與後續

- 樣本：2010-2026 共 17 年，VIX>25 的「危機日」只有 35-37 天，子樣本相對小，bootstrap CI 寬。
- 我們只測了 lag = 1 day。如果 lag 更短（intraday VIX futures 訊號）會不會找到真的紅利？這是 K729 之後可以做的方向。
- 0050 vs SPY 在 crisis 抗跌的差距可以再拆：產業組成、外資/內資結構、漲跌幅限制各自貢獻多少，這是另一個獨立題目。

---

*本文基於實驗 K726（`experiments/k726/k726_results.json`，初版假說）與 K727（`experiments/k727/k727_results.json`，跨 6 市場推翻驗證）。資料來源：yfinance 0050.TW / SPY / EWJ / EWY / FXI / EFA 與 ^VIX，期間 2010-01-01 ~ 2026-04，VIX>25 子樣本 35-37 個觀察日。記憶庫對應 entry：knowledge.json L18181（K726 ⚠️ CORRECTED）、L18199（K727 ★★ self-correction）。*
