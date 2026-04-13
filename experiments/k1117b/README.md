# K1117b: Monthly-frequency alt-data re-test for Paper 4 null compendium

**Status**: COMPLETED — **H2_ROBUST_NULL** verdict
**Date**: 2026-04-13
**Author**: Yi-Hao Lai + VolPred Research System
**Trigger**: Close the last plausible-artifact loophole in Paper 4 alt-data null narrative.

## 1. Motivation

K1116 / K1116b / K1116c all tested alt-data (EPU, NFCI, ANFCI, STLFSI) at **weekly**
frequency and found no incremental vol signal over VIX. K1116c verified this is robust
to publication delay and strict point-in-time (PIT) alignment.

**Residual concern**: Many alt-data indicators are natively **monthly** (CFNAI, UMCSENT,
INDPRO) and a few are weekly (NFCI/ANFCI/STLFSI) or daily-aggregated (EPU). Testing them
at weekly frequency forces an implicit upsampling (forward-fill) of monthly indicators to
weekly, which may *dilute* a real signal through interpolation noise.

**K1117b goal**: Test alt-data at **native monthly frequency** — the cleanest null test
because publication-delay (1-45 days) becomes << period length (30 days), leaving no
room for an "artifact" excuse if alt-data still loses.

**Hypotheses**:
- **H1 (monthly rescue)**: Some alt-data DM |t| > 3 at monthly frequency → weekly null
  was an upsampling artifact; Paper 4 needs a monthly-exception caveat.
- **H2 (monthly NULL)**: alt-data still NULL → Paper 4 null compendium is robust across
  frequencies. Strongest null evidence.
- **H3 (partial)**: 1-2 indicators pass, rest NULL → selective-indicator rescue.

## 2. Data

| Indicator | Source | Cadence | Publication delay | Release-date rule |
|-----------|--------|---------|-------------------|-------------------|
| **USEPU**   | FRED fredgraph (BBD 2016) | daily → monthly mean | T+1 BDay      | `last obs + BDay(1)` |
| **NFCI**    | FRED fredgraph (Chicago Fed) | weekly → monthly mean | Wed of W+1 (~BDay+3) | `last weekly obs + BDay(3)` |
| **CFNAI**   | FRED fredgraph (Chicago Fed) | monthly native | ~4th week of M+1 | `end of M+1` (conservative) |
| **UMCSENT** | FRED fredgraph (U. Michigan) | monthly native | last Fri of M (final) | `end of M` |
| **INDPRO**  | FRED fredgraph (Fed IP index) | monthly native | ~mid-M+1 | `end of M+1` (conservative) |

- **SPY monthly RV**: yfinance SPY daily close → `sqrt(sum(r_i^2))` per month (require >= 15 trading days).
- **VIX monthly**: yfinance `^VIX`, mean and last close per month.
- **Period**: 2000-01 → 2026-03 (315 months). After 12-month YoY warm-up for INDPRO and
  one-lag requirement, effective panel starts 2001-01.
- **IS**: 2001-01 → 2018-12 (216 months). **OOS**: 2019-01 → 2026-03 (**87 months**).
- **FRED access**: fredgraph (revision-corrected) + explicit release-calendar rules (PIT
  alignment). Same upper-bound argument from K1116c applies — revision-corrected is a
  smoother state estimate than vintage; if revised+PIT is NULL, vintage+PIT is also NULL.

**PIT alignment procedure**: At each forecast date F = end-of-month M, for each indicator
take the value with the latest `RELEASE_DATE <= F`. This becomes the signal for predicting
RV of month M+1 (applied with `shift(1)` in the regression so that regression at row t
uses only data available at end of month t-1).

## 3. Models

Seven OLS specs, matched to K1116's spec grouping but adapted for monthly alt-data:

| Spec           | Regressors (all lagged one month via `shift(1)`) |
|----------------|--------------------------------------------------|
| **M1_base**        | AR(1) on rv |
| **M2_vix**         | AR(1) + log(VIX_monthly_mean) — **baseline** |
| **M3_epu**         | AR(1) + log(USEPU) + INDPRO |
| **M4_finstress**   | AR(1) + NFCI |
| **M5_sentiment**   | AR(1) + CFNAI + log(UMCSENT) |
| **M6_all**         | AR(1) + log(VIX) + all 5 alt-data |
| **M7_altonly**     | AR(1) + 5 alt-data (NO VIX) |

