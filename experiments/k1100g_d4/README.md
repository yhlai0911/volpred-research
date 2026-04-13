# K1100g_d4 — Night→day PRG predictability 年度穩定性（Student-t）

[提出: Claude 自主研究 / 執行: Claude worktree agent-a14899fe]

## 1. 動機

K1100g_d3 在 Student-t innovation 下顯示 TAIFEX night→day asymmetric
predictability：

| 指標 | K1100g_d2 (Normal) | K1100g_d3 (Student-t) |
|------|-------------------|----------------------|
| OOS LRT χ² (M4 vs M2, full sample) | 0.000 | **14.61** (p=1.3e-4) |
| DM-HLN t | −0.21 | **+1.92** (borderline) |
| QLIKE improv | −0.48% | **+3.78%** |
| 2020 sub-period improv | −0.98% | **+4.74%** |
| 2021 sub-period improv | +0.10% | **+2.64%** |

2020 sub-period 的 QLIKE 改善是 2021 的 ~1.8 倍，提示 K1100g_d3 的訊號可能
**被 2020 COVID regime shift 放大**。若真結構性，每個年度單獨都該看到
LRT > 7.88 + xn coef 穩定；若 COVID-driven，僅 2020 有訊號其他年份 NS。

## 2. 假說

| # | 假說 | 判準 | 意涵 |
|---|------|------|------|
| H1 | 真結構性 | 5/5 年度 IS LRT > 7.88 且 xn coef 方向穩定（≥4/5 正向） | Paper 3 reframe 站得住 |
| H2 | COVID-driven | 僅 2020 IS LRT >> 7.88，其他年份 NS | 2020 是唯一驅動；reframe 撤回 |
| H3 | Mixed / transitional | 3-4 年 PASS | reframe 需加 caveat |

## 3. 設計

### 3.1 Data（同 K1100g_d3）
TAIFEX TX 2017-2021 session cache，n_aligned=1077:
- 2017: 151 days（2017-05-16 起）
- 2018: 232 days
- 2019: 230 days
- 2020: 233 days
- 2021: 231 days

### 3.2 PRG kernel（同 K1100g_d3，Student-t only）

```
τ_t = θ₀ + θ₁·r²_{t-1} + Σ_k δ_k·D_k,t  [+ ξ_n·r²_night,t]
g_t = ω + α·u²_{t-1} + γ·u²_{t-1}·I(r<0) + β·g_{t-1}
h_t = τ_t · g_t,   ω = 1 − α − γ/2 − β
r_t | F_{t-1} ~ t_df( scale² = h_t·(df−2)/df )   → Var(r_t) = h_t
```

- **M2** day-only (k=10: 9 PRG + df)
- **M4** day + r_night[t]² contemporaneous exog (k=11: 9 PRG + ξ_n + df)
- 8 L-BFGS-B restarts per fit，seed=42

### 3.3 Annual in-year fit
對每年 y ∈ {2017, ..., 2021}：在當年約 150-233 days 上分別 fit M2、M4，
計算 LRT χ² (df=1, 對 ξ_n 的檢定)，1% threshold = 7.88。

### 3.4 Pseudo-OOS per year
對每個 test year y ∈ {2018, 2019, 2020, 2021}：
- Train = all aligned rows with year < y（expanding window, single fit）
- 參數凍結 → forward h recursion through year y
- 計算 year y 的 QLIKE 改善 + DM-HLN + OOS log-likelihood LRT

2017 不 test（無訓練數據）。2018 訓練資料只有 151 days 要留意小樣本。

## 4. 結果

### 4.1 Annual IS LRT（M4 vs M2, Student-t）

| Year | n | LRT χ² | p-value | xn coef | Pass 1% (7.88) | Pass 5% (3.84) |
|------|---|--------|---------|---------|----------------|----------------|
| 2017 | 151 | **0.28** | 0.598 | **−0.066** | ✗ | ✗ |
| 2018 | 232 | **4.37** | 0.037 | +0.077 | ✗ | ✓ |
| 2019 | 230 | **2.84** | 0.092 | +0.049 | ✗ | ✗ |
| 2020 | 233 | **2.28** | 0.131 | +0.140 | ✗ | ✗ |
| 2021 | 231 | **0.19** | 0.662 | +0.077 | ✗ | ✗ |

**零年通過 1% threshold。** 僅 2018 通過 5%。
- **2020 單年 LRT 只有 2.28（NS）——H2 COVID-driven 也被拒**。
- xn coef 方向 4/5 正向（2017 負、其他正），方向性有提示但統計上不顯著。
- 2020 xn coef magnitude 最大（+0.14），與 K1100g_d3 full-sample OOS 的
  2020 強訊號一致，但樣本內單年不足以統計顯著。

### 4.2 Pseudo-OOS per year

