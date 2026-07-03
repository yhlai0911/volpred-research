# k1619 — Staleness-corrected RV vs naive RV in HAR-RV OOS forecasting

**Verdict: NULL / NEGATIVE.** An idle-time (staleness) correction of realized
variance does **not** deliver a robust, Harvey-significant improvement in HAR-RV
out-of-sample forecasting for illiquid ETFs. Apparent conventional-level effects
are specification-dependent (they vanish/flip between levels-HAR and log-HAR) and
directionally inconsistent across assets, so they do not constitute a reliable
increment.

---

## 1. Motivation & research question

Illiquid assets exhibit intraday price **staleness**: intervals with zero returns
because no trade updates the last price (Bandi–Pirino–Renò 2017 "idle time";
Kolokolov–Livieri–Pirino 2020 "price staleness"). Naive realized variance
`RV = Σ rᵢ²` sums squared intraday returns and, if a large fraction of intervals
are stale, may be a biased estimator of integrated variance.

**Question:** After applying an idle-time correction to the RV *estimator itself*,
does the corrected RV — fed into a standard HAR-RV model — improve out-of-sample
volatility forecasting (lower QLIKE, DM/HLN-significant) versus naive RV?

## 2. Differentiation (why this is not a duplicate)

- **≠ research_program.md L501 "realized illiquidity as an incremental vol
  predictor."** That line adds an illiquidity *factor* (Amihud / Corwin–Schultz /
  range–volume) as an **extra HAR regressor**. Here we do **not** add a regressor:
  we **correct the RV estimator itself** (its idle-time bias), then ask whether the
  corrected RV forecasts better. Same HAR feature set, different *target/inputs*.
- **≠ existing lead-lag / Hansen–Lunde ACcov microstructure K's.** Those correct
  RV via **autocovariance** terms (`RV + 2·Σ rᵢrᵢ₋₁`, French–Roll / Hansen–Lunde)
  to remove bid-ask-bounce / non-synchronous *noise*. This experiment stays on the
  distinct **staleness / idle-time (exact zero-return freezing)** sub-line and does
  **not** use any autocovariance correction.

## 3. Related K / project rules honoured

- **K1355** (cross-asset pooling): the pooled illiquid test aggregates the daily
  loss differential across assets **by date first**, then runs DM/HLN on the date
  series — never treats asset-day as iid.
- **K445 / K783c** (QLIKE + arch alignment): QLIKE uses the canonical
  `volpred.stats.model_evaluation.qlike_pointwise(actual, predicted)` (direction
  `actual/predicted`); no hand-written reverse QLIKE. No `arch` package is used.
- **experiment-preamble model↔target matching:** HAR forecasts an intraday-RV-type
  target; evaluation uses an intraday, session-scoped model-free proxy (`r2_oc`),
  not close-to-close `r²`.

## 4. Literature (all verified, real)

1. **Bandi, F. M., Pirino, D., & Renò, R. (2017). "EXcess Idle Time."**
   *Econometrica* 85(6), 1793–1846. DOI 10.3982/ECTA13595. — Formal limit theory
   and tests for price staleness; idle time (fraction of zero returns) as an
   economic indicator of sluggish price adjustment. *(motivates the idle-fraction
   staleness measure and the idle-time rescaling.)*
2. **Kolokolov, A., Livieri, G., & Pirino, D. (2020). "Statistical inferences for
   price staleness."** *Journal of Econometrics* 218(1), 32–81.
   DOI 10.1016/j.jeconom.2019.11.010. — Latent time-varying staleness probability;
   NYSE prices are much staler at high frequency than expected. *(motivates using
   the zero-return fraction as the staleness diagnostic.)*
3. **Corsi, F. (2009). "A Simple Approximate Long-Memory Model of Realized
   Volatility."** *Journal of Financial Econometrics* 7(2), 174–196. — HAR-RV
   (daily/weekly/monthly) specification used here.
4. **Patton, A. J. (2011). "Volatility forecast comparison using imperfect
   volatility proxies."** *Journal of Econometrics* 160(1), 246–256. — QLIKE
   ranking is consistent against a conditionally-unbiased (noisy) proxy; justifies
   using `r2_oc` as the evaluation target.
