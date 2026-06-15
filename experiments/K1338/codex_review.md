# Codex Review - K1338

Review date: 2026-06-15

Reviewer: Codex

## Verdict

Implementation integrity: CONDITIONAL_PASS

Research conclusion: NULL_DATA_LIMITATION

K1338 is acceptable as a data-availability and pipeline experiment. It is not a
valid predictive test of Chinese financial-news sentiment because the public
machine-readable news history available at run time is only 11 Taipei-calendar
days. The script correctly refuses to report OOS QLIKE/DM under that constraint.

## Checklist

1. Lookahead control: PASS.
   - HAR price features use lagged realized variance (`K1338.py:445-447`).
   - Daily sentiment z-score is computed with prior-only expanding mean/std, not
     full-sample standardization (`K1338.py:365-370`).
   - The model signal is explicitly lagged via
     `model["sentiment_z_raw"].shift(1)` (`K1338.py:455-456`).
   - Missing news dates are kept as missing, not silently treated as neutral
     sentiment (`K1338.py:449-453`).

2. Data provenance: PASS with caveat.
   - CNYES categories and CTEE probes are recorded in the results JSON
     (`K1338_results.json:data.news_sources_attempted`).
   - NTUSD download diagnostics are recorded
     (`K1338_results.json:lexicon.diagnostics`).
   - CNYES article titles are not persisted verbatim; the article artifact keeps
     `news_id`, date, hit counts, score, and `title_hash`.
   - Caveat: CTEE returned no usable RSS/API endpoint at run time, so the scored
     sample is CNYES-only.

3. Statistical gate: PASS.
   - The script requires at least 252 model rows plus 60 OOS forecast rows before
     reporting QLIKE/DM (`K1338.py:72-74`, `K1338.py:490-496`).
   - Current usable rows after lag-safe news alignment are only 3
     (`K1338_results.json:model_result.usable_rows`), so OOS/DM is skipped.

4. Reproducibility artifacts: PASS.
   - Required experiment triple exists: `README.md`, `K1338.py`,
     `K1338_results.json`.
   - Additional artifacts exist: `K1338_daily_sentiment.csv`,
     `K1338_article_scores.csv`, `K1338_sentiment_coverage.png`.
   - Seed is fixed at 42 (`K1338.py:41-42`).

## Caveats

- This is a source-availability null, not evidence that Chinese news sentiment
  lacks volatility-predictive content.
- Title-only dictionary sentiment is a deliberately cheap proxy; a full
  FinBERT-style study still needs archived article text or a persistent daily
  collector.
- If a future collector creates enough history, rerun the same script and review
  the OOS branch before promoting any predictive claim.
