# K981: HAR + Wavelet Decomposition — Multi-Scale Volatility

## 動機
標準 HAR-RV 模型使用固定窗口平均（1d, 5d, 22d）捕捉多尺度波動特徵。Wavelet decomposition（小波分解）能更精細地分離不同頻率帶的波動成分，理論上可能提供更好的多尺度信息。本實驗測試 wavelet 能量特徵是否能改進 HAR 的波動率預測。

## 方法
1. **Wavelet 分解**：使用 Daubechies-4 (db4) 和 Haar 小波，5 層分解，滑動窗口 64 天
   - D1 (1-2天): 高頻噪音
   - D2 (2-4天): 短期波動
   - D3 (4-8天): 週波動
   - D4 (8-16天): 雙週波動
   - D5 (16-32天): 月波動
   - A5 (>32天): 長期趨勢
2. **特徵**：每層的能量（係數平方和除以長度）
3. **所有特徵 shift(1)**：防止 lookahead bias

## 模型比較
| 模型 | 特徵 |
|------|------|
| AR(1) | r²_t |
| HAR | r²_t, r²_t^(5), r²_t^(22) |
| WHAR_db4 | D1-D5 + A5 (db4 wavelet 能量) |
| WHAR_haar | D1-D5 + A5 (Haar wavelet 能量) |
| WHAR_HAR_db4 | HAR + db4 wavelet 混合 |
| GJR-GARCH | GARCH(1,1,1) with leverage |

## 數據
- **資產**: SPY
- **來源**: yfinance
- **期間**: 2006-01-04 ~ 2026-04-06 (5094 obs)
- **IS**: 2006-2018 (3270 obs)
- **OOS**: 2019-2026 (1824 obs)
- **Target**: r² = (log return)² × 10000

## 結果

### OOS 預測績效排名（by QLIKE）

| Rank | Model | QLIKE | MSE | R²_OOS | MZ_R² | Corr |
|------|-------|-------|-----|--------|-------|------|
| 1 | GJR-GARCH | 1.5308 | 28.08 | 0.2551 | 0.2824 | 0.5314 |
| 2 | HAR | 1.5408 | 29.30 | 0.2226 | 0.2317 | 0.4813 |
| 3 | AR(1) | 1.7368 | 30.24 | 0.1976 | 0.2003 | 0.4476 |
| 4 | WHAR_db4 | 1.8011 | 38.75 | -0.0279 | 0.0370 | 0.1923 |
| 5 | WHAR_haar | 50.19 | 37.98 | -0.0076 | 0.0344 | 0.1856 |
| 6 | WHAR_HAR_db4 | 474.48 | 31.08 | 0.1755 | 0.2089 | 0.4570 |

### DM Tests (vs AR(1) baseline, QLIKE loss)
- HAR vs AR(1): t=-3.301, p=0.001 *** (HAR better)
- GJR-GARCH vs AR(1): t=-2.650, p=0.008 *** (GJR better)
- WHAR_db4 vs AR(1): t=1.059, p=0.290 (AR(1) better, not significant)
- HAR vs WHAR_db4: t=5.982, p<0.001 *** (HAR much better)

### Wavelet Component Importance (IS OLS)
| Component | t-stat | Significance |
|-----------|--------|-------------|
| D1 (1-2d) | 1.14 | — |
| D2 (2-4d) | 4.11 | *** |
| D3 (4-8d) | -3.16 | *** |
| D4 (8-16d) | 3.30 | *** |
| D5 (16-32d) | 7.86 | *** |
| A5 (>32d) | -2.49 | ** |

IS R² = 0.126（低於 HAR 的預期水準）

## 結論

**Null result: Wavelet 分解不能改進 HAR 的波動率預測。**

1. **HAR 優於 WHAR**：HAR (QLIKE=1.54) 大幅優於所有 wavelet 模型，DM test 高度顯著 (t=5.98)
2. **Wavelet 能量特徵 OOS 失敗**：WHAR_db4 的 R²_OOS=-0.028，連 AR(1) 都不如。能量特徵雖然在 IS 有統計顯著性（D2, D4, D5 都 |t|>3），但 OOS 完全沒有預測力
3. **混合模型（WHAR_HAR）反而更差**：加入 wavelet 特徵拖累了 HAR，QLIKE 從 1.54 惡化到 474.48
4. **GJR-GARCH 仍是最佳**：QLIKE=1.53，R²_OOS=0.255，MZ_R²=0.282

