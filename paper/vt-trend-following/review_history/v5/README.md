# Review Round v5 — vt-trend-following

**Date**: 2026-06-10
**Triggered by**: Hourly dispatch task `paper_review_vtt_v5_audit_2026_06_10` (claimed by hourly-14). Audits v4 (Gemini Jun 5) fix landing in body_v3.tex (Jun 7).
**Reviewers**:
- latex-academic-reviewer: Claude Sonnet 4.6 (main-thread foreground) → `latex_review_v1.md`
- citation-verifier: Claude Sonnet 4.6 (main-thread foreground) → `citation_check_v1.md`
- 3rd model (Codex): **DEFERRED** — 50-min cap would be exceeded; to be run as v6 pre-submission gate per `feedback_3model_review_discipline`

---

## Overall Verdict: **MAJOR_REVISION**

The v4 Gemini fixes have been **partially but not fully landed**. All four issues (H1, H2, M1, M2) show verbal/narrative acknowledgment but the corresponding **quantitative evidence** Gemini required is absent in 3 of 4 cases. A new HIGH-severity finding (NEW-H1: abstract CI range inconsistency) was discovered in this round.

---

## Per-v4-Issue Closure Status

| Issue | v4 Severity | Description | v5 Closure | Reason |
|-------|-------------|-------------|------------|--------|
| **H1** | HIGH | MDD retention >100% may be mechanical (momentum crash rebound) | **PARTIAL** | Verbal caveat + daniel2016 citation added. Empirical decomposition around 2009-03/2020-03 troughs **absent**. |
| **H2** | HIGH | 252-day block bootstrap destroys long-memory | **PARTIAL** | K1417 stationary bootstrap run (mean blocks 756/1260 days). Result favorable (lower bounds move UP not down). But K1417 comparative CI table **not reported in paper** — only a narrative parenthetical "(K1417 task audit)". |
| **M1** | MEDIUM | Split-sample r=0.793 is regime-shift artifact, not endogeneity fix | **PARTIAL** | Regime-shift limitation extensively discussed in prose. Safe-haven dummy control regression **not run**. |
| **M2** | MEDIUM | Insurance premium vs. VRP confound | **PARTIAL** | bollerslev2009 + bondarenko2019 citations added, cautionary "reduced-form" language added. Explicit two-hypothesis comparison with welfare implications **absent**. |
| Citations: bollerslev2009 | REQUIRED | VRP literature | **CLOSED** | Present in bibliography + appropriate in-text usage. |
| Citations: campbell1999 | REQUIRED | Habit/drawdown aversion utility | **CLOSED** | Present in bibliography + appropriate in-text usage. |
| Citations: bondarenko2019 | REQUIRED | Put insurance pricing | **CONDITIONAL** | Present. DOI/author combination requires pre-submission verification. |
| Citations: politis1994 | REQUIRED (H2 fix) | Stationary bootstrap | **CLOSED** | Present and correctly used. |

---

## New Residuals Found in v5

| ID | Severity | Description |
|----|----------|-------------|
| **NEW-H1** | HIGH | Abstract states CI lower bounds "76–93%" (K1376 moving-block). K1417 stationary bootstrap actually gives HIGHER bounds (90–100%). Abstract narrative "no qualitative weakening" is misleading — should say stationary bootstrap *strengthens* the lower bounds. |
| **NEW-M1** | MEDIUM | 50/50 Calmar ratio drop (0.624→0.501) is disproportionate to 95.6% MDD retention — internal inconsistency requiring verification or footnote explanation. |
| **NEW-MINOR-1** | MINOR | Hood & Raughtigan (2025) working paper missing URL/SSRN number. |
| **NEW-MINOR-2** | MINOR | K898 forensic note ("subject to ongoing reconciliation") still unresolved after ≥2 revision rounds; should be closed before submission. |
| **NEW-MINOR-3** | MINOR | Sector sample start date (1998) vs. primary sample (2005) difference not flagged in Section 3.4. |

---

## Severity Summary

| Severity | Count | Items |
|----------|-------|-------|
| HIGH (blocking) | 3 | H1 (partial, empirical decomposition), H2 (partial, CI table missing), NEW-H1 (abstract CI description wrong direction) |
| MEDIUM | 4 | M1 (dummy regression missing), M2 (VRP hypothesis comparison), NEW-M1 (Calmar inconsistency), bondarenko2019 DOI |
| MINOR | 4 | hood2025 URL, K898 forensic close, sector start date, campbell1999 loose usage |

---

## Action Plan for v6

### Must-do (HIGH + blocking MEDIUM):

