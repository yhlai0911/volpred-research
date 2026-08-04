# K1733 — Volatility transmission along the AI-infrastructure funding chain

**Verdicts** — H1 `ACCEPT` · H2 `REJECT` · H2R (post-hoc) `PARTIAL_POST_HOC` · H3 `REJECT` · H4 `NOT_RUN_PRECONDITION_NOT_MET`

**Headline.** Total volatility spillover across the AI / power / credit system is large and
unambiguously real (TCI 60.3pp against a no-spillover floor of 2.0pp, p = 0.002). But the
hypothesis this experiment was built to test — that power/grid/credit volatility leads Nasdaq
realized volatility — fails in both of the ways that matter. The **net variance-share direction
runs outward from the AI leg**, in all 8 pairs, in both sample designs, in all three sub-periods,
with bootstrap sign stability 0.98–1.00. And while the physical/credit leg *does* carry
FDR-surviving, market-controlled, in-sample Granger lead information for AI volatility (7/8 pairs),
**that information is worth exactly nothing out of sample**: 0 of 12 forecast cells improve on a
baseline that already knows the target's own range volatility and the broad-market volatility
factor, and 11 of 12 get worse.

The most transferable result is a near-miss. Run against the brief's literal baseline — a bare
squared-return HAR-RV — the exogenous block looks spectacular: Clark-West t up to **+7.25**,
12/12 FDR-significant. Every bit of that is estimator quality and the common market factor. The
identification ladder in §4 is what separates them, and it is the reason this experiment reports
NULL instead of a false discovery.

---

## 1. Motivation and source

`research_program.md` line 606 (unchecked), sourced from the J.P. Morgan 2026 alternatives
outlook: AI data-centre financing is migrating from public to private markets. The tradable
reading of that thesis is a lead-lag claim — if an AI capex shock hits the **physical bottleneck**
(power, grid, infrastructure) and the **funding cost** (credit) before it reaches equity
volatility, then XLU / PAVE / HYG / LQD volatility should be an early-warning gauge for SMH / QQQ
realized volatility.

That is falsifiable, and this experiment falsifies the useful part of it.

### Why the guardrails in this script are unusually heavy

Three prior K-series results bear directly on the method, and all three were corrections:

| Prior | What it established |
|---|---|
| **K628b** (CORRECTED 2026-07-13) | "SPY net transmitter +43.7pp" was a **Cholesky-ordering artifact**; order-invariant KPPS gave +14.6pp. |
| **K865b** | The Diebold-Yilmaz SPY-hub **direction** was an ordering artifact while the **total** spillover was real. The two conclusions do not share a fate. |
| **K907** | Connectedness is essentially uncorrelated with VIX (r = 0.001) — a separate risk dimension, not a volatility-level proxy. |

K1733's core hypothesis is *directional*, which is precisely where K628b and K865b died. Two
further priors shaped the identification strategy rather than the estimator:

- **K1508** (NULL): the AI power-demand narrative did not robustly reprice XLU/VPU/GRID/PAVE into
  a higher relative-volatility regime.
- **K1332 / K1343 / K1344 / K1499**: public credit proxies as volatility signals are narrow or
  null, and **K1499 specifically found BDC stress largely collapsing after SPY-volatility
  controls**. That is the confound §4 is built to defeat.

---

## 2. Data

| | |
|---|---|
| Source | yfinance daily, `auto_adjust=False` |
| Adjustment | Open/High/Low rescaled by `Adj Close / Close`; Close = Adj Close |
| Download window | from 1990-01-01; actual samples set by common availability (below) |
| Snapshot | `data/prices_raw.csv` + one `data/<TICKER>_adjusted_ohlc.csv` per ticker |
| Seed | 42 for every bootstrap, surrogate, permutation and noise draw |

**Baskets.** AI leg `MSFT NVDA SMH QQQ` · physical leg `XLU PAVE` · credit leg `HYG LQD`.
`SPY` is downloaded but is **not** a basket member — it is the broad-market volatility control
in §4, and nothing else.

### Per-ticker coverage (as run, 2026-07-29 snapshot)

