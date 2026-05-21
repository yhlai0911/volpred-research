# Review Round v3 — prg-periodic-garch (Paper 6)

**Date**: 2026-04-27
**Triggered by**: 主線程 driving v3 修訂收斂 — v2 round (2026-04-27) 採 NotebookLM portfolio-lens 後降至 3.6★（v1 4.2 → v2 3.6 -0.6）。v2 揭示 2 NotebookLM critical issues + 3 MAJOR + 5 MED + 4 MINOR。本 v3 round 主線程 apply 12 actions，並含 K1260 GJR-X experiment first-order finding integration。
**Manuscript**: `paper/prg-periodic-garch/main.tex` (post v3 13-action apply, including post-review M-NEW-1 soft-fix)
**Target journal**: Finance Research Letters (FRL)
**Reviewers**:
- `latex-academic-reviewer` proxy via Claude general-purpose subagent `a0ef3da54b39de3a6`
- `citation-verifier` proxy via Claude general-purpose subagent `aefbb5b06cea2733c`
- `cross-paper-meta-evaluator` 主線程（K1260 portfolio risk re-eval + NotebookLM RAG `5d8707e3` 既有結果）

---

## Overall Assessment

| Reviewer | Verdict | Rating |
|----------|---------|--------|
| Citation | **0 MAJOR / 0 MED / 1 MINOR** (cosmetic Todorova `\doi{}` → `\url`); 20 cites strict alphabetical; 5 假以為的 v1-carry MIN-Cs **不在 P6**（誤 attributed from P5）；Hansen2012 cite **不需要**（Realized = RV proxy 不是 framework cite） | ✅ **GREEN PASS for FRL** |
| Academic | 0 CRITICAL / 0 SEVERE / **1 NEW MAJOR (M-NEW-1) §5 L313 forward-ref Section 4.5 不存在** / 2 NEW MED + 1 carry MED / 1 NEW MIN + 4 carry MIN | ★★★★ (**4.1/5**, v2 3.6 → +0.5) |
| Cross-paper meta | K1260 first-order claim 強化 differentiation；session-bridge structural mechanism 對應 NotebookLM Argument A 完整 close fairness limitation | ✅ no fundamental issue |

**Joint verdict**: **Run v4 round**（不直接升 ready）。M-NEW-1 已 post-review **soft-fix done**（drop forward-ref + 重 phrasing）+ Min-1 cosmetic Todorova \url consistency done。剩 2 NEW MED + 1 carry MED 待 v4。

**Predicted FRL outcome (post v3 + post-fix)**: desk-accept 30% / R&R 55% / **desk-reject 15%**（v2: desk-reject 30% → -15pp）

---

## Issues Summary (v3 latex agent)

### CRITICAL (0) — none
### SEVERE (0) — none

### MAJOR (1) — **post-review fixed**
- **M-NEW-1**. §5 L313 forward-references `Section~4.5` 不存在（§4 has only 4 subsections） — likely v2 carry-over regression
- **Status**: ✅ **Soft-fixed**（drop reference + 重 phrasing「though our TAIFEX tick-level analysis indicates that...」）；medium-fix（write §4.5 covering tick-vs-OHLC robustness + K1260 GJR-X subsection, 1-2 hr）留 v4 評估

### MEDIUM (3 total: 2 NEW + 1 carry)
- **M-NEW-2a**. Paragraph density §2.2 L113-127 single-block（Med-4 partial — 拆 3-句 helped 但 ~670-word block 仍 dense）
- **M-NEW-2b**. K1260 result 在 abstract + §5 已 integrate 但 **missing in §4 Results** — reviewer 可能 read §4 找不到 fair-info GJR-X table
- **M-CARRY-1**. Hansen-Huang-Shek 2012 Realized GARCH citation gap（promoted from v2 Min-4）— **citation agent disagrees**（Realized = RV proxy 不是 framework cite）；reviewer disagreement 待主線程 arbitrate

### MINOR (5 total: 1 NEW + 4 carry)
- **Min-NEW**. Abstract 209 words（target ≤200）— v3 K1260 evidence sentence 加入後超 9 words
- **Min-1 carry**. mathptmx → newtxtext+newtxmath（FRL accepts both, optional）
- **Min-2 carry**. harvey2018 DOI verify（citation agent 確認此 cite-key 不在 P6 — **撤銷**）
- **Min-3-5 carry citation polish**: perchet/danielsson/kyle/cole/Engle-Sokalska — citation agent 確認**這 5 個不在 P6 paper**（誤 attributed from P5）→ **全撤銷**

---

## v2 → v3 Action Apply Audit (12 actions + post-review fix)

