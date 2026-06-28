# K1553 Codex Review

- Review date: 2026-06-28
- Reviewer: Codex
- Verdict: `PASS_WITH_LIMITATIONS`

## Scope

Reviewed `experiments/k1553/k1553.py`, `README.md`, generated
`k1553_results.json`, data snapshots, and `k1553_capital_rank.png`.

## Checks

- Reproducibility: seed fixed at 42; data source, requested period, actual
  fetched period, sample size, and rolling window are written to the result
  JSON.
- Experiment package: required three-piece structure is present:
  `README.md`, `k1553.py`, and `k1553_results.json`; chart and data snapshots
  are also stored under `experiments/k1553/`.
- Lookahead: rolling forecasts use `values[t - WINDOW : t]` and are evaluated
  at `idx[t]`; de-risking returns use
  `applied_leverage = raw_leverage.shift(1).fillna(1.0)` before multiplying by
  OOS portfolio returns.
- Formal diagnostics: VaR coverage uses Kupiec, Christoffersen, Basel
  traffic-light counts, and an Acerbi-Szekely-style ES Z1 statistic; ES
  estimator coherence is tested with pairwise subadditivity.
- Result integrity: final verdict was regenerated after correcting the summary
  logic to identify EWMA, not Cornish-Fisher, as the largest observed
  subadditivity failure.

## Verification Commands

```bash
uv run python experiments/k1553/k1553.py
uv run python -m compileall experiments/k1553/k1553.py
uv run python scripts/lookahead_audit.py --json | jq '.findings["experiments/k1553/k1553.py"] // "no finding for K1553"'
```

The targeted lookahead audit returned `"no finding for K1553"`. A full strict
repo audit still fails on unrelated historical experiments, so it is not used
as a blocking signal for this K1553 review.

## Findings

No blocking issue found for K1553.

Limitations:

- yfinance is a vendor snapshot, so reruns may shift slightly if adjusted prices
  are revised.
- The EWMA and Cornish-Fisher estimators are deliberately practical estimator
  variants, not proven coherent L-estimators.
- The PASS is not a production-risk-model approval: many method/asset
  combinations still fail independence, Basel, or ES Z1 checks.
