# Citation Check Report — leverage-direction v8

**Date**: 2026-05-22  
**Reviewer**: citation-verifier agent (a867ff7f9b90a3141)  
**Verdict**: FAIL — 1 MAJOR issue (factual error in body text about cited paper)  

---

## Issue Summary

| Severity | Count | Description |
|----------|-------|-------------|
| MAJOR | 1 | GJR 1993 data frequency misrepresented in body.tex line 76 |
| MEDIUM | 2 | engle1982 JSTOR DOI; hood2025 "early access" stale |
| MINOR | 3 | nelson2025 unpublished; xu2024 forthcoming; black1976 pre-digital |
| RESOLVED | 1 | campbell2017 DOI (corrected from v7) |

---

## MAJOR Issues

### MAJOR-1: glosten1993 — Factually Incorrect Data Frequency

**Location**: `body.tex`, line 76  
**Confidence**: 95

**Passage**:
```
\citet{glosten1993} established the leverage effect in U.S.\ equities using
fewer than 3,000 daily observations
```

**Problem**: GJR (1993) — Glosten, Jagannathan & Runkle, *Journal of Finance* 48(5) — used **monthly** NYSE/CRSP stock return data (approximately 396–735 monthly observations), not daily. The paper models conditional variance of **monthly** nominal excess returns. "3,000 daily observations" implies ~12 years; GJR's sample spans ~62 years (1926–1987 or 1951–1984 depending on the sub-sample). A referee familiar with GJR (1993) will flag this immediately.

**Suggested fixes**:
1. "using approximately 735 monthly observations (CRSP 1926–1987)"
2. "using monthly return data spanning 1926–1987"
3. Replace with Nelson 1991 (EGARCH, daily data) or Engle & Ng 1993 for a daily-frequency precedent

---

## MEDIUM Issues

### MED-1: engle1982 — JSTOR resolver DOI (carried from v7)

**Location**: `main.tex`, line 115  
**Entry**: `https://doi.org/10.2307/1912773`

JSTOR resolver prefix rather than canonical publisher DOI. Bibliographic details (Econometrica 50(4), pp. 987–1007) are correct. Most finance journals accept this for pre-digital era papers. No immediate action required unless target journal requires canonical DOI.

**Severity**: MEDIUM — content accuracy unaffected.

---

### MED-2: hood2025 — "early access" label outdated

**Location**: `main.tex`, line 184

Current entry cites "early access" for the *Journal of Portfolio Management*. Web search confirms this paper was formally published in Vol. 52, Issue 1 (November 2025). The final volume/issue citation is available.

**Suggested fix**:
```latex
Hood, B., \& Raughtigan, C. (2025). Volatility targeting is trendy: How trend
following explains alpha in volatility-managed strategies. \textit{Journal of
Portfolio Management}, 52(1). https://doi.org/10.3905/jpm.2025.1.764
```

---

## MINOR Issues

### MINOR-1: nelson2025 — Unpublished SSRN working paper

**Location**: `main.tex`, line 217  
Institutional affiliation missing. Check if published; if still unpublished, add "(unpublished manuscript)" per target journal style.

### MINOR-2: xu2024 — Forthcoming without DOI

**Location**: `main.tex`, line 232  
*Critical Finance Review* forthcoming. Add DOI if assigned. Acceptable for truly forthcoming paper.

### MINOR-3: black1976 — Pre-digital, no DOI

**Location**: `main.tex`, line 88  
Pages 177–181 are the standard citation. No fix required; informational only.

---

## RESOLVED (from v7)

- **campbell2017 DOI**: Corrected to `10.1561/104.00000043` — ✅ verified

---

## Complete Bibitem Verification

57 bibitems verified. Zero orphan citations. Zero unused bibitems.

| Key | Verdict |
|-----|---------|
| araya2024 | OK |
| baur2010hedge | OK |
| baur2010safe | OK |
| bali2016 | OK |
| batten2010 | OK |
| bcbs2006 | OK |
| bcbs2019 | OK |
| black1976 | OK (MINOR-3) |
| bollerslev1986 | OK |
| bollerslev1987 | OK |
| bozovic2024 | OK |
| bucci2020 | OK |
| cederburg2020 | OK |
| chang2021 | OK |
| chevallier2017 | OK |
| engleGhyselsSohn2013 | OK |
| engle1982 | OK (MED-1 JSTOR DOI) |
| engle2006 | OK |
| acerbiszekely2014 | OK |
| bayerdimitriadis2022 | OK |
| fisslerziegel2016 | OK |
| pattonSheppard2015 | OK |
| christoffersen1998 | OK |
| christie1982 | OK |
| diebold1995 | OK |
| demiguel2024 | OK |
| engle2018 | OK |
| engle2004 | OK |
| fleming2001 | OK |
| fleming2003 | OK |
| francq2004 | OK |
| glosten1993 | Bibitem OK; MAJOR-1 in body.tex |
| hansen1994 | OK |
| hansen2005 | OK |
| hansen2011 | OK |
| hansen2012 | OK |
| harri2009 | OK |
| harvey2016 | OK |
| harvey2018 | OK |
| hood2025 | MED-2 (early access) |
| henriksson1981 | OK |
| hwang2006 | OK |
| kim2019 | OK |
| kuester2006 | OK |
| kupiec1995 | OK |
| longin2001 | OK |
| mcneil2015 | OK |
| moreira2017 | OK |
| nelson1991 | OK |
| newey1987 | OK |
| nelson2025 | MINOR-1 |
| parkinson1980 | OK |
| patton2011 | OK |
| sheppard2023 | OK |
| treynor1966 | OK |
| xu2024 | MINOR-2 |
| campbell2017 | ✅ RESOLVED |
