# PHASE-Z 檔案堆積 78 班 — 外部第二意見與重構方向裁決

**日期**：2026-07-19（hourly slot-1，job `4684d8b70a50494d8fefa274d1c272ff`）
**觸發**：老闆 Telegram msg 1117「你解決不了 就立刻去問 claude desktop」→ 任務 `assign_a006f8ed`
**Class**：error_log §B（Git owner / canonical-write）— 本 class 第 6+ 次復發，已達 3-STRIKE

---

## 1. 先推翻原任務描述的因果假設

原票的待驗假設是：**PHASE-Z 的 post-commit 測試閘門紅 → 收班被擋 → 檔案永遠留在工作區**。

**這是錯的**，三條獨立證據：

1. **閘門在 commit 之後跑，且只發警報**（`phase_z.py:84-85` 的 `post-commit test gate`）。它在結構上不可能擋住一個已經發生的 commit。
2. **那條紅燈現在是綠的**。用警報裡逐字的重現指令跑：
   `scripts/tests/test_git_writer_lock.py scripts/tests/test_orphan_namespace_registry.py scripts/tests/test_orphan_reaper.py scripts/tests/test_reap_paper_artifacts.py tests/test_reap_draft_artifacts.py` → **66 passed**。
   而 `git log f0350b91294c..HEAD -- scripts/reap_orphan_deliverables.py scripts/tests/test_orphan_reaper.py` **沒有任何 commit** —— 沒人修過它，它自己變綠了。
   ⇒ `test_job_reaper_rejects_agent_external_directory_symlink_and_ignored_paths`（`StopIteration`，line 341）是**環境相依的 flaky test**，不是迴歸。
3. **時間對不上**：最長的 foreign streak 是 **78 班**（三天以上），遠早於 07-19 14:42 那次紅燈。

⇒ 堆積**不是閘門故障，是所有權規則照規格運作的必然結果**。

## 2. 現況硬數據（`.git/volpred_phase_z_foreign_streak.json`，40 筆）

| 連續班數 | 路徑 |
|---|---|
| 78 | `experiments/k1380/`（README / k1380.py / losses_all.npy / results.json / spa_from_cache.py + 3 個 `*_INVALID_20260716.*`）、`storage/work_log.json.bak_graphify_verdict_20260717` |
| 73 | `scripts/gen_codex_cli_reference.py` |
| 38 | `src/volpred/ops/next_tasks.py` |
| 35 | `scripts/telegram_poll.py` |
| 22 | `config/runtime_schedules.json`、`scripts/daily_checkup.py`、`scripts/dreaming_review.py`、`scripts/reclaim_stale_worktrees.py`、`scripts/tests/test_scheduler_max_slots.py`、`tests/test_dreaming_review.py` |
| 17 | `conftest.py`、`scripts/fb_realchrome_post.py`、`scripts/merge_worktree.sh`、`scripts/supabase_sync.py`、`scripts/tests/test_merge_worktree.sh`、`tests/test_supabase_sync_cache_purge.py` |
| 8 | `scripts/continue_task_dispatch.py`、`scripts/task_pool_claim.py`、`src/volpred/ops/dreaming_revalidate.py`、`tests/test_task_pool_claim.py`、`tests/test_dreaming_revalidate.py`、`tests/.!71268!test_task_pool_claim.py`(AFP 垃圾檔) 等 |
| 3 | `paper/*/data/*.csv` ×2、`scripts/build_knowledge_index.py`、`scripts/check_experiment_artifacts.py`、`scripts/repoint_snapshot_from_db.py` 等 |

CRITICAL 警報**有正常發**（3/6/12/24… 班退避）。**78 班零行動**。

## 3. 外部第二意見（取得方式與逐字結論）

**取得方式的誠實揭露**：老闆指定「Claude Desktop」。Claude Desktop 是 GUI 應用，hourly fire 是 headless 程序，**本班在技術上無法驅動它**（repo 內也沒有任何 desktop bridge —— 已掃 `scripts/`、`~/.volpred/bin/`）。因此改用 repo 既有的正式外部審查通道 **`codex exec`（GPT，異廠異模型，老闆已授權「codex 額度無限制」）**，問題陳述存於 `/tmp/phase_z_problem_statement.md`（內容見下方摘要）。若老闆要的就是 Claude Desktop 本身，需在互動 session 補做，本文的裁決在那之前有效。

### 外部意見的四點結論

