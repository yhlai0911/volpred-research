# K1600: HARQ-proxy — Low-Frequency Proxy Test of Measurement-Error-Corrected HAR

**Verdict: CONDITIONAL_PASS (honest reading: essentially NULL)**
**Reviewer: Codex CLI — PASS (no result-validity issue)**
**Date: 2026-07-01**

## Research Question

Does a HARQ-type measurement-error correction — letting the HAR daily-lag
coefficient shrink when the realized-variance measurement is noisy — improve
volatility forecasts when the quarticity signal is built from a **low-frequency
(daily-return) proxy** rather than true intraday realized quarticity?

HARQ (Bollerslev, Patton & Quaedvlieg, *Journal of Econometrics* 2016,
"Exploiting the errors: A simple approach for improved volatility forecasting")
augments HAR with intraday realized quarticity (RQ):

```
RV_{t+h} = β0 + (β1 + β1Q·sqrt(RQ_t))·RV_d,t + β2·RV_w,t + β3·RV_m,t + ε
```

When daily RV is measured with large error (high RQ), the daily-lag coefficient
is attenuated (β1Q < 0). This experiment tests the low-frequency proxy analog.

## Honest Data Reality (defining framing — read first)

This is the repo's **first HARQ-type measurement-error experiment** (dup check:
no existing `harq` K; grep of `experiments/` for HARQ/quarticity returned only
unrelated jump/kurtosis experiments — K1520/k1523 realized-kurtosis, K1057,
K851 jump dynamics — none implements the BPQ measurement-error correction).

**True HARQ requires a long-sample intraday RV+RQ panel, which this repo does
not have.** Clean intraday data is only `data/intraday/SPY_5min_*.csv`, ~115
days from 2026-01 — far below the ≥500-sample rigor bar. Credible intraday
HARQ inference is infeasible here.

Following the repo's **honest-proxy convention** (same route as K1520/k1523),
RV and RQ are built from **daily log returns** over a long sample (2010-2026,
OOS n ≈ 3200 per asset, Harvey-significant inference feasible), and we test
whether the HARQ measurement-error correction improves the HAR proxy forecast.

**A daily-return quarticity proxy is a WEAK analog of intraday RQ.** A NULL
result is fully acceptable and a legitimate contribution: if the proxy is too
coarse to carry the measurement-error signal, we report that honestly. **This is
NOT a claim about true intraday HARQ.**

## Differentiation vs Existing K

| K | Topic | Difference |
|---|---|---|
| K1520 / k1523 | Realized **kurtosis** incremental predictor | Standardized 4th moment as an *additive* HAR regressor; K1600 uses quarticity as a *measurement-error interaction* on the daily lag (BPQ mechanism, not additive) |
| K1057 / K851 | Jump dynamics / quarticity for jump tests | Quarticity used for jump detection, not forecast-coefficient time-variation |
| K1473 | HAR vs DL across horizons | Model-class comparison, no measurement-error correction |

K1600 is the repo's first test of the **BPQ measurement-error-correction
mechanism** (coefficient shrinkage driven by RQ), in low-frequency proxy form.

## Data

- **yfinance daily close**, 2010-01-01 → 2026-06-30.
- **Assets** (each estimated & reported **independently — NO pooling**, per
  experiments.md K1355 rule that cross-asset pooled inference must not treat
  asset-days as iid): `SPY`, `QQQ`, `0050.TW`.
- **`0050.TW` cleaned via `volpred.utils.clean_tw50_data`** — fixes the
  2014-01-02 split artifact (fake −75% return) before returns are computed.

## Method

- **RV proxy** (repo convention): `RV_d,t = r_t²` (daily close-to-close squared
  log return). HAR weekly/monthly = trailing 5/22-day means (Corsi 2009).
- **RQ proxy** (BPQ 2016 realized-quarticity estimator form, low-freq analog):
  `RQ_t = (N/3)·Σ r⁴` over a 22-day window, `N = 22`. `sqrt(RQ)` enters the
  HARQ interaction, standardized (feature-only global affine scaling — an OLS
  reparameterization that does not touch the target and does not alter forecast
  rankings; confirmed by Codex).
