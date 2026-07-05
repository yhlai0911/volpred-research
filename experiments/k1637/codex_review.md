# Codex Review — K1637

Review date: 2026-07-05

## Verdict

CONDITIONAL_PASS_AS_EXPERIMENT_ARTIFACT; research conclusion is `CONDITIONAL_NULL_MSM_BEATS_HAR_BUT_LOSES_TO_EWMA`.

## Checks

- Three-piece experiment artifact exists: `README.md`, `k1637.py`, `k1637_results.json`.
- Data provenance is local and reproducible through `data/cache/price_cache.db`; 0050.TW uses `clean_tw50_data`.
- Lookahead controls are explicit:
  - HAR features use `shift(1)`.
  - MSM/HMM forecast for day t uses `posterior_{t-1}` transitioned forward before observing `r_t`.
  - Parameters are fit on the initial 750-row training sample before OOS evaluation.
- Pooled DM inference aggregates by date before testing, avoiding asset-day iid inflation.
- Seed is fixed at 42.

## Findings

No correctness-critical issue found for the stated daily proxy experiment.

Main caveat: the result must not be framed as a full MSM literature replication. The MSM estimator is intentionally `GMM-lite`, FIGARCH and MS-GARCH are mechanism proxies, and EWMA(0.94) is the best pooled model. Therefore the conclusion is limited to "MSM helps relative to HAR in this proxy, but fails the simple-EWMA practical gate."

## Repro command

```bash
uv run python experiments/k1637/k1637.py
```
