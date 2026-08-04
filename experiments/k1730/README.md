# K1730 — GEVReg-MIDAS-SSVS: does a macro block improve weekly tail-risk intervals?

**Status**: NULL result. Arm A of the K1730 programme, production run
(`quick_mode = false`, seed 42, runtime 3.7 h,
finished 2026-07-19T16:04:42.721751+00:00).

## 1. Research question

Weekly realised-volatility intervals for SPY are already well described by HAR
terms. This experiment asks a narrower question: once HAR is in the model, does a
MIDAS-weighted block of point-in-time macro releases (CPI, NFP, IP, UNRATE, VIX,
TERM) add anything to the *tails* — the quantiles and the expected shortfall,
not the conditional mean?

The estimator is a GEV regression with MIDAS-aggregated macro covariates and SSVS
selection over the macro block, so the macro contribution can be switched off
(`GEV-HAR`) inside the identical likelihood rather than compared across families.

## 2. Data and sample

- SPY daily realised volatility, aggregated to 1,640 weekly blocks
  (1995-02-06 → 2026-07-16, 7,936 daily observations).
- Macro: CPI, NFP, IP, UNRATE, VIX, TERM, **first-release vintages only**, with
  release stamps. Median macro staleness at the forecast origin is
  {'CPI': 15.0, 'NFP': 21.0, 'IP': 16.0, 'UNRATE': 21.0, 'VIX': 16.0, 'TERM': 16.0} days — the model never sees a revision.
- Local sources under `data/`; FRED first-release series and CBOE VIX.

## 3. Evaluation protocol

Rolling annual refits. The estimation set is every block that *finished strictly
before* the refit date; the forecast set is the blocks starting in that calendar
year. No parameter is fitted on a week it later scores. The common scoring sample
is **967 weekly blocks, 2008-01-07 → 2026-07-13**.

Losses: pinball over the τ grid, Kupiec/Christoffersen interval tests, McNeil-Frey
ES backtest, PIT calibration, and Diebold-Mariano with the repo-canonical HAC
bandwidth under the Harvey (2016) |t| > 3 threshold.

### Headline numbers

| Model | Mean pinball | 90% empirical coverage |
|---|---:|---:|
| GEVReg-MIDAS-SSVS | 0.11434 | 0.8521 |
| GEV-HAR | 0.11224 | 0.8625 |
| Gaussian-MIDAS | 0.11510 | 0.8480 |
| HAR-QR | 0.11201 | 0.8542 |
| Empirical | 0.16539 | 0.8366 |

## 4. Result — the macro block adds nothing

`GEV-HAR` (no macro at all) scores a *lower* pinball loss than the full
GEVReg-MIDAS-SSVS. The DM comparison against GEV-HAR favours the benchmark and
does not clear the Harvey threshold, so the honest reading is "no detectable
difference", not "macro hurts".

**Placebo.** The macro history is re-attached to the target at lags
[52, 104, 156, 208, 260] weeks (non-circular: the head is left undefined and dropped
from *every* arm, so wrapping cannot put late releases in front of early
origins). 1380 blocks are scored in every arm. The
point-in-time check is re-run on each shifted stamp array and reports 0
violations for all 5 shifts.

Real macro alignment: 0.11415. Placebo range
[0.11245, 0.11471], median 0.11303.
4/5 placebo arms do at
least as well as the real alignment → one-sided p = 0.833.

with 5 shifts the smallest attainable p-value is 0.167; this is a coarse placebo comparison, not a precise permutation test

This is a **coarse placebo comparison, not a permutation test**. With
5 shifts the smallest attainable p-value is
0.167, so the placebo can corroborate a null but could
never have established a positive result. It is reported as corroboration only.

## 5. What this evidence does *not* support

- **The SSVS posterior inclusion probabilities are diagnostic-only.** Inference
  tier: `diagnostic_only`. Worst R-hat 1.107, worst
  |Geweke z| 28.05. The chains do not mix well enough for
  the PIPs to be read as posterior evidence about which macro variable matters.
  `test_k1730_recovery.py` check 3 shows the same sampler recovers a known ground
  truth (PIP 1.000 / 0.120, R-hat 1.001), which is why the real-data behaviour is
  read as posterior geometry rather than as a sampler bug — but that does not
  promote the real-data PIPs to inference.
