# K908: MF-GJR + Student-t/HistSim — VaR/ES Complete Evaluation

## 問題
K889 的 MF-GJR 預測改善 -6.6% QLIKE（Harvey PASS），但 **1% VaR 全部 FAIL**（因為用 Normal distribution）。用 Student-t 或 HistSim 能否修復？

## 動機
- K889: MF-GJR 是目前最佳預測模型
- K802/K825: Student-t 和 HistSim 可修復 GJR 的 VaR
- 缺口：最佳預測模型 + 最佳分配的組合尚未驗證

## 方法
- 5 模型-分配組合：GJR+Normal, GJR+Student-t, MF-GJR+Normal, MF-GJR+Student-t, MF-GJR+HistSim
- 3 資產：SPY, QQQ, 0050.TW
- OOS: 2019-01 ~ 2026-03 (~1821 天)
- Student-t df 每 63 天 refit，含 sqrt((df-2)/df) scale correction
- 評估：Kupiec + Christoffersen + Basel Trinity, Acerbi-Szekely ES Z-test, Fissler-Ziegel joint scoring

## 結果（★★★）
- **MF-GJR + HistSim: 全部 3 資產 1% 和 5% VaR Trinity PASS (6/6)**——universal solution
- MF-GJR + Student-t: SPY 和 0050.TW Trinity PASS，QQQ FAIL（尾部較輕）
- Student-t df: SPY ~6-9, QQQ ~6-11, 0050.TW ~4.7-6.6（台股最厚尾）

## 結論
**MF-GJR(VIX) + HistSim = 目前最佳完整方案**：最佳預測 + 最佳風控，兩個維度獨立優化。

## 數據來源
yfinance（SPY, QQQ, 0050.TW, ^VIX），2005-2026
