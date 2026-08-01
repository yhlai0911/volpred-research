# 重構設計：自動修復迴圈的 incident 生命週期

**任務**：`assign_10927b4e`（老闆 2026-07-21 裁決，telegram-1231/1232）
**狀態**：設計文件 — 待老闆過目後才分 Phase 實作。本文件不改任何程式碼。
**撰寫**：2026-07-21 12:2x，hourly-slot-1-670daa95（fire_reason=`requested:user:assign_10927b4e`）

---

## 0. 這份文件為什麼不是又一張補丁

老闆的原話是「已經很多次你還是修不好，叫你重新設計重新架構你又不要」。所以第一件事不是提方案，
是說清楚**前幾次的修法為什麼註定失敗** —— 如果診斷錯了，重架也只是換個地方犯同一個錯。

前幾次的修法全都是同一型：**在既有的去重檢查上再加一個條件**（加時間窗、加 fingerprint、加
`if_exists="skip"`、加 `--force` 繞過、加 three-strike）。它們全部有效、全部沒解決問題，因為
它們共用一個沒被質疑的前提：

> 「去重」= 開單前去問任務池：這件事現在有沒有活著的任務？

這個前提本身就是 bug。任務池是**處置**的紀錄，不是**事件**的紀錄。處置會結束，事件不會因此消失。
把去重錨在會被清掉的東西上，等於去重機制自帶重置鍵。加再多條件都改不了這一點 —— 這就是為什麼
「已經很多次還是修不好」。

---

## 1. 實測證據（2026-07-21 查 `storage/next_tasks.json`，3195 筆）

自動補救類任務建立量，單調爆量：

| 日期 | 張數 |
|---|---|
| 2026-07-17 | 8 |
| 2026-07-18 | 10 |
| 2026-07-19 | 32 |
| 2026-07-20 | 38 |

現存 **active**（pending/claimed/in_progress/blocked）205 張中，**35 張（17%）屬於可辨識的重複群**：

| 張數 | 群 | 重複型態 |
|---|---|---|
| 19 | `worktree_salvage_*` | per-instance |
| 16 | `wsb_remed_*` | per-instance |

全時期 `alert_internal_*` 的 episode 數（同一 alert_key 開過幾張全新單）：

| 張數 | alert_key |
|---|---|
| 19 | `silent_fallback_new` |
| 5 | `phase_z_test_gate_red` |
| 4 | `git_push_backup_hold` |
| 1 | `phase_z_baseline_missing` |

`silent_fallback_new` 那 19 張的共同特徵，是整個問題的縮影：**每張都是 `a1`、
`consecutive_remediation_failures=0`、且幾乎立刻被標 `resolved_at`**。系統從頭到尾不知道
自己在處理同一件事 —— 它每次都以為這是第一次。

---

## 2. 根因：三個結構性錯誤

### 2.1 去重錨在「活著的 row」，而 resolve 會把錨拔掉

`_route_internal_task`（`src/volpred/ops/alert_remediation.py:400-448`）掃同 `alert_key` 且
status ∈ `{pending, pending_main_thread, claimed, in_progress}` 的未 resolved row，有就回
`remediation_active` 不開新單。這段邏輯本身是對的。

問題在偵測端一觀察到乾淨就呼叫 `resolve_internal_remediable_alert`
（`scripts/dispatch_supervisor/phase_z.py:3149-3155`）把整個 episode 標 resolved。於是同一 alert_key
下次再 breach 時 `unresolved` 是空的 → 落到「全新 episode」分支（`alert_remediation.py:586-612`）
→ 開一張全新 id、`attempt_number=1`、`consecutive=0` 的單。

**resolve → refire = 一張新單，且計數器歸零。** 唯一擋 refire 的條件是
`now <= max(resolved_at)`（`alert_remediation.py:390-402`）—— 那只擋時鐘倒退，不擋三小時後的再次
breach。這就是 19 張全是 `a1` 的機械原因。

### 2.2 incident 沒有一級身分：四套機制互不相認

