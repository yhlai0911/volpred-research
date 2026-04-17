# Paper 6 (prg-periodic-garch) Pre-Submission Checklist

**Target journal**: Finance Research Letters (FRL) — confirmed in `main.tex` line 2 and `README.md`
**Current state**: `main.tex` commit `7d35418b` (Eq.(5)-(6) errata defence); v3 of PDF in place (`main.pdf` modified 2026-04-17 23:29); paper README marks status "Near submission-ready (R2 SEVERE=0)"
**Audit date**: 2026-04-17
**Audit agent**: K1221 worktree agent-aab1a22a

---

## Summary Scoreboard

| Category | PASS | FAIL | WARN | N/A | Total |
|----------|------|------|------|-----|-------|
| 1. Data Sources        | 4 | 0 | 2 | 0 | 6 |
| 2. Reproduce Scripts   | 3 | 0 | 1 | 0 | 4 |
| 3. Results             | 3 | 1 | 0 | 0 | 4 |
| 4. Experiment Index    | 2 | 0 | 0 | 0 | 2 |
| 5. README              | 3 | 0 | 0 | 0 | 3 |
| 6. Three-Way Consistency | 1 | 0 | 0 | 1 | 2 |
| 7. Post-7d35418b Extras | 1 | 2 | 0 | 0 | 3 |
| **Total**              | **17** | **3** | **3** | **1** | **24** |

**Readiness**: **NEEDS-MINOR-FIX**. 3 blockers enumerated; all small & localised.
Estimated total remediation: ~2-3 hours main-thread work.

---

## 1. Data Sources

### 1.1 [PASS] `data_sources.md` exists
`paper/prg-periodic-garch/data_sources.md` (1975 bytes, updated 2026-04-17 15:53).

### 1.2 [WARN] No `data/` subfolder
`docs/paper-guide.md` rule 1 accepts `data/` OR `data_sources.md`; this paper
uses the latter. However, journal reviewers often open `data/` first. A
stub `data/README.md` pointing at the 4 data locations would improve UX.
**Remediation**: create `data/README.md` (10 min) OR explicitly mark
`data_sources.md` as "data listing only — raw files in paths below".

### 1.3 [PASS] TAIFEX tick data documented
`data_sources.md` lines 11, 32: `~/Dropbox/TAIFEXDATA/`, not in repo — "too
large". Consistent with FRL's "data available on request" convention.

### 1.4 [PASS] yfinance sources documented
`data_sources.md` lines 12-16 document SPY/QQQ/GLD/EEM/0050.TW with tickers
and periods. Line 46 provides the one-line reproduction command.

### 1.5 [PASS] Sample periods explicit per market
Table 1 in `main.tex` lines 154-161 gives n_oos and OOS period per market.
`data_sources.md` also lists 2010-2026 / 2012-2026 per ticker.

### 1.6 [WARN] No Zenodo / LFS plan for TAIFEX data
The TAIFEX tick raw data is in `~/Dropbox/TAIFEXDATA/`, not the repo. FRL
"data available on request" is acceptable but the package should contain an
explicit statement. **Remediation**: add 2-line note in `data_sources.md`
stating "TAIFEX tick data available upon written request to corresponding
author; alternatively, processed daily session RV is in `experiments/k874/data/`"
(5 min).

---

## 2. Reproduce Scripts

### 2.1 [PASS] `scripts/` folder exists
`paper/prg-periodic-garch/scripts/` contains `README.md`. Per `docs/paper-guide.md`
this is acceptable — the actual scripts live in
`paper/prg-periodic-garch/experiments/*.py` (K874c/K874d/K874e/K880/K880b/
K880v2/K881/K881b/K883/K884/K886).

### 2.2 [PASS] `scripts/README.md` maps K → purpose
`paper/prg-periodic-garch/scripts/README.md` lines 16-27 map each K to its
purpose, plus full reproduction sequence in lines 31-46.

### 2.3 [PASS] `reproduce.py` exists
`paper/prg-periodic-garch/reproduce.py` (5672 bytes) is a one-shot pipeline
running K880v2 + K881 (+ optional K874d), with traceability table and
pass/fail on reference comparison.

### 2.4 [WARN] `reproduce.py` does not pin against canonical K880 (lookahead-defended) numbers
Critical issue: `reproduce.py` line 76 runs `k880v2_prg_fixed.py` as the
"main result", but the paper's Table 2 SPY row uses K880 canonical values
(PRG Ext QLIKE = 0.748, DM = 6.00), as documented in the `7d35418b` errata
commit and defended by K1200. Running `reproduce.py` today will produce
K880v2 values (PRG Ext QLIKE = 0.864, DM = -0.57), which print "OK" against
the `k880v2_results.json` reference but look catastrophically different
from the paper body. A reviewer running `reproduce.py` will be confused.

**Remediation**: change `reproduce.py` to:
(a) run K880 canonical instead of K880v2 for the "main result" comparison, OR
(b) additionally run K1200 and verify it lands in the MINOR_DIVERGENT band
(|ΔQLIKE| < 0.05, |ΔDM_t| < 0.3) against K880 canonical.
Estimated 30 min. See Section 7.1 below for the Appendix A linkage.

