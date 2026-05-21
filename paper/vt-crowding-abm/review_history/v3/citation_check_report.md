# P5 vt-crowding-abm — Citation Verification v3

**Date**: 2026-04-28
**Reviewer**: Claude Opus 4.7 (1M ctx) acting as `citation-verifier`
**Manuscript**: `paper/vt-crowding-abm/main.tex` (v3 reframe; 23 pages, 496 LaTeX lines)
**Target journal**: Finance Research Letters (FRL)
**v2 baseline**: 16 cites checked, 0 MAJOR / 2 MED / 5 MINOR
**v3 delta**: +5 new bibitems (`moskowitz2012`, `asness2013`, `lehmann1990`, `lo1990`, `cont2000`); v1/v2 carry-over 13 cites untouched

---

## Overall Assessment

**Verdict**: **revise (NOT submit-ready)** — All 5 v3-new bibitems verified clean (correct DOIs, correct authors, correct journal/volume/pages). All 5 in-text claims accurately reflect the cited papers' findings. Quoted-fact verification on TSMOM scope, Lehmann-1990 weekly contrarian, Lo-MacKinlay lead-lag, and Cont-Bouchaud stylized facts all pass. **However**, **4 of 5 v2 carry-over MINOR/MED issues remain unfixed** in v3 main.tex despite v2 README explicitly listing them as v3 main-thread blockers — this is a process-discipline gap, not a v3-content gap. Detail in §"v2 Carry-Over Audit".

**Issue counts**:
- **0 MAJOR** (no fabrication, wrong DOI, wrong author, wrong journal)
- **1 MED** (v2 carry-over `harvey2018` DOI gap, NOT FIXED — was on v2 v3-blocker list)
- **5 MINOR** (4 v2 carry-over NOT FIXED + 1 new v3 minor)

**Total citations checked**: **21** (13 v1-baseline + 3 v2-new [`barroso2021`, `cederburg2020`, `liu2019`] + 5 v3-new)

| Category | v1 | v2 | v3 | Δ vs v2 |
|---|---|---|---|---|
| `\bibitem` keys | 13 | 16 | 21 | +5 |
| `\cite*` body keys (unique) | 13 | 16 | 21 | +5 |
| Orphan bib | 0 | 0 | 0 | — |
| Phantom cite | 0 | 0 | 0 | — |

**Block submission?** **YES** until `harvey2018` DOI is added (consistency MED, was already promoted in v2). The 5 v3-new bibitems are clean enough to ship; the 4 carry-over MINORs are not blocking individually but their aggregate "v3 polished v2 known issues" reading hurts FRL submission optics.

---

## Section A — v3 New Bibitems Verification (5 entries)

All 5 v3-new entries verified end-to-end via WebSearch (DOI resolution, journal metadata, volume/issue/page, author roster).

### A.1 `moskowitz2012` (lines 463–467)

| Field | Bib value | Verified |
|---|---|---|
| Authors | Moskowitz, T.~J., Ooi, Y.~H., and Pedersen, L.~H. | ✅ Tobias J. Moskowitz, Yao Hua Ooi, Lasse Heje Pedersen |
| Title | Time series momentum | ✅ exact |
| Journal | *Journal of Financial Economics* | ✅ |
| Vol/Issue | 104(2) | ✅ |
| Pages | 228--250 | ✅ |
| DOI | `10.1016/j.jfineco.2011.11.003` | ✅ resolves to ScienceDirect S0304405X11002613 |

**APA format**: ✅ author + initials + year + italic journal + volume(issue) + pp + DOI as `\url{}`. Identical pattern to v2-fixed entries.

**In-text usage**:
- **Line 54**: "trend-following \citep{moskowitz2012, asness2013}" — appropriate; both are foundational TSMOM/CSMOM references for trend-strategy literature
- **Line 88**: "...one-month time-series momentum at intermediate scaling consistent with cross-asset CTA practice \citep{moskowitz2012}" — accurate; M-O-P (2012) explicitly documents 1- to 12-month TSMOM persistence across 58 liquid instruments (equity index, currency, commodity, bond futures), and the paper's headline diversified TSMOM strategy is exactly what cross-asset CTA practice is calibrated against. Citation supports the modeling-baseline rationale (paragraph defends `s = 10`, `W = 22` choice).

**Cross-strategy distinction check**: P5 uses `moskowitz2012` for **time-series** momentum (single-asset own-return predictor), which is correct. The classical cross-sectional momentum citation (Jegadeesh-Titman 1993) is **not** used in P5 — and correctly so, because the ABM operates on a single asset, so cross-sectional momentum is not the natural reference. This is the right citation choice. ✅

