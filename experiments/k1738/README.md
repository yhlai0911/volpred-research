# K1738 — Earnings Surprise (SUE) and Subsequent Realized Volatility: A Causal-Increment Test via DML (+ IV falsification)

**Status**: pre-registered design (this section written and committed **before** any estimate was inspected)
**Seed**: 42
**Owner**: dispatch slot-1 worktree `k1738-slot1-9783132d`
**Reserved K-id**: K1738 (`storage/ops/k_id_registry.json`, claimed 2026-07-19)

---

## 1. What this experiment asks — and what it deliberately does *not* ask

**This is not a forecasting experiment.** The repo already holds a family of experiments asking
"does signal X predict next-month realized volatility out-of-sample?" That question is answered with
pseudo-OOS loss comparisons (QLIKE/MSE, DM tests).

**This experiment asks a different question**: conditional on a rich confounder set, does earnings
surprise carry a *causal increment* to subsequent realized volatility — i.e. would an intervention
that moved a firm's SUE, holding its pre-announcement state fixed, change its realized vol over the
following 1–3 months?

The distinction matters because the naive association is almost certainly confounded. Firms with
volatile fundamentals have (a) noisier earnings, hence larger |SUE|, and (b) higher future realized
vol — for reasons that have nothing to do with the surprise itself. A raw regression of future RV on
SUE therefore recovers mostly a *firm-type* effect, not a *surprise* effect. The entire point of this
experiment is to measure how much of the raw association survives the controls, and to report that
gap as the headline.

**Source of the question**: JFE 2025–26 event-driven causal inference; the application of causal ML
(DML) to earnings-driven volatility is a gap in the applied literature.

### Estimand

The average treatment effect (ATE) of standardized unexpected earnings on the log of annualized
realized volatility over the 1, 2, and 3 months following the announcement, in a partially linear
model

  `log RV_{i,q,h} = θ_h · SUE_{i,q} + g(X_{i,q}) + ε_{i,q}`

θ_h is reported as the change in log RV per treatment unit on the firm historical-surprise scale
(not one pooled-sample SD), and is also translated into a
percentage change in volatility (`exp(θ) − 1`).

### Identification stance (declared up front)

We attempt IV identification and **expect it to fail** (§6). If it fails the pre-registered exclusion
test, the reported θ̂ is identified only under **unconfoundedness / selection-on-observables**, and the
conclusion is stated as a **conditional association** — "the part of the SUE–vol relation that is not
explained by the observed confounder set" — **not** as an established causal effect. Downgrading is
the expected outcome, not a failure of the experiment.

---

## 2. Data

### 2.1 Universe
A fixed, hard-coded list of currently-listed US large/mid-cap tickers spanning all 11 GICS sectors
(the list is a literal constant in `K1738.py` so the sample is reproducible and does not drift with
index membership). No dynamic index-membership scraping.

### 2.2 Earnings
`yfinance.Ticker.get_earnings_dates(limit=100)` returns, per firm, up to 100 quarterly rows with:
- **`Earnings Date`** — the *announcement* timestamp (tz-aware, America/New_York), **not** the fiscal
  period end. This is the event anchor.
- **`EPS Estimate`** — analyst consensus EPS prior to the announcement.
- **`Reported EPS`** — actual EPS.

Because a consensus estimate is available, **SUE here is analyst-based**, matching the standard
definition in the literature — *not* a seasonal-random-walk proxy. (A seasonal-RW fallback was
budgeted for in the task brief but proved unnecessary; had it been used, this README would have said
so explicitly and the estimand would have been labelled a proxy.)

Yahoo caps `limit` at 100 quarters (≈25 years); observed coverage runs back to ~2001–2005 per firm.

### 2.3 Prices
`yfinance` daily OHLCV, auto-adjusted, from 2000-01-01. Realized volatility is computed from daily
close-to-close log returns.

### 2.4 Macro (FRED)
Fetched keyless from `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<ID>`:
- `VIXCLS` (CBOE VIX close)
- `T10Y2Y` (10y−2y Treasury term spread)
- `BAA10Y` (Baa corporate − 10y Treasury credit spread)

**`NFCI` is deliberately excluded.** Per the repo's K1655 lesson, NFCI was first published in 2011 and
its earlier history is a *backcast*; using it as a control on pre-2011 observations would import
values that did not exist at the time, and NFCI is additionally subject to retroactive revision. The
three series above are market-price-based and are not revised, so a final-vintage download equals the
real-time vintage for them. This sidesteps the whole revision/vintage class of error rather than
patching around it.

