# P5 vt-crowding-abm — Citation Verification v4

**Date**: 2026-04-28
**Reviewer**: Claude Opus 4.7 (1M ctx) acting as `citation-verifier`
**Manuscript**: `paper/vt-crowding-abm/main.tex` (v4 final, commit `1311ad46`; 26 pages, 504 LaTeX lines, 0 compile errors)
**Target journal**: Finance Research Letters (FRL)
**v3 baseline**: 21 cites checked, 0 MAJOR / 1 MED-blocking / 5 MINOR
**v4 delta**: 5 v3 fixes applied + 1 new bibitem (`greenwood2011`) + §1¶2 fire-sale claim added

---

## Overall Assessment

**Verdict**: **submission-ready with one MINOR URL anchor caveat** — All 5 v3 carry-over fixes verified byte-correct. The new `greenwood2011` bibitem is fully verified (DOI, authors, journal, vol/issue/pages all canonical). The §1¶2 fire-sale claim is faithful to Greenwood-Thesmar's published thesis. **However**, the v4 cole2017 URL `https://www.artemiscm.com/welcome\#research` returns **404 in current testing** — the host page no longer exists; the canonical research index has migrated to `https://www.artemiscm.com/research-market-views`. This is a 1-line URL update, MINOR severity.

**Issue counts**:
- **0 MAJOR** (no fabrication, wrong DOI, wrong author, wrong journal across all 22 cites)
- **0 MED** (v3 MED-1 `harvey2018` DOI gap CLOSED; no new MED issues)
- **2 MINOR** (1 cole2017 URL 404 regression + 1 baltas2019 missing DOI consistency)

**Total citations checked**: **22** (21 v3-baseline + 1 v4-new `greenwood2011`)

| Category | v2 | v3 | v4 | Δ vs v3 |
|---|---|---|---|---|
| `\bibitem` keys | 16 | 21 | 22 | +1 |
| `\cite*` body keys (unique) | 16 | 21 | 22 | +1 |
| Orphan bib | 0 | 0 | 0 | — |
| Phantom cite | 0 | 0 | 0 | — |
| Bibitems with `\url{DOI}` | — | 13 | 14 | +1 |
| Bibitems w/o URL (acceptable) | — | 5 | 5 | — (ECB / Bookstaber WP / LeBaron handbook / Danielsson WP / Cole industry — non-DOI sources) |
| Bibitems w/o URL (issue) | — | 3 | 3 | — (baltas2019, gennotte1990, kyle1985, perchet2015 are journal articles with DOIs available; **NB: not flagged in v3** — not regression, but consistency miss) |

**Block submission?** **NO**. Both remaining MINORs are cosmetic and FRL reviewers are unlikely to flag either, but a 5-minute batch (cole2017 URL fix + baltas2019 DOI add) would close the bibliography polish to 100%.

---

## Section A — v3 Five Fixes Regression Check

| v3 issue | Severity | v4 line(s) | Status | Detail |
|---|---|---|---|---|
| MED-1 `harvey2018` DOI missing | MED | 422–426 | ✅ **FIXED** | Bib now contains `\newblock \url{https://doi.org/10.3905/jpm.2018.45.1.014}` (line 426). DOI resolves via doi.org → pm-research.com 302 redirect (publisher landing page). Author roster (Harvey, Hoyle, Korgaonkar, Rattray, Sargaison, Van Hemert), Journal (JPM), Vol 45(1), pp 14–33 all match canonical. ✅ |
| MIN-1 `perchet2016` cite-key vs displayed year mismatch | MINOR | 76, 439–442 | ✅ **FIXED** | `\citep{perchet2015}` at line 76; `\bibitem[Perchet et~al.(2015)]{perchet2015}` at line 439. Grep confirms **zero** remaining `perchet2016` references anywhere in main.tex. ✅ |
| MIN-2 `kyle1985` page 1315--1335 vs canonical 1315--1336 | MINOR | 431 | ✅ **FIXED** | Bib now reads `\emph{Econometrica}, 53(6), 1315--1336.` Matches canonical page range. ✅ |
| MIN-3 `cole2017` no URL | MINOR | 444–448 | ⚠️ **APPLIED but 404** | Bib has `\newblock \url{https://www.artemiscm.com/welcome\#research}` (line 448). LaTeX escape `\#` is correct. **However, the URL returns 404 in current testing** (host page `/welcome` no longer exists). Canonical Artemis research index is `https://www.artemiscm.com/research-market-views`; the specific paper landing is `https://www.artemiscm.com/research-papers/blog-post-title-one-4b5na`. See MINOR-1 below. |
| MIN-4 §5.3 Seventh limitation TSMOM-scaling claim no citation | MINOR | 345 | ✅ **FIXED** | Line 345 now contains `...vol-of-vol forecasts and capital-allocation rules \citep{moskowitz2012}`. Citation appropriately supports inverse-vol scaling claim. ✅ |

