# K1708 split child stage 1/2 — verify-and-freeze（驗證兩個 BLOCKER 修好並凍結程式碼）

**Model**: opus / xhigh (per model_router, experiment lane)
**Parent timeout job**: `agent-brief_k1708_fix-e2b3f0`（5400s budget，逾時 exit 1）
**Split stage**: `verify-and-freeze`
**Worktree（唯一可寫範圍）**: `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-8dda242d-k1708`
**唯一 artifact**: `experiments/k1708/K1708_verify_report.json`

## 為什麼有這個 stage（讀完再動手）

parent job 是「修 K1708 兩個 estimation-consistency BLOCKER」。它逾時了，但**留下了大量有效產出，不要重做**：

- `K1708.py`（91,752 bytes, mtime 06:46）— 已含修正
- `test_k1708.py`（18,968 bytes）— 已含疑似釘住兩個 BLOCKER 的新測試
  （`test_discount_filter_gets_the_full_training_scale`、`test_kf_mle_params_are_optimal_for_the_filter_that_forecasts`）
- `K1708_results.json`（full run, `quick_mode=false`, `generated_at_utc=2026-07-16T22:11:21Z`, `runtime_seconds=1546`）
- `README.md`、`K1708_forecast_ledger.csv`、`K1708_cumulative_loss.png`
- 另有 `*.quick.*` 三個檔（06:49 的 quick-mode 產物）

**但 full-run results 是過期的**（本 stage 存在的唯一理由）：

```
K1708_results.json .code_trace["K1708.py"].sha256 = 1b374a457eb51db2f0ea5f3ff1ff38a23afb37913c4bf0f26328d22cb5a365c0  size=89369
現在磁碟上的 K1708.py                sha256 = 43bffdd4784b1522b68aa2ac5cfecbb5b5d6bcfbe5003dd6df687b49d80f018e  size=91752
```

也就是說：agent 先跑完全樣本（22:11Z），**之後又改了 K1708.py**（+2,383 bytes），只來得及跑 quick mode 就被 timeout 砍掉。
現在那份 full-run 數字不是由現在這份程式碼產生的，`code_trace` 這個 provenance 宣稱**自己對不起來**。
→ 全樣本必須用凍結後的程式碼重跑（那是 stage 2/2 的事，**不要在本 stage 跑全樣本**）。

## 本 stage 的工作（bounded，只做這些）

1. **確認 BLOCKER 1 真的修了** — `HAR_KF_DISC` 的 σ²：δ 選完後必須在**完整訓練集 `[:rp]`** 重估 σ² 再交給 OOS filter；
   而 δ 的選擇本身仍只能用 `< rp` 的資料（原作這點是對的，確認沒被修壞、沒引入 look-ahead）。
2. **確認 BLOCKER 2 真的修了** — `HAR_KF_MLE` 的 estimation 與 production forecast 必須用**同一個** initial state，
   且 README 有寫明擇一的理由。
3. **確認兩個 BLOCKER 各有測試釘住**，且**跑完整測試套件**：`uv run pytest experiments/k1708/test_k1708.py -q`。
   全過才可能 PASS；有 fail 就是 FAIL，照實寫，不要修到過再說（修不修是下一輪的決定）。
4. **獨立審查修正有無引入新的 look-ahead**（這是 BLOCKER 修正最容易踩的坑）。
5. **凍結**：把最終 `K1708.py` / `test_k1708.py` 的 sha256 + size 記進 report。
6. **清掉誤導性殘留**：`K1708_results.quick.json` / `K1708_forecast_ledger.quick.csv` / `K1708_cumulative_loss.quick.png`
   是 quick-mode 產物，不是結果。**刪掉它們**（避免下游把 quick 數字當全樣本），並在 report 的 `removed_files` 記錄。
   `__pycache__/` 也刪。
7. **不要**改數字、**不要**跑全樣本、**不要** merge worktree、**不要**寫 knowledge.json、**不要** git commit。

## 成功判準（artifact 必須長這樣）

寫 `experiments/k1708/K1708_verify_report.json`，UTF-8，schema：

```json
{
  "stage": "verify-and-freeze",
  "parent_job_id": "agent-brief_k1708_fix-e2b3f0",
  "verdict": "PASS | FAIL",
  "blocker1_sigma2_refit_on_full_training": {"fixed": true, "evidence": "K1708.py:<行號> <逐字節錄>", "notes": ""},
  "blocker2_same_initial_state": {"fixed": true, "evidence": "K1708.py:<行號> <逐字節錄>", "notes": ""},
  "new_lookahead_introduced": {"found": false, "evidence": ""},
  "tests": {"command": "uv run pytest experiments/k1708/test_k1708.py -q", "passed": 0, "failed": 0, "raw_tail": "<最後 15 行>"},
  "frozen_code": {"K1708.py": {"sha256": "", "size_bytes": 0}, "test_k1708.py": {"sha256": "", "size_bytes": 0}},
  "stale_fullrun_confirmed": true,
  "removed_files": [],
  "full_rerun_required": true,
  "generated_at_utc": "<ISO8601>"
}
```

`verdict=PASS` 的條件（全中才 PASS）：兩個 BLOCKER 都確認修好 + 無新 look-ahead + 測試全過。
任一不中 → `verdict=FAIL`，並在對應欄位的 `notes` 寫清楚差在哪。**FAIL 是可接受的誠實結果，粉飾不是。**

## 研究誠實度（不可妥協）

parent 的收件審查已認定這份工作誠實度高（零假數字、verdict 由 `derive_verdict` 機械推導、低波動 regime 有
p=0.001 顯著卻沒被撈進 claim）。**本 stage 的價值在於獨立查核，不在於讓它過。** 逐字引用程式碼當證據，
不要憑 README 的自述判定「修好了」—— parent 正是因為自述與實際 artifact 對不起來才需要這個 stage。
