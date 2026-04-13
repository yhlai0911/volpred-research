# K1122: Continuous-weight (sigmoid) alt-data allocation

**Status**: Complete | **Period**: 2019-01-15 to 2026-04-10 (1,817 days, SPY+GLD daily; same window for SPY+GLD+TLT) | **Date**: 2026-04-13

## Motivation

K1121 tested 6 STEP-based regime allocation strategies on EPU / NFCI / Hybrid
(`w = 0.7 if alt_pct_rank<0.7 else 0.3`) and found **all NULL** vs the 50/50
SPY/GLD baseline (best Sharpe diff +0.003, p=0.966). K1121's derivative
research line #1 explicitly asked:

> Continuous weights (not regime dummies): does soft EPU/NFCI loading
> (continuous function of z-score) improve over the 70th-percentile step?
> Hypothesis: probably not (underlying info already in VIX) but worth
> 1 confirmatory experiment.

K1122 is that confirmatory experiment.

**Conjecture under test**: was the binarisation throwing away information?
A sigmoid maps the continuous z-score `z = (alt - mean_252)/std_252` into a
smooth `[0, 1]` defensive weight. If alt-data signals are weak-but-real the
sigmoid should at least nominally outperform the step.

## Hypotheses (decision tree)

| ID | Statement | Evidence requirement |
|----|-----------|---------------------|
| **H1** sigmoid SAVES | At least one (alpha, z0) combo passes Harvey t>3 AND 3/3 sub-period stable | partial overturn of K1121 |
| **H2** sigmoid USELESS | All 72 specs near-baseline NS, 0 pass Harvey, <=1/3 stability | K1121 step-regime null is robust |
| **H3** INTERMEDIATE | >=50% specs nominal-beat but no Harvey/stability | marginal, non-actionable |

## Design

### Universes (2)
- **Pair**: SPY + GLD; baseline = 50/50; sigmoid drives `wDef` on **GLD**, `(1-wDef)` on SPY
- **3-asset**: SPY + GLD + TLT; baseline = 1/3 each; `wDef` split 50/50 between GLD and TLT, `(1-wDef)` on SPY

### Drivers (3 alt-data)
- `EPU` = USEPUINDXD (Baker-Bloom-Davis daily news index, FRED)
- `NFCI` = National Financial Conditions Index (Chicago Fed, weekly)
- `STLFSI4` = St Louis Fed Financial Stress Index (weekly)

### Sigmoid weight specification
```
z_t      = (alt_t - rolling_mean_{t-252..t-1}) / rolling_std_{t-252..t-1}
w_def_t  = 1 / (1 + exp(-alpha * (z_t - z0)))
w_risk_t = 1 - w_def_t
```
- `alpha in {0.5, 1, 2, 4}` (slope: 0.5 = nearly linear, 4 = nearly step)
- `z0 in {-0.5, 0, 0.5}` (centre shift: -0.5 biases toward defensive load)
- 12 sigmoid combos x 3 drivers x 2 universes = **72 specs**

### Lookahead controls
- z-score uses **trailing-only** stats (`.shift(1)` on rolling mean/std), so
  `x_t` is never in its own normalisation
- Release-timing lags (per K1121 Codex HIGH-severity finding):
  - EPU: `shift(2)` (USEPUINDXD obs date X is published next day)
  - NFCI: `shift(5)` (weekly obs Friday published following Wednesday)
  - STLFSI4: `shift(5)` (weekly, same convention)
- Codex LOW fix in this experiment: `rolling_std == 0` -> NaN to avoid silent
  sigmoid saturation; sub-period `rs/rb` indexes intersected to avoid silent
  sample mismatch

### Evaluation
- **Sharpe** (annualised, simple returns, daily rebalance)
- **MDD**, **Calmar**, **annualised return / vol**
- **Stationary bootstrap** (Politis-Romano 1994): 1000 reps, block_mean=20, seed=42 -> Sharpe-diff vs baseline 95% CI + p-value
- **Harvey t>3 gate**: t = |obs_diff| / SE_boot, SE_boot = (CI_high - CI_low) / 3.92
- **Sub-period stability**: 2019-2021, 2022-2023, 2024-2026; "stable" = all three sub-periods nominally beat baseline

