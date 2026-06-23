# Refactor Plan — Atomic K-id Allocation + Topic-Claim Ledger（3-STRIKE）

> **狀態**：PARTIAL（A 層 helper 已落地；入口尚未全面改寫）。2026-06-23 strike 2 觸發後寫。`scripts/kid_reserve.py` 已提供 `fcntl` 原子 K-id reservation 與 regression tests；後續仍需把所有配號入口、topic-claim ledger、in-flight marker 接上。
> **觸發**：K-id 配號/挑題 race，同根因連兩次 ——
> - **strike 1** 2026-06-23 K1534 雙佔（主線程 vs 在飛 worktree，commit 774df789/0fe5d876 vs 0f789f32）
> - **strike 2** 2026-06-23 biodiversity K1536/K1537×2（3 個並行 cron Codex agent 撞同一 journal-discovery 題 + 雙佔 K1537，commit f350674e 收斂）
> 兩次 root 一致：**並行 agent 配 K-id / 挑題無跨 agent 原子協調**。K1534 error_log entry 已明確承諾「strike 2 即落地 atomic K-id reservation」。

## 三層診斷（CLAUDE.md Three-Strike §1-3）

### 1. 底層邏輯（domain model 錯在哪）
- **K-id 不是「目錄列舉的衍生值」，而是一個需要被原子配發的稀缺資源**。現行模型把 K-id 當成「`ls experiments/` 的 max+1」——一個從**可變、部分可見的檔案系統狀態**反推的值。多個 writer（主線程 + N 個 cron worktree + N 個 `codex exec` agent）同時讀同一個「max」就必然撞號。正確 domain model：K-id 配發是 **monotonic counter 的 compare-and-swap**，配發動作本身要 atomic 且對所有 writer 可見。
- **journal-discovery 題目同理**：題目是「待認領的工作項」，不是「任誰掃 backlog 都能自由挑」。缺「已被某 agent claim」的狀態，於是同一題被 N 個 agent 重複認領。

### 2. 流程（workflow 缺陷）
- 配號流程**無 reservation 階段**：agent 直接「挑號 → 開做 → 最後 commit」，中間沒有「先把號鎖起來、別人看得到」的一步。
- 挑題流程**無 claim ledger**：cron tick prompt 是「claim 下一個 pending task」，但 journal-discovery 的「下一個」在多 agent 並行時不是互斥的。
- **observability 缺口**：主線程 autonomous tick 看到未 commit 的半成品時，**無法分辨**「孤兒 orphan（該收）」vs「正在飛、agent 還在寫（別碰）」。本次主線程就誤把在飛產物當孤兒去清理 → 與 agent commit race。

### 3. 程式架構（該換的實作）
- 用**單一原子配號源**取代各自 `ls` 猜 max：`storage/ops/k_id_registry.json`（或沿用 next_tasks 配號欄位），配發走檔案鎖（`fcntl.flock` / `O_EXCL` lockfile）的 read-modify-write。
- 加**topic-claim ledger**：`storage/ops/topic_claims.json`，記 `{topic_hash, claimed_by, claimed_at, k_id, status}`；agent 挑題前先原子 claim，撞題者跳過。
- 加 **in-flight 標記**：在飛實驗在 `experiments/kXXX/.inflight`（含 agent pid + start_at + heartbeat），讓主線程/safety-net 能區分 orphan vs 活躍。

## 重構方案

### A. Atomic K-id reservation（`scripts/kid_reserve.py` + `storage/ops/k_id_registry.json`）
- `reserve_kid(topic_hash, claimed_by) -> int`：`flock` 包住 read-`max(registry, ls experiments, ls worktrees/*/experiments, git-log claim, next_tasks)`-`max+1`-`write+fsync`，回傳唯一號。聯集仍掃四源（向後相容，防 registry 漏記）但**配發是原子的**。
- 所有配號入口（主線程、`continue_task_dispatch.py`、cron agent prompt 範本、worktree brief）一律改呼叫 `reserve_kid`，**禁止**任何地方再用 `ls | max+1` 直接配號。

### B. Topic-claim ledger（`storage/ops/topic_claims.json`）
- `claim_topic(topic, claimed_by) -> {ok, existing_k_id?}`：`flock` + normalize(topic) → hash → 若已 claim 回 `ok=False`（附既有 k_id 讓 agent 跳過 / 改挑下一題）；否則寫入並（可選）順帶 `reserve_kid`。
- journal-discovery / backlog 挑題流程：派工前先 `claim_topic`；LanceDB 主題相似度（dist < 0.3 視為同題）併入 claim 判斷，擋「換殼同題」。

### C. In-flight 標記 + orphan 判定
- 實驗開跑寫 `experiments/kXXX/.inflight`（pid/start/heartbeat，每 N 分更新）；完成或 merge 後刪。
- 主線程 / safety-net 清理前先看 `.inflight` + `ps`：活躍 → 不碰；heartbeat 逾時(>30min) → 才當 orphan。

## 廢棄面（重構後移除，不留兩套）
- 移除/改寫所有 `ls experiments/ | ... max+1`、`ls .claude/worktrees/*/experiments/` 手動配號片段（散在 dispatch script、agent brief 範本、`scripts/agent_prompts/*`）→ 全部改呼叫 `reserve_kid`。
- 主線程 autonomous-tick 的「看到未 commit 就清理」行為改為「先驗 in-flight / `ps grep codex`」（已寫進 2026-06-23 error_log 教訓，重構時固化成 helper）。

## 驗證 gate（regression 必覆蓋兩次 incident 觸發條件）
1. **strike 1 重現**：模擬「主線程 + 在飛 worktree 同時 reserve」→ 斷言兩者拿到**不同** K-id。
2. **strike 2 重現**：模擬「3 個並行 caller 同時 `reserve_kid` + `claim_topic` 同一 biodiversity 題」→ 斷言 (a) 3 個不同 K-id 或後兩者被 topic-claim 擋下、(b) knowledge.json 不可能出現 2 個同 K-id 條目。
3. **並發壓力**：`multiprocessing` 開 16 個 worker 各 reserve 100 次 → 斷言 1600 個號全 unique、無 gap-corruption。
4. **provenance 不破**：跑 `scripts/validate_knowledge_provenance.py`（baseline 不因重構而被繞過）。
5. 重構 commit 訊息開頭 `refactor(3-strike): kid-allocation` 便於 grep。

## 開放問題（實作前需定）
- registry 落地點：獨立 `k_id_registry.json` vs 併入 `next_tasks.json` 配號欄位？（傾向獨立檔，單一職責 + 好上鎖）
- topic normalize 規則與 LanceDB dist 門檻（沿用 publishing arc-dedup 的 0.3？）
- cron agent prompt 範本改寫 + worktree brief 範本改寫的同步面（避免改了 script 沒改 prompt）。
