# K1814 — Does deep learning beat HAR at longer horizons? A boundary test on a daily realized-range proxy

> **Data-calibre warning, stated once at the top and repeated wherever it matters:**
> every forecast number in this experiment is computed on a **daily realized-range
> proxy (Parkinson)**, **not** on 5-minute realized variance. This was forced, not chosen
> for convenience — see [§2](#2-data-feasibility-gate-measured-first-before-any-model-was-written).
> The two calibres are never mixed, and §4 measures how far the proxy sits from genuine
> 5-minute RV.

**Status:** complete. §7 and §8 are rendered from `K1814_results.json` by
`render_readme_results.py`, which reads every number programmatically from the artifact —
none is retyped. Re-verify at any time with `python3 render_readme_results.py --check`,
which fails if the prose has drifted from the artifact.
**Canonical result artifact:** `K1814_results.json` (every number below maps to a key in it).
**Entrypoint:** `k1814.py` (`seed=42`; `reproduce_spec.json` emitted at run time by the run itself).

---

## 1. Why run this at all

The knowledge base already contains **four consecutive NULLs** from the K1310–K1330 ML
novel-method series (GARCH-Neural, HAR-GNN, Transformer, KAN, Conformal): at the **1-day**
horizon, deep learning does not beat HAR. K1316 is representative — HAR-VIX looked 40.6%
better than HAR-RV on QLIKE for TX1 and still failed the test (DM-HLN t=1.041, p=0.298).

This experiment is deliberately **not** another architecture proposal. It answers the question
those NULLs left open: **at which horizon, if any, does the DL increment actually appear?**
The literature framing (JFEC / IJF 2025 "ML-vs-HAR") is that ML earns its keep at longer
horizons. So the design tests h ∈ {1, 5, 22} with one honest HAR baseline and a formal test.

**A NULL here is a real answer.** "DL loses at 1, 5 and 22 days" closes the open item just as
well as finding a boundary would. Nothing was tuned toward a positive result; the specific
guard against that is §6.

---

## 2. Data feasibility gate (measured first, before any model was written)

The brief flagged this as the most likely failure point and the most likely thing to be
papered over. So it was measured, not assumed. `probe_intraday_limits()` in `k1814.py`
downloads and counts; the output is stored verbatim at
`data_calibre_gate.measured_intraday_limits`.

| ticker | interval | period requested | bars returned | trading days | bars/day | span |
|---|---|---|---|---|---|---|
| ^GSPC | 5m | 60d | 4,680 | **60** | 78.0 | 2026-05-04 → 2026-07-29 |
| SPY | 5m | 60d | 4,680 | **60** | 78.0 | 2026-05-04 → 2026-07-29 |
| QQQ | 5m | 60d | 4,680 | **60** | 78.0 | 2026-05-04 → 2026-07-29 |
| ^GSPC | 1h | 730d | 5,073 | 730 | 6.95 | 2023-08-30 → 2026-07-29 |
| SPY | 1h | 730d | 5,072 | 730 | 6.95 | 2023-08-30 → 2026-07-29 |

### Route A (5-min RV) is arithmetically impossible — rejected

60 trading days of 5-minute bars yields **60 daily RV observations**. A 22-day-horizon
forecast consumes 22 of them per target, needs ~22 more for the monthly HAR term, and would
leave a low-double-digit number of overlapping OOS points — before any training window at
all. There is no rolling OOS, no DM test with usable power, and no honest way to report one.
Route A is not "weak here"; it does not exist.

The 1-hour route (≈725 trading days) was also considered and rejected: 7 bars/day is a very
coarse RV estimator, and the window 2023-08 → 2026-07 contains **no bear market**, which
violates the standing requirement that OOS span at least one.

### Route B (daily realized-range proxy) — taken

Daily OHLC reaches back decades and covers many bear markets (1962, 1966, 1970, 1973-74,
1987, 1990, 2000-02, 2008-09, 2020, 2022).

| ticker | daily bars | span | usable from |
|---|---|---|---|
| **^GSPC (primary)** | 16,251 | 1962-01-02 → 2026-07-29 | 1962-01-02 (first High>Low) |
| SPY | 8,431 | 1993-01-29 → 2026-07-29 | 1993-01-29 |
| QQQ | 6,889 | 1999-03-10 → 2026-07-29 | 1999-03-10 |

---

## 3. Estimator choice — and a data defect that forced it

Three standard range estimators were considered: Parkinson (needs High, Low),
Garman-Klass and Rogers-Satchell (both additionally need **Open**).

Measuring the Open before trusting it turned up a defect: **on yfinance, `^GSPC`'s Open equals
the prior Close on 59% of all days**, and far more in the early sample.

| decade | rows | Open == prior Close | zero range (High==Low) |
|---|---|---|---|
| 1960s | 1,987 | **96.7%** | 0.96% |
| 1970s | 2,526 | **92.4%** | 0.71% |
| 1980s | 2,528 | 65.5% | 0.04% |
| 1990s | 2,528 | 76.7% | 0.00% |
| 2000s | 2,515 | 63.8% | 0.00% |
| 2010s | 2,516 | 6.2% | 0.00% |
| 2020s | 1,651 | 0.06% | 0.00% |

When Open is a copy of the prior Close, the `ln(C/O)` term in Garman-Klass and
Rogers-Satchell silently stops being an open-to-close intraday return and becomes a
close-to-close return. Both estimators would degenerate across most of the long sample
without erroring.

**Decision:** **Parkinson on ^GSPC is the primary estimator** (High/Low only, immune to the
defect). Garman-Klass and Rogers-Satchell are run as an estimator-robustness arm on **SPY and
QQQ**, whose Opens are genuine (Open==prior Close on only 1.9% and 1.2% of days, and zero
zero-range days).

**Non-positive variance estimates** (38 of 16,251 ^GSPC days, 0.23% — all zero-range days in
the 1960s–70s) are replaced by a **fixed, pre-specified floor `RV_FLOOR = 1e-7`**
(0.5% annualised). Deliberately *not* a sample quantile: a full-sample quantile would let a
2020 observation set the floor applied to a 1963 one, which is full-sample leakage into both
features and targets.

---

## 4. How far is the proxy from real 5-minute RV? (measured, not asserted)

The proxy substitution is quantified rather than hand-waved. `proxy_validation()` compares the
range proxies against genuine intraday RV for SPY on both overlapping windows. Intraday
returns are differenced **within** each trading day, so the first bar of a day is not an
overnight gap — otherwise the "intraday" RV would include the overnight move while Parkinson's
range does not, silently comparing two different calibres.

Stored at `data_calibre_gate.proxy_vs_true_rv`.

**vs genuine 5-minute RV** (60 days, 78 bars/day, 2026-05-04 → 2026-07-29):

| proxy | n | Pearson (logs) | Spearman | median proxy/true | OLS slope log(true) on log(proxy) |
|---|---|---|---|---|---|
| Parkinson | 60 | 0.622 | 0.588 | **0.686** | 0.624 |
| Garman-Klass | 60 | 0.655 | 0.627 | 0.696 | 0.652 |
| Rogers-Satchell | 60 | 0.659 | 0.653 | 0.710 | 0.630 |

**vs genuine 1-hour RV** (721 days, 7 bars/day, 2023-08-30 → 2026-07-29):

| proxy | n | Pearson (logs) | Spearman | median proxy/true | OLS slope |
|---|---|---|---|---|---|
| Parkinson | 721 | 0.726 | 0.707 | 0.775 | 0.879 |
| Garman-Klass | 721 | 0.723 | 0.709 | 0.827 | 0.905 |
| Rogers-Satchell | 721 | 0.656 | 0.657 | 0.807 | 0.776 |

**What this measures, in the expected direction.** The proxy sits **~31% below** genuine
5-minute RV in the median (ratio 0.686), consistent with the two known biases of range
estimators: they capture intraday variation only (no overnight gap), and discretely observed
High/Low understate the true continuous range. The log correlation of 0.62–0.73 says the proxy
carries a **substantial idiosyncratic measurement error** relative to 5-minute RV.

**Why the level bias does not contaminate the comparison, and what does.** QLIKE is
scale-invariant — `qlike(c·a, c·f) = qlike(a, f)` — and every model is trained and scored on
the *same* proxy, so a common multiplicative bias cancels out of the DL-vs-HAR contrast. The
part that does *not* cancel is the extra measurement **noise**. That is a genuine limitation
carried into §9, not a detail: noisier targets and features penalise flexible models more than
rigid ones, so this design is, if anything, tilted against the DL arm.

---

## 5. Method

**Target (direct h-step).** `y_h(t) = mean(rv[t+1 … t+h])`, modelled in logs, for
h ∈ {1, 5, 22}. Direct multi-step, not iterated.

**Baselines.**

| model | specification | role |
|---|---|---|
| `har` | Corsi (2009) HAR-RV: `log y_h ~ log rv_d + log rv_w + log rv_m`, OLS | **pre-registered primary baseline** |
| `harl` | HAR-RV **+ leverage**: adds `r_t` and `min(r_t, 0)` | **strong baseline** (see below) |
| `ridge_lags` | ridge on all 22 individual log-RV lags | linear control: is any gain just a richer lag structure? |
| `ar1` | `log y_h ~ log rv_t` | sanity floor |

`harl` exists because HAR-RV carries **no return information at all**. Any DL edge that a
single linear leverage term also captures must not be credited to deep learning. Reporting only
DL-vs-HAR-RV would be the classic weakened-baseline result.

**DL models.** A 1-layer LSTM and a 1-layer pre-norm Transformer encoder (4 heads,
mean-pooled). Capacity ∈ {16, 32, 64} and learning rate ∈ {1e-3, 3e-3} are **selected on
validation data**, once, at the first origin — not fixed by the author's guess, so the verdict
cannot be dismissed as under-powering the network.

**Information matching (decisive).** The primary DL arm consumes **log RV only**
(`channels=1`) over a 22-day window — *exactly* HAR-RV's information set, since HAR's d/w/m
terms are three linear aggregates of those same 22 lags. A DL win under this setting therefore
cannot be an information advantage. The return channel is a **separate ablation**
(`channels_with_returns`), judged against `harl`, which also has return information.

**Evaluation.** QLIKE (Patton-consistent, `a/f − ln(a/f) − 1`, 0 = perfect) as the primary
metric, with MSE/MAE reported. Log forecasts are converted to levels by `exp(m + s²/2)` using
the residual variance **of the origin that produced that row**; the uncorrected `exp(m)`
variant is reported alongside so no conclusion rests on the correction.

**Inference.** Diebold-Mariano with the Harvey-Leybourne-Newbold small-sample correction,
Newey-West HAC at lag `h−1` for the overlap induced by direct h-step targets, referred to
t(n−1). A data-driven bandwidth and the loss-differential ACF(1) are reported alongside, so
the verdict does not hinge on one lag choice. Sign convention: **positive favours DL**.
Multiplicity is controlled by **BH-FDR at q=0.05** over each 6-test family
(3 horizons × 2 DL models), applied separately for the HAR-RV family and the HAR-L family.

**Seeds.** 5 seeds (42–46) per DL configuration. Reported as ensemble QLIKE plus mean ± sd
across seeds and the per-seed DM statistics — a single-seed win or loss is not evidence.

---

## 6. Lookahead policy — and its mechanical proof

Lookahead is the highest-risk failure mode, so it is *tested*, not just asserted.
Stored at `lookahead_policy`.

1. **Features** at row *t* use rv/return with index ≤ *t*. **Targets** use rv in [t+1, t+h].
   Both are built as explicit sums over exactly the window they depend on (not
   cumsum-differencing, which loses ~1e-12 relative precision to catastrophic cancellation
   over 16k rows — the self-test below caught precisely this and it was fixed).
2. **Direct-h-step embargo.** A model forecasting from origin *T* is fit only on rows *t* with
   `t + h ≤ T`, because row *t*'s h-step target is not observable at *T* otherwise. Applied
   **identically to HAR and DL**.
3. **Fit/validation purge.** `h−1` rows are purged between the fit slice and the validation
   slice **in the rolling engine** (`rolling_forecasts`), so early stopping never scores on
   targets overlapping the fitted rows' targets.

   > **Scope correction (stage-3 certification review).** The purge is applied in
   > `rolling_forecasts` only. `select_hyperparams` — which picks capacity and learning rate
   > once, at the first origin — splits fit/validation with **no purge**. This is visible in
   > the artifact's own `selection_window` fields: at h=22 the fit slice is `[10, 2560)` and
   > the validation slice is `rows[2560:3010]`, i.e. they abut with a zero-row gap. The
   > artifact string `lookahead_policy.fit_validation_purge` says the purge covers "early
   > stopping and hyperparameter selection"; the code covers only the former. That string is
   > frozen (correcting it would mean re-running a 6,170 s experiment for a methods
   > sentence), so the correction is recorded here instead.
   > **Consequence:** for h ∈ {5, 22} the last `h−1` fit rows share future RV days with the
   > first validation rows during that one-off hyperparameter choice. It is **entirely
   > pre-OOS** — the whole selection window ends before the first forecast origin, so no
   > out-of-sample observation is touched and **no reported number changes**. Its only reach
   > is which of six `(hidden, lr)` pairs was selected, biased mildly toward larger capacity,
   > which works *against* the DL arm rather than for it.
4. **Scalers** (X and y) are fit on the training slice only and refit at every origin. No
   full-sample standardisation anywhere.
5. **Hyperparameters** are selected once on the chronological validation tail of the *first*
   training window — strictly pre-OOS — then held fixed.
6. **Level correction** uses each origin's own residual variance, stored per row. Averaging it
   across origins would apply a future refit's residual variance to an early forecast.
7. **Baseline fairness.** Linear models are fit on the **full** training window, since they
   have nothing to early-stop; withholding the validation tail from OLS would handicap the
   baseline by ~15% of its sample for no reason. **The flip side, stated explicitly:** the DL
   arm therefore fits on *fewer rows than its own baselines* — 3,000 for OLS against 2,550 /
   2,546 / 2,529 at h = 1 / 5 / 22 (the 450-row validation tail plus the `h−1` purge), about
   85%. The asymmetry runs **against** the DL arm, so it cannot manufacture a DL win. It is
   instead a caveat on the *negative* finding, and is carried into §9 as one.

**Mechanical proof (`lookahead_selftests`).** For 40 randomly chosen rows:
corrupting rv/returns **strictly after** *t* must leave every feature at row *t* bit-identical;
corrupting rv **strictly at or before** *t* must leave every target at row *t* bit-identical.
Tolerance is **exact equality (atol=0)**, not `allclose`. Flooring is applied inside the
perturbed rebuilds, so a data-dependent floor would surface here as a violation. Each row's
features and targets are additionally re-derived by naive slicing as an independent check.
All 40 rows pass all three checks (`primary.lookahead_selftests`).

---

## 7. Descriptive statistics

<!-- RESULTS:DESCRIPTIVE -->

All figures below describe the **primary series**: the daily Parkinson realized-range proxy on `^GSPC`, **16,251 daily bars** spanning **1962-01-02 → 2026-07-29**. 38 non-positive variance estimates (0.23%) were replaced by the pre-specified floor `RV_FLOOR = 1e-7`, leaving **16,208 usable panel rows** after the warm-up and target tail. These are proxy figures, not 5-minute RV — see §4 for the measured gap.

**Annualised volatility (%), from the proxy**

| mean | sd | min | p1 | p25 | median | p75 | p99 | max |
|---|---|---|---|---|---|---|---|---|
| 13.20 | 8.16 | 0.50 | 2.79 | 7.66 | 12.04 | 16.62 | 40.08 | 218.36 |

The distribution is strongly right-skewed in levels: the median is 12.04% but the maximum reaches 218.36%. That is why every model works in logs.

**Shape, in logs and in levels**

| series | mean | sd | skew | excess kurtosis |
|---|---|---|---|---|
| `log RV` | -9.9032 | 1.1729 | -0.4823 | 1.5670 |
| `RV` (level) | — | — | 39.16 | 2849.2 |

Taking logs pulls skew from 39.16 to -0.4823 and excess kurtosis from 2849.2 to 1.5670. Log RV is still not Gaussian — Jarque-Bera returns p = 0.0, i.e. normality is rejected below the resolution of double precision — but it is far closer, which is the standard justification for modelling log RV rather than RV.

**Autocorrelation of log RV — the long-memory evidence**

| lag (trading days) | 1 | 5 | 10 | 22 | 44 | 66 | 132 | 250 |
|---|---|---|---|---|---|---|---|---|
| ACF | 0.6434 | 0.5751 | 0.5175 | 0.4442 | 0.4014 | 0.3616 | 0.3179 | 0.2543 |

The ACF decays from 0.6434 at lag 1 to 0.2543 at lag 250 — roughly one trading year — without collapsing to zero. That slow hyperbolic-looking decay, not the point estimates below, is the primary evidence for long memory, and it is what motivates HAR's cascade of daily/weekly/monthly terms in the first place.

| estimator | value |
|---|---|
| GPH `d` (headline, bandwidth n^0.5) | 0.4649 |
| GPH `d`, bandwidth n^0.4 | 0.5317 |
| GPH `d`, bandwidth n^0.5 — headline | 0.4649 |
| GPH `d`, bandwidth n^0.6 | 0.4758 |
| Hurst (classical R/S) | 0.9802 |

> GPH and classical R/S are descriptive here, not inferential: both are biased by short-memory contamination, heteroskedasticity and structural breaks, and no confidence interval or break test is computed. The slow ACF decay is the primary evidence; the point estimates only summarise it.

Read as descriptive summaries only: GPH `d` moves between 0.4649 and 0.5317 across the three bandwidths, which is itself a reminder that no CI is attached to any of them.

<!-- /RESULTS:DESCRIPTIVE -->

## 8. Results

<!-- RESULTS:MAIN -->

### 8.1 Headline

**No horizon boundary exists. `h* = None`.** Across h ∈ {1, 5, 22}, `dl_beats_both_baselines` is **false at every horizon**, and `horizons_with_dl_win` is empty.

The result is stronger than "no difference", and in the direction opposite to the hypothesis. At **h = 22** the best DL model is **significantly worse** than the HAR-RV+leverage baseline after BH-FDR correction (DM-HLN = -2.313, q = 0.0414), which the artifact records as `decision_vs_harl_strong = "HARL_BETTER"`. The literature framing that motivated this experiment — ML earns its keep at longer horizons — is **contradicted here, not merely unsupported**: the DL deficit *grows* with the horizon rather than closing.

> No horizon boundary exists: no h in {1,5,22} has DL winning at that horizon and every longer one, against both baselines.

`h*` is defined as: smallest h such that h AND every longer tested horizon show a DL win surviving BH-FDR against BOTH HAR-RV and HAR-RV+leverage

### 8.2 Per-horizon results (primary arm, `^GSPC` Parkinson)

Sign convention throughout: **positive DM favours DL**. `q` is the BH-FDR-adjusted p-value within its own 6-test family (§8.3).

| h | QLIKE HAR | QLIKE HAR-L | QLIKE ridge (control) | QLIKE best DL | best DL | seed sd | DM vs HAR | p | q | DM vs HAR-L | p | q | n OOS | eff. indep. obs | decision vs HAR | decision vs HAR-L |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0.3768 | 0.3713 | 0.3832 | 0.3713 | `lstm` | 0.0036 | +0.980 | 0.3269 | 0.3923 | -0.011 | 0.9915 | 0.9915 | 13,176 | 13,176.0 | `FAIL_TO_REJECT` | `FAIL_TO_REJECT` |
| 5 | 0.2027 | 0.1982 | 0.2059 | 0.2054 | `lstm` | 0.0024 | -0.503 | 0.6153 | 0.6153 | -1.286 | 0.1985 | 0.2382 | 13,176 | 2,635.2 | `FAIL_TO_REJECT` | `FAIL_TO_REJECT` |
| 22 | 0.1931 | 0.1914 | 0.2026 | 0.2128 | `lstm` | 0.0065 | -2.113 | 0.0347 | 0.0693 | -2.313 | 0.0207 | 0.0414 | 13,176 | 598.9 | `FAIL_TO_REJECT` | `HARL_BETTER` |

OOS window: **1974-03-22 → 2026-06-26**, 13,176 rows, 18 rolling refits (`refit_every = 750`). It contains the 1973-74, 1987, 2000-02, 2008-09, 2020 and 2022 drawdowns.

**Reading the three horizons**

- **h = 1** — a dead heat. The best DL model ties HAR-L to four decimals (0.3713 vs 0.3713; DM = -0.011, q = 0.9915). It is nominally ahead of plain HAR-RV (0.3768) but nowhere near significance (DM = 0.980, q = 0.3923). The entire apparent HAR-RV gap of 0.0055 is closed by the single leverage term in HAR-L — which is exactly why HAR-L is in the design.
- **h = 5** — DL is behind both baselines (0.2054 vs HAR 0.2027 and HAR-L 0.1982) and neither gap reaches significance (q = 0.6153 and 0.2382).
- **h = 22** — the deficit becomes significant. DL QLIKE 0.2128 against HAR-L 0.1914, a gap of 0.0214 — roughly 387× the h=1 gap against the same baseline, and about 3.3× the seed sd (0.0065). It survives BH-FDR against HAR-L (q = 0.0414) though not against plain HAR-RV (q = 0.0693).

One caution on h = 22, in the direction of *less* confidence: direct 22-step targets overlap heavily, so the 13,176 OOS rows carry only **598.9 effectively independent observations**. The HAC-corrected DM statistic accounts for this, but the h=22 row is the thinnest evidence in the table despite having the largest point gap.

**The lognormal level correction, checked rather than asserted.** `qlike_no_lognormal_correction` reports the uncorrected `exp(m)` variant for every cell. Across the 6 best-DL-vs-baseline cells (3 horizons × 2 baselines), 4 keep the same ordering under both variants and 2 reverse it:

- **h = 1 vs HAR-L** — corrected: **HAR-L** ahead (0.3713 vs 0.3713, gap 0.000055). Uncorrected: **`lstm`** ahead (0.4472 vs 0.4415, gap 0.005693). Under the correction this cell is a dead heat — DM = -0.011, q = 0.9915.
- **h = 5 vs HAR-RV** — corrected: **HAR-RV** ahead (0.2027 vs 0.2054, gap 0.002689). Uncorrected: **`lstm`** ahead (0.2223 vs 0.2189, gap 0.003379). Under the correction this cell is a dead heat — DM = -0.503, q = 0.6153.

Both reversals are short-horizon cells that the corrected variant already reports as statistically indistinguishable, so neither is a DL win under either variant. Every DM statistic, BH-FDR family and decision field in this experiment is computed on the **corrected** losses, so no reported test moves. The h = 22 cells that carry the headline keep both baselines ahead under both variants (HAR-RV 0.1931 vs 0.2128 corrected, 0.2122 vs 0.2252 uncorrected; HAR-L 0.1914 vs 0.2128 corrected, 0.2100 vs 0.2252 uncorrected).

The sanity floor and the linear control behave as designed:

| h | AR(1) floor | ridge on 22 lags | HAR-RV |
|---|---|---|---|
| 1 | 0.5152 | 0.3832 | 0.3768 |
| 5 | 0.2934 | 0.2059 | 0.2027 |
| 22 | 0.2836 | 0.2026 | 0.1931 |

Ridge on all 22 individual lags never beats HAR's three aggregates, so the HAR restriction is not costing anything a richer *linear* lag structure would recover. The gap DL needed to find was never a linear one.

### 8.3 Multiplicity control — the two FDR families, in full

Multiplicity is controlled by **Benjamini-Hochberg FDR at q = 0.05**, applied **separately to two families of 6 tests each** (3 horizons × 2 DL architectures). The families are **not pooled**: one family tests against **HAR-RV**, the other against **HAR-RV+leverage**. Family members: `h1_lstm`, `h1_transformer`, `h5_lstm`, `h5_transformer`, `h22_lstm`, `h22_transformer`.

**Family `dm_vs_har` — baseline HAR-RV**

| test | DM-HLN | raw p | BH-FDR q | reject at q=0.05 | direction |
|---|---|---|---|---|---|
| `h1_lstm` | +0.980 | 0.3269 | 0.3923 | no | `DL_better` |
| `h1_transformer` | -1.380 | 0.1677 | 0.2515 | no | `baseline_better` |
| `h5_lstm` | -0.503 | 0.6153 | 0.6153 | no | `baseline_better` |
| `h5_transformer` | -2.473 | 0.0134 | 0.0402 | **yes** | `baseline_better` |
| `h22_lstm` | -2.113 | 0.0347 | 0.0693 | no | `baseline_better` |
| `h22_transformer` | -3.744 | 0.0002 | 0.0011 | **yes** | `baseline_better` |

**Family `dm_vs_harl` — baseline HAR-RV+leverage**

| test | DM-HLN | raw p | BH-FDR q | reject at q=0.05 | direction |
|---|---|---|---|---|---|
| `h1_lstm` | -0.011 | 0.9915 | 0.9915 | no | `baseline_better` |
| `h1_transformer` | -2.117 | 0.0343 | 0.0514 | no | `baseline_better` |
| `h5_lstm` | -1.286 | 0.1985 | 0.2382 | no | `baseline_better` |
| `h5_transformer` | -2.595 | 0.0095 | 0.0284 | **yes** | `baseline_better` |
| `h22_lstm` | -2.313 | 0.0207 | 0.0414 | **yes** | `baseline_better` |
| `h22_transformer` | -3.872 | 0.0001 | 0.0007 | **yes** | `baseline_better` |

**Every rejection in both families points the same way — toward the baseline.** 2 of 6 tests reject against HAR-RV (`h5_transformer`, `h22_transformer`) and 3 of 6 against HAR-RV+leverage (`h5_transformer`, `h22_lstm`, `h22_transformer`) — 5 rejections in total, spanning 3 distinct tests. In **every one** the recorded direction is `baseline_better`. **Not one test in either family rejects in favour of DL.**

The Transformer is the weaker of the two architectures and fails hardest: it is significantly worse than *both* baselines at h=5 and h=22, reaching DM = -3.872 (q = 0.0007) against HAR-L. Its per-seed dispersion is also an order of magnitude worse than the LSTM's — at h=1 the Transformer's seed sd is 0.2390 against the LSTM's 0.0036, with per-seed QLIKE ranging 0.4001–0.9749. A single seed of that model would have supported almost any story, which is why the design pre-committed to 5 seeds and reports the spread.

### 8.4 Robustness arms

> Settings, stated not silently applied: reduced vs primary: n_seeds=3, refit_every=1500, hp_grid=[(32, 0.001), (64, 0.001)]

Each arm is compared against **its own** HAR / HAR-L columns. These arms carry different tickers, sample spans and OOS row counts, so their QLIKE levels are not comparable with the primary arm's — only the *sign and significance of the contrast* within each arm is.

| arm | ticker | estimator | h | n OOS | HAR | HAR-L | LSTM | Transformer | best DL | DM vs own HAR | p | DM vs own HAR-L | p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `SPY_parkinson` | SPY | parkinson | 1 | 5,356 | 0.4041 | 0.3952 | 0.4310 | 0.4358 | `lstm` | -4.421 | 1.00e-05 | -4.930 | 8.48e-07 |
| `SPY_parkinson` | SPY | parkinson | 5 | 5,356 | 0.2525 | 0.2429 | 0.2836 | 0.2795 | `transformer` | -4.629 | 3.77e-06 | -5.390 | 7.35e-08 |
| `SPY_parkinson` | SPY | parkinson | 22 | 5,356 | 0.2776 | 0.2735 | 0.3225 | 0.3296 | `lstm` | -2.069 | 0.0386 | -2.212 | 0.0270 |
| `SPY_garman_klass` | SPY | garman_klass | 1 | 5,356 | 0.3750 | 0.3621 | 0.3839 | 0.3948 | `lstm` | -2.128 | 0.0334 | -3.588 | 0.0003 |
| `SPY_garman_klass` | SPY | garman_klass | 5 | 5,356 | 0.2424 | 0.2304 | 0.2805 | 0.2682 | `transformer` | -5.002 | 5.85e-07 | -5.944 | 2.95e-09 |
| `SPY_garman_klass` | SPY | garman_klass | 22 | 5,356 | 0.2804 | 0.2749 | 0.3330 | 0.3195 | `transformer` | -2.446 | 0.0145 | -2.598 | 0.0094 |
| `QQQ_parkinson` | QQQ | parkinson | 1 | 3,814 | 0.3849 | 0.3735 | 0.4009 | 0.4144 | `lstm` | -1.100 | 0.2714 | -1.401 | 0.1613 |
| `QQQ_parkinson` | QQQ | parkinson | 5 | 3,814 | 0.2536 | 0.2458 | 0.2640 | 0.2649 | `lstm` | -1.820 | 0.0689 | -2.649 | 0.0081 |
| `QQQ_parkinson` | QQQ | parkinson | 22 | 3,814 | 0.2510 | 0.2488 | 0.2611 | 0.2593 | `transformer` | -0.785 | 0.4327 | -1.014 | 0.3105 |

**All nine arm × horizon cells put the best DL model behind both of its own baselines** — every DM statistic in both DM columns is negative. The conclusion therefore does not depend on the ticker (`^GSPC` / `SPY` / `QQQ`), on the estimator (Parkinson / Garman-Klass), or on the sample span. `SPY_garman_klass` matters specifically: SPY's Open is genuine (§3), so this arm shows the verdict is not an artifact of being restricted to Parkinson on the defective `^GSPC` Open.

These p-values are **raw, not FDR-adjusted** — the pre-registered BH-FDR families cover the primary arm only (§8.3). They are reported to show consistency of sign, and no headline claim rests on them.

### 8.5 Ablations

> Settings, stated not silently applied: Reduced vs the primary arm, stated rather than silently applied: n_seeds=2 (refit_250 uses 1 seed and drops the Transformer, because 52 refits x 3 horizons x 2 models x 2 seeds did not fit the compute budget), refit_every=3000, select_hp=False (an ablation that re-selected capacity would not be an ablation of capacity; capacity is instead chosen on validation in the primary arm). Compare each ablation against ITS OWN har/harl columns, never the primary arm's: the OOS row set changes when seq_len or train_len changes.

**Comparison basis.** Each ablation is scored against **its own** HAR / HAR-L columns, never the primary arm's. This is not a formality: changing `seq_len` or `train_len` changes the usable OOS row set (`window_L66` has 13,132 rows and `train_len1500` has 14,676, against the primary arm's 13,176), and the sparser `refit_every = 3000` also moves the baselines themselves. Cross-arm QLIKE comparisons would be meaningless.

