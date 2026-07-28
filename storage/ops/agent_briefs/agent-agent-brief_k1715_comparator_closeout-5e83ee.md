# K1715 — 讓 snapshot 重現宣稱把「消失的 leaf」也涵蓋進去

## 已驗收的部分（不要重做）

`agent-brief_k1715_spec_reprocheck-6ff96b` 已完成，`snapshot_repro_report.md` 的核心結論
主線程認可：從 pinned `K1715_source_snapshot.csv` 離線重跑，**7,483 個共有數值 leaf 的
最大絕對偏差恰為 0.0**（最大相對偏差 0.0），零 verdict 翻轉、零 model-ranking 翻轉。
這遠優於 `reproduce_spec.json` 宣告的 `rtol=1e-6 / atol=1e-8`，snapshot 路徑確實可重現。

## 未涵蓋的缺口（本任務要修的唯一一件事）

報告的標題宣稱是「reproduce **every reported verdict**」，但它比對的是**共有**的 leaf。
報告自己列出 **9,456 archived leaves vs 10,532 new leaves** —— 兩邊並不等長，
卻**從頭到尾沒有交代不共有的那些 leaf 是什麼**。

`compare_to_archived.py` 其實有算（`:156-157`）：

```python
only_old = sorted(set(old_flat) - set(new_flat))
only_new = sorted(set(new_flat) - set(old_flat))
```

而且 summary dict 也有輸出 `only_archived` / `only_new` 計數（`:214-215` 一帶）。
問題有兩層：

1. **報告沒有把這兩個數字寫出來**，讀者無從判斷「every reported verdict」是否真的成立。
2. **exit code 不看它們**：`:265` 是 `return 1 if flipped else 0`。
   也就是說 —— **一個 archived 的 reported finding 如果在新的 run 裡整個消失了，
   comparator 依然 exit 0、依然「通過」**。這對一個以「可重現」為賣點的比較器是失效模式：
   它能抓「數字變了」，抓不到「數字不見了」。

## 工作項

1. 跑出實際數字：`only_archived` 與 `only_new` 各是多少、分別是哪些 JSON pointer。
   若手上沒有 archived baseline（sha256 `929cb150a4e2ff33883a8e5cbe47de545177f02ee5175387c73b40fb87a4f786`），
   先從 git 歷史或既有 artifact 取回；取不到就照實回報 BLOCKED，不要用近似檔充數。
2. **分類每一個 `only_archived` pointer**：屬於 (a) 已知的 ignore 集合（`/created_at`、
   `/runtime_seconds`、`/run_utc`、`/runtime_env`、`/code_trace`）、(b) 本次修正刻意移除的
   欄位、還是 (c) **一個真的消失了的 reported finding**。
   **只要有任何一個落在 (c)，立刻停手回報，不要自行決定它不重要。**
3. `only_new` 同樣分類（多半是修正新增的欄位，但要指名道姓，不要一句「新增欄位」帶過）。
4. **讓 comparator fail-closed**：修改 `compare_to_archived.py`，使「archived 有、new 沒有」
   的 **science pointer**（沿用檔內既有的 `science()` 判定，不要自創新規則）造成非零 exit。
   純 documentation / metadata pointer 可豁免，但豁免清單要明列在程式碼裡而非隱含。
5. 補一條 negative test：人為從 new 文件刪掉一個 science leaf → comparator 必須紅。
6. 把 1–3 的實際數字與分類結果補進 `snapshot_repro_report.md`，讓
   「every reported verdict」這句話有對應證據；若分類結果顯示該宣稱過強，**改寫這句話**，
   不要保留原措辭。

## Worktree

`/Users/yhlai0911/volpred-research/.claude/worktrees/k1715-204d556b`

## 產出契約

寫 `experiments/K1715/comparator_closeout_report.json`：

- `only_archived_count` / `only_new_count`
- `only_archived_classified`：每個 pointer 及其分類 (a)/(b)/(c) 與理由
- `only_new_classified`：同上
- `category_c_found`：true/false —— 若 true，列出並把 `status` 設為 `BLOCKED`
- `comparator_change`：fail-closed 的實作方式與豁免清單
- `negative_test`：測試名稱與「刪一個 science leaf 會紅」的實測結果
- `report_wording`：`snapshot_repro_report.md` 標題宣稱改了什麼（或為何不需要改）
- `status`：`CLOSED` 或 `BLOCKED`

完成後 commit worktree。

## 禁止

為了讓 exit 0 而把 science pointer 塞進豁免清單；用「應該不重要」帶過任何 (c) 類 pointer；
merge（主線程的事）；寫 `knowledge.json`（K1259）；force-remove worktree。

**Model**: opus / xhigh (per model_router, experiment)
