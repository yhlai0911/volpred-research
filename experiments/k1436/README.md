# K1436: BTC perpetual funding rate as a HAR-RV covariate

**Verdict: NULL** — the funding rate is a statistically solid *in-sample* predictor of
next-day BTC realized variance (HAC t = 4.18), but it does **not** buy a defensible
out-of-sample forecast improvement over a plain HAR-RV baseline. Under the
nested-model-valid Clark-West test the pre-specified primary covariate gives
CW = 1.40 (one-sided p = 0.080), short of the 5% bar. The secondary |funding| variant
reaches CW = 1.74 (p = 0.041) — nominally significant, but it fails the two-test
Bonferroni bar of 0.025 and its edge is confined to the first half of the OOS window.
Reported as a lead worth following, not as a result.

---

## 1. Motivation

The repo's own BTC line has been circling this question for a while:

- **K136** confirmed BTC volatility is *leverage-crowding-conditioned* — regime-dependent
  gamma, volume-conditioned leverage effect, weekend vol at 69% of weekday. But its
  GARCH-X out-of-sample tests were **all null**. K136 only had *proxies* for leverage
  (volume, weekend dummies).
- **K139**'s liquidation ABM reproduced 6/7 of those stylized facts from a mechanism of
  leveraged position accumulation → forced liquidation. Its one failure was the
  volume-conditioned gamma, which the write-up attributed to needing *position-level data*.
- The knowledge base note attached to that line says plainly that genuine improvement
  "likely needs Binance funding/OI/liquidation data."

**Funding rate is that missing instrument.** On a perpetual swap, funding is the price
longs pay shorts (or vice versa) to hold the contract — it is a direct, market-clearing
readout of leveraged positioning imbalance, not a proxy for it. So the question this
experiment answers is narrow and fair: *given the right instrument instead of a proxy,
does the leverage-crowding mechanism actually forecast volatility?*

## 2. What's different from prior K's

| Prior | What it did | Why this isn't a repeat |
|---|---|---|
| **K1415** | log(VIX9D/VIX) short-end IV term-structure ratio → HAR-RV, SPY, CONDITIONAL_PASS (QLIKE +6.56%) | Same *framework*, different asset class and different signal family: K1415 uses an **implied**, forward-looking equity signal; K1436 uses a **realized** crypto leverage signal. K1415 also used a daily r²×252 RV proxy — K1436 uses true 5-min RV. |
| **K136** | BTC derivatives-conditioned vol via volume / weekend / VIX proxies | K136's leverage measure was a proxy; funding rate is the direct observable. K136's OOS was null — this tests whether that null survives a better instrument. |
| **K139** | Liquidation ABM (simulation) | K139 is theoretical; this is the empirical test of its mechanism. |
| **K1436 v1** | Feasibility audit only | v1 was `BLOCKED_DATA_UNAVAILABLE`. See §3. |

> Note on the dispatch brief: the brief cited "K1431 (VIX9D−VIX implied spread)" as the
> differentiation target. No entry under that ID exists in `knowledge.json`. The nearest
> real match is **K1415**, used above. Flagging rather than silently substituting.

## 3. Why v1 was BLOCKED, and what changed

The 2026-06-09 first pass ran a feasibility audit and correctly returned
**`BLOCKED_DATA_UNAVAILABLE`** (preserved verbatim as `v1_feasibility_audit.py` /
`v1_feasibility_audit_results.json`). It found two hard data gaps:

1. no canonical Binance perpetual funding-rate series anywhere in the repo (0 files)
2. no BTC intraday cache — only daily OHLCV — so no way to build a real HAR-RV target

v1 was right to stop there. The honest fix was not a daily-range proxy dressed up as
intraday RV; it was to go get the data. **v2 does exactly that** — both endpoints turned
out to be publicly reachable with no key:

| Series | Endpoint | Rows | Period |
|---|---|---|---|
| Funding rate (8h) | `GET fapi.binance.com/fapi/v1/fundingRate` | 7,180 | 2020-01-01 → 2026-07-21 |
| 5-min klines | `GET fapi.binance.com/fapi/v1/klines` | 689,225 | 2020-01-01 → 2026-07-21 |

