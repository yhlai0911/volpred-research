# P10 Citation Verification Report — v2

**Paper**: The Crypto Fear Channel — Asymmetric, Tail-Concentrated, and Regime-Dependent Volatility Spillover from Bitcoin to Equity Markets
**File reviewed**: `paper/crypto-fear-channel/main.tex` (v2 final after v2.1 commit `13638cd2` + v2.2 commit `8a68fdc5`, 16 pages, 509 lines)
**Reference source**: `paper/crypto-fear-channel/research_notes/lit_review_dois_2026_04_27.md` + v1 `citation_check_report.md`
**Reviewer**: citation-verifier (subagent)
**Date**: 2026-04-28
**Bibitems audited**: 22 / 22 (v1 had 21; v2 added `andrews1991`)
**External verification**: 1 fresh web verification on the new `andrews1991` entry (DOI / journal / pages / title / content claim)

---

## 1. Verdict (top-line)

| Severity | v1 baseline | v2 final | Δ |
|---|---|---|---|
| **MAJOR** | 1 | **0** | -1 ✓ |
| **MED** | 5 | **1** | -4 ✓ |
| **MINOR** | 7 | **5** | -2 ✓ |

**Blocks review-stage upgrade?**  **NO** — the single MAJOR (`corbet2018` title swap, M-1) was successfully closed in v2.1 (title byte-correct, author order Corbet/Meegan/Larkin/Lucey/Yarovaya restored to match the actual Economics Letters 165:28-34 paper). All three mechanical-DOI MEDs (v1 MED-1/2/3) closed. Bibliography is now clean enough for next review-stage progression. Remaining issues are 1 MED (Conrad-2020 framing, deferred from v1 MINOR-7) and 5 MINOR (mostly defer-to-copy-edit).

**One new MINOR uncovered in v2**: the new `andrews1991` bibitem is alphabetically misplaced — sits between `adrian2016` and `akyildirim2020` but "Andrews" sorts AFTER "Akyildirim" (A-n > A-k). See MINOR-N1 below.

---

## 2. v1 Fix Regression Check Table

| v1 ID | Item | Required fix | v2 status | Byte-level evidence |
|---|---|---|---|---|
| **MAJOR-1** | `corbet2018` title swap + author order | Title → "Exploring the dynamic relationships..."; author order Corbet/Meegan/Larkin/Lucey/Yarovaya | ✓ FIXED (v2.1) | L412: `Corbet, S., Meegan, A., Larkin, C., Lucey, B., and Yarovaya, L. (2018).`<br>L413: `\newblock Exploring the dynamic relationships between cryptocurrencies and other financial assets.` |
| **MED-1** | `conrad2020` missing DOI URL | Add `\url{https://doi.org/10.1002/jae.2742}` | ✓ FIXED (v2.1) | L409: `\newblock \url{https://doi.org/10.1002/jae.2742}` |
| **MED-2** | `diebold1995` missing DOI URL | Add `\url{https://doi.org/10.1080/07350015.1995.10524599}` | ✓ FIXED (v2.1) | L421: `\newblock \url{https://doi.org/10.1080/07350015.1995.10524599}` |
| **MED-3** | `harvey2016` missing DOI URL | Add `\url{https://doi.org/10.1093/rfs/hhv059}` | ✓ FIXED (v2.1) | L457: `\newblock \url{https://doi.org/10.1093/rfs/hhv059}` |
| **MED-4** | `harvey2016` |t|>3 transfer-context footnote | Optional content fix (methodological footnote) | ✗ Not added; **DEFER** to copy-edit pass (acceptable) | — |
| **MED-5** | `iyer2022` policy-tier framing | Optional softening | ✗ Not changed; v1 noted "NOT blocking" | — |
| **MINOR-1** | Header bibitem count | Update "19 bibitems" → "21 bibitems" (v1) → with new andrews1991 should now be "22 bibitems" | ✓ FIXED (v2.2) | L4: `% 9 sections, 16+ pages, 6 tables, 22 bibitems, ~4,900+ body words.` ← matches actual `\bibitem` count of 22 |
| **MINOR-2** | `harvey1997` / `harvey2016` ordering swap | Swap so 1997 precedes 2016 | ✓ FIXED (v2.2) | L447 `harvey1997` BEFORE L453 `harvey2016` ✓ |
| **MINOR-3** | `koenker1978` "Bassett, Jr." cosmetic | Optional | ✗ Unchanged (cosmetic, defer) | — |
| **MINOR-4** | Cite-key portfolio audit | Optional, no immediate action | ✗ N/A | — |
| **MINOR-5** | §6.3 ETF cutoff footnote (SEC approval 1/10 vs trading launch 1/11) | Add footnote distinguishing the two dates | ✗ Not added; L305 still reads "2024-01-11 (the ETF launch date)" without footnote — **DEFER** (semantically correct, footnote is polish) | — |
| **MINOR-6** | `cederburg2020/barroso2021` cluster cross-check | No fix needed (issue moot in v1) | ✓ N/A | — |
| **MINOR-7** | `conrad2020` framing partial overclaim (§2.3 ¶1) | Soften to acknowledge housing-starts positive result | ✗ L78 unchanged: still "demonstrates that incorporating macro-economic information through long-run components can deliver in-sample fit improvements that fail to translate into forecast accuracy gains." — **MED carry-forward** (see §3.2 MED-1 below) | — |

