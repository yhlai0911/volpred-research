---
title: 白天波動看得很清楚，為什麼模型還是會估錯？問題常常出在「隔夜那一下」
audience: general
experiment_refs: [K935]
description: K935 原始 YZ-style 結果仍顯示隔夜調整有用，但 canonical Yang-Zhang 2000 rolling rerun 沒有確認原本的 headline。
---

# 白天波動看得很清楚，為什麼模型還是會估錯？問題常常出在「隔夜那一下」

很多波動率模型都很愛用一種直覺資料：今天盤中最高多少、最低多少。

這樣做有個很吸引人的地方。你不用等更細的分時資料，只看每天的高低開收，就能大致量市場今天震得多厲害。

問題是，市場不只在白天動。

如果昨天收盤和今天開盤之間，剛好發生一個很大的跳空，你只看白天那段高低區間，就會漏掉真正讓投資人受傷的那一下。

這次實驗想回答的是：

**同樣是用每日高低開收來估波動，誰有把「隔夜跳空」算進去，誰沒有？這個差別到底大不大？**

## 先講更新後結論

原始 K935 的主要方向仍然成立：**只看盤中高低價的 Parkinson 版本，確實會漏掉隔夜 gap 這塊風險。**

但 24 小時 source review 後，我們補跑了一次更嚴格的 canonical Yang-Zhang 2000 rolling 版本，結果必須修正：

- 原始文章裡標成 `Yang-Zhang` 的版本，其實更精確應叫 **YZ-style overnight-adjusted proxy**
- 這個 YZ-style 版本仍明顯贏過 Parkinson：`QLIKE 1.541` vs `1.682`，改善約 `8.38%`
- 但 canonical Yang-Zhang 2000 rolling 版本沒有確認原本 headline：`QLIKE 2.232`，比 Parkinson 差約 `32.71%`
- 兩模型比較的統計值為 `+2.13`，方向是 canonical YZ 較差，但未達本平台最嚴格門檻

所以這篇現在最準確的讀法是：

**隔夜 gap 必須處理；原始 K935 的簡化隔夜調整 proxy 有用；但不能再把那個結果說成 canonical Yang-Zhang 2000 本身勝出。**

## 原始實驗看到什麼

原始 K935 把四種日線區間做法放在一起比：

1. `Parkinson`：只看最高價和最低價
2. `Garman-Klass`：開始把開盤到收盤也算進來
3. `Rogers-Satchell`：容許價格有方向漂移
4. `YZ-style`：把隔夜跳空加成獨立成分，但不是 canonical Yang-Zhang 2000 rolling 公式

然後每一種都拿去驅動同一種波動模型，再和兩個基準模型一起比較。

原始結果排序如下：

- 含額外恐慌資訊的基準模型：`1.480`
- `CARR_YZ-style`：`1.556`
- 老牌基準模型：`1.603`
- `CARR_RS`：`1.670`
- `CARR_GK`：`1.689`
- `CARR_Parkinson`：`1.692`

![Comparison of range-based variants and benchmarks](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/range_model_score_chart.png)

這張圖仍然可以看，但標籤要改讀成：圖中的 `CARR_YZ` 是 **YZ-style overnight-adjusted proxy**，不是 canonical Yang-Zhang 2000。

## 第一個重點：只看盤中高低價，仍然會漏掉重要風險

`Parkinson` 這種「只看白天高低價」的做法，在原始 K935 裡排名幾乎墊底。

這個方向沒有被推翻。

因為對投資人來說，昨天收盤 100、今天直接開在 95，這 5% 的落差是真實存在的風險；市場不會因為它發生在開盤前，就當它沒發生。

所以原始 K935 最穩的結論不是「某個名牌公式必勝」，而是：

**只看白天 range 會系統性漏掉隔夜 gap。**

## 第二個重點：簡化 proxy 有用，但 canonical 版本不確認

原始版本如果把 `Parkinson` 當作基準，三種修正版對它的改善幅度是：

- `Garman-Klass`：約 `0.19%`
- `Rogers-Satchell`：約 `1.30%`
- `YZ-style`：約 `8.04%`

![Improvement versus Parkinson after adding gap information](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/gap_adjustment_gain_chart.png)

補跑 canonical rolling Yang-Zhang 後，這裡要加一條限制：

**上面這個 8% 改善，是原始 YZ-style proxy 的改善，不是 canonical Yang-Zhang 2000 rolling estimator 的改善。**

canonical rerun 用的是 2000 日 rolling Yang-Zhang 方差：

`overnight variance + k * open-to-close variance + (1-k) * Rogers-Satchell variance`

結果是：

- `CARR_Parkinson`：`QLIKE 1.682`
- `CARR_YZ-style`：`QLIKE 1.541`
- `CARR_YZ_canonical_2000`：`QLIKE 2.232`

也就是說，把 canonical rolling estimator 直接拿來當 CARR target，在這個設定下反而太平滑，對隔日 `r²` 的校準沒有幫助。

## 第三個重點：這不是「隔夜 gap 不重要」

這次修正容易被誤讀成：既然 canonical YZ 沒贏，所以隔夜 gap 不重要。

這不是正確解讀。

正確解讀是：

1. `Parkinson` 漏掉隔夜 gap，這個問題仍然存在
2. 原始 K935 的 YZ-style proxy 把隔夜成分補回來後，確實改善了預測校準
3. 但 canonical Yang-Zhang 2000 是一個 multi-period rolling historical volatility estimator，不一定適合直接當一日 CARR target

這三件事可以同時成立。

## 這篇現在不能說到哪裡

更新後，這篇不能再說：

- canonical Yang-Zhang 2000 顯著勝 Parkinson
- 「Yang-Zhang」本身是四種版本裡穩定最強
- 原始 8% 改善就是 Yang & Zhang (2000) 原公式的勝利

可以說的是：

- `Parkinson` 忽略隔夜 gap，確實有風險漏算問題
- K935 原始的 YZ-style overnight-adjusted proxy 在同一 OOS 口徑下贏 Parkinson
- canonical rolling Yang-Zhang follow-up 不支持把原始結果升級成「Yang-Zhang 2000 公式勝出」

所以給一般讀者的 takeaway 應該更精準：

**不要忽略隔夜 gap；但也不要把「加了隔夜成分的簡化 proxy」和「canonical Yang-Zhang 2000 rolling estimator」混成同一件事。**

---

*本文基於 SPY 日線波動估計比較。原始 K935 資料期間 `2004-01-01` 至 `2025-12-31`，外樣本 `2016-01-04` 至 `2025-12-31`。2026-06-23 補跑 `experiments/k935/k935_canonical_yz_rerun.py`，同樣使用 SPY 日線 OHLC、OOS `2016-01-04` 至 `2025-12-31`，有效比較樣本 `2,508` 日。資料來源：yfinance。*

**修正紀錄（2026-06-23）**：原文將 `YZ-style overnight-adjusted proxy` 簡稱為 `Yang-Zhang`，容易被理解為 canonical Yang-Zhang 2000。補跑 canonical rolling YZ(2000) 後，headline 不成立：canonical CARR-YZ `QLIKE 2.232`，Parkinson `1.682`，原始 YZ-style `1.541`。本文已改為保留「隔夜 gap 需要處理」的方向性結論，撤回「canonical Yang-Zhang 2000 勝出」的表述。
