# Duplicate Resolution — research_etf_0056_00878_00919

- Task ID: `research_etf_0056_00878_00919`
- Date: 2026-06-09
- Resolution: `already covered by formal experiment`

## Finding

The queued research topic "高股息 ETF（0056/00878/00919）除息日前後的價格行為" is already covered by:

- `experiments/k1375/k1375.py`
- `experiments/k1375/README.md`
- `experiments/k1375/k1375_results.json`

K1375 title:

> 高股息 ETF（0056 / 00878 / 00919）除息日波動率事件研究

## Existing result to reuse

K1375 is a formal NULL result with the required experiment triplet.

Headline numbers:

- `0056.TW`: `d = -0.015`, `p = 0.927`, `n = 21`
- `00878.TW`: `d = +0.343`, `p = 0.179`, `n = 22`
- `00919.TW`: `d = -0.147`, `p = 0.285`, `n = 12`
- pooled: `n = 55`, `d = +0.055`, `p = 0.617`

Interpretation already established in K1375:

- High-dividend ETF ex-dividend-day volatility effect is NULL.
- ETF diversification appears to dilute the individual-stock ex-dividend volatility spike seen in `K1374`.

## Related internal context

- `research_program.md` already records:
  - `K1374` PASS for individual TWSE stocks ex-dividend volatility effect
  - `K1375` NULL for the ETF cohort
- `storage/memory/knowledge.json` already contains a matching knowledge entry for `K1375`

## Literature check

The existing K1375 direction is consistent with the standard ex-dividend literature focus on price / volume frictions around ex-dates:

1. Lakonishok, J., and T. Vermaelen (1986), *Tax-induced trading around ex-dividend days*, Journal of Financial Economics 16, 287-319. DOI: `10.1016/0304-405X(86)90032-2`
2. Michaely, R., and J.-L. Vila (1995), *Investors' Heterogeneity, Prices, and Volume around the Ex-Dividend Day*, Journal of Financial and Quantitative Analysis 30(2), 171-198.
3. Frank, M., and R. Jagannathan (1998), *Why Do Stock Prices Drop by Less than the Value of the Dividend? Evidence from a Country without Taxes*, Journal of Financial Economics 47(2), 161-188.

These papers motivate ex-dividend event studies, but none create a reason to rerun this exact ETF cohort question when a formal in-repo result already exists.

## Decision

Do **not** rerun a duplicate experiment.

If this topic is needed for publication, reuse K1375 directly and frame it as:

- contrast article to `K1374` individual-stock PASS
- ETF-level NULL due to diversification
- sample-power caveat for `00878` and `00919`
