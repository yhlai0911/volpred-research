# K1328 Codex Code Review

**Date**: 2026-06-14 16:09 台灣時間
**Reviewer**: Codex CLI 0.137.0 (ChatGPT auth, gpt-5.4 default)
**Verdict**: **CONDITIONAL_PASS**
**Triggered by**: `K1328_v2_fix_methodology`

## Verdict

v2 已修掉 v1 的兩個核心方法論錯誤：Stage A 改成只在 `2017-01-03` 至 `2020-12-31` 的獨立 holdout 選 HAR scheme，Stage B 才用 `2021-01-04+` 做 final OOS；且 HAR、ElasticNet、RandomForest、XGBoost 全部共用同一個 `expanding + refit_every=21` schedule。lookahead、seed、proxy 揭露都合格。

但結果本身只能到 **CONDITIONAL_PASS**：pooled OOS 下 ElasticNet 的 QLIKE 略優於 HAR（`3.56437 < 3.56486`），DM-HLN `t=2.81`、`p=0.0049`，仍**未達**專案硬門檻 Harvey `|t| > 3`。因此可說「HAR 仍是強 benchmark，沒有被統計強度明確打破」，**不能**說「HAR ceiling confirmed / PASS」。

## Checks

1. **Lookahead safety**
   - `load_asset_frame()` 只用 `shift(1)` 後的 `rv_lag1`, `rv_mean5`, `rv_mean22`
   - target 仍是當期 `log(rv_t)`，無 same-day leakage

2. **Seed discipline**
   - `SEED = 42`
   - ElasticNet / RandomForest / XGBoost 均固定 seed

3. **Fair comparison**
   - Stage A 僅在 selection window 選 scheme
   - Stage B final OOS 與 selection window 完全分離
   - 四個模型共用同一個 expanding / 21d refit cadence

4. **Conclusion strength**
   - `k1328_results.json` 已把 verdict 降為 `CONDITIONAL_PASS`
   - summary 與 pooled DM 結果一致，未再 overstate

5. **Honest disclosure**
   - README 與 results 都明示這是 daily squared-return proxy，不是假裝 5-min RV 複現

## Residual limitation

- 這仍是 daily squared-return proxy 測試，不是 paper-grade intraday RV。可用來回答「fit scheme + matched schedule 下，HAR 是否還是很難被常見 ML 明顯打破」，但不該外推成對高頻 RV 文獻的完整 replication。
