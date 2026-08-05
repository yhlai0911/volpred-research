# Gate 過度封鎖全量盤點與收斂提案

- **產出部門**：治理部（`governance`）
- **產出時間**：2026-08-05 16:44（台灣時間）
- **對應工作項**：`item_20260805T084204237050Z_gate-gate-1-deny-block-pre-comm`（P1，老闆點名）
- **性質**：**提案，待經理裁決**。本報告未退役、未關閉、未放寬任何一道 gate。

---

## 0. 一句話結論

老闆的體感是對的，但**病因不是「gate 太多」，是「gate 擋同一件事擋很多次」**。
7 日窗內 663 次阻擋，只落在 **30 個不同候選**上——平均一個候選被同一道 gate 擋 22 次。
最極端的 `event_reaction_coverage` 對**單一個** task 擋了 246 次，而它的資料源同時被系統
自己標記為 malformed。這是死鎖，不是防護。真正該收斂的是 4 道，不是 29 道。

同時盤出一個結構性缺陷：**Claude Code hook 層（8 個 deny 規則 + 6 個 PreToolUse hook）
完全沒有 telemetry**，「最近 30 天擋下幾次」在該層根本無法回答。無法計數的 gate 無法被
評估、也就無法被收斂——這是本次盤點唯一建議「新增」的東西。

---

## 1. 全量清單（1）：所有會 deny/block 的機制

分五層。**兩層各自已有 canonical registry owner**，本盤點直接引用，不另建清單。

### L-A｜Control-plane gate（29 道）

- **registry owner**：`config/control_gate_registry.json`
- **lifecycle owner**：`src/volpred/ops/control_gate_lifecycle.py`
- **telemetry**：`storage/logs/control_gate_decisions.jsonl` + `storage/ops/control_gate_lifecycle_latest.json`（7 日 inventory，含 trigger_count / blocking_count / distinct_candidates）
- 組成：15 道 hard gate（`hard_block` / `fail_closed`）、11 道 `selection_constraint`、2 道 `warn`、1 道 `shadow`
- 立項理由：每道 gate 在 registry 內強制帶 `incident_refs`（`control_gate_lifecycle.py:343` 校驗），即無 incident 不得立項。**這層的立項紀律是全平台最好的。**

### L-B｜Claude Code PreToolUse hook（6 個 owner）

owner 清單見 `docs/governance/enforcement_layer_map.md`。**該表目前 OUT OF DATE**——
`scripts/audit_enforcement_map.py` 報 `write_claim_guard.py` 在磁碟上但不在表內（見 §4-D）。

| owner script | 擋什麼 | 立項理由 |
|---|---|---|
| `.claude/hooks/pretooluse-bash-optimizer.sh` | 8 條 Bash deny 規則（見下） | CLAUDE.md 散文規則擋不住，逐條升級為機械攔截 |
| `scripts/hooks/write_claim_guard.py` | 跨 session 同路徑併發寫入 | 兩 session 各自 lock、各自 commit、設計往兩方向走 |
| `scripts/hooks/gate_edit_guard.py` | 編輯 gate 檔前保全原始 bytes | 防 gate 被靜默改弱 |
| `scripts/hooks/read_context_budget.py` | 無界整檔讀取（bound，非 deny） | token 紀律 |
| `scripts/hooks/deny_wakeup_interactive.py` | 互動 turn 的 ScheduleWakeup | 防使用者回合被吞掉 |
| `scripts/hooks/enforce_final_text.py` / `enforce_fire_receipt.py` | Stop 時無最終文字 / 無 receipt | 老闆看不到 tool-call 之間的文字 |

8 條 Bash deny：fire 內 spawn headless agent、`git worktree remove --force`、直呼 zeabur
deploy、整檔讀 feed/knowledge.json、裸跑 codex exec、main checkout 裸 Git mutation、
`git commit -m` 內嵌非 ASCII、互動 turn ScheduleWakeup。

### L-C｜Git hook（5 個，`scripts/git_hooks/` 為 canonical）

`pre-commit`（encoding / silent fallback / candidate test closure）、`pre-push`、
`prepare-commit-msg`、`reference-transaction` + `git-writer-lease-verify.py`。

### L-D｜CI（6 個 workflow）

`experiment-artifacts`、`knowledge-provenance`、`pytest`、`queue-invariants`、
`silent-fallbacks`、`source-encoding`。

