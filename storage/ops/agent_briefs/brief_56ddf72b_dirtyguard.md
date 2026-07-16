# 根因修復：daily_update dirty-guard 硬中止導致 host_cron_fail 反覆 critical

**Task ID**: assign_56ddf72b (P1, source=user)
**Model**: claude-opus-4-8 / max (per model_router + 老闆 Telegram msg 794 明示「最高模型與最大深度」)
**Worktree**: `.claude/worktrees/dispatch-slot-1-a9b8c1b6-dirtyguard` (branch `wt/dispatch-slot-1-a9b8c1b6-dirtyguard`)

## 背景：這不是補當日 alert，是深度根因修復

老闆經 Telegram msg 794 針對「為什麼一直出現各種錯誤」直接指示：**解決不了就用最高模型與最大深度去解**。
本任務即該深度修復。**禁止只 silence alert 或只補當天症狀**。

## 已驗證的具體證據（telegram_responder 只讀診斷，未改任何檔）

1. 2026-07-15 14:00 CST，cron `daily_update_intraday` exit=1，log 明說：
   `refusing to overwrite output(s) already dirty before this run: [storage/reports/feed.json]`
   → `tracked output already dirty; aborting before daily writes`
2. 這是**硬失敗 exit=1**（非 142 SIGALRM / 非 75 quota 這類自我恢復碼），所以直接升 `host_cron_fail=critical`。
3. `host_cron_fail` signature 已跨 13 天（first_seen 2026-07-02 → last_seen 2026-07-15），屬**慢性反覆**，不是一次性。
4. 當下 working tree：`storage/reports/feed.json` 為 unstaged-modified（dirty），全樹 21 changed / 18 staged。
5. `git_push_backup` 有正常 commit/push（14:00:15 pushed 2 commits OK），但 feed.json 這類 publish 輸出仍被留在未提交狀態；
   且 `daily_update` 與 `git_push_backup` **都在 :00 同分鐘觸發**，存在對 git working tree / canonical Git-writer lease 的競態。

## 根因假說（需你深度查證後定案 — 不要照單全收）

daily_update 的 dirty-guard 只要 fire 當下 tracked output（feed.json）dirty 就硬 abort exit=1。
而 feed.json 常被 publish/release 寫入後未即時 commit，或與同分鐘的 git_push_backup commit 撞在一起 → 每天可穩定重踩。
它其實是**良性/暫態**（下一輪多半自我恢復），卻用硬 exit=1 觸發 critical，就是老闆看到的「一直出錯」噪音。

**請自行驗證此假說再定案**：實際讀 daily_update 的 guard 程式碼、cron 時序、feed.json 的寫入者，
確認 dirty 的真正來源。若證據推翻假說，以證據為準並在交付說明中講清楚。

## 要交付的三層修復（全部處理，各附驗證）

### A. 正確性
讓 daily_update 的 dirty-guard **不要對「暫態 dirty」硬 abort** — 改成等 lease / 短 retry，
或把 guard 收斂到真正的內容衝突，讓良性未提交的 feed.json 不會殺掉整輪。
⚠️ 但**不可把 guard 拿掉**：它原本要防的是「覆蓋掉別人未提交的真實工作」，這個保護必須留著。
要分辨的是「暫態 dirty（自己的 publish 輸出還沒被 commit）」vs「真衝突（別人正在編輯）」。

### B. 根因
確保 feed.json 等 publish 輸出在發佈後**即時被 commit**，讓 working tree 不再慢性 dirty；
並/或把 :00 同時觸碰 git tree 的 cron **錯開/序列化**，消除競態。

### C. Alert 語意
評估這種「暫態 abort、下輪自我恢復」是否該升 critical。若不該，調整 `host_cron_fail` 判準
（比照 142/75 自我恢復處理），停止 critical 噪音；真正持續斷線交給 outcome-level dead-man switch 抓。
⚠️ 注意分寸：**不要把真實故障也一起 silence 掉**。降噪不等於降盲。

## 約束（HARD）

- 遵守 AGENTS.md「**永遠修流程，不修資料**」：**不要手動 commit feed.json 收尾**，
  要追到產生 dirty 的程式與 cron 時序並修流程。
- **只在本 worktree 內寫檔**（`.claude/worktrees/dispatch-slot-1-a9b8c1b6-dirtyguard`）。禁止寫 canonical checkout。
- 禁止 `--no-verify`、force push、繞過測試閘門。
- 修完寫入 `docs/error_log.md`（記錄根因與修法），並在 storage 對應設定/程式落地。
- 參考既有 `docs/refactor_plan_hourly_dispatch.md`（142 結構根因）與先前 `platform_ops_host_cron_recency_gate` 修法。
- **測試必須真的跑**：改完在 worktree 內跑相關 pytest，把實際輸出貼進 README。
  禁止「應該會過」這種未驗證宣稱。

## 交付物（result artifact）

寫 `docs/fix_56ddf72b_dirty_guard.md`，內容必含：

1. **根因定案**：實際查證結果（假說成立 / 被推翻 → 真因是什麼），附程式碼位置與 log 證據
2. **A/B/C 三層各自的修法**：改了哪些檔、為什麼這樣改、預期消除哪個 failure mode
3. **驗證證據**：實際跑的測試指令 + 真實輸出（貼原文，不要摘要成「通過」）
   - 至少要能證明：暫態 dirty 不再殺整輪、真衝突仍被擋、真故障仍會 alert
4. **殘留風險 / 未解部分**：誠實列出。做不完的部分明說，不要假裝完整。

commit 在本 worktree 內（正常 commit，不要 push）。

## 誠實性要求（最高優先）

研究誠實 > 一切。若三層裡有哪層查不出根因或修不動，**明說**並解釋卡在哪，
不要為了看起來完成而寫沒驗證過的宣稱或假數字。部分完成 + 誠實說明，遠優於假裝全解。
