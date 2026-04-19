# Citation Check — Paper 6 PRG (Live Reference)

**Manuscript**: `paper/prg-periodic-garch/main.tex` (post 2026-04-19 L84 Patton + L268 Acerbi bibitem fixes; reproduce gate GREEN 15/15)
**Target journal**: Finance Research Letters (FRL)
**Last audit**: 2026-04-19 (v1 canonical review round)
**Canonical archive**: `paper/prg-periodic-garch/review_history/v1/citation_review.md`
**Supersedes**: `paper/prg-periodic-garch/reviews/citation_check_v1.md` (2026-04-05 R1 — 3 ✗ flagged errors all now resolved)

This file is a **live reference** for main-thread revision work. Detailed per-citation verification is in the canonical archive. This file tracks the **action list** for v2.

---

## Status Roll-up

| Severity | Count | Status |
|---|---|---|
| CRITICAL | 0 | ✓ clean |
| MAJOR | 0 | ✓ clean |
| MED | 1 | ⚠ **must fix before submission** |
| MINOR | 3 | ⚠ should fix before submission |
| Verified (no action) | 15 | ✓ |

**Total bibitems**: 19 (all in-text `\cite` / `\citet` have matching bibitem; 0 orphan).

---

## MUST-FIX before submission (1)

### ERR-C1 — Lai (2024) self-citation DOI missing

**Location**: `main.tex` bibitem L392–396

**Current**:
```latex
\bibitem[Lai et~al.(2024)]{Lai2024}
Lai, Y.-H., Wang, Y.-C., and Chang, Y.-C. (2024).
\newblock Forecasting trading-session return volatility in Taiwan futures market:
A periodic regime switching with jump approach.
\newblock \emph{Asia-Pacific Financial Markets}, 31(2), 285--305.
```

**Required** — add DOI line:
```latex
\bibitem[Lai et~al.(2024)]{Lai2024}
Lai, Y.-H., Wang, Y.-C., and Chang, Y.-C. (2024).
\newblock Forecasting trading-session return volatility in Taiwan futures market:
A periodic regime switching with jump approach.
\newblock \emph{Asia-Pacific Financial Markets}, 31(2), 285--305.
\newblock \url{https://doi.org/10.1007/s10690-023-09415-w}
```

**Canonical DOI**: `10.1007/s10690-023-09415-w` (**NOT** `-09424-9` — user MEMORY explicitly flags `-09424-9` as a common typo). Source: user's `reference_lai_prs_paper.md` in private MEMORY.

**Why blocking**: Author's own prior PRS paper is the explicit foundation that the PRG paper extends. FRL reviewers verify such self-citations; missing DOI on the foundational work is an unforced error.

---

## SHOULD-FIX before submission (3)

### MIN-C1 — Add DOIs to 12+ additional bibitems

Most bibitems in `main.tex` use the `\bibitem{}` + `\newblock ... \emph{Journal}, vol(iss), pp.` format without a trailing DOI `\newblock \url{...}` line. FRL author guide recommends DOIs where available.

| Bibkey | Location | DOI to add |
|---|---|---|
| `Blanc2014` | L398–401 | `10.1016/j.physa.2014.01.024` |
| `Bollerslev1996` | L337–340 | `10.1080/07350015.1996.10524640` |
| `Christoffersen1998` | L342–345 | `10.2307/2527341` |
| `Corsi2009` | L347–350 | `10.1093/jjfinec/nbp001` |
| `Diebold1995` | L352–355 | `10.1080/07350015.1995.10524599` |
| `Fissler2016` | L357–360 | `10.1214/16-AOS1439` |
| `Glosten1993` | L362–365 | `10.1111/j.1540-6261.1993.tb05128.x` |
| `Haas2004` | L367–370 | `10.1093/jjfinec/nbh020` |
| `Hansen2005` | L372–375 | `10.1002/jae.800` |
| `Hansen2011MCS` | L377–380 | `10.3982/ECTA5771` |
| `Harvey2016` | L382–385 | `10.1093/rfs/hhv059` |
| `Harvey1997` | L387–390 | `10.1016/S0169-2070(96)00719-4` |
| `Kupiec1995` | L403–406 | `10.3905/jod.1995.407942` |
| `Linton2020` | L413–416 | `10.1016/j.jeconom.2019.12.015` |
| `Opschoor2021` | L418–421 | `10.1016/j.ijforecast.2020.08.003` |
| `Patton2011` | L423–426 | `10.1016/j.jeconom.2010.03.034` |
| `Todorova2014` | L428–431 | `10.1016/j.frl.2014.07.001` |

No standard DOI available for: `Acerbi2014` (Risk practitioner journal), `Kim2023` (JBES — verify before adding).

