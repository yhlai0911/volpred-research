# K1655 — Growth-at-Risk moved to markets with true real-time NFCI vintages

**Statistical verdict: `NULL`. Independent post-run review: `PASS` (2026-07-11).**

K1655 asks whether the Chicago Fed National Financial Conditions Index (NFCI) predicts the
5% left tail of future S&P 500 price-index returns, using the Growth-at-Risk quantile-regression
design of Adrian, Boyarchenko, and Giannone (2019). This rerun replaces the invalid
final-vintage NFCI proxy used by the original experiment with genuine ALFRED point-in-time
(PIT) values.

The supported conclusion is deliberately narrow: **over the available 2011–2026 true-PIT
sample and against an unconditional empirical-quantile benchmark, NFCI does not improve
out-of-sample forecasts of the S&P 500 return left tail.** This result does not show that NFCI
can never be useful, does not test a forced-deleveraging mechanism, and does not establish
whether VIX encompasses NFCI.

## What the rerun corrected

The original run used today's revised NFCI history and assigned artificial release dates to it.
That created two lookahead problems: NFCI was scored before its first public vintage, and later
origins used revisions that were not yet available. The original `CONDITIONAL_PASS`, 2000–2026
sample, 2008 calibration discussion, significant in-sample “GaR fan,” and VIX-dominance
narrative are withdrawn.

The corrected implementation:

- downloads the complete ALFRED `output_type=1` revision history with pagination;
- pins the compressed raw response and a separate audit record;
- at every Friday origin selects the latest observation with the unique active inclusive
  interval `realtime_start <= origin <= realtime_end`;
- excludes every origin before the first public vintage, 2011-05-25;
- refuses final-vintage fallback, overlapping revision intervals, incomplete pagination,
  post-launch gaps, or timing-gate failures;
- preserves the strict forecast-training embargo `j + H < i`;
- serializes every OOS forecast and loss, then reconstructs all reported cells from that CSV
  before writing the result JSON.

## Data and sample

| Input | Source | Role |
|---|---|---|
| S&P 500 price index (`^GSPC`) | yfinance adjusted close | Forward log returns and realized-volatility targets |
| NFCI real-time revisions | FRED/ALFRED `NFCI`, `output_type=1` | Primary conditioning variable |
| VIX close (`VIXCLS`) | FRED snapshot | Secondary comparison variable; not an encompassing test |

- Weekly frequency: W-FRI.
- Aligned panel: **788 weeks, 2011-05-27 through 2026-06-26**.
- Selected NFCI observations: 2011-05-20 through 2026-06-19.
- ALFRED input: **207,755 revision rows**, 3 complete pages, 786 vintage dates, and 809
  observation dates.
- Of 1,382 requested Friday origins, **594 before the first vintage are excluded**, 788 are
  valid, and post-release missing origins equal 0.
- NFCI information lag: minimum 7 days, median 7 days, maximum 21 days; hard gate 28 days.

The raw revision cache SHA-256 is
`a31101f9a82773619a35dd1f0da65250ac2467e5e1c8f8e17bf620067a0e880a`; the derived
Friday PIT cache SHA-256 is
`eb927e7ebfc33ff8acf0ece00bb000ac95a0bfe684f3e225e9653cb1a17440e0`.

## Method

- Targets: forward cumulative log return and forward annualized realized volatility at
  horizons 1, 4, and 12 weeks.
- Quantiles: 0.05, 0.25, 0.50, 0.75, and 0.95. The primary claim is NFCI conditioning of the
  0.05 return quantile.
- In-sample model: quantile regression with a moving-block bootstrap, 500 replications,
  seed 1655. Reported `boot_p` uses the bootstrap standard deviation with a normal
  approximation; percentile intervals are also serialized, so this block is descriptive and
  is not the predictive claim.
- OOS model: expanding window, minimum 250 admissible weeks, refitted every four weeks and
  scored weekly.
- Benchmark: unconditional empirical quantile from the identical embargoed training rows.
- Loss: pinball loss.
- Test: Harvey-Leybourne-Newbold-corrected DM with Newey-West lag
  `max(H-1, ceil(H^(1/3) * n^(1/3)))`. A one-sided improvement requires a negative statistic;
  the project-wide Harvey gate requires `t < -3`.

