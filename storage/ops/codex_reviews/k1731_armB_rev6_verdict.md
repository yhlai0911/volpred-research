VERDICT: FAIL

所有 11 個 frozen files 的 SHA-256 均與 manifest 相符。本次 FAIL 來自目前 bytes，而非沿用 round 5 裁決。

## B1 — FAIL

檢查了 arm B 與 arm A 的模型建構、估計視窗、DM 路徑，以及 README／primary JSON 的所有相關宣稱。

實質推導正確：

- arm B 的 GEV-HAR 由 macro coefficient mask 歸零建立；它是較大 GEVReg 模型類別的限制模型。[estimation source:163](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_gevreg_midas_ssvs_returns.py:163)
- `est = block_end < refit_date` 是 expanding window，不是固定長度 rolling window。[estimation source:129](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_gevreg_midas_ssvs_returns.py:129)
- raw DM 路徑只加 HAC；HAC 處理序列相關，無法解除 nested-null 下 loss differential 的退化。這與 [West (1996)](https://users.ssc.wisc.edu/~bhansen/718/West1996.pdf)、[Clark–McCracken (2001)](https://www.sciencedirect.com/science/article/abs/pii/S0304407601000719) 一致。
- [Giacomini–White (2006)](https://onlinelibrary.wiley.com/doi/pdf/10.1111%2Fj.1468-0262.2006.00718.x) 的 fixed-memory 架構不適用這個 expanding-window 設計。SSVS shrinkage 可能減輕 forecast-noise bias，但不恢復 raw statistic 的標準常態極限。
- arm A 使用相同 mask、expanding window 與 raw DM，因此 `t=+2.13` 屬同一缺陷類；且來自 quick mode。

但撤回不完整：

- §3.2 標題仍是 **“bounds, not just p-values”**。[README:188](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:188)
- 表格仍把 nested row 標成 **“95% CI”**，並以粗體呈現 `[−0.74,+4.41]`；既然該 statistic 沒有主張的常態極限，就不能再稱為有效的 95% CI。[README:195](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:195)
- PRIMARY artifact 的 `cross_arm_comparison.what_cannot_be_said` 仍稱 arm A「demonstrably does not」改善預測，`correct_reading` 又將兩臂寫成已證明的 OOS null，沒有 nested-DM caveat。[primary JSON:5252](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_gevreg_midas_ssvs_returns_results_corrected_rev5.json:5252)

因此 B1 不是完整 retraction，而是 README prose 多數修正、表格與 primary narrative 仍漏出舊推論。

## B2 — PASS

受審 bytes 中，`3,776/3776` 只出現在 changelog、自我報告、checker 註解與 negative-control 說明；沒有殘留為現行 README claim。正文兩處均為 3,834，與 gate 的 `n_leaf_values_compared=3834` 相符。

Checker 已新增 gate 與 ES proof sources，輸出包含 69 rows、66 `OK`、3 `PRESENT`，其中 gate leaf count、unexpected count 與 candidate path 均實際解析成功。[verification source:20](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_armB_verification.py:20)

## B3 — PASS

README 的五日 block 值逐欄吻合 rev5：

- GARCH-t：0.1332507626 → 0.13325
- SSVS：0.1422545683 → 0.14225
- Empirical：0.1655885629 → 0.16559

README 明確指定 `oos.robustness_full_weeks_only.by_model.*.mean_pinball` 為來源，舊值只留在歷史說明。[README:399](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:399)

## B4 — PASS

實際程式路徑與改寫後 §4 一致：

- `lag=0` 以 origin 當日收盤後的 GARCH state 預測下一交易日。
- `lag=1` 退回前一交易日的 state，再模擬並排除一個 skipped day，故不使用 origin 當日已實現報酬。[estimation source:208](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_gevreg_midas_ssvs_returns.py:208)
- rev5 specification 的值為 `garch_origin_lag_trading_days=1`。

§4 現在正確區分 unadjusted origin-day lookup 與 rev5 實際採用的 lag-one state。[README:420](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:420)

## B5 — FAIL

README 主體已明確列出三項未控制差異：macro set、GARCH information set、estimation mode，因此主要 attribution 已縮窄。[README:101](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:101)

但 frozen estimation source 的 module claim 仍稱 arm B **“holds the entire engine fixed”**，與上述三項差異直接衝突。[estimation source:4](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_gevreg_midas_ssvs_returns.py:4) 這是舊 attribution 以較弱措辭殘留，故 B5 未完全修復。

另 README 所謂「six things」與其自然列舉數量也不一致；建議移除硬編號，直接說「enumerated shared constructs」。

## B6 — PASS

`hash(name)` 已完全替換為 SHA-256 前四 bytes、模 10,000 的穩定 offset。[ES proof:59](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_es_mixture_check.py:59)

我獨立重建 `posterior_like`：

- offset = 2407
- effective seed = 20263125
- 0.95 與 0.99 的 mixture threshold、new ES、old component-average ES 均與 results JSON bit-identical。

README 也正確將 4.4%–22.8% 限定為四個 constructed scenarios 的 span，而非 worst case。[README:350](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:350)

## B7 — PASS

§8 現在只聲稱三個 production artifacts 具有 embedded provenance，並明說 quickmode artifact 沒有 provenance field。[README:611](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:611)

§10 正確記錄五個 Codex rounds，Round 1–5 均有 disposition。[README:686](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:686)

## Added finding — nested-DM detector — CONFIRMED, BLOCKING

我直接執行 detector channels：

- explicit nested regex：0
- base/augmented prose：0
- nested AST：0
- raw-DM AST：3
- `scan_file(...)`：`None`

根因正如 rev6 所述：AST detector 只辨識 paired identifiers／subset construction，沒有 coefficient-slice-zero mask channel；沒有 nesting evidence 時，`scan_file` 在 raw-DM 分類前直接 return。[detector:204](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/scripts/audit_nested_dm_misuse.py:204), [detector:2553](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/scripts/audit_nested_dm_misuse.py:2553)

所以 K1731 的 gate PASS 是 false negative，不能清除 B1。193-site baseline 已確定至少少算 K1731 一處；其他 mask-based sites 的漏算數仍未知。

## Added finding — arm A quick mode — PASS ON DISCLOSURE

所有 surviving README cross-arm claims 均受到 §3.3b 的 local caveat，以及 §7b「every arm A number here comes from quick mode」的全域 caveat約束。[README:294](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:294), [README:598](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:598)

沒有未揭露 quick-mode provenance 的 README claim。其 nested-DM inference 問題則已在 B1 判 FAIL。

## Structural check 1 — no estimated number moved — PASS

Round-5 與 rev6 freeze 的 SHA-256 對下列四項完全相同：

- PRIMARY rev5 artifact
- estimation script
- models module
- scoring module

Regression-results JSON 的 hash 亦未變。故 Git 將 rev5/rev6 包在同一 commit 的歷史形狀，不代表 rev6 改動了 round-5 reviewed bytes。

Allow-list 的 production exceptions只有兩個 SSVS ES subtrees及 threshold-consistency；`FINALIZE_OWNED_KEYS` 則都是 finalizer 明確寫入的頂層 provenance、audit、derived narrative 與 timestamps。[regression gate:35](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_regression_check.py:35) 底層 `refits[]`、PIP、loss、DM、GARCH 與其餘 `oos.*` 不在 allow-list，因此目前這個 coupling 無法吞掉 production-estimate drift。

## Structural check 2 — traceability negative control — PASS

我不是讀取 self-report flag，而是實際把 checker 的 `gate_leaf_count` expected value 注入為 3776，再執行同一 artifact-resolution 與 comparison path。結果為：

```text
checked_n = 69
problems  = 1
[MISMATCH] gate_leaf_count readme=3776 artifact=3834
```

Negative control 確實穿過 checker，而非手設布林值。

## Structural check 3 — provenance invariant — PASS

直接掃描 JSON objects：

- 恰好一個 artifact 有 `is_primary=true`，且 `do_not_cite=false`。
- 兩個 superseded production artifacts 均有 `is_primary=false`、`do_not_cite=true`、`superseded_by` 與非空 `superseded_reason`。
- quickmode artifact沒有這些 fields，與 README 的限定敘述一致。

## Structural check 4 — earlier fixes — PASS

Round-1 至 Round-4 的 dispositions 都仍在 §10；Round 5 已完整追加。Round-5 freeze 顯示 estimation、model、scoring、primary artifact 與 regression gate bytes沒有 rev6 drift。

PRIMARY artifact 中未修正的 cross-arm nested-DM prose 是 B1 未完成 remediation，不是先前已通過項目遭重新破壞。

## Blocking issues

- [README.md:188](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:188) 與 [README.md:195](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/README.md:195)：§3.2 仍稱 “bounds”，表格仍標有效的 “95% CI”。改成「naive HAC diagnostic interval／不具 95% coverage 保證」，並移除所有 bound/CI 推論措辭。
- [primary JSON `cross_arm_comparison`:5252](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_gevreg_midas_ssvs_returns_results_corrected_rev5.json:5252)：仍有 “demonstrably does not” 與無 caveat 的雙臂 OOS 推論。修正 canonical generator `k1731_finalize_report.py`，將 arm A raw DM 降為 diagnostic direction、加入 nested/expanding/quick-mode caveats，再由 finalizer 重生 artifact；不要手改 JSON。
- [k1731_gevreg_midas_ssvs_returns.py:4](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/experiments/k1731/k1731_gevreg_midas_ssvs_returns.py:4)：`holds the entire engine fixed` 與已揭露的 macro-set、GARCH-lag、mode 差異衝突。改成「reuses the same model implementation while these settings differ」，並同步修正 README 的 “six things” 計數。
- [audit_nested_dm_misuse.py:204](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-bd00f90a-k1731/scripts/audit_nested_dm_misuse.py:204)：新增 coefficient-mask nesting AST channel，至少涵蓋「slice 指派為零後以 restriction/active argument 傳入 fit」；加 positive/negative tests、重新掃描 repo 並更新 frozen baseline。K1731 必須不再得到 false-negative clearance。
