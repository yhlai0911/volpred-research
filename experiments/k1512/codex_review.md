# K1512 — Codex CLI review

- **Reviewer**: Codex CLI 0.132.0 (gpt-5.4)
- **Date**: 2026-06-16 (Taiwan time)
- **Verdict**: **CONDITIONAL_PASS**

## Codex findings (verbatim summary)

1. **Lookahead**: Core `Y/D/X` lag scheme acceptable. Caveat — `VIX_t` / `term_spread_t` are same-date controls; for strictly tradable signal at ETF close, must execute after month-end data is observed. Also the original docstring mentioned `pct_change(12).shift(1)` but the implementation does not shift; fix the comment.
2. **DML**: 2-fold cross-fitting on ~142-145 monthly rows is **defensible only as exploratory**. RF nuisance constrained enough, but fold/seed instability is a real risk. Recommended `n_rep=20-50` repeated cross-fitting, sensitivity to `n_folds`, shallow RF vs Lasso/Ridge, blocked/time-ordered splits.
3. **Newey-West DML SE**: Influence-score adaptation basically correct. Improvements: mean-center `psi`, report lag sensitivity `{1, 3, 6, 12}`, do not silently fall back to default SE.
4. **Verdict gate bug**: Aggregate `PASS_PRELIMINARY` is too loose. QUAL `NW p=0.0357` fails Bonferroni for 3 factors (`alpha=0.0167`, two-sided `|z|≈2.39`). Should be **CONDITIONAL_PASS** or `EXPLORATORY_SIGNAL`.
5. **Metadata bug**: Sample dates from `panel.dropna()` instead of each DML estimation frame; last usable row should exclude final month because `Y=shift(-1)`. Store per-factor `first_date` / `last_date`.

> Suggested wording: "In an ETF-level monthly sample, QUAL shows a marginal negative DML partial association ... does not survive 3-test multiple-testing correction, and the term-spread control was unavailable, so the result is exploratory rather than robust causal evidence." — Do **not** claim a confirmed non-zero causal factor effect.

## Fixes applied (main thread, 2026-06-16 16:35)

| # | Codex finding | Fix in `k1512.py` |
|---|---|---|
| 1 | Docstring mis-described `shift(1)` | Rewrote "Lookahead policy" block in module docstring; flagged same-date VIX caveat |
| 2 | `n_rep=1` fragile | Changed to `n_rep=20` in `DoubleMLPLR(...)` |
| 3 | `psi` not mean-centered | Added `psi = psi - psi.mean()` in `_newey_west_se` |
| 3 | No lag-sensitivity | Compute NW SE at lag ∈ {1, 3, 6, 12}; store all in results JSON |
| 3 | Silent SE fallback | Loud `NW residual computation FAILED` warning + `nw_fallback` flag (not triggered in this run) |
| 4 | Loose verdict gate | New gate: per-factor PASS_PRELIMINARY requires `bonferroni_pass AND ci_excl_zero`; intermediate label = `EXPLORATORY_SIGNAL`; aggregate downgraded to `CONDITIONAL_PASS` |
| 5 | Wrong sample metadata | Removed global `sample` block; added `sample_per_factor` with per-factor `first_date/last_date/n_months` |

## Effect of fixes on results

Single-rep DML (initial run): QUAL θ̂ = −0.0125, NW-t = −2.10, p = 0.036 → looked like marginal signal.

Repeated cross-fitting (n_rep=20, post-fix): **QUAL θ̂ = −0.0065, NW-t = −1.07, p = 0.286**. The signal essentially vanished, confirming Codex's prediction that the n_rep=1 result was fold-randomness artifact. All three factors now NULL or EXPLORATORY, none Bonferroni-pass.

## Verdict gate satisfied

Per K1259 process gate: experiment_id present, reviewer field present (Codex), verdict in {CONDITIONAL_PASS, NULL} — eligible to write `knowledge.json` entry (main thread responsibility).