Fetched 2026-07-21T03:17Z by `fetch_data.py`; provenance (endpoint, fetch time, row
counts, period) recorded in `data/fetch_provenance.json` and mirrored into
`k1436_results.json.data_provenance`. Both CSVs are committed, so the experiment is
reproducible without re-hitting the network.

## 4. Data construction

**RV target.** Daily realized variance = sum of squared 5-minute log returns within a
**UTC calendar day**. BTCUSDT perpetual trades 24/7, so there is no session gap and the
first bar of each day is a genuine 5-minute return. Days with fewer than 250 of the 288
possible bars are dropped as exchange-outage days — **1 day** was dropped out of 2,394;
median coverage is 288/288. Final target: **2,393 days**, 2020-01-01 → 2026-07-20.

**Funding covariate.** Binance settles funding every 8h at 00:00 / 08:00 / 16:00 UTC.
Daily funding = mean of a day's three settlements; days without all three are dropped
(1 day). Descriptives over 7,180 settlements: mean 1.09 bp, sd 2.11 bp, range
[−30 bp, +30 bp], **85.7% positive** (longs pay shorts — the structural contango of a
bull-biased retail perpetual market).

## 5. Lookahead protection — where it lives

This is the highest-risk failure mode for this design, so it is defended twice.

**Layer 1 — explicit lags in the feature builders:**

| Line | Code | Guards |
|---|---|---|
| `k1436.py:131` | `df["har_d"] = log_rv.shift(1)` | daily HAR lag |
| `k1436.py:132` | `df["har_w"] = log_rv.rolling(5).mean().shift(1)` | weekly HAR lag |
| `k1436.py:133` | `df["har_m"] = log_rv.rolling(22).mean().shift(1)` | monthly HAR lag |
| `k1436.py:141` | `out["funding_lag1"] = out["funding"].shift(1)` | **primary covariate** |
| `k1436.py:142` | `out["abs_funding_lag1"] = out["abs_funding"].shift(1)` | secondary covariate |
| `k1436.py:212` | `y_tr, X_tr = y_all[lo:i], X_all[lo:i]` | training rows end strictly before the forecast day |

**Layer 2 — independent re-derivation (`assert_no_lookahead`, `k1436.py:146`).** Rather
than trusting those `.shift()` calls, this samples 250 rows, rebuilds what each predictor
*should* contain using only dates `< t` drawn straight from the raw series, and raises
`AssertionError` on any mismatch. It passes on all 250 rows; the check and its counts are
recorded in `k1436_results.json.lookahead_check`.

**Timing margin.** Day *t*'s funding bucket spans settlements from *t−1* 16:00Z through
*t* 16:00Z. After the `shift(1)`, forecasting RV on day *t* uses the day *t−1* bucket,
whose **last** settlement is at *t−2* 16:00Z — a full 32-hour margin before day *t* opens.
The design is conservative rather than marginal on timing.

**Baseline parity.** Baseline and both alternatives share one panel, one lag convention,
one rolling window, one refit schedule, and one OOS index (`common`, the intersection of
all three forecast series). The only difference between models is the added column.

## 6. Method

- **Baseline**: HAR-RV (Corsi 2009) on log RV, lags d / w(5) / m(22).
- **Alternative**: baseline + `funding_lag1` (primary) or + `abs_funding_lag1` (secondary).
- **Log space + smearing**: models are estimated on log RV and mapped back to the variance
  scale with `exp(μ̂ + s²/2)`, `s²` the in-window residual variance. Both models get the
  identical transform, so it cannot tilt the comparison.
- **OOS**: rolling window W = 1000, refit **daily**, 1-step-ahead, 2024-01-01 → 2026-07-20,
  **n = 932**.
- **Loss**: QLIKE (canonical direction `actual/pred − log(actual/pred) − 1`, via
  `volpred.stats.model_evaluation.qlike_pointwise`) and MSE.