**Summary of fixes**: MAJOR-1 ✓ + MED-1/2/3 ✓ + MINOR-1/2 ✓ — **6 byte-level fixes confirmed**. MED-4/5 + MINOR-3/4/5 are defer-to-copy-edit category and remain open without blocking the next review stage. MINOR-7 (conrad2020 framing) is borderline-MED and is carried forward as v2 MED-1 below.

---

## 3. Issues by Severity (v2)

### 3.1 MAJOR (0)

None. All v1 MAJORs closed.

### 3.2 MED (1)

#### v2 MED-1: `conrad2020` framing partial overclaim (carried from v1 MINOR-7)

- **Bib key**: `conrad2020`
- **Location**: §2.3 ¶1 (L78)
- **Current text**:
  > \citet{conrad2020}'s GARCH-MIDAS application demonstrates that incorporating macro-economic information through long-run components can deliver in-sample fit improvements that fail to translate into forecast accuracy gains.
- **Problem**: Conrad-Kleen (2020) actually find that **some** macro variables (notably housing starts) **do** improve OOS forecasts at 2- and 3-month horizons; the paper is **not** a clean "in-sample-good-OOS-fail" cautionary tale, but rather a more nuanced "long-run regressor matters" message.
- **Why it matters in v2**: This was flagged as MINOR-7 in v1. After cleaning the MAJOR/MED block, this becomes the highest-severity remaining citation-fidelity issue, so I am promoting it to **v2 MED-1**. A careful methodology referee at JoE / IJF could legitimately query whether the citation supports the §2.3 framing.
- **Suggested fix**: Soften L78 to e.g.:
  > \citet{conrad2020} systematically evaluate which macro long-run components in GARCH-MIDAS specifications deliver out-of-sample improvements, finding that the in-sample-fit-to-OOS-accuracy mapping is variable-specific: housing starts deliver significant OOS gains at 2--3-month horizons, while several other macro components fail to translate in-sample fit into out-of-sample improvement.
- **Severity rationale**: MED rather than MAJOR because the cite still anchors a defensible reading of Conrad-Kleen (i.e., the result for non-housing-starts variables IS in-sample-good-OOS-fail) — but the current wording over-generalizes a paper-specific positive result.

### 3.3 MINOR (5)

#### v2 MINOR-N1 (NEW): `andrews1991` is alphabetically misplaced

- **Bib key**: `andrews1991`
- **Location**: L381 (between `adrian2016` L375 and `akyildirim2020` L387)
- **Problem**: APA alphabetical ordering on surname requires:
  - Adrian (A-d) → **Akyildirim (A-k)** → **Andrews (A-n)** → Bouri (B-o) → ...

  Current ordering is Adrian → Andrews → Akyildirim, which violates A-k < A-n. `printf 'Akyildirim\nAndrews\n' | sort` confirms `Akyildirim` comes first.
- **Why it matters**: Cosmetic but will be flagged by Elsevier / Wiley copy-editors for journals like *Economics Letters*, *IJF*, *JoE*. Trivial 1-block-swap fix.
- **Suggested fix**: Move `andrews1991` block (L381--L385) to between `akyildirim2020` (L387--L391) and `bouri2020` (L393--L397) — i.e., insert after L391.

#### v2 MINOR-2 (carried from v1 MED-4): `harvey2016` |t|>3 threshold transfer footnote

- **Status**: Defer-to-copy-edit. v1 flagged as MED but it is a methodological footnote suggestion not a citation-substance error. Demoted to MINOR for v2 since main.tex already cites `harvey2016` faithfully (the threshold IS proposed by Harvey-Liu-Zhu); transferring the threshold to a single-predictor time-series setting is methodologically commonplace.
- **Suggested fix**: Optional one-sentence footnote at L50 acknowledging the cross-sectional / time-series transfer (verbatim from v1 report).

#### v2 MINOR-3 (carried from v1 MED-5): `iyer2022` peer-review tier flagging

