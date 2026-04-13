# K1100g_d3 — Student-t PRG innovation 厚尾檢驗

[提出: Claude 自主研究 / 執行: Claude worktree agent-k1100g-d3]

## 1. 動機

K1100g_d1（Normal innovation）報 **IS LRT χ²=12.48, p=0.0004**（M4 加 night 
exog vs M2），被視為 Paper 3「夜盤→日盤 asymmetric prediction」reframe anchor。
但 K1100g_d2 用 **Normal expanding-window OOS** 完全推翻（χ²=0.00, DM t=-0.21, 
QLIKE 惡化 0.48%）。

K1100g_d1/d2 都使用 **Gaussian QML**。TAIFEX 日內 return 是**顯著厚尾**的：

| 序列 | Excess kurtosis | Skew |
|------|----------------|------|
| r_day | 6.77 | −0.47 |
| r_night | 11.99 | −1.61 |
| r_combined | 9.67 | −0.49 |

Normal innovation 會嚴重低估尾部機率。本實驗直接檢驗：**Student-t innovation 
是否改變 K1100g_d1/d2 的結論？**

## 2. 假說

| # | 假說 | 判準 | 意涵 |
|---|------|------|------|
| H1 | Student-t 救回訊號 | OOS LRT χ² > 7.88、QLIKE 改善 > 1%、DM Harvey t>3、2020/2021 都過 | Normal mis-specification 掩蓋真訊號 |
| H2 | Student-t 同結果 | OOS 仍 reject | Paper 3 reframe 完全死 |
| H3 | IS 降 OOS 仍死 | Student-t IS LRT < Normal × 0.5 且 OOS reject | Normal 過度敏感 |

## 3. 設計

### 3.1 PRG Kernel（與 K1100g_d1 完全相同）

```
τ_t  = θ₀ + θ₁·r²_{t-1} + Σ_k δ_k·D_k,t  [+ ξ·exog]
g_t  = ω + α·u²_{t-1} + γ·u²_{t-1}·I(r<0) + β·g_{t-1},  u_{t-1}=r_{t-1}/√τ_{t-1}
h_t  = τ_t × g_t
ω    = 1 - α - γ/2 - β   (identification: E[g]=1)
```

### 3.2 Innovation

- **Normal (QML)**：`r_t | F_{t-1} ~ N(0, h_t)` — 複製 K1100g_d1/d2
- **Student-t (MLE)**：scale² = h·(df−2)/df，使 `Var(r) = h`；df > 2 強制

### 3.3 模型（5 個，對齊 K1100g_d1）

| Model | Target | Exog | k_Normal | k_Student-t |
|-------|--------|------|---------|-------------|
| M1 | r²_combined | — | 9 | 10 |
| M2 | r²_day | — | 9 | 10 |
| M3 | r²_night | — | 9 | 10 |
| M4 | r²_day | r_night[t]² (contemp) | 10 | 11 |
| M5 | r²_night | r_day[t-1]² (lag) | 10 | 11 |

### 3.4 評估

- **IS** LRT（全樣本 n=1077, 2017-05 ~ 2021-12）
- **OOS** expanding-window refit（REFIT_EVERY=5；train 613, test 464；與 K1100g_d2 一致）
- **VaR Trinity**（Kupiec + Christoffersen CC）在 1% 與 5% 信心水準
- Sub-period 2020 vs 2021 穩定性

## 4. 結果

### 4.1 IS 對比 — Normal vs Student-t

**M2 / M4 log-likelihoods**:
- Normal: M2=3847.92, M4=3854.16 → LRT χ²=**12.48**（K1100g_d1 完全重現）
- Student-t: M2=3884.21, M4=3892.25 → LRT χ²=**16.09**（p = 6.0e-05）

**M3 / M5 log-likelihoods**:
- Normal: M3=4194.88, M5=4196.47 → LRT χ²=**3.18**（p = 0.075）
- Student-t: M3=4225.57, M5=4241.06 → LRT χ²=**30.99**（p = 2.6e-08）

所有 Student-t log-lik 都比 Normal 高 **30-45 單位**（+1% 到 +2% per-obs），
且 **df ∈ [5.1, 9.1]**，確認 TAIFEX innovations 嚴重厚尾。
**Student-t 下 IS LRT 非但沒降低，反而放大**（特別是 M5 從 3.18 跳到 30.99）。

