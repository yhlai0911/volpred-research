# mile_d95b730a Codex 24h Review — 2026-06-07

**Article**: `mile_d95b730a` 「美股昨晚跌了，今天台股會跌嗎？這個問題有答案，但答案沒你想的那麼好用」
**Backing experiment(s)**: `K501` primary, `I8` timing-bias caveat
**Reviewer**: Codex CLI
**Verdict**: **FAIL**

## Findings

1. **Article claim and K501 target are off by one Taiwan day**  
   `experiments/k501/k501_return_prediction.py:157, 163-168` sets `target = tw['ret'].shift(-1)` while `spy_ret_L1` is only forward-filled onto the same Taiwan trading date. That means the model row for TW day `t` uses the latest SPY return available before day `t`, but predicts **TW return from `t` close to `t+1` close**, not “美股昨天 → 台股今天收盤” as stated in [storage/reports/feed.json](</Users/yhlai0911/Desktop/volpred-research/storage/reports/feed.json:40>). The article’s core framing is therefore stricter than what the source code actually estimates.

2. **Unclean 0050 data contains an impossible -138.9% daily return**  
   `experiments/k501/k501_return_prediction_results.json` records `0050.TW.min_pct = -138.8853` and kurtosis `2321.8549`, while `k501_return_prediction.py:149-188` never calls `clean_tw50_data()` or any winsorization. This is a hard data-quality failure. The headline `15.6%` OOS R², `67.5%` hit rate, and `5.66` Sharpe for Taiwan are all computed on a series already flagged as corrupted by the artifact itself.

3. **“Strategy Sharpe 5.66 / cumulative 700%” is not a tradable backtest, only sign(prediction) × close-to-close return arithmetic**  
   `k501_return_prediction.py:532-584` defines strategy return as `np.sign(preds) * actuals` with **no transaction costs**, no execution timestamp, and no removal of the overnight gap that the article itself says is untradable. The caveat is mentioned in prose, but the article still foregrounds `5.66` and `700%` as if they were strategy-level evidence. Source-wise, they are not implementation-grade trading results.

4. **Artifact provenance is inconsistent with the path cited in the article**  
   `k501_return_prediction.py:942-946` writes output to `experiments/k501_return_prediction_results.json`, but the article cites `experiments/k501/k501_return_prediction_results.json` in [storage/reports/feed.json](</Users/yhlai0911/Desktop/volpred-research/storage/reports/feed.json:40>). Current repo state does contain the latter file, but that path is not what the checked-in script writes. Reproducibility / byte-for-byte provenance is therefore broken.

5. **The article’s `3.09 → 0.87` I8 downgrade is not directly traceable from a local experiment artifact**  
   The exact `I8` numbers quoted in [storage/reports/feed.json](</Users/yhlai0911/Desktop/volpred-research/storage/reports/feed.json:40>) are referenced by K501’s caveat text, but the review could not locate a canonical `experiments/<id>/` artifact that directly emits those two numbers. Since the article presents them as numeric evidence, this is a provenance gap unless the specific I8 artifact is surfaced and linked.

## Conclusion

This draft should **not** be promoted or republished in its current form. The central narrative “美股昨天跌，台股今天收盤方向可被高精度預測” is not supported cleanly by the checked-in source because K501 has a day-alignment mismatch, an unclean 0050 outlier, and non-tradable close-to-close pseudo-strategy metrics. Fix K501 first, then regenerate the article from corrected results.
