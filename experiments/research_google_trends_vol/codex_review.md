# Codex Review: research_google_trends_vol

## Verdict

CONDITIONAL_PASS_NULL

## Scope

Reviewed `research_google_trends_vol.py`, `research_google_trends_vol_results.json`, `google_trends_weekly.csv`, and `README.md`.

## Findings

- No lookahead found in the predictive branch. The stock RV target is current-week close-to-close realized variance, while Google Trends attention is explicitly lagged via `attention.shift(1)`.
- The experiment does not replace missing Google Trends terms with VIX, price, or volume proxies. This avoids the K789 circular-proxy problem.
- The Google Trends panel is partial: `iPhone`, `TSMC`, and `HBM` are available only from 2018-01-05 to 2022-12-30; `AI server` is unavailable; later chunks mostly hit HTTP 429.
- The primary result is NULL: 0/4 Taiwan supply-chain tickers pass the Harvey `|t| > 3` gate versus HAR. OOS size is only 69 weeks per ticker, so this is a partial-panel NULL, not a broad impossibility result.

## Required Wording

Do not write an article claiming "Google Trends cannot predict Taiwan supply-chain volatility." The supported claim is narrower:

> In the available 2018-2022 Taiwan Google Trends panel, lagged product-keyword attention did not robustly improve weekly RV forecasts beyond HAR for 2330/2303/2454/2382.

## Status

Acceptable for knowledge entry as a NULL / data-limited methodology result.
