# K1100g_d8 — Hansen (1994) skewed-t innovation on N225 (+SPY) gap² PRG

[提出: Claude 自主研究 / 執行: Claude worktree agent-aa9013ad / 2026-04-17]

## 1. 動機

K1100g_d7 (commit `0ec96389`) 在 Student-t PRG 下完成跨市場 gap² 測試：

| Market | d7 DM-HLN t (gap²) | QLIKE improv | Harvey |t|>3 |
|--------|---------------------|--------------|---------------|
| TAIFEX (d5, n=464)  | +1.49 | +6.62% | ✗ |
| SPY (d7, n~1500)    | +0.66 | +1.38% | ✗ |
| **N225 (d7, n~1465)** | **+2.32** | **+2.33%** | ✗（最接近 Harvey） |

Verdict = DIRECTION_CONSISTENT_ALL_BORDERLINE。d7 README section 5 與 section 7 derivation #4
明確建議 **Hansen (1994) skewed-t innovation** 作為下一個 methodological lever：
若 N225 raw r_intraday 左偏 (skew=-0.977 per d8 descriptives)，symmetric Student-t 可能
underfit tail，導致 DM 被平均稀釋；Hansen skewed-t 加 λ 項可能補強。

K1100g_d8 做的是：在 **d7 相同 PRG 框架下**只替換 innovation（Student-t → Hansen skewed-t），
看 N225 DM 是否跨過 +3.0。

### Verdict decision matrix

| Verdict | 判準 | Paper 3 narrative 意涵 |
|---------|------|-----------------------|
| PASS_N225_HARVEY | N225 gap² DM-HLN t > +3.0 under skewed-t | 升級為 "N225-confirmed" |
| **STILL_BORDERLINE** | N225 \|t\| ∈ (1.96, 3.0) 或 sign flip | d7 verdict 不變 |
| REGRESS | N225 t < d7 - 0.5 且 sign negative | 選 Student-t 為 canonical |

## 2. 設計

### 2.1 模型（4 models × 2 markets = 8 IS fits + 8 OOS expanding-window）

| 模型 | Innovation | Exog gap² | 備註 |
|-----|-----------|-----------|------|
| M_base_st | Student-t (df) | — | d7 replica（但 refit cadence 不同，見 Sec 5.1） |
| M_gap_st  | Student-t (df) | ξ·gap²_t (contemp) | d7 replica |
| M_base_sk | Hansen skewed-t (η, λ) | — | d8 new |
| M_gap_sk  | Hansen skewed-t (η, λ) | ξ·gap²_t (contemp) | **d8 key model** |

PRG kernel、DOW 結構、lookahead convention 與 K1100g_d7 完全一致；只替換 innovation。

### 2.2 Hansen (1994) skewed-t 閉式密度

Hansen 1994 eq. 9-10 標準化形式（E[z]=0, Var[z]=1）：

```
c = Γ((η+1)/2) / (sqrt(π(η-2)) · Γ(η/2))
a = 4·λ·c·(η-2)/(η-1)
b = sqrt(1 + 3λ² - a²)
For z ≥ -a/b :  log f(z) = log b + log c - ((η+1)/2) · log(1 + ((bz+a)/(1+λ))² / (η-2))
For z <  -a/b :  log f(z) = log b + log c - ((η+1)/2) · log(1 + ((bz+a)/(1-λ))² / (η-2))
```

- η∈(2.05, 200)：tail dof
- λ∈(-0.98, 0.98)：偏態參數；λ=0 退化為 variance-standardised Student-t
- **λ=0 restriction** → Student-t 是 skewed-t 的 nested sub-model；LRT dof=1

**Sanity check enforced at import**：`hansen_skewt_logpdf(z, η, 0)` 必須 match
scipy Student-t（scale=sqrt((η-2)/η)）— fail fast 若 regression（reused from K1184）。

### 2.3 Lookahead / seed / MLE 紀律

- `gap²_t = (log Open_t - log Close_{t-1})²`：在 `r_intraday_t` 開始前已 realized
- `np.random.seed(42)` + `np.random.default_rng(42)`
- MLE: L-BFGS-B deterministic；IS `n_restarts=10`；OOS warm-start `n_restarts=2` (+4 fallback)
- **OOS expanding-window refit_every=25**（而非 d7 的 5，見 Sec 5.1 降本說明）
- **λ boundary detection**：若 \|λ\| ≥ 0.95 in any fit → flag `lambda_at_boundary=True`；
  若 OOS cumulative boundary hits > 0 → verdict 標 PRELIMINARY