- **No claim about the shape of the likelihood surface.** Mean basin concentration
  is 0.918 and the mean feasible-optimum rate is
  0.986; the low *feasible-start* rate
  (0.60) is a property of the random start box,
  not of the likelihood. The v1 wording on this point is **RETRACTED** — it was an
  artefact of a constant exterior penalty plus wide random starts, and the
  penalty is now smooth (see `test_k1730_recovery.py` section 1).
- **Interval calibration is not clean for any model**, including the benchmarks:
  every Kupiec/CC p-value in Table 1 rejects at 5%. The NULL is about the macro
  block's marginal contribution, not a claim that these intervals are well
  calibrated.

## 6. Limitations

- One asset (SPY), one horizon (weekly), one macro block. Nothing here
  generalises to other assets or to daily/monthly horizons.
- The placebo has 5 shifts; its resolution floor is stated above.
- The SSVS chains do not converge on real data, so the selection channel is
  described, not tested.
- First-release vintages remove revision lookahead but not real-time publication
  irregularities (holiday shifts, off-cycle releases).

## 7. Reproducing

```
uv run python k1730_gevreg_midas_ssvs.py --workers 6      # ~3.7 h, seed 42
uv run python k1730_report_tables.py                      # the tables below
uv run python verify_readme_alignment.py                  # prose to JSON gate
uv run python test_k1730_recovery.py                      # 19 estimator checks
```

See `reproduce_spec.json` for input hashes.

---

## Generated tables

OOS sample: 967 weekly blocks, 2008-01-07 → 2026-07-13

### Table 1 — Full out-of-sample period

| Model | Pinball | 90% cov. | below/above | Kupiec p | CC p | VaR95 rate | VaR99 rate | PIT χ² p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| GEVReg-MIDAS-SSVS | 0.11434 | 0.852 | 96/47 | 0.0000 | 0.0000 | 0.0486 | 0.0145 | 4.41e-05 |
| GEV-HAR | 0.11224 | 0.862 | 90/43 | 0.0002 | 0.0005 | 0.0445 | 0.0145 | 5.00e-02 |
| Gaussian-MIDAS | 0.11510 | 0.848 | 66/81 | 0.0000 | 0.0000 | 0.0838 | 0.0321 | 4.70e-04 |
| HAR-QR | 0.11201 | 0.854 | 83/58 | 0.0000 | 0.0000 | 0.0600 | 0.0145 | 1.29e-05 |
| Empirical | 0.16539 | 0.837 | 114/44 | 0.0000 | 0.0000 | 0.0455 | 0.0155 | 0.00e+00 |

*Nominal: 90% coverage, ~48/48 two-sided exceedances, VaR95 rate 0.050, VaR99 rate 0.010.*

### Table 2 — Diebold-Mariano, GEVReg-MIDAS-SSVS vs each benchmark

*Pinball loss averaged over the τ grid; repo-canonical HAC bandwidth; Harvey (2016) threshold |t| > 3.*

| Comparison | t | p | HAC lag | acf(1) | Favours | Harvey-sig |
|---|---:|---:|---:|---:|---|---|
| vs GEV-HAR | 2.16 | 0.0311 | 10 | 0.168 | benchmark | no |
| vs Gaussian-MIDAS | -0.68 | 0.4948 | 10 | 0.159 | model | no |
| vs HAR-QR | 1.95 | 0.0512 | 10 | 0.156 | benchmark | no |
| vs Empirical | -6.02 | 0.0000 | 10 | 0.505 | model | yes |

### Table 3 — Expected-shortfall backtest (McNeil-Frey, bootstrapped)

| Model | Level | Exceedances | Mean residual | p |
|---|---:|---:|---:|---:|
| GEVReg-MIDAS-SSVS | 0.950 | 47 | 0.1627 | 0.0478 |
| GEVReg-MIDAS-SSVS | 0.990 | 14 | 0.2345 | 0.1414 |
| GEV-HAR | 0.950 | 43 | 0.1898 | 0.0203 |
| GEV-HAR | 0.990 | 14 | 0.1999 | 0.1726 |
| Gaussian-MIDAS | 0.950 | 81 | 0.2018 | 0.0005 |
| Gaussian-MIDAS | 0.990 | 31 | 0.2995 | 0.0037 |
| HAR-QR | 0.950 | — | — | not identified |
| HAR-QR | 0.990 | — | — | not identified |
| Empirical | 0.950 | — | — | not identified |
| Empirical | 0.990 | — | — | not identified |

### Table 4 — Subperiods (pinball / 90% coverage)

