# K1708 gate-cert 收尾 — §14 real-data rerun（bounded, 3-strike ceiling attempt）

**Model**: opus / max (per model_router.py --task-type experiment --attempt 4; at_ceiling=true, exhausted=true — 這是最後一次嘗試，FAIL 即 escalate 老闆)

## Worktree (禁止在別處寫)
`.claude/worktrees/dispatch-slot-1-457427c2-k1708`（此即你的 cwd）。既有檔案：`K1708.py`、`README.md`、`REMEDIATION_rev2.md`、`K1708_results.json`、`k1708_fix_verdict_gate_results.json`。**只改動 experiments/k1708/ 下的檔案**，不碰 feed.json / next_tasks.json / knowledge.json（knowledge 由主線程在 PASS 後寫）。

## 背景（不可動搖的結論）
K1708 = time-varying state-space HAR vs fixed/rolling HAR。研究結論 = **NULL**（state-space 未勝 HAR）。此結論**不在爭議、不得翻案**。Codex round-1/2/3 全 FAIL，round-3 觸發 3-STRIKE。所有 blocker 都是 **gate 機制可證性**問題，非研究結論問題。

round-3 誠實結論：rev2 的 gate 修正在「門檻/併行條件收緊、comparator」上橫移，但**新口徑 gate 從未在真實資料上被評估**。要拿到新口徑數字，唯一辦法是重跑 §14（前幾輪明列不重跑，這是唯一未做的具體步驟）。

## 你的 bounded scope（只做這些，不擴張）
1. **§14 full-sample rerun**：在既有 `K1708.py` 上跑 §14 full-sample，產生新口徑欄位並寫入 `K1708_results.json`：
   - `cw_vs_own_restriction_primary`（Clark-West vs own-restriction，primary comparator）
   - `cw_holm_family`（Holm family-wise 校正後的 CW）
   - `regime qlike_vs_own_restriction`（regime-conditional QLIKE vs own-restriction）
   - **預期仍 NULL**：t 值無理由變大、門檻由 1.645 → 3.0 更嚴。**若結果非 NULL，視為異常訊號**，不得當利多，要在 summary 裡標記並追查（可能是 lookahead 洩漏或 gate bug），寧可回報異常也不得產出假陽性。
2. **gate + 完整 test 重跑**：用新資料跑 `experiment_gates` + 完整 test suite（**必含 `legacy_derive_verdict` 對照**），逐一確認 round-3 的 4 個 blocker 都 CLOSED。把每個 blocker 的 before/after 狀態寫進 summary。
3. **產出 summary artifact**：寫 `experiments/k1708/K1708_stage2_summary.json`（這是 triage 標記缺失的檔），內容至少含：
   - `study_conclusion`: "NULL — state-space did not beat HAR"（不變）
   - `new_caliber_fields`: 上述三個欄位的實際數值 + 各自門檻 + pass/fail
   - `blockers`: 4 個 blocker 的 id + closed(true/false) + evidence（指向 test 名 / results.json 欄位）
   - `verdict_self`: 你自評 4 blocker 是否全 CLOSED（true/false）+ 一句理由
   - `anomaly_flag`: 若步驟 1 出現非 NULL 的異常，設 true 並說明

## Lookahead / 誠信硬規則
- 任何 signal 必 `signal.shift(1)`，seed=42。禁 lookahead。
- **禁止製造假數字或為了讓 gate 通過而放寬門檻**。研究誠實 > gate 通過。gate 若因真實數字關不掉，如實回報 blocker 仍 OPEN，不得粉飾。
- 不寫 knowledge.json（K1259：agent 禁寫 knowledge）。

## 交付物（success criterion）
`experiments/k1708/K1708_stage2_summary.json` 存在且含上述欄位，且 `K1708_results.json` 已含三個新口徑欄位。runner 只驗此檔存在。

## 不做的事
- 不重新論證研究結論（NULL 已定）。
- 不改 gate 門檻去硬湊 PASS。
- 不 merge worktree（由後續 Codex round-4 PASS 後主線程處理）。
