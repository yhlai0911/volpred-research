# K987: VIX² Nonlinearity in Volatility Forecasting

## 動機
K979 (SKEW) 的副發現：VIX² 非線性項的 OOS R² = 0.198 vs VIX 線性 0.139。這暗示 VIX 與波動率的關係是凸性的（VIX 從 20→30 的波動率增量 > 10→20 的增量）。本實驗系統性測試 VIX 的各種非線性函數形式對日頻波動率預測的增量。

## 方法
- **數據**：SPY + ^VIX（yfinance），2006-2026
- **IS**：2006-2018（3,270 obs），**OOS**：2019-2026（1,824 obs）
- **Target**：r²_t（日平方報酬作為波動率代理）
- **所有特徵均 shift(1)**：使用 VIX_{t-1} 預測 r²_t
- **Seed**：np.random.seed(42)

### 模型
| 模型 | 說明 |
|------|------|
| M1 Linear | r² = α + β₁×VIX + ε |
| M2 Quadratic | r² = α + β₁×VIX + β₂×VIX² + ε |
| M3 Log | r² = α + β₁×log(VIX) + ε |
| M4 Piecewise | r² = α + β₁×VIX + β₂×max(VIX-20,0) + ε |
| M5 Spline | 自然三次樣條（3 個 knots） |
| M6 MF2-VIX | tau = (VIX/√252)² |
| M7 MF2-VIX² | tau + 凸性項 tau×VIX |
| GJR-GARCH | GJR-GARCH(1,1)，遞迴 OOS，每 63 日重新估計 |

### 評估指標
- QLIKE, MSE, OOS R²
- DM test（MSE-based，因部分模型產生負預測使 QLIKE 失效）
- MZ regression（Mincer-Zarnowitz）
- RESET test（Ramsey 函數形式檢定）

## 核心發現

### 1. VIX-Vol 凸性強烈確認
- **凸性比率 5.5x**：VIX 高於中位數（17.1）時，VIX-r² 斜率是低於中位數時的 5.54 倍
- VIX² 與 r² 的相關性（0.558）> VIX 線性（0.489）> log(VIX)（0.392）
- 十分位分析顯示最高 VIX 分位的 r² 是最低分位的 33 倍

### 2. M2 Quadratic 是最佳模型（OOS R²）
| 模型 | OOS R² | MSE | QLIKE |
|------|--------|-----|-------|
| **M2 Quadratic** | **0.2581** | **2.80e-7** | 1.49 |
| M6 MF2-VIX | 0.2538 | 2.81e-7 | 15629* |
| M4 Piecewise | 0.2428 | 2.85e-7 | 1.95 |
| M7 MF2-VIX² | 0.2409 | 2.86e-7 | 1.49 |
| M5 Spline | 0.2093 | 2.98e-7 | 1.46 |
| M1 Linear | 0.2022 | 3.01e-7 | 45701* |
| M3 Log | 0.1277 | 3.29e-7 | 30851* |
| GJR-GARCH | -0.3390 | 5.05e-7 | 3.23 |

*QLIKE 不可靠（模型產生負預測被 clip）

### 3. DM Test 結果（MSE-based）
- M2 vs GJR：t=-4.38, p<0.001（M2 顯著勝出）
- M2 vs M5 Spline：t=-1.85, p=0.064（M2 邊際顯著）
- M2 vs M7 MF2-VIX²：t=-1.64, p=0.102（差異不顯著）
- M2 vs M4 Piecewise：t=-0.66, p=0.511（差異不顯著）
- **結論**：M2 在 MSE 意義下是最佳模型，但與 M4、M7 的差異不具統計顯著性

### 4. 所有模型均 FAIL RESET Test
所有模型（包括二次、樣條）的 RESET test 均顯著拒絕（p<0.01），表示：
- VIX 單一變數無法完全捕捉 VIX-vol 的非線性關係
- 可能需要其他變數（VVIX、SKEW、VIX term structure）來補充

### 5. 負預測問題
M1（Linear）、M3（Log）、M6（MF2-VIX）在低 VIX 時產生負的方差預測：
- M1：293 個 OOS 觀測值被 clip（16%）
- M3：218 個（12%）
- M6：136 個（7%）
- **啟示**：選擇確保非負性的函數形式（M2、M4、M5、M7）是必要的

### 6. VIX >> GJR-GARCH
所有 VIX-based 模型（包括最簡單的線性）都大幅超越 GJR-GARCH（OOS R² = -0.339）。VIX 作為隱含波動率，包含了市場對未來波動的預期，遠優於純歷史報酬模型。

## 結論
1. **VIX² 非線性確實存在且有統計意義**，但增量相對溫和（R² 從 0.20 提升到 0.26）
2. **M2 Quadratic 是最佳選擇**：簡單、可解釋、OOS R² 最高
3. **建議整合到 MF2 框架**：M7（MF2-VIX²）的表現接近 M2，可作為 tau 的改良版本
4. 所有模型仍有殘差非線性 → 需要額外變數補充

## 局限
- Target 為 r²（daily squared return），非 5-min RV
- OOS 期間包含 COVID-19（高 VIX 異常期）
- 未測試高頻 VIX（intraday VIX）

## 檔案
- `k987_vix_nonlinear.py` — 實驗腳本
- `k987_vix_nonlinear_results.json` — 完整結果
- `k987_nonlinear_fit.png` — VIX 非線性擬合圖
- `k987_oos_comparison.png` — OOS 模型比較圖

## 參考
- K979: SKEW experiment（VIX² side finding）
- K970: MF2 framework