### 4.2 OOS Student-t（與 K1100g_d2 的 Normal 直接對比）

| 指標 | Normal (K1100g_d2) | Student-t (K1100g_d3) |
|------|-------------------|----------------------|
| OOS LRT χ² | **0.000** (p=1.00) | **14.608** (p=1.3e-4) |
| DM-HLN t | −0.21 (p=0.83) | **+1.92** (p=0.055) |
| QLIKE improv | **−0.48%**（惡化） | **+3.78%**（改善） |
| 2020 improv | −0.98% | **+4.74%** |
| 2021 improv | +0.10% | **+2.64%** |
| df_full mean | N/A | 6.63 |
| df_null mean | N/A | 8.67 |

**結論反轉**：Student-t 下 OOS 顯示 **M_full (night→day) 勝 M_null ~3.8%**，
兩個子期間一致方向，LRT p<0.001。Normal QML OOS 的 0.48% 惡化是 
**innovation mis-specification 造成的 artifact**。

### 4.3 VaR Trinity OOS（兩模型都未過）

| Level | Model | Breach rate | Kupiec p | CC p | Trinity |
|-------|-------|-------------|----------|------|---------|
| 1% | M_null (t) | 3.66% | 8.8e-06 | 4.6e-05 | FAIL |
| 1% | M_full (t) | 3.23% | 1.3e-04 | 5.1e-04 | FAIL |
| 5% | M_null (t) | 8.41% | 2.1e-03 | 8.6e-03 | FAIL |
| 5% | M_full (t) | 8.41% | 2.1e-03 | 8.6e-03 | FAIL |

兩個模型的 breach rate 都**顯著高於目標**。這不是「night exog 有沒有用」的
問題——兩邊都失敗。原因可能是：
- 2020 COVID 衝擊是 tail-fat regime（Student-t 仍不夠厚）
- 需 TGARCH + asymmetric Student-t (Hansen 1994 skew-t)
- TAIFEX 2020-2021 真實尾部比 df≈5 還厚（極端事件未被 df 吸收）

M_full 1% breach 從 3.66% 降到 3.23% 方向正確但效果有限。

### 4.4 Verdict

**`H1_STUDENT_T_SAVES_PARTIAL`**

具體 criteria：

| 條件 | 判準 | 結果 |
|------|------|------|
| LRT strong | OOS χ² > 7.88 | ✓ PASS (14.6) |
| QLIKE meaningful | > 1% | ✓ PASS (+3.78%) |
| Harvey DM | \|t\| > 3.0 | ✗ FAIL (1.92) |
| Both sub-periods | 2020 和 2021 都 > 1% | ✓ PASS (4.74%, 2.64%) |
| df flag | min df > 3 | ✓ PASS (6.61) |

**Paper 3 reframe 部分 salvage**：Student-t 證據方向正確（4/5 criteria 通過）
但 Harvey (2016) t>3 threshold 未過，因此**不足以作為強 claim**。需要：

1. 延伸樣本期至 2022-2025 增加 N（當前 OOS n=464）以嚐試跨越 Harvey threshold
2. 跨市場複製（SPY overnight-gap, N225 morning+afternoon）
3. Asymmetric-t 或 GHT 驗證（處理 skew=-1.6 的強負偏）

## 5. 限制

1. **DM |t|=1.92 未過 Harvey (2016) threshold**：只靠 LRT 和 QLIKE magnitude 
   不足以宣稱 Paper 3 reframe 成立（需要 Harvey-robust DM test）
2. **VaR Trinity 完全失敗**：表示 Student-t 仍低估 tail；真實 tail 更厚
3. **N_test=464** 對 asymptotic χ² 仍嫌小
4. **單一市場**：跨市場複製（K1100g_d4 候選）仍未做
5. **Symmetric Student-t**：TAIFEX skew=-1.6（night session）極強負偏；asymmetric-t (Hansen 1994) 會更適合
6. **VaR 結構問題**：兩模型都失敗 — 反映整個 PRG 對 tail events 估計不足，不是 night→day 訊號本身的問題

## 6. 對 K1100g_d2 和 Paper 3 的意涵

