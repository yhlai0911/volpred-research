## Freeze integrity

PASS。審查前後兩次驗證，7 個 frozen files 均符合 `k1698_rev5_freeze.txt`：

- `README.md` — `db9257b…22889`
- `k1698.py` — `8900bc9…88007`
- `k1698_results.json` — `a135639…7f54f`
- `run_log.txt` — `ce922e1…214`
- 三張圖 — `355ecef…f119`、`08c2f28…147c`、`7d20615…09093`

## Claim-by-claim

- PASS — headline verdict：README:16 對應 JSON `/GATE_VERDICT` 與 `/gate/verdict`，皆為 `H2_REJECTED`；route 亦一致。
- PASS — leg-1 gate：README:18–20 對應 `/gate/leg1_qlike/aligned_target_r2_0050`：`t_stat=1.4694`、`p_value=0.142442`、`n=436`、`better_model=GJR`、`feeds_gate=true`。
- PASS — OOS 樣本：README:101 對應 `/n_oos=450`、`/oos_stats/n=450`，期間為 `2023-03-01` 至 `2024-12-31`。
- PASS — own-target contrast：README:24–27 對應：
  - `/runs/bridge_old_rv/qlike_dm_tests/secondary_nonnested/rv_tx_aligned/HAR-RV_vs_GJR/t_stat=-5.2522`
  - `/runs/primary/qlike_dm_tests/secondary_nonnested/rv_tx_aligned/HAR-RV_vs_GJR/t_stat=-2.0642`
- PASS — scale factors：README:29–30 與兩個 run 的 `/correction_factors` 一致。Bridge 為 `1.353999 / 1.349112 / 1.203807`；primary 為 `1.202904 / 1.210913 / 1.074651`；placebo 兩者皆 `1.119105`。
- PASS — VaR、bootstrap、IS/OOS、sensitivity、robust-fit 表格：README §4 的數值可在 `/runs/*/var_results`、`/runs/primary/implied_scale_bootstrap`、`/insample`、`/gjr_robust_estimation` 與 `/k854_replication_bridge` 找到相應值。
- PASS — lookahead：`/lookahead_audit` 有 30 個 `_unchanged` assertions，全部為 `true`，且 `all_passed=true`。Code:1705 使用 `< i` 的估計池，1708–1710 僅擾動 `i:`；run_log:24–25 留有 `30 assertions | all_passed=True` receipt。
- PASS — gate 非循環：code:2137–2141 只把 `primary_nonnested/r2_0050/HAR-RV_vs_GJR` 傳入 gate；code:1598–1604 強制檢查 `nonnested`、`primary_gate`、`feeds_gate=true`。Own-target pair 是 `secondary`、`feeds_gate=false`。
- PASS — seed 與 atomic write：README seed 對應 JSON `/seed=20260712` 與 code:125；所有 RNG 使用固定 seed。Code:1773–1779 實作同目錄 tmp、JSON parse verification、`os.replace`。
- FAIL — README:32–34、189 宣稱 bridge「完全復現 K1684/K854 的世界」，但 JSON `/k854_replication_bridge` 明載 `n_matching=11`、`n_cells=14`、`match_rate=0.7857`。README:197 才正確承認 `11/14`；前述「完全復現」超出 telemetry。
- FAIL — README:22、215 的歷史 headline `t≈−5.6`、README:33 的 K1684 `−5.13`、README:52 的「倒置 154 個 CI」均不存在於 `k1698_results.json`。
- FAIL — README:254 的 TAIFEX `2,192` 檔來源數不存在於 results JSON；`/rv_construction/n_days=2191` 與 `/session_alignment_check/files_checked=40` 是不同量，不能作為該 claim 的證據。
- FAIL — README:265 宣稱首次建立 RV「約再 +1 分鐘」，但 JSON 只有 `/elapsed_sec=57.3`；run_log:9 僅證明 cache hit，run_log:234 僅記錄 `elapsed 57.3s`。沒有首次建檔 runtime receipt。

## Standing numerics

- `GATE_VERDICT = H2_REJECTED`
- Leg-1 aligned target：`t=1.4694`、`p=0.142442`、`n=436`
- `n_oos=450`
- Own-target：bridge `−5.2522`；primary `−2.0642`
- Aligned-target bridge：`+2.3118`
- Primary scale factors：`1.202904 / 1.210913 / 1.074651`
- Bridge scale factors：`1.353999 / 1.349112 / 1.203807`
- Placebo：`1.119105`

以上 headline numerics 均與 JSON 一致。

## 新問題

1. `COMPLETE-REPLICATION-OVERCLAIM`：categorical「完全復現」與 JSON 的 `11/14` 衝突。
2. `UNTRACED-HISTORICAL-NUMERICS`：`−5.6`、`−5.13`、`154` 無 results JSON 證據。
3. `UNTRACED-SOURCE-FILE-COUNT`：`2,192` 無 results JSON 證據。
4. `UNRECEIPTED-FIRST-BUILD-RUNTIME`：首次建 RV `+1 分鐘` 無 run-log receipt。

VERDICT: FAIL
