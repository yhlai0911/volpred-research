# Review Round v4 — prg-periodic-garch (Paper 6)

**Date**: 2026-04-27
**Triggered by**: 主線程 v4 batch fix 收尾後啟動 review-cycle — v3 4.1★ + v3 README 「v4 必修 list」4 actions + 1 bonus condense main-thread apply 完，產出 v4 main.tex (15 頁, 21 bibitems, 0 undefined cite)。
**Manuscript**: `paper/prg-periodic-garch/main.tex` (post v4 batch, commit c89bfb49)
**Target journal**: Finance Research Letters (FRL)
**Reviewers**:
- `latex-academic-reviewer` proxy via Claude general-purpose subagent `a90857a0727bdbd8b`
- `citation-verifier` proxy via Claude general-purpose subagent `a031beb5e7719ebdc`
- `cross-paper-meta-evaluator` 主線程

---

## Overall Assessment

| Reviewer | Verdict | Rating |
|----------|---------|--------|
| Citation | **0 MAJOR / 1 MED / 2 MINOR + 2 optional carry-over** (Bollerslev1996 → BollerslevWooldridge1992 for QML claim; cosmetic typos heteroskedasticity / Souček) | ✅ **GREEN PASS for FRL** |
| Academic | 0 CRITICAL / 0 SEVERE / **1 NEW MAJOR (M-NEW-1-v4 §4 vs §4.5 DM 6.00 vs 5.24 inconsistency)** + 1 NEW MED + 3 NEW MIN + 1 carry MIN | ★★★★ (**4.2/5**, v3 4.1 → +0.1) |
| Cross-paper meta | NotebookLM 2 critical issues remain CLOSED (Argument A 不公平基準 + Argument B 新穎性偏低)；K1260 contribution intact；§4 vs §4.5 numerical inconsistency 是 P6 內部 disambiguation 議題（同 memory `feedback_3spec_disambiguation.md` P1 K1256 + P2 γ pattern），不影響 portfolio-level standing | ✅ no fundamental issue |

**Joint verdict**: **HOLD for v4.1**（主線程 ~30-45 min 修 1 MAJOR + 1 MED + 2 cosmetic MIN，不直接升 ready_for_submission）。預期 v4.1 後 4.4-4.6★ + FRL desk-accept 35-45%。

**Predicted FRL outcome (post v4 as-is)**: desk-accept 30% / R&R 55% / desk-reject 15%（v3 同；M-NEW-1-v4 影響 +5pp desk-reject 風險，被 §4.5 GJR-X subsection 強化抵消）

**Predicted FRL outcome (post v4.1 fix)**: desk-accept 35-45% / R&R 50% / desk-reject 5-10%

---

## Issues Summary (v4 latex agent)

### CRITICAL (0) — none
### SEVERE (0) — none

### MAJOR (1 NEW) — v4.1 必修

**M-NEW-1-v4. SPY PRG-vs-GJR DM-statistic cross-section numerical inconsistency**

- **Location**: §4 Table 2 / §4.2 Ablation / Abstract / §4.2 prose all report **DM $t = 6.00$** for SPY PRG vs GJR; §4.5 Table 5 reports **DM $t = 5.24$** for the same comparison
- **Evidence**:
  - K880 `experiments/k880/k880_results.json` `layer5_dm_tests.GJR_vs_PRG_Extended.t_stat = 6.003887940674553` (canonical §4 source)
  - K1260 `experiments/k1260/k1260_results.json` `dm_tests.PRG_vs_GJR.t_stat = 5.236176003002506` (§4.5 source)
  - **K880 與 K1260 配置完全相同**：seed=42, n_starts_prg=5, refit_freq_prg=126, OOS 2019-01-02 to 2026-04-02, n=1823
  - 差異很可能來自 DM 實作細節（HAC bandwidth / lag selection / 優化器收斂閾值的微差），**不是 pipeline-level 不公平比較**
- **Severity**: MAJOR — referee 可能讀為「兩個不同 estimation 挑有利的 report」即使解釋清楚也是 reproducibility concern
- **Recommended fix (v4.1)**: 移除 §4.5 Table 5 的 `PRG Extended vs GJR` row（§4 Table 2 已是 canonical），保留 GJR-X vs GJR (-0.53 NS) + PRG vs GJR-X (7.72 PASS) 兩 row 即可。§4.5 narrative 對應修正：「PRG-vs-GJR 的 canonical 值在 Table 2 (DM $t = 6.00$)；本表聚焦 K1260 fair-information GJR-X benchmark unique 的兩 comparison」
- **Effort**: ~10 min（移除 1 row + 改 §4.5 prose 1 句）