| 身分 | 用在哪 | 存在哪 |
|---|---|---|
| `sha256(level\|title)` | transport 24h 去重 | `storage/ops/alert_dedup.json`（879 key） |
| `alert_key + episode_id` | internal 補救 | **寄生在 `next_tasks.json` 的 task row** |
| `ci_incident_id` | CI 紅燈 | `storage/ops/ci_watch_state.json`（唯一的真 incident 物件） |
| `wsb_remed_<name>` | worker orphaned | 固定 id + `if_exists=skip` |

四套之中只有 CI 那套有持久的 incident 實體 —— 也只有 CI 不會出現 episode 重置。這不是巧合，
是本設計的存在證明：**做對的那條路已經在 repo 裡了，只是沒有推廣。**

`alert_dedup.json` 是 transport ledger 不是 incident store（模組 docstring 自己寫明，
`alerts.py:1-18`）。通知抑制與開單抑制被刻意解耦，所以**信箱安靜與任務池膨脹可以同時發生** ——
實測正是如此。

### 2.3 per-instance 開單：同一根因被拆成 N 個 incident

`worktree_salvage_*` 19 張、`wsb_remed_*` 16 張。每張的 id 都不同、`if_exists=skip` 都正確生效、
沒有任何一張是「重複開單」—— 但它們是**同一個根因的 35 個實例**：worktree/workspace 沒有人收。

老闆說的「對同一批問題反覆開任務」指的就是這個。逐張看沒有 bug，整體看是系統在用開單代替修理。
現行模型沒有任何地方能表達「這 19 張是一件事」。

### 2.4 沒有任何量的上限

`alert_remediation.py` / `check_alerts.py` / `next_tasks.py` 全域 grep `cap` / `per_day` /
`max_per_day` 均無命中。唯一的量限制是 ordinary 路 task id 內含日期（`alert_<id>_<YYYYMMDD>`,
`alert_remediation.py:121`）→ 每 alert 每天最多 1 張。**Internal 路與 per-instance 路完全無上限。**

---

## 3. 新模型：Incident 是一等公民

### 3.1 核心倒轉

```
現行：  偵測 → 查任務池有沒有活 row → 沒有就開一張任務
新制：  偵測 → 對映到 incident（持久身分）→ incident 狀態機決定要不要開任務
```

任務從此是 incident 的**子項**，不是 incident 本身。任務可以結束、可以失敗、可以被清掉；
incident 不會，它只會換狀態。

### 3.2 Incident 實體

新增獨立 store `storage/ops/incidents.json`（**不寄生在 next_tasks.json** —— 2.1 的根因就是寄生）：

```
{
  "incident_id":        "inc_<fingerprint[:12]>",
  "fingerprint":        "<穩定身分，見 3.3>",
  "kind":               "phase_z_test_gate_red | worker_orphaned | worktree_unmerged | ci_red | ...",
  "class":              "machine_self | ordinary",          // 見 §6
  "first_seen_at":      "...",
  "last_seen_at":       "...",
  "occurrence_count":   19,            // 累計偵測次數，永不歸零
  "episode_count":      7,             // 開過幾次處置，永不歸零
  "state":              "open | mitigating | suppressed | escalated | resolved",
  "current_task_id":    "assign_xxx | null",
  "task_history":       ["...", "..."],
  "instances":          [{"key": "worktree-abc", "first_seen_at": "...", "cleared_at": null}],
  "resolution":         {"at": "...", "criterion": "clean_streak_72h", "by": "..."},
  "suppressed_until":   null,
  "escalation":         {"root_cause_task_id": "...", "at": "..."}
}
```

**三個不可協商的性質**：

1. **`occurrence_count` / `episode_count` 永不歸零。** resolve 只改 `state` 與寫 `resolution`，
   不重置計數。這一條單獨就殺死 §2.1 的 19 張 `a1`。
2. **incident row 永不刪除**（只 archive）。刪掉身分 = 恢復重置行為。
3. **同根因的多個實例進 `instances[]`，不各自成 incident。** 這一條殺死 §2.3 的 35 張。

### 3.3 Fingerprint：身分怎麼算

Fingerprint 必須**只由事件的不變性質組成**，不含時間戳、不含 run_id、不含 worktree 名。

