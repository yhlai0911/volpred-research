# K1386: Multivariate fGN-motivated Rough-Volatility Forecast

## Status and supersession

This 2026-07-15 rerun supersedes K1386's published sample statistics. Three
defects were repaired together:

1. The local DM helper used `range(1, max(1, h))`; at `h=1` that loop was
   empty, so its reported `t=3.268827` (fGN-uni vs HAR) and `t=3.257408`
   (fGN-multi vs HAR) used an iid variance rather than HAC.
2. Each source CSV contained the same 10 duplicate dates. Although the paired
   rows were identical, the old inner merge expanded every affected day 2×2.
3. The last HAR in-sample feature row used the first OOS observation as its
   `shift(-1)` training target.

The repaired experiment rejects conflicting duplicate rows, deduplicates the
validated-identical rows, enforces a one-to-one merge, keeps all HAR training
targets inside IS, and delegates the primary comparison to
`volpred.stats.model_evaluation.dm_test`. With the endpoint frozen at
2026-05-19, the canonical Bartlett Newey-West lag is 11. The qualitative result
does **not** reverse: both fGN variants have higher QLIKE than HAR and both
differences remain above the conservative `|t|>3` reporting screen. The
experiment verdict remains `NULL_NO_FGN_IMPROVEMENT`.

K1386 is an empirical OOS forecast comparison, not a causal study. Its model is
an fGN-motivated AR approximation for log-range-variance increments plus a
lagged cross-asset residual correction; it is not a full multivariate fGN
likelihood or GMM estimator.

## Research question and prior evidence

Does adding rough-volatility increment dynamics and lagged QQQ/GLD residual
information improve next-day SPY range-variance forecasts relative to HAR?

- K529 estimated daily SPY roughness near `H=0.1`.
- K806's earlier multivariate fBm attempt was dominated by HAR and suffered a
  contaminated Taiwan-data input plus a coarse variogram design.
- K1386 uses only SPY, QQQ, and GLD; a Parkinson range proxy; a log-structure
  function estimate of `H`; and target-aligned next-day evaluation.

## Data and protocol

- Sources:
  - `paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv`
    (`sha256=b30ba6b9bc90d12482fe90431bc4798cd489810af0fdbd5b6a5c97bbbe778007`)
  - `paper/garch-x-vix/data/gld_vix_gvz_2000-2026.csv`
    (`sha256=33b7abf1d7e5b1df00f0fdcb16684ffae7cf7e0052fd863e4ce7a4b01246ff8c`)
- Assets: SPY (forecast target), QQQ, and GLD.
- Variance proxy: Parkinson daily range variance,
  `(log(high/low))² / (4 log 2)`.
- In-sample: 2010-01-04 through 2021-12-31, `n=3,021`.
- OOS forecast origins: 2022-01-03 through 2026-05-19, `n=1,098`.
- Shared evaluation rows: `n=1,097`; the final origin is dropped because its
  `t+1` target is unavailable inside the frozen endpoint.
- Seed: 42; the fitted models are deterministic.

Within the frozen window, each raw source has 4,129 rows but only 4,119 unique
dates. The 10 duplicate dates are 2026-05-04 through 2026-05-15 on trading days;
the script verifies that every same-date row is value-identical before removing
one copy. The one-to-one merged analysis frame has 4,119 unique increasing dates:
IS `n=3,021`, OOS origins `n=1,098`, and evaluated forecasts `n=1,097`.

The shared CSVs now extend beyond the original experiment. The script therefore
fails the methodology-only comparison closed at `OOS_END=2026-05-19`, records
both current source hashes, and pins the cleaned analysis slice to
`sha256=45160dbaf14b010c942af2af1d41cc4477bb166fa76e25b24dd9f91d8a2b5d48`.
Extending the OOS period is a separate robustness exercise, not part of this
repair.

## Models and timing

### HAR baseline

OLS uses daily, trailing 5-day, and trailing 22-day Parkinson variance through
day `t` to predict variance at `t+1`. An IS origin is admitted to the fit only
when its `t+1` target is also in IS; the last training origin is 2021-12-30 and
its target is 2021-12-31. The first OOS target never enters the fit.

### fGN-motivated univariate approximation

The script estimates an AR(20) on in-sample log-variance increments and anchors
the predicted increment at the observed log variance on day `t`:

`log(RV[t+1]) = log(RV[t]) + predicted_increment[t+1]`.

### Lagged cross-asset correction

The multivariate variant adds an in-sample OLS correction based on lagged QQQ
and GLD AR residuals. At each forecast origin it uses only residuals already
realized by that origin; no contemporaneous `t+1` information enters.

All three forecast arrays are indexed by origin `t`. Evaluation explicitly uses
`actual_rv = rv.shift(-1)` on those origins, so every loss compares a forecast
made with information through `t` against `RV[t+1]`.

## Hurst and dependence diagnostics

The in-sample log-structure function fits lags 1 through 20:

`E[|log RV[t+h] - log RV[t]|²] ≈ C h^(2H)`.

| Asset | Structure-function H | Increment ACF(1) |
|---|---:|---:|
| SPY | 0.103081 | -0.429661 |
| QQQ | 0.093565 | -0.440014 |
| GLD | 0.029357 | -0.491289 |

These estimates describe rough daily range-variance paths in this sample. They
do not by themselves imply that the fitted AR approximation improves forecasts.