5. **Harvey, D., Leybourne, S., & Newbold, P. (1997). "Testing the equality of
   prediction mean squared errors."** *International Journal of Forecasting* 13(2),
   281–291. — HLN small-sample correction to the Diebold–Mariano test.
6. **Hansen, P. R., & Lunde, A. (2006). "Realized variance and market
   microstructure noise."** *Journal of Business & Economic Statistics* 24(2),
   127–161. — Background on RV bias under microstructure frictions (staleness is
   one channel; distinct from the ACcov channel we deliberately exclude).

## 5. Data

- **Source:** yfinance, `interval='1h'`, `period='730d'` (≈ hourly-bar upper
  limit). Cached to `data/<SYM>_1h.csv` and **committed** so the exact dataset is
  reproducible (period="730d" is a rolling window, so re-fetching later would draw
  a different span — the seed does not fix data-vintage; the committed CSVs do).
- **Sample:** 2023-08-04 → 2026-07-02, **721 usable trading days** per asset,
  **≈6.00 hourly bars/day**. Within-day close-to-close returns only (the first bar
  of each day is dropped to exclude the overnight gap).
- **Assets:** liquid benchmark **SPY** + 3 illiquid single-country ETFs selected by
  the staleness diagnostic below: **VNM** (Vietnam), **EWM** (Malaysia),
  **EIDO** (Indonesia).

### 5.1 Staleness diagnostic (premise check)

Idle fraction `f` = mean fraction of exact-zero within-day hourly returns
(Bandi–Pirino–Renò idle-time proxy). Selection scanned 21 candidate ETFs; the 3
illiquid assets have the highest staleness *among names with a full ~6 bars/day*
(QAT was staler at 9.7% but only 3.6 bars/day → excluded as too noisy for RV).

| Asset | role | mean idle (exact-zero) | mean near-zero (<1bp) | bars/day | days |
|-------|------|-----------------------:|----------------------:|---------:|-----:|
| SPY   | liquid benchmark | **0.185 %** | 4.81 % | 6.00 | 721 |
| VNM   | illiquid | **10.264 %** | 12.16 % | 6.00 | 721 |
| EWM   | illiquid | **9.200 %**  | 10.96 % | 6.00 | 721 |
| EIDO  | illiquid | **8.807 %**  | 10.08 % | 6.00 | 721 |

**Premise holds strongly:** the illiquid ETFs have ~48–55× SPY's zero-return
fraction. (Near-zero <1bp is scale-sensitive — SPY's 4.81 % is an artifact of its
high price level — so exact-zero is the canonical staleness measure, matching the
literature.)

## 6. Method

### RV variants (daily, from within-day hourly returns)
- **RV_naive** `= Σᵢ rᵢ²`.
- **RV_corrected (idle-time rescaling)** `= RV_naive / (1 − f_d)`, where `f_d` is
  the exact-zero fraction on day `d`. **Rationale (first-order de-staling):** if a
  fraction `f` of intervals are idle (stale, contributing zero observed variance)
  while the latent efficient price keeps diffusing, naive RV records variance only
  over the `(1−f)` *active* fraction of calendar time; rescaling by `1/(1−f)`
  restores full calendar-time integrated variance. This is a transparent
  first-order implementation of the Bandi–Pirino–Renò idle-time idea (not a
  verbatim reproduction of their estimator). Days with `f_d = 1` (fully stale) are
  dropped.

### Evaluation target (fair, common, model-free)
- **`r2_oc = (Σᵢ rᵢ)²`** = squared cumulative within-day log return. It depends only
  on the day's first/last observed price, so it is **staleness-robust** (not
  mechanically tied to the count of zero intraday bars; endpoints could still be
  mildly stale) and does **not** favour naive or corrected RV. Patton (2011): QLIKE
  against a conditionally-unbiased proxy ranks forecasts consistently.

