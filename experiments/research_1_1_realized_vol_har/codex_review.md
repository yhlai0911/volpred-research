# Codex Review: research_1_1_realized_vol_har

Reviewer: Codex CLI
Date: 2026-06-16
Verdict: CONDITIONAL_PASS

## Findings

- Lookahead: PASS. HAR features use `.shift(1)`, and h-step forward-label
  training rows are filtered with `target_end_pos < forecast_pos`, matching the
  K1337 correction rule.
- Claim-evidence matching: PASS. The experiment does not claim text improves
  HAR because the public RSS data and FinBERT runtime are insufficient.
- DM/Harvey: PASS. No text challenger is evaluated, so no DM significance claim
  is made. The README states the Harvey gate that a future challenger must pass.
- Data transparency: PASS. RSS URLs, yfinance market source, headline snapshot
  file, sample counts, dependency status, and skipped reasons are written to the
  results JSON.

## Caveats

- This is a data-availability/null-limitation experiment, not a negative test of
  all textual regression or all LLM volatility forecasting.
- The HAR baseline uses close-to-close squared returns as a daily proxy rather
  than 5-minute realized variance. That is acceptable for the feasibility gate
  but should be upgraded if a historical headline archive becomes available.

