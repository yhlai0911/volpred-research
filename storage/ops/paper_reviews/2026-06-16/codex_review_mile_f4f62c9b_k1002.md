# Codex Source-Code Review - mile_f4f62c9b / K1002

- **Article**: 同一場模型擂台賽，最後只剩兩個人站著
- **Experiment**: `experiments/k1002/k1002.py`
- **Results**: `experiments/k1002/k1002_results.json`
- **Review timestamp**: 2026-06-16 06:20 台灣時間
- **Verdict**: **CONDITIONAL PASS**

## Findings

1. **No material lookahead found**.
   - Rolling refits train on `returns[s:t]`, excluding the forecast target.
   - GJR/EGARCH/HAR use lagged returns only; A4f uses `vix2[t-1]`; Macro-X uses 22-trading-day-lagged FRED variables and then `t-1` values.

2. **Article numbers match the result file**.
   - OOS: 2019-01-01 to 2026-04-07, `n_oos=1825`.
   - QLIKE ranking: A4f-N -8.361206, A4f-t -8.360525, Macro-X -8.269938, GJR-t -8.266282, GJR-N -8.262498, EGARCH-t -8.246500, HAR-ABS -8.199605.
   - VaR/ES scorecard: A4f-t 7/7, A4f-N 5/7, GJR-N 3/7, Macro-X 2/7, GJR-t 1/7, EGARCH-t 1/7, HAR-ABS 1/7.

3. **DM/Harvey caveat**.
   - The article does not explicitly claim formal statistical significance.
   - However, phrasing such as "直接把其他五個方法甩開" should be read as a reader-facing summary of QLIKE ranking plus MCS membership, not as a Harvey-significant pairwise claim against every non-A4f model.
   - In the result file, A4f-t vs EGARCH-t is not Harvey-significant (`|t|=1.956`), and A4f-N vs A4f-t is not significant (`|t|=0.457`).

## Recommendation

No correction required. Keep the conclusion scoped to SPY 2019-2026 and avoid adding stronger wording that implies pairwise statistical significance against every individual model.
