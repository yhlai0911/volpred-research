# K1079: Matched-IV Hypothesis — VXN vs VIX for QQQ A4f

**Proposer**: User (matched-IV hypothesis)
**Executor**: Claude
**Date**: 2026-04-12
**Status**: Complete

## 問題描述

K1078 已確認 QQQ 以 **VIX²** 作為 A4f 外生變數時 DM t=+5.99 Harvey PASS。
但 QQQ 追蹤 Nasdaq-100，**VIX** 是 S&P 500 的 IV，而 CBOE 有專屬 Nasdaq IV：**VXN**。

> **Matched-IV Hypothesis**：若 VXN 比 VIX 更能捕捉 QQQ 的 conditional variance，
> 以 VXN² 作為 A4f exogenous driver 應在 QQQ 產生更強或更穩定的改善。

## 動機

1. **理論動機**：Nasdaq 含科技密集成分，tech-specific risk（監管、大盤集中度、AI 主題）
   不一定被 SPY 對應的 VIX 捕捉。
2. **實務動機**：若 VXN 顯著勝，Paper 9 應以 "asset-matched IV" 為 robustness 主軸。
3. **反向假設**：QQQ 與 SPY 相關度很高，VIX/VXN 相關度若接近 1，邊際效益可能趨近於 0。

## 方法

### 四種 A4f 規格（QQQ-only）

| Spec | τ formula | 參數 |
|------|-----------|------|
| **A4f-VIX**    | `θ₀ + θ₁·VIX²_{t-1}` | 6 (K1078 baseline) |
| **A4f-VXN**    | `θ₀ + θ₁·VXN²_{t-1}` | 6 (matched IV) |
| **A4f-COMBO**  | `θ₀ + θ₁·VIX² + θ₂·VXN²` | 7 (joint; θ₁/θ₂ 可正可負) |
| **A4f-SPREAD** | `θ₀ + θ₁·(VXN² - VIX²)` | 6 (tech risk premium) |

下層 g_t 一律採 GJR(1,1)，Engle-Ghysels-Sohn (2013) 乘法形式：
`u_{t-1} = r_{t-1}/sqrt(τ_t)`, `σ²_t = τ_t·g_t`。

### Rolling Window
- W=2000（訓練）, refit every 63 交易日
- 三段互不重疊 OOS（與 K1078 嚴格對齊）：
  - Early_Crisis    2007-01-01 ~ 2012-12-31（GFC + Euro）
  - Middle_Recovery 2013-01-01 ~ 2018-12-31
  - Late_COVID      2019-01-01 ~ 2026-04-11
- 全 OOS n=4848，總 refit 次數=78

### 評估
- QLIKE on r² (Patton 2011)
- HAC Newey-West DM test，Harvey |t|>3 門檻
- Moving-block bootstrap 95% CI
- Spearman rank correlation
- θ₁ stability（CV、orders-of-magnitude span）
- 4 個 crisis sub-periods + 5 個 VIX buckets

### 數據
- yfinance: QQQ (Adj Close), ^VIX, ^VXN
- 樣本：2001-01-23 ~ 2026-04-10, n=6341（VXN IPO 於 2001-01-23）
- Random seed: 42

## 預期

基於 Matched-IV Hypothesis，預期：
- **樂觀情境**：VXN² 在 QQQ 上 DM vs VIX² > 3.0 Harvey PASS → Paper 9 加 VXN robustness
- **中性情境**：VXN² ≈ VIX²（邊際改善 < Harvey）→ 強化 VIX 作為 "good enough" baseline
- **悲觀情境**：VXN² 輸 VIX²（tech noise 多於 signal）→ 意外發現

## 結果

### VIX/VXN 關係診斷
- **corr(VIX, VXN) = 0.7854**（中度相關，非極高）
- VXN > VIX 94.9% 的天數；平均 spread +5.45，std 7.63
- VIX max 82.69 於 2020-03-16（COVID），VXN max 82.49 於 2001-09-20（911 後）

### Full OOS QLIKE（n=4848）

| Model | QLIKE | Diff% vs GJR |
|-------|-------|--------------|
| GJR | -7.91176 | — |
| A4f-VIX | -7.96268 | **-0.644%** |
| A4f-VXN | **-7.96886** | **-0.722%** |
| A4f-COMBO | -7.96708 | -0.699% |
| A4f-SPREAD | -7.50667 | +5.120% (worse) |

**排名：VXN > COMBO > VIX >> SPREAD > GJR**

### 關鍵 Pairwise DM Tests（HAC, n=4848）

| Comparison | DM t | p | Harvey |
|------------|------|---|--------|
| A4f-VIX vs GJR | **+5.944** | 0.0000 | **PASS** |
| A4f-VXN vs GJR | **+6.923** | 0.0000 | **PASS** |
| A4f-COMBO vs GJR | +6.407 | 0.0000 | PASS |
| A4f-SPREAD vs GJR | -2.993 | 0.0028 | — (significantly worse) |
| **A4f-VXN vs A4f-VIX** | **+1.277** | **0.2016** | **FAIL** |
| A4f-COMBO vs A4f-VIX | +1.467 | 0.1425 | FAIL |
| A4f-COMBO vs A4f-VXN | -0.444 | 0.6574 | FAIL |

