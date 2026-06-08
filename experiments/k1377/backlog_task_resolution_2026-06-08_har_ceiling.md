# Backlog Task Resolution — `research_har_ceiling`

Date: 2026-06-08  
Resolver: Codex CLI

## Verdict

This backlog task is already covered by an existing HAR experiment line. The relevant work is not a single stub; it is a completed sequence spanning baseline confirmation, ceiling defense against rough-vol extensions, and adaptive combination follow-up.

## Coverage mapping

Primary baseline:
- [k530_har_multiscale_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k530/k530_har_multiscale_results.json:1)

Ceiling defense against richer alternatives:
- [k764_rough_vol_multivariate_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k764/k764_rough_vol_multivariate_results.json:1)

HAR internal extension / combination follow-up:
- [README.md](/Users/yhlai0911/Desktop/volpred-research/experiments/k1377/README.md:1)
- [k1377_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k1377/k1377_results.json:1)

## What is already established

### 1. HAR baseline superiority was already tested directly

`K530` is the direct "HAR ceiling" baseline experiment for daily volatility forecasting:
- SPY best model: `HAR-VIX`, OOS QLIKE `0.462929`
- 0050.TW best model: `HAR-ABS`, OOS QLIKE `0.511462`
- Multiple HAR variants beat `GJR-GARCH` at the Harvey threshold:
  - SPY: `HAR-ABS`, `HAR-VIX`, `HAR-LEVERAGE`, `HAR-JUMP`
  - 0050.TW: `HAR-ABS`, `HAR-LEVERAGE`, `HAR-JUMP`

This already establishes that, within the repo's daily-vol forecasting framework, HAR is not an open conjecture but an empirically verified strong baseline.

### 2. More complex rough-vol extensions failed to break the HAR ceiling

`K764` explicitly records the next-step challenge:
- "Bivariate rough vol did NOT break the HAR-ABS ceiling."
- Best model remains `HAR-ABS`
- Cross-asset roughness and Hurst-type additions help in-sample but vanish OOS

This is exactly the kind of evidence a `research_har_ceiling` backlog item is supposed to produce: once HAR is strong, richer multivariate rough-vol structure does not reliably beat it out of sample.

### 3. HAR follow-on optimization was already explored

`K1377` tested whether adaptive forecast combination can beat the best single HAR model:
- Exp-QLIKE combination beats `HAR-VIX` at Harvey threshold in `SPY` and `GLD`
- `0050.TW` improves directionally but does not pass strict Harvey
- The follow-up conclusion is not "HAR remains untested"; it is "HAR family is already mature enough that the open question is combination and robustness, not whether HAR is competitive at all"

## Why this closes the backlog item

The backlog item title suggests a need to verify whether a "HAR ceiling" exists or whether a well-tuned HAR baseline remains hard to beat. That has already been answered in this repo:

- `K530`: HAR family established as a top-performing daily forecasting baseline
- `K764`: rough-vol augmentations fail to beat the HAR-ABS ceiling OOS
- `K1377`: even the next question, adaptive combination within HAR, has already been run

So this is not an unaddressed research direction. It is a duplicate of an already-populated experiment family.

## Remaining gap, if any

If the team wants to reopen this line, the meaningful next step is narrower:
- test the Los Flamingos 2025 claim with the exact paper design
- move from daily proxies to 5-min realized measures
- extend to cross-asset HAR with the same fairness gates

Those are follow-on replications or extensions, not reasons to leave `research_har_ceiling` pending as a generic backlog item.
