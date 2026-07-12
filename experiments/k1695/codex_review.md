# K1695 Codex Review Verdict

**Final verdict: PASS**  
**Review date:** 2026-07-12  
**Scope:** pre-run source review + post-run artifact/result verification

## Pre-run findings and resolution

1. **FAIL — MDD omitted initial NAV=1 from the running peak.**
   - Impact: bootstrap paths beginning with losses understated MDD and could move the primary CI/kill gate.
   - Fix: scalar metrics now floor the running peak at 1; vectorized bootstrap prepends a NAV=1 row.
   - Regression: first-return-loss test covers both implementations.

2. **FAIL — pinned snapshot coverage was not fail closed.**
   - Impact: a truncated ETF/SHY/VIX/IRX response could silently shorten a supposedly canonical sample.
   - Fix: every required series must end exactly 2026-03-31, internal quote gaps over 10 calendar days fail, and inception/common/paired outputs independently assert the same cutoff.

3. **PASS after clarification — total-return corporate-action reconciliation.**
   - First data preflight stopped before strategy computation because a single 5 bp threshold rejected an EFA dividend date (5.96 bp).
   - Full provider diagnostic showed ordinary-date maximum 0.225 bp and action-date maximum 22.58 bp; the standard `D_t / Close_(t-1)` formula was uniformly closer to Adj Close than the alternative denominator.
   - Gate was transparently split before viewing strategy results: 1 bp ordinary dates / 30 bp distribution dates. Original failure receipt is retained.

4. **Runtime schema fix — `target_weight` Series retained the source name `target`.**
   - Impact: execution stopped before bootstrap/results.
   - Fix: explicitly name each `StrategyPath` output; unit test asserts the output schema.

## Final source checks

- Previous-calendar-month VIX mapping uses `PeriodIndex` + explicit `shift(1)`; January-to-February and December-to-January toy tests pass.
- IRX is forward-filled only from past quotes, then shifted on the return-date calendar.
- BH/VT use identical dates per market; common inference uses identical dates across all 13 markets.
- Monthly holdings drift within month; 10 bp cost is charged only on actual one-way turnover after the first allocation.
- Joint stationary bootstrap uses one shared index for all 26 paired BH/VT columns; no stacked asset-day or independent-market resampling.
- JSON uses native booleans/numbers, `allow_nan=False`, readback validation, and atomic replace. CSV/gzip outputs are also atomically replaced; result JSON pins artifact hashes.

## Post-run numerical verification

- JSON summary exactly matches `table5_rows.csv` and `common_sample_rows.csv` aggregation.
- Common CSV rows exactly match MDD recomputed from `data/paired_common_returns.csv.gz`.
- All artifact hashes match `k1695_results.json`.
- Primary B=10,000 bootstrap was independently recomputed from the pinned paired panel with seed 42; CI, median, mean, tail probability, and all-positive frequency match within CSV round-trip tolerance `1e-12`.
- No VT Sharpe exceeds 2× its BH baseline; there is no “too good to be true” signal.
- Figure PNG was visually inspected and matches its CSV source.

## Verified result

- Inception-aware observed ΔMDD: 13/13 positive; average +27.50 pp.
- Common sample: 2012-02-07 to 2026-03-31, N=3,557; observed average +12.61 pp.
- Joint-bootstrap 90% CI for common-sample average ΔMDD: [+4.22, +19.30] pp; `P(avg ≤ 0)=0.0006`.
- Pre-registered kill gate: **not triggered**.
- Caveat: common-sample VIX-sensitivity correlation is not significant, so the cross-sectional mechanism claim must remain sample-dependent and descriptive.

