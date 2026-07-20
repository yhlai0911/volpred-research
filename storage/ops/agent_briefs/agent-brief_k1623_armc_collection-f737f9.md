# K1623 arm C — 收件審查（collect_completed followup）

**Model**: opus / xhigh (per model_router, task_type=experiment)

## 你的角色

上游 compute job `compute-k1623-arm-c-mc-dm-hac-lag-gate-false-positive-1784574674`
已 **成功完成**（exit_code=0，2026-07-20 19:15→19:20 UTC，experiment_gate=passed）。
你是**收件人**，不是執行者：不要重跑 MC，不要重新設計實驗。
你的工作是**驗數字 → 改文字 → 留下可稽核的判定**。

**產出檔（唯一 success criterion）**：
`experiments/k1623/k1623_arm_c_collection_verdict.json`
（相對你的 cwd worktree；欄位規格見本文最後一節）

**工作根目錄**：`.claude/worktrees/dispatch-slot-2-c5cafe39-k1623/`
**本輪禁止 merge worktree**（round 3 PASS 才可）。

---

## 【0】本次為何是重跑 —— 先讀這段，不要重查一次

前一個 job `compute-k1623-arm-c-mc-mean-structure-generated-regressor-share-work-1784565527`
（2026-07-21 00:43 CST）**腳本本身完整跑完**（395.74s，stdout 有全部 5 資產結果，
`k1623_rev3_armc_results.json` 已寫出），exit=4 純粹敗在 post-run experiment gate：

    [dm-hac-lag] .../experiments/k1623/k1623.py::dm_hln (degenerate_at_h1)

這是 **false positive**：`experiments/k1623/k1623.py::dm_hln` 早已在
`storage/ops/dm_hac_lag_baseline.json` 的 degenerate_sites 凍結名單內，但當時 gate 用
worktree 前綴組 site key，與 baseline key 對不上。該 bug 已由 commit `5c0e9099d`
（`fix(gates): dm-hac-lag/fevd site key 依掃描根正規化`）修好，修後重掃同路徑已 PASS。

⚠️ 前一次（gate-fail）的產出已快照到 `/tmp/k1623_armc_gatefail_run_20260721.json`
   sha256=`94081a31cae51d91f6ad7e635365ba23c06ff8546712489e91898cfd8a4455e5`
   腳本位元未變、RNG 決定性 → 本次結果應與它**逐位元相同**。
   **不同就是 finding，要查根因，不要湊。** 若快照檔已不存在，記 `snapshot_missing`，不要當通過。

---

## 【1】先驗收 gate，不要先看結論

1. `jq '.per_asset[].reproduction_check_vs_frozen_rev2_mc.all_ok'`
   於 `experiments/k1623/k1623_rev3_armc_results.json` → 必須 **5/5 true**。
2. A−B 必須與凍結 `k1623_rev2_mc_results.json` 的
   `claim_corrections_rev3.corrected_attribution` **逐位元相同**：

   | asset | 期望值 |
   |---|---|
   | VIX | -0.01996200161917383 |
   | SPY | -0.045159482487136415 |
   | TW0050 | -0.05562014170297003 |
   | QQQ | -0.04110304364398498 |
   | N225 | -0.045546793733964475 |

3. 若 script 拋 `ReproductionFailure`：代表 numpy/scipy 版本或 OHLC cache 自凍結後漂移。
   **去查漂移，不要放寬 rtol**（reviewer 2 明確指示）。

---

## 【2】與 preview 對帳

`experiments/k1623/k1623_arm_c_decision.json` 的 `preview_numbers_not_citable` 記錄了一次
pre-fix 試跑值（由 review subagent 誤跑產生，已隔離、**不可引用**）。
排隊跑出來的數字**應該完全相同**（後續 fix 全是文字、無數值變更）。
**不同就是 finding，要查，不要湊。**

---

## 【3】更新 README 6.4 — 這次不是補一句，是要改結論