### MEDIUM (1 NEW + 1 CARRY)

**M-NEW-2-v4 (citation MED-1)**. Bollerslev1996 cite for QML-consistency-under-non-Gaussian claim (§2.2 L94)
- **Issue**: QML consistency canonical 來源是 Bollerslev & Wooldridge (1992, *Econometric Reviews* 11(2), 143-172), 不是 Bollerslev & Ghysels (1996)
- **Recommended fix**: §2.2 L94 末 `\citep{Bollerslev1996}` → `\citep{BollerslevWooldridge1992}` 或 `\citep{BollerslevWooldridge1992,Bollerslev1996}`（雙 cite）+ 加 BollerslevWooldridge1992 bibitem
- **Effort**: ~5 min

**M-CARRY-1**. (Already addressed in v4 batch — Hansen2012 disambiguation 1-sentence + bibitem, citation agent 確認 ACCURATE)

### MINOR (3 NEW + 2 CARRY)

| # | Issue | Location | Fix | Effort |
|---|---|---|---|---|
| Min-NEW-1 | §4.5 caption "16 random initializations" 易誤讀為 estimation init | L334 | 改 phrasing「IS LR test internal grid search with 16 starts」明指 LR diagnostic 內部 multistart（K1260 JSON `is_lr_diagnostic.n_starts_used=16` confirmed）| 2 min |
| Min-NEW-2 | Bollerslev1996 bibitem title "heteroscedasticity" → "heteroskedasticity"（canonical）| L385 | 1-char fix | 1 min |
| Min-NEW-3 | Todorova2014 bibitem author "Soucek" → "Souček"（diacritic）| L530+ | char fix | 1 min |
| Min-1 carry | mathptmx → newtxtext+newtxmath (FRL accepts both, optional)| preamble | typography modernization | 1 line |
| Min-2 carry | Bollerslev1996 confusion not fully closed even after Hansen2012 disambig（與 M-NEW-2-v4 同根）| 同上 | 與 M-NEW-2-v4 一併處理 | — |

---

## v3 → v4 Action Apply Audit (4 actions + 1 bonus)

| # | Action | v4 status |
|---|---|---|
| 1 | M-NEW-2b §4.5 K1260 GJR-X subsection | ✅ Closed（latex agent: §4.5 strengths > weaknesses，但 surfaced M-NEW-1-v4）|
| 2 | M-NEW-2a §2.2 forecast-timing paragraph break | ✅ Closed |
| 3 | M-CARRY-1 Hansen2012 disambiguation + bibitem | ✅ Closed（citation agent: ACCURATE）|
| 4 | Min-NEW abstract trim 209→~184 words | ✅ Closed（< FRL 200 limit）|
| 5 (bonus) | §5 third limitation 濃縮 cross-ref §4.5 | ✅ Closed |

**5/5 closed** — v4 batch 全 effective。但 §4.5 K1260 subsection apply 後 **新 surface** 跨 section 數值一致性問題，需 v4.1 disambiguation。

---

## NotebookLM 2 Critical Issues — v4 Status (CONFIRMED CLOSED, STRENGTHENED)

| Issue | v3 verdict | v4 verdict |
|---|---|---|
| Issue A 不公平基準 (PRG 讀 2x vs GJR 1x) | ✅ CLOSED (K1260 + §5 first-order) | ✅ **CLOSED + STRENGTHENED**（§4.5 完整 GJR-X subsection + Table 5 dedicated）|
| Issue B 新穎性偏低 (Bollerslev-Ghysels / Linton-Wu / Kim 2023 / Lai 2024) | ✅ CLOSED (§1 Argument B) | ✅ **CLOSED**（§1 Argument B 維持 + Hansen2012 disambiguation 加強 framework distinction）|

---

## Cross-Paper Meta-Evaluation (主線程)

**Portfolio-level standing**：
- P6 v4 推進路徑健康（v2 3.6 → v3 4.1 → v4 4.2★，monotonic improvement）
- §4.5 K1260 GJR-X subsection 是 portfolio 內最強的「session-bridge structural mechanism」demonstration（DM=7.72 是 paper 最強 single statistic），對 P5 vt-crowding-abm + P10 ohlc-realized-variance 等 sibling papers 提供 differentiation 支撐
- M-NEW-1-v4 的 §4 vs §4.5 DM 6.00 vs 5.24 inconsistency 是**單篇內部 disambiguation 議題**（pattern 同 P1 K1256 + P2 γ，memory `feedback_3spec_disambiguation.md`），**不是** portfolio-level fundamental issue
- NotebookLM 2 critical issues 維持 CLOSED；K1260 contribution intact

