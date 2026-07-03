# K1611: Giacomini-White (2006) conditional predictive ability — is the HAR-RV vs GJR-GARCH winner regime-dependent?

## Motivation

Prior SPY/TAIEX HAR-RV vs GJR-GARCH horse races (K1049 / k1054 / k1057 / k1063)
report a **single full-sample winner** from an **unconditional Diebold-Mariano
(DM)** test. Giacomini & White (2006, *Econometrica* 74(6), 1545-1578) point out
that unconditional DM hides the possibility that **which** model forecasts better
depends on the market state. This experiment runs the GW **conditional predictive
ability test** with a lagged-VIX regime instrument to honestly test whether the
HAR-vs-GJR relative performance is **regime-dependent** rather than constant.

Contemporary forecast-evaluation work (JoE / JBES 2025-26) re-emphasises that
unconditional DM is a special case of conditional predictive ability and that
state-conditioning is essential for honest model selection — this K operationalises
that on the platform's canonical daily horse race.

## Differentiation vs prior K

| | prior K1049/k1054/k1057/k1063 | **K1611** |
|---|---|---|
| test | unconditional DM only | **GW (2006) conditional** + DM baseline |
| sample | 5-min RV, 28-60 days (PRELIMINARY) | daily proxy, **1,212-4,156 OOS days** |
| state split | none | lagged-VIX high/low regime instrument |
| proxy | 5-min RV / r² | **r² (primary) + range+overnight (robust)**, pure-Parkinson excluded with a documented proxy-bias finding |

The task brief forbade the 5-min RV file (`data/intraday/SPY_daily_rv.csv`, only
118 rows / 60 days — far below the ≥500 needed for a regime split).

## Data

- **SPY** OHLC 2005-01-03 .. 2026-07-01 (yfinance, `auto_adjust=True`); regime
  instrument `^VIX` (yfinance). Close-to-close returns are clean (0 impossible
  moves). OOS 2009-12-21 .. 2026-07-01 (n=4,156), crossing the 2020 COVID crash
  and 2022 bear.
- **0050.TW** OHLC, restricted to the **clean post-break window 2014-01-06 ..
  2021-12-31**; regime instrument = 台指VIX (VIXTWN daily, archived at
  `experiments/k1098/k1098_vixtwn_daily.csv`, 2007-2021 — the canonical
  `data/vixtwn/vixtwn_daily.csv` only holds a rolling 140-day recent window, too
  short for a regime split). OOS 2017-01-10 .. 2021-12-30 (n=1,212), crossing the
  2018 vol spikes and the 2020 COVID crash.

### Data-integrity handling (process fix, not a data patch)

yfinance's raw 0050.TW series carries **vendor data errors**: (a) a spurious
adjustment break at **2014-01-02** (adjusted close 37.41 → 9.33 overnight, a
−139% "return", price then stays ~9.2), and (b) **six 2009 rows with |return| >
±7%** — impossible under Taiwan's ±7% daily price limit (±10% after 2015-06). In
the first draft this single 2014-01-02 bad tick poisoned the GJR variance
recursion for a whole month (α·ε² with ε≈139σ), produced a catastrophic one-day
QLIKE differential that dominated the entire cumulative series, drove a **spurious
"robust regime-dependent" verdict**, and even made the results **non-reproducible**
(CSV round-trip float noise flipped that knife-edge day). Fixes:

1. `0050.TW` sample starts **after** the break (2014-01-06); SPY needs no
   trimming (clean).
2. `assert_price_limit()` **aborts** if any used-sample return exceeds the
   exchange price limit (SPY 25% bad-tick guard, 0050 11% price limit).
3. `GJR_DISC_TOL` **aborts** if the manual GJR one-step recursion diverges from
   `arch.forecast(horizon=1)` beyond 5e-3 (catches bad-tick-poisoned fits;
   post-fix discrepancy is machine-epsilon 3e-16 for both assets).

Result is now bit-for-bit reproducible (identical MD5 across runs).