---

## 3. Variable construction

### 3.1 Treatment

Primary (**D1, signed**):

  `SUE_{i,q} = (ReportedEPS_{i,q} − EPSEstimate_{i,q}) / σ̂_{i,q}`

where `σ̂_{i,q}` = standard deviation of the raw surprises `(Reported − Estimate)` over the firm's
**previous 8 announcements** (quarters q−8 … q−1), requiring ≥6 non-missing. Using only prior
announcements makes the scaling point-in-time; using the firm's own surprise history makes SUE
scale-free and immune to share-split re-statements of the EPS units (numerator and denominator carry
the same units). Pooled winsorization at the 1st/99th percentiles.

Secondary (**D2, magnitude**): `|SUE_{i,q}|`, winsorized identically.

Both treatment definitions are declared here, before results, and both enter the multiple-testing
family (§7). They are continuous, not discretized.

### 3.2 Outcome

`Y_{i,q,h} = log( annualized realized volatility of daily log returns over trading days [r+1, r+H_h] )`

with `H_1 = 21`, `H_2 = 42`, `H_3 = 63` trading days (≈1/2/3 months) and `r` = the reaction day (§4).
Annualization by `sqrt(252)`. A window is kept only if ≥80% of its trading days have valid returns.

Log RV is the pre-registered outcome scale (RV is strongly right-skewed; log is the standard
transform and makes θ a proportional effect). Level-RV is reported as a robustness spec.

**The reaction day itself is excluded from the primary window** (window starts at `r+1`). Including it
would make the finding near-tautological: a large surprise mechanically produces a large
announcement-day price jump, which mechanically inflates that window's RV. The economically
interesting question is whether elevated volatility *persists beyond the immediate repricing*. The
inclusive window (starting at `r`) is reported as a robustness spec so the mechanical component is
visible rather than hidden.

### 3.3 Confounders X

All measured from data through trading day **t0 − 1**, where t0 is the announcement calendar date —
strictly before the announcement, uniformly, regardless of BMO/AMC (§4).

| # | Variable | Rationale |
|---|---|---|
| 1–3 | log RV over past 21 / 63 / 252 trading days | **the** first-order confounder: volatile firms have noisier earnings *and* higher future vol |
| 4 | log RV_21 − log RV_252 (vol trend) | vol regime direction |
| 5–6 | cumulative return past 21d / 252d | leverage effect, momentum |
| 7 | log mean dollar volume past 63d | size/liquidity proxy, computable point-in-time (shares outstanding from yfinance is a current snapshot and is therefore **not** used) |
| 8–9 | lagged SUE and lagged |SUE| (prior quarter) | persistent earnings-surprise process |
| 10 | log σ̂ (the SUE scaling denominator) | earnings uncertainty level — separates "surprise" from "surprise-prone firm" |
| 11 | log VIXCLS at t0−1 | market vol regime |
| 12 | T10Y2Y at t0−1 | macro/term structure regime |
| 13 | BAA10Y at t0−1 | credit conditions |
| 14 | log SPY RV_21 at t0−1 | market realized vol regime |
| 15 | days since prior announcement | reporting-lag irregularity (delays signal trouble) |
| 16–17 | year fraction, calendar quarter | secular trend, seasonality |
| 18+ | sector one-hot | industry vol level |

### 3.4 Clustering

Firm-quarter observations announced in the same month share market-wide shocks, and repeated
observations of the same firm are serially dependent. Per the repo's K1355 rule (stacked entity-day
samples must not be treated as iid), **all** standard errors — naive, OLS-controls, DML, and IV — are
**two-way clustered by firm and by announcement year-month** (Cameron–Gelbach–Miller:
`V = V_firm + V_month − V_firm∩month`, with an eigenvalue floor at 0 for PSD repair).

---

## 4. Lookahead policy (binding)

This is the highest-priority risk in this design, and the announcement-date/fiscal-period-end
distinction is where it bites.

1. **Announcement date ≠ fiscal quarter end.** The event anchor is Yahoo's *announcement timestamp*.
   The fiscal period-end date is never used to time anything, anywhere in the code. Anchoring on
   period-end would be a look-ahead of 2–8 weeks, because the earnings number is not public then.
2. **Reaction day `r`.** Yahoo's announcement timestamp carries an hour. If hour ≥ 16:00 ET (after
   market close, the common case) the news is impounded on the **next** trading day, so `r` = next
   trading day after t0. If hour < 09:30 ET (before open), `r` = t0 itself (or the next trading day if
   t0 is not a trading day). Any other/ambiguous hour is treated as after-close (**conservative**:
   pushes the window later, never earlier).
