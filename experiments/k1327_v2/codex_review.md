# K1327-v2 Codex Code Review

**Date**: 2026-06-14 14:32 台灣時間
**Reviewer**: Codex
**Verdict**: **PASS**
**Triggered by**: `K1327_v2_fix_methodology`

## Verdict

K1327-v2 fixes the core K1327 methodology failure. The primary comparison now holds training window and refit cadence fixed across HAR and multi-factor challengers, while expanding-window results are separated as sensitivity.

## Checks

1. **Matched primary comparison**
   - `HAR3`, `MF_Ridge_rolling_matched`, and `MF_ElasticNet_rolling_matched` all use `rolling=True`, `window=1000`, `refit_every=21`.
   - This removes the K1327 failure where the best challenger was expanding while HAR was rolling.

2. **Lookahead safety preserved**
   - K1327-v2 reuses K1327 feature construction, where every raw factor enters through `shift(1).rolling(...).mean()`.
   - Target remains same-row `rv_t`, so features are `t-1` and target is `t`.

3. **Reproducibility**
   - `SEED = 42`.
   - `uv run python experiments/k1327_v2/k1327_v2.py` completed and wrote `k1327_v2_results.json` plus chart.

4. **Verdict wording is appropriately limited**
   - Conclusion is `CONDITIONAL_PASS`, not `PASS`.
   - Summary states the matched rolling ElasticNet lowers QLIKE but remains below Harvey `|t| > 3`, and does not claim the original high-frequency Cinquetti design beats HAR.

## Residual Limitations

- This remains a public daily-data proxy, not the original 287 high-frequency factor dataset.
- The base helper script is imported from `experiments/k1327/k1327.py`; future edits to that helper could affect v2 reruns. The results JSON and chart are therefore the audited artifact for this run.

## Bottom Line

K1327-v2 is suitable for `CONDITIONAL_PASS` knowledge entry if a Python writer is used. The result is weak but methodologically cleaner: matched rolling multi-factor ElasticNet improves QLIKE versus HAR3 (`3.1606` vs `3.5971`) with DM-HLN `t=2.516`, below the Harvey threshold. The expanding-window sensitivity is stronger, so it must remain a sensitivity result rather than the primary model-class claim.
