# K1589 — Reinsurer / cat-bond carrier vol dose-response to Atlantic hurricane landfall

## Motivation

Catastrophe-exposed reinsurers and cat-bond underwriters (RNR, EG, ACGL, AXS)
carry idiosyncratic windstorm risk. Existing finance literature documents
*level* responses of insurance equity prices to disaster shocks (Born & Viscusi
2006; Lamb 1995) and pricing dynamics in catastrophe-bond spreads (Froot 2001;
Lane & Mahul 2008). What is less explored is whether the *Saffir-Simpson
category* of an Atlantic hurricane at landfall produces a graded
**volatility** response in individual reinsurer stocks — a dose-response
relation in second-moment space rather than first.

VolPred's K-series does not currently contain hurricane / cat-bond / weather
event work (`grep` over `knowledge.json` returns 0 matches for
`hurricane|landfall|cat bond|reinsurer`). K1589 fills that gap with a
narrow, event-study-style design that asks: *after controlling for
market-wide vol shock, does landfall category move reinsurer-specific
RV?*

If a true dose-response exists, then (i) cat-event regime detection becomes
a candidate volatility strategy, and (ii) the result earns a section in a
weather-risk paper alongside the cat-bond pricing literature.

## Method

### Data sources

- **Hurricane events**: NOAA HURDAT2 Atlantic basin best-track database,
  cached at `data/hurdat2.txt` (downloaded 2026-06-30). One record per
  storm: the **first** landfall record (`record_id == 'L'`) at hurricane
  intensity (Cat 1+, ≥ 64 kt sustained 1-min wind). Saffir-Simpson
  category derived from the wind speed at that landfall record (kt → cat
  via standard thresholds 64/83/96/113/137).
- **Equity / index data**: `yfinance` auto-adjusted daily close
  2009-09-01 → 2025-01-15, cached at `data/prices.csv`. Tickers:
  - Reinsurers: **RNR** (RenaissanceRe), **EG** (Everest Group — renamed
    from Everest Re "RE" in 2023-06; yfinance backfills under EG to
    2010), **ACGL** (Arch Capital Group — note that "ARCH" on yfinance is
    Arch Resources, an unrelated coal name), **AXS** (AXIS Capital).
  - Sanity baseline: **KIE** (SPDR S&P Insurance ETF).
  - Controls: **SPY** (market), **^VIX** (macro vol regime).

### Outcome construction

Annualized realized volatility from daily log returns over each window:

```
RV(window) = std(log_return[window]) * sqrt(252)
ΔRV_i,e    = RV_post_i,e − RV_pre_i,e
```

- `t0`: first trading day ≥ HURDAT2 first-landfall date.
- **Pre-event RV**: 21 trading-return observations ending at the last
  trading date ≤ `t0 − 6 calendar days`. This preserves the 21-day RV
  scale while keeping landfall-week price action out of the baseline.
- **Event (post) RV**: 5 trading-return observations starting one
  trading day after `t0`.
- **Controls**: VIX uses last close strictly before `t0`; SPY control is
  21-day SPY RV ending strictly before `t0`. No post-event market
  information enters controls.
- Lookahead: pre window is strictly before the landfall week; post window
  is strictly after `t0`. The event-study has no signal→outcome
  `signal.shift(1)` pairing because the "signal" is a historical exposure
  attached to a known event date, not a daily trading signal.

### Regression

For each outcome stock `i` (reinsurer ∪ KIE), pooled across events `e`:

```
ΔRV_i,e = α + β · Category_e + γ · VIX_{t-1} + δ · SPY_RV21_{t-1} + ε_{i,e}
```

- Events are sorted by landfall date before inference.
- HAC (Newey-West) standard errors, `maxlags = 10`, to absorb residual
  autocorrelation across overlapping or near-simultaneous chronological
  events.
- β is the dose-response slope — incremental ΔRV per Saffir-Simpson
  category step.
- **Multiple-testing**: Holm-Bonferroni across the 4 reinsurer outcome
  stocks only (`RNR`, `EG`, `ACGL`, `AXS`) for the β coefficient. `KIE`
  is treated as benchmark, not part of the reinsurer family.

### Identification check

The v2 benchmark test is a stacked panel:

```
ΔRV_{s,e} = α + β1 Category_e + β2 Reinsurer_s
            + β3 Category_e × Reinsurer_s
            + γ VIX_{t-1} + δ SPY_RV21_{t-1} + ε_{s,e}
```

`β3` is the formal reinsurer-minus-KIE dose-response difference. Standard
errors are clustered by event date. The descriptive reinsurer-mean β
minus KIE β is still reported, but it is not used as a pass/fail gate.

### Success criteria (pre-set)

| Criterion | Threshold | Achieved |
| --- | --- | --- |
| Any reinsurer β > 0 with Holm-4 p < 0.10 | required | ✅ |
| Formal reinsurer-minus-KIE interaction β > 0 with p < 0.10 | required | ❌ |
| N_events ≥ 12 | minimum | ✅ (42) |
| N_events ≥ 20 | preferred | ✅ (42) |

→ verdict_internal = **NULL**: individual-stock dose-response appears in
some reinsurers, but the formal KIE benchmark does not identify a
reinsurer-specific effect.

## Result summary

**N events**: 42 Cat 1+ Atlantic landfalls in 2010-2024, distributed as
Cat-1: 24, Cat-2: 5, Cat-3: 4, Cat-4: 6, Cat-5: 3.

**Per-stock dose-response coefficient β** (incremental ΔRV per
Saffir-Simpson category step, chronological HAC SE):