## Variance proxy (Patton 2011 proxy-robust QLIKE)

Both proxies are conditionally **unbiased for the close-to-close variance** that
BOTH HAR (fit on the proxy) and GJR (fit on close-to-close returns) target, so the
QLIKE ranking is proxy-robust and the race is **fair to GJR**:

- **PRIMARY `r²`** — squared close-to-close log return (canonical, noisy; matches
  the k1049/k1054/k782 convention).
- **ROBUST `rsov`** — Parkinson intraday range variance + squared overnight log
  return. Less noisy on the intraday component while still capturing overnight;
  unbiased for close-to-close variance under a drift-free intraday diffusion and
  an overnight jump uncorrelated with the intraday range.

**Pure Parkinson is EXCLUDED from the race** (kept diagnostic-only). It omits the
overnight jump → biased LOW for close-to-close variance → mechanically penalises
the close-to-close GJR forecast and **spuriously inflates DM in favour of the
proxy-matched HAR**. Diagnostic evidence (`proxy_level_diagnostic`, OOS means,
pct²):

| asset | r² | rsov | pure Parkinson | GJR forecast | Parkinson / r² |
|---|---|---|---|---|---|
| SPY | 1.170 | 1.186 | 0.708 | 1.207 | 0.61 |
| 0050.TW | 1.113 | 1.059 | 0.490 | 1.046 | 0.44 |

Pure Parkinson captures only 44-61% of close-to-close variance (on the earlier
bad-tick-inflated 0050 sample, only ~5%), while r²/rsov/GJR agree — confirming the
overnight-omission bias. In the first draft, using pure Parkinson as the primary
proxy produced an absurd **|DM t| = 49** (0050), the classic "too good = bug"
artifact. **Methodological lesson: a daily variance-forecast horse race must use a
close-to-close-consistent proxy; naive intraday range proxies are invalid against
a close-to-close GARCH forecast.**

All quantities in pct² (returns / log-ranges ×100), consistent with GJR variance.
`auto_adjust=True` OHLC are vendor total-return-adjusted; log-ratios embed only the
current-date (known ex-div) dividend → no lookahead.

## Models

- **HAR-RV** RV_t = β0 + β_d·RV_{t-1} + β_w·mean(RV_{t-1:t-5}) + β_m·mean(RV_{t-1:t-22}),
  expanding OLS refit each day. Every feature is an explicit `shift(1)` lag; the
  design row predicting RV_t uses only RV_{t-1..t-22}, and the training set for day
  t is rows j with target RV_j observed at j ≤ t-1 (target_end < forecast_origin).
  Forecast clamped to [1%, 1000%] of the training-mean RV (k1054 convention).
- **GJR-GARCH(1,1)** normal innovations on daily percent returns, **monthly refit**
  (compute control). The one-step forecast σ²_t is produced by the **exact GJR
  variance recursion** σ²_t = ω + (α + γ·1{ε_{t-1}<0})·ε²_{t-1} + β·σ²_{t-1} with
  the month's fixed params, seeded from arch's last in-sample conditional variance.
  σ²_t is F_{t-1}-measurable and **target-aligned to proxy_t by construction**
  (K445 hard rule — no origin/target off-by-one), and cross-validated against
  `arch.forecast(horizon=1)` at every refit day.

## Tests

- **QLIKE** canonical `actual/predicted − log(actual/predicted) − 1` (K783c) via
  `volpred.stats.model_evaluation.qlike_pointwise`. d_t = QLIKE_HAR,t − QLIKE_GJR,t
  (positive → GJR better).
- **Unconditional DM** in two variants: one-step MDS + HLN small-sample correction
  (L=0), and **HAC-DM** (Newey-West, data-driven Bartlett lag — the conservative
  variant, since QLIKE losses cluster). Harvey (2016) |t|>3 bar.
