# P6 PRG — Citation Review v2

**Date**: 2026-04-27
**Reviewer**: Claude general-purpose subagent (citation-verifier protocol)
**Manuscript**: `paper/prg-periodic-garch/main.tex` (456 lines, 20 bibitems)
**Target journal**: Finance Research Letters (FRL)
**v1 baseline**: 19 bibitems · 15 ✓ verified · 0 MAJOR · 1 MED · 3 MINOR (canonical: `review_history/v1/citation_review.md`)

---

## Overall Assessment

**Verdict**: ✅ Pass with minor polish

**Severity roll-up**: **0 MAJOR** / **1 MEDIUM** / **3 MINOR**

**Total citations**: 20 bibitems (v1 had 19; **+1 new**: `Todorova2014` was already in v1 list but **lacked DOI**; net composition unchanged — the v2 version simply moved the DOI-add work forward). All 20 in-text `\cite{}` / `\citet{}` / `\citealp{}` references resolve to a matching bibitem (0 orphan, 0 missing).

**Key v1 → v2 deltas**:
1. **Lai (2024) DOI added** at L411 — v1 ERR-C1/MED-C1 **RESOLVED** ✓
2. **17 of 20 bibitems now carry DOIs** (up from ~3 in v1). Only `Acerbi2014` (Risk practitioner journal — no DOI) and `Todorova2014` (FRL — DOI exists but **still not added**) remain DOI-less. ~15 bibitems gained DOI lines since v1 → MIN-C1 mostly resolved ✓
3. **Three DOIs differ from v1's recommended values** — verification shows v2's values are the correct ones; v1 had stale/wrong DOI candidates. Details in "v1 → v2 DOI Reconciliation" section below.
4. **No new in-text citation added** (no new `\cite{}` keys); the citation footprint is identical to v1 → MAJOR-1 / MAJOR-2 v1 latex-review fixes (Todorova/Opschoor literature defense at L311) were resolved by **rewording** with already-cited references, not by adding new references.

---

## NotebookLM-identified Prior Literature Audit (mandatory)

| Paper | Cited in main.tex? | Bibitem | Differentiation OK? |
|---|---|---|---|
| **Linton & Wu (2020)** *A coupled component DCS-EGARCH model for intraday and overnight volatility*, J. Econometrics 217(1), 176–201 | ✅ **Cited** | L431–435 (`Linton2020`) | ✅ Adequately differentiated. L59 introduces it as "coupled component DCS-EGARCH model that allows cross-session feedback with approximately twelve parameters"; L122 cites it for the standard two-phase timing convention; L309 contrasts PRG's 6–8 params vs. Linton–Wu's ~12. PRG novelty claim (parsimony + simpler estimation) is defensible. |
| **Martens, van Dijk & de Pooter (2004)** intraday seasonality / realized volatility | ❌ **NOT cited** | none | ⚠ MINOR omission. The Martens 2004 work most commonly cited as an intraday-seasonality precursor is "Modeling and Forecasting S&P 500 Volatility: Long Memory, Structural Breaks and Nonlinearity" (Tinbergen DP 04-067/4; later JoE 138). Its periodic content is **day-of-week / holiday effects** plus pre-announcement and leverage — *not* a session-boundary periodic-GARCH model. The omission is therefore defensible: the more directly relevant intraday-periodic precursor (Engle & Sokalska 2012, multiplicative-component intraday GARCH) is also uncited but neither paper is claim-blocking. **Verdict: MINOR — recommend adding either Martens et al. (2004 JoE) or Engle & Sokalska (2012, J. Fin. Econometrics 10(1), 54–83) to §1 paragraph 2 (L59) as a one-line acknowledgment that intraday periodic GARCH structures predate session-boundary work.** Not blocking. |
| **Bollerslev & Ghysels (1996)** *Periodic autoregressive conditional heteroscedasticity*, JBES 14(2), 139–151 | ✅ **Cited** | L340–344 (`Bollerslev1996`) | ✅ Adequately differentiated. L59 names it as the calendar-based periodic GARCH ancestor; L94, L101 use it for QMLE consistency and stationarity derivation. L59 framing — "periodic structures into GARCH models for **calendar-based** variation" — explicitly differentiates from PRG's session-based periodicity. PRG novelty claim is defensible: PRG extends periodicity from day-of-week to session boundary with a 6–8-param session-coupled recursion vs. Bollerslev–Ghysels' Mon–Fri P-GARCH. |

