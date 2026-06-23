# Codex Review: K1544 Fair-Information GJR-X

## Verdict

PASS_WITH_CAVEAT for experiment output. Do not integrate into paper body until
the PRG paper decides whether the main full-day forecast is the canonical
`h_overnight + h_intraday` sequence or an explicitly day-open
`x_overnight + h_intraday` forecast.

## Checks

- Handoff task satisfied: all six markets are run, including TAIFEX, SPY, QQQ,
  GLD, EEM, and 0050.TW.
- Required experiment triplet exists: README, script, and results JSON.
- FairInfo GJR-X uses current `x_overnight[t]`, not lagged overnight.
- OOS fitting uses observations strictly before `t`; same-day `r_c2c[t]` and
  full-day variance target are not used in the forecast.
- DM sign is explicit: `fair-GJR loss - PRG loss`, so positive favors PRG.
- QLIKE target is common full-day variance for each market.

## Findings

1. The direct current-overnight GJR-X benchmark beats canonical PRG Extended in
   all six markets. The result is Harvey-significant against PRG in GLD, EEM,
   0050.TW, and TAIFEX.

2. The open-known PRG diagnostic reverses the conclusion: replacing PRG's
   overnight forecast component with the already observed overnight component
   makes PRG beat FairInfo GJR-X in all six markets.

3. Therefore the fair-information issue is a timing/target-convention issue,
   not a simple add-one-benchmark issue. A paper rewrite should not claim a
   structurally clean PRG advantage unless it first formalizes the open-time
   full-day forecast convention.

## Residual Risk

The PRG and GJR-X likelihoods are non-convex and estimated by multistart
L-BFGS-B. The broad directional result was stable across reruns during this
tick, but exact QLIKE values should be treated as experiment-output numbers,
not hand-transcribed paper constants, until reproduced in the paper pipeline.