**(1) `owned = dirty_now - baseline` 根本不是 ownership**，只是「這段時間內首次被觀察到變髒」。在共享 checkout 上有三個必然誤判：
- 開班前已髒、本班又修改 → 算 foreign，**本班貢獻遺失**；
- 開班後由 human / Codex 修改 → 算 owned，**誤算成本班產出**；
- 兩人同改一個 path → path set 根本無法拆出各自 diff。

集合差只在「單一 writer、期間內 checkout quiescent」時成立。**正確的 primitive 是 producer-scoped workspace**：每個 fire / interactive / Codex session 各自 worktree + branch，ownership = `task_id + workspace ref + parent SHA`，收班先 commit 到該 task 的 WIP ref，測試過後由**序列化 integrator** 併 main；衝突留在 branch 進 blocked，不留在共享 main。daemon 狀態改走單一 writer API/DB，不讓多個 daemon 直接改 main 的版本化檔。成本是 worktree lifecycle / 依賴與 cache / merge 衝突 / 整合延遲 / 修掉依賴 canonical cwd 的腳本。

**(2) 「不掃進 main」與「不遺失」必須拆開。** 現行設計只保證不誤發佈；**dirty working tree 不是 durable preservation** —— 它可被下一個 writer 覆寫、被人 reset、被清理流程刪除。正確的界線是：

> **不確定的內容一律自動保存，但絕不自動進 main。**

即：producer 結束或 crash recovery 時把狀態 checkpoint 成 WIP commit/ref 或不可變 patch bundle（不要求測試過、不宣稱完成）；main 只接受有 task receipt + gate 過 + 完成整合的 commit；partial / invalid / conflicted 都是合法 quarantine state，**「無限期裸躺工作區」不是**。

**(3) CRITICAL 為何 78 班零行動 —— 因為它是 notification，不是控制流程。** 沒有單一必須接手的 owner、沒有 deadline、**沒有對 scheduler 的 admission control**、未解決不影響後續 fire、沒有可驗證的 terminal postcondition。結構性閉環應是：streak 過門檻 → 建**持久 incident**（而非再發一封信）→ scheduler 進 recovery/admission-held（不再讓新 writer 用該共享 checkout）→ 系統自動把無 live lease 的內容 checkpoint 進 quarantine ref → 指派 resolver 直到 postcondition 成立（每個 dirty path 都對應 live workspace 或 immutable WIP ref，main checkout 回到乾淨）。**只有語意衝突與是否進 main 才找人；保存動作不需要人批准。**

**(4) 歷次修復的共同失敗點（最尖銳的一段）**：它們都保留了原始的錯誤抽象，再往上疊事後猜測 ——
- 用目錄、suffix、mtime、receipt、測試變綠等**結果特徵反推 producer identity**；
- 把新 orphan 類別加進 recognizer / registry / bucket，而不是讓 producer 一開始就在隔離 transaction 裡；
- 把 liveness 委託給另一個 best-effort consumer，而 reaper task 又和一般任務競爭資源，也沒有阻止新 fire 繼續製造狀態；
- 測試只證明「這個已知樣本有出口」，**沒有證明「任何 writer crash / 同 path 並行 / pre-dirty 再修改 / 未知檔案類型，都在有限班數內必達 terminal state」**。

特別點名 `config/orphan_namespaces.json` 的「在 `experiments/` 裡所以預設可收編」仍是 **semantics-as-provenance**：目錄位置不能證明作者、完整性或 readiness ——「K1380 正好展示了這個限制」（那 8 個檔含刻意標記的 `*_INVALID_20260716.*`）。`_adopt_orphan_halves` 也只是更窄的因果猜測：「讓某測試變綠」≠「由正確 producer 產生」。

> **核心盲點（逐字）**：「你一直在讓 cleanup layer 解 ownership。Ownership 必須由 execution isolation 產生，不能由 cleanup layer 事後推理。」

## 4. 裁決（採納方向）

**採納 (2) + (3) 為立即方向，(1) 為目標終態，明確不再做 (4) 型的補丁。**

