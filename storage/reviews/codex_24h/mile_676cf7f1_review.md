# Codex 24h Review — mile_676cf7f1 (K1512)

- **Article**: 買因子 ETF 前，先看一眼它真的有沒有超額報酬訊號
- **Task**: `paper_review_mile_676cf7f1`
- **Reviewed**: 2026-06-22 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **PASS with minor caveat**

## Summary

這篇一般讀者版文章和 K1512 canonical source 基本對齊。文章把結論寫成「三檔因子 ETF 都沒有足夠證據預測下個月相對 SPY 的超額報酬」，這符合 `k1512_results.json` 的 `CONDITIONAL_PASS` / essentially NULL framing。`QUAL` 被描述為有一點方向但不夠穩，沒有被包裝成可交易訊號；樣本數、期間、FRED term-spread 失敗與 seed=42 也都交代清楚。

唯一小 caveat：文章中段先用白話說「把殖利率曲線資料一起放進去」，但 canonical run 其實 `term_spread_available=false`，term spread 以常數 0 替代。文章最後有揭露這點，所以不是 blocker；若要更嚴格，可把前段改成「原本嘗試納入殖利率曲線」。

## Numeric verification

| Article claim | Source | Match |
|---|---|---|
| MTUM usable months = 145 | `sample_per_factor.MTUM.n_months` | yes |
| VLUE usable months = 145 | `sample_per_factor.VLUE.n_months` | yes |
| QUAL usable months = 142 | `sample_per_factor.QUAL.n_months` | yes |
| MTUM/VLUE sample 2014-04-30 to 2026-04-30 | `sample_per_factor` | yes |
| QUAL sample 2014-07-31 to 2026-04-30 | `sample_per_factor` | yes |
| MTUM and VLUE did not pass | `per_factor_verdict` = `NULL`, `NULL` | yes |
| QUAL has direction but is not robust | `per_factor_verdict.QUAL` = `EXPLORATORY_SIGNAL` | yes |
| 3-factor multiple-testing gate failed for all factors | all `bonferroni_pass=false` | yes |
| term-spread endpoint failed / constant 0 substitute | `term_spread_available=false` | yes |
| seed = 42 | `seed` | yes |

## Findings

No blocking or major findings.

1. **Core conclusion is source-aligned** — article extract lines 9, 23, 69-71; `experiments/k1512/k1512_results.json:25`
   The article says none of the three ETFs passed and that ETF-level factor names should not be treated as next-month excess-return predictors. This matches the aggregate `CONDITIONAL_PASS` verdict and 0/3 Bonferroni passes.

2. **QUAL is not overclaimed** — article extract lines 21, 23, 45-49; `experiments/k1512/k1512_results.json:81`
   Source has `QUAL` θ̂ = -0.0065, NW t = -1.07, NW p = 0.286, Bonferroni fail. The article's "有一點方向，但不夠穩" framing is appropriate.

3. **Lookahead / timing is acceptable for the stated research question** — article extract lines 5-7; `experiments/k1512/k1512.py:186`
   Source builds `D_t` from the rolling 12-month return ending at month t, uses lagged SPY/own returns for those controls, and defines `Y` as next-month own return minus SPY. Same-date VIX is documented as an after-month-end-close caveat in the experiment README.

4. **Minor wording caveat: term spread is described before the fallback is disclosed** — article extract lines 33 and 73; `experiments/k1512/k1512_results.json:25`
   The article later says FRED failed and term spread was replaced by constant 0. That disclosure is enough for publication, but the earlier "殖利率曲線資料" wording can read as if a live yield-curve control entered the model.

## Source-code audit

- PASS — Seed fixed at `42` for NumPy, random forest nuisance learners, and DML call path; see `experiments/k1512/k1512.py:58`.
- PASS — Outcome/feature timing follows `D_t` and `Y_{t+1}` construction; see `experiments/k1512/k1512.py:190`.
- PASS — Repeated cross-fitting uses `n_rep=20`, directly addressing the original fold-randomness issue; see `experiments/k1512/k1512.py:210`.
- PASS — Newey-West influence-score SE is mean-centered and reported across lag sensitivity `{1,3,6,12}`; see `experiments/k1512/k1512.py:172`.
- PASS — Multiple-testing gate uses Bonferroni α = 0.05/3 and requires corrected significance for a pass; see `experiments/k1512/k1512.py:256`.
- N/A — This article does not make variance-forecast QLIKE or DM/Harvey claims.

## Verification commands

```bash
uv run python -m py_compile experiments/k1512/k1512.py experiments/k1512/generate_article_figures.py
```

The full experiment script was not rerun during this article review because it fetches external yfinance/FRED data and would overwrite canonical artifacts. Existing canonical results, figures, and public image URLs were inspected; both article image URLs returned HTTP 200.