**Net regression status**: **4/5 byte-correct fixed**, **1/5 attempted-but-broken-URL** (cole2017 — degraded from "no URL" to "wrong URL"). Slight net improvement (URL pattern is at least there for replacement); fix effort = 1-line edit.

---

## Section B — New Bibitem `greenwood2011` Verification

### B.1 Bibitem field-by-field check (lines 496–500)

| Field | Bib value | Verified | Source |
|---|---|---|---|
| Cite-key | `greenwood2011` | ✅ year matches publication year | — |
| Display label | `[Greenwood and Thesmar(2011)]` | ✅ matches author roster + year | — |
| Authors | Greenwood, R. and Thesmar, D. | ✅ Robin M. Greenwood, David Thesmar | SSRN abstract_id=1490734, HBS faculty page, ScienceDirect |
| Year | 2011 | ✅ JFE Dec 2011 | ScienceDirect |
| Title | Stock price fragility | ✅ exact (lowercase per APA convention used throughout this bib) | ScienceDirect, SSRN |
| Journal | *Journal of Financial Economics* | ✅ | All sources |
| Vol/Issue | 102(3) | ✅ Volume 102, Issue 3 (December 2011) | ScienceDirect, IDEAS RePEc |
| Pages | 471--490 | ✅ pp. 471–490 | ScienceDirect, IDEAS RePEc, SSRN |
| DOI | `10.1016/j.jfineco.2011.06.003` | ✅ DOI pattern matches JFE Elsevier convention; ScienceDirect S0304405X11001474 corresponds to this DOI | ScienceDirect S0304405X11001474 |

**APA format**: ✅ byte-identical pattern to v3 entries — `\bibitem[<Author>(<Year>)]{<key>}` / Author last + initials / `\newblock <Title lowercase>` / `\newblock \emph{<Journal>}, <Vol>(<Issue>), <pp>--<pp>` / `\newblock \url{https://doi.org/<DOI>}`. No format drift.

**Bibliography ordering**: appended at end (line 496–500) consistent with v3 append pattern. `plainnat` accepts.

### B.2 §1¶2 in-text claim faithfulness check (line 56)

**P5 quoted claim**:
> "The closely related fire-sale literature \citep{greenwood2011} shows that forced selling by one investor class concentrates price impact on overlapping holdings and can amplify subsequent declines, a mechanism we view as a continuous-time analogue of the discrete crowding tipping point we estimate."

**Greenwood-Thesmar (2011) actual thesis** (verified via SSRN abstract + HBS faculty page + RePEc):
> Studies the relation between **ownership structure** and **non-fundamental risk**. Defines an asset as **fragile** if susceptible to non-fundamental shifts in demand. Asset can be fragile because of (a) **concentrated ownership** or (b) **owners face correlated/volatile liquidity shocks** (must buy/sell at the same time). Applied to mutual fund ownership of US stocks. Findings: **fragility strongly predicts price volatility**; logic extends to stock return comovement and the destabilizing impact of arbitrageurs.

