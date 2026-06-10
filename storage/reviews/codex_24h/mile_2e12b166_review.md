# Codex 24h Review — mile_2e12b166 (K1306)

- **Article**: K1306：SEC 10-K 管理階層語氣能預測個股月度 RV 嗎？Loughran-McDonald pilot — NULL
- **Task**: `paper_review_mile_2e12b166`
- **Reviewed**: 2026-06-10 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **PASS**

## Summary

這篇文章的核心結論和 `experiments/k1306/k1306.py` / `experiments/k1306/k1306_results.json` 一致，而且口徑有守住證據邊界。`K1306v2` 的兩個舊問題都已經反映在現行 code：forward window 改成從 `embargo_month_end` 之後的完整月份開始，小樣本 `HC1` guard 也提高到 `N >= 5`。因此文章把結果定性為 `NULL`、把 `β_tone` 解讀成「方向偏正但無法排除零效應」，這個 framing 是成立的。

我沒有看到新的 lookahead 或 DM/Harvey overclaim 問題。這篇可過。唯一非阻塞的 nit 是：`k1306_results.json` 的第一條 limitation 仍寫 `5 firms x 5 years`，但實際 `n_firms=4`、tickers 也是 `AAPL/GOOGL/MSFT/NVDA`；這是 source metadata 的 stale 字串，不影響本文主數字與結論。

## Numeric verification

下列主張與 source 對齊：

| Draft claim | Source | Match |
|---|---|---|
| 4 家公司、2020–2024、N=16 filing obs | `n_firms=4`, `n_filings=16`, `tickers` | ✓ |
| 四家公司都因 N 太小無法做有效 per-firm HC1 | `ols.per_firm.*.skipped = "n<5 insufficient df for HC1"` | ✓ |
| pooled bootstrap mean = `+0.211` | `bootstrap_pooled_beta_tone.mean` | ✓ |
| 95% CI = `[-3.79, +2.63]` | `ci_2_5`, `ci_97_5` | ✓ |
| `frac_positive = 0.856` | `bootstrap_pooled_beta_tone.frac_positive` | ✓ |
| lookahead discipline = filing + 1BD embargo, VIX 用 embargo 前 21 日 | `lookahead_check` + `build_panel()` | ✓ |

## Findings

無重大 findings。

## Lookahead audit

- PASS — `vix_window = daily_vix[daily_vix.index < embargo].iloc[-21:]`，VIX predictor 嚴格落在 embargo 前，沒有 same-day 洩漏。
- PASS — forward RV target 改為 `rv_series.index > embargo_month_end` 且 `<= embargo_month_end + MonthEnd(12)`，已排除 embargo 當月的 partial-month contamination。
- PASS — per-firm OLS guard 改為 `n_obs < 5` skip，避免 `HC1` 在 `df_resid < 2` 的假顯著。

## Residual note

`experiments/k1306/k1306_results.json` 的 limitation 字串仍寫「`5 firms x 5 years`」，與同檔的 `n_firms=4` 不一致。這是非阻塞 metadata stale，不改也不影響本文 `NULL` verdict，但下次若重跑或改稿，建議一併清掉。
