# Citation Check v2 — eav-universal-magnitude

**Reviewer**: Codex, using `.claude/skills/citation-verifier/`
**Date**: 2026-07-06
**Scope**: `body.tex` citations and `references.bib`
**Verification mode**: Web-checked bibliographic metadata against publisher/RePEc/OUP/Taylor & Francis/ScienceDirect pages.

## Executive Verdict

**MAJOR CITATION REVISION REQUIRED**

v2 has improved substantially: `references.bib` exists, all citation keys used in `body.tex` have matching bib entries, and BibTeX compiles cleanly. But at least one reference is bibliographically wrong, every bib entry lacks DOI/stable DOI fields, and two method citations are missing or incomplete.

## Mechanical Citation-Key Audit

| Check | Result |
|---|---|
| Unique cite keys in `body.tex` | 10 |
| Bib entries in `references.bib` | 10 |
| Missing cite keys | 0 |
| Orphan bib entries | 0 |
| BibTeX run | PASS |

Current keys:

`ball_kothari1991`, `beaver1968`, `benjamini_hochberg1995`, `diebold1995`, `engle2013`, `engle_rangel2008`, `glosten1993`, `harvey2016`, `patell1976`, `patell_wolfson1979`.

## Major Issues

### C1. `patell_wolfson1979` has the wrong journal and volume

**Current bib entry**:

```bibtex
journal = {Journal of Financial Economics},
volume  = {7},
number  = {2},
pages   = {117--140}
```

**Verified metadata**: Patell and Wolfson (1979), "Anticipated information releases reflected in call option prices," is listed as **Journal of Accounting and Economics**, volume **1** issue **2**, pages **117-140**. IDEAS/RePEc lists the publisher URL with PII `0165-4101(79)90003-X`.

**Source**: https://ideas.repec.org/a/eee/jaecon/v1y1979i2p117-140.html

**Required fix**:

```bibtex
journal = {Journal of Accounting and Economics},
volume  = {1},
number  = {2},
pages   = {117--140},
doi     = {10.1016/0165-4101(79)90003-X}
```

### C2. DOI fields are missing throughout `references.bib`

The current `.bib` compiles but is not submission-grade. DOI/stable DOI fields should be added where available.

| Key | Verified DOI / stable DOI |
|---|---|
| `beaver1968` | `10.2307/2490070` |
| `patell1976` | `10.2307/2490543` |
| `patell_wolfson1979` | `10.1016/0165-4101(79)90003-X` |
| `engle_rangel2008` | `10.1093/rfs/hhn004` |
| `engle2013` | `10.1162/REST_a_00300` |
| `glosten1993` | `10.1111/j.1540-6261.1993.tb05128.x` |
| `harvey2016` | `10.1093/rfs/hhv059` |
| `diebold1995` | `10.1080/07350015.1995.10524599` |
| `benjamini_hochberg1995` | `10.1111/j.2517-6161.1995.tb02031.x` |

Representative sources:
- Beaver 1968 RePEc/JSTOR: https://ideas.repec.org/a/bla/joares/v6y1968ip67-92.html
- Patell 1976 RePEc/JSTOR: https://ideas.repec.org/a/bla/joares/v14y1976i2p246-276.html
- Engle and Rangel 2008 EconPapers/RFS: https://econpapers.repec.org/RePEc%3Aoup%3Arfinst%3Av%3A21%3Ay%3A2008%3Ai%3A3%3Ap%3A1187-1222
- Engle, Ghysels, and Sohn 2013 EconPapers/ReStat: https://econpapers.repec.org/RePEc%3Atpr%3Arestat%3Av%3A95%3Ay%3A2013%3Ai%3A3%3Ap%3A776-797
- Harvey, Liu, and Zhu 2016 RFS: https://academic.oup.com/rfs/article/29/1/5/1843824
- Benjamini and Hochberg 1995 JRSS-B: https://academic.oup.com/jrsssb/article/57/1/289/7035855
- Diebold and Mariano 1995 JBES: https://www.tandfonline.com/doi/abs/10.1080/07350015.1995.10524599

### C3. GARCH foundation citation is incomplete

