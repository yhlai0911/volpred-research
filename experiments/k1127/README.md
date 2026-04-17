# K1127 - Cross-asset OFI lead-lag (TAIFEX TX vs ES overnight channel)

**Status**: FAIL at OFI level / PARTIAL PASS at RV level (Scenario D with nuance)
**Date**: 2026-04-17
**Author**: Claude (worktree agent-k1127)
**Data**: TAIFEX TX tick (local) + yfinance ES=F 1h bars

## Problem & Motivation

K1100g_d1 found TAIFEX night->day asymmetric cross-prediction (LRT chi^2=12.48, p=0.0004)
in a single-market within-Taiwan setup. K1100g_d2 OOS FAIL flagged this as
possibly an in-sample artifact.

K1127 asks the next question: if there is a real asymmetric channel, should it
generalize **across markets** via microstructure information flow? Specifically,
does TAIFEX TX OFI lead/lag ES (S&P 500 futures) OFI through the natural
US-overnight -> TW-morning (and TW-close -> US-evening) channels?

**Hypothesis channels:**
- **Channel A**: ES US-afternoon/overnight OFI -> TX next-day open
  ("US leads TW via overnight microstructure")
- **Channel B**: TX TW-close OFI -> ES US-evening open
  ("Asia leads US via Asian overnight signal")

If cross-market OFI predicts cross-market OFI/RV, then microstructure info
crossing happens at tick level, not just at return level.

## Data & Method

### Data constraint (hard)
- **yfinance ES=F 5-min**: only 60 days history. **INFEASIBLE** for 2+ year sample.
- **yfinance ES=F 1h**: 730 days history (2023-11-23 onwards). **USED (fallback)**.
- **TAIFEX TX tick**: local 33G, 2012-2026.

*5-min was the original spec; 1h is the best feasible interval given yfinance
limits. This is documented as a data constraint, not a methodological choice.*

### Period
- Overall: 2023-11-23 .. 2026-04-16 (~2.4 years)
- TX trading days: 575; ES distinct dates: 735; ratio 78.2%
- Aligned complete-case panel: **487 days**
- IS: 2023-11-29 .. 2025-06-30 (N=322)
- OOS: 2025-07-01 .. 2026-04-16 (N=164)

### TX OFI (K1124 spec, honored)
- T-1 active contract rolling (K849/K1124 Codex fix)
- Lee-Ready pure-tick rule (no bid/ask data on TAIFEX)
- Session OFI = sum(signed_volume) / sum(volume)
- Day session: 08:45-13:44:59 TW (DAY_END Codex fix)
- Night session T = night_early(T, 15:00-23:59) + night_late(T+1, 00:00-05:00)

### ES OFI proxy (range-based)
- yfinance 1h bars do not provide tick data. Use range-based signed pressure
  (Chordia-Roll-Subrahmanyam 2002 style):
  - direction = sign(close - open)
  - magnitude = |close-open| / (high-low)  in [0, 1]
  - OFI = direction * magnitude  in [-1, 1]

### Overnight windows (UTC, TW date = T)
- **es_night_pre_tw_open**: `(T-1 18:00 UTC, T 00:00 UTC)` - strictly before TX day T opens (00:45 UTC). **Gemini audit fix**: end at 00:00 UTC to avoid the 00:00-01:00 UTC bar overlapping the TX open.
- **es_night_for_tw_full**: `(T-1 18:00 UTC, T 05:00 UTC]` - full overnight, diagnostic only.
- **es_eve_after_tw**: `(T 13:00 UTC, T 21:00 UTC]` - US morning/afternoon after TW close.

### Analyses
1. Cross-correlation at lag -4..+4 for both channels
2. Granger causality (L=2 hard-coded) bi-directional
3. Forecasting models M1 (within-TX), M2 (+ES overnight cross), M3 (asymmetric channels)
4. DM-HLN OOS vs M1

## Gemini Code Audit

Gemini review flagged one **CRITICAL** lookahead bug:
- yfinance 1h bars are interval-START. Bar timestamped 00:00 UTC covers
  [00:00, 01:00), which includes 15 min AFTER TX 08:45 (= 00:45 UTC) open.
  Using it to predict TX day T would leak.
- **Fix applied**: `es_night_pre_tw_open` window ends at 00:00 UTC (exclusive
  on 00:00 UTC bar), so last bar used is 23:00 UTC T-1 (covering 23:00-24:00).
  Strictly pre-TX-open.

Other audits passed:
- TX OFI K1124 DAY_END=13:44:59 and T-1 rolling active contract: honored
- Timezone alignment via `tz_convert('UTC')`: correct
- IS/OOS clean separation: confirmed
- TAIFEX 10-column era (2014+) index reading: correct for 2023-2026
- DM-HLN small-sample correction: implemented correctly

**Acknowledged limitation**: Granger L=2 hard-coded (no AIC/BIC selection).
Results conditional on L=2.

## Results

