# K1040: VRP Return Predictability via A4f g_t

**[提出: 賴奕豪, 執行: Claude]**

## 動機

K1023 發現 A4f 模型分解出的 g_t 與 Variance Risk Premium (VRP) 高度相關 (Spearman rho ~ 0.80)。Bollerslev, Tauchen & Zhou (2009, RFS) 的經典論文證明 VRP 能顯著預測股票報酬 (月頻 R^2 約 5-8%)。K998 已證明 g_t 無法預測未來 VRP，但能否預測未來報酬是不同的問題。

## 研究問題

1. A4f 模型的 g_t 能否預測 SPY 的未來 1/5/22 天報酬？
2. g_t 是否比 raw VRP 或 VIX 水準更有效？
3. 預測力在哪個 horizon 最強？
4. g_t 信號是否有經濟價值（long-short 策略）？

## 方法

**預測迴歸** (OOS expanding window):
```
r_{t→t+h} = a + b1×g_t + b2×VRP_t + b3×VIX_t + ε_{t+h}
```

**模型對比**:
1. Historical mean (benchmark)
2. VRP-only
3. g_t-only
4. VIX-only
5. g_t + VRP
6. Kitchen sink (g_t + VRP + VIX)

**技術規格**:
- 資產: SPY | 數據: 2005-01-01 ~ 2026-04-09 (n=5349)
- OOS: 2019-01-01 起 (n=1805)
- A4f: window=2000, refit_every=63, Student-t(df=8)
- VRP = VIX^2/100^2 × (22/252) - RV_22d
- h>1: 重疊 returns + Newey-West HAC
- 評估: OOS R^2, DM test, Clark-West test, Direction Accuracy, Long-short Sharpe
- Seed: 42

## 結果

### OOS R^2 (越正越好，負=不如歷史均值)

| Model | h=1d | h=5d | h=22d |
|-------|------|------|-------|
| VRP-only | -2.63% | -0.52% | +0.77% |
| g_t-only | -0.61% | -0.85% | +0.87% |
| VIX-only | -1.19% | -0.81% | **+5.63%** |
| g_t+VRP | -3.24% | -1.57% | +0.88% |
| Kitchen sink | -4.08% | -1.74% | +5.27% |

### Clark-West Test (vs hist mean, one-sided p-value)

| Model | h=1d | h=5d | h=22d |
|-------|------|------|-------|
| VRP-only | -0.48 (p=0.68) | +0.95 (p=0.17) | +0.94 (p=0.17) |
| g_t-only | -1.75 (p=0.96) | -1.06 (p=0.86) | +0.91 (p=0.18) |
| VIX-only | -1.59 (p=0.94) | -0.03 (p=0.51) | **+2.02 (p=0.02)** |
| g_t+VRP | -0.63 (p=0.74) | +0.71 (p=0.24) | +0.92 (p=0.18) |
| Kitchen sink | -0.52 (p=0.70) | +0.78 (p=0.22) | +1.59 (p=0.06) |

### In-Sample Kitchen-Sink (h=22d, n=3501, HAC t-stats)

| Variable | Coefficient | t-stat |
|----------|------------|--------|
| const | +0.015 | +0.95 |
| g_t | -0.010 | -1.04 |
| VRP | +2.503 | **+2.77** |
| VIX | +0.026 | +0.53 |

### Long-Short (g_t signal)

| Horizon | LS Sharpe | BH Sharpe |
|---------|-----------|-----------|
| h=1d | -0.118 | 0.711 |
| h=5d | -0.001 | 0.769 |
| h=22d | -0.074 | 0.759 |

## 結論

**NUANCED NULL for g_t**:

1. **g_t 不具有報酬預測力**: g_t-only 在所有 horizon 的 OOS R^2 均接近零或為負，CW test 均不顯著。

2. **VIX 水準在月頻有預測力**: VIX-only 在 h=22d 達到 OOS R^2=+5.63%，CW=+2.02 (p=0.021)。這與 VIX 作為 risk premium proxy 的文獻一致。

3. **VRP 在 IS 顯著但 OOS 失敗**: VRP 在 in-sample 的 t-stat=2.77 (h=22d)，但 OOS R^2 只有 0.77%。這是 return predictability 文獻中常見的 IS/OOS 落差。

4. **g_t 無經濟價值**: Long-short 策略基於 g_t 信號在所有 horizon 都產生負 Sharpe (最差 -0.118)，而 buy-and-hold SPY 的 Sharpe 約 0.71-0.77。

5. **g_t 的角色在波動率域，不在報酬域**: K1023 證明 g_t 高度反映 VRP (rho~0.80)，K988/K995/K1035 證明 g_t 改善波動率預測，但它不能跨域預測報酬。VRP-return predictability 的通道不經過 GARCH dynamics。

## 局限性

- 僅測試 SPY（單一資產）
- OOS 期間 2019-2026 包含 COVID（異常期）
- VRP 構造使用簡單的 22-day RV，非 5-min RV
- 未測試 VIX term structure slope 等替代變數

## 參考文獻

- Bollerslev, T., Tauchen, G., & Zhou, H. (2009). Expected Stock Returns and VRP. RFS 22(11).
- Campbell, J.Y., & Thompson, S.B. (2008). Predicting Excess Stock Returns OOS. RFS 21(4).
- Clark, T.E., & West, K.D. (2007). Approximately Normal Tests for Nested Models. JoE 138(1).
- K1023: g_t vs VRP Spearman rho ~ 0.80
- K998: g_t cannot predict future VRP
- K818: SSVS return prediction NULL (OOS R^2=-1.47%)

## 檔案

- `k1040.py` — 實驗腳本
- `k1040_results.json` — 完整結果
- `k1040_oos_r2_direction.png` — OOS R^2 和方向準確度圖表
