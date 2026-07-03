# K1612 Codex source review

Reviewer: Codex self-review in main interactive session  
Date: 2026-07-03  
Verdict: `CONDITIONAL_PASS`

## Scope

Reviewed:

- `experiments/K1612/K1612.py`
- `experiments/K1612/K1612_results.json`
- `experiments/K1612/README.md`
- generated CSV, raw text, and PNG artifacts under `data/` and `figures/`

## Checks

### Data binding

PASS. The README numbers are copied from `K1612_results.json` and the generated CSV outputs:

- `87` total documents, `44` statements, `43` minutes.
- `SPY` coverage: `1,392` observations from `2020-12-15` to `2026-07-02`.
- Primary verdict: `WEAK_MIXED_SIGNAL_NEEDS_CONFIRMATION`.
- Main significant pooled term-structure result: complexity coefficient `0.0414`, HAC `t=2.58`, `p=0.0099`, `n=86`.

### Release-date alignment and lookahead

PASS. The script treats text as observable at public release:

- statements use the official statement date embedded in the Fed URL;
- minutes use the Fed calendar parent text `Released Month DD, YYYY`;
- forward targets start on the next trading day after the release-aligned market date;
- same-day SPY returns are not used as target returns;
- the lagged RV control is explicitly shifted by one day.

This is especially important for minutes. Backdating minutes language to the meeting date would be lookahead; the script does not do that.

### Inference and dependence

PASS with caveat. Regression inference uses OLS with HAC maxlags 1, and bootstrap high-low diagnostics use 3,000 reps with seed `42`. The sample remains small and event targets can overlap, especially for 22-trading-day horizons.

The README separates adjusted regressions from descriptive high-low tercile diagnostics. It does not present the bootstrap tercile findings as the main predictive result.

### Statistical conclusion

PASS. The conclusion is deliberately weak:

- Realized-volatility regressions are mostly non-significant.
- Term-structure evidence is mixed and concentrated in `^VIX / ^VIX3M` 22-day changes.
- Multiple metrics and multiple targets were checked, so the isolated p-values are treated as hypothesis-generating.

The final wording "worth tracking as event-context features, not yet as a standalone forecasting signal" matches the evidence.

## Caveats

- Self-review is weaker than independent review.
- The Fed calendar HTML sample available in this runtime starts in 2021.
- Dictionary tone metrics are crude proxies and may miss economic meaning.
- HAC maxlags 1 is a pragmatic event-level adjustment, not a complete solution to overlapping horizons.

## Required before publication

Any article should state upfront that K1612 is a small-sample, release-aligned event study with weak mixed evidence. Do not headline it as a proven FOMC language forecasting signal.
