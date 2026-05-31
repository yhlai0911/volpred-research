# Codex 24h Review — mile_d3897886 (K1108 stack)

- **Article**: 晶圓代工財報日為什麼比較劇烈？我們連四層猜想全部失敗了，這篇講為什麼這對你是好消息
- **Draft source**: `/tmp/mile_d3897886.md` extracted from `storage/reports/feed.json`
- **Task**: `paper_review_mile_d3897886`
- **Reviewed**: 2026-05-31 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **CONDITIONAL_PASS**

## Summary

核心敘事大致成立：K1108 / K1108b / K1108c / K1108e 這條四層鏈都沒有產生可發表等級的正向機制證據，文中的主要數字也大致能對上各自的 `results.json`。

但草稿有幾個需要修掉的明確問題：

1. 有兩個 factual / claim-matching 錯誤。
2. 有兩個研究狀態已過時。
3. 有兩處結論強度超過本文證據邊界。

## Numeric verification

下列數字與實驗 JSON 一致：

| Draft line | Claim | Source | Match |
|---|---|---|---|
| 7 | K1108e max 統計強度 1.58 | `k1108e_results.json.verdict.max_abs_t_hac=1.5841` | ✓ |
| 27 | K1108 t=0.94 / underpowered | `k1108_results.json.verdict` | ✓ |
| 33 | 4 firms / 136 events | `k1108b_results.json.verdict` + README | ✓ |
| 35 | K1108b 幾乎貼零 | `Pool Wald t=-0.0003, p=0.9997` | ✓ |
| 43 | K1108c 135 events | `k1108c_results.json` | ✓ |
| 45 | K1108c t=1.34 | `t_HAC=-1.3395` | ✓ |
| 58 | K1108e matched 47 events | `k1108e README` / `results.json` | ✓ |
| 76 | SMIC PPE/Rev 約 2.6–3.8，TSMC 約 0.98–1.44 | `k1108e README` table | ✓ |
| 84 | partial-F p=0.102 | `k1108e_results.json.verdict.partial_f_p=0.1016` | ✓ |

## Findings

1. **Factual contradiction in the summary table** — `/tmp/mile_d3897886.md:93`
`「F 達顯著水準（顯著性 0.10）」` 與上一段 line 84 的 `p 值 = 0.102，連 10% 都過不去` 互相矛盾，也與 `k1108e_results.json.verdict.partial_f_p=0.101646...` 不符。這裡應明確寫成「未達 10% 顯著水準」。

2. **Harvey 2016 attribution is wrong** — `/tmp/mile_d3897886.md:17`
文中把 `t > 3` 的多重檢定高門檻寫成 `Campbell 嚴格統計 2016 那篇有名的論文`。本專案自己的實驗鏈與引用一貫使用的是 `Harvey, Liu & Zhu (2016)`，不是 Campbell。這會直接污染方法 provenance。

3. **Research-state stale: K1108f is not “next”** — `/tmp/mile_d3897886.md:104-126`
草稿寫 `下一輪 K1108F 會試 regime-split`、`K1108F 還在跑`。但 `experiments/k1108f/k1108f_results.json.timestamp` 是 `2026-04-17T16:37:03+00:00`，早就完成，而且結論也是 NULL。這篇 draft 若要留在系統裡，至少要註明這是舊版敘事，否則讀者會被過時狀態誤導。

4. **Research-state stale: K1108d is not “已在試”** — `/tmp/mile_d3897886.md:102`
文中寫 `K1108d 已在試，但 coverage 只有 8.9%`。實際上 K1108d 也已完成，`k1108d_results.json` 已給出 `H_D2_LOW_COVERAGE_PRELIMINARY` verdict；後續甚至還有 K1202 擴 coverage 到 96.3%。如果這篇要保留 draft 狀態，應至少標明「這是寫作當下的狀態」，不然時序會亂。

5. **Conclusion strength slightly overreaches on layer 1** — `/tmp/mile_d3897886.md:5`, `/tmp/mile_d3897886.md:95-97`
文章反覆寫 `四個實驗，四個都失敗`、`四層全部失敗`。但 K1108 第一層的正式 verdict 是 `INCONCLUSIVE`，不是 decisive null。對一般讀者可寫成「四次嘗試都沒找到支持證據」，但不宜把第一層直接寫成與後三層同級的「失敗」。

6. **Trading-edge statement is not directly supported by this article’s experiment set** — `/tmp/mile_d3897886.md:122`
`靠 capex 更新事件去做短線交易策略，從統計上沒有 edge` 超出了本文直接回顧的 K1108 / b / c / e 證據。這四個實驗是在檢驗 `foundry θ_EAV mechanism`，不是完整交易策略 backtest。若要保留這句，應改成「至少從這條機制線索看不出穩定 edge」，或直接引用那篇 K237 策略文的數字。

## Lookahead audit

- PASS — K1108/K1108b/K1108c/K1108e 這條鏈的事件變數與 control 都有明確 lag/PIT 規則，review 中沒看到 same-day signal × same-day return 這類 lookahead。
- PASS — K1108e 對財報資料用 `FY-end + 45 days <= event_date` 的 PIT 對齊，見 `experiments/k1108e/README.md:81-89`。

## AI 味 / 套路語

不重，但有 2 句偏平台自我行銷，建議降一點：

- `/tmp/mile_d3897886.md:110` `正因為這樣，這個平台才值得追蹤。`
- `/tmp/mile_d3897886.md:124` `願意公開那 80% 的人，給的 20% 才可信。`

這兩句不是翻譯腔，但有明顯「收束到品牌可信度」的推進感，會比前半段研究敘事更像宣傳文。

## Recommended fixes

1. line 93 改成 `未達 10% 顯著水準`。
2. line 17 / 112 把 `Campbell` 改回 `Harvey, Liu & Zhu (2016)`。
3. 將 K1108f / K1108d 的狀態改成寫作當時的歷史態，或直接更新為當前已完成狀態。
4. 把 `四層全部失敗` 改成 `四次嘗試都沒提供支持機制的證據`。
5. line 122 的 `沒有 edge` 降級為 `看不出穩定 edge`，除非另外補 K237 的直接策略數字。
