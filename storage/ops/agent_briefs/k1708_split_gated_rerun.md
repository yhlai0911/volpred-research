# K1708 split child stage 2/2 — gated-full-rerun（用凍結後的程式碼重跑全樣本）

**Model**: opus / high (per model_router, experiment lane；本 stage 主要是等 compute + 對帳，非設計)
**Parent timeout job**: `agent-brief_k1708_fix-e2b3f0`（5400s budget，逾時 exit 1）
**Split stage**: `gated-full-rerun`
**前一 stage**: `verify-and-freeze`（同 parent，先跑；compute worker 單線程 FIFO，本 job 起跑時它已結束）
**Worktree（唯一可寫範圍）**: `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-8dda242d-k1708`
**唯一 artifact**: `experiments/k1708/K1708_rerun_report.json`

## GATE — 第一件事，不通過就直接收工

讀 `experiments/k1708/K1708_verify_report.json`：

- **檔案不存在**，或 `verdict != "PASS"`，或 `frozen_code.K1708.py.sha256` 與現在磁碟上的 `K1708.py` 不符
  → **不要跑全樣本**。寫 `K1708_rerun_report.json` 為
  `{"stage":"gated-full-rerun","parent_job_id":"agent-brief_k1708_fix-e2b3f0","status":"SKIPPED_GATE","reason":"<逐字說明哪一項不過>","generated_at_utc":"<ISO8601>"}`
  然後結束。**這是正確結果，不是失敗** —— 用沒驗過的程式碼跑 26 分鐘只會生出另一份不可信的數字。
- 全部通過 → 往下走。

## 為什麼要重跑（讀完再動手）

parent job 已修好兩個 estimation-consistency BLOCKER，但它是**先跑完全樣本、之後又改了 `K1708.py`**，
只來得及跑 quick mode 就被 timeout 砍掉。所以現存的 `K1708_results.json` 相對於最終程式碼是過期的：

```
results.code_trace["K1708.py"].sha256 = 1b374a45…  size=89369   ← 產生這份數字的程式碼
現在磁碟上的 K1708.py                 = 43bffdd4…  size=91752   ← 修正後的程式碼
```

`code_trace` 是這個實驗的 provenance 宣稱，它現在**對不起自己**。修正動到 σ² 重估與 initial state ——
這兩者直接進 Kalman gain、predictive variance 與 Jensen 修正，數字**必然會變**。而原本 `HAR_KF_DISC` 的
QLIKE 優勢只有 0.160492 vs 0.161432（極薄），完全可能翻轉。**所以這不是形式主義的重跑，結論可能改變。**

## 本 stage 的工作（bounded，只做這些）

1. 跑全樣本（**不加 `--quick`**）：`cd experiments/k1708 && uv run python K1708.py`（上次 `runtime_seconds=1546`，約 26 分鐘）。
2. 跑完驗 artifact 自洽：
   - `K1708_results.json` 的 `quick_mode == false`
   - `generated_at_utc` 晚於本 job 起跑時間（不是舊檔佔位）
   - `code_trace["K1708.py"].sha256` **逐字等於** verify report 的 `frozen_code.K1708.py.sha256`
   （這三條就是上一輪失守的地方，逐條核，不要目測）
3. **對帳新舊 verdict**：舊 = `NULL`（`state_space_beating_fixed_har: []`，`HAR_KF_DISC/HAR_KF_MLE/HAR_S_BM` 在 MCS superior set）。
   逐項記錄修正前後的 QLIKE / MCS / Clark-West 有沒有變、verdict 有沒有翻。
4. **README 數字同步**：README 內引用的數字若與新 JSON 不符，改成新 JSON 的**逐字**數字。
   低波動 regime `HAR_S_BM` 的 p 值若仍顯著，照實揭露、不撈進 claim（原作的處理是對的，維持）。
5. **不要** merge worktree、**不要**寫 `knowledge.json`、**不要** git commit、**不要**改判 verdict 邏輯
   （verdict 必須由 `derive_verdict` 機械推導；不要為了好看動它）。

## 成功判準（artifact 必須長這樣）

寫 `experiments/k1708/K1708_rerun_report.json`：

```json
{
  "stage": "gated-full-rerun",
  "parent_job_id": "agent-brief_k1708_fix-e2b3f0",
  "status": "COMPLETED | SKIPPED_GATE | FAILED",
  "run": {"command": "uv run python K1708.py", "runtime_seconds": 0, "exit_code": 0},
  "artifact_selfcheck": {"quick_mode_false": true, "generated_at_utc": "", "code_trace_matches_frozen_sha256": true},
  "verdict_before": "NULL",
  "verdict_after": "",
  "verdict_flipped": false,
  "key_metrics_delta": [{"model": "HAR_KF_DISC", "metric": "QLIKE", "before": 0.160492, "after": 0.0, "benchmark_HAR_FIXED": 0.161432}],
  "readme_numbers_synced": true,
  "readme_edits": ["<逐字：哪個數字從 X 改成 Y>"],
  "generated_at_utc": "<ISO8601>"
}
```

`status=COMPLETED` 的條件：全樣本跑完 exit 0 + 三條 self-check 全過 + README 已同步。
跑失敗 → `status=FAILED` + 逐字 traceback 摘要。

## 研究誠實度（不可妥協）

**verdict 翻成 SUPPORTED 或維持 NULL 都是可接受的結果；假數字不是。** 修正後若仍 NULL，就據實記 NULL ——
parent 的原作者換 Clark-West 時方向對自己不利仍照實交 NULL，這個標準要守住。
禁止硬編數字、禁止把 quick-mode 數字當全樣本、禁止「大致相符」了事（逐字比對）。