- **Inference — and a correction the first draft of this experiment got wrong.**
  The baseline is the alternative with `β_funding = 0`, so the two models are **nested**.
  Under a nested null an ordinary Diebold-Mariano statistic is *not* valid inference: the
  loss differential degenerates, and DM is biased *against* the larger model because that
  model carries estimation noise which vanishes under H₀. The first version of this
  experiment used raw DM as the primary test; the repo's `nested-dm-misuse` gate caught it.

  So **Clark-West (2007) MSPE-adjusted is the only test wired into the verdict**:

  ```
  f_t = (y − ŷ_restricted)² − [(y − ŷ_unrestricted)² − (ŷ_restricted − ŷ_unrestricted)²]
  ```

  one-sided against H₀ "HAR-RV baseline is adequate", Newey-West HAC at the repo's
  canonical bandwidth `ceil(h^{1/3}·n^{1/3})` = 10, standard-normal reference.
  Ordinary DM / HLN statistics are still computed and reported, but are explicitly
  **diagnostic-only** and never touch the verdict.
- **Multiplicity**: two covariates tested → Bonferroni one-sided bar 0.05/2 = **0.025**.
  The headline verdict follows the **pre-specified primary** covariate (signed funding);
  promoting the secondary because it happened to score better is exactly the selection
  this correction exists to prevent.
