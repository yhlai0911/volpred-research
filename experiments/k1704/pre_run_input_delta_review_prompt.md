你是 K1704 的 primary-path Codex pre-run delta reviewer。唯讀審查 frozen commit
22cac8786720c9da4acbf783f644033843842977，工作目錄是
/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704。

上一輪 `pre_run_origin_delta_review.md` 判定 FAIL：eligibility 依賴 raw forecast output，
可能吞掉 estimator failure；而且建立時間在 calibration 之後。這一輪只確認 blocker 是否
真正關閉：

1. `model_input_availability` 僅由 HAR lagged feature、EWMA lagged return count、GJR past
   training returns 建立 mask，不讀 forecast output。
2. `build_origin_eligibility_mask` 在 calibration 前執行；mask 認定 input available 但 raw
   forecast 非有限正值時立即 RuntimeError。
3. audit 對各模型保存 input-unavailable indices、count、SHA-256。
4. 測試以 `rv_5min[t-1]` 缺失造成 HAR input mask 排除多個受 rolling feature 影響的
   origins，另測 input mask=true 但 raw forecast=NaN 必須失敗；eligibility 內 calibrated
   gap 也仍須失敗。
5. 六個 targets、三個 models 最終必須共用單一 frozen mask；不得新增 lookahead。

請讀 experiments/k1704/K1704.py、test_K1704.py、README.md、上一輪 FAIL artifact，並檢查
diff 22cac878^..22cac878。輸出第一行必須恰為 `# PASS` 或 `# FAIL`。PASS 只授權使用本輪
剛從 raw 重建且有 byte verification 的 cache 重跑；不驗證舊 `K1704_results.json`。
FAIL 請列 blocker、行號與最小修法。不要修改任何檔案。
