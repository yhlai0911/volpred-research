# K1715 收尾：run-time reproduce_spec + 實測 snapshot 路徑可重現，才送 recert

**Model**: opus / xhigh (per model_router, task_type=experiment)
**Pool task**: `assign_8f1165f3`（parent triage `assign_c3b0743a`）
**Worktree（唯一可寫範圍）**: `.claude/worktrees/k1715-204d556b`，只碰 `experiments/K1715/`

## 先講最重要的一件事

`experiments/K1715/review_verdict.json`（2,108 B，mtime 07-27 07:40）自述
`reviewed_at=2026-07-26T23:39:43Z`、`reviewed_commit=70923136…`、`verdict=FAIL`。
**那是修正前的舊裁決**，描述的不是現在磁碟上的位元組。
`K1715_results.json` 是 07-27 20:46、`K1715.py` 是 07-27 21:27，都比它晚。
**絕不可把它當成 recert 結果，也不可把它當成「已失敗」而丟棄成果。**
上一個 recert2 job（`agent-brief_k1715_recert2-e2b9fd`）exit_code=-2 被 SIGKILL，
所以新位元組**從未被審過**。

## 主線程已實測確認的現況（不要重新臆測，直接接手）

1. **lossy serialization 的處置方式是「揭露 + 契約」，不是 bit-identical 重凍結。**
   - `K1715.py:119` 的 writer 已改成 `float_format="%.17g"`（無損），
     **但那條路徑只在 snapshot 不存在時才會走**（`if SNAPSHOT.is_file()` 短路）。
   - 磁碟上的 `K1715_source_snapshot.csv`（mtime 07-27 07:13）仍是舊的 `%.10f` 十位小數版
     （已確認：`2000-01-03,91.1327362061`）。
   - `load_returns()` docstring 與 `reproduce_spec.json.comparison.reason` 都已明寫這是
     **TOLERANCE-LEVEL freeze**，量化 `max|delta_close| ~5.0e-11`、`max|delta_return| ~1.6e-10`，
     遠小於宣告的 `rtol=1e-6 / atol=1e-8`。
   - 這個口徑本身可接受（如實揭露、不過度宣稱），**但有一個未被驗證的缺口**：
     docstring 自述 archived `K1715_results.json` 是從 **live download** 產生的，
     而任何人重現時走的是 **snapshot** 路徑 —— 這條路徑**從來沒有真的被跑起來驗證過**
     能在宣告 tolerance 內重現 archived 結論。本任務要把它跑出來。
2. **`reproduce_spec.json` 不是 run-time 產出**：mtime 07-27 08:04，早於 results（20:46）
   與 K1715.py（21:27）；`grep -c finalize_experiment K1715.py` = **0**；
   spec 的 `entrypoint` 只有 path、**沒有 sha／byte size**，連漂移都無從檢查。
   這與 `AGENTS.md`「spec 要在 run-time 產生（2026-07-22，K1708 教訓）」直接衝突。

## 工作項

### 1. 修 `K1715.py` 收尾走 canonical helper
先讀 `src/volpred/research/reproduce_spec.py` 的 `finalize_experiment` 實際簽章與其他
`experiments/*/` 既有用法，再改。收尾以 `finalize_experiment()` 寫出 results + spec，帶
`entrypoint=__file__`、`canonical_result="K1715_results.json"`、
`inputs=[experiments/K1715/K1715_source_snapshot.csv]`、`seeds=[("numpy", 42)]`、`started_at=`。

**保留現有 `comparison` 的 rtol=1e-6 / atol=1e-8 與那段 reason 文字**（近積分似然 ridge +
BLAS/LAPACK 平台敏感性的理由是正當的，而且是既有審查認可過的口徑）——
只是要讓它由 run-time 產出、並補上 entrypoint 的 sha／byte size。
**不准動任何模型、估計、評估、seed、lag 邏輯。**

### 2. 實測 snapshot 路徑能重現 archived 結論（本任務的核心驗證）
- 先備份 `K1715_results.json` 到 `/tmp/K1715_results_archived.json` 當基準。
- 在 **network=deny 的前提下**（snapshot 存在 → 不會觸發 yfinance）重跑 `K1715.py`。
- 程式化比對新舊 results，**用 spec 宣告的 `rtol=1e-6 / atol=1e-8`**，逐一確認所有
  **reported verdict 不變**：DM 統計量、Harvey |t| 門檻判定、VaR/ES coverage counts、
  PIT 檢定結論、各模型排序。
- 產出 `experiments/K1715/snapshot_repro_report.md`：記錄比對方法、最大相對／絕對偏差、
  哪些欄位在 tolerance 內、**有沒有任何一個 verdict 翻轉**。
- **若有任何 verdict 翻轉 → 立刻停手**，如實寫進 report 並在最終回覆標 `blocking_issues`。
  那代表 tolerance-level freeze 的契約不成立，是比缺 spec 嚴重得多的問題，
  必須讓主線程知道；**不准放寬 tolerance、不准改口徑、不准重新解釋來讓它通過**。

### 3. 舊 verdict 歸位
把 `review_verdict.json` 改名或移到 `review_verdict_20260726_stale.json`（保留、不刪），
並在檔內或 README 註明它對應的是 `reviewed_commit=70923136…`、已被 07-27 的修正取代。
**不要**在本任務內自行產生新的 review_verdict —— recert 是下一段、要由獨立 reviewer 做。

### 4. 自查 + commit
- `python3 scripts/check_experiment_artifacts.py check --path experiments/K1715`（spec 半邊須過）。
- worktree 內 commit，訊息寫清楚改了什麼、為什麼。worktree 目前有 dirty 檔，一併 commit，
  **不要丟棄、不要 revert**。
- **禁止**：`git push`、`merge_worktree.sh`、`git worktree remove --force`、`--no-verify`、
  改 worktree 外任何檔、寫 `storage/memory/knowledge.json`（K1259）。

## 成功判準（缺一不可）
1. `reproduce_spec.json` 由本次 `finalize_experiment()` run-time 產出，entrypoint 帶 sha／byte size，
   且與 `K1715_results.json` 的 `code_trace` 來自同一次 trace。
2. `snapshot_repro_report.md` 存在，明確回答「snapshot 路徑能否在 rtol=1e-6/atol=1e-8 內
   重現 archived 的每一個 reported verdict」。
3. 舊 `review_verdict.json` 已標記為 stale 且未被當成有效裁決。
4. `check_experiment_artifacts.py` spec 半邊通過。
5. worktree 已 commit，未 merge、未 push。

## 回覆格式
最後回覆是機器要收的資料。請回：
`spec_runtime_generated`(bool) / `verdicts_reproduced`(bool) /
`max_rel_dev`(float) / `flipped_verdicts`(list) / `stale_verdict_renamed`(bool) /
`artifact_check_pass`(bool) / `commit_sha`(str) / `blocking_issues`(list)。