3. **Confounders** use data through trading day **t0 − 1**, uniformly. For an after-close announcement
   the t0 session is in fact pre-news and would be legitimate to use; we forgo it so that a wrong
   hour field in Yahoo's record cannot create a look-ahead.
4. **Outcome window starts at `r + 1`** (primary) — strictly after the announcement in every case.
5. **The SUE denominator** `σ̂` uses only the previous 8 announcements, all strictly earlier.
6. **FRED series** are as-of t0−1 using **backward fill only** (last observation on or before t0−1).
   No interpolation, which would pull future values backward.
7. **Mechanical enforcement**: `test_k1738.py` asserts, on the realized panel, that (a) every outcome
   window start index exceeds the announcement trading-day index, (b) no confounder window overlaps
   any outcome window, (c) the SUE denominator for each row is computable from strictly-prior rows,
   and (d) a deliberately shifted-forward control variable is rejected by the same guard.

Equivalent of the repo's `signal.shift(1)` requirement: every feature window ends at `t0−1` and every
label window begins at `r+1 ≥ t0+1`, so the feature/label gap is ≥ 2 trading days by construction.

---

## 5. Estimators

Naive OLS, controlled OLS, and DML use the identical common sample and two-way clustered SE. The IV
diagnostic is restricted to rows with prior-sector-peer coverage and therefore reports its own n.

1. **Naive** — OLS of `Y_h` on `D` and a constant. No controls. *This is the number the "SUE predicts
   vol" framing implicitly reports.*
2. **OLS-controls** — OLS of `Y_h` on `D` and X entered linearly.
3. **DML (primary)** — Chernozhukov et al. partially linear model with cross-fitting:
   - `K = 5` folds, **`GroupKFold` by firm**, so no firm's observations appear in both the nuisance-
     training fold and the fold where its residuals are used. Nuisance functions and the effect are
     never estimated on the same data — this is the sample-splitting requirement.
   - Nuisance learners: `HistGradientBoostingRegressor` for both `ĝ(X) = E[Y|X]` and `m̂(X) = E[D|X]`.
     A Lasso-based variant is reported as a robustness spec.
   - Orthogonal (Neyman-orthogonal, partialling-out) score:
     `θ̂ = Σ ṽ ỹ / Σ ṽ²`, with `ṽ = D − m̂(X)`, `ỹ = Y − ĝ(X)`, both out-of-fold.
   - **5 repetitions** with different split seeds (base 42). Reported θ̂ is the median across
     repetitions; variance uses the Chernozhukov median adjustment
     `σ̂²_med = median_s{ σ̂²_s + (θ̂_s − θ̂_med)² }`, so split uncertainty is included rather than hidden.
   - Cluster-robust variance from the influence function
     `ψ_i = ṽ_i (ỹ_i − θ̂ ṽ_i) / mean(ṽ²)`, two-way clustered as in §3.4.
   - Cross-fitting holds out whole firms. Because the panel is crossed, ordinary K-fold partitions
     cannot simultaneously keep both firms and announcement months disjoint: nuisance-training rows
     can share a month with held-out firms. Two-way clustering handles score dependence but does not
     turn that nuisance fit into a multiway cross-fit. This is an explicit limitation, and the result
     remains a conditional association pending a multiway-cross-fit replication.
4. **IV / 2SLS** — see §6. Reported for transparency; interpreted causally **only** if it passes the
   pre-registered exclusion test, which we expect it not to.

The **naive vs OLS-controls vs DML** contrast is the primary deliverable: it shows how much of the
raw association is confounding.

**Common estimation sample.** The three primary contrast estimators, all horizons and both treatment
definitions run on one identical sample: rows with complete confounders **and** all three outcome
horizons available. Letting
each horizon keep its own maximal sample would confound "the effect changes with horizon" with "the
sample changes with horizon", which is precisely the comparison this experiment exists to make.

---

## 6. Instrument, and the pre-registered test that decides whether we may use it

**Candidate instrument** `Z_{i,q}` = the mean SUE of *other* firms in the same sector that announced in
the 30 calendar days **before** firm i's announcement.

- *Relevance argument*: intra-industry information transfer — a sector's early reporters shift what is
  effectively achievable and expected for later reporters, moving the focal firm's realized surprise.
  Relevance is testable and we report the first-stage F.
