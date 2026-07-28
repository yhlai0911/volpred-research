本輪認證：**FAIL**。

Estimator、provenance 與 NULL scope 沒有回歸；但 R3-2 的 RV completeness 仍有兩個可重現的 blocking counterexamples，因此尚不可寫入 `knowledge.json`。

## Blocking defects

1. **Count-only RV 盲點不只「剛好 1 天」。**

`_expected_trading_days()` 扣除 Columbus Day、Veterans Day 等期貨實際仍交易的日子，因此會低估真實交易日數。方向確實更 permissive，但這也直接反駁「共同短少 ≥2 天一定抓得到」。

具體反例：2020-10 的 calendar expected 是 21 天，cache 中所有 22 商品實際都有 22 天。把所有商品共同截短 2 天後：

- `max(ndays) = 20`
- `expected - max(ndays) = 1`
- cross-sectional shortfall = 0
- **22/22 商品仍被判 `rv_complete=True`**

所以以下宣稱不成立：

- `rv_rule_detects` 稱共同短少 2 天以上皆可偵測；
- `rv_residual_blind_spot` 稱盲點只有「exactly ONE day」；
- `panel_span_is_complete_months_only: true`；
- README 的「3275 列皆為完整月份」。

應改用正確的期貨交易日曆，或擴大披露並撤回 complete-only 宣稱；若仍要認證完整月份，count-only frozen cache 需要獨立 endpoint 證據。

2. **帶日期的 cache 仍未升級成所宣稱的 “true endpoint test”。**

[K1694.py](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-e98b43fc-k1694/experiments/K1694/K1694.py:480) 容許月首與月尾各有最多 3 個 weekday gap。直接對 2020-06 注入日期欄位並讓所有商品共同少掉 6/30：

- `last_day = 2020-06-29`
- `rv_month_shortfall = 1`
- `rv_tail_gap_days = 1`
- **22/22 商品仍為 complete**

因此日期路徑仍保留那個它聲稱只存在於 count-only cache 的一日 endpoint 盲點。現有測試只確認結果字串變成 `"applied"`，沒有注入首尾截斷。需要依正確交易日曆核對 expected first/last trading day，並加入 endpoint truncation negative gates；否則不得稱為 true endpoint test。

## 已通過的主要檢查

- DCOT 跨月 entry-gap 修復有效。對認證月份逐一刪除任一週報未發現漏網位置；GOLD 2024-10 反例現在確實形成 14 日 gap。
- 前月尾端或整月缺報會傳導到下月 entry gap；若前月只因內部缺報被排除但最後一份報告仍存在，下月可獨立認證，而 adjacency guards 會阻止跨缺月差分，行為合理。
- `MAX_DCOT_GAP_DAYS=9` 相對實測正常 gap 6/7/8 天有明確 separation；單次刪報形成至少約 12–16 天，不像為結果 fitted。
- Absence wording、結論段與圖標題已改為 NOT SUPPORTED；未見殘留的直接 absence assertion。
- 3275/3275 overlap 數值目前從 estimation frame 計算，其他 README/result 數字母體一致。
- Bootstrap estimator、shared sample/RHS、stationary bootstrap、missing-value guards、t−2 adjacency、PIT regime timing 均未見回歸。expanding moments包含 label 月本身、再 lag 到下一月使用，時序合理；24 個月 warm-up 是明示的樣本要求。
- Dynamic controls 不足以合理解釋穩定的正向 interaction；有效時間自由度與 synthetic publication-date 限制披露強度適當。後者阻止 predictive claim，但不阻止謹慎的 ex-post association。
- Provenance 一致：script、results code trace、spec entrypoint 均為 `92b0b771…`；result bytes 與 canonical identity 均為 `7075ab8f…`。

另有非阻塞文件錯誤：README 第 127 行仍引用已刪除的舊 key `fcm_avail_inside_outcome_month_rows`；round-2 歷史表也仍以現在式描述已退役的 completeness 規則。

本輪認證的是 FAIL：R3-2 尚未實質完成，39 個 mechanical gates 沒有覆蓋上述兩個反例。

VERDICT: FAIL
