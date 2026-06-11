# Codex 24h Review — mile_23312ae9 (K286)

- **Article**: 做了 305 次投資研究後，真正活下來的結論有多少？
- **Task**: `paper_review_mile_23312ae9`
- **Reviewed**: 2026-06-11 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **CONDITIONAL_PASS**

## Summary

這篇文章引用的核心數字和 `K286` 結果檔是對得上的：`305`、`86`、`28.2%`，以及文中舉的兩個代表性自我修正案例，都能在 `k286_session_final_results.json` 的 `results_by_rating` 與 `self_corrections` 找到對應來源。主軸「大部分直覺不該輕易過關」與這份 summary 的口徑一致。

需要補強的是 provenance 誠實度。`K286` 不是一個從原始 corpus 自動掃描、即時重算的 audit pipeline，而是一份 **手工整理的靜態 summary script**；README 也還是 placeholder。文章目前把它寫成一次「回頭整理 305 個實驗」的總體體檢，方向沒錯，但若讀者理解成「這些比例是由底層資料自動再現的完整普查」，source 並不足以支持那麼強的口徑。

## Numeric verification

下列主張與 `experiments/k286/k286_session_final_results.json` 一致：

| Article claim | Source | Match |
|---|---|---|
| 統計區間 2026-03-14 至 2026-03-22 | `title`, script header | ✓ |
| total experiments = `305` | `scale.total_unique_experiments` | ✓ |
| positive = `86` | `28 + 31 + 27` from `results_by_rating` | ✓ |
| hit rate = `28.2%` | `results_by_rating.hit_rate_percent` | ✓ |
| remaining non-positive/other = `219` | `results_by_rating.null_or_other` | ✓ |
| 深度研究系列最多、台灣時區次之 | `scale.experiment_series` (`K=136`, `T=46`) | ✓ |
| same-day bias 修正案例 | `self_corrections[0]` | ✓ |
| 4% → 8% 提領率被推翻案例 | `self_corrections[2]` | ✓ |

## Findings

1. **Core headline numbers are source-aligned** — `experiments/k286/k286_session_final.py:27-60`
   文章最重要的 3 個數字 `305 / 86 / 28.2%` 都能直接由 source 驗證。`86` 來自 `3-star + 2-star + 1-star = 28 + 31 + 27`，這點沒有誇張或算錯。

2. **Self-correction examples are fairly cited** — `experiments/k286/k286_session_final.py:152-186`
   文中提到的兩個代表性修正案例，`same-day timing bias` 與 `VT 不能把退休提領安全率從 4% 拉到 8%`，都明確存在於 `self_corrections`。這部分沒有把系統外的故事硬塞進 `K286`。

3. **Provenance is weaker than the article currently implies** — `experiments/k286/k286_session_final.py`
   `K286` source 是一個直接把 summary dict 寫進 JSON 的 script，不是從 `storage/memory`、`experiments/`、`research_log` 自動聚合重建出的 reproducible audit。這不代表數字一定錯，但代表它比較像一份 curated session memo。文章若要維持研究誠實，最好別讓讀者以為這是「按鈕一按就能從底層資料重算出來」的普查。

4. **One classification sentence should stay explicitly qualified** — `results_by_rating.note`
   source 自己註明：`219 null/other includes nulls, platform entries, AI reviews, and duplicates`。文章有提到其中一部分，例如「平台或流程項目、修正掉的舊結論」，這方向是對的；但如果未來改稿，建議把 **AI reviews / duplicates 也屬於這個 219** 補明，避免讀者誤解成 219 全都是失敗的投資假說。

5. **Series-distribution interpretation is plausible but inferential** — `scale.experiment_series`
   文章把 `K/T/...` 系列分佈解讀成「資源往較穩訊號方向集中」。這是合理敘事，但 source 只有 category counts，沒有直接證明「因為訊號較穩才集中」。這句最好維持現在這種較軟的語氣，不要再升級成因果判斷。

## Lookahead / timing audit

- N/A — 這篇不是單一預測模型或 backtest article，沒有新的 forecast timing / lag 邏輯可審。
- PASS on citation honesty — 文中提到的兩個「修正案例」都確實在 `self_corrections` 裡，不是事後另補的外部例子。

## Recommended fixes

1. 在文末資料來源句或正文前段補一句：`這份統計來自 K286 的研究系統整理摘要，而非自動從所有底層實驗檔即時重算的 audit pipeline。`
2. 把 `219` 的描述補完整成：`包括 null、平台/流程項目、AI reviews、重複項與後續修正項`，避免讓讀者把它全讀成「失敗的投資假說」。
3. 保持「資源會自然往那些地方集中」這種軟敘事，不要再往「已證明這些方向更穩」的因果語氣加碼。
