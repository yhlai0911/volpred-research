# 3-STRIKE 重構：agent 產出的 commit 歸屬

**Task**: `refactor_agent_output_commit_ownership`（P1）
**觸發**: 老闆 Telegram msg 576「還是一直出錯啊」
**執行**: 2026-07-13 hourly-07（主線程）
**Commit prefix**: `refactor(3-strike):`

---

## 0. 症狀

每班 dispatch 結束後，agent 的產出留在工作區沒 commit，由 supervisor 的 PHASE-Z「safety-net」
兜底 auto-commit。commit message 寫著：

```
ops(dispatch-supervisor 03:21): PHASE-Z safety-net auto-commit (agent left uncommitted)
```

近 24h 實測（`git log --grep=PHASE-Z`）：

| 時間 | commit |
|---|---|
| 23:30 | safety-net auto-commit (agent left uncommitted) |
| 00:21 | safety-net auto-commit (agent left uncommitted) |
| 02:26 | safety-net auto-commit (agent left uncommitted) |
| 03:21 | safety-net auto-commit (agent left uncommitted) |
| 04:39 | safety-net auto-commit (agent left uncommitted) |

**5/5 有產出的 fire 全部走 safety-net。** 例外路徑就是主線。每次巡檢重報一次「agent 沒 commit」，
老闆看到的是「系統一直出錯」。

**先澄清一件事**：工作**沒有遺失**。PHASE-Z 確實把產出 commit 了。這是一個
**責任歸屬 + 觀感** 的缺陷，不是資料遺失事故 —— 但它每小時對老闆謊報一次系統健康狀態，
且讓真正的異常訊號淹沒在假警報裡。

## 1. 三層診斷

### 底層邏輯：一個 concern，兩個 owner

「commit 本班產出」這件事同時被交給兩個 actor：

- **prompt 散文**（`cron_hourly_dispatch_prompt.md` PHASE Z）要 agent 自己 `git add` + `git commit`
- **機器**（`dispatch_supervisor/phase_z.py`）在 fire 結束後也 commit 一次

`scheduler.py:385` 的註解是這個設計的自白：

> The dispatched agent's own PHASE Z is prompt-discretion (~90% reliable), so this
> wrapper-level commit captures whatever it left.

**責任雙頭必然導致一方鬆懈**，而鬆懈的一定是 LLM 那一方 —— 因為機器那方永遠會兜底。
實測「~90% reliable」是樂觀估計：真實命中率是 **0/5**。

更根本的問題：**「該 commit 哪些檔」是機械判斷，不是語意判斷。** phase_z 有 fire 起始基線，
精確知道哪些路徑是這班新產生的；agent 只能憑印象猜自己動過什麼。那個猜測已經造成三次事故
（`docs/error_log.md` 2026-07-10）：`git add -A` 收走被截斷的 `next_tasks.json`、把繞過測試閘門的
改寫送進 main、把某互動 session 沒改完的 `merge_worktree.sh` commit 進不相干的訊息裡。

**把機械判斷交給 LLM，再寫一個機器去兜底 LLM 的失誤 —— 這是純負債。**

### 流程：例外路徑變成常態路徑

PHASE-Z 自稱 safety-net（例外），但 5/5 的 fire 都走它。當例外變成 100% 的主線，
它的命名與告警語意就全錯了：

- commit message 說 `agent left uncommitted` → 讀起來像 agent 失職
- 每班巡檢看到 dirty tree / safety-net commit → 重報一次
- 真正該被看見的異常（例如產出無人交代原因）淹沒在每小時一次的假警報裡

**沒有任何反饋回到 agent**：它不 commit，機器默默收拾，沒有訊號說「你漏了」→ 永遠不會改善。

### 架構：discretion 放錯了軸

LLM 的不可靠是給定條件，不是可以靠更多散文修好的東西。架構問題是
**「把 LLM 的不可靠放在哪條軸上」**：

- **舊設計**：discretion 在「工作會不會被正確 commit」這條軸 → 失敗模式是
  **結構性的**（dirty tree / 被下一班誤收 / 別人的檔被收走）
- **正確設計**：discretion 只能落在**非關鍵軸**上 → 失敗模式必須是**裝飾性的**

## 2. 方案：git 歸機器，理由歸 agent

責任切分依「誰知道什麼」：

| 誰 | 知道什麼 | 職責 |
|---|---|---|
| **phase_z.py**（機器） | fire 起始基線 → 精確知道**哪些檔**是這班產生的 | 決定收哪些檔 + 執行 commit（**唯一 owner**） |
| **agent**（LLM） | **為什麼**改（機器永遠不可能知道） | 留下 commit 說明（fire receipt） |

### 落地