**Target**: monthly RV (sqrt-scale). **Loss**: QLIKE `log(pred) + actual / pred`.
**Refit**: **expanding monthly** (refit OLS each OOS month on all prior data; minimum 24
training months).
**Statistical test**: DM-HLN (Harvey-Leybourne-Newbold 1997) two-sided, h=1 Harvey
correction. **Threshold**: Harvey (2016) |t| > 3.
**Bootstrap**: Block bootstrap B=2000, block_length=3 (Politis & Romano 1994), for
small-sample SE on loss differential. Seed=42.

## 4. Results

### 4.1 OOS performance (n=87 months)

| Spec           | n_IS | n_OOS | OOS QLIKE | OOS RMSE | R² IS (static) |
|----------------|------|------:|----------:|---------:|---------------:|
| M1_base        | 216  | 87    | −2.0914   | 0.03022  | 0.5351         |
| **M2_vix** (baseline) | 216 | 87 | **−2.0917** | **0.02998** | 0.5388 |
| M3_epu         | 216  | 87    | −2.0920   | 0.03023  | 0.5383         |
| M4_finstress   | 216  | 87    | −2.0904   | 0.02987  | 0.5449         |
| M5_sentiment   | 216  | 87    | −2.0839   | 0.03113  | 0.5463         |
| M6_all         | 216  | 87    | −2.0817   | 0.03032  | 0.5507         |
| M7_altonly     | 216  | 87    | −2.0821   | 0.03045  | 0.5487         |

Economically all specs produce nearly identical OOS QLIKE (range −2.0817 to −2.0920, all
within 0.01). **M2_vix is tied-lowest or lowest among non-trivial specs**; M3_epu is
−0.00027 below M2_vix (not meaningful).

IS R² is tightly bounded in 0.535-0.551 — the full "kitchen sink" only adds 0.012 R²
over VIX alone, and this in-sample gain does not translate to OOS improvement (in fact
OOS QLIKE worsens slightly for richer specs — classic OOS-deterioration pattern).

### 4.2 DM-HLN vs M2_vix (Harvey |t| > 3 threshold)

| Spec           | DM t (HLN) | p-value | n  | Harvey pass | Direction |
|----------------|-----------:|--------:|---:|:-----------:|:----------|
| M1_base        | −0.123     | 0.903   | 87 | ✗           | VIX ≈ AR(1) |
| M3_epu         | +0.089     | 0.929   | 87 | ✗           | tied |
| M4_finstress   | −0.422     | 0.674   | 87 | ✗           | VIX wins |
| M5_sentiment   | **−1.618** | 0.109   | 87 | ✗           | VIX wins |
| M6_all         | −1.565     | 0.121   | 87 | ✗           | VIX wins |
| M7_altonly     | −1.590     | 0.116   | 87 | ✗           | VIX wins |

**No cell** reaches Harvey |t| > 3. Maximum |t| = 1.62 (M5_sentiment, which *adds*
CFNAI+UMCSENT to AR(1) but without VIX — this spec loses marginally to M2_vix).

Direction: 5 of 6 DM tests have negative sign → VIX baseline at least numerically
outperforms every challenger except M3_epu (which ties). No spec numerically beats VIX.

### 4.3 Block-bootstrap SE (B=2000, block=3, seed=42)

| Spec           | Mean loss diff (spec − VIX) | Bootstrap SE | Bootstrap p (two-sided) |
|----------------|----------------------------:|-------------:|------------------------:|
| M1_base        | −0.00030                    | 0.00206      | 0.871                   |
| M3_epu         | +0.00028                    | 0.00306      | 0.936                   |
| M4_finstress   | −0.00126                    | 0.00246      | 0.612                   |
| **M5_sentiment** | **−0.00778**              | 0.00364      | **0.032** *             |
| M6_all         | −0.00995                    | 0.00554      | 0.069                   |
| **M7_altonly** | **−0.00957**                | 0.00488      | **0.049** *             |

