# K1633 Codex Review（primary path）— 2026-07-05

**整體 Verdict：CONDITIONAL_PASS**

沒有發現明確 lookahead 或主 lag0 baseline apples-to-oranges 的嚴重錯誤；核心 event 對齊、完整窗口過濾、HAC maxlags=H、de-cluster、seed 都正確。原本唯一硬傷是 Python code 未實作 12-cell 多重檢定校正 —— 本次修正後已內建。

| 檢查項 | 判定 | 評語 |
|---|---|---|
| 1. Lookahead / 未來函數 | PASS | `forward_returns()` 用 `SPY[e+H]/SPY[e]-1` 且 `e+H<n` 才保留（完整窗口）；lag1 用 `e=t+1` 無偷看未來。lag0「同收盤進場」為 same-close event study，已有 lag1 robustness。 |
| 2. Baseline 同口徑 | PASS | 主 lag0 baseline 用同一 SPY 序列、同 H、同 simple return。HAC 係數 = event vs non-event mean（數值差極小）。 |
| 3. 重疊窗口推論 | PASS | 主推論 HAC `maxlags=H` 正確（K1355）。bootstrap CI 為 event-order resampling（次要/診斷）→ 已於 `config.bootstrap_ci_note` 降級標示。 |
| 4. 多重檢定 | FAIL→FIXED | 原 code 只做 raw `hac_p<0.05`。**本次修正**：`benjamini_hochberg()` 內建，per-cell 輸出 `bh_qvalue`/`bh_fdr_5pct`/`bh_fdr_10pct` + `verdict.multiple_testing`。Codex 獨立重算 q 值與本檔完全吻合。 |
| 5. 去叢集 | PASS | 首次穿越 `(v[t]>=thr)&(v[t-1]<thr)` + 距上一 accepted event `>=20` 交易日，無重複計數。 |
| 6. Seed / 復現 | PASS | bootstrap/placebo/chart 皆固定或派生 seed（SEED=1629）。`python k1633.py` 重現 per_cell 逐位一致。 |
| 7. 小樣本 | PASS | README 明確揭露 VIX 35/40 事件數小（25/17），提醒不可挑漂亮 cell。 |

**修正落實（本次）**：
1. BH-FDR 內建於 `k1633.py`（must-fix #1）→ `verdict.multiple_testing`（FDR-5% 無存活；FDR-10% 3 存活：thr30_H5, thr35_H60, thr40_H60）。
2. README/JSON 一致（must-fix #2）→ README 指向 `verdict.multiple_testing`。
3. lag1 baseline 近似（#3）→ `config.lag1_baseline_note` 明示。
4. bootstrap CI 降級標示（#4）→ `config.bootstrap_ci_note` 明示主推論為 HAC。

**復現交叉驗證**：committed results 的 per_cell 與重跑逐位一致；BH q 值（0.0533/0.0533/0.0765/0.108…）與 Codex 獨立 Python 重算完全相同。
