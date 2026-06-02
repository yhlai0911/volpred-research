---
title: "把 GARCH 改聰明反而更笨：3 種 STGARCH 在 SPY 上全輸給老派 GJR"
audience: research
status: draft
phase: garch
tags:
  - 美股
  - SPY
  - 波動率
  - GARCH
  - 模型比較
  - 風險管理
experiment_refs:
  - K431
---

# 把 GARCH 改聰明反而更笨：3 種 STGARCH 在 SPY 上全輸給老派 GJR

做量化研究有個常見的誘惑：覺得舊模型太陽春，多加一層邏輯應該會更準。

這次我們直接拿 SPY 2005-2026 的日報酬資料測一個想法。把標準 GARCH 加上 smooth transition 機制，讓波動率可以依照「現在市場是什麼狀態」平滑切換不同係數。試了三種狀態判斷指標：VIX、絕對報酬、滯後波動率。樣本外 2023-01 到 2024-12 共 502 天。

結果一張圖講完。

![5 模型 QLIKE 樣本外比較](storage/drafts/article_images/k431_qlike_bar.png)

| 模型 | QLIKE | 比 GJR 差多少 | DM 比較 |
|---|---:|---:|---|
| GJR-GARCH(1,1) | 0.5588 | — | baseline |
| GARCH(1,1) | 0.5890 | +5.40% | GJR 勝（p=0.008）|
| STGARCH-lagvol | 0.6111 | +9.36% | GJR 勝（p<0.001）|
| STGARCH-VIX | 0.6149 | +10.04% | GJR 勝（p<0.001）|
| STGARCH-\|ret\| | 0.6241 | +11.69% | GJR 勝（p<0.001）|

QLIKE 是波動率預測常用的 loss function，越低越準。GJR 完勝，三種 STGARCH 全敗，差距 9-12%，DM 兩兩比較全部達顯著水準。

![DM 顯著性檢定 — 所有候選模型都顯著輸給 GJR](storage/drafts/article_images/k431_dm_diffpct.png)

DM 是 Diebold-Mariano 預測比較檢定。p 值全部小於 0.01，最嚴格的 STGARCH-|ret| 甚至到 4.2e-6。不是邊際差距，是穩定可量的劣勢。

## 多估七個參數，買到什麼

STGARCH 加上 smooth transition function 之後，需要額外估計 transition 平滑度、threshold 位置、兩個 regime 各自的 GARCH 係數。算下來比 GJR 多估 7 個參數左右。

照直覺，模型自由度越高、越靈活，應該能擬合得更細。樣本內的 log-likelihood 確實提高了，但搬到樣本外，多估出來的參數沒有換到任何預測精度，反而把 502 天的 QLIKE 推高 9-12%。

問題出在哪？GJR 用一個非常便宜的設計，就把美股波動率最關鍵的特性吃掉了：壞消息（負報酬）造成的波動率衝擊比好消息大。一個 dummy 變數，一個額外參數，就抓住了 leverage effect 八成的訊號。

STGARCH 想用 VIX 或滯後資訊重新捕捉「市場到底處於什麼狀態」，但 SPY 的波動率動態裡，超出 GJR 之外可以被模型化的部分太薄，平滑切換機制反而引入估計噪音。

## QLIKE 天花板真的存在

過去三年我們在 SPY 上跑過 100 多個 GARCH 變體：BEKK、GJR、HAR-RV、加 VIX 的 GARCH-X、HEAVY、加跳躍項、加 EVT 尾部修正。每一個的樣本外 QLIKE 都卡在 0.55-0.60 區間。

K431 等於再多一筆證據：複雜化的邊際報酬在 SPY 已經逼近零。想要再壓低 QLIKE，靠的是更高頻的資料（5 分鐘已實現波動率）、或者跳到完全不同典範（HAR-RV、神經網路）；繼續疊 GARCH 內部結構不會有結果。

## 對交易與風控的具體意義

如果你的風險模型還在用 GARCH(1,1)，把它升級成 GJR 是免費午餐。同樣 1 個參數，K431 量到的 QLIKE 改善是 5.4%，DM 顯著。

如果你已經在用 GJR，看到論文或產品推銷 STGARCH、雙 regime GARCH、Markov-switching GARCH，這次的數字可以當參考：在 SPY 這種高度被研究的資產上，多估出來的參數沒有換回預測精度。

新模型想要被認真考慮，門檻不是「樣本內 log-likelihood 提高」，而是「樣本外 QLIKE 在獨立的兩年區間打贏 GJR、而且 DM 達顯著水準」。K431 的三種 STGARCH 全部沒過這個門檻。

研究失敗也是結果。把 QLIKE 卡在 0.55 的事實寫清楚，下次知道往哪邊找新訊號，不要在原地多估參數。

---

**數據來源**：SPY 日收盤資料 2005-01-04 到 2026-03-24，OOS 2023-01-01 到 2024-12-31 共 502 筆。完整實驗腳本與 results JSON 在 `experiments/k431/`。

**K431 結論**：STGARCH does NOT beat GJR. Best ST: STGARCH-lagvol diff=9.362%. QLIKE ceiling confirmed.
