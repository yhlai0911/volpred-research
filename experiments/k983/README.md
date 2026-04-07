# K983: Cross-Asset Return and Volatility Prediction

## 問題描述
全球股市因時區差異存在 lead-lag 關係。美股（SPY/QQQ）收盤後，亞股（0050.TW）次日開盤。本實驗系統性測試 SPY、QQQ、GLD、0050.TW 之間的跨資產 return/volatility 預測力。

## 動機
- 已知 VIX → 0050.TW vol 有影響（多次確認），但跨資產 return prediction 尚未系統測試
- 台股投資人若能利用前日美股信號，具有實際策略價值

## 數據
- **來源**: yfinance
- **期間**: 2010-01-01 ~ 2026-04-07（4,087 observations）
- **資產**: SPY, QQQ, GLD, 0050.TW, VIX
- **IS/OOS**: 2010-2018 / 2019-2026

## 方法
1. **Lead-Lag Cross-Correlation**: lag 0-5 的交叉相關（t-test 檢定）
2. **Return Prediction**: OLS 回歸（HC1 robust SE），IS 估計 + OOS R²
3. **Volatility Spillover**: 用 squared returns 作 RV proxy，Granger causality test
4. **Conditional Returns**: SPY 大漲/大跌日 → TW50 次日 return 分布

## 核心發現

### 1. 強烈的 US → TW Lead-Lag（單向）
- **SPY(t) → TW50(t+1): r = 0.4037**（t=28.20, p<0.001）— 極強的 lag-1 相關
- TW50(t) → SPY(t+1): r = 0.0075（t=0.48, p=0.63）— 幾乎為零
- **結論: 美股單向領先台股，反向不成立**

### 2. Return Prediction
- **TW50 ~ SPY (OOS R² = 15.9%)**: SPY lag-1 return 對 TW50 有顯著預測力（β=0.432, t=13.3）
- **TW50 ~ QQQ (OOS R² = 17.4%)**: QQQ 比 SPY 預測力略強
- SPY ~ TW50: 台股對美股無預測力（β=0.028, t=0.90）
- **VIX 在控制 SPY 後無增量預測力**（β≈0, t=-0.03）

### 3. Volatility Spillover
- SPY vol → TW50 vol: **顯著**（Granger F=543, p<0.001）
- SPY RV baseline R² = 1.7% → 加 SPY 後 R² = 13.6%（巨大提升）
- GLD → SPY vol: 不顯著（p>0.10）

### 4. Conditional Returns（策略含義）
| SPY(t) Regime | N | TW50(t+1) Mean | Win Rate |
|---|---|---|---|
| 大跌 >2% | 135 | -1.19% | 17.8% |
| 跌 1-2% | 322 | -0.68% | 23.6% |
| 正常 | 3100 | +0.08% | 50.7% |
| 漲 1-2% | 428 | +0.61% | 72.7% |
| 大漲 >2% | 101 | +1.19% | 82.2% |

**SPY 大跌日後，TW50 只有 17.8% 機率上漲；SPY 大漲日後，82.2% 機率上漲。**

## 局限性
- 用 squared returns 作 RV proxy（無所有資產的 5-min 數據）
- 不同交易日曆用 ffill 對齊
- 僅線性模型
- 未包含交易成本

## 檔案
- `k983_cross_asset.py` — 實驗腳本
- `k983_cross_asset_results.json` — 完整結果
- `k983_cross_correlation.png` — Lead-lag 相關結構熱力圖
- `k983_conditional_returns.png` — 條件 return 分析圖

## 參考文獻
- Hamao, Masulis, Ng (1990) RFS — 跨國股市相關性
- Eun & Shim (1989) JFQA — 股市波動國際傳遞
- Diebold & Yilmaz (2009) EJ — 金融資產 Return/Volatility Spillover
