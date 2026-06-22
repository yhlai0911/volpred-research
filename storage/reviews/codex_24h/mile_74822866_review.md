# Codex 24h Review — mile_74822866 (K1512)

- **Article**: K1512：Double-ML 因子檢定顯示 ETF 層級沒有確認的非零效應
- **Task**: `paper_review_mile_74822866`
- **Reviewed**: 2026-06-22 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **PASS**

## Summary

這篇研究讀者版文章和 K1512 canonical source 對齊。它準確描述研究問題為 ETF-level next-month relative-return DML，不把結果外推成完整股票橫斷面因子溢酬；也準確呈現 `CONDITIONAL_PASS` 接近 null result、0/3 Bonferroni pass、`QUAL` 初版邊緣訊號在 repeated cross-fitting 後消失。方法限制，尤其 FRED term-spread fallback、same-date VIX/term-spread execution caveat、小樣本 DML 探索性，都有明確揭露。

## Numeric verification

| Article claim | Source | Match |
|---|---|---|
| Aggregate verdict = `CONDITIONAL_PASS`, research meaning near null | `verdict` | yes |
| MTUM/VLUE/QUAL NW p = 0.322 / 0.593 / 0.286 | `per_factor.*.nw_p` | yes |
| Bonferroni gate = 0.0167 and 0/3 pass | `bonferroni_alpha`, all `bonferroni_pass=false` | yes |
| MTUM n=145, θ=0.0164, NW SE=0.0166, NW t=0.990 | `per_factor.MTUM` | yes |
| VLUE n=145, θ=0.0178, NW SE=0.0333, NW t=0.534 | `per_factor.VLUE` | yes |
| QUAL n=142, θ=-0.0065, NW SE=0.0061, NW t=-1.066 | `per_factor.QUAL` | yes |
| OLS comparison p = 0.609 / 0.460 / 0.261 | `per_factor.*.ols_p` | yes |
| term spread unavailable, constant-0 fallback | `term_spread_available=false` | yes |
| seed = 42 | `seed` | yes |

## Findings

No findings.

1. **Core null/conditional framing is correct** — article extract lines 7-9 and 63-67; `experiments/k1512/k1512_results.json:25`
   The article explicitly states the result is `CONDITIONAL_PASS` but substantively near-null, and that no factor clears the strict gate. This matches the source.

2. **Methodology details match implementation** — article extract lines 23-29; `experiments/k1512/k1512.py:206`
   RandomForest nuisance learner parameters, `n_folds=2`, repeated cross-fitting, fixed seed, Newey-West influence-score SE, lag sensitivity, and Bonferroni pass condition all match the script.

3. **Lookahead / live-trading caveat is handled honestly** — article extract lines 17 and 27; `experiments/k1512/k1512.py:186`
   Source defines treatment at month t and outcome at t+1; lagged return controls use `.shift(1)`. The article correctly notes same-month VIX/term-spread controls require month-end observability and does not market the design as an immediate trading rule.

4. **QUAL fold-randomness lesson is source-supported** — article extract lines 49-53; `experiments/k1512/codex_review.md:43`
   The text says the original single-rep marginal QUAL signal shrank under repeated cross-fitting. This is exactly the Codex review chain's documented fix and result.

5. **Scope boundaries are explicit** — article extract lines 15-19 and 55-61; `experiments/k1512/README.md:78`
   The article does not claim to reject factor investing broadly. It limits the finding to ETF-level trailing-year return as treatment, not firm-level characteristics or Fama-French-style portfolio tests.

## Source-code audit

- PASS — Seed fixed at `42`; see `experiments/k1512/k1512.py:58`.
- PASS — `D_t`, lagged controls, and `Y_{t+1}` timing are explicit; see `experiments/k1512/k1512.py:190`.
- PASS — Repeated cross-fitting uses `n_rep=20`; see `experiments/k1512/k1512.py:210`.
- PASS — Newey-West influence score is mean-centered and lag sensitivity is stored; see `experiments/k1512/k1512.py:172`.
- PASS — Bonferroni gate uses α = 0.05/3; see `experiments/k1512/k1512.py:256`.
- N/A — This article does not make variance-forecast QLIKE or DM/Harvey claims.

## Verification commands

```bash
uv run python -m py_compile experiments/k1512/k1512.py experiments/k1512/generate_article_figures.py
```

The full experiment script was not rerun during this article review because it fetches external yfinance/FRED data and would overwrite canonical artifacts. Existing canonical results, figures, and public image URLs were inspected; both article image URLs returned HTTP 200.
