# daily_update dirty-guard — 根因與修復（task assign_56ddf72b）

**日期**：2026-07-16　**Worktree**：`wt/dispatch-slot-1-a9b8c1b6-dirtyguard`　**Commit**：`77b969488`

---

## 1. 根因定案

### 假說裁決：部分成立，兩點被證據推翻

指派 brief 的假說是「feed.json 被 publish/release 寫入後未即時 commit，或與同分鐘的
`git_push_backup` 撞在一起 → 每天穩定重踩」。實際查證後：

| brief 的說法 | 裁決 | 證據 |
|---|---|---|
| feed.json 常被寫入後未 commit | ✅ **成立** | `release_pool`（`7 */6 * * *`）跑 `volpred ops release-pool-by-settings`，不 commit。`git log -- feed.json` 顯示 committer 全是 `[codex]` agent 與 `dispatch(HH:MM)` 自動 commit，即**別的工作的副作用** |
| 與 `git_push_backup` 同分鐘 → working tree 競態 | ❌ **推翻** | `git_push_backup` 在 ownership policy 分類為 `no_repo_tracked_output`；讀 `cron_git_push_backup.sh` 確認它只 `git rev-list` + push **既有 commit**，從不碰 working tree。14:00 同時觸發是真的，但**因果上無效** |
| `host_cron_fail` 跨 13 天（7/02→7/15）屬同一慢性根因 | ❌ **推翻** | dirty-guard 是 **2026-07-13 17:58** 由 `94928252f` 引入的（`git log -S'dirty_paths_before_write'`）。7/13 之前它不存在。`host_cron_fail` 是把**所有 cron 非零退出聚合在一起**的泛用 signature，13 天跨度混了不同根因 |

另：brief 引用的「exit=1 硬失敗」在我開工前 40 分鐘已被 `2f9793b59`（22:36）改成 sentinel 120。
本次開工時 C 層已完成，見 §2.C。

### 真正的根因：**guard 是一個 latch，不是 guard**

`writable_output_paths()` 把 dirty 路徑排除在**寫入集**外，`commit_owned_outputs()` 用**同一個
flag** 把它排除在 **commit 集**外。對於「唯一 committer 就是這個 job」的輸出，
「這輪跳過」等於**「每輪都跳過」** —— 唯一會清掉這個髒的那一輪，被它自己擋掉了。

第一次變髒 → 永遠髒。

**「dirty」被拿來代表「別人正在編輯」，但這些檔沒有人手作者**（CLAUDE.md「永遠修流程，不修資料」、
publishing.md 對 paper_trading.json 的規定都明文禁止手改），所以 dirty 幾乎永遠只代表
**「某個 sibling daemon 寫了，還沒人 commit」**。

### 兩個表現形態（同一個 bug）

**(a) `frontend-v2-fix/data/strategy_metrics.json` — 純粹型態、無人搭救、靜默**

PHASE-Z 的 churn 掃描只覆蓋 parent checkout，**巢狀 frontend repo 它管不到**，所以
`daily_update` 是唯一會 commit 這個檔的東西 —— 而它正因為檔案髒而拒絕碰它。

```
$ cd frontend-v2-fix && git status --porcelain -- data/strategy_metrics.json
 M data/strategy_metrics.json
$ git log -1 --format='%h %ad' --date=format:'%Y-%m-%d %H:%M' -- data/strategy_metrics.json
6f14654 2026-07-05 16:20          ← 11 天沒有 commit
```

從 guard 落地的 7/13 起**每一輪都跳過**，每輪 **exit 0**，**沒有任何 alert**。
`scripts/daily_update.py:1627` 的 `recalc_all(frontend_targets=writable_frontend_metrics)` 收到
空 list → 前端策略 metrics 根本沒被重算。

**(b) `storage/reports/feed.json` — 看似間歇，其實是被 PHASE-Z 一直救**

feed.json 在 `_MACHINE_STATE_FILES` 裡，PHASE-Z 每小時 fire 會把它當 churn 收掉。所以它只在
「release_pool/agent 寫入之後、PHASE-Z 收掉之前」剛好撞上 daily_update 時才發作 —— 一場擲硬幣。
兩次輸掉的紀錄（`storage/logs/cron/`，原始 log）：

```
1938:[daily_update] WARN: refusing to overwrite output(s) already dirty before this run: ['storage/reports/feed.json']
1940:  ❌ tracked output already dirty; aborting before daily writes
1941:=== [daily_update_intraday] exit 1 at 2026-07-15T14:00:07+0800 (duration=3s) ===
```
（morning 班 7/16 08:03 同樣一次；`daily_update.log:7000-7002`）