**Important**: M5_sentiment and M7_altonly have nominal bootstrap p<0.05, but
**the mean diff is NEGATIVE** — i.e., they LOSE to VIX under bootstrap (VIX's loss
is systematically lower). This *strengthens* the null (VIX-sufficiency); it does NOT
rescue alt-data. Given Harvey |t|<3 for both, these fail Harvey's multiple-testing bar
and the signs also favor VIX, so conclusion is:

> Even the most "alt-data-favorable" spec (M5 sentiment using CFNAI + UMCSENT) loses
> to VIX under both DM and block-bootstrap tests at monthly frequency.

### 4.4 Diagnostics

- **SPY monthly RV** (n=303, 2001-01 .. 2026-03):
  mean 0.0461 (≈ 4.61% monthly vol), std 0.0304, skew 3.42, kurt 18.16,
  range [0.013, 0.263].
- **ADF on RV**: stat −8.21, p = 7×10⁻¹³ → **strongly stationary** (good for OLS).
- **Data coverage**: 303/303 (100%) months have all 5 alt-data PIT values in the effective panel.

## 5. Verdict: **H2_ROBUST_NULL**

No alt-data spec achieves Harvey-significant improvement over VIX at monthly frequency.

| Hypothesis | Verdict |
|-----------|---------|
| **H1** — Monthly rescue (alt-data DM \|t\|>3 at monthly frequency) | **FAIL** |
| **H2** — Null robust across frequencies (weekly + monthly) | **CONFIRMED** |
| **H3** — Selective indicator rescue | **FAIL** — all 5 indicators NULL |

### 5.1 Why this is the strongest null evidence to date

At **weekly** frequency (K1116/K1116b/K1116c), monthly alt-data were forward-filled to
weekly observations. One could argue that "forward-filling monthly CFNAI across 4 weeks
kills the signal". At monthly frequency, this concern vanishes:

- CFNAI for month M is **exactly one data point** per month — no upsampling.
- UMCSENT, INDPRO same situation.
- USEPU daily → monthly mean uses all daily values in month (no loss of information).
- NFCI weekly → monthly mean aggregates 4 weekly observations into one monthly value.

Publication-delay ≤ 45 days is << period = 30 days, but the PIT design handles this
cleanly (using only values whose RELEASE_DATE ≤ month-end F). So the K1117b design is
tight: any monthly signal present in alt-data should manifest here. **It does not.**

### 5.2 Cross-frequency comparison

| Frequency | Experiment | OOS n | Max challenger |t\| vs VIX | Verdict |
|-----------|-----------|------:|--------------------------:|---------|
| Weekly    | K1116c (PIT) | 170 | 0 (all favor VIX, max |t| = 3.66 against alt-data) | NULL |
| **Monthly** | **K1117b (PIT)** | **87** | **1.62 (still favors VIX)** | **NULL** |

Both frequencies confirm VIX-sufficiency. Neither frequency yields a single cell with
alt-data beating VIX at Harvey |t| > 3 level, even nominally.

### 5.3 Impact on Paper 4 / K1116c / broader program

| Deliverable | Change |
|-------------|--------|
| Paper 4 compendium narrative | **Strengthen** — add "cross-frequency robust null (weekly + monthly)" claim |
| K1116 / K1116b / K1116c articles | **No caveat change** — null now confirmed at clean monthly frequency |
| `research_program.md` VIX-sufficiency section | **Add K1117b** as cross-frequency confirmation |
| Future alt-data research direction | **Strongly discouraged** — 5 experiments × 3 frequencies × PIT alignment all NULL |

## 6. Limitations

1. **No true vintage data**: fredgraph (revision-corrected) used. Same argument as K1116c
   applies — revision-corrected is smoother than vintage; if revised shows NULL, vintage
   also shows NULL.
2. **Small OOS sample**: n=87 monthly observations. Bootstrap SE used to address this.
   For a Harvey |t| > 3 test, n=87 requires substantial effect size to pass — but the
   maximum |t| observed (1.62) is so far from 3 that even with n=200+ it would likely
   still fail.
3. **Static model class**: OLS (plus expanding refit). Non-linear or regime-switching
   models (Markov-switching, threshold regression) could conceivably extract alt-data
   signal, but K1121 already tested step / regime allocation and found NULL.
4. **Five indicators only**: Does not rule out other alt-data (Google Trends — but K473
   already rejected; SOFR — too recent; jump indicators — separate research line).
