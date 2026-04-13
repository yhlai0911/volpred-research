# K1124 — TAIFEX TX Order Flow Imbalance for Short-Horizon Vol Prediction

**Status**: FAIL (null result, statistically significant but economically immaterial)
**Date**: 2026-04-13
**Author**: Claude (worktree agent-k1124)
**Data**: TAIFEX TX futures tick data 2017-2021 (local 33G), day session 08:45–13:45

## Problem & Motivation

Today's research exhausted 3 directions with null/dead-end results (Paper 2 firm-selection, Paper 3 copula adaptations, Paper 4 alt-data). This experiment tests an **orthogonal microstructure signal** — Order Flow Imbalance (OFI) — as a predictor of short-horizon realized volatility on TAIFEX TX futures.

**OFI theory (Cont, Kukanov, Stoikov 2014)**: aggregated signed order flow within a window aggregates liquidity demand pressure. High |OFI| = concentrated directional pressure → expected short-term vol increase. Sign asymmetry may exist (buy-side pressure ≠ sell-side pressure).

**Unstudied question on TAIFEX**: Prior work establishes OFI → return prediction (Cont et al.). Less clear whether OFI predicts VOL at intraday horizons, especially in a non-US setting with pure electronic execution and no bid/ask data (tick rule variant required).

## Data & Method

- **Source**: TAIFEX TX futures, `~/Dropbox/TAIFEXDATA/TAIFEXDATA/python/Daily_YYYY_MM_DDTX.csv`
- **Period**: 2017-01-03 … 2021-12-30 (1223 trading days, 73,203 5-min bars)
- **Session**: Day session only 08:45–13:44:59 (60 bars of 5 min each)
- **Contract selection (K849 rule + Codex fix)**: Active contract chosen by **T-1 day's total volume** (not current day's — removes selection lookahead). Falls back to next-most-liquid on roll days.
- **Tick rule (Lee & Ready 1991 pure-tick variant, no bid/ask)**:
  - price up → buy-initiated (+1)
  - price down → sell-initiated (−1)
  - zero tick → carry forward prior non-zero direction
- **OFI per bar**: `sum(signed_volume) / sum(total_volume)` ∈ [−1, +1]
- **Target**: `rv_next` = sum of squared tick log-returns in next 5-min bar

## Models

| Model | Features | Interpretation |
|---|---|---|
| M1 GARCH(1,1) | `r_t` series only | 5-min return GARCH (reference) |
| M2 HAR-RV | lag1, mean lag6, mean lag12 RV | Standard intraday HAR baseline |
| M3 HAR + \|OFI_t\| | M2 + current-bar \|OFI\| | H1 core (magnitude effect) |
| M4 HAR + OFI_t signed | M2 + current-bar signed OFI | H2 asymmetry |
| M5 HAR + OFI_pers | M2 + cumulative \|OFI\| over last 5 bars | Persistence effect |
| M6 HAR + \|OFI_{t-1}\| | M2 + strictly-past \|OFI\| | Robustness: no current-bar leak |
| M7 HAR + OFI_{t-1} signed | M2 + strictly-past signed OFI | Robustness variant |

## Results

**In-Sample**: 2017-2019 (34,438 bars); **Out-of-Sample**: 2020-2021 (22,866 bars)

### OOS QLIKE comparison

| Model | OOS QLIKE | DM-HLN vs M2 | QLIKE impr vs M2 | H1 better? | H2 better? |
|---|---|---|---|---|---|
| M1 GARCH | 3.2334 | — | — | — | — |
| **M2 HAR** | **0.2845** | baseline | — | — | — |
| M3 HAR+\|OFI\| | 0.2849 | **−5.24** (wrong sign) | −0.12% | ✗ | ✗ |
| M4 HAR+OFI signed | 0.2832 | +2.63 | +0.46% | ✓ | ✓ |
| M5 HAR+OFI_pers | **0.2813** | **+5.85** | +1.12% | ✓ | ✓ |
| M6 HAR+\|OFI\|_{t-1} | 0.2839 | +3.50 | +0.23% | ✓ | ✓ |
| M7 HAR+OFI_{t-1} signed | 0.2841 | +1.24 | +0.17% | ✓ | ✓ |

### Triple-threshold verdict (DM|t|>2 + QLIKE>5% + sub-period stable)

**All 5 OFI models FAIL.** Statistically significant improvement (M5 DM=5.85) but economically negligible (QLIKE improvement max 1.12%, threshold 5%).

### Additional findings

