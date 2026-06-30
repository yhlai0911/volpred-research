# Well-Written Section Examples from Finance Papers

## Example 1: Introduction Opening (Motivation)

**Good example - Concrete and compelling**:

```
On September 15, 2008, Lehman Brothers filed for bankruptcy, triggering the largest one-day
decline in the S&P 500 since the 1987 crash. Within 48 hours, FTSE 100 dropped 4.5% and the
Nikkei 225 fell 5.4%, erasing $2.8 trillion in global market capitalization. This rapid
transmission of shocks from the United States to international markets exemplifies financial
contagion—the phenomenon whereby localized financial disturbances propagate across borders
and asset classes, often with devastating consequences for global economic stability.

Understanding the mechanisms through which financial shocks transmit internationally is crucial
for both policymakers designing macroprudential regulation and investors managing portfolio
risk. If contagion operates primarily through fundamental linkages (trade, credit exposures),
diversification across countries provides limited protection during crises. If instead contagion
reflects behavioral channels (herding, information cascades), then episodes of extreme co-movement
may be predictable and potentially mitigated through circuit breakers or transparency requirements.
```

**Why this works**:
- Opens with specific, dramatic event (Lehman bankruptcy)
- Quantifies impact ($2.8 trillion)
- Defines key term (contagion)
- Establishes stakes (policy and investor relevance)
- Sets up research question (fundamental vs. behavioral channels)

**Bad example - Vague and generic**:

```
Financial markets are interconnected. In recent years, there have been several financial crises.
Understanding financial markets is important. This paper studies financial contagion, which is an
interesting topic in finance.
```

**Why this fails**:
- No concrete examples
- No quantification
- "Important" and "interesting" are empty claims
- Doesn't establish what's unknown or controversial

---

## Example 2: Research Question

**Good example - Precise and motivated**:

```
Despite extensive documentation of co-movement during crises, the structural mechanisms driving
cross-border transmission remain poorly understood. Existing studies using correlation analysis
(Forbes and Rigobon, 2002) or Granger causality (Baig and Goldfajn, 1999) capture reduced-form
associations but cannot distinguish between fundamental linkages and self-reinforcing feedback.
More recent structural models (Aït-Sahalia et al., 2015) focus on univariate intensity dynamics,
abstracting from cross-asset spillovers.

We address this gap by asking: To what extent do negative returns in one market directly trigger
subsequent negative returns in another market, beyond what common fundamental factors or ex-ante
correlations can explain? We operationalize "direct triggering" using a bivariate Hawkes process,
which allows us to separately identify self-excitation within markets (clustering) from cross-excitation
between markets (contagion), while controlling for diffusive co-movement through correlated Brownian
shocks.
```

**Why this works**:
- Explicitly states what prior work has done
- Identifies the specific gap
- Poses clear, testable question
- Explains how the method addresses the question
- Uses precise language ("operationalize," "separately identify")

---

## Example 3: Methodology Preview

**Good example - Informative yet accessible**:

```
Methodologically, we employ a bivariate jump-diffusion model in which asset returns follow
continuous Brownian motion punctuated by discrete jumps. The innovation of our approach lies
in modeling the jump arrival rate (intensity) as endogenously determined by past jumps rather
than exogenous or tied to observable state variables. Specifically, we adopt the Hawkes (1971)
self-exciting point process framework, extended to allow for cross-excitation: a jump in Asset 1
not only increases the probability of future jumps in Asset 1 (self-excitation), but also
increases the probability of jumps in Asset 2 (contagion). The intensity mean-reverts to a
baseline level, with the speed of reversion and strength of excitation governed by estimable
parameters.

We estimate the seven model parameters using the Generalized Method of Moments (GMM), exploiting
closed-form expressions for the autocorrelation structure derived from the process's infinitesimal
generator. The GMM approach avoids strong distributional assumptions required by maximum likelihood
while remaining computationally tractable for our high-frequency data (T=4,758 daily observations
from 1990-2008 covering US, UK, and Japanese equity markets).
```