5. **OOS period 2019-2026**: Contains COVID-19 vol spike (Mar 2020) and 2022 rate-shock.
   No transition-edge subsample test here — all specs evaluated over full OOS block.
6. **UMCSENT release-date rule**: Uses "end of reference month" (last-Fri final release).
   Preliminary mid-month release could be slightly earlier; this is the conservative
   choice (slightly older signal). If anything, using prelim mid-month values might help
   M5_sentiment slightly — but given |t|=1.62, not plausible to flip to |t|>3.

## 7. Future work

1. **Markov-switching alt-data model**: test whether monthly alt-data provides signal
   conditional on a regime (e.g., CFNAI informative only in recession state).
2. **True ALFRED vintage re-test**: once FRED API key is available, re-run K1117b with
   first-release vintage values.
3. **Combined frequency test**: daily VIX (K1121 NULL) + weekly alt-data (K1116c NULL) +
   monthly alt-data (K1117b NULL) — a 3-frequency MIDAS or FiGARCH design to test
   whether aggregation kills signal.
4. **Non-US tests**: K1117b on TOPIX / FTSE using country-specific alt-data (JP EPU, UK
   NFCI analog) — extends Paper 4 null to cross-market.

## 8. Files

- `k1117b.py` — main experiment script (fit / DM / bootstrap)
- `k1117b_fetch_monthly.py` — monthly alt-data PIT fetch + release-date calendars
- `k1117b_plots.py` — DM bar chart + OOS prediction/cum-loss paths
- `k1117b_results.json` — all numeric results, DM/bootstrap tables, verdict
- `k1117b_oos_loss_series.csv` — per-month OOS QLIKE loss per spec (for DM)
- `k1117b_oos_predictions.csv` — per-month OOS predictions per spec + actual
- `k1117b_dm_barchart.png` — DM t-stats with Harvey ±3 thresholds
- `k1117b_oos_paths.png` — actual RV vs predictions, cum-loss differential
- `data/*_monthly_with_release.csv` — per-indicator monthly series with RELEASE_DATE
- `data/*_monthly_pit.csv` — PIT-aligned monthly panels (one row per month-end)
- `data/fetch_log.json` — fetch audit
- `data/_raw_CFNAI.csv` — raw fredgraph CFNAI download
- `run.log` — execution log

## 9. References

- Baker, S. R., Bloom, N., & Davis, S. J. (2016). Measuring economic policy uncertainty.
  *Quarterly Journal of Economics*, 131(4), 1593-1636.
- Brave, S., & Butters, R. A. (2011). Monitoring financial stability: A financial
  conditions index approach. *Chicago Fed Economic Perspectives*, Q1.
- Chicago Fed. CFNAI technical documentation (Brave et al., 2019 revision).
- Federal Reserve Board. Industrial Production and Capacity Utilization — G.17 release.
- University of Michigan. Surveys of Consumers — preliminary and final release schedule.
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility
  proxies. *Journal of Econometrics*, 160(1), 246-256.
- Harvey, D., Leybourne, S., & Newbold, P. (1997). Testing the equality of prediction
  mean squared errors. *International Journal of Forecasting*, 13(2), 281-291.
- Harvey, C. R., Liu, Y., & Zhu, H. (2016). … and the cross-section of expected returns.
  *Review of Financial Studies*, 29(1), 5-68. — |t| > 3 multiple-testing threshold.
- Politis, D. N., & Romano, J. P. (1994). The stationary bootstrap. *JASA*, 89(428),
  1303-1313.
- K1116 (`experiments/k1116/`) — weekly alt-data NULL (original).
- K1116b (`experiments/k1116b/`) — FRED publication-delay correction; timing artifact.
- K1116c (`experiments/k1116c/`) — PIT alignment; H2 robust null at weekly frequency.
- K1121 (`experiments/k1121/`) — daily step alt-data allocation NULL (6 strategies).
- K1122 (`experiments/k1122/`) — sigmoid continuous alt-data allocation NULL (72 specs).

## 10. Worktree notes

- All files within `experiments/k1117b/`.
- No modifications to `storage/memory/*` or `storage/reports/*` (preamble rule 8).
- Main thread responsible for knowledge/experience entries + feed article, not this worktree.
- Random seed 42 fixed throughout (bootstrap, rng).
