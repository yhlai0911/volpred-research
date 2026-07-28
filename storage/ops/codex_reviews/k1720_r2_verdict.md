VERDICT: FAIL

無法寫入 `storage/ops/codex_reviews/k1720_r2_verdict.md`：目前 workspace 是 read-only，寫入遭 sandbox 拒絕；未修改任何檔案。

阻斷原因：

- R1 `NOT_RESOLVED`：11:30 whitelist 未驗證 official early-close 日期，正常交易日於 11:30 後斷檔仍會冒充收盤（`K1720.py:120-126,193-208`）。目前 8 日期對固定資料是完整的。
- R2 `RESOLVED`：HAC、joint stationary bootstrap 與 verdict inputs 正確。
- R3 `RESOLVED`：殘留 absorption 用語皆明確否定其證據力。
- R4 `RESOLVED`：Holm family 正確涵蓋 12 tests，無 bar-level claim。
- R5 `NOT_RESOLVED`：`K1720.py:687-688` 仍硬編 `~3 years`。
- Lookahead、rev1→rev2 數值變動及 NULL 決策樹均通過。
