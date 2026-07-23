Round 4 結論為 **FAIL**。九個 frozen hashes 在審查前後均吻合；研究結果與 round-3 的主要 claim-surface 缺陷都已修好，但 remediation/runtime 文件新引入兩個可驗證的證據陳述錯誤。依「任何 surviving claim–evidence gap 即 FAIL」規則，不能 PASS。

## 逐項裁決

- **CRITICAL-1: PASS** — PRIMARY JSON 的 `margin_disclosure`、`limitations` 與 q1/q2 `delta_definition` 都改為 `0.1 × [mean QLIKE(uncond) − mean QLIKE(GJR)]`。生成器以同一 aligned mask 計算 loss difference；+1 shift 重新計算 basis、TOST p-value 與 verdict，結果 `0.868961 → 0.868961`、`false → false`，且 [`main()`](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/k1698.py:3028) 在 invariance 移動時會 `raise`。

- **CRITICAL-1-residual: PASS** — 所有 rendered margin 字串都以方括號明確包住完整 loss difference；PRIMARY JSON 中 `0.1 x mean QLIKE` 為 0 hit。加括號足以消除運算優先序歧義，且比重新另造 basis 文案更不易漂移。

- **MAJOR-2: PASS** — README 的現行數值全部是 2 天，並列出 `2017-01-18`、`2017-02-15`，與 JSON 的 `n_days_selection_changed_by_the_leak=2` 及 §2 一致。README 唯一的「3 天」在第 78 行，是「由 3 天更正為 2 天」的歷史說明，不是存續中的三天宣稱。

- **MAJOR-4: PASS** — JSON `honest_reading` 已降為 `DESCRIPTIVELY`，並同時攜帶 bandwidth 翻面、`POST_HOC`、未做 multiplicity correction 三項 caveat。q2 object 的 parent `PREREGISTRATION_STATUS` 和 `preregistration_note` 明確涵蓋其 `dm`、lag sensitivity 與 nested equivalence；全域 limitation 又再次封住泛用 `passes_preregistered...=true` 欄位的誤讀。沒有獨立的 q2 結果宣稱脫離 caveat。

- **MAJOR-5: PASS** — q1 equivalence、q2 parent、`rv_ablation` 均有 `PREREGISTRATION_STATUS: POST_HOC`；`limitations[0]` 明列 equivalence、q2、DM lag grids、ablation 及未做多重檢定。nested q2 equivalence 是同一 q2 comparison 的子區塊，繼承 parent flag 足夠，尤其全域 limitation 亦明確適用於每個 rev2 comparison。

- **MINOR-6: PASS** — README 與 PRIMARY JSON 一致報告 `delta_min=0.224194`、basis 的 `89.98%`，且 0.02/0.05/0.10/0.20/0.50 五格全部 `equivalent_at_5pct=false`。舊 `~14%` 與 `below 20%` 在 PRIMARY JSON 都是 0 hit。

- **STILL-OPEN-7: PASS** — 撤回從未存在的 `review_receipt_rev2.json`，比事後製造 receipt 誠實；三個具名 round-3 review artifacts 均實際存在。`review_verdict.json` 的 enforcing schema 與 `verdict_template()` 相符，所有頂層、逐 finding 與 overall verdict 欄位仍為 literal `FILL: pending Codex round 4`，沒有 self-signing。

- **NEW-MAJOR-stale-generated-claim-assembly: PASS** — 生成器從 q1/q2 objects 取得 threshold、percentage、grid maximum、q2 t/p 與 lag range；完整 rerun 已把結果寫入 PRIMARY JSON。五個指定舊字串在 PRIMARY JSON 全為 0 hit。相對 round-3 artifact，排除 `elapsed_sec` 後，所有 numeric JSON paths 的 digest 完全一致；沒有 substantive number 移動。

- **NEW-MINOR-runtime-doc-drift: FAIL** — frozen run 的 `370.6s` 與 PRIMARY JSON、[`run_log_rev4.txt`](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/run_log_rev4.txt:280) 一致，`288.8s` 也有完整 rev2 receipt；但 README 將 `286.6s` 歸因於「較空載」，remediation 更直接稱它是 receipt。實際 [`run_log_rev3.txt`](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/run_log_rev3.txt:12) 只有 14 行、停在 `parsed 800/2192`，沒有 completion/elapsed，並以 semaphore warning 結束；remediation 自己第 117 行也承認它不是 receipt。Frozen bytes 亦沒有 load telemetry，可支持「較空載」的因果歸因或獨立驗證該次 numeric output。

## Standing checks

- `GATE_VERDICT=H2_REJECTED` 與 FRL / Journal of Forecasting short-note route 均清楚限定：只證明沒有 qualifying HAR win；HAR 勝出及 HAR/GJR equivalence 都未建立。
- t=`1.4694`、n=`436`、p_TOST=`0.868961`、delta_min=`0.224194` 等 substantive numerics，相對 round-3 artifact 全數未動。
- 除上述未受 receipt 支持的 `286.6s`／「較空載」外，未發現 rev3 所觸及 README 數值與 PRIMARY JSON 不一致。

## 新問題

- **NEW-MINOR-AUDIT-RECORD: FAIL** — [`k1698_rev3_remediation.json`](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-2-c5cafe39-k1698/experiments/k1698/k1698_rev3_remediation.json:42) 宣稱 `grep -c '3 天' README.md == 0`，實際為 1。該 README hit 是誠實的歷史更正，因此不重開 MAJOR-2；但 remediation 的 evidence 欄本身不符合 bytes。
- **NEW-MINOR-RUNTIME-EVIDENCE: FAIL** — remediation 第 103 行稱 `286.6s` 是 receipt，卻在第 117 行承認 on-disk log 是無 completion line 的 truncated stub。應刪除該 receipt 宣稱與未受 telemetry 支持的「較空載」歸因；可保留已驗證的 `370.6s`、`288.8s`，並寫成「原因未記錄的 wall-clock variation」。

VERDICT: FAIL