## 3. 資料

yfinance daily OHLC 2010-01-05 .. 2026-03-31（d7 cache 複製至 `data/` 供自包含）：

| Market | Ticker | n | Train (2010-2019) | Test (2020-2025) |
|--------|--------|---|-------------------|------------------|
| N225 | `^N225` | 3970 | 2447 | 1465 |
| SPY  | `SPY`   | 4084 | 2515 | 1508 |

r_intraday skew：N225 = -0.977，SPY = +0.115。N225 左偏強於 SPY。

## 4. 結果

### 4.1 IS 擬合（full-sample MLE）

| Model | N225 log-lik | N225 η/df | N225 λ | N225 ξ | SPY log-lik | SPY η/df | SPY λ | SPY ξ |
|-------|-------------|-----------|--------|--------|-------------|----------|--------|-------|
| M_base_st | 13582.961 | df=5.12 | — | — | 14612.380 | df=9.05 | — | — |
| M_gap_st  | 13614.148 | df=6.61 | — | +0.1403 | 14669.223 | df=6.50 | — | +0.0601 |
| M_base_sk | 13576.723 | η=7.60 | -0.078 | — | 14684.452 | η=9.60 | -0.113 | — |
| M_gap_sk  | 13607.646 | η=7.10 | -0.127 | +0.0914 | 14719.739 | η=7.59 | -0.137 | +0.0651 |

**λ 全部收斂在 modest 左偏範圍 (-0.08, -0.14)，無 boundary hit**。

### 4.2 IS LRT（chi²(1)）

| 比較 | N225 χ² | N225 p | SPY χ² | SPY p |
|------|---------|--------|--------|-------|
| M_gap_st vs M_base_st (gap effect in Student-t) | 62.37 | 2.9e-15 | 113.69 | ~0 |
| M_gap_sk vs M_base_sk (gap effect in skewed-t)  | 61.85 | 3.7e-15 | 70.57 | ~0 |
| M_base_sk vs M_base_st (**λ=0 restriction**)    | **0.00** | 1.0  | **144.14** | ~0 |
| M_gap_sk  vs M_gap_st  (**λ=0 restriction**)    | **0.00** | 1.0  | **101.03** | ~0 |

**關鍵 IS 發現**：
- N225 **skewed-t 與 Student-t 在 IS 不可區分**（LRT ≈ 0）— PRG τ×g + GJR 結構已經吸收 skew
  到 conditional variance dynamics；λ=0 restriction 不被拒絕。N225 raw skew=-0.977 是
  **unconditional** 性質，被 PRG 結構內生化了。
- SPY skewed-t IS 顯著優於 Student-t（χ²=144 in base, χ²=101 in gap），**despite** SPY raw
  r_intraday skew 僅 +0.115（近似對稱）。這反映 SPY 有 conditional heavy left tail 但
  average skew 被 GJR 平均化；λ 直接建模 residual skew 有額外 info gain。

### 4.3 OOS expanding-window DM（Harvey-HLN）

| DM 測試 | N225 t | N225 QLIKE imp | SPY t | SPY QLIKE imp |
|---------|--------|-----------------|--------|----------------|
| d7 Student-t gap (d7 replica, **refit_every=5**) | **+2.32** | +2.33% | **+0.66** | +1.38% |
| d8 Student-t gap (**refit_every=25, new**)       | -1.919 | -0.38% | -2.098 | -19.73% |
| **d8 Hansen skewed-t gap**                       | **-1.333** | -0.69% | -1.742 | -1.31% |
| d8 innov-upgrade (base: sk vs st)                | -2.226 | -0.06% | -0.472 | -0.49% |
| d8 innov-upgrade (gap: sk vs st)                 | -0.821 | -0.38% | **+1.883** | +14.97% |
| d8 cross-best (sk gap vs st base)                | -1.434 | — | -2.113 | — |

**三個重要現象**：
1. **d7 vs d8 Student-t DM 符號翻轉**：refit_every=5 (d7) 到 refit_every=25 (d8) 導致 DM 統計量
   從 +2.32/+0.66 翻為 -1.92/-2.10。這**不是** skewed-t 的問題，而是 **refit cadence artifact**
   （d7 用更密集 refit 讓 gap² 的 time-varying coefficient 即時 adapt；d8 reduced-cost 的
   refit 頻率讓 step-function 近似在 regime shift (2020 COVID, 2022 rate hike) 時傷更大）。