---

## 3. Results

### 3.1 [PASS] `results/` directory exists
`paper/prg-periodic-garch/results/` contains `README.md` (2901 bytes,
updated 2026-04-17 15:54) with full Table → JSON mapping.

### 3.2 [PASS] Table → JSON mapping complete
`results/README.md` lines 10-16 maps every Table 1-5 to source JSON. Covers
K874d, K880, K880v2, K880b, K881, K881b, K883, K884, K886.

### 3.3 [PASS] `figures/` directory with soft-links
`paper/prg-periodic-garch/figures/` contains 4 soft-links to
`experiments/k880_charts/*.png` and `experiments/k881_charts/*.png`. Each
main.tex figure reference has a physical target.

### 3.4 [FAIL — BLOCKER] Table 1 0050.TW OOS period mismatch
`main.tex` Table 1 line 160: "2019/12--2026/04". K886 JSON actual:
2021-01-08 → 2026-04-02. `reproducibility_audit/diff_report.md` DIV-2 flags
this. n_oos=1266 matches but date string does not.

**Remediation**: edit `main.tex` line 160 from "2019/12--2026/04" to
"2021/01--2026/04" (1 line). Re-run xelatex × 2. Rerun `paper-update`.
Estimated 15 min including PDF recompile.

---

## 4. Experiment Index

### 4.1 [PASS] `experiments.md` lists all supporting K
`paper/prg-periodic-garch/experiments.md` (3819 bytes, updated 2026-04-17)
lists K874c / K874d / K874e / K880 / K880b / K880v2 / K881 / K881b / K883 /
K884 / K886 with one-line contribution each, plus path pointers.

### 4.2 [PASS] Table/Figure → K mapping present
`experiments.md` lines 49-67 provides Table 1-5 and Figure 1-4 → K mapping.
Consistent with `results/README.md`.

---

## 5. README

### 5.1 [PASS] Paper title + target journal + status
`paper/prg-periodic-garch/README.md` lines 1-4: title, FRL, status "Near
submission-ready (R2 SEVERE=0)", page count (14), citation count (19).

### 5.2 [PASS] Supporting K list
`README.md` lines 39-54 lists all supporting experiments with key results.

### 5.3 [PASS] Data sources summary in README
`README.md` lines 7-10 summarises data sources; delegates details to
`data_sources.md`.

---

## 6. Three-Way Consistency (docs/paper-guide.md 2026-04-17 rule)

### 6.1 [PASS] Scripts produce numbers matching main.tex body (for K881/K874d/K886)
`reproducibility_audit/script_output.json` and `reproducibility_audit/diff_report.md`
confirm that 56/85 paper numbers match source K JSON at rtol ≤ 0.01, and
after the `nosource_rescan_report.md` pass, all "no-source" items except
DIV-2 (Table 1 date) are resolved. Coverage is 90% with 1 blocker remaining
(3.4 above).

For SPY specifically: K880 canonical gives QLIKE = 0.7478 / DM = 6.004 /
Spearman = 0.5678, which matches main.tex Table 2 SPY row exactly
(0.748 / 6.00 / 0.568). `7d35418b` errata + K1200 defensibility confirm this
is the correct source.

### 6.2 [N/A] `reproduce_report.json` existence
Not explicitly created by `reproduce.py`; instead, `reproduce.py` prints
a traceability table to stdout and overwrites JSON in
`paper/prg-periodic-garch/experiments/`. `docs/paper-guide.md` rule allows
either approach. Marked N/A (not required for FRL).

---

## 7. Post-7d35418b Extras (Eq.(5)-(6) errata follow-ups)

### 7.1 [FAIL — BLOCKER] K1218 Appendix A not cherry-picked into main.tex
`experiments/k1218/k1218_appendix_draft.md` exists (7712 bytes) and provides
a full Appendix A explaining the K1200 clean-slate replication as
transcription evidence for Eqs.(5)-(6). `main.tex` commit `7d35418b` contains
the equation-level errata in the body (lines 111-126) but **no \appendix
section, no Appendix A, no reference to K1200 or K1218**.

This is the single highest-ROI submission fix. Without it, the `7d35418b`
errata is an internal decision with no reviewer-visible defence. With it,
a reviewer asking "how do we know Eq.(5)-(6) are faithfully implemented?"
has a one-paragraph cross-reference and a supplementary replication run
showing DM t = 6.128 (vs 6.00 canonical).

**Remediation**:
1. Convert `k1218_appendix_draft.md` to LaTeX (the file already contains
   LaTeX-compatible math, tables, and bibitems in appendix form).
2. Append to `main.tex` before `\end{document}`:
   ```
   \appendix
   \section{Independent Replication of the Two-Phase Forecast Timing}
   \label{app:replication}
   [contents of k1218_appendix_draft.md]
   ```
3. Add one cross-reference sentence at end of Section 4.1 (main.tex around
   line 203, after the MCS paragraph):
   "Appendix~A.3 documents an independent clean-slate replication of the
   SPY results, yielding DM $t=6.13$ against the main-text $6.00$, which
   confirms the transcription of Eqs.~(5)--(6)."