## Results

### Primary OOS result: NFCI, return tail at τ = 0.05

| Horizon | OOS n | Conditional loss | Unconditional loss | Improvement | DM-HLN t | p | NW lag |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 week | 536 | 0.0030762121 | 0.0030178439 | **−1.934%** | +0.898 | 0.370 | 9 |
| 4 weeks | 530 | 0.0062147593 | 0.0060539435 | **−2.656%** | +0.690 | 0.491 | 13 |
| 12 weeks | 514 | 0.0104202254 | 0.0097085348 | **−7.331%** | +1.819 | 0.0695 | 19 |

All three conditional forecasts have higher loss than the benchmark. None has a negative DM
statistic, none is a significant improvement, and none passes the Harvey gate.

### In-sample diagnostic

The NFCI slope at τ = 0.05 is negative at all three horizons but is not statistically
distinguishable from zero in this PIT sample:

| Horizon | NFCI slope | bootstrap-SD normal p | 90% percentile interval |
|---:|---:|---:|---:|
| 1 week | −0.01627 | 0.151 | [−0.03571, +0.00064] |
| 4 weeks | −0.03994 | 0.205 | [−0.08259, +0.01142] |
| 12 weeks | −0.01486 | 0.871 | [−0.13991, +0.17432] |

The corrected data therefore do not support the earlier claim that an equity GaR fan was
replicated at all horizons.

VIX and the realized-volatility target remain secondary diagnostics in the original rerun. No
VIX-return cell passes the `t < -3` gate against the unconditional benchmark. The direct
VIX-versus-NFCI and encompassing follow-up is reported below.

## Follow-up: does VIX dominate or encompass NFCI?

The addendum first freezes the original expanding-window forecasts and compares VIX-only with
NFCI-only on identical origins. VIX has lower point-estimate loss at all three horizons, but
none of the paired differences passes either the `t < -3` gate or Holm-adjusted `p < 0.05`:

| Horizon | OOS n | VIX loss | NFCI loss | VIX improvement | canonical DM t | Holm p |
|---:|---:|---:|---:|---:|---:|---:|
| 1 week | 536 | 0.0026688621 | 0.0030762121 | +13.242% | −1.608 | 0.325 |
| 4 weeks | 530 | 0.0058484774 | 0.0062147593 | +5.894% | −1.538 | 0.325 |
| 12 weeks | 514 | 0.0102404331 | 0.0104202254 | +1.725% | −0.638 | 0.524 |

The formal quantile forecast-encompassing comparison cannot reuse an expanding recursive
estimation window. Following the fixed-window requirement in Giacomini and Komunjer (2005)
and Giacomini and White (2006), the primary design refits VIX-only and VIX+NFCI every week on
exactly 400 admissible observations. The strict embargo remains `j + H < i`.

| Horizon | OOS n | VIX+NFCI loss | VIX loss | Joint improvement | DM diagnostic | CQFE full bootstrap Holm p | `lambda_joint=0` bootstrap Holm p |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 week | 386 | 0.0029301637 | 0.0028250761 | −3.720% | +0.610 | 0.822 | 1.000 |
| 4 weeks | 380 | 0.0071198793 | 0.0069142139 | −2.975% | +0.437 | 0.822 | 1.000 |
| 12 weeks | 364 | 0.0136779033 | 0.0119394247 | −14.561% | +1.379 | 0.723 | 1.000 |

The nested-model DM statistics are diagnostics only. CQFE inference is based on 1,999-rep
circular moving-block bootstrap distributions, with all 5,997 requested replications
completed. The analytic chi-square p values are retained as diagnostics because the analytic
covariance uses a single residual-sparsity estimate; they cannot upgrade the conclusion.
Rolling-window sensitivities R=300 and R=500 likewise show higher joint-model loss at all
three horizons.

The follow-up verdict is a **double null**: there is no robust evidence that VIX dominates
NFCI, and there is no evidence that NFCI adds predictive information beyond VIX. Failure to
reject incremental value is not proof that VIX fully encompasses, subsumes, or replaces NFCI.

