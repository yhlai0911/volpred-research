# K1426 References — Partial Cointegration Hedging

## Primary methodological sources

### 1. Clegg & Krauss (2018) — PCH canonical formulation

> Clegg, M., & Krauss, C. (2018). Pairs trading with partial cointegration. *Quantitative Finance*, 18(1), 121–138. https://doi.org/10.1080/14697688.2017.1370122

**Core method (used in K1426)**: A bivariate spread is modeled as the sum of an
AR(1) mean-reverting component M_t and a random-walk component R_t:

> "We propose a generalization of the classical cointegration concept, named
> partial cointegration, which allows the residual series to consist of a
> stationary, mean-reverting AR(1) component plus a random walk component.
> The decomposition allows the random walk part to absorb permanent shocks
> that the classical cointegrating residual cannot accommodate."

The state-space MLE estimates `(beta, rho, sigma_M, sigma_R)` by Kalman
filtering on the residual `x_t − beta·y_t`. We implement this exactly
(`kalman_loglik` + `fit_pch` in `k1426.py`) with 100 multistarts (per
project pooled-MLE rule K1213→K1216c).

### 2. Poulos, Curphey & Williams (2024) — RQFA empirical asset pricing via PCH

> Poulos, J., Curphey, R., & Williams, B. (2024). Empirical asset pricing
> via partial cointegration. *Review of Quantitative Finance and Accounting*,
> 62(3), 1031–1061. https://doi.org/10.1007/s11156-023-01230-8

**Why cited**: This paper is the original backlog trigger entry in
`research_program.md` ("Partial Cointegration Hedging — RQFA 2023"). The
authors extend Clegg-Krauss to a cross-sectional asset-pricing setting,
showing that the share of mean-reverting variance R²_MR = σ²_M / (σ²_M + σ²_R)
carries predictive content for future returns beyond the classical
cointegrating residual.

Relevant for K1426: their R²_MR diagnostic is the same one we report per
pair; their finding that "many pairs degenerate to R²_MR ≈ 0 (pure random
walk)" is exactly the honesty-gate condition we pre-commit to.

### 3. Lien (2004) — Classical OLS-vs-ECM hedge baseline

> Lien, D. (2004). Cointegration and the optimal hedge ratio: the general
> case. *The Quarterly Review of Economics and Finance*, 44(5), 654–658.
> https://doi.org/10.1016/j.qref.2003.10.001

**Why cited**: Provides the textbook OLS vs ECM hedge comparison we use as
baseline. Lien shows that when a cointegrating relationship exists, the
OLS hedge ratio is consistent for the long-run hedge, while the ECM adds
short-run dynamics. K1426 uses both as the two baselines against which
PCH is benchmarked.

Quote: "When the spot and futures prices are cointegrated, the OLS
estimator of the minimum-variance hedge ratio is consistent. The
error-correction model produces the same long-run hedge but additionally
captures short-run adjustment via the speed-of-adjustment coefficient α."

## Auxiliary

- Engle, R. F., & Granger, C. W. J. (1987). Co-integration and error
  correction: representation, estimation, and testing. *Econometrica*,
  55(2), 251–276. https://doi.org/10.2307/1913236 — original EG two-step.
- Alexander, C. (1999). Optimal hedging using cointegration. *Philosophical
  Transactions of the Royal Society A*, 357(1758), 2039–2058.
  https://doi.org/10.1098/rsta.1999.0416 — cointegration hedge in commodities.

## Notes on prior K (this project)

`grep` of `storage/memory/knowledge.json` for
`cointegration|hedging|partial` returned 0 hits. K1426 is the first VolPred
experiment to apply Clegg-Krauss state-space PCH; prior hedging work in this
project (PRS / copula-GARCH) used static or DCC-based hedges, not state-space
partial cointegration.
