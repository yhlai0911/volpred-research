# K1708 — Codex round-3 primary-path review + 認證 + 合併

**Model**: opus / xhigh (per model_router, task_type=experiment)

**Task id**: `K1708`（主線程已 claim + start）

## 你的工作目錄

`/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-457427c2-k1708`
（registered linked worktree，branch `wt/dispatch-slot-2-8dda242d-k1708`，3 個已 commit、未合併的 commit，dirty=0）

實驗在該 worktree 的 `experiments/K1708/`。

## 這張任務**不是**跑新實驗

K1708 的實驗與 round-2 BLOCKER remediation **已經做完**（`experiments/K1708/REMEDIATION_rev2.md`，
pytest 54 passed，`experiment_gates.py` PASS）。**不要重跑 full sample，不要重寫實驗。**

卡點只有一個：`merge_worktree.sh` 的認證閘門要求
`experiments/K1708/review_verdict.json`（PASS 裁決 + pin 住 claim surface 的 sha256），
而該檔不存在，所以合併被 ABORT。

## 前一班留下的**錯誤前提**（本班已推翻，你要以此為準）

`REMEDIATION_rev2.md` 寫著「Codex 額度實測耗盡（重置 2026-07-25 13:30 台北），本輪未執行二審」。
**這個宣稱在 2026-07-22 08:2x 已被實測推翻** —— `bash scripts/codex_exec_bounded.sh --timeout 100 "reply with exactly: QUOTA_OK"`
回傳 `QUOTA_OK`、exit 0。**Codex primary path 現在可用。**

順帶：請在 `REMEDIATION_rev2.md` 更正這段（標明原宣稱、推翻時間與證據），
不要讓一個已知錯誤的前提繼續躺在文件裡誤導後續班次。

## 要做什麼

### 1. 讀懂現況（先讀再動）
- `experiments/K1708/REMEDIATION_rev2.md` —— 前一輪對 4 個 BLOCKER 各做了什麼、**還剩什麼沒解決**
- `storage/ops/k1708_codex_review_round2_20260719.md` —— round-2 的 FAIL 裁決與 4 BLOCKERs
- `storage/ops/k1708_codex_review_20260717.md` —— round-1
- `experiments/K1708/README.md`、`K1708.py`、`test_k1708.py`

**特別注意 remediation 自己承認的缺口**：BLOCKER 1 的「修正後 gate 不會把 stored NULL 推成非 NULL」
既無法論證（comparator 移動不可排序）也無法用 stored artifact 補（own-restriction 統計量從未保存）。
前一輪誠實地沒把它寫成已解決。**你的 review 必須正面裁決這個缺口是否 acceptable**，
不要迴避，也不要因為它誠實就自動放行。

### 2. 跑 Codex round-3 primary-path review

**必須用有界 wrapper**（裸跑 codex exec 會被 hook 攔截）：
```
bash scripts/codex_exec_bounded.sh --timeout 1500 "<review prompt>"
```
逾時 exit 124 → 拆小 scope 分段審（例如先審 gate/verdict 邏輯，再審 lookahead/測試），不要無界重試。

Review prompt 至少要求 Codex：
- 逐一裁決 round-2 的 4 個 BLOCKER 是否真的關掉（引 path:line 為證）
- 獨立檢查 lookahead：`signal.shift(1)`、每個 origin 的 filtering 只看窗內資料、
  超參數由內層滾動驗證決定（不得用到窗外）
- 檢查 `derive_verdict` / `legacy_derive_verdict` / `gate_transition_audit` 是否還有盲信 payload label 的路徑
- 給出明確 VERDICT：PASS / CONDITIONAL_PASS / FAIL + 理由

把 Codex 原始輸出**完整**存成 `storage/ops/k1708_codex_review_round3_20260722.md`（不要摘要後才存）。

### 3. 依裁決分流

**若 PASS 或 CONDITIONAL_PASS**：
- 寫 `experiments/K1708/review_verdict.json`，schema 依 `merge_worktree.sh` 認證閘門要求：
  `verdict` / `reviewed_at` (ISO8601) / `review_artifact`（指向 round3 md）/
  `reviewed_sha256`：claim surface（`*.py`、`README.md`、`*_results.json`、reader-facing 圖）
  **每個檔案都要列出審查當下的 sha256**
- ⚠️ 順序：**先凍結 bytes，再算 sha256，之後不得再改任何 claim surface 檔案**。
  改了就要重審 —— **絕對不准手改裁決檔讓 hash 對上**（這正是閘門存在的理由，K1709 事故）。
- 然後合併：
  ```
  cd /Users/yhlai0911/volpred-research
  uv run python scripts/git_writer_lock.py run --actor "<你收到的 owner token>" -- \
    bash scripts/merge_worktree.sh dispatch-slot-1-457427c2-k1708
  ```

**若 FAIL**：
- **不要**寫 review_verdict.json，**不要**合併（閘門會擋，也應該擋）
- 把 BLOCKERs 整理清楚，說明這是 round 3 連續第 3 次 FAIL → 依 3-strike，
  建議是否要開 `docs/refactor_plan_k1708_*.md` 或改變作法，而不是第 4 次同法重試

## 硬性禁令

- 禁止 `--no-verify`、跳過 gate、`--force` 移除 worktree
- 禁止寫 `knowledge.json`（K1259 教訓 —— 那是主線程的事）
- 禁止假造數字、假造測試通過、把 runner lifecycle receipt 當研究結果
- 禁止手改 `review_verdict.json` 讓 sha256 對上
- 研究誠實 > 一切。**FAIL 是完全合格的產出**，不要為了讓任務看起來完成而放水。

## 交付物（你的最終文字就是回傳值，不是給人看的訊息）

- `verdict`: MERGED / FAIL_NOT_MERGED / BLOCKED（附原因）
- Codex round-3 的 VERDICT 與 4 個 BLOCKER 的逐條裁決摘要
- BLOCKER 1 那個已知缺口，Codex 怎麼裁的
- `review_verdict.json` 是否寫出（是→貼 sha256 清單；否→說明）
- 合併是否成功（貼 merge_worktree.sh 真實輸出末 10 行）
- `REMEDIATION_rev2.md` 的 Codex 額度錯誤宣稱是否已更正
- 未解決事項 / 建議下一步