| Test Year | n_train | n_test | QLIKE improv | DM-HLN t | OOS LRT χ² | Pass 1% |
|-----------|---------|--------|--------------|----------|------------|---------|
| 2018 | 151 | 232 | **−1.68%** | −0.36 | 0.04 | ✗ |
| 2019 | 383 | 230 | **+2.92%** | +1.06 | 1.80 | ✗ |
| 2020 | 613 | 233 | **−0.03%** | −0.01 | 0.00 | ✗ |
| 2021 | 846 | 231 | **+0.94%** | +0.53 | 3.53 | ✗ (p=0.060) |

**0/4 年 OOS LRT 通過 1%；0/4 年 DM-HLN |t| > 1.5。**

值得注意：
- **2020 pseudo-OOS (train=2017-2019) QLIKE improv 只有 −0.03%**，與 K1100g_d3
  full-sample OOS 在 2020 報的 +4.74% 有明顯落差。差別來自：(a) K1100g_d3
  train=2017-2019（一次），但 d3 用 expanding-window refit 每 5 天重估；(b)
  d4 這裡的 frozen-params 設計比 d3 更保守。d3 的 2020 sub-period improv 大
  量來自 refit 期間模型「學到」2020 的 regime。
- **2019 和 2021 方向 positive**，但 magnitude 小、DM t 小。
- **2018 方向 NEGATIVE**，但訓練樣本只有 151 days（小樣本偏誤）。

### 4.3 Verdict

**`H3_MIXED_MINORITY_PASS`（實際上比 H3 更弱）**：

| 條件 | 判準 | 結果 |
|------|------|------|
| H1 真結構 | 5/5 年 LRT > 7.88 | ✗ (0/5) |
| H1 xn 穩定 | ≥ 4/5 positive | ✓ (4/5) |
| H2 COVID-driven | 僅 2020 LRT > 7.88 | ✗ (2020 χ²=2.28, NS) |
| H3 mixed | 3-4 年 LRT > 7.88 | ✗ (0 年) |

- **H1 拒絕**：沒有任何年份 IS LRT 通過 1% threshold，表示 night→day 的 xn coef
  在單年~230 day 樣本內 *不是統計顯著的常態結構*。
- **H2 部分拒絕**：2020 雖 xn coef magnitude 最大 (+0.14)，但 IS LRT 只 2.28 (NS)。
  COVID 不是「唯一驅動」——更像「較強但仍弱的 signal 在各年共振」。
- **H3 也不完全成立**：沒有多數年通過 5%。

### 4.4 K1100g_d3 full-sample OOS 訊號的本質

本實驗的結論指向一個 nuanced 解讀：

K1100g_d3 的 full-sample OOS LRT χ²=14.61 *不是單年 regime shift 驅動*，
也不是 *每年穩定的結構性 signal*，而是 **「弱 signal 在多年累積 + Student-t
heavy-tail 權重調整」的合成效果**：

1. **xn coef 方向穩定（4/5 年正向）**——TAIFEX night session 資訊對日盤
   variance 有 *稍微正向* 的預測力，方向可信。
2. **單年 magnitude 不足統計顯著**——任一年度 xn coef 都 |t| 不到 2.5，
   表示這個 signal per-year 是「經濟上有點存在、統計上 borderline」的等級。
3. **K1100g_d3 full-sample LRT 顯著是因為 N≈1077 累積效果**——4 年 × 230 days
   的弱 signal 累積統計力放大。
4. **2020 COVID 不是單一驅動**，但 2020 的 xn magnitude（+0.14）顯著高於
   其他年（+0.05 ~ +0.08），所以 K1100g_d3 的 2020 sub-period OOS improv
   被放大——**但這是「正向 signal 在該年較強」而不是「signal 只存在於該年」**。

## 5. 限制

1. **單年 N≈230 對 Student-t PRG (k=11 parameters) 小樣本偏誤** — Wilks
   asymptotic χ²(1) 在 N<250 可能不準；應用 bootstrap 或小樣本校正。
2. **Expanding train pseudo-OOS 只 fit 一次**，不是 K1100g_d3 那種 5-day refit
   rolling；這是故意的（隔離 regime learning 效果），但會低估 K1100g_d3
   refitted OOS 的 signal。
3. **2018 pseudo-OOS train 只 151 days**（2017 起始延後）小樣本偏誤大；
   實際上 2018 的 −1.68% QLIKE improv 可能是 model underfit 的 artifact
   而非 signal 真的負向。
4. **2017 xn coef 為負**（−0.066）方向翻轉，但只 151 days；可能是起始期
   PRG 估計不穩造成。
5. **Asymmetric-t / skew-t 未測試**：TAIFEX night skew=−1.61；若 2020
   的強 signal 部分來自極端負偏，symmetric Student-t 仍 mis-specify。
