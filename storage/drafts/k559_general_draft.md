---
title: "相關性風險溢酬聽起來比 VIX 更高級，但 K559 的結論還是很樸素"
audience: general
status: draft
tags:
  - SPY
  - VIX
  - dispersion
  - 相關性
  - 策略研究
experiment_refs:
  - K559
---

# 相關性風險溢酬聽起來比 VIX 更高級，但 K559 的結論還是很樸素

市場上有一種很迷人的說法：

與其只看 `VIX` 這種「整體恐慌指數」，不如去看更深一層的東西，例如：

- 類股之間的分散度
- 相關性是不是突然上升
- 所謂的 `correlation risk premium` 有沒有被錯價

這些概念聽起來都比「12 ÷ VIX」高級得多。它們更像是職業交易員在看、研究報告會寫、訪談裡會冒出的詞。

`K559` 測的就是這個問題：

**如果你把這些相關性與 dispersion 訊號做成 timing 規則，真的能比已經很強的 `12/VIX` 再多挖出一點 alpha 嗎？**

答案很克制，也很一致：

**看起來有些小優勢，但整體還是不足以推翻 `12/VIX`。**

## 先看 full sample：很多變體都比基準稍高，但高得不夠乾淨

這份實驗的基準是 `12/VIX`，全樣本 Sharpe = `0.761`。

拿來比的相關性 / dispersion 變體一共有五種：

- dispersion level
- dispersion momentum
- correlation regime
- combined
- dispersion crash

![K559 full sample vs DM](experiments/k559/k559_general_fullsample_vs_dm.png)

如果只看 full sample Sharpe，很多版本都比基準略高：

- `S1 dispersion level`：`0.779`
- `S2 dispersion momentum`：`0.785`
- `S3 correlation regime`：`0.778`
- `S4 combined`：`0.805`
- `S5 dispersion crash`：`0.803`

看起來像是有進步，尤其 `S4` 和 `S5` 最容易讓人心動。

但這張圖的第二層才重要：右軸的兩模型比較統計。

幾個版本雖然數字比較好看，卻沒有通過嚴格門檻。真正過了 `|t| > 3` 的，只有 `S3 correlation regime` 一個版本，但它過關的方式很尷尬：**它顯著，卻不是代表「明顯更好」這種乾淨勝出故事。**

所以 `K559` 的第一個訊息很明白：

**不要把一點點較高的 Sharpe，自動當成新訊號已經成立。**

## 第二張圖更誠實：優勢會出現、消失、再出現，但沒有穩到能讓人放心

![K559 cross OOS consistency](experiments/k559/k559_general_cross_oos_consistency.png)

這張圖把事情講得更像真實世界。

我們把最有代表性的兩條線拉出來：

- `S2 dispersion momentum`：最穩的那條
- `S4 combined`：full sample 最亮眼的那條

對照 `12/VIX` 看三段外樣本：

`S2 dispersion momentum` 的確是 `3/3` 都贏，但贏得很薄：

- `OOS1`: `1.09` vs `1.04`
- `OOS2`: `0.94` vs `0.92`
- `OOS3`: `0.98` vs `0.95`

這種結果很微妙。它不能說完全沒價值，因為方向上是對的；但也很難說你真的找到一條新而穩的 alpha 線。

`S4 combined` 更典型：

- 前兩段沒什麼說服力
- 第三段突然拉出 `1.27`

這種 pattern 很常見：你把很多訊號揉在一起，總會有某一段特別好看。但如果好看的部分主要集中在單一窗口，它就比較像 regime coincidence，不像可以放心複製的規則。

## 最核心的原因：這些訊號其實沒有比 VIX 更獨立

`K559` 裡我覺得最重要的一個描述統計，不是策略績效，而是相關係數。

- dispersion 與 `VIX` 的相關大致接近零：`r = -0.055`
- implied correlation proxy 與 `VIX` 的相關則高得多：`r = 0.428`

這代表什麼？

代表你以為自己在看一個更新、更深的風險維度，但其中一大塊，其實 `VIX` 早就在講了。

如果一個訊號和 `VIX` 本來就高度重疊，那它要在策略層面提供穩定增量，本來就很難。它可能會在某些市場階段幫你多一點判斷，但長期跑下來，常常只是把同一個風險故事換個語言再講一次。

這也是為什麼 `K559` 的結論會直接把它和 `K415` 接起來：

**sector dispersion / correlation premium 這條線，到了策略層面，仍然沒有逃出 VIX-sufficiency。**

## 但這篇不是完全沒東西

`K559` 不是「全部失敗」那種 null。

它比較像一個高品質的 null result：

- 你確實看到一些方向正確的小改善
- `S2` 甚至在 `3/3` OOS 窗口都略勝
- placebo 也不是完全隨機，best strategy 的 permutation p-value 約 `0.033`

這些結果代表：相關性訊號不是胡說八道，它有一些結構。

只是那個結構還不夠厚，不足以讓你對著一個已經很強的 `12/VIX` 說：「好，從今天起我改用這套。」

這種結果在研究上其實很有價值，因為它幫你劃出邊界：

**這個方向值得懂，但還不值得上架。**

## 對投資人有什麼意思

如果你是一般投資人，`K559` 最有用的一句話其實很簡單：

**不要因為某個策略背後的名詞更複雜，就自動以為它一定比簡單規則更厲害。**

「dispersion」「implied correlation」「correlation premium」都很有研究味，也的確抓到某些市場結構。但在這份測試裡，它們能提供的增量還不夠大，不足以讓你放棄簡單、透明、已經被反覆驗證過的 `12/VIX`。

## K559 的一句話結論

相關性與 dispersion 訊號不是沒資訊，但它們對 `SPY` timing 的增量非常有限；就算某些版本在 full sample 或個別外樣本窗口看起來比較亮眼，整體仍不足以穩定打敗 `12/VIX`。`K559` 最終是一個乾淨的 `NULL RESULT`。

## 資料來源

- 實驗編號：`K559`
- 腳本：`experiments/k559/k559_conditional_dispersion.py`
- 結果：`experiments/k559/k559_conditional_dispersion_results.json`
- 研究主題：conditional dispersion / implied correlation / correlation risk premium
- 主要標的：`SPY`
- 核心結論：`VIX` 仍然吸收了大部分可用的相關性風險資訊，相關性策略沒有形成穩定增量