- **Models** (all OLS on **level RV**, BPQ convention; same lag conventions):
  1. **HAR** (Corsi 2009): `RV_{t+h} = β0 + β1·RV_d + β2·RV_w + β3·RV_m`
  2. **HARQ** (BPQ 2016): `+ β1Q·sqrt(RQ)_std·RV_d` (daily-term interaction)
  3. **HARQ-F** (BPQ 2016 full): measurement-error interaction on d/w/m terms
- **Horizons**: h = 1, 5, 22. Target = forward h-day **average** RV.
- **OOS**: expanding-window refit, `init_train = max(500, 20%)`, step 1.
- **Insanity filter** (BPQ 2016, canonical HARQ practice): level-RV OLS can
  extrapolate a forecast outside the empirical support (e.g. negative RV on a
  crisis day) → QLIKE explodes. Any forecast below the training-window min or
  above its max is reset to the **training-window mean**, applied **identically**
  to HAR/HARQ/HARQ-F using **training-window-only** stats (OOS-clean). Filter
  fires rarely (1–7 of ~3200 OOS obs). See "Bug found & fixed" below.

## Anti-Error Compliance

- **Lookahead / forward-label (experiments.md hard rule)**: for horizon h with
  target window `[t+1, t+h]`, training rows must satisfy `j + h < i`
  (`target_end_pos < forecast_pos`). `rolling_oos` trains on rows `[0, i-h)`
  (drops last h rows before origin); `beta1Q_significance` drops the last h
  rows. **Codex confirmed correct — no off-by-one.**
- **Per-horizon DM (experiments.md hard rule)**: each horizon uses its OWN
  inference horizon; HAC lag = `h-1`; **HLN (Harvey-Leybourne-Newbold 1997)**
  small-sample correction `corr = sqrt((n+1−2h+h(h−1)/n)/n)`, `t(n−1)`
  reference. **Codex confirmed correct.**
- **QLIKE**: canonical `volpred.stats.model_evaluation.qlike_pointwise`
  (`actual/predicted − log(actual/predicted) − 1`) — no inverse-QLIKE (K783c
  lesson). **Codex confirmed correct orientation.**
- **Seed**: `numpy seed = 42` fixed.
- **Honest-proxy framing**: title, results JSON `framing`, and this README all
  state "low-frequency proxy of HARQ", NOT true intraday HARQ.

## Success Criteria

A HARQ improvement "counts" only if **both**: DM-HLN `t < −3.0` (Harvey 2016,
challenger better) **AND** β1Q Harvey-significant (`|t| > 3`) with the
BPQ-expected negative sign. Anything less is honestly reported as
CONDITIONAL/NULL.

## Results (OOS 2010-2026, per asset × horizon)

QLIKE loss ratio = HARQ / HAR (**< 1 = HARQ better; > 1 = HARQ worse**).
DM-HLN `t`: negative = HARQ better. β1Q: BPQ expects negative.

| Asset | h | n_OOS | QLIKE HAR | QLIKE HARQ | Loss ratio | DM-HLN t | p | β1Q | β1Q t |
|---|---|---|---|---|---|---|---|---|---|
| SPY | 1 | 3299 | 1.6337 | 1.7389 | **1.064** | +2.49 | 0.013 | −0.021 | −1.71 |
| SPY | 5 | 3296 | 0.5061 | 0.5625 | **1.112** | +2.83 | 0.005 | −0.039 | −2.41 |
| SPY | 22 | 3282 | 0.4455 | 0.4583 | **1.029** | +0.87 | 0.384 | −0.025 | −1.87 |
| QQQ | 1 | 3299 | 1.6061 | 1.6770 | **1.044** | +1.77 | 0.078 | −0.005 | −0.54 |
| QQQ | 5 | 3296 | 0.4405 | 0.4564 | **1.036** | +1.52 | 0.130 | −0.034 | −2.84 |
| QQQ | 22 | 3282 | 0.3439 | 0.3514 | **1.022** | +1.17 | 0.242 | −0.023 | −2.70 |
| 0050.TW | 1 | 3205 | 2.5791 | 2.5763 | 0.999 | −0.73 | 0.465 | −0.009 | −0.59 |
| 0050.TW | 5 | 3202 | 0.4728 | 0.4737 | 1.002 | +0.27 | 0.787 | −0.014 | −1.42 |
| 0050.TW | 22 | 3188 | 0.2885 | 0.2869 | 0.995 | −0.99 | 0.324 | −0.014 | **−3.11** |

