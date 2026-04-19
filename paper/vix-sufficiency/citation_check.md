# Citation Verification Report

**Manuscript**: Paper 4 — "Can Anything Beat VIX?" (`main_v2.tex`)
**Verified against**: `main_v2.tex` bibliography (40 `\bibitem` entries, 38 unique inline citations)
**Date**: 2026-04-18
**Scope**: APA format, DOI, author spelling, year, journal, pages, quoted-content fidelity

> Supersedes the 2026-03-30 `main.tex` check for any overlapping refs. Prior-cycle MAJOR/MED on `bollerslev2020` / `schwert1989` / `harvey2016` / `luo2019` are re-evaluated against main_v2 usage (some already fixed in v2).

---

## Summary

| Status | Count |
|---|---|
| **Total unique inline citations** | 38 |
| **Total bibitem entries** | 40 (2 orphans, see below) |
| **PASS (fully verified)** | 30 |
| **MAJOR (投稿前必修 — DOI/author/content 錯)** | 1 |
| **MED (投稿前必修 — 格式/weak support/orphan)** | 5 |
| **MINOR (nice-to-have — 頁碼等瑣碎)** | 2 |
| **UNVERIFIED** | 0 |

**Bottom line**: No fabricated refs, no DOI errors. One MAJOR content-attribution issue on `harvey2016` (same as v1 check, still present in v2). Two orphan bibitems (`bollerslev2020`, `engle2006`) — v2 removed the flawed `bollerslev2020` inline cite but didn't remove the bibitem. Five MED items and two MINOR items summarized below.

---

## Bibliography Format: Global Observations

- `\bibliographystyle{apalike}` paired with hand-written `thebibliography` — this mixes natbib and apalike conventions. apalike normally uses author-year labels like `Author (Year)` not `[Author(Year)]`. Current entries use the `\bibitem[Label]{key}` syntax correctly, natbib compatible. **No action needed** — compiles cleanly per `main_v2.log`.
- Bibliography NOT alphabetized cleanly: `Campbell and Thompson (2008)` appears before `Bucci (2020)` in the list; `Christoffersen`, `Engle and Gallo`, `Kupiec` are in insertion order rather than alphabetical. APA 7th requires alphabetical order in the reference list. **MED — fix before submission**.
- No DOIs in any bibitem. APA 7th mandates DOI for journal articles where available. **MED — add DOIs to all 40 entries** (list below has the verified DOIs).
- `Barunik` should be `Baruník` (with háček). Current entry drops the diacritic. **MINOR**.
- `Te\"{i}letche` in `maillard2010` is correct (ï), good.

---

## Orphan Bibitems (cited in bibliography but not in body)

1. **`bollerslev2020`** — Bollerslev, Li, Zhao (2020). Listed in bibliography (line 846-847) but **no `\cite` in main_v2.tex**. The v1 citation in Section 3.2.10 (overnight price changes) was correctly replaced with `lou2019` in v2 (line 238), but the bibitem was not removed. **MED — remove bibitem, or add a legitimate inline cite** (it does have real relevance to good/bad vol research on line 140 where `patton2015` is cited — but patton2015 is already there).
2. **`engle2006`** — Engle and Gallo (2006), "A multiple indicators model for volatility using intra-daily data." Listed in bibliography (line 909-910) but **no `\cite` in main_v2.tex**. This is the origin of the MEM/AMEM family mentioned in Section 7 (line 600+), so it should be cited where "MEM" or "AMEM" is first introduced. **MED — either add inline cite at first AMEM mention, or remove bibitem**.

---

## MAJOR Issues (投稿前必修)

### 1. `harvey2016` — content attribution still mis-stated in abstract & Section 5.2

- **Cited as**: Harvey, C. R., Liu, Y., & Zhu, H. (2016). ...and the cross-section of expected returns. *Review of Financial Studies*, 29(1), 5–68. — **verified correct bibliographic detail** (DOI 10.1093/rfs/hhv059).
- **Content issue (unchanged from v1 check)**: Abstract line 48 says "the \citet{harvey2016} multiple-testing threshold ($|t|>3.0$)". This phrasing reads as if Harvey et al. issued a universal recommendation of $|t|>3.0$. Harvey et al. (2016) actually derive a **conditional** threshold depending on prior beliefs and number of tested factors (~300); for smaller test sets the implied threshold differs.
- **Partial mitigation in v2**: Section 5.2 (line 335) now reads "We adopt $|t| > 3.0$ as an approximate conservative threshold motivated by their analysis, noting that for our 11 tests the simple Bonferroni correction yields a comparable threshold of $|t| > 3.23$" — this IS accurate and good.
- **Remaining fix**: Abstract (line 48) and Introduction (line 80) still refer to "the Harvey (2016) multiple-testing threshold" as if it were a fixed number. Change abstract wording to "an approximate conservative $|t|>3.0$ threshold motivated by \citet{harvey2016}". Same fix in line 80, line 804 "Harvey (2016) approximate thresholds" is already fine.
- **Severity**: **MAJOR (content attribution)** — 投稿前必修, 2 word-changes in abstract + intro.

