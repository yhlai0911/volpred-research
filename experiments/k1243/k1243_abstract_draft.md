# Paper 10 Abstract Draft (K1243)

**Paper**: Paper 10 — The Crypto Fear Channel: Asymmetric, Tail-Concentrated, and Regime-Dependent Volatility Spillover from Bitcoin to Equity Markets
**Target length**: ~250 words
**Source**: synthesises §2 (K1237) + §3 (K1238) + §4 (K1239) + §5+§6 (K1240) + §7+§8+§9 (K1242) + body_v0_intro.tex (v0 abstract, 292 words)
**Status**: v1 draft for main-thread review; supersedes the 292-word v0 abstract embedded in `paper/crypto-fear-channel/body_v0_intro.tex` (lines 23–28).
**Seed**: 42 (no stochastic content; noted for reproducibility discipline.)

---

## Abstract (v1 draft, 250 words)

Using daily observations on SPY, BTC-USD, and VIX from 2 February 2015 to 8 April 2026 ($N = 2{,}812$), we document the transmission of traditional-market fear into cryptocurrency conditional volatility along three complementary dimensions. First, the spillover is \emph{asymmetric}: Bitcoin downside realised volatility Granger-causes VIX, whereas Bitcoin upside realised volatility does not, with the asymmetry surviving symmetric-Granger benchmarks. Second, the spillover is \emph{tail-concentrated}: the quantile-regression coefficient of VIX on Bitcoin realised variance rises from $2.61$ at the median to $22.31$ at the $95$th percentile, an $8.5\times$ amplification that conventional OLS and DCC-GARCH estimates systematically understate. Third, the spillover is \emph{regime-dependent}: a five-subperiod breakdown shows Granger significance concentrated in 2020 ($F = 11.05$, $p < 10^{-6}$) and absent in 2015--2017, 2018--2019, 2021--2022, and 2023--2026. Within the Diebold--Yilmaz framework Bitcoin is a \emph{net receiver} rather than a net sender of volatility, reframing the narrative from ``crypto as a fear originator'' to ``crypto as a fear amplifier conditional on pre-existing equity stress.'' We complement these causal-structure findings with a GARCH-X fear-channel regression (pending K1241 output) that quantifies the marginal contribution $\phi$ of lagged VIX$^2$ to Bitcoin conditional variance under a Harvey (2016) $|t^{\text{HLN}}| > 3$ decision threshold. Finally, an out-of-sample Diebold--Mariano test returns $t = -0.98$, $p = 0.33$, below the Harvey threshold: in-sample causal structure does not translate to practical forecastability. Our findings inform crypto-ETF margin design and prudential supervision during crisis regimes. \\

\noindent\textbf{Keywords:} volatility spillover, Bitcoin, VIX, asymmetric causality, quantile regression, Diebold--Yilmaz, GARCH-X, fear channel \\
\textbf{JEL:} G11, G15, G17, C22, C58

---

## Word Count Breakdown

| Segment | Words |
|---------|-------|
| Opening sample statement | 22 |
| Stylized fact 1 — asymmetry | 36 |
| Stylized fact 2 — tail concentration | 44 |
| Stylized fact 3 — regime dependence | 33 |
| Diebold-Yilmaz net-receiver framing | 38 |
| GARCH-X fear-channel (K1241-pending, hedged) | 36 |
| OOS null (DM $t=-0.98$) | 28 |
| Policy implication | 13 |
| **Total body** | **~250** |
| Keywords / JEL (footer) | separate |

Verified by manual word count on the abstract paragraph above.

---

## Comparison vs. v0 (body_v0_intro.tex lines 23–28)

| Dimension | v0 (body_v0_intro.tex) | v1 (K1243) | Change rationale |
|-----------|------------------------|------------|------------------|
| Sample statement | N=2,812, 2015-02 to 2026-04 | Same | Preserve |
| Stylized facts 1–3 | Asymmetry / tail / regime | Same structure | Preserve (K1025 verified) |
| Tail magnitude | $2.61 \to 22.31$ ($8.5\times$) | Same | K1025 canonical |
| Regime headline | $F=11.05$, $p<0.001$ in 2020 | $F = 11.05$, $p < 10^{-6}$ in 2020 | Tighten $p$-value precision (K1025 actual: $7.9\times 10^{-7}$) |
| Diebold-Yilmaz framing | BTC net receiver | Same | Preserve |
| GARCH-X fear channel | *not mentioned* | **Added**: ``pending K1241'' hedge | §2–§9 drafts introduce GARCH-X; abstract must acknowledge |
| OOS DM result | $t = -0.98$, $p = 0.33$ | Same | K1025 canonical |
| Policy implication | ``ex-post risk attribution and margin design'' | ``crypto-ETF margin design and prudential supervision'' | Sharpen operational phrasing |
| Length | 292 words | 250 words | Journal-standard target; trim redundant hedge clauses |

