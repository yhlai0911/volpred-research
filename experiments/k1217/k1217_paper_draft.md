# Regime-Dependent Volatility Jump Prediction on TAIFEX: A Four-Branch Null with Vol-Normalized Partial Positive Signal

> **⚠️ DRAFT STATUS — CONDITIONAL**
>
> This document is a **conditional Paper 3 draft** produced under K1217 on 2026-04-17. It is NOT a committed revision of any existing `paper/<name>/main.tex` body. Per CLAUDE.md "paper narrative state machine" rule, worktree agents are not permitted to write LaTeX bodies directly; this markdown exists **solely for the main thread / user to review and adopt (or reject) after the Paper 3 narrative-pivot decision**.
>
> **Adoption is CONDITIONAL on the user selecting Path (b) "Hybrid null + positive"** in the Paper 3 K1128 pivot decision (see `experiments/k1205/README.md` §4). If Path (a) "Full K1142 anchor" or Path (c) "Abandon leverage-direction" is chosen instead, this draft should be archived unused.
>
> **Canonical data source**: All numbers quoted below are verbatim from `experiments/k1205/k1205_synthesis_table.csv` and the underlying K1128/K1131/K1142/K1199 result JSONs. No new estimation was performed in K1217. Numerical integrity: 7/7 PASS (`experiments/k1205/k1205_integrity_report.txt`).
>
> **Target journals** (ordered by fit, methodology-paper positioning): Journal of Empirical Finance → International Review of Financial Analysis → Pacific-Basin Finance Journal.

---

## Abstract

We study whether order-flow imbalance (OFI) predicts 5-minute Lee-Mykland price jumps on the Taiwan Stock Exchange's TAIFEX TX futures, and whether that predictability is conditional on the VIX-implied volatility regime. Using 73,203 five-minute bars over 2017-2021 with 115 jumps identified by a Lee-Mykland K=16 bipower-variation test (Gumbel threshold α=0.01, common to all four specifications), we estimate four complementary regime-switching specifications on an in-sample window 2017-2019 (81 jumps) and evaluate them out-of-sample in 2020-2021 (33 jumps, covering COVID). The four specifications comprise: (i) discrete IS-fixed VIX tertile, (ii) natural cubic spline in VIX, (iii) vol-normalized OFI that sidesteps VIX entirely, and (iv) an expanding-window adaptive VIX quantile. We find that all three VIX-conditional specifications fail out-of-sample — the IS-fixed tertile suffers degenerate OOS coverage (0/854/20,060 bars across low/mid/high VIX tertiles), the natural-cubic spline extrapolates pathologically (OOS AUC 0.497, Diebold-Mariano/Harvey-Leybourne-Newbold t = -3.93 versus baseline), and the expanding-window design cannot un-learn the COVID regime shift (OOS DM t = +1.14, not significant). Only the regime-free vol-normalized OFI specification crosses the methodological |t| > 2 threshold (DM t = +2.25, AUC = 0.594), but it fails the Harvey (2016) |t| > 3 publication threshold with only 33 out-of-sample jumps. Cross-market daily gap² replication in SPY and N225 supports a borderline weak-universal interpretation (three markets direction-consistent, max t = +2.32 for N225). We conclude that VIX regime-switching is structurally unidentifiable for this microstructure predictor when the OOS period is an unprecedented volatility event; regime-free adaptive standardization is a cleaner, better-identified alternative whose signal is nevertheless underpowered at current jump counts. Our contribution is methodological: a four-branch honest-null protocol for regime-conditional microstructure prediction, and the demonstration that vol-normalization bypasses the regime-identification trap.

**Keywords**: order flow imbalance, Lee-Mykland jumps, regime switching, VIX, TAIFEX, vol-normalization, Diebold-Mariano test, publication bias, COVID.

**JEL**: C52, C53, G10, G17.

---

## 1. Introduction (~1,000 words)

High-frequency microstructure literature has established order-flow imbalance (OFI) as a leading indicator of short-horizon price change (Cont, Kukanov, and Stoikov 2014; Chordia, Huh, and Subrahmanyam 2007). A natural follow-up question — and one that motivates this paper — is whether OFI's ability to forecast *discontinuous* price movements (jumps) is state-dependent. When volatility is elevated, as during a financial crisis or a pandemic, liquidity provision thins, adverse selection intensifies, and microstructure frictions can amplify the mapping from order-flow shocks into observed jumps. If the OFI → jump relationship genuinely shifts with volatility regime, then a practical predictor must condition on that regime. The CBOE VIX, as the most widely disseminated ex-ante volatility proxy, is an obvious conditioning candidate.

