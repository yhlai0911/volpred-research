# Review Round v5 — leverage-direction

**Date**: 2026-05-21
**Triggered by**: v4 MEDIUM M-1 citation fix — systematic plain-text → \citet{}/\citep{} conversion
**Status**: Pre-review (v3.3 fixes applied; v5 academic review not yet run)

---

## v3.3 Fixes Applied (2026-05-21 hourly dispatch)

All M-1 plain-text citations converted to \citet{}/\citep{} commands throughout body.tex:

| Citation | Old (plain text) | New (LaTeX command) |
|---------|-----------------|---------------------|
| bollerslev1986 | "(Bollerslev, 1986)" | `\citep{bollerslev1986}` |
| glosten1993 | "Glosten, Jagannathan, and Runkle (1993)" | `\citet{glosten1993}` |
| black1976 | "Black (1976)" | `\citet{black1976}` |
| christie1982 | "Christie (1982)" | `\citet{christie1982}` |
| hood2025 | "Hood and Raughtigan (2025)" | `\citet{hood2025}` (×3 occurrences) |
| bollerslev1986 | "Bollerslev's (1986)" | `\citeauthor{bollerslev1986}'s (\citeyear{bollerslev1986})` |
| engle2018 | "Engle and Siriwardane (2018)" | `\citet{engle2018}` |
| kupiec1995 | "Kupiec (1995)" | `\citet{kupiec1995}` |
| christoffersen1998 | "Christoffersen (1998)" | `\citet{christoffersen1998}` |
| mcneil2015 | "McNeil, Frey, and Embrechts (2015)" | `\citet{mcneil2015}` |
| bollerslev1987 | "Bollerslev (1987)" | `\citet{bollerslev1987}` |
| kuester2006 | "Kuester, Mittnik, and Paolella (2006)" | `\citet{kuester2006}` |
| moreira2017 | "Moreira and Muir (2017)" | `\citet{moreira2017}` (×2 occurrences) |
| harvey2018 | "Harvey, Hoyle, ... (2018)" | `\citet{harvey2018}` |
| fleming2001,fleming2003 | "Fleming, Kirby, and Ostdiek (2001, 2003)" | `\citet{fleming2001,fleming2003}` |
| bollerslev1986 | "Bollerslev (1986)" (methodology §) | `\citet{bollerslev1986}` |
| glosten1993 | "Glosten et al.\ (1993)" (methodology §) | `\citet{glosten1993}` |
| sheppard2023 | "(Sheppard, 2023)" | `\citep{sheppard2023}` (×2 occurrences) |
| hwang2006 | "Hwang & Valls Pereira, 2006" | `\citealt{hwang2006}` |
| kupiec1995 | "Kupiec's (1995)" | `\citeauthor{kupiec1995}'s (\citeyear{kupiec1995})` |
| christoffersen1998 | "Christoffersen's (1998)" | `\citeauthor{christoffersen1998}'s (\citeyear{christoffersen1998})` |
| chevallier2017 | "Chevallier and Ielpo (2017)" | `\citet{chevallier2017}` (×2 occurrences) |
| baur2010safe | "Baur and McDermott (2010)" | `\citet{baur2010safe}` |
| baur2010hedge | "Baur and Lucey (2010)" | `\citet{baur2010hedge}` |
| chang2021 | "Chang et al.\ (2021)" | `\citet{chang2021}` |
| patton2011 | "Patton's (2011)" | `\citeauthor{patton2011}'s (\citeyear{patton2011})` |
| nelson2025 | "Nelson's (2025)" | `\citeauthor{nelson2025}'s (\citeyear{nelson2025})` |

**Also updated**: main.tex `\date{}` → "May 2026 (v3.3)"

---

## Pending (for next round)

### MEDIUM (2 remaining)
- **M-3 PENDING**: campbell2017 bibitem format — LOW priority (comma separator vs standard natbib)
- **MED-1 PENDING**: Verify Cederburg et al. (2020) 4.9% figure against original Tables 2–3; update footnote with specific table reference (requires external journal access)

### Minor
- **MIN-3 PENDING**: Update hood2025 bibitem with final JPM 51(9) vol/issue/pages + DOI (requires verification at doi.org/10.3905/jpm.2025.1.764 before changing)

---

## Gate for ready_for_submission

After v5 academic + citation review confirms ≥4★ and 0 MEDIUM:
- Academic ≥ 4★ (expected with M-1 complete)
- Citation 0 MAJOR (currently 0 MAJOR ✅)
- ≤ 1 MED (M-3 bibitem format is cosmetic; MED-1 needs external verification)

**Prediction**: v5 review should upgrade to ≥4★ once M-1 is confirmed clean → stage upgrade to `ready_for_submission` pending MED-1 verification.