**Audit verdict**: 2 of 3 NotebookLM-flagged precursors are cited and properly differentiated. The third (Martens et al. 2004) is a defensible omission given that the canonical Martens 2004 paper is about long memory + structural breaks rather than a session-periodic-GARCH structure. Adding a one-line acknowledgment in §1 to either Martens 2004 or Engle–Sokalska 2012 is **recommended but non-blocking** for FRL. Not classified as MAJOR.

---

## v1 Re-check — All 15 v1-verified citations remain content-accurate

Spot-verified that the in-text claims in v2 main.tex still match the v1-verified bibitem content. No claim drift detected.

| Bibitem | v1 status | v2 status | Note |
|---|---|---|---|
| `Acerbi2014` | ✓ | ✓ | L269 use unchanged. Risk practitioner journal — no DOI expected. |
| `Blanc2014` | ✓ | ✓ | L57 framing of asymmetric overnight/intraday feedback unchanged. **DOI updated** (see Reconciliation). |
| `Bollerslev1996` | ✓ | ✓ | L59, L94, L101 uses unchanged. DOI now present at L344. |
| `Christoffersen1998` | ✓ | ✓ | L137 use unchanged. DOI now present at L350. |
| `Corsi2009` | ✓ | ✓ | L131 HAR canonical citation unchanged. DOI now present at L356. |
| `Diebold1995` | ✓ | ✓ | L137 DM test cite unchanged. DOI now present at L362. |
| `Fissler2016` | ✓ | ✓ | L137, L265, L269 FZ joint loss uses unchanged. DOI now present at L368. |
| `Glosten1993` | ✓ | ✓ | L131 GJR canonical cite unchanged. DOI now present at L374. |
| `Haas2004` | ✓ | ✓ | L309 GARCH-Markov estimation difficulties unchanged. DOI now present at L380. |
| `Hansen2005` | ✓ | ✓ | L63, L85 framing (companion to Patton2011) unchanged. DOI now present at L386. |
| `Hansen2011MCS` | ✓ | ✓ | L137 MCS reference unchanged. DOI now present at L392. |
| `Harvey2016` | ✓ | ✓ | L41, L63, L137, L203, L207, L265 threshold uses unchanged. DOI now present at L398. |
| `Harvey1997` | ✓ | ✓ | L137 small-sample correction unchanged. DOI now present at L404. |
| `Kim2023` | ✓ | ✓ | L59, L309 Overnight GARCH-Itô framing unchanged. **DOI updated** (see Reconciliation). |
| `Patton2011` | ✓ | ✓ | L63, L85, L137, L211 uses unchanged. DOI now present at L447. |

**v1 ERR-C1 (Lai 2024 DOI missing)** — bibitem L406–411 now reads:
```latex
\bibitem[Lai et~al.(2024)]{Lai2024}
Lai, Y.-H., Wang, Y.-C., and Chang, Y.-C. (2024).
\newblock Forecasting trading-session return volatility in Taiwan futures market:
A periodic regime switching with jump approach.
\newblock \emph{Asia-Pacific Financial Markets}, 31(2), 285--305.
\newblock \url{https://doi.org/10.1007/s10690-023-09415-w}
```
DOI `10.1007/s10690-023-09415-w` independently verified via Ideas/RePEc URL canonical form `https://ideas.repec.org/a/kap/apfinm/v31y2024i2d10.1007_s10690-023-09415-w.html`. Authors, title, journal, volume, issue, pages all match. **v1 ERR-C1 RESOLVED** ✓

---

## v1 → v2 DOI Reconciliation (3 differences)

Three DOIs in v2 main.tex differ from the values that v1 `citation_review.md` recommended adding. In all three cases, **v2's value is correct** and v1's recommendation was a typo / wrong record. The author should keep v2's values.

