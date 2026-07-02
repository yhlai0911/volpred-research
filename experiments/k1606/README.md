# K1606 — Deposit-flightiness state variable vs regional-bank realized volatility

**Verdict: NULL.** An aggregate deposit-flightiness state variable adds **no robust
incremental out-of-sample predictive power** over an HAR-RV baseline for the future
realized volatility of the regional-bank ETF **KRE** (DM t = −0.38, p = 0.70, h = 5).
The same null holds across a 7-stock component basket.

---

## 1. Honest reframe statement (read this first)

The original backlog item asked whether a bank's **uninsured-deposit share** has
**cross-sectional** predictive power for its equity volatility. That test requires
**FFIEC call-report bank-level uninsured-deposit ratios**, which **this platform does
not have**. Rather than fabricate or approximate bank-level data, this experiment runs
a **data-available time-series reframe**:

> Does an **aggregate deposit-flightiness** state variable — built from FRED weekly
> total commercial-bank deposits — predict the **future realized volatility** of the
> regional-bank ETF (KRE) and its liquid components, **incrementally over HAR-RV**?

**What the reframe sacrifices (explicit):**
- No bank-level cross-section. We cannot rank banks by fragility.
- No per-bank uninsured-deposit share; the signal is one **systematic**, economy-wide
  deposit-flow regime variable, identical for every bank on a given day.
- **No cross-sectional uniqueness claim is made.** The result speaks only to whether a
  systematic time-series deposit-flow regime helps forecast regional-bank vol. It does
  **not** confirm or refute the original cross-sectional uninsured-deposit hypothesis.

## 2. Motivation and literature

