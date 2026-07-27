Round-8 原阻塞文字已移除，兩個 gate 修補也確實生效；但改寫引入一個新的過度斷言，因此仍為 FAIL。

## Standards

阻塞 finding：

- [k1731_finalize_report.py:291](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_finalize_report.py:291) 宣稱 PIP「carries no information about out-of-sample predictive value」。這比證據允許的結論更強：PIP 不是 OOS 衡量或充分證據，但不能因此斷言它完全不含 OOS predictive value 的資訊。這正是本輪要求排除的 overcorrection。
- 該斷言已落入三份 artifact：[primary:71](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_gevreg_midas_ssvs_returns_results_corrected_rev5.json:71)、[corrected:71](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_gevreg_midas_ssvs_returns_results_corrected.json:71)、[original:56](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_gevreg_midas_ssvs_returns_results.json:56)，並由 [collection:57](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/K1731_ARMB_REV9_COLLECTION.md:57) 重述。

最小修正：改為例如「does not directly measure or by itself establish out-of-sample predictive value」，保留低 PIP 不能建立 OOS null 的結論；再由 finalizer 重建三份 JSON、同步 collection 並重建 freeze，不改任何數值。

## Spec

原 round-8 finding 的字面內容確已關閉：source 與三份 JSON 完全一致，舊兩個 claim 均不存在。驗證結果：

- Freeze 35/35 hashes 通過；HEAD 正確且 worktree clean。
- Verification：111/111，rev8 wording 負控偵測三個 banned phrases。
- Drift：numeric moved/added/removed = `0/0/0`；+1/−1 numeric leaf 負控均觸發 FAIL。
- Regression：3,834 leaves accounted，0 unexpected。
- 無 re-estimation 或 scope drift；三個 repo-level nested-DM 檔與 `f5338d54d` byte-identical。
- 非阻塞：drift checker 的 [頂層 docstring:19](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_rev8_drift_check.py:19) 仍錯稱只有 `numeric_moved` 會失敗，與實際 gate 不一致。

總結：Standards 1 個 blocking finding；Spec 0 個 blocking finding、1 個非阻塞文件瑕疵。

VERDICT: FAIL
