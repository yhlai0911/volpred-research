# Codex 24h Review — mile_96fb5f73 (K1314)

- **Article**: 「consistently outperforms」這句話的代價：GSP-HAR 在 5 個美股 ETF 上的誠實複製
- **Draft source**: `/private/tmp/mile_96fb5f73.md` extracted from `storage/reports/feed.json`
- **Task**: `paper_review_mile_96fb5f73`
- **Reviewed**: 2026-06-03 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **CONDITIONAL_PASS**

## Summary

這篇大方向是誠實的，`K1314` 的主數字、placebo 對照、anti-lookahead 敘事都和 source code 對得上，也沒有把單一 `SPY` 的強結果誇大成全面勝利。`"consistently outperforms"` 在這個 5 ETF 簡化複製裡不成立，這個結論合理。

需要降溫的是一處敘事力度：文章把 pooled `t=+3.73` 說成是 `SPY` 加上 `IWM` 那種 placebo artifact「拼湊出來」的結果。source 確實支持「只有 SPY 通過 robust rule、IWM placebo 甚至更強」，但沒有做正式的 pooled-stat contribution decomposition，所以這句應保守一些。

## Numeric verification

下列主數字與 `experiments/k1314/k1314_results.json` 一致：

| Draft line | Claim | Source | Match |
|---|---|---|---|
| 17-23 | 樣本期 / OOS / n_oos=1257 / QLIKE / DM-HLN / seed 42 | `config`, `per_asset.*.n_oos`, methodology in code | ✓ |
| 29-33 | SPY +14.07 / QQQ +1.00 / GLD -2.36 / TLT +1.05 / IWM +2.34 | `per_asset.*.qlike_improvement_pct` | ✓ |
| 35 | pooled t=+3.73 | `cross_asset.pooled_dm_hln.t_stat` | ✓ |
| 49-54 | placebo 對照表與 SPY-only robust 結論 | `placebo.per_asset.*`, robust rule in README | ✓ |
| 80 | `MARGINAL with placebo caveat` | `README.md` final verdict language | ✓ |

## Findings

1. **Main anti-overclaim message is correct and source-supported** — `/private/tmp/mile_96fb5f73.md:25-41,56-80`
   文章核心主張是：在這個 5 ETF 的簡化複製裡，`GSP-HAR` 並沒有呈現 paper 那種 `consistently outperforms` 的穩健樣貌。這點和結果一致。`k1314_results.json` 顯示只有 `SPY` 的 main DM `+5.41` 達到強門檻，`QQQ/TLT` 都只有小正、`GLD` 為負、`IWM` 雖正但 placebo 更強。把最終口徑收在 `MARGINAL with placebo caveat` 是合格的研究誠實。

2. **Lookahead audit is clean** — `experiments/k1314/k1314.py:99-109`, `experiments/k1314/k1314.py:130-157`, `experiments/k1314/k1314.py:181-197`
   HAR feature 明確使用 `rv.shift(1)`；graph filter 在每個日期 `t` 都用 `rv.iloc[:i]` 的嚴格過去資料；walk-forward OLS 只用 `< dt` 的 training window。這篇文章在 lookahead 維度可直接過。

3. **Placebo framing is methodologically valid** — `experiments/k1314/k1314_placebo.py:26-40`, `experiments/k1314/k1314_placebo.py:82-129`, `experiments/k1314/README.md:99-112`
   placebo 不是臨時補洞，而是有固定 seed、固定架構、只替換 graph information 的 sanity check。文章把它拿來區分「真 graph signal」與「extra-regressor variance artifact」是合理的，因為這正是 `k1314_placebo.py` 的設計目的。

4. **One sentence overstates what the pooled result decomposition proves** — `/private/tmp/mile_96fb5f73.md:54`, `experiments/k1314/k1314_results.json:103-149`
   文章寫 pooled `t=+3.73`「其實是 SPY 一個資產撐起來的、加上 IWM 那種 placebo-can-do-the-same 的虛假貢獻拼湊出的結果」。目前 source 能直接證明的是：
   - pooled 統計量確實存在；
   - robust real signal 只剩 `SPY`；
   - `IWM` 的 placebo `t=+4.30` 大於 main `t=+1.49`。

   但 source 沒有做 pooled DM 對各資產的正式貢獻分解，所以「拼湊出的結果」屬於合理推論，不是已被單獨檢定的事實。這句建議降成「pooled 顯著很大程度受 SPY 主導，且 IWM 顯示 placebo 也可產生類似表面改善」。

5. **`K1314` 的正式 verdict 仍是 `MARGINAL`，文章最好不要讓讀者以為是完整否決** — `/private/tmp/mile_96fb5f73.md:69-80`, `experiments/k1314/k1314_results.json:115-121`, `experiments/k1314/README.md:114-124`
   文章最後其實有把口徑收回來，這是好事。但如果未來改稿，仍要維持現在這種精細區分：`not consistent` 不等於 `full NULL`。source 還是留下了 `SPY` 的真訊號空間，因此最誠實的說法是「不支持廣泛一致 outperform」，不是「GSP idea 被推翻」。

## Lookahead audit

- PASS — HAR features use `rv.shift(1)` and lagged rolling means,見 [k1314.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1314/k1314.py:99)。
- PASS — graph filter at date `t` uses strictly past `rv.iloc[:i]`,見 [k1314.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1314/k1314.py:130)。
- PASS — walk-forward OLS trains on `< dt` only,見 [k1314.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1314/k1314.py:181)。

## Recommended fixes

1. 把 `/private/tmp/mile_96fb5f73.md:54` 那句改保守一些，例如：`Pooled DM-HLN t-stat 雖然達到 +3.73，但這個 pooled 顯著主要由 SPY 拉動，且 IWM 顯示 placebo 也能產生類似表面改善。`
2. 保留現在的 `MARGINAL with placebo caveat` 口徑，不要把它改寫成 `NULL` 或「GSP 無效」。
3. 若想再強化論證，應另做 pooled loss-differential 的 leave-one-asset-out 分解或 bootstrap attribution；在那之前，避免把 pooled 顯著的來源講成已被正式證明。
