# K910: TCI (Total Connectedness Index) as VT Strategy Overlay

## 問題
K907 發現 TCI 與 VIX 完全正交（r=0.001）。TCI 能否作為 VT 策略的 overlay，改善投資組合表現？

## 動機
- K907: TCI 代表全新風險維度（網絡結構 vs vol 水平）
- 假說：TCI 高（connectedness 強）時分散化失效 → 應降低風險暴露
- VIX sufficiency 不適用——TCI 是正交維度

## 方法
- 基於 K907 方法重新計算 rolling TCI（9 assets, VAR(5), GFEVD H=10, 250d window）
- 4 種 TCI 策略 vs 3 baselines：
  1. TCI Defensive（高 TCI 減倉 SPY）
  2. TCI+VIX Combined（四 regime 配置）
  3. Smooth TCI weight（k/TCI 類似 12/VIX）
  4. TCI Diversification Timing（低 TCI 加國際分散化）
- Baselines: BH SPY, BH 50/50, 12/VIX
- OOS: 2009-12 ~ 2026-04（~16 年）
- signal.shift(1) 防 lookahead，np.random.seed(42)

## 結果（NULL）
| 策略 | Sharpe | MDD | CRRA(5) |
|------|--------|-----|---------|
| BH 50/50 | 0.973 | -20.3% | 0.082 |
| TCI+VIX Combined | 0.992 | -17.9% | 0.083 |
| TCI Defensive | 0.836 | -22.8% | 0.067 |
| 12/VIX | 0.889 | -14.4% | 0.061 |

- **0/4 TCI 策略通過 Harvey DM test vs 任何 baseline**
- TCI+VIX 略優但 DM t=-0.28（完全 NS）
- TCI vs 次日 return: r=0.005 (p=0.77)——零方向預測力
- TCI vs 21 天 vol: r=0.067 (p<0.001)——弱 vol 預測

## 結論
**TCI 是結構性描述指標，不是交易信號。** 與 K697 一致：VIX 預測 vol magnitude (0.57) 但不預測 direction (0.04)，TCI 也是如此。TCI 的價值在於理解市場結構（誰傳播、誰接收），不在於 timing 策略。

## 數據來源
yfinance（9 assets + VIX），2009-2026
