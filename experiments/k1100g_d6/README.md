# K1100g_d6 — 延伸 K1100g_d5 樣本 2017-2021 → 2017-2025（Harvey |t|>3 測試）

[提出: Claude 主線程 / 執行: Claude worktree agent-a71a442b]

## 1. 動機

K1100g_d3/d4/d5 在 N_OOS=464（2020-2021）下：
- M2_gap_total DM_t = +1.49（borderline）
- REF_night_r2 DM_t = +2.01（borderline）
- 兩者方向一致、但全部未過 Harvey (2016) |t|>3 門檻

**K1100g_d6 核心假說**：若 TAIFEX 夜盤→日盤 predictive signal 真實，DM_t 應隨 √N 線性放大。
- N=464 → t≈2.0 (K1100g_d5 baseline)
- N~1385 (2020-2025) → 預期 t≈3.47（應跨 Harvey threshold）
- 若真 scale，Paper 3 reframe anchor 建立；若不 scale 或 sign-flip，信號 regime-specific 非 robust。

## 2. 設計

### 2.1 資料源

TAIFEX TX tick 2017-2025 共 2192 個交易日，aligned rows=1992（K1100g_d5 為 1071）。
直接 reuse K1100g_d1 的 `build_sessions_cache` 邏輯，只將 date window 從 2017-2021 擴到 2017-2025。

快取檔案：`data/_cache_taifex_sessions_2017-2025.parquet`

### 2.2 規格（與 K1100g_d5 完全一致，僅換期間）

- PRG kernel：tau×g multiplicative, Student-t innovation
- Exog 定義：
  - M1_baseline：無 exog
  - M2_gap_night：gap_night[t]²（隔夜跳空 05:00→08:45）
  - M2_gap_day_lag：gap_day[t-1]²（前日 close→night-open 13:45→15:00）
  - M2_gap_total：gap_night[t]² + gap_day[t-1]²
  - M2_signed_gn：gap_night[t] signed（asym test）
  - REF_night_r2：r_night[t]²（K1100g_d3 M4 benchmark）
- Lookahead 防線：與 K1100g_d5 相同（所有 exog 在 t 日日盤開盤前已實現）
- Train：2017-2019（n=607，與 K1100g_d5 相同）
- Test：2020-2025（n_expand=1385）
- refit_every=5 expanding-window
- seed=42, L-BFGS-B deterministic

### 2.3 分段評估

- **Period A (2017-2021 replicate)**：2020-2021，n=464，應與 K1100g_d5 完全一致（replicate check）
- **Period B (2022-2025 extension)**：2022-2025，n=921，純新樣本測試
- **Period C (2017-2025 combined)**：2020-2025，n=1385，完整延伸

### 2.4 Verdict rules

| Verdict | 條件 |
|---------|------|
| PASS | max(\|M2_gap_total\|, \|REF_night_r2\|) 在 combined 期 > 3.0 |
| MARGINAL | max \|DM_t\| ∈ [2.0, 3.0) |
| FAIL | max \|DM_t\| < 2.0 但同向 |
| REGIME_REVERSAL | 任一 model DM sign flip vs K1100g_d5 且 \|t\|>1 |

## 3. 結果

### 3.1 Replicate check — Period A vs K1100g_d5

| Model | K1100g_d5 DM_t | K1100g_d6 Period A DM_t | abs diff |
|-------|-----------------|--------------------------|----------|
| M2_gap_total | +1.48988 | +1.48988 | **0.00000** |
| REF_night_r2 | +2.00958 | +2.00958 | **0.00000** |

**完全重現**。確認 specification 未漂移、擴大 sample 沒有污染 2017-2021 子期結果。

### 3.2 IS 全樣本 LRT（2017-2025, n=1992, Student-t）

| Model | chi² | p-value |
|-------|------|---------|
| M2_gap_night | **27.69** | 1.4e-07 |
| M2_gap_day_lag | 12.31 | 4.5e-04 |
| **M2_gap_total** | **31.85** | **1.7e-08** |
| M2_signed_gn | 17.33 | 3.1e-05 |
| **REF_night_r2** | **28.25** | **1.1e-07** |

**IS 端訊號極強**：全部 chi² > 12，M2_gap_total 達 31.85（比 K1100g_d5 的 18.87 明顯提升），看似信號 robust。