| Stock | β | SE | t | raw p | Holm-4 p |
| --- | ---: | ---: | ---: | ---: | ---: |
| RNR  | +0.0142 | 0.0109 | +1.30 | 0.195 | 0.195 |
| EG   | +0.0275 | 0.0143 | +1.92 | 0.055 | 0.137 |
| ACGL | +0.0323 | 0.0094 | +3.45 | 0.001 | 0.002 |
| AXS  | +0.0234 | 0.0117 | +2.00 | 0.046 | 0.137 |
| KIE  | +0.0197 | 0.0085 | +2.31 | 0.021 | n/a benchmark |

**Unconditional ΔRV means (no controls)**:

| Stock | pre RV mean | post RV mean | ΔRV mean |
| --- | ---: | ---: | ---: |
| RNR  | 0.212 | 0.215 | +0.003 |
| EG   | 0.218 | 0.227 | +0.009 |
| ACGL | 0.201 | 0.205 | +0.005 |
| AXS  | 0.219 | 0.209 | -0.010 |
| KIE  | 0.166 | 0.164 | -0.002 |
| SPY  | 0.133 | 0.127 | -0.006 |

**Identification check**:

- Descriptive reinsurer-mean β = +0.0243
- Descriptive KIE β = +0.0197
- Descriptive difference = +0.0046
- Formal stacked interaction β(reinsurer − KIE) = +0.0071,
  SE = 0.0142, t = 0.50, p = 0.615

## Interpretation

1. **There is a per-stock dose-response signal, but it is not uniquely
   reinsurer-specific.** ACGL survives Holm-4 at 10% and RNR/EG/AXS all
   have positive point estimates, but KIE also has a positive raw
   category slope.
2. **The formal KIE benchmark fails.** The stacked
   `Category × Reinsurer` interaction is positive but small relative to
   its clustered SE (p = 0.615). This means the data do not distinguish
   reinsurer-specific cat exposure from broad insurance-sector
   co-movement.
3. **Controls are now ex-ante.** VIX and SPY RV controls use only
   information strictly before `t0`, so the regression is no longer
   absorbing post-event market volatility through the v1 SPY post-minus-
   pre RV control.
4. **Power constraints.** Of 42 landfalls, only 13 are Cat 3+ — the
   regime that would plausibly trigger a reinsurer-specific second-moment
   response (where retro covers and cat-bond attachment points engage).
   The Cat-3+ subsample is too small for a clean Cat-3+ vs Cat-1/2
   subgroup test with HAC SEs.

**Bottom line**: K1589_v2 upgrades the methodology enough to trust the
NULL verdict. Hurricane category is associated with higher short-window
volatility in some insurance/reinsurance equities, but the evidence does
not identify a distinct reinsurer-specific effect beyond KIE.

## Limitations / failure modes worth noting

- **First-landfall-only**: multi-landfall storms (e.g., Irma 2017,
  Florida + Cuba) contribute only their first landfall record. A
  cumulative-exposure design (max landfall intensity per storm, or
  landfall-energy sum) might detect what category-of-first-landfall
  misses. Out of scope here; flagged for K1589-followup.
- **Stock-specific cat exposure varies**: AXS materially diversified
  away from US-windstorm exposure post-2018; RNR is the most cat-heavy
  remaining listed reinsurer. A more refined design would weight β by
  each carrier's published probable-maximum-loss (PML) for North
  Atlantic windstorm.
- **Implicit assumption of common slope across events**: a true dose-
  response with regime-dependence (Cat 4-5 only) would not show up in
  a linear-in-category specification. The 13-event Cat 3+ subset is
  small for a non-parametric check.
- **No Bayesian / random-effect shrinkage**: with only 42 events spread
  across 4 stocks, partial pooling could change the picture; not done
  here.
- **HURDAT2 wind-at-landfall is the at-record wind**: not the peak
  storm wind. Some major storms (e.g., Irma) had higher peak intensity
  offshore than at the first landfall record. A storm-peak-wind variant
  is an obvious robustness extension.

## Reproduction

```
uv run python experiments/k1589/k1589.py
```

Dependencies: `yfinance numpy pandas scipy statsmodels requests`.

Outputs to:
- `k1589_results.json` — full result object including events_used,
  regression coefficients, raw + Holm-4 adjusted p, RV diagnostics,
  formal KIE interaction test, success-criteria flags.
- `data/prices.csv` — cached price panel.
- `data/hurdat2.txt` — cached HURDAT2 file (committed for byte-level
  reproducibility; ~7 MB).

## Verdict

- `verdict_internal = NULL`
- **Reviewer (Codex primary path, v2): CONDITIONAL_PASS for methodology,
  NULL for hypothesis**
- The v2 code addresses the five prior blockers: chronological HAC,
  21-day/5-day RV alignment, ex-ante SPY control, Holm-4 scope, and a
  formal KIE interaction test.
- This can be reported as an honest null: some individual reinsurer
  slopes are positive and one survives Holm-4, but the formal benchmark
  test does not separate reinsurer-specific exposure from broad
  insurance-sector response.

## Related K-series

- None — first hurricane / weather-event vol entry in VolPred.

## References

- Born, P. & Viscusi, W.K. (2006). "The catastrophic effects of natural
  disasters on insurance markets." *Journal of Risk and Uncertainty*
  33(1-2), 55-72.
- Froot, K.A. (2001). "The market for catastrophe risk: a clinical
  examination." *Journal of Financial Economics* 60(2-3), 529-571.
- Lane, M.N. & Mahul, O. (2008). "Catastrophe risk pricing: an
  empirical analysis." World Bank Policy Research WP 4765.
- NOAA NHC HURDAT2 Atlantic best-track database,
  `https://www.nhc.noaa.gov/data/hurdat/`.