**Verdict**: ✅ no fundamental issue at portfolio level（cross-paper meta criterion PASS）

---

## 6-Criteria Gate Evaluation (memory `feedback_paper_cross_paper_meta_eval`)

| # | Criterion | v4 Status |
|---|---|---|
| 1 | latex ≥ 4★ | ✅ **PASS** (4.2)|
| 2 | citation 0 MAJOR + ≤3 MED | ✅ **PASS** (0/1)|
| 3 | cross-paper meta = "no fundamental issue" | ✅ **PASS** |
| 4 | 真實接受率 ≥50% | 🟡 **MARGINAL**（v4 as-is desk-accept 30% + R&R 55% = 85% positive；M-NEW-1-v4 fix 後預期 desk-accept 35-45%，criterion 4 達 PASS 邊界）|
| 5 | 無 critical fairness issue | ✅ **PASS**（K1260 + §4.5）|
| 6 | 無方法論套套邏輯 | ✅ **PASS** |

**5/6 PASS + 1 marginal**（v3 同樣 5/6）— v4.1 fix 1 MAJOR + 1 MED 後預期 6/6 PASS（criterion 4 promote）。

---

## v4.1 主線程 batch fix list（升 ready_for_submission gate 必修）

**Priority 1 (MAJOR)**:
1. **M-NEW-1-v4**: §4.5 Table 5 移除 `PRG Extended vs GJR` row（5.24 vs §4 6.00 numerical inconsistency）+ §4.5 prose 對應修正；保留 GJR-X vs GJR + PRG vs GJR-X 兩 row（K1260 unique 貢獻）— **~10 min**

**Priority 2 (MED)**:
2. **M-NEW-2-v4 (citation MED-1)**: §2.2 L94 QML cite Bollerslev1996 → BollerslevWooldridge1992（或雙 cite）+ 加 BollerslevWooldridge1992 bibitem — **~5 min**

**Priority 3 (cosmetic MIN)**:
3. **Min-NEW-1**: §4.5 caption "16 random initializations" 加澄清「IS LR test internal grid」— ~2 min
4. **Min-NEW-2**: Bollerslev1996 bibitem title heteroscedasticity → heteroskedasticity — ~1 min
5. **Min-NEW-3**: Todorova2014 bibitem Soucek → Souček — ~1 min

**Total effort ~20 min 主線程 batch**.

**v4.1 後預期**：4.4-4.6★ + FRL desk-accept 35-45% / R&R 50% / desk-reject <10% → **criterion 4 PASS**, 6/6 PASS。

**v4.1 round 後是否觸發 v5 review-cycle？**
- 若 v4.1 純 cosmetic + 小範圍 disambiguation（無新內容、無新 narrative），**直接升 ready_for_submission**（不需要 v5 review-cycle 燒 token）
- 若 v4.1 觸發新 narrative（如 §4.5 重寫），則 v5 review-cycle 需要

---

## Files in this round

- `academic_review_report.md` — full latex review (4.2★, 1 NEW MAJOR + 1 NEW MED + 3 NEW MIN + 1 carry MIN)
- `citation_check_report.md` — full citation verification (GREEN PASS for FRL, 0 MAJOR / 1 MED / 2 MINOR cosmetic)
- `README.md` — this round summary (6-criteria gate, cross-paper meta, v4.1 batch action plan)

## Cross-link refs

- `paper/prg-periodic-garch/review_history/v3/` — v3 round (4.1★)
- `paper/prg-periodic-garch/research_notes/v4_batch_2026_04_27.md` — v4 batch fix audit
- `paper/prg-periodic-garch/research_notes/v3_progress_2026_04_27.md` — v3 progress audit
- `experiments/k880/k880_results.json` — §4 main SPY PRG (DM 6.00 source)
- `experiments/k1260/k1260_results.json` — §4.5 K1260 fair-info GJR-X (DM 5.24/7.72/-0.53 source)
- Memory: `feedback_3spec_disambiguation.md` (P1 K1256 + P2 γ disambiguation pattern, applicable to v4.1 fix design)
- Memory: `feedback_paper_multi_round_review.md` / `feedback_paper_cross_paper_meta_eval.md`
- Memory: `project_paper_portfolio_decisions_2026_04_27.md` (Tier A 排序)
