# 強美元環境下，哪些資產的波動率真的會被拉高？HAC 校正後只剩 USO 站得住

K1439 原先發佈時，主結論寫成「5 個資產裡有 4 個在強美元環境下波動率顯著偏高」。這句話現在要收回一半以上。原因不是資料變了，而是推論方式補上了本來缺的那一層：21 日滾動已實現波動率彼此高度重疊，相鄰樣本的自相關非常強，直接用 Welch t-test 會把標準誤壓得太小。Codex follow-up 補上 OLS-HAC / Newey-West（`maxlags=21`）之後，原本 4/5 Bonferroni 顯著的結果，縮成只剩 **USO 1/5** 還站得住。

樣本本身沒有變。資料還是 2010-01-04 到 2026-06-05 的 4,131 個交易日，資產還是 EEM、GLD、DBC、USO、DBB，美元體制代理仍是 UUP。體制定義也維持兩條路徑：level 用 UUP 相對 100 日均線的 z-score，trend 用過去 60 日報酬正負，兩者都先 `shift(1)` 避免 lookahead。這次修正的是「怎麼判斷差異夠不夠穩」。

## 更正後的正式結論：naive Welch 看起來是 4/5，但 HAC 後只剩 USO

先把 level 體制的兩套結果放在一起看：

| 資產 | strong-weak RV 差值 | Welch p | Welch Bonferroni | HAC t | HAC p | HAC Bonferroni |
|------|--------------------|---------|------------------|-------|-------|----------------|
| EEM  | +0.0132 | 3.0e-05 | ✔ | +1.10 | 0.2692 | ✘ |
| GLD  | +0.0016 | 0.4663  | ✘ | +0.20 | 0.8389 | ✘ |
| DBC  | +0.0179 | 4.9e-16 | ✔ | +2.13 | 0.0331 | ✘ |
| USO  | +0.0588 | 3.3e-23 | ✔ | +2.61 | 0.0091 | ✔ |
| DBB  | +0.0097 | 3.8e-06 | ✔ | +1.23 | 0.2202 | ✘ |

差值方向幾乎沒變，但顯著性掉得很明顯。EEM、DBC、DBB 在 naive Welch 下都過 Bonferroni，換成 HAC 後全部掉出 α=0.01。只有 USO 還留在門內，代表「強美元下油的波動率偏高」這件事，不只是大樣本把 t 值堆上去，而是在 overlap-aware 的標準誤下仍然成立。

![強美元 vs 弱美元：level 體制下各資產 21 日已實現波動率平均值](experiments/k1439/figures/rv_by_regime_level.png)

## 趨勢體制定義也重跑一次，答案還是一樣

如果把強弱美元改成 trend 體制，故事沒有變回原版。HAC 後仍然只有 USO 通過 Bonferroni；EEM、DBC、DBB 依舊只剩方向一致，沒有留下 paper-grade 顯著性。

| 資產 | strong-weak RV 差值 | Welch p | Welch Bonferroni | HAC t | HAC p | HAC Bonferroni |
|------|--------------------|---------|------------------|-------|-------|----------------|
| EEM  | +0.0151 | 2.5e-08 | ✔ | +1.49 | 0.1361 | ✘ |
| GLD  | -0.0013 | 0.5475  | ✘ | -0.16 | 0.8696 | ✘ |
| DBC  | +0.0160 | 9.1e-17 | ✔ | +2.20 | 0.0275 | ✘ |
| USO  | +0.0569 | 3.8e-29 | ✔ | +2.90 | 0.0038 | ✔ |
| DBB  | +0.0083 | 1.3e-05 | ✔ | +1.14 | 0.2531 | ✘ |

這個 cross-check 很重要，因為它把新的 canonical 結論釘得更窄也更穩：**不是「強美元會普遍抬高跨資產波動率」；而是「在這 5 個資產裡，USO 是唯一在兩種體制定義、兩層 Bonferroni、以及 HAC 校正後都留下來的標的」。**

![強美元 vs 弱美元：trend 體制下各資產 21 日已實現波動率平均值](experiments/k1439/figures/rv_by_regime_trend.png)

## 為什麼這次修正不能只當成註腳

關鍵在 21 日 RV 的重疊性。K1439 的 ACF(1) 幾乎貼在 1 附近：EEM 0.989、GLD 0.984、DBC 0.984、USO 0.990、DBB 0.984；連 ACF(21) 都還有 0.43 到 0.59。這種資料結構下，把每天的 RV 當成彼此接近獨立，結論會太樂觀，這不是 wording 問題，是 inference layer 的問題。

所以現在的口徑應該分兩層講：

1. **描述性層次**：EEM、DBC、USO、DBB 的 strong-minus-weak RV 差值都為正，方向上確實像是強美元對風險資產和商品帶來較高波動。
2. **正式推論層次**：補上 HAC/Newey-West 後，只有 USO 在 level 與 trend 兩種 regime 定義下都通過 Bonferroni。其他資產最多只能說「方向一致、證據偏弱」，不能再寫成已確認的普遍效果。

## 研究與實務上現在能說什麼

如果目的是做 reader-facing 的誠實總結，最重要的更新只有一句：**K1439 不再支持「4/5 資產顯著」的廣泛敘事，現在只支持「油（USO）對強美元體制最敏感，而且這個結果在嚴格推論下仍然成立」。**

如果目的是拿去做模型先驗，美元體制變數仍值得留在觀察名單裡，但優先順序要改。USO 可以當成有正式統計支撐的候選外生變數；DBC、DBB、EEM 則比較像需要下一輪 moving-block bootstrap 或子期間切分再確認的 suggestive evidence。GLD 目前仍然是乾淨的 null。

*本文基於實驗 K1439（腳本：`experiments/k1439/k1439.py`；重現腳本：`experiments/k1439/reproduce.py`；結果：`experiments/k1439/k1439_results.json`）。資料來源：yfinance，期間：2010-01-04 至 2026-06-05，樣本：4,131 個交易日。2026-06-13 起，HAC/Newey-West（`maxlags=21`）為 canonical inference；Welch t-test 僅保留為描述性統計。*
