# K1100g_d5 — Overnight gap² 替代 night session r² (Student-t PRG)

[提出: Claude 自主研究 / 執行: Claude worktree agent-af9d1ed4]

## 1. 動機

K1100g 原始 daily session ratio 1.586 被 K1100g_d1 揭穿不是 pure session asymmetry,
而是 **gap effect**（13:45→15:00 close-to-open + 05:00→08:45 overnight gap 兩個 jump
期集中了絕大部分跨 session 變異）。

K1100g_d3 用 5-min aggregated night r² 作 exog → Student-t OOS borderline PASS
（LRT 14.61, QLIKE +3.78%, 但 DM t=1.92 未過 Harvey (2016) |t|>3 threshold）。
K1100g_d4 annual stability 也很弱（0/5 年通過 1% IS LRT）。

**K1100g_d5 核心假說**：如果 gap 才是真正 info carrier（不是整個夜盤 5-min RV），
改用**純 gap²** 作 exog 理論上應該比 night session r² 更強，可能讓 DM t 跨越 Harvey
threshold。

## 2. 假說

| # | 假說 | 判準 | 意涵 |
|---|------|------|------|
| H1 | gap saves | M2_gap_total OOS DM t > 3 Harvey PASS + LRT > 7.88 + QLIKE > 1% | 純 gap info 最強 → Paper 3 anchor 建立 |
| H2 | both similar | gap ≈ REF_night_r² DM t 類似量級 | gap 跟 night RV 相似 → Paper 3 reframe 仍 borderline |
| H3 | night_r² better | REF_night_r² DM t > gap² DM t | 5-min 夜盤 RV 才是 info carrier，gap 非 main driver |

## 3. 設計

### 3.1 Data

TAIFEX TX 2017-2021 session cache（繼承自 K1100g_d3）。本實驗多需 gap 兩項,
且都要非空 → 嚴格 alignment **N=1071**（比 K1100g_d3 的 1077 少 6 筆因
`gap_day_lag` 起始 lag 損失）。

### 3.2 Gap 構造（使用 cache 既有欄位）

```
gap_day[t]   = log(night_open_t / day_close_t)             ← 13:45→15:00 同日 close→open
gap_night[t] = log(day_open_t / night_close_{t-1}) = r_overnight_gap  ← 05:00→08:45 overnight close→open
```

**Information set（預測 r_day[t]² 的合法 exog）**：

| 變數 | 實現時間 | Legal？ |
|------|---------|--------|
| gap_night[t]  | 08:45 day t 開盤**前**已實現 | ✓ contemp |
| gap_day[t-1]  | 昨日 15:00 已實現 | ✓ lagged |
| gap_day[t]    | 13:45 day t 收盤**後**才實現 | ✗ lookahead |

**Gap² exog 定義**：

```
gap2_exog_total[t] = gap_night[t]² + gap_day[t-1]²   (全部合法 gap info)
```

### 3.3 模型對比（全 Student-t，df 聯合估計）

| Model | Exog | 說明 |
|-------|------|------|
| M1_baseline     | (none)                    | day-only PRG 基線 |
| M2_gap_night    | gap_night[t]²             | 純 overnight gap (05:00→08:45) |
| M2_gap_day_lag  | gap_day[t-1]²             | 純 同日 gap 的 lag (13:45→15:00) |
| **M2_gap_total**| gap_night[t]² + gap_day[t-1]² | **合併全部 legal gap²** |
| M2_signed_gn    | gap_night[t] (signed, 非平方) | 不對稱性測試 |
| **REF_night_r2**| r_night[t]²               | **K1100g_d3 M4 spec, 直接對照 benchmark** |

PRG kernel 與 K1100g_d3 完全相同（Student-t, tau×g, 9 PRG params + ξ + df）。

### 3.4 評估

- IS: LRT (dof=1) 每個 exog model vs M1_baseline
- OOS: expanding-window refit_every=5, train 2017-2019 (n=607), test 2020-2021 (n=464)
- 跨模型 DM: M2_gap_total vs REF_night_r² (誰是真 info carrier？)

