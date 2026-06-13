# Codex Review — I7 Practical Cross-Border Futures

- Reviewer: Codex
- Date: 2026-06-13
- Verdict: PASS with caveats

## Checks

- Re-ran `uv run python experiments/i7_practical_cross_border_futures/i7_practical_cross_border_futures.py`.
- Ran `uv run python -m py_compile experiments/i7_practical_cross_border_futures/i7_practical_cross_border_futures.py`.
- Verified required artifacts exist: README, script, results JSON, and two PNG figures.
- Verified ES notional is about 10x MES notional after fixing the SPY-to-SPX proxy.
- Verified results JSON has `verdict = CONDITIONAL_PASS` and non-empty feasible plans.

## Findings

No blocking implementation issues found after the SPY-to-SPX proxy correction and half-up contract rounding fix.

## Caveats

- Margin, tax, and transaction-cost values are scenario assumptions, not live broker or exchange quotes.
- ES sizing uses `SPY close × 10` as an SPX proxy because continuous ES settlement data is not available locally in this experiment.
- The tax section is a sensitivity table only and must not be read as tax advice.