1. **`scripts/fire_receipt.py`**（新）— agent 的整個 PHASE Z 收斂成一行 CLI：
   ```bash
   uv run python scripts/fire_receipt.py --task-id <id> --subject "<what | why>" --body "<細節>"
   ```
2. **`phase_z.py`**（改）— receipt 寫進 git dir（同 pre-fire snapshot 慣例：`git status` 看不到、
   per-checkout、永不可能被 commit）。`run_phase_z()` 開頭 **read-and-consume**（單一呼叫點，
   任何 exit path 都不可能把 receipt 洩漏到下一班）。commit message：
   - 有 receipt → `dispatch(HH:MM): <agent 的 subject>` ← **正常路徑，不再有 "safety-net" 字樣**
   - 有產出但無 receipt → `dispatch(HH:MM): 本班產出未附說明（agent 沒留 receipt）` + **warn alert**
   - 無產出（只有 machine churn）→ 維持 `PHASE-Z state churn`（正常，不 alert）
3. **prompt PHASE Z**（改）— 從「你要 git add + commit」改寫成「你要留 receipt」；
   **明文禁止 agent 碰 git**。依 CLAUDE.md anti-stacking：機械化之後 prose 縮成 pointer。

### 失敗模式的位移（這是整個重構的重點）

| | 舊設計 | 新設計 |
|---|---|---|
| agent 盡責 | 工作被 commit | 工作被 commit + 好的 message |
| **agent 漏做** | **工作裸躺工作區**、靠兜底、可能被下一班誤收、別人的檔可能被 `git add -A` 收走 | **工作照樣被 commit**，只是 message 是系統生成的 + 一則 warn |

失敗成本從「結構性風險」降到「commit message 變醜」。

## 3. 廢棄面（不留兩套並行）

- ❌ prompt PHASE Z 的 `git add -- <paths>` / `git commit -m` 區塊 — **已刪**
- ❌ commit message 字串 `PHASE-Z safety-net auto-commit (agent left uncommitted)` — **已從正常路徑移除**
  （由 `test_normal_commit_no_longer_reads_as_a_failure` 釘住，防回歸）
- ⚠️ `scripts/cron_hourly_dispatch.sh` 的 PHASE-Z shell 區塊仍含舊字串 —— 該 wrapper 已於 2026-07-04
  launchctl-disabled（保留作一鍵回滾 artifact），**不在執行路徑上**，故不動。真正退役時一併刪。

## 4. 驗證 gate

`scripts/tests/test_phase_z_receipt.py`（6 tests），每個 test 釘住一個 incident 觸發條件：

| test | 釘住的 incident |
|---|---|
| `test_receipt_becomes_the_commit_subject` | agent 的「為什麼」要真的進 git log |
| `test_no_receipt_still_commits_and_warns` | 漏 receipt **不可**掉工作（失敗模式必須是裝飾性的） |
| `test_normal_commit_no_longer_reads_as_a_failure` | 舊字串不可回歸（否則老闆又看到「一直出錯」） |
| `test_foreign_paths_are_never_swept_in` | 2026-07-10 `git add -A` 偷別人的檔 |
| `test_receipt_does_not_survive_its_fire` | 上一班的 receipt 不可 caption 下一班的 commit（**假 audit trail 比沒有更糟**） |
| `test_stale_receipt_is_refused` | 過期 receipt = 那班 fire 根本沒跑完 |

**Break-then-verify 已執行**（control-plane.md：兩邊都會過的測試等於沒有測試）：
在**臨時 worktree**（不在 daemon 腳下抽地毯）移除 `_read_and_consume_fire_receipt` 的 unlink →
`test_receipt_does_not_survive_its_fire` 如預期紅燈（`AssertionError: a stale receipt captioned the next fire`）。
gate 咬得住。

**上線後的觀測 gate**：接下來幾班 fire 的 commit message 應該是 `dispatch(HH:MM): <真實理由>`。
若仍出現 `本班產出未附說明` → agent 沒照新 prompt 跑 receipt，查 prompt 是否被改壞。

## 5. 為什麼這次不是又一個 patch

CLAUDE.md 的 anti-stacking 條款寫得很清楚：**一個 concern 只有一個 enforcement owner；
升級路徑是 prose 提醒（strike 1）→ 機械 gate（strike 2+），機械化後 prose 縮 pointer。**

這次沒有新增第 N 個 watchdog / flag / retry。相反：**移除了一個 owner**（prompt 散文的 git 指令），
把 concern 收斂到既有的機械 owner（phase_z.py）。prompt 從「命令 agent 做機械動作」降級成
「請 agent 提供只有它知道的語意」。層數是 **少了一層**，不是多了一層。
