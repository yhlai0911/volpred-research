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
  - K431_v2
---

# 把 GARCH 改聰明反而更笨：3 種 STGARCH 在 SPY 上全輸給老派 GJR

做量化研究有個常見的誘惑：覺得舊模型太陽春，多加一層邏輯應該會更準。

這次我們直接拿 SPY 2005-2026 的日報酬資料測一個想法。把標準 GARCH 加上 smooth transition 機制，讓波動率可以依照「現在市場是什麼狀態」平滑切換不同係數。試了三種狀態判斷指標：VIX、絕對報酬、滯後波動率。樣本外 2023-01 到 2024-12 共 502 天。

2026-06-16 的 v2 重跑修正了三個實作問題：滯後波動率 transition variable 不再用 full-sample GJR、GARCH/GJR baseline 改成真正 t-1 資訊的一步預測、STGARCH OOS state propagation 改成用當期 forecast variance 傳遞。結論沒翻轉，但精確差距比初版小。

結果一張圖講完。

![5 模型 QLIKE 樣本外比較](storage/drafts/article_images/k431_qlike_bar.png)

| 模型 | QLIKE | 比 GJR 差多少 | DM 比較 |
|---|---:|---:|---|
| GJR-GARCH(1,1) | 0.5588 | — | baseline |
| STGARCH-lagvol | 0.5870 | +5.05% | GJR 勝（p=0.014）|
| STGARCH-VIX | 0.5883 | +5.28% | GJR 勝（p=0.013）|
| GARCH(1,1) | 0.5890 | +5.40% | GJR 勝（p=0.008）|
| STGARCH-\|ret\| | 0.5957 | +6.60% | GJR 勝（p=0.001）|

QLIKE 是波動率預測常用的 loss function，越低越準。GJR 仍是第一，三種 STGARCH 全敗，但 v2 後的差距是 5.05-6.60%，不是初版的 9-12%。

![DM 顯著性檢定 — 所有候選模型都顯著輸給 GJR](storage/drafts/article_images/k431_dm_diffpct.png)

DM 是 Diebold-Mariano 預測比較檢定。這裡用的是 conventional non-HAC 雙邊 DM；三個 STGARCH 都輸給 GJR，其中 |ret| 版本最弱（p=0.0014），VIX 與 lagvol 版本則落在 conventional 5% 顯著、但不是 Harvey |t|>3 等級。這點比初版寫得更保守，也更準確。

## 多估四個參數，買到什麼

STGARCH 加上 smooth transition function 之後，需要估計 transition 平滑度 γ、threshold 位置 c、兩個 regime 的 GARCH 係數。照這支程式的 free parameters 算，STGARCH 是 9 個，GJR 是 5 個，差 4 個。

照直覺，模型自由度越高、越靈活，應該能擬合得更細。v2 把 likelihood 常數補回同一尺度後，STGARCH-VIX 的樣本內 log-likelihood 確實高於 GJR；但搬到樣本外，多估出來的參數沒有換到預測精度，502 天的 QLIKE 仍高出 GJR 約 5-7%。

問題出在哪？GJR 用一個非常便宜的設計，就把美股波動率最關鍵的特性吃掉了：壞消息（負報酬）造成的波動率衝擊比好消息大。一個 dummy 變數，一個額外參數，就抓住了 leverage effect 八成的訊號。

STGARCH 想用 VIX 或滯後資訊重新捕捉「市場到底處於什麼狀態」，但 SPY 的波動率動態裡，超出 GJR 之外可以被模型化的部分太薄，平滑切換機制反而引入估計噪音。

## QLIKE 天花板真的存在

過去三年我們在 SPY 上跑過大量 GARCH 系與日頻波動率模型：GJR、HAR-RV、加 VIX 的 GARCH-X、HEAVY、加跳躍項、加 EVT 尾部修正、regime 類模型。多數有效模型的 OOS QLIKE 都擠在很窄的區間；K431 v2 的三組 STGARCH 也只是落在 0.587-0.596，沒有把 GJR 的 0.5588 壓下去。

K431 v2 等於再多一筆證據：複雜化的邊際報酬在 SPY 已經很薄。想要再壓低 QLIKE，下一步不該只是繼續疊 GARCH 內部結構，而是換資料粒度或換 target，例如 5 分鐘已實現波動率、日內/隔夜分解、或更直接的 realized-measure 模型。

## 對交易與風控的具體意義

如果你的風險模型還在用 GARCH(1,1)，升級成 GJR 仍有清楚的 OOS 改善：K431 v2 量到的 QLIKE 改善是 5.4%，conventional DM p=0.008。不過若採 Harvey |t|>3 的研究上架門檻，這一格還不算強證據。

如果你已經在用 GJR，看到論文或產品推銷 STGARCH、雙 regime GARCH、Markov-switching GARCH，這次的數字可以當參考：在 SPY 這種高度被研究的資產上，多估出來的參數沒有換回預測精度。

新模型想要被認真考慮，門檻不是「樣本內 log-likelihood 提高」，而是「樣本外 QLIKE 在獨立的兩年區間打贏 GJR、而且通過嚴格的 DM / Harvey / bootstrap 檢查」。K431 v2 的三種 STGARCH 全部沒過這個門檻。

研究失敗也是結果。把 GJR 仍守住 SPY 日頻 QLIKE 第一名的事實寫清楚，下次知道往哪邊找新訊號，不要在原地多估參數。

---

**數據來源**：SPY 日收盤資料 2005-01-04 到 2026-03-24，OOS 2023-01-01 到 2024-12-31 共 502 筆。v2 完整實驗腳本與 results JSON 在 `experiments/k431/k431_stgarch_v2.py` 與 `experiments/k431/k431_stgarch_v2_results.json`。

**K431 v2 結論**：STGARCH does NOT beat GJR. Best ST: STGARCH-lagvol diff=5.050%. QLIKE ceiling confirmed.

**2026-06-16 v2 更正**：初版引用的 STGARCH 數字受 lagvol transition lookahead、baseline forecast slice 不對稱、STGARCH state propagation 與 likelihood 尺度問題影響。v2 修正後，headline 結論不變，但 STGARCH 與 GJR 的差距從 9-12% 改為 5-7%，DM 強度也改為 conventional 5% 到 1% 等級。
