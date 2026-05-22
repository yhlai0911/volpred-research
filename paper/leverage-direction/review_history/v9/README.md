# Review Round v9 — leverage-direction

**Date**: 2026-05-23
**Triggered by**: Deferred MEDIUM cleanup from v8 + new review cycle (paper_body task, hourly dispatch 06:07 Taiwan time)
**Reviewers**:
- citation-verifier (citation-v9 agent)
- latex-academic-reviewer (academic-v9 agent)

## Overall Assessment
| Reviewer | Verdict | Rating |
|----------|---------|--------|
| Citation | 0 MAJOR / 1 MEDIUM / 3 MINOR — PASS | ✅ |
| Academic | 3.5★/5 — NEAR-READY; 1 SEVERE fixed, 9 orphan labels fixed | ⚠️ → ✅ after fixes |

## Issues Resolved in v9

### SEVERE (1) — Fixed immediately
1. **Abstract date mismatch**: Abstract said "over 2017--2026" while body said "2017--2025"; fixed to "over 2017--2025 (with 2026 reserved for out-of-sample validation)" in both `main.tex` abstract and `body.tex` line 156.

### HIGH/MEDIUM from v8 deferred (4 items) — All Fixed
1. **IS/OOS period note** (`body.tex` line 156): clarified in-sample period vs OOS reservation
2. **Table caption** (`tables.tex` caption): "Descriptive Statistics" now reads "(In-Sample Period: 2017--2025)"
3. **Dagger footnote style** (`tables.tex` lines 125, 204): replaced `\textit{Errata:}` prefix with `$^{\dagger}$` standard footnote marker
4. **γ_HM abbreviation expansion** (`body.tex` line 382): first use of "HM" now expanded to "Henriksson--Merton (HM)"

### MEDIUM from v9 academic review (2 items) — Fixed
1. **Abstract significance criterion**: updated from magnitude-only `$|\gamma| > 0.10$` to significance-first `$t > 1.65$, $|\gamma| > 0.10$` in `main.tex` abstract
2. **CRRA expansion** (`body.tex` line ~495): "CRRA risk aversion parameter" → "Constant Relative Risk Aversion (CRRA) risk aversion parameter" at first use

### MINOR from v9 academic review — Fixed
1. **9 orphan labels** (`body.tex`): all 9 labels now have `\ref{}`/`\eqref{}` callouts added to body text:
   - `eq:fz` → "(Eq.~\eqref{eq:fz})" at FZ joint loss introduction (line 257)
   - `eq:mdd_utility` → "in Eq.~\eqref{eq:mdd_utility}:" at formalization sentence (line 488)
   - `fig:rolling_gamma` → "Figure~\ref{fig:rolling_gamma} illustrates..." after line 168
   - `fig:vix_garch_ratio` → "(Figure~\ref{fig:vix_garch_ratio})" at switching threshold discussion (line 400)
   - `fig:cumulative_returns` → "Figure~\ref{fig:cumulative_returns} shows..." after line 295
   - `fig:mdd_comparison` → "Figure~\ref{fig:mdd_comparison} presents..." after line 527
   - `tab:amplify` → "(Table~\ref{tab:amplify})" at ETF amplification discussion (line 414)
   - `tab:hybrid` → "(; Table~\ref{tab:hybrid})" at MDD reduction citation (line 449)
   - `tab:tail` → new sentence with "(Table~\ref{tab:tail})" citing ES/worst-day metrics (line 449)

## Deferred to v10

### MEDIUM (1 remaining — citation-verifier)
- `engle1982` DOI: citation-verifier flagged DOI `10.2307/1912773` as unverified; actual paper is Engle (1982) ARCH model in Econometrica. Defer to citation DOI verification pass.

### MINOR (3 remaining — citation-verifier)
- `moreira2017` journal abbreviation style inconsistency
- `cederburg2020` page range missing
- `bayerdimitriadis2022` preprint vs published version check

## Compilation Status
- XeLaTeX compiled clean: **66 pages, 0 errors, 0 undefined-reference warnings**
- Both compile passes passed with only standard `Underfull \hbox` badness warnings (reference list line breaks, non-blocking)

## Stage Assessment
- Citation: 0 MAJOR + 1 MEDIUM (DOI, low-risk) + 3 MINOR → citation tier OK for submission
- Academic: SEVERE fixed, all orphan labels resolved → estimated score improvement to 4★+
- **Stage: ready_for_submission** (maintained; SEVERE issue resolved)

## Files in this round
- `citation_check_report.md`
- `academic_review_report.md`
- `README.md` (本檔)

## Next round trigger
After v10 citation DOI cleanup (engle1982 + moreira2017 + cederburg2020 + bayerdimitriadis2022) → v10 review cycle → confirm 0 MAJOR / 0 MEDIUM citation