### 假設檢驗

| H | 敘述 | 結果 | 關鍵數字 |
|---|------|------|---------|
| **H1** | VXN vs VIX Harvey \|t\|>3 | **FAIL** | DM t=+1.277 |
| **H2** | CV(VXN) < CV(VIX) | **PASS** | CV_VIX=6.214, CV_VXN=3.641 |
| **H3** | COMBO > single spec | **FAIL** | COMBO vs VIX DM=+1.467; vs VXN DM=-0.444 |
| **H4** | 3 windows 一致性 | **PARTIAL** | 2/3 windows VXN 方向性勝 |

### Per-Window VXN vs VIX

| Window | n | QL_VIX | QL_VXN | Diff% | DM(VXN-VIX) |
|--------|---|--------|--------|-------|-------------|
| Early_Crisis    | 1510 | -7.70361 | -7.71198 | -0.109% | +0.760 |
| Middle_Recovery | 1510 | -8.45598 | -8.46775 | -0.139% | +1.478 |
| Late_COVID      | 1828 | -7.76919 | -7.76895 | **+0.003%** | **-0.046** |

VXN 方向性勝 Early_Crisis 和 Middle_Recovery，但 Late_COVID 持平（幾乎 tie）。

### Crisis Sub-Periods

| Crisis | n | VIX mean | VXN mean | QL_VIX | QL_VXN | DM(VXN-VIX) |
|--------|---|----------|----------|--------|--------|-------------|
| GFC | 505 | 32.09 | 33.64 | -7.09886 | -7.09078 | -0.289 |
| Euro_Crisis | 274 | 24.29 | 25.00 | -7.66856 | -7.66739 | -0.142 |
| COVID_Crash | 104 | 36.69 | 37.14 | -6.51633 | -6.51409 | -0.064 |
| **Bear_2022** | 251 | 25.62 | **31.62** | -6.73537 | **-6.75926** | **+3.399** |

**關鍵發現**：在 2022 科技熊市，VXN 比 VIX 平均高 6 點（tech-specific fear），
且 VXN² 作為 A4f driver **DM t=+3.399 Harvey 通過**。其他 crisis 期間（GFC、COVID），
VIX 和 VXN 的平均值差距較小，兩者近乎等價。

### VIX Bucket 分析

| Bucket | Range | n | DM(VXN-VIX) |
|--------|-------|---|-------------|
| Low | [0,15) | 1545 | +1.200 |
| **Normal** | **[15,25)** | **2421** | **+2.838** |
| High | [25,40) | 703 | -0.563 |
| Extreme | [40,60) | 141 | -0.785 |
| Crisis | [60,200) | 38 | +0.397 |

**Normal VIX regime**（[15,25)，佔 50% 樣本）DM t=+2.838 幾乎達 Harvey 門檻。
意味 VXN 在「日常交易」期間帶來最大邊際改善。

### θ₁ 穩定性

| Spec | Median | Range | CV | Orders span |
|------|--------|-------|-----|-------------|
| VIX | 2.43e-07 | [1.12e-07, 1.37e-03] | **6.214** | 4.09 |
| VXN | 1.69e-07 | [1.25e-07, 5.21e-04] | **3.641** | 3.62 |

**VXN 的 θ₁ 變異係數約為 VIX 的 60%**。VXN 規格產生更穩定的 loading，
即使 full-OOS DM 未達 Harvey。COMBO 規格：θ₁(VIX) 2.9% 次數為負、θ₂(VXN) 1.5% 次數為負，
collinearity 對 COMBO 帶來不穩定的符號變化。

## 結論

### 主要結論

1. **H1 FAIL — Matched-IV 假設邊際支持度不足**：在 QQQ 全 OOS 上，
   以 VXN² 取代 VIX² 並未達到 Harvey |t|>3 門檻（DM t=+1.277, p=0.202）。
   方向性上 VXN 略勝（QLIKE 低 0.08%），但統計證據不足以宣稱 "matched IV 一定勝"。

2. **H2 PASS — VXN 產生更穩定的 loading**：θ₁(VXN) 的 CV=3.64，
   顯著小於 θ₁(VIX) 的 CV=6.21。若 Paper 9 重視 out-of-sample 穩定性，
   VXN 是更穩健的 driver。

3. **VXN 在 tech-specific regime 才顯現明顯勝出**：
   - 2022 科技熊市（VXN vs VIX 多 +6 點）DM t=+3.399 Harvey PASS
   - Normal VIX bucket（佔 50% 樣本）DM t=+2.838 接近 Harvey
   - Extreme/High VIX buckets 中 VXN 反而略輸 VIX（但 n 小、非顯著）

