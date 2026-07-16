# 2026-07-16 16:15 — PHASE-Z gate 修好後 ownership 證明消失

## 現象

PHASE-Z 連續通報 20 個 foreign paths；其中 TAIFEX canonical tick 任務其實早已完成（manifest 10,644 files / 35.9GB、sample 9/9 PASS），但 13 個 code/data artifacts 連續 37 班未提交；`storage/paper_pipeline_status.json` 最久 54 班。另有兩個新版 isolated lazypack run 的 `*_article.md` 每班被重報，以及 repo 根目錄每整點重建 0-byte `market_closure_detect`。

## 根因鏈

1. 原 fire 的 candidate 被 silent-fallback pre-commit gate 擋下。PHASE-Z 當下其實知道 exact owned paths，但 ownership 只存在 6 小時 fire baseline 與 scheduler 的 3 次 drain token。
2. 第三次失敗後 scheduler 為避免 livelock 正確停止重試，卻同時丟掉唯一 ownership 證明。下一班修好 gate 時，這批檔案已在 fire baseline 前就是 dirty，只能被分類為 foreign；安全規則禁止盲收養，因此永遠不會自癒。
3. lazypack scratch 的 ignore rule 只涵蓋舊版 `jobs/<id>/panels/`，漏掉新版 `jobs/<id>/runs/<run>/panels/`。
4. `market_closure_detect` 不是產物：host crontab 的 stdout 直接重導向這個 repo-root 檔名，且同一 `0 * * * *` job 已由 LaunchAgent 執行，造成每小時雙觸發與 NCDR HTTP 429。

## 修正

- PHASE-Z 第一次 candidate 失敗即在 per-worktree git-dir 寫 durable failed-closeout receipt，保存原 fire exact paths、SHA-256 / symlink target / deletion state 與 commit reason；後續 pre-fire 在沒有 active writer 時先重試 receipt。所有 bytes 完全一致才提交，任一路徑被後來 session 修改就 fail-closed 並保留現場。
- isolated recovery 不增加 foreign streak，避免同一時鐘班被算兩次；原 3 次 bounded retry 與禁止 `git add -A` 的安全邊界不變。
- lazypack ignore 改為 `storage/lazypack_jobs/**/panels/*_article.md` 並加 direct / isolated-run regression。
- `config/runtime_schedules.json` 將 `market_closure_detect` 明確設為 `host_crontab_managed=false`、LaunchAgent 單一 owner；targeted crontab reconcile 移除舊行與空殼。

## 驗證

- PHASE-Z receipt / drain / ownership 相關 26 tests PASS；break-then-verify：gate 修好後會提交原 bytes，後續改 1 byte 則 HEAD 不動且 critical。
- TAIFEX 跨 era sample 9/9、parquet 8 files / 511,023 rows schema PASS、silent-fallback findings=0。
- lazypack renderer 三張 1600×1000 PNG 可 bit-for-bit 重現。
- crontab 已無 market-closure 行，LaunchAgent runs=149 / last exit=0。

## 教訓

停止無界重試是對的，但不能把「停止重試」等同「銷毀 ownership」。安全自癒需要保存的是可驗證能力（exact paths + immutable content identity），不是下一班對 dirty tree 的猜測。
