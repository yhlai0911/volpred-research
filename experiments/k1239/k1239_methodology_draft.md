# Paper 10 Section 4: Methodology (Initial Draft)

**Paper**: Paper 10 — The Crypto Fear Channel: Asymmetric BTC-Equity Volatility Spillover
**Version**: v0 (initial draft, 2026-04-17)
**Source K**: K1234 kickoff guide; K1237 (§2 Literature Review); K1238 (§3 Data)
**Supporting experiments**: K639, K746b, K1025, K949 (MF-GJR + VIX precedent)
**Target length**: ~800 words (actual: see word-count footer)
**Format**: Markdown draft (not `.tex` — to be transcribed into main body by main thread)
**Seed**: 42 (for all subsequent simulation / bootstrap references)

> **Scope note**: This draft specifies the *fear-channel GARCH-X regression* building block emphasised in the K1234 kickoff guide (variance-domain transmission test). It is complementary to — not a replacement for — the asymmetric-Granger / quantile-regression / Diebold–Yilmaz methodology already sketched in `paper/crypto-fear-channel/outline.md` (§4.1–§4.5). The main thread will decide on §4 sub-ordering before transcription to `body.tex`.

---

## §4.1 Fear-Channel Regression Specification (~250 words)

We define the *fear channel* operationally as the one-lag transmission of a traditional-market fear proxy into the conditional variance of Bitcoin returns. Let $r_{t}^{\text{BTC}} = \ln(P_{t}/P_{t-1})$ denote the daily log-return of BTC-USD, with innovation $\varepsilon_{t} = r_{t}^{\text{BTC}} - \mu_{t}$ and conditional variance $\sigma_{t}^{2} = \mathbb{E}_{t-1}[\varepsilon_{t}^{2}]$. The fear-channel GARCH-X specification is

$$
\sigma_{t}^{2} \;=\; \omega \;+\; \alpha \, \varepsilon_{t-1}^{2} \;+\; \gamma \, \varepsilon_{t-1}^{2} \, \mathbb{I}(\varepsilon_{t-1} < 0) \;+\; \beta \, \sigma_{t-1}^{2} \;+\; \phi \, \text{Fear}_{t-1}^{2},
$$

where $\text{Fear}_{t-1}$ denotes the end-of-day-$t{-}1$ level of the CBOE Volatility Index (VIX) as the baseline fear proxy, with the Crypto Fear & Greed Index (CFIX) used as a robustness alternative. The squared transformation follows the variance-domain convention of @engle2002, ensuring dimensional compatibility with the left-hand side and tractable positivity. The parameter $\phi$ is the central object of interest: it quantifies the marginal contribution of lagged fear to today's conditional BTC variance after controlling for own-shock persistence ($\alpha$), asymmetric leverage ($\gamma$; @glosten1993), and volatility memory ($\beta$). We test

$$
H_{0}:\; \phi = 0 \quad \text{(no fear channel)} \qquad \text{vs.} \qquad H_{1}:\; \phi > 0 \quad \text{(positive fear transmission)},
$$

a one-sided test motivated by the *amplifier* narrative developed in Section 2: fear in the established-equity complex should raise — not lower — conditional volatility in a retail-heavy, beta-exposed crypto market. Stationarity is imposed via $\alpha + \gamma/2 + \beta < 1$ and $\omega, \alpha, \gamma, \beta, \phi \ge 0$.

## §4.2 GARCH-X Base Model Selection (~200 words)

