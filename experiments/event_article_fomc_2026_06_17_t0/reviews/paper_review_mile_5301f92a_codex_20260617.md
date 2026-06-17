# event_article_fomc_2026_06_17_t0 / mile_5301f92a Codex 24h Publication Review

- Article: `mile_5301f92a` — "FOMC 決議前夕：VIX9D/VIX 比值 0.961，term structure 已把 6/5 的震盪完全解除"
- Source package: `experiments/event_article_fomc_2026_06_17_t0/`
- Supporting packages checked: `event_article_fomc_2026_06_17_t7`, `event_article_fomc_2026_06_17_t2`
- Reviewed files: `article.md`, `data.csv`, `gen_chart2.py`, `fomc_t7_results.json`, `event_article_fomc_2026_06_17_t2/results.json`
- Verdict: **CONDITIONAL_PASS**
- Reviewer: Codex
- Review date: 2026-06-17

## Bottom Line

The core article claim is supported: `data.csv` shows VIX `16.41`, VIX9D `15.77`, and VIX9D/VIX `0.960999` on 2026-06-16, so the headline ratio `0.961` and "backwardation has faded below 1.0" are evidence-matched. There is no DM/Harvey overclaim because the article is a descriptive event piece, not a formal forecast comparison. It should not be treated as a clean PASS until several secondary numeric/label issues are corrected.

## Matched Claims

- 2026-06-05: VIX `21.51`, VIX9D `23.92`, ratio `1.112041`.
- 2026-06-09: VIX `19.87`, VIX9D `22.14`, ratio `1.114242`.
- 2026-06-10 peak: VIX `22.22`, VIX9D `25.67`, ratio `1.155266`.
- 2026-06-12: VIX `17.68`, VIX9D `17.26`, ratio `0.976244`.
- 2026-06-16: VIX `16.41`, VIX9D `15.77`, SPY `750.33`, ratio `0.960999`.
- Ratio peak-to-6/16 decline: `1.155 - 0.961 = 0.194`, about `16.8%` of the peak.
- VIX9D drawdown from `25.67` to `15.77` is about `38.6%`, matching "超過 38%".
- SOFR path `3.67 -> 3.81 -> 3.96 -> 4.06` matches T-2/T-7 supporting files.

## Issues To Fix

1. **"從 6/5 到 6/16，共 11 個交易日" is wrong.** From 2026-06-05 to 2026-06-16 there are 11 calendar days, but the listed market observations are 8 trading dates: 6/5, 6/8, 6/9, 6/10, 6/11, 6/12, 6/15, 6/16. Revise to "11 個日曆日 / 8 個交易觀察日".

2. **SPY "收復 94%" is not supported by `data.csv`.** If the drawdown is measured from 2026-06-04 `757.09` to 2026-06-10 `725.43`, recovery by 2026-06-16 `750.33` is `(750.33 - 725.43) / (757.09 - 725.43) = 78.6%`, not 94%. Either correct to about `79%` or define a different denominator explicitly.

3. **Chart label typo in `gen_chart2.py`.** The annotation loop labels 2026-06-12 as `T-2\n0.961` while plotting value `0.976` (`gen_chart2.py:89-93`). Article text and data use `0.976`; regenerate `fig_spy_recovery.png` after fixing the label.

4. **"過去四場 FOMC 裡，T-0 最低的 ratio 出現在 4 月那場（0.915）" is unsupported.** The `0.915` figure comes from the T-7/T-2 comparison package, not a demonstrated T-0 ratio. Reword to "今年先前 FOMC 觀察窗口裡" or provide actual T-0 VIX9D/VIX evidence.

5. **"那場最終是 SPY 小漲、VIX 收平" needs evidence.** The checked T-2 results show 2026-04 FOMC T-2->T+0 SPY `-0.50%` and VIX `+0.79`, not "小漲、收平". If a different window is intended, cite and compute it.

## Lookahead / Overclaim Audit

- The T-0 article uses data through the 2026-06-16 close for a 2026-06-17 FOMC decision-day preview. That is a valid publication-time information set.
- The article does not claim formal statistical significance, DM, Harvey-Newey-West, or a backtested trading edge.
- Scenario probabilities and phrases such as "市場定價接近確定" are interpretive. They are directionally tied to SOFR futures, but should remain framed as scenario assumptions, not as formally estimated probabilities.

## Reproducibility / Provenance Risk

- The T-0 package has `data.csv` and `gen_chart2.py`, but no README/results JSON.
- `gen_chart2.py` regenerates `fig_spy_recovery.png` only; no committed generator was found for `fig_vol_term_structure.png`.
- The source of `data.csv` is not documented in the T-0 folder. Add a short README or script note identifying yfinance tickers and retrieval date.

## Actionable Items

1. Correct the article's `11 個交易日` and `94%` recovery statements.
2. Fix and regenerate the chart annotation for T-2 `0.976`.
3. Reword or substantiate the April FOMC `T-0 0.915` / "SPY 小漲、VIX 收平" claim.
4. Add T-0 provenance notes: data source, retrieval time, and chart-generation path for both figures.