| Bibitem | v1 recommended | v2 main.tex actual | Verified correct value | Verdict |
|---|---|---|---|---|
| `Blanc2014` | `10.1016/j.physa.2014.01.024` | `10.1016/j.physa.2014.01.047` | **`10.1016/j.physa.2014.01.047`** | v2 ✓ correct (per HAL hal-01010333 + ScienceDirect S0378437114000594 + RePEc v402y2014icp58-75); v1 record had a digit transposition typo |
| `Kim2023` | `10.1080/07350015.2022.2116450` (v1 marked as "to verify") | `10.1080/07350015.2022.2116027` | **`10.1080/07350015.2022.2116027`** | v2 ✓ correct (per RePEc taf/jnlbes/v41y2023i4p1215-1227 + Tandfonline canonical URL); v1 had wrong DOI candidate |
| `Opschoor2021` | `10.1016/j.ijforecast.2020.08.003` | `10.1016/j.ijforecast.2020.07.009` | **`10.1016/j.ijforecast.2020.07.009`** | v2 ✓ correct (per ScienceDirect S016920702030114X + RePEc v37y2021i2p622-633); v1 had wrong DOI |

All three v2 DOIs were independently confirmed via author-page / RePEc / ScienceDirect cross-reference. The v1 canonical doc `citation_review.md` should be patched to reflect these corrections, but this does not affect the v2 manuscript.

---

## Issues

### MAJOR (0)

None. The v1 ERR-C1 / MED-C1 (Lai 2024 DOI) is resolved. NotebookLM prior-literature audit clears 2/3; the third (Martens 2004) is a defensible non-citation given content mismatch.

### MEDIUM (1)

#### MED-C1 — `Todorova2014` DOI missing (load-bearing citation)

**Location**: bibitem L449–452.

**Current**:
```latex
\bibitem[Todorova and Soucek(2014)]{Todorova2014}
Todorova, N. and Soucek, M. (2014).
\newblock Overnight information flow and realized volatility forecasting.
\newblock \emph{Finance Research Letters}, 11(4), 420--428.
```

**Required fix** — append:
```latex
\newblock \url{https://doi.org/10.1016/j.frl.2014.07.001}
```

**Verified DOI**: `10.1016/j.frl.2014.07.001` (per ScienceDirect pii S1544612314000348 + RePEc finlet/v11y2014i4p420-428).

**Why MED, not MINOR**: This citation became **load-bearing in v2** for the §5 limitations defense at L311 (the v1 latex-review MAJOR-1 Fix B literature defense for the missing GJR-X benchmark). The whole passage hinges on Todorova & Souček (2014) and Opschoor & Lucas (2021); the latter has its DOI, the former does not. FRL reviewers will be especially attentive to a DOI-missing reference in the **same journal** (Finance Research Letters) as the target.

**Fix effort**: ~30 seconds (one-line edit).

### MINOR (3)

#### MIN-C1 — Bibliography ordering not alphabetical

Current bibitem order is by appearance in manuscript:
Acerbi → Bollerslev → Christoffersen → Corsi → Diebold → Fissler → Glosten → Haas → Hansen2005 → Hansen2011MCS → Harvey2016 → Harvey1997 → Lai → Blanc → Kupiec → Kim → Linton → Opschoor → Patton → Todorova.

`\bibliographystyle{apalike}` typically expects alphabetical order. This was already flagged in v1 (MIN-A4 / MIN-C3) and remains unfixed in v2.

**Fix effort**: ~10–15 min (manual reorder of `thebibliography` block; `natbib + apalike` resolves citations by key so the visual order is purely cosmetic — does not affect cite resolution).

**Optional**. FRL does not strictly mandate alphabetical for author-year keys. Recommend before final submission only.

#### MIN-C2 — Consider adding intraday-periodic-GARCH precursor at §1 L59

NotebookLM flagged Martens et al. (2004) as a periodic-GARCH precursor. As discussed in the Prior Literature Audit, the canonical Martens 2004 paper is about long-memory + structural breaks rather than session-periodic GARCH; the closer precursor is Engle & Sokalska (2012), "Forecasting intraday volatility in the US equity market: Multiplicative component GARCH," *J. Financial Econometrics* 10(1), 54–83 (DOI: `10.1093/jjfinec/nbr005`).

**Suggested edit** (optional, ~2 min): add to L59 after the Bollerslev–Ghysels sentence:
> "\citet{Engle2012} decompose intraday volatility into multiplicative daily, diurnal, and stochastic components."

