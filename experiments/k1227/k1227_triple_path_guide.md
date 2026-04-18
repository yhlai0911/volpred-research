# Paper 3 Triple-Path Edit Guide (resolve K1128 narrative pivot a/b/c)

> **Status**: Pre-decision pre-production material (markdown only).
> **Date**: 2026-04-17
> **Seed**: 42 (no estimation; seed recorded for any downstream script)
> **Author**: Claude (worktree K1227)
> **Scope**: Extend K1217 (path b full draft) by pre-producing path (a) + path (c) guides so the user can select from complete pre-produced materials in a single review pass.

> ⚠️ **K1205 recommends path (b). K1217 fully drafted path (b). K1227 adds path (a) + path (c) for complete pre-production.** No main-thread paper body should be written until the user confirms a selection. Per CLAUDE.md narrative state machine, single experiments cannot trigger paper body rewrites; this guide is a menu of pre-computed options, not a decision.

---

## 0. Context & canonical inputs

All numerical claims in this guide are verbatim from the K1205 cross-experiment integrity synthesis:

- Source 1 — `experiments/k1205/k1205_synthesis_table.csv`
- Source 2 — `experiments/k1205/k1205_integrity_report.txt` (7 checks, ALL PASS)
- Source 3 — `experiments/k1205/k1205_results.json`
- Source 4 — `experiments/k1217/k1217_paper_draft.md` (~4,991 words, pre-drafted path b body)

Canonical four-branch synthesis (K1205):

| Branch | Experiment | Focal model | n_OOS | n_OOS_jumps | AUC_OOS | DM t vs baseline | Verdict |
|--------|-----------|-------------|-------|-------------|---------|------------------|---------|
| Tertile | K1128 | M3_tertile_high | 20,060 | 32 | 0.5926 | +1.306 | NULL (partial; OOS coverage 0/854/20060 degenerate) |
| Spline | K1131 | M_spline | 20,914 | 33 | 0.4965 | −3.934 | NULL (reverse) |
| Vol-norm | K1142 | M_volnorm | 20,914 | 33 | 0.5940 | +2.255 | PARTIAL_OOS_ONLY |
| Expanding | K1199 | M_expanding | 20,914 | 33 | 0.5484 | +1.143 | NULL |

Harvey (2016) publication threshold is |t| > 3. No branch clears it. K1142 is the only branch crossing the methodological |t| > 2 threshold.

---

## 1. Path (a) — Full K1142 vol-norm anchor

### 1.1 Narrative

**Working title**: *Vol-Normalized Microstructure Signal: A Regime-Free OFI Forecast for TAIFEX 5-Minute Jumps*

Core claim: vol-normalization of the OFI imbalance variable yields a direction-correct jump-prediction signal (AUC_OOS = 0.594, DM t = +2.255) that bypasses the regime-identification problem documented in K1128 / K1131 / K1199. The paper frames this as a methodological contribution, not a trading strategy.

### 1.2 Paper focus

- **Hero result**: K1142 OOS AUC = 0.594, DM t = +2.255, LL_OOS = 0.01165, Brier_OOS = 0.001574.
- **De-emphasize**: the K1128 tertile, K1131 spline, K1199 expanding-window failures. These are cited only briefly (one paragraph) as motivation for why regime identification is brittle, not as central evidence.
- **Positioning**: methodological advance — bypass regime identification via a pre-specified vol-normalized feature, which is robust to the unknown true jump-generating regime.
- **Word target**: ~4,500–5,000 words.

### 1.3 Section outline

1. **Introduction (~700 w)** — microstructure jump prediction for equity index futures, OFI literature (Cont et al. 2014, Xu et al. 2018), regime-identification fragility in high-frequency jump forecasting, statement of contribution.
2. **Methodology (~1,200 w)** — vol-normalization specification (K1142). sigma_hat from strictly-past 60 bars, explicit shift(1) lag, Lee–Mykland jump test, Gumbel α = 0.01 threshold 5.1256. Map of how vol-normalization differs from discrete tertile and continuous spline anchors.
3. **Data (~500 w)** — K1124 TAIFEX TX 5-minute cache, 52,412 valid prediction bars, 115 total jumps, 20,914 OOS bars, 33 OOS jumps, sample period.
4. **Results (~1,400 w)** — K1142 headline table, OOS AUC, DM test (acknowledge Harvey |t| > 3 is not crossed), calibration decile table, lag-12 robustness note (breaks; flagged as limitation).
5. **Discussion (~600 w)** — why vol-normalization succeeds where regime splits fail: the unknown true regime-transition function is absorbed into sigma_hat. Implications for high-frequency microstructure literature.
6. **Conclusion (~300 w)** — regime-free vol-normalized OFI is a methodologically novel signal with Harvey-borderline but direction-correct OOS evidence; future work on cross-market replication (K1145/K1220).

### 1.4 Risks