4. Re-run xelatex × 2.
5. `uv run volpred ops paper-update --paper-id paper-6`.

Estimated 45-60 min including table formatting, cross-reference, and
PDF recompile. **This is the critical blocker**.

### 7.2 [PASS] Section 4 cross-reference to two-phase timing sentence (partial)
`main.tex` line 202 already has a note in Table 2 caption referring to
"the two-phase timing convention in Eqs.~(\ref{eq:prg_ov_forecast})--(\ref{eq:prg_fullday})".
This is good. The additional K1200/Appendix A cross-reference (7.1 step 3)
is still required.

### 7.3 [FAIL — BLOCKER] `paper-update` CLI not yet re-run after 7d35418b
`main.pdf` is dated 2026-04-17 23:29 (after commit `7d35418b` 2026-04-17),
so xelatex has run. But `paper-update` status in knowledge.json (K1200 entry
id=972d8402, committed 287de785) does not record a post-errata sync of
paper-6 metadata/PDF to Supabase + Mirror. Check commit history:

  28fc3772 4-hour sync: K1108b capex null + token updates + notifications

No paper-6-specific paper-update commit after `7d35418b`. The live Supabase
paper metadata may still point at the pre-errata version. If the Appendix A
cherry-pick (7.1) happens anyway, a single `paper-update` run covers both.

**Remediation**: run `uv run volpred ops paper-update --paper-id paper-6`
after 7.1 is done. Covers both 7.1 and 7.3 in one step. ~5 min.

---

## Submission Blockers Summary (enumerated)

Three blockers stand between the current state and a clean FRL submission:

| # | Blocker | Remediation | Time |
|---|---------|-------------|------|
| B1 | Table 1 0050.TW OOS date "2019/12" → "2021/01" (main.tex line 160) | Edit main.tex, xelatex ×2 | 15 min |
| B2 | Appendix A (K1200 clean-slate replication) not in main.tex; convert k1218_appendix_draft.md to `\appendix` section + cross-reference sentence in Sec 4.1 | Write LaTeX appendix, xelatex ×2 | 45-60 min |
| B3 | paper-update CLI not re-run since `7d35418b` errata; Supabase metadata may be stale | Run `uv run volpred ops paper-update --paper-id paper-6` | 5 min (covers B1+B2) |

**Total blocker remediation**: ~65-80 minutes

WARN items (polish, non-blocking):
- W1 (10 min): Add `data/README.md` stub pointing at 4 data paths
- W2 (5 min): Add TAIFEX "data on request" clause to `data_sources.md`
- W3 (30 min): Update `reproduce.py` to run K880 canonical (not K880v2) OR add K1200 defensibility-band check

**Total with polish**: ~2-3 hours main-thread work

---

## Paper Body Numbers Verification (verbatim sanity check)

Spot-check 10 numbers from main.tex against the JSON source:

| # | Location | main.tex value | JSON source | JSON value | Match |
|---|----------|----------------|-------------|------------|-------|
| 1 | Abstract line 40: "4.26 to 6.63" | 4.26-6.63 | K881 QQQ (4.26) / EEM (6.63) | 4.257 / 6.629 | PASS |
| 2 | Abstract line 40: "6.00 → -0.57" | 6.00 / -0.57 | K880 / K880v2 | 6.004 / -0.569 | PASS |
| 3 | Table 2 SPY QLIKE | 0.748 | K880 | 0.7478 | PASS |
| 4 | Table 2 TAIFEX QLIKE | 0.198 | K874d | 0.1979 | PASS |
| 5 | Table 2 GLD QLIKE (Basic) | 0.811 | K881 PRG_Basic | 0.8115 | PASS |
| 6 | Table 2 TAIFEX DM vs Sep | -4.07 | K874c PRG_Ext vs Sep | -4.0657 | PASS |
| 7 | Table 2 TAIFEX Spearman | 0.726 | K874d PRG_Ext | 0.72650 | PASS |
| 8 | Table 3 PRG-Ablated QLIKE | 0.864 | K880v2 | 0.8636 | PASS |
| 9 | Table 4 SPY VaR VR% | 0.93 | K880 VaR_1pct | 0.9325% | PASS |
| 10 | Table 5 PRG Ext Sharpe | 1.66 | K874e | 1.6622 | PASS |

**10/10 verbatim match** (within 3-decimal-place rounding). Body numbers are
internally consistent with source JSON; the only paper-body defect is B1
(Table 1 date string, not a number).

---

## Recommendation

Paper 6 is **approximately 80-90% submission-ready**. After completing B1+B2+B3
(~65-80 min), the paper should be ready for FRL submission. W1-W3 are polish
items that improve reviewer experience but are not gating.

The canonical numbers in main.tex body are accurate (10/10 spot-checks) and
the self-contained folder structure (README, experiments.md, data_sources.md,
scripts/README.md, results/README.md, figures/) is compliant with
`docs/paper-guide.md` replication-package hard requirement. The remaining
gaps are the K1218 Appendix A integration (which converts the internal
`7d35418b` errata into reviewer-visible defence), one Table 1 date typo,
and one missing paper-update sync.
