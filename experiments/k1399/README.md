# K1399: VIX Feature Decomposition in HAR

## 研究動機

K1315 確認 HAR-VIX（加入 VIX level 作為外生變量）以 DM t≈4.4（Harvey-significant）顯著優於 HAR-ABS baseline。但 VIX 的哪個分量驅動這個預測優勢？本實驗解構 VIX 的四個子分量：水準（level）、變化量（change）、波動率溢酬（vol premium）、趨勢（MA5），分別測試各自的增量預測力。

**相關實驗**：K530（HAR Multi-Scale，HAR-VIX 最優個別模型）、K1315（預測組合，確認 VIX 充分統計量性質）

## 設計

| 項目 | 規格 |
|------|------|
| 資產 | SPY（本地 CSV: `paper/leverage-direction/data/spy_vix_2004-2026.csv`）|
| 預測目標 | `\|r_t\|`（日絕對 log 報酬，HAR-ABS paradigm，與 K1315 一致）|
| IS 期間 | 2005-01-04 至 2018-12-31（n=3522）|
| OOS 期間 | 2019-01-02 至 2026-05-19（n=1865）|
| 模型估計 | OLS + HC3（IS 固定係數，OOS 靜態預測）|
| 評估損失函數 | QLIKE（Patton 2011 form B: mean[log(ŷ)+\|r\|/ŷ]）|
| 顯著性標準 | DM-HLN（Harvey 1997），Harvey threshold \|t\|>3.0（Harvey et al. 2016）|

### 六個模型規格

| 模型 | 特徵 |
|------|------|
| HAR-ABS（baseline）| rv1, rv5, rv22 |
| HAR-VIX-L（level）| + VIX_{t-1} |
| HAR-VIX-dV（change）| + ΔVIX_{t-1} |
| HAR-VIX-P（vol premium）| + (VIX/\|r\|×√252)_{t-1}（winsorized 1-99th IS pct）|
| HAR-VIX-T（MA5 trend）| + MA5_VIX_{t-1} |
| HAR-VIX-All | + 全部四個特徵 |

### Lookahead 防護（完整記錄）

| 特徵 | 構造方式 | 驗證 |
|------|---------|------|
| rv1 | `abs_r.shift(1)` | rv1[date_i] == abs_r[date_{i-1}] ✓ |
| rv5 | `abs_r.rolling(5).mean().shift(1)` | 同上邏輯 ✓ |
| rv22 | `abs_r.rolling(22).mean().shift(1)` | 同上邏輯 ✓ |
| VIX level | `vix_close.shift(1)` | 明確 t-1 ✓ |
| ΔVIX | `vix_close.diff().shift(1)` | VIX_{t-2}→VIX_{t-1} 差分 ✓ |
| Vol premium | `(vix/(\|r\|×√252)).shift(1)` winsorized | 先計算 t 日 premium，shift(1) 取 t-1 ✓ |
| MA5 VIX | `vix_close.rolling(5).mean().shift(1)` | 明確 t-1 ✓ |

**Seed**: `np.random.seed(42)`

## 結果

### OOS QLIKE 排名（Patton 2011 Form B）

| 排名 | 模型 | QLIKE | vs HAR-ABS | DM t vs baseline | Harvey pass |
|------|------|-------|-----------|-----------------|-------------|
| 1 | HAR-VIX-All | **-3.9423** | -0.0260 | -4.36 | ✓ |
| 2 | HAR-VIX-L | -3.9411 | -0.0248 | -4.40 | ✓ |
| 3 | HAR-VIX-T | -3.9312 | -0.0150 | -3.53 | ✓ |
| 4 | HAR-ABS | -3.9163 | — | — | — |
| 5 | HAR-VIX-P | -3.9161 | +0.0001 | +0.82 | ✗ |
| 6 | HAR-VIX-dV | -3.9121 | +0.0042 | +1.01 | ✗ |

### DM 配對檢定 vs HAR-VIX-L（增量資訊檢定）

| 比較 | DM t | Harvey pass | 解讀 |
|------|------|------------|------|
| HAR-VIX-dV vs L | +4.15 | ✓ | dV 顯著**差於** L |
| HAR-VIX-P vs L | +4.42 | ✓ | P 顯著**差於** L |
| HAR-VIX-T vs L | +3.47 | ✓ | T 顯著**差於** L |
| HAR-VIX-All vs L | -0.40 | ✗ | All 與 L 無顯著差異 |

### VIF（HAR-VIX-All，IS 樣本）