**Why this works**:
- Explains the model in plain language first ("continuous Brownian motion punctuated by discrete jumps")
- Highlights the innovation ("endogenously determined by past jumps")
- Previews the key mechanism (self- vs. cross-excitation)
- Justifies methodological choice (GMM vs. ML)
- Specifies data and sample

---

## Example 4: Main Findings

**Good example - Specific and quantified**:

```
We obtain three main findings. First, we find statistically significant and economically
substantial contagion from US to UK markets. The cross-excitation parameter β₂₁ is estimated
at 13.1 (standard error 6.1, p<0.05), implying that each negative jump in the US market increases
the UK market's instantaneous jump intensity by 13.1 events per unit time. Relative to the
baseline intensity of λ_∞=0.40, this represents a 33-fold amplification, suggesting that
cross-border spillovers dominate baseline jump probabilities during shock transmission.

Second, we document substantial asymmetry: while US jumps strongly affect UK and Japanese markets
(β₂₁=13.1 and 15.3 respectively), the reverse direction shows no significant effect (β₁₂ estimates
are statistically indistinguishable from zero with t-statistics below 1.0). This asymmetry is
consistent with the US serving as the originator of global financial shocks during our sample period.

Third, we show that contagion intensifies during crisis episodes. Restricting our sample to the
2007-2009 financial crisis, the cross-excitation parameter increases to β₂₁=18.7, a 44% amplification
relative to normal periods (β₂₁=9.4, 1990-2006). A counterfactual simulation setting β₂₁=0 reveals
that contagion accounts for approximately 75% of observed jump clustering in recipient markets,
highlighting its first-order importance for understanding crisis dynamics.
```

**Why this works**:
- Numbered list for clarity
- Each finding has: point estimate, standard error, p-value, economic interpretation
- Quantifies magnitudes ("33-fold," "75%")
- Compares across subsamples and counterfactuals
- Connects to economic interpretation (US as originator)

---

## Example 5: Literature Review Integration

**Good example - Thematic organization with clear positioning**:

```
Our paper contributes to three strands of literature. First, we add to the extensive literature
on financial contagion. Early work (King and Wadhwani, 1990; Lee and Kim, 1993) documented
increased correlation during crises but faced the critique that correlation naturally increases
with volatility (Forbes and Rigobon, 2002). Subsequent studies employed structural models to
disentangle contagion from interdependence: Bekaert et al. (2005) use regime-switching copulas,
while Dungey et al. (2006) propose latent factor models. Our Hawkes-based approach differs by
explicitly modeling the dynamic feedback through which shocks propagate: past events directly
increase future event probabilities, capturing the self-reinforcing nature of crisis transmission.

Second, we contribute to the literature on jump dynamics in asset prices. Early applications
(Ball and Torous, 1983; Jorion, 1988) assumed constant jump intensity, while more recent work
(Eraker et al., 2003; Broadie et al., 2007) allows for stochastic intensity driven by latent
factors or volatility. Aït-Sahalia et al. (2015) introduce self-exciting jumps where intensity
depends on past jump history, but focus on univariate processes. We extend this framework to
bivariate settings, allowing us to separately identify within-asset clustering (self-excitation)
from cross-asset spillovers (cross-excitation), which is essential for distinguishing contagion
from mere co-movement.

Third, methodologically, we contribute to the GMM estimation literature for continuous-time
processes. Hansen (1982) and Hansen and Singleton (1982) establish the GMM framework, while
Gallant and Tauchen (1996) develop efficient method of moments for discretely observed diffusions.
Aït-Sahalia et al. (2015) derive moment conditions for univariate Hawkes processes using the
infinitesimal generator. We extend these moment conditions to bivariate settings and show how
to construct optimal weighting matrices that account for cross-equation correlation, which is
ignored in standard applications.
```

**Why this works**:
- Organized by theme, not chronology
- For each paper: author, year, what they do, how you differ
- Builds narrative of progression
- Clearly positions contribution
- Covers methodological and substantive contributions

---

## Example 6: Econometric Specification

**Good example - Builds gradually with intuition**:

