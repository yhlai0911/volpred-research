# PASS

frozen commit `22cac8786720c9da4acbf783f644033843842977` 已關閉上一輪 blocker：

- `model_input_availability` 僅使用 HAR lagged rolling features、EWMA lagged return count、GJR `start:origin` 歷史報酬。[K1704.py](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/k1704/K1704.py:459)
- Eligibility 由 input masks 決定；input available 但 raw forecast 無效會立即 `RuntimeError`。各模型 audit 保存 unavailable indices、count、SHA-256。[K1704.py](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/k1704/K1704.py:661)
- Eligibility 在所有 `calibrate_forecasts_to_target` 呼叫前建立；六 targets、三 models 最終共用同一 `common_mask`。[K1704.py](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/k1704/K1704.py:889)
- 測試涵蓋 `rv_5min[107]` 缺失造成 HAR rolling mask 排除 22 個 origins、input-available/raw-NaN fail closed，以及 eligibility 內 calibrated gap fail closed。[test_K1704.py](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-f217aefb-k1704/experiments/k1704/test_K1704.py:99)
- 新增 mask 全部僅讀取 `t-1` 或更早資料，未發現新增 lookahead。

pytest 因唯讀環境無 writable temp／Matplotlib cache 而無法 collection；這不是測試失敗。審查採 frozen Git objects，未讀取或驗證既有 `K1704_results.json`。

本 PASS 僅授權使用「本輪剛從 raw 重建，且完成 raw-byte size/SHA-256 verification」的 cache 重跑；不授權沿用舊 cache 或舊 results。