### A.2 `asness2013` (lines 469–473)

| Field | Bib value | Verified |
|---|---|---|
| Authors | Asness, C.~S., Moskowitz, T.~J., and Pedersen, L.~H. | ✅ Clifford S. Asness, Tobias J. Moskowitz, Lasse Heje Pedersen |
| Title | Value and momentum everywhere | ✅ exact |
| Journal | *Journal of Finance* | ✅ |
| Vol/Issue | 68(3) | ✅ June 2013 |
| Pages | 929--985 | ✅ |
| DOI | `10.1111/jofi.12021` | ✅ resolves to Wiley Online Library |

**APA format**: ✅

**In-text usage**:
- **Line 54 only**: "trend-following \citep{moskowitz2012, asness2013}" — Adequate as a co-citation for the cross-asset momentum literature. Asness-Moskowitz-Pedersen (2013) documents value AND momentum jointly across 8 markets/asset classes, with momentum as one of the two factors. The citation is **slightly broader than ideal** — a stricter reading would prefer `moskowitz2012` alone (pure TSMOM) or pair with a CSMOM-specific reference (Jegadeesh-Titman 1993, *JF* 48(1)). But for a single in-text co-citation establishing "trend-following exists as a documented academic strategy," `asness2013` is defensible.

**Quoted-fact accuracy**: P5 line 54 only uses `asness2013` as parenthetical citation for "trend-following" alongside `moskowitz2012`; no specific claim from `asness2013` is asserted. ✅ (no mischaracterization risk)

### A.3 `lehmann1990` (lines 475–479)

| Field | Bib value | Verified |
|---|---|---|
| Authors | Lehmann, B.~N. | ✅ Bruce N. Lehmann |
| Title | Fads, martingales, and market efficiency | ✅ exact |
| Journal | *Quarterly Journal of Economics* | ✅ |
| Vol/Issue | 105(1) | ✅ Feb 1990 |
| Pages | 1--28 | ✅ |
| DOI | `10.2307/2937816` | ✅ resolves to OUP/JSTOR |

**APA format**: ✅

**In-text usage**:
- **Line 54**: "short-horizon mean-reversion \citep{lehmann1990, lo1990}" — appropriate co-citation
- **Line 93**: "The negative coefficient captures the short-horizon reversal documented by \citet{lehmann1990} and \citet{lo1990}" — accurate. Lehmann (1990) documents that "winners" and "losers" one week experience sizeable return reversals the next week, with apparent arbitrage profits surviving bid-ask and transaction-cost corrections. P5's MR rule (sign-flipped 22-day momentum) is in the same family as Lehmann's weekly contrarian profits. The W=22 day window is **longer** than Lehmann's 1-week window, but P5's robustness sweep includes W ∈ {10, 22, 60} and the strategy's "short-horizon mean-reversion" framing is honest. ✅

### A.4 `lo1990` (lines 481–485)

| Field | Bib value | Verified |
|---|---|---|
| Authors | Lo, A.~W. and MacKinlay, A.~C. | ✅ Andrew W. Lo, A. Craig MacKinlay |
| Title | When are contrarian profits due to stock market overreaction? | ✅ exact |
| Journal | *Review of Financial Studies* | ✅ |
| Vol/Issue | 3(2) | ✅ April 1990 |
| Pages | 175--205 | ✅ |
| DOI | `10.1093/rfs/3.2.175` | ✅ resolves to OUP |

**APA format**: ✅

**In-text usage**:
- **Lines 54, 93** (paired with `lehmann1990`)
- Lo-MacKinlay (1990) shows contrarian profits can arise even with temporally independent individual security returns — driven by **cross-autocovariances** (large stocks lead small stocks), **not** purely overreaction. This is a slightly different mechanism than Lehmann's weekly reversal.
- P5's framing ("short-horizon reversal documented by") is **broad enough** to encompass both papers without overstating. ✅
- **Note**: P5 does NOT claim "lead-lag effects drive contrarian profits" specifically (which would be the Lo-MacKinlay headline) — the citation is at "short-horizon reversal" level, which is appropriate for both. No mischaracterization. The task brief's question "is the cite about lead-lag effects?" — answer: P5 cites Lo-MacKinlay for the **existence** of short-horizon contrarian profits, not for the lead-lag mechanism specifically. This is accurate to both papers' overlap.

### A.5 `cont2000` (lines 487–491)