**Aggregate**: 9 cells | DM-HLN Harvey-significant (challenger better): **0/9** |
β1Q Harvey-significant: **1/9** (0050.TW h=22, t=−3.11) | joint support: **0/9**.

(HARQ-F is uniformly worse than HARQ — see `k1600_results.json`; the extra
weekly/monthly measurement-error interactions add noise, not signal, under the
daily proxy.)

## Verdict — Honest Reading

The automated verdict is **CONDITIONAL_PASS**, triggered by the single
Harvey-significant β1Q (0050.TW, h=22, t=−3.11). **But the honest reading is
essentially NULL**:

1. **HARQ-proxy does NOT beat HAR anywhere.** QLIKE loss ratios are ≥ 1.0 in
   7/9 cells (HARQ *worse*). The only 2 cells with ratio < 1 (0050.TW h=1, h=22)
   have DM |t| < 1 — not distinguishable from HAR.
2. **No cell reaches Harvey significance in the "challenger better" direction.**
   Where DM-HLN is significant (SPY h=1, h=5), it is significant that HARQ is
   *worse*, not better.
3. **All 9 β1Q coefficients carry the BPQ-expected negative sign**, and the
   magnitudes are economically small (−0.005 to −0.039). But the single
   Harvey-significant β1Q (0050.TW h=22) does **not** translate into a
   significant or material forecast improvement (loss ratio 0.995, DM t = −0.99).
   A significant coefficient that does not improve OOS loss is not evidence the
   correction is material.

**Conclusion**: The daily-return quarticity proxy carries **essentially no
usable measurement-error-correction signal**. The negative-sign β1Q across all
cells is directionally consistent with the BPQ mechanism (measurement error does
depress the optimal daily-lag weight), but the effect is too small and too noisy
under the coarse daily proxy to improve forecasts — and the extra parameter
generally *hurts* OOS QLIKE.

## Honest Limitation Statement

This is a **low-frequency proxy** of HARQ, not true intraday HARQ. A daily
squared-return RV proxy and a `(N/3)·Σr⁴` daily quarticity proxy are **weak
analogs** of intraday RV and RQ: intraday RQ is a within-day dispersion-of-
dispersion measure estimated from ~78 five-minute returns, whereas the daily
proxy uses only 22 daily returns and cannot separate the intraday measurement
error that HARQ is designed to exploit. **The NULL/CONDITIONAL result here does
NOT imply true intraday HARQ fails** — BPQ (2016) document real gains on
intraday data. It only shows the measurement-error mechanism is not recoverable
from a daily-frequency quarticity proxy in this setup. A genuine intraday HARQ
test requires a long-sample 5-min RV+RQ panel the repo does not yet have.

## Files

- `k1600.py` — reproducible script (data fetch, RV/RQ proxy, HAR/HARQ/HARQ-F,
  expanding OOS with insanity filter, DM-HLN, β1Q HAC inference, figures)
- `k1600_results.json` — all numbers (per asset × horizon: QLIKE, MSE, loss
  ratio, DM-HLN stat/p, β1Q/t/p, insanity-filter counts, n_obs, periods)
- `figures/k1600_qlike_loss_ratio.png` — QLIKE loss ratio by asset × horizon
- `figures/k1600_dm_and_beta1q.png` — DM-HLN t-stats + β1Q significance
- `codex_review.md` — Codex code review (PASS)

## Bug Found & Fixed (provenance)

The first run produced absurd QLIKE values (up to 1.7e13). Diagnosis: a single
level-RV OLS OOS forecast extrapolated **negative** on a crisis day, was floored
to 1e-16, and QLIKE `actual / 1e-16` exploded, dominating the 3200-obs mean.
This is the known level-RV HARQ pathology BPQ (2016) address with an **insanity
filter** (reset out-of-support forecasts to the training-window mean). Fixed by
implementing the filter identically across all three models using
training-window-only stats. Post-fix QLIKE values are all in a sane range
(0.28–2.58). Codex reviewed the fixed version → PASS.

## References

- Bollerslev, Patton & Quaedvlieg (2016), *Exploiting the errors: A simple
  approach for improved volatility forecasting*, Journal of Econometrics.
- Corsi (2009), *A Simple Approximate Long-Memory Model of Realized Volatility*.
- Patton (2011), *Volatility forecast comparison using imperfect volatility
  proxies*.
- Diebold & Mariano (1995); Harvey, Leybourne & Newbold (1997), small-sample
  DM refinement.