6. **HAR-RV / intraday variance 未納入**：K1100g_d3 日內 RV 可能有
   complementary signal。

## 6. 對 K1100g_d3 / Paper 3 reframe 的意涵

### 6.1 K1100g_d3 結論需要再 qualify

K1100g_d3 的「Student-t saves PARTIAL」結論仍成立，但需要補充：

| 層級 | 說法 |
|------|------|
| Full-sample OOS | LRT χ²=14.6 有統計顯著（N=464 強） |
| Year-by-year IS | 無任何年 LRT > 7.88 — signal 不是年度強結構 |
| xn coef 方向 | 4/5 年 positive — 方向可信 |
| 本質解讀 | 弱 signal 在多年累積，2020 較強但非唯一源 |

### 6.2 Paper 3 narrative 再調整

**K1100g_d3 claim（原）**：
> Night session carries asymmetric predictive info for day variance
> (LRT χ²=14.6, QLIKE +3.78%); directionally real but borderline.

**K1100g_d4 修正 claim**：
> Under Student-t innovation, TAIFEX night→day predictive coefficient
> is directionally stable (4/5 years positive, 2017-2021) but marginal in
> magnitude; no single year achieves 1% IS LRT significance, and 2020
> alone shows elevated magnitude (|ξ_n|=0.14) consistent with COVID
> volatility regime—though still NS in-sample. K1100g_d3's full-sample
> OOS significance reflects cumulative statistical power (N=464) over
> a weak-but-stable annual signal, NOT a robust year-to-year structural
> mechanism. Paper 3 reframe should explicitly caveat this as a
> **low-frequency averaged effect** rather than a **per-period
> predictive structure**.

### 6.3 Verdict 對 Paper 3 的影響

- **Paper 3 reframe 不死但需降級 claim**
- 不能宣稱「TAIFEX night 對日盤有穩定 asymmetric predictive structure」
- 可以宣稱「經 Student-t 調整後有微弱但方向穩定的平均效應，累積樣本
  下統計顯著」
- 建議加入：(a) K1100g_d6 延伸到 2022-2025 看 signal 是否仍存在；
  (b) cross-market 複製（SPY overnight, N225 morning）看方向是否一致。

## 7. 教訓

1. **Full-sample OOS 顯著 ≠ 每年穩定**。N=464 的 LRT χ²=14.6 聽起來強，
   但每年單獨 N=230 時 χ² 全部 < 5。N 累積會放大弱 signal 到顯著門檻。
2. **COVID-regime hypothesis 不可光看 sub-period split**：K1100g_d3 的
   2020/2021 improv 比（4.74 vs 2.64%，1.8x）看似提示 COVID-driven，但
   本實驗 2020 單年 IS LRT 只 2.28 (NS)，更接近「2020 signal 較大但
   仍弱」而非「COVID 唯一驅動」。
3. **Annual stability 是比 sub-period split 更嚴格的 robustness test**：
   若每年單獨都過 1% threshold，才能宣稱穩定結構。

## 8. 衍生方向（沿用 K1100g_d3 列出）

1. **K1100g_d5（Asymmetric-t + TGARCH）**：處理 night skew=−1.6
2. **K1100g_d6（延伸 2022-2025）**：N 翻倍，看 Harvey t>3 threshold 是否仍失敗
3. **K1100g_d7（Cross-market 複製）**：SPY overnight、N225 morning-afternoon

## 9. 檔案

- `k1100g_d4.py` — annual fit + pseudo-OOS 腳本
- `k1100g_d4_results.json` — 完整結果
- `k1100g_d4_annual_lrt.png` — 5 年 IS LRT χ² bar chart
- `k1100g_d4_xn_and_oos.png` — 年度 xn coef + pseudo-OOS QLIKE improv
- `data/_cache_taifex_sessions_2017-2021.parquet` — 繼承自 K1100g_d3
- `run.log` — 執行 log

## 10. 參考文獻

- **Bollerslev (1987)** *REStat* 69(3) — Student-t GARCH
- **Engle & Rangel (2008)** *RFS* 21(3) — multiplicative tau·g PRG
- **Harvey, Leybourne & Newbold (1997)** *IJF* 13(2) — HLN DM correction
- **Harvey (2016)** *JF* — t>3 threshold
- **Kupiec (1995)** *JoD* 3(2) — UC VaR test（未納入，VaR 已在 d3 測過）
- **Patton (2011)** *JoE* 160(1) — QLIKE proxy-robust loss

## 11. Seed 與可重現性

- `np.random.seed(42)` + `np.random.default_rng(42)`
- `fit_prg_student()` 內部 `np.random.default_rng(42)` 建 restart 初值
- L-BFGS-B deterministic
- 重跑應得到完全相同 annual LRT 和 OOS 統計