| # | 決定 | 理由 |
|---|---|---|
| D1 | **停止一切「再加一個 recognizer / namespace / 收編條件」型修復** | 本 class 已 6+ 次，全部是同一個錯誤抽象的延伸 |
| D2 | **先落地「不確定 ⇒ 自動保存到 quarantine ref，絕不自動進 main」** | 這是把「never lose」從 0 分變成 1 分的最小改動，且不放寬任何既有安全性（不碰 main、不碰工作區） |
| D3 | **streak 過門檻改為建立持久 incident + admission control**，而不是再發一封 CRITICAL | 沒有 actuator 的警報等於紅色日誌 |
| D4 | **終態走 producer-scoped workspace**（每個 fire 自己的 worktree + branch + 序列化 integrator） | 唯一能真正產生 ownership 的作法；但這是多班的架構工程，必須切段做 |
| D5 | K1380 那 8 個檔（含 `*_INVALID_20260716.*`）**不由 cleanup layer 猜著收** | 它們是有語意的實驗裁決產物，只能由知道 K1380 現況的人/任務裁決 |

**不採納的部分**：外部意見主張「若堅持共享 checkout，file lease 也只能降低風險、不能稱為正確歸因」—— 同意其論斷，但共享 checkout 短期無法拆除（19 個 worktree、大量腳本假設 canonical cwd），故 D2/D3 是在錯誤模型上的**止血**，不宣稱是根治；根治是 D4。這一點必須誠實寫在任何後續驗收裡。

## 5. 本班已做 / 未做

**已做**：推翻原因果假設（3 條證據）｜取得並存檔外部意見｜本裁決文件｜error_log §B 加一行｜bug class 全量掃描（下節）｜queue 出 D2/D3/D4/D5 與 flaky test 的後續任務。

**未做（且刻意不做）**：沒有動那 44 個檔（本班規則禁止 agent 跑 git mutation，且 D5 明確要求逐類裁決）；沒有實作 D4；沒有猜 flaky test 的修法。

## 6. Bug class 全量掃描

掃描問題：**還有哪些地方是「用結果特徵反推 producer identity」？**

| 位置 | 形態 | 判定 |
|---|---|---|
| `phase_z.py` `owned = dirty_now - baseline` | 用「觀察時間」反推作者 | **class 本體**，D4 處理 |
| `phase_z.py::_adopt_orphan_halves` | 用「測試變綠」反推作者 | 同 class，範圍窄、已知不能收 test/config/doc/rename |
| `config/orphan_namespaces.json` | 用「目錄位置」反推可收編性 | 同 class，K1380 即反例 |
| `scripts/reap_orphan_deliverables.py` | 用 job receipt 的 `output_paths` 反推 | **不同**：receipt 是 producer 自己宣告的，屬正當 provenance；但它只覆蓋有 receipt 的 job |
| `volpred.ops.machine_churn`（lock + parse） | 用 **live flock** 判 liveness | **不同**：flock 是真實的 producer 訊號，非事後猜測。這是本 repo 唯一做對的那一個 |

⇒ class 成員 3 個（`owned` 差集、`_adopt_orphan_halves`、`orphan_namespaces.json`），皆歸 D4 統一處理；不逐個補丁（否則就是第 7 次）。

## 7. 機械 gate

`scripts/tests/test_phase_z_ownership_class_gate.py`：
1. **釘住 class 成員清單** —— 上述 3 個 provenance-guessing 位置若有人新增第 4 個（新的 recognizer / namespace / 收編條件），測試紅，強迫回來讀本文的 D1。
2. **釘住「不確定 ⇒ 必須可持久保存」** —— 斷言 foreign streak 的 CRITICAL 路徑不得是唯一出口（`_streak_is_notifiable` 之外必須存在 quarantine/incident 出口的呼叫點），未落地前以 xfail-strict 形式釘住 D2/D3 的缺口，落地時自動轉綠。

## 8. flaky test（`test_orphan_reaper.py::test_job_reaper_rejects_agent_external_directory_symlink_and_ignored_paths`）

現在是綠的，且無 intervening commit ⇒ 環境相依。**刻意不猜修法**（那正是外部意見第 4 點批評的行為）。已 queue 一張任務，要求**先建可重現的 harness**（在變動 `TMPDIR`（`/var` ↔ `/private/var` symlink）、git 版本、global `core.excludesFile` 下重跑 N 次），能穩定重現再談修。

---

**相關**：`docs/error_log.md` §B ｜ `docs/governance/2026-07/git_single_writer_transaction.md` ｜ `docs/fix_56ddf72b_dirty_guard.md` ｜ 歷次同 class 任務 `assign_bc041e57` / `assign_01127566` / `assign_5f16a7c5` / `assign_d8b55d37` / `assign_6e8ece3f` / `assign_c0ad1962`
