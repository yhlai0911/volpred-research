# K1679 — Does deposit flight FROM regional banks predict regional-bank volatility?

**Verdict: NULL** (mildly negative). A regional-bank-specific deposit-flight
signal — the small-minus-large bank deposit growth differential from FRED H.8 —
adds **no robust incremental out-of-sample forecasting power** over a HAR baseline
for KRE forward realized volatility or downside semivariance, at H = 5 or H = 21,
before or after multiple-testing correction. The few near-significant cells point
the *wrong* way (the signal marginally *increases* forecast error) and none
survives FDR.

---

## 0. Read this first — relation to K1606

K1606 asked essentially the same economic question with the **aggregate** deposit
series `DPSACBW027SBOG` (deposits at **all** commercial banks) on KRE forward RV at
H = 5, 2015–2026, HAR baseline. It found NULL (DM t = −0.382, p = 0.703). K1606's
own *Limitations* section named the follow-up explicitly:

> "DPSACBW027SBOG is total-system deposits, not deposits *at regional banks*; a
> regional-bank-specific or uninsured-only deposit series (if obtainable) could
> carry different content. This is the natural follow-up if bank-level or
> call-report data becomes available."

That series **is** obtainable without FFIEC call reports: FRED's H.8 release breaks
deposits out by charter size.

| Series | Definition |
|---|---|
| `DPSSCBW027SBOG` | Deposits, **Small** Domestically Chartered Commercial Banks (weekly, SA, 1973+) |
| `DPSLCBW027SBOG` | Deposits, **Large** Domestically Chartered Commercial Banks (weekly, SA, 1985+) |

The **small-minus-large deposit growth differential** is a direct measure of deposits
fleeing regional/community banks for the G-SIBs — precisely the funding-flight channel
the hypothesis is about, and precisely what happened in March 2023. K1679 therefore is
**not** a rerun of K1606. It differs on three declared axes:

1. **Predictor** — regional-bank-specific small−large differential, vs K1606's all-bank aggregate level.
2. **Targets / horizons** — adds forward **downside semivariance** (funding fragility is a left-tail story) and **H = 21**, vs K1606's symmetric RV at H = 5 only.
3. **Sample** — **2007–2026** (includes the GFC deposit-stress regime), vs K1606's 2015+.

The HAR baseline, Parkinson RV proxy, lookahead policy, canonical QLIKE and seed = 42
are kept identical in spirit to K1606 so the two are directly comparable. **No
cross-sectional / bank-level uniqueness claim is made** — this is a systematic
time-series test of a size-cohort deposit differential.

---

## 1. Motivation and literature

The RFS "bank deposits and the stock market" line argues that when the stock market
booms, households shift deposits into equities, thinning bank funding and raising
funding fragility — a channel that should be sharpest for deposit-funded regional
banks. The March-2023 episode (SVB, Signature, First Republic) was a textbook run in
which deposits fled small banks for the perceived safety of the G-SIBs. If that
funding-flight channel carries **forward-looking** information, the small−large deposit
differential should lead KRE's realized volatility and left-tail risk. This is the
VolPred funding-risk-proxy candidate: if it predicts, it becomes a regional-bank
volatility-regime filter; if it is null, that is itself a publishable, decision-relevant
null (K1606 established the aggregate version was null; K1679 tests the sharper,
size-specific version K1606 could not).

---

## 2. Data

| Source | Series | Freq | Handling |
|---|---|---|---|
| FRED H.8 | `DPSSCBW027SBOG` (small-bank deposits) | weekly (Wed) | +10-day publication embargo |
| FRED H.8 | `DPSLCBW027SBOG` (large-bank deposits) | weekly (Wed) | +10-day publication embargo |
| yfinance | `KRE` (regional-bank ETF), `XLF`, `SPY`, `^VIX` | daily | `auto_adjust=True` |

- **1,109** usable weekly deposit observations feed the signal.
- **Modelling window: 2007-01-03 → 2026-07-02** (KRE inception 2006-06; a lead-in is
  used for the HAR(22) and 52-week z-score terms).
- **OOS: 2018-09-11 → 2026-07-02**, 1,962 forecast origins at H = 5 (1,956 at H = 21).
- VIX control was available and used.

### Publication-lag handling (the load-bearing lookahead defence)