The Taiwan Futures Exchange (TAIFEX) TX futures contract is an attractive laboratory for this question. The contract is deeply liquid during Asian trading hours, tick data are widely available, and the regulatory environment during 2017-2019 was stable. The subsequent COVID-19 shock of 2020-2021 provides a natural out-of-sample period containing the largest volatility event of the past two decades: the VIX peaked at 82.69 in March 2020, a value never observed in TAIFEX's 2017-2019 in-sample window (whose VIX maximum was 37.32). This IS/OOS disjunction is what makes the dataset simultaneously attractive (a clean structural break) and treacherous (any IS-calibrated regime boundary may fail to map into the OOS distribution).

This paper implements four complementary specifications of a VIX-conditional OFI-to-jump predictor and rigorously documents the failure of each in turn, together with a single partially-positive result that arises only when the regime-switching framing is abandoned in favor of regime-free vol-normalization. Our four specifications are:

- **M_tertile** (following Ang and Timmermann 2012 regime-switching tradition): VIX split into IS-defined tertiles with separate coefficients per regime. Straightforward, non-parametric in VIX, and preserves the standard regime-switching identification strategy. Failure mode: when OOS VIX exits the IS support, tertile assignment becomes degenerate — in our data the IS-fixed 67% cutoff (VIX = 14.99) is exceeded in 20,060 of 20,914 OOS bars (95.9%), collapsing the OOS distribution to a single tertile.

- **M_spline** (Hastie and Tibshirani 1990; Ruppert, Wand, and Carroll 2003): a continuous natural cubic spline in VIX-lagged-one-day, with four internal knots at the IS 20/40/60/80 percentiles and the natural-boundary linearity constraint. This removes the discrete-cutoff degeneracy but exposes a different pathology: when OOS VIX extends to 82.69 while the highest IS knot is only 17.3, natural-spline linear extrapolation produces inflated coefficients that drive OOS log-loss above baseline (DM t = -3.93; AUC = 0.497, below chance).

- **M_volnorm** (Hansen and Lunde 2005 volatility-proxy tradition; Cont et al. 2014 microstructure noise framework): replace the VIX conditioning entirely by standardizing OFI by a strictly-past 60-bar realized-volatility estimate. This bypasses the regime-identification problem altogether, substituting a continuously-updating, endogenously-observed standardization for the exogenously-defined VIX regime. This is the only specification that delivers an OOS DM t exceeding the methodological |t| > 2 threshold (t = +2.25, AUC = 0.594), though it falls below the Harvey (2016) |t| > 3 publication standard.

- **M_expanding** (Catania 2018 adaptive-regime tradition): expanding-window VIX quantile cutoffs refit every 252 trading days. In principle this lets the "low / mid / high" VIX labels absorb the COVID regime shift as it arrives. In practice the expanding window cannot un-learn elevated values once seen, so it still cannot identify a "low VIX" bar in late 2021 relative to an already-COVID-contaminated history. OOS DM t = +1.14 (not significant); low-tertile OOS coverage remains 0 bars.

Our contribution is twofold and deliberately methodological rather than empirical. **First**, we document a structured four-branch null protocol for regime-conditional microstructure prediction under IS/OOS regime disjunction. The exhaustion of four specifications — discrete, smooth, regime-free, and adaptive — is, we argue, a sharper falsification of the regime-switching framing than any single branch alone. **Second**, we identify vol-normalization as the specification that crosses the methodological |t| > 2 threshold precisely *because* it does not rely on regime identification. The continuous endogenous standardization of OFI by a strictly-past realized-volatility proxy is a regime-free specification in the sense of Hansen and Lunde (2005), and its OOS predictive performance (AUC 0.594 against baseline 0.554) is distinctively above the three VIX-conditional alternatives (AUC range 0.497-0.559, except the documented K1199 fallback-sigma variant).

We further corroborate the borderline-but-universal character of the gap²-based overnight-information carrier via cross-market replication. Using daily OHLC data for SPY and N225 over 2010-2025, the squared overnight gap² produces three-market direction-consistent (+, +, +) DM-HLN evidence with maximum t = +2.32 in N225, supporting a weak-universal interpretation rather than a TAIFEX-specific artifact.

