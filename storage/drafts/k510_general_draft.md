---
title: "把成交量塞進 GARCH 真的會更準嗎？K510 對經典論文的答案偏負面"
audience: general
status: draft
tags:
  - GARCH
  - 成交量
  - SPY
  - QQQ
  - 波動率預測
experiment_refs:
  - K510
---

# 把成交量塞進 GARCH 真的會更準嗎？K510 對經典論文的答案偏負面

金融市場裡有一個很有名的直覺：

**價格波動大，是因為資訊很多；資訊很多時，成交量也會放大。**

如果這個故事是真的，那把成交量直接加進波動率模型，好像就很合理。這不只是一個散戶級的想法，學術上也有經典版本。`Lamoureux & Lastrapes (1990)` 就曾提出，當你把 volume 放進 `GARCH`，原本很高的 volatility persistence 會明顯下降，看起來像是「其實你以為的 GARCH 持續性，有一大塊只是成交量在代打」。

`K510` 測的，就是這個故事到了今天還站不站得住。

答案很簡單：

**樣本內，那個經典現象確實看得到；但一進外樣本，成交量版 GARCH 大多不是更準，而是更差。**

## 先看最重要的一張圖：大多數 volume 版本都讓 QLIKE 變差

這份實驗用的是 `SPY` 與 `QQQ` 的日資料，期間 `2010-01-01` 到 `2025-12-31`，外樣本從 `2023-01-01` 開始。基準模型是 `GJR-GARCH`，然後拿四種 volume 規格去比：

- raw volume
- detrended volume（最接近經典論文版本）
- log volume
- volume z-score

![K510 OOS QLIKE changes](experiments/k510/k510_general_oos_qlike_changes.png)

圖的讀法很直接：**柱子越高，代表比 baseline 更差。**

結果幾乎一面倒：

- `SPY raw volume`：`+0.58%`
- `SPY detrended volume`：`+10.79%`
- `SPY log volume`：`+0.02%`
- `SPY z-score`：`+3.31%`
- `QQQ raw volume`：`+0.50%`
- `QQQ detrended volume`：`+1.82%`
- `QQQ z-score`：`+2.36%`

只有一個例外看起來接近持平：

- `QQQ log volume`：`-0.01%`

但這也只是接近零，沒有形成可宣稱的優勢。

更關鍵的是，幾個最常被認為「資訊含量比較高」的版本，退步反而最明顯：

- `SPY z-score`：兩模型比較統計 `-2.067`
- `QQQ detrended volume`：`-2.526`
- `QQQ z-score`：`-3.045`

也就是說，不只是「沒變好」，而是有些版本已經差到不能再說是雜訊。

## 但經典論文不是完全錯，它樣本內真的有那個現象

這篇最值得注意的，不是把舊文獻一筆抹掉，而是把它拆成兩段看。

`K510` 確實重現了經典論文最有名的那個畫面：一旦把 volume 項放進模型，樣本內估出來的 persistence 會大幅下降。

![K510 persistence versus OOS](experiments/k510/k510_general_persistence_vs_oos.png)

例如：

- `SPY` baseline persistence = `0.9616`
- `SPY detrended volume` = `0.7969`
- `SPY z-score` = `0.8261`

`QQQ` 也差不多：

- baseline = `0.9645`
- detrended volume = `0.8092`
- z-score = `0.8887`

這個落差不小。從樣本內看，你很容易得到一個很漂亮的故事：

> 你看，加入成交量之後，GARCH 的「高持續性」明顯掉下來了，所以原本那塊 persistence 其實只是資訊到達造成的假象。

問題是，右邊那張圖把這個故事戳破了。

雖然 persistence 在樣本內掉下來了，但外樣本預測並沒有跟著變好，反而經常更差。這意味著：

**那個 persistence 的下降，可能比較像樣本內重新分配參數的會計效果，不是能轉成真實預測優勢的結構洞見。**

## 為什麼成交量這件事會卡在這裡

最合理的解釋不是「成交量完全沒資訊」，而是它的資訊對 daily volatility forecasting 來說，沒有你想像中那麼乾淨。

可能的原因包括：

- 成交量本身帶有趨勢、制度變遷與市場結構雜訊
- 同樣的高成交量，有時是資訊湧入，有時只是 ETF 再平衡、風格輪動或事件交易
- 你在樣本內看到的關係，未必能穩定延續到下一段市場環境

這也解釋了為什麼 `detrended volume` 看起來理論上最漂亮，實際上卻不穩。把 volume 做得越「聰明」，不代表它就越能提供可泛化的預測訊號。

## 對投資人真正有用的意思

`K510` 的價值，不只是替一個 old-school 論點打叉，而是提醒我們一個很常見的研究陷阱：

**不要把樣本內參數變漂亮，誤認成模型真的更有用。**

如果你在做波動率預測，看到某個新變數讓：

- persistence 降低了
- 參數更「合理」了
- 故事更符合直覺了

先不要急著覺得自己找到答案。真正該問的是：

> 外樣本有沒有更準？

在 `K510` 這裡，答案大多是沒有。

這種負結果其實很乾淨。因為它不是「成交量偶爾沒用」，而是多種規格都測過之後，仍然看不到穩定改善。這對後續研究反而很有方向性：與其再花時間把 volume 包裝成不同函數形狀，不如把注意力放到更直接的 forward-looking 變數上。

## K510 的一句話結論

把成交量加進 `GARCH`，可以在樣本內把 persistence 壓低，重現經典文獻的視覺效果；但到了外樣本，這個效果大多沒有變成更準的波動率預測，反而常常讓結果更差。

## 資料來源

- 實驗編號：`K510`
- 腳本：`experiments/k510/k510_volume_garch.py`
- 結果：`experiments/k510/k510_volume_garch_results.json`
- 資料來源：`yfinance (SPY, QQQ daily OHLCV)`
- 樣本期間：`2010-01-01` 至 `2025-12-31`
- 外樣本起點：`2023-01-01`
- 主要評估：`QLIKE`、`MSE`、兩模型比較檢定（Newey-West HAC）
- 核心結論：`Volume-GARCH` 在樣本內能重現 `Lamoureux & Lastrapes (1990)` 的 persistence drop，但外樣本大多退步，整體 verdict 為 `NEGATIVE`