### 3.5 Lookahead 紀律

- gap_night[t] 組成要素 `day_open[t]` 和 `night_close[t-1]` 都在 08:45 前實現
- gap_day[t-1] 全部來自昨日，遞迴中使用 `exog[t]`（已 shift 到 t-1 位置）
- Student-t innovation (K1100g_d3 教訓)
- seed=42, L-BFGS-B deterministic

## 4. 結果

### 4.1 Gap 系列 descriptives

| 系列 | sd | skew | excess kurt |
|------|----|------|-------------|
| gap_night_t | 1.18e-2 | **−1.43** | 11.10 |
| gap_day_lag | 1.05e-2 | +0.94 | 9.12 |

- gap_night 強負偏（COVID 等連夜跳空主要往下）
- gap_day_lag 正偏（反向，可能因白天大跌後夜盤反彈）
- `var(gap_total) / var(r_night²) = 36.7` → gap² 比 5-min 夜盤 r² 變異大得多

### 4.2 IS 全樣本 LRT（Student-t）

| Model | log_lik | LRT vs M1 | p-value | xn |
|-------|---------|-----------|---------|-----|
| M1_baseline      | 3859.634 | —        | —         | — |
| M2_gap_night     | 3868.899 | **18.53** | 1.7e-05  | +0.0601 |
| M2_gap_day_lag   | 3863.433 | 7.60     | 5.8e-03  | +0.0601 |
| **M2_gap_total** | 3869.071 | **18.87** | **1.4e-05** | +0.0601 |
| M2_signed_gn     | 3861.403 | 3.54     | 6.0e-02  | −0.0005 |
| REF_night_r2     | 3867.785 | **16.30** | 5.4e-05  | +0.1403 |

**觀察**：
- M2_gap_total IS LRT = 18.87 **強於** REF_night_r2 的 16.30 → gap² 在 in-sample 確實更多信息
- M2_signed_gn 幾乎 null（squared 才重要，不是方向）
- gap_day_lag 單獨已經 p<0.01 PASS

**方法論警示**：M2_gap_night/day_lag/total 的 xn 都收斂到 ~0.0601，雖然三個 exog
series 不同，但 optimizer 在 warm start 附近找到類似解。由於 LL 明顯不同
(3868.9 vs 3863.4 vs 3869.1)，exog 路徑確實不同 → 結果有效；但 tight clustering
提示 likelihood 在該區域相對平坦，xn 估計的小樣本 SE 可能較大。

### 4.3 OOS expanding-window（Student-t）

| Model | n | LRT χ² | **DM-HLN t** | QLIKE improv | 2020 | 2021 |
|-------|---|--------|--------------|---------------|------|------|
| M2_gap_night     | 464 | 7.30  | +1.29  | +4.75% | +7.81% | +1.15% |
| M2_gap_day_lag   | 464 | 1.16  | +0.14  | +0.42% | −2.94% | +4.38% |
| **M2_gap_total** | 464 | **14.37** | **+1.49** | **+6.62%** | +8.82% | +4.02% |
| M2_signed_gn     | 464 | 0.00  | −0.27  | −1.02% | −2.75% | +1.02% |
| **REF_night_r2** | 464 | **14.94** | **+2.01** | +3.80% | +4.60% | +2.86% |

Harvey (2016) |t|>3 門檻：**全部未過**。

### 4.4 Cross-model DM（gap vs night_r²，誰是真 info carrier？）

| 比較 | DM-QLIKE t | p | DM-loglik t | QLIKE_a | QLIKE_b |
|------|------------|---|-------------|---------|---------|
| M2_gap_total vs REF_night_r2 | −0.72 | 0.47 | +0.04 | 1.5347 | 1.5810 |
| M2_gap_night vs REF_night_r2 | −0.31 | 0.76 | +0.82 | 1.5653 | 1.5810 |
| M2_gap_night vs M2_gap_total | +0.96 | 0.34 | +0.82 | 1.5653 | 1.5347 |