## Results

### Verdict: **H2 - sigmoid does NOT rescue alt-data**

| Metric | Value | Threshold |
|--------|-------|-----------|
| Specs evaluated | 72 (36 pair + 36 3-asset) | - |
| Specs nominally beating baseline | **24 / 72 (33%)** | <=50% -> H2 |
| Specs with bootstrap p < 0.05 | **0 / 72** | -> H2 |
| Specs passing Harvey t > 3 | **0 / 72** | -> H2 |
| Specs with 3/3 sub-period stability | **1 / 72** | -> H2 |
| Specs passing Harvey AND 3/3 stability | **0 / 72** | needed for H1 |

### Top 5 specs by raw Sharpe-diff vs baseline

| Spec (driver / alpha / z0) | Universe | Sharpe diff | p (boot) | Sharpe (full) | MDD | Calmar | Harvey | 3/3 stable |
|----------------------------|----------|------------:|---------:|--------------:|----:|-------:|:------:|:----------:|
| NFCI / 0.5 / +0.5 | 3-asset | +0.135 | 0.376 | 1.239 | -0.231 | 0.611 | NO | NO |
| NFCI / 0.5 / 0.0 | 3-asset | +0.124 | 0.336 | 1.229 | -0.233 | 0.586 | NO | NO |
| NFCI / 0.5 / 0.0 | pair    | +0.119 | 0.306 | 1.428 | -0.194 | 0.927 | NO | NO |
| NFCI / 0.5 / -0.5 | pair    | +0.116 | 0.336 | 1.426 | -0.197 | 0.917 | NO | NO |
| NFCI / 0.5 / +0.5 | pair    | +0.108 | 0.346 | 1.417 | -0.191 | 0.940 | NO | NO |

