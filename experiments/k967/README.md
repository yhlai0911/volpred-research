# K967: Probabilistic Volatility Quantile Forecasting

## 動機
標準 GARCH/HAR 產出點預測（條件變異數的期望值），但實務上投資人需要分位數預測：波動率有多大機率超過某個閾值？本實驗比較三類方法產出條件分位數的能力。

## 方法
1. **GJR-GARCH(1,1) + Student-t**：從參數分配直接計算 VaR = mu + sigma * q_alpha * sqrt((nu-2)/nu)
2. **CAViaR (SAV, AS)**：Engle & Manganelli (2004) 直接建模 VaR 動態 Q_t = f(Q_{t-1}, r_{t-1})
3. **Quantile Regression**：|r_{t-1:5}| + VIX_{t-1} 作為解釋變數

## 數據
- SPY 2006-01-04 ~ 2026-04-06（5094 obs）
- IS: 2006-2020（3775 obs），OOS: 2021-2026（1319 obs）
- 分位數水準：alpha = 0.01, 0.05, 0.10, 0.90, 0.95, 0.99

## 核心結果

### CAViaR 在所有分位數都是最佳模型（Pinball Loss 最低）

| Alpha | GARCH PL | CAViaR PL | QR PL | Best |
|-------|---------|-----------|-------|------|
| 0.01 | 0.000356 | **0.000342** | 0.000344 | CAViaR |
| 0.05 | 0.001175 | **0.001164** | 0.001171 | CAViaR |
| 0.10 | 0.001920 | **0.001898** | 0.001905 | CAViaR |
| 0.90 | 0.001591 | **0.001557** | 0.001582 | CAViaR |
| 0.95 | 0.000962 | **0.000928** | 0.000949 | CAViaR |
| 0.99 | 0.000277 | **0.000275** | 0.000276 | CAViaR |

### Coverage 準確度
- **CAViaR**：所有分位數 Kupiec test p > 0.35（無法拒絕正確覆蓋）
- **GARCH**：5%/10% 下尾和 95%/99% 上尾 Kupiec 拒絕（覆蓋偏離）
- **QR**：多數可接受，但 95% 分位偏離

### DM Test
- 唯一 Harvey (2016) 顯著差異：alpha=0.95，GARCH vs CAViaR，t=3.079（CAViaR 更好）
- 其餘分位數差異不顯著（|t| < 3.0）

### VIX 增量預測力
- alpha=0.01：VIX 改善 QR pinball loss 5.09%，DM t=3.595 **顯著**
- alpha=0.05：改善 2.82%，DM t=2.191（不顯著）
- alpha=0.10：改善 2.59%，DM t=2.533（不顯著）
- VIX 對極端分位數有統計顯著的增量預測力

## 結論
1. CAViaR（AS 變體）在所有分位數都優於 GARCH-based VaR 和 QR，且 coverage 最準確
2. 差異在統計上多數不顯著（DM |t| < 3.0），但 coverage 品質差異明顯
3. GARCH 的 Student-t 分配假設導致尾部 coverage 偏離，CAViaR 的非參數性質避免了此問題
4. VIX 對 1% 極端分位數有顯著增量預測力（DM t=3.595）

## 局限
- CAViaR 使用固定 IS 參數，未做遞迴估計（可能高估 OOS 表現）
- GARCH 也用固定參數遞迴更新條件變異數
- OOS 期間（2021-2026）包含多次 regime 轉換，可能有利於適應性模型

## 參考文獻
- Engle & Manganelli (2004) CAViaR. JBE 22, 367-381
- Xiao & Koenker (2009) Conditional Quantile Estimation for GARCH. JASA 104(488)
- Kupiec (1995) Techniques for Verifying Risk Measurement Models. J. Derivatives
- Christoffersen (1998) Evaluating Interval Forecasts. IER 39, 841-862
