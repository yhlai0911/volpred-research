---
name: 每小時派一個任務並徹底完成才停止
description: 派工頻率回到 hourly（24 slot/day）；每次 fire 必須徹底完成 task goal 才能停止，禁止把未完成丟給下一輪；任務必 scope 到 50min cap 內收尾，heavy compute 走 compute_queue 異步
type: feedback
originSessionId: 91283b9e-7227-43f5-88bb-9d92168d243a
---
**Rule**: LaunchAgent + `/loop` 派工節奏 = **每小時觸發一次**（HH:07 CST，**24 slot/day**），每次 fire **必須徹底完成 task goal 才能停止**。**禁止做一半丟下一輪**。

**Why**:
- 用戶 2026-05-16 明確指示：「繼續研究的頻率改 1 小時」（回到 2026-05-12 原 hourly 規則，但保留 2026-05-14 加入的「完整完成」hard rule）
- 4-hourly 期間（2026-05-14 → 2026-05-16）觀察：研究產出節奏太慢、新議題 surface 太久才被選；hourly 更密能 reflect 即時 trending / breaking insight
- 「完整完成」與 hourly 不衝突 — 解法是 scope 切小：1 fire = 1 unit of bounded work（不再嘗試在 1 fire 內走完 experiment→review→article 三段，改成 1 fire 1 段）
- Heavy compute 強制走 `scripts/compute_queue.py` 給 async worker（cron */15min），hourly fire 只做 decision / writing / review

**How to apply**:
1. **LaunchAgent schedule**：`~/Library/LaunchAgents/com.volpred.hourly-dispatch.plist` `StartCalendarInterval` = `Minute=7` 單一 dict（24 slot/day）
2. **Cap**：`HOURLY_CAP_SEC=3000`（50min，60min 間隔 - 10min buffer），perl alarm 防 hang
3. **完整完成 gate**（fire 結束前驗證所有條件）：
   - (a) Agent 跑完 + 結果 verify
   - (b) `knowledge.json` 或 `work_log` 已寫
   - (c) Commit 已 push 主線 OR worktree merged
   - (d) `next_tasks` status 標 succeeded/failed（不留 in_progress）
   - 任一未完成 = 本 fire 尚未真正結束，繼續做完
4. **任務 scope 原則**：1 fire = 1 bounded unit ≤ 50min。**禁止**在單一 fire 內安排 experiment→review→article 三段（會超 cap）；應 split 成 3 個 fire（每 fire 1 段）
5. **分流**：heavy compute（GARCH MLE / Bootstrap / 全期 backtest / pooled-MLE multistart）強制 `scripts/compute_queue.py enqueue` → worker cron */15min 接手 → 下個 hourly fire 派 interpretation agent（省 60-70% tokens）
6. **/loop in-session** 行為仍是 skip-non-cadence（用戶 task-notification 來回時不主動加派），等下一個整點 slot
7. **Emergency override**：reproduce gate red / paper blocker / Codex 恢復可一次清完 backlog — 中途加派需 `docs/error_log.md` 紀錄理由

**取代規則**：原 `每 4 小時派一個任務並徹底完成才停止` (2026-05-14) 已 superseded by this entry（同檔案改寫，git 留前版 history）。

**舊規則保留部分**：
- 11 type 多樣化（last-3 不在的 type 優先；trending_repost daily cap = 2）
- `continue_task_dispatch` cron */30min refill 不變
- 雲端 routine 仍 disabled
- 完整完成 gate（4-hourly 時加入的 hard rule，hourly 期間繼續 enforce — 透過 scope 切小達成）
- anti-ai-style skill 寫作任務必引用