| kind | fingerprint 組成 | 實例 key（進 `instances[]`） |
|---|---|---|
| `phase_z_test_gate_red` | `kind` + 失敗 node id 集合（排序後 hash） | 該次 commit sha |
| `silent_fallback_new` | `kind` + 觸發的 hook 規則 id | file:line |
| `worker_orphaned` | `kind`（單一根因） | workspace 名 |
| `worktree_unmerged` | `kind`（單一根因） | worktree 名 |
| `ci_red` | `kind` + root_cause 分類 | run_id |

注意 `worker_orphaned` / `worktree_unmerged` 的 fingerprint **刻意不含實例名** —— 這正是把 35 張
收成 2 個 incident 的機制。現行 `distinct_incident_new_episode`（`alert_remediation.py:477-533`）
把 fingerprint 不同一律當新 incident，方向相反，需改為「fingerprint 決定 incident，實例只進陣列」。

### 3.4 狀態機

```
                  偵測到
     (無此 incident) ──────► open
                              │ 依 §4 決定開處置任務
                              ▼
                          mitigating ──── 任務 succeeded 且通過收斂判準 ──► resolved
                              │                                              │
                              │ 任務 failed / 完成但仍 breach                  │ 再次偵測到
                              ▼                                              │（不是新單，
                          （episode_count++，回 open）◄────────────────────────┘  是同一 incident 復發）
                              │
                              │ episode_count >= N（§5）
                              ▼
                          escalated ──► 開「根因重構」任務一張，之後永久 suppressed
                                        （不再自動開修復單）
```

`suppressed` 是獨立狀態：incident 仍被記錄、仍被計數、仍在報表可見，但**不開任何任務**。
這是「知道但不吵」，取代現行「不知道所以一直開」。

---

## 4. 收斂判準：什麼叫「處理完了」

現行沒有 resolution 條件 —— 偵測端看到乾淨就寫 `resolved_at`，一次乾淨就算數。這是為什麼
resolve/refire 來回震盪。

**新判準：resolve 需要「持續乾淨」，不是「一次乾淨」。**

| kind | resolution criterion |
|---|---|
| 週期性偵測類（PHASE-Z、hook、CI） | 連續 **K 次**偵測皆乾淨（K≥3）**且**跨越 ≥24h |
| 實例型（worker_orphaned、worktree） | `instances[]` 全部 `cleared_at` 非空，且 ≥24h 無新實例 |
| 一次性事件（單次 job 失敗） | 對應任務 succeeded 即可 resolve |

未達判準時 incident 停在 `mitigating`，**不開新單**（因為 `current_task_id` 還在或剛結束）。
達判準才寫 `resolution{at, criterion, by}` 進 `resolved`。

從 `resolved` 復發時：**不是新 incident**，是同一列 row `state` 回 `open`、`episode_count++`。
計數帶著歷史走，所以第 8 次復發時系統知道這是第 8 次 —— 現行系統永遠以為是第 1 次。

---

## 5. 升級路徑：不收斂就停止自動修復

**規則**：`episode_count >= 3` 且未達 resolution → incident 轉 `escalated`。

轉 `escalated` 時**恰好做三件事**：

1. 開**一張** `task_type=platform_ops`、`priority=P1`、`source=user`、標題前綴 `[根因重構]` 的任務，
   描述自動帶入：fingerprint、`first_seen_at`、`occurrence_count`、前 N 次處置任務 id 與各自
   失敗原因、`instances[]` 摘要。
2. 寄一封（**一封**）升級通知給老闆。
3. incident 轉 `suppressed`，`suppressed_until = null`（永久，直到根因任務 succeeded 才解除）。

**之後這個 incident 永遠不再自動開修復單。** 這是本設計最重要的一條：現行系統的失敗模式是
「修不好 → 繼續重試 → 無限開單」，新制是「修不好 → 承認修不好 → 交給人 → 閉嘴」。

三次不收斂就升級，對應 CLAUDE.md 既有的 3-strike rule，不引入新概念。

---

## 6. 症狀 vs 根因分流：機器自己壞掉不進一般迴圈

`class` 欄位把 incident 分兩類，走不同路徑：