```
The Hawkes process allows jump intensity to evolve stochastically in response to past jumps.
Consider first the univariate case. The intensity λ_t follows:

    dλ_t = α(λ_∞ - λ_t)dt + β dN_t                                                    (1)

Equation (1) consists of two components. The first term, α(λ_∞ - λ_t)dt, captures mean reversion:
if the current intensity λ_t exceeds its long-run level λ_∞, the negative drift pulls it back
down at speed α, and vice versa. This ensures the process is stationary provided α > 0. The
second term, β dN_t, captures self-excitation: whenever a jump occurs (dN_t=1), the intensity
increases discontinuously by amount β. This formalization captures the intuitive idea that extreme
events cluster: one bad shock makes subsequent bad shocks more likely.

The parameter α governs how quickly elevated intensity dissipates. The half-life of an intensity
shock is t_{1/2} = ln(2)/α days. The parameter β determines the strength of clustering: larger
β implies each jump has a larger impact on future jump probability. For stationarity, we require
α > β to ensure mean reversion dominates self-excitation.

We extend (1) to the bivariate case, allowing for cross-excitation:

    dλ_{1,t} = α(λ_∞ - λ_{1,t})dt + β_{11} dN_{1,t}                                  (2a)
    dλ_{2,t} = α(λ_∞ - λ_{2,t})dt + β_{21} dN_{1,t} + β_{22} dN_{2,t}              (2b)

Equation (2a) states that Asset 1's intensity exhibits self-excitation governed by parameter β_{11}.
Equation (2b) allows Asset 2's intensity to respond to both its own jumps (β_{22}, self-excitation)
and Asset 1's jumps (β_{21}, cross-excitation or contagion). The parameter β_{21} is our key object
of interest: it measures the extent to which shocks in Asset 1 propagate to Asset 2 through a
self-reinforcing intensity feedback channel.
```

**Why this works**:
- Presents univariate case first (simpler)
- Interprets each term economically before moving on
- Explains parameter meanings and restrictions (stationarity)
- Derives intuitive quantities (half-life)
- Then extends to bivariate case
- Identifies the key parameter of interest (β₂₁)

---

## Example 7: Results Discussion

**Good example - Systematic and interpretive**:

```
Table 2 reports the GMM estimation results. We discuss each panel in turn.

Panel A presents the diffusion parameters estimated in Stage 1 from truncated returns. The volatility
estimates are σ̂₁=0.014 (s.e. 0.001) and σ̂₂=0.016 (s.e. 0.001), consistent with typical daily
volatility levels of 1.4% and 1.6% for US and UK equity markets respectively. Both are precisely
estimated (t>10) and stable across alternative sample periods (not shown). The correlation coefficient
ρ̂=0.39 (s.e. 0.045, t=8.67) indicates moderate positive co-movement during normal times, consistent
with the contemporaneous estimates of Longin and Solnik (2001) who report correlations of 0.35-0.45
for US-UK equity pairs over similar periods.

Panel B reports the Hawkes parameters estimated in Stage 2. The mean reversion parameter α̂=20.3
(s.e. 9.3, t=2.18) is statistically significant at the 5% level. This estimate implies a half-life
of ln(2)/20.3 = 0.034 days, or approximately 16 trading minutes, suggesting that intensity shocks
dissipate rapidly within a single trading session. The fast mean reversion is consistent with the
intraday decay documented by Lee and Mykland (2008) for individual stock jumps.

The self-excitation parameters are β̂₁₁=17.1 (s.e. 6.7, t=2.55) for Asset 1 and β̂₂₂=7.1 (s.e. 6.5,
t=1.09) for Asset 2. The former is statistically significant while the latter is marginally
insignificant (p=0.14), suggesting stronger clustering in the US market than UK market. The stationarity
conditions α > β₁₁ and α > β₂₂ are comfortably satisfied (20.3 > 17.1 and 20.3 > 7.1), confirming
that our estimates correspond to a well-defined stationary process.

Most importantly, the cross-excitation parameter β̂₂₁=13.1 (s.e. 6.1, t=2.15) is statistically
significant at the 5% level. We reject the null hypothesis of no contagion (H₀: β₂₁=0) with
p=0.032. Economically, this estimate implies that each jump in the US market increases the UK
market's instantaneous jump intensity by 13.1 units. Given the baseline intensity λ_∞=0.40, this
represents a 33-fold (13.1/0.40) amplification. To put this in perspective: absent any recent jumps,
the UK market has a 0.40 probability per day of experiencing a jump; immediately following a US jump,
this probability increases to 13.5 (=0.40+13.1), an increase of 3,275%. This substantial amplification
highlights the economically meaningful nature of cross-border contagion.
```

