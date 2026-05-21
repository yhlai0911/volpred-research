# P10 Crypto Fear Channel — v1 Academic Review Report

**Reviewer**: latex-academic-reviewer (Claude main thread)
**Date**: 2026-04-28
**File reviewed**: `paper/crypto-fear-channel/main.tex` (494 lines, 15 pages, 6 tables, 19 bibitems)
**Source experiments**: K1025 (primary), K639 + K746b (lemmas)
**Reproduce status**: 29/29 byte-match GREEN, alert_level=green
**Target journals**: JIMFIM (1st) / JEF (2nd) / FRL (backup)

---

## 1. Overall Assessment (10-dimension scoring, 1–5★)

| # | Dimension | Score | Comment |
|---|-----------|------|---------|
| 1 | Logic flow (abstract→§9) | 4.0 | Spine is clean: three stylized facts + OOS null + reconciliation. Section ordering OK; one weak transition in §6→§7 (robustness ends without explicit hand-off to OOS) |
| 2 | Argument quality / honest reporting | **4.5** | Joint reporting of in-sample success + OOS null + Granger≠forecastability lesson is exemplary. §8.2 reconciliation is the strongest section in the paper |
| 3 | Methodology self-containedness | 3.5 | §4.1–§4.5 readable; but Hatemi-J cumulative-vs-first-difference notation in §3.2 vs §4.2 is **internally inconsistent** (see SEVERE-1). HAC kernel/bandwidth not specified |
| 4 | Equation correctness & clarity | 3.5 | 4 numbered equations OK structurally; eq:granger_unrestricted lacks the same lag-pattern-test notation as eq:granger_asym; §3.2 RV+/- definition contradicts the "cumulative" wording in §4.2 |
| 5 | Symbol consistency (§1–§9) | 3.5 | RV(20) vs RV^btc vs RV^{btc,+} sometimes uses superscript-as-window-length, sometimes superscript-as-asset-tag; β_τ used cleanly; γ in eq:oos_aug appears once and never again referenced in OOS narrative |
| 6 | Citation grounding (5 threads) | 4.0 | 19 bibitems all logically mapped; harvey1997 is cited in T6 caption but never in body §4.5 prose (MED). conrad2020 cited in 3 places consistently |
| 7 | Structure / sequencing | 4.0 | 9 sections well-paced; §5 three subsections asym→QR→regime is correct logical order. §6 robustness 3 subsections cleanly mapped to §5 results. §8.4 limitations is honest |
| 8 | Honest reporting (§7 OOS, §8.2 reconciliation, §8.4 limits) | **4.5** | Best feature of the paper. §8.2 Granger≠forecastability methodological lesson is publication-worthy in itself; §8.4 admits sample limits, intraday gap, altcoin gap |
| 9 | Tables (T1–T6 self-containedness) | 3.5 | All have footnotes + sources, but T1 missing skew/kurt for VIX & RV^btc rows (dashed); T5 DCC mean/median ordering by regime monotonicity has a non-monotone in Crisis (0.41 < 0.45 in High) which is documented but not flagged as economically meaningful |
| 10 | First-time-paper fundamentals (typos / xref / citation format / equation numbering) | 3.0 | **CRITICAL-1**: §3.3 line 94 inverts the BTC vs SPY kurtosis comparison (claims BTC fatter-tailed but cites SPY's 14.15 as the higher number). Several MED cross-ref issues and 1 hard-coded "Section 3" instead of \ref. 4 LaTeX overfull/underfull boxes |

**Weighted overall**: ★★★★ (3.95 / 5)

---

## Verdict Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 1 |
| SEVERE   | 3 |
| MAJOR    | 5 |
| MED      | 9 |
| MINOR    | 7 |

**Total issues**: 25 (typical for a v1 first-pass review; on the lower end for a 15-page draft, reflecting solid first-draft quality from 5-slot main-thread writing).

---

## Issues by Severity

### CRITICAL (correctness; must fix before any external read)

#### CRITICAL-1 — Inverted BTC vs SPY kurtosis claim (§3.3, line 94)

**Location**: line 94
**Current text**:
> BTC daily returns exhibit mean 0.23%, daily standard deviation 3.76%, and excess kurtosis 7.58 — **materially fatter-tailed than SPY (14.15 excess kurtosis** is concentrated in a handful of crisis days), reflecting the well-documented heavy-tailed nature of cryptocurrency returns.

**Problem**: The numbers in Table 1 (verified against `reproduce_report.json` 29/29 GREEN) show:
- BTC excess kurtosis = 7.579
- SPY excess kurtosis = 14.150

So **SPY is actually more leptokurtic than BTC** in this sample. The claim "materially fatter-tailed than SPY" is the **opposite of what the data show**. The parenthetical "(14.15 excess kurtosis is concentrated in a handful of crisis days)" reads as an apologetic for SPY's higher number, but the surrounding sentence still asserts the opposite ranking.

**Why CRITICAL**: First-page-after-abstract sanity-check; any referee at JIMFIM/JEF will flag this on page-one and likely desk-reject for arithmetic mismatch with Table 1. The Table is correct; the prose is wrong.

**Suggested fix**: Rewrite to match data. E.g.:
> BTC daily returns exhibit mean 0.23%, daily standard deviation 3.76%, and excess kurtosis 7.58. While BTC has the well-documented heavy-tailed return distribution, SPY's higher excess kurtosis (14.15) reflects the concentration of crisis-day jumps in the equity index over our sample window — a distinct phenomenon driven by COVID-2020 and 2022. BTC's heavy-tail signature is in the bulk of its day-to-day distribution (volatility of 3.76% vs SPY's 1.12%), not in extreme outliers.

This rewrites the comparison around **return volatility** (where BTC dominates 3.4×) rather than **excess kurtosis** (where SPY actually dominates due to crisis concentration), and removes the factually-wrong phrase.

---

### SEVERE (methodology / specification clarity; review-blocking)

#### SEVERE-1 — Hatemi-J decomposition: "cumulative" vs first-difference is internally inconsistent (§3.2 line 90 vs §4.2 line 136)

**Location**: lines 90, 136
- Line 90 (Data §3.2): defines `RV^{btc,+}_t = max(ΔRV^btc_t, 0)` and `RV^{btc,-}_t = -min(ΔRV^btc_t, 0)` — **this is the first-difference / innovation form**
- Line 136 (Methodology §4.2): "we decompose BTC realized-volatility innovations into positive and negative **cumulative** components" — **this is the cumulative form** following Hatemi-J's original formulation

**Problem**: Hatemi-J (2012) decomposes a series into cumulative positive innovations $X^+_t = \sum_{i=1}^{t} \max(\varepsilon_i, 0)$ and cumulative negative innovations $X^-_t = -\sum_{i=1}^{t} \min(\varepsilon_i, 0)$. The data §3.2 definition is the **non-cumulative** (per-period) form. The two are not equivalent and produce different test results.

K1025 source data (per `reproduce_report.json` GREEN gate) presumably implements one specific form; the paper text contradicts itself about which.

**Why SEVERE**: A referee with Hatemi-J expertise will catch this immediately; reproducibility hangs on which form is used. Affects table interpretation.

**Suggested fix**:
1. Verify in `experiments/k1025/k1025.py` which form is actually computed.
2. Update §3.2 line 90 to match. If first-difference form is used (likely, given the simpler definition), §4.2 should say "we decompose BTC RV innovations into positive and negative components ($\Delta RV^+$, $\Delta RV^-$)" and drop "cumulative" (or cite a non-cumulative variant of Hatemi-J).
3. If cumulative form is used, §3.2 should write $X^{btc,+}_t = \sum_{i=1}^{t} \max(\Delta RV^{btc}_i, 0)$.

---

#### SEVERE-2 — HAC standard-error specification missing across all four eq blocks (§4.1, §4.2, §4.5; line 131, 138, 166)

**Location**: §4.1 line 131 ("HAC standard errors"), §4.2 line 141, §4.5 line 166 ("HAC standard errors per Diebold-Mariano")
**Problem**: The paper invokes "HAC standard errors" and "small-sample adjustment of Harvey 1997" (line 323) but never specifies:
- Kernel choice (Bartlett, Quadratic Spectral, Parzen?)
- Bandwidth selection rule (Newey-West 1994 automatic? Andrews 1991? Fixed bandwidth?)
- Whitening pre-filter?

**Why SEVERE**: For a top-tier journal with reviewer expertise (JIMFIM editorial board includes time-series econometricians), unspecified HAC choices are a standard reject-or-revise trigger. Any DM-type test result is sensitive to bandwidth.

**Suggested fix**: Add one sentence per §4.1 / §4.2 / §4.5: "HAC standard errors use the Bartlett kernel with bandwidth selected by the Newey-West (1994) automatic data-driven rule." (or whatever K1025 actually implements — verify in code).

---

#### SEVERE-3 — γ in eq:oos_aug (line 163) never tested or reported

**Location**: line 163, eq:oos_aug
**Problem**: The augmented forecast specification adds `γ · RV^{(20)}_{btc, t-1}` with a single coefficient γ. The OOS section §7 reports only the DM test on **forecast loss differences** (MSE, MAE, QLIKE) — but never reports the in-sample value of γ̂ in the rolling estimation, its t-stat, or its sign stability across the rolling window. A referee will ask: "is γ̂ even significant in-sample within the OOS window? If γ̂ ≈ 0 in-sample, OOS DM null is mechanical."

**Why SEVERE**: Reduces the OOS-null result from "informative null" to "uninformative" if γ̂ itself is insignificant in-sample. Joint reporting requires both.

**Suggested fix**: Add a sentence to §7 (after line 307): "Within the OOS rolling window, the augmented model's γ̂ averages [X] with median t-stat [Y]; the in-sample regression of VIX_t on lagged BTC RV alone yields γ̂ = [Z], t = [W] (significant in-sample), confirming that the OOS-DM null is not a mechanical artifact of an uninformative regressor." Pull these from K1025 if computed; if not, add to reproduce.py.

---

### MAJOR (literature / coverage / structural; revision-required)

#### MAJOR-1 — Five-thread literature claim in §1.2 says four building blocks but text lists five thread topics

**Location**: §2 line 57 ("Each thread has progressed independently") + line 65 ("our four building blocks")
**Problem**: §2 first paragraph (line 57) lists three threads: spillover/safe-haven, methodological building blocks, OOS evaluation. §2.2 (line 65) says "our four building blocks" (asymmetric Granger / QR / DY / DM) — but §4 lists **five** subsections (4.1 symmetric Granger, 4.2 asymmetric Granger, 4.3 QR, 4.4 DY, 4.5 DM). Symmetric Granger as the baseline is not a "building block" per the lit-review wording, yet it has its own subsection in §4.

**Suggested fix**: Either (a) §4.1 symmetric Granger demoted to a paragraph inside §4.2 as "baseline check" (cleaner; matches "four building blocks" framing), or (b) §2.2 updated to "four building blocks plus a symmetric-Granger baseline check." Option (a) is preferred — symmetric Granger contributes nothing the asymmetric test does not, except as the baseline already discussed in §5.1 last paragraph.

---

#### MAJOR-2 — §1 "five subperiod breakdown" but list cites 5 names; abstract says "5 subperiods" but only 4 fail to reject (line 27)

**Location**: abstract line 27
**Problem**: "in a five-subperiod breakdown, Granger causality is statistically significant only during 2020 ... and **non-significant in 2015–2017, 2018–2019, 2021–2022, and 2023–2026**" — the four-region listing is correct, but the abstract should explicitly note this is "four of five." Currently a reader might misparse the four-region listing as covering all subperiods.

**Suggested fix**: Rewrite as "Granger causality is statistically significant only during 2020 ... and non-significant in the other four subperiods (2015–2017, 2018–2019, 2021–2022, 2023–2026)."

---

#### MAJOR-3 — Spillover index variation magnitude inconsistent across §5.3 and §6.1 (lines 275, 286)

**Location**: §5.3 line 275 and §6.1 line 286
- Line 275: "the total spillover index averages 90.1% with very low variation (std. 0.21%)" — **0.21% as a fraction**
- Line 286: "mean is 90.11% with a standard deviation of only 0.21%" + "ranging from a minimum of 89.79% to a maximum of 90.81%" — range of about 1.0pp

**Problem**: Internal arithmetic check: if mean ≈ 90.11 and std ≈ 0.21 percentage points, range of [89.79, 90.81] = 1.02pp ≈ 4.86 standard deviations of spread. That's plausible for an 11-year sample with ~512 windows IF the index is bounded near 90% (which would suggest the underlying data is structurally stable). But the labeling is ambiguous: is "0.21%" a relative percentage (i.e., 0.21% of 90.11 = 0.19pp std) or an absolute percentage point?

The K1025 source (alongside the rolling 252-day spillover series) needs to clarify whether `spillover_std` is in pp or relative %.

**Suggested fix**: Make units explicit in both lines: "std. = 0.21 percentage points" (not "0.21%" which is ambiguous). Verify against K1025 JSON `.spillover_index.total_std` units.

---

#### MAJOR-4 — Subperiod count mismatch in robustness §6.1 line 287 ("variance-decomposition shares move by less than 1 percentage point") vs §5.3 wording

**Location**: line 287
**Problem**: §6.1 says "variance-decomposition shares move by less than 1 percentage point even as the within-period Granger F-statistic ranges from 0.23 (crypto winter) to 11.05 (COVID-2020)" — but the "0.23" claim is for **crypto winter (2018–2019)**, while Table 4 reports 2018–2019 F = 0.23 with p = 0.630 (matches). The minimum F across the full subperiod table is actually **0.23 at 2018–2019** (not 0.46 at 2023–2026 nor 0.59 at 2015–2017). Confirmed correct. **No fix needed**, but the inline grouping of "0.23 to 11.05" should explicitly note these are the min and max across the 5 subperiods to avoid confusion.

**Suggested fix**: "the within-period Granger F-statistic ranges from a minimum of 0.23 (2018–2019 crypto winter) to a maximum of 11.05 (COVID-2020) — a 48× spread."

---

#### MAJOR-5 — §1 line 52 hard-codes "Section 3" through "Section 9" instead of using \ref

**Location**: line 52
**Current**:
> Section~\ref{sec:lit} surveys ... **Section 3 describes the data ... Section 4 details ... Sections 5 and 6 ... Section 7 ... Section 8 ... Section 9 concludes.**

**Problem**: Only `\ref{sec:lit}` is used; the rest are hard-coded numbers. If section ordering changes during revision (which it likely will after review), these numbers will silently desync.

**Suggested fix**: Replace each "Section N" with `\S\ref{sec:data}`, `\S\ref{sec:methodology}`, `\S\ref{sec:results}`, `\S\ref{sec:robustness}`, `\S\ref{sec:oos}`, `\S\ref{sec:discussion}`, `\S\ref{sec:conclusion}` — all labels exist (verified).

---

### MED (writing quality / minor methodology / referee anticipation)

#### MED-1 — §1 "five methodological building blocks" (line 52) contradicts §2 "four building blocks" (line 65)

**Location**: line 52 vs line 65
**Problem**: §1 last paragraph: "Section 4 details the **five** methodological building blocks." §2.2 first sentence: "Our **four** building blocks each have a settled methodological literature." Choose one.

**Suggested fix**: Match MAJOR-1's resolution. If §4.1 stays as a separate subsection, both should say "five." If §4.1 is merged into §4.2's baseline paragraph, both should say "four."

---

#### MED-2 — Quantile list inconsistency: §1 abstract uses 4 quantiles {0.05, 0.25, 0.50, 0.95} but §5.2 Table 3 reports 5 quantiles including 0.75

**Location**: abstract line 27, §4.3 line 146, Table 3 (line 211–225)
**Problem**: Abstract reports {τ=0.05, 0.25, 0.50, 0.95}. §4.3 line 146: "we estimate quantile regressions of VIX on BTC realized variance at four representative quantiles τ ∈ {0.05, 0.25, 0.50, 0.95}." Table 3 actually shows **five** quantiles {0.05, 0.25, 0.50, 0.75, 0.95}, all reported.

**Suggested fix**: Update §4.3 line 146 to "five representative quantiles τ ∈ {0.05, 0.25, 0.50, 0.75, 0.95}" and update abstract line 27 to mention τ=0.75 (β = +8.76) as the intermediate-positive transition between median and upper-tail. The current abstract elides the 0.75 quantile and creates a discontinuous jump from 2.61 → 22.31 that obscures the smooth amplification pattern.

---

#### MED-3 — DCC correlation "monotonically rises ... then drops in Crisis" (§5.3 line 254) but text says "rises monotonically"

**Location**: line 254, Table 5
**Problem**: Line 254: "the mean BTC-SPY DCC correlation **rises monotonically** from 0.07 in the Low regime to 0.27 in Normal, 0.45 in High, and 0.41 in Crisis." But 0.45 → 0.41 is **not monotone**; it's a slight non-monotonic drop in the Crisis regime.

**Why MED**: Plausibly the small-sample noise (Crisis n=63), but the prose contradicts itself by saying "monotonically" while showing 0.45 → 0.41.

**Suggested fix**: "rises **near-monotonically** from 0.07 in Low to 0.27 in Normal, peaking at 0.45 in High, and remaining elevated at 0.41 in Crisis (the slight Crisis dip reflects the small Crisis-regime sample of n=63)."

---

#### MED-4 — Forecasting OOS window starts 2019-01-01 but training uses "2015-02 to 2018-12" — burn-in is only 4 years

**Location**: §4.5 line 161
**Problem**: §4.5 says "lag length selected by AIC on the in-sample window (2015-02 to 2018-12)." Four years of daily data (~1,000 obs) is on the lower end for AIC-based lag selection on a 10-lag candidate set — particularly for VIX which has known long-memory features (cf. Bollerslev-Mikkelsen). A referee will ask whether AIC was re-selected on a rolling basis or fixed at the burn-in choice.

**Suggested fix**: One sentence: "AIC lag length p was selected once on the burn-in window 2015-02 to 2018-12 (best p = [N]) and held fixed across the rolling re-estimation; results are robust to BIC and SIC selection (unreported)." Verify against K1025 implementation.

---

#### MED-5 — harvey1997 cited only in T6 caption (line 323), not in body §4.5

**Location**: line 323 (Table 6 footnote) and §4.5 line 166
**Problem**: §4.5 line 166 cites only `\citet{diebold1995}` and `\citet{harvey2016}`. The Harvey-Leybourne-Newbold (1997) small-sample adjustment is mentioned only in T6 caption.

**Why MED**: Citation hygiene. Body should cite where the methodology is described; tables corroborate.

**Suggested fix**: Add to §4.5 line 166 after "...test of equal predictive accuracy": "with the small-sample adjustment of \citet{harvey1997}".

---

#### MED-6 — Symbol RV^{(20)} vs RV^{btc} inconsistent across body (window length vs asset tag in superscript)

**Location**: throughout
- §3.2 line 88: $\text{RV}^{(20)}_t$ (window in superscript)
- §3.2 line 90: $\text{RV}^{\text{btc},+}$, $\text{RV}^{\text{btc},-}$ (asset+sign in superscript)
- §4.2 eq (line 138): $\text{RV}^{\text{btc},+}_{t-j}$
- §4.5 eq (line 163): $\text{RV}^{(20)}_{\text{btc}, t-1}$ (window in superscript, asset in subscript)

**Problem**: Mixed convention. Reader has to parse whether "(20)" is window length or RV order; whether "btc" lives in superscript (with sign) or subscript (with time).

**Suggested fix**: Pick one convention. Recommended: $\text{RV}^{(h)}_{a,t}$ with $h$ = window length (always 20-day), $a$ = asset (btc/spy), $t$ = time. For asymmetric branches: $\text{RV}^{(h),\pm}_{a,t}$. Apply consistently.

---

#### MED-7 — Eq:granger_unrestricted (line 128) cuts off the joint-test wording; missing F-stat formula

**Location**: §4.1 line 128
**Problem**: Eq (1) writes the unrestricted regression but then describes the F-test only narratively: "the joint null H_0: β_1=...=β_ℓ=0 is tested with a standard F-test under HAC standard errors." A reader new to the asymmetric-vs-symmetric distinction expects an explicit Wald or LR statistic equation, especially since eq:granger_asym does not.

**Why MED**: Replication-friendly papers in JIMFIM/JEF show the test statistic formula. Style-wise, brief; substance-wise, minor.

**Suggested fix**: Add: "The Wald statistic $W_\ell = (\hat{\beta}'_\ell V_{HAC}^{-1} \hat{\beta}_\ell) / \ell$, computed under HAC standard errors $V_{HAC}$, is asymptotically $\chi^2_\ell$ under the null and $F_{\ell, T-2\ell-1}$-distributed in finite samples." (Or a footnote pointing to a standard reference.)

---

#### MED-8 — Footnote on lag-1 vs lag 2-10 (line 201) is the most important interpretive nuance but is only a sentence

**Location**: §5.1 line 200–201
**Problem**: The lag-1 symmetric Granger non-rejection (F = 0.64, p = 0.42) versus the lag-1 asymmetric significance (F = 18.96 for downside) is a substantive empirical point that quantifies why asymmetric decomposition matters. Currently delivered in 2 sentences and tucked at end of §5.1. Deserves visibility — either an inset box, footnote with formal interpretation, or a "Reading the two tests jointly" subsubsection.

**Suggested fix**: Add a small "Asymmetric vs symmetric Granger: lag-1 reading" inset paragraph or a methodology-flagged sentence: "The asymmetric decomposition recovers a **lag-1 signal that the symmetric test cannot disentangle**: the symmetric F-statistic at lag 1 (F = 0.64) averages over the contradictory contributions of the upside (β^+ = small positive) and downside (β^- = large positive) coefficients, producing a non-rejection. Once these are estimated separately as in eq:granger_asym, the F-statistic on the downside coefficient alone is 18.96. This is a clean illustration of why asymmetric and symmetric Granger are not interchangeable."

---

#### MED-9 — 4 LaTeX overfull/underfull boxes (lines 26–28, 156–157, 227–228, 232–233)

**Location**: log warnings
**Problem**: From `main.log`:
- Underfull \hbox at lines 26–28 (abstract paragraph break)
- Overfull \hbox 1.61pt at lines 156–157 (§4.4 sentence)
- Overfull \hbox 13.74pt at lines 227–228 (§5.2 wrap-up sentence)
- Overfull \hbox 4.68pt at lines 232–233 (§5.3 first paragraph)

**Why MED**: Will not block a desk review but show up as visible spacing artifacts in the PDF. Aesthetic but visible.

**Suggested fix**: For overfull hboxes, either rewrap with shorter words or insert `\linebreak` / `\sloppy` block. The 13.74pt overfull at line 227–228 is the most visible; rewriting that sentence with one shorter clause should fix it.

---

### MINOR (typos / cosmetic / future-proofing)

#### MINOR-1 — Line 52 "Section 3 describes the data and preliminary diagnostics" — but §3 title is "Data and Preliminaries", not "Data and Preliminary Diagnostics"

**Suggested fix**: "Section~\ref{sec:data} describes the data and preliminaries."

#### MINOR-2 — abstract line 26: "lags 1--5" then "(symmetric Granger tests covering lags 1--10 corroborate the broader directional result)" — parenthetical adds 1-10 result without explaining why "1--5" was chosen for asymmetric

The footnote on line 141 explains the lag window choice but the abstract doesn't get this context.

**Suggested fix**: Drop the parenthetical from abstract; mention lag-window justification in §4.2 footnote only (already there).

#### MINOR-3 — bibitem `harvey2016` (line 433) has "Harvey et al., 2016" key but `\citet` in §1 line 50 uses `\citet{harvey2016}` correctly. Bib title "...and the cross-section of expected returns" reads correctly but starts with "..." which may be a key-typing issue. Original title is "And the Cross-Section of Expected Returns". Verify.

#### MINOR-4 — `\citep` vs `\citet` mixed in §1.4 (line 50): "\citep{harvey2016, conrad2020}" used as parenthetical; consistent with §2.3 usage. OK.

#### MINOR-5 — VIX "min/max are 9.14 / 82.69" (line 111) but body line 94 reports rounded "9.1 / 82.7". Reasonable rounding consistency; not a bug.

#### MINOR-6 — Table 4 column order "Subperiod, N, Best lag, F, p" — order is fine, but the "Best lag" column header could be "p (lags)" or "AIC-best $\ell$" to match notation in §4.

#### MINOR-7 — `spy_btc_usd_vix_2015-2026.csv` (line 84) — clarify that this is the snapshot file, not the live yfinance pull. Already implied by "pinned to a fixed snapshot" but a referee skimming for replication will appreciate `(see \texttt{paper/crypto-fear-channel/data/data\_sources.md} for full source)`.

---

## Cross-Cutting Observations

### Strengths (preserve in v2)
1. **Honest joint reporting** of in-sample success + OOS null is the paper's signature contribution. §8.2 reconciliation is the clearest statement of the Granger≠forecastability methodological lesson I have seen in a single paragraph.
2. **Three-dimensional decomposition** (asymmetry / tail / regime) is well-integrated; not three disconnected sections but three lenses on one phenomenon.
3. **Robustness §6** maps cleanly onto §5 results — every headline finding has a corresponding robustness check.
4. **§8.4 limitations** is admissive without being defeatist; daily-frequency, COVID-confounding, and altcoin-omission limits are all real.
5. **5-subperiod breakdown** is a clever empirical design that quantifies regime-dependence in a way prior literature has missed.
6. **Reproduce gate GREEN** (29/29 byte-match) gives the paper a solid replication foundation.

### Weaknesses (address in v2)
1. **CRITICAL-1 inverted kurtosis claim is the most urgent** — fix in v2 round 1.
2. **HAC specifications must be explicit** for top-tier journal review.
3. **Hatemi-J cumulative vs first-difference decomposition** internal inconsistency could be flagged by any referee fluent in the technique.
4. **γ̂ in eq:oos_aug** is never reported in the OOS narrative; this is a gap relative to "honest reporting" standard.

### Strategic submission recommendations
- **JIMFIM (1st target)**: The honest joint reporting and methodological reconciliation (§8.2) align with the journal's interest in cross-market integration findings. **Predicted outcome**: R&R likely if CRITICAL-1, SEVERE-1/2/3 are addressed. The OOS-null result is unusual but the paper's "we don't hide it" framing is consistent with JIMFIM's editorial preference for empirical honesty.
- **JEF (2nd)**: JEF is more forecasting-focused; an in-sample-positive + OOS-null paper may face stronger scrutiny on whether the in-sample evidence is "real." With v2 fixes, R&R likely; without SEVERE fixes, desk reject possible.
- **FRL (backup short-form)**: For a 4,000–5,000 word condensed version focused on the asymmetric Granger + tail-amplification + OOS-null trio. FRL is less concerned with the methodological reconciliation (which is the paper's strongest section) so submitting to FRL would lose the strongest contribution.

---

## Recommendation: ★★★★ / 5 (3.95 weighted)

- Submit-ready after **CRITICAL-1 + 3 SEVERE fixes** (round 2). Round 2 will likely take 1 main-thread slot.
- v3 round to address all MED + MINOR (~1 main-thread slot).
- Total estimated effort to ready_for_submission: **2–3 review-revision cycles**.

**Predicted IJFMIM outcome**: R&R (high), then accept after one revision. Predicted JEF outcome: R&R (medium), then accept after 1–2 revisions. Predicted FRL: accept (high) but loses the methodological reconciliation contribution.

---

**Reviewer signature**: latex-academic-reviewer (Claude main thread)
**Round**: v1, first-pass
**Next round trigger**: after main thread implements CRITICAL-1 + SEVERE-1/2/3 fixes (estimated 1 slot), trigger v2 review (latex-academic-reviewer + citation-verifier in parallel).
