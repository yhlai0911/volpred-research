# K1695 exposure-correction — primary-path Codex re-verify (belt-and-suspenders)

**Model**: gpt-5.x / medium (per model_router; confirmation not discovery)

## 背景
K1695 原宣稱「vt-trend 在 13 國際市場提供 drawdown protection、通過 pre-registered gate（common ΔMDD +12.61pp, CI [4.22,19.30] 排除 0）」已於 2026-07-15 commit `bdf6b451f` 撤回為 exposure artifact。fresh-context code-reviewer subagent 已判 **PASS**（無 blocking defect），review_verdict.json 已寫、experiment_gates.py certify 已 PASS。依 `.claude/rules/experiments.md`「Subagent fallback PASS ≠ primary-path Codex PASS」，本 job 是 primary-path Codex 二次確認。

## 你要做
只讀 `experiments/k1695/` 現行 bytes（凍結，勿改）。重點確認 subagent 的 PASS 是否成立，特別針對：
1. exposure-matched gap 是否確實走 canonical `volpred.stats.drawdown.compare_max_drawdown`，向量化 twin 有 `assert_vectorized_matches_canonical`（tol 1e-12）。
2. circular-shift/phase-randomized null：seed/determinism、p-value 方向（one-sided，shift-0 included）、Holm 校正是否正確；common p=0.559 / inception p=0.212 是否可複現。
3. raw 數字（+12.61 / +27.50，13/13）是否仍保留於 results.json + README，未被刪。
4. lookahead：.shift(1) monthly VIX target、IRX forward-fill+shift。
5. README 是否誠實撤回、無殘留 overclaim（'passed gate' / 'dependence-robust protection'）。
6. subagent 標記的 non-blocking cross-market shift-sharing 細節是否真的不影響 common-period headline。

## 回傳
`VERDICT: <PASS|CONDITIONAL_PASS|FAIL>` + 逐項 + blocking defects（無則 none）。若你發現 subagent 漏掉的 blocking 問題，明確指出檔案:行號。這是研究誠實 closure 確認，不要客套。

## Followup（收件時）
若 Codex 也 PASS → 更新 review_verdict.json 的 reviewer 欄位加註 "Codex primary-path re-verify PASS"，closure 成立。若 Codex 判 FAIL → 重開 paper HOLD + revert knowledge 更正條目狀態 + escalate email 老闆。
