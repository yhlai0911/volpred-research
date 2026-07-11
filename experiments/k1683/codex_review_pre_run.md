# K1683 pre-run code review

Date: 2026-07-11
Verdict: **PASS_TO_RUN**

## Reviewed scope

- CFTC TFF Futures Only API fields and four-contract gross-participation formula.
- Tuesday report / nominal Friday release semantics, weekly `.shift(1)`, and
  explicit exclusion of government-shutdown catch-up report windows.
- Market and FRED target construction: all outcomes start after forecast origin.
- Expanding OOS training embargo: every admitted label has
  `target_end_date < forecast_origin`.
- Matched baseline/augmented samples and one-feature nesting.
- QLIKE and MSE loss direction, HLN-DM sign, helper cross-check, and four-cell
  BH-FDR gate.
- Pinned CSV provenance and tmp/parse/`os.replace` atomic JSON output.
- Proxy wording: CFTC Leveraged Funds is not confidential Form PF hedge-fund
  exposure, basis-trade AUM, fund concentration, or causal forced deleveraging.

## Pre-execution diagnostic

Public-data construction completed without estimating the models: 4,192 CFTC
contract-report rows produced 899 lagged signal origins; the four primary panels
had 894–898 eligible pre-OOS rows. Static compilation and diff checks passed.

No blocking defect remained. Formal model execution was authorized only after
this review; all numerical claims still require post-run verification.
