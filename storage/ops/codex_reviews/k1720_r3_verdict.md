VERDICT: FAIL

- R1 `RESOLVED` — 官方日曆逐日生效；11:30 截斷無法冒充 16:00 收盤，own-close gate 與樣本 reconciliation 正確。接受此規則對未來 cache 的目標 failure mode 是 sound。
- R5 `NOT_RESOLVED` — blocking：`README.md:58-59,216-217,237,331-332,396-397,408` 及 `k1720_rev3_report.json:175,185,205` 仍以 literal 寫入目前 sample scale，繞過 `format_sample_scale()`。引用 JSON pointer 不構成 single-producer。
- scope `RESOLVED` — 新增欄位均屬 R1/R5 provenance、diagnostics 或 audit；未改 estimator、threshold、bootstrap、Holm 或 decision tree。
- lookahead `RESOLVED` — `.shift(1)` threshold 與 prior-session close lag 仍正確。
- verdict_supported `RESOLVED` — rev3 數字依決策樹仍導出 `NULL`。

Required fix：移除 README/report 中展開的 sample-scale literals，或以 canonical renderer 從 `verdict.sample_scale` 生成並加機械檢查。

無法寫入指定檔案：workspace 為 read-only，寫入遭 sandbox 拒絕。
