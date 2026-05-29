# Paper 1 GLD Rolling γ Forensic — `-0.067` Source Untraceable

**Task**: `Paper1_GLD_gamma_negative_0.067_forensic` (P4 paper_review, claimed by hourly-00 2026-05-30)
**Date**: 2026-05-30 (台灣時間)
**Status**: ERRATA PATH (c) recommended — Table 2 GLD row + body Section 5 narrative require major revision

## 1. 起因

Task description 假設 Paper Table 2 GLD γ=−0.067 (93% negative, HAC t=−5.79) 來自 **K799** original experiment，要求查 K799 spec (sample filter / weighting / HAC lags / truncated early data) 以找出 K903 +0.002 與 paper −0.067 的 spec 差異。

## 2. 實際 source provenance

- **K799** (`experiments/k799/k799_grand_evaluation.py`): **SPY-only** grand evaluation（OOS 2023--2024, refit 63d, 2006-01 to 2025-12）。**沒有 GLD rolling gamma section**。Task description 前提錯誤。
- **K902** (`experiments/k902/k902_paper1_tables_supplement_results.json`): 只有 `table1_descriptive_stats` 與 `table3_cross_asset_qlike`，**無 rolling_gamma 區段**。
- **K903** (`experiments/k903/k903_results.json`): canonical 2010-start replication，**唯一**有 Paper Table 2 對應的 7-asset rolling γ 數據。

結論：Paper Table 2 GLD γ=−0.067 在當前 experiment ledger 中**無可 reproduce 之 source experiment**。

## 3. K903 canonical spec vs Paper Table 2 narrative

K903 用 paper 自己宣稱的 spec（`experiments/k903/k903.py` L70-87）：
- `TABLE2_START = '2010-01-01'`
- `ROLLING_GAMMA_WINDOW = 504`
- `ROLLING_GAMMA_STEP = 63`
- HAC lags = 8（per `experiments/k903/k903_vs_paper_diff.md` L7）
- Data range: 2010-01-04 to 2026-04-16, n_obs = 4096

K903 rolling γ vs paper Table 2:

| Asset | Paper Table 2 mean γ | K903 mean γ | Paper % neg | K903 % neg | Paper HAC t | K903 HAC t | n_windows |
|-------|----------------------|-------------|-------------|------------|-------------|------------|-----------|
| SPY | +0.211 | +0.132 | 0% | 0% | +8.30 | +11.08 | 58 |
| QQQ | +0.110 | +0.116 | 12% | 0% | +3.21 | +10.76 | 58 |
| EEM | +0.180 | +0.087 | 8% | 2% | +4.12 | +11.88 | 58 |
| **GLD** | **−0.067** | **+0.002** | **93%** | **67%** | **−5.79** | **+0.15** | 58 |
| TLT | −0.008 | −0.005 | 52% | 69% | −0.34 | −0.46 | 58 |
| BTC-USD | +0.117 | +0.072 | 28% | 25% | +1.83 | +2.88 | 60 |
| SLV | −0.041 | −0.009 | 72% | 71% | −2.91 | −0.68 | 58 |

GLD 是唯一**符號翻轉 + HAC t 落差 5.94**的 row。其他 6 assets 同 spec 下方向一致（magnitude 差但 sign preserved）。

## 4. Paper body footnote 錯誤辨識

`paper/leverage-direction/body.tex` L170 footnote 寫：

> A v3 reproducibility audit (K903) of the **full-sample GJR-GARCH estimate** on GLD returns the near-zero value γ̂ = +0.002 rather than the rolling-window mean of −0.067. The two numbers measure different objects: the −0.067 figure is the mean of quarterly rolling γ estimates (504-day window, 2010--2026), while **K903 reports the single full-sample point estimate**, which averages opposing regimes...

**此 footnote 對 K903 的描述錯誤**。事實：
- K903 *也是* rolling 504/63 (見 `k903.py` L86-87)
- K903 `n_windows = 58` quarterly windows on 2010-01 to 2026-04 (per `k903_results.json::table2_rolling_gamma.GLD.n_windows`)
- K903 +0.002 是 **58 個 rolling γ 的 mean**，不是 single full-sample point estimate