- **GW (2006) conditional test** h_{t-1} = [1, regime_{t-1}], z_t = h_{t-1}·d_t,
  S = n·z̄'Ω̂⁻¹z̄, Ω̂ = HAC (Bartlett, not demeaned — under H0 E[z]=0), S ~ χ²(2).
  Reported at HAC and L=0 (MDS) bandwidths. **A df=2 rejection means the models are
  NOT conditionally equivalent (E[d]=0 and E[regime·d]=0 jointly fail); it does NOT
  by itself mean the winner flips with the regime.** Implementation cross-validated
  against the equivalent [low,high] orthogonal-basis closed form (exact match) and
  against synthetic null/regime cases (correct size and power).
- **Regime-slope test** d_t = a + b·regime_{t-1} + e_t, HAC se on b — the **direct**
  test of regime-dependence (b≠0 ⇔ loss differential differs by regime). Proxy-robust
  sign + significance of b is the **gate** for any "regime-dependent" verdict.
- **Regime subsample decomposition** mean d_t / winner / DM in high vs low regime.

### Regime instrument (lookahead-free)

regime_{t-1} = 1{VIX_{t-1} > expanding_median(VIX_{0..t-1})} — lagged VIX vs an
**expanding (past-only) median**, strictly F_{t-1}-measurable. A full-sample-median
split is reported as secondary robustness only.

## Lookahead policy (all defended)

- HAR: explicit `shift(1)` on every feature; training rows satisfy target_end <
  forecast_origin.
- GJR: exact one-step recursion, σ²_t is F_{t-1}-measurable, target-aligned;
  monthly refit on returns[:origin] (info through t-1); cross-validated vs arch.
- Regime instrument: **lagged** VIX (t-1) vs **expanding** (past-only) median.
- Per-asset only (SPY and 0050 fully separate — **no asset-day pooling**, K1355).
- `seed = 42`.

## Results (primary proxy = r²; HAC bandwidth = conservative)

| asset | proxy | n OOS | QLIKE HAR / GJR | uncond DM (HAC t, p) | GW χ² (HAC, p) | regime-slope b (t, p) | high-reg mean d (win) | low-reg mean d (win) |
|---|---|---|---|---|---|---|---|---|
| SPY | r² | 4156 | 1.765 / 1.579 | 2.12 (0.034) | 57.3 (3.6e-13) | 0.163 (0.86, 0.39) | 0.273 (GJR) | 0.110 (GJR) |
| SPY | rsov | 4156 | 0.447 / 0.435 | 1.20 (0.232) | 5.02 (0.081) | −0.011 (−0.52, 0.60) | 0.006 (GJR) | 0.017 (GJR) |
| 0050.TW | r² | 1212 | 1.984 / 1.947 | 1.25 (0.211) | 5.47 (0.065) | −0.051 (−1.00, 0.32) | 0.020 (GJR) | 0.070 (GJR) |
| 0050.TW | rsov | 1212 | 0.646 / 0.582 | 1.01 (0.311) | 20.8 (3.0e-5) | −0.019 (−0.20, 0.84) | 0.058 (GJR) | 0.077 (GJR) |

Figures: `K1611_SPY_gw.png`, `K1611_0050_TW_gw.png` (top: cumulative loss
differential with high-VIX shading; bottom: mean d_t by regime with GW / slope
stats).

## Honest verdict

**No robust regime-dependence in either market. The HAR-vs-GJR winner does NOT flip
with the VIX regime.**

- **GJR-GARCH marginally and consistently beats HAR-RV in BOTH high and low VIX
  regimes** for both assets and both proxies — **no sign flip**. But the edge is
  small: **not Harvey-significant unconditionally** (|HAC-DM t| = 1.0-2.1 < 3
  everywhere).
- The **GW conditional test rejects equal conditional predictive ability on one
  proxy each** (SPY r² p=3.6e-13; 0050 rsov p=3.0e-5) but **not the other** (SPY
  rsov p=0.081; 0050 r² p=0.065) — **proxy-sensitive**. The rejection reflects a
  *consistent small GJR edge present in both regimes*, not a regime flip.
