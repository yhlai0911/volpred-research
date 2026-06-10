# Codex 24h Review — mile_41b7c7d0 (K1400)

- **Article**: 退休時房貸該一次還清嗎？模擬 1 萬次後，答案其實沒那麼直覺
- **Task**: `paper_review_mile_41b7c7d0`
- **Reviewed**: 2026-06-10 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **PASS**

## Summary

這篇文章的核心排序、數字口徑與 `experiments/K1400/k1400.py` / `experiments/K1400/k1400_results.json` 一致，沒有新的 lookahead、未標示假設，或把模擬結果講成因果定律的 overclaim。文章有清楚交代這是 `TWII` 月資料 + block bootstrap、baseline 是房貸 2.2% 與「含息 +3.5%/年假設」版本，主結論也守在「B 繼續繳在這組歷史分布下破產率最低，但不是全面無風險優勢」這個證據範圍內。

我沒有看到需要阻擋發布的問題。唯一值得記一筆的是：`median_bust_month` 在 source code 是以 `m=0` 起算的月 index，文中寫「第 217 / 192 / 205 個月」若要嚴格對應日常語言，會更接近第 218 / 193 / 206 個月。這是敘述層的小 off-by-one，不影響排序、破產率或終值主張。

## Numeric verification

下列主張與 source 對齊：

| Draft claim | Source | Match |
|---|---|---|
| 資料期 `1997-08` 至 `2026-05`、10,000 paths、30 年、block=12、seed=42 | `meta.data_period`, `n_paths`, `horizon_months`, `block_size`, `seed` | ✓ |
| baseline 房貸 2.2% 含息版破產率 A/B/C = `32.7% / 30.5% / 31.5%` | `sensitivity_total_return["2.2%"]` | ✓ |
| 含息版終值中位數 A/B/C = `1617 / 2414 / 1992` 萬 | `final_p50` ÷ 1e4 | ✓ |
| 含息版 95 分位終值 A/B/C ≈ `3.25 / 4.45 / 3.85` 億 | `final_p95` | ✓ |
| B 在三組房貸利率下破產率都最低 | `sensitivity_total_return` 與 `sensitivity_price_only` | ✓ |
| 股息處理是額外假設 `+3.5%/年`，不是實際 TR 序列 | `DIV_YIELD_ANNUAL = 0.035`, `meta.dividend_yield_annual_assumed` | ✓ |

## Findings

無重大 findings。

## Lookahead audit

- PASS — 模擬只重抽歷史月度 `log returns`，沒有用任何未來狀態變數決定當期部位。
- PASS — `simulate_strategy()` 的順序是「月初資產 → 月底報酬 → 月底提領」，和 README 的 timing 說明一致，沒有偷看下一期報酬。
- PASS — 隨機程序固定 `seed = 42`，重現性與研究誠實要求一致。

## Residual note

`median_bust_month` 是以 0 起算的 index；因此文中的「第 217 個月 / 第 192 個月 / 第 205 個月」若要翻成日常月數，應各自再加 1。這是非阻塞的敘述精度問題，不影響本文主結論。
