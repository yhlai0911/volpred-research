# Codex Source Review

Review date: 2026-07-02

Verdict: PASS as scoped null-result pilot.

## Checks

- Reproducibility: PASS. The experiment runs with:

```bash
uv run python experiments/research_glp_1_adoption_shock_sector_consumption_healthca/research_glp_1_adoption_shock_sector_consumption_healthca.py
```

- Required artifacts: PASS. The directory contains `README.md`, the experiment script, and `research_glp_1_adoption_shock_sector_consumption_healthca_results.json`.
- Data provenance: PASS. Prices are yfinance adjusted closes cached under `data/raw/`, with `auto_adjust=False` and explicit `Adj Close` extraction. Event dates are listed in the script and results JSON.
- Lookahead control: PASS. Primary post-event windows start at `loc + 1`, so same-day announcement returns are diagnostics only.
- Inference unit: PASS. Formal tests use event-level group means. Ticker-event rows are not pooled as independent observations.
- Multiple testing: PASS. The script reports Holm-adjusted t-test, sign-test, and placebo p-values across all group x horizon cells.
- Randomness: PASS. Bootstrap and placebo sampling use fixed seed `42`.
- Result honesty: PASS. No group survives the formal gates; README and results report `null_or_inconclusive` and do not generalize beyond the public-equity event-study design.

## Caveats

- The sample has only six major events, so wide intervals are expected.
- Daily close-to-close returns may miss intraday repricing.
- Some event announcements may have occurred before the open or after the close; excluding same-day returns is conservative but may understate announcement-day volatility.
- The proxy observes public equity repricing, not actual GLP-1 prescription adoption, grocery spending, claims data, or patient-level treatment uptake.

## Reviewer Notes

The code originally had a slow placebo path that recomputed ticker windows inside each bootstrap draw. It was replaced with a precomputed `anchor_group_metrics.csv` lookup, leaving the statistical design unchanged and making the run practical for hourly failover.