### 3.3 OOS 分段 DM-HLN（主要結果）

| Model | Period | n | DM_t | p | QLIKE improv | LRT chi² |
|-------|--------|---|------|---|--------------|---------|
| **M2_gap_total** | A (2020-2021) | 464 | **+1.49** | 0.136 | +6.62% | 14.37 |
| **M2_gap_total** | B (2022-2025) | 921 | **+0.48** | 0.629 | +1.18% | 1.01 |
| **M2_gap_total** | C (2020-2025) | 1385 | **+1.40** | 0.162 | +3.18% | 15.37 |
| **REF_night_r2** | A (2020-2021) | 464 | **+2.01** | 0.045 | +3.80% | 14.94 |
| **REF_night_r2** | B (2022-2025) | 921 | **+0.92** | 0.356 | +1.28% | 8.15 |
| **REF_night_r2** | C (2020-2025) | 1385 | **+1.99** | 0.047 | +2.21% | 23.08 |
| M2_gap_night | C | 1385 | +1.86 | 0.063 | +2.04% | 13.46 |
| M2_gap_day_lag | C | 1385 | +0.04 | 0.966 | +0.07% | 0.00 |
| M2_signed_gn | C | 1385 | +0.38 | 0.706 | +0.92% | 14.38 |

**關鍵觀察**：
- Period A 完美重現 K1100g_d5 → pipeline 正確
- Period B 信號**大幅崩塌**：DM_t 從 1.49/2.01 掉到 0.48/0.92，QLIKE improv 從 +6.6%/+3.8% 掉到 +1.2%/+1.3%
- Period C 的 DM_t 受 Period A 主導（Period B 幾乎零貢獻），並未隨 N 放大
- 方向仍為正（未 sign-flip），但 strength 未 scale

### 3.4 √N scaling check（核心判準）

| Model | t(d5, N=464) | t(d6, N=1385) | 預期 √N scaling | 實際-預期 | scaling ratio |
|-------|---------------|---------------|------------------|-----------|---------------|
| M2_gap_total | +1.49 | +1.40 | +2.57 | **−1.18** | 0.54 |
| REF_night_r2 | +2.01 | +1.99 | +3.47 | **−1.48** | 0.57 |

**兩個 model 都只達到預期 √N scaling 的 54-57%**。若信號為真 i.i.d. 特徵，實際 DM_t 應該接近預期值（± 1 內）。實際差距達 1.2-1.5 個 t-unit，統計上與「信號 regime-specific」一致。

### 3.5 Harvey (2016) Verdict → **FAIL**

判定邏輯：
- Harvey PASS：max |DM_t| > 3.0 → NOT met（max=1.99）
- MARGINAL：max ∈ [2.0, 3.0) → NOT met
- REGIME_REVERSAL：sign flip → NOT triggered (兩者仍 positive)
- **FAIL**：max |DM_t| < 2.0 同向 → **✓ 觸發**

### 3.6 Cross-model DM (combined, gap vs night_r²)

| 比較 | DM_qlike t | p |
|------|-----------|---|
| M2_gap_night vs REF_night_r2 | −0.10 | 0.92 |
| M2_gap_total vs REF_night_r2 | −0.95 | 0.34 |
| M2_gap_night vs M2_gap_total | +0.85 | 0.39 |

所有 cross-DM p > 0.3：gap² 與 night_r² 在 N=1385 仍統計上不可區分，與 K1100g_d5 結論一致（兩者同 signal class）。

### 3.7 Paper 3 reframe anchor status

**否，未建立**。

- Period A 的 borderline 結果並非在更大樣本中被放大，而是被稀釋
- IS 端 chi²=31.85 的強訊號 **未轉化** 為 OOS robust 預測力
- 典型 in-sample fitting but OOS-shaky 模式，K1100g 系列「TAIFEX 夜盤 → 日盤」命題**不具 Harvey 級 robustness**
- Paper 3 若要 reframe，需改用「directionally consistent but statistically fragile」級 claim，或轉向 K1100g_d7 跨市場複製（SPY/N225）尋找更強 anchor

## 4. 限制