---

## MED Issues (投稿前必修)

### 2. Bibliography not alphabetized (global)

- **Issue**: Per APA 7th, reference list must be alphabetized by first-author surname. Current order mixes insertion order: `Campbell and Thompson (2008)` at line 861 precedes `Bucci (2020)` at 864; `Christoffersen (1998)` at 906 is placed between `Holm (1979)` and `Engle and Gallo (2006)`; `Kupiec (1995)` at 915 is between `Jiang and Tian (2005)` and `Lou et al. (2019)`.
- **Fix**: Sort all 40 entries alphabetically by first-author surname (and year within same author). Correct order: Andersen, Baker, Barunik, Bekaert, Bollerslev 2009, Bollerslev 2020, Bouman, Bouri, Bozovic, Britten-Jones, Bucci, Campbell, Christensen, Christoffersen, Corsi, Da, DeMiguel, Diebold 1995, Diebold 2012, Engle & Gallo, Engle & Rangel, Estrella, Fleming, Hansen & Lunde, Hansen et al., Harvey, Holm, Jiang, Kupiec, Lou, Luo, Maillard, Moreira, Newey, Patton 2011, Patton 2015, Poon, Preis, Schwert, Whaley.
- **Severity**: **MED** — formatting but required for most finance journals.

### 3. DOIs missing across entire bibliography

- **Issue**: APA 7th requires DOI for journal articles where assigned. Zero DOIs currently in main_v2.tex.
- **Fix**: Add DOIs to all 40 bibitems. Verified DOIs below:

| Key | Verified DOI |
|---|---|
| `andersen2003` | 10.1111/1468-0262.00418 |
| `baker2006` | 10.1111/j.1540-6261.2006.00885.x |
| `barunik2016` | 10.1016/j.finmar.2015.09.003 |
| `bekaert2014` | 10.1016/j.jeconom.2014.05.008 |
| `bollerslev2009` | 10.1093/rfs/hhp008 |
| `bollerslev2020` | 10.1017/S0022109018001084 (if retained) |
| `bouman2002` | 10.1257/000282802762024683 |
| `bouri2017` | 10.1016/j.frl.2016.09.025 |
| `bozovic2024` | 10.1016/j.irfa.2024.103353 |
| `britten2000` | 10.1111/0022-1082.00228 |
| `bucci2020` | 10.1093/jjfinec/nbaa008 |
| `campbell2008` | 10.1093/rfs/hhm055 |
| `christensen1998` | 10.1016/S0304-405X(98)00034-8 |
| `christoffersen1998` | 10.2307/2527341 (JSTOR DOI) |
| `corsi2009` | 10.1093/jjfinec/nbp001 |
| `da2011` | 10.1111/j.1540-6261.2011.01679.x |
| `demiguel2009` | 10.1093/rfs/hhm075 |
| `diebold1995` | 10.1080/07350015.1995.10524599 |
| `diebold2012` | 10.1016/j.ijforecast.2011.02.006 |
| `engle2006` | 10.1016/j.jeconom.2005.01.018 |
| `engle2008` | 10.1093/rfs/hhn004 |
| `estrella1998` | 10.1162/003465398557320 |
| `fleming2001` | 10.1111/0022-1082.00327 |
| `hansen2005` | 10.1002/jae.800 |
| `hansen2011mcs` | 10.3982/ECTA5771 |
| `harvey2016` | 10.1093/rfs/hhv059 |
| `holm1979` | (no DOI — JSTOR 4615733) |
| `jiang2005` | 10.1093/rfs/hhi027 |
| `kupiec1995` | 10.3905/jod.1995.407942 |
| `lou2019` | 10.1016/j.jfineco.2019.03.011 |
| `luo2019` | 10.1002/fut.21944 |
| `maillard2010` | 10.3905/jpm.2010.36.4.060 |
| `moreira2017` | 10.1111/jofi.12513 |
| `newey1987` | 10.2307/1913610 |
| `patton2011` | 10.1016/j.jeconom.2010.03.034 |
| `patton2015` | 10.1162/REST_a_00503 |
| `poon2003` | 10.1257/002205103765762743 |
| `preis2013` | 10.1038/srep01684 |
| `schwert1989` | 10.1111/j.1540-6261.1989.tb02647.x |
| `whaley2000` | 10.3905/jpm.2000.319728 |