| Model | 2008-2009 GFC (n=104) | 2010-2019 post-crisis (n=522) | 2020-2021 COVID (n=104) | 2022-2026 tightening (n=237) |
|---|---|---|---|---|
| GEVReg-MIDAS-SSVS | 0.1030 / 0.837 | 0.1149 / 0.852 | 0.1298 / 0.808 | 0.1114 / 0.878 |
| GEV-HAR | 0.0936 / 0.856 | 0.1150 / 0.860 | 0.1300 / 0.817 | 0.1065 / 0.890 |
| Gaussian-MIDAS | 0.1151 / 0.827 | 0.1148 / 0.841 | 0.1312 / 0.827 | 0.1087 / 0.882 |
| HAR-QR | 0.0922 / 0.865 | 0.1144 / 0.851 | 0.1321 / 0.798 | 0.1066 / 0.882 |
| Empirical | 0.2226 / 0.760 | 0.1697 / 0.797 | 0.1637 / 0.875 | 0.1314 / 0.941 |

### Table 5 — Subperiod DM vs GEV-HAR (no macro)

| Subperiod | t | p | Favours |
|---|---:|---:|---|
| 2008-2009 GFC | 2.38 | 0.0189 | benchmark |
| 2010-2019 post-crisis | -0.17 | 0.8662 | model |
| 2020-2021 COVID | -0.06 | 0.9551 | model |
| 2022-2026 tightening | 2.02 | 0.0445 | benchmark |

### Table 6 — SSVS posterior inclusion probabilities

| Variable | Mean PIP | Min | Max | Refits with PIP>0.5 |
|---|---:|---:|---:|---:|
| CPI | 0.663 | 0.112 | 0.994 | 11/19 |
| NFP | 0.452 | 0.145 | 0.925 | 7/19 |
| IP | 0.120 | 0.088 | 0.248 | 0/19 |
| UNRATE | 0.472 | 0.090 | 0.922 | 8/19 |
| VIX | 0.869 | 0.591 | 0.993 | 19/19 |
| TERM | 0.140 | 0.086 | 0.301 | 0/19 |

MCMC diagnostics across all refits: worst R-hat 1.107, worst |Geweke z| 28.05 (ACF-sized bandwidth; 49.64 under the fixed Newey-West rule), min ESS 42, max cross-chain PIP spread 0.267.

**Inference tier: DIAGNOSTIC_ONLY** — 0/19 refits meet the pre-registered convergence gate {'rhat_max_lt': 1.05, 'ess_min_gte': 400, 'geweke_max_abs_z_lt': 2.0}. The sampler does not meet the pre-registered convergence gate at every refit vintage, so the posterior inclusion probabilities and the posterior predictive describe what this fixed-seed sampler did, not a converged posterior. They are reported as diagnostics and no claim in this experiment rests on them.

### Table 7 — GEV MLE multistart diagnostics

- Feasible *starting points*: min 0.600, mean 0.600 — a property of the random start distribution, not of the likelihood surface
- Starts reaching a feasible *optimum*: min 0.967, mean 0.986
- Basin concentration (feasible optima reaching the best one): min 0.867, mean 0.918 — this is the only figure here that speaks to multiple optima
- Fewest starts reaching the best basin: 26 of 30
- All Hessians positive definite: True
- Max Hessian condition number: 17853
- Max Nelder-Mead improvement over L-BFGS-B: 1.64e-09
- Estimated ξ range across refits: [-0.140, -0.095]

### Table 8 — Non-circular lag-shift placebo

Macro history re-attached at lags [52, 104, 156, 208, 260] weeks; 1380 blocks scored in every arm (first 260 dropped from all arms alike).

| Arm | Mean pinball |
|---|---:|
| real macro (matched sample) | 0.11415 |
| placebo_shift_104w | 0.11289 |
| placebo_shift_156w | 0.11245 |
| placebo_shift_208w | 0.11405 |
| placebo_shift_260w | 0.11471 |
| placebo_shift_52w | 0.11303 |
| GEV-HAR, no macro at all | 0.11169 |

- Placebo arms at least as good as real: 4/5 → one-sided p = 0.833
- with 5 shifts the smallest attainable p-value is 0.167; this is a coarse placebo comparison, not a precise permutation test
- Point-in-time check re-run on every shifted macro history: 0 violations

The real macro alignment sits inside the spread of placebo alignments: re-attaching the macro history at an arbitrary lag does the job about as well. That is what a null macro contribution looks like, and it is the expected outcome under H0 rather than a failed check.


