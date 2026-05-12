# K1315: Forecast Combination — Anti-QLIKE Weighted Ensemble

## 研究問題

K530 (★★★★) 確認 HAR-VIX (QLIKE=-3.917) 是 SPY 最強個別模型，優於 HAR-ABS (QLIKE=-3.892)。
**核心問題**：組合預測（等權、反QLIKE加權、Bates-Granger OLS）能否在統計上顯著超越最佳個別模型 HAR-VIX？

## 設計

| 項目 | 規格 |
|------|------|
| 資產 | SPY (yfinance, 日頻) |
| 預測目標 | `\|r_t\|` (日絕對報酬, HAR-ABS paradigm) |
| IS 期間 | 2005-01-04 to 2018-12-31 (n=3522) |
| OOS 期間 | 2019-01-02 to 2024-12-30 (n=1509) |
| HAR 係數更新 | Static (IS 估計後固定，與 K530 一致) |
| 組合 weights | Expanding window (只用 t-1 以前 OOS loss) |

### 模型池

1. **HAR-ABS**：regressors = rv1, rv5, rv22 (lag 1/5/22-day `\|r\|`)
2. **HAR-VIX**：HAR-ABS + VIX_{t-1}
3. **Equal-Weight**：(HAR-ABS + HAR-VIX) / 2
4. **Anti-QLIKE**：w_i ∝ 1/(excess_QLIKE_i + ε)，expanding window
5. **Bates-Granger**：constrained OLS β1+β2=1，expanding window

## Lookahead 防護

| 特徵 | 公式 | 說明 |
|------|------|------|
| rv1_t | `abs_r.shift(1)` | 使用 t-1 日報酬 |
| rv5_t | `abs_r.rolling(5).mean().shift(1)` | 使用 t-5..t-1 |
| rv22_t | `abs_r.rolling(22).mean().shift(1)` | 使用 t-22..t-1 |
| VIX_t | `vix_level.ffill().shift(1)` | 使用 t-1 收盤 VIX |
| Combo weights | expanding window over OOS[0..t-2] | t 時刻只用 t-1 以前 OOS losses |

## 結果

### OOS QLIKE (Patton 2011 form B: E[log(ŷ) + \|r\|/ŷ])

| 模型 | QLIKE | MSE |
|------|-------|-----|
| Bates-Granger | **-3.9181** | 0.00006086 |
| HAR-VIX | -3.9170 | 0.00006037 |
| Anti-QLIKE | -3.9167 | 0.00006046 |
| Equal-Weight | -3.9138 | 0.00006058 |
| HAR-ABS | -3.8918 | 0.00006421 |

### DM-HLN Tests (Harvey et al. 1997, h=1, NW bandwidth=T^(1/3))

| 比較 | DM stat | p-value | Harvey (|t|>3.0) |
|------|---------|---------|-----------------|
| Anti-QLIKE vs HAR-VIX | +1.08 | 0.279 | No |
| Equal-Weight vs HAR-VIX | +1.04 | 0.297 | No |
| Bates-Granger vs HAR-VIX | -0.69 | 0.492 | No |
| Anti-QLIKE vs HAR-ABS | -3.98 | 0.0001 | **Yes** |
| Equal-Weight vs HAR-ABS | -5.96 | <0.0001 | **Yes** |
| Bates-Granger vs HAR-ABS | -4.59 | <0.0001 | **Yes** |

### Verdict: PASS_NULL

**任何組合預測均未以 Harvey 3σ 門檻顯著超越 HAR-VIX。**

- Bates-Granger 有最低 QLIKE (-3.9181)，略優於 HAR-VIX (-3.9170)，但差距 DM t=-0.69，遠低於顯著性水準。
- Anti-QLIKE 最終 weights 收斂至 HAR-ABS=0.000, HAR-VIX=1.000 — VIX 完全主導組合。
- 所有組合均以 Harvey 3σ 顯著優於 HAR-ABS（VIX 是關鍵增量信息來源）。

## 結論

1. **VIX 是充分統計量**：在 SPY 2019-2024 OOS 期間，加入 HAR-ABS 無法對 HAR-VIX 帶來統計顯著的額外信息。
2. **理論支撐**（研究方向 D）：VIX 作為市場隱含波動率，已充分涵蓋日頻 |r| 預測所需的所有短中期記憶成分，與 Corsi (2009) HAR 的多尺度 RV 特徵在信息上高度重疊。
3. **Bates-Granger 稍優**：numerically 最佳，但差距不顯著——符合「best-wins」情況（Timmermann 2006：某模型信噪比遠超其他時，組合無額外益）。
4. **發表價值**：此 null result 確認並強化 K530 發現，可作為「VIX 的資訊含量已飽和」類文章的依據，亦可作為論文附錄補充分析。

## 方法論注意事項

- QLIKE formula (Patton 2011 form B): `log(ŷ) + y/ŷ`，可為負值（daily |r| << 1）。K530 使用 form A (`y/ŷ - log(y/ŷ) - 1`，恆正)，兩者均為 robust loss，但數值尺度不同，不可直接比較絕對值。
- DM-HLN 修正：forecast horizon h=1（1-step-ahead）與 NW bandwidth=T^(1/3) 分開設定（Codex review 發現並修正）。
- Anti-QLIKE weighting：使用 excess loss 方法（`1/(mean_QLIKE_i - min_mean + ε)`）以確保 QLIKE 為負值時權重仍有意義（Codex review 發現並修正）。
- Bates-Granger：純 sum-to-one OLS，無非負約束（Codex review 確認，移除原有 `clip(0,1)` 以符合 Bates-Granger 1969 原始設定）。

## 圖表

- `k1315_oos_qlike_comparison.png`：OOS QLIKE 條形圖
- `k1315_cumulative_qlike.png`：累積 QLIKE 損失折線圖

## 參考文獻

- Corsi (2009, JFE): HAR-RV model
- Patton (2011, JFE): Robust loss functions for volatility forecasting
- Harvey, Leybourne & Newbold (1997, IJoF): Finite-sample DM test correction
- Timmermann (2006, HEF): Forecast combinations
- Genre et al. (2013, IJoF): Combination methods comparison
- Bates & Granger (1969, OR): Constrained OLS forecast combination

## 相關實驗

- K530 (★★★★): HAR Multi-Scale — confirms HAR-VIX best individual model
- K529 (★★★): HAR-Rough — HAR beats GJR-GARCH (DM=-7.04)