| Field | Bib value | Verified |
|---|---|---|
| Authors | Cont, R. and Bouchaud, J.-P. | ✅ Rama Cont, Jean-Philippe Bouchaud |
| Title | Herd behavior and aggregate fluctuations in financial markets | ✅ exact |
| Journal | *Macroeconomic Dynamics* | ✅ |
| Vol/Issue | 4(2) | ✅ June 2000 |
| Pages | 170--196 | ✅ |
| DOI | `10.1017/S1365100500015029` | ✅ resolves to Cambridge Core |

**APA format**: ✅

**In-text usage**:
- **Line 56 only**: "\citet{cont2000} build an agent-based herd-behavior model in which correlated demand generates fat-tailed returns" — accurate. Cont-Bouchaud (2000) presents a stock-market model where random communication structure between agents generates heavy tails in price variations (exponentially truncated power law); the paper explicitly links **excess kurtosis** in returns to **herding/imitation** behavior of market participants.
- **Quoted-fact verification**: Task brief asked whether the cite is about "fat-tailed returns + volatility clustering stylized facts." Cont-Bouchaud (2000) **does** establish heavy-tailed returns from herd behavior, but **volatility clustering** is *not* the focus of this paper specifically — that is the broader stylized-facts canon (Cont 2001 *Quant. Finance*, or Mandelbrot 1963 / Fama 1965 for the original heavy-tail observation). P5 line 56 only claims "fat-tailed returns" (correct), not volatility clustering — so the citation matches the claim. ✅

**Cross-strategy critique check (knife-edge §5.4)**: Task brief asked whether `cont2000` is the right citation for §5.4 knife-edge rebuttal — **answer**: `cont2000` is **NOT cited in §5.4 knife-edge rebuttal**. It only appears at line 56 (literature review). §5.4 (lines 350–359) cites only `kyle1985` (via Eq.~(\ref{eq:price})) and uses the model's own falsifiability anchor (NoiseControl) — no external stylized-facts citation needed. **The brief's hypothetical "should it be replaced by mandelbrot1963 / fama1965?" is moot** — `cont2000` is correctly placed at the lit-review level, and the knife-edge rebuttal correctly leans on Kyle-impact mechanism + NoiseControl rather than stylized-facts citations.

---

## Section B — v2 Carry-Over Audit

v2 README listed these as **v3 main-thread blockers** (≤30-min batch fixes). v3 main.tex status:

| v2 issue | Severity | v3 line(s) | Status | Detail |
|---|---|---|---|---|
| MED-1 `barroso2021` mischaracterization | MED | 58 | ✅ **FIXED** | v3 reworded: "while \citet{barroso2021} find that volatility-managed market portfolios survive transaction costs in directions opposite to those questioned by \citet{cederburg2020}" — correctly captures partial-defense reading per v2 fix option (1) |
| MED-2 `harvey2018` DOI missing | MED | 421–424 | ❌ **NOT FIXED** | v3 bib still lacks `\url{https://doi.org/10.3905/jpm.2018.45.1.014}` after `Vol. 45(1), 14--33.` — gap conspicuous given moreira2017/brunnermeier2009/harvey2016/barroso2021/cederburg2020/liu2019 all have DOIs adjacent in same bibliography |
| MIN-1 `perchet2016` cite-key vs year 2015 | MINOR | 76, 437–440 | ❌ **NOT FIXED** | Cite-key still `perchet2016`, bib still renders "(2015)". 5-second rename pending |
| MIN-2 `danielsson2012` characterized as ABM | MINOR | 56 | ⚠️ **partially mitigated** | v3 reframes from v2 "ABMs have proven effective" to "while \citet{lebaron2006} and \citet{danielsson2012} study feedback-driven market dynamics" — drops the "ABM" assertion specifically applied to Danielsson, so the literal claim is now defensible. ABM is now only attributed to `bookstaber2014`, `lebaron2006`, and `cont2000` (all genuinely ABM). |
| MIN-3 `kyle1985` page 1315--1335 vs canonical 1315--1336 | MINOR | 429 | ❌ **NOT FIXED** | v3 still `1315--1335` |
| MIN-4 `cole2017` no URL | MINOR | 442–445 | ❌ **NOT FIXED** | v3 industry research-report entry still no URL field |
| MIN-5 multi-key `\citet{...,...,...}` rendering | MINOR | 58 | ✅ **FIXED** | v3 splits into separate `\citet{cederburg2020}`, `\citet{liu2019}`, `\citet{barroso2021}` reads cleanly |