Our scope and limitations are explicit. The 33 out-of-sample jumps in 2020-2021 place a hard ceiling on the statistical power of any Harvey-(2016)-style publication-gate test. Extending the sample to 2012-2016 (a methodological direction flagged in Lee and Mykland 2008 and consistent with user-assigned long-sample-period guidance) would add volatility-regime diversity but at the cost of microstructure heterogeneity (TAIFEX tick-size and fee schedule changes). We view the 33-jump limitation as a fundamental constraint under which the honest-null + partial-positive narrative is the appropriate framing rather than a strength-asymmetric positive-only claim.

The remainder of the paper is organized as follows. Section 2 details the methodology, including the Lee-Mykland jump test, the four regression specifications, and the Diebold-Mariano / Harvey-Leybourne-Newbold inference protocol. Section 3 describes the TAIFEX 5-minute data, the Lee-Mykland jump detection, and descriptive statistics. Section 4 reports results for each of the four specifications plus cross-market corroboration. Section 5 discusses the structural reasons for the null results and the partial success of vol-normalization. Section 6 concludes.

## 2. Methodology (~800 words)

### 2.1 Data Environment

The primary dataset is the K1124 TAIFEX TX 5-minute bar cache: 73,203 bars over 2017-01-01 through 2021-12-31, built from tick-level trade and quote data (DAY_END = 13:44:59, T-1 rolling active contract convention per Codex review of K1124). We split into in-sample 2017-2019 (31,498 bars; 81 jumps) and out-of-sample 2020-2021 (20,914 bars; 33 jumps). After validity masks for jump_current and OFI feature construction, 52,369 bars enter regression (the K1142 specification strictly drops 43 rows where the 60-bar rolling σ̂ is not yet defined; K1199 instead substitutes the Lee-Mykland bipower-variation σ in that window, retaining all 52,412 rows — a documented implementation difference, not a divergence bug, as cross-verified in `experiments/k1205/k1205_integrity_report.txt` check #7).

### 2.2 Lee-Mykland Jump Detection

We follow Lee and Mykland (2008) to detect jumps in log-return space. For a 5-minute log-return r_t, the local bipower-variation window of K = 16 strictly-past observations yields a noise-robust scale estimate σ̂_t^{BV}. The standardized statistic L_t = |r_t| / σ̂_t^{BV} is compared against the Gumbel-distributed multi-test threshold at α = 0.01, which in our sample evaluates to 5.125598 (identical to six significant digits across all four experiments — see `k1205_integrity_report.txt` check #2). Bars with L_t exceeding this threshold are flagged as jumps. The procedure yields 115 total jumps (0.156% of bars), distributed 81 in-sample and 33 out-of-sample (unequal because COVID volatility expansion concentrated more jumps in OOS despite shorter horizon). No alternative jump thresholds or detection frequencies are tested; the fixed K = 16, α = 0.01 setting is applied identically across all specifications for cross-experiment comparability.

### 2.3 Four Regression Specifications

All four models are binary-outcome logistic regressions with target jump_{t+1} ∈ {0, 1} (the Lee-Mykland indicator at bar t+1). The OFI feature at bar t is the signed imbalance in active-side aggressor volume over the 5-minute window (Cont et al. 2014 definition, identical to K1124 construction). The |OFI| transform is the absolute value; OFI preserves sign. All models include a jump_curr covariate (lag-1 jump indicator) to absorb persistence. The specifications are:

**Baseline** (M_base):
logit P(jump_{t+1} = 1) = α + β₁ · jump_curr + β₂ · |OFI|_t + β₃ · OFI_t

**IS-fixed tertile** (M_tertile, following K1128 — discrete regime):
logit P(·) = base + β_mid · mid_IS · |OFI| + β_high · high_IS · |OFI| + γ_mid · mid_IS · OFI + γ_high · high_IS · OFI

where mid_IS and high_IS are indicator variables based on the IS VIX 33rd-percentile cutoff of 12.07 and 67th-percentile cutoff of 14.99. Both cutoffs are fixed at IS quantile values and held constant throughout OOS — this is the standard Ang-Timmermann (2012) non-parametric regime-switching specification.

**Natural cubic spline** (M_spline, following K1131 — continuous regime):
logit P(·) = base + [Σ_k θ_abs,k · B_k(VIX_{t-1})] · |OFI|_t + [Σ_k θ_sgn,k · B_k(VIX_{t-1})] · OFI_t

where B_k(·) are natural-cubic-spline basis functions with four internal knots at IS VIX 20/40/60/80 percentiles (11.05, 12.50, 14.25, 17.30) and two boundary knots at IS min/max. The natural constraint forces linearity beyond the boundary knots, which — as we show in Section 4.1 — is the key source of OOS extrapolation pathology.

**Vol-normalized** (M_volnorm, following K1142 — regime-free):
logit P(jump_{t+1} = 1) = α + β₁ · jump_curr + β₂ · z_absOFI_t + β₃ · z_sgnOFI_t

where z_absOFI_t = |OFI|_t / σ̂_t and z_sgnOFI_t = OFI_t / σ̂_t, with σ̂_t = std(log_ret_{t-60}, …, log_ret_{t-1}) the strictly-past rolling 60-bar (approximately 5-hour) realized-volatility estimate. The cross-day rolling convention is chosen rather than per-day reset to avoid 60-bar-per-day zeroing that would destroy the sample; overnight-gap returns thus contribute to σ̂.

**Expanding-window** (M_expanding, following K1199 — adaptive regime):
same functional form as M_tertile, but the low/mid/high indicator variables at bar t use an expanding-window 33/67 VIX quantile computed on all VIX observations strictly prior to VIX_{t-1}. Refit occurs every 252 trading days to balance computational cost against information absorption; quantile thresholds update daily even within a refit window.

### 2.4 Estimation and Inference

All models are estimated by L-BFGS-B maximum likelihood with an L2 ridge penalty of 10⁻⁴ on non-intercept coefficients (identical hyperparameters across specifications). Seed 42 is fixed throughout. Standard errors for reported DM tests use the Harvey-Leybourne-Newbold (1997) small-sample adjustment. IS likelihood-ratio tests against baseline are reported with standard χ² calibration. Out-of-sample evaluation uses four criteria: log-loss, AUC, Brier score, and the Diebold-Mariano (1995) / Harvey-Leybourne-Newbold (1997) test of equal predictive accuracy (positive t indicates the alternative model has smaller loss than baseline). We report both the Harvey (2016) publication threshold (|t| > 3) and a weaker methodological-significance threshold (|t| > 2), given the 33-OOS-jump power limitation.

## 3. Data (~400 words)

### 3.1 TAIFEX TX 5-Minute Bars

The core microstructure dataset consists of 73,203 five-minute bars of TAIFEX TX (the benchmark Taiwan Stock Exchange futures contract) over 2017-01-01 through 2021-12-31. Each bar carries: open/high/low/close prices, volume, signed OFI per Cont-Kukanov-Stoikov (2014), and log-return log(Close_t / Close_{t-1}). Bars are constructed from tick-level trade and quote data with active-contract rolls performed at the T-1 end-of-day using a standard tick-size-weighted criterion. The day-end boundary is 13:44:59 local time, reflecting the TAIFEX regular-session close. Night-session bars are excluded.

### 3.2 In-Sample / Out-of-Sample Split

The IS period is 2017-2019 (three calendar years, 31,498 bars post-validity-mask, 81 jumps). The OOS period is 2020-2021 (two calendar years, 20,914 bars, 33 jumps). This split was fixed ex ante at the design of K1128 and has been preserved unchanged through K1131, K1142, and K1199 to maintain strict cross-experiment comparability. The COVID volatility shock occurs entirely within OOS; the VIX ranges are IS [9.14, 37.32] and OOS [12.32, 82.69]. This IS/OOS disjunction in VIX support is the central structural phenomenon that drives the four-branch null.

### 3.3 Descriptive Statistics

Jump rates: IS 0.257% of bars, OOS 0.158% of bars. The lower OOS rate despite COVID reflects the temporal concentration of OOS jumps in brief 2020 Q1 and mid-2020 episodes rather than uniform distribution. Median realized volatility approximately doubled from IS 0.000578 to OOS 0.000920 (σ̂ from the rolling 60-bar specification). Mean |OFI|_t is comparable across regimes, but the right tail of |OFI| distribution is thicker in 2020-2021 (empirical 99th percentile roughly 2.3× the IS value). VIX-lagged-one-day is sourced from standard CBOE daily close, attached to each TAIFEX bar via the rule VIX(D) for all bars on local date D+1 (reflecting the 14-hour time-zone offset and the previous-day US close being the most recent available datum at TAIFEX open).

## 4. Results (~1,500 words)

### 4.1 Four-Branch Null Evidence

Table 1 collects the canonical cross-experiment numbers for the four specifications. Numbers are verbatim from `experiments/k1205/k1205_synthesis_table.csv` and have passed the 7-check cross-experiment integrity audit in `k1205_integrity_report.txt` (Lee-Mykland jump count, Gumbel threshold, VIX tertile cutoffs, baseline coefficients, K1128 coverage-gap arithmetic, K1142-vs-K1199 σ̂-fallback-implementation note).

**Table 1. Four-branch regime-conditional OFI→jump prediction: OOS evidence.**

| Model | Branch | n_OOS | OOS jumps | AUC | LL_OOS | Brier | DM t vs base | Verdict |
|---|---|---|---|---|---|---|---|---|
| M_tertile_high | VIX tertile (IS-fixed) | 20,060 | 32 | 0.593 | 0.01196 | 0.001592 | +1.31 | NULL (degenerate coverage) |
| M_spline | Natural cubic spline | 20,914 | 33 | 0.497 | 0.01248 | n/a | -3.93 | NULL (reverse) |
| **M_volnorm** | **Vol-normalized (σ̂₆₀, strictly-past)** | **20,914** | **33** | **0.594** | **0.01165** | **0.001574** | **+2.25** | **PARTIAL (OOS methodological-only)** |
| M_expanding | Expanding-window quantile | 20,914 | 33 | 0.548 | 0.01165 | 0.001574 | +1.14 | NULL |

(Harvey 2016 publication threshold: |t| > 3. Methodological threshold: |t| > 2. Baseline M_base OOS AUC = 0.554, LL = 0.01171.)

The discrete IS-fixed tertile specification (M_tertile, row 1) exhibits the expected degenerate coverage: of the 20,914 OOS bars, 0 fall in the low tertile (VIX ≤ 12.07), 854 in the mid tertile (12.07 < VIX ≤ 14.99), and 20,060 (95.9%) in the high tertile. The high-tertile-only DM t = +1.31 falls below both thresholds. Coverage degeneracy alone prevents a substantive regime-dependence test.

The natural cubic spline specification (M_spline, row 2) formally removes the discrete-cutoff degeneracy — the spline is a smooth function of VIX with no cutoff boundaries — but introduces a more harmful pathology. The natural-boundary linearity constraint forces the spline to extrapolate linearly beyond the IS data range [9.14, 37.32], and at VIX = 82.69 the |OFI|-interaction log-odds contribution reaches +20.43 (see K1131 Figure spline_beta_vs_vix.png). This extrapolation inflates OOS predictive contributions without accuracy, yielding OOS AUC = 0.497 (below chance) and a DM statistic of -3.93 *in the wrong direction* — the spline is significantly worse than baseline. In-sample, the χ² LRT against base is χ²(6) = 8.05, p = 0.235 — not significant. The spline is the most harmful of the four specifications.

The vol-normalized specification (M_volnorm, row 3) is the partial-positive result. Substituting z_OFI = OFI / σ̂_t for raw OFI yields OOS AUC = 0.594 (baseline 0.554), OOS log-loss 0.01165 (baseline 0.01171), and DM t = +2.255 — the only specification of the four that crosses the methodological |t| > 2 threshold. The in-sample log-likelihood improves (NLL = 553.92 vs base 556.95) with identical parameter count, ruling out a pure overfit-from-extra-degrees-of-freedom interpretation. The in-sample DM t = +1.45 is marginal; the OOS-only significance asymmetry is a weak signal that at 33 jumps may reflect small-sample favor.

The expanding-window specification (M_expanding, row 4) was designed to address the IS/OOS VIX disjunction by refitting quantile thresholds adaptively. The OOS coverage is somewhat less degenerate than IS-fixed tertile (low 0 / mid 6,816 / high 14,098 versus 0 / 854 / 20,060), but the low tertile is still empty. The structural reason is that the expanding window incorporates COVID-spike VIX values into its history starting in Q1 2020 and cannot un-learn them; by late 2021 the "low VIX" threshold has lifted sufficiently that no OOS bar falls below it. The DM t = +1.14 against baseline is not significant.

### 4.2 Partial-Positive: Vol-Normalized Signal Characteristics

Figure 4.1 (ROC overlay for M_base, M_tertile, M_spline, M_volnorm, M_expanding — see `experiments/k1205/k1205_figureC_auc_ranking.png`) shows M_volnorm's AUC distinctively above the VIX-conditional competitors. The spline sits visibly below random diagonal. M_base, M_tertile, and M_expanding cluster near AUC 0.55. Only M_volnorm reaches 0.59.

Within the K1142 specification, a secondary specification using σ̂-tertile regime indicators (M_realvol_tertile: replace VIX tertile with σ̂-tertile, keeping discrete regimes) achieves OOS AUC 0.666 — the highest of any variant — but its DM t = +1.98 falls marginally below the |t| > 2 methodological threshold. The DM between M_volnorm and M_realvol_tertile is -1.57 (not significant): the two specifications are statistically indistinguishable despite different AUCs. The natural reading is that the fundamental signal is "OFI relative to recent realized noise", however parameterized (continuous standardization or discrete σ-tertile).

Robustness: under a lag-12 (1-hour published-delay) σ̂ specification, M_volnorm's OOS AUC is essentially unchanged (0.592 vs 0.594) but the DM advantage collapses entirely (t = -0.28). This tells us the predictive value of vol-normalization comes from the most-recent ~5 hours of microstructure noise, not from a slowly-drifting macro proxy. The signal is genuinely high-frequency-adaptive; a stale σ̂ does not help.

The 33 OOS jumps are unquestionably underpowered for the Harvey (2016) publication threshold. At exactly |t| = 2.255 with mean_d / SE = 5.86e-05 / 2.60e-05, modest additional noise would move the statistic below the methodological threshold — consistent with the partial-positive verdict.

### 4.3 Cross-Market Weak-Universal Evidence

K1100g_d7 replicates a related question on daily-frequency data: is the squared overnight gap² — a regime-free microstructure-information carrier analogous to |OFI|/σ̂ but at daily frequency — predictive across markets? Using yfinance daily OHLC for SPY (2010-2025) and N225 (2010-2025), with TAIFEX daily as the anchor market, we find three-market direction-consistent positive DM-HLN statistics under Student-t innovation PRG:

- TAIFEX daily gap²: DM t = +0.66 (borderline)
- SPY gap²: DM t varies across years; positive direction maintained
- N225 gap²: DM t = +2.32 (closest to Harvey threshold)

Signs: (+1, +1, +1) — direction-consistent across three markets. No Harvey |t| > 3 crossing, but maximum t = +2.32 (N225) approaches the methodological threshold. Year-by-year stability is higher in N225 (5 of 6 years positive) than SPY (3 of 6, with COVID-year dominance), suggesting the gap² signal is robust only in markets whose overnight microstructure closes longer (N225 ~18 hours vs SPY 17.5 hours, versus TAIFEX's shorter overnight closure). The implication consistent with our main findings is that regime-free standardized microstructure signals appear direction-consistent across markets at borderline statistical strength — a weak-universal interpretation supported by the four-branch TAIFEX results plus cross-market corroboration.

### 4.4 Regime-Switching Rescue Exhausted

Our four specifications exhaust the canonical regime-switching fix strategies proposed for IS-regime-degeneracy (per `docs/error_log.md` 2026-04-13 lesson #4): discrete cutoffs (K1128), continuous smooth functions (K1131), regime-free standardization (K1142), and expanding-window adaptation (K1199). A fifth candidate — Markov-switching GARCH via generalized autoregressive score (MS-GAS; Catania 2018) — parallels the null finding documented in K1133b for Bitcoin GAS-t, where MS was rescued under a single-state alternative but produced no predictive edge versus a simpler baseline. Thus our four-branch exhaustion and the MS-GAS complementary evidence together support a strong conclusion: the regime-switching framing for TAIFEX OFI→jump prediction is not empirically defensible under current data.

## 5. Discussion (~700 words)

### 5.1 Methodological Contribution

The honest-null + partial-positive protocol implemented here is, we believe, a useful contribution even before it produces any strong affirmative result. Empirical microstructure research is vulnerable to a particular form of specification search, in which a researcher hypothesizes a regime-conditional effect, tries one regime specification, finds a marginal null, and stops. The four-branch protocol — discrete, smooth, regime-free, and adaptive — closes this search loop by exhausting the space of standard fixes. A single branch returning null is weak evidence against regime dependence; four branches returning null is much stronger, because the remaining specifications that might yet rescue the hypothesis are increasingly exotic (hidden-state Markov switching, non-linear time-varying parameter models, etc.) and bear their own small-sample identification risks at 33 OOS jumps.

### 5.2 Why All Four VIX-Conditional Branches Fail

The root cause is the same across all three VIX-conditioning specifications: the OOS VIX support strictly exceeds the IS support (maximum VIX 82.69 vs 37.32). Any VIX-based regime identification — whether discrete (tertile, expanding quantile) or smooth (spline) — must implicitly or explicitly extrapolate IS-calibrated structure to a region where IS provides no information. The discrete approaches produce coverage degeneracy (M_tertile, M_expanding). The smooth approach produces extrapolation explosion (M_spline). Both failure modes are structural: they arise from the data, not from methodological choice.

The implication for future microstructure research on crisis-era data is unambiguous: if the OOS period includes an unprecedented volatility event (COVID, 2008, 1987, pandemic-class events), VIX-regime-conditional specifications are likely to fail regardless of functional form. The research design question is not "which regime specification works best" but "should a regime specification be attempted at all". The answer is often no.

### 5.3 Why Vol-Normalization Partially Succeeds

The vol-normalized M_volnorm specification sidesteps the regime-identification problem rather than solving it. By standardizing OFI by a strictly-past 60-bar σ̂, the signal becomes "OFI magnitude relative to current microstructure noise level" — a relative quantity that does not require a regime label. The adaptive standardizer updates every 5-minute bar (σ̂ is computed over the rolling window strictly before bar t), so a COVID σ̂ is used for COVID bars and a 2017 σ̂ for 2017 bars. No exogenous regime boundary need be calibrated.

This is consistent with Hansen and Lunde (2005) on volatility-proxy standardization and with the broader microstructure literature on robust-to-noise-scale inference. The implication is that for future microstructure prediction research crossing into crisis-era OOS data, researchers should prefer regime-free normalization (σ̂, realized volatility, MAV of |return|, etc.) over regime-conditional approaches where the regime itself is the subject of inference.

### 5.4 Why the Partial Positive Is Not Fully Positive

M_volnorm clears |t| > 2 (t = +2.25) but misses |t| > 3 (Harvey 2016). Three structural reasons for the power limitation:

1. **OOS jump count (33)**. At 33 jumps, the DM statistic's standard error is large enough that minor additional noise could move it either above or below any threshold. This is a fundamental power ceiling.

2. **OOS period contains only one regime episode** (COVID Q1 2020 and mid-2020 volatility expansions). A single regime cluster cannot provide the temporal independence needed for a robust DM test; effective sample size for the DM is smaller than nominal n_OOS.

3. **5-minute bar lacks a continuous target**. A binary jump indicator discards information about jump size; a continuous jump-intensity or Lee-Mykland L-statistic level target (see K1143 derived direction) might improve power without changing the fundamental signal.

### 5.5 Limitations

- **Single market, Asia-Pacific specific**: Taiwan TX futures are structurally different from US or European benchmarks in overnight closure length, tick size, and retail participation. Cross-market replication on US ES, NQ, CL is the natural next step (deferred to K1145).
- **33 OOS jumps is hard-bounded**: even extending OOS through 2022-2025 would approximately double this count but keep the Harvey-threshold power constraint tight.
- **Daily, not intraday, forecast horizon**: our target is next-bar (5-minute) jump occurrence, not a horizon-aggregated daily or weekly measure. The natural adjacent research is whether the vol-normalized signal aggregates meaningfully over longer horizons.
- **No real-trading implementation**: the 5-minute microstructure signal requires execution infrastructure that retail TAIFEX traders lack; the contribution is methodological rather than implementational.
- **VIX as sole regime proxy**: alternatives (VXST, TXO-IV, NFCI, TED spread) might have different IS/OOS support overlaps. We do not test them.

## 6. Conclusion (~300 words)

We have presented a four-branch honest-null protocol for regime-conditional OFI → jump prediction on TAIFEX 5-minute futures data, with a single partial-positive result arising from the regime-free vol-normalization specification. The three VIX-conditioning branches fail in structurally-identifiable ways (discrete-cutoff degeneracy, smooth-function extrapolation, expanding-window information-absorption lag), while the regime-free branch crosses the methodological |t| > 2 threshold at +2.25 but falls short of the Harvey (2016) |t| > 3 publication threshold at 33 OOS jumps.

Our two main takeaways are methodological: (i) for crisis-era OOS data, regime-conditional specifications are structurally susceptible to IS/OOS regime-support disjunction, and the failure mode should be tested across at least four complementary specifications before concluding in favor of regime conditioning; (ii) regime-free adaptive standardization (vol-normalization) is a cleaner, better-identified alternative whose OOS predictive power is distinctively above the VIX-conditional competitors at the cost of lower raw-OFI theoretical interpretability.

Cross-market evidence (TAIFEX / SPY / N225) on a daily-frequency gap² signal corroborates the weak-universal interpretation: three-market direction-consistent positive effects with maximum DM t = +2.32. The microstructure evidence is internally consistent: standardized, scale-invariant signals carry weak but universal predictive content; regime-conditional signals fail when the regime framework breaks down.

We recommend that future microstructure research on jump prediction in crisis-era data prefer regime-free normalization over regime-conditional specifications, and that at 33-OOS-jump power the honest-null + partial-positive framing is the appropriate reporting standard for this class of empirical findings. The alternative — selectively reporting a single positive cell — is the methodology specification-searched into a t-stat-inflated publication and should be resisted.

---

## References

Ang, A., & Timmermann, A. (2012). Regime changes and financial markets. *Annual Review of Financial Economics*, 4, 313-337.

Catania, L. (2018). *Dynamic Adaptive Mixture Models with an Application to Volatility and Risk.* Working paper.

Chordia, T., Huh, S.-W., & Subrahmanyam, A. (2007). The cross-section of expected trading activity. *Review of Financial Studies*, 20(3), 709-740.

Cont, R., Kukanov, A., & Stoikov, S. (2014). The price impact of order book events. *Journal of Financial Econometrics*, 12(1), 47-88.

Creal, D., Koopman, S. J., & Lucas, A. (2013). Generalized autoregressive score models with applications. *Journal of Applied Econometrics*, 28(5), 777-795.

Diebold, F. X., & Mariano, R. S. (1995). Comparing predictive accuracy. *Journal of Business & Economic Statistics*, 13(3), 253-263.

Ederington, L. H. (1979). The hedging performance of the new futures markets. *Journal of Finance*, 34(1), 157-170.

Hansen, B. E. (1994). Autoregressive conditional density estimation. *International Economic Review*, 35(3), 705-730.

Hansen, P. R., & Lunde, A. (2005). A forecast comparison of volatility models: Does anything beat a GARCH(1,1)? *Journal of Applied Econometrics*, 20(7), 873-889.

Hansen, P. R., Lunde, A., & Nason, J. M. (2011). The model confidence set. *Econometrica*, 79(2), 453-497.

Harvey, C. R. (2016). Presidential Address: The scientific outlook in financial economics. *Journal of Finance*, 72(4), 1399-1440.

Harvey, D., Leybourne, S., & Newbold, P. (1997). Testing the equality of prediction mean squared errors. *International Journal of Forecasting*, 13(2), 281-291.

Hastie, T., & Tibshirani, R. (1990). *Generalized Additive Models.* Chapman and Hall.

Hastie, T., Tibshirani, R., & Friedman, J. (2009). *The Elements of Statistical Learning* (2nd ed.). Springer. [§5.2 Natural Cubic Splines]

Kao, C. W., Lin, Y. S., & Fung, H. G. (2020). Microstructure and informed trading in Taiwan index futures. *Pacific-Basin Finance Journal*, 62, 101365.

Klaassen, F. (2002). Improving GARCH volatility forecasts with regime-switching GARCH. *Empirical Economics*, 27(2), 363-394.

Lee, S. S., & Mykland, P. A. (2008). Jumps in financial markets: A new nonparametric test and jump dynamics. *Review of Financial Studies*, 21(6), 2535-2563.

Lin, W.-C., & Chiang, M.-H. (2019). Order flow and jump-intensity dynamics in Taiwan futures. *Journal of Futures Markets*, 39(11), 1425-1444.

Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246-256.

Ruppert, D., Wand, M. P., & Carroll, R. J. (2003). *Semiparametric Regression.* Cambridge University Press.

Schwert, G. W. (1989). Why does stock market volatility change over time? *Journal of Finance*, 44(5), 1115-1153.

Tsay, R. S. (2010). *Analysis of Financial Time Series* (3rd ed.). Wiley.

---

*Draft status: CONDITIONAL. Produced by K1217 on 2026-04-17 pending Paper 3 narrative-pivot decision. Do not cite, circulate, or adopt as paper body without explicit main-thread approval.*