**Why this works**:
- Discusses each panel/parameter systematically
- Always reports: estimate, standard error, t-stat, interpretation
- Compares to literature values
- Checks implications (stationarity)
- Translates key finding (β₂₁) into economically meaningful quantities
- Uses multiple ways to convey magnitude (33-fold, 3,275% increase)

---

## Example 8: Conclusion

**Good example - Concise summary with forward look**:

```
Financial crises rarely remain contained within national borders. This paper examines the mechanisms
through which negative shocks transmit internationally, using a bivariate Hawkes jump-diffusion model
estimated on US, UK, and Japanese equity markets from 1990-2008. Our framework allows us to separately
identify self-excitation within markets (clustering) from cross-excitation between markets (contagion),
while controlling for diffusive co-movement through correlated Brownian shocks.

We document three key findings. First, we find statistically significant and economically substantial
contagion from US to international markets, with cross-excitation parameters implying 30- to 40-fold
amplification of baseline jump probabilities. Second, this transmission is strongly asymmetric: US
shocks affect foreign markets, but not vice versa. Third, contagion intensifies during crisis periods,
with cross-excitation parameters rising by 40-50% relative to normal times.

These findings have important implications for international portfolio diversification and regulatory
policy. The asymmetric nature of transmission suggests that investors seeking tail-risk protection
should focus on hedging US market exposure, as shocks originating elsewhere exhibit limited spillover
potential. From a regulatory perspective, our estimates of contagion magnitude can inform the
calibration of cross-border macroprudential tools such as reciprocal capital buffers and coordinated
circuit breakers. If US regulators implement policies that reduce the frequency or severity of domestic
jumps—such as single-stock circuit breakers or short-sale restrictions—our estimates suggest this would
significantly reduce jump clustering in foreign markets, generating positive spillovers for global
financial stability.

Our analysis is subject to several caveats. First, we impose a triangular structure (β₁₂=0), which
may not hold during episodes when multiple countries experience simultaneous crises. Second, we focus
on equity markets, abstracting from transmission through credit, foreign exchange, and derivative
markets. Third, our sample ends in 2008; post-crisis regulatory changes and increased algorithmic
trading may have altered contagion dynamics. Extensions could relax the triangular assumption using
more flexible Hawkes specifications, incorporate additional asset classes, or study time variation in
contagion using rolling-window or time-varying parameter methods.
```

**Why this works**:
- Restates question in fresh language (not copy-paste from abstract)
- Concise summary of findings (3 sentences)
- Policy implications: specific and actionable
- Honest about limitations (3 clear caveats)
- Concrete directions for future research (not vague "more work needed")
- No new results or citations in conclusion

---

## Common Patterns in Strong Writing

1. **Concrete before abstract**: Start with specific events/numbers, then generalize
2. **Signposting**: "First," "Second," "Finally" for enumeration
3. **Parallel structure**: "We find X. We document Y. We show Z."
4. **Active voice**: "We estimate" not "It is estimated"
5. **Transition sentences**: Last sentence of paragraph previews next paragraph
6. **Quantification**: Always include numbers (magnitudes, percentages, t-stats)
7. **Comparisons**: Relate to prior studies, subsamples, counterfactuals
8. **Jargon moderation**: Define technical terms; use plain language when possible

## Phrases That Signal Strong Writing

- "To put this in perspective..."
- "Economically, this implies..."
- "Relative to [benchmark], this represents..."
- "This finding is robust to [alternative]..."
- "We differ from prior work in that..."
- "The economic magnitude is substantial: [specific number]..."
- "These results have implications for..."

## Phrases to Avoid

- "It is interesting that..." (say why it's interesting!)
- "We believe that..." (say what the evidence shows)
- "Obviously..." (if obvious, don't state it; if not obvious, provide evidence)
- "Clearly..." (same as above)
- "Future research should investigate..." (be specific about what and why)
