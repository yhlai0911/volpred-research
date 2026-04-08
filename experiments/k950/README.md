# K950: Monthly Regime VT Cross-Asset Validation

## 問題
K946 的 Monthly Regime VT (SPY+GLD) 在 Sharpe 上微勝 BH。此實驗驗證該策略在 5 個不同 equity+gold 配對中的跨市場穩健性。

## 動機
- K946 只測了 SPY+GLD，需要跨市場驗證避免 data mining
- K949 已確認 VIX 跨市場有效性（4/5 Harvey pass），但那是 VIX 預測力，不是策略績效

## 方法
**策略設計（Monthly Regime VT）**：
- VIX < 15（calm）：80% equity
- VIX ≥ 25（stress）：30% equity  
- 15 ≤ VIX < 25（normal）：50% equity
- 月初 VIX 決定整月權重，`shift(1)` 防前瞻偏誤
- 交易成本：10bps 單邊

**對照組**：BH 50/50（年度再平衡）

**市場配對**：
1. SPY + GLD（美國）
2. QQQ + GLD（美國科技）
3. 0050.TW + GLD（台灣）
4. EWJ + GLD（日本）
5. FEZ + GLD（歐元區）

**數據**：yfinance, 2008-2025

## 結果

| 市場 | BH Sharpe | VT Sharpe(net) | ΔSharpe | BH MDD | VT MDD | 權重變化次數 |
|------|-----------|----------------|---------|--------|--------|-------------|
| SPY+GLD | 0.833 | 0.806 | -0.027 | -32.5% | -30.9% | 69 |
| QQQ+GLD | 0.919 | 0.886 | -0.033 | -33.5% | -30.9% | 69 |
| 0050+GLD | 0.924 | 0.890 | -0.034 | -23.0% | -22.1% | 66 |
| EWJ+GLD | 0.569 | 0.501 | -0.068 | -30.5% | -30.5% | 69 |
| FEZ+GLD | 0.535 | 0.424 | -0.111 | -38.1% | -36.7% | 69 |

**VT wins on Sharpe: 0/5**
**VT improves MDD: 4/5**（EWJ 幾乎持平 -30.5% vs -30.5%）

## 結論

1. **Monthly Regime VT 在 Sharpe 上全面落敗**（0/5），與 K687 一致：VT 不是 alpha generator
2. **MDD 改善一致**（4/5 市場），確認 VT 是 drawdown insurance（K688 結論）
3. **歐元區最差**：FEZ+GLD Sharpe 差距最大（-0.111），因為 VIX 是美國指標，對歐洲市場的 regime 識別力較弱
4. **交易頻率一致**：~69 次/18年（~3.8次/年），策略確實低頻
5. **年化 turnover ~108%** 看似高，但因為每次只有 ±30% 的 weight shift

**核心洞察**：VIX regime switching 的 MDD 保護效果跨市場穩健，但 Sharpe 改善不存在。這支持 K688 的 CRRA utility 框架——VT 的價值在於風險厭惡投資人的 utility 改善，不是報酬改善。

## 局限
- VIX 是美國指標，非美市場可能需要本地 implied vol 指標
- BH 50/50 的 "annual rebalance" 簡化了實際執行
- 2008-2025 包含多次危機（GFC、COVID），結果可能受極端事件驅動

## 檔案
- `k950.py` — 實驗腳本
- `k950_results.json` — 完整結果
- `k950_cross_asset.png` — 跨市場比較圖

## 數據來源
yfinance: SPY, QQQ, 0050.TW, EWJ, FEZ, GLD, ^VIX (2008-2025)
