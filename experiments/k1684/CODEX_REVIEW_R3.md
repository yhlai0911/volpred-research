# K1684 R3 primary Codex review

- Review date: 2026-07-12
- Reviewer: Codex primary path (`codex-vscode`)
- Verdict: **CONDITIONAL_PASS**
- Reviewed source SHA-256: `8060902100e81e7e7fd939e5e74ad7f75ff305027a450c50e0bad4418ceebf12`
- Reviewed result SHA-256: `ffffe2a735571160c67eae277a6ee0b66e7d8d8a3e2d7a7731aa0194f4a3e392`

## Disposition

R3 的 primary gate 與 null 結論可採信：**`H2_UNSUPPORTED`**。可將 null result 與方法論教訓寫入
knowledge；不可據此發 feed、改 paper narrative 或選 FRL / IJF 路線。下一個識別步驟仍是 E2：在同一市場
自己的 realized measure 上評分、`n >= 2500`，並補 cross-OOS 與 block-bootstrap sensitivity。

之所以是 `CONDITIONAL_PASS` 而不是無條件 PASS，是外部效度與部分非 gate 診斷仍有限：OOS 只有 450
個平靜期觀測、scale/Δc band 使用 iid resampling、`RGL` 是 reduced-form log-GARCH-X comparator 而非
完整 measurement-equation Realized GARCH。這些限制不改本次 null，但限制可說的話。

## Primary review findings

1. **共同支撐與 timing：PASS。** `_common_support(lo, hi, ...)` 使用 `[lo, hi)`，forecast origin `hi`
   不入池；HAR、GJR 與 return 必須同時 finite/positive。HAR/GJR theta 與 tail estimator 接到完全相同的
   index set。Primary 首日／末日共同 theta pool 是 985／1,426 筆；把 HAR 額外約 250 天保留反而會讓
   placebo 不對稱。
2. **Lookahead gate：PASS。** HAR、GJR、theta 與 tail 都只讀 origin 之前資料；30 個 perturbation
   assertions 全過。R3 另補 `path_end_ts` 必須與 RV row 同日，且 clock time ≤ 13:30；2,213 天的
   missing/date-mismatch/late counts 都是 0。
3. **權重命名：PASS。** `day_weighted_oos_mean` 是 450 個 held-constant OOS 日值的平均；
   `equal_weighted_mean_of_updates` 是 8 次 refresh 等權平均。Primary HAR 是 1.158867 / 1.161513，
   placebo 是 1.124409 / 1.123626；最後更新估計另列為 1.183562 / 1.117105，不混用口徑。
4. **Verdict isolation：PASS。** `GJRf-a+HistSim` 不被 `decide_gate()` 讀取；回歸測試把該 cell 的
   PASS/FAIL 翻轉後，完整 gate dict 逐值不變。Diagnostic runs 也明標 `gate_eligible=false`。
5. **Canonical risk tests：PASS after rescue。** Trinity 現為 Kupiec UC + Christoffersen CC joint +
   Basel 三者全過；Acerbi–Szekely Z1 是 canonical ES test，McNeil–Frey 只作補充。全 5 runs × 214 個
   alpha-cell records 的 Trinity 重新遍歷為 0 mismatch，Acerbi–Szekely 缺漏為 0。這兩項修正沒有翻動
   任何 VaR Trinity cell 或 `decide_gate()` verdict。
6. **R3 provenance：PASS after rescue。** JSON、README、figure title 與 receipt 均標 R3；R2 歷史 receipt
   恢復成真正 R2 hash `99e80e...`，R3 receipt 指向結果 hash `ffffe2...` 且逐位元吻合。

## Result verification

- Canonical rerun exit code 0，elapsed 83.1 秒；三份 pinned CSV 未被改寫。
- OOS `n=450`，2023-03-01 至 2024-12-31；aligned squared-return QLIKE 因 14 個零報酬日為 `n=436`。
- Aligned DM：`t=+1.476651, p=.140493, n=436`；TX-RV DM：`t=-2.096810, p=.036569, n=450`。
  兩者都未過 Harvey `|t|>3`，所以 leg 1 無法建立，`H2_UNSUPPORTED` 正確。
- 五個 run 的 verdict 全是 `H2_UNSUPPORTED`；rescue counts 的正確向量是：primary `0/3`、
  theta-short `1/2`、daily `0/3`、burnin `3/3`、legacy `0/3`。先前 work-log 的「五個 run 都 0/3」
  文字不正確；只有「五個 verdict 都是 H2_UNSUPPORTED」正確，本文件與 R3 README 取代該敘述。
- Primary HistSim scale-equivariance 最大差 `2.78e-17`；機械不變性成立。
- Fresh-context result auditor 對修正前核心 result packet 做 4,754 項獨立代數檢查為 0 errors；R3
  canonical-test additions 另由 post-rerun full-population traversal 與 regression tests 驗證。

## Conditions on use

- Knowledge 必須標成 null：`H2_UNSUPPORTED`，不是 `H2_REJECTED`，也不是模型等價證明。
- 不得以本實驗宣稱 HAR-RV 不如 GJR；HAR 的 TX-RV 與 0050 return 仍是 cross-asset target。
- GJR+CF 的 1% VaR Trinity PASS 不等於 ES PASS；Acerbi–Szekely Z1 在 1% 為 p=.0084（FAIL）。
- E2 必須採 own-market realized target、`n>=2500`、cross-OOS，並對 iid resampling 結果做 block-bootstrap
  sensitivity，完成前沒有 paper route。
