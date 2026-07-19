# Task: K1708 修正 stage — verdict gate 假陽性 + CW nesting/gate 三個 BLOCKER（k1708_fix_verdict_gate_20260717, P2, experiment）

**Model**: opus / xhigh (per model_router)
**Worktree (你唯一可寫的地方)**: `.claude/worktrees/dispatch-slot-2-8dda242d-k1708`（**禁 force-remove**）
**必讀**: `storage/ops/k1708_codex_review_20260717.md`（Codex primary review 全文，判 FAIL）

## 已確認為真、不要動的部分

- 兩個原始 BLOCKER 真的修好了
- CW 公式正確
- NULL 結論由現行數字機械重算得出
- provenance 三項對上凍結程式碼

**硬性禁止**：不要重跑全樣本、不要 merge worktree、**不要為了過 gate 動數字**。

## 三個 BLOCKER，分兩類

### (A) 機械 bug — 可直接修

`K1708.py:1941-1968` `derive_verdict` **沒實作它自己宣告的跨市場條件**：
- 只讀 TAIFEX 的 QLIKE / CW；第二個市場只要 `status=='OK'` 就算 qualified，**不需要任何改善**
- Codex 用最小 payload（SPY=OK 但無 metrics、只有 TAIFEX 過）實測回傳 `SUPPORTED` = **假陽性路徑**
- 亦未檢查 `README.md:246-251` 宣告的 GW / MCS / regime consistency

修法：
1. qualified 條件要**真的**要求該市場有 admissible metrics 且達成宣告的改善
2. 補上「宣告了卻沒實作」的檢查（GW / MCS / regime consistency）
3. 加**非空洞** regression test：用 Codex 那個最小 payload 當種子，該測試在舊邏輯下必須 FAIL

**驗證錨點**：本 run 的 NULL 不受影響（SPY/QQQ 為 `FAIL_NO_DATA`）→ 修完**應仍為 NULL**。**若 label 變了就是修錯**，回頭查。

### (B) 推論設計 — 需研究判斷後才動 code

1. `K1708.py:1394-1405`：CW 被套用在「被評分的 level forecast 上並非精確 nested」的比較。
   HAR_FIXED 每日重估 β/σ²；KF/HARSL 每 252 日 refit 且 σ² 不同，差異經 `exp(mu+var/2)` 進入預測。
   `README.md:280-306` 自己承認 δ=1 ≠ HAR_FIXED。
   → **先決定「哪個比較才真的 nested」**，再改 code。
2. `K1708.py:1952-1960`：把事前的 DM-HLN `|t|>=3` 換成「三模型任一 CW 單尾 5%」，且**無 multiple-testing correction**。
   方向一致時明顯較寬 = **verdict-shopping 風險**。揭露誠實 ≠ 讓較寬的 gate 等價。
   → **先決定「哪個 gate 治理 verdict」**，再改 code + README。

**不可反向配合現有數字。** 方法論決定要有明確理由（引文獻或推導），寫進 README。

## 完成條件

- (A) 修好 + 非空洞 test + 全套 test 綠（`uv run pytest -q`，或相關子集 + 說明）
- (B) 有明確方法論決定，寫進 `README.md`
- 產出 `experiments/k1708/k1708_fix_verdict_gate_results.json`：
```json
{"task_id":"k1708_fix_verdict_gate_20260717",
 "A_fixed":{"changes":["..."],"regression_test":"<path>::<test>","fails_on_old_logic":true},
 "A_verdict_label_after_fix":"NULL",
 "B_nesting_decision":{"decision":"...","rationale":"...","code_changed":["..."],"readme_updated":true},
 "B_gate_decision":{"decision":"...","multiple_testing":"...","rationale":"..."},
 "pytest":"pass|fail+說明","honest_notes":"..."}
```

## 收尾

- worktree 內 commit（訊息 what|why）。**不要 merge**、**不要 force-remove worktree** —— 後續 fire 的 PHASE A 會派 Codex re-review → merge → 寫 knowledge（NULL 據實記錄）。
- **不要寫 `storage/knowledge.json`**（K1259）。