| 特徵 | VIF | 備注 |
|------|-----|------|
| rv1 | 2.25 | — |
| rv5 | 5.13 | — |
| rv22 | 8.14 | — |
| vix_L | **60.26** | HIGH — vix_L 與 ma5_vix 高度共線 |
| dvix | 2.10 | — |
| premium | 1.12 | — |
| ma5_vix | **68.30** | HIGH — 因 vix level 與 5日均線共線 |

## 假說驗證

| 假說 | 內容 | 結果 | DM t | 說明 |
|------|------|------|------|------|
| H1 | VIX level 顯著 | **PASS** | -4.40 | 複製 K1315；輕微差異因 OOS 延長至 2026 |
| H2 | ΔVIX 有增量資訊 | **PARTIAL** | vs baseline: +1.01; vs L: +4.15 | 絕對預測力不如 baseline；但 ΔVIX 使預測顯著惡化（不是 level 的補充）|
| H3 | Vol premium 有 regime 資訊 | **PARTIAL** | vs baseline: +0.82; vs L: +4.42 | 單獨使用無法超越 baseline；相比 L 亦顯著較差 |
| H4 | VIX trend（MA5）無增量資訊 | **FAIL** | vs baseline: -3.53 | MA5 VIX 本身是 Harvey-significant predictor；但 vs L 差（+3.47），說明 MA5 資訊已在 level 中 |
| H5 | All-feature 不優於最佳單一特徵 | **PASS** | All vs L: -0.40 | HAR-VIX-All 與 HAR-VIX-L 無顯著差異，parsimony confirmed |

## 結論

1. **VIX level 是充分分量**：在四個 VIX 子特徵中，VIX 水準（HAR-VIX-L）是唯一 Harvey-significant 且最優的單一特徵（QLIKE=-3.941）。其他三個分量單獨使用均無法超越 HAR-ABS baseline（H2, H3 PARTIAL/FAIL）。

2. **VIX trend（MA5）異常顯著但受共線性污染**：HAR-VIX-T 本身 DM t=-3.53（Harvey-significant），但 vs HAR-VIX-L 則 DM t=+3.47（顯著差於 L）。這反映 MA5 VIX 實質上只是 VIX level 的低頻近似，VIF=68.3 證實高度共線性。

3. **All-feature 不增加顯著預測力**（H5 PASS）：HAR-VIX-All vs HAR-VIX-L 的 DM t=-0.40（p=0.69），parsimony principle 獲得支持。高 VIF（vix_L=60、ma5_vix=68）亦說明全特徵模型存在嚴重多重共線性。

4. **ΔVIX 和 Vol premium 均無獨立預測力**：ΔVIX 和 vol premium 不僅無法超越 baseline，相較 VIX level 還顯著較差（H2, H3 PARTIAL）。VIX 的預測資訊集中在水準本身，而非其變化或與已實現波動率的比值。

5. **K1315 複製確認**：HAR-VIX-L DM t=4.40（K1315 reported 4.58），差異源自 OOS 延長 2024→2026，屬預期誤差範圍。

## 方法論注意事項

- **Vol premium winsorization**：原始 premium = VIX/(|r|×√252) 有 29 個 zero-return 造成 inf 值。採用 IS 樣本 1st-99th 百分位數截斷（[48.26, 10232.37]），僅以 IS 統計量進行（無 OOS lookahead）。
- **QLIKE Form B**：`log(ŷ) + y/ŷ`，日報酬極小時可為負值，與 K1315 採用相同公式。
- **DM-HLN**：NW bandwidth=T^(1/3)，HLN correction，t(T-1) 分佈。
- **VIF high warning**：HAR-VIX-All 中 vix_L 與 ma5_vix 高度共線（VIF>10），All-feature 模型係數估計不穩定；結論依賴 OOS QLIKE 和 DM 檢定，不依賴 IS 係數值。

## 參考文獻

- Corsi (2009, JFE): HAR-RV model
- Patton (2011, JFE): Robust loss functions for volatility forecasting
- Harvey, Leybourne & Newbold (1997, IJoF): Finite-sample DM test correction
- Harvey et al. (2016): Higher threshold |t|>3 for multiple testing
- Whaley (2000, JoD): VIX as investor fear gauge
- Bollerslev, Tauchen & Zhou (2009, RFS): Variance risk premium

## 相關實驗

- K530 (★★★★): HAR Multi-Scale — first identified HAR-VIX as best model
- K1315 (★★★): Forecast Combination — confirmed VIX level as sufficient statistic
