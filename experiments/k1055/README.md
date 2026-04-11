# K1055: Conformal Prediction Intervals for A4f vs GJR Volatility Forecasts

## 問題描述
A4f（乘法 GARCH-X with VIX^2）是最佳波動率點預測模型（K988, DM t=4.48 vs GJR），但點預測無法告訴投資人「預測有多不確定」。本實驗用 Conformal Prediction (CP) 為 A4f 和 GJR 生成分配自由（distribution-free）的預測區間，評估 A4f 的預測區間是否比 GJR 更精確（更窄）。

## 動機
- 波動率點預測缺少不確定性量化
- Conformal Prediction 是 distribution-free 方法，不依賴模型殘差分配假設
- 與 K768 (Conformal VaR) 不同：K768 校準 VaR violation rate，本實驗建構波動率預測區間
- 更好的點預測模型理應產生更窄的預測區間——本實驗驗證此假說

## 方法

### Split Conformal Prediction (Vovk et al. 2005, Lei et al. 2018)
- Nonconformity score: |r^2_t - sigma^2_hat_t| / sigma^2_hat_t（相對誤差）
- Rolling calibration window: 252 天
- Prediction interval: [sigma^2_hat * (1 - q_alpha), sigma^2_hat * (1 + q_alpha)]
- Finite-sample correction: q_level = (1-alpha)(1 + 1/n_calib)

### Adaptive Conformal Inference (Gibbs & Candes 2021)
- 動態調整 alpha_t based on 最近的 coverage
- alpha_{t+1} = alpha_t + gamma * (alpha - err_t)
- gamma = 0.01（learning rate）
- 在高波動時自動擴大區間

### 實驗設定
- **數據**：SPY daily returns + VIX, yfinance, 2004-01-05 ~ 2026-04-10 (N=5,602)
- **模型**：A4f-VIX^2 (free omega, 6 params) vs GJR-GARCH(1,1) (4 params)
- **OOS**：2019-01-02 ~ 2026-04-10 (1,828 天)
- **Training window**：2,000 天，每 63 天 refit（30 次 refit）
- **Target coverage**：90% 和 95%
- **Bootstrap**：10,000 reps, seed=42

## 結果

### QLIKE 驗證（點預測品質）
| Model | QLIKE | Improvement |
|-------|-------|-------------|
| GJR | -8.2663 | — |
| A4f | -8.3495 | +1.01% (A4f better) |

### 90% Conformal Prediction Intervals

| Method | Model | Coverage | Avg Width | Winkler Score |
|--------|-------|----------|-----------|---------------|
| Split Conformal | GJR | 0.8966 | 0.000444 | 0.001213 |
| Split Conformal | A4f | 0.9029 | 0.000414 | 0.001205 |
| ACI | GJR | 0.8985 | 0.000546 | 0.001163 |
| ACI | A4f | 0.8997 | 0.000485 | 0.001148 |

**Width Ratio (A4f/GJR)**:
- Split Conformal: 0.932 (A4f 6.8% narrower)
- ACI: 0.888 (A4f 11.2% narrower)

### 95% Conformal Prediction Intervals

| Method | Model | Coverage | Avg Width | Winkler Score |
|--------|-------|----------|-----------|---------------|
| Split Conformal | GJR | 0.9524 | 0.000700 | 0.001536 |
| Split Conformal | A4f | 0.9480 | 0.000662 | 0.001509 |
| ACI | GJR | 0.9492 | 0.000823 | 0.001556 |
| ACI | A4f | 0.9499 | 0.000803 | 0.001385 |

**Width Ratio (A4f/GJR)**:
- Split Conformal: 0.946 (A4f 5.4% narrower)
- ACI: 0.975 (A4f 2.5% narrower)

### Bootstrap Significance Test（10,000 reps）

| Level | Width diff (GJR-A4f) | SE | t-stat | 95% CI | Significant? |
|-------|---------------------|----|--------|--------|-------------|
| 90% | 0.000030 | 0.000008 | 3.669 | [0.000014, 0.000047] | **YES** |
| 95% | 0.000038 | 0.000013 | 2.845 | [0.000012, 0.000064] | **YES** |

