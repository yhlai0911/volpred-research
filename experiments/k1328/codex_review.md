# K1328 Codex Code Review

**Date**: 2026-06-14 13:18 台灣時間
**Reviewer**: Codex CLI 0.137.0 (ChatGPT auth, gpt-5.4 default)
**Verdict**: **FAIL**
**Triggered by**: hourly-13 dispatch fire (orphan recovery; codex_loop daemon 標 succeeded 但未跑 Codex review)

## Verdict

特徵 lag、seed、proxy 揭露皆合格；但 Stage B 未用同一 walk-forward cadence，且 HAR scheme 用同段 OOS 先挑再下結論，公平比較不成立。**`verdict=PASS` 不能寫入 knowledge.json**。

## Issues

1. **不對稱 refit cadence** (`k1328.py:194-197`)
   - HAR 用 `rolling_1000_refit_1d`（每日 refit）
   - ML challengers 固定 21-day refit
   - 違反「同 train window + 同 cadence」公平比較原則

2. **In-sample selection on OOS data** (`k1328.py:157-184`)
   - Stage A 在 `OOS 起點 2021-01-04` 之後的同一 OOS 期間選最佳 HAR scheme
   - Stage B 用「同段 OOS」宣稱 HAR ceiling supported
   - 等同對 OOS 做 in-sample selection — overstated ceiling claim

3. **Verdict / summary 不可採信**
   - results.json `verdict="PASS"` + `summary="ceiling supported"` 必須降級
   - 除非改成 matched refit 或 nested/holdout validation

## 後續 (K1328-v2)

派 v2 task 修正：
- (a) 改 matched refit cadence（HAR 與 ML 同 21d 或同 1d）
- (b) Stage A 在 burn-in / holdout 上選 best HAR，Stage B 才用獨立 OOS evaluate
- (c) Re-run 後再寫 knowledge.json

## 為什麼這次 review 是必要的

codex_loop daemon 跑完 K1328 但**沒跑** Codex code review（per `.claude/rules/experiments.md` 強制流程），直接 mark next_tasks `succeeded`。hourly-13 fire 補做這層 gate。Lesson: codex_loop daemon 派 K-experiment 後必須串 Codex review 才能 mark succeeded（記入 error_log）。