| class | 定義 | 處置 |
|---|---|---|
| `machine_self` | **執行機器本身**故障：PHASE-Z 收班、dispatch supervisor、queue writer、commit gate、worktree 生命週期 | **不進自動修復迴圈**。直接記錄 incident + 通知，`episode_count>=2` 即升級為 `[根因重構]` 主線程任務 |
| `ordinary` | 研究/內容/資料層的可自動處理故障 | 走 §3.4 完整狀態機，3-strike 升級 |

**理由**：`machine_self` 類的自動修復有結構性矛盾 —— 修復動作本身要靠那台壞掉的機器執行。
PHASE-Z 收班失敗時開一張任務，那張任務要靠下一班 fire 的 PHASE-Z 來 commit，於是失敗會傳染給
處置本身。實測 `silent_fallback_new` 與 `phase_z_test_gate_red` 兩類共 24 張全在此類，
無一收斂 —— 這是機制性的，不是運氣不好。

`machine_self` 的 threshold 用 2 而非 3，因為這類問題會阻塞所有其他工作，容忍度應更低。

### 6.1 2026-08-01 owner amendment：從通知死路改為一次有界修復

上表原始的「完全不進自動修復迴圈」在 production 驗證中暴露另一個不可接受的死路：detector
只記錄並通知，Operations Core 沒有任何可 claim 的 actuator，因此信件雖列出錯誤，平台卻不會
主動修復。自本修正起，五個 shipped machine-self kinds（`phase_z_test_gate_red`、
`silent_fallback_new`、`git_push_backup_hold`、`phase_z_baseline_missing`、
`phase_z_generation_rejected`）的 canonical 契約改為：

1. episode 1 建立**恰一張** P2、isolated、具 `write_intent=repo_patch` 與有限
   `declared_output_paths` 的修復任務；重複 poll 只重用同一 task id，不通知 owner。
2. 任務自綁定起 **2 小時**內必須 terminal；仍未派工者先由 queue CAS 標記 failed，CAS
   acknowledgement 成功後 incident 才能前進。已 claimed／in-progress 者保留唯一 producer
   custody，由 supervisor 既有 work-cap／termination owner 回收；未收到 terminal receipt 前
   不得另開修復者。
3. 任務 terminal（含上述 deadline handoff 完成）而 detector 仍 breached，立即進 episode 2，建立恰一張
   `main_thread` `[根因重構]` 任務並通知一次；不得再開第二張機器自修任務。
4. 舊 durable incident row 在下一次 breach 依 canonical `KIND_POLICY` 前向遷移，並保存
   `policy_history`，不可因為事故早於 cutover 就永久停在 notification-only。

此 amendment 取代本節上表對上述五個 shipped kinds 的 notification-only 處置；
`worker_orphaned`／`worktree_unmerged` 的 main-thread adjudication 與已有明確外部 actuator 的
kind 不受影響。它同時保留原設計要避免的無限自修迴圈，並補上 autonomous-manager 必須具備的
首次 actuator。

---

## 7. 反迴歸的機械 gate

設計要能被測試證明，否則就是散文。以下每條都是可執行的測試斷言：

| # | 測試 | 斷言 |
|---|---|---|
| G1 | 同 fingerprint 連續觸發 10 次 | `next_tasks.json` 只多 **1** 張任務；`occurrence_count == 10` |
| G2 | resolve 後再 breach | **不開新單**；同一 incident row `state=open`、`episode_count==2`；計數**未歸零** |
| G3 | 同根因 5 個不同實例 | 只 **1** 個 incident、`len(instances)==5`、只 **1** 張任務 |
| G4 | 連續 3 次 episode 未收斂 | `state=escalated`，恰 **1** 張 `[根因重構]` 任務，恰 **1** 封信，之後再觸發 10 次 → **0** 張新任務 |
| G5 | shipped `class=machine_self` 首次 breach，之後持續 breach | episode 1 恰 **1** 張具 WS-B execution contract 的 P2 修復單；2h deadline 先完成 queue／producer-custody settlement，terminal 後仍 breached → episode 2 直接 `escalated`，不開第二張自修單 |
| G6 | **24h 全域上限** | 任一滾動 24h 內自動補救任務總量 > `MAX_AUTO_REMEDIATION_PER_DAY`（初值 **8**）時，超出的一律不開單、記 `throttled` 到 incident、每日彙整成 **1** 封摘要信 |
| G7 | 一次乾淨不足以 resolve | 單次乾淨後 `state` 仍為 `mitigating`；滿足 K 次+24h 才 `resolved` |