- **Severity**: **MED** — required for APA 7th + most journals.

### 4. `luo2019` — weak citation support (unchanged from v1 check)

- **Cited as**: Luo, X., & Zhang, J. E. (2019). VIX term structure and VIX futures pricing with realized volatility. *Journal of Futures Markets*, 39(1), 72–93. Bibliographic detail **correct** (DOI 10.1002/fut.21944).
- **Content issue**: Line 206 uses `\citep{luo2019}` to support the claim that VIX/VIX3M contango/backwardation is "proposed as a regime indicator." Luo & Zhang (2019) primarily model VIX futures pricing using realized volatility — they do not propose the contango/backwardation regime framework. 
- **Fix**: Supplement or replace with Simon & Campasano (2014), *Journal of Derivatives Research* — "The VIX Futures Basis: Evidence and Trading Strategies" — which explicitly frames contango/backwardation as a regime signal. Alexander & Korovilas (2013) also work.
- **Severity**: **MED** — content-support mismatch.

### 5. Orphan bibitems (see "Orphan Bibitems" section above)

- `bollerslev2020` and `engle2006` are in bibliography but never `\cite`d inline.
- Most journals flag orphan references during desk check.
- **Severity**: **MED** — fix by removing or adding inline cites.

### 6. `schwert1989` — abstracted away in v2 but fix verified

- v1 check flagged "misleading positioning" — in v2, line 72 cites `schwert1989, engle2008` together for "macroeconomic determinants of time-varying volatility," which is an accurate characterization of Schwert (1989). **Issue resolved in v2**. No action.
- Noted here for completeness so the v1 MAJOR doesn't re-surface.

---

## MINOR Issues (nice-to-have)

### 7. `barunik2016` — missing diacritic

- Should be "Baruník, J." (with háček over ní). Currently "Barunik". Preserve Czech author name spelling per APA 7th.
- **Severity**: **MINOR** — common omission, journals usually accept.

### 8. `bozovic2024` — also missing diacritic

- Correct form is "Božović, M." (with two hačeks and an acute). Current entry "Bozovic, M." strips them.
- Affiliated with University of Belgrade; author consistently uses diacritics.
- **Severity**: **MINOR** — like #7.

---

## Resolved from v1 Check (no action in v2)

