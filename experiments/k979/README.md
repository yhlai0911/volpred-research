# K979: CBOE SKEW Index as Volatility Predictor

## 動機
CBOE SKEW Index 衡量 S&P 500 選擇權的 OTM put 偏度（尾部風險定價），與 VIX 衡量的 ATM 波動率水準是不同維度。本實驗探討 SKEW 是否提供超越 VIX 的波動率預測增量。

## 方法
- **數據**：SPY, ^VIX, ^SKEW from yfinance (2010-02 to 2026-04, N=4004)
- **Target**：Realized Volatility (squared daily returns, annualized)
- **IS**: 2010-2018 (N=2222), **OOS**: 2019-2026 (N=1759)
- **模型**：OLS 回歸，所有預測變數 shift(1) 防止 lookahead
- **評估**：OOS R², QLIKE (Patton 2011), DM test, Harvey (2016) |t|>3.0

## 回歸模型
| Model | Predictors | IS R² | OOS R² | SKEW t-stat |
|-------|-----------|-------|--------|-------------|
| M1 | VIX | 0.1717 | 0.1387 | — |
| M2 | VIX + SKEW | 0.1730 | 0.1387 | 1.876 |
| M3 | VIX (5d) | 0.2811 | 0.1838 | — |
| M4 | VIX + SKEW (5d) | 0.2815 | 0.1844 | 1.108 |
| M5 | VIX (22d) | 0.2719 | 0.1053 | — |
| M6 | VIX + SKEW (22d) | 0.2721 | 0.1060 | 0.687 |
| M7 | VIX + SKEW + Interact | 0.1731 | 0.1408 | — |
| M8 | VIX + VIX² + SKEW | 0.1777 | 0.1978 | 1.015 |

## 關鍵發現

### 1. VIX 與 SKEW 相關性低 (-0.197)
確認兩者衡量不同維度：VIX = ATM vol level, SKEW = tail risk pricing。

### 2. SKEW 無顯著增量預測力
- 1 天 horizon：SKEW t-stat = 1.876（低於 Harvey 3.0 門檻），Delta OOS R² = -0.000009
- 5 天 horizon：t-stat = 1.108, Delta OOS R² = +0.0006
- 22 天 horizon：t-stat = 0.687, Delta OOS R² = +0.0007
- DM test：stat = -0.004, p = 0.997（完全不顯著）

### 3. 但 SKEW 有條件資訊價值
- Low SKEW (P10, <118) 時 mean forward RV = 0.059（高）
- High SKEW (P90, >148) 時 mean forward RV = 0.014（低）
- SKEW Quintile Q1→Q5 的 forward RV 單調遞減：0.050 → 0.032 → 0.027 → 0.023 → 0.016
- 這反映 **低 SKEW = 高 VIX 時期**（負相關 -0.197），而非 SKEW 獨立預測力

### 4. VIX² 比 SKEW 更有用
M8 (VIX + VIX² + SKEW) OOS R² = 0.198 vs M2 (VIX + SKEW) = 0.139，改善來自 VIX² 的非線性效果，不是 SKEW。

## 結論
**SKEW 不提供超越 VIX 的波動率預測增量。** 雖然 VIX-SKEW 相關性低（衡量不同維度），但 SKEW 的條件波動率模式主要反映其與 VIX 的負相關，而非獨立訊息。VIX 的非線性效果（VIX²）比 SKEW 更能改善預測。

## 局限性
- RV proxy 使用日收益平方（非 5-min RV），noise 較大
- OLS 標準誤未使用 Newey-West HAC（可能低估 SE）
- 未測試 SKEW 在極端事件（如 COVID crash）的即時預測力
- SKEW 可能對 tail risk measures (VaR/ES) 有增量，此實驗僅測 mean vol

## 檔案
- `k979_skew_vol.py` — 實驗腳本
- `k979_skew_vol_results.json` — 完整結果
- `k979_skew_vix_scatter.png` — VIX vs SKEW 散佈圖 + 時序圖
- `k979_conditional_vol.png` — SKEW 條件下的波動率行為