### K1100g_d2 的結論需要部分 qualify

K1100g_d2「Paper 3 anchor REJECTED」的結論需要附註：
- Normal QML OOS 反轉是 **innovation mis-specification 產物**
- 真實 fat-tail-aware OOS（Student-t）顯示 night→day **方向正確**
- 但 Harvey-robust 證據不足，因此不能反向宣稱 Paper 3 reframe 完全 vindicated

### Paper 3 narrative 調整

**原 K1100g_d1 claim**：night session 攜帶 asymmetric predictive information → 
被 K1100g_d2 推翻為 data mining。

**K1100g_d3 修正 claim**：
> Under innovation distribution appropriately accounting for TAIFEX's heavy 
> tails (Student-t df≈6-9), night session exogenous variance retains OOS 
> predictive power for day session variance (LRT χ²=14.6, QLIKE +3.78%), 
> consistent across COVID and recovery sub-periods. However, the DM-HLN 
> statistic (|t|=1.92) falls short of the Harvey (2016) threshold for 
> strong claims, suggesting the effect is **directionally real but 
> statistically borderline** at this sample size. Proper inference 
> requires (a) longer OOS sample or (b) cross-market replication.

### 教訓

**Innovation assumption matters for nested-model OOS comparison in fat-tail 
data.** K1100g_d1 IS LRT 與 K1100g_d2 OOS DM 的方向反轉，不是「真實效果消失」
而是「Gaussian mis-specification 讓額外 parameter 的評估偏誤變號」。
未來 TAIFEX/fat-tail 資產的模型比較應預設 Student-t 或 asymmetric-t。

## 7. 衍生方向

1. **K1100g_d4（跨市場 Student-t decomposition）**：SPY overnight gap / N225 
   morning-afternoon 在 Student-t OOS 下是否重現 night→day 方向性？
2. **K1100g_d5（Asymmetric-t + TGARCH）**：TAIFEX night skew=-1.6；用 
   Hansen (1994) skew-t + TGARCH 看 VaR Trinity 能否修復
3. **K1100g_d6（延伸 OOS 至 2022-2025）**：2 年 → 6 年 OOS 提升 N 能否讓 DM 
   越過 Harvey threshold

## 8. 檔案

- `k1100g_d3.py` — Student-t PRG 腳本（IS + OOS + VaR Trinity）
- `k1100g_d3_results.json` — 完整結果 JSON
- `k1100g_d3_is_lrt_normal_vs_student.png` — IS LRT Normal vs Student-t 對照圖
- `k1100g_d3_oos_student_qlike_df.png` — OOS 30 天 rolling QLIKE 差 + df 時序
- `data/_cache_taifex_sessions_2017-2021.parquet` — K1100g_d1 乾淨 session cache
- `run.log` — 執行輸出

## 9. 參考文獻

- **Bollerslev (1987)** "A Conditionally Heteroskedastic Time Series Model 
  for Speculative Prices and Rates of Return", *REStat* 69(3), 542-547 — 
  Student-t GARCH 標準參照
- **Engle & Rangel (2008)** "The Spline-GARCH Model for Low-Frequency 
  Volatility and Its Global Macroeconomic Causes", *RFS* 21(3) — τ×g 
  multiplicative PRG
- **Kupiec (1995)** "Techniques for Verifying the Accuracy of Risk 
  Measurement Models", *JoD* 3(2), 73-84
- **Christoffersen (1998)** "Evaluating Interval Forecasts", *IER* 39(4), 
  841-862 — CC test
- **Harvey, Leybourne & Newbold (1997)** "Testing the Equality of Prediction 
  Mean Squared Errors", *IJF* 13(2)
- **Harvey (2016)** "Presidential Address: The Scientific Outlook in 
  Financial Economics", *JF* — t>3 threshold
- **Hansen (1994)** "Autoregressive Conditional Density Estimation", *IER* 
  35(3) — asymmetric-t

## 10. Seed 與可重現性

- `np.random.seed(42)` + `np.random.default_rng(42)`
- `fit_prg()` 內部 `np.random.default_rng(42)` 建 restart 初值
- L-BFGS-B deterministic，Warm-start 用上次 params
- 重跑應得到完全相同結果（已 replicate K1100g_d1 Normal LRT=12.48）