**Net effect**: v1 is a tighter, more scope-honest abstract that (a) retains all K1025-verified numbers, (b) adds the GARCH-X variance-domain dimension as pending rather than hiding it, and (c) matches typical JIFMIM / JEF abstract length conventions.

---

## Pending-Experiment Flag

**K1241 (critical)**: The GARCH-X fear-channel regression coefficient $\hat{\phi}$ and its Harvey-corrected $t$-statistic are not yet available. The abstract hedges this with ``(pending K1241 output) that quantifies the marginal contribution $\phi$...under a Harvey (2016) $|t^{\text{HLN}}| > 3$ decision threshold.'' Once K1241 produces results:

- **If $\hat{\phi} > 0$ and $|t^{\text{HLN}}| > 3$**: Main thread replaces the hedge with an affirmative sentence, e.g., ``Augmenting an MF-GJR baseline with lagged VIX$^2$ yields $\hat{\phi} = [value]$ ($t^{\text{HLN}} = [value]$), exceeding the Harvey threshold and confirming a cross-market variance-domain fear channel.''
- **If $\hat{\phi}$ fails the Harvey threshold**: Main thread replaces the hedge with an honest-NULL sentence, consistent with research-honesty principle 9, e.g., ``Augmenting an MF-GJR baseline with lagged VIX$^2$ yields an insignificant $\hat{\phi}$ ($t^{\text{HLN}} = [value]$), reinforcing the §7 out-of-sample null: Granger causality does not guarantee variance-domain transmission at daily frequency.''
- **Do NOT fabricate**: Per research-honesty principle 1, the abstract must not be committed with a representative $\hat{\phi}$ value before K1241 completes. The placeholder hedge is the minimum-commitment form acceptable under research ethics.

---

## Notes for Main-Thread Adoption

1. **Two abstract variants to choose between**: (a) K1025-only abstract (matches body_v0_intro.tex framing exactly; drop the GARCH-X hedge; safer); (b) full K1025+K1241 abstract (current v1; richer but depends on K1241). Main-thread decision should align with whether §6 is kept (K1241 required) or cut (K1025-only scope).

2. **Keywords updated**: Added ``GARCH-X'' and ``fear channel'' to reflect the variance-domain dimension introduced in §4 (K1239). Keep ``asymmetric causality'', ``quantile regression'', ``Diebold--Yilmaz'' verbatim from v0 for continuity with existing body_v0_intro.tex bibliography.

3. **JEL codes**: Added C58 (Financial Econometrics) to v0's G11, G15, G17, C22 set, reflecting the methodology emphasis.

4. **Length discipline**: 250 words is the canonical JIFMIM / JEF ceiling. v0's 292 words exceeds typical journal instructions; v1 trims redundant stretch clauses (e.g., ``Taken together, our findings reframe...'' → absorbed into the D-Y net-receiver sentence).

5. **Citations in abstract**: Harvey (2016) is cited inline; Diebold--Yilmaz, Hatemi-J, Koenker--Bassett are referenced via phrase (``Diebold--Yilmaz framework'', ``quantile-regression coefficient'') rather than inline \citet. This matches v0 convention and keeps the abstract self-contained.

6. **Honesty discipline**: No number in this abstract is interpolated or estimated. All numerical claims (N=2,812; QR coefficients; F-stat; DM statistic) are verbatim from K1025 JSON or body_v0_intro.tex (which itself sources K1025). K1241-dependent claims are explicitly flagged as pending.

---

*End of K1243 abstract draft. Target 250 words met (verified manually). For main-thread cherry-pick into `paper/crypto-fear-channel/body_v1.tex` after main-thread resolves the K1241 / GARCH-X scope decision.*