而 parent 的 guard 還多一個問題：`daily_update.py:759` 把 per-path 粒度**塌縮成 all-or-nothing**
（`len(writable) != len(DAILY_TRACKED_OUTPUTS)` → 整輪 hold），儘管 `scheduled_writer_commit`
的 docstring 明寫它是 per-path 設計（「一個 FRED series 髒掉不該擋住其他乾淨 series」）。

### 這是同一個 bug class 的第 4、5 次

| # | 實例 | 症狀 | 處置 |
|---|---|---|---|
| 1 | phase_z 對「已刪除」路徑判 deferred | *"every fire, forever. One had been cycling that way for eight."* | 2026-07-12 修 |
| 2 | `storage/work_log.json` | *"foreign for 35 fires"* | `a8ecca38c`（今天 23:19，另一 session）→ 往硬編清單追加 |
| 3 | `storage/next_tasks_archive/` | 同上，35 fires | 同上 |
| 4 | `feed.json` @ daily_update | 2 次整輪 abort → critical | **本次** |
| 5 | frontend `strategy_metrics.json` | 11 天靜默不 commit | **本次** |

前三次的處置都是**「發現一個就往 `_MACHINE_STATE_FILES` 追加一個」的 per-file patch**。
依 3-strike 規則，本次不再 patch，改**移除 latch 本身**。

---

## 2. 三層修法

### A. 正確性 — 把 guard 收斂到真正的內容衝突

**不是新建機制，是啟用既有機制。** PHASE-Z 早就有真正的判別器，而且在註解裡寫明了：

```python
# Dirty-at-fire-start splits two ways, not one. A daemon-written churn path has
# an owner (this module); only the rest is "another session is still typing it".
```

`_classify_machine_churn()` 用兩道**真實**閘門分辨暫態 vs 衝突：
1. **lock gate** — `fcntl.LOCK_SH|LOCK_NB`。拿不到 = 有 writer **此刻**握著 → 這才是「別人正在編輯」
2. **parse gate** — 內容解析不了 = 寫到一半 → corrupt

daily_update 的 guard 只有一路，把所有 dirty 都當外人。

**改法**（`77b969488`）：

| 檔案 | 改動 |
|---|---|
| `src/volpred/ops/machine_churn.py` | **新增**。classifier 從 phase_z 搬來的**唯一實作**；phase_z 改為委派。**沒有製造第二份拷貝**（若只讓我的 caller 用新模組、phase_z 留舊拷貝，就是我自己造出 dual source） |
| `src/volpred/ops/scheduled_writer_commit.py` | 新增 `probe_dirty_outputs()`（把 `dirty` 與 `unprobed` **分開**）與 `adoptable_churn()`（churn / conflict 二分）。`dirty_paths_before_write()` 保留為兩者聯集，**其餘 5 個 caller 行為完全不變** |
| `scripts/daily_update.py` | parent 與 frontend 兩處都改成：**只有 conflict 才 hold**；churn → 照常寫 + commit |
| `scripts/dispatch_supervisor/phase_z.py` | `_classify_machine_churn` 改為委派共用實作（行為不變，61 tests 綠） |

**guard 沒有被拿掉**，這三種情況照樣擋：
- 有 writer 握著 flock（真的正在編輯）
- 內容解析不了（寫到一半 / 截斷）
- git probe 失敗 → `unprobed`，**與 dirty 分開**，永遠不可 adopt

最後一點是刻意的：`unprobed` 是**事實的缺席**（git 答不出來），`dirty` 是**關於內容的事實**。
舊碼把兩者合併，等於把「我不知道」悄悄升級成「有人擁有它」—— 對其中一個是安全解讀，對另一個
就是 latch。

### B. 根因 — 讓輸出真的被 commit

A 層直接解決 B：**churn 現在會被寫入且 commit**，所以每輪 08:03 / 14:00 都會把
前一輪留下的未提交輸出收乾淨，working tree 不再慢性 dirty。

brief 要求的「錯開 :00 同時觸碰 git tree 的 cron」**不需要做，也不該做** —— 見 §1，
`git_push_backup` 不碰 working tree，競態不存在。錯開 cron 只會製造「修了但沒解決」的假象。

**未手動 commit 任何資料**（brief HARD 約束）：本次沒有手動 commit feed.json 或前端 metrics 收尾，
修的是產生 dirty 的流程與判別邏輯。前一 session 的 `ecfcdfbd1` 經查是 daily_update **自己的
self-commit**（訊息與 `daily_update.py:1670` 的 f-string 一致），不是人工補。

### C. Alert 語意 — 已完成（非本次），但有一個盲點

`2f9793b59`（22:36，我開工前）已把 exit 1 改成 sentinel 120。查證屬實：