**Net carry-over status**: 2/7 fixed (MED-1, MIN-5), 1/7 partially mitigated (MIN-2), **4/7 NOT FIXED** (MED-2, MIN-1, MIN-3, MIN-4).

---

## Section C — v3-Specific In-Text Citation Audit

v3 reframe added/moved citations in §1, §3.1, §4.4 (no §5.4 cite changes), §5.3 limitation 7, §6 conclusion. Cross-checked all citation insertions:

| v3 insertion | Line | Cite | Verdict |
|---|---|---|---|
| §1 lit-review TF/MR refs | 54 | `moskowitz2012`, `asness2013`, `lehmann1990`, `lo1990` | ✅ all 4 appropriate |
| §1 ABM herd model | 56 | `cont2000` | ✅ appropriate (fat-tail herd model, ABM) |
| §1 VT-alpha contestation reframe | 58 | `cederburg2020`, `liu2019`, `barroso2021` | ✅ now correctly disambiguates Barroso-Detzel partial defense |
| §3.1 TF baseline justification | 88 | `moskowitz2012` | ✅ supports `s=10, W=22` ≈ 1-month TSMOM |
| §3.1 MR mechanism citation | 93 | `lehmann1990`, `lo1990` | ✅ appropriate |
| §4.4 cross-strategy ordering | 219–263 | (no new cites; uses internal Tables) | ✅ no new citations introduced |
| §5.3 limitation 7 (TF scaling) | 344 | (no cites) | **MINOR concern** — see below |
| §5.4 knife-edge rebuttal | 350–359 | `kyle1985` only | ✅ no new cites needed |
| §6 conclusion | 366–368 | (no new cites) | ✅ |

### MINOR-NEW (v3): §5.3 Seventh limitation lacks TSMOM-scaling citation

**Location**: line 344, "the TF and MR scaling parameter $s = 10$ used in K1261 Phase~1 and the K1262b OAT cells is an aggressive choice. ... Real-world TF managers' effective scaling is heterogeneous and depends on volatility-of-volatility forecasts and capital-allocation rules"

**Issue**: Task brief asked whether §5.3 needs to cite TSMOM scaling literature. P5 makes a substantive claim about **real-world TF manager scaling heterogeneity** without a citation. Closest available reference would be `moskowitz2012` (already in bib) §IV "Time Series Momentum Factor," which discusses position-sizing by inverse-volatility — but P5 does not cite it here.

**Severity**: MINOR (claim is plausibility-level, not headline-level; an FRL reviewer is unlikely to flag).

**Fix options**:
- (a) Add `\citep{moskowitz2012}` after "...volatility-of-volatility forecasts" on line 344, since the inverse-vol scaling rule used by TSMOM literature is exactly the reference for "effective scaling depends on vol-of-vol forecasts."
- (b) Leave as-is; it is a limitation paragraph, not a result claim. Defensible.

**Suggested fix**: (a), 1-line edit.

---

## Section D — APA Format Cross-Validation

All 5 v3-new bibitems follow the **identical pattern** as v1/v2 entries:

```
\bibitem[<Author>(<Year>)]{<key>}
<Author last>, <Initials> ... (<Year>).
\newblock <Title in lowercase>.
\newblock \emph{<Journal>}, <Vol>(<Issue>), <pp>--<pp>.
\newblock \url{https://doi.org/<DOI>}
```

**Format consistency check**: ✅ all 5 v3-new entries match this pattern byte-identical to v1/v2 cleanups. No format drift.

**Bibliography ordering**: v3 appends 5 new entries at end (lines 463–491) rather than inserting alphabetically. This is acceptable for `plainnat` natbib without alpha-sort, but a minor stylistic concern (FRL accepts both orderings; reviewer unlikely to flag).

---

## Issues Summary

### MAJOR (0)
None. No fabrication, no wrong DOI, no wrong journal, no wrong year, no wrong author across all 21 cites.

### MEDIUM (1)

**MED-1 (carryover from v2 MED-2). `harvey2018` DOI still missing**
- **Location**: lines 421–424
- **Current**: `\emph{Journal of Portfolio Management}, 45(1), 14--33.` (no DOI)
- **Add**: `\newblock \url{https://doi.org/10.3905/jpm.2018.45.1.014}`
- **Rationale**: Adjacent bib entries (moreira2017, brunnermeier2009, harvey2016, barroso2021, cederburg2020, liu2019) all carry DOIs. The single gap on `harvey2018` reads as oversight. Was on v2 v3-blocker list; not addressed.
- **Severity**: MED (consistency + lead-paragraph citation at line 54)
- **Effort**: 30 seconds

