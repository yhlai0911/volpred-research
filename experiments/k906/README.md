# K906: SPY HAR-RV Preliminary Horse Race

## 問題
HAR-RV 在 TAIFEX 數據上以 DM t=-11.14 壓倒 GJR（K849），但那是在 RV-only target 上的 mechanical result。**在公平的統一 target（Patton 2011 QLIKE on r²、Hansen & Lunde 2005 RV_total）上，HAR-RV 是否仍勝 GJR？**

## 動機
- K849：HAR-RV 在 RV target 上勝 GJR（mechanical，HAR 本來就預測 RV）
- K782：HAR 在 r² target 上全輸 GJR（首次修正）
- 首次用 SPY 5-min 數據驗證

## 方法
- SPY 55 天 5-min 數據（2026-01-14 ~ 2026-04-02）
- HAR-RV：Corsi (2009) 標準 HAR，expanding window OLS
- GJR-GARCH：日頻 2000 天 window，逐日遞迴 OOS
- 公平比較：QLIKE on r²、QLIKE on RV_total、Spearman、DM test

## 結果
- **GJR 在兩個統一 target 上大勝**：QLIKE on r² = 1.14 vs HAR 41,845
- **根本原因：SPY 隔夜波動佔總波動 ~50%**，HAR 只捕捉日內
- VaR：GJR 2/29 OK，HAR 6/29 FAIL (20.7%)
- **PRELIMINARY**：29 天 OOS 遠不夠正式結論

## 結論
HAR-RV 需要 Hansen & Lunde (2005) 隔夜調整才能公平競爭。等 252+ OOS 天再做正式結論。

## 數據來源
yfinance 5-min intraday + daily（SPY, ^VIX）