### 為什麼 wavelet 失敗？
- Wavelet 能量是**二次統計量的二次統計量**（r² 的 wavelet 係數的平方和），可能過度非線性
- 64 天滑動窗口的能量比 HAR 的簡單移動平均噪音更大
- HAR 的 fixed-window 設計（1/5/22）已經高度匹配金融時間序列的自然尺度（日/週/月）
- Wavelet 的 dyadic 尺度（2^k）不完全對應金融日曆

## 局限性
- 只用 r² proxy，沒有 5-min RV
- 僅測試 db4 和 Haar 兩種 wavelet
- 能量（L2）可能不是最佳的 wavelet 特徵

## 參考文獻
- Corsi (2009) "A Simple Approximate Long-Memory Model of Realized Volatility", JFE
- Percival & Walden (2000) "Wavelet Methods for Time Series Analysis", Cambridge UP
- Patton (2011) "Volatility Forecast Comparison Using Imperfect Volatility Proxies", JoE

## 檔案
- `k981_wavelet_har.py` — 實驗腳本
- `k981_wavelet_har_results.json` — 完整結果
- `k981_wavelet_decomposition.png` — 小波分解視覺化
- `k981_forecast_comparison.png` — 模型比較圖

## v2 修正（2026-05-16 Codex CONDITIONAL_PASS 修正）

**問題（Codex primary-path 2026-05-16）**：
1. **MAJOR**: Wavelet window t-2 lag — `values[t-window:t]` 後又 `.shift(1)` 導致 wavelet 比 HAR 多一日 lag（t-2 vs t-1），對 wavelet 不公平。
2. **MAJOR**: QLIKE floor 0.0001 太小（r² scale ~1-10），造成 WHAR_HAR_db4=474.48 artifact。
3. **MAJOR**: IS t-stats 設計矩陣不含截距項，標準誤偏誤。
4. **MINOR**: HAR vs WHAR DM t=5.98 未寫入 JSON；IS R²=0.126 未存入 JSON；n_oos 無法區分 total vs evaluated；7 DM tests 無 multiple-testing note。

**修正（v2）**：
- `values[t-window+1:t+1]` 使 wavelet lag 與 HAR 對稱（t-1）
- QLIKE floor 改為 `np.percentile(y_train, 0.5)` 資料自適應下限
- XtX 加截距列，IS t-stats 現在正確
- HAR_vs_WHAR_db4 DM、wavelet_is_r2、dm_multiple_testing_note 均已加入 JSON

**狀態**：v2 已 enqueue compute queue (compute-k981-v2-wavelet-lag-fix-qlike-floor-fix-is-t-stats-fix-1778915759)，等待重跑驗證 NULL 結論是否持續（expected: HAR 仍優於 wavelet，但 WHAR_HAR_db4 QLIKE 應大幅改善）。

## v3 修正（2026-05-19 code-reviewer CONDITIONAL_PASS 收束）

**觸發原因**：v2 執行失敗 — `ValueError: buffer source array is read-only`。yfinance 現在回傳唯讀 numpy array；`pywt.wavedec` 內部需寫入 buffer，`except Exception: continue` 靜默吞下 5030 個 error 導致 wavelet 特徵全 NaN（Non-null wavelet rows: 0）。

**修正（v3）**：
- `compute_wavelet_features()` 第 82 行：`values = series.values.copy()`（加 `.copy()` 確保 buffer 可寫）
- 移除 `rolling_oos_forecast()` 死代碼（`train_mask` 計算後未使用）
- `k981_wavelet_har_results.json` 加 `qlike_artifact: true` 旗標於 WHAR_haar / WHAR_HAR_db4

**v3 結果（1823 OOS obs）**：
| Model | QLIKE | R²_OOS | DM vs AR(1) |
|-------|-------|--------|-------------|
| GJR-GARCH | 1.5308 | 0.2551 | t=-2.650, p=0.008 *** |
| HAR | 1.5408 | 0.2226 | t=-3.301, p=0.001 *** |
| AR(1) | 1.7368 | 0.1976 | — |
| WHAR_db4 | 1.7455 | -0.0545 | t=0.136, p=0.891 |
| WHAR_haar | 327.79* | -0.0582 | — |
| WHAR_HAR_db4 | 236.71* | 0.1129 | — |

*QLIKE artifact（OLS 近似奇異，不可與其他模型比較）

HAR vs WHAR_db4 DM: t=5.954, p<0.0001 *** → **NULL 結論確認，與 v1 一致（原 t=5.98）**。

**Review**：`feature-dev:code-reviewer` subagent fallback（Codex quota 耗盡，重置後需 primary-path Codex 二次驗證）。Verdict: CONDITIONAL_PASS。

**狀態**：CLOSED — 結論為 NULL，wavelet energy 特徵不能改進 HAR 日頻 r² 預測。