### MINOR (5)

**MIN-1 (carryover v2 MIN-1). `perchet2016` cite-key vs displayed year mismatch** — lines 76, 437–440. Rename cite-key to `perchet2015`. Cosmetic.

**MIN-2 (carryover v2 MIN-3). `kyle1985` page range** — line 429. Change `1315--1335` to `1315--1336`. Both variants in widespread use; canonical is 1336.

**MIN-3 (carryover v2 MIN-4). `cole2017` missing URL** — lines 442–445. Add `\url{https://www.artemiscm.com/welcome#research}` or specific PDF link if known stable.

**MIN-4 (NEW v3). §5.3 Seventh limitation TSMOM-scaling claim lacks citation** — line 344. Suggested: append `\citep{moskowitz2012}` after "vol-of-vol forecasts" clause.

**MIN-5 (NEW v3). Bibliography ordering** — v3 appends 5 new entries at end (lines 463–491) rather than alphabetical. `plainnat` accepts both; FRL reviewer unlikely to flag, but final-pass cleanup could re-alphabetize.

---

## Recommendation for v3 → v4 / submission decision

**Main thread MUST fix before submitting v3 to FRL**:
- [ ] **MED-1**: Add `harvey2018` DOI `10.3905/jpm.2018.45.1.014` (was on v2 must-fix list, still missing)

**Strongly recommended (sub-2-min batch)**:
- [ ] MIN-1: rename `perchet2016` → `perchet2015`
- [ ] MIN-2: update `kyle1985` page to `1315--1336`
- [ ] MIN-3: add `cole2017` URL
- [ ] MIN-4: add `\citep{moskowitz2012}` to line 344 §5.3 Seventh limitation

**Aspirational (deferrable to v4 polish)**:
- MIN-5: re-alphabetize bibliography ordering

**Do NOT submit as-is**: Even though no MAJOR issues exist, the unfixed v2 carry-over MED (`harvey2018` DOI gap) is now a 2-round-old known issue. FRL submission with a known unaddressed reviewer-list item undermines the multi-round-review process the user explicitly mandated.

---

## Verdict

**0 MAJOR / 1 MED / 5 MINOR**

**Submission gate**: ❌ **DO NOT submit until MED-1 fixed**. After MED-1 + MIN-1/2/3/4 batch (≤5 min total), bibliography is ready for FRL submission.

**v3 quality vs v2**:
- New v3 cites: ✅ all 5 are clean (DOI/author/journal/pages all verified)
- Quoted-fact accuracy: ✅ all 5 in-text claims faithful to cited papers
- v2 carry-overs: ⚠️ **4/7 NOT FIXED** despite v2 README listing them as v3 main-thread blockers — process discipline gap

**Predicted FRL outcome (after MED-1 + MIN-1/2/3/4 fix)**: bibliography no longer a barrier. The cross-paper meta-evaluation framing concerns flagged in v2 README (designed-vs-emergent, dataset-overlap with portfolio P1-P10) are **outside citation-verifier scope** and are not weighed in this report's verdict.

---

## Verification trail

- v3 5 new bibitems verified via WebSearch 2026-04-28:
  - `moskowitz2012` ⇒ ScienceDirect S0304405X11002613 / IDEAS RePEc v104y2012i2p228-250 / DOI 10.1016/j.jfineco.2011.11.003 ✅
  - `asness2013` ⇒ Wiley OnlineLibrary jofi.12021 / SSRN 2174501 / NYU Stern faculty PDF ✅
  - `lehmann1990` ⇒ OUP qje 105(1):1–28 / NBER w2533 / JSTOR 2937816 ✅
  - `lo1990` ⇒ OUP rfs 3(2):175–205 / NBER 2977 / DOI 10.1093/rfs/3.2.175 ✅
  - `cont2000` ⇒ Cambridge Core macdyn 4(2):170–196 / RePEc cup/macdyn / arXiv cond-mat/9712318 / DOI 10.1017/S1365100500015029 ✅
- v1/v2 carry-over 13 cites: byte-identical to v2 verified state (no regression)
- TSMOM time-series vs cross-section disambiguation: confirmed M-O-P (2012) is the canonical TSMOM (single-asset own-return predictor), distinct from Jegadeesh-Titman (1993) CSMOM. P5's choice is correct.
- Cont-Bouchaud (2000) scope: confirmed paper covers fat-tail herd model (✅ matches P5 line 56 claim) but NOT volatility clustering specifically (would need Cont 2001 Quant. Finance for that — but P5 does not claim VC, so no issue).
