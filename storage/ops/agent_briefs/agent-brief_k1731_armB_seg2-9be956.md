# K1731 arm B — 段 2/2（bounded）：ES 修正的回歸檢查 + finalize + README 同步

**Model**: opus / xhigh (per model_router, task_type=experiment)
**Parent task**: `assign_1394a67a`（本班 owner: hourly-slot-1-79fea1ed6e8645819a3751ccdb37ce9d）
**Parent compute job**: `k1731-armB-corrected-rev5`（exit 0, completed 2026-07-18T18:35Z）
**Worktree / cwd**: `.claude/worktrees/dispatch-slot-1-bd00f90a-k1731`

## 你不必做的事（段 1 已完成，禁止重做）

corrected-spec production 重跑已由 compute_queue 完成，產出：

```
experiments/k1731/k1731_gevreg_midas_ssvs_returns_results_corrected_rev5.json   （179,830 bytes, 2026-07-19 02:35）
```

這是 rev5 ES 估計量（mixture ES，非 component-wise 平均）的完整 19-refit 結果。
**禁止**：整份重跑、開任何 heavy compute（GARCH MLE / bootstrap / 全期 backtest）、
force-remove worktree、把中斷的舊 log 當結果。你這一段全部是「讀既有 artifact + 跑既有輕量腳本 + 改文件」。

若你判斷真的需要新的 heavy compute 才能收尾 —— **不要自己跑**，寫進最後的 blocking_issues，
由後續 fire 走 `scripts/compute_queue.py enqueue`。

## 背景：為什麼要做這一段

`k1731_es_mixture_check_results.json` 已確立舊 ES 估計量是**系統性偏誤而非雜訊**
（MC 標準誤每 4 倍樣本乾淨減半，|old − mc| 固定在 2.12 不動 → 舊算法低估 ES 3.9%–22.8%）。
所以所有依賴 ES 的結論都必須用 rev5 重新檢視。

**特別注意**：README §3.1 那個 ES p=0.0145 的拒絕，**部分是舊 ES 估計量造成的假象**。
修正後 §3.5 的結論有實質翻轉的可能。**若翻轉就照實寫** —— 不得為了維持原結論而修飾措辭、
不得把「修正後不再顯著」寫成「證據較弱但方向一致」這類軟化。研究誠實 > 敘事一致性。

## 要做的四件事（依序）

### (1) 回歸檢查 — 這是 gate，FAIL 就停

```bash
uv run python experiments/k1731/k1731_regression_check.py
```

比對 `experiments/k1731/regression_baseline/` 下的 `_corrected.json` 基線。
判準：**只有 SSVS 的 ES 相關欄位可以變動**。allow-list 之外的任何漂移一律 FAIL。

- FAIL → **立即停止，不要繼續 (2)(3)(4)**。把漂移欄位、baseline 值、rev5 值、你的診斷寫進
  `k1731_armB_esfix.json` 的 `blocking_issues`，`verdict` 設 `regression_failed`，然後結束。
  漂移代表 rev5 改動的影響面超出預期，必須人工判斷，不得放行。
- PASS → 繼續。

### (2) finalize / provenance 蓋章 — 禁手改 JSON

```bash
uv run python experiments/k1731/k1731_finalize_report.py
```

（腳本無 provenance 會直接 SystemExit；這是設計，不要繞過。）預期效果：

- `k1731_gevreg_midas_ssvs_returns_results.json` → `superseded_by` + `do_not_cite`
- `k1731_gevreg_midas_ssvs_returns_results_corrected.json` → `superseded_by` + `do_not_cite`
- `..._corrected_rev5.json` → `is_primary: true`

這是 verification B2 的修正項。**一律透過腳本蓋章，禁止手動編輯任何 results JSON 的欄位。**
若腳本沒有正確蓋到三份，修腳本（並在產出裡說明改了什麼），不要手改資料。

### (3) 同步 `experiments/k1731/README.md` 的 §3.1 / §3.5 / §8 / §9 / §10

所有數字**逐一從 rev5 artifact 讀出**，不得沿用舊值、不得憑印象。每個改動的數字要能指到
rev5 JSON 的哪個 key path。

- **§3.1 Forecast accuracy**：更新受 ES 影響的數字；ES p=0.0145 若在 rev5 下改變，明確寫出
  「舊值 → 新值」與「這個拒絕原本部分來自 ES 估計量偏誤」。
- **§3.5 Coverage, DQ, and expected shortfall**：這一節是主要衝擊面。結論翻轉就照實改寫，
  並保留一句話說明是什麼造成翻轉（估計量修正，非資料或模型改變）。
- **§8 Files**：加入 rev5 artifact，並標示哪兩份已 `do_not_cite`。讀者要能一眼看出該引哪一份。
- **§9 Reproduction**：補 rev5 的重跑指令（含實際旗標，從 `run_corrected_rev5.log` 開頭反推，不要猜）。
- **§10 Review trail**：追加本次 ES 修正的條目（job id、日期、改了什麼、結論是否翻轉）。

風格照 README 現有調性（誠實、直述、不推銷）。不要新增行銷語言。

### (4) 產出 `experiments/k1731/k1731_armB_esfix.json`

**這是 result artifact，必須存在，否則 runner 判失敗。** 至少含：

```json
{
  "verdict": "ready_for_codex_review | regression_failed | blocked",
  "regression_check": {"status": "PASS|FAIL", "changed_fields": [], "out_of_allowlist": []},
  "finalize": {"is_primary": "<檔名>", "do_not_cite": ["<檔名>", "<檔名>"]},
  "es_impact": {
    "conclusion_flipped": true/false,
    "sections_changed": ["3.1", "3.5", "8", "9", "10"],
    "key_numbers": [{"what": "...", "old": ..., "new": ..., "json_path": "..."}]
  },
  "blocking_issues": [],
  "notes": "..."
}
```

## 成功判準

1. `k1731_regression_check.py` PASS（或 FAIL 但已如實記錄並停止）
2. 三份 results JSON 的 provenance 由腳本蓋章完成，rev5 是唯一 `is_primary`
3. README 五節數字全部可回溯到 rev5 artifact
4. `k1731_armB_esfix.json` 存在且欄位完整

## 不要做的事

- 不要 merge worktree（那是 `assign_67f56b79` 段 2 的事，且要先過 Codex 重審）
- 不要寫 knowledge.json（K1259：agent 禁寫 knowledge）
- 不要 commit（PHASE-Z 統一收）
- 不要發文章 / 動 feed
