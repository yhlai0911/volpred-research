# K864-v2: Heterogeneous ABM — Strategy Diversity and VT Crowding

## Status

- Status: revised after Codex FAIL review
- Revision date: 2026-06-14
- Type: Monte Carlo ABM simulation, not empirical market data
- Script: `experiments/k864/k864_heterogeneous_abm.py`
- Results: `experiments/k864/k864_results.json`
- Related article: `mile_1a6d9369`

## Motivation

K864 tests whether strategy heterogeneity among volatility-targeting (VT)
agents reduces the crowding risk found in K827v3. The original result was
published, then Codex source review failed it for seven production-critical
issues: ex-post crash threshold, no HLN-style paired test, clamp/noise demand
bugs, missing linear-demand sensitivity, no per-type flow diagnostics, and an
over-strong article claim about individual accounts.

K864-v2 fixes those issues and reruns the full simulation.

## Design

| Item | Setting |
|---|---|
| Agents | 1000 |
| Noise traders | fixed 200 |
| Sim length | 2520 trading days |
| Monte Carlo | 200 runs per cell |
| VT adoption | 0%, 10%, 20%, 30%, 50%, 70%, 100% |
| Primary demand | quadratic herding amplification inherited from K827v3 |
| Sensitivity | linear demand |
| Random seeds | common random numbers: same seed for homo vs hetero per `sim_idx` |
| Crash metric | rolling t-1 22-day sigma, `r_t < -3 * sigma_{t-1}` |
| Fixed crash metric | `r_t < -5%` |

Heterogeneous VT agents are split equally across:

- A: standard `12/VIX`
- B: `12/VIX` with 30% floor and 90% cap
- C: risk parity, target 10% volatility
- D: EWMA(22) volatility target

## V2 Fixes

- Replaced ex-post full-sample crash threshold with rolling t-1 crash metric.
- Added fixed -5% crash frequency.
- Fixed price clamp path: rolling-vol buffer now receives the clamped return.
- Fixed noise trader flow: market demand uses actual clipped weight delta.
- Added linear-demand sensitivity alongside primary quadratic demand.
- Added common-random-number paired HLN-style tests and Harvey `|t| >= 3` gate.
- Added per-type Sharpe/MDD and sell-flow lag diagnostics.
- Revised article `mile_1a6d9369` to remove unsupported A -> C -> D cascade claim.

## Key Results

Primary quadratic demand still shows heterogeneity worsening market stability:

| VT adoption | Metric | Homogeneous | Heterogeneous | Change |
|---|---|---:|---:|---:|
| 50% | rolling crash / year | 0.756 | 5.563 | +636% |
| 50% | annual market vol | 19.0% | 29.0% | +52.2% |
| 50% | max drawdown | -41.1% | -53.6% | -12.5 pp |
| 50% | aggregate VT Sharpe | 0.313 | 0.419 | +33.7% |
| 70% | rolling crash / year | 0.797 | 9.020 | +1031% |
| 70% | annual market vol | 23.6% | 51.8% | +119.6% |

The tipping point by 10% drop from peak VT Sharpe remains 50% in both regimes.

Linear-demand sensitivity reverses the strength of the narrative: at 50% VT,
annual market vol is 16.008% in both regimes, rolling crash frequency is
0.987/year in both regimes, and aggregate VT Sharpe changes only -0.3%.

## Interpretation

The robust conclusion is not "heterogeneity is always harmful." The supported
claim is narrower:

> Under the K827v3-style quadratic herding amplification, diversifying VT rules
> does not remove crowding risk and can amplify crashes, volatility, and
> drawdowns. Under linear demand, this effect is essentially absent.

The old mechanism story that A-type agents sell first, then C/D agents sell
later, is not supported by the new flow diagnostics. At 50% VT, A-to-C and
A-to-D sell-flow lag correlations are small and negative; C and D flows are
mostly contemporaneous.

Per-type performance also differs sharply at 50% VT: A Sharpe=-0.245,
B=-0.170, C=0.773, D=1.173. The aggregate VT Sharpe improvement does not mean
every agent type benefits.

## Limitations

- Simulation only; no empirical market data.
- Heterogeneity is across four deterministic type rules, not within-type belief
  learning.
- Primary model uses a strong quadratic demand assumption; linear sensitivity
  is the key robustness boundary.
- No transaction costs or adaptive switching.
- 100% VT quadratic hetero cells are pathological and should not be used as a
  stable real-market forecast.

## References

- K827v3: fixed-liquidity ABM VT crowding baseline.
- K859: robust VT floor/cap and EWMA variants.
- Kyle (1985), continuous auctions and price impact.
- Farmer and Foley (2009), agent-based financial modeling.
- LeBaron (2006), agent-based computational finance.
- Hommes (2006), heterogeneous agent models.
