# Paper 6 K880 vs K880v2 — Errata Decision Memo

**Date**: 2026-05-31 (Taiwan time)
**Owner**: 主線程 hourly-16
**Task**: `Paper6_major_errata_K880v2_canonical` (paper_review, P4)

## Verdict: **NO ERRATA REQUIRED**

Paper Table 2 SPY DM=6.00 + Table 4 SPY VR=0.93% 數字皆 reproducible，
K880 timing convention 在 paper Eq 3-4 information set 定義下 admissible。
Task description 將此 framing 為「artifact / errata」是 **過時前提**。

## 證據

### 1. K880 vs K880v2 數字（皆已 verify）

| Comparison | K880 t-stat | K880v2 t-stat | n | Paper Used |
|------------|------------:|--------------:|--:|------------|
| GJR vs PRG_Extended | **+6.00** PASS | −0.57 NS | 1,823 | K880 (Table 2 L196) |
| PRG_Extended VaR_1% | VR=0.93% / Kupiec p=0.77 | VR=1.59% / p=0.0196 | 1,823 | K880 (Table 4 L260) |
| GJR_vs_PRG_Basic | +6.34 | −0.98 | 1,823 | K880 |

Sources：
- `experiments/k880/k880_results.json::layer5_dm_tests` + `layer4_var`
- `experiments/k880v2/k880v2_results.json::layer5_dm_tests` + `layer4_var`

### 2. K880 timing 在 paper 模型定義下 admissible

Paper Eq 3-4 (Section 2 methodology) 將 forecast horizon 定義為
**"at market open for the intraday period only"**，
此時點 overnight realized variance $r^2_{\text{overnight},t}$ 已 fully observed 屬 information set $\mathcal{F}_{t}^{\text{open}}$。
K880 line 512 `r2_overnight[t]` 不是 lookahead — 是 session-boundary 時點對 already-realized overnight 的合法 condition。

對比 K880v2 採用 "at t−1 close for full day t" convention，
此情境下 overnight 尚未 realized → 必須用 forecast $h_{\text{overnight},t}$ — 此即 K880v2 line 中的 `h_overnight_t` 變動。
K880v2 不是「修正版」，是**另一 forecast horizon convention**。

User memory `feedback_session_boundary_forecast_timing` 已正式確認此判定原則：
> "Session-boundary model 在 open 用已 realized overnight = legitimate timing (Paper 6 K880 判定原則)"

### 3. Paper 已內建 disclosure（VaR 段）

`main.tex` L245 footnote 已明確：
> "The SPY VaR row uses the **canonical K880 timing convention**, not K880v2.
>  K880 conditions the intraday variance on the same-day overnight realized
>  variance, which is **admissible under the paper's information-set
>  definition in Eqs.~(3)--(4)**: the forecast target is the intraday period
>  formed at market open, when the overnight return is already observed."

此 footnote 是 2026-05-29 audit (`spy_var_source_audit_2026_05_29.md`) 的直接 actioned outcome。

### 4. K880 vs K880v2 已 documented 在 experiments.md

`experiments.md` L73 已正式區分 timing convention：
- "at t−1 close for full day t" → K880v2 correct
- "at market open for the intraday period only" → K880 valid

## 還剩什麼 gap（reviewer-facing 改進，非 errata）

### Gap 1：Table 2 (main DM results, L196) 缺對應 footnote

VaR 段 (L245) 已有完整 K880/K880v2 disclosure footnote。
但 **Table 2 SPY 行 DM=6.00 (L196) 沒有平行 footnote**。
Reviewer 讀到 main result DM=6.00 不知道：
1. 此數字對應 K880 timing convention
2. K880v2 convention 下 DM=−0.57 NS
3. paper Eq 3-4 為何 justify K880 選擇

**Recommendation**: 在 Table 2 SPY 行（或 Table 2 footnote）加 cross-ref：
> "SPY DM statistics use the canonical K880 timing convention
>  (forecast at market open with realized overnight); see footnote on
>  Table~\ref{tab:var_es} for the timing-convention disclosure."

### Gap 2：Abstract 不需改

Abstract L41 主 DM 數字 (SPY 6.00) 與 paper Eq 3-4 self-consistent。
不需提 K880v2 — Abstract 應呈現 paper 自身 convention 下的結果。

### Gap 3：Ablation Table 3 (L221) 數字確認

Table 3 ablation 「DM $t = 6.00 \to -0.57$」其實是 K880 → K880v2 比較
（不是真 ablation removing session-boundary update），標籤 misleading。
**Recommendation**：rename Table 3 為「Alternative timing convention comparison」
而非「Ablation removing session-boundary update」 — 兩者語意不同。
Ablation 應指 within-K880 移除 session bridge；K880v2 是 different convention。

但此 framing 是 reviewer-level critique，影響 narrative 清晰度，**非 errata**。
**Defensible 但建議微調 (P5 priority, post-this-decision)**。

## 對 FRL 投稿的影響

- **數字 reproducibility**：✅ Table 2 + Table 4 SPY 行 100% reproducible from K880
- **Lookahead 指控**：❌ 不成立 — K880 timing 在 paper own Eq 3-4 定義下合法
- **K880v2 obligation**：optional supplementary — 可放 online appendix 作 robustness，
  不需放 main paper
- **Reviewer R1 風險**：Table 2 缺 footnote 可能被點名「why DM=6.00 not robust to
  alternative timing」 → 平行 footnote 補上即解

## 建議的 followup tasks（非 blocking 本決策）

1. **`Paper6_table2_timing_footnote`** (P5, paper_body)：main.tex Table 2 SPY 行加
   timing-convention cross-ref footnote
2. **`Paper6_table3_relabel`** (P6, paper_body)：rename Table 3 「ablation」→
   「alternative timing convention」 + 補 within-K880 真 ablation（如有時間）
3. **`Paper6_online_appendix_k880v2`** (P6, paper_body)：online appendix 加
   K880v2 robustness table 作完整 disclosure

## Task 結案

`Paper6_major_errata_K880v2_canonical` → **succeeded, NO REWRITE**.

主要 deliverable = 本 memo + 確認 paper 數字 provenance clean +
identify 3 個 reviewer-facing 強化 followup（非 errata, P5-P6）。

## References

- `paper/prg-periodic-garch/main.tex` L41 (Abstract), L196 (Table 2), L221 (Table 3), L245 (Table 4 + footnote)
- `paper/prg-periodic-garch/experiments.md` L73 (timing convention 區分)
- `paper/prg-periodic-garch/research_notes/spy_var_source_audit_2026_05_29.md`
- `experiments/k880/k880_results.json`, `experiments/k880v2/k880v2_results.json`
- User memory: `feedback_session_boundary_forecast_timing`
- Eq 3-4 in main.tex methodology section (forecast at market open convention)