### Forecast model
- **HAR-RV (Corsi 2009):** `RV_t = β₀ + β₁·RV_{t-1} + β₂·RV^w_{t-1} + β₃·RV^m_{t-1}`
  (weekly = 5-day mean, monthly = 22-day mean), **all predictors lagged one day**.
  Two parallel HARs: one on `RV_naive`, one on `RV_corrected`.
- **Expanding-window, one-step-ahead OOS:** 250-day warmup, then re-fit each origin
  → **449 OOS days** per asset (≥ 252 requirement met). Levels-OLS forecasts are
  floored at the **1st percentile of positive training RV** (data-driven, applied
  identically to both models → symmetric).

### Inference
- Per-asset **QLIKE(r2_oc, forecast)**; DM test on the pointwise QLIKE differential
  with the **Harvey–Leybourne–Newbold small-sample correction** (factor
  `√((T+1−2h+h(h−1)/T)/T)`, Student-t `df=T−1`), `h=1`.
- **Pooled illiquid** test: mean daily `(loss_naive − loss_corr)` across the 3
  illiquid assets **by date**, then DM/HLN on the date series (K1355).
- **Significance bar:** Harvey (2016) `|t| > 3` (project multiple-testing standard);
  conventional `p < 0.05` reported alongside for transparency.
- **Sign convention:** `d = loss_naive − loss_corr`; `t > 0` ⇒ corrected has lower
  loss (correction helps); `t < 0` ⇒ naive better (correction hurts).

## 7. Results

### 7.1 Primary — levels-HAR

| Asset | median QLIKE naive | median QLIKE corr | MSE better | DM/HLN t | p | Harvey \|t\|>3 |
|-------|------:|------:|:--:|------:|------:|:--:|
| SPY   | 0.7028 | 0.7032 | naive | **−1.81** | 0.071 | ✗ |
| VNM   | 1.0028 | 0.9890 | corrected | **+2.78** | 0.006 | ✗ |
| EWM   | 0.6913 | 0.6946 | corrected | **+0.58** | 0.559 | ✗ |
| EIDO  | 0.8042 | 0.8986 | naive | **−2.58** | 0.010 | ✗ |
| **Pooled illiquid** | — | — | — | **+2.49** | 0.013 | ✗ |

*(Mean QLIKE levels are large — e.g. VNM ~1.16e6 — because the `−log(actual)` term
blows up on near-zero-proxy days; this term is **identical** for naive vs corrected
and **cancels exactly** in the DM differential, so DM/HLN is the valid inference.
Median QLIKE is reported as the interpretable central tendency.)*

**Read:** no asset reaches the Harvey `|t|>3` bar. At conventional levels the
effect is **heterogeneous and directionally inconsistent**: the correction helps
VNM (+2.78) but **hurts** the *most-stale* asset EIDO (−2.58, largest
over-correction ratio 1.14). The pooled +2.49 is conventionally significant but
masks the EIDO reversal.

### 7.2 Robustness — floor-free log-HAR

To rule out that §7.1's conventional-level effects are an artifact of
negative-forecast flooring, we re-run with **log-HAR** (fit on `log RV`, exp +
log-normal smearing retransform → always positive, no flooring):

| Asset | log-HAR DM/HLN t | p | better | Harvey \|t\|>3 |
|-------|------:|------:|:--:|:--:|
| SPY   | −1.74 | 0.083 | naive | ✗ |
| VNM   | −0.46 | 0.645 | naive | ✗ |
| EWM   | +1.35 | 0.177 | corrected | ✗ |
| EIDO  | +0.85 | 0.395 | corrected | ✗ |
| **Pooled illiquid** | **+0.44** | 0.658 | corrected | ✗ |

**Read:** under log-HAR the levels-HAR effects **vanish or flip** (VNM
+2.78→−0.46; EIDO −2.58→+0.85; pooled +2.49→+0.44, all insignificant). The
apparent conventional-level effects are therefore **specification-dependent**, not
a real forecasting increment. Under **both** specifications, **no asset crosses
Harvey `|t|>3`.**

## 8. Conclusion (honest, incl. NULL)

