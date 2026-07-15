# K1705 — Honest dependence-score audit of K1100c

## Motivation

K1100c reports that the Joe copula beats DCC for SPY–TLT and SPY–GLD. That
claim is load-bearing for the asset-class-specific Paper 3 narrative, but its
published comparison is a portfolio-variance QLIKE comparison rather than a
copula score. More importantly, the archived implementation defines the loss
difference as model 1 minus model 2 while the README interprets a positive
statistic as model 1 winning. Its Joe density also fails the defining
independence check: at theta=1 a Joe copula must have density one everywhere,
but the archived formula does not.

K1705 asks whether the conclusion survives a margin-first evaluation. It
rebuilds one-sided rolling marginal PITs, checks marginal calibration before
dependence, and then evaluates DCC and Joe with their copula log scores on the
same PIT sequence. This follows Fissler and Hoga's warning that copula forecasts
cannot generally be ranked independently of their marginal forecasts.

## Data and provenance

- Repository-pinned yfinance adjusted-close snapshot:
  `paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv`
- Period available in the snapshot: 2005-01-03 through 2026-07-10.
- Pairs: SPY–TLT and SPY–GLD, the two K1100c “winning” pairs.
- Parent artifacts are read-only inputs. Their SHA-256 hashes are recorded in
  `k1705_results.json`.

## Method

1. Compute close-to-close log returns.
2. At each forecast origin, construct a one-sided EWMA variance forecast from
   returns no later than t-1. Refit unit-variance Student-t degrees of freedom
   every 63 observations on the preceding 1,250 observations.
3. Transform realized returns to PITs and test uniformity plus PIT and squared
   normal-score serial dependence. DCC and Joe deliberately receive identical
   marginal PITs.
4. Refit Gaussian DCC and Joe dependence parameters every 63 observations and
   calculate one-step copula negative log scores. The Joe density is obtained
   by differentiating its stated CDF and is checked against the theta=1
   independence limit.
5. Compare pointwise losses with the repository's canonical HAC DM test.
6. Repeat after delaying the second asset return by one trading day. Because
   SPY, TLT and GLD share the US close, this is a conservative asynchrony stress
   test rather than a claim about their actual timestamps.

The random seed is 42. There is no trading signal. All forecasts and fits use
only observations strictly before the scored date; this is the equivalent of
an explicit one-period lag. Results are written through a validated temporary
JSON and `os.replace`.

## Pre-registered success criteria

- A Joe dependence advantage requires both marginal PITs to pass the joint
  calibration gate and canonical DM t > 3 on the dependence scores.
- If the margins fail, the two-step decision stops at the marginal stage.
- The parent sign audit fails K1100c's interpretation if its stored
  Joe-minus-DCC mean loss is positive while the README calls Joe superior.
- A robust direction must not reverse under the one-day delay stress test.

## References

- Fissler, T. and Hoga, Y. (2026), *How to Compare Copula Forecasts?*, JBES;
  public manuscript: https://arxiv.org/abs/2410.04165
- Patton, A. J. (2006), *Modelling Asymmetric Exchange Rate Dependence*, IER
  47(2), 527–556.
- Giacomini, R. and White, H. (2006), *Tests of Conditional Predictive
  Ability*, Econometrica 74(6), 1545–1578.

## Outputs

- `k1705.py` — complete, reproducible audit.
- `k1705_results.json` — byte-traceable results.
- `review_verdict.json` — generated after independent Codex review and pins the
  exact claim-surface bytes.
