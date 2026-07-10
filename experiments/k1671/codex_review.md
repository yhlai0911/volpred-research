# Codex Review — K1671

Verdict: **PASS_WITH_NULL_AND_PARTIAL_NUANCE**

## Checklist

1. **Lookahead**
   - PASS. 成交量門檻用 `rolling(VOL_WINDOW).mean().shift(1)`，今日 volume 不進入自己的門檻。
   - PASS. 事件訊號在 `evaluate_signal()` 和 `strategy_returns()` 都用 `signal.shift(1)` 對齊 same-index return，等價於 signal at t-1 -> return at t。
   - PASS. Pooled diagnostic 使用已 lag 後的條件報酬 series，先按日期聚合，再做 HAC。

2. **公平比較**
   - PASS. A/B 兩個迷思在同一批 9 資產、同一資料來源、同一 2x previous-20d volume threshold、同一 lag convention 下比較。
   - PASS. 經濟價值加了 5 bps 單向成本，並提供全期等權 buy-and-hold 對照。

3. **Seed**
   - PASS. 所有 bootstrap 使用 seed=42 加 deterministic offset；results.json 記錄 seed、reps、block。

4. **統計檢定**
   - PASS. Per-asset primary 使用 hit-rate baseline test + block bootstrap mean-diff CI，18 個 primary cells 做 BH-FDR。
   - PASS. Cross-asset pooled 僅標為 diagnostic，且遵守 K1355 date-level aggregation，不把 asset-day 當 iid。

5. **結論強度**
   - PASS. README 沒把「量先價行」寫成全 null；明確承認 2317.TW 通過 BH、pooled diagnostic 為正。
   - PASS. README 也沒把 pooled diagnostic 升格成普世規則，並把「爆量長黑隔日續跌」與「量先價行」分開下結論。

## Notes

- `scripts/lookahead_audit.py --strict` 的全域掃描仍因歷史舊實驗 unverified patterns exit 1；K1671 新檔未出現在 unverified 清單。源碼級人工審查已確認 K1671 的 lag 防線存在。
- 本任務是 stale backlog closure。K1659/K1667 已是同題主結果；K1671 的增量是 stricter previous-volume threshold + 9-asset replication。
