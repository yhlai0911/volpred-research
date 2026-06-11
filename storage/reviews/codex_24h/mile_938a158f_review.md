# Codex 24h Review — mile_938a158f (K453)

- **Article**: 跌的時候才算數：RS⁻ 跨 8 資產波動率預測力實測
- **Task**: `paper_review_mile_938a158f`
- **Reviewed**: 2026-06-11 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **CONDITIONAL_PASS**

## Summary

這篇文章的主結論大方向和 `K453` source 一致：RS⁻ 的增量預測力不是普遍存在，而是高度集中在美股大型股指；lookahead 控制也乾淨，`shift(1)` 有明確實作。主表中的 `SPY / QQQ / EEM / BTC / 0050` 數字大多能和 `k453_semivar_cross_asset_results.json` 對上。

需要收斂的是兩個敘事點。第一，source 的預測目標其實是 **next-day absolute return `|r_{t+1}|` proxy**，不是直接的 next-day RV / variance；文章通篇寫成「隔天波動率」會讓口徑偏寬。第二，文中把「同時顯著且 OOS R² 為正」幾乎收斂成只有 `SPY` / `QQQ`，但若照表內 `M2 vs M1` 標準，`IWM` 也符合 `DM p=0.046` 且 `R²_oos=0.018`。如果要把 `IWM` 排除，應明講原因是它 **未過 Harvey |t|>3 且 bootstrap p=0.071**，而不是直接讓讀者以為只有兩檔存活。

## Numeric verification

下列主張與 `experiments/k453/k453_semivar_cross_asset_results.json` 一致：

| Article claim | Source | Match |
|---|---|---|
| OOS 期間 2023-01-01 至 2025-12-31 | `methodology.OOS_period` | ✓ |
| SPY `M3 R² = 0.153` | `per_asset_results.SPY.models.M3_HAR_semi.R2_oos=0.153488` | ✓ |
| QQQ `M3 R² = 0.117` | `per_asset_results.QQQ.models.M3_HAR_semi.R2_oos=0.117033` | ✓ |
| EEM `M3 R² = -0.058` | `per_asset_results.EEM.models.M3_HAR_semi.R2_oos=-0.05835` | ✓ |
| BTC `M3 R² = -0.011` | `per_asset_results.BTC-USD.models.M3_HAR_semi.R2_oos=-0.011195` | ✓ |
| 0050 `M3 R² = -0.001` | `per_asset_results.0050.TW.models.M3_HAR_semi.R2_oos=-0.00066` | ✓ |
| SPY `M2 vs M1 p=0.007` | `per_asset_results.SPY.dm_tests.M2_vs_M1.DM_pval=0.007192` | ✓ |
| QQQ `M2 vs M1 p=0.004` | `per_asset_results.QQQ.dm_tests.M2_vs_M1.DM_pval=0.004015` | ✓ |
| EEM `M2 vs M1 p<0.001` | `per_asset_results.EEM.dm_tests.M2_vs_M1.DM_pval=0.0` | ✓ |
| BTC `γ=-0.012` 且不顯著 | `gjr_gammas.BTC-USD.gamma=-0.011883`, `gamma_pval=0.503187` | ✓ |
| SPY `γ=0.241`、QQQ `γ=0.205` | `gjr_gammas.SPY/QQQ.gamma` | ✓ |
| `gamma vs r2_gain` Pearson `r=0.81, p=0.014` | `cross_sectional_analysis.pearson.gamma_vs_r2_gain_M2` | ✓ |

## Findings

1. **Lookahead control is clean** — `experiments/k453/k453_semivar_cross_asset.py:283-291`
   五個 predictor 都先 `shift(1)`，target 才是當日 `abs_ret`。這份 source 在 timing 上沒有 same-day leakage，文章的「用 t-1 資訊預測 t」主軸成立。

2. **Target is `|r_{t+1}|` proxy, not direct next-day volatility** — `experiments/k453/k453_semivar_cross_asset.py:263-291`, `k453_semivar_cross_asset_results.json.methodology.target`
   source 明寫 `target: next-day |return|`，M1/M2/M3 全部是在預測 `|r_{t+1}|`。這可以被視為波動 proxy，但不等於直接預測 `RV_{t+1}` 或 `σ²_{t+1}`。文章如果通篇寫成「隔天波動率」而不補 `|return| proxy`，嚴格來看口徑偏寬。

3. **「真正同時顯著且 OOS R² 為正的，主要是 SPY 和 QQQ」這句過度收斂** — `per_asset_results.IWM`
   `IWM` 的 `M2` 其實也滿足 `DM p=0.046393 < 0.05` 且 `R²_oos=0.01833 > 0`。它當然比 `SPY/QQQ` 弱，因為 `bootstrap p=0.071`、`passes_harvey=false`，但如果文章的判準是「顯著 + 正 R²」，就不能直接把 `IWM` 隱掉。建議改成「最穩的是 SPY/QQQ；IWM 只有邊際證據」。

4. **Model labeling is occasionally blurred between `M2` and `M3`** — article table vs narrative, `per_asset_results.*.dm_tests`
   主表列的是 `M2 vs M1 DM p 值`，但 EEM 段落很容易被讀成「因為表上的 DM 顯著，所以 `M3` 證明有效」。EEM 在 source 裡剛好 `M2` 和 `M3` 都顯著，所以沒有造成數字錯誤；但這種寫法在 `IWM / 0050 / BTC` 會讓證據層次變得模糊。建議各段明確標 `M2` 或 `M3`，不要混稱。

5. **Main thesis remains source-supported after tightening** — `summary.verdict="EQUITY_SPECIFIC"`
   `K453` 的正式 summary 是 `EQUITY_SPECIFIC`，而不是 universal success。文章把 takeaway 收在「工具和資產要配對」，這和 source 一致；只要把 target proxy 與 `IWM` 邊際案例講清楚，整篇仍可成立。

## Lookahead audit

- PASS — predictors are built with explicit `shift(1)`,見 [k453_semivar_cross_asset.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k453/k453_semivar_cross_asset.py:283)。
- PASS — OOS evaluation uses fixed pre-2023 training sample and 2023-2025 holdout,沒有用未來資料回填特徵，見 [k453_semivar_cross_asset.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k453/k453_semivar_cross_asset.py:293)。

## Recommended fixes

1. 把「隔天波動率」至少在方法段改成「**隔天 `|return|` 波動 proxy**」或等價說法，避免把 proxy 講成直接 volatility target。
2. 把「真正同時滿足顯著且 R² 為正的，主要是 SPY 和 QQQ」改成「**最穩的是 SPY 和 QQQ；IWM 只有邊際證據，未過 Harvey / bootstrap 較弱**」。
3. 在 EEM / BTC / 0050 那段把 `M2` 與 `M3` 標籤拆開寫，避免讀者把 `M2 vs M1` 的 DM p 值誤套到 `M3`。