1. **Regime shift**：2022-2025 覆蓋升息循環、AI bubble、geo 事件，結構可能不穩定。Period A 的 2020-2021 COVID shock 可能人為放大 DM_t。
2. **Expanding-window bias**：早期估計參數向後延伸，2022-2025 refits 仍吃到 2017-2019 規範，不反映 late-period 最佳 exog weighting。
3. **單市場**：TAIFEX 獨家結果，K1100g_d7 SPY overnight gap 跨市場複製仍 open。
4. **Symmetric Student-t**：gap_night skew≈−1.49，asymmetric-t (Hansen 1994) 仍可能救一些（建議 K1100g_d8）。
5. **Roll days**：與 K1100g_d5 相同，NaN r_combined 處理未區分滾月日的 variance 特殊性。

## 5. 對 K1100g 系列的意涵

### 5.1 完整時序圖景

| 實驗 | Innovation | N_OOS | M2_gap_total DM_t | REF_night_r2 DM_t | Verdict |
|------|-----------|-------|-------------------|-------------------|---------|
| K1100g_d2 | Normal | 464 | — | −0.21 | 完全 null |
| K1100g_d3 | Student-t | 464 | — | +1.92 | borderline |
| K1100g_d4 | Student-t (annual) | 464 | — | 0/5 年 IS PASS | 不穩 |
| K1100g_d5 | Student-t | 464 | +1.49 | +2.01 | borderline |
| **K1100g_d6** | Student-t | **1385** | **+1.40** | **+1.99** | **FAIL** |

樣本擴 3 倍，DM_t 幾乎沒動 → 不是 i.i.d. 信號，是 COVID-period-specific pattern。

### 5.2 修正後 Paper 3 narrative（建議）

> Under Student-t innovation, TAIFEX overnight-information encodings exhibit
> positive and directionally consistent predictive signs for next-day session
> variance, but OOS DM-HLN statistics fail to scale with sample size as
> expected under a homogeneous effect. Extending the test sample from
> N=464 (2020-2021) to N=1385 (2020-2025) leaves the DM_t essentially
> unchanged (+1.49→+1.40 for gap², +2.01→+1.99 for 5-min night-RV),
> falling well short of the √N-projected +2.57 and +3.47 respectively
> (Harvey 2016 threshold of 3.0). We therefore characterize this as a
> **period-dependent, statistically borderline predictability**, rather
> than a robust structural feature. The 2020-2021 COVID period appears
> to dominate the signal; 2022-2025 contributes near-zero incremental DM_t.

## 6. 衍生方向

1. **K1100g_d7**：SPY overnight gap² 跨市場複製（見 K1100g_d5 §7）
2. **K1100g_d8**：Winsorized gap²，測 COVID outlier 影響
3. **Regime-conditional PRG**：分 quiet / crisis regime fit，看 COVID 2020 是否單獨撐起全部信號
4. **Asymmetric-t PRG** (Hansen 1994)：處理 gap_night skew

## 7. 檔案

- `k1100g_d6.py` — Student-t PRG 完整 pipeline（reuse K1100g_d5 engine）
- `k1100g_d6_results.json` — IS/OOS/cross-DM/verdict/sqrtN scaling 完整結果
- `k1100g_d6_dm_t_vs_n_growth.png` — DM_t vs N 成長曲線（actual vs √N expected）
- `k1100g_d6_qlike_timeseries_by_period.png` — 60d rolling QLIKE improvement timeseries
- `data/_cache_taifex_sessions_2017-2025.parquet` — 2017-2025 session cache
- `data/_oos_runs_cache.npz` — OOS h_oos / df_log cache（重跑用）
- `run.log` — 執行 log

## 8. 參考文獻

- Bollerslev (1987) *RESTAT* 69(3) — Student-t GARCH
- Engle & Rangel (2008) *RFS* 21(3) — multiplicative τ×g PRG
- French & Roll (1986) *JFE* 17(1), 5-26 — non-trading-hours information
- Andersen, Bollerslev, Huang (2011) *JoE* 160(1) — overnight jump vs continuous
- Harvey, Leybourne & Newbold (1997) *IJF* 13(2) — HLN DM correction
- Harvey (2016) *JF* — |t|>3 threshold
- Hansen (1994) *IER* 35(3) — asymmetric-t

## 9. Seed 與可重現性

- `np.random.seed(42)`, `np.random.default_rng(42)`
- L-BFGS-B deterministic
- Period A 的 2017-2021 replicate 與 K1100g_d5 baseline **abs_diff = 0.00000**（4 dp 以上 identical），確認 pipeline 與 optimization 重現性完整