### L-E｜Merge gate（`scripts/merge_worktree.sh` 內嵌）

至少 8 個 ABORT 點：side/detached HEAD、worktree git status 失敗、自我比較 0-commit
（K1618 STRIKE-2）、stale base 無 merge-base、K1262-v6 fail-closed、review-certification
（`experiment_gates.py certify`）、artifact-completeness（`check_experiment_artifacts.py`）、
`--force` 拒絕。

---

## 2. 三個問題的實測回答（2）

**觀測窗**：control-plane 為 `control_gate_lifecycle_latest.json` 的 7 日窗
（2026-07-29T08:01Z → 08-05T08:01Z）；decisions log 另涵蓋 07-30 → 08-03。
**誠實邊界**：任務要求 30 天，但 lifecycle inventory 的窗口是 7 天且由該工具定義，
治理部不改它的口徑去湊 30 天。下表數字一律標為 7 日。

### 2.1 有觸發紀錄的 11 道（7 日）

| gate | mode | trigger | **block** | 候選數 | block/候選 | 判讀 |
|---|---|---|---|---|---|---|
| `event_reaction_coverage` | hard_block | 246 | **246** | **1** | **246** | ❌ **擋錯（死鎖）** |
| `dispatch_starvation_lockout` | selection_constraint | 72 | 72 | 14 | 5.1 | ⚠️ 反覆 |
| `dispatch_collision` | hard_block | 54 | 54 | 6 | 9.0 | ⚠️ 反覆 |
| `release_lazypack_completeness` | selection_constraint | 8 | 8 | 3 | 2.7 | ⚠️ 待查 |
| `publisher_arc_dedup` | warn | 215 | 7 | 57 | 0.12 | ✅ 擋對 |
| `anti_ai_style` | selection_constraint | 48 | 4 | 36 | 0.11 | ✅ 擋對 |
| `publisher_provenance_contract` | hard_block | 4 | 4 | 4 | 1.0 | ✅ 擋對 |
| `publish_throttle` | selection_constraint | 74 | 0 | 48 | 0 | ✅ 零阻擋 |
| `task_generation` | selection_constraint | 339 | 0 | 6 | 0 | ✅ 零阻擋 |
| `publisher_coverage_metadata_gap` | warn | 19 | 0 | 6 | 0 | ✅ 零阻擋 |
| `release_pool_arc_dedup` | selection_constraint | 3 | 0 | 3 | 0 | ✅ 零阻擋 |

**判準**：block/候選 ≈ 1 代表擋一次、對方修好就過（健康）；≫ 1 代表同一個候選被反覆
擋而始終沒能通過——**gate 沒有給出可走的出路，或出路走不通**。

**總計 663 次阻擋只落在 30 個不同候選上。** 老闆感受到的「動不動被鎖」，
數學上就是這個比值。

### 2.2 零觸發的 18 道（7 日內完全沒有紀錄）

`event_stage_idempotency`、`hourly_pregate`、`phase_z_baseline_ownership`、
`candidate_silent_fallback_audit`、`worktree_merge_ownership`、`dispatch_worker_ownership`、
`release_content_audit`、`member_qa_publish_identity`、`event_cross_stage_similarity`、
`publisher_title_identity`、`publisher_content_depth`、`publisher_digest_identity`、
`publisher_digest_recap`、`publisher_k_coverage`、`publisher_cluster_cap`、
`event_metadata_contract`、`publisher_image_url_contract`、`publisher_cjk_font_contract`。

**零觸發 ≠ 該退役。** contract 型 gate（provenance / image_url / cjk_font / metadata）
的正常狀態就是零觸發——上游沒犯錯。**它們不是老闆體感的來源**（沒擋到人就不會被感覺到），
所以不列入收斂範圍。唯一例外是 `hourly_pregate`（見 §3-C）。

### 2.3 L-B/L-C/L-D/L-E 四層：**無法回答**

`.claude/hooks/pretooluse-bash-optimizer.sh` 不寫任何 deny log（已逐行確認）；其餘 hook
同樣只回傳 `permissionDecision`，不落盤。git hook、merge gate 也沒有拒絕 receipt
（`storage/ops/` 下無 merge 拒絕紀錄）。CI 統計本次取不到（`gh` 在本 session 的
don't-ask mode 下被擋，非工具不存在）。

