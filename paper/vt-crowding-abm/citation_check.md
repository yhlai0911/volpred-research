# Citation Verification Report — Paper 5 (vt-crowding-abm) v1

**Manuscript**: `paper/vt-crowding-abm/main.tex` (FRL 15p R3 submission-ready draft)
**Date**: 2026-04-18
**Reviewer**: Claude Opus 4.7 (1M) — `citation-verifier` skill
**Scope**: All 13 `\cite*` keys in body (lines 54–183) + 13 `\bibitem` entries in `thebibliography` (lines 278–345).
**Basis**: This is the first formal `review_history/v1/` round. It integrates and re-validates findings from the prior three `reviews/citation_check_v{1,2,3}.md` rounds (2026-04-05) against the current canonical `main.tex`. No new citations have been added since R3; all R3 fixes remain in place.

---

## Summary

| Metric | Count |
|--------|-------|
| Unique `\bibitem` keys | 13 |
| Unique `\cite*` keys in body | 13 |
| Orphan bib entries (not cited) | 0 |
| Orphan in-text cites (no bib) | 0 |
| **MAJOR (wrong author / year / journal / page / fabricated)** | **0** |
| **MEDIUM (missing DOI / APA format gaps)** | **3** |
| **MINOR (cosmetic / stylistic)** | **4** |
| OK (fully verified) | 13 / 13 (bibliographic substance) |

**Verdict**: **acceptable for FRL submission**. The bibliography is substantively clean — zero MAJOR errors, perfect in-text ↔ bib one-to-one mapping, all 13 content claims accurately represent the cited works per independent WebSearch verification (R3, 2026-04-05). Three MEDIUM items (missing DOIs for three references that have valid DOIs) should be added before submission per APA 7 guidance. Four MINOR items are cosmetic and do not block submission.

---

## MAJOR Issues — 0

No wrong-author, wrong-year, wrong-journal, or fabricated citations detected. R3 confirmed this; the current `main.tex` is byte-identical on all `\bibitem` blocks.

---

## MEDIUM Issues — 3

### MEDIUM-1. `moreira2017` — missing DOI
- Current bib (lines 320–323): *Journal of Finance*, 72(4), 1611–1644.
- **Add DOI**: `https://doi.org/10.1111/jofi.12513`
- Rationale: Moreira & Muir is the canonical VT paper and cited in the lead sentence; FRL copy-editors expect DOI on journal articles.

### MEDIUM-2. `brunnermeier2009` — missing DOI
- Current bib (lines 290–293): *Review of Financial Studies*, 22(6), 2201–2238.
- **Add DOI**: `https://doi.org/10.1093/rfs/hhn098`
- Rationale: Cited 4× (lines 56, 97, 183, 269) as the theoretical anchor of the feedback structure; high-visibility citation.

### MEDIUM-3. `harvey2016` — missing DOI
- Current bib (lines 305–308): *Review of Financial Studies*, 29(1), 5–68.
- **Add DOI**: `https://doi.org/10.1093/rfs/hhv059`
- Rationale: Methodology citation (|t|>3.0 threshold, line 179); readers will want direct access.

