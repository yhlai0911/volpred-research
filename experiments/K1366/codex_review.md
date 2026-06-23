# Codex Review — K1366

Verdict: `PASS_FOR_NARROW_PARTIAL_RESULT`

## Scope

Reviewed `experiments/K1366/K1366.py`, `K1366_results.json`, generated CSVs,
figures, and README language after a fresh rerun:

```bash
uv run python experiments/K1366/K1366.py
```

## Findings

No blocking issues found for the narrow stated conclusion.

The code now stores EWMA covariance forecasts only after the 252-day
initialization window, so the covariance path used for events and diagnostics
does not expose early rows to initialization-window lookahead.

The lookahead requirement is explicitly satisfied for the only predictive
carryover diagnostic:

```python
lagged_signal = signal.shift(1)
```

The main event-response paths are correctly described as historical
post-shock templates, not ex-ante trading signals.

## Caveats

- This is EWMA covariance filtering, not structural BEKK/DCC VIRF
  identification.
- Event dates are manually specified; 2018Q4 peaks late in the 60-day window,
  so it should be interpreted as an episode template rather than a clean
  one-day causal impulse.
- Total-variance response passes for 2018Q4 and 2025 tariff shock, but
  correlation-response placebo tests do not pass. Article or knowledge usage
  must not claim structural covariance-network evidence.
- Because the experiment verdict is partial rather than `CONDITIONAL_PASS`,
  no `storage/memory/knowledge.json` entry should be written from this run.

## Reproducibility

Fresh rerun produced `K1366_results.json` with verdict
`PARTIAL_VARIANCE_TEMPLATE_CORR_NULL` and regenerated all three figures.