Footnote 試圖以「不同 estimator 維度」化解衝突，但兩個數字是**同維度同 spec 的可比較數**。

## 5. 結論

- Paper Table 2 GLD row (`mean γ = −0.067, 93% neg, HAC t = −5.79`) 數字**無 source experiment 可追**；現有 canonical replication (K903) 得 `+0.002 / 67% neg / +0.15`。
- 6 個其他 assets 同 spec 下方向一致 → 排除「整列 sample period 不同」可能（否則 SPY/QQQ/EEM HAC t 也會偏差更多）。
- Paper body L170 footnote 對 K903 的描述為事實錯誤（K903 是 rolling estimator 不是 full-sample single estimate）。
- 由 K903 67% negative 仍佔多數可知 GLD γ 確有 negative bias，但量級接近 0 (mean +0.002, HAC t = +0.15 NS) → **paper 原始「inverted leverage 統計顯著」claim 不成立**。

## 6. Errata path (recommended)

**Path (c) — major errata**:

1. **Table 2 GLD row** 改寫成 K903 canonical: mean γ = +0.002, std = 0.055, % neg = 67%, HAC t = +0.15 (n=58)
2. **Body L170-172** GLD inverted leverage 段大幅降溫:
   - 刪除 `HAC t = −5.79, p < 0.001` 此 unsupported claim
   - 改為 "GLD's rolling γ estimates straddle zero (mean +0.002, 67% of quarterly windows negative, HAC t = +0.15 non-significant). Unlike SPY/QQQ/EEM which exhibit uniformly positive γ, GLD's mixed-sign behavior is consistent with regime-dependent leverage."
3. **Body L170 footnote** 刪除或重寫，承認 K903 是 paper canonical spec 的 rolling replication，paper 原始 −0.067 origin untraceable
4. **Body L181** "γ < 0 for GLD" claim 改為 "γ ≈ 0 for GLD"
5. **Body L182** skewness-based selection example 重寫（GLD γ ≈ 0 而非 < 0，仍可作 |γ| < 0.10 → 不需 GJR 的例子，但 narrative 不可宣稱 negative leverage 統計顯著）
6. **Body L196-198** 2025--2026 GLD γ=−0.089 / 100% negative claim 需要獨立 K-experiment verify（建議建立 follow-up task 跑 K903-extension 限定 2025-01 to 2026-04 window）

## 7. 對 paper 整體 thesis 的影響

- **Leverage direction taxonomy** 核心論點（risk assets γ > 0, safe-haven γ < 0, rates γ ≈ 0）需修整：GLD 落在 "γ ≈ 0" 而非 "γ < 0" — TLT 與 GLD 兩者同屬 γ ≈ 0
- **|γ| > 0.10 rule** 仍站得住（SPY +0.132, QQQ +0.116 在 K903 都 > 0.10；GLD/TLT/SLV 都 < 0.10，DM tests 確認 GJR 對這三者 not significant）
- **"Gold's inverted leverage is statistically significant" headline claim** 不成立 — 主結論需要降溫成"gold's γ is near zero, statistically indistinguishable from no-asymmetry"

## 8. 後續 task 建議

1. 建 follow-up task `Paper1_body_GLD_section_rewrite` (P3) — main thread 寫作，依本 report 改 Table 2 + Section 5 narrative
2. 建 follow-up task `K903_extension_GLD_2025_2026_subwindow` (P4) — 驗證 paper L196-198 "γ=−0.089 in 2025-2026" claim
3. `Paper1_GLD_gamma_negative_0.067_forensic` 本 task 標 succeeded，path (c) errata 確認需要寫作

---
*Forensic by hourly-00 dispatch session 750dd610a922; paper canonical source check fully traced; recommendation aligned with research integrity principle (rigorous reproduction takes priority over preserving headline claims).*