```
src/volpred/ops/alerts.py:1310  _PUSH_HELD_EXIT_CODE = 120
src/volpred/ops/alerts.py:1311  _BENIGN_FINDINGS_EXIT_CODES = frozenset({_PUSH_HELD_EXIT_CODE})
src/volpred/ops/alerts.py:1735  if int(latest.get("exit_code", 0)) in _BENIGN_FINDINGS_EXIT_CODES: continue
```
→ 120 不進 `failing_logs`，不觸發 `host_cron_fail`。**C 層有效，不需重做。**

該 commit 聲稱「Real damage from a held run (data going stale) surfaces through the data_freshness
checks」。**查證後只對一半**：
- ✅ **整輪 hold**：`_parse_strategy_metrics_freshness_state` 量 `storage/strategy_metrics.json`
  的 mtime；hold 時 daily_update 提早 return 不寫入 → mtime 不前進 → 26h 後 warn。**確實有兜底。**
- ❌ **前端 per-path skip**：daily_update 照常 exit 0、照常寫 parent 的 metrics（mtime 新鮮 →
  freshness **通過**），只有前端那份靜靜地爛掉。**沒有任何偵測器看得到**（見 §4 殘留風險）。

經 A 層修復後，hold 變成罕見且**真的代表「有人正在編輯」**，所以 120 + 26h freshness 的組合
是合理的；本次**不再調整 alert 判準**，避免把真實故障一起 silence（brief 明示的分寸）。

---

## 3. 驗證證據（實際輸出，非摘要）

### 3.1 新 regression suite — 9/9 綠

```
tests/test_daily_update_dirty_guard_latch.py::test_uncommitted_machine_output_is_churn_not_conflict PASSED [ 11%]
tests/test_daily_update_dirty_guard_latch.py::test_churn_stays_in_the_write_set PASSED [ 22%]
tests/test_daily_update_dirty_guard_latch.py::test_old_behaviour_would_have_excluded_it PASSED [ 33%]
tests/test_daily_update_dirty_guard_latch.py::test_live_writer_holds_the_guard PASSED [ 44%]
tests/test_daily_update_dirty_guard_latch.py::test_truncated_content_is_never_adopted PASSED [ 55%]
tests/test_daily_update_dirty_guard_latch.py::test_unresolved_git_probe_fails_closed PASSED [ 66%]
tests/test_daily_update_dirty_guard_latch.py::test_a_deletion_is_adoptable PASSED [ 77%]
tests/test_daily_update_dirty_guard_latch.py::test_mixed_set_holds_only_on_the_real_conflict PASSED [ 88%]
tests/test_daily_update_dirty_guard_latch.py::test_latch_releases_after_one_run PASSED [100%]
============================== 9 passed in 1.40s ===============================
```
（全 hermetic：每個 case 自建 throwaway git repo，不碰真 repo — `feedback_hermetic_git_in_tests`）

對應 brief 要求的三個證明：
- **暫態 dirty 不再殺整輪** → `test_churn_stays_in_the_write_set`、`test_latch_releases_after_one_run`
- **真衝突仍被擋** → `test_live_writer_holds_the_guard`（真的 flock）、`test_truncated_content_is_never_adopted`、`test_unresolved_git_probe_fails_closed`
- **真故障仍會 alert** → §3.4（120 豁免 + 26h freshness 兜底查證）

### 3.2 Break-then-verify — 證明測試真的會咬

把 `adoptable_churn` 改回舊規則（`committable = []`；`conflict = dirty | unprobed`）後：

```
FAILED tests/test_daily_update_dirty_guard_latch.py::test_uncommitted_machine_output_is_churn_not_conflict
FAILED tests/test_daily_update_dirty_guard_latch.py::test_churn_stays_in_the_write_set
FAILED tests/test_daily_update_dirty_guard_latch.py::test_a_deletion_is_adoptable
FAILED tests/test_daily_update_dirty_guard_latch.py::test_mixed_set_holds_only_on_the_real_conflict
FAILED tests/test_daily_update_dirty_guard_latch.py::test_latch_releases_after_one_run
5 failed, 4 passed in 1.27s
```

5 個 latch 測試全紅；另 4 個（guard 保留面）照樣綠 —— 正確，因為它們斷言的行為在新舊規則下相同。
**兩邊都會過的測試等於沒有測試**（control-plane.md）；已於 worktree 內做，未在 production
checkout 抽地毯。改回後重跑 9 passed。

### 3.3 對真實卡死檔案的端到端驗證（唯讀）

對**實際卡了 11 天**的 `frontend-v2-fix/data/strategy_metrics.json` 跑新判別器：