- **Seed**: 42 (`np.random.seed` + the `assert_no_lookahead` sampler's `default_rng`).
  Nothing else in the pipeline is stochastic — estimation is closed-form OLS.

## 7. Results

### 7.1 Out-of-sample (n = 932, 2024-01-01 → 2026-07-20)

| Model | QLIKE | Δ% | MSE | Δ% |
|---|---|---|---|---|
| HAR-RV (baseline) | 0.285709 | — | 6.3957e-07 | — |
| HAR-RV + funding | 0.283634 | **−0.73%** | 6.3691e-07 | −0.42% |
| HAR-RV + \|funding\| | 0.283144 | **−0.90%** | 6.3548e-07 | −0.64% |

Both alternatives improve QLIKE by under 1%. For scale, K1415's accepted equity result
moved QLIKE by 6.56%.

### 7.2 Clark-West — the actual inference (positive stat = funding model better)

| Covariate | CW stat | one-sided p | < 0.05? | < 0.025 (Bonferroni)? |
|---|---|---|---|---|
| signed funding (**primary**) | 1.402 | 0.080 | ❌ | ❌ |
| \|funding\| (secondary) | 1.739 | **0.041** | ✅ | ❌ |

The pre-specified primary covariate **does not clear the 5% bar**. The secondary
|funding| variant clears the nominal bar but **not** the two-test Bonferroni bar of
0.025 — and §7.4 shows its edge is not stable across the OOS window. Neither result
supports a claim that funding improves BTC volatility forecasts.

### 7.3 Ordinary DM — diagnostic only, and why it disagrees

| Comparison | Loss | DM t | p | HLN-corrected t |
|---|---|---|---|---|
| +funding vs baseline | QLIKE | −0.829 | 0.407 | −0.829 |
| +funding vs baseline | MSE | −0.638 | 0.523 | −0.638 |
| +\|funding\| vs baseline | QLIKE | −0.917 | 0.359 | −0.917 |

**These are not inference and are not in the verdict** — they are reported because prior
non-nested K's in this repo quote DM, and dropping them silently would make this
experiment look incomparable.

The disagreement is itself the interesting part. DM says p ≈ 0.36-0.41; Clark-West says
p ≈ 0.04-0.08 on the same forecasts. That gap is the textbook nested-model bias: DM
penalises the larger model for estimation noise that is zero under the null, so it
under-rejects. **Had this experiment shipped its first draft, it would have reported a
"clean, far-from-significant null" that was partly an artifact of the wrong test.** The
conclusion still lands on NULL, but for properly-earned reasons rather than lucky ones.

HAC bandwidth is not doing any work in either test: loss-differential acf(1) = 0.035
(essentially uncorrelated), and DM t ranges only −0.89 → −0.83 across bandwidths
{1, 5, 10, 22, 44}.

### 7.4 Coefficient — significant in-sample

| Spec | β (funding, lag-1) | HAC se | t | p | n |
|---|---|---|---|---|---|
| Full sample | 342.84 | 81.99 | **4.18** | 2.9e-05 | 2,371 |
| Pre-2024 only | 267.41 | 75.38 | **3.55** | 3.9e-04 | 1,439 |
| \|funding\|, full sample | 411.75 | 88.28 | **4.66** | 3.1e-06 | 2,371 |

**Both things are true and both are reported.** β is positive, sizeable, HAC-significant,
and stable in sign and order of magnitude across the pre-2024 subsample — higher funding
(more crowded longs) genuinely does precede higher realized variance. Economically, a 1-sd
funding move (1.96 bp/8h) raises expected next-day RV by **+6.9%**, i.e. about **+3.4%** on
the volatility scale. That is a real but modest effect, and HAR's own lags already capture
almost everything it would contribute: full-sample R² rises only from **0.53046** (baseline)
to **0.53419** (+funding) — an incremental R² of **+0.00372**, i.e. roughly a third of one
percent of the variance of log RV. (|funding| adds +0.00463.) All three fits use the
identical panel; see `k1436_results.json.incremental_r2`.

**In-sample significance did not convert into out-of-sample skill.** That gap *is* the
result.

### 7.5 OOS split-half — the small edge isn't stable

| Half | Period | n | QLIKE base | QLIKE +funding | **CW stat** | **CW p** |
|---|---|---|---|---|---|---|
| First | 2024-01-01 → 2025-04-10 | 466 | 0.29801 | 0.29376 | 1.605 | 0.054 |
| Second | 2025-04-11 → 2026-07-20 | 466 | 0.27341 | 0.27351 | **0.363** | 0.358 |

The entire improvement comes from the first half and is essentially *zero* in the second
(CW 1.61 → 0.36; QLIKE actually a hair worse). This is the signature of a marginal
relationship leaking a little signal in one regime, not a durable forecasting edge — and
it is the main reason the marginal full-sample |funding| result should not be read as
"nearly significant, therefore probably real."

## 8. Conclusion

BTC perpetual funding rate is a **genuine in-sample correlate** of next-day realized
variance (HAC t = 4.18, +6.9% RV per 1-sd), but it does **not** deliver a defensible
out-of-sample forecasting gain over HAR-RV. Under the nested-valid Clark-West test the
pre-specified primary covariate lands at p = 0.080, and the secondary |funding| variant's
p = 0.041 fails the two-test Bonferroni bar and collapses in the second half of the OOS
window (CW 1.61 → 0.36). **Verdict: NULL**, with |funding| logged as a lead worth a
properly pre-registered follow-up rather than a finding.

This **extends K136's null rather than overturning it**. K136 found the leverage-crowding
mechanism real but OOS-unforecastable using *proxies* (volume, weekend dummies); the
natural next hypothesis was that the proxies were the problem. They were not. Handed the
direct instrument — the actual price of leverage rather than a stand-in for it — the OOS
null holds. The economically interesting reading is that HAR's own volatility lags already
embed nearly all of the positioning information funding carries: incremental R² is
+0.0037. That is the crypto counterpart of the "VIX sufficiency" pattern this repo has now
hit roughly 26 times in equities — the market's own realized history is a sufficient
statistic for most of what the derivatives complex knows.

**Methodological note worth carrying forward.** The nested-model correction was not
cosmetic here. Raw DM put these comparisons at p ≈ 0.36-0.41; Clark-West puts the same
forecasts at p ≈ 0.04-0.08. Every future HAR-plus-a-covariate experiment in this repo is
nested by construction, so any of them that quoted raw DM as inference will have been
systematically *under*-rejecting — biased toward declaring null results. That direction of
bias is comfortable and therefore easy not to notice.

## 9. Limitations

1. **Single exchange.** Binance only. It is the largest BTC perp venue, but funding on
   OKX/Bybit/dYdX can diverge, and a cross-venue funding dispersion measure is untested here.
2. **Single contract.** BTCUSDT perpetual only — no quarterly-futures basis, no options
   skew, no OI or liquidation data. A composite leverage measure may still work where
   funding alone does not.
3. **Short sample by volatility-research standards.** 2,393 days (2020-2026), OOS n = 932.
   The sample contains the 2021 bull, the 2022 bear/LUNA-FTX deleveraging, and the 2024-25
   ETF era, so it is regime-diverse — but it is one asset over six years, and DM power at
   n = 932 is limited for small effects.
4. **Funding regime shift.** Binance changed funding-interval and cap rules over the
   sample; the series is treated as homogeneous, which it is not strictly.
5. **Linear specification.** Funding enters linearly. The K139 liquidation mechanism is
   explicitly non-linear (cascades trigger at thresholds), so a threshold/quantile spec is
   a live untested alternative — the |funding| variant is only a crude first step toward it.
6. **Two covariates tested, and the secondary is the one that scored better.** Signed
   funding was the pre-specified primary; |funding| was pre-specified as secondary on the
   K139 cascade mechanism. |funding| clearing the nominal 5% bar while the primary does not
   is exactly the configuration where selective reporting does its damage, which is why the
   Bonferroni bar (0.025) is applied and the headline follows the primary. A clean test of
   |funding| needs a fresh pre-registration and an OOS window this experiment has not
   already looked at.
7. **CW is one-sided and asymptotic.** Clark-West's normal reference is an approximation;
   Clark & West themselves note it is somewhat conservative in finite samples. At n = 932
   with effects this small, neither a bootstrap CW nor the normal approximation would be
   decisive — the honest statement is that this design lacks the power to resolve an effect
   of this magnitude, not that the effect is zero.
8. **Row-position vs calendar-date lagging.** `panel`'s rows are RV days, and one RV day
   (low bar coverage) plus one funding day (incomplete settlements) are dropped. So at
   those two boundaries `.shift(1)` means "last available prior row" rather than literally
   "yesterday". This is *not* a lookahead violation — it still only reads strictly earlier
   data, and `assert_no_lookahead` verifies exactly that — but it is a real alignment
   nuance affecting at most 2 of 2,393 days. Immaterial here; would matter on a series
   with substantial missingness.
9. **RV target choice.** 5-min sampling with no sub-sampling/averaging and no
   microstructure-noise correction (no realized kernel, no bipower variation). Standard for
   a liquid perp, but not the most robust estimator available.

## 10. Files

| File | Role |
|---|---|
| `fetch_data.py` | Stage 1: materializes both series from Binance, writes provenance |
| `k1436.py` | Stage 2: RV construction, lookahead checks, rolling OOS, DM tests, figures |
| `k1436_results.json` | Result artifact |
| `reproduce_spec.json` | Reproduction spec |
| `data/btc_funding_rate_8h.csv` | 7,180 funding settlements |
| `data/btcusdt_5m.csv` | 689,225 5-min bars |
| `data/fetch_provenance.json` | Endpoint / fetch-time / row-count provenance |
| `fig_rv_vs_funding.png` | RV series with funding rate overlaid |
| `fig_oos_comparison.png` | Cumulative QLIKE differential + OOS QLIKE bars |
| `v1_feasibility_audit.py` / `v1_feasibility_audit_results.json` | Preserved v1 BLOCKED audit |

Reproduce: `uv run --active python experiments/k1436/k1436.py`
(uses committed CSVs; re-fetching is only needed to extend the sample).

## 11. References

- Corsi, F. (2009). A Simple Approximate Long-Memory Model of Realized Volatility. *JFEC* 7(2).
- Patton, A. (2011). Volatility Forecast Comparison Using Imperfect Volatility Proxies. *JoE* 160(1).
- Diebold, F. & Mariano, R. (1995). Comparing Predictive Accuracy. *JBES* 13(3).
- Harvey, D., Leybourne, S. & Newbold, P. (1997). Testing the Equality of Prediction Mean Squared Errors. *IJF* 13(2).
- Harvey, C. (2016). Editorial: The Scientific Outlook in Financial Economics. *JF* 72(4).
- Internal: K136 (BTC leverage-crowding), K139 (liquidation ABM), K1415 (IV term-structure ratio → HAR-RV).
