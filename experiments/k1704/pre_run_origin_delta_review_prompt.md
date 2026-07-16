你是 K1704 的 primary-path Codex pre-run delta reviewer。唯讀審查 frozen commit
55ebed7832420aaacb1c3b6506e613648365c434，工作目錄是
/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704。

背景：先前 pre-run review 已攔下共同 ledger、raw byte cache 驗證、forecast coverage、
consensus self-inclusion 等問題；修正後 delta review 在 commit 7f63de5f1 給 PASS。
正式 raw rebuild 隨後 fail closed：HAR_RV5 在 24 個「當日 targets 皆正值」的 origin 因
lagged RV input 缺日而無法形成 raw forecast。這不是 estimator crash，也不能補值；舊設計
把 target positivity 當作唯一 eligibility，錯把事前不可預測 origin 當成 post-eligibility
forecast gap。

本次 delta 只做以下修正：

1. 新增 build_origin_eligibility_mask：在 calibration 前，以 OOS、六 targets 正值、三個
   raw one-step forecasts 可由截至 t-1 的資料形成之交集，預先固定可評估 origin；並記錄
   各模型因 raw forecast unavailable 排除的數量。
2. build_common_evaluation_mask 接收 frozen origin_eligibility；eligibility 內任何 target 或
   calibrated forecast 缺值仍 fail closed，不能靜默縮樣本。
3. 結果 JSON 寫 origin eligibility audit；README 揭露此 policy；測試同時覆蓋「raw input
   缺失可事前排除」與「eligibility 內 calibrated gap 必須失敗」。

請完整檢查 experiments/k1704/K1704.py、test_K1704.py、README.md 以及 relevant diff
55ebed783^..55ebed783。特別判斷：

- eligibility 是否只依賴 origin t 當下可觀察的 target 與截至 t-1 可形成的 forecast，沒有
  未來資訊或 outcome-conditioned model selection；
- 這個兩階段 ledger 是否會掩蓋真正 forecast failure；
- 六 targets / 三 models 是否仍使用完全相同日期；
- audit 與測試是否足以讓排除原因可驗證；
- 是否需要在正式 rerun 前再修改。

輸出第一行必須恰為 `# PASS` 或 `# FAIL`。PASS 代表此 frozen commit 可使用剛由 raw
重建的 proxy cache 正式重跑；FAIL 則列出 blocker、檔案行號與最小修法。不要採信或解讀
現有 K1704_results.json；它仍是舊 provisional result。不要修改任何檔案。
