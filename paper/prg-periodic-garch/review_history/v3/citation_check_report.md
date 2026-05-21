# P6 PRG — Citation Review v3

**Date**: 2026-04-27
**Reviewer**: Claude general-purpose (citation-verifier protocol, Opus 4.7 1M)
**Manuscript**: `paper/prg-periodic-garch/main.tex` (v3 post 12-action apply, 459 lines, 20 bibitems)
**Target journal**: Finance Research Letters (FRL)
**v2 baseline**: 0 MAJOR / 1 MED / 3 MINOR (`review_history/v2/citation_check_report.md`)
**v3 fixes applied (per task brief)**: MED-C1 Todorova DOI ✓, Med-3 bibliography alphabetical reorder (Blanc / Harvey1997 swap / Kim / Kupiec four-locus reordering)
**v3 carry pending (per task brief)**: MED-C2 harvey2018, MIN-C1 perchet2016, MIN-C2 danielsson2012, MIN-C3 kyle1985, MIN-C4 cole2017, MIN-C5 Engle-Sokalska 2012, plus Min-4 Hansen-Huang-Shek 2012

---

## Overall Assessment

**Verdict**: ✅ **READY FOR FRL — citation pillar GREEN**

**Severity roll-up**: **0 MAJOR** / **0 MEDIUM** / **1 MINOR (carry-over, optional)**

**Total citations**: 20 bibitems · all 20 in-text `\cite{}` / `\citet{}` / `\citealp{}` resolve to a matching bibitem (0 orphan, 0 missing). No new in-text cite added since v2; +0 net.

**Headline**: The single MED-blocker in v2 (Todorova 2014 DOI) is resolved. The bibliography is now fully alphabetical (A–T) and APA-format compliant. The 5 "carry-over" items listed in the v3 task brief (`harvey2018`, `perchet2016`, `danielsson2012`, `kyle1985`, `cole2017`) **do not exist in the v1 or v2 review trail for this paper** — they appear to be misattributed from a different paper's pending list. The PRG paper has never cited any of those keys and there is no MED-C2 / MIN-C1–C4 in either v1 or v2 review documents (only MIN-C1 alphabetical-order, MIN-C2 Engle–Sokalska add, MIN-C3 Acerbi page format). Treating those 5 as N/A.

---

## v2 → v3 Fix Verification

### MED-C1 Todorova 2014 DOI — RESOLVED ✓

**Bibitem L451–455 (current)**:
```latex
\bibitem[Todorova and Soucek(2014)]{Todorova2014}
Todorova, N. and Soucek, M. (2014).
\newblock Overnight information flow and realized volatility forecasting.
\newblock \emph{Finance Research Letters}, 11(4), 420--428.
\newblock \doi{10.1016/j.frl.2014.07.001}.
```

**DOI live-verification**: WebFetch via `https://doi.org/10.1016/j.frl.2014.07.001` redirects 302 to `linkinghub.elsevier.com/retrieve/pii/S1544612314000348` (active Elsevier resolution). WebSearch independently confirms paper title "Overnight information flow and realized volatility forecasting" by Todorova & Souček, *Finance Research Letters* 11(4), 420–428. **Bibliographic match: 100%** (authors, title, journal, volume, issue, pages all correct). **Status: RESOLVED ✓**

**Note on macro choice**: The bibitem uses `\doi{...}.` rather than `\newblock \url{https://doi.org/...}` (the convention used by all 16 other DOI-bearing bibitems in the same file). With `\bibliographystyle{apalike}` and no explicit `\newcommand{\doi}{...}` definition or `doi` package loaded in the preamble, `\doi{}` is **undefined** and will compile only via `natbib`'s built-in fallback (which renders the argument as plain text without an active hyperlink). For visual / hyperlink consistency with the other 16 bibitems, recommend changing to:
```latex
\newblock \url{https://doi.org/10.1016/j.frl.2014.07.001}
```
This is **cosmetic / sub-MINOR** — does not block submission, but worth a 30-second consistency edit. Classified as **MIN-C1 (new)** below.

### Med-3 Bibliography Alphabetical — RESOLVED ✓

**v3 bibitem order (verified via `grep -n "bibitem" main.tex`)**:

| # | Key | Line | Author surname / sort key |
|---|---|---|---|
| 1 | Acerbi2014 | 337 | Acerbi |
| 2 | Blanc2014 | 342 | Blanc |
| 3 | Bollerslev1996 | 348 | Bollerslev |
| 4 | Christoffersen1998 | 354 | Christoffersen |
| 5 | Corsi2009 | 360 | Corsi |
| 6 | Diebold1995 | 366 | Diebold |
| 7 | Fissler2016 | 372 | Fissler |
| 8 | Glosten1993 | 378 | Glosten |
| 9 | Haas2004 | 384 | Haas |
| 10 | Hansen2005 | 390 | Hansen, P.R. (2005) |
| 11 | Hansen2011MCS | 396 | Hansen, P.R. (2011) |
| 12 | Harvey1997 | 402 | Harvey, D. (1997) |
| 13 | Harvey2016 | 408 | Harvey, C.R. (2016) |
| 14 | Kim2023 | 414 | Kim |
| 15 | Kupiec1995 | 420 | Kupiec |
| 16 | Lai2024 | 426 | Lai |
| 17 | Linton2020 | 433 | Linton |
| 18 | Opschoor2021 | 439 | Opschoor |
| 19 | Patton2011 | 445 | Patton |
| 20 | Todorova2014 | 451 | Todorova |

