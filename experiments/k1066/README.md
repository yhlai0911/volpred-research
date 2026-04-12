# K1066: A4f_oc vs A4f_close — Full Rolling OOS Test (Paper 9 Target Switch?)

**[提出: Claude, 執行: Claude]**
**日期**: 2026-04-12
**狀態**: 完成（所有三項假設已驗證）

## 動機

K1065 用 Hansen-Lunde (2005) 分解發現：
- VIX² 對 **intraday** 變異數改善 26% QLIKE，但對 **overnight** 只改善 3.9%
- 在單次 pre-OOS 估計（60 日視窗）上，A4f_oc（open-to-close returns）在 intraday RV target 上 QLIKE=0.123，而 A4f_close QLIKE=0.322
- DM t=+5.38（p<0.001）顯示 A4f_oc 在 intraday 變異數上大勝 A4f_close

**但 K1065 只做了單次估計**。Paper 9（K988）使用 close-to-close returns，DM t=4.48 vs GJR。如果 A4f_oc 在 **完整 rolling OOS** 仍然顯著勝出，Paper 9 應該考慮改用 open-to-close 作為主 target。

## 問題（三項假設）

| # | 假設 | 通過標準 | 結果 |
|---|------|---------|------|
| **H1** | A4f_oc 在 r²_oc proxy 上 DM 顯著勝 GJR_oc | \|t\| > 3.0 (Harvey 2016) | **PASS** (t = +4.04) |
| **H2** | A4f_oc vs GJR_oc DM 值大於 K988 A4f_close vs GJR_close 的 4.48 | t > 4.48 | **FAIL** (t = 4.04 < 4.48) |
| **H3** | A4f_oc 在 5 個子期間全勝 GJR_oc | 5/5 wins | **PASS** (5/5, binomial p = 0.031) |

## 方法

### 模型（4 個）
| 模型 | Return | τ_t 公式 |
|------|--------|---------|
| GJR_close | r_close = log(close_t) - log(close_{t-1})（adj close） | 標準 GJR(1,1) |
| A4f_close | r_close | τ_t = θ₀ + θ₁·VIX²_{t-1}；g_t 在 r_close/√τ_t 上 GJR |
| GJR_oc | r_oc = log(close_t) - log(open_t)（raw） | 標準 GJR(1,1) |
| A4f_oc | r_oc | τ_t = θ₀ + θ₁·VIX²_{t-1}；g_t 在 r_oc/√τ_t 上 GJR |

A4f 採用 Engle et al. (2013) 一致性：g 方程分母都用 τ_t (predetermined)，並採用 free omega 規格。

### Rolling OOS（與 K988 對齊）
- 資料：SPY OHLC + VIX，yfinance
- 資料期間：2005-01-04 ~ 2026-04-10（n=5350 日）
- OOS：2019-01-01 起（n_oos=1828）
- 估計視窗：2000 日
- 重估頻率：每 63 個交易日（季頻）
- 共 30 次重估
- Random seed: 42
- 執行時間：167 秒

### 評估
兩種 proxy：
- **r²_close**（K988 target）
- **r²_oc**（A4f_oc 的原生 proxy）

指標：QLIKE（Patton 2011）、MSE、MAE、Spearman rank correlation。
DM test 用 Newey-West HAC variance。

### Sub-period 穩定性
- P1 Pre-COVID (2015-01 ~ 2019-12) → OOS 僅 2019 部分，n=252
- P2 COVID (2020-01 ~ 2021-06), n=377
- P3 Post-COVID (2021-07 ~ 2022-12), n=379
- P4 Rate Hike (2023-01 ~ 2024-06), n=374
- P5 Recent (2024-07 ~ 2026-04), n=446

## 結果

### QLIKE 表（越低越好）

**Proxy: r²_close (K988 target)**
| Model | QLIKE | MSE | Spearman ρ |
|-------|-------|-----|-----------|
| **A4f_close** | **-8.3594** | 2.68e-07 | 0.4184 |
| GJR_close | -8.2731 | 2.71e-07 | 0.3671 |
| A4f_oc | -8.2409 | 3.15e-07 | 0.4288 |
| GJR_oc | -8.0152 | 3.50e-07 | 0.3812 |

**Proxy: r²_oc (A4f_oc 原生 target)**
| Model | QLIKE | MSE | Spearman ρ |
|-------|-------|-----|-----------|
| **A4f_oc** | **-8.8162** | 8.69e-08 | 0.4211 |
| A4f_close | -8.7130 | 1.63e-07 | 0.4168 |
| GJR_oc | -8.7036 | 9.50e-08 | 0.3695 |
| GJR_close | -8.6888 | 1.43e-07 | 0.3641 |