- *Exclusion argument, and why we distrust it*: for Z to be a valid instrument, sector-peer surprises
  must affect the focal firm's future volatility **only through the focal firm's own SUE**. This is
  implausible on its face — industry-wide news raises uncertainty about every firm in the sector
  directly, through demand, input costs, regulation and common discount-rate shocks. Exclusion is
  the fragile link, exactly as the brief anticipates.

**Pre-registered decision rule (fixed before estimation):** include Z in the *outcome* equation
alongside D and the full X. If Z's direct coefficient has **|t| > 1.96** (two-way clustered) at any
horizon, the exclusion restriction is declared **violated**, the instrument is declared **invalid**,
and the 2SLS estimates are reported as a labelled diagnostic that is **not** interpreted causally.

We will not search over alternative instruments until one passes. Instruments considered and rejected
*a priori*, with reasons, so the absence of a search is auditable:

| Candidate | Why rejected before testing |
|---|---|
| Lagged own SUE | Earnings uncertainty is persistent, so lagged SUE affects future vol directly. Exclusion fails by construction. |
| Analyst forecast dispersion / revision staleness | Not available in yfinance history at all. Infeasible, not merely invalid. |
| Announcement day-of-week / calendar timing | Relevance is essentially zero; a weak instrument would bias 2SLS toward OLS while looking exotic. |
| Weather / natural-experiment shocks | No firm-level linkage plausible at this frequency. |

If no instrument survives, the honest output is a pure-DML result under unconfoundedness with the
conclusion **downgraded to conditional association**. Per the brief, that is an acceptable and
expected deliverable — it is strictly more honest than manufacturing a weak instrument.

---

## 7. Multiple testing

- **Family F1 (primary)**: {3 horizons} × {signed SUE, |SUE|} = **6 hypotheses**, per estimator.
  Benjamini–Hochberg FDR at **q = 0.10**. Both raw p and BH-adjusted q are recorded in the results
  JSON, and both the pre-correction and post-correction verdicts are reported.
- **Family F2 (secondary)**: {3 horizons} × {3 sub-periods} for signed-SUE DML = **9 hypotheses**,
  BH-corrected **separately** (it is a distinct family, and mixing it into F1 would dilute the primary
  test).
- Robustness specs (level-RV outcome, inclusive window, Lasso nuisance, within-month demeaning) are
  **descriptive sensitivity checks, not additional confirmatory tests**, and are reported without FDR
  membership. They cannot promote a NULL to a PASS; they can only demote (§8).

## 7.1 Sub-periods (repo cross-period rule)

- **P1 2002-01 – 2009-12** (dot-com aftermath + GFC bear)
- **P2 2010-01 – 2017-12** (post-GFC expansion)
- **P3 2018-01 – 2026-07** (2018 Q4 selloff, COVID 2020 crash, 2022 bear)

Each sub-period contains at least one bear market, satisfying the repo's long-sample requirement.

---

## 8. Success criteria — **written before any result was inspected**

- **PASS** — all of:
  1. signed-SUE DML effect BH-significant (q < 0.10 within F1) in **≥2 of 3** horizons;
  2. the point estimate has the **same sign across all 3** horizons;
  3. the same sign in **all 3** sub-periods;
  4. survives the within-announcement-month-demeaned robustness spec with the same sign and q < 0.10
     in ≥1 horizon.
- **CONDITIONAL_PASS** — BH-significant in ≥1 horizon but at least one of conditions 2–4 fails; or the
  effect appears only for |SUE| and not for signed SUE.
- **NULL** — no BH-significant DML effect at any horizon for either treatment definition. **This is a
  fully acceptable and informative outcome**: it would say the raw SUE–vol association is explained by
  the observed confounder set, with no measurable increment.
- **FAIL** — an integrity defect (look-ahead, coverage collapse, non-reproducibility) makes the
  estimates uninterpretable.
- **INSUFFICIENT_DATA** — any of: fewer than **500** usable firm-quarter observations; fewer than **30**
  firms; fewer than **20** distinct announcement quarters; or SUE coverage below **30%** of
  firm-quarters with an announcement record.

A PASS is additionally **capped at CONDITIONAL_PASS in its interpretation** whenever the instrument
fails the §6 exclusion test — statistical significance under unconfoundedness does not license a
causal claim. The verdict field records both.

**No criterion in this section may be edited after results are inspected.** Post-hoc exploration, if
any, is reported in a clearly separated `exploratory` block in the results JSON and never described as
pre-registered.

---