- 把 "DISCLOSED, NOT FIXED" 的 scope limit 換成實測 B−C；表格加 arm C 欄。
- **finding 2 必須改寫**（不是補充，是降級）：rev2 宣稱 SE 低估主因是 `1/(2 sqrt m)`
  漸近公式。加入 arm C 後，dominant sd factor 只有 **2/5** 資產是 `asymptotic_formula`
  （VIX、SPY），QQQ/N225 是 `mean_estimation`，TW0050 是 `break_location`。
  原宣稱**跨資產不成立** → 降級為 **asset-dependent**。
- B−C 只能寫成「相對 ELW 自身單一 grand-mean demeaning 的**增量**成本」，
  **不可**寫成「估計任何均值的成本」（arm C 不是 zero-mean oracle，ELW 內部仍減一個
  sample mean）。兩位 reviewer 都獨立指出 —— 這是 arm B 那次 retract 的同一類 overclaim。
  你寫完 README 後**自己回頭讀一次這段**，確認沒有再犯。

---

## 【4】`claim_corrections_rev3` 只准新增

凍結 JSON 已用 flatten-diff 驗證 0 改 0 移（181 keys）。要補 supersession 走 patch script
（比照 `k1623_rev3_patch_mc_artifact.py`），**禁止手改 JSON**。
注意 `k1623_rev2_mc.py` 現已有 `_guard_frozen_artifact()`，直接重跑會 fail-closed 擋下。

---

## 【5】收尾

- 重跑 `experiment_gates.py` verdict-template（新 results JSON 會改 claim surface，目前 30 pins）。
- **Codex primary-path 尚未審過**（usage limit 到 2026-07-25）。目前只有 agy PASS +
  code-reviewer subagent CONDITIONAL PASS 兩份 fallback。依 K1259 教訓，
  **Codex 額度恢復後必須重審，這是 round-3 放行的 blocking 前提** —— 在 verdict JSON
  裡把這條記成 `blocking_open_items`，不要讓它消失。
- 另有一個 process gap：review subagent 執行了它被指派審查的實驗碼（違反先審後跑）。
  記進 `docs/error_log.md`（worktree 內），並在 verdict JSON 註記建議強化 review brief template。

---

## 誠信硬規則

- **禁止寫 knowledge.json**（K1259 教訓 —— agent 不寫 knowledge）。
- **禁止假數字**：任何你沒親眼從 artifact 讀到的數，不准寫進 README 或 verdict。
- 驗不過就記 `FAIL` + 根因，**不要放寬門檻讓它過**。研究誠實 > 交差。
- 你只能在自己的 worktree 內寫檔，禁止碰 main checkout。

---

## 產出規格 — `experiments/k1623/k1623_arm_c_collection_verdict.json`

```json
{
  "job_id": "compute-k1623-arm-c-mc-dm-hac-lag-gate-false-positive-1784574674",
  "collected_at": "<ISO8601>",
  "verdict": "PASS | FAIL",
  "reproduction_check": {"all_ok_count": 0, "expected": 5, "detail": "..."},
  "bitwise_vs_frozen_rev2": {"ok": true, "per_asset": {"VIX": {"expected": 0, "actual": 0, "match": true}}},
  "bitwise_vs_gatefail_snapshot": {"ok": true, "snapshot_found": true, "detail": "..."},
  "preview_reconciliation": {"ok": true, "detail": "..."},
  "finding2_rewrite": {
    "done": true,
    "dominant_sd_factor_by_asset": {"VIX": "asymptotic_formula"},
    "downgraded_to": "asset-dependent"
  },
  "bc_wording_check": {"phrased_as_incremental_vs_elw_grand_mean": true, "quote": "<README 實際句子>"},
  "readme_6_4_updated": true,
  "experiment_gates_rerun": {"status": "passed|failed", "pins": 0},
  "blocking_open_items": ["codex_primary_path_review_pending_until_2026-07-25"],
  "findings": ["..."],
  "files_changed": ["..."]
}
```

最後 return 一段 ≤200 字的純文字摘要：verdict、幾項驗證通過/失敗、README 改了什麼、
還剩什麼 blocking。這段是回傳值，不是給人看的訊息。
