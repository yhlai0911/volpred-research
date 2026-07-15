# Refactor Plan — git-push-backup 單一排程 owner

**Status**: IMPLEMENTED，待 48 小時 production observation
**Triggered by**: `dreaming_persistent_alert_52425890cc2f99a1`
**Scope**: 排程 ownership；不改 push gate、研究資料或歷史告警紀錄

## 1. 證據與 strike 分類

同一個告警鍵 `52425890cc2f99a1…` 只代表相同標題，不能單獨證明相同根因。逐次查閱 `storage/logs/cron/git_push_backup.log` 後至少分成兩類：

1. 六個 distinct send windows 中，2026-06-28、06-29、06-30、07-14、07-15 共五次都是 host cron 無法讀 macOS Keychain：`could not read Username ... Device not configured`。
2. 2026-07-12 的一次是 source-encoding pre-push gate 阻擋損壞的 Python 檔；這是正確 fail-closed，不屬於排程認證故障。
3. 07-14、07-15 的整點 host fire 失敗後，同一小時的登入 session piggy-back/CI remediation 又成功，排除 GitHub outage、remote divergence 與 credential 本身失效；兩日間另有多次同錯誤被 90 分鐘 successful-fire window 抑制。
4. 認證類在 2026-06-28 至 06-30 已被診斷，當時靠手動移除 crontab entry 止血；07-14、07-15 復發，證明 canonical reconcile 能重建壞路徑。相同底層原因跨五個日期，符合 Three-Strike 結構修正門檻。

嚴格來說，不能宣稱「三個 dreaming run 都新增了同根因 fire」：07-12 是 encoding、07-13 沒有新 fire、07-14/15 才再出現 auth。此 plan 是依五個跨日同根因邏輯事件與使用者「立刻從底層修復」指示啟動，而不是拿 dreaming signature 代替逐次證據。

另有計數 caveat：06-28 同一秒因舊 dedup writer 競態實際送出六次 transport，但狀態最後只保留一次增量；所以 `send_count=6` 不是完整通知總數，也不應當成六個獨立根因。

## 2. 根因

`host_crontab_managed` 原本同時承擔兩個互斥語意：

- `install_host_crontab.sh` 把 `true` 解讀為「把 job 寫入 host crontab」。
- `run_due_jobs.py` 把 `false` 解讀為「禁止 piggy-back dispatch」。

因此 `git_push_backup` 若要保留可用的 piggy-back，只能標成 `true`；但任何 full/targeted canonical reconcile 都會重新安裝已知必敗的 host leg。文件宣稱手動移除，config 卻要求安裝，狀態必然漂移。

## 3. 結構修正

- `host_crontab_managed: false`：唯一語意是禁止 host-crontab owner，讓 canonical installer 自動移除該 entry。
- `piggy_back_enabled: true`：獨立授權 `run_due_jobs.py` 從登入 session 執行。
- `run_due_jobs.py` 只在此旗標明確為 `true` 時允許 `host_crontab_managed=false` 的 job；其他既有 disabled jobs 保持原行為。
- 回歸測試同時鎖定 config ownership 與 dispatcher opt-in，防止未來再把兩條執行路徑耦合。

## 4. 驗證與解除條件

1. 單元測試：host-disabled/piggy-enabled job 仍可被 dispatcher 選中；未 opt-in 的 host-disabled job 仍跳過。
2. 安裝器 dry-run/targeted reconcile：輸出不得含 `volpred-git-push-backup`。
3. 套用 targeted reconcile 後，live `crontab -l` 不得含該 entry。
4. 保留 `run_due_jobs` hourly fire，並觀察至少 48 小時；不得再出現整點 `Device not configured` host fire。
5. 告警鍵因混合不同 fail-closed 原因，不以清除歷史 dedup 記錄收尾；由 dreaming 的 48 小時 inactivity 規則自然解除。

非阻斷後續：push wrapper 應把 fetch/auth、source gate、remote rejection 分成不同 failure fingerprint，避免相同標題再次合併不同事故；這不影響本次單一 schedule owner 的完成判定。

## 5. Rollback

若 piggy-back 停火，先檢查 `check_alerts` LaunchAgent 與 `cron_last_run.json`，不要恢復 host crontab。緊急備份可在登入 session 手動執行 wrapper；修復 piggy-back owner 後再恢復自動化。
