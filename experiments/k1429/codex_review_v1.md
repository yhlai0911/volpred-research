# K1429 Codex 24h Re-review — VERDICT: FAIL

**Reviewer**: Codex CLI 0.137.0 (GPT-5.4 medium reasoning)
**Reviewed at**: 2026-06-09 06:10 CST (~50 min after article publish 05:23)
**Article**: mile_072c3972 — 「財報前波動率反而縮水？NVDA 九次財報的 EAV 解剖」
**Files reviewed**: `experiments/k1429/k1429.py`, `experiments/k1429/k1429_results.json`

## SEVERITY 1 issues (block publish)

1. **檢定設計不成立** — `stats.ttest_rel(pre_rvs, baseline_arr)` 把每個 event 配對到同一個常數 `baseline_mean`，這不是自然配對資料，且把 baseline 當無誤差已知常數，會低估標準誤。`p_pre=0.0336`、`p_post=0.0049` 都不能當作可發表的正式顯著性證據。
   - `experiments/k1429/k1429.py:203-207`, `experiments/k1429/k1429_results.json:17, 65, 99`

2. **事件日定義與實作不一致** — 註解說 daily close 分析要把「next trading day 當 T」；實作用 `searchsorted(earn_date)`，對多數 after-hours 財報直接把公告當日當 `T=0`，沒有 shift。NVDA / MSFT 多數場次本來就盤後 → pre/post window 經濟意義錯位。
   - `experiments/k1429/k1429.py:32-33, 166-171`

## SEVERITY 2 issues (require revision)

1. Lookahead / hindsight baseline — `±10 days around earnings` 排除窗已是事後資訊
2. Multiple testing 敘事誤導 — NVDA pre p=0.034 Bonferroni 不通過；MSFT post p=0.0049 雖通過 0.00833 門檻但檢定本身缺陷
3. 「5 日 RV」實作是 5 個 rolling vol 的平均，不是單一 5 日 window
4. RV 名稱不精確（close-to-close annualized rolling vol ≠ realized variance estimator）
5. n=9 paired t inference 太脆弱（缺正態性、bootstrap、sensitivity）

## SEVERITY 3 issues (minor)

1. `significant_*` 用未校正 0.05 與 6 重檢定敘事不一致
2. `seed=42` metadata 寫但實驗為決定性
3. `get_trading_days_offset` / `valid_events` 程式碼未實際使用

## Narrative overclaim analysis

「反而縮水」「倍增」強敘事讓讀者誤以為已被嚴格驗證；NVDA pre Bonferroni 不成立、MSFT post 雖通過但檢定缺陷。AAPL 全 NS 表述較誠實。樣本「9 events × 3 firm × 2024-2026」與程式一致無問題。

## Recommended actions (v2 deliverables)

1. 區分 after-close / before-open，T=0 對齊真正交易日
2. 單一 window measure `sqrt(252/5 * sum r²)`，pre/post 各算一個值
3. Permutation test or moving-block bootstrap，把 baseline uncertainty 納入
4. 多重檢定後重新寫結論（NVDA pre 探索性訊號、MSFT post 較強訊號待嚴格方法確認）
5. 文章術語改為 5-day rolling annualized volatility
6. 若維持發佈，主標降級為探索性，明寫 Bonferroni 狀態

## Disposition

- Article 已加文末「⚠️ 編輯部後續校正」disclaimer（2026-06-09 06:14 CST）公開 Codex FAIL 與待修事項
- P1 followup task `daily_article_k1429_v2_methodology_fix` 已開（24h deadline）
- Article 未 unpublish（自揭警示優於沉默撤回）
- 修訂版完成後此 v1 review 歸檔 review_history

## Tokens used

31,424
