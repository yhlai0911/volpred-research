# Codex 24h-rule Narrative Review — mile_dc516a52

**Review date**: 2026-06-24
**Article**: 氣候新聞延燒越久，綠棕 ETF 的尾端風險：用免費資料未找到可靠證據
**Published**: 2026-06-23T19:00:21 UTC
**Reviewer**: Codex (gpt-5.4) via `codex exec --skip-git-repo-check`
**Scope**: Article narrative vs source code (K1367) consistency — NOT source-code review (already done in `codex_review.md`)

## Verdict

`CONDITIONAL_PASS` → corrigenda 已套用，文章現為 PASS。

## Issues found (5) + fixes applied

| # | Type | Original | Corrected |
|---|---|---|---|
| 1 | **Numerical / 研究誠實硬底線** | 「Welch 統計強度 1.30，達顯著水準（顯著性 0.20）」 | 「Welch t 值 1.30，p 值 0.20，未達顯著水準」 |
| 2 | Conclusion strength | 標題「綠棕 ETF 的尾端風險不會跟著升」 | 「綠棕 ETF 的尾端風險：用免費資料未找到可靠證據」 |
| 3 | Method consistency | 「VaR 穿越次數」（程式為 binary indicator） | 「VaR 穿越指標」 |
| 4 | Literature framing | Fahmy 2025「日內 tick 資料」（公開摘要無法確認到 tick 精度） | 「日內小時級／高頻資料」 |
| 5 | Literature framing | 「Fahmy 2025 的 IG-ACD-GARCH 通道在日內運作，tick 或分鐘頻率才能捕捉那個過程」 | 「小時級或分鐘頻率才能捕捉那個過程」 |

## PASS items (no changes needed)

- 69 aligned events / 18 focal tests / 0 通過 Bonferroni / Harvey `|t|≥3` — 與 results.json byte-exact 一致
- GDELT 3,440 筆、2017-01-01 至 2026-06-23；ETF 2017-01-04 至 2026-06-22 — sample 區間正確
- 9 個 target n 與 focal t-stats 全部四捨五入正確
- Bonferroni-adjusted p=1.0 全部 cell 一致
- 描述統計（duration median 7 / mean 10.3 / max 38；reaction gap median 1 / mean 1.4）正確
- Bootstrap CI `[-0.0131, +0.0956]` 與 event diagnostic 數字一致
- Lookahead guard 描述（z-score `shift(1)`、lagged 60-day sigma、`signal.shift(1)`）與程式碼一致
- OLS + HAC Newey-West、Bonferroni 18-cell、bootstrap 1000 次 + seed 42 全部一致
- 「Fahmy 2025 JBF firm-level / intraday / IG-ACD-GARCH」方向正確
- 全文有清楚標示「GDELT + 日頻 ETF 在這組資料找不到可靠訊號」與「不能否定 Fahmy 機制」的免責語句

## Residual issues（可選優化，未阻 publish）

- 「前一期新聞強度」應明確寫成 `peak_news_z_lag1`，程式未把 `daily_news_z_lag1` 放進 regressors
- Reaction gap 描述應補上「最多觀察事件開始後 5 個交易日」與門檻下限 `max(sigma, 0.005)`
- 「反應較慢的股票，VaR/ES 往往更高」較穩妥寫法為「response time 可改善 VaR/ES 等風險統計的精度」

## Process trail

- Codex full prompt: `/tmp/codex_full_prompt.md` (1968 lines, includes article + K1367.py + results.json + existing codex_review.md)
- Fix script: `/tmp/fix_mile_dc516a52.py` — 使用 `publisher._rewrite_feed_entry` 帶 lock + supabase sync
- Sanity check：fix script 對每個 substitution 都驗 forbidden phrase removed + expected phrase present；fail-fast
- Corrigendum metadata 寫入 `details.corrigenda` (date / trigger / fixes list / reviewer)
- Supabase sync: `articles: 2` 同步完成
- Mirror sync 401（既有 auth issue，不影響 Supabase 線上來源）

## Linked

- Source experiment: `experiments/K1367/`
- Source code review: `experiments/K1367/codex_review.md` (2026-06-23, source-integrity CONDITIONAL_PASS — 仍有效)
- Article: `storage/reports/feed.json` entry `mile_dc516a52`
- Task: `paper_review_mile_dc516a52` (hourly-12 claim)