兩邊 DM p-value 都 > 0.3，**gap² 和 night_r² 沒有統計上可區分的差異**。
QLIKE mean 上 M2_gap_total（1.5347）略低於 REF_night_r2（1.5810）但差距小且 insig。

### 4.5 Verdict — `H3_NIGHT_R2_BETTER`

依 verdict 規則：M2_gap_total DM t=+1.49 < REF_night_r2 DM t=+2.01（差 0.5 以上）。
程式判定 **H3**。

但細看其實更接近 **H2（both similar）**：

| 指標 | M2_gap_total | REF_night_r2 | 差 |
|------|--------------|-------------|-----|
| IS LRT | 18.87 | 16.30 | **+2.57 gap 贏** |
| OOS LRT | 14.37 | 14.94 | −0.57 |
| OOS DM t | +1.49 | +2.01 | −0.52 |
| OOS QLIKE improv | +6.62% | +3.80% | **+2.82% gap 贏** |
| 2020 improv | +8.82% | +4.60% | **+4.22% gap 贏** |
| 2021 improv | +4.02% | +2.86% | +1.16% |
| Cross-DM | — | — | p=0.47（不可區分） |

**關鍵矛盾**：gap_total 的 QLIKE mean 改善更大（+6.62% vs +3.80%），
但 DM t 較小（1.49 vs 2.01）。意思是 **gap² 提供更大的平均改善，但波動更大
（signal-to-noise ratio 較差）**；night_r² 提供較小但較穩定的改善。

**修正解讀**：H2_GAP_AND_NIGHT_SIMILAR（實務等級）——gap² 和 night_r² 在這個樣本
下**屬於同一 signal 等級**，都沒過 Harvey threshold，都無法作為 Paper 3 reframe
的強 anchor。差別在於 gap² 平均改善大但 noisier，而 night_r² 較 stable。

### 4.6 Paper 3 reframe 是否真正 anchor？

**否**。K1100g_d5 的結論進一步加深 K1100g_d3/d4 已經觀察到的模式：

- TAIFEX night→day predictive signal **方向正確**（兩個 exog 設計都 positive DM）
- **統計上 borderline**（全部 DM t 在 1.3-2.0 間，無一過 Harvey 3.0）
- 改用「純 gap²」不能讓信號跨越 Harvey threshold
- Gap² 並非比 5-min night RV 更強的 info carrier；兩者提供本質相同的信息

**Paper 3 reframe 的可能出路**：

1. **延伸樣本**：K1100g_d6 候選（2022-2025），N ~ 1000→2000 有機會讓 DM 過 3.0
2. **跨市場複製**：SPY overnight, N225 morning — 如果同一方向在其他市場重現，
   可作為 structural claim 而非 Taiwan-specific
3. **承認 signal 弱**：論文改為「direction consistent but statistical strength
   borderline」的 nuanced claim，承認 TAIFEX night→day asymmetric structure
   是真但弱的 effect

## 5. 限制

1. **OOS N=464 仍在 asymptotic 邊界**：Harvey threshold 在中等 N 下較難跨越；
   延伸到 2022-2025 可提升 N。
2. **xn 估計 clustering (0.0601)**：多個 gap model 收斂到相同 xn，likelihood
   surface 可能較平坦，小樣本 SE 有放大風險。
3. **未做 Winsorization**：單日極端 gap（如 2020 Mar COVID）對 gap² 影響大於
   對 5-min aggregated r²；gap² 更大 QLIKE mean 改善但 DM t 較小的現象部分
   源於此。Robustness 可用 winsorized gap² 重測。
4. **Symmetric Student-t**：gap_night skew=−1.43 強負偏；asymmetric-t (Hansen 1994)
   或 skew-t 可能讓 gap signed 項更有力。
5. **單市場**：未做 SPY overnight gap / N225 morning 的跨市場複製。
6. **gap 與 r_night 信息重疊**：r_night 本身不完全獨立於 gap — 5-min 夜盤
   aggregated return 起點是 15:00，與 gap_day_lag 末端銜接。兩者 CROSS-DM
   p=0.47 也暗示 overlap。

## 6. 對 K1100g 系列的意涵