- **Status**: Defer. §2.2 ¶4 already labels Iyer as "IMF policy note" (L72). v1 said "NOT blocking". No further action.

#### v2 MINOR-4 (carried from v1 MINOR-3): `koenker1978` "Bassett, Jr." spelling

- **Status**: Cosmetic, defer.

#### v2 MINOR-5 (carried from v1 MINOR-5): §6.3 ETF cutoff date footnote

- **Status**: Not added in v2. Current L305 reads: "we partition the 2023--2026 sample at 2024-01-11 (the ETF launch date)". Semantically correct (trading-launch is the relevant cutoff). Footnote distinguishing SEC approval (2024-01-10) from trading launch (2024-01-11) would save a reviewer round-trip but is not blocking.

---

## 4. New Bibitem `andrews1991` Verification Table

| Field | Bibitem entry (main.tex L381--L385) | Web-verified ground truth | Match? |
|---|---|---|---|
| Bib key | `andrews1991` | — (internal) | — |
| Author | Andrews, D.W.K. | Donald W. K. Andrews (Econometric Society canonical) | ✓ |
| Year | 1991 | 1991 (May 1991, Econometrica vol. 59 issue 3) | ✓ |
| Title | "Heteroskedasticity and autocorrelation consistent covariance matrix estimation" | "Heteroskedasticity and Autocorrelation Consistent Covariance Matrix Estimation" | ✓ (capitalization differs but APA-style sentence-case is acceptable) |
| Journal | *Econometrica* | *Econometrica* | ✓ |
| Vol/Issue/Pages | 59(3):817--858 | 59(3):817-858 | ✓ |
| DOI | 10.2307/2938229 | JSTOR 2938229 (canonical Econometrica DOI for vol 59 issue 3 pp 817-858) | ✓ |
| `\url{}` line present? | YES (L385) | — | ✓ |
| APA format byte-pattern vs sibling entries | Matches `\bibitem[Author, Year]{key}` + author + `\newblock` title + `\newblock {\em Journal}, vol(issue):pp--pp.` + `\newblock \url{...}` — identical pattern | — | ✓ byte-identical pattern |

### In-text usage verification (§4.1 L131)

- **Cite location**: L131--L132, in §3.2.1 (Symmetric Granger) — see grep result: "the automatic bandwidth selection rule of \citet{andrews1991}, the default specification used by the \texttt{statsmodels.tsa.stattools.grangercausalitytests} routine"
- **Source paper claim** (web-verified): The 1991 Econometrica paper "introduces data-dependent automatic bandwidth/lag truncation parameters" using "asymptotically optimal kernel/weighting scheme and bandwidth/lag truncation parameters" via a minimax MSE approach.
- **Verdict**: **Faithful citation.** The main.tex framing — "automatic bandwidth selection rule of Andrews (1991)" used in the Newey-West HAC kernel — is exactly what Andrews 1991 contributes. The cite supports the claim it anchors. ✓
- **Caveat (NOT a defect)**: Andrews 1991 covers a class of HAC kernels (Bartlett, Parzen, QS, etc.); calling it the "Newey-West kernel with the automatic bandwidth selection rule of Andrews 1991" is the textbook standard combination (Newey-West 1987 kernel = Bartlett kernel; Andrews 1991 = automatic bandwidth). The phrasing is methodologically conventional and not over-claiming.

---

## 5. v2 Sample-Period & Narrative Audit (commits 13638cd2 + 8a68fdc5)

- **\cite usage**: All 22 bibitems are cited in-text exactly once or more (extracted via `grep -oE '\\cite[ptp]?\{[^}]+\}' | sort -u`):
  ```
  adrian2016, akyildirim2020, andrews1991, bouri2020, conlon2020, conrad2020,
  corbet2018, diebold1995, diebold2009, diebold2012, diebold2014network,
  diks2006, harvey1997, harvey2016, hatemi2012, hong2001, iyer2022, klein2018,
  koenker1978, matkovskyy2019, shahzad2019, yarovaya2022
  ```
  → 22/22 used. **No orphan bibitems.**
- **\cite without bibitem**: None — all 22 cite-keys resolve to a bibitem.
- **§1 narrative flow** (v2.2 L52 area, sample-period extension): Reads correctly. The Introduction's six paragraph blocks (asymmetry / tail / regime / forecast-gap / contributions / roadmap) all cite within the bibliography. No \cite is orphaned by the v2.2 narrative tightening.

---

## 6. Bibliography Health Audit (22 bibitems)

