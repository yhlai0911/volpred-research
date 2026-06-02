# K998: VRP Predictability from MF-GJR-X g Component

## 動機
K988b 發現 A4f 模型的 g 成分與 VRP (Variance Risk Premium) 有高同期相關。本實驗測試 g 能否**預測未來** VRP，而非僅是同期 proxy。

## 方法
- **數據**: SPY 2005-2026, VIX (yfinance), n=5345, OOS n=1824
- **模型**: A4f (vix_squared, free_omega, tau_t), rolling window=2000, refit every 63 days
- **VRP proxy**: VRP_t = (VIX_{t-1}/100)²/252 - r²_t
- **測試**:
  1. Granger causality (h=1,5,10,22)
  2. Predictive regressions with Newey-West HAC (Harvey t>3.0)
  3. OOS R² (Campbell & Thompson 2008, expanding window)
  4. Variance swap strategy simulation (signal.shift(1) applied)

## 核心結果

### Granger Causality
| Horizon | F-stat | p-value | Significant? |
|---------|--------|---------|-------------|
| h=1     | 65.81  | <0.001  | Yes          |
| h=5     | 31.78  | <0.001  | Yes          |
| h=10    | 17.83  | <0.001  | Yes          |
| h=22    | 2.10   | 0.1473  | No           |

### Predictive Regressions (g coefficient, controlling for VRP lag)
| Horizon | t_g (NW) | Harvey sig? | In-sample R² |
|---------|----------|------------|-------------|
| h=1     | -2.15    | No         | 0.0748      |
| h=5     | -1.91    | No         | 0.0266      |
| h=10    | -1.61    | No         | 0.0145      |
| h=22    | -1.40    | No         | 0.0013      |

### OOS R² (vs historical mean)
| Horizon | R²_OOS(g) | R²_OOS(AR1) | R²_OOS(AR1+g) |
|---------|-----------|------------|---------------|
| h=1     | 0.011     | -0.079     | -0.053        |
| h=5     | -0.004    | -0.419     | -0.412        |
| h=10    | -0.012    | -0.457     | -0.434        |
| h=22    | -0.002    | -0.005     | -0.006        |

### Variance Swap Strategy
- g-based signal: Sharpe = **-1.06** (negative — reverse indicator!)
- Baseline (always sell variance): Sharpe = **0.85**
- g signal destroys value vs naive strategy

## 結論

**NULL RESULT**: g 在 Granger causality 測試中統計顯著（in-sample），但：
1. 所有 Newey-West t-statistics < 3.0（未通過 Harvey threshold）
2. OOS R² 幾乎全部為負（overfitting）
3. Variance swap strategy 基於 g signal 產生負 Sharpe

**g 是 VRP 的同期 proxy，但沒有可利用的預測能力。** 這與 VRP 本身高度 noisy 且 daily VRP autocorrelation 僅 0.20 的特性一致。GARCH 動態追蹤的是當期 variance decomposition，而非未來 VRP 走勢。

## 局限性
- VRP proxy 使用日頻 VIX²/252 - r²（非 model-free IV from options）
- OOS 期間含 COVID-19 極端波動（2020-03）可能主導結果
- 僅測試 SPY，未跨資產驗證

## 參考文獻
- Bollerslev, Tauchen & Zhou (2009). Expected Stock Returns and Variance Risk Premia. RFS.
- Campbell & Thompson (2008). Predicting Excess Stock Returns OOS. RFS.
- Harvey et al. (2016). t > 3.0 threshold.
- Carr & Wu (2009). Variance Risk Premiums. RFS.
