# K1363 Codex Source Review

Review date: 2026-06-23

Verdict: **CONDITIONAL_PASS_AS_NULL_DIAGNOSTIC**

The experiment is acceptable as a transparent public-data null diagnostic. It should not be used as evidence against the motivating Journal of Econometrics speech-NLP mechanism, and it should not be written into `knowledge.json` as a strong finding.

## Checks

| Area | Verdict | Notes |
|---|---|---|
| Required files | PASS | `README.md`, `K1363.py`, and `K1363_results.json` exist. Supporting CSVs, index/calendar/OHLCV raw cache, and figures are present. The per-speech HTML corpus is intentionally not kept as committed output; URL-level trace is in `data/K1363_speech_corpus*.csv`. |
| Data provenance | PASS | Speech text comes from Federal Reserve Board official speech pages; FOMC dates from official Fed calendar; market data from yfinance daily adjusted OHLCV. Results JSON records sample dates and counts. |
| Lookahead | PASS | `align_speech_signals()` maps speech date to a trading day and writes `*_z_l1` via `z.shift(1)`; HAR controls use `log_rv.shift(1)` and lagged range variance. |
| Between-meeting scope | PASS with caveat | Speeches within +/-1 business day of parsed FOMC dates are excluded. Caveat: parsed calendar dates are page-text regex extraction, not a manually audited FOMC date table. |
| Formal tests | PASS | Primary regressions use OLS-HAC Newey-West `maxlags=5`, Harvey-style positive `t>=3`, and BH q-values over primary tests. |
| 5d target handling | PASS with caveat | Forward 5d RV and left-tail targets overlap; HAC mitigates serial correlation. Results correctly remain diagnostic. |
| Claim discipline | PASS | Verdict is `NULL_PUBLIC_DICTIONARY_PROXY`; README states that this does not refute the original NLP literature. |

## Result Audit

Primary tests: 12 asset-target cells for `forecast_revision_shock_z_l1`.

- Positive Harvey `t>=3`: 0/12.
- Absolute Harvey `|t|>=3`: 0/12.
- Positive discovery pass with BH q<=0.05: 0/12.

The strongest positive primary cell is SPY `log_rv_1d`, HAC t=+1.60, BH q=0.654. The most negative primary cell is SPY `left_tail5`, HAC t=-2.65, BH q=0.097. Neither supports a tail-vol prior claim.

The secondary high-signal diagnostic was corrected to use the top quintile among positive lagged speech-shock z-signal days. It also stays null: all four forward 5d RV Welch p-values are above 0.49.

## Limitations

- Federal Reserve Board pages do not cover all Reserve Bank president speeches, so the corpus is not a full FOMC-member speech library.
- Dictionary scoring is intentionally crude and cannot substitute for sentence-level forecast-revision NLP.
- Daily close-to-close and high-low proxies cannot capture high-frequency speech-window market reactions.
- Speech release timestamps are not modeled; the one-trading-day lag is conservative but coarse.
- The FOMC calendar parser should be replaced by a curated canonical table before a stronger v2.

## Required Follow-Up Before Any Strong Claim

1. Full FOMC-member corpus across Board and Reserve Bank sites.
2. Speech timestamp and high-frequency event-window equity / Treasury futures reaction.
3. Sentence-level forecast-revision classifier or a documented FinBERT-style model.
4. Non-overlapping weekly robustness for 5d targets.

Conclusion: source review passes the experiment as a null public-proxy diagnostic only. Do not publish a strong article or update `knowledge.json` with a robust finding from this version.