4. **COMBO 沒有顯著幫助**：兩個 IV 高度相關（0.79），
   joint spec collinearity 問題（θ₁ 偶爾負）→ 資訊冗餘，無法同時保留雙方增量。

5. **SPREAD 規格失敗**：以 `(VXN² - VIX²)` 作為唯一 exog 表現顯著比 GJR 差（+5.12% QLIKE），
   原因是 θ₀ 作為 "baseline level" 必須承擔所有波動預測。

### Paper 9 意涵

- **建議採用 VIX² 為 main spec**（K1078 已驗證 DM t=+5.99，VIX 樣本長度 + 理論匹配 SPY 合作良好）
- **VXN 可作為 robustness check 附註**：
  - 方向性一致（VXN 不顯著輸）
  - 在 tech-specific regime（如 2022）明顯更勝
  - 在 Normal VIX regime 有邊際改善
  - θ₁ 穩定性更佳
- **重要限制**：本實驗不證明「VIX 絕對勝」，也不證明「VXN 絕對勝」—
  兩者幾乎等效，符合 corr=0.79 的直接預期。"Good enough" 概念適用。

### 理論啟發

1. **IV family 內部替代性高**：K1073 在 SPY 上測試 VIX vs VIX9D/VIX3M/VVIX 也是 VIX 勝。
   IV-family 中 "細微匹配" 不如 "強 signal + 長樣本" 重要。
2. **Regime-specific matching**：VXN 在 tech-specific stress（2022）確實顯著勝。
   這符合 Whaley (2009) 的 "sector-specific fear" 理論。
3. **Tech premium ≠ tech volatility signal**：SPREAD 規格失敗表明，
   "tech minus broad" 的 premium 本身並不是強波動 predictor — 它是情緒 / 定價 anomaly，
   不是 direct variance proxy。

## 局限

1. **樣本起點 2001-01-23**：VXN 可用歷史不及 VIX（1990-）。
   Dot-com 衰退初期資料不可得，無法測試 "dot-com recovery" regime。
2. **QQQ 是 ETF，非直接 Nasdaq-100 index**：tracking error 理論上干擾 VXN 匹配。
3. **權益與 IV 估計的 time-zone mismatch**：VIX/VXN 收盤 16:15 ET，QQQ 16:00 ET，
   15-minute 差異在 crisis days 可能放大。
4. **未分金融 vs 非金融熊市**：2022 結果可能特別是因為 Nasdaq 跌幅大（-33%），
   而非 VXN 真的捕捉了 unique information。
5. **Bootstrap CI 窄**：block bootstrap 的 CI 對 VXN vs VIX 橫跨 0，
   確認無統計顯著性（不只 DM t）。

## 檔案

- `k1079.py` — 完整實驗腳本
- `k1079_results.json` — 4 models × 4848 OOS × 78 refits 完整結果
- `k1079_dm_matrix.png` — 5 模型兩兩 DM t-stat 矩陣 + QLIKE bar
- `k1079_vix_vs_vxn.png` — VIX/VXN 時序 + 散點
- `k1079_theta1_compare.png` — θ₁(VIX) vs θ₁(VXN) 隨時間演化
- `k1079_regime_analysis.png` — Crisis + Per-window VXN vs VIX

## 參考文獻

1. Engle, R. F., Ghysels, E., & Sohn, B. (2013). Stock market volatility and
   macroeconomic fundamentals. *Review of Economics and Statistics*, 95(3), 776-797.
2. Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility
   proxies. *Journal of Econometrics*, 160(1), 246-256.
3. Harvey, C. R., Liu, Y., & Zhu, H. (2016). ... and the cross-section of expected
   returns. *Review of Financial Studies*, 29(1), 5-68.
4. Whaley, R. E. (2009). Understanding the VIX. *Journal of Portfolio Management*,
   35(3), 98-105.

## 上游實驗

- K988 SPY A4f baseline
- K1073 VIX vs VIX9D/VIX3M/VVIX on SPY (VIX wins)
- K1075 SPY extended 2007-2026 DM t=+7.92
- K1077 0050.TW extended 2010-2025 DM t=-0.49 NS
- K1078 QQQ + VIX² extended DM t=+5.99（直接上游）

## 衍生方向

1. **K1080 candidate**: Regime-dependent switching — 只在 VXN-VIX spread > 3 時切換到 VXN²，
   否則用 VIX²。測試 adaptive matching 是否能捕捉 Bear_2022 regime gain。
2. **K1081 candidate**: 其他 sector ETF 的 matched IV
   （XLF + VIX, XLE + OVX, TLT + MOVE）— 廣泛驗證 matched-IV hypothesis。
3. **K1082 candidate**: Forward-looking exogenous — 實驗以 VXN 減 VIX term structure
   （VXN3M - VIX3M）作為 tech risk premium 信號，而非 level spread。