**Baseline reference**: SPY/GLD 50/50 Sharpe = 1.309 (MDD -0.203); 3-asset 1/3-each Sharpe = 1.104 (MDD -0.227). Best pair sigmoid Sharpe 1.428 = **1.09x baseline** -> well below the "Sharpe > 2x baseline = bug" threshold (Preamble Rule #5).

### Breakdown by driver

| Driver | n_specs | n_nominal_beat | median diff | min p-value | max diff |
|--------|--------:|---------------:|------------:|------------:|---------:|
| EPU | 24 | 6 | -0.118 | 0.102 | +0.060 |
| **NFCI** | 24 | **18** | **+0.051** | 0.306 | +0.135 |
| STLFSI4 | 24 | **0** | -0.188 | 0.036 | -0.022 |

- **NFCI** is the only driver that nominally helps in the majority of specs (consistent with K1121's S5 NFCI being the only step-regime spec to *tie* the baseline). But still 0 specs pass any formal threshold.
- **STLFSI4** is uniformly harmful: 0/24 nominally beat baseline, and one spec is significant in the WRONG direction (p=0.036, lower Sharpe than baseline). This matches K1116's finding that STLFSI added nothing for forecasting.
- **EPU** fails in both directions and corroborates K1121's finding that EPU is "topic-specific, not general stress" (it raised wSPY in 2022 rate shock).

### Breakdown by alpha (sigmoid steepness)

| alpha | n_nominal_beat | median diff |
|------:|---------------:|------------:|
| 0.5 (gentle) | 12/18 | **+0.040** |
| 1.0 | 6/18 | -0.039 |
| 2.0 | 4/18 | -0.166 |
| 4.0 (sharp, near step) | 2/18 | -0.248 |

**Steeper sigmoids (closer to step) hurt more** - the only "edge" comes from being barely informative at all (alpha=0.5 is nearly linear). This is consistent with the interpretation that the alt-data signals do not contain actionable conditioning information; the gentle sigmoid is functionally close to constant 0.5 weight, which is just K1121's S1 baseline by construction.

### Sub-period stability

Only **1 / 72 specs** beat the baseline in all three sub-periods (2019-21, 2022-23, 2024-26): `EPU_a0.5_z0.5_3a` with full-sample diff +0.032 and sub-period diffs `[+0.100, +0.002, +0.125]`. None of the NFCI specs were 3/3 stable - their gains concentrated in 2024-26 with losses in 2022-23.

## Interpretation

### Core finding: sigmoid does NOT rescue alt-data allocation

1. **No spec passes Harvey t>3**, the bar for any reportable Sharpe-based claim
2. **Only 33% nominally beat baseline** - well below 50% (a coin-flip would give ~50%); even the nominal beats are concentrated in NFCI, the one driver K1121 already showed could tie (not beat) baseline
3. **Sigmoid steepness is monotonically harmful**: alpha=0.5 (gentle) > alpha=4 (near-step). The "best" sigmoid is functionally close to constant 50/50 - i.e., the alt-data conditioning adds nothing
4. **Sub-period stability is essentially absent** (1/72) - what little nominal edge there is, is sample-period-dependent
5. **3-asset extension does not change the story** - adding TLT to the defensive sleeve did not unlock alt-data signal

### Why does NFCI nominally help while EPU/STLFSI hurt?

NFCI is the only driver that K1121 found could *tie* the baseline (S5 Sharpe 1.312 vs S1 1.309). K1122 confirms this is a **drawdown-insurance pattern**, not alpha: top NFCI sigmoid spec MDD -0.194 vs baseline -0.203, Calmar 0.927 vs 0.888. NFCI mechanically de-loads SPY in stress (because financial conditions tighten in stress), but the de-loading is too late or too small to add Sharpe. **This is consistent with the K687/K697 "VT = drawdown insurance, not alpha" finding** in CLAUDE.md.

### What this rules out

- **Binarisation was NOT the bug** in K1121. The continuous-loading version is no better, and steeper sigmoids (which approach the step) are worse than gentle ones
- **Alt-data conditioning** of allocation weights does not survive even the loosest formal threshold
- The K1121 finding (alt-data null for allocation) is **robust to functional form**

## K1121 + K1122 combined evidence (alt-data NULL for allocation)

| Test | K1121 (step) | K1122 (sigmoid) | Combined |
|------|--------------|-----------------|----------|
| Best alt-data Sharpe diff | +0.003 (NFCI) | +0.135 (NFCI sigmoid 3a) | NFCI consistently bumps a tiny amount |
| p-value of best | 0.966 | 0.336 | NS in both |
| Specs passing Harvey | 0 / 6 | 0 / 72 | **0 / 78 total** |
| Sub-period stability | not formally tested | 1 / 72 | essentially absent |

## Limitations

1. **Bootstrap p-value is not studentized** (Codex MEDIUM, K1122 review). Centred-percentile bootstrap is approximate; for borderline cases this could matter, but the present results are NS by every reasonable threshold so studentization would not change the verdict
2. **Release-timing lags (HIGH risk per K1122 Codex review)**: fixed daily lags (2 / 5 / 5) are not full publication-calendar alignment. K1121 used the same scheme after Codex review accepted it; results below baseline are conservative regardless. Sensitivity to looser lags (e.g. shift(10) for weekly data) was not run; given the 0/72 Harvey result, looser lags would only worsen the case for sigmoid
3. **Single OOS window** (2019-01-15 to 2026-04-10). Pre-2018 alt-data testing requires backfilled FRED EPU (USEPUINDXD only goes to 2017 reliably)
4. **Two universes only** (SPY+GLD, SPY+GLD+TLT). Bond-heavy or international universes not tested
5. **No transaction costs**. Daily rebalance with sigmoid weights would have non-trivial turnover, which would further erode any edge
6. **Sigmoid grid is 4 x 3 = 12 combos**. Wider grid possible but bootstrap p-value spread already covers the parameter region of interest

## Paper 4 implication

K1122 **expands the alt-data NULL territory** further:
- K1116/K1118 (9 experiments): alt-data NULL for *forecasting*
- K1121: alt-data NULL for *step-based allocation*
- **K1122**: alt-data NULL for *continuous-loading allocation*

Compendium statement: "Alt-data (EPU/NFCI/STLFSI4) cannot predict vol AND cannot improve SPY/GLD or SPY/GLD/TLT allocation, regardless of whether the loading is binary or continuous."

## Derivative research directions

1. **Cross-asset alt-data allocation**: bond-heavy (TLT-dominant) or international (EFA/EEM) universes - K1118 cross-asset forecasting was null but allocation cross-asset still has open territory
2. **Event-driven alt-data with absolute thresholds** (K1121 derivative #3): NFCI > 0.5 for N consecutive days as a "crisis flag" - de-risk only, no whipsaw. Lower aspiration than continuous, but might survive
3. **Alt-data for risk *targeting*** (not allocation): use NFCI to scale leverage of an existing strategy rather than choose between assets. Different risk-management role
4. **Macro-state classifier** (multi-driver fusion via supervised learning): e.g. HMM or random forest on EPU + NFCI + STLFSI4 jointly - K1116 already negative on regression, but classifier-style aggregation has not been tested

## Files

- `k1122.py` - experiment script (sigmoid grid, 2 universes, bootstrap, sub-periods)
- `k1122_results.json` - 72-spec results, top5, summary, decision-tree verdict
- `k1122_plots.py` - plot generator
- `k1122_sigmoid_curves.png` - illustration of alpha and z0 effects on the sigmoid
- `k1122_sharpe_heatmap.png` - 6-panel grid (3 drivers x 2 universes) of Sharpe-diff
- `k1122_summary.png` - per-driver bar charts
- `data/panel.parquet` - merged daily panel (SPY/GLD/TLT/VIX/EPU/NFCI/STLFSI4)
- `data/signals.parquet` - 36 sigmoid weight series + baseline
- `data/backtest_pair.parquet`, `data/backtest_3asset.parquet` - daily strategy returns
- `data/fred_USEPUINDXD.csv`, `data/fred_NFCI.csv`, `data/fred_STLFSI4.csv` - cached FRED data
- `run.log`

## References

- **K1121 (Apr 2026)**: step-based allocation NULL on EPU/NFCI/Hybrid -> motivation for sigmoid test
- **K1116 / K1118**: alt-data forecasting NULL (9 experiments) -> consistent territory
- **K687 / K697 (CLAUDE.md)**: VT = drawdown insurance, not alpha generator -> matches NFCI MDD pattern in K1122
- **Politis & Romano (1994)**: stationary bootstrap for time-series Sharpe inference
- **Harvey, Liu, Zhu (2016)** *RFS*: t > 3 threshold for Sharpe-based discoveries
- **Baker, Bloom, Davis (2016)** *QJE*: EPU index construction
- **Brave & Butters (2011)**: NFCI methodology
- **Kliesen, Owyang & Vermann (2012)** Federal Reserve Bank of St Louis Review: STLFSI methodology

## Codex review trail

1. **Pre-run review** (2026-04-13): one HIGH (release-timing fixed-lag vs publication-calendar - inherited from K1121 acceptance), two MEDIUM (bootstrap p-value not studentized, sub-period rs/rb not intersected), two LOW (rolling std=0 -> inf, NaN swallowed in bootstrap mean). MEDIUM (sub-period intersection) and LOW (std=0) fixed in code; HIGH and bootstrap-method MEDIUM are acknowledged as inherited limitations from K1121's accepted scheme; given 0/72 Harvey result, neither would change the verdict
2. **Self-check (Preamble Rule #5)**: best Sharpe 1.428 / baseline 1.309 = 1.09x ratio - well below 2x bug threshold

Seed: 42 (np.random.seed + np.random.default_rng for bootstrap).