### Coverage
- TX days: 575; ES distinct UTC dates: 735; **ratio 78.2%** (>> 20% threshold)
- Complete-case panel: **487 aligned days**
- Coverage OK -> proceed.

### Cross-correlation table
cr95 = 2/sqrt(487) = **0.091** (95% CI for zero correlation)

#### Channel A: ES overnight(t) -> TX day(t+lag)
| lag | OFI    | RV     | |OFI|   |
|----:|:------:|:------:|:------:|
| 0   | +0.069 | +0.042 | +0.036 |
| +1  | -0.063 | **+0.304** | +0.058 |
| +2  | -0.001 | **+0.349** | -0.005 |
| +4  | +0.062 | +0.161 | +0.052 |

#### Channel B: TX day(t) -> ES evening(t+lag)
| lag | OFI    | RV     | |OFI|   |
|----:|:------:|:------:|:------:|
| -2  | -0.088 | **+0.318** | +0.081 |
| 0   | -0.026 | **+0.370** | -0.047 |
| +1  | +0.093 | **+0.287** | +0.065 |

**All OFI / |OFI| cross-corrs are within +/- CI (not significant).**
**RV cross-corrs are strongly significant at several lags** (vol co-movement is well-established).

### Granger causality (L=2)
| Direction | OFI F, p | RV F, p | |OFI| F, p |
|-----------|----------|---------|------------|
| ES -> TX (Channel A) | 1.02, **0.36** | 44.66, **<0.0001** | 0.84, **0.43** |
| TX -> ES (Channel B) | 3.02, **0.0497** | 36.58, **<0.0001** | 0.99, **0.37** |

**Key finding**: RV strongly Granger-causes bi-directionally (expected for
co-moving global assets). OFI only marginally in TX -> ES (p=0.0497, borderline
and not after multiple-test correction).

### Forecasting models (target: TX day RV)
| Model | Features | IS QLIKE | OOS QLIKE |
|-------|----------|----------|-----------|
| M1 within-TX | `tx_day_rv_lag1`, `|tx_day_ofi|_lag1` | 0.3035 | **0.1585** |
| M2 +ES cross | M1 + `es_night_rv_sameday`, `es_night_|ofi|_sameday` | 763140* | 0.1736 |
| M3 asymmetric | M2 (signed ES) + prior TX night RV & OFI | 0.2491 | **0.1528** |

*M2 IS QLIKE blowup: OLS predicted near-zero / negative variance in IS on a
 handful of days; clipping to 1e-12 dominates QLIKE. This is an OLS
 specification issue (linear model ill-suited for variance), not a data leak.
 OOS is clean (prediction clipping occurs on <2% of bars).

**DM-HLN vs M1 (OOS)**:
| Comparison | t-stat | p-value | QLIKE impr |
|------------|--------|---------|------------|
| M2 vs M1 | **-1.35** | 0.18 | **-9.54%** (M1 better) |
| M3 vs M1 | +0.51 | 0.61 | +3.59% |

**Neither M2 nor M3 significantly improves over M1** at Harvey (2016) |t| > 3.0 threshold.
M2 is actually WORSE (negative DM), indicating ES cross features add noise.

## Verdict

### Scenario D (with nuance)

**OFI level (primary test)**: FAIL both channels.
- Channel A (US -> TW): lag-0 cross-corr OFI/|OFI| within CI; Granger OFI p=0.36. NO PASS.
- Channel B (TW -> US): lag-0 cross-corr within CI; Granger OFI p=0.0497 (borderline, not robust). NO PASS.
- -> **Microstructure OFI information does NOT cross markets at daily aggregate in this sample.**

**RV level (secondary observation)**: Strong bi-directional co-movement.
- Granger RV F>>36 both directions, p<0.0001.
- Channel A RV cross-corr peaks at lag +1/+2 (0.30/0.35).
- Channel B RV cross-corr peaks at lag 0 / -2 (0.37/0.32).
- -> **Return-level lead-lag IS PRESENT** (consistent with established global vol
      spillover literature), but it is NOT mediated by OFI in our specification.

### Microstructure implication

> Consistent with the K1124 finding that OFI's RV-prediction on TAIFEX is
> statistically weak and opposite-signed (vol MEAN-REVERSION after flow bursts).
> **OFI is local and Taiwan-idiosyncratic**; it does not aggregate into a
> cross-market lead-lag signal at daily horizon.
>
> Cross-market vol comovement exists and is strong, but its channel is likely
> common news/risk factors, not tick-level microstructure. Earlier findings that
> return-level lead-lag "predicts" across markets are likely driven by the same
> underlying news, NOT by OFI propagation.

This means **K1100g_d1's night->day asymmetric cross-prediction (which did not
OOS-replicate in K1100g_d2) is unlikely to be rescued by extending to a
cross-market OFI channel**. Different channel, same null result.

## Verdict block (per prompt format)

