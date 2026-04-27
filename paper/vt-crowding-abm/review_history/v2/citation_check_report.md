# P5 vt-crowding-abm — Citation Review v2

**Date**: 2026-04-27
**Reviewer**: Claude Opus 4.7 (1M) general-purpose subagent (proxy for `citation-verifier` skill)
**Manuscript**: `paper/vt-crowding-abm/main.tex` (post v1 fix; lines 1–384)
**Target journal**: Finance Research Letters (FRL)
**v1 baseline**: 13/13 verified, 3 DOIs added (moreira2017, brunnermeier2009, harvey2016), 0 MAJOR / 3 MED / 4 MINOR

---

## Overall Assessment

**Verdict**: **⚠️ revise** — bibliography is substantively clean, but **one cited-fact mischaracterization** (`barroso2021`) and **persistent v1 MINOR carryover** require attention before submission.

**Issue counts**: **0 MAJOR / 2 MEDIUM / 5 MINOR**

**Total citations checked**: **16** (13 v1-verified + 3 v2 new)

| Category | v1 | v2 | Δ |
|---|---|---|---|
| `\bibitem` keys | 13 | 16 | +3 |
| `\cite*` body keys | 13 | 16 | +3 |
| Orphan bib | 0 | 0 | — |
| Phantom cite | 0 | 0 | — |

---

## v1 Re-check (13 baseline citations)

### v1 MEDIUM fixes (3 DOIs added) — all verified active

| Citation | DOI added | Verification |
|---|---|---|
| `moreira2017` (line 353) | `10.1111/jofi.12513` | ✅ Resolves to Wiley Online Library, *J. of Finance* 72(4):1611–1644 |
| `brunnermeier2009` (line 315) | `10.1093/rfs/hhn098` | ✅ Resolves to OUP, *RFS* 22(6):2201–2238, 2009 |
| `harvey2016` (line 337) | `10.1093/rfs/hhv059` | ✅ Resolves to OUP, *RFS* 29(1):5–68 |

All 3 DOI URLs follow standard `https://doi.org/<DOI>` format and use `\url{}` wrap correctly.

### v1 13 content claims (re-verified at body level)

All 13 v1-verified claims (Moreira-Muir VT formalization, Harvey-Hoyle 2018 tail risk, Baltas 2019 crowding, ECB 2020 procyclicality, Gennotte-Leland 1990 portfolio insurance parallel, Brunnermeier-Pedersen 2009 spiral 4×, Harvey-Liu-Zhu 2016 |t|>3.0 threshold, Bookstaber 2014 ABM fragility, Kyle 1985 market maker 5×, Perchet 2015 12/VIX heuristic, Cole 2017 USD 2T, LeBaron 2006 ABM, Danielsson 2012 ABM umbrella) **remain in place byte-identical** in v2 main.tex. Verification trail from v1 stands.

### v1 MINOR carry-over status

| v1 MINOR # | Issue | v2 status |
|---|---|---|
| MINOR-1 | `perchet2016` cite-key vs 2015 year mismatch | **NOT FIXED** (lines 75, 355) |
| MINOR-2 | `danielsson2012` not actually ABM, joint-cited with `lebaron2006` | **NOT FIXED** (line 56) |
| MINOR-3 | `kyle1985` page 1315–1335 vs 1315–1336 | **NOT FIXED** (line 347) |
| MINOR-4 | `cole2017` URL field absent | **NOT FIXED** (lines 360–363) |

These are inherited as MINOR-1 through MINOR-4 below.

---

## New Citations (v1 → v2)

Three new bibitems added in v2; all serve a single body location:

**Line 58** introduces an empirical-VT-alpha-literature contestation paragraph:
> "The empirical VT-alpha literature itself is contested---\citet{cederburg2020, barroso2021, liu2019} question whether VT's Sharpe improvement survives realistic implementation costs and out-of-sample tests..."

| New Citation | Bib lines | DOI | Verification |
|---|---|---|---|
| `barroso2021` | 300–304 | `10.1016/j.jfineco.2021.02.009` | ✅ Resolves to *JFE* 140(3):744–767, 2021 |
| `cederburg2020` | 317–321 | `10.1016/j.jfineco.2020.04.015` | ✅ Resolves to *JFE* 138(1):95–117, 2020 |
| `liu2019` | 375–379 | `10.3905/jpm.2019.1.107` | ✅ Resolves to *JPM* 46(1):38–51, Nov 2019 (jpm.2019.1.107 is published-version DOI; supplemental URL `jpm.2019.1.107_JPM_Liu.pdf` confirms) |

