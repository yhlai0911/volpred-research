# Review Round v2 — vt-crowding-abm (Paper 5)

**Date**: 2026-04-27
**Triggered by**: User explicit feedback 2026-04-27「學術論文要經過多輪 latex-academic-reviewer 審核與修訂」(memory: `feedback_paper_multi_round_review.md`). P5 was sitting in 「✅ READY GREEN — 等用戶 confirm 投稿」standby for 7-8 days; user redirected to review-cycle path instead of direct submission.
**Manuscript**: `paper/vt-crowding-abm/main.tex` (post v1 fix; reproduce GREEN 33/33)
**Target journal**: Finance Research Letters (FRL)
**Reviewers**:
- `latex-academic-reviewer` proxy via Claude general-purpose subagent `a7487ff0cce7e0c95`
- `citation-verifier` proxy via Claude general-purpose subagent `aa34c83f50e04cedb`

---

## Overall Assessment

| Reviewer | Verdict | Rating |
|----------|---------|--------|
| Citation | 0 MAJOR / 2 MED / 5 MINOR; 16 cites checked (13 v1-baseline + 3 v2-new), v1 13 claims all byte-identical | ⚠️ revise (sub-30-min fixes) |
| Academic | 0 CRITICAL / 0 SEVERE / **1 MAJOR** / 6 MED / 7 MINOR; v1 all 4 MAJOR addressed (no regression) | ★★★★⯨ (**4.4/5**, v1 4.0 → predicted 4.3 exceeded by +0.1) |

**Joint verdict**: **Minor revise → v3 round (~30-60 min main-thread effort)**. Both reviewers agree the paper is now substantively strong; 1 broken cross-ref + 2 citation MEDs + 3 carry-over v1 MEDs are the v3 focus list. **Do NOT submit as-is**: 1 visible compilation glitch (`??` in PDF) is a desk-reject signal even if every other section is solid.

**Predicted FRL outcome (after v3 polish)**: 85-90% acceptance, R&R-then-accept realistic.

---

## Issues Summary

### CRITICAL (0) — none
### SEVERE (0) — none

### MAJOR (1)
**M1. Broken cross-reference `\S\ref{subsec:vt_rule}` at main.tex line 197**
- Source: academic review v2
- Issue: `\ref{subsec:vt_rule}` used but no matching `\label{subsec:vt_rule}` exists; will compile to `??` placeholder in PDF
- Why it matters: any reviewer opening the PDF sees `§??` — instant red flag for FRL desk-reject screen
- Fix: 2-line change — add `\label{subsec:vt_rule}` to the relevant subsection in §3 (VT rule definition); recompile

### MEDIUM (8 total — 6 academic + 2 citation)

**Academic MEDs (6)**:
1. **M2. Abstract length regression**: grew from ~254 to ~280 words because "0.13 of 0.25" detail added without offsetting cuts — over FRL norm (target ≤250). Trim 30+ words.
2. **M3. MC standard error not reported** (carry from v1) — bootstrap MC over 1000 simulations should publish SE alongside point estimate
3. **M4. Kurtosis CI at φ=100% implausibly narrow** (carry from v1) — CI width inconsistent with sample size; possibly downward-biased estimator
4. **M5. Fire-sale literature missing** (carry from v1) — at minimum cite Shleifer-Vishny (1992) or Coval-Stafford (2007) given crowding mechanism
5. **M6. (additional academic MED — see academic_review_report.md §MED)**
6. **M7. (additional academic MED — see academic_review_report.md §MED)**

**Citation MEDs (2)**:
1. **M8. `barroso2021` mischaracterized at line 58** — paper actually finds vol-managed *market* portfolio survives transaction costs (opposite to "question whether VT's Sharpe improvement survives realistic implementation costs" framing). Fix: drop from critic-trio or reframe as cost-conditional. Cederburg2020 and liu2019 are correctly cited.
2. **M9. `harvey2018` DOI gap** conspicuous now that v1 added 3 sibling DOIs. Add `10.3905/jpm.2018.45.1.014`.

### MINOR (12 total — 7 academic + 5 citation)
- Academic minors: typography / writing polish / 1-2 figure caption tweaks
- Citation minors: 4 carry from v1 (perchet2016 cite-key inconsistency, danielsson2012 ABM page, kyle1985 page number, cole2017 URL drift) + 1 new
- See individual reports for full enumeration

---

## v1 Progress Verification

| v1 Issue tier | Count | v2 status |
|---|---|---|
| MAJOR (academic) | 4 | ✅ all addressed (figures added, eq:vt_delta formalized, 3 VT-skeptic refs added, contributions reframed to 3) — **no regression** |
| MED-C DOIs (citation) | 3 | ✅ all added verbatim (moreira2017 / brunnermeier2009 / harvey2016) — confirmed active and resolve correctly |
| MED (academic) | 7 | 4 fixed; 3 carry to v3 (MC SE / kurtosis CI / fire-sale lit) |
| MINOR (citation) | 4 | 0 fixed (carry to v3 — sub-30-min batch) |

---

## Action Plan for v3