**這四層合計 8 條 deny 規則 + 6 個 hook + 5 個 git hook + 6 個 CI job + 8 個 merge ABORT
點，全部沒有觸發計數。** 老闆說「動不動被鎖」，很可能有相當比例來自這裡——而我們拿不出
任何數字證實或反駁。

### 2.4 deny 訊息有沒有出路（per `feedback_gates_smooth_no_deadlock`）

抽查結果分歧：

- ✅ **範本級**：`write_claim_guard.py:207-219` 給了持有者身分、到期倒數、**三條編號出路**
  外加具名的硬搶逃生門（`OVERRIDE_ENV=1`，會留紀錄）。
- ✅ `pretooluse-bash-optimizer.sh` 的 commit 非 ASCII 規則：講了為什麼不可回復，並給出
  `Write /tmp/msg.txt` + `git commit -F` 的完整替代路徑。
- ✅ `merge_worktree.sh` K1262-v6：明說「既不移除也不擴大 commit 來源，請人工確認」並列指令。
- ❌ **control-plane gate 的 decisions log 只寫 `reason`**，例如
  `age_hours=264.5 threshold_hours=72.0`。這是**狀態陳述，不是出路**。候選被擋 246 次
  卻始終沒有一句「你該做什麼才能過」——這正是 §2.1 高比值的機制解釋。

---

## 3. 分類處置提案（3）

### A｜❌ 擋錯 → 立即收斂：`event_reaction_coverage`（P1）

- 7 日內對**單一** task `event_article_fomc_2026-07-29_tplus0` 擋了 246 次。
- `audit_health.unhealthy_sources` 同時指出它讀的 `storage/next_tasks.json` 是
  `missing_or_malformed_task_deadlines`，任務 id 正是同一個。
- **判定**：gate 在對一筆自己都讀不動的資料反覆行使 hard_block。這不是防護，是活鎖。
- **提案處置**：不是放寬 gate，是修上游那筆 malformed deadline（**owner = platform_eng**），
  並替 control-plane gate 加一條通則：**同一候選被同一 gate 擋滿 N 次（建議 N=5）即自動
  升級為 incident，不再靜默重擋**。這條通則的 owner 是既有的 `control_gate_lifecycle.py`，
  不新建機制。

### B｜⚠️ 反覆但可能擋對 → 補出路，不退役

`dispatch_starvation_lockout`（5.1）、`dispatch_collision`（9.0）、
`release_lazypack_completeness`（2.7）。這三道擋的都是真問題，但候選一再撞牆說明
**修復路徑沒有寫在 deny 訊息裡**。

- **提案處置**：control gate registry 增設必填欄位 `remedy`（一句可執行的出路），
  由 `control_gate_lifecycle.py` 在 registry 校驗時強制（比照現行 `incident_refs` 必填），
  並寫進 `control_gate_decisions.jsonl`。**owner = 既有 lifecycle 模組**，同樣不新建機制。
- 這一條直接對應 `feedback_gates_smooth_no_deadlock`：block 必附「修復／寬限／裁決」三選一。

### C｜🧟 殭屍 → 提請退役：`hourly_pregate`

- 近 30 天 **527 筆全部是 `mode=shadow`，0 筆 real decision**；其中 would_skip=True 僅 39 筆。
- 最後一筆 2026-07-30 後即無紀錄。它有一張 review task 掛著
  （`control_gate_review_hourly_pregate_20260730T040739_...`）。
- **提案處置**：兩條路請經理擇一——(i) 轉 real 讓它真正生效，(ii) 退役並刪 shadow log 寫入。
  **治理部不自行退役**，但明確指出「永遠 shadow 的 gate 只在產生 log 噪音」。

### D｜✅ 保留（賺取存在價值，不動）

`publisher_arc_dedup`、`anti_ai_style`、`publisher_provenance_contract`（block/候選 ≈ 1，
擋一次就修好）、4 道零阻擋的 selection_constraint、18 道零觸發的 contract gate、
以及 L-B/L-C/L-E 全部（無證據顯示擋錯，**且沒有證據就不動 gate**）。

### E｜🔭 補上可觀測性（本盤點唯一建議新增之物）

L-B 四層無 telemetry。**提案**：`pretooluse-bash-optimizer.sh` 與各 hook 在 deny 時
append 一行到 `storage/logs/hook_denials.jsonl`（`ts / owner / rule_key / cwd`，不記命令
全文以免洩漏）。這不是新 gate，是既有 gate 的計量。**owner = enforcement_layer_map 已登記
的各 hook 自身**，30 天後可用同一套 §2.1 判準複審這四層。

