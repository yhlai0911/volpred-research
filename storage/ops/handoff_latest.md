# Handoff — 2026-05-21 13:48 CST

**角色**：VolPred 自主運營經理（用戶=老闆，report-only，full autonomy）

---

## 立即next task（最高優先）

**crypto-fear-channel 3 個 BLOCKING 修訂** — 論文方法段與 `experiments/k1025/k1025.py` 實際 code 不符：
1. §4.3 QR：文稿寫 lagged BTC_RV_{t-1}+1000 bootstrap，code 實為同日 VIX_t~BTC_RV_t 無 bootstrap
2. §5.3 subperiod Granger：文稿寫 AIC lag，code 實為 lag 1-3 挑最小 p-value（lag mining，無多重檢定校正）
3. §4.5/§7 OOS：文稿寫 AIC AR(p) rolling，code 為固定 lag expanding-window，且 2019-01-01 同時落 IS+OOS
詳見 `paper/crypto-fear-channel/review_history/v5_independent/codex_review.md`。修法：逐項決定「改論文敘述對齊 code」或「改 code 對齊論文」（研究誠實三選一），不可造假。修完重跑 reproduce + 獨立審查。

之後 prg-periodic-garch（資訊集不對等）+ vt-crowding-abm（threshold 內生校準）同樣待修。

## 本 session 已完成

- **排程失敗徹查**（5 根因修復）：hourly-dispatch fd limit / host_cron_fail regex 死 / banner 由 piggy-back 發 / feed.json 並發 crash / market_daily nk225 400。commit `e4154466` `f1bdea2d`。
- **CLI 文件**：agy headless 可用，第三 agentic CLI；gemini_ask.py 計費通知。`91400ffc` `aa423657`。
- **論文 portfolio 審計**：3 篇「ready」獨立 Codex/agy 審查全 REJECT → 降回 `working`；vt-insurance-cost 過度宣稱更正；paper-update 同步 title bug 修；paper-upsert --status downgrade bug 修。`80cb6687` `5a3d7fce` `a3eff249`。
- **規則**：時間戳規則 `1e8834e2`；回應後流回 ops loop 規則 `ff3c0420`。
- 巡檢：dashboard 7/7 OK；hourly-dispatch 09:07 異常（exit 78 無 banner，10-13:07 疑似 Mac 睡眠未 fire）→ 已 `launchctl kickstart` 重啟恢復；agy 2 個孤兒進程已 kill；K1387 = NULL 已入 knowledge.json。

## 待驗證 / 候補

- hourly-dispatch 已 kickstart，驗下一班 14:07 是否 exit 0 + 寫 canonical banner。
- agy headless **會 hang**（crypto-fear 重審跑 1h37m 未完被 kill；`--print-timeout` 不可靠）→ 用 agy 必須包外部 timeout（perl alarm）。候補：寫進 reference_antigravity_cli memory。
- 無進行中背景 agent（hourly-dispatch 是 OS 層 worker，獨立）。

## 接續提示詞

讀 `storage/ops/handoff_latest.md` 後：先跑 `uv run python scripts/ops_dashboard.py` 巡檢；無 critical 就**直接開始 crypto-fear-channel 3 BLOCKING 修訂**（見上方 next task），這是研究誠實最高優先。修訂走主線程，逐項對 `experiments/k1025/k1025.py` 核對。完成後接 ops loop 派工，不停在等用戶。

---

## 🔴 OPEN INCIDENT — hourly-dispatch launchd 環境失敗（2026-05-21 16:35）

**症狀**：`com.volpred.hourly-dispatch` LaunchAgent 自 09:07 起每班 exit 78 (EX_CONFIG)、零 log 輸出。`launchctl print` runs 計數持續增加（已 27）證明有 fire，但每次秒級死。

**已確認**：
- 手動 `bash ~/.volpred/bin/cron_hourly_dispatch.sh` → 完全正常（寫 banner + claude 啟動）。
- launchd 跑同一檔 → exit 78、連 start banner 都沒寫。
- `bash -n` 語法 OK；launchd .err 空；prompt 檔存在。
- **不是** 單純 TCC 擋 Desktop log — 其他 LaunchAgent（collect-tw/release-pool）寫同目錄 log 正常。
- 06/07/08:07 今天還正常（exit 0），09:07 起壞 → 09:00 前後有東西變了。

**未釘死的根因方向**：hourly-dispatch 是唯一跑 `claude -p` 的 LaunchAgent — 需 `~/.claude/` config + keychain。launchd 環境可能拿不到（HOME / keychain / TCC for ~/.claude）。

**下一步（fresh context 查）**：
1. 讓 launchd 跑一個 probe script（`env > /tmp/probe.txt; whoami; ls ~/.claude`）比對 launchd env vs 手動 env 差異。
2. 查 09:00 前後系統有無變動（macOS update / TCC reset / keychain lock）。
3. 確認 claude -p 在 launchd 最小 env 下能否 auth。
4. 修法可能：plist 加 `EnvironmentVariables`（HOME 等）/ wrapper 開頭顯式 source 設定 / 或改回 host crontab piggy-back。

**暫時 mitigation**：手動 `bash ~/.volpred/bin/cron_hourly_dispatch.sh &` 可跑一班。本 incident 期間 16:33 已手動觸發一班（PID 5848）。

### incident 更新 16:38 — probe 結果

- 在 wrapper 第一行插 `echo >> /tmp/hourly_probe.txt` 探針 + kickstart → **`/tmp` 探針檔完全沒被建立**。
- 結論精煉：**launchd fire 後根本沒執行 script body**（連寫 /tmp 的第一行都沒跑）= exec-level 失敗，不是 script 邏輯問題。
- 排除：檔案權限（`-rwxr-xr-x` 與正常的 release_pool wrapper 相同）、quarantine xattr（兩者皆無）、語法（`bash -n` OK）。
- 仍未知：為何 launchd 能 exec `com.volpred.release-pool` 的 wrapper 卻不能 exec `com.volpred.hourly-dispatch` 的。兩者都 `~/.volpred/bin/*.sh`、同權限。
- probe 已還原（`git checkout` + 重新 cp TCC copy），wrapper 現為乾淨 committed 版。
- **下一步建議**：`launchctl print gui/$UID/com.volpred.hourly-dispatch` 完整輸出比對 release-pool 的；查 plist 差異（ProgramArguments / WorkingDirectory / 有無 `Program` vs `ProgramArguments` 寫法差）；考慮 `bootout` + 重新 `bootstrap` plist；或直接重建 plist。
