# Codex Review — research_rv_proxy

Reviewer: Codex (`gpt-5.4`) — 2026-07-03

## Verdict: CONDITIONAL_PASS_AS_PILOT

The experiment is reproducible and lookahead-clean for the stated NP15-only
pilot, but the evidence is not publication-strength for the broader queued
question ("regional renewable penetration drives power-price RV"). Treat the
result as a bounded NULL / descriptive diagnostic until EIA key or multi-ISO
data are available.

## Checks

- **Data provenance**: PASS. Script records EIA key absence and uses CAISO OASIS
  public ZIP endpoints for `PRC_LMP`, `SLD_REN_FCST`, and `SLD_FCST`; raw caches
  are saved under `data/`.
- **Lookahead**: PASS. Formal OOS uses `renew_share_mean_lag1` plus HAR lag
  features generated with `.shift(1)`; expanding fits train on `work.iloc[:pos]`
  only.
- **Metric alignment**: PASS. Target is direct hourly day-ahead LMP realized
  variance, not utility ETF RV. QLIKE compares actual `price_rv` with model
  forecasts of `price_rv`; log-MSE is secondary.
- **Claim strength**: CONDITIONAL. Only CAISO NP15 is included because EIA key is
  absent and CAISO multi-hub downloads hit practical rate limits. The same-day
  high-renewable relation is strong but explicitly diagnostic, not the PASS gate.
- **Statistical gate**: PASS. Formal augmented HAR does not improve QLIKE
  (`-0.25%`, DM p=0.447), and lagged renewable-share HAC t=0.71; verdict `NULL`
  is conservative.

## Required Follow-Up Before Publication

- Add EIA API key or a robust multi-ISO source and rerun at least CAISO/PJM/ERCOT
  or all CAISO hubs.
- Keep same-day high-renewable / negative-price results descriptive unless
  publication timestamp and tradability are modeled.
- If promoted to an article, frame as "NP15 pilot: lagged renewable share did
  not improve HAR-RV forecasts; same-day high-renewable days have more negative
  prices", not as a general renewable-volatility law.