| v1 finding | v1 severity | v2 status |
|---|---|---|
| `bollerslev2020` content mismatch (overnight claim) | MED | **RESOLVED** — v2 now uses `lou2019` on line 238 for overnight. (But orphan bibitem remains, see MED #5.) |
| `schwert1989` misleading positioning | HIGH | **RESOLVED** — v2 pairs schwert1989+engle2008 at line 72 for macro determinants of time-varying vol, which is accurate. |
| `harvey2016` oversimplified attribution | HIGH | **Partially resolved** in Section 5.2 (now uses "approximate conservative threshold motivated by"); **still mis-stated in abstract and introduction**. See MAJOR #1 above. |
| `bozovic2024` DOI unverifiable | LOW | **RESOLVED** — DOI 10.1016/j.irfa.2024.103353 verified via SSRN + ScienceDirect. |
| `bucci2020` page range | LOW | **RESOLVED** — 502–531 verified (Oxford Academic). |
| `corsi2009` "does not benchmark against VIX" claim | LOW | **Minor-checked**: Corsi (2009) benchmarks HAR-RV against GARCH and other RV models; does not include VIX/implied vol in the horse race. Claim is **correct**. |
| Missing foundational refs (Poon-Granger, Hansen-Lunde, Andersen et al., Campbell-Thompson, Patton, Hansen et al. MCS, Newey-West) | MED (structural) | **RESOLVED** — v2 adds all of these: `poon2003`, `hansen2005`, `andersen2003`, `campbell2008`, `patton2011`, `hansen2011mcs`, `newey1987`, plus `patton2015`, `holm1979`, `christoffersen1998`, `kupiec1995`, `engle2008`, `lou2019`. Good. |

---

## Detailed Verification Table (main_v2 — 38 unique inline cites)

| # | Key | Bib check | Inline use check | Verdict |
|---|---|---|---|---|
| 1 | andersen2003 | Econometrica 71(2), 579–625 ✓ (DOI 10.1111/1468-0262.00418) | RV framework, line 128 — accurate | PASS |
| 2 | baker2006 | JF 61(4), 1645–1680 ✓ | Investor sentiment, line 210 — accurate | PASS |
| 3 | barunik2016 | JFM 27, 55–78 ✓ | Cross-asset spillovers, line 202 — accurate | PASS (minor diacritic) |
| 4 | bekaert2014 | JoE 183(2), 181–190 ✓ | VRP decomposition, lines 68/126 — accurate | PASS |
| 5 | bollerslev2009 | RFS 22(11), 4463–4492 ✓ | VRP predicts returns, lines 72/142/214/450 — accurate, and v2 correctly distinguishes return vs vol prediction | PASS |
| 6 | bouman2002 | AER 92(5), 1618–1635 ✓ | Halloween effect, line 242 — accurate | PASS |
| 7 | bouri2017 | FRL 20, 192–198 ✓ | Bitcoin diversifier, line 226 — accurate | PASS |
| 8 | bozovic2024 | IRFA 95, 103353 ✓ (DOI 10.1016/j.irfa.2024.103353) | VIX-managed portfolios, line 130 — accurate; Bozovic's finding of "drawdown reduction rather than return enhancement" matches paper's abstract | PASS (minor diacritic) |
| 9 | britten2000 | JF 55(2), 839–866 ✓ | Model-free IV, line 110 — accurate | PASS |
| 10 | bucci2020 | JFE 18(3), 502–531 ✓ (DOI 10.1093/jjfinec/nbaa008) | NN RV forecasting, line 142 — accurate; claim "does not test whether improvement survives after VIX" is correct (Bucci compares NN vs econometric RV models, no VIX) | PASS |
| 11 | campbell2008 | RFS 21(4), 1509–1531 ✓ (DOI 10.1093/rfs/hhm055) | OOS R² convention, line 298/438 — accurate methodological attribution | PASS |
| 12 | christensen1998 | JFE 50(2), 125–150 ✓ | VIX subsumes historical vol, lines 68/126 — accurate | PASS |
| 13 | christoffersen1998 | IER 39(4), 841–862 ✓ | Conditional coverage test, line 711 — accurate | PASS |
| 14 | corsi2009 | JFE (Oxford) 7(2), 174–196 ✓ (DOI 10.1093/jjfinec/nbp001) | HAR-RV, line 142 — accurate | PASS |
| 15 | da2011 | JF 66(5), 1461–1499 ✓ | Internet attention, line 234 — accurate | PASS |
| 16 | demiguel2009 | RFS 22(5), 1915–1953 ✓ | 1/N outperforms, lines 218/385/531/791 — accurate | PASS |
| 17 | diebold1995 | JBES 13(3), 253–263 ✓ | DM test, line 320 — standard | PASS |
| 18 | diebold2012 | IJF 28(1), 57–66 ✓ | Spillover connectedness, lines 72/202 — accurate | PASS |
| 19 | engle2008 | RFS 21(3), 1187–1222 ✓ (DOI 10.1093/rfs/hhn004) | Macro determinants of vol, line 72 — accurate | PASS |
| 20 | estrella1998 | REStat 80(1), 45–61 ✓ | Yield curve recession predictor, line 230 — accurate | PASS |
| 21 | fleming2001 | JF 56(1), 329–352 ✓ | VT seminal, line 70 — accurate | PASS |
| 22 | hansen2005 | JAE 20(7), 873–889 ✓ (DOI 10.1002/jae.800) | Canonical horse race, line 140 — accurate; "330 ARCH-type models" matches paper abstract | PASS |
| 23 | hansen2011mcs | Econometrica 79(2), 453–497 ✓ (DOI 10.3982/ECTA5771) | MCS, lines 81/140/342/etc. — accurate | PASS |
| 24 | harvey2016 | RFS 29(1), 5–68 ✓ (DOI 10.1093/rfs/hhv059) | Multiple testing threshold — **content issue in abstract/intro; Section 5.2 accurate** | **MAJOR** |
| 25 | holm1979 | Scand. J. Stat. 6(2), 65–70 ✓ (no DOI — JSTOR 4615733) | Holm-Bonferroni, line 337 — standard | PASS |
| 26 | jiang2005 | RFS 18(4), 1305–1342 ✓ | Model-free IV dominates GARCH, lines 68/110/126 — accurate | PASS |
| 27 | kupiec1995 | J. Derivatives 3(2), 73–84 ✓ (DOI 10.3905/jod.1995.407942) | Unconditional coverage test, line 711 — accurate | PASS |
| 28 | lou2019 | JFE 134(1), 192–213 ✓ (DOI 10.1016/j.jfineco.2019.03.011) | Overnight vs intraday, line 238 — accurate replacement for v1's bollerslev2020 misuse | PASS |
| 29 | luo2019 | JFM 39(1), 72–93 ✓ (DOI 10.1002/fut.21944) | Contango/backwardation regime, line 206 — **weak support for the specific claim** | **MED** |
| 30 | maillard2010 | JPM 36(4), 60–70 ✓ | ERC, lines 222/385 — accurate | PASS |
| 31 | moreira2017 | JF 72(4), 1611–1644 ✓ | VT framework, line 70 — accurate | PASS |
| 32 | newey1987 | Econometrica 55(3), 703–708 ✓ | HAC SE, lines 330/438 — standard | PASS |
| 33 | patton2011 | JoE 160(1), 246–256 ✓ | Proxy-robust QLIKE, lines 48/81/128/289/600/632/804 — accurate | PASS |
| 34 | patton2015 | REStat 97(3), 683–697 ✓ (DOI 10.1162/REST_a_00503) | Good/bad vol semivariance, line 140 — accurate | PASS |
| 35 | poon2003 | JEL 41(2), 478–539 ✓ (DOI 10.1257/002205103765762743) | Definitive survey, line 126 — accurate | PASS |
| 36 | preis2013 | Sci. Reports 3, 1684 ✓ | Google Trends fear, line 234 — accurate | PASS |
| 37 | schwert1989 | JF 44(5), 1115–1153 ✓ | Time-varying vol macro determinants, line 72 — accurate in v2 (paired with engle2008) | PASS |
| 38 | whaley2000 | JPM 26(3), 12–17 ✓ | "Fear gauge" label, line 68 — accurate | PASS |

Orphan bibitems (not in table above, see "Orphan Bibitems"):
- `bollerslev2020` — bibitem present, no inline cite → MED
- `engle2006` — bibitem present, no inline cite → MED

---

## Correction Checklist (pre-submission)

### 投稿前必修 (MAJOR + MED)

- [ ] **[MAJOR #1]** Change abstract (line 48) "the \citet{harvey2016} multiple-testing threshold ($|t|>3.0$)" to "an approximate conservative $|t|>3.0$ threshold motivated by \citet{harvey2016}". Same wording fix in introduction line 80.
- [ ] **[MED #2]** Alphabetize bibliography (40 entries, order specified above).
- [ ] **[MED #3]** Add DOIs to all 40 bibitems (verified DOI table above).
- [ ] **[MED #4]** `luo2019` usage line 206 — supplement with Simon & Campasano (2014) for regime interpretation, or rewrite claim to match Luo & Zhang's actual focus (VIX futures pricing).
- [ ] **[MED #5a]** Remove `bollerslev2020` bibitem (lines 846–847) OR add a legitimate inline cite.
- [ ] **[MED #5b]** Remove `engle2006` bibitem (lines 909–910) OR add inline cite at first AMEM mention (Section 7).

### Nice-to-have (MINOR)

- [ ] **[MINOR #7]** Add háček: `Baruník` for `barunik2016`.
- [ ] **[MINOR #8]** Add diacritics: `Božović` for `bozovic2024`.

---

## Hard-rule compliance

- [x] Did not modify `main_v2.tex` or `body.tex`
- [x] Did not commit
- [x] Did not fabricate — all DOIs verified via WebSearch + publisher sites
- [x] Did not read full `knowledge.json` / `feed.json`
- [x] UNVERIFIED count = 0 (all 38 inline cites resolved to primary sources)

## Verification sources

- Oxford Academic, ScienceDirect, Wiley Online Library, NBER, MIT Press, JSTOR, SSRN, IDEAS/RePEc (via WebSearch 2026-04-18)
- Full search trail available in session transcript.