After the 2023 SVB / regional-bank crisis, "deposit flight" became a core state
variable for regional-bank systemic risk. Jiang, Matvos, Piskorski & Seru (2023) link
uninsured deposits to bank fragility; Drechsler, Savov & Schnabl (the "deposits
channel") show deposits respond systematically to rates. The testable hypothesis for a
**tradable, systematic** signal: aggregate deposit contraction (outflow intensity)
leads a rise in regional-bank equity volatility. If true, aggregate deposit flow is a
usable conditioning variable for regional-bank RV. This experiment tests that
time-series proposition directly and finds no robust support.

## 3. Data

| Component | Source | Detail |
|---|---|---|
| Prices / RV | `yfinance` (`auto_adjust=True`) | KRE + components; daily High/Low/Close |
| Deposits | FRED `DPSACBW027SBOG` via `api.stlouisfed.org` REST | Deposits, All Commercial Banks, weekly, SA (703 obs from 2013) |

- **Period:** 2015-01-01 → 2026-07-03. **2,891 trading days** in-window (well above the
  ≥500 sample-size floor); OOS evaluation origins = **1,155**.
- **Primary target:** KRE (single ETF series — clean, no cross-asset pooling issue).
- **Component basket:** ZION, KEY, RF, FITB, HBAN, MTB, WAL (7 stocks). `CMA` (Comerica)
  is excluded — it persistently returns HTTP 404 under the installed `yfinance` version
  (symbol-resolution failure, logged via `diagnostics.warn`, not fabricated around).
- **RV proxy:** **Parkinson (1980)** daily variance from the high-low range,
  `RV_t = (1/(4 ln 2)) · (ln(High_t/Low_t))²`. Chosen over squared close-to-close return
  because the range estimator is ~5× more efficient and less noisy for daily RV. (The
  Parkinson ratio `ln(H/L)` is invariant to split/dividend adjustment.)

## 4. Method

- **Target:** forward H-day **average** RV, `y_t = mean(RV_{t+1..t+H})`, **H = 5**
  (weekly), computed as `rv.rolling(H).mean().shift(-H)`. The target is strictly over
  `(t, t+H]`.
- **Baseline — HAR-RV** (Corsi 2009): `y_t ~ RV_d(t) + RV_w(t) + RV_m(t)`, where
  `RV_d = RV_t`, `RV_w = mean(RV_{t-4..t})`, `RV_m = mean(RV_{t-21..t})`.
- **Augmented — HAR-RV + deposit-flightiness (lagged):** baseline plus one term,
  `dep_flight`.
- **Deposit-flightiness state variable:** `dep_flight = −z(weekly log deposit growth,
  rolling trailing 52-week window)`. High value = deposits contracting relative to
  recent norm (outflow stress). The z-score uses **only trailing** data. The signal
  correctly spikes to **+2.75 on 2023-03-24**, right after the SVB collapse.

### Lookahead defence (highest-priority risk)

1. **Information-set timing:** all predictors are known at the **close of day t** (`F_t`);
   the target is realized strictly over the **future** window `(t, t+H]`. There is no
   contemporaneous feature/target overlap. Signal at t → target at t+1..t+H.
2. **Deposit publication lag:** each weekly deposit observation is made available only at
   `observation_date + 9 calendar days` (H.8 publishes prior-Wednesday data the following
   Friday; +9d is a conservative buffer). The daily merge is `merge_asof(direction=
   "backward")`, so trading day t only ever sees a deposit value already public by t.
3. **Forward-label embargo in OOS:** the expanding refit at origin `i` trains only on
   rows `j ≤ i − H − 1`, i.e. every training row's label window ends **before** the
   forecast origin (`j + H < i`). This purges the overlap between the training labels and
   the forecast target. The baseline and augmented models use **identical** timing and
   embargo — the *only* difference is the presence of the `dep_flight` column.
4. **DM horizon = H:** the Diebold-Mariano test uses `h = 5`, matching the target horizon
   (Newey-West HAC bandwidth scales with h). The moving-block bootstrap uses block length
   10 (≥ H) so the overlap-induced autocorrelation is preserved within blocks.

### OOS scheme

Expanding window, **refit every step** (HAR-OLS is cheap), initial train = 60% of the
sample, one-step-ahead forecast at each of 1,155 origins with the H-embargo above.

### Evaluation and tests

- **QLIKE** (canonical, `actual/pred − log(actual/pred) − 1`, imported from
  `volpred.stats.model_evaluation.qlike_pointwise` — not hand-written) + **MSE**.
- **Diebold-Mariano** with Newey-West HAC at h = 5 (`dm_test`); negative t ⇒ augmented
  better. Harvey (2016) multiple-testing bar |t| > 3.0.
- **Moving-block bootstrap** (block 10, 2,000 reps, seed 42) on the loss differential,
  as a second overlap-robust check.
- Predictions floored at a tiny positive value for QLIKE positivity — **0 predictions
  were floored** in either model, so the floor does not affect any number.
- **Component basket (robustness):** per `.claude/rules/experiments.md`, cross-asset
  loss differentials are **aggregated by date first** (mean across available stocks per
  day), then DM/HAC is run on the date series — asset-days are **never** treated as iid.
- **Seed = 42** for every stochastic step.

## 5. Results

### Primary — KRE (single ETF), 1,155 OOS origins

| Metric | Baseline HAR-RV | HAR-RV + deposit-flight | Δ |
|---|---|---|---|
| QLIKE | 0.20181 | 0.20138 | −0.21% (better, negligible) |
| MSE | 7.170e-08 | 7.164e-08 | −0.09% |
| **DM t (h=5)** | — | — | **−0.382** |
| **DM p-value** | — | — | **0.703** |
| Block-bootstrap z / p | — | — | −0.39 / **0.695** |
| Bootstrap 95% CI (mean loss diff) | — | — | [−0.00274, +0.00157] (straddles 0) |
| Predictions floored | 0 | 0 | — |

In-sample descriptive diagnostic (full sample, Newey-West lag 10): `dep_flight`
coefficient = −7.6e-06, **NW t = −1.21** (not significant, and the sign is *negative* —
higher flightiness weakly associates with *lower* future RV, opposite to the
hypothesis). Unconditional corr(`dep_flight_t`, forward y) = **−0.109**.

**The tiny 0.21% QLIKE "improvement" is statistical noise** (DM p = 0.70, bootstrap
CI straddles zero). Deposit-flightiness carries no robust incremental signal for KRE.

### Robustness — 7-stock component basket (date-aggregated)

Cross-asset mean loss differential per date, then DM/HAC (h=5): **DM t = 1.44,
p = 0.149** (bootstrap p = 0.150). The sign is now mildly *positive* (augmented slightly
*worse*), still insignificant. Per-stock OOS QLIKE (base → aug):

| Stock | QLIKE base | QLIKE aug | mean loss diff (aug−base) |
|---|---|---|---|
| ZION | 0.4724 | 0.4704 | −0.00197 |
| KEY | 0.2539 | 0.2584 | +0.00452 |
| RF | 0.3229 | 0.3200 | −0.00292 |
| FITB | 0.2287 | 0.2293 | +0.00059 |
| HBAN | 0.2177 | 0.2176 | −0.00006 |
| MTB | 0.2148 | 0.2146 | −0.00021 |
| WAL | 41.63 | 41.67 | +0.03612 |

**Note on WAL:** Western Alliance is a high-QLIKE **outlier** (≈41.6 vs ≈0.2 for the
others) because its idiosyncratic March-2023 near-collapse produced extreme RV that any
HAR massively under-predicts, inflating QLIKE. WAL therefore dominates the equal-weighted
date aggregate. The aggregate DM is insignificant **with or without** WAL (the remaining
six stocks' mean loss diff is marginally negative but nowhere near significant), so the
null conclusion is robust to this outlier — but the equal-weighted cross-asset average
should be read with WAL's dominance in mind.

### Figures (real matplotlib PNGs)

- `k1606_fig_state_vs_rv.png` — deposit-flightiness state variable vs KRE annualized
  realized vol, 2015–2026, with the March-2023 SVB window shaded. Shows the state
  variable and RV both spike around SVB but do **not** co-move systematically elsewhere.
- `k1606_fig_oos_compare.png` — (left) OOS QLIKE base vs augmented bar; (right)
  cumulative QLIKE gain of the augmented model over time (hovers around zero — no
  persistent edge), annotated with the DM statistic.

## 6. Conclusion (honest, evidence-bounded)

For the **time-series reframe tested here**, an aggregate deposit-flightiness state
variable provides **no robust incremental out-of-sample predictive power** over HAR-RV
for regional-bank realized volatility: KRE DM p = 0.70, component basket p = 0.15, both
far from the |t| > 3 Harvey bar and even from |t| > 1.96. The one salient co-movement —
the March-2023 SVB episode, where the state variable correctly spikes — is a **single
regime event**, not a systematic, exploitable lead-lag relationship over 2015–2026.

**Interpretation:** by the time aggregate H.8 deposit data is public (and after the
publication-lag embargo), the information is already impounded in prices; HAR-RV's own
autoregressive structure already captures the volatility clustering around deposit-stress
episodes. A slow, economy-wide, weekly deposit aggregate does not add forecasting content
to a daily RV model.

## 7. Limitations

- **Reframe, not the original claim.** This is a systematic time-series test; it says
  nothing about the *cross-sectional* uninsured-deposit-share hypothesis, which needs
  bank-level FFIEC data unavailable here.
- **Aggregate signal.** DPSACBW027SBOG is total-system deposits, not deposits *at
  regional banks*; a regional-bank-specific or uninsured-only deposit series (if
  obtainable) could carry different content. This is the natural follow-up if bank-level
  or call-report data becomes available.
- **Single RV proxy / horizon.** Parkinson RV at H = 5. Squared-return RV or other
  horizons were not swept (the null is already clear at the primary spec).
- **WAL outlier** in the equal-weighted component aggregate (see §5).

## 8. Reproduce

```bash
uv run python experiments/k1606/k1606.py
```

Deterministic given `seed = 42`; requires `FRED_API_KEY` in `.env.local` and live
`yfinance` access. Outputs `k1606_results.json` + two PNGs. All numbers in this README
come from that live run; nothing is hand-entered.

## 9. Files

- `k1606.py` — full reproducible script.
- `k1606_results.json` — all statistics (QLIKE, MSE, DM stat/p, bootstrap, in-sample
  diagnostic, per-stock component results, data sources, seed, period).
- `k1606_fig_state_vs_rv.png`, `k1606_fig_oos_compare.png` — figures.
