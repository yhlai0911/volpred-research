# 2026-08-03 — release pool 與 agent dispatch 沒有閉環

狀態：`root_cause_fixed_and_verified`（控制面五步 Gate；文章本身仍須等目前安全 slot 的工作完成後產出）。

## 症狀證據

- `preview_release_pool_by_settings()` live 回讀：draft=0、scheduled=0、eligible=0。
- `storage/next_tasks.json` 同時已有 7 張可執行 daily_article，其中 6 張 P1；所以不是「沒文章任務」。
- supervisor 受 shared-launchd coalition 安全限制只能使用一個 slot；當下 slot 正執行 `ci-red-30736983439`。
- `storage/ops/schedule_receipts.json` 有 25,171 個 fire、27,639,056 bytes，先前 Operations Core 已出現 `ENOSPC`。

## 根因層級

這是控制面契約斷裂，不是單一排程漏跑：release owner 只負責消耗草稿，dispatch report 雖能偵測乾池、補任務與升 priority，Operations Core 的正式每分鐘 tick 卻只觸發 supervisor，沒有把 `eligible=0` 轉成「下一個安全 slot 必須執行哪一張文章」。priority 只能影響一般排序，無法跨過 recurring mutating/preempt admission。schedule receipt ledger 另採無限增長的單檔 atomic rewrite，讓控制面在磁碟壓力下整體停止。

## 底層修正

1. 新增 `volpred.ops.article_continuity`：flock 內批次升級文章 backlog、只 nominate 最老一張，寫入 continuity-owned preempt metadata，commit queue 後才寫 durable fire request。
2. `cron_agent_dispatch_tick.sh` 每分鐘先跑 model-free continuity actuator，再觸發 supervisor；無 token 成本。
3. supervisor scheduled-preempt admission 使用 `dispatch_preempt_rank`；continuity 只在 scheduled preempt 內取得一次 next-fire 優先權，human urgent 與 time-critical lane 仍在更外層。
4. 已有 daily_article claimed/in_progress 時不 nominate 第二張；release pool 恢復後只清 `dispatch_preempt_source=article_continuity` 的 marker。
5. `FileReceiptStore` 每次落盤前保留所有 live/retryable rows，terminal 6,000、shadow 2,000 有界；retention 數字寫回 canonical schedule spec。

## 回歸與 live 回讀

- 217 個 article-continuity、dispatch starvation、task claim、draft refill、schedule materialization 相關測試通過。
- Operations Core canonical config validate：57 jobs、57 個 owner 都是 operations_core、ok=true。
- live actuator 選中 `K1706_article_general`，queue 回讀 marker rank=-100。
- dispatch state 回讀 `fire_request_reason=article_continuity:K1706_article_general`；同時 current CI job 仍 running，證明忙碌 slot 沒有吞掉 request，也沒有危險地提高 slots。

## 制度化

canonical schedule description、wrapper manifest、控制模組、admission ranking tests、receipt retention regression 與本 error-log class 同步。未來「queue 有文章但 pool=0」不再只寄通知或等下一次人類巡檢，而會在正式 clock 每分鐘自動收斂。
