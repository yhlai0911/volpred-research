# K1529 Codex Review

Reviewer: Codex CLI
Review date: 2026-06-17

## Verdict

PASS on implementation hygiene; empirical verdict remains `NULL_ETF_PROXY`.

The experiment is suitable as an exploratory ETF-proxy null result. It is not
suitable for a strong article claim about firm-level sticky-price credit risk or
industry credit spreads.

## Checks Performed

- Ran the experiment end to end:
  `uv run python experiments/k1529_credit_spread_fomc_vol/k1529_credit_spread_fomc_vol.py`
- Ran syntax check:
  `uv run python -m py_compile experiments/k1529_credit_spread_fomc_vol/k1529_credit_spread_fomc_vol.py`
- Checked artifacts exist:
  - `README.md`
  - `k1529_credit_spread_fomc_vol.py`
  - `k1529_credit_spread_fomc_vol_results.json`
  - `k1529_credit_spread_fomc_vol.png`
- Searched results/code for `NaN` / `Infinity`; none found.

## Lookahead Review

Pass.

- Pre-FOMC OOS model predicts SPY RV over t0 to t+5 using only lagged SPY RV,
  lagged VIX variance, and HYG-LQD credit stress from t-5 to t-1.
- Post-response OOS model uses HYG-LQD credit response from t0 to t+5, but its
  target starts at t+6 and ends at t+26, so predictor and target windows do not
  overlap.
- There is no strategy return computed as same-day signal times same-day return.
- FOMC dates are public; surprise magnitude is used for event-response
  regression or post-announcement interpretation, not pre-announcement trading.

## Claim-Evidence Review

Pass with scope caveat.

The result is correctly framed as an ETF-proxy pilot:

- HYG-LQD stress event-vs-baseline mean difference is tiny and insignificant:
  diff mean `0.000457`, paired t p `0.737580`, Wilcoxon p `0.340171`.
- Absolute orthogonalized surprise has HAC t `1.9229` for credit response, below
  Bonferroni/Harvey-strength standards.
- Pre-FOMC credit worsens OOS QLIKE for SPY RV t0 to t+5 by about `-13.85%`.
- Post-response credit improves SPY RV t+6 to t+26 QLIKE by about `5.92%`, but
  DM t is only `-1.294`, far below Harvey strength.

## Caveats

- SF Fed chart surprise data end at 2023-12-13 in this run. Price data extend to
  2026-06-17, but the experiment intentionally does not mix surprise-series
  methodologies.
- Sticky/flexible sector baskets are crude ETF proxies, not NFIB, markup, or
  firm-level price-duration measures.
- Daily ETF OHLC cannot test the high-frequency 2pm ET FOMC announcement window.
- The exploratory sticky-minus-flexible coefficient is not a publishable finding
  after multiple-testing discipline.

## Final

Implementation: PASS.

Finding: NULL_ETF_PROXY.