```
## Verdict: Scenario D

Data coverage: TX bars=575 days, ES bars=735 distinct dates (ratio 78.2%),
                aligned 487 complete-case days
Cross-corr peak lag: A channel (OFI) lag 0 = +0.069 (NS, within +/-0.091 CI)
                    B channel (OFI) lag 0 = -0.026 (NS)
                    Both RV channels show strong lag-0/+1/+2 co-movement (0.28-0.37)
                    but that is return-level, not OFI-level

M2 (with ES cross) OOS DM vs M1 (TX only): t=-1.346, p=0.180 (M2 slightly WORSE)
M3 (asymmetric channels) OOS DM vs M1: t=+0.514, p=0.608 (not significant)

Microstructure implication: OFI is local. Cross-market OFI microstructure info
does not flow at daily aggregate. Daily-level return/RV co-movement is real and
strong but is likely driven by common news factors, NOT by OFI propagation.
K1100g_d1 asymmetric signal unlikely to generalize via this cross-asset OFI route.
```

## Limitations

1. **1h bars instead of 5-min** (hard yfinance constraint). Finer intraday structure (e.g., 5-min OFI lead-lag during 15-min windows around market opens/closes) may exist but is not measurable here.
2. **ES OFI is a range-based proxy**, not tick-based. If true ES OFI differs substantially from the proxy, results could change.
3. **Granger L=2 hard-coded** (no AIC/BIC selection).
4. **Single cross-pair (TX, ES)**. Generalization to NK (Nikkei), HSI, or GE (DAX) untested.
5. **M2 OLS ill-suited for variance target** (produces negative predictions IS).
   A log-linear HAR (log-RV target) would be more appropriate; however, the
   core conclusion (no OFI-level cross signal) holds independent of model form
   because it comes from Step 5/6 cross-corr/Granger, which are model-free.
6. **Sample ~2 years** relatively short. A long-horizon 2012-2023 analysis
   would need tick-level ES/SPY data (not publicly available).

## Implications for research program

- **K1100g_d1 asymmetric cross-prediction**: further evidence that it is
  likely a single-sample artifact. K1100g_d2 FAIL + K1127 Scenario D = two
  independent null results against the hypothesis.
- **OFI research program**: consistent with K1124 finding that OFI is a
  local signal on TAIFEX (vol-MR pattern, 1.12% QLIKE impr), not a
  cross-market information channel.
- **Cross-market vol spillover**: confirmed strong at return/RV level
  (well-established literature), but it is NOT mediated through microstructure
  OFI at daily aggregation. Sub-daily HF analysis may still find an OFI channel
  but would require tick data for ES (not in scope here).

## Derived directions

1. **K1128 (proposed)**: Cross-market OFI at 5-min horizon using the 60-day
   yfinance ES 5m + TAIFEX 5m. Small sample but finer resolution might reveal
   minute-level spillover that is invisible at daily aggregate.
2. **K1129 (proposed)**: Common factor decomposition. Fit a PCA/DCC on
   TX-ES-NK daily RV and test whether the "global factor" Granger-drives both.
   If yes, that confirms the vol comovement is news-driven not microstructure.
3. **K1130 (proposed)**: ES 5-min OFI internal structure (without cross-market)
   via yfinance 60-day window - does US-market OFI -> RV replicate the K1124
   Taiwan result? Different sign/magnitude would indicate market-specific
   microstructure regimes.

## Files

- `k1127.py` - main experiment script
- `k1127_results.json` - full numeric results
- `tx_es_ofi_crosscorr.png` - Channel A/B cross-correlation structure
- `overnight_info_transfer.png` - OOS QLIKE across M1/M2/M3
- `_cache_tx_sessions_*.parquet` - TX session cache (115s to rebuild)
- `_cache_es_1h_*.parquet` - ES 1h cache
- `run.log` - execution log

## References

- Cont, R., Kukanov, A., Stoikov, S. (2014). "The Price Impact of Order Book Events." *JoFE* 12(1), 47-88.
- Chordia, T., Roll, R., Subrahmanyam, A. (2002). "Order Imbalance, Liquidity, and Market Returns." *JFE* 65(1), 111-130. [cited for range-based OFI proxy]
- Lee, C., Ready, M. (1991). "Inferring Trade Direction from Intraday Data." *JF* 46(2), 733-746.
- Granger, C. (1969). "Investigating Causal Relations by Econometric Models." *Econometrica* 37(3), 424-438.
- Patton, A. (2011). "Volatility Forecast Comparison Using Imperfect Volatility Proxies." *JoE* 160(1), 246-256.
- Harvey, D., Leybourne, S., Newbold, P. (1997). "Testing the Equality of Prediction Mean Squared Errors." *IJF* 13(2), 281-291.
- K1100g_d1: TAIFEX within-market night-day asymmetric cross-prediction (in-sample PASS)
- K1100g_d2: OOS FAIL of the K1100g_d1 asymmetric result
- K1124: TAIFEX TX OFI for vol prediction (FAIL, triple-threshold null)
