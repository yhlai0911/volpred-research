# K1417: Paper 3 H2 — Stationary bootstrap MDD CI

**Date**: 2026-06-05
**Status**: SCRIPTED — compute_queue dispatched
**Parent**: `paper/vt-trend-following/review_history/v4/README.md` H2

## Motivation

Gemini v4 review (`paper/vt-trend-following/review_history/v4/`) raised H2:
fixed 252-day blocks in K1192's bootstrap chop multi-year drawdown
autocorrelation, mechanically shallow-ing synthetic BH MDDs, inflating the
retention ratio, and pushing 90% CI lower bounds upward. The fix Gemini
prescribes is stationary bootstrap (Politis & Romano 1994) with mean block
length 3-5 years — long enough to span the 2008 and 2022 peak-to-recovery
arcs without strictly forcing identical block sizes.

## Methodology

Identical to K1192 in every respect except the bootstrap:

| Component | K1192 baseline | K1417 H2 variant |
|-----------|----------------|------------------|
| VT rule   | `min(12/VIX_month_end, 1)`, monthly, lag 1 month | same |
| Cash      | SHY              | same |
| TSMOM     | rolling 252-day, β∈[0, 0.5], lag 1 day | same |
| Seed      | 42               | 42 |
| Period    | 2005-01-03 to 2026-04-01 | same |
| Bootstrap | fixed-block size 252, B=10,000 | **stationary (Politis-Romano 1994), mean block ∈ {756, 1260} (3y, 5y), B=10,000** |
| CI        | 90% percentile (5th/95th) | same |

The stationary-bootstrap index draw uses standard geometric block continuation:
at each step, with probability `1/mean_block` start a new block at a uniformly
random position; otherwise continue the current block by `+1 mod n`. Expected
block length equals `mean_block`; the resulting time series is strictly
stationary, unlike fixed-block resampling.

Strategy construction (`build_vt_monthly`, `compute_hedged_vt`, `compute_mdd`)
imports K1192 verbatim via `sys.path` injection so the only methodological
difference between the two experiments is the resampling scheme.

## H2 Acceptance Criterion

If H2 is correct, K1417's retention 90% CI lower bound shifts **materially
downward** vs K1192's published `[86, 90, 82, 91, 91]` across the 5 assets.
Pre-registered threshold: at least 3 of 5 assets show ≥3 pp drop in the lo
bound at mean_block=1260. If fewer than 3 assets shift, retention is robust
to bootstrap block-length choice and Gemini's H2 is rejected.

The script writes `summary.verdict` to `k1417_results.json` based on this
threshold; downstream paper-body integration uses that verdict to decide
whether Table 6 needs a new column or just a footnote.

## Reproduce

```bash
# Smoke test (fast, lets the compute worker pick up the full job afterwards):
uv run python experiments/k1417/k1417.py --n-reps 200 \
    --out experiments/k1417/k1417_smoke.json

# Full run (heavy — dispatched to compute_queue worker):
uv run python experiments/k1417/k1417.py --n-reps 10000
```

## Files

- `k1417.py` — script (entry point, importable for tests)
- `k1417_results.json` — full results (written by worker)
- `k1417_smoke.json` — smoke-test output (B=200, sanity gate before full run)
- `run.log` — execution log

## Downstream

After the worker completes, the next hourly fire picks up the `claude_followup`
brief and dispatches an interpretation agent that integrates K1417 into
Paper 3 v4 Section "robustness" + Table 6 footnote. The accompanying paper_body
sub-tasks (H1 PureVT trough decomposition, M1 safe-haven dummy, M2 VRP
clarification, 3 missing citations) remain separate hourly-fire scope and are
not affected by K1417's outcome.