### 6.1 K1100g session ratio 1.586 的再解讀

- K1100g 報告 TAIFEX 隔夜/日盤 vol ratio = 1.586（K1100g_d1 拆解為 gap effect）
- K1100g_d3 用 r_night² 做 exog → Student-t 下 borderline
- K1100g_d5 證明：**改用 pure gap² 並未讓 signal 變強**
- 結論：dim2 的 1.586 ratio 反映的 **既不是「5-min 夜盤 RV 特有」、也不是「純 gap
  特有」，而是兩者都共享的 overnight information**

### 6.2 Paper 3 narrative 再調整

**K1100g_d5 建議 claim**：

> Under Student-t innovation, TAIFEX overnight information (whether encoded
> as 5-minute night-session RV or as pure close-to-open gap²) adds
> directionally consistent but statistically borderline predictive power
> for next-day session variance. OOS DM-HLN t-statistics range from +1.29
> to +2.01 across encodings (N=464), none exceeding the Harvey (2016)
> threshold of 3.0. Cross-model DM between gap² and night-r² (p=0.47) shows
> the two encodings are statistically indistinguishable at this sample size.
> Paper 3 reframe should therefore be **decoupled from choice of encoding**
> — TAIFEX night→day predictability is a weak-but-consistent property, not
> contingent on a particular signal specification.

## 7. 衍生方向

1. **K1100g_d6**：延伸 OOS 樣本至 2022-2025（N=464 → ~1200），測試 DM t 是否
   過 Harvey 3.0
2. **K1100g_d7**：SPY overnight gap² 跨市場複製 — 同 signal 是否在 US 存在？
3. **K1100g_d8**：Winsorized gap² 測試（1% / 5% winsor）對 DM stability 的影響
4. **Asymmetric-t PRG**：用 Hansen (1994) skew-t 處理 gap_night 強負偏；預期
   M2_signed_gn 的 asymmetric 項可能變顯著

## 8. 檔案

- `k1100g_d5.py` — Student-t PRG 腳本（IS + OOS + cross-DM）
- `k1100g_d5_results.json` — 完整結果
- `k1100g_d5_is_lrt_bar.png` — IS LRT 各 exog 變數 vs M1 bar chart
- `k1100g_d5_oos_dm_comparison.png` — OOS 30d rolling QLIKE + DM bar
- `data/_cache_taifex_sessions_2017-2021.parquet` — 繼承自 K1100g_d3
- `run.log` — 執行 log

## 9. 參考文獻

- **Bollerslev (1987)** "A Conditionally Heteroskedastic Time Series Model
  for Speculative Prices and Rates of Return", *REStat* 69(3), 542-547 —
  Student-t GARCH
- **Engle & Rangel (2008)** "The Spline-GARCH Model for Low-Frequency
  Volatility and Its Global Macroeconomic Causes", *RFS* 21(3) —
  multiplicative τ×g PRG
- **French & Roll (1986)** "Stock return variances: The arrival of
  information and the reaction of traders", *JFE* 17(1), 5-26 —
  non-trading-hour information bundling
- **Andersen, Bollerslev, Huang (2011)** "A reduced form framework for
  modeling volatility of speculative prices based on realized variation
  measures", *JoE* 160(1) — overnight jump vs continuous
- **Harvey, Leybourne & Newbold (1997)** "Testing the Equality of Prediction
  Mean Squared Errors", *IJF* 13(2) — HLN DM correction
- **Harvey (2016)** "Presidential Address: The Scientific Outlook in
  Financial Economics", *JF* — t>3 threshold
- **Hansen (1994)** "Autoregressive Conditional Density Estimation", *IER*
  35(3) — asymmetric-t

## 10. Seed 與可重現性

- `np.random.seed(42)` + `np.random.default_rng(42)`
- `fit_prg_student()` 內部 `np.random.default_rng(42)` 建 restart 初值
- L-BFGS-B deterministic；warm-start from prev OOS refit
- 重跑應得到完全相同的 IS/OOS 結果（IS LRT、OOS DM t、QLIKE improv 到 4 位小數）