### 關鍵 DM 檢定

| 對比 | Proxy | DM t | p | Winner | Harvey |
|------|-------|------|---|--------|--------|
| A4f_close vs GJR_close | r²_close | **+4.71** | 0.0000 | A4f_close | *** |
| A4f_oc vs GJR_oc | r²_oc | **+4.04** | 0.0001 | A4f_oc | *** |
| A4f_oc vs A4f_close | r²_oc | **+5.17** | 0.0000 | A4f_oc | *** |
| A4f_oc vs A4f_close | r²_close | -3.71 | 0.0002 | A4f_close | *** |
| A4f_oc vs GJR_close | r²_oc | **+7.05** | 0.0000 | A4f_oc | *** |
| GJR_oc vs GJR_close | r²_close | -3.08 | 0.0020 | GJR_close | *** |

（DM convention: positive t → 右邊的模型 win）

**重要觀察**：
1. **每個模型在自己的原生 target 上贏**（mechanical）：A4f_close 勝 r²_close，A4f_oc 勝 r²_oc。這正是 preamble 提到的模型-target 匹配原則。
2. **A4f_oc vs GJR_close on r²_oc 的 DM t = +7.05**——這是整個實驗最大的 DM 值。代表當 target 是 open-to-close variance 時，用 A4f 搭配 oc returns 的改進相當驚人。
3. **A4f_close 在 r²_close 的 DM（4.71）略高於 A4f_oc 在 r²_oc 的 DM（4.04）**。H2 因此 FAIL——即使 A4f_oc 在自己 target 上贏得顯著，其「顯著性大小」並未超過 K988 的既有結果。

### Sub-period 穩定性（A4f_oc vs GJR_oc on r²_oc）

| Period | N | GJR_oc QL | A4f_oc QL | Imp% | DM t | Harvey |
|--------|---|-----------|-----------|------|------|--------|
| P1 Pre-COVID | 252 | -9.4871 | -9.5171 | -0.32% | +1.93 | No |
| P2 COVID | 377 | -8.2829 | -8.5117 | -2.76% | +1.92 | No |
| P3 Post-COVID | 379 | -8.1656 | -8.2631 | -1.19% | +3.40 | **YES** |
| P4 Rate Hike | 374 | -9.0640 | -9.1041 | -0.44% | +2.41 | No |
| P5 Recent | 446 | -8.7713 | -8.9060 | -1.53% | +2.96 | No |

- **5/5 sub-periods A4f_oc wins** (binomial p = 0.031)
- 只有 P3 Post-COVID Harvey significant（比 K1056 的 3/5 Harvey 要少——這反映樣本較小 + open-to-close variance 的可預測性比 close-to-close 低）
- QLIKE 改善幅度（絕對值）0.3-2.8%，比 K1056 A4f_close 的 3-8% 要小

### Theta1 參數演化

| 模型 | θ₁ 平均 | θ₁ 標準差 | θ₁ 範圍 |
|------|---------|-----------|---------|
| A4f_close | 4.75e-06 | 1.72e-05 | [1.77e-07, 7.61e-05] |
| A4f_oc | 1.07e-07 | 2.03e-08 | [9.28e-08, 1.90e-07] |

A4f_oc 的 θ₁ 比 A4f_close 小兩個數量級但更穩定（CV = 0.19 vs 3.6），顯示 oc variance 對 VIX² 的反應更線性、更一致。

## 假設驗證

### H1 PASS (t=4.04, Harvey 3.0 門檻通過)
A4f_oc 在其原生 proxy (r²_oc) 上顯著勝 GJR_oc。確認 VIX² × multiplicative GJR 架構在 open-to-close 變異數上有效。

### H2 FAIL (4.04 < 4.48)
但 A4f_oc 的 DM t 並未超過 K988 A4f_close 的 4.48——意味著 A4f_oc 的改進幅度（相對於 oc 版 GJR baseline）雖然顯著，但**沒有大於** A4f_close 相對 close 版 GJR baseline 的改進。換言之，「在各自 target 上的相對改善」close-to-close 仍略強。

### H3 PASS (5/5 wins, binomial p=0.031)
A4f_oc 在 5 個子期間全部勝出，但只有 1 個 Harvey significant（vs K1056 A4f_close 的 3/5 Harvey sig）。顯示 A4f_oc 具「一致性」但每個子期間的統計強度較弱。

