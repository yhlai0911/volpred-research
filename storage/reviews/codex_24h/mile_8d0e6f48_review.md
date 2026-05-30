# Codex 24h Review — mile_8d0e6f48 (K1108f)

- **Article**: 把樣本拆成「景氣循環的上升期 vs 下降期」再測一次，晶圓代工財報日的謎還是沒解開
- **Draft**: [storage/drafts/k1108f_general_draft.md](/Users/yhlai0911/Desktop/volpred-research/storage/drafts/k1108f_general_draft.md:1)
- **Task**: `paper_review_mile_8d0e6f48`
- **Reviewed**: 2026-05-31 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **CONDITIONAL_PASS**

## 結論摘要

核心 null claim 安全：`K1108f` 的主結論「景氣上升/下降分組沒有救回 capex 訊號」與 `experiments/k1108f/k1108f_results.json`、[experiments/k1108f/k1108f.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1108f/k1108f.py:390) 一致，lookahead guard 也明確存在。

但草稿仍有 3 類需要修正的文字層問題，否則 provenance 會不乾淨：

1. 文末方法腳註把 bootstrap 類型與樣本期間寫錯。
2. 文中把 Spec 2 的互動項講成「當季營收年增率」，但實作其實是「事件日前最近一次已公布的 TSMC 營收 YoY」。
3. 後續研究方向段落把已完成的 D3（K1108e）寫成「還沒做」。

## Numeric verification

下列文中數字已對上 `experiments/k1108f/k1108f_results.json`：

| Draft line | Claim | results.json | Match |
|---|---|---|---|
| 31 | 上升期 54、下降期 32、主要回歸 86 | `regime_counts.UP=54`, `regime_counts.DOWN=32`, `spec1_regime_dummy.n=86` | ✓ |
| 35 | β_up = -0.0000176 | `spec1_regime_dummy.beta_up=-1.7623695e-05` | ✓ |
| 35 | β_down = -0.0000117 | `spec1_regime_dummy.beta_down=-1.1724632e-05` | ✓ |
| 36 | t 值 -0.60 / -0.86 | `t_hac_up=-0.5987`, `t_hac_down=-0.8628` | ✓ |
| 39 | Wald p 值 0.85 | `wald_p_chi2=0.8491214` | ✓ |
| 49 | bootstrap 1000 次 | `block_bootstrap_spec1.n_reps=1000` | ✓ |
| 55 | 互動項不顯著 | `spec2_continuous_yoy.t_hac_b2=-0.8767`, CI 跨 0 | ✓ |
| 65 | 前序 K1108 / b / c 都是零結果鏈 | `comparison_stack` + parent experiment JSON | ✓ |

## Findings

1. **Method/provenance mismatch** — [storage/drafts/k1108f_general_draft.md](/Users/yhlai0911/Desktop/volpred-research/storage/drafts/k1108f_general_draft.md:83)
文末寫的是 `Politis-Romano (1994) stationary bootstrap`，但實作是固定區塊的 within-firm moving block bootstrap：見 [experiments/k1108f/k1108f.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1108f/k1108f.py:297) 與 `k1108f_results.json.block_bootstrap_spec1.block_size=10`。同一行也把資料期間寫成 `2014-2026`，但實際事件池上限是 `2025-11-17`；主分析樣本是 `2020-04-28` 到 `2025-11-17` 的 86 場事件。這不改會讓方法來源與樣本期間對不上。

2. **Spec 2 敘述不精確** — [storage/drafts/k1108f_general_draft.md](/Users/yhlai0911/Desktop/volpred-research/storage/drafts/k1108f_general_draft.md:55)
草稿寫「景氣 × 台積電當季營收年增率」，但程式實際是 `guide_delta_pct × tsmc_rev_yoy_lag`，採嚴格 PIT：事件日只吃「先前已公布、且 `reporting_date < event_date`」的最近一筆 YoY，見 [experiments/k1108f/k1108f.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1108f/k1108f.py:197) 與 [experiments/k1108f/k1108f.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1108f/k1108f.py:420)。如果寫成「當季」，讀者會以為用了同期資訊。

3. **Future-work state stale** — [storage/drafts/k1108f_general_draft.md](/Users/yhlai0911/Desktop/volpred-research/storage/drafts/k1108f_general_draft.md:73)
這段把「固定成本結構假說」寫成 `K1108b/c README 裡列出來、但還沒做的其他候選機制`，但 D3 的 K1108e 已在 `2026-04-17T16:36:51+00:00` 完成，早於 K1108f；見 `experiments/k1108e/k1108e_results.json.timestamp`。這不是核心結論錯誤，但會讓文章對 research stack 的狀態描述失真。

4. **結論語氣略超前於證據邊界** — [storage/drafts/k1108f_general_draft.md](/Users/yhlai0911/Desktop/volpred-research/storage/drafts/k1108f_general_draft.md:63)
「你才有資格說『這條路真的沒有』」寫得太滿。K1108f 自己在限制段又承認樣本 86 場、regime 邊界是研究者先驗切法，較嚴謹的表述應是「目前看不到可重複的證據」或「這條路暫時沒有被資料支持」，避免把 null evidence 寫成最終性否證。

## Lookahead audit

- PASS — regime 邊界是 script 頂端預先寫死，非 data-adaptive：[experiments/k1108f/k1108f.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1108f/k1108f.py:119)
- PASS — Spec 2 的 TSMC YoY 採 `reporting_date < event_date` 嚴格 PIT merge：[experiments/k1108f/k1108f.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1108f/k1108f.py:210)
- PASS — `theta_eav_empirical` 直接重用 K1108c pool，沒有重估或偷改 dependent variable：[experiments/k1108f/k1108f.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1108f/k1108f.py:349)

## AI 味 / 翻譯腔

整體不重，但有 1 處明顯研究腔混英文，建議順手修掉：

- [storage/drafts/k1108f_general_draft.md](/Users/yhlai0911/Desktop/volpred-research/storage/drafts/k1108f_general_draft.md:79) `robust 的「沒有」訊號本身就是一個結果。`

## 建議修法

1. 文末腳註改成「within-firm moving block bootstrap（block=10, 1000 reps）」並把日期改成實際事件上限 `2025-11-17`。
2. line 55 改成「景氣 × 事件日前最近一次已公布的台積電營收年增率」。
3. line 73 改寫研究方向，拿掉已完成的 K1108e，改列真正未完成的候選機制。
4. 把 line 63 的「真的沒有」降一級，避免 null-result overclaim。
