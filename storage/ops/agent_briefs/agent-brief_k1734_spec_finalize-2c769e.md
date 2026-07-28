# K1734 收尾：run-time reproduce_spec 補齊 + BH-FDR p 值口徑落檔

**Model**: opus / xhigh (per model_router, task_type=experiment)
**Pool task**: `assign_04212462`（parent triage `assign_17d6da38`）
**Worktree（唯一可寫範圍）**: `.claude/worktrees/dispatch-slot-1-1e5922b4-k1734`，只碰 `experiments/k1734/`

## 背景（已由主線程實測確認，勿重新推測）

K1734（EM carry-unwind crash-risk asymmetry）已完成並取得 `review_verdict.json`：
`consolidated_verdict = CONDITIONAL_PASS`，兩個獨立 review 都是 PASS，無 blocking issue。
**成果要保留，不是失敗重跑**。目前卡兩件事，本任務只處理第 1 件：

1. **（本任務）`experiments/k1734/reproduce_spec.json` 不存在** → canonical main 的
   `scripts/check_experiment_artifacts.py` 會擋下 `merge_worktree.sh`。
   已 grep 確認 `k1734.py` 內**完全沒有** `finalize_experiment` / `reproduce_spec` / `trace_file`
   的呼叫 —— spec 從來沒被產生過。
2. **（不是本任務，別動）** primary-path reviewer = Codex，撞 usage limit 到 2026-08-02，
   合併裁決另有 gate 任務。**本任務結束時不得 merge、不得寫 knowledge.json。**

## 為什麼不能手寫 spec

`AGENTS.md`「spec 要在 run-time 產生，不是事後補（2026-07-22 起，K1708 教訓）」：
K1708 的 spec 是人事後補的，記的 sha／byte size 與真正跑出結果的程式不符。
所以 spec 必須由 `volpred.research.reproduce_spec.finalize_experiment()` 在**同一次執行**中
與 results 一起寫出，`results["code_trace"]` 與 `spec["entrypoint"]` 取自同一次 trace snapshot。

## 工作項

### 1. 讀 canonical helper 再動手
先讀 `src/volpred/research/reproduce_spec.py` 的 `finalize_experiment` 簽章與既有呼叫範例
（可 grep 其他 `experiments/*/` 的用法），照它實際的參數寫，不要照本 brief 的示意硬套。

### 2. 修 `k1734.py` 收尾
把 `main()` 末端目前的 `RESULTS_PATH.write_text(json.dumps(...))` 改成經 `finalize_experiment()`
寫出，帶：`entrypoint=__file__`、`canonical_result="K1734_results.json"`、
`inputs=[data/analysis_panel.csv 與 data/raw/*.csv 的實際路徑]`、`seeds=[("numpy", 42)]`、
`started_at=` 執行起始時間戳。

**只准動收尾寫檔那一段與必要 import。**任何會改到數值的計算、口徑、統計檢定一律不准碰 ——
這份程式已經過兩個獨立 reviewer 逐行審過。

### 3. 重跑並驗證數值不變（硬性驗收）
- `data/raw/*.csv` 與 `data/analysis_panel.csv` 已快取，`_download()` 有 `path.exists()` 短路，
  **離線可重現**；seed=42、`BOOT_REPS=5000` 固定。
- 重跑前先把現有 `K1734_results.json` 複製到 `/tmp/K1734_results_prereview.json` 當基準。
- 重跑後**程式化 diff**：除 `code_trace`、時間戳、spec 相關欄位外，所有數值必須逐欄相同。
  重點 assert：`bh_fdr`（含 `conservative_two_sided_cw`）、`H1/H2/H3` 全部統計量與 p、
  `verdicts.*`、`oos_primary.clark_west_mse.p_value_one_sided`。
- **若有任何數值改變 → 停止，不要硬推**：把 diff 寫進 `experiments/k1734/rerun_diff_report.md`
  並在最終回覆說明；數值漂移代表這份 results 不可重現，那是比缺 spec 更嚴重的問題，
  必須讓主線程知道，不准自行「重新解釋」或改口徑掩蓋。

### 4. README 補 p 值口徑（verdict 的非阻斷保留項）
`README.md` 內明確寫清楚：H3 的 OOS 主檢定 Clark–West 用 **one-sided** p，
與其他 **two-sided** p 一起放進同一個 BH–FDR family；並註明保守處理
（CW p 加倍後 H3 仍存活，adjusted p = 0.0401 < 0.05，見
`K1734_results.json.bh_fdr.conservative_two_sided_cw`）。
**不要改結論強度**，只是把口徑講明白，不讓混用留在紀錄裡。

### 5. 自查 + commit
- 跑 `python3 scripts/check_experiment_artifacts.py check --path experiments/k1734`
  （knowledge 半邊由主線程負責，spec 半邊必須過）。
- worktree 內 commit（`git add experiments/k1734` 後 commit，訊息寫清楚改了什麼、為什麼）。
  目前 worktree 有 4 個 dirty 檔（results / README / k1734.py / review_verdict.json）
  —— 那是上一輪已完成但沒 commit 的成果，**一併 commit，不要丟棄、不要 revert**。
- **禁止**：`git push`、`merge_worktree.sh`、改 worktree 外任何檔、寫 `storage/memory/knowledge.json`
  （K1259：knowledge 只能主線程寫）、`--no-verify`、`git worktree remove --force`。

## 成功判準（缺一不可）
1. `experiments/k1734/reproduce_spec.json` 存在，且由本次執行的 `finalize_experiment()` 產出。
2. `K1734_results.json` 的 `code_trace` 與 spec 的 entrypoint sha／byte size 一致（同一次 trace）。
3. 重跑數值與受審版本逐欄相同（或 diff report 已如實產出並在回覆中說明）。
4. README 已寫入 p 值口徑段落。
5. `check_experiment_artifacts.py` 的 spec 半邊通過。
6. worktree 已 commit，未 merge、未 push。

## 回覆格式
最後回覆是機器要收的資料，不是給人看的信。請回：
`spec_written`(bool) / `numbers_identical`(bool) / `diff_summary`(str，若有) /
`readme_caliber_added`(bool) / `artifact_check_pass`(bool) / `commit_sha`(str) /
`blocking_issues`(list)。
