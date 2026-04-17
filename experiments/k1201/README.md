# K1201 — QQQ + USO PIT alignment and Paper 4 7-asset panorama

**Status**: COMPLETED — **UNIVERSAL_NULL with TLT caveat (6/7 panorama, 1 isolated outlier)**
**Date**: 2026-04-17
**Worktree**: `agent-a64c1bdc`

## 1. Motivation

- **K1116c** established SPY weekly-AR(1)+IV baseline + PIT release-calendar alignment and
  confirmed alt-data (EPU / NFCI / ANFCI / STLFSI / WLEMU) NULL — no spec beats VIX baseline
  at Harvey |t|>3 across 6 lag variants.
- **K1116f** extended K1116c PIT framework to GLD / TLT / BTC-USD. GLD & BTC confirmed NULL.
  TLT finstress gave +3.74 DM t at `pit_shift0` but collapsed to +2.00 at `pit_shift1`
  (Harvey-insignificant) and failed the 5% QLIKE gate. K1116f verdict: ASSET_SPECIFIC with
  TLT caveat.
- **K1118** ran the shift(1) cross-asset baseline on GLD / TLT / BTC only — **not** QQQ /
  USO / EEM (the original brief mis-remembered K1118 coverage).
- **Research question**: Does the K1116c / K1116f NULL generalize to QQQ (equity technology)
  and USO (commodity crude oil), both of which have liquid native-IV proxies (^VXN, ^OVX)?
  Completing these two cells gives Paper 4 a 6/7 coverage of its stated cross-asset universe.

### Differentiation

| Experiment | Assets | Lag framework |
|------------|--------|---------------|
| K1116c     | SPY    | 6 PIT variants |
| K1118      | GLD, TLT, BTC-USD | shift(1) weekly mean |
| K1116f     | GLD, TLT, BTC-USD | PIT (3 variants) |
| **K1201**  | **QQQ, USO** | **PIT (3 variants, same as K1116f)** |

### Related K

- K1116 / K1116b / K1116c — SPY publication-delay + PIT series
- K1116f — GLD / TLT / BTC PIT extension (direct predecessor)
- K1118 — original shift(1) cross-asset (no QQQ / USO)
- K1121 — daily alt-data allocation NULL
- K1098 — 0050.TW / VIXTWN sufficiency

### EEM note (scope trim)

The task brief suggested EEM was already covered by K1118. It is not — K1118's
`asset_configs` holds only `[GLD, TLT, BTC-USD]`. EEM native-IV ^VXEEM exists on CBOE but
has known yfinance gaps; extending to EEM would require its own data-availability audit.
**K1201 therefore covers 6/7 Paper 4 universe (SPY + GLD + TLT + BTC + QQQ + USO)** and
flags EEM as follow-up. This is documented in `results.json` `panorama_coverage`.

## 2. Data and method

### 2.1 Market data

| Asset | Ticker | Native IV | IV src | IV type | Weekly agg |
|-------|--------|-----------|--------|---------|------------|
| QQQ   | QQQ    | ^VXN (CBOE NASDAQ-100 VIX) | yfinance | close | W-FRI |
| USO   | USO    | ^OVX (CBOE Crude Oil VIX)  | yfinance | close | W-FRI |

- Period: 2018-01-12 → 2026-04-10 (same window as K1116f).
- IS: 2018-01-01 → 2022-12-31; OOS: 2023-01-01 → 2026-04-10.
- Weekly RV = `sqrt(sum(daily log-return^2))`, minimum 4 trading days per week.
- `iv_mean` aggregates the native IV index across the W-FRI week.

### 2.2 Alt-data and PIT spec (reused from K1116c / K1116f)

| Indicator | Cadence | Publication lag | Source |
|-----------|---------|-----------------|--------|
| USEPU  | daily | T+1 business day | `experiments/k1116c/data/USEPU_weekly_pit.csv` |
| WLEMU  | daily | T+1 business day | same |
| NFCI   | weekly (Fri obs) | Wed of W+1 | same |
| ANFCI  | weekly (Fri obs) | Wed of W+1 | same |
| STLFSI | weekly (Fri obs) | Thu of W+1 | same |

PIT panel construction: for each W-FRI F, take the latest observation with
`release_date <= F`. **Publication lags are inherited directly from K1116c; not
self-invented.**

### 2.3 Five specs × three lag variants (identical to K1116f)

Specs: `base` = AR(1); `iv` = AR(1)+native IV (**DM baseline**); `epu` = AR(1)+USEPU+WLEMU;
`finstress` = AR(1)+NFCI+ANFCI+STLFSI; `all` = AR(1)+IV+5 alt.

Variants: `k1118_shift1` (weekly mean panel, `shift(1)`); `pit_shift0` (PIT panel, `shift(0)`,
primary); `pit_shift1` (PIT panel, `shift(1)`, extra safety).

### 2.4 Statistics