---

## 4. Anti-stacking 檢查（4）

逐一查同一 concern 是否疊了多個 owner：

| concern | 涉及機制 | 判定 |
|---|---|---|
| 實驗 artifact 完整性 | `merge_worktree.sh:628` + `.github/workflows/experiment-artifacts.yml:75` | ✅ **不算疊層**：兩道門**跑同一個 script**（`check_experiment_artifacts.py`），workflow 註解明寫 "Both doors run the SAME script"。單一 owner、雙入口，是正確設計 |
| arc dedup | `publisher_arc_dedup`(warn) + `release_pool_arc_dedup`(selection_constraint) | ⚠️ **疑似疊層**：同一 concern 兩個 gate_id、不同 mode。請經理指派複核何者為 owner |
| digest 身分 | `publisher_digest_identity`(hard_block) + `publisher_digest_recap`(selection_constraint) | ⚠️ 同上，兩者皆 7 日零觸發，優先序低 |
| 內容品質 | `release_content_audit` + `publisher_content_depth` + `anti_ai_style` | ⚠️ 三個 gate_id 切同一塊。三者皆非老闆體感來源（阻擋數 0/0/4），**建議不動**，僅登記 |
| 併發寫入 | `write_claim_guard.py`(hook) + `git_writer_lock`(lease) + `reference-transaction`(git hook) | ✅ **不算疊層**：分別管「編輯前」「commit 時」「ref 變更時」三個不同時點，職責不重疊 |
| Silent fallback | `silent-fallbacks.yml`(CI) + `pre-commit` + `candidate_silent_fallback_audit`(control gate) | ⚠️ **三層同 concern**。`.claude/rules/no-silent-fallback.md` 是規則 owner，但機械執行點有三個。建議收斂為單一 script 三入口（比照 artifact gate 的正確範例） |

**額外發現（D 級，需修）**：`scripts/audit_enforcement_map.py` 報
`docs/governance/enforcement_layer_map.md` **OUT OF DATE**——`write_claim_guard.py` 在磁碟上
但不在表內。稽核工具自己的話：「A stale index makes agents stack a new layer on top of an
owner that already exists.」**索引過期正是疊床架屋的溫床。** 這張表是治理部轄區，
但 `docs/` 不在本部門 owned_paths，請經理指派歸屬後補登。

---

## 5. 給經理的裁決清單

| # | 提案 | 建議 owner | 建議優先序 |
|---|------|-----------|-----------|
| 1 | 修 `event_article_fomc_2026-07-29_tplus0` 的 malformed deadline，解掉 246 次活鎖 | platform_eng | **P1** |
| 2 | control gate 加「同候選連擋 N 次自動升 incident」通則 | platform_eng（`control_gate_lifecycle.py`） | P1 |
| 3 | control gate registry 增設必填 `remedy` 欄位並寫入 decisions log | platform_eng | P2 |
| 4 | `hourly_pregate` 二擇一：轉 real 或退役 | **經理裁決**後指派 | P2 |
| 5 | hook 層 deny telemetry（`storage/logs/hook_denials.jsonl`） | platform_eng | P2 |
| 6 | `enforcement_layer_map.md` 補登 `write_claim_guard.py` | 經理指派歸屬 | P2 |
| 7 | 複核 arc dedup / digest / silent-fallback 三組疑似疊層 | governance（下一輪） | P3 |

**治理部沒有動任何 gate。** 上述七項全部等經理裁決。

---

## 6. 誠實邊界

1. 阻擋統計窗口是 **7 天**（工具定義），不是任務要求的 30 天。未改工具口徑湊數。
2. L-B/L-C/L-D/L-E 四層的「擋下幾次」**無法回答**，因為沒有 telemetry。這是缺口，不是零。
3. CI 觸發統計本次未取得（`gh` 在本 session 被 don't-ask mode 擋下，非 CLI 缺失）。
4. 「擋對／擋錯」的判準是 **block/候選比值**，屬治理部自訂啟發式，不是既有系統定義的指標。
   比值高只證明「反覆撞牆」，不直接證明 gate 邏輯錯——`event_reaction_coverage` 之所以
   判為擋錯，是因為另有 `audit_health` 的 malformed 證據佐證，其餘三道只標 ⚠️ 待查。