H.8 is a **released report**, so the date a deposit figure refers to is **not** the date
it can be traded on. H.8 reports the prior-Wednesday balance sheet on the following
Friday (~8-day lag). We set `available_date = as_of_date + 10 calendar days` (the 8-day
lag plus a 2-day buffer, and strictly more conservative than K1606's +9d), so a deposit
observation is only ever usable on a session that **opens after** its release. The daily
merge is `merge_asof(direction="backward")` on `available_date`. A mechanical assertion
in every grid cell verifies that the minimum gap between any trading day and the as-of
date of the deposit value it used is **≥ 10 days** (observed minimum in the run: 12 days).

---

## 3. Signal construction

```
dep_flight_Nw = − z( logΔ_N(small deposits) − logΔ_N(large deposits) )
```

with the z-score computed on a **trailing 52-week** window (only past data). `N ∈ {4, 13}`
weeks. Sign convention (same spirit as K1606): **high = stress** — deposits contracting at
small banks relative to large banks pushes the differential very negative, so `−z` is large
and positive.

**Construct validity (the reason the null is credible).** If this differential is a real
measure of regional-bank deposit flight, it must spike in the known runs. It does:

| Episode | Max 13-week signal | Date |
|---|---|---|
| March-2023 regional-bank stress | **+4.16** | 2023-03-27 |
| GFC (2008-09 → 2009-06) | **+3.20** | — |

So the null below is **not** an artifact of a broken or flat signal — the signal
correctly identifies both regional-bank deposit-run episodes. It simply carries no
*exploitable, forward-looking* content beyond what HAR already knows.

---

## 4. Method

- **Target.** Forward-mean quantity over the strictly-future window `(t, t+H]`:
  `y_t = mean(q_{t+1..t+H})`, computed as `q.rolling(H).mean().shift(-H)`.
  - `rv`: Parkinson (high-low) daily variance.
  - `dsv`: daily **downside semivariance** `min(log-return, 0)²`.
- **Baseline (HAR).** OLS: `1 + q_d + q_w + q_m` on the target quantity (Corsi 2009),
  **plus** a SPY 21-day RV control and a VIX-level control.
- **Augmented.** Baseline **+ the deposit-flight signal**. The only difference between the
  two models is that one column; timing, embargo and controls are otherwise identical.
- **OOS scheme.** Expanding window, **refit at every origin** by SVD least squares
  (`np.linalg.lstsq`; we deliberately do *not* accumulate normal equations, because the
  collinear HAR terms would square an already-large condition number). Initial train = 60%.
- **Forward-label embargo.** At origin `i` the model trains only on rows `j` with
  `j + H < i`, purging the overlap between training labels and the forecast target. A
  mechanical check asserts this holds for every origin.
- **Positivity floor.** OLS in variance *levels* can emit a negative variance forecast.
  Each forecast is floored at the **minimum positive forward variance in its own training
  window** (strictly in-sample, no future leak), applied identically to both models. This
  replaces a naïve 1e-16 floor — see §6.
- **Loss.** Pre-declared per target: `rv → QLIKE` (canonical
  `actual/pred − log(actual/pred) − 1`, imported from
  `volpred.stats.model_evaluation.qlike_pointwise`, never hand-written);
  `dsv → MSE` (downside semivariance has structural zeros at short H where QLIKE's log
  term is undefined — QLIKE is reported as a secondary diagnostic with the zero count
  disclosed).
- **Test.** Diebold-Mariano with Newey-West HAC at **truncation lag = H** (each horizon
  gets its own inference horizon — no shared HAC lag) **and** the
  Harvey-Leybourne-Newbold (1997) small-sample correction, compared against `t(n−1)`.
  Negative t ⇒ deposit-augmented model better. Harvey (2016) bar: |t| > 3.
- **Bootstrap.** Moving-block bootstrap (block = max(10, H), 2,000 reps, seed 42) on the
  primary-loss differential as an overlap-robust second check.
- **Multiple testing.** The **pre-registered** primary family is 2 predictors × 2 targets
  × 2 horizons = **8 tests**. Bonferroni and Benjamini-Hochberg are applied over that
  family; raw and adjusted p-values are both reported.
- **Falsification (secondary, declared, not in the FDR family).** The same 13-week signal
  is run on **XLF** (large-bank-heavy financials) and **SPY** (broad market). If the
  differential were really about *regional-bank* funding, it must not work equally well
  there.
- **seed = 42** everywhere.

---

## 5. Results

### Primary grid — KRE (all 8 pre-registered cells, significant or not)

| predictor | target | H | primary loss | base | aug | improv. % | DM t (HLN) | p raw | p Bonf. | BH q |
|---|---|---|---|---|---|---|---|---|---|---|
| dep_flight_13w | rv  | 5  | QLIKE | 0.2698 | 0.2810 | −4.17 | +0.633 | 0.527 | 1.00 | 0.60 |
| dep_flight_13w | rv  | 21 | QLIKE | 0.1957 | 0.2085 | −6.58 | +0.661 | 0.509 | 1.00 | 0.60 |
| dep_flight_13w | dsv | 5  | MSE   | 3.92e-7 | 3.93e-7 | −0.16 | +1.154 | 0.249 | 1.00 | 0.50 |
| dep_flight_13w | dsv | 21 | MSE   | 2.19e-7 | 2.19e-7 | +0.08 | −0.097 | 0.923 | 1.00 | 0.92 |
| dep_flight_4w  | rv  | 5  | QLIKE | 0.2698 | 0.2775 | −2.86 | +0.698 | 0.485 | 1.00 | 0.60 |
| dep_flight_4w  | rv  | 21 | QLIKE | 0.1957 | 0.2564 | −31.04 | +1.722 | 0.085 | 0.68 | 0.34 |
| dep_flight_4w  | dsv | 5  | MSE   | 3.92e-7 | 3.93e-7 | −0.08 | +1.773 | 0.076 | 0.61 | 0.34 |
| dep_flight_4w  | dsv | 21 | MSE   | 2.19e-7 | 2.20e-7 | −0.29 | +1.447 | 0.148 | 1.00 | 0.39 |

- **Every DM t is positive except one** (which is essentially zero): the deposit signal
  makes forecasts **worse or no better**, never reliably better. It is not a helpful predictor.
- **No cell reaches |t| = 1.96** (raw), let alone the Harvey |t| = 3 bar.
- **No cell survives** Bonferroni (min = 0.61) **or** BH-FDR at q = 0.10 (min q = 0.34).
- Strongest cell (`dep_flight_4w · dsv · H5`, p = 0.076 raw): its moving-block bootstrap CI
  on the loss differential is **[+2.4e-11, +6.5e-10]** — entirely *positive*, i.e. the
  bootstrap agrees the signal marginally *raises* error. The economic magnitude is nil
  (dsv MSE change −0.08%).

### Falsification — XLF / SPY (declared secondary, not FDR-corrected)

All 8 secondary cells are also null (largest |t| = 1.79 on SPY·dsv·H5, p = 0.074, wrong
direction). Nothing spuriously "works" on the broad market either, which is consistent
with the primary null being a true absence of signal rather than a mis-specified test.

### Figures (real matplotlib PNGs from the live run)

- `K1679_fig_signal_vs_forward_rv.png` — top: the 13-week deposit-flight signal (red)
  spiking at GFC and SVB against KRE forward 21-day RV (blue); bottom: the raw
  signal / future-vol scatter, **Spearman ρ = 0.006 (p = 0.688, n = 4,889)** — no
  contemporaneous relationship.
- `K1679_fig_dm_grid.png` — the whole pre-registered primary grid; no bar reaches ±1.96.

---

## 6. A numerical bug we caught and fixed (honesty note)

A first run floored negative variance forecasts at `1e-16`. OLS-in-levels occasionally
emits a negative forward-variance forecast; against a real RV of ~2.5e-4, a 1e-16 floor
makes that single QLIKE point ~1e12 and dominate the mean loss. That inflated the QLIKE
DM t-stats (e.g. rv·H5 read t = 1.61 instead of the correct 0.63) — a numerical artifact,
not signal. The fix (floor each forecast at the min positive forward variance in its own
training window, leak-free, both models identically) removed the artifact. The null is
robust either way — the MSE-primary `dsv` cells were never affected, and even the
distorted QLIKE pointed the wrong way — but the reported QLIKE numbers are now the clean ones.

---

## 7. Conclusion (honest, evidence-bounded)

Supplying the **bank-size-specific** deposit series that K1606 said it lacked does **not**
rescue K1606's null. A validated regional-bank deposit-flight signal — one that correctly
spikes in both the GFC and the March-2023 run — carries **no robust incremental
out-of-sample forecasting content** for KRE forward realized volatility or downside
semivariance over a HAR baseline, at either horizon, before or after FDR, and on both
the ETF and its falsification benchmarks.

**Interpretation.** By the time size-cohort H.8 deposit data is public (after the
publication embargo), the deposit-flight information is already impounded in regional-bank
prices; HAR's own autoregressive structure already captures the volatility clustering
around deposit-stress episodes. A slow, weekly, publicly-released deposit aggregate — even
the regional-specific one — does not add daily-frequency forecasting content. The
funding-flight channel is real in the *cross-section during* a run (as March-2023 showed),
but it is **not an exploitable time-series lead signal** from public H.8 data.

**Not a strategy candidate.** This closes the aggregate/size-cohort branch of the
funding-flight proxy. A genuine test of the hypothesis would need **bank-level** or
**uninsured-deposit-share** data (FFIEC call reports), which price behaviour around
idiosyncratic runs — not H.8 aggregates — would drive.

---

## 8. Limitations

- **Still an aggregate, not bank-level.** The small/large split is by charter size, not a
  regional-bank-specific or uninsured-only series. The genuine cross-sectional
  uninsured-deposit-share hypothesis needs FFIEC call-report data, unavailable here.
- **Publicly-released data only.** The whole exercise is bounded by what a public,
  lagged H.8 aggregate can carry; it says nothing about proprietary or higher-frequency
  deposit-flow data.
- **RV proxy.** Parkinson high-low variance and daily downside semivariance; realized
  5-minute RV was not used (unavailable free for this ETF at this history).
- **OLS-in-levels HAR** with a training-min positivity floor (see §6); a log-variance HAR
  would avoid the floor entirely but the null at the primary spec is already unambiguous.

---

## 9. Reproduce

```bash
uv run python experiments/K1679/K1679.py
```

Deterministic given `seed = 42`; requires `FRED_API_KEY` in `.env.local` and live
yfinance access. Emits `K1679_results.json` + two PNGs. Every number in this README comes
from that live run; nothing is hand-entered. Each statistic in the JSON carries `n_obs`,
`sample_start`, `sample_end`, `p_value`, `p_value_adjusted`, and `hac_lag`.

## 10. Files

- `K1679.py` — the experiment (pre-registered grid, lookahead assertions, DM-HLN, BH-FDR).
- `K1679_results.json` — full byte-traceable results (primary + secondary + construct check).
- `K1679_fig_signal_vs_forward_rv.png`, `K1679_fig_dm_grid.png` — figures.

---

## 11. Code review status (2026-07-11, main-thread + Codex)

**Verdict: FAIL — directional NULL stands but is NOT yet knowledge-grade; a revision is required before writing to `knowledge.json`.**

Codex review confirmed the hard checks that matter most: the forward-label OOS
embargo `j + H < i` is genuinely enforced (`j_end = i - H - 1`), each cell uses
its own H as the HAC/HLN truncation lag, the QLIKE direction is canonical, the
8-cell Bonferroni/BH-FDR is computed correctly, construct validity holds (signal
spikes +4.16 at SVB, +3.20 at GFC), and `seed = 42` is fixed. The README BH-q
column was corrected on 2026-07-11 to match the JSON (6/8 cells were off; the
stated "min q = 0.26" was wrong, the true minimum is 0.34 — the conclusion that
no cell survives q = 0.10 is unchanged).

Three substantive issues block knowledge-grade status:

1. **Point-in-time data (lookahead).** The H.8 deposit series is pulled from the
   *current* FRED vintage, not ALFRED point-in-time vintages. H.8 is revised, so
   the pseudo-OOS uses hindsight-revised values that were not available at the
   trading date. For a NULL this is *hindsight-favorable* to the signal (revised
   data is cleaner), so it makes the null conservative rather than obviously
   spurious — but it is not a clean point-in-time test.
2. **Nested-model inference (most important for a NULL).** The baseline HAR is
   fully nested in the augmented model, yet the test is standard DM/HLN. Standard
   DM on nested models is biased toward *not* rejecting — i.e. biased toward the
   null. A Clark–West (2007) style test on the strongest cells
   (`dep_flight_4w · dsv · H5`, `dep_flight_4w · rv · H21`) is required before the
   null can be trusted; it could move the strongest cell.
3. **Floor sensitivity.** The training-min positivity floor (leak-free for
   RV/QLIKE) is also applied to DSV/MSE cells that admit exact zeros; the
   strongest cell had ~50/53 obs clipped. Needs an unclipped-loss sensitivity run.

Revision tracked as a follow-up task (ALFRED point-in-time H.8 + Clark–West on
nested strongest cells + unclipped floor sensitivity). Until that passes review,
K1679 is a *provisional* directional null and is intentionally absent from
`knowledge.json`.
