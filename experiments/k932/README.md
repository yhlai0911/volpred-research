# K932: Utility-Based Portfolio Allocation — Min-CVaR + Max CRRA Utility

## 問題
加入 Min-CVaR 和 Max CRRA Utility 後，動態配置能否打敗靜態 50/50？

## 方法
5 種配置（SPY/GLD/TLT，DCC covariance，OOS 2016-2026）：
1. Static 50/50 SPY/GLD
2. Min-Variance
3. Min-CVaR 5%
4. Max CRRA Utility ($\gamma=5$)
5. Risk Parity

## 結果（NULL — 50/50 Irreducible #14）

| 方法 | Gross Sharpe | Net Sharpe | MDD |
|------|------------|-----------|------|
| **Static 50/50** | **1.216** | **1.216** | -20.3% |
| Risk Parity | 1.090 | 1.007 | -22.0% |
| Min-CVaR 5% | 1.085 | 0.842 | -21.9% |
| Max CRRA $\gamma=5$ | 1.081 | 0.900 | -21.6% |
| Min-Variance | 1.078 | 0.899 | -21.6% |

## 關鍵發現
1. **Min-CVaR ≈ Min-Variance**：Normal 模擬下 CVaR 最小化收斂到 variance 最小化
2. **Max CRRA ≈ Min-Variance**：return 不可預測 → utility maximization 退化為 risk minimization
3. **Turnover 殺死動態方法**：Min-CVaR 1.085→0.842（net Sharpe 降 28%）
4. 動態方法過度配置 TLT（~39%），但 TLT 報酬低（4.2% ann）拖累績效

## 結論
50/50 SPY/GLD 第 14 次確認不可超越。與 DeMiguel, Garlappi & Uppal (2009) 一致：1/N 在實務中打敗「最優」配置。

## 注意
腳本因 worktree 清理遺失，需重新執行。結果基於 agent 回報。

## 數據來源
yfinance (SPY, GLD, TLT, ^VIX)
