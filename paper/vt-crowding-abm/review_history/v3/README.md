# Review Round v3 — vt-crowding-abm (Paper 5)

**Date**: 2026-04-28
**Triggered by**: Post-reframe full review. v2 (2026-04-27) ended with 4.4★/5 + 1 MAJOR (`\ref{subsec:vt_rule}` broken). 主線程 2026-04-27/28 做了 v3 reframe（VT-only crowding → family-level threshold framework on positive-feedback strategies），新增 4 strategy treatments (VT/TF/MR/NoiseControl)、43,300 sims (K827v3 + K1261 + K1262 + K1262b)、§4.4 cross-strategy + §4.5 K1262b OAT + §5.4 knife-edge rebuttal + §5.3 +2 limitations + §6 3-claim conclusion + 5 new bibitems。
**Manuscript**: `paper/vt-crowding-abm/main.tex` (v3 final, 23 pages, 0 errors / 0 undefined refs, reproduce GREEN 47/47 100%)
**Target journal**: Finance Research Letters (FRL)
**Reviewers** (Claude general-purpose subagent proxies):
- `latex-academic-reviewer` proxy via `a1166416bf76c0383`
- `citation-verifier` proxy via `a5ab50b1d0e7cfd3d`

---

## Overall Assessment

| Reviewer | Verdict | Rating |
|----------|---------|--------|
| Academic | 0 CRITICAL / **1 SEVERE** / **3 MAJOR** / 7 MED / 6 MINOR | ★★★★⯨ (**4.2/5**, v2 4.4 → −0.2 due to v3 reframe integration artifacts) |
| Citation | 0 MAJOR / **1 MED-blocking** / 5 MINOR; 5 v3 new bibitems all verified clean | ⚠️ revise (≤5 min DOI patches) |

**Joint verdict**: **DO NOT submit as-is — v4 round needed (~2-3 hr main-thread)**. Reframe quality itself is strong（family-level argument intellectually defensible、§3.1 4-strategy treatments clean、§5.4 knife-edge rebuttal honest、§5.3 Seventh/Eighth limitations 強）；但 v3 reframe 留下 3 個整合 artifact 必須修：

1. **§2.4 Simulation Design paragraph 仍是 v2 design**（K1262 OAT-9 × {10%,30%,50%}）— 直接矛盾 §4.5 v3 K1262b design (5 cells × 4 adoption {10%,30%,70%,100%}, $\kappa$ dropped)。Single biggest credibility risk in v3。
2. **Table 2 vs Table 4 cell1 baseline 數值不一致**：Table 2 (K1261, M=500) 報 TF=20%/MR=20%；Table 4 (K1262b, M=200) 報 TF=30%/MR=70%。MC sampling noise at adoption-grid boundary — 必補 reconciliation footnote。
3. **Abstract "7 × 4 × 12 × 5" 讀起來像 fully-crossed design**（應為三層 K1261 + K1262 + K1262b）— compute backwards-derives wrong sim count。

**Predicted FRL outcome (after v4)**: R&R with minor-to-moderate revisions → accept (~50% minor-rev path, ~80-85% net acceptance conditional on S1 + M1 + M2 + MED-blocking fixed).

---

## Issues Summary

### CRITICAL (0) — none

### SEVERE (1)

**S1. §2.4 stale OAT description** (main.tex line 121)
- Source: academic v3
- Issue: Simulation Design paragraph still describes v2 OAT design ($\lambda$/$\gamma$/$\kappa$ × 9 configs × 3 adoption {10%,30%,50%})；contradicts §4.5 line 279 v3 K1262b design ($\lambda$/$\gamma$ × 5 cells × 4 adoption {10%,30%,70%,100%}, $\kappa$ dropped)
- Why critical: any reviewer reads §2 → §4 sees direct contradiction → desk-reject signal
- Fix: rewrite §2.4 to match K1262b design exactly (15-20 min)

### MAJOR (3 academic + 0 citation = 3)

**M1. Table 2 vs Table 4 internal inconsistency** (cell1 baseline detector mismatch)
- Source: academic v3
- Both report "cell1 baseline, Sharpe-only detector"; Table 2 (K1261, M=500): TF=20%/MR=20%; Table 4 (K1262b, M=200): TF=30%/MR=70%
- Root cause: M=500 vs M=200 MC sampling noise at adoption-grid boundary（驗證 against `k1261_threshold_comparison.md` + `k1262b_oat_table.md`）
- Fix: add reconciliation footnote explaining MC variance at adoption boundary; OR re-run K1262b cell1 with M=500 for harmonization (~2 hr compute)
- Decision: **footnote + acknowledge sampling noise** is sufficient（cheaper, honest）

**M2. Abstract sim-count cross-product misleading**
- Source: academic v3
- "7 × 4 × 12 × 5" reads as fully-crossed (would imply 1,680 cells × ~26 MC); actual design is three-phase layered (K1261 + K1262 + K1262b)
- Fix: rewrite abstract sim-count line to "8,800 baseline + 16,000 K1262 OAT-9 + 17,800 K1262b cross-treatment OAT = 43,300 total" or similar layered statement (5 min)

**M3. (academic v3 — see academic_review_report.md for detail)**
- See academic_review_report.md M3 entry; not blocking but should fix in v4

### MEDIUM (7 academic + 1 citation = 8)

**Citation MED-1 (BLOCKING)**: `harvey2018` DOI 仍缺 (main.tex line 421-424); v2 README 已列為 v3 必修，v3 維持原樣
- Fix: 補 `\url{https://doi.org/10.3905/jpm.2018.45.1.014}` (1 min)