The GARCH-X nesting is chosen deliberately so that the fear-channel restriction is a single-parameter coefficient test, minimising degrees-of-freedom loss and sharpening interpretability. Within this class, we adopt the *MF-GJR* variant with Student-$t$ innovations as the primary specification, following the Paper 9 precedent (K949 cross-market evidence that MF-GJR(VIX) delivers Harvey-significant improvements in 4 of 5 international equity markets with VIX-elasticity $\theta_{1} \approx 2.1$). Two features make this choice appropriate for Bitcoin. First, BTC daily returns exhibit heavy tails (sample kurtosis $=7.97$ in K1129), necessitating Student-$t$ innovations with degrees-of-freedom parameter $\nu$ estimated jointly; Gaussian quasi-ML is retained only as a robustness cross-check. Second, the leverage term $\gamma \, \varepsilon_{t-1}^{2} \, \mathbb{I}(\varepsilon_{t-1} < 0)$ captures the downside asymmetry documented in K746b for BTC, where only the negative branch Granger-causes VIX. Three baselines are estimated for comparison: (i) GARCH(1,1) (homoscedastic leverage, no fear term), (ii) GJR-GARCH(1,1,1) (asymmetric, no fear term), and (iii) GARCH(1,1)-X (no asymmetry, with fear term). Specification (iv), MF-GJR(1,1,1)-X, nests all three.

## §4.3 Statistical Tests (~200 words)

We assess each specification along four complementary axes. (1) *In-sample significance*: the $\phi$ coefficient is tested via its robust (@bollerslev1992) asymptotic $t$-statistic and a likelihood-ratio test (LRT) against the GJR baseline with df $=1$. (2) *Out-of-sample forecast accuracy*: we compute the pairwise @diebold1995 test of equal predictive accuracy under the @patton2011 proxy-robust QLIKE loss
$$
L^{\text{QLIKE}}(\hat{\sigma}^{2}, \hat{\sigma}^{2}_{\text{proxy}}) \;=\; \frac{\hat{\sigma}^{2}_{\text{proxy}}}{\hat{\sigma}^{2}} - \ln \frac{\hat{\sigma}^{2}_{\text{proxy}}}{\hat{\sigma}^{2}} - 1,
$$
with the squared daily return as volatility proxy. (3) *Small-sample correction*: all DM statistics apply the @harvey1997 finite-sample adjustment factor. (4) *Multiple-testing protection*: claim of fear-channel existence requires $|t^{\text{HLN}}| > 3.0$, the @harvey2016 threshold for newly proposed signals, in order to guard against the cross-section of alternative fear proxies (VIX, VVIX, MOVE, CFIX) producing spurious wins. (5) *Sub-period robustness*: motivated by the K1133b structural break, we re-estimate on pre-ETF (2015-02 to 2023-12-31) and post-ETF (2024-01-01 to 2026-04) sub-samples and report whether $\hat{\phi}$ remains sign-stable.

## §4.4 Identification Strategy (~150 words)

Identification of a *causal* fear channel — rather than a spurious reduced-form co-movement — requires three ingredients. First, an *exogenous* fear proxy: VIX is constructed from S&P 500 index options whose underlying market is an order of magnitude larger than the Bitcoin cash market, making reverse feedback from BTC into VIX empirically negligible at the daily horizon; this stands in contrast to the Crypto Fear & Greed Index (CFIX), which is partly a function of BTC price momentum. Second, *directional precedence*: we verify that VIX Granger-causes $\sigma_{t}^{\text{BTC},2}$ at lag 1, and that the reverse test fails at conventional levels, thereby ruling out simultaneity. Third, an *instrumental-variable* alternative: we extract the VIX innovation from an AR$(p)$ filter selected by BIC, regress this orthogonalised fear shock on the conditional variance, and confirm that $\hat{\phi}$ remains positive and HLN-significant, isolating unexpected-fear transmission from auto-predictable fear persistence.

---

**Word count**: ~870 words across the four subsections (target ~800, variance ≤10% acceptable).
**Citations introduced**: @engle2002, @glosten1993, @diebold1995, @harvey1997, @harvey2016, @patton2011, @bollerslev1992. Full bibkeys to be harmonised with `paper/crypto-fear-channel/body_v0_intro.tex` bibliography during main-thread transcription.
**Open methodological decisions (for main thread)**:
1. Whether to keep this GARCH-X module as `§4.1` (preceding Granger/QR/DY) or as `§4.6` (following the spillover-index block). The K1234 kickoff leaves room; the outline.md currently has no fear-regression subsection.
2. Whether the IV alternative in §4.4 merits its own subsection or a footnote.
3. Whether sub-sample split follows K1133b (pre/post-ETF) or K1025 (five-regime) convention for §4.3 point (5).
