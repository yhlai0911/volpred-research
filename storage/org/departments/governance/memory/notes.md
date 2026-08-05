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

## 判準：gate 是否過度封鎖，看 block/候選 比值，不看 gate 數量

（2026-08-05，老闆點名「gate 太多」案）

7 日內 663 次阻擋只落在 30 個候選上。數量不是問題，**同一候選被同一 gate 反覆擋**才是。
比值 ≈ 1 = 健康（擋一次、修好就過）；≫ 1 = deny 訊息沒給出可走的出路。
極端案例 `event_reaction_coverage` 對單一 task 擋 246 次，且該 gate 的資料源同時被
`audit_health` 標記 malformed —— 活鎖，不是防護。

推論：**零觸發的 contract gate 不是老闆體感的來源**（沒擋到人就感覺不到），
不該因「看起來沒用」被列入收斂範圍。

## 缺口：Claude Code hook / git hook / merge gate 層完全沒有 deny telemetry

`pretooluse-bash-optimizer.sh` 不寫 deny log，其餘 hook 只回 permissionDecision 不落盤，
merge_worktree.sh 的 8 個 ABORT 點無拒絕 receipt。**無法計數的 gate 無法被評估、
也就無法被收斂。** 下次做 gate 盤點前，先確認這層是否已補上
`storage/logs/hook_denials.jsonl`（提案編號 5，2026-08-05 送經理）。

## 資料來源：control-plane gate 已有 canonical registry，不要另建清單

`config/control_gate_registry.json`（registry）＋ `src/volpred/ops/control_gate_lifecycle.py`
（lifecycle owner）＋ `storage/ops/control_gate_lifecycle_latest.json`（7 日 inventory，
含 per-gate trigger_count / blocking_count / distinct_candidates / audit_health）。
registry 強制每道 gate 帶 `incident_refs`，是全平台立項紀律最好的一層。
另一半（hook / git hook / CI）的 owner 是 `docs/governance/enforcement_layer_map.md`，
用 `scripts/audit_enforcement_map.py` 驗它有沒有過期——2026-08-05 當下是過期的。
