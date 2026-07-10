# Codex pre-run review — K1676

Final verdict before binding rerun: **PASS_AFTER_MAJOR_FIXES**

Review history: an initial self-review incorrectly returned PASS and the script
was run once before the independent reviewer replied. That run is explicitly
**non-binding**. The reviewer then found three major issues: returns were built
after the cross-asset join, the -2% robustness result was not wired into the
verdict, and the tracked `K1609` source path had incorrect case. All three were
fixed before the binding rerun; this file records the final pre-rerun gate.

Review scope: `experiments/k1676/k1676.py` source only. No experiment result had
been generated when this gate was written.

## Mandatory checks

1. **Lookahead / information set — PASS**
   - SPY, GLD and UUP returns are computed on each asset's native date series
     before merging. Merged rows must also share the exact same return-start
     date, so a multi-day return cannot be paired with a one-day return.
   - UUP regime uses trailing data and explicit `.shift(1)`.
   - DFII10 uses backward `merge_asof` by observation date, then a further
     market-day `.shift(1)` before its regime is built. There is no backfill.
   - Rolling correlations are shifted one day.
   - Same-day SPY-tail and GLD returns are explicitly labelled as a descriptive
     safe-haven estimand, not a forecast or trading signal.

2. **Increment beyond K1628 — PASS**
   - The primary test is not another crisis-day table. It is a formal moderator
     test: lagged continuous USD / real-yield states enter joint tail-mean and
     hierarchical `SPY × tail × state` beta models.

3. **Model hierarchy / partial effects — PASS**
   - Tail-mean and tail-beta models are separated so the mean effect is not an
     extrapolated beta-model intercept.
   - Every triple beta interaction includes all lower-order terms.
   - USD and real-yield states enter the canonical joint model together; their
     correlation and VIF are reported. Separate models are context only.

4. **Inference — PASS**
   - HAC lag is 21, not the K1628 five-day default.
   - Four pre-specified partial interactions form one Holm family and also face
     Harvey `|t| >= 3`, expected-direction, 5,000-rep circular-block CI, and
     leave-one-year-out sign gates.
   - Extreme-state cells must have at least 50 tail observations spanning five
     calendar years before a statistical pass may become a conditional PASS.
   - The -2% threshold, bucket regressions, rolling correlations and subperiods
     cannot upgrade the primary verdict. It can block an apparent PASS when a
     coefficient reverses sign; sparse -2% cells force INCONCLUSIVE.

5. **Randomness / artifacts — PASS**
   - All bootstrap paths use `seed=42` and block length 21.
   - Results use temp write → parse check → `os.replace`, with `allow_nan=False`.
   - The script records source paths, sample dates/counts, proxy limitations,
     current-vintage FRED limitation and input mtimes.
   - The DFII10 path uses tracked canonical case `experiments/K1609/...`, so the
     reproduction path is valid on case-sensitive filesystems.

## Static validation

- `python -m py_compile experiments/k1676/k1676.py`: PASS.
- `git diff --check -- experiments/k1676/k1676.py`: PASS.
- `ruff` is not installed in this environment; absence is tooling availability,
  not a source failure.

## Constraints on the eventual conclusion

- Do not use the word “decoupling” unless the joint partial interaction passes
  every primary gate and is robust to leave-one-year-out checks.
- Current-vintage DFII10 plus a conservative lag is not ALFRED vintage evidence.
- GLD/UUP are ETF proxies. Any result remains U.S.-ETF sample co-movement, not
  bullion causality, a forecast, or an investable strategy.
