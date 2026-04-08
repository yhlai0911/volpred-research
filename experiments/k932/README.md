# K932: Utility-Based Portfolio Allocation — Min-CVaR + Max CRRA Utility

## 問題
加入 Min-CVaR 和 Max CRRA Utility 後，動態配置能否打敗靜態 50/50？

## 方法
5 種配置（SPY/GLD/TLT，Rolling 252-day sample covariance，OOS 2016-2026）：
1. Static 50/50 SPY/GLD
2. Min-Variance
3. Min-CVaR 5%（Normal 近似：CVaR = -μ + σ_p × φ(Φ⁻¹(α))/α）
4. Max CRRA Utility ($\gamma=5$)（均值-方差近似：U ≈ μ_p - (γ/2)σ²_p）
5. Risk Parity（inverse volatility weighting）

交易成本：10 bps 單邊，基於每日 turnover 扣除。
信號 lag：權重基於 t-1 的 rolling covariance，套用到 t 的 return。

## 結果（NULL — 50/50 Irreducible #14）

| 方法 | Gross Sharpe | Net Sharpe | MDD | Avg Turnover |
|------|------------|-----------|------|-------------|
| **Static 50/50** | **1.262** | **1.251** | -20.3% | 0.0054 |
| Min-CVaR 5% | 1.056 | 1.031 | -23.3% | 0.0093 |
| Min-Variance | 1.048 | 1.022 | -23.2% | 0.0098 |
| Risk Parity | 1.046 | 1.029 | -22.5% | 0.0064 |
| Max CRRA $\gamma=5$ | 0.729 | 0.580 | -30.4% | 0.0827 |

### 平均配置權重
| 方法 | SPY | GLD | TLT |
|------|-----|-----|-----|
| Static 50/50 | 50.0% | 50.0% | 0.0% |
| Min-Variance | 36.2% | 28.1% | 35.7% |
| Min-CVaR 5% | 36.9% | 28.6% | 34.5% |
| Max CRRA γ=5 | 50.0% | 35.4% | 14.6% |
| Risk Parity | 30.9% | 34.9% | 34.2% |

## 關鍵發現
1. **Min-CVaR ≈ Min-Variance**：Normal 近似下 CVaR 最小化收斂到 variance 最小化（Sharpe 差異僅 0.008）
2. **Max CRRA 表現最差**：高 turnover（0.0827 vs 其他 <0.01）導致 Sharpe 從 0.729 降到 0.580（-20.4%）
3. **動態方法過度配置 TLT**：Min-Var/Min-CVaR/Risk Parity 平均 ~35% TLT，但 TLT 年化報酬僅 2.5%（vs SPY 14.2%、GLD 11.2%）
4. **50/50 的優勢來源**：(1) 不配置低報酬的 TLT (2) 零交易成本 (3) SPY-GLD 低相關（0.033）提供分散化

## 結論
50/50 SPY/GLD 第 14 次確認不可超越。與 DeMiguel, Garlappi & Uppal (2009) 一致：1/N 在實務中打敗「最優」配置。動態方法的估計誤差 + 交易成本 > 理論上的配置改善。

## 數據來源
yfinance (SPY, GLD, TLT)，期間 2014-01-01 至 2026-01-01，OOS 自 2016-01-01 起。

## 參考文獻
- DeMiguel, Garlappi & Uppal (2009) "Optimal Versus Naive Diversification" RFS 22(5):1915-1953
- Rockafellar & Uryasev (2000) "Optimization of CVaR" J Risk 2:21-42
- Markowitz (1952) "Portfolio Selection" J Finance 7(1):77-91

## 檔案
- `k932.py` — 實驗腳本（重建於 2026-04-06）
- `k932_results.json` — 完整結果
- `k932_equity_curves.png` — 權益曲線（gross + net）
- `k932_weights.png` — 動態權重配置時序圖