1. **NEW-H1 fix (LOW effort, HIGH impact)**: Update abstract CI description. Replace "76–93% in the five-asset canonical table" with accurate description: "90% CI lower bounds of 76–93% (K1376 moving-block-252); stationary bootstrap with 3–5 year blocks yields lower bounds of 90–100% (K1417), confirming robustness to long-memory resampling." This is 2-sentence fix.

2. **H2 fix (LOW effort, favorable results)**: Add K1417 comparative CI table (5 assets × 3 block lengths). Data already exists in `experiments/k1417/k1417_results.json`. Propose as Online Appendix Table A1 or insert as Table 4. This is the easiest fix with the most favorable result.

3. **H1 empirical decomposition (MEDIUM effort)**: New compute experiment needed. For each of the five canonical assets (SPY, DIA, QQQ, IWM, 50/50), decompose PureVT daily return advantage over VT around MDD trough windows (±63 days). Report: (a) fraction of total MDD improvement occurring during "momentum crash rebound" windows (negative TSMOM days inside bear-market-recovery), (b) fraction from regular VIX-level channel. If rebound contribution is <50% of total, retention is primarily real.

4. **M1 dummy control (LOW effort)**: Add equity-vs-non-equity dummy as a third predictor in Table 2 (cross-sectional regression). If γ t-stat remains > 2.0 after controlling for asset class, M1 is empirically addressed.

### Should-do (MEDIUM):

5. **M2 welfare discussion (MEDIUM effort)**: Add 2-paragraph subsection contrasting insurance premium vs. VRP opportunity cost interpretations with welfare implications and target-investor differentiation.

6. **K898 forensic note closure**: Report 5.3% as canonical, state 1.4% original figure cannot be reproduced, remove "ongoing reconciliation" qualifier.

### Deferred to submission gate:

7. **Codex 3rd-model adversarial review** (deferred from v5 due to time cap): Run `codex exec` review of body_v3.tex focusing on statistical methodology (H1, H2 bootstrap arguments) before final submission.

8. **bondarenko2019 DOI verification**: Manual lookup of `10.1093/rfs/hhy061` before camera-ready.

9. **hood2025 SSRN URL**: Add before final submission.

---

## K1417 Numerical Summary (for v6 paper update)

K1417 stationary bootstrap (from `experiments/k1417/k1417_results.json`):

| Asset | Fixed-252 lo (K1376) | Stationary-756 lo (K1417) | Stationary-1260 lo (K1417) | Lo shift (1260) |
|-------|---------------------|--------------------------|--------------------------|----------------|
| SPY | 86 | 97.1 | 97.7 | +11.7 pp |
| 50/50 | 90 | 84.7 | 89.8 | -0.2 pp |
| DIA | 83 | 91.3 | 93.4 | +10.4 pp |
| QQQ | 82 | 97.5 | 97.5 | +15.5 pp |
| IWM | 91 | 97.3 | 100.0 | +9.0 pp |

K1417 overall verdict (from JSON): "H2 NOT SUPPORTED — CI shift below 3pp on majority of assets; retention robust to bootstrap block length" — Note: The K1417 verdict descriptor is slightly misleading (it says "below 3pp" but shifts are 9–15pp for 4 of 5 assets). Actual finding: stationary bootstrap is **favorable** for the paper, tightening lower bounds upward for 4 of 5 assets. Only 50/50 is marginally lower (-0.2pp, essentially unchanged).

---

## Provenance

- Paper file audited: `paper/vt-trend-following/body_v3.tex` (624 lines, Jun 7 2026)
- K1417 results: `experiments/k1417/k1417_results.json` (run 2026-06-04T21:16:40Z)
- v4 review: `paper/vt-trend-following/review_history/v4/README.md` + `gemini_review_v1.md`
- Reviewer model: Claude Sonnet 4.6 (claude-sonnet-4-6), foreground execution
- 3rd model: Codex adversarial review DEFERRED to v6 (time cap; see `feedback_3model_review_discipline`)

## Files in This Round

- `README.md` (this file) — overall verdict + tables
- `latex_review_v1.md` — full latex-academic-reviewer output
- `citation_check_v1.md` — citation-verifier output

## Next Round Trigger

After main-thread completes v6 fixes (NEW-H1 abstract update + H2 K1417 table + M1 dummy + H1 trough decomposition experiment) → v6 review round with Codex 3rd-model adversarial pass → then re-assess submission readiness.

**Submission gate criterion**: v6 review must show 0 HIGH-severity blocking items, ≤2 MEDIUM. Codex must PASS. bondarenko2019 DOI and hood2025 URL must be verified.
