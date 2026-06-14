# Codex Review — K1495

Date: 2026-06-14  
Reviewer: Codex GPT-5

## Scope

Source-level review of:

- `experiments/k1495/k1495.py`
- `experiments/k1495/k1495_results.json`

## Checks

1. **Lookahead**
   - PASS. Concentration proxies only use returns or prices through `t`.
   - High-regime threshold uses expanding quantile, so the threshold itself is also history-only.
   - Forward outcomes explicitly start at `t+1` via `future_realized_vol()` / `future_min_return()`.

2. **Inference**
   - PASS. Overlapping 21-day forward windows imply serial dependence; script uses HAC(21) and stationary bootstrap instead of relying only on iid Welch tests.
   - Welch tests remain in results, but README correctly treats them as descriptive support rather than the sole formal gate.

3. **Research honesty**
   - PASS. Script and README explicitly state that `SPY-RSP` is a concentration **proxy**, not true historical top-10 weights / HHI.
   - Final verdict does not overclaim a unique `SPY-RSP` vol-gap widening; it records that H2 fails.

4. **Result alignment**
   - PASS. README headline numbers match `k1495_results.json`:
     - future `SPY` vol `18.16%` vs `14.41%`
     - bootstrap CI `[+0.95 pp, +7.39 pp]`
     - HAC high-regime coefficient `+2.03 pp`, `p=0.041`

## Verdict

`PASS`

No blocking implementation bug found. Main caveat is conceptual, not coding: the concentration signal appears to be a broad turbulence regime proxy rather than a uniquely cap-weight fragility spread.
