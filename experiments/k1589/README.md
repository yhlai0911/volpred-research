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

- **Pre-event window**: trading rows whose dates fall in
  `[landfall_date − 30, landfall_date − 6]` calendar days. The strict
  `−6 day` upper bound prevents leak of landfall-week price action into
  the baseline (lookahead-safe).
- **Event (post) window**: the 10 trading days starting *one trading day
  after* the first trading day ≥ landfall date.
- Lookahead: pre window is strictly before landfall in calendar days;
  post window strictly after; VIX control uses last close strictly before
  `t0` (`close.index < t0`). No future info enters either window. The
  event-study has no signal→outcome `shift(1)` pairing because the
  "signal" is a historical exposure (Saffir-Simpson category) attached
  to a known past date, not a forecast made at `t` for `t+1`.

### Regression

For each outcome stock `i` (reinsurer ∪ KIE), pooled across events `e`:

```
ΔRV_i,e = α + β · Category_e + γ · VIX_{t-1} + δ · ΔSPY_RV_e + ε_{i,e}
```

- HAC (Newey-West) standard errors, `maxlags = 10`, to absorb residual
  autocorrelation across overlapping or near-simultaneous events.
- β is the dose-response slope — incremental ΔRV per Saffir-Simpson
  category step.
- **Multiple-testing**: Holm-Bonferroni across the 5 outcome stocks for
  the β coefficient. Both raw and Holm-adjusted p reported.

### Identification check

Reinsurer-mean β minus KIE β. The hypothesis only earns weight if
reinsurer-specific dose-response exceeds the broad-insurance ETF baseline
(else we've identified a sector-wide weather factor, not a
reinsurer-specific cat-exposure factor).

### Success criteria (pre-set)

| Criterion | Threshold | Achieved |
| --- | --- | --- |
| Any reinsurer β > 0 with Holm p < 0.10 | required | ❌ |
| Reinsurer-mean β > KIE β | required | ✅ (trivially, +0.0012) |
| N_events ≥ 12 | minimum | ✅ (42) |
| N_events ≥ 20 | preferred | ✅ (42) |

→ verdict_internal = **NULL** (only the trivial identification check
holds; the primary significance gate fails).

## Result summary

**N events**: 42 Cat 1+ Atlantic landfalls in 2010-2024, distributed as
Cat-1: 24, Cat-2: 5, Cat-3: 4, Cat-4: 6, Cat-5: 3.

**Per-stock dose-response coefficient β** (incremental ΔRV per
Saffir-Simpson category step, HAC SE):

| Stock | β | SE | t | raw p | Holm p |
| --- | ---: | ---: | ---: | ---: | ---: |
| RNR  | +0.0206 | 0.0177 | +1.16 | 0.246 | 0.986 |
| EG   | +0.0175 | 0.0189 | +0.93 | 0.355 | 0.986 |
| ACGL | +0.0145 | 0.0144 | +1.00 | 0.315 | 0.986 |
| AXS  | +0.0064 | 0.0158 | +0.41 | 0.685 | 0.986 |
| KIE  | +0.0135 | 0.0075 | +1.80 | 0.071 | 0.356 |

**Unconditional ΔRV means (no controls)**:

| Stock | pre RV mean | post RV mean | ΔRV mean |
| --- | ---: | ---: | ---: |
| RNR  | 0.216 | 0.230 | +0.014 |
| EG   | 0.224 | 0.233 | +0.009 |
| ACGL | 0.206 | 0.226 | +0.020 |
| AXS  | 0.223 | 0.226 | +0.003 |
| KIE  | 0.168 | 0.169 | +0.001 |
| SPY  | 0.132 | 0.131 | −0.001 |

**Identification check**:

- Reinsurer-mean β = +0.0148
- KIE β = +0.0135
- Difference = +0.0012 (positive but economically negligible)

## Interpretation

1. **Direction is right, magnitude is small and noisy.** All four
   reinsurers have positive point estimates of β (more intense storms →
   slightly more post-landfall vol), and the unconditional ΔRV means are
   uniformly positive while SPY's is ≈ 0. The signs are economically
   consistent.