- **Settlement day effect (H3)**: |OFI| on 3rd-Wed settlement days = 0.1194 vs non-settlement 0.0991 (Welch t=6.77, p<0.0001). **But RV ratio settlement/non = 0.84×** (lower, not higher). Settlement days have concentrated directional flow but LOWER subsequent volatility — plausibly because most directional unwinds have completed by expiry close.
- **GARCH(1,1) is dominated by HAR** on 5-min data (QLIKE 3.23 vs 0.28). HAR is the correct baseline for this horizon. GARCH inappropriate — return-based unsuitable for RV target (preamble rule).
- **|OFI| ACF(1) = 0.133, ACF(5) = 0.120** — moderate short-run persistence (consistent with Cont et al. 2014).
- **beta(|OFI|) negative and significant** even in M6 strict-lag version: high |OFI| at t-1 → LOWER RV at t+1. Not a current-bar leak; a genuine empirical pattern on TAIFEX. Interpretation: bursts of concentrated one-sided order flow are followed by vol MEAN-REVERSION (pressure releases, spread normalizes).

## Codex Audit Record

Codex identified 3 bugs before full run (prevented false positive):

1. **HIGH — bar bucket overflow**: `DAY_END=13:45` with `//5` assigned `bar=60` alongside bars 0–59. Fixed to `DAY_END=13:44:59`, verified `bar_idx max=58` and last bar of each day correctly excluded from training.

2. **HIGH — selection lookahead on active contract**: Original pick used entire day's volume to choose contract → using afternoon's winner to label morning bars. Fixed to use T-1 day's total volume (rolling selection).

3. **MEDIUM — current-bar info-set asymmetry** (explains initial pilot `beta(|OFI|)<0`): Added M6 and M7 strict lag-1 specifications. Result held: beta still negative and significant (M6 DM=3.50).

## Limitations

- No bid/ask data → tick-rule approximation (Lee-Ready pure-tick); known to be noisier than quote-based classification on illiquid ticks.
- Day session only; cross-session effects (K1100g night→day asymmetry) not incorporated.
- Linear OLS variance model — QLIKE penalizes gross misspecification so likely robust but nonlinear Hawkes or MIDAS may change sign.
- Single asset (TX). US equivalents (ES, NQ) with quote data untested.
- Static IS-estimated GARCH parameters (not rolling re-estimation).

## Verdict & Paper Implications

**Not publishable as a standalone finding.** Triple-threshold FAIL on all 5 OFI specifications. The statistically significant DM t-stats (up to 5.85) without economic improvement (1.12% QLIKE) is exactly the pattern Patton (2011) and Hansen's SPA warn against over-reporting.

**However, the negative-sign robustness is scientifically interesting**: OFI magnitude predicts NEGATIVE short-run vol innovation on TAIFEX, opposite to the intuitive "pressure → vol up" intuition. This is a Taiwan-specific microstructure pattern worth documenting as an observational finding (not a model).

**Paper 6/7 candidate status**: NOT a paper on its own. Could be one sub-section of a broader Taiwan-microstructure paper, contrasting OFI's vol-MR pattern vs US markets' classic "flow → vol up" (Cont et al.).

## Derived directions (3)

1. **K1125**: OFI × realized jump detection — does |OFI| condition on upcoming JUMP rather than diffusive vol? Use Lee-Mykland (2008) jump test on TX.
2. **K1126**: OFI asymmetry regime — split sample by VIX level and test if buy-OFI / sell-OFI asymmetry strengthens in high-vol periods.
3. **K1127**: Cross-asset OFI — does TAIFEX TX OFI lead / lag SPY ES OFI via overnight quote updates? Extend K1100g night-session cross-prediction using OFI as the channel.

## Files

- `k1124.py` — Main experiment
- `k1124_pilot.py` — Single-day pipeline validation (pre-run sanity check)
- `k1124_pipeline_test.py` — 3-month validation after Codex fixes
- `k1124_results.json` — Full numeric results
- `k1124_ofi_distribution.png` — OFI histogram + |OFI| ACF
- `k1124_oos_qlike.png` — 6-model OOS QLIKE comparison
- `k1124_settlement_ofi.png` — |OFI| box plot settlement vs non
- `_cache_bars_*.parquet` — 5-min bar cache (73,203 rows, 239s load time)

## References

- Cont, R., Kukanov, A., Stoikov, S. (2014). "The Price Impact of Order Book Events." *Journal of Financial Econometrics* 12(1), 47–88.
- Lee, C., Ready, M. (1991). "Inferring Trade Direction from Intraday Data." *Journal of Finance* 46(2), 733–746.
- Corsi, F. (2009). "A Simple Approximate Long-Memory Model of Realized Volatility." *JoFEconometrics* 7(2), 174–196.
- Patton, A. (2011). "Volatility Forecast Comparison Using Imperfect Volatility Proxies." *Journal of Econometrics* 160(1), 246–256.
- Harvey, D., Leybourne, S., Newbold, P. (1997). "Testing the Equality of Prediction Mean Squared Errors." *IJF* 13(2), 281–291.