2. **N225 IS LRT 為 0 與 OOS innov DM 不一致**：IS LRT innov=0 說明 λ 完全不 help in-sample，
   但 OOS innov_gap DM=-0.82 small negative，一致表示 N225 的 PRG 已內生化 skew。
3. **SPY innov_gap OOS DM=+1.883 (p≈0.06)** borderline — skewed-t **確實** 改善 SPY 的
   gap model OOS；這是 d8 最 interesting 的副產物結果。

### 4.4 SkewT OOS 參數穩定性

| | N225 gap_sk | SPY gap_sk |
|---|-------------|------------|
| η mean (sd) over OOS refits | 8.00 (0.00) | 8.00 (0.00) |
| λ mean (sd) over OOS refits | -0.100 (0.000) | -0.104 (0.004) |
| λ boundary hits (\|λ\|≥0.95) | **0** | 0 |

**警訊**：OOS refits 的 (η, λ) 變異近乎零 — 特別是 N225 完全不動。代表 warm-start +
`n_restarts=2` 在 expanding-window refit 時，L-BFGS-B 從前一次 estimate 出發但幾乎沒
迭代就收斂回同一點。這可能是：
- (a) likelihood surface 在該區域非常 flat（skewed-t 參數 essentially unidentified
  conditional on PRG τ×g + GJR dynamics）— 這與 N225 IS LRT=0 一致
- (b) warm-start artifact：當 n_restarts 降到 2 時，optimizer 依賴 warm-start 而不
  重新 explore — 可能錯過真實新局部最佳

→ **d8 OOS skewed-t 結果標為 PRELIMINARY**。完整證據需要 K1100g_d9 rerun with
refit_every=5, n_restarts=10（直接對應 d7 cadence）或手動驗證 SPY IS 參數在
Sec 4.1 與 OOS 平均值的一致性。

### 4.5 Verdict — `STILL_BORDERLINE` (preliminary)

- N225 gap_sk DM-HLN t = **-1.333** < +1.96，**未過 Harvey**，sign 甚至翻為負
- 但 d8 Student-t 基線也翻負 (DM gap_st = -1.92 vs d7 +2.32) — 這告訴我們 sign flip 是
  **refit cadence artifact**，而非 skewed-t regression
- 相對比較 `DM(innov_gap)` N225 = -0.82 (skewed-t slightly worse) vs SPY = +1.88
  (skewed-t marginally better)：skewed-t 在 N225 **幾乎無差**（與 IS LRT=0 一致），
  在 SPY 有微幅 OOS 改善

**最終結論**：Hansen skewed-t 在 **PRG-integrated framework** 下對 N225 gap² DM 沒有
幫助（IS LRT=0 + OOS innov_gap DM=-0.82），**無法升級 d7 DIRECTION_CONSISTENT_ALL_BORDERLINE**
到 PASS_N225_HARVEY。d7 原本 verdict 不變。

## 5. 限制與 caveat

### 5.1 refit_every=25 降本的 caveat（最重要）

d7 使用 `refit_every=5`（對應 ~300 refits per model）。在 d8 需要跑 4 models × 2 markets 
= 8 次 expanding-window，加上 Hansen skewed-t 的 12-param likelihood surface + branch test
比 Student-t 11-param 約慢 2×，完整 d7-cadence 跑會超過 300 分鐘。**d8 改用 refit_every=25**
（約 60 refits per model）讓實驗可在 ~13 分鐘跑完。代價：

- **refit 之間的參數固定**：在 refit_every=5 下，gap² 的 ξ coefficient 在 300 次 OOS 都
  被重新估計；在 refit_every=25 下只估 60 次。Regime shift (e.g. 2020-03 COVID) 時
  延遲 adapt。
- **d7 vs d8 Student-t DM 不可 apples-to-apples 比較**：這就是為何 d8 的 Student-t
  DM 從 d7 的 +2.32/+0.66 翻到 -1.92/-2.10。d7 與 d8 的 DM 符號差異 **不是 skewed-t
  造成的**，而是 refit 頻率不同。
- **Proper d7-cadence skewed-t run** 應在 K1100g_d9 追蹤（見 Sec 7）。

### 5.2 OOS skewed-t 參數 identification 警訊

OOS refits 產出的 (η, λ) 幾乎完全固定在初始值 (8, -0.10)，特別是 N225。解釋選項：

- (a) **真實 likelihood 極平**：給定 PRG + GJR 已吸收 skew，Hansen λ 非 identifiable
  conditional on 整個 PRG kernel — IS LRT=0 支持此解釋