`ar1` and `ridge_lags` are **not run** in the ablation arms, and the Transformer is not run in `refit_250`. The console log prints `AR1=nan` / `RIDGE=nan` / `TRF=nan` for these as a fixed-width formatting placeholder; the models are simply **absent from the result artifact**, and no claim below rests on them.

| ablation | changed from primary | h | n OOS | own HAR | own HAR-L | LSTM | Transformer | DM LSTM vs own HAR-L | p (raw) |
|---|---|---|---|---|---|---|---|---|---|
| `channels_with_returns` | `channels` 1 → 2 (adds return path) | 1 | 13,176 | 0.3867 | 0.3804 | 0.3643 | 0.5497 | +3.088 | 0.0020 |
| `channels_with_returns` | `channels` 1 → 2 (adds return path) | 5 | 13,176 | 0.2077 | 0.2026 | 0.1944 | 0.3469 | +2.085 | 0.0371 |
| `channels_with_returns` | `channels` 1 → 2 (adds return path) | 22 | 13,176 | 0.2016 | 0.2003 | 0.2028 | 0.2187 | -0.343 | 0.7316 |
| `refit_250` | `refit_every` 750 → 250 | 1 | 13,176 | 0.3755 | 0.3693 | 0.3701 | not run | -0.129 | 0.8977 |
| `refit_250` | `refit_every` 750 → 250 | 5 | 13,176 | 0.2036 | 0.2001 | 0.2010 | not run | -0.120 | 0.9041 |
| `refit_250` | `refit_every` 750 → 250 | 22 | 13,176 | 0.1933 | 0.1920 | 0.2109 | not run | -1.998 | 0.0458 |
| `window_L66` | `seq_len` 22 → 66 | 1 | 13,132 | 0.3876 | 0.3817 | 0.3770 | 0.4366 | +0.984 | 0.3249 |
| `window_L66` | `seq_len` 22 → 66 | 5 | 13,132 | 0.2085 | 0.2035 | 0.2054 | 0.2655 | -0.421 | 0.6735 |
| `window_L66` | `seq_len` 22 → 66 | 22 | 13,132 | 0.2027 | 0.2013 | 0.2325 | 0.2694 | -2.283 | 0.0224 |
| `train_len1500` | `train_len` 3000 → 1500 | 1 | 14,676 | 0.3519 | 0.3666 | 0.4061 | 0.4651 | -2.038 | 0.0416 |
| `train_len1500` | `train_len` 3000 → 1500 | 5 | 14,676 | 0.1873 | 0.1839 | 0.2340 | 0.2603 | -7.994 | 1.33e-15 |
| `train_len1500` | `train_len` 3000 → 1500 | 22 | 14,676 | 0.1863 | 0.1847 | 0.2411 | 0.2648 | -5.575 | 2.52e-08 |
| `loss_qlike_direct` | `loss` logmse → qlike | 1 | 13,176 | 0.3867 | 0.3804 | 0.4180 | 0.4299 | -5.368 | 8.11e-08 |
| `loss_qlike_direct` | `loss` logmse → qlike | 5 | 13,176 | 0.2077 | 0.2026 | 0.2194 | 0.2376 | -3.370 | 0.0008 |
| `loss_qlike_direct` | `loss` logmse → qlike | 22 | 13,176 | 0.2016 | 0.2003 | 0.2325 | 0.2228 | -2.800 | 0.0051 |