| # | Action | v3 status |
|---|---|---|
| 1 | M2 §1 contribution rewrite (Argument B + C punch) | ✅ Closed |
| 2 | M2 abstract trim (砍重複句) | ✅ Closed |
| 3 | MED-C1 Todorova DOI add | ✅ Closed (post-review consistency `\doi{}` → `\url{}`) |
| 4 | M1 K1260 GJR-X experiment + cherry-pick | ✅ Closed |
| 5 | knowledge.json append (item_id=f16c1ade) | ✅ Closed (Codex review timeout, self-verified) |
| 6 | Med-1 Bollerslev calendar→session sentence | ✅ Closed |
| 7 | Min-3 Table 4 MDD sign convention | ✅ Closed |
| 8 | Med-4 forecast-timing paragraph break | 🟡 Partial（拆 3-句 helped 但 paragraph 整體仍 dense）|
| 9 | abstract K1260 evidence sentence | ✅ Closed |
| 10 | Med-5 §5 limitation 升級 first-order finding | ✅ Closed |
| 11 | Med-2 PRG-vs-Separate cross-market promote | ✅ Closed (`\paragraph{Cross-market generalization.}`) |
| 12 | Med-3 bibliography full alphabetical | ✅ Closed (verified 20 entries strict A-Z) |
| 13 (post-review) | M-NEW-1 §5 L313 forward-ref soft-fix | ✅ Closed |

**11/12 fully closed + 1 partial + 1 post-review fix = effective 13 actions done in v3**

---

## NotebookLM 2 Critical Issues — v3 Status (CONFIRMED CLOSED)

| Issue | v2 verdict | v3 verdict |
|---|---|---|
| Issue A 不公平基準 (PRG 讀 2x vs GJR 1x) | MAJOR (Fix A 缺) | ✅ **CLOSED** — K1260 experiment + §5 first-order finding |
| Issue B 新穎性偏低 (Bollerslev-Ghysels / Linton-Wu / Kim 2023 / Lai 2024) | MAJOR (over-claim risk) | ✅ **CLOSED** — §1 contribution Argument B Ultra-Parsimony 對比 |

---

## 6-Criteria Gate Evaluation (memory `feedback_paper_cross_paper_meta_eval`)

| # | Criterion | v3 Status |
|---|---|---|
| 1 | latex ≥ 4★ | ✅ **PASS** (4.1) |
| 2 | citation 0 MAJOR + ≤3 MED | ✅ **PASS** (0/0) |
| 3 | cross-paper meta = "no fundamental issue" | ✅ **PASS** (K1260 mitigates portfolio risk; differentiation 強化) |
| 4 | 真實接受率 ≥50% | 🟡 **MARGINAL** (R&R 55% + accept 30% = 85% positive；desk-accept 30% alone = below 50%) |
| 5 | 無 critical fairness issue | ✅ **PASS** (K1260 closes) |
| 6 | 無方法論套套邏輯 | ✅ **PASS** |

**5/6 PASS + 1 marginal**（v2 was 2/6）

---

## v4 Round 必修 list（升 ready_for_submission gate）

**主線程必修（v4 開始前）**:
1. **M-NEW-2b**: K1260 result 加進 §4 Results — 加 §4.5 subsection（~30-60 min）含 GJR-X table + IS LR diagnostic discussion，referenced from §5 limitation
2. **M-NEW-2a**: §2.2 L113-127 整段 dense — 拆成 2 個小 paragraphs（~10 min）
3. **M-CARRY-1 Hansen2012 disagreement arbitration**: 採 citation agent 判斷（不需 cite），但在 §1 / §2.2 加 1 sentence 解釋「Realized」是 RV proxy（避免 reviewer 質疑 attribution gap）（~10 min）
4. **Min-NEW abstract trim 9 words to ≤200** (~5 min)

**Total effort ~1-2 hr 主線程 batch**.

**v4 round 預期**：M-NEW-1/2 fix 後 + abstract trim → ★4.4-4.6 + FRL desk-accept 35-45% / R&R 55% / desk-reject <10%。**criterion 4 應 promote 到 PASS**（desk-accept ≥40%）.

---

## Files in this round

- `academic_review_report.md` — full latex review (NotebookLM Arguments A/B/C 全 close + 1 NEW MAJOR + 2 NEW MED 等)
- `citation_check_report.md` — full citation verification (GREEN PASS for FRL)
- `README.md` — this round summary

## Cross-link refs

- `paper/prg-periodic-garch/review_history/v2/` — v2 round (3.6★)
- `paper/prg-periodic-garch/review_history/v1/` + `pre_submission_audit_v1/`
- `paper/prg-periodic-garch/research_notes/notebooklm_prior_periodic_garch.md` — NotebookLM 3 arguments
- `paper/prg-periodic-garch/research_notes/v3_progress_2026_04_27.md` — v3 progress audit
- `paper/prg-periodic-garch/main_pre_v3_m2.tex` — pre-v3 M2 backup
- `experiments/k1260/` — K1260 GJR-X experiment (cherry-picked commit a49d4b9a)
- Memory: `project_paper_portfolio_decisions_2026_04_27.md` (Tier A) / `feedback_paper_multi_round_review.md` / `feedback_paper_cross_paper_meta_eval.md`