## 9. Known limitations, declared in advance

1. **Survivorship bias.** The universe is currently-listed firms; delisted/acquired firms are absent.
   Expected direction: **attenuation toward the null** — firms that failed had both the largest
   negative surprises and the highest realized vol, and dropping them removes the most influential
   observations. This makes a positive finding conservative and a NULL finding slightly less
   informative. Not correctable with yfinance.
2. **Consensus is not a true archived vintage.** Yahoo's stored `EPS Estimate` is a current snapshot of
   the pre-announcement consensus rather than a timestamped vintage, and `Reported EPS` may embed
   later restatements. Standardizing by the firm's own prior surprise dispersion neutralizes unit and
   split-adjustment drift but not restatement. This is the single largest data-quality caveat and is
   why the SUE definition is documented as "analyst-based, non-vintage".
3. **Sector labels** come from a current yfinance snapshot; a firm reclassified mid-sample carries its
   current label throughout.
4. **No credible instrument** (expected, §6) → identification rests on unconfoundedness. Unobserved
   drivers correlated with both SUE and future vol (e.g. private information about operating
   fragility) would still bias θ̂. Stated as conditional association.
5. **Overlapping outcome windows.** At h = 3 months (63 trading days ≈ one quarter) consecutive
   announcements for the same firm produce nearly-adjacent, occasionally overlapping windows. Firm-
   level clustering absorbs the resulting serial dependence; no additional HAC correction is applied
   because the clustering is at the level of the dependence.

---

## 10. Artifacts

- `K1738.py` — the bounded cached-continuation entrypoint (seed 42). It requires `--no-download`,
  verifies the frozen checkpoint/panel identities, estimates only the missing DML stages, and writes
  the final results plus runtime `reproduce_spec.json`.
- `K1738_results.json` — byte-traceable output. **Every number in this README's results discussion and
  in the return summary is read from this file; none is typed by hand.**
- `test_k1738.py` — lookahead guards, construction invariants, estimator sanity checks.
- `panel_k1738.parquet` — the constructed firm-quarter panel (cached; enables re-estimation without
  re-downloading).
- `review_verdict.json` — produced by `scripts/experiment_gates.py verdict-template`, filled by the
  reviewer. Never hand-authored.

## 11. Results

See `K1738_results.json`; the `verdict` field there is authoritative. Section 12 below is generated mechanically from that file by `render_readme_results.py`.

## 12. Results as run (generated from `K1738_results.json` — no figure typed by hand)

**Verdict: `CONDITIONAL_PASS`** — BH-significant at signed=['h1m', 'h2m'] abs=[] but failed pre-registered condition(s): ['c3_sign_consistent_across_subperiods']

> CAPPED: no credible valid instrument, so every estimate is interpreted as a conditional association under unconfoundedness, never as a causal ATE.

Sample: **24,519 firm-quarters**, 292 firms, 97 quarters, 2001-08-14 to 2026-04-30, 279 distinct announcement months. Constructible-SUE coverage of frozen announcement records in-span: 92.3% (24,884/26,954).

Treatment: Yahoo analyst-estimate-based SUE proxy (current snapshot, non-vintage; NOT a seasonal-random-walk proxy) — `(ReportedEPS - ConsensusEPSEstimate) / std(prior 8 announcement surprises)`.

### 12.1 The headline contrast: naive vs OLS-controls vs DML

Effect on **log** realized vol per 1 treatment unit. A SUE unit is the firm's historical-surprise scale; it is not the pooled estimation-sample SD. `q` is Benjamini–Hochberg-adjusted within the 6-hypothesis family F1.

**Signed SUE (primary)**

| horizon | naive OLS | OLS + controls | DML | DML 95% CI | raw p | BH q | vol change / treatment unit |
|---|---|---|---|---|---|---|---|
| 1m | -0.0146 | -0.0075 | **-0.0042** | [-0.0071, -0.0014] | 0.003653 | 0.01096 | -0.42% |
| 2m | -0.0136 | -0.0074 | **-0.0040** | [-0.0065, -0.0015] | 0.001809 | 0.01085 | -0.40% |
| 3m | -0.0101 | -0.0060 | **-0.0023** | [-0.0047, +0.0001] | 0.066 | 0.132 | -0.23% |

Share of the naive association absorbed by linear controls: 1m 49%, 2m 45%, 3m 41%.
Share absorbed by cross-fitted DML nuisance adjustment: 1m 71%, 2m 70%, 3m 78%.

**|SUE| (secondary)**