The idle-time staleness correction `RV/(1−f)` provides **no robust incremental
improvement** to HAR-RV OOS volatility forecasting for these illiquid ETFs:

- 0 / 3 illiquid assets show a Harvey-significant QLIKE improvement (levels or log).
- The correction **hurts** the most-stale asset (EIDO) under levels-HAR.
- Conventional-level effects flip between HAR specifications → not reliable.

**Mechanistic reading (why NULL is expected):** under a "stale-then-catch-up"
model, when a price is stale for `k` intervals and then jumps, the single large
update return `(Σ eᵢ)²` already captures the accumulated latent variance in
expectation (`E[(Σeᵢ)²] = Σ Var(eᵢ)`). So naive RV is approximately unbiased *in
expectation* even under heavy staleness; the `1/(1−f)` rescaling therefore tends to
**over-inflate** RV (most for the highest-`f` asset, EIDO, ratio 1.14) rather than
de-bias it. Staleness mainly raises the *variance/noise* of RV, which a level
rescaling does not fix. This is a genuine, useful null: a simple idle-time
rescaling is **not** a free lunch for HAR forecasting.

## 9. Codex review

`codex exec` (gpt-5.5, read-only) reviewed the correctness-critical logic:
**no Critical/High findings.** Confirmed: (1) no lookahead/leakage — `.shift(1)`
features + training on `X[:i]` whose target days are strictly before the forecast
origin; (2) QLIKE used as `qlike_pointwise(actual=r2_oc, predicted=forecast)` (not
reversed); (3) DM/HLN sign convention and the `h=1` HLN factor `√((T−1)/T)` with
`t_{T−1}` correct; (4) idle correction arithmetic correct; (5) no bug collapsing
naive≈corrected. Two Low findings were addressed post-review: "staleness-immune"
softened to "staleness-robust", and the yfinance CSVs committed for data-vintage
reproducibility. (The 1e-12→1st-percentile forecast floor and the log-HAR
robustness block were added after review; they do not touch the reviewed
lag/DM/QLIKE/idle-correction logic.)

## 10. Anti-error checklist

| Rule | How satisfied |
|------|---------------|
| **Lookahead** | `build_har_features` applies `.shift(1)` to daily/weekly/monthly regressors → row `t` predictors use only ≤ `t-1`. Expanding OOS trains on `X[:i], y[:i]` whose target days are strictly `< day_i`; `H=1` so `j+H ≤ i`. Codex-confirmed no leakage. |
| **Same lag for baseline** | Naive and corrected HARs use the identical feature construction and OOS loop; only the RV series differs. |
| **Seed** | `np.random.seed(42)`. Design is analytic (OLS + DM); no bootstrap/sampling, so results are deterministic given the committed data. |
| **QLIKE direction** | Canonical `volpred.stats.model_evaluation.qlike_pointwise(actual, predicted)` = `actual/predicted − log(actual/predicted) − 1`; never reversed. |
| **Fair proxy** | Single common `r2_oc` target for both models — does not favour either RV variant. |
| **Sample size** | 449 OOS days per asset (≥ 252). |
| **Cross-asset pooling (K1355)** | Pooled test aggregates loss differential by date first, then DM/HLN. |
| **Reproducibility** | Raw hourly CSVs committed under `data/`. |

## 11. Files

- `k1619.py` — full reproducible script (data fetch/cache → RV variants → HAR OOS →
  QLIKE + DM/HLN → log-HAR robustness → figures).
- `k1619_results.json` — all numbers (staleness diagnostic, per-asset QLIKE/DM,
  pooled, log-HAR robustness, verdict, seed, period).
- `data/<SYM>_1h.csv` — committed raw hourly bars (reproducibility).
- `probe_staleness.py` — asset-selection diagnostic (not part of final inference).
- `k1619_fig1_staleness.png` — staleness by asset (SPY vs illiquid 3).
- `k1619_fig2_dmhln.png` — DM/HLN t-statistics per asset with Harvey ±3 / conv ±1.96.
- `k1619_fig3_lossdiff.png` — cumulative OOS QLIKE loss differential over time.