## Corrected OOS results

### Mean QLIKE

Canonical QLIKE is `actual/predicted - log(actual/predicted) - 1`; lower is
better.

| Model | Mean QLIKE | Relative to HAR |
|---|---:|---:|
| HAR | 0.37534907 | baseline |
| fGN-motivated univariate | 0.47163477 | 25.65% higher loss |
| fGN-motivated multivariate | 0.47314873 | 26.06% higher loss |

The lagged cross-asset correction does not improve the univariate approximation
in this frozen run; its mean QLIKE is 0.32% higher.

### Canonical HAC-DM

The loss differential is `QLIKE(fGN) - QLIKE(HAR)`, so positive `t` means the
fGN variant has higher loss. The primary bandwidth is
`max(1, min(ceil(h^(1/3) n^(1/3)), n//4)) = 11` for `h=1`, `n=1,097`.

| Comparison | DM t | Two-sided p | Loss-diff ACF(1) | `|t|>3` |
|---|---:|---:|---:|:---:|
| fGN-uni vs HAR | +3.437383 | 0.000609 | -0.044616 | PASS |
| fGN-multi vs HAR | +3.452342 | 0.000577 | -0.050840 | PASS |

The public-to-repaired statistic change cannot be attributed to HAC alone,
because duplicate-date handling and the HAR training boundary changed in the
same correction. On the repaired sample, however, the lag-11 statistics are
larger than the same-sample lag-0 diagnostics shown below. Negative first-order
autocorrelation does not by itself determine the full HAC change because higher
lags also enter.

The optional Harvey-Leybourne-Newbold (1997) factors are 0.999544, yielding
diagnostic t-statistics 3.435816 and 3.450768. These are not the primary
statistics and are distinct from the Harvey-Liu-Zhu (2016) `|t|>3` reporting
screen.

### Lag sensitivity

| Comparison | lag 0 | lag 1 | lag 5 | lag 10 | lag 11 primary | lag 20 |
|---|---:|---:|---:|---:|---:|---:|
| fGN-uni vs HAR | 3.315 | 3.392 | 3.370 | 3.418 | 3.437 | 3.594 |
| fGN-multi vs HAR | 3.307 | 3.395 | 3.381 | 3.432 | 3.452 | 3.614 |

Both comparisons remain above `|t|=3` throughout the displayed lag grid. This
supports the qualitative conclusion, while the canonical lag-11 result remains
the primary statistic.

## Verdict and limitations

Verdict: `NULL_NO_FGN_IMPROVEMENT`.

- In this fixed SPY OOS window and Parkinson range-variance target, the two
  fGN-motivated approximations do not improve on HAR; HAR has lower QLIKE and
  both pairwise differences pass the conservative reporting screen.
- The conclusion is protocol-specific. It does not show that continuous-time
  rough-volatility models are generally inferior, nor that richer intraday
  realized-variance implementations cannot help.
- Parkinson range variance excludes the overnight close-to-open component and
  is not a 5-minute realized-variance target.
- This is one frozen OOS period and one primary asset. Cross-period and
  cross-asset target replications are not supplied here.
- The cross-asset residual correction is a simple lagged OLS approximation,
  not a structural multivariate rough-volatility estimator.

## Reproduction and artifacts

Run from the repository root:

```bash
uv run python experiments/k1386/k1386.py
```

The script regenerates:

- `k1386_results.json`, written through a validated temporary file and atomic
  replacement;
- `k1386_forecast_comparison.png`;
- `k1386_loss_har.npy`, `k1386_loss_fgn_uni.npy`, and
  `k1386_loss_fgn_multi.npy` for independent DM recomputation.

## References

- Corsi, F. (2009), “A Simple Approximate Long-Memory Model of Realized
  Volatility,” *Journal of Financial Econometrics* 7(2), 174-196.
  <https://doi.org/10.1093/jjfinec/nbp001>
- Diebold, F. X., and Mariano, R. S. (1995), “Comparing Predictive Accuracy,”
  *Journal of Business & Economic Statistics* 13(3), 253-263.
  <https://doi.org/10.1080/07350015.1995.10524599>
- Gatheral, J., Jaisson, T., and Rosenbaum, M. (2018), “Volatility is Rough,”
  *Quantitative Finance* 18(6), 933-949.
  <https://doi.org/10.1080/14697688.2017.1393551>
- Harvey, D., Leybourne, S., and Newbold, P. (1997), “Testing the Equality of
  Prediction Mean Squared Errors,” *International Journal of Forecasting*
  13(2), 281-291. <https://doi.org/10.1016/S0169-2070(96)00719-4>
- Harvey, C. R., Liu, Y., and Zhu, H. (2016), “...and the Cross-Section of
  Expected Returns,” *Review of Financial Studies* 29(1), 5-68.
  <https://doi.org/10.1093/rfs/hhv059>
- Newey, W. K., and West, K. D. (1987), “A Simple, Positive Semi-Definite,
  Heteroskedasticity and Autocorrelation Consistent Covariance Matrix,”
  *Econometrica* 55(3), 703-708. <https://doi.org/10.2307/1913610>
- Patton, A. J. (2011), “Volatility Forecast Comparison Using Imperfect
  Volatility Proxies,” *Journal of Econometrics* 160(1), 246-256.
  <https://doi.org/10.1016/j.jeconom.2010.03.034>