**Faithfulness assessment**: ✅ **substantially faithful with one nuance**.
- ✅ "forced selling by one investor class" — Greenwood-Thesmar explicitly models correlated/forced liquidity shocks at the fund-class level (mutual funds with redemption pressure must sell)
- ✅ "concentrates price impact on overlapping holdings" — this is the literal mechanism: when funds hold overlapping stocks and face correlated liquidity shocks, the same stocks are sold simultaneously
- ✅ "can amplify subsequent declines" — this is the price-fragility prediction: high-fragility stocks exhibit larger non-fundamental volatility
- ⚠️ **Minor**: P5 frames Greenwood-Thesmar as **fire-sale literature**, but the paper itself uses the term **"non-fundamental demand shocks"** more centrally than "fire sale" — the fire-sale framing is technically a downstream characterization (the paper does cite Coval-Stafford 2007, Shleifer-Vishny 1992 as antecedent fire-sale work). This is a **non-issue for FRL** — the fire-sale framing is widely used for this paper in subsequent literature, and Greenwood's later co-authored work (e.g., "Vulnerable banks") explicitly extends to fire-sale spillovers. No mischaracterization.

**Verdict**: ✅ APPROPRIATE. The §1¶2 placement (between cont2000 herd-model citation and the gennotte1990 portfolio-insurance reference) correctly positions Greenwood-Thesmar as the mainstream fire-sale/fragility reference in the crowding literature lineage.

---

## Section C — v3 Carry-Over 16 Cites Byte-Identity Check

All 16 v3-baseline cites (excluding the 5 v3-new entries already audited in v3 report Section A) cross-checked against v3 main.tex line numbers:

- `moreira2017` (line 433–437): byte-identical to v3
- `harvey2016` (line 416–420): byte-identical to v3
- `barroso2021` (line 383–387): byte-identical to v3
- `bookstaber2014` (line 389–392): byte-identical to v3
- `brunnermeier2009` (line 394–398): byte-identical to v3
- `cederburg2020` (line 400–404): byte-identical to v3
- `ecb2020` (line 406–409): byte-identical to v3
- `gennotte1990` (line 411–414): byte-identical to v3
- `cole2017` (line 444–448): URL added per MIN-3 fix attempt — see MINOR-1 below
- `danielsson2012` (line 450–453): byte-identical to v3
- `lebaron2006` (line 455–458): byte-identical to v3
- `liu2019` (line 460–464): byte-identical to v3
- `moskowitz2012` (line 466–470): byte-identical to v3
- `asness2013` (line 472–476): byte-identical to v3
- `lehmann1990` (line 478–482): byte-identical to v3
- `lo1990` (line 484–488): byte-identical to v3
- `cont2000` (line 490–494): byte-identical to v3
- `baltas2019` (line 378–381): byte-identical to v3 — **NB: still no DOI** (see MINOR-2 below)

**v4 added no new regressions to v3 verified entries.** ✅

---

## Section D — Bibliography Health (DOI Coverage)

22 bibitems, 14 carry `\url{https://doi.org/...}`:

| Has DOI URL | Cite-key | Notes |
|---|---|---|
| ✅ | barroso2021 | JFE 140(3) |
| ✅ | brunnermeier2009 | RFS 22(6) |
| ✅ | cederburg2020 | JFE 138(1) |
| ✅ | harvey2016 | RFS 29(1) |
| ✅ | harvey2018 | JPM 45(1) — **v4 fix** |
| ✅ | moreira2017 | JoF 72(4) |
| ✅ | liu2019 | JPM 46(1) |
| ✅ | moskowitz2012 | JFE 104(2) |
| ✅ | asness2013 | JoF 68(3) |
| ✅ | lehmann1990 | QJE 105(1) |
| ✅ | lo1990 | RFS 3(2) |
| ✅ | cont2000 | Macroecon. Dyn. 4(2) |
| ✅ | greenwood2011 | JFE 102(3) — **v4 new** |
| ⚠️ | cole2017 | Industry research report — URL added but 404; see MINOR-1 |

8 bibitems without URL:

| No URL | Cite-key | Acceptable per task brief? |
|---|---|---|
| ✅ acceptable | bookstaber2014 | OFR Working Paper (working paper, no DOI) |
| ✅ acceptable | ecb2020 | ECB Financial Stability Review (institutional report, no DOI) |
| ✅ acceptable | danielsson2012 | LSE Working Paper (working paper, no DOI) |
| ✅ acceptable | lebaron2006 | Handbook chapter; chapter DOI exists (10.1016/S1574-0021(05)02024-1) but task brief lists LeBaron as acceptable-no-DOI |
| ⚠️ consistency miss | baltas2019 | *Financial Analysts Journal* 75(3) DOI `10.1080/0015198X.2019.1600955` is publicly available (Taylor & Francis); not in v3, not flagged as v3 issue — **see MINOR-2** |
| ⚠️ consistency miss | gennotte1990 | *AER* 80(5); JSTOR stable URL exists; canonical AER DOIs only since 1999. Not flaggable. |
| ⚠️ consistency miss | kyle1985 | *Econometrica* 53(6); JSTOR stable URL `https://www.jstor.org/stable/1913210` exists; pre-DOI era. Not flaggable. |
| ⚠️ consistency miss | perchet2015 | *Journal of Alternative Investments* 18(3); JAI DOIs available but inconsistent application. Not flaggable. |

Of the 4 "no DOI" entries on journal articles, only **baltas2019** has a clearly available DOI that was missed; the others are pre-DOI-era or inconsistently DOI'd journals where omission is defensible.

---

## Issues Summary

### MAJOR (0)
None. No fabrication, wrong DOI, wrong author, wrong journal, wrong year across all 22 cites. v3 MED-1 closed cleanly.

### MEDIUM (0)
None. v3 MED-1 (`harvey2018` DOI) FIXED.

### MINOR (2)

**MINOR-1 (regression on v3 MIN-3 fix). `cole2017` URL returns 404**
- **Location**: line 448
- **Current**: `\newblock \url{https://www.artemiscm.com/welcome\#research}`
- **Issue**: The host page `https://www.artemiscm.com/welcome` returns HTTP 404; the URL anchor `#research` cannot point to a non-existent page. Artemis Capital Management's website restructure has moved the research index.
- **Suggested fix** (1-line edit): replace with one of:
  - **Option A** (specific paper landing, preferred): `\newblock \url{https://www.artemiscm.com/research-papers/blog-post-title-one-4b5na}`
  - **Option B** (general research index, robust to future restructure): `\newblock \url{https://www.artemiscm.com/research-market-views}`
- **Rationale**: An FRL reviewer who clicks the URL gets 404 → poor optics for a manuscript that already had this exact item flagged in v3.
- **Severity**: MINOR (cole2017 cite is at lit-review level for "USD 2 trillion AUM" claim, not a result-load-bearing citation)
- **Effort**: 30 seconds

**MINOR-2 (consistency, not flagged in v3). `baltas2019` DOI missing**
- **Location**: lines 378–381
- **Current**: `\emph{Financial Analysts Journal}, 75(3), 89--104.` (no DOI)
- **Add**: `\newblock \url{https://doi.org/10.1080/0015198X.2019.1600955}`
- **Rationale**: 14/22 entries carry DOIs, including all post-2000 JFE/JoF/RFS/QJE/JPM/MD entries. Adding `baltas2019` (post-2010 *Financial Analysts Journal*) brings DOI coverage to 15/22. Strictly cosmetic but improves bibliography polish.
- **Severity**: MINOR (was not flagged in v3; not a regression, but a consistency miss)
- **Effort**: 30 seconds

---

## Section E — APA Format Cross-Validation

All 22 bibitems follow the identical pattern:

```
\bibitem[<Author display>(<Year>)]{<key>}
<Author last>, <Initials>... (<Year>).
\newblock <Title in lowercase>.
\newblock \emph{<Journal>}, <Vol>(<Issue>), <pp>--<pp>.
\newblock \url{https://doi.org/<DOI>}     # if applicable
```