**Note on other references**: `harvey2018` (JPM 45.1.14) and `baltas2019` (FAJ 75.3.89) also have DOIs (`10.3905/jpm.2018.45.1.014`, `10.1080/0015198X.2019.1600955`) that are currently missing. Adding them is recommended but not required for FRL (the journal's reference style accepts entries without DOI when the full volume/issue/page triple resolves uniquely). Flagged as aspirational rather than MEDIUM.

---

## MINOR Issues — 4

### MINOR-1. `perchet2016` cite-key vs display year mismatch (cosmetic)
- Lines 75, 325: cite-key is `perchet2016` but rendered year is 2015 (bib entry correctly says `(2015)`).
- Reader sees "(Perchet et al., 2015)" — fully correct.
- Fix (optional): rename cite-key to `perchet2015` throughout (line 75 + line 325). Pure `.tex`-source hygiene; zero reader impact.
- **Priority**: LOW.

### MINOR-2. `danielsson2012` thematic fit
- Line 56: `\citep{lebaron2006, danielsson2012}` — "ABMs have proven effective for studying feedback-driven market dynamics".
- Danielsson, Shin & Zigrand (2012) uses an **analytical equilibrium model**, not an ABM. The joint citation slightly over-generalizes the "ABM" umbrella.
- Options:
  1. **Keep** (defensible — sentence is about "feedback-driven dynamics" broadly).
  2. **Rephrase** (recommended if revising): separate into "ABMs have proven effective ... \citep{lebaron2006}; analytical models demonstrate how risk-management constraints amplify endogenous risk \citep{danielsson2012}".
  3. **Replace** `danielsson2012` with Thurner, Farmer & Geanakoplos (2012), *Quant. Finance*, 12(5), 695–707 — a pure ABM reference.
- **Priority**: LOW. Unlikely to trigger FRL reviewer flag; a revise-with-comments letter might mention it.

### MINOR-3. `kyle1985` page number — 1315–1335 vs 1315–1336
- Line 318: `1315--1335`.
- Econometric Society's authoritative record: 1315–1336. SCIRP/sciepub cite 1315–1335 (widespread variant).
- Fix (optional): change to `1315--1336`.
- **Priority**: LOW. Both variants are accepted in the literature; off-by-one.

### MINOR-4. `cole2017` — subtitle + URL enhancement (optional)
- Full title: "Volatility and the Alchemy of Risk: Reflexivity in the Shadows of Black Monday 1987".
- Current bib drops the subtitle. Adding `URL` (e.g., https://caia.org/sites/default/files/03_volatility_4-2-18.pdf) would improve traceability.
- **Priority**: LOW. Industry white paper; full APA format is permissive.

---

## Orphan / Phantom Cross-check

### In-text `\cite*` keys (13):
`baltas2019`, `bookstaber2014`, `brunnermeier2009`, `cole2017`, `danielsson2012`, `ecb2020`, `gennotte1990`, `harvey2016`, `harvey2018`, `kyle1985`, `lebaron2006`, `moreira2017`, `perchet2016`

### `\bibitem` keys (13):
`baltas2019`, `bookstaber2014`, `brunnermeier2009`, `cole2017`, `danielsson2012`, `ecb2020`, `gennotte1990`, `harvey2016`, `harvey2018`, `kyle1985`, `lebaron2006`, `moreira2017`, `perchet2016`

### Result
- **Orphans** (bib but not cited): **0** ✓
- **Phantoms** (cited but no bib): **0** ✓
- **One-to-one**: perfect. ✓

---

## Content Accuracy (re-verified from R3 trail 2026-04-05; no text changes since)

| # | Claim in manuscript | Cited work | Status |
|---|---------------------|------------|--------|
| 1 | "formalized by Moreira and Muir (2017)" with $w_t = \sigma^*/\hat{\sigma}_t$ | Moreira & Muir (2017), *JoF* 72(4):1611–1644 | ✓ Accurate |
| 2 | "Harvey et al. (2018) demonstrate [VT] meaningfully reduce tail risk across asset classes" | Harvey, Hoyle, Korgaonkar, Rattray, Sargaison & Van Hemert (2018), *JPM* 45(1):14–33 | ✓ Accurate |
| 3 | "Baltas (2019) document crowding effects in alternative risk premia" | Baltas (2019), *FAJ* 75(3):89–104 | ✓ Accurate |
| 4 | "ECB (2020) explicitly flagged VT procyclicality as a source of market fragility" | ECB FSR May 2020 Box 2 | ✓ Accurate (title corrected in R1→R2: "Volatility-targeting strategies and the market sell-off") |
| 5 | "parallels to portfolio insurance strategies implicated in the 1987 crash" | Gennotte & Leland (1990), *AER* 80(5):999–1021 | ✓ Accurate |
| 6 | "Brunnermeier–Pedersen (2009) liquidity spiral" (cited 4×) | Brunnermeier & Pedersen (2009), *RFS* 22(6):2201–2238 | ✓ Accurate |
| 7 | "Harvey et al. (2016) $|t|>3.0$ threshold" | Harvey, Liu & Zhu (2016), *RFS* 29(1):5–68 | ✓ Accurate |
| 8 | "Bookstaber et al. (2014) use agent-based modeling to study financial system fragility but do not specifically examine VT crowding" | Bookstaber, Paddrik & Tivnan (2014), OFR WP 14-05 | ✓ Accurate |
| 9 | "Kyle (1985) market maker with $\lambda$" (cited 5×) | Kyle (1985), *Econometrica* 53(6):1315–1335 | ✓ Accurate (page ±1, see MINOR-3) |
| 10 | "widely-used practitioner heuristic" (12/VIX rule) | Perchet et al. (2015), *JAI* 18(3):21–38 | ✓ Reasonable |
| 11 | "over USD 2 trillion in assets" for vol-sensitive strategies | Cole (2017), Artemis Capital Research Report | ✓ Accurate (independently confirmed by ECB FSR May 2020 citing ~USD 2T) |
| 12 | "ABMs have proven effective for studying feedback-driven market dynamics" | LeBaron (2006), *Handbook of Computational Economics*, Vol. 2, ch. 24 | ✓ Accurate |
| 13 | Grouped with LeBaron under ABM umbrella | Danielsson, Shin & Zigrand (2012), LSE WP | ⚠ See MINOR-2 |

---

## Pre-submission Correction Checklist

**Must do before FRL submission (MEDIUM)**:
- [ ] Add DOI to `moreira2017`: `https://doi.org/10.1111/jofi.12513`
- [ ] Add DOI to `brunnermeier2009`: `https://doi.org/10.1093/rfs/hhn098`
- [ ] Add DOI to `harvey2016`: `https://doi.org/10.1093/rfs/hhv059`

**Recommended but optional (MINOR)**:
- [ ] Rename cite-key `perchet2016` → `perchet2015` (lines 75, 325)
- [ ] Reword line 56 to separate LeBaron (ABM) from Danielsson (analytical), OR replace `danielsson2012` with Thurner-Farmer-Geanakoplos (2012)
- [ ] Update Kyle page range to 1315–1336
- [ ] Add `URL` field to `cole2017` bib entry

**Aspirational (nice-to-have DOIs)**:
- [ ] `harvey2018` DOI: `10.3905/jpm.2018.45.1.014`
- [ ] `baltas2019` DOI: `10.1080/0015198X.2019.1600955`
- [ ] `bookstaber2014`: consider updating to published journal version (JEIC 13(2):433–466, 2018, DOI: `10.1007/s11403-017-0188-1`)

---

## Overall Assessment

The bibliography is **ready for FRL submission** on substance. The 13 citations form a perfect one-to-one in-text/bib mapping, all 13 content claims have been independently verified against primary sources, and zero MAJOR errors remain. Three DOIs should be added for APA 7 / FRL copy-editor compliance (5-minute fix). The four MINOR items are cosmetic and optional.

**Verification trail**: All 13 citations were independently verified via WebSearch in R3 (2026-04-05) against primary publishers (Wiley, Oxford Academic, T&F, Econometric Society, ECB, OFR, NBER, SSRN). The current main.tex has not modified any `\bibitem` block since R3, so the trail remains valid. No new citations introduced.

**Next round trigger**: After v(n+1) revision adds MEDIUM DOI fixes, a v2 round is optional (30-min spot-check) but not required — the verification trail from R3+v1 is sufficient for submission.