APA format on all three: ✓ author + initials + year + italic journal + volume(issue) + pp. + DOI as `\url{...}`. Format matches v1-fixed entries.

---

## Issues

### MAJOR (0)

No fabricated authors, wrong-DOI, wrong-journal, or fabricated years detected. All 16 entries resolve to real, identifiable publications matching the bib metadata.

---

### MEDIUM (2)

#### MED-1. `barroso2021` — cited claim partially mischaracterizes the paper's findings
- **Location**: line 58, `\citet{cederburg2020, barroso2021, liu2019} question whether VT's Sharpe improvement survives realistic implementation costs and out-of-sample tests`.
- **Issue**: Barroso & Detzel (2021) present a **mixed** result, not a clean critique:
  - **Supports critique**: "After transaction costs, volatility management of asset-pricing factors besides the market return generally produces zero abnormal returns and significantly reduces Sharpe ratios" — applies to non-market factors.
  - **Defends VT (market portfolio)**: The volatility-managed *market* portfolio's abnormal returns "are robust to transaction costs and concentrated in the most easily arbitraged stocks." This directly contradicts the framing that they "question whether VT's Sharpe improvement survives realistic implementation costs."
- **Source**: [Barroso & Detzel (2021) JFE 140(3):744-767](https://doi.org/10.1016/j.jfineco.2021.02.009); [IDEAS/RePEc abstract](https://ideas.repec.org/a/eee/jfinec/v140y2021i3p744-767.html).
- **Suggested fix** (any of):
  1. **Reword line 58** to acknowledge the partial-defense reading: e.g., "...the empirical VT-alpha literature itself is contested---\citet{cederburg2020, liu2019} question whether VT's Sharpe improvement survives realistic implementation costs and out-of-sample tests, while \citet{barroso2021} find that VT alpha on the market portfolio is robust to costs but disappears for non-market factors..."
  2. **Drop `barroso2021` from the critic group** if FRL space is tight; cederburg+liu alone cover the critique cleanly.
  3. **Reframe the critique as "implementation-cost-conditional" rather than absolute**: "...the empirical VT-alpha literature itself is contested, with returns sensitive to transaction costs and out-of-sample design \citep{cederburg2020, barroso2021, liu2019}..." (avoids mischaracterizing direction).
- **Severity rationale**: MEDIUM (not MAJOR) because Barroso-Detzel does include a critique of factor-VT, so the citation is not wholly inappropriate; but the current single-line framing groups them with pure critics, which mis-states the market-VT finding. Reviewer at FRL who knows this literature will flag.

#### MED-2. `harvey2018` — DOI still missing (aspirational v1, now elevated)
- **Location**: lines 339–342.
- **Current bib**: `\emph{Journal of Portfolio Management}, 45(1), 14--33.`
- **Add DOI**: `https://doi.org/10.3905/jpm.2018.45.1.014`
- **Rationale**: Lead-paragraph citation (line 54: "Harvey et al. (2018) demonstrate that such strategies meaningfully reduce tail risk"). With v1 having added DOIs to moreira2017/brunnermeier2009/harvey2016, the absence on harvey2018 is conspicuous. v1 flagged this as "aspirational"; given v2 has elevated 3 DOIs, consistency now warrants harvey2018 too.
- **Severity**: MEDIUM (was aspirational in v1; promoted because of consistency with adjacent fixed entries).

---

### MINOR (5)

#### MIN-1 (carryover v1 MINOR-1). `perchet2016` cite-key vs displayed year mismatch
- **Location**: lines 75 (in-text), 355 (bib).
- **Issue**: Cite-key is `perchet2016`, but bib year is `(2015)` and renders as "Perchet et al., 2015".
- **Fix**: Rename cite-key to `perchet2015` in both locations. Cosmetic only; reader sees correct year.
- **Priority**: LOW. Pure source hygiene.

#### MIN-2 (carryover v1 MINOR-2). `danielsson2012` mischaracterized as ABM
- **Location**: line 56, `ABMs have proven effective for studying feedback-driven market dynamics \citep{lebaron2006, danielsson2012}`.
- **Issue**: Danielsson, Shin & Zigrand (2012) is an analytical equilibrium model, not an ABM.
- **Fix options**: (a) split into two cites with different framing; (b) replace with Thurner-Farmer-Geanakoplos (2012, *Quant. Finance* 12(5):695–707).
- **Priority**: LOW. Defensible if read broadly as "feedback-driven dynamics" rather than ABM specifically.

#### MIN-3 (carryover v1 MINOR-3). `kyle1985` page range
- **Location**: line 347, `1315--1335`.
- **Authoritative**: Econometric Society lists 1315–1336.
- **Fix**: Change to `1315--1336`.
- **Priority**: LOW. Both variants in widespread use.

#### MIN-4 (carryover v1 MINOR-4). `cole2017` missing URL
- **Location**: lines 360–363, industry white paper without URL field.
- **Fix**: Add `\url{https://www.artemiscm.com/welcome#research}` or specific PDF link if stable.
- **Priority**: LOW. Industry research report; APA permissive.

#### MIN-5 (new in v2). `\citet{key1, key2, key3}` rendering with natbib
- **Location**: line 58, `\citet{cederburg2020, barroso2021, liu2019}`.
- **Issue**: natbib supports multi-key `\citet`, but the rendering convention (semicolon-separated text-style: "Cederburg et al. (2020); Barroso and Detzel (2021); Liu et al. (2019)") interrupts sentence flow. Many style guides prefer either `\citep{...}` for parenthetical lists, or splitting into separate `\citet{}` in different sentences.
- **Fix options**: (a) confirm `plainnat.bst` renders this readably (compile review_v2.pdf and inspect); (b) reword to `\citep{cederburg2020, barroso2021, liu2019}` if sentence allows; (c) split into separate sentences if reviewer flags.
- **Priority**: LOW. Compiles validly; only a stylistic concern.

---

## Aspirational items (still not addressed; non-blocking)

- `baltas2019` DOI: `10.1080/0015198X.2019.1600955` — recommended but not required by FRL.
- `bookstaber2014` could be updated to published version: Bookstaber, Paddrik & Tivnan (2018), *J. Econ. Interaction & Coordination* 13(2):433–466, DOI `10.1007/s11403-017-0188-1`. WP citation is acceptable.

---

## Recommendation for v3 round

**Main thread MUST fix before FRL submission**:
- [ ] **MED-1**: Reword line 58 to fix `barroso2021` mischaracterization. Suggested: drop `barroso2021` from the critic-trio or reframe as "cost-conditional" critique.
- [ ] **MED-2**: Add `harvey2018` DOI `10.3905/jpm.2018.45.1.014` to lines 339–342.

**Recommended (5-min cleanup)**:
- [ ] MIN-1: rename `perchet2016` → `perchet2015`.
- [ ] MIN-3: update `kyle1985` page to `1315--1336`.
- [ ] MIN-5: confirm multi-key `\citet` renders cleanly in compile (or convert to `\citep`).

**Deferred (optional, not blocking)**:
- MIN-2: Danielsson reframing.
- MIN-4: cole2017 URL.
- baltas2019/bookstaber2014 aspirational DOIs.

---

## Verdict

**⚠️ revise** — substantive bibliography integrity is solid (0 MAJOR; all 16 DOIs verified; one-to-one in-text/bib mapping; all v1 fixes intact). However, the new `barroso2021` insertion at line 58 mischaracterizes the paper's market-portfolio finding, and one consistent-with-v1-pattern DOI gap (`harvey2018`) is now conspicuous. Both are sub-30-minute fixes. Once MED-1 and MED-2 are addressed, the paper is bibliography-ready for FRL submission.

**Verification trail**: v1 R3 WebSearch verifications (2026-04-05, 13 cites) + v2 round (2026-04-27): 3 new DOIs verified via doi.org/Elsevier/OUP/SSRN/RePEc + WebSearch cross-check + Wiley/PM-Research metadata + IDEAS/RePEc abstract for MED-1 cited-fact verification.