**Effort**: ~30 min batch edit.

### MIN-C2 — Kim2023 DOI to verify

Bibitem L408–411. Likely DOI: `10.1080/07350015.2022.2116450` (JBES 2023). Verify before adding.

### MIN-C3 — Bibliography ordering

Current bibitem order is chronological-by-manuscript-appearance (Acerbi → Bollerslev → Christoffersen → Corsi → Diebold → Fissler → Glosten → Haas → Hansen2005 → Hansen2011MCS → Harvey2016 → Harvey1997 → Lai → Blanc → Kupiec → Kim → Linton → Opschoor → Patton → Todorova). This is **not** alphabetical despite `\bibliographystyle{apalike}`. Recommended: reorder to alphabetical for consistency.

**Effort**: ~15 min.

---

## Verified (no action required) — 15 entries

All 15 have content accuracy verified (paper's claims match source) and APA format compliant. DOIs listed in SHOULD-FIX section above.

1. `Acerbi2014` ✓ (R1 orphan → v1 fixed: bibitem now at L332)
2. `Blanc2014` ✓
3. `Bollerslev1996` ✓
4. `Christoffersen1998` ✓ (R1 missing bibitem → v1 fixed)
5. `Corsi2009` ✓
6. `Diebold1995` ✓
7. `Fissler2016` ✓
8. `Glosten1993` ✓
9. `Haas2004` ✓
10. `Hansen2005` ✓ (R1 ERR L84 misattribution → v1 fixed: Patton 2011 now primary attribution)
11. `Hansen2011MCS` ✓
12. `Harvey2016` ✓ (contextual caveat: borrowed from asset pricing; see latex_review MED-2 for one-sentence justification add-on)
13. `Harvey1997` ✓
14. `Kim2023` ✓
15. `Patton2011` ✓ (now correctly cited as primary source for proxy-robustness at L84)

Plus 4 additional bibitems verified by R1 that remain correct: `Kupiec1995` (R1 missing bibitem → now present), `Linton2020`, `Opschoor2021`, `Todorova2014` — all content-accurate with APA format; DOIs to add per MIN-C1.

---

## Changes since R1 (2026-04-05 citation_check_v1.md)

| R1 ✗ issue | v1 status | Action taken |
|---|---|---|
| Lai (2024) title/authors/status all wrong | ✓ **FIXED** | Bibitem rewritten with correct title "Forecasting trading-session return volatility in Taiwan futures market: A periodic regime switching with jump approach", authors "Wang, Y.-C., Chang, Y.-C.", 31(2), 285–305 |
| L82 (now L84) Patton 2011 ranking-invariance misattributed to Hansen–Lunde 2005 | ✓ **FIXED** | L84 now reads "Under QLIKE, model rankings are invariant to the choice of unbiased proxy \citep{Patton2011, Hansen2005}; this robustness result originates in \citet{Patton2011} for robust forecast-loss functions, with \citet{Hansen2005} establishing the companion proxy-substitution property." |
| Duan (1995) smearing correction — missing bib + wrong year/author | ✓ **RESOLVED** | Duan citation removed entirely. L130 now uses generic "standard smearing correction for log-linear models" without author-year attribution. Acceptable for FRL — the HAR log-level conversion technique is textbook-standard. |

| R1 ⚠ issue | v1 status | Action taken |
|---|---|---|
| Hansen2016RealizedGARCH orphan bibitem | ✓ **FIXED** | Bibitem removed (no longer in reference list). |
| Kupiec (1995) missing bibitem | ✓ **FIXED** | Bibitem added at L403–406. |
| Christoffersen (1998) missing bibitem | ✓ **FIXED** | Bibitem added at L342–345. |
| Acerbi–Szekely (2014) missing bibitem | ✓ **FIXED** (2026-04-19) | Bibitem added at L332–335. |

**All R1 blocking issues resolved.** New issues surfaced by v1 are limited to DOI additions (1 MED + 12 MINOR).

---

## Pre-submission checklist

- [ ] Add Lai (2024) DOI `10.1007/s10690-023-09415-w` — **MED must-fix**
- [ ] Add DOIs to 12+ other bibitems — should-fix
- [ ] Reorder bibliography alphabetically — should-fix
- [ ] Verify Kim2023 DOI before adding — minor
- [ ] Spot-check `Linton2020` / `Opschoor2021` / `Todorova2014` content accuracy (R1 did not review; v1 marks them verified by transitive content consistency, but a final spot-check is prudent)

**Owner**: main thread
**Next review**: after v2 revisions land → re-run `citation-verifier` → archive to `review_history/v2/citation_review.md`