| Risk | Severity | Mitigation path |
|------|----------|-----------------|
| Single positive cell (only K1142 among 4 branches works) | **HIGH** | Methodological framing: vol-norm was ex-ante pre-specified, not ex-post selected from a sweep |
| Realvol-tertile K1142-equivalent alt spec DM = +1.98 non-significant | **HIGH** | Report as robustness in appendix; state that VIX vol-norm is the pre-specified canonical choice |
| 33 OOS jumps underpowered for Harvey (2016) |t| > 3 gate | **MEDIUM** | Acknowledge explicitly; position as |t| > 2 methodological contribution |
| Lag-12 robustness breaks | **MEDIUM** | Appendix robustness section; lag-1 is the pre-specified canonical |
| Reviewer challenges ex-ante vs ex-post specification | **HIGH** | Point to K1142 pre-registration commit timestamp (2026-04-17) and sigma_hat strictly-past construction |

### 1.5 Target journals

Primary: **International Review of Financial Analysis** (IRFA) — receptive to methodology-contribution papers with single-feature focal results.
Secondary: **Finance Research Letters** (FRL) — short-format suits narrow-scope contribution; fast review cycle.
Tertiary: **Pacific-Basin Finance Journal** (PBFJ) — Taiwan-market audience, but lower impact.

### 1.6 Estimated effort

- ~3 weeks new body draft (path a has no pre-drafted material).
- +1 round `paper-review-cycle` (latex-academic-reviewer + citation-verifier).
- +1 round Codex adversarial review (expected focus: single-cell evidentiary risk).
- K1220 cross-market replication (ES / NQ) is **recommended** to strengthen before submission; without it reviewer risk remains HIGH.

---

## 2. Path (b) — Hybrid null + K1142 partial positive (K1205 RECOMMENDED)

### 2.1 Narrative (K1217 pre-drafted)

**Working title**: *Regime-Dependent Volatility Jump Prediction on TAIFEX: A Four-Branch Null with Vol-Normalized Partial Positive Signal*

Core claim: four complementary operationalizations of regime dependence (IS-fixed tertile, continuous spline, expanding-window adaptive quantile, vol-normalized continuous anchor) yield an honest null on TAIFEX 5-minute jump prediction, with one partial-positive methodological exception (vol-normalization, K1142 DM t = +2.255).

### 2.2 Materials

Full ~4,991-word pre-draft at `experiments/k1217/k1217_paper_draft.md`. Structure (6 sections + abstract + references):

- Abstract
- §1 Introduction
- §2 Methodology
- §3 Data
- §4 Results (four-branch panel + partial positive row)
- §5 Discussion (why the honest null matters; when vol-normalization helps)
- §6 Conclusion + references (24 citations listed)

### 2.3 Status

**CONDITIONAL on user selection.** Per CLAUDE.md narrative state machine: single experiments cannot trigger paper body rewrites; K1217 must not be cherry-picked into any `paper/<name>/main.tex` without explicit main-thread / user approval.

### 2.4 Risks

| Risk | Severity | Mitigation |
|------|----------|-----------|
| Reviewer dismisses null-dominant paper as uninteresting | **MEDIUM** | Methodological framing: four-branch null is a pre-registered rule-out protocol, not a failed sweep |
| Vol-norm partial positive feels cherry-picked | **MEDIUM** | Four branches pre-specified and reported; K1142 is one of four, not isolated from null branches |
| Honest-null paper may face journal-fit issue at certain venues | **LOW** | JoE explicitly open to honest-null framings |

### 2.5 Target journals

Primary: **Journal of Empirical Finance** (JoE) — methodology-paper tradition, receptive to honest null + partial positive framings.
Secondary: **International Review of Financial Analysis** (IRFA).
Tertiary: **Pacific-Basin Finance Journal** (PBFJ).

### 2.6 Estimated effort

- ~2 weeks to adopt K1217 into `paper/<name>/main.tex` (body substantially pre-drafted).
- +1 round `paper-review-cycle`.
- +1 round Codex adversarial review (expected focus: honest-null framing credibility, vol-norm partial-positive calibration).
- K1218 (Codex review of K1217), K1219 (.bib construction + citation verification), K1220 (cross-market K1142) are derived directions.

---

## 3. Path (c) — Abandon Paper 3

### 3.1 Rationale

- All four branches are NULL or PARTIAL at borderline (|t| < 3). Harvey (2016) publication threshold is not crossed by any branch.
- Cumulative effort across the K1100g series + K1128 / K1131 / K1142 / K1199 is already ~1 year+.
- Expected write-up cost (~2–3 weeks) is non-trivial vs. marginal publication probability (JoE / IRFA acceptance at borderline |t| is uncertain).
- TAIFEX microstructure paper pipeline has higher-EV candidates; submission slot is a scarce resource.

### 3.2 Salvage options

1. **Methodology note**: write the K1205 synthesis as a standalone negative-result methodology note (Journal of Empirical Finance methodology section, 3–4 pages). Lower effort (~1 week), lower reward, but preserves the four-branch null as a contribution.
2. **Cross-market contribution**: repurpose K1142 vol-norm + K1100g_d7 cross-market material as a robustness appendix / data-note contribution to a sibling negative-result paper (K1214-style BTC pattern).
3. **Internal research memo**: archive as an internal research memo, no external publication. K1205 synthesis + figures already preserved at `experiments/k1205/`; K1217 draft stored as historical artifact.

