# Codex Review - K1614

Review date: 2026-07-03

## Verdict

`CONDITIONAL_PASS` for a narrow public-proxy diagnostic.

The experiment now covers volatility structure plus lagged inflation / drought public proxies, writes reproducible cached inputs, fixes the seed, and keeps the conclusion at `DIRECTIONAL_ONLY_PUBLIC_PROXY_DIAGNOSTIC`. It is not an implementable trading signal or publication-grade significant factor claim.

## Checks

- Lookahead: clean for the public-proxy stress diagnostic. CPI/PPI are assumed available only after conservative release delays and then shifted one trading day; T10YIE and USDM DSCI columns are also shifted one trading day. Targets are next-21-trading-day RV, downside volatility, and SPY return correlation.
- Data provenance: yfinance adjusted closes, FRED CPIAUCSL/PPIACO/T10YIE, and USDM California weekly statistics are cached under `data/`.
- Statistical gate: 63 HAC regression cells were tested across stress proxy × asset × target. Safe-haven and risk-amplifier gates both require `|t|>=3` in direction and Holm-adjusted p<=0.05. Gate pass count is zero.
- Multiple testing: signal p-values are Holm-adjusted across all public-proxy regression cells. Raw high/low splits are descriptive only.
- Randomness: seed fixed at 42. No bootstrap or stochastic split is used.

## Issues / Caveats

- MEDIUM: CPI/PPI are FRED current-vintage release-lag proxies, not consensus surprises or ALFRED real-time vintages. Inflation-surprise claims are not allowed.
- MEDIUM: California statewide DSCI is an imperfect geography proxy for LAND/FPI/WY/RYN/PHO/CGW/FIW; it is a climate-risk state proxy, not verified issuer-level exposure.
- MEDIUM: high/low stress splits can look strong, especially drought intensification raising forward RV ratios, but controlled HAC regressions with Holm correction do not pass the gate.
- LOW: rolling and forward 21-day windows overlap; HAC and non-overlap robustness reduce but do not eliminate finite-sample dependence concerns.

## Allowed Claim

K1614 can claim that listed natural-resource real-asset proxies are not a homogeneous low-volatility safe-haven basket, and that lagged public inflation/drought proxies show mixed directional forward-volatility associations without formal gate significance. It cannot claim a significant inflation hedge, climate-risk volatility premium, causal drought exposure, or tradable signal.