**Academic MEDs**:
- MED-1: MC SE in Tables (v2 carry-over)
- MED-2: kurtosis CI block-bootstrap (v2 carry-over)
- MED-4: fire-sale citation (v2 carry-over)
- MED-5: §5.4 ¶2 knife-edge rebuttal under-flags ±50% perturbation 範圍 vs literature ~10× $\lambda$ variation (K1262b verdict caveat #3)
- MED-6: Welch's t justification (v2 carry-over)
- MED-7: NoiseControl $w=0.5$ rationale unjustified — easy preempt for falsifier credibility
- (見 academic_review_report.md 完整列表)

### MINOR (6 academic + 5 citation = 11)

**Citation MINORs (v2 carry-over 4/5)**:
- MIN-1: perchet2016 cite-key
- MIN-3: kyle1985 page 1335→1336
- MIN-4: cole2017 URL
- MIN-2: danielsson2012 ABM phrasing (v3 改為 "feedback-driven market dynamics" 部分緩解，可進一步收緊)
- MIN-5 (NEW v3): §5.3 Seventh limitation TSMOM scaling 主張缺 citation，補 `\citep{moskowitz2012}`

**Academic MINORs**: MIN-1 `\and VolPred Research System` 仍存在 (v2 carry-over) + 5 個 v3 新發現 (見 academic_review_report.md)

---

## v2 Unfixed Carry-overs (3rd round!)

**Process discipline gap**：v2 標為 "v3 必修" 的清單在 v3 reframe 期間沒整批處理。屬於主線程 reframe 注意力被 narrative 改寫吃掉的疏失。

| v2 ID | Type | Status in v3 | Severity |
|---|---|---|---|
| harvey2018 DOI 缺 | citation MED | ❌ unfixed | MED-blocking |
| perchet2016 cite-key | citation MIN | ❌ unfixed | MINOR |
| kyle1985 page | citation MIN | ❌ unfixed | MINOR |
| cole2017 URL | citation MIN | ❌ unfixed | MINOR |
| MC SE in Tables | academic MED | ❌ unfixed | MED |
| kurtosis CI bootstrap | academic MED | ❌ unfixed | MED |
| fire-sale citation | academic MED | ❌ unfixed | MED |
| Welch's t justification | academic MED | ❌ unfixed | MED |
| `\and VolPred Research System` | academic MIN | ❌ unfixed | MINOR |

**v2 已修**: subsec:vt_rule broken ref (修法為 \label{eq:vt_rule} + 直引 `\eqref{eq:vt_rule}`)、barroso2021 mischaracterization、multi-key `\citet`。

---

## v3 Strengths

- Family-level reframe **intellectually defensible**：abstract / §1 / §3.1 / §4.4 / §5.1 / §6 narrative 一脈相連
- §3.1 4-strategy treatments (VT/TF/MR/NoiseControl) clean；3 new equations 整合好
- §4.4 17/17 robustness checks (12 strategy-spec + 5 microstructure) 直接 answer NotebookLM knife-edge critique
- §5.3 Seventh (s=10 honesty) + Eighth (three-class vs continuum) limitations 強
- §6 conclusion 3-claim structure 每 claim 有 §4 對應證據
- 5 new bibitems 全 verified clean (DOI/author/quoted-content all match)
- Reproduce GREEN 47/47 — 所有 numerical claims auditable

---

## Action Plan for v4

**主線程必修 (paper-update skill, ~2-3 hr)**:

1. **S1 fix** (15-20 min): 重寫 §2.4 Simulation Design paragraph match K1262b 設計
2. **M1 fix** (5 min): 加 reconciliation footnote explaining Table 2 vs Table 4 cell1 MC variance
3. **M2 fix** (5 min): 重寫 abstract sim-count 為三層 layered statement
4. **Citation MED-1 fix** (1 min): 補 harvey2018 DOI
5. **v2 carry-over batch** (~10 min): 一次處理 perchet2016/kyle1985/cole2017/MC SE/kurtosis CI/fire-sale/Welch/`\and` etc.
6. **MED-5 fix** (5 min): §5.4 ¶2 補 ±50% vs literature scale 範圍 caveat
7. **MED-7 fix** (5-10 min): §3.1 NoiseControl $w=0.5$ rationale 補 1-2 句 (random-coin midpoint baseline)
8. **MIN-5 fix** (1 min): §5.3 Seventh 補 `\citep{moskowitz2012}` for TSMOM scaling literature
9. **v3 編譯**: `cd paper/vt-crowding-abm && pdflatex main.tex` × 2 確認 0 errors
10. **reproduce.py 重跑**: 確認 47/47 GREEN 不退化（v4 純 narrative + footnote 不應改數字）

**可 deferred 到 v5**:
- M3 (academic v3 detail)
- 其餘 MINOR 5 個（v3 新發現）

**Prediction**: if S1 + M1 + M2 + MED-blocking + v2 carry-over batch fixed → 4.6-4.7★/5；FRL R&R-then-accept 概率 85%。

---

## Stage Decision

**Stage stays at `review`** (NOT promoted to `ready_for_submission`).

**Reason**: 1 SEVERE + 3 MAJOR + 1 MED-blocking 全部要在 v4 修完才符合 ready 標準（latex ≥ 4★ + citation 0 MAJOR + ≤3 MED）。v4 修完跑下一輪 review，若達標再升 stage。

---

## Files in this round

- `academic_review_report.md` (latex-academic-reviewer proxy a1166416bf76c0383)
- `citation_check_report.md` (citation-verifier proxy a5ab50b1d0e7cfd3d)
- `README.md` (本檔)

## Next round trigger

After 主線程完成 v4 修正（paper-update skill）→ 新一輪 review → 寫入 `review_history/v4/`。
