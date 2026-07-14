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

## Verdict: NULL（2026-07-14 更正，以 `k1523_results.json` 為準）
`k1523_results.json` 的 `verdict` 是 `NULL`，六個假設全部 `supported: false`（無一通過 Harvey |t|>3，
亦無一通過 Bonferroni α=0.003125，family_size=16）：

- SPY: H1 t=-2.27、H2 t=-2.44、H3 t=-1.06 — 全 NULL
- TWII: H1 t=-2.87、H2 t=-2.71、H3 t=-1.29 — 全 NULL（**RKt 對 HAR / RSk 沒有增量預測力**）

**本節原本寫「Codex CONDITIONAL PASS；TWII H1 PASS (t=-3.14)、H2 PASS (t=-3.15)」，與結果檔直接矛盾**
（兩個數字都剛好被寫成越過 |t|≥3 門檻，而結果檔是 -2.87 / -2.71）。推測是 K1520→K1523 worktree salvage
時 README 未隨結果同步。2026-07-14 kb-backfill 稽核（`storage/ops/kb_backfill/README.md` §不可靠案例 1）
發現後更正。結論以結果檔為準：**這是一個 null result，不得被引用為 RKt 有預測力的證據。**

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