```
REAL latched file, live frontend repo (read-only):
  git-dirty   : ['data/strategy_metrics.json']
  unprobed    : []
  churn       : ['data/strategy_metrics.json'] <- adoptable: run writes + commits it
  conflict    : []
  write set   : ['data/strategy_metrics.json']
```

舊規則下 write set 為 `[]`（由 `test_old_behaviour_would_have_excluded_it` 釘住）。
→ **下一輪 daily_update 會重算並 commit 它，latch 解除。**

### 3.4 回歸 — 107/107 綠

```
uv run --extra dev python -m pytest tests/test_daily_update_dirty_guard_latch.py \
  tests/test_daily_update_guard_held_exit.py scripts/tests/test_scheduled_writer_commit_policy.py \
  scripts/tests/test_phase_z_runtime_state_ownership.py tests/test_phase_z_ownership.py \
  scripts/tests/test_phase_z_receipt.py scripts/tests/test_phase_z_drain_retry.py \
  scripts/tests/test_git_writer_lock.py -q
→ 107 passed in 41.72s
```

過程中有 2 個既有測試轉紅，**都是真實的、我改的**，已修正而非繞過：
- `test_scheduled_writer_commit_policy::test_self_commit_rows_have_guard_and_path_scoped_commit`
  —— **ratchet 正確地咬到我**：它只認得 `dirty_paths_before_write`。已教它同時接受
  `probe_dirty_outputs`（兩者都是真正的 staged+unstaged pre-write guard），**未放寬 ratchet 的意圖**。
- `test_daily_update_guard_held_exit::test_dirty_guard_does_not_return_bare_one` —— 它 pin 的訊息字串
  被我改了，且該測試自己寫著「guard message changed — re-point this test at the new hold path」。
  已 re-point；它真正 pin 的（hold 必須回 sentinel 不可回 1）原封不動。

---

## 4. 殘留風險 / 未解部分（誠實列出）

### 明確未做

1. **前端 metrics staleness 沒有 outcome-level 偵測器**（§2.C 的盲點）。`strategy_metrics_freshness`
   量的是 `storage/strategy_metrics.json`，**不是** `frontend-v2-fix/data/strategy_metrics.json`。
   本次修復讓它不再卡住，但**如果它未來因別的原因再度停止更新，仍然沒有人會知道**。
   這正是 brief 說的「降噪不等於降盲」，我修掉了噪音源，**沒有補上這個盲點**。
   建議後續：`alerts.py` 加一條量測前端 metrics 檔的 freshness 條件。**未做。**

2. **沒有實跑一次完整 daily_update 端到端**。它耗時 250–340s 且會寫 canonical `storage/`；
   brief 限定「只在本 worktree 內寫檔」，故未執行。§3.3 的唯讀驗證證明了**判別結果正確**
   （churn → 進寫入集），但「整輪跑完真的把檔 commit 掉」是由 hermetic 的
   `test_latch_releases_after_one_run` 證明，**不是**在真 repo 上證明的。

3. **`_MACHINE_STATE_FILES` 仍是硬編清單**。本次移除了 daily_update 的 latch，但 PHASE-Z 端
   「哪些路徑有資格被當 churn」仍要人工往清單追加（`a8ecca38c` 就是這個模式）。
   新增一個 daemon 寫的檔而忘了登記 → 它會靜默地變成 foreign。**這個 latch 的上游還在。**

### 已知邊界

4. **daily_update 對 feed.json 是 read-modify-write**（`daily_update.py:1322-1368`：
   `_load_json_retry` → 改 → `write_text`），所以 adopt churn 不會吃掉 agent 剛發的文章 ——
   髒內容就在它讀進來的東西裡面。但這**沒有消除 TOCTOU**：若 agent 在 daily_update 的
   read 與 write 之間寫入，該次寫入仍會遺失。那是**既有的、與本 bug 正交的** race，
   flock gate 只縮小、未消除它。**本次未處理。**

5. **phase_z 是常駐 daemon，改 code 必須重載才生效**（control-plane.md）。本次改動在 worktree、
   尚未合併，故不影響線上 daemon。合併後 `selfreload.py` 會自行接手；若要即時生效走
   `bash scripts/reload_dispatch_supervisor.sh --reason <why>`。**merge 者需注意。**

6. **與並行 session 的交會**：`a8ecca38c`（23:19）是另一個 session 在修同一個 bug class
   （老闆 msg 806）。我已 merge main 進本 branch 保住他們的修復並在其上施工；但**若他們仍在
   編輯 `phase_z.py`，合併時可能衝突**。我的改動只動 `_classify_machine_churn` 的 body
   （改為委派），未動他們改的 `_MACHINE_STATE_FILES` 清單，衝突面應該最小。

### 未驗證的宣稱：無

本文所有數字與輸出均取自實際命令；沒有「應該會過」的宣稱。