G6 是最後防線：即使前面全部推理錯了，量也不會失控。這正是現行系統完全缺席的東西（§2.4）。

---

## 8. 清理：現存重複 pending 怎麼收

實作 Phase 完成後執行，**回報實際清掉幾張**（不預先宣稱數字）：

| 群 | 現存 active | 處置 |
|---|---|---|
| `worktree_salvage_*` | 19 | 合併為 **1** 個 `worktree_unmerged` incident，19 個 worktree 進 `instances[]`；19 張任務關為 `superseded`，新開 1 張批次裁決任務 |
| `wsb_remed_*` | 16 | 合併為 **1** 個 `worker_orphaned` incident，同上 |
| `alert_internal_silent_fallback_new_*` | 見查詢 | 全部 episode 合併為 1 個 incident，`episode_count=19`；因 `class=machine_self` 且已 >2 → 直接 `escalated`，開 1 張根因重構任務 |
| `alert_internal_phase_z_test_gate_red_*` | 見查詢 | 同上，`episode_count=5` → `escalated` |

預期：**35+ 張 active 收斂到個位數**，且之後不再增生。

治本任務 `assign_eb78aedc` / `assign_e7643d81` / `assign_commit_atomicity_gate` 已在池中 ——
它們應被掛為對應 incident 的 `escalation.root_cause_task_id`，而不是與新開的單並存。

---

## 9. 分 Phase 實作順序（待老闆核可後才動工）

| Phase | 內容 | 可獨立驗證 |
|---|---|---|
| **P1** | `storage/ops/incidents.json` + `src/volpred/ops/incident.py`：實體、fingerprint 計算、狀態機、CRUD。純新增，不接線 | G1/G2/G3 單元測試 |
| **P2** | G6 全域 24h 上限。**先上，與 P1 獨立** —— 這是止血，不需等整套完成 | G6 |
| **P3** | 四條現行路徑接線到 incident store：`alert_remediation` internal 路、CI（已有 incident，改為共用 store）、`workspace.py` WS-B、worktree salvage | G1-G3 整合測試 |
| **P4** | §5 升級路徑 + §6 `machine_self` 分流 | G4/G5 |
| **P5** | §8 清理 + 回報實際張數 | 清理後 active 重複群計數 |

**P2 先行**是刻意的：老闆現在最痛的是量，而量的上限不依賴任何 incident 語意。先把出血止住，
再做正確的事。

---

## 10. 明確不做什麼

- ❌ 不在既有去重條件上再加旗標 —— 那是第四次犯同一個錯（§0）
- ❌ 不動 `alert_dedup.json` 的 transport 語意 —— 它做對了自己的事（防信箱轟炸），問題不在它
- ❌ 不把 incident 狀態繼續寄生在 `next_tasks.json` —— 那是 §2.1 的根因
- ❌ 不引入新的第五套身分機制 —— 這次重構的成功判準之一是**四套收斂成一套**

---

## 附註：本文件產出時的執行軌矛盾（需老闆裁決）

`assign_10927b4e` 標 `status=pending_main_thread`（main_thread lane，不得走 hourly 派工），
但 supervisor 為它發了一個 hourly fire（`fire_reason=requested:user:assign_10927b4e`）。
`task_pool_claim.py claim` 因此回 `main_thread_lane` 拒絕，本班未 claim 該任務。

本文件是在**不 claim、不改碼**的前提下產出的（設計階段不觸及運營機器，不違反 lane 規則的意圖）。
但這個矛盾本身需要修：`request_fire` 對 `pending_main_thread` 任務起 hourly fire，會讓這類任務
**永遠沒有合法執行者** —— 沒有 interactive session 就卡死，卡死後又會被巡檢當成異常再開單。
這正是本文件描述的病灶在 dispatch 層的同構複製，建議納入 P4 一併處理。