**Verdict**: ✓ **Strictly alphabetical by surname**. The 4 reorder loci flagged in the task brief (Blanc, Harvey1997↔Harvey2016 swap, Kim, Kupiec) are all correctly positioned:
- Blanc (#2) correctly between Acerbi (#1) and Bollerslev (#3) — moved up from v2's L342–344 chronological-by-appearance slot.
- Harvey1997 (#12) precedes Harvey2016 (#13) — correct: same surname H-cluster, sorted by first author's first name initial (D < C), but since both start "Harvey", the secondary sort follows the publication-year convention used by `apalike` (1997 < 2016). ✓
- Kim2023 (#14) correctly between Harvey (#13) and Kupiec (#15).
- Kupiec1995 (#15) correctly between Kim (#14) and Lai (#16) — moved up from the v2 L408 slot.

**One minor sort-key sub-issue**: For the same surname `Harvey`, APA 7 strict ordering uses the first **author's first initial** as secondary sort. Harvey1997 lists `Harvey, D. (David)` and Harvey2016 lists `Harvey, C. (Campbell)` — under strict APA 7, "C" sorts before "D", so `Harvey2016` should arguably precede `Harvey1997`. However, `\bibliographystyle{apalike}` uses **year as secondary sort** (oldest first) when surnames match, which gives the current order (1997 → 2016). This is an `apalike`-vs-strict-APA-7 stylistic choice; both are acceptable, FRL accepts either. **Non-issue.**

---

## v2 Carry-over Status (5 task-brief items)

| Item (per task brief) | Status in v1/v2 review docs | v3 verdict |
|---|---|---|
| MED-C2 harvey2018 DOI | **Not present in v1 or v2 review.** No `harvey2018` cite key exists in `main.tex` (grep confirms). The only Harvey-cite keys are `Harvey1997` (Harvey-Leybourne-Newbold IJF) and `Harvey2016` (Harvey-Liu-Zhu RFS). | **N/A** — no such issue to carry. |
| MIN-C1 perchet2016 cite-key | **Not present in v1 or v2 review.** No `perchet2016` cite key in `main.tex`. | **N/A** |
| MIN-C2 danielsson2012 | **Not present in v1 or v2 review.** No `danielsson2012` in `main.tex`. | **N/A** |
| MIN-C3 kyle1985 | **Not present in v1 or v2 review.** No `kyle1985` in `main.tex`. | **N/A** |
| MIN-C4 cole2017 | **Not present in v1 or v2 review.** No `cole2017` in `main.tex`. | **N/A** |
| MIN-C5 Engle–Sokalska 2012 (optional pre-empt) | v2 MIN-C2 — recommend adding as intraday-periodic-GARCH precursor at L59. | **Still optional, still not added.** Non-blocking. See "Open MINOR" below. |

**Interpretation**: The task brief's "5 carry-over pending" list (`harvey2018` / `perchet2016` / `danielsson2012` / `kyle1985` / `cole2017`) appears to have been imported from a different paper's review trail (possibly P5 vt-trend-following or P10's risk-management section). For P6 PRG, the only true v2 carry-over is **MIN-C2 Engle–Sokalska 2012** (optional, non-blocking) and **MIN-C3 Acerbi page format** (cosmetic). Both remain in the same status as v2 — neither was actioned, neither is required for FRL submission.

---

## New v3 Items

### Min-4 Hansen-Huang-Shek 2012 cite + bibitem — N/A (not needed)

**Task brief claim**: "Min-4 (新): Hansen-Huang-Shek 2012 cite + bibitem 待補 — DOI 預估 `10.1002/jae.1234`."

**Web verification of DOI**: WebSearch confirms `10.1002/jae.1234` resolves to "Realized GARCH: a joint model for returns and realized measures of volatility," Hansen, P.R., Huang, Z., & Shek, H.H., *Journal of Applied Econometrics* 27(6), 877–906 (2012). DOI is **valid and active** ([Wiley Online Library](https://onlinelibrary.wiley.com/doi/abs/10.1002/jae.1234)).

**However**: A grep of `main.tex` for `Hansen2012`, `Huang`, `Shek`, `RealizedGARCH`, `Realized GARCH` (substring) returns **zero matches in body text or in cite keys**. The Realized GARCH framework is **not invoked anywhere** in the PRG manuscript:
- The model name "Realized GARCH" appears only in the paper title `Periodic Realized GARCH`. The PRG paper does not extend / build on / compare against Hansen–Huang–Shek's Realized GARCH model.
- The benchmarks are GJR-GARCH (close-to-close), HAR, Separate GJR, and GJR-X. None of these are Hansen2012-RG variants.
- The conceptual hook in the title is to **realized variance proxies** (5-min RV for TAIFEX, squared returns for OHLC markets), not to the joint-model Realized GARCH framework of Hansen–Huang–Shek 2012.

**Verdict**: Adding a Hansen2012 cite is **not required**. The paper title naming convention "Periodic Realized GARCH" refers to the use of realized-variance proxies in a periodic GARCH structure, not to Hansen–Huang–Shek's joint-model framework. **However**, if the author wants to pre-empt a referee comment of the form "the title says Realized GARCH but you don't cite Hansen et al. 2012," a one-sentence acknowledgment in §2.2 would suffice — e.g., "The label *Realized* in PRG refers to the use of realized-variance proxies $x_n$, distinct from the joint return-RV framework of \citet{Hansen2012RG}." Optional pre-emptive add, **not blocking**. Logged as **MIN-C2 (new, optional)** below.

### Did v3 add any new in-text cite? — No

`grep -nP "\\\\cite[a-z]*\\{[^}]+\\}"` on v3 main.tex extracts the same 20 unique cite keys present in v2. No new cite added. No abstract-level change introduced new keys (the abstract's `\citet{Harvey2016}` was already cited in v2).

---

## Issues (v3)

### MAJOR (0)
None.

### MEDIUM (0)
None. v2 MED-C1 (Todorova DOI) resolved.

### MINOR (1 actionable + 2 carry-over optional)

#### MIN-C1 (new, cosmetic) — Todorova bibitem uses `\doi{}` macro; other 16 use `\url{}`

**Location**: bibitem L455.

**Current**:
```latex
\newblock \doi{10.1016/j.frl.2014.07.001}.
```

**All 16 other DOI-bearing bibitems use**:
```latex
\newblock \url{https://doi.org/10.xxxx/xxxxx}
```

**Issue**: `\doi{}` is **undefined** under `\bibliographystyle{apalike}` + the current preamble (no `doi` package loaded, no `\newcommand{\doi}`). PDF will compile (via natbib fallback rendering arg as text) but the result is an inactive plain-text DOI without a clickable hyperlink — visually inconsistent with the other 16 bibitems that produce active blue/black hyperlinks.

**Fix** (~30 seconds):
```latex
\newblock \url{https://doi.org/10.1016/j.frl.2014.07.001}
```

**Severity**: MINOR (cosmetic / hyperlink-activity only). Non-blocking for FRL — the DOI text is correct and human-readable. But low-cost consistency fix recommended for v4 final-proof pass.

#### MIN-C2 (carry-over optional from v2 MIN-C2) — Engle & Sokalska 2012 add at L59

Same recommendation as v2: add a one-line acknowledgment of `Engle2012` (multiplicative-component intraday GARCH) at L59 to pre-empt the most-likely "missing intraday-periodic-GARCH precursor" referee comment. DOI: `10.1093/jjfinec/nbr005`. Suggested edit (optional, ~2 min):

> "\citet{Engle2012} decompose intraday volatility into multiplicative daily, diurnal, and stochastic components."

Non-blocking; v3 can ship as-is.

#### MIN-C3 (carry-over optional from v2 MIN-C3) — Acerbi2014 page-abbreviation format

Bibitem L337–340 renders *Risk* magazine as "27(11), 76--81." APA 7 accepts both this academic-style and the trade-magazine style "Risk Magazine, November 2014, 76--81." Non-blocking.

#### MIN-C4 (new, optional pre-emptive) — Hansen-Huang-Shek 2012 RG one-sentence disambiguation in §2.2

If the author wants to pre-empt referee confusion about the "Realized GARCH" name in the title vs. Hansen–Huang–Shek's joint-model framework, add a one-sentence note in §2.2 with `\citet{Hansen2012RG}` + bibitem with DOI `10.1002/jae.1234`. **Optional pre-emptive only — referee may not raise the issue if the title's "Realized" is interpreted as referring to realized-variance proxies (which §2.1's RV definitions support).** Not blocking.

---

## NotebookLM Prior Literature Audit (v2 → v3 carry-over)

The v2 audit cleared 2/3 NotebookLM-flagged precursors:
- ✓ `Linton2020` cited and properly differentiated (parsimony claim defensible).
- ✓ `Bollerslev1996` cited and properly differentiated (calendar vs. session periodicity).
- ⚠ Martens et al. (2004) defensible omission (canonical Martens 2004 is long-memory + structural breaks, not session-periodic).

**v3 status: unchanged.** No body-text edits to L59 between v2 and v3 (verified via grep). Audit verdict still **clears for FRL submission**.

---

## Cross-paper Consistency / Coverage

The 20 cited bibitems cover the full methodological chain for a session-boundary volatility-forecasting paper targeting FRL:

| Coverage area | Cited works |
|---|---|
| Periodic GARCH lineage | `Bollerslev1996` (calendar P-GARCH ancestor), `Lai2024` (PRS extension) |
| Session-aware volatility models | `Linton2020` (DCS-EGARCH), `Kim2023` (Overnight GARCH-Itô), `Todorova2014` (overnight RV), `Opschoor2021` (score-driven realized variance), `Blanc2014` (overnight/intraday feedback asymmetry) |
| Benchmark models | `Glosten1993` (GJR), `Corsi2009` (HAR), `Haas2004` (Markov-GARCH estimation difficulty) |
| Forecast evaluation | `Patton2011` (proxy-robust QLIKE), `Hansen2005` (proxy-substitution), `Diebold1995` + `Harvey1997` + `Harvey2016` (DM test + small-sample correction + Harvey threshold), `Hansen2011MCS` (MCS) |
| Risk evaluation | `Kupiec1995` (VaR coverage), `Christoffersen1998` (interval forecasts), `Fissler2016` (FZ joint loss), `Acerbi2014` (ES backtesting) |

**Verdict**: Coverage is **complete for FRL scope**. No gaps in citation backbone for the paper's methodological / empirical claims. The optional pre-emptive adds (Engle–Sokalska, Hansen-Huang-Shek RG) would broaden the prior-literature acknowledgment but are not required to substantiate any claim made in the paper.

---

## Recommendation for v4

### Must-fix (0)
None. Paper is **submission-ready** on the citation dimension.

### Should-fix (1, cosmetic)
- **MIN-C1 (new)**: Replace `\doi{...}.` with `\newblock \url{https://doi.org/10.1016/j.frl.2014.07.001}` at Todorova bibitem L455 for visual consistency with the other 16 DOI-bearing bibitems. ~30-second edit. Recommended at final-proof pass.

### Optional pre-emptive (3, all carry-over)
- MIN-C2: Add Engle–Sokalska 2012 at L59 (intraday-periodic-GARCH precursor).
- MIN-C3: Reformat Acerbi 2014 page rendering (academic vs. trade-magazine style).
- MIN-C4: Add Hansen–Huang–Shek 2012 RG one-sentence disambiguation in §2.2.

None of these are blocking for FRL.

---

## v3 Citation Trajectory

| Round | MAJOR | MED | MINOR | Verdict |
|---|---|---|---|---|
| R1 (2026-04-05) | 0 | 3 | several | ✗ blocked |
| v1 (2026-04-19) | 0 | 1 | 3 | ⚠ revise |
| v2 (2026-04-27) | 0 | 1 | 3 | ⚠ revise |
| **v3 (2026-04-27)** | **0** | **0** | **1 (cosmetic) + 3 optional** | **✅ READY for FRL** |

---

## 6-criteria Gate (citation dimension)

Per `feedback_paper_cross_paper_meta_eval`:

| Criterion | Threshold | v3 status |
|---|---|---|
| 2. Citation rigor | 0 MAJOR + ≤3 MED | ✅ **PASS** (0 MAJOR / 0 MED / 1 cosmetic MINOR) |

**Citation gate: GREEN.**

---

## Reviewer Signature

Reviewer: Claude general-purpose (citation-verifier protocol, Opus 4.7 1M)
Round: v3 canonical
Baseline: supersedes `review_history/v2/citation_check_report.md`
Outstanding: 0 blocking · 1 cosmetic MINOR (Todorova `\doi{}` macro) · 3 optional carry-over MINORs
Web verifications performed: 4 (Todorova 2014 FRL DOI redirect-active confirmation; Todorova 2014 bibliographic spot-check via WebSearch; Hansen–Huang–Shek 2012 JAE DOI confirmation; Harvey 2018 keyword search to confirm no `harvey2018` cite key exists in this paper)
Web verification failures (paywall 403): 1 (ScienceDirect S1544612314000348 direct fetch — handled via redirect resolver + WebSearch fallback; no INCONCLUSIVE classifications)
Task-brief carry-over discrepancy: 5 of 6 listed "v2 carry-over" items (`harvey2018`, `perchet2016`, `danielsson2012`, `kyle1985`, `cole2017`) do not exist in v1 or v2 review trail for this paper — flagged as N/A and likely misattributed from a different manuscript's pending list.
