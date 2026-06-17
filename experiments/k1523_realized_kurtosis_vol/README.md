# K1523 — Realized kurtosis (daily proxy) vs HAR-Full

**Salvage of stale worktree work** (originally tagged K1520, K-id collision with main K1520; renamed K1523).

## Motivation
Test realized kurtosis (RKt) — daily-return 22-day rolling 4th moment proxy — as incremental predictor of 5-day RV. K1084 tested 60-day 5-min RKt and was NULL; this is a longer-sample daily-proxy variant.

## Methodology
- Sample: SPY + TAIEX, 2010-2026 (16y daily)
- Target: log(fwd5_rv) = log of sum r²[t+1..t+5]
- Lookahead: feat.shift(1), expanding OLS
- Specs: HAR, HAR + RSk, HAR + RKt, HAR-Full (all 4 features)
- DM HAC test vs HAR baseline; Bonferroni over 16 tests

## Verdict (Codex CONDITIONAL PASS, 2026-06-17)
- SPY: NULL (best HAR-Full t=-2.69, fails Harvey −3)
- TWII: H1 PASS (t=-3.14), H2 PASS (t=-3.15) — RKt has incremental predictive power over HAR & RSk
- TWII H3 (RKt over SV): NULL

## Codex review caveats
- DM HAC lag=16 sufficient for 5-day overlap
- log(rv_plus/minus) clip at 1e-12 could distort OLS; Jensen bias correction missing in exp(pred)
- Recommend: re-run with Jensen correction + rv_plus/minus floor at 1e-6

## Files
- `k1523.py` (orig k1520_realized_kurtosis_vol.py)
- `k1523_results.json`
- `figures/k1520_*.png`
- `references.md`

## Provenance
- Worktree branch: `worktree-agent-a392514c5c054287d` (commit 27aa7a26)
- Codex review: thread 019ed22b (worktree-local)
- Salvaged by: hourly-10 2026-06-17 (K-id collision with main K1520; renamed to K1523)
