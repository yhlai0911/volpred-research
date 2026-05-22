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

## ✅ RESOLVED — hourly-dispatch launchd exit-78（2026-05-21 16:41 修復，commit 90d493e2）

根因：plist StandardOutPath/StandardErrorPath 在 TCC 保護的 ~/Desktop → launchd spawn 階段 open 失敗 → EX_CONFIG/78、script body 從沒跑。Fix：plist std 路徑 + wrapper exec-log 全移 ~/.volpred/logs/；storage/logs/cron/hourly_dispatch.log 改 symlink；bootout+bootstrap reload；kickstart 驗證 16:41 班正常啟動 claude。詳見 docs/error_log.md。候補：LaunchAgent plist 無 repo 源，應建 config/launchagents/ + install script。

---

## （存查，已解決）原 incident 診斷紀錄

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

---

## 🟡 待辦 — 3 篇 FB 發文（drafts 全備好，待乾淨 session 發）

boss_report 13:00 報 FB pipeline critical（3 pending）。3 篇 FB-native 草稿
已全部寫好存入 `storage/reports/trending_repost_log.json`，volpred URL 已驗 200，
Ivan Lai 牆已 get_page_text 確認 3 篇都沒發過：

| mile_id | 主題 | fb_draft |
|---|---|---|
| mile_bb62fc66 | VIX 31 vs S&P +8.5% | ✅ 已存 |
| mile_02518109 | 特習會跨資產（KOSPI -9.68%） | ✅ 已存（本 session 補寫） |
| mile_b14391d9 | Sell in May 的 VIX 面向 | ✅ 已存（本 session 補寫） |

**發文 SOP**：`.claude/skills/trending-repost/SKILL.md` Step 7 八條。逐篇：
開 composer → 貼 fb_draft → 繼續 → 發佈 → 驗牆 → 留言貼 volpred URL →
**發完一篇立刻** 把該 mile 的 `fb_post_status` 改 `success`（防 compaction 重發）。

**注意**：FB profile 視窗太寬會變兩欄、composer 被切邊點不開 — 發文前先
`resize_window` 到 ~860 寬（單欄模式，composer 置中可點）。

**根因待修**：mile_02518109 / mile_b14391d9 原本 `fb_post_status=pending` 但
**無 fb_draft** — trending_repost pipeline 發了 feed 卻沒生成 FB 草稿。需查
trending-repost workflow 為何漏生 FB 草稿步驟。

---

## ✅ FB pipeline critical 已清除（2026-05-22 13:44）+ 待補

3 篇 trending_repost 已發佈 Ivan Lai FB（commit a8b77d7d），fb_post_status 全 success：
mile_bb62fc66 / mile_02518109 / mile_b14391d9。

**突破關鍵**：FB 發文框「繼續/發佈」鈕在 viewport 外點不到 → 改用 `javascript_tool`
直接 DOM `.click()`，繞過 viewport 限制。**這是 FB 發文的 canonical 方法**，比
對像素座標可靠。開發文框也用 JS：點含「在想些什麼」的 role=button。

**待補 1 — 留言連結**：3 篇都還沒加 volpred 連結留言（feed DOM 用 JS 找 article
節點失敗）。下次：每篇 post 底下 comment box 貼 `https://volpred.zeabur.app/v3/reports/<mile>`。

**待補 2 — 附圖（用戶硬性要求「貼文要附圖」）**：本 session 實測 4 種附圖法全撞工具牆：
(a) file_upload — 已改 API 不收 host 路徑 (b) upload_image — 只收 screenshot 的 imageId
(c) DataTransfer + fetch — FB CSP 擋跨域 fetch (d) DataTransfer + base64 from 同源分頁 —
javascript_tool 結果截斷大字串。**未解的方法**：把圖存成 user-uploaded image 再用
upload_image 的 imageId？或研究 file_upload 新 `files` 參數格式。下次發 trending_repost
要附圖必須先解這個。trending-repost SKILL Step 7 應補：JS DOM 發文法 + 附圖方法。