### 3.3 Sunk-cost consideration

- Experiments are **not sunk**. Knowledge entries preserved:
  - `knowledge.json` id = aab5c94b (K1205 synthesis)
  - `knowledge.json` id = f63b6e01 (K1128 tertile null)
  - `knowledge.json` id = ae05df05 (K1142 vol-norm partial positive)
- Each failed branch is a tested rule-out protecting future research from repeating dead ends.
- K1142 vol-norm methodology may seed a future paper, either as a TAIFEX-specific follow-up or as part of a cross-market microstructure study.
- Cross-market K1100g_d7 weak-universal gap² evidence remains available as a standalone replication note.

### 3.4 Estimated effort

- Salvage option 1 (methodology note): ~1 week.
- Salvage option 2 (appendix donation): effort absorbed into host paper, minimal.
- Salvage option 3 (internal memo): ~1 day to finalize archive.

---

## 4. Decision matrix

| Dimension | (a) Vol-norm anchor | (b) Hybrid K1205-RECOMMENDED | (c) Abandon |
|-----------|---------------------|------------------------------|-------------|
| Paper count delta | +1 new | +1 new | 0 |
| Draft completeness | outline only (K1227) | full draft (K1217, ~4,991 w) | n/a |
| Evidence quality | single positive cell (K1142 only) | 4-branch null + 1 partial positive | n/a |
| Reviewer risk | **HIGH** (single-cell) | **MEDIUM** | **LOW** (no submission) |
| Contribution strength | narrow (methodological) | methodological + honest-null | null (or minor salvage) |
| Time to submission | ~3 weeks | ~2 weeks | 0 |
| Target journal tier | IRFA / FRL (B-tier) | JoE / IRFA / PBFJ (B–A-tier) | n/a |
| Sunk-cost preservation | partial (K1142 only) | full (4 branches reported) | full (no external publication) |
| Cross-market robustness dependency | K1220 recommended pre-submission | K1220 optional | n/a |

---

## 5. Recommendation (as-of K1227)

**Default to path (b)** per K1205 synthesis recommendation. Path (b) rationale:

- Evidence quality is highest (4 branches + partial positive, not single cell).
- Draft is substantially pre-written (K1217 ~5k words), lowering submission time.
- Reviewer risk is moderate (honest-null framing is defensible with JoE editor fit).
- Target journal quality is highest (JoE primary).

**Path (a) is a fallback** if cross-market K1220 replication produces a strong universal vol-norm result; in that case the single-cell weakness is substantially mitigated and methodological positioning becomes stronger. Without K1220, path (a) carries HIGH reviewer risk.

**Path (c) is available** if (i) cognitive fatigue is high, (ii) the submission pipeline is crowded with higher-EV candidates, or (iii) the user judges the marginal publication probability too low to justify ~2–3 weeks of write-up effort. Salvage option 1 (methodology note) preserves most of the contribution at ~1 week cost.

---

## 6. How to select

Per CLAUDE.md narrative state machine:

1. User confirms selection (a / b / c) in the main thread.
2. `research_program.md` Paper 3 section is updated with `status='decision_made_awaiting_body_rewrite'` (for a/b) or `status='abandoned_with_salvage'` (for c).
3. `knowledge.json` is updated with the decision entry.
4. Body rewrite (for a/b) or salvage execution (for c) begins in the main thread using the chosen pre-produced material:
   - Path (a): use §1 of this guide as the outline starter.
   - Path (b): use `experiments/k1217/k1217_paper_draft.md` as the body draft starter.
   - Path (c): use §3 of this guide to execute the chosen salvage option.

No paper body `.tex` is written by a background / worktree agent under any path. K1227 is the pre-production menu; it does not authorize body writes.

---

## 7. References

- `experiments/k1205/` — canonical 4-branch synthesis (integrity report ALL PASS)
- `experiments/k1217/k1217_paper_draft.md` — path (b) pre-drafted body (~4,991 words)
- `experiments/k1128/` — VIX tertile IS-fixed, NULL (partial; OOS coverage degenerate)
- `experiments/k1131/` — Natural cubic spline, NULL (reverse direction)
- `experiments/k1142/` — Vol-normalized OFI, PARTIAL_OOS_ONLY
- `experiments/k1199/` — Expanding-window adaptive quantile, NULL
- `experiments/k1100g_d7/` — Cross-market weak-universal gap² evidence
- `experiments/k1124/` — TAIFEX TX 5-minute cache
- `research_program.md` §Paper 3 — current state and narrative decision options
- `docs/error_log.md` 2026-04-13 — IS-regime degeneracy lesson
- CLAUDE.md "paper narrative state machine" — governs when body rewrite may begin
- Harvey, C. R. (2016). *The Scientific Outlook in Financial Economics*. AFA Presidential Address. — |t| > 3 publication threshold