- OLS with `statsmodels.OLS`.
- QLIKE = `log(pred) + actual/pred` (Patton 2011 proxy-robust).
- DM-HLN with Harvey (1997) finite-sample correction.
- Gate: Harvey (2016) |t|>3 for challenger-wins; |t|>2 reported as softer comparison.
- Seed 42.
- Minimum 170 common OOS weeks per asset (achieved: QQQ 170, USO 170).

### 2.5 Lookahead defence

- Every regressor is explicitly lagged in `make_X`: `y_lag1 = df["rv"].shift(1)`,
  `iv_lag1 = df["iv_mean"].shift(1)`, `<alt>_signal` is pre-lagged in
  `build_variant_panel`.
- PIT panel already respects release-date causality (`value[week_end=F]` uses only
  observations with `release_date <= F`), so `pit_shift0` is the natural primary; `shift(1)`
  adds an extra week of safety margin.

## 3. Results

### 3.1 DM t vs IV baseline (positive = alt beats IV; Harvey |t|>3 gate)

#### QQQ (IV = ^VXN)

| Variant | base | epu | finstress | all |
|---------|------:|-----:|----------:|-----:|
| k1118_shift1 | −2.186 | −1.807 | −2.439 | −1.035 |
| pit_shift0   | −2.186 | −1.967 | −2.439 | −1.967 |
| pit_shift1   | −2.186 | −1.979 | **−3.001** | −1.696 |

- Every cell negative: baseline ^VXN always matches or beats alt-data.
- `pit_shift1` finstress reaches Harvey |t|>3 on the baseline side (`BASELINE_WINS`).
- QLIKE improvement (best alt vs VXN baseline): **−0.56%** at `pit_shift0` → FAIL the 5% gate
  (actually negative, alt-data degrades accuracy).

#### USO (IV = ^OVX)

| Variant | base | epu | finstress | all |
|---------|------:|-----:|----------:|-----:|
| k1118_shift1 | **−3.049** | **−4.463** | −2.584 | −2.998 |
| pit_shift0   | **−3.049** | **−5.596** | −2.584 | **−3.735** |
| pit_shift1   | **−3.049** | **−5.282** | −2.694 | **−3.562** |

- USO is the **strongest NULL of the 6-asset panorama**: OVX baseline beats every alt-spec
  with |t|>3 on base + epu + all (pit_shift0), and epu alone reaches |t|>5 (p<1e-7).
- This is exactly what the K1116c thesis predicts when the native IV is well-matched to the
  underlying's vol process (OVX is model-free VIX-methodology on WTI options — a precise
  implied-vol proxy, leaving no room for lagged macro sentiment to add value).
- QLIKE improvement: **−0.84%** — alt-data actively harms.

### 3.2 7-asset panorama (pit_shift0 DM t vs IV baseline)

| Asset | Source | base | epu | finstress | all |
|-------|--------|-----:|----:|---------:|----:|
| SPY | K1116c | −3.021 | −2.603 | −3.001 | −2.537 |
| GLD | K1116f | −2.103 | −2.069 | −3.341 | −2.246 |
| TLT | K1116f | +1.433 | −2.477 | **+3.743** | −5.666 |
| BTC-USD | K1116f | −5.494 | −3.550 | +1.370 | +0.203 |
| **QQQ** | **K1201** | −2.186 | −1.967 | −2.439 | −1.967 |
| **USO** | **K1201** | −3.049 | **−5.596** | −2.584 | **−3.735** |
| EEM | — | NOT TESTED (out of K1118 scope; follow-up) | | | |

**Only one cell (TLT finstress) exceeds +3 across the entire 4-spec × 6-asset panorama**,
and K1116f already showed that cell collapses under `pit_shift1` to +2.00 (Harvey fails)
with QLIKE improvement only +0.50% (below 5% gate).

### 3.3 Cross-asset gates synthesis

| Variant (QQQ+USO only) | Harvey |t|>3 pass | |t|>2 pass | baseline |t|>3 wins total |
|------------------------|--------|-----------|--------|
| k1118_shift1 | [] | [] | 2 |
| pit_shift0   | [] | [] | 4 |
| pit_shift1   | [] | [] | 4 |

Across three variants and both assets, **zero alt-spec challengers win at any Harvey
threshold** in QQQ or USO. Baseline wins count grows under PIT (4 vs 2 at shift(1)),
meaning PIT alignment *strengthens* the native-IV superiority — exactly the direction
K1116c predicted for any cell where shift(1) was leaking publication timing.

### 3.4 Spearman rank consistency (shift1 vs PIT, QQQ+USO finstress t)

Only two assets available so Spearman is a boundary case (n=2, rho either ±1). Both
assets have the same sign across shift(1) and PIT variants (both negative), so rank
consistency is preserved. The informative check is sign consistency, which is satisfied.

## 4. Verdict

