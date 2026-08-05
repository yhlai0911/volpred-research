# governance 部門私有記憶

## 判準：帶已知會計缺陷的成本證據，不得直接驅動行為政策

（2026-08-05，R4 桌面 session 輪替案）

資源監控部報告同時給出「桌面互動佔 34.2%」與「fork 重複計算上界 60.1M」。兩者相衝：
若重複落在上界，結論反轉。**證據自帶誤差上界且上界足以翻轉結論時，五步 Gate 的第 1 步
（證據化症狀）就還沒過**，不得進第 3 步做底層修正，更不得驚動老闆改變工作方式。
處置：把政策案排在口徑修正案之後，標 blocked-on-<修正案>。

## 判準：無執行面的 concern 不算「缺 owner」

同案 C3。老闆桌面 Codex.app 的 session 壽命，平台沒有任何 hook / cron / deny 能干預。
這種 concern 就算沒有 owner，也不該為它新建機制——能寫出來的只會是 prose 提醒，
依 CLAUDE.md 升級路徑那是 strike 1 層級，不進 `docs/governance/enforcement_layer_map.md`。
正確出口是「對老闆的建議」，走經理的 proposals 流程。

## Owner-first 查法（本部門標準動作）

1. `docs/governance/enforcement_layer_map.md` 四張表（hooks / deny / CI / git hooks）
2. `config/runtime_schedules.json` 找語意最接近的既有 retention / cleanup job
3. 對疑似 owner 的 script 直接 `rg` 關鍵詞驗證它真的管這件事，不憑檔名推斷