| horizon | naive OLS | OLS + controls | DML | DML 95% CI | raw p | BH q | vol change / treatment unit |
|---|---|---|---|---|---|---|---|
| 1m | +0.0084 | +0.0010 | **+0.0024** | [-0.0011, +0.0058] | 0.1758 | 0.211 | +0.24% |
| 2m | +0.0080 | -0.0003 | **+0.0011** | [-0.0017, +0.0040] | 0.4392 | 0.4392 | +0.11% |
| 3m | +0.0097 | +0.0005 | **+0.0025** | [-0.0004, +0.0054] | 0.08957 | 0.1344 | +0.25% |

Share of the naive association absorbed by linear controls: 1m 88%, 2m 104%, 3m 95%.
Share absorbed by cross-fitted DML nuisance adjustment: 1m 72%, 2m 86%, 3m 74%.

### 12.2 Multiple testing (family F1 = 3 horizons × 2 treatment definitions)

| estimator | significant at raw p<0.05 | significant after BH (q<0.10) |
|---|---|---|
| naive_ols | 4/6 | 6/6 |
| ols_controls | 3/6 | 3/6 |
| dml | 2/6 | 2/6 |

### 12.3 Sub-period stability (signed SUE, DML; family F2)

Each cell is θ (BH q within the 9-cell F2 family).

| sub-period | n | 1m | 2m | 3m |
|---|---|---|---|---|
| P1_2002_2009 | 6,124 | +0.0005 (q=0.8433) | -0.0004 (q=0.8433) | -0.0011 (q=0.7634) |
| P2_2010_2017 | 8,661 | -0.0071 (q=0.01855) | -0.0062 (q=0.01855) | -0.0040 (q=0.08695) |
| P3_2018_2026 | 9,732 | -0.0044 (q=0.04075) | -0.0043 (q=0.03916) | -0.0020 (q=0.3732) |

### 12.4 Robustness (within-month = confirmatory F3; others descriptive)

| spec | 1m | 2m | 3m |
|---|---|---|---|
| within_month_demeaned | -0.0034 (q=0.01825) | -0.0033 (q=0.01425) | -0.0018 (q=0.1273) |
| inclusive_window | -0.0032 | -0.0037 | -0.0029 |
| level_rv_outcome | -0.0012 | -0.0014 | -0.0008 |
| lasso_nuisance | -0.0087 | -0.0074 | -0.0058 |

### 12.5 Instrument

Candidate instrument: mean SUE of other same-sector firms announcing in the prior 30 calendar days (n = 23,519).

- **Relevance**: first-stage coefficient +0.1478, cluster-robust F = 31.78 (not weak by the F<10 rule of thumb).
- **Exclusion test** (pre-registered: |t| > 1.96 on the instrument in the controlled outcome equation ⇒ invalid):
  - h1m: coefficient -0.0121, t = -1.79, p = 0.07281 → does not reject exclusion
  - h2m: coefficient -0.0107, t = -1.63, p = 0.1021 → does not reject exclusion
  - h3m: coefficient -0.0077, t = -1.20, p = 0.2287 → does not reject exclusion

**Instrument valid: `False`.** INVALID -- the candidate has plausible direct industry-news pathways to the outcome. The pre-registered direct-effect diagnostic is reported unchanged, but its non-rejection does not establish exclusion. 2SLS is a transparency diagnostic only and is NOT interpreted causally.

2SLS estimates (invalid-IV transparency diagnostic only; never causal):

| horizon | 2SLS | 95% CI | raw p |
|---|---|---|---|
| 1m | -0.0895 | [-0.1699, -0.0091] | 0.0291 |
| 2m | -0.0798 | [-0.1607, +0.0011] | 0.05334 |
| 3m | -0.0582 | [-0.1382, +0.0219] | 0.1546 |

### 12.6 Pre-registered criteria, applied verbatim

- `c1_bh_significant_in_ge2_horizons`: **True**
- `c2_sign_consistent_across_horizons`: **True**
- `c3_sign_consistent_across_subperiods`: **False**
- `c4_survives_within_month_fe`: **True**
- `significant_horizons_signed`: **['h1m', 'h2m']**
- `significant_horizons_abs`: **[]**
- `subperiods_evaluated`: **True**
- `within_month_fe_evaluated`: **True**
- `statistical_verdict_before_iv_cap`: **CONDITIONAL_PASS**

_Generated from `K1738_results.json` (code sha256 `a1add225764e563a…`, runtime 458s, last checkpoint `complete`)._