| # | Bib key | DOI present? | URL line correct? |
|---|---|---|---|
| 1 | adrian2016 | ✓ 10.1257/aer.20120555 | ✓ |
| 2 | akyildirim2020 | ✓ 10.1016/j.frl.2019.06.010 | ✓ |
| 3 | andrews1991 (NEW) | ✓ 10.2307/2938229 | ✓ |
| 4 | bouri2020 | ✓ 10.1016/j.qref.2020.03.004 | ✓ |
| 5 | conlon2020 | ✓ 10.1016/j.frl.2020.101607 | ✓ |
| 6 | conrad2020 | ✓ 10.1002/jae.2742 (NEW v2.1) | ✓ |
| 7 | corbet2018 | ✓ 10.1016/j.econlet.2018.01.004 | ✓ (title fixed v2.1) |
| 8 | diebold1995 | ✓ 10.1080/07350015.1995.10524599 (NEW v2.1) | ✓ |
| 9 | diebold2009 | ✓ 10.1111/j.1468-0297.2008.02208.x | ✓ |
| 10 | diebold2012 | ✓ 10.1016/j.ijforecast.2011.02.006 | ✓ |
| 11 | diebold2014network | ✓ 10.1016/j.jeconom.2014.04.012 | ✓ |
| 12 | diks2006 | ✓ 10.1016/j.jedc.2005.08.008 | ✓ |
| 13 | harvey1997 | ✓ 10.1016/S0169-2070(96)00719-4 | ✓ |
| 14 | harvey2016 | ✓ 10.1093/rfs/hhv059 (NEW v2.1) | ✓ |
| 15 | hatemi2012 | ✓ 10.1007/s00181-011-0484-x | ✓ |
| 16 | hong2001 | ✓ 10.1016/S0304-4076(01)00043-4 | ✓ |
| 17 | iyer2022 | ✓ 10.5089/9781616358068.065 | ✓ |
| 18 | klein2018 | ✓ 10.1016/j.irfa.2018.07.010 | ✓ |
| 19 | koenker1978 | ✓ 10.2307/1913643 | ✓ |
| 20 | matkovskyy2019 | ✓ 10.1016/j.frl.2019.04.007 | ✓ |
| 21 | shahzad2019 | ✓ 10.1016/j.irfa.2019.01.002 | ✓ |
| 22 | yarovaya2022 | ✓ 10.1016/j.intfin.2022.101589 | ✓ |

**Result**: **22/22 entries have DOI URLs. Zero missing DOI.** Replication-package quality bar is satisfied for citation hygiene.

**Alphabetical order**:
- ✓ harvey1997 → harvey2016 (fixed v2.2)
- ✗ adrian2016 → andrews1991 → akyildirim2020 (BROKEN — should be Adrian → Akyildirim → Andrews) — **see v2 MINOR-N1**
- ✓ All other entries alphabetically ordered.

---

## 7. Final Verdict

| Severity | Count | Items |
|---|---|---|
| **MAJOR** | **0** | — |
| **MED** | **1** | v2 MED-1: `conrad2020` §2.3 ¶1 framing softening (carried-forward from v1 MINOR-7) |
| **MINOR** | **5** | N1 (NEW: andrews1991 alphabetical position), 2 (harvey2016 transfer footnote, deferred), 3 (iyer2022 tier flag, deferred), 4 (koenker1978 Bassett-Jr cosmetic), 5 (ETF cutoff date footnote) |

**Blocks review-stage upgrade?**  **NO.**

The v2 revision pass closed the single MAJOR (corbet2018 title + author order) and all three mechanical-DOI MEDs cleanly. The remaining 1 MED is a copy-edit-class framing softening that does not require holding the paper at the current review stage — it can be addressed in any subsequent revision pass before `ready_for_submission`. The remaining 5 MINORs are all defer-to-copy-edit (cosmetic, footnote-polish, and one trivial 1-block-swap for the new andrews1991 bibitem).

**Recommended actions (non-blocking)**:
1. Optional single-line softening of L78 (`conrad2020` framing) — addresses v2 MED-1.
2. Trivial swap of `andrews1991` block to between `akyildirim2020` and `bouri2020` — addresses v2 MINOR-N1.
3. Footnote polish at §6.3 L305 (ETF cutoff date) and §1 L50 (Harvey-2016 threshold transfer) — defer to final copy-edit pass.

**Improvement vs v1**: 1 MAJOR / 5 MED / 7 MINOR → 0 MAJOR / 1 MED / 5 MINOR. Net -1 MAJOR / -4 MED / -2 MINOR. Single revision pass closed 6/13 v1 issues at the byte level + N-1 newly introduced issue (alphabetical order). **Citation quality now publication-ready** modulo defer-to-copy-edit polish.

---

*End of citation_check_report.md v2*