**主線程必修（v3 開始前）**:
1. M1 broken cross-ref — 2-line label fix + recompile (≤5 min)
2. M2 abstract trim 30 words (≤10 min)
3. M3-M5 三個 v1 carry-over MEDs (MC SE / kurtosis CI / fire-sale lit) — 30 min combined
4. M8 barroso2021 reframe or drop (≤10 min)
5. M9 harvey2018 DOI add (≤2 min)
6. Citation MINORs batch fix (≤10 min)

**Total**: ~60-75 min main-thread effort to converge.

**可 deferred 到 v4**:
- 7 academic MINORs（typography polish — final-pass）
- 1 citation MINOR (new in v2)

**Predicted v3 → ready_for_submission**: if all M1-M9 fixed → 4.6★ → FRL R&R 70%+ + accept 85-90%.

---

## Stage Decision (per paper-stage-classifier logic)

**Current stage**: review (留 review stage 不升)
**Reasoning**:
- Latex 4.4★ ≥ 4★ ✓ but **1 MAJOR (broken cross-ref) blocking** — 即便 SOP 字面允許升 ready (latex ≥4★ + citation 0 MAJOR + ≤3 MED)，SOP 沒明示 latex MAJOR 不為 0 時的處理；用戶 feedback 明確要「多輪收斂」，保守留 review
- Citation 0 MAJOR + 2 MED ≤3 ✓
- Decision: **stay in review**, run v3 after main-thread applies action plan

**Next round trigger**: After 主線程完成 v3 修訂 → 新一輪 v3 review → 寫入 `review_history/v3/`

---

## Files in this round

- `academic_review_report.md` — full latex academic review (283 lines, 26KB)
- `citation_check_report.md` — full citation verification (16 cites checked)
- `README.md` — this round summary

---

## ⚠️ 2026-04-27 User-Challenge Follow-up — v2 4.4★ 預測過度樂觀

用戶 2026-04-27 提供 NotebookLM + 獨立 Opus 評估，揭露此 v2 round 的 single-paper agent 視角無法抓到的 fundamental issue：

### Cross-paper meta-evaluation 結論
- **P5 ABM 臨界點是「設計出來的」**：70% 崩盤閾值是參數 λ/γ 的數學結果，不是市場湧現現象 — reviewer 會說這不是「發現臨界點」而是「製造臨界點」。**這是 single-paper latex review 看不到的 step-back perspective**。
- **真實新穎性低估**：Brunnermeier-Pedersen (2009) + Cont-Bouchaud (2000) 已有 ABM crowding 框架；本文貢獻是「VT 擁擠的量化」這個窄縫，不是 fundamental new
- **跨 9 papers 同數據集 (SPY/GLD/TLT/VIX) 同主題 risk**：reviewer 可能懷疑「一篇切九份」，這個 portfolio-level critique 在任何 single-paper round 都不會 surface

### 修正 v2 verdict
- **舊預測**: 4.4★ + FRL 85-90% accept after v3 polish — **過度樂觀，撤回**
- **新預測（NotebookLM-aligned）**: ★★★⯨ 3.5-3.8/5 + **FRL 40-50% accept** + R&R 機率較高，desk-reject 風險不可忽略
- **根因**: latex-academic-reviewer agent 範圍只在 main.tex，看不到「設計性結果 vs emergent finding」的方法論誠實 framing 問題

### v3 round 必加 3rd 維度（不只 latex + citation）
- 主線程或 dedicated cross-paper-meta-evaluator agent 跑 portfolio-level review，覆蓋：
  - 設計性 vs emergent finding 誠實 framing
  - 真實新穎性（先行文獻 ±3 years）
  - 與其他 P1-P10 paper 的 dataset / methodology / conclusion 重疊度
  - Self-citation 比例
- 詳見 memory `feedback_paper_cross_paper_meta_eval.md`

### v3 主線程必修（升級版 action plan）
舊 plan 的 M1-M9 fix（broken cross-ref / abstract trim / barroso2021 reframe / harvey2018 DOI 等）**仍要修**，但 **不夠**。需 **加上**：
- ABM mechanism framing 重寫：從「發現臨界點」改為「參數敏感度分析 + crowding cost magnitude bounding」（誠實 framing）
- 補充「非 VT 策略也有的擁擠效應」對照（NotebookLM 建議）—— 證明 finding 不僅是 VT-specific
- 加一段討論 dataset / methodology overlap with portfolio 並 explicit 區隔本文獨立貢獻

### Stage 決定維持 review（更保守）
- v2 latex 4.4★ 已被 NotebookLM 降到 3.5-3.8★ → 不滿足升 ready 條件
- 必跑 v3 round 含 cross-paper meta-evaluation 才考慮升 stage

---

## Cross-link refs

- `paper/vt-crowding-abm/review_history/v1/` — v1 round (date 2026-04-18)
- `paper/vt-crowding-abm/citation_check.md` — main canonical citation trail
- `paper/vt-crowding-abm/reproduce_report.json` — GREEN 33/33 confirmed
- Memory `feedback_paper_multi_round_review.md` — multi-round review policy (2026-04-27)
