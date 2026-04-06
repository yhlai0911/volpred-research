# K946: VIX Regime-Conditional Rebalancing

## 動機
K942 顯示 VIX 在 normal range (15-25) 幾乎無資訊價值（+0.5%），但極端 regime 有顯著價值（Low <15: +8.7%, High >=25: +17.3%）。如果一個策略只在 VIX 進入極端區域時才調整配置（否則維持 50/50），能否在降低 turnover 的同時保持或改善 risk-adjusted return？

## 假說
- 多數 VT 策略失敗因在 normal regime 過度交易（K687）
- 只在極端 regime 動作可避免 whipsaw
- K688 顯示 VT 在 CRRA gamma>=5 勝出 → regime-conditional 可放大此優勢

## 方法
5 種策略比較（SPY+GLD，2006-2026，yfinance）：
1. **BH 50/50**: 靜態配置
2. **12/VIX (Daily)**: w_SPY = min(12/VIX_{t-1}, 1)
3. **Regime-Only VT**: Calm(<15)=80%, Normal(15-25)=50%, Stress(>=25)=30%
4. **Smooth Regime VT**: <12=80%, 12-30=50%, >=30=20%
5. **Monthly Regime VT**: 同 #3 但月頻檢查

Lag: VIX_{t-1} via `shift(1)`，交易成本 10bps 單邊。

## 主要結果

| Strategy | Sharpe(G) | Sharpe(N) | CAGR | MDD | Turnover | Changes |
|----------|-----------|-----------|------|-----|----------|---------|
| BH 50/50 | 0.857 | 0.857 | 11.75% | -32.49% | 0.000 | 0 |
| 12/VIX (Daily) | 0.862 | 0.724 | 11.11% | -32.03% | 8.028 | 4591 |
| Regime-Only VT | 0.895 | 0.792 | 11.61% | -28.76% | 5.992 | 471 |
| Smooth Regime VT | 0.776 | 0.714 | 10.29% | -26.61% | 3.696 | 249 |
| Monthly Regime VT | **0.896** | **0.878** | 11.77% | -30.81% | 1.059 | 80 |

### CRRA Utility（年化）

| Strategy | gamma=3 | gamma=5 | gamma=7 |
|----------|---------|---------|---------|
| BH 50/50 | 0.0922 | 0.0732 | 0.0541 |
| 12/VIX | 0.0886 | 0.0718 | 0.0549 |
| Regime-Only VT | 0.0929 | 0.0759 | 0.0588 |
| Monthly Regime VT | **0.0939** | **0.0765** | **0.0590** |

### Regime 統計
- Calm (<15): 34.5% of time, SPY vol 8.9%
- Normal (15-25): 48.2% of time, SPY vol 15.5%
- Stress (>=25): 17.3% of time, SPY vol 36.5%

## 結論

1. **Monthly Regime VT 是本實驗最佳策略**：Sharpe(net) 0.878 vs BH 0.857，差異極小（~0.02），但 turnover 僅 1.059（vs 12/VIX 的 8.028）
2. **BH 50/50 在 net Sharpe 上仍然非常強**：確認 K687/K846 結論——50/50 幾乎不可打敗
3. **Regime-Only VT 在 MDD 上最優**：-28.76% vs BH -32.49%，改善 3.7 個百分點
4. **Monthly Regime VT 在所有 CRRA gamma 上勝出**：gamma=3/5/7 皆為最高，對風險厭惡投資人有吸引力
5. **12/VIX 的高 turnover 是致命弱點**：4591 次 weight change，net Sharpe 降至 0.724
6. **核心洞察**：不動 > 頻繁動作。月頻 regime 檢查 + 極端才動 = 最佳 Sharpe/turnover 比

### 局限性
- Sharpe 差異很小（SE ~ 0.23 for 19 years），統計不顯著
- Regime 閾值（15/25）可能 overfit 美股歷史
- 未測試台股（0050.TW）

## 檔案
- `k946.py` — 實驗腳本
- `k946_results.json` — 完整數值結果
- `k946_equity_curves.png` — 權益曲線
- `k946_regime_analysis.png` — Regime 分析圖