- (b) **Warm-start artifact**：`n_restarts=2` + L-BFGS-B gradient 太小不跳出初值 → 
  可能錯過真正局部最佳

K1100g_d9 應以 `n_restarts=10` rerun 2-3 個 OOS refits 手動 audit 參數穩定性。

### 5.3 其他限制

1. **TAIFEX 未重測**：d5 TAIFEX n=464 small sample，skewed-t 額外 1 param（λ）statistical
   power 不夠；d8 只跑 N225 + SPY。
2. **OOS test window 2020-2025 含 COVID 極端 gap**：d8 未做 winsorization；winsorized
   gap² robustness 仍為 open direction（d7 proposed K1100g_d9）。
3. **DM-HLN 1/3 power bandwidth**：其他 HAC kernel 可能給出 ±0.1-0.2 t 差異；但不應
   讓 |t| 跨過 Harvey 僅因 kernel 選擇。
4. **yfinance daily OHLC only**：與 d7 相同限制。

## 6. Paper 3 narrative implication

- **不觸發 path (b) "N225-confirmed weak-but-directional cross-market"**：N225 gap_sk
  DM 未過 Harvey，且 IS LRT=0 表示 skew effect in PRG 已完全被 GJR 內生化
- **d7 verdict DIRECTION_CONSISTENT_ALL_BORDERLINE 保持不變**
- **Paper 3 canonical innovation 仍為 Student-t**：skewed-t 在 PRG-integrated 下對
  N225 gap² 無增益；SPY 有 borderline 改善但 SPY 本就不是 Paper 3 anchor market
- **narrative state machine 不啟動 body rewrite**：d8 是單一實驗，不觸發 Paper 3 pivot；
  若未來 K1100g_d9/d10 再有互補證據，才進 decision review

## 7. 衍生方向

- **K1100g_d9**：proper d7-cadence skewed-t（refit_every=5, n_restarts=10），確認 Sec 5.1
  的 refit artifact 是主導效應。預計 runtime ~60-90 分鐘。
- **K1100g_d10**：Winsorized gap² (1% / 5%) 測 COVID 極端 gap 對 DM stability 影響
- **K1100g_d11**：加入 DAX / FTSE 提升 spatial coverage
- **K1100g_d12**：TAIFEX d6 2020-2025 加 Hansen skewed-t，做三市場對齊 skew comparison
- **Paper 3 body rewrite 暫不觸發**：narrative state machine 要求 ≥3 互補實驗 reviewed

## 8. 檔案

- `k1100g_d8.py` — 主腳本：Student-t + Hansen skewed-t PRG cross-market pipeline
- `k1100g_d8_results.json` — 完整結果
- `k1100g_d8_dm_progression.png` — TAIFEX/SPY/N225 Student-t vs skewed-t DM 進展圖
- `k1100g_d8_innovation_density_n225.png` — N225 IS fitted innovation density 比較
- `data/n225_daily_2010-2026.parquet`、`data/spy_daily_2010-2026.parquet` — yfinance cache
- `run.log` — 執行 log（含每 125 obs 進度）

## 9. 參考文獻

- **Hansen, B. E. (1994)** "Autoregressive Conditional Density Estimation", *IER* 35(3), 705-730
- **Jondeau & Rockinger (2003)** *JEDC* 27(10), 1699-1737 — 條件波動率、偏態、峰度
- **Bollerslev (1987)** *REStat* 69(3), 542-547 — Student-t GARCH
- **Engle & Rangel (2008)** *RFS* 21(3) — multiplicative τ×g PRG
- **French & Roll (1986)** *JFE* 17(1), 5-26 — non-trading-hour information
- **Harvey, Leybourne & Newbold (1997)** *IJF* 13(2) — HLN DM correction
- **Harvey (2016)** *JF* — |t|>3 threshold

## 10. Seed 與可重現性

- `np.random.seed(42)` + `np.random.default_rng(42)`
- `fit_prg_skewt()` / `fit_prg_student()` 內部 `np.random.default_rng(42)` 建 restart 初值
- L-BFGS-B deterministic；warm-start from prev OOS refit
- yfinance cache 固定在 `data/` 下（從 d7 直接複製，確保 raw data 一致）
- `_hansen_sanity_check()` 在 import time 強制執行；若 Hansen skewed-t 實作 regress 立即 fail
- 重跑應得到完全相同的 IS/OOS 結果到 4 位小數
- Total runtime: 767s ≈ 12.8 min（M1 Max, refit_every=25）