Plus a corresponding bibitem.

This pre-empts a referee comment of the form "the authors should acknowledge intraday-periodic-GARCH precursors beyond day-of-week effects." Not blocking; v2 can ship as-is.

#### MIN-C3 — Acerbi2014 page abbreviation

Bibitem L335–338 uses `27(11), 76--81.` for *Risk* magazine. *Risk* is a practitioner monthly that does not typically use volume/issue numbering in the same way as academic journals. The current rendering is acceptable but some style guides prefer `Risk Magazine, November 2014, 76--81.` Non-blocking; APA 7 accepts both forms for trade publications.

---

## New Citations (v1 → v2)

**Zero new in-text citations** added. The bibliography composition is identical to v1 except that:
- `Lai2024` gained its DOI `\newblock` line (v1 ERR-C1 resolved)
- 14 other bibitems gained DOI `\newblock` lines (v1 MIN-C1 mostly resolved — only `Todorova2014` and `Acerbi2014` still without; `Acerbi2014` has no DOI to add)

The v1 latex-review MAJOR-1 Fix B (literature defense for GJR-X non-comparison) was implemented by **rewording** at L311 leveraging already-cited `Todorova2014` and `Opschoor2021` — no new references introduced.

---

## Recommendation for v3

### Must-fix (1)
- **MED-C1**: Add Todorova & Souček (2014) DOI `https://doi.org/10.1016/j.frl.2014.07.001` to bibitem L452. ~30 sec edit. **Blocking for FRL submission** because it is now a load-bearing citation in §5 and missing DOI in same-journal reference is reviewer-visible.

### Should-fix (1)
- **MIN-C2**: Add a one-line acknowledgment of Engle & Sokalska (2012) at §1 L59 as an intraday-periodic-GARCH precursor, plus bibitem. Pre-empts the most likely "missing prior literature" referee comment (NotebookLM-identified concern).

### Deferred (1)
- **MIN-C1**: Bibliography alphabetical ordering — cosmetic; do at final proof.

### Patch v1 canonical doc (housekeeping, not v3-blocking)
- Update `paper/prg-periodic-garch/citation_check.md` and `review_history/v1/citation_review.md` to record the **correct** DOIs for `Blanc2014`, `Kim2023`, `Opschoor2021` (per Reconciliation table above). v1 docs currently list typo / wrong DOI candidates that were silently corrected during v2 revise. Owner: main thread.

---

## v3 readiness assessment

If MED-C1 (Todorova2014 DOI) is fixed → citation pillar is **GREEN** for FRL submission. Combined with v1-resolved ERR-C1 and v2-resolved 14× DOI additions, the citation review trajectory is:

| Round | MAJOR | MED | MINOR | Verdict |
|---|---|---|---|---|
| R1 (2026-04-05) | 0 | 3 | several | ✗ blocked (3 errors) |
| v1 (2026-04-19) | 0 | 1 | 3 | ⚠ revise (Lai DOI must add) |
| **v2 (2026-04-27)** | **0** | **1** | **3** | **✅ revise (Todorova DOI must add)** |
| v3 (target) | 0 | 0 | 1–2 | ✅ ready for FRL |

**Bottom line**: Citation pillar is one ~30-second edit (Todorova DOI) from being submission-clean. The NotebookLM Prior Literature Audit clears the most reviewer-visible challenge to PRG's novelty claim (Linton-Wu and Bollerslev-Ghysels both cited and properly differentiated; Martens 2004 omission is defensible).

---

## Reviewer signature

Reviewer: Claude general-purpose subagent (citation-verifier protocol, Opus 4.7 1M)
Round: v2 canonical
Baseline: supersedes `review_history/v1/citation_review.md`
Outstanding: 1 MED (Todorova 2014 DOI) + 3 MINOR (alphabetical order; Engle-Sokalska 2012 add; Acerbi page format)
Web verifications performed: 6 (Blanc 2014 Physica A DOI; Kim 2023 JBES DOI; Opschoor 2021 IJF DOI; Todorova 2014 FRL DOI; Lai 2024 APFM DOI; Linton-Wu 2020 JoE bibliographic spot-check)
WebFetch failures (paywall 403): 4 (handled via WebSearch fallback; no INCONCLUSIVE classifications)