| Ticker | First | Last | N |
|---|---|---|---|
| MSFT | 1990-01-02 | 2026-07-29 | 9210 |
| NVDA | 1999-01-22 | 2026-07-29 | 6921 |
| QQQ | 1999-03-10 | 2026-07-29 | 6889 |
| SMH | 2000-06-05 | 2026-07-29 | 6576 |
| XLU | 1998-12-22 | 2026-07-29 | 6941 |
| **PAVE** | **2017-03-08** | 2026-07-29 | **2361** |
| HYG | 2007-04-11 | 2026-07-29 | 4856 |
| LQD | 2002-07-30 | 2026-07-29 | 6038 |
| SPY | 1993-01-29 | 2026-07-29 | 8431 |

### Two samples, on purpose

PAVE was listed 2017-03-08. Padding it with NaN would be fabrication; dropping ten years of
history to accommodate it would discard the GFC and hide whether any result is sample-specific.
So both are reported:

| System | Assets | Sample | N | OOS start | Role |
|---|---|---|---|---|---|
| `full8` | MSFT NVDA SMH QQQ XLU PAVE HYG LQD | 2017-03-08 → 2026-07-29 | 2361 | 2021-01-04 | **primary** (brief's spec) |
| `long7` | same minus PAVE | 2007-04-11 → 2026-07-29 | 4856 | 2015-01-01 | secondary (sample robustness) |

The brief's OOS cut is 2015-01-01, which `long7` uses directly. It predates `full8`'s common
sample entirely, so `full8` uses 2021-01-04 — leaving ~4 years of training and putting the 2022
bear market in the evaluation window. `long7`'s OOS additionally contains 2018Q4, the 2020 COVID
crash and 2022, satisfying the repo requirement that OOS include at least one bear market.

### Volatility proxy

**Primary: log annualised Parkinson (1980) daily volatility**, `log(sqrt(252 · PK))` where
`PK = ln(H/L)² / (4 ln 2)`.

Why Parkinson: it is range-based, **strictly non-negative** (Garman-Klass can go negative and
needs a floor, which quietly deletes the exact days a range estimator is most informative), and
it is the same estimator family Diebold-Yilmaz (2012) use for daily connectedness. Logs stabilise
the right skew and keep the VAR's linear shock structure defensible.

Floor audit: 1 floored observation across all 9 tickers × full history (PAVE, one zero-range day).

**Robustness: Garman-Klass.** Re-estimating the `full8` network on GK gives TCI 60.76 (vs 60.27)
and **8/8 sign agreement** on the pairwise net-directional measure. The proxy choice does not
drive anything.

ADF (`autolag='AIC'`) rejects a unit root at 5% for **every** series in both systems
(`n_series_adf_nonstationary_at_5pct = 0`), so the VAR is estimated on log-volatility levels as
the DY literature does, without a differencing caveat.

---

## 3. Method — the connectedness arm (H1, H2)

VAR(p) on the log-volatility panel, p selected by AIC within `maxlags=5` (selected p = 5 for both
systems), forecast-error variance decomposed at horizon H = 10, row-normalised, then
Diebold-Yilmaz aggregation in percentage points.

**Every directional number comes from a hand-rolled order-invariant KPPS generalized FEVD**
(Koop-Pesaran-Potter 1996; Pesaran-Shin 1998), built from `res.sigma_u` and the
non-orthogonalised `res.ma_rep`:

```
theta_ij(H) = sigma_jj^-1 · Σ_h (e_i' A_h Σ e_j)² / Σ_h (e_i' A_h Σ A_h' e_i)
```

`statsmodels`'s `.fevd()` is the **Cholesky** decomposition and is never used for a claim. A
Cholesky arm is estimated deliberately, on 200 genuinely re-fitted random column orders, purely
to **measure** the size of the artifact.

**Pairwise net directional connectedness** `NPDC_{s→t} = θ[t,s] − θ[s,t]`, in pp — the share of
t's forecast-error variance explained by s's shock minus the reverse. Positive = s is a net
transmitter to t.

**Three separate robustness numbers, deliberately not conflated:**

1. **KPPS order-invariance** — max absolute deviation across 200 orderings. This is a *numerical
   certification that the estimator is what it claims to be*, not a statistical result. Sign
   stability of 1.00 here is true by construction and is reported as such.
2. **Statistical sign stability** — from a circular block bootstrap (L = 60 ≈ 3 months,
   B = 1000). This is the real robustness number.
3. **Cholesky sign stability** — the artifact yardstick.

**H1's null floor.** A GFEVD estimated on finitely many observations of *genuinely independent*
series still reports a positive TCI, so a TCI level is uninterpretable without knowing what the
estimator says when the answer is zero. The floor is 500 independent AR(p) surrogates that
preserve each series' own persistence and set true cross-dependence to exactly zero.

### Formal lead-lag test (required for any "A leads B" sentence)

HAC-robust Granger causality, both directions, run in two arms:

- **bivariate** — target's own p lags + source's p lags;
- **`spy_controlled`** — the same plus SPY's p lags. **This is the identified arm and the only
  one the verdicts read.** Without it, a Granger rejection can be the common market volatility
  factor arriving at the two legs with slightly different timing.

Newey-West covariance with bandwidth `ceil(n^(1/3))` = 14 (`full8`) / 17 (`long7`) — the repo
canonical rule, never the degenerate `h−1 = 0`. Reported alongside: lag-specific coefficients
with HAC standard errors, and a circular-block-bootstrap 90% interval on the sum of the source's
lag coefficients (B = 500; the bootstrap needs no HAC of its own, so those refits are plain OLS).
Benjamini-Hochberg FDR at q = 0.10 within each direction × arm family.

### Sub-period robustness

Cut on events, not equal thirds: `pre_ai_2007_2019` (GFC, 2011, 2015-16), `covid_ratehike_2020_2022`,
`ai_capex_2023_2026` (post-ChatGPT — the period the source thesis is actually about).

---

## 4. Method — the forecast arm (H3), and why it has a ladder

The brief's literal H3 is "add physical/credit volatility to a HAR-RV baseline". **Tested that
way the hypothesis is not identified**, for two independent reasons:

1. The exogenous regressors are **range-based** volatility; a HAR-RV baseline's regressors are
   **squared close-to-close returns**. A large part of any gain is therefore a better volatility
   *estimator*, not a lead-lag channel.
2. XLU/PAVE/HYG/LQD volatility is strongly loaded on the **common market volatility factor**.
   Part of any remaining gain is generic beta. This is exactly what K1499 found for BDCs.

So the comparison is a ladder of nested models on one shared index, one shared lag convention,
one shared expanding-training schedule:

| Rung | Model | Adds |
|---|---|---|
| M0 | own HAR-RV: squared-return log RV at d/w/m | — (the brief's literal baseline) |
| M1 | + own **range** volatility at d/w/m | estimator quality |
| M2 | + **SPY** range volatility at d/w/m | broad-market volatility factor |
| **M3** | + **physical/credit** range volatility (5-day mean, one per exogenous ticker) | **the channel under test** |

**Primary comparison: M3 vs M2.** Diagnostic rungs M1−M0 and M2−M1 are reported so a reader can
see exactly where the apparent gain lives, and `M0plusExog_vs_M0` is reported as the brief's
literal reading, explicitly labelled as not identified. Each rung gets its own BH-FDR family over
the 12 cells — mixing the estimator-quality rung into the primary family would let it carry the
correction.

**Cells:** 2 systems × 2 targets (QQQ, SMH) × 3 horizons (h = 1, 5, 22) = 12.

**Target:** forward realized variance, `y_t = mean(r_s²)` over `s ∈ [t, t+h−1]`, from log
close-to-close returns.

**Inference:** Clark-West (2007) one-sided, on log-variance MSPE, via the repo canonical
`volpred.stats.model_evaluation.clark_west_test` with `h` = the cell's horizon (HAC bandwidth
12–40 across cells; never degenerate). Every rung is nested in the next, so Clark-West is the
right test throughout, and **no unadjusted nested loss t-statistic exists anywhere in this
experiment** — under a nested null it is undersized. QLIKE on the variance level is reported with
a stationary-bootstrap interval and is **descriptive only**; it governs no verdict.

Companions: OOS R² increment on the log scale, and a stationary-bootstrap 90% interval
(B = 1000, mean block 22) on the raw squared-error gap.

---

## 5. Lookahead policy

- **Every predictor enters as an explicit `.shift(1)`.** The feature row stamped at date *t*
  contains only closes up to *t−1*; the target stamped at *t* is realized variance over
  `[t, t+h−1]`. `signal from t−1, outcome at t`, literally.
- **Label embargo on training rows.** At forecast origin *i*, training row *j* is admitted only
  if its entire label window closes first: `j + h − 1 < i`, i.e. `j ≤ i − h`. Implemented as
  `last_train = i - h` in `expanding_oos`.
- **One convention for everything.** M0…M3 share the same shift, the same index, the same
  training schedule; the strategy arms use the same one-day lag.
- **The log→level conversion uses in-sample residual variance only.** `expanding_oos` returns the
  *training* residual variance per origin; taking it from realized OOS residuals would be a
  lookahead through the back door. (This was a real defect in the first draft, caught before the
  production run.)
- **Rolling / sub-period networks** are in-sample descriptions stamped at each window's last
  observation; they make no forecast claim.

### Future-noise causal probe

Every OHLC bar **on or after 2020-06-30** is replaced by an N(0, 0.005²) random walk (0.5%
daily), and the whole pipeline is rebuilt. Anything stamped on or before the cut must be
**bit-identical**.

**The boundary is inclusive (`>= cut`), and that is the point.** A forecast at origin
`i ≤ cut` may legally touch dates up to `i − 1`, so corrupting from the cut inclusive leaves
every legal input untouched while poisoning the first illegal one. The first version of this
probe corrupted only `> cut`, which **cannot** catch a predictor that reads its own same-day
bar or an embargo that is off by one day: at `i = cut` both read bar `cut`, which that version
left clean. Codex review caught this and it was fixed before the final run.

Second hardening from the same review: an unmeasurable comparison is now a **violation**, not
a silent zero. `_probe_deviation` fails on an index mismatch, a changed missingness pattern, too
few finite cells to constitute a test, or a shape mismatch — a probe that reports 0.0 because it
compared nothing certifies only its own blindness. Structurally missing history (PAVE before
2017) is legal and present in both panels, so masks are compared and only finite cells are
differenced.

| Stage | Max absolute deviation |
|---|---|
| the corruption itself, **post**-cut (sanity: the noise must bite) | **5.262** |
| log-volatility panel, pre-cut | **0.0** |
| all 5 ladder design matrices, 6 cells × 3325 pre-cut rows | **0.0** |
| all 5 rungs' forecasts, log scale, 6 cells × 1383 origins | **0.0** |
| all 5 rungs' forecasts, variance level (incl. the σ² conversion) | **0.0** |
| every strategy weight **and** z-score (`w_bh w_own w_mkt w_cross z_own z_mkt z_cross`) | **0.0** |

`violations = []`, `n_violations = 0`, verdict `CLEAN`.

---

## 6. Success criteria, fixed before the run

| | Hypothesis | Criterion |
|---|---|---|
| **H1** | total spillover exists | surrogate/bootstrap p < 0.05 vs an independent-AR no-spillover floor |
| **H2** | physical/credit → AI net transmission | KPPS NPDC > 0, BH-significant at q = 0.10, **and** bootstrap sign stability ≥ 90%, **and** verified estimator order-invariance. Any one failing → REJECT/PARTIAL, no hedging. |
| **H3** | incremental OOS predictive content | primary rung M3 vs M2: Clark-West one-sided, BH q = 0.10 over 12 cells, positive OOS R² increment; bootstrap interval on the squared-error gap excluding zero in ≥ 1 cell |
| **H4** | tradability | run only if H2 or H3 is ACCEPT/PARTIAL. Beat buy-and-hold **and** the own-volatility gate **and** the market-volatility gate across 0/1/5 bp per side. A win only in the high-cost column is a **turnover artifact**, not a signal. |

---

## 7. Results

### H1 — total spillover: `ACCEPT`

| System | TCI (pp) | 95% block-bootstrap CI | Independent-AR floor (mean / q95) | p |
|---|---|---|---|---|
| `full8` | **60.27** | [57.42, 65.81] | 1.70 / 2.03 | **0.002** |
| `long7` | **52.99** | [51.32, 59.50] | 0.66 / 0.83 | **0.002** |

Roughly 53–60% of one-day-ahead volatility forecast-error variance in this system is cross-asset.
The floor makes the size interpretable: an estimator handed genuinely independent series with the
same persistence and the same sample length reports ~1–2pp. The observed value is ~30× that.
p = 0.002 is 1/501, the minimum attainable with 500 surrogates.

Sub-period TCI: 54.3 / 66.5 / 56.5 (`full8`) and 50.5 / 63.2 / 51.8 (`long7`) — elevated during
COVID + rate hikes, as expected, and never near the floor. This is consistent with K865b's
finding that *total* spillover survives even when direction does not.

### H2 — direction: `REJECT`, and decisively in the wrong direction

All 8 pairwise net-directional values are **negative**: the AI leg is the net transmitter, the
physical/credit leg the net receiver.

| Pair | NPDC (pp) | 90% bootstrap CI | Bootstrap sign stability | BH p (H2) |
|---|---|---|---|---|
| XLU→SMH | −4.27 | [−5.86, −2.63] | 1.00 | 1.000 |
| XLU→QQQ | −5.54 | [−7.27, −3.85] | 1.00 | 1.000 |
| PAVE→SMH | −3.25 | [−4.97, −1.05] | 1.00 | 1.000 |
| PAVE→QQQ | −5.45 | [−7.54, −3.87] | 1.00 | 1.000 |
| HYG→SMH | −2.11 | [−3.53, −0.60] | 0.98 | 1.000 |
| HYG→QQQ | −3.90 | [−5.81, −2.12] | 1.00 | 1.000 |
| LQD→SMH | −3.26 | [−4.76, −1.62] | 1.00 | 1.000 |
| LQD→QQQ | −2.70 | [−4.68, −1.65] | 1.00 | 1.000 |

`n_pairs_fdr_significant_positive = 0` of 8. The pre-specified criterion fails on its first
clause, so H2 is REJECT — not PARTIAL.

Asset-level net directional (`full8`): QQQ **+28.6**, SMH +15.0, MSFT +6.5, HYG +3.3, NVDA −7.0,
PAVE −10.1, LQD −11.9, **XLU −24.4**. The utilities ETF is the single largest net receiver in the
system.

**Sub-period stability:** `sign_agreement_with_full_sample = 1.00` and
`all_subperiods_all_pairs_negative = true` for **both** systems across all three regimes —
including `ai_capex_2023_2026`, the window the source thesis describes. The reversal is not a
regime artifact (fig6).

### The ordering artifact, measured

| System | KPPS max abs deviation over 200 orderings | Cholesky worst-pair sign stability |
|---|---|---|
| `full8` | 2.98 × 10⁻¹³ | **0.315** |
| `long7` | 3.27 × 10⁻¹³ | **0.355** |

The KPPS arm is order-invariant to machine precision, as required. The Cholesky arm is worse than
a coin flip: for LQD→SMH in `full8`, 200 random orderings of the same fitted system span
**[−9.7, +9.8] pp** and the sign is stable only 32% of the time. Had this experiment used
`statsmodels`'s `.fevd()`, the ordering alone could have produced a headline in either direction
for essentially every pair (fig2). This is a direct, quantitative reproduction of the K628b /
K865b failure mode on new data.

### H2R (post-hoc) — the mirror: `PARTIAL_POST_HOC`

The complement of the pre-specified one-sided test. 8/8 pairs are negative and
BH-significant in their own family with sign stability ≥ 0.98, but the SPY-controlled Granger
evidence is *stronger* in the hypothesised direction (7/8) than in the reverse (5/8), so the
composite criterion is only partly met. **This was not pre-specified and is labelled post-hoc
everywhere it appears.** KPPS shares are shares of *correlated* shocks, so this is a reduced-form
informational lead, not a structural causal effect.

### Granger lead-lag — the physical/credit leg *does* lead, in sample

Identified (`spy_controlled`) arm, BH q = 0.10 within direction:

| System | physical/credit → AI | AI → physical/credit |
|---|---|---|
| `full8` | **7 / 8** | 5 / 8 |
| `long7` | **5 / 6** | 2 / 6 |

Coefficient sums are positive with bootstrap intervals excluding zero for the significant pairs
(e.g. `long7` XLU→QQQ: Wald 34.6, sum of 5 lag coefficients +0.101, 90% CI [+0.062, +0.140], sign
stability 1.00). Only HYG→SMH fails in both systems.

**This does not contradict H2.** The two measures answer different questions: Granger asks
whether the source's lags add incremental predictability to the target's conditional mean;
NPDC asks which way the *balance* of correlated-shock variance shares points. Both can be true at
once, and here they are. The tension is recorded in the results JSON at
`verdicts.H2.granger_vs_npdc_tension`.

### H3 — out-of-sample: `REJECT`. And this is the important part.

FDR-significant cells by ladder rung, 12-cell family each:

| Rung | What it adds | FDR-significant | …with positive ΔR² |
|---|---|---|---|
| M1 − M0 | own **range** volatility | **12 / 12** | 12 / 12 |
| M2 − M1 | **SPY** volatility factor | 4 / 12 | 4 / 12 |
| **M3 − M2** | **physical/credit block (PRIMARY)** | **0 / 12** | **0 / 12** |
| M0+Exog − M0 | *brief's literal reading, not identified* | **12 / 12** | 8 / 12 |

The loose reading reaches Clark-West **t = +7.25** and would have been declared a discovery.
Once the baseline knows the target's own range volatility, the entire effect vanishes: the primary
rung's largest t is **+0.98** (`full8` SMH h=1) and 11 of 12 cells have a *negative* OOS R²
increment. Every primary BH-adjusted p is 0.934.

Per-cell primary rung:

| System | Target | h | n OOS | M1−M0 t | M2−M1 t | **M3−M2 t** | ΔR² | QLIKE Δ |
|---|---|---|---|---|---|---|---|---|
| full8 | QQQ | 1 | 1398 | +8.95 | −0.96 | −0.02 | −0.0024 | −1.96% |
| full8 | QQQ | 5 | 1394 | +7.90 | −0.00 | +0.37 | −0.0035 | −2.61% |
| full8 | QQQ | 22 | 1377 | +6.11 | −0.02 | −1.29 | −0.0371 | −8.65% |
| full8 | SMH | 1 | 1398 | +7.66 | +1.90 | +0.98 | +0.0001 | −1.98% |
| full8 | SMH | 5 | 1394 | +6.88 | +0.96 | −0.67 | −0.0104 | −3.40% |
| full8 | SMH | 22 | 1377 | +5.14 | +0.35 | −0.54 | −0.0290 | −6.74% |
| long7 | QQQ | 1 | 2909 | +11.81 | −0.71 | −1.34 | −0.0019 | −0.01% |
| long7 | QQQ | 5 | 2905 | +9.88 | +0.55 | −1.02 | −0.0039 | −1.10% |
| long7 | QQQ | 22 | 2888 | +6.02 | +0.10 | −0.17 | −0.0154 | −6.09% |
| long7 | SMH | 1 | 2909 | +9.40 | +2.66 | −0.25 | −0.0012 | −0.56% |
| long7 | SMH | 5 | 2905 | +8.31 | +2.30 | −1.51 | −0.0038 | −1.03% |
| long7 | SMH | 22 | 2888 | +4.56 | +2.13 | +0.05 | −0.0103 | −3.92% |

Four cells have squared-error-gap intervals lying strictly **below** zero (full8 QQQ h=22, long7
QQQ h=1, long7 QQQ h=5, long7 SMH h=5): the exogenous block is significantly *harmful* there, not
merely useless. The criterion asked for an interval above zero; none exists.

### H4 — `NOT_RUN_PRECONDITION_NOT_MET`

The pre-specified gate was "run only if H2 or H3 is ACCEPT/PARTIAL". Both are REJECT, so the
strategy arm was not run and **no Sharpe ratio, return or drawdown number is reported anywhere in
this artifact** — `h4_strategy` is `null`. Running it after a double REJECT would be fishing, and
the brief forbade it.

The code is present (`run_h4`, cost grid 0/1/5 bp per side, four arms including a
market-volatility gate, `compare_max_drawdown` plus a circular-shift null for the
exposure-matched drawdown gap). Because dormant code should not be *described* as working,
`test_k1733.py::test_h4_path_executes_and_is_coherent` executes it against the real cached panel
and checks cost monotonicity, the exposure ≤ buy-and-hold bound, presence of the exposure-matched
companion and its phase null, and that the turnover-artifact flag is a genuine function of the
cost grid. That test's numbers are deliberately not reported: they are a code-health check, not a
result. The lookahead probe separately confirms the strategy weights are lag-clean.

---

## 8. Limitations

1. **Free daily equity proxies are not the funding chain.** XLU/PAVE/HYG/LQD are liquid *shadows*
   of power prices, interconnection capacity and private-credit marks. They carry the market
   factor with them, which is why M2 exists. A null here bounds the *proxy*, not the underlying
   economics.
2. **KPPS shares are not structural.** Generalized FEVD shares come from correlated, un-orthogonalised
   shocks. NPDC is a reduced-form informational balance, not a causal effect. The alternative
   (Cholesky) is measurably worse — §7 quantifies exactly how much worse — but "better than an
   artifact" is not "structural".
3. **`full8` is only 2361 observations**, and PAVE cannot be extended backwards. `long7` covers
   4856 and agrees on every sign, which is the mitigation, but the PAVE-specific channel rests on
   the short sample alone.
4. **Daily frequency.** An intraday funding-stress channel could exist and be invisible here.
5. **H2R is post-hoc.** The reversal was not pre-registered. It is formally tested and
   sub-period-stable, but its p-values are not protected against the fact that the direction was
   chosen after seeing the sign.
6. **Fixed VAR lag and FEVD horizon.** p by AIC within 5, H = 10. No sensitivity sweep over
   (p, H); the DY literature's conventional values were used.
7. **PAVE has one floored zero-range day.** Recorded in `descriptive.floor_audit_parkinson`;
   1 observation out of 2361 cannot move anything.

---

## 9. Mission sanity check — what is this worth to VolPred?

**What the NULL rules out.** A plausible, currently fashionable route to a volatility signal:
"watch power/grid/credit volatility, forecast Nasdaq volatility". After controlling for the
target's own range volatility and the broad-market volatility factor, the physical/credit block
adds **nothing** out of sample across 12 cells, 2 sample designs, 3 horizons and 2 targets — and
is significantly harmful in 4 of them. Nobody on this platform needs to build that feature, and
the H4 strategy that would have followed it does not need a backtest. That is the value of the
NULL: one fewer live hypothesis, and a specific reason it dies.

**What is genuinely usable, three things:**

1. **The identification ladder is reusable and it changed the answer.** M0-vs-M0+Exog says
   t = +7.25 and 12/12 significant. M2-vs-M3 says 0/12. Any future experiment that adds a
   range-based or cross-asset volatility regressor to a squared-return HAR baseline **must** run
   the M1 rung, or it will report estimator quality as a discovery. This is the same class as
   K1499's SPY-vol collapse, now with a mechanical recipe.
2. **In-sample Granger significance is not forecast value — measured on the same data.** 7/8
   FDR-surviving, market-controlled Granger rejections coexist with 0/12 out-of-sample wins.
   Copies the K195 lesson ("cross-section structural evidence ≠ forecast utility") into the
   lead-lag setting with both numbers computed side by side in one artifact.
3. **The Cholesky artifact is now sized on a third dataset.** Worst-pair sign stability 0.315,
   ranges spanning ±10 to ±29pp. K628b and K865b each showed it once; this shows it holds on an
   entirely different asset set, which strengthens the repo-wide rule rather than restating it.

**What the total-spillover result is good for.** TCI ~53–60pp against a ~1–2pp floor says these
eight assets are one volatility system, and XLU is its largest net receiver. That is a
*risk-management* fact, not a forecasting one: a portfolio hedging AI-capex exposure with
utilities is buying an instrument that receives AI volatility rather than one that anticipates it.
Consistent with K907, this is a separate dimension from the volatility level and should not be
read as a VIX proxy.

**What would change the verdict.** Instrument the physical leg directly instead of through equity
proxies: PJM/ERCOT interconnection-queue and capacity-auction prices, data-centre
power-purchase-agreement spreads, private-credit fund marks. Those are the variables the J.P.
Morgan thesis is actually about. The result here is that their free equity shadows do not
substitute for them.

---

## 10. Artifacts and reproduction

```
experiments/k1733/
├── K1733.py                     # entrypoint; sha256 e29c99197be7… (101233 bytes)
├── K1733_results.json           # canonical result, byte-pinned by reproduce_spec.json
├── reproduce_spec.json          # emitted AT RUN TIME by finalize_experiment
├── README.md                    # this file
├── test_k1733.py                # 18 tests: dormant-H4 health, verdict re-derivation, invariants
├── data/                        # yfinance snapshot: raw panel + per-ticker adjusted OHLC
└── figures/                     # 9 PNGs (see below)
```

```bash
uv run python experiments/k1733/K1733.py            # ~193 s, uses the cached snapshot
uv run python experiments/k1733/K1733.py --refresh  # re-download from yfinance
uv run python experiments/k1733/K1733.py --quick    # smoke run, reduced replicate counts

uv run --extra dev python -m pytest experiments/k1733/test_k1733.py -q   # 18 passed
uv run python scripts/experiment_gates.py run --path experiments/k1733   # PASS, 4 gates
```

`--quick` reduces replicate counts and is for smoke-testing only; it stamps
`config.quick_mode = true`, and a test refuses to accept such a run as the artifact.

`reproduce_spec.json` and `K1733_results.json` are written by a single
`finalize_experiment(...)` call, so `results["code_trace"]` and `spec["entrypoint"]` describe the
same bytes by construction, and the spec additionally pins the exact result bytes.

**Figures**

| File | Content |
|---|---|
| `fig1_network_full8.png`, `fig1_network_long7.png` | KPPS GFEVD table + the 8 (6) pairwise NPDC values with bootstrap CIs |
| `fig2_ordering_full8.png`, `fig2_ordering_long7.png` | the ordering-artifact audit: Cholesky range over 200 orders vs the invariant KPPS point |
| `fig3_rolling_tci.png` | rolling 250-day TCI for both systems against the independent-AR floor |
| `fig4_h3_increment.png` | the identification ladder — which block earns the forecast gain |
| `fig5_granger_full8.png`, `fig5_granger_long7.png` | SPY-controlled Granger, both directions |
| `fig6_subperiods.png` | sub-period stability of the NPDC sign |

**Key numbers in the results JSON**

| Claim | JSON path |
|---|---|
| verdicts | `verdicts.{H1,H2,H2R_post_hoc,H3,H4}.verdict` |
| plain-language reading | `synthesis` |
| TCI + null floor | `networks.<sys>.h1_total_spillover` |
| pairwise NPDC + FDR | `networks.<sys>.h2_pairwise` |
| ordering audit | `ordering_robustness.<sys>` |
| sub-periods | `networks.<sys>.subperiods` |
| Granger | `granger_lead_lag.<sys>` |
| forecast ladder | `h3_forecast.fdr_by_rung`, `h3_forecast.cells[].ladder` |
| lookahead probe | `lookahead_diagnostics` |
| per-ticker coverage | `ticker_coverage` |

---

## 11. References

- Diebold, F.X. & Yilmaz, K. (2012). *Better to give than to receive.* IJF 28(1), 57–66.
- Diebold, F.X. & Yilmaz, K. (2014). *On the network topology of variance decompositions.*
  J. Econometrics 182(1), 119–134.
- Koop, G., Pesaran, M.H. & Potter, S.M. (1996). J. Econometrics 74(1), 119–147.
- Pesaran, H.H. & Shin, Y. (1998). *Generalized impulse response analysis in linear multivariate
  models.* Economics Letters 58(1), 17–29.
- Clark, T.E. & West, K.D. (2007). *Approximately normal tests for equal predictive accuracy in
  nested models.* J. Econometrics 138(1), 291–311.
- Benjamini, Y. & Hochberg, Y. (1995). JRSS-B 57(1), 289–300.
- Parkinson, M. (1980). J. Business 53(1), 61–65.
- Garman, M.B. & Klass, M.J. (1980). J. Business 53(1), 67–78.
- Politis, D.N. & Romano, J.P. (1994). *The stationary bootstrap.* JASA 89(428), 1303–1313.
- J.P. Morgan (2026), alternatives outlook — AI data-centre financing shifting from public to
  private markets (motivating source, `research_program.md` line 606).
- Prior K-series: K628b, K865b, K907, K1508, K1332, K1343, K1344, K1499, K195, K1701.
