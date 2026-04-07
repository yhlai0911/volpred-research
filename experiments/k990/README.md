# K990: SPY→0050.TW Monthly Lead-Lag Strategy

## 動機
- K983 發現 SPY→0050.TW daily lead-lag r=0.40, OOS R²=15.9%（顯著）
- K984 發現日頻策略因台股交易成本（~0.585% round trip, 122 trades）導致 alpha 被成本吃掉（Sharpe -0.14）
- **核心問題**：改成月頻 rebalancing（每月僅 1 筆交易），成本大幅降低後 lead-lag alpha 能否存活？

## 方法
- **數據**：yfinance（SPY, 0050.TW, ^VIX），2009-2026（0050.TW 資料起點）
- **IS/OOS**：2009-2016 / 2017-2026
- **信號設計**（全部使用前月資料，shift(1) 防止 lookahead）：
  1. Monthly Binary：SPY 前月 return > 0 → w=1.0，否則 w=0.0
  2. Monthly Proportional：w = clip(0.5 + 2 × SPY_prev_month_return, 0, 1.5)
  3. Monthly Momentum：SPY 前 3 個月 return > 0 → w=1.0，否則 w=0.5
  4. VT + SPY Signal：w = (8.63/VIX_prev_month) × spy_adj（spy_adj = 1.2/0.8）
- **Benchmarks**：Buy & Hold TW50、VT Only (8.63/VIX)
- **交易成本**：0.585% round trip，依 weight change 比例扣除

## 結果

### Monthly Lead-Lag Correlation
- SPY(t-1) → TW50(t) monthly correlation = **0.031**（t=0.44, p=0.66）
- **日頻 r=0.40 vs 月頻 r=0.03**：lead-lag 效應在月頻完全消失

### Full Sample Performance

| Strategy | Sharpe | Ann Return | Ann Vol | MDD | Turnover |
|----------|--------|-----------|---------|-----|----------|
| Buy & Hold | 0.944 | 17.23% | 18.25% | -29.19% | 0.06 |
| 3-Month Momentum | 0.996 | 15.63% | 15.69% | -16.53% | 1.08 |
| VT Only (8.63/VIX) | 0.890 | 7.35% | 8.26% | -11.57% | 0.99 |
| Proportional | 0.876 | 8.56% | 9.77% | -15.76% | 1.14 |
| VT + SPY Signal | 0.831 | 7.73% | 9.30% | -13.07% | 1.93 |
| Monthly Binary | 0.637 | 9.56% | 15.00% | -32.80% | 5.01 |

### OOS (2017-2026)

| Strategy | Sharpe | Ann Return | MDD |
|----------|--------|-----------|-----|
| 3-Month Momentum | 1.215 | 20.05% | -16.51% |
| VT + SPY Signal | 1.093 | 11.43% | -12.63% |
| VT Only | 1.087 | 9.98% | -11.57% |
| Proportional | 1.060 | 10.77% | -15.76% |
| Buy & Hold | 1.049 | 20.39% | -29.19% |
| Binary | 1.013 | 16.19% | -23.27% |

### Statistical Tests
- **VT+SPY vs VT-only**：excess = 0.38 bps/month, t=0.91, p=0.37（不顯著）
- **Momentum vs Buy&Hold（OOS）**：t=-0.21, p=0.83（不顯著差異）
- **月頻 TC 總額**：~10.8%（vs 日頻 ~71.4%），成本降低 85%

## 結論

**MARGINAL / NULL**：月頻 SPY lead-lag 策略未能顯著改善台股配置。

### 核心發現
1. **Lead-lag 是日頻現象，非月頻**：日頻 r=0.40 → 月頻 r=0.03。SPY 對台股的預測力在 1-5 日內就消散
2. **成本問題解決但 alpha 也消失**：月頻成本僅 10.8%（vs 日頻 71.4%），但月頻信號本身沒有預測力
3. **3-Month Momentum 表面最佳**：OOS Sharpe 1.215，但 vs Buy&Hold 不顯著（p=0.83）。這本質上是美股動量效應（SPY 3 個月上漲期間台股也漲），非 lead-lag
4. **VT+SPY overlay 無附加值**：vs VT-only Sharpe 差 -0.06，t=0.91，SPY 信號在 VT 框架下無法提供額外資訊
5. **VT 的真正價值在降低波動**：VT Only MDD -11.57% vs Buy&Hold -29.19%，Sharpe 相當（0.89 vs 0.94），風險管理價值確認

### 對 K983/K984 系列的總結
- K983：日頻 lead-lag 統計上顯著（r=0.40, R²=15.9%）
- K984：日頻策略被交易成本殺死（NULL）
- K990：月頻策略成本可控但 alpha 不存在（NULL）
- **結論：SPY→TW50 lead-lag 是真實但短暫的現象，無法轉化為可交易的策略**

## 檔案
- `k990_monthly_leadlag.py` — 實驗腳本
- `k990_monthly_leadlag_results.json` — 完整結果
- `k990_cumulative_returns.png` — 累積收益圖
- `k990_annual_returns.png` — 年度收益比較圖
