# K1734 — nested-DM-misuse gate remediation（續跑既有 worktree）

**Model**: claude-opus-5 / xhigh (per model_router)
**Task**: K1734 (experiment lane, worktree topology) — REMEDIATION, attempt 2
**Worktree（就地續跑，勿新建）**: `.claude/worktrees/dispatch-slot-1-1e5922b4-k1734`
**既有產物**: `experiments/k1734/{k1734.py, K1734_results.json, README.md, review_verdict.json, figures/, data/}` — 實驗已完整跑完、兩份獨立 review 皆 PASS（CONDITIONAL_PASS）。**不要重做整個實驗、不要換題**。

## 唯一 blocker（compute-queue experiment-gate exit 4）
```
[nested-dm-misuse] experiments/k1734/k1734.py  (primary_raw_dm)
→ Raw DM/HLN is not valid inference under a nested-model null. Use Clark-West (2007)
  for squared-error, or a general-loss / recursive-bootstrap design for QLIKE/pinball,
  and wire THAT into the verdict.
```
Enforcement owner: `scripts/tests/test_nested_dm_misuse_ratchet.py` + `scripts/audit_nested_dm_misuse.py`。

## 已定位的根因（先驗證再動手）
- H3 的**主推論已經是 Clark-West**：`clark_west_mse` 的 `p_value_one_sided < 0.05` 才是 verdict `oos_lead_present` 的依據（k1734.py ~L680-682, L705, BH-FDR L889）。這一條**正確、不要改動其統計意義**。
- 被 ratchet 判為 `primary_raw_dm` 的是 **`dm_qlike = _dm_test(q_r, q_u, HAC_LAG)`（k1734.py ~L634）** —— 對 QLIKE loss 直接跑 raw Diebold-Mariano/HLN，而 HAR vs HAR+carry 是**巢狀**模型。即便此處只是用來說「QLIKE 差異不顯著」(diagnostic/robustness，見 L701-702 `dm_qlike_insignificant`)，auditor 刻意 lexically broad、不採信作者自貼的 marker，因此照樣 flag。

## 你的任務（二選一，擇 methodologically 最誠實者；先讀 auditor 再決定）
**必讀**：`scripts/audit_nested_dm_misuse.py`（scan_file / test_role 分類邏輯）與 `scripts/tests/test_nested_dm_misuse_ratchet.py`（baseline / reviewed_nonnested 機制、docstring 明言「false positives are retired one at a time, by a recorded adjudication with a reason, never by a marker an author can apply to their own file」）。

- **路徑 A（優先，statistically 最乾淨）**：把巢狀 QLIKE 比較從 raw DM 換成**合法的巢狀/general-loss 推論** —— recursive/rolling out-of-sample 的 block-bootstrap（circular block, `seed=42`）對 QLIKE loss 差做檢定，或採 Clark-West 精神的 general-loss 版本。把該結果**接進 verdict / results.json**（取代 `dm_qlike` 在 claim/robustness sink 的角色），raw DM 若保留只能是純描述且不得進任何 claim/verdict 欄位。重新跑實驗（`seed=42`，確認無 lookahead：signal t-1 / target t，`.shift(1)`）→ 更新 `K1734_results.json` + `README.md` + `review_verdict.json`。
- **路徑 B（僅當你判定該 site 確為 non-claim diagnostic 且路徑 A 不合適）**：依 auditor 支援的機制走**正式 baseline adjudication**（`storage/ops/nested_dm_misuse_baseline.json` 的 `reviewed_nonnested`），寫明 site、理由、為何非巢狀 claim。**嚴禁**在 k1734.py 貼自我 marker 蒙混、嚴禁放寬 auditor 掃描面把別的 109 個真陽性一起消音。

## 完成 gate（全部要過才算完成）
1. `uv run --extra dev python -m pytest scripts/tests/test_nested_dm_misuse_ratchet.py -q` **PASS**（且未新增其他 baseline 破口）。
2. `experiments/k1734/K1734_results.json` 存在且內容自洽（H3 主結論仍由 Clark-West 支撐；若跑了 bootstrap，數字為實算、`seed=42`、標注 N / 期間）。
3. `README.md` 與 `review_verdict.json` 與最終 results.json 一致；誠實標註本次只改了 QLIKE 巢狀推論口徑，H1/H2/H3 結論強度不變（或如實記錄任何變動）。
4. 不得造假、不得過度宣稱；DM 若降級為 diagnostic 要在文中明講。

## 研究誠實原則（見 AGENTS.md，不可違反）
Lookahead 最高風險（`signal.shift(1)`）；固定 `seed=42`；null 如實報；區分實證/模擬；巢狀模型比較必用合法檢定。**agent 不寫 knowledge.json（K1259）** —— knowledge 由 main thread 於 collection 時寫。

## 交付
- `--result-artifact experiments/k1734/K1734_results.json`（runner 只驗存在）。
- 收件時的 followup：驗數字 + 確認 ratchet PASS + 寫 knowledge + merge worktree。