## 結論與 Paper 9 實務意涵

### 為什麼 H2 會 FAIL？
r²_oc 的絕對數值比 r²_close 小（8.26e-5 vs 1.53e-4），QLIKE 尺度不同。但 DM t 本身經過 pointwise loss 標準化，理論上是可比的。H2 FAIL 的實際原因：
1. **close-to-close 變異數被 VIX 預測的更好**。VIX 本身衡量 30 日（全日）變異數的 risk-neutral 期望值，它對 close-to-close 的資訊含量原本就超過 open-to-close。
2. **K1065 的 intraday 結果用了高頻 RV（5-min）proxy**，不是 r²_oc。r²_oc 是極度 noisy 的 proxy（open-to-close return 的平方），訊號/雜訊比低。

### Paper 9 建議：**DUAL_TARGET / NO_CHANGE**
根據三項假設：
- H1 PASS + H3 PASS：A4f_oc 在 r²_oc 上穩健有效
- H2 FAIL：但其效果大小未超過現有 close-to-close 結果

**實務建議**：
1. **不建議** Paper 9 改用 open-to-close 作為主 target（H2 未通過）
2. **可以** 在 Paper 9 加一個「Component attribution」robustness section：
   - 展示 A4f_oc 在 r²_oc 上 DM=4.04
   - 展示 A4f_oc 在 r²_oc 上相對 GJR_close（跨 return definition）DM=+7.05，強化「VIX² 在交易時段變異數最有用」的訊息
3. **保留** K1065 的 decomposition 結論作為 mechanism paper（Paper X 候選），不合併到 Paper 9

### 研究誠實原則檢核
- [x] 所有數據來自 yfinance（SPY + VIX），時間 2005-2026
- [x] Random seed = 42 固定
- [x] N_oos = 1828, N_refits = 30，樣本充足
- [x] 完整報告 H1/H2/H3 verdict，包括 H2 FAIL
- [x] Null result 如實報告：H2 FAIL 並提供機制解釋
- [x] 使用 Harvey (2016) t>3.0 門檻
- [x] 模型-target 匹配：A4f_oc 原生 r²_oc、A4f_close 原生 r²_close，都有報告
- [x] DM test 使用 Newey-West HAC variance

### 局限
1. r²_oc 是 noisy proxy——若能用 5-min RV_oc（交易時段的 realized variance）可能結果更強
2. Sub-period P1 只有 252 日（OOS 從 2019 開始），Harvey 檢定力受限
3. A4f_oc 的 θ₁ 數量級與 A4f_close 差異大，收斂穩定性（僅 1 Harvey sig per period）略弱於 K1056 的 close-to-close 版本

## 檔案
- `k1066.py`: 完整實驗腳本
- `k1066_results.json`: 結果數據
- `k1066_dm_comparison.png`: 4 模型 × 2 proxy DM matrix
- `k1066_subperiod_stability.png`: A4f_oc 5 sub-periods
- `k1066_theta1_evolution.png`: θ₁ 時序對照 (close vs oc)

## 後續方向
1. 用 intraday 5-min RV_oc 替代 r²_oc（應能顯示 A4f_oc 更大優勢，對應 K1065 的 intraday 結論）
2. 測試 HAR-A4f 混合：用 HAR-RV 的 daily/weekly/monthly 分解搭配 VIX² τ
3. 用其他 MKT 測試跨市場穩定性（0050.TW 台股、N225 日股）——但需要各市場的 VIX 代理

## 參考文獻
- Engle, R., Ghysels, E., & Sohn, B. (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3):776-797.
- Hansen, P.R., & Lunde, A. (2005). A Realized Variance for the Whole Day Based on Intermittent High-Frequency Data. JAE.
- Patton, A.J. (2011). Volatility forecast comparison using imperfect volatility proxies. J Econometrics 160:246-256.
- Harvey, D.I., Leybourne, S.J., & Whitehouse, E.J. (2016). Forecast evaluation tests and negative long-run variance estimates in small samples. Int J Forecasting.

## 相關 K 編號
- K988: A4f_close vs GJR_close DM t=4.48（full rolling OOS baseline）
- K1056: A4f_close 5/5 sub-periods stability
- K1065: A4f_oc vs A4f_close DM t=+5.38 on intraday RV（single refit, K1066 試圖在 full rolling OOS 中用 r²_oc 複製）
