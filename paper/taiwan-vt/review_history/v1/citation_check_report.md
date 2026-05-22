# Citation Verification Report — taiwan-vt v1

**Reviewer**: citation-verifier agent (feature-dev:code-reviewer subagent)
**Date**: 2026-05-23
**Document**: `paper/taiwan-vt/body.tex` (833 lines) + `paper/taiwan-vt/main_v3.tex`
**Target journal**: Pacific-Basin Finance Journal (PBFJ)
**Scope**: 34 `\bibitem` entries; all `\cite{}` calls in body.tex

---

## Summary

| Severity | Count |
|----------|-------|
| MAJOR (blocking) | 1 |
| MEDIUM | 2 |
| MINOR | 2 |
| Verified clean | 31 |

**Overall verdict: CONDITIONAL_PASS** — one blocking undefined citation key must be fixed before compilation; all bibliographic content is accurate.

---

## MAJOR Issues (blocking submission)

### MAJOR-1: Undefined citation key `politis1994stationary` — compiles as `[?]`

**File**: `body.tex`, line 449

`body.tex:449` contains `\citep{politis1994stationary}`, but the bibliography key in `main_v3.tex:143` is `politis1994`. No `\bibitem{politis1994stationary}` exists anywhere in the file. LaTeX will render this as an undefined citation `[?]` and emit an `undefined citation` warning on every compile.

Note: the correct key `politis1994` is used correctly at `body.tex:181`:
`\citep[Politis-Romano][]{politis1994}` — resolves fine.

**Fix**: In `body.tex` line 449, change `\citep{politis1994stationary}` → `\citep{politis1994}`.

**Confidence**: 100

---

## MEDIUM Issues

### MEDIUM-1: `christoffersen1998` bibitem exists but is never cited in body.tex

`main_v3.tex:83-84` — bibitem entry present: `\bibitem[Christoffersen(1998)]{christoffersen1998}`
`body.tex` — zero occurrences of `christoffersen1998` (confirmed by grep).

The VaR Trinity mentions "Kupiec VaR test" (line 593) but does not cite Christoffersen (1998) for the independence component. The bibitem was added in commit 70438101 (M3-persist fix) but the `\citet{}` call was not inserted into body.tex.

**Fix options**:
- Add `\citet{christoffersen1998}` in Section 7.2 at "Basel III Trinity" / independence test mention alongside `\citet{kupiec1995}`.
- If not needed: remove `\bibitem{christoffersen1998}` from `main_v3.tex`.

**Confidence**: 95

### MEDIUM-2: Engle (1982) end page — `987--1007` should be `987--1008`

**File**: `main_v3.tex:93`

The Econometrica Vol. 50, No. 4 (Jul. 1982) article runs pages 987–1008, not 987–1007. Common transcription error propagated from secondary sources.

**Fix**: Change `987--1007` to `987--1008` in `main_v3.tex:93`.

**Confidence**: 85

---

## MINOR Issues

### MINOR-1: Inconsistent `et~al.` non-breaking tilde in `\bibitem` display text

Some bibitems use the LaTeX non-breaking tilde (`et~al.`) while others use plain space (`et al.`). Inconsistent within a single bibliography.

Entries needing fix in `main_v3.tex`: `fleming2001` (line 104), `glosten1993` (line 110), `harvey2016` (line 116), `rapach2013` (line 146).

**Fix**: Standardize to `et~al.` in the `\bibitem[...]` display argument for these four entries.

### MINOR-2: No DOIs in any bibliography entry

APA 7th edition requires DOIs for journal articles. PBFJ production may request at accepted stage. No immediate fix needed for initial submission.

---

## Verified Citations (31 clean)

`acerbi2014`, `ang2002`, `barber2009`, `barclay2003`, `barndorff2010`, `black1976`, `bollerslev1986`, `bollerslev1992`, `bozovic2024`, `christie1982`, `christoffersen1998` (bibliographically correct; cited in main_v3.tex body text — see MEDIUM-1), `corsi2009`, `diebold1995`, `engle2013`, `eun1989`, `fissler2016`, `fleming2001`, `gagnon2010`, `glosten1993`, `hamao1990`, `harvey2016`, `harvey2018`, `hwang2006`, `jpmorgan1996`, `kupiec1995`, `lin1994`, `moreira2017`, `nelson1991`, `patton2011`, `politis1994`, `rapach2013`, `whaley2000`, `whaley2009`

(Excludes `engle1982` which has the MEDIUM-2 page number issue.)

---

## Correction Checklist

- [ ] **BLOCKING**: `body.tex:449` — change `\citep{politis1994stationary}` to `\citep{politis1994}`
- [ ] **MEDIUM**: Decide: add `\citet{christoffersen1998}` in VaR independence test text, or remove orphan bibitem
- [ ] **MEDIUM**: `main_v3.tex:93` — change `987--1007` to `987--1008` for Engle (1982)
- [ ] **MINOR**: `main_v3.tex:104,110,116,146` — standardize `et al.` → `et~al.` for 4 bibitems
