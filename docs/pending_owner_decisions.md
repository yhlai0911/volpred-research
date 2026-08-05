# 待討論事項（等老闆裁決／等額度恢復）

> 這份是**需要老闆判斷**或**被額度卡住**的事，不是一般待辦。一般待辦在
> `storage/next_tasks.json` 與各部門收件匣；工程進度在 `storage/ops/handoff_org_refactor.md`。
>
> **提醒機制**：`config/runtime_schedules.json` 的 event_job
> `owner-decisions-quota-restored`，`not_before = 2026-08-09T16:30+08:00`（週限額重置後
> 半小時）。到期自動 materialize 成 P1 任務，不靠任何人記得。

---

## A. Codex 接手部門（老闆 2026-08-05 提問）

**問題**：Claude 沒額度但 Codex 有額度時，能不能讓所有部門改由 Codex 執行？

**現況**：架構上這條路已存在（`telegram_responder.sh` 有 Claude→Codex failover、
`codex_exec_bounded.sh` 在），但**部門層沒有接線**。而且 2026-08-05 當天
**Codex 額度也已耗盡**（到 8/8 12:01 才恢復），比 Claude 的週日重置還晚 —— 所以那天
沒有第二條腿可站，這也是為什麼要先問「兩邊額度能不能被程式讀到」。

**缺的三件**：
1. 部門 pane 寫死 `--kind claude`（`scripts/org/org_attach.py::DEFAULT_KIND`）——
   要能按 provider 額度選 kind
2. **額度訊號沒有可查詢介面**：Claude 這邊 `/usage` 是 UI，Codex 那邊只有 API 錯誤訊息。
   現在只能「撞到才知道」。沒有這個訊號，自動切換只是猜
3. Codex 沒有部門身分注入機制（`--append-system-prompt-file` 是 Claude 的旗標）

**建議**：等兩邊額度都恢復（8/9 之後）再做，屆時才有實驗餘裕。第 2 點是前提，
先做它；沒有可讀訊號的自動切換會在最需要的時候切錯方向。

**要老闆決定的**：值不值得投入。若 Codex 訂閱本來就有額度，這條等於把平台的
單點依賴變成雙供應商，對「零付費續跑」這條 mission 有直接貢獻。

---

## B. CLAUDE.md／AGENTS.md 精煉與解構（老闆 2026-08-05 指令）

**已做**：修掉事實錯誤（它原本說平台在並行遷移期、舊 dispatch 照跑，那在 `b7d975351`
之後就不成立）；補進經理＋部門模式與今天新增的機制。

**未做**：瘦身本身。

**量測（2026-08-05 21:25）**：
- CLAUDE.md 39 KB ≈ 13k tok（每個主線程 session 付一次）
- policy.md 14 KB ≈ 4.8k tok（每個角色付一次）
- **但真正的大頭曾是 brief**：platform_eng 115 KB ≈ 38k tok ——
  已由平台工程部瘦身到 17.8 KB（`bc9cc3b22`），**6.5 倍**

**指標稽核結果（重要）**：CLAUDE.md 的 68 個路徑型引用中**只有 1 個是死指標**
（`experiments/kXXX/`，是佔位符，誤報）。**所以它沒有腐爛**，瘦身的收益是純 token，
不是修正確性 —— 這降低了它的優先序，也降低了風險。

**要老闆決定的**：既然指標沒爛、brief 已經瘦了 6.5 倍，CLAUDE.md 的 13k 還值不值得
花額度去重構？我的建議是**先不動**，等有更明確的痛點（例如主線程 context 真的不夠用）
再說。過時資訊的 archive 可以獨立做，成本低很多。

---

## C. 部門派 subagent（老闆先前提問，尚未定案）

- **唯讀 subagent（大搜尋／大 log／隔離分析）**：現在就可以給，無寫入衝突、無 claim 問題
- **會寫檔的 subagent／多 worktree**：**先不要**。`scripts/hooks/write_claim_guard.py:198-199`
  的寫者身分是 `dept:<部門>`，同一部門的 N 個 subagent 對彼此隱形 ——
  等於在部門內部重建那個「各自 lock、各自 commit、往兩個方向走」的 race。
  要開，得先讓 claim 身分下沉到 `dept:<名>#<agent-id>`

**要老闆決定的**：唯讀那半要不要現在開。

---

## D. 已知缺陷（工程面，不需老闆裁決，但被額度卡住）

| 缺陷 | 影響 | 狀態 |
|---|---|---|
| `write_claim_guard` claim-on-deny 不釋放 | 路徑被空鎖 45 分鐘；2026-08-05 至少 3 次，經理自己中 2 次 | 未修（platform_eng D31-a） |
| dispatch-supervisor 自帶 croniter | 兩個派工者搶同一個池；互斥靠 claim，不會雙做，但選工策略有兩套 | 未修（GitHub #46 / #9） |
| `ops_snapshot.alerts.sent_last_24h` 恆為 0 | 讀 `sent_at`、寫的是 `last_sent_at`；2026-08-05 停擺 2h45m 才被發現的能見度根因 | 未修（platform_eng D28-b） |
| 部門 headless 執行未接線 | 關掉 Herdr 後只有經理能無人值守運作 | 未做 |
| 今日 token 採集為 0 | 組織上線第一天完全沒有量測 | 已派 resource_monitor P1 |

---

## E. GitHub issue backlog 三桶裁決（26 張）

讀完的結論：**沒有一張是舊架構遺物**。它們是平台的工程綱領（issue #3 的 44 條
user story），組織改組只實作了其中第 2／12／13／15 條。而且每張 ticket 自己就寫著
「GitHub Issue 僅負責規劃與驗收，不得建立第二套 pending queue」——今天做的
`dept:*` label → canonical 池那道門，正是這份綱領指定的橋。

12 張零留言的不是被遺忘，是**依賴排序在等前置**（各自標了 `Blocked by`）。

**建議**：不要一次全部倒進池（platform_eng 已 95 件）。依 `Blocked by` 圖找可動的葉節點，
一次放行一兩張。**不要為了清乾淨而關 issue** —— 沒證據就關，等於把未完成的工作變成
看不見的工作。