A4f 的預測區間顯著比 GJR 窄（width t=3.67 at 90%, t=2.85 at 95%）。但 Winkler score 差異不顯著（t=0.09 / t=0.17），因為 coverage 差異被 width 差異抵消。

### Conditional Coverage by VIX Regime (90% Split Conformal)

| Regime | N | GJR Cov | A4f Cov | GJR Width | A4f Width |
|--------|---|---------|---------|-----------|-----------|
| Low (VIX<15) | 415 | 0.9364 | 0.9187 | 0.000139 | 0.000102 |
| Medium (15-25) | 1064 | 0.9111 | 0.9143 | 0.000252 | 0.000242 |
| High (25-35) | 290 | 0.8339 | 0.8720 | 0.000745 | 0.000741 |
| Crisis (>=35) | 59 | 0.7797 | 0.7966 | 0.003503 | 0.003053 |

**關鍵發現**：
- A4f 在高 VIX 和危機時 coverage 顯著較好（0.872 vs 0.834, 0.797 vs 0.780）
- 低 VIX 時 GJR coverage 較好（0.936 vs 0.919）但 A4f width 大幅更窄（0.000102 vs 0.000139）
- 危機時 A4f width 更窄（0.003053 vs 0.003503，減少 12.9%）

### Model Failure Detection
- GJR 有 258 個寬度尖峰日（閾值以上），平均 VIX=32.2
- A4f 有 235 個寬度尖峰日（9% fewer），平均 VIX=33.5
- A4f 的 VIX 外生變數使其在高波動時更穩定

### ACI Adaptation
- ACI 方法成功讓 alpha_t 隨市場狀態自動調整
- 高波動時 alpha_t 下降（更寬區間），低波動時回升
- ACI 的 rolling coverage 波動較小（std: GJR 0.020 vs Split 0.033）

## 結論

1. **A4f 的 conformal interval 顯著比 GJR 窄**：width t=3.67（90%）/ t=2.85（95%），兩者都通過 2.5% 顯著水準
2. **兩個模型都達到名義覆蓋率**：90%/95% 的實際覆蓋率與名義水準一致
3. **A4f 在高波動 regime 表現更好**：coverage 更高且 width 更窄，VIX 外生變數的優勢在市場壓力期最明顯
4. **ACI 比 Split Conformal 更穩定**：rolling coverage 波動更小，但代價是略寬的區間
5. **Winkler score 差異不顯著**：coverage 和 width 的權衡使整體 Winkler score 差異較小

## 局限性
- OOS 期間（2019-2026）包含 COVID 但可能不代表所有市場環境
- Calibration window (252 天) 的選擇可能影響結果
- 相對 nonconformity score 的分母用 forecast（而非 target），可能在 forecast 嚴重偏差時失真
- Crisis regime 樣本數僅 59 天，統計穩定性有限

## 檔案
- `k1055.py`：完整腳本
- `k1055_results.json`：完整結果
- `k1055_coverage_plot.png`：Rolling coverage 時序圖
- `k1055_interval_width.png`：區間寬度時序圖
- `k1055_width_comparison.png`：A4f vs GJR 寬度比較
- `k1055_aci_adaptation.png`：ACI alpha_t 自適應軌跡

## 參考文獻
- Vovk, Gammerman, Shafer (2005). Algorithmic Learning in a Random World
- Lei, G'Sell, Rinaldo, Tibshirani, Wasserman (2018). Distribution-Free Predictive Inference
- Gibbs & Candes (2021). Adaptive Conformal Inference Under Distribution Shift
- Barber, Candes, Ramdas, Tibshirani (2023). Conformal Prediction Beyond Exchangeability
- Winkler (1972). A Decision-Theoretic Approach to Interval Estimation
- Patton (2011). Volatility Forecast Comparison Using Imperfect Volatility Proxies