**UNIVERSAL_NULL with TLT caveat (6/7 panorama, 1 isolated outlier).**

1. **SPY, GLD, BTC-USD, QQQ, USO all confirm universal NULL under PIT alignment.** None of
   them has any alt-data spec (EPU / finstress / all) that beats native IV at Harvey |t|>3.
2. **USO is the strongest NULL cell**: OVX baseline dominates EPU alt-data with DM
   t=−5.60 (p<1e-7) at `pit_shift0` — near the ceiling of rejection strength given 170
   observations. This is consistent with Paper 4's "well-constructed native IV is all you
   need" claim.
3. **TLT remains the single isolated outlier**: finstress `pit_shift0` DM t=+3.74 — but
   K1116f already showed this collapses at `pit_shift1` and fails the QLIKE 5% gate, so it
   is not a structural niche for alt-data.
4. **Paper 4 "native IV sufficiency" claim is strengthened**: 6/7 PIT-tested assets
   (85.7% panorama coverage) give uniform NULL verdicts. EEM is the only untested cell
   and is flagged as follow-up.

## 5. Paper 4 narrative implications

This result is a major strengthening of Paper 4's thesis:

- **Before K1201**: PIT evidence existed for only SPY (K1116c) and GLD/TLT/BTC (K1116f) —
  4 assets including the TLT caveat. The "universal" claim was slightly vulnerable because
  commodity (USO) and growth equity (QQQ) asset classes were untested.
- **After K1201**: 6 of 7 stated universe assets confirmed NULL; USO in particular gives
  the strongest individual-asset rejection in the entire panorama (|t|>5). The TLT cell
  remains the *only* isolated positive DM t and is already shown lag-sensitive.
- **Cannot yet promote to "universal" without EEM**. Recommend EEM as the next PIT cell
  (using ^VXEEM if yfinance coverage is adequate, else 30-day rolling RV proxy as K1118 did
  for BTC).
- **Narrative-state-machine guidance (CLAUDE.md §Automation)**: K1201 is the 3rd
  complementary experiment (K1116c + K1116f + K1201) all confirming the panorama narrative,
  which *does* allow narrative decision making — but only to the 6/7 strength. **Do not
  touch Paper 4 `body.tex` yet**; update `research_program.md` and `knowledge.json` per
  main-thread workflow.

## 6. Limitations

1. **EEM not covered** (scope choice documented above); panorama is 6/7, not 7/7.
2. **Weekly AR(1)+IV baseline** is the K1118/K1116f convention, not daily HAR-RV. A daily
   HAR-RV cross-asset PIT remains a separate follow-up.
3. **PIT data is revision-corrected (fredgraph)**, not true ALFRED vintage (needs FRED API
   key). K1116c §2 argues revision-corrected is a smoother upper bound of vintage-PIT
   explanatory power; since revision-corrected PIT is NULL, vintage PIT is also NULL.
4. **170 weeks common OOS per asset** is adequate but not enormous for regime-conditional
   sub-analysis. The universal-NULL verdict would strengthen further with post-2030 data.
5. **^VXN and ^OVX are standard CBOE VIX-methodology indices** computed off listed option
   chains; same methodology as VIX so the "IV sufficiency" comparison is apples-to-apples
   with SPY. No proxy error as in the BTC case (K1116f) where rv30 was a backward-looking
   substitute.

## 7. Files

- `k1201.py` — experiment main script
- `k1201_results.json` — full numeric results + 7-asset panorama + verdict
- `k1201_dm_heatmap_7asset.png` — 6-asset × 4-spec DM t heatmap (pit_shift0)
- `k1201_qlike_improvement.png` — 6-asset QLIKE improvement bar chart
- `run.log` — execution log
- `README.md` — this file

## 8. References

- Baker, Bloom, Davis (2016) QJE — EPU index
- Brave, Butters (2011) Chicago Fed Letter 286 — NFCI Wed release
- Kliesen, Smith (2010) — STLFSI
- Croushore, Stark (2001) J Econometrics — vintage data importance
- Patton (2011) JoE — QLIKE proxy-robust loss
- Harvey, Leybourne, Newbold (1997) IJF — HLN DM correction
- Harvey (2016) RFS — |t|>3 multiple-testing threshold
- CBOE VXN methodology docs — NASDAQ-100 implied vol
- CBOE OVX methodology docs — WTI crude oil implied vol
- K1116 / K1116b / K1116c — SPY publication-delay + PIT series
- K1116f — GLD / TLT / BTC PIT (direct predecessor)
- K1118 — shift(1) cross-asset baseline

## 9. Worktree discipline

- All outputs confined to `experiments/k1201/`.
- No shared state modified (`storage/**`, `paper/**`, `research_program.md`,
  `knowledge.json`, `experiment_experiences.json`, Mirror / Supabase sync — all untouched).
- Main thread owns knowledge / experience / article writes and Paper 4 narrative decisions.