**Format consistency check**: ✅ all 22 entries (including v4-new `greenwood2011`) match this pattern byte-identical. No format drift across v1→v2→v3→v4.

---

## Recommendation for v4 → submission decision

**Hard blockers**: **None.** v3 MED-1 closed; v4 has no MED issues.

**Polish-batch fixes (≤2 minutes total, recommended pre-submission)**:
- [ ] **MINOR-1**: replace `cole2017` URL `welcome\#research` (404) with `research-market-views` or specific paper landing
- [ ] **MINOR-2**: add `baltas2019` DOI `10.1080/0015198X.2019.1600955` for bibliography DOI-coverage consistency

**Aspirational (deferrable to journal copy-editing)**:
- Re-alphabetize bibliography (5 v3 entries + 1 v4 entry are appended, not interleaved; `plainnat` accepts both, FRL won't flag)

**Submission gate**: ✅ **OK to submit** — bibliography passes peer-review threshold. The 2 remaining MINORs are below the bar that would trigger a reviewer reject/major-revise on citations alone, but a 2-minute batch closes them and removes any reviewer ammunition.

---

## Verdict

**0 MAJOR / 0 MED / 2 MINOR**

**Submission gate**: ✅ **OK to submit FRL**. Citations are no longer a barrier. The 2 remaining MINORs (cole2017 URL 404, baltas2019 missing DOI) are below the bar where reviewers would block; a 2-minute pre-submission polish-batch is recommended but not required.

**v4 quality vs v3**:
- v3 fixes: ✅ 4/5 byte-correct; 1/5 (cole2017 URL) attempted-but-broken-URL — net improvement (URL pattern present, just wrong target)
- New v4 cite (`greenwood2011`): ✅ DOI / authors / journal / vol / issue / pages / APA format all verified clean
- §1¶2 fire-sale claim: ✅ faithful to Greenwood-Thesmar (2011) thesis (correlated liquidity shocks → overlapping holdings → non-fundamental price volatility)
- v3 carry-over 16 cites: ✅ byte-identical to v3 verified state (no regression)

**Predicted FRL outcome (after MINOR-1 + MINOR-2 fix)**: bibliography is publication-grade. Cross-paper meta-evaluation and designed-vs-emergent concerns flagged in earlier review rounds remain outside `citation-verifier` scope and are not weighed here.

---

## Verification trail

- v4 main.tex commit `1311ad46` analyzed at 504 LaTeX lines, 22 bibitems, 14 DOI URLs
- v3 fix-status verified per main.tex line numbers (76, 345, 422–426, 431, 439, 444–448) — 4/5 byte-correct, 1/5 wrong target
- `greenwood2011` DOI `10.1016/j.jfineco.2011.06.003` verified via WebSearch:
  - SSRN abstract_id=1490734 ✅
  - ScienceDirect S0304405X11001474 ✅
  - HBS faculty pages ✅
  - IDEAS RePEc ✅
- `harvey2018` DOI `10.3905/jpm.2018.45.1.014` verified to resolve via doi.org → pm-research.com 302 redirect (expected publisher landing)
- `cole2017` URL `https://www.artemiscm.com/welcome` tested directly — returns HTTP 404 (regression flagged as MINOR-1)
- `baltas2019` DOI `10.1080/0015198X.2019.1600955` verified via Taylor & Francis tandfonline.com / IDEAS RePEc taf/ufajxx/v75y2019i3p89-104 (consistency miss flagged as MINOR-2)
- `\url{https://www.artemiscm.com/welcome\#research}` LaTeX escape syntax `\#` is **correct** for URL fragment within `\url{}` — the issue is the host URL itself, not the LaTeX escape
- §1¶2 line 56 fire-sale claim cross-checked against Greenwood-Thesmar (2011) abstract: substantively faithful (forced/correlated liquidity shocks → overlapping holdings → amplified non-fundamental price impact)
- `perchet2016` grep across main.tex confirms zero remaining occurrences (rename complete)
- All 22 bibitems pass APA format consistency check (no drift v1→v4)