**What each ablation answers**

- **`refit_250` — is the verdict an artifact of a sparse refit cadence? No.** This is the ablation the design most needed, because 18 refits over 52 years is sparse by daily-practice standards. Tripling the cadence (53 refits against the primary arm's 18) leaves the picture intact: LSTM 0.2109 against its own HAR-L 0.1920 at h=22 (DM = -1.998, p = 0.0458), essentially reproducing the primary arm's h=22 deficit. The refit is genuinely re-fitting — the two arms differ in origin count by a factor of 2.9 — and it does not rescue the DL arm.
- **`channels_with_returns` — the one place DL wins, and it does not transfer.** Giving the LSTM the return path beats *its own* HAR-L at h=1 (0.3643 vs 0.3804; DM = 3.088, raw p = 0.0020) and at h=5 (DM = 2.085, raw p = 0.0371) — but **not at h=22** (DM = -0.343, raw p = 0.7316). This is reported because it is the only positive signal in the experiment and burying it would be selective reporting. It does **not** change the headline, for reasons fixed before the run: it is outside the pre-registered FDR families so its p-values are **uncorrected**; it runs `n_seeds = 2` against the primary arm's 5; and its `refit_every = 3000` also degrades the arm's own baselines (its HAR-L is 0.3804 against the primary arm's 0.3713), so part of the margin is a weaker comparison point rather than a better model. Its honest reading is a **hypothesis for a future pre-registered test** — that any DL edge here lives in the leverage channel at short horizons, not in the volatility path at long ones — and notably it points the *opposite* way to the horizon hypothesis this experiment set out to test.
- **`window_L66` — is 22 days too short a window for the DL models? No.** Tripling the input window makes h=22 worse, not better (0.2325 against its own HAR-L 0.2013, DM = -2.283).
- **`train_len1500` — would a shorter, more adaptive window help? No, it hurts sharply.** LSTM degrades to 0.2340 at h=5 (DM = -7.994), consistent with these models being data-hungry rather than over-fit to a long window.
- **`loss_qlike_direct` — is the log-MSE training loss mismatched to the QLIKE evaluation metric? Training directly on QLIKE makes it worse at every horizon** (h=1 DM = -5.368, h=22 DM = -2.800), so the loss mismatch is not what is holding the DL arm back.

Taken together, the four non-`channels` ablations close the obvious "you configured it badly" objections: cadence, window length, training-window size and loss function each move the result the wrong way or leave it unchanged.

### 8.6 What this closes, and what it does not

**Closed.** The open item left by K1310–K1330 — *at which horizon, if any, does the DL increment appear?* — is answered for this design: **at none of h ∈ {1, 5, 22}**. `H1_short_horizon = FAIL_TO_REJECT` reproduces the four prior NULLs at h=1, and `H2_boundary_exists = False` extends them. The longer-horizon extension is not a weaker version of the h=1 null; it is a stronger result in the opposite direction, since the DL deficit is significant at h=22 against HAR-L and the Transformer is significantly worse than both baselines at h=5 and h=22.

**Not closed, and not claimed.** This bounds *two architectures* at *these capacities* on a *daily realized-range proxy*. §9 states the binding limitation: the proxy carries measurement noise that genuine 5-minute RV would not, and that noise plausibly penalises flexible models more than rigid ones — so this design is, if anything, **tilted against the DL arm**. A 5-minute-RV replication could in principle move the h=5 and h=22 rows. What it could not do is rescue the framing this experiment tested, because the deficit here widens with the horizon rather than narrowing. The `channels_with_returns` ablation is the one lead worth a pre-registered follow-up, and it points at short horizons and the leverage channel.

<!-- /RESULTS:MAIN -->

---

## 9. Limitations

1. **The data is a proxy, not 5-minute RV.** This is the binding limitation. §4 measures a
   ~31% median level gap and a 0.62–0.73 log correlation against genuine 5-minute RV. The
   level gap cancels in QLIKE; the **extra measurement noise does not**, and it plausibly
   penalises flexible models more than rigid ones. A 5-minute-RV replication would need a data
   source yfinance cannot provide.
2. **Range proxies omit the overnight gap** entirely. Conclusions are about *intraday*
   variation, not close-to-close variance.
3. **^GSPC's early sample is coarse.** Zero-range days (~1% in the 1960s–70s) and a synthetic
   Open constrain the estimator to Parkinson and make the pre-1980 data noisier.
4. **Refit cadence** is sparse relative to daily practice; the `refit_250` ablation exists
   precisely to test whether the verdict is an artifact of it.
5. **Seed dispersion is not a confidence interval.** The reported sd across seeds 42–46
   measures optimisation variability conditional on those five runs; it is not sampling
   uncertainty.
6. **GPH and R/S are descriptive only.** Both are biased under short-memory contamination,
   heteroskedasticity and structural breaks; no CI or break test is computed. The slow ACF
   decay is the primary evidence, with the point estimates only summarising it.
7. **Two architectures, not a survey.** A negative result bounds *these* models at *these*
   capacities on *this* proxy — it is not a claim about deep learning in general.
8. **The DL arm trains on ~15% fewer rows than the linear baselines.** Early stopping needs a
   holdout, so the DL fit slice gives up the validation tail and the `h−1` purge while OLS
   keeps the whole window (§6.7). The asymmetry is forced by early stopping and it
   disadvantages the DL arm, so it cannot have produced a spurious DL win — but part of the
   h=22 deficit could be a training-sample-size effect rather than an architecture effect,
   and this design cannot separate the two.
9. **The lognormal level correction moves two short-horizon orderings.** §8.2 reports the two
   best-DL-vs-baseline cells (h=1 vs HAR-L, h=5 vs HAR-RV) whose ordering reverses under the
   uncorrected `exp(m)` variant. Both are cells the corrected variant already calls
   statistically indistinguishable, and all inference runs on the corrected losses — but the
   sign of those two comparisons is not robust to the level-conversion choice.

---

## 10. Reproducing

```bash
cd experiments/k1814
python3 k1814.py                 # full run
python3 k1814.py --pilot         # fast smoke test (truncated sample, 2 seeds)
```

`reproduce_spec.json` is written **by the run itself**, from the same `trace_file()` snapshot
that stamps `code_trace` into `K1814_results.json`, so the spec cannot describe a different
program than the one that produced the results. Cached inputs live in `data/` and are hashed
into the spec. Verify with:

```bash
python3 scripts/check_experiment_artifacts.py check --path experiments/k1814
```

### Entrypoint hash: `k1814.py` no longer matches the pin, on purpose

`reproduce_spec.json` pins the entrypoint at sha `b1a67269…` (66,724 bytes). The working
`k1814.py` hashes to `d5b851a9…` (67,086 bytes). **This divergence is intentional and the
spec is correct as written.**

After the run completed, one post-hoc edit was made to `k1814.py`: the ablation loop called
`checkpoint(f"ablation:{name}", [])`, so an artifact cut mid-loop would have reported zero
unresolved items while holding only some of the five ablations — claiming completeness it did
not have. The loop now tracks the outstanding specs and names them, matching what the
robustness loop already did. The diff is 4 added lines and 1 changed line, and it touches
**no estimation, no data and no verdict logic** — it changes only what a *future partial*
artifact reports about itself. The run was therefore not repeated and no number moved.

The bytes that actually produced the archived results are preserved verbatim at
**`gate_history/b1a67269__k1814.py`**, which hashes exactly to the pin.

- To **audit or reproduce the archived numbers**, use `gate_history/b1a67269__k1814.py`.
- To **run the experiment again**, use `k1814.py`.
- Do **not** re-point `reproduce_spec.json` at the new sha. The spec describes the code that
  produced the results, which is precisely the traceability it exists to provide.

## 11. Files

| file | what |
|---|---|
| `k1814.py` | entrypoint; models, rolling engine, tests, figures |
| `K1814_results.json` | canonical result artifact (byte-traceable) |
| `reproduce_spec.json` | run-time-emitted reproduction spec; pins the entrypoint sha that produced the results |
| `render_readme_results.py` | renders §7 and §8 from the result artifact; `--check` fails on drift |
| `review_verdict.json` | second-review verdict (checklist, artifact hashes, residual risks) |
| `gate_history/` | byte-exact copy of the entrypoint that produced the results (see §10) |
| `fig1_longmemory_regimes.png` | ACF of log RV-proxy + volatility regimes |
| `fig2_qlike_by_horizon.png` | QLIKE by horizon, error bars = sd across seeds |
| `fig3_dm_statistics.png` | DM-HLN statistics vs HAR by horizon |
| `fig4_forecast_vs_actual.png` | realised vs forecast, h=1 and h=22 |
| `fig5_proxy_validation.png` | range proxies vs genuine intraday RV |
| `data/` | cached inputs (hashed into the spec) |