**Location**: `body.tex:142-145`, `body.tex:286-296`

The manuscript cites Glosten, Jagannathan, and Runkle (1993) for leverage asymmetry, but it does not cite Bollerslev (1986) for GARCH itself. Since the model is repeatedly described as GJR-GARCH, this should cite both:

- Bollerslev (1986), "Generalized autoregressive conditional heteroskedasticity," Journal of Econometrics 31(3), 307-327, DOI `10.1016/0304-4076(86)90063-1`.
- Glosten, Jagannathan, and Runkle (1993) for the asymmetric term.

Source: https://www.sciencedirect.com/science/article/pii/0304407686900631

### C4. DM-HLN implementation requires Harvey-Leybourne-Newbold (1997)

**Location**: `body.tex:796`, `experiments/k1148_d2/README.md`, `experiments/k1149/README.md`

The manuscript cites Diebold and Mariano (1995), but the experiment documentation describes per-stock **DM-HLN** and the implementation uses `dm_hln_stat`. The finite-sample correction should be cited as:

Harvey, D., Leybourne, S., and Newbold, P. (1997). "Testing the equality of prediction mean squared errors." International Journal of Forecasting, 13(2), 281-291. DOI `10.1016/S0169-2070(96)00719-4`.

Source: https://www.sciencedirect.com/science/article/pii/S0169207096007194

**Required fix**: add a bib entry and cite it at the first DM/DM-HLN mention, or rename the manuscript test as plain DM only if the underlying result is no longer HLN-corrected.

## Medium Issues

### M1. `patell1976` title should use plural "Empirical Tests"

The `.bib` currently says `Empirical test`. RePEc/JSTOR metadata lists "Empirical Tests". Fix the title capitalization/plural.

Source: https://ideas.repec.org/a/bla/joares/v14y1976i2p246-276.html

### M2. `benjamini_hochberg1995` journal name should match modern metadata

Current:

```bibtex
journal = {Journal of the Royal Statistical Society: Series {B}}
```

Verified OUP page: `Journal of the Royal Statistical Society: Series B (Methodological)`, volume 57 issue 1, pages 289-300, DOI `10.1111/j.2517-6161.1995.tb02031.x`.

### M3. First-use author formatting is not fully journal-style

The manuscript uses `\citet{harvey2016}` and `\citet{engle2013}` in first appearances. Depending on target journal, first narrative references with three authors may be acceptable as et al. via natbib style, but the local reviewer criteria prefer listing all authors on first use. If this is retained, document that the target style permits it.

## Verified Correct / Low Risk

- `beaver1968`: journal, volume, pages match RePEc/JSTOR metadata.
- `engle_rangel2008`: RFS 21(3), 1187-1222, DOI verified; content claim about multiplicative low-frequency component is faithful.
- `engle2013`: ReStat 95(3), 776-797, DOI verified; content claim should remain framed as component-volatility lineage, not direct EAV model lineage.
- `glosten1993`: Journal of Finance 48(5), 1779-1801, DOI verified through Wiley DOI page.
- `harvey2016`: RFS 29(1), 5-68, DOI verified; manuscript's `|t|>3` usage is faithful to the source's multiple-testing argument.
- `diebold1995`: JBES 13(3), 253-263, DOI verified; appropriate for predictive-accuracy testing, subject to C4.

## Correction Checklist

- [ ] Fix `patell_wolfson1979` journal/volume/DOI.
- [ ] Add DOI fields to all `.bib` entries with verified DOI/stable DOI.
- [ ] Add `bollerslev1986` and cite it at first GARCH model definition.
- [ ] Add `harvey_leybourne_newbold1997` and cite it where DM-HLN is described.
- [ ] Correct Patell (1976) title plural.
- [ ] Consider first-use full-author style or document target journal style.

After these changes, rerun:

```bash
cd paper/eav-universal-magnitude
/Library/TeX/texbin/xelatex -interaction=nonstopmode body.tex
/Library/TeX/texbin/bibtex body
/Library/TeX/texbin/xelatex -interaction=nonstopmode body.tex
/Library/TeX/texbin/xelatex -interaction=nonstopmode body.tex
```