2. **No reinsurer β survives Holm-adjusted significance.** Raw p
   range 0.25-0.69 for reinsurers. Only KIE is marginally significant raw
   (p = 0.07) and even that collapses after Holm correction (p = 0.36).
3. **Identification check passes only trivially.** Reinsurer mean β
   barely exceeds KIE β (Δ = +0.0012). Within standard error, the two
   are indistinguishable — meaning whatever weather-vol relation exists
   is shared across the broad insurance ETF, not specific to
   catastrophe-exposed reinsurers.
4. **Power constraints.** Of 42 landfalls, only 13 are Cat 3+ — the
   regime that would plausibly trigger a reinsurer-specific second-moment
   response (where retro covers and cat-bond attachment points engage).
   The Cat-3+ subsample is too small for a clean Cat-3+ vs Cat-1/2
   subgroup test with HAC SEs.

**Bottom line**: the dose-response hypothesis is **not rejected in
direction** but is **not supported by significance**. Idiosyncratic
reinsurer vol after Atlantic landfall is dominated by broader insurance-
sector and market-vol comovement once VIX and SPY ΔRV are controlled
for.

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
cd experiments/k1589
python3 k1589.py
```

Dependencies: `yfinance numpy pandas scipy statsmodels requests`.

Outputs to:
- `k1589_results.json` — full result object including events_used,
  regression coefficients, raw + Holm-adjusted p, RV diagnostics,
  identification check, success-criteria flags.
- `data/prices.csv` — cached price panel.
- `data/hurdat2.txt` — cached HURDAT2 file (committed for byte-level
  reproducibility; ~7 MB).

## Verdict

- `verdict_internal = NULL` (any_reinsurer_holm_p < 0.10 fails;
  identification only trivially passes)
- **Reviewer (Codex primary path, 2026-06-30 16:44): NEEDS_REVISION**
- This is a legitimate null finding in direction, but the inference
  pipeline has methodological issues that prevent a clean PASS. The null
  conclusion is **not yet** publication-grade; a K1589_v2 revision is
  queued to address the blockers below.

### Codex review blockers (must address in v2 before knowledge.json write)

1. **HAC chronological ordering (high)** — Newey-West lag structure
   requires events sorted by `landfall_date` (chronological), but the
   current pipeline sorts by `storm_id`. Result: HAC p-values not
   meaningful. Fix: sort by landfall date before HAC SE estimation.
2. **KIE identification not formally tested (high)** —
   `mean(reinsurer β) − KIE β = +0.0012` is a descriptive gap with no
   formal SE/interaction test. Replace with stacked panel + reinsurer
   dummy × category interaction, or downgrade KIE comparison to
   descriptive only.
3. **ΔSPY_RV control is ex-post (high)** — Control variable uses the
   post-event window, not a t<t0 observable. Replace with a t-1 SPY RV
   or other ex-ante control, or explicitly frame the estimand as
   ex-post abnormal vol (not deployable forecast).
4. **Holm multiple-testing scope (medium)** — Holm applied over 5
   outcomes including KIE; success criterion
   `any_reinsurer_beta_pos_holm_p_lt_0p10` loops over all `STOCKS`
   instead of the 4 reinsurers only. Fix scope.
5. **RV window misalignment with brief (medium)** — Brief asked for
   21-day baseline / 5-day event window; implementation produces 16-19
   trading-day pre window and 10-day post window. Either align the
   spec to the brief or document the trading-day implementation as
   deliberate and add a robustness check at the brief's nominal window.

### Honest interpretation (pending v2)

Direction-of-effect is consistent with intuition (all reinsurer β > 0
after VIX + SPY ΔRV controls) but the dose-response signal is not
statistically distinguishable from broader insurance-sector / macro-vol
comovement given the available 2010-2024 Atlantic landfall sample —
and even this null finding requires the v2 methodological fixes before
it can be reported with confidence.

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