- The **direct regime-slope test — the correct test for regime-dependence — is
  insignificant for both assets and both proxies** (|t| = 0.20-1.00, all p>0.3).
  Its point estimates are even slightly negative on 3 of 4 cells (GJR's edge
  marginally *smaller* in high-VIX), the opposite of a "GJR shines in crises"
  story.

**Interpretation:** the GW framework confirms the prior unconditional-DM horse
races were not masking a regime flip — the single-winner ambiguity is genuine, not
a hidden state effect. The value added is a rigorous *negative* answer plus two
methodological guardrails.

## Contributions

1. **Method**: GW (2006) conditional predictive ability test operationalised on the
   canonical daily HAR-vs-GJR race, correctly distinguishing "not conditionally
   equivalent" (GW joint) from "winner flips with regime" (direct slope).
2. **Proxy-validity guardrail**: a daily variance-forecast horse race must use a
   close-to-close-consistent proxy; naive intraday range (Parkinson) omits overnight
   and produces spurious |DM t|=49 artifacts. Diagnostic table quantifies the bias.
3. **Data-integrity guardrail**: a single vendor bad tick produced a spurious
   "robust regime-dependent" finding that reversed on cleaning; added a price-limit
   data gate + GJR alignment tolerance guard, restoring reproducibility.

## Limitations

- Daily variance proxies (r², rsov) are noisy; the regime-slope test is
  correspondingly low-powered — a genuine but small regime effect could go
  undetected. The consistent *insignificance* across proxies and the near-zero /
  wrong-signed point estimates, however, argue against a large regime effect.
- 0050.TW OOS is 2017-2021 (1 major crisis, 2020) because the clean post-break
  window + VIXTWN coverage bound it; SPY OOS spans 2009-2026 (2020 + 2022).
- GW conditioning uses a single binary VIX-regime instrument; richer instruments
  (continuous VIX, term structure, macro) are left to follow-up.

## Related K / rules

- K1049 / k1054 / k1057 / k1063 (unconditional-DM horse races this refines)
- K445 (arch target-alignment), K783c (canonical QLIKE direction), K1355 (no
  asset-day pooling), K1213 (package limits ≠ model failure)
- k1098 (archived long VIXTWN series), k782 (daily r² proxy convention)

## Codex Review

Round 1 (`codex exec`, gpt-5.4) verdict **MAJOR_ISSUES**, all addressed:

1. *MAJOR — GW rejection over-interpreted as regime-dependent winner.* Fixed: the
   "regime-dependent" verdict is now gated on the **direct regime-slope test**
   (proxy-robust sign + significance), not on the GW joint or high-regime subsample
   DM. Both assets now correctly land on "no robust regime-dependence".
2. *MAJOR — 0050 GJR cross-val discrepancy 0.69 not aborted.* Root cause was the
   2014-01-02 bad tick; fixed by the clean-window restriction + `assert_price_limit`
   + `GJR_DISC_TOL` abort (post-fix discrepancy 3e-16).
3. *MODERATE — DM called "Newey-West HAC" but L=0 for one-step.* Fixed: DM now
   reports both the L=0 MDS+HLN variant and a data-driven-lag **HAC-DM** (the
   conservative primary bar).
4. Docstring said Parkinson=PRIMARY (contradicted implementation) → corrected;
   rsov unbiasedness assumptions stated; `auto_adjust` flagged as vendor-adjusted.
5. Singular-HAC `pinv` fallback added; README (this file) added.

Round 2 (post-fix confirmatory re-review) did NOT complete before the dispatch
window closed (the agent's background Codex waiter did not return a written
verdict). Main-thread closure therefore rests on **Round 1 (all five issues
addressed)** + an **independent main-thread numeric audit** (results.json
matches every README figure to 3 sig-figs; `regime_dependent_robust=false` on
both assets and both proxies; lookahead defences verified against K445/K783c/
K1355). **Verdict recorded as CONDITIONAL_PASS**, not full PASS — a Round-2
confirmatory Codex re-review is left as a light follow-up before any paper use.