## Audit and review

- Forecast artifact: **31,600 rows across all 60 model cells**, SHA-256
  `0b47082bcc51be299be45fc122cc8c5a410cd691a0665594ddd88e68712c468e`.
- The serialized artifact independently reproduces every cell's mean losses, improvement, DM
  statistic, p value, and bandwidth; maximum DM-statistic discrepancy is below `6.5e-14`.
- All target, embargo, observation-date, and revision-window timing gates pass.
- Quantile-regression fits: 37,980 calls. Three iteration-limit events resolved at the second
  20,000-iteration stage; unresolved limits, other warnings, bootstrap exceptions, and OOS
  exceptions are all zero. Every bootstrap cell completed 500/500 replications.
- Independent review: `reviews/codex_alfred_pit_postrun_2026-07-11.md`.
- VIX/NFCI addendum: 4,970 serialized forecast rows, SHA-256
  `04a17e6741dd7ec3da2f15523a8675d5410bcaaaaab7fd015ac115558270e356`; all three 1,999-rep
  CQFE bootstraps completed without failure. Independent numeric verification and post-run
  review both pass; see
  `reviews/codex_vix_nfci_encompassing_postrun_2026-07-11.md`.

## Files and reproduction

| File | Purpose |
|---|---|
| `K1655.py` | Reproducible experiment and ALFRED PIT reconstruction |
| `K1655_results.json` | Full reported results, provenance, gates, and diagnostics |
| `K1655_oos_forecasts.csv` | Forecast-level OOS audit artifact |
| `data/alfred_NFCI_vintage_history.csv.gz` | Pinned raw ALFRED revision history |
| `data/alfred_NFCI_vintage_audit.json` | Pagination, row-count, vintage, and hash audit |
| `data/alfred_NFCI_pit_weekly.csv` | Derived Friday-origin PIT observations |
| `K1655_nfci_slope_across_quantiles.png` | In-sample NFCI slope diagnostic |
| `K1655_gar_quantiles_vs_realized.png` | OOS conditional quantile versus realized return |
| `K1655_oos_pinball_by_horizon.png` | OOS pinball-loss comparison |
| `K1655_vix_nfci_encompassing.py` | Frozen paired DM and fixed-window CQFE addendum |
| `K1655_vix_nfci_encompassing_results.json` | Addendum results, gates, and review metadata |
| `K1655_vix_nfci_encompassing_oos.csv` | Addendum forecast-level audit artifact |
| `K1655_vix_nfci_encompassing.png` | Same-origin loss comparison across horizons |

Use the pinned cache without network access:

```bash
python experiments/K1655/K1655.py
```

Refresh the ALFRED input explicitly when a new immutable cache is intended:

```bash
python experiments/K1655/K1655.py --refresh-alfred
```

## References

- Adrian, T., Boyarchenko, N., & Giannone, D. (2019). “Vulnerable Growth.” *American
  Economic Review*, 109(4), 1263–1289. https://doi.org/10.1257/aer.20161923
- Croushore, D., & Stark, T. (2001). “A Real-Time Data Set for Macroeconomists.” *Journal of
  Econometrics*, 105(1), 111–130. https://doi.org/10.1016/S0304-4076(01)00072-0
- Diebold, F. X., & Mariano, R. S. (1995). “Comparing Predictive Accuracy.” *Journal of
  Business & Economic Statistics*, 13(3), 253–263.
- Giacomini, R., & Komunjer, I. (2005). “Evaluation and Combination of Conditional Quantile
  Forecasts.” *Journal of Business & Economic Statistics*, 23(4), 416–431.
- Giacomini, R., & White, H. (2006). “Tests of Conditional Predictive Ability.”
  *Econometrica*, 74(6), 1545–1578.
- Clark, T. E., & McCracken, M. W. (2001). “Tests of Equal Forecast Accuracy and
  Encompassing for Nested Models.” *Journal of Econometrics*, 105(1), 85–110.
- Harvey, D., Leybourne, S., & Newbold, P. (1997). “Testing the Equality of Prediction Mean
  Squared Errors.” *International Journal of Forecasting*, 13(2), 281–291.
