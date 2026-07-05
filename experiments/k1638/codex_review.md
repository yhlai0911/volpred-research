# Codex Review — K1638

Review date: 2026-07-05

## Verdict

CONDITIONAL_PASS as an evaluation-layer audit. The research conclusion must stay coverage-limited.

## Checks

- Three-piece artifact exists: `README.md`, `k1638.py`, `k1638_results.json`.
- Input data are existing repo OOS forecast artifacts; no new market data are fetched.
- Distribution calibration uses only the initial slice of each OOS panel and evaluates later rows only.
- Short panels below the minimum row threshold are skipped and listed in results.
- `seed=42` controls moving-block bootstrap MCS.
- Results explicitly reject the overclaim that K1638 ranks all 1400+ K experiments.

## Findings

No correctness-critical issue found in the stated scope.

The main limitation is methodological: point forecasts are wrapped into lognormal predictive distributions. That is acceptable as a transparent audit bridge, but should not be described as native probabilistic forecasting. The practical output is a reusable scoring layer and coverage map, not a new universal model leaderboard.

## Repro command

```bash
uv run python experiments/k1638/k1638.py
```
