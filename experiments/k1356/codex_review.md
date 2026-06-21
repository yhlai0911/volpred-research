# K1356 Codex Review

Review date: 2026-06-21

Verdict: PASS for research-honesty controls; empirical finding remains NULL.

## Checks

- Lookahead: PASS. The target is next-day variance via `target_log_rv = log_rv.shift(-1)` and `target_rv = rv.shift(-1)` in `K1356.py:227-228`. News and inventory predictors are both lagged at the row level in `K1356.py:231-233`.
- Regime/proxy construction: PASS. GDELT z-score normalization uses prior rolling mean/std through `.shift(1)` in `K1356.py:142-144`. EIA stock changes use prior rolling moments in `K1356.py:167-169`.
- Inventory availability: PASS. Weekly EIA period dates are shifted forward by five business days before daily forward-fill in `K1356.py:171-173`, then lagged again in the model panel.
- OOS fitting: PASS. Expanding OLS trains only on rows before the forecast row via `df.iloc[:i]` in `K1356.py:264-268`.
- QLIKE/DM sign: PASS. Comparisons call `dm_test(challenger_loss, base_loss)` in `K1356.py:307-310`; project helper defines negative t as model 1 better. Pooled DM averages same-date cross-asset loss differentials before testing in `K1356.py:339-341`.
- Seed/provenance: PASS. `SEED=42` is set and written to results. Sources, sample, tickers, and lookahead policy are recorded in `K1356_results.json`.

## Result Integrity

- Main result: NULL. `HAR_INV_NEWS` pooled mean QLIKE loss differential is `-0.0005708`, but DM `t=-0.744`, `p=0.457`; only 2 of 4 assets improve.
- Asset pattern is mixed: CL=F and USO improve slightly, XLE and XOP worsen. The result does not satisfy the predeclared 3-of-4 asset and `t<-3` gate.
- No knowledge promotion recommended. This is a useful null/proxy diagnostic, not a robust K finding.

## Caveats

- GDELT article-count attention is a weak public proxy, not Reuters full-text topic modeling or sentiment.
- EIA WCESTUS1 stock changes are realized inventory changes, not survey surprises.
- Daily Garman-Klass range variance is a low-frequency RV proxy, not intraday realized volatility.
